"""Benchmark widget-lərinin gediş-gəliş büdcəsi — PERF-5.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAYĞAC TESTİ, «SÜRƏT» TESTİ YOX
──────────────────────────────────────────────────────────────────────────────
`test_session_roundtrips.py` ilə eyni səbəb: bu quraşdırmada bir gediş-gəliş
~206 ms-dir (`docs/performance_notes.md`), yəni sorğu SAYI birbaşa istifadəçi
gözləməsidir. Vaxt ölçən test şəbəkədən asılı olar və CI-da səbəbsiz sınardı.

──────────────────────────────────────────────────────────────────────────────
HANSI QÜSURU KİLİDLƏYİR (CANLI ÖLÇÜ)
──────────────────────────────────────────────────────────────────────────────
`trend()` N ayı N AYRI sorğu ilə oxuyurdu, `ranking()` isə cari və əvvəlki ayı
İKİ sorğu ilə. İdarə Panelinin canlı ölçüsündə bu, 17 sorğudan ALTISI idi —
panel 5.25 saniyə çəkirdi. Toplu oxudan sonra: 13 sorğu, 3.25 saniyə.

Sayğac artarsa, düzəliş sükutla geri qayıdıb deməkdir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.application.use_cases.multi_store_benchmark import (
    VIEW_BENCHMARK_FLAG,
    BenchmarkMetric,
    MultiStoreBenchmarkUseCase,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import PermissionFlag, RolePriority, SystemRole
from src.domain.value_objects.identifiers import StoreId, TenantId
from tests.unit.test_benchmark_widgets import TENANT, make_employee, make_position

pytestmark = pytest.mark.unit

STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
TREND_MONTHS = int(DEFAULT_LIMITS[SystemLimitKey.BENCHMARK_TREND_MONTHS])


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Limits:
    """Defolt dəyərləri qaytarır — bu testin mövzusu limit deyil, sorğu sayıdır."""

    def get_int(self, _tenant_id: TenantId, _key: str, default: int) -> int:
        return default

    def get_float(self, _tenant_id: TenantId, _key: str, default: float) -> float:
        return default

    def get_str(self, _tenant_id: TenantId, _key: str, default: str) -> str:
        return default


class _BatchedProvider:
    """Toplu oxunu DƏSTƏKLƏYƏN provayder — `PostgresMultiStoreBenchmarkRepository`
    ilə eyni müqavilə, lakin bazasız: hər çağırış SADƏCƏ sayılır."""

    def __init__(self) -> None:
        self.single_calls: list[tuple[date, date]] = []
        self.batch_calls: list[list[tuple[date, date]]] = []

    def active_stores(self, _tenant_id: TenantId) -> dict[StoreId, str]:
        return {STORE: "Filial"}

    def metric_values(
        self, _tenant_id: TenantId, _metric: BenchmarkMetric, *, start: date, end: date
    ) -> dict[StoreId, float]:
        self.single_calls.append((start, end))
        return {STORE: 1.0}

    def metric_values_by_period(
        self,
        _tenant_id: TenantId,
        _metric: BenchmarkMetric,
        *,
        periods: Any,
    ) -> list[dict[StoreId, float]]:
        windows = [(start, end) for start, end in periods]
        self.batch_calls.append(windows)
        return [{STORE: 1.0} for _ in windows]


class _PlainProvider(_BatchedProvider):
    """Toplu oxunu DƏSTƏKLƏMƏYƏN provayder — `metric_values_by_period` YOXDUR."""

    metric_values_by_period = None  # type: ignore[assignment]


def _actor() -> Any:
    """`can_export_reports` daşıyan Root — bu testin mövzusu səlahiyyət deyil."""
    flags = [PermissionFlag(code=VIEW_BENCHMARK_FLAG, category="SISTEM")]
    return make_employee(
        position=make_position(SystemRole.ROOT.value, priority=RolePriority.ROOT, flags=flags)
    )


def _use_case(provider: Any) -> MultiStoreBenchmarkUseCase:
    return MultiStoreBenchmarkUseCase(provider=provider, limits=_Limits(), clock=_Clock())


def test_trend_reads_every_month_in_a_single_call() -> None:
    """N ay = BİR toplu çağırış (əvvəl N ayrı sorğu idi)."""
    provider = _BatchedProvider()

    points = _use_case(provider).trend(
        tenant_id=TENANT, actor=_actor(), metric=BenchmarkMetric.FINE_COUNT
    )

    assert len(points) == TREND_MONTHS
    assert len(provider.batch_calls) == 1
    assert len(provider.batch_calls[0]) == TREND_MONTHS
    assert provider.single_calls == []  # tək-tək oxu QALMADI


def test_ranking_reads_the_current_and_previous_month_together() -> None:
    """Cari + əvvəlki ay BİR çağırışdadır — sıra da qorunur."""
    provider = _BatchedProvider()

    _use_case(provider).ranking(tenant_id=TENANT, actor=_actor(), metric=BenchmarkMetric.FINE_COUNT)

    assert len(provider.batch_calls) == 1
    windows = provider.batch_calls[0]
    assert len(windows) == 2
    # Birinci CARİ ay olmalıdır: `ranking` reytinqi ONUN üzərində qurur,
    # əvvəlki ay yalnız trend oxunu (↑↓) hesablayır.
    assert windows[0][0] == date(2026, 6, 1)
    assert windows[1][0] == date(2026, 5, 1)


def test_a_provider_without_batching_still_works() -> None:
    """Toplu oxu OPTİMALLAŞDIRMADIR, TƏLƏB DEYİL — nəticə eynidir.

    Yaddaş-daxili sahtələr (testlər, gələcək plugin provayderləri) həmin
    metodu tətbiq etmək MƏCBURİYYƏTİNDƏ deyil; bu qapı onların sükutla
    sınmadığını təsbit edir.
    """
    provider = _PlainProvider()

    points = _use_case(provider).trend(
        tenant_id=TENANT, actor=_actor(), metric=BenchmarkMetric.FINE_COUNT
    )

    assert len(points) == TREND_MONTHS
    assert provider.batch_calls == []
    assert len(provider.single_calls) == TREND_MONTHS  # köhnə dövrə İŞLƏYİR
