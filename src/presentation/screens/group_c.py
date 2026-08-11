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

from typing import TYPE_CHECKING, Final

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
from src.presentation.widgets.forms import FormField
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


class DashboardScreen(Screen):
    """Konfiqurasiya edilə bilən widget şəbəkəsi.

    Maketdəki düzülüş: üstdə dörd rəqəm kartı, altda qrafik + limit ölçəni,
    sonra liderlik lövhəsi + server sağlamlığı.
    """

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        # ------------------------------ rəqəmlər ---------------------------- #
        tiles = QWidget()
        tiles_layout = QHBoxLayout(tiles)
        tiles_layout.setContentsMargins(0, 0, 0, 0)
        tiles_layout.setSpacing(metrics.CARD_SPACING)

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

    # ------------------------------- doldurma -------------------------------- #

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
        groups: list[tuple[str, list[tuple[str, str, bool, bool]]]],
    ) -> None:
        """Matrisi qurur.

        Args:
            groups: (kateqoriya adı, [(flag, etiket, aktiv, hardlock)]).
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

            for index, (flag, label, enabled, hardlock) in enumerate(items):
                total_count += 1
                if enabled:
                    active_count += 1

                box = QCheckBox(label)
                box.setChecked(enabled)
                if hardlock:
                    box.setEnabled(False)
                    box.setIcon(icons.icon("lock", self.theme.color("--color-text-muted")))
                    box.setToolTip("Hardlock — yalnız ROOT İdarə Mərkəzindən dəyişdirilir")
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
    PRIORITIES: Final[tuple[tuple[str, int], ...]] = (
        ("Rəhbərlik (0)", 0),
        ("Admin (1)", 1),
        ("Operativ (2)", 2),
        ("Personal (3)", 3),
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
        # Defolt «Personal (3)»: ən aşağı pillə ən az risklidir və pilləni
        # sonradan qaldırmaq, səhvən yüksək verilmiş pilləni endirməkdən
        # asandır.
        self._priority.setCurrentIndex(len(self.PRIORITIES) - 1)
        card.add(FormField("Səlahiyyət pilləsi", widget=self._priority))

        self._camera = QCheckBox("Kamera-tipli rol")
        card.add(self._camera)
        card.add(
            muted_label(
                "Kamera-tipli rol cərimə yaza bilən rollar sinfindəndir və "
                "yalnız operativ (2) və ya daha yüksək pillədə yaradıla bilər.",
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
    ACTIONS: Final = (
        ("reset_pin", "PIN Sıfırla"),
        ("reset_password", "Şifrəni Yenilə"),
        ("change_role", "Rolu Dəyiş"),
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
                "Rolu Dəyiş, Deaktiv Et."
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


# --------------------------------------------------------------------------- #
# 12 — Növbə Planlama
# --------------------------------------------------------------------------- #


class ShiftPlanningScreen(Screen):
    """Aylıq növbə matrisi — işçi × gün.

    Signals:
        template_selected: İş rejimi şablonu ("5/2", "6/1", "2/2", "custom").
        publish_requested: "Planı Yayımla".
        month_changed: (-1 və ya +1).
    """

    template_selected = Signal(str)
    publish_requested = Signal()
    month_changed = Signal(int)

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
        return footer

    def set_month(self, label: str, *, stores: list[str], mode: str) -> None:
        self._month_label.setText(label)
        if stores and self._store_combo.count() == 0:
            self._store_combo.addItems(stores)
        self._mode_label.setText(f"İş Rejimi: {mode}")

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
    "RoleCreateDialog",
    "ShiftPlanningScreen",
    "ShiftSwapScreen",
    "UsersScreen",
]
