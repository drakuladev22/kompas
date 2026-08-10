"""Örtük və ekranların uçdan-uca yoxlanması — Faza 4.2.

Burada REAL widget-lər qurulur (offscreen platformada) və maketin əsas
davranışları təsdiqlənir:

    * "Görmək = Səlahiyyətin Olması" — sol panel yalnız icazəli bölmələri verir
    * gizli ekrana birbaşa keçid (deep link) bloklanır
    * hər ekran hər iki temada qurula bilir
    * boş/xəta vəziyyətləri Qrup G qaydasına uyğun göstərilir
"""

from __future__ import annotations

import uuid

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
    """ROOT Control Center modulu söndürdükdə bölmə itməlidir.

    Açarlar `FeatureModule` dəyərləridir — `feature_toggles` cədvəli və
    `menu.py` EYNİ ad məkanını işlədir (bax `menu.py` başlığı).
    """
    from src.domain.policies import FeatureModule
    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=preview_data.PREVIEW_NOW,
        # Yalnız Kamera Təsdiqi açıqdır — Tapşırıq modulu söndürülüb.
        enabled_modules=frozenset({FeatureModule.CAMERA_VERIFICATION.value}),
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


# --------------------------------------------------------------------------- #
# ROOT Control Center — üç bölmə (bölmə 3)
# --------------------------------------------------------------------------- #


@requires_qt
def test_root_control_has_all_three_sections(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Limitlər, Feature Toggles və Permission Registry — hamısı olmalıdır."""
    from src.presentation import preview_screens
    from src.presentation.screens.group_d import RootControlScreen

    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    preview_screens.populate("root_control", screen)

    collected = screen.collected()
    assert collected["limits"], "Dinamik limitlər bölməsi boşdur"
    assert collected["modules"], "Modul açarları bölməsi boşdur"
    assert screen._registry_rows.count() > 0, "İcazə registri bölməsi boşdur"


@requires_qt
def test_root_control_uses_the_shared_key_namespace(qtbot, theme) -> None:
    """Ekrandakı açarlar `SystemLimitKey`/`FeatureModule` dəyərləridir.

    Maket öz adlarını işlədəndə ("fines", "appeal_days") panel canlı bazaya
    bağlananda sükutla yanlış açarlara yazardı.
    """
    from src.domain.policies import FeatureModule, SystemLimitKey
    from src.presentation import preview_screens
    from src.presentation.screens.group_d import RootControlScreen

    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    preview_screens.populate("root_control", screen)

    collected = screen.collected()
    known_limits = {key.value for key in SystemLimitKey}
    known_modules = {module.value for module in FeatureModule}

    assert set(collected["limits"]) <= known_limits  # type: ignore[arg-type]
    assert set(collected["modules"]) <= known_modules  # type: ignore[arg-type]


@requires_qt
def test_non_numeric_limit_gets_a_text_field(qtbot, theme) -> None:
    """`LEAVE_ALLOWANCE_SOURCE` ədəd deyil — ekrandan ÇIXARILMAMALIDIR."""
    from src.domain.policies import SystemLimitKey
    from src.presentation.controllers.root_control import limit_row
    from src.presentation.screens.group_d import RootControlScreen

    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    screen.set_limits([limit_row(SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value, "LEAVE_TYPE")])

    collected = screen.collected()
    assert collected["limits"] == {  # type: ignore[comparison-overlap]
        SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value: "LEAVE_TYPE"
    }


@requires_qt
def test_simple_module_toggle_needs_no_confirmation(qtbot, theme) -> None:
    """Shift Swap / Cərimə Modulu üçün sadə toggle kifayətdir (bölmə 3)."""
    from src.domain.policies import FeatureModule
    from src.presentation.screens.group_d import RootControlScreen

    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    screen.set_modules([(FeatureModule.FINE_MODULE.value, "Cərimə modulu", True, False)])

    seen: list[tuple[str, bool, str]] = []
    screen.module_toggled.connect(lambda *args: seen.append(args))  # type: ignore[arg-type]
    screen._module_toggles[FeatureModule.FINE_MODULE.value].setChecked(False)

    assert seen == [(FeatureModule.FINE_MODULE.value, False, "")]


@requires_qt
def test_structural_module_disable_requires_written_confirmation(qtbot, theme, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Kamera Təsdiqi bir kliklə söndürülə BİLMƏZ (bölmə 3).

    Modal ləğv edilsə heç bir siqnal yayılmır və açar geri qayıdır; yazılı
    təsdiq verilsə mətn siqnalla birlikdə use case-ə çatır.
    """
    from PySide6.QtWidgets import QInputDialog

    from src.domain.policies import FeatureModule
    from src.presentation.screens.group_d import RootControlScreen

    key = FeatureModule.CAMERA_VERIFICATION.value
    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    screen.set_modules([(key, "Kamera Təsdiqi", True, True)])

    seen: list[tuple[str, bool, str]] = []
    screen.module_toggled.connect(lambda *args: seen.append(args))  # type: ignore[arg-type]

    # 1) Ləğv → siqnal yoxdur, açar açıq qalır.
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))
    screen._module_toggles[key].setChecked(False)
    assert seen == []
    assert screen._module_toggles[key].isChecked() is True

    # 2) Yazılı təsdiq → mətn siqnalla gedir.
    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Filial bağlanır, kamera axını dayandırılır", True)),
    )
    screen._module_toggles[key].setChecked(False)
    assert len(seen) == 1
    assert seen[0][0] == key
    assert seen[0][1] is False
    assert "Filial bağlanır" in seen[0][2]


# --------------------------------------------------------------------------- #
# Drive razılıq ekranı (miqrasiya 002)
# --------------------------------------------------------------------------- #


@requires_qt
def test_drive_screen_states_switch_between_idle_and_pending(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Razılıq gedərkən düymə bloklanır və ünvan mətn kimi görünür.

    Ünvanın mətn kimi qalması qəsdəndir: kiosk/terminal quraşdırmasında
    `webbrowser.open()` heç nə etməyə bilər və administrator ünvanı başqa
    cihazda açmalıdır (bax ekran docstring-i).
    """
    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    screen.set_active(
        account=None, status_text="Qoşulmayıb", tone="neutral", quota_text="Kvota yoxdur"
    )

    assert screen._connect.isEnabled()
    assert not screen._pending.isVisible()

    screen.show_pending("https://accounts.google.com/o/oauth2/v2/auth?x=1")
    assert not screen._connect.isEnabled()
    assert screen._auth_url.text().startswith("https://accounts.google.com")

    screen.clear_pending()
    assert screen._connect.isEnabled()
    assert screen._auth_url.text() == ""


@requires_qt
def test_drive_screen_button_label_reflects_an_existing_account(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Hesab varsa düymə "Dəyiş" deyir — "Qoş" onu təsadüfən əvəz etməyə çağırardı."""
    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)

    screen.set_active(account=None, status_text="Qoşulmayıb", tone="neutral", quota_text="")
    assert screen._connect.text() == "Google Hesabı Qoş"

    screen.set_active(account="a@b.c", status_text="Aktiv", tone="success", quota_text="")
    assert screen._connect.text() == "Hesabı Dəyiş"


class _StubActor:
    """`has_permission` və `id` — kontrollerin toxunduğu yeganə sahələr."""

    def __init__(self, *, allowed: bool) -> None:
        self.id = uuid.uuid4()
        self._allowed = allowed

    def has_permission(self, flag: str, *, now) -> bool:  # type: ignore[no-untyped-def]
        return self._allowed


@requires_qt
def test_drive_consent_is_blocked_without_the_permission(qtbot, theme, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Menyunun gizlədilməsi kifayət deyil — əməliyyatın özü də bağlanmalıdır."""
    from src.presentation.controllers.drive_connection import DriveConnectionController
    from src.presentation.screens.group_d import DriveConnectionScreen

    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_SECRET", "secret")

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = DriveConnectionController(object(), _StubActor(allowed=False))  # type: ignore[arg-type]
    controller._on_connect(screen)

    assert screen.switcher().current_state() == "error"
    assert controller._flow is None, "Səlahiyyətsiz istifadəçi üçün port AÇILMAMALIDIR"


@requires_qt
def test_drive_consent_reports_missing_google_config(qtbot, theme, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """OAuth açarları yoxdursa səbəb AÇIQ deyilməlidir, düymə sükutla ölməməlidir."""
    from src.presentation.controllers.drive_connection import DriveConnectionController
    from src.presentation.screens.group_d import DriveConnectionScreen

    monkeypatch.delenv("KOMPASOS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("KOMPASOS_GOOGLE_CLIENT_SECRET", raising=False)

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = DriveConnectionController(object(), _StubActor(allowed=True))  # type: ignore[arg-type]
    controller._on_connect(screen)

    assert screen.switcher().current_state() == "error"
    assert controller._flow is None


@requires_qt
def test_drive_consent_starts_a_flow_and_cancel_releases_it(qtbot, theme, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Ləğv həm taymeri dayandırır, həm portu buraxır."""
    from src.presentation.controllers.drive_connection import DriveConnectionController
    from src.presentation.screens.group_d import DriveConnectionScreen

    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_SECRET", "secret")
    # Test brauzer AÇMAMALIDIR.
    monkeypatch.setattr(
        "src.infrastructure.storage.oauth_flow.webbrowser.open", lambda *_a, **_k: True
    )

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = DriveConnectionController(object(), _StubActor(allowed=True))  # type: ignore[arg-type]
    controller._on_connect(screen)

    assert controller._flow is not None
    assert screen._auth_url.text().startswith("https://accounts.google.com")
    assert not screen._connect.isEnabled()

    controller._on_cancel(screen)
    assert controller._flow is None
    assert controller._timer is None
    assert screen._connect.isEnabled()
