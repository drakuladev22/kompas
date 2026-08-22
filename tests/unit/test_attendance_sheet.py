"""Gündəlik Mağaza Tabeli testləri (bölmə 3) — Faza 5."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from src.application.use_cases.daily_attendance import (
    DailyAttendanceSheetUseCase,
    SheetPermissionError,
)
from src.domain.entities.attendance_sheet import (
    AttendanceCountingPolicy,
    AttendanceFact,
    AutoAttendanceStatus,
    DailyAttendanceSheet,
    SheetLine,
)
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
    new_daily_sheet_id,
)
from tests.fixtures.fakes import (
    FakeAttendanceFacts,
    FakeClock,
    InMemorySheets,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
DAY = date(2026, 8, 10)
NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)

FILL = PermissionFlag(code="can_fill_daily_attendance", category="NOVBE")
VIEW_REPORTS = PermissionFlag(code="can_view_employee_reports", category="HR")


def make_employee(
    role: SystemRole, *, flags: list[PermissionFlag], store_id: StoreId | None = STORE
) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        is_system=True,
    )
    for flag in flags:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=store_id,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


class Ctx:
    def __init__(self, facts: list[AttendanceFact] | None = None) -> None:
        self.clock = FakeClock(NOW)
        self.sheets = InMemorySheets()
        self.facts = FakeAttendanceFacts(facts)
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()

    def use_case(self) -> DailyAttendanceSheetUseCase:
        return DailyAttendanceSheetUseCase(
            sheets=self.sheets,  # type: ignore[arg-type]
            facts=self.facts,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------- #
# Status çevirmə qaydası
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("fact", "expected"),
    [
        (
            AttendanceFact(employee_id=WORKER, planned_off=False, has_verified_check_in=True),
            AutoAttendanceStatus.VERIFIED,
        ),
        (
            AttendanceFact(
                employee_id=WORKER,
                planned_off=False,
                has_verified_check_in=True,
                is_late=True,
            ),
            AutoAttendanceStatus.LATE,
        ),
        (
            AttendanceFact(employee_id=WORKER, planned_off=False, is_currently_outside=True),
            AutoAttendanceStatus.OUTSIDE,
        ),
        (
            AttendanceFact(employee_id=WORKER, planned_off=True),
            AutoAttendanceStatus.OFF_DAY,
        ),
        (
            AttendanceFact(employee_id=WORKER, planned_off=False, day_is_over=True),
            AutoAttendanceStatus.ABSENT,
        ),
        (
            AttendanceFact(employee_id=WORKER, planned_off=True, has_verified_check_in=True),
            AutoAttendanceStatus.UNPLANNED,
        ),
        (
            # DEEP-GAP D1 — regressiya testi: təsdiqlənmiş illik məzuniyyət
            # günündə növbə matrisində sətir açılmayıb (`planned_off=False`,
            # adi hal) VƏ heç bir check-in qeydi yoxdur. Düzəlişdən ƏVVƏL bu
            # kombinasiya `ABSENT` ("🔴 İcazəsiz qayıb") verirdi.
            AttendanceFact(employee_id=WORKER, planned_off=False, on_annual_leave=True),
            AutoAttendanceStatus.ANNUAL_LEAVE,
        ),
    ],
)
def test_status_is_derived_from_facts(fact: AttendanceFact, expected: AutoAttendanceStatus) -> None:
    assert fact.derive_status() is expected


def test_day_not_over_shows_pending_not_absent() -> None:
    """Səhər saat 10-da gəlməmiş işçi "qayıb" DEYİL (modul başlığı)."""
    fact = AttendanceFact(employee_id=WORKER, planned_off=False, day_is_over=False)
    assert fact.derive_status() is AutoAttendanceStatus.PENDING


def test_currently_outside_outranks_annual_leave() -> None:
    """Fiziki iştirak faktı (`OUTSIDE`) HR-ın illik məzuniyyət qeydindən üstündür."""
    fact = AttendanceFact(
        employee_id=WORKER, planned_off=False, is_currently_outside=True, on_annual_leave=True
    )
    assert fact.derive_status() is AutoAttendanceStatus.OUTSIDE


def test_annual_leave_outranks_stray_check_in() -> None:
    """HR-ın təsdiqlədiyi məzuniyyət qeydi ötəri check-in siqnalından üstündür."""
    fact = AttendanceFact(
        employee_id=WORKER, planned_off=False, has_verified_check_in=True, on_annual_leave=True
    )
    assert fact.derive_status() is AutoAttendanceStatus.ANNUAL_LEAVE


def test_annual_leave_label_is_never_absent() -> None:
    assert AutoAttendanceStatus.ANNUAL_LEAVE.label_az == "🟣 Məzuniyyətdə"


def test_annual_leave_is_never_a_mismatch() -> None:
    """DEEP-GAP D1 — `planned_off` istənilən dəyərdə uyğunsuzluq yaranmamalıdır."""
    for planned_off in (True, False):
        line = SheetLine(
            employee_id=WORKER,
            auto_status=AutoAttendanceStatus.ANNUAL_LEAVE,
            planned_off=planned_off,
        )
        assert line.has_mismatch is False


def test_annual_leave_counting_follows_the_root_policy() -> None:
    """`counts_as_worked` sabitdir (False); Root-lu variant keçidli olmalıdır."""
    assert AutoAttendanceStatus.ANNUAL_LEAVE.counts_as_worked is False
    assert AutoAttendanceStatus.ANNUAL_LEAVE.counts_as_worked_with(
        AttendanceCountingPolicy(annual_leave_counts_as_worked=True)
    )
    assert not AutoAttendanceStatus.ANNUAL_LEAVE.counts_as_worked_with(
        AttendanceCountingPolicy(annual_leave_counts_as_worked=False)
    )
    # Digər statuslar üçün Root parametri təsirsizdir — yalnız ANNUAL_LEAVE fərqlənir.
    assert AutoAttendanceStatus.VERIFIED.counts_as_worked_with(
        AttendanceCountingPolicy(annual_leave_counts_as_worked=False)
    )


def test_attendance_counting_policy_default_matches_default_limits() -> None:
    """`DEFAULT_LIMITS[ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY]` "1"-dir — sayılır."""
    assert AttendanceCountingPolicy.defaults().annual_leave_counts_as_worked is True


def test_mismatch_is_computed_not_stored() -> None:
    """Plan = iş günü, fakt = qeyd yoxdur → uyğunsuzluq."""
    line = SheetLine(employee_id=WORKER, auto_status=AutoAttendanceStatus.ABSENT, planned_off=False)
    assert line.has_mismatch

    line.auto_status = AutoAttendanceStatus.VERIFIED
    assert not line.has_mismatch


def test_unplanned_work_on_an_off_day_is_also_a_mismatch() -> None:
    """Off-day sayı səhv çıxarsa maaş hesabatı yanlış olur."""
    line = SheetLine(
        employee_id=WORKER, auto_status=AutoAttendanceStatus.UNPLANNED, planned_off=True
    )
    assert line.has_mismatch


# --------------------------------------------------------------------------- #
# Aqreqat
# --------------------------------------------------------------------------- #


def test_confirmed_sheet_cannot_be_refilled() -> None:
    sheet = DailyAttendanceSheet(
        sheet_id=new_daily_sheet_id(),
        tenant_id=TENANT,
        store_id=STORE,
        sheet_date=DAY,
        lines=[SheetLine(employee_id=WORKER, auto_status=AutoAttendanceStatus.VERIFIED)],
    )
    sheet.confirm(manager_id=EmployeeId(uuid.uuid4()), confirmed_at=NOW)

    with pytest.raises(DomainRuleError, match="Təsdiqlənmiş tabel"):
        sheet.prefill([])


def test_empty_sheet_cannot_be_confirmed() -> None:
    sheet = DailyAttendanceSheet(
        sheet_id=new_daily_sheet_id(),
        tenant_id=TENANT,
        store_id=STORE,
        sheet_date=DAY,
    )
    with pytest.raises(DomainRuleError, match="Boş tabel"):
        sheet.confirm(manager_id=EmployeeId(uuid.uuid4()), confirmed_at=NOW)


def test_prefill_keeps_manager_notes() -> None:
    """Menecerin yazdığı qeyd yenidən doldurmada İTMİR."""
    sheet = DailyAttendanceSheet(
        sheet_id=new_daily_sheet_id(),
        tenant_id=TENANT,
        store_id=STORE,
        sheet_date=DAY,
        lines=[
            SheetLine(
                employee_id=WORKER,
                auto_status=AutoAttendanceStatus.ABSENT,
                manager_note="PIN sistemi işləmirdi",
            )
        ],
    )
    sheet.prefill([SheetLine(employee_id=WORKER, auto_status=AutoAttendanceStatus.VERIFIED)])

    assert sheet.lines[0].manager_note == "PIN sistemi işləmirdi"


# --------------------------------------------------------------------------- #
# Use case
# --------------------------------------------------------------------------- #


def test_sheet_is_prefilled_not_empty() -> None:
    """Bölmə 3: "Tabel BOŞ başlamır"."""
    ctx = Ctx(
        facts=[AttendanceFact(employee_id=WORKER, planned_off=False, has_verified_check_in=True)]
    )
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL])

    view = ctx.use_case().open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)

    assert len(view.sheet.lines) == 1
    assert view.sheet.lines[0].auto_status is AutoAttendanceStatus.VERIFIED


def test_manager_cannot_open_another_store(_: None = None) -> None:
    ctx = Ctx()
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL])

    with pytest.raises(SheetPermissionError):
        ctx.use_case().open_sheet(tenant_id=TENANT, actor=manager, store_id=OTHER_STORE)


def test_hr_sees_every_store() -> None:
    ctx = Ctx()
    hr = make_employee(SystemRole.HR_ADMIN, flags=[VIEW_REPORTS], store_id=None)

    view = ctx.use_case().open_sheet(tenant_id=TENANT, actor=hr, store_id=OTHER_STORE)

    assert view.sheet.store_id == OTHER_STORE


def test_confirming_with_mismatches_notifies_hr() -> None:
    """Bölmə 3: uyğunsuzluq aşkarlanarsa HR_Admin-ə xəbərdarlıq."""
    ctx = Ctx(facts=[AttendanceFact(employee_id=WORKER, planned_off=False, day_is_over=True)])
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL])
    use_case = ctx.use_case()
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)

    view = use_case.confirm(tenant_id=TENANT, actor=manager, store_id=STORE, sheet_date=DAY)

    assert view.mismatch_count == 1
    assert "ATTENDANCE_SHEET_MISMATCH" in ctx.notifier.categories()
    assert "ATTENDANCE_SHEET_CONFIRMED" in ctx.audit.actions()


def test_confirmation_requires_the_fill_flag() -> None:
    ctx = Ctx(facts=[AttendanceFact(employee_id=WORKER, planned_off=True)])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[VIEW_REPORTS], store_id=None)
    use_case = ctx.use_case()
    use_case.open_sheet(tenant_id=TENANT, actor=hr, store_id=STORE)

    with pytest.raises(SheetPermissionError, match="can_fill_daily_attendance"):
        use_case.confirm(tenant_id=TENANT, actor=hr, store_id=STORE, sheet_date=DAY)
