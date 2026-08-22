"""Çox-Mağaza Benchmark Dashboard — #24, kompasos11.md Faza 9A.

Dashboard Builder-in mövcud widget qeydiyyatına (`application.use_cases.
dashboard_layout.WIDGET_CATALOG`) dörd YENİ widget tipi əlavə olunur:
`ranking_table`, `store_vs_network`, `metric_trend`, `benchmark_outliers`.
Bu fayl onların DATA/MƏNTİQ qatıdır — heç bir yeni ekran, heç bir yeni
naviqasiya qeydiyyatı yaratmır (kompasos11.md #24 qərar C: "AYRI EKRAN
YARATMA").

──────────────────────────────────────────────────────────────────────────────
1C SƏRHƏDİ — YALNIZ KompasOS-un ÖZ DATASI
──────────────────────────────────────────────────────────────────────────────
`tests/unit/test_benchmark_widgets.py`-dəki statik (`ast`) qapı
`attrition_risk.py`/`staffing_pattern.py` ilə EYNİ naxışdadır: bu modulda və
`infrastructure.persistence.benchmark_repository`-də nə `erp`/`sales` idxalı,
nə də `SalesDataConnector`/`OneCSaleRecord` kimi 1C identifikatoru ola bilməz.
Metriklər YALNIZ cərimə (`fines`), davamiyyət (`daily_attendance_sheet_
lines`), xal (`points_ledger` — mövcud, icazəli 1C-bal-kanalı, YENİ bağlantı
DEYİL), overtime (`overtime_log`), turnover riski (`attrition_risk_scores`,
#21-in NATİV nəticəsi) və audit balı (`field_reports` +
`field_report_checklist_items`, #26-nın NATİV nəticəsi) cədvəllərindən
qidalanır. Xam satış rəqəmi/marja BURAYA DAXİL EDİLMİR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YENİ FLAG YOX — `can_export_reports` TƏKRAR İSTİFADƏ OLUNUR
──────────────────────────────────────────────────────────────────────────────
`schema.sql` §23-dəki rol-defolt cədvəlini yoxlasaq: `can_export_reports`
DƏQİQ Root (bütün qeyri-kamera flag), CEO (hardlock≠1), Admin və HR_Admin-ə
verilib, Mağaza_Meneceri/Kamera_Nəzarətçisi/Satıcı-nın siyahısında İSƏ
YOXDUR (`menu.py`-dakı "Hesabatlar" maddəsi də EYNİ flag-lə qapılıb — çox-
mağaza benchmarkı da eyni "şəbəkə-miqyaslı hesabat" kateqoriyasıdır). Yəni
tələb olunan dördlük (Root/CEO/Admin/HR_Admin) üçün TƏK flag KİFAYƏT EDİR —
yeni flag yaratmaq artıq mürəkkəblik olardı.

──────────────────────────────────────────────────────────────────────────────
"GÖRMƏK = SƏLAHİYYƏTİN OLMASI" İKİ QATDA
──────────────────────────────────────────────────────────────────────────────
Widget kataloqunda (`dashboard_layout.WIDGET_CATALOG`) `required_flag` bu
widget-ləri SEÇİM SİYAHISINDAN gizlədir. Bu use case İSƏ AYRICA `_require`
yoxlaması aparır (`AttritionRiskUseCase._require_view` ilə EYNİ naxış) —
defolt-qapalı ikinci qat: ekran bağlaması səhvən çağırılsa belə (məs. gələcək
skript, test), məlumat sızmır.

──────────────────────────────────────────────────────────────────────────────
"ƏN YAXŞI" İSTİQAMƏTİ METRİKİN TƏRİFİDİR, `if` ZƏNCİRİ DEYİL
──────────────────────────────────────────────────────────────────────────────
Cərimə sayında/overtime saatında/turnover balında AZ yaxşıdır; davamiyyət
faizində/xal balansında ÇOX yaxşıdır. `BenchmarkMetric.lower_is_better`
buna görə sıralamanın ÖZÜ bu bayrağı oxuyur — yeni metrik əlavə olunanda
unudulası bir `if metric == ...` budağı YARANMIR.

──────────────────────────────────────────────────────────────────────────────
ROOT PARAMETRLƏRİ — HARDCODE YOX
──────────────────────────────────────────────────────────────────────────────
`SystemLimitKey.BENCHMARK_TREND_MONTHS` (defolt 6) və `BENCHMARK_OUTLIER_
SIGMA_MULTIPLIER` (defolt 2.0) `system_limits`-dən oxunur (seed: migrations/
031). Sinifdəki `_FALLBACK_*` sabitləri YALNIZ sətir hələ seed edilməyibsə
işə düşən ehtiyat dəyərdir — həqiqi mənbə HƏMİŞƏ `system_limits`-dir
(`BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER` ilə EYNİ oxuma naxışı, `behavior_
baseline.py`).

──────────────────────────────────────────────────────────────────────────────
FİLİAL SAYI HARDCODE DEYİL
──────────────────────────────────────────────────────────────────────────────
`MultiStoreMetricProvider.active_stores` bazadan gələn AKTİV mağaza dəstini
qaytarır — nə "21" sabiti, nə də sərt limit. Reytinq/outlier siyahısı bu
dəstin ÖZÜNÜN uzunluğu qədərdir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from statistics import fmean, pstdev
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import AuthorizationError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import Clock, SystemLimits
    from src.domain.value_objects.identifiers import StoreId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Bu widget dəstinin görünmə qapısı (bax modul başlığı — YENİ FLAG YOXDUR).
VIEW_BENCHMARK_FLAG: Final = "can_export_reports"

#: Fallback-lar — həqiqi mənbə `system_limits` (migrations/031 seed edir).
_FALLBACK_TREND_MONTHS: Final = int(DEFAULT_LIMITS[SystemLimitKey.BENCHMARK_TREND_MONTHS])
_FALLBACK_SIGMA_MULTIPLIER: Final = float(
    DEFAULT_LIMITS[SystemLimitKey.BENCHMARK_OUTLIER_SIGMA_MULTIPLIER]
)


# --------------------------------------------------------------------------- #
# Metrik tərifi
# --------------------------------------------------------------------------- #


class BenchmarkMetric(str, Enum):
    """Native metriklər (bax modul başlığı — 1C xam satış BURADA YOXDUR).

    `AUDIT_SCORE` (#26, kompas1.md Faza 3) Struktur Qərar C ilə BURAYA əlavə
    olundu — AYRI ekran/widget YARADILMADI. Səbəb: audit balı da digər beşi
    kimi "filialı filialla müqayisə et" sualının cavabıdır; onun üçün ayrı
    panel qurmaq eyni reytinq/trend/outlier məntiqini ikinci nüsxədə
    saxlamaq olardı. Yeni metrik dörd widget-in HAMISINDA avtomatik işləyir,
    çünki hər biri metriki arqument kimi alır.
    """

    FINE_COUNT = "FINE_COUNT"
    ATTENDANCE_RATE = "ATTENDANCE_RATE"
    POINTS_BALANCE = "POINTS_BALANCE"
    OVERTIME_HOURS = "OVERTIME_HOURS"
    TURNOVER_RISK = "TURNOVER_RISK"
    AUDIT_SCORE = "AUDIT_SCORE"

    @property
    def label_az(self) -> str:
        return _METRIC_LABELS[self]

    @property
    def unit_suffix(self) -> str:
        return _METRIC_UNITS[self]

    @property
    def lower_is_better(self) -> bool:
        """ "Ən yaxşı" nəyi göstərir — metrikin ÖZÜNÜN tərifi (bax modul başlığı)."""
        return _METRIC_LOWER_IS_BETTER[self]

    @property
    def network_aggregation(self) -> _NetworkAggregation:
        """Filial seçilmədən (şəbəkə-miqyaslı trend) necə cəmlənir."""
        return _METRIC_NETWORK_AGGREGATION[self]


class _NetworkAggregation(str, Enum):
    """Şəbəkə-miqyaslı dəyər CƏM (say/saat) yoxsa ORTALAMA (faiz/bal) olsun."""

    SUM = "SUM"
    AVERAGE = "AVERAGE"


_METRIC_LABELS: Final[dict[BenchmarkMetric, str]] = {
    BenchmarkMetric.FINE_COUNT: "Cərimə sayı",
    BenchmarkMetric.ATTENDANCE_RATE: "Davamiyyət faizi",
    BenchmarkMetric.POINTS_BALANCE: "Xal balansı",
    BenchmarkMetric.OVERTIME_HOURS: "Overtime saatı",
    BenchmarkMetric.TURNOVER_RISK: "Turnover riski",
    BenchmarkMetric.AUDIT_SCORE: "Audit balı",
}
_METRIC_UNITS: Final[dict[BenchmarkMetric, str]] = {
    BenchmarkMetric.FINE_COUNT: "",
    BenchmarkMetric.ATTENDANCE_RATE: "%",
    BenchmarkMetric.POINTS_BALANCE: " xal",
    BenchmarkMetric.OVERTIME_HOURS: " saat",
    BenchmarkMetric.TURNOVER_RISK: " bal",
    # Faiz: "keçən bəndlərin cavablanmışlara nisbəti" (bax
    # `FieldReport.audit_score`). Xam bənd sayı OLSAYDI, 10 bəndlik audit ilə
    # 40 bəndlik audit müqayisə edilə bilməzdi.
    BenchmarkMetric.AUDIT_SCORE: "%",
}
#: Cərimə/overtime/turnover — AZ yaxşıdır. Davamiyyət/xal/audit — ÇOX yaxşıdır.
_METRIC_LOWER_IS_BETTER: Final[dict[BenchmarkMetric, bool]] = {
    BenchmarkMetric.FINE_COUNT: True,
    BenchmarkMetric.ATTENDANCE_RATE: False,
    BenchmarkMetric.POINTS_BALANCE: False,
    BenchmarkMetric.OVERTIME_HOURS: True,
    BenchmarkMetric.TURNOVER_RISK: True,
    # `False` — audit balında ÇOX yaxşıdır: bal keçən checklist bəndlərinin
    # faizidir, uğursuzluq sayı DEYİL. İstiqamət metrikin TƏRİFİNİN bir
    # hissəsidir (bax modul başlığı): səhv seçilsəydi, reytinq cədvəlində ən
    # pis filial birinci sırada "ən yaxşı" kimi görünərdi və outlier kartı
    # yüksək balı problem kimi göstərərdi.
    BenchmarkMetric.AUDIT_SCORE: False,
}
_METRIC_NETWORK_AGGREGATION: Final[dict[BenchmarkMetric, _NetworkAggregation]] = {
    BenchmarkMetric.FINE_COUNT: _NetworkAggregation.SUM,
    BenchmarkMetric.ATTENDANCE_RATE: _NetworkAggregation.AVERAGE,
    BenchmarkMetric.POINTS_BALANCE: _NetworkAggregation.SUM,
    BenchmarkMetric.OVERTIME_HOURS: _NetworkAggregation.SUM,
    BenchmarkMetric.TURNOVER_RISK: _NetworkAggregation.AVERAGE,
    # ORTALAMA, CƏM YOX: faizlərin cəmi mənasızdır (üç filialın 90%+80%+70%-i
    # "240%" verərdi) — `ATTENDANCE_RATE` ilə eyni səbəb.
    BenchmarkMetric.AUDIT_SCORE: _NetworkAggregation.AVERAGE,
}


class TrendDirection(str, Enum):
    """Ötən dövrlə müqayisədə RƏQƏMİN xam istiqaməti (yaxşı/pis DEYİL).

    Oxu YALNIZ rənglə fərqlənmir — `arrow` işarəni, `label_az` isə mətni
    daşıyır (kompasos11.md #24 açıq tələbi).
    """

    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"

    @property
    def arrow(self) -> str:
        return {"UP": "↑", "DOWN": "↓", "FLAT": "→"}[self.value]

    @property
    def label_az(self) -> str:
        return {"UP": "artıb", "DOWN": "azalıb", "FLAT": "dəyişməyib"}[self.value]


# --------------------------------------------------------------------------- #
# Nəticə görünüşləri
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RankingRow:
    """Reytinq Cədvəli — bir mağaza sətri."""

    rank: int
    store_id: StoreId
    store_name: str
    value: float
    display_value: str
    previous_value: float | None
    trend: TrendDirection


@dataclass(frozen=True)
class StoreVsNetworkView:
    """Mağaza-Qarşı-Şəbəkə-Ortalaması — tək mağaza nəticəsi."""

    metric: BenchmarkMetric
    store_id: StoreId
    store_name: str
    store_value: float | None
    network_average: float | None
    network_store_count: int


@dataclass(frozen=True)
class TrendPoint:
    """Zaman-üzrə Trend — bir ayın nöqtəsi."""

    period_label: str
    value: float | None


@dataclass(frozen=True)
class OutlierStore:
    """Kritik-Kənar Kartı — bir kənar mağaza."""

    store_id: StoreId
    store_name: str
    value: float
    deviation_sigma: float
    above_average: bool


@dataclass(frozen=True)
class OutlierReport:
    """Kritik-Kənar Kartı — tam nəticə (boş ola bilər — bax modul başlığı)."""

    metric: BenchmarkMetric
    mean: float | None
    stdev: float | None
    threshold_sigma: float
    outliers: tuple[OutlierStore, ...]

    @property
    def summary_text_az(self) -> str:
        """Nümunə: "Diqqət: 3 filial cərimə sayı göstəricisində ortalamadan
        2×σ kənardır." (kompasos11.md #24-ün öz nümunə mətni)."""
        if not self.outliers:
            return (
                f"{self.metric.label_az} göstəricisində şəbəkə ortalamasından "
                "statistik əhəmiyyətli kənar filial yoxdur."
            )
        return (
            f"Diqqət: {len(self.outliers)} filial {self.metric.label_az.lower()} "
            f"göstəricisində ortalamadan {self.threshold_sigma:g}×σ kənardır."
        )


# --------------------------------------------------------------------------- #
# Xam məlumat mənbəyi — ReportFactProvider naxışı (bax modul başlığı)
# --------------------------------------------------------------------------- #


@runtime_checkable
class MultiStoreMetricProvider(Protocol):
    """Repo qatının bu use case-ə verdiyi TƏTBİQ-qatı struktur (dict).

    Sadə `dict[StoreId, float]` qaytardığı üçün `ports.py`-da DEYİL, BURADA
    təyin olunur (CLAUDE.md — "port tətbiq qatının strukturunu qaytarırsa
    use case faylının yanında təyin olunur").
    """

    def active_stores(self, tenant_id: TenantId) -> dict[StoreId, str]:
        """Aktiv filiallar — `id → ad`. Say DATADAN gəlir, HARDCODE deyil."""
        ...

    def metric_values(
        self, tenant_id: TenantId, metric: BenchmarkMetric, *, start: date, end: date
    ) -> dict[StoreId, float]:
        """`[start, end)` aralığında filial başına aqreqat dəyər.

        Məlumatı OLMAYAN filial dict-DƏ YOXDUR (sıfır DEYİL) — "heç bir
        qeyd yoxdur" ilə "dəyər sıfırdır" fərqi çağıran tərəfə ötürülür.
        """
        ...


class BatchedMetricProvider(Protocol):
    """ÇOX aralığı BİR gediş-gəlişdə oxuyan OPSİYONAL genişlənmə (PERF-5).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRI PROTOCOL, NİYƏ `MultiStoreMetricProvider`-ə ƏLAVƏ METOD DEYİL
    ──────────────────────────────────────────────────────────────────────────
    `trend()` N ay üçün N ayrı `metric_values()` çağırırdı — CANLI ölçüdə bu,
    İdarə Panelinin 17 sorğusundan ALTISI idi (hər biri ~206 ms şəbəkə
    gediş-gəlişi, bax `docs/performance_notes.md`). Toplu oxu həmin altını
    BİRƏ endirir.

    Metod ƏSAS porta əlavə edilsəydi, onu TƏTBİQ ETMƏYƏN hər sahtə (testlərin
    yaddaş-daxili provayderləri) sükutla protokoldan düşərdi — halbuki toplu
    oxu OPTİMALLAŞDIRMADIR, TƏLƏB deyil: bir aralığı bir dəfə oxumaq HƏMİŞƏ
    düzgün nəticə verir. Ona görə use case `isinstance` YOX, `getattr` ilə
    yoxlayır və metod yoxdursa KÖHNƏ dövrəyə düşür (eyni "opsional port"
    naxışı `ports.py::RowLockingLeaveRequests`-dədir).
    """

    def metric_values_by_period(
        self,
        tenant_id: TenantId,
        metric: BenchmarkMetric,
        *,
        periods: Sequence[tuple[date, date]],
    ) -> list[dict[StoreId, float]]:
        """Hər `[start, end)` aralığı üçün BİR dict — SIRA qorunur.

        Qaytarılan siyahının uzunluğu `periods`-un uzunluğu ilə EYNİDİR;
        məlumatı olmayan aralıq BOŞ dict-dir (`None` DEYİL) — çağıran tərəf
        "aralıq yoxdur" halını AYRICA yoxlamamalıdır.
        """
        ...


# --------------------------------------------------------------------------- #
# Use case
# --------------------------------------------------------------------------- #


class MultiStoreBenchmarkUseCase:
    """4 widget-in (ranking/store_vs_network/trend/outliers) OXU yolu.

    Widget-lər yalnız OXUYUR (kompasos11.md #24) — bu sinifdə YAZI metodu
    yoxdur, `controllers/screen_data.py` ilə eyni "yalnız-oxu" sərhədində
    qalır.
    """

    def __init__(
        self,
        *,
        provider: MultiStoreMetricProvider,
        limits: SystemLimits,
        clock: Clock,
    ) -> None:
        self._provider = provider
        self._limits = limits
        self._clock = clock

    # ------------------------------ 1. Reytinq -------------------------------- #

    def ranking(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        metric: BenchmarkMetric,
        now: datetime | None = None,
    ) -> list[RankingRow]:
        """Bütün filialları metrikə görə ƏN YAXŞIDAN ƏN PİSƏ sıralayır."""
        moment = self._require(actor, tenant_id, now)
        current_start, current_end = _month_bounds(moment.date())
        previous_start, previous_end = _month_bounds(_shift_months(current_start, -1))

        stores = self._provider.active_stores(tenant_id)
        # PERF-5: cari VƏ əvvəlki ay BİR gediş-gəlişdə (bax
        # `BatchedMetricProvider`). Toplu oxunu dəstəkləməyən provayder köhnə
        # iki çağırışı işlədir — NƏTİCƏ EYNİDİR.
        current, previous = self._metric_windows(
            tenant_id,
            metric,
            windows=[(current_start, current_end), (previous_start, previous_end)],
        )

        # Yalnız AKTİV (kataloqda olan) filiallar sıralanır — bağlanmış
        # mağazanın köhnə qeydi reytinqi təhrif etməsin.
        entries = [
            (store_id, stores[store_id], value)
            for store_id, value in current.items()
            if store_id in stores
        ]
        # "Ən yaxşı" başdadır: `lower_is_better` doğrudursa ARTAN, əks
        # halda AZALAN sıra (bax modul başlığı — metrikin ÖZÜ qərar verir).
        entries.sort(key=lambda item: item[2], reverse=not metric.lower_is_better)

        rows: list[RankingRow] = []
        for rank, (store_id, name, value) in enumerate(entries, start=1):
            previous_value = previous.get(store_id)
            rows.append(
                RankingRow(
                    rank=rank,
                    store_id=store_id,
                    store_name=name,
                    value=value,
                    display_value=format_metric_value(value, metric),
                    previous_value=previous_value,
                    trend=_trend_direction(value, previous_value),
                )
            )
        return rows

    # ------------------------- 2. Mağaza vs Şəbəkə ---------------------------- #

    def store_vs_network(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        metric: BenchmarkMetric,
        store_id: StoreId,
        now: datetime | None = None,
    ) -> StoreVsNetworkView:
        """Tək mağazanın dəyərini ŞƏBƏKƏ ORTALAMASI ilə yan-yana qoyur."""
        moment = self._require(actor, tenant_id, now)
        start, end = _month_bounds(moment.date())
        stores = self._provider.active_stores(tenant_id)
        values = self._provider.metric_values(tenant_id, metric, start=start, end=end)

        network_values = list(values.values())
        return StoreVsNetworkView(
            metric=metric,
            store_id=store_id,
            store_name=stores.get(store_id, "—"),
            store_value=values.get(store_id),
            network_average=fmean(network_values) if network_values else None,
            network_store_count=len(network_values),
        )

    # ---------------------------- 3. Zaman-trend ------------------------------ #

    def trend(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        metric: BenchmarkMetric,
        store_id: StoreId | None = None,
        now: datetime | None = None,
    ) -> list[TrendPoint]:
        """Son N ayın dəyəri — `store_id=None` olduqda ŞƏBƏKƏ-miqyaslı.

        N — ROOT PARAMETRİDİR (`BENCHMARK_TREND_MONTHS`, bax modul başlığı).
        """
        moment = self._require(actor, tenant_id, now)
        months = max(
            1,
            self._limits.get_int(
                tenant_id,
                SystemLimitKey.BENCHMARK_TREND_MONTHS.value,
                _FALLBACK_TREND_MONTHS,
            ),
        )
        anchor = _month_bounds(moment.date())[0]

        windows: list[tuple[date, date]] = []
        for offset in range(months - 1, -1, -1):
            month_start = _shift_months(anchor, -offset)
            windows.append((month_start, _shift_months(month_start, 1)))

        monthly = self._metric_windows(tenant_id, metric, windows=windows)

        points: list[TrendPoint] = []
        for (month_start, _), values in zip(windows, monthly, strict=True):
            value = values.get(store_id) if store_id is not None else _network_value(values, metric)
            points.append(TrendPoint(period_label=f"{month_start:%Y-%m}", value=value))
        return points

    def _metric_windows(
        self,
        tenant_id: TenantId,
        metric: BenchmarkMetric,
        *,
        windows: Sequence[tuple[date, date]],
    ) -> list[dict[StoreId, float]]:
        """Bir neçə aralığın dəyəri — mümkünsə BİR gediş-gəlişdə (PERF-5).

        Provayder `metric_values_by_period`-i DƏSTƏKLƏYİRSƏ o çağırılır;
        dəstəkləmirsə (testlərin yaddaş-daxili sahtələri) hər aralıq ayrıca
        oxunur. NƏTİCƏ HƏR İKİ YOLDA EYNİDİR — fərq YALNIZ sorğu sayındadır,
        ona görə çağıran metodlar (`ranking`, `trend`) hansı yolun işlədiyini
        bilmir və bilməməlidir (bax `BatchedMetricProvider` başlığı).
        """
        batched = getattr(self._provider, "metric_values_by_period", None)
        if batched is not None:
            values: list[dict[StoreId, float]] = batched(tenant_id, metric, periods=windows)
            return values
        return [
            self._provider.metric_values(tenant_id, metric, start=start, end=end)
            for start, end in windows
        ]

    # ---------------------------- 4. Kənar-kart ------------------------------- #

    def outliers(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        metric: BenchmarkMetric,
        now: datetime | None = None,
    ) -> OutlierReport:
        """Şəbəkə ortalamasından σ-hədddindən kənar mağazalar.

        σ HƏDDİ ROOT PARAMETRİDİR (`BENCHMARK_OUTLIER_SIGMA_MULTIPLIER`).
        Sıfır/tək mağaza VƏ bütün dəyərlər eyni (σ=0) hallarında BOŞ
        nəticə qaytarılır — sıfıra bölmə YOXDUR (kompasos11.md #24 açıq
        tələbi).
        """
        moment = self._require(actor, tenant_id, now)
        sigma = _parse_float(
            self._limits.get_str(
                tenant_id,
                SystemLimitKey.BENCHMARK_OUTLIER_SIGMA_MULTIPLIER.value,
                str(_FALLBACK_SIGMA_MULTIPLIER),
            ),
            fallback=_FALLBACK_SIGMA_MULTIPLIER,
        )
        start, end = _month_bounds(moment.date())
        stores = self._provider.active_stores(tenant_id)
        values = self._provider.metric_values(tenant_id, metric, start=start, end=end)
        entries = [
            (store_id, stores[store_id], value)
            for store_id, value in values.items()
            if store_id in stores
        ]

        # TƏK/SIFIR mağaza — statistik sapma anlayışı mənasızdır.
        if len(entries) < 2:  # noqa: PLR2004 — "ən azı iki nöqtə" statistik minimumdur
            return OutlierReport(
                metric=metric, mean=None, stdev=None, threshold_sigma=sigma, outliers=()
            )

        raw_values = [value for _, _, value in entries]
        mean = fmean(raw_values)
        spread = pstdev(raw_values)

        # BÜTÜN DƏYƏRLƏR EYNİDİR (σ=0) — kənarlaşma yoxdur, sıfıra bölmə YOXDUR.
        if spread == 0:
            return OutlierReport(
                metric=metric, mean=mean, stdev=0.0, threshold_sigma=sigma, outliers=()
            )

        found = [
            OutlierStore(
                store_id=store_id,
                store_name=name,
                value=value,
                deviation_sigma=abs(value - mean) / spread,
                above_average=value > mean,
            )
            for store_id, name, value in entries
            if abs(value - mean) >= sigma * spread
        ]
        found.sort(key=lambda outlier: outlier.deviation_sigma, reverse=True)
        return OutlierReport(
            metric=metric,
            mean=mean,
            stdev=spread,
            threshold_sigma=sigma,
            outliers=tuple(found),
        )

    # ------------------------------- köməkçi ---------------------------------- #

    def _require(self, actor: Employee, tenant_id: TenantId, now: datetime | None) -> datetime:
        """`GÖRMƏK = SƏLAHİYYƏTİN OLMASI` — ikinci qat (bax modul başlığı)."""
        moment = now or self._clock.now()
        if actor.tenant_id != tenant_id:
            raise AuthorizationError(
                "Aktor bu kirayəçiyə aid deyil", context={"actor_id": str(actor.id)}
            )
        if not actor.has_permission(VIEW_BENCHMARK_FLAG, now=moment):
            _security_log.warning(
                "BENCHMARK_VIEW_DENIED",
                extra={"actor_id": str(actor.id), "flag": VIEW_BENCHMARK_FLAG},
            )
            raise AuthorizationError(
                f"«{VIEW_BENCHMARK_FLAG}» səlahiyyəti yoxdur",
                user_message="Bu məlumata baxmaq səlahiyyətiniz yoxdur.",
                context={"flag": VIEW_BENCHMARK_FLAG},
            )
        return moment


# --------------------------------------------------------------------------- #
# Modul-səviyyəli köməkçilər
# --------------------------------------------------------------------------- #


def _month_bounds(reference: date) -> tuple[date, date]:
    """Verilən tarixin ayı — `[başlanğıc, sonrakı ayın başlanğıcı)`."""
    start = reference.replace(day=1)
    return start, _shift_months(start, 1)


def _shift_months(reference: date, delta: int) -> date:
    """Ayın 1-i ilə işləyir — hər ayın gün sayı fərqli olduğu üçün TƏHLÜKƏSİZ
    yeganə üsul illik/aylıq indeksi tam ədəd kimi sürüşdürməkdir."""
    total = reference.year * 12 + (reference.month - 1) + delta
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def _trend_direction(current: float, previous: float | None) -> TrendDirection:
    if previous is None:
        return TrendDirection.FLAT
    if current > previous:
        return TrendDirection.UP
    if current < previous:
        return TrendDirection.DOWN
    return TrendDirection.FLAT


def _network_value(values: dict[StoreId, float], metric: BenchmarkMetric) -> float | None:
    """Filial seçilmədən şəbəkə-miqyaslı dəyər — metrikin `network_aggregation`-ı."""
    if not values:
        return None
    numbers = list(values.values())
    if metric.network_aggregation is _NetworkAggregation.SUM:
        return sum(numbers)
    return fmean(numbers)


def format_metric_value(value: float | None, metric: BenchmarkMetric) -> str:
    """Ekranda göstərilən mətn — say tam ədəd, qalanı bir onluq həssaslıqla.

    `None` (məlumat yoxdur) "—" ilə göstərilir — 0.0 İLƏ QARIŞDIRILMIR, çünki
    "heç bir qeyd yoxdur" ilə "dəyər sıfırdır" fərqi istifadəçiyə vacibdir
    (bax `MultiStoreMetricProvider.metric_values` şərhi).
    """
    if value is None:
        return "—"
    if metric is BenchmarkMetric.FINE_COUNT:
        return f"{round(value)}{metric.unit_suffix}"
    return f"{value:.1f}{metric.unit_suffix}"


def _parse_float(raw: str, *, fallback: float) -> float:
    """`system_limits`-dən onluq ədəd oxuyur — yararsız mətn fallback-a düşür
    (`behavior_baseline._parse_float` ilə EYNİ naxış)."""
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return fallback


__all__ = [
    "VIEW_BENCHMARK_FLAG",
    "BenchmarkMetric",
    "MultiStoreBenchmarkUseCase",
    "MultiStoreMetricProvider",
    "OutlierReport",
    "OutlierStore",
    "RankingRow",
    "StoreVsNetworkView",
    "TrendDirection",
    "TrendPoint",
    "format_metric_value",
]
