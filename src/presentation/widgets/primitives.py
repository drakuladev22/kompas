"""Dizayn sisteminin bazis komponentləri — Faza 4.2.

Maketdə (Qrup A–G) təkrarlanan ən kiçik hissələr: kart, nişan (chip), status
nöqtəsi, avatar, ayırıcı, skeleton bloku və mətn rolları.

──────────────────────────────────────────────────────────────────────────────
RƏNG NİYƏ ARQUMENT KİMİ ÖTÜRÜLÜR
──────────────────────────────────────────────────────────────────────────────
`StatusDot` və `Avatar` QSS ilə ifadə oluna bilməyən formalar çəkir (dairə,
baş hərflər), yəni rəngi `QPainter`-ə özləri verməlidirlər. Rəngi qlobal
"cari tema" dəyişənindən oxumaq daha qısa olardı, lakin o zaman:

    * widget-i testdə tək başına qurmaq mümkün olmazdı (qlobal quraşdırma
      tələb olunardı), və
    * eyni ekranda iki fərqli palitra (məs. tünd kiosk kartı işıqlı admin
      pəncərəsində) göstərmək mümkün olmazdı.

Ona görə rəng ARQUMENTDİR; onu verən tərəf ekran/örtükdür və o, `ThemeManager`
-dən oxuyur. QSS ilə ifadə oluna bilən hər şey (kart, chip, ayırıcı) isə
`variant`/`chip` xüsusiyyəti ilə şablona buraxılır — orada tema avtomatik
işləyir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.i18n.text import az_upper
from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import metrics

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent, QPaintEvent

#: Nişan tonları — QSS-dəki `QLabel[chip="…"]` seçiciləri ilə eynidir.
ChipTone = Literal["success", "warning", "danger", "info", "neutral"]

#: Maketdəki kart kölgəsi: `0 18px 46px rgba(11,29,58,0.28)` (ekran çərçivəsi)
#: və `0 6px 16px rgba(11,29,58,0.12)` (üzən element). Qt-də `box-shadow`
#: yoxdur — `QGraphicsDropShadowEffect` işlədilir.
_SHADOW_BLUR: Final = 32
_SHADOW_OFFSET_Y: Final = 8
_SHADOW_ALPHA: Final = 46


# --------------------------------------------------------------------------- #
# Mətn rolları
# --------------------------------------------------------------------------- #


def title_label(text: str, *, size: int = metrics.FONT_PAGE_TITLE) -> QLabel:
    """Səhifə/bölmə başlığı — 600 çəki (maketdə `font-weight: 600`)."""
    label = QLabel(text)
    label.setObjectName("PageTitle")
    font = label.font()
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold)
    label.setFont(font)
    return label


def muted_label(text: str, *, size: int = metrics.FONT_CAPTION) -> QLabel:
    """Solğun köməkçi mətn (`--color-text-muted`)."""
    label = QLabel(text)
    label.setProperty("variant", "muted")
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    return label


def mono_label(text: str, *, muted: bool = False, size: int = metrics.FONT_CAPTION) -> QLabel:
    """Monoaralıqlı mətn — saat, xəta kodu, `tenant_id` kimi dəyərlər üçün."""
    label = QLabel(text)
    label.setProperty("variant", "mono-muted" if muted else "mono")
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    return label


def section_label(text: str) -> QLabel:
    """Böyük hərfli bölmə etiketi ("NAVİQASİYA").

    Maketdə `text-transform: uppercase` və `letter-spacing: 0.12em` var —
    Qt Style Sheet hər ikisini dəstəkləmir, ona görə burada `QFont` ilə
    verilir və mətn Python tərəfdə böyüdülür.
    """
    label = QLabel(az_upper(text))
    label.setObjectName("SidebarSectionLabel")
    font = label.font()
    font.setPixelSize(metrics.FONT_SECTION_LABEL)
    font.setWeight(QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, metrics.SECTION_LABEL_LETTER_SPACING)
    label.setFont(font)
    return label


def body_label(text: str, *, size: int = 14, wrap: bool = True) -> QLabel:
    """Adi gövdə mətni — boş vəziyyət izahları kimi çoxsətirli bloklar üçün."""
    label = QLabel(text)
    label.setWordWrap(wrap)
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    return label


# --------------------------------------------------------------------------- #
# Səthlər
# --------------------------------------------------------------------------- #


class Card(QFrame):
    """Ağ (tünddə `#0F1B30`) səth, 1px sərhəd, 12px künc — maketin əsas qabı.

    Args:
        padding: Daxili boşluq. Maketdə siyahı sətri 16/20, adi kart 18-dir.
        shadow: Üzən elementlər (bildiriş paneli, modal) üçün kölgə.
    """

    def __init__(
        self,
        *,
        padding: int = metrics.CARD_PADDING,
        spacing: int = 12,
        shadow: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("variant", "card")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(spacing)

        if shadow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(_SHADOW_BLUR)
            effect.setOffset(0, _SHADOW_OFFSET_Y)
            effect.setColor(QColor(11, 29, 58, _SHADOW_ALPHA))
            self.setGraphicsEffect(effect)

    def body(self) -> QVBoxLayout:
        """Kartın daxili yerləşdirməsi — məzmun bura əlavə olunur."""
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        """Widget-i karta əlavə edir və onu geri qaytarır (zəncirləmə üçün)."""
        self._layout.addWidget(widget)
        return widget


class Divider(QFrame):
    """1px ayırıcı xətt — maketdə `border-bottom: 1px solid #EDF0F6`."""

    def __init__(self, *, vertical: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("variant", "divider-v" if vertical else "divider")
        if vertical:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


# --------------------------------------------------------------------------- #
# Nişanlar və göstəricilər
# --------------------------------------------------------------------------- #


class Chip(QLabel):
    """Yumşaq fonlu status nişanı — "Boş vəziyyət", "5 yeni", "Aktiv".

    Ton QSS-ə `chip` xüsusiyyəti ilə ötürülür; rəng cütləri `tokens.py`-da
    WCAG AA üçün kalibrlənib (bax orada "DİZAYN MAKETİ İLƏ FƏRQLƏR").
    """

    def __init__(
        self, text: str, tone: ChipTone = "neutral", *, parent: QWidget | None = None
    ) -> None:
        super().__init__(text, parent)
        self.setProperty("chip", tone)
        font = self.font()
        font.setPixelSize(metrics.FONT_CAPTION)
        self.setFont(font)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: ChipTone) -> None:
        """Tonu dəyişir və üslubu yenidən hesablatdırır.

        Qt dinamik xüsusiyyət dəyişəndə QSS-i özü yeniləmir — `unpolish`/
        `polish` olmadan nişan köhnə rəngdə qalardı.
        """
        self.setProperty("chip", tone)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()


class FilterChip(Chip):
    """Klik edilə bilən nişan — süzgəc zolaqlarında işlədilir.

    Ayrı sinif kimi mövcuddur, çünki `QLabel`-in `mousePressEvent`-ini
    kənardan `lambda` ilə əvəz etmək (`chip.mousePressEvent = ...`) işləyir,
    lakin tip yoxlayıcısı üçün görünməzdir və hadisə imzası səhv yazılsa
    yalnız icra zamanı üzə çıxardı.

    Signals:
        clicked: Nişanın açarı.
    """

    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        text: str,
        tone: ChipTone = "neutral",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, tone, parent=parent)
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class LinkLabel(QLabel):
    """Mətn şəklində hərəkət — "Hamısını oxunmuş et", "Bütün bildirişlərə bax".

    Signals:
        clicked: Klik.
    """

    clicked = Signal()

    def __init__(self, text: str, *, size: int = 13, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        font = self.font()
        font.setPixelSize(size)
        self.setFont(font)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ClickableCard(Card):
    """Bütövlükdə seçilə bilən kart — siyahı sətirlərində (növbə dəyişmə).

    Signals:
        clicked: Kartın açarı.
    """

    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        *,
        padding: int = metrics.CARD_PADDING,
        spacing: int = 12,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(padding=padding, spacing=spacing, parent=parent)
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class StatusDot(QWidget):
    """Kiçik dolu dairə — cədvəllərdə status göstəricisi (maketdə 8px).

    QSS ilə dairə çəkmək üçün `border-radius` yarım ölçüyə bərabər olmalıdır;
    bu, widget ölçüsü dəyişdikdə pozulur. Ona görə birbaşa çəkilir.
    """

    def __init__(
        self, color: str, *, size: int = metrics.STATUS_DOT_SIZE, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())


class Avatar(QWidget):
    """Dairəvi istifadəçi avatarı — şəkil yoxdursa baş hərflər.

    Maketdə şəkilsiz avatar zolaqlı boz naxışdır; burada baş hərflər seçilib,
    çünki 21 filialda eyni naxış bir-birindən ayırd edilməzdi və ad onsuz da
    yan tərəfdə həmişə görünmür (cədvəl sətirlərində yer dardır).
    """

    def __init__(
        self,
        full_name: str,
        *,
        background: str,
        foreground: str,
        size: int = metrics.AVATAR_SIZE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._initials = self._compute_initials(full_name)
        self._background = QColor(background)
        self._foreground = QColor(foreground)
        self._size = size
        self.setFixedSize(size, size)

    @staticmethod
    def _compute_initials(full_name: str) -> str:
        parts = [part for part in full_name.split() if part]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:1].upper()
        return (parts[0][:1] + parts[-1][:1]).upper()

    def set_colors(self, *, background: str, foreground: str) -> None:
        self._background = QColor(background)
        self._foreground = QColor(foreground)
        self.update()

    def set_name(self, full_name: str) -> None:
        """Adı dəyişir və baş hərfləri yenidən hesablayır.

        Widget-i yenidən yaratmaq əvəzinə mövcud olanı yeniləyir — avatar
        layout-da oturur və dəyişdirilməsi valideyn sırasını pozardı.
        """
        self._initials = self._compute_initials(full_name)
        self.setToolTip(full_name)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        path = QPainterPath()
        path.addEllipse(0, 0, self._size, self._size)
        painter.fillPath(path, self._background)

        painter.setPen(self._foreground)
        font = painter.font()
        font.setPixelSize(max(9, int(self._size * 0.4)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._initials)


class Skeleton(QWidget):
    """Yüklənmə bloku — maketdəki `kshimmer` animasiyasının Qt qarşılığı.

    Maket 1.4s-lik `opacity: 0.55 → 1 → 0.55` dövrü və sətirlər arası
    pilləli gecikmə (`0.1s`, `0.2s`, …) işlədir. Burada eyni effekt
    `QGraphicsOpacityEffect` üzərində `QPropertyAnimation` ilə qurulur;
    gecikmə `delay_ms` ilə verilir.

    Animasiya `start()` çağırılana qədər İŞLƏMİR — belə ki, ekran testdə
    sabit görüntü ilə yoxlana bilsin.
    """

    #: Maketdəki dövr müddəti.
    DURATION_MS: Final = 1400
    MIN_OPACITY: Final = 0.55

    def __init__(
        self,
        width: int,
        height: int,
        *,
        alt: bool = False,
        delay_ms: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("variant", "skeleton-alt" if alt else "skeleton")
        enable_styled_background(self)
        self.setFixedSize(width, height)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)

        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(self.DURATION_MS)
        self._animation.setStartValue(self.MIN_OPACITY)
        self._animation.setKeyValueAt(0.5, 1.0)
        self._animation.setEndValue(self.MIN_OPACITY)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._animation.setLoopCount(-1)
        self._delay_ms = delay_ms

    def start(self) -> None:
        """Animasiyanı işə salır (pilləli gecikmə ilə)."""
        self._animation.start()
        if self._delay_ms:
            # Dövrün ORTASINDAN başlamaq gecikmə effekti verir — `QTimer` ilə
            # gözləmək eyni nəticəni verərdi, lakin hər blok üçün ayrıca
            # taymer yaradardı.
            self._animation.setCurrentTime(self._delay_ms % self.DURATION_MS)

    def stop(self) -> None:
        self._animation.stop()
        self._effect.setOpacity(1.0)


# --------------------------------------------------------------------------- #
# Sıra köməkçiləri
# --------------------------------------------------------------------------- #


def row(
    *widgets: QWidget,
    spacing: int = 8,
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> QWidget:
    """Widget-ləri üfüqi sıraya yığan qab — maketdəki `display: flex` sətirləri.

    `None` ötürülməsi mümkün deyil; boşluq üçün `stretch()` işlədin.
    """
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def column(
    *widgets: QWidget,
    spacing: int = 8,
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> QWidget:
    """`row()`-un şaquli variantı."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def stretch() -> QWidget:
    """Genişlənən boşluq — maketdəki `margin-left: auto` davranışı."""
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return spacer


__all__ = [
    "Avatar",
    "Card",
    "Chip",
    "ChipTone",
    "ClickableCard",
    "Divider",
    "FilterChip",
    "LinkLabel",
    "Skeleton",
    "StatusDot",
    "body_label",
    "column",
    "mono_label",
    "muted_label",
    "row",
    "section_label",
    "stretch",
    "title_label",
]
