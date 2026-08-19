"""UX-1 — kiosk «Üzlə daxil ol» düyməsi ekranı DONDURMUR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
Kamera çəkilişi + 1:N tanıma + 1:1 doğrulama saniyələr çəkir. Kiosk yolunda
heç bir göstərici yox idi: işçi düyməni basırdı, ekran cavabsız qalırdı və o,
düyməni TƏKRAR basırdı — ikinci çəkiliş növbəyə düşürdü. Panel girişində eyni
yol ARTIQ düzgün qurulmuşdu (`LoginScreen.set_busy` + `flush_ui`), kiosk
unudulmuşdu.

Test ekranın ÖZ müqavilələrini ölçür: məşğul vəziyyətdə klaviatura və üz
düyməsi söndürülür, iş bitəndə — uğurlu VƏ uğursuz halda — yenidən açılır.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _pin_pad(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    return PinPadScreen(theme, store_name="Mağaza 1", terminal_name="Terminal A")


@requires_qt
def test_busy_disables_the_keypad_and_the_face_button(qt_app) -> None:  # type: ignore[no-untyped-def]
    screen = _pin_pad(qt_app)

    screen.set_busy(True)

    assert screen.is_busy is True
    assert screen.face_button().isEnabled() is False
    assert all(not button.isEnabled() for button in screen._keys)


@requires_qt
def test_clearing_busy_restores_every_button(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`finally` bloku bunu HƏR halda çağırır — uğursuzluqdan sonra da."""
    screen = _pin_pad(qt_app)

    screen.set_busy(True)
    screen.set_busy(False)

    assert screen.is_busy is False
    assert screen.face_button().isEnabled() is True
    assert all(button.isEnabled() for button in screen._keys)


@requires_qt
def test_busy_shows_a_neutral_message_not_an_error(qt_app) -> None:  # type: ignore[no-untyped-def]
    """«Yoxlanılır…» xəta DEYİL — nöqtələr qırmızıya boyanmamalıdır."""
    screen = _pin_pad(qt_app)

    screen.set_busy(True)

    assert screen._message.text() == "Üz yoxlanılır…"
    assert screen._dots._error is False


@requires_qt
def test_busy_is_independent_from_the_lockout_state(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Bloklama siyasət nəticəsidir, məşğulluq müvəqqəti gözləmədir."""
    screen = _pin_pad(qt_app)

    screen.set_busy(True)
    screen.set_busy(False)

    assert screen.is_locked is False
