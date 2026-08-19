"""Giriş körpüsünün testləri — Faza 5.

Qt LAZIM DEYİL: kontroller saf Python-dur, ekran yalnız onun nəticəsini
göstərir. Beləliklə giriş qaydaları GUI olmadan yoxlanılır.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from src.application.use_cases.authentication import (
    AccountLockedError,
    AdminLoginUseCase,
    AuthenticationError,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    TenantId,
)
from src.presentation.controllers.auth import GENERIC_FAILURE_MESSAGE, AuthController

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Saxta obyektlər
# --------------------------------------------------------------------------- #


@dataclass
class _FakeCredentials:
    employee_id: EmployeeId
    password_hash: str | None
    pepper_version: int = 1
    pin_hash: str | None = None


class _FakeEmployees:
    def __init__(self, employee: Employee | None) -> None:
        self._employee = employee
        self.lookups: list[str] = []

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        self.lookups.append(str(username))
        return self._employee


class _FakeCredentialSource:
    def __init__(self, credentials: _FakeCredentials | None) -> None:
        self._credentials = credentials

    def credentials_for(self, employee_id: EmployeeId) -> _FakeCredentials | None:
        return self._credentials


class _FakeLogin:
    """`AdminLoginUseCase`-in yerinə keçən nazik saxta."""

    def __init__(self, *, outcome: object) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, object]] = []

    def login(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


@dataclass
class _Result:
    employee: Employee
    stage: object


def _employee(*, username: str = "r.mammadov") -> Employee:
    tenant = TENANT
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="ADMIN",
        name_az="Admin",
        priority=RolePriority.ADMIN,
        tenant_id=tenant,
        is_system=True,
    )
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant,
        position=position,
        first_name="Rəşad",
        last_name="Məmmədov",
        username=Username(username),
        has_password=True,
    )


def _controller(
    *, employee: Employee | None, credentials: _FakeCredentials | None, outcome: object
) -> tuple[AuthController, _FakeLogin, _FakeEmployees]:
    employees = _FakeEmployees(employee)
    login = _FakeLogin(outcome=outcome)
    controller = AuthController(
        login_use_case=login,  # type: ignore[arg-type]
        credentials=_FakeCredentialSource(credentials),
        employees=employees,
        tenant_id=TENANT,
    )
    return controller, login, employees


# --------------------------------------------------------------------------- #
# Uğurlu giriş
# --------------------------------------------------------------------------- #


def test_successful_login_returns_employee() -> None:
    from src.application.use_cases.authentication import LoginStage

    person = _employee()
    controller, login, _ = _controller(
        employee=person,
        credentials=_FakeCredentials(person.id, "argon2-hash", pepper_version=2),
        outcome=_Result(employee=person, stage=LoginStage.AUTHENTICATED),
    )

    outcome = controller.authenticate(Username("r.mammadov"), "Passw0rd!")

    assert outcome.succeeded
    assert outcome.employee is person
    assert not outcome.must_change_password
    # Hash və pepper versiyası use case-ə ÖTÜRÜLMƏLİDİR.
    assert login.calls[0]["stored_hash"] == "argon2-hash"
    assert login.calls[0]["pepper_version"] == 2


def test_password_change_requirement_is_surfaced() -> None:
    from src.application.use_cases.authentication import LoginStage

    person = _employee()
    controller, _, _ = _controller(
        employee=person,
        credentials=_FakeCredentials(person.id, "hash"),
        outcome=_Result(employee=person, stage=LoginStage.MUST_CHANGE_PASSWORD),
    )

    outcome = controller.authenticate(Username("r.mammadov"), "Passw0rd!")

    assert outcome.succeeded
    assert outcome.must_change_password


# --------------------------------------------------------------------------- #
# Uğursuz giriş
# --------------------------------------------------------------------------- #


def test_authentication_error_becomes_generic_message() -> None:
    """Hansı sahənin səhv olduğu AÇIQLANMAMALIDIR (user enumeration)."""
    person = _employee()
    controller, _, _ = _controller(
        employee=person,
        credentials=_FakeCredentials(person.id, "hash"),
        outcome=AuthenticationError("İstifadəçi adı və ya şifrə yanlışdır"),
    )

    outcome = controller.authenticate(Username("r.mammadov"), "səhv")

    assert not outcome.succeeded
    assert outcome.message == GENERIC_FAILURE_MESSAGE
    assert outcome.employee is None


def test_unknown_account_produces_the_same_message() -> None:
    """Mövcud olmayan hesab MÖVCUD hesabdan fərqlənməməlidir."""
    controller, login, employees = _controller(
        employee=None,
        credentials=None,
        outcome=AuthenticationError("yoxdur"),
    )

    outcome = controller.authenticate(Username("yoxdur"), "nəsə")

    assert outcome.message == GENERIC_FAILURE_MESSAGE
    # Hesab tapılmasa belə use case ÇAĞIRILIR — sabit vaxt üçün.
    assert login.calls, "Hesab yoxdursa da yoxlama aparılmalıdır"
    assert login.calls[0]["stored_hash"] is None
    assert employees.lookups == ["yoxdur"]


def test_locked_account_message_is_shown_verbatim() -> None:
    """Bloklanma gizlədilmir — istifadəçi nə qədər gözləyəcəyini bilməlidir."""
    person = _employee()
    locked = AccountLockedError("Hesab bloklanıb")
    controller, _, _ = _controller(
        employee=person,
        credentials=_FakeCredentials(person.id, "hash"),
        outcome=locked,
    )

    outcome = controller.authenticate(Username("r.mammadov"), "Passw0rd!")

    assert not outcome.succeeded
    assert outcome.message == locked.user_message
    assert outcome.message != GENERIC_FAILURE_MESSAGE


def test_unexpected_error_does_not_crash_the_screen() -> None:
    """Gözlənilməz istisna giriş ekranını çökdürməməlidir."""
    person = _employee()
    controller, _, _ = _controller(
        employee=person,
        credentials=_FakeCredentials(person.id, "hash"),
        outcome=RuntimeError("baza əlçatmazdır"),
    )

    outcome = controller.authenticate(Username("r.mammadov"), "Passw0rd!")

    assert not outcome.succeeded
    assert "Yenidən cəhd" in outcome.message


def test_missing_credentials_row_is_treated_as_no_password() -> None:
    """İşçi var, lakin şifrə sətri yoxdursa — sabit vaxtlı uğursuzluq."""
    person = _employee()
    controller, login, _ = _controller(
        employee=person,
        credentials=None,
        outcome=AuthenticationError("yoxdur"),
    )

    outcome = controller.authenticate(Username("r.mammadov"), "nəsə")

    assert not outcome.succeeded
    assert login.calls[0]["stored_hash"] is None


# --------------------------------------------------------------------------- #
# Real use case ilə inteqrasiya (saxta repo, əsl Argon2 yoxlaması)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("password", ["", "  ", "səhv-şifrə"])
def test_real_use_case_rejects_bad_passwords(password: str) -> None:
    """Saxta deyil, ƏSL `AdminLoginUseCase` ilə — hash yoxlaması işləyir."""
    from src.infrastructure.security.hashing import HashingService

    hashing = HashingService()
    person = _employee()
    stored = hashing.hash_password("Doğru-Şifrə-123")

    class _Clock:
        def now(self) -> datetime:
            return NOW

    class _Audit:
        def record(self, *args: object, **kwargs: object) -> None: ...

    class _SecurityEvents:
        """SEC-7: `AdminLoginUseCase` indi `security_events`-i MƏCBURİ tələb edir."""

        def record(self, *args: object, **kwargs: object) -> None: ...

    employees = _FakeEmployees(person)
    use_case = AdminLoginUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        clock=_Clock(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        security_events=_SecurityEvents(),  # type: ignore[arg-type]
    )
    controller = AuthController(
        login_use_case=use_case,
        credentials=_FakeCredentialSource(_FakeCredentials(person.id, stored)),
        employees=employees,
        tenant_id=TENANT,
    )

    outcome = controller.authenticate(Username("r.mammadov"), password)

    assert not outcome.succeeded
    assert outcome.message == GENERIC_FAILURE_MESSAGE


def test_real_use_case_accepts_the_correct_password() -> None:
    from src.infrastructure.security.hashing import HashingService

    hashing = HashingService()
    person = _employee()
    stored = hashing.hash_password("Doğru-Şifrə-123")

    class _Clock:
        def now(self) -> datetime:
            return NOW

    class _Audit:
        def record(self, *args: object, **kwargs: object) -> None: ...

    class _SecurityEvents:
        """SEC-7: `AdminLoginUseCase` indi `security_events`-i MƏCBURİ tələb edir."""

        def record(self, *args: object, **kwargs: object) -> None: ...

    employees = _FakeEmployees(person)
    use_case = AdminLoginUseCase(
        employees=employees,  # type: ignore[arg-type]
        hashing=hashing,
        clock=_Clock(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        security_events=_SecurityEvents(),  # type: ignore[arg-type]
    )
    controller = AuthController(
        login_use_case=use_case,
        credentials=_FakeCredentialSource(_FakeCredentials(person.id, stored)),
        employees=employees,
        tenant_id=TENANT,
    )

    outcome = controller.authenticate(Username("r.mammadov"), "Doğru-Şifrə-123")

    assert outcome.succeeded
    assert outcome.employee is person
