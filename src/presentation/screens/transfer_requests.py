"""Filiallar-arası daimi köçürmə sorğusu ekranları — `v2backlog.md` Faza 3.3.

`annual_leave.py` İLƏ EYNİ İKİ-WIDGET NAXIŞI (BAX HƏMİN FAYLIN BAŞLIĞI):

    `TransferRequestDialog`      → İŞÇİ (kiosk): hədəf filial + səbəb seçir,
                                    sorğu göndərir.
    `TransferRequestInboxScreen` → HR_Admin (`can_approve_transfer_request`):
                                    təsdiq növbəsi.

Yeni QSS/rəng YOXDUR — `Card`, `DataTable`, `QComboBox[variant="form"]`,
`QLineEdit[variant="form"]` TƏKRAR İSTİFADƏ olunur (`v2backlog.md` MƏRKƏZİ
TƏLƏB #2).

──────────────────────────────────────────────────────────────────────────────
GERİ ÇƏKMƏ BURADA DEYİL
──────────────────────────────────────────────────────────────────────────────
`[Sorğunu Geri Çək]` `EmployeeHomeScreen`-in "Filiallar-arası Köçürmə"
kartındadır (`group_a_kiosk.py`), BU FAYLDA YOX — geri çəkmə YALNIZ sorğunu
göndərən işçiyə aiddir (`TransferRequestUseCase.withdraw` başlığı) və işçi
kioskdan kənar bu ekranı ümumiyyətlə görmür (menyu `can_approve_transfer_
request` tələb edir). İki fərqli auditoriyanın əməliyyatını bir ekrana
yığmaq "görmək = səlahiyyət" qaydasını (kompasos-ui skill, bənd 3) DAİMİ
şərtli render koduna çevirərdi.

──────────────────────────────────────────────────────────────────────────────
`effective_date` NİYƏ DİALOQDA YOXDUR
──────────────────────────────────────────────────────────────────────────────
`TransferRequestUseCase.submit`-in `effective_date` arqumenti İSTƏYƏ BAĞLIDIR
— `None` halında təsdiq DƏRHAL tətbiq olunur (ən çox işlədiləcək yol). Gələcək
tarixli planlaşdırma (`apply_scheduled_transfers`) buradan ötürülə bilməz;
lazım olsa, bu dialoqa YENİ sahə kimi əlavə olunmalıdır — hazırkı əhatə
(`v2backlog.md` FAZA 3-ün ekran tapşırığı) yalnız "Göndərmə/təsdiq/rədd/geri
çəkmə" istəyir, planlaşdırılmış tarix seçimini YOX.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import Card, Divider, muted_label, stretch, title_label

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class TransferRequestInboxScreen(Screen):
    """HR_Admin-in köçürmə təsdiq növbəsi — `can_approve_transfer_request`.

    Signals:
        approve_requested: Sətrin `[Təsdiqlə]` düyməsi (sorğu identifikatoru).
        reject_requested: Sətrin `[Rədd Et]` düyməsi (sorğu identifikatoru).
        refresh_requested: `[Yenilə]` — siyahını təzədən oxuyur.

    `AnnualLeaveInboxScreen` İLƏ EYNİ STRUKTUR (səbəb sahəsi cədvəldə deyil,
    `QInputDialog` ilə soruşulur — bax həmin sinfin başlığı).
    """

    approve_requested = Signal(str)
    reject_requested = Signal(str)
    refresh_requested = Signal()

    _COLUMNS: ClassVar[list[Column]] = [
        Column("İşçi"),
        Column("Cari filial", 160),
        Column("Hədəf filial", 160),
        Column("Səbəb"),
        Column("Göndərilib", 150, mono=True),
        Column("Əməliyyat", 210),
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

        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        toolbar_layout.addWidget(refresh)
        self.add(toolbar)

        self._table_host = QWidget()
        self._table_layout = QVBoxLayout(self._table_host)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self.add(self._table_host)

    def set_requests(self, rows: list[dict[str, str]]) -> None:
        """Təsdiq gözləyən sorğuları göstərir.

        Args:
            rows: `id`, `employee`, `from_store`, `to_store`, `reason`,
                `submitted` açarları olan sözlüklər. Açarlar HƏM maket
                (`preview_screens._transfer_requests`), HƏM canlı yol
                (`controllers/transfer_requests.py::_to_inbox_row`) üçün
                EYNİDİR (CLAUDE.md §6).

        Boş siyahı NORMAL haldır — `show_empty`, `show_error` YOX.
        """
        clear_layout(self._table_layout)

        if not rows:
            self.show_empty(
                # "transfer" adlı ikon YOXDUR (`widgets/icons.py`) — "refresh"
                # (`arrow-clockwise`) filiallar-arası HƏRƏKƏTİ ən yaxın təmsil
                # edən MÖVCUD addır, `shift_swaps` menyu ikonu ilə EYNİ seçim.
                icon_name="refresh",
                title="Təsdiq gözləyən köçürmə sorğusu yoxdur",
                message="İşçi kioskundan göndərilən köçürmə sorğuları burada görünür.",
            )
            return

        self._summary.setText(f"{len(rows)} sorğu təsdiq gözləyir")

        table = DataTable(self._COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)
        self.show_content()

    def table_layout(self) -> QVBoxLayout:
        """Cədvəl qabı — testlər sətir sayını buradan oxuyur."""
        return self._table_layout

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        key = row.get("id", "")
        approve = action_button("Təsdiqlə")
        approve.clicked.connect(lambda *_, k=key: self.approve_requested.emit(k))
        actions_layout.addWidget(approve)

        reject = secondary_button("Rədd Et")
        reject.setProperty("variant", "danger")
        reject.clicked.connect(lambda *_, k=key: self.reject_requested.emit(k))
        actions_layout.addWidget(reject)

        return [
            row.get("employee", ""),
            row.get("from_store", ""),
            row.get("to_store", ""),
            row.get("reason", ""),
            row.get("submitted", ""),
            actions,
        ]


class TransferRequestDialog(QDialog):
    """İşçinin `[Köçürmə Sorğusu]` forması — hədəf filial + səbəb.

    Signals:
        submitted: `(to_store_id, reason)`.

    Dialoq BALANSI/UST-ÜSTƏ DÜŞMƏNİ YOXLAMIR — "artıq gözləyən sorğu var"
    qaydası `TransferRequestUseCase.submit`-dədir (bax həmin metodun
    docstring-i). Burada yalnız BOŞ seçim/mətn bloklanır — `AnnualLeaveRequest
    Dialog._on_submit` ilə eyni sərhəd.
    """

    submitted = Signal(str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        stores: list[tuple[str, str]],
        current_store_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """
        Args:
            stores: `(id, ad)` cütləri — CARİ filial ÇIXARILMIŞ (bax
                `controllers/transfer_requests.py::_destination_choices`):
                işçi öz filialına "köçürmə" göndərə bilməz, siyahıda görünməsi
                mənasız seçim təklif edərdi.
            current_store_name: köməkçi mətn üçün ("Cari filial: Nərimanov").
        """
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Köçürmə Sorğusu")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label("Filiallar-arası Köçürmə Sorğusu", size=19))
        hint = "Sorğu HR_Admin təsdiqindən sonra qüvvəyə minir."
        if current_store_name:
            hint = f"Cari filial: {current_store_name}. {hint}"
        card.add(muted_label(hint, size=12))
        card.add(Divider())

        store_box = QWidget()
        store_layout = QVBoxLayout(store_box)
        store_layout.setContentsMargins(0, 0, 0, 0)
        store_layout.setSpacing(8)
        store_layout.addWidget(field_label("Hədəf filial"))
        self._store = QComboBox()
        self._store.setProperty("variant", "form")
        for store_id, name in stores:
            self._store.addItem(name, store_id)
        store_layout.addWidget(self._store)
        card.add(store_box)

        reason_box = QWidget()
        reason_layout = QVBoxLayout(reason_box)
        reason_layout.setContentsMargins(0, 0, 0, 0)
        reason_layout.setSpacing(8)
        reason_layout.addWidget(field_label("Səbəb"))
        self._reason = QLineEdit()
        self._reason.setProperty("variant", "form")
        self._reason.setPlaceholderText("Köçürmə səbəbini qısaca yazın")
        reason_layout.addWidget(self._reason)
        card.add(reason_box)

        self._hint = muted_label("")
        card.add(self._hint)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        submit = action_button("Sorğu Göndər")
        submit.clicked.connect(self._on_submit)
        buttons_layout.addWidget(submit)
        card.add(buttons)

        submit.setDefault(True)
        submit.setAutoDefault(True)
        cancel.setAutoDefault(False)

        QWidget.setTabOrder(self._store, self._reason)
        QWidget.setTabOrder(self._reason, cancel)
        QWidget.setTabOrder(cancel, submit)

    def _on_submit(self) -> None:
        store_id = self._store.currentData()
        reason = self._reason.text().strip()
        if not store_id:
            # Boş siyahı (aktiv filial yoxdur) müdafiə xəttidir — dialoq
            # sükutla bağlanmaz, işçiyə səbəb göstərilir.
            self._hint.setText("Seçilə bilən hədəf filial yoxdur.")
            return
        if not reason:
            self._hint.setText("Səbəb boş buraxıla bilməz.")
            return
        self.submitted.emit(str(store_id), reason)
        self.accept()


__all__ = ["TransferRequestDialog", "TransferRequestInboxScreen"]
