"""Lokal SQLite offline buffer (spesifikasiya bölmə 5) — Faza 3.5.

Spesifikasiya: *"Local SQLite offline buffer yalnız connectivity yoxdursa
aktivləşir; hər yazı `sync_status` (`PENDING`, `SYNCED`, `CONFLICT`) sahəsi
ilə işarələnir."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ "OUTBOX", TAM OFFLINE KOPYA DEYİL
──────────────────────────────────────────────────────────────────────────────
İki mümkün yanaşma var:

    (a) bütün bazanın lokal replikası — offline oxumaq da mümkün olur,
    (b) yalnız YAZILARIN növbəsi (outbox) — offline yazmaq mümkün olur.

(a) seçilsəydi hər mağaza PC-sində bütün tenant-ın işçi/cərimə/maaş məlumatı
olardı: RLS-in bütün faydası itərdi və oğurlanan bir kiosk PC bütün şirkətin
məlumatını verərdi. Ona görə (b) seçilib — buferdə yalnız HƏMİN PC-də
yaradılmış yazılar dayanır və sinxronizasiyadan sonra silinir.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏLƏMƏ
──────────────────────────────────────────────────────────────────────────────
Bufer mağaza PC-sinin diskindədir və içində PII var (ad, PIN handshake vaxtı,
cərimə məbləği). `payload` AES-256-GCM ilə şifrələnir; AAD kontekstinə
`tenant_id:table:record_id` bağlanır — beləliklə şifrəli sahəni başqa sətrə
KÖÇÜRMƏK, həm də BAŞQA KİRAYƏÇİNİN kontekstində AÇMAQ mümkün olmur.

`tenant_id` AAD-ə SONRADAN əlavə edildi (D2 izolyasiya auditi). Əvvəlki
kontekst `offline:<cədvəl>:<id>` idi, yəni maşın tenant DƏYİŞDİRİLƏRƏK yenidən
quraşdırılsa köhnə kirayəçinin sətri yeni kontekstdə problemsiz açılırdı və
kripto qatı bunu TUTMURDU. Naxış `license_state:<tenant_id>`
(`licensing/state_store.py`) və `telegram_config:<tenant_id>`
(`persistence/telegram_repositories.py`) AAD-lərindən gəlir — orada kirayəçi
ARTIQ kontekstin bir hissəsidir.

GERİYƏ UYĞUNLUQ — MƏCBURİDİR: AAD-in dəyişməsi MÖVCUD şifrəli sətirləri
oxunmaz edərdi, halbuki onlar sinxronlaşdırılmamış davamiyyət/cərimə
yazılarıdır və heç yerdə başqa surətdə YOXDUR. Ona görə oxu iki addımlıdır —
əvvəlcə YENİ AAD sınanır, `DecryptionError` alınarsa KÖHNƏ AAD ilə açılır
(`EncryptionService._decrypt_legacy_fernet` ilə eyni fikir). YENİ yazılar
həmişə yeni formatdadır; köhnə sətirlər sinxronizasiyadan sonra `purge_synced`
ilə onsuz da silinir, yəni ayrıca köçürmə keçidi TƏLƏB OLUNMUR.

──────────────────────────────────────────────────────────────────────────────
DAVAMLILIQ (CRASH SAFETY)
──────────────────────────────────────────────────────────────────────────────
`journal_mode=WAL` + `synchronous=FULL`. Bufer dəqiqədə bir neçə yazı alır,
ona görə performans itkisi əhəmiyyətsizdir, elektrik kəsilməsində isə növbənin
itməməsi kritikdir (bu yazılar heç yerdə başqa surətdə mövcud deyil).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.time_integrity import APPROXIMATE_LEVELS, TimeTrustLevel
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_float,
    fallback_int_tuple,
    tenant_from_text,
)
from src.shared.exceptions import DecryptionError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.infrastructure.security.encryption import EncryptionService

_log = get_logger(__name__)

#: Cəhd sayına görə gözləmə (spesifikasiya bölmə 5: 30s → 2dq → 10dq).
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`OFFLINE_RETRY_BACKOFF_SECONDS`, seed: migrations/032). Cədvəl vergüllü
#: siyahıdır, çünki addımların SIRASI mənalıdır (bax
#: `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` əsaslandırması).
FALLBACK_BACKOFF_SCHEDULE_SECONDS: Final[tuple[int, ...]] = fallback_int_tuple(
    SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS
)

#: SQLite kilid gözləmə taymautu — FALLBACK; HƏQİQİ MƏNBƏ `system_limits`
#: (`OFFLINE_SQLITE_TIMEOUT_SECONDS`). Bufer faylı antivirus taramasına və ya
#: yavaş diskə düşəndə 10 saniyə çatmaya bilər; taymaut bitəndə `sqlite3`
#: "database is locked" atır və YAZI İTİR — məhz bu, offline-first-un
#: qorumalı olduğu haldır.
FALLBACK_SQLITE_TIMEOUT_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.OFFLINE_SQLITE_TIMEOUT_SECONDS
)

#: Bu cədvəllərdə "sonuncu yazan qalib gəlir" QADAĞANDIR (bölmə 5).
#:
#: Spesifikasiya üçünü sadalayır: `leave_requests`, `fines`, `audit_logs`.
#: `attendance_records` da əlavə edilib — gecikmə dəqiqələri birbaşa
#: `fines`-a çevrilir, yəni onu sükutla üzərinə yazmaq PUL dəyişdirmək
#: deməkdir. Sadalanan üçünü qorumaq, mənbəyini qorumamaq məntiqsiz olardı.
#:
#: ÜÇ CƏDVƏL SONRADAN ƏLAVƏ OLUNDU (AF-6) — eyni məntiqin davamı: hər üçünün
#: nəticəsi PULDUR və konfliktdə sükutla üzərinə yazılması real məbləği
#: dəyişərdi:
#:     * `points_ledger`          — xal → mükafat,
#:     * `overtime_log`           — aşım saatı → əlavə ödəniş,
#:     * `annual_leave_balances`  — qalıq gün → istifadə olunmamış günün ödənişi.
#:
#: NİYƏ İNDİ ƏLAVƏ OLUNUR, HALBUKİ ONLAR HƏLƏ `SYNCABLE_TABLES`-də YOXDUR
#: (`offline/sync.py`): bu siyahı cədvəlin XASSƏSİDİR («üzərinə yazılsa pul
#: dəyişir»), sinxronizasiya dəstinin surəti DEYİL. Sıra məhz belə təhlükəsizdir
#: — əks sıra (əvvəl `SYNCABLE_TABLES`-ə əlavə etmək, audit-kritikliyi sonraya
#: saxlamaq) həmin cədvəlin ilk konfliktini last-write-wins ilə həll edərdi və
#: itki yalnız maaş hesablanandan SONRA görünərdi.
AUDIT_CRITICAL_TABLES: Final[frozenset[str]] = frozenset(
    {
        "leave_requests",
        "fines",
        "audit_logs",
        "attendance_records",
        "points_ledger",
        "overtime_log",
        "annual_leave_balances",
    }
)

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS outbox (
    id                        TEXT PRIMARY KEY,
    seq                       INTEGER NOT NULL,
    tenant_id                 TEXT NOT NULL,
    table_name                TEXT NOT NULL,
    record_id                 TEXT NOT NULL,
    operation                 TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE')),
    payload_encrypted         TEXT NOT NULL,
    base_version              TEXT,
    sync_status               TEXT NOT NULL DEFAULT 'PENDING'
                                  CHECK (sync_status IN ('PENDING', 'SYNCED', 'CONFLICT')),
    attempts                  INTEGER NOT NULL DEFAULT 0,
    last_error                TEXT,
    queued_at                 TEXT NOT NULL,
    next_attempt_at           TEXT NOT NULL,
    synced_at                 TEXT,
    remote_version_encrypted  TEXT,
    -- TIME-1: yazının vaxt-möhürü hansı mənbədən gəldi. Oflayn növbənin
    -- MƏNASI budur ki, server əlçatmaz idi — yəni bu sütun tez-tez
    -- `SERVER_VERIFIED`-dən fərqli olacaq və bu, NORMALdır. Saxlanmasının
    -- səbəbi sonradan «bu qeyd nə vaxt yarandı» sualına dürüst cavab
    -- verməkdir: sinxronizasiya anındakı server vaxtı YARANMA anı DEYİL.
    time_trust_level          TEXT NOT NULL DEFAULT 'SERVER_VERIFIED'
);
CREATE INDEX IF NOT EXISTS idx_outbox_ready ON outbox (sync_status, next_attempt_at, seq);
CREATE INDEX IF NOT EXISTS idx_outbox_record ON outbox (table_name, record_id, sync_status);
CREATE TABLE IF NOT EXISTS outbox_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class SyncStatus(str, Enum):
    """`sync_status` enum-u — DB-dəki eyniadlı tiplə üst-üstə düşür."""

    PENDING = "PENDING"
    SYNCED = "SYNCED"
    CONFLICT = "CONFLICT"


class Operation(str, Enum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"


@dataclass(frozen=True)
class BufferedWrite:
    """Növbədəki bir yazı (payload artıq deşifrə olunub)."""

    id: str
    seq: int
    tenant_id: str
    table_name: str
    record_id: str
    operation: Operation
    payload: dict[str, Any]
    #: Yazı hazırlanarkən uzaq sətrin `updated_at`-ı. `None` → yeni qeyd.
    base_version: datetime | None
    status: SyncStatus
    attempts: int
    queued_at: datetime
    next_attempt_at: datetime
    last_error: str | None = None
    #: Konflikt halında uzaq versiyanın surəti (hər iki versiya saxlanılır).
    remote_version: dict[str, Any] | None = None
    #: Yazının vaxt-möhürünün mənbəyi (TIME-1). Sinxronizasiya anında DEYİL,
    #: YARANMA anında təyin olunur — sonradan bərpa etmək mümkün olmazdı.
    time_trust: TimeTrustLevel = TimeTrustLevel.SERVER_VERIFIED

    @property
    def is_audit_critical(self) -> bool:
        return self.table_name in AUDIT_CRITICAL_TABLES

    @property
    def has_approximate_time(self) -> bool:
        """Vaxtı təxminidirsə `True` — HR_Admin siyahısı bunu soruşur."""
        return self.time_trust in APPROXIMATE_LEVELS

    @property
    def record_key(self) -> tuple[str, str]:
        """Bloklama yoxlaması üçün açar — eyni sətrə aid yazılar birlikdə gedir."""
        return (self.table_name, self.record_id)

    def __repr__(self) -> str:
        # Payload PII saxlayır — `repr` loglara düşə bilər, ona görə gizlədilir.
        return (
            f"BufferedWrite(id={self.id}, table={self.table_name}, "
            f"record={self.record_id}, status={self.status.value}, "
            f"attempts={self.attempts}, payload=***REDACTED***)"
        )


class OfflineBuffer:
    """SQLite outbox — thread-safe, şifrəli payload."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        encryption: EncryptionService,
        backoff_schedule: tuple[int, ...] | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            backoff_schedule: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.

        SQLite taymautu BURADA — bağlantı qurularkən — həll olunur, çünki
        `sqlite3.connect()` onu sonradan qəbul etmir. Bufer prosesin ömrü
        boyu bir dəfə açılır; Root dəyişikliyi növbəti başlanğıcda qüvvəyə
        minir (backoff cədvəli isə hər cəhddə oxunur).
        """
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption = encryption
        self._explicit_backoff = backoff_schedule
        self._limits = limits or InfrastructureLimits()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
            timeout=self._limits.float_of(SystemLimitKey.OFFLINE_SQLITE_TIMEOUT_SECONDS),
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._upgrade_schema()
        _log.info("OFFLINE_BUFFER_OPENED", extra={"path": str(self._path)})

    def _upgrade_schema(self) -> None:
        """Mövcud SQLite fayllarına sonradan gələn sütunları əlavə edir.

        `CREATE TABLE IF NOT EXISTS` MÖVCUD cədvələ sütun ƏLAVƏ ETMİR — o,
        cədvəl varsa heç nə etmir. Yəni yeni sütun yalnız TƏMİZ quraşdırmada
        yaranardı və yenilənən mağazada `no such column` ilə çökərdi. Bufer
        faylı isə paylaşılan məlumat qovluğundadır (`%PROGRAMDATA%\\KompasOS\\
        data`, bax `shared/data_paths.py`): onu silmək sinxronlaşdırılmamış
        davamiyyət qeydlərini silmək deməkdir.

        Postgres tərəfdəki `database/migrations/` mexanizmi buraya
        gətirilmədi: burada bir SQLite faylı və bir neçə sütun var, versiya
        ağacı deyil (eyni qərar `migrations/061`-də Alembic üçün verilmişdi).
        """
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(outbox)")}
        if "time_trust_level" not in existing:
            self._conn.execute(
                "ALTER TABLE outbox ADD COLUMN time_trust_level TEXT "
                "NOT NULL DEFAULT 'SERVER_VERIFIED'"
            )
            _log.info("OFFLINE_BUFFER_SCHEMA_UPGRADED", extra={"column": "time_trust_level"})

    def _backoff_schedule(self, tenant_id: str | None = None) -> tuple[int, ...]:
        """Təkrar cəhd cədvəli — HƏR UĞURSUZLUQDA oxunur.

        Bufer prosesin bütün ömrü boyu açıq qalır; cədvəli konstruktorda
        dondursaydıq, Root-un dəyişikliyi yalnız tətbiq yenidən açılanda
        qüvvəyə minərdi — halbuki dəyişiklik məhz uzun-sürən offline
        dövründə lazım olur.

        Args:
            tenant_id: SAAS-5 — cədvəl SƏTRİN kirayəçisindən oxunur. Bufer
                faylı MAŞINA aiddir və içində birdən çox kirayəçinin sətri ola
                bilər (bax `_tenant_clause`); paylaşılan `InfrastructureLimits`
                nüsxəsi isə tək kirayəçiyə bağlıdır. Bağlamanı sətir üzrə
                dəyişmək «hansı müştərinin gözləmə cədvəli tətbiq olunur»
                sualını koddan görünən edir. Mətn UUID deyilsə mövcud bağlama
                saxlanılır.
        """
        if self._explicit_backoff is not None:
            return self._explicit_backoff
        limits = self._limits.for_tenant(tenant_from_text(tenant_id))
        return limits.int_tuple_of(SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------------------------------- yazma ---------------------------------- #

    def enqueue(
        self,
        *,
        tenant_id: str,
        table_name: str,
        record_id: str,
        operation: Operation,
        payload: dict[str, Any],
        base_version: datetime | None = None,
        now: datetime | None = None,
        time_trust: TimeTrustLevel = TimeTrustLevel.SERVER_VERIFIED,
    ) -> str:
        """Yazını növbəyə salır və onun `id`-sini qaytarır.

        Args:
            time_trust: yazının vaxt-möhürünün mənbəyi (TIME-1). Defolt
                `SERVER_VERIFIED`-dir, çünki bufer YALNIZ oflayn halda deyil,
                keçici şəbəkə nasazlığında da işlədilir — çağıran tərəf
                vəziyyəti bilirsə onu AÇIQ ötürür. Defolt olaraq `UNTRUSTED`
                seçmək bütün növbəni şübhəli göstərərdi və işarə mənasını
                itirərdi.
        """
        moment = now or datetime.now(UTC)
        entry_id = str(uuid.uuid4())
        token = self._encryption.encrypt(
            json.dumps(payload, ensure_ascii=False, default=str),
            context=self._aad(tenant_id, table_name, record_id),
        )
        with self._lock, self._transaction() as conn:
            seq = self._next_seq(conn)
            conn.execute(
                """
                INSERT INTO outbox (
                    id, seq, tenant_id, table_name, record_id, operation,
                    payload_encrypted, base_version, sync_status, attempts,
                    queued_at, next_attempt_at, time_trust_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?)
                """,
                (
                    entry_id,
                    seq,
                    tenant_id,
                    table_name,
                    record_id,
                    operation.value,
                    token,
                    base_version.isoformat() if base_version else None,
                    moment.isoformat(),
                    moment.isoformat(),
                    time_trust.value,
                ),
            )
        _log.info(
            "OFFLINE_WRITE_QUEUED",
            extra={
                "table": table_name,
                "record_id": record_id,
                "operation": operation.value,
                "time_trust_level": time_trust.value,
            },
        )
        return entry_id

    # -------------------------------- oxuma ---------------------------------- #

    def pending(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> list[BufferedWrite]:
        """Sinxronizasiyaya HAZIR yazılar — FIFO sırası ilə.

        Konfliktdə qalmış qeydi olan `record_id` üçün SONRAKI yazılar da
        buraxılır: onlar həll olunmamış vəziyyətin üzərinə tikilib, ardıcıl
        tətbiq edilsə məlumatı korlayardılar.

        Args:
            tenant_id: verilərsə YALNIZ həmin kirayəçinin sətirləri
                (`_tenant_clause`). Bloklama yoxlaması DA süzülür — əks halda
                BAŞQA kirayəçinin həll olunmamış konflikti bu kirayəçinin
                növbəsini dayandırardı (ID-lər UUID olsa da qayda "eyni sətir"
                haqqındadır, "eyni ada malik sətir" haqqında yox).
        """
        moment = now or datetime.now(UTC)
        clause, clause_params = self._tenant_clause(tenant_id)
        with self._lock:
            blocked = {
                (row["table_name"], row["record_id"])
                for row in self._conn.execute(
                    # `clause` sabit İKİ variantdan biridir (`_tenant_clause`).
                    f"""
                    SELECT DISTINCT table_name, record_id FROM outbox
                     WHERE sync_status = 'CONFLICT'{clause}
                    """,  # noqa: S608 — şərtlər sabit siyahıdandır
                    clause_params,
                )
            }
            rows = self._conn.execute(
                f"""
                SELECT * FROM outbox
                 WHERE sync_status = 'PENDING' AND next_attempt_at <= ?{clause}
                 ORDER BY seq
                 LIMIT ?
                """,  # noqa: S608 — şərtlər sabit siyahıdandır
                (moment.isoformat(), *clause_params, limit),
            ).fetchall()
        return [write for row in rows if (write := self._to_write(row)).record_key not in blocked]

    def conflicts(self, *, tenant_id: str | None = None) -> list[BufferedWrite]:
        """HR_Admin-in manual həlli gözləyən yazılar (bölmə 5).

        Args:
            tenant_id: verilərsə YALNIZ həmin kirayəçinin konfliktləri — bir
                müştərinin HR_Admin-i digərinin yazısını (payload-da ad, məbləğ
                var) siyahıda GÖRMƏMƏLİDİR.
        """
        clause, clause_params = self._tenant_clause(tenant_id)
        with self._lock:
            rows = self._conn.execute(
                # `clause` sabit İKİ variantdan biridir (`_tenant_clause`).
                f"SELECT * FROM outbox WHERE sync_status = 'CONFLICT'{clause} "  # noqa: S608
                "ORDER BY seq",
                clause_params,
            ).fetchall()
        return [self._to_write(row) for row in rows]

    def counts(self, *, tenant_id: str | None = None) -> dict[str, int]:
        """System Health Monitor üçün sayğaclar.

        Args:
            tenant_id: verilərsə YALNIZ həmin kirayəçinin sətirləri sayılır —
                əks halda ekrandakı "gözləyən yazı" rəqəmi başqa quraşdırmanın
                qalıq sətirlərini də göstərər və admin heç vaxt boşalmayan
                növbə görərdi.
        """
        clause, clause_params = self._tenant_clause(tenant_id)
        with self._lock:
            rows = self._conn.execute(
                # `WHERE 1 = 1` sabit şərtin AND-lə birləşməsi üçündür:
                # `_tenant_clause` hər yerdə EYNİ formatı (` AND ...`) qaytarır
                # ki, çağırış yerlərində iki fərqli yığma qaydası yaranmasın.
                f"SELECT sync_status, COUNT(*) AS n FROM outbox "  # noqa: S608
                f"WHERE 1 = 1{clause} GROUP BY sync_status",
                clause_params,
            ).fetchall()
        counts = {status.value: 0 for status in SyncStatus}
        for row in rows:
            counts[row["sync_status"]] = row["n"]
        return counts

    def oldest_pending_queued_at(self, *, tenant_id: str | None = None) -> datetime | None:
        """Ən köhnə GÖZLƏYƏN yazının növbəyə düşmə anı — Faza 5.1.

        `counts()` «neçə sətir» sualına cavab verir, bu isə «nə qədərdir»
        sualına. İKİSİ AYRIDIR VƏ HƏR İKİSİ LAZIMDIR: bir kassa səhəri boyu
        şəbəkəsiz işləyən mağaza AZ sətirlə UZUN müddət, bir günlük
        inventarizasiya isə QISA müddətdə ÇOX sətir yığır — biri digərini
        görmür (`OFFLINE_BACKLOG_MAX_HOURS` / `..._MAX_ENTRIES`).

        `next_attempt_at` YOX, `queued_at` ölçülür: təkrar cəhd cədvəli
        (backoff) uğursuzluqda gələcəyə sürüşür və o rəqəmlə yaş HƏMİŞƏ
        kiçik görünərdi — halbuki sual «bu məlumat nə vaxtdan bəri serverə
        çatmayıb».
        """
        clause, clause_params = self._tenant_clause(tenant_id)
        with self._lock:
            row = self._conn.execute(
                # `clause` sabit İKİ variantdan biridir (`_tenant_clause`).
                f"""
                SELECT MIN(queued_at) AS oldest FROM outbox
                 WHERE sync_status = 'PENDING'{clause}
                """,  # noqa: S608 — şərtlər sabit siyahıdandır
                clause_params,
            ).fetchone()
        if row is None or row["oldest"] is None:
            return None
        return datetime.fromisoformat(row["oldest"])

    def read_meta(self, key: str) -> str | None:
        """`outbox_meta` — bufer faylının öz kiçik açar/dəyər yaddaşı.

        NİYƏ BURADA: xəbərdarlıq təkrar-susma anı (Faza 5.1) OFFLINE
        vəziyyətdə YAZILMALIDIR — Postgres-dəki bir sütun məhz o an əlçatmaz
        olur. `outbox_meta` cədvəli sxemdə ARTIQ var idi (`_SCHEMA`), yalnız
        oxuyucusu yox idi.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM outbox_meta WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else None

    def write_meta(self, key: str, value: str) -> None:
        """`outbox_meta`-ya UPSERT."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO outbox_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get(self, entry_id: str) -> BufferedWrite | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM outbox WHERE id = ?", (entry_id,)).fetchone()
        return self._to_write(row) if row else None

    # ------------------------------ vəziyyət --------------------------------- #

    def mark_synced(self, entry_id: str, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            conn.execute(
                """UPDATE outbox
                      SET sync_status = 'SYNCED', synced_at = ?, last_error = NULL
                    WHERE id = ?""",
                (moment.isoformat(), entry_id),
            )

    def mark_failed(self, entry_id: str, error: str, *, now: datetime | None = None) -> datetime:
        """Cəhdi artırır və eksponensial gözləmə təyin edir. Növbəti cəhd anını qaytarır."""
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT attempts, tenant_id FROM outbox WHERE id = ?", (entry_id,)
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            schedule = self._backoff_schedule(row["tenant_id"] if row else None)
            delay = schedule[min(attempts - 1, len(schedule) - 1)]
            next_at = moment + timedelta(seconds=delay)
            conn.execute(
                """UPDATE outbox
                      SET attempts = ?, last_error = ?, next_attempt_at = ?
                    WHERE id = ?""",
                (attempts, error[:500], next_at.isoformat(), entry_id),
            )
        _log.warning(
            "OFFLINE_SYNC_RETRY_SCHEDULED",
            extra={"entry_id": entry_id, "attempts": attempts, "delay_seconds": delay},
        )
        return next_at

    def mark_conflict(
        self,
        entry_id: str,
        *,
        remote_version: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        """Hər iki versiyanı saxlayır və manual həll üçün işarələyir (bölmə 5)."""
        moment = now or datetime.now(UTC)
        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT tenant_id, table_name, record_id FROM outbox WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return
            # Uzaq versiya da sətrin ÖZ kirayəçisinə bağlanır — payload ilə
            # eyni AAD. Köhnə formatda yazılmış sətrin uzaq versiyası yeni
            # formatda yazılır və `_decrypt_field` hər iki sahəni AYRI-AYRI
            # sınadığı üçün qarışıq sətir də problemsiz oxunur.
            token = self._encryption.encrypt(
                json.dumps(remote_version, ensure_ascii=False, default=str),
                context=self._aad(row["tenant_id"], row["table_name"], row["record_id"]),
            )
            conn.execute(
                """UPDATE outbox
                      SET sync_status = 'CONFLICT',
                          remote_version_encrypted = ?,
                          last_error = 'Uzaq versiya dəyişib — manual həll tələb olunur',
                          next_attempt_at = ?
                    WHERE id = ?""",
                (token, moment.isoformat(), entry_id),
            )
        _log.error(
            "OFFLINE_SYNC_CONFLICT",
            extra={
                "entry_id": entry_id,
                "table": row["table_name"],
                "record_id": row["record_id"],
                "action": "HR_Admin manual həlli gözlənilir",
            },
        )

    def resolve_conflict(self, entry_id: str, *, keep_local: bool) -> None:
        """HR_Admin qərarını tətbiq edir.

        `keep_local=True`  → yazı yenidən növbəyə düşür (təzə əsasla).
        `keep_local=False` → yerli versiya atılır, uzaq versiya qalır.
        """
        with self._lock, self._transaction() as conn:
            if keep_local:
                conn.execute(
                    """UPDATE outbox
                          SET sync_status = 'PENDING', attempts = 0, base_version = NULL,
                              last_error = NULL, next_attempt_at = ?
                        WHERE id = ?""",
                    (datetime.now(UTC).isoformat(), entry_id),
                )
            else:
                conn.execute(
                    """UPDATE outbox
                          SET sync_status = 'SYNCED', synced_at = ?,
                              last_error = 'Uzaq versiya saxlanıldı (KEPT_REMOTE)'
                        WHERE id = ?""",
                    (datetime.now(UTC).isoformat(), entry_id),
                )
        _log.info(
            "OFFLINE_CONFLICT_RESOLVED",
            extra={
                "entry_id": entry_id,
                "resolution": "KEPT_LOCAL" if keep_local else "KEPT_REMOTE",
            },
        )

    def purge_synced(self, *, older_than: datetime, tenant_id: str | None = None) -> int:
        """Sinxronlaşmış yazıları silir — bufer PII-ni lazımsız saxlamamalıdır.

        Args:
            tenant_id: verilərsə YALNIZ həmin kirayəçinin sətirləri silinir.
                Silmə əməliyyatında filtr xüsusilə vacibdir: filtrsiz çağırış
                bir müştərinin təmizləmə əməliyyatını DİGƏRİNİN sətirlərinə
                də tətbiq edərdi.
        """
        clause, clause_params = self._tenant_clause(tenant_id)
        with self._lock, self._transaction() as conn:
            cursor = conn.execute(
                # `clause` sabit İKİ variantdan biridir (`_tenant_clause`).
                f"DELETE FROM outbox WHERE sync_status = 'SYNCED' "  # noqa: S608
                f"AND synced_at < ?{clause}",
                (older_than.isoformat(), *clause_params),
            )
            deleted = cursor.rowcount
        if deleted:
            _log.info("OFFLINE_BUFFER_PURGED", extra={"deleted": deleted})
        return deleted

    # ------------------------------- daxili ---------------------------------- #

    @staticmethod
    def _aad(tenant_id: str, table_name: str, record_id: str) -> str:
        """Şifrələmə konteksti — kirayəçi DAXİLDİR (bax modul başlığı)."""
        return f"offline:{tenant_id}:{table_name}:{record_id}"

    @staticmethod
    def _legacy_aad(table_name: str, record_id: str) -> str:
        """Kirayəçisiz KÖHNƏ kontekst — YALNIZ OXU yolunda, ehtiyat variant kimi.

        Yazı yolunda İSTİFADƏ EDİLMİR: köhnə formatda yeni sətir yaratmaq
        düzəlişi mənasız edərdi. Metod SİLİNMİR — mağazada aylarla oflayn
        qalmış bufer faylı yenilənmiş tətbiqlə açıla bilər.
        """
        return f"offline:{table_name}:{record_id}"

    def _decrypt_field(self, row: sqlite3.Row, column: str) -> str:
        """Şifrəli sahəni açır: ƏVVƏLCƏ yeni AAD, uğursuz olarsa KÖHNƏ.

        Sıra qəsdən BELƏDİR — yeni format hər yazıda yaranır, köhnəsi isə
        yalnız keçid dövründə mövcuddur. Tərs sıra hər oxuda bir artıq
        (uğursuz) deşifrə cəhdi demək olardı.

        Köhnə AAD də uğursuz olarsa istisna ÖTÜRÜLÜR: bu artıq keçid halı
        deyil, faylın dəyişdirilməsi və ya açarın itməsi əlamətidir — sükutla
        boş payload qaytarmaq həmin yazını itirmək olardı.
        """
        token = row[column]
        try:
            return self._encryption.decrypt(
                token,
                context=self._aad(row["tenant_id"], row["table_name"], row["record_id"]),
            )
        except DecryptionError:
            plaintext = self._encryption.decrypt(
                token, context=self._legacy_aad(row["table_name"], row["record_id"])
            )
            _log.info(
                "OFFLINE_BUFFER_LEGACY_AAD_READ",
                extra={
                    "entry_id": row["id"],
                    "column": column,
                    "reason": "kirayəçisiz KÖHNƏ AAD — sətir yeni formata YAZILMADAN oxundu",
                },
            )
            return plaintext

    @staticmethod
    def _tenant_clause(tenant_id: str | None) -> tuple[str, tuple[str, ...]]:
        """`AND`-lə başlayan kirayəçi şərti + parametrləri (D2 izolyasiya).

        Naxış `EvidenceUploadQueue._tenant_clause()`-un eynidir: `None` halı
        KÖHNƏ (filtrsiz) davranışı saxlayır və YALNIZ kirayəçiyə əhəmiyyət
        verməyən çağırışlar üçündür (diaqnostika, testlər). İstehsalat yolu —
        `BufferDrainAdapter` — `tenant_id`-ni HƏMİŞƏ ötürür.
        """
        if tenant_id is None:
            return "", ()
        return " AND tenant_id = ?", (tenant_id,)

    def _transaction(self) -> _SqliteTransaction:
        return _SqliteTransaction(self._conn)

    @staticmethod
    def _next_seq(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM outbox").fetchone()
        return int(row["n"])

    def _to_write(self, row: sqlite3.Row) -> BufferedWrite:
        payload = json.loads(self._decrypt_field(row, "payload_encrypted"))
        remote: dict[str, Any] | None = None
        if row["remote_version_encrypted"]:
            remote = json.loads(self._decrypt_field(row, "remote_version_encrypted"))
        write = BufferedWrite(
            id=row["id"],
            seq=row["seq"],
            tenant_id=row["tenant_id"],
            table_name=row["table_name"],
            record_id=row["record_id"],
            operation=Operation(row["operation"]),
            payload=payload,
            base_version=(
                datetime.fromisoformat(row["base_version"]) if row["base_version"] else None
            ),
            status=SyncStatus(row["sync_status"]),
            attempts=row["attempts"],
            queued_at=datetime.fromisoformat(row["queued_at"]),
            next_attempt_at=datetime.fromisoformat(row["next_attempt_at"]),
            last_error=row["last_error"],
            remote_version=remote,
            time_trust=TimeTrustLevel(row["time_trust_level"]),
        )
        return write


class _SqliteTransaction:
    """`BEGIN IMMEDIATE` — eyni faylı açan ikinci proses gözləsin, xəta verməsin."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            self._conn.execute("ROLLBACK")


def iter_backoff(schedule: tuple[int, ...] = FALLBACK_BACKOFF_SCHEDULE_SECONDS) -> Iterator[int]:
    """Cədvəli verir, sonuncu dəyəri təkrarlayır (sonsuz geri çəkilmə yoxdur)."""
    yield from schedule
    while True:
        yield schedule[-1]


__all__ = [
    "AUDIT_CRITICAL_TABLES",
    "FALLBACK_BACKOFF_SCHEDULE_SECONDS",
    "FALLBACK_SQLITE_TIMEOUT_SECONDS",
    "BufferedWrite",
    "OfflineBuffer",
    "Operation",
    "SyncStatus",
    "iter_backoff",
]
