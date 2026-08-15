"""Ekran bazası və vəziyyət keçidi — Faza 4.2.

Qrup G sənədinin qaydası:

    "Hər modulun boş, yüklənmə və xəta vəziyyəti eyni qaydaya tabedir."

Bu modul həmin qaydanı MEXANİZMƏ çevirir: hər ekran `ContentSwitcher` üzərində
qurulur və dörd vəziyyətdən birini göstərir — yüklənir / boş / xəta / məzmun.
Modul müəllifi vəziyyətləri ayrıca idarə etmir, sadəcə `show_loading()`,
`show_empty(...)`, `show_error(...)`, `show_content()` çağırır.

──────────────────────────────────────────────────────────────────────────────
400 ms QAYDASI
──────────────────────────────────────────────────────────────────────────────
Maketdə açıq yazılıb: "Skeleton 400 ms-dən sonra görünür — daha qısa
yükləmələrdə heç nə göstərilmir." Səbəb: bir anlıq görünüb yox olan boz
bloklar "sayrışma" (flash) effekti yaradır və yükləmənin özündən daha çox
nəzərə çarpır.

`show_loading()` bunu ÖZÜ tətbiq edir — çağıran tərəf taymer qurmur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import metrics
from src.presentation.widgets.responsive import LayoutMode
from src.presentation.widgets.states import EmptyState, ErrorState, LoadingState

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Skeleton bu müddətdən əvvəl göstərilmir (maketdən).
LOADING_DELAY_MS: Final = 400


class Screen(QWidget):
    """Bütün modul ekranlarının bazası.

    Standart daxili boşluğu (maketdə `padding: 22px 26px`) və vəziyyət
    keçidini təmin edir.
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        padded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        # Ekran KONTENT fonunu özü çəkir: örtükdəki `#ContentArea` onun
        # ALTINDA qalır və uşaq widget onu tamamilə örtür.
        self.setObjectName("ScreenSurface")
        enable_styled_background(self)

        outer = QVBoxLayout(self)
        if padded:
            # ALT boşluq daha genişdir: sağ-alt küncdə üzən dəstək düyməsi
            # (FAB) məzmunun üstünə düşür və altdakı sətirləri örtürdü —
            # məsələn "Server sağlamlığı" kartının son sətri kəsilirdi.
            outer.setContentsMargins(
                metrics.CONTENT_PADDING_H,
                metrics.CONTENT_PADDING_V,
                metrics.CONTENT_PADDING_H,
                metrics.CONTENT_BOTTOM_SAFE_AREA,
            )
        else:
            outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(metrics.CARD_SPACING)

        self._switcher = ContentSwitcher(theme)
        outer.addWidget(self._switcher)

        # Modulun öz məzmunu bura yığılır.
        self._content = QWidget()
        self._content.setObjectName("ScreenSurface")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(metrics.CARD_SPACING)
        self._switcher.set_content(self._content)

        #: Dar pəncərədə şaquli yığılacaq üfüqi sətirlər (bax `responsive_row`).
        self._responsive_rows: list[QBoxLayout] = []
        self._layout_mode = LayoutMode.WIDE

    # ---------------------------- tərtibat rejimi ---------------------------- #
    # NİYƏ BURADA, HƏR EKRANDA DEYİL
    # ─────────────────────────────────────────────────────────────────────────
    # `uxui.md` Addım 3 açıq deyir: "hər widget öz-özünə yoxlamasın, mərkəzi bir
    # «layout mode» siqnalına abunə olsun — təkrarlanan kod yaranmasın". Ekran
    # eni ÖLÇMÜR və hədd ədədini görmür; o, yalnız hansı sətirlərinin dar
    # pəncərədə bir sütuna yığılmalı olduğunu BİLDİRİR. Qərarı pəncərə verir
    # (`shell/window.py` → `AdminShell.apply_layout_mode`).

    def responsive_row(self, layout: QBoxLayout) -> QBoxLayout:
        """Üfüqi sətri "dar pəncərədə bir sütuna yığıl" kimi qeyd edir.

        NİYƏ `setDirection`, NİYƏ YENİDƏN QURMA: `QHBoxLayout` da,
        `QVBoxLayout` da `QBoxLayout`-dur və istiqamət bir çağırışla dəyişir.
        Kartları söküb yenidən yığmaq isə onların vəziyyətini (sürüşdürmə
        mövqeyi, seçilmiş sətir, fokus) itirərdi — halbuki istifadəçi sadəcə
        pəncərəni daraltmışdır.

        Returns:
            Eyni layout — çağırış yerində zəncirlə yazıla bilsin deyə.
        """
        self._responsive_rows.append(layout)
        layout.setDirection(self._direction_for(self._layout_mode))
        return layout

    def apply_layout_mode(self, mode: LayoutMode) -> None:
        """Örtük rejimi dəyişdi — qeyd olunmuş sətirlər istiqamətini dəyişir.

        Alt siniflər bunu ÜSTƏLƏYƏ bilər (məs. əlavə bir kartı gizlətmək
        üçün), lakin adi halda `responsive_row()` ilə qeydiyyat kifayətdir.
        """
        self._layout_mode = mode
        direction = self._direction_for(mode)
        for row in self._responsive_rows:
            row.setDirection(direction)

    @property
    def layout_mode(self) -> LayoutMode:
        return self._layout_mode

    @staticmethod
    def _direction_for(mode: LayoutMode) -> QBoxLayout.Direction:
        if mode is LayoutMode.COMPACT:
            return QBoxLayout.Direction.TopToBottom
        return QBoxLayout.Direction.LeftToRight

    # ------------------------------- məzmun --------------------------------- #

    @property
    def theme(self) -> ThemeManager:
        return self._theme

    def body(self) -> QVBoxLayout:
        """Modulun məzmun yerləşdirməsi."""
        return self._content_layout

    def add(self, widget: QWidget) -> QWidget:
        self._content_layout.addWidget(widget)
        return widget

    # ------------------------------ vəziyyətlər ------------------------------ #

    def show_loading(self, *, rows: int = 4, show_filters: bool = True) -> None:
        self._switcher.show_loading(rows=rows, show_filters=show_filters)

    # NİYƏ İMZA TAM YAZILIR, `**kwargs` DEYİL
    # ─────────────────────────────────────────────────────────────────────────
    # Əvvəl bunlar `**kwargs: object` + `# type: ignore[arg-type]` idi. Nəticədə
    # mypy çağırış yerini YOXLAMIRDI və üç ekran `message=` əvəzinə `body=`
    # göndərirdi — kataloqlar, Yardım Mərkəzi və Plugin ekranı BOŞ siyahı ilə
    # `TypeError` atırdı. Boş siyahı isə məhz ilk quraşdırmada normal haldır,
    # yəni qüsur ən pis anda üzə çıxırdı.
    #
    # İmza `ContentSwitcher`-inkini təkrarlayır; ikisi ayrılsa mypy dərhal
    # göstərir, halbuki `**kwargs` onları sükutla ayrı buraxırdı.

    def show_empty(
        self,
        *,
        icon_name: str = "list",
        title: str,
        message: str,
        primary_text: str = "",
        primary_icon: str | None = None,
        secondary_text: str = "",
        footnote: str = "",
    ) -> EmptyState:
        return self._switcher.show_empty(
            icon_name=icon_name,
            title=title,
            message=message,
            primary_text=primary_text,
            primary_icon=primary_icon,
            secondary_text=secondary_text,
            footnote=footnote,
        )

    def show_error(
        self,
        *,
        title: str,
        message: str,
        icon_name: str = "server_off",
        primary_text: str = "Yenidən Cəhd Et",
        secondary_text: str = "",
        details: list[tuple[str, str]] | None = None,
        footnote: str = "",
    ) -> ErrorState:
        return self._switcher.show_error(
            title=title,
            message=message,
            icon_name=icon_name,
            primary_text=primary_text,
            secondary_text=secondary_text,
            details=details,
            footnote=footnote,
        )

    def show_content(self) -> None:
        self._switcher.show_content()

    def switcher(self) -> ContentSwitcher:
        return self._switcher


class ContentSwitcher(QWidget):
    """Yüklənir / boş / xəta / məzmun vəziyyətləri arasında keçid.

    Vəziyyət widget-ləri hər dəfə YENİDƏN qurulur, çünki mətnləri (başlıq,
    izah, düymə adları) hər çağırışda fərqli olur — məsələn eyni ekran həm
    "Bu ay cərimə yoxdur", həm də "Serverə bağlanmaq mümkün olmadı" göstərə
    bilər.
    """

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        # Bütün ekran alt-ağacı EYNİ kontent fonunu çəkir. Ümumi `QWidget`
        # qaydası (`--color-bg-primary`) Qt tərəfindən HƏR widget-ə tətbiq
        # olunduğu üçün, işarələnməyən bir ara qab altındakı fonu örtərdi.
        self.setObjectName("ScreenSurface")
        enable_styled_background(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # `QStackedWidget` `QFrame`-dən törəyir, yəni ÜMUMİ `QWidget` qaydasını
        # (`--color-bg-primary`) özü çəkir və altındakı kontent fonunu örtərdi.
        # Ona görə o da ekran səthi kimi işarələnir.
        self._stack = QStackedWidget()
        self._stack.setObjectName("ScreenSurface")
        layout.addWidget(self._stack)

        self._content: QWidget | None = None
        self._transient: QWidget | None = None

        # Gecikməli skeleton — bax modulun başındakı "400 ms QAYDASI".
        self._loading_timer = QTimer(self)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.setInterval(LOADING_DELAY_MS)
        self._loading_timer.timeout.connect(self._present_loading)
        self._pending_loading: tuple[int, bool] | None = None

    # ------------------------------- məzmun --------------------------------- #

    def set_content(self, widget: QWidget) -> None:
        if self._content is not None:
            self._stack.removeWidget(self._content)
        self._content = widget
        self._stack.addWidget(widget)
        self._stack.setCurrentWidget(widget)

    def show_content(self) -> None:
        """Yükləmə taymerini dayandırır və modulun məzmununu göstərir."""
        self._loading_timer.stop()
        self._pending_loading = None
        self._clear_transient()
        if self._content is not None:
            self._stack.setCurrentWidget(self._content)

    # ------------------------------ vəziyyətlər ------------------------------ #

    def show_loading(self, *, rows: int = 4, show_filters: bool = True) -> None:
        """Yükləməni işarələyir; skeleton yalnız 400 ms sonra görünür."""
        self._pending_loading = (rows, show_filters)
        self._loading_timer.start()

    def _present_loading(self) -> None:
        if self._pending_loading is None:
            return
        rows, show_filters = self._pending_loading
        widget = LoadingState(rows=rows, show_filters=show_filters)
        self._present(widget)

    def show_empty(
        self,
        *,
        icon_name: str,
        title: str,
        message: str,
        primary_text: str = "",
        primary_icon: str | None = None,
        secondary_text: str = "",
        footnote: str = "",
    ) -> EmptyState:
        state = EmptyState(
            self._theme,
            icon_name=icon_name,
            title=title,
            message=message,
            primary_text=primary_text,
            primary_icon=primary_icon,
            secondary_text=secondary_text,
        )
        if footnote:
            state.set_footnote(footnote)
        self._present(state)
        return state

    def show_error(
        self,
        *,
        title: str,
        message: str,
        icon_name: str = "server_off",
        primary_text: str = "Yenidən Cəhd Et",
        secondary_text: str = "",
        details: list[tuple[str, str]] | None = None,
        footnote: str = "",
    ) -> ErrorState:
        state = ErrorState(
            self._theme,
            title=title,
            message=message,
            icon_name=icon_name,
            primary_text=primary_text,
            secondary_text=secondary_text,
            details=details,
        )
        if footnote:
            state.set_footnote(footnote)
        self._present(state)
        return state

    # ------------------------------- daxili ---------------------------------- #

    def _present(self, widget: QWidget) -> None:
        self._loading_timer.stop()
        self._clear_transient()
        self._transient = widget
        self._stack.addWidget(widget)
        self._stack.setCurrentWidget(widget)

    def _clear_transient(self) -> None:
        if self._transient is None:
            return
        self._stack.removeWidget(self._transient)
        self._transient.deleteLater()
        self._transient = None

    def current_state(self) -> str:
        """Cari vəziyyətin adı — testlər üçün."""
        widget = self._stack.currentWidget()
        if widget is self._content:
            return "content"
        if isinstance(widget, LoadingState):
            return "loading"
        if isinstance(widget, ErrorState):
            return "error"
        if isinstance(widget, EmptyState):
            return "empty"
        return "unknown"


def section_header(title: str, subtitle: str = "") -> QWidget:
    """Kontent daxilindəki bölmə başlığı — "Açıq Tapşırıqlarım" kimi."""
    from src.presentation.widgets.primitives import muted_label, title_label  # noqa: PLC0415

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    heading = title_label(title, size=16)
    heading.setAlignment(Qt.AlignmentFlag.AlignLeft)
    layout.addWidget(heading)

    if subtitle:
        layout.addWidget(muted_label(subtitle))

    return container


__all__ = ["LOADING_DELAY_MS", "ContentSwitcher", "Screen", "section_header"]
