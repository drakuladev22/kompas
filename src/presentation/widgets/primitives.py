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

──────────────────────────────────────────────────────────────────────────────
HƏR ETİKET NİYƏ AÇIQ ŞƏKİLDƏ `PlainText`-dir
──────────────────────────────────────────────────────────────────────────────
`QLabel` defolt olaraq `Qt.AutoText` rejimindədir: mətnə baxıb onun HTML olub
olmadığını ÖZÜ qərara alır. Bu fayldakı fabrikalara isə mətn demək olar həmişə
BAZADAN gəlir — işçi adı, cərimə səbəbi, mağaza adı, dəstək mesajı. Belə bir
sətrə `<b>` və ya `<img src=...>` yazılsa, o, ekranda RENDER olunardı: yəni
istifadəçi məzmunu interfeysin görünüşünü idarə edərdi.

Layihədə QƏSDƏN yazılmış zəngin mətn HEÇ BİR ekranda yoxdur (bütün vurğular
QSS və `QFont` ilə verilir), ona görə rejimin açıq şəkildə `PlainText`-ə
sabitlənməsi görünüşü DƏYİŞMİR — yalnız qərarı Qt-nin təxminindən alıb kodun
öhdəsinə verir. Tooltip isə `QWidget` səviyyəsindədir və bu ayara TABE
DEYİL — onun üçün `safe_text.plain_tooltip()` var.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
)
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
from src.presentation.widgets.safe_text import plain_tooltip

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent, QMouseEvent

#: Nişan tonları — QSS-dəki `QLabel[chip="…"]` seçiciləri ilə eynidir.
ChipTone = Literal["success", "warning", "danger", "info", "neutral"]

#: Klaviatura ilə "klik" sayılan düymələr.
#:
#: ──────────────────────────────────────────────────────────────────────────
#: NİYƏ HƏM `Enter`, HƏM `Space`
#: ──────────────────────────────────────────────────────────────────────────
#: WAI-ARIA konvensiyası ikisini fərqli elementlərə bağlayır: `button` rolu
#: hər ikisini, `link` rolu isə yalnız `Enter`-i qəbul edir. Buradakı
#: elementlər (`FilterChip`, `LinkLabel`, klik edilə bilən kart və sətirlər)
#: vizual olaraq link kimi görünsə də ƏMƏLİYYAT icra edir — panel açır,
#: süzgəc tətbiq edir — yəni funksional olaraq düymədir. Ona görə hər iki
#: düymə qəbul olunur: istifadəçi hansını gözləyirsə, o işləyir.
#:
#: `Qt.Key_Enter` `Qt.Key_Return`-dan AYRIDIR — birincisi rəqəm bloğundakı
#: Enter-dir. İkisindən birini unutmaq nəticəni klaviatura düzülüşündən asılı
#: edərdi.
ACTIVATION_KEYS: Final = frozenset(
    {
        int(Qt.Key.Key_Return),
        int(Qt.Key.Key_Enter),
        int(Qt.Key.Key_Space),
    }
)


def is_activation_key(event: QKeyEvent) -> bool:
    """Hadisə "klaviatura ilə klik" sayılırmı."""
    return event.key() in ACTIVATION_KEYS


#: Maketdəki kart kölgəsi: `0 18px 46px rgba(11,29,58,0.28)` (ekran çərçivəsi)
#: və `0 6px 16px rgba(11,29,58,0.12)` (üzən element). Qt-də `box-shadow`
#: yoxdur — `QGraphicsDropShadowEffect` işlədilir.
_SHADOW_BLUR: Final = 32
_SHADOW_OFFSET_Y: Final = 8
_SHADOW_ALPHA: Final = 46


# --------------------------------------------------------------------------- #
# Mətn rolları
# --------------------------------------------------------------------------- #


def plain_label(text: str = "", parent: QWidget | None = None) -> QLabel:
    """Rolsuz, DÜZ MƏTN rejimli `QLabel` — birbaşa `QLabel(...)` əvəzinə.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA FABRİKA
    ──────────────────────────────────────────────────────────────────────
    Yuxarıdakı rol fabrikaları (`title_label`, `muted_label`, …) mətn
    rejimini artıq özləri sabitləyir. Lakin ekranlarda ROL TƏLƏB ETMƏYƏN
    onlarla etiket var — cədvəl xanası, nişan rəqəmi, ikon yeri, boş
    yer tutucu — və onlar birbaşa `QLabel(...)` çağırırdı, yəni Qt-nin
    `AutoText` təxmini yenidən qüvvəyə minirdi.

    Qayda hər çağırış yerində `setTextFormat(...)` sətri ilə təkrarlansaydı,
    növbəti yeni etiketdə unudulardı və boşluq sükutla geri qayıdardı. Bir
    fabrika isə "düz mətn" qərarını MƏRKƏZLƏŞDİRİR: yeni kod `plain_label()`
    yazır və qorunma onunla birlikdə gəlir.

    Görünüş DƏYİŞMİR: nə obyekt adı, nə `variant` xüsusiyyəti, nə də şrift
    verilir — `QLabel(...)`-in etdiyi hər şey eynidir, yalnız mətn rejimi
    təxminə buraxılmır.
    """
    label = QLabel(text, parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def title_label(text: str, *, size: int = metrics.FONT_PAGE_TITLE) -> QLabel:
    """Səhifə/bölmə başlığı — 600 çəki (maketdə `font-weight: 600`)."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)  # bax modul başlığı
    label.setObjectName("PageTitle")
    font = label.font()
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold)
    label.setFont(font)
    return label


def muted_label(text: str, *, size: int = metrics.FONT_CAPTION) -> QLabel:
    """Solğun köməkçi mətn (`--color-text-muted`)."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)  # bax modul başlığı
    label.setProperty("variant", "muted")
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    return label


def mono_label(text: str, *, muted: bool = False, size: int = metrics.FONT_CAPTION) -> QLabel:
    """Monoaralıqlı mətn — saat, xəta kodu, `tenant_id` kimi dəyərlər üçün.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ QSS-dəki `font-family` KİFAYƏT DEYİL
    ──────────────────────────────────────────────────────────────────────
    QSS `"IBM Plex Mono", "Cascadia Mono", Consolas, monospace` verir, lakin
    sondakı `monospace` GENERİK ad-dır və Qt onu yalnız ad-uyğunlaşdırma ilə
    həll etməyə çalışır. Siyahıdakı konkret şriftlərin heç biri quraşdırılmasa
    (minimal Windows imici, konteyner, CI runner-i) nəticə PROPORSİONAL şrift
    olur — cədvəldəki rəqəm sütunları şaquli düzülməsini itirir, yəni bu
    etiketin bütün mövcudluq səbəbi yox olur.

    `setStyleHint(Monospace)` isə ad deyil, Qt-nin şrift-uyğunlaşdırma
    mühərrikinə verilən TƏLƏBDİR: ad tapılmasa sistemdəki sabit-enli şriftə
    düşür. Ona görə QSS ilə birlikdə işlədilir — QSS gözəl şrifti seçir, style
    hint isə heç biri yoxdursa nəticənin yenə sabit-enli olmasını təmin edir.
    """
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)  # bax modul başlığı
    label.setProperty("variant", "mono-muted" if muted else "mono")
    font = label.font()
    font.setPixelSize(size)
    font.setStyleHint(QFont.StyleHint.Monospace, QFont.StyleStrategy.PreferMatch)
    font.setFixedPitch(True)
    label.setFont(font)
    return label


def section_label(text: str) -> QLabel:
    """Böyük hərfli bölmə etiketi ("NAVİQASİYA", "ŞƏXSİ MƏLUMAT").

    Maketdə `text-transform: uppercase` və `letter-spacing: 0.1–0.12em` var —
    Qt Style Sheet hər ikisini dəstəkləmir, ona görə burada `QFont` ilə
    verilir və mətn Python tərəfdə böyüdülür. Şrift ailəsi QSS-dədir (mono).

    Rol sol panelə BAĞLI DEYİL: maket eyni etiketi kartların içində də
    işlədir ("Bu ayın xülasəsi", "Son giriş tarixçəsi"). Ona görə obyekt adı
    yerə görə deyil, ROLA görə verilir.
    """
    label = QLabel(az_upper(text))
    label.setTextFormat(Qt.TextFormat.PlainText)  # bax modul başlığı
    label.setObjectName("SectionLabel")
    font = label.font()
    font.setPixelSize(metrics.FONT_SECTION_LABEL)
    font.setWeight(QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, metrics.SECTION_LABEL_LETTER_SPACING)
    label.setFont(font)
    return label


def body_label(text: str, *, size: int = 14, wrap: bool = True) -> QLabel:
    """Adi gövdə mətni — boş vəziyyət izahları kimi çoxsətirli bloklar üçün."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)  # bax modul başlığı
    label.setWordWrap(wrap)
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    return label


# --------------------------------------------------------------------------- #
# Səthlər
# --------------------------------------------------------------------------- #


class Card(QFrame):
    """Ağ (tünddə `#0F1B30`) səth, 1px sərhəd — maketin əsas qabı.

    Maket üç səth pilləsi işlədir və onlar YALNIZ künc radiusu ilə fərqlənir:

        `card`   12px — səhifədəki adi kart (ən çox işlənən)
        `panel`  11px — KARTIN İÇİNDƏKİ alt-qutu
        `modal`  14px — üzən və ya mərkəzi iri səth (dəstək, lisenziya)

    Args:
        padding: Daxili boşluq. Maketdə siyahı sətri 16/20, adi kart 18-dir.
        spacing: Uşaq widget-lər arası məsafə.
        surface: Yuxarıdakı üç pillədən biri.
        shadow: Üzən elementlər (bildiriş paneli, modal) üçün kölgə.
    """

    def __init__(
        self,
        *,
        padding: int = metrics.CARD_PADDING,
        spacing: int = 12,
        surface: Literal["card", "panel", "modal"] = "card",
        shadow: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("variant", surface)

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


#: Aparıcı nişanın diametri — `metrics.STATUS_DOT_SIZE` ilə eyni ailədən.
_GLYPH_SIZE: Final = 8
#: Nişan üçün ayrılan sol boşluq (nişan + mətnə qədər nəfəs).
_GLYPH_GUTTER: Final = 18


class Chip(QLabel):
    """Yumşaq fonlu status nişanı — "Boş vəziyyət", "5 yeni", "Aktiv".

    Ton QSS-ə `chip` xüsusiyyəti ilə ötürülür; rəng cütləri `tokens.py`-da
    WCAG AA üçün kalibrlənib (bax orada "DİZAYN MAKETİ İLƏ FƏRQLƏR").

    ──────────────────────────────────────────────────────────────────────────
    APARICI NİŞAN (`dot=True`) — NİYƏ FORMA, NİYƏ TƏKCƏ RƏNG
    ──────────────────────────────────────────────────────────────────────────
    `design_reference/tasks.jpg` status çiplərini üç FƏRQLİ formada göstərir
    (dolu nöqtə / işarə / boş halqa), `design_reference/permission.jpg` isə
    birbaşa göstərişdir: «az vizual səs-küy = güclü status siqnalı».

    Bu, bəzək deyil. KompasOS-un bütün ekranları bir işçinin VƏZİYYƏTİ
    ətrafında qurulub, vəziyyət isə yalnız rənglə verilsəydi:
      * rəng korluğunda (kişilərin ~8%-i) `success` və `danger` eyni görünərdi
        — mağaza müdirlərinin çoxu kişidir;
      * ağ-qara çap edilmiş aylıq cərimə hesabatında fərq TAMAMİLƏ itərdi,
        halbuki həmin hesabat mübahisə halında sübutdur.
    Forma hər iki halda sağ qalır.

    Nişan `text()`-ə TOXUNMUR — mətnə "● " əlavə etsəydik, hər testin və hər
    `text()` müqayisəsinin gözləntisi dəyişərdi və nişan məlumat olmaqdan
    çıxıb sətrin bir hissəsinə çevrilərdi. Ona görə o, `paintEvent`-də
    çəkilir, yeri isə `contentsMargins` ilə ayrılır.

    Nişan rəngi AYRICA token DEYİL: `palette().windowText()`, yəni çipin öz
    mətn rəngi işlədilir. Beləliklə hər yeni ton avtomatik düzgün rəng alır və
    kontrast yoxlayıcısına yeni cüt əlavə olunmur (mətnlə eyni cütdür).
    """

    def __init__(
        self,
        text: str,
        tone: ChipTone = "neutral",
        *,
        dot: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)  # bax modul başlığı
        self.setProperty("chip", tone)
        self._tone: ChipTone = tone
        self._dot = dot
        font = self.font()
        font.setPixelSize(metrics.FONT_CAPTION)
        self.setFont(font)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        if dot:
            self.setContentsMargins(_GLYPH_GUTTER, 0, 0, 0)

    def set_tone(self, tone: ChipTone) -> None:
        """Tonu dəyişir və üslubu yenidən hesablatdırır.

        Qt dinamik xüsusiyyət dəyişəndə QSS-i özü yeniləmir — `unpolish`/
        `polish` olmadan nişan köhnə rəngdə qalardı.
        """
        self.setProperty("chip", tone)
        self._tone = tone
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        super().paintEvent(event)
        if not self._dot:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().windowText().color()
        left = (_GLYPH_GUTTER - _GLYPH_SIZE) // 2
        top = (self.height() - _GLYPH_SIZE) // 2
        box = QRectF(left, top, _GLYPH_SIZE, _GLYPH_SIZE)

        if self._tone == "success":
            # İŞARƏ: "tamamlandı" bitmiş bir hərəkətdir — nöqtə isə davam edən
            # vəziyyəti bildirir. İkisini eyni formada göstərmək «təsdiqləndi»
            # ilə «gözləyir» arasındakı fərqi silərdi.
            pen = QPen(color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(box.left(), box.center().y())
            path.lineTo(box.center().x() - 0.5, box.bottom() - 1.0)
            path.lineTo(box.right(), box.top())
            painter.drawPath(path)
        elif self._tone == "warning":
            # BOŞ HALQA: "hələ tamamlanmayıb" — daxili boşluq gözlə də
            # "içi dolmayıb" kimi oxunur.
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(box.adjusted(0.75, 0.75, -0.75, -0.75))
        elif self._tone == "danger":
            # ROMB: dairədən kəskin fərqlənən yeganə sadə forma; 8px-də belə
            # "xəbərdarlıq" kimi oxunur (yol nişanları ilə eyni məntiq).
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            diamond = QPolygonF(
                [
                    QPointF(box.center().x(), box.top()),
                    QPointF(box.right(), box.center().y()),
                    QPointF(box.center().x(), box.bottom()),
                    QPointF(box.left(), box.center().y()),
                ]
            )
            painter.drawPolygon(diamond)
        else:
            # DOLU NÖQTƏ: davam edən/neytral vəziyyət (`info`, `neutral`).
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(box)
        painter.end()


class FilterChip(Chip):
    """Klik edilə bilən nişan — süzgəc zolaqlarında işlədilir.

    Ayrı sinif kimi mövcuddur, çünki `QLabel`-in `mousePressEvent`-ini
    kənardan `lambda` ilə əvəz etmək (`chip.mousePressEvent = ...`) işləyir,
    lakin tip yoxlayıcısı üçün görünməzdir və hadisə imzası səhv yazılsa
    yalnız icra zamanı üzə çıxardı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `_activate()` ADLI ORTAQ METOD VAR
    ──────────────────────────────────────────────────────────────────────────
    Siçan və klaviatura EYNİ əməliyyatı işə salmalıdır. Siqnalı hər iki hadisə
    idarəedicisində ayrıca `emit` etsəydik, sonradan biri dəyişəndə (məs.
    ikiqat göndərmə qoruması əlavə olunanda) digəri arxada qalardı və qüsur
    yalnız klaviatura ilə üzə çıxardı — yəni ən az test edilən yolda.
    Ona görə hər iki idarəedici bir metoda gedir.

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
        # `QLabel` defolt olaraq `NoFocus`-dur — süzgəc zolağı klaviatura ilə
        # tamamilə keçilməz idi. Fokus halqası QSS-dədir (`QLabel[chip=…]:focus`).
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _activate(self) -> None:
        self.clicked.emit(self.key)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self._activate()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt adlandırması
        if is_activation_key(event):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)


class LinkLabel(QLabel):
    """Mətn şəklində hərəkət — "Hamısını oxunmuş et", "Bütün bildirişlərə bax".

    Siçan və klaviatura yolu `_activate()`-də birləşir — səbəbi `FilterChip`
    başlığında izah olunub.

    Signals:
        clicked: Klik.
    """

    clicked = Signal()

    def __init__(self, text: str, *, size: int = 13, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)  # bax modul başlığı
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # `variant="link"` yalnız fokus halqasının yerini ayırır — rəngə
        # toxunmur, ona görə mövcud ekranların görünüşü dəyişmir (bax `qss.py`).
        self.setProperty("variant", "link")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Ekran oxuyucusu üçün rol: mətn etiketi deyil, HƏRƏKƏTdir.
        self.setAccessibleName(text)
        font = self.font()
        font.setPixelSize(size)
        self.setFont(font)

    def _activate(self) -> None:
        self.clicked.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self._activate()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt adlandırması
        if is_activation_key(event):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)


class ClickableCard(Card):
    """Bütövlükdə seçilə bilən kart — siyahı sətirlərində (növbə dəyişmə).

    Siçan və klaviatura yolu `_activate()`-də birləşir — səbəbi `FilterChip`
    başlığında izah olunub.

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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _activate(self) -> None:
        self.clicked.emit(self.key)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self._activate()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt adlandırması
        if is_activation_key(event):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)


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

        Ad tooltip-ə `plain_tooltip()` ilə düşür: tooltip `setTextFormat`-a
        tabe deyil, yəni bazadakı "Rəşad <img src=...>" sətri burada işarə
        kimi şərh olunardı (bax `safe_text.py`).
        """
        self._initials = self._compute_initials(full_name)
        self.setToolTip(plain_tooltip(full_name))
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
    "ACTIVATION_KEYS",
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
    "is_activation_key",
    "mono_label",
    "muted_label",
    "plain_label",
    "row",
    "section_label",
    "stretch",
    "title_label",
]
