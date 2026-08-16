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

──────────────────────────────────────────────────────────────────────────────
BÖLMƏ XƏTASI: NİYƏ DÖRD VƏZİYYƏT KİFAYƏT ETMİRDİ
──────────────────────────────────────────────────────────────────────────────
`show_error()` BÜTÜN ekranı əvəz edir və bu, ekranın tək bir sorğusu olduqda
doğrudur. İdarə Paneli isə YEDDİ müstəqil bölmədən ibarətdir; onlardan biri
sınanda qalan altısını gizlətmək məlumat İTİRMƏKDİR, sükutla boş buraxmaq isə
YALAN DANIŞMAQDIR — istifadəçi «0 cərimə» rəqəmini HƏQİQƏT kimi oxuyur.

Ona görə beşinci, MƏZMUNLA BİRLİKDƏ yaşayan vəziyyət var:
`set_section_error("Xülasə sayğacları")`. O, məzmunu gizlətmir, üstünə görünən
bir sətir əlavə edir. Qüsurun tarixçəsi: `screen_data.py`-dakı sorğu
`fine_types.name` sütununu oxuyurdu (`name_az` olmalı idi), `populate()`-dakı
`except Exception` `UndefinedColumn`-u tuturdu və «Cərimələr» ekranı AYLARLA
boş göründü — jurnalda səbəb var idi, ekranda isə heç bir fərq YOX idi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import metrics
from src.presentation.widgets.responsive import LayoutMode
from src.presentation.widgets.states import EmptyState, ErrorState, LoadingState

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Skeleton bu müddətdən əvvəl göstərilmir (maketdən).
LOADING_DELAY_MS: Final = 400

#: Bölmə xətası bannerinin nişan mətni — «boş»dan FƏRQLİ vizual (danger tonu).
SECTION_ERROR_CHIP: Final = "Yüklənə bilmədi"

#: Bannerin ikinci cümləsi: istifadəçinin ATA BİLƏCƏYİ addım.
#:
#: NİYƏ «Xəta baş verdi» YAZILMIR — o cümlə istifadəçiyə nə baş verdiyini də,
#: nə edəcəyini də demir; onu yalnız köməksiz qoyur (Qrup G qaydası: "nə baş
#: verdiyini bir cümlə ilə izah et, sonra bir aydın hərəkət təklif et").
#:
#: NİYƏ TEXNİKİ DETAL YOXDUR — sorğu mətni, sütun adı və izləmə `error.log`-da
#: qalır. Onları ekrana çıxarmaq nə istifadəçinin problemini həll edir, nə də
#: onun səlahiyyətindədir; üstəlik sxem detalı ekranda görünən məlumat olardı.
SECTION_ERROR_HINT: Final = "Səhifəni yeniləyin, davam edərsə administratora bildirin."


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

        #: Yüklənə bilməyən bölmələrin ADLARI (bax `set_section_error`).
        #: Siyahı SIRA saxlayır: istifadəçi eyni ekranı iki dəfə açanda
        #: bölmələrin adı yer dəyişsəydi, "nə dəyişdi?" sualı yaranardı.
        self._section_errors: list[str] = []
        #: Banner LAZIM OLANA QƏDƏR QURULMUR — sağlam ekranda heç bir əlavə
        #: widget yaranmır (eyni naxış: `HealthScreen.set_conflict_action`).
        self._section_error_banner: QWidget | None = None
        self._section_error_text: QLabel | None = None

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

    # --------------------------- bölmə xətası -------------------------------- #
    # NİYƏ AYRICA MEXANİZM (bax modul başlığı)
    # ─────────────────────────────────────────────────────────────────────────
    # `show_error()` ekranı ƏVƏZ EDİR — qismən uğur halında (5 bölmədən 1-i
    # sındı) bu, doğru olan 4 bölməni də gizlədərdi. Banner isə məzmunun
    # ÜSTÜNDƏ yaşayır: düzgün rəqəmlər qalır, etibarsız bölmə isə AÇIQ
    # şəkildə işarələnir.
    #
    # İMZA OPSİONALDIR VƏ HEÇ BİR MÖVCUD SETTER DƏYİŞMİR: kontroller bu metodu
    # `getattr` ilə axtarır (bax `screen_data.report_section_error`), ona görə
    # metodu daşımayan sahə obyekti (test saxtası) də sınmır.

    def set_section_error(self, section_label: str) -> None:
        """«{bölmə} yüklənə bilmədi» xəbərdarlığını ekranın başında göstərir.

        Args:
            section_label: İSTİFADƏÇİ dilində bölmə adı ("Xülasə sayğacları").
                Texniki ad (`_dashboard_summary`) YAZILMIR — istifadəçi kodun
                daxili adlarını görməməlidir.

        Təkrar çağırış eyni adı İKİ dəfə əlavə etmir: bir bölmə bir
        yenilənmədə bir dəfə sınır, lakin panel saatlarla açıq qala bilər və
        siyahının şişməsi bannerini oxunmaz edərdi.
        """
        if not section_label:
            return
        if section_label not in self._section_errors:
            self._section_errors.append(section_label)
        self._refresh_section_error_banner()

    def clear_section_errors(self) -> None:
        """Yenidən yükləmədən ƏVVƏL çağırılır — köhnə xəbərdarlıq qalmasın.

        Silinmiş xəbərdarlıq YALAN olardı: bölmə artıq düzgün yüklənibsə,
        istifadəçi hələ də etibarsız rəqəm gördüyünü düşünərdi.
        """
        self._section_errors.clear()
        if self._section_error_banner is not None:
            self._section_error_banner.setVisible(False)

    def section_errors(self) -> tuple[str, ...]:
        """Hazırda xəta ilə işarələnmiş bölmələr — testlər və diaqnostika üçün."""
        return tuple(self._section_errors)

    def _refresh_section_error_banner(self) -> None:
        if self._section_error_banner is None:
            self._section_error_banner, self._section_error_text = _section_error_banner()
            # Bannerin yeri ƏN ÜSTDƏDİR: xəbərdarlıq etibarsız rəqəmlərdən
            # SONRA gəlsəydi, istifadəçi onu rəqəmləri oxuyandan sonra görərdi.
            self._content_layout.insertWidget(0, self._section_error_banner)

        if self._section_error_text is not None:
            self._section_error_text.setText(_section_error_sentence(self._section_errors))
        self._section_error_banner.setVisible(True)

        # BANNER MƏZMUN QATINDA YAŞAYIR: ekran «boş vəziyyət» və ya «yüklənir»
        # görüntüsündə qalıbsa xəbərdarlıq GÖRÜNMƏZ olardı — halbuki
        # düzəltdiyimiz qüsur məhz budur (boş ekran xətanı gizlədir). «Xəta
        # vəziyyəti» (`show_error`) İSƏ toxunulmur: o, artıq daha güclü
        # bildirişdir və onu banner ilə əvəzləmək məlumat itkisi olardı.
        if self._switcher.current_state() not in {"content", "error"}:
            self.show_content()


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

    heading = title_label(title, size=15)
    heading.setAlignment(Qt.AlignmentFlag.AlignLeft)
    layout.addWidget(heading)

    if subtitle:
        layout.addWidget(muted_label(subtitle))

    return container


def _section_error_sentence(sections: list[str]) -> str:
    """Banner mətni — bir bölmə üçün TƏK, çoxu üçün SİYAHI forması.

    «Bu bölmələr yüklənə bilmədi: A, B» cümləsi bir bölmə üçün süni səslənir,
    ona görə tək hal ayrıca yazılır. Bölmə ADLARI göstərilir, çünki istifadəçi
    məhz hansı rəqəmə inanmayacağını bilməlidir — ümumi «məlumat yüklənmədi»
    xəbərdarlığı bütün ekranı şübhəli edərdi, halbuki qalan bölmələr düzgündür.
    """
    if not sections:
        return ""
    if len(sections) == 1:
        return f"«{sections[0]}» bölməsi yüklənə bilmədi. {SECTION_ERROR_HINT}"
    listed = ", ".join(f"«{name}»" for name in sections)
    return f"Bu bölmələr yüklənə bilmədi: {listed}. {SECTION_ERROR_HINT}"


def _section_error_banner() -> tuple[QWidget, QLabel]:
    """Xəbərdarlıq zolağı — MÖVCUD primitivlərdən yığılır, yeni widget YOX.

    `Chip(tone="danger")` + `body_label` cütü onsuz da bütün ekranlarda
    işlədilir və rəng cütləri `tokens.py`-da WCAG AA üçün kalibrlənib; xəta
    üçün YENİ rəng götürmək kontrast qapısını (`scripts/check_contrast.py`)
    yeni cütlə yükləyərdi və heç bir üstünlük verməzdi.

    Returns:
        (banner, mətn etiketi) — mətn hər yeni sınmış bölmədə yenilənir.
    """
    from src.presentation.widgets.primitives import (  # noqa: PLC0415
        Card,
        Chip,
        body_label,
        stretch,
    )

    card = Card(padding=16, spacing=12)
    line = QWidget()
    layout = QHBoxLayout(line)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    chip = Chip(SECTION_ERROR_CHIP, "danger")
    layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)

    text = body_label("", size=13)
    layout.addWidget(text, 1)
    layout.addWidget(stretch())

    card.add(line)
    return card, text


__all__ = [
    "LOADING_DELAY_MS",
    "SECTION_ERROR_CHIP",
    "SECTION_ERROR_HINT",
    "ContentSwitcher",
    "Screen",
    "section_header",
]
