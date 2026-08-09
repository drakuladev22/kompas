"""KompasOS loqo işarəsi — Faza 4.2.

Maketdə loqo Navy yumşaq-künclü kvadratın içində AMBER KOMPAS-dır: nazik
dairə (əqrəb halqası) və onun üstündən 35° bucaqla keçən iynə. Ad da
buradan gəlir — "Kompas".

Şəkil faylı əvəzinə çəkilir, çünki:

    * ölçüsü ekrandan-ekrana dəyişir (splash 96px, giriş kartı 52px,
      pəncərə başlığı 16px) və rastr fayl kiçildilində bulanıqlaşır;
    * tünd/işıqlı temada eyni qalır, yəni iki fayl saxlamağa ehtiyac yoxdur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

#: Maketdəki nisbətlər (52px qutuya görə) — hər ölçüdə eyni qalsın deyə
#: mütləq piksel yox, nisbət saxlanılır.
_RADIUS_RATIO = 14 / 52
_RING_RATIO = 18 / 52
_RING_PEN_RATIO = 2 / 52
_NEEDLE_LENGTH_RATIO = 21 / 52
_NEEDLE_WIDTH_RATIO = 2 / 52
_NEEDLE_ANGLE_DEGREES = 35


class CompassLogo(QWidget):
    """Navy kvadrat + amber kompas işarəsi.

    Args:
        size: Kvadratın kənar uzunluğu.
        background: Kvadratın rəngi — adətən `--color-brand-navy`.
        mark: Kompasın rəngi — adətən `--color-brand-amber`.
    """

    def __init__(
        self,
        *,
        size: int = 52,
        background: str = "#0B1D3A",
        mark: str = "#F5A623",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._background = QColor(background)
        self._mark = QColor(mark)
        self.setFixedSize(size, size)

    def set_colors(self, *, background: str, mark: str) -> None:
        self._background = QColor(background)
        self._mark = QColor(mark)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        size = self._size
        # --- fon kvadratı ---
        path = QPainterPath()
        radius = size * _RADIUS_RATIO
        path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
        painter.fillPath(path, self._background)

        painter.translate(size / 2, size / 2)

        # --- əqrəb halqası ---
        ring_diameter = size * _RING_RATIO
        pen = QPen(self._mark)
        pen.setWidthF(max(1.0, size * _RING_PEN_RATIO))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            QRectF(
                -ring_diameter / 2,
                -ring_diameter / 2,
                ring_diameter,
                ring_diameter,
            )
        )

        # --- iynə ---
        painter.rotate(_NEEDLE_ANGLE_DEGREES)
        needle_length = size * _NEEDLE_LENGTH_RATIO
        needle_width = max(1.0, size * _NEEDLE_WIDTH_RATIO)
        needle = QPainterPath()
        needle.addRoundedRect(
            QRectF(
                -needle_width / 2,
                -needle_length / 2,
                needle_width,
                needle_length,
            ),
            needle_width / 2,
            needle_width / 2,
        )
        painter.fillPath(needle, self._mark)


__all__ = ["CompassLogo"]
