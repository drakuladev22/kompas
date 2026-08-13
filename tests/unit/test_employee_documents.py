"""İşçi Sənədləri (#17, kompasos11.md Faza 7) testləri.

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR — VƏ NİYƏ MƏHZ BU
──────────────────────────────────────────────────────────────────────────────
`test_labor_rules.py` (#14) ilə EYNİ struktur: #17-nin də ƏSAS TƏLƏBİ
"BLOKLAMIR"dır — ona görə Shift Matrix inteqrasiya testlərinin bir yarısı
pozuntunun (bitmiş bloklayıcı sənəd) AŞKARLANDIĞINI, digər yarısı isə
təyinatın buna BAXMAYARAQ yazıldığını təsbit edir.

Sahtələr BURADA, YERLİ təyin olunub (`tests/fixtures/fakes.py`-a əlavə
edilmir) — `test_labor_rules.py` başlığındakı EYNİ əsaslandırma: bu fayl
paralel işləyən başqa fazaların sahtə dəstindən asılı olmamalıdır.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from src.application.use_cases.document_compliance import DocumentComplianceAdvisor
from src.application.use_cases.employee_documents import (
    EmployeeDocumentDraft,
    EmployeeDocumentNotFoundError,
    EmployeeDocumentUseCase,
)
from src.application.use_cases.shift_scheduling import ShiftPlanningUseCase, ShiftSource
from src.domain.document_rules import (
    BlockingDocumentSnapshot,
    DocumentRuleKind,
    evaluate_document_rules,
)
from src.domain.entities.base import InvalidStateTransitionError
from src.domain.entities.employee import Employee
from src.domain.entities.employee_document import EmployeeDocument
from src.domain.entities.position import Position
from src.domain.entities.shift import ShiftAssignment
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeDocumentId,
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
    WorkModeId,
    new_employee_document_id,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
TODAY = date(2026, 8, 12)
NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)

MANAGE_DOCS = PermissionFlag(code="can_manage_employee_documents", category="HR")
MANAGE_SHIFTS = PermissionFlag(code="can_manage_shifts", category="HR")


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


@dataclass
class FakeClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


class FakeLimits:
    """`SystemLimits` — yalnız `get_str` işlədilir, qalanı istifadə olunmur."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return int(self._values.get(key, default))

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class FakeEmployeeDocuments:
    """`EmployeeDocumentRepository` — yaddaşda saxlanan sənəd sətirləri.

    Süzgəclər REAL SQL sorğularının (`migrations/020` indeksləri) davranışını
    güzgüləyir: `list_blocking_for_employee` yalnız aktiv+bloklayıcı,
    `list_expiring` yalnız aktiv+bitmə-tarixli sətirləri qaytarır — soft
    delete edilmiş sənəd HƏR İKİ sorğuda GÖRÜNMÜR (bax `chk_...` DB şərtinə
    paralel domen qaydası).
    """

    def __init__(self) -> None:
        self.rows: dict[EmployeeDocumentId, EmployeeDocument] = {}

    def get(self, document_id: EmployeeDocumentId) -> EmployeeDocument | None:
        return self.rows.get(document_id)

    def list_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId, *, include_inactive: bool = False
    ) -> list[EmployeeDocument]:
        return [
            d
            for d in self.rows.values()
            if d.tenant_id == tenant_id
            and d.employee_id == employee_id
            and (include_inactive or d.is_active)
        ]

    def list_blocking_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> list[EmployeeDocument]:
        return [
            d
            for d in self.rows.values()
            if d.tenant_id == tenant_id
            and d.employee_id == employee_id
            and d.is_active
            and d.is_blocking
        ]

    def list_expiring(self, tenant_id: TenantId, *, on_or_before: date) -> list[EmployeeDocument]:
        return [
            d
            for d in self.rows.values()
            if d.tenant_id == tenant_id
            and d.is_active
            and d.expiry_date is not None
            and d.expiry_date <= on_or_before
        ]

    def save(self, record: EmployeeDocument) -> None:
        self.rows[record.id] = record


class FakeEmployees:
    def __init__(self, employees: dict[EmployeeId, Employee] | None = None) -> None:
        self._employees = employees or {}

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._employees.get(employee_id)


class FakeShifts:
    """`ShiftRepository` — Shift Matrix inteqrasiya testləri üçün minimal."""

    def __init__(self) -> None:
        self.assignments: dict[tuple[EmployeeId, date], ShiftAssignment] = {}

    def get_assignment(self, employee_id: EmployeeId, work_date: date) -> ShiftAssignment | None:
        return self.assignments.get((employee_id, work_date))

    def save_assignment(self, assignment: ShiftAssignment) -> None:
        self.assignments[(assignment.employee_id, assignment.shift_date)] = assignment

    def clear_assignment(self, employee_id: EmployeeId, work_date: date) -> None:
        self.assignments.pop((employee_id, work_date), None)

    def list_range(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
        employee_ids: list[EmployeeId] | None = None,
    ) -> list[ShiftAssignment]:
        return [
            assignment
            for (employee_id, day), assignment in self.assignments.items()
            if start <= day <= end and (employee_ids is None or employee_id in employee_ids)
        ]

    def is_off_day(self, employee_id: EmployeeId, work_date: date) -> bool:
        assignment = self.assignments.get((employee_id, work_date))
        return assignment.is_off_day if assignment else False

    def scheduled_start(self, employee_id: EmployeeId, work_date: date) -> datetime | None:
        return None


class FakeLeaveRequests:
    def find_open_for_employee(self, employee_id: EmployeeId) -> None:
        return None


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.entries.append(kwargs)


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


def make_actor(*, flags: list[PermissionFlag] | None = None) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.HR_ADMIN.value,
        name_az="HR Admin",
        priority=SystemRole.HR_ADMIN.default_priority,
        is_system=True,
    )
    for flag in flags if flags is not None else [MANAGE_DOCS, MANAGE_SHIFTS]:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="H",
        last_name="Admin",
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def make_document(
    *,
    employee_id: EmployeeId = WORKER,
    doc_type: str = "SANITAR_KITABCA",
    expiry_date: date | None = None,
    is_blocking: bool = True,
    is_active: bool = True,
) -> EmployeeDocument:
    document = EmployeeDocument(
        document_id=new_employee_document_id(),
        tenant_id=TENANT,
        employee_id=employee_id,
        doc_type=doc_type,
        doc_number=None,
        file_ref=None,
        expiry_date=expiry_date,
        is_blocking=is_blocking,
        uploaded_by=None,
        created_at=NOW,
        updated_at=NOW,
    )
    if not is_active:
        document.deactivate(
            reason="Test üçün deaktiv edilib", deactivated_by=WORKER, now=NOW + timedelta(days=1)
        )
    return document


# --------------------------------------------------------------------------- #
# 1. `document_rules.evaluate_document_rules` — saf qayda
# --------------------------------------------------------------------------- #


def test_an_expired_blocking_document_is_reported() -> None:
    findings = evaluate_document_rules(
        reference_date=TODAY,
        blocking_documents=[
            BlockingDocumentSnapshot(
                doc_type="SANITAR_KITABCA", doc_number="12", expiry_date=TODAY - timedelta(days=1)
            )
        ],
    )
    assert len(findings) == 1
    assert findings[0].kind is DocumentRuleKind.EXPIRED_BLOCKING_DOCUMENT
    assert "bloklanmadı" in findings[0].message_az


def test_expiry_date_equal_to_today_is_not_yet_expired() -> None:
    """SƏRHƏD: bitmə tarixi bugünlə EYNİDİRSƏ sənəd HƏLƏ qüvvədədir."""
    findings = evaluate_document_rules(
        reference_date=TODAY,
        blocking_documents=[
            BlockingDocumentSnapshot(doc_type="MUQAVILE", doc_number=None, expiry_date=TODAY)
        ],
    )
    assert findings == []


def test_a_future_expiry_produces_no_warning() -> None:
    findings = evaluate_document_rules(
        reference_date=TODAY,
        blocking_documents=[
            BlockingDocumentSnapshot(
                doc_type="MUQAVILE", doc_number=None, expiry_date=TODAY + timedelta(days=1)
            )
        ],
    )
    assert findings == []


def test_multiple_expired_documents_each_get_their_own_finding() -> None:
    findings = evaluate_document_rules(
        reference_date=TODAY,
        blocking_documents=[
            BlockingDocumentSnapshot(
                doc_type="MUQAVILE", doc_number=None, expiry_date=TODAY - timedelta(days=5)
            ),
            BlockingDocumentSnapshot(
                doc_type="SANITAR_KITABCA", doc_number=None, expiry_date=TODAY - timedelta(days=2)
            ),
        ],
    )
    assert {f.doc_type for f in findings} == {"MUQAVILE", "SANITAR_KITABCA"}


# --------------------------------------------------------------------------- #
# 2. `EmployeeDocument` aqreqatı
# --------------------------------------------------------------------------- #


def test_doc_type_shorter_than_two_characters_is_rejected() -> None:
    with pytest.raises(Exception, match="Sənəd növü"):
        make_document(doc_type="A")


def test_doc_type_is_normalized_to_uppercase() -> None:
    document = make_document(doc_type="muqavile")
    assert document.doc_type == "MUQAVILE"


def test_is_expired_on_boundary_matches_the_domain_rule() -> None:
    document = make_document(expiry_date=TODAY)
    assert document.is_expired_on(TODAY) is False
    assert document.is_expired_on(TODAY + timedelta(days=1)) is True


def test_null_expiry_is_never_expired() -> None:
    document = make_document(expiry_date=None)
    assert document.is_expired_on(TODAY + timedelta(days=3650)) is False


def test_deactivating_a_document_requires_a_reason() -> None:
    document = make_document()
    with pytest.raises(Exception, match="minimum"):
        document.deactivate(reason="ok", deactivated_by=WORKER, now=NOW)


def test_deactivating_twice_raises() -> None:
    document = make_document()
    document.deactivate(reason="Sənəd səhvən yaradılıb", deactivated_by=WORKER, now=NOW)
    with pytest.raises(Exception, match="artıq deaktivdir"):
        document.deactivate(reason="Yenidən", deactivated_by=WORKER, now=NOW)


def test_an_inactive_document_cannot_be_updated() -> None:
    document = make_document(is_active=False)
    with pytest.raises(Exception, match="Deaktiv sənəd"):
        document.update(doc_number="X", expiry_date=None, is_blocking=True, now=NOW)


# --------------------------------------------------------------------------- #
# 3. `DocumentComplianceAdvisor` — mövcud sənədlərin yığımı
# --------------------------------------------------------------------------- #


def test_advisor_reports_an_expired_blocking_document() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY - timedelta(days=1)))
    advisor = DocumentComplianceAdvisor(documents=repo, clock=FakeClock())
    findings = advisor.review(tenant_id=TENANT, employee_id=WORKER)
    assert len(findings) == 1
    assert findings[0].kind is DocumentRuleKind.EXPIRED_BLOCKING_DOCUMENT


def test_advisor_ignores_a_non_blocking_expired_document() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY - timedelta(days=1), is_blocking=False))
    advisor = DocumentComplianceAdvisor(documents=repo, clock=FakeClock())
    assert advisor.review(tenant_id=TENANT, employee_id=WORKER) == []


def test_advisor_ignores_a_document_without_an_expiry_date() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=None, is_blocking=True))
    advisor = DocumentComplianceAdvisor(documents=repo, clock=FakeClock())
    assert advisor.review(tenant_id=TENANT, employee_id=WORKER) == []


def test_advisor_ignores_a_soft_deleted_document() -> None:
    """Deaktiv edilmiş sənəd `list_blocking_for_employee`-də ÜMUMİYYƏTLƏ görünmür."""
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY - timedelta(days=1), is_active=False))
    advisor = DocumentComplianceAdvisor(documents=repo, clock=FakeClock())
    assert advisor.review(tenant_id=TENANT, employee_id=WORKER) == []


# --------------------------------------------------------------------------- #
# 4. Shift Matrix inteqrasiyası — BLOKLAMIR
# --------------------------------------------------------------------------- #


def _planning_with_documents(repo: FakeEmployeeDocuments) -> ShiftPlanningUseCase:
    return ShiftPlanningUseCase(
        shifts=FakeShifts(),
        leave_requests=FakeLeaveRequests(),
        audit=RecordingAudit(),
        clock=FakeClock(),
        notifier=RecordingNotifier(),
        documents=DocumentComplianceAdvisor(documents=repo, clock=FakeClock()),
    )


def test_an_expired_blocking_document_produces_a_conflict_but_does_not_block() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY - timedelta(days=1)))
    planning = _planning_with_documents(repo)

    result = planning.apply_assignment(
        tenant_id=TENANT,
        actor_id=WORKER,
        employee_id=WORKER,
        shift_date=TODAY,
        is_off_day=False,
        work_mode_id=WorkModeId(uuid.uuid4()),
        source=ShiftSource.ADMIN_MATRIX,
    )

    assert result.assignment is not None, "Təyinat YAZILMALIDIR — sənəd bloklaması bloklamır"
    assert result.has_conflicts
    assert "DOCUMENT_EXPIRED_BLOCKING" in {c.kind for c in result.conflicts}


def test_a_non_blocking_expired_document_creates_no_conflict() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY - timedelta(days=1), is_blocking=False))
    planning = _planning_with_documents(repo)

    result = planning.apply_assignment(
        tenant_id=TENANT,
        actor_id=WORKER,
        employee_id=WORKER,
        shift_date=TODAY,
        is_off_day=False,
        work_mode_id=WorkModeId(uuid.uuid4()),
        source=ShiftSource.ADMIN_MATRIX,
    )
    assert result.conflicts == []


def test_an_unlimited_document_creates_no_conflict() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=None, is_blocking=True))
    planning = _planning_with_documents(repo)

    result = planning.apply_assignment(
        tenant_id=TENANT,
        actor_id=WORKER,
        employee_id=WORKER,
        shift_date=TODAY,
        is_off_day=False,
        work_mode_id=WorkModeId(uuid.uuid4()),
        source=ShiftSource.ADMIN_MATRIX,
    )
    assert result.conflicts == []


def test_the_conflict_reaches_the_audit_trail() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY - timedelta(days=1)))
    shifts = FakeShifts()
    audit = RecordingAudit()
    planning = ShiftPlanningUseCase(
        shifts=shifts,
        leave_requests=FakeLeaveRequests(),
        audit=audit,
        clock=FakeClock(),
        notifier=RecordingNotifier(),
        documents=DocumentComplianceAdvisor(documents=repo, clock=FakeClock()),
    )
    planning.apply_assignment(
        tenant_id=TENANT,
        actor_id=WORKER,
        employee_id=WORKER,
        shift_date=TODAY,
        is_off_day=False,
        work_mode_id=WorkModeId(uuid.uuid4()),
        source=ShiftSource.ADMIN_MATRIX,
    )
    entry = next(item for item in audit.entries if item["action"] == "SHIFT_ASSIGNED")
    after_state = entry["after_state"]
    assert isinstance(after_state, dict)
    assert "DOCUMENT_EXPIRED_BLOCKING" in after_state["conflicts"]


def test_without_the_advisor_the_use_case_behaves_exactly_as_before() -> None:
    """Fail-open: məsləhətçi qoşulmayıbsa Faza 5 davranışı toxunulmazdır."""
    planning = ShiftPlanningUseCase(
        shifts=FakeShifts(),
        leave_requests=FakeLeaveRequests(),
        audit=RecordingAudit(),
        clock=FakeClock(),
        notifier=RecordingNotifier(),
    )
    result = planning.apply_assignment(
        tenant_id=TENANT,
        actor_id=WORKER,
        employee_id=WORKER,
        shift_date=TODAY,
        is_off_day=False,
        work_mode_id=WorkModeId(uuid.uuid4()),
        source=ShiftSource.ADMIN_MATRIX,
    )
    assert result.conflicts == []
    assert result.assignment is not None


# --------------------------------------------------------------------------- #
# 5. `EmployeeDocumentUseCase` — CRUD + səlahiyyət
# --------------------------------------------------------------------------- #


def _use_case(
    repo: FakeEmployeeDocuments | None = None,
    *,
    employees: FakeEmployees | None = None,
    limits: FakeLimits | None = None,
    notifier: RecordingNotifier | None = None,
    clock: FakeClock | None = None,
) -> tuple[EmployeeDocumentUseCase, FakeEmployeeDocuments, RecordingAudit, RecordingNotifier]:
    documents_repo = repo or FakeEmployeeDocuments()
    audit = RecordingAudit()
    sent = notifier or RecordingNotifier()
    use_case = EmployeeDocumentUseCase(
        documents=documents_repo,
        employees=employees or FakeEmployees(),
        limits=limits or FakeLimits(),
        audit=audit,
        clock=clock or FakeClock(),
        notifier=sent,
    )
    return use_case, documents_repo, audit, sent


def test_create_document_requires_the_permission_flag() -> None:
    use_case, _, _, _ = _use_case()
    actor = make_actor(flags=[])
    with pytest.raises(AuthorizationError):
        use_case.create_document(
            tenant_id=TENANT,
            actor=actor,
            employee_id=WORKER,
            draft=EmployeeDocumentDraft(
                doc_type="MUQAVILE", doc_number=None, expiry_date=None, is_blocking=False
            ),
        )


def test_create_document_writes_and_audits() -> None:
    use_case, repo, audit, _ = _use_case()
    actor = make_actor()
    document = use_case.create_document(
        tenant_id=TENANT,
        actor=actor,
        employee_id=WORKER,
        draft=EmployeeDocumentDraft(
            doc_type="muqavile", doc_number="55", expiry_date=TODAY, is_blocking=True
        ),
    )
    assert repo.get(document.id) is not None
    assert document.doc_type == "MUQAVILE"
    assert any(e["action"] == "EMPLOYEE_DOCUMENT_CREATED" for e in audit.entries)


def test_update_document_changes_mutable_fields_only() -> None:
    use_case, repo, _, _ = _use_case()
    document = make_document(doc_type="MUQAVILE")
    repo.save(document)
    updated = use_case.update_document(
        tenant_id=TENANT,
        actor=make_actor(),
        document_id=document.id,
        doc_number="99",
        expiry_date=TODAY + timedelta(days=10),
        is_blocking=False,
    )
    assert updated.doc_type == "MUQAVILE"  # dəyişməz
    assert updated.doc_number == "99"
    assert updated.is_blocking is False


def test_update_missing_document_raises_not_found() -> None:
    use_case, _, _, _ = _use_case()
    with pytest.raises(EmployeeDocumentNotFoundError):
        use_case.update_document(
            tenant_id=TENANT,
            actor=make_actor(),
            document_id=EmployeeDocumentId(uuid.uuid4()),
            doc_number=None,
            expiry_date=None,
            is_blocking=False,
        )


def test_attach_file_fills_a_null_reference() -> None:
    use_case, repo, _, _ = _use_case()
    document = make_document()
    document.file_ref = None
    repo.save(document)
    updated = use_case.attach_file(
        tenant_id=TENANT,
        actor=make_actor(),
        document_id=document.id,
        file_ref="GOOGLE_DRIVE:abc:xyz",
    )
    assert updated.file_ref == "GOOGLE_DRIVE:abc:xyz"


def test_attach_uploaded_file_has_no_actor_but_still_audits() -> None:
    """#17: `EvidenceUploadWorker` geri-çağırışının aktoru YOXDUR (bax istifadə metodu başlığı)."""
    use_case, repo, audit, _ = _use_case()
    document = make_document()
    document.file_ref = None
    repo.save(document)

    use_case.attach_uploaded_file(
        tenant_id=TENANT,
        document_id=document.id,
        file_ref="GOOGLE_DRIVE:conn-1:file-9",
    )

    assert repo.get(document.id).file_ref == "GOOGLE_DRIVE:conn-1:file-9"
    entry = next(
        e for e in audit.entries if e["action"] == "EMPLOYEE_DOCUMENT_FILE_UPLOAD_COMPLETED"
    )
    # Canlı aktor yoxdur — audit sətri sənədi YARADAN şəxsə aid edilir.
    assert entry["actor_id"] == document.uploaded_by


def test_attach_uploaded_file_respects_the_domain_invariant() -> None:
    """Deaktiv sənədə fayl bağlamaq domen qaydasında YENƏ DƏ qadağandır."""
    use_case, repo, _, _ = _use_case()
    document = make_document()
    document.deactivate(reason="Sənəd artıq etibarsızdır", deactivated_by=WORKER, now=NOW)
    repo.save(document)

    with pytest.raises(InvalidStateTransitionError):
        use_case.attach_uploaded_file(
            tenant_id=TENANT,
            document_id=document.id,
            file_ref="GOOGLE_DRIVE:conn-1:file-9",
        )


def test_deactivate_document_is_a_soft_delete() -> None:
    use_case, repo, audit, _ = _use_case()
    document = make_document()
    repo.save(document)
    deactivated = use_case.deactivate_document(
        tenant_id=TENANT,
        actor=make_actor(),
        document_id=document.id,
        reason="Sənəd səhvən ikinci dəfə yaradılıb",
    )
    assert deactivated.is_active is False
    assert repo.get(document.id) is not None, "Sətir SİLİNMİR — yalnız deaktiv olunur"
    assert any(e["action"] == "EMPLOYEE_DOCUMENT_DEACTIVATED" for e in audit.entries)


def test_a_different_tenant_actor_is_rejected() -> None:
    use_case, _, _, _ = _use_case()
    foreign_actor = make_actor()
    with pytest.raises(AuthorizationError):
        use_case.list_for_employee(
            tenant_id=TenantId(uuid.uuid4()), actor=foreign_actor, employee_id=WORKER
        )


# --------------------------------------------------------------------------- #
# 6. Bitmə xəbərdarlığı — 30/14/7 sərhədləri və təkrarsızlıq
# --------------------------------------------------------------------------- #


def test_a_document_expiring_in_exactly_30_days_triggers_a_warning() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY + timedelta(days=30)))
    use_case, _, _, notifier = _use_case(repo, clock=FakeClock(NOW))
    sent = use_case.notify_expiring_documents(TENANT)
    assert sent == 1
    assert notifier.messages[0]["is_critical"] is True
    assert notifier.messages[0]["category"] == "EMPLOYEE_DOCUMENT_EXPIRING"


def test_a_document_expiring_in_29_days_does_not_trigger() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY + timedelta(days=29)))
    use_case, _, _, notifier = _use_case(repo, clock=FakeClock(NOW))
    assert use_case.notify_expiring_documents(TENANT) == 0
    assert notifier.messages == []


@pytest.mark.parametrize("threshold", [30, 14, 7])
def test_each_configured_threshold_triggers_exactly_once(threshold: int) -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY + timedelta(days=threshold)))
    use_case, _, _, notifier = _use_case(repo, clock=FakeClock(NOW))
    assert use_case.notify_expiring_documents(TENANT) == 1
    assert len(notifier.messages) == 1


def test_the_same_threshold_is_not_renotified_the_next_day() -> None:
    """TƏKRARSIZLIQ: bərabərlik-yoxlaması ilə (bax `employee_documents.py`
    başlığı) — ertəsi gün eyni sənəd artıq HEÇ BİR həddə düşmür, çünki
    günlər_qalıb 30-dan 29-a düşüb."""
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY + timedelta(days=30)))
    clock = FakeClock(NOW)
    use_case, _, _, notifier = _use_case(repo, clock=clock)

    assert use_case.notify_expiring_documents(TENANT) == 1
    clock.moment = NOW + timedelta(days=1)
    assert use_case.notify_expiring_documents(TENANT) == 0
    assert len(notifier.messages) == 1, "Ertəsi gün TƏKRAR bildiriş getməməlidir"


def test_a_deactivated_document_is_excluded_from_expiry_warnings() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY + timedelta(days=7), is_active=False))
    use_case, _, _, notifier = _use_case(repo, clock=FakeClock(NOW))
    assert use_case.notify_expiring_documents(TENANT) == 0
    assert notifier.messages == []


def test_warning_days_are_configurable_via_system_limits() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY + timedelta(days=3)))
    limits = FakeLimits({"EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS": "3"})
    use_case, _, _, notifier = _use_case(repo, limits=limits, clock=FakeClock(NOW))
    assert use_case.notify_expiring_documents(TENANT) == 1
    assert len(notifier.messages) == 1


def test_malformed_limit_values_are_skipped_not_fatal() -> None:
    repo = FakeEmployeeDocuments()
    repo.save(make_document(expiry_date=TODAY + timedelta(days=30)))
    limits = FakeLimits({"EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS": "30,,abc,-5"})
    use_case, _, _, notifier = _use_case(repo, limits=limits, clock=FakeClock(NOW))
    assert use_case.notify_expiring_documents(TENANT) == 1
    assert len(notifier.messages) == 1
