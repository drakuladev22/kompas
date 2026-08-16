"""Səhifə başlığı (header) — Faza 4.2.

Maketdə hər admin ekranının üstündə eyni 62px-lik zolaq var: solda səhifə adı
və kontekst mətni, sağda tema keçidi, bildiriş zəngi və istifadəçi.

──────────────────────────────────────────────────────────────────────────────
ZƏNG NİŞANI NİYƏ AYRICA WIDGET-DİR
──────────────────────────────────────────────────────────────────────────────
Maketdə oxunmamış bildiriş sayı zəng düyməsinin SAĞ-YUXARI küncündən kənara
daşan kiçik amber dairədir (`top: -4px; right: -4px`). Qt-də bir düymənin
üzərinə "daşan" element yerləşdirmək layout ilə mümkün deyil — uşaq widget
valideynin sərhədləri ilə kəsilir. Ona görə zəng + nişan birlikdə bir
konteynerdə saxlanılır və nişan `move()` ilə mütləq mövqeyə qoyulur.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import icon_button
from src.presentation.widgets.primitives import Avatar, muted_label, plain_label, title_label


class NotificationBell(QWidget):
    """Bildiriş zəngi + oxunmamış sayı nişanı.

    Signals:
        clicked: Zəngə klik — bildiriş paneli açılır.
    """

    clicked = Signal()

    #: Nişanın ölçüsü və düymədən kənara daşma məsafəsi (maketdən).
    _BADGE_HEIGHT = 18
    _BADGE_OFFSET = 4

    def __init__(
        self,
        *,
        icon_color: str,
        badge_bg: str,
        badge_fg: str,
        border_color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        size = metrics.HEADER_ICON_BUTTON + self._BADGE_OFFSET
        self.setFixedSize(size, size)

        self._button = icon_button(
            "bell",
            icon_color,
            tooltip="Bildirişlər",
            accessible_name="Bildirişlər",
            accessible_description="Oxunmamış bildiriş sayı adın yanında elan olunur",
            parent=self,
        )
        self._button.move(0, self._BADGE_OFFSET)
        self._button.clicked.connect(self.clicked)

        self._badge = plain_label("", self)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_bg = badge_bg
        self._badge_fg = badge_fg
        self._border_color = border_color
        self._apply_badge_style()

        font = self._badge.font()
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        self._badge.setFont(font)
        self._badge.setVisible(False)

        self._count = 0

    def _apply_badge_style(self) -> None:
        # Bu tək element QSS şablonuna qoyulmur: rəngləri valideyn ekrandan
        # gəlir (aktiv/passiv zəng fərqli fonda olur) və şablon token adı ilə
        # işləyir, konkret dəyərlə deyil.
        self._badge.setStyleSheet(
            f"background-color: {self._badge_bg};"
            f"color: {self._badge_fg};"
            f"border: 2px solid {self._border_color};"
            f"border-radius: {self._BADGE_HEIGHT // 2}px;"
            "padding: 0 4px;"
        )

    def set_count(self, count: int) -> None:
        """Oxunmamış sayını göstərir; sıfır olduqda nişan gizlənir."""
        self._count = max(0, count)
        # Say ekran oxuyucusuna da çatmalıdır: nişan düymənin ÜSTÜNDƏ üzən
        # ayrıca `QLabel`-dir və Qt onu düymənin adı ilə əlaqələndirmir —
        # yalnız-vizual qalsaydı, oxunmamış bildirişin VARLIĞI görməyən
        # istifadəçidən gizli olardı.
        self._button.setAccessibleName(
            "Bildirişlər" if self._count == 0 else f"Bildirişlər — {self._count} oxunmamış"
        )
        if self._count == 0:
            self._badge.setVisible(False)
            return

        text = "99+" if self._count > 99 else str(self._count)  # noqa: PLR2004
        self._badge.setText(text)
        self._badge.adjustSize()
        width = max(self._BADGE_HEIGHT, self._badge.width())
        self._badge.setFixedSize(width, self._BADGE_HEIGHT)
        self._badge.move(self.width() - width, 0)
        self._badge.setVisible(True)
        self._badge.raise_()

    def set_active(self, active: bool) -> None:
        """Panel açıq olduqda düymə dolu fon alır (maketdəki kimi)."""
        self._button.setProperty("active", "true" if active else "false")
        style = self._button.style()
        style.unpolish(self._button)
        style.polish(self._button)

    def apply_theme(
        self, *, icon_color: str, badge_bg: str, badge_fg: str, border_color: str
    ) -> None:
        self._button.setIcon(icons.icon("bell", icon_color))
        self._badge_bg = badge_bg
        self._badge_fg = badge_fg
        self._border_color = border_color
        self._apply_badge_style()


class PageHeader(QWidget):
    """62px-lik səhifə başlığı.

    Signals:
        theme_toggled: Tema düyməsi.
        bell_clicked: Bildiriş zəngi.
        profile_clicked: İstifadəçi adına/avatarına klik.
    """

    theme_toggled = Signal()
    bell_clicked = Signal()
    profile_clicked = Signal()

    def __init__(
        self,
        *,
        icon_color: str,
        avatar_bg: str,
        avatar_fg: str,
        badge_bg: str,
        badge_fg: str,
        surface_color: str,
        dark_mode: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        enable_styled_background(self)
        self.setFixedHeight(metrics.HEADER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(metrics.HEADER_PADDING_H, 0, metrics.HEADER_PADDING_H, 0)
        layout.setSpacing(metrics.HEADER_SPACING)

        # ------------------------------ sol tərəf --------------------------- #
        self._title = title_label("")
        layout.addWidget(self._title)

        self._subtitle = muted_label("")
        layout.addWidget(self._subtitle)

        self._slot = QWidget()
        slot_layout = QHBoxLayout(self._slot)
        slot_layout.setContentsMargins(0, 0, 0, 0)
        slot_layout.setSpacing(12)
        self._slot_layout = slot_layout
        layout.addWidget(self._slot)

        layout.addStretch(1)

        # ------------------------------ sağ tərəf --------------------------- #
        self._theme_button = icon_button(
            "sun" if dark_mode else "moon",
            icon_color,
            tooltip="Görünüşü dəyiş",
            accessible_name="Görünüş rejimini dəyiş",
            accessible_description="İşıqlı və tünd tema arasında keçid edir",
        )
        self._theme_button.clicked.connect(self.theme_toggled)
        layout.addWidget(self._theme_button)

        self._bell = NotificationBell(
            icon_color=icon_color,
            badge_bg=badge_bg,
            badge_fg=badge_fg,
            border_color=surface_color,
        )
        self._bell.clicked.connect(self.bell_clicked)
        layout.addWidget(self._bell)

        self._avatar = Avatar("", background=avatar_bg, foreground=avatar_fg)
        layout.addWidget(self._avatar)

        self._user_name = plain_label()
        user_font = self._user_name.font()
        user_font.setPixelSize(13)
        user_font.setWeight(QFont.Weight.DemiBold)
        self._user_name.setFont(user_font)
        layout.addWidget(self._user_name)

        self._icon_color = icon_color

    # ------------------------------- məzmun --------------------------------- #

    def set_page(self, title: str, subtitle: str = "") -> None:
        """Başlıq və kontekst mətnini dəyişir (məs. "Cərimələr", "Avqust 2026")."""
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._subtitle.setVisible(bool(subtitle))

    def set_user(self, full_name: str) -> None:
        self._user_name.setText(full_name)
        self._avatar.set_name(full_name)

    def user_name(self) -> str:
        """Hazırda göstərilən istifadəçi adı."""
        return self._user_name.text()

    def set_unread(self, count: int) -> None:
        self._bell.set_count(count)

    def bell(self) -> NotificationBell:
        """Zəng widget-i — panel açılanda `set_active()` üçün."""
        return self._bell

    def slot(self) -> QHBoxLayout:
        """Başlığın yanındakı sərbəst sahə — filtr çipləri, status nişanları."""
        return self._slot_layout

    # ------------------------------- görünüş --------------------------------- #

    def apply_theme(
        self,
        *,
        icon_color: str,
        avatar_bg: str,
        avatar_fg: str,
        badge_bg: str,
        badge_fg: str,
        surface_color: str,
        dark_mode: bool,
    ) -> None:
        self._icon_color = icon_color
        self._theme_button.setIcon(icons.icon("sun" if dark_mode else "moon", icon_color))
        self._theme_button.setIconSize(QSize(icons.DEFAULT_SIZE, icons.DEFAULT_SIZE))
        self._bell.apply_theme(
            icon_color=icon_color,
            badge_bg=badge_bg,
            badge_fg=badge_fg,
            border_color=surface_color,
        )
        self._avatar.set_colors(background=avatar_bg, foreground=avatar_fg)


__all__ = ["NotificationBell", "PageHeader"]
