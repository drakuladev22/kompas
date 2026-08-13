"""SNTP klienti və saat-sürüşməsi nəzarətçisi (spesifikasiya bölmə 2) — Faza 3.4.

Spesifikasiya: *"Fərq 60 saniyədən çoxdursa, tətbiq `TIME_DRIFT_DETECTED`
xəbərdarlığı verir və kritik əməliyyatları (PIN handshake, override)
müvəqqəti bloklayır."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU ÜMUMİYYƏTLƏ TƏHLÜKƏSİZLİK MƏSƏLƏSİDİR
──────────────────────────────────────────────────────────────────────────────
Bütün davamiyyət məntiqi (gecikmə dəqiqələri → cərimə, 45 dəqiqəlik timeout,
30 dəqiqəlik dual-control həddi) mağaza PC-sinin saatına əsaslanır. Saatı 20
dəqiqə geri çəkmək = gecikməni və cəriməni silmək. Ona görə vaxt-kritik
əməliyyatlar yoxlanılmamış saatla icra edilməməlidir.

──────────────────────────────────────────────────────────────────────────────
ÜÇ HALIN FƏRQLƏNDİRİLMƏSİ (ƏSAS DİZAYN QƏRARI)
──────────────────────────────────────────────────────────────────────────────
"Sürüşmə yoxdur" ilə "sürüşməni ölçə bilmədik" EYNİ ŞEY DEYİL:

    ölçülüb, hədd daxilində  → verified=True,  drift=<dəyər>  → icazə var
    ölçülüb, həddi aşır      → verified=False, drift=<dəyər>  → BLOKLANIR
    heç ölçülməyib           → verified=False, drift=None     → icazə var,
                                                                lakin qeydə
                                                                alınır

Üçüncü hal qəsdən bloklamır: mağazada UDP/123 bağlıdırsa bütün işi dayandırmaq
saat sürüşməsindən daha böyük zərərdir (tətbiq bölmə 5-də "offline-first"
elan olunub). Bunun əvəzinə hadisə `security.log`-a düşür və System Health
Monitor-da (bölmə 6) görünür.

──────────────────────────────────────────────────────────────────────────────
LATCH (MƏNDƏLƏMƏ) — SADƏ, LAKİN VACİB DETAL
──────────────────────────────────────────────────────────────────────────────
Əgər sürüşmə bir dəfə həddi aşıbsa, ölçmə "köhnəldi" deyə blok AVTOMATİK
götürülmür. Əks halda hücum çox ucuz olardı: saatı dəyiş, sonra NTP trafikini
blokla → ölçmə köhnəlir → drift `None` olur → blok itir. Ona görə blok yalnız
YENİ VƏ UĞURLU ölçmə həddin daxilində olduqda açılır.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from src.domain.policies import SystemLimitKey
from src.infrastructure.config.limits import InfrastructureLimits, fallback_float
from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: NTP dövrü 1900-01-01, Unix dövrü 1970-01-01 — aradakı saniyə fərqi.
NTP_UNIX_DELTA: Final[int] = 2_208_988_800
NTP_PACKET_SIZE: Final[int] = 48
#: LI=0 (xəbərdarlıq yox), VN=4 (versiya), Mode=3 (klient) → 0b00_100_011.
NTP_CLIENT_HEADER: Final[int] = 0x23
NTP_PORT: Final[int] = 123
#: Cavab paketində Mode sahəsi 4 (server) olmalıdır.
NTP_SERVER_MODE: Final[int] = 4
#: Stratum 0 = "kiss-of-death" (server imtina edir), 16+ = sinxronlaşdırılmayıb.
MIN_STRATUM: Final[int] = 1
MAX_STRATUM: Final[int] = 15
#: 2^32 — fraksiya hissəsinin böləni.
FRACTION_DIVISOR: Final[float] = 4_294_967_296.0
#: Originate timestamp bu dəqiqliklə üst-üstə düşməlidir (saniyə).
ORIGINATE_TOLERANCE_SECONDS: Final[float] = 1e-3

DEFAULT_SERVERS: Final[tuple[str, ...]] = (
    "pool.ntp.org",
    "time.windows.com",
    "time.google.com",
)
#: BEŞİ DƏ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`. Sürüşmə həddi ARTIQ
#: ROOT parametri idi (`NTP_MAX_DRIFT_SECONDS`, `schema.sql`); qalan dördü
#: migrations/032 ilə əlavə olundu (`NTP_POLL_INTERVAL_SECONDS`,
#: `NTP_QUERY_TIMEOUT_SECONDS`, `NTP_SAMPLE_TTL_SECONDS`,
#: `NTP_MAX_ROUND_TRIP_SECONDS`). Bu ədədlər yalnız ROOT portu əlçatmaz
#: olduqda işə düşür.
#:
#: NİYƏ ROOT PARAMETRİDİR: mağaza şəbəkəsi UDP/123-ü ləng ötürə bilər (proxy,
#: mobil modem) və 3 saniyəlik taymaut belə yerlərdə HƏMİŞƏ ölçməsiz nəticə
#: verərdi — bu isə "vaxt yoxlanıla bilmir" xəbərdarlığının daimi görünməsi
#: deməkdir. Protokol sabitləri (paket ölçüsü, port 123, stratum hüdudları,
#: fraksiya böləni) isə YUXARIDA qalır: onlar RFC 4330 tələbidir, siyasət deyil.
FALLBACK_MAX_DRIFT_SECONDS: Final[float] = fallback_float(SystemLimitKey.NTP_MAX_DRIFT_SECONDS)
FALLBACK_POLL_INTERVAL_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.NTP_POLL_INTERVAL_SECONDS
)
FALLBACK_TIMEOUT_SECONDS: Final[float] = fallback_float(SystemLimitKey.NTP_QUERY_TIMEOUT_SECONDS)
#: Bu müddətdən köhnə ölçmə "təzə" sayılmır (verified=False olur).
FALLBACK_SAMPLE_TTL_SECONDS: Final[float] = fallback_float(SystemLimitKey.NTP_SAMPLE_TTL_SECONDS)
#: Şəbəkə gecikməsi bundan böyükdürsə ölçmə etibarsızdır (ölçü xətası
#: sürüşmənin özündən böyük ola bilər).
FALLBACK_MAX_ACCEPTABLE_DELAY_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.NTP_MAX_ROUND_TRIP_SECONDS
)


class NtpError(Exception):
    """SNTP sorğusu uğursuz oldu (daxili — istifadəçiyə çıxarılmır)."""


@dataclass(frozen=True)
class NtpSample:
    """Bir uğurlu SNTP ölçməsi."""

    server: str
    #: Serverin saatı - yerli saat. Müsbət → yerli saat GERİ qalır.
    offset_seconds: float
    #: Gediş-dönüş gecikməsi — ölçmənin dəqiqlik göstəricisi.
    delay_seconds: float
    stratum: int
    #: `time.monotonic()` anı — köhnəlmə hesabı üçün. Divar saatı İSTİFADƏ
    #: OLUNMUR: saatın etibarlılığını saatın özü ilə ölçmək dövri məntiqdir.
    measured_at_monotonic: float


class SntpClient:
    """Asılılıqsız SNTP (RFC 4330) klienti.

    Xarici kitabxana (`ntplib`) əlavə edilmir: protokol 48 baytlıq bir UDP
    paketidir və əlavə asılılıq tədarük zənciri riskini artırır.
    """

    def __init__(
        self,
        *,
        timeout: float | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            timeout: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.
        """
        self._explicit_timeout = timeout
        self._limits = limits or InfrastructureLimits()

    def _timeout_seconds(self) -> float:
        """Soket taymautu — SORĞU ANINDA oxunur (klient uzun ömürlüdür)."""
        if self._explicit_timeout is not None:
            return self._explicit_timeout
        return self._limits.float_of(SystemLimitKey.NTP_QUERY_TIMEOUT_SECONDS)

    def _max_acceptable_delay(self) -> float:
        """Qəbul edilən maksimum gediş-dönüş vaxtı — ölçmə ANINDA oxunur."""
        return self._limits.float_of(SystemLimitKey.NTP_MAX_ROUND_TRIP_SECONDS)

    def query(self, server: str, *, port: int = NTP_PORT) -> NtpSample:
        """Bir serverdən ölçmə alır. Uğursuzluqda `NtpError`."""
        packet = bytearray(NTP_PACKET_SIZE)
        packet[0] = NTP_CLIENT_HEADER

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self._timeout_seconds())
        try:
            t1 = time.time()
            monotonic_start = time.monotonic()
            # Transmit Timestamp (offset 40) — server bunu geri qaytarır və
            # cavabın bizim sorğumuza aid olduğunu yoxlamağa imkan verir.
            struct.pack_into("!II", packet, 40, *_to_ntp(t1))
            sock.sendto(bytes(packet), (server, port))
            data, _ = sock.recvfrom(256)
            t4 = time.time()
        except (TimeoutError, OSError) as exc:
            raise NtpError(f"{server}: {exc}") from exc
        finally:
            sock.close()

        if len(data) < NTP_PACKET_SIZE:
            raise NtpError(f"{server}: qısa paket ({len(data)} bayt)")

        mode = data[0] & 0b111
        stratum = data[1]
        if mode != NTP_SERVER_MODE:
            raise NtpError(f"{server}: gözlənilməz mode={mode}")
        if not MIN_STRATUM <= stratum <= MAX_STRATUM:
            # Stratum 0 kiss-of-death paketidir (məs. "RATE" — çox tez-tez
            # sorğu). Bunu vaxt kimi qəbul etmək təhlükəlidir.
            raise NtpError(f"{server}: etibarsız stratum={stratum}")

        originate = _from_ntp(*struct.unpack_from("!II", data, 24))
        receive = _from_ntp(*struct.unpack_from("!II", data, 32))
        transmit = _from_ntp(*struct.unpack_from("!II", data, 40))
        if transmit == 0.0:
            raise NtpError(f"{server}: boş transmit timestamp")
        if abs(originate - t1) > ORIGINATE_TOLERANCE_SECONDS:
            # Cavab bizim sorğumuza aid deyil → spoofing və ya köhnə paket.
            raise NtpError(f"{server}: originate timestamp uyğun gəlmir")

        offset = ((receive - t1) + (transmit - t4)) / 2.0
        delay = max(0.0, (t4 - t1) - (transmit - receive))
        if delay > self._max_acceptable_delay():
            raise NtpError(f"{server}: gecikmə çox böyükdür ({delay:.2f} s)")

        return NtpSample(
            server=server,
            offset_seconds=offset,
            delay_seconds=delay,
            stratum=stratum,
            measured_at_monotonic=monotonic_start,
        )


class NtpDriftChecker:
    """`NtpVerifier` portunun implementasiyası + arxa fon yoxlaması.

    Thread-safe: `poll()` arxa fon sapında işləyir, `verified_now()` isə UI
    sapından çağırılır.
    """

    def __init__(
        self,
        *,
        servers: tuple[str, ...] = DEFAULT_SERVERS,
        client: SntpClient | None = None,
        max_drift_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        sample_ttl_seconds: float | None = None,
        limits: InfrastructureLimits | None = None,
        machine_name: str = "",
        on_drift: object = None,
    ) -> None:
        """
        Args:
            max_drift_seconds / poll_interval_seconds / sample_ttl_seconds:
                AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR. `None` = hər
                istifadədə `system_limits`-dən oxunur.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.
        """
        self._servers = servers
        self._limits = limits or InfrastructureLimits()
        self._client = client or SntpClient(limits=self._limits)
        # `_max_drift` MANDALLA (`set_max_drift_seconds`) da təyin edilə bilir:
        # ROOT ekranı həddi dəyişəndə kontroller onu dərhal ötürür və o an
        # dəyər AÇIQ verilmiş sayılır.
        self._max_drift = max_drift_seconds
        self._poll_interval = poll_interval_seconds
        self._sample_ttl = sample_ttl_seconds
        self._machine_name = machine_name or socket.gethostname()
        self._on_drift = on_drift

        self._lock = threading.Lock()
        self._sample: NtpSample | None = None
        #: Hədd aşıldıqda mandallanır; yalnız təzə və hədd daxilində olan
        #: ölçmə açır (yuxarıdakı LATCH izahı).
        self._alarm_drift: float | None = None
        self._consecutive_failures = 0

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # --------------------------- NtpVerifier portu --------------------------- #

    def verified_now(self) -> tuple[datetime, bool]:
        """Düzəlişli indiki an və onun NTP ilə təsdiqlənib-təsdiqlənmədiyi."""
        with self._lock:
            sample = self._fresh_sample_locked()
            alarm = self._alarm_drift
        offset = sample.offset_seconds if sample else 0.0
        moment = datetime.now(UTC) + timedelta(seconds=offset)
        verified = sample is not None and alarm is None
        return moment, verified

    def drift_seconds(self) -> float | None:
        """Ölçülmüş sürüşmə; heç ölçülməyibsə `None`.

        Mandal aktivdirsə ölçmə köhnəlsə belə SON PİS DƏYƏR qaytarılır —
        NTP-ni bloklayaraq blokdan qurtulmaq mümkün olmasın.
        """
        with self._lock:
            if self._alarm_drift is not None:
                return self._alarm_drift
            sample = self._fresh_sample_locked()
            return sample.offset_seconds if sample else None

    def offset_seconds(self) -> float | None:
        """`NtpCorrectedClock` üçün — yalnız TƏZƏ ölçmənin düzəlişi."""
        with self._lock:
            sample = self._fresh_sample_locked()
            return sample.offset_seconds if sample else None

    # ------------------------------- ölçmə ----------------------------------- #

    def poll(self) -> NtpSample | None:
        """Serverləri sırayla yoxlayır; ilk uğurlu cavabı qəbul edir."""
        errors: list[str] = []
        for server in self._servers:
            try:
                sample = self._client.query(server)
            except NtpError as exc:
                errors.append(str(exc))
                continue
            self._accept(sample)
            return sample

        with self._lock:
            self._consecutive_failures += 1
            failures = self._consecutive_failures
        _log.warning(
            "NTP_UNREACHABLE",
            extra={
                "servers": list(self._servers),
                "consecutive_failures": failures,
                "errors": errors,
                "impact": "vaxt yoxlanıla bilmir — kritik əməliyyatlar qeydə alınır",
            },
        )
        return None

    def _accept(self, sample: NtpSample) -> None:
        max_drift = self._max_drift_value()
        exceeded = abs(sample.offset_seconds) > max_drift
        with self._lock:
            self._sample = sample
            self._consecutive_failures = 0
            was_alarmed = self._alarm_drift is not None
            # Mandal YALNIZ burada — təzə, uğurlu ölçmə ilə — açılır.
            self._alarm_drift = sample.offset_seconds if exceeded else None

        if exceeded:
            _security_log.critical(
                "TIME_DRIFT_DETECTED",
                extra={
                    "drift_seconds": round(sample.offset_seconds, 3),
                    "max_allowed": max_drift,
                    "ntp_server": sample.server,
                    "machine_name": self._machine_name,
                    "impact": "vaxt-kritik əməliyyatlar bloklanır",
                },
            )
            self._emit_drift_event(sample)
        elif was_alarmed:
            _security_log.warning(
                "TIME_DRIFT_CLEARED",
                extra={
                    "drift_seconds": round(sample.offset_seconds, 3),
                    "ntp_server": sample.server,
                    "machine_name": self._machine_name,
                },
            )
        else:
            _log.debug(
                "NTP_SAMPLE_OK",
                extra={
                    "drift_seconds": round(sample.offset_seconds, 3),
                    "delay_seconds": round(sample.delay_seconds, 3),
                    "ntp_server": sample.server,
                    "stratum": sample.stratum,
                },
            )

    def _emit_drift_event(self, sample: NtpSample) -> None:
        if self._on_drift is None:
            return
        from src.domain.events import TimeDriftDetectedEvent  # noqa: PLC0415

        event = TimeDriftDetectedEvent(
            drift_seconds=sample.offset_seconds,
            ntp_server=sample.server,
            machine_name=self._machine_name,
        )
        try:
            self._on_drift(event)  # type: ignore[operator]
        except Exception as exc:  # abunəçinin nasazlığı ölçməni pozmamalıdır
            _log.error("NTP_EVENT_PUBLISH_FAILED", extra={"error": str(exc)})

    def _fresh_sample_locked(self) -> NtpSample | None:
        sample = self._sample
        if sample is None:
            return None
        age = time.monotonic() - sample.measured_at_monotonic
        return sample if age <= self._sample_ttl_value() else None

    # ---------------------------- arxa fon sapı ------------------------------ #

    def _max_drift_value(self) -> float:
        """Qüvvədə olan sürüşmə həddi.

        AÇIQ təyin edilibsə (konstruktor arqumenti və ya `set_max_drift_
        seconds`) o qalır — kontroller ROOT dəyərini artıq oxuyub ötürüb.
        Əks halda hədd BURADA, ölçmə anında oxunur.
        """
        if self._max_drift is not None:
            return self._max_drift
        return self._limits.float_of(SystemLimitKey.NTP_MAX_DRIFT_SECONDS)

    def _poll_interval_value(self) -> float:
        if self._poll_interval is not None:
            return self._poll_interval
        return self._limits.float_of(SystemLimitKey.NTP_POLL_INTERVAL_SECONDS)

    def _sample_ttl_value(self) -> float:
        if self._sample_ttl is not None:
            return self._sample_ttl
        return self._limits.float_of(SystemLimitKey.NTP_SAMPLE_TTL_SECONDS)

    def set_max_drift_seconds(self, value: float) -> None:
        """Həddi `system_limits`-dən (NTP_MAX_DRIFT_SECONDS) yeniləyir."""
        with self._lock:
            self._max_drift = value

    @property
    def status(self) -> dict[str, object]:
        """System Health Monitor sətri (bölmə 6)."""
        with self._lock:
            sample = self._sample
            fresh = self._fresh_sample_locked()
            return {
                "ntp_server": sample.server if sample else None,
                "drift_seconds": round(sample.offset_seconds, 3) if sample else None,
                "is_fresh": fresh is not None,
                "is_alarmed": self._alarm_drift is not None,
                "consecutive_failures": self._consecutive_failures,
                "max_drift_seconds": self._max_drift_value(),
            }

    def start(self) -> None:
        """Periodik yoxlamanı başladır (daemon sap — bağlanmanı gecikdirmir)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ntp-drift-checker", daemon=True)
        self._thread.start()
        _log.info("NTP_CHECKER_STARTED", extra={"interval_seconds": self._poll_interval_value()})

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        _log.info("NTP_CHECKER_STOPPED")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll()
            except Exception as exc:  # arxa fon sapı heç vaxt ölməməlidir
                _log.error("NTP_POLL_CRASHED", extra={"error": str(exc)})
            # Aralıq HƏR DÖVRDƏ yenidən oxunur: Root onu dəyişəndə növbəti
            # gözləmə artıq yeni dəyərlə olur, yenidən başlatma tələb olunmur.
            self._stop_event.wait(self._poll_interval_value())


def _to_ntp(unix_seconds: float) -> tuple[int, int]:
    seconds = int(unix_seconds) + NTP_UNIX_DELTA
    fraction = int((unix_seconds - int(unix_seconds)) * FRACTION_DIVISOR)
    return seconds, fraction


def _from_ntp(seconds: int, fraction: int) -> float:
    if seconds == 0 and fraction == 0:
        return 0.0
    return (seconds - NTP_UNIX_DELTA) + fraction / FRACTION_DIVISOR


__all__ = [
    "DEFAULT_SERVERS",
    "FALLBACK_MAX_DRIFT_SECONDS",
    "NTP_UNIX_DELTA",
    "NtpDriftChecker",
    "NtpError",
    "NtpSample",
    "SntpClient",
]
