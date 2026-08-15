"""Çox-Mağaza Benchmark Dashboard testləri (#24, kompasos11.md Faza 9A).

──────────────────────────────────────────────────────────────────────────────
BİRİNCİ QAPI: 1C-YƏ TOXUNMAMAQ
──────────────────────────────────────────────────────────────────────────────
`test_attrition_risk.py` (#21) ilə EYNİ statik (`ast`) qapı: kimsə sabah
`SalesDataConnector`-u bu modullara asılılıq kimi əlavə etsə, kompilyasiya
xətası VERMƏZ və qərar sükutla geri alınmış olardı.

Sahtələr YERLİdir (`tests/fixtures/fakes.py` toxunulmur) — `test_attrition_
risk.py`/`test_staffing_pattern.py` başlıqlarındakı eyni əsaslandırma: bu
fayl paralel işləyən başqa fazaların sahtə dəstindən asılı olmamalıdır.
"""

from __future__ import annotations

import ast
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from src.application.use_cases.dashboard_layout import (
    WIDGET_CATALOG,
    DashboardLayoutUseCase,
)
from src.application.use_cases.multi_store_benchmark import (
    VIEW_BENCHMARK_FLAG,
    BenchmarkMetric,
    MultiStoreBenchmarkUseCase,
    TrendDirection,
    format_metric_value,
)
from src.domain.entities.attendance_sheet import AutoAttendanceStatus
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
from src.presentation.controllers.screen_data import (
    ScreenDataBinder,
    perform_ranking_drill_down,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE_A = StoreId(uuid.uuid4())
STORE_B = StoreId(uuid.uuid4())
STORE_C = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)

_USE_CASE_PATH: Final = (
    Path(__file__).resolve().parents[2] / "src/application/use_cases/multi_store_benchmark.py"
)
_REPO_PATH: Final = (
    Path(__file__).resolve().parents[2] / "src/infrastructure/persistence/benchmark_repository.py"
)

_BENCHMARK_WIDGET_KEYS: Final = (
    "ranking_table",
    "store_vs_network",
    "metric_trend",
    "benchmark_outliers",
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

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return int(self._values.get(key, default))

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return str(self._values.get(key, default))

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)

    def set_value(self, tenant_id: TenantId, key: str, value: str, *, changed_by: Any) -> None:
        self._values[key] = value

    def describe(self, tenant_id: TenantId) -> list[dict[str, object]]:
        return []


class FakeProvider:
    """`MultiStoreMetricProvider` — ay-başına sabit lüğətlərdən oxuyur."""

    def __init__(
        self,
        *,
        stores: dict[StoreId, str],
        monthly_values: dict[BenchmarkMetric, dict[date, dict[StoreId, float]]],
    ) -> None:
        self._stores = stores
        self._monthly_values = monthly_values
        self.calls: list[tuple[BenchmarkMetric, date, date]] = []

    def active_stores(self, tenant_id: TenantId) -> dict[StoreId, str]:
        return dict(self._stores)

    def metric_values(
        self, tenant_id: TenantId, metric: BenchmarkMetric, *, start: date, end: date
    ) -> dict[StoreId, float]:
        self.calls.append((metric, start, end))
        return dict(self._monthly_values.get(metric, {}).get(start, {}))


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


def make_employee(*, position: Position, store_id: StoreId | None = None) -> Employee:
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Ad",
        last_name="Soyad",
        store_id=store_id,
        has_pin=True,
    )


def _with_flag(role_code: str, *, priority: RolePriority) -> Employee:
    flags = [PermissionFlag(code=VIEW_BENCHMARK_FLAG, category="SISTEM")]
    return make_employee(position=make_position(role_code, priority=priority, flags=flags))


def _root() -> Employee:
    return _with_flag(SystemRole.ROOT.value, priority=RolePriority.ROOT)


def _ceo() -> Employee:
    return _with_flag(SystemRole.CEO.value, priority=RolePriority.EXECUTIVE)


def _admin() -> Employee:
    return _with_flag(SystemRole.ADMIN.value, priority=RolePriority.ADMIN)


def _hr_admin() -> Employee:
    return _with_flag(SystemRole.HR_ADMIN.value, priority=RolePriority.OPERATIONAL)


def _store_manager() -> Employee:
    """`can_export_reports` YOXDUR — `schema.sql` §23 rol-defolt cədvəlinə uyğun."""
    position = make_position(
        SystemRole.STORE_MANAGER.value, priority=RolePriority.OPERATIONAL, flags=[]
    )
    return make_employee(position=position, store_id=STORE_A)


_NETWORK_WIDE_ACTORS: Final = (_root, _ceo, _admin, _hr_admin)


def _provider_for_ranking() -> FakeProvider:
    stores = {STORE_A: "28 May", STORE_B: "Gəncə", STORE_C: "Sumqayıt"}
    current_month = date(2026, 8, 1)
    previous_month = date(2026, 7, 1)
    return FakeProvider(
        stores=stores,
        monthly_values={
            BenchmarkMetric.FINE_COUNT: {
                current_month: {STORE_A: 2.0, STORE_B: 7.0, STORE_C: 4.0},
                previous_month: {STORE_A: 5.0, STORE_B: 7.0, STORE_C: 1.0},
            },
        },
    )


# --------------------------------------------------------------------------- #
# 1. Dashboard Builder qeydiyyatı — 4 widget
# --------------------------------------------------------------------------- #


def test_widget_catalog_registers_all_four_benchmark_widgets() -> None:
    catalog_keys = {widget.key for widget in WIDGET_CATALOG}
    for key in _BENCHMARK_WIDGET_KEYS:
        assert key in catalog_keys


def test_widget_catalog_scopes_benchmark_widgets_to_can_export_reports() -> None:
    by_key = {widget.key: widget for widget in WIDGET_CATALOG}
    for key in _BENCHMARK_WIDGET_KEYS:
        assert by_key[key].required_flag == "can_export_reports"


@pytest.mark.parametrize("actor_factory", _NETWORK_WIDE_ACTORS)
def test_network_wide_roles_see_benchmark_widgets_in_catalog(actor_factory: Any) -> None:
    by_key = {widget.key: widget for widget in WIDGET_CATALOG}
    actor = actor_factory()
    for key in _BENCHMARK_WIDGET_KEYS:
        assert by_key[key].is_visible_to(actor, now=NOW) is True


def test_store_manager_does_not_see_benchmark_widgets_in_catalog() -> None:
    by_key = {widget.key: widget for widget in WIDGET_CATALOG}
    manager = _store_manager()
    for key in _BENCHMARK_WIDGET_KEYS:
        assert by_key[key].is_visible_to(manager, now=NOW) is False


class _FakeLayoutStore:
    """`DashboardLayoutStore` — heç vaxt saxlanmayıb (`None`)."""

    def load(self, employee_id: EmployeeId) -> list[str] | None:
        return None

    def save(self, employee_id: EmployeeId, layout: list[str]) -> None:  # pragma: no cover
        raise AssertionError("bu testdə çağırılmamalıdır")


def test_dashboard_builder_view_excludes_benchmark_for_store_manager_includes_for_root() -> None:
    """Bölmə 3: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" — Panel Qurucusunun ÖZÜ süzülür.

    `DashboardLayoutUseCase.view_for` MƏHZ Panel Qurucusunun oxuduğu funksiyadır
    (bax `controllers/dashboard_builder.py`) — Mağaza_Meneceri widget-i
    seçim siyahısında GÖRMƏMƏLİDİR, yalnız render zamanı gizlənməməlidir.
    """
    use_case = DashboardLayoutUseCase(store=_FakeLayoutStore(), clock=FakeClock())

    manager_view = use_case.view_for(actor=_store_manager(), tenant_id=TENANT)
    manager_keys = {widget.key for widget in manager_view.available}
    for key in _BENCHMARK_WIDGET_KEYS:
        assert key not in manager_keys

    root_view = use_case.view_for(actor=_root(), tenant_id=TENANT)
    root_keys = {widget.key for widget in root_view.available}
    for key in _BENCHMARK_WIDGET_KEYS:
        assert key in root_keys


# --------------------------------------------------------------------------- #
# 2. Reytinq Cədvəli — istiqamət + trend oxu
# --------------------------------------------------------------------------- #


def test_ranking_direction_depends_on_metric_definition_not_hardcoded_branch() -> None:
    """Eyni RƏQƏMLƏR, İKİ FƏRQLİ metrik — sıra TAM TƏRSİNƏ çevrilməlidir.

    Bu, `if metric == ...` zənciri OLMADIĞINI sübut edir: istiqamət YALNIZ
    `BenchmarkMetric.lower_is_better`-dən gəlir.
    """
    stores = {STORE_A: "A-Store", STORE_B: "B-Store", STORE_C: "C-Store"}
    current = date(2026, 8, 1)
    values = {STORE_A: 10.0, STORE_B: 20.0, STORE_C: 30.0}
    provider = FakeProvider(
        stores=stores,
        monthly_values={
            BenchmarkMetric.FINE_COUNT: {current: dict(values), date(2026, 7, 1): dict(values)},
            BenchmarkMetric.ATTENDANCE_RATE: {
                current: dict(values),
                date(2026, 7, 1): dict(values),
            },
        },
    )
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())

    lower_is_better = use_case.ranking(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    higher_is_better = use_case.ranking(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.ATTENDANCE_RATE, now=NOW
    )

    assert [row.store_id for row in lower_is_better] == [STORE_A, STORE_B, STORE_C]
    assert [row.store_id for row in higher_is_better] == [STORE_C, STORE_B, STORE_A]
    assert [row.rank for row in lower_is_better] == [1, 2, 3]


def test_ranking_trend_arrow_carries_text_not_only_color() -> None:
    provider = _provider_for_ranking()
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    rows = use_case.ranking(
        tenant_id=TENANT, actor=_hr_admin(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    by_store = {row.store_id: row for row in rows}

    assert by_store[STORE_A].trend is TrendDirection.DOWN  # 2 < 5 (ötən ay)
    assert by_store[STORE_A].trend.label_az == "azalıb"
    assert by_store[STORE_C].trend is TrendDirection.UP  # 4 > 1
    assert by_store[STORE_B].trend is TrendDirection.FLAT  # 7 == 7
    # Oxun ÖZÜ də var — YALNIZ rənglə fərqlənmir (kompasos11.md #24).
    assert by_store[STORE_A].trend.arrow == "↓"


def test_ranking_excludes_stores_missing_from_active_catalog() -> None:
    """Bağlanmış (deaktiv) mağazanın köhnə qeydi reytinqi TƏHRİF ETMİR."""
    stale_store = StoreId(uuid.uuid4())
    provider = FakeProvider(
        stores={STORE_A: "28 May"},
        monthly_values={
            BenchmarkMetric.FINE_COUNT: {
                date(2026, 8, 1): {STORE_A: 3.0, stale_store: 99.0},
                date(2026, 7, 1): {},
            }
        },
    )
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    rows = use_case.ranking(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert [row.store_id for row in rows] == [STORE_A]


# --------------------------------------------------------------------------- #
# 3. Mağaza vs Şəbəkə Ortalaması
# --------------------------------------------------------------------------- #


def test_store_vs_network_computes_average_and_handles_missing_store() -> None:
    provider = _provider_for_ranking()
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())

    view = use_case.store_vs_network(
        tenant_id=TENANT,
        actor=_admin(),
        metric=BenchmarkMetric.FINE_COUNT,
        store_id=STORE_A,
        now=NOW,
    )
    assert view.store_value == 2.0
    assert view.network_average == pytest.approx((2.0 + 7.0 + 4.0) / 3)
    assert view.network_store_count == 3

    missing_store = StoreId(uuid.uuid4())
    empty_view = use_case.store_vs_network(
        tenant_id=TENANT,
        actor=_admin(),
        metric=BenchmarkMetric.FINE_COUNT,
        store_id=missing_store,
        now=NOW,
    )
    assert empty_view.store_value is None
    assert empty_view.network_average == pytest.approx((2.0 + 7.0 + 4.0) / 3)


# --------------------------------------------------------------------------- #
# 4. Zaman-üzrə Trend — ROOT parametri
# --------------------------------------------------------------------------- #


def test_trend_root_parameter_changes_number_of_points() -> None:
    provider = FakeProvider(
        stores={STORE_A: "28 May"},
        monthly_values={
            BenchmarkMetric.FINE_COUNT: {
                date(2026, month, 1): {STORE_A: float(month)} for month in range(1, 9)
            }
        },
    )
    default_case = MultiStoreBenchmarkUseCase(
        provider=provider, limits=FakeLimits(), clock=FakeClock()
    )
    default_points = default_case.trend(
        tenant_id=TENANT,
        actor=_hr_admin(),
        metric=BenchmarkMetric.FINE_COUNT,
        store_id=STORE_A,
        now=NOW,
    )
    assert len(default_points) == int(DEFAULT_LIMITS[SystemLimitKey.BENCHMARK_TREND_MONTHS])

    custom_case = MultiStoreBenchmarkUseCase(
        provider=provider,
        limits=FakeLimits({"BENCHMARK_TREND_MONTHS": "3"}),
        clock=FakeClock(),
    )
    custom_points = custom_case.trend(
        tenant_id=TENANT,
        actor=_hr_admin(),
        metric=BenchmarkMetric.FINE_COUNT,
        store_id=STORE_A,
        now=NOW,
    )
    assert len(custom_points) == 3
    assert [point.period_label for point in custom_points] == ["2026-06", "2026-07", "2026-08"]
    assert [point.value for point in custom_points] == [6.0, 7.0, 8.0]


def test_trend_network_wide_uses_metric_specific_aggregation() -> None:
    month = date(2026, 8, 1)
    provider = FakeProvider(
        stores={STORE_A: "A", STORE_B: "B"},
        monthly_values={
            BenchmarkMetric.FINE_COUNT: {month: {STORE_A: 3.0, STORE_B: 5.0}},
            BenchmarkMetric.ATTENDANCE_RATE: {month: {STORE_A: 80.0, STORE_B: 90.0}},
        },
    )
    use_case = MultiStoreBenchmarkUseCase(
        provider=provider,
        limits=FakeLimits({"BENCHMARK_TREND_MONTHS": "1"}),
        clock=FakeClock(),
    )

    fine_points = use_case.trend(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert fine_points[-1].value == pytest.approx(8.0)  # SUM — say göstəricisi

    attendance_points = use_case.trend(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.ATTENDANCE_RATE, now=NOW
    )
    assert attendance_points[-1].value == pytest.approx(85.0)  # AVERAGE — faiz göstəricisi


def test_trend_with_empty_network_keeps_correct_length_with_none_values() -> None:
    """Boş məlumat halı — çökmür, uzunluq YENƏ DƏ ROOT parametrinə uyğun gəlir."""
    provider = FakeProvider(stores={}, monthly_values={})
    use_case = MultiStoreBenchmarkUseCase(
        provider=provider,
        limits=FakeLimits({"BENCHMARK_TREND_MONTHS": "4"}),
        clock=FakeClock(),
    )
    points = use_case.trend(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert len(points) == 4
    assert all(point.value is None for point in points)


# --------------------------------------------------------------------------- #
# 5. Kritik-Kənar (Outlier) Kartı
# --------------------------------------------------------------------------- #


def _outlier_provider(values: dict[StoreId, float]) -> FakeProvider:
    month = date(2026, 8, 1)
    stores = {store_id: f"Store-{index}" for index, store_id in enumerate(values)}
    return FakeProvider(
        stores=stores, monthly_values={BenchmarkMetric.FINE_COUNT: {month: dict(values)}}
    )


def test_outliers_zero_stores_does_not_crash() -> None:
    provider = _outlier_provider({})
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    report = use_case.outliers(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert report.outliers == ()
    assert report.mean is None
    assert "kənar filial yoxdur" in report.summary_text_az


def test_outliers_single_store_does_not_crash() -> None:
    provider = _outlier_provider({STORE_A: 5.0})
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    report = use_case.outliers(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert report.outliers == ()


def test_outliers_all_values_equal_zero_sigma_does_not_crash() -> None:
    """σ=0 (bütün mağazalar eyni) — sıfıra bölmə YOXDUR (kompasos11.md #24)."""
    provider = _outlier_provider({STORE_A: 4.0, STORE_B: 4.0, STORE_C: 4.0})
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    report = use_case.outliers(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert report.stdev == 0.0
    assert report.outliers == ()


def test_outliers_detects_deviation_beyond_sigma_threshold() -> None:
    # Kiçik nümunədə (4 mağaza) TƏK kənar dəyər populyasiya σ-nı da böyüdür,
    # ona görə hədd BURADA açıq göstərilir (1.0σ) — nəticə YENƏ DƏ ROOT
    # parametrindən (`BENCHMARK_OUTLIER_SIGMA_MULTIPLIER`) gəlir, sabit deyil.
    outlier_store = StoreId(uuid.uuid4())
    provider = _outlier_provider({STORE_A: 10.0, STORE_B: 11.0, STORE_C: 9.0, outlier_store: 200.0})
    use_case = MultiStoreBenchmarkUseCase(
        provider=provider,
        limits=FakeLimits({"BENCHMARK_OUTLIER_SIGMA_MULTIPLIER": "1.0"}),
        clock=FakeClock(),
    )
    report = use_case.outliers(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert len(report.outliers) == 1
    assert report.outliers[0].store_id == outlier_store
    assert report.outliers[0].above_average is True
    assert "Diqqət" in report.summary_text_az


def test_outliers_root_sigma_parameter_changes_result() -> None:
    """ROOT parametri dəyişəndə NƏTİCƏ DƏYİŞİR — hardcode-a qarşı qapı."""
    values = {STORE_A: 10.0, STORE_B: 12.0, STORE_C: 20.0}
    provider = _outlier_provider(values)

    strict_case = MultiStoreBenchmarkUseCase(
        provider=provider,
        limits=FakeLimits({"BENCHMARK_OUTLIER_SIGMA_MULTIPLIER": "5.0"}),
        clock=FakeClock(),
    )
    loose_case = MultiStoreBenchmarkUseCase(
        provider=provider,
        limits=FakeLimits({"BENCHMARK_OUTLIER_SIGMA_MULTIPLIER": "0.1"}),
        clock=FakeClock(),
    )

    strict_report = strict_case.outliers(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    loose_report = loose_case.outliers(
        tenant_id=TENANT, actor=_root(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )

    assert strict_report.outliers == ()
    assert len(loose_report.outliers) > 0


# --------------------------------------------------------------------------- #
# 6. Boş məlumat halı — bütün DÖRD metod
# --------------------------------------------------------------------------- #


def test_empty_network_returns_empty_results_without_crashing_any_widget() -> None:
    provider = FakeProvider(stores={}, monthly_values={})
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    actor = _root()

    assert (
        use_case.ranking(tenant_id=TENANT, actor=actor, metric=BenchmarkMetric.FINE_COUNT, now=NOW)
        == []
    )

    view = use_case.store_vs_network(
        tenant_id=TENANT, actor=actor, metric=BenchmarkMetric.FINE_COUNT, store_id=STORE_A, now=NOW
    )
    assert view.store_value is None
    assert view.network_average is None
    assert view.network_store_count == 0

    outliers = use_case.outliers(
        tenant_id=TENANT, actor=actor, metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert outliers.outliers == ()


# --------------------------------------------------------------------------- #
# 7. Scoping — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (istifadə qatı)
# --------------------------------------------------------------------------- #


def test_store_manager_is_blocked_from_all_four_reads() -> None:
    provider = _provider_for_ranking()
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    manager = _store_manager()

    with pytest.raises(AuthorizationError):
        use_case.ranking(
            tenant_id=TENANT, actor=manager, metric=BenchmarkMetric.FINE_COUNT, now=NOW
        )
    with pytest.raises(AuthorizationError):
        use_case.store_vs_network(
            tenant_id=TENANT,
            actor=manager,
            metric=BenchmarkMetric.FINE_COUNT,
            store_id=STORE_A,
            now=NOW,
        )
    with pytest.raises(AuthorizationError):
        use_case.trend(tenant_id=TENANT, actor=manager, metric=BenchmarkMetric.FINE_COUNT, now=NOW)
    with pytest.raises(AuthorizationError):
        use_case.outliers(
            tenant_id=TENANT, actor=manager, metric=BenchmarkMetric.FINE_COUNT, now=NOW
        )


@pytest.mark.parametrize("actor_factory", _NETWORK_WIDE_ACTORS)
def test_network_wide_roles_can_read_ranking(actor_factory: Any) -> None:
    provider = _provider_for_ranking()
    use_case = MultiStoreBenchmarkUseCase(provider=provider, limits=FakeLimits(), clock=FakeClock())
    rows = use_case.ranking(
        tenant_id=TENANT, actor=actor_factory(), metric=BenchmarkMetric.FINE_COUNT, now=NOW
    )
    assert rows  # boş DEYİL — icazə var, məlumat da var


# --------------------------------------------------------------------------- #
# 8. ROOT parametrləri `system_limits`-ə qeydiyyatdan keçib
# --------------------------------------------------------------------------- #


def test_root_parameters_are_registered_with_documented_defaults() -> None:
    assert DEFAULT_LIMITS[SystemLimitKey.BENCHMARK_TREND_MONTHS] == "6"
    assert DEFAULT_LIMITS[SystemLimitKey.BENCHMARK_OUTLIER_SIGMA_MULTIPLIER] == "2.0"


def test_format_metric_value_distinguishes_missing_from_zero() -> None:
    assert format_metric_value(None, BenchmarkMetric.FINE_COUNT) == "—"
    assert format_metric_value(0.0, BenchmarkMetric.FINE_COUNT) == "0"
    assert format_metric_value(91.456, BenchmarkMetric.ATTENDANCE_RATE) == "91.5%"


# --------------------------------------------------------------------------- #
# 9. DRILL-DOWN naviqasiyası — SAF funksiya, Qt tələb etmir
# --------------------------------------------------------------------------- #


class _FakeShell:
    """`AdminShell.show_screen`/`screen_for` müqaviləsinin minimal təkrarı."""

    def __init__(self, *, visible: bool, screen: object | None) -> None:
        self._visible = visible
        self._screen = screen
        self.show_screen_calls: list[str] = []
        self.screen_for_calls: list[str] = []

    def show_screen(self, key: str) -> bool:
        self.show_screen_calls.append(key)
        return self._visible

    def screen_for(self, key: str) -> object | None:
        self.screen_for_calls.append(key)
        return self._screen


def test_drill_down_navigates_to_daily_roster_and_populates_clicked_store() -> None:
    fake_screen = object()
    shell = _FakeShell(visible=True, screen=fake_screen)
    populated: list[tuple[StoreId, object]] = []
    store_id = StoreId(uuid.uuid4())

    result = perform_ranking_drill_down(
        str(store_id),
        show_screen=shell.show_screen,
        screen_for=shell.screen_for,
        populate=lambda sid, screen: populated.append((sid, screen)),
    )

    assert result is True
    assert shell.show_screen_calls == ["daily_roster"]
    assert shell.screen_for_calls == ["daily_roster"]
    assert populated == [(store_id, fake_screen)]


def test_drill_down_does_not_populate_when_target_screen_is_hidden() -> None:
    """`show_screen` `False` qaytarırsa (icazə yoxdur) — `screen_for` ÇAĞIRILMIR."""
    shell = _FakeShell(visible=False, screen=None)
    populated: list[Any] = []

    result = perform_ranking_drill_down(
        str(uuid.uuid4()),
        show_screen=shell.show_screen,
        screen_for=shell.screen_for,
        populate=lambda sid, screen: populated.append((sid, screen)),
    )

    assert result is False
    assert populated == []
    assert shell.screen_for_calls == []


def test_drill_down_rejects_invalid_store_id_before_navigating() -> None:
    shell = _FakeShell(visible=True, screen=object())

    result = perform_ranking_drill_down(
        "not-a-uuid",
        show_screen=shell.show_screen,
        screen_for=shell.screen_for,
        populate=lambda sid, screen: None,
    )

    assert result is False
    assert shell.show_screen_calls == []  # naviqasiya BAŞLAMADI belə


# --------------------------------------------------------------------------- #
# 10. Drill-down-un YAZI yolu — `ScreenDataBinder.populate_daily_roster_for_store`
# --------------------------------------------------------------------------- #


class _FakeDailyAttendance:
    def __init__(self, view: Any) -> None:
        self._view = view
        self.calls: list[StoreId] = []

    def open_sheet(self, *, tenant_id: TenantId, actor: Employee, store_id: StoreId) -> Any:
        self.calls.append(store_id)
        return self._view


class _FakeEmployees:
    def __init__(self, employees: dict[EmployeeId, Employee]) -> None:
        self._employees = employees

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._employees.get(employee_id)


@dataclass
class _FakeUow:
    employees: _FakeEmployees


@dataclass
class _FakeBenchmarkSession:
    tenant_id: TenantId
    daily_attendance: _FakeDailyAttendance
    uow: _FakeUow
    commits: int = field(default=0)

    def commit(self) -> None:
        self.commits += 1


class _FakeBenchmarkContext:
    def __init__(self, session: _FakeBenchmarkSession) -> None:
        self._session = session

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


class _FakeRosterScreen:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] | None = None
        self.mismatch_text: str | None = None

    def set_rows(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def set_mismatch(self, text: str) -> None:
        self.mismatch_text = text


def test_populate_daily_roster_for_store_opens_the_clicked_store_not_actors_own() -> None:
    """Root-un ÖZ `store_id`-si `None`-dur — drill-down BAŞQA mağazanı açmalıdır."""
    root = _root()
    assert root.store_id is None  # Root heç bir mağazaya bağlı deyil (şəbəkə-miqyaslı rol)

    target_store = StoreId(uuid.uuid4())
    line_employee = make_employee(
        position=make_position(SystemRole.SELLER.value, priority=RolePriority.STAFF, flags=[])
    )
    line = type(
        "FakeLine",
        (),
        {
            "employee_id": line_employee.id,
            "auto_status": AutoAttendanceStatus.VERIFIED,
            "manager_note": "",
        },
    )()
    sheet = type("FakeSheet", (), {"lines": [line]})()
    view = type("FakeSheetView", (), {"sheet": sheet, "mismatch_count": 1})()

    daily_attendance = _FakeDailyAttendance(view)
    session = _FakeBenchmarkSession(
        tenant_id=TENANT,
        daily_attendance=daily_attendance,
        uow=_FakeUow(employees=_FakeEmployees({line_employee.id: line_employee})),
    )
    context = _FakeBenchmarkContext(session)
    binder = ScreenDataBinder(context, root)
    screen = _FakeRosterScreen()

    binder.populate_daily_roster_for_store(target_store, screen)

    assert daily_attendance.calls == [target_store]
    assert session.commits == 1
    assert screen.rows == [
        {
            "employee": line_employee.full_name,
            "status": AutoAttendanceStatus.VERIFIED.label_az,
            "note": "",
        }
    ]
    assert screen.mismatch_text is not None


# --------------------------------------------------------------------------- #
# 11. 1C SƏRHƏDİ — statik qapı
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
    """#24 mənbəyi YALNIZ KompasOS-un öz cərimə/davamiyyət/xal/overtime/risk datasıdır."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    leaking = sorted(name for name in imported if "erp" in name or "sales" in name)
    assert not leaking, f"#24 1C qatına bağlandı: {leaking}"


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
    assert not hits, f"#24 kodunda 1C izi: {hits}"


# --------------------------------------------------------------------------- #
# 12. Maket/canlı paritet — setter imzası
# --------------------------------------------------------------------------- #


def test_store_vs_network_setter_signature_matches_preview_data_shape() -> None:
    """CLAUDE.md bölmə 6: maket və canlı yol EYNİ AÇARLI olmalıdır.

    `DashboardScreen.set_store_vs_network`-in keyword imzası `preview_data.
    BenchmarkStoreVsNetwork`-un sahələri ilə TAM üst-üstə düşməlidir — əks
    halda maket yolu sükutla köhnəlmiş qala bilər (bax `menu.py` başlığındakı
    tarixi qüsur).
    """
    import inspect

    from src.presentation import preview_data
    from src.presentation.screens.group_c import DashboardScreen

    signature = inspect.signature(DashboardScreen.set_store_vs_network)
    setter_params = {name for name in signature.parameters if name != "self"}
    namedtuple_fields = set(preview_data.BenchmarkStoreVsNetwork._fields)
    assert setter_params == namedtuple_fields
