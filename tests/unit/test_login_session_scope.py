"""Bir giriş cəhdi = BİR tranzaksiya — PERF-2.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`app._SessionScopedLogin` başlığı belə vəd edirdi: «Üçü BİR sinifdədir, çünki
hər üçü eyni sətri oxuyur; ayrı-ayrı olsaydılar bir giriş cəhdi üç ardıcıl
tranzaksiya açardı». Vəd YERİNƏ YETİRİLMİRDİ — üç metodun HƏR BİRİ öz
`context.session()`-unu açırdı:

    1. `get_by_username`  → sessiya 1
    2. `credentials_for`  → sessiya 2
    3. `login`            → sessiya 3 (üstəlik `commit`)

Uzaq bazada (ölçülüb: gediş-gəliş ~206 ms) bu, «Daxil Ol» düyməsindən sonra
təxminən üç saniyə gözləmə demək idi. İstifadəçinin bildirdiyi «button late
reply» şikayətinin ən böyük payı buradan gəlirdi.

Bu fayl sərhədin FAKTİKİ olaraq işlədiyini yoxlayır — sayğac testidir, vaxt
testi deyil (səbəb `test_session_roundtrips.py` başlığındadır).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.presentation.controllers.auth import AuthController

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())


class _Bridge:
    """`_SessionScopedLogin`-in ölçülə bilən modeli.

    Real körpü `ApplicationContext`-ə bağlıdır (yəni canlı bazaya); burada
    yalnız SESSİYA AÇILIŞLARI sayılır, çünki qüsur da elə onların sayında idi.
    """

    def __init__(self, employee: Employee | None) -> None:
        self._employee = employee
        self.opened = 0
        self.closed = 0
        self._shared: Any | None = None

    @contextmanager
    def attempt(self) -> Iterator[None]:
        with self._session():
            self._shared = object()
            try:
                yield
            finally:
                self._shared = None

    @contextmanager
    def _session(self) -> Iterator[Any]:
        if self._shared is not None:
            yield self._shared
            return
        self.opened += 1
        try:
            yield object()
        finally:
            self.closed += 1

    # --- körpünün üç üzü ---------------------------------------------------- #

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        with self._session():
            return self._employee

    def credentials_for(self, employee_id: EmployeeId) -> Any:
        with self._session():
            return None

    def login(self, **kwargs: Any) -> Any:
        with self._session():
            return _Result(self._employee)


class _Result:
    def __init__(self, employee: Employee | None) -> None:
        self.employee = employee
        from src.application.use_cases.authentication import LoginStage

        self.stage = LoginStage.AUTHENTICATED


def _employee() -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="CEO",
        name_az="CEO",
        priority=RolePriority.EXECUTIVE,
        tenant_id=TENANT,
        is_system=True,
    )
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Murad",
        last_name="Bayramov",
        username=Username("m.bayramov"),
        has_password=True,
    )


def _controller(bridge: _Bridge) -> AuthController:
    return AuthController(
        login_use_case=bridge,  # type: ignore[arg-type]
        credentials=bridge,
        employees=bridge,
        tenant_id=TENANT,
        scope=bridge,
    )


def test_one_attempt_opens_exactly_one_session() -> None:
    """QÜSURUN ÖLÇÜSÜ: üç oxu, BİR sessiya."""
    bridge = _Bridge(_employee())

    _controller(bridge).authenticate(Username("m.bayramov"), "Uzun-Sifre-123")

    assert bridge.opened == 1
    assert bridge.closed == 1


def test_a_missing_account_still_opens_only_one_session() -> None:
    """Hesab tapılmasa da axın EYNİDİR — sabit vaxt qoruması pozulmur.

    Sessiya sayı hesabın mövcudluğundan asılı olsaydı, cavab müddəti fərqi
    hesab sadalamağa (user enumeration) yol açardı — yəni bu, təkcə sürət
    deyil, təhlükəsizlik xüsusiyyətidir.
    """
    bridge = _Bridge(None)

    _controller(bridge).authenticate(Username("yoxdur"), "Uzun-Sifre-123")

    assert bridge.opened == 1


def test_the_session_is_released_when_the_attempt_raises() -> None:
    """İstisna halında paylaşılan istinad QALMAMALIDIR.

    Qalsaydı, növbəti cəhd ARTIQ BAĞLANMIŞ tranzaksiyaya yazmağa çalışardı və
    səbəb «bir dəfə işlədi, ikinci dəfə işləmədi» kimi görünərdi.
    """
    bridge = _Bridge(_employee())

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("gözlənilməz")

    bridge.login = _boom  # type: ignore[method-assign]
    outcome = _controller(bridge).authenticate(Username("m.bayramov"), "Uzun-Sifre-123")

    assert outcome.succeeded is False
    assert bridge.closed == 1
    assert bridge._shared is None


def test_without_a_scope_each_read_opens_its_own_session() -> None:
    """Sərhəd İSTƏYƏ BAĞLIDIR — sahtələrlə qurulan testlər dəyişməz qalır."""
    bridge = _Bridge(_employee())
    controller = AuthController(
        login_use_case=bridge,  # type: ignore[arg-type]
        credentials=bridge,
        employees=bridge,
        tenant_id=TENANT,
    )

    controller.authenticate(Username("m.bayramov"), "Uzun-Sifre-123")

    assert bridge.opened == 3
