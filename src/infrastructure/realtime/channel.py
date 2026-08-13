"""Canlı yeniləmə kanalı — WebSocket + polling fallback (spesifikasiya bölmə 6).

Bölmə 6: *"Real-time yeniləmə WebSocket (Supabase Realtime) üzərindən, polling
fallback ilə."*

──────────────────────────────────────────────────────────────────────────────
FALLBACK NİYƏ AVTOMATİKDİR VƏ NİYƏ GERİ QAYIDIR
──────────────────────────────────────────────────────────────────────────────
Mağaza şəbəkələri qeyri-sabitdir: WebSocket bağlantısı gün ərzində bir neçə
dəfə qırıla bilər. İki sadə qərar var idi —

    (a) qırılanda polling-ə keç və ORADA QAL — dashboard günün qalanında
        gecikmiş məlumat göstərərdi;
    (b) yalnız WebSocket — qırıq bağlantıda ekran DONARDI.

Hər ikisi pisdir. Buradakı model: qırılanda dərhal polling-ə keçilir (məlumat
axını KƏSİLMİR), lakin WebSocket-i yenidən qurmaq cəhdləri artan gecikmə ilə
davam edir. Bağlantı qayıdan kimi polling dayanır.

──────────────────────────────────────────────────────────────────────────────
"DEGRADED" VƏZİYYƏTİ NİYƏ GİZLƏDİLMİR
──────────────────────────────────────────────────────────────────────────────
Polling rejimində məlumat 30 saniyəyə qədər köhnə ola bilər. İstifadəçi bunu
BİLMƏLİDİR — canlı zənn etdiyi rəqəmə əsasən qərar verə bilər (məsələn "növbədə
kimsə yoxdur" deyib gedə bilər). `RealtimeState.DEGRADED` məhz bunun üçündür və
ekranda nişan kimi göstərilir.

──────────────────────────────────────────────────────────────────────────────
BU MODUL TAYMER YARATMIR
──────────────────────────────────────────────────────────────────────────────
Qt tətbiqində taymer `QTimer` olmalıdır (GUI axınında), testdə isə heç bir
taymer olmamalıdır. Ona görə `tick()` XARİCDƏN çağırılır — modul yalnız
"indi nə etməliyəm?" sualına cavab verir. Beləliklə bütün keçid məntiqi
saniyə gözləmədən test olunur.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, Protocol

from src.domain.policies import SystemLimitKey
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_int,
    fallback_int_tuple,
)
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: HƏR İKİSİ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`REALTIME_POLL_INTERVAL_SECONDS`, `REALTIME_RECONNECT_BACKOFF_SECONDS`;
#: seed: migrations/032). Yük 21 filialın SAYINDAN və şəbəkə keyfiyyətindən
#: asılıdır — tək mağazalı quraşdırma daha tez-tez sorğu edə bilər, böyük
#: şəbəkə isə aralığı uzatmalıdır.
#:
#: Polling rejimində sorğu aralığı (saniyə). 30 saniyə seçilib: daha tez-tez
#: sorğu 21 filialdan gələn yüklə bazanı lazımsız yükləyər, daha seyrək isə
#: "canlı" hissini tamamilə itirər.
FALLBACK_POLL_SECONDS: Final[int] = fallback_int(SystemLimitKey.REALTIME_POLL_INTERVAL_SECONDS)
#: WebSocket-i yenidən qurmaq cəhdləri arasındakı artan gecikmə.
FALLBACK_RECONNECT_BACKOFF_SECONDS: Final[tuple[int, ...]] = fallback_int_tuple(
    SystemLimitKey.REALTIME_RECONNECT_BACKOFF_SECONDS
)


class RealtimeState(str, Enum):
    """Kanalın cari vəziyyəti."""

    LIVE = "LIVE"
    #: WebSocket yoxdur, məlumat polling ilə gəlir — GECİKMƏLİ ola bilər.
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"

    @property
    def label_az(self) -> str:
        return {
            RealtimeState.LIVE: "Canlı",
            RealtimeState.DEGRADED: "Gecikmiş (yenilənmə hər 30 san)",
            RealtimeState.STOPPED: "Dayandırılıb",
        }[self]

    @property
    def is_delayed(self) -> bool:
        """İstifadəçiyə xəbərdarlıq nişanı göstərilməlidirmi."""
        return self is RealtimeState.DEGRADED


class RealtimeTransport(Protocol):
    """Supabase Realtime abunəliyi — infrastruktur detalı.

    `connect()` uğursuz olarsa istisna ATIR; kanal onu tutub polling-ə keçir.
    """

    def connect(self, channels: Iterable[str], on_event: Callable[[str, Any], None]) -> None: ...

    def disconnect(self) -> None: ...

    def is_connected(self) -> bool: ...


class LiveUpdateChannel:
    """WebSocket-i idarə edir, qırıldıqda polling-ə keçir.

    Testdə `transport` və `poll` saxta funksiyalarla əvəzlənir — real şəbəkə
    və real saniyə lazım deyil (modul başlığına bax).
    """

    def __init__(
        self,
        *,
        channels: list[str],
        transport: RealtimeTransport | None,
        poll: Callable[[], None],
        on_event: Callable[[str, Any], None] | None = None,
        poll_seconds: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            poll_seconds: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.
        """
        self._channels = channels
        self._transport = transport
        self._poll = poll
        self._on_event = on_event or (lambda _channel, _payload: None)
        self._explicit_poll_seconds = poll_seconds
        self._limits = limits or InfrastructureLimits()

        self._state = RealtimeState.STOPPED
        self._elapsed = 0
        self._reconnect_attempts = 0
        self._seconds_since_attempt = 0
        self._poll_count = 0

    # -------------------------------- vəziyyət ------------------------------- #

    @property
    def state(self) -> RealtimeState:
        return self._state

    @property
    def poll_count(self) -> int:
        """Neçə dəfə polling sorğusu edilib — diaqnostika üçün."""
        return self._poll_count

    # --------------------------------- həyat --------------------------------- #

    def start(self) -> RealtimeState:
        """Kanalı açır. WebSocket alınmasa DƏRHAL polling-ə keçir."""
        if self._transport is None:
            # Nəqliyyat konfiqurasiya edilməyib (offline quraşdırma) —
            # bu, xəta deyil, sadəcə polling rejimidir.
            return self._degrade("Realtime nəqliyyatı konfiqurasiya edilməyib")

        try:
            self._transport.connect(self._channels, self._on_event)
        except Exception as exc:
            return self._degrade(str(exc))

        self._state = RealtimeState.LIVE
        self._reconnect_attempts = 0
        _log.info("REALTIME_CONNECTED", extra={"channels": self._channels})
        return self._state

    def stop(self) -> None:
        if self._transport is not None:
            try:
                self._transport.disconnect()
            except Exception:
                # Bağlanma uğursuzluğu maraqlı deyil — obyekt onsuz da atılır.
                _log.debug("REALTIME_DISCONNECT_FAILED")
        self._state = RealtimeState.STOPPED

    # ---------------------------------- tick --------------------------------- #

    def tick(self, seconds: int = 1) -> None:
        """Xaricdən çağırılan saat addımı (modul başlığına bax)."""
        if self._state is RealtimeState.STOPPED:
            return

        if self._state is RealtimeState.LIVE:
            self._check_liveness()
            return

        self._elapsed += seconds
        self._seconds_since_attempt += seconds

        if self._elapsed >= self._poll_interval():
            self._elapsed = 0
            self._run_poll()

        if self._seconds_since_attempt >= self._current_backoff():
            self._seconds_since_attempt = 0
            self._try_reconnect()

    def _check_liveness(self) -> None:
        """WebSocket hələ də açıqdırmı.

        Nəqliyyat özü xəbər vermir (Supabase klienti sükutla qırıla bilər),
        ona görə hər tick-də açıq şəkildə soruşulur.
        """
        if self._transport is None or self._transport.is_connected():
            return
        self._degrade("WebSocket bağlantısı qırıldı")

    def _run_poll(self) -> None:
        """Fallback sorğusu — uğursuzluq kanalı DAYANDIRMIR."""
        self._poll_count += 1
        try:
            self._poll()
        except Exception as exc:
            _error_log.error("REALTIME_POLL_FAILED", extra={"error": str(exc)})

    def _try_reconnect(self) -> None:
        if self._transport is None:
            return
        try:
            self._transport.connect(self._channels, self._on_event)
        except Exception as exc:
            self._reconnect_attempts += 1
            _log.info(
                "REALTIME_RECONNECT_FAILED",
                extra={"attempt": self._reconnect_attempts, "error": str(exc)},
            )
            return

        self._state = RealtimeState.LIVE
        self._reconnect_attempts = 0
        self._elapsed = 0
        _log.info("REALTIME_RECOVERED", extra={"channels": self._channels})

    def _current_backoff(self) -> int:
        schedule = self._limits.int_tuple_of(SystemLimitKey.REALTIME_RECONNECT_BACKOFF_SECONDS)
        index = min(self._reconnect_attempts, len(schedule) - 1)
        return schedule[index]

    def _poll_interval(self) -> int:
        """Polling aralığı — HƏR TİKDƏ oxunur.

        Kanal sessiya boyu yaşayır; Root aralığı dəyişəndə növbəti tik artıq
        yeni dəyərlə hesablanır və yenidən qoşulma tələb olunmur.
        """
        if self._explicit_poll_seconds is not None:
            return self._explicit_poll_seconds
        return self._limits.int_of(SystemLimitKey.REALTIME_POLL_INTERVAL_SECONDS)

    def _degrade(self, reason: str) -> RealtimeState:
        """Polling rejiminə keçir və DƏRHAL bir sorğu edir.

        Dərhal sorğu vacibdir: onsuz ekran ilk 30 saniyə tamamilə boş qalardı
        və istifadəçi tətbiqi "sınmış" hesab edərdi.
        """
        was_live = self._state is RealtimeState.LIVE
        self._state = RealtimeState.DEGRADED
        self._elapsed = 0
        self._seconds_since_attempt = 0
        if was_live:
            self._reconnect_attempts = 0
        _log.warning("REALTIME_DEGRADED", extra={"reason": reason})
        self._run_poll()
        return self._state


__all__ = [
    "FALLBACK_POLL_SECONDS",
    "FALLBACK_RECONNECT_BACKOFF_SECONDS",
    "LiveUpdateChannel",
    "RealtimeState",
    "RealtimeTransport",
]
