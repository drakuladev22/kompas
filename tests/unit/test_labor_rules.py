"""Əmək qanunu xəbərdarlıqlarının testləri (#14, Faza 6).

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR — VƏ NİYƏ MƏHZ BU
──────────────────────────────────────────────────────────────────────────────
#14-ün ƏSAS TƏLƏBİ "BLOKLAMIR"dır. Ona görə testlərin yarısı pozuntunun
AŞKARLANDIĞINI, digər yarısı isə təyinatın həmin pozuntuya BAXMAYARAQ
yazıldığını təsbit edir — ikincisi olmasaydı, gələcək bir "təkmilləşdirmə"
xəbərdarlığı istisnaya çevirə bilər və heç bir test qırılmazdı.

Sahtələr BURADA, YERLİ təyin olunub (`tests/fixtures/fakes.py`-a əlavə
edilmir): bu fayl paralel işləyən başqa fazaların sahtə dəstindən asılı
olmamalıdır — asılılıq iki dəyişikliyi bir-birinə bağlar və hər ikisi
"digərinin qırdığı" testlə üzləşərdi.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from src.application.use_cases.labor_compliance import LaborComplianceAdvisor
from src.application.use_cases.shift_scheduling import (
    ShiftPlanningUseCase,
    ShiftSource,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.entities.shift import ShiftAssignment
from src.domain.labor_rules import (
    LaborLimits,
    LaborRuleKind,
    PlannedShift,
    check_consecutive_days,
    check_mandatory_break,
    check_min_rest,
    evaluate_labor_rules,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.catalogs import WorkMode
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
    WorkModeId,
    new_shift_assignment_id,
)
from src.domain.value_objects.scheduling import TimeRange

if TYPE_CHECKING:
    from src.domain.labor_rules import LaborRuleFinding

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)

MORNING = TimeRange(time(9, 0), time(18, 0))  # 9 saat
NIGHT = TimeRange(time(22, 0), time(6, 0))  # gecə növbəsi — 8 saat
SHORT = TimeRange(time(10, 0), time(14, 0))  # 4 saat

DAY = date(2026, 8, 20)

#: İş rejimi kataloqunun test nüsxələri — hər çağırışda yenidən qurmaq
#: sətirləri uzadır və eyni obyektin təkrar yaradılmasından başqa heç nə
#: vermir (kataloq sətri `frozen`-dır, dəyişdirilə bilməz).
MORNING_MODE = WorkMode(name="Səhər növbəsi", tenant_id=TENANT, schedule=MORNING)
SHORT_MODE = WorkMode(name="Qısa növbə", tenant_id=TENANT, schedule=SHORT)

MANAGE_SHIFTS = PermissionFlag(code="can_manage_shifts", category="HR")
FILL_ATTENDANCE = PermissionFlag(
    code="can_fill_daily_attendance", category="NOVBE", hardlock=HardlockLevel.NONE
)

#: Testlərin əsas limit dəsti — DEFAULT_LIMITS ilə eyni, yəni defoltların
#: dəyişməsi bu faylı da qırır (qəsdən: defolt dəyişikliyi görünməli olmalıdır).
LIMITS = LaborLimits.defaults()


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


@dataclass
class FakeClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


class FakeLimits:
    """`SystemLimits` — yalnız `get_int` işlədilir, qalanı istifadə olunmur."""

    def __init__(self, values: dict[str, int] | None = None) -> None:
        self._values = values or {}
        self.requested: list[str] = []

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        self.requested.append(key)
        return self._values.get(key, default)

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return default

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return {}


class FakeWorkModes:
    """`WorkModeRepository.get()` — yalnız oxu; sorğu sayı da izlənir."""

    def __init__(self, modes: dict[WorkModeId, WorkMode]) -> None:
        self._modes = modes
        self.lookups = 0

    def get(self, work_mode_id: WorkModeId) -> WorkMode | None:
        self.lookups += 1
        return self._modes.get(work_mode_id)


class FakeShifts:
    """`ShiftRepository` — yaddaşda təqvim."""

    def __init__(self) -> None:
        self.assignments: dict[tuple[EmployeeId, date], ShiftAssignment] = {}

    def get_assignment(self, employee_id: EmployeeId, work_date: date) -> ShiftAssignment | None:
        return self.assignments.get((employee_id, work_date))

    def save_assignment(self, assignment: ShiftAssignment) -> None:
        self.assignments[(assignment.employee_id, assignment.shift_date)] = assignment

    def clear_assignment(self, employee_id: EmployeeId, work_date: date) -> None:
        self.assignments.pop((employee_id, work_date), None)

    def list_range(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
        employee_ids: list[EmployeeId] | None = None,
    ) -> list[ShiftAssignment]:
        return [
            assignment
            for (employee_id, day), assignment in self.assignments.items()
            if start <= day <= end and (employee_ids is None or employee_id in employee_ids)
        ]

    def is_off_day(self, employee_id: EmployeeId, work_date: date) -> bool:
        assignment = self.assignments.get((employee_id, work_date))
        return assignment.is_off_day if assignment else False

    def scheduled_start(self, employee_id: EmployeeId, work_date: date) -> datetime | None:
        return None


class FakeLeaveRequests:
    """`LeaveRequestRepository` — bu testlərdə açıq icazə YOXDUR."""

    def find_open_for_employee(self, employee_id: EmployeeId) -> None:
        return None


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.entries.append(kwargs)


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


def make_actor() -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.HR_ADMIN.value,
        name_az="HR Admin",
        priority=SystemRole.HR_ADMIN.default_priority,
        is_system=True,
    )
    position.grant(MANAGE_SHIFTS)
    position.grant(FILL_ATTENDANCE)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="H",
        last_name="Admin",
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def planned(day: date, *, schedule: TimeRange | None, off: bool = False) -> PlannedShift:
    return PlannedShift(shift_date=day, is_off_day=off, schedule=schedule)


def kinds(findings: list[LaborRuleFinding]) -> set[LaborRuleKind]:
    return {finding.kind for finding in findings}


# --------------------------------------------------------------------------- #
# 1. Minimum istirahət
# --------------------------------------------------------------------------- #


def test_short_rest_after_a_night_shift_is_reported() -> None:
    """22:00–06:00-dan sonra səhər 09:00 = 3 saat istirahət (limit 12)."""
    findings = check_min_rest(
        planned(DAY, schedule=MORNING),
        {
            DAY - timedelta(days=1): planned(DAY - timedelta(days=1), schedule=NIGHT),
            DAY: planned(DAY, schedule=MORNING),
        },
        LIMITS,
    )
    assert kinds(findings) == {LaborRuleKind.MIN_REST}
    assert "3 saat" in findings[0].message_az
    assert findings[0].related_date == DAY - timedelta(days=1)


def test_the_overnight_end_is_taken_on_the_next_calendar_day() -> None:
    """Gecə növbəsi BİTMƏ ANI ilə ölçülür, bitmə SAATI ilə yox.

    Sadəcə `end` saatına (06:00) baxılsaydı, istirahət 09:00 − 06:00 = 3 saat
    ƏVƏZİNƏ 27 saat çıxardı və qayda heç vaxt işə düşməzdi. Bu test məhz
    həmin sürüşməni qoruyur.
    """
    rest_start = NIGHT.end_on(DAY - timedelta(days=1))
    assert rest_start.date() == DAY, "Gecə növbəsi növbəti gün bitməlidir"


def test_a_normal_two_day_gap_produces_no_warning() -> None:
    """18:00-da bitib növbəti gün 09:00-da başlamaq = 15 saat (limit 12)."""
    findings = check_min_rest(
        planned(DAY, schedule=MORNING),
        {DAY - timedelta(days=1): planned(DAY - timedelta(days=1), schedule=MORNING)},
        LIMITS,
    )
    assert findings == []


def test_the_following_shift_is_checked_too() -> None:
    """Ortadakı günü gecə növbəsinə çevirmək SABAHKI növbəni pozur."""
    findings = check_min_rest(
        planned(DAY, schedule=NIGHT),
        {DAY + timedelta(days=1): planned(DAY + timedelta(days=1), schedule=MORNING)},
        LIMITS,
    )
    assert kinds(findings) == {LaborRuleKind.MIN_REST}
    assert findings[0].related_date == DAY + timedelta(days=1)


def test_overlapping_shifts_get_their_own_sentence() -> None:
    """Mənfi fasilə "−2 saat" kimi yazılmır — üst-üstə düşmə açıq deyilir."""
    late_night = TimeRange(time(20, 0), time(10, 0))  # 14 saat, gecəni keçir
    findings = check_min_rest(
        planned(DAY, schedule=MORNING),
        {DAY - timedelta(days=1): planned(DAY - timedelta(days=1), schedule=late_night)},
        LIMITS,
    )
    assert "ÜST-ÜSTƏ DÜŞÜR" in findings[0].message_az


def test_a_neighbour_without_a_fixed_schedule_silences_the_rule() -> None:
    """ "Növbəli 2/2" rejimində saat yoxdur — uydurma saatla xəbərdarlıq olmaz."""
    findings = check_min_rest(
        planned(DAY, schedule=MORNING),
        {DAY - timedelta(days=1): planned(DAY - timedelta(days=1), schedule=None)},
        LIMITS,
    )
    assert findings == []


def test_an_unplanned_gap_day_stops_the_neighbour_search() -> None:
    """Planlaşdırılmamış gün "ardıcıl növbə" zəncirini kəsir.

    İki gün əvvəlki gecə növbəsi ilə müqayisə etmək "iki ARDICIL növbə"
    tərifini pozardı — aradakı gün planda yoxdursa, o növbə qonşu deyil.
    """
    findings = check_min_rest(
        planned(DAY, schedule=MORNING),
        {DAY - timedelta(days=2): planned(DAY - timedelta(days=2), schedule=NIGHT)},
        LIMITS,
    )
    assert findings == []


def test_zero_min_rest_disables_the_rule() -> None:
    """0 = qayda susur (Root bir qaydanı ayrıca söndürə bilməlidir)."""
    findings = check_min_rest(
        planned(DAY, schedule=MORNING),
        {DAY - timedelta(days=1): planned(DAY - timedelta(days=1), schedule=NIGHT)},
        LaborLimits(0, 60, 6, 6),
    )
    assert findings == []


# --------------------------------------------------------------------------- #
# 2. Məcburi fasilə
# --------------------------------------------------------------------------- #


def test_a_long_shift_reminds_about_the_mandatory_break() -> None:
    findings = check_mandatory_break(planned(DAY, schedule=MORNING), LIMITS)
    assert kinds(findings) == {LaborRuleKind.MANDATORY_BREAK}
    assert "60 dəqiqəlik" in findings[0].message_az
    assert "9 saat" in findings[0].message_az


def test_a_short_shift_needs_no_break_reminder() -> None:
    assert check_mandatory_break(planned(DAY, schedule=SHORT), LIMITS) == []


def test_an_off_day_never_needs_a_break() -> None:
    assert check_mandatory_break(planned(DAY, schedule=None, off=True), LIMITS) == []


def test_zero_break_minutes_disables_the_rule() -> None:
    assert check_mandatory_break(planned(DAY, schedule=MORNING), LaborLimits(12, 0, 6, 6)) == []


# --------------------------------------------------------------------------- #
# 3. Maksimum ardıcıl iş günü
# --------------------------------------------------------------------------- #


def test_the_seventh_consecutive_day_is_reported() -> None:
    plan = {
        DAY - timedelta(days=offset): planned(DAY - timedelta(days=offset), schedule=MORNING)
        for offset in range(7)
    }
    findings = check_consecutive_days(plan[DAY], plan, LIMITS)
    assert kinds(findings) == {LaborRuleKind.MAX_CONSECUTIVE_DAYS}
    assert "7 olur" in findings[0].message_az


def test_six_consecutive_days_are_allowed_by_default() -> None:
    """6/1 iş rejimi (`ShiftPlanningScreen.TEMPLATES`) xəbərdarlıq doğurmur."""
    plan = {
        DAY - timedelta(days=offset): planned(DAY - timedelta(days=offset), schedule=MORNING)
        for offset in range(6)
    }
    assert check_consecutive_days(plan[DAY], plan, LIMITS) == []


def test_an_off_day_in_the_middle_breaks_the_streak() -> None:
    plan = {
        DAY - timedelta(days=offset): planned(DAY - timedelta(days=offset), schedule=MORNING)
        for offset in range(8)
    }
    plan[DAY - timedelta(days=3)] = planned(DAY - timedelta(days=3), schedule=None, off=True)
    assert check_consecutive_days(plan[DAY], plan, LIMITS) == []


def test_assigning_an_off_day_never_warns() -> None:
    """İstirahət günü zənciri yalnız QISALDA bilər — düzəlişə xəbərdarlıq olmaz."""
    plan = {
        DAY - timedelta(days=offset): planned(DAY - timedelta(days=offset), schedule=MORNING)
        for offset in range(1, 10)
    }
    target = planned(DAY, schedule=None, off=True)
    plan[DAY] = target
    assert check_consecutive_days(target, plan, LIMITS) == []


def test_the_streak_counts_days_after_the_target_as_well() -> None:
    """Ortadakı boşluğu doldurmaq İKİ zənciri birləşdirir."""
    plan = {}
    for offset in range(1, 4):
        earlier = DAY - timedelta(days=offset)
        plan[earlier] = planned(earlier, schedule=MORNING)
    for offset in range(1, 4):
        later = DAY + timedelta(days=offset)
        plan[later] = planned(later, schedule=MORNING)
    target = planned(DAY, schedule=MORNING)
    plan[DAY] = target

    findings = check_consecutive_days(target, plan, LIMITS)
    assert kinds(findings) == {LaborRuleKind.MAX_CONSECUTIVE_DAYS}
    assert "7 olur" in findings[0].message_az


# --------------------------------------------------------------------------- #
# 4. Limit oxunuşu — hardcode ədəd yoxdur
# --------------------------------------------------------------------------- #


def test_the_defaults_come_from_the_system_limit_catalogue() -> None:
    """`LaborLimits.defaults()` yalnız `DEFAULT_LIMITS`-i təkrarlayır."""
    assert LIMITS.min_rest_hours == int(DEFAULT_LIMITS[SystemLimitKey.LABOR_MIN_REST_HOURS])
    assert LIMITS.mandatory_break_minutes == int(
        DEFAULT_LIMITS[SystemLimitKey.LABOR_MANDATORY_BREAK_MINUTES]
    )
    assert LIMITS.break_required_after_hours == int(
        DEFAULT_LIMITS[SystemLimitKey.LABOR_BREAK_REQUIRED_AFTER_HOURS]
    )
    assert LIMITS.max_consecutive_work_days == int(
        DEFAULT_LIMITS[SystemLimitKey.LABOR_MAX_CONSECUTIVE_WORK_DAYS]
    )


def test_every_new_root_parameter_is_seeded_by_migration_025() -> None:
    """Elan edilmiş, lakin SEED EDİLMƏMİŞ açar ROOT ekranında GÖRÜNMÜR.

    Bu, funksional qüsur vermir (kod `DEFAULT_LIMITS` ilə işləyir), ona görə
    heç bir digər test onu tutmur — parametr sükutla sabitə çevrilir və Root
    onu dəyişə bilmir. Miqrasiya 022/023/024 məhz bu boşluğu bağlamışdı;
    bu test onun 025-də təkrarlanmamasını təmin edir.
    """
    migration = (
        Path(__file__).resolve().parents[2]
        / "database/migrations/025_labor_and_staffing_limits.sql"
    ).read_text(encoding="utf-8")

    phase_six_keys = [
        key.value for key in SystemLimitKey if key.value.startswith(("LABOR_", "STAFFING_PATTERN_"))
    ]
    assert phase_six_keys, "Faza 6 açarları `SystemLimitKey`-dən itib"

    missing = [key for key in phase_six_keys if f"'{key}'" not in migration]
    assert not missing, f"025 seed etmir: {missing}"

    # Defolt dəyər İKİ yerdə yazılır (kod + SQL) — uyğunsuzluq təzə
    # quraşdırmada kodun bildiyindən FƏRQLİ dəyər yaradardı.
    for key in phase_six_keys:
        expected = DEFAULT_LIMITS[SystemLimitKey(key)]
        assert f"'{key}', '{expected}'" in migration, (
            f"{key} defoltu kod ({expected}) ilə 025 arasında fərqlənir"
        )


def test_negative_root_values_are_clamped_instead_of_crashing() -> None:
    """Ekranı yan keçən skript mənfi yaza bilər — matris çökməməlidir."""
    limits = LaborLimits(-5, -1, -2, -3)
    assert (limits.min_rest_hours, limits.mandatory_break_minutes) == (0, 0)
    assert (limits.break_required_after_hours, limits.max_consecutive_work_days) == (0, 0)


def test_the_advisor_reads_all_four_keys_from_system_limits() -> None:
    limits = FakeLimits()
    advisor = LaborComplianceAdvisor(
        shifts=FakeShifts(), work_modes=FakeWorkModes({}), limits=limits
    )
    advisor.review(
        tenant_id=TENANT,
        employee_id=WORKER,
        shift_date=DAY,
        is_off_day=True,
        work_mode_id=None,
    )
    assert set(limits.requested) == {
        SystemLimitKey.LABOR_MIN_REST_HOURS.value,
        SystemLimitKey.LABOR_MANDATORY_BREAK_MINUTES.value,
        SystemLimitKey.LABOR_BREAK_REQUIRED_AFTER_HOURS.value,
        SystemLimitKey.LABOR_MAX_CONSECUTIVE_WORK_DAYS.value,
    }


def test_a_root_override_changes_the_outcome() -> None:
    """Limit ROOT-dan gəlir: 4 saatlıq hədd qısa növbədə də xəbərdarlıq verir."""
    mode_id = WorkModeId(uuid.uuid4())
    shifts = FakeShifts()
    advisor = LaborComplianceAdvisor(
        shifts=shifts,
        work_modes=FakeWorkModes({mode_id: SHORT_MODE}),
        limits=FakeLimits({SystemLimitKey.LABOR_BREAK_REQUIRED_AFTER_HOURS.value: 3}),
    )
    findings = advisor.review(
        tenant_id=TENANT,
        employee_id=WORKER,
        shift_date=DAY,
        is_off_day=False,
        work_mode_id=mode_id,
    )
    assert kinds(findings) == {LaborRuleKind.MANDATORY_BREAK}


def test_the_work_mode_lookup_is_cached_within_one_review() -> None:
    """Eyni rejimə istinad edən 15 gün 15 sorğu YARATMAMALIDIR."""
    mode_id = WorkModeId(uuid.uuid4())
    shifts = FakeShifts()
    for offset in range(-3, 4):
        day = DAY + timedelta(days=offset)
        shifts.save_assignment(
            ShiftAssignment(
                assignment_id=new_shift_assignment_id(),
                tenant_id=TENANT,
                employee_id=WORKER,
                shift_date=day,
                is_off_day=False,
                work_mode_id=mode_id,
            )
        )
    modes = FakeWorkModes({mode_id: MORNING_MODE})
    advisor = LaborComplianceAdvisor(shifts=shifts, work_modes=modes, limits=FakeLimits())
    advisor.review(
        tenant_id=TENANT,
        employee_id=WORKER,
        shift_date=DAY,
        is_off_day=False,
        work_mode_id=mode_id,
    )
    assert modes.lookups == 1


def test_another_employees_rows_never_enter_the_window() -> None:
    """Süzgəci görməzdən gələn mənbə tamamilə yanlış zəncir qurardı."""
    mode_id = WorkModeId(uuid.uuid4())
    other = EmployeeId(uuid.uuid4())

    class LeakyShifts(FakeShifts):
        def list_range(
            self,
            tenant_id: TenantId,
            *,
            start: date,
            end: date,
            store_id: StoreId | None = None,
            employee_ids: list[EmployeeId] | None = None,
        ) -> list[ShiftAssignment]:
            # Süzgəc QƏSDƏN görməzdən gəlinir.
            return super().list_range(tenant_id, start=start, end=end)

    shifts = LeakyShifts()
    for offset in range(1, 7):
        shifts.save_assignment(
            ShiftAssignment(
                assignment_id=new_shift_assignment_id(),
                tenant_id=TENANT,
                employee_id=other,
                shift_date=DAY - timedelta(days=offset),
                is_off_day=False,
                work_mode_id=mode_id,
            )
        )
    advisor = LaborComplianceAdvisor(
        shifts=shifts,
        work_modes=FakeWorkModes({mode_id: MORNING_MODE}),
        limits=FakeLimits(),
    )
    findings = advisor.review(
        tenant_id=TENANT,
        employee_id=WORKER,
        shift_date=DAY,
        is_off_day=False,
        work_mode_id=mode_id,
    )
    assert LaborRuleKind.MAX_CONSECUTIVE_DAYS not in kinds(findings)


# --------------------------------------------------------------------------- #
# 5. Shift Matrix inteqrasiyası — BLOKLAMIR
# --------------------------------------------------------------------------- #


def _planning_with_labor() -> tuple[ShiftPlanningUseCase, FakeShifts, RecordingAudit, WorkModeId]:
    mode_id = WorkModeId(uuid.uuid4())
    shifts = FakeShifts()
    audit = RecordingAudit()
    planning = ShiftPlanningUseCase(
        shifts=shifts,
        leave_requests=FakeLeaveRequests(),
        audit=audit,
        clock=FakeClock(),
        notifier=RecordingNotifier(),
        labor=LaborComplianceAdvisor(
            shifts=shifts,
            work_modes=FakeWorkModes({mode_id: MORNING_MODE}),
            limits=FakeLimits(),
        ),
    )
    return planning, shifts, audit, mode_id


def test_the_assignment_is_written_despite_the_warning() -> None:
    """QIRMIZI XƏTT: xəbərdarlıq BLOKLAMIR — sətir yazılır."""
    planning, shifts, _, mode_id = _planning_with_labor()
    for offset in range(1, 7):
        shifts.save_assignment(
            ShiftAssignment(
                assignment_id=new_shift_assignment_id(),
                tenant_id=TENANT,
                employee_id=WORKER,
                shift_date=DAY - timedelta(days=offset),
                is_off_day=False,
                work_mode_id=mode_id,
            )
        )

    result = planning.assign_work_day(
        tenant_id=TENANT,
        actor=make_actor(),
        employee_id=WORKER,
        shift_date=DAY,
        work_mode_id=mode_id,
    )

    assert result.assignment is not None, "Təyinat YAZILMALIDIR — qayda bloklamır"
    assert shifts.get_assignment(WORKER, DAY) is not None
    assert result.has_conflicts
    assert LaborRuleKind.MAX_CONSECUTIVE_DAYS.value in {c.kind for c in result.conflicts}


def test_the_warning_reaches_the_audit_trail() -> None:
    """ "Xəbərdarlıq edildi, buna baxmayaraq təyin etdi" faktı sübutlu olmalıdır."""
    planning, shifts, audit, mode_id = _planning_with_labor()
    for offset in range(1, 7):
        shifts.save_assignment(
            ShiftAssignment(
                assignment_id=new_shift_assignment_id(),
                tenant_id=TENANT,
                employee_id=WORKER,
                shift_date=DAY - timedelta(days=offset),
                is_off_day=False,
                work_mode_id=mode_id,
            )
        )
    planning.assign_work_day(
        tenant_id=TENANT,
        actor=make_actor(),
        employee_id=WORKER,
        shift_date=DAY,
        work_mode_id=mode_id,
    )

    entry = next(item for item in audit.entries if item["action"] == "SHIFT_ASSIGNED")
    after_state = entry["after_state"]
    assert isinstance(after_state, dict)
    assert LaborRuleKind.MAX_CONSECUTIVE_DAYS.value in after_state["conflicts"]


def test_no_notification_is_sent_for_a_labor_warning() -> None:
    """Ekran qarşısındakı admin üçün mesaj — bildiriş kanalı doldurulmur."""
    mode_id = WorkModeId(uuid.uuid4())
    shifts = FakeShifts()
    notifier = RecordingNotifier()
    planning = ShiftPlanningUseCase(
        shifts=shifts,
        leave_requests=FakeLeaveRequests(),
        audit=RecordingAudit(),
        clock=FakeClock(),
        notifier=notifier,
        labor=LaborComplianceAdvisor(
            shifts=shifts,
            work_modes=FakeWorkModes({mode_id: MORNING_MODE}),
            limits=FakeLimits(),
        ),
    )
    planning.assign_work_day(
        tenant_id=TENANT,
        actor=make_actor(),
        employee_id=WORKER,
        shift_date=DAY,
        work_mode_id=mode_id,
    )
    assert notifier.messages == []


def test_without_the_advisor_the_use_case_behaves_exactly_as_before() -> None:
    """Fail-open: məsləhətçi qoşulmayıbsa Faza 5 davranışı toxunulmazdır."""
    shifts = FakeShifts()
    planning = ShiftPlanningUseCase(
        shifts=shifts,
        leave_requests=FakeLeaveRequests(),
        audit=RecordingAudit(),
        clock=FakeClock(),
        notifier=RecordingNotifier(),
    )
    result = planning.apply_assignment(
        tenant_id=TENANT,
        actor_id=WORKER,
        employee_id=WORKER,
        shift_date=DAY,
        is_off_day=False,
        work_mode_id=WorkModeId(uuid.uuid4()),
        source=ShiftSource.ADMIN_MATRIX,
    )
    assert result.conflicts == []
    assert result.assignment is not None


def test_a_clean_week_produces_no_warning_at_all() -> None:
    """Yalançı xəbərdarlıq testi: 5/2 rejimi tamamilə təmiz olmalıdır."""
    mode_id = WorkModeId(uuid.uuid4())
    shifts = FakeShifts()
    monday = date(2026, 8, 17)
    for offset in range(4):
        shifts.save_assignment(
            ShiftAssignment(
                assignment_id=new_shift_assignment_id(),
                tenant_id=TENANT,
                employee_id=WORKER,
                shift_date=monday + timedelta(days=offset),
                is_off_day=False,
                work_mode_id=mode_id,
            )
        )
    advisor = LaborComplianceAdvisor(
        shifts=shifts,
        work_modes=FakeWorkModes({mode_id: SHORT_MODE}),
        limits=FakeLimits(),
    )
    findings = advisor.review(
        tenant_id=TENANT,
        employee_id=WORKER,
        shift_date=monday + timedelta(days=4),
        is_off_day=False,
        work_mode_id=mode_id,
    )
    assert findings == []


def test_evaluate_labor_rules_merges_the_target_over_the_stored_window() -> None:
    """Hələ yazılmamış dəyişiklik də yoxlana bilməlidir."""
    stored = [planned(DAY, schedule=None, off=True)]
    findings = evaluate_labor_rules(
        target=planned(DAY, schedule=MORNING),
        window=stored,
        limits=LIMITS,
    )
    assert kinds(findings) == {LaborRuleKind.MANDATORY_BREAK}
