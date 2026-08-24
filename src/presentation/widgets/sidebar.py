"""Sol naviqasiya paneli — Faza 4.2.

Spesifikasiya (bölmə 3, "GÖRMƏK = SƏLAHİYYƏTİN OLMASI"):

    "Sol naviqasiya SABİT paneldir (hamburger menyu yox), daralda bilər və
     YALNIZ istifadəçinin icazəsi olan bölmələri göstərir (icazəsiz maddə boz
     görünmür, tamamilə yoxdur)."

──────────────────────────────────────────────────────────────────────────────
FİLTRLƏMƏ BURADA DEYİL
──────────────────────────────────────────────────────────────────────────────
Bu widget maddələri ÖZÜ süzgəcdən keçirmir — hazır siyahı alır. Səbəb:
`NavigationRegistry.visible_for()` PySide6-dan asılı olmayan saf məntiqdir və
GUI olmadan test olunur (bax `navigation.py`). Filtri bura köçürmək həmin
testləri Qt-dən asılı edərdi və eyni qayda iki yerdə yaşayardı.

Panel sadəcə "sənə verilən nə varsa, onu göstər" prinsipi ilə işləyir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import KeyFocusIconButton, NavButton
from src.presentation.widgets.primitives import section_label, stretch
from src.presentation.widgets.safe_text import plain_tooltip

if TYPE_CHECKING:
    from PySide6.QtGui import QResizeEvent

    from src.presentation.navigation import MenuEntry

#: `MenuEntry.icon` boş olduqda işlədilən ikon — menyu maddəsi ikonsuz qalsa
#: sətir sıçrayardı (mətn sola sürüşərdi), ona görə neytral bir forma verilir.
FALLBACK_ICON: Final = "list"


class _OverlayScrollArea(QScrollArea):
    """Şaquli zolaq MƏZMUNUN ÜSTÜNDƏ üzür — LAYOUT-dan yer ALMIR.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ ÜST-QAT (OVERLAY), NİYƏ ADİ `QScrollArea` KİFAYƏT ETMİR
    ──────────────────────────────────────────────────────────────────────
    Adi `QScrollArea` şaquli zolaq görünəndə viewport-un ENİNİ zolağın
    ölçüsü qədər AZALDIR (daxili layout belə qurulub) — nazik zolaq
    (8px) belə maddələrin sahəsini 244→236px endirir və uzun başlıqların
    elide sayını artırır (ölçülüb: istifadəçi məhz mətn kəsilməsindən
    şikayət etmişdi). macOS-un sürüşdürmə zolağı LAYOUT-a təsir ETMİR —
    o, məzmunun üstündə üzür və yalnız sürüşmə baş verəndə görünür; bu
    sinif həmin naxışı təkrarlayır (layihənin dizayn dili, sırf texniki
    seçim deyil).

    ──────────────────────────────────────────────────────────────────────
    NECƏ İŞLƏYİR — QT-nin ÖZ ZOLAĞI, YALNIZ YENİDƏN YERLƏŞDİRİLİR
    ──────────────────────────────────────────────────────────────────────
    Yeni, DUBLİKAT zolaq YARADILMIR (siçan təkərİ/klaviatura/sürüşdürmə
    məntiqini TƏKRAR yazmaqdan qaçmaq üçün) — `verticalScrollBar()`
    Qt-nin ÖZ obyektidir, bütün funksionallığı DAŞIYIR. `resizeEvent`
    yalnız İKİ şeyi override edir: (1) viewport HƏMİŞƏ TAM enə qədər
    genişlənir (Qt-nin defolt "zolağa yer ayır" davranışı ƏVƏZLƏNİR),
    (2) zolağın özü sağ kənarda, viewport-un ÜSTÜNDƏ, `raise_()` ilə
    üzən vəziyyətdə yerləşdirilir.

    Zolaq `SIDEBAR_PADDING_H` (12px) sağ boşluğunun İÇİNDƏ qalır (8px enli,
    12px-lik boşluqdan kiçikdir) — düymələrin `Expanding` en siyasəti
    onları bu boşluğa QƏDƏR, yəni zolağın YERİNƏ UZATMIR, ona görə zolaq
    klikə açıq mətn/ikon sahəsini ÖRTMÜR."""

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self.viewport().setGeometry(0, 0, self.width(), self.height())

        vbar = self.verticalScrollBar()
        width = max(vbar.sizeHint().width(), 1)
        vbar.setGeometry(self.width() - width, 0, width, self.height())
        vbar.raise_()


class Sidebar(QWidget):
    """Naviqasiya paneli — 226px, daraldıla bilən.

    Signals:
        navigated: İstifadəçi maddəni seçdi (`key` ötürülür).
        collapse_toggled: Aç/bağla düyməsi basıldı (yeni vəziyyət ötürülür).
    """

    navigated = Signal(str)
    #: ──────────────────────────────────────────────────────────────────────
    #: DARALTMA ARTIQ YALNIZ PƏNCƏRƏ ENİNDƏN ASILI DEYİL
    #: ──────────────────────────────────────────────────────────────────────
    #: `set_collapsed()` əvvəldən vardı, lakin onu YALNIZ `AdminShell.
    #: apply_layout_mode()` çağırırdı — yəni panel yalnız pəncərə kiçiləndə
    #: daralırdı və istifadəçinin öz iradəsi yox idi. İstifadəçi hesabatı:
    #: «açılıb bağlanan navigation olmalıdır».
    #:
    #: Düymə vəziyyəti YAYIR, özü qərar vermir: örtük onu «əl ilə seçim» kimi
    #: yadda saxlayır və avtomatik rejimin üstünə qoyur (bax
    #: `AdminShell.apply_layout_mode`).
    collapse_toggled = Signal(bool)

    def __init__(
        self,
        *,
        idle_icon_color: str,
        active_icon_color: str,
        section_title: str = "Naviqasiya",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        enable_styled_background(self)
        self.setFixedWidth(metrics.SIDEBAR_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._idle_icon_color = idle_icon_color
        self._active_icon_color = active_icon_color
        self._buttons: dict[str, NavButton] = {}
        self._active_key: str | None = None
        self._collapsed = False

        # ──────────────────────────────────────────────────────────────────
        # BAŞLIQ SABİTDİR, MADDƏLƏR SÜRÜŞDÜRÜLƏ BİLƏR (funksional düzəliş)
        # ──────────────────────────────────────────────────────────────────
        # Əvvəl `self._layout` (bu, birbaşa `self`-ə bağlı idi) həm başlığı,
        # həm bütün maddələri birbaşa daşıyırdı, `QScrollArea` heç yerdə
        # yox idi. Nəticə ölçülüb: ROOT rolunun 42 maddəsi ~2268px tələb
        # edir, 1080p ekranda isə paneldə ~1040px yer var — sürüşdürmə
        # olmadığı üçün ~1190px-lik hissə (təxminən yarısı) HEÇ CÜR
        # açılmır, istifadəçi ora ÇATA BİLMİR. Bu, kosmetik deyil,
        # funksional qüsurdur.
        #
        # Həll: xarici `self._layout` YALNIZ iki bloku (başlıq + sürüşdürmə
        # sahəsi) daşıyır; maddələr `self._items_layout`-a keçib, o da
        # `self._scroll`-un daxili widget-indədir. Köhnə vahid padding
        # (`SIDEBAR_PADDING_H/V`) iki yerə bölünür ki, GÖRÜNÜŞ DƏYİŞMƏSİN —
        # yalnız DAVRANIŞ (sürüşdürmə) əlavə olunur.
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Başlıq sətri: bölmə adı + aç/bağla düyməsi. Düymə YUXARIDADIR,
        # çünki daraldılmış rejimdə mətn yox olur və istifadəçi paneli geri
        # açmaq üçün SABİT bir nöqtə axtarır — siyahının altında olsaydı, uzun
        # menyuda ekrandan çıxardı. BAŞLIQ SÜRÜŞMÜR — sürüşəndə panelin
        # kimliyi (bölmə adı, daraltma düyməsi) itərdi.
        header = QWidget()
        header_layout = QHBoxLayout(header)
        # SOL KƏNAR NAVİQASİYA SƏTRİ İLƏ EYNİDİR.
        #
        # Əvvəl burada 12px vardı, `QPushButton[variant="nav"]` isə QSS-də
        # `padding: 0 16px` daşıyır — yəni bölmə etiketi ikonlardan 4px SOLDA
        # başlayırdı və panelin sol kənarında iki fərqli şaquli xətt yaranırdı
        # (navbar.md PROBLEM 1 bənd 4). Dəyər `--space-md`-nin özündən gəlir:
        # ikisi bir tokendən oxunmasa, biri dəyişəndə digəri sükutla geridə
        # qalar.
        header_layout.setContentsMargins(
            metrics.NAV_ITEM_TEXT_INDENT, 0, 0, metrics.SIDEBAR_LABEL_BOTTOM
        )
        header_layout.setSpacing(4)

        self._section = section_label(section_title)
        header_layout.addWidget(self._section)
        header_layout.addWidget(stretch())

        # `icon_button()` DEYİL: bu düymə panelin İLK fokus ala bilən
        # elementidir, yəni pəncərə açılanda fokusu O alır və adi `:focus`
        # qaydası halqanı şərtsiz çəkirdi. İstifadəçi hesabatı bunu «ağ dairəvi
        # cizgi» kimi təsvir etdi (navbar.md PROBLEM 1 bənd 6).
        self._toggle = KeyFocusIconButton(
            "chevron_left",
            idle_icon_color,
            tooltip="Paneli daralt",
            accessible_name="Naviqasiya panelini daralt",
            accessible_description="Sol paneli yalnız ikonlara qədər daraldır",
            width=metrics.SIDEBAR_TOGGLE_SIZE,
            height=metrics.SIDEBAR_TOGGLE_SIZE,
        )
        self._toggle.clicked.connect(self._on_toggle_clicked)
        header_layout.addWidget(self._toggle)

        # Başlığın ÖZ qabı — köhnə `self._layout`-un sol/sağ/üst padding-i
        # BURAYA köçür (aşağıdakı sürüşdürmə sahəsi EYNİ üfüqi padding-i
        # ÖZÜ təkrarlayır). Alt padding YOXDUR: başlıqla ilk maddə arasındakı
        # boşluğu indi sürüşmə sahəsinin ÖZ üst kənar boşluğu verir (aşağı
        # bax) — əks halda iki mənbə eyni boşluğu ikiqat yaradardı.
        header_host = QWidget()
        header_host_layout = QVBoxLayout(header_host)
        header_host_layout.setContentsMargins(
            metrics.SIDEBAR_PADDING_H, metrics.SIDEBAR_PADDING_V, metrics.SIDEBAR_PADDING_H, 0
        )
        header_host_layout.addWidget(header)
        self._layout.addWidget(header_host)

        # Maddələr sürüşdürülə bilər sahədədir — bax konstruktorun başındakı
        # "BAŞLIQ SABİTDİR" şərhi. `_OverlayScrollArea` (bax yuxarı) — adi
        # `QScrollArea` DEYİL: zolaq maddələrin sahəsindən yer ALMIR.
        self._scroll = _OverlayScrollArea()
        self._scroll.setObjectName("SidebarScroll")
        self._scroll.setWidgetResizable(True)
        # `admin_shell.py`-dəki `ContentScroll` NAXIŞI TƏKRARLANIR
        # (`setFrameShape(NoFrame)`): çərçivə əlavə olunsaydı panelin sağ
        # kənarında naviqasiyaya AİD OLMAYAN ikinci bir xətt görünərdi.
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # ÜFÜQİ sürüşdürmə YOXDUR — maddələr HƏMİŞƏ panelin (sabit) eninə
        # sığır, `NavButton`-un `Expanding` ölçü siyasəti bunu təmin edir;
        # üfüqi zolağın görünməsi yalnız gözlənilməz bir dizayn səhvini
        # gizli saxlayardı.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._layout.addWidget(self._scroll, 1)

        items_host = QWidget()
        self._items_layout = QVBoxLayout(items_host)
        # SOL/SAĞ: başlıqla EYNİ üfüqi padding (`SIDEBAR_PADDING_H`) —
        # maddələr başlıqla eyni şaquli xətdən başlamalıdır. ÜST:
        # `SIDEBAR_ITEM_SPACING` — başlıqla ilk maddə arasında əvvəlki
        # `self._layout.setSpacing(SIDEBAR_ITEM_SPACING)`-in verdiyi boşluğun
        # EYNİSİ. ALT: `SIDEBAR_PADDING_V` — panelin köhnə alt padding-i,
        # indi sürüşən məzmunun sonuna keçib.
        self._items_layout.setContentsMargins(
            metrics.SIDEBAR_PADDING_H,
            metrics.SIDEBAR_ITEM_SPACING,
            metrics.SIDEBAR_PADDING_H,
            metrics.SIDEBAR_PADDING_V,
        )
        self._items_layout.setSpacing(metrics.SIDEBAR_ITEM_SPACING)
        self._items_layout.addStretch(1)
        self._scroll.setWidget(items_host)

    # ------------------------------- məzmun --------------------------------- #

    def set_entries(self, entries: tuple[MenuEntry, ...] | list[MenuEntry]) -> None:
        """Menyunu yenidən qurur.

        `NavigationRegistry.visible_for()` nəticəsi birbaşa buraya verilir.
        Rol dəyişdikdə (məs. istifadəçi dəyişdi) yenidən çağırılır — köhnə
        düymələr silinir, çünki icazəsi qalxan maddə panelə "yapışıb"
        qalmamalıdır.
        """
        self._clear()

        for entry in entries:
            button = NavButton(
                entry.key,
                entry.title_az,
                icon_name=entry.icon or FALLBACK_ICON,
                idle_color=self._idle_icon_color,
                active_color=self._active_icon_color,
            )
            button.clicked.connect(lambda _=False, key=entry.key: self._on_clicked(key))
            # `insertWidget` — sondakı stretch-dən ƏVVƏL yerləşdirilməlidir,
            # əks halda maddələr sürüşmə sahəsinin dibinə düşərdi.
            # `self._items_layout` — `self._layout` DEYİL (o, indi YALNIZ
            # başlıq + sürüşdürmə qabını daşıyır, bax konstruktor).
            self._items_layout.insertWidget(self._items_layout.count() - 1, button)
            self._buttons[entry.key] = button

        if self._active_key is not None and self._active_key in self._buttons:
            self._buttons[self._active_key].set_active(True)

    def entry_keys(self) -> tuple[str, ...]:
        """Panelin hazırda göstərdiyi açarlar — testlər üçün."""
        return tuple(self._buttons)

    def set_badge(self, key: str, count: int) -> None:
        """Maddənin oxunmamış sayğacını qurur (CHAT-1 Faza 6).

        NAMƏLUM AÇAR SÜKUTLA BURAXILIR: sayğacı yeniləyən kontroller
        səlahiyyəti olmayan istifadəçidə də işləyə bilər və o halda maddə
        panelə heç vaxt əlavə olunmur. İstisna atsaydıq, «GÖRMƏK =
        SƏLAHİYYƏTİN OLMASI» prinsipinin normal nəticəsi çökmə kimi
        görünərdi.
        """
        button = self._buttons.get(key)
        if button is not None:
            button.set_badge(count)

    def badge_count(self, key: str) -> int:
        """Maddənin sayğacı — testlər üçün. Maddə yoxdursa `0`."""
        button = self._buttons.get(key)
        return button.badge_count() if button is not None else 0

    def _clear(self) -> None:
        for button in self._buttons.values():
            self._items_layout.removeWidget(button)
            button.deleteLater()
        self._buttons.clear()

    # ------------------------------- vəziyyət -------------------------------- #

    @property
    def active_key(self) -> str | None:
        return self._active_key

    def set_active(self, key: str) -> None:
        """Aktiv maddəni dəyişir (siqnal YAYMADAN — proqramatik keçid üçün)."""
        for entry_key, button in self._buttons.items():
            button.set_active(entry_key == key)
        self._active_key = key

    def _on_clicked(self, key: str) -> None:
        self.set_active(key)
        self.navigated.emit(key)

    # ------------------------------- görünüş --------------------------------- #

    def _on_toggle_clicked(self) -> None:
        """Düymə: vəziyyəti çevirir və YAYIR (qərarı örtük verir)."""
        self.set_collapsed(not self._collapsed)
        self.collapse_toggled.emit(self._collapsed)

    def toggle_button(self) -> QPushButton:
        """Aç/bağla düyməsi — testlər və örtük üçün."""
        return self._toggle

    def set_collapsed(self, collapsed: bool) -> None:
        """Paneli daraldır — yalnız ikonlar qalır (spesifikasiya: "daralda bilər")."""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(metrics.SIDEBAR_COLLAPSED_WIDTH if collapsed else metrics.SIDEBAR_WIDTH)
        self._section.setVisible(not collapsed)
        self._apply_toggle_icon()
        for button in self._buttons.values():
            button.set_compact(collapsed)

    def _apply_toggle_icon(self) -> None:
        """İkon NƏTİCƏNİ göstərir: daralmışsa «genişlət» oxu çəkilir."""
        self._toggle.setIcon(
            icons.icon(
                "chevron_right" if self._collapsed else "chevron_left",
                self._idle_icon_color,
            )
        )
        self._toggle.setToolTip(
            plain_tooltip("Paneli genişləndir" if self._collapsed else "Paneli daralt")
        )

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def apply_theme(self, *, idle_icon_color: str, active_icon_color: str) -> None:
        """Tema dəyişdikdə ikon rənglərini yeniləyir.

        QSS fon/mətn rənglərini özü tətbiq edir, lakin ikon piksel şəklidir —
        onu yenidən çəkmək lazımdır (bax `buttons.NavButton`).
        """
        self._idle_icon_color = idle_icon_color
        self._active_icon_color = active_icon_color
        self._apply_toggle_icon()
        for button in self._buttons.values():
            button.set_colors(idle_color=idle_icon_color, active_color=active_icon_color)


__all__ = ["FALLBACK_ICON", "Sidebar"]
