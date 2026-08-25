"""İşdən çıxma checklist-i — `v2backlog.md` Faza 3.4.

`AnnualLeaveRequestDialog`/`field_reports.py`-nin cavablama sətri (`QRadioButton`
+ `QButtonGroup`) İLƏ EYNİ dizayn dili TƏKRAR İSTİFADƏ olunur (`v2backlog.md`
MƏRKƏZİ TƏLƏB #2) — yeni QSS/rəng YOXDUR.

──────────────────────────────────────────────────────────────────────────────
BU DİALOQ ADDIM-ADDIM (WIZARD) DEYİL, TƏK-SƏHİFƏLİK SİYAHIDIR
──────────────────────────────────────────────────────────────────────────────
`field_reports.py`-nin `store_audit`/`incident_report` checklist-i ADDIM-ADDIM
göstərilir, çünki bəndlər ONLARCA ola bilər və hər biri foto/qeyd tələb edir.
Offboarding checklist-i isə Root-un yazdığı QISA bir siyahıdır (adətən
3–8 bənd, `avadanlıq/son-haqq-hesab/çıxış-müsahibəsi` kateqoriyaları) — HR
bir baxışda hamısını görməlidir ki, hansı bəndin BAĞLAYICI (`is_blocking`)
olduğunu qabaqcadan qiymətləndirə bilsin.

──────────────────────────────────────────────────────────────────────────────
`[Checklist-i Bağla]` NİYƏ SÜKUTLA SÖNDÜRÜLMÜR
──────────────────────────────────────────────────────────────────────────────
`team-lead`-in AÇIQ göstərişi: bağlayıcı bənd həll olunmayanda düymə BOZ
edilmir — HR onu basa bilir və `ChecklistNotCompletableError` AÇIQ mesajla
(`set_message`) qayıdır, hansı bəndlərin çatışmadığı sadalanır. Səbəb
`kompasos-ui` bənd 3-ün ƏKSİ görünsə də FƏRQLİDİR: "görmək = səlahiyyət"
İCAZƏYƏ aiddir, bu isə DOMEN VƏZİYYƏTİDİR (bənd sonradan cavablana bilər) —
düymənin daim basıla bilməsi HR-a "niyə bağlanmır?" sualının CAVABINI verir,
sükutla boz düymə isə sualı VERMƏYƏ BELƏ İMKAN verməzdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    muted_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: `ChecklistItemCategory.value` → Azərbaycanca ad. `catalog_management.py`-dakı
#: `ChecklistItemTemplateUseCase`-in "Faza 3.4 + 4.1 ORTAQ" başlığı ilə eyni
#: sözlük — YENİ kateqoriya gələndə (Faza 4.1, BU sahənin işi DEYİL) burada
#: DA əlavə olunmalıdır, əks halda köhnə ad göstərilər.
_CATEGORY_LABELS: Final[dict[str, str]] = {
    "EQUIPMENT": "Avadanlıq",
    "SETTLEMENT": "Son Haqq-Hesab",
    "EXIT_INTERVIEW": "Çıxış Müsahibəsi",
}


class OffboardingChecklistDialog(QDialog):
    """Deaktivasiyadan sonra açılan checklist — Root şablonundan gələn bəndlər.

    Signals:
        item_answered: `(item_id, passed, notes)` — bir sətrin Keçdi/Uğursuz
            seçimi DƏYİŞDİKDƏ. Hər dəyişiklik DƏRHAL yazılır (bax kontroller
            başlığı) — `[Bağla]`-nı gözləmir, çünki HR pəncərəni bağlasa da
            (məs. "Sonra") artıq cavablanmış bəndlər İTMƏMƏLİDİR.
        complete_requested: `[Checklist-i Bağla]`.
    """

    item_answered = Signal(str, bool, str)
    complete_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employee_name: str,
        items: list[dict[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        """
        Args:
            items: `id`, `position_no`, `category`, `item_text`,
                `is_blocking` (`"1"`/`"0"`), `passed` (`"1"`/`"0"`/`""` —
                boş = cavabsız), `notes` açarlı sözlüklər, sıra ARTIQ
                `position_no`-ya görə düzülüb (bax `controllers/user_
                lifecycle.py::_to_checklist_row`).
        """
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(f"İşdən Çıxma Checklist-i — {employee_name}")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label("İşdən Çıxma Checklist-i", size=19))
        card.add(
            muted_label(
                "Bəndləri işarələyin. Bağlayıcı (✱) bəndlər həll olunmadan "
                "checklist bağlana bilməz.",
                size=12,
            )
        )
        card.add(Divider())

        for item in items:
            card.add(self._build_row(item))
            card.add(Divider())

        self._message = muted_label("")
        self._message.setWordWrap(True)
        card.add(self._message)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())

        close = secondary_button("Sonra")
        close.clicked.connect(self.accept)
        buttons_layout.addWidget(close)

        complete = action_button("Checklist-i Bağla")
        complete.clicked.connect(self.complete_requested)
        buttons_layout.addWidget(complete)
        card.add(buttons)

    def _build_row(self, item: dict[str, str]) -> QWidget:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(8)
        head_layout.addWidget(
            Chip(_CATEGORY_LABELS.get(item.get("category", ""), "Digər"), "neutral")
        )
        head_layout.addWidget(muted_label(item.get("item_text", ""), size=13), 1)
        if item.get("is_blocking") == "1":
            head_layout.addWidget(Chip("Bağlayıcı", "warning"))
        row_layout.addWidget(head)

        answer = QWidget()
        answer_layout = QHBoxLayout(answer)
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setSpacing(16)

        item_id = item.get("id", "")
        passed_btn = QRadioButton("Keçdi")
        failed_btn = QRadioButton("Uğursuz")
        group = QButtonGroup(answer)
        for button in (passed_btn, failed_btn):
            group.addButton(button)
            answer_layout.addWidget(button)

        notes = QLineEdit()
        notes.setProperty("variant", "form")
        notes.setPlaceholderText("Qeyd (istəyə bağlı)")
        notes.setText(item.get("notes", ""))
        answer_layout.addWidget(notes, 1)

        if item.get("passed") == "1":
            passed_btn.setChecked(True)
        elif item.get("passed") == "0":
            failed_btn.setChecked(True)

        passed_btn.toggled.connect(
            lambda checked, i=item_id, n=notes: self._emit_if_checked(i, True, n, checked=checked)
        )
        failed_btn.toggled.connect(
            lambda checked, i=item_id, n=notes: self._emit_if_checked(i, False, n, checked=checked)
        )
        # Qeyd sahəsi CAVABSIZ bənddə YAZILA BİLƏR (`answer_item` `passed`-i
        # MƏCBURİ tələb edir — bax use case imzası), ona görə burada YALNIZ
        # ARTIQ cavablanmış sətirdə redaktə yenidən yazır, cavabsız sətirdə
        # `returnPressed` heç nə göndərmir (boş `passed` yazıla bilməz).
        notes.editingFinished.connect(
            lambda i=item_id, g=group, n=notes: self._resubmit_if_answered(i, g, n)
        )

        row_layout.addWidget(answer)
        return row

    def _emit_if_checked(
        self, item_id: str, passed: bool, notes: QLineEdit, *, checked: bool
    ) -> None:
        """`toggled` HƏM seçiləndə, HƏM seçim itəndə gəlir — yalnız birincisi
        (`field_reports.py::_on_answer_toggled` ilə eyni qoruma)."""
        if checked:
            self.item_answered.emit(item_id, passed, notes.text().strip())

    def _resubmit_if_answered(self, item_id: str, group: QButtonGroup, notes: QLineEdit) -> None:
        checked = group.checkedButton()
        if checked is None:
            return
        passed = checked.text() == "Keçdi"
        self.item_answered.emit(item_id, passed, notes.text().strip())

    def set_message(self, message: str) -> None:
        """`ChecklistNotCompletableError`-un aydın mesajı (görmək = səlahiyyət DEYİL,
        domen vəziyyəti — bax modul başlığı)."""
        self._message.setText(message)


__all__ = ["OffboardingChecklistDialog"]
