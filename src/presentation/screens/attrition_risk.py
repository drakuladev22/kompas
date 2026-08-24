"""İşdən Çıxma Riski ekranı — #21, kompasos11.md Faza 9.

Maketdə AYRICA fayl kimi verilməyib (Qrup A–I-də yoxdur) — `announcements.py`/
`performance_review.py` ilə eyni vəziyyət (Faza 9-un YENİ funksiyası). Mövcud
dizayn dilini (`Card`, `DataTable`, `Chip`) TƏKRAR İSTİFADƏ edir.

──────────────────────────────────────────────────────────────────────────────
YAZI YOLU YOXDUR — TAMAMİLƏ OXU EKRANIDIR
──────────────────────────────────────────────────────────────────────────────
Bal gecəlik planlaşdırılmış işlə hesablanır (`AttritionRiskUseCase.
recalculate_all`); ekranda heç bir forma/dialoq YOXDUR — yalnız "Yenilə"
düyməsi mövcud siyahını təzədən oxuyur. Bu, `announcements.py`/`performance_
review.py`-dən FƏRQLİDİR (onlar HƏM yazır) və `group_i.ExceptionsScreen`-in
"baxış+qərar" formasından da FƏRQLİDİR (bu ekranda qərar əməliyyatı yoxdur —
bal MƏSLƏHƏTDİR, bax `domain.attrition_rules` başlığı).

──────────────────────────────────────────────────────────────────────────────
"ƏSAS AMİL" SÜTUNU — NİYƏ TƏK CÜMLƏ, TAM `factors_json` YOX
──────────────────────────────────────────────────────────────────────────────
Cədvəl sətri ən böyük payı olan TƏK amili göstərir (oxunaqlılıq) — tam
parçalanma (`factors_json`-un dörd sətri) `set_scores`-a ötürülən `factors_text`
sahəsində, sətrin özündə çoxsətirli mətn kimi verilir. Ayrı dialoqa YOXLANMIR:
HR-ın bir baxışda "niyə" sualının cavabını görməsi vacibdir, əlavə klik tələb
etmək bu prinsipi (bölmə 3, "izah edilə bilən bal") zəiflədərdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import Chip, muted_label, stretch

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class AttritionRiskScreen(Screen):
    """İşdən çıxma riski siyahısı — `can_view_attrition_risk`.

    Signals:
        refresh_requested: "Yenilə" düyməsi — kontroller siyahını yenidən oxuyur.
    """

    refresh_requested = Signal()

    _COLUMNS: ClassVar[list[Column]] = [
        Column("İşçi"),
        Column("Mağaza", 160),
        Column("Bal", 90, mono=True),
        Column("Səviyyə", 110),
        Column("Əsas Amillər", 320),
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

    def set_scores(self, rows: list[dict[str, str]]) -> None:
        """Siyahını yenidən çəkir.

        Args:
            rows: `employee`, `store`, `score`, `band_text`, `is_high_risk`
                (`"1"`/`"0"`), `factors_text` açarları — açarlar
                `controllers/attrition_risk.py::_to_row` ilə EYNİDİR
                (CLAUDE.md §6).
        """
        clear_layout(self._table_layout)

        if not rows:
            self.show_empty(
                icon_name="activity",
                title="Hələ bal hesablanmayıb",
                message="Gecəlik hesablama işlədikdən sonra işçilərin risk balı burada görünəcək.",
            )
            return

        high_risk_count = sum(1 for row in rows if row.get("is_high_risk") == "1")
        self._summary.setText(f"{len(rows)} işçi — {high_risk_count} yüksək riskdə")

        table = DataTable(self._COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)
        self.show_content()

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        is_high_risk = row.get("is_high_risk") == "1"
        band = Chip(row.get("band_text", ""), "danger" if is_high_risk else "neutral")
        return [
            row.get("employee", ""),
            row.get("store", "—"),
            row.get("score", ""),
            band,
            row.get("factors_text", ""),
        ]


__all__ = ["AttritionRiskScreen"]
