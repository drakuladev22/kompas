"""Server-lövbərli vaxt — `Clock` portunun manipulyasiyaya davamlı mənbəyi (TIME-1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ NTP KİFAYƏT ETMİRDİ — VƏ NİYƏ NTP YENƏ DƏ SİLİNMİR
──────────────────────────────────────────────────────────────────────────────
`ntp.py` lokal saatın YANLIŞ olub-olmadığını ÖLÇÜR. Lakin NTP UDP/123 tələb
edir və mağaza şəbəkəsində bu port tez-tez bağlı olur — yəni ölçmə HƏMİŞƏ
mümkün deyil. Postgres isə onsuz da MƏCBURİ asılılıqdır: bağlantı yoxdursa
tətbiq zatən işləmir. Deməli baza NTP-dən ETİBARLI vaxt mənbəyidir.

İkisi rəqib deyil, tamamlayıcıdır:

    NTP        → lokal saatın sürüşməsini AŞKARLAYIR (fırıldaqçılıq siqnalı)
    Postgres   → qeydin vaxtını YAZIR (həqiqətin özü)

Ona görə mövcud `TIME_DRIFT_DETECTED` mexanizmi silinmir; bu modul ONA ƏLAVƏ
ikinci — və daha etibarlı — ölçü xətti gətirir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `clock_timestamp()`, `now()` YOX
──────────────────────────────────────────────────────────────────────────────
Postgres-də `now()` = `transaction_timestamp()`, yəni TRANZAKSİYANIN başlama
anı. Sütun defoltları üçün məhz bu doğrudur (bir tranzaksiyada yazılan bütün
sətirlər eyni möhür alır — audit üçün arzuolunan davranış). Lakin BİZ burada
«indi saat neçədir» sualını veririk və uzun tranzaksiyanın içində `now()`
onun BAŞLANĞICINI qaytarardı. `clock_timestamp()` ifadənin icra anıdır.

──────────────────────────────────────────────────────────────────────────────
LÖVBƏR + MONOTONIC = SAAT DƏYİŞSƏ BELƏ DÜZGÜN VAXT
──────────────────────────────────────────────────────────────────────────────
Serverdən alınan vaxt bir DƏFƏLİK ölçüdür; ondan sonrakı axım `time.monotonic()`
ilə ölçülür. Monotonic saat sistem saatının dəyişməsindən TƏSİRLƏNMİR — yəni
istifadəçi Windows saatını iki saat irəli çəksə, bu modulun qaytardığı vaxt
DƏYİŞMİR. Divar saatı ilə ölçmək dövri məntiq olardı: saatın etibarlılığını
saatın özü ilə yoxlamaq (eyni qərar `ntp.py::NtpSample.measured_at_monotonic`).

Gediş-dönüş vaxtının YARISI kompensasiya edilir: sorğu göndərildiyi an ilə
cavabın gəldiyi an arasında server vaxtı da irəliləyib. Bu, SNTP-nin standart
təxminidir və `ntp.py`-dakı `offset` hesabı ilə eyni prinsipdir.

──────────────────────────────────────────────────────────────────────────────
LÖVBƏR YOXDURSA — FALLBACK SAAT, LAKİN AÇIQ ETİRAFLA
──────────────────────────────────────────────────────────────────────────────
Server heç oxunmayıbsa `now()` fallback saata (NTP-düzəlişli və ya OS saatı)
düşür — tətbiq vaxtsız qala bilməz. Lakin `status()` həmin anda `UNTRUSTED`
qaytarır, yəni sistem bilmədiyini GİZLƏTMİR. Sükutla lokal saata qayıtmaq bu
modulun bütün mənasını itirərdi.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.time_integrity import (
    NO_ANCHOR_STATUS,
    TimeIntegrityStatus,
    TimeTrustLevel,
)
from src.infrastructure.config.limits import InfrastructureLimits, fallback_float
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.interfaces.ports import Clock
    from src.infrastructure.persistence.connection_types import TenantDatabase

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Server vaxtını oxuyan sorğu. `clock_timestamp()` — bax modul başlığı.
#: `AT TIME ZONE 'UTC'` YAZILMIR: `clock_timestamp()` onsuz da `timestamptz`-dir
#: və psycopg onu tz-aware `datetime` kimi qaytarır. Əl ilə çevirmək naive
#: dəyər yaradar və `clock.py`-dakı «naive QADAĞANDIR» qaydasını pozardı.
SERVER_TIME_SQL: Final[str] = "SELECT clock_timestamp()"

#: ÜÇÜ DƏ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits` (miqrasiya 062).
#: Bu ədədlər yalnız ROOT portu əlçatmaz olduqda işə düşür.
FALLBACK_SYNC_INTERVAL_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.SERVER_TIME_SYNC_INTERVAL_SECONDS
)
FALLBACK_MAX_OFFLINE_TRUST_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS
)
FALLBACK_MANIPULATION_THRESHOLD_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS
)

#: Lövbər «təzə» sayılan pəncərə = sinxronizasiya intervalının bu qatı.
#: NİYƏ ROOT PARAMETRİ DEYİL: bu, ayrıca siyasət deyil, intervalın ÖZÜNÜN
#: nəticəsidir — bir buraxılmış dövr hələ nasazlıq deyil, ikisi artıq nasazlıqdır.
#: Root-a verilsəydi, interval ilə ziddiyyətli qoşa dəyər yaranardı.
FRESHNESS_INTERVAL_MULTIPLIER: Final[float] = 2.0


@runtime_checkable
class ServerTimeProbe(Protocol):
    """Serverdən bir vaxt oxuyan mənbə.

    Dar interfeys QƏSDƏNDİR: bu modul `Database`-i, hovuzu və ya psycopg-ni
    TANIMIR. Nəticədə testdə real baza olmadan sınana bilir və gələcəkdə
    başqa server mənbəyi (məs. vendor bazası) eyni yerə taxıla bilər.
    """

    def read_server_time(self) -> datetime:
        """Serverin cari vaxtı (tz-aware). Uğursuzluqda istisna atır."""
        ...


@dataclass(frozen=True)
class ServerAnchor:
    """Bir uğurlu server oxuması — sonrakı bütün vaxt bundan törəyir."""

    #: Serverin qaytardığı an (gediş-dönüşün yarısı ilə düzəlişli).
    server_time: datetime
    #: Həmin ana uyğun `time.monotonic()` dəyəri. Divar saatı SAXLANMIR —
    #: bax modul başlığı.
    monotonic_at_read: float
    #: Sorğunun gediş-dönüş müddəti — lövbərin dəqiqlik payı.
    round_trip_seconds: float
    #: Server vaxtı − bu PC-nin Windows saatı (ölçmə anında).
    local_offset_seconds: float

    def extrapolate(self, monotonic_now: float) -> datetime:
        """Lövbərdən bu ana qədər keçən monotonic müddəti əlavə edir."""
        return self.server_time + timedelta(seconds=monotonic_now - self.monotonic_at_read)

    def age_seconds(self, monotonic_now: float) -> float:
        return monotonic_now - self.monotonic_at_read


class PostgresServerTimeProbe:
    """`ServerTimeProbe`-un Postgres implementasiyası.

    `system_scope()` işlədilir, `unit_of_work()` YOX: server saatı tenant-a aid
    deyil və RLS konteksti tələb etmir. Üstəlik vaxt sorğusu tətbiqin ƏN ERKƏN
    mərhələsində — hələ heç bir istifadəçi seçilməmiş ola bilər — lazımdır.
    """

    def __init__(self, database: TenantDatabase) -> None:
        """
        Args:
            database: TENANT bazası. Tip AÇIQ yazılıb və `Database` DEYİL —
                DB-4-ün ayırıcısı burada da qüvvədədir: vendor bazasının
                saatını tenant qeydlərinə lövbər etmək sükutlu qüsur olardı
                (iki fərqli Supabase layihəsi, iki fərqli saat).
                İdxal `TYPE_CHECKING` altındadır, yəni icra vaxtı asılılıq
                yaranmır — modulun dar interfeys prinsipi qorunur.
        """
        self._database = database

    def read_server_time(self) -> datetime:
        # SAAS-2: `tables=()` — "heç bir cədvələ toxunmuram" BƏYANI. Sorğu
        # `SELECT now()`-dur, yəni kirayəçi məlumatı oxunmur; bəyan yenə də
        # AÇIQ yazılır, çünki bəyan ETMƏYƏN çağırış owner hovuzunu ALMIR və
        # bu yol hər sinxronizasiya dövründə işləyir.
        with self._database.system_scope(tables=()) as conn, conn.cursor() as cur:
            cur.execute(SERVER_TIME_SQL)
            row = cur.fetchone()
        if row is None:  # pragma: no cover - Postgres həmişə sətir qaytarır
            raise RuntimeError("Server vaxtı üçün boş cavab")
        moment = next(iter(row.values())) if isinstance(row, dict) else row[0]
        if not isinstance(moment, datetime):  # pragma: no cover - sürücü zəmanəti
            raise TypeError(f"Server vaxtı datetime gözlənilirdi: {type(moment)!r}")
        if moment.tzinfo is None:  # pragma: no cover - `timestamptz` həmişə aware
            raise ValueError("Server naive datetime qaytardı — `timestamptz` gözlənilirdi")
        return moment.astimezone(UTC)


class ServerTimeService:
    """Server lövbərini saxlayan və `Clock` portunu təmin edən servis.

    `Clock` protokolunu MİRAS ALMIR — `now()` imzası ilə strukturca ödəyir
    (`CLAUDE.md` §3: portlar `Protocol`-dur, miras yoxdur). Ayrıca örtük sinif
    yazılmadı: o, yalnız `now()`-u ötürərdi və heç nə qazandırmazdı.

    Thread-safe: `sync()` arxa fon sapında, `now()` UI sapında çağırılır.
    """

    def __init__(
        self,
        *,
        probe: ServerTimeProbe,
        fallback_clock: Clock,
        limits: InfrastructureLimits | None = None,
        sync_interval_seconds: float | None = None,
        max_offline_trust_seconds: float | None = None,
        manipulation_threshold_seconds: float | None = None,
        machine_name: str = "",
        on_manipulation: Callable[[float, float], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        local_now: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Args:
            probe: server vaxtını oxuyan mənbə.
            fallback_clock: lövbər YOXDURSA istifadə olunan saat (NTP-düzəlişli
                və ya OS saatı). Məcburidir — vaxtsız qalmaq variant deyil.
            sync_interval_seconds / max_offline_trust_seconds /
            manipulation_threshold_seconds: AÇIQ üstünlük — verilərsə ROOT
                dəyəri OXUNMUR. `None` = hər istifadədə `system_limits`-dən.
            on_manipulation: `(offset_saniyə, hədd)` ilə çağırılır — lokal saat
                serverdən həddindən çox fərqlənəndə. Bildiriş göndərmək bu
                modulun işi DEYİL (o, domen hadisəsi ilə yayılır).
            monotonic / local_now: testdə vaxtın idarə olunması üçün.
        """
        self._probe = probe
        self._fallback = fallback_clock
        self._limits = limits or InfrastructureLimits()
        self._explicit_interval = sync_interval_seconds
        self._explicit_offline_trust = max_offline_trust_seconds
        self._explicit_manipulation = manipulation_threshold_seconds
        self._machine_name = machine_name
        self._on_manipulation = on_manipulation
        self._monotonic = monotonic
        self._local_now = local_now or (lambda: datetime.now(UTC))

        self._lock = threading.Lock()
        self._anchor: ServerAnchor | None = None
        self._consecutive_failures = 0
        self._manipulation_reported = False

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------ Clock portu ------------------------------ #

    def now(self) -> datetime:
        """Cari UTC vaxtı — lövbər varsa ondan, yoxsa fallback saatdan.

        Windows saatının dəyişməsi bu dəyərə TƏSİR ETMİR (lövbər varkən):
        keçən müddət `time.monotonic()` ilə ölçülür.
        """
        with self._lock:
            anchor = self._anchor
        if anchor is None:
            return self._fallback.now()
        return anchor.extrapolate(self._monotonic())

    # ---------------------------- vəziyyət hesabatı --------------------------- #

    def status(self) -> TimeIntegrityStatus:
        """Vaxtın hazırkı etibarlılıq səviyyəsi (qeydlə birlikdə yazılır)."""
        with self._lock:
            anchor = self._anchor
        if anchor is None:
            return NO_ANCHOR_STATUS

        age = anchor.age_seconds(self._monotonic())
        if age <= self._fresh_window():
            level = TimeTrustLevel.SERVER_VERIFIED
        elif age <= self._max_offline_trust():
            level = TimeTrustLevel.MONOTONIC_ESTIMATE
        else:
            level = TimeTrustLevel.UNTRUSTED

        return TimeIntegrityStatus(
            level=level,
            anchor_age_seconds=age,
            local_clock_offset_seconds=anchor.local_offset_seconds,
            round_trip_seconds=anchor.round_trip_seconds,
        )

    @property
    def health(self) -> dict[str, object]:
        """System Health Monitor sətri (bölmə 6) — `ntp.py::status` ilə eyni naxış."""
        status = self.status()
        with self._lock:
            failures = self._consecutive_failures
        return {
            "trust_level": status.level.value,
            "anchor_age_seconds": (
                round(status.anchor_age_seconds, 1)
                if status.anchor_age_seconds is not None
                else None
            ),
            "local_clock_offset_seconds": (
                round(status.local_clock_offset_seconds, 3)
                if status.local_clock_offset_seconds is not None
                else None
            ),
            "consecutive_failures": failures,
            "sync_interval_seconds": self._sync_interval(),
            "max_offline_trust_seconds": self._max_offline_trust(),
        }

    # -------------------------------- ölçmə ---------------------------------- #

    def sync(self) -> ServerAnchor | None:
        """Serverdən bir vaxt oxuyur və lövbəri yeniləyir.

        Uğursuzluqda MÖVCUD lövbər SAXLANILIR — silmək tətbiqi dərhal
        `UNTRUSTED`-ə salardı, halbuki bir buraxılmış sorğu hələ nasazlıq
        deyil. Köhnəlmə onsuz da `status()`-da yaşla ölçülür.
        """
        started = self._monotonic()
        local_before = self._local_now()
        try:
            server_time = self._probe.read_server_time()
        except Exception as exc:
            with self._lock:
                self._consecutive_failures += 1
                failures = self._consecutive_failures
            _log.warning(
                "SERVER_TIME_SYNC_FAILED",
                extra={
                    "error": str(exc),
                    "consecutive_failures": failures,
                    "impact": "vaxt monotonic lövbərlə uzadılır",
                },
            )
            return None

        finished = self._monotonic()
        round_trip = max(0.0, finished - started)
        half = round_trip / 2.0
        # Cavab gələnə qədər server vaxtı da irəliləyib — yarısı kompensasiya
        # edilir (SNTP standart təxmini, `ntp.py` ilə eyni prinsip).
        anchor_moment = server_time + timedelta(seconds=half)
        local_at_read = local_before + timedelta(seconds=half)
        local_offset = (anchor_moment - local_at_read).total_seconds()

        anchor = ServerAnchor(
            server_time=anchor_moment,
            monotonic_at_read=started + half,
            round_trip_seconds=round_trip,
            local_offset_seconds=local_offset,
        )
        with self._lock:
            self._anchor = anchor
            self._consecutive_failures = 0
        _log.debug(
            "SERVER_TIME_SYNCED",
            extra={
                "round_trip_seconds": round(round_trip, 3),
                "local_offset_seconds": round(local_offset, 3),
            },
        )
        self._check_manipulation(local_offset)
        return anchor

    def _check_manipulation(self, local_offset: float) -> None:
        """Lokal saat serverdən çox fərqlənirsə — audit + bildiriş (Faza 4).

        Əməliyyat BLOKLANMIR: vaxt onsuz da serverdən gəlir, yəni manipulyasiya
        qeydə təsir edə bilmir. Bloklamaq mağazanı dayandırardı və heç nə
        qazandırmazdı. Lakin hadisə fırıldaqçılıq siqnalıdır və İZSİZ qalmamalıdır.
        """
        threshold = self._manipulation_threshold()
        exceeded = abs(local_offset) > threshold
        with self._lock:
            already = self._manipulation_reported
            self._manipulation_reported = exceeded

        if not exceeded:
            if already:
                _security_log.warning(
                    "LOCAL_CLOCK_MANIPULATION_CLEARED",
                    extra={
                        "local_offset_seconds": round(local_offset, 3),
                        "machine_name": self._machine_name,
                    },
                )
            return

        _security_log.critical(
            "LOCAL_CLOCK_MANIPULATION_DETECTED",
            extra={
                "local_offset_seconds": round(local_offset, 3),
                "threshold_seconds": threshold,
                "machine_name": self._machine_name,
                "impact": "qeydlər server vaxtı ilə yazılır — dəyişiklik təsir etmir",
            },
        )
        # Təkrar bildiriş göndərilmir: saat düzəldilənə qədər hər sinxronizasiya
        # eyni xəbərdarlığı yaradardı və HR_Admin-in gələn qutusunu doldurardı.
        if already or self._on_manipulation is None:
            return
        try:
            self._on_manipulation(local_offset, threshold)
        except Exception as exc:  # abunəçinin nasazlığı ölçməni pozmamalıdır
            _log.error("SERVER_TIME_EVENT_PUBLISH_FAILED", extra={"error": str(exc)})

    # ---------------------------- ROOT parametrləri --------------------------- #

    def _sync_interval(self) -> float:
        if self._explicit_interval is not None:
            return self._explicit_interval
        return self._limits.float_of(SystemLimitKey.SERVER_TIME_SYNC_INTERVAL_SECONDS)

    def _fresh_window(self) -> float:
        return self._sync_interval() * FRESHNESS_INTERVAL_MULTIPLIER

    def _max_offline_trust(self) -> float:
        if self._explicit_offline_trust is not None:
            return self._explicit_offline_trust
        return self._limits.float_of(SystemLimitKey.SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS)

    def _manipulation_threshold(self) -> float:
        if self._explicit_manipulation is not None:
            return self._explicit_manipulation
        return self._limits.float_of(SystemLimitKey.LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS)

    # ------------------------------ arxa fon sapı ----------------------------- #

    def start(self) -> None:
        """İlk sinxronizasiyanı edir və periodik yeniləməni başladır.

        İlk sorğu SAP AÇILMADAN ƏVVƏL, sinxron edilir: tətbiq işə düşən kimi
        lövbər hazır olmalıdır, əks halda ilk ekranlar `UNTRUSTED` vaxtla
        işləyərdi.
        """
        self.sync()
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="server-time-sync", daemon=True)
        self._thread.start()
        _log.info("SERVER_TIME_SERVICE_STARTED", extra={"interval_seconds": self._sync_interval()})

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        _log.info("SERVER_TIME_SERVICE_STOPPED")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            # Aralıq HƏR DÖVRDƏ yenidən oxunur: Root onu dəyişəndə növbəti
            # gözləmə yeni dəyərlə olur (`ntp.py::_run` ilə eyni qərar).
            self._stop_event.wait(self._sync_interval())
            if self._stop_event.is_set():
                return
            try:
                self.sync()
            except Exception as exc:  # arxa fon sapı heç vaxt ölməməlidir
                _log.error("SERVER_TIME_SYNC_CRASHED", extra={"error": str(exc)})


__all__ = [
    "FALLBACK_MANIPULATION_THRESHOLD_SECONDS",
    "FALLBACK_MAX_OFFLINE_TRUST_SECONDS",
    "FALLBACK_SYNC_INTERVAL_SECONDS",
    "FRESHNESS_INTERVAL_MULTIPLIER",
    "SERVER_TIME_SQL",
    "PostgresServerTimeProbe",
    "ServerAnchor",
    "ServerTimeProbe",
    "ServerTimeService",
]
