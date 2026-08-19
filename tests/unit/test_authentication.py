"""Autentifikasiya use case testləri (Faza 2.6)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.application.use_cases.authentication import (
    RESET_PASSWORD_FLAG,
    RESET_PIN_FLAG,
    REVOKE_SESSION_FLAG,
    AccountLockedError,
    AdminLoginUseCase,
    AuthenticationError,
    CredentialResetUseCase,
    EmergencyAccessRecoveryUseCase,
    IssuedSession,
    LoginStage,
    PinHandshakeUseCase,
    SessionContextNotSupportedError,
    SessionExpiredError,
    SessionManagementUseCase,
    TenantContact,
    TerminalLockedError,
    TerminalThrottleUnavailableError,
)
from src.domain.entities import Employee, Position
from src.domain.entities.auth_session import SessionContext
from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
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
from src.domain.value_objects.machine_identity import MachineIdentityHash
from src.domain.value_objects.pin_throttle import TerminalPinThrottle
from src.infrastructure.security.hashing import HashingService
from tests.fixtures.fakes import (
    FakeClock,
    FakeSystemLimits,
    InMemoryAuthSessions,
    InMemoryEmployees,
    InMemoryPinThrottle,
    RecordingAudit,
    RecordingNotifier,
    RecordingSecurityEvents,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
#: SEC-05: throttle açarı — sınaqda sabit SHA-256-formatlı dəyər kifayətdir,
#: xam `MachineGuid` heç vaxt bu qatda görünmür (bax `MachineIdentityHash`-in
#: öz modul başlığı).
MACHINE = MachineIdentityHash(digest="a" * 64)
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
        # SEC-7: bu faylın 34 mövcud çağırışı `security_events`-i YOXLAMIR,
        # ona görə birdəfəlik sahtə kifayətdir — inspeksiya lazımdırsa ayrıca
        # arqument əlavə edin (SEC-8-dəki `review_batches` naxışı ilə eyni).
        security_events=RecordingSecurityEvents(),  # type: ignore[arg-type]
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
    *,
    pin_throttle: InMemoryPinThrottle | None = None,
    security_events: RecordingSecurityEvents | None = None,
    limits: FakeSystemLimits | None = None,
) -> PinHandshakeUseCase:
    """`pin_throttle`/`security_events`/`limits` OPSİONALDIR — köhnə çağıranlar
    (arqumentsiz) dəyişmir, YENİ SEC-01 testləri isə eyni `InMemoryPinThrottle`/
    `RecordingSecurityEvents` obyektini test bədənində SAXLAYIB birbaşa
    yoxlaya bilsin deyə (məs. `locked_reads`, `.event_types()`)."""
    resolved_limits = limits or FakeSystemLimits()
    return PinHandshakeUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        clock=clock,  # type: ignore[arg-type]
        limits=resolved_limits,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        security_events=security_events or RecordingSecurityEvents(),  # type: ignore[arg-type]
        pin_throttle=pin_throttle or InMemoryPinThrottle(clock=clock, limits=resolved_limits),  # type: ignore[arg-type]
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
        machine_key=MACHINE,
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
            machine_key=MACHINE,
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
            machine_key=MACHINE,
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
            machine_key=MACHINE,
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
        machine_key=MACHINE,
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
        machine_key=MACHINE,
        pin="4821",
        pin_hashes={employee.id: (stored, 1)},
    )

    assert result.employee.id == employee.id
    assert result.needs_pepper_rehash is True


# --------------------------------------------------------------------------- #
# SEC-01/SEC-05 — terminal PIN throttle DOMEN səviyyəsi
# (`TerminalPinThrottle.advance_after_failure` — sabit-pəncərə sərhədləri)
# --------------------------------------------------------------------------- #


def _throttle(
    *,
    failed_count: int = 0,
    window_started_at: datetime | None = None,
    locked_until: datetime | None = None,
) -> TerminalPinThrottle:
    return TerminalPinThrottle(
        tenant_id=TENANT,
        machine_key=MACHINE,
        store_id=STORE,
        failed_count=failed_count,
        window_started_at=window_started_at,
        locked_until=locked_until,
        updated_at=NOW,
    )


def test_advance_after_failure_starts_a_new_window_exactly_at_the_lock_boundary() -> None:
    """Dövrə 4-ün ƏSAS düzəlişi: `now == locked_until` DƏQİQ anında kilid
    ARTIQ bitmiş sayılır (`is_locked` ilə EYNİ `<` sərhəddi) — sayğac
    KÖHNƏDƏN DAVAM ETMİR, YENİ pəncərə `1`-dən başlayır, terminal DƏRHAL
    yenidən kilidlənmir. Bu, team-lead-in "kobud +1 dəqiqə testi tutmaz"
    xəbərdarlıq etdiyi DƏQİQ sərhəddir."""
    locked_until = NOW
    throttle = _throttle(
        failed_count=20, window_started_at=NOW - timedelta(minutes=15), locked_until=locked_until
    )

    result = throttle.advance_after_failure(now=locked_until, max_attempts=20, lockout_minutes=15)

    assert result.failed_count == 1
    assert result.window_started_at == locked_until
    assert result.locked_until is None


def test_advance_after_failure_freezes_the_counter_while_still_locked() -> None:
    """Kilid müddətində sayğac DONUR — `locked_until` yenidən hesablanmır,
    kilid UZADILMIR (müdafiə xətti; normal axında `_require_unlocked_throttle`
    bu haldan ƏVVƏL dayanır)."""
    locked_until = NOW + timedelta(minutes=5)
    throttle = _throttle(failed_count=20, window_started_at=NOW, locked_until=locked_until)

    result = throttle.advance_after_failure(
        now=NOW + timedelta(minutes=1), max_attempts=20, lockout_minutes=15
    )

    assert result is throttle  # DƏYİŞMƏYİB — eyni obyekt qaytarılır.


def test_advance_after_failure_accumulates_within_an_open_window() -> None:
    """Pəncərə HƏLƏ bitməyib, kilid YOXDUR — sayğac ARTIR, pəncərənin
    başlanğıcı DƏYİŞMİR."""
    window_started_at = NOW
    throttle = _throttle(failed_count=3, window_started_at=window_started_at, locked_until=None)

    result = throttle.advance_after_failure(
        now=NOW + timedelta(minutes=5), max_attempts=20, lockout_minutes=15
    )

    assert result.failed_count == 4
    assert result.window_started_at == window_started_at
    assert result.locked_until is None


def test_advance_after_failure_starts_a_new_window_after_natural_expiry() -> None:
    """Terminal HEÇ VAXT kilidlənməyib (hədd aşılmayıb), AMMA pəncərə
    (`lockout_minutes`) təbii olaraq bitib — köhnə typo-lar İLİŞİB QALMIR,
    YENİ pəncərə açılır. Bu, "uğurda sıfırlama yoxdur" qərarının ƏVƏZİNİ
    verən DECAY mexanizmidir."""
    throttle = _throttle(
        failed_count=5, window_started_at=NOW - timedelta(minutes=20), locked_until=None
    )

    result = throttle.advance_after_failure(now=NOW, max_attempts=20, lockout_minutes=15)

    assert result.failed_count == 1
    assert result.window_started_at == NOW


def test_advance_after_failure_locks_at_the_threshold() -> None:
    """Hədd DƏQİQ bu cəhdlə keçilir — kilid MƏHZ bu andan başlayır."""
    throttle = _throttle(failed_count=19, window_started_at=NOW, locked_until=None)

    result = throttle.advance_after_failure(
        now=NOW + timedelta(minutes=2), max_attempts=20, lockout_minutes=15
    )

    assert result.failed_count == 20
    assert result.locked_until == NOW + timedelta(minutes=2) + timedelta(minutes=15)


# --------------------------------------------------------------------------- #
# SEC-01 — terminal PIN throttle (dövrə 3 audit tapıntısı)
# --------------------------------------------------------------------------- #


def _low_threshold_limits() -> FakeSystemLimits:
    """Testdə 20 cəhd gözləməmək üçün həddi 2-yə endirir."""
    return FakeSystemLimits(
        {"KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS": "2", "KIOSK_STORE_PIN_LOCKOUT_MINUTES": "15"}
    )


class _BrokenPinThrottle:
    """`get_for_update` HƏMİŞƏ istisna atır — fail-closed testi üçün (SEC-06)."""

    def get_for_update(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash
    ) -> None:  # pragma: no cover - yalnız istisna atır
        raise RuntimeError("DB əlçatmazdır")

    def record_failure(self, *args: object, **kwargs: object) -> None:  # pragma: no cover
        raise AssertionError("bura HEÇ ÇATMAMALIDIR — fail-closed daha ƏVVƏL dayanmalıdır")

    def update_last_seen_store(self, *args: object, **kwargs: object) -> None:  # pragma: no cover
        raise AssertionError("bura HEÇ ÇATMAMALIDIR")


def test_terminal_locks_after_the_threshold_and_the_message_hides_the_employee(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """Hədd sərhədi + mesajın işçi kimliyini AÇMAMASI.

    İKİ fərqli işçi (A, B) İKİ AYRI yanlış PIN yazır — terminal sayğacı
    KONKRET işçiyə yox, MAŞINA bağlıdır (SEC-05), ona görə fərqli işçilərin
    cəhdləri EYNİ sayğacı artırır.
    """
    seller_a, stored_a = make_seller(hashing, pin="6532")
    seller_b, stored_b = make_seller(hashing, pin="7419")
    employees = InMemoryEmployees([seller_a, seller_b])
    pin_hashes = {seller_a.id: (stored_a, 1), seller_b.id: (stored_b, 1)}

    events = RecordingSecurityEvents()
    uc = pin_uc(
        employees, hashing, clock, audit, security_events=events, limits=_low_threshold_limits()
    )

    # 1-ci səhv cəhd (hədd 2-dir) — hələ bloklanmır.
    with pytest.raises(AuthenticationError):
        uc.authenticate(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="9999", pin_hashes=pin_hashes
        )

    # 2-ci səhv cəhd — hədd DOLUR, terminal bloklanır.
    with pytest.raises(AuthenticationError):
        uc.authenticate(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="9998", pin_hashes=pin_hashes
        )

    # 3-cü cəhd artıq DOĞRU PIN olsa belə rədd edilir — terminal bloklanıb.
    with pytest.raises(TerminalLockedError) as excinfo:
        uc.authenticate(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="6532", pin_hashes=pin_hashes
        )

    # Mesaj/kontekst HANSI işçinin (A və ya B) bloklandığını AÇMIR — çünki
    # heç bir işçi bloklanmayıb, TERMİNAL bloklanıb (PIN anonimdir).
    assert str(seller_a.id) not in str(excinfo.value.context)
    assert str(seller_b.id) not in str(excinfo.value.context)
    assert str(seller_a.id) not in excinfo.value.user_message
    assert "terminal" in excinfo.value.user_message.lower()

    assert "PIN_TERMINAL_LOCKED" in events.event_types()


def test_terminal_lockout_expires_after_the_window(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """Pəncərənin bitməsi: `KIOSK_STORE_PIN_LOCKOUT_MINUTES` keçdikdən sonra
    terminal ÖZÜ-ÖZÜNƏ açılır — əl ilə sıfırlama tələb olunmur."""
    employee, stored = make_seller(hashing)
    employees = InMemoryEmployees([employee])
    pin_hashes = {employee.id: (stored, 1)}
    uc = pin_uc(employees, hashing, clock, audit, limits=_low_threshold_limits())

    for _ in range(2):
        with pytest.raises(AuthenticationError):
            uc.authenticate(
                tenant_id=TENANT,
                store_id=STORE,
                machine_key=MACHINE,
                pin="9999",
                pin_hashes=pin_hashes,
            )

    with pytest.raises(TerminalLockedError):
        uc.authenticate(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="4821", pin_hashes=pin_hashes
        )

    clock.advance(minutes=16)  # 15 dəqiqəlik pəncərə keçib

    result = uc.authenticate(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="4821", pin_hashes=pin_hashes
    )
    assert result.employee.id == employee.id


def test_successful_login_does_not_reset_the_terminal_counter(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """SEC-05 qərarı: DOĞRU PIN terminal sayğacını SIFIRLAMIR (qərar
    əsaslandırması `PinThrottleRepository`-nin öz şərhindədir, `ports.py`) —
    əks halda hücumçu N-1 səhv edib qanuni girişi gözləməklə sayğacı
    PULSUZ təmizləyərdi."""
    employee, stored = make_seller(hashing)
    employees = InMemoryEmployees([employee])
    pin_hashes = {employee.id: (stored, 1)}
    throttle = InMemoryPinThrottle(clock=clock, limits=_low_threshold_limits())
    uc = pin_uc(
        employees, hashing, clock, audit, pin_throttle=throttle, limits=_low_threshold_limits()
    )

    with pytest.raises(AuthenticationError):
        uc.authenticate(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="9999", pin_hashes=pin_hashes
        )
    assert throttle.rows[(TENANT, MACHINE.digest)].failed_count == 1

    uc.authenticate(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="4821", pin_hashes=pin_hashes
    )
    # Uğurlu giriş sayğaca TOXUNMADI — dəyər UĞURDAN ƏVVƏLKİ kimi qalır.
    assert throttle.rows[(TENANT, MACHINE.digest)].failed_count == 1

    # YALNIZ 1 ƏLAVƏ səhv cəhd terminalı bloklamağa YETƏR (hədd 2, sayğac
    # artıq 1-dir) — sıfırlansaydı, bu, İKİNCİ (yox, birinci) səhv olardı
    # və hələ bloklamazdı. Bu ÇAĞIRIŞIN ÖZÜ hələ `AuthenticationError` verir
    # (PIN doğrudan da yanlışdır) — həddi KEÇƏN çağırışın ÖZÜ deyil, YALNIZ
    # NÖVBƏTİ çağırış `TerminalLockedError` görür (bax birinci testin eyni
    # naxışı).
    with pytest.raises(AuthenticationError):
        uc.authenticate(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="9996", pin_hashes=pin_hashes
        )
    assert throttle.rows[(TENANT, MACHINE.digest)].failed_count == 2

    with pytest.raises(TerminalLockedError):
        uc.authenticate(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="9995", pin_hashes=pin_hashes
        )


def test_pin_check_reads_the_throttle_row_under_lock(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """`get_for_update` HƏR çağırışda işlədilir (yarış qapağı — DOM-R2-02-nin
    eyni naxışı, bax `PinThrottleRepository`-nin öz şərhi)."""
    employee, stored = make_seller(hashing)
    employees = InMemoryEmployees([employee])
    throttle = InMemoryPinThrottle(clock=clock)
    uc = pin_uc(employees, hashing, clock, audit, pin_throttle=throttle)

    uc.authenticate(
        tenant_id=TENANT,
        store_id=STORE,
        machine_key=MACHINE,
        pin="4821",
        pin_hashes={employee.id: (stored, 1)},
    )

    assert throttle.locked_reads == [(TENANT, MACHINE.digest)]


def test_throttle_read_failure_rejects_the_pin_attempt(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """FAIL-CLOSED (SEC-06): throttle sətri oxuna bilmirsə PIN cəhdi RƏDD
    edilir — fail-OPEN (yoxlamanı keçib davam etmək) YOX. Səbəb
    `TerminalThrottleUnavailableError`-in öz şərhindədir: sükutla
    söndürülmüş qoruma məhz SEC-01-in özüdür."""
    employee, stored = make_seller(hashing)
    employees = InMemoryEmployees([employee])
    uc = pin_uc(employees, hashing, clock, audit, pin_throttle=_BrokenPinThrottle())  # type: ignore[arg-type]

    with pytest.raises(TerminalThrottleUnavailableError):
        uc.authenticate(
            tenant_id=TENANT,
            store_id=STORE,
            machine_key=MACHINE,
            pin="4821",  # DOĞRU PIN belə keçmir — DB nasazlığı hər şeydən əvvəldir.
            pin_hashes={employee.id: (stored, 1)},
        )


def test_clone_detection_logs_but_does_not_block(
    hashing: HashingService, clock: FakeClock, audit: RecordingAudit
) -> None:
    """Klon aşkarlaması (team-lead-in əlavə tapşırığı): saxlanmış `store_id`
    CARİ `store_id`-dən fərqlidirsə, PIN axını BLOKLANMIR — YALNIZ
    `SUSPECTED_CLONED_MACHINE_GUID` yazılır və sətir yenilənir."""
    employee, stored = make_seller(hashing)
    employees = InMemoryEmployees([employee])
    pin_hashes = {employee.id: (stored, 1)}
    other_store = StoreId(uuid.uuid4())
    events = RecordingSecurityEvents()
    throttle = InMemoryPinThrottle(clock=clock)
    uc = pin_uc(employees, hashing, clock, audit, pin_throttle=throttle, security_events=events)

    # BAŞQA mağazada eyni `machine_key` ilə bir səhv cəhd — sətirdə
    # `store_id=other_store` saxlanılır.
    with pytest.raises(AuthenticationError):
        uc.authenticate(
            tenant_id=TENANT,
            store_id=other_store,
            machine_key=MACHINE,
            pin="9999",
            pin_hashes=pin_hashes,
        )

    # İNDİ eyni `machine_key`, AMMA CARİ mağaza fərqlidir (STORE) — klon şübhəsi.
    result = uc.authenticate(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE, pin="4821", pin_hashes=pin_hashes
    )

    assert result.employee.id == employee.id  # PIN axını BLOKLANMADI.
    assert "SUSPECTED_CLONED_MACHINE_GUID" in events.event_types()
    # Sətir YENİLƏNİB — təkrar siqnal göndərməmək üçün.
    assert throttle.rows[(TENANT, MACHINE.digest)].store_id == STORE


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
        security_events=RecordingSecurityEvents(),  # type: ignore[arg-type]
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
        security_events=RecordingSecurityEvents(),  # type: ignore[arg-type]
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
# REQRESSİYA: müvəqqəti şifrənin heşi FAKTİKİ olaraq SAXLANILIR
#
# Əvvəl `recover()` heşi hesablayıb `TemporaryCredential`-da qaytarırdı, lakin
# HEÇ KİM onu bazaya yazmırdı (`save()` sirrlərə toxunmur). Nəticə: hesab
# aktivləşir, admin ekranda şifrə görür, müştəri isə DAXİL OLA BİLMİR — və bu,
# yalnız hər şey artıq bağlı olanda çağırılan mexanizmdir.
#
# Aşağıdakı testlər "metod çağırıldımı" DEYİL, "saxlanmış heş verilən açıq
# şifrəni DOĞRULAYIRMI" sualını yoxlayır — qüsur məhz ikinci sualda idi.
# --------------------------------------------------------------------------- #


def test_recovery_saxlanmis_hes_muveqqeti_sifreni_dogrulayir(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """Bərpadan sonra SAXLANMIŞ heş açıq şifrə ilə üst-üstə düşməlidir."""
    target = make_employee(SystemRole.ROOT)
    target.is_active = False
    employees = InMemoryEmployees([target])
    uc = recovery_uc(employees, hashing, clock, audit, notifier)

    credential = uc.recover(
        tenant_id=TENANT,
        target=target,
        developer_reference="TICKET-1234",
        active_admin_count=0,
        tenant_contact=COMPANY_CONTACT,
        verified_contact=COMPANY_CONTACT.email,
    )

    stored = employees.credentials[target.id]
    assert stored["password_hash"], "Heş bazaya YAZILMALIDIR — `save()` ona toxunmur"
    assert (
        hashing.verify_password(
            stored["password_hash"],
            credential.plaintext,
            pepper_version=stored["pepper_version"],
        )
        is True
    ), "Ekranda göstərilən şifrə ilə saxlanmış heş uyğun gəlmirsə giriş mümkün deyil"
    # PIN heşinə TOXUNULMAMALIDIR: şifrə bərpası PIN-i sıfırlamır.
    assert "pin_hash" not in stored


def test_recovery_pepper_versiyasi_da_yazilir(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """SEC-005: heş yeni pepper ilə yaradılırsa versiya da yenilənməlidir.

    Yazılmasaydı, `AdminLoginUseCase.login` sətirdəki KÖHNƏ versiya ilə
    yoxlayar və doğru şifrə də rədd edilərdi.
    """
    target = make_employee(SystemRole.ROOT)
    employees = InMemoryEmployees([target])
    uc = recovery_uc(employees, hashing, clock, audit, notifier)

    credential = uc.recover(
        tenant_id=TENANT,
        target=target,
        developer_reference="TICKET-1234",
        active_admin_count=0,
        tenant_contact=COMPANY_CONTACT,
        verified_contact=COMPANY_CONTACT.email,
    )

    assert employees.credentials[target.id]["pepper_version"] == credential.pepper_version
    assert credential.pepper_version == hashing.current_pepper_version


def test_reset_password_saxlanmis_hes_dogrulayir(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """`CredentialResetUseCase.reset_password` də heşi YAZMALIDIR.

    Bu use case istehsalat yoluna qoşulu deyil (bax sinif başlığı), lakin eyni
    tələ orada da vardı — qoşulduğu gün sükutla işləməyən şifrə verərdi.
    """
    actor = make_employee(SystemRole.ROOT, flags=[RESET_PASSWORD_FLAG])
    subject = make_employee(SystemRole.HR_ADMIN)
    employees = InMemoryEmployees([actor, subject])
    uc = reset_uc(employees, hashing, clock, audit, notifier)

    credential = uc.reset_password(actor=actor, subject=subject)

    stored = employees.credentials[subject.id]
    assert (
        hashing.verify_password(
            stored["password_hash"],
            credential.plaintext,
            pepper_version=stored["pepper_version"],
        )
        is True
    )


def test_reset_pin_saxlanmis_hes_dogrulayir(
    hashing: HashingService,
    clock: FakeClock,
    audit: RecordingAudit,
    notifier: RecordingNotifier,
) -> None:
    """PIN heşi `employee_id`-yə bağlıdır (SEC-005) — saxlanan dəyər onunla yoxlanır."""
    actor = make_employee(SystemRole.ROOT, flags=[RESET_PIN_FLAG])
    subject = make_employee(SystemRole.HR_ADMIN)
    employees = InMemoryEmployees([actor, subject])
    uc = reset_uc(employees, hashing, clock, audit, notifier)

    credential = uc.reset_pin(actor=actor, subject=subject)

    stored = employees.credentials[subject.id]
    assert (
        hashing.verify_pin(
            stored["pin_hash"],
            credential.plaintext,
            employee_id=str(subject.id),
            pepper_version=stored["pepper_version"],
        )
        is True
    )
    # Şifrə heşinə TOXUNULMAMALIDIR — `COALESCE` davranışı (bax repo docstring-i).
    assert "password_hash" not in stored


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


# --------------------------------------------------------------------------- #
# Sessiya müddəti (SEC-011 / dövrə debatı SEC-5)
# --------------------------------------------------------------------------- #
# `SessionManagementUseCase` `authentication.py:80%` əhatəsindəki əsas boş
# blokdur (`qa` əhatə hesabatı, sətir 568-704) — dövrənin ƏN BÖYÜK satış
# blokeri. Əsas invariant `AuthSession.touch()`-dadır (entity), bu sinif isə
# limitləri oxuyub ona ötürür — testlər HƏR İKİ qatı əhatə edir.


def session_uc(
    *,
    clock: FakeClock,
    audit: RecordingAudit,
    sessions: InMemoryAuthSessions | None = None,
    limits: FakeSystemLimits | None = None,
) -> tuple[SessionManagementUseCase, InMemoryAuthSessions]:
    store = sessions if sessions is not None else InMemoryAuthSessions()
    use_case = SessionManagementUseCase(
        sessions=store,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        limits=limits or FakeSystemLimits(),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )
    return use_case, store


def _issue(
    uc: SessionManagementUseCase, employee: Employee, context: SessionContext
) -> IssuedSession:
    return uc.issue(tenant_id=TENANT, employee=employee, context=context)


# --------------------------- `issue()` — token/hash --------------------------- #


def test_issue_writes_only_the_hash_never_the_plaintext_token(
    clock: FakeClock, audit: RecordingAudit
) -> None:
    """SEC-011: «DB sızsa mövcud sessiyalar oğurlana bilməz» — açıq token YAZILMIR."""
    uc, sessions = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)

    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)

    stored = sessions.items[issued.session.id]
    assert stored.token_hash == hashlib.sha256(issued.token.encode("utf-8")).hexdigest()
    # `AuthSession`-in HEÇ BİR sahəsi açıq tokenin ÖZÜNÜ daşımır.
    assert issued.token not in vars(stored).values()
    assert "SESSION_ISSUED" in audit.actions()


def test_kiosk_context_never_gets_a_session() -> None:
    """SEC-011: `KIOSK`-da sessiya YOXDUR — hər əməliyyat üçün PIN."""
    uc, _ = session_uc(clock=FakeClock(NOW), audit=RecordingAudit())
    employee = make_employee(SystemRole.SELLER)

    with pytest.raises(SessionContextNotSupportedError):
        _issue(uc, employee, SessionContext.KIOSK)


# --------------------------------- kontekstlər --------------------------------- #


def test_admin_panel_has_both_an_idle_and_an_absolute_ceiling(clock: FakeClock) -> None:
    uc, _ = session_uc(clock=clock, audit=RecordingAudit())
    employee = make_employee(SystemRole.HR_ADMIN)

    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)

    assert issued.session.expires_at == NOW + timedelta(minutes=30)
    assert issued.session.absolute_expiry == NOW + timedelta(hours=8)


def test_camera_dashboard_has_no_idle_ceiling_only_the_absolute_one(clock: FakeClock) -> None:
    """SEC-011-in açıq tələbi: operator ekrana baxır, klikləmir."""
    uc, _ = session_uc(clock=clock, audit=RecordingAudit())
    employee = make_employee(SystemRole.CAMERA_OPERATOR)

    issued = _issue(uc, employee, SessionContext.CAMERA_DASHBOARD)

    assert issued.session.context.has_idle_timeout is False
    assert issued.session.absolute_expiry == NOW + timedelta(hours=12)
    # Hərəkətsizlik pəncərəsi YOXDUR — `expires_at` birbaşa mütləq tavana bərabərdir.
    assert issued.session.expires_at == issued.session.absolute_expiry


# ---------------------------------- `validate()` ---------------------------------- #


def test_validate_accepts_a_freshly_issued_session(clock: FakeClock, audit: RecordingAudit) -> None:
    uc, _ = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)

    validated = uc.validate(tenant_id=TENANT, token=issued.token)

    assert validated.id == issued.session.id


def test_validate_rejects_an_unknown_token(clock: FakeClock, audit: RecordingAudit) -> None:
    uc, _ = session_uc(clock=clock, audit=audit)

    with pytest.raises(SessionExpiredError):
        uc.validate(tenant_id=TENANT, token="heç-vaxt-verilməmiş-token")


def test_validate_expires_an_idle_session_and_audits_it_once(
    clock: FakeClock, audit: RecordingAudit
) -> None:
    """Müddət bitməsi SƏSSİZ deyil — SEC-5 müqaviləsi: audit izi tələb edir."""
    uc, sessions = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)
    clock.advance(minutes=31)  # idle həddi (30 dəq) keçib

    with pytest.raises(SessionExpiredError):
        uc.validate(tenant_id=TENANT, token=issued.token)

    stored = sessions.items[issued.session.id]
    assert stored.is_revoked is True
    assert stored.revocation_reason == "Sessiya müddəti bitdi (timeout)"
    assert audit.actions().count("SESSION_EXPIRED") == 1

    # İKİNCİ `validate()` eyni (artıq ləğv edilmiş) sessiyanı YENƏ rədd edir,
    # LAKİN audit sətri TƏKRAR yazılmır (`_expire_if_needed`-in `is_revoked`
    # qapısı) — əks halda hər sınanmış sorğu öz sətrini yaradardı.
    with pytest.raises(SessionExpiredError):
        uc.validate(tenant_id=TENANT, token=issued.token)
    assert audit.actions().count("SESSION_EXPIRED") == 1


def test_validate_rejects_a_session_past_the_absolute_ceiling_even_if_recently_touched(
    clock: FakeClock, audit: RecordingAudit
) -> None:
    """Mütləq tavan keçəndə TOXUNULMA TARİXİNDƏN ASILI OLMAYARAQ rədd edilir."""
    uc, _ = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)
    clock.advance(hours=7, minutes=50)
    uc.touch(tenant_id=TENANT, session=issued.session)  # idle pəncərə tavana YAPIŞIR
    clock.advance(hours=1)  # indi mütləq tavanın (8 saat) O TAYINDA

    with pytest.raises(SessionExpiredError):
        uc.validate(tenant_id=TENANT, token=issued.token)


# ----------------------------------- `touch()` ------------------------------------ #


def test_touch_extends_the_idle_window(clock: FakeClock, audit: RecordingAudit) -> None:
    uc, _ = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)
    clock.advance(minutes=20)

    touched = uc.touch(tenant_id=TENANT, session=issued.session)

    assert touched.expires_at == clock.now() + timedelta(minutes=30)
    assert touched.last_seen_at == clock.now()


def test_touch_never_extends_the_absolute_ceiling(clock: FakeClock, audit: RecordingAudit) -> None:
    """SEC-011-in BÜTÜN MƏNASI (team-lead xüsusi vurğuladı, SEC5_CONTRACT.md).

    `touch()` NƏ QƏDƏR TƏKRAR çağırılsa da `absolute_expiry` BİR SANİYƏ belə
    sürüşmür — gecə növbəsinə "diri" qalan açıq sessiya SEC-011-in qadağan
    etdiyi məhz budur.
    """
    uc, _ = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)
    absolute_expiry = issued.session.absolute_expiry  # NOW + 8 saat

    # 6 saat ərzində, 20 dəqiqəlik addımlarla — fasiləsiz "fəaliyyət" simulyasiyası.
    for _ in range(18):
        clock.advance(minutes=20)
        uc.touch(tenant_id=TENANT, session=issued.session)

    assert issued.session.absolute_expiry == absolute_expiry, (
        "6 saatlıq fasiləsiz fəaliyyətdən sonra belə mütləq tavan dəyişməməlidir"
    )
    assert issued.session.expires_at <= absolute_expiry


def test_touch_caps_the_idle_window_at_the_absolute_ceiling(
    clock: FakeClock, audit: RecordingAudit
) -> None:
    """Namizəd pəncərə mütləq tavanı KEÇƏNDƏ `expires_at` ONA BƏRABƏRLƏŞDİRİLİR.

    `AuthSession.touch()`-un `min(namizəd, absolute_expiry)` sətrinin BİRBAŞA
    ölçüsü — bu sətir `now + idle_timeout` ilə əvəzlənsəydi test BURADA sınardı.
    """
    uc, _ = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)
    absolute_expiry = issued.session.absolute_expiry  # NOW + 8 saat
    clock.advance(hours=7, minutes=55)  # namizəd (+30 dəq) mütləq tavanı KEÇƏRDİ

    uc.touch(tenant_id=TENANT, session=issued.session)

    assert issued.session.expires_at == absolute_expiry
    assert issued.session.is_valid(now=clock.now()) is True  # hələ sərhəddə, etibarlı


def test_touch_is_a_no_op_for_camera_dashboard(clock: FakeClock, audit: RecordingAudit) -> None:
    """CAMERA_DASHBOARD-da `touch()` SÜKUTLA heç nə etmir (PERF-1/2/3: lazımsız yazı yoxdur)."""
    uc, sessions = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.CAMERA_OPERATOR)
    issued = _issue(uc, employee, SessionContext.CAMERA_DASHBOARD)
    original_expires_at = issued.session.expires_at
    original_last_seen = issued.session.last_seen_at
    saves_before = len(sessions.saves)
    clock.advance(hours=1)

    result = uc.touch(tenant_id=TENANT, session=issued.session)

    assert result.expires_at == original_expires_at
    assert result.last_seen_at == original_last_seen
    assert len(sessions.saves) == saves_before  # yenidən `save()` ÇAĞIRILMADI


def test_touch_refuses_a_revoked_session(clock: FakeClock, audit: RecordingAudit) -> None:
    uc, _ = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)
    uc.revoke(tenant_id=TENANT, actor=employee, target=issued.session, reason="Çıxış")

    with pytest.raises(InvalidStateTransitionError):
        uc.touch(tenant_id=TENANT, session=issued.session)


# ----------------------------------- `revoke()` ------------------------------------ #


def test_the_owner_can_revoke_their_own_session_without_any_flag(
    clock: FakeClock, audit: RecordingAudit
) -> None:
    """«Çıxış» düyməsi HƏR KƏSƏ açıqdır — `can_revoke_sessions` ÖZÜNƏ aid deyil."""
    uc, sessions = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.SELLER)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)

    uc.revoke(tenant_id=TENANT, actor=employee, target=issued.session, reason="Çıxış")

    assert sessions.items[issued.session.id].is_revoked is True
    assert "SESSION_REVOKED" in audit.actions()


def test_revoking_someone_elses_session_requires_the_flag(
    clock: FakeClock, audit: RecordingAudit
) -> None:
    uc, _ = session_uc(clock=clock, audit=audit)
    owner = make_employee(SystemRole.SELLER)
    admin_without_flag = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, owner, SessionContext.ADMIN_PANEL)

    with pytest.raises(AuthenticationError):
        uc.revoke(
            tenant_id=TENANT,
            actor=admin_without_flag,
            target=issued.session,
            reason="Şübhəli giriş",
        )


def test_revoking_someone_elses_session_succeeds_with_the_flag(
    clock: FakeClock, audit: RecordingAudit
) -> None:
    uc, sessions = session_uc(clock=clock, audit=audit)
    owner = make_employee(SystemRole.SELLER)
    admin = make_employee(SystemRole.HR_ADMIN, flags=[REVOKE_SESSION_FLAG])
    issued = _issue(uc, owner, SessionContext.ADMIN_PANEL)

    uc.revoke(tenant_id=TENANT, actor=admin, target=issued.session, reason="Şübhəli giriş")

    stored = sessions.items[issued.session.id]
    assert stored.is_revoked is True
    assert stored.revoked_by == admin.id
    assert stored.revocation_reason == "Şübhəli giriş"


def test_a_revoked_session_fails_validation(clock: FakeClock, audit: RecordingAudit) -> None:
    uc, _ = session_uc(clock=clock, audit=audit)
    employee = make_employee(SystemRole.HR_ADMIN)
    issued = _issue(uc, employee, SessionContext.ADMIN_PANEL)
    uc.revoke(tenant_id=TENANT, actor=employee, target=issued.session, reason="Çıxış")

    with pytest.raises(SessionExpiredError):
        uc.validate(tenant_id=TENANT, token=issued.token)
