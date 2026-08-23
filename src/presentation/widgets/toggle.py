"""Açar/bağla düyməsi (toggle switch) — Faza 4.2.

Maketdə Ayarlar və ROOT İdarə Mərkəzi ekranlarında sürüşən açar işlədilir.
Qt-də hazır belə widget YOXDUR (`QCheckBox` kvadrat qutudur), ona görə
`QAbstractButton` üzərində çəkilir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `QCheckBox`-U QSS İLƏ "AÇAR" KİMİ GÖSTƏRMƏK YOX
──────────────────────────────────────────────────────────────────────────────
`QCheckBox::indicator`-a şəkil vermək mümkündür, lakin o zaman:
    * sürüşmə animasiyası olmur (indikator ani dəyişir),
    * hər tema üçün iki şəkil faylı lazım gəlir.
Çəkmək hər ikisini həll edir və `isChecked()` davranışı `QAbstractButton`-dan
olduğu kimi qalır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QWidget

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

    from src.presentation.theme.manager import ThemeManager

#: Maketdəki ölçülər.
TRACK_WIDTH: Final = 42
TRACK_HEIGHT: Final = 24
KNOB_MARGIN: Final = 3
ANIMATION_MS: Final = 140


class ToggleSwitch(QAbstractButton):
    """Sürüşən açar.

    `QAbstractButton`-dan gəldiyi üçün `setChecked()`, `toggled` siqnalı və
    klaviatura ilə idarə (Space) olduğu kimi işləyir.
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        checked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(TRACK_WIDTH, TRACK_HEIGHT)

        self._offset = 1.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(ANIMATION_MS)
        # Sönən əyri — `theme/transition.py`-dakı EYNİ qərar (qayda 8).
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    # `offset` — 0.0 (sönülü) … 1.0 (yanılı). Animasiya bu xassəni sürüşdürür.
    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def set_theme(self, theme: ThemeManager) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track_on = QColor(self._theme.color("--color-success"))
        track_off = QColor(self._theme.color("--color-neutral-bg"))
        knob_color = QColor(self._theme.color("--color-card-bg"))

        if not self.isEnabled():
            track_on.setAlpha(110)
            track_off.setAlpha(110)

        # İki rəngi qarışdırmaq keçidi yumşaq edir — açar "yolun ortasında"
        # da düzgün görünür.
        track = QColor(
            int(track_off.red() + (track_on.red() - track_off.red()) * self._offset),
            int(track_off.green() + (track_on.green() - track_off.green()) * self._offset),
            int(track_off.blue() + (track_on.blue() - track_off.blue()) * self._offset),
        )

        radius = TRACK_HEIGHT / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, TRACK_WIDTH, TRACK_HEIGHT), radius, radius)

        knob_size = TRACK_HEIGHT - 2 * KNOB_MARGIN
        travel = TRACK_WIDTH - knob_size - 2 * KNOB_MARGIN
        x = KNOB_MARGIN + travel * self._offset
        painter.setBrush(knob_color)
        painter.drawEllipse(QRectF(x, KNOB_MARGIN, knob_size, knob_size))


__all__ = ["ANIMATION_MS", "TRACK_HEIGHT", "TRACK_WIDTH", "ToggleSwitch"]
