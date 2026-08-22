"""`HealthScreen` ↔ `ScreenDataBinder._health` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, infra dalğası)
──────────────────────────────────────────────────────────────────────────────
`test_erp_and_health_bindings.py` `_health` bağlamasını YALNIZ duck-typing
sahə obyekti (`_HealthScreen`) ilə ölçür — REAL `HealthScreen`, REAL
`LinkLabel` (konflikt keçidi), REAL "Yenidən Yoxla" düyməsi heç vaxt
qurulmur. Bu ekranın öz kontrolleri yoxdur: `app.py::_attach_health`
`screen.recheck_requested`-i birbaşa `binder.populate("health", screen)`-ə
bağlayır (bax `app.py:3086`) — həmin BİR sətirlik naxış burada TƏKRARLANIR
ki, real klik → real yenidən-oxuma zənciri sınansın.

──────────────────────────────────────────────────────────────────────────────
KONFLİKT KEÇİDİNİN SƏLAHİYYƏT QAPISI — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI"
──────────────────────────────────────────────────────────────────────────────
`HealthScreen.set_conflict_action` docstring-i açıq deyir: keçid YALNIZ
`RESOLVE_CONFLICT_FLAG` daşıyan aktorda qurulur, `setEnabled(False)` ilə boz
qalmır — widget ÜMUMİYYƏTLƏ YARADILMIR. Bu, `test_screen_binding_coverage.py`-
nin CLAUDE.md §2-də təsvir etdiyi "adla xatırlanır, çağırılmır" tələsinin tam
əksidir — burada REAL `findChildren(LinkLabel)` ilə widget-in yaranıb-yaranmadığı
yoxlanılır, sahə obyektinin bir atributu yox.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Final

import pytest
from PySide6.QtCore import Qt

from src.application.use_cases.sync_conflicts import RESOLVE_CONFLICT_FLAG
from src.presentation.controllers.screen_data import (
    SECTION_HEALTH_CONFLICTS,
    ScreenDataBinder,
)
from src.presentation.widgets.primitives import LinkLabel
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = uuid.uuid4()
ACTOR_ID: Final = uuid.uuid4()


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


# --------------------------------------------------------------------------- #
# `ScreenDataBinder._health` sahtələri — `test_erp_and_health_bindings.py`
# ilə EYNİ müqavilə (`session.uow`, `session.limits`, `session.notifications`,
# `context.ntp_drift_seconds`, `context.offline_drain`), amma yerli nüsxə:
# modul başlığında izah edildiyi kimi sahtələr hər faylda yerlidir.
# --------------------------------------------------------------------------- #


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _HealthRow(dict):
    pass


def _health_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "server_name": "1C-BAKI-01",
        "health": "HEALTHY",
        "sync_delay_seconds": 42,
        "last_error_at": None,
        "consecutive_failures": 0,
        "mapped_stores": 9,
    }
    row.update(overrides)
    return row


class _Connection:
    def __init__(self, health_rows: list[dict[str, Any]]) -> None:
        self.health_rows = health_rows

    def execute(self, sql: str, _params: Any = None) -> _Cursor:
        if "v_erp_server_health" in sql:
            return _Cursor(list(self.health_rows))
        return _Cursor([{"?column?": 1}])  # `SELECT 1` — DB ping


class _Conflicts:
    """`open_count` uğursuzluğu SINANMASI ÜÇÜN dəyişdirilə bilər."""

    def __init__(self, *, count: int = 0, error: Exception | None = None) -> None:
        self.count = count
        self.error = error
        self.calls = 0

    def open_count(self, _tenant_id: Any) -> int:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.count


class _Uow:
    def __init__(self, connection: _Connection, conflicts: _Conflicts) -> None:
        self.connection = connection
        self._conflicts = conflicts

    def repository(self, name: str) -> Any:
        assert name == "sync_conflicts"
        return self._conflicts


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default


class _Notifications:
    def list_for_recipient(self, _employee_id: Any, *, hidden_categories: Any) -> list[Any]:
        assert hidden_categories is not None
        return []


class _Session:
    def __init__(self, connection: _Connection, conflicts: _Conflicts) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(connection, conflicts)
        self.limits = _Limits()
        self.notifications = _Notifications()


class _Context:
    def __init__(self, session: _Session, *, drift: float | None = None) -> None:
        self._session = session
        self._drift = drift
        self.opens = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opens += 1
        yield self._session

    def ntp_drift_seconds(self) -> float | None:
        return self._drift

    def offline_drain(self) -> Any:
        class _Drain:
            def pending_count(self, _tenant_id: Any) -> int:
                return 5

        return _Drain()


class _Actor:
    def __init__(self, *, can_resolve: bool) -> None:
        self.id = ACTOR_ID
        self._can_resolve = can_resolve

    def has_permission(self, flag: str, *, now: Any) -> bool:
        return self._can_resolve and flag == RESOLVE_CONFLICT_FLAG


def _wire(screen: Any, binder: ScreenDataBinder) -> None:
    """`app.py::_attach_health`-dəki BİRLİK sətrin dəqiq nüsxəsi (`app.py:3086`)."""
    screen.recheck_requested.connect(lambda: binder.populate("health", screen))


# --------------------------------------------------------------------------- #
# 1. Real "Yenidən Yoxla" kliki — real widget-lər YENİDƏN dolur
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_recheck_repopulates_the_real_metric_and_alert_widgets(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import HealthScreen

    connection = _Connection([_health_row()])
    conflicts = _Conflicts(count=0)
    session = _Session(connection, conflicts)
    context = _Context(session, drift=None)
    binder = ScreenDataBinder(context, _Actor(can_resolve=True))  # type: ignore[arg-type]

    screen = HealthScreen(theme)
    qtbot.addWidget(screen)
    _wire(screen, binder)
    binder.populate("health", screen)

    # İlk vəziyyət: heç bir problem yoxdur.
    assert screen._alerts_rows.count() == 1  # "Aktiv xəbərdarlıq yoxdur." sətri

    # Server sınır, konflikt yaranır — REAL klikdən SONRA görünməlidir.
    connection.health_rows = [_health_row(health="NEVER_SYNCED", sync_delay_seconds=None)]
    conflicts.count = 4

    _click(screen, "Yenidən Yoxla")  # REAL düymə, `recheck_requested` → `populate`

    assert context.opens == 2, "Klik yeni sessiya açmalıdır (köhnə keşdən oxumur)"

    from PySide6.QtWidgets import QLabel

    labels = " ".join(label.text() for label in screen._alerts.findChildren(QLabel))
    assert "1C-BAKI-01" in labels
    assert "4 sinxronizasiya konflikti həll gözləyir" in labels


# --------------------------------------------------------------------------- #
# 2–3. Konflikt keçidi — YALNIZ flag daşıyan aktorda QURULUR
# --------------------------------------------------------------------------- #


@requires_qt
def test_conflict_link_is_never_built_for_an_actor_without_the_resolve_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Alert mətni konflikti göstərir, LAKİN keçid widget-i YOXDUR (boz da deyil)."""
    from src.presentation.screens.group_d import HealthScreen

    connection = _Connection([_health_row()])
    conflicts = _Conflicts(count=3)
    session = _Session(connection, conflicts)
    context = _Context(session, drift=None)
    binder = ScreenDataBinder(context, _Actor(can_resolve=False))  # type: ignore[arg-type]

    screen = HealthScreen(theme)
    qtbot.addWidget(screen)
    binder.populate("health", screen)

    from PySide6.QtWidgets import QLabel

    labels = " ".join(label.text() for label in screen._alerts.findChildren(QLabel))
    assert "3 sinxronizasiya konflikti həll gözləyir" in labels
    assert screen.findChildren(LinkLabel) == []


@requires_qt
def test_conflict_link_is_built_clickable_and_removed_once_conflicts_reach_zero(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import HealthScreen

    connection = _Connection([_health_row()])
    conflicts = _Conflicts(count=2)
    session = _Session(connection, conflicts)
    context = _Context(session, drift=None)
    binder = ScreenDataBinder(context, _Actor(can_resolve=True))  # type: ignore[arg-type]

    screen = HealthScreen(theme)
    qtbot.addWidget(screen)
    _wire(screen, binder)
    binder.populate("health", screen)

    links = screen.findChildren(LinkLabel)
    assert len(links) == 1
    assert links[0].text() == "2 sinxronizasiya konfliktini həll et"

    navigated: list[bool] = []
    screen.conflicts_requested.connect(lambda: navigated.append(True))
    qtbot.mouseClick(links[0], Qt.MouseButton.LeftButton)
    assert navigated == [True], "Real klik `conflicts_requested` siqnalını YAYMALIDIR"

    # Sonuncu konflikt həll olunur — keçid REAL olaraq SİLİNMƏLİDİR.
    conflicts.count = 0
    _click(screen, "Yenidən Yoxla")
    # `deleteLater()` silməni NÖVBƏTİ hadisə dövrəsinə ötürür (Qt-nin adi
    # davranışı) — `set_conflict_action` özü `self._conflict_link = None`-i
    # DƏRHAL edir, widget-in özü isə hadisə dövrəsi işlədikdən sonra yox olur.
    qtbot.wait(50)
    assert screen.findChildren(LinkLabel) == []


# --------------------------------------------------------------------------- #
# 4. Konflikt sayğacı oxunmur — bölmə banneri göstərilir, ÇÖKMÜR, TƏMİZLƏNİR
# --------------------------------------------------------------------------- #


@requires_qt
def test_unreadable_conflict_counter_shows_a_section_banner_and_recheck_clears_it(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import HealthScreen

    connection = _Connection([_health_row()])
    conflicts = _Conflicts(error=RuntimeError("baza əlaqəsi kəsildi"))
    session = _Session(connection, conflicts)
    context = _Context(session, drift=None)
    binder = ScreenDataBinder(context, _Actor(can_resolve=True))  # type: ignore[arg-type]

    screen = HealthScreen(theme)
    qtbot.addWidget(screen)
    _wire(screen, binder)
    binder.populate("health", screen)  # ÇÖKMƏMƏLİDİR

    assert SECTION_HEALTH_CONFLICTS in screen.section_errors()
    # Oxuna bilməyən sayğac keçid QURMUR — `0` kimi rəftar edilir (bax
    # `ScreenDataBinder._health` şərhi: "OXUNA BİLMƏYƏN SAYĞAC KEÇİD QURMUR").
    assert screen.findChildren(LinkLabel) == []

    # Sonrakı REAL klik uğurlu oxumaya keçir — köhnə banner YALAN qalmamalıdır.
    conflicts.error = None
    conflicts.count = 1
    _click(screen, "Yenidən Yoxla")

    assert SECTION_HEALTH_CONFLICTS not in screen.section_errors()
    links = screen.findChildren(LinkLabel)
    assert len(links) == 1
    assert links[0].text() == "1 sinxronizasiya konfliktini həll et"
