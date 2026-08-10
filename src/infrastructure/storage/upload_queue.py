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
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.infrastructure.offline.buffer import BACKOFF_SCHEDULE_SECONDS
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import FineId, StoreId
    from src.domain.value_objects.storage import StorageReference

_log = get_logger(__name__)

_SCHEMA: Final[str] = """
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
                        CHECK (status IN ('PENDING', 'UPLOADED', 'FAILED')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    queued_at       TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    uploaded_at     TEXT,
    drive_file_id   TEXT,
    connection_id   TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_ready
    ON evidence_uploads (status, next_attempt_at, seq);
"""


class UploadStatus(str, Enum):
    PENDING = "PENDING"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"


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
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._spool = Path(spool_dir) if spool_dir else self._path.parent / "evidence_spool"
        self._spool.mkdir(parents=True, exist_ok=True)
        self._backoff = backoff_schedule
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path, check_same_thread=False, isolation_level=None, timeout=10.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)

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
                """UPDATE evidence_uploads
                      SET attempts = ?, last_error = ?, next_attempt_at = ?
                    WHERE id = ?""",
                (attempts, error[:500], next_at.isoformat(), entry_id),
            )
        _log.warning(
            "EVIDENCE_UPLOAD_RETRY",
            extra={"entry_id": entry_id, "attempts": attempts, "delay_seconds": delay},
        )
        return next_at

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
        items = self._queue.pending(now=moment, limit=self._batch_size)
        if not items:
            return report

        try:
            provider = self._factory.active()  # type: ignore[attr-defined]
        except Exception as exc:  # aktiv bağlantı yoxdur / token problemi
            report.skipped_no_connection = True
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
            },
        )
        return report


__all__ = [
    "EvidenceUploadQueue",
    "EvidenceUploadWorker",
    "PendingUpload",
    "UploadRunReport",
    "UploadStatus",
]
