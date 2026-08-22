"""Çox-Mağaza Benchmark Dashboard-un aqreqasiya qatı — #24, kompasos11.md Faza 9A.

`application.use_cases.multi_store_benchmark.MultiStoreMetricProvider`-in
Postgres tətbiqi. Hər metrik ÖZ, TAM statik SQL sətrindən oxunur —
dinamik `WHERE` şərti YOXDUR, metrik seçimi `_METRIC_QUERIES` sabit lüğətindən
gəlir (CLAUDE.md bölmə 4: "dinamik metrik seçimi SQL-ə sətir-birləşdirmə ilə
GİRMƏSİN"). Hər sorğu tam literal mətndir — heç bir f-string/`.format()`/`%`
ilə QURULMUR, ona görə bandit S608 xəbərdarlığı BURADA yaranmır (müqayisə
üçün bax `config_repositories.py::list_range` — orada dinamik `AND` siyahısı
VAR və `noqa: S608` ORADADIR).

──────────────────────────────────────────────────────────────────────────────
1C SƏRHƏDİ
──────────────────────────────────────────────────────────────────────────────
Sorğular YALNIZ `fines`, `daily_attendance_sheets`/`_lines`, `points_ledger`,
`overtime_log`, `attrition_risk_scores`, `field_reports`/`field_report_*` və
`employees`/`stores` cədvəllərinə toxunur. `sales_transactions`/`erp_servers`
HEÇ YERDƏ görünmür (statik `ast` qapısı: `tests/unit/test_benchmark_widgets.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR SORĞU `store_id`-Sİ OLMAYAN SƏTRİ ATIR
──────────────────────────────────────────────────────────────────────────────
Nəticə dict-i YALNIZ dəyəri olan mağazaları ehtiva edir (`GROUP BY` təbii
olaraq bunu edir) — istifadəçi qatı (use case) "məlumat yoxdur" ilə "dəyər
sıfırdır" fərqini BUNDAN çıxarır (bax use case modul başlığı).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from src.application.use_cases.multi_store_benchmark import BenchmarkMetric
from src.domain.value_objects.identifiers import StoreId
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection

    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.persistence.connection import TenantContext

#: Aktiv filiallar — reytinq/outlier/store-vs-network HAMISININ bazası.
_ACTIVE_STORES_QUERY: Final = """
    SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name
"""

#: Metrik → TAM statik SQL. Hər sorğu `(tenant_id, start, end)` ilə çağırılır
#: və `store_id, value` sütunlarını qaytarır (bax modul başlığı).
_METRIC_QUERIES: Final[dict[BenchmarkMetric, str]] = {
    # Cərimə sayı — `_dashboard_fines` ilə EYNİ əsaslandırma: idarəetmə
    # göstəricisidir, hesabat ixracı deyil, ona görə BÜTÜN statuslar (o
    # cümlədən hələ nəşr olunmamış `PENDING_REVIEW`) daxildir.
    BenchmarkMetric.FINE_COUNT: """
        SELECT store_id AS store_id, COUNT(*) AS value
          FROM fines
         WHERE tenant_id = %s AND fine_date >= %s AND fine_date < %s
         GROUP BY store_id
    """,
    # Davamiyyət faizi — `daily_attendance_sheet_lines.auto_status`
    # `AutoAttendanceStatus.counts_as_worked` domen tərifinin SQL güzgüsüdür
    # (bax `domain/entities/attendance_sheet.py`): VERIFIED/LATE/OUTSIDE/
    # UNPLANNED "işlənilib" sayılır, OFF_DAY/PENDING isə məxrəcdən DƏ çıxılır
    # (istirahət günü və günün hələ bitməməsi "davamsızlıq" deyil).
    BenchmarkMetric.ATTENDANCE_RATE: """
        SELECT das.store_id AS store_id,
               100.0 * COUNT(*) FILTER (
                   WHERE dal.auto_status IN ('VERIFIED', 'LATE', 'OUTSIDE', 'UNPLANNED')
               ) / COUNT(*) FILTER (WHERE dal.auto_status NOT IN ('OFF_DAY', 'PENDING')) AS value
          FROM daily_attendance_sheets das
          JOIN daily_attendance_sheet_lines dal ON dal.sheet_id = das.id
         WHERE das.tenant_id = %s AND das.sheet_date >= %s AND das.sheet_date < %s
         GROUP BY das.store_id
        -- Məxrəc sıfır olan qrup (bütün sətirlər OFF_DAY/PENDING) BURADA
        -- SÜZÜLÜR — sıfıra bölmə DB SƏVİYYƏSİNDƏ baş vermir.
        HAVING COUNT(*) FILTER (WHERE dal.auto_status NOT IN ('OFF_DAY', 'PENDING')) > 0
    """,
    # Xal balansı — MÖVCUD, icazəli 1C-bal-kanalından (`points_ledger`) gəlir,
    # `_dashboard_leaders`-lə EYNİ `status <> 'REVERSED'` süzgəci. YENİ
    # bağlantı YOXDUR — `sales_transactions` FK-si BURADA HEÇ oxunmur.
    BenchmarkMetric.POINTS_BALANCE: """
        SELECT e.store_id AS store_id, COALESCE(SUM(l.delta_points), 0) AS value
          FROM points_ledger l
          JOIN employees e ON e.id = l.employee_id
         WHERE l.tenant_id = %s AND l.created_at >= %s AND l.created_at < %s
           AND l.status <> 'REVERSED'
         GROUP BY e.store_id
    """,
    # Overtime saatı — #15-in `overtime_log.hours_over_norm` sütunu, mağazaya
    # `employees.store_id` ilə bağlanır (jurnalın özündə store_id yoxdur).
    BenchmarkMetric.OVERTIME_HOURS: """
        SELECT e.store_id AS store_id, COALESCE(SUM(ol.hours_over_norm), 0) AS value
          FROM overtime_log ol
          JOIN employees e ON e.id = ol.employee_id
         WHERE ol.tenant_id = %s AND ol.work_date >= %s AND ol.work_date < %s
         GROUP BY e.store_id
    """,
    # Turnover riski — #21-in NATİV NƏTİCƏSİ (`attrition_risk_scores.score`),
    # hər işçinin PƏNCƏRƏ daxilindəki ƏN SON balı orta alınır (DISTINCT ON —
    # `AttritionRiskScoreRepository.get_latest_for_employee` ilə EYNİ "ən son
    # tarix" məntiqi, tək sorğuya sıxılmış).
    BenchmarkMetric.TURNOVER_RISK: """
        SELECT latest.store_id AS store_id, AVG(latest.score) AS value
          FROM (
              SELECT DISTINCT ON (ars.employee_id)
                     e.store_id AS store_id, ars.score AS score
                FROM attrition_risk_scores ars
                JOIN employees e ON e.id = ars.employee_id
               WHERE ars.tenant_id = %s AND ars.score_date >= %s AND ars.score_date < %s
               ORDER BY ars.employee_id, ars.score_date DESC
          ) AS latest
         GROUP BY latest.store_id
    """,
    # Audit balı — #26-nın NATİV nəticəsi (Struktur Qərar C: AYRI ekran YOX).
    # `FieldReport.audit_score` domen tərifinin SQL güzgüsüdür: keçən
    # bəndlərin CAVABLANMIŞ bəndlərə nisbəti.
    #
    # ŞABLON KODU SQL-Ə YAZILMIR (`fr.type = 'STORE_AUDIT'` YOXDUR): "audit"
    # tərifi kataloqdadır (`field_report_types.requires_checklist`), yəni
    # gələcəkdə əlavə edilən checklist-li şablon BİR `INSERT` ilə bu metrikə
    # daxil olur və bu sətir DƏYİŞMİR (Struktur Qərar A).
    #
    # `fri.passed IS NOT NULL` süzgəci HƏM MƏNA, HƏM TƏHLÜKƏSİZLİK daşıyır:
    # cavabsız bənd nə uğur, nə uğursuzluqdur (037: üç vəziyyət) və eyni
    # zamanda məxrəci sıfırlaya bilməz — süzgəcdən sonra qrup YALNIZ ən azı
    # bir cavablanmış bənd olduqda mövcuddur, yəni SIFIRA BÖLMƏ BAŞ VERMİR
    # (`ATTENDANCE_RATE`-dəki `HAVING` bu səbəbdən burada LAZIM DEYİL).
    BenchmarkMetric.AUDIT_SCORE: """
        SELECT fr.store_id AS store_id,
               100.0 * COUNT(*) FILTER (WHERE fri.passed) / COUNT(*) AS value
          FROM field_reports fr
          JOIN field_report_types frt ON frt.code = fr.type AND frt.requires_checklist
          JOIN field_report_checklist_items fri ON fri.report_id = fr.id
         WHERE fr.tenant_id = %s AND fr.created_at >= %s AND fr.created_at < %s
           AND fri.passed IS NOT NULL
         GROUP BY fr.store_id
    """,
}


class PostgresMultiStoreBenchmarkRepository(_BaseRepository):
    """`MultiStoreMetricProvider`-in Postgres tətbiqi (#24).

    ──────────────────────────────────────────────────────────────────────────
    NÜSXƏ-SƏVİYYƏLİ KEŞ (QA-FULL Faza 5, ölçülüb)
    ──────────────────────────────────────────────────────────────────────────
    `MultiStoreBenchmarkUseCase`-in 4 metodu (`ranking`, `store_vs_network`,
    `trend`, `outliers`) `screen_data.py::_populate_benchmark_sections`
    tərəfindən EYNİ sessiyada ARDICIL çağırılır və CARİ ayın aralığı ÜÇÜNÜN
    ÜÇÜNDƏ DƏ (ranking-in "current"i, store_vs_network, outliers) EYNİDİR —
    `trend`-in son nöqtəsi də həmin aya düşür. Ölçü: eyni `(tenant_id, metric,
    start, end)` üçün `metric_values` **9 dəfə** çağırılıb (biri 409 ms).

    Use case-in ÖZÜ bu təkrarı BİLMİR — hər metod `_provider.metric_values(...)`
    çağırır və aralar arasında əlaqəni GÖRMÜR (bilərəkdən: `MultiStoreMetricProvider`
    sadə "verilmiş aralıq üçün dəyər ver" portudur). Keşi BURADA saxlamaq
    use case-i DƏYİŞMƏDƏN eyni SQL-i təkrarlamağın qarşısını alır — repo
    nüsxəsi `PostgresSystemLimits`/`PostgresFeatureToggles` ilə EYNİ ömrə
    malikdir (`connection.py::_build_repositories`, bir `UnitOfWork`).
    """

    def __init__(self, conn: Connection[dict[str, Any]], context: TenantContext) -> None:
        super().__init__(conn, context)
        self._cache: dict[tuple[TenantId, BenchmarkMetric, date, date], dict[StoreId, float]] = {}
        self._stores: dict[TenantId, dict[StoreId, str]] = {}

    def active_stores(self, tenant_id: TenantId) -> dict[StoreId, str]:
        """Aktiv filiallar — EYNİ tranzaksiyada TƏKRAR SORĞU ATMIR.

        `metric_values` keşi ilə eyni səbəb və eyni ömür (bax sinif başlığı):
        use case-in dörd metodundan İKİSİ (`ranking`, `outliers`) filial
        siyahısını ayrıca istəyir və açılış ölçüsündə eyni
        `SELECT id, name FROM stores ...` sorğusu **2 dəfə** — hər biri
        ~206 ms — işə düşürdü.
        """
        cached = self._stores.get(tenant_id)
        if cached is None:
            rows = self._fetch_all(_ACTIVE_STORES_QUERY, (tenant_id,))
            cached = {StoreId(row["id"]): str(row["name"]) for row in rows}
            self._stores[tenant_id] = cached
        return dict(cached)  # kopya — çağıran yerində dəyişsə keş korlanmasın

    def metric_values(
        self, tenant_id: TenantId, metric: BenchmarkMetric, *, start: date, end: date
    ) -> dict[StoreId, float]:
        cache_key = (tenant_id, metric, start, end)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)  # kopya — çağıran yerində dəyişsə keş korlanmasın

        query = _METRIC_QUERIES[metric]
        rows = self._fetch_all(query, (tenant_id, start, end))
        result = {
            StoreId(row["store_id"]): float(row["value"])
            for row in rows
            if row["store_id"] is not None and row["value"] is not None
        }
        self._cache[cache_key] = result
        return dict(result)


__all__ = ["PostgresMultiStoreBenchmarkRepository"]
