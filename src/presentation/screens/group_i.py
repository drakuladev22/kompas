"""Qrup İ — infrastruktur, dashboard qurucusu və plugin idarəetməsi — Faza 5/6.

    36  [İnfrastruktur Və Baza Ayarları]  (`can_switch_db`,      bölmə 2)
    37  Dashboard Qurucusu                (səlahiyyət tələb etmir, bölmə 6)
    38  Plugin İdarəetməsi                (`can_manage_plugins`, bölmə 1)

──────────────────────────────────────────────────────────────────────────────
BAZA KEÇİDİ EKRANI NİYƏ "SEHRBAZ" DEYİL
──────────────────────────────────────────────────────────────────────────────
ERP bağlantısı çox addımlı sehrbazdır, çünki orada İSTİFADƏÇİ məlumat daxil
edir. Baza keçidində isə istifadəçi yalnız BİR qərar verir ("hara?") — qalan
yeddi addımı sistem özü icra edir. Sehrbaz forması burada saxta seçim
təəssüratı yaradardı; əvəzinə tək təsdiq + gedişat siyahısı göstərilir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.value_objects.infrastructure import (
    ALL_PHASES,
    DatabaseTarget,
    MigrationPhase,
)
from src.presentation.screens.base import Screen, section_header
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, icon_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    body_label,
    muted_label,
    stretch,
    title_label,
)
from src.presentation.widgets.toggle import ToggleSwitch

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


# --------------------------------------------------------------------------- #
# 36 — İnfrastruktur Və Baza Ayarları
# --------------------------------------------------------------------------- #


class PhaseRow(QWidget):
    """Keçidin bir addımı — gözləyir / icra olunur / tamamlandı / uğursuz."""

    STATES: Final = ("pending", "running", "done", "failed")

    def __init__(
        self, phase: MigrationPhase, theme: ThemeManager, *, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._phase = phase

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)

        self._marker = QLabel()
        self._marker.setFixedSize(22, 22)
        self._marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._marker)

        label = body_label(f"{phase.order + 1}. {phase.label_az}")
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        self._chip = Chip("Gözləyir", "neutral")
        layout.addWidget(self._chip)

        self.set_state("pending")

    def set_state(self, state: str) -> None:
        """Vəziyyəti dəyişir.

        Nişan HƏM ikon, HƏM mətnlə verilir — yalnız rəngə güvənmək rəng
        ayırd edə bilməyən istifadəçi üçün məlumatı itirərdi (bölmə 9).
        """
        icon_name, token, chip_text, tone = {
            "pending": ("clock", "--color-text-muted", "Gözləyir", "neutral"),
            "running": ("refresh", "--color-info", "İcra olunur", "info"),
            "done": ("check_circle", "--color-success", "Tamamlandı", "success"),
            "failed": ("close", "--color-danger", "Uğursuz", "danger"),
        }[state]

        self._marker.setPixmap(
            icons.render(icon_name, self._theme.color(token), size=14, stroke_width=1.8)
        )
        self._chip.setText(chip_text)
        self._chip.set_tone(tone)  # type: ignore[arg-type]


class InfrastructureScreen(Screen):
    """Cloud ↔ Şəxsi Server keçidi + texniki fasilə gedişatı (bölmə 2).

    Signals:
        switch_requested: Hədəf baza (`CLOUD` / `PRIVATE_SERVER`).
        history_requested: Jurnalın yenilənməsi.
    """

    switch_requested = Signal(str)
    history_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._phase_rows: dict[MigrationPhase, PhaseRow] = {}
        self._active = DatabaseTarget.CLOUD

        self.add(
            section_header(
                "İnfrastruktur Və Baza Ayarları",
                "Keçid yalnız texniki fasilə rejimində icra olunur.",
            )
        )

        # ------------------------------ aktiv baza --------------------------- #
        target_card = Card()
        body = target_card.body()

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        row_layout.addWidget(muted_label("Aktiv baza"))
        self._active_label = title_label("", size=15)
        row_layout.addWidget(self._active_label)
        row_layout.addWidget(stretch())

        self._switch_button = action_button(
            "Digər bazaya keç",
            icon_name="database",
            icon_color=theme.color("--color-action-text"),
        )
        self._switch_button.clicked.connect(
            lambda: self.switch_requested.emit(self._active.opposite().value)
        )
        row_layout.addWidget(self._switch_button)
        body.addWidget(row)

        self._warning_label = muted_label("")
        self._warning_label.setWordWrap(True)
        body.addWidget(self._warning_label)
        self.add(target_card)

        # ------------------------------ gedişat ------------------------------ #
        phases_card = Card()
        phases_body = phases_card.body()
        phases_body.addWidget(title_label("Keçid addımları", size=14))
        phases_body.addWidget(Divider())
        for phase in ALL_PHASES:
            widget = PhaseRow(phase, theme)
            self._phase_rows[phase] = widget
            phases_body.addWidget(widget)
        self.add(phases_card)

        # ------------------------------ jurnal ------------------------------- #
        self._history_host = QWidget()
        self._history_layout = QVBoxLayout(self._history_host)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.setSpacing(0)
        self.add(self._history_host)

        self.set_active_target(DatabaseTarget.CLOUD)

    # -------------------------------- API ------------------------------------ #

    def set_active_target(self, target: DatabaseTarget) -> None:
        self._active = target
        self._active_label.setText(target.label_az)
        self._switch_button.setText(f"{target.opposite().label_az}-ə keç")

    def set_warnings(self, warnings: list[str]) -> None:
        """Ön yoxlama xəbərdarlıqları — boşdursa "hazırdır" yazılır.

        Boş sətir buraxmaq istifadəçidə "yoxlama aparılmadı?" sualı yaradardı.
        """
        self._warning_label.setText(
            "\n".join(f"• {text}" for text in warnings)
            if warnings
            else "Ön yoxlama təmizdir — sinxronlaşmamış yazı yoxdur."
        )

    def set_phase_state(self, phase: MigrationPhase, state: str) -> None:
        self._phase_rows[phase].set_state(state)

    def reset_phases(self) -> None:
        for widget in self._phase_rows.values():
            widget.set_state("pending")

    def set_history(self, rows: list[dict[str, str]]) -> None:
        """Keçid tarixçəsi (`db_migration_events`)."""
        clear_layout(self._history_layout)
        if not rows:
            self._history_layout.addWidget(muted_label("Hələ heç bir baza keçidi olmayıb."))
            self.show_content()
            return

        table = DataTable(
            [
                Column("Tarix", 160, mono=True),
                Column("İstiqamət"),
                # Barmaq izi bir HASH-dır — maketin identifikator qaydası.
                Column("Barmaq izi", 170, mono=True),
                Column("Nəticə", 150),
            ],
            self.theme,
            footnote="Hər keçid `db_migration_events` cədvəlinə yazılır və silinmir.",
        )
        for entry in rows:
            table.add_row(
                [
                    entry.get("date", ""),
                    entry.get("direction", ""),
                    entry.get("checksum", ""),
                    Chip(entry.get("status", ""), entry.get("tone", "neutral")),  # type: ignore[arg-type]
                ]
            )
        self._history_layout.addWidget(table)
        self.show_content()


# --------------------------------------------------------------------------- #
# 37 — Dashboard Qurucusu
# --------------------------------------------------------------------------- #


class WidgetRow(QWidget):
    """Dashboard qurucusunda bir widget sətri — göstər/gizlət + sıralama.

    Signals:
        toggled: `(widget_key, görünürmü)`.
        moved: `(widget_key, istiqamət)` — `-1` yuxarı, `+1` aşağı.
    """

    toggled = Signal(str, bool)
    moved = Signal(str, int)

    def __init__(
        self,
        key: str,
        title: str,
        description: str,
        *,
        visible: bool,
        theme: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(12)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(title_label(title, size=14))
        caption = muted_label(description)
        caption.setWordWrap(True)
        text_layout.addWidget(caption)
        layout.addWidget(text_box, 1)

        icon_color = theme.color("--color-text-secondary")
        up = icon_button("arrow_up", icon_color, tooltip="Yuxarı")
        up.clicked.connect(lambda: self.moved.emit(self.key, -1))
        layout.addWidget(up)

        down = icon_button("arrow_down", icon_color, tooltip="Aşağı")
        down.clicked.connect(lambda: self.moved.emit(self.key, 1))
        layout.addWidget(down)

        # Vəziyyət KONSTRUKTORDA verilir, `setChecked()` ilə yox: sonuncu
        # animasiya başladır və hadisə dövrü işləməyənə qədər açar hələ də
        # köhnə vəziyyəti çəkir (ekran ilk dəfə boyananda yanlış görünürdü).
        self._toggle = ToggleSwitch(theme, checked=visible)
        self._toggle.toggled.connect(lambda state: self.toggled.emit(self.key, state))
        layout.addWidget(self._toggle)

    def set_visible_state(self, visible: bool) -> None:
        self._toggle.setChecked(visible)


class DashboardBuilderScreen(Screen):
    """Dashboard-un konfiqurasiya ekranı (bölmə 6).

    Signals:
        layout_changed: Yeni düzülüş (görünən widget açarları, SIRA ilə).
        reset_requested: Defolt düzülüşə qayıt.
    """

    layout_changed = Signal(list)
    reset_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._rows: list[WidgetRow] = []
        self._order: list[str] = []
        self._visible: set[str] = set()
        self._catalog: dict[str, tuple[str, str]] = {}

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(
            section_header(
                "Dashboard Qurucusu",
                "Hansı bölmələrin görünəcəyini və sırasını təyin edin.",
            ),
            1,
        )
        reset = secondary_button("Defolta qaytar")
        reset.clicked.connect(self.reset_requested)
        header_layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignTop)
        self.add(header)

        self._card = Card()
        self._list_layout = self._card.body()
        self.add(self._card)

        self._summary = muted_label("")
        self._summary.setWordWrap(True)
        self.add(self._summary)

        # Artıq hündürlük SONA — onsuz Qt boşluğu başlıq ilə kart arasında
        # bölüşdürür və izahsız aralıq yaranır (bax `group_h` eyni düzəliş).
        self.body().addStretch(1)

    def set_widgets(
        self, catalog: dict[str, tuple[str, str]], *, order: list[str], visible: set[str]
    ) -> None:
        """Kataloqu və cari düzülüşü göstərir.

        Args:
            catalog: `açar → (başlıq, izah)`.
            order: Göstərilmə sırası (kataloqda olmayan açarlar buraxılır).
            visible: Görünən açarlar.
        """
        self._catalog = catalog
        self._order = [key for key in order if key in catalog]
        # Kataloqda olub sırada olmayan widget SONA əlavə olunur: yeni
        # modul əlavə edildikdə istifadəçinin köhnə düzülüşü onu gizlətməməli,
        # sadəcə sonuncu yerə qoymalıdır.
        self._order += [key for key in catalog if key not in self._order]
        self._visible = {key for key in visible if key in catalog}
        self._render()

    def _render(self) -> None:
        clear_layout(self._list_layout)
        self._rows = []

        for index, key in enumerate(self._order):
            title, description = self._catalog[key]
            row = WidgetRow(
                key,
                title,
                description,
                visible=key in self._visible,
                theme=self.theme,
            )
            row.toggled.connect(self._on_toggled)
            row.moved.connect(self._on_moved)
            self._rows.append(row)
            self._list_layout.addWidget(row)
            if index < len(self._order) - 1:
                self._list_layout.addWidget(Divider())

        self._summary.setText(
            f"{len(self._visible)}/{len(self._order)} bölmə göstərilir. "
            f"Dəyişiklik dərhal yadda saxlanılır."
        )
        self.show_content()

    def _on_toggled(self, key: str, visible: bool) -> None:
        if visible:
            self._visible.add(key)
        else:
            self._visible.discard(key)
        self._emit()
        self._summary.setText(
            f"{len(self._visible)}/{len(self._order)} bölmə göstərilir. "
            f"Dəyişiklik dərhal yadda saxlanılır."
        )

    def _on_moved(self, key: str, direction: int) -> None:
        """Sətri bir addım yuxarı/aşağı sürüşdürür.

        Sərhəddən kənara çıxma SƏSSİZCƏ nəzərə alınmır — ilk sətirdə "yuxarı"
        basmaq xəta deyil, sadəcə effektsizdir.
        """
        if key not in self._order:
            return
        index = self._order.index(key)
        target = index + direction
        if not 0 <= target < len(self._order):
            return
        self._order[index], self._order[target] = self._order[target], self._order[index]
        self._render()
        self._emit()

    def _emit(self) -> None:
        self.layout_changed.emit([key for key in self._order if key in self._visible])

    def current_layout(self) -> list[str]:
        """Görünən widget-lər — SIRA ilə."""
        return [key for key in self._order if key in self._visible]


# --------------------------------------------------------------------------- #
# 38 — Plugin İdarəetməsi
# --------------------------------------------------------------------------- #


class PluginScreen(Screen):
    """Quraşdırılmış plugin-lərin siyahısı (bölmə 1, `can_manage_plugins`).

    Signals:
        install_requested: "Plugin Quraşdır".
        toggle_requested: `(plugin_id, aktivləşdirilsinmi)`.
        remove_requested: `plugin_id`.
    """

    install_requested = Signal()
    toggle_requested = Signal(str, bool)
    remove_requested = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())
        install = action_button(
            "Plugin Quraşdır",
            icon_name="plus",
            icon_color=theme.color("--color-action-text"),
        )
        install.clicked.connect(self.install_requested)
        toolbar_layout.addWidget(install)
        self.add(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        self._list_layout = QVBoxLayout(host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(metrics.CARD_SPACING)
        self._list_layout.addStretch(1)
        scroll.setWidget(host)
        self.add(scroll)

    def set_plugins(self, plugins: list[dict[str, str]]) -> None:
        """Plugin siyahısını göstərir.

        Args:
            plugins: `id`, `name`, `version`, `publisher`, `enabled` (`"1"`/`"0"`),
                `signature` (`valid` / `invalid` / `unsigned`).
        """
        clear_layout(self._list_layout, keep_last=1)

        if not plugins:
            self.show_empty(
                title="Plugin quraşdırılmayıb",
                body=(
                    "Plugin-lər ayrıca prosesdə, məhdud API səthi ilə işləyir və "
                    "yalnız imzalanmış paketlər qəbul edilir."
                ),
            )
            return

        enabled = sum(1 for plugin in plugins if plugin.get("enabled") == "1")
        self._summary.setText(f"{len(plugins)} plugin — {enabled} aktiv")

        for plugin in plugins:
            self._list_layout.insertWidget(self._list_layout.count() - 1, self._build_card(plugin))
        self.show_content()

    def _build_card(self, plugin: dict[str, str]) -> QWidget:
        card = Card()
        body = card.body()

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)
        head_layout.addWidget(title_label(plugin.get("name", ""), size=15))
        head_layout.addWidget(Chip(f"v{plugin.get('version', '?')}", "neutral"))

        # İMZA VƏZİYYƏTİ ƏN GÖRÜNƏN NİŞANDIR: imzasız plugin ayrıca prosesdə
        # işləsə belə, mənbəyi naməlumdur — istifadəçi bunu quraşdırma
        # qərarından ƏVVƏL görməlidir (bölmə 1, sandbox qaydası).
        signature = plugin.get("signature", "unsigned")
        head_layout.addWidget(
            Chip(
                {
                    "valid": "İmza doğrulandı",
                    "invalid": "İMZA YANLIŞDIR",
                    "unsigned": "İMZASIZ",
                }.get(signature, "İMZASIZ"),
                "success" if signature == "valid" else "danger",
            )
        )
        head_layout.addWidget(stretch())

        enabled = plugin.get("enabled") == "1"
        toggle = ToggleSwitch(self.theme, checked=enabled)
        plugin_id = plugin.get("id", "")
        toggle.toggled.connect(lambda state, pid=plugin_id: self.toggle_requested.emit(pid, state))
        head_layout.addWidget(toggle)
        body.addWidget(head)

        publisher = muted_label(f"Naşir: {plugin.get('publisher', 'naməlum')}")
        publisher.setWordWrap(True)
        body.addWidget(publisher)
        body.addWidget(Divider())

        remove = secondary_button("Sil")
        remove.clicked.connect(lambda *_, pid=plugin_id: self.remove_requested.emit(pid))
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addWidget(stretch())
        footer_layout.addWidget(remove)
        body.addWidget(footer)
        return card


__all__ = [
    "DashboardBuilderScreen",
    "InfrastructureScreen",
    "PhaseRow",
    "PluginScreen",
    "WidgetRow",
]
