"""Header-dəki hesab menyusu — «Çıxış» (RECOVERY-1 Faza 1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Kiosk ekranında «Çıxış» İLK GÜNDƏN var (`group_a_kiosk.py`), admin panelində
isə YOX İDİ: bir dəfə girən adam proqramı tamamilə bağlamadan hesabı dəyişə
bilmirdi. Paylaşılan mağaza kompüterində bu, real problemdir — növbə
dəyişəndə ikinci işçi birincinin sessiyası ilə işləyər və HƏR əməliyyat SƏHV
adama yazılar.

Menyu iki şeyi ölçür: maddələr mövcuddur və siqnal FAKTİKİ yayılır. İkincisi
olmasa, düymə basılar və heç nə baş verməzdi — `test_dead_signal_wiring.py`
başlığındakı qüsur sinfi.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _header(theme: Any) -> Any:
    from src.presentation.widgets.page_header import PageHeader

    # Tokenlər `AdminShell`-dəki ilə EYNİDİR: test başqa token seçsəydi,
    # header burada bir cür, tətbiqdə başqa cür görünərdi.
    return PageHeader(
        icon_color=theme.color("--color-nav-item-text"),
        badge_bg=theme.color("--color-brand-amber"),
        badge_fg=theme.color("--color-brand-navy"),
        surface_color=theme.color("--color-header-bg"),
        avatar_bg=theme.color("--color-neutral-bg"),
        avatar_fg=theme.color("--color-text-primary"),
        dark_mode=False,
    )


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


@requires_qt
def test_the_account_menu_offers_profile_and_logout(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """İki maddə: mövcud «Profil» axını POZULMUR, «Çıxış» ƏLAVƏ olunur."""
    header = _header(theme)
    qtbot.addWidget(header)

    labels = [action.text() for action in header.account_menu().actions()]

    assert labels == ["Profil", "Çıxış"]


@requires_qt
def test_choosing_logout_emits_the_signal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Siqnal yayılmasa düymə ölüdür — istifadəçi basar, sessiya qalar."""
    header = _header(theme)
    qtbot.addWidget(header)
    fired: list[str] = []
    header.logout_requested.connect(lambda: fired.append("çıxış"))

    logout = next(a for a in header.account_menu().actions() if a.text() == "Çıxış")
    logout.trigger()

    assert fired == ["çıxış"]


@requires_qt
def test_choosing_profile_still_navigates(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """MÖVCUD DAVRANIŞ: `profile_clicked` örtüyü «profile» ekranına aparır."""
    header = _header(theme)
    qtbot.addWidget(header)
    fired: list[str] = []
    header.profile_clicked.connect(lambda: fired.append("profil"))

    profile = next(a for a in header.account_menu().actions() if a.text() == "Profil")
    profile.trigger()

    assert fired == ["profil"]


@requires_qt
def test_the_user_name_is_still_readable_by_the_shell(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`app.py` adı `user_name()` ilə oxuyur — menyuya keçid onu POZMAMALIDIR."""
    header = _header(theme)
    qtbot.addWidget(header)

    header.set_user("Aysel Quliyeva")

    assert header.user_name() == "Aysel Quliyeva"


@requires_qt
def test_the_shell_forwards_the_logout_request(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Örtük siqnalı ötürməsə, tətbiq onu heç vaxt eşitməz."""
    from datetime import UTC, datetime

    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )
    qtbot.addWidget(shell)
    fired: list[str] = []
    shell.logout_requested.connect(lambda: fired.append("çıxış"))

    logout = next(a for a in shell.header().account_menu().actions() if a.text() == "Çıxış")
    logout.trigger()

    assert fired == ["çıxış"]


@requires_qt
def test_logging_out_clears_the_session_and_returns_to_login(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Sessiya təmizlənməsə, «çıxış» yalnız EKRAN dəyişdirərdi.

    Paylaşılan mağaza kompüterində bu, ən təhlükəli forma olardı: ikinci işçi
    giriş ekranını görər, lakin tətbiq hələ də BİRİNCİNİN kimliyini daşıyardı.
    """
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(
        qt_app, preview=True, theme_preference=ThemeMode.LIGHT, context=None
    )
    shown: list[str] = []
    monkeypatch.setattr(application, "show_login", lambda: shown.append("login"))
    application._current_employee = object()  # type: ignore[assignment]

    application.logout()

    assert application._current_employee is None
    assert application._shell is None
    assert shown == ["login"]
