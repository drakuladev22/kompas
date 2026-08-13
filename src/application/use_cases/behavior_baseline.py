"""İşçi Davranış Baz Xətti (#8, kompasos11.md Faza 5) — hesablama + qayda.

Bu fayl İKİ şeyi birlikdə saxlayır və bu QƏSDƏNDİR:

    1. `BehaviorBaselineUseCase` — gecəlik yenidən-hesablama: son N günün
       təsdiqlənmiş giriş anlarından hər işçi üçün orta vaxt/standart
       kənarlaşma çıxarır və `employee_behavior_baseline`-a yazır.
    2. `BehaviorAnomalyRule` — Vahid İstisna Motoruna (Faza 3) qoşulan qayda:
       bugünkü girişi HƏMİN baz xəttiylə müqayisə edir.

İkisi EYNİ cədvəli (`employee_behavior_baseline`) və EYNİ xam mənbəni
(`CheckInHistoryProvider`) paylaşır — ayrı fayllara bölünsəydi, "baz xətt
necə hesablanır?" və "anomaliya necə aşkarlanır?" sualları arasındakı əlaqə
yalnız idxal zənciri ilə görünərdi. Bir yerdə saxlamaq bu ƏLAQƏNİ oxucuya
dərhal göstərir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YENİ PLANLAYICI MEXANİZMİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
`recalculate_all()` `FineAppealManagementUseCase.expire_stale()` (bax
`fine_management.py`) və `NightlyBackupService.create()/prune()` ilə EYNİ
naxışı təkrarlayır: tenant başına çağırıla bilən, vaxt-idempotent BİR metod.
Onu kim və NƏ VAXT çağıracağı bu faylın işi deyil — `docs/scheduler_setup.md`
Variant A-da (`pg_cron`) və ya Variant B-də (xarici planlayıcı,
`run_all_scheduled_jobs()`) həll olunur. Yeni bir Python `Timer`/`APScheduler`
əlavə etmək bu MÖVCUD mexanizmi TƏKRARLAYAR və iki paralel planlayıcı
yarışı yaradardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BAZ XƏTT HESABLAMASI `Clock` PORTUNDAN GƏLİR, `datetime.now()` YOX
──────────────────────────────────────────────────────────────────────────────
"Son 30 gün" pəncərəsi `now`-a nisbətdir. `datetime.now()` çağırılsaydı,
gecəlik hesablamanın nəticəsini testdə TEKRAR ETMƏK mümkün olmazdı (bölmə 4,
CLAUDE.md §4 "Vaxt" tələbi) — `FakeClock` ilə eyni gün hər dəfə eyni pəncərəni
verir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import fmean, stdev
from typing import TYPE_CHECKING, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.behavior_signals import (
    MAX_CHECKIN_MINUTES,
    BehaviorBaseline,
    CheckInObservation,
)
from src.domain.value_objects.exception_signals import (
    BEHAVIOR_ANOMALY_SOURCE,
    ExceptionFinding,
    ExceptionSeverity,
    RuleEvaluationContext,
)
from src.domain.value_objects.scheduling import checkin_minutes_since_midnight
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.interfaces.ports import (
        BehaviorBaselineRepository,
        CheckInHistoryProvider,
        Clock,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_log = get_logger(__name__)

#: Fallback dəyərlər — bax `policies.py`-dakı `SystemLimitKey.BEHAVIOR_*`
#: şərhləri. HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/024 seed edir);
#: bu sabitlər YALNIZ sətir hələ seed edilməyibsə işə düşür.
_FALLBACK_WINDOW_DAYS: Final = int(DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_BASELINE_WINDOW_DAYS])
_FALLBACK_THRESHOLD_MINUTES: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_ANOMALY_THRESHOLD_MINUTES]
)
_FALLBACK_MIN_SAMPLE_SIZE: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE]
)
_FALLBACK_SIGMA_MULTIPLIER: Final = float(
    DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER]
)


# --------------------------------------------------------------------------- #
# 1. Gecəlik yenidən-hesablama
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BaselineRecalculationReport:
    """Bir icranın yekunu — planlaşdırılmış işin log/monitorinq sətri."""

    tenant_id: TenantId
    started_at: datetime
    window_days: int
    since: date
    until: date
    employees_updated: int = 0


class BehaviorBaselineUseCase:
    """Hər işçi üçün son N günün orta check-in vaxtını/kənarlaşmasını yazır."""

    def __init__(
        self,
        *,
        checkins: CheckInHistoryProvider,
        baselines: BehaviorBaselineRepository,
        limits: SystemLimits,
        clock: Clock,
    ) -> None:
        self._checkins = checkins
        self._baselines = baselines
        self._limits = limits
        self._clock = clock

    def recalculate_all(
        self, tenant_id: TenantId, *, now: datetime | None = None
    ) -> BaselineRecalculationReport:
        """Bütün işçilər üçün baz xətti yenidən yazır (planlaşdırılmış iş).

        YALNIZ ən azı BİR müşahidəsi olan işçilər üçün sətir YAZILIR/
        YENİLƏNİR — məzuniyyətdə/uzun icazədə olan işçinin köhnə (etibarlı)
        baz xətti bu pəncərədə müşahidə YOXDUR deyə sıfırla ƏVƏZ EDİLMİR.
        Bu, "yazılıdı ≠ etibarlıdır" fərqini qoruyur (bax `NightlyBackupService`
        modul başlığındakı eyni prinsip: yarımçıq nəticəni sükutla yazmaq
        mövcud, doğru məlumatdan PİSDİR).
        """
        as_of = now or self._clock.now()
        window_days = self._limits.get_int(
            tenant_id,
            SystemLimitKey.BEHAVIOR_BASELINE_WINDOW_DAYS.value,
            _FALLBACK_WINDOW_DAYS,
        )
        # Pəncərə DÜNƏNlə bitir, BUGÜNÜ ehtiva ETMİR: bugünkü giriş məhz
        # bu baz xəttiylə müqayisə ediləcək (`BehaviorAnomalyRule`) — özü öz
        # ortasını "normallaşdırsaydı", kəskin sapma belə görünməz qalardı.
        until = as_of.date() - timedelta(days=1)
        since = until - timedelta(days=max(0, window_days - 1))

        observations = self._checkins.list_checkins(tenant_id, since=since, until=until)
        grouped = _group_by_employee(observations)

        updated = 0
        for employee_id, employee_observations in grouped.items():
            minutes = [
                checkin_minutes_since_midnight(obs.checked_in_at, timezone_name=obs.store_timezone)
                for obs in employee_observations
            ]
            baseline = BehaviorBaseline(
                tenant_id=tenant_id,
                employee_id=employee_id,
                avg_checkin_minutes=round(fmean(minutes), 2),
                stddev_minutes=round(stdev(minutes), 2) if len(minutes) > 1 else 0.0,
                sample_size=len(minutes),
                last_calculated_at=as_of,
            )
            self._baselines.save(baseline)
            updated += 1

        report = BaselineRecalculationReport(
            tenant_id=tenant_id,
            started_at=as_of,
            window_days=window_days,
            since=since,
            until=until,
            employees_updated=updated,
        )
        _log.info(
            "BEHAVIOR_BASELINE_RECALCULATED",
            extra={
                "tenant_id": str(tenant_id),
                "pencere_gun": window_days,
                "yenilenen_isci": updated,
            },
        )
        return report


def _group_by_employee(
    observations: list[CheckInObservation],
) -> dict[EmployeeId, list[CheckInObservation]]:
    grouped: dict[EmployeeId, list[CheckInObservation]] = {}
    for obs in observations:
        grouped.setdefault(obs.employee_id, []).append(obs)
    return grouped


# --------------------------------------------------------------------------- #
# 2. Exception Engine qaydası
# --------------------------------------------------------------------------- #

#: Sapmanın neçə "hədd qatı" olduğuna görə baza ciddiyyəti (kiçikdən böyüyə
#: doğru, İLK uyğun gələn seçilir — bax `_severity_for`).
_RATIO_TIERS: Final[tuple[tuple[float, ExceptionSeverity], ...]] = (
    (4.0, ExceptionSeverity.CRITICAL),
    (3.0, ExceptionSeverity.HIGH),
    (2.0, ExceptionSeverity.MEDIUM),
)
_SIGMA_ESCALATION: Final[dict[ExceptionSeverity, ExceptionSeverity]] = {
    ExceptionSeverity.LOW: ExceptionSeverity.MEDIUM,
    ExceptionSeverity.MEDIUM: ExceptionSeverity.HIGH,
    ExceptionSeverity.HIGH: ExceptionSeverity.CRITICAL,
    ExceptionSeverity.CRITICAL: ExceptionSeverity.CRITICAL,
}


class BehaviorAnomalyRule:
    """#8 — bugünkü girişi işçinin baz xəttiylə müqayisə edən qayda.

    `ExceptionRule` Protokoluna (ports.py) strukturaldır — miras yoxdur.
    Reyestrə `engine.register_rule(BehaviorAnomalyRule(...))` ilə qoşulur;
    motorun ÖZÜ (`exception_engine.py`) DƏYİŞMİR.
    """

    def __init__(
        self, *, baselines: BehaviorBaselineRepository, checkins: CheckInHistoryProvider
    ) -> None:
        self._baselines = baselines
        self._checkins = checkins

    @property
    def source_code(self) -> str:
        return BEHAVIOR_ANOMALY_SOURCE

    @property
    def name_az(self) -> str:
        return "Davranış Baz Xətti Sapması"

    def evaluate(self, context: RuleEvaluationContext) -> list[ExceptionFinding]:
        """Bugünkü (`context.as_of` tarixli) girişləri baz xəttlə müqayisə edir.

        MİNİMUM NÜMUNƏ HƏDDİ (migrations/018 şərhi): `sample_size` həddin
        altında olan baz xətt bu siyahıya DAXİL EDİLMİR — az müşahidədən
        çıxan "adət" ilə anomaliya elan etmək yanlış ittihamdır.
        """
        min_sample = context.limit_int(
            SystemLimitKey.BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE.value,
            _FALLBACK_MIN_SAMPLE_SIZE,
        )
        threshold = context.limit_int(
            SystemLimitKey.BEHAVIOR_ANOMALY_THRESHOLD_MINUTES.value,
            _FALLBACK_THRESHOLD_MINUTES,
        )
        sigma_multiplier = _parse_float(
            context.limit_str(
                SystemLimitKey.BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER.value,
                str(_FALLBACK_SIGMA_MULTIPLIER),
            ),
            fallback=_FALLBACK_SIGMA_MULTIPLIER,
        )

        eligible_baselines = {
            baseline.employee_id: baseline
            for baseline in self._baselines.list_for_tenant(context.tenant_id)
            if baseline.sample_size >= min_sample
        }
        if not eligible_baselines:
            return []

        today = context.as_of.date()
        todays_checkins = self._checkins.list_checkins(context.tenant_id, since=today, until=today)

        findings: list[ExceptionFinding] = []
        for observation in todays_checkins:
            baseline = eligible_baselines.get(observation.employee_id)
            if baseline is None:
                continue

            actual_minutes = checkin_minutes_since_midnight(
                observation.checked_in_at, timezone_name=observation.store_timezone
            )
            deviation = abs(actual_minutes - baseline.avg_checkin_minutes)
            if deviation < threshold:
                continue

            severity = _severity_for(
                deviation,
                threshold=threshold,
                stddev=baseline.stddev_minutes,
                sigma_multiplier=sigma_multiplier,
            )
            findings.append(
                ExceptionFinding(
                    employee_id=observation.employee_id,
                    store_id=observation.store_id,
                    detail=(
                        f"İşçinin bugünkü giriş vaxtı ({_format_minutes(actual_minutes)}) "
                        f"adət etdiyi vaxtdan ({_format_minutes(baseline.avg_checkin_minutes)}) "
                        f"{deviation:.0f} dəqiqə fərqlənir (son {baseline.sample_size} gün üzrə)."
                    ),
                    context={
                        "baseline_avg_minutes": round(baseline.avg_checkin_minutes, 2),
                        "baseline_stddev_minutes": round(baseline.stddev_minutes, 2),
                        "baseline_sample_size": baseline.sample_size,
                        "actual_minutes": round(actual_minutes, 2),
                        "deviation_minutes": round(deviation, 2),
                        "threshold_minutes": threshold,
                    },
                    severity=severity,
                    # Qayda+işçi+tarix: eyni gün üçün EYNİ sapma iki dəfə
                    # yaranmasın (planlaşdırılmış iş hər gün yenidən işləyir,
                    # bax `exception_engine.py::_persist`).
                    dedupe_key=f"{observation.employee_id}:{today.isoformat()}",
                )
            )
        return findings


def _severity_for(
    deviation_minutes: float, *, threshold: int, stddev: float, sigma_multiplier: float
) -> ExceptionSeverity:
    """Sapmanın ölçüsünə görə ciddiyyət seçir.

    İKİ MEYAR BİRLƏŞDİRİLİR:
      1. Hədd-qatı (ratio) — sapma ROOT həddinin neçə qatıdırsa, o qədər
         yuxarı başlanğıc ciddiyyəti.
      2. σ eskalasiyası — sapma işçinin ÖZ standart kənarlaşmasının
         `sigma_multiplier` qatını keçəndə ciddiyyət BİR pillə yuxarı qalxır
         (statistik cəhətdən "bu, onun adi dəyişkənliyi deyil" siqnalı).
         `stddev == 0` olduqda (bax "sıfır stddev" test halı) bu addım
         SÜKUTLA ATLANIR — sıfıra bölmə əvəzinə sadəcə eskalasiya baş vermir.
    """
    ratio = deviation_minutes / threshold if threshold > 0 else deviation_minutes
    severity = ExceptionSeverity.LOW
    for boundary, tier in _RATIO_TIERS:
        if ratio >= boundary:
            severity = tier
            break

    if stddev > 0 and deviation_minutes >= sigma_multiplier * stddev:
        severity = _SIGMA_ESCALATION[severity]
    return severity


def _format_minutes(total_minutes: float) -> str:
    """Dəqiqəni `HH:MM` görünüşünə çevirir (`detail` mətni üçün)."""
    total = round(total_minutes) % MAX_CHECKIN_MINUTES
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_float(raw: str, *, fallback: float) -> float:
    """`system_limits`-dən onluq ədəd oxuyur — yararsız mətn fallback-a düşür.

    Root-un yazı səhvi (məs. boş sətir, vergüllü format) gecəlik aşkarlamanı
    çökdürməməlidir — `ExceptionSeverity.parse` ilə eyni fəlsəfə.
    """
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return fallback


__all__ = [
    "BaselineRecalculationReport",
    "BehaviorAnomalyRule",
    "BehaviorBaselineUseCase",
]
