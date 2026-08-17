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

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import KeyFocusIconButton, NavButton
from src.presentation.widgets.primitives import section_label, stretch
from src.presentation.widgets.safe_text import plain_tooltip

if TYPE_CHECKING:
    from src.presentation.navigation import MenuEntry

#: `MenuEntry.icon` boş olduqda işlədilən ikon — menyu maddəsi ikonsuz qalsa
#: sətir sıçrayardı (mətn sola sürüşərdi), ona görə neytral bir forma verilir.
FALLBACK_ICON: Final = "list"


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

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            metrics.SIDEBAR_PADDING_H,
            metrics.SIDEBAR_PADDING_V,
            metrics.SIDEBAR_PADDING_H,
            metrics.SIDEBAR_PADDING_V,
        )
        self._layout.setSpacing(metrics.SIDEBAR_ITEM_SPACING)

        # Başlıq sətri: bölmə adı + aç/bağla düyməsi. Düymə YUXARIDADIR,
        # çünki daraldılmış rejimdə mətn yox olur və istifadəçi paneli geri
        # açmaq üçün SABİT bir nöqtə axtarır — siyahının altında olsaydı, uzun
        # menyuda ekrandan çıxardı.
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

        self._layout.addWidget(header)

        self._layout.addStretch(1)

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
            # əks halda maddələr panelin dibinə düşərdi.
            self._layout.insertWidget(self._layout.count() - 1, button)
            self._buttons[entry.key] = button

        if self._active_key is not None and self._active_key in self._buttons:
            self._buttons[self._active_key].set_active(True)

    def entry_keys(self) -> tuple[str, ...]:
        """Panelin hazırda göstərdiyi açarlar — testlər üçün."""
        return tuple(self._buttons)

    def _clear(self) -> None:
        for button in self._buttons.values():
            self._layout.removeWidget(button)
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
