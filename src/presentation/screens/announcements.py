"""Elan (Broadcast) idarəetmə ekranı — #19, kompasos11.md Faza 8.

Maketdə AYRICA fayl kimi verilməyib (Qrup A–I-də yoxdur) — bu, Faza 8-in
`can_broadcast_announcements` sahibi üçün YENİ funksiyadır. Mövcud dizayn
dilini (`Card`, `DataTable`, `FormField`, `Chip`) TƏKRAR İSTİFADƏ edir —
`group_h.CatalogScreen`/`CatalogEntryDialog` ilə EYNİ vizual naxış.

──────────────────────────────────────────────────────────────────────────────
BU, DƏSTƏK ÇATI DEYİL — CAVAB SAHƏSİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
`AnnouncementComposeDialog`-da mesaj YALNIZ YAZILIR, heç bir "thread"/"cavab"
UI elementi YOXDUR. Siyahı sətirlərinin YEGANƏ əməliyyatı "Geri Çək"dir
(soft delete) — redaktə düyməsi YOXDUR, çünki elanın mətni yaradıldıqdan
sonra dəyişmir (`AnnouncementUseCase.broadcast` başlığı).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.presentation.i18n import tr
from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    muted_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: `AnnouncementScope` dəyərlərinin Azərbaycanca etiketi — ekran domen enum-unu
#: TANIMIR (yalnız sətir işlədir, `AnnouncementDraft.scope` use case qatında
#: qurulur), ona görə uyğunlaşma burada, sabit lüğətlə edilir.
SCOPE_ALL = "ALL"
SCOPE_STORE_LIST = "STORE_LIST"


class AnnouncementsScreen(Screen):
    """Elan siyahısı + "Yeni Elan" düyməsi.

    Signals:
        create_requested: "Yeni Elan" düyməsi — kontroller dialoqu özü qurur
            (`OpenShiftPostDialog` ilə eyni naxış, bax `controllers/open_shift.py`).
        withdraw_requested: Sətir açarı (elan ID-si) — "Geri Çək".
    """

    create_requested = Signal()
    withdraw_requested = Signal(str)

    #: `ClassVar` — `Column` siyahısı bütün nüsxələr arasında PAYLAŞILA bilər
    #: (heç bir nüsxə onu dəyişmir), sadə mutable class atributu isə statik
    #: analizatorda "təsadüfən paylaşılan vəziyyət" xəbərdarlığı doğurur.
    _COLUMNS: ClassVar[list[Column]] = [
        Column("Başlıq"),
        Column("Əhatə", 160),
        Column(tr("common.date"), 150, mono=True),
        Column("Vəziyyət", 110),
        Column(tr("common.action"), 140),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(metrics.SPACE_MS)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())

        create = action_button(
            "Yeni Elan", icon_name="plus", icon_color=theme.color("--color-action-text")
        )
        create.clicked.connect(self.create_requested)
        toolbar_layout.addWidget(create)
        self.add(toolbar)

        self._table_host = QWidget()
        self._table_layout = QVBoxLayout(self._table_host)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self.add(self._table_host)

    def set_announcements(self, rows: list[dict[str, str]]) -> None:
        """Siyahını yenidən çəkir.

        Args:
            rows: `id`, `title`, `scope_text`, `date`, `is_active` (`"1"`/`"0"`)
                açarları — açarlar `controllers/announcements.py::_to_admin_row`
                ilə EYNİDİR (CLAUDE.md §6).
        """
        clear_layout(self._table_layout)

        if not rows:
            self.show_empty(
                icon_name="bell",
                title="Hələ elan verilməyib",
                message="«Yeni Elan» düyməsi ilə bütün mağazalara və ya seçilmiş "
                "mağazalara göstəriş göndərin.",
            )
            return

        active_count = sum(1 for row in rows if row.get("is_active", "1") == "1")
        self._summary.setText(
            f"{len(rows)} elan — {active_count} aktiv, {len(rows) - active_count} geri çəkilib"
        )

        table = DataTable(self._COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)
        self.show_content()

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        is_active = row.get("is_active", "1") == "1"
        status = Chip(
            "Aktiv" if is_active else "Geri çəkilib", "success" if is_active else "neutral"
        )

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        key = row.get("id", "")
        if is_active:
            withdraw = secondary_button("Geri Çək")
            withdraw.clicked.connect(lambda *_, k=key: self.withdraw_requested.emit(k))
            actions_layout.addWidget(withdraw)
        else:
            actions_layout.addWidget(muted_label("—"))

        return [
            row.get("title", ""),
            row.get("scope_text", ""),
            row.get("date", ""),
            status,
            actions,
        ]


class AnnouncementComposeDialog(QDialog):
    """Yeni elan forması — başlıq, mətn, əhatə, mağaza seçimi.

    Signals:
        submitted: `(title, message, scope, store_ids)` — `store_ids`
            `STORE_LIST` seçildikdə YOXLANILMIŞ mağaza ID-lərinin siyahısıdır,
            `ALL`-da HƏMİŞƏ boşdur (ekran domen qaydasını TƏKRARLAMIR, sadəcə
            boş siyahı göndərir — `AnnouncementDraft`/`Announcement` STORE_LIST
            üçün boş siyahını rədd edir, `pos_threshold.py` başlığındakı
            "dialoq domen qaydasını yoxlamır" prinsipi).
    """

    submitted = Signal(str, str, str, list)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        stores: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Yeni Elan")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # VİZUAL FAZA #1 — dialoqun BÜTÖV məzmun kartı, BİR dəfə (dialoq
        # açılanda) qurulur, loop-da DEYİL.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label("Yeni Elan", size=19))

        self._title = FormField("Başlıq")
        card.add(self._title)

        card.add(field_label("Mətn"))
        self._message = QPlainTextEdit()
        self._message.setProperty("variant", "form")
        self._message.setMinimumHeight(112)
        self._message.setPlaceholderText("Elanın tam mətni…")
        card.add(self._message)

        card.add(field_label("Əhatə"))
        scope_row = QWidget()
        scope_layout = QHBoxLayout(scope_row)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(16)
        self._scope_all = QRadioButton("Bütün mağazalar")
        self._scope_store_list = QRadioButton("Seçilmiş mağazalar")
        self._scope_all.setChecked(True)
        self._scope_group = QButtonGroup(self)
        self._scope_group.addButton(self._scope_all)
        self._scope_group.addButton(self._scope_store_list)
        scope_layout.addWidget(self._scope_all)
        scope_layout.addWidget(self._scope_store_list)
        scope_layout.addWidget(stretch())
        card.add(scope_row)

        self._store_list = QListWidget()
        self._store_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._store_list.setMaximumHeight(160)
        self._store_list.setEnabled(False)
        for store_id, store_name in stores:
            item = QListWidgetItem(store_name)
            item.setData(Qt.ItemDataRole.UserRole, store_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._store_list.addItem(item)
        card.add(self._store_list)
        self._scope_store_list.toggled.connect(self._store_list.setEnabled)

        self._error = muted_label("")
        self._error.setProperty("variant", "danger-text")
        self._error.setVisible(False)
        card.add(self._error)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button(tr("common.decline"))
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        submit = action_button("Yayımla")
        submit.clicked.connect(self._on_submit)
        submit.setDefault(True)
        submit.setAutoDefault(True)
        cancel.setAutoDefault(False)
        buttons_layout.addWidget(submit)
        card.add(buttons)

        self._title.focus_input()

    def _on_submit(self) -> None:
        title = self._title.text().strip()
        message = self._message.toPlainText().strip()
        scope = SCOPE_STORE_LIST if self._scope_store_list.isChecked() else SCOPE_ALL

        self._title.clear_error()
        self._error.setVisible(False)
        if not title:
            self._title.set_error("Başlıq məcburidir")
            return
        if not message:
            self._error.setText("Elan mətni məcburidir.")
            self._error.setVisible(True)
            return

        store_ids: list[str] = []
        if scope == SCOPE_STORE_LIST:
            store_ids = [
                str(self._store_list.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self._store_list.count())
                if self._store_list.item(i).checkState() == Qt.CheckState.Checked
            ]
            if not store_ids:
                self._error.setText("Ən azı bir mağaza seçin.")
                self._error.setVisible(True)
                return

        self.submitted.emit(title, message, scope, store_ids)
        self.accept()


__all__ = ["SCOPE_ALL", "SCOPE_STORE_LIST", "AnnouncementComposeDialog", "AnnouncementsScreen"]
