"""Use case testləri (Faza 2.5) — 3-STEP axını, Saga, NTP, scope, timeout."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from src.application.use_cases import (
    LeaveVerificationUseCase,
    ModuleDisabledError,
    MorningCheckInUseCase,
    OperationNotPermittedError,
    TimeDriftError,
)
from src.domain.entities import CheckInStatus, FineSource, LeaveStatus
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.identifiers import (
    EmployeeId,
    LeaveTypeId,
    StoreId,
    TenantId,
)
from src.shared.saga_orchestrator import SagaOrchestrator, SagaStatus
from tests.fixtures.fakes import (
    FakeCameraAssignments,
    FakeClock,
    FakeFeatureToggles,
    FakeLeaveTypes,
    FakeNtp,
    FakeShifts,
    FakeSystemLimits,
    InMemoryAttendance,
    InMemoryEmployees,
    InMemoryFines,
    InMemoryLeaveRequests,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
OPERATOR = EmployeeId(uuid.uuid4())
LUNCH = LeaveTypeId(uuid.uuid4())
DAY = date(2026, 8, 8)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 8, hour, minute, tzinfo=UTC)


class Ctx:
    """Bütün sahtə portları bir yerdə saxlayan test konteksti."""

    def __init__(self) -> None:
        self.clock = FakeClock(at(12, 0))
        self.ntp = FakeNtp(self.clock)
        self.limits = FakeSystemLimits()
        self.toggles = FakeFeatureToggles()
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()
        self.leave_requests = InMemoryLeaveRequests()
        self.fines = InMemoryFines()
        self.employees = InMemoryEmployees()
        self.leave_types = FakeLeaveTypes({LUNCH: 60})
        self.shifts = FakeShifts()
        self.attendance = InMemoryAttendance()
        self.cameras = FakeCameraAssignments({OPERATOR: [STORE]})
        self.saga = SagaOrchestrator()

    def leave_uc(self) -> LeaveVerificationUseCase:
        return LeaveVerificationUseCase(
            leave_requests=self.leave_requests,  # type: ignore[arg-type]
            fines=self.fines,  # type: ignore[arg-type]
            employees=self.employees,  # type: ignore[arg-type]
            leave_types=self.leave_types,  # type: ignore[arg-type]
            camera_assignments=self.cameras,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            ntp=self.ntp,  # type: ignore[arg-type]
            limits=self.limits,  # type: ignore[arg-type]
            toggles=self.toggles,  # type: ignore[arg-type]
            saga=self.saga,
            audit=self.audit,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def checkin_uc(self) -> MorningCheckInUseCase:
        return MorningCheckInUseCase(
            attendance=self.attendance,  # type: ignore[arg-type]
            shifts=self.shifts,  # type: ignore[arg-type]
            camera_assignments=self.cameras,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            ntp=self.ntp,  # type: ignore[arg-type]
            limits=self.limits,  # type: ignore[arg-type]
            toggles=self.toggles,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


def open_leave(ctx: Ctx):
    return ctx.leave_uc().request_leave(
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        leave_type_id=LUNCH,
        employee_is_in_store=True,
    )


# --------------------------------------------------------------------------- #
# STEP 1
# --------------------------------------------------------------------------- #


def test_request_leave_uses_leave_type_allowance(ctx: Ctx) -> None:
    """BR-001 defoltu: güzəşt İcazə Növünün müddətindən gəlir."""
    request = open_leave(ctx)

    assert request.allowance_minutes == 60
    assert request.status is LeaveStatus.OUTSIDE
    assert "LEAVE_REQUESTED" in ctx.audit.actions()


def test_allowance_source_none_is_strictest(ctx: Ctx) -> None:
    ctx.limits.set(SystemLimitKey.LEAVE_ALLOWANCE_SOURCE, "NONE")
    assert open_leave(ctx).allowance_minutes == 0


def test_allowance_source_fixed(ctx: Ctx) -> None:
    ctx.limits.set(SystemLimitKey.LEAVE_ALLOWANCE_SOURCE, "FIXED")
    ctx.limits.set(SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES, "20")
    assert open_leave(ctx).allowance_minutes == 20


def test_second_open_leave_blocked(ctx: Ctx) -> None:
    open_leave(ctx)
    with pytest.raises(OperationNotPermittedError, match="açıq icazə"):
        open_leave(ctx)


def test_leave_blocked_when_module_disabled(ctx: Ctx) -> None:
    ctx.toggles.disable(FeatureModule.CAMERA_VERIFICATION.value)
    with pytest.raises(ModuleDisabledError):
        open_leave(ctx)


def test_time_drift_blocks_leave_request(ctx: Ctx) -> None:
    """Bölmə 2: sürüşmə 60 saniyəni keçirsə vaxt-kritik əməliyyat bloklanır."""
    ctx.ntp.verified = False
    ctx.ntp.drift = 95.0

    with pytest.raises(TimeDriftError, match="Saat sürüşməsi"):
        open_leave(ctx)


def test_small_drift_allows_operation(ctx: Ctx) -> None:
    ctx.ntp.verified = False
    ctx.ntp.drift = 12.0

    request = open_leave(ctx)
    assert request.ntp_verified is False  # qeyd olunur, lakin bloklanmır


# --------------------------------------------------------------------------- #
# STEP 2 & 3
# --------------------------------------------------------------------------- #


async def test_full_flow_creates_no_fine_by_default(ctx: Ctx) -> None:
    """BR-002 defoltu: dərəcə 0 → pul cəriməsi YARANMIR, yalnız dəqiqələr."""
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    assert outcome.succeeded is True
    assert outcome.penalty.delay_minutes == 30
    assert outcome.penalty.total_minutes == 120
    assert outcome.fine is None
    assert ctx.fines.items == {}


async def test_fine_created_when_rate_configured(ctx: Ctx) -> None:
    """BR-002: dərəcə təyin ediləndə AUTO_DELAY cəriməsi avtomatik yaranır."""
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    assert outcome.fine is not None
    assert outcome.fine.source is FineSource.AUTO_DELAY
    assert str(outcome.fine.amount) == "15.00 AZN"  # 30 dəq × 0.50
    assert "LEAVE_VERIFIED" in ctx.audit.actions()


async def test_no_fine_when_no_delay(ctx: Ctx) -> None:
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(12, 45))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    assert outcome.penalty.delay_minutes == 0
    assert outcome.fine is None


async def test_saga_compensates_when_fine_save_fails(ctx: Ctx) -> None:
    """SAGA (bölmə 1): cərimə addımı çökərsə status geri qaytarılır və
    əməliyyat `PENDING_RECONCILIATION`-a keçir."""
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request_id = next(iter(ctx.leave_requests.items))
    ctx.fines.save_failure = RuntimeError("DB əlçatmazdır")

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is False
    assert outcome.saga.status is SagaStatus.PENDING_RECONCILIATION
    # Kompensasiya statusu geri qaytardı — yarımçıq "VERIFIED" qalmadı
    assert ctx.leave_requests.items[request_id].status is (LeaveStatus.PENDING_RETURN_VERIFICATION)


async def test_operator_outside_scope_blocked(ctx: Ctx) -> None:
    """FAIL-SAFE (bölmə 4): operator öz mağazası olmayan sorğunu təsdiqləyə bilməz."""
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    stranger = EmployeeId(uuid.uuid4())  # heç bir mağazaya təyin edilməyib
    with pytest.raises(OperationNotPermittedError, match="təyin edilməyib"):
        await ctx.leave_uc().verify_return(
            tenant_id=TENANT,
            operator_id=stranger,
            request_id=next(iter(ctx.leave_requests.items)),
        )


# --------------------------- manual override -------------------------------- #


def test_override_below_threshold_no_dual_control(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request = ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
        overridden_time=at(12, 50),
        reason="Kameradan təsdiqləndi, işçi 12:50-də qayıtdı",
    )

    assert request.override is not None
    assert request.override.requires_dual_control is False
    assert "DUAL_CONTROL_PENDING" not in ctx.notifier.categories()


def test_override_above_threshold_triggers_notification(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request = ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
        overridden_time=at(12, 20),
        reason="Kameradan təsdiqləndi, işçi 12:20-də qayıtdı",
    )

    assert request.override is not None
    assert request.override.requires_dual_control is True
    assert "DUAL_CONTROL_PENDING" in ctx.notifier.categories()
    assert "MANUAL_TIME_OVERRIDE" in ctx.audit.actions()


def test_dual_control_toggle_off_skips_second_approval(ctx: Ctx) -> None:
    """RETROAKTİV TƏSİR: modul söndürüləndə YENİ override-lar təsdiq tələb etmir."""
    ctx.toggles.disable(FeatureModule.DUAL_CONTROL.value)
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request = ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
        overridden_time=at(12, 10),  # 50 dəqiqəlik fərq
        reason="Kameradan təsdiqləndi, işçi 12:10-da qayıtdı",
    )

    assert request.override is not None
    assert request.override.requires_dual_control is False


def test_dual_control_approval_requires_flag(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(12, 20),
        reason="Kameradan təsdiqləndi, işçi 12:20-də qayıtdı",
    )

    unknown = EmployeeId(uuid.uuid4())
    with pytest.raises(OperationNotPermittedError, match="dual-control"):
        ctx.leave_uc().approve_dual_control(
            tenant_id=TENANT, approver_id=unknown, request_id=request_id
        )


# ------------------------------- timeout ------------------------------------ #


def test_leave_timeout_escalation(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    ctx.clock.set(at(13, 46))
    count = ctx.leave_uc().escalate_timeouts(TENANT)

    assert count == 1
    assert "VERIFICATION_TIMEOUT" in ctx.notifier.categories()
    # Təkrar çağırış yeni bildiriş yaratmır
    assert ctx.leave_uc().escalate_timeouts(TENANT) == 0


# --------------------------------------------------------------------------- #
# Morning Check-in
# --------------------------------------------------------------------------- #


def test_check_in_flow(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 5))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    assert uc.employee_can_request_leave(WORKER, DAY) is False

    ctx.shifts.starts[(WORKER, DAY)] = at(8, 0)
    outcome = uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    assert outcome.record.status is CheckInStatus.VERIFIED
    assert outcome.lateness is not None
    assert outcome.lateness.is_late is False  # 15 dəq tolerantlıq
    assert uc.employee_can_request_leave(WORKER, DAY) is True


def test_check_in_late_beyond_tolerance(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 40))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    ctx.shifts.starts[(WORKER, DAY)] = at(8, 0)

    outcome = uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    assert outcome.lateness is not None
    assert outcome.lateness.is_late is True
    assert outcome.lateness.late_minutes == 25
    assert outcome.lateness.creates_fine is False  # gecikmə cərimə yaratmır


def test_check_in_reject_notifies_hr(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    outcome = uc.reject(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        employee_id=WORKER,
        reason="Görüntüdə başqa şəxs PIN-dən istifadə edib",
        work_date=DAY,
    )

    assert outcome.was_rejected is True
    assert outcome.record.status is CheckInStatus.NOT_STARTED
    assert "CHECK_IN_REJECTED" in ctx.notifier.categories()


def test_pending_queue_is_fail_safe_without_assignment(ctx: Ctx) -> None:
    """Bölmə 4: təyinatsız operator HEÇ NƏ görmür."""
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    assert uc.pending_queue(EmployeeId(uuid.uuid4())) == []
    assert len(uc.pending_queue(OPERATOR)) == 1


def test_pending_queue_excludes_other_stores(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    other_worker = EmployeeId(uuid.uuid4())
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    uc.start_day(tenant_id=TENANT, employee_id=other_worker, store_id=OTHER_STORE, work_date=DAY)

    queue = uc.pending_queue(OPERATOR)
    assert len(queue) == 1
    assert queue[0].employee_id == WORKER


def test_check_in_timeout_escalation(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    ctx.clock.set(at(8, 46))
    assert uc.escalate_timeouts(TENANT, OPERATOR) == 1
    assert "CHECK_IN_TIMEOUT" in ctx.notifier.categories()
    assert uc.escalate_timeouts(TENANT, OPERATOR) == 0


def test_absence_detection(ctx: Ctx) -> None:
    """Bölmə 4: off-day deyil VƏ VERIFIED yoxdur → İcazəsiz Qayıb."""
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    assert uc.detect_absences(TENANT, DAY) == 1
    assert "UNAUTHORIZED_ABSENCE_DETECTED" in ctx.audit.actions()
    assert uc.detect_absences(TENANT, DAY) == 0  # təkrar işarələmə yoxdur


def test_off_day_is_not_absence(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    ctx.shifts.off_days.add((WORKER, DAY))

    assert uc.detect_absences(TENANT, DAY) == 0


def test_verified_day_is_not_absence(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    assert uc.detect_absences(TENANT, DAY) == 0


def test_check_in_time_drift_blocked(ctx: Ctx) -> None:
    ctx.ntp.verified = False
    ctx.ntp.drift = 120.0

    with pytest.raises(TimeDriftError):
        ctx.checkin_uc().start_day(
            tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY
        )


def test_verify_requires_pending_record(ctx: Ctx) -> None:
    with pytest.raises(OperationNotPermittedError, match="davamiyyət qeydi yoxdur"):
        ctx.checkin_uc().verify(
            tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY
        )


def test_ntp_drift_limit_is_configurable(ctx: Ctx) -> None:
    """Sürüşmə həddi `system_limits`-dən oxunur (bölmə 3)."""
    ctx.limits.set(SystemLimitKey.NTP_MAX_DRIFT_SECONDS, "300")
    ctx.ntp.verified = False
    ctx.ntp.drift = 120.0

    record = ctx.checkin_uc().start_day(
        tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY
    )
    assert record.status is CheckInStatus.PENDING_VERIFICATION


def test_clock_advance_helper() -> None:
    clock = FakeClock(at(9, 0))
    clock.advance(minutes=30)
    assert clock.now() == at(9, 30)
    assert timedelta(minutes=30) == at(9, 30) - at(9, 0)
