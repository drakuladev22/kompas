"""Domen aqreqatlarının testləri (Faza 2.2) — vəziyyət maşınları və qaydalar."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from src.domain.entities import (
    AttendanceRecord,
    CheckInStatus,
    DomainRuleError,
    Employee,
    Fine,
    FineSource,
    FineStatus,
    InvalidStateTransitionError,
    LeaveRequest,
    LeaveStatus,
    PermissionOverride,
    Position,
)
from src.domain.events import (
    FineIssuedEvent,
    LeaveRequestedEvent,
    LeaveVerifiedEvent,
    ManualTimeOverrideEvent,
    MorningCheckInVerifiedEvent,
    UnauthorizedAbsenceDetectedEvent,
    VerificationTimeoutEscalatedEvent,
)
from src.domain.value_objects import (
    DUAL_CONTROL_APPROVAL_FLAG,
    AuthorizationError,
    EmailAddress,
    HardlockLevel,
    Money,
    PermissionEffect,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    FineId,
    FineTypeId,
    LeaveRequestId,
    PositionId,
    StoreId,
    TenantId,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
OPERATOR = EmployeeId(uuid.uuid4())
APPROVER = EmployeeId(uuid.uuid4())


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 8, hour, minute, tzinfo=UTC)


def make_position(
    role: SystemRole, *, priority: RolePriority | None = None, camera: bool = False
) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=priority or role.default_priority,
        is_system=True,
        is_camera_type=camera or role.is_camera_type,
    )


def make_employee(
    role: SystemRole = SystemRole.SELLER, *, employee_id: EmployeeId | None = None
) -> Employee:
    admin_tier = role is not SystemRole.SELLER and role is not SystemRole.STORE_MANAGER
    return Employee(
        employee_id=employee_id or EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=make_position(role),
        first_name="Test",
        last_name=role.value,
        store_id=STORE,
        email=EmailAddress.parse(f"{role.value.lower()}@kompas.az") if admin_tier else None,
        has_password=admin_tier,
        has_pin=not admin_tier or role is SystemRole.HR_ADMIN,
    )


# --------------------------------------------------------------------------- #
# LeaveRequest — 3-STEP vəziyyət maşını
# --------------------------------------------------------------------------- #


def open_leave(*, allowance: int = 60) -> LeaveRequest:
    return LeaveRequest.open(
        request_id=LeaveRequestId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        requested_time=at(12, 0),
        allowance_minutes=allowance,
        ntp_verified=True,
        employee_is_in_store=True,
    )


def test_step1_requires_employee_in_store() -> None:
    """Bölmə 4: işçi günə başlamadan icazə istəyə bilməz."""
    with pytest.raises(DomainRuleError, match="Mağazada"):
        LeaveRequest.open(
            request_id=LeaveRequestId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=WORKER,
            store_id=STORE,
            requested_time=at(12, 0),
            employee_is_in_store=False,
        )


def test_step1_records_event_and_timestamp() -> None:
    leave = open_leave()
    events = leave.collect_events()

    assert leave.status is LeaveStatus.OUTSIDE
    assert leave.requested_time == at(12, 0)
    assert len(events) == 1
    assert isinstance(events[0], LeaveRequestedEvent)


def test_requested_time_is_immutable() -> None:
    leave = open_leave()
    with pytest.raises(AttributeError):
        leave.requested_time = at(13, 0)  # type: ignore[misc]


def test_step2_only_from_outside() -> None:
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))
    assert leave.status is LeaveStatus.PENDING_RETURN_VERIFICATION

    # İkinci dəfə basmaq mümkün deyil
    with pytest.raises(InvalidStateTransitionError):
        leave.claim_return(claimed_at=at(13, 5))


def test_full_happy_path_penalty() -> None:
    """60 dəq. icazə, 90 dəq. sonra qayıdış → Delay=30, Total=120."""
    leave = open_leave(allowance=60)
    leave.claim_return(claimed_at=at(13, 30))
    penalty = leave.verify_return(operator_id=OPERATOR, verified_at=at(13, 30))

    assert leave.status is LeaveStatus.VERIFIED
    assert penalty.delay_minutes == 30
    assert penalty.total_minutes == 120


def test_option_a_uses_operator_click_time() -> None:
    """Bölmə 4, Option A: `[Təsdiqlə]` CARİ SİSTEM VAXTINI istifadə edir.

    Operator gec kliklədisə, gecikmə də ona görə hesablanır — bu, qəsdəndir:
    faktiki qayıdışı təsdiqləmək operatorun məsuliyyətidir. Əgər real qayıdış
    daha erkən olubsa, Option B (`[Vaxtı Əllə Təyin Et]`) istifadə edilməlidir.
    """
    leave = open_leave(allowance=60)
    leave.claim_return(claimed_at=at(13, 30))
    penalty = leave.verify_return(operator_id=OPERATOR, verified_at=at(13, 32))

    assert penalty.elapsed_minutes == 92
    assert penalty.delay_minutes == 32


def test_penalty_uses_actual_return_not_click_time() -> None:
    """KRİTİK (bölmə 4): cərimə operatorun klik vaxtına əsaslanmır."""
    leave = open_leave(allowance=60)
    leave.claim_return(claimed_at=at(13, 0))

    # Operator 2 saat gec kliklədi, lakin faktiki qayıdış 13:00-dır
    penalty = leave.verify_return(
        operator_id=OPERATOR, verified_at=at(15, 0), actual_return_time=at(13, 0)
    )

    assert penalty.elapsed_minutes == 60
    assert penalty.delay_minutes == 0
    assert leave.verified_at == at(15, 0)  # audit üçün klik vaxtı da saxlanılır
    assert leave.actual_return_time == at(13, 0)


def test_verify_emits_event_with_correct_fields() -> None:
    leave = open_leave(allowance=60)
    leave.claim_return(claimed_at=at(13, 30))
    leave.collect_events()

    leave.verify_return(operator_id=OPERATOR, verified_at=at(13, 30))
    event = leave.collect_events()[0]

    assert isinstance(event, LeaveVerifiedEvent)
    assert event.delay_minutes == 30
    assert event.total_minutes == 120
    assert event.was_manual_override is False


def test_cannot_verify_before_claim() -> None:
    leave = open_leave()
    with pytest.raises(InvalidStateTransitionError):
        leave.verify_return(operator_id=OPERATOR, verified_at=at(13, 0))


# --------------------------- manual override -------------------------------- #


def test_override_requires_reason_length() -> None:
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))

    with pytest.raises(DomainRuleError, match="10 simvol"):
        leave.apply_manual_override(
            operator_id=OPERATOR,
            overridden_time=at(12, 50),
            system_time=at(13, 0),
            reason="qısa",
        )


def test_override_rejects_time_before_request() -> None:
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))

    with pytest.raises(DomainRuleError, match="əvvəl"):
        leave.apply_manual_override(
            operator_id=OPERATOR,
            overridden_time=at(11, 0),
            system_time=at(13, 0),
            reason="Kameradan yoxlanıldı, işçi daha tez qayıtmışdı",
        )


def test_override_rejects_future_time() -> None:
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))

    with pytest.raises(DomainRuleError, match="Gələcək"):
        leave.apply_manual_override(
            operator_id=OPERATOR,
            overridden_time=at(14, 0),
            system_time=at(13, 0),
            reason="Kameradan yoxlanıldı, gələcək vaxt cəhdi",
        )


def test_small_override_does_not_need_dual_control() -> None:
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))

    override = leave.apply_manual_override(
        operator_id=OPERATOR,
        overridden_time=at(12, 45),
        system_time=at(13, 0),
        reason="Kameradan təsdiqləndi, işçi 12:45-də qayıtdı",
    )

    assert override.delta_minutes == 15
    assert override.requires_dual_control is False
    assert override.is_pending_approval is False


def test_large_override_triggers_dual_control() -> None:
    """Bölmə 4: 30+ dəqiqəlik override ikinci təsdiqə düşür."""
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))

    override = leave.apply_manual_override(
        operator_id=OPERATOR,
        overridden_time=at(12, 25),
        system_time=at(13, 0),
        reason="Kameradan təsdiqləndi, işçi 12:25-də qayıtdı",
    )

    assert override.delta_minutes == 35
    assert override.requires_dual_control is True
    assert override.is_pending_approval is True

    event = next(e for e in leave.collect_events() if isinstance(e, ManualTimeOverrideEvent))
    assert event.requires_dual_control is True


def test_operator_cannot_approve_own_override() -> None:
    """SEC-001 / vəzifə ayrılığı — DB CHECK ilə eyni qayda."""
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))
    leave.apply_manual_override(
        operator_id=OPERATOR,
        overridden_time=at(12, 25),
        system_time=at(13, 0),
        reason="Kameradan təsdiqləndi, işçi 12:25-də qayıtdı",
    )

    with pytest.raises(DomainRuleError, match="özü təsdiqləyə bilməz"):
        leave.approve_override(approver_id=OPERATOR, approved_at=at(13, 10))

    leave.approve_override(approver_id=APPROVER, approved_at=at(13, 10))
    assert leave.override is not None
    assert leave.override.is_pending_approval is False


# ------------------------------- timeout ------------------------------------ #


def test_timeout_escalation_after_45_minutes() -> None:
    leave = open_leave()
    leave.claim_return(claimed_at=at(13, 0))
    leave.collect_events()

    assert leave.escalate_timeout(now=at(13, 44)) is False
    assert leave.escalate_timeout(now=at(13, 45)) is True
    assert leave.status is LeaveStatus.TIMEOUT_ESCALATED

    event = leave.collect_events()[0]
    assert isinstance(event, VerificationTimeoutEscalatedEvent)
    assert event.subject_type == "LEAVE_RETURN"

    # Təkrar eskalasiya bildirişi göndərilmir
    assert leave.escalate_timeout(now=at(14, 30)) is False


def test_escalated_leave_can_still_be_verified() -> None:
    leave = open_leave(allowance=60)
    leave.claim_return(claimed_at=at(13, 0))
    leave.escalate_timeout(now=at(13, 45))

    penalty = leave.verify_return(operator_id=APPROVER, verified_at=at(13, 50))
    assert leave.status is LeaveStatus.VERIFIED
    assert penalty.delay_minutes == 50


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (SystemRole.HR_ADMIN, True),
        (SystemRole.CEO, True),
        (SystemRole.ROOT, True),
        (SystemRole.STORE_MANAGER, False),  # dual-control tiering — bölmə 4
        (SystemRole.CAMERA_OPERATOR, False),
        (SystemRole.SELLER, False),
    ],
)
def test_timeout_resolver_roles(role: SystemRole, allowed: bool) -> None:
    if allowed:
        LeaveRequest.assert_can_resolve_timeout(role)
    else:
        with pytest.raises(DomainRuleError, match="dual-control"):
            LeaveRequest.assert_can_resolve_timeout(role)


# --------------------------------------------------------------------------- #
# AttendanceRecord — Morning Check-in
# --------------------------------------------------------------------------- #


def make_attendance() -> AttendanceRecord:
    return AttendanceRecord(
        record_id=AttendanceRecordId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        work_date=date(2026, 8, 8),
    )


def test_check_in_flow() -> None:
    record = make_attendance()
    assert record.can_request_leave is False

    record.request_check_in(requested_at=at(8, 5), ntp_verified=True)
    assert record.status is CheckInStatus.PENDING_VERIFICATION
    assert record.can_request_leave is False  # 🟡 halında hələ YOX

    record.collect_events()
    lateness = record.verify(
        operator_id=OPERATOR,
        verified_at=at(8, 5),
        scheduled_start=at(8, 0),
        late_tolerance_minutes=15,
    )

    assert record.status is CheckInStatus.VERIFIED
    assert record.can_request_leave is True
    assert lateness.is_late is False
    assert isinstance(record.collect_events()[0], MorningCheckInVerifiedEvent)


def test_late_check_in_does_not_create_fine() -> None:
    """Bölmə 4: gecikmə "ayrıca cərimə yaratmır", yalnız hesabat üçündür."""
    record = make_attendance()
    record.request_check_in(requested_at=at(8, 40), ntp_verified=True)

    lateness = record.verify(
        operator_id=OPERATOR,
        verified_at=at(8, 40),
        scheduled_start=at(8, 0),
        late_tolerance_minutes=15,
    )

    assert lateness.is_late is True
    assert lateness.late_minutes == 25
    assert lateness.creates_fine is False


def test_double_check_in_blocked() -> None:
    record = make_attendance()
    record.request_check_in(requested_at=at(8, 0), ntp_verified=True)

    with pytest.raises(DomainRuleError, match="gözlənilir"):
        record.request_check_in(requested_at=at(8, 1), ntp_verified=True)


def test_reject_returns_to_not_started_and_allows_retry() -> None:
    """Bölmə 4: rədd → ⚪-ya qayıdır, işçi yenidən cəhd edə bilər."""
    record = make_attendance()
    record.request_check_in(requested_at=at(8, 0), ntp_verified=True)

    record.reject(
        operator_id=OPERATOR,
        reason="Görüntüdə başqa şəxs PIN-dən istifadə edib",
        rejected_at=at(8, 10),
    )

    assert record.status is CheckInStatus.NOT_STARTED
    assert record.rejection_count == 1
    assert record.requested_at is None

    record.request_check_in(requested_at=at(8, 15), ntp_verified=True)
    assert record.status is CheckInStatus.PENDING_VERIFICATION


def test_reject_requires_reason() -> None:
    record = make_attendance()
    record.request_check_in(requested_at=at(8, 0), ntp_verified=True)

    with pytest.raises(DomainRuleError, match="10 simvol"):
        record.reject(operator_id=OPERATOR, reason="yox", rejected_at=at(8, 5))


def test_check_in_timeout_keeps_pending_status() -> None:
    """İşçi növbə ekranından itməməlidir — status 🟡 qalır."""
    record = make_attendance()
    record.request_check_in(requested_at=at(8, 0), ntp_verified=True)
    record.collect_events()

    assert record.escalate_timeout(now=at(8, 44)) is False
    assert record.escalate_timeout(now=at(8, 45)) is True
    assert record.status is CheckInStatus.PENDING_VERIFICATION
    assert record.is_awaiting_operator is True

    event = record.collect_events()[0]
    assert isinstance(event, VerificationTimeoutEscalatedEvent)
    assert event.subject_type == "MORNING_CHECK_IN"


def test_unauthorized_absence_rule() -> None:
    """Bölmə 4: off-day deyil VƏ VERIFIED qeyd yoxdur → İcazəsiz Qayıb."""
    record = make_attendance()

    assert record.mark_unauthorized_absence(is_off_day=True) is False
    assert record.mark_unauthorized_absence(is_off_day=False) is True
    assert record.is_unauthorized_absence is True
    assert isinstance(record.collect_events()[0], UnauthorizedAbsenceDetectedEvent)

    # Təkrar işarələmə hadisə yaratmır
    assert record.mark_unauthorized_absence(is_off_day=False) is False


def test_verified_day_is_never_absence() -> None:
    record = make_attendance()
    record.request_check_in(requested_at=at(8, 0), ntp_verified=True)
    record.verify(operator_id=OPERATOR, verified_at=at(8, 0))

    assert record.mark_unauthorized_absence(is_off_day=False) is False


# --------------------------------------------------------------------------- #
# Position & Employee
# --------------------------------------------------------------------------- #


def test_position_hierarchy() -> None:
    root = make_position(SystemRole.ROOT)
    admin = make_position(SystemRole.ADMIN)
    seller = make_position(SystemRole.SELLER)

    assert root.outranks(admin) is True
    assert admin.outranks(seller) is True
    assert admin.outranks(make_position(SystemRole.ADMIN)) is False  # bərabər pillə


def test_custom_role_cannot_bypass_hardlock() -> None:
    """Custom rol yaradıb qadağanı yan keçmək mümkün olmamalıdır."""
    custom = Position(
        position_id=PositionId(uuid.uuid4()),
        code="ANBAR_NEZARETCISI",
        name_az="Anbar Nəzarətçisi",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
    )
    root_only = PermissionFlag(
        code="can_manage_permissions", category="ICAZE", hardlock=HardlockLevel.ROOT_ONLY
    )

    with pytest.raises(AuthorizationError, match="HARDLOCK"):
        custom.grant(root_only)


def test_camera_flag_only_on_camera_type_position() -> None:
    camera_flag = PermissionFlag(
        code="can_issue_fines",
        category="KAMERA_CERIME",
        is_anti_fraud=True,
        is_camera_only=True,
    )

    make_position(SystemRole.CAMERA_OPERATOR).grant(camera_flag)  # OK

    with pytest.raises(AuthorizationError):
        make_position(SystemRole.STORE_MANAGER).grant(camera_flag)


def test_dual_control_flag_not_on_camera_position() -> None:
    flag = PermissionFlag(
        code=DUAL_CONTROL_APPROVAL_FLAG, category="KAMERA_CERIME", is_anti_fraud=True
    )
    make_position(SystemRole.HR_ADMIN).grant(flag)

    with pytest.raises(AuthorizationError, match="VƏZİFƏ AYRILIĞI"):
        make_position(SystemRole.CAMERA_OPERATOR).grant(flag)


def test_system_position_cannot_be_deactivated() -> None:
    with pytest.raises(DomainRuleError):
        make_position(SystemRole.ROOT).deactivate()


def test_employee_requires_authentication_method() -> None:
    with pytest.raises(DomainRuleError, match="autentifikasiya"):
        Employee(
            employee_id=EmployeeId(uuid.uuid4()),
            tenant_id=TENANT,
            position=make_position(SystemRole.SELLER),
            first_name="A",
            last_name="B",
        )


def test_camera_operator_cannot_use_kiosk_pin() -> None:
    """Bölmə 2: Kamera_Nəzarətçisi sadə PIN-dən istisna edilib."""
    operator = Employee(
        employee_id=OPERATOR,
        tenant_id=TENANT,
        position=make_position(SystemRole.CAMERA_OPERATOR),
        first_name="Rizvan",
        last_name="Operator",
        email=EmailAddress.parse("rizvan@kompas.az"),
        has_password=True,
        has_pin=True,  # DB-də olsa belə
    )

    assert operator.requires_admin_tier_auth is True
    assert operator.can_use_kiosk_pin is False


def test_store_manager_uses_kiosk_pin() -> None:
    """Bölmə 2: menecer də mağazadan çıxıb-qayıdır, PIN axını ona da aiddir."""
    manager = make_employee(SystemRole.STORE_MANAGER)
    assert manager.can_use_kiosk_pin is True
    assert manager.requires_admin_tier_auth is False


def test_pin_lockout_after_five_attempts() -> None:
    employee = make_employee(SystemRole.SELLER)
    now = at(9, 0)

    for _ in range(4):
        assert employee.register_failed_pin_attempt(now=now) is False
    assert employee.register_failed_pin_attempt(now=now) is True

    assert employee.is_pin_locked(now=now + timedelta(minutes=14)) is True
    assert employee.is_pin_locked(now=now + timedelta(minutes=16)) is False


def test_successful_pin_resets_counter() -> None:
    employee = make_employee(SystemRole.SELLER)
    employee.register_failed_pin_attempt(now=at(9, 0))
    employee.register_successful_pin_attempt()
    assert employee.pin_security.failed_attempts == 0


def test_override_beats_role_default() -> None:
    employee = make_employee(SystemRole.HR_ADMIN)
    flag = PermissionFlag(code="can_export_reports", category="SISTEM")
    employee.position.grant(flag)
    now = at(9, 0)

    assert employee.has_permission("can_export_reports", now=now) is True

    employee.apply_override(
        PermissionOverride(
            flag_code="can_export_reports",
            effect=PermissionEffect.DENY,
            granted_by=APPROVER,
        )
    )
    assert employee.has_permission("can_export_reports", now=now) is False


def test_expired_override_falls_back_to_role() -> None:
    employee = make_employee(SystemRole.HR_ADMIN)
    employee.position.grant(PermissionFlag(code="can_export_reports", category="SISTEM"))
    employee.apply_override(
        PermissionOverride(
            flag_code="can_export_reports",
            effect=PermissionEffect.DENY,
            granted_by=APPROVER,
            expires_at=at(10, 0),
        )
    )

    assert employee.has_permission("can_export_reports", now=at(9, 0)) is False
    assert employee.has_permission("can_export_reports", now=at(11, 0)) is True


def test_camera_operator_store_scoping_is_fail_safe() -> None:
    """Bölmə 4: təyinat yoxdursa HEÇ BİR mağaza görünmür."""
    operator = Employee(
        employee_id=OPERATOR,
        tenant_id=TENANT,
        position=make_position(SystemRole.CAMERA_OPERATOR),
        first_name="Rizvan",
        last_name="Operator",
        email=EmailAddress.parse("rizvan2@kompas.az"),
        has_password=True,
    )

    assert operator.can_see_store(STORE) is False  # defolt "heç nə"

    operator.assign_store(STORE)
    assert operator.can_see_store(STORE) is True
    assert operator.can_see_store(OTHER_STORE) is False

    operator.unassign_store(STORE)
    assert operator.can_see_store(STORE) is False


def test_store_assignment_only_for_camera_operator() -> None:
    with pytest.raises(DomainRuleError, match="Kamera Operatoru"):
        make_employee(SystemRole.HR_ADMIN).assign_store(STORE)


# --------------------------------------------------------------------------- #
# Fine
# --------------------------------------------------------------------------- #


def make_manual_fine(*, issued_at: datetime | None = None) -> Fine:
    return Fine(
        fine_id=FineId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        source=FineSource.MANUAL_CAMERA,
        amount=Money.parse("10.00"),
        issued_at=issued_at or at(10, 0),
        fine_type_id=FineTypeId(uuid.uuid4()),
        issued_by=OPERATOR,
        photo_evidence_url="https://storage/evidence.jpg",
    )


def test_manual_fine_requires_photo_evidence() -> None:
    with pytest.raises(DomainRuleError, match="foto"):
        Fine(
            fine_id=FineId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=WORKER,
            store_id=STORE,
            source=FineSource.MANUAL_CAMERA,
            amount=Money.parse("10.00"),
            issued_at=at(10, 0),
            fine_type_id=FineTypeId(uuid.uuid4()),
            issued_by=OPERATOR,
        )


def test_manual_fine_requires_catalog_type() -> None:
    """Anti-fraud: operator sərbəst məbləğ təyin edə bilməz."""
    with pytest.raises(DomainRuleError, match="Cərimə Növü"):
        Fine(
            fine_id=FineId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=WORKER,
            store_id=STORE,
            source=FineSource.MANUAL_CAMERA,
            amount=Money.parse("10.00"),
            issued_at=at(10, 0),
            issued_by=OPERATOR,
            photo_evidence_url="https://storage/x.jpg",
        )


def test_auto_fine_requires_leave_request() -> None:
    with pytest.raises(DomainRuleError, match="icazə sorğusuna"):
        Fine(
            fine_id=FineId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=WORKER,
            store_id=STORE,
            source=FineSource.AUTO_DELAY,
            amount=Money.parse("5.00"),
            issued_at=at(10, 0),
        )


def test_fine_emits_issued_event() -> None:
    fine = make_manual_fine()
    assert isinstance(fine.collect_events()[0], FineIssuedEvent)


def test_appeal_window_is_72_hours() -> None:
    fine = make_manual_fine(issued_at=at(10, 0))
    assert fine.is_appeal_window_open(now=at(10, 0) + timedelta(hours=71)) is True
    assert fine.is_appeal_window_open(now=at(10, 0) + timedelta(hours=73)) is False


def test_export_lock_while_appeal_window_open() -> None:
    """Bölmə 6, HÜQUQİ RİSK: pəncərə açıqdırsa export QADAĞANDIR."""
    fine = make_manual_fine(issued_at=at(10, 0))

    assert fine.is_exportable(now=at(10, 0) + timedelta(hours=1)) is False
    with pytest.raises(DomainRuleError, match="export edilə bilməz"):
        fine.mark_exported(period="2026-08", now=at(10, 0) + timedelta(hours=1))

    later = at(10, 0) + timedelta(hours=73)
    assert fine.is_exportable(now=later) is True
    fine.mark_exported(period="2026-08", now=later)
    assert fine.exported_period == "2026-08"

    # Təkrar export mümkün deyil
    assert fine.is_exportable(now=later) is False


def test_reversed_fine_never_exported() -> None:
    fine = make_manual_fine(issued_at=at(10, 0))
    fine.reverse(
        decided_by=APPROVER,
        decided_at=at(11, 0),
        reason="Etiraz təsdiqləndi, işçi haqlıdır",
    )

    assert fine.status is FineStatus.REVERSED
    assert fine.amount == Money.zero()
    assert fine.original_amount == Money.parse("10.00")  # orijinal SİLİNMİR
    assert fine.is_exportable(now=at(10, 0) + timedelta(hours=73)) is False


def test_fine_can_be_reduced() -> None:
    fine = make_manual_fine()
    fine.reverse(
        decided_by=APPROVER,
        decided_at=at(11, 0),
        reason="Qismən haqlıdır, məbləğ azaldılır",
        new_amount=Money.parse("4.00"),
    )

    assert fine.status is FineStatus.REDUCED
    assert fine.amount == Money.parse("4.00")
    assert fine.original_amount == Money.parse("10.00")
    # Azaldılmış cərimə export oluna BİLƏR (ləğv edilməyib)
    assert fine.is_exportable(now=at(10, 0) + timedelta(hours=73)) is True


def test_reduced_amount_must_be_lower() -> None:
    fine = make_manual_fine()
    with pytest.raises(DomainRuleError, match="kiçik olmalıdır"):
        fine.reverse(
            decided_by=APPROVER,
            decided_at=at(11, 0),
            reason="Səhv azaltma cəhdi edilir",
            new_amount=Money.parse("20.00"),
        )


def test_fine_cannot_be_reversed_twice() -> None:
    fine = make_manual_fine()
    fine.reverse(decided_by=APPROVER, decided_at=at(11, 0), reason="Etiraz təsdiqləndi tam")
    with pytest.raises(DomainRuleError, match="aktiv cərimə"):
        fine.reverse(decided_by=APPROVER, decided_at=at(12, 0), reason="İkinci cəhd edilir")


# --------------------------------------------------------------------------- #
# AggregateRoot hadisə toplama
# --------------------------------------------------------------------------- #


def test_events_are_collected_not_published() -> None:
    """Hadisə DB commit-dən ƏVVƏL yayımlanmamalıdır."""
    leave = open_leave()
    assert leave.has_pending_events is True

    events = leave.collect_events()
    assert len(events) == 1
    assert leave.has_pending_events is False
    assert leave.collect_events() == ()


def test_events_can_be_discarded_on_rollback() -> None:
    leave = open_leave()
    leave.discard_events()
    assert leave.has_pending_events is False
