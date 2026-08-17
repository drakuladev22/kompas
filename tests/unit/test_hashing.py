"""Argon2id hash-ləmə, pepper və PIN lockout testləri (spesifikasiya bölmə 2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.security.hashing import (
    HashingService,
    PasswordPolicy,
    PepperProvider,
    PepperSet,
    PinPolicy,
    WeakSecretError,
    evaluate_pin_attempt,
    generate_pepper,
)
from src.shared.exceptions import ConfigurationError

pytestmark = pytest.mark.unit

EMP_A = "11111111-1111-1111-1111-111111111111"
EMP_B = "22222222-2222-2222-2222-222222222222"


def _now() -> datetime:
    return datetime(2026, 8, 8, 10, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Şifrə
# --------------------------------------------------------------------------- #


def test_password_roundtrip(hashing_service: HashingService) -> None:
    stored = hashing_service.hash_password("Güclü-Şifrə-2026!")

    assert stored != "Güclü-Şifrə-2026!"
    assert stored.startswith("$argon2id$")
    assert hashing_service.verify_password(stored, "Güclü-Şifrə-2026!") is True
    assert hashing_service.verify_password(stored, "yanlış-şifrə") is False


def test_same_password_gives_different_hash(hashing_service: HashingService) -> None:
    """Duz (salt) təsadüfi olmalıdır — eyni şifrə fərqli hash verir."""
    first = hashing_service.hash_password("Eyni-Şifrə-2026!")
    second = hashing_service.hash_password("Eyni-Şifrə-2026!")
    assert first != second


@pytest.mark.parametrize(
    ("password", "expected_fragment"),
    [
        # Yeddi simvol — həddin bir addım altı. Hədd 8-dir (miqrasiya 066);
        # əvvəl 12 idi və İlk Quraşdırma Sihirbazını dayandırırdı.
        ("qısa1!A", "8 simvol"),
        ("hamısıkiçik123!", "böyük hərf"),
        ("HAMISIBOYUK123!", "kiçik hərf"),
        ("RəqəmsizŞifrəAB!", "rəqəm"),
        ("SimvolsuzSifre123", "xüsusi simvol"),
    ],
)
def test_weak_passwords_rejected(
    hashing_service: HashingService, password: str, expected_fragment: str
) -> None:
    with pytest.raises(WeakSecretError) as exc_info:
        hashing_service.hash_password(password)
    assert expected_fragment in str(exc_info.value)


def test_password_validation_can_be_skipped(hashing_service: HashingService) -> None:
    """Miqrasiya ssenarisi — mövcud zəif şifrələri yenidən hash-ləmək üçün."""
    stored = hashing_service.hash_password("zəif", validate=False)
    assert hashing_service.verify_password(stored, "zəif") is True


def test_verify_against_missing_hash_is_false(hashing_service: HashingService) -> None:
    """Hesab yoxdursa `False`, lakin istisna YOX (enumeration qorunması)."""
    assert hashing_service.verify_password(None, "hər hansı") is False


# --------------------------------------------------------------------------- #
# PIN
# --------------------------------------------------------------------------- #


def test_pin_roundtrip(hashing_service: HashingService) -> None:
    stored = hashing_service.hash_pin("4821", employee_id=EMP_A)

    assert hashing_service.verify_pin(stored, "4821", employee_id=EMP_A) is True
    assert hashing_service.verify_pin(stored, "4822", employee_id=EMP_A) is False


def test_pin_hash_is_bound_to_employee(hashing_service: HashingService) -> None:
    """Eyni PIN başqa işçinin kontekstində keçməməlidir."""
    stored = hashing_service.hash_pin("4821", employee_id=EMP_A)
    assert hashing_service.verify_pin(stored, "4821", employee_id=EMP_B) is False


def test_same_pin_different_employees_differ(hashing_service: HashingService) -> None:
    """DB-də "kimlərdə eyni PIN var" analizi mümkün olmamalıdır."""
    a = hashing_service.hash_pin("4821", employee_id=EMP_A)
    b = hashing_service.hash_pin("4821", employee_id=EMP_B)
    assert a != b


@pytest.mark.parametrize("pin", ["0000", "1111", "1234", "4321", "2580", "1212"])
def test_weak_pins_rejected(hashing_service: HashingService, pin: str) -> None:
    with pytest.raises(WeakSecretError):
        hashing_service.validate_pin_format(pin)


@pytest.mark.parametrize("pin", ["123", "12345", "48a1", "", "  48"])
def test_invalid_pin_format_rejected(hashing_service: HashingService, pin: str) -> None:
    with pytest.raises(WeakSecretError):
        hashing_service.validate_pin_format(pin)


def test_valid_pin_accepted(hashing_service: HashingService) -> None:
    hashing_service.validate_pin_format("4821")  # istisna atmamalıdır


def test_pin_requires_employee_id(hashing_service: HashingService) -> None:
    with pytest.raises(ValueError, match="employee_id"):
        hashing_service.hash_pin("4821", employee_id="")


# --------------------------------------------------------------------------- #
# Pepper (SEC-005)
# --------------------------------------------------------------------------- #


def test_pepper_changes_hash_input(pepper: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pepper olmadan və pepper ilə yaradılan hash-lər bir-birini qəbul etməməlidir."""
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER", raising=False)
    without = HashingService(time_cost=1, memory_cost=8, parallelism=1)
    stored_without = without.hash_pin("4821", employee_id=EMP_A)

    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", pepper)
    with_pepper = HashingService(time_cost=1, memory_cost=8, parallelism=1)

    assert with_pepper.has_pepper is True
    assert without.has_pepper is False
    # Pepper-siz yaradılmış hash pepper-li servisdə AÇILMAMALIDIR
    assert with_pepper.verify_pin(stored_without, "4821", employee_id=EMP_A) is False


def test_different_peppers_are_incompatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", generate_pepper())
    first = HashingService(time_cost=1, memory_cost=8, parallelism=1)
    stored = first.hash_pin("4821", employee_id=EMP_A)

    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", generate_pepper())
    second = HashingService(time_cost=1, memory_cost=8, parallelism=1)

    assert second.verify_pin(stored, "4821", employee_id=EMP_A) is False


def test_service_works_without_pepper(
    hashing_service_no_pepper: HashingService,
) -> None:
    """Deqradasiya rejimi: pepper yoxdursa sistem işləyir, lakin xəbərdarlıq verir."""
    assert hashing_service_no_pepper.has_pepper is False
    stored = hashing_service_no_pepper.hash_pin("4821", employee_id=EMP_A)
    assert hashing_service_no_pepper.verify_pin(stored, "4821", employee_id=EMP_A)


def test_required_pepper_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER", raising=False)
    with pytest.raises(ConfigurationError):
        PepperProvider(required=True).load()


def test_short_pepper_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", "qısa")
    with pytest.raises(ConfigurationError, match="qısadır"):
        PepperProvider().load()


def test_generate_pepper_is_long_enough() -> None:
    assert len(generate_pepper()) == 64


# --------------------------------------------------------------------------- #
# Pepper LAZY MIGRATION (SEC-005) — kütləvi sıfırlama olmadan rotasiya
# --------------------------------------------------------------------------- #


def _fast_service() -> HashingService:
    return HashingService(time_cost=1, memory_cost=8, parallelism=1)


def test_pepper_version_starts_at_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", generate_pepper())
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER_PREVIOUS", raising=False)
    assert _fast_service().current_pepper_version == 1


def test_pepper_version_increments_per_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Versiya AVTOMATİK hesablanır: len(previous) + 1 — əl ilə idarəetmə yoxdur."""
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", generate_pepper())
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER_PREVIOUS", f"{generate_pepper()},{generate_pepper()}")
    assert _fast_service().current_pepper_version == 3


def test_old_hash_still_verifies_after_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ƏSAS SSENARİ: rotasiyadan sonra köhnə PIN işləməyə davam etməlidir."""
    old_pepper = generate_pepper()
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", old_pepper)
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER_PREVIOUS", raising=False)

    before = _fast_service()
    stored = before.hash_pin("4821", employee_id=EMP_A)
    stored_version = before.current_pepper_version
    assert stored_version == 1

    # --- ROTASİYA: köhnə pepper PREVIOUS-a köçür, yenisi cari olur ---
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", generate_pepper())
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER_PREVIOUS", old_pepper)
    after = _fast_service()

    assert after.current_pepper_version == 2
    # Köhnə hash öz versiyası ilə hələ də açılır — kütləvi sıfırlama YOXDUR
    assert (
        after.verify_pin(stored, "4821", employee_id=EMP_A, pepper_version=stored_version) is True
    )
    # Rehash lazımdır
    assert after.needs_pepper_rehash(stored_version) is True


def test_rehashed_value_uses_new_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uğurlu girişdən sonra hash yenidən yazılır və köhnə pepper-ə ehtiyac qalmır."""
    old_pepper = generate_pepper()
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", old_pepper)
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER_PREVIOUS", raising=False)
    stored = _fast_service().hash_pin("4821", employee_id=EMP_A)

    new_pepper = generate_pepper()
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", new_pepper)
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER_PREVIOUS", old_pepper)
    rotating = _fast_service()

    assert rotating.verify_pin(stored, "4821", employee_id=EMP_A, pepper_version=1)
    rehashed = rotating.hash_pin("4821", employee_id=EMP_A)  # lazy migration addımı
    assert rotating.needs_pepper_rehash(rotating.current_pepper_version) is False

    # Köhnə pepper artıq konfiqurasiyadan çıxarıla bilər
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", new_pepper)
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER_PREVIOUS", raising=False)
    only_new = _fast_service()
    assert only_new.verify_pin(rehashed, "4821", employee_id=EMP_A) is True


def test_unknown_pepper_version_fails_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naməlum versiya istisna atmır — sadəcə `False` (enumeration qorunması)."""
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", generate_pepper())
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER_PREVIOUS", raising=False)
    service = _fast_service()
    stored = service.hash_pin("4821", employee_id=EMP_A)

    assert service.verify_pin(stored, "4821", employee_id=EMP_A, pepper_version=99) is False


def test_password_rotation_also_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    old_pepper = generate_pepper()
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", old_pepper)
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER_PREVIOUS", raising=False)
    stored = _fast_service().hash_password("Güclü-Şifrə-2026!")

    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", generate_pepper())
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER_PREVIOUS", old_pepper)
    after = _fast_service()

    assert after.verify_password(stored, "Güclü-Şifrə-2026!", pepper_version=1) is True
    assert after.verify_password(stored, "Güclü-Şifrə-2026!") is False  # cari pepper


def test_pepper_set_repr_is_masked() -> None:
    peppers = PepperSet(current=generate_pepper().encode(), previous=(generate_pepper().encode(),))
    text = repr(peppers)
    assert "***" in text
    assert peppers.current is not None
    assert peppers.current.decode() not in text
    assert peppers.current_version == 2


def test_no_pepper_keeps_version_one(
    hashing_service_no_pepper: HashingService,
) -> None:
    assert hashing_service_no_pepper.current_pepper_version == 1
    assert hashing_service_no_pepper.needs_pepper_rehash(1) is False


# --------------------------------------------------------------------------- #
# Müvəqqəti sirlər
# --------------------------------------------------------------------------- #


def test_temporary_password_passes_policy(hashing_service: HashingService) -> None:
    for _ in range(5):
        temp = hashing_service.generate_temporary_password()
        hashing_service.password_policy.validate(temp)  # istisna atmamalıdır
        assert len(temp) == 16


def test_temporary_pin_is_not_weak(hashing_service: HashingService) -> None:
    for _ in range(20):
        temp = hashing_service.generate_temporary_pin()
        hashing_service.validate_pin_format(temp)  # istisna atmamalıdır


# --------------------------------------------------------------------------- #
# Lockout siyasəti (bölmə 2: 5 səhv → 15 dəqiqə)
# --------------------------------------------------------------------------- #


def test_successful_attempt_resets_counter() -> None:
    decision = evaluate_pin_attempt(
        success=True,
        current_failed_attempts=3,
        current_locked_until=None,
        policy=PinPolicy(),
        now=_now(),
    )
    assert decision.accepted is True
    assert decision.failed_attempts == 0
    assert decision.is_locked is False


def test_failed_attempts_accumulate() -> None:
    policy = PinPolicy()
    decision = evaluate_pin_attempt(
        success=False,
        current_failed_attempts=2,
        current_locked_until=None,
        policy=policy,
        now=_now(),
    )
    assert decision.failed_attempts == 3
    assert decision.remaining_attempts == 2
    assert decision.is_locked is False
    assert decision.reason == "WRONG_PIN"


def test_fifth_failure_locks_for_fifteen_minutes() -> None:
    policy = PinPolicy()
    decision = evaluate_pin_attempt(
        success=False,
        current_failed_attempts=4,
        current_locked_until=None,
        policy=policy,
        now=_now(),
    )
    assert decision.is_locked is True
    assert decision.failed_attempts == 5
    assert decision.locked_until == _now() + timedelta(minutes=15)
    assert decision.reason == "LOCKED_AFTER_FAILED_ATTEMPTS"


def test_locked_account_rejects_even_correct_pin() -> None:
    """Bloklanmış hesabda DOĞRU PIN də qəbul edilməməlidir."""
    decision = evaluate_pin_attempt(
        success=True,
        current_failed_attempts=5,
        current_locked_until=_now() + timedelta(minutes=10),
        policy=PinPolicy(),
        now=_now(),
    )
    assert decision.accepted is False
    assert decision.reason == "ACCOUNT_LOCKED"


def test_lockout_expires() -> None:
    decision = evaluate_pin_attempt(
        success=True,
        current_failed_attempts=5,
        current_locked_until=_now() - timedelta(minutes=1),
        policy=PinPolicy(),
        now=_now(),
    )
    assert decision.accepted is True
    assert decision.failed_attempts == 0


def test_policy_is_configurable_from_system_limits() -> None:
    """`system_limits` dəyərləri ilə (bölmə 3, ROOT Control Center)."""
    policy = PinPolicy(max_attempts=3, lockout_minutes=30)
    decision = evaluate_pin_attempt(
        success=False,
        current_failed_attempts=2,
        current_locked_until=None,
        policy=policy,
        now=_now(),
    )
    assert decision.is_locked is True
    assert decision.locked_until == _now() + timedelta(minutes=30)


def test_needs_rehash_on_stronger_params(hashing_service: HashingService) -> None:
    weak = HashingService(time_cost=1, memory_cost=8, parallelism=1)
    stored = weak.hash_password("Güclü-Şifrə-2026!")

    stronger = HashingService(time_cost=3, memory_cost=1024, parallelism=1)
    assert stronger.needs_rehash(stored) is True
    assert hashing_service.needs_rehash(hashing_service.hash_password("Güclü-Şifrə-2026!")) is False


def test_password_policy_rejects_padding_whitespace() -> None:
    with pytest.raises(WeakSecretError, match="boşluq"):
        PasswordPolicy().validate(" Güclü-Şifrə-2026! ")
