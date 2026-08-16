"""Növbə planlaması və dəyişmə sorğusu testləri (bölmə 3) — Faza 5."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.application.use_cases.shift_scheduling import (
    ANNUAL_LEAVE_CONFLICT_KIND,
    ShiftPermissionError,
    ShiftPlanningUseCase,
    ShiftRequestError,
    ShiftSwapUseCase,
)
from src.domain.entities.annual_leave import AnnualLeaveRequest, AnnualLeaveStatus
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
    new_annual_leave_request_id,
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


class FakeAnnualLeaveRequests:
    """`AnnualLeaveRequestRepository` — YALNIZ `find_overlapping_approved`.

    Qalan metodlar QƏSDƏN YOXDUR: `ShiftPlanningUseCase` onları çağırsaydı
    test `AttributeError` ilə qırılardı və bu, istənilən nəticədir — növbə
    planlaması məzuniyyət sorğularını OXUMAQDAN artıq heç nə etməməlidir
    (`entities/annual_leave.py` başlığı: matris və məzuniyyət bir-birini
    yazmır).
    """

    def __init__(self, approved: list[AnnualLeaveRequest] | None = None) -> None:
        self.rows = list(approved or [])
        self.queries: list[tuple[EmployeeId, date, date]] = []

    def find_overlapping_approved(
        self, employee_id: EmployeeId, *, start: date, end: date
    ) -> AnnualLeaveRequest | None:
        self.queries.append((employee_id, start, end))
        for request in self.rows:
            if request.employee_id != employee_id:
                continue
            if request.status is not AnnualLeaveStatus.APPROVED:
                continue
            if request.start_date <= end and start <= request.end_date:
                return request
        return None


def approved_annual_leave(
    *, employee_id: EmployeeId = WORKER, start: date, end: date
) -> AnnualLeaveRequest:
    request = AnnualLeaveRequest(
        request_id=new_annual_leave_request_id(),
        tenant_id=TENANT,
        employee_id=employee_id,
        start_date=start,
        end_date=end,
        created_at=NOW,
        status=AnnualLeaveStatus.APPROVED,
        approved_by=EmployeeId(uuid.uuid4()),
        decided_at=NOW,
        deducted_days=Decimal("5"),
        emit_created_event=False,
    )
    return request


class Ctx:
    def __init__(self) -> None:
        self.clock = FakeClock(NOW)
        self.shifts = InMemoryShiftMatrix()
        self.swaps = InMemorySwaps()
        self.leave_requests = InMemoryLeaveRequests()
        self.annual_leave = FakeAnnualLeaveRequests()
        self.toggles = FakeFeatureToggles()
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()

    def planning(self, *, with_annual_leave: bool = True) -> ShiftPlanningUseCase:
        return ShiftPlanningUseCase(
            shifts=self.shifts,  # type: ignore[arg-type]
            leave_requests=self.leave_requests,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            # `with_annual_leave=False` KÖÇÜRMƏDƏN ƏVVƏLKİ qurulmanı təkrarlayır
            # (asılılıq İSTƏYƏ BAĞLIDIR) — mövcud çağırış yerlərinin davranışının
            # dəyişmədiyini sınamaq üçün.
            annual_leave=self.annual_leave if with_annual_leave else None,  # type: ignore[arg-type]
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


# --------------------------------------------------------------------------- #
# #28 — təsdiqlənmiş illik məzuniyyət ↔ Shift Matrix bağlantısı
# --------------------------------------------------------------------------- #


def test_assigning_a_work_day_during_approved_annual_leave_warns(ctx: Ctx) -> None:
    """Boşluq: matris məzuniyyətdən xəbərsiz idi və süni «qayıb» doğururdu."""
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    ctx.annual_leave.rows.append(
        approved_annual_leave(start=DAY - timedelta(days=2), end=DAY + timedelta(days=2))
    )

    result = ctx.planning().assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY, work_mode_id=MODE
    )

    kinds = [conflict.kind for conflict in result.conflicts]
    assert ANNUAL_LEAVE_CONFLICT_KIND in kinds


def test_the_annual_leave_warning_never_blocks_the_assignment(ctx: Ctx) -> None:
    """`ScheduleConflict` müqaviləsi: "BLOKLAYICI DEYİL — admin yenə edə bilər"."""
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    ctx.annual_leave.rows.append(approved_annual_leave(start=DAY, end=DAY))

    result = ctx.planning().assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY, work_mode_id=MODE
    )

    assert result.assignment is not None
    assert ctx.shifts.assignments  # təyinat FAKTİKİ olaraq yazıldı


def test_the_annual_leave_warning_is_written_into_the_audit_trail(ctx: Ctx) -> None:
    """«Xəbərdar edildi, buna baxmayaraq təyin etdi» faktı sübutlu qalmalıdır."""
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    ctx.annual_leave.rows.append(approved_annual_leave(start=DAY, end=DAY))

    ctx.planning().assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY, work_mode_id=MODE
    )

    entry = next(e for e in ctx.audit.entries if e["action"] == "SHIFT_ASSIGNED")
    assert ANNUAL_LEAVE_CONFLICT_KIND in entry["after_state"]["conflicts"]


def test_marking_the_leave_day_as_off_produces_no_annual_leave_warning(ctx: Ctx) -> None:
    """İstirahət kimi işarələmək planlayıcının DOĞRU reaksiyasıdır.

    Orada da xəbərdarlıq göstərsəydik, düzgün əməliyyat xəbərdarlıqla
    "cəzalandırılar" və kanal səs-küyə çevrilərdi.
    """
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    ctx.annual_leave.rows.append(approved_annual_leave(start=DAY, end=DAY))

    result = ctx.planning().assign_off_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY
    )

    kinds = [conflict.kind for conflict in result.conflicts]
    assert ANNUAL_LEAVE_CONFLICT_KIND not in kinds


def test_a_day_outside_the_leave_range_is_not_flagged(ctx: Ctx) -> None:
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    ctx.annual_leave.rows.append(
        approved_annual_leave(start=DAY + timedelta(days=5), end=DAY + timedelta(days=9))
    )

    result = ctx.planning().assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY, work_mode_id=MODE
    )

    assert [c.kind for c in result.conflicts] == []


def test_a_pending_annual_leave_request_does_not_warn(ctx: Ctx) -> None:
    """Yalnız TƏSDİQLƏNMİŞ məzuniyyət xəbərdarlıq doğurur.

    Gözləyən sorğu heç nəyi dəyişmir (`AnnualLeaveUseCase.submit` başlığı) —
    onu da xəbərdarlığa salsaydıq, hər sorğu bütün planlaşdırmanı
    "problemli" göstərərdi.
    """
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    pending = AnnualLeaveRequest(
        request_id=new_annual_leave_request_id(),
        tenant_id=TENANT,
        employee_id=WORKER,
        start_date=DAY,
        end_date=DAY,
        created_at=NOW,
        emit_created_event=False,
    )
    ctx.annual_leave.rows.append(pending)

    result = ctx.planning().assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY, work_mode_id=MODE
    )

    assert [c.kind for c in result.conflicts] == []


def test_planning_without_the_annual_leave_repository_behaves_as_before(ctx: Ctx) -> None:
    """Asılılıq İSTƏYƏ BAĞLIDIR — qoşulmayan çağırış yolu dəyişmir (fail-open)."""
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_SHIFTS])
    ctx.annual_leave.rows.append(approved_annual_leave(start=DAY, end=DAY))

    result = ctx.planning(with_annual_leave=False).assign_work_day(
        tenant_id=TENANT, actor=hr, employee_id=WORKER, shift_date=DAY, work_mode_id=MODE
    )

    assert result.assignment is not None
    assert [c.kind for c in result.conflicts] == []
    assert ctx.annual_leave.queries == []


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
