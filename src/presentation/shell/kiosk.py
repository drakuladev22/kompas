"""Kiosk pəncərəsi — Faza 4.2.

Spesifikasiya (bölmə "PLATFORMA QAYDALARI"):

    "İSTİSNA: Kiosk Mode ekranları (PIN klaviaturası, İşçi Ana Ekranı) TAM
     EKRAN, çərçivəsiz, toxunma-ilk dizayndadır (paylaşılan mağaza kiosk
     PC-sində istifadə olunur)."

──────────────────────────────────────────────────────────────────────────────
NİYƏ BAĞLAMA DÜYMƏSİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
Kiosk PC-si mağazada işçilərin ümumi istifadəsindədir. Orada "×" düyməsi
olsaydı, hər kəs proqramı bağlaya bilərdi və növbəti işçi giriş qeydiyyatını
apara bilməzdi. Ona görə pəncərə tam ekrandır və yalnız gizli qısayolla
(`Ctrl+Shift+Q`) bağlanır — həmin qısayol mağaza menecerinə verilir.

`Alt+F4` Qt tərəfindən bloklanmır (OS səviyyəsindədir), lakin `closeEvent`
təsdiq tələb edir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.presentation.widgets.layout_utils import detach_layout
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from PySide6.QtGui import QCloseEvent

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Kioskdan çıxış qısayolu — mağaza menecerinə verilir.
EXIT_SHORTCUT = "Ctrl+Shift+Q"


class KioskWindow(QWidget):
    """Tam ekran, çərçivəsiz kiosk pəncərəsi.

    Signals:
        exit_requested: Gizli qısayol basıldı — çağıran tərəf təsdiq istəyir.
    """

    exit_requested = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KioskWindow")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("KompasOS")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._allow_close = False

        shortcut = QShortcut(QKeySequence(EXIT_SHORTCUT), self)
        shortcut.activated.connect(self._on_exit_shortcut)

    def set_content(self, widget: QWidget) -> None:
        """Kiosk məzmununu dəyişir (PIN klaviaturası ↔ İşçi Ana Ekranı)."""
        detach_layout(self._layout)
        self._layout.addWidget(widget)

    def start(self) -> None:
        """Tam ekran rejimində açır."""
        self.showFullScreen()

    def _on_exit_shortcut(self) -> None:
        _security_log.info("KIOSK_EXIT_SHORTCUT")
        self.exit_requested.emit()

    def allow_close(self) -> None:
        """Təsdiqdən sonra bağlanmağa icazə verir."""
        self._allow_close = True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if self._allow_close:
            super().closeEvent(event)
            return
        # Təsadüfi Alt+F4 kiosk terminalını söndürməməlidir.
        _security_log.warning("KIOSK_CLOSE_BLOCKED")
        event.ignore()


__all__ = ["EXIT_SHORTCUT", "KioskWindow"]
