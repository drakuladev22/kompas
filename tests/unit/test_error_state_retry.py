"""UI-R4-01 — «Yenidən Cəhd Et» düyməsi ya İŞLƏYİR, ya da ÇƏKİLMİR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
`ErrorState.primary_clicked` bütün layihədə CƏMİ BİR yerdə bağlanmışdı,
halbuki `Screen.show_error(...)` 200-dən çox yerdən çağırılır və hər dəfə
«Yenidən Cəhd Et» yazılmış düymə çəkirdi. Yəni oxu/yazı uğursuzluğunda
istifadəçi tam ekran xəta görür, düyməni basır və HEÇ NƏ olmurdu: siyahı artıq
silinmişdi, geri qayıtmağın yeganə yolu isə başqa ekrana keçib qayıtmaq idi.

İLK HƏLL: `on_retry` verilməyibsə düymə ÜMUMİYYƏTLƏ çəkilmirdi («işləməyən
element boz deyil, render olunmur» qaydası).

SONRA ÖLÇÜLDÜ VƏ QƏRAR DƏYİŞDİ: 250 `show_error` çağırışından yalnız 29-u
`on_retry` ötürür. Qalan ~220 nöqtədə düyməsiz xəta ekranı qalırdı, ekranlar isə
örtükdə KEŞLƏNİR və yalnız `dashboard` qayıdışda təzələnir — yəni tək bir şəbəkə
düşməsi həmin ekranı SESSİYANIN SONUNA QƏDƏR ölü saxlayırdı. Düyməni gizlətmək
qüsuru görünməz etdi, aradan qaldırmadı.

İNDİKİ QAYDA: düymə HƏMİŞƏ çəkilir və HEÇ VAXT ölü deyil — `on_retry` varsa onu
çağırır, yoxdursa `reload_requested` siqnalını yayır və örtük ekranı fabrikadan
yenidən qurur (`AdminShell.rebuild_screen`). Test hər iki yolu kilidləyir.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _screen(theme):  # type: ignore[no-untyped-def]
    from src.presentation.screens.base import Screen

    return Screen(theme)


def _buttons(widget):  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    return [button for button in widget.findChildren(QPushButton) if button.text()]


@requires_qt
def test_an_error_without_a_retry_handler_asks_the_shell_to_rebuild(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`on_retry` yoxdursa düymə QALIR və ekranın bərpasını istəyir.

    Bu, faylın başlığındakı qərar dəyişikliyinin ölçüsüdür: köhnə test
    düymənin OLMAMASINI tələb edirdi, indi isə onun İŞLƏMƏSİNİ tələb edir.
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = _screen(theme)
    reloads: list[int] = []
    screen.reload_requested.connect(lambda: reloads.append(1))

    state = screen.show_error(title="Baza əlçatmazdır", message="Yenidən cəhd edin.")
    buttons = _buttons(state)

    assert [button.text() for button in buttons] == ["Yenidən Cəhd Et"]
    buttons[0].click()
    assert reloads == [1], "düymə basıldı, ekranın bərpası istənmədi"


@requires_qt
def test_a_retry_handler_draws_the_button_and_the_click_calls_it(qt_app) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = _screen(theme)
    calls: list[int] = []

    state = screen.show_error(
        title="Baza əlçatmazdır",
        message="Yenidən cəhd edin.",
        on_retry=lambda: calls.append(1),
    )
    buttons = _buttons(state)

    assert [button.text() for button in buttons] == ["Yenidən Cəhd Et"]
    buttons[0].click()
    assert calls == [1]


@requires_qt
def test_a_secondary_button_is_untouched_by_the_rule(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Qayda YALNIZ əsas düyməyədir — ikinci düymə çağıranın öz məsuliyyətidir."""
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = _screen(theme)

    state = screen.show_error(
        title="Baza əlçatmazdır",
        message="Yenidən cəhd edin.",
        secondary_text="Dəstəyə yaz",
    )

    # Əsas düymə indi HƏMİŞƏ var (bax fayl başlığı), ikinci düymə isə onun
    # YANINDA qalır — qayda ikincisinə toxunmur.
    assert [button.text() for button in _buttons(state)] == ["Yenidən Cəhd Et", "Dəstəyə yaz"]
