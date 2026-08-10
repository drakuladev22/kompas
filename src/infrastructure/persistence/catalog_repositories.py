"""Kataloq, tapşırıq və xal repository-ləri — Faza 5/6.

    PostgresWorkModeRepository   — İş Rejimləri kataloqu (bölmə 4)
    PostgresFineTypeRepository   — Cərimə Növləri kataloqu (bölmə 4)
    PostgresTaskRepository       — Tapşırıq aqreqatı (bölmə 6)
    PostgresSalesPointsRepository — `points_ledger` + `points_appeals` (bölmə 6)
    PostgresRewardRepository     — mükafat kataloqu + mübadilələr (bölmə 6)

──────────────────────────────────────────────────────────────────────────────
SOFT DELETE HƏR ÜÇ KATALOQDA EYNİDİR
──────────────────────────────────────────────────────────────────────────────
`deactivate()` `UPDATE ... SET is_active = FALSE` edir, `DELETE` YOX. Səbəb
`domain/value_objects/catalogs.py` modul başlığındadır: keçmiş cərimənin
növünü silmək onun səbəbini "naməlum"a çevirərdi.

`list_all(include_inactive=False)` isə DEFOLT-dur — seçim siyahıları
təhlükəsiz tərəfə düşür. İdarəetmə ekranı açıq şəkildə `True` ötürür.

──────────────────────────────────────────────────────────────────────────────
TAPŞIRIQ SÜBUTLARI NİYƏ AYRI CƏDVƏLDƏ
──────────────────────────────────────────────────────────────────────────────
`task_evidence` sətirləri `tasks`-dan ayrıdır (bir tapşırıqda bir neçə fayl).
`save()` onları TAM ƏVƏZ ETMİR — yalnız YENİLƏRİNİ əlavə edir: rədd edilmiş
sübutun silinməsi auditdə "nə rədd edildi?" sualını cavabsız qoyardı.

──────────────────────────────────────────────────────────────────────────────
XAL SƏTRİ NİYƏ İKİ CƏDVƏLDƏN BƏRPA OLUNUR
──────────────────────────────────────────────────────────────────────────────
`points_ledger` xalı, `points_appeals` isə etirazı saxlayır (bax
`gamification.PointsEntryStatus` izahı). `PointsEntry` aqreqatı hər ikisini
BİRLİKDƏ təmsil edir, ona görə `LEFT JOIN` istifadə olunur — etiraz yoxdursa
sətir yenə qaytarılır.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.domain.entities.sales_points import PointsEntry, RewardRedemption
from src.domain.entities.task import Task, TaskPriority, TaskStatus
from src.domain.value_objects.catalogs import FineType, WorkMode
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.gamification import (
    PointsAppealStatus,
    PointsEntryStatus,
    PointsPeriod,
    RedemptionStatus,
    RewardItem,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PointsEntryId,
    RedemptionId,
    RewardId,
    SalesTransactionId,
    StoreId,
    TaskId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import TimeRange
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import (
        FineTypeId,
        WorkModeId,
    )

_log = get_logger(__name__)


def _as_bool(value: object, *, default: bool = True) -> bool:
    return default if value is None else bool(value)


def _aware(value: object) -> datetime | None:
    """DB-dən gələn vaxtı tz-aware edir.

    `TIMESTAMPTZ` sütunları psycopg-də onsuz da aware gəlir; yoxlama
    konfiqurasiya səhvinə (məs. `TIMESTAMP` sütunu) qarşı sığortadır —
    naive vaxt cərimə hesablamasını sükutla pozardı.
    """
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# İş Rejimləri
# --------------------------------------------------------------------------- #


class PostgresWorkModeRepository(_BaseRepository):
    """`work_modes` — növbə şablonları."""

    _SELECT = """
        SELECT id, tenant_id, name, start_time, end_time, is_active, updated_at
        FROM work_modes
    """

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[WorkMode]:
        sql = self._SELECT + " WHERE tenant_id = %s"
        if not include_inactive:
            sql += " AND is_active"
        rows = self._fetch_all(sql + " ORDER BY name", (tenant_id,))
        return [self._hydrate(row) for row in rows]

    def get(self, work_mode_id: WorkModeId) -> WorkMode | None:
        row = self._fetch_one(self._SELECT + " WHERE id = %s", (work_mode_id,))
        return self._hydrate(row) if row else None

    def save(self, tenant_id: TenantId, entry: WorkMode, *, changed_by: EmployeeId) -> None:
        schedule = entry.schedule
        self._execute(
            """
            INSERT INTO work_modes
                (id, tenant_id, name, start_time, end_time, is_overnight,
                 is_active, created_by)
            VALUES (COALESCE(%s, gen_random_uuid()), %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, name)
            DO UPDATE SET start_time   = EXCLUDED.start_time,
                          end_time     = EXCLUDED.end_time,
                          is_overnight = EXCLUDED.is_overnight,
                          is_active    = EXCLUDED.is_active
            """,
            (
                entry.work_mode_id,
                tenant_id,
                entry.name,
                # Sərbəst növbə ("Növbəli 2/2") üçün saat yoxdur, lakin DB
                # sütunları NOT NULL-dur: 00:00–00:00 saxlanılır və domen
                # tərəfdə `schedule=None` kimi geri oxunur (bax `_hydrate`).
                schedule.start if schedule else "00:00",
                schedule.end if schedule else "00:00",
                bool(schedule and schedule.is_overnight),
                entry.is_active,
                changed_by,
            ),
        )

    def deactivate(
        self, tenant_id: TenantId, work_mode_id: WorkModeId, *, changed_by: EmployeeId
    ) -> None:
        self._execute(
            "UPDATE work_modes SET is_active = FALSE WHERE id = %s AND tenant_id = %s",
            (work_mode_id, tenant_id),
        )
        _log.info(
            "WORK_MODE_DEACTIVATED",
            extra={"work_mode_id": str(work_mode_id), "changed_by": str(changed_by)},
        )

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> WorkMode:
        start, end = row.get("start_time"), row.get("end_time")
        # `00:00–00:00` "saat təyin olunmayıb" deməkdir (bax `save`).
        # Tip yoxlaması sütun növü səhv konfiqurasiya edilsə (məs. `TEXT`)
        # `TimeRange`-in gec çökməsinin qarşısını alır.
        schedule = (
            TimeRange(start, end)
            if isinstance(start, time) and isinstance(end, time) and start != end
            else None
        )
        is_active = _as_bool(row.get("is_active"))
        return WorkMode(
            name=str(row["name"]),
            tenant_id=TenantId(row["tenant_id"]),
            is_active=is_active,
            deactivated_at=None if is_active else _aware(row.get("updated_at")),
            work_mode_id=row["id"],
            schedule=schedule,
        )


# --------------------------------------------------------------------------- #
# Cərimə Növləri
# --------------------------------------------------------------------------- #


class PostgresFineTypeRepository(_BaseRepository):
    """`fine_types` — anti-fraud kataloqu (bölmə 4)."""

    _SELECT = """
        SELECT id, tenant_id, name_az, standard_amount, is_active, created_at
        FROM fine_types
    """

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[FineType]:
        sql = self._SELECT + " WHERE tenant_id = %s"
        if not include_inactive:
            sql += " AND is_active"
        rows = self._fetch_all(sql + " ORDER BY name_az", (tenant_id,))
        return [self._hydrate(row) for row in rows]

    def get(self, fine_type_id: FineTypeId) -> FineType | None:
        row = self._fetch_one(self._SELECT + " WHERE id = %s", (fine_type_id,))
        return self._hydrate(row) if row else None

    def save(self, tenant_id: TenantId, entry: FineType, *, changed_by: EmployeeId) -> None:
        self._execute(
            """
            INSERT INTO fine_types
                (id, tenant_id, name_az, standard_amount, is_active, created_by)
            VALUES (COALESCE(%s, gen_random_uuid()), %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, name_az)
            DO UPDATE SET standard_amount = EXCLUDED.standard_amount,
                          is_active       = EXCLUDED.is_active
            """,
            (
                entry.fine_type_id,
                tenant_id,
                entry.name,
                entry.standard_amount.amount,
                entry.is_active,
                changed_by,
            ),
        )

    def deactivate(
        self, tenant_id: TenantId, fine_type_id: FineTypeId, *, changed_by: EmployeeId
    ) -> None:
        self._execute(
            "UPDATE fine_types SET is_active = FALSE WHERE id = %s AND tenant_id = %s",
            (fine_type_id, tenant_id),
        )
        _log.info(
            "FINE_TYPE_DEACTIVATED",
            extra={"fine_type_id": str(fine_type_id), "changed_by": str(changed_by)},
        )

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> FineType:
        is_active = _as_bool(row.get("is_active"))
        return FineType(
            name=str(row["name_az"]),
            tenant_id=TenantId(row["tenant_id"]),
            is_active=is_active,
            deactivated_at=None if is_active else _aware(row.get("created_at")),
            fine_type_id=row["id"],
            standard_amount=Money(Decimal(str(row.get("standard_amount", "0")))),
        )


# --------------------------------------------------------------------------- #
# Tapşırıqlar
# --------------------------------------------------------------------------- #


class PostgresTaskRepository(_BaseRepository):
    """`tasks` + `task_evidence`."""

    _SELECT = """
        SELECT t.id, t.tenant_id, t.store_id, t.title, t.description,
               t.assignee_id, t.assigned_by, t.deadline, t.status,
               t.completed_at, t.reviewed_by, t.reviewed_at, t.reject_reason,
               t.escalated_at, t.created_at,
               COALESCE(
                   ARRAY(SELECT e.file_url FROM task_evidence e
                          WHERE e.task_id = t.id ORDER BY e.uploaded_at),
                   '{}'
               ) AS evidence_urls
        FROM tasks t
    """

    def get(self, task_id: TaskId) -> Task | None:
        row = self._fetch_one(self._SELECT + " WHERE t.id = %s", (task_id,))
        return self._hydrate(row) if row else None

    def list_for_assignee(self, employee_id: EmployeeId, *, open_only: bool = True) -> list[Task]:
        sql = self._SELECT + " WHERE t.assignee_id = %s"
        if open_only:
            sql += " AND t.status NOT IN ('APPROVED', 'CANCELLED')"
        rows = self._fetch_all(sql + " ORDER BY t.deadline", (employee_id,))
        return [self._hydrate(row) for row in rows]

    def list_awaiting_review(self, tenant_id: TenantId) -> list[Task]:
        rows = self._fetch_all(
            self._SELECT + " WHERE t.tenant_id = %s AND t.status = 'EVIDENCE_SUBMITTED'"
            " ORDER BY t.deadline",
            (tenant_id,),
        )
        return [self._hydrate(row) for row in rows]

    def list_overdue(self, tenant_id: TenantId, *, now: datetime) -> list[Task]:
        """Eskalasiya növbəsi — YALNIZ hələ bildirilməmişlər.

        `escalated_at IS NULL` şərti sorğuya salınır ki, planlayıcı hər
        dövrdə eyni minlərlə sətri gətirməsin; entity-dəki `needs_escalation`
        yoxlaması isə yenə qalır (iki qat müdafiə).
        """
        rows = self._fetch_all(
            self._SELECT
            + """
             WHERE t.tenant_id = %s
               AND t.deadline < %s
               AND t.escalated_at IS NULL
               AND t.status NOT IN ('APPROVED', 'CANCELLED')
             ORDER BY t.deadline
            """,
            (tenant_id, now),
        )
        return [self._hydrate(row) for row in rows]

    def save(self, task: Task) -> None:
        self._execute(
            """
            INSERT INTO tasks
                (id, tenant_id, store_id, title, description, assignee_id,
                 assigned_by, deadline, status, completed_at, reviewed_by,
                 reviewed_at, reject_reason, escalated_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id)
            DO UPDATE SET status        = EXCLUDED.status,
                          completed_at  = EXCLUDED.completed_at,
                          reviewed_by   = EXCLUDED.reviewed_by,
                          reviewed_at   = EXCLUDED.reviewed_at,
                          reject_reason = EXCLUDED.reject_reason,
                          escalated_at  = EXCLUDED.escalated_at
            """,
            (
                task.id,
                task.tenant_id,
                task.store_id,
                task.title,
                task.description or None,
                task.assignee_id,
                task.assigned_by,
                task.deadline,
                task.status.value,
                task.completed_at,
                task.reviewed_by,
                task.reviewed_at,
                task.rejection_reason,
                task.escalated_at,
                task.created_at,
            ),
        )
        self._save_evidence(task)

    def _save_evidence(self, task: Task) -> None:
        """Yalnız YENİ sübut sətirlərini əlavə edir (modul başlığına bax)."""
        for url in task.evidence_urls:
            self._execute(
                """
                INSERT INTO task_evidence (task_id, file_url, uploaded_by)
                SELECT %s, %s, %s
                 WHERE NOT EXISTS (
                     SELECT 1 FROM task_evidence WHERE task_id = %s AND file_url = %s
                 )
                """,
                (task.id, url, task.assignee_id, task.id, url),
            )

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> Task:
        deadline = _aware(row["deadline"])
        created_at = _aware(row.get("created_at")) or deadline
        assert deadline is not None and created_at is not None

        task = Task.__new__(Task)
        # `__init__` YAN KEÇİLİR: o, yeni tapşırıq üçün `TaskAssignedEvent`
        # yayımlayır və `deadline > created_at` tələb edir. Bərpa isə mövcud
        # sətri oxumaqdır — nə hadisə, nə də həmin yoxlama yerinə düşür
        # (keçmişdə yaradılmış tapşırığın son tarixi artıq keçmiş ola bilər).
        super(Task, task).__init__()
        task.id = TaskId(row["id"])
        task.tenant_id = TenantId(row["tenant_id"])
        task.store_id = StoreId(row["store_id"]) if row.get("store_id") else None
        task.title = str(row["title"])
        task.description = str(row.get("description") or "")
        task.assignee_id = EmployeeId(row["assignee_id"])
        task.assigned_by = EmployeeId(row["assigned_by"])
        task.deadline = deadline
        task.created_at = created_at
        task.priority = TaskPriority.NORMAL
        task.requires_evidence = True
        task.status = TaskStatus(str(row["status"]))
        task.evidence_urls = tuple(row.get("evidence_urls") or ())
        task.submitted_at = None
        task.reviewed_by = EmployeeId(row["reviewed_by"]) if row.get("reviewed_by") else None
        task.reviewed_at = _aware(row.get("reviewed_at"))
        task.rejection_reason = row.get("reject_reason")
        task.completed_at = _aware(row.get("completed_at"))
        task.cancelled_at = None
        task.escalated_at = _aware(row.get("escalated_at"))
        return task


# --------------------------------------------------------------------------- #
# Satış xalları
# --------------------------------------------------------------------------- #


class PostgresSalesPointsRepository(_BaseRepository):
    """`points_ledger` + `points_appeals`."""

    _SELECT = """
        SELECT l.id, l.tenant_id, l.employee_id, l.delta_points, l.reason,
               l.source_transaction_id, l.period_start, l.status,
               l.corrected_by, l.corrected_at, l.created_at,
               a.status  AS appeal_status,
               a.reason  AS appeal_reason,
               a.created_at AS appeal_created_at,
               a.decision_note,
               a.decided_at AS appeal_decided_at,
               s.store_id AS store_id
        FROM points_ledger l
        LEFT JOIN points_appeals a ON a.ledger_id = l.id
        LEFT JOIN sales_transactions s ON s.id = l.source_transaction_id
    """

    def get(self, entry_id: PointsEntryId) -> PointsEntry | None:
        row = self._fetch_one(self._SELECT + " WHERE l.id = %s", (entry_id,))
        return self._hydrate(row) if row else None

    def list_for_employee(
        self, employee_id: EmployeeId, *, period: PointsPeriod
    ) -> list[PointsEntry]:
        rows = self._fetch_all(
            self._SELECT
            + " WHERE l.employee_id = %s AND l.period_start = %s ORDER BY l.created_at DESC",
            (employee_id, period.start),
        )
        return [self._hydrate(row) for row in rows]

    def list_disputes(self, tenant_id: TenantId) -> list[PointsEntry]:
        rows = self._fetch_all(
            self._SELECT + " WHERE l.tenant_id = %s AND a.status = 'PENDING' ORDER BY a.created_at",
            (tenant_id,),
        )
        return [self._hydrate(row) for row in rows]

    def save(self, entry: PointsEntry) -> None:
        self._execute(
            """
            INSERT INTO points_ledger
                (id, tenant_id, employee_id, delta_points, reason,
                 source_transaction_id, period_start, status,
                 corrected_by, corrected_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id)
            DO UPDATE SET delta_points = EXCLUDED.delta_points,
                          status       = EXCLUDED.status,
                          corrected_by = EXCLUDED.corrected_by,
                          corrected_at = EXCLUDED.corrected_at
            """,
            (
                entry.id,
                entry.tenant_id,
                entry.employee_id,
                entry.points,
                entry.decision_reason or f"Satış xalı ({entry.confidence.value})",
                entry.sales_transaction_id,
                PointsPeriod.containing(entry.awarded_at.date()).start,
                entry.status.value,
                entry.decided_by,
                entry.decided_at,
                entry.awarded_at,
            ),
        )
        self._save_appeal(entry)

    def _save_appeal(self, entry: PointsEntry) -> None:
        """Etiraz sətri — yalnız etiraz AÇILDIQDA yaranır."""
        if entry.appeal_status is None or entry.disputed_at is None:
            return
        self._execute(
            """
            INSERT INTO points_appeals
                (tenant_id, ledger_id, employee_id, reason, status,
                 window_closes_at, decided_by, decision_note, decided_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ledger_id)
            DO UPDATE SET status        = EXCLUDED.status,
                          decided_by    = EXCLUDED.decided_by,
                          decision_note = EXCLUDED.decision_note,
                          decided_at    = EXCLUDED.decided_at
            """,
            (
                entry.tenant_id,
                entry.id,
                entry.employee_id,
                entry.dispute_reason,
                entry.appeal_status.value,
                entry.dispute_window_closes_at,
                entry.decided_by,
                entry.decision_reason,
                entry.decided_at,
                entry.disputed_at,
            ),
        )

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> PointsEntry:
        awarded_at = _aware(row.get("created_at"))
        assert awarded_at is not None

        entry = PointsEntry.__new__(PointsEntry)
        # `__init__` yan keçilir: o, `points > 0` tələb edir, bərpa isə
        # `REVERSED` sətri də oxumalıdır (bax `PostgresTaskRepository._hydrate`).
        super(PointsEntry, entry).__init__()
        entry.id = PointsEntryId(row["id"])
        entry.tenant_id = TenantId(row["tenant_id"])
        entry.employee_id = EmployeeId(row["employee_id"])
        entry.store_id = StoreId(row["store_id"]) if row.get("store_id") else None  # type: ignore[assignment]
        entry.confidence = MatchConfidence.EXACT_MATCH
        entry.sales_transaction_id = (
            SalesTransactionId(row["source_transaction_id"])
            if row.get("source_transaction_id")
            else None
        )
        entry.gross_amount = None
        entry.awarded_at = awarded_at
        entry.dispute_window_hours = 72
        entry.status = PointsEntryStatus(str(row["status"]))
        entry.points = int(row["delta_points"])
        entry.original_points = int(row["delta_points"])
        raw_appeal = row.get("appeal_status")
        entry.appeal_status = PointsAppealStatus(str(raw_appeal)) if raw_appeal else None
        entry.dispute_reason = row.get("appeal_reason")
        entry.disputed_at = _aware(row.get("appeal_created_at"))
        entry.decided_by = EmployeeId(row["corrected_by"]) if row.get("corrected_by") else None
        entry.decided_at = _aware(row.get("corrected_at")) or _aware(row.get("appeal_decided_at"))
        entry.decision_reason = row.get("decision_note")
        return entry


# --------------------------------------------------------------------------- #
# Mükafatlar
# --------------------------------------------------------------------------- #


class PostgresRewardRepository(_BaseRepository):
    """`rewards` + `reward_redemptions` (migration 010 sütunları ilə)."""

    def list_rewards(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[tuple[RewardId, RewardItem]]:
        sql = "SELECT id, name_az, cost_points, is_active FROM rewards WHERE tenant_id = %s"
        if not include_inactive:
            sql += " AND is_active"
        rows = self._fetch_all(sql + " ORDER BY cost_points", (tenant_id,))
        return [(RewardId(row["id"]), self._hydrate_reward(row)) for row in rows]

    def get_reward(self, reward_id: RewardId) -> RewardItem | None:
        row = self._fetch_one(
            "SELECT id, name_az, cost_points, is_active FROM rewards WHERE id = %s",
            (reward_id,),
        )
        return self._hydrate_reward(row) if row else None

    def save_reward(self, tenant_id: TenantId, reward_id: RewardId, reward: RewardItem) -> None:
        self._execute(
            """
            INSERT INTO rewards (id, tenant_id, name_az, cost_points, is_active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id)
            DO UPDATE SET name_az     = EXCLUDED.name_az,
                          cost_points = EXCLUDED.cost_points,
                          is_active   = EXCLUDED.is_active
            """,
            (reward_id, tenant_id, reward.name, reward.cost_points, reward.is_active),
        )

    _REDEMPTION_SELECT = """
        SELECT id, tenant_id, reward_id, employee_id, points_spent, status,
               approved_by, approved_at, decision_note, fulfilled_at,
               reward_name_snapshot, created_at
        FROM reward_redemptions
    """

    def list_redemptions(
        self, tenant_id: TenantId, *, pending_only: bool = False
    ) -> list[RewardRedemption]:
        sql = self._REDEMPTION_SELECT + " WHERE tenant_id = %s"
        if pending_only:
            sql += " AND status = 'REQUESTED'"
        rows = self._fetch_all(sql + " ORDER BY created_at DESC", (tenant_id,))
        return [self._hydrate_redemption(row) for row in rows]

    def get_redemption(self, redemption_id: RedemptionId) -> RewardRedemption | None:
        row = self._fetch_one(self._REDEMPTION_SELECT + " WHERE id = %s", (redemption_id,))
        return self._hydrate_redemption(row) if row else None

    def save_redemption(self, redemption: RewardRedemption) -> None:
        self._execute(
            """
            INSERT INTO reward_redemptions
                (id, tenant_id, reward_id, employee_id, points_spent, status,
                 approved_by, approved_at, decision_note, fulfilled_at,
                 reward_name_snapshot, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id)
            DO UPDATE SET status        = EXCLUDED.status,
                          approved_by   = EXCLUDED.approved_by,
                          approved_at   = EXCLUDED.approved_at,
                          decision_note = EXCLUDED.decision_note,
                          fulfilled_at  = EXCLUDED.fulfilled_at
            """,
            (
                redemption.id,
                redemption.tenant_id,
                redemption.reward_id,
                redemption.employee_id,
                redemption.cost_points,
                redemption.status.value,
                redemption.decided_by,
                redemption.decided_at,
                redemption.decision_reason,
                redemption.fulfilled_at,
                redemption.reward_name,
                redemption.requested_at,
            ),
        )

    @staticmethod
    def _hydrate_reward(row: dict[str, Any]) -> RewardItem:
        return RewardItem(
            name=str(row["name_az"]),
            cost_points=int(row["cost_points"]),
            is_active=_as_bool(row.get("is_active")),
        )

    @staticmethod
    def _hydrate_redemption(row: dict[str, Any]) -> RewardRedemption:
        requested_at = _aware(row.get("created_at"))
        assert requested_at is not None

        redemption = RewardRedemption.__new__(RewardRedemption)
        # `__init__` yan keçilir: o, balans yoxlaması aparır və mövcud sətrin
        # bərpası zamanı işçinin CARİ balansı ilə keçmiş qərarı ləğv edərdi.
        super(RewardRedemption, redemption).__init__()
        redemption.id = RedemptionId(row["id"])
        redemption.tenant_id = TenantId(row["tenant_id"])
        redemption.employee_id = EmployeeId(row["employee_id"])
        redemption.reward_id = RewardId(row["reward_id"])
        redemption.reward_name = str(row.get("reward_name_snapshot") or "Mükafat")
        redemption.cost_points = int(row["points_spent"])
        redemption.requested_at = requested_at
        redemption.status = RedemptionStatus(str(row.get("status") or "REQUESTED"))
        redemption.decided_by = EmployeeId(row["approved_by"]) if row.get("approved_by") else None
        redemption.decided_at = _aware(row.get("approved_at"))
        redemption.decision_reason = row.get("decision_note")
        redemption.fulfilled_at = _aware(row.get("fulfilled_at"))
        return redemption


__all__ = [
    "PostgresFineTypeRepository",
    "PostgresRewardRepository",
    "PostgresSalesPointsRepository",
    "PostgresTaskRepository",
    "PostgresWorkModeRepository",
]
