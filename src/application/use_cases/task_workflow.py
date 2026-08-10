"""Tapşırıq & İş Axını use case-ləri (spesifikasiya bölmə 6).

──────────────────────────────────────────────────────────────────────────────
ÜÇ SƏLAHİYYƏT, ÜÇ FƏRQLİ ŞƏXS
──────────────────────────────────────────────────────────────────────────────
    * `can_assign_tasks`           — tapşırığı VERƏN
    * (səlahiyyət tələb olunmur)   — tapşırığı İCRA EDƏN (təyin olunmuş işçi)
    * `can_approve_task_evidence`  — sübutu TƏSDİQLƏYƏN

Bölmə 6-nın açıq düzəlişi: təsdiq `can_assign_tasks` DEYİL, ayrıca
`can_approve_task_evidence` tələb edir. Eyni şəxsin həm verməsi, həm
təsdiqləməsi mümkündür (kiçik mağazada başqa yol yoxdur), lakin bu, artıq
İKİ AYRI səlahiyyət tələb edir — yəni Root bunu qəsdən verməlidir, təsadüfən
yox.

──────────────────────────────────────────────────────────────────────────────
SÜBUTU YALNIZ TƏYİN OLUNAN GÖNDƏRƏ BİLƏR
──────────────────────────────────────────────────────────────────────────────
`submit_evidence` səlahiyyət flag-i yoxlamır, SAHİBLİK yoxlayır: tapşırıq
kimə verilibsə, onu yalnız o bağlaya bilər. Flag ilə qorunsaydı, hər işçidə
"tapşırıq bağlamaq" flag-i olardı və bir işçi digərinin tapşırığını bağlaya
bilərdi.

──────────────────────────────────────────────────────────────────────────────
ESKALASİYA NİYƏ AYRI USE CASE-DİR
──────────────────────────────────────────────────────────────────────────────
Onu istifadəçi deyil, planlayıcı çağırır (STEP 2 timeout qaydası ilə eyni
məntiq). İnsan aktoru olmadığından səlahiyyət yoxlaması da yoxdur — əvəzində
`escalated_at` təkrar bildirişi bloklayır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.domain.entities.task import Task, TaskPriority
from src.domain.policies import FeatureModule
from src.domain.value_objects.notifications import NotificationCategory
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        FeatureToggles,
        Notifier,
        TaskRepository,
    )
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        StoreId,
        TaskId,
        TenantId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)
_app_log = get_logger(__name__)

ASSIGN_TASKS_FLAG = "can_assign_tasks"
APPROVE_EVIDENCE_FLAG = "can_approve_task_evidence"


class TaskWorkflowError(KompasOSError):
    """Tapşırıq əməliyyatı qadağandır və ya yararsızdır."""

    user_message = "Bu tapşırıq əməliyyatı icra edilə bilmədi."


class TaskNotFoundError(TaskWorkflowError):
    """Tapşırıq tapılmadı — silinib və ya başqa tenant-a aiddir."""

    user_message = "Tapşırıq tapılmadı."


@dataclass(frozen=True)
class TaskDraft:
    """Yeni tapşırıq forması — ekranın topladığı sahələr."""

    title: str
    assignee_id: EmployeeId
    deadline: datetime
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    store_id: StoreId | None = None
    requires_evidence: bool = True


@dataclass
class EscalationResult:
    """Planlayıcı dövrünün nəticəsi — monitorinq üçün."""

    checked: int = 0
    escalated: list[TaskId] = field(default_factory=list)

    @property
    def escalated_count(self) -> int:
        return len(self.escalated)


class TaskWorkflowUseCase:
    """Tapşırığın bütün həyat dövrü — təyinat, sübut, qərar, eskalasiya."""

    def __init__(
        self,
        *,
        tasks: TaskRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        toggles: FeatureToggles | None = None,
    ) -> None:
        self._tasks = tasks
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        # `None` → toggle mənbəyi qoşulmayıb (testlər, planlayıcı işləri).
        # Fail-open: konfiqurasiya oxuna bilmirsə modul AÇIQ sayılır — eyni
        # istiqamət `PostgresFeatureToggles.is_enabled`-dədir.
        self._toggles = toggles

    # ------------------------------- təyinat --------------------------------- #

    def assign(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        draft: TaskDraft,
        task_id: TaskId,
    ) -> Task:
        """ "[Tapşırıq Ver]" — `can_assign_tasks` sahibi yeni tapşırıq yaradır.

        RETROAKTİV TƏSİR QAYDASI (bölmə 3): `TASK_ENGINE` söndürülübsə YENİ
        tapşırıq yaradıla bilmir, lakin mövcud tapşırıqlar öz axınını normal
        tamamlayır — `submit_evidence`/`review`/`escalate` toggle yoxlamır.
        """
        now = self._clock.now()
        self._require_module(tenant_id)
        self._require(actor, ASSIGN_TASKS_FLAG, now=now)

        task = Task(
            task_id=task_id,
            tenant_id=tenant_id,
            title=draft.title,
            assignee_id=draft.assignee_id,
            assigned_by=actor.id,
            deadline=draft.deadline,
            created_at=now,
            description=draft.description,
            priority=draft.priority,
            store_id=draft.store_id,
            requires_evidence=draft.requires_evidence,
        )
        self._tasks.save(task)
        self._drain(task)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TASK_ASSIGNED",
            entity_type="task",
            entity_id=task.id,
            after_state={
                "title": task.title,
                "assignee_id": str(task.assignee_id),
                "deadline": task.deadline.isoformat(),
                "priority": task.priority.value,
            },
        )
        self._notify(
            recipient=draft.assignee_id,
            category=NotificationCategory.TASK_DEADLINE,
            title="Yeni tapşırıq",
            body=f"{task.title} — son tarix: {task.deadline:%d.%m.%Y %H:%M}",
            tenant_id=tenant_id,
        )
        return task

    # ------------------------------ sübut yükləmə ---------------------------- #

    def submit_evidence(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        task_id: TaskId,
        evidence_urls: list[str],
    ) -> Task:
        """ "[Tamamlandı Kimi İşarələ]" — yalnız TƏYİN OLUNAN işçi."""
        now = self._clock.now()
        task = self._load(task_id)

        if task.assignee_id != actor.id:
            _audit_log.warning(
                "TASK_EVIDENCE_FOREIGN_SUBMIT_BLOCKED",
                extra={"actor_id": str(actor.id), "task_id": str(task_id)},
            )
            raise TaskWorkflowError(
                "Yalnız tapşırığın təyin olunduğu işçi onu bağlaya bilər",
                user_message="Bu tapşırıq sizə təyin olunmayıb.",
                context={"task_id": str(task_id)},
            )

        task.submit_evidence(evidence_urls=evidence_urls, submitted_at=now)
        self._tasks.save(task)
        self._drain(task)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TASK_EVIDENCE_SUBMITTED",
            entity_type="task",
            entity_id=task.id,
            after_state={"evidence_count": len(task.evidence_urls)},
        )
        self._notify(
            recipient=task.assigned_by,
            category=NotificationCategory.TASK_DEADLINE,
            title="Tapşırıq təsdiq gözləyir",
            body=f"{task.title} — sübut yükləndi",
            tenant_id=tenant_id,
        )
        return task

    # -------------------------------- qərar ---------------------------------- #

    def approve(self, *, tenant_id: TenantId, actor: Employee, task_id: TaskId) -> Task:
        """ "[Təsdiqlə]" — `can_approve_task_evidence` sahibi."""
        now = self._clock.now()
        self._require(actor, APPROVE_EVIDENCE_FLAG, now=now)

        task = self._load(task_id)
        task.approve(reviewer_id=actor.id, reviewed_at=now)
        self._tasks.save(task)
        self._drain(task)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TASK_APPROVED",
            entity_type="task",
            entity_id=task.id,
            after_state={"status": task.status.value},
        )
        self._notify(
            recipient=task.assignee_id,
            category=NotificationCategory.TASK_DEADLINE,
            title="Tapşırıq təsdiqləndi",
            body=task.title,
            tenant_id=tenant_id,
        )
        return task

    def reject(self, *, tenant_id: TenantId, actor: Employee, task_id: TaskId, reason: str) -> Task:
        """ "[Rədd Et]" — tapşırıq yenidən açılır, işçiyə səbəb bildirilir."""
        now = self._clock.now()
        self._require(actor, APPROVE_EVIDENCE_FLAG, now=now)

        task = self._load(task_id)
        task.reject(reviewer_id=actor.id, reviewed_at=now, reason=reason)
        self._tasks.save(task)
        self._drain(task)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TASK_REJECTED",
            entity_type="task",
            entity_id=task.id,
            after_state={"status": task.status.value},
            reason=task.rejection_reason,
        )
        self._notify(
            recipient=task.assignee_id,
            category=NotificationCategory.TASK_DEADLINE,
            title="Tapşırıq rədd edildi",
            body=f"{task.title} — səbəb: {task.rejection_reason}",
            tenant_id=tenant_id,
        )
        return task

    # ------------------------------ eskalasiya ------------------------------- #

    def escalate_overdue(self, *, tenant_id: TenantId) -> EscalationResult:
        """Planlayıcı dövrü — son tarixi keçmiş tapşırıqları eskalasiya edir.

        Bir tapşırığın uğursuzluğu QALANLARI DAYANDIRMIR: bildiriş kanalı
        müvəqqəti sıradan çıxsa, digər tapşırıqlar da eskalasiyasız qalardı.
        """
        now = self._clock.now()
        result = EscalationResult()

        for task in self._tasks.list_overdue(tenant_id, now=now):
            result.checked += 1
            if not task.needs_escalation(now=now):
                continue

            task.escalate(now=now)
            self._tasks.save(task)
            self._drain(task)
            result.escalated.append(task.id)

            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="TASK_DEADLINE_ESCALATED",
                entity_type="task",
                entity_id=task.id,
                after_state={"overdue_minutes": task.overdue_minutes(now=now)},
            )
            try:
                self._notify(
                    recipient=task.assigned_by,
                    category=NotificationCategory.TASK_DEADLINE,
                    title="Tapşırıq son tarixi keçdi",
                    body=(
                        f"{task.title} — {task.overdue_minutes(now=now)} dəqiqə gecikmə. "
                        f"İcraçı: {task.assignee_id}"
                    ),
                    tenant_id=tenant_id,
                )
            except Exception:
                _app_log.exception("TASK_ESCALATION_NOTIFY_FAILED", extra={"task_id": str(task.id)})

        return result

    # ------------------------------- köməkçilər ------------------------------ #

    def _load(self, task_id: TaskId) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(
                f"Tapşırıq tapılmadı: {task_id}", context={"task_id": str(task_id)}
            )
        return task

    def _require_module(self, tenant_id: TenantId) -> None:
        """`TASK_ENGINE` Feature Toggle qapısı (bölmə 3)."""
        if self._toggles is None:
            return
        if not self._toggles.is_enabled(tenant_id, FeatureModule.TASK_ENGINE.value):
            raise TaskWorkflowError(
                "TASK_ENGINE modulu deaktiv edilib",
                user_message="Tapşırıq modulu hazırda aktiv deyil.",
                context={"module": FeatureModule.TASK_ENGINE.value},
            )

    def _require(self, actor: Employee, flag: str, *, now: datetime) -> None:
        if not actor.has_permission(flag, now=now):
            _audit_log.warning(
                "TASK_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": flag},
            )
            raise TaskWorkflowError(
                f"«{flag}» səlahiyyəti yoxdur",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
                context={"flag": flag},
            )

    def _drain(self, task: Task) -> None:
        """Aqreqatın topladığı hadisələri yazıdan SONRA boşaldır.

        Hadisə avtobusu bu use case-ə İNJEKSİYA EDİLMİR: tapşırıq axını
        çox-aqreqatlı saga deyil, hadisələr yalnız audit/telemetriya üçündür.
        Onları boşaltmaq isə vacibdir — əks halda eyni aqreqat obyekti təkrar
        istifadə edildikdə hadisələr yığılıb ikinci dəfə yayımlanardı.
        """
        task.collect_events()

    def _notify(
        self,
        *,
        recipient: EmployeeId,
        category: NotificationCategory,
        title: str,
        body: str,
        tenant_id: TenantId,
    ) -> None:
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=recipient,
            category=category.value,
            title_az=title,
            body_az=body,
            is_critical=category.is_always_critical,
        )


__all__ = [
    "APPROVE_EVIDENCE_FLAG",
    "ASSIGN_TASKS_FLAG",
    "EscalationResult",
    "TaskDraft",
    "TaskNotFoundError",
    "TaskWorkflowError",
    "TaskWorkflowUseCase",
]
