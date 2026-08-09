"""Domen value object-lərinin testləri (Faza 2.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.domain.value_objects import (
    DUAL_CONTROL_APPROVAL_FLAG,
    AuthorizationError,
    EmailAddress,
    HardlockLevel,
    InvalidEmailError,
    InvalidMoneyError,
    InvalidPenaltyInputError,
    InvalidPinError,
    InvalidScheduleError,
    InvalidUsernameError,
    Money,
    NaiveDatetimeError,
    PermissionFlag,
    Pin,
    RolePriority,
    SystemRole,
    TimeRange,
    Username,
    assess_lateness,
    calculate_leave_penalty,
    require_aware,
)

pytestmark = pytest.mark.unit

BAKU = ZoneInfo("Asia/Baku")


# --------------------------------------------------------------------------- #
# Pin
# --------------------------------------------------------------------------- #


def test_valid_pin() -> None:
    pin = Pin.parse("4821")
    assert pin.value == "4821"
    assert pin.is_weak is False


@pytest.mark.parametrize("raw", ["123", "12345", "48a1", "", "  ", "١٢٣٤"])
def test_invalid_pin_format(raw: str) -> None:
    with pytest.raises(InvalidPinError):
        Pin.parse(raw)


@pytest.mark.parametrize("raw", ["0000", "1234", "4321", "2580", "1212"])
def test_weak_pin_rejected_when_setting(raw: str) -> None:
    with pytest.raises(InvalidPinError, match="sadə"):
        Pin.parse(raw)


def test_weak_pin_accepted_when_verifying() -> None:
    """Siyasət sərtləşdirilməzdən ƏVVƏL yaradılmış PIN-lə giriş bloklanmamalıdır."""
    pin = Pin.parse("1234", reject_weak=False)
    assert pin.is_weak is True


def test_pin_repr_is_masked() -> None:
    pin = Pin.parse("4821")
    assert "4821" not in repr(pin)
    assert "4821" not in str(pin)
    assert repr(pin) == "Pin(****)"


def test_pin_constant_time_comparison() -> None:
    pin = Pin.parse("4821")
    assert pin.equals("4821") is True
    assert pin.equals("4822") is False


def test_pin_strips_whitespace() -> None:
    assert Pin.parse("  4821  ").value == "4821"


# --------------------------------------------------------------------------- #
# EmailAddress
# --------------------------------------------------------------------------- #


def test_email_normalised() -> None:
    email = EmailAddress.parse("  Admin@Kompas.AZ ")
    assert email.value == "admin@kompas.az"
    assert email.domain == "kompas.az"
    assert email.local_part == "admin"


@pytest.mark.parametrize(
    "raw", ["", "yanlış", "@kompas.az", "admin@", "admin@kompas", "a b@kompas.az"]
)
def test_invalid_email(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        EmailAddress.parse(raw)


def test_email_length_limit() -> None:
    with pytest.raises(InvalidEmailError, match="uzun"):
        EmailAddress.parse("a" * 250 + "@kompas.az")


# --------------------------------------------------------------------------- #
# Username (SEC-016)
# --------------------------------------------------------------------------- #


def test_username_normalised() -> None:
    """DB-də CITEXT — VO da eyni normallaşdırmanı tətbiq etməlidir."""
    assert Username.parse("  HR.Admin  ").value == "hr.admin"


@pytest.mark.parametrize(
    "raw",
    [
        "rashad",
        "hr.admin",
        "store_manager_01",
        "a1b",  # minimum uzunluq
        "u" * 32,  # maksimum uzunluq
        "kamera-operator",
    ],
)
def test_valid_usernames(raw: str) -> None:
    assert Username.parse(raw).value == raw.lower()


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ab",  # çox qısa
        "u" * 33,  # çox uzun
        ".admin",  # nöqtə ilə başlayır
        "-admin",  # defis ilə başlayır
        "_admin",  # alt-xətt ilə başlayır
        "admin@kompas.az",  # e-poçt DEYİL
        "admin user",  # boşluq
        "şəbnəm",  # Azərbaycan hərfləri — kiosk klaviaturasında yazıla bilməz
        "админ",  # kiril
        "admin!",  # xüsusi simvol
    ],
)
def test_invalid_usernames(raw: str) -> None:
    with pytest.raises(InvalidUsernameError):
        Username.parse(raw)


def test_username_is_not_an_email() -> None:
    """SEC-016 reqressiya qoruyucusu: e-poçt formatı giriş adı kimi qəbul edilməməlidir."""
    with pytest.raises(InvalidUsernameError):
        Username.parse("admin@kompas.az")


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def test_money_quantises_to_two_places() -> None:
    assert Money.parse("10.005").amount == Decimal("10.01")  # ROUND_HALF_UP
    assert Money.parse("10.004").amount == Decimal("10.00")


def test_money_rejects_float() -> None:
    with pytest.raises(InvalidMoneyError, match="float"):
        Money.parse(10.5)  # type: ignore[arg-type]
    with pytest.raises(InvalidMoneyError, match="float"):
        Money.parse("10").multiply(2.0)  # type: ignore[arg-type]


def test_money_arithmetic() -> None:
    assert (Money.parse("10.50") + Money.parse("4.50")).amount == Decimal("15.00")
    assert (Money.parse("10.00") - Money.parse("2.50")).amount == Decimal("7.50")
    assert Money.parse("10.00").multiply(3).amount == Decimal("30.00")
    assert (-Money.parse("5.00")).amount == Decimal("-5.00")


def test_money_comparison_and_ordering() -> None:
    assert Money.parse("5.00") < Money.parse("10.00")
    assert Money.parse("10.00") == Money.parse("10.000")
    assert sorted([Money.parse("3"), Money.parse("1"), Money.parse("2")])[0] == Money.parse("1")


def test_money_accepts_comma_decimal_separator() -> None:
    """Azərbaycanda vergüllə yazılış geniş yayılıb."""
    assert Money.parse("12,50").amount == Decimal("12.50")


def test_money_non_negative_guard() -> None:
    Money.parse("0").require_non_negative()
    with pytest.raises(InvalidMoneyError, match="mənfi"):
        Money.parse("-1").require_non_negative(field="cərimə")


def test_money_exceeds_db_limit() -> None:
    with pytest.raises(InvalidMoneyError, match="limit"):
        Money.parse("100000000.00")


def test_money_formats_in_azn() -> None:
    assert Money.parse("12.5").format_az() == "12.50 AZN"


def test_money_zero() -> None:
    assert Money.zero().is_zero is True


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #


def test_role_priority_ordering() -> None:
    assert RolePriority.EXECUTIVE.outranks(RolePriority.ADMIN)
    assert RolePriority.ADMIN.outranks(RolePriority.STAFF)
    # Bərabər pillə üstünlük vermir — Strict Hierarchy Guard-ın əsası
    assert RolePriority.ADMIN.outranks(RolePriority.ADMIN) is False
    assert RolePriority.STAFF.outranks(RolePriority.EXECUTIVE) is False


def test_default_priorities_match_spec() -> None:
    assert SystemRole.ROOT.default_priority == RolePriority.EXECUTIVE
    assert SystemRole.CEO.default_priority == RolePriority.EXECUTIVE
    assert SystemRole.ADMIN.default_priority == RolePriority.ADMIN
    assert SystemRole.HR_ADMIN.default_priority == RolePriority.OPERATIONAL
    assert SystemRole.STORE_MANAGER.default_priority == RolePriority.OPERATIONAL
    assert SystemRole.CAMERA_OPERATOR.default_priority == RolePriority.OPERATIONAL
    assert SystemRole.SELLER.default_priority == RolePriority.STAFF


@pytest.mark.parametrize(
    ("level", "role", "allowed"),
    [
        (HardlockLevel.ROOT_ONLY, SystemRole.ROOT, True),
        (HardlockLevel.ROOT_ONLY, SystemRole.CEO, False),
        (HardlockLevel.ROOT_CEO, SystemRole.CEO, True),
        (HardlockLevel.ROOT_CEO, SystemRole.ADMIN, False),
        (HardlockLevel.DELEGABLE, SystemRole.ADMIN, True),
        (HardlockLevel.DELEGABLE, SystemRole.HR_ADMIN, False),
        (HardlockLevel.NONE, SystemRole.SELLER, True),
    ],
)
def test_hardlock_levels(level: HardlockLevel, role: SystemRole, allowed: bool) -> None:
    assert level.allows(role) is allowed


def _camera_flag(code: str) -> PermissionFlag:
    return PermissionFlag(
        code=code, category="KAMERA_CERIME", is_anti_fraud=True, is_camera_only=True
    )


@pytest.mark.parametrize(
    "code", ["can_verify_returns", "can_override_return_time", "can_issue_fines"]
)
def test_camera_flags_only_for_camera_roles(code: str) -> None:
    flag = _camera_flag(code)

    flag.assert_grantable_to(SystemRole.CAMERA_OPERATOR)  # istisna atmamalıdır
    flag.assert_grantable_to(SystemRole.HR_ADMIN, is_camera_type_role=True)

    for role in (SystemRole.STORE_MANAGER, SystemRole.SELLER):
        with pytest.raises(AuthorizationError, match="ANTI-FRAUD"):
            flag.assert_grantable_to(role)

    with pytest.raises(AuthorizationError, match="kamera-tipli"):
        flag.assert_grantable_to(SystemRole.HR_ADMIN)


def test_dual_control_approval_never_on_camera_role() -> None:
    """SEC-001: operator öz override-ını özü təsdiqləyə bilməz."""
    flag = PermissionFlag(
        code=DUAL_CONTROL_APPROVAL_FLAG, category="KAMERA_CERIME", is_anti_fraud=True
    )

    flag.assert_grantable_to(SystemRole.HR_ADMIN)  # təsdiqçi buradadır
    flag.assert_grantable_to(SystemRole.CEO)

    with pytest.raises(AuthorizationError, match="VƏZİFƏ AYRILIĞI"):
        flag.assert_grantable_to(SystemRole.CAMERA_OPERATOR)
    with pytest.raises(AuthorizationError, match="ANTI-FRAUD"):
        flag.assert_grantable_to(SystemRole.STORE_MANAGER)


def test_root_only_flag_not_for_ceo() -> None:
    flag = PermissionFlag(
        code="can_manage_permissions", category="ICAZE", hardlock=HardlockLevel.ROOT_ONLY
    )
    flag.assert_grantable_to(SystemRole.ROOT)
    with pytest.raises(AuthorizationError, match="HARDLOCK"):
        flag.assert_grantable_to(SystemRole.CEO)


def test_flag_code_must_be_prefixed() -> None:
    with pytest.raises(ValueError, match="can_"):
        PermissionFlag(code="manage_stuff", category="X")


def test_camera_only_requires_anti_fraud() -> None:
    with pytest.raises(ValueError, match="anti-fraud"):
        PermissionFlag(code="can_x", category="X", is_camera_only=True)


def test_is_grantable_to_does_not_raise() -> None:
    flag = _camera_flag("can_issue_fines")
    assert flag.is_grantable_to(SystemRole.SELLER) is False
    assert flag.is_grantable_to(SystemRole.CAMERA_OPERATOR) is True


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #


def test_time_range_duration() -> None:
    assert TimeRange(time(8, 0), time(17, 0)).duration == timedelta(hours=9)


def test_overnight_time_range() -> None:
    night = TimeRange(time(22, 0), time(6, 0))
    assert night.is_overnight is True
    assert night.duration == timedelta(hours=8)

    day = date(2026, 8, 8)
    assert night.end_on(day).date() == date(2026, 8, 9)
    assert night.start_on(day).date() == day


def test_time_range_rejects_equal_bounds() -> None:
    with pytest.raises(InvalidScheduleError):
        TimeRange(time(8, 0), time(8, 0))


def test_require_aware_rejects_naive() -> None:
    with pytest.raises(NaiveDatetimeError):
        require_aware(datetime(2026, 8, 8, 10, 0))  # noqa: DTZ001


def test_require_aware_accepts_tz() -> None:
    moment = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    assert require_aware(moment) is moment


def test_lateness_within_tolerance() -> None:
    scheduled = datetime(2026, 8, 8, 8, 0, tzinfo=BAKU)
    verified = scheduled + timedelta(minutes=10)

    result = assess_lateness(verified_at=verified, scheduled_start=scheduled, tolerance_minutes=15)

    assert result.is_late is False
    assert result.late_minutes == 0
    assert result.creates_fine is False  # gecikmə cərimə YARATMIR (bölmə 4)


def test_lateness_beyond_tolerance() -> None:
    scheduled = datetime(2026, 8, 8, 8, 0, tzinfo=BAKU)
    verified = scheduled + timedelta(minutes=40)

    result = assess_lateness(verified_at=verified, scheduled_start=scheduled, tolerance_minutes=15)

    assert result.is_late is True
    assert result.late_minutes == 25


def test_lateness_without_schedule() -> None:
    result = assess_lateness(
        verified_at=datetime(2026, 8, 8, 8, 0, tzinfo=BAKU), scheduled_start=None
    )
    assert result.is_late is False
    assert result.scheduled_start is None


def test_early_arrival_is_not_late() -> None:
    scheduled = datetime(2026, 8, 8, 8, 0, tzinfo=BAKU)
    result = assess_lateness(
        verified_at=scheduled - timedelta(minutes=20), scheduled_start=scheduled
    )
    assert result.is_late is False
    assert result.late_minutes == 0


# --------------------------------------------------------------------------- #
# Penalty (bölmə 4 PENALTY LOGIC)
# --------------------------------------------------------------------------- #


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 8, hour, minute, tzinfo=BAKU)


def test_penalty_within_allowance() -> None:
    """60 dəq. icazə, 45 dəq.-də qayıdış → gecikmə yoxdur."""
    result = calculate_leave_penalty(
        requested_time=_at(12, 0), actual_return_time=_at(12, 45), allowance_minutes=60
    )
    assert result.elapsed_minutes == 45
    assert result.delay_minutes == 0
    assert result.total_minutes == 60  # allowance + 2×0
    assert result.is_late is False


def test_penalty_doubles_the_overage() -> None:
    """60 dəq. icazə, 90 dəq. sonra → Delay=30, Total = 60 + 2×30 = 120."""
    result = calculate_leave_penalty(
        requested_time=_at(12, 0), actual_return_time=_at(13, 30), allowance_minutes=60
    )
    assert result.delay_minutes == 30
    assert result.total_minutes == 120
    assert result.is_late is True


def test_penalty_literal_spec_mode_without_allowance() -> None:
    """`allowance = 0` → hərfi spesifikasiya: Delay = keçən vaxt, Total = 2×Delay."""
    result = calculate_leave_penalty(requested_time=_at(12, 0), actual_return_time=_at(12, 30))
    assert result.delay_minutes == 30
    assert result.total_minutes == 60


def test_penalty_delay_never_negative() -> None:
    """Spesifikasiyanın açıq tələbi: `Delay mənfi ola bilməz`."""
    result = calculate_leave_penalty(
        requested_time=_at(12, 0), actual_return_time=_at(12, 5), allowance_minutes=60
    )
    assert result.delay_minutes == 0


def test_penalty_rejects_return_before_request() -> None:
    """Bölmə 4, validasiya 1 — sükutla 0-a yuvarlaqlaşdırmaq TƏHLÜKƏLİDİR."""
    with pytest.raises(InvalidPenaltyInputError, match="əvvəl"):
        calculate_leave_penalty(requested_time=_at(13, 0), actual_return_time=_at(12, 0))


def test_penalty_rounds_partial_minute_up() -> None:
    """30 saniyəlik gecikmə də 1 dəqiqə sayılır (DB CEIL ilə eyni)."""
    result = calculate_leave_penalty(
        requested_time=_at(12, 0),
        actual_return_time=_at(12, 0) + timedelta(seconds=30),
    )
    assert result.elapsed_minutes == 1


def test_penalty_rejects_naive_datetime() -> None:
    with pytest.raises(NaiveDatetimeError):
        calculate_leave_penalty(
            requested_time=datetime(2026, 8, 8, 12, 0),  # noqa: DTZ001
            actual_return_time=_at(13, 0),
        )


def test_penalty_rejects_negative_allowance() -> None:
    with pytest.raises(InvalidPenaltyInputError, match="mənfi"):
        calculate_leave_penalty(
            requested_time=_at(12, 0),
            actual_return_time=_at(13, 0),
            allowance_minutes=-5,
        )


def test_penalty_across_timezones_is_consistent() -> None:
    """UTC və Bakı vaxtı eyni anı göstərirsə nəticə eyni olmalıdır."""
    baku = datetime(2026, 8, 8, 12, 0, tzinfo=BAKU)
    same_moment_utc = baku.astimezone(UTC)

    result = calculate_leave_penalty(
        requested_time=same_moment_utc, actual_return_time=baku + timedelta(minutes=90)
    )
    assert result.elapsed_minutes == 90


def test_penalty_serialisation() -> None:
    result = calculate_leave_penalty(
        requested_time=_at(12, 0), actual_return_time=_at(13, 30), allowance_minutes=60
    )
    assert result.to_dict() == {
        "elapsed_minutes": 90,
        "allowance_minutes": 60,
        "delay_minutes": 30,
        "total_minutes": 120,
    }
