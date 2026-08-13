"""Norma üstü iş saatlarının saxlama qatı (#15) — `overtime_log` + iş pəncərələri.

    PostgresOvertimeLogRepository — `overtime_log` (migrations/019)
    PostgresWorkedHoursProvider   — günün ölçülə bilən iş pəncərələri

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — layihənin bütün repo-larında eyni naxış
(bax `behavior_repositories.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
NİYƏ İŞ PƏNCƏRƏSİ TƏK SORĞUDUR
──────────────────────────────────────────────────────────────────────────────
Bir günün uzunluğu ÜÇ mənbədən çıxır: təsdiqlənmiş giriş (`attendance_records`),
təyin edilmiş növbə (`shift_assignments` → `work_modes`) və həmin gün icazə ilə
kənarda keçən dəqiqələr (`leave_requests`). Use case onları ayrı-ayrı oxusaydı,
30 işçilik mağazanın BİR günü üçün 90 sorğu olardı (`PostgresAttendanceFact
Provider` ilə eyni əsaslandırma).

──────────────────────────────────────────────────────────────────────────────
İCAZƏ DƏQİQƏLƏRİ NİYƏ MAĞAZANIN ZONASINA ÇEVRİLİR
──────────────────────────────────────────────────────────────────────────────
`PostgresAttendanceFactProvider` icazəni `lr.requested_time::date` ilə tapır —
orada cavab BAYRAQDIR ("hazırda xaricdədir?") və sərhəd yaxınlığındakı bir
saatlıq sürüşmə statusu dəyişmir. Burada isə nəticə RƏQƏMDİR və birbaşa
işlənmiş saatdan çıxılır: gecə 01:00-da başlayan icazənin səhv günə düşməsi
İKİ günün hər ikisinin saatını yanlış edərdi. Ona görə `AT TIME ZONE
s.timezone` açıq yazılır — mağazanın iş günü onun ÖZ zonasındadır.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.domain.entities.attendance_record import CheckInStatus
from src.domain.entities.leave_request import LeaveStatus
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.domain.value_objects.overtime import (
    OvertimeEntry,
    OvertimeSource,
    WorkedSpan,
)
from src.domain.value_objects.scheduling import (
    DEFAULT_TIMEZONE,
    InvalidScheduleError,
    TimeRange,
)
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import date

    from src.domain.value_objects.identifiers import StoreId

_log = get_logger(__name__)


class PostgresOvertimeLogRepository(_BaseRepository):
    """`overtime_log` — işçi-gün başına BİR sətir (#15)."""

    _SELECT = """
        SELECT tenant_id, employee_id, work_date, norm_hours, actual_hours,
               hours_over_norm, source, recorded_by
        FROM overtime_log
    """

    def save(self, entry: OvertimeEntry) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id, work_date)`.

        AVTOMATİK HESABLAMA ƏL İLƏ YAZILMIŞ SƏTRİ ÜSTÜNDƏN YAZMIR. DDL
        `source` sütununu məhz bunun üçün ayırır: `MANUAL_HR` sətir İNSANIN
        iddiasıdır (məs. HR kamera qeydinə baxıb saatı düzəldib) və növbəti
        gecə yenidən-hesablaması onu sükutla silsəydi, düzəlişin heç bir izi
        qalmazdı. Əks istiqamət açıqdır: HR-ın yazısı avtomatik sətri əvəz edir.

        `id` sütunu siyahıda YOXDUR — sətri `(tenant_id, employee_id,
        work_date)` üçlüyü tam eyniləşdirir; ilk yazıda DB `gen_random_uuid()`
        defoltu işə düşür, yenidən yazmada mövcud `id` TOXUNULMUR (belə ki,
        sətrə istinad edən gələcək hesabat linki qırılmasın).
        """
        self._execute(
            """
            INSERT INTO overtime_log
                (tenant_id, employee_id, work_date, norm_hours, actual_hours,
                 hours_over_norm, source, recorded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, employee_id, work_date) DO UPDATE
                SET norm_hours      = EXCLUDED.norm_hours,
                    actual_hours    = EXCLUDED.actual_hours,
                    hours_over_norm = EXCLUDED.hours_over_norm,
                    source          = EXCLUDED.source,
                    recorded_by     = EXCLUDED.recorded_by
                WHERE overtime_log.source <> %s OR EXCLUDED.source = %s
            """,
            (
                entry.tenant_id,
                entry.employee_id,
                entry.work_date,
                entry.norm_hours,
                entry.actual_hours,
                entry.hours_over_norm,
                entry.source.value,
                entry.recorded_by,
                OvertimeSource.MANUAL_HR.value,
                OvertimeSource.MANUAL_HR.value,
            ),
        )

    def list_for_period(
        self, tenant_id: TenantId, *, start: date, end: date
    ) -> list[OvertimeEntry]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND work_date BETWEEN %s AND %s
            ORDER BY work_date DESC, employee_id
            """,
            (tenant_id, start, end),
        )
        return [_row_to_entry(row) for row in rows]

    def list_for_employee_period(
        self, tenant_id: TenantId, employee_id: EmployeeId, *, start: date, end: date
    ) -> list[OvertimeEntry]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND employee_id = %s AND work_date BETWEEN %s AND %s
            ORDER BY work_date
            """,
            (tenant_id, employee_id, start, end),
        )
        return [_row_to_entry(row) for row in rows]


class PostgresWorkedHoursProvider(_BaseRepository):
    """Günün ölçülə bilən iş pəncərələri — TƏK sorğu (modul başlığına bax)."""

    def spans_for(self, store_id: StoreId, work_date: date) -> list[WorkedSpan]:
        """Yalnız TƏSDİQLƏNMİŞ girişi olan işçilər.

        `check_in_status = 'VERIFIED'` süzgəci burada, SQL-dədir: təsdiqlənməmiş
        (`PENDING_VERIFICATION`) və ya rədd edilmiş gün üçün "faktiki saat"
        anlayışı yoxdur — həmin işçinin işə başladığı hələ SÜBUT olunmayıb və
        onun üçün aşım hesablamaq iddianı faktdan qabağa salardı.
        """
        rows = self._fetch_all(
            """
            SELECT ar.employee_id                       AS employee_id,
                   ar.verified_at                       AS verified_at,
                   wm.start_time                        AS start_time,
                   wm.end_time                          AS end_time,
                   s.timezone                           AS store_timezone,
                   COALESCE((
                       SELECT SUM(lr.total_minutes)
                         FROM leave_requests lr
                        WHERE lr.employee_id = ar.employee_id
                          AND lr.tenant_id = ar.tenant_id
                          AND lr.status = %s
                          AND (lr.requested_time AT TIME ZONE s.timezone)::date
                              = ar.work_date
                   ), 0)                                AS leave_minutes
              FROM attendance_records ar
              JOIN stores s ON s.id = ar.store_id
              LEFT JOIN shift_assignments sa
                     ON sa.employee_id = ar.employee_id AND sa.shift_date = ar.work_date
              LEFT JOIN work_modes wm ON wm.id = sa.work_mode_id
             WHERE ar.tenant_id = %s
               AND ar.store_id = %s
               AND ar.work_date = %s
               AND ar.check_in_status = %s
               AND ar.verified_at IS NOT NULL
             ORDER BY ar.employee_id
            """,
            (
                LeaveStatus.VERIFIED.value,
                self._tenant,
                store_id,
                work_date,
                CheckInStatus.VERIFIED.value,
            ),
        )
        return [_row_to_span(row, work_date) for row in rows]


def _row_to_entry(row: dict[str, Any]) -> OvertimeEntry:
    return OvertimeEntry(
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        work_date=row["work_date"],
        norm_hours=Decimal(row["norm_hours"]),
        actual_hours=Decimal(row["actual_hours"]),
        hours_over_norm=Decimal(row["hours_over_norm"]),
        source=OvertimeSource(row["source"]),
        recorded_by=EmployeeId(row["recorded_by"]) if row["recorded_by"] else None,
    )


def _row_to_span(row: dict[str, Any], work_date: date) -> WorkedSpan:
    return WorkedSpan(
        employee_id=EmployeeId(row["employee_id"]),
        work_date=work_date,
        scheduled=_time_range(row),
        checked_in_at=row["verified_at"],
        leave_minutes=int(row["leave_minutes"] or 0),
        store_timezone=str(row["store_timezone"] or DEFAULT_TIMEZONE),
    )


def _time_range(row: dict[str, Any]) -> TimeRange | None:
    """Növbə şablonu — təyinat yoxdursa (və ya yararsızdırsa) `None`.

    YARARSIZ ŞABLON SƏTRİ ÇÖKDÜRMÜR: `TimeRange` başlanğıc = bitiş halını
    rədd edir (`InvalidScheduleError`). Belə bir `work_modes` sətri kataloq
    validasiyasını yan keçib bazaya düşsəydi, istisnanın buradan qalxması
    TABELİN TƏSDİQİNİ bloklayardı — halbuki menecerin imzası bir işçinin
    saat hesabından vacibdir. Gün "ölçülə bilməyən" sayılır və xəbərdarlıq
    jurnala düşür ki, konfiqurasiya səhvi görünməz qalmasın.
    """
    start = row["start_time"]
    end = row["end_time"]
    if start is None or end is None:
        return None
    try:
        return TimeRange(start=start, end=end)
    except InvalidScheduleError:
        _log.warning(
            "OVERTIME_INVALID_WORK_MODE",
            extra={"isci": str(row["employee_id"]), "start": str(start), "end": str(end)},
        )
        return None


__all__ = [
    "PostgresOvertimeLogRepository",
    "PostgresWorkedHoursProvider",
]
