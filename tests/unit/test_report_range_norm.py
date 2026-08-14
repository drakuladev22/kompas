"""Tarix aralığı, dinamik norma və pro-rata — kompas1.md Faza 7.

──────────────────────────────────────────────────────────────────────────────
BU FAYLIN ÜÇ MƏRKƏZİ TESTİ
──────────────────────────────────────────────────────────────────────────────
Buradakı rəqəmlər real pul kəsintisinə çevrilir, ona görə hər hesablamanın öz
testi var. Üçü isə struktur qərarları qoruyur:

  1. `test_fine_on_the_last_day_of_the_range_inside_the_open_window_is_excluded`
     — STRUKTUR QƏRAR D (LOCK). Tarix aralığı seçmək 72 saatlıq etiraz
     pəncərəsini BAYPAS EDƏ BİLMİR.
  2. `test_overlapping_range_never_charges_the_same_fine_twice`
     — üst-üstə düşən iki export işçidən İKİQAT pul kəsə bilməz.
  3. `test_overlapping_range_reports_the_skipped_fines_instead_of_silence`
     — və həmin atlama SÜKUTLA baş vermir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from src.application.use_cases.reporting import (
    AttendanceRow,
    EmployeeAttendanceFacts,
    EmployeePlanFacts,
    EmployeeSalesFacts,
    MonthlyReportUseCase,
    ReportPeriod,
    ReportPeriodError,
    ReportPermissionError,
    ReportRange,
    ReportRangeTooLongError,
)
from src.domain.entities.fine import Fine, FineSource
from src.domain.entities.position import Position
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FineId,
    FineTypeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import TimeRange
from src.domain.work_norm import (
    EmploymentWindow,
    PlannedDay,
    WorkNorm,
    WorkNormError,
    WorkNormRequest,
    calculate_work_norm,
    calendar_days,
    daily_norm_hours,
)
from tests.fixtures.fakes import FakeSystemLimits

TENANT = TenantId(uuid.uuid4())
EMPLOYEE = EmployeeId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
REVIEWER = EmployeeId(uuid.uuid4())

MORNING = TimeRange(start=time(9, 0), end=time(18, 0))  # 9 saat
EVENING = TimeRange(start=time(13, 0), end=time(22, 0))  # 9 saat
SHORT = TimeRange(start=time(9, 0), end=time(15, 0))  # 6 saat
NIGHT = TimeRange(start=time(22, 0), end=time(6, 0))  # 8 saat, gecə növbəsi
LONG = TimeRange(start=time(8, 0), end=time(20, 0))  # 12 saat


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _actor(*, can_export: bool = True):  # type: ignore[no-untyped-def]
    from src.domain.entities.employee import Employee, PermissionOverride

    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.ADMIN,
        tenant_id=TENANT,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Aygün",
        last_name="Əliyeva",
        username=Username("a.aliyeva"),
        has_password=True,
    )
    if can_export:
        employee.apply_override(
            PermissionOverride(
                flag_code="can_export_reports",
                effect=PermissionEffect.GRANT,
                granted_by=REVIEWER,
            )
        )
    return employee


def _use_case(**overrides: str) -> MonthlyReportUseCase:
    return MonthlyReportUseCase(limits=FakeSystemLimits(overrides))


def _work_days(start: date, count: int, schedule: TimeRange | None = MORNING) -> list[PlannedDay]:
    return [
        PlannedDay(day=start + timedelta(days=offset), is_off_day=False, schedule=schedule)
        for offset in range(count)
    ]


def _norm(
    *,
    start: date,
    end: date,
    plan: list[PlannedDay],
    employment: EmploymentWindow | None = None,
    legal: str = "8.00",
) -> WorkNorm:
    return calculate_work_norm(
        WorkNormRequest(
            start=start,
            end=end,
            plan=tuple(plan),
            employment=employment or EmploymentWindow(),
            legal_daily_norm_hours=Decimal(legal),
        )
    )


def _attendance_fact(*, employee_id: EmployeeId = EMPLOYEE) -> EmployeeAttendanceFacts:
    return EmployeeAttendanceFacts(
        employee_id=employee_id,
        full_name="Rəşad Məmmədov",
        store_name="Bellona 28 May",
        position_name="Satıcı",
        # SQL sayğacı QƏSDƏN mənasız rəqəmlərlə doldurulub: aralıq yolunun
        # normanı ONDAN GÖTÜRMƏDİYİ yalnız belə sübut oluna bilər.
        norm_work_days=999,
        actual_worked_days=12,
        off_days=999,
        unauthorized_absences=1,
    )


def _sales_facts() -> list[EmployeeSalesFacts]:
    return [
        EmployeeSalesFacts(
            employee_id=EMPLOYEE,
            full_name="Rəşad Məmmədov",
            store_name="Bellona 28 May",
            gross_sales=Money(Decimal("18450.00")),
            earned_points=320,
        )
    ]


def _published_fine(*, published_at: datetime, amount: str = "25.00") -> Fine:
    fine = Fine(
        fine_id=FineId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=EMPLOYEE,
        store_id=STORE,
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal(amount)),
        issued_at=published_at - timedelta(hours=1),
        fine_type_id=FineTypeId(uuid.uuid4()),
        issued_by=REVIEWER,
        photo_evidence_url="https://drive/evidence.jpg",
    )
    fine.publish(reviewed_by=REVIEWER, published_at=published_at)
    return fine


# --------------------------------------------------------------------------- #
# 1. Tarix aralığı — TAM AY YOLU DƏYİŞMİR
# --------------------------------------------------------------------------- #


def test_full_month_range_produces_the_legacy_month_key() -> None:
    """Tam ay export-u Faza 7-dən SONRA da EYNİ `exported_period` yazır."""
    assert ReportRange.for_month(2026, 8).key == ReportPeriod(2026, 8).key == "2026-08"


def test_full_month_range_keeps_the_legacy_label() -> None:
    assert ReportRange.for_month(2026, 8).label_az() == ReportPeriod(2026, 8).label_az()


def test_period_converts_to_a_range_without_losing_its_key() -> None:
    period = ReportPeriod(2026, 2)
    assert period.to_range().key == period.key
    assert period.to_range().end == date(2026, 2, 28)


def test_leap_february_ends_on_the_twenty_ninth() -> None:
    """Ayın uzunluğu `calendar`-dan gəlir — 28 hardcode edilməyib."""
    assert ReportRange.for_month(2024, 2).end == date(2024, 2, 29)
    assert ReportRange.for_month(2024, 2).day_count == 29


def test_custom_range_key_is_filename_safe() -> None:
    key = ReportRange(date(2026, 4, 1), date(2026, 4, 15)).key
    assert key == "2026-04-01_2026-04-15"
    assert "." not in key and "/" not in key and "\\" not in key


def test_custom_range_label_shows_both_ends() -> None:
    label = ReportRange(date(2026, 4, 1), date(2026, 4, 15)).label_az()
    assert label == "01.04.2026 – 15.04.2026"


def test_single_day_range_counts_one_day() -> None:
    """Bir günlük aralıq QANUNİDİR və 1 gün sayılır, 0 yox."""
    one_day = ReportRange(date(2026, 4, 7), date(2026, 4, 7))
    assert one_day.day_count == 1
    assert not one_day.is_full_month
    assert one_day.key == "2026-04-07_2026-04-07"


def test_range_starting_after_it_ends_is_rejected() -> None:
    with pytest.raises(ReportPeriodError) as error:
        ReportRange(date(2026, 4, 15), date(2026, 4, 1))
    assert "əvvəl" in error.value.user_message


def test_partial_month_is_not_a_full_month() -> None:
    assert not ReportRange(date(2026, 4, 1), date(2026, 4, 29)).is_full_month
    assert not ReportRange(date(2026, 4, 2), date(2026, 4, 30)).is_full_month
    assert ReportRange(date(2026, 4, 1), date(2026, 4, 30)).is_full_month


def test_range_crossing_a_month_boundary_is_not_a_full_month() -> None:
    assert not ReportRange(date(2025, 12, 20), date(2026, 1, 10)).is_full_month


def test_absurd_year_is_rejected() -> None:
    with pytest.raises(ReportPeriodError):
        ReportRange(date(1999, 1, 1), date(1999, 1, 31))


def test_range_contains_its_own_boundaries() -> None:
    span = ReportRange(date(2026, 4, 1), date(2026, 4, 15))
    assert span.contains(date(2026, 4, 1))
    assert span.contains(date(2026, 4, 15))
    assert not span.contains(date(2026, 4, 16))


def test_calendar_days_covers_both_ends() -> None:
    days = calendar_days(date(2026, 4, 1), date(2026, 4, 3))
    assert days == [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]
    assert calendar_days(date(2026, 4, 3), date(2026, 4, 1)) == []


# --------------------------------------------------------------------------- #
# 2. ROOT PARAMETRİ — maksimum aralıq uzunluğu
# --------------------------------------------------------------------------- #


def test_range_longer_than_the_root_limit_is_rejected_with_a_clear_message() -> None:
    """Hədd aşılanda SÜKUTLA rədd YOXDUR — mesaj hər iki rəqəmi göstərir."""
    use_case = _use_case(**{SystemLimitKey.REPORT_RANGE_MAX_DAYS.value: "30"})
    with pytest.raises(ReportRangeTooLongError) as error:
        use_case.resolve_range(tenant_id=TENANT, start=date(2026, 1, 1), end=date(2026, 3, 1))
    message = error.value.user_message
    assert "60 gündür" in message
    assert "30 gündür" in message
    assert SystemLimitKey.REPORT_RANGE_MAX_DAYS.value in message


def test_the_maximum_range_is_read_from_root_and_not_hardcoded() -> None:
    """Root həddi artırırsa, əvvəl rədd edilən aralıq QƏBUL edilməlidir."""
    strict = _use_case(**{SystemLimitKey.REPORT_RANGE_MAX_DAYS.value: "10"})
    generous = _use_case(**{SystemLimitKey.REPORT_RANGE_MAX_DAYS.value: "400"})
    start, end = date(2026, 1, 1), date(2026, 2, 1)

    with pytest.raises(ReportRangeTooLongError):
        strict.resolve_range(tenant_id=TENANT, start=start, end=end)
    assert generous.resolve_range(tenant_id=TENANT, start=start, end=end).day_count == 32


def test_a_range_exactly_at_the_limit_is_accepted() -> None:
    use_case = _use_case(**{SystemLimitKey.REPORT_RANGE_MAX_DAYS.value: "31"})
    span = use_case.resolve_range(tenant_id=TENANT, start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert span.day_count == 31


def test_the_full_month_path_ignores_the_range_limit() -> None:
    """Root həddi 15 günə salsa belə, tam ay hesabatı çıxarıla bilməlidir."""
    use_case = _use_case(**{SystemLimitKey.REPORT_RANGE_MAX_DAYS.value: "15"})
    assert use_case.resolve_month(year=2026, month=1).day_count == 31


def test_a_meaningless_root_limit_falls_back_instead_of_blocking_everything() -> None:
    """`0` yazılsaydı HƏR aralıq bloklanardı — bir yazı səhvi export-u dayandırardı."""
    use_case = _use_case(**{SystemLimitKey.REPORT_RANGE_MAX_DAYS.value: "0"})
    assert (
        use_case.resolve_range(
            tenant_id=TENANT, start=date(2026, 1, 1), end=date(2026, 1, 31)
        ).day_count
        == 31
    )


def test_the_use_case_works_without_a_limits_port() -> None:
    """Maket/test yolu portsuz qurula bilir və davranış dəyişmir."""
    assert MonthlyReportUseCase().resolve_month(year=2026, month=8).key == "2026-08"


# --------------------------------------------------------------------------- #
# 3. DİNAMİK NORMA — Shift Matrix-dən, sabit aylıq norma YOX
# --------------------------------------------------------------------------- #


def test_norm_days_come_from_the_shift_matrix() -> None:
    norm = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 30), plan=_work_days(date(2026, 4, 1), 3)
    )
    assert norm.norm_work_days == 3
    assert norm.range_days == 30


def test_off_days_are_counted_separately_and_carry_no_norm() -> None:
    plan = [
        PlannedDay(day=date(2026, 4, 1), is_off_day=False, schedule=MORNING),
        PlannedDay(day=date(2026, 4, 2), is_off_day=True, schedule=None),
        PlannedDay(day=date(2026, 4, 3), is_off_day=True, schedule=MORNING),
    ]
    norm = _norm(start=date(2026, 4, 1), end=date(2026, 4, 3), plan=plan)
    assert norm.norm_work_days == 1
    assert norm.off_days == 2
    assert norm.norm_work_hours == Decimal("8.00")


def test_plan_rows_outside_the_range_are_ignored() -> None:
    plan = _work_days(date(2026, 3, 28), 8)  # 28 mart – 4 aprel
    norm = _norm(start=date(2026, 4, 1), end=date(2026, 4, 30), plan=plan)
    assert norm.norm_work_days == 4


def test_duplicate_plan_rows_never_double_count_a_day() -> None:
    """Təkrar sətir işçiyə çatmayan saatı «planlaşdırılmış» göstərərdi."""
    day = date(2026, 4, 1)
    plan = [
        PlannedDay(day=day, is_off_day=False, schedule=MORNING),
        PlannedDay(day=day, is_off_day=False, schedule=MORNING),
    ]
    norm = _norm(start=day, end=day, plan=plan)
    assert norm.norm_work_days == 1
    assert norm.norm_work_hours == Decimal("8.00")


def test_an_empty_plan_gives_a_zero_norm_and_no_crash() -> None:
    norm = _norm(start=date(2026, 4, 1), end=date(2026, 4, 30), plan=[])
    assert norm.norm_work_days == 0
    assert norm.norm_work_hours == Decimal("0.00")


# --------------------------------------------------------------------------- #
# 4. İŞ REJİMİ NORMASI + `OVERTIME_DAILY_NORM_HOURS` ZİDDİYYƏTİ
# --------------------------------------------------------------------------- #


def test_a_short_work_mode_produces_a_smaller_norm_than_a_long_one() -> None:
    """Hər işçinin rejiminə görə FƏRQLİ norma (9:00–15:00 ≠ 9:00–18:00)."""
    short = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 5), plan=_work_days(date(2026, 4, 1), 5, SHORT)
    )
    full = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 5), plan=_work_days(date(2026, 4, 1), 5, MORNING)
    )
    assert short.norm_work_hours == Decimal("30.00")  # 5 × 6 saat
    assert full.norm_work_hours == Decimal("40.00")  # 5 × min(9, 8) saat
    assert short.norm_work_days == full.norm_work_days == 5


def test_a_schedule_longer_than_the_legal_norm_is_capped_and_the_cap_is_visible() -> None:
    """12 saatlıq növbə: norma 8, qalan 4 saat AŞIM jurnalının payıdır."""
    norm = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 2), plan=_work_days(date(2026, 4, 1), 2, LONG)
    )
    assert norm.norm_work_hours == Decimal("16.00")
    assert norm.scheduled_hours == Decimal("24.00")
    assert norm.capped_days == 2


def test_the_legal_norm_comes_from_root_so_the_two_sources_cannot_diverge() -> None:
    """Root gündəlik normanı 10-a qaldırsa, sıxılma NÖQTƏSİ də dəyişməlidir."""
    default_cap = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 1), plan=_work_days(date(2026, 4, 1), 1, LONG)
    )
    raised_cap = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 1),
        plan=_work_days(date(2026, 4, 1), 1, LONG),
        legal="10.00",
    )
    assert default_cap.norm_work_hours == Decimal("8.00")
    assert raised_cap.norm_work_hours == Decimal("10.00")
    assert raised_cap.capped_days == 1


def test_a_mode_without_fixed_hours_falls_back_to_the_legal_daily_norm() -> None:
    """ "Növbəli 2/2" — uydurma saat seçilmir, hüquqi norma tətbiq olunur."""
    norm = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 3), plan=_work_days(date(2026, 4, 1), 3, None)
    )
    assert norm.norm_work_hours == Decimal("24.00")
    assert norm.unscheduled_plan_days == 3
    assert norm.capped_days == 0


def test_a_meaningless_legal_norm_falls_back_instead_of_zeroing_the_report() -> None:
    norm = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 1),
        plan=_work_days(date(2026, 4, 1), 1, LONG),
        legal="0",
    )
    assert norm.norm_work_hours == Decimal("8.00")


def test_the_screen_and_the_report_use_the_same_daily_norm_function() -> None:
    """GUI nişanı ilə hesabat rəqəmi eyni funksiyadan gəlir."""
    assert daily_norm_hours(MORNING, legal_daily_norm_hours=Decimal("8.00")) == Decimal("8.00")
    assert daily_norm_hours(SHORT, legal_daily_norm_hours=Decimal("8.00")) == Decimal("6.00")
    assert daily_norm_hours(None, legal_daily_norm_hours=Decimal("8.00")) == Decimal("8.00")


def test_daily_norm_hours_uses_the_module_fallback_when_no_root_value_is_given() -> None:
    assert daily_norm_hours(None) == Decimal("8.00")


# --------------------------------------------------------------------------- #
# 5. GECƏ NÖVBƏSİ — AY/İL SƏRHƏDİ
# --------------------------------------------------------------------------- #


def test_an_overnight_shift_counts_its_full_duration() -> None:
    """22:00–06:00 = 8 saat; sadə `end − start` MƏNFİ verərdi."""
    assert NIGHT.is_overnight
    norm = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 1), plan=_work_days(date(2026, 4, 1), 1, NIGHT)
    )
    assert norm.norm_work_hours == Decimal("8.00")
    assert norm.capped_days == 0


def test_an_overnight_shift_on_new_years_eve_stays_in_the_old_year() -> None:
    """31 dekabr 22:00–06:00 tam 8 saatı ilə DEKABRA düşür, yanvara sızmır."""
    december = ReportRange(date(2025, 12, 1), date(2025, 12, 31))
    january = ReportRange(date(2026, 1, 1), date(2026, 1, 31))
    plan = [PlannedDay(day=date(2025, 12, 31), is_off_day=False, schedule=NIGHT)]

    in_december = _norm(start=december.start, end=december.end, plan=plan)
    in_january = _norm(start=january.start, end=january.end, plan=plan)

    assert in_december.norm_work_days == 1
    assert in_december.norm_work_hours == Decimal("8.00")
    assert in_january.norm_work_days == 0
    assert in_january.norm_work_hours == Decimal("0.00")


def test_an_overnight_shift_on_the_last_day_of_a_month_stays_in_that_month() -> None:
    plan = [PlannedDay(day=date(2026, 4, 30), is_off_day=False, schedule=NIGHT)]
    april = _norm(start=date(2026, 4, 1), end=date(2026, 4, 30), plan=plan)
    may = _norm(start=date(2026, 5, 1), end=date(2026, 5, 31), plan=plan)
    assert (april.norm_work_days, may.norm_work_days) == (1, 0)


# --------------------------------------------------------------------------- #
# 6. ARALIQ ƏRZİNDƏ İŞ REJİMİ DƏYİŞİR
# --------------------------------------------------------------------------- #


def test_a_work_mode_change_inside_the_range_is_followed_day_by_day() -> None:
    """İlk üç gün səhər (9 s → 8), sonrakı iki gün qısa növbə (6 s)."""
    plan = [
        *_work_days(date(2026, 4, 1), 3, MORNING),
        *_work_days(date(2026, 4, 4), 2, SHORT),
    ]
    norm = _norm(start=date(2026, 4, 1), end=date(2026, 4, 5), plan=plan)
    assert norm.norm_work_days == 5
    assert norm.norm_work_hours == Decimal("36.00")  # 3×8 + 2×6
    assert norm.scheduled_hours == Decimal("39.00")  # 3×9 + 2×6
    assert norm.capped_days == 3


def test_switching_from_a_day_shift_to_a_night_shift_mid_range() -> None:
    plan = [
        *_work_days(date(2026, 4, 1), 2, EVENING),
        *_work_days(date(2026, 4, 3), 2, NIGHT),
    ]
    norm = _norm(start=date(2026, 4, 1), end=date(2026, 4, 4), plan=plan)
    assert norm.norm_work_hours == Decimal("32.00")  # 2×min(9,8) + 2×8
    assert norm.average_norm_hours_per_day == Decimal("8.00")


# --------------------------------------------------------------------------- #
# 7. PRO-RATA — AVTOMATİK, ƏL DÜZƏLİŞİ YOX
# --------------------------------------------------------------------------- #


def test_hiring_in_the_middle_of_the_range_prorates_automatically() -> None:
    """16 apreldə işə düşən işçi aprelin yarısına görə hesablanır."""
    plan = _work_days(date(2026, 4, 1), 30)
    norm = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 30),
        plan=plan,
        employment=EmploymentWindow(started_on=date(2026, 4, 16)),
    )
    assert norm.covered_days == 15
    assert norm.range_days == 30
    assert norm.pro_rata_ratio == Decimal("0.5000")
    assert norm.is_prorated
    assert norm.norm_work_days == 15


def test_leaving_in_the_middle_of_the_range_prorates_automatically() -> None:
    plan = _work_days(date(2026, 4, 1), 30)
    norm = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 30),
        plan=plan,
        employment=EmploymentWindow(ended_on=date(2026, 4, 10)),
    )
    assert norm.covered_days == 10
    assert norm.norm_work_days == 10
    assert norm.pro_rata_ratio == Decimal("0.3333")


def test_a_plan_row_before_the_hire_date_is_never_counted() -> None:
    """Plan cədvəli ilə kadr sənədi uyğunsuzdursa, kadr sənədi üstündür."""
    plan = _work_days(date(2026, 4, 1), 5)
    norm = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 5),
        plan=plan,
        employment=EmploymentWindow(started_on=date(2026, 4, 4)),
    )
    assert norm.norm_work_days == 2


def test_an_employee_without_employment_dates_is_not_prorated() -> None:
    """Boş `hire_date` «işləməyib» demək DEYİL — məlumat qüsuru maaş kəsməməlidir."""
    norm = _norm(
        start=date(2026, 4, 1), end=date(2026, 4, 30), plan=_work_days(date(2026, 4, 1), 22)
    )
    assert norm.pro_rata_ratio == Decimal("1.0000")
    assert not norm.is_prorated
    assert norm.norm_work_days == 22


def test_an_employee_whose_window_misses_the_range_entirely_has_a_zero_norm() -> None:
    norm = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 30),
        plan=_work_days(date(2026, 4, 1), 30),
        employment=EmploymentWindow(started_on=date(2026, 6, 1)),
    )
    assert norm.covered_days == 0
    assert norm.pro_rata_ratio == Decimal("0.0000")
    assert norm.norm_work_days == 0
    assert norm.norm_work_hours == Decimal("0.00")


def test_hiring_and_leaving_inside_the_same_range() -> None:
    norm = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 30),
        plan=_work_days(date(2026, 4, 1), 30),
        employment=EmploymentWindow(started_on=date(2026, 4, 10), ended_on=date(2026, 4, 19)),
    )
    assert norm.covered_days == 10
    assert norm.norm_work_days == 10


def test_an_employment_window_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(WorkNormError):
        EmploymentWindow(started_on=date(2026, 4, 10), ended_on=date(2026, 4, 1))


def test_a_work_norm_request_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(WorkNormError) as error:
        WorkNormRequest(start=date(2026, 4, 10), end=date(2026, 4, 1))
    assert "əvvəl" in error.value.user_message


# --------------------------------------------------------------------------- #
# 8. SIFIRA BÖLMƏ YOXDUR
# --------------------------------------------------------------------------- #


def test_an_employee_with_zero_work_days_does_not_divide_by_zero() -> None:
    norm = _norm(
        start=date(2026, 4, 1),
        end=date(2026, 4, 30),
        plan=[PlannedDay(day=date(2026, 4, 1), is_off_day=True, schedule=None)],
    )
    assert norm.norm_work_days == 0
    assert norm.average_norm_hours_per_day == Decimal("0.00")


def test_a_zero_length_range_guard_returns_zero_ratio() -> None:
    """`range_days <= 0` konstruksiyaya görə mümkün deyil — qoruyucu yenə var."""
    guard = WorkNorm(
        range_days=0,
        covered_days=0,
        norm_work_days=0,
        norm_work_hours=Decimal("0.00"),
        scheduled_hours=Decimal("0.00"),
        capped_days=0,
        unscheduled_plan_days=0,
        off_days=0,
    )
    assert guard.pro_rata_ratio == Decimal("0.00")


def test_a_single_day_range_is_fully_covered() -> None:
    norm = _norm(start=date(2026, 4, 7), end=date(2026, 4, 7), plan=_work_days(date(2026, 4, 7), 1))
    assert norm.range_days == 1
    assert norm.pro_rata_ratio == Decimal("1.0000")
    assert norm.norm_work_hours == Decimal("8.00")


# --------------------------------------------------------------------------- #
# 9. Aralıq üzrə davamiyyət sətirləri
# --------------------------------------------------------------------------- #


def test_range_rows_take_the_norm_from_the_plan_not_from_the_sql_counter() -> None:
    """SQL sayğacı pro-rata və iş rejimini bilmir — aralıq yolunda İSTİFADƏ OLUNMUR."""
    use_case = _use_case()
    rows = use_case.build_attendance_rows_for_range(
        tenant_id=TENANT,
        actor=_actor(),
        facts=[_attendance_fact()],
        plans=[
            EmployeePlanFacts(
                employee_id=EMPLOYEE,
                planned_days=tuple(_work_days(date(2026, 4, 1), 12, SHORT)),
                employment=EmploymentWindow(),
            )
        ],
        report_range=ReportRange(date(2026, 4, 1), date(2026, 4, 15)),
        now=datetime(2026, 5, 1, 10, tzinfo=UTC),
    )

    row = rows[0]
    assert row.norm_work_days == 12  # SQL "999" DEYİL
    assert row.off_days == 0  # SQL "999" DEYİL
    assert row.norm_work_hours == Decimal("72.00")
    # Davamiyyət tərəfi ƏKSİNƏ, yalnız SQL-dən gələ bilər.
    assert row.actual_worked_days == 12
    assert row.unauthorized_absences == 1


def test_range_rows_carry_the_pro_rata_ratio_for_a_mid_period_hire() -> None:
    use_case = _use_case()
    rows = use_case.build_attendance_rows_for_range(
        tenant_id=TENANT,
        actor=_actor(),
        facts=[_attendance_fact()],
        plans=[
            EmployeePlanFacts(
                employee_id=EMPLOYEE,
                planned_days=tuple(_work_days(date(2026, 4, 1), 30)),
                employment=EmploymentWindow(started_on=date(2026, 4, 16)),
            )
        ],
        report_range=ReportRange(date(2026, 4, 1), date(2026, 4, 30)),
        now=datetime(2026, 5, 1, 10, tzinfo=UTC),
    )
    assert rows[0].pro_rata_ratio == Decimal("0.5000")
    assert rows[0].is_partial_period
    assert rows[0].norm_work_days == 15


def test_an_employee_without_a_plan_still_gets_a_row() -> None:
    """Sətri gizlətmək «plan qurulmayıb» siqnalını udardı."""
    use_case = _use_case()
    rows = use_case.build_attendance_rows_for_range(
        tenant_id=TENANT,
        actor=_actor(),
        facts=[_attendance_fact()],
        plans=[],
        report_range=ReportRange(date(2026, 4, 1), date(2026, 4, 30)),
        now=datetime(2026, 5, 1, 10, tzinfo=UTC),
    )
    assert len(rows) == 1
    assert rows[0].norm_work_days == 0
    assert rows[0].norm_work_hours == Decimal("0.00")


def test_the_range_report_requires_the_export_flag() -> None:
    use_case = _use_case()
    with pytest.raises(ReportPermissionError):
        use_case.build_attendance_rows_for_range(
            tenant_id=TENANT,
            actor=_actor(can_export=False),
            facts=[],
            plans=[],
            report_range=ReportRange(date(2026, 4, 1), date(2026, 4, 30)),
            now=datetime(2026, 5, 1, 10, tzinfo=UTC),
        )


def test_norm_for_returns_the_same_numbers_as_the_row_builder() -> None:
    """Ekranın izah paneli rəqəmi İKİNCİ DƏFƏ hesablamamalıdır."""
    use_case = _use_case()
    plan = EmployeePlanFacts(
        employee_id=EMPLOYEE,
        planned_days=tuple(_work_days(date(2026, 4, 1), 10, LONG)),
        employment=EmploymentWindow(),
    )
    span = ReportRange(date(2026, 4, 1), date(2026, 4, 30))
    norm = use_case.norm_for(tenant_id=TENANT, plan=plan, report_range=span)
    rows = use_case.build_attendance_rows_for_range(
        tenant_id=TENANT,
        actor=_actor(),
        facts=[_attendance_fact()],
        plans=[plan],
        report_range=span,
        now=datetime(2026, 5, 1, 10, tzinfo=UTC),
    )
    assert norm.norm_work_hours == rows[0].norm_work_hours
    assert norm.capped_days == rows[0].capped_norm_days == 10


def test_attendance_row_rejects_impossible_values() -> None:
    base = {
        "employee_id": EMPLOYEE,
        "full_name": "X",
        "store_name": "Y",
        "position_name": "Z",
        "norm_work_days": 1,
        "actual_worked_days": 1,
        "off_days": 0,
        "unauthorized_absences": 0,
    }
    with pytest.raises(ReportPeriodError):
        AttendanceRow(**base, norm_work_hours=Decimal("-1.00"))  # type: ignore[arg-type]
    with pytest.raises(ReportPeriodError):
        AttendanceRow(**base, pro_rata_ratio=Decimal("1.5"))  # type: ignore[arg-type]
    with pytest.raises(ReportPeriodError):
        AttendanceRow(**base, capped_norm_days=-1)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 10. LOCK MEXANİZMİ — STRUKTUR QƏRAR D
# --------------------------------------------------------------------------- #


def test_fine_on_the_last_day_of_the_range_inside_the_open_window_is_excluded() -> None:
    """MƏRKƏZİ TEST: aralıq seçimi 72 saatlıq pəncərəni BAYPAS ETMİR.

    Ssenari: `[Xüsusi Aralıq]` 1–15 aprel seçilir və export 15 aprel axşamı
    çıxarılır. Aralığın SON GÜNÜ nəşr olunmuş cərimənin etiraz pəncərəsi hələ
    açıqdır — işçi ona etiraz edə bilər. Tarix süzgəci onu "aralığa düşür"
    deyə tutmağa cəhd etsəydi, uğurlu etirazdan sonra pul geri qaytarılmalı
    olardı. Ona görə cərimə export-dan XARİC edilir və növbəti dövrdə
    yenidən qiymətləndirilir.
    """
    now = datetime(2026, 4, 15, 20, 0, tzinfo=UTC)
    last_day_fine = _published_fine(published_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC))

    selection = _use_case().build_bonus_penalty(
        actor=_actor(), facts=_sales_facts(), fines=[last_day_fine], now=now
    )

    assert selection.included_fines == []
    assert selection.deferred_fine_count == 1
    row = selection.rows[0]
    assert row.confirmed_fine_count == 0
    assert row.total_fine_amount == Money(Decimal("0.00"))
    assert row.open_appeal_count == 1
    assert row.has_deferred_fines
    # Və pəncərə HƏLƏ AÇIQDIR — bu, iddianın öz-özünə doğru olmadığının sübutu.
    assert last_day_fine.is_appeal_window_open(now=now)


def test_the_same_fine_enters_the_next_range_once_the_window_closes() -> None:
    """Xaric edilən cərimə İTMİR — pəncərə bağlananda növbəti dövrə düşür."""
    fine = _published_fine(published_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC))
    use_case = _use_case()

    early = use_case.build_bonus_penalty(
        actor=_actor(),
        facts=_sales_facts(),
        fines=[fine],
        now=datetime(2026, 4, 15, 20, 0, tzinfo=UTC),
    )
    later = use_case.build_bonus_penalty(
        actor=_actor(),
        facts=_sales_facts(),
        fines=[fine],
        now=datetime(2026, 4, 20, 20, 0, tzinfo=UTC),
    )

    assert early.included_fines == []
    assert later.included_fines == [fine]


def test_a_narrow_range_cannot_pull_in_a_reversed_fine() -> None:
    """Ləğv olunmuş cərimə heç bir aralıqda tutulmur."""
    fine = _published_fine(published_at=datetime(2026, 4, 1, 9, 0, tzinfo=UTC))
    fine.reverse(
        decided_by=REVIEWER,
        decided_at=datetime(2026, 4, 2, 9, 0, tzinfo=UTC),
        reason="Etiraz qəbul olundu, kamera qeydi işçini təsdiqlədi",
    )
    selection = _use_case().build_bonus_penalty(
        actor=_actor(),
        facts=_sales_facts(),
        fines=[fine],
        now=datetime(2026, 4, 30, 20, 0, tzinfo=UTC),
    )
    assert selection.included_fines == []
    assert selection.rows[0].open_appeal_count == 0
    assert selection.already_exported_count == 0


def test_build_bonus_penalty_has_no_date_range_parameter() -> None:
    """QAPI: aralığı bu metoda ötürmək LOCK-u baypas edən yeganə yol olardı."""
    import inspect

    signature = inspect.signature(MonthlyReportUseCase.build_bonus_penalty)
    assert set(signature.parameters) == {"self", "actor", "facts", "fines", "now"}


# --------------------------------------------------------------------------- #
# 11. ÜST-ÜSTƏ DÜŞƏN İKİ EXPORT
# --------------------------------------------------------------------------- #


def test_overlapping_range_never_charges_the_same_fine_twice() -> None:
    """1–15 aprel export edilir, sonra 10–20 aprel — cərimə İKİNCİ DƏFƏ TUTULMUR."""
    use_case = _use_case()
    now = datetime(2026, 4, 25, 10, tzinfo=UTC)
    fine = _published_fine(published_at=datetime(2026, 4, 12, 9, 0, tzinfo=UTC), amount="30.00")

    first = ReportRange(date(2026, 4, 1), date(2026, 4, 15))
    first_selection = use_case.build_bonus_penalty(
        actor=_actor(), facts=_sales_facts(), fines=[fine], now=now
    )
    assert use_case.mark_exported(selection=first_selection, period=first, now=now) == 1
    assert fine.exported_period == "2026-04-01_2026-04-15"

    second_selection = use_case.build_bonus_penalty(
        actor=_actor(), facts=_sales_facts(), fines=[fine], now=now
    )
    assert second_selection.included_fines == []
    assert second_selection.rows[0].confirmed_fine_count == 0
    assert second_selection.rows[0].total_fine_amount == Money(Decimal("0.00"))
    # İkinci `mark_exported` heç nə işarələmir — dövr açarı DƏYİŞMİR.
    assert (
        use_case.mark_exported(
            selection=second_selection,
            period=ReportRange(date(2026, 4, 10), date(2026, 4, 20)),
            now=now,
        )
        == 0
    )
    assert fine.exported_period == "2026-04-01_2026-04-15"


def test_overlapping_range_reports_the_skipped_fines_instead_of_silence() -> None:
    """Atlama SÜKUTLA baş vermir: sayğac + dövr adı + hazır mesaj."""
    use_case = _use_case()
    now = datetime(2026, 4, 25, 10, tzinfo=UTC)
    already = _published_fine(published_at=datetime(2026, 4, 12, 9, 0, tzinfo=UTC), amount="30.00")
    fresh = _published_fine(published_at=datetime(2026, 4, 18, 9, 0, tzinfo=UTC), amount="12.00")

    first = use_case.build_bonus_penalty(
        actor=_actor(),
        facts=_sales_facts(),
        fines=[already],
        now=datetime(2026, 4, 16, 10, tzinfo=UTC),
    )
    use_case.mark_exported(
        selection=first,
        period=ReportRange(date(2026, 4, 1), date(2026, 4, 15)),
        now=datetime(2026, 4, 16, 10, tzinfo=UTC),
    )

    second = use_case.build_bonus_penalty(
        actor=_actor(), facts=_sales_facts(), fines=[already, fresh], now=now
    )

    assert second.already_exported_count == 1
    assert second.already_exported_periods == ["2026-04-01_2026-04-15"]
    assert second.rows[0].already_exported_count == 1
    assert second.rows[0].has_overlap_with_previous_export
    notice = second.overlap_notice_az()
    assert notice is not None
    assert "2026-04-01_2026-04-15" in notice
    assert "təkrar tutulmur" in notice
    # Yeni cərimə NORMAL tutulur — atlama yalnız kəsişən hissəyə aiddir.
    assert second.rows[0].confirmed_fine_count == 1
    assert second.rows[0].total_fine_amount == Money(Decimal("12.00"))


def test_no_overlap_means_no_notice() -> None:
    selection = _use_case().build_bonus_penalty(
        actor=_actor(),
        facts=_sales_facts(),
        fines=[_published_fine(published_at=datetime(2026, 4, 1, 9, tzinfo=UTC))],
        now=datetime(2026, 4, 25, 10, tzinfo=UTC),
    )
    assert selection.already_exported_count == 0
    assert selection.overlap_notice_az() is None
    assert not selection.rows[0].has_overlap_with_previous_export


def test_a_full_month_export_after_a_custom_range_keeps_both_period_keys() -> None:
    """İki dövr açarı yan-yana yaşayır və hansının nə olduğu itmir."""
    use_case = _use_case()
    now = datetime(2026, 5, 5, 10, tzinfo=UTC)
    in_range = _published_fine(published_at=datetime(2026, 4, 2, 9, tzinfo=UTC))
    later = _published_fine(published_at=datetime(2026, 4, 20, 9, tzinfo=UTC))

    first = use_case.build_bonus_penalty(
        actor=_actor(), facts=_sales_facts(), fines=[in_range], now=now
    )
    use_case.mark_exported(
        selection=first, period=ReportRange(date(2026, 4, 1), date(2026, 4, 10)), now=now
    )
    second = use_case.build_bonus_penalty(
        actor=_actor(), facts=_sales_facts(), fines=[in_range, later], now=now
    )
    use_case.mark_exported(selection=second, period=ReportPeriod(2026, 4), now=now)

    assert in_range.exported_period == "2026-04-01_2026-04-10"
    assert later.exported_period == "2026-04"
