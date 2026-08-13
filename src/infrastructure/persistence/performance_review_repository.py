"""#20 Performans Qiymətləndirməsi saxlama qatı — `performance_reviews`.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — tətbiq səhvən owner rolu ilə qoşulsa
(RLS onda tətbiq olunmur), izolyasiya bu şərtlə qalır (`pos_policy_repository.py`
ilə eyni naxış).

`ratings_json` YAZILMASI/OXUNMASI — `exception_repositories.py::context_json`
ilə EYNİ naxış: yazıda `json.dumps(...)` + `%s::jsonb`, oxuda həm sətir, həm
artıq-Python-obyekti halını dəstəkləyən köməkçi (`_as_ratings`). Layihədə bu
iki naxış (`Jsonb` adaptoru YOX) artıq TƏKRARLANIB, ona görə üçüncü bir üslub
əlavə edilmir.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from src.domain.entities.performance_review import PerformanceReview
from src.domain.value_objects.identifiers import EmployeeId, PerformanceReviewId, TenantId
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

_log = get_logger(__name__)


class PostgresPerformanceReviewRepository(_BaseRepository):
    """`performance_reviews` — bir işçi + bir dövr = BİR sətir (UNIQUE)."""

    _SELECT = """
        SELECT id, tenant_id, employee_id, reviewer_id, period, ratings_json,
               overall_score, notes, created_at, updated_at
        FROM performance_reviews
    """

    def get(
        self, tenant_id: TenantId, employee_id: EmployeeId, period: str
    ) -> PerformanceReview | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE tenant_id = %s AND employee_id = %s AND period = %s",
            (tenant_id, employee_id, period),
        )
        return _row_to_review(row) if row else None

    def list_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> list[PerformanceReview]:
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s AND employee_id = %s ORDER BY period DESC",
            (tenant_id, employee_id),
        )
        return [_row_to_review(row) for row in rows]

    def save(self, record: PerformanceReview) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id, period)`.

        `id` YENİLƏMƏDƏ TOXUNULMUR (`pos_permission_thresholds.save` ilə
        eyni naxış): eyni dövrün YENİLƏNMƏSİ sətrin İDENTİTİSİNİ dəyişmir —
        audit jurnalındakı `entity_id` istinadları qırılmamalıdır.
        `reviewer_id` isə TƏKRAR göndərişdə DƏYİŞƏ bilər (son qiymətləndirən
        kimdirsə sətir ONUN adına keçir, bax `PerformanceReview.update_ratings`).
        """
        self._execute(
            """
            INSERT INTO performance_reviews
                (id, tenant_id, employee_id, reviewer_id, period, ratings_json,
                 overall_score, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, employee_id, period) DO UPDATE
                SET reviewer_id   = EXCLUDED.reviewer_id,
                    ratings_json  = EXCLUDED.ratings_json,
                    overall_score = EXCLUDED.overall_score,
                    notes         = EXCLUDED.notes,
                    updated_at    = EXCLUDED.updated_at
            """,
            (
                record.id,
                record.tenant_id,
                record.employee_id,
                record.reviewer_id,
                record.period,
                json.dumps(record.ratings, ensure_ascii=False),
                record.overall_score,
                record.notes,
                record.created_at,
                record.updated_at,
            ),
        )


def _row_to_review(row: dict[str, Any]) -> PerformanceReview:
    return PerformanceReview(
        review_id=PerformanceReviewId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        reviewer_id=EmployeeId(row["reviewer_id"]),
        period=row["period"],
        ratings=_as_ratings(row["ratings_json"]),
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        # DB-dəki HESABLANMIŞ dəyər OLDUĞU KİMİ oxunur — YENİDƏN
        # hesablanmır (`entities/performance_review.py` başlığı).
        overall_score=(None if row["overall_score"] is None else Decimal(row["overall_score"])),
        # BƏRPA hadisə YAYMIR — əks halda hər siyahı oxunuşu "yeni
        # qiymətləndirmə yazıldı" bildirişi doğurardı.
        emit_created_event=False,
    )


def _as_ratings(raw: Any) -> dict[str, int]:
    """`ratings_json` sütununu `dict[str, int]`-ə çevirir.

    `exception_repositories._as_context` ilə EYNİ qərar: sürücü `jsonb`-i
    artıq Python obyekti kimi qaytarır, lakin sətir halı da emal olunur ki,
    format fərqi ekranı sındırmasın. Pozulmuş dəyər sükutla BOŞ lüğətə
    çevrilir — sətir bütövlükdə gizlədilməkdənsə, boş KPI cədvəli ilə
    göstərilməsi daha az zərərlidir.
    """
    if isinstance(raw, str):
        try:
            value: Any = json.loads(raw)
        except (TypeError, ValueError):
            _log.warning("PERFORMANCE_REVIEW_RATINGS_UNREADABLE", extra={"raw_length": len(raw)})
            return {}
    else:
        value = raw
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, int] = {}
    for key, item in value.items():
        try:
            cleaned[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return cleaned


__all__ = ["PostgresPerformanceReviewRepository"]
