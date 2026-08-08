"""Portların test implementasiyaları (Faza 2.5+).

Mock kitabxanası ƏVƏZİNƏ əl ilə yazılmış sahtə (fake) obyektlər istifadə
olunur: onlar real davranışı saxlayır (yaddaşda saxlama, axtarış), ona görə
testlər "metod çağırıldımı" deyil, "NƏTİCƏ DÜZGÜNDÜRMÜ" yoxlayır.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from src.domain.entities.attendance_record import AttendanceRecord, CheckInStatus
from src.domain.entities.employee import Employee
from src.domain.entities.fine import Fine
from src.domain.entities.leave_request import LeaveRequest
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    FineId,
    LeaveRequestId,
    LeaveTypeId,
    StoreId,
    TenantId,
)


class FakeClock:
    """Sabitlənə bilən vaxt mənbəyi."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def advance(self, **kwargs: float) -> None:
        self._moment += timedelta(**kwargs)

    def set(self, moment: datetime) -> None:
        self._moment = moment


class FakeNtp:
    """NTP yoxlayıcısı — sürüşməni testdə idarə etmək üçün."""

    def __init__(
        self, clock: FakeClock, *, verified: bool = True, drift: float | None = 0.0
    ) -> None:
        self._clock = clock
        self.verified = verified
        self.drift = drift

    def verified_now(self) -> tuple[datetime, bool]:
        return self._clock.now(), self.verified

    def drift_seconds(self) -> float | None:
        return self.drift


class FakeSystemLimits:
    """`system_limits` — defoltlar + testdə override."""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self._values: dict[str, str] = {key.value: value for key, value in DEFAULT_LIMITS.items()}
        self._values.update(overrides or {})

    def set(self, key: SystemLimitKey | str, value: str) -> None:
        self._values[key.value if isinstance(key, SystemLimitKey) else key] = value

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        try:
            return int(self._values.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class FakeFeatureToggles:
    """Feature Toggle-lar — defolt hamısı aktiv."""

    def __init__(self, disabled: set[str] | None = None) -> None:
        self.disabled = disabled or set()

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        return module_key not in self.disabled

    def disable(self, module_key: str) -> None:
        self.disabled.add(module_key)


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def notify(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    def categories(self) -> list[str]:
        return [str(m["category"]) for m in self.messages]


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(e["action"]) for e in self.entries]


class InMemoryLeaveRequests:
    def __init__(self) -> None:
        self.items: dict[LeaveRequestId, LeaveRequest] = {}
        self.save_failure: Exception | None = None

    def get(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        return self.items.get(request_id)

    def find_open_for_employee(self, employee_id: EmployeeId) -> LeaveRequest | None:
        for request in self.items.values():
            if request.employee_id == employee_id and request.status.is_open:
                return request
        return None

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[LeaveRequest]:
        return [
            r
            for r in self.items.values()
            if r.store_id in store_ids and r.status.value == "PENDING_RETURN_VERIFICATION"
        ]

    def list_due_for_timeout(
        self, tenant_id: TenantId, *, now: datetime, timeout_minutes: int
    ) -> list[LeaveRequest]:
        return [
            r
            for r in self.items.values()
            if r.tenant_id == tenant_id and r.status.value == "PENDING_RETURN_VERIFICATION"
        ]

    def save(self, request: LeaveRequest) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.items[request.id] = request


class InMemoryFines:
    def __init__(self) -> None:
        self.items: dict[FineId, Fine] = {}
        self.save_failure: Exception | None = None

    def get(self, fine_id: FineId) -> Fine | None:
        return self.items.get(fine_id)

    def list_for_employee_month(
        self, employee_id: EmployeeId, *, year: int, month: int
    ) -> list[Fine]:
        return [
            f
            for f in self.items.values()
            if f.employee_id == employee_id
            and f.issued_at.year == year
            and f.issued_at.month == month
        ]

    def list_exportable(self, tenant_id: TenantId, *, now: datetime) -> list[Fine]:
        return [f for f in self.items.values() if f.is_exportable(now=now)]

    def save(self, fine: Fine) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.items[fine.id] = fine


class InMemoryAttendance:
    def __init__(self) -> None:
        self.items: dict[AttendanceRecordId, AttendanceRecord] = {}

    def get(self, record_id: AttendanceRecordId) -> AttendanceRecord | None:
        return self.items.get(record_id)

    def get_for_day(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord | None:
        for record in self.items.values():
            if record.employee_id == employee_id and record.work_date == work_date:
                return record
        return None

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[AttendanceRecord]:
        return [
            r
            for r in self.items.values()
            if r.store_id in store_ids and r.status is CheckInStatus.PENDING_VERIFICATION
        ]

    def list_expected_on(self, tenant_id: TenantId, work_date: date) -> list[AttendanceRecord]:
        return [
            r for r in self.items.values() if r.tenant_id == tenant_id and r.work_date == work_date
        ]

    def save(self, record: AttendanceRecord) -> None:
        self.items[record.id] = record


class InMemoryEmployees:
    def __init__(self, employees: list[Employee] | None = None) -> None:
        self.items: dict[EmployeeId, Employee] = {e.id: e for e in employees or []}

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.items.get(employee_id)

    def get_by_email(self, tenant_id: TenantId, email: Any) -> Employee | None:
        for employee in self.items.values():
            if employee.email == email and employee.tenant_id == tenant_id:
                return employee
        return None

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Employee]:
        return [
            e
            for e in self.items.values()
            if e.tenant_id == tenant_id and e.store_id == store_id and e.has_pin
        ]

    def save(self, employee: Employee) -> None:
        self.items[employee.id] = employee

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        from datetime import UTC

        now = datetime.now(tz=UTC)
        return sum(
            1
            for e in self.items.values()
            if e.tenant_id == tenant_id and e.is_active and e.has_permission(flag_code, now=now)
        )


class FakeLeaveTypes:
    def __init__(self, durations: dict[LeaveTypeId, int] | None = None) -> None:
        self.durations = durations or {}

    def get_default_duration(self, leave_type_id: LeaveTypeId) -> int | None:
        return self.durations.get(leave_type_id)


class FakeShifts:
    def __init__(
        self,
        *,
        off_days: set[tuple[EmployeeId, date]] | None = None,
        starts: dict[tuple[EmployeeId, date], datetime] | None = None,
    ) -> None:
        self.off_days = off_days or set()
        self.starts = starts or {}

    def is_off_day(self, employee_id: EmployeeId, work_date: date) -> bool:
        return (employee_id, work_date) in self.off_days

    def scheduled_start(self, employee_id: EmployeeId, work_date: date) -> datetime | None:
        return self.starts.get((employee_id, work_date))


class FakeCameraAssignments:
    """FAIL-SAFE: defolt BOŞ — operator heç nə görmür."""

    def __init__(self, mapping: dict[EmployeeId, list[StoreId]] | None = None) -> None:
        self.mapping = mapping or {}

    def stores_for_operator(self, operator_id: EmployeeId) -> list[StoreId]:
        return self.mapping.get(operator_id, [])

    def assign(self, operator_id: EmployeeId, store_id: StoreId) -> None:
        self.mapping.setdefault(operator_id, []).append(store_id)


__all__ = [
    "FakeCameraAssignments",
    "FakeClock",
    "FakeFeatureToggles",
    "FakeLeaveTypes",
    "FakeNtp",
    "FakeShifts",
    "FakeSystemLimits",
    "InMemoryAttendance",
    "InMemoryEmployees",
    "InMemoryFines",
    "InMemoryLeaveRequests",
    "RecordingAudit",
    "RecordingNotifier",
]
