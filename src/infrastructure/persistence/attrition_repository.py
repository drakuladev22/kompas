"""İşdən Çıxma Riski — SQL aqreqasiyası və tarixçə saxlanması (#21, Faza 9).

`AttritionRiskUseCase` HESABLAMIR, YALNIZ ÇAĞIRIR: xam siqnalların (cərimə,
davamiyyət, icazə) YIĞILMASI burada, BİR sorğu ilə aparılır
(`report_repositories.py` başlığı: "21 filialın bütün davamiyyət qeydlərini
yaddaşa yükləmək demək olardı" — eyni əsaslandırma, gecəlik iş yüzlərlə işçini
emal edir).

──────────────────────────────────────────────────────────────────────────────
1C SƏRHƏDİ — statik `ast` qapısı bu faylı da əhatə edir
──────────────────────────────────────────────────────────────────────────────
`tests/unit/test_attrition_risk.py` bu modulun mətnində `erp`/`sales` idxalını
və `SalesDataConnector`/`OneCSaleRecord` kimi 1C identifikatorlarını YOXLAYIR.
Aşağıdakı sorğular YALNIZ `employees`, `fines`, `attendance_records`,
`leave_requests` cədvəllərinə toxunur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BİR SİNİF İKİ PROTOKOLU BİRLİKDƏ TƏTBİQ EDİR
──────────────────────────────────────────────────────────────────────────────
`PostgresAttritionRepository` HƏM `domain.interfaces.ports.
AttritionRiskScoreRepository`-i (saxlama/oxuma), HƏM DƏ `application.
use_cases.attrition_risk.AttritionSignalProvider`-i (xam siqnal yığımı)
strukturaldır (Protocol — miras YOX). İkisi EYNİ cədvəl ailəsinə (`attrition_
risk_scores` + `fines`/`attendance_records`/`leave_requests`) toxunduğu üçün
ayrı sinifə bölmək YALNIZ eyni bağlantını iki dəfə keçirən boilerplate
yaradardı — `report_repositories.PostgresReportFactProvider`-in İKİ hesabatı
BİR sinifdə saxlaması ilə EYNİ qərar. `composition.py` bu TƏK nüsxəni İKİ
açarla (`attrition_scores`, `attrition_signals`) qeydiyyatdan keçirir.

──────────────────────────────────────────────────────────────────────────────
CƏRİMƏ SAYĞACI NİYƏ `REVERSED`-İ İSTİSNA EDİR
──────────────────────────────────────────────────────────────────────────────
Tam ləğv olunmuş (`REVERSED`) cərimə YANLIŞ İTTİHAM demək ola bilər — onu risk
siqnalına qatmaq işçini ÖZ günahı olmayan bir hadisəyə görə cəzalandırardı.
`PENDING_REVIEW`/`PUBLISHED`/`REDUCED` isə qalır: hamısı REAL qeydə alınmış
hadisədir, son maliyyə nəticəsindən (endirim, icmal) asılı olmayaraq.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.application.use_cases.attrition_risk import EmployeeAttritionSignals
from src.domain.attrition_rules import AttritionRiskScore
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import date

_log = get_logger(__name__)

#: Bir "ayın" gün qarşılığı — `domain.attrition_rules._DAYS_PER_MONTH` ilə
#: EYNİ təxmini (dəqiq təqvim ay riyaziyyatı bu pəncərə üçün lazımsızdır).
_DAYS_PER_MONTH = 30

#: Ləğv olunmuş cərimə risk siqnalına DAXİL EDİLMİR (bax modul başlığı).
_EXCLUDED_FINE_STATUS = "REVERSED"


class PostgresAttritionRepository(_BaseRepository):
    """`attrition_risk_scores` saxlaması VƏ xam siqnal aqreqasiyası (#21)."""

    # ------------------------- AttritionSignalProvider ------------------------ #

    def list_signals(
        self, tenant_id: TenantId, *, window_months: int, as_of: date
    ) -> list[EmployeeAttritionSignals]:
        """Aktiv işçilərin dörd xam siqnalını BİR sorğuda yığır.

        Pəncərə `window_months × 30` günə çevrilir və ORTADAN iki yarıya
        bölünür (`midpoint`) — FINE_TREND siqnalı sonuncu yarımla əvvəlki
        yarımı müqayisə edir (bax `attrition_rules.py` başlığı).
        """
        window_days = max(1, window_months) * _DAYS_PER_MONTH
        window_start = as_of - timedelta(days=window_days)
        midpoint = as_of - timedelta(days=window_days // 2)

        rows = self._fetch_all(
            """
            SELECT e.id        AS employee_id,
                   e.store_id  AS store_id,
                   e.hire_date AS hire_date,
                   COALESCE(fines.recent, 0)  AS fine_count_recent_half,
                   COALESCE(fines.prior, 0)   AS fine_count_prior_half,
                   COALESCE(att.absences, 0)  AS unauthorized_absences,
                   COALESCE(lv.used_minutes, 0) AS leave_minutes_used
            FROM employees e
            LEFT JOIN LATERAL (
                SELECT
                    count(*) FILTER (WHERE f.fine_date >= %s AND f.fine_date < %s) AS recent,
                    count(*) FILTER (WHERE f.fine_date >= %s AND f.fine_date < %s) AS prior
                FROM fines f
                WHERE f.employee_id = e.id AND f.status <> %s
            ) fines ON TRUE
            LEFT JOIN LATERAL (
                SELECT count(*) FILTER (WHERE ar.is_unauthorized_absence) AS absences
                FROM attendance_records ar
                WHERE ar.employee_id = e.id
                  AND ar.work_date >= %s AND ar.work_date < %s
            ) att ON TRUE
            LEFT JOIN LATERAL (
                SELECT COALESCE(sum(lr.total_minutes), 0) AS used_minutes
                FROM leave_requests lr
                WHERE lr.employee_id = e.id AND lr.status = 'VERIFIED'
                  AND date_part('year', lr.requested_time) = %s
                  AND date_part('month', lr.requested_time) = %s
            ) lv ON TRUE
            WHERE e.tenant_id = %s AND e.is_active
            ORDER BY e.last_name, e.first_name
            """,
            (
                midpoint,
                as_of,
                window_start,
                midpoint,
                _EXCLUDED_FINE_STATUS,
                window_start,
                as_of,
                as_of.year,
                as_of.month,
                tenant_id,
            ),
        )
        return [
            EmployeeAttritionSignals(
                employee_id=EmployeeId(row["employee_id"]),
                store_id=StoreId(row["store_id"]) if row["store_id"] is not None else None,
                hire_date=row["hire_date"],
                fine_count_recent_half=int(row["fine_count_recent_half"]),
                fine_count_prior_half=int(row["fine_count_prior_half"]),
                unauthorized_absences=int(row["unauthorized_absences"]),
                leave_minutes_used=int(row["leave_minutes_used"]),
            )
            for row in rows
        ]

    # ------------------------- AttritionRiskScoreRepository ------------------- #

    def save(self, score: AttritionRiskScore) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id, score_date)`.

        Gün ərzində təkrar icra (məs. manual "indi hesabla") KÖHNƏ sətri
        ƏVƏZLƏYİR — migrations/020 şərhi: "gün başına bir sətir, təkrar
        hesablama UPSERT edir".
        """
        self._execute(
            """
            INSERT INTO attrition_risk_scores
                (tenant_id, employee_id, score, factors_json, score_date, calculated_at)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (tenant_id, employee_id, score_date) DO UPDATE
                SET score         = EXCLUDED.score,
                    factors_json  = EXCLUDED.factors_json,
                    calculated_at = EXCLUDED.calculated_at
            """,
            (
                score.tenant_id,
                score.employee_id,
                score.score,
                json.dumps(score.factors, ensure_ascii=False, default=str),
                score.score_date,
                score.calculated_at,
            ),
        )

    def get_latest_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> AttritionRiskScore | None:
        row = self._fetch_one(
            """
            SELECT tenant_id, employee_id, score, factors_json, score_date, calculated_at
            FROM attrition_risk_scores
            WHERE tenant_id = %s AND employee_id = %s
            ORDER BY score_date DESC
            LIMIT 1
            """,
            (tenant_id, employee_id),
        )
        return _row_to_score(row) if row else None

    def list_latest_for_tenant(self, tenant_id: TenantId) -> list[AttritionRiskScore]:
        """Hər işçinin ƏN SON sətri — `DISTINCT ON` `idx_attrition_scores_employee`
        indeksini işlədir (migrations/020: `(employee_id, score_date DESC)`)."""
        rows = self._fetch_all(
            """
            SELECT DISTINCT ON (employee_id)
                   tenant_id, employee_id, score, factors_json, score_date, calculated_at
            FROM attrition_risk_scores
            WHERE tenant_id = %s
            ORDER BY employee_id, score_date DESC
            """,
            (tenant_id,),
        )
        return [_row_to_score(row) for row in rows]


def _row_to_score(row: dict[str, Any]) -> AttritionRiskScore:
    return AttritionRiskScore(
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        score=float(row["score"]),
        factors=_as_factors(row["factors_json"]),
        score_date=row["score_date"],
        calculated_at=row["calculated_at"],
    )


def _as_factors(raw: Any) -> dict[str, dict[str, object]]:
    """`factors_json` sütununu lüğətə çevirir.

    Sürücü `jsonb`-i artıq Python obyekti kimi qaytarır, lakin köhnə
    yazılarda sətir də ola bilər — `exception_repositories._as_context` ilə
    EYNİ ikili emal. POZULMUŞ DƏYƏR SÜKUTLA UDULMUR: boş lüğət qaytarılır
    (`AttritionRiskScore.__post_init__` bunu "izahsız bal" kimi RƏDD EDƏR —
    qərar HƏMİŞƏ izah tələb edir, hətta oxu zamanı da).
    """
    if isinstance(raw, str):
        try:
            value: Any = json.loads(raw)
        except (TypeError, ValueError):
            _log.warning("ATTRITION_FACTORS_UNREADABLE", extra={"raw_length": len(raw)})
            return {}
    else:
        value = raw
    if not isinstance(value, dict):
        return {}
    return {str(key): dict(item) if isinstance(item, dict) else {} for key, item in value.items()}


__all__ = ["PostgresAttritionRepository"]
