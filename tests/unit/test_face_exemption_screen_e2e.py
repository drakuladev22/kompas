"""`FaceExemptionScreen` ↔ `FaceExemptionController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_face_control_screen.py`-dəki `_ExemptionScreen` sahtəsi kontrollerin
`set_limits`/`set_employees`/`set_exemptions`/`show_error` çağırışlarını
YALNIZ siyahıya yazır — heç bir REAL forma, real `[Ləğv Et]` sətir düyməsi,
real `QLineEdit` yoxdur. Bu ekran isə `hardlock_level = 2` (Root/CEO) —
üz qatının PIN-only istisnasını verir, yəni ən yüksək riskli sahələrdən
biridir (modul başlığı). Burada ekran VƏ kontroller BİRLİKDƏ, real widget
ağacı ilə sınanır.

Sahtələr BU FAYLDA yerlidir (`tests/fixtures/fakes.py`-a TOXUNULMUR) — paralel
işləyən agentlər həmin ortaq faylı dəyişə bilər.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.application.use_cases.face_control import (
    MIN_EXEMPTION_REASON_LENGTH,
    FaceExemptionView,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.face_recognition import FaceExemption
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    TenantId,
    new_face_exemption_id,
)
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

_VALID_REASON = "Tibbi səbəb — həkim arayışı təqdim edilib"


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


def _employee(*, code: str, name_az: str, flags: tuple[str, ...] = ()) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=name_az,
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    for flag in flags:
        position.grant(PermissionFlag(code=flag, category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )


def _root() -> Employee:
    return _employee(code="ROOT", name_az="Root", flags=("can_manage_face_exemptions",))


def _seller() -> Employee:
    return _employee(code="SATICI", name_az="Satıcı")


# --------------------------------------------------------------------------- #
# Sahtələr — YALNIZ kontrollerin faktiki oxuduğu atributlar
# --------------------------------------------------------------------------- #


class _Row(dict):  # type: ignore[type-arg]
    """`row["sütun"]` müqaviləsi ilə uyğun gələn sətir."""


class _Cursor:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def fetchall(self) -> list[_Row]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def execute(self, _sql: str, _params: Any = ()) -> _Cursor:
        return _Cursor(self._rows)


class _Employees:
    def __init__(self, employees: dict[EmployeeId, Employee]) -> None:
        self._employees = employees

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._employees.get(employee_id)


class _Uow:
    def __init__(self, rows: list[_Row], employees: dict[EmployeeId, Employee]) -> None:
        self.connection = _Connection(rows)
        self.employees = _Employees(employees)


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default

    def get_str(self, _tenant_id: Any, _key: str, default: str) -> str:
        return default


class _ExemptionUseCase:
    def __init__(
        self,
        *,
        active: list[FaceExemptionView] | None = None,
        list_error: Exception | None = None,
        grant_error: Exception | None = None,
        revoke_error: Exception | None = None,
    ) -> None:
        self._active = active or []
        self._list_error = list_error
        self._grant_error = grant_error
        self._revoke_error = revoke_error
        self.granted: list[dict[str, Any]] = []
        self.revoked: list[dict[str, Any]] = []
        self.list_calls = 0

    def list_active(self, *, tenant_id: Any, actor: Any) -> list[FaceExemptionView]:
        self.list_calls += 1
        if self._list_error is not None:
            raise self._list_error
        return list(self._active)

    def grant(self, **kwargs: Any) -> None:
        if self._grant_error is not None:
            raise self._grant_error
        self.granted.append(kwargs)

    def revoke(self, **kwargs: Any) -> None:
        if self._revoke_error is not None:
            raise self._revoke_error
        self.revoked.append(kwargs)


class _Session:
    def __init__(
        self,
        *,
        employee_rows: list[_Row] | None = None,
        employees: dict[EmployeeId, Employee] | None = None,
        exemptions: _ExemptionUseCase | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(employee_rows or [], employees or {})
        self.limits = _Limits()
        self.face_exemptions = exemptions
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext` müqaviləsinin minimal təkrarı — HƏR ÇAĞIRIŞ YENİ sessiya."""

    def __init__(self, session_factory: Callable[[], _Session]) -> None:
        self._session_factory = session_factory
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = self._session_factory()
        self.sessions.append(created)
        yield created


def _exemption(employee_id: EmployeeId, granted_by: EmployeeId) -> FaceExemption:
    return FaceExemption(
        exemption_id=new_face_exemption_id(),
        tenant_id=TENANT,
        employee_id=employee_id,
        granted_by=granted_by,
        reason="Üz cərrahiyyəsindən sonra sağalma dövrü",
        granted_at=NOW,
        expires_at=NOW + timedelta(days=56),
    )


# --------------------------------------------------------------------------- #
# 1. Real forma → real klik → grant() + commit + REAL cədvəl yenilənir
# --------------------------------------------------------------------------- #


@requires_qt
def test_granting_an_exemption_via_the_real_form_commits_and_rereads_the_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    owner = _seller()
    root = _root()
    use_case = _ExemptionUseCase()
    context = _Context(
        lambda: _Session(
            employee_rows=[_Row(id=owner.id, first_name="Aysel", last_name="Quliyeva")],
            employees={owner.id: owner, root.id: root},
            exemptions=use_case,
        )
    )
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    FaceExemptionController(context, root).attach(screen)

    screen._reason.setText(_VALID_REASON)
    screen._days.setValue(14)
    _click(screen, "İstisna Ver")

    assert len(use_case.granted) == 1
    assert use_case.granted[0]["reason"] == _VALID_REASON
    assert use_case.list_calls >= 1, "Yazıdan sonra siyahı təzədən oxunmalıdır"
    assert any(s.commits == 1 for s in context.sessions)
    assert screen._reason.text() == "", "Uğurlu göndərişdən sonra sahə TƏMİZLƏNMƏLİDİR"


@requires_qt
def test_granting_without_selecting_an_employee_is_rejected_before_reaching_the_use_case(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    root = _root()
    use_case = _ExemptionUseCase()
    context = _Context(lambda: _Session(employee_rows=[], employees={}, exemptions=use_case))
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    FaceExemptionController(context, root).attach(screen)  # işçi siyahısı BOŞDUR

    screen._reason.setText(_VALID_REASON)
    _click(screen, "İstisna Ver")  # ÇÖKMƏMƏLİDİR

    assert use_case.granted == []
    assert "İşçi seçilməlidir" in screen._hint.text()


# --------------------------------------------------------------------------- #
# 2. Səbəb sahəsi — real klik, YARARSIZ dəyər YOLA ÇIXMIR
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("reason", ["", "   ", "qısa"])
def test_a_too_short_reason_via_the_real_button_never_reaches_the_use_case(
    qtbot, theme, reason: str
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    owner = _seller()
    root = _root()
    use_case = _ExemptionUseCase()
    context = _Context(
        lambda: _Session(
            employee_rows=[_Row(id=owner.id, first_name="Aysel", last_name="Quliyeva")],
            employees={owner.id: owner, root.id: root},
            exemptions=use_case,
        )
    )
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    FaceExemptionController(context, root).attach(screen)

    screen._reason.setText(reason)
    _click(screen, "İstisna Ver")  # ÇÖKMƏMƏLİDİR

    assert use_case.granted == []
    assert str(MIN_EXEMPTION_REASON_LENGTH) in screen._hint.text()


@requires_qt
@pytest.mark.parametrize(
    "reason",
    [
        "A" * 10_000,
        "😀🙂 üz istisnasının səbəbi kifayət qədər uzundur 😀🙂",
        "'; DROP TABLE face_control_exemptions; --",
    ],
    ids=["10000-simvol", "emoji", "sql-bənzər"],
)
def test_unusual_reason_text_passes_through_the_real_form_without_crashing(
    qtbot, theme, reason: str
) -> None:  # type: ignore[no-untyped-def]
    """Uzunluq/simvol yoxlaması YALNIZ minimal uzunluqdur — MƏZMUNU süzmür.

    SQL-bənzər mətnin bloklanmaması QƏSDƏNDİR: parametrləşdirilmiş sorğu
    (CLAUDE.md bölmə 4) qorunmanı DB sərhədində verir, GUI-nin mətni
    "təhlükəli görünür" deyə rədd etməsi lazım deyil — səbəb sahəsi sərbəst
    mətndir və işçi HƏQİQƏTƏN belə simvollar yaza bilər.
    """
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    owner = _seller()
    root = _root()
    use_case = _ExemptionUseCase()
    context = _Context(
        lambda: _Session(
            employee_rows=[_Row(id=owner.id, first_name="Aysel", last_name="Quliyeva")],
            employees={owner.id: owner, root.id: root},
            exemptions=use_case,
        )
    )
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    FaceExemptionController(context, root).attach(screen)

    screen._reason.setText(reason)
    _click(screen, "İstisna Ver")  # ÇÖKMƏMƏLİDİR

    assert len(use_case.granted) == 1
    assert use_case.granted[0]["reason"] == reason.strip()


# --------------------------------------------------------------------------- #
# 3. Real sətir düyməsi — [Ləğv Et] → modal → revoke() + commit
# --------------------------------------------------------------------------- #


@requires_qt
def test_revoking_via_the_real_row_button_commits_only_after_a_reason_is_given(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers import face_control as module
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    owner = _seller()
    root = _root()
    view = FaceExemptionView(exemption=_exemption(owner.id, root.id), days_remaining=30)
    use_case = _ExemptionUseCase(active=[view])
    context = _Context(
        lambda: _Session(employees={owner.id: owner, root.id: root}, exemptions=use_case)
    )
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    FaceExemptionController(context, root).attach(screen)

    # Modal BAĞLANIR (istifadəçi «Ləğv et» yazıb, sonra imtina edib) — YAZI
    # YOLUNA GETMİR, domen istisnası əvəzinə sükutla geri qayıdır.
    monkeypatch.setattr(
        module.FaceExemptionController, "_ask_reason", staticmethod(lambda *_: None)
    )
    _click(screen, "Ləğv Et")
    assert use_case.revoked == []

    monkeypatch.setattr(
        module.FaceExemptionController,
        "_ask_reason",
        staticmethod(lambda *_: "Sağalma dövrü bitdi, üz tanınır"),
    )
    _click(screen, "Ləğv Et")

    assert len(use_case.revoked) == 1
    assert any(s.commits == 1 for s in context.sessions)


# --------------------------------------------------------------------------- #
# 4. İlk yükləmə xətası — real `attach()`, boş cədvəl DEYİL, AÇIQ SƏBƏB
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_list_read_failure_on_attach_shows_an_error_not_a_blank_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    root = _root()
    denial = KompasOSError("hardlock", user_message="Hardlock 2 tələb olunur.")
    use_case = _ExemptionUseCase(list_error=denial)
    context = _Context(lambda: _Session(exemptions=use_case))
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)

    FaceExemptionController(context, root).attach(screen)  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 5–6. DÜZƏLDİLDİ — xəta banneri artıq `refresh()` ilə ÜSTÜNDƏN yazılmır
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_grant_error_banner_survives_the_refresh_that_follows(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    owner = _seller()
    root = _root()
    denial = KompasOSError("hardlock", user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.")
    use_case = _ExemptionUseCase(grant_error=denial)
    context = _Context(
        lambda: _Session(
            employee_rows=[_Row(id=owner.id, first_name="Aysel", last_name="Quliyeva")],
            employees={owner.id: owner, root.id: root},
            exemptions=use_case,
        )
    )
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    FaceExemptionController(context, root).attach(screen)

    screen._reason.setText(_VALID_REASON)
    _click(screen, "İstisna Ver")

    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_failed_revoke_error_banner_survives_the_refresh_that_follows(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers import face_control as module
    from src.presentation.controllers.face_control import FaceExemptionController
    from src.presentation.screens.face_control import FaceExemptionScreen

    owner = _seller()
    root = _root()
    view = FaceExemptionView(exemption=_exemption(owner.id, root.id), days_remaining=30)
    denial = KompasOSError("hardlock", user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.")
    use_case = _ExemptionUseCase(active=[view], revoke_error=denial)
    context = _Context(
        lambda: _Session(employees={owner.id: owner, root.id: root}, exemptions=use_case)
    )
    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    FaceExemptionController(context, root).attach(screen)

    monkeypatch.setattr(
        module.FaceExemptionController,
        "_ask_reason",
        staticmethod(lambda *_: "Sağalma dövrü bitdi, üz tanınır"),
    )
    _click(screen, "Ləğv Et")

    assert screen.switcher().current_state() == "error"
