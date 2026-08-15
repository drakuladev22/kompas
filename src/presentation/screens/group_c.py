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
from src.presentation.widgets.layout_utils import clear_layout
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

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from src.presentation.theme.manager import ThemeManager


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
        for tile in (self._in_store, self._pending, self._fines, self._tasks):
            tile.setFixedHeight(metrics.DASHBOARD_ROW_HEIGHT)
            tiles_layout.addWidget(tile, 1)
        self.add(tiles)

        # --------------------------- qrafik + limit ------------------------- #
        middle = QWidget()
        middle_layout = QHBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(metrics.CARD_SPACING)
        self.responsive_row(middle_layout)

        chart_card = Card(padding=20, spacing=16)
        chart_head = QWidget()
        chart_head_layout = QHBoxLayout(chart_head)
        chart_head_layout.setContentsMargins(0, 0, 0, 0)
        chart_head_layout.setSpacing(10)
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

        # ------------------------ liderlər + serverlər ---------------------- #
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(metrics.CARD_SPACING)
        self.responsive_row(bottom_layout)

        self._leaders = RankList("Xal liderləri")
        bottom_layout.addWidget(self._leaders, 1)

        self._health = Card(padding=18, spacing=12)
        self._health.add(title_label("Server sağlamlığı", size=14))
        self._health_rows = QVBoxLayout()
        self._health_rows.setSpacing(10)
        health_holder = QWidget()
        health_holder.setLayout(self._health_rows)
        self._health.add(health_holder)
        self._health.body().addStretch(1)
        bottom_layout.addWidget(self._health, 1)
        self.add(bottom)

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

    def _build_ranking_card(self) -> Card:
        card = Card(padding=18, spacing=12)
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)
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
        card = Card(padding=18, spacing=12)
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
        card = Card(padding=18, spacing=12)
        title = title_label("Zaman-üzrə Trend", size=15)
        card.add(title)
        chart = BarChart(theme)
        card.add(chart)
        card.setVisible(False)
        return card, title, chart

    def _build_outlier_card(self) -> tuple[Card, QLabel, QVBoxLayout]:
        card = Card(padding=18, spacing=10)
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
        card = Card(padding=18, spacing=10)
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
            layout.setSpacing(10)
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
            layout.setSpacing(10)
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
            layout.setSpacing(10)
            layout.addWidget(body_label(name, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(Chip(detail, "warning"))
            self._outlier_rows.addWidget(row)
        self._outlier_card.setVisible(True)
        self.show_content()


# --------------------------------------------------------------------------- #
# 10 — İcazə Matrisi
# --------------------------------------------------------------------------- #


class PermissionMatrixScreen(Screen):
    """Discord-tərzi icazə matrisi: solda vəzifələr, sağda kateqoriyalı grid.

    Signals:
        role_selected: Vəzifə açarı.
        saved: (vəzifə açarı, {flag: aktiv}).
        role_create_requested: "Yeni Vəzifə".

    ──────────────────────────────────────────────────────────────────────
    HARDLOCK QIFILLARI NİYƏ GÖRÜNÜR AMMA BASILA BİLMİR
    ──────────────────────────────────────────────────────────────────────
    Adətən bu layihədə "icazən yoxdursa, element ÜMUMİYYƏTLƏ yoxdur"
    prinsipi işləyir (bax `navigation.py`). Burada isə ƏKSİNƏ: hardlock
    icazələr qıfıl ikonu ilə GÖRÜNÜR.

    Səbəb fərqlidir — bu, "sənin görməyə icazən yoxdur" deyil, "bu icazə
    heç kim tərəfindən dəyişdirilə bilməz" deməkdir. Onu gizlətsək, admin
    həmin icazənin ümumiyyətlə mövcud olmadığını düşünər və nə üçün
    işlədiyini başa düşməzdi. Maket də bunu izah edir: "Qıfıllı icazələr
    hardlock-dur — yalnız ROOT İdarə Mərkəzindən dəyişdirilir."

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
        layout.setSpacing(10)

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

        self._matrix_title = title_label("", size=17)
        head_layout.addWidget(self._matrix_title)
        self._matrix_count = muted_label("")
        head_layout.addWidget(self._matrix_count)
        head_layout.addWidget(stretch())

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
        self._groups_layout.setSpacing(18)
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
        card = Card(padding=16, spacing=10)
        card.add(title_label("Fərdi İstisna", size=14))
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
            groups: (kateqoriya adı, [(flag, etiket, aktiv, hardlock, aktorda_var)]).

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
            card = Card(padding=18, spacing=12)
            card.add(title_label(group_name, size=14))
            card.add(Divider())

            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(10)

            for index, (flag, label, enabled, hardlock, actor_owns) in enumerate(items):
                total_count += 1
                if enabled:
                    active_count += 1

                box = QCheckBox(label)
                box.setChecked(enabled)
                if hardlock:
                    box.setEnabled(False)
                    box.setIcon(icons.icon("lock", self.theme.color("--color-text-muted")))
                    box.setToolTip("Hardlock — yalnız ROOT İdarə Mərkəzindən dəyişdirilir")
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

    Signals:
        submitted: (ad, prioritet dəyəri, kamera-tipli).
    """

    submitted = Signal(str, int, bool)

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
        self.setMinimumWidth(470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=26, spacing=18)
        layout.addWidget(card)
        card.add(title_label("Yeni Vəzifə", size=19))
        card.add(Divider())

        self._name = FormField(
            "Vəzifə adı",
            placeholder="Məsələn: Anbar Nəzarətçisi",
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

        # Fokus sırası vizual sıra ilə: ad → pillə → kamera-tipi → düymələr.
        QWidget.setTabOrder(self._name.input_widget(), self._priority)
        QWidget.setTabOrder(self._priority, self._camera)
        QWidget.setTabOrder(self._camera, cancel)
        QWidget.setTabOrder(cancel, create)

        self._name.focus_input()

    def _on_submit(self) -> None:
        name = self._name.text().strip()
        self._name.clear_error()
        if not name:
            self._name.set_error("Vəzifə adı məcburidir")
            return
        self.submitted.emit(name, int(self._priority.currentData()), self._camera.isChecked())
        self.accept()


# --------------------------------------------------------------------------- #
# 11 — İstifadəçi və Rol İdarəetməsi
# --------------------------------------------------------------------------- #


class UsersScreen(Screen):
    """İşçi cədvəli — axtarış, yeni işçi, sətir əməliyyatları.

    Signals:
        create_requested: "Yeni İşçi".
        action_requested: (əməliyyat açarı, istifadəçi adı).
        search_changed: Axtarış mətni.
    """

    create_requested = Signal()
    action_requested = Signal(str, str)
    search_changed = Signal(str)

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
        self._search.textChanged.connect(self.search_changed)
        toolbar_layout.addWidget(self._search)
        toolbar_layout.addWidget(stretch())

        create = action_button(
            "Yeni İşçi",
            icon_name="plus",
            icon_color=theme.color("--color-action-text"),
        )
        create.clicked.connect(self.create_requested)
        toolbar_layout.addWidget(create)
        self.add(toolbar)

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

    def set_users(self, users: list[dict[str, str]]) -> None:
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
            identity_layout.setSpacing(2)
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
            menu.addAction(
                label,
                lambda k=key, name=full_name: self.action_requested.emit(k, name),
            )
        button.setMenu(menu)
        return button

    def table(self) -> DataTable:
        return self._table


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
        self.setMinimumWidth(470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=26, spacing=18)
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
            placeholder="məsələn 15",
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
        note_layout.setSpacing(7)
        note_layout.addWidget(field_label("Qeyd (səbəb)"))
        self._note = QPlainTextEdit()
        self._note.setPlainText(note)
        self._note.setPlaceholderText(
            "Bu səlahiyyət niyə verilir? Səbəbsiz hədd mübahisədə müdafiə olunmur."
        )
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


class EmployeeDocumentDialog(QDialog):
    """ "Sənədlər" modalı — işçinin sənəd/müqavilə siyahısı + yeni sənəd forması.

    #17 (kompasos11.md Faza 7). `PosThresholdDialog` ilə EYNİ naxış: `UsersScreen`-in
    "···" menyusundakı "Sənədlər" bəndi ilə açılır, mövcud ekran SİLİNMİR.

    TARİX SAHƏSİ NİYƏ `FormField` (sadə mətn), `QDateEdit` DEYİL: `open_shift.py`
    başlığındakı EYNİ səbəb — `qss.py`-də `QDateEdit` üçün kontrast-yoxlanılmış
    rəng cütü YOXDUR, onu əlavə etmək `scripts/check_contrast.py`-a yeni cüt
    gətirərdi. `FormField`-in `QLineEdit[variant="form"]` cütü ARTIQ yoxlanılıb.

    Signals:
        document_added: (sənəd növü, nömrə, bitmə tarixi mətni, bloklayıcı,
            seçilmiş faylın YEREL yolu — boş sətir ola bilər, fayl SEÇİLMƏSƏ
            belə qeyd yaradılmalıdır, bax `_file_path` başlığı).
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

        card = Card(padding=26, spacing=18)
        layout.addWidget(card)
        card.add(title_label("Sənədlər", size=19))
        card.add(muted_label(employee_name))
        card.add(Divider())

        self._table = DataTable(
            [
                Column("Növ", 150),
                Column("Nömrə", 110),
                Column("Bitmə tarixi", 120),
                Column("Bloklayıcı", 100),
                Column("Vəziyyət", 100),
                Column("Əməliyyat"),
            ],
            theme,
            footnote=(
                "Bloklayıcı sənəd bitibsə Növbə Matrisində təyinat zamanı "
                "xəbərdarlıq göstərilir — təyinat BLOKLANMIR."
            ),
        )
        self.set_documents(documents)
        card.add(self._table)

        card.add(Divider())
        card.add(body_label("Yeni sənəd əlavə et", size=14))

        self._doc_type = FormField("Sənəd növü", placeholder="məsələn MUQAVILE, SANITAR_KITABCA")
        card.add(self._doc_type)

        self._doc_number = FormField("Sənəd nömrəsi (könüllü)")
        card.add(self._doc_number)

        self._expiry = FormField(
            "Bitmə tarixi",
            placeholder="YYYY-AA-GG",
            hint="Boş buraxılsa sənəd müddətsiz sayılır.",
        )
        card.add(self._expiry)

        self._blocking = QCheckBox(
            "Bu sənəd bitəndə növbə təyinatında xəbərdarlıq göstərilsin (bloklayıcı)"
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
        file_row_layout.setSpacing(10)
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
        template_selected: İş rejimi şablonu ("5/2", "6/1", "2/2", "custom").
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

    template_selected = Signal(str)
    publish_requested = Signal()
    month_changed = Signal(int)
    open_shift_post_requested = Signal()
    open_shift_cancel_requested = Signal(str)
    work_mode_selected = Signal(str)

    #: Növbə kodları (maketdəki izah sətri).
    LEGEND: Final = (
        ("S", "Səhər 09:00–18:00", "--color-info"),
        ("A", "Axşam 13:00–22:00", "--color-warning"),
        ("", "İstirahət günü", "--color-neutral-bg"),
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

        self._month_label = title_label("", size=16)
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

        publish = action_button("Planı Yayımla")
        publish.clicked.connect(self.publish_requested)
        layout.addWidget(publish)
        return bar

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.CARD_SPACING)

        legend = Card(padding=16, spacing=10)
        legend.add(title_label("Növbə kodları", size=14))
        for code, description, token in self.LEGEND:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
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

        templates = Card(padding=16, spacing=10)
        templates.add(title_label("İş Rejimi Şablonları", size=14))
        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)
        for template in self.TEMPLATES:
            button = secondary_button(template)
            button.clicked.connect(lambda _=False, t=template: self.template_selected.emit(t))
            buttons_layout.addWidget(button)
        buttons_layout.addStretch(1)
        templates.add(buttons)
        templates.add(
            muted_label(
                "Şablon seçildikdə boş xanalar avtomatik doldurulur, əl ilə "
                "edilmiş dəyişikliklər saxlanılır."
            )
        )
        layout.addWidget(templates, 1)

        self._summary = Card(padding=16, spacing=10)
        self._summary.add(title_label("Ayın xülasəsi", size=14))
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
        self._staffing_card = Card(padding=16, spacing=10)
        self._staffing_card.add(title_label("Tarixi nümunə (məsləhət)", size=14))
        self._staffing_rows = QVBoxLayout()
        self._staffing_rows.setSpacing(6)
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
        self._month_label.setText(label)
        if stores and self._store_combo.count() == 0:
            self._store_combo.addItems(stores)
        self._mode_label.setText(f"İş Rejimi: {mode}")

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
            weekday_label = muted_label(weekday, size=10)
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
        self._stats_layout.setSpacing(10)
        self.add(self._stats)

        # Uyğunsuzluq xəbərdarlığı — HR planı ilə faktiki giriş uyuşmayanda.
        self._mismatch = Card(padding=14, spacing=8)
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

        note_card = Card(padding=16, spacing=12)
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
        self._detail_title = title_label("", size=18)
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
        buttons_layout.setSpacing(10)

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

        for request in requests:
            card = ClickableCard(request["id"], padding=16, spacing=8)

            head = QWidget()
            head_layout = QHBoxLayout(head)
            head_layout.setContentsMargins(0, 0, 0, 0)
            head_layout.setSpacing(10)
            head_layout.addWidget(
                title_label(f"{request['from_name']} → {request['to_name']}", size=14)
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
        self._current = request_id
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


__all__ = [
    "DailyRosterScreen",
    "DashboardScreen",
    "PermissionMatrixScreen",
    "PosThresholdDialog",
    "RankingEntry",
    "RoleCreateDialog",
    "ShiftPlanningScreen",
    "ShiftSwapScreen",
    "UsersScreen",
]
