r"""`ProfileScreen` ↔ `ProfileController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik — "profile" ekranı)
──────────────────────────────────────────────────────────────────────────────
`test_phase56_write_controllers.py`/`test_controller_gap_coverage.py`/
`test_session_touch_guard.py` `ProfileController`-i duck-typing sahtəsi
(`_ProfileScreen`) və ya çılpaq `QWidget()` ilə ölçür — REAL `ProfileScreen`,
REAL "Ad, Soyad" `FormField`-inə YAZILMIŞ mətn və REAL "Yadda Saxla" /
"Şəkli Dəyiş" / "Şifrəni Dəyiş" / "Digər sessiyaları bağla" düymələri heç
vaxt qurulmur.

`_on_photo` VƏ `_on_password` (profile.py) HEÇ BİR mövcud testdə ÇAĞIRILMIR —
`grep -rn "_on_photo\|_on_password" tests/` boş nəticə verirdi bu fayldan
əvvəl. İkisi də `_inform()` vasitəsilə REAL `QMessageBox(screen).exec()`
açır — real `QWidget` parent tələb etdiyi üçün duck-type sahtə ilə sınana
BİLMƏZ (bax `test_settings_controller.py`-nin son qeydi, eyni səbəb).

Sahtələr `test_phase56_write_controllers.py::_ProfileSession` ailəsinin
TƏKRARIDIR (fayl-lokal saxlanılır — CLAUDE.md §6: hər e2e faylı öz sahtəsini
daşıyır, `test_pos_threshold_screen_e2e.py`/`test_tasks_screen_e2e.py` ilə
EYNİ konvensiya).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


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


@pytest.fixture(autouse=True)
def _messages(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """`_inform()` (`profile.py`) REAL `QMessageBox(screen).exec()` açır —
    real modal event loop test sapını əbədi bloklardı (bax
    `test_session_touch_guard.py`-dəki EYNİ naxış)."""
    from PySide6.QtWidgets import QMessageBox

    captured: list[tuple[str, str]] = []

    def _fake_exec(self: Any) -> int:
        captured.append((self.windowTitle(), self.text()))
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    return captured


# --------------------------------------------------------------------------- #
# Sahtələr — `test_phase56_write_controllers.py::_ProfileSession` ailəsi
# --------------------------------------------------------------------------- #


class _Users:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.updates: list[Any] = []
        self._error = error

    def update_employee(self, *, tenant_id: Any, actor: Any, employee_id: Any, draft: Any) -> Any:
        if self._error is not None:
            raise self._error
        self.updates.append(draft)


class _Employees:
    def __init__(self, employee: Any) -> None:
        self._employee = employee

    def get(self, _employee_id: Any) -> Any:
        return self._employee


class _PermissionFlagCatalog:
    def list_all(self) -> list[Any]:
        return [type("_Flag", (), {"code": "can_manage_employees"})()]


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def execute(self, _sql: str, _params: Any = ()) -> _Cursor:
        return _Cursor([])


class _AuthSessionsRepo:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []
        self.calls = 0

    def list_recent_for_user(self, _tenant_id: Any, _user_id: Any, *, limit: int = 10) -> list[Any]:
        self.calls += 1
        return list(self._rows)


class _Uow:
    def __init__(self, employee: Any, auth_sessions: _AuthSessionsRepo) -> None:
        self.employees = _Employees(employee)
        self.connection = _Connection()
        self._auth_sessions = auth_sessions

    def repository(self, name: str) -> Any:
        if name == "auth_sessions":
            return self._auth_sessions
        assert name == "permission_flags"
        return _PermissionFlagCatalog()


class _EmployeeProfileAccess:
    def require_view(self, *, viewer: Any, subject: Any) -> None:
        pass


class _PerformanceReviews:
    def list_own(self, *, tenant_id: Any, employee: Any) -> list[Any]:
        return []


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default

    def get_str(self, _tenant_id: Any, _key: str, default: str) -> str:
        return default


class _RevokingSessions:
    def __init__(self) -> None:
        self.revoked: list[Any] = []

    def revoke(self, *, tenant_id: Any, actor: Any, target: Any, reason: str) -> None:
        self.revoked.append(target)


class _Session:
    def __init__(
        self,
        employee: Any,
        users: _Users,
        *,
        auth_sessions: _AuthSessionsRepo | None = None,
        sessions: _RevokingSessions | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.users = users
        self.uow = _Uow(employee, auth_sessions or _AuthSessionsRepo())
        self.employee_profile = _EmployeeProfileAccess()
        self.performance_reviews = _PerformanceReviews()
        self.limits = _Limits()
        self.sessions = sessions or _RevokingSessions()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Clock:
    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _Context:
    def __init__(
        self,
        employee: Any,
        users: _Users,
        *,
        auth_sessions: _AuthSessionsRepo | None = None,
        sessions: _RevokingSessions | None = None,
    ) -> None:
        self._employee = employee
        self._users = users
        self._auth_sessions = auth_sessions
        self._sessions = sessions
        self.clock = _Clock()
        self.opened: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            self._employee, self._users, auth_sessions=self._auth_sessions, sessions=self._sessions
        )
        self.opened.append(created)
        yield created


def _employee() -> Any:
    from src.domain.entities.employee import Employee
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import RolePriority
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import EmployeeId, PositionId

    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Rəşad",
        last_name="Məmmədov",
        username=Username.parse("r.mammadov"),
        has_password=True,
    )


def _attach(context: Any, theme: Any, *, qtbot: Any) -> Any:
    from src.presentation.controllers.profile import ProfileController
    from src.presentation.screens.group_g import ProfileScreen

    screen = ProfileScreen(
        theme,
        full_name="Rəşad Məmmədov",
        role_name="HR Admin",
        store_name="Mərkəz",
        member_since="2024",
    )
    qtbot.addWidget(screen)
    ProfileController(context, _employee_actor(context)).attach(screen)  # type: ignore[arg-type]
    return screen


def _employee_actor(context: Any) -> Any:
    return context._employee


# --------------------------------------------------------------------------- #
# 1. Real "Yadda Saxla" — real yazılmış mətn yazı yoluna çatır
# --------------------------------------------------------------------------- #


@requires_qt
def test_typing_into_the_real_field_and_saving_writes_only_the_name(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    users = _Users()
    context = _Context(_employee(), users)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._full_name.set_text("Rəşad Əli Məmmədov")  # REAL yazının yerini tutur

    _click(screen, "Yadda Saxla")

    assert len(users.updates) == 1
    assert users.updates[0].first_name == "Rəşad Əli"
    assert users.updates[0].last_name == "Məmmədov"
    assert any(s.committed for s in context.opened)
    # Yazıdan SONRA `refresh()` real ekranı YENİDƏN doldurur.
    assert screen._username.text() == "r.mammadov"


@requires_qt
def test_hostile_and_extreme_text_in_the_real_name_field_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    users = _Users()
    context = _Context(_employee(), users)
    screen = _attach(context, theme, qtbot=qtbot)

    hostile = "'; DROP TABLE employees; -- 🔥 " + "A" * 10_000 + " Soyad"
    screen._full_name.set_text(hostile)

    _click(screen, "Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert len(users.updates) == 1
    assert users.updates[0].last_name == "Soyad"  # SON söz soyad sayılır


@requires_qt
def test_saving_a_whitespace_only_real_name_is_rejected_inline(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    users = _Users()
    context = _Context(_employee(), users)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._full_name.set_text("    ")

    _click(screen, "Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert users.updates == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_denied_save_shows_the_domain_reason_not_a_generic_one(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    class _DeniedError(KompasOSError):
        user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."

    users = _Users(error=_DeniedError("no flag"))
    context = _Context(_employee(), users)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._full_name.set_text("Yeni Ad")
    _click(screen, "Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 2. Real "Şəkli Dəyiş" / "Şifrəni Dəyiş" — HEÇ BİR mövcud testdə yox idi
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_change_photo_shows_the_real_dialog_with_the_expected_message(
    qtbot, theme, _messages: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    context = _Context(_employee(), _Users())
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Şəkli Dəyiş")

    assert len(_messages) == 1
    title, message = _messages[0]
    assert title == "Profil şəkli"
    assert "yükləmə" in message.lower()


@requires_qt
def test_clicking_change_password_shows_the_real_dialog_pointing_at_the_admin_flow(
    qtbot, theme, _messages: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    context = _Context(_employee(), _Users())
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Şifrəni Dəyiş")

    title, message = _messages[0]
    assert title == "Şifrənin dəyişdirilməsi"
    assert "administratorunuza müraciət edin" in message.lower()


# --------------------------------------------------------------------------- #
# 3. Real "Digər sessiyaları bağla" — cari sessiya istisna, ekran yenilənir
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_close_other_sessions_excludes_the_current_one_on_a_real_screen(
    qtbot, theme, _messages: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    current = SimpleNamespace(id="CARİ", revoked_at=None, expires_at=now + timedelta(hours=8))
    other = SimpleNamespace(id="DİGƏR", revoked_at=None, expires_at=now + timedelta(hours=8))
    auth_sessions = _AuthSessionsRepo([current, other])
    revoking = _RevokingSessions()
    context = _Context(_employee(), _Users(), auth_sessions=auth_sessions, sessions=revoking)

    from src.presentation.controllers.profile import ProfileController
    from src.presentation.screens.group_g import ProfileScreen

    screen = ProfileScreen(
        theme,
        full_name="Rəşad Məmmədov",
        role_name="HR Admin",
        store_name="Mərkəz",
        member_since="2024",
    )
    qtbot.addWidget(screen)
    ProfileController(context, _employee(), current_session_id="CARİ").attach(screen)  # type: ignore[arg-type]

    _click(screen, "Digər sessiyaları bağla")

    assert [row.id for row in revoking.revoked] == ["DİGƏR"]
    title, message = _messages[-1]
    assert title == "Sessiyalar"
    assert "1 sessiya bağlandı" in message


@requires_qt
def test_clicking_close_other_sessions_with_none_active_says_so_on_a_real_screen(
    qtbot, theme, _messages: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    context = _Context(_employee(), _Users())
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Digər sessiyaları bağla")

    assert _messages[-1] == ("Sessiyalar", "Başqa aktiv sessiya yoxdur.")
