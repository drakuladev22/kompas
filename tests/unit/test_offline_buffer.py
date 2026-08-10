"""SQLite offline bufer testləri (Faza 3.5)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from src.infrastructure.offline.buffer import (
    AUDIT_CRITICAL_TABLES,
    BufferedWrite,
    OfflineBuffer,
    Operation,
    SyncStatus,
)
from src.infrastructure.security.encryption import EncryptionService, KeyMaterial, generate_key
from src.shared.exceptions import DecryptionError

if TYPE_CHECKING:
    from collections.abc import Iterator

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class _StaticProvider:
    name = "static"

    def __init__(self, material: KeyMaterial) -> None:
        self._material = material

    def load(self) -> KeyMaterial:
        return self._material


@pytest.fixture
def encryption() -> EncryptionService:
    return EncryptionService(_StaticProvider(KeyMaterial(primary=generate_key())))  # type: ignore[arg-type]


@pytest.fixture
def buffer(tmp_path: Path, encryption: EncryptionService) -> Iterator[OfflineBuffer]:
    buf = OfflineBuffer(tmp_path / "offline.db", encryption=encryption)
    yield buf
    buf.close()


def enqueue(
    buf: OfflineBuffer,
    *,
    table: str = "attendance_records",
    record_id: str = "11111111-1111-1111-1111-111111111111",
    payload: dict[str, object] | None = None,
    base_version: datetime | None = None,
    now: datetime = T0,
) -> str:
    return buf.enqueue(
        tenant_id="22222222-2222-2222-2222-222222222222",
        table_name=table,
        record_id=record_id,
        operation=Operation.UPDATE,
        payload=payload or {"check_in_status": "PENDING_VERIFICATION"},
        base_version=base_version,
        now=now,
    )


# --------------------------------------------------------------------------- #
# Əsas axın
# --------------------------------------------------------------------------- #


def test_enqueued_write_is_pending_and_readable(buffer: OfflineBuffer) -> None:
    entry_id = enqueue(buffer, payload={"late_minutes": 12})

    pending = buffer.pending(now=T0)
    assert len(pending) == 1
    assert pending[0].id == entry_id
    assert pending[0].status is SyncStatus.PENDING
    assert pending[0].payload == {"late_minutes": 12}


def test_fifo_order_is_preserved(buffer: OfflineBuffer) -> None:
    """Eyni sətrə iki yazı tərs sıra ilə tətbiq olunsa məlumat korlanır."""
    first = enqueue(buffer, payload={"step": 1})
    second = enqueue(buffer, payload={"step": 2}, now=T0 + timedelta(seconds=1))

    assert [w.id for w in buffer.pending(now=T0 + timedelta(minutes=1))] == [first, second]


def test_mark_synced_removes_from_pending(buffer: OfflineBuffer) -> None:
    entry_id = enqueue(buffer)
    buffer.mark_synced(entry_id, now=T0)

    assert buffer.pending(now=T0) == []
    assert buffer.counts()[SyncStatus.SYNCED.value] == 1


def test_counts_for_health_monitor(buffer: OfflineBuffer) -> None:
    enqueue(buffer, record_id="a" * 8)
    synced = enqueue(buffer, record_id="b" * 8)
    buffer.mark_synced(synced, now=T0)

    counts = buffer.counts()
    assert counts == {"PENDING": 1, "SYNCED": 1, "CONFLICT": 0}


# --------------------------------------------------------------------------- #
# Şifrələmə
# --------------------------------------------------------------------------- #


def test_payload_is_encrypted_at_rest(tmp_path: Path, encryption: EncryptionService) -> None:
    """Oğurlanan kiosk PC-si açıq PII verməməlidir."""
    path = tmp_path / "offline.db"
    buf = OfflineBuffer(path, encryption=encryption)
    enqueue(buf, payload={"employee_name": "Rəşad Məmmədov", "fine_amount": "50.00"})
    buf.close()

    raw = path.read_bytes()
    assert b"Rashad" not in raw
    assert "Rəşad Məmmədov".encode() not in raw
    assert b"50.00" not in raw


def test_payload_cannot_be_moved_between_records(
    tmp_path: Path, encryption: EncryptionService
) -> None:
    """AAD kontekstinə `table:record_id` bağlanıb — köçürmə deşifrəni pozur."""
    path = tmp_path / "offline.db"
    buf = OfflineBuffer(path, encryption=encryption)
    victim = enqueue(buf, record_id="aaaaaaaa-0000-0000-0000-000000000001")
    enqueue(buf, record_id="bbbbbbbb-0000-0000-0000-000000000002", payload={"late_minutes": 999})

    with sqlite3.connect(path) as conn:
        stolen = conn.execute(
            "SELECT payload_encrypted FROM outbox WHERE record_id LIKE 'bbbb%'"
        ).fetchone()[0]
        conn.execute("UPDATE outbox SET payload_encrypted = ? WHERE id = ?", (stolen, victim))
        conn.commit()

    with pytest.raises(DecryptionError):
        buf.get(victim)
    buf.close()


def test_repr_does_not_leak_payload(buffer: OfflineBuffer) -> None:
    enqueue(buffer, payload={"pin": "1234", "salary": "3000"})
    write = buffer.pending(now=T0)[0]

    text = repr(write)
    # Identifikatorlar ÇIXARILIR: onlar UUID-dir və təsadüfən "1234" kimi
    # onaltılıq ardıcıllıq ehtiva edə bilər. Onları saxlasaydıq, test bəzən
    # sızma OLMADAN da uğursuz olardı (təxminən hər bir neçə yüz icrada bir)
    # və əsl sızmanı gizlədən "bəzən qırmızı" testə çevrilərdi.
    scanned = text.replace(str(write.id), "").replace(str(write.record_id), "")

    assert "1234" not in scanned
    assert "3000" not in scanned
    assert "REDACTED" in scanned


# --------------------------------------------------------------------------- #
# Eksponensial geri çəkilmə (30s → 2dq → 10dq)
# --------------------------------------------------------------------------- #


def test_backoff_schedule_matches_specification(buffer: OfflineBuffer) -> None:
    entry_id = enqueue(buffer)

    assert buffer.mark_failed(entry_id, "şəbəkə", now=T0) == T0 + timedelta(seconds=30)
    assert buffer.mark_failed(entry_id, "şəbəkə", now=T0) == T0 + timedelta(minutes=2)
    assert buffer.mark_failed(entry_id, "şəbəkə", now=T0) == T0 + timedelta(minutes=10)
    # Dördüncü və sonrakı cəhdlər 10 dəqiqədə qalır — sonsuz böyümə yoxdur.
    assert buffer.mark_failed(entry_id, "şəbəkə", now=T0) == T0 + timedelta(minutes=10)


def test_entry_is_hidden_until_next_attempt_time(buffer: OfflineBuffer) -> None:
    entry_id = enqueue(buffer)
    buffer.mark_failed(entry_id, "şəbəkə", now=T0)

    assert buffer.pending(now=T0 + timedelta(seconds=29)) == []
    assert len(buffer.pending(now=T0 + timedelta(seconds=31))) == 1


def test_error_message_is_truncated(buffer: OfflineBuffer) -> None:
    entry_id = enqueue(buffer)
    buffer.mark_failed(entry_id, "x" * 5000, now=T0)

    write = buffer.get(entry_id)
    assert write is not None
    assert write.last_error is not None
    assert len(write.last_error) <= 500


# --------------------------------------------------------------------------- #
# Konflikt
# --------------------------------------------------------------------------- #


def test_conflict_keeps_both_versions(buffer: OfflineBuffer) -> None:
    """Bölmə 5: konfliktdə hər iki versiya saxlanılır."""
    entry_id = enqueue(buffer, table="fines", payload={"amount": "50.00"})
    buffer.mark_conflict(entry_id, remote_version={"amount": "20.00"}, now=T0)

    conflicts = buffer.conflicts()
    assert len(conflicts) == 1
    assert conflicts[0].payload == {"amount": "50.00"}
    assert conflicts[0].remote_version == {"amount": "20.00"}


def test_conflict_blocks_later_writes_for_same_record(buffer: OfflineBuffer) -> None:
    """Həll olunmamış konfliktin üzərinə tikilmiş yazı tətbiq edilməməlidir."""
    record = "cccccccc-0000-0000-0000-000000000003"
    first = enqueue(buffer, table="fines", record_id=record, payload={"amount": "50.00"})
    enqueue(
        buffer,
        table="fines",
        record_id=record,
        payload={"amount": "60.00"},
        now=T0 + timedelta(seconds=1),
    )
    buffer.mark_conflict(first, remote_version={"amount": "20.00"}, now=T0)

    assert buffer.pending(now=T0 + timedelta(minutes=1)) == []


def test_conflict_does_not_block_other_records(buffer: OfflineBuffer) -> None:
    conflicted = enqueue(buffer, table="fines", record_id="dddddddd-0000-0000-0000-000000000004")
    other = enqueue(buffer, table="fines", record_id="eeeeeeee-0000-0000-0000-000000000005")
    buffer.mark_conflict(conflicted, remote_version={}, now=T0)

    assert [w.id for w in buffer.pending(now=T0)] == [other]


def test_resolve_conflict_keep_local_requeues_with_fresh_base(buffer: OfflineBuffer) -> None:
    entry_id = enqueue(buffer, table="fines", base_version=T0 - timedelta(hours=5))
    buffer.mark_conflict(entry_id, remote_version={}, now=T0)
    buffer.resolve_conflict(entry_id, keep_local=True)

    write = buffer.get(entry_id)
    assert write is not None
    assert write.status is SyncStatus.PENDING
    assert write.attempts == 0
    # Köhnə `base_version` saxlansaydı yazı dərhal yenidən konfliktə düşərdi.
    assert write.base_version is None


def test_resolve_conflict_keep_remote_discards_local(buffer: OfflineBuffer) -> None:
    entry_id = enqueue(buffer, table="fines")
    buffer.mark_conflict(entry_id, remote_version={}, now=T0)
    buffer.resolve_conflict(entry_id, keep_local=False)

    write = buffer.get(entry_id)
    assert write is not None
    assert write.status is SyncStatus.SYNCED
    assert buffer.pending(now=T0 + timedelta(days=1)) == []


# --------------------------------------------------------------------------- #
# Audit-kritik cədvəllər
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("table", ["leave_requests", "fines", "audit_logs", "attendance_records"])
def test_audit_critical_tables_are_flagged(buffer: OfflineBuffer, table: str) -> None:
    enqueue(buffer, table=table)
    assert buffer.pending(now=T0)[0].is_audit_critical is True


def test_non_critical_table_is_not_flagged(buffer: OfflineBuffer) -> None:
    enqueue(buffer, table="user_preferences")
    assert buffer.pending(now=T0)[0].is_audit_critical is False


def test_specification_named_tables_are_all_covered() -> None:
    assert {"leave_requests", "fines", "audit_logs"} <= AUDIT_CRITICAL_TABLES


# --------------------------------------------------------------------------- #
# Davamlılıq və təmizləmə
# --------------------------------------------------------------------------- #


def test_buffer_survives_reopen(tmp_path: Path, encryption: EncryptionService) -> None:
    """Elektrik kəsilməsi ssenarisi — növbə diskdə qalmalıdır."""
    path = tmp_path / "offline.db"
    first = OfflineBuffer(path, encryption=encryption)
    entry_id = enqueue(first, payload={"late_minutes": 7})
    first.close()

    second = OfflineBuffer(path, encryption=encryption)
    write = second.get(entry_id)
    second.close()

    assert write is not None
    assert write.payload == {"late_minutes": 7}


def test_purge_removes_only_old_synced_entries(buffer: OfflineBuffer) -> None:
    old = enqueue(buffer, record_id="ffffffff-0000-0000-0000-000000000006")
    recent = enqueue(buffer, record_id="ffffffff-0000-0000-0000-000000000007")
    still_pending = enqueue(buffer, record_id="ffffffff-0000-0000-0000-000000000008")
    buffer.mark_synced(old, now=T0 - timedelta(days=10))
    buffer.mark_synced(recent, now=T0)

    deleted = buffer.purge_synced(older_than=T0 - timedelta(days=1))

    assert deleted == 1
    assert buffer.get(old) is None
    assert buffer.get(recent) is not None
    assert buffer.get(still_pending) is not None


def test_journal_mode_is_wal(tmp_path: Path, encryption: EncryptionService) -> None:
    path = tmp_path / "offline.db"
    buf = OfflineBuffer(path, encryption=encryption)
    mode = buf._conn.execute("PRAGMA journal_mode").fetchone()[0]
    buf.close()

    assert mode.lower() == "wal"


def test_payload_json_roundtrip_keeps_azerbaijani_characters(buffer: OfflineBuffer) -> None:
    enqueue(buffer, payload={"reason": "Şəxsi işə görə çıxış — İçərişəhər"})
    write = buffer.pending(now=T0)[0]

    assert write.payload["reason"] == "Şəxsi işə görə çıxış — İçərişəhər"


def test_buffered_write_is_frozen() -> None:
    write = BufferedWrite(
        id="x",
        seq=1,
        tenant_id="t",
        table_name="fines",
        record_id="r",
        operation=Operation.UPDATE,
        payload={},
        base_version=None,
        status=SyncStatus.PENDING,
        attempts=0,
        queued_at=T0,
        next_attempt_at=T0,
    )
    with pytest.raises(FrozenInstanceError):
        write.attempts = 5  # type: ignore[misc]


def test_json_payload_is_stored_as_object_not_string(buffer: OfflineBuffer) -> None:
    """Payload iki dəfə JSON-lansa oxunanda sətir olardı — səssiz tip xətası."""
    enqueue(buffer, payload={"nested": {"a": 1}})
    write = buffer.pending(now=T0)[0]

    assert isinstance(write.payload, dict)
    assert write.payload["nested"] == {"a": 1}
    assert json.dumps(write.payload)
