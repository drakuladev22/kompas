""" "İstisnalar" ekranı və kontrolleri — #9-un GUI tərəfi (kompasos11.md Faza 5).

Testlər İKİ təbəqəni ayrıca yoxlayır:

    * ekranın ÖZÜ (boş vəziyyət, naməlum mənbə üçün çökməmə) — Qt TƏLƏB EDİR,
      çünki `set_exceptions` real `Chip`/`DataTable` qurur;
    * kontroller (yazıdan sonra yenidən oxuma, uğursuzluğun izahı) — Qt TƏLƏB
      ETMİR, `tests/unit/test_phase56_write_controllers.py`-dəki duck-typing
      naxışını təkrarlayır (dialoqlu düymələr PRİVAT `_decide()` metodu ilə
      birbaşa yoxlanılır — `QInputDialog` modalı testdə açılmır).

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py`-a TOXUNULMUR, çünki
paralel aparılan #8 (`BehaviorBaselineUseCase`) işi həmin faylı da işlədə
bilər.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.exception_engine import ExceptionView
from src.domain.value_objects.identifiers import EmployeeId, ExceptionId, TenantId
from src.presentation.controllers.exceptions import ExceptionsController
from src.presentation.shell.menu import DEFAULT_ENTRIES
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())


def _actor() -> Any:
    return type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()


def _view(**overrides: Any) -> ExceptionView:
    defaults: dict[str, Any] = {
        "exception_id": ExceptionId(uuid.uuid4()),
        "source_code": "BEHAVIOR_ANOMALY",
        "source_name_az": "Davranış Anomaliyası",
        "employee_id": str(uuid.uuid4()),
        "store_id": str(uuid.uuid4()),
        "detail": "Son 30 günün orta check-in vaxtından 42 dəqiqə sapma.",
        "severity": "HIGH",
        "status": "OPEN",
        "created_at": datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ExceptionView(**defaults)


class _DeniedError(KompasOSError):
    user_message = "Rədd səbəbini ətraflı yazın."


# --------------------------------------------------------------------------- #
# Menyu: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (CLAUDE.md bölmə 3)
# --------------------------------------------------------------------------- #


def test_menu_entry_requires_the_view_flag() -> None:
    """Maddə `can_view_exceptions`-a bağlıdır — spesifikasiyanın gözlədiyi flag."""
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "exceptions")
    assert entry.required_flag == "can_view_exceptions"


def test_navigation_hides_the_entry_without_the_flag() -> None:
    """Flag-i olmayan aktor "İstisnalar" bəndini menyuda GÖRMÜR."""
    from src.presentation import preview_data
    from src.presentation.shell.menu import build_default_registry

    registry = build_default_registry()
    operator = preview_data.build_camera_operator()

    assert registry.is_visible("exceptions", operator, now=preview_data.PREVIEW_NOW) is False


def test_navigation_shows_the_entry_with_the_flag() -> None:
    """Flag-i olan aktor bəndi GÖRÜR — əks halın özü xəta olardı."""
    from src.presentation import preview_data
    from src.presentation.shell.menu import build_default_registry

    registry = build_default_registry()
    admin = preview_data.build_admin()

    assert registry.is_visible("exceptions", admin, now=preview_data.PREVIEW_NOW) is True


# --------------------------------------------------------------------------- #
# Ekranın özü — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


@requires_qt
def test_empty_list_shows_the_empty_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import ExceptionsScreen

    screen = ExceptionsScreen(theme)
    qtbot.addWidget(screen)

    screen.set_exceptions([])

    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_unknown_source_badge_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sabahkı ikinci mənbə ekrana TOXUNMADAN görünməlidir (bax ekran başlığı).

    Badge mətni `ExceptionView.source_name_az`-dan gəlir — "naməlum" mənbə
    üçün heç bir `if source == ...` budağı YOXDUR, ona görə tanınmayan kod da
    sadəcə öz mətnini göstərməlidir, çökməməlidir.
    """
    from src.presentation.screens.group_i import ExceptionsScreen

    screen = ExceptionsScreen(theme)
    qtbot.addWidget(screen)

    screen.set_exceptions(
        [
            {
                "id": str(uuid.uuid4()),
                "source": "FUTURE_SOURCE",
                "source_name": "Gələcək Mənbə",
                "employee": "Aysel Quliyeva",
                "store": "Bellona 28 May",
                "detail": "Naməlum mənbədən gələn tapıntı.",
                # Ciddiyyət də naməlum dəyərdir — `_SEVERITY_TONES.get(...)`
                # defolta ("neutral") düşməlidir, istisna atmamalıdır.
                "severity": "UNKNOWN",
                "severity_text": "UNKNOWN",
                "date": "12.08.2026 09:42",
            }
        ]
    )

    assert screen.switcher().current_state() == "content"
    assert screen.table().row_count == 1


# --------------------------------------------------------------------------- #
# Kontroller — Qt tələb ETMİR (duck-typing)
# --------------------------------------------------------------------------- #


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or [{"name": "Bellona 28 May"}]

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        return _Cursor(self.rows)


class _Employees:
    def get(self, employee_id: Any) -> Any:
        return None  # Ekran ID-nin qısa formasına düşür — sadə test yetərlidir.


class _Uow:
    def __init__(self) -> None:
        self.employees = _Employees()
        self.connection = _Connection()


class _ExceptionsUseCase:
    def __init__(
        self, views: list[ExceptionView], *, dismiss_error: Exception | None = None
    ) -> None:
        self.views = list(views)
        self.dismiss_error = dismiss_error
        self.dismissed: list[tuple[Any, str]] = []
        self.reviewed: list[Any] = []

    def list_open(self, *, tenant_id: Any, actor: Any) -> list[ExceptionView]:
        return list(self.views)

    def dismiss(self, *, tenant_id: Any, actor: Any, exception_id: Any, note: str) -> None:
        if self.dismiss_error is not None:
            raise self.dismiss_error
        self.dismissed.append((exception_id, note))
        self.views = [v for v in self.views if v.exception_id != exception_id]

    def mark_reviewed(
        self, *, tenant_id: Any, actor: Any, exception_id: Any, note: str | None = None
    ) -> None:
        self.reviewed.append(exception_id)
        self.views = [v for v in self.views if v.exception_id != exception_id]


class _Session:
    def __init__(self, use_case: _ExceptionsUseCase) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow()
        self.exceptions = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: _Session) -> None:
        self._session = session

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


class _Screen:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] | None = None
        self.errors: list[tuple[str, str]] = []

    def set_exceptions(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


def test_refresh_reads_open_exceptions_into_the_screen_namespace() -> None:
    """Sətir açarları maket yolu (`preview_data.EXCEPTIONS`) ilə EYNİ olmalıdır."""
    view = _view()
    session = _Session(_ExceptionsUseCase([view]))
    controller = ExceptionsController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _Screen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows is not None
    assert set(screen.rows[0]) == {
        "id",
        "source",
        "source_name",
        "employee",
        "store",
        "detail",
        "severity",
        "severity_text",
        "date",
    }
    assert screen.rows[0]["severity_text"] == "Yüksək"


def test_dismiss_refreshes_the_list_after_writing() -> None:
    """ "Rədd Et"-dən sonra siyahı YENİDƏN oxunur (CLAUDE.md bölmə 6)."""
    view = _view()
    use_case = _ExceptionsUseCase([view])
    session = _Session(use_case)
    controller = ExceptionsController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _Screen()

    controller._decide(
        screen,  # type: ignore[arg-type]
        str(view.exception_id),
        note="Kameradan yoxlanıldı, əsassız tapıntı olduğu müəyyən edildi.",
        dismiss=True,
        failure_title="Rədd əməliyyatı yazılmadı",
    )

    assert use_case.dismissed == [
        (view.exception_id, "Kameradan yoxlanıldı, əsassız tapıntı olduğu müəyyən edildi.")
    ]
    assert session.commits == 1
    # Bağlanmış istisna `list_open`-də artıq yoxdur — yenidən oxuma bunu
    # ƏKS ETDİRİR, əks halda ekran hələ "OPEN" göstərərdi.
    assert screen.rows == []


def test_failed_dismiss_is_explained_not_swallowed() -> None:
    """Domen qaydası (qeyd qısadır) sükutla udulmur, istifadəçiyə göstərilir."""
    view = _view()
    use_case = _ExceptionsUseCase([view], dismiss_error=_DeniedError("qeyd qısadır"))
    session = _Session(use_case)
    controller = ExceptionsController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _Screen()

    controller._decide(
        screen,  # type: ignore[arg-type]
        str(view.exception_id),
        note="qısa",
        dismiss=True,
        failure_title="Rədd əməliyyatı yazılmadı",
    )

    assert session.commits == 0
    assert screen.errors == [("Rədd əməliyyatı yazılmadı", "Rədd səbəbini ətraflı yazın.")]


def test_reviewed_does_not_require_a_note() -> None:
    """ "Nəzərdən Keçirildi" qeydsiz göndərilə bilir — domen onu KÖNÜLLÜ sayır."""
    view = _view()
    use_case = _ExceptionsUseCase([view])
    session = _Session(use_case)
    controller = ExceptionsController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _Screen()

    controller._decide(
        screen,  # type: ignore[arg-type]
        str(view.exception_id),
        note=None,
        dismiss=False,
        failure_title="Nəzərdən keçirmə yazılmadı",
    )

    assert use_case.reviewed == [view.exception_id]
    assert session.commits == 1
    assert not screen.errors
