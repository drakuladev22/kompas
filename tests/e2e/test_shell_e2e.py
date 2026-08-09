"""Örtük və ekranların uçdan-uca yoxlanması — Faza 4.2.

Burada REAL widget-lər qurulur (offscreen platformada) və maketin əsas
davranışları təsdiqlənir:

    * "Görmək = Səlahiyyətin Olması" — sol panel yalnız icazəli bölmələri verir
    * gizli ekrana birbaşa keçid (deep link) bloklanır
    * hər ekran hər iki temada qurula bilir
    * boş/xəta vəziyyətləri Qrup G qaydasına uyğun göstərilir
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = [pytest.mark.e2e, pytest.mark.qt]


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    """İşıqlı temada qurulmuş menecer — QSS tətbiq olunmuş şəkildə."""
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


# --------------------------------------------------------------------------- #
# Naviqasiya və icazələr
# --------------------------------------------------------------------------- #


@requires_qt
def test_admin_sees_every_permitted_section(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=preview_data.PREVIEW_NOW,
    )
    qtbot.addWidget(shell)

    keys = shell.sidebar().entry_keys()
    assert "dashboard" in keys
    assert "root_control" in keys
    assert "settings" in keys


@requires_qt
def test_camera_operator_sees_only_its_own_sections(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bölmə 3: icazəsiz maddə boz DEYİL, ÜMUMİYYƏTLƏ yoxdur."""
    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_camera_operator(),
        now=preview_data.PREVIEW_NOW,
    )
    qtbot.addWidget(shell)

    keys = shell.sidebar().entry_keys()
    assert "live_queue" in keys
    assert "fines" in keys
    # Operatorun bu bölmələrə icazəsi yoxdur — panel onları GÖSTƏRMƏMƏLİDİR.
    assert "users" not in keys
    assert "permissions" not in keys
    assert "root_control" not in keys


@requires_qt
def test_deep_link_to_hidden_screen_is_denied(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Menyunun gizlədilməsi kifayət deyil — keçidin özü bağlanmalıdır."""
    from src.presentation import preview_data
    from src.presentation.screens.group_d import RootControlScreen
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_camera_operator(),
        now=preview_data.PREVIEW_NOW,
    )
    qtbot.addWidget(shell)
    shell.register_screen("root_control", lambda: RootControlScreen(theme))

    assert shell.show_screen("root_control") is False


@requires_qt
def test_feature_toggle_hides_module(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """ROOT Control Center modulu söndürdükdə bölmə itməlidir."""
    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=preview_data.PREVIEW_NOW,
        enabled_modules=frozenset({"leave"}),
    )
    qtbot.addWidget(shell)

    keys = shell.sidebar().entry_keys()
    assert "live_queue" in keys, "Aktiv modul görünməlidir"
    assert "tasks" not in keys, "Söndürülmüş modul gizlənməlidir"
    assert "settings" in keys, "Modula bağlı olmayan maddə qalmalıdır"


# --------------------------------------------------------------------------- #
# Ekranlar
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("mode_name", ["light", "dark"])
def test_every_screen_builds_in_both_themes(qtbot, qt_app, mode_name) -> None:  # type: ignore[no-untyped-def]
    """27 ekranın hamısı hər iki palitrada xətasız qurulmalıdır."""
    from src.presentation import preview_data
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(qt_app, preview=True, theme_preference=ThemeMode(mode_name))
    application.show_admin(preview_data.build_admin(), now=preview_data.PREVIEW_NOW)
    shell = application._shell
    assert shell is not None
    qtbot.addWidget(shell)

    for key in shell.sidebar().entry_keys():
        assert shell.show_screen(key), f"'{key}' ekranı açılmadı"


@requires_qt
def test_theme_toggle_switches_palette(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    from src.presentation import preview_data
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT)
    application.show_admin(preview_data.build_admin(), now=preview_data.PREVIEW_NOW)
    shell = application._shell
    assert shell is not None
    qtbot.addWidget(shell)

    assert application.theme().mode is ThemeMode.LIGHT
    application.toggle_theme()
    assert application.theme().mode is ThemeMode.DARK
    application.toggle_theme()
    assert application.theme().mode is ThemeMode.LIGHT


# --------------------------------------------------------------------------- #
# Qrup G — vəziyyətlər
# --------------------------------------------------------------------------- #


@requires_qt
def test_empty_state_is_shown_when_queue_has_no_entries(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_b import OperatorQueueScreen

    screen = OperatorQueueScreen(theme, assigned_stores=["Bellona 28 May"])
    qtbot.addWidget(screen)

    screen.set_entries([])
    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_unassigned_operator_gets_a_different_empty_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş təyinat "növbə boşdur" ilə qarışdırılmamalıdır."""
    from src.presentation.screens.group_b import OperatorQueueScreen, QueueEntry

    screen = OperatorQueueScreen(theme, assigned_stores=[])
    qtbot.addWidget(screen)

    screen.set_entries(
        [
            QueueEntry(
                request_id="1",
                employee_name="Aysel Quliyeva",
                store_name="Bellona 28 May",
                position_name="Satış",
                kind="Giriş Təsdiqi",
                timestamp_text="09:42",
                waiting_text="1 dəq gözləyir",
            )
        ]
    )
    assert screen.switcher().current_state() == "empty"
    assert screen.visible_rows == 0


@requires_qt
def test_error_state_carries_diagnostic_rows(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.base import Screen

    screen = Screen(theme)
    qtbot.addWidget(screen)

    screen.show_error(
        title="Serverə bağlanmaq mümkün olmadı",
        message="Şəbəkə bağlantınızı yoxlayın.",
        details=[("Xəta kodu", "ERR_CONN_TIMEOUT")],
    )
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_loading_state_is_delayed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Maket: skeleton 400 ms-dən əvvəl GÖRÜNMÜR (sayrışmanın qarşısı)."""
    from src.presentation.screens.base import Screen

    screen = Screen(theme)
    qtbot.addWidget(screen)

    screen.show_loading()
    # Taymer hələ işə düşməyib — məzmun göstərilir.
    assert screen.switcher().current_state() == "content"

    # Tez tamamlanan sorğu skeletonu ÜMUMİYYƏTLƏ göstərmir.
    screen.show_content()
    assert screen.switcher().current_state() == "content"


@requires_qt
def test_slow_loading_eventually_shows_skeleton(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.base import LOADING_DELAY_MS, Screen

    screen = Screen(theme)
    qtbot.addWidget(screen)
    screen.show_loading(rows=2)

    def skeleton_visible() -> bool:
        return screen.switcher().current_state() == "loading"

    qtbot.waitUntil(skeleton_visible, timeout=LOADING_DELAY_MS + 1500)


# --------------------------------------------------------------------------- #
# Naviqasiya widget-i
# --------------------------------------------------------------------------- #


@requires_qt
def test_sidebar_marks_the_active_item(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=preview_data.PREVIEW_NOW,
    )
    qtbot.addWidget(shell)

    sidebar = shell.sidebar()
    sidebar.set_active("users")
    assert sidebar.active_key == "users"


@requires_qt
def test_sidebar_collapses(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Spesifikasiya: sol panel daralda bilər."""
    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry
    from src.presentation.widgets import metrics

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=preview_data.PREVIEW_NOW,
    )
    qtbot.addWidget(shell)

    sidebar = shell.sidebar()
    assert sidebar.width() == metrics.SIDEBAR_WIDTH

    sidebar.set_collapsed(True)
    assert sidebar.is_collapsed
    assert sidebar.width() == metrics.SIDEBAR_COLLAPSED_WIDTH
