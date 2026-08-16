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
    QVBoxLayout,
    QWidget,
)

from src.presentation.theme.manager import set_surface_color
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.primitives import (
    Card,
    Divider,
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
        header.setFixedHeight(56)
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
        identity_layout.setSpacing(4)
        identity_layout.addWidget(title_label("KompasOS Dəstək", size=15))
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
        self._messages_layout.setSpacing(16)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._messages_host)
        panel.body().addWidget(self._scroll, 1)

        panel.add(Divider())

        # ------------------------------- giriş ------------------------------ #
        composer = QWidget()
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(16, 14, 16, 14)
        composer_layout.setSpacing(12)

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


# --------------------------------------------------------------------------- #
# DEVELOPER PANELİ BURADA DEYİL
# --------------------------------------------------------------------------- #
# Bu faylda əvvəllər `DeveloperPanelScreen` adlı ikinci bir panel vardı: maket
# dövründən qalmış, HEÇ YERDƏN qurulmayan bir sinif. Nə `app.py`, nə
# `preview_screens`, nə də testlər ona toxunurdu — üç siqnalı da (axtarış,
# müştəri seçimi, aktivləşdirmə) məhz buna görə ölü idi.
#
# CANLI panel `src/developer_panel/ui.py::DeveloperPanelWindow`-dur və
# `--gui --developer-mode` onu açır (`main.py::_run_developer_panel`). İki
# nüsxəni saxlamaq təhlükəli idi: hansısa düzəliş səhv panelə yazıla bilərdi
# və fərq yalnız hazırlayıcı rejimində, yəni müştəridə görünməyən yerdə üzə
# çıxardı. Ona görə ölü nüsxə silindi.
#
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
        set_surface_color(self, theme.color("--color-content-bg"))

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Lisenziya bloklaması — maketdə mərkəzi `620px` kart, `14px` künc.
        card = Card(padding=40, spacing=20, surface="modal", shadow=True)
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
    "LicenseInactiveScreen",
    "SupportChatWidget",
]
