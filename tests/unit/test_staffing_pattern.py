"""Tarixi-nümunə əsaslı kadr təklifinin testləri (#13, Faza 6).

──────────────────────────────────────────────────────────────────────────────
BİRİNCİ QAPI: 1C-YƏ TOXUNMAMAQ
──────────────────────────────────────────────────────────────────────────────
kompasos11.md struktur qərar D-nin pozulması KOMPİLYASİYA XƏTASI VERMİR: kimsə
sabah `SalesDataConnector`-u bu use case-ə asılılıq kimi əlavə etsə, hər şey
işləməyə davam edərdi və qərar sükutla geri alınmış olardı. Ona görə burada
statik (`ast`) qapı var — modul mətnində 1C/ERP izinin olmaması təsbit edilir.

Sahtələr YERLİdir (`tests/fixtures/fakes.py` toxunulmur) — bax
`test_labor_rules.py` başlığındakı eyni əsaslandırma.
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases.staffing_pattern import StaffingPatternUseCase
from src.domain.entities.base import DomainRuleError
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import StoreId, TenantId
from src.domain.value_objects.staffing_signals import (
    StaffingPatternSuggestion,
    StoreDayHeadcount,
    weekday_name_az,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())

#: 2026-08-12 çərşənbədir; pəncərə DÜNƏNlə (11 avqust) bitir.
NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)

_USE_CASE_PATH: Final = (
    Path(__file__).resolve().parents[2] / "src/application/use_cases/staffing_pattern.py"
)
_REPO_PATH: Final = (
    Path(__file__).resolve().parents[2] / "src/infrastructure/persistence/staffing_repositories.py"
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
    def __init__(self, values: dict[str, int] | None = None) -> None:
        self._values = values or {}
        self.requested: list[str] = []

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        self.requested.append(key)
        return self._values.get(key, default)

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return default

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return {}


class FakeHistory:
    """`StaffingHistoryProvider` — verilmiş günləri geri qaytarır."""

    def __init__(self, observations: list[StoreDayHeadcount]) -> None:
        self._observations = observations
        self.calls: list[tuple[StoreId, date, date]] = []

    def headcount_by_day(
        self, tenant_id: TenantId, *, store_id: StoreId, since: date, until: date
    ) -> list[StoreDayHeadcount]:
        self.calls.append((store_id, since, until))
        return [item for item in self._observations if since <= item.work_date <= until]


class InMemorySuggestions:
    """`StaffingPatternRepository` — UPSERT davranışını təkrarlayır."""

    def __init__(self) -> None:
        self.rows: dict[tuple[StoreId, int], StaffingPatternSuggestion] = {}

    def list_for_store(
        self, tenant_id: TenantId, store_id: StoreId
    ) -> list[StaffingPatternSuggestion]:
        return [row for (store, _), row in self.rows.items() if store == store_id]

    def save(self, suggestion: StaffingPatternSuggestion) -> None:
        self.rows[(suggestion.store_id, suggestion.weekday)] = suggestion


def build(
    observations: list[StoreDayHeadcount],
    *,
    limits: FakeLimits | None = None,
) -> tuple[StaffingPatternUseCase, InMemorySuggestions, FakeHistory]:
    history = FakeHistory(observations)
    suggestions = InMemorySuggestions()
    use_case = StaffingPatternUseCase(
        history=history,
        suggestions=suggestions,
        limits=limits or FakeLimits(),
        clock=FakeClock(),
    )
    return use_case, suggestions, history


def wednesdays(counts: list[int]) -> list[StoreDayHeadcount]:
    """Ardıcıl çərşənbələr (7 gün geriyə addımlarla), ən yenisi 2026-08-05."""
    start = date(2026, 8, 5)
    return [
        StoreDayHeadcount(
            work_date=date.fromordinal(start.toordinal() - 7 * index),
            headcount=count,
        )
        for index, count in enumerate(counts)
    ]


# --------------------------------------------------------------------------- #
# 1. Hesablama
# --------------------------------------------------------------------------- #


def test_the_average_is_written_per_iso_weekday() -> None:
    use_case, suggestions, _ = build(wednesdays([2, 3, 3, 2]))
    report = use_case.recalculate_for_store(TENANT, store_id=STORE)

    assert report.weekdays_updated == 1
    row = suggestions.rows[(STORE, 3)]  # 3 = Çərşənbə (ISO)
    assert row.avg_historical_headcount == 2.5
    assert row.weekday_label_az == "Çərşənbə"


def test_a_fractional_average_is_kept_to_two_decimals() -> None:
    """migrations/019: "8 həftənin 3-ündə 2, 5-ində 3 nəfər → 2.63"."""
    use_case, suggestions, _ = build(wednesdays([2, 2, 2, 3, 3, 3, 3, 3]))
    use_case.recalculate_for_store(TENANT, store_id=STORE)
    assert suggestions.rows[(STORE, 3)].avg_historical_headcount == 2.63


def test_the_window_ends_yesterday_and_spans_root_weeks() -> None:
    """Bugünkü yarımçıq gün ortanı aşağı çəkməməlidir."""
    use_case, _, history = build([])
    report = use_case.recalculate_for_store(TENANT, store_id=STORE)

    store_id, since, until = history.calls[0]
    assert store_id == STORE
    assert until == date(2026, 8, 11), "Pəncərə DÜNƏNlə bitməlidir"
    assert (until - since).days + 1 == report.based_on_weeks * 7


def test_the_window_length_comes_from_system_limits() -> None:
    limits = FakeLimits({SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS.value: 3})
    use_case, suggestions, history = build(wednesdays([2, 2]), limits=limits)
    report = use_case.recalculate_for_store(TENANT, store_id=STORE)

    assert SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS.value in limits.requested
    assert report.based_on_weeks == 3
    _, since, until = history.calls[0]
    assert (until - since).days + 1 == 21
    assert suggestions.rows[(STORE, 3)].based_on_weeks == 3


def test_the_default_window_matches_the_limit_catalogue() -> None:
    """Defolt HARDCODE DEYİL — `DEFAULT_LIMITS`-dən gəlir."""
    use_case, _, _ = build([])
    report = use_case.recalculate_for_store(TENANT, store_id=STORE)
    assert report.based_on_weeks == int(
        DEFAULT_LIMITS[SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS]
    )


def test_days_without_observations_are_not_counted_as_zero() -> None:
    """Bağlı bazar günü "0 işçi lazımdır" demək deyil — sətir YARANMIR."""
    use_case, suggestions, _ = build(wednesdays([2, 2]))
    use_case.recalculate_for_store(TENANT, store_id=STORE)

    assert set(suggestions.rows) == {(STORE, 3)}
    assert all(weekday == 3 for _, weekday in suggestions.rows)


def test_observations_outside_the_window_are_ignored() -> None:
    """Pəncərədən kənar (yarım il əvvəlki) gün ortaya qatılmır."""
    inside = StoreDayHeadcount(work_date=date(2026, 8, 5), headcount=2)
    outside = StoreDayHeadcount(work_date=date(2026, 2, 4), headcount=99)
    use_case, suggestions, _ = build([inside, outside])
    use_case.recalculate_for_store(TENANT, store_id=STORE)
    assert suggestions.rows[(STORE, 3)].avg_historical_headcount == 2.0


def test_recalculation_is_an_upsert_not_an_append() -> None:
    """Eyni mağaza + həftə günü = BİR sətir (DB `UNIQUE` güzgüsü)."""
    use_case, suggestions, _ = build(wednesdays([2, 4]))
    use_case.recalculate_for_store(TENANT, store_id=STORE)
    use_case.recalculate_for_store(TENANT, store_id=STORE)
    assert len(suggestions.rows) == 1


def test_a_clock_override_keeps_the_calculation_deterministic() -> None:
    """`datetime.now()` ÇAĞIRILMIR — `Clock` portu / açıq `now` işlədilir."""
    use_case, suggestions, _ = build(wednesdays([2]))
    frozen = datetime(2026, 8, 12, 23, 59, tzinfo=UTC)
    use_case.recalculate_for_store(TENANT, store_id=STORE, now=frozen)
    assert suggestions.rows[(STORE, 3)].calculated_at == frozen


def test_an_empty_history_writes_nothing_and_says_so() -> None:
    use_case, suggestions, _ = build([])
    report = use_case.recalculate_for_store(TENANT, store_id=STORE)
    assert suggestions.rows == {}
    assert (report.weekdays_updated, report.observed_days) == (0, 0)


# --------------------------------------------------------------------------- #
# 2. Oxu yolu
# --------------------------------------------------------------------------- #


def test_suggestions_are_sorted_monday_first() -> None:
    """Maket və canlı yol eyni ardıcıllığı göstərməlidir."""
    use_case, suggestions, _ = build([])
    for weekday in (7, 3, 1):
        suggestions.save(
            StaffingPatternSuggestion(
                tenant_id=TENANT,
                store_id=STORE,
                weekday=weekday,
                avg_historical_headcount=2.0,
                based_on_weeks=8,
                calculated_at=NOW,
            )
        )
    ordered = use_case.suggestions_for(TENANT, store_id=STORE)
    assert [item.weekday for item in ordered] == [1, 3, 7]


def test_another_stores_rows_are_not_returned() -> None:
    use_case, suggestions, _ = build([])
    suggestions.save(
        StaffingPatternSuggestion(
            tenant_id=TENANT,
            store_id=OTHER_STORE,
            weekday=1,
            avg_historical_headcount=9.0,
            based_on_weeks=8,
            calculated_at=NOW,
        )
    )
    assert use_case.suggestions_for(TENANT, store_id=STORE) == []


# --------------------------------------------------------------------------- #
# 3. Domen tipi — DB CHECK-lərinin güzgüsü
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("weekday", [0, 8, -1])
def test_an_out_of_range_weekday_is_rejected(weekday: int) -> None:
    with pytest.raises(DomainRuleError):
        StaffingPatternSuggestion(
            tenant_id=TENANT,
            store_id=STORE,
            weekday=weekday,
            avg_historical_headcount=1.0,
            based_on_weeks=8,
            calculated_at=NOW,
        )


def test_a_naive_calculation_timestamp_is_rejected() -> None:
    """CLAUDE.md §4: bütün `datetime` tz-aware olmalıdır."""
    with pytest.raises(Exception, match=r"naive|zona"):
        StaffingPatternSuggestion(
            tenant_id=TENANT,
            store_id=STORE,
            weekday=1,
            avg_historical_headcount=1.0,
            based_on_weeks=8,
            calculated_at=datetime(2026, 8, 12, 3, 0),  # noqa: DTZ001 — qəsdən naive
        )


def test_a_zero_week_window_is_rejected() -> None:
    """DB `CHECK (based_on_weeks > 0)` güzgüsü."""
    with pytest.raises(DomainRuleError):
        StaffingPatternSuggestion(
            tenant_id=TENANT,
            store_id=STORE,
            weekday=1,
            avg_historical_headcount=1.0,
            based_on_weeks=0,
            calculated_at=NOW,
        )


def test_a_negative_headcount_is_rejected() -> None:
    with pytest.raises(DomainRuleError):
        StoreDayHeadcount(work_date=date(2026, 8, 5), headcount=-1)


def test_the_iso_weekday_names_match_python_isoweekday() -> None:
    """1 = Bazar ertəsi … 7 = Bazar (migrations/019 konvensiyası).

    `date.weekday()` (0 = B.e) ilə qarışdırmaq klassik "bir gün sürüşmə"
    qüsurudur — bu test onu təsbit edir.
    """
    monday = date(2026, 8, 17)
    assert monday.isoweekday() == 1
    assert weekday_name_az(monday.isoweekday()) == "Bazar ertəsi"
    assert weekday_name_az(date(2026, 8, 23).isoweekday()) == "Bazar"


def test_an_unknown_weekday_name_is_rejected() -> None:
    with pytest.raises(DomainRuleError):
        weekday_name_az(0)


def test_the_headcount_label_rounds_to_one_decimal() -> None:
    """ "2.63 nəfər" saxta dəqiqlik təəssüratı yaradardı."""
    suggestion = StaffingPatternSuggestion(
        tenant_id=TENANT,
        store_id=STORE,
        weekday=3,
        avg_historical_headcount=2.63,
        based_on_weeks=8,
        calculated_at=NOW,
    )
    assert suggestion.headcount_label_az() == "2.6 nəfər"


# --------------------------------------------------------------------------- #
# 4. 1C SƏRHƏDİ — statik qapı
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
    """#13 mənbəyi YALNIZ KompasOS davamiyyətidir (struktur qərar D)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    leaking = sorted(name for name in imported if "erp" in name or "sales" in name)
    assert not leaking, f"#13 1C qatına bağlandı: {leaking}"


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
    assert not hits, f"#13 kodunda 1C izi: {hits}"
