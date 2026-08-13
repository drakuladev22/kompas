"""Norma üstü iş saatlarının izlənməsi (#15, kompasos11.md Faza 6).

SAHTƏLƏR BU FAYLDA YERLİDİR (`tests/fixtures/fakes.py`-a əlavə edilmir):
modul üç paralel iş axınının ortasında yazılıb və ortaq sahtə faylını
genişləndirmək başqa fazaların testləri ilə toqquşma riski yaradırdı. Sahtələr
kiçikdir və yalnız burada işlədilir — yerli saxlamaq oxucuya "bu testin nəyə
ehtiyacı var" sualını bir ekranda göstərir.

TESTİN ƏSAS SUALLARI:
    * saat hesablaması (gecə növbəsi, gec gəliş, icazə, erkən gəliş);
    * gündəlik VƏ həftəlik normanın bir sətirdə necə birləşməsi;
    * ROOT parametrlərinin (hardcode ədəd YOX) faktiki oxunması;
    * mövcud tabel axınının POZULMAMASI (təsdiq hələ də işləyir).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.daily_attendance import DailyAttendanceSheetUseCase
from src.application.use_cases.overtime_tracking import (
    OVERTIME_NOTIFY_CATEGORY,
    OvertimeDayReport,
    OvertimePermissionError,
    OvertimeTrackingUseCase,
    iso_week_bounds,
)
from src.domain.entities.attendance_sheet import AttendanceFact
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.overtime import (
    OvertimeEntry,
    OvertimeSource,
    WorkedSpan,
)
from src.domain.value_objects.scheduling import NaiveDatetimeError, TimeRange

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
OTHER_WORKER = EmployeeId(uuid.uuid4())

#: 2026-08-10 = Bazar ertəsi (ISO həftəsinin BİRİNCİ günü) — həftəlik
#: hesablamaların sərhəd testləri bu tarixdən sayılır.
MONDAY = date(2026, 8, 10)
SUNDAY_BEFORE = date(2026, 8, 9)
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)

#: Mağaza zonası UTC seçilib ki, testdəki `datetime` dəyərləri gözlə oxunsun:
#: məqsəd zona çevirməsini yox, SAAT HESABLAMASINI yoxlamaqdır (zona
#: çevirməsinin öz testi `test_behavior_baseline.py`-dadır).
TZ = "UTC"

DAY_SHIFT = TimeRange(start=time(9, 0), end=time(17, 0))  # 8 saat
LONG_SHIFT = TimeRange(start=time(8, 0), end=time(20, 0))  # 12 saat
NIGHT_SHIFT = TimeRange(start=time(22, 0), end=time(6, 0))  # gecə, 8 saat
SEVEN_HOUR_SHIFT = TimeRange(start=time(9, 0), end=time(16, 0))  # 7 saat

FILL = PermissionFlag(code="can_fill_daily_attendance", category="NOVBE")
VIEW_REPORTS = PermissionFlag(code="can_view_employee_reports", category="HR")


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


class FakeClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class FakeLimits:
    """`system_limits` — `DEFAULT_LIMITS` + testdə override."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {key.value: value for key, value in DEFAULT_LIMITS.items()}

    def set(self, key: SystemLimitKey, value: str) -> None:
        self._values[key.value] = value

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        try:
            return int(self._values.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def notify(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    def categories(self) -> list[str]:
        return [str(message["category"]) for message in self.messages]


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(entry["action"]) for entry in self.entries]


class InMemoryOvertimeLog:
    """`overtime_log` — UPSERT davranışı (işçi + gün = BİR sətir)."""

    def __init__(self) -> None:
        self.items: dict[tuple[EmployeeId, date], OvertimeEntry] = {}
        self.write_count = 0

    def save(self, entry: OvertimeEntry) -> None:
        self.write_count += 1
        key = (entry.employee_id, entry.work_date)
        existing = self.items.get(key)
        # Real repo-nun `ON CONFLICT ... WHERE` şərtinin güzgüsü: avtomatik
        # hesablama əl ilə yazılmış sətri üstündən yazmır.
        if (
            existing is not None
            and existing.source is OvertimeSource.MANUAL_HR
            and entry.source is not OvertimeSource.MANUAL_HR
        ):
            return
        self.items[key] = entry

    def list_for_period(
        self, tenant_id: TenantId, *, start: date, end: date
    ) -> list[OvertimeEntry]:
        return [entry for entry in self.items.values() if start <= entry.work_date <= end]

    def list_for_employee_period(
        self, tenant_id: TenantId, employee_id: EmployeeId, *, start: date, end: date
    ) -> list[OvertimeEntry]:
        return [
            entry
            for entry in self.items.values()
            if entry.employee_id == employee_id and start <= entry.work_date <= end
        ]


class FakeWorkedHours:
    """Günə görə iş pəncərələri — SQL provayderinin yaddaş qarşılığı."""

    def __init__(self) -> None:
        self.by_day: dict[date, list[WorkedSpan]] = {}

    def add(self, span: WorkedSpan) -> None:
        self.by_day.setdefault(span.work_date, []).append(span)

    def spans_for(self, store_id: StoreId, work_date: date) -> list[WorkedSpan]:
        return list(self.by_day.get(work_date, []))


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
    def __init__(self, facts: list[AttendanceFact] | None = None) -> None:
        self.facts = facts or []

    def facts_for(self, store_id: StoreId, work_date: date) -> list[AttendanceFact]:
        return list(self.facts)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def span(
    *,
    employee_id: EmployeeId = WORKER,
    work_date: date = MONDAY,
    scheduled: TimeRange | None = DAY_SHIFT,
    check_in_hour: int | None = 9,
    check_in_minute: int = 0,
    check_in_day: date | None = None,
    leave_minutes: int = 0,
) -> WorkedSpan:
    checked_in_at = (
        datetime.combine(
            check_in_day or work_date, time(check_in_hour, check_in_minute), tzinfo=UTC
        )
        if check_in_hour is not None
        else None
    )
    return WorkedSpan(
        employee_id=employee_id,
        work_date=work_date,
        scheduled=scheduled,
        checked_in_at=checked_in_at,
        leave_minutes=leave_minutes,
        store_timezone=TZ,
    )


class Ctx:
    """Aşım izləyicisinin tam dəsti."""

    def __init__(self) -> None:
        self.clock = FakeClock(NOW)
        self.log = InMemoryOvertimeLog()
        self.hours = FakeWorkedHours()
        self.limits = FakeLimits()
        self.notifier = RecordingNotifier()

    def use_case(self) -> OvertimeTrackingUseCase:
        return OvertimeTrackingUseCase(
            overtime_log=self.log,  # type: ignore[arg-type]
            worked_hours=self.hours,  # type: ignore[arg-type]
            limits=self.limits,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
        )

    def record(self, work_date: date = MONDAY) -> OvertimeDayReport:
        return self.use_case().record_for_day(tenant_id=TENANT, store_id=STORE, work_date=work_date)

    def entry(self, work_date: date = MONDAY, employee_id: EmployeeId = WORKER) -> OvertimeEntry:
        return self.log.items[(employee_id, work_date)]


def make_employee(role: SystemRole, *, flags: list[PermissionFlag]) -> Employee:
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
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


# --------------------------------------------------------------------------- #
# 1. Saat hesablaması (`WorkedSpan`)
# --------------------------------------------------------------------------- #


def test_full_shift_is_counted_as_its_own_length() -> None:
    assert span().worked_hours == Decimal("8.00")


def test_late_arrival_shortens_the_day() -> None:
    """Qismən gün: 09:00 əvəzinə 11:30 → 5.5 saat."""
    assert span(check_in_hour=11, check_in_minute=30).worked_hours == Decimal("5.50")


def test_early_arrival_does_not_create_extra_hours() -> None:
    """Erkən gəliş TAPŞIRILMIŞ iş deyil (modul başlığı) — gün yenə 8 saatdır."""
    assert span(check_in_hour=7).worked_hours == Decimal("8.00")


def test_overnight_shift_crosses_midnight_correctly() -> None:
    """22:00–06:00 səkkiz saatdır, mənfi deyil (`TimeRange.is_overnight`)."""
    night = span(scheduled=NIGHT_SHIFT, check_in_hour=22)
    assert night.worked_hours == Decimal("8.00")


def test_late_arrival_on_an_overnight_shift() -> None:
    night = span(scheduled=NIGHT_SHIFT, check_in_hour=22, check_in_minute=30)
    assert night.worked_hours == Decimal("7.50")


def test_leave_minutes_are_subtracted() -> None:
    """3 saatlıq icazə "işlənmiş saat" sayılmır."""
    assert span(leave_minutes=180).worked_hours == Decimal("5.00")


def test_leave_longer_than_the_shift_never_goes_negative() -> None:
    assert span(leave_minutes=1000).worked_hours == Decimal("0.00")


def test_check_in_after_the_shift_ends_is_zero_hours() -> None:
    """Operator növbədən sonra təsdiqləyibsə mənfi saat yaranmır."""
    assert span(check_in_hour=18).worked_hours == Decimal("0.00")


def test_a_day_without_a_shift_assignment_is_not_measurable() -> None:
    """Planlanmamış iş — uzunluğu NAMƏLUM, uydurulmur (modul başlığı)."""
    assert not span(scheduled=None).is_measurable


def test_a_day_without_a_verified_check_in_is_not_measurable() -> None:
    assert not span(check_in_hour=None).is_measurable


def test_naive_check_in_is_rejected() -> None:
    """CLAUDE.md §4: bütün `datetime` tz-aware olmalıdır."""
    with pytest.raises(NaiveDatetimeError):
        WorkedSpan(
            employee_id=WORKER,
            work_date=MONDAY,
            scheduled=DAY_SHIFT,
            checked_in_at=datetime(2026, 8, 10, 9, 0),  # noqa: DTZ001 — testin məqsədi budur
        )


def test_negative_leave_minutes_are_rejected() -> None:
    with pytest.raises(DomainRuleError):
        WorkedSpan(
            employee_id=WORKER,
            work_date=MONDAY,
            scheduled=DAY_SHIFT,
            checked_in_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            leave_minutes=-1,
        )


# --------------------------------------------------------------------------- #
# 2. Gündəlik norma
# --------------------------------------------------------------------------- #


def test_exactly_at_norm_produces_a_row_without_overtime() -> None:
    """TAM norma = aşım YOXDUR, lakin sətir yenə yazılır (0.00 qanunidir)."""
    ctx = Ctx()
    ctx.hours.add(span())

    report = ctx.record()

    assert len(report.entries) == 1
    assert ctx.entry().hours_over_norm == Decimal("0.00")
    assert ctx.entry().actual_hours == Decimal("8.00")
    assert not report.exceeded_entries


def test_long_shift_creates_daily_overtime() -> None:
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))

    report = ctx.record()

    assert ctx.entry().hours_over_norm == Decimal("4.00")
    assert ctx.entry().norm_hours == Decimal("8.00")
    assert len(report.exceeded_entries) == 1


def test_zero_hour_day_is_logged_without_overtime() -> None:
    """Sıfır saat: sətir var, aşım yoxdur — "hesablandı, aşım qalmadı" faktı."""
    ctx = Ctx()
    ctx.hours.add(span(leave_minutes=1000))

    ctx.record()

    assert ctx.entry().actual_hours == Decimal("0.00")
    assert ctx.entry().hours_over_norm == Decimal("0.00")


def test_unmeasurable_days_are_skipped_entirely() -> None:
    ctx = Ctx()
    ctx.hours.add(span(scheduled=None))
    ctx.hours.add(span(employee_id=OTHER_WORKER, check_in_hour=None))

    report = ctx.record()

    assert report.entries == []
    assert ctx.log.items == {}


def test_the_daily_norm_comes_from_system_limits() -> None:
    """Norma KODDA deyil, `system_limits`-dədir — Root onu dəyişə bilir."""
    ctx = Ctx()
    ctx.hours.add(span())
    ctx.limits.set(SystemLimitKey.OVERTIME_DAILY_NORM_HOURS, "6.00")

    ctx.record()

    assert ctx.entry().norm_hours == Decimal("6.00")
    assert ctx.entry().hours_over_norm == Decimal("2.00")


def test_a_broken_limit_value_falls_back_instead_of_crashing() -> None:
    """Root-un yazı səhvi tabelin TƏSDİQİNİ çökdürməməlidir."""
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))
    ctx.limits.set(SystemLimitKey.OVERTIME_DAILY_NORM_HOURS, "səkkiz")

    ctx.record()

    assert ctx.entry().norm_hours == Decimal("8.00")
    assert ctx.entry().hours_over_norm == Decimal("4.00")


# --------------------------------------------------------------------------- #
# 3. Həftəlik norma
# --------------------------------------------------------------------------- #


def test_weekly_overtime_appears_without_any_daily_overtime() -> None:
    """6 × 7 saat = 42 > 40: gündəlik norma heç vaxt aşılmır, həftəlik aşılır."""
    ctx = Ctx()
    for offset in range(6):
        day = date.fromordinal(MONDAY.toordinal() + offset)
        ctx.hours.add(span(work_date=day, scheduled=SEVEN_HOUR_SHIFT))

    for offset in range(6):
        ctx.record(date.fromordinal(MONDAY.toordinal() + offset))

    first_five = [
        ctx.entry(date.fromordinal(MONDAY.toordinal() + offset)).hours_over_norm
        for offset in range(5)
    ]
    sixth = ctx.entry(date.fromordinal(MONDAY.toordinal() + 5)).hours_over_norm

    assert first_five == [Decimal("0.00")] * 5, "Gündəlik norma aşılmayıb"
    assert sixth == Decimal("2.00"), "42 − 40 = 2 saat həftəlik aşım"


def test_daily_and_weekly_overtime_are_not_double_counted() -> None:
    """5 × 10 saat: hər gün 2 saat gündəlik aşım, həftəlik cəm 10 saat.

    Cəm (maks əvəzinə) işlədilsəydi, sonuncu gün əlavə 10 saat da alardı və
    həftənin cəmi 20 çıxardı — yəni eyni saat iki dəfə sayılardı.
    """
    ctx = Ctx()
    for offset in range(5):
        day = date.fromordinal(MONDAY.toordinal() + offset)
        ctx.hours.add(span(work_date=day, scheduled=LONG_SHIFT, check_in_hour=10))
        ctx.record(day)

    per_day = [
        ctx.entry(date.fromordinal(MONDAY.toordinal() + offset)).hours_over_norm
        for offset in range(5)
    ]

    assert per_day == [Decimal("2.00")] * 5
    assert sum(per_day) == Decimal("10.00"), "50 − 40 = 10 saat həftəlik aşım"


def test_the_weekly_norm_comes_from_system_limits() -> None:
    ctx = Ctx()
    ctx.limits.set(SystemLimitKey.OVERTIME_WEEKLY_NORM_HOURS, "12.00")
    for offset in range(2):
        day = date.fromordinal(MONDAY.toordinal() + offset)
        ctx.hours.add(span(work_date=day))
        ctx.record(day)

    assert ctx.entry(MONDAY).hours_over_norm == Decimal("0.00")
    assert ctx.entry(date.fromordinal(MONDAY.toordinal() + 1)).hours_over_norm == Decimal("4.00")


def test_the_previous_week_does_not_leak_into_this_one() -> None:
    """Həftə sərhədi: bazar günü işlənən saat Bazar ertəsinin normasına düşmür."""
    ctx = Ctx()
    ctx.limits.set(SystemLimitKey.OVERTIME_WEEKLY_NORM_HOURS, "8.00")
    ctx.hours.add(span(work_date=SUNDAY_BEFORE))
    ctx.hours.add(span(work_date=MONDAY))

    ctx.record(SUNDAY_BEFORE)
    ctx.record(MONDAY)

    assert ctx.entry(SUNDAY_BEFORE).hours_over_norm == Decimal("0.00")
    assert ctx.entry(MONDAY).hours_over_norm == Decimal("0.00"), (
        "Bazar günü ÖZ həftəsinə aiddir — yeni həftə sıfırdan başlayır"
    )


def test_iso_week_bounds_start_on_monday() -> None:
    assert iso_week_bounds(MONDAY) == (MONDAY, date(2026, 8, 16))
    assert iso_week_bounds(SUNDAY_BEFORE) == (date(2026, 8, 3), SUNDAY_BEFORE)


def test_recalculating_the_same_day_is_idempotent() -> None:
    """Təkrar icra həftəlik payı İKİ dəfə yazmır (öz sətri kənarda qalır)."""
    ctx = Ctx()
    ctx.limits.set(SystemLimitKey.OVERTIME_WEEKLY_NORM_HOURS, "5.00")
    ctx.hours.add(span())

    ctx.record()
    first = ctx.entry().hours_over_norm
    ctx.record()

    assert first == Decimal("3.00")
    assert ctx.entry().hours_over_norm == first
    assert len(ctx.log.items) == 1


def test_each_employee_is_counted_separately() -> None:
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))
    ctx.hours.add(span(employee_id=OTHER_WORKER))

    report = ctx.record()

    assert len(report.entries) == 2
    assert ctx.entry(employee_id=OTHER_WORKER).hours_over_norm == Decimal("0.00")
    assert ctx.entry(employee_id=WORKER).hours_over_norm == Decimal("4.00")


# --------------------------------------------------------------------------- #
# 4. Bildiriş
# --------------------------------------------------------------------------- #


def test_overtime_notifies_hr_through_the_existing_notifier() -> None:
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))

    report = ctx.record()

    assert OVERTIME_NOTIFY_CATEGORY in ctx.notifier.categories()
    assert report.notified
    message = ctx.notifier.messages[0]
    assert message["is_critical"] is True, "E-poçt ehtiyat kanalı işə düşməlidir"
    assert message["recipient_id"] is None


def test_no_notification_when_nobody_exceeds_the_norm() -> None:
    ctx = Ctx()
    ctx.hours.add(span())

    report = ctx.record()

    assert ctx.notifier.messages == []
    assert not report.notified


def test_small_overtime_stays_below_the_notification_threshold() -> None:
    """Hədd `system_limits`-dədir: 30 dəqiqəlik aşım kanalı doldurmamalıdır."""
    ctx = Ctx()
    ctx.hours.add(span(scheduled=TimeRange(start=time(9, 0), end=time(17, 30)), check_in_hour=9))

    report = ctx.record()

    assert ctx.entry().hours_over_norm == Decimal("0.50")
    assert ctx.notifier.messages == []
    assert not report.notified


def test_lowering_the_threshold_makes_small_overtime_notifiable() -> None:
    ctx = Ctx()
    ctx.limits.set(SystemLimitKey.OVERTIME_NOTIFY_THRESHOLD_HOURS, "0.25")
    ctx.hours.add(span(scheduled=TimeRange(start=time(9, 0), end=time(17, 30)), check_in_hour=9))

    assert ctx.record().notified


def test_one_notification_covers_the_whole_store_day() -> None:
    """İşçi başına ayrıca mesaj kanalı yararsız edərdi (metod şərhi)."""
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))
    ctx.hours.add(span(employee_id=OTHER_WORKER, scheduled=LONG_SHIFT, check_in_hour=8))

    ctx.record()

    assert len(ctx.notifier.messages) == 1
    assert "2 işçidə" in str(ctx.notifier.messages[0]["body_az"])


# --------------------------------------------------------------------------- #
# 5. Jurnal sətri (`OvertimeEntry`) və oxu yolu
# --------------------------------------------------------------------------- #


def test_manual_entry_requires_an_author() -> None:
    """`chk_overtime_manual_author` güzgüsü."""
    with pytest.raises(DomainRuleError):
        OvertimeEntry(
            tenant_id=TENANT,
            employee_id=WORKER,
            work_date=MONDAY,
            norm_hours=Decimal("8.00"),
            actual_hours=Decimal("10.00"),
            hours_over_norm=Decimal("2.00"),
            source=OvertimeSource.MANUAL_HR,
        )


def test_negative_hours_are_rejected() -> None:
    with pytest.raises(DomainRuleError):
        OvertimeEntry(
            tenant_id=TENANT,
            employee_id=WORKER,
            work_date=MONDAY,
            norm_hours=Decimal("8.00"),
            actual_hours=Decimal("-1.00"),
            hours_over_norm=Decimal("0.00"),
        )


def test_hours_above_the_schema_ceiling_are_rejected() -> None:
    """`NUMERIC(5, 2)` tavanı — DB xətası əvəzinə domen xətası."""
    with pytest.raises(DomainRuleError):
        OvertimeEntry(
            tenant_id=TENANT,
            employee_id=WORKER,
            work_date=MONDAY,
            norm_hours=Decimal("8.00"),
            actual_hours=Decimal("1000.00"),
            hours_over_norm=Decimal("0.00"),
        )


def test_automatic_recalculation_does_not_overwrite_a_manual_row() -> None:
    """HR-ın əl ilə yazdığı iddia gecəlik hesablama ilə silinmir."""
    ctx = Ctx()
    ctx.log.save(
        OvertimeEntry(
            tenant_id=TENANT,
            employee_id=WORKER,
            work_date=MONDAY,
            norm_hours=Decimal("8.00"),
            actual_hours=Decimal("12.00"),
            hours_over_norm=Decimal("4.00"),
            source=OvertimeSource.MANUAL_HR,
            recorded_by=OTHER_WORKER,
        )
    )
    ctx.hours.add(span())

    ctx.record()

    assert ctx.entry().source is OvertimeSource.MANUAL_HR
    assert ctx.entry().hours_over_norm == Decimal("4.00")


def test_reading_the_log_requires_the_reports_flag() -> None:
    ctx = Ctx()
    seller = make_employee(SystemRole.SELLER, flags=[FILL])

    with pytest.raises(OvertimePermissionError, match="can_view_employee_reports"):
        ctx.use_case().overtime_for_period(tenant_id=TENANT, actor=seller, start=MONDAY, end=MONDAY)


def test_hr_reads_the_period_log() -> None:
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))
    ctx.record()
    hr = make_employee(SystemRole.HR_ADMIN, flags=[VIEW_REPORTS])

    rows = ctx.use_case().overtime_for_period(tenant_id=TENANT, actor=hr, start=MONDAY, end=MONDAY)

    assert [row.hours_over_norm for row in rows] == [Decimal("4.00")]


def test_a_reversed_period_is_normalised_instead_of_returning_nothing() -> None:
    """Ekran tarixləri tərs göndərsə boş siyahı "aşım yoxdur" kimi oxunardı."""
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))
    ctx.record()
    hr = make_employee(SystemRole.HR_ADMIN, flags=[VIEW_REPORTS])

    rows = ctx.use_case().overtime_for_period(
        tenant_id=TENANT, actor=hr, start=date(2026, 8, 16), end=MONDAY
    )

    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# 6. Mövcud tabel axını POZULMUR (əlavə, əvəzləmə deyil)
# --------------------------------------------------------------------------- #


def _sheet_use_case(ctx: Ctx, *, with_overtime: bool) -> tuple[DailyAttendanceSheetUseCase, Any]:
    sheets = InMemorySheets()
    audit = RecordingAudit()
    facts = FakeAttendanceFacts(
        [AttendanceFact(employee_id=WORKER, planned_off=False, has_verified_check_in=True)]
    )
    use_case = DailyAttendanceSheetUseCase(
        sheets=sheets,  # type: ignore[arg-type]
        facts=facts,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=ctx.clock,  # type: ignore[arg-type]
        notifier=ctx.notifier,  # type: ignore[arg-type]
        overtime=ctx.use_case() if with_overtime else None,
    )
    return use_case, audit


def test_confirming_the_sheet_writes_the_overtime_log() -> None:
    """#15 tabel təsdiqinin ÜZƏRİNƏ qoyulur — yazı anı məhz təsdiqdir."""
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))
    use_case, audit = _sheet_use_case(ctx, with_overtime=True)
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL])
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE, sheet_date=MONDAY)

    view = use_case.confirm(tenant_id=TENANT, actor=manager, store_id=STORE, sheet_date=MONDAY)

    assert view.sheet.is_confirmed
    assert "ATTENDANCE_SHEET_CONFIRMED" in audit.actions()
    assert ctx.entry().hours_over_norm == Decimal("4.00")


def test_nothing_is_written_before_confirmation() -> None:
    """Təsdiqdən əvvəlki rəqəm hələ mübahisəlidir (modul başlığı)."""
    ctx = Ctx()
    ctx.hours.add(span(scheduled=LONG_SHIFT, check_in_hour=8))
    use_case, _ = _sheet_use_case(ctx, with_overtime=True)
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL])

    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE, sheet_date=MONDAY)
    use_case.annotate_line(
        tenant_id=TENANT,
        actor=manager,
        store_id=STORE,
        sheet_date=MONDAY,
        employee_id=WORKER,
        note="PIN sistemi işləmirdi",
    )

    assert ctx.log.items == {}


def test_the_sheet_flow_still_works_without_the_overtime_module() -> None:
    """Asılılıq qeyri-məcburidir: köhnə çağırışlar beş arqumentlə işləyir."""
    ctx = Ctx()
    use_case, audit = _sheet_use_case(ctx, with_overtime=False)
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL])
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE, sheet_date=MONDAY)

    view = use_case.confirm(tenant_id=TENANT, actor=manager, store_id=STORE, sheet_date=MONDAY)

    assert view.sheet.is_confirmed
    assert "ATTENDANCE_SHEET_CONFIRMED" in audit.actions()
    assert ctx.log.items == {}
