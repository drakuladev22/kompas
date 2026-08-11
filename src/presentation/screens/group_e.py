"""Qrup E — dəstək və developer — Faza 4.2.

Maket: "KompasOS - Qrup E.dc.html", ekranlar 21–23.

    21  Diskret Dəstək Chat Widget-i
    22  Developer (Master) Panel
    23  LICENSE_INACTIVE ekranı
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    ChipTone,
    Divider,
    StatusDot,
    body_label,
    mono_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)
from src.presentation.widgets.states import StateIconBox

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


# --------------------------------------------------------------------------- #
# 21 — Dəstək Chat Widget-i
# --------------------------------------------------------------------------- #


class ChatBubble(QWidget):
    """Bir mesaj balonu.

    Maketdə gələn mesaj sol tərəfdə neytral fonda (`radius 12 12 12 4`),
    göndərilən mesaj sağda amber fonda (`radius 12 12 4 12`) göstərilir —
    yəni "quyruq" küncü mənbəyi bildirir. Rəngdən ƏLAVƏ olaraq mövqe də
    fərqləndirici olduğu üçün, rəng görməyən istifadəçi də kimin yazdığını
    ayırd edir.
    """

    def __init__(
        self,
        text: str,
        theme: ThemeManager,
        *,
        outgoing: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bubble = plain_label(text)
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(250)
        font = bubble.font()
        font.setPixelSize(13)
        bubble.setFont(font)

        if outgoing:
            background = theme.color("--color-brand-amber")
            foreground = theme.color("--color-brand-navy")
            radius = "12px 12px 4px 12px"
            border = "none"
        else:
            background = theme.color("--color-neutral-bg")
            foreground = theme.color("--color-text-primary")
            radius = "12px 12px 12px 4px"
            border = f"1px solid {theme.color('--color-card-border')}"

        bubble.setStyleSheet(
            f"background-color: {background}; color: {foreground};"
            f"border-radius: {radius}; border: {border}; padding: 12px 14px;"
        )

        if outgoing:
            layout.addStretch(1)
            layout.addWidget(bubble)
        else:
            layout.addWidget(bubble)
            layout.addStretch(1)


class SupportChatWidget(QWidget):
    """Sağ-alt küncdə üzən dəstək paneli.

    Signals:
        message_sent: Yazılan mesaj.
        opened / closed: Panel vəziyyəti.

    Widget örtüyün ÜSTÜNDƏ üzür (layout-da yer tutmur) — ona görə valideyn
    ölçüsü dəyişəndə `reposition()` çağırılmalıdır.
    """

    message_sent = Signal(str)
    opened = Signal()
    closed = Signal()

    #: Kənarlardan məsafə (maketdə `right: 28px; bottom: 28px`).
    MARGIN: Final = 28

    def __init__(
        self,
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._is_open = False

        self._panel = self._build_panel()
        self._panel.setParent(self)
        self._panel.setVisible(False)

        self._fab = QPushButton(self)
        self._fab.setFixedSize(metrics.SUPPORT_FAB_SIZE, metrics.SUPPORT_FAB_SIZE)
        self._fab.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fab.setIcon(
            icons.icon("chat", theme.color("--color-action-text"), size=24, stroke_width=1.4)
        )
        self._fab.setIconSize(QSize(24, 24))
        self._fab.setStyleSheet(
            f"background-color: {theme.color('--color-action-bg')};"
            f"border: none; border-radius: {metrics.SUPPORT_FAB_SIZE // 2}px;"
        )
        self._fab.clicked.connect(self.toggle)

        # Oxunmamış cavab nişanı — FAB-ın küncündən daşır.
        self._dot = plain_label(parent=self)
        self._dot.setFixedSize(12, 12)
        self._dot.setStyleSheet(
            f"background-color: {theme.color('--color-brand-amber')};"
            f"border: 2px solid {theme.color('--color-content-bg')};"
            "border-radius: 6px;"
        )
        self._dot.setVisible(False)

        self.setFixedSize(
            metrics.SUPPORT_PANEL_WIDTH,
            metrics.SUPPORT_PANEL_HEIGHT + metrics.SUPPORT_FAB_SIZE + 12,
        )
        self._layout_children()

    def _build_panel(self) -> Card:
        # Maketdə üzən dəstək paneli `border-radius: 14px` — iri səth pilləsi.
        panel = Card(padding=0, spacing=0, surface="modal", shadow=True)
        panel.setFixedSize(metrics.SUPPORT_PANEL_WIDTH, metrics.SUPPORT_PANEL_HEIGHT)

        # ------------------------------ başlıq ------------------------------ #
        header = QWidget()
        header.setFixedHeight(58)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 0, 18, 0)
        header_layout.setSpacing(12)

        avatar = plain_label()
        avatar.setFixedSize(34, 34)
        avatar.setPixmap(
            icons.render(
                "chat",
                self._theme.color("--color-brand-amber"),
                size=17,
                stroke_width=1.4,
            )
        )
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background-color: {self._theme.color('--color-neutral-bg')};"
            f"border: 1px solid {self._theme.color('--color-card-border')};"
            "border-radius: 17px;"
        )
        header_layout.addWidget(avatar)

        identity = QWidget()
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(2)
        identity_layout.addWidget(title_label("KompasOS Dəstək", size=14))
        status = muted_label("Onlayn · adətən 10 dəq içində")
        status.setStyleSheet(f"color: {self._theme.color('--color-success')};")
        identity_layout.addWidget(status)
        header_layout.addWidget(identity)
        header_layout.addWidget(stretch())

        close = QPushButton("×")
        close.setProperty("variant", "window")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.close_panel)
        header_layout.addWidget(close)

        panel.add(header)
        panel.add(Divider())

        # ------------------------------ mesajlar ---------------------------- #
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._messages_host = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_host)
        self._messages_layout.setContentsMargins(18, 18, 18, 18)
        self._messages_layout.setSpacing(14)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._messages_host)
        panel.body().addWidget(self._scroll, 1)

        panel.add(Divider())

        # ------------------------------- giriş ------------------------------ #
        composer = QWidget()
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(16, 14, 16, 14)
        composer_layout.setSpacing(10)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Mesaj yazın…")
        self._input.setProperty("variant", "form")
        self._input.setMinimumHeight(40)
        self._input.returnPressed.connect(self._on_send)
        composer_layout.addWidget(self._input, 1)

        send = QPushButton()
        send.setFixedSize(40, 40)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setIcon(
            icons.icon("send", self._theme.color("--color-brand-navy"), size=17, stroke_width=1.6)
        )
        send.setStyleSheet(
            f"background-color: {self._theme.color('--color-brand-amber')};"
            "border: none; border-radius: 9px;"
        )
        send.clicked.connect(self._on_send)
        composer_layout.addWidget(send)

        panel.add(composer)
        return panel

    # ------------------------------- mesajlar -------------------------------- #

    def add_separator(self, text: str) -> None:
        """Tarix ayırıcısı — "Bu gün 09:12"."""
        label = mono_label(text, muted=True, size=11)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, label)

    def add_message(self, text: str, *, outgoing: bool = False) -> None:
        bubble = ChatBubble(text, self._theme, outgoing=outgoing)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, bubble)

    def add_attachment(self, file_name: str) -> None:
        """Fayl əlavəsi — diaqnostika log-u kimi."""
        chip = QWidget()
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        box = QWidget()
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(12, 10, 12, 10)
        box_layout.setSpacing(8)
        glyph = plain_label()
        glyph.setPixmap(icons.render("file", self._theme.color("--color-text-muted"), size=15))
        box_layout.addWidget(glyph)
        box_layout.addWidget(body_label(file_name, size=12, wrap=False))
        box.setStyleSheet(
            f"background-color: {self._theme.color('--color-neutral-bg')};"
            f"border: 1px solid {self._theme.color('--color-card-border')};"
            "border-radius: 10px;"
        )
        layout.addWidget(box)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, chip)

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self.add_message(text, outgoing=True)
        self._input.clear()
        self.message_sent.emit(text)

    # ------------------------------- vəziyyət -------------------------------- #

    def set_unread(self, has_unread: bool) -> None:
        self._dot.setVisible(has_unread and not self._is_open)

    def toggle(self) -> None:
        self.close_panel() if self._is_open else self.open_panel()

    def open_panel(self) -> None:
        self._is_open = True
        self._panel.setVisible(True)
        self._dot.setVisible(False)
        self._input.setFocus()
        self.opened.emit()

    def close_panel(self) -> None:
        self._is_open = False
        self._panel.setVisible(False)
        self.closed.emit()

    @property
    def is_open(self) -> bool:
        return self._is_open

    def _layout_children(self) -> None:
        self._panel.move(0, 0)
        fab_x = self.width() - metrics.SUPPORT_FAB_SIZE
        fab_y = self.height() - metrics.SUPPORT_FAB_SIZE
        self._fab.move(fab_x, fab_y)
        self._dot.move(fab_x + metrics.SUPPORT_FAB_SIZE - 16, fab_y + 4)
        self._dot.raise_()

    def reposition(self, parent_width: int, parent_height: int) -> None:
        """Valideynin sağ-alt küncünə yerləşdirir."""
        self.move(
            parent_width - self.width() - self.MARGIN,
            parent_height - self.height() - self.MARGIN,
        )
        self._layout_children()


# --------------------------------------------------------------------------- #
# 22 — Developer (Master) Panel
# --------------------------------------------------------------------------- #


class DeveloperPanelScreen(Screen):
    """Tenant cədvəli + detal paneli (telemetriya, ticket, crash).

    Signals:
        tenant_selected: `tenant_id`.
        activation_toggled: (`tenant_id`, aktiv olsun?).
        search_changed: Axtarış mətni.
    """

    tenant_selected = Signal(str)
    activation_toggled = Signal(str, bool)
    search_changed = Signal(str)

    _STATUS_TONES: Final[dict[str, ChipTone]] = {
        "Aktiv": "success",
        "Deaktiv": "danger",
    }

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, padded=False, parent=parent)
        self._tenants: list[dict[str, str]] = []
        self._current: str | None = None
        self._current_active = True

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(26, 20, 26, 20)
        left_layout.setSpacing(12)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())
        self._search = QLineEdit()
        self._search.setPlaceholderText("Tenant axtar")
        self._search.setProperty("variant", "form")
        self._search.setFixedWidth(260)
        self._search.textChanged.connect(self.search_changed)
        toolbar_layout.addWidget(self._search)
        left_layout.addWidget(toolbar)

        self._table = DataTable(
            [
                Column("Tenant", 230),
                Column("Versiya", 110, mono=True),
                Column("İstifadəçi", 110),
                Column("Son aktivlik", 150),
                Column("Vəziyyət"),
            ],
            theme,
            footnote=(
                "Deaktiv edilmiş tenant-da bütün istifadəçilər LICENSE_INACTIVE ekranını görür."
            ),
        )
        self._table.row_selected.connect(self._on_row)
        left_layout.addWidget(self._table)
        layout.addWidget(left, 1)

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

        layout.addWidget(section_label("Tenant detalı"))
        self._detail_name = title_label("", size=18)
        layout.addWidget(self._detail_name)
        self._detail_meta = mono_label("", muted=True)
        layout.addWidget(self._detail_meta)

        self._toggle_button = action_button("Deaktiv Et")
        self._toggle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle_button.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_button)

        self._telemetry = self._build_metric_card("Telemetriya (7 gün)")
        layout.addWidget(self._telemetry)

        self._tickets = self._build_metric_card("Açıq ticket-lər")
        layout.addWidget(self._tickets)

        self._crashes = self._build_metric_card("Son crash hesabatları")
        layout.addWidget(self._crashes)

        layout.addStretch(1)
        return panel

    def _build_metric_card(self, title: str) -> Card:
        # Detal panelinin İÇİNDƏ oturur — maketdə `border-radius: 11px`.
        card = Card(padding=16, spacing=10, surface="panel")
        card.add(title_label(title, size=13))
        rows = QVBoxLayout()
        rows.setSpacing(10)
        holder = QWidget()
        holder.setLayout(rows)
        card.add(holder)
        card.setProperty("rows_layout", None)
        # `QVBoxLayout`-u xassə kimi saxlamaq olmur (Qt meta-tipi deyil),
        # ona görə birbaşa atribut kimi bağlanır.
        card.rows_layout = rows  # type: ignore[attr-defined]
        return card

    # ------------------------------- doldurma -------------------------------- #

    def set_tenants(self, tenants: list[dict[str, str]], *, summary: str) -> None:
        self._tenants = tenants
        self._summary.setText(summary)
        self._table.clear()

        for tenant in tenants:
            status = tenant.get("status", "Aktiv")
            tone = self._STATUS_TONES.get(status)
            if tone is None:
                # "Sınaq — 12 gün" kimi dəyişkən mətnlər xəbərdarlıq tonundadır.
                tone = "warning"
            status_cell = QWidget()
            status_layout = QHBoxLayout(status_cell)
            status_layout.setContentsMargins(0, 0, 0, 0)
            status_layout.setSpacing(8)
            dot_tokens = {
                "success": "--color-success",
                "danger": "--color-danger",
                "warning": "--color-warning",
            }
            status_layout.addWidget(StatusDot(self.theme.color(dot_tokens[tone])))
            status_layout.addWidget(body_label(status, size=13, wrap=False))
            status_layout.addStretch(1)

            self._table.add_row(
                [
                    tenant["name"],
                    mono_label(tenant.get("version", "")),
                    tenant.get("users", ""),
                    tenant.get("last_seen", ""),
                    status_cell,
                ]
            )

        if tenants:
            self._table.select(0)
            self._on_row(0)
        self.show_content()

    def _on_row(self, index: int) -> None:
        if not (0 <= index < len(self._tenants)):
            return
        tenant = self._tenants[index]
        self._current = tenant.get("id", tenant["name"])
        self._current_active = tenant.get("status") == "Aktiv"
        self._detail_name.setText(tenant["name"])
        self._detail_meta.setText(
            f"tenant_id: {tenant.get('id', '—')} · lisenziya {tenant.get('license_until', '—')}"
        )
        self._toggle_button.setText("Deaktiv Et" if self._current_active else "Aktivləşdir")
        self.tenant_selected.emit(self._current)

    def _on_toggle(self) -> None:
        if self._current is not None:
            self.activation_toggled.emit(self._current, not self._current_active)

    def _fill(self, card: Card, rows: list[tuple[str, str, str]]) -> None:
        layout = card.rows_layout  # type: ignore[attr-defined]
        clear_layout(layout)

        tokens = {
            "": "--color-text-primary",
            "warning": "--color-warning",
            "danger": "--color-danger",
        }
        for name, value, tone in rows:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            if tone:
                row_layout.addWidget(StatusDot(self.theme.color(tokens[tone]), size=7))
            row_layout.addWidget(body_label(name, size=13, wrap=False))
            row_layout.addWidget(stretch())
            value_label = mono_label(value)
            if tone:
                value_label.setStyleSheet(f"color: {self.theme.color(tokens[tone])};")
            row_layout.addWidget(value_label)
            layout.addWidget(row)

    def set_telemetry(self, rows: list[tuple[str, str, str]]) -> None:
        self._fill(self._telemetry, rows)

    def set_tickets(self, rows: list[tuple[str, str, str]]) -> None:
        self._fill(self._tickets, rows)

    def set_crashes(self, rows: list[tuple[str, str, str]]) -> None:
        self._fill(self._crashes, rows)

    def table(self) -> DataTable:
        return self._table


# --------------------------------------------------------------------------- #
# 23 — LICENSE_INACTIVE
# --------------------------------------------------------------------------- #


class LicenseInactiveScreen(QWidget):
    """Tam ekran bloklama — naviqasiya YOXDUR.

    Bu ekran şüurlu şəkildə ÇIXIŞSIZDIR: menyu, geri düyməsi və ya "bağla"
    yoxdur. Lisenziya deaktivdirsə, tətbiqin heç bir hissəsi açılmamalıdır —
    əks halda bloklama sadəcə bir bildiriş olardı.

    Məlumatın qorunduğu AÇIQ yazılır, çünki istifadəçinin ilk qorxusu
    "məlumatlarım silindimi?" olur.
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        reason: str,
        deactivated_at: str,
        installation_id: str,
        support_contact: str = "dəstək@kompas.az · +994 12 000 00 00",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {theme.color('--color-content-bg')};")

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Lisenziya bloklaması — maketdə mərkəzi `620px` kart, `14px` künc.
        card = Card(padding=44, spacing=24, surface="modal", shadow=True)
        card.setFixedWidth(620)
        card.body().setAlignment(Qt.AlignmentFlag.AlignHCenter)

        icon_box = StateIconBox("lock", theme, tone="danger", box_size=62, icon_size=28)
        card.body().addWidget(icon_box, alignment=Qt.AlignmentFlag.AlignHCenter)

        heading = plain_label("Lisenziya aktiv deyil")
        heading_font = heading.font()
        heading_font.setPixelSize(26)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.add(heading)

        message = body_label(
            "Bu quraşdırma müvəqqəti dayandırılıb. Məlumatlarınız qorunur, "
            "lakin proqramdan istifadə mümkün deyil.",
            size=15,
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setMaximumWidth(440)
        message.setStyleSheet(f"color: {theme.color('--color-text-secondary')};")
        card.body().addWidget(message, alignment=Qt.AlignmentFlag.AlignHCenter)

        details = Card(padding=0, spacing=0)
        for index, (name, value) in enumerate(
            (
                ("Səbəb", reason),
                ("Deaktiv tarixi", deactivated_at),
                ("Quraşdırma nömrəsi", installation_id),
            )
        ):
            if index:
                details.add(Divider())
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(18, 14, 18, 14)
            row_layout.addWidget(muted_label(name, size=13))
            row_layout.addWidget(stretch())
            row_layout.addWidget(
                mono_label(value, size=13) if index else body_label(value, size=13, wrap=False)
            )
            details.add(row)
        card.add(details)

        card.add(Divider())

        contact_hint = muted_label("Bərpa üçün təchizatçı ilə əlaqə saxlayın")
        contact_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body().addWidget(contact_hint, alignment=Qt.AlignmentFlag.AlignHCenter)

        contact = title_label(support_contact, size=15)
        contact.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body().addWidget(contact, alignment=Qt.AlignmentFlag.AlignHCenter)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)


__all__ = [
    "ChatBubble",
    "DeveloperPanelScreen",
    "LicenseInactiveScreen",
    "SupportChatWidget",
]
