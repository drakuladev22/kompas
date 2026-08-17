"""Başlıq zolağındakı canlı saat — server vaxtını göstərir (TIME-1 Faza 2.3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA WIDGET — VƏ NİYƏ WINDOWS SAATINI GÖSTƏRMİR
──────────────────────────────────────────────────────────────────────────────
Bu saat `datetime.now()` OXUMUR. O, `Clock` portundan — yəni server lövbərli
`ServerTimeService`-dən — gəlir. Fərq gözlə görünəndir və məhz görünməsi
üçündür: istifadəçi Windows saatını iki saat irəli çəkəndə tapşırıqlar
panelindəki saat sıçrayır, PROQRAMDAKI saat isə YERİNDƏ QALIR.

Bu, sadəcə xoş detal deyil — davranış dəyişikliyinin GÖRÜNƏN sübutudur.
Saat manipulyasiyası edən adam nəticəsiz qaldığını dərhal görür, HR isə
"işçi saatı dəyişib" iddiasını ekranın özündən yoxlaya bilir.

──────────────────────────────────────────────────────────────────────────────
VAXT BAKI YERLİ VAXTI İLƏ GÖSTƏRİLİR, UTC SAXLANILIR
──────────────────────────────────────────────────────────────────────────────
`clock.now()` UTC qaytarır (bütün saxlama UTC-dir). Ekranda isə istifadəçinin
gözlədiyi yerli vaxt olmalıdır, ona görə `to_baku()` tətbiq olunur —
`clock.py`-dakı «UI-da göstərmək üçün; SAXLANMA həmişə UTC-dir» qaydası.

──────────────────────────────────────────────────────────────────────────────
TAYMER YALNIZ MƏNBƏ VERİLƏNDƏ İŞLƏYİR
──────────────────────────────────────────────────────────────────────────────
Widget mənbəsiz qurula bilir və o halda BOŞDUR, taymer də başlamır. Səbəb
praktikdir: önizləmə/maket yolu (`preview_screens`) və e2e testləri saatsız
işləyir və hər saniyə tıqqıldayan taymer onlarda yalnız səs-küy yaradardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QWidget

from src.domain.value_objects.time_integrity import TimeTrustLevel
from src.infrastructure.timekeeping.clock import to_baku
from src.presentation.widgets.primitives import plain_label

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.interfaces.ports import Clock
    from src.domain.value_objects.time_integrity import TimeIntegrityStatus

#: Yeniləmə aralığı. Saniyə göstərildiyi üçün 1 saniyədir — daha seyrək
#: yeniləmə saatın "donmuş" görünməsinə səbəb olardı və manipulyasiya
#: sınağında (saatı dəyiş → proqramdakı saat dəyişmir) fərq gec görünərdi.
TICK_MS: Final[int] = 1000

#: Vaxt təxminidirsə mətnin yanına qoyulan işarə. Rəng DEYİL, SİMVOL:
#: başlıq zolağı dar və tünddür, orada rəng fərqi kiçik mətndə oxunmur.
APPROXIMATE_MARK: Final[str] = "~"


class LiveClock(QWidget):
    """`HH:MM:SS` — server lövbərli vaxt, təxmini olduqda işarə ilə."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LiveClock")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = plain_label("")
        self._label.setObjectName("LiveClockText")
        layout.addWidget(self._label)

        self._clock: Clock | None = None
        self._status: Callable[[], TimeIntegrityStatus] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.refresh)

    # ------------------------------- quraşdırma ------------------------------ #

    def set_source(
        self,
        clock: Clock,
        *,
        status: Callable[[], TimeIntegrityStatus] | None = None,
    ) -> None:
        """Vaxt mənbəyini bağlayır və taymeri başladır.

        Args:
            clock: `Clock` portu — istehsalatda `ServerTimeService`.
            status: vaxtın etibarlılıq səviyyəsi. Verilməzsə işarə
                göstərilmir — «bilmirik» ilə «dəqiqdir» qarışdırılmasın deyə
                bu halda tooltip də qoyulmur.
        """
        self._clock = clock
        self._status = status
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        """Taymeri dayandırır — pəncərə bağlananda çağırılır."""
        self._timer.stop()

    # -------------------------------- yeniləmə ------------------------------- #

    def refresh(self) -> None:
        """Mətni yeniləyir. İstisna udulur: saat tətbiqi çökdürməməlidir."""
        clock = self._clock
        if clock is None:
            return
        try:
            moment = to_baku(clock.now())
        except Exception:
            # Mənbə nasazdırsa saat BOŞALIR, köhnə dəyər QALMIR: donmuş rəqəm
            # işləyən saat kimi oxunardı və bu, yanlış məlumatdır.
            self._label.setText("")
            self.setToolTip("")
            return

        text = moment.strftime("%H:%M:%S")
        status = self._read_status()
        if status is not None and status.is_approximate:
            text = f"{APPROXIMATE_MARK}{text}"
            self._label.setToolTip(status.describe())
        elif status is not None:
            self._label.setToolTip(status.describe())
        self._label.setText(text)

    def _read_status(self) -> TimeIntegrityStatus | None:
        if self._status is None:
            return None
        try:
            return self._status()
        except Exception:
            return None

    # ------------------------------- test üçün ------------------------------- #

    @property
    def text(self) -> str:
        """Göstərilən mətn — testlər QLabel-in daxilinə girməsin deyə."""
        return self._label.text()

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()


def trust_tooltip(level: TimeTrustLevel) -> str:
    """Səviyyə → tooltip mətni; ekranlar da eyni mətni işlədə bilsin deyə açıqdır."""
    return {
        TimeTrustLevel.SERVER_VERIFIED: "Vaxt server ilə təsdiqlənib",
        TimeTrustLevel.MONOTONIC_ESTIMATE: "Server ilə əlaqə yoxdur — vaxt təxminidir",
        TimeTrustLevel.UNTRUSTED: "Vaxt dəqiqliyi şübhəlidir",
    }[level]


__all__ = ["APPROXIMATE_MARK", "TICK_MS", "LiveClock", "trust_tooltip"]
