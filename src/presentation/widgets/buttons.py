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
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from src.presentation.theme.manager import refresh_widget_style
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.safe_text import plain_tooltip


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
    """
    button = QPushButton(text, parent)
    button.setProperty("variant", "action")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    _apply_font(button, size=14, weight=QFont.Weight.DemiBold)
    button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    if icon_name is not None and icon_color is not None:
        button.setIcon(icons.icon(icon_name, icon_color, size=15, stroke_width=1.6))
        button.setIconSize(QSize(15, 15))
    return button


def secondary_button(text: str, *, parent: QWidget | None = None) -> QPushButton:
    """İkinci dərəcəli düymə — "Keçən aya bax", "Dəstəyə yaz"."""
    button = QPushButton(text, parent)
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

    def _refresh_icon(self) -> None:
        color = self._active_color if self._active else self._idle_color
        self.setIcon(icons.icon(self._icon_name, color, device_pixel_ratio=self._dpr()))

    def _dpr(self) -> float:
        window = self.window()
        handle = window.windowHandle() if window is not None else None
        return handle.devicePixelRatio() if handle is not None else 1.0


class WindowButton(QPushButton):
    """Pəncərə başlığındakı —/□/× düymələri.

    Simvollar maketdəki kimi mətnlə verilir (— □ ×) — onlar ikon dəstinin
    bir hissəsi deyil, çünki Windows konvensiyasının özüdür və hər üçü eyni
    tipoqrafik ölçüdə görünməlidir.
    """

    #: Maketdəki simvollar.
    GLYPHS: ClassVar[dict[str, str]] = {
        "minimize": "—",
        "maximize": "□",
        "close": "×",
    }

    #: Ekran oxuyucusunun elan edəcəyi adlar. Simvolun ÖZÜ ad ola bilməz:
    #: `—`, `□`, `×` oxunanda "tire", "kvadrat", "vur" kimi səslənir və
    #: istifadəçi düymənin nə etdiyini bilmir.
    ACCESSIBLE_NAMES: ClassVar[dict[str, str]] = {
        "minimize": "Pəncərəni kiçilt",
        "maximize": "Pəncərəni böyüt və ya bərpa et",
        "close": "Pəncərəni bağla",
    }

    def __init__(self, action: str, *, parent: QWidget | None = None) -> None:
        if action not in self.GLYPHS:
            raise ValueError(f"Naməlum pəncərə əməliyyatı: {action!r}")
        super().__init__(self.GLYPHS[action], parent)
        self.setProperty("variant", "window")
        self.setProperty("action", action)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFixedSize(metrics.WINDOW_BUTTON_WIDTH, metrics.TITLEBAR_HEIGHT)
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


__all__ = [
    "NavButton",
    "WindowButton",
    "action_button",
    "icon_button",
    "secondary_button",
]
