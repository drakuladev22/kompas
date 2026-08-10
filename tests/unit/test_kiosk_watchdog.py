"""Kiosk Mode Watchdog — Faza 4/bölmə 5.

REAL PROSES YARADILMIR və REAL SANİYƏ GÖZLƏNİLMİR: `runner`, `sleeper` və
`monotonic` əvəzlənir. Beləliklə "sonsuz yenidən başlatma dövrü" kimi ən
təhlükəli ssenari test mühitini bloklamadan yoxlanılır.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from src.infrastructure.kiosk.watchdog import (
    CLEAN_EXIT_CODE,
    DEFAULT_RESTART_BACKOFF_SECONDS,
    KioskWatchdog,
)


class _Runner:
    """Əvvəlcədən verilmiş çıxış kodlarını sıra ilə qaytarır."""

    def __init__(self, exit_codes: list[int]) -> None:
        self._codes = list(exit_codes)
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> int:
        self.calls.append(list(command))
        # Siyahı bitəndə sonuncu kod təkrarlanır — "həmişə çökür" ssenarisi.
        return self._codes.pop(0) if self._codes else 1


class _Sleeper:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


class _Clock:
    """Yalnız `sleep` çağırıldıqda irəliləyən saxta monotonik saat."""

    def __init__(self, sleeper: _Sleeper) -> None:
        self._sleeper = sleeper

    def __call__(self) -> float:
        return float(sum(self._sleeper.waits))


def _watchdog(
    exit_codes: list[int], *, max_restarts: int = 5
) -> tuple[KioskWatchdog, _Runner, _Sleeper]:
    runner = _Runner(exit_codes)
    sleeper = _Sleeper()
    watchdog = KioskWatchdog(
        command=["python", "-m", "src.main", "--gui", "--kiosk"],
        runner=runner,
        sleeper=sleeper,
        monotonic=_Clock(sleeper),
        max_restarts=max_restarts,
    )
    return watchdog, runner, sleeper


# --------------------------------------------------------------------------- #
# Normal bağlanma
# --------------------------------------------------------------------------- #


def test_clean_exit_is_not_restarted() -> None:
    """Əks halda tətbiqi bağlamaq MÜMKÜNSÜZ olardı."""
    watchdog, runner, sleeper = _watchdog([CLEAN_EXIT_CODE])

    outcome = watchdog.run()

    assert outcome.stopped_because == "clean_exit"
    assert outcome.restart_count == 0
    assert len(runner.calls) == 1
    assert not sleeper.waits


def test_crash_then_clean_exit_restarts_once() -> None:
    watchdog, runner, _ = _watchdog([1, CLEAN_EXIT_CODE])

    outcome = watchdog.run()

    assert outcome.restart_count == 1
    assert outcome.stopped_because == "clean_exit"
    assert len(runner.calls) == 2


# --------------------------------------------------------------------------- #
# SONSUZ DÖVR QORUYUCUSU
# --------------------------------------------------------------------------- #


def test_restart_storm_stops_the_watchdog() -> None:
    """Başlanğıcda çökən tətbiq saniyədə onlarla proses yaratmamalıdır."""
    watchdog, runner, _ = _watchdog([1] * 20, max_restarts=5)

    outcome = watchdog.run()

    assert outcome.hit_restart_limit
    assert outcome.stopped_because == "restart_storm"
    # 5 yenidən başlatma + limiti aşan 6-cı cəhd = 6 icra.
    assert len(runner.calls) == 6


def test_backoff_grows_between_restarts() -> None:
    """Dərhal yenidən başlatmaq ən təhlükəli davranışdır."""
    watchdog, _, sleeper = _watchdog([1] * 20, max_restarts=5)

    watchdog.run()

    assert sleeper.waits == list(DEFAULT_RESTART_BACKOFF_SECONDS)[: len(sleeper.waits)]
    assert sleeper.waits == sorted(sleeper.waits)


def test_backoff_repeats_the_last_value_instead_of_growing_forever() -> None:
    watchdog, _, sleeper = _watchdog([1] * 30, max_restarts=8)

    watchdog.run()

    longest = DEFAULT_RESTART_BACKOFF_SECONDS[-1]
    assert all(wait <= longest for wait in sleeper.waits)
    assert sleeper.waits[-1] == longest


def test_restarts_outside_the_window_do_not_count_toward_the_limit() -> None:
    """10 dəqiqədən köhnə hadisə yeni fırtına sayılmamalıdır.

    Saxta saat yalnız `sleep` ilə irəlilədiyi üçün pəncərə burada təbii
    şəkildə aşılmır; ona görə saat AYRICA idarə olunur.
    """
    runner = _Runner([1] * 30)
    sleeper = _Sleeper()
    ticks = iter(range(0, 30_000, 1_000))  # hər çökmə 1000 saniyə aralı

    watchdog = KioskWatchdog(
        command=["python"],
        runner=runner,
        sleeper=sleeper,
        monotonic=lambda: float(next(ticks)),
        max_restarts=5,
    )

    outcome = watchdog.run(max_cycles=10)

    assert not outcome.hit_restart_limit
    assert outcome.stopped_because == "stopped"


# --------------------------------------------------------------------------- #
# Hesabatlılıq
# --------------------------------------------------------------------------- #


class _CrashReporter:
    def __init__(self, *, fail: bool = False) -> None:
        self.reported: list[BaseException] = []
        self._fail = fail

    def report_exception(self, exc: BaseException) -> bool:
        if self._fail:
            raise RuntimeError("şəbəkə yoxdur")
        self.reported.append(exc)
        return True


def test_crash_is_reported_to_the_dashboard() -> None:
    reporter = _CrashReporter()
    watchdog = KioskWatchdog(
        command=["python"],
        runner=_Runner([1, CLEAN_EXIT_CODE]),
        sleeper=_Sleeper(),
        monotonic=lambda: 0.0,
        crash_reporter=reporter,  # type: ignore[arg-type]
    )

    watchdog.run()

    assert len(reporter.reported) == 1
    assert "1 kodu ilə dayandı" in str(reporter.reported[0])


def test_offline_crash_reporting_does_not_stop_the_restart() -> None:
    """Mağaza PC-si offline ola bilər — məhz o vaxt watchdog ən çox lazımdır."""
    watchdog = KioskWatchdog(
        command=["python"],
        runner=_Runner([1, CLEAN_EXIT_CODE]),
        sleeper=_Sleeper(),
        monotonic=lambda: 0.0,
        crash_reporter=_CrashReporter(fail=True),  # type: ignore[arg-type]
    )

    outcome = watchdog.run()

    assert outcome.restart_count == 1
    assert outcome.stopped_because == "clean_exit"


def test_no_reporter_is_not_an_error() -> None:
    watchdog, _, _ = _watchdog([1, CLEAN_EXIT_CODE])
    assert watchdog.run().restart_count == 1


# --------------------------------------------------------------------------- #
# Əmr və idarəolunan dayanma
# --------------------------------------------------------------------------- #


def test_default_command_launches_kiosk_mode() -> None:
    watchdog = KioskWatchdog()
    assert "--kiosk" in watchdog.command
    assert "--gui" in watchdog.command


def test_stop_ends_the_loop_without_restarting() -> None:
    runner = _Runner([1] * 5)
    watchdog = KioskWatchdog(
        command=["python"], runner=runner, sleeper=_Sleeper(), monotonic=lambda: 0.0
    )
    watchdog.stop()

    outcome = watchdog.run()

    assert outcome.stopped_because == "stopped"
    assert not runner.calls


@pytest.mark.parametrize("cycles", [1, 2, 3])
def test_max_cycles_bounds_the_loop(cycles: int) -> None:
    watchdog, runner, _ = _watchdog([1] * 10, max_restarts=99)
    watchdog.run(max_cycles=cycles)
    assert len(runner.calls) == cycles
