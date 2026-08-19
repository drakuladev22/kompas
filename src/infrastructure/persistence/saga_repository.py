"""`saga_instances` — Saga uzlaşma vəziyyətinin DAVAMLI saxlanması (D6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ YADDAŞ-DAXİLİ VERSİYA KİFAYƏT ETMİRDİ
──────────────────────────────────────────────────────────────────────────────
`saga_orchestrator.SagaStateRepository` Protocol-u Faza 1-dən bəri
`InMemorySagaStateRepository`-yə bağlı idi — modulun ÖZ şərhi bunu «Faza 3-də
`saga_instances` cədvəli üzərində implementasiya olunur» deyə etiraf edirdi,
amma HEÇ VAXT yazılmamışdı (`grep SagaStateRepository src/infrastructure`
sıfır nəticə verirdi). `schema.sql:1300`-dəki `saga_instances` cədvəli isə
bütün bu müddətdə YAZANI OLMAYAN boş bir cədvəl idi.

Üstəlik `composition.py`-dakı YEGANƏ real istehsalat çağırışı
(`LeaveVerificationUseCase`) `SagaOrchestrator()`-u SIFIR ARQUMENTLƏ qurur —
yəni `state_repository=None` → HƏR `session()` çağırışında TƏZƏ, boş
`InMemorySagaStateRepository()`. Panel bağlanan kimi (və ya proses çökəndə)
bu obyekt GC olunur.

NƏTİCƏ: `LeaveVerificationUseCase.verify_return`-in Saga-sı uğursuz olub
`PENDING_RECONCILIATION`-a keçəndə (bölmə 1: "audit-kritik məlumat heç vaxt
yarımçıq vəziyyətdə qalmır" tələbinin YEGANƏ təminatçısı) — `_persist()`
(saga_orchestrator.py:622) İSTİSNA ATMADAN "uğurla" yaddaşa yazır, sonra
sessiya bağlananda İZ SİLİNİR. `pending_reconciliation()` HƏMİŞƏ boş qayıdır,
çünki sorğulanan instans YAZILAN instansdan FƏRQLİDİR. Operator «hansı
əməliyyat uzlaşma gözləyir?» sualına HEÇ VAXT cavab ala bilmirdi — yəni
Saga mexanizminin bütün MƏNASI (bölmə 1) sükutla puç olurdu. Bu, satışa
çıxan sistem üçün qəbuledilməzdir (D6).

──────────────────────────────────────────────────────────────────────────────
`context` SÜTUNU YOXDUR — QƏSDƏN
──────────────────────────────────────────────────────────────────────────────
`SagaResult.context` (`SagaContext = dict[str, Any]`) addımların qaytardığı
İSTƏNİLƏN Python obyektini daşıya bilər (entity, exception, s.) — ümumi
JSON-safe deyil və `saga_instances`-da ona uyğun sütun da YOXDUR
(`schema.sql`-ə bu miqrasiya ilə sütun ƏLAVƏ EDİLMİR, bax aşağı). Bu,
BOŞLUQ deyil, sərhəddir: bu repo-nun məqsədi SAGA-nı YENİDƏN İCRA ETMƏK
(resume) deyil, İNSANA GÖRÜNÜRLÜK verməkdir — `pending_reconciliation()`-un
YEGANƏ çağıranı (`main.py::_check_pending_reconciliation`) yalnız SAYĞACI
oxuyur, `.context`-ə toxunmur. `list_pending_reconciliation()`-dan qayıdan
`SagaResult.context` ona görə HƏMİŞƏ `{}`-dir — bu, "məlumat itib" demək
DEYİL, "bu sahə bu qatda mənasızdır" deməkdir.

──────────────────────────────────────────────────────────────────────────────
`tenant_id` NİYƏ `self._tenant`-DƏNDİR, ARQUMENTDƏN YOX
──────────────────────────────────────────────────────────────────────────────
`SagaResult`-un ÖZÜNDƏ `tenant_id` sahəsi YOXDUR (`execute()`-un `tenant_id`
arqumenti yalnız hadisə yayımına gedir, `SagaResult`-a əlavə olunmur) — yəni
bu, INFRA-2-dəki "arqumentə güvənmə" seçimi belə DEYİL, arqumentin özü
mövcud deyil. `self._tenant` (bu repo-nun bağlı olduğu `TenantContext`)
YEGANƏ mənbədir. Bu həm də MƏCBURİDİR: `saga_instances` `tenant_scoped`
siyahısındadır (`schema.sql` §"RLS", `tenant_isolation` policy-si) və
`WITH CHECK (tenant_id = current_tenant_id())` — səhv/NULL `tenant_id` ilə
INSERT RLS tərəfindən BİRBAŞA rədd edilər.

──────────────────────────────────────────────────────────────────────────────
UPSERT RECONCILIATION SÜTUNLARINI ƏZMİR
──────────────────────────────────────────────────────────────────────────────
`save()` praktikada HƏR `saga_id` üçün YALNIZ BİR DƏFƏ çağırılır
(`saga_id = uuid.uuid4()` hər `execute()`-da təzədir), lakin müdafiə xatirinə
`ON CONFLICT (saga_id) DO UPDATE` yazılıb. UPDATE bölməsi `reconciled_by` /
`reconciled_at` / `reconciliation_note` sütunlarına TOXUNMUR — onlar GƏLƏCƏK
bir "uzlaşdırıldı" iş axınının yazacağı sahələrdir (bu miqrasiyanın əhatəsi
DEYİL) və təkrar `save()` çağırışı onları sükutla SIFIRLAMAMALIDIR.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger
from src.shared.saga_orchestrator import (
    CompensationOutcome,
    SagaResult,
    SagaStatus,
    StepExecution,
)

if TYPE_CHECKING:
    from psycopg import Connection

    from src.infrastructure.persistence.connection import TenantContext

_log = get_logger(__name__)


def _serialize_executions(executions: list[StepExecution]) -> str:
    """`step_log` JSONB-ə düşən forma — `%s::jsonb` ilə yazılır.

    Naxış `performance_review_repository.py`-dakı `ratings_json` ilə EYNİDİR
    (`json.dumps(...)` + SQL-də açıq cast) — layihədə `psycopg.types.json.Jsonb`
    adaptoru işlədilmir, üçüncü üslub əlavə edilmir.
    """
    rows = [
        {
            "step_name": execution.step_name,
            "started_at": execution.started_at.isoformat(),
            "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
            "succeeded": execution.succeeded,
            "attempts": execution.attempts,
            "error": execution.error,
            "compensated": execution.compensated,
            "compensation_error": execution.compensation_error,
        }
        for execution in executions
    ]
    return json.dumps(rows, ensure_ascii=False, default=str)


def _deserialize_executions(step_log: Any) -> list[StepExecution]:
    """`step_log`-u geri `StepExecution` siyahısına çevirir.

    `step_log` psycopg3-də ADƏTƏN artıq Python `list`-dir (JSONB avtomatik
    açılır), lakin sətir kimi gələ biləcəyi hallar üçün (məs. xam SQL alət
    ilə yazılmış sətir) müdafiəli — eyni ehtiyat `performance_review_
    repository.py::_as_ratings`-də var.
    """
    rows = json.loads(step_log) if isinstance(step_log, str) else (step_log or [])
    executions: list[StepExecution] = []
    for row in rows:
        executions.append(
            StepExecution(
                step_name=row["step_name"],
                started_at=datetime.fromisoformat(row["started_at"]),
                finished_at=(
                    datetime.fromisoformat(row["finished_at"]) if row.get("finished_at") else None
                ),
                succeeded=bool(row.get("succeeded", False)),
                attempts=int(row.get("attempts", 0)),
                error=row.get("error"),
                compensated=bool(row.get("compensated", False)),
                compensation_error=row.get("compensation_error"),
            )
        )
    return executions


class PostgresSagaStateRepository(_BaseRepository):
    """`SagaStateRepository` Protocol-una STRUCTURAL uyğun (miras YOX, CLAUDE.md §3)."""

    def __init__(self, conn: Connection[dict[str, Any]], context: TenantContext) -> None:
        super().__init__(conn, context)

    def save(self, result: SagaResult) -> None:
        """Saga nəticəsini `saga_instances`-a yazır (UPSERT).

        `context` sahəsi qəsdən yazılmır — bax modul başlığı.
        """
        error_message = f"{type(result.error).__name__}: {result.error}" if result.error else None
        self._execute(
            """
            INSERT INTO saga_instances
                (saga_id, tenant_id, saga_name, status, compensation_outcome,
                 failed_step, error_message, correlation_id, step_log,
                 started_at, finished_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (saga_id) DO UPDATE SET
                status               = EXCLUDED.status,
                compensation_outcome = EXCLUDED.compensation_outcome,
                failed_step          = EXCLUDED.failed_step,
                error_message        = EXCLUDED.error_message,
                step_log             = EXCLUDED.step_log,
                finished_at          = EXCLUDED.finished_at
            """,
            (
                result.saga_id,
                self._tenant,
                result.saga_name,
                result.status.value,
                result.compensation_outcome.value,
                result.failed_step,
                error_message,
                result.correlation_id,
                _serialize_executions(result.executions),
                result.started_at,
                result.finished_at,
            ),
        )

    def list_pending_reconciliation(self) -> list[SagaResult]:
        """`PENDING_RECONCILIATION` statusundakı sagalar — YALNIZ bu kirayəçi.

        Qayıdan `SagaResult.context` HƏMİŞƏ `{}`-dir — bax modul başlığı
        ("`context` SÜTUNU YOXDUR").
        """
        rows = self._fetch_all(
            """
            SELECT saga_id, saga_name, status, compensation_outcome, failed_step,
                   error_message, correlation_id, step_log, started_at, finished_at
            FROM saga_instances
            WHERE tenant_id = %s AND status = %s
            ORDER BY started_at DESC
            """,
            (self._tenant, SagaStatus.PENDING_RECONCILIATION.value),
        )
        return [self._hydrate(row) for row in rows]

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> SagaResult:
        """DB sətrini `SagaResult`-a çevirir.

        `error`: orijinal `Exception` OBYEKTİ heç vaxt saxlanmır (yalnız
        `error_message` mətni) — real tipini bərpa etmək mümkün deyil və
        saxta tip uydurmaq YALANÇI məlumat olardı. Ona görə mətn USTA
        `Exception` daşıyıcısına qoyulur: `SagaResult.to_dict()`-in
        `"error": str(self.error)` sətri operatora ƏSL mesajı göstərməyə
        davam edir (bax `_persist`-in yazdığı format,
        `f"{type(exc).__name__}: {exc}"`), sadəcə `type(error).__name__`
        artıq orijinal sinif adını DEYİL, `Exception`-u göstərir.
        """
        outcome_raw = row["compensation_outcome"]
        saga_id = row["saga_id"]
        return SagaResult(
            saga_id=saga_id if isinstance(saga_id, uuid.UUID) else uuid.UUID(saga_id),
            saga_name=row["saga_name"],
            status=SagaStatus(row["status"]),
            compensation_outcome=(
                CompensationOutcome(outcome_raw)
                if outcome_raw
                else CompensationOutcome.NOT_REQUIRED
            ),
            context={},
            executions=_deserialize_executions(row["step_log"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            failed_step=row["failed_step"],
            error=Exception(row["error_message"]) if row["error_message"] else None,
            correlation_id=row["correlation_id"],
        )


__all__ = ["PostgresSagaStateRepository"]
