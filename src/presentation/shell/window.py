"""Çərçivəsiz pəncərə bazası — Faza 4.2 (native örtüklə genişləndirilib).

Spesifikasiya admin ekranları üçün öz başlıq zolağını tələb edir, yəni Windows
çərçivəsi söndürülür (`FramelessWindowHint`). Bunun İKİ nəticəsi var və hər
ikisi burada bərpa olunur:

    1. **Ölçü dəyişdirmə itir.** Çərçivəsiz pəncərənin kənarından tutub
       böyütmək mümkün olmur. `QWindow.startSystemResize()` idarəni OS-ə verir
       — Aero Snap, çox-monitor DPI və toxunma dəstəyi beləliklə saxlanılır.
       Əl ilə `setGeometry()` yazmaq bunların hamısını itirərdi.

    2. **Maksimallaşdırma ekranı örtür.** Çərçivəsiz pəncərə maksimuma
       keçəndə tapşırıq panelinin (taskbar) üstünə çıxır. `showMaximized()`
       əvəzinə `availableGeometry()` işlədilir — nəticə istifadəçinin
       gözlədiyi davranışdır.

──────────────────────────────────────────────────────────────────────────────
İKİ YOL: NATIVE VƏ SAF-QT
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı iki bənd HƏLƏ DƏ doğrudur — lakin onlar yalnız EHTİYAT yoldur.
Windows-da (faktiki `windows` platform plugin-i ilə) pəncərə indi native
örtüklə işləyir: `shell/native_chrome.py` `WM_NCHITTEST`/`WM_NCCALCSIZE`
mesajlarını emal edir və DWM həm Aero Snap-i, həm Windows 11 Snap Layouts
menyusunu ÖZÜ verir.

Native yol qurula bilmədikdə (Linux, macOS, `offscreen` test platforması,
`pywin32` yoxdur) əvvəlki saf-Qt kodu bir hərf də dəyişmədən işləyir. Ona görə
`_edge_at`, `_cursor_for` və əl ilə maksimallaşdırma SİLİNMİR: onlar həmin
mühitlərdə pəncərənin ölçüsünü dəyişməyin yeganə yoludur.

──────────────────────────────────────────────────────────────────────────────
TƏRTİBAT REJİMİ (RESPONSIVE) NİYƏ BURADADIR
──────────────────────────────────────────────────────────────────────────────
Pəncərə eni yalnız BU obyektə məlumdur — sol panel özünü 226px, ekran isə
"pəncərə mənfi panel" görür. Ölçən tək yer olmalıdır, yoxsa hədd hər widget
üçün başqa şey ifadə edərdi (bax `shell/responsive.py` başlığı). Ona görə
`resizeEvent` bir siqnal yayır və abunəçilər (`AdminShell` → sol panel →
ekranlar) ona reaksiya verir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.presentation.shell import native_chrome
from src.presentation.theme.tokens import ThemeMode
from src.presentation.widgets import metrics
from src.presentation.widgets.layout_utils import detach_layout
from src.presentation.widgets.responsive import LayoutMode, mode_for_width
from src.presentation.widgets.title_bar import TitleBar
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent, QResizeEvent, QShowEvent

    from src.presentation.theme.manager import ThemeManager

_log = get_logger(__name__)

#: Kənardan neçə piksel məsafədə kursor "ölçü dəyişdirmə" sayılır.
#: YALNIZ saf-Qt yolunda işlənir — native örtükdə həddi OS özü verir (DPI-yə
#: həssas `getResizeBorderThickness`).
_RESIZE_MARGIN: Final = 6


class FramelessWindow(QWidget):
    """Öz başlıq zolağı olan, ölçüsü dəyişdirilə bilən pəncərə.

    Args:
        title: Başlıq mətni.
        resizable: `False` → kiosk/bloklama ekranları (ölçü sabit).
        show_title_bar: `False` → tam ekran kiosk (başlıq zolağı yoxdur).
        theme: Verilərsə pəncərə düymələrinin İKONLARI tema rənglərinə
            köklənir və tema dəyişikliyinə abunə olunur. `None` → ikonlar
            işıqlı temanın tokenləri ilə çəkilir (dizayn önizləməsi, testlər).

    Signals:
        layout_mode_changed: Pəncərə eni tərtibat həddini keçdi
            (`LayoutMode` dəyəri). Bax `shell/responsive.py`.
        theme_toggle_requested: Başlıq zolağındakı tema düyməsi basıldı.
    """

    layout_mode_changed = Signal(str)
    #: Başlıq zolağı HƏR ekranda var (splash, sihirbaz, giriş, örtük) — ona
    #: görə tema keçidi buradan da mümkündür. Pəncərə temanı ÖZÜ dəyişmir,
    #: yalnız siqnalı ötürür (bax `apply_theme` yanındakı izah).
    theme_toggle_requested = Signal()

    def __init__(
        self,
        *,
        title: str = "KompasOS",
        resizable: bool = True,
        show_title_bar: bool = True,
        theme: ThemeManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AppWindow")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle(title)
        # MİNİMUM ölçü ilə İLK AÇILIŞ ölçüsü ayrılır: minimum 1280 qaldıqca
        # Windows-un yarım-ekran snap-i fiziki olaraq mümkün deyildi (səbəb
        # `metrics.WINDOW_HARD_MIN_WIDTH` yanında).
        self.setMinimumSize(metrics.WINDOW_HARD_MIN_WIDTH, metrics.WINDOW_HARD_MIN_HEIGHT)
        self.resize(metrics.WINDOW_MIN_WIDTH, metrics.WINDOW_MIN_HEIGHT)

        self._resizable = resizable
        self._theme = theme
        if resizable:
            # Kənar zonasını tutmaq üçün siçan hərəkəti izlənməlidir.
            self.setMouseTracking(True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._title_bar: TitleBar | None = None
        if show_title_bar:
            self._title_bar = TitleBar(title=title, show_maximize=resizable)
            self._title_bar.minimize_requested.connect(self.showMinimized)
            self._title_bar.maximize_requested.connect(self.toggle_maximized)
            self._title_bar.close_requested.connect(self.close)
            # Tema siqnalı pəncərədən YUXARI ötürülür — `KompasApplication`
            # onu `toggle_theme()`-ə bağlayır. Pəncərə temanı ÖZÜ dəyişmir:
            # keçid animasiyası, örtük ikonları və saxlanmış tercih bir yerdə,
            # `app.py`-də idarə olunur.
            self._title_bar.theme_toggle_requested.connect(self.theme_toggle_requested)
            self._layout.addWidget(self._title_bar)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        self._layout.addWidget(self._body, 1)

        self._normal_geometry: QRect | None = None
        self._layout_mode = mode_for_width(self.width())

        if theme is not None:
            self.apply_theme(theme)

        # Native örtük KONSTRUKTORDA qurulur, `showEvent`-də deyil: üslub
        # dəyişikliyi (`WS_THICKFRAME` və s.) pəncərə ekranda görünməmişdən
        # ƏVVƏL tətbiq olunmalıdır, əks halda ilk kadrda Windows öz çərçivəsini
        # bir anlıq çəkir və "sayrışma" görünür.
        self._native: native_chrome.NativeWindowChrome | None = None
        if native_chrome.is_supported():
            chrome = native_chrome.NativeWindowChrome(self)
            # `winId()` native pəncərəni MƏCBUR yaradır — HWND onsuz yoxdur.
            self.winId()
            if chrome.install():
                self._native = chrome

    # ------------------------------- məzmun --------------------------------- #

    def set_content(self, widget: QWidget) -> None:
        """Başlıq zolağının altındakı əsas məzmunu təyin edir.

        Köhnə ekran MƏHV olur və fokuslu düyməsi onunla birlikdə gedir. Qt
        həmin anda fokusu zəncirin növbəti elementinə — başlıq zolağına —
        `TabFocusReason` ilə ötürür; halqa məntiqi isə bu səbəbi klaviatura
        fokusu sayır (bax `KeyFocusRingMixin.clear_key_focus_ring`). Nəticədə
        istifadəçi düyməni SİÇANLA basandan sonra tema düyməsinin
        işıqlandığını görürdü. Halqa burada söndürülür, çünki keçidin ekran
        əvəzlənməsi olduğunu YALNIZ bu metod bilir.
        """
        detach_layout(self._body_layout)
        self._body_layout.addWidget(widget)
        if self._title_bar is not None:
            self._title_bar.clear_key_focus_rings()

    def title_bar(self) -> TitleBar | None:
        """Başlıq zolağı — adı dəyişmək üçün (`"KompasOS — Master"`)."""
        return self._title_bar

    # -------------------------------- tema ----------------------------------- #

    def apply_theme(self, theme: ThemeManager) -> None:
        """Pəncərə düymələrinin ikon rənglərini temaya uyğunlaşdırır.

        QSS fonu və mətn rəngini özü verir, lakin ikon piksel şəklidir və QSS
        onu boyamır (bax `widgets/buttons.py` başlığı) — ona görə rənglər
        Python tərəfdən ötürülür.
        """
        self._theme = theme
        if self._title_bar is None:
            return
        self._title_bar.apply_theme(
            control_color=theme.color("--color-titlebar-control"),
            hover_color=theme.color("--color-titlebar-text"),
            # Bağla düyməsi hover-da QIRMIZI fon alır (Windows/Chrome
            # konvensiyası) — ikon həmin fonun üzərində oxunmalıdır, ona görə
            # rəng `qss.py`-dakı `color:` qaydası ilə EYNİ tokendəndir.
            close_hover_color=theme.color("--color-bg-primary"),
            # LOQO DÜYMƏ RƏNGİNDƏ DEYİL, MARKA RƏNGİNDƏDİR (logo.md).
            # Düymələr ikinci dərəcəli idarəetmədir və solğun tonda olur;
            # loqo isə markanın özüdür — eyni solğunluqda çəkilsəydi zolaqda
            # «sönük» görünərdi. Dəyər loqo faylının ÖZ rəngidir (açıq teal),
            # yəni eyni marka iki yerdə iki cür görünmür (bax `tokens.py`,
            # `BRAND_TEAL_LIGHT` şərhi və `windows_app.png` referansı).
            brand_mark_color=theme.color("--color-brand-mark"),
            # Düymə NƏTİCƏNİ göstərir: tünd rejimdə «günəş» (bax
            # `TitleBar.set_theme_icon`).
            dark_mode=theme.mode is ThemeMode.DARK,
        )

    # --------------------------- maksimallaşdırma ---------------------------- #

    def toggle_maximized(self) -> None:
        """Maksimum/normal arasında keçid.

        Native örtük varsa əmr OS-ə verilir (DWM animasiyası ilə). Əks halda
        `showMaximized()` çərçivəsiz pəncərədə tapşırıq panelini örtür, ona
        görə əlçatan sahə (`availableGeometry`) əl ilə tətbiq olunur.
        """
        if not self._resizable:
            return
        if self._native is not None and self._native.toggle_maximized():
            return

        if self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
            self._normal_geometry = None
            self._sync_maximize_button()
            return

        screen = self.screen() or QGuiApplication.primaryScreen()
        self._normal_geometry = self.geometry()
        self.setGeometry(screen.availableGeometry())
        self._sync_maximize_button()

    @property
    def is_maximized(self) -> bool:
        """Pəncərə maksimallaşdırılıbmı?

        Native rejimdə cavab OS-dədir (`Win`+`↑`, Aero Snap və tapşırıq
        panelindən böyütmə də vəziyyəti dəyişir), saf-Qt rejimində isə əl ilə
        saxlanılan həndəsədir.
        """
        if self._native is not None:
            return self.isMaximized()
        return self._normal_geometry is not None

    def _sync_maximize_button(self) -> None:
        """Düymənin nişanını faktiki vəziyyətlə uzlaşdırır."""
        if self._title_bar is not None:
            self._title_bar.set_maximized(self.is_maximized)

    # --------------------------- tərtibat rejimi ----------------------------- #

    @property
    def layout_mode(self) -> LayoutMode:
        """Cari tərtibat rejimi — yeni abunəçi onu dərhal soruşa bilir."""
        return self._layout_mode

    def _update_layout_mode(self) -> None:
        """Eni ölçür və rejim DƏYİŞİBSƏ siqnal yayır.

        Siqnal yalnız KEÇİDDƏ yayılır, hər piksel dəyişikliyində yox: sol
        paneli və bütün kart şəbəkəsini saniyədə onlarla dəfə yenidən qurmaq
        sürükləmə zamanı görünən ləngimə yaradardı.
        """
        mode = mode_for_width(self.width())
        if mode is self._layout_mode:
            return
        self._layout_mode = mode
        _log.debug("LAYOUT_MODE_CHANGED", extra={"mode": mode.value, "width": self.width()})
        self.layout_mode_changed.emit(mode.value)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt adlandırması
        super().resizeEvent(event)
        self._update_layout_mode()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt adlandırması
        """İlk göstərmədə rejimi yayır — abunəçilər pəncərədən SONRA qoşulur.

        `set_content()` çağırılan anda ekran hələ mövcud deyil, yəni ilk
        `resizeEvent` heç kimə çatmır. Göstərmə anında rejim yenidən elan
        olunur ki, artıq daralmış pəncərədə açılan tətbiq DƏRHAL düzgün
        görünsün.
        """
        super().showEvent(event)
        self._layout_mode = mode_for_width(self.width())
        self.layout_mode_changed.emit(self._layout_mode.value)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Pəncərə vəziyyəti dəyişdi — böyüt/bərpa nişanı uzlaşdırılır.

        Vəziyyəti yalnız bizim düymə dəyişmir: Aero Snap, `Win`+`↑`, tapşırıq
        panelindən böyütmə və Snap Layouts menyusu da onu dəyişir. Nişan
        yalnız öz klikimizə baxsaydı, həmin hallarda YANLIŞ qalardı.
        """
        super().changeEvent(event)
        if event.type() is QEvent.Type.WindowStateChange:
            self._sync_maximize_button()

    # ---------------------------- native örtük -------------------------------- #

    @property
    def native_chrome_active(self) -> bool:
        """Native Windows örtüyü quruldumu? (diaqnostika və testlər üçün)"""
        return self._native is not None

    def nativeEvent(  # noqa: N802 - Qt adlandırması
        self,
        eventType: QByteArray | bytes | bytearray | memoryview,  # noqa: N803 - Qt imzası
        message: int,
    ) -> object:
        """Windows mesajlarını native örtüyə yönləndirir.

        Örtük qurulmayıbsa (başqa platforma) heç nə dəyişmir — Qt öz emalını
        aparır.
        """
        if self._native is not None:
            # Qt bu parametri `QByteArray` kimi verir; `bytes()` onu birbaşa
            # qəbul etmir, ona görə `data()` üzərindən keçirilir.
            raw = eventType.data() if isinstance(eventType, QByteArray) else eventType
            handled = self._native.handle(bytes(raw), message)
            if handled is not None:
                return handled
        return super().nativeEvent(eventType, message)

    # ------------------- native örtüyün soruşduğu suallar --------------------- #
    # Bunlar `native_chrome.NativeChromeHost` protokolunu ödəyir. Protokol
    # STRUKTURDUR (miras yoxdur) — pəncərə kitabxananın sinif iyerarxiyasından
    # asılı olmur (səbəb `native_chrome.py` başlığında).

    def native_window_id(self) -> int:
        handle = self.windowHandle()
        return int(handle.winId()) if handle is not None else 0

    def native_is_resizable(self) -> bool:
        return self._resizable

    def native_device_pixel_ratio(self) -> float:
        handle = self.windowHandle()
        return handle.devicePixelRatio() if handle is not None else self.devicePixelRatioF()

    def native_is_drag_area(self, x: int, y: int) -> bool:
        if self._title_bar is None:
            return False
        local = self._title_bar.mapFrom(self, QPoint(x, y))
        return self._title_bar.is_drag_region(local)

    def native_maximize_button_rect(self) -> QRect | None:
        if self._title_bar is None:
            return None
        button = self._title_bar.maximize_button()
        if not button.isVisible():
            return None
        return QRect(button.mapTo(self, QPoint(0, 0)), button.size())

    def native_set_maximize_hovered(self, hovered: bool) -> None:
        if self._title_bar is not None:
            self._title_bar.maximize_button().set_hovered(hovered)

    def native_set_maximize_pressed(self, pressed: bool) -> None:
        if self._title_bar is not None:
            self._title_bar.maximize_button().setDown(pressed)

    def native_toggle_maximized(self) -> None:
        self.toggle_maximized()

    # --------------------------- ölçü dəyişdirmə ----------------------------- #

    def _edge_at(self, x: int, y: int) -> Qt.Edge | None:
        """Kursorun hansı kənarda olduğunu qaytarır (yoxdursa `None`).

        Native örtük aktivdirsə bu kod HEÇ VAXT işə düşmür: `WM_NCHITTEST`
        kənarları OS-ə bildirir və siçan hadisəsi Qt-yə gəlmir. Saf-Qt
        yolunda isə ölçü dəyişdirmənin yeganə mənbəyidir.
        """
        if not self._resizable or self.is_maximized:
            return None

        left = x <= _RESIZE_MARGIN
        right = x >= self.width() - _RESIZE_MARGIN
        top = y <= _RESIZE_MARGIN
        bottom = y >= self.height() - _RESIZE_MARGIN

        edges: Qt.Edge | None = None
        for active, edge in (
            (left, Qt.Edge.LeftEdge),
            (right, Qt.Edge.RightEdge),
            (top, Qt.Edge.TopEdge),
            (bottom, Qt.Edge.BottomEdge),
        ):
            if active:
                edges = edge if edges is None else edges | edge
        return edges

    @staticmethod
    def _cursor_for(edge: Qt.Edge | None) -> Qt.CursorShape:
        if edge is None:
            return Qt.CursorShape.ArrowCursor
        horizontal = bool(edge & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edge & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            # Diaqonal: sol-üst/sağ-alt eyni oxdadır.
            top_left = bool(edge & Qt.Edge.TopEdge) == bool(edge & Qt.Edge.LeftEdge)
            return Qt.CursorShape.SizeFDiagCursor if top_left else Qt.CursorShape.SizeBDiagCursor
        if horizontal:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        position = event.position().toPoint()
        self.setCursor(self._cursor_for(self._edge_at(position.x(), position.y())))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        position = event.position().toPoint()
        edge = self._edge_at(position.x(), position.y())
        handle = self.windowHandle()
        if edge is not None and handle is not None and event.button() is Qt.MouseButton.LeftButton:
            handle.startSystemResize(edge)
            event.accept()
            return
        super().mousePressEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt adlandırması
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)


__all__ = ["FramelessWindow"]
