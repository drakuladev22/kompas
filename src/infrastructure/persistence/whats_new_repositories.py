"""«Nə Yeni?» versiya-qeydlərinin saxlama qatı — `v2backlog.md` Faza 8.2.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL, RLS-Ə ƏLAVƏ açıq
`tenant_id` şərti (`campaign_periods.py` ilə eyni naxış). Soft delete
(`is_active`) use case-in qərarıdır — silmə yoxdur (`catalogs.py`
əsaslandırması: keçmiş qeyd dəyişiklik tarixçəsinin sübutudur).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from src.application.use_cases.whats_new import WhatsNewEntry
from src.domain.value_objects.identifiers import TenantId
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    pass


class PostgresWhatsNewRepository(_BaseRepository):
    """`whats_new_entries` — kirayəçi-daxili versiya-qeydləri (migrations/104).

    Repo TƏKMİLDİR: ad/uzunluq yoxlamaları use case-də, DB `CHECK`-lərdədir —
    burada yalnız oxu/yazı.
    """

    def list_entries(self, tenant_id: TenantId, *, include_inactive: bool) -> list[WhatsNewEntry]:
        extra = "" if include_inactive else " AND is_active"
        rows = self._fetch_all(
            # f-string yalnız İKİ sabit variantdan birini seçir — dinamik SQL
            # yoxdur (CLAUDE.md §4).
            f"""
            SELECT id, version_label, title_az, body_az, is_active, created_at
            FROM whats_new_entries
            WHERE tenant_id = %s{extra}
            ORDER BY created_at DESC
            """,  # noqa: S608 - şərtlər sabit siyahıdandır
            (tenant_id,),
        )
        return [_row_to_entry(row) for row in rows]

    def create(
        self,
        tenant_id: TenantId,
        *,
        version_label: str,
        title_az: str,
        body_az: str,
        created_by_id: object,
    ) -> WhatsNewEntry:
        row = self._fetch_one(
            """
            INSERT INTO whats_new_entries
                (tenant_id, version_label, title_az, body_az, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, version_label, title_az, body_az, is_active, created_at
            """,
            (tenant_id, version_label, title_az, body_az, created_by_id),
        )
        if row is None:  # pragma: no cover — RETURNING həmişə sətir qaytarır
            raise RuntimeError("whats_new_entries INSERT nəticə vermədi")
        return _row_to_entry(row)

    def deactivate(self, tenant_id: TenantId, entry_id: str) -> bool:
        row = self._fetch_one(
            """
            UPDATE whats_new_entries
               SET is_active = FALSE,
                   deactivated_at = now()
             WHERE tenant_id = %s AND id = %s AND is_active
            RETURNING id
            """,
            (tenant_id, entry_id),
        )
        return row is not None


def _row_to_entry(row: dict[str, object]) -> WhatsNewEntry:
    return WhatsNewEntry(
        entry_id=str(row["id"]),
        version_label=str(row["version_label"]),
        title_az=str(row["title_az"]),
        body_az=str(row["body_az"]),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"]
        if isinstance(row["created_at"], datetime)
        else datetime.fromisoformat(str(row["created_at"])),
    )


__all__ = [
    "PostgresWhatsNewRepository",
]
