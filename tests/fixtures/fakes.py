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
from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.entities.leave_request import LeaveRequest, LeaveStatus
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
        #: Audit yazısının UĞURSUZLUĞUNU simulyasiya edir (defolt: uğurlu).
        #:
        #: NİYƏ LAZIMDIR — Saga zəncirinin SONUNCU addımı `write_audit`-dır.
        #: Yalnız daha erkən addımın çökməsi test edilsəydi, kompensasiya
        #: "cərimə artıq YARADILDIQDAN SONRA" heç vaxt işə düşməzdi və məhz
        #: həmin yolda gizlənən qüsur (kompensasiyanın `reverse()` çağırıb
        #: `DomainRuleError` alması) testlərdən yaşıl keçərdi.
        #:
        #: `AuditTrail.record()`-un istisna udmaması layihə qaydasıdır
        #: (CLAUDE.md §5) — yəni bu, süni deyil, real ssenaridir.
        self.failure: Exception | None = None

    def record(self, **kwargs: Any) -> None:
        if self.failure is not None:
            raise self.failure
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(e["action"]) for e in self.entries]


class InMemoryLeaveRequests:
    def __init__(self) -> None:
        self.items: dict[LeaveRequestId, LeaveRequest] = {}
        self.save_failure: Exception | None = None
        #: `get_for_update()` neçə dəfə çağırılıb — yazma axınının kilidli
        #: oxudan keçdiyini test AÇIQ şəkildə yoxlaya bilsin deyə.
        self.locked_reads: list[LeaveRequestId] = []

    def get(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        return self.items.get(request_id)

    def get_for_update(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        """`RowLockingLeaveRequests` qabiliyyəti — yaddaşda kilid MƏNASIZDIR.

        Sahtə repo tək saplı testdə işləyir, ona görə burada həqiqi kilid yox,
        yalnız ÇAĞIRIŞ QEYDİ var: test "yazma axını kilidli oxu istədimi"
        sualına cavab ala bilir. Həqiqi `FOR UPDATE` davranışı
        `database/tests/test_guards.sql` və inteqrasiya testlərinin işidir.
        """
        self.locked_reads.append(request_id)
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

    def monthly_used_minutes(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        """Aylıq icazə cəmi — YALNIZ təsdiqlənmiş sorğular (bölmə 3 limiti).

        Dəyər `penalty.total_minutes`-dən oxunur: `leave_requests.total_minutes`
        SÜTUNU məhz təsdiq anında bu hesablamadan yazılır (bax `verify()`).
        Təsdiqlənib, lakin penalty-si olmayan sətir mümkün deyil, yenə də
        `or 0` qoyulub ki, fake real repo-dan DAHA SƏRT olmasın.
        """
        return sum(
            (request.penalty.total_minutes if request.penalty is not None else 0)
            for request in self.items.values()
            if request.employee_id == employee_id
            and request.status is LeaveStatus.VERIFIED
            and request.requested_time.year == year
            and request.requested_time.month == month
        )

    def save(self, request: LeaveRequest) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.items[request.id] = request


#: `uq_fines_one_live_auto_delay_per_leave` (miqrasiya 015) indeksinin əhatə
#: etdiyi DİRİ statuslar. `REVERSED` QƏSDƏN yoxdur — ölü sətir indeks yerini
#: tutsaydı, kompensasiyadan sonra təkrar təsdiq əbədi bloklanardı.
LIVE_AUTO_DELAY_STATUSES = frozenset(
    {FineStatus.PENDING_REVIEW, FineStatus.PUBLISHED, FineStatus.REDUCED}
)


class DuplicateLiveFineError(Exception):
    """Sahtə repo-da DB unikal indeksinin qarşılığı.

    Real `PostgresFineRepository` bu halda `psycopg.errors.UniqueViolation`
    alır. Sahtə repo həmin qaydanı təkrarlayır ki, "ikinci cərimə yaranmır"
    iddiası DB olmadan da yoxlana bilsin — əks halda unit dəsti indeksin
    olmadığı bir dünyada yaşayardı və qüsuru görməzdi.
    """


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
        self._require_single_live_auto_delay(fine)
        self.items[fine.id] = fine

    def _require_single_live_auto_delay(self, fine: Fine) -> None:
        """Bir icazə sorğusuna yalnız BİR diri `AUTO_DELAY` cəriməsi."""
        if fine.source is not FineSource.AUTO_DELAY or fine.leave_request_id is None:
            return
        if fine.status not in LIVE_AUTO_DELAY_STATUSES:
            return
        for existing in self.items.values():
            if (
                existing.id != fine.id
                and existing.source is FineSource.AUTO_DELAY
                and existing.leave_request_id == fine.leave_request_id
                and existing.status in LIVE_AUTO_DELAY_STATUSES
            ):
                raise DuplicateLiveFineError(
                    f"İcazə sorğusuna ({fine.leave_request_id}) artıq diri "
                    f"AUTO_DELAY cəriməsi bağlıdır"
                )


class InMemoryAttendance:
    def __init__(self) -> None:
        self.items: dict[AttendanceRecordId, AttendanceRecord] = {}
        #: `get_for_day_for_update()` çağırışlarının izi (bax
        #: `InMemoryLeaveRequests.get_for_update` izahı).
        self.locked_reads: list[tuple[EmployeeId, date]] = []

    def get(self, record_id: AttendanceRecordId) -> AttendanceRecord | None:
        return self.items.get(record_id)

    def get_for_day(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord | None:
        for record in self.items.values():
            if record.employee_id == employee_id and record.work_date == work_date:
                return record
        return None

    def get_for_day_for_update(
        self, employee_id: EmployeeId, work_date: date
    ) -> AttendanceRecord | None:
        """`RowLockingAttendance` qabiliyyəti — yalnız çağırış qeydi."""
        self.locked_reads.append((employee_id, work_date))
        return self.get_for_day(employee_id, work_date)

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

    def get_by_username(self, tenant_id: TenantId, username: Any) -> Employee | None:
        for employee in self.items.values():
            if employee.username == username and employee.tenant_id == tenant_id:
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
    "LIVE_AUTO_DELAY_STATUSES",
    "DuplicateDedupeKeyError",
    "DuplicateLiveFineError",
    "FakeCameraAssignments",
    "FakeClock",
    "FakeExceptionSources",
    "FakeFeatureToggles",
    "FakeLeaveTypes",
    "FakeNtp",
    "FakeShifts",
    "FakeSystemLimits",
    "InMemoryAttendance",
    "InMemoryEmployees",
    "InMemoryExceptions",
    "InMemoryFines",
    "InMemoryLeaveRequests",
    "RecordingAudit",
    "RecordingNotifier",
]


# --------------------------------------------------------------------------- #
# Faza 5/6 qatları — növbə, tabel, etiraz, dəstək
# --------------------------------------------------------------------------- #


class InMemoryShiftMatrix(FakeShifts):
    """`ShiftRepository`-nin YAZMA tərəfi də daxil olmaqla tam sahtəsi.

    `FakeShifts`-dən miras alır ki, mövcud testlər (`is_off_day`,
    `scheduled_start`) toxunulmaz qalsın — yeni metodlar yalnız əlavədir.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.assignments: dict[tuple[EmployeeId, date], Any] = {}

    def get_assignment(self, employee_id: EmployeeId, work_date: date) -> Any:
        return self.assignments.get((employee_id, work_date))

    def list_range(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
        employee_ids: list[EmployeeId] | None = None,
    ) -> list[Any]:
        rows = [
            item
            for (employee_id, day), item in self.assignments.items()
            if start <= day <= end and (employee_ids is None or employee_id in employee_ids)
        ]
        return sorted(rows, key=lambda item: item.shift_date)

    def save_assignment(self, assignment: Any) -> None:
        self.assignments[(assignment.employee_id, assignment.shift_date)] = assignment
        # `is_off_day()` mövcud testlərlə eyni mənbədən oxunmalıdır.
        key = (assignment.employee_id, assignment.shift_date)
        if assignment.is_off_day:
            self.off_days.add(key)
        else:
            self.off_days.discard(key)

    def clear_assignment(self, employee_id: EmployeeId, work_date: date) -> None:
        self.assignments.pop((employee_id, work_date), None)
        self.off_days.discard((employee_id, work_date))


class InMemorySwaps:
    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}

    def get(self, request_id: Any) -> Any:
        return self.items.get(request_id)

    def list_pending(self, tenant_id: TenantId, *, store_id: StoreId | None = None) -> list[Any]:
        return [item for item in self.items.values() if item.status.value == "PENDING_APPROVAL"]

    def list_for_employee(self, employee_id: EmployeeId, *, limit: int = 50) -> list[Any]:
        return [item for item in self.items.values() if item.employee_id == employee_id][:limit]

    def find_open_for_date(self, employee_id: EmployeeId, target_date: date) -> Any:
        for item in self.items.values():
            if (
                item.employee_id == employee_id
                and item.target_date == target_date
                and item.status.value == "PENDING_APPROVAL"
            ):
                return item
        return None

    def save(self, request: Any) -> None:
        self.items[request.id] = request


class InMemorySheets:
    def __init__(self) -> None:
        self.items: dict[tuple[StoreId, date], Any] = {}

    def get_for_day(self, store_id: StoreId, sheet_date: date) -> Any:
        return self.items.get((store_id, sheet_date))

    def list_unconfirmed(self, tenant_id: TenantId, *, up_to: date) -> list[Any]:
        return [
            sheet
            for (_, day), sheet in self.items.items()
            if day <= up_to and not sheet.is_confirmed
        ]

    def save(self, sheet: Any) -> None:
        self.items[(sheet.store_id, sheet.sheet_date)] = sheet


class FakeAttendanceFacts:
    def __init__(self, facts: list[Any] | None = None) -> None:
        self.facts = facts or []

    def facts_for(self, store_id: StoreId, work_date: date) -> list[Any]:
        return list(self.facts)


class InMemoryAppeals:
    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}

    def get(self, appeal_id: Any) -> Any:
        return self.items.get(appeal_id)

    def get_for_fine(self, fine_id: Any) -> Any:
        return next((item for item in self.items.values() if item.fine_id == fine_id), None)

    def list_pending(self, tenant_id: TenantId) -> list[Any]:
        return [item for item in self.items.values() if item.status.value == "PENDING"]

    def list_for_employee(self, employee_id: EmployeeId, *, limit: int = 50) -> list[Any]:
        return [item for item in self.items.values() if item.employee_id == employee_id][:limit]

    def save(self, appeal: Any) -> None:
        self.items[appeal.id] = appeal


class DuplicateDedupeKeyError(Exception):
    """Sahtə repo-da `uq_exceptions_dedupe` indeksinin qarşılığı.

    Real `PostgresExceptionRepository` bu halda `UniqueViolation` alır. Sahtə
    repo qaydanı təkrarlayır ki, "təkrar tapıntı ikinci sətir yaratmır"
    iddiası DB olmadan da yoxlana bilsin — əks halda unit dəsti indeksin
    olmadığı bir dünyada yaşayardı (`DuplicateLiveFineError` ilə eyni qərar).
    """


class InMemoryExceptions:
    """`ExceptionRepository` sahtəsi — Vahid İstisna Jurnalı (#9).

    `delete()` QƏSDƏN YOXDUR: DB-də `REVOKE DELETE` var və sahtə repo real
    məhdudiyyətdən daha sərbəst olmamalıdır.
    """

    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}
        self.save_failure: Exception | None = None

    def get(self, exception_id: Any) -> Any:
        return self.items.get(exception_id)

    def find_by_dedupe(self, tenant_id: TenantId, *, source: str, dedupe_key: str) -> Any:
        for record in self.items.values():
            if (
                record.tenant_id == tenant_id
                and record.source == source
                and record.dedupe_key == dedupe_key
            ):
                return record
        return None

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_ids: list[StoreId] | None = None,
        limit: int = 200,
    ) -> list[Any]:
        rows = [
            record
            for record in self.items.values()
            if record.tenant_id == tenant_id
            and record.status.value == "OPEN"
            and (store_ids is None or record.store_id in store_ids)
        ]
        rows.sort(key=lambda record: record.created_at, reverse=True)
        return rows[:limit]

    def save(self, record: Any) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self._require_unique_dedupe(record)
        self.items[record.id] = record

    def _require_unique_dedupe(self, record: Any) -> None:
        if record.dedupe_key is None:
            return
        existing = self.find_by_dedupe(
            record.tenant_id, source=record.source, dedupe_key=record.dedupe_key
        )
        if existing is not None and existing.id != record.id:
            raise DuplicateDedupeKeyError(
                f"'{record.source}' mənbəyində '{record.dedupe_key}' açarı artıq var"
            )


class FakeExceptionSources:
    """`ExceptionSourceCatalog` sahtəsi — `exception_sources` kataloqu."""

    def __init__(self, sources: list[Any] | None = None) -> None:
        self.sources: dict[str, Any] = {source.code: source for source in sources or []}

    def get(self, tenant_id: TenantId, code: str) -> Any:
        return self.sources.get(code.strip().upper())

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        return [source for source in self.sources.values() if include_inactive or source.is_active]


class InMemoryPOSThresholds:
    """`POSThresholdRepository` sahtəsi (#7 — sənədləşdirmə/siyasət qeydi).

    Açar `employee_id`-dir: `pos_permission_thresholds`-da işçi başına BİR
    diri sətir var (`UNIQUE (tenant_id, employee_id)`, migrations/018).
    `delete()` QƏSDƏN YOXDUR — real repo-da `REVOKE DELETE` var
    (bax `InMemoryExceptions` ilə eyni qərar).
    """

    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}
        self.save_failure: Exception | None = None

    def get_for_employee(self, tenant_id: TenantId, employee_id: EmployeeId) -> Any:
        record = self.items.get(employee_id)
        if record is None or record.tenant_id != tenant_id:
            return None
        return record

    def save(self, record: Any) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.items[record.employee_id] = record


class FakeFineTypes:
    def __init__(self, entries: dict[Any, Any] | None = None) -> None:
        self.entries = entries or {}

    def get(self, fine_type_id: Any) -> Any:
        return self.entries.get(fine_type_id)

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        return [entry for entry in self.entries.values() if include_inactive or entry.is_active]

    def save(self, tenant_id: TenantId, entry: Any, *, changed_by: EmployeeId) -> None:
        self.entries[entry.fine_type_id] = entry

    def deactivate(self, tenant_id: TenantId, fine_type_id: Any, *, changed_by: EmployeeId) -> None:
        self.entries.pop(fine_type_id, None)
