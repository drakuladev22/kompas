"""«Nə Yeni?» versiya-qeydləri ekranı — `v2backlog.md` Faza 8.2.

CEO/HR_Admin görünüşündə sadə «versiya-qeydləri» siyahısı; nəşr forması
yalnız `can_publish_whats_new` sahibində render olunur (kontroller
`set_publish_visible(False)` çağırır — «görmək = səlahiyyət», kompasos-ui
bənd 3).

MÖVCUD DİZAYN SİSTEMİ: `Card`, `DataTable`, `Chip`, `FormField`,
`QPlainTextEdit[variant="form"]` (`announcements.py` ilə eyni komponentlər) —
yeni QSS/rəng YOXDUR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import Card, Chip, muted_label, stretch

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class WhatsNewScreen(Screen):
    """Kirayəçi-daxili versiya-qeydləri (`can_view_whats_new`).

    Signals:
        refresh_requested: «Yenilə» düyməsi.
        publish_requested: `(etiket, başlıq, mətn)` — Root/CEO nəşri.
        deactivate_requested: sətrin `[Söndür]` düyməsi (qeyd id).
    """

    refresh_requested = Signal()
    publish_requested = Signal(str, str, str)
    deactivate_requested = Signal(str)

    _COLUMNS: ClassVar[list[Column]] = [
        Column("Versiya", 140),
        Column("Başlıq", 220),
        Column("Mətn"),
        Column("Tarix", 120, mono=True),
        Column("Vəziyyət", 110),
        Column("Əməliyyat", 110),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        # «Yenilə» düyməsi SİYAHININ ÜSTÜNDƏDİR və qəsdən belədir: ekran
        # açıq qalarkən başqa bir Root yeni qeyd nəşr edə bilər, siyahı isə
        # yalnız açılışda oxunur. Düymə əvvəl UNUDULMUŞDU — siqnal təyin
        # olunub, kontroller ona qoşulub, lakin heç bir widget onu YAYMIRDI
        # (`test_signal_wiring_gate` məhz bu boşluğu tutdu: sinif sənədi
        # «Yenilə düyməsi» yazırdı, ekranda isə düymə yox idi).
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(metrics.SPACE_MS)
        toolbar_layout.addWidget(stretch())
        refresh = secondary_button("Yenilə")
        refresh.setAccessibleName("Versiya qeydlərini yenilə")
        refresh.clicked.connect(self.refresh_requested)
        toolbar_layout.addWidget(refresh)
        self.add(toolbar)

        self._table_host = QWidget()
        self._table_layout = QVBoxLayout(self._table_host)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self.add(self._table_host)

        # ---------------- Nəşr forması (Root/CEO) ---------------------------- #
        # Flag-siz istifadəçidə bu kart ÜMUMİYYƏTLƏ qurulmur (kontroller
        # `set_publish_visible(False)` çağırır).
        self._publish_section = QWidget()
        publish_layout = QVBoxLayout(self._publish_section)
        publish_layout.setContentsMargins(0, 0, 0, 0)
        publish_layout.setSpacing(metrics.CARD_CONTENT_SPACING)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        self._version_field = FormField("Versiya etiketi", placeholder="0.2.0 (avqust)")
        card.add(self._version_field)

        self._title_field = FormField("Başlıq")
        card.add(self._title_field)

        card.add(field_label("Mətn"))
        self._body_edit = QPlainTextEdit()
        self._body_edit.setProperty("variant", "form")
        self._body_edit.setMinimumHeight(96)
        self._body_edit.setPlaceholderText("Bu buraxılışda nə dəyişdi…")
        card.add(self._body_edit)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(metrics.SPACE_MS)
        row_layout.addWidget(muted_label("Qeyd bütün «can_view_whats_new» sahiblərinə görünür."))
        row_layout.addWidget(stretch())
        publish = action_button("Nəşr Et")
        publish.clicked.connect(self._on_publish)
        row_layout.addWidget(publish)
        card.add(row)
        publish_layout.addWidget(card)

        self._publish_message = muted_label("")
        publish_layout.addWidget(self._publish_message)
        self.add(self._publish_section)
        self._publish_section.setVisible(True)

    # ------------------------------- oxu -------------------------------------- #

    def set_entries(self, rows: list[dict[str, str]]) -> None:
        """Siyahını yenidən çəkir — açarlar `controllers/whats_new.py::
        _to_row` ilə EYNİDİR (maket ilə birlikdə, CLAUDE.md §6)."""
        clear_layout(self._table_layout)
        if not rows:
            self.show_empty(
                title="Hələ versiya qeydi yoxdur",
                message="Root «Nəşr Et» forması ilə ilk qeydi əlavə edə bilər.",
            )
            return
        self.show_content()
        table = DataTable(self._COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        is_active = row.get("is_active", "1") == "1"
        status = Chip(
            "Aktiv" if is_active else "Söndürülüb",
            "success" if is_active else "neutral",
        )
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        key = row.get("entry_id", "")
        if is_active:
            deactivate = secondary_button("Söndür")
            deactivate.clicked.connect(lambda *_, k=key: self.deactivate_requested.emit(k))
            actions_layout.addWidget(deactivate)
        else:
            actions_layout.addWidget(muted_label("—"))
        return [
            row.get("version", ""),
            row.get("title", ""),
            row.get("body", ""),
            row.get("date", ""),
            status,
            actions,
        ]

    # ------------------------------ nəşr -------------------------------------- #

    def set_publish_visible(self, visible: bool) -> None:
        """Nəşr flag-i yoxdursa forma HEÇ render olunmur."""
        self._publish_section.setVisible(visible)

    def set_publish_message(self, text: str) -> None:
        self._publish_message.setText(text)

    def _on_publish(self) -> None:
        version = self._version_field.text().strip()
        title = self._title_field.text().strip()
        body = self._body_edit.toPlainText().strip()
        if not version or not title or not body:
            self.set_publish_message("Etiket, başlıq və mətn dolu olmalıdır.")
            return
        self.publish_requested.emit(version, title, body)
        self._version_field.input_widget().clear()
        self._title_field.input_widget().clear()
        self._body_edit.clear()


__all__ = ["WhatsNewScreen"]
