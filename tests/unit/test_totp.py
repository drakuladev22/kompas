"""TOTP 2FA testləri (spesifikasiya bölmə 2, qərar SEC-004)."""

from __future__ import annotations

from datetime import UTC, datetime

import pyotp
import pytest

from src.infrastructure.security.encryption import EncryptionService
from src.infrastructure.security.hashing import HashingService
from src.infrastructure.security.totp import (
    TOTP_INTERVAL_SECONDS,
    TotpError,
    TotpService,
)

pytestmark = pytest.mark.unit

EMPLOYEE = "33333333-3333-3333-3333-333333333333"
OTHER = "44444444-4444-4444-4444-444444444444"
BASE_TIME = 1_800_000_000  # sabit Unix vaxtı — testlər determinstikdir


def _code_at(service: TotpService, enrollment, moment: int) -> str:
    """Servisin daxili hesablaması ilə EYNİ (tz-aware) üsulla kod yaradır."""
    return pyotp.TOTP(enrollment.manual_entry_key).at(datetime.fromtimestamp(moment, tz=UTC))


# --------------------------------------------------------------------------- #
# Qeydiyyat
# --------------------------------------------------------------------------- #


def test_enroll_returns_complete_package(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="admin@kompas.az")

    assert enrollment.encrypted_secret.startswith("v1.")
    assert enrollment.provisioning_uri.startswith("otpauth://totp/")
    assert "KompasOS" in enrollment.provisioning_uri
    assert len(enrollment.manual_entry_key) == 32
    assert len(enrollment.backup_codes) == 10
    assert len(enrollment.backup_code_hashes) == 10


def test_secret_is_never_stored_in_plaintext(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    assert enrollment.manual_entry_key not in enrollment.encrypted_secret


def test_secret_is_bound_to_employee(
    totp_service: TotpService, encryption_service: EncryptionService
) -> None:
    """Şifrəli sirri başqa işçinin sətrinə köçürmək mümkün olmamalıdır (AAD)."""
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    code = _code_at(totp_service, enrollment, BASE_TIME)

    with pytest.raises(TotpError):
        totp_service.verify(
            encrypted_secret=enrollment.encrypted_secret,
            code=code,
            employee_id=OTHER,  # başqa işçi → AAD uyğunsuzluğu
            at_time=BASE_TIME,
        )


def test_enroll_requires_employee_id(totp_service: TotpService) -> None:
    with pytest.raises(ValueError):
        totp_service.enroll(employee_id="", account_label="a@b.az")


# --------------------------------------------------------------------------- #
# Yoxlama
# --------------------------------------------------------------------------- #


def test_correct_code_is_accepted(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    code = _code_at(totp_service, enrollment, BASE_TIME)

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=code,
        employee_id=EMPLOYEE,
        at_time=BASE_TIME,
    )

    assert result.is_valid is True
    assert result.used_counter == BASE_TIME // TOTP_INTERVAL_SECONDS
    assert result.reason == "OK"


def test_wrong_code_rejected(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code="000000",
        employee_id=EMPLOYEE,
        at_time=BASE_TIME,
    )

    assert result.is_valid is False
    assert result.reason == "MISMATCH"


@pytest.mark.parametrize("bad", ["12345", "1234567", "abcdef", "", "12 34 56 78"])
def test_malformed_code_rejected(totp_service: TotpService, bad: str) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=bad,
        employee_id=EMPLOYEE,
        at_time=BASE_TIME,
    )

    assert result.is_valid is False
    assert result.reason == "INVALID_FORMAT"


def test_code_with_spaces_is_normalized(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    code = _code_at(totp_service, enrollment, BASE_TIME)
    spaced = f"{code[:3]} {code[3:]}"

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=spaced,
        employee_id=EMPLOYEE,
        at_time=BASE_TIME,
    )
    assert result.is_valid is True


def test_previous_window_accepted_for_clock_drift(totp_service: TotpService) -> None:
    """±1 addım (±30 s) drift tolerantlığı — mağaza PC saatları dəqiq deyil."""
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    earlier = BASE_TIME - TOTP_INTERVAL_SECONDS
    code = _code_at(totp_service, enrollment, earlier)

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=code,
        employee_id=EMPLOYEE,
        at_time=BASE_TIME,
    )
    assert result.is_valid is True
    assert result.used_counter == earlier // TOTP_INTERVAL_SECONDS


def test_too_old_code_rejected(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    too_old = BASE_TIME - 3 * TOTP_INTERVAL_SECONDS
    code = _code_at(totp_service, enrollment, too_old)

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=code,
        employee_id=EMPLOYEE,
        at_time=BASE_TIME,
    )
    assert result.is_valid is False


# --------------------------------------------------------------------------- #
# Replay qorunması (SEC-004) — əsas təhlükəsizlik zəmanəti
# --------------------------------------------------------------------------- #


def test_same_code_cannot_be_reused(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    code = _code_at(totp_service, enrollment, BASE_TIME)

    first = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=code,
        employee_id=EMPLOYEE,
        at_time=BASE_TIME,
    )
    assert first.is_valid is True

    # Eyni kod, eyni pəncərə — DB-dəki last_used_counter ilə bloklanır
    second = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=code,
        employee_id=EMPLOYEE,
        last_used_counter=first.used_counter,
        at_time=BASE_TIME,
    )
    assert second.is_valid is False
    assert second.reason == "REPLAY_DETECTED"


def test_older_window_code_blocked_after_newer_use(totp_service: TotpService) -> None:
    """Sonrakı pəncərə istifadə olunubsa, əvvəlki pəncərənin kodu keçməməlidir."""
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    current_counter = BASE_TIME // TOTP_INTERVAL_SECONDS
    old_code = _code_at(totp_service, enrollment, BASE_TIME - TOTP_INTERVAL_SECONDS)

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=old_code,
        employee_id=EMPLOYEE,
        last_used_counter=current_counter,
        at_time=BASE_TIME,
    )
    assert result.is_valid is False
    assert result.reason == "REPLAY_DETECTED"


def test_next_window_code_accepted_after_previous_use(
    totp_service: TotpService,
) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    first_counter = BASE_TIME // TOTP_INTERVAL_SECONDS
    later = BASE_TIME + TOTP_INTERVAL_SECONDS
    code = _code_at(totp_service, enrollment, later)

    result = totp_service.verify(
        encrypted_secret=enrollment.encrypted_secret,
        code=code,
        employee_id=EMPLOYEE,
        last_used_counter=first_counter,
        at_time=later,
    )
    assert result.is_valid is True
    assert result.used_counter == later // TOTP_INTERVAL_SECONDS


# --------------------------------------------------------------------------- #
# Ehtiyat kodları
# --------------------------------------------------------------------------- #


def test_backup_code_verifies_once(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    hashes = list(enrollment.backup_code_hashes)

    index = totp_service.verify_backup_code(
        code=enrollment.backup_codes[3], stored_hashes=hashes, employee_id=EMPLOYEE
    )
    assert index == 3

    # Çağıran tərəf kodu SİLİR — sonra eyni kod işləməməlidir
    hashes.pop(index)
    assert (
        totp_service.verify_backup_code(
            code=enrollment.backup_codes[3], stored_hashes=hashes, employee_id=EMPLOYEE
        )
        is None
    )


def test_backup_codes_are_hashed_not_plaintext(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    for code, stored in zip(enrollment.backup_codes, enrollment.backup_code_hashes, strict=True):
        assert code not in stored
        assert stored.startswith("$argon2id$")


def test_backup_code_is_case_insensitive(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    index = totp_service.verify_backup_code(
        code=enrollment.backup_codes[0].lower(),
        stored_hashes=list(enrollment.backup_code_hashes),
        employee_id=EMPLOYEE,
    )
    assert index == 0


def test_backup_code_bound_to_employee(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    assert (
        totp_service.verify_backup_code(
            code=enrollment.backup_codes[0],
            stored_hashes=list(enrollment.backup_code_hashes),
            employee_id=OTHER,
        )
        is None
    )


def test_unknown_backup_code_rejected(totp_service: TotpService) -> None:
    enrollment = totp_service.enroll(employee_id=EMPLOYEE, account_label="a@b.az")
    assert (
        totp_service.verify_backup_code(
            code="ZZZZZ-ZZZZZ",
            stored_hashes=list(enrollment.backup_code_hashes),
            employee_id=EMPLOYEE,
        )
        is None
    )


def test_corrupted_secret_raises(
    encryption_service: EncryptionService, hashing_service: HashingService
) -> None:
    service = TotpService(encryption_service, hashing_service)
    with pytest.raises(TotpError):
        service.verify(
            encrypted_secret="v1.deadbeef.qırıq",
            code="123456",
            employee_id=EMPLOYEE,
            at_time=BASE_TIME,
        )
