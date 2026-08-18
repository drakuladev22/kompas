"""Fokus halqası siçan hərəkətindən SONRA yanmır — FOCUS-1.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
İstifadəçinin bildirdiyi şəkil: «daxil ola basanda triggerlenir və ətrafında
portağal rəngli dairə yaranır». Zəncir belədir:

    1. «Daxil Ol» SİÇANLA basılır;
    2. `set_busy(True)` düyməni söndürür (`setEnabled(False)`);
    3. Qt söndürülən fokuslu widget-dən fokusu `focusNextPrevChild()` ilə
       aparır və səbəb kimi `TabFocusReason` yazır;
    4. `KeyFocusRingMixin` səbəbə baxıb «klaviatura» qərarı verir və başlıq
       zolağındakı tema düyməsində halqa yanır.

Səbəb kodu doğrudur — YANILDICI olan onun tək başına istifadəsidir. Ona görə
`_InputModalityTracker` əlavə olundu: sual «fokus necə gəldi?» deyil,
«istifadəçi son olaraq nə ilə işləyirdi?» şəklinə salındı (brauzerlərin
`:focus-visible` qaydası ilə eyni model).

Bu fayl hər iki tərəfi yoxlayır — halqa siçandan sonra YANMIR, klaviaturadan
sonra isə HƏLƏ DƏ yanır. İkincisi olmasa, düzəliş əlçatanlığı sındırardı.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from src.presentation.widgets.buttons import (
    KeyFocusIconButton,
    action_button,
    input_modality_tracker,
)

pytestmark = pytest.mark.unit


def _press_mouse(widget: QWidget) -> None:
    """Faktiki siçan hadisəsi göndərir — izləyici hadisəni GÖRMƏLİDİR."""
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPoint(1, 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _press_key(widget: QWidget) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


class _Panel(QWidget):
    """Söndürülən əsas düymə + zəncirin növbəti elementi (tema düyməsi)."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.submit = action_button("Daxil Ol")
        self.theme = KeyFocusIconButton("sun", "#000000", accessible_name="Tema")
        layout.addWidget(self.submit)
        layout.addWidget(self.theme)
        QWidget.setTabOrder(self.submit, self.theme)


def _panel(qtbot: Any) -> _Panel:
    """Görünən VƏ AKTİV pəncərə.

    `activateWindow()` opsional deyil: Qt fokus hadisələrini yalnız aktiv
    pəncərəyə çatdırır və onsuz `focusInEvent` heç çağırılmır — test də
    «halqa yoxdur» deyib keçərdi, halbuki ölçdüyü şey heç baş verməyib.
    """
    panel = _Panel()
    qtbot.addWidget(panel)
    with qtbot.waitExposed(panel):
        panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    return panel


def test_disabling_a_button_after_a_click_leaves_no_ring(qtbot: Any) -> None:
    """QÜSURUN ÖZÜ: siçan → söndürmə → fokus sıçrayışı → halqa OLMAMALIDIR."""
    panel = _panel(qtbot)
    panel.submit.setFocus(Qt.FocusReason.MouseFocusReason)
    _press_mouse(panel.submit)

    panel.submit.setEnabled(False)  # `set_busy(True)`-un etdiyi

    # Fokusun HƏQİQƏTƏN sıçradığı ayrıca yoxlanılır: sıçramasaydı, aşağıdakı
    # iddia da keçərdi (xüsusiyyətin başlanğıc dəyəri elə `"false"`-dur) və
    # test qüsuru görməzdi.
    assert panel.theme.hasFocus() is True
    assert panel.theme.property("keyfocus") == "false"


def test_the_ring_still_appears_for_a_keyboard_user(qtbot: Any) -> None:
    """Düzəliş klaviatura ilə gəzən istifadəçini KOR QOYMAMALIDIR."""
    panel = _panel(qtbot)
    _press_key(panel.submit)

    panel.theme.setFocus(Qt.FocusReason.TabFocusReason)

    assert panel.theme.hasFocus() is True
    assert panel.theme.property("keyfocus") == "true"


def test_a_mouse_click_directly_on_the_button_draws_no_ring(qtbot: Any) -> None:
    """Siçanla basılan düymənin ÖZÜ də halqasız qalır."""
    panel = _panel(qtbot)
    _press_mouse(panel.theme)

    panel.theme.setFocus(Qt.FocusReason.MouseFocusReason)

    assert panel.theme.hasFocus() is True
    assert panel.theme.property("keyfocus") == "false"


def test_the_tracker_is_installed_once(qtbot: Any) -> None:
    """İkinci nüsxə hər hadisəni iki dəfə emal edər və `findChild` qeyri-müəyyən olardı."""
    first = input_modality_tracker()
    second = input_modality_tracker()

    assert first is not None
    assert first is second


def test_the_modality_starts_as_keyboard() -> None:
    """Heç bir giriş olmayıbsa modallıq NAMƏLUMDUR — halqa GÖSTƏRİLİR.

    Seçim əlçatanlıq tərəfinədir: görünməyən fokus, artıq halqadan pis
    nasazlıqdır (izah `_InputModalityTracker` docstring-ində).
    """
    tracker = input_modality_tracker()

    assert tracker is not None
    # Vəziyyət digər testlərdən qalmış ola bilər — ona görə SİNİFİN defoltu
    # yoxlanılır, canlı nüsxənin cari dəyəri yox.
    fresh = type(tracker)()
    assert fresh.keyboard is True
