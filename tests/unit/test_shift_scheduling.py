"""Növbə planlaması və dəyişmə sorğusu testləri (bölmə 3) — Faza 5."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from src.application.use_cases.shift_scheduling import (
    ShiftPermissionError,
    ShiftPlanningUseCase,
    ShiftRequestError,
    ShiftSwapUseCase,
)
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.entities.shift import (
    ShiftAssignment,
    ShiftSource,
    ShiftSwapRequest,
    SwapStatus,
)
from src.domain.policies import FeatureModule
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
    WorkModeId,
    new_shift_assignment_id,
    new_shift_swap_request_id,
)
from tests.fixtures.fakes import (
    FakeClock,
    FakeFeatureToggles,
    InMemoryLeaveRequests,
    InMemoryShiftMatrix,
    InMemorySwaps,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
MODE = WorkModeId(uuid.uuid4())
DAY = date(2026, 8, 20)
NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)

MANAGE_SHIFTS = PermissionFlag(code="can_manage_shifts", category="HR")
APPROVE_SWAP = PermissionFlag(code="can_approve_shift_swap", category="HR")
FILL_ATTENDANCE = PermissionFlag(
    code="can_fill_daily_attendance", category="NOVBE", hardlock=HardlockLevel.NONE
)


def make_employee(role: SystemRole, *, flags: list[PermissionFlag]) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for flag in flags:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


class Ctx:
    def __init__(self) -> None:
        self.clock = FakeClock(NOW)
        self.shifts = InMemoryShiftMatrix()
        self.swaps = InMemorySwaps()
        self.leave_requests = InMemoryLeaveRequests()
        self.toggles = FakeFeatureToggles()
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()

    def planning(self) -> ShiftPlanningUseCase:
        return ShiftPlanningUseCase(
            shifts=self.shifts,  # type: ignore[arg-type]
            leave_requests=self.leave_requests,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def swaps_uc(self) -> ShiftSwapUseCase:
        return ShiftSwapUseCase(
            swaps=self.swaps,  # type: ignore[arg-type]
            planning=self.planning(),
            toggles=self.toggles,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


# --------------------------------------------------------------------------- #
# Entity qaydaları
# --------------------------------------------------------------------------- #


def test_off_day_cannot_carry_a_work_mode() -> None:
    """DB `chk_shift_mode` domendə də təkrarlanır (defense-in-depth)."""
    with pytest.raises(DomainRuleError, match="İstirahət gününə"):
        ShiftAssignment(
            assignment_id=new_shift_assignment_id(),
            tenant_id=TENANT,
            employee_id=WORKER,
            shift_date=DAY,
            is_off_day=True,
            work_mode_id=MODE,
        )


def test_work_day_requires_a_work_mode() -> None:
    """Rejimsiz iş günü gecikməni hesablamağa imkan verməzdi."""
    with pytest.raises(DomainRuleError, match="iş rejimi MƏCBURİDİR"):
        ShiftAssignment(
            assignment_id=new_shift_assignment_id(),
            tenant_id=TENANT,
            employee_id=WORKER,
            shift_date=DAY,
            is_off_day=False,
        )


def test_worker_cannot_decide_their_own_swap() -> None:
    """Vəzifə ayrılığı — öz sorğusunu təsdiqləmək qadağandır."""
    request = ShiftSwapRequest(
        request_id=new_shift_swap_request_id(),
        tenant_id=TENANT,
        employee_id=WORKER,
        target_date=DAY,
        reason="Ailə səbəbi",
        created_at=NOW,
    )
    with pytest.raises(DomainRuleError, match="öz növbə dəyişmə"):
        request.approve(approver_id=WORKER, decided_at=NOW)


def test_manager_note_does_not_change_status() -> None:
    """Bölmə 3: Store Manager TƏSDİQ ETMİR, yalnız tövsiyə yazır."""
    request = ShiftSwapRequest(
        request_id=new_shift_swap_request_id(),
        tenant_id=TENANT,
        employee_id=WORKER,
        target_date=DAY,
        reason="Ailə səbəbi",
        created_at=NOW,
    )
    request.attach_manager_note(manager_id=EmployeeId(uuid.uuid4()), note="Razıyam")

    assert request.status is SwapStatus.PENDING_APPROVAL
    assert request.manager_note == "Razıyam"


# --------------------------------------------------------------------------- #
# Shift Matrix
# --------------------------------------------------------------------------- #


def test_planning_requires_the_flag(ctx: Ctx) -> None:
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(ShiftPermissionError, match="can_manage_shifts"):
        ctx.planning().assign_off_day(
            tenant_id=TENANT, actor=seller, employee_id=WORKER, shift_date=DAY
        )


def test_assigning_a_work_day_is_audited(ctx: Ctx) -> None:
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])

    result = ctx.planning().assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY, work_mode_id=MODE
    )

    assert result.assignment is not None
    assert result.assignment.is_working_day
    assert "SHIFT_ASSIGNED" in ctx.audit.actions()


def test_week_planning_marks_requested_weekdays_as_off(ctx: Ctx) -> None:
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    monday = date(2026, 8, 17)

    results = ctx.planning().assign_week(
        tenant_id=TENANT,
        actor=hr,
        employee_id=WORKER,
        week_start=monday,
        work_mode_id=MODE,
        off_day_weekdays=frozenset({5, 6}),  # şənbə + bazar
    )

    off_days = [r for r in results if r.assignment is not None and r.assignment.is_off_day]
    assert len(off_days) == 2


def test_open_leave_on_the_same_day_raises_a_conflict_warning(ctx: Ctx) -> None:
    """Bölmə 3: dəyişiklik BLOKLANMIR, amma xəbərdarlıq verilir."""
    from src.domain.entities.leave_request import LeaveRequest

    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    request = LeaveRequest.open(
        request_id=uuid.uuid4(),  # type: ignore[arg-type]
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        requested_time=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        leave_type_id=None,
        allowance_minutes=0,
        ntp_verified=True,
        employee_is_in_store=True,
    )
    ctx.leave_requests.save(request)

    result = ctx.planning().assign_off_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY
    )

    assert result.has_conflicts
    assert result.assignment is not None  # dəyişiklik YENƏ tətbiq olundu
    assert "SHIFT_CHANGE_CONFLICT" in ctx.notifier.categories()


def test_seller_only_sees_their_own_calendar(ctx: Ctx) -> None:
    """CANLI GÖRÜNMƏ SCOPİNQİ (bölmə 3)."""
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    other = EmployeeId(uuid.uuid4())
    ctx.planning().assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=other, shift_date=DAY, work_mode_id=MODE
    )

    seller = make_employee(SystemRole.SELLER, flags=[])
    visible = ctx.planning().view_matrix(tenant_id=TENANT, actor=seller, start=DAY, end=DAY)

    assert visible == []


# --------------------------------------------------------------------------- #
# Shift Swap
# --------------------------------------------------------------------------- #


def test_submitting_does_not_touch_the_calendar(ctx: Ctx) -> None:
    """Bölmə 3: "Təqvimdə HEÇ BİR dəyişiklik baş vermir"."""
    seller = make_employee(SystemRole.SELLER, flags=[])

    ctx.swaps_uc().submit(tenant_id=TENANT, employee=seller, target_date=DAY, reason="Ailə səbəbi")

    assert ctx.shifts.assignments == {}


def test_second_request_for_the_same_day_is_blocked(ctx: Ctx) -> None:
    seller = make_employee(SystemRole.SELLER, flags=[])
    use_case = ctx.swaps_uc()
    use_case.submit(tenant_id=TENANT, employee=seller, target_date=DAY, reason="Ailə səbəbi")

    with pytest.raises(ShiftRequestError, match="artıq gözləyən sorğunuz"):
        use_case.submit(tenant_id=TENANT, employee=seller, target_date=DAY, reason="Yenə lazımdır")


def test_past_dates_are_rejected(ctx: Ctx) -> None:
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(ShiftRequestError, match="Keçmiş tarix"):
        ctx.swaps_uc().submit(
            tenant_id=TENANT,
            employee=seller,
            target_date=date(2026, 8, 1),
            reason="Ailə səbəbi",
        )


def test_disabled_module_blocks_new_requests_only(ctx: Ctx) -> None:
    """RETROAKTİV TƏSİR QAYDASI: mövcud sorğu öz axınını tamamlayır."""
    seller = make_employee(SystemRole.SELLER, flags=[])
    use_case = ctx.swaps_uc()
    existing = use_case.submit(
        tenant_id=TENANT, employee=seller, target_date=DAY, reason="Ailə səbəbi"
    )

    ctx.toggles.disable(FeatureModule.SHIFT_SWAP.value)

    with pytest.raises(ShiftRequestError, match="deaktiv"):
        use_case.submit(
            tenant_id=TENANT,
            employee=seller,
            target_date=date(2026, 8, 21),
            reason="Başqa gün",
        )

    # Mövcud sorğu HƏLƏ DƏ təsdiqlənə bilir.
    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_SWAP, MANAGE_SHIFTS])
    use_case.approve(tenant_id=TENANT, approver=hr, request_id=existing.id)
    assert ctx.swaps.items[existing.id].status is SwapStatus.APPROVED


def test_approval_updates_the_matrix_through_the_shared_function(ctx: Ctx) -> None:
    """Bölmə 3: "eyni yeniləmə funksiyasından istifadə edərək"."""
    seller = make_employee(SystemRole.SELLER, flags=[])
    use_case = ctx.swaps_uc()
    request = use_case.submit(
        tenant_id=TENANT, employee=seller, target_date=DAY, reason="Ailə səbəbi"
    )

    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_SWAP, MANAGE_SHIFTS])
    change = use_case.approve(tenant_id=TENANT, approver=hr, request_id=request.id)

    assert change.assignment is not None
    assert change.assignment.is_off_day
    assert change.assignment.source is ShiftSource.SHIFT_SWAP


def test_store_manager_cannot_approve(ctx: Ctx) -> None:
    """Bölmə 3 düzəlişi: son qərar HR/Admin-dədir."""
    seller = make_employee(SystemRole.SELLER, flags=[])
    use_case = ctx.swaps_uc()
    request = use_case.submit(
        tenant_id=TENANT, employee=seller, target_date=DAY, reason="Ailə səbəbi"
    )

    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL_ATTENDANCE])
    with pytest.raises(ShiftPermissionError, match="can_approve_shift_swap"):
        use_case.approve(tenant_id=TENANT, approver=manager, request_id=request.id)


def test_rejection_notifies_the_worker_critically(ctx: Ctx) -> None:
    """İşçi həmin gün işə çıxmalı olduğunu MÜTLƏQ bilməlidir."""
    seller = make_employee(SystemRole.SELLER, flags=[])
    use_case = ctx.swaps_uc()
    request = use_case.submit(
        tenant_id=TENANT, employee=seller, target_date=DAY, reason="Ailə səbəbi"
    )

    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_SWAP])
    use_case.reject(
        tenant_id=TENANT,
        approver=hr,
        request_id=request.id,
        reason="Həmin gün başqa işçi yoxdur",
    )

    decided = [m for m in ctx.notifier.messages if m["category"] == "SHIFT_SWAP_DECIDED"]
    assert decided and decided[-1]["is_critical"] is True
