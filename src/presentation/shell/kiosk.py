"""Kiosk pəncərəsi — Faza 4.2.

Spesifikasiya (bölmə "PLATFORMA QAYDALARI"):

    "İSTİSNA: Kiosk Mode ekranları (PIN klaviaturası, İşçi Ana Ekranı) TAM
     EKRAN, çərçivəsiz, toxunma-ilk dizayndadır (paylaşılan mağaza kiosk
     PC-sində istifadə olunur)."

──────────────────────────────────────────────────────────────────────────────
NİYƏ BAĞLAMA DÜYMƏSİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
Kiosk PC-si mağazada işçilərin ümumi istifadəsindədir. Orada "×" düyməsi
olsaydı, hər kəs proqramı bağlaya bilərdi və növbəti işçi giriş qeydiyyatını
apara bilməzdi. Ona görə pəncərə tam ekrandır və yalnız gizli qısayolla
(`Ctrl+Shift+Q`) bağlanır — həmin qısayol mağaza menecerinə verilir.

`Alt+F4` Qt tərəfindən bloklanmır (OS səviyyəsindədir), lakin `closeEvent`
təsdiq tələb edir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from src.presentation.i18n import tr
from src.presentation.widgets.layout_utils import detach_layout
from src.presentation.widgets.metrics import KIOSK_CARDS_ROW_MIN_WIDTH
from src.presentation.widgets.responsive import LayoutMode
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from PySide6.QtGui import QCloseEvent, QResizeEvent

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Kioskdan çıxış qısayolu — mağaza menecerinə verilir.
EXIT_SHORTCUT = "Ctrl+Shift+Q"


class KioskWindow(QWidget):
    """Tam ekran, çərçivəsiz kiosk pəncərəsi.

    Signals:
        exit_requested: Gizli qısayol basıldı — çağıran tərəf təsdiq istəyir.
    """

    exit_requested = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KioskWindow")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle(tr("common.app_name"))

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._allow_close = False
        #: Cari məzmun — `resizeEvent`-in tərtibat rejimini ötürdüyü hədəf
        #: (bax `_apply_layout_mode`).
        self._content: QWidget | None = None

        shortcut = QShortcut(QKeySequence(EXIT_SHORTCUT), self)
        shortcut.activated.connect(self._on_exit_shortcut)

    def set_content(self, widget: QWidget) -> None:
        """Kiosk məzmununu dəyişir (PIN klaviaturası ↔ İşçi Ana Ekranı)."""
        detach_layout(self._layout)
        self._layout.addWidget(widget)
        self._content = widget
        self._apply_layout_mode()

    def start(self) -> None:
        """Tam ekran rejimində açır."""
        self.showFullScreen()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt adlandırması
        super().resizeEvent(event)
        self._apply_layout_mode()

    def _apply_layout_mode(self) -> None:
        """Kiosk-un ÖZ tərtibat həddi — `widgets/responsive.py::mode_for_width` DEYİL.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRI HƏDD, `shell/window.py::FramelessWindow` İLƏ EYNİ FUNKSİYA
        YOX
        ──────────────────────────────────────────────────────────────────────
        `mode_for_width()`-in `LAYOUT_BREAKPOINT_WIDE`-i (1280px) admin
        panelin sol-panel+kontent bölgüsünün həddidir. Kiosk-un sol paneli
        YOXDUR (modul başlığı) və 1280/1366 — tipik kiosk sensor panel
        enləri — HƏR İKİSİ bu həddən (`>= 1280`) YUXARIDADIR: admin
        funksiyasını təkrar işlətsəydik, kiosk HƏMİŞƏ "WIDE" sayılıb altı-
        kartlıq sıra yenə sıxışardı (bax `metrics.KIOSK_CARDS_ROW_MIN_WIDTH`
        şərhi). Ona görə BURADA, kiosk-un ÖZ ölçən nöqtəsində, ayrı hədd
        işlədilir — "TƏK yer ölçür" prinsipi (`widgets/responsive.py`
        başlığı) pozulmur, çünki ölçən YENƏ TƏK yerdir (bu pəncərə), sadəcə
        admin panelinki İLƏ EYNİ ƏDƏD deyil.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `self.width()` DEYİL, `self.screen().availableGeometry()`
        (`perf-screens`-in real-platforma tapıntısı, TOYUQ-YUMURTA)
        ──────────────────────────────────────────────────────────────────────
        `self.width()` PƏNCƏRƏNİN ARTIQ Qt tərəfindən HƏLL EDİLMİŞ (clamped)
        enidir — WIDE rejimdə məzmunun `QGridLayout`-u 6 sütunla minimum
        `KIOSK_CARDS_ROW_MIN_WIDTH`-i tələb edir, Qt isə pəncərəni bu
        minimumdan AŞAĞI SIXA BİLMİR (`resize(1366, …)` çağırılsa belə,
        `self.width()` YENƏ ~1656 qalır — real ölçüldü, 1366×768 VƏ
        1280×768 EYNİ 1656×833 nəticəsini verdi). Nəticədə `resizeEvent`
        HEÇ VAXT 1656-dan aşağı en GÖRMÜR, rejim HEÇ VAXT COMPACT-a keçmir,
        keçmədiyi üçün minimum HEÇ VAXT kiçilmir — qapalı dövrə.

        Fiziki EKRANIN eni isə bu dövrədən TAM MÜSTƏQİLDİR: monitor 1366px-
        dirsə, pəncərənin ÖZ minimum tələbi nə olursa olsun, bu FAKT
        DƏYİŞMİR. `QScreen.availableGeometry()` məhz bunu verir — rejim
        artıq "pəncərə özünü necə həll etdi" sualına deyil, "bu kiosk hansı
        fiziki displeydədir" sualına əsaslanır və dövrə BİR DƏFƏLİK qırılır.

        `hasattr` DUCK-TYPE: PIN klaviaturası ekranının `apply_layout_mode`-u
        YOXDUR (yalnız `EmployeeHomeScreen`-də lazımdır) və çağırış sükutla
        keçilir.
        """
        if self._content is None:
            return
        apply_mode = getattr(self._content, "apply_layout_mode", None)
        if apply_mode is None:
            return
        screen = self.screen() or QApplication.primaryScreen()
        # Ekran HEÇ VAXT tapılmasa (nəzəri, real mühitdə baş vermir) —
        # `self.width()` SON ÇARƏ kimi qalır, HEÇ NƏ etməmək susmadan pisdir.
        width = screen.availableGeometry().width() if screen is not None else self.width()
        mode = LayoutMode.WIDE if width >= KIOSK_CARDS_ROW_MIN_WIDTH else LayoutMode.COMPACT
        apply_mode(mode)

    def _on_exit_shortcut(self) -> None:
        _security_log.info("KIOSK_EXIT_SHORTCUT")
        self.exit_requested.emit()

    def allow_close(self) -> None:
        """Təsdiqdən sonra bağlanmağa icazə verir."""
        self._allow_close = True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if self._allow_close:
            super().closeEvent(event)
            return
        # Təsadüfi Alt+F4 kiosk terminalını söndürməməlidir.
        _security_log.warning("KIOSK_CLOSE_BLOCKED")
        event.ignore()


__all__ = ["EXIT_SHORTCUT", "KioskWindow"]
