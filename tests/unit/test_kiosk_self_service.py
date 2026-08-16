"""İşçi Ana Ekranının üç öz-xidmət keçidi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
Üç düymə (`Tapşırıqlar`, `Xallar`, `Cərimələrim`) ekranda VARDI, siqnal da
yayırdı — dinləyən yox idi. Yəni işçi basırdı, heç nə olmurdu və heç bir xəta
çıxmırdı. Ən ağır nəticəsi cərimə etirazı idi: `FineAppealUseCase.submit`
işləyirdi, 72 saatlıq pəncərə işləyirdi, lakin həmin formaya çatan BİR YOL DA
yox idi.

Ona görə burada siqnalın yayılması DEYİL, NƏTİCƏSİ yoxlanılır: kioskda hansı
ekran göstərildi, geri yolu varmı, etiraz use case-ə hansı arqumentlərlə
getdi. Siqnalın özünü qapılamaq kifayət etməzdi — o, əvvəllər də yayılırdı.

Sahtələr BU FAYLDA yerlidir (`tests/fixtures/fakes.py` paylaşılan fayldır).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from tests.conftest import requires_qt

NOW = datetime(2026, 8, 16, 9, 30, tzinfo=UTC)
FINE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


class _Task:
    def __init__(self, title: str) -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.deadline = NOW


class _Money:
    def __init__(self, amount: Decimal) -> None:
        self.amount = amount


class _Fine:
    def __init__(self) -> None:
        self.id = FINE_ID
        self.amount = _Money(Decimal("25"))
        self.issued_at = NOW


class _Appeal:
    def __init__(self, *, open_: bool) -> None:
        self.fine_id = FINE_ID

        class _Status:
            is_open = open_

        self.status = _Status()


class _Row(dict):  # type: ignore[type-arg]
    pass


class _Cursor:
    def fetchone(self) -> Any:
        return _Row(name="Gecikmə")


class _Connection:
    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        return _Cursor()


class _TaskRepo:
    def __init__(self, tasks: list[_Task]) -> None:
        self._tasks = tasks
        self.seen: list[Any] = []

    def list_for_assignee(self, employee_id: Any, *, open_only: bool = True) -> list[_Task]:
        self.seen.append((employee_id, open_only))
        return self._tasks


class _Uow:
    def __init__(self, tasks: list[_Task]) -> None:
        self.connection = _Connection()
        self._tasks = _TaskRepo(tasks)

    def repository(self, name: str) -> Any:
        assert name == "tasks"
        return self._tasks


class _ManualFines:
    def __init__(self, fines: list[_Fine]) -> None:
        self._fines = fines

    def my_fines(self, *, employee: Any, year: int, month: int) -> list[_Fine]:
        return self._fines


class _Appeals:
    def __init__(self, appeals: list[_Appeal]) -> None:
        self._appeals = appeals
        self.submitted: list[dict[str, Any]] = []

    def my_appeals(self, _employee: Any) -> list[_Appeal]:
        return self._appeals

    def submit(self, *, tenant_id: Any, employee: Any, fine_id: Any, reason: str) -> Any:
        self.submitted.append({"fine_id": fine_id, "reason": reason})
        return object()


class _Session:
    def __init__(self, *, tasks: list[_Task], fines: list[_Fine], appeals: list[_Appeal]) -> None:
        self.tenant_id = uuid.uuid4()
        self.uow = _Uow(tasks)
        self.manual_fines = _ManualFines(fines)
        self.fine_appeals = _Appeals(appeals)
        self.committed = 0

    def commit(self) -> None:
        self.committed += 1


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
        self.opened += 1
        yield self._session


class _Kiosk:
    def __init__(self) -> None:
        self.shown: list[Any] = []

    def set_content(self, widget: Any) -> None:
        self.shown.append(widget)


class _Actor:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.full_name = "Rəşad Məmmədov"


def _wire(theme: Any, *, tasks: Any = None, fines: Any = None, appeals: Any = None) -> Any:
    from src.presentation.controllers.kiosk_self_service import KioskSelfServiceController
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    session = _Session(
        tasks=tasks if tasks is not None else [],
        fines=fines if fines is not None else [],
        appeals=appeals if appeals is not None else [],
    )
    context = _Context(session)
    kiosk = _Kiosk()
    home = EmployeeHomeScreen(
        theme,
        full_name="Rəşad Məmmədov",
        position_name="Satıcı",
        store_name="Bellona 28 May",
    )
    controller = KioskSelfServiceController(context, _Actor(), kiosk=kiosk, theme=theme)
    controller.attach(home)
    return home, kiosk, session


def _find(widget: Any, kind: type) -> Any:
    return widget.findChild(kind)


@requires_qt
def test_tasks_link_opens_the_employees_own_task_board(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import TasksScreen

    home, kiosk, session = _wire(theme, tasks=[_Task("Vitrin yenilənməsi")])
    qtbot.addWidget(home)

    home.tasks_requested.emit()

    assert kiosk.shown, "kioskda heç nə göstərilmədi — keçid ölüdür"
    assert _find(kiosk.shown[-1], TasksScreen) is not None
    # ÖZ tapşırıqları oxunur, tenant üzrə «təsdiq gözləyən» siyahı YOX.
    assert session.uow.repository("tasks").seen[-1][1] is True


@requires_qt
def test_rewards_link_opens_the_points_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import SalesPointsScreen

    home, kiosk, _session = _wire(theme)
    qtbot.addWidget(home)

    home.rewards_requested.emit()

    assert _find(kiosk.shown[-1], SalesPointsScreen) is not None


@requires_qt
def test_fines_link_opens_the_appeal_screen_with_the_month_history(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, _session = _wire(theme, fines=[_Fine()], appeals=[_Appeal(open_=True)])
    qtbot.addWidget(home)

    home.appeal_requested.emit()

    screen = _find(kiosk.shown[-1], FineAppealScreen)
    assert screen is not None
    assert screen.switcher().current_state() == "content"


@requires_qt
def test_every_opened_screen_offers_a_way_back(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Kioskda çıxış yolu olmayan ekran işçini tələyə salardı."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.kiosk_self_service import BACK_TEXT

    home, kiosk, _session = _wire(theme)
    qtbot.addWidget(home)

    for signal in (home.tasks_requested, home.rewards_requested, home.appeal_requested):
        signal.emit()
        buttons = [b.text() for b in kiosk.shown[-1].findChildren(QPushButton)]
        assert BACK_TEXT in buttons

    # Geri düyməsi ANA EKRANA qaytarır.
    back = next(b for b in kiosk.shown[-1].findChildren(QPushButton) if b.text() == BACK_TEXT)
    back.click()
    assert kiosk.shown[-1] is home


@requires_qt
def test_appeal_submission_reaches_the_use_case_with_both_fields(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    home.appeal_requested.emit()
    screen = _find(kiosk.shown[-1], FineAppealScreen)

    screen.appeal_submitted.emit(
        {
            "fine_id": str(FINE_ID),
            "reason": "Vaxt düzgün qeyd olunmayıb",
            "explanation": "Saat 09:05-də mağazada idim, kamera qeydi var.",
            "document": "",
        }
    )

    assert len(session.fine_appeals.submitted) == 1
    sent = session.fine_appeals.submitted[0]
    # KATEQORİYA İTMİR: domendə tək `reason` sahəsi var, ona görə seçim və
    # izah birləşdirilir — yalnız izahı göndərsəydik, təsdiqləyicinin ilk
    # oxuduğu sətir yox olardı.
    assert "Vaxt düzgün qeyd olunmayıb" in sent["reason"]
    assert "kamera qeydi var" in sent["reason"]
    assert session.committed == 1


@requires_qt
def test_attached_document_is_reported_not_silently_dropped(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sənəd hələ göndərilmir — işçi bunu BİLMƏLİDİR.

    Sükutla buraxılsaydı, işçi sübutunun sistemə düşdüyünü sanar və mübahisə
    zamanı onu ayrıca təqdim etməzdi.
    """
    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    home.appeal_requested.emit()
    screen = _find(kiosk.shown[-1], FineAppealScreen)

    screen.appeal_submitted.emit(
        {
            "fine_id": str(FINE_ID),
            "reason": "Digər",
            "explanation": "Ətraflı izah buradadır və kifayət qədər uzundur.",
            "document": "C:/subut.jpg",
        }
    )

    # Etiraz YAZILIR (sənədin olmaması onu bloklamamalıdır) …
    assert len(session.fine_appeals.submitted) == 1
    # … lakin ekran vəziyyəti AÇIQ xəbərdarlığa keçir.
    assert screen.switcher().current_state() == "error"
