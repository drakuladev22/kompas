"""Xal etirazlarının MENECER növbəsi — `decide_dispute()` ARTIQ ÇAĞIRILIR.

──────────────────────────────────────────────────────────────────────────────
BOŞLUQ NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`SalesPointsUseCase.decide_dispute()` yazılıb, testli idi və audit sətri də
qururdu — LAKİN onu çağıran heç bir ekran yox idi. İşçi xala etiraz edirdi,
etiraz `PENDING` qalırdı, 72 saatdan sonra `EXPIRED` olurdu və HEÇ KİMİN
siyahısına düşmürdü. Yəni hüquq verilmişdi, ona çatan yol yox idi.

Testlər ÜÇ müqaviləni kilidləyir:

1. siyahı `PENDING` VƏ `EXPIRED` sətirləri göstərir («vaxt bitdi» ≠ «qərar
   verildi», M-6);
2. hər iki düymə `decide_dispute()`-in DÜZGÜN qoluna gedir (rədd / ləğv);
3. səbəb MƏCBURİDİR — ləğv edilən dialoq heç nə yazmır, qısa səbəb isə
   dialoqu YAZILAN MƏTNLƏ yenidən açır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
ENTRY_PENDING = uuid.uuid4()
ENTRY_EXPIRED = uuid.uuid4()
NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


class _View:
    """`PointsDisputeView`-in əvəzedicisi — kontroller BEŞ sahə oxuyur."""

    def __init__(self, entry_id: Any, *, points: int, expired: bool) -> None:
        self.entry_id = entry_id
        self.employee_id = uuid.uuid4()
        self.points = points
        self.dispute_reason = "Çek mənim satışımdır, kassa səhv işçiyə yazıb."
        self.disputed_at = NOW
        self.appeal_status = "EXPIRED" if expired else "PENDING"
        self.entry_status = "ACTIVE"
        self.window_closes_at = NOW

    @property
    def is_expired(self) -> bool:
        return self.appeal_status == "EXPIRED"


class _SalesPoints:
    def __init__(self, views: list[_View], *, failure: Exception | None = None) -> None:
        self._views = views
        self._failure = failure
        self.decisions: list[dict[str, Any]] = []

    def list_undecided_disputes(self, *, tenant_id: Any, actor: Any) -> list[_View]:
        if self._failure is not None:
            raise self._failure
        return self._views

    def decide_dispute(self, **kwargs: Any) -> Any:
        self.decisions.append(kwargs)
        return object()


class _Employees:
    def get(self, _employee_id: Any) -> Any:
        return SimpleNamespace(full_name="Aygün Məmmədova")


class _Uow:
    employees = _Employees()


class _Session:
    def __init__(self, sales_points: _SalesPoints) -> None:
        self.tenant_id = TENANT
        self.sales_points = sales_points
        self.uow = _Uow()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, sales_points: _SalesPoints) -> None:
        self._sales_points = sales_points
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
        created = _Session(self._sales_points)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _screen(qt_app: Any) -> Any:
    from src.presentation.screens.group_f import SalesPointsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    return SalesPointsScreen(theme)


def _attach(screen: Any, market: _SalesPoints) -> _Context:
    from src.presentation.controllers.points_disputes import PointsDisputeController

    context = _Context(market)
    PointsDisputeController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    return context


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


@requires_qt
def test_both_pending_and_expired_disputes_stay_in_the_queue(qt_app) -> None:  # type: ignore[no-untyped-def]
    """«Vaxt bitdi» ≠ «qərar verildi» — `EXPIRED` sətir siyahıdan ÇIXMIR (M-6)."""
    from PySide6.QtWidgets import QPushButton

    screen = _screen(qt_app)
    market = _SalesPoints(
        [
            _View(ENTRY_PENDING, points=60, expired=False),
            _View(ENTRY_EXPIRED, points=-30, expired=True),
        ]
    )
    _attach(screen, market)

    labels = [b.text() for b in screen.findChildren(QPushButton)]
    assert labels.count("Etirazı Rədd Et") == 2
    assert labels.count("Xalı Ləğv Et") == 2


@requires_qt
def test_an_empty_queue_hides_the_section(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Boş başlıq «burada nəsə olmalıydı» sualı yaradardı."""
    screen = _screen(qt_app)
    _attach(screen, _SalesPoints([]))

    assert screen._dispute_section.isVisible() is False


@requires_qt
def test_rejecting_a_dispute_keeps_the_entry_and_writes_the_reason(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`[Etirazı Rədd Et]` → `reject=True` (sətir QÜVVƏDƏ qalır)."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Kassa qeydi satışı düzgün göstərir", True)),
    )
    screen = _screen(qt_app)
    market = _SalesPoints([_View(ENTRY_PENDING, points=60, expired=False)])
    context = _attach(screen, market)

    _click(screen, "Etirazı Rədd Et")

    assert len(market.decisions) == 1
    decision = market.decisions[0]
    assert decision["reject"] is True
    assert decision["entry_id"] == ENTRY_PENDING
    assert decision["reason"] == "Kassa qeydi satışı düzgün göstərir"
    assert any(session.committed for session in context.sessions)


@requires_qt
def test_reversing_the_points_goes_through_the_other_branch(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`[Xalı Ləğv Et]` → `reject=False` (`corrected_points=None` → `reverse()`)."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Etiraz haqlıdır, xal səhv yazılıb", True)),
    )
    screen = _screen(qt_app)
    market = _SalesPoints([_View(ENTRY_PENDING, points=60, expired=False)])
    _attach(screen, market)

    _click(screen, "Xalı Ləğv Et")

    assert market.decisions[0]["reject"] is False


@requires_qt
def test_a_cancelled_reason_dialog_decides_nothing(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Səbəb MƏCBURİDİR: işçiyə gedən bildiriş məhz həmin mətni daşıyır."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))
    screen = _screen(qt_app)
    market = _SalesPoints([_View(ENTRY_PENDING, points=60, expired=False)])
    context = _attach(screen, market)
    before = len(context.sessions)

    _click(screen, "Etirazı Rədd Et")

    assert market.decisions == []
    assert len(context.sessions) == before, "yazı sessiyası ümumiyyətlə açılmamalıdır"


@requires_qt
def test_a_short_reason_reopens_the_dialog_with_the_typed_text(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Qısa cavabda YAZILAN MƏTN İTMİR (naxış: `camera_queue._ask_reason`)."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    calls: list[tuple[Any, ...]] = []

    def _multiline(*args: Any, **kwargs: Any) -> tuple[str, bool]:
        calls.append(args)
        return ("qısa", True) if len(calls) == 1 else ("", False)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(_multiline))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
    screen = _screen(qt_app)
    market = _SalesPoints([_View(ENTRY_PENDING, points=60, expired=False)])
    _attach(screen, market)

    _click(screen, "Etirazı Rədd Et")

    assert len(calls) == 2, "qısa cavabdan sonra dialoq YENİDƏN açılmalıdır"
    assert calls[1][3] == "qısa", "yazılan mətn dialoqa GERİ verilməlidir"
    assert market.decisions == []


@requires_qt
def test_a_denied_read_hides_the_section_without_breaking_the_screen(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Səlahiyyət xətası balans/tarixçə kartlarını GİZLƏTMƏMƏLİDİR.

    Bölmə səhifənin SONUNDADIR; `show_error()` bütün məzmunu əvəz edərdi
    (eyni qərar `root_control.py::_on_module_toggled`-dədir).
    """
    from src.shared.exceptions import KompasOSError

    screen = _screen(qt_app)
    market = _SalesPoints([], failure=KompasOSError("denied", user_message="İcazə yoxdur."))
    _attach(screen, market)

    assert screen._dispute_section.isVisible() is False
    assert screen.switcher().current_state() != "error"
