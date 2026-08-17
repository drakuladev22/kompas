"""Custom pəncərə başlığı — Faza 4.2.

Spesifikasiya (bölmə "PLATFORMA QAYDALARI"):

    "Admin ekranları öz custom title bar-ına malikdir: sol küncdə kiçik loqo +
     «KompasOS» mətni, sağ küncdə Windows pəncərə düymələri (—, □, ×)."

──────────────────────────────────────────────────────────────────────────────
SÜRÜKLƏMƏ NİYƏ `startSystemMove()` İLƏDİR
──────────────────────────────────────────────────────────────────────────────
Çərçivəsiz pəncərəni `move()` ilə əl ilə sürükləmək mümkündür, lakin o zaman
Windows-un ÖZ davranışları itir: ekranın kənarına çəkib yarım-ekrana yapışdırma
(Aero Snap), çox-monitorlu DPI keçidi və toxunma ekranında sürükləmə.
`QWindow.startSystemMove()` idarəni OS-ə verir, yəni bu davranışlar pulsuz
gəlir. Uğursuz olarsa (bəzi platformalarda dəstəklənmir) əl ilə sürükləməyə
qayıdılır — ona görə `_drag_origin` hələ də saxlanılır.

──────────────────────────────────────────────────────────────────────────────
WINDOWS-DA BU KOD ARTIQ İŞLƏMİR (VƏ BU, DÜZGÜNDÜR)
──────────────────────────────────────────────────────────────────────────────
Native pəncərə örtüyü qurulduqda (`shell/native_chrome.py`) başlıq zolağının
sürüklənən sahəsi `WM_NCHITTEST`-də `HTCAPTION` qaytarır — yəni Windows həmin
sahəni QEYRİ-MÜŞTƏRİ sahə sayır və siçan hadisələri Qt-yə HEÇ GƏLMİR. Aşağıdakı
`mousePressEvent` o platformada sadəcə çağırılmır; sürükləmə, snap, sağ-klik
sistem menyusu və ikiqat klik tamamilə OS-dədir.

Kod yenə də saxlanılır: Linux/macOS-da, `offscreen` platformasında (testlər) və
native örtüyün qurula bilmədiyi hallarda YEGANƏ sürükləmə yoludur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import brand_assets, icons, metrics
from src.presentation.widgets.buttons import KeyFocusIconButton, WindowButton
from src.presentation.widgets.live_clock import LiveClock
from src.presentation.widgets.primitives import image_label, plain_label

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QMouseEvent

    from src.domain.interfaces.ports import Clock
    from src.domain.value_objects.time_integrity import TimeIntegrityStatus


class TitleBar(QWidget):
    """38px hündürlüyündə pəncərə başlığı.

    Signals:
        minimize_requested: — düyməsi.
        maximize_requested: □ düyməsi (və ya zolağa ikiqat klik).
        close_requested: × düyməsi.
        theme_toggle_requested: İşıqlı ↔ tünd keçidi.
    """

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()
    #: ──────────────────────────────────────────────────────────────────────
    #: TEMA DÜYMƏSİ NİYƏ BAŞLIQ ZOLAĞINDADIR
    #: ──────────────────────────────────────────────────────────────────────
    #: Əvvəl o, YALNIZ səhifə başlığında (`page_header.py`) idi — həmin başlıq
    #: isə `AdminShell`-in içindədir, yəni GİRİŞDƏN SONRA görünür. Nəticə
    #: istifadəçi hesabatı ilə üzə çıxdı: «işıqlı/qaranlıq mod işləmir».
    #: Mexanizm işləyirdi; İlk Quraşdırma Sihirbazında, giriş və splash
    #: ekranlarında onu basmaq üçün DÜYMƏ yox idi və defolt `SYSTEM` olduğu
    #: üçün Windows tünd rejimdəsə hər şey tünd açılırdı.
    #:
    #: Başlıq zolağı HƏR ekranda var (splash, sihirbaz, giriş, örtük), ona görə
    #: düymənin yeri buradır. Səhifə başlığındakı düymə SİLİNMİR: örtük
    #: içindəkilər üçün o, əlin altındakı yerdədir və hər ikisi eyni siqnala
    #: bağlanır.
    theme_toggle_requested = Signal()

    def __init__(
        self,
        *,
        title: str = "KompasOS",
        show_maximize: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        enable_styled_background(self)
        self.setFixedHeight(metrics.TITLEBAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._drag_origin: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(12)

        # ------------------------------------------------------------------
        # LOQO — RƏNGLİ KVADRAT DEYİL, ƏSL PƏRGAR İŞARƏSİ (logo.md)
        # ------------------------------------------------------------------
        # Əvvəl burada `#TitleBarLogo` QSS ilə boyanan BOŞ `QWidget` vardı,
        # yəni zolaqda markanın özü deyil, rəngli kvadrat görünürdü.
        # `16_withoutcontainer.png` konteynersizdir və məhz bunun üçündür:
        # zolağın öz tünd fonu var, rozet artıq olardı.
        #
        # Fayl SABİT tünd-teal rəngdədir və tünd zolaqda görünməzdi — ona görə
        # o, ALFA MASKASI kimi işlədilir və rəng `apply_theme`-dən gəlir
        # (bax `widgets/brand_assets.py`). Şəkil tapılmasa köhnə kvadrat
        # QALIR: loqonun olmaması pəncərəni açılmaz etməməlidir.
        self._logo = image_label()
        self._logo.setObjectName("TitleBarLogo")
        self._logo.setFixedSize(metrics.TITLEBAR_LOGO_SIZE, metrics.TITLEBAR_LOGO_SIZE)
        layout.addWidget(self._logo)

        self._title = plain_label(title)
        layout.addWidget(self._title)

        layout.addStretch(1)

        # ------------------------------------------------------------------
        # CANLI SAAT — SERVER VAXTI (TIME-1)
        # ------------------------------------------------------------------
        # Yeri qəsdən pəncərə düymələrinin SOLUNDADIR: zolağın sağ küncü
        # OS-in idarə düymələrinə aiddir və istifadəçi oraya "bağla" gözləyir.
        # Saat mərkəzə qoyulsaydı başlıq mətni ilə yer üstündə yarışardı.
        #
        # Mənbə verilməyənə qədər BOŞDUR və taymeri işləmir — maket/önizləmə
        # yolu saatsız qurulur (bax `live_clock.py` başlığı).
        self._clock_widget = LiveClock()
        layout.addWidget(self._clock_widget)

        # Tema düyməsi pəncərə düymələrindən ƏVVƏL gəlir: sağ künc OS-in
        # «bağla» sahəsidir və istifadəçi oraya səhvən basmamalıdır.
        # İkon `WindowButton` DEYİL — o, minimize/maximize/close ailəsinin
        # görünüşünü daşıyır və tema keçidi OS əməliyyatı kimi oxunardı.
        # ÖLÇÜ PƏNCƏRƏ DÜYMƏLƏRİ İLƏ EYNİDİR (navbar.md PROBLEM 3 bənd 3).
        # 34×34 kvadrat qalsaydı, tam hündürlüklü düzbucaqlı düymələrin yanında
        # «dairə» kimi oxunardı — istifadəçi hesabatı bunu belə təsvir etdi.
        self._theme_button = KeyFocusIconButton(
            "moon",
            "",
            tooltip="Görünüşü dəyiş",
            accessible_name="Görünüş rejimini dəyiş",
            accessible_description="İşıqlı və tünd tema arasında keçid edir",
            width=metrics.WINDOW_BUTTON_WIDTH,
            height=metrics.TITLEBAR_HEIGHT,
        )
        self._theme_button.clicked.connect(self.theme_toggle_requested)
        layout.addWidget(self._theme_button)

        self._minimize = WindowButton("minimize")
        self._minimize.clicked.connect(self.minimize_requested)
        layout.addWidget(self._minimize)

        self._maximize = WindowButton("maximize")
        self._maximize.clicked.connect(self.maximize_requested)
        self._maximize.setVisible(show_maximize)
        layout.addWidget(self._maximize)

        self._close = WindowButton("close")
        self._close.clicked.connect(self.close_requested)
        layout.addWidget(self._close)

    # ------------------------------- məzmun --------------------------------- #

    def set_title(self, title: str) -> None:
        """Başlıq mətnini dəyişir — Developer Panelində "KompasOS — Master"."""
        self._title.setText(title)

    def set_clock_source(
        self,
        clock: Clock,
        *,
        status: Callable[[], TimeIntegrityStatus] | None = None,
    ) -> None:
        """Canlı saatı server vaxtına bağlayır (TIME-1).

        `app.py` bunu örtük qurulduqdan sonra çağırır. Çağırılmasa zolaqda
        saat GÖRÜNMÜR — yanlış (lokal) saat göstərməkdənsə heç nə göstərməmək
        doğrudur, çünki zolaqdakı rəqəmə istifadəçi sənəd kimi baxır.
        """
        self._clock_widget.set_source(clock, status=status)

    @property
    def live_clock(self) -> LiveClock:
        """Saat widget-i — pəncərə bağlananda taymeri dayandırmaq üçün."""
        return self._clock_widget

    # ------------------------------ vəziyyət --------------------------------- #

    def set_maximized(self, maximized: bool) -> None:
        """Pəncərə maksimallaşdı/bərpa oldu — düymənin nişanı dəyişir.

        Çağıran tərəf pəncərənin ÖZÜDÜR (`FramelessWindow.changeEvent`), çünki
        vəziyyəti OS də dəyişə bilir (Aero Snap, `Win`+`↑`, tapşırıq panelindən
        böyütmə) — düymə yalnız öz klikinə baxsaydı, o hallarda nişan yanlış
        qalardı.
        """
        self._maximize.set_maximized(maximized)

    def apply_theme(
        self,
        *,
        control_color: str,
        hover_color: str,
        close_hover_color: str,
        brand_mark_color: str = "",
        dark_mode: bool = True,
    ) -> None:
        """İkon rənglərini temaya uyğunlaşdırır.

        QSS fonu və MƏTN rəngini özü tətbiq edir, lakin ikon piksel şəklidir —
        onu yenidən çəkmək lazımdır (eyni səbəb `Sidebar.apply_theme`-də).

        Loqo da eyni qayda ilə boyanır: `brand_mark_color` verilməzsə düymə
        rəngi işlədilir — belə halda işarə mətn/düymələrlə eyni tonda olur və
        zolaq bütöv görünür.
        """
        for button in (self._minimize, self._maximize):
            button.set_colors(idle_color=control_color, hover_color=hover_color)
        self._close.set_colors(idle_color=control_color, hover_color=close_hover_color)
        self.set_logo_color(brand_mark_color or control_color)
        self.set_theme_icon(dark_mode=dark_mode, color=control_color)

    def set_theme_icon(self, *, dark_mode: bool, color: str) -> None:
        """Tema düyməsinin ikonu CARİ rejimi deyil, NƏTİCƏNİ göstərir.

        Tünd rejimdə «günəş» çəkilir, çünki basılanda İŞIQLI rejimə keçilir.
        Cari rejimi göstərsəydik, düymə vəziyyət göstəricisi kimi oxunardı və
        istifadəçi onu basmaqla nə alacağını təxmin etməli olardı — səhifə
        başlığındakı düymə də ilk gündən bu qaydadadır (`page_header.py`).
        """
        self._theme_button.setIcon(icons.icon("sun" if dark_mode else "moon", color))

    def theme_button(self) -> QPushButton:
        """Tema düyməsi — testlər və örtük üçün."""
        return self._theme_button

    def set_logo_color(self, color: str) -> None:
        """Başlıq loqosunu verilmiş rənglə yenidən çəkir.

        Fayl tapılmasa etiket BOŞ qalır və QSS-dəki `#TitleBarLogo` qaydası
        (rəngli kvadrat) görünür — yəni köhnə davranış fallback kimi işləyir.
        """
        pixmap = brand_assets.tinted_pixmap(
            brand_assets.TITLE_MARK,
            height=metrics.TITLEBAR_LOGO_SIZE,
            color=color,
        )
        if pixmap is not None:
            self._logo.setPixmap(pixmap)

    def buttons(self) -> tuple[WindowButton, WindowButton, WindowButton]:
        """Kiçilt / böyüt / bağla — testlər və native örtük üçün."""
        return (self._minimize, self._maximize, self._close)

    def maximize_button(self) -> WindowButton:
        """Böyüt/bərpa düyməsi.

        Native örtük onun DÜZBUCAQLISINI bilməlidir: Windows 11 Snap Layouts
        menyusunu yalnız `WM_NCHITTEST` həmin sahə üçün `HTMAXBUTTON`
        qaytardıqda açır (bax `shell/native_chrome.py`).
        """
        return self._maximize

    # ------------------------------ sürüklənən sahə --------------------------- #

    def is_drag_region(self, position: QPoint) -> bool:
        """Verilmiş nöqtə pəncərəni sürükləyirmi?

        Native örtük bu cavabı `WM_NCHITTEST`-də işlədir: `True` → `HTCAPTION`
        (OS sürükləməni, snap-i və sistem menyusunu öz üzərinə götürür),
        `False` → adi müştəri sahəsi (düymələr Qt kliklərini alır).

        Yalnız DÜYMƏLƏR çıxarılır — loqo və başlıq mətni sürüklənən qalır,
        çünki maketdə onlar zolağın bir hissəsidir, ayrı idarəetmə deyil.
        Yoxlama `childAt()` ilədir, sabit koordinatla deyil: düymələr gizlədilə
        bilir (`show_maximize=False`) və sabit hesablama o halda zolağın sağ
        kənarını yanlış "düymə" sayardı.
        """
        if not self.rect().contains(position):
            return False
        child = self.childAt(position)
        while child is not None and child is not self:
            if isinstance(child, QAbstractButton):
                return False
            child = child.parentWidget()
        return True

    # ------------------------------ sürükləmə -------------------------------- #

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is not Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        window = self.window()
        handle = window.windowHandle() if window is not None else None
        if handle is not None and handle.startSystemMove():
            event.accept()
            return

        # Ehtiyat yol — OS sürükləməni idarə etmirsə.
        self._drag_origin = event.globalPosition().toPoint() - window.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if self._drag_origin is None:
            super().mouseMoveEvent(event)
            return
        self.window().move(event.globalPosition().toPoint() - self._drag_origin)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Başlığa ikiqat klik — Windows-da tam ekran/bərpa konvensiyası."""
        if event.button() is Qt.MouseButton.LeftButton and self._maximize.isVisible():
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


__all__ = ["TitleBar"]
