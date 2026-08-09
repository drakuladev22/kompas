"""Cədvəl komponenti — Faza 4.2.

Maketdə cədvəllər (tenant siyahısı, istifadəçilər, audit log, serverlər) EYNİ
quruluşdadır: monoaralıqlı böyük-hərfli sütun başlıqları cədvəlin ÜSTÜNDƏ,
kənarsız; sətirlər isə bir kartın içində, aralarında 1px ayırıcı ilə.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `QTableWidget` DEYİL
──────────────────────────────────────────────────────────────────────────────
`QTableWidget` xanaya yalnız mətn və ya ikon qoymağa imkan verir. Maketdəki
sətirlərdə isə status nöqtəsi + mətn, nişan (chip), avatar + ad, düymə kimi
BİRLƏŞMİŞ xanalar var. `setCellWidget()` ilə bunu qurmaq mümkündür, lakin o
zaman cədvəlin öz seçim/sıralama məntiqi həmin widget-lərlə uyğunsuzlaşır
(klik xanaya yox, içindəki widget-ə düşür).

Ona görə cədvəl adi `QVBoxLayout` sətirlərindən qurulur: hər sətir bir
widget-dir, istənilən məzmunu qəbul edir və kliki bütöv olaraq tutur. Say
minlərlə deyil (21 filial, ~50 server, ~200 istifadəçi), yəni virtuallaşdırma
tələb olunmur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.i18n.text import az_upper
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import Card, Divider

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent

    from src.presentation.theme.manager import ThemeManager


class Column:
    """Sütun tərifi.

    Args:
        title: Başlıq mətni (böyük hərflərə çevrilir).
        width: Sabit en. `None` → qalan yeri tutur (yalnız BİR sütun belə
            ola bilər, əks halda enlər qeyri-müəyyən olur).
    """

    __slots__ = ("title", "width")

    def __init__(self, title: str, width: int | None = None) -> None:
        self.title = title
        self.width = width


class TableRow(QWidget):
    """Bir cədvəl sətri — klik edilə bilən, seçilə bilən.

    Signals:
        clicked: Sətrə klik (detal paneli açmaq üçün).
    """

    clicked = Signal()

    def __init__(
        self,
        columns: list[Column],
        cells: list[QWidget | str],
        theme: ThemeManager,
        *,
        highlighted: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if len(cells) != len(columns):
            raise ValueError(f"Sətirdə {len(cells)} xana var, sütun sayı isə {len(columns)}")

        self._theme = theme
        self._highlighted = highlighted
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(0)

        for column, cell in zip(columns, cells, strict=True):
            widget = self._to_widget(cell)
            if column.width is not None:
                widget.setFixedWidth(column.width)
                layout.addWidget(widget)
            else:
                layout.addWidget(widget, 1)

        self._apply_background()

    def _to_widget(self, cell: QWidget | str) -> QWidget:
        if isinstance(cell, QWidget):
            return cell
        label = QLabel(cell)
        font = label.font()
        font.setPixelSize(13)
        label.setFont(font)
        return label

    def _apply_background(self) -> None:
        # Maketdə seçilmiş/ilk sətir bir ton fərqli fondadır (`#F7F9FC`).
        color = self._theme.color("--color-neutral-bg") if self._highlighted else "transparent"
        self.setStyleSheet(f"background-color: {color};")

    def set_highlighted(self, highlighted: bool) -> None:
        self._highlighted = highlighted
        self._apply_background()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DataTable(QWidget):
    """Başlıq sətri + kart içində sətirlər.

    Signals:
        row_selected: Sətir indeksi.
    """

    row_selected = Signal(int)

    def __init__(
        self,
        columns: list[Column],
        theme: ThemeManager,
        *,
        footnote: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = columns
        self._theme = theme
        self._rows: list[TableRow] = []
        self._selected: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())

        # Sətirlər kartın İÇİNDƏ yaşayır — kartın `padding`-i sıfırdır, çünki
        # boşluq hər sətrin öz `contentsMargins`-indədir (ayırıcı xətt kartın
        # kənarına qədər uzanmalıdır).
        self._card = Card(padding=0, spacing=0)
        self._body = self._card.body()
        layout.addWidget(self._card)

        if footnote:
            from src.presentation.widgets.primitives import muted_label  # noqa: PLC0415

            layout.addWidget(muted_label(footnote))

        layout.addStretch(1)

    def _build_header(self) -> QWidget:
        """Monoaralıqlı, böyük hərfli, kənarsız başlıq sətri."""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(0)

        for column in self._columns:
            label = QLabel(az_upper(column.title))
            label.setProperty("variant", "mono-muted")
            font = label.font()
            font.setPixelSize(11)
            font.setWeight(QFont.Weight.DemiBold)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
            label.setFont(font)
            if column.width is not None:
                label.setFixedWidth(column.width)
                layout.addWidget(label)
            else:
                layout.addWidget(label, 1)

        return header

    # ------------------------------- sətirlər -------------------------------- #

    def add_row(self, cells: list[QWidget | str], *, highlighted: bool = False) -> TableRow:
        """Sətir əlavə edir və onu qaytarır."""
        if self._rows:
            self._body.addWidget(Divider())

        row = TableRow(self._columns, cells, self._theme, highlighted=highlighted)
        index = len(self._rows)
        row.clicked.connect(lambda idx=index: self._on_row_clicked(idx))
        self._body.addWidget(row)
        self._rows.append(row)
        return row

    def clear(self) -> None:
        """Bütün sətirləri silir — süzgəc dəyişdikdə."""
        clear_layout(self._body)
        self._rows.clear()
        self._selected = None

    @property
    def row_count(self) -> int:
        return len(self._rows)

    def _on_row_clicked(self, index: int) -> None:
        self.select(index)
        self.row_selected.emit(index)

    def select(self, index: int) -> None:
        """Sətri seçilmiş kimi işarələyir."""
        for position, row in enumerate(self._rows):
            row.set_highlighted(position == index)
        self._selected = index

    @property
    def selected_index(self) -> int | None:
        return self._selected


__all__ = ["Column", "DataTable", "TableRow"]
