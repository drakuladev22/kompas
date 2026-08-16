"""Ekran-daxili süzgəclərin FAKTİKİ təsiri — «klikləyirəm, heç nə olmur» qüsuru.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
Bir siqnalın elan olunması onun İŞLƏDİYİNİ sübut etmir. Layihədə 171 ekran
siqnalından 32-si `src/` daxilində heç yerdə consume olunmurdu; bir hissəsi
qəsdən belədir (ekran işi ÖZÜ görür, siqnal yalnız məlumat üçündür), qalanı
isə sadəcə ölü idi — istifadəçi düyməni basır, vizual vəziyyət dəyişir,
NƏTİCƏ isə dəyişmir.

Ən aldadıcı forması budur: `set_filter` aktiv çipin rəngini dəyişirdi, yəni
istifadəçi "işlədi" siqnalı alırdı, lakin siyahı olduğu kimi qalırdı. Səhv
görünmür — sadəcə yanlış nəticə göstərilir. `set_store_filter` isə EYNİ
ekranda düzgün yazılmışdı (keşlənmiş sətirləri yenidən süzürdü), yəni qüsur
naxışın özündə deyil, onun bir yerdə tətbiq olunmamasında idi.

Ona görə bu fayl siqnalın YAYILDIĞINI yox, EKRANIN NƏTİCƏSİNİ yoxlayır:
süzgəcdən sonra cədvəldə neçə sətir qalır.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import requires_qt


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _entries() -> list[Any]:
    from src.presentation.screens.group_b import QueueEntry

    def entry(request_id: str, name: str, store: str, kind: str) -> Any:
        return QueueEntry(
            request_id=request_id,
            employee_name=name,
            store_name=store,
            position_name="Satıcı",
            kind=kind,
            timestamp_text="09:14",
            waiting_text="2 dəq",
        )

    return [
        entry("r1", "Rəşad Məmmədov", "Bellona 28 May", "Giriş Təsdiqi"),
        entry("r2", "Aysel Quliyeva", "Bellona 28 May", "Qayıdış Təsdiqi"),
        entry("r3", "Nigar Səfərova", "İstikbal Gənclik", "Giriş Təsdiqi"),
    ]


def _queue(theme: Any) -> Any:
    from src.presentation.screens.group_b import OperatorQueueScreen

    screen = OperatorQueueScreen(
        theme,
        assigned_stores=["Bellona 28 May", "İstikbal Gənclik"],
        store_filter_threshold=1,
    )
    screen.set_entries(_entries())
    return screen


@requires_qt
def test_status_chip_actually_filters_the_visible_rows(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _queue(theme)
    qtbot.addWidget(screen)
    assert screen.visible_rows == 3

    screen.set_filter("check_in")

    # Çipin rəngi deyil, SİYAHI yoxlanılır: iki «Giriş Təsdiqi» qalmalıdır.
    assert screen.visible_rows == 2


@requires_qt
def test_status_chip_can_be_reset_to_all(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _queue(theme)
    qtbot.addWidget(screen)

    screen.set_filter("return")
    assert screen.visible_rows == 1
    screen.set_filter("all")
    assert screen.visible_rows == 3


@requires_qt
def test_status_and_store_filters_combine_with_and(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _queue(theme)
    qtbot.addWidget(screen)

    screen.set_store_filter("Bellona 28 May")
    screen.set_filter("check_in")

    # Kəsişmə: Bellona-nın YALNIZ giriş təsdiqi — bir sətir.
    assert screen.visible_rows == 1


@requires_qt
def test_store_filter_still_works_after_the_status_fix(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Reqressiya qapısı — mağaza süzgəci ARTIQ işləyirdi, sınmamalıdır."""
    screen = _queue(theme)
    qtbot.addWidget(screen)

    screen.set_store_filter("İstikbal Gənclik")

    assert screen.visible_rows == 1


# ---------------------------------------------------------------------------
# İstifadəçilər — axtarış sahəsi
# ---------------------------------------------------------------------------


def _users() -> list[dict[str, str]]:
    return [
        {
            "full_name": "Rəşad Məmmədov",
            "username": "rmammadov",
            "role": "Kassir",
            "store": "Bellona 28 May",
        },
        {
            "full_name": "Aysel Quliyeva",
            "username": "aquliyeva",
            "role": "Satış Məsləhətçisi",
            "store": "İstikbal Gənclik",
        },
        {
            "full_name": "Nigar Səfərova",
            "username": "nsaferova",
            "role": "Kassir",
            "store": "İstikbal Gənclik",
        },
    ]


def _users_screen(theme: Any) -> Any:
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    screen.set_users(_users())
    return screen


@requires_qt
def test_user_search_narrows_the_table_by_name(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _users_screen(theme)
    qtbot.addWidget(screen)
    assert screen.table().row_count == 3

    screen.search_field().setText("aysel")

    assert screen.table().row_count == 1


@requires_qt
def test_user_search_also_matches_role_and_store(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _users_screen(theme)
    qtbot.addWidget(screen)

    screen.search_field().setText("kassir")
    assert screen.table().row_count == 2

    screen.search_field().setText("gənclik")
    assert screen.table().row_count == 2


@requires_qt
def test_user_search_matches_the_visible_username(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Cədvəldə görünən `username` üzrə də axtarılmalıdır."""
    screen = _users_screen(theme)
    qtbot.addWidget(screen)

    screen.search_field().setText("nsaferova")

    assert screen.table().row_count == 1


@requires_qt
def test_user_search_with_no_match_shows_the_empty_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _users_screen(theme)
    qtbot.addWidget(screen)

    screen.search_field().setText("belə adam yoxdur")

    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_clearing_the_search_restores_every_row(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _users_screen(theme)
    qtbot.addWidget(screen)

    screen.search_field().setText("aysel")
    screen.search_field().setText("")

    assert screen.table().row_count == 3


@requires_qt
def test_reloading_users_keeps_the_active_search(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Yazı əməliyyatından sonra siyahı təzələnir — süzgəc itməməlidir."""
    screen = _users_screen(theme)
    qtbot.addWidget(screen)
    screen.search_field().setText("kassir")

    screen.set_users(_users())

    assert screen.table().row_count == 2


@requires_qt
def test_search_signal_is_still_emitted_for_future_consumers(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _users_screen(theme)
    qtbot.addWidget(screen)
    seen: list[str] = []
    screen.search_changed.connect(seen.append)

    screen.search_field().setText("aysel")

    assert seen[-1] == "aysel"


# ---------------------------------------------------------------------------
# Bildiriş paneli — kateqoriya süzgəci
# ---------------------------------------------------------------------------


def _notifications() -> list[dict[str, str]]:
    return [
        {"title": "Cərimə nəşr olundu", "category": "fine", "unread": "1", "time": "10:02"},
        {"title": "İcazə təsdiqi gözləyir", "category": "leave", "unread": "1", "time": "10:05"},
        {"title": "Sistem yeniləndi", "category": "system", "unread": "0", "time": "09:40"},
    ]


def _panel(theme: Any) -> Any:
    from src.presentation.screens.group_g import NotificationPanel

    panel = NotificationPanel(theme)
    panel.set_notifications(_notifications())
    return panel


def _item_count(panel: Any) -> int:
    """Görünən bildiriş sayı.

    `deleteLater()` növbəyə qoyulmuş widget-lər hadisə dövrəsi işləyənə qədər
    `findChildren`-də QALIR — sayğac ölçmədən əvvəl həmin növbəni boşaldır,
    əks halda test köhnə sətirləri "görünən" sayardı.
    """
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from src.presentation.screens.group_g import NotificationItem

    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return len(panel.findChildren(NotificationItem))


@requires_qt
def test_notification_filter_actually_narrows_the_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(theme)
    qtbot.addWidget(panel)
    assert _item_count(panel) == 3

    panel.set_filter("fine")

    assert _item_count(panel) == 1


@requires_qt
def test_notification_filter_returns_to_all(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(theme)
    qtbot.addWidget(panel)

    panel.set_filter("leave")
    assert _item_count(panel) == 1
    panel.set_filter("all")
    assert _item_count(panel) == 3


@requires_qt
def test_empty_filter_result_does_not_lose_the_cached_set(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş nəticədən sonra «Hamısı» ƏVVƏLKİ dəsti göstərməlidir."""
    panel = _panel(theme)
    qtbot.addWidget(panel)

    panel.set_filter("shift")
    assert _item_count(panel) == 0
    panel.set_filter("all")

    assert _item_count(panel) == 3


# ---------------------------------------------------------------------------
# Audit jurnalı — süzgəc və səhifələmə kontrolleri
# ---------------------------------------------------------------------------


class _FakeLimits:
    def get_int(self, _tenant: Any, _key: str, default: int) -> int:
        return default


class _FakeAuditUseCase:
    def __init__(self, total: int = 45) -> None:
        self.calls: list[Any] = []
        self._total = total

    def search(self, *, tenant_id: Any, actor: Any, filters: Any = None) -> Any:
        from src.application.use_cases.audit_query import AuditPage

        self.calls.append(filters)
        return AuditPage(entries=[], total=self._total, filters=filters)


class _FakeSession:
    def __init__(self, use_case: Any) -> None:
        self.audit_query = use_case
        self.tenant_id = "tenant-1"
        self.limits = _FakeLimits()
        self.committed = 0

    def commit(self) -> None:
        self.committed += 1


class _FakeContext:
    def __init__(self, session: Any) -> None:
        self._session = session
        self.opened = 0

    def session(self, *, user_id: Any = None) -> Any:
        from contextlib import contextmanager

        @contextmanager
        def _open() -> Any:
            self.opened += 1
            yield self._session

        return _open()


def _audit_pair(theme: Any) -> tuple[Any, Any, Any]:
    from src.presentation.controllers.audit_log import AuditLogController
    from src.presentation.screens.group_d import AuditScreen

    use_case = _FakeAuditUseCase()
    session = _FakeSession(use_case)
    context = _FakeContext(session)

    class _Actor:
        id = "actor-1"

    screen = AuditScreen(theme, modules=["Davamiyyət", "Cərimə"])
    AuditLogController(context, _Actor()).attach(screen)
    return screen, use_case, session


@requires_qt
def test_audit_filter_change_triggers_a_new_query(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen, use_case, session = _audit_pair(theme)
    qtbot.addWidget(screen)

    screen.filters_changed.emit({"search": "cərimə", "module": "", "critical_only": False})

    assert len(use_case.calls) == 1
    assert use_case.calls[0].search == "cərimə"
    # Baxış faktı da audit-lənir — commit unudulsa həmin iz itərdi.
    assert session.committed == 1


@requires_qt
def test_audit_page_change_keeps_the_active_filter(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen, use_case, _session = _audit_pair(theme)
    qtbot.addWidget(screen)

    screen.filters_changed.emit({"search": "cərimə", "module": "", "critical_only": False})
    screen.page_changed.emit(3)

    assert len(use_case.calls) == 2
    last = use_case.calls[-1]
    assert last.search == "cərimə"  # süzgəc səhifə ilə birlikdə ATILMIR
    assert last.offset == 2 * last.limit


@requires_qt
def test_new_filter_returns_to_the_first_page(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """7-ci səhifədə dar süzgəc seçən istifadəçi boş ekran görməməlidir."""
    screen, use_case, _session = _audit_pair(theme)
    qtbot.addWidget(screen)

    screen.page_changed.emit(5)
    screen.filters_changed.emit({"search": "yeni", "module": "", "critical_only": False})

    assert use_case.calls[-1].offset == 0


@requires_qt
def test_module_selector_placeholder_is_not_sent_as_a_filter(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import ALL_MODULES

    screen, use_case, _session = _audit_pair(theme)
    qtbot.addWidget(screen)

    screen.filters_changed.emit({"search": "", "module": ALL_MODULES, "critical_only": False})

    assert use_case.calls[-1].entity_type is None


def test_audit_row_uses_the_same_keys_as_the_preview_path() -> None:
    """Canlı və maket yolu EYNİ AÇARLARI işlətməlidir (CLAUDE.md bölmə 6)."""
    from datetime import UTC, datetime

    from src.presentation import preview_data
    from src.presentation.controllers.audit_log import entry_row

    class _Entry:
        occurred_at = datetime(2026, 8, 12, 9, 58, tzinfo=UTC)
        actor_name = "Elvin Həsənov"
        action = "Giriş təsdiqləndi"
        entity_type = "Davamiyyət"
        reason = "Aysel Quliyeva · 09:42"

    assert set(entry_row(_Entry()).keys()) == set(preview_data.AUDIT_ENTRIES[0].keys())
