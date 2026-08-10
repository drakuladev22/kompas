"""Tapşırıq və xal aqreqatlarının vəziyyət maşınları — Faza 6.

Bu testlər spesifikasiyanın İKİ kritik qaydasını qoruyur:

    * "rədd olunan tapşırıq yenidən «açıq» statusuna qayıdır" (bölmə 6);
    * "orijinal əməliyyat qeydi silinmir — yalnız REVERSED/CORRECTED statusu
      əlavə olunur" (bölmə 6, xal etirazı).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.domain.entities.base import DomainRuleError
from src.domain.entities.sales_points import PointsEntry, RewardRedemption
from src.domain.entities.task import Task, TaskStatus
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.gamification import (
    InsufficientPointsError,
    PointsAppealStatus,
    PointsEntryStatus,
    RedemptionStatus,
    RewardItem,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PointsEntryId,
    RedemptionId,
    RewardId,
    StoreId,
    TaskId,
    TenantId,
)

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
ASSIGNEE = EmployeeId(uuid.uuid4())
MANAGER = EmployeeId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
REASON = "Sübut şəkli oxunmur, yenidən çəkin"


def _task(*, requires_evidence: bool = True, hours: int = 8) -> Task:
    return Task(
        task_id=TaskId(uuid.uuid4()),
        tenant_id=TENANT,
        title="Vitrini yenilə",
        assignee_id=ASSIGNEE,
        assigned_by=MANAGER,
        deadline=NOW + timedelta(hours=hours),
        created_at=NOW,
        store_id=STORE,
        requires_evidence=requires_evidence,
    )


# --------------------------------------------------------------------------- #
# Yaradılma
# --------------------------------------------------------------------------- #


def test_new_task_starts_open_and_records_an_event() -> None:
    task = _task()
    assert task.status is TaskStatus.OPEN
    events = task.collect_events()
    assert [type(event).__name__ for event in events] == ["TaskAssignedEvent"]


def test_deadline_in_the_past_is_rejected() -> None:
    """Keçmişə tapşırıq təyin etmək dərhal eskalasiya yaradardı."""
    with pytest.raises(DomainRuleError, match="Son tarix"):
        Task(
            task_id=TaskId(uuid.uuid4()),
            tenant_id=TENANT,
            title="Gec",
            assignee_id=ASSIGNEE,
            assigned_by=MANAGER,
            deadline=NOW - timedelta(hours=1),
            created_at=NOW,
        )


def test_short_title_is_rejected() -> None:
    with pytest.raises(DomainRuleError):
        Task(
            task_id=TaskId(uuid.uuid4()),
            tenant_id=TENANT,
            title="X",
            assignee_id=ASSIGNEE,
            assigned_by=MANAGER,
            deadline=NOW + timedelta(hours=2),
            created_at=NOW,
        )


# --------------------------------------------------------------------------- #
# Sübut və qərar
# --------------------------------------------------------------------------- #


def test_evidence_is_mandatory_when_the_task_requires_it() -> None:
    task = _task()
    with pytest.raises(DomainRuleError, match="MƏCBURİDİR"):
        task.submit_evidence(evidence_urls=[], submitted_at=NOW)


def test_task_without_evidence_requirement_closes_with_an_empty_list() -> None:
    task = _task(requires_evidence=False)
    task.submit_evidence(evidence_urls=[], submitted_at=NOW)
    assert task.status is TaskStatus.EVIDENCE_SUBMITTED


def test_approval_is_terminal() -> None:
    task = _task()
    task.submit_evidence(evidence_urls=["https://drive/1.jpg"], submitted_at=NOW)
    task.approve(reviewer_id=MANAGER, reviewed_at=NOW)

    assert task.status is TaskStatus.APPROVED
    assert task.completed_at == NOW
    with pytest.raises(DomainRuleError):
        task.submit_evidence(evidence_urls=["https://drive/2.jpg"], submitted_at=NOW)


def test_rejected_task_can_be_resubmitted() -> None:
    """Bölmə 6: rədd TERMİNAL DEYİL."""
    task = _task()
    task.submit_evidence(evidence_urls=["https://drive/1.jpg"], submitted_at=NOW)
    task.reject(reviewer_id=MANAGER, reviewed_at=NOW, reason=REASON)

    assert task.status is TaskStatus.REJECTED
    assert task.status.accepts_evidence

    task.submit_evidence(evidence_urls=["https://drive/2.jpg"], submitted_at=NOW)
    assert task.status is TaskStatus.EVIDENCE_SUBMITTED
    # Yeni cəhddə köhnə rədd səbəbi ekranda qalmamalıdır.
    assert task.rejection_reason is None


def test_rejected_evidence_is_kept_for_audit() -> None:
    """Nəyin rədd edildiyi auditdə görünməlidir."""
    task = _task()
    task.submit_evidence(evidence_urls=["https://drive/1.jpg"], submitted_at=NOW)
    task.reject(reviewer_id=MANAGER, reviewed_at=NOW, reason=REASON)
    assert task.evidence_urls == ("https://drive/1.jpg",)


def test_rejection_requires_a_meaningful_reason() -> None:
    task = _task()
    task.submit_evidence(evidence_urls=["https://drive/1.jpg"], submitted_at=NOW)
    with pytest.raises(DomainRuleError, match="Rədd səbəbi"):
        task.reject(reviewer_id=MANAGER, reviewed_at=NOW, reason="yox")


def test_decision_requires_submitted_evidence() -> None:
    task = _task()
    with pytest.raises(DomainRuleError):
        task.approve(reviewer_id=MANAGER, reviewed_at=NOW)


# --------------------------------------------------------------------------- #
# Eskalasiya
# --------------------------------------------------------------------------- #


def test_escalation_marks_an_open_task_overdue() -> None:
    task = _task(hours=2)
    late = NOW + timedelta(hours=3)

    assert task.needs_escalation(now=late)
    task.escalate(now=late)

    assert task.status is TaskStatus.OVERDUE
    assert task.escalated_at == late


def test_escalation_does_not_blame_the_assignee_who_already_submitted() -> None:
    """Gözləyən tərəf təsdiqləyəndirsə, tapşırıq «vaxtı keçib» kimi damğalanmır."""
    task = _task(hours=2)
    task.submit_evidence(evidence_urls=["https://drive/1.jpg"], submitted_at=NOW)
    late = NOW + timedelta(hours=3)

    task.escalate(now=late)

    assert task.status is TaskStatus.EVIDENCE_SUBMITTED
    assert task.escalated_at == late


def test_escalation_happens_only_once() -> None:
    """Planlayıcı hər dövrdə eyni tapşırığı görəcək — təkrar bildiriş getməməlidir."""
    task = _task(hours=2)
    late = NOW + timedelta(hours=3)
    task.escalate(now=late)
    task.collect_events()

    task.escalate(now=late + timedelta(hours=1))
    assert not task.collect_events()


def test_repeated_escalation_does_not_raise() -> None:
    task = _task(hours=2)
    task.escalate(now=NOW + timedelta(hours=3))
    task.escalate(now=NOW + timedelta(hours=4))  # istisna ATMAMALIDIR


def test_completed_task_is_never_overdue() -> None:
    task = _task(hours=2)
    task.submit_evidence(evidence_urls=["https://drive/1.jpg"], submitted_at=NOW)
    task.approve(reviewer_id=MANAGER, reviewed_at=NOW)
    assert not task.is_overdue(now=NOW + timedelta(days=5))


def test_overdue_task_can_still_be_completed() -> None:
    task = _task(hours=2)
    task.escalate(now=NOW + timedelta(hours=3))
    task.submit_evidence(
        evidence_urls=["https://drive/1.jpg"], submitted_at=NOW + timedelta(hours=4)
    )
    assert task.status is TaskStatus.EVIDENCE_SUBMITTED


# --------------------------------------------------------------------------- #
# Xal sətri
# --------------------------------------------------------------------------- #


def _entry(*, points: int = 40, awarded_at: datetime = NOW) -> PointsEntry:
    return PointsEntry(
        entry_id=PointsEntryId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=ASSIGNEE,
        store_id=STORE,
        points=points,
        awarded_at=awarded_at,
        confidence=MatchConfidence.LOW_CONFIDENCE_MATCH,
    )


def test_low_confidence_match_still_awards_points() -> None:
    """Bölmə 6: nəzərdən keçirmə gözləyən satış işçinin xalını gecikdirməməlidir."""
    entry = _entry()
    assert entry.status is PointsEntryStatus.ACTIVE
    assert entry.effective_points == 40


def test_unassigned_sale_cannot_create_a_points_row() -> None:
    with pytest.raises(DomainRuleError):
        PointsEntry(
            entry_id=PointsEntryId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=ASSIGNEE,
            store_id=STORE,
            points=10,
            awarded_at=NOW,
            confidence=MatchConfidence.UNASSIGNED,
        )


def test_dispute_leaves_the_points_in_force() -> None:
    """Qərardan ƏVVƏL işçi cəzalandırılmır."""
    entry = _entry()
    entry.open_dispute(reason="Bu satış mənim deyil", disputed_at=NOW + timedelta(hours=1))

    assert entry.status is PointsEntryStatus.ACTIVE
    assert entry.appeal_status is PointsAppealStatus.PENDING
    assert entry.effective_points == 40


def test_dispute_after_72_hours_is_refused() -> None:
    entry = _entry()
    with pytest.raises(DomainRuleError, match="pəncərəsi bağlanıb"):
        entry.open_dispute(reason="Gec qaldım", disputed_at=NOW + timedelta(hours=73))


def test_second_dispute_is_blocked() -> None:
    entry = _entry()
    entry.open_dispute(reason="Bu satış mənim deyil", disputed_at=NOW + timedelta(hours=1))
    with pytest.raises(DomainRuleError, match="artıq göndərilib"):
        entry.open_dispute(reason="Yenə etiraz edirəm", disputed_at=NOW + timedelta(hours=2))


def test_correction_keeps_the_original_value() -> None:
    """Bölmə 6: orijinal əməliyyat qeydi SİLİNMİR."""
    entry = _entry(points=40)
    entry.open_dispute(reason="Say səhvdir", disputed_at=NOW + timedelta(hours=1))
    entry.correct(
        new_points=25,
        decided_by=MANAGER,
        decided_at=NOW + timedelta(hours=2),
        reason="Kassa qeydi ilə tutuşduruldu",
    )

    assert entry.status is PointsEntryStatus.CORRECTED
    assert entry.points == 25
    assert entry.original_points == 40
    assert entry.appeal_status is PointsAppealStatus.APPROVED


def test_reversal_keeps_the_amount_visible() -> None:
    """Nə qədər xal ləğv olunduğu auditdə görünməlidir."""
    entry = _entry(points=40)
    entry.reverse(
        decided_by=MANAGER,
        decided_at=NOW + timedelta(hours=2),
        reason="Satış tamamilə başqa işçiyə aiddir",
    )

    assert entry.status is PointsEntryStatus.REVERSED
    assert entry.points == 40
    assert entry.effective_points == 0


def test_zero_correction_is_routed_to_reversal_not_silently_accepted() -> None:
    entry = _entry()
    with pytest.raises(DomainRuleError, match="reverse"):
        entry.correct(
            new_points=0,
            decided_by=MANAGER,
            decided_at=NOW,
            reason="Tam ləğv edilməlidir",
        )


def test_rejecting_a_dispute_leaves_the_row_untouched() -> None:
    entry = _entry(points=40)
    entry.open_dispute(reason="Say səhvdir", disputed_at=NOW + timedelta(hours=1))
    entry.reject_dispute(
        decided_by=MANAGER,
        decided_at=NOW + timedelta(hours=2),
        reason="1C qeydi ilə tam üst-üstə düşür",
    )

    assert entry.status is PointsEntryStatus.ACTIVE
    assert entry.appeal_status is PointsAppealStatus.REJECTED
    assert entry.points == 40


def test_rejecting_without_an_open_dispute_is_refused() -> None:
    entry = _entry()
    with pytest.raises(DomainRuleError, match="etiraz yoxdur"):
        entry.reject_dispute(decided_by=MANAGER, decided_at=NOW, reason="Səbəb yazıldı")


def test_a_decided_row_cannot_be_decided_again() -> None:
    entry = _entry()
    entry.reverse(decided_by=MANAGER, decided_at=NOW, reason="Səhv işçiyə yazılıb")
    with pytest.raises(DomainRuleError, match="artıq verilib"):
        entry.correct(new_points=10, decided_by=MANAGER, decided_at=NOW, reason="İkinci düzəliş")


# --------------------------------------------------------------------------- #
# Mükafat mübadiləsi
# --------------------------------------------------------------------------- #


def _redemption(*, available: int = 500) -> RewardRedemption:
    return RewardRedemption(
        redemption_id=RedemptionId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=ASSIGNEE,
        reward_id=RewardId(uuid.uuid4()),
        reward=RewardItem(name="Kinoteatr bileti", cost_points=300),
        available_points=available,
        requested_at=NOW,
    )


def test_redemption_snapshots_the_cost_at_request_time() -> None:
    """Kataloq qiyməti sonradan qalxsa da, işçidən tutulan dəyişmir."""
    redemption = _redemption()
    assert redemption.cost_points == 300
    assert redemption.reward_name == "Kinoteatr bileti"


def test_redemption_requires_sufficient_points() -> None:
    with pytest.raises(InsufficientPointsError):
        _redemption(available=299)


def test_requested_redemption_holds_the_points() -> None:
    assert _redemption().holds_points


def test_rejection_releases_the_points() -> None:
    redemption = _redemption()
    redemption.reject(decided_by=MANAGER, decided_at=NOW, reason="Anbarda mükafat qalmayıb")
    assert redemption.status is RedemptionStatus.REJECTED
    assert not redemption.holds_points


def test_unapproved_redemption_cannot_be_fulfilled() -> None:
    """Təsdiq ≠ təhvil — sıra pozula bilməz."""
    redemption = _redemption()
    with pytest.raises(DomainRuleError):
        redemption.fulfil(fulfilled_at=NOW)


def test_approved_redemption_can_be_fulfilled() -> None:
    redemption = _redemption()
    redemption.approve(decided_by=MANAGER, decided_at=NOW)
    redemption.fulfil(fulfilled_at=NOW + timedelta(days=1))

    assert redemption.status is RedemptionStatus.FULFILLED
    assert redemption.holds_points


def test_a_decided_redemption_cannot_be_decided_again() -> None:
    redemption = _redemption()
    redemption.approve(decided_by=MANAGER, decided_at=NOW)
    with pytest.raises(DomainRuleError, match="artıq verilib"):
        redemption.approve(decided_by=MANAGER, decided_at=NOW)
