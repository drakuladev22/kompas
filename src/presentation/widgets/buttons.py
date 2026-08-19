"""Düymə variantları — Faza 4.2.

Maketdə dörd fərqli düymə rolu var və onlar QSS-də `variant` xüsusiyyəti ilə
seçilir (bax `theme/qss.py`):

    action     — əsas hərəkət. İşıqlı rejimdə Navy, tünddə Amber.
    secondary  — ikinci dərəcəli. Ağ səth + boz sərhəd.
    icon       — 34×34 kvadrat, header-dəki tema/zəng düymələri.
    nav        — sol paneldəki 40px sətir; aktiv halda dolu fon.
    window     — pəncərə başlığındakı —/□/× .

──────────────────────────────────────────────────────────────────────────────
İKON RƏNGİ NİYƏ QSS-DƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Qt `QIcon`-un rəngini QSS ilə dəyişə bilmir — ikon hazır piksel şəklidir.
Maketdə isə aktiv naviqasiya ikonu amber, passiv ikon bozdur. Ona görə
`NavButton` vəziyyət dəyişəndə ikonu YENİDƏN ÇƏKİR (`icons.render`), rəngi
konstruktorda verilən cütdən götürərək.

──────────────────────────────────────────────────────────────────────────────
KLAVİATURA-YALNIZ FOKUS HALQASI (`KeyFocusRingMixin`) `focus_ring.py`-A KÖÇDÜ
──────────────────────────────────────────────────────────────────────────────
D11 (dövrə 2/3 audit): mixin əvvəl BURADA yaşayırdı, indi `primitives.py`
(`FilterChip`, `LinkLabel`, `ClickableCard`), `data_table.py` (`TableRow`)
və `screens/group_g.py` (`NotificationItem`) tərəfindən DƏ işlədilir.
Bu fayl `primitives.py`-dan idxal etdiyi üçün (`plain_label`) mixin buraya
qala bilməzdi — dövri idxal yaranardı. Bax `focus_ring.py` modul başlığı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from src.presentation.theme.manager import refresh_widget_style
from src.presentation.theme.tokens import ThemeMode, theme_tokens
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.focus_ring import KeyFocusRingMixin
from src.presentation.widgets.primitives import plain_label
from src.presentation.widgets.safe_text import plain_tooltip

if TYPE_CHECKING:
    from PySide6.QtGui import QEnterEvent, QResizeEvent


def _apply_font(button: QPushButton, *, size: int, weight: QFont.Weight) -> None:
    font = button.font()
    font.setPixelSize(size)
    font.setWeight(weight)
    button.setFont(font)


def action_button(
    text: str,
    *,
    icon_name: str | None = None,
    icon_color: str | None = None,
    parent: QWidget | None = None,
) -> QPushButton:
    """Əsas hərəkət düyməsi — "Yeni Cərimə", "Yenidən Cəhd Et".

    Args:
        icon_name: Soldakı ikon (maketdə `+`, `refresh` və s.).
        icon_color: İkonun rəngi — adətən `--color-action-text`.

    Qaytarılan tip `QPushButton` OLARAQ QALIR (`_KeyFocusRingButton` onun alt
    sinfidir, `isinstance` keçir) — FOCUS-1/D11: halqa YALNIZ klaviatura
    modallığında görünür (bax `_KeyFocusRingButton`, `qss.py`-dəki
    `[variant="action"][keyfocus="true"]`).
    """
    button = _KeyFocusRingButton(text, parent)
    button.setProperty("variant", "action")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    _apply_font(button, size=14, weight=QFont.Weight.DemiBold)
    button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    if icon_name is not None and icon_color is not None:
        button.setIcon(icons.icon(icon_name, icon_color, size=15, stroke_width=1.6))
        button.setIconSize(QSize(15, 15))
    return button


def secondary_button(text: str, *, parent: QWidget | None = None) -> QPushButton:
    """İkinci dərəcəli düymə — "Keçən aya bax", "Dəstəyə yaz".

    FOCUS-1/D11: bax `action_button` başlığı — eyni izah.
    """
    button = _KeyFocusRingButton(text, parent)
    button.setProperty("variant", "secondary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    _apply_font(button, size=14, weight=QFont.Weight.Normal)
    button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return button


def icon_button(
    icon_name: str,
    color: str,
    *,
    tooltip: str = "",
    accessible_name: str = "",
    accessible_description: str = "",
    checkable: bool = False,
    parent: QWidget | None = None,
) -> QPushButton:
    """Header-dəki 34×34 ikon düyməsi (tema keçidi, bildiriş zəngi).

    ──────────────────────────────────────────────────────────────────────────
    `setToolTip` EKRAN OXUYUCUSU ÜÇÜN AD DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Qt bir düymənin əlçatan adını hesablayarkən əvvəlcə `accessibleName()`-ə,
    o boşdursa `text()`-ə baxır. Bu fabrika MƏTNSİZ düymə qaytarır (yalnız
    ikon), yəni hər iki mənbə boşdur və Narrator/NVDA düyməni sadəcə "düymə"
    kimi elan edir. `toolTip` bu zəncirdə YOXDUR — o, siçan üçün nəzərdə
    tutulub və klaviatura ilə gəzən istifadəçiyə heç vaxt oxunmur.

    Ona görə ad AYRICA verilir. `tooltip` ilə eyni sətir olsa belə, ikisi bir
    parametrə birləşdirilmir: tooltip qısa göstərişdir ("Görünüşü dəyiş"),
    əlçatan ad isə elementin NƏ OLDUĞUNU deməlidir ("Tema keçidi düyməsi") —
    ekran oxuyucusu onu kontekstsiz, tək başına oxuyur.

    Args:
        accessible_name: Ekran oxuyucusunun elan edəcəyi ad (Azərbaycanca).
            Boş buraxılarsa `tooltip` mətninə düşür — çünki adsız qalmaqdansa
            təxmini ad yaxşıdır; lakin YALNIZ-İKON düymələr üçün açıq ad
            MƏCBURİDİR (`test_icon_buttons_have_accessible_names` qapısı).
        accessible_description: Əlavə izah — nəticə dərhal aydın deyilsə.
    """
    button = QPushButton(parent)
    button.setProperty("variant", "icon")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setIcon(icons.icon(icon_name, color))
    button.setIconSize(QSize(icons.DEFAULT_SIZE, icons.DEFAULT_SIZE))
    button.setFixedSize(metrics.HEADER_ICON_BUTTON, metrics.HEADER_ICON_BUTTON)
    button.setCheckable(checkable)
    if tooltip:
        # Tooltip `setTextFormat`-a tabe deyil və Qt onu avtomatik olaraq
        # zəngin mətn saya bilər. Mətn hazırda sabit sətirlərdən gəlir, lakin
        # fabrika hər çağırana açıqdır — qorunma çağırış yerində deyil, BURADA
        # (bax `safe_text.py`).
        button.setToolTip(plain_tooltip(tooltip))
    button.setAccessibleName(accessible_name or tooltip)
    if accessible_description:
        button.setAccessibleDescription(accessible_description)
    return button


#: Nişanda göstərilən ən böyük dəqiq rəqəm — üstü «99+» olur.
#:
#: ROOT PARAMETRİ DEYİL: bu, siyasət deyil, 64px-lik nişan sahəsinin
#: ölçüsüdür — üç rəqəmli dəyər menyu mətninin üstünə çıxır.
MAX_BADGE_COUNT = 99


class NavButton(QPushButton):
    """Sol paneldəki naviqasiya sətri — 40px, ikon + mətn, aktiv vəziyyət.

    Aktiv halda maket DOLU fon göstərir (sol kənar xətti deyil) və ikonu
    amber rəngə çevirir — hər ikisi `set_active()` içində tətbiq olunur.

    ──────────────────────────────────────────────────────────────────────────
    TOOLTIP NİYƏ KONSTRUKTORDA QURULUR
    ──────────────────────────────────────────────────────────────────────────
    İki AYRI səbəb eyni bir sətirdə birləşir:

    1. KƏSİLƏN MƏTN OXUNA BİLƏN QALIR. Sol panel sabit enlidir
       (`metrics.SIDEBAR_WIDTH`) və uzun maddə (məsələn «Ehtiyat Nüsxə və
       Bərpa») Qt tərəfindən «…» ilə kəsilir. Tooltip olmasa, istifadəçi
       maddənin tam adını NƏ görə, NƏ də siçanla oxuya bilərdi — yeganə yol
       ekran oxuyucusu qalırdı.

    2. `set_compact()` MƏTNİ TOOLTIP-DƏ SAXLAYIR. O metod daraldılmış paneldə
       `setText("")` edir və mətni geri qaytarmaq üçün `toolTip()`-dən oxuyur.
       Tooltip boş olsaydı, dövrə belə pozulardı:
           set_compact(True)  → text="", tooltip=""      (mətn İTİR)
           set_compact(False) → text=toolTip() or text() = ""  (geri gəlmir)
       Yəni panel bir dəfə yığılıb açıldıqdan sonra bütün maddələr ADSIZ
       qalırdı. Tooltip-i başlanğıcda doldurmaq həm bu dövrəni bağlayır, həm
       də (1)-i həll edir — ona görə ayrıca saxlama sahəsi əlavə edilmir.
    """

    def __init__(
        self,
        key: str,
        text: str,
        *,
        icon_name: str,
        idle_color: str,
        active_color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.key = key
        self._icon_name = icon_name
        self._idle_color = idle_color
        self._active_color = active_color
        self._active = False

        self.setProperty("variant", "nav")
        # Başlanğıc dəyər AÇIQ yazılır: Qt təyin olunmamış dinamik xüsusiyyəti
        # `[compact="false"]` kimi saymır (eyni səbəb `WindowButton`-dakı
        # `keyfocus`-da). Yazılmasa, ilk `set_compact(False)` çağırışına qədər
        # seçici heç bir vəziyyətlə uyğun gəlmir.
        self.setProperty("compact", "false")
        self.setProperty("active", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        # Ad KONSTRUKTORDA sabitlənir, `text()`-dən oxunmur: `set_compact()`
        # daraldılmış paneldə mətni SİLİR (yalnız ikon qalır) və o andan
        # etibarən Qt-nin avtomatik adı boş olardı — yəni sol panel məhz
        # daraldıldıqda ekran oxuyucusu üçün yararsız hala düşərdi.
        self.setAccessibleName(text)
        # Sinif başlığındakı iki səbəb. `plain_tooltip()` — mətn Root-un
        # yaratdığı menyu maddəsindən gələ bilər, Qt isə `<b>` kimi parçanı
        # zəngin mətn kimi render edərdi (bax `safe_text.py`).
        self.setToolTip(plain_tooltip(text))
        self.setFixedHeight(metrics.NAV_ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _apply_font(self, size=metrics.FONT_NAV_ITEM, weight=QFont.Weight.Normal)

        self.setIconSize(QSize(icons.DEFAULT_SIZE, icons.DEFAULT_SIZE))
        self._refresh_icon()

        # Sayğac düymənin ÜSTÜNDƏ üzür (layout-da yer tutmur): `QPushButton`
        # mətn + ikon üçün öz daxili tərtibatını qurur və ora üçüncü element
        # əlavə etmək mətnin kəsilmə nöqtəsini dəyişərdi.
        # `plain_label` — xam Qt etiketi YOX: mətn rejimi (`PlainText`) bir
        # yerdə mərkəzləşdirilib (`primitives.py`) və sayğac rəqəmi də ondan
        # kənarda qalmamalıdır. Qayda `test_security_hardening.py::
        # test_no_screen_creates_a_bare_qlabel` ilə bağlanıb — həmin qapı
        # MƏNBƏ MƏTNİNİ oxuyur, yəni şərhdə də xam sinif adı yazılmır.
        self._badge = plain_label(parent=self)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setVisible(False)
        self._badge_count = 0
        self._apply_badge_style()

    # -------------------------------- sayğac -------------------------------- #

    def set_badge(self, count: int) -> None:
        """Oxunmamış sayını göstərir. `0` → nişan gizlənir.

        99-dan çoxu «99+» kimi göstərilir: üç rəqəmli nişan menyu mətninin
        üstünə çıxardı və «Performans Qiymətləndirmələri» kimi uzun başlıq
        artıq kəsilmiş vəziyyətdədir.
        """
        self._badge_count = max(0, count)
        if self._badge_count == 0:
            self._badge.setVisible(False)
            return
        self._badge.setText(
            f"{MAX_BADGE_COUNT}+" if self._badge_count > MAX_BADGE_COUNT else str(self._badge_count)
        )
        self._badge.adjustSize()
        self._badge.setVisible(True)
        self._position_badge()

    def badge_count(self) -> int:
        """Testlər və örtük üçün — hazırkı say."""
        return self._badge_count

    def _apply_badge_style(self) -> None:
        # Amber fon + navy mətn — `PageHeader` bildiriş nişanı ilə EYNİ cüt.
        # İkinci rəng cütü yaratmaq eyni mənanı iki fərqli rənglə göstərərdi.
        #
        # `ThemeMode.LIGHT`-dan oxunur, çünki BRAND rəngləri hər iki temada
        # eynidir (`tokens.py`: `BRAND_NAVY`/`BRAND_AMBER` sabitləri) — tema
        # dəyişəndə nişanı yenidən rəngləməyə ehtiyac yoxdur.
        palette = theme_tokens(ThemeMode.LIGHT)
        self._badge.setStyleSheet(
            f"background-color: {palette['--color-brand-amber']};"
            f"color: {palette['--color-brand-navy']};"
            "border-radius: 8px; padding: 0 5px; font-size: 10px; font-weight: 600;"
        )
        self._badge.setMinimumSize(16, 16)

    def _position_badge(self) -> None:
        margin = 12
        self._badge.move(
            max(0, self.width() - self._badge.width() - margin),
            (self.height() - self._badge.height()) // 2,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        if self._badge.isVisible():
            self._position_badge()

    # ------------------------------- vəziyyət ------------------------------- #

    @property
    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        """Aktiv vəziyyəti dəyişir — fon, mətn çəkisi və ikon rəngi birlikdə."""
        if active == self._active:
            return
        self._active = active
        self.setChecked(active)
        self.setProperty("active", "true" if active else "false")
        _apply_font(
            self,
            size=metrics.FONT_NAV_ITEM,
            weight=QFont.Weight.DemiBold if active else QFont.Weight.Normal,
        )
        self._refresh_icon()
        refresh_widget_style(self)

    def set_colors(self, *, idle_color: str, active_color: str) -> None:
        """Tema dəyişdikdə çağırılır — ikon yenidən çəkilir."""
        self._idle_color = idle_color
        self._active_color = active_color
        self._refresh_icon()

    def set_compact(self, compact: bool) -> None:
        """Daraldılmış paneldə yalnız ikon göstərilir (mətn tooltip-də qalır).

        Tooltip HƏM açıq, HƏM yığılmış vəziyyətdə eyni mətni saxlayır — o,
        həm kəsilən başlığın oxunma yolu, həm də `setText("")`-dən sonra
        mətnin yeganə mənbəyidir (bax sinif başlığı).
        """
        self.setText("" if compact else self.toolTip() or self.text())
        self.setToolTip(self.text() if not compact else self.toolTip())
        # ──────────────────────────────────────────────────────────────────
        # DARALDILMIŞ REJİMDƏ İKON MƏRKƏZDƏ OLUR
        # ──────────────────────────────────────────────────────────────────
        # `variant="nav"` QSS-də `text-align: left` və `padding: 0 16px`
        # daşıyır — açıq paneldə düzgündür, çünki mətn ikonun ardından gəlir
        # və hamısı bir şaquli xətdən başlayır. Daraldılmış paneldə isə mətn
        # YOXDUR: eyni sol padding ikonu 64px-lik zolağın sol yarısına
        # sıxışdırırdı və ikonlar mərkəz oxundan sürüşürdü (navbar.jpg-də
        # daraldılmış zolaqda ikonlar TAM mərkəzdədir).
        #
        # `variant` dəyişdirilmir — rəng/fon/aktiv vəziyyət qaydaları eyni
        # qalmalıdır. Yalnız `compact` xüsusiyyəti qoyulur və QSS onu
        # mərkəzləmə üçün oxuyur.
        self.setProperty("compact", "true" if compact else "false")
        # Daraldılmış paneldə nişan ikonun sağ-üst küncünə sıxılır: mətn
        # yoxdur, yəni sağ kənarda 12px boşluq da yoxdur.
        if self._badge_count:
            self._position_badge()
        refresh_widget_style(self)

    def _refresh_icon(self) -> None:
        color = self._active_color if self._active else self._idle_color
        self.setIcon(icons.icon(self._icon_name, color, device_pixel_ratio=self._dpr()))

    def _dpr(self) -> float:
        window = self.window()
        handle = window.windowHandle() if window is not None else None
        return handle.devicePixelRatio() if handle is not None else 1.0


class KeyFocusIconButton(KeyFocusRingMixin, QPushButton):
    """Halqası YALNIZ klaviatura fokusunda çıxan ikon düyməsi.

    `icon_button()` fabrikasından fərqi budur. İki yerdə işlənir və ikisində
    də səbəb eynidir: həmin düymə öz səthinin İLK fokus ala bilən elementidir,
    yəni pəncərə açılanda fokusu O alır (bax mixin izahı).

        * başlıq zolağı — tema keçidi;
        * sol panel — aç/bağla düyməsi.

    Səhifə başlığındakı ikon düymələri bu sinifdən İSTİFADƏ ETMİR: onlar
    məzmun sahəsindədir və ilk fokusu heç vaxt almır, ona görə adi `:focus`
    halqası orada düzgün davranışdır.

    Ölçü VERİLƏNDƏN gəlir: başlıq zolağında pəncərə düymələri ilə eyni
    olmalıdır (navbar.md PROBLEM 3 bənd 3), sol paneldə isə naviqasiya
    sətrindən kiçik.
    """

    def __init__(
        self,
        icon_name: str,
        color: str,
        *,
        tooltip: str = "",
        accessible_name: str = "",
        accessible_description: str = "",
        width: int = metrics.HEADER_ICON_BUTTON,
        height: int = metrics.HEADER_ICON_BUTTON,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("variant", "icon")
        # Başlanğıc dəyər AÇIQ yazılır: Qt təyin olunmamış dinamik xüsusiyyəti
        # `[keyfocus="false"]` kimi saymır (eyni səbəb `WindowButton`-da).
        self.setProperty("keyfocus", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icons.icon(icon_name, color))
        self.setIconSize(QSize(icons.DEFAULT_SIZE, icons.DEFAULT_SIZE))
        self.setFixedSize(width, height)
        # QSS-in `min/max` qaydası Qt-də `setFixedSize()`-i üstələyə bilir
        # (bax `qss.py`-dakı izah). Sərt siyasət ölçünü layout tərəfindən də
        # kilidləyir — əks halda düymə ikonun `sizeHint`-inə yığılırdı.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # `TabFocus` — səbəb `WindowButton`-dakı ilə eynidir: siçanla klikləmək
        # halqa qoymamalıdır, klaviatura yolu isə açıq qalmalıdır.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if tooltip:
            self.setToolTip(plain_tooltip(tooltip))
        self.setAccessibleName(accessible_name or tooltip)
        if accessible_description:
            self.setAccessibleDescription(accessible_description)


class _KeyFocusRingButton(KeyFocusRingMixin, QPushButton):
    """`QPushButton` + fokus halqası YALNIZ klaviatura modallığında (FOCUS-1/D11).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ YENİ SİNİF, `KeyFocusIconButton`-UN ÖZÜ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    `KeyFocusIconButton` ikon-only, sabit-ölçülü düymələr üçündür (başlıq
    zolağı/sol panel) — konstruktoru `icon_name`, `width`/`height` kimi bu
    kontekstə xas arqumentlər tələb edir. `action_button()`/`secondary_button()`
    isə mətn, opsional ikon, DƏYİŞKƏN ölçü qəbul edir — həmin konstruktoru
    məcburi işlətmək tamamilə əlaqəsiz parametrlər tələb edərdi. Bu sinif
    YALNIZ mixin-in verdiyi `[keyfocus]` davranışını əlavə edir; qalan hər
    şeyi (`variant`, ölçü, kursor, ikon) çağıran fabrik funksiyası
    (`action_button`/`secondary_button`) əvvəlki kimi ÖZÜ təyin edir —
    paralel iyerarxiya YOX, TƏK əlavə qat.

    `isinstance(x, QPushButton)` HƏMİŞƏ `True`-dur (birbaşa varis) — çağıran
    kodun heç biri (`.clicked.connect(...)`, `QPushButton` tipli sahələr)
    dəyişməli DEYİL.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        # Başlanğıc dəyər AÇIQ yazılır — eyni səbəb `KeyFocusIconButton`-da.
        self.setProperty("keyfocus", "false")


class WindowButton(KeyFocusRingMixin, QPushButton):
    """Pəncərə başlığındakı kiçilt / böyüt–bərpa / bağla düymələri.

    ──────────────────────────────────────────────────────────────────────────
    SİMVOLDAN İKONA KEÇİD
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl düymələr MƏTN idi (`—`, `□`, `×`). Üç problemi vardı:

    1. Ölçü şriftdən asılı idi — `□` bəzi şriftlərdə kvadrat, bəzilərində
       düzbucaqlı, bəzilərində isə ümumiyyətlə "tofu" (□ əvəzedicisi) kimi
       çıxırdı. Nəticə maşından maşına dəyişirdi.
    2. Windows konvensiyasındakı BƏRPA nişanı (iki üst-üstə düşən kvadrat)
       üçün ümumi işlənən Unicode simvolu yoxdur — yəni maksimallaşdırılmış
       pəncərədə düymə HƏMİŞƏ "böyüt" göstərirdi, halbuki basanda bərpa edirdi.
    3. `—` və `×` interfeys şriftinin metrikasına görə fərqli optik çəkidə
       görünürdü.

    İndi hər üçü `icons.py`-dan gələn SVG-dir: eyni şəbəkə, eyni qalınlıq,
    şriftdən asılı deyil və `set_maximized()` nişanı əsl bərpa formasına
    çevirir.

    ──────────────────────────────────────────────────────────────────────────
    RƏNG NİYƏ QSS-DƏN DEYİL, PYTHON-DAN GƏLİR
    ──────────────────────────────────────────────────────────────────────────
    `QIcon` hazır piksel şəklidir — QSS-in `color:` qaydası ona TƏSİR ETMİR
    (bax modul başlığı, `NavButton` ilə eyni səbəb). Ona görə hover vəziyyəti
    burada izlənir və ikon yenidən çəkilir. QSS-dəki `color:` qaydası isə
    silinmir: o, mətn ehtiyatı üçün lazımdır (aşağıda `GLYPHS`).
    """

    #: Maketdəki simvollar — İNDİ EHTİYAT YOLDUR.
    #:
    #: NİYƏ SAXLANILIR: pəncərə çərçivəsizdir, yəni Windows-un öz sistem
    #: menyusu yoxdur və bu üç düymə tətbiqi bağlamağın/kiçiltməyin yeganə
    #: SİÇAN yoludur. İkon dəsti gələcəkdə yenidən adlandırılsa
    #: (`icons.IconNotFoundError`), düymə tamamilə BOŞ qalardı — istifadəçi
    #: 46×38px görünməz kvadrata basmalı olardı. Simvol həmin halda ən azı
    #: nəyin harada olduğunu göstərir.
    GLYPHS: ClassVar[dict[str, str]] = {
        "minimize": "—",
        "maximize": "□",
        "close": "×",
    }

    #: Əməliyyat → ikon adı (`icons.py`). `maximize` iki nişan daşıyır, ona
    #: görə cütdür: (normal hal, maksimallaşdırılmış hal).
    ICON_NAMES: ClassVar[dict[str, tuple[str, str]]] = {
        "minimize": ("window_minimize", "window_minimize"),
        "maximize": ("window_maximize", "window_restore"),
        "close": ("window_close", "window_close"),
    }

    #: Ekran oxuyucusunun elan edəcəyi adlar. Simvolun ÖZÜ ad ola bilməz:
    #: `—`, `□`, `×` oxunanda "tire", "kvadrat", "vur" kimi səslənir və
    #: istifadəçi düymənin nə etdiyini bilmir. İkona keçiddən sonra bu daha da
    #: vacibdir: ikonun heç bir mətni yoxdur.
    ACCESSIBLE_NAMES: ClassVar[dict[str, str]] = {
        "minimize": "Pəncərəni kiçilt",
        "maximize": "Pəncərəni böyüt və ya bərpa et",
        "close": "Pəncərəni bağla",
    }

    #: Maksimallaşdırılmış halda "böyüt" düyməsinin adı DƏYİŞİR — ekran
    #: oxuyucusu istifadəçiyə basdıqda NƏ olacağını deməlidir.
    MAXIMIZED_NAME: ClassVar[str] = "Pəncərəni əvvəlki ölçüsünə qaytar"

    #: İkon ölçüsü — 46×38px düymənin içində Windows-un öz nisbətinə yaxın.
    ICON_SIZE: ClassVar[int] = 16
    #: Xətt qalınlığı: dəstin standartı (1.5) bu ölçüdə bir az ağır görünür.
    ICON_STROKE: ClassVar[float] = 1.3

    def __init__(
        self,
        action: str,
        *,
        idle_color: str | None = None,
        hover_color: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Args:
        action: `minimize` / `maximize` / `close`.
        idle_color: İkonun adi rəngi. `None` → işıqlı temanın tokeni.
            Rəng KONSTRUKTORDA icbari deyil, çünki `TitleBar()` tema
            obyekti olmadan da qurula bilir (testlər, dizayn önizləməsi);
            canlı tətbiqdə `apply_theme()` onu dərhal üstələyir.
        hover_color: Kursor üstündə olduqda. `close` üçün bu, qırmızı
            fonun üzərindəki rəngdir (bax `qss.py`).
        """
        if action not in self.ICON_NAMES:
            raise ValueError(f"Naməlum pəncərə əməliyyatı: {action!r}")
        super().__init__(parent)
        self._action = action
        self._maximized = False
        self._hovered = False
        light = theme_tokens(ThemeMode.LIGHT)
        self._idle_color = idle_color or light["--color-titlebar-control"]
        self._hover_color = hover_color or (
            light["--color-bg-primary"] if action == "close" else light["--color-titlebar-text"]
        )

        self.setProperty("variant", "window")
        self.setProperty("action", action)
        self.setProperty("hover", "false")
        # Fokus halqası KLAVİATURA fokusuna bağlıdır — səbəbi
        # `focusInEvent`-dədir. Başlanğıc dəyər açıq yazılır ki, QSS
        # selektoru ilk kadrda da uyğun gəlsin (Qt təyin olunmamış dinamik
        # xüsusiyyəti `[keyfocus="false"]` kimi saymır).
        self.setProperty("keyfocus", "false")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFixedSize(metrics.WINDOW_BUTTON_WIDTH, metrics.TITLEBAR_HEIGHT)
        self.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
        # ──────────────────────────────────────────────────────────────────
        # NİYƏ `TabFocus`, NƏ `NoFocus`, NƏ DƏ `StrongFocus`
        # ──────────────────────────────────────────────────────────────────
        # Pəncərə çərçivəsizdir, yəni Windows-un öz sistem menyusu (Alt+Boşluq)
        # yoxdur: bu üç düymə bağlamağın/kiçiltmənin YEGANƏ yoludur. `NoFocus`
        # onları klaviatura üçün tamamilə əlçatmaz edirdi — siçansız istifadəçi
        # pəncərəni yalnız Alt+F4 ilə bağlaya bilərdi, kiçildə isə heç cür.
        #
        # `StrongFocus` isə siçanla klikləyəndə də fokus halqası çəkərdi və
        # başlıq zolağında hər klikdən sonra halqa qalardı — masaüstü
        # konvensiyasına ziddir. `TabFocus` yalnız klaviatura ilə fokus verir:
        # siçan davranışı HEÇ DƏYİŞMİR, klaviatura yolu isə açılır.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(self.ACCESSIBLE_NAMES[action])
        _apply_font(self, size=13, weight=QFont.Weight.Normal)
        self._refresh_icon()

    # ------------------------------- vəziyyət ------------------------------- #

    @property
    def action(self) -> str:
        return self._action

    @property
    def is_maximized(self) -> bool:
        return self._maximized

    def icon_name(self) -> str:
        """Hazırda göstərilən ikonun adı — testlər və audit üçün."""
        normal, maximized = self.ICON_NAMES[self._action]
        return maximized if self._maximized else normal

    def set_maximized(self, maximized: bool) -> None:
        """Pəncərə vəziyyəti dəyişdi — nişan böyüt ↔ bərpa arasında keçir.

        Yalnız `maximize` düyməsində görünən təsiri var; digər ikisində
        çağırış zərərsizdir, ona görə çağıran tərəf tip yoxlaması etmir.
        """
        if maximized == self._maximized:
            return
        self._maximized = maximized
        if self._action == "maximize":
            self.setAccessibleName(
                self.MAXIMIZED_NAME if maximized else self.ACCESSIBLE_NAMES["maximize"]
            )
        self._refresh_icon()

    def set_colors(self, *, idle_color: str, hover_color: str) -> None:
        """Tema dəyişdikdə çağırılır — ikon yenidən çəkilir (bax `NavButton`)."""
        self._idle_color = idle_color
        self._hover_color = hover_color
        self._refresh_icon()

    # -------------------------------- hover ---------------------------------- #

    def set_hovered(self, hovered: bool) -> None:
        """Hover görünüşünü təyin edir — İKİ mənbədən çağırılır.

        Adi halda `enterEvent`/`leaveEvent`. Lakin Windows-un Snap Layouts
        rejimində "böyüt" düyməsi QEYRİ-MÜŞTƏRİ sahəyə çevrilir
        (`WM_NCHITTEST` → `HTMAXBUTTON`) və Qt həmin sahəyə heç bir siçan
        hadisəsi göndərmir — hover ORADAN, `WM_NCMOUSEMOVE`-dan gəlir
        (bax `shell/native_chrome.py`).

        `hover` DİNAMİK XÜSUSİYYƏTİ ona görə lazımdır: QSS-in `:hover`
        psevdo-sinfi Qt-nin öz siçan izləməsinə bağlıdır və native halda heç
        vaxt işə düşməzdi — yəni fon dəyişməz, yalnız ikon dəyişərdi.
        """
        if hovered == self._hovered:
            return
        self._hovered = hovered
        self.setProperty("hover", "true" if hovered else "false")
        refresh_widget_style(self)
        self._refresh_icon()

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt adlandırması
        self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt adlandırması
        self.set_hovered(False)
        super().leaveEvent(event)

    # -------------------------------- fokus ---------------------------------- #
    #
    # Halqa məntiqi `KeyFocusRingMixin`-dədir — başlıq zolağındakı tema
    # düyməsi ilə ORTAQdır. Əvvəl nüsxə burada idi; ikinci istifadəçi
    # yarananda köçürmək əvəzinə ortaq bazaya çıxarıldı.

    # -------------------------------- çəkmə ---------------------------------- #

    def _refresh_icon(self) -> None:
        color = self._hover_color if self._hovered else self._idle_color
        try:
            self.setIcon(
                icons.icon(
                    self.icon_name(),
                    color,
                    size=self.ICON_SIZE,
                    stroke_width=self.ICON_STROKE,
                    device_pixel_ratio=self._dpr(),
                )
            )
        except icons.IconNotFoundError:
            # Bax `GLYPHS` şərhi: boş düymə pəncərəni idarəolunmaz edərdi.
            self.setText(self.GLYPHS[self._action])

    def _dpr(self) -> float:
        window = self.window()
        handle = window.windowHandle() if window is not None else None
        return handle.devicePixelRatio() if handle is not None else 1.0


__all__ = [
    "NavButton",
    "WindowButton",
    "action_button",
    "icon_button",
    "secondary_button",
]
