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
    TenantContact,
)
from src.domain.entities import Employee, Position
from src.domain.entities.base import DomainRuleError
from src.domain.value_objects import (
    EmailAddress,
    PermissionFlag,
    SystemRole,
    Username,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.infrastructure.security.hashing import HashingService
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

#: Tenant-səviyyəli şirkət əlaqəsi (`license_tenants.company_contact_*`).
COMPANY_CONTACT = TenantContact(email="rehber@kompas.az", phone="+994 50 123 45 67")


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
    username: str | None = None,
    notification_email: str | None = None,
    has_pin: bool = False,
    must_change: bool = False,
    flags: list[str] | None = None,
) -> Employee:
    position = make_position(role)
    for code in flags or []:
        position.grant(PermissionFlag(code=code, category="HR"))

    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Test",
        last_name=role.value,
        store_id=STORE,
        username=Username.parse(username or f"u{uuid.uuid4().hex[:8]}"),
        notification_email=(EmailAddress.parse(notification_email) if notification_email else None),
        has_password=True,
        has_pin=has_pin,
        must_change_password=must_change,
    )


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
    clock: FakeClock,
    audit: RecordingAudit,
) -> AdminLoginUseCase:
    return AdminLoginUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        clock=clock,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )


def test_login_succeeds_in_one_step(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """SEC-016: uğurlu username+şifrə DƏRHAL sessiya verir — 2FA addımı yoxdur."""
    employee = make_employee(SystemRole.HR_ADMIN, username="hr.admin")
    employees = InMemoryEmployees([employee])
    stored = hashing.hash_password(GOOD_PASSWORD)

    result = login_uc(employees, hashing, clock, audit).login(
        tenant_id=TENANT,
        username=Username.parse("hr.admin"),
        password=GOOD_PASSWORD,
        stored_hash=stored,
    )

    assert result.stage is LoginStage.AUTHENTICATED
    assert result.is_complete is True
    assert "ADMIN_LOGIN" in audit.actions()


def test_login_is_case_insensitive(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """DB-də CITEXT — "HR.Admin" ilə "hr.admin" EYNİ hesabdır."""
    employee = make_employee(SystemRole.HR_ADMIN, username="hr.admin")
    employees = InMemoryEmployees([employee])
    stored = hashing.hash_password(GOOD_PASSWORD)

    result = login_uc(employees, hashing, clock, audit).login(
        tenant_id=TENANT,
        username=Username.parse("  HR.Admin  "),
        password=GOOD_PASSWORD,
        stored_hash=stored,
    )

    assert result.stage is LoginStage.AUTHENTICATED


def test_wrong_password_rejected(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.HR_ADMIN, username="hr.admin")
    employees = InMemoryEmployees([employee])
    stored = hashing.hash_password(GOOD_PASSWORD)

    with pytest.raises(AuthenticationError):
        login_uc(employees, hashing, clock, audit).login(
            tenant_id=TENANT,
            username=Username.parse("hr.admin"),
            password="yanlış-şifrə",
            stored_hash=stored,
        )

    assert "ADMIN_LOGIN" not in audit.actions()


def test_unknown_username_gives_same_error(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """User enumeration qorunması: mövcud olmayan hesab da eyni mesaj verir."""
    employees = InMemoryEmployees([])

    with pytest.raises(AuthenticationError) as exc_info:
        login_uc(employees, hashing, clock, audit).login(
            tenant_id=TENANT,
            username=Username.parse("yoxdur"),
            password=GOOD_PASSWORD,
            stored_hash=None,
        )

    assert exc_info.value.user_message == "İstifadəçi adı və ya şifrə yanlışdır."


def test_unknown_username_and_bad_password_messages_are_identical(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """İki fərqli səbəb — İSTİFADƏÇİYƏ eyni cavab."""
    employee = make_employee(SystemRole.HR_ADMIN, username="hr.admin")
    stored = hashing.hash_password(GOOD_PASSWORD)
    uc = login_uc(InMemoryEmployees([employee]), hashing, clock, audit)

    with pytest.raises(AuthenticationError) as unknown:
        uc.login(
            tenant_id=TENANT,
            username=Username.parse("yoxdur"),
            password=GOOD_PASSWORD,
            stored_hash=None,
        )
    with pytest.raises(AuthenticationError) as bad_password:
        uc.login(
            tenant_id=TENANT,
            username=Username.parse("hr.admin"),
            password="səhv",
            stored_hash=stored,
        )

    assert unknown.value.user_message == bad_password.value.user_message


def test_deactivated_account_cannot_log_in(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.CEO, username="ceo")
    employee.is_active = False
    stored = hashing.hash_password(GOOD_PASSWORD)

    with pytest.raises(DomainRuleError, match=r"[Dd]eaktiv"):
        login_uc(InMemoryEmployees([employee]), hashing, clock, audit).login(
            tenant_id=TENANT,
            username=Username.parse("ceo"),
            password=GOOD_PASSWORD,
            stored_hash=stored,
        )


def test_must_change_password_stage(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    employee = make_employee(SystemRole.HR_ADMIN, username="hr.admin", must_change=True)
    employees = InMemoryEmployees([employee])
    stored = hashing.hash_password(GOOD_PASSWORD)

    result = login_uc(employees, hashing, clock, audit).login(
        tenant_id=TENANT,
        username=Username.parse("hr.admin"),
        password=GOOD_PASSWORD,
        stored_hash=stored,
    )

    assert result.stage is LoginStage.MUST_CHANGE_PASSWORD
    assert result.is_complete is False
    # Şifrə dəyişdirilməyib — bu, tam giriş sayılmır və audit-ə yazılmır.
    assert "ADMIN_LOGIN" not in audit.actions()


def test_login_lazy_pepper_migration_flag(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-005: köhnə pepper ilə yaradılmış şifrə hash-i hələ də işləyir."""
    employee = make_employee(SystemRole.CEO, username="ceo")
    stored = hashing.hash_password(GOOD_PASSWORD)

    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", "b" * 64)
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER_PREVIOUS", "a" * 64)
    rotated = HashingService(time_cost=1, memory_cost=8, parallelism=1)

    result = login_uc(InMemoryEmployees([employee]), rotated, clock, audit).login(
        tenant_id=TENANT,
        username=Username.parse("ceo"),
        password=GOOD_PASSWORD,
        stored_hash=stored,
        pepper_version=1,
    )

    assert result.stage is LoginStage.AUTHENTICATED
    assert result.needs_pepper_rehash is True


def test_login_use_case_has_no_two_factor_surface() -> None:
    """SEC-016 reqressiya qoruyucusu: 2FA metodları geri qayıtmamalıdır."""
    for removed in ("verify_totp", "verify_backup_code", "verify_password"):
        assert not hasattr(AdminLoginUseCase, removed), removed


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
        username=Username.parse("rizvan.operator"),
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


def test_ceo_cannot_reset_the_root_accounts_password(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """`Root`/`CEO` prioritet ayrılığının BİRBAŞA nəticəsi (reqressiya qapısı).

    Köhnə (səhv) modeldə `Root` və `CEO` hər ikisi prioritet 0-da idi. Bölmə
    2 isə sıfırlamaya "daha yüksək VƏ YA BƏRABƏR" pilləyə icazə verir — yəni
    `0 > 0` yanlış olduğu üçün CEO `Root` hesabının ŞİFRƏSİNİ sıfırlaya
    bilirdi. Müvəqqəti şifrə ilə isə həmin hesaba GİRMƏK olur, yəni bu, bütün
    `ROOT_ONLY` hardlock-larının dolayı yan keçilməsi idi.

    İndi `CEO` (1) `Root`-dan (0) aşağıdadır və qapı bağlıdır.
    """
    actor = make_employee(SystemRole.CEO, flags=[RESET_PASSWORD_FLAG])
    subject = make_employee(SystemRole.ROOT)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="aşağı səlahiyyət"):
        uc.reset_password(actor=actor, subject=subject)

    assert subject.must_change_password is False
    assert audit.actions() == []


def test_another_root_can_still_reset_the_root_accounts_password(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """Bərabər pillə qalır — əks halda tək Root-lu tenant kilidlənərdi.

    Yuxarıdakı testin "hər şeyi bloklamaq" olmadığını göstərir: qadağa
    PİLLƏYƏ görədir, `Root` roluna görə yox.
    """
    actor = make_employee(SystemRole.ROOT, flags=[RESET_PASSWORD_FLAG])
    subject = make_employee(SystemRole.ROOT)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    credential = uc.reset_password(actor=actor, subject=subject)

    assert credential.plaintext
    assert "PASSWORD_RESET" in audit.actions()


def test_root_can_still_reset_a_ceo_password(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """İstiqamət YALNIZ yuxarıdan aşağıya açıldı — CEO hələ də idarə olunur."""
    actor = make_employee(SystemRole.ROOT, flags=[RESET_PASSWORD_FLAG])
    subject = make_employee(SystemRole.CEO)
    uc = reset_uc(InMemoryEmployees([actor, subject]), hashing, clock, audit, notifier)

    credential = uc.reset_password(actor=actor, subject=subject)

    assert credential.plaintext
    assert subject.must_change_password is True


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
            tenant_contact=COMPANY_CONTACT,
            verified_contact=COMPANY_CONTACT.email,
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
            tenant_contact=COMPANY_CONTACT,
            verified_contact=COMPANY_CONTACT.email,
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
            tenant_contact=COMPANY_CONTACT,
            verified_contact=COMPANY_CONTACT.email,
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
        tenant_contact=COMPANY_CONTACT,
        verified_contact=COMPANY_CONTACT.email,
    )

    assert target.is_active is True
    assert target.must_change_password is True
    assert hashing.verify_password(credential.hashed, credential.plaintext) is True
    assert "EMERGENCY_ACCESS_RECOVERY" in audit.actions()
    assert notifier.messages[0]["is_critical"] is True


# --------------------------------------------------------------------------- #
# SEC-016: bərpa şirkət əlaqəsinə əsaslanır, fərdi e-poçta YOX
# --------------------------------------------------------------------------- #


def test_recovery_rejects_contact_that_is_not_the_company_contact(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """ƏSAS QAPI: uyğunsuz əlaqə → bərpa yoxdur.

    Yoxlanılmasaydı, prosedur istənilən şəxsə Root hesabı verən arxa qapı
    olardı — aktiv admin qalmadıqda onu dayandıracaq başqa maneə yoxdur.
    """
    target = make_employee(SystemRole.ROOT, notification_email="oqru@hacker.test")
    target.is_active = False
    uc = recovery_uc(InMemoryEmployees([target]), hashing, clock, audit, notifier)

    with pytest.raises(AuthenticationError, match="şirkət əlaqə"):
        uc.recover(
            tenant_id=TENANT,
            target=target,
            developer_reference="TICKET-1234",
            active_admin_count=0,
            tenant_contact=COMPANY_CONTACT,
            verified_contact="oqru@hacker.test",
        )

    assert target.is_active is False
    assert "EMERGENCY_ACCESS_RECOVERY" not in audit.actions()


def test_recovery_accepts_company_phone_as_alternative_channel(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """Telefon fərqli formatda yazıla bilər — normallaşdırma tələb olunur."""
    target = make_employee(SystemRole.CEO)
    uc = recovery_uc(InMemoryEmployees([target]), hashing, clock, audit, notifier)

    credential = uc.recover(
        tenant_id=TENANT,
        target=target,
        developer_reference="TICKET-9",
        active_admin_count=0,
        tenant_contact=COMPANY_CONTACT,
        verified_contact="0501234567",  # qeydiyyatda "+994 50 123 45 67"
    )

    assert credential.plaintext


@pytest.mark.parametrize(
    "claimed",
    ["", "   ", "başqa@kompas.az", "0559999999", "12345"],
)
def test_tenant_contact_rejects_non_matching_values(claimed: str) -> None:
    assert COMPANY_CONTACT.matches(claimed) is False


@pytest.mark.parametrize(
    "claimed",
    ["rehber@kompas.az", "  REHBER@Kompas.AZ  ", "+994501234567", "994 50 123 45 67"],
)
def test_tenant_contact_accepts_matching_values(claimed: str) -> None:
    assert COMPANY_CONTACT.matches(claimed) is True


def test_tenant_contact_without_phone_rejects_any_number() -> None:
    """Telefon qeydiyyatda yoxdursa, telefonla təsdiq mümkün olmamalıdır."""
    contact = TenantContact(email="rehber@kompas.az")

    assert contact.matches("+994501234567") is False
    assert contact.matches("rehber@kompas.az") is True
