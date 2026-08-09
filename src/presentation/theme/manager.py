"""Tema meneceri — seçimin həlli, tətbiqi və yayımı (bölmə 9) — Faza 4.1.

──────────────────────────────────────────────────────────────────────────────
ÜÇ DƏYƏR, İKİ TEMA
──────────────────────────────────────────────────────────────────────────────
`user_preferences.theme` üç dəyər saxlayır (`LIGHT`/`DARK`/`SYSTEM`), lakin
faktiki palitra yalnız İKİDİR. `SYSTEM` bir palitra deyil — "OS nə deyirsə"
mənasını verən SAXLANILAN SEÇİMDİR və hər tətbiq anında yenidən həll olunur.
Bu fərq qarışdırılsa, istifadəçi OS temasını dəyişdikdə tətbiq köhnə rejimdə
qalar, çünki bir dəfə "dark" kimi yazılmış olardı.

──────────────────────────────────────────────────────────────────────────────
OS TEMASININ ZONDLANMASI NİYƏ PROTOKOLDUR
──────────────────────────────────────────────────────────────────────────────
`QStyleHints.colorScheme()` yalnız `QApplication` mövcud olduqda işləyir və
CI-ın offscreen platformasında `Unknown` qaytara bilər. Zond ayrıca protokol
olduğu üçün həll məntiqi (`resolve_mode`) Qt-siz, saf funksiya kimi test
olunur; `Unknown` halında isə İŞIQLI rejimə düşülür — səbəb aşağıda.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from PySide6.QtCore import Qt

from src.presentation.theme.qss import build_stylesheet
from src.presentation.theme.tokens import ThemeMode, theme_tokens
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QApplication, QWidget

_log = get_logger(__name__)

#: OS seçimi bilinmədikdə istifadə olunan rejim.
#:
#: İŞIQLI seçilir, çünki bu, bilinməyən mühitdə daha təhlükəsiz nəticədir:
#: tünd palitranı işıqlı ekranda oxumaq mümkündür, lakin əksi — parlaq işıq
#: altındakı mağaza kassasında tünd fon — praktikada oxunmaz olur. Kassa
#: PC-ləri məhz belə şəraitdədir (bölmə 9, PIN ekranı qeydi).
FALLBACK_MODE: ThemeMode = ThemeMode.LIGHT


@runtime_checkable
class SystemColorSchemeProbe(Protocol):
    """OS-in tema seçimini oxuyan mənbə."""

    def detect(self) -> ThemeMode | None:
        """`LIGHT`/`DARK` qaytarır; bilinmirsə `None`."""
        ...


class QtColorSchemeProbe:
    """`QStyleHints.colorScheme()` üzərindən OS temasını oxuyur."""

    def detect(self) -> ThemeMode | None:
        from PySide6.QtCore import Qt  # noqa: PLC0415
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        app = QApplication.instance()
        # `instance()` bazis tip (`QCoreApplication`) qaytarır — `styleHints()`
        # yalnız `QApplication`-da var (konsol tətbiqində ekran anlayışı yoxdur).
        if not isinstance(app, QApplication):
            return None

        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return ThemeMode.DARK
        if scheme == Qt.ColorScheme.Light:
            return ThemeMode.LIGHT
        return None


def resolve_mode(preference: ThemeMode, probe: SystemColorSchemeProbe | None = None) -> ThemeMode:
    """Saxlanılan seçimi faktiki palitraya çevirir.

    Args:
        preference: `user_preferences.theme`-dən gələn dəyər.
        probe: `SYSTEM` seçildikdə OS-ə müraciət edən zond. `None` verilsə
            və ya zond nəticə qaytarmasa `FALLBACK_MODE` işlədilir.
    """
    if preference is not ThemeMode.SYSTEM:
        return preference

    detected = probe.detect() if probe is not None else None
    if detected is None:
        _log.debug("THEME_SYSTEM_UNKNOWN", extra={"fallback": FALLBACK_MODE.value})
        return FALLBACK_MODE
    return detected


def enable_styled_background(widget: QWidget) -> None:
    """Widget-in QSS fonunu FAKTİKİ olaraq çəkməsini təmin edir.

    ──────────────────────────────────────────────────────────────────────
    QT-NİN GİZLİ QAYDASI
    ──────────────────────────────────────────────────────────────────────
    `QWidget`-dən törəmiş adi sinif QSS-dəki `background-color` qaydasını
    SƏSSİZCƏ İQNORAR EDİR. Qayda seçiciyə uyğun gəlsə belə, widget öz
    `paintEvent`-ini yazmadığı üçün fon çəkilmir — nə xəta, nə xəbərdarlıq.
    (`QFrame`, `QLabel`, `QPushButton` kimi siniflərdə bu problem yoxdur,
    çünki onların öz çəkmə məntiqi var.)

    Nəticə xüsusilə aldadıcıdır: işıqlı temada fon onsuz da ağ olduğu üçün
    "işləyir" görünür, tünd temada isə səhv rəngdə qalır. Məhz bu qüsur
    pəncərə başlığının Navy əvəzinə ağ görünməsinə səbəb olmuşdu.

    `WA_StyledBackground` atributu Qt-yə fonu üslub cədvəlinə görə çəkməyi
    tapşırır.
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


def refresh_widget_style(widget: QWidget) -> None:
    """Dinamik xüsusiyyət dəyişdikdən sonra üslubu yenidən hesablatdırır.

    Qt `setProperty("variant", ...)` çağırışından SONRA QSS-i özü yeniləmir —
    seçici artıq uyğun gəlsə belə widget köhnə görünüşdə qalır. Bu funksiya
    olmadan "aktiv menyu maddəsi" kimi vəziyyət dəyişiklikləri görünməzdi.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class ThemeManager:
    """Cari temanı saxlayır, `QApplication`-a tətbiq edir və dəyişikliyi yayır.

    Abunəçilər (`subscribe`) tema dəyişəndə xəbərdar edilir — QSS ilə ifadə
    oluna bilməyən elementlər (məs. `QPainter` ilə çəkilən qrafiklər, loqonun
    tünd/işıqlı variantı) özlərini burada yeniləyir.
    """

    def __init__(
        self,
        *,
        preference: ThemeMode = ThemeMode.SYSTEM,
        probe: SystemColorSchemeProbe | None = None,
    ) -> None:
        self._preference = preference
        self._probe = probe if probe is not None else QtColorSchemeProbe()
        self._mode = resolve_mode(preference, self._probe)
        self._listeners: list[Callable[[ThemeMode], None]] = []

    # ------------------------------- vəziyyət ------------------------------- #

    @property
    def preference(self) -> ThemeMode:
        """İstifadəçinin saxlanılan seçimi (`SYSTEM` ola bilər)."""
        return self._preference

    @property
    def mode(self) -> ThemeMode:
        """Faktiki tətbiq olunan palitra (`LIGHT` və ya `DARK`)."""
        return self._mode

    @property
    def tokens(self) -> dict[str, str]:
        """Cari rejimin tokenləri — QSS-siz çəkilən komponentlər üçün."""
        return theme_tokens(self._mode)

    def color(self, token: str) -> str:
        """Tək tokenin dəyəri.

        Raises:
            KeyError: Token mövcud deyil — səhv yazılmış ad səssiz keçməsin.
        """
        return self.tokens[token]

    # ------------------------------- tətbiq --------------------------------- #

    def stylesheet(self) -> str:
        return build_stylesheet(self.tokens)

    def apply(self, app: QApplication) -> None:
        """QSS-i tətbiqə yazır."""
        app.setStyleSheet(self.stylesheet())
        _log.info(
            "THEME_APPLIED",
            extra={"preference": self._preference.value, "mode": self._mode.value},
        )

    def set_preference(self, preference: ThemeMode, app: QApplication | None = None) -> ThemeMode:
        """Seçimi dəyişir, lazım gələrsə yenidən tətbiq edir və abunəçiləri xəbərdar edir.

        Returns:
            Yeni FAKTİKİ rejim (`SYSTEM` verilibsə həll olunmuş dəyər).
        """
        self._preference = preference
        new_mode = resolve_mode(preference, self._probe)
        changed = new_mode is not self._mode
        self._mode = new_mode

        if app is not None:
            self.apply(app)
        if changed:
            self._notify()
        return new_mode

    def reevaluate_system(self, app: QApplication | None = None) -> bool:
        """OS teması dəyişdikdə yenidən həll edir.

        Yalnız seçim `SYSTEM` olduqda təsir göstərir — istifadəçi açıq şəkildə
        işıqlı/tünd seçibsə, OS-in fikri onu ləğv etməməlidir.

        Returns:
            Rejim dəyişdisə `True`.
        """
        if self._preference is not ThemeMode.SYSTEM:
            return False

        previous = self._mode
        return self.set_preference(ThemeMode.SYSTEM, app) is not previous

    # ------------------------------ abunəliklər ------------------------------ #

    def subscribe(self, listener: Callable[[ThemeMode], None]) -> Callable[[], None]:
        """Tema dəyişikliyinə abunə olur.

        Returns:
            Abunəliyi ləğv edən funksiya — bağlanan pəncərə özünü çıxarmalıdır,
            əks halda menecer silinmiş widget-ə müraciət edərdi.
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener(self._mode)
            except Exception:
                _log.exception("THEME_LISTENER_FAILED", extra={"mode": self._mode.value})


__all__ = [
    "FALLBACK_MODE",
    "QtColorSchemeProbe",
    "SystemColorSchemeProbe",
    "ThemeManager",
    "refresh_widget_style",
    "resolve_mode",
]
