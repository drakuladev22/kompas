"""#7 POS Səlahiyyət Siyasəti saxlama qatı — `pos_permission_thresholds`.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — tətbiq səhvən owner rolu ilə qoşulsa
(RLS onda tətbiq olunmur), izolyasiya bu şərtlə qalır (layihənin bütün
repo-larında eyni naxış, bax `exception_repositories.py`).

NİYƏ `delete()` YOXDUR: miqrasiya 018 `REVOKE DELETE` edir — səlahiyyətin
geri alınması `is_active = FALSE` ilə edilir (`POSPermissionThreshold.
revoke()`), sətir SİLİNMİR: "o gün bu işçinin hansı səlahiyyəti var idi?"
sualı HR/audit araşdırmasında cavabsız qalmamalıdır.
"""

from __future__ import annotations

from typing import Any

from src.domain.entities.pos_threshold import POSPermissionThreshold
from src.domain.value_objects.identifiers import EmployeeId, PosThresholdId, TenantId
from src.infrastructure.persistence.repositories import _BaseRepository


class PostgresPOSThresholdRepository(_BaseRepository):
    """`pos_permission_thresholds` — işçi başına BİR diri sətir (UPSERT)."""

    _SELECT = """
        SELECT id, tenant_id, employee_id, max_discount_pct, can_void,
               can_refund, note, is_active, deactivated_at, deactivated_by,
               updated_by, created_at, updated_at
        FROM pos_permission_thresholds
    """

    def get_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> POSPermissionThreshold | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE tenant_id = %s AND employee_id = %s",
            (tenant_id, employee_id),
        )
        return _row_to_threshold(row) if row else None

    def save(self, record: POSPermissionThreshold) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id)`.

        `id` YENİLƏMƏ SƏTRİNDƏ TOXUNULMUR (`EXCLUDED`-dən çıxarılıb): işçi
        başına bir sətir olduğu üçün mövcud sətrin identifikatoru DAİMİ
        qalmalıdır — hər yeniləmə yeni ID alsaydı, audit jurnalındakı
        `entity_id` istinadları qırılardı.
        """
        self._execute(
            """
            INSERT INTO pos_permission_thresholds
                (id, tenant_id, employee_id, max_discount_pct, can_void,
                 can_refund, note, is_active, deactivated_at, deactivated_by,
                 updated_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, employee_id) DO UPDATE
                SET max_discount_pct = EXCLUDED.max_discount_pct,
                    can_void          = EXCLUDED.can_void,
                    can_refund        = EXCLUDED.can_refund,
                    note              = EXCLUDED.note,
                    is_active         = EXCLUDED.is_active,
                    deactivated_at    = EXCLUDED.deactivated_at,
                    deactivated_by    = EXCLUDED.deactivated_by,
                    updated_by        = EXCLUDED.updated_by,
                    updated_at        = EXCLUDED.updated_at
            """,
            (
                record.id,
                record.tenant_id,
                record.employee_id,
                record.max_discount_pct,
                record.can_void,
                record.can_refund,
                record.note,
                record.is_active,
                record.deactivated_at,
                record.deactivated_by,
                record.updated_by,
                record.created_at,
                record.updated_at,
            ),
        )


def _row_to_threshold(row: dict[str, Any]) -> POSPermissionThreshold:
    return POSPermissionThreshold(
        threshold_id=PosThresholdId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        max_discount_pct=row["max_discount_pct"],
        can_void=bool(row["can_void"]),
        can_refund=bool(row["can_refund"]),
        note=row["note"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_active=bool(row["is_active"]),
        deactivated_at=row["deactivated_at"],
        deactivated_by=row["deactivated_by"],
    )


__all__ = ["PostgresPOSThresholdRepository"]
