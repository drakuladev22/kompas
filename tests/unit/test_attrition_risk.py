"""İşdən Çıxma Riski Balı (#21, kompasos11.md Faza 9) testləri.

──────────────────────────────────────────────────────────────────────────────
BİRİNCİ QAPI: 1C-YƏ TOXUNMAMAQ
──────────────────────────────────────────────────────────────────────────────
`test_staffing_pattern.py` (#13) ilə EYNİ statik (`ast`) qapı: kimsə sabah
`SalesDataConnector`-u bu modullara asılılıq kimi əlavə etsə, kompilyasiya
xətası VERMƏZ və qərar sükutla geri alınmış olardı.

Sahtələr YERLİdir (`tests/fixtures/fakes.py` toxunulmur) — `test_staffing_
pattern.py`/`test_employee_documents.py` başlıqlarındakı eyni əsaslandırma:
bu fayl paralel işləyən başqa fazaların sahtə dəstindən asılı olmamalıdır.
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases.attrition_risk import (
    ATTRITION_RISK_NOTIFICATION_CATEGORY,
    VIEW_ATTRITION_RISK_FLAG,
    AttritionRiskUseCase,
    EmployeeAttritionSignals,
)
from src.domain.attrition_rules import (
    MAX_SCORE,
    AttritionRiskScore,
    AttritionSignal,
    AttritionSignalInput,
    AttritionWeights,
    calculate_attrition_score,
    tenure_months,
)
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import EmployeeId, PositionId, StoreId, TenantId

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)

_USE_CASE_PATH: Final = (
    Path(__file__).resolve().parents[2] / "src/application/use_cases/attrition_risk.py"
)
_REPO_PATH: Final = (
    Path(__file__).resolve().parents[2] / "src/infrastructure/persistence/attrition_repository.py"
)


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


@dataclass
class FakeClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


class FakeLimits:
    """`SystemLimits` — dəyər verilməyibsə çağıranın DEFOLTUNU qaytarır."""

    def __init__(self, values: dict[str, int] | None = None) -> None:
        self._values = values or {}
        self.requested: list[str] = []

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        self.requested.append(key)
        return int(self._values.get(key, default))

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return str(self._values.get(key, default))

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return {}


class FakeSignals:
    """`AttritionSignalProvider` — sabit siyahını geri qaytarır."""

    def __init__(self, rows: list[EmployeeAttritionSignals]) -> None:
        self._rows = rows
        self.calls: list[tuple[TenantId, int, date]] = []

    def list_signals(
        self, tenant_id: TenantId, *, window_months: int, as_of: date
    ) -> list[EmployeeAttritionSignals]:
        self.calls.append((tenant_id, window_months, as_of))
        return list(self._rows)


class FakeScores:
    """`AttritionRiskScoreRepository` — yaddaşda saxlanan tarixçə."""

    def __init__(self) -> None:
        self.rows: dict[tuple[TenantId, EmployeeId, date], AttritionRiskScore] = {}

    def save(self, score: AttritionRiskScore) -> None:
        self.rows[(score.tenant_id, score.employee_id, score.score_date)] = score

    def get_latest_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> AttritionRiskScore | None:
        candidates = [
            s for (t, e, _d), s in self.rows.items() if t == tenant_id and e == employee_id
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.score_date)

    def list_latest_for_tenant(self, tenant_id: TenantId) -> list[AttritionRiskScore]:
        latest: dict[EmployeeId, AttritionRiskScore] = {}
        for (t, e, _d), s in self.rows.items():
            if t != tenant_id:
                continue
            if e not in latest or s.score_date > latest[e].score_date:
                latest[e] = s
        return list(latest.values())


class FakeEmployees:
    """`EmployeeRepository` — YALNIZ bu testlərin işlətdiyi iki metod."""

    def __init__(
        self,
        *,
        by_store: dict[StoreId, list[Employee]] | None = None,
        by_id: dict[EmployeeId, Employee] | None = None,
    ) -> None:
        self._by_store = by_store or {}
        self._by_id = by_id or {}

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._by_id.get(employee_id)

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Employee]:
        return list(self._by_store.get(store_id, []))


@dataclass
class RecordingAudit:
    entries: list[dict[str, object]] = field(default_factory=list)

    def record(self, **kwargs: object) -> None:
        self.entries.append(kwargs)


@dataclass
class RecordingNotifier:
    messages: list[dict[str, object]] = field(default_factory=list)

    def notify(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


def make_position(code: str, *, priority: RolePriority, flags: list[PermissionFlag]) -> Position:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=code.title(),
        priority=priority,
        is_system=True,
    )
    for flag in flags:
        position.grant(flag)
    return position


def make_employee(
    *, position: Position, store_id: StoreId | None = None, employee_id: EmployeeId | None = None
) -> Employee:
    return Employee(
        employee_id=employee_id or EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Ad",
        last_name="Soyad",
        store_id=store_id,
        has_pin=True,
    )


def build(
    signal_rows: list[EmployeeAttritionSignals],
    *,
    limits_values: dict[str, int] | None = None,
    employees_by_store: dict[StoreId, list[Employee]] | None = None,
    moment: datetime = NOW,
) -> tuple[AttritionRiskUseCase, FakeScores, RecordingNotifier, RecordingAudit, FakeLimits]:
    scores = FakeScores()
    notifier = RecordingNotifier()
    audit = RecordingAudit()
    limits = FakeLimits(limits_values)
    employees = FakeEmployees(by_store=employees_by_store)
    use_case = AttritionRiskUseCase(
        signals=FakeSignals(signal_rows),
        scores=scores,
        employees=employees,
        limits=limits,
        audit=audit,
        clock=FakeClock(moment),
        notifier=notifier,
    )
    return use_case, scores, notifier, audit, limits


def make_signals(
    *,
    employee_id: EmployeeId = WORKER,
    store_id: StoreId | None = STORE,
    hire_date: date | None = None,
    fine_recent: int = 0,
    fine_prior: int = 0,
    absences: int = 0,
    leave_minutes: int = 0,
) -> EmployeeAttritionSignals:
    return EmployeeAttritionSignals(
        employee_id=employee_id,
        store_id=store_id,
        hire_date=hire_date,
        fine_count_recent_half=fine_recent,
        fine_count_prior_half=fine_prior,
        unauthorized_absences=absences,
        leave_minutes_used=leave_minutes,
    )


# --------------------------------------------------------------------------- #
# 1. Saf domen hesablaması
# --------------------------------------------------------------------------- #


def test_zero_signals_produce_zero_score_but_full_explanation() -> None:
    """Sıfır datalı (yeni işə düşən, hire_date məlum deyil) işçi → sıfır bal."""
    result = calculate_attrition_score(
        AttritionSignalInput(
            fine_count_recent_half=0,
            fine_count_prior_half=0,
            unauthorized_absences=0,
            tenure_months=None,
            leave_usage_ratio=0.0,
        ),
        AttritionWeights.defaults(),
    )
    assert result.score == 0.0
    assert not result.is_high_risk
    # Dörd siqnalın HAMISI YAZILIR — sıfır olsa belə (bax modul başlığı).
    signals_present = {factor.signal for factor in result.factors}
    assert signals_present == {
        AttritionSignal.FINE_TREND,
        AttritionSignal.ATTENDANCE_VIOLATIONS,
        AttritionSignal.NEW_HIRE_TENURE,
        AttritionSignal.LEAVE_USAGE,
    }


def test_weight_change_changes_the_score() -> None:
    """Hardcode olsaydı çəki dəyişəndə bal DƏYİŞMƏZDİ — bu, ona qarşı qapıdır."""
    signals = AttritionSignalInput(
        fine_count_recent_half=5,
        fine_count_prior_half=2,
        unauthorized_absences=0,
        tenure_months=None,
        leave_usage_ratio=0.0,
    )
    low_weight = AttritionWeights(
        fine_trend_weight=1,
        attendance_violation_weight=1,
        new_hire_risk_points=1,
        new_hire_threshold_months=3,
        leave_usage_weight=1,
        window_months=3,
        high_risk_threshold=70,
    )
    high_weight = AttritionWeights(
        fine_trend_weight=20,
        attendance_violation_weight=1,
        new_hire_risk_points=1,
        new_hire_threshold_months=3,
        leave_usage_weight=1,
        window_months=3,
        high_risk_threshold=70,
    )
    low = calculate_attrition_score(signals, low_weight)
    high = calculate_attrition_score(signals, high_weight)
    assert low.score != high.score
    assert high.score > low.score
    assert high.score == pytest.approx(60.0)  # trend=3 × çəki 20


def test_factors_json_sum_matches_the_final_score() -> None:
    """`factors_json`-un bal cəmi HƏMİŞƏ yekun balla üst-üstə düşür (cəm uyğunluğu)."""
    result = calculate_attrition_score(
        AttritionSignalInput(
            fine_count_recent_half=4,
            fine_count_prior_half=1,
            unauthorized_absences=2,
            tenure_months=1.0,
            leave_usage_ratio=0.5,
        ),
        AttritionWeights.defaults(),
    )
    payload = result.factors_payload()
    total = sum(float(entry["bal"]) for entry in payload.values())
    assert total == pytest.approx(result.score)


def test_score_cap_factor_keeps_the_sum_invariant_when_total_exceeds_100() -> None:
    """Dörd amilin xam cəmi 100-ü keçəndə `SCORE_CAP` fərqi izah edir."""
    weights = AttritionWeights(
        fine_trend_weight=90,
        attendance_violation_weight=50,
        new_hire_risk_points=0,
        new_hire_threshold_months=3,
        leave_usage_weight=0,
        window_months=3,
        high_risk_threshold=70,
    )
    result = calculate_attrition_score(
        AttritionSignalInput(
            fine_count_recent_half=2,
            fine_count_prior_half=0,
            unauthorized_absences=1,
            tenure_months=None,
            leave_usage_ratio=0.0,
        ),
        weights,
    )
    assert result.score == MAX_SCORE
    cap_factors = [f for f in result.factors if f.signal is AttritionSignal.SCORE_CAP]
    assert len(cap_factors) == 1
    assert cap_factors[0].points < 0
    assert sum(f.points for f in result.factors) == pytest.approx(result.score)


def test_new_hire_signal_fires_only_under_the_threshold() -> None:
    weights = AttritionWeights.defaults()
    new_hire = calculate_attrition_score(
        AttritionSignalInput(
            fine_count_recent_half=0,
            fine_count_prior_half=0,
            unauthorized_absences=0,
            tenure_months=1.0,
            leave_usage_ratio=0.0,
        ),
        weights,
    )
    veteran = calculate_attrition_score(
        AttritionSignalInput(
            fine_count_recent_half=0,
            fine_count_prior_half=0,
            unauthorized_absences=0,
            tenure_months=24.0,
            leave_usage_ratio=0.0,
        ),
        weights,
    )
    assert new_hire.score == pytest.approx(weights.new_hire_risk_points)
    assert veteran.score == 0.0


def test_tenure_months_returns_none_for_unknown_hire_date() -> None:
    assert tenure_months(None, date(2026, 8, 12)) is None


def test_tenure_months_clamps_future_hire_date_to_zero() -> None:
    assert tenure_months(date(2026, 9, 1), date(2026, 8, 12)) == 0.0


def test_high_risk_threshold_boundary() -> None:
    """Bal HƏDDİN tam üstündə YÜKSƏK, tam altında NORMAL sayılır."""
    weights = AttritionWeights(
        fine_trend_weight=1,
        attendance_violation_weight=1,
        new_hire_risk_points=0,
        new_hire_threshold_months=3,
        leave_usage_weight=0,
        window_months=3,
        high_risk_threshold=70,
    )
    at_threshold = calculate_attrition_score(
        AttritionSignalInput(
            fine_count_recent_half=70,
            fine_count_prior_half=0,
            unauthorized_absences=0,
            tenure_months=None,
            leave_usage_ratio=0.0,
        ),
        weights,
    )
    below_threshold = calculate_attrition_score(
        AttritionSignalInput(
            fine_count_recent_half=69,
            fine_count_prior_half=0,
            unauthorized_absences=0,
            tenure_months=None,
            leave_usage_ratio=0.0,
        ),
        weights,
    )
    assert at_threshold.score == 70.0
    assert at_threshold.is_high_risk is True
    assert below_threshold.score == 69.0
    assert below_threshold.is_high_risk is False


def test_attrition_risk_score_rejects_empty_factors() -> None:
    with pytest.raises(DomainRuleError):
        AttritionRiskScore(
            tenant_id=TENANT,
            employee_id=WORKER,
            score=10.0,
            factors={},
            score_date=date(2026, 8, 12),
            calculated_at=NOW,
        )


def test_attrition_risk_score_rejects_out_of_range_score() -> None:
    with pytest.raises(DomainRuleError):
        AttritionRiskScore(
            tenant_id=TENANT,
            employee_id=WORKER,
            score=101.0,
            factors={"FINE_TREND": {"bal": 101.0}},
            score_date=date(2026, 8, 12),
            calculated_at=NOW,
        )


def test_weights_defaults_match_the_limit_catalogue() -> None:
    """Defolt HARDCODE DEYİL — `DEFAULT_LIMITS`-dən gəlir."""
    defaults = AttritionWeights.defaults()
    assert defaults.fine_trend_weight == int(
        DEFAULT_LIMITS[SystemLimitKey.ATTRITION_FINE_TREND_WEIGHT]
    )
    assert defaults.high_risk_threshold == int(
        DEFAULT_LIMITS[SystemLimitKey.ATTRITION_HIGH_RISK_THRESHOLD]
    )


def test_weights_clamp_negative_values_to_zero() -> None:
    weights = AttritionWeights(
        fine_trend_weight=-5,
        attendance_violation_weight=-1,
        new_hire_risk_points=-1,
        new_hire_threshold_months=-1,
        leave_usage_weight=-1,
        window_months=-1,
        high_risk_threshold=-1,
    )
    assert weights.fine_trend_weight == 0
    assert weights.window_months == 1  # minimum 1 ay — 0 pəncərəni yox edərdi


# --------------------------------------------------------------------------- #
# 2. Use case — gecəlik hesablama
# --------------------------------------------------------------------------- #


def test_recalculate_all_reads_every_weight_from_system_limits() -> None:
    use_case, scores, _notifier, _audit, limits = build([make_signals()])
    use_case.recalculate_all(TENANT, now=NOW)

    for key in (
        SystemLimitKey.ATTRITION_FINE_TREND_WEIGHT.value,
        SystemLimitKey.ATTRITION_ATTENDANCE_VIOLATION_WEIGHT.value,
        SystemLimitKey.ATTRITION_NEW_HIRE_RISK_POINTS.value,
        SystemLimitKey.ATTRITION_NEW_HIRE_THRESHOLD_MONTHS.value,
        SystemLimitKey.ATTRITION_LEAVE_USAGE_WEIGHT.value,
        SystemLimitKey.ATTRITION_WINDOW_MONTHS.value,
        SystemLimitKey.ATTRITION_HIGH_RISK_THRESHOLD.value,
    ):
        assert key in limits.requested
    assert scores.get_latest_for_employee(TENANT, WORKER) is not None


def test_recalculate_all_zero_data_employee_gets_zero_score_and_no_notification() -> None:
    use_case, scores, notifier, _audit, _limits = build(
        [make_signals(hire_date=None, fine_recent=0, fine_prior=0, absences=0, leave_minutes=0)]
    )
    report = use_case.recalculate_all(TENANT, now=NOW)

    stored = scores.get_latest_for_employee(TENANT, WORKER)
    assert stored is not None
    assert stored.score == 0.0
    assert report.high_risk_count == 0
    assert notifier.messages == []


def test_recalculate_all_weight_override_changes_the_stored_score() -> None:
    default_use_case, default_scores, _n1, _a1, _l1 = build(
        [make_signals(fine_recent=5, fine_prior=2)]
    )
    default_use_case.recalculate_all(TENANT, now=NOW)

    overridden_use_case, overridden_scores, _n2, _a2, _l2 = build(
        [make_signals(fine_recent=5, fine_prior=2)],
        limits_values={SystemLimitKey.ATTRITION_FINE_TREND_WEIGHT.value: 50},
    )
    overridden_use_case.recalculate_all(TENANT, now=NOW)

    default_score = default_scores.get_latest_for_employee(TENANT, WORKER)
    overridden_score = overridden_scores.get_latest_for_employee(TENANT, WORKER)
    assert default_score is not None
    assert overridden_score is not None
    assert default_score.score != overridden_score.score


def test_recalculate_all_audits_once_per_run_not_once_per_employee() -> None:
    other_worker = EmployeeId(uuid.uuid4())
    use_case, _scores, _notifier, audit, _limits = build(
        [make_signals(employee_id=WORKER), make_signals(employee_id=other_worker)]
    )
    use_case.recalculate_all(TENANT, now=NOW)

    recalculation_entries = [
        e for e in audit.entries if e["action"] == "ATTRITION_SCORES_RECALCULATED"
    ]
    assert len(recalculation_entries) == 1
    assert recalculation_entries[0]["actor_id"] is None
    assert recalculation_entries[0]["after_state"]["yenilənən_işçi"] == 2


# --------------------------------------------------------------------------- #
# 3. Bildiriş ardıcıllığı — ƏVVƏLCƏ Store Manager, SONRA HR_Admin
# --------------------------------------------------------------------------- #


def _high_risk_signals() -> EmployeeAttritionSignals:
    # fine_trend_weight defolt 5, artım 20 → 100 bal (tavan) → hər zaman yüksək risk.
    return make_signals(fine_recent=20, fine_prior=0)


def _store_manager() -> Employee:
    manager_flags: list[PermissionFlag] = []
    position = make_position(
        SystemRole.STORE_MANAGER.value, priority=RolePriority.OPERATIONAL, flags=manager_flags
    )
    return make_employee(position=position, store_id=STORE)


def _hr_admin(*, with_flag: bool = True) -> Employee:
    flags = [PermissionFlag(code=VIEW_ATTRITION_RISK_FLAG, category="HR")] if with_flag else []
    position = make_position(
        SystemRole.HR_ADMIN.value, priority=RolePriority.OPERATIONAL, flags=flags
    )
    return make_employee(position=position, store_id=None)


def test_high_risk_notifies_store_manager_before_hr_admin() -> None:
    manager = _store_manager()
    use_case, _scores, notifier, _audit, _limits = build(
        [_high_risk_signals()], employees_by_store={STORE: [manager]}
    )
    report = use_case.recalculate_all(TENANT, now=NOW)

    assert report.high_risk_count == 1
    assert len(notifier.messages) == 2
    first, second = notifier.messages
    assert first["recipient_id"] == manager.id
    assert second["recipient_id"] is None
    assert first["category"] == ATTRITION_RISK_NOTIFICATION_CATEGORY
    assert second["category"] == ATTRITION_RISK_NOTIFICATION_CATEGORY


def test_high_risk_without_store_manager_still_notifies_hr_admin() -> None:
    """`store_id=None` (mağazasız işçi) — YALNIZ HR_Admin bildirişi gedir."""
    signals = make_signals(store_id=None, fine_recent=20, fine_prior=0)
    use_case, _scores, notifier, _audit, _limits = build([signals])
    use_case.recalculate_all(TENANT, now=NOW)

    assert len(notifier.messages) == 1
    assert notifier.messages[0]["recipient_id"] is None


def test_repeated_high_risk_does_not_notify_twice() -> None:
    """Eyni işçi ARDICIL iki gecə YÜKSƏK RİSKDƏ qalsa, İKİNCİ dəfə bildiriş getmir."""
    manager = _store_manager()
    use_case, _scores, notifier, _audit, _limits = build(
        [_high_risk_signals()], employees_by_store={STORE: [manager]}
    )
    use_case.recalculate_all(TENANT, now=NOW)
    assert len(notifier.messages) == 2

    # EYNİ gün təkrar icra (məs. manual "indi hesabla") — vəziyyət DƏYİŞMƏYİB.
    use_case.recalculate_all(TENANT, now=NOW)
    assert len(notifier.messages) == 2, "Təkrar bildiriş göndərilməməli idi"


def test_score_dropping_below_threshold_then_rising_again_notifies_again() -> None:
    """Risk aşağı düşüb YENİDƏN qalxanda bildiriş YENİDƏN göndərilir.

    ÜÇ GÜN ÜÇÜN ÜÇ AYRI use case QURULUR (hər gün öz `AttritionSignalProvider`
    məlumatını gətirir — canlı sistemdə bu, sadəcə fərqli günün SQL nəticəsidir),
    lakin `scores`/`notifier`/`employees` YADDAŞLARI PAYLAŞILIR ki, "dünənki
    bilinən vəziyyət" real ssenarini əks etdirsin.
    """
    manager = _store_manager()
    scores = FakeScores()
    notifier = RecordingNotifier()
    audit = RecordingAudit()
    limits = FakeLimits()
    employees = FakeEmployees(by_store={STORE: [manager]})

    def run(rows: list[EmployeeAttritionSignals], moment: datetime) -> None:
        use_case = AttritionRiskUseCase(
            signals=FakeSignals(rows),
            scores=scores,
            employees=employees,
            limits=limits,
            audit=audit,
            clock=FakeClock(moment),
            notifier=notifier,
        )
        use_case.recalculate_all(TENANT, now=moment)

    day1 = NOW
    day2 = datetime(2026, 8, 13, 3, 0, tzinfo=UTC)
    day3 = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)

    run([_high_risk_signals()], day1)
    assert len(notifier.messages) == 2, "1-ci gün: ilk dəfə yüksək risk — bildiriş gedir"

    run([make_signals(fine_recent=0, fine_prior=0)], day2)
    assert len(notifier.messages) == 2, "2-ci gün: risk normala düşüb — bildiriş YOXDUR"

    run([_high_risk_signals()], day3)
    assert len(notifier.messages) == 4, "3-cü gün: YENİDƏN yüksəlib — bildiriş TƏKRAR gedir"


# --------------------------------------------------------------------------- #
# 4. Oxu yolu — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI"
# --------------------------------------------------------------------------- #


def test_list_for_tenant_requires_the_permission_flag() -> None:
    use_case, _scores, _notifier, _audit, _limits = build([make_signals()])
    use_case.recalculate_all(TENANT, now=NOW)

    actor_without_flag = _hr_admin(with_flag=False)
    with pytest.raises(AuthorizationError):
        use_case.list_for_tenant(tenant_id=TENANT, actor=actor_without_flag)


def test_list_for_tenant_succeeds_and_audits_the_view() -> None:
    use_case, _scores, _notifier, audit, _limits = build([make_signals(fine_recent=20)])
    use_case.recalculate_all(TENANT, now=NOW)

    actor = _hr_admin(with_flag=True)
    views = use_case.list_for_tenant(tenant_id=TENANT, actor=actor)

    assert len(views) == 1
    assert views[0].employee_id == WORKER
    view_entries = [e for e in audit.entries if e["action"] == "ATTRITION_RISK_VIEWED"]
    assert len(view_entries) == 1
    assert view_entries[0]["actor_id"] == actor.id


def test_list_for_tenant_band_reflects_the_current_threshold() -> None:
    """Bant SAXLANILMIR — oxuma anında CARİ hədlə hesablanır."""
    use_case, _scores, _notifier, _audit, limits = build([make_signals(fine_recent=20)])
    use_case.recalculate_all(TENANT, now=NOW)

    actor = _hr_admin(with_flag=True)
    strict_views = use_case.list_for_tenant(tenant_id=TENANT, actor=actor)
    assert strict_views[0].is_high_risk is True

    limits._values[SystemLimitKey.ATTRITION_HIGH_RISK_THRESHOLD.value] = 1000
    lenient_views = use_case.list_for_tenant(tenant_id=TENANT, actor=actor)
    assert lenient_views[0].is_high_risk is False


# --------------------------------------------------------------------------- #
# 5. 1C SƏRHƏDİ — statik qapı
# --------------------------------------------------------------------------- #

#: Kod mətnində görünməsi struktur qərar D-nin pozulması demək olan adlar.
_FORBIDDEN_1C_TOKENS: Final[tuple[str, ...]] = (
    "SalesDataConnector",
    "OneCSaleRecord",
    "ErpServer",
    "SyncCursor",
    "erp_servers",
    "sales_transactions",
)


@pytest.mark.parametrize("path", [_USE_CASE_PATH, _REPO_PATH], ids=lambda p: p.name)
def test_the_module_never_imports_anything_from_the_1c_layer(path: Path) -> None:
    """#21 mənbəyi YALNIZ KompasOS-un öz cərimə/davamiyyət/icazə datasıdır."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    leaking = sorted(name for name in imported if "erp" in name or "sales" in name)
    assert not leaking, f"#21 1C qatına bağlandı: {leaking}"


@pytest.mark.parametrize("path", [_USE_CASE_PATH, _REPO_PATH], ids=lambda p: p.name)
def test_the_module_body_has_no_1c_identifiers(path: Path) -> None:
    """İdxalsız da olsa 1C adının işlədilməsi qərarı sükutla geri alardı.

    Şərhlər DAXİLDİR — modul başlığında bu adlar "İŞLƏDİLMİR" cümləsinin
    içində keçdiyi üçün yoxlama YALNIZ icra olunan koda tətbiq edilir.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)

    hits = sorted(token for token in _FORBIDDEN_1C_TOKENS if token in names)
    assert not hits, f"#21 kodunda 1C izi: {hits}"
