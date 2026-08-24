"""Qrup E — dəstək və developer — Faza 4.2.

Maket: "KompasOS - Qrup E.dc.html", ekranlar 21–23.

    21  Diskret Dəstək Chat Widget-i
    22  Developer (Master) Panel
    23  LICENSE_INACTIVE ekranı
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.domain.value_objects.support import SupportChannel
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
    #: İşçi kanalı seçdi — dəyər `SupportChannel` sətridir (Faza 1).
    channel_selected = Signal(str)

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
        # `None` = hələ seçilməyib. Defolt kanal QOYULMUR: «Texniki» defolt
        # olsaydı, tələsik yazan işçinin kadr sualı hazırlayıcıya gedərdi və
        # o, seçim ekranını heç görməzdi (Faza 1-in bütün mənası budur).
        self._channel: SupportChannel | None = None
        # Seçilmiş, LAKİN hələ göndərilməmiş şəkil: `(ad, baytlar)`.
        #
        # Baytlar YADDAŞDA saxlanılır, fayl YOLU yox: istifadəçi şəkli seçib
        # sonra onu masaüstündən silə bilər və göndərmə anında yol boşa
        # çıxardı. 5 MB hədd (`MAX_UPLOAD_BYTES`) bunu təhlükəsiz edir.
        self._attachment: tuple[str, bytes] | None = None

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
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(metrics.SPACE_MS)

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
        # Başlıqdakı ikinci sətir SEÇİLMİŞ KANALI göstərir. Əvvəl burada
        # «Onlayn · adətən 10 dəq içində» yazırdı — o, uydurma vəd idi
        # (heç bir yerdə ölçülmürdü) və indi onun yerini işçinin FAKTİKİ
        # seçimi tutur: mesajın hara getdiyi vədədən vacibdir.
        self._channel_label = muted_label("")
        identity_layout.addWidget(self._channel_label)
        header_layout.addWidget(identity)
        header_layout.addWidget(stretch())

        self._back = QPushButton("‹")
        self._back.setProperty("variant", "window")
        self._back.setFixedSize(28, 28)
        self._back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back.setToolTip("Kanal seçiminə qayıt")
        self._back.setVisible(False)
        self._back.clicked.connect(self.reset_channel)
        header_layout.addWidget(self._back)

        close = QPushButton("×")
        close.setProperty("variant", "window")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.close_panel)
        header_layout.addWidget(close)

        panel.add(header)

        # ------------------------------ mesajlar ---------------------------- #
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._messages_host = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_host)
        self._messages_layout.setContentsMargins(16, 16, 16, 16)
        self._messages_layout.setSpacing(16)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._messages_host)

        # İKİ SƏHİFƏ, BİR PANEL: seçim və söhbət eyni yeri paylaşır.
        # Seçimi ayrıca dialoqda göstərmək «kiçik, nəzakətli» panelin
        # (bölmə 8) üstünə modal açardı və diskretliyi pozardı.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_chooser())
        self._stack.addWidget(self._build_chat_page())
        panel.body().addWidget(self._stack, 1)
        return panel

    def _build_chooser(self) -> QWidget:
        """«Kimə yazırsınız?» — iki kart, uzun izahat YOX (Faza 1)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(metrics.SPACE_MS)
        layout.addWidget(title_label("Kimə yazırsınız?", size=15))
        for channel in (SupportChannel.INTERNAL, SupportChannel.TECHNICAL):
            layout.addWidget(self._channel_card(channel))
        layout.addStretch(1)
        return page

    def _channel_card(self, channel: SupportChannel) -> QWidget:
        card = QPushButton()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumHeight(64)
        card.setStyleSheet(
            f"QPushButton {{ background-color: {self._theme.color('--color-neutral-bg')};"
            f"border: 1px solid {self._theme.color('--color-card-border')};"
            f"border-radius: {self._theme.color('--radius-control')}px; text-align: left; "
            "padding: 12px 14px; }"
            f"QPushButton:hover {{ border-color: {self._theme.color('--color-brand-amber')}; }}"
        )
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        inner.addWidget(title_label(channel.label_az, size=13))
        inner.addWidget(muted_label(channel.hint_az))
        card.clicked.connect(lambda _=False, value=channel: self.select_channel(value))
        return card

    def _build_chat_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(Divider())

        # ------------------------------- giriş ------------------------------ #
        composer = QWidget()
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(16, 16, 16, 16)
        composer_layout.setSpacing(metrics.SPACE_MS)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Mesaj yazın…")
        self._input.setProperty("variant", "form")
        self._input.setMinimumHeight(40)
        self._input.returnPressed.connect(self._on_send)
        composer_layout.addWidget(self._input, 1)

        attach = QPushButton()
        attach.setFixedSize(40, 40)
        attach.setCursor(Qt.CursorShape.PointingHandCursor)
        attach.setToolTip("Şəkil əlavə et")
        attach.setIcon(
            icons.icon("file", self._theme.color("--color-text-muted"), size=17, stroke_width=1.6)
        )
        attach.clicked.connect(self._on_attach)
        composer_layout.addWidget(attach)

        send = QPushButton()
        send.setFixedSize(40, 40)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setIcon(
            icons.icon("send", self._theme.color("--color-brand-navy"), size=17, stroke_width=1.6)
        )
        send.setStyleSheet(
            f"background-color: {self._theme.color('--color-brand-amber')};"
            f"border: none; border-radius: {self._theme.color('--radius-control')}px;"
        )
        send.clicked.connect(self._on_send)
        composer_layout.addWidget(send)

        # «Təcili» YALNIZ texniki kanalda görünür: daxili müraciətdə onun
        # heç bir nəticəsi olmazdı (Telegram rejimi yalnız texnikiyə baxır)
        # və mənasız işarə qutusu istifadəçini yanıldardı.
        self._urgent = QCheckBox("Təcili")
        self._urgent.setVisible(False)
        urgent_row = QWidget()
        urgent_layout = QHBoxLayout(urgent_row)
        urgent_layout.setContentsMargins(16, 0, 16, 8)
        urgent_layout.setSpacing(8)
        urgent_layout.addWidget(self._urgent)
        # Seçilmiş faylın adı — «əlavə etdimmi?» sualının YEGANƏ cavabı:
        # fayl dialoqu bağlandıqdan sonra panel heç bir iz göstərməsəydi,
        # istifadəçi şəkli iki dəfə seçərdi.
        self._attachment_label = muted_label("")
        urgent_layout.addWidget(self._attachment_label)
        urgent_layout.addStretch(1)

        layout.addWidget(composer)
        layout.addWidget(urgent_row)
        return page

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
        box_layout.setContentsMargins(12, 8, 12, 8)
        box_layout.setSpacing(8)
        glyph = plain_label()
        glyph.setPixmap(icons.render("file", self._theme.color("--color-text-muted"), size=15))
        box_layout.addWidget(glyph)
        box_layout.addWidget(body_label(file_name, size=12, wrap=False))
        box.setStyleSheet(
            f"background-color: {self._theme.color('--color-neutral-bg')};"
            f"border: 1px solid {self._theme.color('--color-card-border')};"
            f"border-radius: {self._theme.color('--radius-control')}px;"
        )
        layout.addWidget(box)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, chip)

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        # Kanal seçilməyibsə göndərmə YOXDUR: `_on_send` yalnız söhbət
        # səhifəsindən çağırıla bilər, lakin klaviatura ilə (Enter) səhv
        # vaxtda tetiklənməsi mümkündür və mesaj təyinatsız qalardı.
        if self._channel is None:
            return
        self.add_message(text, outgoing=True)
        if self._attachment is not None:
            self.add_attachment(self._attachment[0])
        self._input.clear()
        self.message_sent.emit(text)
        # Əlavə GÖNDƏRİŞDƏN SONRA təmizlənir: qalsaydı, növbəti mesaj eyni
        # şəkli İKİNCİ dəfə yükləyərdi və işçi bunu görməzdi.
        self._attachment = None
        self._attachment_label.setText("")

    def _on_attach(self) -> None:
        """Şəkil seçimi — fayl YOLU deyil, BAYTLAR götürülür (bax `__init__`).

        Oxu uğursuzluğu (fayl silinib, icazə yoxdur) söhbətin İÇİNDƏ
        göstərilir: modal açmaq kiçik, diskret panelin xarakterini pozardı
        (eyni qərar `controllers/support_chat.py` başlığındadır).
        """
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        path, _ = QFileDialog.getOpenFileName(
            self, "Şəkil seçin", "", "Şəkillər (*.jpg *.jpeg *.png *.webp)"
        )
        if not path:
            return
        file = Path(path)
        try:
            content = file.read_bytes()
        except OSError:
            self.add_message("⚠ Şəkil oxunmadı — faylı yenidən seçin.")
            return
        self._attachment = (file.name, content)
        self._attachment_label.setText(f"📎 {file.name}")

    def pending_attachment(self) -> tuple[str, bytes] | None:
        """Göndəriləcək şəkil — kontroller onu `send()`-ə ötürür."""
        return self._attachment

    # -------------------------------- kanal ---------------------------------- #

    def select_channel(self, channel: SupportChannel) -> None:
        """Kanalı seçir və söhbət səhifəsinə keçir."""
        self._channel = channel
        self._channel_label.setText(channel.label_az)
        self._urgent.setVisible(channel.notifies_telegram)
        self._urgent.setChecked(False)
        self._back.setVisible(True)
        self._stack.setCurrentIndex(1)
        self._input.setFocus()
        self.channel_selected.emit(channel.value)

    def reset_channel(self) -> None:
        """Seçim ekranına qayıdır və söhbəti təmizləyir.

        Söhbət TƏMİZLƏNİR, çünki digər kanalın tarixçəsi AYRIdır: köhnə
        balonlar qalsaydı, işçi daxili müraciətinin cavabını texniki
        söhbətdə görərdi.
        """
        self._channel = None
        self._channel_label.setText("")
        self._attachment = None
        self._attachment_label.setText("")
        self._urgent.setVisible(False)
        self._back.setVisible(False)
        self.clear_messages()
        self._stack.setCurrentIndex(0)

    def clear_messages(self) -> None:
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def selected_channel(self) -> SupportChannel | None:
        return self._channel

    def is_urgent(self) -> bool:
        return bool(self._urgent.isChecked())

    # ------------------------------- vəziyyət -------------------------------- #

    def set_unread(self, has_unread: bool) -> None:
        self._dot.setVisible(has_unread and not self._is_open)

    def toggle(self) -> None:
        self.close_panel() if self._is_open else self.open_panel()

    def open_panel(self) -> None:
        self._is_open = True
        self._panel.setVisible(True)
        self._dot.setVisible(False)
        # Kanal seçilməyibsə fokus GİRİŞ SAHƏSİNƏ verilmir: o, gizli
        # səhifədədir və fokusun görünməyən sahədə olması klaviatura ilə
        # işləyəni «yazıram, görünmür» vəziyyətinə salardı.
        if self._channel is None:
            self._stack.setCurrentIndex(0)
        else:
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
        self._theme = theme
        set_surface_color(self, theme.color("--color-content-bg"))

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Lisenziya bloklaması — maketdə mərkəzi `620px` kart, `14px` künc.
        card = Card(padding=40, spacing=metrics.CARD_CONTENT_SPACING, surface="modal", shadow=True)
        card.setFixedWidth(620)
        card.body().setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # İstinad tema keçidi üçün saxlanılır (bax `apply_theme`).
        self._icon_box = StateIconBox("lock", theme, tone="danger", box_size=62, icon_size=28)
        card.body().addWidget(self._icon_box, alignment=Qt.AlignmentFlag.AlignHCenter)

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
        self._message = message
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
            row_layout.setContentsMargins(16, 16, 16, 16)
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

    def apply_theme(self, theme: ThemeManager) -> None:
        """Bloklama ekranı da tema düyməsinə tabedir (THEME-1).

        Ekran çıxışsızdır, lakin başlıq zolağı görünür və düymə işləkdir —
        mətn oxunmaz qalsaydı, istifadəçi bloklamanın SƏBƏBİNİ də görməzdi.
        """
        self._theme = theme
        set_surface_color(self, theme.color("--color-content-bg"))
        self._message.setStyleSheet(f"color: {theme.color('--color-text-secondary')};")
        self._icon_box.apply_theme(theme)


__all__ = [
    "ChatBubble",
    "LicenseInactiveScreen",
    "SupportChatWidget",
]
