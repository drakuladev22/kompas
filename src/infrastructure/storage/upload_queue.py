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

from src.infrastructure.offline.buffer import BACKOFF_SCHEDULE_SECONDS
from src.infrastructure.storage.google_drive import (
    MAX_UPLOAD_BYTES,
    EvidenceValidationError,
    validate_evidence_payload,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import FineId, StoreId
    from src.domain.value_objects.storage import StorageReference

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
    connection_id   TEXT
);
"""
_INDEX_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_evidence_ready
    ON evidence_uploads (status, next_attempt_at, seq);
"""
_SCHEMA: Final[str] = _TABLE_SQL + _INDEX_SQL

#: Cədvəl köçürməsində (bax `_ensure_rejected_status`) sütunlar AÇIQ sadalanır:
#: `INSERT INTO ... SELECT *` sütun sırasından asılıdır və gələcəkdə əlavə
#: olunacaq bir sütun köçürməni sükutla təhrif edərdi.
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
CLAIM_STALE_AFTER_SECONDS: Final[int] = 600


class UploadStatus(str, Enum):
    PENDING = "PENDING"
    #: Bir işçi elementi "claim" edib və hazırda yükləyir. `PENDING`
    #: seçimindən ÇIXIR — ikinci işçi eyni şəkli təkrar yükləyə bilmir.
    #: Çökmə halında köhnəlmə müddəti (`CLAIM_STALE_AFTER_SECONDS`) bitəndən
    #: sonra element yenidən claim edilə bilir — sonsuz ilişmə YOXDUR.
    PROCESSING = "PROCESSING"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"
    #: Fayl yararsızdır (ölçü/uzantı/imza) — TƏKRAR CƏHD EDİLMİR.
    #: `FAILED`-dən fərqi: o, backoff ilə növbəyə qayıdır, bu isə qayıtmır.
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class PendingUpload:
    id: str
    tenant_id: str
    fine_id: str
    store_id: str
    filename: str
    spool_path: Path
    taken_at: datetime
    attempts: int
    status: UploadStatus
    last_error: str | None = None

    def read_bytes(self) -> bytes:
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
        spool_dir: Path | str | None = None,
        backoff_schedule: tuple[int, ...] = BACKOFF_SCHEDULE_SECONDS,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        claim_stale_after_seconds: int = CLAIM_STALE_AFTER_SECONDS,
    ) -> None:
        """Args:
        max_upload_bytes: `enqueue()`-dəki ölçü həddi. Defolt `MAX_UPLOAD_BYTES`
            FALLBACK-dır (həqiqi mənbə `system_limits.MAX_UPLOAD_SIZE_BYTES`);
            provider öz həddini ayrıca tətbiq edir. Sıfır/mənfi dəyər həddi
            SÖNDÜRMÜR, defolta qaytarır — səhv konfiqurasiya qorumanı sükutla
            itirməməlidir (provider-dəki eyni qərar).
        claim_stale_after_seconds: `PROCESSING`-də ilişmiş elementin yenidən
            claim edilə biləcəyi müddət. Sıfır/mənfi dəyər defolta qaytarılır —
            əks halda element claim edilən kimi köhnəlmiş sayılar və qoruma
            (ikiqat yükləmənin qarşısını alan mexanizm) sükutla itərdi.
        """
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._spool = Path(spool_dir) if spool_dir else self._path.parent / "evidence_spool"
        self._spool.mkdir(parents=True, exist_ok=True)
        self._backoff = backoff_schedule
        self._max_upload_bytes = max_upload_bytes if max_upload_bytes > 0 else MAX_UPLOAD_BYTES
        self._claim_stale_after = (
            claim_stale_after_seconds
            if claim_stale_after_seconds > 0
            else CLAIM_STALE_AFTER_SECONDS
        )
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path, check_same_thread=False, isolation_level=None, timeout=10.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)
        self._ensure_rejected_status()
        self._ensure_processing_status()

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
        fine_id: FineId,
        store_id: StoreId,
        filename: str,
        content: bytes,
        taken_at: datetime,
        now: datetime | None = None,
    ) -> str:
        # ÖN-ŞƏRT DİSKƏ YAZMAZDAN ƏVVƏL: yararsız fayl növbəyə DÜŞMÜR.
        #
        # Qayda `google_drive.validate_evidence_payload`-dadır — provider ilə
        # EYNİ funksiya. Burada yoxlanmasaydı, fayl diskə düşər, `PENDING`
        # qalar və hər 10 dəqiqədən bir eyni cavabla rədd edilərdi (bax modul
        # başlığı). İstisna QƏSDƏN yuxarı ötürülür: operator səbəbi dərhal
        # ekranda görməlidir, cərimə isə sübutsuz yaradılmamalıdır.
        try:
            validate_evidence_payload(content, filename, max_bytes=self._max_upload_bytes)
        except EvidenceValidationError as error:
            _log.warning(
                "EVIDENCE_UPLOAD_REJECTED_AT_ENQUEUE",
                extra={"fine_id": str(fine_id), "bytes": len(content), "reason": str(error)},
            )
            raise

        moment = now or datetime.now(UTC)
        entry_id = str(uuid.uuid4())
        spool_path = self._spool / f"{entry_id}.bin"
        # Əvvəlcə DİSKƏ, sonra indeksə: tərsi olsaydı, aradakı çökmə
        # "növbədə var, faylı yoxdur" vəziyyəti yaradardı.
        spool_path.write_bytes(content)

        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM evidence_uploads"
            ).fetchone()
            conn.execute(
                """
                INSERT INTO evidence_uploads
                    (id, seq, tenant_id, fine_id, store_id, filename, spool_path,
                     taken_at, status, attempts, queued_at, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)
                """,
                (
                    entry_id,
                    int(row["n"]),
                    tenant_id,
                    str(fine_id),
                    str(store_id),
                    filename,
                    str(spool_path),
                    taken_at.isoformat(),
                    moment.isoformat(),
                    moment.isoformat(),
                ),
            )
        _log.info(
            "EVIDENCE_UPLOAD_QUEUED",
            extra={"fine_id": str(fine_id), "bytes": len(content)},
        )
        return entry_id

    # -------------------------------- oxuma ---------------------------------- #

    def pending(self, *, now: datetime | None = None, limit: int = 20) -> list[PendingUpload]:
        moment = now or datetime.now(UTC)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM evidence_uploads
                 WHERE status = 'PENDING' AND next_attempt_at <= ?
                 ORDER BY seq LIMIT ?
                """,
                (moment.isoformat(), limit),
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
        stale_at = moment + timedelta(seconds=self._claim_stale_after)
        with self._lock, self._transaction() as conn:
            rows = conn.execute(
                """
                SELECT * FROM evidence_uploads
                 WHERE next_attempt_at <= ?
                   AND status IN ('PENDING', 'PROCESSING')
                 ORDER BY seq LIMIT ?
                """,
                (moment.isoformat(), limit),
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
            delay = self._backoff[min(attempts - 1, len(self._backoff) - 1)]
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
    return PendingUpload(
        id=row["id"],
        tenant_id=row["tenant_id"],
        fine_id=row["fine_id"],
        store_id=row["store_id"],
        filename=row["filename"],
        spool_path=Path(row["spool_path"]),
        taken_at=datetime.fromisoformat(row["taken_at"]),
        attempts=row["attempts"],
        status=UploadStatus(row["status"]),
        last_error=row["last_error"],
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
        on_uploaded: `(fine_id: str, reference: StorageReference) -> None` —
            `fines` sətrini yeniləmək üçün geri çağırış.
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
                    item.read_bytes(),
                    item.filename,
                    _UUID(item.store_id),
                    item.taken_at,
                )
            except EvidenceValidationError as exc:
                # Fayl yararsızdır — şəbəkə/kvota problemi DEYİL. Gözləmək
                # nəticəni dəyişmədiyi üçün element daimi olaraq kənara
                # qoyulur (bax `mark_rejected`). Bura yalnız köhnə növbə
                # sətirləri və hədd sonradan aşağı salınan hallar düşür:
                # yeni element artıq `enqueue()`-dan keçmir.
                report.rejected += 1
                assert report.errors is not None
                report.errors.append(f"{item.fine_id}: {exc}")
                self._queue.mark_rejected(item.id, str(exc), now=moment)
                continue
            except Exception as exc:  # bir şəklin nasazlığı növbəni dayandırmasın
                report.failed += 1
                assert report.errors is not None
                report.errors.append(f"{item.fine_id}: {exc}")
                self._queue.mark_failed(item.id, str(exc), now=moment)
                continue

            self._queue.mark_uploaded(item.id, reference, now=moment)
            report.uploaded += 1
            if self._on_uploaded is not None:
                try:
                    self._on_uploaded(item.fine_id, reference)  # type: ignore[operator]
                except Exception as exc:  # DB yeniləməsi sonra təkrar oluna bilər
                    _log.error(
                        "EVIDENCE_UPLOAD_CALLBACK_FAILED",
                        extra={"fine_id": item.fine_id, "error": str(exc)},
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
    "CLAIM_STALE_AFTER_SECONDS",
    "EvidenceUploadQueue",
    "EvidenceUploadWorker",
    "PendingUpload",
    "UploadRunReport",
    "UploadStatus",
]
