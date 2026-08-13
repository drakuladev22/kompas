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

from src.presentation.theme.manager import enable_styled_background
from src.presentation.theme.tokens import ThemeMode
from src.presentation.widgets import metrics
from src.presentation.widgets.page_header import PageHeader
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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ------------------------------ sol panel --------------------------- #
        self._sidebar = Sidebar(
            idle_icon_color=theme.color("--color-nav-item-icon"),
            active_icon_color=theme.color("--color-brand-amber"),
        )
        self._sidebar.navigated.connect(self.show_screen)
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
        if widget is None:
            widget = factory()
            self._screens[key] = widget
            self._stack.addWidget(widget)

        self._stack.setCurrentWidget(widget)
        title, subtitle = self._titles.get(key, (key, ""))
        self._header.set_page(title, subtitle)
        self._sidebar.set_active(key)
        self.screen_changed.emit(key)
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
