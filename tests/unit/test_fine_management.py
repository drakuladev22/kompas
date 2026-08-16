"""Manual cərimə və 72-saatlıq etiraz testləri (bölmə 4) — Faza 5."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.application.use_cases.fine_management import (
    AppealWindowClosedError,
    FineAppealUseCase,
    FinePermissionError,
    ManualFineUseCase,
)
from src.application.use_cases.leave_verification import OperationNotPermittedError
from src.domain.entities.appeal import AppealStatus, FineAppeal
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee
from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.catalogs import FineType
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FineTypeId,
    PositionId,
    StoreId,
    TenantId,
    new_appeal_id,
    new_fine_id,
)
from src.domain.value_objects.money import Money
from tests.fixtures.fakes import (
    FakeCameraAssignments,
    FakeClock,
    FakeFeatureToggles,
    FakeFineTypes,
    FakeSystemLimits,
    InMemoryAppeals,
    InMemoryFines,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
FINE_TYPE = FineTypeId(uuid.uuid4())
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

ISSUE_FINES = PermissionFlag(
    code="can_issue_fines", category="KAMERA_CERIME", is_anti_fraud=True, is_camera_only=True
)
APPROVE_APPEAL = PermissionFlag(code="can_approve_leave_appeal", category="HR")

UNIFORM_FINE = FineType(
    name="Formaya uyğun geyinməmək",
    tenant_id=TENANT,
    fine_type_id=FINE_TYPE,
    standard_amount=Money(Decimal("25.00")),
)


def make_employee(
    role: SystemRole, *, flags: list[PermissionFlag], employee_id: EmployeeId | None = None
) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for flag in flags:
        position.grant(flag)
    return Employee(
        employee_id=employee_id or EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


class Ctx:
    def __init__(self) -> None:
        self.clock = FakeClock(NOW)
        self.fines = InMemoryFines()
        self.appeals = InMemoryAppeals()
        self.fine_types = FakeFineTypes({FINE_TYPE: UNIFORM_FINE})
        self.limits = FakeSystemLimits()
        self.toggles = FakeFeatureToggles()
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()
        self.operator = make_employee(SystemRole.CAMERA_OPERATOR, flags=[ISSUE_FINES])
        self.cameras = FakeCameraAssignments({self.operator.id: [STORE]})

    def manual(self) -> ManualFineUseCase:
        return ManualFineUseCase(
            fines=self.fines,  # type: ignore[arg-type]
            fine_types=self.fine_types,  # type: ignore[arg-type]
            camera_assignments=self.cameras,  # type: ignore[arg-type]
            limits=self.limits,  # type: ignore[arg-type]
            toggles=self.toggles,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def appeals_uc(self) -> FineAppealUseCase:
        return FineAppealUseCase(
            appeals=self.appeals,  # type: ignore[arg-type]
            fines=self.fines,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def published_fine(self) -> Fine:
        """Nəşr olunmuş, etiraz pəncərəsi AÇIQ cərimə."""
        fine = Fine(
            fine_id=new_fine_id(),
            tenant_id=TENANT,
            employee_id=WORKER,
            store_id=STORE,
            source=FineSource.MANUAL_CAMERA,
            amount=Money(Decimal("25.00")),
            issued_at=NOW,
            fine_type_id=FINE_TYPE,
            issued_by=self.operator.id,
            photo_evidence_url="drive://evidence-1",
        )
        fine.publish(reviewed_by=self.operator.id, published_at=NOW)
        self.fines.save(fine)
        return fine


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


# --------------------------------------------------------------------------- #
# Manual cərimə — anti-fraud
# --------------------------------------------------------------------------- #


def test_amount_comes_from_the_catalog_not_the_caller(ctx: Ctx) -> None:
    """Bölmə 4: operator sərbəst məbləğ təyin edə BİLMİR."""
    fine = ctx.manual().issue(
        tenant_id=TENANT,
        operator=ctx.operator,
        employee_id=WORKER,
        store_id=STORE,
        fine_type_id=FINE_TYPE,
        evidence_reference="drive://evidence-1",
    )

    assert fine.amount == Money(Decimal("25.00"))
    assert fine.source is FineSource.MANUAL_CAMERA


def test_evidence_is_mandatory(ctx: Ctx) -> None:
    with pytest.raises(OperationNotPermittedError, match="foto sübutu"):
        ctx.manual().issue(
            tenant_id=TENANT,
            operator=ctx.operator,
            employee_id=WORKER,
            store_id=STORE,
            fine_type_id=FINE_TYPE,
            evidence_reference="   ",
        )


def test_operator_cannot_fine_an_unassigned_store(ctx: Ctx) -> None:
    """Bölmə 4: öz izləmədiyi mağazanın işçisinə cərimə yaza bilməz."""
    with pytest.raises(FinePermissionError, match="təyin edilməyib"):
        ctx.manual().issue(
            tenant_id=TENANT,
            operator=ctx.operator,
            employee_id=WORKER,
            store_id=OTHER_STORE,
            fine_type_id=FINE_TYPE,
            evidence_reference="drive://evidence-1",
        )


def test_issuing_requires_the_flag(ctx: Ctx) -> None:
    stranger = make_employee(SystemRole.HR_ADMIN, flags=[])
    ctx.cameras.mapping[stranger.id] = [STORE]

    with pytest.raises(FinePermissionError, match="can_issue_fines"):
        ctx.manual().issue(
            tenant_id=TENANT,
            operator=stranger,
            employee_id=WORKER,
            store_id=STORE,
            fine_type_id=FINE_TYPE,
            evidence_reference="drive://evidence-1",
        )


def test_new_fine_is_not_visible_to_the_worker_yet(ctx: Ctx) -> None:
    """Cərimə `PENDING_REVIEW` doğulur (aylıq icmal qərarı)."""
    fine = ctx.manual().issue(
        tenant_id=TENANT,
        operator=ctx.operator,
        employee_id=WORKER,
        store_id=STORE,
        fine_type_id=FINE_TYPE,
        evidence_reference="drive://evidence-1",
    )
    assert fine.status is FineStatus.PENDING_REVIEW
    assert not fine.is_visible_to_employee


# --------------------------------------------------------------------------- #
# Etiraz
# --------------------------------------------------------------------------- #


def test_worker_can_appeal_their_own_published_fine(ctx: Ctx) -> None:
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)

    appeal = ctx.appeals_uc().submit(
        tenant_id=TENANT,
        employee=worker,
        fine_id=fine.id,
        reason="Həmin gün formada idim, kamera səhv göstərir",
    )

    assert appeal.status is AppealStatus.PENDING
    assert "FINE_APPEAL_SUBMITTED" in ctx.audit.actions()


def test_appealing_someone_elses_fine_is_blocked(ctx: Ctx) -> None:
    fine = ctx.published_fine()
    stranger = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(FinePermissionError, match="Başqasının"):
        ctx.appeals_uc().submit(
            tenant_id=TENANT,
            employee=stranger,
            fine_id=fine.id,
            reason="Bu mənim deyil, amma etiraz edirəm",
        )


def test_unpublished_fine_cannot_be_appealed(ctx: Ctx) -> None:
    """İşçi cəriməni hələ GÖRMƏYİB."""
    fine = Fine(
        fine_id=new_fine_id(),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal("25.00")),
        issued_at=NOW,
        fine_type_id=FINE_TYPE,
        issued_by=ctx.operator.id,
        photo_evidence_url="drive://evidence-1",
    )
    ctx.fines.save(fine)
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)

    with pytest.raises(OperationNotPermittedError, match="Nəşr olunmamış"):
        ctx.appeals_uc().submit(
            tenant_id=TENANT, employee=worker, fine_id=fine.id, reason="Razı deyiləm"
        )


def test_appeal_after_the_window_is_rejected(ctx: Ctx) -> None:
    """72 saatlıq pəncərə bağlandıqdan sonra etiraz qəbul edilmir."""
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)
    ctx.clock.set(NOW + timedelta(hours=73))

    with pytest.raises(AppealWindowClosedError):
        ctx.appeals_uc().submit(
            tenant_id=TENANT,
            employee=worker,
            fine_id=fine.id,
            reason="Gec oldu, amma etiraz edirəm",
        )


def test_second_appeal_for_the_same_fine_is_blocked(ctx: Ctx) -> None:
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)
    use_case = ctx.appeals_uc()
    use_case.submit(tenant_id=TENANT, employee=worker, fine_id=fine.id, reason="Birinci etirazım")

    with pytest.raises(OperationNotPermittedError, match="artıq etiraz"):
        use_case.submit(
            tenant_id=TENANT, employee=worker, fine_id=fine.id, reason="İkinci etirazım"
        )


def test_approving_an_appeal_reverses_the_fine_without_deleting_it(ctx: Ctx) -> None:
    """Bölmə 4: orijinal qeyd HEÇ VAXT silinmir."""
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)
    use_case = ctx.appeals_uc()
    appeal = use_case.submit(
        tenant_id=TENANT, employee=worker, fine_id=fine.id, reason="Kamera səhv göstərir"
    )

    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_APPEAL])
    decision = use_case.approve(
        tenant_id=TENANT,
        actor=hr,
        appeal_id=appeal.id,
        note="Görüntü yenidən yoxlanıldı, işçi haqlıdır",
    )

    assert decision.was_approved
    assert decision.fine.status is FineStatus.REVERSED
    assert decision.fine.original_amount == Money(Decimal("25.00"))
    assert decision.fine.amount.is_zero


def test_partial_approval_reduces_instead_of_cancelling(ctx: Ctx) -> None:
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)
    use_case = ctx.appeals_uc()
    appeal = use_case.submit(
        tenant_id=TENANT, employee=worker, fine_id=fine.id, reason="Məbləğ çox yüksəkdir"
    )

    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_APPEAL])
    decision = use_case.approve(
        tenant_id=TENANT,
        actor=hr,
        appeal_id=appeal.id,
        note="Qismən qəbul edildi, məbləğ azaldıldı",
        new_amount=Money(Decimal("10.00")),
    )

    assert decision.fine.status is FineStatus.REDUCED
    assert decision.fine.amount == Money(Decimal("10.00"))


def test_deciding_requires_the_flag(ctx: Ctx) -> None:
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)
    use_case = ctx.appeals_uc()
    appeal = use_case.submit(
        tenant_id=TENANT, employee=worker, fine_id=fine.id, reason="Razı deyiləm"
    )

    with pytest.raises(FinePermissionError, match="can_approve_leave_appeal"):
        use_case.reject(
            tenant_id=TENANT, actor=worker, appeal_id=appeal.id, note="Özüm rədd edirəm"
        )


def test_worker_cannot_decide_their_own_appeal() -> None:
    appeal = FineAppeal(
        appeal_id=new_appeal_id(),
        tenant_id=TENANT,
        fine_id=new_fine_id(),
        employee_id=WORKER,
        reason="Bu cərimə haqsızdır",
        created_at=NOW,
    )
    with pytest.raises(DomainRuleError, match="öz etirazına"):
        appeal.approve(decided_by=WORKER, decided_at=NOW, note="Özüm qəbul edirəm")


def test_expired_appeals_are_closed_by_the_scheduler(ctx: Ctx) -> None:
    """Cavabsız qalan etiraz sükutla itmir — `EXPIRED` olur."""
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)
    use_case = ctx.appeals_uc()
    use_case.submit(tenant_id=TENANT, employee=worker, fine_id=fine.id, reason="Razı deyiləm")

    ctx.clock.set(NOW + timedelta(hours=80))
    closed = use_case.expire_stale(TENANT)

    assert closed == 1
    assert all(item.status is AppealStatus.EXPIRED for item in ctx.appeals.items.values())


# --------------------------------------------------------------------------- #
# M-6 — pəncərə bağlananda GÖZLƏYƏN etiraz
# --------------------------------------------------------------------------- #


def _appealed_fine(ctx: Ctx) -> tuple[Fine, Employee, FineAppealUseCase]:
    """Nəşr olunmuş cərimə + işçinin göndərdiyi etiraz."""
    fine = ctx.published_fine()
    worker = make_employee(SystemRole.SELLER, flags=[], employee_id=WORKER)
    use_case = ctx.appeals_uc()
    use_case.submit(
        tenant_id=TENANT,
        employee=worker,
        fine_id=fine.id,
        reason="Həmin gün formada idim, kamera səhv göstərir",
    )
    return fine, worker, use_case


def test_an_open_appeal_blocks_the_export_even_before_the_window_closes(ctx: Ctx) -> None:
    """Etiraz göndərilən an cərimə MÜBAHİSƏLİ olur."""
    fine, _worker, _use_case = _appealed_fine(ctx)

    assert fine.has_open_appeal is True
    assert fine.is_exportable(now=NOW + timedelta(hours=80)) is False


def test_an_unanswered_appeal_keeps_the_fine_out_of_the_export(ctx: Ctx) -> None:
    """M-6-nın MƏĞZİ: HR baxmayıbsa, pul KƏSİLMİR.

    Əvvəl `expire_stale` cəriməni export-a buraxırdı — yəni HR-ın süstlüyü
    işçidən real pul kəsintisi ilə nəticələnirdi.
    """
    fine, _worker, use_case = _appealed_fine(ctx)
    after_window = NOW + timedelta(hours=80)
    ctx.clock.set(after_window)

    assert use_case.expire_stale(TENANT) == 1

    assert fine.is_exportable(now=after_window) is False
    assert "FINE_APPEAL_SLA_BREACH" in ctx.notifier.categories()


def test_an_expired_appeal_can_still_be_decided(ctx: Ctx) -> None:
    """72 saat İŞÇİNİN göndərmə hüququnun müddətidir, HR-ın cavab borcunun YOX."""
    fine, _worker, use_case = _appealed_fine(ctx)
    ctx.clock.set(NOW + timedelta(hours=80))
    use_case.expire_stale(TENANT)
    appeal = next(iter(ctx.appeals.items.values()))
    assert appeal.status is AppealStatus.EXPIRED

    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_APPEAL])
    decision = use_case.approve(
        tenant_id=TENANT,
        actor=hr,
        appeal_id=appeal.id,
        note="Görüntü yenidən yoxlanıldı, işçi haqlıdır",
    )

    assert decision.was_approved
    assert decision.fine.status is FineStatus.REVERSED
    assert fine.has_open_appeal is False


def test_an_undecided_appeal_stays_in_the_hr_inbox_after_the_window(ctx: Ctx) -> None:
    """`EXPIRED` sətir inbox-dan düşsəydi, cərimə əbədi bloklanardı."""
    _fine, _worker, use_case = _appealed_fine(ctx)
    ctx.clock.set(NOW + timedelta(hours=80))
    use_case.expire_stale(TENANT)

    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_APPEAL])
    inbox = use_case.inbox(tenant_id=TENANT, actor=hr)

    assert len(inbox) == 1
    assert inbox[0].status is AppealStatus.EXPIRED
    assert inbox[0].is_overdue(now=ctx.clock.now()) is True
    assert use_case.undecided_count(TENANT) == 1


def test_rejecting_an_appeal_releases_the_export_lock(ctx: Ctx) -> None:
    """Rədd də QƏRARDIR — cərimə qüvvədə qalır və hesabata düşə bilir."""
    fine, _worker, use_case = _appealed_fine(ctx)
    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_APPEAL])
    appeal = next(iter(ctx.appeals.items.values()))

    use_case.reject(
        tenant_id=TENANT,
        actor=hr,
        appeal_id=appeal.id,
        note="Görüntüdə işçi forma geyinməyib, etiraz əsassızdır",
    )

    assert fine.has_open_appeal is False
    assert fine.status is FineStatus.PUBLISHED
    assert fine.is_exportable(now=NOW + timedelta(hours=80)) is True
    assert use_case.undecided_count(TENANT) == 0


def test_reversal_after_export_raises_a_payroll_correction_alarm(ctx: Ctx) -> None:
    """M-6, bənd 3: export-dan sonra ləğv SÜKUTLA baş verə bilməz.

    `exported_period` sıfırlanmır (əks halda növbəti export cəriməni yenidən
    tutardı) — ona görə düzəlişin YEGANƏ siqnalı bu kritik bildirişdir.
    """
    fine, _worker, use_case = _appealed_fine(ctx)
    fine.exported_period = "2026-08"  # hesabat artıq göndərilib
    hr = make_employee(SystemRole.HR_ADMIN, flags=[APPROVE_APPEAL])
    appeal = next(iter(ctx.appeals.items.values()))

    decision = use_case.approve(
        tenant_id=TENANT,
        actor=hr,
        appeal_id=appeal.id,
        note="Görüntü yenidən yoxlanıldı, cərimə səhvdir",
    )

    assert decision.fine.requires_payroll_correction is True
    assert decision.fine.exported_period == "2026-08"
    assert "FINE_REVERSED_AFTER_EXPORT" in ctx.notifier.categories()


# --------------------------------------------------------------------------- #
# Etiraz SLA-sı — ROOT limiti, kodda sabit ədəd deyil (bölmə 3, bənd 1)
# --------------------------------------------------------------------------- #


def test_appeal_sla_follows_the_given_window_not_a_hardcoded_72() -> None:
    """`is_overdue` çağıranın ötürdüyü pəncərəni işlətməlidir.

    72 saat `MIN_APPEAL_SLA_HOURS` fallback-ıdır; həqiqi dəyər
    `system_limits.FINE_APPEAL_WINDOW_HOURS`-dan gəlir və Root onu dəyişə
    bilər. Əgər metod defoltu zorla tətbiq etsəydi, Root sürüşdürücünü
    dəyişəndə HR inbox-u yenə 72 saata görə vurğulayardı.
    """
    from src.domain.value_objects.identifiers import AppealId, FineId

    created = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    appeal = FineAppeal(
        appeal_id=AppealId(uuid.uuid4()),
        tenant_id=TENANT,
        fine_id=FineId(uuid.uuid4()),
        employee_id=EmployeeId(uuid.uuid4()),
        reason="Həmin gün xəstəxanada idim, arayış əlavə edirəm.",
        created_at=created,
    )
    after_30h = created + timedelta(hours=30)

    assert appeal.is_overdue(now=after_30h) is False, "72 saatlıq fallback hələ aşılmayıb"
    assert appeal.is_overdue(now=after_30h, sla_hours=24) is True, (
        "Root pəncərəni 24 saata endirdikdə etiraz gecikmiş sayılmalıdır"
    )
    assert appeal.is_overdue(now=after_30h, sla_hours=168) is False, (
        "Root pəncərəni genişləndirdikdə vurğu götürülməlidir"
    )


def test_caller_supplied_fine_id_is_honoured(ctx: Ctx) -> None:
    """Sübut növbəsi `fine_id`-ni ƏVVƏLCƏDƏN bilməlidir.

    Növbə sətri `fine_id` tələb edir, cərimə isə növbə açarını sübut istinadı
    kimi saxlayır. Biri digərini gözləsəydi dövrə bağlanardı — ona görə
    identifikator kənardan verilir (`TaskWorkflowUseCase.assign` naxışı).
    """
    from src.domain.value_objects.identifiers import new_fine_id

    chosen = new_fine_id()
    fine = ctx.manual().issue(
        tenant_id=TENANT,
        operator=ctx.operator,
        employee_id=WORKER,
        store_id=STORE,
        fine_type_id=FINE_TYPE,
        evidence_reference="queue-entry-1",
        fine_id=chosen,
    )

    assert fine.id == chosen
    assert ctx.fines.items[chosen].photo_evidence_url == "queue-entry-1"


def test_omitted_fine_id_still_generates_one(ctx: Ctx) -> None:
    """Köhnə çağırış yolu dəyişməməlidir."""
    fine = ctx.manual().issue(
        tenant_id=TENANT,
        operator=ctx.operator,
        employee_id=WORKER,
        store_id=STORE,
        fine_type_id=FINE_TYPE,
        evidence_reference="drive://evidence-9",
    )
    assert fine.id is not None
