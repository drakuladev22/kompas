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
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from src.presentation.theme.manager import enable_styled_background
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import NavButton
from src.presentation.widgets.primitives import section_label

if TYPE_CHECKING:
    from src.presentation.navigation import MenuEntry

#: `MenuEntry.icon` boş olduqda işlədilən ikon — menyu maddəsi ikonsuz qalsa
#: sətir sıçrayardı (mətn sola sürüşərdi), ona görə neytral bir forma verilir.
FALLBACK_ICON: Final = "list"


class Sidebar(QWidget):
    """Naviqasiya paneli — 226px, daraldıla bilən.

    Signals:
        navigated: İstifadəçi maddəni seçdi (`key` ötürülür).
    """

    navigated = Signal(str)

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

        self._section = section_label(section_title)
        self._section.setContentsMargins(12, 0, 12, metrics.SIDEBAR_LABEL_BOTTOM)
        self._layout.addWidget(self._section)

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

    def set_collapsed(self, collapsed: bool) -> None:
        """Paneli daraldır — yalnız ikonlar qalır (spesifikasiya: "daralda bilər")."""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(metrics.SIDEBAR_COLLAPSED_WIDTH if collapsed else metrics.SIDEBAR_WIDTH)
        self._section.setVisible(not collapsed)
        for button in self._buttons.values():
            button.set_compact(collapsed)

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
        for button in self._buttons.values():
            button.set_colors(idle_color=idle_icon_color, active_color=active_icon_color)


__all__ = ["FALLBACK_ICON", "Sidebar"]
