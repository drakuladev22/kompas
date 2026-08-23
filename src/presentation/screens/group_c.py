"""Qrup C — admin nüvəsi — Faza 4.2.

Maket: "KompasOS - Qrup C.dc.html", ekranlar 09–14.

    09  Admin / CEO İdarə Paneli
    10  İcazə Matrisi (Discord-tərzi)
    11  İstifadəçi və Rol İdarəetməsi
    12  Növbə Planlama (aylıq matris)
    13  Gündəlik Mağaza Tabeli
    14  Növbə Dəyişmə Sorğuları
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.document_rules import (
    ATTENTION_FLAG_LABEL_AZ,
    ATTENTION_FLAG_LABEL_INLINE_AZ,
)
from src.presentation.screens.base import Screen
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.charts import (
    BarChart,
    BarDatum,
    MeterCard,
    RankList,
    StatTile,
)
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.help_hint import HelpButton
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.multi_select import MultiSelectCombo
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ChipTone,
    ClickableCard,
    Divider,
    StatusDot,
    body_label,
    mono_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)
from src.presentation.widgets.responsive import LayoutMode

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from src.presentation.theme.manager import ThemeManager


#: İdarə Panelindəki bölmələrin ŞƏBƏKƏ AÇARLARI (audit G-5).
#:
#: ──────────────────────────────────────────────────────────────────────────
#: NİYƏ BURADA SİYAHI VAR VƏ NİYƏ ADLAR SEÇİLMİR
#: ──────────────────────────────────────────────────────────────────────────
#: Açarlar `application.use_cases.dashboard_layout.WIDGET_CATALOG`-un
#: açarlarıdır — Panel Qurucusu məhz onları saxlayır. Ekran tətbiq qatını
#: İDXAL ETMİR (qat sərhədi, bax `screens/group_i.py: PLACEMENT_SEPARATOR`
#: şərhi), ona görə siyahı burada TƏKRARLANIR; sükutla ayrılmasın deyə
#: `tests/unit/test_dashboard_grid.py` iki mənbənin uyğunluğunu QAPI
#: kimi yoxlayır.
#:
#: `open_tasks` BURADA YOXDUR və bu, qəsdəndir: onun öz kartı yoxdur — açıq
#: tapşırıq sayı rəqəm kartlarının (`stat_tiles`) içindədir. Yerləşdirməsi
#: olan, lakin bölməsi olmayan açar sükutla BURAXILIR (fail-soft).
DASHBOARD_SECTION_KEYS: Final[tuple[str, ...]] = (
    "stat_tiles",
    "fines_chart",
    "leave_gauge",
    "points_leaderboard",
    "server_health",
    "ranking_table",
    "store_vs_network",
    "metric_trend",
    "benchmark_outliers",
)


def _is_placement(value: object) -> bool:
    """Yerləşdirmənin FORMASINI yoxlayır — yararsızı sükutla buraxmaq üçün.

    Dəyər maket yolundan, kontrollerdən və ya gələcək bir skriptdən gələ
    bilər; üç tam ədəddən ibarət olmayan element düzülüşü SINDIRMAMALIDIR
    (ekran çökməkdənsə həmin bölməni öz yerində saxlayır). `bool` QƏSDƏN
    rədd edilir: Python-da `True` bir `int`-dir və `(True, 0, 1)` sətri
    `1`-ə çevirərək izahsız sürüşmə yaradardı.
    """
    return (
        isinstance(value, tuple)
        and len(value) == 3  # noqa: PLR2004 — üçlük formanın ÖZÜDÜR (sətir, sütun, en)
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    )


# --------------------------------------------------------------------------- #
# 09 — Admin / CEO İdarə Paneli
# --------------------------------------------------------------------------- #


class RankingEntry(NamedTuple):
    """Çox-Mağaza Reytinq Cədvəlinin bir sətri (#24, kompasos11.md Faza 9A).

    Sıra nömrəsi BURADA YOXDUR — siyahının ÖZÜ artıq sıralanmış gəlir (bax
    `MultiStoreBenchmarkUseCase.ranking`), ekran yalnız mövqeyə görə 1-dən
    nömrələyir. Trend OXU mətnlə birgə gəlir — kompasos11.md #24: "yalnız
    rənglə fərqlənməsin, işarə/mətn də daşısın".
    """

    store_id: str
    store_name: str
    value_display: str
    trend_arrow: str
    trend_label: str


class DashboardScreen(Screen):
    """Konfiqurasiya edilə bilən widget şəbəkəsi.

    Maketdəki düzülüş: üstdə dörd rəqəm kartı, altda qrafik + limit ölçəni,
    sonra liderlik lövhəsi + server sağlamlığı.

    ──────────────────────────────────────────────────────────────────────
    #24 ÇOX-MAĞAZA BENCHMARK BÖLMƏSİ NİYƏ DEFOLT GİZLİDİR
    ──────────────────────────────────────────────────────────────────────
    Dörd yeni bölmə (`set_ranking_table`/`set_store_vs_network`/
    `set_metric_trend`/`set_outliers`) `Card.setVisible(False)` ilə BAŞLAYIR
    və yalnız müvafiq `set_*` çağırılanda görünür. Kontroller
    (`screen_data.py::_dashboard`) bu çağırışı YALNIZ `can_export_reports`
    sahibi üçün edir — Mağaza_Meneceri üçün bölmələr sadəcə HEÇ VAXT
    doldurulmur, ekranın özü "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipini bu
    yolla qoruyur (bölmə 3).

    Signals:
        ranking_metric_changed: Reytinq cədvəlinin dropdown-u dəyişdi (metrik açarı).
        ranking_row_selected: Reytinq sətrinə klik (mağaza ID) — DRILL-DOWN.
    """

    ranking_metric_changed = Signal(str)
    ranking_row_selected = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        # ------------------------------ rəqəmlər ---------------------------- #
        tiles = QWidget()
        tiles_layout = QHBoxLayout(tiles)
        tiles_layout.setContentsMargins(0, 0, 0, 0)
        tiles_layout.setSpacing(metrics.CARD_SPACING)
        # Dar pəncərədə (700–1280px, yarım-ekran snap) dörd rəqəm kartı
        # yan-yana 150px-ə düşür və başlıqları kəsilir — o həddən sonra
        # bir sütuna yığılır (bax `screens/base.py::responsive_row`).
        self.responsive_row(tiles_layout)

        self._in_store = StatTile("Hazırda mağazada")
        self._pending = StatTile("Təsdiq gözləyir")
        self._fines = StatTile("Bu ayın cərimələri")
        self._tasks = StatTile("Açıq tapşırıqlar")
        # ŞƏBƏKƏNİN ÖLÇÜSÜ — «neçə işçi, neçə filial».
        #
        # Dörd kart ƏMƏLİYYAT rəqəmləridir (bu gün, bu ay); bu ikisi isə
        # şirkətin ÖZ ölçüsüdür və CEO panelində ilk soruşulan sualdır.
        # Say bazadan gəlir, ona görə mağaza/işçi əlavə edildikdə ekran
        # növbəti açılışda ARTIR — heç bir yerdə əl ilə yazılmır.
        self._employees = StatTile("İşçilər")
        self._stores = StatTile("Filiallar")
        for tile in (
            self._in_store,
            self._pending,
            self._fines,
            self._tasks,
            self._employees,
            self._stores,
        ):
            tile.setFixedHeight(metrics.DASHBOARD_ROW_HEIGHT)
            tiles_layout.addWidget(tile, 1)
        self.add(tiles)
        self._tiles_row = tiles

        # --------------------------- qrafik + limit ------------------------- #
        middle = QWidget()
        middle_layout = QHBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(metrics.CARD_SPACING)
        self.responsive_row(middle_layout)

        chart_card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        chart_head = QWidget()
        chart_head_layout = QHBoxLayout(chart_head)
        chart_head_layout.setContentsMargins(0, 0, 0, 0)
        chart_head_layout.setSpacing(12)
        chart_head_layout.addWidget(title_label("Cərimələr — filial üzrə", size=15))
        self._chart_period = muted_label("")
        chart_head_layout.addWidget(self._chart_period)
        chart_head_layout.addWidget(stretch())
        chart_card.add(chart_head)

        self._chart = BarChart(theme)
        chart_card.add(self._chart)
        middle_layout.addWidget(chart_card, 2)

        self._leave_meter = MeterCard(
            theme,
            title="İcazə istifadəsi",
            subtitle="Bu ay verilən icazələrin limitə nisbəti",
        )
        middle_layout.addWidget(self._leave_meter, 1)
        self.add(middle)
        self._middle_row = middle
        self._chart_card = chart_card

        # ------------------------ liderlər + serverlər ---------------------- #
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(metrics.CARD_SPACING)
        self.responsive_row(bottom_layout)

        self._leaders = RankList("Xal liderləri")
        bottom_layout.addWidget(self._leaders, 1)

        self._health = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        self._health.add(title_label("Server sağlamlığı", size=15))
        self._health_rows = QVBoxLayout()
        self._health_rows.setSpacing(12)
        health_holder = QWidget()
        health_holder.setLayout(self._health_rows)
        self._health.add(health_holder)
        self._health.body().addStretch(1)
        bottom_layout.addWidget(self._health, 1)
        self.add(bottom)
        self._bottom_row = bottom

        # ------------------ #24 Çox-Mağaza Benchmark (Faza 9A) --------------- #
        # Dördü də defolt GİZLİDİR (bax sinif başlığı) — yalnız müvafiq
        # `set_*` çağırılanda görünür.
        self._ranking_store_ids: list[str] = []
        self._ranking_card = self._build_ranking_card()
        self.add(self._ranking_card)

        store_vs_network = self._build_store_vs_network_card(theme)
        self._store_vs_network_card = store_vs_network[0]
        self._store_vs_network_subtitle = store_vs_network[1]
        self._store_vs_network_chart = store_vs_network[2]
        self.add(self._store_vs_network_card)

        self._trend_card, self._trend_title, self._trend_chart = self._build_trend_card(theme)
        self.add(self._trend_card)

        self._outlier_card, self._outlier_summary, self._outlier_rows = self._build_outlier_card()
        self.add(self._outlier_card)

        # ------------ Nahar/Çay gündəlik həddi (nahar.md GUI, bənd 2) --------- #
        # Benchmark kartları ilə EYNİ naxış: defolt gizli, yalnız doldurulanda
        # görünür. FƏRQ bir addım irəlidədir — bu kart BOŞ SİYAHIDA da gizli
        # qalır, çünki "bu gün heç kim həddi aşmayıb" xəbər deyil. Həmişə
        # görünən boş kart HR-ı ona baxmamağa öyrədərdi.
        self._break_card, self._break_rows = self._build_break_overuse_card()
        self.add(self._break_card)

        # ---------------- şəbəkə yerləşdirməsi (audit G-5) ------------------ #
        # BURADA HEÇ NƏ DƏYİŞMİR: aşağıdakılar yalnız QEYDİYYATDIR. Şəbəkə
        # `set_layout()` çağırılana qədər TƏTBİQ OLUNMUR, yəni yerləşdirməsi
        # olmayan istifadəçidə ekran hərfən əvvəlki kimi qalır (tam-enli
        # şaquli yığın) — geriyə uyğunluq qapısı budur.
        self._sections: dict[str, QWidget] = {
            "stat_tiles": self._tiles_row,
            "fines_chart": self._chart_card,
            "leave_gauge": self._leave_meter,
            "points_leaderboard": self._leaders,
            "server_health": self._health,
            "ranking_table": self._ranking_card,
            "store_vs_network": self._store_vs_network_card,
            "metric_trend": self._trend_card,
            "benchmark_outliers": self._outlier_card,
        }
        #: `açar → (sətir, sütun, en)`. Boş = şəbəkə yoxdur.
        self._placements: dict[str, tuple[int, int, int]] = {}
        self._grid_columns = 1
        #: Şəbəkə qabı LAZIM OLANA QƏDƏR QURULMUR (eyni naxış: `Screen.
        #: _section_error_banner`) — şəbəkəsiz ekranda bir dənə də artıq
        #: widget yaranmır.
        self._grid_host: QWidget | None = None
        self._grid: QGridLayout | None = None

    # ------------------------ şəbəkə yerləşdirməsi --------------------------- #

    def set_layout(
        self,
        placements: dict[str, tuple[int, int, int]] | None = None,
        *,
        columns: int = 1,
    ) -> None:
        """Panel Qurucusunda seçilmiş şəbəkəni TƏTBİQ edir (audit G-5).

        Args:
            placements: `açar → (sətir, sütun, en)` — `DashboardView.
                placement_map()`-ın çıxışı. `None`/boş → ŞƏBƏKƏ YOXDUR.
            columns: Şəbəkənin sütun sayı (ROOT: `DASHBOARD_GRID_COLUMNS`).

        ──────────────────────────────────────────────────────────────────────
        BOŞ YERLƏŞDİRMƏ HEÇ NƏYƏ TOXUNMUR
        ──────────────────────────────────────────────────────────────────────
        Qurucuda şəbəkə qurmamış istifadəçi (və köhnə xətti konfiqurasiya)
        EYNİ görünüşü görməlidir. Ona görə burada "tək sütunlu şəbəkə qur"
        yolu SEÇİLMƏDİ: nəticə vizual olaraq eyni olsa da, widget-lər yeni
        qaba köçürülərdi və hər hansı fərq (kart aralığı, uzanma əmsalı)
        səbəbsiz reqressiya olardı. Heç nə etməmək — sübutu ən asan olan
        davranışdır.

        İMZA OPSİONALDIR: mövcud `set_*` çağırışlarının heç biri dəyişmir və
        bu metodu çağırmayan yol (maket və ya köhnə kontroller) sınmır.
        """
        known = {
            key: value
            for key, value in (placements or {}).items()
            if key in self._sections and _is_placement(value)
        }
        if not known:
            return
        self._placements = known
        self._grid_columns = max(1, columns)
        self._apply_grid()

    def apply_layout_mode(self, mode: LayoutMode) -> None:
        """Pəncərə rejimi dəyişdi — şəbəkə yenidən yerləşdirilir.

        SAXLANMIŞ ŞƏBƏKƏ TOXUNULMUR: dar pəncərə yalnız GÖSTƏRİLMƏNİ dəyişir,
        istifadəçinin seçimini silmir (eyni qərar `DashboardBuilderScreen.
        apply_layout_mode`-da verilib).
        """
        super().apply_layout_mode(mode)
        if self._grid is not None:
            self._apply_grid()

    def _apply_grid(self) -> None:
        """Bölmələri şəbəkəyə köçürür — FAIL-SOFT.

        Dar pəncərədə (`LayoutMode.COMPACT`) şəbəkə TƏK SÜTUNA yığılır və
        oxunuş sırası (sətir, sonra sütun) qorunur — `application.use_cases.
        dashboard_layout.collapse_to_single_column()` ilə EYNİ qayda. Rejimi
        burada ÖLÇMÜRÜK: qərar mərkəzi mexanizmdən gəlir (`widgets/
        responsive.py` → `Screen.apply_layout_mode`), yeni breakpoint
        yaradılmır.
        """
        grid = self._ensure_grid()
        compact = self.layout_mode is LayoutMode.COMPACT
        columns = 1 if compact else self._grid_columns

        for key, row, column, span in self._grid_slots(columns=columns):
            widget = self._sections[key]
            # GİZLİ QALAN GİZLİ QALIR: benchmark kartları doldurulana qədər
            # `setVisible(False)`-dır (bax sinif başlığı) və Qt reparent zamanı
            # görünürlüyü sıfırlayır — vəziyyət açıq şəkildə bərpa olunmasa,
            # icazəsi olmayan istifadəçi boş benchmark kartlarını GÖRƏRDİ.
            hidden = widget.isHidden()
            self._detach(widget)
            grid.addWidget(widget, row, column, 1, span)
            widget.setVisible(not hidden)

        for index in range(max(columns, self._grid_columns)):
            grid.setColumnStretch(index, 1 if index < columns else 0)

        # Boşalmış sətir qabları GİZLƏNİR: içindəki hər iki kart şəbəkəyə
        # köçübsə, qab yalnız izahsız bir boşluq qoyardı. Hansısa kart
        # köçməyibsə (məs. yerləşdirməsi çatışmır) qab GÖRÜNƏN qalır — kart
        # heç vaxt yox olmamalıdır.
        for container in (self._middle_row, self._bottom_row):
            layout = container.layout()
            container.setVisible(layout is not None and layout.count() > 0)

    def _grid_slots(self, *, columns: int) -> list[tuple[str, int, int, int]]:
        """Yerləşdirmələri ÜST-ÜSTƏ DÜŞMƏYƏN xanalara çevirir.

        Saxlanmış dəyər üç yolla "yanlış" ola bilər və heç biri istifadəçinin
        günahı deyil: Root sütun sayını azaldıb, iki kart eyni xanaya düşüb,
        format köhnədir. Hər üç halda kart YOX OLMAMALIDIR — ona görə burada
        yer TAPILIR, istisna atılmır (`dashboard_layout.normalize_placements`
        ilə eyni istiqamət; orada tətbiq qatı, burada ekranın öz müdafiəsi,
        çünki ekranı maket yolu da doldurur).
        """
        ordered = sorted(
            ((key, self._placements[key]) for key in self._placements if key in self._sections),
            key=lambda item: (item[1][0], item[1][1], item[0]),
        )
        if self.layout_mode is LayoutMode.COMPACT:
            return [(key, index, 0, 1) for index, (key, _) in enumerate(ordered)]

        occupied: set[tuple[int, int]] = set()
        slots: list[tuple[str, int, int, int]] = []
        for key, (raw_row, raw_column, raw_span) in ordered:
            column = max(0, min(columns - 1, raw_column))
            span = max(1, min(columns - column, raw_span))
            row = max(0, raw_row)
            # Dövr HƏMİŞƏ bitir: sətir sayı sərhədsizdir, yəni ən pis halda
            # kart yeni sətrə düşür.
            while any((row, column + offset) in occupied for offset in range(span)):
                row += 1
            for offset in range(span):
                occupied.add((row, column + offset))
            slots.append((key, row, column, span))
        return slots

    def _ensure_grid(self) -> QGridLayout:
        """Şəbəkə qabını BİR DƏFƏ qurur və rəqəm kartlarının yerinə qoyur.

        Yer `indexOf` ilə tapılır, sabit `0` ilə deyil: bölmə-xətası banneri
        (`Screen.set_section_error`) məzmunun ƏN ÜSTÜNƏ qoyulur və şəbəkəni
        şərtsiz 0-cı mövqeyə salsaydıq, xəbərdarlıq rəqəmlərin ALTINDA
        qalardı.
        """
        if self._grid is not None:
            return self._grid
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(metrics.CARD_SPACING)
        anchor = self.body().indexOf(self._tiles_row)
        self.body().insertWidget(anchor if anchor >= 0 else self.body().count(), host)
        self._grid_host = host
        self._grid = grid
        return grid

    @staticmethod
    def _detach(widget: QWidget) -> None:
        """Widget-i köhnə yerləşdirməsindən AÇIQ şəkildə çıxarır.

        `QGridLayout.addWidget` valideyni onsuz da dəyişir, lakin köhnə
        `QBoxLayout` elementi orada QALIR və qab "boş deyil" görünərdi —
        yəni aşağıdakı gizlətmə şərti heç vaxt işə düşməzdi.
        """
        parent = widget.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is not None:
            layout.removeWidget(widget)

    def _build_ranking_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)
        head_layout.addWidget(title_label("Çox-Mağaza Reytinq Cədvəli", size=15))
        head_layout.addWidget(stretch())
        self._ranking_metric_combo = QComboBox()
        self._ranking_metric_combo.setProperty("variant", "form")
        self._ranking_metric_combo.setFixedWidth(220)
        self._ranking_metric_combo.currentIndexChanged.connect(self._on_ranking_metric_changed)
        head_layout.addWidget(self._ranking_metric_combo)
        card.add(head)

        self._ranking_table = DataTable(
            [
                Column("Sıra", 50, mono=True),
                Column("Mağaza", 220),
                Column("Dəyər", 110, mono=True),
                Column("Trend"),
            ],
            self.theme,
            footnote="Sətrə klik — mağazanın Gündəlik Tabelinə keçir.",
        )
        self._ranking_table.row_selected.connect(self._on_ranking_row_selected)
        card.add(self._ranking_table)
        card.setVisible(False)
        return card

    def _build_store_vs_network_card(self, theme: ThemeManager) -> tuple[Card, QLabel, BarChart]:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(title_label("Mağaza — Şəbəkə Ortalaması", size=15))
        subtitle = muted_label("")
        card.add(subtitle)
        # `highlight_max=False`: iki sütun BƏRABƏR əhəmiyyətlidir (mağaza VƏ
        # şəbəkə), amber vurğusu birini digərindən "daha yaxşı" göstərərdi.
        chart = BarChart(theme, highlight_max=False)
        card.add(chart)
        card.setVisible(False)
        return card, subtitle, chart

    def _build_trend_card(self, theme: ThemeManager) -> tuple[Card, QLabel, BarChart]:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        title = title_label("Zaman-üzrə Trend", size=15)
        card.add(title)
        chart = BarChart(theme)
        card.add(chart)
        card.setVisible(False)
        return card, title, chart

    def _build_outlier_card(self) -> tuple[Card, QLabel, QVBoxLayout]:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(title_label("Kritik-Kənar (Outlier) Kartı", size=15))
        summary = body_label("", size=13)
        summary.setWordWrap(True)
        card.add(summary)
        rows_layout = QVBoxLayout()
        rows_layout.setSpacing(8)
        holder = QWidget()
        holder.setLayout(rows_layout)
        card.add(holder)
        card.setVisible(False)
        return card, summary, rows_layout

    def _build_break_overuse_card(self) -> tuple[Card, QVBoxLayout]:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(title_label("Gündəlik fasilə həddini aşanlar", size=15))
        card.add(
            muted_label(
                "Hədd ROOT parametridir və aşılma HEÇ NƏ BLOKLAMIR — bu siyahı yalnız "
                "məlumatlandırıcıdır."
            )
        )
        rows_layout = QVBoxLayout()
        rows_layout.setSpacing(8)
        holder = QWidget()
        holder.setLayout(rows_layout)
        card.add(holder)
        card.setVisible(False)
        return card, rows_layout

    # ------------------------------- doldurma -------------------------------- #

    def set_break_overuse(self, rows: list[tuple[str, str]]) -> None:
        """`rows`: (işçinin adı, xəbərdarlıq mətni) — boş siyahı kartı gizlədir.

        Xəbərdarlıq mətni EKRANDA QURULMUR: «2-ci nahar fasiləsi (limit: 1)»
        ifadəsi `BreakAllowance.warning_az()`-dan gəlir, yəni işçinin öz
        ekranındakı mətnlə HƏRFƏN eynidir. İki yerdə ayrıca qursaydıq, biri
        dəyişəndə HR ilə işçi fərqli ifadə görərdi və "hansı doğrudur?" sualı
        yaranardı.
        """
        clear_layout(self._break_rows)
        self._break_card.setVisible(bool(rows))
        if not rows:
            return

        for name, warning in rows:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(body_label(name, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(Chip(warning, "warning"))
            self._break_rows.addWidget(row)

    def set_summary(
        self,
        *,
        in_store: int,
        planned: int,
        pending: int,
        longest_wait: str,
        fines_total: str,
        fines_delta: str,
        open_tasks: int,
        overdue_tasks: int,
    ) -> None:
        self._in_store.set_value(str(in_store), caption=f"planlaşdırılan {planned}-dan")
        self._pending.set_value(str(pending), caption=f"ən uzunu {longest_wait}")
        self._fines.set_value(fines_total, caption=fines_delta)
        self._tasks.set_value(str(open_tasks), caption=f"{overdue_tasks}-u gecikib")
        self.show_content()

    def set_network_size(self, *, employees: int, stores: int) -> None:
        """«İşçilər» və «Filiallar» kartları — şəbəkənin cari ölçüsü.

        `set_summary()`-dən AYRI metoddur, çünki mənbəyi də ayrıdır: o,
        günün/ayın əməliyyat rəqəmlərini gətirir, bu isə `employees`/`stores`
        cədvəllərinin sadə sayını. Bir metoda yığsaydıq, sayları gətirə
        bilməyən yol (məs. icazəsi dar operator) bütün kartları boş qoyardı.

        `show_content()` BURADA ÇAĞIRILMIR: ekranın «məzmun var» vəziyyətini
        `set_summary()` təyin edir — iki yerdən çağırmaq vəziyyət keçidini
        sıraya bağlı edərdi.
        """
        self._employees.set_value(str(employees), caption="aktiv")
        self._stores.set_value(str(stores), caption="aktiv")

    def set_fines_by_branch(self, data: list[tuple[str, float, str]], *, period: str) -> None:
        self._chart_period.setText(period)
        self._chart.set_data([BarDatum(label, value, display) for label, value, display in data])

    def set_leave_usage(self, used: float, limit: float) -> None:
        self._leave_meter.set_usage(used, limit)

    def set_leaders(self, leaders: list[tuple[str, str]]) -> None:
        self._leaders.set_items(leaders, accent=self.theme.color("--color-brand-amber"))

    def set_server_health(self, servers: list[tuple[str, str, str]]) -> None:
        """`servers`: (ad, gecikmə mətni, ton) — ton: success/warning/danger."""
        clear_layout(self._health_rows)

        tones = {
            "success": "--color-success",
            "warning": "--color-warning",
            "danger": "--color-danger",
        }
        for name, latency, tone in servers:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(StatusDot(self.theme.color(tones.get(tone, "--color-success"))))
            layout.addWidget(body_label(name, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(mono_label(latency))
            self._health_rows.addWidget(row)

    # -------------------- #24 Çox-Mağaza Benchmark (Faza 9A) ----------------- #

    def set_ranking_table(
        self,
        entries: list[RankingEntry],
        *,
        metric_options: list[tuple[str, str]],
        selected_metric: str,
    ) -> None:
        """Reytinq cədvəlini doldurur və bölməni GÖSTƏRİR.

        Args:
            entries: ARTIQ sıralanmış (ən yaxşıdan ən pisə) siyahı.
            metric_options: dropdown-un tam siyahısı — `(metrik-açarı, ad)`.
            selected_metric: hazırda seçili metrik açarı.
        """
        self._ranking_metric_combo.blockSignals(True)
        if self._ranking_metric_combo.count() == 0:
            for key, label in metric_options:
                self._ranking_metric_combo.addItem(label, key)
        index = self._ranking_metric_combo.findData(selected_metric)
        if index >= 0:
            self._ranking_metric_combo.setCurrentIndex(index)
        self._ranking_metric_combo.blockSignals(False)

        self._ranking_table.clear()
        self._ranking_store_ids = [entry.store_id for entry in entries]
        for rank, entry in enumerate(entries, start=1):
            self._ranking_table.add_row(
                [
                    str(rank),
                    entry.store_name,
                    entry.value_display,
                    f"{entry.trend_arrow} {entry.trend_label}",
                ]
            )
        self._ranking_card.setVisible(True)
        self.show_content()

    def _on_ranking_metric_changed(self, _index: int) -> None:
        key = self._ranking_metric_combo.currentData()
        if key:
            self.ranking_metric_changed.emit(str(key))

    def _on_ranking_row_selected(self, index: int) -> None:
        """DRILL-DOWN mənbəyi — kontroller bunu `AdminShell.show_screen`-ə bağlayır."""
        if 0 <= index < len(self._ranking_store_ids):
            self.ranking_row_selected.emit(self._ranking_store_ids[index])

    def set_store_vs_network(
        self,
        *,
        metric_label: str,
        store_label: str,
        store_value: float,
        store_display: str,
        network_label: str,
        network_value: float,
        network_display: str,
    ) -> None:
        self._store_vs_network_subtitle.setText(metric_label)
        self._store_vs_network_chart.set_data(
            [
                BarDatum(store_label, store_value, store_display),
                BarDatum(network_label, network_value, network_display),
            ]
        )
        self._store_vs_network_card.setVisible(True)
        self.show_content()

    def set_metric_trend(self, *, metric_label: str, points: list[tuple[str, float, str]]) -> None:
        """`points`: (dövr etiketi, dəyər, göstəriləcək mətn) — ay-ay ardıcıllıqla."""
        self._trend_title.setText(f"Zaman-üzrə Trend — {metric_label}")
        self._trend_chart.set_data(
            [BarDatum(label, value, display) for label, value, display in points]
        )
        self._trend_card.setVisible(True)
        self.show_content()

    def set_outliers(self, *, summary_text: str, rows: list[tuple[str, str]]) -> None:
        """`rows`: (mağaza adı, "X.Xσ ortalamadan yuxarı/aşağı" mətni)."""
        self._outlier_summary.setText(summary_text)
        clear_layout(self._outlier_rows)
        for name, detail in rows:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(body_label(name, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(Chip(detail, "warning"))
            self._outlier_rows.addWidget(row)
        self._outlier_card.setVisible(True)
        self.show_content()


# --------------------------------------------------------------------------- #
# 10 — İcazə Matrisi
# --------------------------------------------------------------------------- #


#: İcazə Matrisinin kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: deaktiv xananın İKİ fərqli
#: səbəbi (hardlock ↔ Self-Escalation Guard) sinif başlığında izah olunur və
#: izahın iki nüsxəsi ayrı fayllarda saxlanılsaydı, biri düzəldiləndə digəri
#: sükutla arxada qalardı.
MATRIX_HELP_TITLE: Final = "İcazə Matrisi"

MATRIX_HELP_INTRO: Final = (
    "Bu ekranda hər vəzifənin hansı icazələrə sahib olduğu təyin edilir. "
    "Dəyişiklik bir nəfərə deyil, həmin vəzifədə işləyən HƏR KƏSƏ aiddir və "
    "yazıldığı andan qüvvəyə minir."
)

MATRIX_HELP_STEPS: Final[tuple[str, ...]] = (
    "Soldakı siyahıdan vəzifəni seçin — axtarış sahəsi uzun siyahını süzür. "
    "Sağdakı matris yalnız seçilmiş vəzifəni göstərir; başqa vəzifəyə keçmək "
    "yazılmamış işarələmələri saxlamır.",
    "Kateqoriyalar üzrə xanaları işarələyin və ya boşaldın. İşarəni götürmək "
    "həmin ekranı işçidən TAMAMİLƏ gizlədir — element boz göstərilmir, "
    "ümumiyyətlə qurulmur.",
    "Qıfıl ikonu olan xana hardlock-dur: onu heç kim buradan dəyişə bilməz, "
    "yalnız ROOT İdarə Mərkəzindən. Qıfılsız, lakin sönük xana isə həmin "
    "icazənin SİZDƏ olmadığını bildirir — özündə olmayan icazəni başqasına "
    "vermək olmaz.",
    "«Yadda Saxla» bütün işarələmələri bir anda yazır və audit jurnalına "
    "salır. «Ləğv Et» vəzifəni bazadakı halına qaytarır — o ana qədər "
    "edilmiş, lakin saxlanmamış işarələmələr bərpa olunmadan itir.",
    "«+ Yeni Vəzifə» yeni rol açır. Vəzifənin maşın kodu addan törədilir və "
    "sonradan DƏYİŞDİRİLƏ BİLMİR: adı düzəltmək olar, kodu yox.",
)


class PermissionMatrixScreen(Screen):
    """Discord-tərzi icazə matrisi: solda vəzifələr, sağda kateqoriyalı grid.

    Signals:
        role_selected: Vəzifə açarı.
        saved: (vəzifə açarı, {flag: aktiv}).
        role_create_requested: "Yeni Vəzifə".

    ──────────────────────────────────────────────────────────────────────
    QIFILLI XANALAR NİYƏ GÖRÜNÜR AMMA BASILA BİLMİR
    ──────────────────────────────────────────────────────────────────────
    Adətən bu layihədə "icazən yoxdursa, element ÜMUMİYYƏTLƏ yoxdur"
    prinsipi işləyir (bax `navigation.py`). Burada isə ƏKSİNƏ: bu ROLA
    verilə bilməyən icazələr qıfıl ikonu ilə GÖRÜNÜR.

    Səbəb fərqlidir — bu, "sənin görməyə icazən yoxdur" deyil, "bu icazə
    heç kim tərəfindən dəyişdirilə bilməz" deməkdir. Onu gizlətsək, admin
    həmin icazənin ümumiyyətlə mövcud olmadığını düşünər və nə üçün
    işlədiyini başa düşməzdi. Qıfıl İKİ fərqli qaydanın BİRLƏŞMİŞ nəticəsidir
    (`PermissionFlag.is_grantable_to()`, bax `permission_matrix.py::
    _flag_groups`): statik hardlock səviyyəsi VƏ rola-görə anti-fraud/kamera-
    tip istisnaları (SEC-001 daxil). İkisini ayrı göstərsəydik, admin eyni
    "mən niyə bunu dəyişə bilmirəm?" sualına İKİ fərqli yerdə baxmalı olardı.

    ──────────────────────────────────────────────────────────────────────
    İKİNCİ DEAKTİV NÖV: AKTORDA OLMAYAN İCAZƏ
    ──────────────────────────────────────────────────────────────────────
    Qıfıldan başqa bir səbəblə də xana basıla bilmir: Self-Escalation Guard
    aktora ÖZÜNDƏ OLMAYAN flag-i paylamağa icazə vermir. Bu, gizlətmə
    qaydasının istisnası deyil — flag mövcuddur və rolda ola bilər, sadəcə
    ONU verən konkret istifadəçi deyil. Gizlətsəydik admin matrisi natamam
    sanardı; boz xana isə səbəbi tooltip-də açıq deyir.
    """

    role_selected = Signal(str)
    saved = Signal(str, dict)
    role_create_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, padded=False, parent=parent)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._role_buttons: dict[str, QPushButton] = {}
        self._active_role: str | None = None

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_role_panel())
        layout.addWidget(self._build_matrix_panel(), 1)
        self.add(container)

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Fokus vəzifə axtarışına qoyulur — matrisin GİRİŞ nöqtəsi budur.

        Matris onlarla qutucuqdan ibarətdir və hansısa qutucuqda başlamaq
        təsadüfi olardı; axın isə həmişə eynidir — əvvəlcə vəzifə seçilir,
        sonra icazələr dəyişdirilir. Axtarış sahəsi həmin ilk addımın ən
        qısa yoludur (21 filialda vəzifə siyahısı uzundur).
        """
        super().showEvent(event)
        self._role_search.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------ sol panel -------------------------------- #

    def _build_role_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("RolePanel")
        panel.setFixedWidth(280)
        # SELEKTOR MƏCBURİDİR. Selektorsuz widget stylesheet-i Qt-də yalnız
        # widget-in ÖZÜNƏ yox, bütün ÖVLADLARINA da şamil olunur və tətbiq
        # səviyyəli QSS-i əzir. Burada nəticə görünməz sətir idi: aktiv rol
        # düyməsi fonunu bu qaydadan (ağ), mətn rəngini isə tətbiq QSS-indən
        # (ağ) alırdı — yəni seçilmiş rol ekranda ÜMUMİYYƏTLƏ görünmürdü.
        panel.setStyleSheet(
            f"QWidget#RolePanel {{"
            f"background-color: {self.theme.color('--color-sidebar-bg')};"
            f"border-right: 1px solid {self.theme.color('--color-sidebar-border')};"
            f"}}"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(12)

        layout.addWidget(title_label("Vəzifələr", size=15))

        self._role_search = QLineEdit()
        self._role_search.setPlaceholderText("Vəzifə axtar")
        self._role_search.setProperty("variant", "form")
        self._role_search.textChanged.connect(self._filter_roles)
        layout.addWidget(self._role_search)

        self._roles_layout = QVBoxLayout()
        self._roles_layout.setSpacing(4)
        holder = QWidget()
        holder.setLayout(self._roles_layout)
        layout.addWidget(holder)

        layout.addStretch(1)

        create = secondary_button("+ Yeni Vəzifə")
        create.clicked.connect(self.role_create_requested)
        layout.addWidget(create)
        return panel

    def set_roles(self, roles: list[tuple[str, str, int]]) -> None:
        """`roles`: (açar, ad, istifadəçi sayı)."""
        clear_layout(self._roles_layout)
        self._role_buttons.clear()

        for key, name, count in roles:
            button = QPushButton(f"{name}    {count}")
            button.setProperty("variant", "nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(metrics.NAV_ITEM_HEIGHT)
            button.clicked.connect(lambda _=False, k=key: self.select_role(k))
            self._roles_layout.addWidget(button)
            self._role_buttons[key] = button

    def _filter_roles(self, text: str) -> None:
        needle = text.strip().lower()
        for button in self._role_buttons.values():
            button.setVisible(needle in button.text().lower())

    def select_role(self, key: str) -> None:
        self._active_role = key
        for role_key, button in self._role_buttons.items():
            button.setProperty("active", "true" if role_key == key else "false")
            style = button.style()
            style.unpolish(button)
            style.polish(button)
        self.role_selected.emit(key)

    # ------------------------------ sağ panel -------------------------------- #

    def _build_matrix_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)

        self._matrix_title = title_label("", size=19)
        head_layout.addWidget(self._matrix_title)
        self._matrix_count = muted_label("")
        head_layout.addWidget(self._matrix_count)
        head_layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — deaktiv xananın İKİ fərqli səbəbi
        # (hardlock ↔ "bu icazə sizdə yoxdur") yalnız tooltip-də izah olunurdu,
        # yəni siçanı üzərinə gətirməyən istifadəçi fərqi heç vaxt görmürdü.
        self._help = HelpButton(
            self.theme,
            title=MATRIX_HELP_TITLE,
            intro=MATRIX_HELP_INTRO,
            steps=MATRIX_HELP_STEPS,
        )
        head_layout.addWidget(self._help)

        self._cancel = secondary_button("Ləğv Et")
        self._cancel.clicked.connect(self._on_cancel)
        head_layout.addWidget(self._cancel)

        self._save = action_button("Yadda Saxla")
        self._save.clicked.connect(self._on_save)
        head_layout.addWidget(self._save)
        layout.addWidget(head)
        layout.addWidget(Divider())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._groups_host = QWidget()
        self._groups_layout = QVBoxLayout(self._groups_host)
        self._groups_layout.setContentsMargins(0, 0, 0, 0)
        self._groups_layout.setSpacing(16)
        scroll.setWidget(self._groups_host)
        layout.addWidget(scroll, 1)

        layout.addWidget(
            muted_label(
                "Qıfıllı icazələr hardlock-dur — yalnız ROOT İdarə Mərkəzindən dəyişdirilir."
            )
        )
        layout.addWidget(self._build_override_card())
        return panel

    def _build_override_card(self) -> Card:
        card = Card(padding=16, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(title_label("Fərdi İstisna", size=15))
        card.add(muted_label("Bir istifadəçiyə rolundan kənar icazə vermək"))
        self._override_search = QLineEdit()
        self._override_search.setPlaceholderText("İstifadəçi axtar")
        self._override_search.setProperty("variant", "form")
        card.add(self._override_search)
        return card

    def set_matrix(
        self,
        role_name: str,
        groups: list[tuple[str, list[tuple[str, str, bool, bool, bool]]]],
    ) -> None:
        """Matrisi qurur.

        Args:
            groups: (kateqoriya adı, [(flag, etiket, aktiv, locked, aktorda_var)]).
                `locked` — D3: `PermissionFlag.is_grantable_to()`-nun BİRLƏŞMİŞ
                nəticəsi (statik hardlock + rola-görə anti-fraud/kamera-tip
                istisnaları), köhnə xalis "hardlock" sahəsini ƏVƏZ edir (bax
                `permission_matrix.py::_flag_groups`).

        ──────────────────────────────────────────────────────────────────────
        BEŞİNCİ SAHƏ — `aktorda_var` (aktorun ÖZÜNDƏ olan flag)
        ──────────────────────────────────────────────────────────────────────
        Backend `PositionManagementUseCase._apply_flags`-dəki Self-Escalation
        Guard aktorun özündə OLMAYAN flag-i rola verməsini onsuz da rədd edir.
        Lakin admin xananı işarələyib "Yadda Saxla" basana qədər bunu BİLMİRDİ:
        bütün seçim geri qaytarılır və o, hansı xananın günahkar olduğunu
        tapmağa çalışırdı. Deaktiv xana həmin qərarı seçimdən ƏVVƏL göstərir.

        Ekran heç nə HESABLAMIR — Self-Escalation Guard-ın məntiqi burada
        TƏKRARLANMIR; kontroller aktorun flag dəstini onsuz da bilir və hazır
        nəticəni ötürür. Əks halda qayda ÜÇÜNCÜ nüsxəyə sahib olardı.
        """
        clear_layout(self._groups_layout)
        self._checkboxes.clear()

        active_count = 0
        total_count = 0

        for group_name, items in groups:
            card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
            card.add(title_label(group_name, size=15))

            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(10)

            for index, (flag, label, enabled, locked, actor_owns) in enumerate(items):
                total_count += 1
                if enabled:
                    active_count += 1

                box = QCheckBox(label)
                box.setChecked(enabled)
                if locked:
                    # `locked` İNDİ `PermissionFlag.is_grantable_to()`-dan gəlir
                    # (D3) — statik hardlock SƏVİYYƏSİ VƏ rola-görə anti-fraud/
                    # kamera-tip istisnalarının (SEC-001 daxil) BİRLƏŞMİŞ
                    # nəticəsidir, ona görə tooltip mətni ÜMUMİ yazılıb (bax
                    # `permission_matrix.py::_flag_groups`).
                    box.setEnabled(False)
                    box.setIcon(icons.icon("lock", self.theme.color("--color-text-muted")))
                    box.setToolTip(
                        "Hardlock və ya vəzifə ayrılığı qaydası — bu icazə bu "
                        "rola verilə bilməz (dəyişdirilə bilməz)"
                    )
                elif not actor_owns:
                    # QIFIL İKONU QOYULMUR — səbəb fərqlidir və istifadəçi ikiuclu
                    # siqnal almamalıdır: qıfıl "heç kim dəyişə bilməz", boz xana
                    # isə "SƏN verə bilməzsən" deməkdir. Fərqi tooltip açır.
                    box.setEnabled(False)
                    box.setToolTip("Bu icazə sizdə yoxdur — başqasına verə bilməzsiniz")
                self._checkboxes[flag] = box
                grid.addWidget(box, index // 2, index % 2)

            holder = QWidget()
            holder.setLayout(grid)
            card.add(holder)
            self._groups_layout.addWidget(card)

        self._groups_layout.addStretch(1)
        self._matrix_title.setText(f"{role_name} — İcazələr")
        self._matrix_count.setText(f"{active_count} / {total_count} aktiv")
        self.show_content()

    def collected(self) -> dict[str, bool]:
        """Hazırkı işarələmələr — hardlock olanlar DA daxil (dəyişməz)."""
        return {flag: box.isChecked() for flag, box in self._checkboxes.items()}

    def _on_save(self) -> None:
        if self._active_role is not None:
            self.saved.emit(self._active_role, self.collected())

    def _on_cancel(self) -> None:
        if self._active_role is not None:
            self.role_selected.emit(self._active_role)


class RoleCreateDialog(QDialog):
    """«+ Yeni Vəzifə» modalı — ad, pillə və kamera-tipi.

    ──────────────────────────────────────────────────────────────────────────
    KOD SORUŞULMUR, ADDAN TÖRƏDİLİR
    ──────────────────────────────────────────────────────────────────────────
    `RoleDraft` həm `code`, həm `name_az` gözləyir, lakin kod maşın açarıdır
    (`ANBAR_NEZARETCISI`) və istifadəçidən onu ayrıca yazmasını istəmək iki
    sahəni sinxron saxlamaq yükünü ona ötürərdi. `PositionManagementUseCase`
    onsuz da kodu normallaşdırır (`_clean_code`: böyük hərf + alt-xətt), ona
    görə hər iki sahəyə EYNİ mətn verilir.

    ──────────────────────────────────────────────────────────────────────────
    KAMERA-TİPİ SEÇİMİ NİYƏ XƏBƏRDARLIQLA GƏLİR
    ──────────────────────────────────────────────────────────────────────────
    `is_camera_type=True` custom rol praktikada `Kamera_Nəzarətçisi`-nin
    ekvivalentidir və maliyyə nəticəli səlahiyyət daşıya bilər (bölmə 3). Use
    case onu operativ pillə ilə məhdudlaşdırır; dialoq isə həmin nəticəni
    seçimdən ƏVVƏL yazır ki, qərar məlumatlı olsun.

    ──────────────────────────────────────────────────────────────────────────
    "MAĞAZA-PİLLƏLİ" SEÇİMİ (T6) — `is_camera_type`-IN GÜZGÜSÜ
    ──────────────────────────────────────────────────────────────────────────
    CEO/Root Mağaza Menecerini prioritet-3 custom rola köçürüb anti-fraud
    qadağasını (satıcı-pilləli rollara verilə bilməyən flag-lər) yan keçə
    bilməsin deyə, "mağaza-pilləli" custom rol AÇIQ işarələnməlidir —
    `PermissionFlag.is_grantable_to()` bu bayraq olmadan yeni rolu tanımır və
    checkbox-ları YALNIŞ aktiv göstərər (bax `permission_matrix.py::
    _flag_groups`).

    Signals:
        submitted: (ad, prioritet dəyəri, kamera-tipli, mağaza-pilləli).
    """

    submitted = Signal(str, int, bool, bool)

    #: Açılan siyahıdakı pillələr — `RolePriority` dəyərləri ilə eyni sıra.
    #:
    #: ──────────────────────────────────────────────────────────────────────
    #: `Root` PİLLƏSİ (0) SİYAHIDA YOXDUR — SİLİNMƏ DEYİL, DÜZƏLİŞDİR
    #: ──────────────────────────────────────────────────────────────────────
    #: Əvvəllər siyahının ilk sətri «Rəhbərlik (0)» idi, çünki `Root` və `CEO`
    #: EYNİ pillədə (0) sayılırdı. Root/CEO ayrılığından sonra pillə 0 TƏK
    #: BAŞINA `Root`-a aiddir və orada yaradılan custom rol yanıltıcı olardı:
    #: `Position.effective_system_role` onu `Root` YOX, `CEO` semantikası ilə
    #: qiymətləndirir (bax `_PRIORITY_TO_ROLE`), yəni etiket səlahiyyətdən
    #: GÜCLÜ görünərdi. Həmin «Rəhbərlik» pilləsi itmir — dəyəri 1-dir və
    #: siyahının ilk sətri olaraq qalır.
    #:
    #: Praktikada bu, heç bir imkanı da bağlamır: pillə 0-lı rol yaratmaq
    #: onsuz da yalnız `Root` aktoruna mümkün idi (Strict Hierarchy Guard —
    #: yaradan CİDDİ ŞƏKİLDƏ yuxarıda olmalıdır və 0-dan yuxarı pillə yoxdur).
    PRIORITIES: Final[tuple[tuple[str, int], ...]] = (
        ("Rəhbərlik (1)", 1),
        ("Admin (2)", 2),
        ("Operativ (3)", 3),
        ("Personal (4)", 4),
    )

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Yeni Vəzifə")
        self.setModal(True)
        self.setMinimumWidth(472)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)
        card.add(title_label("Yeni Vəzifə", size=19))

        self._name = FormField(
            "Vəzifə adı",
            hint="İcazələr rol yaradıldıqdan sonra matrisdən verilir.",
        )
        card.add(self._name)

        self._priority = QComboBox()
        for label, value in self.PRIORITIES:
            self._priority.addItem(label, value)
        # Defolt «Personal (4)»: ən aşağı pillə ən az risklidir və pilləni
        # sonradan qaldırmaq, səhvən yüksək verilmiş pilləni endirməkdən
        # asandır.
        self._priority.setCurrentIndex(len(self.PRIORITIES) - 1)
        card.add(FormField("Səlahiyyət pilləsi", widget=self._priority))

        self._camera = QCheckBox("Kamera-tipli rol")
        card.add(self._camera)
        card.add(
            muted_label(
                "Kamera-tipli rol cərimə yaza bilən rollar sinfindəndir və "
                "yalnız operativ (3) və ya daha yüksək pillədə yaradıla bilər.",
                size=12,
            )
        )

        self._store = QCheckBox("Mağaza-pilləli rol")
        card.add(self._store)
        card.add(
            muted_label(
                "Mağaza-pilləli rol satıcı sinfindəndir və anti-fraud vəzifə "
                "ayrılığına (cərimə yazma/təsdiq, cüt-nəzarət) tabedir.",
                size=12,
            )
        )

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        create = action_button("Yarat")
        create.clicked.connect(self._on_submit)
        buttons_layout.addWidget(create)
        card.add(buttons)

        # Enter «Yarat»-ı işə salır: rol YARADILIR, heç nə silinmir və səhv
        # rol dərhal deaktiv edilə bilir. Açıq təyin edilməsəydi Qt ilk
        # düyməni («İmtina») defolt sayardı — Enter işi ləğv edərdi.
        create.setDefault(True)
        create.setAutoDefault(True)
        cancel.setAutoDefault(False)

        # Fokus sırası vizual sıra ilə: ad → pillə → kamera-tipi →
        # mağaza-pilləli → düymələr.
        QWidget.setTabOrder(self._name.input_widget(), self._priority)
        QWidget.setTabOrder(self._priority, self._camera)
        QWidget.setTabOrder(self._camera, self._store)
        QWidget.setTabOrder(self._store, cancel)
        QWidget.setTabOrder(cancel, create)

        self._name.focus_input()

    def _on_submit(self) -> None:
        name = self._name.text().strip()
        self._name.clear_error()
        if not name:
            self._name.set_error("Vəzifə adı məcburidir")
            return
        self.submitted.emit(
            name,
            int(self._priority.currentData()),
            self._camera.isChecked(),
            self._store.isChecked(),
        )
        self.accept()


# --------------------------------------------------------------------------- #
# 11 — İstifadəçi və Rol İdarəetməsi
# --------------------------------------------------------------------------- #


#: İşçilər ekranının kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: menyu maddəsi dəyişəndə
#: (məs. `ACTIONS`-a yeni bənd qoşulanda) redaktə edən adam mətni DƏRHAL
#: yanında görür; ayrı kataloqda saxlansaydı, mətn sükutla arxada qalardı.
USERS_HELP_TITLE: Final = "İşçilər"

USERS_HELP_INTRO: Final = (
    "Bu ekranda mağazaların işçiləri sadalanır. Hər sətrin sonundakı «···» "
    "düyməsi altı əməliyyat açır — aşağıda hər birinin nə etdiyi yazılıb. "
    "Diqqət: sonuncusu geri qaytarıla bilmir."
)

#: Addımların sırası `ACTIONS`-un sırası ilə EYNİDİR — istifadəçi menyunu
#: açıb köməyi yan-yana oxuyanda gözü eyni ardıcıllığı görməlidir.
USERS_HELP_STEPS: Final[tuple[str, ...]] = (
    "«PIN Sıfırla» — işçinin kiosk PIN-ini silir; işçi növbəti girişində "
    "yeni PIN təyin edir. Köhnə PIN dərhal işləməz olur.",
    "«Şifrəni Yenilə» — panelə giriş üçün müvəqqəti şifrə verir. İşçi ilk "
    "girişində onu dəyişməyə məcburdur.",
    "«Rolu Dəyiş» — işçinin rolunu, deməli görəcəyi ekranları dəyişir. "
    "Yalnız ÖZÜNÜZDƏN aşağı pilləyə toxuna bilərsiniz.",
    "«POS Səlahiyyəti» — endirim/void/refund həddini QEYD EDİR. Bu, yalnız "
    "sənədləşdirmədir: kassanı bloklamır, 1C-yə heç nə göndərmir.",
    "«Sənədlər» — müqavilə, tibbi arayış və digər sənədlərin bitmə "
    "tarixlərini idarə edir; bitmiş sənəd növbə cədvəlində xəbərdarlıq verir.",
    "«Deaktiv Et» — işçini siyahıdan çıxarır və girişini bağlayır. GERİ "
    "QAYTARILA BİLMİR: yenidən işə götürülərsə yeni işçi kartı açılır.",
)


class UsersScreen(Screen):
    """İşçi cədvəli — axtarış, yeni işçi, sətir əməliyyatları.

    Signals:
        create_requested: "Yeni İşçi".
        action_requested: (əməliyyat açarı, istifadəçi adı).
        search_changed: Axtarış mətni.
        status_filter_changed: "Vəziyyət" seçicisinin açarı
            (`"active"`/`"inactive"`/`"all"` — bax `_STATUS_FILTERS`).

    ──────────────────────────────────────────────────────────────────────────
    "VƏZİYYƏT" SEÇİCİSİ — QA-FULL FAZA 3, İSTİFADƏÇİNİN SÖZÜ İLƏ
    ──────────────────────────────────────────────────────────────────────────
    İstifadəçi: «işçi işdən çıxsa, işçinin üstünə basıb xitam vermək lazımdır
    ki, ƏLAVƏ YER TUTMASIN». `screen_data.py::_users` bunu artıq SERVER
    tərəfdə tətbiq edir — deaktiv işçilər DEFOLTDA sorğuya belə DÜŞMÜR (əks
    halda `LIMIT 500` altında yığılıb aktiv işçiləri sıxışdırırdılar, bax
    həmin funksiyanın başlığı). Amma soft-delete FİZİKİ SİLMƏ DEYİL
    (CLAUDE.md §4/§6: keçmiş qeyd SÜBUT olaraq lazımdır) — bu seçici həmin
    "gizlət, yox etmə" prinsipinin GÖRÜNƏN yarısıdır: admin istəyəndə
    deaktivləri YENƏ görə bilir.
    """

    create_requested = Signal()
    action_requested = Signal(str, str)
    search_changed = Signal(str)
    status_filter_changed = Signal(str)

    #: `(açar, etiket)` — etiketlər `_STATUS_TONES`-dəki "Aktiv"/"Deaktiv" ilə
    #: EYNİ terminologiyadır (sətir çipi ilə toolbar seçicisi arasında söz
    #: fərqi yaranmasın deyə). "Hamısı" DEFOLT DEYİL — İSTİFADƏÇİNİN sözü
    #: "əlavə yer tutmasın"dır, yəni defolt görünüş DAR olmalıdır.
    _STATUS_FILTERS: Final[tuple[tuple[str, str], ...]] = (
        ("active", "Aktiv"),
        ("inactive", "Deaktiv"),
        ("all", "Hamısı"),
    )

    #: Maketdəki ··· menyusu.
    #:
    #: `"pos_threshold"` — #7 POS Səlahiyyət Siyasəti (kompasos11.md Faza 4,
    #: sənədləşdirmə). Mövcud dörd maddə TOXUNULMADAN, əlavə kimi qoşulub —
    #: "Deaktiv Et"-dən ƏVVƏL, çünki geri dönməz əməliyyat menyunun sonunda
    #: qalmalıdır (UX konvensiyası).
    #: `"employee_documents"` — #17 İşçi Sənədləri (kompasos11.md Faza 7).
    #: EYNİ naxışla, `pos_threshold`-dan SONRA əlavə olunub — mövcud beş
    #: maddə TOXUNULMADAN qalır.
    ACTIONS: Final = (
        ("reset_pin", "PIN Sıfırla"),
        ("reset_password", "Şifrəni Yenilə"),
        ("change_role", "Rolu Dəyiş"),
        ("pos_threshold", "POS Səlahiyyəti"),
        ("employee_documents", "Sənədlər"),
        ("deactivate", "Deaktiv Et"),
    )

    _STATUS_TONES: Final[dict[str, ChipTone]] = {
        "Aktiv": "success",
        "Məzuniyyətdə": "info",
        "Bloklanıb": "danger",
        "Deaktiv": "neutral",
    }

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Ad, rol və ya mağaza")
        self._search.setProperty("variant", "form")
        self._search.setFixedWidth(320)
        self._search.textChanged.connect(self._on_search)
        toolbar_layout.addWidget(self._search)

        # "Vəziyyət" seçicisi (sinif başlığı) — DEFOLT "Aktiv": deaktiv
        # işçilər İSTİFADƏÇİNİN sözü ilə "əlavə yer tutmamalıdır". `group_h.py::
        # _build_role_filter` ilə EYNİ naxış (etiket + `QComboBox`).
        self._status_filter: str = "active"
        toolbar_layout.addWidget(muted_label("Vəziyyət"))
        self._status_filter_box = QComboBox()
        for key, label in self._STATUS_FILTERS:
            self._status_filter_box.addItem(label, key)
        self._status_filter_box.setProperty("variant", "form")
        self._status_filter_box.currentIndexChanged.connect(self._on_status_filter_changed)
        toolbar_layout.addWidget(self._status_filter_box)

        toolbar_layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — «···» menyusundakı altı əməliyyatın
        # hansının nə etdiyi (və hansının GERİ QAYTARILA BİLMƏDİYİ) burada
        # izah olunur; cədvəlin altındakı bir sətirlik qeyd yalnız adları
        # sadalayır.
        self._help = HelpButton(
            theme,
            title=USERS_HELP_TITLE,
            intro=USERS_HELP_INTRO,
            steps=USERS_HELP_STEPS,
        )
        toolbar_layout.addWidget(self._help)

        create = action_button(
            "Yeni İşçi",
            icon_name="plus",
            icon_color=theme.color("--color-action-text"),
        )
        create.clicked.connect(self.create_requested)
        toolbar_layout.addWidget(create)
        self.add(toolbar)

        #: Sonuncu doldurulmuş dəst — axtarış onun üzərində işləyir.
        self._users: list[dict[str, str]] = []

        #: `None` = HAMISI göstərilir (maket və köhnə çağıranlar üçün geriyə
        #: uyğun defolt). Canlı yol `set_permitted_actions()` ilə cari
        #: aktorun daşıdığı flag-lərə uyğun dar dəst göndərir — "GÖRMƏK =
        #: SƏLAHİYYƏTİN OLMASI" (kompasos-ui skill, bölmə 3): icazəsi
        #: olmayan bənd boz DEYİL, menyuda ÜMUMİYYƏTLƏ yoxdur (bax
        #: `screen_data.py::_users` və `controllers/user_lifecycle.py`,
        #: QA-FULL Faza 3).
        self._permitted_actions: frozenset[str] | None = None

        self._table = DataTable(
            [
                Column("İşçi", 260),
                Column("Rol", 200),
                Column("Mağaza", 220),
                Column("Vəziyyət", 160),
                Column("Əməliyyat"),
            ],
            theme,
            footnote=(
                "Sağ-klik və ya ··· menyusu ilə: PIN Sıfırla, Şifrəni Yenilə, "
                "Rolu Dəyiş, POS Səlahiyyəti, Sənədlər, Deaktiv Et."
            ),
        )
        self.add(self._table)

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    def search_field(self) -> QLineEdit:
        """Axtarış sahəsi — kontroller/testlər üçün."""
        return self._search

    def status_filter_selector(self) -> QComboBox:
        """ "Vəziyyət" seçicisi — kontroller/testlər üçün."""
        return self._status_filter_box

    def status_filter(self) -> str:
        """Cari "Vəziyyət" seçimi (`"active"`/`"inactive"`/`"all"`).

        `screen_data.py::_users` BUNU OXUYUR və SQL `WHERE`-ə keçirir — çünki
        deaktiv işçilər DEFOLTDA sorğuya belə DÜŞMÜR (sinif başlığı). Client-
        side axtarışdan (`_matches_search`) FƏRQLİ olaraq bu, SERVER-tərəfli
        süzgəcdir: seçim dəyişəndə dəst YENİDƏN oxunmalıdır (kontroller
        `status_filter_changed`-i dinləyib `refresh()` çağırır).
        """
        return self._status_filter

    def set_permitted_actions(self, keys: frozenset[str] | None) -> None:
        """ "···" menyusunun cari aktora GÖRÜNƏN bəndlərini məhdudlaşdırır.

        `None` HAMISINI göstərir (`__init__`-dəki defolt izahına bax).
        Sətirlər ARTIQ dolubsa cədvəl DƏRHAL yenidən qurulur ki, çağırış
        sırasından (bu, `set_users`-dan əvvəl VƏ ya sonra gələ bilər) asılı
        olmasın.
        """
        self._permitted_actions = keys
        if self._users:
            self._render()

    def set_users(self, users: list[dict[str, str]]) -> None:
        """Siyahını təzələyir; aktiv axtarış şərti QORUNUR.

        SƏTİRLƏR KEŞLƏNİR: axtarış hər hərfdə bazaya sorğu göndərməməlidir —
        `screen_data` onsuz da bütün dəsti gətirir və hər vuruşda yeni sorğu
        kadrı dondurardı. Eyni səbəblə yenidən oxumadan sonra süzgəc sıfırlanmır:
        yazı əməliyyatından (məs. «PIN Sıfırla») sonra siyahı yenilənir və
        operator axtardığı adamı yenidən yazmalı olsaydı, bu, hər əməliyyatdan
        sonra təkrarlanan bir cəza olardı.
        """
        self._users = list(users)
        self._render()

    def _on_search(self, text: str) -> None:
        """Axtarış sahəsi — SİYAHINI süzür, sonra siqnalı yayır.

        Əvvəllər `textChanged` birbaşa `search_changed` siqnalına relay
        olunurdu və həmin siqnalı heç bir kontroller dinləmirdi: istifadəçi
        yazırdı, siyahı isə toxunulmaz qalırdı. Boş ekranın mətni («Axtarış
        şərtinə uyğun işçi yoxdur») süzgəcin MÖVCUD olduğunu vəd edirdi —
        yəni interfeys bir davranış vəd edib onu yerinə yetirmirdi.

        Siqnal SAXLANILIR: server-tərəfli axtarış lazım olsa, kontroller ona
        qoşulub `set_users` ilə daha dar dəst göndərə bilər — yerli süzgəc
        həmin dəstin üzərində işləməyə davam edir.
        """
        self._render()
        self.search_changed.emit(text)

    def _on_status_filter_changed(self, index: int) -> None:
        """ "Vəziyyət" seçimi — `_on_search`-dan FƏRQLİ olaraq BURADA ekranı
        özü SÜZMÜR: seçim SERVER sorğusunun `WHERE` şərtidir, deaktiv
        işçilər `self._users`-də ÜMUMİYYƏTLƏ ola bilməz (dar dəst DEFOLTDUR,
        bax `status_filter()`). Ona görə siqnal ATILIR, kontroller onu
        dinləyib YENİDƏN oxuyur (`ShiftWindowController` ilə EYNİ naxış).
        """
        key = self._status_filter_box.itemData(index)
        self._status_filter = str(key) if key else "active"
        self.status_filter_changed.emit(self._status_filter)

    def _matches_search(self, user: dict[str, str]) -> bool:
        """Ad, istifadəçi adı, rol və mağaza üzrə uyğunluq (registrsiz).

        Dörd sahənin hamısı yoxlanılır, çünki yer tutucusu məhz bunu vəd edir
        («Ad, rol və ya mağaza»); `username` əlavə olunub, çünki cədvəldə
        adın altında GÖRÜNÜR və görünən mətnə görə axtara bilməmək izahsız
        olardı.
        """
        needle = self._search.text().strip().casefold()
        if not needle:
            return True
        haystack = " ".join(
            (
                user.get("full_name", ""),
                user.get("username", ""),
                user.get("role", ""),
                user.get("store", ""),
            )
        )
        return needle in haystack.casefold()

    def _render(self) -> None:
        users = [user for user in self._users if self._matches_search(user)]
        self._table.clear()
        if not users:
            self.show_empty(
                icon_name="users",
                title="İşçi tapılmadı",
                message="Axtarış şərtinə uyğun işçi yoxdur. Süzgəci dəyişin.",
            )
            return

        for user in users:
            identity = QWidget()
            identity_layout = QVBoxLayout(identity)
            identity_layout.setContentsMargins(0, 0, 0, 0)
            identity_layout.setSpacing(4)
            identity_layout.addWidget(body_label(user["full_name"], size=13, wrap=False))
            identity_layout.addWidget(mono_label(user["username"], muted=True))

            status = user.get("status", "Aktiv")
            self._table.add_row(
                [
                    identity,
                    user.get("role", ""),
                    user.get("store", ""),
                    Chip(status, self._STATUS_TONES.get(status, "neutral")),
                    self._build_actions(user["full_name"]),
                ]
            )
        self.show_content()

    def _build_actions(self, full_name: str) -> QWidget:
        button = QPushButton("···")
        button.setProperty("variant", "secondary")
        button.setFixedWidth(48)
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        menu = QMenu(button)
        for key, label in self.ACTIONS:
            # "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (bax `__init__`-dəki
            # `_permitted_actions` şərhi) — süzülən bənd `QAction`-a
            # ÇEVRİLMİR belə, boz göstərilmir.
            if self._permitted_actions is not None and key not in self._permitted_actions:
                continue
            menu.addAction(
                label,
                lambda k=key, name=full_name: self.action_requested.emit(k, name),
            )
        button.setMenu(menu)
        return button

    def table(self) -> DataTable:
        return self._table


class NewUserDialog(QDialog):
    """ "Yeni İşçi" modalı — `UsersScreen`-in `create_requested`-i açır.

    `create_requested` düyməsi VARDI, lakin heç bir kontroller onu dinləmirdi
    (yalnız CSV toplu idxalı işləyirdi) — bu, həmin boşluğu bağlayan dialoqdur.
    `PosThresholdDialog` ilə EYNİ naxış: ekran domen tiplərini TANIMIR, yalnız
    xam mətn/bool toplayır — `Position`/`StoreId`/`Username` kimi VO-lara
    çevirmə `controllers/user_admin.py`-dədir (CLAUDE.md §6).

    Signals:
        submitted: sözlük (aşağıdakı bütün sahələr, açar adları
            `controllers/user_admin.py`-də sabit kimi TƏKRARLANIR — dəyişəndə
            İKİSİ birlikdə dəyişməlidir).

    ──────────────────────────────────────────────────────────────────────────
    ƏN AZI BİR AUTENTİFİKASİYA VASİTƏSİ — DİALOQ SƏVİYYƏSİNDƏ DƏ YOXLANILIR
    ──────────────────────────────────────────────────────────────────────────
    `Employee` konstruktoru "PIN, VƏ YA istifadəçi adı + şifrə" invariantını
    domendə MƏCBUR edir (`_assert_has_authentication_method`), lakin bu
    yoxlamanı YALNIZ use case-ə buraxsaydıq, admin bütün formanı (ad, vəzifə,
    mağaza, tarix) doldurub "Yadda Saxla" basdıqdan SONRA rədd cavabı alardı
    və dialoq bağlanmadığı üçün YAZDIQLARI İTMƏZDİ — amma səbəb yalnız use
    case-in mətnindən görünərdi, sahə isə İŞARƏLƏNMƏZDİ. Ona görə eyni qayda
    burada da yoxlanılır (`PosThresholdDialog._on_submit` ilə eyni "sahə
    işarələ, bağlama" naxışı) — bu, domen qaydasının TƏKRARI deyil, onun
    İSTİFADƏÇİYƏ görünən əks-sədasıdır; həqiqi qapı YENƏ DƏ domendədir.

    ──────────────────────────────────────────────────────────────────────────
    KAMERA STORE-ID SAHƏSİ YALNIZ KAMERA-TİPLİ VƏZİFƏDƏ GÖRÜNÜR
    ──────────────────────────────────────────────────────────────────────────
    `UserManagementUseCase._apply_camera_stores` çox-mağazalı təyinatı YALNIZ
    Kamera Operatoru roluna icazə verir — başqa rolda göndərilən sahə use
    case-də RƏDD EDİLİR. Sahəni HƏMİŞƏ göstərmək "hansı rolda işə yarayır?"
    sualını admin özü sınaqla öyrənməli edərdi; bunun əvəzinə `is_camera_type`
    seçiləndə sahə görünür, seçilməyəndə ÜMUMİYYƏTLƏ RENDER OLUNMUR (bölmə 3-ün
    "görmək = lazım olması" prinsipi — mənasız sahə boz göstərilmir, gizlədilir).
    """

    submitted = Signal(dict)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        stores: list[tuple[str, str]],
        positions: list[tuple[str, str, bool]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        #: `position_id` → kamera-tipli bayrağı — seçim dəyişəndə sahənin
        #: görünürlüyünü qərarlaşdırmaq üçün (aşağı `_on_position_changed`).
        self._camera_positions = {position_id for position_id, _, camera in positions if camera}
        self.setWindowTitle("Yeni İşçi")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)
        card.add(title_label("Yeni İşçi", size=19))

        self._first_name = FormField("Ad")
        card.add(self._first_name)

        self._last_name = FormField("Soyad")
        card.add(self._last_name)

        position_box = QComboBox()
        for position_id, name_az, _camera in positions:
            position_box.addItem(name_az, position_id)
        position_box.currentIndexChanged.connect(self._on_position_changed)
        self._position = FormField("Vəzifə", widget=position_box)
        card.add(self._position)

        store_box = QComboBox()
        # Boş bənd BİRİNCİDİR VƏ USERDATA `""`-dir — "mağaza təyin edilməyib"
        # domendə QANUNİ haldır (`EmployeeDraft.store_id: StoreId | None`),
        # məcburi seçim isə Root/CEO kimi mağazasız rolları bloklayardı.
        store_box.addItem("— Seçilməyib —", "")
        for store_id, store_name in stores:
            store_box.addItem(store_name, store_id)
        self._store = FormField("Mağaza", widget=store_box)
        card.add(self._store)

        self._username = FormField(
            "İstifadəçi adı",
            placeholder="Admin panelə giriş üçün (kiosk-yalnız işçidə boş qalır)",
        )
        card.add(self._username)

        self._password = FormField(
            "İlkin şifrə",
            password=True,
            hint="İstifadəçi adı ilə BİRLİKDƏ tələb olunur. İşçi ilk girişdə dəyişməlidir.",
        )
        card.add(self._password)

        self._pin = FormField(
            "PIN (4 rəqəm)",
            password=True,
            hint="Kiosk girişi üçün — istifadəçi adı/şifrə əvəzinə (və ya onlarla birgə).",
        )
        card.add(self._pin)

        self._email = FormField(
            "Bildiriş e-poçtu",
            hint="YALNIZ bildiriş üçündür — girişə təsiri yoxdur (SEC-016).",
        )
        card.add(self._email)

        # TARİX SAHƏLƏRİ `FormField` (sadə mətn), `QDateEdit` DEYİL —
        # `EmployeeDocumentDialog` başlığındakı EYNİ səbəb: `qss.py`-də
        # `QDateEdit` üçün kontrast-yoxlanılmış rəng cütü yoxdur.
        # FORMAT GÖSTƏRİLİR, NÜMUNƏ TARİX YOX: «(məs. 2026-08-19)» hissəsi
        # SİLİNDİ — `test_no_form_field_shows_example_data` onu nümunə dəyər
        # kimi tutur və qayda haqlıdır: konkret tarix sahəni «doldurulmuş»
        # göstərir, `YYYY-AA-GG` isə yalnız NƏ formatda yazılacağını deyir.
        # Aşağıdakı «Doğum tarixi» sahəsi onsuz da belə yazılmışdı — ikisi
        # arasındakı fərq təsadüfi idi.
        self._hire_date = FormField("İşə başlama tarixi", placeholder="YYYY-AA-GG")
        card.add(self._hire_date)

        self._date_of_birth = FormField("Doğum tarixi", placeholder="YYYY-AA-GG")
        card.add(self._date_of_birth)

        self._camera_field = FormField(
            "Kamera Operatoru mağazaları",
            widget=MultiSelectCombo("Mağaza seçin…"),
            hint="Çox-seçimli təyinat — YALNIZ Kamera Operatoru rolunda tətbiq olunur.",
        )
        camera_widget = self._camera_field.input_widget()
        if isinstance(camera_widget, MultiSelectCombo):
            camera_widget.set_options(stores)
        card.add(self._camera_field)

        self._error = muted_label("")
        self._error.setProperty("variant", "danger-text")
        self._error.setVisible(False)
        card.add(self._error)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Yarat")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        save.setDefault(True)
        save.setAutoDefault(True)
        cancel.setAutoDefault(False)

        self._first_name.focus_input()
        self._on_position_changed(position_box.currentIndex())

    def _on_position_changed(self, _index: int) -> None:
        """Kamera sahəsi YALNIZ kamera-tipli vəzifədə göstərilir (bax sinif başlığı)."""
        widget = self._position.input_widget()
        position_id = widget.currentData() if isinstance(widget, QComboBox) else None
        self._camera_field.setVisible(position_id in self._camera_positions)

    def _on_submit(self) -> None:
        for field in (self._first_name, self._last_name):
            field.clear_error()
        self._error.setVisible(False)

        first_name = self._first_name.text().strip()
        last_name = self._last_name.text().strip()
        missing = False
        if not first_name:
            self._first_name.set_error("Ad məcburidir")
            missing = True
        if not last_name:
            self._last_name.set_error("Soyad məcburidir")
            missing = True

        position_widget = self._position.input_widget()
        position_id = (
            str(position_widget.currentData() or "")
            if isinstance(position_widget, QComboBox)
            else ""
        )
        if not position_id:
            self._error.setText("Vəzifə seçilməlidir.")
            self._error.setVisible(True)
            missing = True

        username = self._username.text().strip()
        password = self._password.text().strip()
        pin = self._pin.text().strip()
        # DOMEN QAYDASININ ƏKS-SƏDASI (bax sinif başlığı): PIN, VƏ YA
        # istifadəçi adı + şifrə BİRLİKDƏ — tək başına biri `Employee`
        # konstruktorunda YENƏ DƏ rədd edilir. İki addımlı yoxlama:
        #   1) istifadəçi adı və şifrə YA İKİSİ BİRLİKDƏ, YA HEÇ BİRİ —
        #      tək başına şifrə istifadəyə yaramaz, tək başına istifadəçi
        #      adı isə giriş vasitəsi vermir;
        #   2) (1) keçəndən sonra ən azı PIN, YA DA cüt mövcud olmalıdır.
        if bool(username) != bool(password):
            self._error.setText(
                "İstifadəçi adı və şifrə BİRLİKDƏ verilməlidir — biri "
                "olmadan digəri istifadə oluna bilməz."
            )
            self._error.setVisible(True)
            missing = True
        elif not pin and not username:
            self._error.setText(
                "PIN, YA DA istifadəçi adı + şifrə BİRLİKDƏ verilməlidir "
                "— işçinin ən azı bir giriş vasitəsi olmalıdır."
            )
            self._error.setVisible(True)
            missing = True

        if missing:
            return

        store_widget = self._store.input_widget()
        store_id = (
            str(store_widget.currentData() or "") if isinstance(store_widget, QComboBox) else ""
        )
        camera_widget = self._camera_field.input_widget()
        camera_store_ids = (
            camera_widget.selected_values() if isinstance(camera_widget, MultiSelectCombo) else []
        )

        self.submitted.emit(
            {
                "first_name": first_name,
                "last_name": last_name,
                "position_id": position_id,
                "store_id": store_id,
                "username": username,
                "password": password,
                "pin": pin,
                "notification_email": self._email.text().strip(),
                "hire_date": self._hire_date.text().strip(),
                "date_of_birth": self._date_of_birth.text().strip(),
                "camera_store_ids": camera_store_ids,
            }
        )
        self.accept()


class PosThresholdDialog(QDialog):
    """ "POS Səlahiyyəti" modalı — işçinin endirim/void/refund həddini göstərir/dəyişir.

    kompasos11.md struktur qərar A: bu, YALNIZ sənədləşdirmə formasıdır — heç
    bir POS əməliyyatını yoxlamır, 1C-yə heç nə göndərmir. `UsersScreen`-in
    "···" menyusundakı "POS Səlahiyyəti" bəndi ilə açılır (mövcud ekran
    SİLİNMİR, əlavə əməliyyat kimi qoşulur).

    Signals:
        submitted: (endirim faizi mətni, void, refund, qeyd).
        revoke_requested: "Geri Al" — mövcud səlahiyyəti soft-delete edir.
    """

    submitted = Signal(str, bool, bool, str)
    revoke_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employee_name: str,
        max_discount_pct: str,
        can_void: bool,
        can_refund: bool,
        note: str,
        ceiling_pct: str,
        has_existing: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("POS Səlahiyyəti")
        self.setModal(True)
        self.setMinimumWidth(472)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)
        card.add(title_label("POS Səlahiyyəti", size=19))
        card.add(muted_label(employee_name))
        card.add(Divider())
        card.add(
            muted_label(
                "Bu, YALNIZ rəsmi siyasət qeydidir — heç bir kassa əməliyyatını "
                "yoxlamır və 1C-yə bağlı deyil (kompasos11.md struktur qərarı A).",
                size=12,
            )
        )

        self._pct = FormField(
            "Maksimum endirim faizi (%)",
            hint=f"0–{ceiling_pct} arası (Root həddi: {ceiling_pct}%).",
        )
        self._pct.set_text(max_discount_pct)
        card.add(self._pct)

        self._void = QCheckBox("Satışı ləğv etmə səlahiyyəti (Void)")
        self._void.setChecked(can_void)
        card.add(self._void)

        self._refund = QCheckBox("Geri-qaytarma səlahiyyəti (Refund)")
        self._refund.setChecked(can_refund)
        card.add(self._refund)

        note_box = QWidget()
        note_layout = QVBoxLayout(note_box)
        note_layout.setContentsMargins(0, 0, 0, 0)
        note_layout.setSpacing(8)
        note_layout.addWidget(field_label("Qeyd (səbəb)"))
        self._note = QPlainTextEdit()
        # GÖSTƏRİŞDİR, NÜMUNƏ DEYİL — ona görə nümunə mətnlərin təmizlənməsində
        # SAXLANILIR: sahə boş qalır, mətn isə NƏ YAZILACAĞINI deyir. Səbəb
        # mübahisə halında həddin müdafiəsidir (`pos_threshold.py` başlığı).
        self._note.setPlaceholderText(
            "Bu səlahiyyət niyə verilir? Səbəbsiz hədd mübahisədə müdafiə olunmur."
        )
        self._note.setPlainText(note)
        self._note.setFixedHeight(80)
        note_layout.addWidget(self._note)
        card.add(note_box)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)

        # "Geri Al" YALNIZ mövcud, aktiv sətir varsa görünür — olmayan bir
        # səlahiyyəti "geri almaq" istifadəçini çaşdırardı.
        if has_existing:
            revoke = secondary_button("Geri Al")
            revoke.setProperty("variant", "danger")
            revoke.clicked.connect(self._on_revoke)
            buttons_layout.addWidget(revoke)

        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Yadda Saxla")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        save.setDefault(True)
        save.setAutoDefault(True)
        cancel.setAutoDefault(False)

        # Fokus sırası vizual sıra ilə: faiz → void → refund → qeyd → düymələr.
        QWidget.setTabOrder(self._pct.input_widget(), self._void)
        QWidget.setTabOrder(self._void, self._refund)
        QWidget.setTabOrder(self._refund, self._note)
        QWidget.setTabOrder(self._note, cancel)
        QWidget.setTabOrder(cancel, save)

        self._pct.focus_input()

    def _on_submit(self) -> None:
        text = self._pct.text().strip()
        self._pct.clear_error()
        if not text:
            self._pct.set_error("Endirim faizi məcburidir")
            return
        self.submitted.emit(
            text,
            self._void.isChecked(),
            self._refund.isChecked(),
            self._note.toPlainText().strip(),
        )
        self.accept()

    def _on_revoke(self) -> None:
        self.revoke_requested.emit()
        self.accept()


class ResetPinDialog(QDialog):
    """ "PIN Sıfırla" modalı — admin-vasitəçili PIN sıfırlaması (bölmə 2).

    QA-FULL Faza 3: `UsersScreen`-in "···" menyusundakı bu bənd əvvəl heç
    bir kontrollerə bağlı deyildi (bax `controllers/user_lifecycle.py`
    başlığı). `PosThresholdDialog` ilə EYNİ naxış: ekran domen tiplərini
    TANIMIR, yalnız xam mətni toplayır — `Pin` VO-suna çevirmə/yoxlama
    `controllers/user_lifecycle.py`-dədir (CLAUDE.md §6).

    Signals:
        submitted: yeni PIN (xam mətn, 4 rəqəm).
    """

    submitted = Signal(str)

    def __init__(
        self, theme: ThemeManager, *, employee_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("PIN Sıfırla")
        self.setModal(True)
        # EN 480-DİR, 420 DEYİL (simmetriya qapısı, `check_symmetry.py`):
        # 420 layihədə YALNIZ bu üç dialoqda işlənirdi və ölçü səpələnməsini
        # bir vahid artırırdı. Digər forma dialoqları (`annual_leave.py`,
        # `bulk_operations.py`) 480 işlədir — eyni sıra genişlikdə iki fərqli
        # ölçü yalnız ekranlar yan-yana görüləndə hiss olunan sürüşmə yaradır.
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)
        card.add(title_label("PIN Sıfırla", size=19))
        card.add(muted_label(employee_name))
        card.add(Divider())
        card.add(
            muted_label(
                "Köhnə PIN dərhal işləməz olur. İşçi bildiriş alır — sizin "
                "xahişiniz deyilsə dərhal rəhbərliyə bildirməlidir (bölmə 2).",
                size=12,
            )
        )

        self._pin = FormField("Yeni PIN (4 rəqəm)", password=True)
        card.add(self._pin)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Sıfırla")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        save.setDefault(True)
        save.setAutoDefault(True)
        cancel.setAutoDefault(False)

        self._pin.focus_input()

    def _on_submit(self) -> None:
        pin = self._pin.text().strip()
        self._pin.clear_error()
        if not pin:
            self._pin.set_error("Yeni PIN məcburidir")
            return
        # FORMAT/ZƏİFLİK YOXLAMASI BURADA TƏKRARLANMIR — `Pin.create()`
        # domendə edir (`user_lifecycle.py::_reset_pin`), rədd cavabı isə
        # `KompasOSError.user_message` ilə eyni "İmtina/Sıfırla" pəncərəsi
        # bağlanmadan modal xəta kimi göstərilir (`NewUserDialog` ilə eyni
        # qərar deyil — burada sahə ARTIQ silinib, ona görə sahə-səviyyəli
        # işarələmə mənasızdır).
        self.submitted.emit(pin)
        self.accept()


class ResetPasswordDialog(QDialog):
    """ "Şifrəni Yenilə" modalı — admin-vasitəçili şifrə sıfırlaması (bölmə 2).

    `ResetPinDialog` ilə EYNİ naxış (bax onun başlığı).

    Signals:
        submitted: yeni şifrə (xam mətn).
    """

    submitted = Signal(str)

    def __init__(
        self, theme: ThemeManager, *, employee_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Şifrəni Yenilə")
        self.setModal(True)
        # EN 480-DİR, 420 DEYİL (simmetriya qapısı, `check_symmetry.py`):
        # 420 layihədə YALNIZ bu üç dialoqda işlənirdi və ölçü səpələnməsini
        # bir vahid artırırdı. Digər forma dialoqları (`annual_leave.py`,
        # `bulk_operations.py`) 480 işlədir — eyni sıra genişlikdə iki fərqli
        # ölçü yalnız ekranlar yan-yana görüləndə hiss olunan sürüşmə yaradır.
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)
        card.add(title_label("Şifrəni Yenilə", size=19))
        card.add(muted_label(employee_name))
        card.add(Divider())
        card.add(
            muted_label(
                "İşçi ilk girişdə bu şifrəni DƏYİŞMƏYƏ MƏCBURDUR — admin şifrəni "
                "daimi bilməməlidir (`UserManagementUseCase.reset_password`).",
                size=12,
            )
        )

        self._password = FormField("Yeni şifrə", password=True)
        card.add(self._password)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Yenilə")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        save.setDefault(True)
        save.setAutoDefault(True)
        cancel.setAutoDefault(False)

        self._password.focus_input()

    def _on_submit(self) -> None:
        password = self._password.text().strip()
        self._password.clear_error()
        if not password:
            self._password.set_error("Yeni şifrə məcburidir")
            return
        self.submitted.emit(password)
        self.accept()


class ChangeRoleDialog(QDialog):
    """ "Rolu Dəyiş" modalı — işçinin vəzifəsini (deməli rolunu) dəyişir.

    `NewUserDialog`-un vəzifə seçimi ilə EYNİ combo naxışı, LAKİN yalnız
    BİR sahə var: `controllers/user_lifecycle.py::_change_role` mövcud
    işçini YÜKLƏYİR və draftı ONUN cari sahələri ilə doldurub YALNIZ
    `position`-u əvəzləyir — əks halda `UserManagementUseCase.update_employee`
    boş sahələri (mağaza, e-poçt, tarix) SİLƏRDİ (CLAUDE.md §6: use case
    draftın HAMISINI yazır, "yalnız dəyişəni göndər" YOXDUR).

    Signals:
        submitted: seçilmiş vəzifənin `position_id`-si (mətn).
    """

    submitted = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employee_name: str,
        current_role: str,
        positions: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Rolu Dəyiş")
        self.setModal(True)
        # EN 480-DİR, 420 DEYİL (simmetriya qapısı, `check_symmetry.py`):
        # 420 layihədə YALNIZ bu üç dialoqda işlənirdi və ölçü səpələnməsini
        # bir vahid artırırdı. Digər forma dialoqları (`annual_leave.py`,
        # `bulk_operations.py`) 480 işlədir — eyni sıra genişlikdə iki fərqli
        # ölçü yalnız ekranlar yan-yana görüləndə hiss olunan sürüşmə yaradır.
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)
        card.add(title_label("Rolu Dəyiş", size=19))
        card.add(muted_label(f"{employee_name} — hazırkı rol: {current_role}"))
        card.add(Divider())
        card.add(
            muted_label(
                "Yalnız ÖZÜNÜZDƏN aşağı pilləyə toxuna bilərsiniz (Strict "
                "Hierarchy Guard) — qadağan olan seçim növbəti addımda rədd edilir.",
                size=12,
            )
        )

        position_box = QComboBox()
        for position_id, name_az in positions:
            position_box.addItem(name_az, position_id)
        self._position = FormField("Yeni vəzifə", widget=position_box)
        card.add(self._position)

        self._error = muted_label("")
        self._error.setProperty("variant", "danger-text")
        self._error.setVisible(False)
        card.add(self._error)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Dəyiş")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        save.setDefault(True)
        save.setAutoDefault(True)
        cancel.setAutoDefault(False)

    def _on_submit(self) -> None:
        widget = self._position.input_widget()
        position_id = str(widget.currentData() or "") if isinstance(widget, QComboBox) else ""
        self._error.setVisible(False)
        if not position_id:
            self._error.setText("Vəzifə seçilməlidir.")
            self._error.setVisible(True)
            return
        self.submitted.emit(position_id)
        self.accept()


class EmployeeDocumentDialog(QDialog):
    """ "Sənədlər" modalı — işçinin sənəd/müqavilə siyahısı + yeni sənəd forması.

    #17 (kompasos11.md Faza 7). `PosThresholdDialog` ilə EYNİ naxış: `UsersScreen`-in
    "···" menyusundakı "Sənədlər" bəndi ilə açılır, mövcud ekran SİLİNMİR.

    TARİX SAHƏSİ NİYƏ `FormField` (sadə mətn), `QDateEdit` DEYİL: `open_shift.py`
    başlığındakı EYNİ səbəb — `qss.py`-də `QDateEdit` üçün kontrast-yoxlanılmış
    rəng cütü YOXDUR, onu əlavə etmək `scripts/check_contrast.py`-a yeni cüt
    gətirərdi. `FormField`-in `QLineEdit[variant="form"]` cütü ARTIQ yoxlanılıb.

    Signals:
        document_added: (sənəd növü, nömrə, bitmə tarixi mətni, diqqət tələb
            edən sənəd bayrağı (`is_blocking` — bloklamır, bax
            `domain/document_rules.py`), seçilmiş faylın YEREL yolu — boş sətir
            ola bilər, fayl SEÇİLMƏSƏ belə qeyd yaradılmalıdır, bax
            `_file_path` başlığı).
        deactivate_requested: sətrin `document_id`-si (mətn) — səbəb
            kontrollerdə `QInputDialog` ilə soruşulur (`controllers/open_shift.py`
            `_ask_reason` ilə eyni naxış).
    """

    document_added = Signal(str, str, str, bool, str)
    deactivate_requested = Signal(str)

    _STATUS_TONES: Final[dict[str, ChipTone]] = {
        "Aktiv": "success",
        "Bitib": "danger",
        "Deaktiv": "neutral",
    }

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employee_name: str,
        documents: list[dict[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        #: Seçilmiş faylın YEREL (disk üstü) yolu — `""` = seçilməyib.
        #: `set_file()` naxışı (`fine_entry.py`-dəki `PhotoDropZone` ilə eyni)
        #: bir addım sadələşib: burada sürüklə-burax YOXDUR, çünki sənəd forması
        #: modaldır və drag-drop səthi əlavə mürəkkəblik gətirərdi.
        self._file_path = ""
        self.setWindowTitle("Sənədlər")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)
        card.add(title_label("Sənədlər", size=19))
        card.add(muted_label(employee_name))
        card.add(Divider())

        self._table = DataTable(
            [
                Column("Növ", 150),
                Column("Nömrə", 110),
                Column("Bitmə tarixi", 120),
                # SÜTUN ADI «Bloklayıcı» DEYİL: sahə heç nə bloklamır və
                # başlıqdakı söz HR-a yanlış təhlükəsizlik hissi verirdi
                # (bax `domain/document_rules.py` başlığı). Mətn domendəki
                # SABİTDƏN gəlir ki, bildiriş və ekran ayrılmasın.
                Column(ATTENTION_FLAG_LABEL_AZ, 130),
                Column("Vəziyyət", 100),
                Column("Əməliyyat"),
            ],
            theme,
            footnote=(
                f"{ATTENTION_FLAG_LABEL_AZ} sənəd bitibsə Növbə Matrisində təyinat "
                "zamanı xəbərdarlıq göstərilir — təyinat BLOKLANMIR, işçi işə "
                "buraxılmağa davam edir."
            ),
        )
        self.set_documents(documents)
        card.add(self._table)

        card.add(Divider())
        card.add(body_label("Yeni sənəd əlavə et", size=13))

        self._doc_type = FormField("Sənəd növü")
        card.add(self._doc_type)

        self._doc_number = FormField("Sənəd nömrəsi (könüllü)")
        card.add(self._doc_number)

        # Format göstərişi `hint`-dədir, placeholder-də YOX: hint sahənin
        # ALTINDA yazılır və qutunu dolu göstərmir. Formatsız qalsaydı sahə
        # cavabsız olardı — «12.08.2026» ilə «2026-08-12» arasında seçimi
        # istifadəçi bilməzdi və səhv dəyər sükutla rədd edilərdi.
        self._expiry = FormField(
            "Bitmə tarixi",
            hint="İL-AY-GÜN formatında. Boş buraxılsa sənəd müddətsiz sayılır.",
        )
        card.add(self._expiry)

        self._blocking = QCheckBox(
            "Bu sənəd bitəndə növbə təyinatında xəbərdarlıq göstərilsin "
            f"({ATTENTION_FLAG_LABEL_INLINE_AZ} sənəd — təyinat bloklanmır)"
        )
        card.add(self._blocking)

        # ──────────────────────────────────────────────────────────────────
        # FAYL SEÇİCİSİ — #17 (Faza 7), sübut yükləmə növbəsinin YAZI yolu
        # ──────────────────────────────────────────────────────────────────
        # `file_ref` NULL qala bilər (DB qaydası, `EmployeeDocument.file_ref`
        # başlığı) — fayl seçilməzsə də qeyd yaradılmalıdır, ona görə bu sahə
        # MƏCBURİ DEYİL. Seçilmiş yol `_file_path`-də saxlanır və
        # `document_added` siqnalı ilə kontrollerə ötürülür; faktiki YÜKLƏMƏ
        # (spool + Drive növbəsi) burada BAŞLAMIR — o, kontrollerin işidir
        # (`controllers/employee_documents.py` başlığı, `fine_entry.py` ilə
        # EYNİ "əvvəlcə diskə, sonra bazaya" sırası).
        # Etiket qəbul edilən formatı ADLA sayır: istifadəçi "şəkil" sözünü
        # oxuyub PDF müqaviləsini seçməkdən çəkinməsin (SEC-018 sənəd tərəfində
        # PDF-i AÇIQ şəkildə icazəli edir).
        card.add(field_label("Skan/sənəd — PDF və ya şəkil (könüllü)"))
        file_row = QWidget()
        file_row_layout = QHBoxLayout(file_row)
        file_row_layout.setContentsMargins(0, 0, 0, 0)
        file_row_layout.setSpacing(12)
        self._file_label = muted_label("Fayl seçilməyib")
        file_row_layout.addWidget(self._file_label, stretch=1)
        pick_button = secondary_button("Fayl Seç")
        pick_button.clicked.connect(self._pick_file)
        file_row_layout.addWidget(pick_button)
        card.add(file_row)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        close_button = secondary_button("Bağla")
        close_button.clicked.connect(self.accept)
        buttons_layout.addWidget(close_button)

        add_button = action_button("Sənəd Əlavə Et")
        add_button.clicked.connect(self._on_add)
        buttons_layout.addWidget(add_button)
        card.add(buttons)

        add_button.setDefault(True)
        add_button.setAutoDefault(True)
        close_button.setAutoDefault(False)

        self._doc_type.focus_input()

    def set_documents(self, documents: list[dict[str, str]]) -> None:
        """Cədvəli yeniləyir — kontroller əlavə/deaktivasiya sonrası çağırır."""
        self._table.clear()
        if not documents:
            self._table.add_row([muted_label("Hələ sənəd əlavə edilməyib"), "", "", "", "", ""])
            return
        for document in documents:
            status = document.get("status", "Aktiv")
            row_actions: QWidget | str = ""
            if status == "Aktiv":
                deactivate = secondary_button("Deaktiv Et")
                deactivate.setProperty("variant", "danger")
                document_id = document["id"]
                deactivate.clicked.connect(
                    lambda _checked=False, doc_id=document_id: self.deactivate_requested.emit(
                        doc_id
                    )
                )
                row_actions = deactivate
            self._table.add_row(
                [
                    document.get("doc_type", ""),
                    document.get("doc_number", "") or "—",
                    document.get("expiry_date", "") or "Müddətsiz",
                    "Bəli" if document.get("is_blocking") == "true" else "Xeyr",
                    Chip(status, self._STATUS_TONES.get(status, "neutral")),
                    row_actions,
                ]
            )

    def _pick_file(self) -> None:
        """Fayl seçimini açır — siçan üçün YEGANƏ yol (drag-drop YOXDUR, bax konstruktor).

        SÜZGƏC PDF-İ DƏ GÖSTƏRİR: müqavilə praktikada PDF-dir (SEC-018), süzgəc
        isə yalnız şəkilləri saydığı üçün istifadəçi öz sənədini pəncərədə
        GÖRMÜRDÜ — yəni modul əsas istifadə halında işləmirdi. Süzgəcin ÖZÜ
        qoruma DEYİL (istifadəçi "Bütün fayllar"a keçə bilər və Qt-nin süzgəci
        məzmuna baxmır); həqiqi qapı `validate_evidence_payload`-dadır.

        Birləşmiş bənd BİRİNCİDİR — defolt seçim odur; ayrıca "PDF"/"Şəkillər"
        bəndləri isə çoxlu faylı olan qovluqda axtarışı daraltmaq üçündür.
        """
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Sənəd skanı seçin",
            "",
            "Sənəd faylları (*.pdf *.png *.jpg *.jpeg *.webp)"
            ";;PDF sənədləri (*.pdf)"
            ";;Şəkillər (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        self._file_path = path
        self._file_label.setText(path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])

    def _on_add(self) -> None:
        self._doc_type.clear_error()
        doc_type = self._doc_type.text().strip()
        if not doc_type:
            self._doc_type.set_error("Sənəd növü məcburidir")
            return
        self.document_added.emit(
            doc_type,
            self._doc_number.text().strip(),
            self._expiry.text().strip(),
            self._blocking.isChecked(),
            self._file_path,
        )

    def clear_form(self) -> None:
        """Uğurlu əlavədən sonra formu boşaldır — kontroller çağırır."""
        self._doc_type.set_text("")
        self._doc_number.set_text("")
        self._expiry.set_text("")
        self._blocking.setChecked(False)
        self._file_path = ""
        self._file_label.setText("Fayl seçilməyib")
        self._doc_type.focus_input()


# --------------------------------------------------------------------------- #
# 12 — Növbə Planlama
# --------------------------------------------------------------------------- #


class ShiftPlanningScreen(Screen):
    """Aylıq növbə matrisi — işçi × gün.

    Signals:
        publish_requested: "Planı Yayımla".
        month_changed: (-1 və ya +1).
        open_shift_post_requested: "Açıq Növbə Elan Et" (#16).
        open_shift_cancel_requested: Elanın "Ləğv Et" düyməsi (#16, elan id-si).
        work_mode_selected: İş Rejimi dropdown-unda seçim (Faza 7, `work_mode_id`).

    #16 (AÇIQ NÖVBƏ BAZARI) MATRİSƏ TOXUNMUR: kart matrisin ALTINA əlavə
    olunur, `set_matrix`/`LEGEND`/şablon məntiqi olduğu kimi qalır. Kartın
    ÖZÜ ayrı moduldadır (`screens/open_shift.py`) — səbəb orada yazılıb.

    ──────────────────────────────────────────────────────────────────────────
    İŞ REJİMİ DROPDOWN-U (Faza 7) — NƏ ƏLAVƏ OLUNDU, NƏ OLUNMADI
    ──────────────────────────────────────────────────────────────────────────
    ƏLAVƏ OLUNDU: `work_modes` kataloqundan gələn seçici + seçilmiş rejimin
    GÜNDƏLİK NORMA SAATINI göstərən nişan. Norma saat kataloqda SÜTUN kimi
    saxlanmır — `bitmə − başlanğıc` fərqindən hesablanır
    (`domain/work_norm.daily_norm_hours`), ona görə ekranda göstərilən rəqəm
    hesabatdakı ilə eyni funksiyadan gəlir.

    ƏLAVƏ OLUNMADI: təyinetmə məntiqi. Növbənin yazılması yenə
    `ShiftPlanningUseCase.assign_work_day` → `apply_assignment`-dədir və bu
    ekran ona BİR SƏTİR belə əlavə etmir; dropdown yalnız «hansı şablon
    seçilib» sualının cavabını verir (`selected_work_mode_id()`).
    """

    publish_requested = Signal()
    month_changed = Signal(int)
    open_shift_post_requested = Signal()
    open_shift_cancel_requested = Signal(str)
    work_mode_selected = Signal(str)

    #: Növbə kodları (maketdəki izah sətri).
    LEGEND: Final = (
        ("S", "Səhər 09:00–18:00", "--color-info"),
        ("A", "Axşam 13:00–22:00", "--color-warning"),
        # İSTİRAHƏT GÜNÜ — MƏTN RƏNGİ FON RƏNGİ İLƏ EYNİ OLA BİLMƏZ.
        # Əvvəl burada `--color-neutral-bg` yazılırdı, nişanın FONU isə elə
        # həmin tokendir: nəticədə «—» işarəsi hər iki temada tam görünməz
        # qalırdı (ölçüldü: 1.12:1 işıqlı, 1.14:1 tünd). Əfsanə sətri boş
        # kvadrat kimi görünürdü və oxucu «istirahət günü» kodunun nə olduğunu
        # bilmirdi. Rəng cütü palitrada düzgün idi — səhv onun İŞLƏNDİYİ
        # yerdə idi, ona görə `check_contrast.py` bunu tuta bilmirdi.
        ("", "İstirahət günü", "--color-text-muted"),
        ("M", "Məzuniyyət", "--color-text-muted"),
    )

    TEMPLATES: Final = ("5/2", "6/1", "2/2", "Fərdi")

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._cells: dict[tuple[str, int], QLabel] = {}

        self.add(self._build_toolbar())

        self._matrix_card = Card(padding=0, spacing=0)
        self._matrix_scroll = QScrollArea()
        self._matrix_scroll.setWidgetResizable(True)
        self._matrix_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._matrix_host = QWidget()
        self._matrix_grid = QGridLayout(self._matrix_host)
        self._matrix_grid.setContentsMargins(16, 16, 16, 16)
        self._matrix_grid.setSpacing(4)
        self._matrix_scroll.setWidget(self._matrix_host)
        self._matrix_card.add(self._matrix_scroll)
        self.add(self._matrix_card)

        # #16 — açıq növbə bazarı matrisin ALTINDA: admin əvvəlcə planı görür,
        # boşluğu MÜƏYYƏN EDİR, sonra elan edir. Kart yuxarıda olsaydı, qərarın
        # əsası (matris) ekrandan sürüşərdi.
        from src.presentation.screens.open_shift import OpenShiftMarketCard  # noqa: PLC0415

        self._open_shift_card = OpenShiftMarketCard(theme)
        self._open_shift_card.post_requested.connect(self.open_shift_post_requested)
        self._open_shift_card.cancel_requested.connect(self.open_shift_cancel_requested)
        self.add(self._open_shift_card)

        self.add(self._build_footer())

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        previous = secondary_button("‹")
        previous.setFixedWidth(44)
        previous.clicked.connect(lambda: self.month_changed.emit(-1))
        layout.addWidget(previous)

        self._month_label = title_label("", size=15)
        layout.addWidget(self._month_label)

        nxt = secondary_button("›")
        nxt.setFixedWidth(44)
        nxt.clicked.connect(lambda: self.month_changed.emit(1))
        layout.addWidget(nxt)

        self._store_combo = QComboBox()
        self._store_combo.setProperty("variant", "form")
        self._store_combo.setFixedWidth(220)
        layout.addWidget(self._store_combo)

        # Faza 7 — İş Rejimi SEÇİCİSİ. Mağaza seçicisi ilə eyni `variant="form"`
        # xassəsi qəsdəndir: yeni rəng cütü yaranmır, kontrast qapısı (130 cüt)
        # olduğu kimi qalır.
        self._mode_combo = QComboBox()
        self._mode_combo.setProperty("variant", "form")
        self._mode_combo.setFixedWidth(220)
        self._mode_combo.currentIndexChanged.connect(self._emit_work_mode)
        layout.addWidget(self._mode_combo)

        # Nişan artıq şablonun ADINI deyil, ondan ÇIXAN gündəlik normanı
        # göstərir — seçim ilə maaş hesablaması arasındakı əlaqə görünən olur.
        self._mode_label = Chip("İş Rejimi: 5/2", "info")
        layout.addWidget(self._mode_label)

        layout.addWidget(stretch())

        # ──────────────────────────────────────────────────────────────────────
        # «PLANI YAYIMLA» DÜYMƏSİ SİLİNDİ — ARXASINDA HEÇ NƏ YOX İDİ
        # ──────────────────────────────────────────────────────────────────────
        # Düymə `publish_requested` yayırdı, lakin heç bir kontroller onu
        # dinləmirdi və `ShiftPlanningUseCase`-də «nəşr» ANLAYIŞI DA YOXDUR:
        # matrisdəki hər toxunuş `apply_assignment` ilə DƏRHAL yazılır, yəni
        # plan onsuz da canlıdır.
        #
        # Ona görə düymə sadəcə işləmirdi DEYİL — YANLIŞ MODEL öyrədirdi:
        # menecer «hələ yayımlamamışam, deməli işçilər görmür» sanıb matrisdə
        # sınaq dəyişiklikləri edə bilərdi, halbuki hər klik artıq qüvvədədir.
        # Bu, sükutla işləməyən düymədən daha zərərlidir.
        #
        # `publish_requested` siqnalı SAXLANILIR: gələcəkdə həqiqi nəşr axını
        # (məs. «ay hazırdır» bildirişi) əlavə olunarsa, ekranın müqaviləsi
        # dəyişməyəcək — bax `test_signal_wiring_gate.py::NEVER_RAISED`.
        return bar

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.CARD_SPACING)

        legend = Card(padding=16, spacing=metrics.CARD_CONTENT_SPACING)
        legend.add(title_label("Növbə kodları", size=15))
        for code, description, token in self.LEGEND:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)
            badge = plain_label(code or "—")
            badge.setFixedSize(26, 26)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                f"background-color: {self.theme.color('--color-neutral-bg')};"
                f"color: {self.theme.color(token)};"
                "border-radius: 6px;"
            )
            row_layout.addWidget(badge)
            row_layout.addWidget(body_label(description, size=13, wrap=False))
            row_layout.addWidget(stretch())
            legend.add(row)
        layout.addWidget(legend, 1)

        # «İŞ REJİMİ ŞABLONLARI» KARTI ÇIXARILDI (QA-FULL FAZA 3, istifadəçi qərarı)
        #
        # Dörd düymə (`TEMPLATES`) `template_selected` siqnalını yayırdı, onu isə
        # HEÇ KİM dinləmirdi — nə kontroller, nə ekranın özü. Altındakı mətn
        # «boş xanalar avtomatik doldurulur» VƏD EDİRDİ. Canlı sınaqda klik
        # heç bir nəticə vermədi: sükutla-boş-ekrandan pisdir, çünki əməliyyatın
        # icra olunduğu təsəvvürü yaranır.
        #
        # NİYƏ DOLDURMA YAZILMADI, NİYƏ SİLİNDİ: bu ekranın YAZI yolu YOXDUR —
        # «Planı Yayımla» əvvəlki fazada QƏSDƏN çıxarılıb və matris xanaları
        # sadəcə etiketdir. Şablon doldurması yazı yolu, əmək-uyğunluq qaydası
        # və yayımlama axını tələb edir; düymələr həmin çıxarılmış funksiyanın
        # QALIĞI idi. Təyinetmə məntiqi yenə `ShiftPlanningUseCase.
        # assign_work_day`-dədir (bax sinif başlığı) — ekran ona bir sətir də
        # əlavə etmirdi.
        #
        # `TEMPLATES` SABİTİ QALIR: `tests/unit/test_labor_rules.py` 6/1 rejimini
        # məhz bu siyahıya istinadla sınayır — sabit iş rejimlərinin ADLARIDIR,
        # düymələrin deyil.

        self._summary = Card(padding=16, spacing=metrics.CARD_CONTENT_SPACING)
        self._summary.add(title_label("Ayın xülasəsi", size=15))
        self._summary_rows = QVBoxLayout()
        self._summary_rows.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._summary_rows)
        self._summary.add(holder)
        layout.addWidget(self._summary, 1)

        layout.addWidget(self._build_staffing_card(), 1)
        return footer

    def _build_staffing_card(self) -> QWidget:
        """#13 — tarixi nümunə kartı (QEYRİ-MƏCBURİ göstərici).

        AYRI KART, «Ayın xülasəsi»NİN İÇİNDƏ DEYİL — bu, dizayn qərarıdır:
        xülasə FAKTdır (planlaşdırılmış saat, açıq növbə), bu isə TƏXMİNdir.
        İkisini eyni kartda göstərmək təxmini fakt kimi oxutdurardı; #13-ün
        açıq tələbi isə istifadəçinin onu proqnoz sanmamasıdır.
        """
        self._staffing_card = Card(padding=16, spacing=metrics.CARD_CONTENT_SPACING)
        self._staffing_card.add(title_label("Tarixi nümunə (məsləhət)", size=15))
        self._staffing_rows = QVBoxLayout()
        self._staffing_rows.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._staffing_rows)
        self._staffing_card.add(holder)

        # XƏBƏRDARLIQ MƏTNİ SABİTDİR və məlumatdan ƏVVƏL qurulur: siyahı boş
        # olsa belə görünür, çünki göstəricinin NƏ OLMADIĞI onun nə olduğu
        # qədər vacibdir (kompasos11.md #13 — "GUI-də bu açıq bildirilməlidir").
        self._staffing_note = muted_label(
            "Bu, tələb proqnozu DEYİL: keçmiş davamiyyət tarixçəsinin ortasıdır "
            "və heç nəyi avtomatik təyin etmir. Nəzərə almaq qərarı sizindir."
        )
        self._staffing_card.add(self._staffing_note)
        return self._staffing_card

    def set_month(self, label: str, *, stores: list[str], mode: str) -> None:
        """DAVRANIŞI DƏYİŞMƏYİB — maket və canlı yol eyni imza ilə çağırır.

        `mode` mətni dropdown-a TOXUNMUR: seçici canlı kataloqdan
        (`set_work_modes`) dolur, bu isə yalnız nişan mətnidir. İkisini
        birləşdirmək maket rejimində uydurma `work_mode_id` yaradardı.
        """
        self.set_window_label(label)
        if stores and self._store_combo.count() == 0:
            self._store_combo.addItems(stores)
        self._mode_label.setText(f"İş Rejimi: {mode}")

    def set_window_label(self, label: str) -> None:
        """Toolbar-dakı «‹ [aralıq] ›» etiketi — CANLI yolun İŞLƏTDİYİ setter.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `set_month()` DEYİL (QA-FULL FAZA 3 tapıntısı)
        ──────────────────────────────────────────────────────────────────────
        Canlı yol (`screen_data.py`) `set_month()`-u HEÇ VAXT çağırmırdı —
        yalnız maket çağırırdı — və nəticədə istehsalatda etiket HƏMİŞƏ BOŞ
        qalırdı: istifadəçi oxlarla gəzir, amma hansı tarix aralığına baxdığını
        GÖRMÜRDÜ.

        Canlı yolu birbaşa `set_month()`-a bağlamaq DÜZGÜN OLMAZDI: onun
        `mode` arqumenti `_mode_label`-a yazır, həmin nişanı isə canlı rejimdə
        ARTIQ `set_work_mode_norm()` doldurur (`controllers/shift_matrix.py`) —
        yəni `set_month()` seçilmiş rejimin gündəlik normasını SÜKUTLA
        üstələyərdi. Ona görə etiket ayrıca, dar setterlə yazılır; `set_month()`
        maket yolunda onu ÖZÜ çağırır, yəni iki yol eyni widget-i işlədir.
        """
        self._month_label.setText(label)

    # --------------------------- İş Rejimi seçicisi -------------------------- #

    def set_work_modes(self, modes: list[tuple[str, str]]) -> None:
        """Dropdown-u kataloqdan doldurur — `(work_mode_id, etiket)`.

        SİQNAL BLOKLANIR: `addItem` hər dəfə `currentIndexChanged` doğurur və
        doldurma zamanı yayılan siqnal kontrolleri hələ seçilməmiş dəyərlə
        işə salardı. Doldurma bitdikdən SONRA bir dəfə — və yalnız siyahı boş
        deyilsə — yayılır.
        """
        blocked = self._mode_combo.blockSignals(True)
        try:
            self._mode_combo.clear()
            for mode_id, label in modes:
                self._mode_combo.addItem(label, mode_id)
        finally:
            self._mode_combo.blockSignals(blocked)
        if modes:
            self._emit_work_mode()

    def selected_work_mode_id(self) -> str:
        """Cari seçim — növbə təyinetməsi bu dəyəri oxuyur (boşdursa `""`)."""
        data = self._mode_combo.currentData()
        return "" if data is None else str(data)

    def select_work_mode(self, work_mode_id: str) -> bool:
        """Seçimi PROQRAM YOLU ilə dəyişir; tapılmasa `False` qaytarır.

        Sükutla ilk elementə düşmür: tapılmayan rejim (məs. kataloqdan
        çıxarılmış şablon) seçilsəydi, istifadəçi BAŞQA bir rejimi seçdiyini
        bilmədən növbə təyin edərdi.
        """
        index = self._mode_combo.findData(work_mode_id)
        if index < 0:
            return False
        self._mode_combo.setCurrentIndex(index)
        return True

    def set_work_mode_norm(self, text: str) -> None:
        """Seçilmiş rejimin gündəlik normasını nişanda göstərir."""
        self._mode_label.setText(text)

    def _emit_work_mode(self) -> None:
        self.work_mode_selected.emit(self.selected_work_mode_id())

    def set_matrix(
        self,
        days: list[tuple[int, str]],
        rows: list[tuple[str, list[str]]],
    ) -> None:
        """Matrisi qurur.

        Args:
            days: (gün nömrəsi, həftə günü qısaltması).
            rows: (işçi adı, hər gün üçün kod siyahısı).
        """
        clear_layout(self._matrix_grid)
        self._cells.clear()

        header = plain_label("İşçi")
        header.setProperty("variant", "mono-muted")
        self._matrix_grid.addWidget(header, 0, 0)

        for column, (number, weekday) in enumerate(days, start=1):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(0)
            number_label = plain_label(str(number))
            number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number_font = number_label.font()
            number_font.setPixelSize(11)
            number_label.setFont(number_font)
            cell_layout.addWidget(number_label)
            weekday_label = muted_label(weekday, size=11)
            weekday_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell_layout.addWidget(weekday_label)
            self._matrix_grid.addWidget(cell, 0, column)

        codes = {code: token for code, _, token in self.LEGEND}
        for row_index, (name, day_codes) in enumerate(rows, start=1):
            label = body_label(name, size=13, wrap=False)
            self._matrix_grid.addWidget(label, row_index, 0)

            for column, code in enumerate(day_codes, start=1):
                cell = plain_label(code)
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFixedSize(30, 28)
                token = codes.get(code, "--color-text-muted")
                # İstirahət günü fərqli fon alır — boş xana ilə "hələ
                # planlaşdırılmayıb" halını qarışdırmamaq üçün.
                background = (
                    self.theme.color("--color-neutral-bg")
                    if code
                    else self.theme.color("--color-skeleton-alt")
                )
                cell.setStyleSheet(
                    f"background-color: {background};"
                    f"color: {self.theme.color(token)};"
                    "border-radius: 6px; font-weight: 600;"
                )
                self._matrix_grid.addWidget(cell, row_index, column)
                self._cells[(name, column)] = cell

        self.show_content()

    def set_summary(self, items: list[tuple[str, str]]) -> None:
        clear_layout(self._summary_rows)

        for name, value in items:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(muted_label(name))
            layout.addWidget(stretch())
            layout.addWidget(title_label(value, size=15))
            self._summary_rows.addWidget(row)

    def set_open_shift_postings(self, rows: list[dict[str, str]]) -> None:
        """#16 — açıq elanlar. Açarlar: `id`, `date`, `work_mode`, `store`.

        Ekran yalnız ÖTÜRÜR: kartın öz `set_postings()`-i sətirləri qurur.
        Bu, matrisin kodu ilə bazarın kodunu qarışdırmamaq üçündür.
        """
        self._open_shift_card.set_postings(rows)

    def set_staffing_pattern(
        self,
        items: list[tuple[str, str]],
        *,
        store_name: str,
        based_on_weeks: int,
        calculated_label: str,
    ) -> None:
        """#13 — həftə günü üzrə tarixi kadr nümunəsi (məsləhət xarakterli).

        Args:
            items: (həftə günü adı, "2.6 nəfər") cütləri — SIRALAMA çağıranın
                məsuliyyətidir (`StaffingPatternUseCase.suggestions_for`
                B.e→Bazar sıralayır), çünki maket və canlı yol eyni ardıcıllığı
                göstərməlidir.
            store_name: Rəqəmlərin AİD OLDUĞU mağaza. Adsız göstərici 21
                filiallı şəbəkədə mənasızdır — admin hansı mağazanın nümunəsinə
                baxdığını bilməlidir.
            based_on_weeks: Pəncərənin uzunluğu (ROOT parametri).
            calculated_label: Sonuncu hesablamanın tarixi. YAŞ GÖSTƏRİLİR,
                çünki "8 həftəlik nümunə" yazısı hesablama 3 ay əvvəl
                aparılıbsa yanıldıcıdır (migrations/019 `calculated_at` şərhi).

        BOŞ SİYAHI GİZLƏTMİR: kart görünür və "tarixçə yoxdur" yazır. Kartı
        yox etmək istifadəçidə "bu funksiya işləmir" təəssüratı yaradardı,
        halbuki cavab "hələ kifayət qədər məlumat yığılmayıb"dır.
        """
        clear_layout(self._staffing_rows)

        header = muted_label(f"{store_name} · son {based_on_weeks} həftə · {calculated_label}")
        self._staffing_rows.addWidget(header)

        if not items:
            self._staffing_rows.addWidget(
                body_label("Bu mağaza üçün kifayət qədər tarixçə yoxdur.", size=13, wrap=True)
            )
            return

        for weekday, value in items:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(muted_label(weekday))
            layout.addWidget(stretch())
            layout.addWidget(body_label(value, size=13, wrap=False))
            self._staffing_rows.addWidget(row)


# --------------------------------------------------------------------------- #
# 13 — Gündəlik Mağaza Tabeli
# --------------------------------------------------------------------------- #


class DailyRosterScreen(Screen):
    """Avtomatik ön-doldurulmuş gündəlik tabel.

    Signals:
        approve_requested: "Tabeli Təsdiqlə".
        draft_saved: "Qaralama Saxla" (rəhbər qeydi ilə).
    """

    approve_requested = Signal()
    draft_saved = Signal(str)

    _STATUS_TONES: Final[dict[str, ChipTone]] = {
        "Təsdiqli": "success",
        "gecikib": "warning",
        "İcazədə": "info",
        "Plandan kənar giriş": "warning",
        "Gəlməyib": "danger",
    }

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        self._stats = QWidget()
        self._stats_layout = QHBoxLayout(self._stats)
        self._stats_layout.setContentsMargins(0, 0, 0, 0)
        self._stats_layout.setSpacing(12)
        self.add(self._stats)

        # Uyğunsuzluq xəbərdarlığı — HR planı ilə faktiki giriş uyuşmayanda.
        self._mismatch = Card(padding=16, spacing=8)
        self._mismatch_text = body_label("", size=13)
        self._mismatch.add(self._mismatch_text)
        self._mismatch.setVisible(False)
        self.add(self._mismatch)

        self._table = DataTable(
            [
                Column("İşçi", 220),
                Column("Plan", 110, mono=True),
                Column("Giriş", 110, mono=True),
                Column("Vəziyyət", 220),
                Column("Qeyd"),
            ],
            theme,
        )
        self.add(self._table)

        note_card = Card(padding=16, spacing=metrics.CARD_CONTENT_SPACING)
        self._note = QPlainTextEdit()
        self._note.setPlaceholderText("Rəhbər qeydi əlavə et…")
        self._note.setFixedHeight(80)
        note_card.add(self._note)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        draft = secondary_button("Qaralama Saxla")
        draft.clicked.connect(lambda: self.draft_saved.emit(self._note.toPlainText()))
        buttons_layout.addWidget(draft)

        approve = action_button("Tabeli Təsdiqlə")
        approve.clicked.connect(self.approve_requested)
        buttons_layout.addWidget(approve)
        note_card.add(buttons)
        self.add(note_card)

    def set_stats(self, stats: list[tuple[str, int]]) -> None:
        clear_layout(self._stats_layout)

        tones: dict[str, ChipTone] = {
            "Planlaşdırılıb": "neutral",
            "Təsdiqli giriş": "success",
            "Gecikən": "warning",
            "Gəlməyən": "danger",
        }
        for name, value in stats:
            self._stats_layout.addWidget(Chip(f"{name} {value}", tones.get(name, "neutral")))
        self._stats_layout.addStretch(1)

    def set_mismatch(self, message: str) -> None:
        """HR planı ilə uyğunsuzluğu göstərir; boş mətn onu gizlədir."""
        self._mismatch_text.setText(message)
        self._mismatch.setVisible(bool(message))

    def set_rows(self, rows: list[dict[str, str]]) -> None:
        self._table.clear()
        for row in rows:
            status = row.get("status", "")
            tone: ChipTone = "neutral"
            for key, value in self._STATUS_TONES.items():
                if key in status:
                    tone = value
                    break
            self._table.add_row(
                [
                    row.get("employee", ""),
                    mono_label(row.get("plan", "—")),
                    mono_label(row.get("check_in", "—")),
                    Chip(status, tone) if status else plain_label("—"),
                    muted_label(row.get("note", "—")),
                ]
            )
        self.show_content()

    def table(self) -> DataTable:
        return self._table

    def manager_note(self) -> str:
        """Rəhbər qeydinin CARİ mətni.

        `draft_saved` mətni siqnalla daşıyır, `approve_requested` isə
        parametrsizdir — imza anında qeydi oxumağın yolu yox idi. Siqnalın
        imzasını dəyişməkdənsə oxu metodu əlavə olundu: ekran onsuz da
        setter/getter API-si təqdim edir (CLAUDE.md bölmə 6) və siqnal
        imzası dəyişsəydi maket yolu da yenilənməli olardı."""
        return str(self._note.toPlainText())


# --------------------------------------------------------------------------- #
# 14 — Növbə Dəyişmə Sorğuları
# --------------------------------------------------------------------------- #


class ShiftSwapScreen(Screen):
    """Növbə dəyişmə inbox-u — siyahı + detal paneli.

    Signals:
        approved / rejected: `request_id`.
        selected: `request_id`.
    """

    approved = Signal(str)
    rejected = Signal(str)
    selected = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, padded=False, parent=parent)
        self._rows: list[Card] = []
        self._current: str | None = None
        #: `set_requests()`-in son sətirləri, `id` ilə — QA-FULL FAZA 3
        #: tapıntısı: `select()` bunsuz detal panelini doldura BİLMİRDİ,
        #: çünki `set_detail()`-i heç kim çağırmırdı (bax `select` şərhi).
        self._requests_by_id: dict[str, dict[str, str]] = {}

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ------------------------------ siyahı ------------------------------ #
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(
            metrics.CONTENT_PADDING_H,
            metrics.CONTENT_PADDING_V,
            metrics.CONTENT_PADDING_H,
            metrics.CONTENT_PADDING_V,
        )
        left_layout.setSpacing(12)

        self._filters = QWidget()
        filters_layout = QHBoxLayout(self._filters)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(8)
        self._filter_chips: dict[str, Chip] = {}
        for key, label in (
            ("pending", "Gözləyən"),
            ("approved", "Təsdiqlənən"),
            ("rejected", "Rədd edilən"),
        ):
            chip = Chip(label, "neutral")
            self._filter_chips[key] = chip
            filters_layout.addWidget(chip)
        filters_layout.addStretch(1)
        left_layout.addWidget(self._filters)

        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(12)
        list_holder = QWidget()
        list_holder.setLayout(self._list_layout)
        left_layout.addWidget(list_holder)
        left_layout.addStretch(1)
        layout.addWidget(left, 1)

        # ------------------------------ detal ------------------------------- #
        layout.addWidget(self._build_detail_panel())
        self.add(container)

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(metrics.DETAIL_PANEL_WIDTH)
        panel.setStyleSheet(
            f"background-color: {self.theme.color('--color-card-bg')};"
            f"border-left: 1px solid {self.theme.color('--color-card-border')};"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        from src.presentation.widgets.primitives import section_label  # noqa: PLC0415

        layout.addWidget(section_label("Sorğu detalı"))
        self._detail_title = title_label("", size=19)
        layout.addWidget(self._detail_title)

        self._detail_rows = QVBoxLayout()
        self._detail_rows.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._detail_rows)
        layout.addWidget(holder)

        layout.addStretch(1)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)

        reject = secondary_button("Rədd Et")
        reject.clicked.connect(self._emit_rejected)
        buttons_layout.addWidget(reject)

        approve = action_button("Təsdiqlə")
        approve.clicked.connect(self._emit_approved)
        buttons_layout.addWidget(approve)
        layout.addWidget(buttons)
        return panel

    def _emit_approved(self) -> None:
        if self._current is not None:
            self.approved.emit(self._current)

    def _emit_rejected(self) -> None:
        if self._current is not None:
            self.rejected.emit(self._current)

    def set_counts(self, counts: dict[str, int]) -> None:
        labels = {"pending": "Gözləyən", "approved": "Təsdiqlənən", "rejected": "Rədd edilən"}
        for key, chip in self._filter_chips.items():
            chip.setText(f"{labels[key]} · {counts.get(key, 0)}")

    def set_requests(self, requests: list[dict[str, str]]) -> None:
        clear_layout(self._list_layout)
        self._rows.clear()
        # SAHƏLƏR CANLI (`controllers/screen_data.py::_shift_swaps`) VƏ MAKET
        # (`preview_screens.py::_shift_swaps`) yolunda EYNİDİR (CLAUDE.md §6),
        # ona görə `select()` bu keşdən detal panelini TAM doldura bilir —
        # ayrıca sorğu APARMIR.
        self._requests_by_id = {request["id"]: request for request in requests}

        for request in requests:
            card = ClickableCard(request["id"], padding=16, spacing=8)

            head = QWidget()
            head_layout = QHBoxLayout(head)
            head_layout.setContentsMargins(0, 0, 0, 0)
            head_layout.setSpacing(12)
            head_layout.addWidget(
                title_label(f"{request['from_name']} → {request['to_name']}", size=15)
            )
            head_layout.addWidget(stretch())
            head_layout.addWidget(Chip(request.get("status", "Gözləyir"), "warning"))
            card.add(head)

            card.add(body_label(request.get("shift", ""), size=13))
            card.add(muted_label(request.get("store", "")))

            note = request.get("note", "")
            if note:
                card.add(muted_label(note))

            card.clicked.connect(self.select)
            self._list_layout.addWidget(card)
            self._rows.append(card)

        if requests:
            self.select(requests[0]["id"])
        self.show_content()

    def select(self, request_id: str) -> None:
        """Kartı seçir VƏ detal panelini DƏRHAL doldurur (QA-FULL FAZA 3 düzəlişi).

        ──────────────────────────────────────────────────────────────────────
        ƏVVƏL YALNIZ `_current`-i qururdu — TAPINTI
        ──────────────────────────────────────────────────────────────────────
        `set_detail()`-i canlı rejimdə heç bir kontroller çağırmırdı
        (`controllers/shift_swaps.py::attach()` `selected` siqnalına
        ÜMUMİYYƏTLƏ abunə deyildi) — «Sorğu detalı» paneli menecerin hər
        klikindən sonra HƏMİŞƏ boş qalırdı, halbuki «Təsdiqlə»/«Rədd Et»
        funksional işləyirdi. Detal BURADA, EKRANIN ÖZÜNDƏ qurulur (ayrıca
        kontroller keşi YOX): `set_requests()`-in qəbul etdiyi sətir onsuz da
        detal üçün lazım olan HƏR ŞEYİ daşıyır, ikinci sorğu göndərmək
        mənasız təkrar olardı.
        """
        self._current = request_id
        row = self._requests_by_id.get(request_id)
        if row is not None:
            self.set_detail(*_detail_for(row))
        self.selected.emit(request_id)

    def set_detail(self, title: str, rows: list[tuple[str, str]]) -> None:
        """Detal panelini doldurur."""
        self._detail_title.setText(title)
        clear_layout(self._detail_rows)

        for name, value in rows:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(4)
            box_layout.addWidget(muted_label(name))
            box_layout.addWidget(body_label(value, size=13))
            self._detail_rows.addWidget(box)

    @property
    def current_request(self) -> str | None:
        return self._current


def _detail_for(row: dict[str, str]) -> tuple[str, list[tuple[str, str]]]:
    """`set_requests()` sətri → `set_detail()`-in gözlədiyi (başlıq, sətirlər).

    Açarlar `controllers/screen_data.py::_shift_swaps` (canlı) və
    `preview_data.SWAP_REQUESTS` (maket) ilə EYNİDİR — `to_name`/`shift` canlı
    yolda EYNİ dəyərdir (hədəf işçi sorğuda YOXDUR, bax `_shift_swaps`
    şərhi), ona görə burada TƏKRARLANMIR.
    """
    from_name = row.get("from_name", "")
    date_text = row.get("shift") or row.get("to_name", "")
    title = f"{from_name} — {date_text}" if date_text else from_name
    rows = [
        ("Sorğunu göndərən", from_name),
        ("İstədiyi tarix", date_text),
        ("Mağaza", row.get("store", "")),
        ("Vəziyyət", row.get("status", "")),
    ]
    note = row.get("note", "")
    if note:
        rows.append(("Səbəb", note))
    return title, rows


__all__ = [
    "ChangeRoleDialog",
    "DailyRosterScreen",
    "DashboardScreen",
    "NewUserDialog",
    "PermissionMatrixScreen",
    "PosThresholdDialog",
    "RankingEntry",
    "ResetPasswordDialog",
    "ResetPinDialog",
    "RoleCreateDialog",
    "ShiftPlanningScreen",
    "ShiftSwapScreen",
    "UsersScreen",
]
