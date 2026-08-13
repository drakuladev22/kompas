"""İşçi Davranış Baz Xətti (#8, kompasos11.md Faza 5) — hesablama + qayda.

BAZA LAZIM DEYİL: bütün portlar sahtə obyektlərlə əvəz olunur (bu faylda
YERLİ təyin olunub — `tests/fixtures/fakes.py`-a paralel işləyən başqa bir
agentlə konflikt riskinə görə TOXUNULMUR).

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
1. BAZ XƏTT HESABLAMASI — orta/kənarlaşma/nümunə sayı düzgün çıxır, mağazanın
   yerli zaman qurşağı nəzərə alınır (gecəyarını keçən anlar daxil).
2. KİFAYƏT QƏDƏR DATA YOXDURSA — müşahidəsi olmayan işçinin KÖHNƏ (etibarlı)
   baz xətti sıfırla ƏVƏZ EDİLMİR; boş pəncərə çökmür.
3. SƏRHƏD HALLARI — sapma həddinin DƏQİQ üstündə/altında, sıfır standart
   kənarlaşma (sıfıra bölmə YOXDUR), minimum nümunə həddinin altında olan
   baz xətt heç bir anomaliya yaratmır.
4. MOTORA GÖNDƏRMƏ — qayda `ExceptionRuleRegistry`-ə qeydiyyatdan keçir və
   `ExceptionEngineUseCase.run()` onun tapıntısını `exceptions` jurnalına
   yazır (BEHAVIOR_ANOMALY mənbəyi ilə).

Sinif/metod adları CLAUDE.md bölmə 4-ə görə İNGİLİSCƏDİR — Azərbaycan dili
yalnız docstring/şərhlərdədir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from src.application.use_cases.behavior_baseline import (
    BehaviorAnomalyRule,
    BehaviorBaselineUseCase,
)
from src.application.use_cases.exception_engine import ExceptionEngineUseCase
from src.domain.entities.base import DomainRuleError
from src.domain.exception_rules import DuplicateExceptionRuleError, ExceptionRuleRegistry
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.behavior_signals import BehaviorBaseline, CheckInObservation
from src.domain.value_objects.exception_signals import (
    BEHAVIOR_ANOMALY_SOURCE,
    ExceptionSeverity,
    ExceptionSource,
    RuleEvaluationContext,
)
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.domain.value_objects.scheduling import checkin_minutes_since_midnight
from tests.fixtures.fakes import (
    FakeClock,
    FakeExceptionSources,
    FakeSystemLimits,
    InMemoryExceptions,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
BAKU = "Asia/Baku"
#: Bu test faylında "yerli saat" birbaşa UTC kimi işlədilir — dəqiqə
#: hesabını əl ilə yoxlamağı asanlaşdırır (Bakı-özəl çevrilmə AYRICA test
#: sinfində, `TestCheckinMinutesSinceMidnight`-da örtülür).
UTC_STORE_TZ = "UTC"


# --------------------------------------------------------------------------- #
# Yerli sahtələr — `BehaviorBaselineRepository` / `CheckInHistoryProvider`
# --------------------------------------------------------------------------- #


class InMemoryBehaviorBaselines:
    """`BehaviorBaselineRepository` sahtəsi — `(tenant_id, employee_id)` açarlı."""

    def __init__(self) -> None:
        self.items: dict[tuple[TenantId, EmployeeId], BehaviorBaseline] = {}

    def get_for_employee(self, tenant_id: TenantId, employee_id: EmployeeId) -> Any:
        return self.items.get((tenant_id, employee_id))

    def list_for_tenant(self, tenant_id: TenantId) -> list[Any]:
        return [b for (t, _), b in self.items.items() if t == tenant_id]

    def save(self, baseline: BehaviorBaseline) -> None:
        self.items[(baseline.tenant_id, baseline.employee_id)] = baseline


class FakeCheckInHistory:
    """`CheckInHistoryProvider` sahtəsi — tarix süzgəci YEREL tarixə görədir.

    Real repo `work_date` sütununu süzür; sahtədə ayrıca sütun olmadığı üçün
    `checked_in_at`-in mağaza zonasındakı TARİXİ istifadə olunur — VERIFIED
    qeydlərdə bu ikisi praktik olaraq üst-üstə düşür.
    """

    def __init__(self, observations: list[CheckInObservation] | None = None) -> None:
        self.observations = list(observations or [])

    def list_checkins(
        self, tenant_id: TenantId, *, since: date, until: date
    ) -> list[CheckInObservation]:
        return [
            obs
            for obs in self.observations
            if since <= obs.checked_in_at.astimezone(ZoneInfo(obs.store_timezone)).date() <= until
        ]


def _observation(
    *,
    employee_id: EmployeeId = WORKER,
    store_id: StoreId = STORE,
    checked_in_at: datetime,
    timezone_name: str = UTC_STORE_TZ,
) -> CheckInObservation:
    """`checked_in_at` AWARE olmalıdır — çağıran tərəf öz `tzinfo`-sunu verir."""
    return CheckInObservation(
        employee_id=employee_id,
        store_id=store_id,
        checked_in_at=checked_in_at,
        store_timezone=timezone_name,
    )


def _context(
    *, as_of: datetime = NOW, overrides: dict[str, str] | None = None
) -> RuleEvaluationContext:
    limits = {key.value: value for key, value in DEFAULT_LIMITS.items()}
    limits.update(overrides or {})
    return RuleEvaluationContext(tenant_id=TENANT, as_of=as_of, limits=limits)


def _baseline(
    *, avg: float = 510.0, stddev: float = 10.0, sample_size: int = 10
) -> BehaviorBaseline:
    """Standart baz xətt: orta 08:30 (510 dəq.), kənarlaşma 10 dəq., 10 gün."""
    return BehaviorBaseline(
        tenant_id=TENANT,
        employee_id=WORKER,
        avg_checkin_minutes=avg,
        stddev_minutes=stddev,
        sample_size=sample_size,
        last_calculated_at=NOW,
    )


# --------------------------------------------------------------------------- #
# 0. `BehaviorBaseline` — DB `CHECK`-lərinin domen güzgüsü
# --------------------------------------------------------------------------- #


class TestBehaviorBaselineInvariants:
    def test_average_out_of_range_is_rejected(self) -> None:
        with pytest.raises(DomainRuleError):
            _baseline(avg=1440.0)

    def test_negative_stddev_is_rejected(self) -> None:
        with pytest.raises(DomainRuleError):
            _baseline(stddev=-1.0)

    def test_negative_sample_size_is_rejected(self) -> None:
        with pytest.raises(DomainRuleError):
            _baseline(sample_size=-1)


# --------------------------------------------------------------------------- #
# 1. `checkin_minutes_since_midnight` — xam çevirmə funksiyası
# --------------------------------------------------------------------------- #


class TestCheckinMinutesSinceMidnight:
    def test_local_midnight_is_zero_minutes(self) -> None:
        moment = datetime(2026, 8, 12, 0, 0, tzinfo=ZoneInfo(BAKU))
        assert checkin_minutes_since_midnight(moment, timezone_name=BAKU) == 0.0

    def test_end_of_day_stays_below_1440(self) -> None:
        moment = datetime(2026, 8, 12, 23, 59, 30, tzinfo=ZoneInfo(BAKU))
        result = checkin_minutes_since_midnight(moment, timezone_name=BAKU)
        assert 1439.0 < result < 1440.0

    def test_utc_moment_crossing_local_midnight_lands_on_correct_day(self) -> None:
        """Bakı UTC+4-dür: UTC 21:00 → yerli 01:00 (NÖVBƏTİ GÜN, saat 01:00)."""
        utc_moment = datetime(2026, 8, 12, 21, 0, tzinfo=UTC)
        result = checkin_minutes_since_midnight(utc_moment, timezone_name=BAKU)
        assert result == pytest.approx(60.0)


# --------------------------------------------------------------------------- #
# 2. `BehaviorBaselineUseCase.recalculate_all`
# --------------------------------------------------------------------------- #


class TestRecalculateAll:
    def test_average_and_stddev_are_computed_correctly(self) -> None:
        # UTC-nin ÖZÜ zona kimi işlədilir ki, dəqiqə hesabı əl ilə asan
        # yoxlanıla bilsin (08:20/08:30/08:40 → 500/510/520 dəqiqə).
        observations = [
            _observation(checked_in_at=datetime(2026, 8, 1, 8, 20, tzinfo=UTC)),
            _observation(checked_in_at=datetime(2026, 8, 2, 8, 30, tzinfo=UTC)),
            _observation(checked_in_at=datetime(2026, 8, 3, 8, 40, tzinfo=UTC)),
        ]
        baselines = InMemoryBehaviorBaselines()
        use_case = BehaviorBaselineUseCase(
            checkins=FakeCheckInHistory(observations),
            baselines=baselines,
            limits=FakeSystemLimits(),
            clock=FakeClock(NOW),
        )

        report = use_case.recalculate_all(TENANT)

        assert report.employees_updated == 1
        baseline = baselines.get_for_employee(TENANT, WORKER)
        assert baseline is not None
        assert baseline.avg_checkin_minutes == pytest.approx(510.0)
        assert baseline.stddev_minutes == pytest.approx(10.0)
        assert baseline.sample_size == 3

    def test_empty_history_does_not_crash_and_writes_nothing(self) -> None:
        baselines = InMemoryBehaviorBaselines()
        use_case = BehaviorBaselineUseCase(
            checkins=FakeCheckInHistory([]),
            baselines=baselines,
            limits=FakeSystemLimits(),
            clock=FakeClock(NOW),
        )

        report = use_case.recalculate_all(TENANT)

        assert report.employees_updated == 0
        assert baselines.list_for_tenant(TENANT) == []

    def test_missing_observations_do_not_zero_out_an_existing_baseline(self) -> None:
        """Uzun icazədə olan işçinin ETİBARLI köhnə baz xətti qorunmalıdır."""
        baselines = InMemoryBehaviorBaselines()
        old_baseline = BehaviorBaseline(
            tenant_id=TENANT,
            employee_id=WORKER,
            avg_checkin_minutes=500.0,
            stddev_minutes=8.0,
            sample_size=20,
            last_calculated_at=NOW - timedelta(days=1),
        )
        baselines.save(old_baseline)
        use_case = BehaviorBaselineUseCase(
            checkins=FakeCheckInHistory([]),  # bu pəncərədə HEÇ bir müşahidə yoxdur
            baselines=baselines,
            limits=FakeSystemLimits(),
            clock=FakeClock(NOW),
        )

        report = use_case.recalculate_all(TENANT)

        assert report.employees_updated == 0
        preserved = baselines.get_for_employee(TENANT, WORKER)
        assert preserved is old_baseline

    def test_single_observation_has_zero_stddev(self) -> None:
        observations = [_observation(checked_in_at=datetime(2026, 8, 1, 8, 30, tzinfo=UTC))]
        baselines = InMemoryBehaviorBaselines()
        use_case = BehaviorBaselineUseCase(
            checkins=FakeCheckInHistory(observations),
            baselines=baselines,
            limits=FakeSystemLimits(),
            clock=FakeClock(NOW),
        )

        use_case.recalculate_all(TENANT)

        baseline = baselines.get_for_employee(TENANT, WORKER)
        assert baseline is not None
        assert baseline.sample_size == 1
        assert baseline.stddev_minutes == 0.0

    def test_window_excludes_today(self) -> None:
        """Bugünkü giriş baz xəttin İÇİNƏ düşməməlidir — özü özünü normallaşdırmasın."""
        today_observation = _observation(checked_in_at=NOW)
        baselines = InMemoryBehaviorBaselines()
        use_case = BehaviorBaselineUseCase(
            checkins=FakeCheckInHistory([today_observation]),
            baselines=baselines,
            limits=FakeSystemLimits(),
            clock=FakeClock(NOW),
        )

        report = use_case.recalculate_all(TENANT)

        assert report.employees_updated == 0
        assert baselines.list_for_tenant(TENANT) == []


# --------------------------------------------------------------------------- #
# 3. `BehaviorAnomalyRule.evaluate` — sərhəd halları
# --------------------------------------------------------------------------- #


class TestBehaviorAnomalyRule:
    def test_deviation_below_threshold_raises_nothing(self) -> None:
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline())
        # Hədd 45 dəqiqədir (DEFAULT_LIMITS): 510+44=554 dəqiqə (09:14) —
        # 44 dəqiqəlik sapma KİFAYƏT ETMİR.
        today = _observation(checked_in_at=datetime(2026, 8, 12, 9, 14, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        findings = rule.evaluate(_context())

        assert findings == []

    def test_deviation_exactly_at_threshold_raises_a_finding(self) -> None:
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline())
        # 510 + 45 = 555 dəqiqə → sapma DƏQİQ hədd qədərdir (sərhəd daxildir).
        today = _observation(checked_in_at=datetime(2026, 8, 12, 9, 15, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        findings = rule.evaluate(_context())

        assert len(findings) == 1
        finding = findings[0]
        assert finding.employee_id == WORKER
        assert finding.store_id == STORE
        assert finding.dedupe_key == f"{WORKER}:{NOW.date().isoformat()}"
        assert finding.context["deviation_minutes"] == pytest.approx(45.0)

    def test_sample_size_below_minimum_raises_nothing(self) -> None:
        """Migrations/018 şərhi: az nümunədən çıxan baz xətt anomaliya elan edə bilməz."""
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline(sample_size=2))  # DEFAULT min = 5
        # Nəhəng sapma olsa belə (3 saat) — nümunə azdır, qayda SUSMALIDIR.
        today = _observation(checked_in_at=datetime(2026, 8, 12, 11, 30, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        findings = rule.evaluate(_context())

        assert findings == []

    def test_zero_stddev_does_not_raise_a_division_error(self) -> None:
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline(stddev=0.0))
        # Sapma = 2×hədd (90 dəqiqə) → ratio-tier MEDIUM, lakin σ=0 olduğu üçün
        # eskalasiya ATLANMALIDIR (sıfıra bölmə İSTİSNA ATMAMALIDIR).
        today = _observation(checked_in_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        findings = rule.evaluate(_context())

        assert len(findings) == 1
        assert findings[0].severity is ExceptionSeverity.MEDIUM

    def test_large_deviation_is_escalated_by_sigma(self) -> None:
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline(avg=510.0, stddev=10.0))
        # Sapma 60 dəqiqə: ratio=60/45≈1.33 → əsas tier LOW, lakin
        # 60 >= 2.0×10 (σ) olduğu üçün BİR pillə yuxarı — MEDIUM.
        today = _observation(checked_in_at=datetime(2026, 8, 12, 9, 30, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        findings = rule.evaluate(_context())

        assert len(findings) == 1
        assert findings[0].severity is ExceptionSeverity.MEDIUM

    def test_employee_without_baseline_is_skipped(self) -> None:
        baselines = InMemoryBehaviorBaselines()  # heç bir baz xətt YOXDUR
        today = _observation(checked_in_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        assert rule.evaluate(_context()) == []

    def test_no_checkin_today_raises_nothing(self) -> None:
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline())
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([]))

        assert rule.evaluate(_context()) == []

    def test_root_threshold_override_changes_the_gate(self) -> None:
        """SOFT-CODED: hədd `system_limits`-dən gəlir — sinifdə hardcode YOXDUR.

        Defolt həddə (45 dəq.) görə keçməyəcək 20 dəqiqəlik sapma, Root
        həddi 10-a endirəndə anomaliya kimi elan olunmalıdır.
        """
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline())
        # 510 + 20 = 530 dəqiqə (08:50).
        today = _observation(checked_in_at=datetime(2026, 8, 12, 8, 50, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        assert rule.evaluate(_context()) == []
        overridden = _context(
            overrides={SystemLimitKey.BEHAVIOR_ANOMALY_THRESHOLD_MINUTES.value: "10"}
        )
        assert len(rule.evaluate(overridden)) == 1


# --------------------------------------------------------------------------- #
# 4. Motora göndərmə — `ExceptionEngineUseCase` ilə tam inteqrasiya
# --------------------------------------------------------------------------- #


class TestEngineIntegration:
    def test_rule_registers_and_engine_persists_the_finding(self) -> None:
        baselines = InMemoryBehaviorBaselines()
        baselines.save(_baseline())
        today = _observation(checked_in_at=datetime(2026, 8, 12, 9, 30, tzinfo=UTC))
        rule = BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([today]))

        registry = ExceptionRuleRegistry()
        registered_code = registry.register(rule)
        assert registered_code == BEHAVIOR_ANOMALY_SOURCE

        exceptions = InMemoryExceptions()
        engine = ExceptionEngineUseCase(
            exceptions=exceptions,
            sources=FakeExceptionSources(
                [
                    ExceptionSource(
                        code=BEHAVIOR_ANOMALY_SOURCE,
                        name_az="Davranış Anomaliyası",
                        default_severity=ExceptionSeverity.MEDIUM,
                    )
                ]
            ),
            registry=registry,
            limits=FakeSystemLimits(),
            audit=RecordingAudit(),
            clock=FakeClock(NOW),
            notifier=RecordingNotifier(),
        )

        report = engine.run(tenant_id=TENANT)

        assert report.created_total == 1
        assert not report.failed_rules
        saved = next(iter(exceptions.items.values()))
        assert saved.source == BEHAVIOR_ANOMALY_SOURCE
        assert saved.employee_id == WORKER
        assert saved.store_id == STORE
        assert saved.status.value == "OPEN"

    def test_duplicate_registration_is_rejected(self) -> None:
        """Reyestr QƏSDƏN eyni mənbədə ikinci qaydaya icazə vermir (bax `exception_rules.py`)."""
        baselines = InMemoryBehaviorBaselines()
        registry = ExceptionRuleRegistry()
        registry.register(BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([])))

        with pytest.raises(DuplicateExceptionRuleError):
            registry.register(
                BehaviorAnomalyRule(baselines=baselines, checkins=FakeCheckInHistory([]))
            )
