"""Tema keçidi GİRİŞ-ÖNCƏSİ ekranlara da çatır — THEME-1.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`KompasApp.set_theme()` üç şey edirdi: QSS-i yenidən tətbiq edir, pəncərə
düymələrinin ikonlarını boyayır və — ƏGƏR ARTIQ QURULUBSA — `AdminShell`-i
xəbərdar edirdi. Sihirbaz, giriş, bağlantı və fatal ekran isə örtükdən
KƏNARDA yaşayır (`FramelessWindow.set_content`) və rənglərinin bir hissəsini
`setStyleSheet` ilə QURULMA ANINDA hesablayır.

Nəticə istifadəçinin bildirdiyi şəkil idi: «sadəcə boxlar ağarır və fontlar
görsənmir» — QSS-dən gələn fon yeni temaya keçir, sətir-içi mətn rəngi isə
köhnəsində qalır.

Düzəliş `FramelessWindow.apply_theme`-dədir: cari məzmun widget-i `apply_theme`
təqdim edirsə, çağırılır. Bu fayl həm həmin ötürməni, həm də hər ekranın
öz rənglərini FAKTİKİ olaraq yenilədiyini yoxlayır — «metod var» iddiası
kifayət deyildi, çünki qüsur məhz metodun OLMAMASI idi.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtWidgets import QWidget

from src.presentation.screens.group_a_entry import (
    AdminLoginScreen,
    ConnectionSettingsScreen,
    FatalStartupScreen,
    FirstRunWizard,
)
from src.presentation.screens.group_e import LicenseInactiveScreen
from src.presentation.shell.window import FramelessWindow
from src.presentation.theme.manager import ThemeManager
from src.presentation.theme.tokens import ThemeMode
from src.presentation.widgets.states import StateIconBox

pytestmark = pytest.mark.unit


def _light() -> ThemeManager:
    return ThemeManager(preference=ThemeMode.LIGHT)


def _dark() -> ThemeManager:
    return ThemeManager(preference=ThemeMode.DARK)


class _Recording(QWidget):
    """`apply_theme` təqdim edən məzmun — ötürmənin ölçüsü."""

    def __init__(self) -> None:
        super().__init__()
        self.received: list[ThemeMode] = []

    def apply_theme(self, theme: ThemeManager) -> None:
        self.received.append(theme.mode)


def test_the_window_forwards_the_theme_to_its_content(qtbot: Any) -> None:
    """Ötürmə OLMASAYDI qüsur qayıdardı — bu, düzəlişin özünün ölçüsüdür."""
    window = FramelessWindow(title="Sınaq", theme=_light())
    qtbot.addWidget(window)
    content = _Recording()
    window.set_content(content)

    window.apply_theme(_dark())

    assert content.received == [ThemeMode.DARK]


def test_content_without_the_hook_is_not_an_error(qtbot: Any) -> None:
    """Sadə widget-lər (məs. boş konteyner) `apply_theme` təqdim etmir.

    Ötürmə onları məcbur etsəydi, hər ekran yalnız tema üçün boş metod
    yazmalı olardı — müqavilə İSTƏYƏ BAĞLIDIR.
    """
    window = FramelessWindow(title="Sınaq", theme=_light())
    qtbot.addWidget(window)
    window.set_content(QWidget())

    window.apply_theme(_dark())  # istisna atmamalıdır


def test_the_wizard_repaints_every_inline_colour(qtbot: Any) -> None:
    """Sol panel, izah və xəta zolağı — üçü də sətir-içidir."""
    light, dark = _light(), _dark()
    wizard = FirstRunWizard(light)
    qtbot.addWidget(wizard)

    before_panel = wizard._panel.styleSheet()
    before_description = wizard._description.styleSheet()

    wizard.apply_theme(dark)

    assert light.color("--color-sidebar-bg") in before_panel
    assert dark.color("--color-sidebar-bg") in wizard._panel.styleSheet()
    assert before_description != wizard._description.styleSheet()
    assert dark.color("--color-text-secondary") in wizard._description.styleSheet()
    assert dark.color("--color-danger-bg") in wizard._error.styleSheet()


def test_the_wizard_keeps_the_current_step_after_a_theme_change(qtbot: Any) -> None:
    """Nişan rəngi yenidən hesablanır, VƏZİYYƏT isə itmir.

    Vəziyyət saxlanmasaydı, tema düyməsi istifadəçini «hansı addımdayam?»
    sualı ilə qoyardı: bütün nişanlar «gözlənilir» rənginə düşərdi.
    """
    light, dark = _light(), _dark()
    wizard = FirstRunWizard(light)
    qtbot.addWidget(wizard)
    wizard._index = 1
    wizard._apply_step()

    wizard.apply_theme(dark)

    current = wizard._steps[1]
    assert current._state == "current"
    assert dark.color("--color-action-bg") in current._badge.styleSheet()


def test_the_login_screen_repaints_its_footer(qtbot: Any) -> None:
    light, dark = _light(), _dark()
    screen = AdminLoginScreen(light)
    qtbot.addWidget(screen)

    screen.apply_theme(dark)

    assert dark.color("--color-text-secondary") in screen._footer.styleSheet()


def test_the_fatal_screen_repaints_its_detail(qtbot: Any) -> None:
    """Çıxılmaz ekranda mətn oxunmasa, səbəb də görünmür."""
    light, dark = _light(), _dark()
    screen = FatalStartupScreen(light, message="Baza əlçatmazdır")
    qtbot.addWidget(screen)

    screen.apply_theme(dark)

    assert dark.color("--color-text-secondary") in screen._detail.styleSheet()


def test_the_connection_screen_keeps_the_error_colour_across_a_theme_change(
    qtbot: Any,
) -> None:
    """Xəta mesajı tema keçidində NEYTRAL rəngə düşməməlidir.

    Düşsəydi, «bağlantı alınmadı» sətri adi izah mətninə bənzəyər və
    istifadəçi problemi həll olunmuş sayardı.
    """
    light, dark = _light(), _dark()
    screen = ConnectionSettingsScreen(light)
    qtbot.addWidget(screen)
    screen.set_error("Server cavab vermir")

    screen.apply_theme(dark)

    assert dark.color("--color-danger") in screen._status.styleSheet()


def test_the_connection_screen_keeps_a_neutral_status_neutral(qtbot: Any) -> None:
    light, dark = _light(), _dark()
    screen = ConnectionSettingsScreen(light)
    qtbot.addWidget(screen)
    screen.set_status("Yoxlanılır…")

    screen.apply_theme(dark)

    assert dark.color("--color-text-secondary") in screen._status.styleSheet()


def test_the_license_block_screen_repaints(qtbot: Any) -> None:
    """Bloklama ekranı çıxışsızdır, LAKİN tema düyməsi hələ də işləkdir."""
    light, dark = _light(), _dark()
    screen = LicenseInactiveScreen(
        light,
        reason="Ödəniş gözlənilir",
        deactivated_at="12.08.2026",
        installation_id="0c298b71",
    )
    qtbot.addWidget(screen)

    screen.apply_theme(dark)

    assert dark.color("--color-text-secondary") in screen._message.styleSheet()
    assert dark.color("--color-danger-bg") in screen._icon_box.styleSheet()


def test_the_state_icon_box_repaints_background_and_glyph(qtbot: Any) -> None:
    """İkon PİKSEL şəklidir — QSS onu boyamır, yenidən çəkilməlidir.

    Fon rəngi dəyişib ikon köhnə qalsaydı, nəticə tünd fonda tünd nişan
    olardı: qutu görünür, içindəki isə yox.
    """
    light, dark = _light(), _dark()
    box = StateIconBox("lock", light, tone="danger")
    qtbot.addWidget(box)
    before = box._glyph.pixmap().toImage()

    box.apply_theme(dark)

    assert dark.color("--color-danger-bg") in box.styleSheet()
    assert box._glyph.pixmap().toImage() != before
