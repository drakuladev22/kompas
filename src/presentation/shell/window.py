"""Çərçivəsiz pəncərə bazası — Faza 4.2.

Spesifikasiya admin ekranları üçün öz başlıq zolağını tələb edir, yəni Windows
çərçivəsi söndürülür (`FramelessWindowHint`). Bunun İKİ nəticəsi var və hər
ikisi burada bərpa olunur:

    1. **Ölçü dəyişdirmə itir.** Çərçivəsiz pəncərənin kənarından tutub
       böyütmək mümkün olmur. `QWindow.startSystemResize()` idarəni OS-ə verir
       — Aero Snap, çox-monitor DPI və toxunma dəstəyi beləliklə saxlanılır.
       Əl ilə `setGeometry()` yazmaq bunların hamısını itirərdi.

    2. **Maksimallaşdırma ekranı örtür.** Çərçivəsiz pəncərə maksimuma
       keçəndə tapşırıq panelinin (taskbar) üstünə çıxır. `showMaximized()`
       əvəzinə `availableGeometry()` işlədilir — nəticə istifadəçinin
       gözlədiyi davranışdır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.presentation.widgets import metrics
from src.presentation.widgets.layout_utils import detach_layout
from src.presentation.widgets.title_bar import TitleBar

if TYPE_CHECKING:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

#: Kənardan neçə piksel məsafədə kursor "ölçü dəyişdirmə" sayılır.
_RESIZE_MARGIN: Final = 6


class FramelessWindow(QWidget):
    """Öz başlıq zolağı olan, ölçüsü dəyişdirilə bilən pəncərə.

    Args:
        title: Başlıq mətni.
        resizable: `False` → kiosk/bloklama ekranları (ölçü sabit).
        show_title_bar: `False` → tam ekran kiosk (başlıq zolağı yoxdur).
    """

    def __init__(
        self,
        *,
        title: str = "KompasOS",
        resizable: bool = True,
        show_title_bar: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AppWindow")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle(title)
        self.setMinimumSize(metrics.WINDOW_MIN_WIDTH, metrics.WINDOW_MIN_HEIGHT)

        self._resizable = resizable
        if resizable:
            # Kənar zonasını tutmaq üçün siçan hərəkəti izlənməlidir.
            self.setMouseTracking(True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._title_bar: TitleBar | None = None
        if show_title_bar:
            self._title_bar = TitleBar(title=title, show_maximize=resizable)
            self._title_bar.minimize_requested.connect(self.showMinimized)
            self._title_bar.maximize_requested.connect(self.toggle_maximized)
            self._title_bar.close_requested.connect(self.close)
            self._layout.addWidget(self._title_bar)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        self._layout.addWidget(self._body, 1)

        self._normal_geometry: QRect | None = None

    # ------------------------------- məzmun --------------------------------- #

    def set_content(self, widget: QWidget) -> None:
        """Başlıq zolağının altındakı əsas məzmunu təyin edir."""
        detach_layout(self._body_layout)
        self._body_layout.addWidget(widget)

    def title_bar(self) -> TitleBar | None:
        """Başlıq zolağı — adı dəyişmək üçün (`"KompasOS — Master"`)."""
        return self._title_bar

    # --------------------------- maksimallaşdırma ---------------------------- #

    def toggle_maximized(self) -> None:
        """Maksimum/normal arasında keçid.

        `showMaximized()` çərçivəsiz pəncərədə tapşırıq panelini örtür, ona
        görə əlçatan sahə (`availableGeometry`) əl ilə tətbiq olunur.
        """
        if self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
            self._normal_geometry = None
            return

        screen = self.screen() or QGuiApplication.primaryScreen()
        self._normal_geometry = self.geometry()
        self.setGeometry(screen.availableGeometry())

    @property
    def is_maximized(self) -> bool:
        return self._normal_geometry is not None

    # --------------------------- ölçü dəyişdirmə ----------------------------- #

    def _edge_at(self, x: int, y: int) -> Qt.Edge | None:
        """Kursorun hansı kənarda olduğunu qaytarır (yoxdursa `None`)."""
        if not self._resizable or self.is_maximized:
            return None

        left = x <= _RESIZE_MARGIN
        right = x >= self.width() - _RESIZE_MARGIN
        top = y <= _RESIZE_MARGIN
        bottom = y >= self.height() - _RESIZE_MARGIN

        edges: Qt.Edge | None = None
        for active, edge in (
            (left, Qt.Edge.LeftEdge),
            (right, Qt.Edge.RightEdge),
            (top, Qt.Edge.TopEdge),
            (bottom, Qt.Edge.BottomEdge),
        ):
            if active:
                edges = edge if edges is None else edges | edge
        return edges

    @staticmethod
    def _cursor_for(edge: Qt.Edge | None) -> Qt.CursorShape:
        if edge is None:
            return Qt.CursorShape.ArrowCursor
        horizontal = bool(edge & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edge & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            # Diaqonal: sol-üst/sağ-alt eyni oxdadır.
            top_left = bool(edge & Qt.Edge.TopEdge) == bool(edge & Qt.Edge.LeftEdge)
            return Qt.CursorShape.SizeFDiagCursor if top_left else Qt.CursorShape.SizeBDiagCursor
        if horizontal:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        position = event.position().toPoint()
        self.setCursor(self._cursor_for(self._edge_at(position.x(), position.y())))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        position = event.position().toPoint()
        edge = self._edge_at(position.x(), position.y())
        handle = self.windowHandle()
        if edge is not None and handle is not None and event.button() is Qt.MouseButton.LeftButton:
            handle.startSystemResize(edge)
            event.accept()
            return
        super().mousePressEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt adlandırması
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)


__all__ = ["FramelessWindow"]
