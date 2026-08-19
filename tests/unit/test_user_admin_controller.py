"""`UserAdminController` yazı yolu (`controllers/user_admin.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
`UsersScreen`-in "Yeni İşçi" düyməsi `create_requested` yayırdı, lakin heç bir
kontroller onu dinləmirdi — GUI-dan tək-tək işçi yaratmağın yolu YOX İDİ
(yalnız CSV toplu idxalı işləyirdi). `UserManagementUseCase.create_employee`
isə tam işlək idi.

Burada use case-in ÖZÜ (anti-fraud vəzifə ayrılığı, `_assert_may_assign_
position`, `chk_employee_auth` invariantı) TƏKRAR yoxlanmır — o, `test_use_
cases.py`/`test_entities.py`-nin işidir. Ölçülən YALNIZ kontrollerin öz
məsuliyyətidir: xam sözlüyü DOMEN tiplərinə düzgün çevirmək, yararsız
sahədə sessiya AÇMADAN dayanmaq, uğursuz yazıda `commit()`-i çağırmamaq və
YALNIZ uğurda siyahını yenidən oxumaq.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.domain.entities.position import Position
from src.domain.value_objects.authorization import RolePriority
from src.domain.value_objects.identifiers import PositionId, StoreId, TenantId
from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers import user_admin as user_admin_module
from src.presentation.controllers.user_admin import UserAdminController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = uuid.uuid4()
CAMERA_STORE = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Signal:
    """`Signal.connect(...)` + `emit(...)` — Qt olmadan."""

    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, *args: Any) -> None:
        for slot in self._slots:
            slot(*args)

    @property
    def connected(self) -> bool:
        return bool(self._slots)


class _Screen:
    """Minimal `UsersScreen` əvəzi."""

    def __init__(self) -> None:
        self.create_requested = _Signal()
        self.theme = object()
        self.errors: list[tuple[str, str]] = []
        self.retries: list[Any] = []

    def show_error(self, *, title: str, message: str, on_retry: Any = None, **_: Any) -> None:
        self.errors.append((title, message))
        self.retries.append(on_retry)


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Connection:
    """`session.uow.connection` — `_store_choices`-in xam sorğusu üçün."""

    def __init__(self, stores: list[dict[str, Any]]) -> None:
        self._stores = stores

    def execute(self, _sql: str, _params: Any = None) -> _Cursor:
        return _Cursor(self._stores)


class _Positions:
    """`session.uow.positions` — `PositionRepository` sahtəsi."""

    def __init__(self, positions: list[Position]) -> None:
        self._by_id = {p.id: p for p in positions}
        self._tenant = list(positions)

    def get(self, position_id: PositionId) -> Position | None:
        return self._by_id.get(position_id)

    def list_for_tenant(self, _tenant_id: Any) -> list[Position]:
        return list(self._tenant)


class _Uow:
    def __init__(self, *, connection: _Connection, positions: _Positions) -> None:
        self.connection = connection
        self.positions = positions


class _Users:
    """`session.users` — `UserManagementUseCase` sahtəsi (YALNIZ `create_employee`)."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self._failure = failure
        self.created: list[dict[str, Any]] = []

    def create_employee(self, **kwargs: Any) -> Any:
        if self._failure is not None:
            raise self._failure
        self.created.append(kwargs)
        return object()


class _Session:
    def __init__(self, *, uow: _Uow, users: _Users) -> None:
        self.tenant_id = TENANT
        self.uow = uow
        self.users = users
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    """Hər `with` YENİ sessiya açır (CLAUDE.md §6: kontroller sessiyanı SAXLAMIR)."""

    def __init__(
        self,
        *,
        stores: list[dict[str, Any]] | None = None,
        positions: list[Position] | None = None,
        users_failure: Exception | None = None,
        open_failure: Exception | None = None,
    ) -> None:
        self._connection = _Connection(stores or [])
        self._positions = _Positions(positions or [])
        self._users = _Users(failure=users_failure)
        self._open_failure = open_failure
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        if self._open_failure is not None:
            raise self._open_failure
        created = _Session(
            uow=_Uow(connection=self._connection, positions=self._positions), users=self._users
        )
        self.sessions.append(created)
        yield created


class _Actor:
    id = uuid.uuid4()


class _Binder:
    """Sahtə `ScreenDataBinder` — `refresh()` çağırılıbmı."""

    populated: ClassVar[list[str]] = []
    failure: ClassVar[Exception | None] = None

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        if _Binder.failure is not None:
            raise _Binder.failure
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Binder-i və modalı sahtələ — Qt bu testlərdə qalxmır."""
    _Binder.populated = []
    _Binder.failure = None
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        user_admin_module, "_inform", lambda _screen, title, message: shown.append((title, message))
    )
    return shown


def _position(
    *, camera: bool = False, active: bool = True, priority: RolePriority = RolePriority.OPERATIONAL
) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code="KAMERA_NƏZARƏTÇİSİ" if camera else "SATICI",
        name_az="Kamera Nəzarətçisi" if camera else "Satıcı",
        priority=priority,
        tenant_id=TENANT,
        is_camera_type=camera,
        is_active=active,
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "first_name": "Aysel",
        "last_name": "Məmmədova",
        "position_id": "",
        "store_id": "",
        "username": "",
        "password": "",
        "pin": "1234",
        "notification_email": "",
        "hire_date": "",
        "date_of_birth": "",
        "camera_store_ids": [],
    }
    base.update(overrides)
    return base


def _build(**context_kwargs: Any) -> tuple[UserAdminController, _Screen, _Context]:
    context = _Context(**context_kwargs)
    controller = UserAdminController(context, _Actor())  # type: ignore[arg-type]
    screen = _Screen()
    controller.attach(screen)  # type: ignore[arg-type]
    return controller, screen, context


# --------------------------------------------------------------------------- #
# Bağlantı
# --------------------------------------------------------------------------- #


def test_attach_connects_the_create_signal() -> None:
    """Qüsurun ÖZÜ: `create_requested`-i heç bir kontroller dinləmirdi."""
    _, screen, _ = _build()

    assert screen.create_requested.connected


# --------------------------------------------------------------------------- #
# (a) forma use case-ə düzgün `EmployeeDraft` ötürür
# --------------------------------------------------------------------------- #


def test_create_passes_a_correctly_built_employee_draft() -> None:
    position = _position()
    controller, screen, context = _build(
        stores=[{"id": STORE, "name": "Mərkəz"}], positions=[position]
    )

    controller._create(
        screen,  # type: ignore[arg-type]
        _payload(
            position_id=str(position.id),
            store_id=str(STORE),
            username="aysel.m",
            password="Kompas123!",
            pin="",
            notification_email="aysel@example.com",
            hire_date="2026-01-15",
        ),
    )

    assert len(context._users.created) == 1
    call = context._users.created[0]
    draft = call["draft"]
    assert draft.first_name == "Aysel"
    assert draft.last_name == "Məmmədova"
    assert draft.position is position
    assert draft.store_id == StoreId(STORE)
    assert draft.username.value == "aysel.m"
    assert draft.notification_email.value == "aysel@example.com"
    assert draft.hire_date.isoformat() == "2026-01-15"
    assert call["initial_password"] == "Kompas123!"
    assert call["initial_pin"] is None
    assert call["tenant_id"] == TENANT
    assert context.sessions[0].committed is True
    assert _Binder.populated == ["users"]


def test_create_with_pin_only_omits_username_and_password() -> None:
    position = _position()
    controller, screen, context = _build(positions=[position])

    controller._create(
        screen,  # type: ignore[arg-type]
        _payload(position_id=str(position.id), pin="4821"),
    )

    call = context._users.created[0]
    assert call["initial_pin"] == "4821"
    assert call["initial_password"] is None
    assert call["draft"].username is None


# --------------------------------------------------------------------------- #
# (b) yararsız/məcburi sahə sessiya AÇMADAN dayandırılır
# --------------------------------------------------------------------------- #


def test_an_unusable_position_id_never_opens_a_session(_isolate: list[tuple[str, str]]) -> None:
    """Boş/yararsız `position_id` — `PositionId(UUID(""))` `ValueError` atır."""
    controller, screen, context = _build()

    controller._create(screen, _payload(position_id=""))  # type: ignore[arg-type]

    assert context.sessions == []
    assert len(_isolate) == 1


def test_an_invalid_hire_date_never_opens_a_session(_isolate: list[tuple[str, str]]) -> None:
    position = _position()
    controller, screen, context = _build(positions=[position])

    controller._create(
        screen,  # type: ignore[arg-type]
        _payload(position_id=str(position.id), hire_date="15/01/2026"),
    )

    assert context.sessions == []
    assert len(_isolate) == 1
    assert user_admin_module.DATE_FORMAT_MESSAGE in _isolate[0][1]


def test_a_malformed_username_is_reported_before_writing(_isolate: list[tuple[str, str]]) -> None:
    """`Username(...)` domendə formatı yoxlayır — kontroller onu TƏKRARLAMIR, tutur."""
    position = _position()
    controller, screen, context = _build(positions=[position])

    controller._create(
        screen,  # type: ignore[arg-type]
        _payload(position_id=str(position.id), username="!", password="Kompas123!", pin=""),
    )

    assert context.sessions == []
    assert len(_isolate) == 1


def test_a_position_missing_at_write_time_is_reported(_isolate: list[tuple[str, str]]) -> None:
    """Dialoq açıq qalarkən vəzifə silinib — `session.uow.positions.get` `None` qaytarır."""
    position = _position()
    controller, screen, context = _build(positions=[])  # repository ARTIQ boşdur

    controller._create(screen, _payload(position_id=str(position.id)))  # type: ignore[arg-type]

    assert context.sessions[0].committed is False
    assert context._users.created == []
    assert len(_isolate) == 1


# --------------------------------------------------------------------------- #
# (c) uğursuz yazıda commit olmur və siyahı YENİDƏN oxunmur
# --------------------------------------------------------------------------- #


def test_use_case_failure_skips_commit_and_the_reread(_isolate: list[tuple[str, str]]) -> None:
    position = _position()
    failure = KompasOSError("icazə yoxdur", user_message="Bu əməliyyat üçün icazəniz yoxdur.")
    controller, screen, context = _build(positions=[position], users_failure=failure)

    controller._create(screen, _payload(position_id=str(position.id)))  # type: ignore[arg-type]

    assert context.sessions[0].committed is False
    assert _Binder.populated == []
    assert screen.errors == [], "yazı xətası `show_error` DEYİL, modaldır (fine_appeals.py qərarı)"
    assert _isolate == [("İşçi yaradılmadı", "Bu əməliyyat üçün icazəniz yoxdur.")]


def test_an_unexpected_exception_is_not_silently_swallowed(
    _isolate: list[tuple[str, str]],
) -> None:
    position = _position()
    controller, screen, context = _build(positions=[position], users_failure=RuntimeError("boom"))

    controller._create(screen, _payload(position_id=str(position.id)))  # type: ignore[arg-type]

    assert context.sessions[0].committed is False
    assert _Binder.populated == []
    assert len(_isolate) == 1


# --------------------------------------------------------------------------- #
# (d) kamera vəzifəsində çox-seçimli mağaza siyahısı ötürülür
# --------------------------------------------------------------------------- #


def test_camera_role_forwards_the_multi_store_selection() -> None:
    camera_position = _position(camera=True)
    controller, screen, context = _build(positions=[camera_position])

    controller._create(
        screen,  # type: ignore[arg-type]
        _payload(
            position_id=str(camera_position.id),
            camera_store_ids=[str(STORE), str(CAMERA_STORE)],
        ),
    )

    draft = context._users.created[0]["draft"]
    assert set(draft.camera_store_ids) == {StoreId(STORE), StoreId(CAMERA_STORE)}


def test_non_camera_role_still_creates_the_employee_when_no_stores_are_selected() -> None:
    """Kamera olmayan roldan boş siyahı gəlir — `_apply_camera_stores` bunu qəbul edir."""
    position = _position(camera=False)
    controller, screen, context = _build(positions=[position])

    controller._create(
        screen,  # type: ignore[arg-type]
        _payload(position_id=str(position.id), camera_store_ids=[]),
    )

    assert len(context._users.created) == 1
    assert context._users.created[0]["draft"].camera_store_ids == ()


# --------------------------------------------------------------------------- #
# Dialoqun açılışı — mağaza/vəzifə siyahısının OXUNMASI
# --------------------------------------------------------------------------- #


def test_dialog_data_load_failure_shows_an_error_without_wiping_the_table() -> None:
    """Oxu xətası `show_error` ilədir — burada siyahı hələ AÇILMAYIB, itki yoxdur."""
    _, screen, _ = _build(open_failure=RuntimeError("baza əlçatmazdır"))

    screen.create_requested.emit()

    assert screen.errors, "forma açılmadığı bildirilməlidir"


def test_dialog_refuses_to_open_without_any_position() -> None:
    """Vəzifə siyahısı boşdursa dialoq admin-i «Vəzifə» xanası boş buraxmır."""
    _, screen, _ = _build(positions=[])

    screen.create_requested.emit()

    assert screen.errors
    assert "vəzifə" in screen.errors[0][1].lower()


def test_inactive_positions_are_excluded_from_the_dropdown() -> None:
    """Deaktiv rol yeni işçiyə TƏYİN OLUNMAMALIDIR — bax `_position_choices`."""
    active = _position(active=True)
    inactive = _position(active=False)

    choices = user_admin_module._position_choices(
        _Session(
            uow=_Uow(connection=_Connection([]), positions=_Positions([active, inactive])),
            users=_Users(),
        )  # type: ignore[arg-type]
    )

    assert [code for code, _, _ in choices] == [str(active.id)]
