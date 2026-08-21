"""`UsersScreen` ↔ `controllers/user_admin.py` + `controllers/user_lifecycle.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/user_admin.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi.

──────────────────────────────────────────────────────────────────────────────
DÜZƏLDİLDİ — DÖRD "···" MENYU MADDƏSİ İNDİ `UserLifecycleController`-Ə BAĞLIDIR
──────────────────────────────────────────────────────────────────────────────
İlkin sınaqda `UsersScreen.ACTIONS`-dakı `reset_pin`, `reset_password`,
`change_role`, `deactivate` bəndlərinin TAMAMİLƏ ÖLÜ olduğu tapıldı (bax
git tarixçəsi). `ui` yeni `controllers/user_lifecycle.py`
(`UserLifecycleController`) yazaraq bu dörd bəndi `UserManagementUseCase`-ə
bağladı VƏ `UsersScreen.set_permitted_actions()` + `screen_data.py::
_permitted_user_actions()` ilə "GÖRMƏK = SƏLAHİYYƏT" qapısını əlavə etdi —
icazəsi olmayan aktorda bənd menyuda RENDER OLUNMUR (boz DEYİL, YOXDUR).

Aşağıda İKİ QAT sınanır:
    1. `test_user_admin_controller_alone_does_not_handle_the_lifecycle_
       menu_actions` — `UserAdminController` TƏKBAŞINA bu dörd açarı
       DİNLƏMİR (bu, DOĞRU məhsul davranışıdır: həmin kontrollerin
       ƏHATƏSİ YALNIZ "Yeni İşçi"dir — `UserLifecycleController` AYRICA
       bağlanmalıdır, bax aşağıdakı `_build_lifecycle()`).
    2. `test_resetting_the_pin_via_the_real_dialog_...` və s. —
       `UserLifecycleController` REAL bağlanmış halda hər DÖRD bəndin REAL
       kliklə işlədiyini sübut edir.
    3. `test_*_action_is_absent_without_the_permission_flag` /
       `test_*_action_is_present_with_the_permission_flag` — `set_permitted_
       actions`/`_permitted_user_actions` qapısı hər bənd üçün AYRI-AYRI.

Strict Hierarchy Guard/Self-Escalation Guard `UserManagementUseCase`-in
İÇİNDƏDİR (`_assert_may_manage`/`_assert_not_self`) — bu fayl onları TƏKRAR
YAZMIR, YALNIZ istisnanın istifadəçiyə göstərildiyini sınayır (bax
`test_reset_pin_failure_shows_the_domain_message_and_does_not_commit` və
`test_assigning_a_position_above_the_actors_own_hierarchy_is_rejected_...`,
sonuncu "Yeni İşçi" axınından).

──────────────────────────────────────────────────────────────────────────────
FAKE ≠ REAL QAT — `change_role`-un icazə qapısı, TARİXİ QEYD
──────────────────────────────────────────────────────────────────────────────
`_permitted_user_actions()` `change_role`-u `can_manage_employees` VƏ
`can_manage_roles` FLAG-LƏRİNİN İKİSİNİ BİRDƏN tələb edir. Bu tapıntı əvvəlcə
`can_manage_roles`-un `permission_flags` reyestrində HEÇ olmadığını üzə
çıxarmışdı (`security`-ə göndərilmişdi) — bu, `migrations/077_manage_roles_
flag.sql` ilə DÜZƏLDİLİB: flag indi reyestrdə var və defolt olaraq YALNIZ
`ROOT`/`CEO` mövqelərinə verilir (Self-Escalation Guard-a tabe olaraq başqa
rola əl ilə əlavə oluna bilər). Aşağıdakı `test_change_role_action_is_
present_with_the_permission_flags` bu fayldakı FAKE `_Actor.has_permission()`
ilə DÜSTURU (iki flag = görünmə) ölçür — bu, artıq REAL sistem vəziyyətinə
UYĞUNDUR, sadəcə fake-in özü `permission_flags` reyestrini SORĞULAMIR (REAL
`Employee.has_permission()` `granted_by`/hardlock zəncirindən keçir, fake isə
birbaşa `frozenset` üzvlüyünə baxır) — nəticə eynidir, YOL fərqlidir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
POSITION_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()


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


def _user_row(full_name: str = "Aygün Məmmədova") -> dict[str, str]:
    return {"full_name": full_name, "username": "aygun.m", "role": "Satıcı", "store": "Mərkəz"}


def _trigger_menu_action(screen: Any, label: str) -> None:
    from PySide6.QtWidgets import QPushButton

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    menu = ellipsis.menu()
    action = next(a for a in menu.actions() if a.text() == label)
    action.trigger()


def _position(*, position_id: Any = POSITION_ID, name_az: str = "Satıcı") -> Any:
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import RolePriority

    return Position(
        position_id=position_id,
        code="SELLER",
        name_az=name_az,
        priority=RolePriority.STAFF,
        tenant_id=TENANT,
        is_camera_type=False,
    )


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    """SQL-i FİNGERPRİNT-ə görə yönləndirən sahtə — mağaza VƏ işçi axtarışı
    EYNİ `session.uow.connection.execute(...)` interfeysindən keçir."""

    def __init__(self, stores: dict[str, str], employees: list[tuple[Any, str, str]]) -> None:
        self._stores = stores
        self._employees = employees
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _Connection:
        self._last_sql = sql
        return self

    def fetchall(self) -> list[_Row]:
        if "FROM employees" in self._last_sql:
            return [
                _Row(id=eid, first_name=first, last_name=last)
                for eid, first, last in self._employees
            ]
        return [_Row(id=sid, name=name) for sid, name in self._stores.items()]


class _PositionsRepo:
    def __init__(self, positions: list[Any]) -> None:
        self._positions = positions

    def list_for_tenant(self, _tenant_id: Any) -> list[Any]:
        return list(self._positions)

    def get(self, position_id: Any) -> Any:
        return next((p for p in self._positions if p.id == position_id), None)


class _FakeEmployee:
    """`Employee`-in yerini tutur — `_change_role` YALNIZ bu atributları oxuyur."""

    def __init__(
        self,
        *,
        position: Any,
        first_name: str = "Aygün",
        last_name: str = "Məmmədova",
        store_id: Any = None,
        assigned_store_ids: tuple[Any, ...] = (),
    ) -> None:
        self.position = position
        self.first_name = first_name
        self.last_name = last_name
        self.store_id = store_id
        self.notification_email = None
        self.hire_date = None
        self.date_of_birth = None
        self.profile_photo_url = None
        self.assigned_store_ids = assigned_store_ids


class _EmployeesRepo:
    def __init__(self, employee: Any) -> None:
        self._employee = employee

    def get(self, _employee_id: Any) -> Any:
        return self._employee


class _Uow:
    def __init__(
        self,
        stores: dict[str, str],
        positions: list[Any],
        employee: Any,
        employee_rows: list[tuple[Any, str, str]],
    ) -> None:
        self.connection = _Connection(stores, employee_rows)
        self.positions = _PositionsRepo(positions)
        self.employees = _EmployeesRepo(employee)


class _Users:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.create_error: KompasOSError | None = None
        self.reset_pin_calls: list[dict[str, Any]] = []
        self.reset_pin_error: KompasOSError | None = None
        self.reset_password_calls: list[dict[str, Any]] = []
        self.reset_password_error: KompasOSError | None = None
        self.update_calls: list[dict[str, Any]] = []
        self.update_error: KompasOSError | None = None
        self.deactivate_calls: list[dict[str, Any]] = []
        self.deactivate_error: KompasOSError | None = None

    def create_employee(self, **kwargs: Any) -> Any:
        if self.create_error is not None:
            raise self.create_error
        self.created.append(kwargs)
        return type("_Employee", (), {"id": kwargs.get("employee_id")})()

    def reset_pin(self, **kwargs: Any) -> None:
        if self.reset_pin_error is not None:
            raise self.reset_pin_error
        self.reset_pin_calls.append(kwargs)

    def reset_password(self, **kwargs: Any) -> None:
        if self.reset_password_error is not None:
            raise self.reset_password_error
        self.reset_password_calls.append(kwargs)

    def update_employee(self, **kwargs: Any) -> None:
        if self.update_error is not None:
            raise self.update_error
        self.update_calls.append(kwargs)

    def deactivate_employee(self, **kwargs: Any) -> None:
        if self.deactivate_error is not None:
            raise self.deactivate_error
        self.deactivate_calls.append(kwargs)


class _Session:
    def __init__(
        self,
        stores: dict[str, str],
        positions: list[Any],
        employee: Any,
        employee_rows: list[tuple[Any, str, str]],
        users: _Users,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(stores, positions, employee, employee_rows)
        self.users = users
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(
        self,
        *,
        stores: dict[str, str] | None = None,
        positions: list[Any] | None = None,
        employee: Any = None,
        employee_rows: list[tuple[Any, str, str]] | None = None,
    ) -> None:
        self._stores = stores if stores is not None else {str(STORE_ID): "Mərkəz"}
        self._positions = positions if positions is not None else [_position()]
        self._employee = employee if employee is not None else _FakeEmployee(position=_position())
        # `_find_employee_id` (`user_lifecycle.py`/`user_admin.py`/`pos_threshold.py`)
        # `UsersScreen`-in göstərdiyi ADA görə axtarır — sətir `_user_row()`-un
        # defolt adı ilə UYĞUN olmalıdır, əks halda hər üç kontroller "İşçi
        # tapılmadı" deyər.
        self._employee_rows = (
            employee_rows if employee_rows is not None else [(EMPLOYEE_ID, "Aygün", "Məmmədova")]
        )
        self.users = _Users()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            self._stores, self._positions, self._employee, self._employee_rows, self.users
        )
        self.sessions.append(created)
        yield created


class _Actor:
    """`flags` YALNIZ `_permitted_user_actions()` testlərində istifadə olunur
    (bax modul başlığındakı "FAKE ≠ REAL QAT" qeydi) — digər testlərdə
    `has_permission()` heç çağırılmır, çünki fakes bu faylda öz-özünə
    icazə yoxlaması APARMIR (real qapı use case-in içindədir)."""

    def __init__(self, flags: frozenset[str] = frozenset()) -> None:
        self.id = ACTOR_ID
        self._flags = flags

    def has_permission(self, flag: str, *, now: Any) -> bool:
        return flag in self._flags


class _Binder:
    populated: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers import screen_data as screen_data_module

    _Binder.populated = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)


def _build(theme: Any, qtbot: Any, context: Any) -> Any:
    from src.presentation.controllers.user_admin import UserAdminController
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_users([_user_row()])
    UserAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


def _build_lifecycle(theme: Any, qtbot: Any, context: Any, *, actor: Any = None) -> Any:
    """`UserLifecycleController`-i REAL bağlayır — dörd bəndin (PIN/şifrə/rol/
    deaktivasiya) sınağı BUNDAN keçir, `UserAdminController`-dən DEYİL."""
    from src.presentation.controllers.user_lifecycle import UserLifecycleController
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_users([_user_row()])
    UserLifecycleController(context, actor or _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


def _patched_dialog_exec(
    monkeypatch: pytest.MonkeyPatch,
    *,
    first_name: str = "Kamran",
    last_name: str = "Əliyev",
    pin: str = "1234",
    username: str = "",
    password: str = "",
    hire_date: str = "",
) -> None:
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import NewUserDialog

    def fake_exec(self: NewUserDialog) -> int:
        self._first_name.set_text(first_name)
        self._last_name.set_text(last_name)
        self._pin.set_text(pin)
        self._username.set_text(username)
        self._password.set_text(password)
        self._hire_date.set_text(hire_date)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yarat")
        submit.click()
        return 0

    monkeypatch.setattr(NewUserDialog, "exec", fake_exec)


# --------------------------------------------------------------------------- #
# 1. `UserAdminController` TƏKBAŞINA — dörd bənd onun ƏHATƏSİNDƏN KƏNARDIR
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("label", ["PIN Sıfırla", "Şifrəni Yenilə", "Rolu Dəyiş", "Deaktiv Et"])
def test_user_admin_controller_alone_does_not_handle_the_lifecycle_menu_actions(
    qtbot, theme, label: str
) -> None:  # type: ignore[no-untyped-def]
    """`UserAdminController`-in ƏHATƏSİ YALNIZ "Yeni İşçi"dir — DOĞRU ayrılıqdır.

    Bu, artıq "ölü düymə" TAPINTISI DEYİL: dörd bənd indi `UserLifecycleController`-ə
    bağlıdır (bax `test_resetting_the_pin_via_the_real_dialog_...` və s. aşağıda,
    həmçinin faylın başlığı). Burada YALNIZ `UserAdminController`-in ÖZÜNÜN bu
    açarları dinləmədiyi — yəni sahə ayrılığının POZULMADIĞI — yoxlanılır.
    """
    from src.presentation.controllers.user_admin import UserAdminController

    context = _Context()
    screen = _build(theme, qtbot, context)
    UserAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # heç nə dəyişmir

    _trigger_menu_action(screen, label)  # ÇÖKMƏMƏLİDİR

    assert context.users.created == []
    assert screen.switcher().current_state() == "content", (
        f'"{label}" `UserAdminController`-ə aid DEYİL — kontroller bu açarı dinləmir '
        "(bu, DOĞRUdur, `UserLifecycleController` ayrıca bağlanmalıdır)."
    )


# --------------------------------------------------------------------------- #
# 2. Real "Yeni İşçi" — uğur, dialoqun öz validasiyası
# --------------------------------------------------------------------------- #


@requires_qt
def test_creating_an_employee_via_the_real_dialog_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build(theme, qtbot, context)
    _patched_dialog_exec(monkeypatch, first_name="Kamran", last_name="Əliyev", pin="4321")

    _click(screen, "Yeni İşçi")

    assert len(context.users.created) == 1
    draft = context.users.created[0]["draft"]
    assert draft.first_name == "Kamran"
    assert draft.last_name == "Əliyev"
    assert any(s.committed for s in context.sessions)
    assert "users" in _Binder.populated


@requires_qt
def test_missing_position_is_rejected_by_the_real_dialog_before_any_write(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Boş kataloqla açılan forma «Yarat»-a icazə vermir (real widget validasiyası)."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import NewUserDialog

    context = _Context(positions=[_position()])
    screen = _build(theme, qtbot, context)

    def fake_exec(self: NewUserDialog) -> int:
        self._first_name.set_text("Kamran")
        self._last_name.set_text("Əliyev")
        self._pin.set_text("1234")
        combo = self._position.input_widget()
        combo.setCurrentIndex(-1)  # HEÇ NƏ seçilməyib
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yarat")
        submit.click()
        return self.reject()

    monkeypatch.setattr(NewUserDialog, "exec", fake_exec)

    _click(screen, "Yeni İşçi")

    assert context.users.created == []


@requires_qt
def test_username_without_password_is_rejected_by_the_real_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build(theme, qtbot, context)
    _patched_dialog_exec(monkeypatch, pin="", username="kamran.e", password="")

    _click(screen, "Yeni İşçi")

    assert context.users.created == []


@requires_qt
def test_no_authentication_method_is_rejected_by_the_real_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Nə PIN, nə istifadəçi adı — real klik forma qapısında dayanır."""
    context = _Context()
    screen = _build(theme, qtbot, context)
    _patched_dialog_exec(monkeypatch, pin="", username="", password="")

    _click(screen, "Yeni İşçi")

    assert context.users.created == []


@requires_qt
def test_no_positions_available_shows_a_real_error_and_does_not_open_the_dialog(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    context = _Context(positions=[])
    screen = _build(theme, qtbot, context)

    _click(screen, "Yeni İşçi")  # ÇÖKMƏMƏLİDİR

    assert context.users.created == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 3. Strict Hierarchy Guard, malformed data, ekstremal mətn — çökmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_assigning_a_position_above_the_actors_own_hierarchy_is_rejected_with_a_real_modal(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Strict Hierarchy Guard (`_assert_may_assign_position`) — real klik AÇIQ modal göstərir,
    formanı SÜKUTLA udmur, commit etmir."""
    context = _Context()
    context.users.create_error = KompasOSError(
        "hierarchy violation",
        user_message="Öz pillənizdən yüksək bir vəzifə təyin edə bilməzsiniz.",
    )
    screen = _build(theme, qtbot, context)

    shown: list[tuple[str, str]] = []
    from src.presentation.controllers import user_admin as user_admin_module

    monkeypatch.setattr(
        user_admin_module,
        "_inform",
        lambda _screen, title, message: shown.append((title, message)),
    )
    _patched_dialog_exec(monkeypatch)

    _click(screen, "Yeni İşçi")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert shown == [
        ("İşçi yaradılmadı", "Öz pillənizdən yüksək bir vəzifə təyin edə bilməzsiniz.")
    ]


@requires_qt
def test_a_malformed_hire_date_shows_a_real_error_and_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers import user_admin as user_admin_module

    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        user_admin_module,
        "_inform",
        lambda _screen, title, message: shown.append((title, message)),
    )
    context = _Context()
    screen = _build(theme, qtbot, context)
    _patched_dialog_exec(monkeypatch, hire_date="12.08.2026")  # ISO deyil

    _click(screen, "Yeni İşçi")  # ÇÖKMƏMƏLİDİR

    assert context.users.created == []
    assert shown, "Yanlış tarix formatı AÇIQ mesajla göstərilməli idi"


@requires_qt
def test_hostile_and_extreme_names_pass_through_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build(theme, qtbot, context)
    hostile = "'; DROP TABLE employees; -- 🔥" + "A" * 10_000
    _patched_dialog_exec(monkeypatch, first_name=hostile, last_name="Əliyev")

    _click(screen, "Yeni İşçi")  # ÇÖKMƏMƏLİDİR

    assert len(context.users.created) == 1
    assert context.users.created[0]["draft"].first_name == hostile


# --------------------------------------------------------------------------- #
# 4. `UserLifecycleController` — real "PIN Sıfırla" / "Şifrəni Yenilə" /
#    "Rolu Dəyiş" / "Deaktiv Et"
# --------------------------------------------------------------------------- #
#
# MODAL TƏHLÜKƏSİ: `ResetPinDialog`/`ResetPasswordDialog`/`ChangeRoleDialog`
# REAL `QDialog.exec()` çağırır — mock edilməzsə headless testdə proses
# ƏBƏDİ DONA bilər (test QIRMIZI olmaz, DONAR). Hər üçü aşağıda
# `AnnouncementComposeDialog`/`NewUserDialog` ilə EYNİ "patched-exec" trikini
# işlədir (real sahə doldurma + real düymə kliki, YALNIZ blok edən `exec()`
# əvəz olunur). `deactivate` isə `QInputDialog.getMultiLineText` işlədir —
# `camera_queue.py`/`open_shift.py` testlərindəki EYNİ naxış.


def _patched_reset_pin_exec(monkeypatch: pytest.MonkeyPatch, *, pin: str = "4321") -> None:
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import ResetPinDialog

    def fake_exec(self: ResetPinDialog) -> int:
        self._pin.set_text(pin)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sıfırla")
        submit.click()
        return 0

    monkeypatch.setattr(ResetPinDialog, "exec", fake_exec)


def _patched_reset_password_exec(
    monkeypatch: pytest.MonkeyPatch,
    *,
    password: str = "Yeni-Sifre-2026",  # noqa: S107 — test sahtəsi, real sirr deyil
) -> None:
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import ResetPasswordDialog

    def fake_exec(self: ResetPasswordDialog) -> int:
        self._password.set_text(password)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yenilə")
        submit.click()
        return 0

    monkeypatch.setattr(ResetPasswordDialog, "exec", fake_exec)


def _patched_change_role_exec(monkeypatch: pytest.MonkeyPatch, *, position_id: Any) -> None:
    from PySide6.QtWidgets import QComboBox, QPushButton

    from src.presentation.screens.group_c import ChangeRoleDialog

    def fake_exec(self: ChangeRoleDialog) -> int:
        combo = self._position.input_widget()
        assert isinstance(combo, QComboBox)
        index = combo.findData(str(position_id))
        assert index >= 0
        combo.setCurrentIndex(index)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Dəyiş")
        submit.click()
        return 0

    monkeypatch.setattr(ChangeRoleDialog, "exec", fake_exec)


@requires_qt
def test_resetting_the_pin_via_the_real_dialog_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build_lifecycle(theme, qtbot, context)
    _patched_reset_pin_exec(monkeypatch, pin="9999")

    _trigger_menu_action(screen, "PIN Sıfırla")

    assert len(context.users.reset_pin_calls) == 1
    assert context.users.reset_pin_calls[0]["new_pin"] == "9999"
    assert any(s.committed for s in context.sessions)
    assert "users" in _Binder.populated


@requires_qt
def test_an_empty_pin_is_rejected_by_the_real_dialog_before_any_write(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import ResetPinDialog

    context = _Context()
    screen = _build_lifecycle(theme, qtbot, context)

    def fake_exec(self: ResetPinDialog) -> int:
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sıfırla")
        submit.click()  # PIN BOŞ
        assert self._pin.has_error
        return self.reject()

    monkeypatch.setattr(ResetPinDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "PIN Sıfırla")

    assert context.users.reset_pin_calls == []


@requires_qt
def test_reset_pin_failure_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Strict Hierarchy Guard rəddi (`_assert_may_manage`) — real klik AÇIQ mesaj göstərir."""
    context = _Context()
    context.users.reset_pin_error = KompasOSError(
        "hierarchy violation", user_message="Bu işçiyə toxunmaq səlahiyyətiniz yoxdur."
    )
    screen = _build_lifecycle(theme, qtbot, context)
    _patched_reset_pin_exec(monkeypatch)

    _trigger_menu_action(screen, "PIN Sıfırla")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_reset_pin_for_a_deleted_employee_shows_a_real_error(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """İşçi BAZADA silinib/deaktiv edilib, LAKİN ekranda hələ görünür (köhnəlmiş
    keş) — `_find_employee_id` `None` qaytarır, real klik ÇÖKMƏMƏLİDİR."""
    context = _Context(employee_rows=[])  # DB-də artıq bu adda sətir YOXDUR
    screen = _build_lifecycle(theme, qtbot, context)  # ekran hələ KÖHNƏ sətri göstərir
    _patched_reset_pin_exec(monkeypatch)

    _trigger_menu_action(screen, "PIN Sıfırla")  # ÇÖKMƏMƏLİDİR

    assert context.users.reset_pin_calls == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_resetting_the_password_via_the_real_dialog_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build_lifecycle(theme, qtbot, context)
    _patched_reset_password_exec(monkeypatch, password="Kamran#2026Yeni")

    _trigger_menu_action(screen, "Şifrəni Yenilə")

    assert len(context.users.reset_password_calls) == 1
    assert context.users.reset_password_calls[0]["new_password"] == "Kamran#2026Yeni"
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_an_empty_password_is_rejected_by_the_real_dialog_before_any_write(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import ResetPasswordDialog

    context = _Context()
    screen = _build_lifecycle(theme, qtbot, context)

    def fake_exec(self: ResetPasswordDialog) -> int:
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yenilə")
        submit.click()  # şifrə BOŞ
        assert self._password.has_error
        return self.reject()

    monkeypatch.setattr(ResetPasswordDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Şifrəni Yenilə")

    assert context.users.reset_password_calls == []


@requires_qt
def test_changing_the_role_via_the_real_dialog_preserves_the_employees_other_fields(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_change_role` mövcud işçini YÜKLƏYİR, YALNIZ `position`-u əvəzləyir (modul başlığı)."""
    new_position = _position(position_id=uuid.uuid4(), name_az="Mağaza Meneceri")
    old_position = _position()
    employee = _FakeEmployee(position=old_position, first_name="Aygün", last_name="Məmmədova")
    context = _Context(positions=[old_position, new_position], employee=employee)
    screen = _build_lifecycle(theme, qtbot, context)
    _patched_change_role_exec(monkeypatch, position_id=new_position.id)

    _trigger_menu_action(screen, "Rolu Dəyiş")

    assert len(context.users.update_calls) == 1
    draft = context.users.update_calls[0]["draft"]
    assert draft.position is new_position
    assert draft.first_name == "Aygün"
    assert draft.last_name == "Məmmədova"
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_change_role_without_a_selection_is_rejected_by_the_real_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import ChangeRoleDialog

    context = _Context()
    screen = _build_lifecycle(theme, qtbot, context)

    def fake_exec(self: ChangeRoleDialog) -> int:
        self.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
        combo = self._position.input_widget()
        combo.setCurrentIndex(-1)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Dəyiş")
        submit.click()
        assert self._error.isVisible()
        return self.reject()

    monkeypatch.setattr(ChangeRoleDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Rolu Dəyiş")

    assert context.users.update_calls == []


@requires_qt
def test_change_role_failure_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Self-Escalation Guard (`_assert_not_self`) rəddi — real klik AÇIQ mesaj göstərir."""
    new_position = _position(position_id=uuid.uuid4(), name_az="Admin")
    context = _Context(positions=[_position(), new_position])
    context.users.update_error = KompasOSError(
        "self escalation", user_message="Özünüzə yüksək rol təyin edə bilməzsiniz."
    )
    screen = _build_lifecycle(theme, qtbot, context)
    _patched_change_role_exec(monkeypatch, position_id=new_position.id)

    _trigger_menu_action(screen, "Rolu Dəyiş")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_deactivating_via_the_real_reason_prompt_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("İşdən öz istəyi ilə ayrıldı", True)),
    )
    context = _Context()
    screen = _build_lifecycle(theme, qtbot, context)

    _trigger_menu_action(screen, "Deaktiv Et")

    assert len(context.users.deactivate_calls) == 1
    assert context.users.deactivate_calls[0]["reason"] == "İşdən öz istəyi ilə ayrıldı"
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_declining_the_deactivate_reason_prompt_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))
    context = _Context()
    screen = _build_lifecycle(theme, qtbot, context)

    _trigger_menu_action(screen, "Deaktiv Et")

    assert context.users.deactivate_calls == []


@requires_qt
def test_deactivate_failure_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("səbəb burada", True))
    )
    context = _Context()
    context.users.deactivate_error = KompasOSError(
        "hierarchy violation", user_message="Bu işçiyə toxunmaq səlahiyyətiniz yoxdur."
    )
    screen = _build_lifecycle(theme, qtbot, context)

    _trigger_menu_action(screen, "Deaktiv Et")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 5. "GÖRMƏK = SƏLAHİYYƏT" — `set_permitted_actions`/`_permitted_user_actions`
# --------------------------------------------------------------------------- #


@requires_qt
def test_reset_pin_action_is_absent_without_the_permission_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(_permitted_user_actions(_Actor()))  # flag-siz
    screen.set_users([_user_row()])

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "PIN Sıfırla" not in labels


@requires_qt
def test_reset_pin_action_is_present_with_the_permission_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.application.use_cases.user_management import RESET_PIN_FLAG
    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(_permitted_user_actions(_Actor(frozenset({RESET_PIN_FLAG}))))
    screen.set_users([_user_row()])

    from PySide6.QtWidgets import QPushButton

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "PIN Sıfırla" in labels


@requires_qt
def test_reset_password_action_is_absent_without_the_permission_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(_permitted_user_actions(_Actor()))
    screen.set_users([_user_row()])

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "Şifrəni Yenilə" not in labels


@requires_qt
def test_reset_password_action_is_present_with_the_permission_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.application.use_cases.user_management import RESET_PASSWORD_FLAG
    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(_permitted_user_actions(_Actor(frozenset({RESET_PASSWORD_FLAG}))))
    screen.set_users([_user_row()])

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "Şifrəni Yenilə" in labels


@requires_qt
def test_deactivate_action_is_absent_without_the_permission_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(_permitted_user_actions(_Actor()))
    screen.set_users([_user_row()])

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "Deaktiv Et" not in labels


@requires_qt
def test_deactivate_action_is_present_with_the_permission_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.application.use_cases.user_management import MANAGE_EMPLOYEES_FLAG
    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(
        _permitted_user_actions(_Actor(frozenset({MANAGE_EMPLOYEES_FLAG})))
    )
    screen.set_users([_user_row()])

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "Deaktiv Et" in labels


@requires_qt
def test_change_role_action_is_absent_with_only_one_of_the_two_required_flags(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`change_role` İKİ flag tələb edir (`MANAGE_EMPLOYEES_FLAG` + `MANAGE_ROLES_FLAG`) —
    yalnız birini daşımaq KİFAYƏT ETMİR (modul başlığındakı "iki flag = görünmə" düsturu)."""
    from PySide6.QtWidgets import QPushButton

    from src.application.use_cases.user_management import MANAGE_EMPLOYEES_FLAG
    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(
        _permitted_user_actions(_Actor(frozenset({MANAGE_EMPLOYEES_FLAG})))
    )
    screen.set_users([_user_row()])

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "Rolu Dəyiş" not in labels


@requires_qt
def test_change_role_action_is_present_with_the_permission_flags(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Real sistemdə bu iki flag-i BİRGƏ YALNIZ ROOT/CEO daşıyır defolt olaraq
    (`migrations/077_manage_roles_flag.sql`) — bax modul başlığındakı qeyd."""
    from PySide6.QtWidgets import QPushButton

    from src.application.use_cases.user_management import MANAGE_EMPLOYEES_FLAG, MANAGE_ROLES_FLAG
    from src.presentation.controllers.screen_data import _permitted_user_actions
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_permitted_actions(
        _permitted_user_actions(_Actor(frozenset({MANAGE_EMPLOYEES_FLAG, MANAGE_ROLES_FLAG})))
    )
    screen.set_users([_user_row()])

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    labels = [a.text() for a in ellipsis.menu().actions()]
    assert "Rolu Dəyiş" in labels
