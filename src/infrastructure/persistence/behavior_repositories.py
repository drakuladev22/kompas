"""İşçi Davranış Baz Xəttinin saxlama qatı (#8) — `employee_behavior_baseline`
+ `attendance_records`-dan xam giriş anları.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — layihənin bütün repo-larında eyni naxış
(bax `exception_repositories.py` başlığı).

NİYƏ `PostgresCheckInHistoryProvider.list_checkins()` `attendance_records.
verified_at` OXUYUR, `requested_at` YOX: bölmə 4 `verified_at`-i "günün RƏSMİ
başlama vaxtı" adlandırır (`AttendanceRecord.verify()` docstring-i) — "check-in
vaxtı" anlayışının sistemdəki YEGANƏ tərifi budur, gecikmə hesablaması da elə
bu sahədən istifadə edir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.entities.attendance_record import CheckInStatus
from src.domain.value_objects.behavior_signals import BehaviorBaseline, CheckInObservation
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date


class PostgresBehaviorBaselineRepository(_BaseRepository):
    """`employee_behavior_baseline` — işçi başına BİR törəmə sətir (#8)."""

    _SELECT = """
        SELECT tenant_id, employee_id, avg_checkin_minutes, stddev_minutes,
               sample_size, last_calculated_at
        FROM employee_behavior_baseline
    """

    def get_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> BehaviorBaseline | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE tenant_id = %s AND employee_id = %s",
            (tenant_id, employee_id),
        )
        return _row_to_baseline(row) if row else None

    def list_for_tenant(self, tenant_id: TenantId) -> list[BehaviorBaseline]:
        rows = self._fetch_all(f"{self._SELECT} WHERE tenant_id = %s", (tenant_id,))
        return [_row_to_baseline(row) for row in rows]

    def save(self, baseline: BehaviorBaseline) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id)`.

        `id` sütunu SİYAHIDA YOXDUR: sətir tam törəmə olduğu üçün domen
        obyektinin öz identifikatoru yoxdur (bax `behavior_signals.py`
        başlığı) — ilk yazıda DB `gen_random_uuid()` defoltu işə düşür,
        yenidən-hesablamada isə mövcud `id` `ON CONFLICT` sayəsində TOXUNULMUR.
        """
        self._execute(
            """
            INSERT INTO employee_behavior_baseline
                (tenant_id, employee_id, avg_checkin_minutes, stddev_minutes,
                 sample_size, last_calculated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, employee_id) DO UPDATE
                SET avg_checkin_minutes = EXCLUDED.avg_checkin_minutes,
                    stddev_minutes      = EXCLUDED.stddev_minutes,
                    sample_size         = EXCLUDED.sample_size,
                    last_calculated_at  = EXCLUDED.last_calculated_at
            """,
            (
                baseline.tenant_id,
                baseline.employee_id,
                baseline.avg_checkin_minutes,
                baseline.stddev_minutes,
                baseline.sample_size,
                baseline.last_calculated_at,
            ),
        )


class PostgresCheckInHistoryProvider(_BaseRepository):
    """`attendance_records.verified_at` — baz xətt VƏ anomaliya qaydasının
    EYNİ xam mənbəyi (bax modul başlığı).
    """

    def list_checkins(
        self, tenant_id: TenantId, *, since: date, until: date
    ) -> list[CheckInObservation]:
        # `s.timezone`: DDL-in "yerli zamana çevrildikdən SONRA yaz" tələbi
        # bu sətirdən başlayır — çevirmənin ÖZÜ tətbiq qatında olur
        # (`checkin_minutes_since_midnight`), lakin zona məlumatı BURADA,
        # mənbədə oxunmalıdır ki, hər müşahidə ÖZ mağazasının zonasını daşısın.
        rows = self._fetch_all(
            """
            SELECT ar.employee_id, ar.store_id, ar.verified_at, s.timezone
            FROM attendance_records ar
            JOIN stores s ON s.id = ar.store_id
            WHERE ar.tenant_id = %s
              AND ar.check_in_status = %s
              AND ar.verified_at IS NOT NULL
              AND ar.work_date BETWEEN %s AND %s
            """,
            (tenant_id, CheckInStatus.VERIFIED.value, since, until),
        )
        return [_row_to_observation(row) for row in rows]


def _row_to_baseline(row: dict[str, Any]) -> BehaviorBaseline:
    return BehaviorBaseline(
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        avg_checkin_minutes=float(row["avg_checkin_minutes"]),
        stddev_minutes=float(row["stddev_minutes"]),
        sample_size=int(row["sample_size"]),
        last_calculated_at=row["last_calculated_at"],
    )


def _row_to_observation(row: dict[str, Any]) -> CheckInObservation:
    return CheckInObservation(
        employee_id=EmployeeId(row["employee_id"]),
        store_id=StoreId(row["store_id"]),
        checked_in_at=row["verified_at"],
        store_timezone=str(row["timezone"]),
    )


__all__ = [
    "PostgresBehaviorBaselineRepository",
    "PostgresCheckInHistoryProvider",
]
