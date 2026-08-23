"""Kontekst SPLASH ARXASINDA qurulur — açılışda ağ ekran yoxdur (SETUP-1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
`build_context()` baza hovuzunu açır və bağlantı taymautu 15 saniyəyədəkdir.
Əvvəl o, `main.py`-da PƏNCƏRƏDƏN ƏVVƏL çağırılırdı: server əlçatmazdırsa
istifadəçi həmin müddət ərzində HEÇ NƏ görmürdü — nə splash, nə xəta. Mağaza
işçisi üçün bu, «proqram açılmır» deməkdir və nəticə dəstəyə zəngdir.

İki şey ölçülür:

    1. iş GUI sapında İCRA OLUNMUR (yəni pəncərə donmur);
    2. nasazlıq İTMİR — `StartupError` mətni və növü çağırana qayıdır ki,
       ekran «yenidən cəhd et» ilə «bağlantı ayarları» arasında seçim edə
       bilsin (DB-4 Faza 4).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _application(qt_app: Any) -> Any:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    return KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT, context=None)


@requires_qt
def test_the_context_is_not_built_on_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ağır iş GUI sapında qalsaydı, splash donardı — «Cavab vermir»."""
    from PySide6.QtCore import QThread

    from src.presentation.app import _load_context_behind_splash

    gui_thread = QThread.currentThread()
    seen: dict[str, Any] = {}

    def factory() -> object:
        seen["thread"] = QThread.currentThread()
        return "kontekst"

    context, message, kind, reason = _load_context_behind_splash(
        qt_app, _application(qt_app), factory
    )

    assert seen["thread"] is not gui_thread, "kontekst GUI sapında quruldu — pəncərə donar"
    assert context == "kontekst"
    assert message == ""
    assert kind is None
    assert reason == "", "uğurlu açılışda texniki səbəb OLMAMALIDIR — konsol xəta zolağı göstərməz"


@requires_qt
def test_a_startup_error_keeps_its_message_and_kind(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Nasazlıq sükutla udulmur — ekran ona görə düymə seçir."""
    from src.presentation.app import _load_context_behind_splash
    from src.presentation.composition import StartupError, StartupFailureKind

    def factory() -> object:
        raise StartupError(
            "Baza bağlantısı konfiqurasiya edilməyib",
            user_message="Bağlantı Ayarları ekranından server məlumatlarını daxil edin.",
            kind=StartupFailureKind.CREDENTIALS_MISSING,
        )

    context, message, kind, reason = _load_context_behind_splash(
        qt_app, _application(qt_app), factory
    )

    assert context is None
    assert "Bağlantı Ayarları" in message
    assert kind is StartupFailureKind.CREDENTIALS_MISSING
    # TEXNİKİ səbəb İSTİFADƏÇİ mesajından FƏRQLİDİR: birincisi `Ctrl+Shift+K`
    # konsolunda texnikə, ikincisi fatal ekranda mağaza işçisinə gedir.
    assert reason == "Başlanğıc nasazlığı: Baza bağlantısı konfiqurasiya edilməyib"


@requires_qt
def test_an_unexpected_failure_still_produces_a_screen(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Gözlənilməyən istisna da BOŞ pəncərəyə çevrilməməlidir."""
    from src.presentation.app import _load_context_behind_splash

    def factory() -> object:
        raise RuntimeError("gözlənilməz")

    context, message, kind, reason = _load_context_behind_splash(
        qt_app, _application(qt_app), factory
    )

    assert context is None
    assert message, "istifadəçiyə göstəriləcək mətn boşdur"
    assert kind is None
    assert "gözlənilməz" in reason, "texnikə istisnanın öz mətni çatmalıdır"
