"""Pəncərə örtüyü: ikon düymələr, native Aero Snap qatı, tərtibat rejimi.

`uxui.md` üç addım tələb edir və bu fayl onların PROQRAMLA yoxlana bilən
hissəsini kilidləyir:

    Addım 1 — düymələr ikondur, maksimallaşdırılmış halda BƏRPA nişanına
              keçir, bağla düyməsi hover-də qırmızı fon alır;
    Addım 2 — native örtüyün qapıları (platforma yoxlaması, hit-test zonaları,
              sürüklənən sahə, Snap Layouts düyməsinin düzbucaqlısı);
    Addım 3 — pəncərə eninin bir "layout mode" siqnalına çevrilməsi və onun
              sol panelə + ekranlara paylanması.

──────────────────────────────────────────────────────────────────────────────
NƏYİ TEST EDƏ BİLMİRİK (VƏ NİYƏ)
──────────────────────────────────────────────────────────────────────────────
Pəncərəni siçanla ekran kənarına sürüşdürmək FİZİKİ, interaktiv əməliyyatdır;
`offscreen` platformasında nə DWM, nə də tapşırıq paneli var. Ona görə burada
`WM_NCHITTEST`-in FAKTİKİ cavabı deyil, onu formalaşdıran hər bir GİRİŞ
yoxlanılır: kənar zonası riyaziyyatı (`edge_zone`), sürüklənən sahə
(`is_drag_region`), böyüt düyməsinin düzbucaqlısı və `lParam` koordinat
ayrıcısı. Bu dörd giriş düzgündürsə, `HTMAXBUTTON`/`HTCAPTION` cavabı
determinstikdir.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLabel, QWidget

from src.presentation.shell import native_chrome
from src.presentation.theme.manager import ThemeManager
from src.presentation.theme.tokens import DARK_THEME, LIGHT_THEME, ThemeMode
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import WindowButton
from src.presentation.widgets.responsive import LayoutMode, mode_for_width
from src.presentation.widgets.title_bar import TitleBar
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _themed(app, mode: ThemeMode) -> ThemeManager:  # type: ignore[no-untyped-def]
    """Temanı FAKTİKİ olaraq tətbiq edir — QSS-siz `:hover` sınana bilməz."""
    theme = ThemeManager(preference=mode)
    theme.apply(app)
    return theme


# --------------------------------------------------------------------------- #
# ADDIM 1 — pəncərə düymələri
# --------------------------------------------------------------------------- #


def test_window_icons_exist_in_the_icon_set() -> None:
    """Dörd nişan dizayn dəstindədir — generic Qt ikonu işlədilmir."""
    available = set(icons.available())
    assert {
        "window_minimize",
        "window_maximize",
        "window_restore",
        "window_close",
    } <= available


def test_window_icons_are_stroke_based_like_the_rest_of_the_set() -> None:
    """Nişanlar dəstin dilindədir: dolğun deyil, xətt (`fill="none"`)."""
    for name in ("window_minimize", "window_maximize", "window_restore", "window_close"):
        document = icons._document(name, "#123456", 1.3).decode()
        assert 'fill="none"' in document
        assert 'stroke="#123456"' in document
        assert 'viewBox="0 0 16 16"' in document


@requires_qt
@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_window_buttons_render_an_icon_not_a_text_glyph(qt_app, mode) -> None:  # type: ignore[no-untyped-def]
    """Düymə MƏTNSİZDİR və ikonu boş deyil — hər iki temada.

    Simvol (`—`, `□`, `×`) şriftdən asılı idi: `□` bəzi Windows quraşdırmalarda
    "tofu" kimi çıxırdı, yəni düymə üzərində heç nə görünmürdü.
    """
    _themed(qt_app, mode)
    for action in ("minimize", "maximize", "close"):
        button = WindowButton(action)
        assert button.text() == "", "pəncərə düyməsi hələ də mətn simvolu göstərir"
        assert not button.icon().isNull(), "ikon çəkilməyib"


@requires_qt
def test_maximize_button_switches_to_the_restore_glyph(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Maksimallaşdırılmış pəncərədə nişan BƏRPA formasına keçir.

    Simvol dövründə bu mümkün deyildi: Unicode-da ümumi işlənən "bərpa"
    işarəsi yoxdur, ona görə düymə həmişə "böyüt" göstərirdi.
    """
    _themed(qt_app, ThemeMode.DARK)
    button = WindowButton("maximize")
    assert button.icon_name() == "window_maximize"

    button.set_maximized(True)
    assert button.icon_name() == "window_restore"
    assert button.accessibleName() == WindowButton.MAXIMIZED_NAME

    button.set_maximized(False)
    assert button.icon_name() == "window_maximize"
    assert button.accessibleName() == WindowButton.ACCESSIBLE_NAMES["maximize"]


@requires_qt
def test_minimize_and_close_keep_one_glyph_in_both_states(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Yalnız «böyüt» iki nişanlıdır; digər ikisi vəziyyətdən asılı deyil."""
    _themed(qt_app, ThemeMode.LIGHT)
    for action, expected in (("minimize", "window_minimize"), ("close", "window_close")):
        button = WindowButton(action)
        button.set_maximized(True)
        assert button.icon_name() == expected


@requires_qt
def test_accessible_names_survive_the_icon_migration(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ekran oxuyucusu üçün ad İKONA keçiddən sonra daha da vacibdir.

    Mətn simvolu olsaydı, Qt heç olmasa `text()`-i oxuyardı ("tire", "vur").
    İkonun heç bir mətni yoxdur — ad olmasa düymə sadəcə "düymə"dir.
    """
    _themed(qt_app, ThemeMode.LIGHT)
    for action in ("minimize", "maximize", "close"):
        button = WindowButton(action)
        assert button.accessibleName().strip()
        assert button.accessibleName() == WindowButton.ACCESSIBLE_NAMES[action]


@requires_qt
def test_opening_the_window_does_not_draw_a_focus_ring(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Tətbiq açılanda «kiçilt» düyməsinin ətrafında halqa OLMAMALIDIR.

    Faktiki qüsur: Qt pəncərə göstəriləndə fokusu fokus-zəncirinin BİRİNCİ
    elementinə verir və başlıq zolağı tərtibatın ən üstündə olduğu üçün bu,
    «Pəncərəni kiçilt» düyməsi olurdu. `:focus` qaydası isə 2px açıq haşiyə
    çəkirdi — istifadəçi heç nəyə toxunmadan ekranda AĞ KVADRAT görürdü.

    Ölçdüyümüz şey QSS deyil, QSS-in ASILDIĞI xüsusiyyətdir: `keyfocus`
    "false" qaldıqca selektor uyğun gəlmir.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QVBoxLayout

    _themed(qt_app, ThemeMode.DARK)
    window = QWidget()
    layout = QVBoxLayout(window)
    bar = TitleBar()
    layout.addWidget(bar)
    window.show()
    qt_app.processEvents()

    # İLK FOKUSU HANSI DÜYMƏNİN ALDIĞI ARTIQ ÖLÇÜLMÜR.
    #
    # Əvvəl burada `focusWidget() is minimize` iddiası vardı və o, zəncirin
    # SIRASINI qapıya salırdı — halbuki qorunan şey sıra deyil, HALQANIN
    # OLMAMASIdır. Başlıq zolağına tema düyməsi əlavə olunanda iddia sındı,
    # zəmanət isə pozulmamışdı.
    #
    # İndi qapı birbaşa zəmanəti ölçür: fokusu KİM alırsa alsın, açılışda
    # halqa çəkilməməlidir. Bu, həm də daha güclüdür — zolağa üçüncü düymə
    # əlavə edən adam onu da avtomatik yoxlayır.
    focused = qt_app.focusWidget()
    assert focused is not None, "başlıq zolağı fokusu ümumiyyətlə almır"
    assert focused.property("keyfocus") == "false", (
        "tətbiq açılan kimi fokus halqası çəkilir — istifadəçi heç nəyə "
        "toxunmadan işıqlı kvadrat görür"
    )

    # Klaviatura yolu POZULMUR: `Tab` səbəbi ilə halqa QAYIDIR.
    focused.clearFocus()
    qt_app.processEvents()
    focused.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert focused.property("keyfocus") == "true"

    focused.clearFocus()
    qt_app.processEvents()
    assert focused.property("keyfocus") == "false"

    # Zolaqdakı HƏR fokus ala bilən düymə eyni qaydaya tabedir.
    for button in (*bar.buttons(), bar.theme_button()):
        assert button.property("keyfocus") == "false", (
            f"{button.accessibleName()!r} açılışda halqa çəkir"
        )
    window.close()


@requires_qt
def test_replacing_the_screen_does_not_light_up_the_title_bar(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ekran əvəzlənəndə başlıq zolağı SƏBƏBSİZ halqa çəkməməlidir.

    ──────────────────────────────────────────────────────────────────────────
    FAKTİKİ QÜSUR
    ──────────────────────────────────────────────────────────────────────────
    İstifadəçi «Bağlantı qurula bilmədi» ekranında «Yenidən cəhd et» düyməsini
    SİÇANLA basır. Ekran əvəzlənir, yəni fokuslu düymə MƏHV olur — və Qt
    fokusu zəncirin növbəti elementinə (başlıq zolağındakı tema düyməsinə)
    `TabFocusReason` ilə ötürür. Səbəb kodu HƏQİQİ `Tab` basılışı ilə eynidir,
    ona görə halqa məntiqi onu klaviatura fokusu sanırdı və çərçivə çəkirdi:
    istifadəçi klaviaturaya toxunmadan tema düyməsinin işıqlandığını görürdü.

    Ölçülən şey siçan/klaviatura fərqi DEYİL, məhz bu keçiddir — klaviatura
    yolu yuxarıdakı testlə qorunur və pozulmamalıdır.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton, QVBoxLayout

    from src.presentation.shell.window import FramelessWindow

    theme = _themed(qt_app, ThemeMode.DARK)
    window = FramelessWindow(theme=theme, title="KompasOS")

    page = QWidget()
    page_layout = QVBoxLayout(page)
    retry = QPushButton("Yenidən cəhd et")
    page_layout.addWidget(retry)
    window.set_content(page)
    window.show()
    qt_app.processEvents()

    retry.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()

    window.set_content(QPushButton("yeni ekran"))
    qt_app.processEvents()

    bar = window.title_bar()
    assert bar is not None
    for button in (*bar.buttons(), bar.theme_button()):
        assert button.property("keyfocus") == "false", (
            f"{button.accessibleName()!r} ekran əvəzlənəndən sonra halqa çəkir"
        )
    window.close()


@requires_qt
def test_activating_the_window_keeps_the_keyboard_ring(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`Alt`+`Tab` ilə qayıdanda klaviatura halqası İTMİR.

    İstifadəçi `Tab`-la düyməyə çatıb başqa proqrama keçirsə, qayıdışda fokus
    eyni düyməyə `ActiveWindow` səbəbi ilə gəlir. Həmin səbəbi "klaviatura
    deyil" saysaydıq, halqa itər və istifadəçi fokusun harada olduğunu
    itirərdi — yəni düzəliş bu dəfə ƏKS istiqamətdə eyni qüsuru yaradardı.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFocusEvent

    _themed(qt_app, ThemeMode.DARK)
    button = WindowButton("minimize")
    button.show()
    qt_app.processEvents()
    # Göstərilən pəncərə fokusu ARTIQ düyməyə vermiş ola bilər (aktivləşmə
    # səbəbi ilə); `setFocus` o halda heç bir hadisə yaratmaz. Ona görə əvvəl
    # təmizlənir — yəni `Tab` yolu FAKTİKİ olaraq sınanır.
    button.clearFocus()
    qt_app.processEvents()
    button.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert button.property("keyfocus") == "true"

    button.focusOutEvent(
        QFocusEvent(QFocusEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason)
    )
    button.focusInEvent(
        QFocusEvent(QFocusEvent.Type.FocusIn, Qt.FocusReason.ActiveWindowFocusReason)
    )
    assert button.property("keyfocus") == "true"


@requires_qt
def test_focus_policy_and_size_are_unchanged(qt_app) -> None:  # type: ignore[no-untyped-def]
    """İkona keçid ƏVVƏLKİ iki qərarı pozmamalıdır (bax `buttons.py`)."""
    from PySide6.QtCore import Qt

    _themed(qt_app, ThemeMode.DARK)
    button = WindowButton("close")
    assert button.focusPolicy() is Qt.FocusPolicy.TabFocus
    assert button.width() == metrics.WINDOW_BUTTON_WIDTH
    assert button.height() == metrics.TITLEBAR_HEIGHT


@requires_qt
@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_hover_repaints_the_icon_because_qss_cannot_colour_it(qt_app, mode) -> None:  # type: ignore[no-untyped-def]
    """Hover-də ikon YENİDƏN çəkilir — QSS `QIcon`-u boyamır.

    Qüsur ssenarisi: hover fonu tünddən qırmızıya keçir, ikon isə köhnə
    rəngdə qalır və qırmızı üzərində oxunmaz olur.
    """
    theme = _themed(qt_app, mode)
    button = WindowButton("close")
    button.set_colors(
        idle_color=theme.color("--color-titlebar-control"),
        hover_color=theme.color("--color-bg-primary"),
    )
    idle = button.icon().pixmap(WindowButton.ICON_SIZE, WindowButton.ICON_SIZE).toImage()

    button.set_hovered(True)
    hovered = button.icon().pixmap(WindowButton.ICON_SIZE, WindowButton.ICON_SIZE).toImage()

    assert idle != hovered, "hover ikonun rəngini dəyişmədi"
    assert button.property("hover") == "true"

    button.set_hovered(False)
    assert button.property("hover") == "false"


@requires_qt
@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_close_hover_uses_the_red_surface_token(qt_app, mode) -> None:  # type: ignore[no-untyped-def]
    """Bağla düyməsinin hover fonu QIRMIZIDIR (Windows/Chrome konvensiyası).

    QSS-in faktiki mətni yoxlanılır: qayda silinsə və ya token dəyişsə test
    qırılır. Rəngin özü `scripts/check_contrast.py`-da ölçülür.
    """
    theme = _themed(qt_app, mode)
    sheet = theme.stylesheet()
    assert 'QPushButton[variant="window"][action="close"]:hover' in sheet
    assert theme.color("--color-danger") in sheet


@requires_qt
def test_titlebar_hover_surface_is_not_the_titlebar_background(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Hover fonu zolağın fonundan FƏRQLİ olmalıdır.

    Qüsur tarixi: hover `--color-nav-active-bg` idi və İŞIQLI temada o da
    `BRAND_NAVY`-dir — yəni başlıq zolağının fonu ilə eyni rəng. Kursoru
    düymənin üstünə gətirən istifadəçi HEÇ BİR cavab görmürdü.
    """
    _themed(qt_app, ThemeMode.LIGHT)
    for palette in (LIGHT_THEME, DARK_THEME):
        assert palette["--color-titlebar-control-hover"] != palette["--color-titlebar-bg"]


@requires_qt
@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_title_bar_applies_theme_colours_to_all_three_buttons(qt_app, mode) -> None:  # type: ignore[no-untyped-def]
    """Tema dəyişikliyi ikonların rənglərinə ÇATIR (hər iki rejim)."""
    theme = _themed(qt_app, mode)
    bar = TitleBar()
    bar.apply_theme(
        control_color=theme.color("--color-titlebar-control"),
        hover_color=theme.color("--color-titlebar-text"),
        close_hover_color=theme.color("--color-bg-primary"),
    )
    minimize, maximize, close = bar.buttons()
    for button in (minimize, maximize, close):
        assert button._idle_color == theme.color("--color-titlebar-control")
    assert maximize._hover_color == theme.color("--color-titlebar-text")
    # Bağla düyməsi qırmızı fonun ÜZƏRİNDƏ oxunmalıdır — ona görə fərqli rəng.
    assert close._hover_color == theme.color("--color-bg-primary")


@requires_qt
@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_synthetic_hover_actually_paints_the_hover_surface(qt_app, mode) -> None:  # type: ignore[no-untyped-def]
    """`hover="true"` xüsusiyyəti FAKTİKİ olaraq fonu dəyişir — piksel sübutu.

    İki qüsuru birdən kilidləyir:

    1. İŞIQLI temada hover görünmürdü (`--color-nav-active-bg` başlıq zolağının
       fonu ilə eyni Navy idi, 1.00:1).
    2. Snap Layouts rejimində Qt-nin `:hover` psevdo-sinfi HEÇ VAXT işə düşmür
       (düymə qeyri-müştəri sahədədir), ona görə fon dinamik xüsusiyyətdən
       gəlməlidir — əks halda yalnız ikon dəyişərdi, fon yox.
    """
    theme = _themed(qt_app, mode)
    bar = TitleBar()
    bar.resize(600, metrics.TITLEBAR_HEIGHT)
    bar.show()
    qt_app.processEvents()

    _minimize, maximize, close = bar.buttons()
    expected = {
        maximize: theme.color("--color-titlebar-control-hover"),
        close: theme.color("--color-danger"),
    }
    for button, surface in expected.items():
        # Nümunə KÜNCDƏN götürülür, mərkəzdən yox: 16px ikon məhz mərkəzdədir
        # və orada oxunan piksel ikonun ştrixidir, fon deyil.
        probe = button.geometry().topLeft() + QPoint(3, 3)
        idle = bar.grab().toImage().pixelColor(probe).name().upper()

        button.set_hovered(True)
        qt_app.processEvents()
        hovered = bar.grab().toImage().pixelColor(probe).name().upper()

        assert hovered == surface.upper(), f"«{button.accessibleName()}» hover fonu tətbiq olunmadı"
        assert idle != hovered, "hover halı gözlə seçilmir"
        button.set_hovered(False)


@requires_qt
def test_missing_icon_falls_back_to_the_maket_glyph(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """İkon tapılmasa düymə BOŞ qalmır — simvol ehtiyatı işə düşür.

    Çərçivəsiz pəncərədə sistem menyusu yoxdur: bu üç düymə bağlamağın yeganə
    siçan yoludur. Görünməz 46×38px kvadrat qəbuledilməzdir.
    """
    _themed(qt_app, ThemeMode.LIGHT)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise icons.IconNotFoundError("test", context={})

    monkeypatch.setattr(icons, "icon", _raise)
    button = WindowButton("close")
    assert button.text() == WindowButton.GLYPHS["close"]


# --------------------------------------------------------------------------- #
# ADDIM 2 — native örtük
# --------------------------------------------------------------------------- #


def test_edge_zone_maps_every_corner_and_side() -> None:
    """Səkkiz zona + daxili sahə. Cədvəl səhv yazılsa kursor səhv künclə dartar."""
    width, height, border = 200, 100, 8
    cases = {
        (0, 0): 13,  # HTTOPLEFT
        (100, 0): 12,  # HTTOP
        (199, 0): 14,  # HTTOPRIGHT
        (0, 50): 10,  # HTLEFT
        (199, 50): 11,  # HTRIGHT
        (0, 99): 16,  # HTBOTTOMLEFT
        (100, 99): 15,  # HTBOTTOM
        (199, 99): 17,  # HTBOTTOMRIGHT
    }
    for (x, y), expected in cases.items():
        assert native_chrome.edge_zone(x, y, width, height, border) == expected
    assert native_chrome.edge_zone(100, 50, width, height, border) is None


def test_edge_zone_is_disabled_when_the_border_is_zero() -> None:
    """Maksimallaşdırılmış pəncərədə kənar zolağı OLMUR (`border == 0`)."""
    assert native_chrome.edge_zone(0, 0, 200, 100, 0) is None


def test_lparam_coordinates_are_read_as_signed_words() -> None:
    """Koordinat MƏNFİ ola bilər — soldakı ikinci monitor.

    İşarəsiz oxunsaydı `-1` → `65535` olardı və hit-test heç vaxt uyğun
    gəlməzdi (pəncərə həmin monitorda "ölü" görünərdi).
    """
    assert native_chrome._signed_point((10 & 0xFFFF) | (20 << 16)) == (10, 20)
    packed = ((-5) & 0xFFFF) | (((-7) & 0xFFFF) << 16)
    assert native_chrome._signed_point(packed) == (-5, -7)


@requires_qt
def test_native_chrome_is_not_installed_on_the_offscreen_platform(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`offscreen` platformasında `winId()` REAL HWND deyil — örtük qurulmur.

    Bu qapı olmasaydı Win32 çağırışları uydurma tutacağa gedərdi.
    """
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "windows":
        pytest.skip("Bu maşında Qt native `windows` plugin-i ilə işləyir")
    assert native_chrome.is_supported() is False


class _FakeHost:
    """`NativeChromeHost` protokolunun test əvəzi (Qt-siz).

    Protokolun DAR olması məhz bunun üçündür: saxta host bir neçə sətirdir.
    """

    def __init__(self, *, resizable: bool = True) -> None:
        self.resizable = resizable
        self.hovered: bool | None = None
        self.pressed: bool | None = None
        self.toggled = 0

    def native_window_id(self) -> int:
        return 0

    def native_is_resizable(self) -> bool:
        return self.resizable

    def native_device_pixel_ratio(self) -> float:
        return 1.0

    def native_is_drag_area(self, x: int, y: int) -> bool:
        return y < 38

    def native_maximize_button_rect(self) -> QRect | None:
        return QRect(100, 0, 46, 38)

    def native_set_maximize_hovered(self, hovered: bool) -> None:
        self.hovered = hovered

    def native_set_maximize_pressed(self, pressed: bool) -> None:
        self.pressed = pressed

    def native_toggle_maximized(self) -> None:
        self.toggled += 1


def test_uninstalled_chrome_never_swallows_a_message() -> None:
    """Quraşdırılmamış örtük `None` qaytarır — Qt öz emalını aparır."""
    chrome = native_chrome.NativeWindowChrome(_FakeHost())
    assert chrome.installed is False
    assert chrome.handle(native_chrome.NATIVE_EVENT_TYPE, 0) is None
    assert chrome.toggle_maximized() is False


def test_foreign_event_types_are_ignored() -> None:
    """Yalnız Windows mesaj axını emal olunur."""
    chrome = native_chrome.NativeWindowChrome(_FakeHost())
    assert chrome.handle(b"xcb_generic_event_t", 0) is None


# --------------------------------------------------------------------------- #
# ADDIM 2 — hit-testing girişləri (pəncərə tərəfi)
# --------------------------------------------------------------------------- #


@requires_qt
def test_title_bar_drag_region_excludes_the_window_buttons(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Sürüklənən sahə düymələri ƏHATƏ ETMİR.

    Əhatə etsəydi, native rejimdə düymələr `HTCAPTION` olar, yəni Qt onlara
    klik göndərməzdi — pəncərə bağlanmaz və kiçilməzdi.
    """
    _themed(qt_app, ThemeMode.DARK)
    bar = TitleBar()
    bar.resize(900, metrics.TITLEBAR_HEIGHT)
    bar.show()
    qt_app.processEvents()

    assert bar.is_drag_region(QPoint(300, 10)) is True, "zolağın boş hissəsi sürüklənməlidir"
    for button in bar.buttons():
        centre = button.geometry().center()
        assert bar.is_drag_region(centre) is False, (
            f"«{button.accessibleName()}» düyməsi sürüklənən sahəyə düşüb"
        )


@requires_qt
def test_logo_and_title_stay_draggable(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Loqo və başlıq mətni zolağın bir hissəsidir, ayrı idarəetmə deyil."""
    _themed(qt_app, ThemeMode.LIGHT)
    bar = TitleBar(title="KompasOS")
    bar.resize(900, metrics.TITLEBAR_HEIGHT)
    bar.show()
    qt_app.processEvents()

    label = bar.findChild(QLabel)
    assert label is not None
    assert bar.is_drag_region(label.geometry().center()) is True


@requires_qt
def test_window_reports_the_snap_layouts_button_rectangle(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Böyüt düyməsinin düzbucaqlısı PƏNCƏRƏ koordinatındadır.

    Windows 11 Snap Layouts menyusu yalnız `WM_NCHITTEST` bu sahə üçün
    `HTMAXBUTTON` qaytardıqda açılır — düzbucaqlı səhv olsa menyu heç vaxt
    çıxmaz.
    """
    from src.presentation.shell.window import FramelessWindow

    _themed(qt_app, ThemeMode.DARK)
    window = FramelessWindow(title="KompasOS")
    window.resize(1400, 900)
    window.show()
    qt_app.processEvents()

    rect = window.native_maximize_button_rect()
    assert rect is not None
    bar = window.title_bar()
    assert bar is not None
    assert rect.size() == bar.maximize_button().size()
    assert rect.top() >= 0
    assert rect.right() <= window.width()
    # Düymə zolağın SAĞ tərəfindədir (maket) — sol yarıda olsaydı, sürüklənən
    # sahə ilə üst-üstə düşərdi.
    assert rect.left() > window.width() // 2

    window.close()


@requires_qt
def test_hidden_maximize_button_disables_snap_layouts(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ölçüsü sabit pəncərədə tərtibat menyusu təklif edilmir.

    Menyu çıxsaydı, seçim heç nə etməzdi — istifadəçi tətbiqi sınmış sayardı.
    """
    from src.presentation.shell.window import FramelessWindow

    _themed(qt_app, ThemeMode.LIGHT)
    window = FramelessWindow(title="KompasOS", resizable=False)
    window.show()
    qt_app.processEvents()

    assert window.native_maximize_button_rect() is None
    window.close()


@requires_qt
def test_window_falls_back_to_pure_qt_when_native_chrome_is_absent(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Native örtük yoxdursa əvvəlki saf-Qt yolu İŞLƏMƏYƏ DAVAM EDİR.

    Bu, `offscreen`/Linux mühitinin YEGANƏ ölçü dəyişdirmə yoludur — silinsə,
    həmin platformalarda pəncərə ölçüsü sabitlənərdi.
    """
    from PySide6.QtCore import Qt

    from src.presentation.shell.window import FramelessWindow

    _themed(qt_app, ThemeMode.DARK)
    window = FramelessWindow(title="KompasOS")
    window.resize(1400, 900)
    window.show()
    qt_app.processEvents()

    assert window.native_chrome_active is False
    assert window._edge_at(1, 1) == (Qt.Edge.LeftEdge | Qt.Edge.TopEdge)
    assert window._edge_at(700, 400) is None

    window.toggle_maximized()
    assert window.is_maximized is True
    bar = window.title_bar()
    assert bar is not None
    assert bar.maximize_button().icon_name() == "window_restore"

    window.toggle_maximized()
    assert window.is_maximized is False
    assert bar.maximize_button().icon_name() == "window_maximize"

    window.close()


# --------------------------------------------------------------------------- #
# ADDIM 3 — tərtibat rejimi
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("width", "expected"),
    [
        (1920, LayoutMode.WIDE),
        (1280, LayoutMode.WIDE),
        (1279, LayoutMode.COMPACT),
        (960, LayoutMode.COMPACT),
        (700, LayoutMode.COMPACT),
    ],
)
def test_breakpoints_split_at_the_documented_widths(width: int, expected: LayoutMode) -> None:
    """1280 DAXİLDİR: spesifikasiyanın minimum ölçüsü dərhal "dar" olmamalıdır."""
    assert mode_for_width(width) is expected


def test_breakpoint_constants_live_in_metrics_not_in_root_settings() -> None:
    """Hədlər kod-səviyyəli sabitdir (`uxui.md` bunu açıq deyir)."""
    assert metrics.LAYOUT_BREAKPOINT_WIDE == 1280
    assert metrics.LAYOUT_BREAKPOINT_COMPACT == 700
    # Yarım-ekran snap 700–1280 diapazonuna düşür; minimum en o həddin
    # ÜSTÜNDƏ qalsaydı, Windows pəncərəni sığışdıra bilməzdi.
    assert metrics.WINDOW_HARD_MIN_WIDTH == metrics.LAYOUT_BREAKPOINT_COMPACT


@requires_qt
def test_window_minimum_width_allows_half_screen_snap(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Minimum en 1280-də qalsaydı yarım-ekran snap MÜMKÜN OLMAZDI."""
    from src.presentation.shell.window import FramelessWindow

    _themed(qt_app, ThemeMode.LIGHT)
    window = FramelessWindow(title="KompasOS")
    assert window.minimumWidth() == metrics.WINDOW_HARD_MIN_WIDTH
    assert window.minimumWidth() < metrics.LAYOUT_BREAKPOINT_WIDE
    # İlk açılış ölçüsü spesifikasiyanın 1280×800 tələbini saxlayır.
    assert window.width() >= metrics.WINDOW_MIN_WIDTH
    window.close()


@requires_qt
def test_resize_emits_the_layout_mode_signal_once_per_transition(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Siqnal yalnız KEÇİDDƏ yayılır — hər piksel dəyişikliyində yox.

    Hər ölçü hadisəsində yayılsaydı, sürükləmə boyu sol panel və bütün kart
    şəbəkəsi saniyədə onlarla dəfə yenidən qurulardı.
    """
    from src.presentation.shell.window import FramelessWindow

    _themed(qt_app, ThemeMode.DARK)
    window = FramelessWindow(title="KompasOS")
    window.resize(1400, 900)
    window.show()
    qt_app.processEvents()

    seen: list[str] = []
    window.layout_mode_changed.connect(seen.append)

    window.resize(1000, 900)
    qt_app.processEvents()
    window.resize(900, 900)
    qt_app.processEvents()
    assert seen == [LayoutMode.COMPACT.value], f"gözlənilməz siqnal axını: {seen}"

    window.resize(1400, 900)
    qt_app.processEvents()
    assert seen == [LayoutMode.COMPACT.value, LayoutMode.WIDE.value]
    assert window.layout_mode is LayoutMode.WIDE

    window.close()


@requires_qt
def test_responsive_row_stacks_into_one_column(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Qeyd olunmuş sətir dar rejimdə şaquli olur — kartlar SÖKÜLMÜR.

    Yenidən qurulsaydı, kartların vəziyyəti (sürüşdürmə, seçilmiş sətir,
    fokus) itərdi; istifadəçi isə sadəcə pəncərəni daraltmışdır.
    """
    from src.presentation.screens.base import Screen

    theme = _themed(qt_app, ThemeMode.LIGHT)
    screen = Screen(theme)
    host = QWidget()
    row = QHBoxLayout(host)
    left, right = QLabel("sol"), QLabel("sağ")
    row.addWidget(left)
    row.addWidget(right)
    screen.responsive_row(row)
    screen.add(host)

    assert row.direction() is QBoxLayout.Direction.LeftToRight

    screen.apply_layout_mode(LayoutMode.COMPACT)
    assert row.direction() is QBoxLayout.Direction.TopToBottom
    assert row.itemAt(0).widget() is left, "widget-lər yenidən qurulmamalıdır"
    assert row.itemAt(1).widget() is right

    screen.apply_layout_mode(LayoutMode.WIDE)
    assert row.direction() is QBoxLayout.Direction.LeftToRight


@requires_qt
def test_dashboard_registers_its_three_rows(qt_app) -> None:  # type: ignore[no-untyped-def]
    """İdarə Paneli dar rejimdə bir sütuna yığılır (`uxui.md` Addım 3)."""
    from src.presentation.screens.group_c import DashboardScreen

    theme = _themed(qt_app, ThemeMode.DARK)
    screen = DashboardScreen(theme)
    assert len(screen._responsive_rows) == 3

    screen.apply_layout_mode(LayoutMode.COMPACT)
    for row in screen._responsive_rows:
        assert row.direction() is QBoxLayout.Direction.TopToBottom


@requires_qt
def test_shell_collapses_the_sidebar_and_forwards_to_screens(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Örtük MÖVCUD daralma funksiyasını çağırır, yenisini yazmır.

    `Sidebar.set_collapsed` → `NavButton.set_compact` zənciri Faza 4.2-dən
    bəri var idi; responsive sistem yalnız onu TETİKLƏYİR.
    """
    from datetime import UTC, datetime

    from src.presentation import preview_data
    from src.presentation.screens.base import Screen
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    theme = _themed(qt_app, ThemeMode.LIGHT)
    employee = preview_data.build_admin()
    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=employee,
        now=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )

    screen = Screen(theme)
    host = QWidget()
    row = QHBoxLayout(host)
    row.addWidget(QLabel("bir"))
    screen.responsive_row(row)
    key = shell.sidebar().entry_keys()[0]
    shell.register_screen(key, lambda: screen)
    assert shell.show_screen(key) is True

    assert shell.sidebar().is_collapsed is False
    shell.apply_layout_mode(LayoutMode.COMPACT)
    assert shell.sidebar().is_collapsed is True
    assert row.direction() is QBoxLayout.Direction.TopToBottom
    assert shell.layout_mode is LayoutMode.COMPACT

    shell.apply_layout_mode(LayoutMode.WIDE)
    assert shell.sidebar().is_collapsed is False
    assert row.direction() is QBoxLayout.Direction.LeftToRight


@requires_qt
def test_lazily_built_screen_inherits_the_current_layout_mode(qt_app) -> None:  # type: ignore[no-untyped-def]
    """GEC qurulan ekran rejim siqnalını qaçırır — örtük onu ÖZÜ ötürür.

    Onsuz daraldılmış pəncərədə ilk dəfə açılan ekran geniş tərtibatla
    görünərdi və yalnız növbəti ölçü dəyişikliyində düzələrdi.
    """
    from datetime import UTC, datetime

    from src.presentation import preview_data
    from src.presentation.screens.base import Screen
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    theme = _themed(qt_app, ThemeMode.DARK)
    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )
    shell.apply_layout_mode(LayoutMode.COMPACT)

    screen = Screen(theme)
    host = QWidget()
    row = QHBoxLayout(host)
    row.addWidget(QLabel("gec"))
    screen.responsive_row(row)

    key = shell.sidebar().entry_keys()[0]
    shell.register_screen(key, lambda: screen)
    assert shell.show_screen(key) is True
    assert row.direction() is QBoxLayout.Direction.TopToBottom


@requires_qt
def test_shell_accepts_the_signal_payload_as_a_plain_string(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Qt siqnalı `str` daşıyır — çevirmə TƏK yerdə (örtükdə) olur."""
    from datetime import UTC, datetime

    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry

    theme = _themed(qt_app, ThemeMode.LIGHT)
    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )
    shell.apply_layout_mode("COMPACT")
    assert shell.layout_mode is LayoutMode.COMPACT


# --------------------------------------------------------------------------- #
# KİOSK — miqrasiya onu SINDIRMAMALIDIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_kiosk_window_is_untouched_by_the_native_chrome_work(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Kiosk tam ekrandır: Aero Snap ona AİD DEYİL.

    Kiosk pəncərəsində başlıq zolağı, ölçü dəyişdirmə və bağla düyməsi
    QƏSDƏN yoxdur (mağazada paylaşılan terminal) — pəncərə örtüyü işi bu
    qərarların HEÇ BİRİNƏ toxunmamalıdır.
    """
    from PySide6.QtCore import Qt

    from src.presentation.shell.kiosk import EXIT_SHORTCUT, KioskWindow

    _themed(qt_app, ThemeMode.DARK)
    kiosk = KioskWindow()
    assert kiosk.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert kiosk.objectName() == "KioskWindow"
    assert not kiosk.findChildren(TitleBar), "kiosk-a başlıq zolağı sızıb"
    assert not kiosk.findChildren(WindowButton), "kiosk-a pəncərə düyməsi sızıb"
    assert EXIT_SHORTCUT == "Ctrl+Shift+Q"

    # Gizli qısayol hələ də YEGANƏ çıxış yoludur.
    events: list[bool] = []
    kiosk.exit_requested.connect(lambda: events.append(True))
    kiosk._on_exit_shortcut()
    assert events == [True]


@requires_qt
def test_kiosk_still_blocks_accidental_close(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`Alt+F4` təsdiqsiz keçmir — bu qayda dəyişmədi."""
    from PySide6.QtGui import QCloseEvent

    from src.presentation.shell.kiosk import KioskWindow

    _themed(qt_app, ThemeMode.LIGHT)
    kiosk = KioskWindow()

    event = QCloseEvent()
    kiosk.closeEvent(event)
    assert event.isAccepted() is False

    kiosk.allow_close()
    allowed = QCloseEvent()
    kiosk.closeEvent(allowed)
    assert allowed.isAccepted() is True
