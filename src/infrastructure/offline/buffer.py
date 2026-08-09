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
`table:record_id` bağlanır — beləliklə şifrəli sahəni başqa sətrə köçürmək
mümkün olmur.

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

from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.infrastructure.security.encryption import EncryptionService

_log = get_logger(__name__)

#: Cəhd sayına görə gözləmə (spesifikasiya bölmə 5: 30s → 2dq → 10dq).
BACKOFF_SCHEDULE_SECONDS: Final[tuple[int, ...]] = (30, 120, 600)

#: Bu cədvəllərdə "sonuncu yazan qalib gəlir" QADAĞANDIR (bölmə 5).
#:
#: Spesifikasiya üçünü sadalayır: `leave_requests`, `fines`, `audit_logs`.
#: `attendance_records` da əlavə edilib — gecikmə dəqiqələri birbaşa
#: `fines`-a çevrilir, yəni onu sükutla üzərinə yazmaq PUL dəyişdirmək
#: deməkdir. Sadalanan üçünü qorumaq, mənbəyini qorumamaq məntiqsiz olardı.
AUDIT_CRITICAL_TABLES: Final[frozenset[str]] = frozenset(
    {"leave_requests", "fines", "audit_logs", "attendance_records"}
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
    remote_version_encrypted  TEXT
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

    @property
    def is_audit_critical(self) -> bool:
        return self.table_name in AUDIT_CRITICAL_TABLES

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
        backoff_schedule: tuple[int, ...] = BACKOFF_SCHEDULE_SECONDS,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption = encryption
        self._backoff = backoff_schedule
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path, check_same_thread=False, isolation_level=None, timeout=10.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        _log.info("OFFLINE_BUFFER_OPENED", extra={"path": str(self._path)})

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
    ) -> str:
        """Yazını növbəyə salır və onun `id`-sini qaytarır."""
        moment = now or datetime.now(UTC)
        entry_id = str(uuid.uuid4())
        token = self._encryption.encrypt(
            json.dumps(payload, ensure_ascii=False, default=str),
            context=self._aad(table_name, record_id),
        )
        with self._lock, self._transaction() as conn:
            seq = self._next_seq(conn)
            conn.execute(
                """
                INSERT INTO outbox (
                    id, seq, tenant_id, table_name, record_id, operation,
                    payload_encrypted, base_version, sync_status, attempts,
                    queued_at, next_attempt_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)
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
                ),
            )
        _log.info(
            "OFFLINE_WRITE_QUEUED",
            extra={"table": table_name, "record_id": record_id, "operation": operation.value},
        )
        return entry_id

    # -------------------------------- oxuma ---------------------------------- #

    def pending(self, *, now: datetime | None = None, limit: int = 100) -> list[BufferedWrite]:
        """Sinxronizasiyaya HAZIR yazılar — FIFO sırası ilə.

        Konfliktdə qalmış qeydi olan `record_id` üçün SONRAKI yazılar da
        buraxılır: onlar həll olunmamış vəziyyətin üzərinə tikilib, ardıcıl
        tətbiq edilsə məlumatı korlayardılar.
        """
        moment = now or datetime.now(UTC)
        with self._lock:
            blocked = {
                (row["table_name"], row["record_id"])
                for row in self._conn.execute(
                    "SELECT DISTINCT table_name, record_id FROM outbox "
                    "WHERE sync_status = 'CONFLICT'"
                )
            }
            rows = self._conn.execute(
                """
                SELECT * FROM outbox
                 WHERE sync_status = 'PENDING' AND next_attempt_at <= ?
                 ORDER BY seq
                 LIMIT ?
                """,
                (moment.isoformat(), limit),
            ).fetchall()
        return [write for row in rows if (write := self._to_write(row)).record_key not in blocked]

    def conflicts(self) -> list[BufferedWrite]:
        """HR_Admin-in manual həlli gözləyən yazılar (bölmə 5)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM outbox WHERE sync_status = 'CONFLICT' ORDER BY seq"
            ).fetchall()
        return [self._to_write(row) for row in rows]

    def counts(self) -> dict[str, int]:
        """System Health Monitor üçün sayğaclar."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT sync_status, COUNT(*) AS n FROM outbox GROUP BY sync_status"
            ).fetchall()
        counts = {status.value: 0 for status in SyncStatus}
        for row in rows:
            counts[row["sync_status"]] = row["n"]
        return counts

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
            row = conn.execute("SELECT attempts FROM outbox WHERE id = ?", (entry_id,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            delay = self._backoff[min(attempts - 1, len(self._backoff) - 1)]
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
                "SELECT table_name, record_id FROM outbox WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return
            token = self._encryption.encrypt(
                json.dumps(remote_version, ensure_ascii=False, default=str),
                context=self._aad(row["table_name"], row["record_id"]),
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

    def purge_synced(self, *, older_than: datetime) -> int:
        """Sinxronlaşmış yazıları silir — bufer PII-ni lazımsız saxlamamalıdır."""
        with self._lock, self._transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM outbox WHERE sync_status = 'SYNCED' AND synced_at < ?",
                (older_than.isoformat(),),
            )
            deleted = cursor.rowcount
        if deleted:
            _log.info("OFFLINE_BUFFER_PURGED", extra={"deleted": deleted})
        return deleted

    # ------------------------------- daxili ---------------------------------- #

    @staticmethod
    def _aad(table_name: str, record_id: str) -> str:
        return f"offline:{table_name}:{record_id}"

    def _transaction(self) -> _SqliteTransaction:
        return _SqliteTransaction(self._conn)

    @staticmethod
    def _next_seq(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM outbox").fetchone()
        return int(row["n"])

    def _to_write(self, row: sqlite3.Row) -> BufferedWrite:
        payload = json.loads(
            self._encryption.decrypt(
                row["payload_encrypted"],
                context=self._aad(row["table_name"], row["record_id"]),
            )
        )
        remote: dict[str, Any] | None = None
        if row["remote_version_encrypted"]:
            remote = json.loads(
                self._encryption.decrypt(
                    row["remote_version_encrypted"],
                    context=self._aad(row["table_name"], row["record_id"]),
                )
            )
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


def iter_backoff(schedule: tuple[int, ...] = BACKOFF_SCHEDULE_SECONDS) -> Iterator[int]:
    """Cədvəli verir, sonuncu dəyəri təkrarlayır (sonsuz geri çəkilmə yoxdur)."""
    yield from schedule
    while True:
        yield schedule[-1]


__all__ = [
    "AUDIT_CRITICAL_TABLES",
    "BACKOFF_SCHEDULE_SECONDS",
    "BufferedWrite",
    "OfflineBuffer",
    "Operation",
    "SyncStatus",
    "iter_backoff",
]
