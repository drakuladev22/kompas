"""Autentifikasiya use case testləri (Faza 2.6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.application.use_cases.authentication import (
    RESET_PASSWORD_FLAG,
    RESET_PIN_FLAG,
    AccountLockedError,
    AdminLoginUseCase,
    AuthenticationError,
    CredentialResetUseCase,
    EmergencyAccessRecoveryUseCase,
    LoginStage,
    PinHandshakeUseCase,
)
from src.domain.entities import Employee, Position
from src.domain.value_objects import (
    EmailAddress,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.infrastructure.security.hashing import HashingService
from src.infrastructure.security.totp import TotpService
from tests.fixtures.fakes import (
    FakeClock,
    FakeSystemLimits,
    InMemoryEmployees,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
GOOD_PASSWORD = "Güclü-Şifrə-2026!"


def make_position(role: SystemRole) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )


def make_employee(
    role: SystemRole,
    *,
    email: str | None = None,
    has_pin: bool = False,
    totp: bool = False,
    must_change: bool = False,
    flags: list[str] | None = None,
) -> Employee:
    position = make_position(role)
    for code in flags or []:
        position.grant(PermissionFlag(code=code, category="HR"))

    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Test",
        last_name=role.value,
        store_id=STORE,
        email=EmailAddress.parse(email or f"{uuid.uuid4().hex[:8]}@kompas.az"),
        has_password=True,
        has_pin=has_pin,
        totp_enabled=totp,
        must_change_password=must_change,
    )
    return employee


@pytest.fixture
def hashing(monkeypatch: pytest.MonkeyPatch) -> HashingService:
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", "a" * 64)
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER_PREVIOUS", raising=False)
    return HashingService(time_cost=1, memory_cost=8, parallelism=1)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit()


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


# --------------------------------------------------------------------------- #
# Admin giriş
# --------------------------------------------------------------------------- #


def login_uc(
    employees: InMemoryEmployees,
    hashing: HashingService,
    encryption_service,
    clock: FakeClock,
    audit: RecordingAudit,
) -> AdminLoginUseCase:
    return AdminLoginUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        totp=TotpService(encryption_service, hashing),
        clock=clock,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )


def test_login_without_2fa_succeeds_with_warning(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.HR_ADMIN, email="hr@kompas.az")
    employees = InMemoryEmployees([employee])
    stored = hashing.hash_password(GOOD_PASSWORD)

    result = login_uc(employees, hashing, encryption_service, clock, audit).verify_password(
        tenant_id=TENANT,
        email=EmailAddress.parse("hr@kompas.az"),
        password=GOOD_PASSWORD,
        stored_hash=stored,
    )

    assert result.stage is LoginStage.AUTHENTICATED
    assert result.is_complete is True
    assert "ADMIN_LOGIN" in audit.actions()


def test_login_with_2fa_requires_second_step(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.CEO, email="ceo@kompas.az", totp=True)
    employees = InMemoryEmployees([employee])
    uc = login_uc(employees, hashing, encryption_service, clock, audit)
    stored = hashing.hash_password(GOOD_PASSWORD)

    first = uc.verify_password(
        tenant_id=TENANT,
        email=EmailAddress.parse("ceo@kompas.az"),
        password=GOOD_PASSWORD,
        stored_hash=stored,
    )
    assert first.stage is LoginStage.PASSWORD_OK_AWAITING_TOTP
    assert first.is_complete is False

    totp = TotpService(encryption_service, hashing)
    enrollment = totp.enroll(employee_id=str(employee.id), account_label="ceo@kompas.az")
    import pyotp

    code = pyotp.TOTP(enrollment.manual_entry_key).now()

    second = uc.verify_totp(
        employee=employee,
        code=code,
        encrypted_secret=enrollment.encrypted_secret,
        last_used_counter=None,
    )
    assert second.stage is LoginStage.AUTHENTICATED
    assert second.totp_counter is not None


def test_wrong_password_rejected(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.HR_ADMIN, email="hr@kompas.az")
    employees = InMemoryEmployees([employee])
    stored = hashing.hash_password(GOOD_PASSWORD)

    with pytest.raises(AuthenticationError):
        login_uc(employees, hashing, encryption_service, clock, audit).verify_password(
            tenant_id=TENANT,
            email=EmailAddress.parse("hr@kompas.az"),
            password="yanlış-şifrə",
            stored_hash=stored,
        )


def test_unknown_email_gives_same_error(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    """User enumeration qorunması: mesaj eynidir."""
    employees = InMemoryEmployees([])

    with pytest.raises(AuthenticationError) as exc_info:
        login_uc(employees, hashing, encryption_service, clock, audit).verify_password(
            tenant_id=TENANT,
            email=EmailAddress.parse("yoxdur@kompas.az"),
            password=GOOD_PASSWORD,
            stored_hash=None,
        )

    assert exc_info.value.user_message == "E-poçt və ya şifrə yanlışdır."


def test_must_change_password_stage(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.HR_ADMIN, email="hr@kompas.az", must_change=True, totp=True)
    employees = InMemoryEmployees([employee])
    stored = hashing.hash_password(GOOD_PASSWORD)

    result = login_uc(employees, hashing, encryption_service, clock, audit).verify_password(
        tenant_id=TENANT,
        email=EmailAddress.parse("hr@kompas.az"),
        password=GOOD_PASSWORD,
        stored_hash=stored,
    )

    assert result.stage is LoginStage.MUST_CHANGE_PASSWORD


def test_wrong_totp_rejected(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.CEO, email="ceo@kompas.az", totp=True)
    uc = login_uc(InMemoryEmployees([employee]), hashing, encryption_service, clock, audit)
    enrollment = TotpService(encryption_service, hashing).enroll(
        employee_id=str(employee.id), account_label="ceo@kompas.az"
    )

    with pytest.raises(AuthenticationError, match="2FA"):
        uc.verify_totp(
            employee=employee,
            code="000000",
            encrypted_secret=enrollment.encrypted_secret,
            last_used_counter=None,
        )


def test_backup_code_login(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.ROOT, email="root@kompas.az", totp=True)
    uc = login_uc(InMemoryEmployees([employee]), hashing, encryption_service, clock, audit)
    enrollment = TotpService(encryption_service, hashing).enroll(
        employee_id=str(employee.id), account_label="root@kompas.az"
    )

    result, index = uc.verify_backup_code(
        employee=employee,
        code=enrollment.backup_codes[2],
        stored_hashes=list(enrollment.backup_code_hashes),
    )

    assert result.stage is LoginStage.AUTHENTICATED
    assert index == 2


def test_unknown_backup_code_rejected(
    hashing: HashingService, encryption_service, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.ROOT, email="root@kompas.az", totp=True)
    uc = login_uc(InMemoryEmployees([employee]), hashing, encryption_service, clock, audit)
    enrollment = TotpService(encryption_service, hashing).enroll(
        employee_id=str(employee.id), account_label="root@kompas.az"
    )

    with pytest.raises(AuthenticationError, match="Ehtiyat"):
        uc.verify_backup_code(
            employee=employee,
            code="ZZZZZ-ZZZZZ",
            stored_hashes=list(enrollment.backup_code_hashes),
        )


# --------------------------------------------------------------------------- #
# Kiosk PIN
# --------------------------------------------------------------------------- #


def pin_uc(
    employees: InMemoryEmployees,
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
) -> PinHandshakeUseCase:
    return PinHandshakeUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        clock=clock,  # type: ignore[arg-type]
        limits=FakeSystemLimits(),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )


def make_seller(hashing: HashingService, pin: str = "4821") -> tuple[Employee, str]:
    position = make_position(SystemRole.SELLER)
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Satıcı",
        last_name="Test",
        store_id=STORE,
        has_pin=True,
    )
    return employee, hashing.hash_pin(pin, employee_id=str(employee.id))


def test_pin_handshake_success(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee, stored = make_seller(hashing)
    employees = InMemoryEmployees([employee])

    result = pin_uc(employees, hashing, clock, audit).authenticate(
        tenant_id=TENANT,
        store_id=STORE,
        pin="4821",
        pin_hashes={employee.id: (stored, 1)},
    )

    assert result.employee.id == employee.id
    assert result.needs_pepper_rehash is False


def test_pin_handshake_wrong_pin(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee, stored = make_seller(hashing)
    employees = InMemoryEmployees([employee])

    with pytest.raises(AuthenticationError, match="PIN"):
        pin_uc(employees, hashing, clock, audit).authenticate(
            tenant_id=TENANT,
            store_id=STORE,
            pin="9999",
            pin_hashes={employee.id: (stored, 1)},
        )


def test_camera_operator_cannot_use_kiosk_pin(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """Bölmə 2: Kamera_Nəzarətçisi sadə PIN-dən istisna edilib."""
    operator = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=make_position(SystemRole.CAMERA_OPERATOR),
        first_name="Rizvan",
        last_name="Operator",
        store_id=STORE,
        email=EmailAddress.parse("rizvan@kompas.az"),
        has_password=True,
        has_pin=True,
    )
    stored = hashing.hash_pin("4821", employee_id=str(operator.id))

    with pytest.raises(AuthenticationError):
        pin_uc(InMemoryEmployees([operator]), hashing, clock, audit).authenticate(
            tenant_id=TENANT,
            store_id=STORE,
            pin="4821",
            pin_hashes={operator.id: (stored, 1)},
        )


def test_locked_account_rejects_correct_pin(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee, stored = make_seller(hashing)
    for _ in range(5):
        employee.register_failed_pin_attempt(now=NOW)
    employees = InMemoryEmployees([employee])

    with pytest.raises(AccountLockedError):
        pin_uc(employees, hashing, clock, audit).authenticate(
            tenant_id=TENANT,
            store_id=STORE,
            pin="4821",
            pin_hashes={employee.id: (stored, 1)},
        )


def test_failure_registration_locks_after_five(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee, _ = make_seller(hashing)
    uc = pin_uc(InMemoryEmployees([employee]), hashing, clock, audit)

    for expected_remaining in (4, 3, 2, 1):
        locked, remaining = uc.register_failure(tenant_id=TENANT, employee=employee)
        assert locked is False
        assert remaining == expected_remaining

    locked, remaining = uc.register_failure(tenant_id=TENANT, employee=employee)
    assert locked is True
    assert remaining == 0
    assert "PIN_LOCKOUT" in audit.actions()


def test_successful_pin_resets_lockout_counter(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee, stored = make_seller(hashing)
    employee.register_failed_pin_attempt(now=NOW)
    employee.register_failed_pin_attempt(now=NOW)

    pin_uc(InMemoryEmployees([employee]), hashing, clock, audit).authenticate(
        tenant_id=TENANT,
        store_id=STORE,
        pin="4821",
        pin_hashes={employee.id: (stored, 1)},
    )

    assert employee.pin_security.failed_attempts == 0


def test_pin_lazy_pepper_migration_flag(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-005: köhnə pepper versiyası ilə giriş işləyir və rehash tələb olunur."""
    employee, stored = make_seller(hashing)

    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", "b" * 64)
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER_PREVIOUS", "a" * 64)
    rotated = HashingService(time_cost=1, memory_cost=8, parallelism=1)

    result = pin_uc(InMemoryEmployees([employee]), rotated, clock, audit).authenticate(
        tenant_id=TENANT,
        store_id=STORE,
        pin="4821",
        pin_hashes={employee.id: (stored, 1)},
    )

    assert result.employee.id == employee.id
    assert result.needs_pepper_rehash is True


# --------------------------------------------------------------------------- #
# Admin-tərəfindən sıfırlama
# --------------------------------------------------------------------------- #


def reset_uc(
    employees: InMemoryEmployees,
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> CredentialResetUseCase:
    return CredentialResetUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        clock=clock,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
    )


def test_password_reset_by_admin(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    actor = make_employee(SystemRole.ROOT, flags=[RESET_PASSWORD_FLAG])
    subject = make_employee(SystemRole.HR_ADMIN)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    credential = uc.reset_password(actor=actor, subject=subject)

    assert subject.must_change_password is True
    assert hashing.verify_password(credential.hashed, credential.plaintext) is True
    assert "PASSWORD_RESET" in audit.actions()
    assert len(notifier.messages) == 1


def test_reset_requires_flag(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    actor = make_employee(SystemRole.ADMIN)  # flag yoxdur
    subject = make_employee(SystemRole.SELLER, has_pin=True)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="səlahiyyəti"):
        uc.reset_password(actor=actor, subject=subject)


def test_cannot_reset_own_credentials(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    actor = make_employee(SystemRole.ROOT, flags=[RESET_PASSWORD_FLAG])
    uc = reset_uc(InMemoryEmployees([actor]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="öz"):
        uc.reset_password(actor=actor, subject=actor)


def test_lower_tier_cannot_reset_higher(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    actor = make_employee(SystemRole.HR_ADMIN, flags=[RESET_PASSWORD_FLAG])
    subject = make_employee(SystemRole.CEO)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="aşağı səlahiyyət"):
        uc.reset_password(actor=actor, subject=subject)


def test_equal_tier_can_reset(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """Bölmə 2: "daha yüksək VƏ YA BƏRABƏR səlahiyyətli başqa bir admin"."""
    actor = make_employee(SystemRole.HR_ADMIN, flags=[RESET_PASSWORD_FLAG])
    subject = make_employee(SystemRole.STORE_MANAGER)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    credential = uc.reset_password(actor=actor, subject=subject)
    assert credential.plaintext


def test_pin_reset_clears_lockout(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    actor = make_employee(SystemRole.HR_ADMIN, flags=[RESET_PIN_FLAG])
    subject, _ = make_seller(hashing)
    for _ in range(5):
        subject.register_failed_pin_attempt(now=NOW)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    credential = uc.reset_pin(actor=actor, subject=subject)

    assert subject.pin_security.failed_attempts == 0
    assert subject.pin_security.locked_until is None
    assert hashing.verify_pin(credential.hashed, credential.plaintext, employee_id=str(subject.id))
    assert "PIN_RESET" in audit.actions()


# --------------------------------------------------------------------------- #
# Emergency Access Recovery
# --------------------------------------------------------------------------- #


def recovery_uc(
    employees: InMemoryEmployees,
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> EmergencyAccessRecoveryUseCase:
    return EmergencyAccessRecoveryUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        clock=clock,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
    )


def test_recovery_blocked_when_admin_exists(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """ƏSAS QORUYUCU: bu, adi "arxa qapı" olmamalıdır."""
    target = make_employee(SystemRole.ROOT)
    uc = recovery_uc(InMemoryEmployees([target]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="aktiv admin"):
        uc.recover(
            tenant_id=TENANT,
            target=target,
            developer_reference="TICKET-1234",
            active_admin_count=1,
        )


def test_recovery_requires_identity_reference(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    target = make_employee(SystemRole.ROOT)
    uc = recovery_uc(InMemoryEmployees([target]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="istinad"):
        uc.recover(
            tenant_id=TENANT,
            target=target,
            developer_reference="x",
            active_admin_count=0,
        )


def test_recovery_only_for_root_or_ceo(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    target = make_employee(SystemRole.HR_ADMIN)
    uc = recovery_uc(InMemoryEmployees([target]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="Root/CEO"):
        uc.recover(
            tenant_id=TENANT,
            target=target,
            developer_reference="TICKET-1234",
            active_admin_count=0,
        )


def test_recovery_succeeds_and_is_audited(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    target = make_employee(SystemRole.ROOT)
    target.is_active = False
    uc = recovery_uc(InMemoryEmployees([target]), hashing, clock, audit, notifier)

    credential = uc.recover(
        tenant_id=TENANT,
        target=target,
        developer_reference="TICKET-1234",
        active_admin_count=0,
    )

    assert target.is_active is True
    assert target.must_change_password is True
    assert hashing.verify_password(credential.hashed, credential.plaintext) is True
    assert "EMERGENCY_ACCESS_RECOVERY" in audit.actions()
    assert notifier.messages[0]["is_critical"] is True
