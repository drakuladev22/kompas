"""Sübut şəkillərinin asinxron yüklənmə növbəsi — Faza 3.9.

Tələb: *"Cərimə yaradılan an Drive-a yükləmə GÖZLƏNİLMİR — cərimə qeydi
DƏRHAL yazılır, şəkil isə arxa planda, retry ilə yüklənir."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA NÖVBƏ, `OfflineBuffer` DEYİL
──────────────────────────────────────────────────────────────────────────────
`OfflineBuffer` (Faza 3.5) DB SƏTİRLƏRİNİN outbox-udur: payload JSON-dur və
şifrələnib SQLite sütununda saxlanılır. Şəkil isə megabaytlarla ikili
məlumatdır — onu JSON-a bazalayıb SQLite sütununa yazmaq faylı ~33% şişirdər
və hər oxunuşda bütün sətri yaddaşa gətirərdi.

Ona görə eyni PATTERN (SQLite indeks + eksponensial backoff + status), lakin
baytlar diskdə ayrıca spool faylında saxlanılır. Backoff cədvəli də eynidir
(30s → 2dq → 10dq) — iki fərqli gözləmə davranışı olsaydı, nasazlıq zamanı
sistemin nə vaxt təkrar cəhd edəcəyini proqnozlaşdırmaq çətinləşərdi.

──────────────────────────────────────────────────────────────────────────────
KVOTA DOLDUQDA
──────────────────────────────────────────────────────────────────────────────
Yükləmə uğursuz olur, lakin CƏRİMƏ YARADILMASI bloklanmır — element
növbədə qalır və admin yeni Drive qoşandan sonra avtomatik yüklənir.

──────────────────────────────────────────────────────────────────────────────
İKİ FƏRQLİ UĞURSUZLUQ: MÜVƏQQƏTİ vs DAİMİ
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı qayda (şəbəkə/kvota → gözlə və təkrar cəhd et) YALNIZ müvəqqəti
nasazlığa aiddir. Faylın ÖZÜ yararsızdırsa — 5 MB-dan böyük, `.exe` uzantılı
və ya məzmunu şəkil olmayan — heç bir gözləmə nəticəni dəyişmir. Belə element
əvvəllər `FAILED`-ə düşüb hər 10 dəqiqədən bir eyni cavabla rədd edilirdi:
sonsuz dövrə, dolan disk və heç kimin oxumadığı jurnal sətirləri.

Ona görə iki qat əlavə olundu:

    1. `enqueue()` faylı DİSKƏ YAZMAZDAN ƏVVƏL `validate_evidence_payload()`
       çağırır — yararsız fayl növbəyə ümumiyyətlə düşmür və operator səbəbi
       DƏRHAL ekranda görür (`controllers/fine_entry.py`).
    2. Artıq növbədə olan (köhnə versiyadan qalmış və ya tenant həddi
       sonradan aşağı salınmış) element yükləmə anında `REJECTED` statusuna
       keçir — `PENDING` seçimindən çıxır, yəni dövrə qırılır.

Bu, Drive əlçatmazlığı davranışına TOXUNMUR: şəbəkə xətası əvvəlki kimi
`FAILED` + backoff yolundadır və cərimə hər halda normal yaranır.

──────────────────────────────────────────────────────────────────────────────
NÖVBƏ ELEMENTİ "CLAIM" EDİLİR (yarış vəziyyəti)
──────────────────────────────────────────────────────────────────────────────
`pending()` sadəcə OXUYURDU. İki işçi (məs. kiosk prosesi + admin paneli, və
ya proqramın iki nüsxəsi) eyni anda işə düşəndə hər ikisi EYNİ sətri görür və
eyni şəkli Drive-a İKİ dəfə yükləyirdi: yetim fayl, boşuna sərf olunan kvota
və `fines` sətrində hansı `file_id`-nin qaldığı təsadüfə bağlı.

Ona görə seçim artıq atomikdir: `claim_pending()` `BEGIN IMMEDIATE` daxilində
sətri `PROCESSING` statusuna keçirir. `PROCESSING` `PENDING` seçimindən
çıxdığı üçün ikinci işçi həmin elementi ÜMUMİYYƏTLƏ görmür.

ÇÖKMƏ HALI: proses `PROCESSING`-də dayanarsa element əbədi ilişməməlidir.
`claim` anında `next_attempt_at` "köhnəlmə anı"na (defolt +10 dəq.) təyin
olunur; həmin an keçdikdən sonra element yenidən claim edilə bilir. Yəni
ilişmə müddəti MƏHDUDDUR və heç bir əl müdaxiləsi tələb etmir.

──────────────────────────────────────────────────────────────────────────────
SAHİB CƏDVƏLİN ÜMUMİLƏŞDİRİLMƏSİ: `fine_id` → `owner_type` + `owner_id` (#17)
──────────────────────────────────────────────────────────────────────────────
Növbə əvvəllər YALNIZ cərimə sübutu üçün mövcud idi (`fine_id TEXT NOT NULL`).
İşçi sənədi skanı (`EmployeeDocumentUseCase.attach_file`) ÜÇÜN AYRICA ikinci
SQLite spool qurmaq bu faylın başlığındakı "eyni PATTERN, iki nüsxə YOX"
prinsipini pozardı — həm claim/backoff/köhnəlmə məntiqini, həm də miqrasiya
tarixçəsini ikiqat saxlamaq lazım gələrdi. Ona görə `fine_id` YERİNƏ ümumi
`owner_type` (`UploadOwnerType`) + `owner_id` (mətn) cütü gəldi.

`fine_id` sütunu FİZİKİ SİLİNMİR: köhnə buraxılışa geri dönüş zamanı (`.exe`
downgrade) həmin versiya yalnız bu sütunu tanıyır və gözləyən cərimə şəkli
onsuz "yetim" görünərdi. Yeni yazılarda sütun BOŞ QALMIR — `owner_id`-nin EYNİ
dəyəri yazılır (FINE sətirləri üçün bu, əvvəlki davranışla BİREBİRDİR;
EMPLOYEE_DOCUMENT sətirləri üçün sütun mənasız olsa da, `NOT NULL`
məhdudiyyətini pozmadan sıfır əlavə informasiya itkisi ilə dolur — sütunun
CHECK/FK-i olmadığı üçün bu, DB səviyyəsində zərərsizdir).

Sahib tipi YALNIZ hədəf cədvəli seçmir — İCAZƏLİ FORMATI da o seçir: cərimə
sübutu yalnız şəkil, işçi sənədi isə şəkil + PDF qəbul edir (SEC-018, qayda
`google_drive.allowed_extensions_for`-dadır). Ona görə `owner_type` həm
`enqueue()`-dakı ön-yoxlamaya, həm də `provider.upload()`-a ötürülür — iki
qatın eyni cavabı verməsi bu faylın əsas şərtidir (yuxarıya bax).

Köhnə (yalnız `fine_id` bilən) SQLite faylı `_ensure_owner_columns()` ilə
köçürülür — `_ensure_rejected_status`/`_ensure_processing_status` ilə EYNİ
idempotentlik prinsipi, lakin FƏRQLİ mexanizm: `status`-un `CHECK`
siyahısından fərqli olaraq `owner_type`/`owner_id`-də `CHECK` YOXDUR (validasiya
Python səviyyəsində, `UploadOwnerType` enum-u ilə), ona görə SQLite-ın
dəstəklədiyi sadə `ALTER TABLE ... ADD COLUMN` kifayətdir — bütöv cədvəli
yenidən qurmaq (rename + copy) YERSİZ RİSK olardı.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.domain.policies import SystemLimitKey
from src.infrastructure.config.limits import InfrastructureLimits, fallback_int
from src.infrastructure.storage.google_drive import (
    MAX_UPLOAD_BYTES,
    EvidenceValidationError,
    validate_evidence_payload,
)
from src.shared.exceptions import DecryptionError, EncryptionKeyError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import StoreId
    from src.domain.value_objects.storage import StorageReference
    from src.infrastructure.security.encryption import EncryptionService

_log = get_logger(__name__)

_TABLE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS evidence_uploads (
    id              TEXT PRIMARY KEY,
    seq             INTEGER NOT NULL,
    tenant_id       TEXT NOT NULL,
    fine_id         TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    filename        TEXT NOT NULL,
    spool_path      TEXT NOT NULL,
    taken_at        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING', 'PROCESSING', 'UPLOADED',
                                          'FAILED', 'REJECTED')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    queued_at       TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    uploaded_at     TEXT,
    drive_file_id   TEXT,
    connection_id   TEXT,
    -- `owner_type`/`owner_id` (#17, Faza 7) — `fine_id`-in ÜMUMİLƏŞDİRİLMİŞ
    -- davamı. CHECK QƏSDƏN YOXDUR (bax modul başlığı): validasiya `enqueue()`-
    -- dəki `UploadOwnerType` enum-undadır, köhnə fayl köçürməsi isə YALNIZ
    -- sadə `ALTER TABLE ADD COLUMN`-la işləməlidir (bax `_ensure_owner_columns`).
    owner_type      TEXT,
    owner_id        TEXT
);
"""
_INDEX_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_evidence_ready
    ON evidence_uploads (status, next_attempt_at, seq);
"""
_SCHEMA: Final[str] = _TABLE_SQL + _INDEX_SQL


def _spool_context(entry_id: str) -> str:
    """Şifrələmə AAD-i — SEC-4.

    Sətrin ÖZ `entry_id`-sinə bağlanır (`telegram_config:{tenant_id}` ilə
    EYNİ naxış, `telegram_repositories.py`): şifrələnmiş spool faylı BAŞQA
    bir sətrin altına köçürülsə (disk faylına birbaşa çıxışı olan hücumçu
    üçün nəzəri mümkün əməliyyat), deşifrə mərhələsində uğursuz olur.
    `enqueue()` (yazır) və `read_plaintext()` (oxuyur) EYNİ funksiyanı
    çağırır — iki ayrı yerdə TƏKRARLANAN sətir AAD uyğunsuzluğu riski
    yaradardı (bax `telegram_repositories.py` başlığındakı xəbərdarlıq).
    """
    return f"evidence_upload:{entry_id}"


#: Cədvəl köçürməsində (bax `_ensure_rejected_status`) sütunlar AÇIQ sadalanır:
#: `INSERT INTO ... SELECT *` sütun sırasından asılıdır və gələcəkdə əlavə
#: olunacaq bir sütun köçürməni sükutla təhrif edərdi.
#:
#: `owner_type`/`owner_id` QƏSDƏN SİYAHIDA YOXDUR: bu köçürmə YALNIZ `status`
#: sütununun `CHECK`-ini genişləndirir (bax `_ensure_rejected_status`/
#: `_ensure_processing_status`) və konstruktorda HƏMİŞƏ owner-sütun köçürməsindən
#: (`_ensure_owner_columns`) ƏVVƏL işə düşür — yəni bu addımda mənbə cədvəldə
#: hələ owner sütunları OLA BİLMƏZ. Onları siyahıya salmaq `sqlite3.
#: OperationalError: no such column` ilə çökərdi.
_COLUMNS: Final[str] = (
    "id, seq, tenant_id, fine_id, store_id, filename, spool_path, taken_at, "
    "status, attempts, last_error, queued_at, next_attempt_at, uploaded_at, "
    "drive_file_id, connection_id"
)

#: Claim edilmiş elementin "köhnəlmə" müddəti (saniyə).
#:
#: Bu, struktur zəmanət DEYİL — infrastruktur detalıdır və `BACKOFF_SCHEDULE_
#: SECONDS` ilə eyni yerdə (modul sabiti kimi) yaşayır. Dəyər backoff
#: cədvəlinin ƏN UZUN addımı ilə (10 dəq.) uzlaşdırılıb: daha qısası hələ
#: yüklənməkdə olan böyük faylı ikinci işçiyə verərdi, daha uzunu isə çökmüş
#: prosesin elementini lazımsız yerə gözlədərdi. Konstruktorla dəyişdirilə
#: bilər (test və xüsusi quraşdırma üçün).
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`UPLOAD_CLAIM_STALE_AFTER_SECONDS`, seed: migrations/032).
FALLBACK_CLAIM_STALE_AFTER_SECONDS: Final[int] = fallback_int(
    SystemLimitKey.UPLOAD_CLAIM_STALE_AFTER_SECONDS
)


class UploadStatus(str, Enum):
    PENDING = "PENDING"
    #: Bir işçi elementi "claim" edib və hazırda yükləyir. `PENDING`
    #: seçimindən ÇIXIR — ikinci işçi eyni şəkli təkrar yükləyə bilmir.
    #: Çökmə halında köhnəlmə müddəti (`UPLOAD_CLAIM_STALE_AFTER_SECONDS`) bitəndən
    #: sonra element yenidən claim edilə bilir — sonsuz ilişmə YOXDUR.
    PROCESSING = "PROCESSING"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"
    #: Fayl yararsızdır (ölçü/uzantı/imza) — TƏKRAR CƏHD EDİLMİR.
    #: `FAILED`-dən fərqi: o, backoff ilə növbəyə qayıdır, bu isə qayıtmır.
    REJECTED = "REJECTED"


class UploadOwnerType(str, Enum):
    """Növbə elementinin hansı domen sətrinə aid olduğu (bax modul başlığı).

    `StrEnum` YOX, açıq `.value` (CLAUDE.md §4) — digər statuslarla EYNİ qərar.
    """

    #: `fines.id` — sübut şəkli (bölmə 4, əvvəlki YEGANƏ sahib).
    FINE = "FINE"
    #: `employee_documents.id` — sənəd/müqavilə skanı (#17, Faza 7).
    EMPLOYEE_DOCUMENT = "EMPLOYEE_DOCUMENT"
    #: `field_reports.id` VƏ YA `field_report_checklist_items.id` — mağaza
    #: auditi/insident foto-sübutu (#26+#27, kompas1.md Faza 3).
    #:
    #: İKİ CƏDVƏL, TƏK SAHİB TİPİ: hər iki İD `gen_random_uuid()`-dir, yəni
    #: QLOBAL unikaldır — bir UUID hər iki cədvəldə eyni anda mövcud ola
    #: bilməz və geri-çağırış sahibi birmənalı tapır
    #: (`FieldReportUseCase.attach_uploaded_photo` başlığı). Ayrı tip
    #: (`FIELD_REPORT_ITEM`) əlavə etmək uzantı ağ siyahısını, işçi
    #: geri-çağırışını və miqrasiya tarixçəsini ikiqat artırardı — halbuki
    #: hər ikisinin FORMAT qaydası və saxlanma yolu EYNİDİR.
    FIELD_REPORT = "FIELD_REPORT"
    #: `support_messages.id` — dəstək söhbətinə əlavə edilən şəkil
    #: (CHAT-1 Faza 6).
    #:
    #: NİYƏ MÖVCUD NÖVBƏYƏ QOŞULUR, AYRI MEXANİZM YAZILMIR: şəkil eyni
    #: problemləri daşıyır — mağazada internet kəsilir, Drive tokeni bitir,
    #: fayl yararsız ola bilər. Bunların hamısı burada artıq həll olunub
    #: (spool, backoff, `REJECTED` ayrımı). İkinci mexanizm eyni qüsurları
    #: sıfırdan təkrarlamalı olardı.
    SUPPORT_MESSAGE = "SUPPORT_MESSAGE"


@dataclass(frozen=True)
class PendingUpload:
    id: str
    tenant_id: str
    owner_type: UploadOwnerType
    owner_id: str
    store_id: str
    filename: str
    spool_path: Path
    taken_at: datetime
    attempts: int
    status: UploadStatus
    last_error: str | None = None
    #: SEC-4. `False` — köhnə (şifrələmə əlavə edilməzdən ƏVVƏL yazılmış)
    #: sətirlərin DEFOLTU da budur (bax `_ensure_encrypted_column`). Xam
    #: bayt YALNIZ `read_bytes()`-dən gəlir — deşifrə üçün
    #: `EvidenceUploadQueue.read_plaintext()` işlədilməlidir.
    is_encrypted: bool = False

    def read_bytes(self) -> bytes:
        """Spool faylının XAM baytı — şifrələnibsə HƏLƏ ŞİFRƏLİDİR.

        Bu metod QƏSDƏN deşifrə ETMİR: `PendingUpload` `EncryptionService`-ə
        istinad DAŞIMIR (təmiz məlumat obyekti olaraq qalır — sınaq və
        diaqnostika kodunun kripto asılılığı olmadan işləməsi üçün). Yükləmə
        axınının işlətməli olduğu düzgün yol `EvidenceUploadQueue.
        read_plaintext(item)`-dir.
        """
        return self.spool_path.read_bytes()


@dataclass
class UploadRunReport:
    attempted: int = 0
    uploaded: int = 0
    failed: int = 0
    #: Daimi olaraq rədd edilənlər. `failed`-dən AYRI sayılır, çünki onlar
    #: növbəyə qayıtmır — iki rəqəmi qarışdırmaq "50 uğursuz" xəbərinin
    #: gözləmək lazım olduğunu, yoxsa müdaxilə tələb etdiyini gizlədərdi.
    rejected: int = 0
    skipped_no_connection: bool = False
    errors: list[str] | None = None


class EvidenceUploadQueue:
    """Yüklənməni gözləyən şəkillərin SQLite indeksi + disk spool-u."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        tenant_id: str | None = None,
        spool_dir: Path | str | None = None,
        backoff_schedule: tuple[int, ...] | None = None,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        claim_stale_after_seconds: int | None = None,
        limits: InfrastructureLimits | None = None,
        encryption: EncryptionService | None = None,
    ) -> None:
        """Args:
        tenant_id: D2 (dövrə audit) — `pending()`/`claim_pending()` YALNIZ bu
            kirayəçinin sətirlərini seçir (naxış: `DriveConnectionRepository`-
            nin konstruktoru). SQLite indeksi `evidence_uploads.db` bir DATA
            QOVLUĞUNA bağlıdır (`resolve_data_file`), tenant-a YOX — maşın
            tenant DƏYİŞDİRİLƏRƏK yenidən quraşdırılsa (və ya köhnə fayl
            silinməyibsə), köhnə tenant-ın gözləyən sətirləri qalır. Filtrsiz
            `claim_pending()` onları CARİ (`self._factory.active()`) tenant-ın
            Drive-ına yükləyirdi — sübut zənciri qırılırdı: `file_id` A-nın
            `fines` sətrinə yazılır, fayl isə B-nin Drive-ındadır. `None` =
            KÖHNƏ (filtrsiz) davranış — YALNIZ `tests/`-in tenant-a əhəmiyyət
            verməyən ssenariləri üçün; kompozisiya kökü ONU HƏMİŞƏ ötürür
            (bax `composition.py::evidence_queue`).
        max_upload_bytes: `enqueue()`-dəki ölçü həddi. Defolt `MAX_UPLOAD_BYTES`
            FALLBACK-dır (həqiqi mənbə `system_limits.MAX_UPLOAD_SIZE_BYTES`);
            provider öz həddini ayrıca tətbiq edir. Sıfır/mənfi dəyər həddi
            SÖNDÜRMÜR, defolta qaytarır — səhv konfiqurasiya qorumanı sükutla
            itirməməlidir (provider-dəki eyni qərar).
        claim_stale_after_seconds: `PROCESSING`-də ilişmiş elementin yenidən
            claim edilə biləcəyi müddət. `None` = ROOT-dan
            (`UPLOAD_CLAIM_STALE_AFTER_SECONDS`) oxunur. Sıfır/mənfi dəyər
            defolta qaytarılır — əks halda element claim edilən kimi köhnəlmiş
            sayılar və qoruma (ikiqat yükləmənin qarşısını alan mexanizm)
            sükutla itərdi. ROOT tərəfdə eyni qoruma aralıq hüdudu ilə var
            (min 60 saniyə, migrations/032).
        backoff_schedule: `None` = ROOT-dan (`OFFLINE_RETRY_BACKOFF_SECONDS`).
        limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.
        encryption: SEC-4. `None` — DEFOLTSUZ DEYİL (fərq
            `telegram_repositories.py`-dan): bu sinif sınaq/diaqnostika
            kontekstlərində şifrələməsiz də qurula bilməlidir (məs. `tests/`
            fixture-ları), `PostgresTelegramConfigRepository`-nin tələb etdiyi
            kimi HƏMİŞƏ mövcud bir DB bağlantısı deyil. `None` verilərsə
            BÜTÜN yeni yazılar da açıq (`is_encrypted=False`) qalır — köhnə
            sətirlərlə EYNİ, sənədləşdirilmiş vəziyyət (bax `_ensure_
            encrypted_column`), sükutla "təhlükəsizdir" görünən YALANÇI qat
            DEYİL. İSTEHSALATDA kompozisiya kökü onu HƏMİŞƏ ötürür.
        """
        self._tenant_id = tenant_id
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._spool = Path(spool_dir) if spool_dir else self._path.parent / "evidence_spool"
        self._spool.mkdir(parents=True, exist_ok=True)
        self._limits = limits or InfrastructureLimits()
        self._encryption = encryption
        self._explicit_backoff = backoff_schedule
        self._max_upload_bytes = max_upload_bytes if max_upload_bytes > 0 else MAX_UPLOAD_BYTES
        self._explicit_claim_stale_after = (
            claim_stale_after_seconds
            if claim_stale_after_seconds is not None and claim_stale_after_seconds > 0
            else None
        )
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
            # Kilid gözləmə taymautu `OfflineBuffer` ilə EYNİ ROOT açarındandır
            # (`OFFLINE_SQLITE_TIMEOUT_SECONDS`): hər ikisi eyni maşındakı eyni
            # tipli lokal SQLite faylıdır və ayrı-ayrı tənzimlənməsi yalnız
            # "hansı biri idi?" sualını doğurardı.
            timeout=self._limits.float_of(SystemLimitKey.OFFLINE_SQLITE_TIMEOUT_SECONDS),
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)
        self._ensure_rejected_status()
        self._ensure_processing_status()
        # SIRA MƏCBURİDİR: bu addım `owner_type`/`owner_id`-i BACKFILL edərkən
        # cədvəlin son formada (bütün statuslarla) olduğunu güman edir —
        # yuxarıdakı iki köçürmə hələ işə düşməmişsə cədvəl rename-COPY
        # ortasında ola bilər (bax `_ensure_owner_columns` başlığı).
        self._ensure_owner_columns()
        # SEC-4 — `owner_type`/`owner_id` İLƏ EYNİ NAXIŞ: TAMAMİLƏ YENİ,
        # `CHECK`-siz sütun, sadə `ALTER TABLE ADD COLUMN` kifayətdir.
        self._ensure_encrypted_column()

    def _backoff_schedule(self) -> tuple[int, ...]:
        """Təkrar cəhd cədvəli — HƏR UĞURSUZ YÜKLƏMƏDƏ oxunur."""
        if self._explicit_backoff is not None:
            return self._explicit_backoff
        return self._limits.int_tuple_of(SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS)

    def _claim_stale_after(self) -> int:
        """Claim köhnəlmə müddəti — HƏR CLAIM-də oxunur.

        Növbə uzun ömürlüdür (tətbiqin bütün sessiyası); müddəti konstruktorda
        dondursaydıq, admin ilişmiş elementi tez azad etmək üçün proqramı
        yenidən başlatmalı olardı.
        """
        if self._explicit_claim_stale_after is not None:
            return self._explicit_claim_stale_after
        return self._limits.int_of(SystemLimitKey.UPLOAD_CLAIM_STALE_AFTER_SECONDS)

    def _ensure_rejected_status(self) -> None:
        """Köhnə növbə faylının `CHECK` məhdudiyyətini genişləndirir.

        `CREATE TABLE IF NOT EXISTS` MÖVCUD cədvəli dəyişmir — əvvəlki
        versiyada yaradılmış SQLite faylında `status` hələ də yalnız üç dəyər
        qəbul edir və `REJECTED` yazmaq `IntegrityError` verərdi, yəni sonsuz
        dövrənin qarşısını alan mexanizm məhz köhnə quraşdırmalarda işləməzdi.
        SQLite `CHECK`-i `ALTER` ilə dəyişmir, ona görə cədvəl köçürülür.

        Əməliyyat idempotentdir (sxem artıq yenidirsə dərhal qayıdır) və
        sətirlərin HAMISI olduğu kimi köçürülür — gözləyən şəkillər itmir.
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'evidence_uploads'"
        ).fetchone()
        if row is None or "REJECTED" in (row["sql"] or ""):
            return
        self._conn.executescript(
            "BEGIN IMMEDIATE;\n"  # noqa: S608 — sxem mətni sabitdir, istifadəçi girişi yoxdur
            "ALTER TABLE evidence_uploads RENAME TO evidence_uploads_legacy;\n"
            f"{_TABLE_SQL}\n"
            f"INSERT INTO evidence_uploads ({_COLUMNS})\n"
            f"     SELECT {_COLUMNS} FROM evidence_uploads_legacy;\n"
            # Köhnə cədvəllə birlikdə onun indeksi də gedir — indeks həmin
            # addan sonra yenidən qurulur.
            "DROP TABLE evidence_uploads_legacy;\n"
            f"{_INDEX_SQL}\n"
            "COMMIT;"
        )
        _log.info("EVIDENCE_QUEUE_SCHEMA_UPGRADED", extra={"status": "REJECTED"})

    def _ensure_processing_status(self) -> None:
        """`PROCESSING` statusunu köhnə növbə faylına gətirir.

        Naxış `_ensure_rejected_status`-un eynidir (Faza 3-də `REJECTED` məhz
        belə əlavə olunmuşdu) və eyni səbəbə görə lazımdır: `CREATE TABLE IF
        NOT EXISTS` mövcud cədvəlin `CHECK` məhdudiyyətini DƏYİŞMİR, yəni
        əvvəlki versiyada yaradılmış faylda `claim` cəhdi `IntegrityError`
        verərdi — ikiqat yükləməni əngəlləyən mexanizm məhz köhnə
        quraşdırmalarda işləməzdi.

        İKİ AYRI METOD QƏSDƏNDİR: hər addım ÖZ markerinə (`REJECTED` /
        `PROCESSING`) baxır və müstəqil işləyir. Onları bir funksiyaya
        yığmaq mövcud, sınaqdan çıxmış addımın davranışını dəyişdirmək
        olardı; ardıcıl icra isə hər iki köhnə variantı (3 statuslu və 4
        statuslu fayl) düzgün gətirir.

        İdempotentdir və sətirlərin hamısını olduğu kimi köçürür.
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'evidence_uploads'"
        ).fetchone()
        if row is None or "PROCESSING" in (row["sql"] or ""):
            return
        self._conn.executescript(
            "BEGIN IMMEDIATE;\n"  # noqa: S608 — sxem mətni sabitdir, istifadəçi girişi yoxdur
            "ALTER TABLE evidence_uploads RENAME TO evidence_uploads_legacy;\n"
            f"{_TABLE_SQL}\n"
            f"INSERT INTO evidence_uploads ({_COLUMNS})\n"
            f"     SELECT {_COLUMNS} FROM evidence_uploads_legacy;\n"
            "DROP TABLE evidence_uploads_legacy;\n"
            f"{_INDEX_SQL}\n"
            "COMMIT;"
        )
        _log.info("EVIDENCE_QUEUE_SCHEMA_UPGRADED", extra={"status": "PROCESSING"})

    def _ensure_owner_columns(self) -> None:
        """`owner_type`/`owner_id`-i köhnə (yalnız `fine_id` bilən) fayla gətirir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ RENAME-ƏSASLI KÖÇÜRMƏ YOX (`_ensure_rejected_status`-dan FƏRQ)
        ──────────────────────────────────────────────────────────────────────
        Yuxarıdakı iki metod `status` sütununun `CHECK` siyahısını genişləndirir
        və SQLite `CHECK`-i `ALTER` ilə DƏYİŞMİR — ona görə bütün cədvəl
        köçürülməli idi. `owner_type`/`owner_id` isə TAMAMİLƏ YENİ, `CHECK`-siz
        sütunlardır (bax `_TABLE_SQL` şərhi) — SQLite `ALTER TABLE ... ADD
        COLUMN`-u bunun üçün birbaşa dəstəkləyir, yəni bütün cədvəli yenidən
        qurmaq (rename + tam köçürmə) YERSİZ RİSK olardı.

        ──────────────────────────────────────────────────────────────────────
        BACKFILL — MƏLUMAT İTKİSİ YOXDUR
        ──────────────────────────────────────────────────────────────────────
        Sütun(lar) əlavə olunduqdan sonra `owner_type IS NULL` olan HƏR sətir
        `owner_type = 'FINE', owner_id = fine_id` ilə doldurulur — növbə
        əvvəllər YALNIZ cərimə sübutu üçün mövcud olduğu üçün bu, YEGANƏ mümkün
        mənbədir. Gözləyən (hələ yüklənməmiş) şəkil sətirləri toxunulmadan
        qalır, yalnız iki yeni sütun dolur.

        Əməliyyat HƏR başlanğıcda təkrar işə düşür (idempotentlik, digər iki
        metodla eyni prinsip): sütun mövcuddursa `ALTER` ötürülür, `UPDATE ...
        WHERE owner_type IS NULL` isə artıq köçürülmüş sətirlərdə heç nə
        etməyən ucuz sorğuya çevrilir.
        """
        with self._lock, self._transaction() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(evidence_uploads)")}
            altered = False
            if "owner_type" not in columns:
                conn.execute("ALTER TABLE evidence_uploads ADD COLUMN owner_type TEXT")
                altered = True
            if "owner_id" not in columns:
                conn.execute("ALTER TABLE evidence_uploads ADD COLUMN owner_id TEXT")
                altered = True
            cursor = conn.execute(
                "UPDATE evidence_uploads SET owner_type = 'FINE', owner_id = fine_id "
                "WHERE owner_type IS NULL"
            )
            backfilled = cursor.rowcount if cursor.rowcount > 0 else 0
        if altered or backfilled:
            _log.info(
                "EVIDENCE_QUEUE_SCHEMA_UPGRADED",
                extra={"status": "OWNER_COLUMNS", "backfilled_rows": backfilled},
            )

    def _ensure_encrypted_column(self) -> None:
        """`is_encrypted`-i köhnə (şifrələmədən ƏVVƏLKİ) fayla gətirir (SEC-4).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ KÖHNƏ SƏTİRLƏR BACKFILL EDİLMİR (`owner_type`-dan FƏRQ)
        ──────────────────────────────────────────────────────────────────────
        `_ensure_owner_columns()` köhnə sətirləri YENİ dəyərlə (`'FINE'`)
        doldurur, çünki əvvəlki həqiqət MƏLUMDUR (növbə əvvəllər YALNIZ
        cərimə üçün var idi). Burada isə əksinədir: sütun defolt `0`-dır və
        KÖHNƏ sətirlər FAKTİKİ olaraq AÇIQ (şifrələnməmiş) yazılıb — onları
        `1`-ə "düzəltmək" YALAN məlumat yazmaq olardı, çünki spool faylının
        ÖZÜ şifrəli DEYİL. `%LOCALAPPDATA%` → `%PROGRAMDATA%` keçidinin
        "köhnəni tanı, köçürmə" prinsipinin analoqu (CLAUDE.md §8): oxucu
        (`read_plaintext`) bayrağa görə ŞƏRTİ davranır, məlumatın özü
        dəyişmir.

        Əməliyyat idempotentdir: sütun mövcuddursa `ALTER` ötürülür.
        """
        with self._lock, self._transaction() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(evidence_uploads)")}
            if "is_encrypted" in columns:
                return
            conn.execute(
                "ALTER TABLE evidence_uploads ADD COLUMN is_encrypted INTEGER NOT NULL DEFAULT 0"
            )
        _log.info("EVIDENCE_QUEUE_SCHEMA_UPGRADED", extra={"status": "ENCRYPTED_COLUMN"})

    def set_max_upload_bytes(self, value: int) -> None:
        """Ölçü həddini yeniləyir — Root paneldəki dəyişiklikdən sonra.

        Növbə obyekti tətbiq işlədikcə yaşayır. Hədd yalnız konstruktorda
        oxunsaydı, Root onu qaldırandan sonra provider dərhal yeni dəyəri,
        növbə isə proqram yenidən açılana qədər KÖHNƏSİNİ işlədərdi — yəni
        eyni fayl bir qatda qəbul, digərində rədd edilərdi.
        """
        self._max_upload_bytes = value if value > 0 else MAX_UPLOAD_BYTES

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------------------------------- yazma ---------------------------------- #

    def enqueue(
        self,
        *,
        tenant_id: str,
        owner_type: UploadOwnerType,
        owner_id: str,
        store_id: StoreId,
        filename: str,
        content: bytes,
        taken_at: datetime,
        now: datetime | None = None,
    ) -> str:
        """Args:
        owner_type: Sətrin aid olduğu domen cədvəli (bax `UploadOwnerType`).
        owner_id: Həmin cədvəldəki sətrin ID-si (mətn) — `FINE` üçün
            `fines.id`, `EMPLOYEE_DOCUMENT` üçün `employee_documents.id`.
        """
        # ÖN-ŞƏRT DİSKƏ YAZMAZDAN ƏVVƏL: yararsız fayl növbəyə DÜŞMÜR.
        #
        # Qayda `google_drive.validate_evidence_payload`-dadır — provider ilə
        # EYNİ funksiya. Burada yoxlanmasaydı, fayl diskə düşər, `PENDING`
        # qalar və hər 10 dəqiqədən bir eyni cavabla rədd edilərdi (bax modul
        # başlığı). İstisna QƏSDƏN yuxarı ötürülür: operator səbəbi dərhal
        # ekranda görməlidir, sənəd/cərimə isə sübutsuz yaradılmamalıdır.
        #
        # İCAZƏLİ FORMAT SAHİB TİPİNDƏN ASILIDIR (SEC-018, bax
        # `google_drive` başlığı): cərimə sübutu yalnız şəkil, işçi sənədi
        # şəkil + PDF qəbul edir. Qərar burada VERİLMİR — `owner_type`
        # ötürülür, siyahı isə qayda ilə birlikdə TƏK yerdə saxlanır.
        try:
            validate_evidence_payload(
                content,
                filename,
                max_bytes=self._max_upload_bytes,
                owner_type=owner_type.value,
            )
        except EvidenceValidationError as error:
            _log.warning(
                "EVIDENCE_UPLOAD_REJECTED_AT_ENQUEUE",
                extra={
                    "owner_type": owner_type.value,
                    "owner_id": owner_id,
                    "bytes": len(content),
                    "reason": str(error),
                },
            )
            raise

        moment = now or datetime.now(UTC)
        entry_id = str(uuid.uuid4())
        spool_path = self._spool / f"{entry_id}.bin"

        # ŞİFRƏLƏMƏ VALIDASİYADAN SONRA, DİSKƏ YAZMAZDAN ƏVVƏL (SEC-4).
        # ──────────────────────────────────────────────────────────────────
        # `self._encryption is None` — QƏSDƏN sükutla açıq yazmaq DEYİL:
        # bu, YALNIZ kompozisiya kökünün xidməti ÖTÜRMƏDİYİ (sınaq/dev)
        # kontekstlərdə baş verir və köhnə sətirlərlə EYNİ, sənədləşdirilmiş
        # vəziyyətdir (bax konstruktor şərhi).
        #
        # `encrypt_bytes()` İSTİSNA ATSA (açar yüklənməyib, s.) — SÜKUTLA
        # AÇIQ YAZILMIR, İstisna YUXARI ÖTÜRÜLÜR: heç nə hələ diskə/DB-yə
        # yazılmayıb, yəni operator YALNIZ "yenidən cəhd edin" görür və
        # şəkli itirmir — foto hələ ekranında/kamerasındadır. Bu, `validate_
        # evidence_payload`-un yuxarıdakı İSTİSNA-ötürmə qərarı ilə EYNİ
        # məntiqdir. `mark_failed`-in arxa-plan backoff-u BURADA YERSİZDİR:
        # operator DƏRHAL, SİNXRON nəticə gözləyir (bu, arxa-plan Drive
        # yükləməsi kimi gözədən-uzaq bir iş DEYİL).
        is_encrypted = self._encryption is not None
        to_write = (
            self._encryption.encrypt_bytes(content, context=_spool_context(entry_id))
            if self._encryption is not None
            else content
        )
        # Əvvəlcə DİSKƏ, sonra indeksə: tərsi olsaydı, aradakı çökmə
        # "növbədə var, faylı yoxdur" vəziyyəti yaradardı.
        try:
            spool_path.write_bytes(to_write)
        except OSError:
            # INF2-03 (dövrə 2 audit): `OSError` (disk dolu, icazə itib)
            # YARIMÇIQ/sıfır-baytlıq fayl buraxa bilər. Heç bir DB sətri ona
            # istinad ETMİR — aşağıdakı tranzaksiya BURAYA HEÇ VAXT çatmır —
            # ona görə fayl SİLİNMƏSƏ ƏBƏDİ YETİM qalırdı və heç bir sweep/
            # reconcile mexanizmi onu tapmırdı (bax `docs/open_questions.md`
            # OQ — tam təmizləmə siyasəti AYRI qərardır, bu YALNIZ BU
            # konkret uğursuzluq yolunun özünü təmizləyir). Məhz disk-dolu
            # insidenti zamanı bu TƏKRARLANIR (hər uğursuz cəhd YENİ
            # `entry_id` alır), yəni düzəliş olmasa insidenti yüngülləşdirmək
            # ƏVƏZİNƏ tədricən AĞIRLAŞDIRIRDI. `missing_ok=True`: yazı hətta
            # faylın ÖZÜ yaranmadan da uğursuz ola bilər (`open()` mərhələsi).
            spool_path.unlink(missing_ok=True)
            raise

        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM evidence_uploads"
            ).fetchone()
            conn.execute(
                """
                INSERT INTO evidence_uploads
                    (id, seq, tenant_id, fine_id, store_id, filename, spool_path,
                     taken_at, status, attempts, queued_at, next_attempt_at,
                     owner_type, owner_id, is_encrypted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    int(row["n"]),
                    tenant_id,
                    # `fine_id` KÖHNƏ (`NOT NULL`) sütunudur — silinmir (bax modul
                    # başlığı). Bura HƏMİŞƏ `owner_id`-nin EYNİ dəyəri yazılır:
                    # `FINE` sətirləri üçün bu, əvvəlki davranışla BİREBİRDİR;
                    # `EMPLOYEE_DOCUMENT` üçün sütun mənasız olsa da, `NOT NULL`
                    # məhdudiyyətini pozmadan doldurulur.
                    owner_id,
                    str(store_id),
                    filename,
                    str(spool_path),
                    taken_at.isoformat(),
                    moment.isoformat(),
                    moment.isoformat(),
                    owner_type.value,
                    owner_id,
                    int(is_encrypted),
                ),
            )
        _log.info(
            "EVIDENCE_UPLOAD_QUEUED",
            extra={
                "owner_type": owner_type.value,
                "owner_id": owner_id,
                "bytes": len(content),
                "encrypted": is_encrypted,
            },
        )
        return entry_id

    # -------------------------------- oxuma ---------------------------------- #

    def _tenant_clause(self) -> tuple[str, tuple[str, ...]]:
        """D2: `self._tenant_id` verilibsə SQL-ə `AND tenant_id = ?` qoşur.

        `None` halı (naxış: konstruktor şərhi) YALNIZ tenant-a əhəmiyyət
        verməyən köhnə testlər üçün qalır — boş sətir + boş parametr
        qaytarır, sorğu filtrsiz qalır.
        """
        if self._tenant_id is None:
            return "", ()
        return " AND tenant_id = ?", (self._tenant_id,)

    def pending(self, *, now: datetime | None = None, limit: int = 20) -> list[PendingUpload]:
        moment = now or datetime.now(UTC)
        clause, clause_params = self._tenant_clause()
        with self._lock:
            rows = self._conn.execute(
                # `clause` sabit İKİ variantdan biridir (`_tenant_clause`) —
                # bölmə 4 qaydası.
                f"""
                SELECT * FROM evidence_uploads
                 WHERE status = 'PENDING' AND next_attempt_at <= ?{clause}
                 ORDER BY seq LIMIT ?
                """,  # noqa: S608 — şərtlər sabit siyahıdandır
                (moment.isoformat(), *clause_params, limit),
            ).fetchall()
        return [_row_to_upload(row) for row in rows]

    def claim_pending(self, *, now: datetime | None = None, limit: int = 20) -> list[PendingUpload]:
        """`pending()`-in ATOMİK variantı — seçilən element `PROCESSING` olur.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `pending()` DƏYİŞDİRİLMİR
        ──────────────────────────────────────────────────────────────────────
        `pending()` oxu-yalnız görünüşdür (ekran, diaqnostika, test). Ona
        yan-təsir qoymaq "növbəyə baxmaq" əməliyyatını "növbəni tutmaq"a
        çevirərdi — bir dəfə açılan diaqnostika ekranı bütün növbəni
        bloklayardı. Ona görə claim AYRICA metoddur və onu yalnız işçi çağırır.

        ATOMİKLİK: seçim və işarələmə TƏK `BEGIN IMMEDIATE` tranzaksiyasındadır.
        SQLite-da `IMMEDIATE` dərhal yazı kilidi alır, yəni ikinci proses
        (fərqli bağlantı, hətta fərqli tətbiq nüsxəsi) tranzaksiya bitənə
        qədər gözləyir və sonra artıq `PROCESSING` olan sətri GÖRMÜR.

        ÇÖKMƏDƏN BƏRPA: claim anında `next_attempt_at` köhnəlmə anına təyin
        olunur. Proses yükləmə ortasında ölsə, həmin andan sonra element
        yenidən claim edilə bilir — status sahəsi ayrıca "kim tutub" sütunu
        tələb etmədən həm kilid, həm taymer rolunu oynayır.
        """
        moment = now or datetime.now(UTC)
        stale_at = moment + timedelta(seconds=self._claim_stale_after())
        clause, clause_params = self._tenant_clause()
        with self._lock, self._transaction() as conn:
            rows = conn.execute(
                # `clause` sabit İKİ variantdan biridir (`_tenant_clause`).
                f"""
                SELECT * FROM evidence_uploads
                 WHERE next_attempt_at <= ?
                   AND status IN ('PENDING', 'PROCESSING'){clause}
                 ORDER BY seq LIMIT ?
                """,  # noqa: S608 — şərtlər sabit siyahıdandır
                (moment.isoformat(), *clause_params, limit),
            ).fetchall()
            for row in rows:
                # Sətir-sətir UPDATE: `IN (?,?,...)` siyahısını sətir
                # birləşdirməklə qurmaq lazım gələrdi, halbuki paket ölçüsü
                # onsuz da 20-dir — dinamik SQL-in yeri burada deyil.
                conn.execute(
                    """UPDATE evidence_uploads
                          SET status = 'PROCESSING', next_attempt_at = ?
                        WHERE id = ?""",
                    (stale_at.isoformat(), row["id"]),
                )
        # Statusu AÇIQ şəkildə düzəldirik: sətirlər UPDATE-dən ƏVVƏL oxunub,
        # yəni onlarda hələ `PENDING` yazılıdır. Çağıran tərəfə "hələ
        # gözləyir" deyən obyekt vermək, elementin artıq tutulduğu faktını
        # gizlədərdi.
        return [replace(_row_to_upload(row), status=UploadStatus.PROCESSING) for row in rows]

    def release(self, entry_ids: list[str], *, now: datetime | None = None) -> None:
        """Claim-i geri qaytarır — element DƏRHAL yenidən `PENDING` olur.

        Yükləmə HEÇ CƏHD EDİLMƏDİYİ hallar üçündür (məs. aktiv Drive bağlantısı
        yoxdur). Köhnəlmə müddətini gözləmək burada mənasız gecikmə olardı:
        element toxunulmayıb, növbəti dövrədə dərhal cəhd edilə bilər.

        Boş siyahı üçün heç nə etmir — çağıran tərəfdə şərt yazmağa ehtiyac
        qalmasın (`run_once` naxışı).
        """
        if not entry_ids:
            return
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            for entry_id in entry_ids:
                conn.execute(
                    """UPDATE evidence_uploads
                          SET status = 'PENDING', next_attempt_at = ?
                        WHERE id = ? AND status = 'PROCESSING'""",
                    (moment.isoformat(), entry_id),
                )

    def get(self, entry_id: str) -> PendingUpload | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM evidence_uploads WHERE id = ?", (entry_id,)
            ).fetchone()
        return _row_to_upload(row) if row else None

    def read_plaintext(self, item: PendingUpload) -> bytes:
        """`item.read_bytes()`-in DEŞİFRƏ-BİLƏN variantı (SEC-4).

        Yükləmə axınının (`EvidenceUploadWorker`) işlətməli olduğu YEGANƏ
        oxu yoludur — `PendingUpload.read_bytes()` ÖZÜ deşifrə etmir (bax
        onun docstring-i).

        Raises:
            DecryptionError, EncryptionKeyError: açar dəyişib/itibsə.
                `EvidenceUploadWorker` bunu `mark_rejected`-ə yönləndirir
                (`mark_failed` YOX): açarın YENİDƏN yüklənməsi gözləməklə
                DEYİL, operator müdaxiləsi ilə həll olunur, ona görə
                avtomatik backoff `mark_rejected`-in qorumaq istədiyi
                "sonsuz dövrə" problemini TƏKRARLAYARDI. Spool faylı
                (`mark_rejected` heç vaxt silmir) toxunulmaz qalır — açar
                bərpa olunanda `requeue_rejected()` yenidən cəhd edə bilər.
        """
        raw = item.read_bytes()
        if not item.is_encrypted:
            return raw
        # `self._encryption is None` ola BİLMƏZ burada: `is_encrypted=True`
        # sətri YALNIZ `encryption` verilmiş konstruktorda yarana bilər.
        # Yenə də `None` olarsa (məs. eyni SQLite faylı ARDINCA şifrələməsiz
        # konstruktorla açılıbsa — qeyri-adi, amma mümkün əməliyyat xətası),
        # `EncryptionKeyError`-a bənzər aydın mesajla dayanmaq sükutla
        # "deşifrə edilməyib" bayt qaytarmaqdan (yəni şifrəli zibili Drive-a
        # göndərməkdən) qat-qat üstündür.
        if self._encryption is None:
            raise EncryptionKeyError(
                "Sətir şifrəli işarələnib, lakin bu növbə şifrələmə xidməti "
                "OLMADAN qurulub — konfiqurasiya uyğunsuzluğu",
                context={"entry_id": item.id},
            )
        return self._encryption.decrypt_bytes(raw, context=_spool_context(item.id))

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM evidence_uploads GROUP BY status"
            ).fetchall()
        counts = {status.value: 0 for status in UploadStatus}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    # ------------------------------ vəziyyət --------------------------------- #

    def mark_uploaded(
        self,
        entry_id: str,
        reference: StorageReference,
        *,
        now: datetime | None = None,
        delete_spool: bool = True,
    ) -> None:
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT spool_path FROM evidence_uploads WHERE id = ?", (entry_id,)
            ).fetchone()
            conn.execute(
                """
                UPDATE evidence_uploads
                   SET status = 'UPLOADED', uploaded_at = ?, drive_file_id = ?,
                       connection_id = ?, last_error = NULL
                 WHERE id = ?
                """,
                (
                    moment.isoformat(),
                    reference.file_id,
                    str(reference.connection_id) if reference.connection_id else None,
                    entry_id,
                ),
            )
        if delete_spool and row is not None:
            # Şəkil artıq Drive-dadır — lokal surət yalnız disk yeyir.
            Path(row["spool_path"]).unlink(missing_ok=True)

    def mark_failed(self, entry_id: str, error: str, *, now: datetime | None = None) -> datetime:
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT attempts FROM evidence_uploads WHERE id = ?", (entry_id,)
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            schedule = self._backoff_schedule()
            delay = schedule[min(attempts - 1, len(schedule) - 1)]
            next_at = moment + timedelta(seconds=delay)
            conn.execute(
                # `status = 'PENDING'` ƏLAVƏ EDİLİB: element artıq `claim_pending()`
                # ilə `PROCESSING`-ə keçirilmiş olur və onu geri qaytarmasaq
                # backoff bitəndən sonra da `PENDING` seçiminə düşməzdi.
                # Claim-dən əvvəlki davranışla eynidir — orada status onsuz da
                # `PENDING` idi, yəni bu, dəyişiklik yox, açıq yazılışdır.
                """UPDATE evidence_uploads
                      SET status = 'PENDING', attempts = ?, last_error = ?,
                          next_attempt_at = ?
                    WHERE id = ?""",
                (attempts, error[:500], next_at.isoformat(), entry_id),
            )
        _log.warning(
            "EVIDENCE_UPLOAD_RETRY",
            extra={"entry_id": entry_id, "attempts": attempts, "delay_seconds": delay},
        )
        return next_at

    def mark_rejected(self, entry_id: str, error: str, *, now: datetime | None = None) -> None:
        """Elementi DAİMİ olaraq növbədən çıxarır — təkrar cəhd edilmir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `mark_failed` KİFAYƏT DEYİL
        ──────────────────────────────────────────────────────────────────────
        `mark_failed` backoff təyin edib elementi `PENDING` saxlayır, yəni
        gözləməkdən sonra vəziyyətin düzələcəyini FƏRZ EDİR. Ölçü/uzantı/imza
        pozuntusunda bu fərziyyə yanlışdır: yüz cəhd də eyni cavabı verəcək.
        Nəticə sonsuz dövrə, dolmuş disk və faydasız jurnal axını olardı.

        ──────────────────────────────────────────────────────────────────────
        SPOOL FAYLI NİYƏ SİLİNMİR
        ──────────────────────────────────────────────────────────────────────
        `mark_uploaded`-dan fərqli olaraq bayt Drive-da DEYİL — silinsə, şəkil
        birdəfəlik itərdi. Halbuki rədd səbəbi konfiqurasiya da ola bilər
        (Root həddi 1 MB-a salıb); hədd geri qaldırıldıqda fayl yerindədir və
        admin onu yenidən növbəyə sala bilər — bu yol `requeue_rejected()`
        metodudur. Yer itkisi məhduddur — yeni yararsız fayl artıq
        `enqueue()`-dan keçmir.
        """
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            conn.execute(
                """UPDATE evidence_uploads
                      SET status = 'REJECTED', last_error = ?, next_attempt_at = ?
                    WHERE id = ?""",
                (error[:500], moment.isoformat(), entry_id),
            )
        _log.error(
            "EVIDENCE_UPLOAD_REJECTED",
            extra={"entry_id": entry_id, "reason": error[:200]},
        )

    def requeue_rejected(self, entry_id: str, *, now: datetime | None = None) -> bool:
        """Rədd edilmiş elementi yenidən növbəyə salır. Qaytarır: alındımı.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BU METOD MƏCBURİDİR
        ──────────────────────────────────────────────────────────────────────
        `mark_rejected` spool faylını QƏSDƏN saxlayır və docstring-i açıq vəd
        edir: hədd geri qaldırıldıqda «admin onu yenidən növbəyə sala bilər».
        Belə bir yol olmasaydı, vəd yerinə yetirilməzdi: Root
        `MAX_UPLOAD_SIZE_BYTES`-i artırsa belə, əvvəllər rədd edilmiş sübut
        şəkli əbədi əlçatmaz qalardı — halbuki 72 saatlıq etiraz pəncərəsi
        (bölmə 4) məhz həmin sübuta əsaslana bilər.

        ──────────────────────────────────────────────────────────────────────
        SONSUZ DÖVRƏ YARANMIR
        ──────────────────────────────────────────────────────────────────────
        Element `PENDING` olur, yəni növbəti dövrədə YENİDƏN validasiyadan
        keçir (`provider.upload` → `validate_evidence_payload`). Hədd hələ də
        kiçikdirsə nəticə yenə `REJECTED` olur və element növbədən çıxır —
        yəni bir düymə = BİR əlavə cəhd, avtomatik təkrarlanma yox.
        `REJECTED` sətri `claim_pending()` seçiminə düşmür, ona görə heç bir
        fon dövrəsi onu öz-özünə geri qaytara bilmir.

        ──────────────────────────────────────────────────────────────────────
        SPOOL FAYLI YOXDURSA GERİ QAYTARILMIR
        ──────────────────────────────────────────────────────────────────────
        Fayl əl ilə silinibsə, `PENDING` etmək daha pis vəziyyət yaradardı:
        `read_bytes()` ümumi istisna atar, işçi isə onu `mark_failed` kimi
        oxuyub BACKOFF ilə əbədi təkrarlayardı (validasiya xətası olmadığı
        üçün `mark_rejected`-ə düşməzdi). Ona görə belə element `REJECTED`
        qalır və metod `False` qaytarır.

        `attempts` sıfırlanmır: o, "neçə dəfə cəhd edilib" tarixidir və onu
        silmək diaqnostikanı korlayardı (backoff cədvəli onsuz da yalnız
        `mark_failed` yolunda işləyir).
        """
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT spool_path, status FROM evidence_uploads WHERE id = ?",
                (entry_id,),
            ).fetchone()
            if row is None or row["status"] != UploadStatus.REJECTED.value:
                # Yalnız `REJECTED`-dən çıxış: `UPLOADED` sətri geri qaytarmaq
                # eyni şəkli Drive-a ikinci dəfə yükləyərdi, `PENDING`/
                # `PROCESSING` üçün isə bu əməliyyatın mənası yoxdur.
                requeued = False
            elif not Path(row["spool_path"]).exists():
                requeued = False
            else:
                conn.execute(
                    """UPDATE evidence_uploads
                          SET status = 'PENDING', last_error = NULL, next_attempt_at = ?
                        WHERE id = ?""",
                    (moment.isoformat(), entry_id),
                )
                requeued = True

        if requeued:
            _log.warning(
                "EVIDENCE_UPLOAD_REQUEUED",
                extra={
                    "entry_id": entry_id,
                    "impact": "növbəti dövrədə yenidən validasiyadan keçəcək",
                },
            )
        else:
            _log.warning(
                "EVIDENCE_UPLOAD_REQUEUE_SKIPPED",
                extra={
                    "entry_id": entry_id,
                    "reason": "sətir REJECTED deyil və ya spool faylı yoxdur",
                },
            )
        return requeued

    def _transaction(self) -> _Tx:
        return _Tx(self._conn)


class _Tx:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._conn.execute("COMMIT" if exc_type is None else "ROLLBACK")


def _row_to_upload(row: sqlite3.Row) -> PendingUpload:
    # `owner_type`/`owner_id`/`is_encrypted` bu ANDA HƏMİŞƏ doludur: konstruktor
    # `_ensure_owner_columns()`/`_ensure_encrypted_column()`-u sxem quraşdırmasının
    # SON addımları kimi çağırır, yəni oxuma metodları işə düşənə qədər hər ikisi
    # artıq bitib.
    return PendingUpload(
        id=row["id"],
        tenant_id=row["tenant_id"],
        owner_type=UploadOwnerType(row["owner_type"]),
        owner_id=row["owner_id"],
        store_id=row["store_id"],
        filename=row["filename"],
        spool_path=Path(row["spool_path"]),
        taken_at=datetime.fromisoformat(row["taken_at"]),
        attempts=row["attempts"],
        status=UploadStatus(row["status"]),
        last_error=row["last_error"],
        is_encrypted=bool(row["is_encrypted"]),
    )


class EvidenceUploadWorker:
    """Növbəni boşaldan işçi. Sap yaratmır — planlaşdırma çağıranın işidir."""

    def __init__(
        self,
        *,
        queue: EvidenceUploadQueue,
        provider_factory: object,
        on_uploaded: object = None,
        batch_size: int = 20,
    ) -> None:
        """Args:
        provider_factory: `.active()` metodu ilə aktiv provider verən obyekt
            (`DriveProviderFactory`). Aktiv bağlantı yoxdursa istisna atır və
            işçi növbəti dövrədə yenidən cəhd edir.
        on_uploaded: `(owner_type: str, owner_id: str, reference: StorageReference)
            -> None` — sahib sətri (`fines` və ya `employee_documents`)
            yeniləmək üçün geri çağırış. `owner_type` `UploadOwnerType.value`-dur
            (mətn) — çağıran tərəf import dövrəsi qurmadan sadə müqayisə edə
            bilsin deyə enum DEYİL, sətir ötürülür.
        """
        self._queue = queue
        self._factory = provider_factory
        self._on_uploaded = on_uploaded
        self._batch_size = batch_size

    def run_once(self, *, now: datetime | None = None) -> UploadRunReport:
        from uuid import UUID as _UUID  # noqa: PLC0415

        moment = now or datetime.now(UTC)
        report = UploadRunReport(errors=[])
        # CLAIM: element seçilən anda `PROCESSING` olur — paralel işləyən ikinci
        # işçi eyni şəkli Drive-a təkrar yükləyə bilmir (bax modul başlığı).
        items = self._queue.claim_pending(now=moment, limit=self._batch_size)
        if not items:
            return report

        try:
            provider = self._factory.active()  # type: ignore[attr-defined]
        except Exception as exc:  # aktiv bağlantı yoxdur / token problemi
            report.skipped_no_connection = True
            # Heç bir yükləmə CƏHD EDİLMƏDİ — claim dərhal geri qaytarılır ki,
            # şəkillər köhnəlmə müddəti boyu "görünməz" qalmasın.
            self._queue.release([item.id for item in items], now=moment)
            _log.warning("EVIDENCE_UPLOAD_NO_CONNECTION", extra={"error": str(exc)})
            return report

        for item in items:
            report.attempted += 1
            try:
                reference = provider.upload(
                    # SEC-4: `item.read_bytes()` DEYİL — o, şifrələnibsə XAM
                    # (hələ şifrəli) bayt qaytarardı. `read_plaintext()` bayrağa
                    # görə şərti deşifrə edir (bax onun docstring-i).
                    self._queue.read_plaintext(item),
                    item.filename,
                    _UUID(item.store_id),
                    item.taken_at,
                    # Provider yükü İKİNCİ dəfə yoxlayır (hədd dəyişmiş ola
                    # bilər) və format siyahısı sahib tipindən asılıdır
                    # (SEC-018). Sahib tipi ötürülməsəydi, provider ən dar
                    # siyahını — yalnız şəkil — tətbiq edər və növbədəki
                    # QANUNİ sənəd PDF-i `REJECTED` olardı.
                    owner_type=item.owner_type.value,
                )
            except (DecryptionError, EncryptionKeyError) as exc:
                # SEC-4: açar dəyişib/itib — GÖZLƏMƏK NƏTİCƏNİ DƏYİŞMİR (əks
                # halda `mark_failed`-in backoff-u eyni "sonsuz dövrə"
                # problemini yaradardı ki, `mark_rejected` məhz onun üçün
                # icad olunub — bax onun docstring-i). Spool faylı SİLİNMİR
                # (`mark_rejected` heç vaxt silmir): açar bərpa olunanda
                # (`KOMPASOS_FERNET_KEY_PREVIOUS`) admin `requeue_rejected()`
                # ilə yenidən cəhd edə bilər — sübut İTMİR, YALNIZ gözləyir.
                report.rejected += 1
                assert report.errors is not None
                report.errors.append(f"{item.owner_type.value}:{item.owner_id}: {exc}")
                self._queue.mark_rejected(item.id, str(exc), now=moment)
                continue
            except EvidenceValidationError as exc:
                # Fayl yararsızdır — şəbəkə/kvota problemi DEYİL. Gözləmək
                # nəticəni dəyişmədiyi üçün element daimi olaraq kənara
                # qoyulur (bax `mark_rejected`). Bura yalnız köhnə növbə
                # sətirləri və hədd sonradan aşağı salınan hallar düşür:
                # yeni element artıq `enqueue()`-dan keçmir.
                report.rejected += 1
                assert report.errors is not None
                report.errors.append(f"{item.owner_type.value}:{item.owner_id}: {exc}")
                self._queue.mark_rejected(item.id, str(exc), now=moment)
                continue
            except Exception as exc:  # bir şəklin nasazlığı növbəni dayandırmasın
                report.failed += 1
                assert report.errors is not None
                report.errors.append(f"{item.owner_type.value}:{item.owner_id}: {exc}")
                self._queue.mark_failed(item.id, str(exc), now=moment)
                continue

            self._queue.mark_uploaded(item.id, reference, now=moment)
            report.uploaded += 1
            if self._on_uploaded is not None:
                try:
                    self._on_uploaded(  # type: ignore[operator]
                        item.owner_type.value, item.owner_id, reference
                    )
                except Exception as exc:  # DB yeniləməsi sonra təkrar oluna bilər
                    _log.error(
                        "EVIDENCE_UPLOAD_CALLBACK_FAILED",
                        extra={
                            "owner_type": item.owner_type.value,
                            "owner_id": item.owner_id,
                            "error": str(exc),
                        },
                    )

        _log.info(
            "EVIDENCE_UPLOAD_RUN",
            extra={
                "attempted": report.attempted,
                "uploaded": report.uploaded,
                "failed": report.failed,
                "rejected": report.rejected,
            },
        )
        return report


__all__ = [
    "FALLBACK_CLAIM_STALE_AFTER_SECONDS",
    "EvidenceUploadQueue",
    "EvidenceUploadWorker",
    "PendingUpload",
    "UploadOwnerType",
    "UploadRunReport",
    "UploadStatus",
]
