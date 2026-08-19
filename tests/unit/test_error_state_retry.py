"""UI-R4-01 — «Yenidən Cəhd Et» düyməsi ya İŞLƏYİR, ya da ÇƏKİLMİR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
`ErrorState.primary_clicked` bütün layihədə CƏMİ BİR yerdə bağlanmışdı,
halbuki `Screen.show_error(...)` 200-dən çox yerdən çağırılır və hər dəfə
«Yenidən Cəhd Et» yazılmış düymə çəkirdi. Yəni oxu/yazı uğursuzluğunda
istifadəçi tam ekran xəta görür, düyməni basır və HEÇ NƏ olmurdu: siyahı artıq
silinmişdi, geri qayıtmağın yeganə yolu isə başqa ekrana keçib qayıtmaq idi.

Bu, ekranların «görmək = səlahiyyətin olması» qaydası ilə eyni ailədəndir:
işləməyən element boz DEYİL, ÜMUMİYYƏTLƏ render olunmamalıdır. Test hər iki
istiqaməti kilidləyir — `on_retry` yoxdursa düymə YOXDUR, varsa düymə HƏQİQƏTƏN
həmin funksiyanı çağırır.
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
def test_an_error_without_a_retry_handler_draws_no_dead_button(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Qüsurun ÖZÜ: düymə çəkilirdi, heç nəyə bağlı deyildi."""
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = _screen(theme)

    state = screen.show_error(title="Baza əlçatmazdır", message="Yenidən cəhd edin.")

    assert _buttons(state) == []


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

    assert [button.text() for button in _buttons(state)] == ["Dəstəyə yaz"]
