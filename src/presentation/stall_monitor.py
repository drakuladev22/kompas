"""Əsas sapın DONMA ölçüsü — «ağır işləyir» şikayətini rəqəmə çevirir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
Bu layihədə donma qüsurları TƏKRAR-TƏKRAR eyni yolla tapıldı: istifadəçi
«proqram ağır işləyir» dedi, biz jurnaldakı İKİ hadisənin vaxt fərqinə baxıb
donmanı ÇIXARIŞ yolu ilə hesabladıq (`GUI_STARTED` 0.46 s → `STARTUP_RETRY_
FAILED` 7.30 s, aradakı ~6.8 saniyə). Bu üsulun iki qüsuru var:

    * yalnız ARASINDA jurnal yazısı olan donmalar görünür — səssiz yolda
      bloklayan hər hansı əməliyyat tamamilə görünməz qalır;
    * ölçü SONRADAN, şikayətdən sonra edilir. Yəni qüsur həmişə əvvəlcə
      müştəridə üzə çıxır.

`StallMonitor` bunu tərsinə çevirir: donma BAŞ VERƏN KİMİ və ÖZÜ jurnala
düşür, üstəlik neçə millisaniyə olduğu ilə. Bir dəfə quraşdırılır və bütün
ekranlara, bütün yollara eyni anda şamil olur — hər ekran üçün ayrıca ölçü
yazmaq lazım gəlmir.

──────────────────────────────────────────────────────────────────────────────
NECƏ İŞLƏYİR — «GECİKMİŞ TAYMER» PRİNSİPİ
──────────────────────────────────────────────────────────────────────────────
`QTimer` hadisə dövrəsində işləyir. Əsas sap bloklanıbsa taymer AT ƏSA
İŞLƏMİR — o, blokdan SONRA, GECİKMƏ ilə işə düşür. Məhz bu gecikmə ölçüdür:

    gözlənilən: 500 ms      faktiki: 7300 ms      donma: 6800 ms

Yəni monitor donmanı BAŞ VERƏRKƏN görə bilmir (görsəydi, o da bloklanmış
sapda olardı) — o, donma BİTƏN kimi onu ölçür. Bu, məqsəd üçün kifayətdir:
bizə lazım olan xəbərdarlıq deyil, SÜBUTdur — hansı əməliyyat neçə saniyə
bloklayıb.

Ayrı bir sapda «canlıyam?» soruşan variant da mümkündür və o, donmanı
CANLI görərdi. Seçilmədi: ölçünün özü üçün əlavə sap və sap-arası
sinxronizasiya lazım olardı, halbuki ölçü DƏQİQLİYİ (donma 6.8 s idi, yoxsa
6.9 s) bu problemdə heç bir qərara təsir etmir. Sadə mexanizm işlək qalır,
mürəkkəbi isə öz nasazlıqlarını gətirər.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İSTEHSALATDA DA AÇIQDIR, YALNIZ TESTDƏ YOX
──────────────────────────────────────────────────────────────────────────────
İki taymer siqnalı arasında `perf_counter()` oxumaq ölçüləbilən yük DEYİL
(500 ms-də bir çağırış). Buna qarşılıq götürdüyümüz şey böyükdür: mağazadakı
maşında baş verən donma bizə ÖZÜ xəbər verir — həmin PC-yə çıxış tələb
etmədən, istifadəçinin «bir az ağır idi» təsvirinə güvənmədən.

Hədd `KOMPASOS_STALL_WARN_MS` ilə dəyişilir. Bu, `system_limits` açarı DEYİL
(CLAUDE.md bölmə 5): dəyər bazadan oxunsaydı, monitor bazadan ƏVVƏL — məhz
açılış yolunda, ən çox donan yerdə — işə düşə bilməzdi. Dövri asılılıq
`HARDWARE_PROBE_TIMEOUT_SECONDS` ilə eynidir.
"""

from __future__ import annotations

import os
from time import perf_counter
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, QTimer, Signal

from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

_log = get_logger(__name__)

#: Nəbz aralığı. 500 ms qəsdən seçilib: insan gözü ~100 ms-dən qısa
#: kilidlənməni onsuz da hiss etmir, daha tez-tez soruşmaq isə yalnız jurnalı
#: doldurardı.
HEARTBEAT_INTERVAL_MS: Final = 500

#: Bu qədər GECİKMƏ donma sayılır. 1000 ms — «kliklədim, cavab yoxdur»
#: hissinin başladığı hədd. Aşağı salsaq hər açılış animasiyası jurnala
#: düşərdi; qaldırsaq istifadəçinin şikayət etdiyi 1–3 saniyəlik kilidlənmələr
#: görünməz qalardı.
DEFAULT_STALL_THRESHOLD_MS: Final = 1000

#: Həddi dəyişən mühit açarı (`.env.example`-də sənədləşdirilib).
STALL_ENV_KEY: Final = "KOMPASOS_STALL_WARN_MS"


def stall_threshold_ms(environ: dict[str, str] | None = None) -> int:
    """Mühitdən oxunan hədd — səhv dəyər SÜKUTLA defolta qayıdır.

    Səhv yazılmış diaqnostika açarı tətbiqi işə salmamaq üçün SƏBƏB DEYİL:
    monitor köməkçi alətdir, onun ucbatından proqramın açılmaması ölçmək
    istədiyimiz problemdən betər olardı. Ona görə burada istisna atılmır,
    lakin dəyər jurnala düşür ki, «niyə hədd tətbiq olunmadı» sualı cavabsız
    qalmasın.
    """
    raw = (environ if environ is not None else os.environ).get(STALL_ENV_KEY, "").strip()
    if not raw:
        return DEFAULT_STALL_THRESHOLD_MS
    try:
        value = int(raw)
    except ValueError:
        _log.warning("STALL_THRESHOLD_INVALID", extra={"value": raw})
        return DEFAULT_STALL_THRESHOLD_MS
    if value <= 0:
        _log.warning("STALL_THRESHOLD_INVALID", extra={"value": raw})
        return DEFAULT_STALL_THRESHOLD_MS
    return value


class StallMonitor(QObject):
    """Əsas sapın kilidlənmələrini ölçür və jurnala yazır.

    Attributes:
        stalled: Donma aşkarlandıqda yayılır — arqument millisaniyədir.
            Testlər buna qoşulur; istehsalatda heç kim qoşulmur, çünki
            istifadəçiyə göstəriləcək bir şey yoxdur (donma ARTIQ bitib).
    """

    stalled = Signal(int)

    def __init__(
        self,
        *,
        threshold_ms: int | None = None,
        interval_ms: int = HEARTBEAT_INTERVAL_MS,
        parent: QObject | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        super().__init__(parent)
        self._threshold_ms = threshold_ms if threshold_ms is not None else stall_threshold_ms()
        self._interval_ms = interval_ms
        self._clock = clock
        self._last = clock()
        #: Ən uzun donma — sessiyanın sonunda bir rəqəmlə hesabat vermək üçün.
        self.worst_ms = 0
        #: Aşkarlanan donmaların sayı.
        self.count = 0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    @property
    def threshold_ms(self) -> int:
        return self._threshold_ms

    def start(self) -> None:
        """Ölçməyə başlayır. Təkrar çağırış zərərsizdir."""
        self._last = self._clock()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        """Taymer nə qədər GEC işə düşdü — fərq elə donmanın özüdür."""
        now = self._clock()
        elapsed_ms = int((now - self._last) * 1000)
        self._last = now
        lag_ms = elapsed_ms - self._interval_ms
        if lag_ms < self._threshold_ms:
            return
        self.count += 1
        self.worst_ms = max(self.worst_ms, lag_ms)
        _log.warning(
            "MAIN_THREAD_STALL",
            extra={"stall_ms": lag_ms, "threshold_ms": self._threshold_ms},
        )
        self.stalled.emit(lag_ms)


__all__ = [
    "DEFAULT_STALL_THRESHOLD_MS",
    "HEARTBEAT_INTERVAL_MS",
    "STALL_ENV_KEY",
    "StallMonitor",
    "stall_threshold_ms",
]
