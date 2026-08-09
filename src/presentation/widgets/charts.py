"""Dashboard qrafikləri — Faza 4.2.

Maket: Qrup C, ekran 09 (Admin/CEO Dashboard).

──────────────────────────────────────────────────────────────────────────────
NİYƏ TƏK RƏNG, HƏR FİLİALA AYRI RƏNG DEYİL
──────────────────────────────────────────────────────────────────────────────
"Cərimələr — filial üzrə" qrafiki BİR seriyadır: eyni ölçü (manat) altı fərqli
filial üçün. Belə halda hər sütuna ayrı rəng vermək məlumat DAŞIMIR — rəng
oxucuya heç nə demir, çünki filialın adı onsuz da altda yazılıb. Üstəlik altı
ayrı rəng rəng-korluğu olan istifadəçidə ayırd edilməz olardı.

Ona görə bütün sütunlar eyni Navy rəngdədir və YALNIZ ən yüksək dəyər amberlə
vurğulanır — bu, "diqqət buraya" mesajıdır və mövqe/uzunluq kodlaması ilə
təkrarlanır (ən hündür sütun onsuz da gözə çarpır), yəni məlumat tək rəngə
bağlı qalmır.

Ox və şəbəkə xətti YOXDUR: dəyərlər hover-də göstərilir. Altı sütunluq
müqayisədə ox işarələri qrafikdən çox yer tutardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ DAİRƏVİ "GAUGE" DEYİL, DÜZ ZOLAQ
──────────────────────────────────────────────────────────────────────────────
İcazə limiti bir nisbətdir (128/200). Dairəvi əqrəb belə nisbətləri dəqiq
oxumağı ÇƏTİNLƏŞDİRİR — insan bucaq uzunluğunu düz uzunluqdan pis qiymətləndirir.
Maket də düz zolaq işlədir: iri faiz rəqəmi + altında incə zolaq.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import Card, muted_label, stretch, title_label

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent, QPaintEvent

    from src.presentation.theme.manager import ThemeManager

#: Sütunun yuxarı künc radiusu (maketdə `border-radius: 6px 6px 0 0`).
_BAR_RADIUS: Final = 6
#: Sütunlar arası boşluq.
_BAR_GAP: Final = 14
#: Etiket sətrinin hündürlüyü.
_LABEL_HEIGHT: Final = 18
#: Zolaqlı ölçənin hündürlüyü (maketdə `height: 10px`).
METER_HEIGHT: Final = 10


class BarDatum(NamedTuple):
    """Bir sütun: etiket, dəyər və göstəriləcək mətn."""

    label: str
    value: float
    display: str


class BarChart(QWidget):
    """Şaquli sütun qrafiki — tək seriya, ən yüksək dəyər vurğulanır.

    Dəyərlər hover-də tooltip kimi görünür; qrafikin üzərində daimi rəqəm
    yazılmır (altı sütunda altı rəqəm qrafiki oxunmaz edərdi).
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        highlight_max: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._data: list[BarDatum] = []
        self._highlight_max = highlight_max
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_data(self, data: list[BarDatum]) -> None:
        self._data = data
        self.setToolTip("")
        self.update()

    def _bar_rects(self) -> list[tuple[QRectF, BarDatum, bool]]:
        """Hər sütunun düzbucaqlısını hesablayır (çəkmə və hover üçün ortaq)."""
        if not self._data:
            return []

        peak = max((d.value for d in self._data), default=0.0)
        if peak <= 0:
            return []

        count = len(self._data)
        total_gap = _BAR_GAP * (count - 1)
        bar_width = max(6.0, (self.width() - total_gap) / count)
        plot_height = max(1, self.height() - _LABEL_HEIGHT - 6)

        highest = max(range(count), key=lambda i: self._data[i].value)

        rects: list[tuple[QRectF, BarDatum, bool]] = []
        for index, datum in enumerate(self._data):
            height = plot_height * (datum.value / peak)
            x = index * (bar_width + _BAR_GAP)
            y = plot_height - height
            rects.append(
                (
                    QRectF(x, y, bar_width, height),
                    datum,
                    self._highlight_max and index == highest,
                )
            )
        return rects

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Sütunlar ÖZ tokenini işlədir: `--color-action-bg` tünd temada
        # amberdir və vurğulanan sütunla eyniləşərək müqayisəni itirirdi.
        base_color = QColor(self._theme.color("--color-chart-bar"))
        peak_color = QColor(self._theme.color("--color-brand-amber"))
        label_color = QColor(self._theme.color("--color-text-muted"))

        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)

        for rect, datum, is_peak in self._bar_rects():
            # Yalnız YUXARI künclər yumrudur — sütun bazis xəttinə oturur.
            path = QPainterPath()
            path.moveTo(rect.left(), rect.bottom())
            path.lineTo(rect.left(), rect.top() + _BAR_RADIUS)
            path.quadTo(rect.left(), rect.top(), rect.left() + _BAR_RADIUS, rect.top())
            path.lineTo(rect.right() - _BAR_RADIUS, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + _BAR_RADIUS)
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            painter.fillPath(path, peak_color if is_peak else base_color)

            painter.setPen(label_color)
            painter.drawText(
                QRectF(rect.left(), self.height() - _LABEL_HEIGHT, rect.width(), _LABEL_HEIGHT),
                Qt.AlignmentFlag.AlignCenter,
                datum.label,
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Sütunun üstündə dəyəri tooltip kimi göstərir."""
        position = event.position()
        for rect, datum, _ in self._bar_rects():
            if rect.left() <= position.x() <= rect.right():
                self.setToolTip(f"{datum.label}: {datum.display}")
                break
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)


class Meter(QWidget):
    """Düz nisbət zolağı — `--color-brand-amber` dolğu, neytral yol."""

    def __init__(
        self,
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._ratio = 0.0
        self.setFixedHeight(METER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_ratio(self, ratio: float) -> None:
        """0.0–1.0 aralığına sıxılmış nisbət."""
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        radius = METER_HEIGHT / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(self.rect()), radius, radius)
        painter.fillPath(track, QColor(self._theme.color("--color-neutral-bg")))

        if self._ratio <= 0:
            return

        fill_width = self.width() * self._ratio
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(0, 0, fill_width, self.height()), radius, radius)
        painter.fillPath(fill, QColor(self._theme.color("--color-brand-amber")))


class StatTile(Card):
    """Bir rəqəmlik göstərici — "Hazırda mağazada / 148 / planlaşdırılan 156-dan".

    Qrafik deyil: bir ədədi qrafiklə göstərmək onu oxumağı çətinləşdirir.
    """

    def __init__(
        self,
        title: str,
        *,
        value: str = "—",
        caption: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(padding=20, spacing=8, parent=parent)
        self.add(muted_label(title, size=13))

        self._value = title_label(value, size=30)
        self.add(self._value)

        self._caption = muted_label(caption)
        self._caption.setVisible(bool(caption))
        self.add(self._caption)
        self.body().addStretch(1)

    def set_value(self, value: str, *, caption: str = "") -> None:
        self._value.setText(value)
        self._caption.setText(caption)
        self._caption.setVisible(bool(caption))


class MeterCard(Card):
    """İcazə limiti kartı — iri faiz + nisbət mətni + zolaq."""

    def __init__(
        self,
        theme: ThemeManager,
        *,
        title: str,
        subtitle: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(padding=20, spacing=12, parent=parent)

        head = QWidget()
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(6)
        head_layout.addWidget(title_label(title, size=15))
        head_layout.addWidget(muted_label(subtitle))
        self.add(head)

        values = QWidget()
        values_layout = QHBoxLayout(values)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(8)

        self._percent = title_label("0%", size=26)
        values_layout.addWidget(self._percent)

        self._fraction = muted_label("")
        values_layout.addWidget(self._fraction)
        values_layout.addWidget(stretch())
        self.add(values)

        self._meter = Meter(theme)
        self.add(self._meter)

    def set_usage(self, used: float, limit: float, *, unit: str = "saat") -> None:
        ratio = used / limit if limit else 0.0
        self._percent.setText(f"{round(ratio * 100)}%")
        self._fraction.setText(f"{used:g} / {limit:g} {unit}")
        self._meter.set_ratio(ratio)


class RankList(Card):
    """Sıralanmış siyahı — "Xal liderləri" (nömrə, ad, dəyər)."""

    def __init__(self, title: str, *, parent: QWidget | None = None) -> None:
        super().__init__(padding=18, spacing=12, parent=parent)
        self.add(title_label(title, size=14))
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(10)
        holder = QWidget()
        holder.setLayout(self._rows_layout)
        self.add(holder)
        self.body().addStretch(1)

    def set_items(self, items: list[tuple[str, str]], *, accent: str) -> None:
        """`items`: (ad, dəyər) cütləri — sıra nömrəsi avtomatik verilir."""
        clear_layout(self._rows_layout)

        for index, (name, value) in enumerate(items, start=1):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

            rank = QLabel(str(index))
            rank.setProperty("variant", "mono")
            rank.setStyleSheet(f"color: {accent};")
            rank_font = rank.font()
            rank_font.setPixelSize(12)
            rank.setFont(rank_font)
            layout.addWidget(rank)

            label = QLabel(name)
            label_font = label.font()
            label_font.setPixelSize(13)
            label.setFont(label_font)
            layout.addWidget(label)
            layout.addWidget(stretch())

            amount = QLabel(value)
            amount_font = amount.font()
            amount_font.setPixelSize(13)
            amount_font.setWeight(QFont.Weight.DemiBold)
            amount.setFont(amount_font)
            layout.addWidget(amount)

            self._rows_layout.addWidget(row)


__all__ = [
    "METER_HEIGHT",
    "BarChart",
    "BarDatum",
    "Meter",
    "MeterCard",
    "RankList",
    "StatTile",
]
