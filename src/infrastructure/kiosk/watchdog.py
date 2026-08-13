"""Kiosk Mode Watchdog — avtomatik yenidən başlatma (spesifikasiya bölmə 5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
Bölmə 5: "Mağaza PC-lərində işləyən Kiosk Mode instansiyası üçün yüngül bir
watchdog prosesi tətbiq gözlənilmədən çökərsə (crash) onu avtomatik yenidən
başladır (son vəziyyət/session-a təsir etmədən) və hadisəni lokal `error.log`-a
+ (bağlantı varsa) crash-hesabatlılığına yazır. Bu, mağaza işçisinin «proqram
açılmır» deyə panikə düşüb dərhal sizə zəng etməsinin qarşısını alan sadə,
effektiv tədbirdir."

──────────────────────────────────────────────────────────────────────────────
SONSUZ DÖVR QORUYUCUSU (KRİTİK)
──────────────────────────────────────────────────────────────────────────────
Ən təhlükəli watchdog — dərhal yenidən başladan watchdog-dur. Tətbiq
başlanğıcda çökürsə (məs. konfiqurasiya səhvi), yenidən başlatma dövrü
saniyədə onlarla proses yaradar, `error.log`-u qıfıllayar və mağaza PC-sini
yararsız edərdi.

İki qoruyucu var:

    * **Artan gecikmə** (`2 → 4 → 8 → 16 → 30` saniyə) — hər yenidən başlatma
      arasında;
    * **Pəncərə limiti** — 10 dəqiqədə maksimum 5 yenidən başlatma. Aşılarsa
      watchdog DAYANIR və ekrana səbəbi yazır. Sonsuz dövr əvəzinə açıq
      dayanma daha yaxşıdır: işçi "proqram açılmır" görəcək, lakin PC işlək
      qalacaq və uzaqdan müdaxilə mümkün olacaq.

──────────────────────────────────────────────────────────────────────────────
"SESSION-A TƏSİR ETMƏDƏN" NƏ DEMƏKDİR
──────────────────────────────────────────────────────────────────────────────
Watchdog tətbiqin DAXİLİ vəziyyətinə toxunmur — o, yalnız prosesi yenidən
başladır. Sessiyanın bərpası tətbiqin öz işidir (offline bufer + PIN
yenidən daxil edilməsi). Ona görə burada heç bir "state" ötürülmür: bu,
sadəlik deyil, sərhəd qərarıdır — watchdog nə qədər az bilirsə, o qədər az
şey poza bilər.

──────────────────────────────────────────────────────────────────────────────
NORMAL BAĞLANMA YENİDƏN BAŞLADILMIR
──────────────────────────────────────────────────────────────────────────────
Çıxış kodu `0` — istifadəçi/admin tətbiqi qəsdən bağlayıb. Onu yenidən
başlatmaq tətbiqi bağlamağı MÜMKÜNSÜZ edərdi.
"""

from __future__ import annotations

# Nəzarətçinin işi məhz prosesi idarə etməkdir; əmr siyahı kimi ötürülür,
# `shell=False` saxlanılır (bax `_spawn`).
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from src.domain.policies import SystemLimitKey
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_int,
    fallback_int_tuple,
)
from src.shared.logger import LogChannel, get_logger
from src.shared.runtime import deployment_root, relaunch_command

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.infrastructure.notifications.crash_reporter import CrashReporter

_error_log = get_logger(__name__, channel=LogChannel.ERROR)
_app_log = get_logger(__name__)

#: ÜÇÜ DƏ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`KIOSK_RESTART_BACKOFF_SECONDS`, `KIOSK_RESTART_WINDOW_MINUTES`,
#: `KIOSK_MAX_RESTARTS_PER_WINDOW`; seed: migrations/032).
#:
#: NİYƏ ROOT PARAMETRİDİR: fırtına həddi mağazanın avadanlığından asılıdır —
#: zəif kioskda soyuq açılış uzun çəkir və 10 dəqiqədə 5 restart normal
#: bərpa ola bilər, sabit quraşdırmada isə eyni say real nasazlıq əlamətidir.
#: Hədd struktur zəmanət DEYİL: watchdog dayananda tətbiq bağlanmır, sadəcə
#: avtomatik yenidən başlatma dayanır və hadisə `error.log`-a düşür.
#:
#: Artan gecikmə cədvəli (saniyə) — sonuncu dəyər təkrarlanır. Vergüllü siyahı
#: naxışı `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` ilə eynidir (sıra mənalıdır).
FALLBACK_RESTART_BACKOFF_SECONDS: Final[tuple[int, ...]] = fallback_int_tuple(
    SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS
)
#: Pəncərə limiti: bu qədər dəqiqədə...
FALLBACK_RESTART_WINDOW_MINUTES: Final[int] = fallback_int(
    SystemLimitKey.KIOSK_RESTART_WINDOW_MINUTES
)
#: ...bu qədər yenidən başlatmadan çox olarsa watchdog dayanır.
FALLBACK_MAX_RESTARTS_PER_WINDOW: Final[int] = fallback_int(
    SystemLimitKey.KIOSK_MAX_RESTARTS_PER_WINDOW
)
#: `0` — qəsdən bağlanma; yenidən başlatma tələb OLUNMUR.
CLEAN_EXIT_CODE: Final[int] = 0


class KioskProcessCrashError(RuntimeError):
    """Kiosk prosesinin qeyri-sıfır kodla dayanması.

    `CrashReporter` istisna obyekti üzərində işlədiyi üçün lazımdır — bax
    `KioskWatchdog._report_crash` izahı.
    """


@dataclass(frozen=True)
class RestartRecord:
    """Bir yenidən başlatma hadisəsi — hesabat və test üçün."""

    attempt: int
    exit_code: int
    waited_seconds: int
    at_monotonic: float


@dataclass
class WatchdogOutcome:
    """Nəzarətçinin yekun vəziyyəti."""

    restarts: list[RestartRecord] = field(default_factory=list)
    #: Dayanma səbəbi: `clean_exit`, `restart_storm`, `stopped`.
    stopped_because: str = "clean_exit"
    last_exit_code: int = 0

    @property
    def restart_count(self) -> int:
        return len(self.restarts)

    @property
    def hit_restart_limit(self) -> bool:
        return self.stopped_because == "restart_storm"


class KioskWatchdog:
    """Kiosk prosesini izləyir və çökmə halında yenidən başladır.

    Testdə `runner` və `sleeper` əvəzlənir — beləliklə real proses
    yaratmadan və real saniyələr gözləmədən bütün qərar məntiqi yoxlanılır.
    """

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        crash_reporter: CrashReporter | None = None,
        runner: Callable[[Sequence[str]], int] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        backoff_seconds: Sequence[int] | None = None,
        max_restarts: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            backoff_seconds / max_restarts: AÇIQ üstünlük — verilərsə ROOT
                dəyəri OXUNMUR (test və xüsusi quraşdırma bunu işlədir).
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.
        """
        self._command = list(command) if command else self._default_command()
        self._crash_reporter = crash_reporter
        self._runner = runner or self._spawn
        self._sleep = sleeper
        self._monotonic = monotonic
        self._explicit_backoff = tuple(backoff_seconds) if backoff_seconds else None
        self._explicit_max_restarts = max_restarts
        self._limits = limits or InfrastructureLimits()
        self._stopped = False

    def _backoff_schedule(self) -> tuple[int, ...]:
        """Gözləmə cədvəli — HƏR ÇÖKMƏDƏ oxunur.

        Nəzarətçi tətbiqdən UZUN yaşayır (o, tətbiqi yenidən başladan
        prosesdir), ona görə konstruktorda dondurulmuş cədvəl Root-un
        dəyişikliyini heç vaxt görməzdi.
        """
        if self._explicit_backoff is not None:
            return self._explicit_backoff
        return self._limits.int_tuple_of(SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS)

    def _max_restarts_value(self) -> int:
        if self._explicit_max_restarts is not None:
            return self._explicit_max_restarts
        return self._limits.int_of(SystemLimitKey.KIOSK_MAX_RESTARTS_PER_WINDOW)

    def _window_minutes(self) -> int:
        return self._limits.int_of(SystemLimitKey.KIOSK_RESTART_WINDOW_MINUTES)

    @staticmethod
    def _default_command() -> list[str]:
        """Kiosk rejimini işə salan əmr.

        Prefiks `relaunch_command()`-dən gəlir, çünki paketlənmiş `.exe`
        Python interpretatoru DEYİL: ona `-m src.main` ötürülsəydi, `argparse`
        onu tanımayıb 2 kodu ilə çıxardı və nəzarətçi hər cəhdi "çökmə" sayıb
        dərhal restart fırtınası limitinə dəyərdi (bax `shared/runtime.py`).
        """
        return [*relaunch_command(), "--gui", "--kiosk"]

    @property
    def command(self) -> tuple[str, ...]:
        return tuple(self._command)

    def stop(self) -> None:
        """Növbəti dövrdə dayanmağı tələb edir (idarəolunan bağlanma)."""
        self._stopped = True

    # ------------------------------- əsas dövr ------------------------------- #

    def run(self, *, max_cycles: int | None = None) -> WatchdogOutcome:
        """Kiosk prosesini işə salır və lazım olduqda yenidən başladır.

        Args:
            max_cycles: Testdə sonsuz dövrün qarşısını alır. `None` —
                real istifadə (yalnız təmiz çıxış və ya limit dayandırır).
        """
        outcome = WatchdogOutcome()
        recent: deque[float] = deque()
        cycles = 0

        while not self._stopped:
            cycles += 1
            exit_code = self._runner(self._command)
            outcome.last_exit_code = exit_code

            if exit_code == CLEAN_EXIT_CODE:
                outcome.stopped_because = "clean_exit"
                _app_log.info("KIOSK_CLEAN_EXIT", extra={"cycles": cycles})
                return outcome

            now = self._monotonic()
            self._prune(recent, now, self._window_minutes())
            recent.append(now)

            if len(recent) > self._max_restarts_value():
                outcome.stopped_because = "restart_storm"
                _error_log.error(
                    "KIOSK_RESTART_STORM",
                    extra={
                        "restarts": len(recent),
                        "window_minutes": self._window_minutes(),
                        "exit_code": exit_code,
                    },
                )
                self._report_crash(exit_code, storm=True)
                return outcome

            wait = self._backoff_for(outcome.restart_count)
            outcome.restarts.append(
                RestartRecord(
                    attempt=outcome.restart_count + 1,
                    exit_code=exit_code,
                    waited_seconds=wait,
                    at_monotonic=now,
                )
            )
            _error_log.warning(
                "KIOSK_CRASH_RESTARTING",
                extra={
                    "exit_code": exit_code,
                    "attempt": outcome.restart_count,
                    "wait_seconds": wait,
                },
            )
            self._report_crash(exit_code, storm=False)

            if max_cycles is not None and cycles >= max_cycles:
                outcome.stopped_because = "stopped"
                return outcome

            self._sleep(wait)

        outcome.stopped_because = "stopped"
        return outcome

    # ------------------------------- köməkçilər ------------------------------ #

    def _backoff_for(self, previous_restarts: int) -> int:
        """Artan gecikmə — cədvəlin sonuncu dəyəri təkrarlanır."""
        schedule = self._backoff_schedule()
        index = min(previous_restarts, len(schedule) - 1)
        return schedule[index]

    @staticmethod
    def _prune(recent: deque[float], now: float, window_minutes: int) -> None:
        """Pəncərədən çıxmış hadisələri atır.

        Pəncərə uzunluğu ARQUMENT kimi gəlir (metod ROOT-a özü müraciət etmir),
        çünki bu, saf hesablamadır: eyni giriş həmişə eyni nəticə verməlidir və
        testdə konfiqurasiya olmadan yoxlanıla bilməlidir.
        """
        cutoff = now - window_minutes * 60
        while recent and recent[0] < cutoff:
            recent.popleft()

    def _report_crash(self, exit_code: int, *, storm: bool) -> None:
        """Çökməni crash-hesabatlılığına ötürür — bağlantı yoxdursa səssiz.

        Bildirişin uğursuzluğu yenidən başlatmanı DAYANDIRMAMALIDIR: mağaza
        PC-si offline ola bilər və məhz o vaxt watchdog ən çox lazımdır.
        """
        if self._crash_reporter is None:
            return

        # Süni istisna qurulur, çünki `CrashReporter` istisna obyekti gözləyir:
        # watchdog çökən prosesin traceback-inə çıxa BİLMİR (o, ayrı prosesdə
        # baş verib və öz `error.log`-una yazılıb). Buradakı hesabat "kiosk
        # çökdü" faktını mərkəzə çatdırır, səbəbini yox.
        detail = " — yenidən başlatma limiti aşıldı" if storm else ""
        try:
            raise KioskProcessCrashError(f"Kiosk prosesi {exit_code} kodu ilə dayandı{detail}")
        except KioskProcessCrashError as crash:
            try:
                self._crash_reporter.report_exception(crash)
            except Exception:
                _error_log.exception("KIOSK_CRASH_REPORT_FAILED")

    @staticmethod
    def _spawn(command: Sequence[str]) -> int:
        """Prosesi işə salır və çıxış kodunu gözləyir.

        `shell=False` (defolt) QƏSDƏN saxlanılır: əmr siyahı kimi ötürülür və
        heç bir hissəsi qabıq tərəfindən şərh edilmir.

        İş qovluğu `deployment_root()`-dur: paketlənmiş rejimdə
        `Path(__file__).parents[3]` arxivin müvəqqəti qovluğunu göstərərdi və
        alt-proses tətbiq bağlananda silinən qovluqda işləyərdi.
        """
        cwd = deployment_root()
        completed = subprocess.run(command, check=False, cwd=cwd)  # noqa: S603
        return completed.returncode


__all__ = [
    "CLEAN_EXIT_CODE",
    "FALLBACK_MAX_RESTARTS_PER_WINDOW",
    "FALLBACK_RESTART_BACKOFF_SECONDS",
    "FALLBACK_RESTART_WINDOW_MINUTES",
    "KioskProcessCrashError",
    "KioskWatchdog",
    "RestartRecord",
    "WatchdogOutcome",
]
