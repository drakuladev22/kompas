"""`NotificationPanel`/`PageHeader` ↔ `NotificationsController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_notification_panel_wiring.py` `_Panel`/`_Header` SAHTƏLƏRİ ilə (öz
`_Signal` təqlidi, QApplication BELƏ qurulmur) yazılıb — real
`NotificationPanel`, real `NotificationItem`, real `PageHeader` heç vaxt
qurulmur, heç bir real klik göndərilmir. Modulun öz başlığı bunu açıq
sənədləşdirir: «Testlər Qt və baza TƏLƏB ETMİR». Bu, CLAUDE.md-nin təsvir
etdiyi tələdir — bildiriş zənginin nişanı, real sətrə klik, real «Hamısını
oxunmuş et» keçidi heç vaxt REAL widget ağacı ilə yoxlanılmayıb.

Burada `NotificationsController.attach(panel, header)` REAL `NotificationPanel`
və REAL `PageHeader`-ə bağlanır; hər ssenari HƏQİQİ zəng kliki, HƏQİQİ sətir
kliki və HƏQİQİ «Hamısını oxunmuş et» keçidi ilə işə salınır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.infrastructure.persistence.notification_repositories import NotificationRow
from src.presentation.controllers.notifications import NotificationsController
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
ACTOR = EmployeeId(uuid.uuid4())
NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _row(
    *,
    category: str = "FINE_APPEAL_PENDING",
    title: str = "Yeni cərimə etirazı",
    critical: bool = False,
    created_at: datetime = NOW,
    read_at: datetime | None = None,
) -> NotificationRow:
    return NotificationRow(
        id=uuid.uuid4(),
        category=category,
        title_az=title,
        body_az="İcazəsiz çıxış · 40 ₼",
        is_critical=critical,
        created_at=created_at,
        read_at=read_at,
    )


class _Repo:
    def __init__(self, rows: list[NotificationRow]) -> None:
        self.rows = rows
        self.read_calls: list[tuple[uuid.UUID, EmployeeId]] = []
        self.all_calls: list[EmployeeId] = []
        self.list_calls = 0

    def list_for_recipient(
        self, recipient_id: EmployeeId, *, hidden_categories: Any, **_: Any
    ) -> list[NotificationRow]:
        self.list_calls += 1
        return self.rows

    def mark_read(
        self, notification_id: uuid.UUID, recipient_id: EmployeeId, *, hidden_categories: Any
    ) -> int:
        self.read_calls.append((notification_id, recipient_id))
        self.rows = [row if row.id != notification_id else _mark(row) for row in self.rows]
        return 1

    def mark_all_read(self, recipient_id: EmployeeId, *, hidden_categories: Any) -> int:
        self.all_calls.append(recipient_id)
        self.rows = [_mark(row) for row in self.rows]
        return len(self.rows)


def _mark(row: NotificationRow) -> NotificationRow:
    from dataclasses import replace

    return replace(row, read_at=NOW)


class _Session:
    def __init__(self, repo: _Repo) -> None:
        self.notifications = repo
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Context:
    def __init__(self, repo: _Repo) -> None:
        self.tenant_id = TENANT
        self.sessions: list[_Session] = []
        self._repo = repo

    def session(self, **_: Any) -> _Session:
        created = _Session(self._repo)
        self.sessions.append(created)
        return created


class _Actor:
    """Bütün `permission_flags` daşıyan aktor — auditoriya süzgəci burada ölçülmür."""

    id = ACTOR

    def has_permission(self, flag_code: str, *, now: datetime) -> bool:
        return True


def _header(theme: Any) -> Any:
    from src.presentation.widgets.page_header import PageHeader

    return PageHeader(
        icon_color=theme.color("--color-nav-item-text"),
        badge_bg=theme.color("--color-brand-amber"),
        badge_fg=theme.color("--color-brand-navy"),
        surface_color=theme.color("--color-header-bg"),
        avatar_bg=theme.color("--color-neutral-bg"),
        avatar_fg=theme.color("--color-text-primary"),
        dark_mode=False,
    )


def _wire(theme: Any, rows: list[NotificationRow]) -> tuple[Any, Any, _Repo, _Context]:
    from src.presentation.screens.group_g import NotificationPanel

    repo = _Repo(rows)
    context = _Context(repo)
    panel = NotificationPanel(theme)
    header = _header(theme)
    controller = NotificationsController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(panel, header)  # type: ignore[arg-type]
    return panel, header, repo, context


def _item_widgets(panel: Any) -> list[Any]:
    from src.presentation.screens.group_g import NotificationItem

    return panel.findChildren(NotificationItem)


def _settle(qt_app: Any) -> None:
    """`clear_layout()` köhnə sətirləri `deleteLater()` ilə silir — adi
    `processEvents()` təxirə salınmış silinməni EMAL ETMİR (bax `test_
    announcements_screen_e2e.py::test_clicking_withdraw_...` eyni qərar).
    Bu funksiya olmasa, İKİNCİ `set_notifications()` çağırışından sonra
    köhnə VƏ yeni sətirlər eyni anda `findChildren`-də görünər."""
    from PySide6.QtCore import QEvent

    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


# --------------------------------------------------------------------------- #
# 1. Real zəng kliki → panel doldurulur
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_bell_click_opens_and_fills_the_real_panel(qtbot, qt_app, theme) -> None:  # type: ignore[no-untyped-def]
    panel, header, repo, _context = _wire(theme, [_row(), _row(read_at=NOW), _row()])
    qtbot.addWidget(panel)
    qtbot.addWidget(header)

    # `attach()` girişdən dərhal sonra bir dəfə oxuyub — burada ƏLAVƏ real
    # zəng kliki `isVisible()`-ə görə YALNIZ görünəndə sorğu göndərir.
    panel.setVisible(True)
    calls_before = repo.list_calls
    header.bell()._button.click()
    _settle(qt_app)

    assert repo.list_calls == calls_before + 1
    assert len(_item_widgets(panel)) == 3
    assert header.bell()._count == 2, "Oxunmuş sətir sayğaca düşməməlidir"


@requires_qt
def test_bell_click_does_not_query_while_the_panel_is_hidden(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    panel, header, repo, _context = _wire(theme, [_row()])
    qtbot.addWidget(panel)
    qtbot.addWidget(header)
    panel.setVisible(False)
    calls_before = repo.list_calls

    header.bell()._button.click()

    assert repo.list_calls == calls_before, "Bağlanış sorğu göndərməməlidir"


# --------------------------------------------------------------------------- #
# 2. Real sətrə klik = «oxundu» — HƏQİQİ `NotificationItem` widget-i
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_a_real_row_marks_it_read_and_refreshes_the_real_bell(
    qtbot, qt_app, theme
) -> None:  # type: ignore[no-untyped-def]
    row = _row()
    panel, header, repo, context = _wire(theme, [row])
    qtbot.addWidget(panel)
    qtbot.addWidget(header)

    item = _item_widgets(panel)[0]
    item._activate()  # siçan kliki ilə EYNİ yol (`mousePressEvent` → `_activate`)
    _settle(qt_app)

    assert repo.read_calls == [(row.id, ACTOR)]
    assert any(s.committed for s in context.sessions), "Yazı sessiyası commit edilməlidir"
    assert header.bell()._count == 0, "Real zəng nişanı REFRESH-DƏN sonra sıfırlanmalıdır"


@requires_qt
def test_keyboard_activation_of_a_real_row_also_marks_it_read(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sətir klaviatura ilə fokuslana bilir (`FocusPolicy.StrongFocus`) — Enter da işləməlidir."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    row = _row()
    panel, header, repo, _context = _wire(theme, [row])
    qtbot.addWidget(panel)
    qtbot.addWidget(header)
    item = _item_widgets(panel)[0]

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(item, event)

    assert repo.read_calls == [(row.id, ACTOR)]


# --------------------------------------------------------------------------- #
# 3. Real «Hamısını oxunmuş et» keçidi
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_mark_all_read_link_clears_every_row_and_the_bell(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets.primitives import LinkLabel

    panel, header, repo, context = _wire(theme, [_row(), _row()])
    qtbot.addWidget(panel)
    qtbot.addWidget(header)

    link = next(w for w in panel.findChildren(LinkLabel) if w.text() == "Hamısını oxunmuş et")
    link._activate()  # `LinkLabel.clicked` — real klik ilə EYNİ tetikləyici

    assert repo.all_calls == [ACTOR]
    assert any(s.committed for s in context.sessions), "Yazı sessiyası commit edilməlidir"
    assert header.bell()._count == 0


# --------------------------------------------------------------------------- #
# 4. Real «Bütün bildirişlərə bax» — genişlənmiş rejim QALIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_see_all_link_widens_the_history_and_stays_wide_after_a_refresh(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets.primitives import LinkLabel

    panel, header, repo, _context = _wire(theme, [_row()])
    qtbot.addWidget(panel)
    qtbot.addWidget(header)

    see_all = next(w for w in panel.findChildren(LinkLabel) if w.text() == "Bütün bildirişlərə bax")
    see_all._activate()

    # `_show_all` bayrağı QALIR: sonrakı yeniləmə (məs. zəng kliki) də
    # genişlənmiş rejimi saxlamalıdır.
    panel.setVisible(True)
    header.bell()._button.click()

    assert repo.list_calls >= 2


# --------------------------------------------------------------------------- #
# 5. Xəta qolu — real zəng kliki, panel boş qalır, örtük ÇÖKMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_database_failure_leaves_the_real_panel_empty_not_crashed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_g import NotificationPanel

    class _BrokenContext:
        tenant_id = TENANT

        def session(self, **_: Any) -> Any:
            raise RuntimeError("baza əlçatmazdır")

    panel = NotificationPanel(theme)
    header = _header(theme)
    qtbot.addWidget(panel)
    qtbot.addWidget(header)
    controller = NotificationsController(_BrokenContext(), _Actor())  # type: ignore[arg-type]

    controller.attach(panel, header)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert _item_widgets(panel) == []
    assert header.bell()._count == 0


@requires_qt
def test_an_invalid_row_id_from_a_stale_item_does_not_crash_the_real_panel(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`NotificationItem._id` köhnəlmiş sətirdən naməlum sətir gəlsə də ÇÖKMƏMƏLİDİR."""
    panel, header, repo, _context = _wire(theme, [_row()])
    qtbot.addWidget(panel)
    qtbot.addWidget(header)

    panel.notification_clicked.emit("bu-uuid-deyil")  # ÇÖKMƏMƏLİDİR

    assert repo.read_calls == []


# --------------------------------------------------------------------------- #
# 6. Real filtr çipləri — panel özü kontrollerə TOXUNMUR, geriyə uyğunluq
# --------------------------------------------------------------------------- #


@requires_qt
def test_real_filter_chips_only_change_what_is_shown_not_the_unread_badge(
    qtbot, qt_app, theme
) -> None:  # type: ignore[no-untyped-def]
    """Süzgəc VİZUAL sətirləri gizlədir — `set_unread` çipi TOXUNULMAZ qalır."""
    panel, header, _repo, _context = _wire(
        theme, [_row(category="DUAL_CONTROL_PENDING"), _row(category="PAYMENT_REMINDER")]
    )
    qtbot.addWidget(panel)
    qtbot.addWidget(header)
    before = header.bell()._count

    panel.set_filter("approval")
    _settle(qt_app)

    assert len(_item_widgets(panel)) == 1
    assert header.bell()._count == before, "Süzgəc dəyişməsi zəng nişanına TƏSİR ETMƏMƏLİDİR"
