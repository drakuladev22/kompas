"""«Ləğv Et» düyməsi — profil formasının ölü düyməsi (`screens/group_g.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
Düymə yaradılır və panelə əlavə olunurdu, lakin `clicked` HEÇ NƏYƏ bağlı
deyildi. Zərəri «heç nə olmur»dan artıqdır: istifadəçi adını səhv yazır,
«Ləğv Et» basır, sahələr OLDUĞU KİMİ qalır və o, dəyişikliyin atıldığını
sanır — sonra «Yadda Saxla» basanda SƏHV ad yazılır.

Ləğv bazaya toxunmur (hələ heç nə göndərilməyib), ona görə kontroller yox,
ekranın öz vəziyyət bərpasıdır.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _profile(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_g import ProfileScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    return ProfileScreen(
        theme,
        full_name="Aysel Quliyeva",
        role_name="HR Admin",
        store_name="Mağaza 1",
        member_since="2024",
    )


@requires_qt
def test_cancel_restores_the_loaded_values(qt_app) -> None:  # type: ignore[no-untyped-def]
    screen = _profile(qt_app)
    screen.set_account(username="aysel", email="a@b.az", phone="055", password_note="")

    screen._full_name.set_text("SƏHV AD")
    screen._phone.set_text("000")
    screen.revert_edits()

    assert screen.collected() == {"full_name": "Aysel Quliyeva", "phone": "055"}


@requires_qt
def test_cancel_returns_to_the_last_read_not_the_first_open(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Yazıdan sonra kontroller yenidən oxuyur — ləğv ONA qayıtmalıdır."""
    screen = _profile(qt_app)
    screen.set_account(username="aysel", email="a@b.az", phone="055")
    screen.set_identity("Aysel Məmmədova")  # ad dəyişdi və yazıldı

    screen._full_name.set_text("yarımçıq redaktə")
    screen.revert_edits()

    assert screen.collected()["full_name"] == "Aysel Məmmədova"


@requires_qt
def test_the_cancel_button_is_actually_connected(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Qüsurun ÖZÜ: düymə bağlı deyildi — kliki YOXLAYIRIQ, koda baxmırıq."""
    from PySide6.QtWidgets import QPushButton

    screen = _profile(qt_app)
    screen.set_account(username="aysel", email="a@b.az", phone="055")
    screen._full_name.set_text("dəyişdirildi")

    buttons = [b for b in screen.findChildren(QPushButton) if b.text() == "Ləğv Et"]
    assert buttons, "«Ləğv Et» düyməsi tapılmadı"
    buttons[0].click()

    assert screen.collected()["full_name"] == "Aysel Quliyeva"
