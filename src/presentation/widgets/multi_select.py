"""Çox-seçimli açılan siyahı — `QComboBox` üzərində işarə qutuları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `QComboBox`, `QListWidget` DEYİL
──────────────────────────────────────────────────────────────────────────────
Süzgəc zolağında beş element yan-yana durur (status, filial, vəzifə, tarix,
axtarış). `QListWidget` şaquli yer tutur və beş filialı olan kirayəçidə də,
iyirmi filialı olanda da eyni hündürlüyü saxlaya bilmir — panel ya boş
yerlə, ya da sürüşdürücü ilə dolur. Açılan siyahı isə YIĞILMIŞ vəziyyətdə
bir sətirdir və seçimin XÜLASƏSİNİ göstərir.

──────────────────────────────────────────────────────────────────────────────
SEÇİM AÇILAN SİYAHI BAĞLANANDA DEYİL, DƏRHAL YAYILIR
──────────────────────────────────────────────────────────────────────────────
`selection_changed` hər işarə qutusunda yayılır. Bağlanma anını gözləsəydik,
istifadəçi iki filial seçib siyahını açıq saxlayanda nəticə hələ köhnə
qalardı və o, süzgəcin işləmədiyini düşünərdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QWidget

if TYPE_CHECKING:
    from collections.abc import Iterable


class MultiSelectCombo(QComboBox):
    """İşarə qutulu açılan siyahı.

    Signals:
        selection_changed: Seçilmiş dəyərlərin siyahısı (`list[str]`).
    """

    selection_changed = Signal(list)

    def __init__(self, placeholder: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        # `setEditable(True)` + `readOnly` — YIĞILMIŞ sətirdə xülasə mətnini
        # göstərməyin YEGANƏ yolu budur: adi `QComboBox` yalnız seçilmiş
        # BƏNDİN adını göstərir, çox-seçimdə isə belə bir bənd yoxdur.
        self.setEditable(True)
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setReadOnly(True)
            # Fokus alsaydı, klaviatura ilə gəzən istifadəçi mətn yazmağa
            # çalışar və heç nə baş verməzdi.
            line_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self._model.itemChanged.connect(self._on_item_changed)
        self._refresh_text()

    # ------------------------------- məzmun ---------------------------------- #

    def set_options(self, options: Iterable[tuple[str, str]]) -> None:
        """`(dəyər, ad)` cütləri. Mövcud seçim MÜMKÜN QƏDƏR saxlanılır.

        Seçimi tam sıfırlasaydıq, siyahının hər yenilənməsi (məs. yeni filial
        əlavə olundu) istifadəçinin qurduğu kəsimi silərdi.
        """
        previous = set(self.selected_values())
        self._model.blockSignals(True)
        self._model.clear()
        for value, label in options:
            item = QStandardItem(label)
            item.setData(value, Qt.ItemDataRole.UserRole)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if value in previous else Qt.CheckState.Unchecked
            )
            self._model.appendRow(item)
        self._model.blockSignals(False)
        self._refresh_text()

    def selected_values(self) -> list[str]:
        values: list[str] = []
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                values.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return values

    def clear_selection(self) -> None:
        """Hamısını söndürür — TƏK siqnal yayır.

        Hər bənd üçün ayrıca siqnal yaysaydıq, «Filtrləri Təmizlə» düyməsi
        siyahının uzunluğu qədər sorğu göndərərdi.
        """
        self._model.blockSignals(True)
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._model.blockSignals(False)
        self._refresh_text()
        self.selection_changed.emit([])

    # ------------------------------- daxili ---------------------------------- #

    def _on_item_changed(self, _item: QStandardItem) -> None:
        self._refresh_text()
        self.selection_changed.emit(self.selected_values())

    def _refresh_text(self) -> None:
        """Yığılmış sətir: «Bütün filiallar» / «Yataş Babək» / «2 filial».

        Üç ADdan çoxunu sadalamaq sətri kəsərdi; say isə həmişə sığır və
        «neçəsini seçmişəm?» sualına dəqiq cavab verir.
        """
        labels = [
            str(self._model.item(row).text())
            for row in range(self._model.rowCount())
            if self._model.item(row) is not None
            and self._model.item(row).checkState() == Qt.CheckState.Checked
        ]
        line_edit = self.lineEdit()
        if line_edit is None:  # pragma: no cover - `setEditable(True)` qoruyur
            return
        if not labels:
            line_edit.setText(self._placeholder)
        elif len(labels) == 1:
            line_edit.setText(labels[0])
        else:
            line_edit.setText(f"{len(labels)} seçim")


__all__ = ["MultiSelectCombo"]
