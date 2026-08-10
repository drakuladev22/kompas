"""Kataloq və oyunlaşdırma value object-lərinin qərarları — Faza 5/6.

Bu testlər İMPLEMENTASİYANI deyil, SPESİFİKASİYANIN QAYDALARINI qoruyur:
soft delete niyə var, 6 aylıq dövr sərhədi harada keçir, deaktiv cərimə növü
ilə niyə yeni cərimə yazıla bilməz.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from src.domain.value_objects.catalogs import (
    MAX_LEAVE_DURATION_MINUTES,
    CatalogEntryInUseError,
    FineType,
    InvalidCatalogEntryError,
    LeaveType,
    WorkMode,
    active_only,
)
from src.domain.value_objects.gamification import (
    DEFAULT_RESET_NOTICE_DAYS,
    InsufficientPointsError,
    InvalidPointsError,
    PointsBalance,
    PointsEntryStatus,
    PointsPeriod,
    RedemptionStatus,
    RewardItem,
)
from src.domain.value_objects.identifiers import TenantId
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import TimeRange

TENANT = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Kataloq bazisi
# --------------------------------------------------------------------------- #


def test_name_is_normalised() -> None:
    """Ardıcıl boşluqlar birləşir — «Nahar  Fasiləsi» ilə «Nahar Fasiləsi» eynidir."""
    entry = LeaveType(name="  Nahar   Fasiləsi ", tenant_id=TENANT)
    assert entry.name == "Nahar Fasiləsi"


@pytest.mark.parametrize("bad", ["", " ", "A"])
def test_short_name_is_rejected(bad: str) -> None:
    with pytest.raises(InvalidCatalogEntryError):
        LeaveType(name=bad, tenant_id=TENANT)


def test_inactive_entry_requires_a_deactivation_moment() -> None:
    """«Nə vaxt çıxarıldı?» sualı auditdə cavabsız qala bilməz."""
    with pytest.raises(InvalidCatalogEntryError, match="MƏCBURİDİR"):
        FineType(name="Gecikmə", tenant_id=TENANT, is_active=False)


def test_active_entry_cannot_carry_a_deactivation_moment() -> None:
    """Ziddiyyətli vəziyyət yaradıla bilməz."""
    with pytest.raises(InvalidCatalogEntryError):
        FineType(
            name="Gecikmə",
            tenant_id=TENANT,
            is_active=True,
            deactivated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )


def test_active_only_filters_deactivated_entries() -> None:
    live = LeaveType(name="Nahar", tenant_id=TENANT)
    dead = LeaveType(
        name="Siqaret",
        tenant_id=TENANT,
        is_active=False,
        deactivated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert active_only([live, dead]) == [live]


# --------------------------------------------------------------------------- #
# İş Rejimi
# --------------------------------------------------------------------------- #


def test_work_mode_without_schedule_is_labelled_as_free_shift() -> None:
    """«Növbəli 2/2» sabit saatı olmayan rejimdir — bu, səhv deyil."""
    mode = WorkMode(name="Növbəli 2/2", tenant_id=TENANT)
    assert mode.schedule is None
    assert mode.scheduled_start_label() == "Sərbəst növbə"


def test_work_mode_shows_its_time_range() -> None:
    mode = WorkMode(
        name="Səhər",
        tenant_id=TENANT,
        schedule=TimeRange(time(8, 0), time(17, 0)),
    )
    assert mode.scheduled_start_label() == "08:00–17:00"


# --------------------------------------------------------------------------- #
# Cərimə Növü — ANTİ-FRAUD
# --------------------------------------------------------------------------- #


def test_fine_type_supplies_the_amount_operator_cannot_choose() -> None:
    """Bölmə 4: operator sərbəst məbləğ təyin edə bilmir."""
    fine_type = FineType(
        name="Formaya uyğun geyinməmək",
        tenant_id=TENANT,
        standard_amount=Money(Decimal("25.00")),
    )
    assert fine_type.amount_for_new_fine() == Money(Decimal("25.00"))


def test_deactivated_fine_type_blocks_new_fines() -> None:
    """Deaktivləşdirmə yalnız siyahıdan çıxarmaq DEYİL — yeni qeydi bloklayır.

    Əks halda köhnə ekran keşindən seçim edən operator qaydanı yan keçərdi.
    """
    fine_type = FineType(
        name="Köhnə növ",
        tenant_id=TENANT,
        standard_amount=Money(Decimal("10.00")),
        is_active=False,
        deactivated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    with pytest.raises(CatalogEntryInUseError):
        fine_type.amount_for_new_fine()


def test_negative_standard_amount_is_rejected() -> None:
    from src.domain.value_objects.money import InvalidMoneyError

    with pytest.raises(InvalidMoneyError):
        FineType(name="Səhv", tenant_id=TENANT, standard_amount=Money(Decimal("-5.00")))


# --------------------------------------------------------------------------- #
# İcazə Növü
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "Müddət təyin olunmayıb"),
        (45, "45 dəq"),
        (60, "1 saat"),
        (90, "1 saat 30 dəq"),
    ],
)
def test_leave_type_duration_label(minutes: int, expected: str) -> None:
    entry = LeaveType(name="Fasilə", tenant_id=TENANT, default_duration_minutes=minutes)
    assert entry.duration_label() == expected


def test_leave_duration_beyond_a_working_day_is_rejected() -> None:
    with pytest.raises(InvalidCatalogEntryError):
        LeaveType(
            name="Fasilə",
            tenant_id=TENANT,
            default_duration_minutes=MAX_LEAVE_DURATION_MINUTES + 1,
        )


# --------------------------------------------------------------------------- #
# 6 aylıq dövr — SƏRHƏD QAYDASI
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("day", "start", "end"),
    [
        (date(2026, 1, 1), date(2026, 1, 1), date(2026, 7, 1)),
        (date(2026, 6, 30), date(2026, 1, 1), date(2026, 7, 1)),
        (date(2026, 7, 1), date(2026, 7, 1), date(2027, 1, 1)),
        (date(2026, 12, 31), date(2026, 7, 1), date(2027, 1, 1)),
    ],
)
def test_period_boundaries_are_half_open(day: date, start: date, end: date) -> None:
    """30 iyun birinci dövrə, 1 iyul ikinciyə düşür — heç bir gün İKİ dövrdə deyil."""
    period = PointsPeriod.containing(day)
    assert (period.start, period.end) == (start, end)


def test_notice_is_due_exactly_14_days_before_reset() -> None:
    period = PointsPeriod.containing(date(2026, 8, 1))
    assert period.reset_on == date(2027, 1, 1)
    assert period.notice_on() == date(2026, 12, 18)
    assert period.is_notice_due(date(2026, 12, 18))


def test_notice_stays_due_after_a_missed_day() -> None:
    """Tətbiq bildiriş günündə söndürülübsə, xəbərdarlıq İTMİR."""
    period = PointsPeriod.containing(date(2026, 8, 1))
    assert period.is_notice_due(date(2026, 12, 25))


def test_notice_is_not_due_before_the_window() -> None:
    period = PointsPeriod.containing(date(2026, 8, 1))
    assert not period.is_notice_due(date(2026, 12, 17))


def test_notice_is_not_due_after_the_reset() -> None:
    """Sıfırlanma günü artıq YENİ dövrdür — köhnə dövr üçün bildiriş mənasızdır."""
    period = PointsPeriod.containing(date(2026, 8, 1))
    assert not period.is_notice_due(date(2027, 1, 1))


def test_period_contains_requires_timezone() -> None:
    from src.domain.value_objects.scheduling import NaiveDatetimeError

    period = PointsPeriod.containing(date(2026, 8, 1))
    with pytest.raises(NaiveDatetimeError):
        period.contains(datetime(2026, 8, 12, 9, 0))  # noqa: DTZ001 — qəsdən naive


def test_period_label_distinguishes_the_two_halves() -> None:
    assert PointsPeriod.containing(date(2026, 3, 1)).label_az() == "2026 I yarım"
    assert PointsPeriod.containing(date(2026, 9, 1)).label_az() == "2026 II yarım"


def test_next_period_follows_immediately() -> None:
    first = PointsPeriod.containing(date(2026, 3, 1))
    assert first.next_period().start == first.end


# --------------------------------------------------------------------------- #
# Balans və mükafat
# --------------------------------------------------------------------------- #


def test_available_points_exclude_held_ones() -> None:
    """Bloklanmış xal ikiqat xərclənməni bağlayır."""
    balance = PointsBalance(period=PointsPeriod.containing(date(2026, 8, 1)), earned=500, held=200)
    assert balance.available == 300


def test_held_cannot_exceed_earned() -> None:
    with pytest.raises(InvalidPointsError, match="ikiqat"):
        PointsBalance(period=PointsPeriod.containing(date(2026, 8, 1)), earned=100, held=150)


def test_days_until_reset_never_goes_negative() -> None:
    balance = PointsBalance(period=PointsPeriod.containing(date(2026, 8, 1)), earned=10)
    assert balance.days_until_reset(today=date(2027, 6, 1)) == 0


def test_free_reward_is_rejected() -> None:
    """Pulsuz mükafat xal sistemini mənasızlaşdırar."""
    with pytest.raises(InvalidPointsError):
        RewardItem(name="Pulsuz", cost_points=0)


def test_insufficient_points_raise_a_dedicated_error() -> None:
    reward = RewardItem(name="Kupon", cost_points=500)
    with pytest.raises(InsufficientPointsError):
        reward.require_affordable(499)


def test_inactive_reward_cannot_be_redeemed_even_with_enough_points() -> None:
    reward = RewardItem(name="Kupon", cost_points=100, is_active=False)
    with pytest.raises(InvalidPointsError):
        reward.require_affordable(1_000)


# --------------------------------------------------------------------------- #
# Statusların DB ilə uyğunluğu
# --------------------------------------------------------------------------- #


def test_reversed_entry_is_excluded_from_the_balance() -> None:
    assert not PointsEntryStatus.REVERSED.counts_toward_balance
    assert PointsEntryStatus.ACTIVE.counts_toward_balance
    assert PointsEntryStatus.CORRECTED.counts_toward_balance


def test_rejected_redemption_releases_the_points() -> None:
    assert not RedemptionStatus.REJECTED.holds_points
    for status in (
        RedemptionStatus.REQUESTED,
        RedemptionStatus.APPROVED,
        RedemptionStatus.FULFILLED,
    ):
        assert status.holds_points


def test_notice_days_default_matches_the_specification() -> None:
    """Bölmə 6: «reset öncəsi işçilərə 14 gün əvvəldən bildiriş göndərilir»."""
    assert DEFAULT_RESET_NOTICE_DAYS == 14
