"""Planlanmış iş nüvəsi: icarə, gecikmiş icra, qismən uğur, ağır/yüngül ayrımı.

──────────────────────────────────────────────────────────────────────────────
BU FAYLIN ƏSAS TESTİ YARIŞ VƏZİYYƏTİDİR
──────────────────────────────────────────────────────────────────────────────
Sistem 21 mağazada, hər mağazada bir neçə terminalda işləyir və planlayıcı
HƏR terminalda var. Ona görə birinci sual "iki instansiya eyni işi eyni anda
götürəndə nə olur?"dur. Test #16 açıq növbə bazarındakı naxışı təkrarlayır
(`test_open_shift_market.test_two_parallel_claims_produce_exactly_one_winner`):
`threading.Barrier(2)` hər iki iş axınını OXU ilə YAZI arasında saxlayır, yəni
hər ikisi "qeyd yoxdur" görür — məhz tətbiq qatındakı "əvvəlcə oxu, sonra yaz"
naxışının uduzduğu ssenari.

SAHTƏ BU FAYLDA TƏYİN OLUNUB (paylaşılan `tests/fixtures/fakes.py`
dəyişdirilmir). `InMemoryScheduledJobRuns` DB semantikasını modelləşdirir:

  * `atomic=True`  — `INSERT ... ON CONFLICT DO NOTHING` + şərti `UPDATE`
    (qərar kilid altında YENİDƏN oxunur, yəni real DB kimi);
  * `atomic=False` — MUTASİYA REJİMİ: qərar barrier-dən ƏVVƏLKİ köhnə oxuya
    görə verilir (naiv tətbiq qatı yoxlaması).

`atomic=False` rejimi ayrıca test ilə yoxlanılır: qoruma söndürüləndə İKİ icra
baş verməlidir. Əks halda yarış testi "heç nə qorumayan yaşıl test" olardı —
onu sübut etmək üçün mutasiyanın ÖZÜ də testdədir.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

import pytest

from src.application.use_cases.job_runner import (
    DuplicateJobError,
    JobCadence,
    JobExecutionContext,
    JobOutcomeState,
    JobRunner,
    JobWeight,
    ScheduledJob,
    ScheduledJobRegistry,
    SchedulerError,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import TenantId
from src.domain.value_objects.job_runs import (
    InvalidJobRunError,
    JobRunStatus,
    ScheduledJobRun,
    normalize_job_key,
    trim_error_text,
)
from src.domain.value_objects.scheduling import DEFAULT_TIMEZONE, NaiveDatetimeError
from tests.fixtures.fakes import FakeClock, FakeSystemLimits, RecordingAudit

pytestmark = pytest.mark.unit

BAKU: Final = ZoneInfo(DEFAULT_TIMEZONE)
TENANT: Final = TenantId(uuid.uuid4())
#: Barrier gözləməsi TESTİN ASILMASINI bloklayır: qüsurlu kodda ikinci axın
#: heç vaxt gəlməyə bilər və test sonsuz gözləyərdi.
BARRIER_TIMEOUT: Final = 5.0

NIGHTLY_HOUR: Final = int(DEFAULT_LIMITS[SystemLimitKey.SCHEDULER_NIGHTLY_HOUR])
LEASE_MINUTES: Final = int(DEFAULT_LIMITS[SystemLimitKey.SCHEDULER_LEASE_MINUTES])
MAX_ATTEMPTS: Final = int(DEFAULT_LIMITS[SystemLimitKey.SCHEDULER_MAX_ATTEMPTS])


def local(
    year: int, month: int, day: int, hour: int, minute: int = 0, *, second: int = 0
) -> datetime:
    """Mağazanın YERLİ anı — slot sərhədləri yerli saatla təyin olunur."""
    return datetime(year, month, day, hour, minute, second, tzinfo=BAKU)


#: Gecə slotu (yerli 03:00) və həmin slota aid səhər anı.
NIGHT_SLOT: Final = local(2026, 8, 13, NIGHTLY_HOUR)
MORNING: Final = local(2026, 8, 13, 9, 12)


# --------------------------------------------------------------------------- #
# Yerli sahtə — DB-nin ATOMİK icarə semantikası
# --------------------------------------------------------------------------- #


class InMemoryScheduledJobRuns:
    """`ScheduledJobRepository`-nin yaddaş versiyası.

    ATOMİKLİK QƏSDƏN MODELLƏŞDİRİLİB (bax modul başlığı). Qərar qaydası
    domenin `ScheduledJobRun.is_reclaimable` metodundan gəlir — həmin metod
    SQL şərtinin sənədləşdirilmiş güzgüsüdür, yəni sahtə ilə repo eyni
    qaydanı işlədir.
    """

    def __init__(
        self, *, read_barrier: threading.Barrier | None = None, atomic: bool = True
    ) -> None:
        self.rows: dict[tuple[str, str, str], ScheduledJobRun] = {}
        self.acquire_calls: list[str] = []
        self.atomic = atomic
        self._barrier = read_barrier
        self._lock = threading.Lock()

    # --- açar --- #

    @staticmethod
    def _key(tenant_id: TenantId, job_key: str, scheduled_for: datetime) -> tuple[str, str, str]:
        # `scheduled_for` ANI ilə açarlanır (UTC-yə gətirilir): eyni slotu
        # fərqli zona ilə yazan iki instansiya EYNİ sətrə düşməlidir.
        return (str(tenant_id), job_key, scheduled_for.astimezone(UTC).isoformat())

    # --- icarə --- #

    def acquire(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        now: datetime,
        leased_until: datetime,
        max_attempts: int,
    ) -> bool:
        key = self._key(tenant_id, job_key, scheduled_for)
        self.acquire_calls.append(job_key)
        stale = self.rows.get(key)  # "əvvəlcə oxu"
        if self._barrier is not None:
            self._barrier.wait(timeout=BARRIER_TIMEOUT)
        if not self.atomic:
            # MUTASİYA REJİMİ: qərar KÖHNƏ oxuya görə verilir.
            return self._write(
                key,
                stale,
                tenant_id=tenant_id,
                job_key=job_key,
                scheduled_for=scheduled_for,
                instance_id=instance_id,
                now=now,
                leased_until=leased_until,
                max_attempts=max_attempts,
            )
        with self._lock:
            # DB qatı: `ON CONFLICT` / şərti `UPDATE` vəziyyəti YENİDƏN oxuyur.
            return self._write(
                key,
                self.rows.get(key),
                tenant_id=tenant_id,
                job_key=job_key,
                scheduled_for=scheduled_for,
                instance_id=instance_id,
                now=now,
                leased_until=leased_until,
                max_attempts=max_attempts,
            )

    def _write(
        self,
        key: tuple[str, str, str],
        existing: ScheduledJobRun | None,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        now: datetime,
        leased_until: datetime,
        max_attempts: int,
    ) -> bool:
        if existing is None:
            self.rows[key] = ScheduledJobRun(
                tenant_id=tenant_id,
                job_key=job_key,
                scheduled_for=scheduled_for,
                status=JobRunStatus.RUNNING,
                leased_by=instance_id,
                leased_until=leased_until,
                started_at=now,
                attempts=1,
            )
            return True
        if not existing.is_reclaimable(now, max_attempts=max_attempts):
            return False
        self.rows[key] = replace(
            existing,
            status=JobRunStatus.RUNNING,
            leased_by=instance_id,
            leased_until=leased_until,
            started_at=now,
            finished_at=None,
            attempts=existing.attempts + 1,
        )
        return True

    # --- nəticə --- #

    def mark_succeeded(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        result_detail: str | None = None,
    ) -> bool:
        return self._finish(
            tenant_id=tenant_id,
            job_key=job_key,
            scheduled_for=scheduled_for,
            instance_id=instance_id,
            finished_at=finished_at,
            status=JobRunStatus.SUCCEEDED,
            last_error=None,
            result_detail=result_detail,
        )

    def mark_failed(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        error: str,
    ) -> bool:
        return self._finish(
            tenant_id=tenant_id,
            job_key=job_key,
            scheduled_for=scheduled_for,
            instance_id=instance_id,
            finished_at=finished_at,
            status=JobRunStatus.FAILED,
            last_error=trim_error_text(error),
            result_detail=None,
        )

    def _finish(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        status: JobRunStatus,
        last_error: str | None,
        result_detail: str | None,
    ) -> bool:
        key = self._key(tenant_id, job_key, scheduled_for)
        with self._lock:
            existing = self.rows.get(key)
            # `leased_by` + `RUNNING` şərti — SQL-dəki `WHERE` ilə eyni.
            if (
                existing is None
                or existing.leased_by != instance_id
                or existing.status is not JobRunStatus.RUNNING
            ):
                return False
            self.rows[key] = replace(
                existing,
                status=status,
                finished_at=finished_at,
                last_error=last_error,
                result_detail=result_detail,
            )
            return True

    # --- oxu --- #

    def get(
        self, *, tenant_id: TenantId, job_key: str, scheduled_for: datetime
    ) -> ScheduledJobRun | None:
        return self.rows.get(self._key(tenant_id, job_key, scheduled_for))


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


class Recorder:
    """İşin neçə dəfə FAKTİKİ icra olunduğunu sayır (thread-safe)."""

    def __init__(self, *, detail: str | None = "hazır", error: Exception | None = None) -> None:
        self.calls: list[JobExecutionContext] = []
        self._lock = threading.Lock()
        self._detail = detail
        self._error = error

    def __call__(self, context: JobExecutionContext) -> str | None:
        with self._lock:
            self.calls.append(context)
        if self._error is not None:
            raise self._error
        return self._detail

    @property
    def count(self) -> int:
        return len(self.calls)


def _runner(
    runs: InMemoryScheduledJobRuns,
    *,
    now: datetime,
    instance_id: str = "TERMINAL-A",
    limits: dict[str, str] | None = None,
    audit: RecordingAudit | None = None,
) -> tuple[JobRunner, RecordingAudit, FakeClock]:
    clock = FakeClock(now)
    trail = audit or RecordingAudit()
    return (
        JobRunner(
            runs=runs,
            limits=FakeSystemLimits(limits),
            audit=trail,
            clock=clock,
            instance_id=instance_id,
        ),
        trail,
        clock,
    )


def _job(
    key: str = "NIGHTLY_BACKUP",
    *,
    handler: Any,
    weight: JobWeight = JobWeight.LIGHT,
    cadence: JobCadence = JobCadence.DAILY,
    enabled: bool = True,
) -> ScheduledJob:
    return ScheduledJob(key=key, handler=handler, cadence=cadence, weight=weight, enabled=enabled)


# --------------------------------------------------------------------------- #
# 1. YARIŞ VƏZİYYƏTİ — BU FAYLIN ƏSAS TESTİ
# --------------------------------------------------------------------------- #


def _race(*, atomic: bool) -> tuple[int, list[JobOutcomeState]]:
    """İki instansiya EYNİ işi EYNİ anda götürməyə çalışır.

    `atomic=False` sahtənin qorumasını söndürür (mutasiya) — nəticə testin
    həqiqətən nəyisə ölçdüyünü göstərir.
    """
    barrier = threading.Barrier(2)
    runs = InMemoryScheduledJobRuns(read_barrier=barrier, atomic=atomic)
    recorder = Recorder()

    states: list[JobOutcomeState] = []
    states_lock = threading.Lock()

    def attempt(instance: str) -> None:
        runner, _audit, _clock = _runner(runs, now=MORNING, instance_id=instance)
        runner.register(_job(handler=recorder))
        report = runner.run_due(tenant_id=TENANT, include_heavy=True)
        with states_lock:
            states.extend(outcome.state for outcome in report.outcomes)

    threads = [
        threading.Thread(target=attempt, args=("TERMINAL-A",)),
        threading.Thread(target=attempt, args=("TERMINAL-B",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=BARRIER_TIMEOUT * 2)
    assert not any(thread.is_alive() for thread in threads), "Axın asılı qaldı"
    return recorder.count, states


def test_two_instances_racing_execute_the_job_exactly_once() -> None:
    """İki terminal eyni anda götürür — YALNIZ biri icra edir.

    Barrier hər iki axını OXU-dan sonra saxlayır, yəni hər ikisi "qeyd yoxdur"
    görür. Əgər runner qərarı oxuduğu vəziyyətə görə versəydi, baz xətti iki
    dəfə hesablanar, HR eyni sənəd üçün iki e-poçt alardı.
    """
    executions, states = _race(atomic=True)

    assert executions == 1, "İş İKİ dəfə icra olundu — icarə işləmir"
    assert sorted(states, key=lambda s: s.value) == [
        JobOutcomeState.NOT_ACQUIRED,
        JobOutcomeState.SUCCEEDED,
    ]


def test_the_race_test_detects_a_broken_guard() -> None:
    """MUTASİYA YOXLAMASI — sahtənin atomikliyi söndürüləndə test DÜŞMƏLİDİR.

    Bu test olmasaydı, yuxarıdakı iddia "hər zaman yaşıl" ola bilərdi: sahtə
    işi sadəcə sıra ilə icra etsəydi (paralellik yoxdursa) heç bir qoruma
    ölçülməzdi. Aşağıdakı nəticə göstərir ki, fərqi yaradan MƏHZ atomik
    götürmədir.
    """
    executions, states = _race(atomic=False)

    assert executions == 2, (
        "Qoruma söndürüldü, lakin iş yenə bir dəfə işlədi — yarış testi "
        "atomikliyi ÖLÇMÜR və heç nə qorumur."
    )
    assert states == [JobOutcomeState.SUCCEEDED, JobOutcomeState.SUCCEEDED]


# --------------------------------------------------------------------------- #
# 2. GECİKMİŞ İCRA VƏ İDEMPOTENTLİK
# --------------------------------------------------------------------------- #


def test_missed_nightly_slot_runs_when_the_terminal_starts_late() -> None:
    """03:00-a planlaşdırılıb, kompüter 09:12-də açılıb → İCRA OLUNUR.

    "Vaxt keçdi, buraxaq" davranışı masaüstü tətbiqdə işi ƏBƏDİ icra
    olunmamış qoyardı.
    """
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, _clock = _runner(runs, now=MORNING)
    runner.register(_job(handler=recorder))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 1
    assert report.outcomes[0].state is JobOutcomeState.SUCCEEDED
    # Slot 03:00-dır, faktiki başlanğıc 09:12 — gecikmə görünən qalır.
    assert recorder.calls[0].scheduled_for == NIGHT_SLOT
    assert recorder.calls[0].now == MORNING


def test_the_same_slot_is_not_executed_twice_on_the_same_day() -> None:
    """İdempotentlik: eyni gün ikinci çağırış İCRA ETMİR."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, clock = _runner(runs, now=MORNING)
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)
    clock.set(MORNING + timedelta(hours=3))
    second = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 1
    assert second.outcomes[0].state is JobOutcomeState.NOT_ACQUIRED
    stored = runs.get(tenant_id=TENANT, job_key="NIGHTLY_BACKUP", scheduled_for=NIGHT_SLOT)
    assert stored is not None
    assert stored.status is JobRunStatus.SUCCEEDED
    assert stored.attempts == 1, "Tamamlanmış slot üçün cəhd sayğacı artmamalıdır"


def test_the_next_day_slot_is_a_new_run() -> None:
    """Növbəti gün AYRI slotdur — idempotentlik günü bloklamır."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, clock = _runner(runs, now=MORNING)
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)
    clock.set(MORNING + timedelta(days=1))
    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 2
    assert {call.scheduled_for for call in recorder.calls} == {
        NIGHT_SLOT,
        NIGHT_SLOT + timedelta(days=1),
    }


# --------------------------------------------------------------------------- #
# 3. SLOT SƏRHƏDİ (`SCHEDULER_NIGHTLY_HOUR`)
# --------------------------------------------------------------------------- #


def test_slot_boundary_exactly_at_the_nightly_hour_belongs_to_today() -> None:
    """TAM 03:00:00 — slot BUGÜNKÜDÜR (`local_now < slot` müqayisəsi).

    `<=` yazılsaydı, sərhəd anında işləyən dövrə dünənin slotunu görər və
    günün işi bir dövrə (15 dəq.) gecikərdi.
    """
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, _clock = _runner(runs, now=NIGHT_SLOT)
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.calls[0].scheduled_for == NIGHT_SLOT


def test_slot_boundary_one_second_before_belongs_to_yesterday() -> None:
    """02:59:59 — hələ DÜNƏNKİ slotdur (gecə işi bu gün üçün işləməyib)."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, _clock = _runner(runs, now=NIGHT_SLOT - timedelta(seconds=1))
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.calls[0].scheduled_for == NIGHT_SLOT - timedelta(days=1)


def test_the_nightly_hour_comes_from_root_not_from_code() -> None:
    """Root saatı dəyişəndə slot da dəyişir — kodda sabit saat YOXDUR."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, _clock = _runner(
        runs, now=MORNING, limits={SystemLimitKey.SCHEDULER_NIGHTLY_HOUR.value: "5"}
    )
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.calls[0].scheduled_for == local(2026, 8, 13, 5)


def test_an_out_of_range_nightly_hour_is_clamped_to_a_real_hour() -> None:
    """Root yararsız saat yazsa (99), dövrə çökmür — sərhədə sıxılır."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, _clock = _runner(
        runs, now=MORNING, limits={SystemLimitKey.SCHEDULER_NIGHTLY_HOUR.value: "99"}
    )
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.calls[0].scheduled_for == local(2026, 8, 12, 23)


def test_hourly_cadence_uses_the_start_of_the_hour() -> None:
    """Saatlıq iş üçün slot saatın BAŞIDIR — dəqiqə/saniyə kəsilir."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, _clock = _runner(runs, now=local(2026, 8, 13, 9, 47, second=30))
    runner.register(_job(key="STALE_FINE_SWEEP", handler=recorder, cadence=JobCadence.HOURLY))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.calls[0].scheduled_for == local(2026, 8, 13, 9)


# --------------------------------------------------------------------------- #
# 4. QİSMƏN UĞUR
# --------------------------------------------------------------------------- #


def test_one_failing_job_does_not_stop_the_others() -> None:
    """Bir iş istisna atır → qalanlar işləyir, çökən `FAILED` yazılır."""
    runs = InMemoryScheduledJobRuns()
    first = Recorder()
    broken = Recorder(error=RuntimeError("1C cavab vermir"))
    last = Recorder()
    runner, audit, _clock = _runner(runs, now=MORNING)
    runner.register(_job(key="BEHAVIOR_BASELINE", handler=first))
    runner.register(_job(key="DOCUMENT_EXPIRY", handler=broken))
    runner.register(_job(key="ATTRITION_SCORE", handler=last))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert (first.count, broken.count, last.count) == (1, 1, 1)
    assert report.failed_jobs == ("DOCUMENT_EXPIRY",)
    assert report.succeeded == 2
    stored = runs.get(tenant_id=TENANT, job_key="DOCUMENT_EXPIRY", scheduled_for=NIGHT_SLOT)
    assert stored is not None
    assert stored.status is JobRunStatus.FAILED
    assert stored.last_error is not None
    assert "1C cavab vermir" in stored.last_error
    # Audit AQREQATDIR: üç iş üçün BİR sətir.
    assert audit.actions() == ["SCHEDULED_JOBS_EXECUTED"]


def test_a_failed_job_is_retried_until_the_attempt_ceiling() -> None:
    """Uğursuz iş növbəti dövrələrdə təkrarlanır, tavanda DAYANIR."""
    runs = InMemoryScheduledJobRuns()
    broken = Recorder(error=RuntimeError("şəbəkə yoxdur"))
    runner, _audit, clock = _runner(runs, now=MORNING)
    runner.register(_job(key="PAYMENT_REMINDER", handler=broken, cadence=JobCadence.HOURLY))

    # Eyni saat slotunda `MAX_ATTEMPTS + 2` dövrə: yalnız tavan qədəri işləyir.
    for minute in range(MAX_ATTEMPTS + 2):
        clock.set(local(2026, 8, 13, 9, minute))
        runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert broken.count == MAX_ATTEMPTS
    stored = runs.get(
        tenant_id=TENANT, job_key="PAYMENT_REMINDER", scheduled_for=local(2026, 8, 13, 9)
    )
    assert stored is not None
    assert stored.attempts == MAX_ATTEMPTS


# --------------------------------------------------------------------------- #
# 5. ÇÖKMÜŞ İNSTANSİYA — İCARƏ MÜDDƏTİ
# --------------------------------------------------------------------------- #


def _crashed_lease(runs: InMemoryScheduledJobRuns) -> ScheduledJobRun:
    """Çökmüş terminalın izi: `RUNNING`, heç vaxt bitməyən sətir."""
    run = ScheduledJobRun(
        tenant_id=TENANT,
        job_key="NIGHTLY_BACKUP",
        scheduled_for=NIGHT_SLOT,
        status=JobRunStatus.RUNNING,
        leased_by="TERMINAL-ÇÖKMÜŞ",
        leased_until=NIGHT_SLOT + timedelta(minutes=LEASE_MINUTES),
        started_at=NIGHT_SLOT,
        attempts=1,
    )
    runs.rows[InMemoryScheduledJobRuns._key(TENANT, "NIGHTLY_BACKUP", NIGHT_SLOT)] = run
    return run


def test_a_crashed_instance_lease_is_reclaimed_after_it_expires() -> None:
    """Cərəyan kəsilib: icarə bitəndən sonra iş YENİDƏN götürülür.

    Bu qoruma olmasaydı, iş əbədi "RUNNING" qalar və bir daha işləməzdi.
    """
    runs = InMemoryScheduledJobRuns()
    crashed = _crashed_lease(runs)
    recorder = Recorder()
    runner, _audit, _clock = _runner(
        runs, now=crashed.leased_until + timedelta(seconds=1), instance_id="TERMINAL-B"
    )
    runner.register(_job(handler=recorder))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 1
    assert report.outcomes[0].state is JobOutcomeState.SUCCEEDED
    stored = runs.get(tenant_id=TENANT, job_key="NIGHTLY_BACKUP", scheduled_for=NIGHT_SLOT)
    assert stored is not None
    assert stored.leased_by == "TERMINAL-B"
    assert stored.attempts == 2


def test_a_live_lease_is_not_stolen() -> None:
    """İcarə hələ diridirsə (bir saniyə qalıb) — iş GÖTÜRÜLMÜR."""
    runs = InMemoryScheduledJobRuns()
    crashed = _crashed_lease(runs)
    recorder = Recorder()
    runner, _audit, _clock = _runner(
        runs, now=crashed.leased_until - timedelta(seconds=1), instance_id="TERMINAL-B"
    )
    runner.register(_job(handler=recorder))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 0
    assert report.outcomes[0].state is JobOutcomeState.NOT_ACQUIRED


def test_the_lease_boundary_is_inclusive() -> None:
    """SƏRHƏD: `now == leased_until` anında icarə ARTIQ bitmiş sayılır.

    `<=` seçimi kod (`is_lease_expired`) və SQL (`leased_until <= %s`) üçün
    eynidir; `<` olsaydı, sərhəd anında iki instansiya eyni işi "diri icarə"
    ilə görərdi.
    """
    runs = InMemoryScheduledJobRuns()
    crashed = _crashed_lease(runs)
    recorder = Recorder()
    runner, _audit, _clock = _runner(runs, now=crashed.leased_until, instance_id="TERMINAL-B")
    runner.register(_job(handler=recorder))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 1
    assert report.outcomes[0].state is JobOutcomeState.SUCCEEDED


def test_a_late_finisher_cannot_overwrite_the_new_owner() -> None:
    """İcarəsi keçmiş instansiya nəticəsini YENİ sahibin üstünə yaza bilmir."""
    runs = InMemoryScheduledJobRuns()
    crashed = _crashed_lease(runs)

    taken = runs.acquire(
        tenant_id=TENANT,
        job_key="NIGHTLY_BACKUP",
        scheduled_for=NIGHT_SLOT,
        instance_id="TERMINAL-B",
        now=crashed.leased_until,
        leased_until=crashed.leased_until + timedelta(minutes=LEASE_MINUTES),
        max_attempts=MAX_ATTEMPTS,
    )
    late = runs.mark_succeeded(
        tenant_id=TENANT,
        job_key="NIGHTLY_BACKUP",
        scheduled_for=NIGHT_SLOT,
        instance_id="TERMINAL-ÇÖKMÜŞ",
        finished_at=crashed.leased_until + timedelta(minutes=1),
    )

    assert taken is True
    assert late is False, "Köhnə sahib yeni icarənin nəticəsini üstündən yazdı"


def test_a_lost_lease_is_reported_but_does_not_break_the_cycle() -> None:
    """İcarə iş ərzində başqasına keçsə, dövrə çökmür — nəticə YAZILMIR.

    Bu, `SCHEDULER_LEASE_MINUTES` çox kiçik seçiləndə baş verir və planlayıcı
    üçün YEGANƏ siqnaldır (`SCHEDULED_JOB_LEASE_LOST` xəbərdarlığı). Sətir
    yeni sahibin adında `RUNNING` qalır — köhnə icraçı onu üstündən yaza
    bilmir.
    """
    runs = InMemoryScheduledJobRuns()
    key = InMemoryScheduledJobRuns._key(TENANT, "NIGHTLY_BACKUP", NIGHT_SLOT)

    def steal_the_lease(context: JobExecutionContext) -> str:
        runs.rows[key] = replace(runs.rows[key], leased_by="TERMINAL-B")
        return "iş bitdi, amma gec"

    runner, _audit, _clock = _runner(runs, now=MORNING, instance_id="TERMINAL-A")
    runner.register(_job(handler=steal_the_lease))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert runner.instance_id == "TERMINAL-A"
    assert report.outcomes[0].state is JobOutcomeState.SUCCEEDED
    stored = runs.get(tenant_id=TENANT, job_key="NIGHTLY_BACKUP", scheduled_for=NIGHT_SLOT)
    assert stored is not None
    assert stored.status is JobRunStatus.RUNNING
    assert stored.leased_by == "TERMINAL-B"


# --------------------------------------------------------------------------- #
# 6. AĞIR / YÜNGÜL AYRIMI
# --------------------------------------------------------------------------- #


def test_light_only_mode_skips_heavy_jobs() -> None:
    """GUI axını: ağır iş ATLANIR, yüngül iş işləyir."""
    runs = InMemoryScheduledJobRuns()
    heavy = Recorder()
    light = Recorder()
    runner, _audit, _clock = _runner(runs, now=MORNING)
    runner.register(_job(key="NIGHTLY_BACKUP", handler=heavy, weight=JobWeight.HEAVY))
    runner.register(_job(key="DOCUMENT_EXPIRY", handler=light))

    report = runner.run_due(tenant_id=TENANT, include_heavy=False)

    assert heavy.count == 0
    assert light.count == 1
    assert report.skipped_heavy == ("NIGHTLY_BACKUP",)
    # Atlanan iş İCARƏ DƏ GÖTÜRMÜR: əks halda gecə işi GUI tərəfindən
    # "tamamlanmış" işarələnər və CLI onu bir daha işlətməzdi.
    assert runs.acquire_calls == ["DOCUMENT_EXPIRY"]


def test_heavy_jobs_run_when_they_are_included() -> None:
    """CLI axını: `include_heavy=True` ağır işi icra edir."""
    runs = InMemoryScheduledJobRuns()
    heavy = Recorder()
    runner, _audit, _clock = _runner(runs, now=MORNING)
    runner.register(_job(key="NIGHTLY_BACKUP", handler=heavy, weight=JobWeight.HEAVY))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert heavy.count == 1
    assert report.skipped_heavy == ()


# --------------------------------------------------------------------------- #
# 7. REYESTR: BOŞ, SÖNDÜRÜLMÜŞ, TƏKRAR, QEYDİYYATSIZ
# --------------------------------------------------------------------------- #


def test_an_empty_registry_does_not_crash() -> None:
    """Sıfır iş — dövrə sükutla və çökmədən keçir, audit yazılmır."""
    runs = InMemoryScheduledJobRuns()
    runner, audit, _clock = _runner(runs, now=MORNING)

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert report.outcomes == ()
    assert report.executed == 0
    assert runs.acquire_calls == []
    assert audit.entries == [], "İcra baş vermədi — aqreqat audit sətri də olmamalıdır"


def test_a_disabled_job_is_not_executed() -> None:
    """Söndürülmüş iş reyestrdə qalır, lakin icarə də götürmür."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, audit, _clock = _runner(runs, now=MORNING)
    runner.register(_job(handler=recorder, enabled=False))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 0
    assert report.outcomes[0].state is JobOutcomeState.DISABLED
    assert runs.acquire_calls == []
    assert audit.entries == []


def test_an_unregistered_job_never_runs() -> None:
    """Qeydiyyatdan keçməyən iş nə tapılır, nə icra olunur."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    registry = ScheduledJobRegistry()
    registry.register(_job(key="BEHAVIOR_BASELINE", handler=recorder))
    runner = JobRunner(
        runs=runs,
        limits=FakeSystemLimits(),
        audit=RecordingAudit(),
        clock=FakeClock(MORNING),
        instance_id="TERMINAL-A",
        registry=registry,
    )

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert registry.get("NIGHTLY_BACKUP") is None
    assert "NIGHTLY_BACKUP" not in registry
    assert runs.acquire_calls == ["BEHAVIOR_BASELINE"]


def test_registering_the_same_key_twice_is_a_startup_failure() -> None:
    """İkiqat qeydiyyat sükutla udulmur — hər ikisi eyni icarəyə düşərdi."""
    runner, _audit, _clock = _runner(InMemoryScheduledJobRuns(), now=MORNING)
    runner.register(_job(handler=Recorder()))

    with pytest.raises(DuplicateJobError):
        runner.register(_job(handler=Recorder()))


def test_job_keys_are_normalised_everywhere() -> None:
    """`"nightly_backup"` → `"NIGHTLY_BACKUP"`: reyestr, DB və log eyni açarı görür."""
    job = _job(key="  nightly_backup ", handler=Recorder())
    registry = ScheduledJobRegistry((job,))

    assert job.key == "NIGHTLY_BACKUP"
    assert registry.keys() == ("NIGHTLY_BACKUP",)
    assert registry.get("nightly_backup") is job
    assert registry.get("xx") is None  # yararsız açar istisna atmır


def test_registry_preserves_registration_order() -> None:
    """Sıra qeydiyyat sırasıdır — `started_at` möhürləri qarışmasın deyə."""
    registry = ScheduledJobRegistry()
    for key in ("ALFA_JOB", "BETA_JOB", "QAMMA_JOB"):
        registry.register(_job(key=key, handler=Recorder()))

    assert registry.keys() == ("ALFA_JOB", "BETA_JOB", "QAMMA_JOB")
    assert [job.key for job in registry] == ["ALFA_JOB", "BETA_JOB", "QAMMA_JOB"]
    assert len(registry) == 3
    assert registry.is_empty is False
    # `repr` diaqnostikadır: hansı işlərin bağlandığını log-da görmək üçün.
    assert "BETA_JOB" in repr(registry)


# --------------------------------------------------------------------------- #
# 8. PARAMETRLƏR VƏ SƏRHƏD GİRİŞLƏRİ
# --------------------------------------------------------------------------- #


def test_poll_interval_comes_from_root() -> None:
    """`QTimer` aralığı ROOT parametrindən oxunur, kodda sabit YOXDUR."""
    runner, _audit, _clock = _runner(InMemoryScheduledJobRuns(), now=MORNING)
    assert runner.poll_interval(TENANT) == timedelta(
        minutes=int(DEFAULT_LIMITS[SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES])
    )

    custom, _a, _c = _runner(
        InMemoryScheduledJobRuns(),
        now=MORNING,
        limits={SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES.value: "1"},
    )
    assert custom.poll_interval(TENANT) == timedelta(minutes=1)


def test_a_zero_poll_interval_is_rejected_by_the_clamp() -> None:
    """Sıfır aralıq dövrəni fasiləsiz işlədərdi — ən azı 1 dəqiqə."""
    runner, _audit, _clock = _runner(
        InMemoryScheduledJobRuns(),
        now=MORNING,
        limits={SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES.value: "0"},
    )
    assert runner.poll_interval(TENANT) == timedelta(minutes=1)


def test_a_broken_limit_value_falls_back_to_the_default() -> None:
    """Yararsız mətn (`"tez-tez"`) dövrəni çökdürmür — defolta düşür."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner, _audit, _clock = _runner(
        runs, now=MORNING, limits={SystemLimitKey.SCHEDULER_NIGHTLY_HOUR.value: "tez-tez"}
    )
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.calls[0].scheduled_for == NIGHT_SLOT


class UnseededLimits:
    """`system_limits` sətri hələ SEED EDİLMƏYİB — snapshot tam boşdur.

    Bu, real haldır: miqrasiya 036 tətbiq olunana qədər (və ya köhnə
    kirayəçidə) sətir mövcud olmur. Runner yalnız `all_for()` çağırır —
    portun qalan metodları bu yol üçün lazım deyil.
    """

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return {}


def test_missing_limit_rows_fall_back_to_default_limits() -> None:
    """Seed edilməmiş kirayəçidə planlayıcı `DEFAULT_LIMITS` ilə işləyir."""
    runs = InMemoryScheduledJobRuns()
    recorder = Recorder()
    runner = JobRunner(
        runs=runs,
        limits=UnseededLimits(),  # type: ignore[arg-type]
        audit=RecordingAudit(),
        clock=FakeClock(MORNING),
        instance_id="TERMINAL-A",
    )
    runner.register(_job(handler=recorder))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert recorder.count == 1
    assert recorder.calls[0].scheduled_for == NIGHT_SLOT
    assert runner.poll_interval(TENANT) == timedelta(
        minutes=int(DEFAULT_LIMITS[SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES])
    )


def test_an_empty_instance_id_is_a_configuration_error() -> None:
    """Boş instansiya identifikatoru icarəni sahibsiz qoyardı."""
    with pytest.raises(SchedulerError):
        JobRunner(
            runs=InMemoryScheduledJobRuns(),
            limits=FakeSystemLimits(),
            audit=RecordingAudit(),
            clock=FakeClock(MORNING),
            instance_id="   ",
        )


def test_a_naive_now_is_rejected() -> None:
    """tz-naive giriş rədd olunur — slot sərhədi yanlış günə düşərdi."""
    runner, _audit, _clock = _runner(InMemoryScheduledJobRuns(), now=MORNING)
    runner.register(_job(handler=Recorder()))

    with pytest.raises(NaiveDatetimeError):
        runner.run_due(
            tenant_id=TENANT,
            include_heavy=True,
            now=datetime(2026, 8, 13, 9, 12),  # noqa: DTZ001 — testin mövzusu budur
        )


def test_the_audit_row_is_a_single_aggregate() -> None:
    """235 işçi üçün 235 sətir yox — icra üçün BİR aqreqat sətir."""
    runs = InMemoryScheduledJobRuns()
    runner, audit, _clock = _runner(runs, now=MORNING)
    for key in ("BEHAVIOR_BASELINE", "DOCUMENT_EXPIRY", "ATTRITION_SCORE"):
        runner.register(_job(key=key, handler=Recorder()))

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry["action"] == "SCHEDULED_JOBS_EXECUTED"
    assert entry["actor_id"] is None, "Planlaşdırılmış işin aktoru YOXDUR"
    assert entry["after_state"]["icra_edilən"] == 3
    assert entry["after_state"]["uğurlu"] == 3


def test_result_detail_is_stored_for_the_health_screen() -> None:
    """İşin qaytardığı xülasə qeyddə saxlanılır ("işlədi, amma nə etdi?")."""
    runs = InMemoryScheduledJobRuns()
    runner, _audit, _clock = _runner(runs, now=MORNING)
    runner.register(_job(handler=Recorder(detail="235 işçi yeniləndi")))

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert report.outcomes[0].detail == "235 işçi yeniləndi"
    stored = runs.get(tenant_id=TENANT, job_key="NIGHTLY_BACKUP", scheduled_for=NIGHT_SLOT)
    assert stored is not None
    assert stored.result_detail == "235 işçi yeniləndi"


# --------------------------------------------------------------------------- #
# 9. DOMEN QEYDİ — SƏRHƏD VƏ YARARSIZ GİRİŞ
# --------------------------------------------------------------------------- #


def test_a_run_record_requires_at_least_one_attempt() -> None:
    """Sıfır/mənfi cəhd sayı cəhd tavanının hesabını pozardı."""
    with pytest.raises(InvalidJobRunError):
        ScheduledJobRun(
            tenant_id=TENANT,
            job_key="NIGHTLY_BACKUP",
            scheduled_for=NIGHT_SLOT,
            status=JobRunStatus.RUNNING,
            leased_by="TERMINAL-A",
            leased_until=NIGHT_SLOT,
            started_at=NIGHT_SLOT,
            attempts=0,
        )


def test_a_run_record_requires_a_lease_owner() -> None:
    """Sahibsiz icarə çökmüş instansiyanın izini oxunmaz edərdi."""
    with pytest.raises(InvalidJobRunError):
        ScheduledJobRun(
            tenant_id=TENANT,
            job_key="NIGHTLY_BACKUP",
            scheduled_for=NIGHT_SLOT,
            status=JobRunStatus.RUNNING,
            leased_by="  ",
            leased_until=NIGHT_SLOT,
            started_at=NIGHT_SLOT,
            attempts=1,
        )


def test_a_terminal_record_requires_a_finish_time() -> None:
    """`chk_job_run_finished` məhdudiyyətinin kod tərəfi."""
    with pytest.raises(InvalidJobRunError):
        ScheduledJobRun(
            tenant_id=TENANT,
            job_key="NIGHTLY_BACKUP",
            scheduled_for=NIGHT_SLOT,
            status=JobRunStatus.SUCCEEDED,
            leased_by="TERMINAL-A",
            leased_until=NIGHT_SLOT,
            started_at=NIGHT_SLOT,
            attempts=1,
        )


def test_a_naive_slot_is_rejected() -> None:
    """tz-naive slot iki zonada iki ayrı sətir yaradardı."""
    with pytest.raises(NaiveDatetimeError):
        ScheduledJobRun(
            tenant_id=TENANT,
            job_key="NIGHTLY_BACKUP",
            scheduled_for=datetime(2026, 8, 13, 3),  # noqa: DTZ001 — testin mövzusu budur
            status=JobRunStatus.RUNNING,
            leased_by="TERMINAL-A",
            leased_until=NIGHT_SLOT,
            started_at=NIGHT_SLOT,
            attempts=1,
        )


def test_a_succeeded_record_is_never_reclaimable() -> None:
    """Tamamlanmış slot heç bir şəraitdə yenidən götürülmür — idempotentlik."""
    done = ScheduledJobRun(
        tenant_id=TENANT,
        job_key="NIGHTLY_BACKUP",
        scheduled_for=NIGHT_SLOT,
        status=JobRunStatus.SUCCEEDED,
        leased_by="TERMINAL-A",
        leased_until=NIGHT_SLOT,
        started_at=NIGHT_SLOT,
        finished_at=NIGHT_SLOT + timedelta(minutes=2),
        attempts=1,
    )

    assert done.is_lease_expired(NIGHT_SLOT + timedelta(days=7)) is True
    assert done.is_reclaimable(NIGHT_SLOT + timedelta(days=7), max_attempts=99) is False
    assert done.is_terminal is True


def test_an_empty_job_key_is_rejected() -> None:
    """Boş/qısa açar DB `CHECK`-inə düşərdi — qeydiyyat anında tutulur."""
    for candidate in ("", "  ", "AB"):
        with pytest.raises(InvalidJobRunError):
            normalize_job_key(candidate)


def test_long_error_text_is_trimmed_visibly() -> None:
    """Uzun `traceback` kəsilir, lakin kəsilmə GÖRÜNÜR."""
    trimmed = trim_error_text("x" * 5000)

    assert len(trimmed) == 2000
    assert trimmed.endswith("…")
