"""`SalesPointsScreen` ↔ `SalesPointsController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_sales_points_controller.py` və `test_controller_dead_guards.py` sahtə
`_Screen`/`_SalesPoints` siniflərlə ölçür — REAL `SalesPointsScreen`, REAL
mükafat kartları ("Al"/"Çatmır"), REAL tarixçə sətri ("Etiraz") heç vaxt
qurulmur. Modul başlığının vəd etdiyi əsas fakt («iki düymə ekranda VARDI,
basılırdı, heç nə olmurdu») BURADA — real widget kliki ilə — yenidən yoxlanır.

`set_catalog()`/`set_history()` REAL, ictimai ekran API-lərdir (maket və
canlı yol EYNİ açarları işlədir, CLAUDE.md §6) — burada onlarla ƏL İLƏ
render edilir ki, real "Al"/"Etiraz" düymələri klikllənə bilsin.
`refresh()` `ScreenDataBinder`-dən keçdiyi üçün (`sales_points.py::refresh`)
o, `test_controller_dead_guards.py` ilə EYNİ sahtə ilə əvəzlənir.
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
REWARD_ID = str(uuid.uuid4())
ENTRY_ID = str(uuid.uuid4())


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


def _reward_row(*, reward_id: str = REWARD_ID, cost: int = 500) -> dict[str, str]:
    return {"id": reward_id, "name": "Qəhvə fincanı", "cost": str(cost)}


def _history_row(*, entry_id: str = ENTRY_ID, can_appeal: bool = True) -> dict[str, str]:
    return {
        "entry_id": entry_id,
        "date": "20.08.2026",
        "reason": "Satış #4521",
        "status": "Təsdiqli",
        "points": "+50",
        "can_appeal": "1" if can_appeal else "0",
    }


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _SalesPoints:
    def __init__(self) -> None:
        self.rewards: list[dict[str, Any]] = []
        self.disputes: list[dict[str, Any]] = []
        self.reward_error: KompasOSError | None = None
        self.dispute_error: KompasOSError | None = None

    def request_reward(self, **kwargs: Any) -> None:
        if self.reward_error is not None:
            raise self.reward_error
        self.rewards.append(kwargs)

    def open_dispute(self, **kwargs: Any) -> None:
        if self.dispute_error is not None:
            raise self.dispute_error
        self.disputes.append(kwargs)


class _Session:
    def __init__(self, sales_points: _SalesPoints) -> None:
        self.tenant_id = TENANT
        self.sales_points = sales_points
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, sales_points: _SalesPoints) -> None:
        self._sales_points = sales_points
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._sales_points)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


class _Binder:
    """`screen_data.ScreenDataBinder`-in yerini tutur (`test_controller_dead_guards.py`
    ilə eyni naxış)."""

    calls: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        _Binder.calls.append(key)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.presentation.controllers import screen_data as screen_data_module

    _Binder.calls = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)


# --------------------------------------------------------------------------- #
# 1. Real mükafat kartı — real "Al" kliki
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_buy_on_a_real_reward_card_commits_and_refreshes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_catalog([_reward_row(cost=500)], balance=1000)

    _click(screen, "Al")

    assert len(sales_points.rewards) == 1
    assert str(sales_points.rewards[0]["reward_id"]) == REWARD_ID
    assert any(s.committed for s in context.sessions)
    assert "sales_points" in _Binder.calls


@requires_qt
def test_an_unaffordable_reward_renders_a_disabled_button_that_does_nothing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """«Çatmır» düyməsi SÖNDÜRÜLÜB — real klik heç nə etməməlidir."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_catalog([_reward_row(cost=5000)], balance=100)

    button = next(b for b in screen.findChildren(QPushButton) if b.text() == "Çatmır")
    assert not button.isEnabled()
    button.click()  # deaktiv düymədə Qt heç bir siqnal yaymır

    assert sales_points.rewards == []


@requires_qt
def test_double_clicking_buy_reuses_the_same_redemption_id(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`_redemption_id_for` — insan reaksiya pəncərəsi (CLAUDE.md §5), REAL kliklə."""
    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_catalog([_reward_row(cost=500)], balance=1000)

    _click(screen, "Al")
    # `refresh()` sahtələnib — kart TƏKRAR qurulmur, ona görə həmin DÜYMƏNİ
    # İKİNCİ dəfə tapıb basmaq REAL "sürətli ikiqat klik"i təqlid edir.
    _click(screen, "Al")

    assert len(sales_points.rewards) == 2
    assert sales_points.rewards[0]["redemption_id"] == sales_points.rewards[1]["redemption_id"]


# --------------------------------------------------------------------------- #
# 2. Real tarixçə sətri — real "Etiraz" kliki + real səbəb modalı
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_appeal_on_a_real_row_prompts_and_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_history([_history_row()], period="Avqust 2026")

    reason = "Bu satış mənə aid deyil"
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (reason, True))
    )

    _click(screen, "Etiraz")

    assert len(sales_points.disputes) == 1
    assert str(sales_points.disputes[0]["entry_id"]) == ENTRY_ID
    assert sales_points.disputes[0]["reason"] == reason
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_appeal_button_does_not_render_when_the_window_has_closed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`can_appeal=0` — 72 saatlıq pəncərə bağlıdırsa düymə ÜMUMİYYƏTLƏ yoxdur."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_history([_history_row(can_appeal=False)], period="Avqust 2026")

    assert "Etiraz" not in [b.text() for b in screen.findChildren(QPushButton)]


@requires_qt
def test_declining_the_appeal_reason_prompt_disputes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_history([_history_row()], period="Avqust 2026")

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    _click(screen, "Etiraz")

    assert sales_points.disputes == []


# --------------------------------------------------------------------------- #
# 3. Malformed ID və use-case istisnası — çökmür, AÇIQ mesaj göstərir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_malformed_reward_id_from_a_stale_card_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.reward_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert sales_points.rewards == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_malformed_entry_id_from_a_stale_row_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.appeal_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert sales_points.disputes == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_reward_request_failure_shows_the_domain_message_and_keeps_it_visible(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Balans mübadilə anında kifayət etməyə bilər (use case qaydası) — real klik
    AÇIQ mesaj göstərir."""
    from src.presentation.controllers.sales_points import SalesPointsController
    from src.presentation.screens.group_f import SalesPointsScreen

    sales_points = _SalesPoints()
    sales_points.reward_error = KompasOSError(
        "insufficient balance", user_message="Balansınız bu mükafat üçün kifayət etmir."
    )
    context = _Context(sales_points)
    screen = SalesPointsScreen(theme)
    qtbot.addWidget(screen)
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_catalog([_reward_row(cost=500)], balance=1000)

    _click(screen, "Al")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"
