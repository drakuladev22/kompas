"""Custom pəncərə başlığı — Faza 4.2.

Spesifikasiya (bölmə "PLATFORMA QAYDALARI"):

    "Admin ekranları öz custom title bar-ına malikdir: sol küncdə kiçik loqo +
     «KompasOS» mətni, sağ küncdə Windows pəncərə düymələri (—, □, ×)."

──────────────────────────────────────────────────────────────────────────────
SÜRÜKLƏMƏ NİYƏ `startSystemMove()` İLƏDİR
──────────────────────────────────────────────────────────────────────────────
Çərçivəsiz pəncərəni `move()` ilə əl ilə sürükləmək mümkündür, lakin o zaman
Windows-un ÖZ davranışları itir: ekranın kənarına çəkib yarım-ekrana yapışdırma
(Aero Snap), çox-monitorlu DPI keçidi və toxunma ekranında sürükləmə.
`QWindow.startSystemMove()` idarəni OS-ə verir, yəni bu davranışlar pulsuz
gəlir. Uğursuz olarsa (bəzi platformalarda dəstəklənmir) əl ilə sürükləməyə
qayıdılır — ona görə `_drag_origin` hələ də saxlanılır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import WindowButton
from src.presentation.widgets.primitives import plain_label

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent


class TitleBar(QWidget):
    """38px hündürlüyündə pəncərə başlığı.

    Signals:
        minimize_requested: — düyməsi.
        maximize_requested: □ düyməsi (və ya zolağa ikiqat klik).
        close_requested: × düyməsi.
    """

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        *,
        title: str = "KompasOS",
        show_maximize: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        enable_styled_background(self)
        self.setFixedHeight(metrics.TITLEBAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._drag_origin: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(10)

        # Loqo — maketdə 16×16 amber kvadrat, 5px künc.
        logo = QWidget()
        logo.setObjectName("TitleBarLogo")
        logo.setFixedSize(metrics.TITLEBAR_LOGO_SIZE, metrics.TITLEBAR_LOGO_SIZE)
        layout.addWidget(logo)

        self._title = plain_label(title)
        layout.addWidget(self._title)

        layout.addStretch(1)

        self._minimize = WindowButton("minimize")
        self._minimize.clicked.connect(self.minimize_requested)
        layout.addWidget(self._minimize)

        self._maximize = WindowButton("maximize")
        self._maximize.clicked.connect(self.maximize_requested)
        self._maximize.setVisible(show_maximize)
        layout.addWidget(self._maximize)

        self._close = WindowButton("close")
        self._close.clicked.connect(self.close_requested)
        layout.addWidget(self._close)

    # ------------------------------- məzmun --------------------------------- #

    def set_title(self, title: str) -> None:
        """Başlıq mətnini dəyişir — Developer Panelində "KompasOS — Master"."""
        self._title.setText(title)

    # ------------------------------ sürükləmə -------------------------------- #

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is not Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        window = self.window()
        handle = window.windowHandle() if window is not None else None
        if handle is not None and handle.startSystemMove():
            event.accept()
            return

        # Ehtiyat yol — OS sürükləməni idarə etmirsə.
        self._drag_origin = event.globalPosition().toPoint() - window.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if self._drag_origin is None:
            super().mouseMoveEvent(event)
            return
        self.window().move(event.globalPosition().toPoint() - self._drag_origin)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Başlığa ikiqat klik — Windows-da tam ekran/bərpa konvensiyası."""
        if event.button() is Qt.MouseButton.LeftButton and self._maximize.isVisible():
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


__all__ = ["TitleBar"]
