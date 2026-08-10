"""`sync_conflicts` repository-si (bölmə 5) — Faza 5.

Konflikt sətirlərini `infrastructure/offline/sync.py` YAZIR; bu modul onları
HR-ın həll ekranı üçün OXUYUR və bağlayır.

Sətir HEÇ VAXT silinmir — `resolved_at` doldurulur. Bölmə 5-in "hər iki
versiya saxlanılır" tələbi həllə də şamil olunur: hansı versiyanın niyə
seçildiyi sonradan sual oluna bilər.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.application.use_cases.sync_conflicts import ConflictItem, Resolution
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import EmployeeId, TenantId


class PostgresSyncConflictRepository(_BaseRepository):
    """`sync_conflicts` — açıq konfliktlər və onların həlli."""

    _SELECT = """
        SELECT id, table_name, record_id, local_version, remote_version, detected_at
        FROM sync_conflicts
    """

    def list_open(self, tenant_id: TenantId, *, limit: int = 100) -> list[ConflictItem]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND resolved_at IS NULL
            ORDER BY detected_at
            LIMIT %s
            """,
            (tenant_id, limit),
        )
        return [_row_to_item(row) for row in rows]

    def get(self, conflict_id: object) -> ConflictItem | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (conflict_id, self._tenant),
        )
        return _row_to_item(row) if row else None

    def open_count(self, tenant_id: TenantId) -> int:
        row = self._fetch_one(
            """
            SELECT count(*) AS total FROM sync_conflicts
             WHERE tenant_id = %s AND resolved_at IS NULL
            """,
            (tenant_id,),
        )
        return int(row["total"]) if row else 0

    def resolve(
        self,
        conflict_id: object,
        *,
        resolution: Resolution,
        resolved_by: EmployeeId,
        resolved_at: datetime,
        note: str,
    ) -> None:
        """Konflikti bağlayır — `local_version`/`remote_version` TOXUNULMUR.

        `resolved_at IS NULL` şərti idempotentlik verir: iki HR eyni anda
        eyni konflikti həll etsə, ikincisi heç nə dəyişmir və birincinin
        qərarı qalır (son yazan qazanmır).
        """
        self._execute(
            """
            UPDATE sync_conflicts
               SET resolution      = %s,
                   resolved_by     = %s,
                   resolved_at     = %s,
                   resolution_note = %s
             WHERE id = %s AND tenant_id = %s AND resolved_at IS NULL
            """,
            (resolution.value, resolved_by, resolved_at, note, conflict_id, self._tenant),
        )


def _row_to_item(row: dict[str, Any]) -> ConflictItem:
    return ConflictItem(
        conflict_id=row["id"],
        table_name=row["table_name"],
        record_id=row["record_id"],
        local_version=_as_dict(row["local_version"]),
        remote_version=_as_dict(row["remote_version"]),
        detected_at=row["detected_at"],
    )


def _as_dict(raw: Any) -> dict[str, Any]:
    """`JSONB` sütununu sözlüyə çevirir (sürücü artıq obyekt qaytara bilər)."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    return dict(value) if isinstance(value, dict) else {}


__all__ = ["PostgresSyncConflictRepository"]
