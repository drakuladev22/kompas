"""Admin örtüyü: sol panel + başlıq + kontent — Faza 4.2.

Maketdəki bütün admin ekranları (Qrup B–G) eyni üç hissədən ibarətdir:

    ┌──────────────────────────────────────────────┐
    │ TitleBar (pəncərə)                           │
    ├────────────┬─────────────────────────────────┤
    │            │ PageHeader (62px)               │
    │ Sidebar    ├─────────────────────────────────┤
    │ (226px)    │ kontent (QStackedWidget)        │
    └────────────┴─────────────────────────────────┘

──────────────────────────────────────────────────────────────────────────────
EKRANLAR NİYƏ FABRİKA İLƏ VERİLİR
──────────────────────────────────────────────────────────────────────────────
27 ekranın hamısını işə düşmə anında qurmaq həm yavaş olardı, həm də mənasız:
istifadəçi bir sessiyada adətən 3–4-ünə baxır. Ona görə örtük `key → callable`
xəritəsi alır və ekranı YALNIZ ilk dəfə açılanda yaradır.

Bu, həm də icazə ilə uyğun gəlir: görünməyən maddənin ekranı heç vaxt
qurulmur, yəni onun sorğuları da işə düşmür.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.theme.manager import enable_styled_background
from src.presentation.theme.tokens import ThemeMode
from src.presentation.widgets import metrics
from src.presentation.widgets.page_header import PageHeader
from src.presentation.widgets.responsive import LayoutMode
from src.presentation.widgets.sidebar import Sidebar
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.presentation.navigation import NavigationRegistry
    from src.presentation.theme.manager import ThemeManager

_log = get_logger(__name__)

#: Ekran qurucusu — örtük onu ilk açılışda çağırır.
ScreenFactory = "Callable[[], QWidget]"


class AdminShell(QWidget):
    """Rol-əsaslı admin örtüyü.

    Signals:
        theme_toggle_requested: İstifadəçi tema düyməsini basdı.
        screen_changed: Aktiv ekran dəyişdi (`key`).
    """

    theme_toggle_requested = Signal()
    #: Artıq qurulmuş ekrana qayıdış — məlumatın təzələnməsi üçün
    #: (bax `show_screen` içindəki izah).
    screen_revisited = Signal(str)
    screen_changed = Signal(str)

    def __init__(
        self,
        *,
        theme: ThemeManager,
        registry: NavigationRegistry,
        employee: Employee,
        now: datetime,
        enabled_modules: frozenset[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._registry = registry
        self._employee = employee
        self._now = now
        self._enabled_modules = enabled_modules
        self._factories: dict[str, Callable[[], QWidget]] = {}
        self._screens: dict[str, QWidget] = {}
        self._titles: dict[str, tuple[str, str]] = {}
        #: Cari tərtibat rejimi — pəncərədən gəlir (bax `apply_layout_mode`).
        self._layout_mode = LayoutMode.WIDE
        #: İstifadəçinin ƏL İLƏ verdiyi qərar; `None` = seçim edilməyib.
        #: Bax `_on_collapse_toggled`.
        self._manual_collapse: bool | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ------------------------------ sol panel --------------------------- #
        self._sidebar = Sidebar(
            idle_icon_color=theme.color("--color-nav-item-icon"),
            active_icon_color=theme.color("--color-brand-amber"),
        )
        self._sidebar.navigated.connect(self.show_screen)
        self._sidebar.collapse_toggled.connect(self._on_collapse_toggled)
        layout.addWidget(self._sidebar)

        # ------------------------------ sağ tərəf --------------------------- #
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._header = PageHeader(
            icon_color=theme.color("--color-nav-item-text"),
            avatar_bg=theme.color("--color-neutral-bg"),
            avatar_fg=theme.color("--color-text-primary"),
            badge_bg=theme.color("--color-brand-amber"),
            badge_fg=theme.color("--color-brand-navy"),
            surface_color=theme.color("--color-header-bg"),
            dark_mode=theme.mode is ThemeMode.DARK,
        )
        self._header.theme_toggled.connect(self.theme_toggle_requested)
        self._header.profile_clicked.connect(lambda: self.show_screen("profile"))
        self._header.set_user(employee.full_name)
        right_layout.addWidget(self._header)

        # Kontent sürüşdürülə bilir — 1280×800-dən kiçik ekranlarda uzun
        # formalar (ERP sihirbazı, icazə matrisi) kəsilməməlidir.
        self._scroll = QScrollArea()
        self._scroll.setObjectName("ContentScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._stack = QStackedWidget()
        self._stack.setObjectName("ContentArea")
        enable_styled_background(self._stack)
        self._scroll.setWidget(self._stack)
        right_layout.addWidget(self._scroll, 1)

        layout.addWidget(right, 1)

        self.refresh_navigation()

    # ------------------------------ ekranlar --------------------------------- #

    def register_screen(
        self,
        key: str,
        factory: Callable[[], QWidget],
        *,
        title: str = "",
        subtitle: str = "",
    ) -> None:
        """Bir ekranı qeydiyyata alır (hələ QURMADAN).

        Args:
            title/subtitle: Başlıqda göstəriləcək mətn. Boş buraxılsa, menyu
                maddəsinin adı işlədilir.
        """
        self._factories[key] = factory
        entry = self._registry.get(key)
        self._titles[key] = (title or (entry.title_az if entry else key), subtitle)

    def show_screen(self, key: str) -> bool:
        """Ekranı göstərir; icazə yoxdursa heç nə etmir.

        Returns:
            Ekran göstərildisə `True`.

        Bu, sadəcə menyu klikinə cavab deyil — proqramatik keçidlər (məs.
        bildirişdən "sorğuya bax") də buradan gedir. Ona görə icazə BURADA da
        yoxlanılır: gizli maddəyə birbaşa keçid (deep link) bağlanmalıdır.
        """
        if not self._registry.is_visible(
            key,
            self._employee,
            now=self._now,
            enabled_modules=self._enabled_modules,
        ):
            _log.warning(
                "NAVIGATION_DENIED",
                extra={"screen": key, "employee_id": str(self._employee.id)},
            )
            return False

        factory = self._factories.get(key)
        if factory is None:
            _log.error("SCREEN_NOT_REGISTERED", extra={"screen": key})
            return False

        widget = self._screens.get(key)
        revisited = widget is not None
        if widget is None:
            widget = factory()
            self._screens[key] = widget
            self._stack.addWidget(widget)
            # Ekran GEC qurulur (bax modul başlığı), yəni rejim siqnalını
            # qaçırıb. Onsuz daraldılmış pəncərədə ilk dəfə açılan ekran
            # geniş tərtibatla görünərdi və yalnız növbəti ölçü dəyişikliyində
            # düzələrdi.
            self._apply_mode_to(widget)

        self._stack.setCurrentWidget(widget)
        title, subtitle = self._titles.get(key, (key, ""))
        self._header.set_page(title, subtitle)
        self._sidebar.set_active(key)
        self.screen_changed.emit(key)
        # ARTIQ QURULMUŞ ekrana QAYIDIŞ ayrıca siqnaldır.
        #
        # Ekranlar bir dəfə qurulur və məlumatı QURULMA anında doldurulur
        # (`app.py::make`). Yəni istifadəçi mağaza əlavə edib panelə qayıdanda
        # köhnə rəqəmi görürdü — «yaratdıqca artmalıdır» gözləntisi məhz
        # burada pozulurdu.
        #
        # `screen_changed` bu iş üçün YARAMIR: o, İLK qurulmada da yayılır və
        # abunəçi məlumatı iki dəfə oxuyardı. Ayrı siqnal fərqi birmənalı edir.
        if revisited:
            self.screen_revisited.emit(key)
        return True

    def screen_for(self, key: str) -> QWidget | None:
        """Artıq qurulmuş ekranı qaytarır — `None` hələ AÇILMAYIBSA.

        Drill-down üçün lazımdır (#24, kompasos11.md Faza 9A): çağıran tərəf
        `show_screen(key)` ilə keçiddən SONRA həmin ekranın instansına
        müraciət edib ONA XÜSUSİ parametrlə (məs. kliklənən mağaza) yenidən
        canlı məlumat yazdıra bilir — YENİ naviqasiya qatı YARADILMIR, sadəcə
        artıq mövcud olan `_screens` reyestri XARİCƏ açılır.
        """
        return self._screens.get(key)

    def set_screen_subtitle(self, key: str, subtitle: str) -> None:
        """Bir ekranın kontekst mətnini AÇARLA yeniləyir.

        `set_page_subtitle()`-dan fərqi: o, YALNIZ aktiv ekrana yazır və
        girişdən sonra bütün ekranların say/tarix mətnini bir dəfəyə
        doldurmaq üçün yaramır — istifadəçi hər ekranı açana qədər gözləmək
        lazım gələrdi.
        """
        entry = self._registry.get(key)
        title, _ = self._titles.get(key, (entry.title_az if entry else key, ""))
        self._titles[key] = (title, subtitle)
        if self._sidebar.active_key == key:
            self._header.set_page(title, subtitle)

    def set_page_subtitle(self, subtitle: str) -> None:
        """Aktiv ekranın kontekst mətnini yeniləyir ("Avqust 2026 · Bellona")."""
        key = self._sidebar.active_key
        if key is None:
            return
        title, _ = self._titles.get(key, (key, ""))
        self._titles[key] = (title, subtitle)
        self._header.set_page(title, subtitle)

    def current_screen_key(self) -> str | None:
        return self._sidebar.active_key

    # ------------------------------ naviqasiya ------------------------------- #

    def refresh_navigation(self) -> None:
        """Menyunu istifadəçinin cari icazələrinə görə yenidən qurur."""
        visible = self._registry.visible_for(
            self._employee,
            now=self._now,
            enabled_modules=self._enabled_modules,
        )
        self._sidebar.set_entries(visible)
        _log.info(
            "NAVIGATION_BUILT",
            extra={"visible": [entry.key for entry in visible]},
        )

    def set_employee(self, employee: Employee, *, now: datetime) -> None:
        """İstifadəçi dəyişdikdə (yenidən giriş) örtüyü sıfırlayır."""
        self._employee = employee
        self._now = now
        self._header.set_user(employee.full_name)

        # Köhnə istifadəçinin ekranları SİLİNİR — onlarda əvvəlki şəxsin
        # məlumatı qalırdı və yeni istifadəçi onu görərdi.
        for widget in self._screens.values():
            self._stack.removeWidget(widget)
            widget.deleteLater()
        self._screens.clear()

        self.refresh_navigation()

    def set_enabled_modules(self, modules: frozenset[str] | None) -> None:
        """Feature Toggle dəyişdikdə (ROOT İdarə Mərkəzi) menyunu yeniləyir."""
        self._enabled_modules = modules
        self.refresh_navigation()

    # --------------------------- tərtibat rejimi ------------------------------ #

    def apply_layout_mode(self, mode: LayoutMode | str) -> None:
        """Pəncərə eninin rejimini örtüyə və bütün ekranlara ötürür.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BURADA TOPLANIR
        ──────────────────────────────────────────────────────────────────────
        Pəncərə yalnız BİR siqnal yayır (`shell/window.py`), örtük isə onu
        iki ünvana paylayır: sol panel (yalnız-ikon rejimi) və artıq qurulmuş
        ekranlar. Alternativ — hər ekranın pəncərəyə birbaşa abunə olması —
        27 ayrı abunəlik və 27 ləğvetmə demək olardı; ekran bağlananda
        ləğvetmə unudulsaydı, silinmiş widget-ə siqnal gedərdi.

        `str` də qəbul edilir, çünki Qt siqnalı `LayoutMode` dəyərini mətn
        kimi daşıyır (`Signal(str)`) — çevirmə bir yerdə, burada olur.
        """
        mode = LayoutMode(mode)
        if mode is self._layout_mode:
            return
        self._layout_mode = mode
        # Sol panelin daralması ARTIQ mövcud idi (`Sidebar.set_collapsed` →
        # `NavButton.set_compact`) — burada yalnız ÇAĞIRILIR, yenidən
        # yazılmır (`uxui.md` Addım 3: "mövcud daralma funksiyasını ÇAĞIRARAQ").
        # ĞƏSDLİ SEÇİM AVTOMATİKANI ÜSTƏLƏYİR
        # ---------------------------------------------------------------
        # İstifadəçi paneli ƏL İLƏ açıbsa, pəncərə kiçiləndə onu geri
        # bağlamaq onun qərarını sükutla ləğv etmək olardı — və əksinə.
        # `None` = «hələ seçim edilməyib», yəni avtomatika sərbəstdir.
        self._sidebar.set_collapsed(
            mode is LayoutMode.COMPACT if self._manual_collapse is None else self._manual_collapse
        )
        for widget in self._screens.values():
            self._apply_mode_to(widget)
        _log.debug(
            "SHELL_LAYOUT_MODE",
            extra={"mode": mode.value, "manual_collapse": self._manual_collapse},
        )

    def _on_collapse_toggled(self, collapsed: bool) -> None:
        """İstifadəçi paneli əl ilə açdı/bağladı.

        Seçim YADDA SAXLANILIR (`_manual_collapse`) və bundan sonra pəncərə
        eni onu üstələmir. Saxlanmasaydı, növbəti ölçü dəyişikliyi (məs.
        pəncərəni böyütmək) paneli istifadəçinin istəmədiyi vəziyyətə
        qaytarardı.

        EKRANLARA DA XƏBƏR VERİLİR: məzmun sahəsinin eni dəyişir və
        `Screen.apply_layout_mode()` sütun sayını məhz ona görə hesablayır —
        çağırılmasaydı, panel bağlananda cədvəllər köhnə enlə qalardı.
        """
        self._manual_collapse = collapsed
        for widget in self._screens.values():
            self._apply_mode_to(widget)
        _log.debug("SHELL_SIDEBAR_MANUAL", extra={"collapsed": collapsed})

    @property
    def layout_mode(self) -> LayoutMode:
        return self._layout_mode

    def _apply_mode_to(self, widget: QWidget) -> None:
        """Rejimi bir ekrana ötürür.

        Yalnız `Screen` bazasından törəyən widget-lər rejimi başa düşür;
        qalanları (məs. örtüyə taxılan xüsusi panellər) toxunulmadan qalır —
        `hasattr` yoxlaması əvəzinə tip yoxlaması seçilib ki, mypy imzanı
        həqiqətən yoxlaya bilsin.
        """
        if isinstance(widget, Screen):
            widget.apply_layout_mode(self._layout_mode)

    # -------------------------------- tema ----------------------------------- #

    def apply_theme(self) -> None:
        """Tema dəyişdikdən sonra QSS-siz elementləri yeniləyir."""
        theme = self._theme
        self._sidebar.apply_theme(
            idle_icon_color=theme.color("--color-nav-item-icon"),
            active_icon_color=theme.color("--color-brand-amber"),
        )
        self._header.apply_theme(
            icon_color=theme.color("--color-nav-item-text"),
            avatar_bg=theme.color("--color-neutral-bg"),
            avatar_fg=theme.color("--color-text-primary"),
            badge_bg=theme.color("--color-brand-amber"),
            badge_fg=theme.color("--color-brand-navy"),
            surface_color=theme.color("--color-header-bg"),
            dark_mode=theme.mode is ThemeMode.DARK,
        )

    # ------------------------------ komponentlər ------------------------------ #

    def header(self) -> PageHeader:
        return self._header

    def sidebar(self) -> Sidebar:
        return self._sidebar

    def content_margins(self) -> tuple[int, int, int, int]:
        """Ekranların işlətməli olduğu daxili boşluq (maketdən: 22/26)."""
        return (
            metrics.CONTENT_PADDING_H,
            metrics.CONTENT_PADDING_V,
            metrics.CONTENT_PADDING_H,
            metrics.CONTENT_PADDING_V,
        )


__all__ = ["AdminShell", "ScreenFactory"]
