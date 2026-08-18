"""«Cihazlar» ekranının aparat izi qapısı (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Aparat izi uyğunsuzluğunun DOMEN tərəfi bağlıdır (`test_device_registry.py`),
lakin admin onu yalnız EKRANDA görürsə həll edə bilər. Burada iki şey
ölçülür və hər ikisi «görmək = səlahiyyətin olması» prinsipinin əksidir:

    1. Düymə YALNIZ uyğunsuzluq görülmüş sətirdə çıxır — hər sətirdə
       görünsəydi, aparat lövbərini dəyişən əməliyyat adi düymə kimi
       oxunardı;
    2. Düymə basılanda siqnal FAKTİKİ yayılır — elan edilmiş, lakin heç
       kimə bağlanmayan siqnal `test_dead_signal_wiring.py` başlığındakı
       «klikləyirəm, heç nə olmur» qüsurudur.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.value_objects.devices import DeviceStatus
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

_ACCEPT_LABEL = "İzi Qəbul Et"


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _screen(theme: Any) -> Any:
    from src.presentation.screens.devices import DeviceAdminScreen

    return DeviceAdminScreen(theme)


def _row(*, pending: bool) -> dict[str, object]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "KASSA-1",
        "store_id": "22222222-2222-2222-2222-222222222222",
        "store": "Mərkəz",
        "type": "İdarə kompüteri",
        "status": DeviceStatus.ACTIVE.value,
        "status_label": "Aktiv",
        "last_seen": "18.08.2026 09:00",
        "fingerprint_pending": pending,
    }


def _button_texts(widget: Any) -> list[str]:
    from PySide6.QtWidgets import QPushButton

    return [button.text() for button in widget.findChildren(QPushButton)]


@requires_qt
def test_the_accept_button_appears_only_when_a_fingerprint_is_waiting(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Adi aktiv cihazda belə düymə OLMAMALIDIR."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    quiet = screen._build_actions(_row(pending=False))
    waiting = screen._build_actions(_row(pending=True))

    assert _ACCEPT_LABEL not in _button_texts(quiet)
    assert _ACCEPT_LABEL in _button_texts(waiting)


@requires_qt
def test_clicking_accept_emits_the_device_id(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Siqnal yayılmasa admin düyməni basar və HEÇ NƏ baş verməz."""
    from PySide6.QtWidgets import QPushButton

    screen = _screen(theme)
    qtbot.addWidget(screen)
    row = _row(pending=True)
    actions = screen._build_actions(row)
    button = next(
        item for item in actions.findChildren(QPushButton) if item.text() == _ACCEPT_LABEL
    )

    emitted: list[str] = []
    screen.accept_fingerprint_requested.connect(emitted.append)
    button.click()

    assert emitted == [row["id"]]


@requires_qt
def test_a_waiting_row_is_highlighted_like_a_blocked_one(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Vurğu olmasaydı düymə uzun siyahıda gözdən qaçardı."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_devices([_row(pending=True), _row(pending=False)])

    assert screen._table.row_count == 2
    assert screen._table._rows[0]._highlighted, "gözləyən sətir vurğulanmayıb"
    assert not screen._table._rows[1]._highlighted, "adi sətir səbəbsiz vurğulanıb"
