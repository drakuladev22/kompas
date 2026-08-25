"""Tapşırıq aqreqatı (spesifikasiya bölmə 6 — Task & Workflow Panel).

──────────────────────────────────────────────────────────────────────────────
VƏZİYYƏT MAŞINI
──────────────────────────────────────────────────────────────────────────────

    OPEN ─────submit_evidence()─────> EVIDENCE_SUBMITTED ──approve()──> APPROVED
     │ ▲                                     │
     │ └──────────────────────────┐          └──reject(səbəb)──> REJECTED
     │                            │                                  │
     └──escalate() (vaxt keçib)──> OVERDUE ──submit_evidence()───────>┘ ↺

Statuslar `database/schema.sql`-dakı `task_status` enum-u ilə EYNİDİR — domen
tərəfində "daha rahat" ad seçmək (məs. `AWAITING_REVIEW`) hər oxunuşda
tərcümə cədvəli tələb edərdi və bir tərəf dəyişəndə digəri sükutla arxada
qalardı.

Bölmə 6: "rədd olunan tapşırıq yenidən «açıq» statusuna qayıdır". Yəni
`REJECTED` TERMİNAL DEYİL — işçi düzəldib yenidən göndərə bilər. Status isə
`OPEN`-a QAYTARILMIR: DB-nin `chk_task_reject` məhdudiyyəti rədd səbəbini
`REJECTED` statusuna bağlayır, üstəlik işçi "niyə geri gəldi?" sualının
cavabını ekranda görməlidir. Praktik nəticə eynidir — tapşırıq yenidən
icra oluna bilən vəziyyətdədir (`is_outstanding`).

`APPROVED` və `CANCELLED` terminaldır: təsdiqlənmiş tapşırıq yenidən
açılmır, əks halda menecer təsdiqindən sonra sübut dəyişdirilə bilərdi.

──────────────────────────────────────────────────────────────────────────────
İKİ AYRI SƏLAHİYYƏT — NİYƏ
──────────────────────────────────────────────────────────────────────────────
Bölmə 6-nın açıq düzəlişi: sübutu nəzərdən keçirən `can_approve_task_evidence`
sahibidir, tapşırığı təyin edən isə `can_assign_tasks` sahibi. Bunlar bilərəkdən
AYRI flag-lərdir — tapşırığı verən şəxsin öz tapşırığının sübutunu təsdiqləməsi
nəzarəti mənasızlaşdırardı. Entity səlahiyyəti YOXLAMIR (o, use case-in işidir),
lakin `assigned_by` və `reviewed_by` sahələrini AYRI saxlayır ki, yoxlama
mümkün olsun və audit "kim verdi / kim təsdiqlədi" sualını cavablandırsın.

──────────────────────────────────────────────────────────────────────────────
ESKALASİYA NİYƏ ENTITY-DƏDİR
──────────────────────────────────────────────────────────────────────────────
Son tarix keçdikdə eskalasiya bildirişi gedir (bölmə 6). "Keçibmi?" sualı
məlumat qaydasıdır və entity-yə aiddir; bildirişin FAKTİKİ göndərilməsi
infrastruktur işidir. `escalate()` yalnız hadisə yazır — kimə/necə çatdığını
`Notifier` həll edir. `escalated_at` isə təkrar bildirişin qarşısını alır:
onsuz hər planlayıcı dövrü eyni tapşırıq üçün yeni e-poçt göndərərdi.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import (
    TaskAssignedEvent,
    TaskDeadlineEscalatedEvent,
    TaskEvidenceReviewedEvent,
    TaskEvidenceSubmittedEvent,
)
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TaskId, TenantId
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

MIN_TITLE_LENGTH: Final[int] = 3
MAX_TITLE_LENGTH: Final[int] = 200
#: Rədd səbəbi — cərimə ləğvi ilə eyni minimum (boş "yox" cavabı qadağandır).
MIN_REJECTION_REASON_LENGTH: Final[int] = 10


class TaskStatus(str, Enum):
    """`tasks.status` — DB `task_status` enum-u ilə EYNİ dəyərlər."""

    OPEN = "OPEN"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.APPROVED, TaskStatus.CANCELLED)

    @property
    def is_outstanding(self) -> bool:
        """Hələ bağlanmayıb — eskalasiya yalnız bunlara şamil olunur."""
        return not self.is_terminal

    @property
    def accepts_evidence(self) -> bool:
        """Sübut göndərilə bilən vəziyyətlər.

        `REJECTED` və `OVERDUE` DAXİLDİR: hər ikisi "iş hələ qalıb" deməkdir
        və işçinin yenidən cəhd etməsi məhz gözlənilən davranışdır.
        """
        return self in (TaskStatus.OPEN, TaskStatus.REJECTED, TaskStatus.OVERDUE)


class TaskPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class TaskSource(str, Enum):
    """`tasks.source` — tapşırığın MƏNBƏYİ (`v2backlog.md` Faza 4.2).

    `ShiftAssignment.source` (`ADMIN_MATRIX`/`SHIFT_SWAP`) ilə EYNİ naxış:
    sətrin haradan doğduğu "NƏ" sualı deyil, "NİYƏ belədir" sualıdır və
    audit/sui-istifadə hesablaması üçün AYRICA sahə tələb edir.

    `EMPLOYEE_SELF_CORRECTION` üçün `assignee_id == assigned_by` — işçi
    ÖZÜNÜ təyin edir (bax `TaskWorkflowUseCase.request_self_correction`),
    sübutu (izahat + istəyə-bağlı foto) elə YARADILIŞ anında özü təqdim
    edir. Bu, `assigned_by`-ın "kim tapşırıq VERDİ" mənasını POZMUR — işçi
    faktiki olaraq ÖZ-ÖZÜNƏ tapşırıq "verib", rəyi isə BAŞQASI (nəzərdən
    keçirən) verəcək.
    """

    ASSIGNED = "ASSIGNED"
    EMPLOYEE_SELF_CORRECTION = "EMPLOYEE_SELF_CORRECTION"


class Task(AggregateRoot):
    """Tapşırıq qeydi — sübutla tamamlanma və təsdiq axını."""

    def __init__(
        self,
        *,
        task_id: TaskId,
        tenant_id: TenantId,
        title: str,
        assignee_id: EmployeeId,
        assigned_by: EmployeeId,
        deadline: datetime,
        created_at: datetime,
        description: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        store_id: StoreId | None = None,
        requires_evidence: bool = True,
        source: TaskSource = TaskSource.ASSIGNED,
    ) -> None:
        super().__init__()
        require_aware(deadline, field="deadline")
        require_aware(created_at, field="created_at")

        cleaned_title = normalise_decision_text(title)
        if len(cleaned_title) < MIN_TITLE_LENGTH:
            raise DomainRuleError(
                f"Tapşırıq başlığı minimum {MIN_TITLE_LENGTH} simvol olmalıdır",
                user_message="Tapşırıq başlığı çox qısadır.",
            )
        if len(cleaned_title) > MAX_TITLE_LENGTH:
            raise DomainRuleError(
                f"Tapşırıq başlığı maksimum {MAX_TITLE_LENGTH} simvol ola bilər",
                user_message="Tapşırıq başlığı çox uzundur.",
            )
        if deadline <= created_at:
            raise DomainRuleError(
                "Son tarix yaradılma anından sonra olmalıdır — "
                "keçmişə tapşırıq təyin etmək dərhal eskalasiya yaradardı",
                user_message="Son tarix gələcəkdə olmalıdır.",
            )

        self.id = task_id
        self.tenant_id = tenant_id
        self.title = cleaned_title
        self.description = description.strip()
        self.assignee_id = assignee_id
        self.assigned_by = assigned_by
        self.deadline = deadline
        self.created_at = created_at
        self.priority = priority
        self.store_id = store_id
        self.requires_evidence = requires_evidence
        self.source = source

        self.status = TaskStatus.OPEN
        #: Yüklənmiş sübut sənədlərinin URL-ləri (Google Drive / Supabase Storage).
        self.evidence_urls: tuple[str, ...] = ()
        self.submitted_at: datetime | None = None
        self.reviewed_by: EmployeeId | None = None
        self.reviewed_at: datetime | None = None
        self.rejection_reason: str | None = None
        self.completed_at: datetime | None = None
        self.cancelled_at: datetime | None = None
        #: Eskalasiya BİR DƏFƏ göndərilir — təkrar bildirişin qarşısını alır.
        self.escalated_at: datetime | None = None

        self.record_event(
            TaskAssignedEvent(
                task_id=task_id,
                assignee_id=assignee_id,
                assigned_by=assigned_by,
                deadline=deadline,
                tenant_id=tenant_id,
                actor_id=assigned_by,
            )
        )

    # ------------------------------ sübut yükləmə ---------------------------- #

    def submit_evidence(self, *, evidence_urls: list[str], submitted_at: datetime) -> None:
        """ "[Tamamlandı Kimi İşarələ]" — işçi sübutu yükləyir.

        Rədd edilmiş və vaxtı keçmiş tapşırıq da buradan keçir
        (`TaskStatus.accepts_evidence`), beləliklə düzəldilmiş sübut eyni
        yolla yenidən nəzərdən keçirilir.
        """
        require_aware(submitted_at, field="submitted_at")
        if not self.status.accepts_evidence:
            raise DomainRuleError(
                f"Bu vəziyyətdə sübut göndərilə bilməz, cari status: {self.status.value}",
                context={"task_id": str(self.id), "status": self.status.value},
            )

        cleaned = [url.strip() for url in evidence_urls if url.strip()]
        if self.requires_evidence and not cleaned:
            raise DomainRuleError(
                "Bu tapşırıq üçün sübut MƏCBURİDİR",
                user_message="Tapşırığı tamamlamaq üçün sübut faylı əlavə edin.",
            )

        self.status = TaskStatus.EVIDENCE_SUBMITTED
        self.evidence_urls = tuple(cleaned)
        self.submitted_at = submitted_at
        # Yeni cəhd — köhnə rədd səbəbi qalırsa, ekranda yanlış göstərilərdi.
        self.rejection_reason = None

        self.record_event(
            TaskEvidenceSubmittedEvent(
                task_id=self.id,
                assignee_id=self.assignee_id,
                evidence_count=len(cleaned),
                tenant_id=self.tenant_id,
                actor_id=self.assignee_id,
            )
        )

    # -------------------------------- nəzərdən keçirmə ----------------------- #

    def approve(self, *, reviewer_id: EmployeeId, reviewed_at: datetime) -> None:
        """ "[Təsdiqlə]" — `can_approve_task_evidence` sahibinin qərarı."""
        require_aware(reviewed_at, field="reviewed_at")
        self._require_awaiting_review()
        self._require_not_self_review(reviewer_id)

        self.status = TaskStatus.APPROVED
        self.reviewed_by = reviewer_id
        self.reviewed_at = reviewed_at
        self.completed_at = reviewed_at
        self.rejection_reason = None

        self.record_event(
            TaskEvidenceReviewedEvent(
                task_id=self.id,
                reviewer_id=reviewer_id,
                approved=True,
                reason=None,
                tenant_id=self.tenant_id,
                actor_id=reviewer_id,
            )
        )

    def reject(self, *, reviewer_id: EmployeeId, reviewed_at: datetime, reason: str) -> None:
        """ "[Rədd Et]" — tapşırıq YENİDƏN açılır (bölmə 6).

        Səbəb məcburidir: işçi nəyi düzəltməli olduğunu bilmirsə, eyni sübutu
        yenidən göndərəcək və dövr sonsuza qədər təkrarlanacaq.
        """
        require_aware(reviewed_at, field="reviewed_at")
        self._require_awaiting_review()
        self._require_not_self_review(reviewer_id)

        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_REJECTION_REASON_LENGTH:
            raise DomainRuleError(
                f"Rədd səbəbi minimum {MIN_REJECTION_REASON_LENGTH} simvol olmalıdır",
                user_message="Rədd səbəbini daha ətraflı yazın.",
            )

        self.status = TaskStatus.REJECTED
        self.reviewed_by = reviewer_id
        self.reviewed_at = reviewed_at
        self.rejection_reason = cleaned
        # Sübut SİLİNMİR — nəyin rədd edildiyi auditdə görünməlidir.

        self.record_event(
            TaskEvidenceReviewedEvent(
                task_id=self.id,
                reviewer_id=reviewer_id,
                approved=False,
                reason=cleaned,
                tenant_id=self.tenant_id,
                actor_id=reviewer_id,
            )
        )

    def cancel(self, *, cancelled_by: EmployeeId, cancelled_at: datetime) -> None:
        """Tapşırıq təyin edən tərəfindən ləğv edilir (artıq lazım deyil)."""
        require_aware(cancelled_at, field="cancelled_at")
        if self.status.is_terminal:
            raise DomainRuleError(
                f"Bağlanmış tapşırıq ləğv edilə bilməz, cari status: {self.status.value}"
            )
        self.status = TaskStatus.CANCELLED
        self.cancelled_at = cancelled_at
        self.reviewed_by = cancelled_by

    def _require_awaiting_review(self) -> None:
        if self.status is not TaskStatus.EVIDENCE_SUBMITTED:
            raise DomainRuleError(
                f"Yalnız nəzərdən keçirmə gözləyən tapşırıq üçün qərar verilə bilər, "
                f"cari status: {self.status.value}",
                context={"task_id": str(self.id), "status": self.status.value},
            )

    def _require_not_self_review(self, reviewer_id: EmployeeId) -> None:
        """İcraçı ÖZ sübutunu özü təsdiqləyə/rədd edə bilməz (vəzifə ayrılığı).

        NORMAL təyinatda bu heç vaxt işə düşmür (`assigned_by` başqa şəxsdir,
        `can_assign_tasks`/`can_approve_task_evidence` AYRI flag-lərdir —
        modul başlığı). LAKİN `TaskSource.EMPLOYEE_SELF_CORRECTION`-da
        `assignee_id == assigned_by`-dır (işçi özünü təyin edir) və məhz bu
        hal `v2backlog.md` Faza 4.2-nin açıq tələbini yaradır: "işçi öz
        uyğunsuzluğunu özü həll edə bilməz". `ShiftSwapRequest._decide`-dəki
        eyni qadağanın EYNİ əsaslandırması.
        """
        if reviewer_id == self.assignee_id:
            raise DomainRuleError(
                "İcraçı öz tapşırığının sübutunu özü təsdiqləyə/rədd edə bilməz",
                user_message="Öz tapşırığınıza qərar verə bilməzsiniz.",
                context={"task_id": str(self.id), "assignee_id": str(self.assignee_id)},
            )

    # -------------------------------- eskalasiya ----------------------------- #

    def is_overdue(self, *, now: datetime) -> bool:
        """Son tarix keçib, tapşırıq isə hələ bağlanmayıb."""
        require_aware(now, field="now")
        return self.status.is_outstanding and now > self.deadline

    @property
    def _blames_assignee(self) -> bool:
        """Gecikmə İCRAÇIYA aiddirmi.

        `EVIDENCE_SUBMITTED` halında YOX: işçi öz işini görüb, gözləyən tərəf
        təsdiqləyəndir. Həmin tapşırığı `OVERDUE` işarələmək günahı səhv
        adama yazardı — eskalasiya bildirişi isə yenə gedir, çünki iş
        bağlanmayıb.
        """
        return self.status is not TaskStatus.EVIDENCE_SUBMITTED

    def overdue_minutes(self, *, now: datetime) -> int:
        require_aware(now, field="now")
        if not self.is_overdue(now=now):
            return 0
        return int((now - self.deadline).total_seconds() // 60)

    def needs_escalation(self, *, now: datetime) -> bool:
        """Eskalasiya bildirişi göndərilməlidirmi — BİR DƏFƏ."""
        return self.is_overdue(now=now) and self.escalated_at is None

    def escalate(self, *, now: datetime) -> None:
        """Eskalasiya hadisəsini yazır (bildirişi `Notifier` göndərir).

        Təkrar çağırış istisna ATMIR, sadəcə heç nə etmir: planlayıcı eyni
        tapşırığı bir neçə dövrdə görəcək və hər dəfə çökməsi mənasızdır.
        """
        require_aware(now, field="now")
        if not self.needs_escalation(now=now):
            return

        overdue_minutes = self.overdue_minutes(now=now)
        self.escalated_at = now
        if self._blames_assignee:
            self.status = TaskStatus.OVERDUE
        self.record_event(
            TaskDeadlineEscalatedEvent(
                task_id=self.id,
                assignee_id=self.assignee_id,
                assigned_by=self.assigned_by,
                # Status artıq `OVERDUE`-ya keçib, ona görə dəyər ƏVVƏLCƏDƏN
                # hesablanır — `overdue_minutes()` yenidən çağırılsaydı,
                # nəticə eyni olardı, lakin asılılıq gizli qalardı.
                overdue_minutes=overdue_minutes,
                tenant_id=self.tenant_id,
            )
        )

    # -------------------------------- göstərmə ------------------------------- #

    @property
    def status_label_az(self) -> str:
        return {
            TaskStatus.OPEN: "Açıq",
            TaskStatus.EVIDENCE_SUBMITTED: "Təsdiq gözləyir",
            TaskStatus.APPROVED: "Tamamlandı",
            TaskStatus.REJECTED: "Rədd edildi — yenidən göndərin",
            TaskStatus.OVERDUE: "Vaxtı keçib",
            TaskStatus.CANCELLED: "Ləğv edildi",
        }[self.status]

    def __repr__(self) -> str:
        return f"Task(id={self.id}, status={self.status.value}, title={self.title!r})"


__all__ = [
    "MIN_REJECTION_REASON_LENGTH",
    "MIN_TITLE_LENGTH",
    "Task",
    "TaskPriority",
    "TaskSource",
    "TaskStatus",
]
