"""Native Windows pəncərə örtüyü — Aero Snap və Snap Layouts.

`uxui.md` Addım 2 tələb edir ki, başlıq zolağını ekran kənarına sürüşdürəndə
Windows-un ÖZ animasiyası ilə tam/yarım ekrana keçilsin və Windows 11-in Snap
Layouts menyusu (böyüt düyməsinin üstünə saxlayanda çıxan tərtibat seçimləri)
işləsin.

──────────────────────────────────────────────────────────────────────────────
PROBLEM: `FramelessWindowHint` NATIVE DAVRANIŞI ÖLDÜRÜR
──────────────────────────────────────────────────────────────────────────────
Qt çərçivəsiz pəncərə üçün `WS_CAPTION`, `WS_THICKFRAME` və `WS_MAXIMIZEBOX`
üslublarını çıxarır. DWM (Windows-un kompozitoru) isə məhz həmin üslublara
baxaraq qərar verir: sürüşdürmə-snap, maksimum/minimum animasiyası, kölgə və
Snap Layouts. Üslub yoxdursa davranış da yoxdur — ona görə əl ilə yazılmış
`startSystemMove()` çağırışı da snap vermirdi.

──────────────────────────────────────────────────────────────────────────────
HƏLL: ÜSLUBU GERİ QAYTAR, ÇƏRÇİVƏNİ İSƏ `WM_NCCALCSIZE` İLƏ SİL
──────────────────────────────────────────────────────────────────────────────
1. `WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX` geri əlavə
   olunur (`qframelesswindow.WindowEffect.addWindowAnimation`) — DWM yenidən
   "bu, normal pəncərədir" deyir.
2. `WM_NCCALCSIZE` 0 qaytarır → qeyri-müştəri sahə SIFIRLANIR, yəni Windows
   öz başlığını və çərçivəsini ÇƏKMİR, bütün sahə bizim widget-lərimizindir.
3. `WM_NCHITTEST` kənarlarda `HT*` kodları, başlıq zolağında `HTCAPTION`
   qaytarır → sürükləmə, snap və sistem menyusu OS-dədir.

Animasiya BİZDƏ YAZILMIR — bu üç addım verilsə DWM onu özü edir (`uxui.md`:
"bizim özümüz animasiya YAZMIRIQ").

──────────────────────────────────────────────────────────────────────────────
SNAP LAYOUTS: KİTABXANADA YOXDUR, BURADA ƏLAVƏ EDİLİR
──────────────────────────────────────────────────────────────────────────────
`PySideSix-Frameless-Window` 0.8.2 mənbəyində `HTMAXBUTTON` HEÇ YERDƏ keçmir
(`windows/__init__.py::nativeEvent` yalnız kənarları və `WM_NCCALCSIZE`-ı
idarə edir). Yəni kitabxana Aero Snap verir, Snap Layouts VERMİR.

Windows 11 həmin menyunu göstərmək üçün YEGANƏ meyara baxır: `WM_NCHITTEST`
kursorun altındakı sahə üçün `HTMAXBUTTON` qaytarırmı. Qaytarırsa, DWM bir
neçə yüz millisaniyəlik gözləmədən sonra tərtibat seçimlərini özü açır.
Bunun İKİ əlavə nəticəsi var və hər ikisi burada bağlanır:

* Həmin sahə artıq QEYRİ-MÜŞTƏRİ sayılır, yəni Qt oraya nə `enterEvent`,
  nə də `mousePressEvent` göndərir. Düymənin hover görünüşü və kliki
  `WM_NCMOUSEMOVE` / `WM_NCLBUTTONDOWN` / `WM_NCLBUTTONUP` üzərindən BƏRPA
  olunur (bax `_on_nc_mouse_move`, `_on_nc_button`).
* `WS_MAXIMIZEBOX` olmayan pəncərədə (ölçüsü sabit) menyu onsuz da
  görünmür — ona görə orada `HTMAXBUTTON` heç vaxt qaytarılmır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ KİTABXANANIN SİNFİNDƏN MİRAS ALINMIR
──────────────────────────────────────────────────────────────────────────────
`WindowsFramelessWindow` bazası başlıq zolağını ÖRTÜK (overlay) kimi qurur və
öz `resizeEvent`-ində `titleBar.resize(...)` çağırır; KompasOS-un zolağı isə
`QVBoxLayout`-un birinci sətridir. Miras alınsaydı iki yerləşdirmə mexanizmi
eyni widget üzərində yarışardı.

İkinci və daha ağır səbəb: baza konstruktoru İDXAL ANINDA platformaya görə
seçilir və `_initFrameless()` dərhal Win32 API çağırır. Testlər
`QT_QPA_PLATFORM=offscreen` ilə (həm Windows-da, həm Linux CI-da) işləyir,
orada isə `winId()` REAL HWND deyil. Yəni miras bütün GUI test dəstini
platformadan asılı edərdi.

Ona görə kompozisiya seçilib: kitabxananın FUNKSİYALARI (üslub effekti, DPI-yə
həssas kənar qalınlığı, taskbar mövqeyi, maksimum vəziyyət keçidi) yenidən
işlədilir, sinif iyerarxiyası isə toxunulmur. Native örtük yalnız FAKTİKİ
`windows` platformasında qurulur; hər yerdə köhnə saf-Qt yolu qalır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from PySide6.QtGui import QGuiApplication

from src.shared.logger import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QRect

_log = get_logger(__name__)

# --------------------------------------------------------------------------- #
# Win32 sabitləri
# --------------------------------------------------------------------------- #
# NİYƏ `win32con`-dan OXUNMUR: bu modul Windows-dan kənarda da İDXAL OLUNUR
# (Linux CI, `import src.presentation.shell`). Sabitlər isə ABI-nin bir
# hissəsidir və 1985-dən bəri dəyişməyib — onları modul səviyyəsində yazmaq
# idxalı platformadan asılı olmaqdan azad edir. Faktiki API çağırışları
# (`win32gui`, `win32api`) `_load_win32()` içində, mühafizə altındadır.

_WM_NCCALCSIZE: Final = 0x0083
_WM_NCHITTEST: Final = 0x0084
_WM_NCMOUSEMOVE: Final = 0x00A0
_WM_NCLBUTTONDOWN: Final = 0x00A1
_WM_NCLBUTTONUP: Final = 0x00A2
_WM_NCMOUSELEAVE: Final = 0x02A2

_HTCLIENT: Final = 1
_HTCAPTION: Final = 2
_HTMAXBUTTON: Final = 9
_HTLEFT: Final = 10
_HTRIGHT: Final = 11
_HTTOP: Final = 12
_HTTOPLEFT: Final = 13
_HTTOPRIGHT: Final = 14
_HTBOTTOM: Final = 15
_HTBOTTOMLEFT: Final = 16
_HTBOTTOMRIGHT: Final = 17

#: `WVR_REDRAW` — `WM_NCCALCSIZE` cavabında müştəri sahəsinin tam yenidən
#: çəkilməsini istəyir; onsuz ölçü dəyişəndə köhnə piksellər qalırdı.
_WVR_REDRAW: Final = 0x0300

_SWP_NOMOVE: Final = 0x0002
_SWP_NOSIZE: Final = 0x0001
_SWP_NOZORDER: Final = 0x0004
_SWP_FRAMECHANGED: Final = 0x0020

_WM_SYSCOMMAND: Final = 0x0112
_WM_LBUTTONUP: Final = 0x0202
_SC_MAXIMIZE: Final = 0xF030
_SC_RESTORE: Final = 0xF120

#: Qt native hadisələri bu ad altında ötürür (Windows platform plugin-i).
NATIVE_EVENT_TYPE: Final = b"windows_generic_MSG"

#: Kənardan neçə piksel məsafədə kursor "ölçü dəyişdirmə" sayılır — OS
#: dəyəri oxuna bilmədikdə (DPI sorğusu uğursuz) işlədilən EHTİYAT dəyər.
#: Həqiqi mənbə `getResizeBorderThickness` (DPI-yə həssasdır).
FALLBACK_BORDER_PX: Final = 8


@dataclass(frozen=True)
class _Win32Api:
    """`_load_win32()`-un topladığı modul dəsti.

    Sahələr `Any`-dir: `pywin32` və `qframelesswindow` tip stub-u daşımır və
    onları saxta protokollarla təsvir etmək faydadan çox şərh gətirərdi.
    Bu qatın bütün istifadəsi aşağıdakı bir neçə metodla məhdudlaşır.
    """

    api: Any
    gui: Any
    utils: Any
    nccalcsize: Any
    effect: Any


_win32: _Win32Api | None = None
_win32_probed = False


def _load_win32() -> _Win32Api | None:
    """Win32 və `qframelesswindow` modullarını bir dəfə yükləyir.

    `None` → bu platformada native örtük mümkün deyil. Uğursuzluq SÜKUTLA
    ötürülmür: səbəb bir dəfə jurnala yazılır, çünki istehsalatda "snap
    işləmir" şikayətinin ilk sualı məhz budur.
    """
    # Modul səviyyəli keş: idxal cəhdi bir dəfə edilir (`PLW0603` layihə
    # miqyasında icazəlidir — bax `pyproject.toml`).
    global _win32, _win32_probed
    if _win32_probed:
        return _win32

    _win32_probed = True
    try:
        import win32api  # noqa: PLC0415
        import win32gui  # noqa: PLC0415
        from qframelesswindow.utils import win32_utils  # noqa: PLC0415
        from qframelesswindow.windows.c_structures import (  # noqa: PLC0415
            LPNCCALCSIZE_PARAMS,
        )
        from qframelesswindow.windows.window_effect import (  # noqa: PLC0415
            WindowsWindowEffect,
        )
    except ImportError as exc:
        _log.info("NATIVE_CHROME_UNAVAILABLE", extra={"reason": str(exc)})
        return None

    _win32 = _Win32Api(
        api=win32api,
        gui=win32gui,
        utils=win32_utils,
        nccalcsize=LPNCCALCSIZE_PARAMS,
        effect=WindowsWindowEffect,
    )
    return _win32


def is_supported() -> bool:
    """Native örtük bu prosesdə qurula bilərmi?

    İKİ şərt birlikdə yoxlanılır:

    1. Win32 modulları idxal olunur (Windows + `pywin32` quraşdırılıb).
    2. Qt FAKTİKİ olaraq `windows` platform plugin-i ilə işləyir.

    İkincisi olmadan `QT_QPA_PLATFORM=offscreen` altında `winId()` uydurma
    tam ədəd qaytarır və Win32 çağırışları yad pəncərələrə ünvanlanardı.
    Ona görə platforma adı ƏN ETİBARLI qapıdır — mühit dəyişəni oxumaqdan
    fərqli olaraq, o, Qt-nin faktiki qərarını əks etdirir.
    """
    if _load_win32() is None:
        return False
    app = QGuiApplication.instance()
    return app is not None and QGuiApplication.platformName() == "windows"


class NativeChromeHost(Protocol):
    """Native örtüyün pəncərədən soruşduğu suallar.

    Protokol qəsdən DARDIR: örtük pəncərənin daxili quruluşunu bilmir, yalnız
    "bu nöqtə sürüklənən sahədirmi", "böyüt düyməsi haradadır" kimi qərarları
    soruşur. Beləliklə eyni örtük gələcəkdə başqa pəncərə tipinə də taxıla
    bilər və test üçün saxta host yazmaq bir neçə sətirdir.
    """

    def native_window_id(self) -> int:
        """Pəncərənin HWND-i (0 → hələ yaradılmayıb)."""
        ...

    def native_is_resizable(self) -> bool:
        """Ölçü dəyişdirmə və maksimallaşdırma icazəlidirmi?"""
        ...

    def native_device_pixel_ratio(self) -> float:
        """Piksel sıxlığı — məntiqi Qt koordinatı ↔ fiziki piksel."""
        ...

    def native_is_drag_area(self, x: int, y: int) -> bool:
        """Məntiqi koordinat başlıq zolağının sürüklənən hissəsindədirmi?"""
        ...

    def native_maximize_button_rect(self) -> QRect | None:
        """Böyüt/bərpa düyməsinin məntiqi koordinatdakı düzbucaqlısı."""
        ...

    def native_set_maximize_hovered(self, hovered: bool) -> None:
        """Snap Layouts sahəsində kursor var/yox — düymənin görünüşü."""
        ...

    def native_set_maximize_pressed(self, pressed: bool) -> None:
        """Qeyri-müştəri sahədə siçan basıldı/buraxıldı."""
        ...

    def native_toggle_maximized(self) -> None:
        """Maksimum ↔ normal keçidi."""
        ...


class NativeWindowChrome:
    """Bir pəncərəyə native Windows davranışını əlavə edir.

    İstifadə (bax `window.py`):

        chrome = NativeWindowChrome(self)
        chrome.install()                      # üslublar + çərçivə yenilənməsi
        ...
        def nativeEvent(self, kind, message):
            handled = chrome.handle(kind, message)
            return handled if handled is not None else super().nativeEvent(...)
    """

    def __init__(self, host: NativeChromeHost) -> None:
        self._host = host
        self._effect: Any | None = None
        self._maximize_hovered = False

    # ------------------------------ quraşdırma ------------------------------- #

    def install(self) -> bool:
        """Pəncərə üslublarını native rejimə keçirir.

        Returns:
            Uğurlu olduqda `True`. `False` → çağıran tərəf saf-Qt yolunda
            qalır (heç nə pozulmur, sadəcə snap olmur).
        """
        win32 = _load_win32()
        handle = self._host.native_window_id()
        if win32 is None or not handle:
            return False

        try:
            # Kitabxananın öz effekt sinfi: `WS_CAPTION | WS_THICKFRAME |
            # WS_MAXIMIZEBOX | WS_MINIMIZEBOX` geri qoyulur (DWM üçün) və
            # kölgə bərpa edilir. Bu iki çağırış native davranışın ÖZƏYİDİR.
            self._effect = win32.effect(None)
            self._effect.addWindowAnimation(handle)
            self._effect.addShadowEffect(handle)
            if not self._host.native_is_resizable():
                # Ölçüsü sabit pəncərədə Snap Layouts menyusu yanıltıcı olardı:
                # menyu çıxar, seçim isə heç nə etməzdi.
                self._effect.disableMaximizeButton(handle)
            # Üslub dəyişikliyi yalnız çərçivə yenidən hesablananda qüvvəyə
            # minir — `SWP_FRAMECHANGED` `WM_NCCALCSIZE`-ı təkrar göndərir.
            win32.gui.SetWindowPos(
                handle,
                None,
                0,
                0,
                0,
                0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED,
            )
        except Exception:
            # Win32 çağırışı uğursuz olarsa tətbiq İŞLƏMƏYƏ DAVAM ETMƏLİDİR —
            # itirilən yalnız snap animasiyasıdır, funksionallıq deyil.
            _log.exception("NATIVE_CHROME_INSTALL_FAILED")
            self._effect = None
            return False

        _log.info("NATIVE_CHROME_INSTALLED", extra={"resizable": self._host.native_is_resizable()})
        return True

    @property
    def installed(self) -> bool:
        return self._effect is not None

    # -------------------------- hadisə emalı --------------------------------- #

    def handle(self, event_type: bytes, message: int) -> tuple[bool, int] | None:
        """Bir native mesajı emal edir.

        Returns:
            `(handled, result)` — Qt-yə birbaşa qaytarılır. `None` → mesaj
            bizim deyil, adi Qt emalı davam etsin.
        """
        win32 = _load_win32()
        if win32 is None or self._effect is None or bytes(event_type) != NATIVE_EVENT_TYPE:
            return None

        from ctypes.wintypes import MSG  # noqa: PLC0415

        msg = MSG.from_address(int(message))
        if not msg.hWnd:
            return None
        return self._dispatch(msg)

    def _dispatch(self, msg: Any) -> tuple[bool, int] | None:
        """Mesaj kodunu uyğun emalçıya yönləndirir."""
        message = msg.message
        if message == _WM_NCHITTEST:
            zone = self._hit_test(msg.hWnd, msg.lParam)
            return None if zone is None else (True, zone)
        if message == _WM_NCCALCSIZE:
            return self._calc_size(msg)
        if message == _WM_NCMOUSEMOVE:
            return self._on_nc_mouse_move(int(msg.wParam))
        if message == _WM_NCMOUSELEAVE:
            self._set_hovered(False)
            return None
        if message in (_WM_NCLBUTTONDOWN, _WM_NCLBUTTONUP):
            return self._on_nc_button(message, int(msg.wParam))
        return None

    # ------------------------------ hit-testing ------------------------------ #

    def _hit_test(self, handle: int, lparam: int) -> int | None:
        """`WM_NCHITTEST` cavabı: kənar → ölçü, düymə → Snap, zolaq → sürükləmə.

        SIRA VACİBDİR. Kənar zolağı başlığın ÜSTÜNDƏN keçir; əvvəlcə düymə
        yoxlansaydı, pəncərənin yuxarı kənarından hündürlük dəyişdirmək
        mümkün olmazdı, çünki böyüt düyməsi məhz o zolağın altındadır.
        """
        win32 = _load_win32()
        if win32 is None:
            return None

        try:
            screen_x, screen_y = _signed_point(lparam)
            x, y = win32.gui.ScreenToClient(handle, (screen_x, screen_y))
            left, top, right, bottom = win32.gui.GetClientRect(handle)
        except Exception:
            _log.debug("NATIVE_HITTEST_FAILED")
            return None

        width = right - left
        height = bottom - top
        resizable = self._host.native_is_resizable()
        maximized = _is_maximized(win32, handle)

        # Maksimallaşdırılmış pəncərədə kənar zolağı OLMUR: ekranın kənarına
        # yapışmış pəncərəni oradan tutmaq mümkün deyil, lakin zolaq qalsaydı
        # başlığın ilk 8 pikseli "ölçü dəyişdirmə" sayılar və sürükləyib
        # bərpa etmək çətinləşərdi.
        border = 0 if (maximized or not resizable) else self._border(win32, handle)

        edge = edge_zone(x, y, width, height, border)
        if edge is not None:
            return edge

        ratio = self._host.native_device_pixel_ratio() or 1.0
        logical_x = int(x / ratio)
        logical_y = int(y / ratio)

        # ─── Snap Layouts qapısı ───────────────────────────────────────────
        # Yalnız BURADA `HTMAXBUTTON` qaytarılır; Windows 11-in tərtibat
        # menyusunu açan yeganə siqnal budur.
        if resizable:
            button = self._host.native_maximize_button_rect()
            if button is not None and button.contains(logical_x, logical_y):
                return _HTMAXBUTTON

        if self._host.native_is_drag_area(logical_x, logical_y):
            return _HTCAPTION
        return _HTCLIENT

    def _border(self, win32: _Win32Api, handle: int) -> int:
        """Kənar zolağının qalınlığı — DPI-yə həssas (kitabxananın hesabı)."""
        try:
            thickness = int(win32.utils.getResizeBorderThickness(handle))
        except Exception:
            thickness = 0
        return thickness or FALLBACK_BORDER_PX

    # ----------------------------- çərçivə ölçüsü ---------------------------- #

    def _calc_size(self, msg: Any) -> tuple[bool, int]:
        """`WM_NCCALCSIZE`: qeyri-müştəri sahəni sıfırlayır.

        Maksimallaşdırılmış pəncərədə TAM sıfırlamaq olmaz — Windows belə
        pəncərəni qəsdən çərçivə qalınlığı qədər BÖYÜK edir (kənarların
        ekrandan kənara çıxması üçün). Düzəliş edilməsəydi, məzmunun hər
        tərəfindən bir neçə piksel ekrandan kənarda qalardı.

        Avtomatik gizlənən tapşırıq paneli üçün 2px pay saxlanılır: tam ekranı
        örtən pəncərə panelin geri çıxmasını bloklayır və istifadəçi ona bir
        daha çata bilmirdi (kitabxananın həlli ilə eyni).
        """
        win32 = _load_win32()
        assert win32 is not None  # `handle()` onsuz bura gəlmir

        from ctypes import cast  # noqa: PLC0415
        from ctypes.wintypes import LPRECT  # noqa: PLC0415

        if msg.wParam:
            rect = cast(msg.lParam, win32.nccalcsize).contents.rgrc[0]
        else:
            rect = cast(msg.lParam, LPRECT).contents

        maximized = _is_maximized(win32, msg.hWnd)
        fullscreen = _is_fullscreen(win32, msg.hWnd)

        if maximized and not fullscreen:
            vertical = win32.utils.getResizeBorderThickness(msg.hWnd, False)
            horizontal = win32.utils.getResizeBorderThickness(msg.hWnd, True)
            rect.top += vertical
            rect.bottom -= vertical
            rect.left += horizontal
            rect.right -= horizontal

        if (maximized or fullscreen) and _taskbar_autohides(win32):
            _inset_for_taskbar(win32, msg.hWnd, rect)

        return True, (_WVR_REDRAW if msg.wParam else 0)

    # -------------------------- qeyri-müştəri siçan -------------------------- #

    def _on_nc_mouse_move(self, zone: int) -> tuple[bool, int] | None:
        """Kursor qeyri-müştəri sahədə hərəkət edir.

        Böyüt düyməsi artıq Qt üçün "görünməzdir" (`HTMAXBUTTON` onu qeyri-
        müştəri sahəyə çevirir), ona görə hover görünüşü buradan idarə olunur.
        Mesaj UDULMUR (`None`): `DefWindowProc` `WM_NCMOUSELEAVE` izləməsini
        özü qurur, biz onu kəssək tərk hadisəsi heç vaxt gəlməzdi və düymə
        həmişəlik "hover" qalardı.
        """
        self._set_hovered(zone == _HTMAXBUTTON)
        return None

    def _on_nc_button(self, message: int, zone: int) -> tuple[bool, int] | None:
        """Böyüt düyməsinə qeyri-müştəri klik.

        `DefWindowProc`-a buraxılsaydı, Windows öz (mövcud olmayan) çərçivə
        düyməsini idarə etməyə çalışar və klik itərdi. Basılma ANINDA yox,
        BURAXILMA anında işə salınır — masaüstü konvensiyası budur: düymənin
        üstündən sürüşdürüb kənarda buraxan istifadəçi əməliyyatı ləğv edir.
        """
        if zone != _HTMAXBUTTON:
            return None
        if message == _WM_NCLBUTTONDOWN:
            self._host.native_set_maximize_pressed(True)
            return True, 0

        self._host.native_set_maximize_pressed(False)
        self._host.native_toggle_maximized()
        return True, 0

    def _set_hovered(self, hovered: bool) -> None:
        if hovered == self._maximize_hovered:
            return
        self._maximize_hovered = hovered
        self._host.native_set_maximize_hovered(hovered)
        if not hovered:
            self._host.native_set_maximize_pressed(False)

    # ------------------------------ vəziyyət --------------------------------- #

    def toggle_maximized(self) -> bool:
        """Maksimum ↔ normal — Windows-un öz animasiyası ilə.

        `showMaximized()` ƏVƏZİNƏ `WM_SYSCOMMAND` göndərilir. Fərq görünür:
        Qt-nin metodu pəncərənin vəziyyətini birbaşa dəyişir, DWM isə keçid
        animasiyasını YALNIZ sistem əmri ilə oynadır — yəni düymə ilə böyütmək
        "sıçrayır", `Win`+`↑` isə sürüşürdü. Eyni əmr kitabxananın
        `WindowsMoveResize.toggleMaxState`-ində də seçilib.

        Sonrakı `WM_LBUTTONUP` MƏCBURİDİR: keçid qeyri-müştəri klikdən
        (Snap Layouts sahəsi) gələ bilər və Qt həmin halda siçan düyməsini
        hələ də "basılı" sayardı — növbəti klik itərdi.

        Returns:
            `False` → native yol mövcud deyil, çağıran tərəf öz yolunu işlətsin.
        """
        win32 = _load_win32()
        handle = self._host.native_window_id()
        if win32 is None or self._effect is None or not handle:
            return False
        try:
            command = _SC_RESTORE if _is_maximized(win32, handle) else _SC_MAXIMIZE
            win32.gui.PostMessage(handle, _WM_SYSCOMMAND, command, 0)
            win32.api.SendMessage(handle, _WM_LBUTTONUP, 0, 0)
        except Exception:
            _log.exception("NATIVE_TOGGLE_MAX_FAILED")
            return False
        return True


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


#: `(üfüqi, şaquli)` → `HT*` kodu. `-1` = sol/yuxarı, `0` = orta, `1` = sağ/aşağı.
#:
#: NİYƏ CƏDVƏL, NİYƏ SƏKKİZ `if`: səkkiz budaq eyni məntiqi səkkiz dəfə
#: təkrarlayırdı və birində "sol-alt"un yerinə "sağ-alt" yazmaq gözlə tutulmur
#: — hər ikisi diaqonaldır və simptom yalnız kursorun səhv künclə dartılması
#: kimi görünərdi. Cədvəldə uyğunluq bir baxışda oxunur.
_EDGE_CODES: Final[dict[tuple[int, int], int]] = {
    (-1, -1): _HTTOPLEFT,
    (0, -1): _HTTOP,
    (1, -1): _HTTOPRIGHT,
    (-1, 0): _HTLEFT,
    (1, 0): _HTRIGHT,
    (-1, 1): _HTBOTTOMLEFT,
    (0, 1): _HTBOTTOM,
    (1, 1): _HTBOTTOMRIGHT,
}


def edge_zone(x: int, y: int, width: int, height: int, border: int) -> int | None:
    """Nöqtə hansı ölçü-dəyişdirmə kənarındadır (`None` → daxildədir).

    Saf funksiyadır və Win32-siz test olunur — hit-testing məntiqinin YEGANƏ
    riyazi hissəsi budur, qalanı OS sorğularıdır.
    """
    if border <= 0:
        return None
    horizontal = -1 if x < border else (1 if x > width - border else 0)
    vertical = -1 if y < border else (1 if y > height - border else 0)
    return _EDGE_CODES.get((horizontal, vertical))


#: 16 bitlik işarəli ədədin işarə biti və tam diapazonu.
_SIGN_BIT_16: Final = 0x8000
_WORD_RANGE: Final = 0x10000


def _signed_point(lparam: int) -> tuple[int, int]:
    """`lParam`-dakı iki 16-bitlik İŞARƏLİ koordinatı ayırır.

    NİYƏ `GetCursorPos()` DEYİL: kursorun cari yeri mesajın göndərildiyi andan
    fərqli ola bilər (xüsusən sürükləmə və Snap Layouts zondlarında). Mesajın
    ÖZ koordinatı həqiqətdir.

    Koordinat MƏNFİ ola bilər — çox monitorlu quraşdırmada soldakı ekranın
    x-i mənfidir; işarəsiz oxunsaydı 65 000-ə yaxın nəhəng ədəd alınardı və
    hit-test heç vaxt uyğun gəlməzdi.
    """
    low = lparam & 0xFFFF
    high = (lparam >> 16) & 0xFFFF
    x = low - _WORD_RANGE if low >= _SIGN_BIT_16 else low
    y = high - _WORD_RANGE if high >= _SIGN_BIT_16 else high
    return x, y


def _is_maximized(win32: _Win32Api, handle: int) -> bool:
    try:
        return bool(win32.utils.isMaximized(handle))
    except Exception:
        return False


def _is_fullscreen(win32: _Win32Api, handle: int) -> bool:
    try:
        return bool(win32.utils.isFullScreen(handle))
    except Exception:
        return False


def _taskbar_autohides(win32: _Win32Api) -> bool:
    try:
        return bool(win32.utils.Taskbar.isAutoHide())
    except Exception:
        return False


def _inset_for_taskbar(win32: _Win32Api, handle: int, rect: Any) -> None:
    """Avtomatik gizlənən tapşırıq paneli üçün 2px pay saxlayır."""
    taskbar = win32.utils.Taskbar
    try:
        position = taskbar.getPosition(handle)
    except Exception:
        return
    thickness = taskbar.AUTO_HIDE_THICKNESS
    if position == taskbar.TOP:
        rect.top += thickness
    elif position == taskbar.BOTTOM:
        rect.bottom -= thickness
    elif position == taskbar.LEFT:
        rect.left += thickness
    elif position == taskbar.RIGHT:
        rect.right -= thickness


__all__ = [
    "FALLBACK_BORDER_PX",
    "NATIVE_EVENT_TYPE",
    "NativeChromeHost",
    "NativeWindowChrome",
    "edge_zone",
    "is_supported",
]
