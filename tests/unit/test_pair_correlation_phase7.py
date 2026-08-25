"""İki-nəfərlik fırıldaqçılıq aşkarlaması — `v2backlog.md` Faza 7.

Hər test qaydanın BİR iddiasını sınayır:

  * sinxron cüt tapıntı verir; kontekstdə cütün İKİ tərəfi də var;
  * hədd Root açarından oxunur (limit lüğəti davranışı dəyişir);
  * az nümunə (min_shared_days) və fərqli-mağaza günləri sayılmır;
  * bugünkü natamam gün pəncərəyə DÜŞMÜR (#8 ilə eyni pəncərə qaydası).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.application.use_cases.pair_correlation import PairBehaviorCorrelationRule
from src.domain.value_objects.behavior_signals import CheckInObservation
from src.domain.value_objects.exception_signals import (
    BEHAVIOR_PAIR_SOURCE,
    ExceptionFinding,
    RuleEvaluationContext,
)
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
STORE_B = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
TZ = "Asia/Baku"
# Pəncərə as_of=25 avqust üçün [26 iyul .. 24 avqust]-dur — nümunə günləri
# BU aralıqda olmalıdır, əks halda qayda onları onsuz da süzgücləyir.
FIRST_DAY = date(2026, 8, 10)


def _emp() -> EmployeeId:
    return EmployeeId(uuid.uuid4())


def _day(offset: int) -> date:
    return FIRST_DAY + timedelta(days=offset)


def _obs(
    employee_id: EmployeeId, day: date, hour: int, store: StoreId = STORE
) -> CheckInObservation:
    return CheckInObservation(
        employee_id=employee_id,
        store_id=store,
        checked_in_at=datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC),
        store_timezone=TZ,
    )


class _Reader:
    def __init__(self, *observations: CheckInObservation) -> None:
        self.observations = list(observations)

    def list_checkins(
        self, tenant_id: TenantId, *, since: date, until: date
    ) -> list[CheckInObservation]:
        assert tenant_id == TENANT
        return [obs for obs in self.observations if since <= obs.checked_in_at.date() <= until]


def _rule(reader: _Reader) -> PairBehaviorCorrelationRule:
    return PairBehaviorCorrelationRule(checkins=reader)  # type: ignore[arg-type]


def _context(limits: dict[str, str] | None = None) -> RuleEvaluationContext:
    base = {
        "BEHAVIOR_PAIR_CORRELATION_THRESHOLD": "90",
        "BEHAVIOR_PAIR_MIN_SHARED_DAYS": "3",
        "BEHAVIOR_PAIR_SYNC_MINUTES": "5",
        "BEHAVIOR_BASELINE_WINDOW_DAYS": "30",
    }
    if limits:
        base.update(limits)
    return RuleEvaluationContext(tenant_id=TENANT, as_of=NOW, limits=base)


def test_synchronized_pair_produces_a_finding() -> None:
    """10 ortaq günün hamısında eyni saatda giriş → TƏK tapıntı."""
    left, right = _emp(), _emp()
    observations: list[CheckInObservation] = []
    for offset in range(10):
        observations.append(_obs(left, _day(offset), 6))
        observations.append(_obs(right, _day(offset), 6))

    findings = _rule(_Reader(*observations)).evaluate(_context())

    assert len(findings) == 1
    finding: ExceptionFinding = findings[0]
    assert _rule(_Reader(*observations)).source_code == BEHAVIOR_PAIR_SOURCE
    # Kiçik-ID subyektdir, böyüyü kontekst cütündədir — hər iki tərəf izlənilir.
    assert {str(finding.employee_id), str(finding.context["pair_employee_id"])} == {
        str(left),
        str(right),
    }
    assert NOW.date().isoformat() in (finding.dedupe_key or "")
    assert finding.store_id == STORE


def test_below_threshold_pair_is_not_flagged() -> None:
    """Cütdən yalnız 50% sinxron günlər — adi həmkarlar, tapıntı YOX."""
    left, right = _emp(), _emp()
    observations: list[Any] = []
    for offset in range(10):
        late_hour = 6 if offset < 5 else 14  # son 5 gün 8 saat fərqlidir
        observations.append(_obs(left, _day(offset), 6))
        observations.append(_obs(right, _day(offset), late_hour))

    assert _rule(_Reader(*observations)).evaluate(_context()) == []


def test_different_store_days_do_not_count_as_shared() -> None:
    """Hər gün FƏRQLİ mağazalarda üst-üstə düşmə «eyni növbə» deyil."""
    left, right = _emp(), _emp()
    observations: list[Any] = []
    for offset in range(10):
        observations.append(_obs(left, _day(offset), 6, store=STORE))
        observations.append(_obs(right, _day(offset), 6, store=STORE_B))

    assert _rule(_Reader(*observations)).evaluate(_context()) == []


def test_min_sample_limit_blocks_small_pairs() -> None:
    """2 ortaq gün < min_shared_days=3 — az nümunədən ittiham çıxmır."""
    left, right = _emp(), _emp()
    observations: list[CheckInObservation] = []
    for offset in range(2):
        observations.append(_obs(left, _day(offset), 6))
        observations.append(_obs(right, _day(offset), 6))

    assert _rule(_Reader(*observations)).evaluate(_context()) == []


def test_root_threshold_key_drives_the_behaviour() -> None:
    """Eyni data, FƏRQLİ hədd: Root açarı nəticəni DƏYİŞDİRİR (ROOT PARAMETRİ)."""
    left, right = _emp(), _emp()
    observations: list[Any] = []
    for offset in range(10):
        late_hour = 6 if offset < 5 else 14  # 50% sinxron
        observations.append(_obs(left, _day(offset), 6))
        observations.append(_obs(right, _day(offset), late_hour))
    reader = _Reader(*observations)

    assert _rule(reader).evaluate(_context({"BEHAVIOR_PAIR_CORRELATION_THRESHOLD": "40"})) != []
    assert _rule(reader).evaluate(_context({"BEHAVIOR_PAIR_CORRELATION_THRESHOLD": "90"})) == []


def test_today_is_excluded_from_the_window() -> None:
    """Bugünkü natamam gün statistikaya DÜŞMÜR — pəncərə dünənlə bitir."""
    left, right = _emp(), _emp()
    yesterday = NOW.date() - timedelta(days=1)
    observations = [
        *[_obs(left, yesterday, 6), _obs(right, yesterday, 6)],
        # Yalnız BUGÜN sinxron girişlər — pəncərə onsuz da bugünü ehtiva etmir.
        *[_obs(left, NOW.date(), 6), _obs(right, NOW.date(), 6)],
    ]

    # 1 ortaq gün (dünən) < min_shared_days=3 → boş; bugünkü gün heç hesaba katılmır.
    assert _rule(_Reader(*observations)).evaluate(_context()) == []


def test_single_employee_never_produces_findings() -> None:
    solo = _emp()

    assert _rule(_Reader(_obs(solo, FIRST_DAY, 6))).evaluate(_context()) == []
