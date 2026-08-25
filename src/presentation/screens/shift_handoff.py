"""Növbə təhvili qeydi dialoqu — `v2backlog.md` Faza 5.3.

`TransferRequestDialog` İLƏ EYNİ FORMA (kart + sahə + iki düymə), İKİ FƏRQLƏ:

  * mətn sahəsi `QLineEdit` DEYİL, `QPlainTextEdit`-dir: təhvil qeydi bir
    cümlə deyil, siyahıdır («kassada 120 AZN qaldı; soyuducu təmirdədir;
    səhər gələn yükü qəbul etmək lazımdır») və tək sətirli sahə işçini
    hamısını bir sətrə sıxmağa məcbur edərdi;
  * UZUNLUQ HƏDDİ BURADA YOXDUR — o, Root parametridir
    (`SHIFT_HANDOFF_NOTE_MAX_CHARS`) və domendə yoxlanılır
    (`ShiftHandoffNote.__init__`). Dialoqda sabit `setMaxLength` qoyulsaydı,
    Root həddi böyüdəndə ekran onu GÖRMƏZDİ və istifadəçi səbəbini
    anlamadan kəsilmiş mətn göndərərdi.

Dialoq YALNIZ BOŞ mətni bloklayır — `TransferRequestDialog._on_submit` ilə
eyni sərhəd: forma qaydası ekranda, biznes qaydası domendə.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.presentation.i18n import tr
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.primitives import Card, Divider, muted_label, stretch, title_label

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class ShiftHandoffNoteDialog(QDialog):
    """İşçinin `[Təhvil Qeydi Yaz]` forması.

    Signals:
        submitted: `(note,)` — qeydin mətni.
    """

    submitted = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Növbə Təhvili")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label("Növbəni Təhvil Ver", size=19))
        card.add(
            muted_label(
                "Qeyd növbəti işçiyə göstəriləcək — açıq tapşırıqlar, "
                "kassa vəziyyəti və diqqət tələb edən nə varsa yazın.",
                size=12,
            )
        )
        card.add(Divider())

        note_box = QWidget()
        note_layout = QVBoxLayout(note_box)
        note_layout.setContentsMargins(0, 0, 0, 0)
        note_layout.setSpacing(8)
        note_layout.addWidget(field_label("Təhvil qeydi"))
        self._note = QPlainTextEdit()
        self._note.setProperty("variant", "form")
        # Placeholder NÜMUNƏ DEYİL, TƏLİMATDIR («Məsələn: …» qadağası —
        # `test_setup_wizard_state.py::_EXAMPLE_PATTERNS`): sahəni nənin
        # gözlədiyini deyir, dəyər YAZMIR.
        self._note.setPlaceholderText(
            "Kassa, açıq tapşırıqlar və diqqət tələb edən məqamları yazın…"
        )
        # ÇOXSƏTİRLİ FORM SAHƏSİ HÜNDÜRLÜYÜ = 112: `announcements.py`/`
        # field_reports.py`-dakı eyni tipli `QPlainTextEdit` sahələri ilə EYNİ
        # dəyər — yeni ad-hoc ölçü səpələnmə tavanını keçirdi
        # (`test_design_symmetry.py::test_design_scatter_does_not_grow`).
        self._note.setMinimumHeight(112)
        note_layout.addWidget(self._note)
        card.add(note_box)

        self._hint = muted_label("")
        card.add(self._hint)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button(tr("common.decline"))
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        submit = action_button("Qeydi Saxla")
        submit.clicked.connect(self._on_submit)
        buttons_layout.addWidget(submit)
        card.add(buttons)

        # `setDefault(True)` MƏTN SAHƏSİ İLƏ BİRLİKDƏ TƏHLÜKƏSİZDİR:
        # `QPlainTextEdit` Enter-i ÖZÜ udur (yeni sətir), yəni yazı zamanı
        # təsadüfi göndərmə baş vermir — `QLineEdit`-li dialoqlardan fərqli
        # olaraq burada bu, qəsdli bir seçimdir.
        submit.setDefault(True)
        submit.setAutoDefault(True)
        cancel.setAutoDefault(False)

        QWidget.setTabOrder(self._note, cancel)
        QWidget.setTabOrder(cancel, submit)

    def _on_submit(self) -> None:
        note = self._note.toPlainText().strip()
        if not note:
            self._hint.setText("Qeyd boş buraxıla bilməz.")
            return
        self.submitted.emit(note)
        self.accept()


__all__ = ["ShiftHandoffNoteDialog"]
