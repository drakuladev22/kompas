"""İşdən Çıxma Riski ekranı — #21, kompasos11.md Faza 9.

Maketdə AYRICA fayl kimi verilməyib (Qrup A–I-də yoxdur) — `announcements.py`/
`performance_review.py` ilə eyni vəziyyət (Faza 9-un YENİ funksiyası). Mövcud
dizayn dilini (`Card`, `DataTable`, `Chip`) TƏKRAR İSTİFADƏ edir.

──────────────────────────────────────────────────────────────────────────────
YAZI YOLU — İNDİ İKİSİ VAR (v2backlog.md Faza 6.4)
──────────────────────────────────────────────────────────────────────────────
Risk balları YALNIZ OXUNUR (aşağıdakı qayda qalır). LAKİN kampaniya dövrləri
bölməsi YAZI yoludur: Root/CEO promosyon aralıqlarını burada daxil edir, çünki
onların TƏK istehlakçısı məhz bu ekranın kontekstidir (heyət fərqindəliyi
analitikası) və ayrıca «kampaniyalar» ekranı açmaq naviqasiya tullantısı
olardı. Bölmə flag-qapılıdır (`can_manage_campaign_periods`, migrations/102):
flag-siz istifadəçi üçün HEÇ RENDER OLUNMUR («görmək = səlahiyyət», kompasos-ui
bənd 3).

Bal gecəlik planlaşdırılmış işlə hesablanır (`AttritionRiskUseCase.
recalculate_all`); risk siyahısında forma/dialoq YOXDUR — yalnız «Yenilə»
düyməsi var. Bu, `group_i.ExceptionsScreen`-in «baxış+qərar» formasından
fərqlidir: bal MƏSLƏHƏTDİR, kampaniya tarixi isə GİRİŞ datasıdır.

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
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen, section_header
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import Card, Chip, muted_label, stretch

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class AttritionRiskScreen(Screen):
    """İşdən çıxma riski siyahısı + kampaniya dövrləri (`can_view_attrition_risk`).

    Signals:
        refresh_requested: «Yenilə» düyməsi — kontroller siyahını yenidən oxuyur.
        campaign_add_requested: `(ad, başlanğıc ISO, bitmə ISO)` — Root/CEO yazısı.
        campaign_deactivate_requested: sətrin `[Ləğv et]` düyməsi (dövr id).
    """

    refresh_requested = Signal()
    campaign_add_requested = Signal(str, str, str)
    campaign_deactivate_requested = Signal(str)

    _COLUMNS: ClassVar[list[Column]] = [
        Column("İşçi"),
        Column("Mağaza", 160),
        Column("Bal", 90, mono=True),
        Column("Səviyyə", 110),
        Column("Əsas Amillər", 320),
    ]

    _CAMPAIGN_COLUMNS: ClassVar[list[Column]] = [
        Column("Ad"),
        Column("Başlanğıc", 120, mono=True),
        Column("Bitmə", 120, mono=True),
        Column("Vəziyyət", 100),
        Column("Əməliyyat", 120),
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

        # ---------------- Kampaniya Dövrləri (Faza 6.4, Root/CEO) ------------ #
        # Flag-siz istifadəçidə bu kart ÜMUMİYYƏTLƏ qurulmur (kontroller
        # `set_campaigns_visible(False)` çağırır) — «görmək = səlahiyyət».
        self._campaign_section = QWidget()
        campaign_layout = QVBoxLayout(self._campaign_section)
        campaign_layout.setContentsMargins(0, 0, 0, 0)
        campaign_layout.setSpacing(metrics.CARD_CONTENT_SPACING)
        campaign_layout.addWidget(
            section_header(
                "Kampaniya Dövrləri",
                "Promosyon aralıqları heyət-planlama tövsiyəsinə ƏLAVƏ ÇƏKİ verir "
                "(Dashboard: «Promosyon Dövrü Heyət Fərqi»).",
            )
        )
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        form = QWidget()
        form_layout = QHBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(metrics.SPACE_MS)

        name_box = QWidget()
        name_layout = QVBoxLayout(name_box)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(4)
        name_layout.addWidget(field_label("Ad"))
        self._campaign_name = QLineEdit()
        self._campaign_name.setProperty("variant", "form")
        self._campaign_name.setPlaceholderText("Məs.: Novruz kampaniyası")
        name_layout.addWidget(self._campaign_name)
        form_layout.addWidget(name_box, 2)

        self._start_edit = QDateEdit()
        self._start_edit.setProperty("variant", "form")
        self._start_edit.setCalendarPopup(True)
        self._start_edit.setDisplayFormat("dd.MM.yyyy")
        start_box = QWidget()
        start_layout = QVBoxLayout(start_box)
        start_layout.setContentsMargins(0, 0, 0, 0)
        start_layout.setSpacing(4)
        start_label = QLabel("Başlanğıc")
        start_label.setObjectName("FieldLabel")
        start_layout.addWidget(start_label)
        start_layout.addWidget(self._start_edit)
        form_layout.addWidget(start_box, 1)

        self._end_edit = QDateEdit()
        self._end_edit.setProperty("variant", "form")
        self._end_edit.setCalendarPopup(True)
        self._end_edit.setDisplayFormat("dd.MM.yyyy")
        end_box = QWidget()
        end_layout = QVBoxLayout(end_box)
        end_layout.setContentsMargins(0, 0, 0, 0)
        end_layout.setSpacing(4)
        end_label = QLabel("Bitmə")
        end_label.setObjectName("FieldLabel")
        end_layout.addWidget(end_label)
        end_layout.addWidget(self._end_edit)
        form_layout.addWidget(end_box, 1)

        add = action_button("Əlavə Et")
        add.clicked.connect(self._on_add)
        form_layout.addWidget(add, 0)
        card.add(form)

        self._campaign_table_host = QWidget()
        self._campaign_table_layout = QVBoxLayout(self._campaign_table_host)
        self._campaign_table_layout.setContentsMargins(0, 0, 0, 0)
        self._campaign_table_layout.setSpacing(0)
        card.add(self._campaign_table_host)
        campaign_layout.addWidget(card)
        self.add(self._campaign_section)
        self._campaign_hint = muted_label("")
        self.add(self._campaign_hint)
        self._campaign_section.setVisible(False)

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

    # ------------------------- kampaniya dövrləri ---------------------------- #

    def set_campaigns_visible(self, visible: bool) -> None:
        """Flag yoxdursa bölmə HEÇ render olunmur (boz kart deyil)."""
        self._campaign_section.setVisible(visible)
        self._campaign_hint.setVisible(visible)

    def set_campaign_message(self, text: str) -> None:
        self._campaign_hint.setText(text)

    def set_campaigns(self, rows: list[dict[str, str]]) -> None:
        """Kampaniya siyahısı — açarlar `controllers/attrition_risk.py::
        _to_campaign_row` ilə EYNİDİR (CLAUDE.md §6)."""
        clear_layout(self._campaign_table_layout)
        table = DataTable(self._CAMPAIGN_COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._campaign_cells(row))
        self._campaign_table_layout.addWidget(table)

    def _campaign_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        cells: list[QWidget | str] = [
            row.get("name", ""),
            row.get("start", ""),
            row.get("end", ""),
            Chip(
                "Aktiv" if row.get("is_active") == "1" else "Söndürülüb",
                "success" if row.get("is_active") == "1" else "neutral",
            ),
        ]
        if row.get("is_active") == "1":
            deactivate = secondary_button("Ləğv et")
            deactivate.setProperty("variant", "danger")
            key = row.get("period_id", "")
            deactivate.clicked.connect(lambda *_, k=key: self.campaign_deactivate_requested.emit(k))
            cells.append(deactivate)
        else:
            cells.append("")
        return cells

    def _on_add(self) -> None:
        name = self._campaign_name.text().strip()
        start = self._start_edit.date()
        end = self._end_edit.date()
        if not name or not start.isValid() or not end.isValid():
            self.set_campaign_message("Ad və tarixlər dolu olmalıdır.")
            return
        if end < start:
            self.set_campaign_message("Bitmə tarixi başlanğıcdan əvvəl ola bilməz.")
            return
        self.campaign_add_requested.emit(
            name, start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")
        )
        self._campaign_name.clear()


__all__ = ["AttritionRiskScreen"]
