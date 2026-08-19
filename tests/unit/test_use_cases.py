"""Use case testləri (Faza 2.5) — 3-STEP axını, Saga, NTP, scope, timeout."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.application.use_cases import (
    LeaveVerificationUseCase,
    ModuleDisabledError,
    MorningCheckInUseCase,
    OperationNotPermittedError,
    TimeDriftError,
)
from src.application.use_cases.leave_verification import MonthlyLeaveUsage
from src.domain import events as domain_events
from src.domain.entities import CheckInStatus, FineSource, LeaveStatus
from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
from src.domain.entities.employee import Employee
from src.domain.entities.fine import FineStatus
from src.domain.entities.position import Position
from src.domain.policies import BreakKind, FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    LeaveRequestId,
    LeaveTypeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.shared.saga_orchestrator import CompensationOutcome, SagaOrchestrator, SagaStatus
from tests.fixtures.fakes import (
    FakeCameraAssignments,
    FakeClock,
    FakeFeatureToggles,
    FakeLeaveTypes,
    FakeNtp,
    FakeShifts,
    FakeSystemLimits,
    InMemoryAttendance,
    InMemoryBreakUsage,
    InMemoryEmployees,
    InMemoryFines,
    InMemoryLeaveRequests,
    RecordingAudit,
    RecordingEventBus,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
OPERATOR = EmployeeId(uuid.uuid4())
#: Dual-control ikinci təsdiqçisi (M-5). Kamera rolunda OLA BİLMƏZ (SEC-001),
#: ona görə HR_Admin kimi qurulur — `_with_approver` onu repo-ya yazır.
APPROVER = EmployeeId(uuid.uuid4())
LUNCH = LeaveTypeId(uuid.uuid4())
DAY = date(2026, 8, 8)

#: Kamera əməliyyat flag-ləri (bölmə 3) — `is_camera_only`, yəni yalnız
#: kamera-tipli rollarda ola bilər.
VERIFY_FLAG = PermissionFlag(
    code="can_verify_returns",
    category="KAMERA_CERIME",
    is_anti_fraud=True,
    is_camera_only=True,
)
OVERRIDE_FLAG = PermissionFlag(
    code="can_override_return_time",
    category="KAMERA_CERIME",
    is_anti_fraud=True,
    is_camera_only=True,
)
#: İkinci təsdiq — kamera roluna VERİLMİR (SEC-001), HR_Admin/CEO daşıyır.
DUAL_FLAG = PermissionFlag(
    code="can_approve_dual_control_override",
    category="KAMERA_CERIME",
    is_anti_fraud=True,
    hardlock=HardlockLevel.NONE,
)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 8, hour, minute, tzinfo=UTC)


def make_employee(
    employee_id: EmployeeId,
    role: SystemRole,
    *,
    flags: list[PermissionFlag] | None = None,
    store_id: StoreId | None = STORE,
) -> Employee:
    """Testlərdə istifadə olunan minimal işçi qurucusu."""
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for flag in flags or []:
        position.grant(flag)

    return Employee(
        employee_id=employee_id,
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=store_id,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


class Ctx:
    """Bütün sahtə portları bir yerdə saxlayan test konteksti."""

    def __init__(self) -> None:
        self.clock = FakeClock(at(12, 0))
        self.ntp = FakeNtp(self.clock)
        self.limits = FakeSystemLimits()
        self.toggles = FakeFeatureToggles()
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()
        self.leave_requests = InMemoryLeaveRequests()
        self.fines = InMemoryFines()
        self.employees = InMemoryEmployees()
        # `LUNCH` sabiti burada NAHAR icazə NÖVÜNÜN id-sidir; nişan onu
        # nahar.md-nin sistem fasiləsinə bağlayır ki, STEP1 sayğacı artırsın.
        self.leave_types = FakeLeaveTypes({LUNCH: 60}, {LUNCH: BreakKind.LUNCH})
        self.break_usage = InMemoryBreakUsage()
        self.shifts = FakeShifts()
        self.attendance = InMemoryAttendance()
        self.cameras = FakeCameraAssignments({OPERATOR: [STORE]})
        self.saga = SagaOrchestrator()

        # Bölmə 3: kamera əməliyyatları `can_verify_returns` /
        # `can_override_return_time` TƏLƏB EDİR — operator repo-da mövcud
        # olmalıdır, əks halda use case onu tanımır.
        self.employees.save(
            make_employee(
                OPERATOR,
                SystemRole.CAMERA_OPERATOR,
                flags=[VERIFY_FLAG, OVERRIDE_FLAG],
            )
        )

    def leave_uc(self, *, event_bus: Any = None) -> LeaveVerificationUseCase:
        # `event_bus` OPSİONAL VƏ DEFOLT `None`: mövcud bütün çağırışlar
        # (`ctx.leave_uc()`) heç nə ötürmür və `_publish_events`-in "bus
        # yoxdursa heç nə etmə" qolunu artıq işlədir (bax D2 — [c] halı,
        # `test_event_bus_absence_does_not_change_the_outcome`). Yeni parametr
        # YALNIZ D2 reqressiya testlərinə xidmət edir.
        return LeaveVerificationUseCase(
            leave_requests=self.leave_requests,  # type: ignore[arg-type]
            fines=self.fines,  # type: ignore[arg-type]
            employees=self.employees,  # type: ignore[arg-type]
            leave_types=self.leave_types,  # type: ignore[arg-type]
            camera_assignments=self.cameras,  # type: ignore[arg-type]
            break_usage=self.break_usage,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            ntp=self.ntp,  # type: ignore[arg-type]
            limits=self.limits,  # type: ignore[arg-type]
            toggles=self.toggles,  # type: ignore[arg-type]
            saga=self.saga,
            audit=self.audit,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            event_bus=event_bus,
        )

    def checkin_uc(self) -> MorningCheckInUseCase:
        return MorningCheckInUseCase(
            attendance=self.attendance,  # type: ignore[arg-type]
            shifts=self.shifts,  # type: ignore[arg-type]
            employees=self.employees,  # type: ignore[arg-type]
            camera_assignments=self.cameras,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            ntp=self.ntp,  # type: ignore[arg-type]
            limits=self.limits,  # type: ignore[arg-type]
            toggles=self.toggles,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


def _with_approver(ctx: Ctx) -> EmployeeId:
    """İkinci təsdiqçini repo-ya yazır və id-sini qaytarır (M-5)."""
    ctx.employees.save(make_employee(APPROVER, SystemRole.HR_ADMIN, flags=[DUAL_FLAG]))
    return APPROVER


def open_leave(ctx: Ctx):
    return ctx.leave_uc().request_leave(
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        leave_type_id=LUNCH,
        employee_is_in_store=True,
    )


# --------------------------------------------------------------------------- #
# STEP 1
# --------------------------------------------------------------------------- #


def test_request_leave_uses_leave_type_allowance(ctx: Ctx) -> None:
    """BR-001 defoltu: güzəşt İcazə Növünün müddətindən gəlir."""
    request = open_leave(ctx)

    assert request.allowance_minutes == 60
    assert request.status is LeaveStatus.OUTSIDE
    assert "LEAVE_REQUESTED" in ctx.audit.actions()


def test_allowance_source_none_is_strictest(ctx: Ctx) -> None:
    ctx.limits.set(SystemLimitKey.LEAVE_ALLOWANCE_SOURCE, "NONE")
    assert open_leave(ctx).allowance_minutes == 0


def test_allowance_source_fixed(ctx: Ctx) -> None:
    ctx.limits.set(SystemLimitKey.LEAVE_ALLOWANCE_SOURCE, "FIXED")
    ctx.limits.set(SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES, "20")
    assert open_leave(ctx).allowance_minutes == 20


def test_second_open_leave_blocked(ctx: Ctx) -> None:
    open_leave(ctx)
    with pytest.raises(OperationNotPermittedError, match="açıq icazə"):
        open_leave(ctx)


def test_leave_blocked_when_module_disabled(ctx: Ctx) -> None:
    ctx.toggles.disable(FeatureModule.CAMERA_VERIFICATION.value)
    with pytest.raises(ModuleDisabledError):
        open_leave(ctx)


def test_time_drift_blocks_leave_request(ctx: Ctx) -> None:
    """Bölmə 2: sürüşmə 60 saniyəni keçirsə vaxt-kritik əməliyyat bloklanır."""
    ctx.ntp.verified = False
    ctx.ntp.drift = 95.0

    with pytest.raises(TimeDriftError, match="Saat sürüşməsi"):
        open_leave(ctx)


def test_small_drift_allows_operation(ctx: Ctx) -> None:
    ctx.ntp.verified = False
    ctx.ntp.drift = 12.0

    request = open_leave(ctx)
    assert request.ntp_verified is False  # qeyd olunur, lakin bloklanmır


# --------------------------------------------------------------------------- #
# STEP 2 & 3
# --------------------------------------------------------------------------- #


async def test_full_flow_creates_no_fine_by_default(ctx: Ctx) -> None:
    """BR-002 defoltu: dərəcə 0 → pul cəriməsi YARANMIR, yalnız dəqiqələr."""
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    assert outcome.succeeded is True
    assert outcome.penalty.delay_minutes == 30
    assert outcome.penalty.total_minutes == 120
    assert outcome.fine is None
    assert ctx.fines.items == {}


async def test_fine_created_when_rate_configured(ctx: Ctx) -> None:
    """BR-002: dərəcə təyin ediləndə AUTO_DELAY cəriməsi avtomatik yaranır."""
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    assert outcome.fine is not None
    assert outcome.fine.source is FineSource.AUTO_DELAY
    assert str(outcome.fine.amount) == "15.00 AZN"  # 30 dəq × 0.50
    assert "LEAVE_VERIFIED" in ctx.audit.actions()


async def test_no_fine_when_no_delay(ctx: Ctx) -> None:
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(12, 45))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    assert outcome.penalty.delay_minutes == 0
    assert outcome.fine is None


async def test_saga_compensates_when_fine_save_fails(ctx: Ctx) -> None:
    """SAGA (bölmə 1): cərimə addımı çökərsə status geri qaytarılır və
    əməliyyat `PENDING_RECONCILIATION`-a keçir."""
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request_id = next(iter(ctx.leave_requests.items))
    ctx.fines.save_failure = RuntimeError("DB əlçatmazdır")

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is False
    assert outcome.saga.status is SagaStatus.PENDING_RECONCILIATION
    # Kompensasiya statusu geri qaytardı — yarımçıq "VERIFIED" qalmadı
    assert ctx.leave_requests.items[request_id].status is (LeaveStatus.PENDING_RETURN_VERIFICATION)


async def test_saga_compensation_discards_fine_when_audit_fails(ctx: Ctx) -> None:
    """SAGA (bölmə 1): cərimə ARTIQ YARADILDIQDAN SONRA çökmə.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ MƏHZ `write_audit` ADDIMI
    ──────────────────────────────────────────────────────────────────────────
    `test_saga_compensates_when_fine_save_fails` daha ERKƏN uğursuzluğu
    yoxlayır — cərimə heç yaranmır, yəni `undo_create_fine` boş dövrədən
    ibarətdir və heç nə sübut etmir. Kompensasiyanın həqiqi yolu yalnız
    cərimə yarandıqdan SONRAKI çökmədə açılır. Orada `reverse()` çağırılırdı
    və o, `PUBLISHED` tələb etdiyi üçün HƏR dəfə `DomainRuleError` atırdı:
    kompensasiya uğursuz sayılır, cərimə isə DB-də `PENDING_REVIEW` yetim
    sətir kimi qalırdı və aylıq icmalda nəşr olunub İKİQAT kəsinti verə
    bilərdi.
    """
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request_id = next(iter(ctx.leave_requests.items))
    ctx.audit.failure = RuntimeError("Audit yazısı çökdü")

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is False
    assert outcome.saga.status is SagaStatus.PENDING_RECONCILIATION
    # Kompensasiyanın ÖZÜ çökməməlidir — əvvəl `reverse()` burada partlayırdı.
    assert outcome.saga.compensation_outcome is CompensationOutcome.FULLY_COMPENSATED
    fine_step = next(e for e in outcome.saga.executions if e.step_name == "create_fine")
    assert fine_step.compensated is True
    assert fine_step.compensation_error is None

    # Cərimə SİLİNMİR (bölmə 4), lakin ölü statusa keçir və məbləği sıfırlanır.
    assert len(ctx.fines.items) == 1
    fine = next(iter(ctx.fines.items.values()))
    assert fine.status is FineStatus.REVERSED
    assert fine.amount == Money.zero()
    assert fine.original_amount == Money.parse("15.00")  # orijinal qalır
    # Nəşr olunmadığı üçün etiraz pəncərəsi HEÇ VAXT açılmayıb.
    assert fine.published_at is None
    # Status da geri qaytarılıb — yarımçıq "VERIFIED" qalmadı.
    assert ctx.leave_requests.items[request_id].status is LeaveStatus.PENDING_RETURN_VERIFICATION


# --------------------------------------------------------------------------- #
# D2 — `verify_return()` hadisə yayımı
# --------------------------------------------------------------------------- #
# `qa` çarpaz sorğuda tapdı: mövcud ~15 `verify_return()` çağırışının HEÇ BİRİ
# `LeaveVerifiedEvent`-in Event Bus-a çatıb-çatmadığını yoxlamırdı (yalnız
# `outcome` — status/cərimə). `domain` düzəlişi: `event_bus: EventBus | None`
# opsional parametr, uğur yolunda `request.collect_events()` yayılır.
# Dörd hal AŞAĞIDA — `_publish_events` modul başlığındakı bütün budaqlar.


async def test_a_successful_verification_publishes_the_event(ctx: Ctx) -> None:
    """[a] `event_bus` verilib, saga UĞURLU → `LeaveVerifiedEvent` bus-a çatır.

    STEP1/STEP2 arasında `request.collect_events()` ÇAĞIRILIR: `InMemory
    LeaveRequests` (bu fayldakı digər testlərdən fərqli olaraq BURADA) `save()`
    zamanı obyekti KOPYALAMIR — eyni Python instansı bütün 3 addım boyu
    saxlanılır, yəni `LeaveRequestedEvent`/`LeaveReturnClaimedEvent` DRENAJ
    EDİLMƏSƏ STEP3-ə qədər yığılıb qalır. Real Postgres repo-da hər addım
    aqreqatı SƏTİRDƏN YENİDƏN qurur (`emit_created_event=False`) — yəni
    `verify_return()` yalnız ÖZ addımının hadisəsini görər. Bu sətir məhz
    HƏMİN fərqi kompensasiya edir ki, test yalnız D2-nin predmetini (STEP3-ün
    ÖZ hadisəsi yayılırmı) ölçsün, fakenin obyekt-referans xüsusiyyətini yox.
    """
    bus = RecordingEventBus()
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_requests.items[request_id].collect_events()

    outcome = await ctx.leave_uc(event_bus=bus).verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is True
    assert bus.names() == ["LeaveVerifiedEvent"]
    (event,) = bus.published
    assert isinstance(event, domain_events.LeaveVerifiedEvent)


async def test_a_compensated_verification_does_not_publish(ctx: Ctx) -> None:
    """[b] Saga KOMPENSASİYAYA düşsə hadisə YAYILMIR.

    `undo_update_status` (`leave_verification.py:400`) `request.
    discard_events()` çağırır — `_pending_events` uğursuzluq anında ARTIQ
    boşdur. `verify_return()`-un özündəki `if result.succeeded:` şərti bunu
    İKİNCİ dəfə təmin edir (bax modul şərhi, sətir 517-522).
    """
    bus = RecordingEventBus()
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.fines.save_failure = RuntimeError("DB əlçatmazdır")

    outcome = await ctx.leave_uc(event_bus=bus).verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is False
    assert outcome.saga.status is SagaStatus.PENDING_RECONCILIATION
    assert bus.published == []


async def test_event_bus_absence_does_not_change_the_outcome(ctx: Ctx) -> None:
    """[c] `event_bus=None` (defolt) → istisna atılmır, əməliyyat normal işləyir.

    Bu, `ctx.leave_uc()`-un ARQUMENTSİZ formasıdır — yəni bu faylda ARTIQ
    mövcud olan bütün digər `verify_return()` testləri (məs.
    `test_full_flow_creates_no_fine_by_default`) bu halı örtür. Test AÇIQ
    saxlanılıb ki, "defolt niyə etibarlıdır" sualı bu faylda BİR yerdə,
    D2 bölməsində cavablandırılsın.
    """
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is True


async def test_a_publish_failure_does_not_undo_the_verification(ctx: Ctx) -> None:
    """[d] Bus `publish()` istisna atsa `verify_return()` YENƏ uğurlu qalır.

    `saga_orchestrator._emit()` ilə EYNİ naxış: bu nöqtədə Saga artıq
    `COMPLETED`-dir, status/cərimə/audit DB-yə yazılıb. Yayım nasazlığı
    telemetriya kanalını itirir, əməliyyatı YOX (bax `_publish_events`
    docstring-i, `leave_verification.py:872-878`).
    """
    bus = RecordingEventBus()
    bus.failure = RuntimeError("Event Bus əlçatmazdır")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))

    outcome = await ctx.leave_uc(event_bus=bus).verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is True
    assert outcome.saga.status is SagaStatus.COMPLETED
    assert bus.published == []  # istisna `append`-dən ƏVVƏL atılıb


async def test_compensated_fine_does_not_block_a_new_verification(ctx: Ctx) -> None:
    """Kompensasiyadan sonra TƏKRAR təsdiq bloklanmır.

    `REVERSED` sətir DB-dəki qismən unikal indeksin (miqrasiya 015) əhatəsindən
    QƏSDƏN kənardadır. Əks halda bir dəfə uğursuz olmuş təsdiq işçinin həmin
    icazəsini əbədi "təsdiqlənə bilməz" vəziyyətdə saxlayardı.
    """
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))

    ctx.audit.failure = RuntimeError("Audit yazısı çökdü")
    await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    ctx.audit.failure = None
    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.succeeded is True
    assert outcome.fine is not None
    assert outcome.fine.status is FineStatus.PENDING_REVIEW
    # Ölü sətir + yeni diri sətir = 2 qeyd, lakin diri olan YALNIZ BİRDİR.
    live = [f for f in ctx.fines.items.values() if f.status is not FineStatus.REVERSED]
    assert len(live) == 1


async def test_second_verification_creates_no_second_fine(ctx: Ctx) -> None:
    """Paralel/təkrar `[Təsdiqlə]` — İKİNCİ cərimə YARANMIR.

    Yarışın birinci qatı domendədir (`_require_verifiable`), ikinci qatı isə
    DB-dəki qismən unikal indeksdir. Bu test birinci qatı sübut edir: təkrar
    çağırış ilk ADDIMDA dayanır, yəni cərimə addımına ÇATMIR.

    İstisna çağırana qalxmır, çünki Saga onu tutur (`execute` heç vaxt istisna
    atmır — bax `SagaOrchestrator.execute` docstring); nəticə `SagaResult`
    üzərindən oxunur.
    """
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))

    first = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )
    assert first.succeeded is True
    assert len(ctx.fines.items) == 1

    second = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert second.succeeded is False
    assert second.saga.failed_step == "update_status", "yarış cərimə addımına çatmamalıdır"
    assert isinstance(second.saga.error, InvalidStateTransitionError)
    assert second.fine is None

    # İKİNCİ YAZI YOXDUR və birinci cərimə toxunulmaz qalıb.
    assert len(ctx.fines.items) == 1
    assert next(iter(ctx.fines.items.values())).status is FineStatus.PENDING_REVIEW
    assert ctx.leave_requests.items[request_id].status is LeaveStatus.VERIFIED


async def test_verify_return_reads_the_row_under_lock(ctx: Ctx) -> None:
    """Yazma axını KİLİDLİ oxudan keçir (oxu-yalnız yol toxunulmazdır).

    D-R2-02 (dövrə 2) düzəlişindən SONRA STEP 2 (`claim_return`) DƏ kilidli
    oxudur — əvvəllər YALNIZ STEP 3 (`verify_return`) kilidli idi, halbuki
    STEP 2-nin kilidsiz `find_open_for_employee`-si ikiqat toxunma/şəbəkə
    təkrarında `LEAVE_RETURN_CLAIMED`-i ikiqat yaza, `return_claimed_time`-ı
    (gecikmə/cərimə hesabına birbaşa daxil olan sahə) qeyri-deterministik
    qoya bilirdi (bax `_require_open_request_locked`-in öz şərhi).
    """
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))

    assert ctx.leave_requests.locked_reads == [request_id]  # STEP 2 kilidli oxudur

    await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert ctx.leave_requests.locked_reads == [request_id, request_id]  # STEP 2 + STEP 3


def test_double_claim_return_is_rejected_on_the_second_locked_read(ctx: Ctx) -> None:
    """D-R2-02: ikiqat toxunma/şəbəkə təkrarını modelləşdirir.

    Sahtə repo həqiqi `FOR UPDATE` kilidini simulyasiya edə bilmir (tək
    saplıdır — bax `InMemoryLeaveRequests.get_for_update`-in öz şərhi),
    AMMA əsl DB-də ikinci tranzaksiya BİRİNCİNİN commit-indən SONRA eyni
    sətri oxuyacaq — yəni artıq `PENDING_RETURN_VERIFICATION` görəcək.
    Bu test məhz o SIRALI nəticəni yoxlayır: ikinci `claim_return()`
    entity-səviyyəli `_require_status(OUTSIDE)` qoruğuna çırpılmalıdır,
    həm də HƏR İKİ çağırış kilidli oxudan keçməlidir (əks halda qoruma
    yalnız TƏSADÜFƏN işləyər, strukturca deyil).
    """
    open_leave(ctx)
    ctx.clock.set(at(13, 0))

    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    assert ctx.leave_requests.items[request_id].status is LeaveStatus.PENDING_RETURN_VERIFICATION

    with pytest.raises(InvalidStateTransitionError, match="OUTSIDE"):
        ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    # HƏR İKİ cəhd kilidli oxu ilə keçib — ikincinin rədd edilməsi TƏSADÜFİ
    # sıralamanın deyil, hər çağırışın eyni kilidli yoldan keçməsinin nəticəsidir.
    assert ctx.leave_requests.locked_reads == [request_id, request_id]


async def test_operator_outside_scope_blocked(ctx: Ctx) -> None:
    """FAIL-SAFE (bölmə 4): operator öz mağazası olmayan sorğunu təsdiqləyə bilməz."""
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    # Səlahiyyəti VAR, amma başqa mağazaya təyin edilib — bloklayan məhz
    # mağaza scope-udur, flag deyil.
    stranger = EmployeeId(uuid.uuid4())
    ctx.employees.save(make_employee(stranger, SystemRole.CAMERA_OPERATOR, flags=[VERIFY_FLAG]))
    ctx.cameras.mapping[stranger] = [OTHER_STORE]

    with pytest.raises(OperationNotPermittedError, match="təyin edilməyib"):
        await ctx.leave_uc().verify_return(
            tenant_id=TENANT,
            operator_id=stranger,
            request_id=next(iter(ctx.leave_requests.items)),
        )


# --------------------------- manual override -------------------------------- #


def test_override_below_threshold_no_dual_control(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request = ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
        overridden_time=at(12, 50),
        reason="Kameradan təsdiqləndi, işçi 12:50-də qayıtdı",
    )

    assert request.override is not None
    assert request.override.requires_dual_control is False
    assert "DUAL_CONTROL_PENDING" not in ctx.notifier.categories()


def test_override_above_threshold_triggers_notification(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request = ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
        overridden_time=at(12, 20),
        reason="Kameradan təsdiqləndi, işçi 12:20-də qayıtdı",
    )

    assert request.override is not None
    assert request.override.requires_dual_control is True
    assert "DUAL_CONTROL_PENDING" in ctx.notifier.categories()
    assert "MANUAL_TIME_OVERRIDE" in ctx.audit.actions()


def test_dual_control_toggle_off_skips_second_approval(ctx: Ctx) -> None:
    """RETROAKTİV TƏSİR: modul söndürüləndə YENİ override-lar təsdiq tələb etmir."""
    ctx.toggles.disable(FeatureModule.DUAL_CONTROL.value)
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    request = ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
        overridden_time=at(12, 10),  # 50 dəqiqəlik fərq
        reason="Kameradan təsdiqləndi, işçi 12:10-da qayıtdı",
    )

    assert request.override is not None
    assert request.override.requires_dual_control is False


def test_dual_control_approval_requires_flag(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(12, 20),
        reason="Kameradan təsdiqləndi, işçi 12:20-də qayıtdı",
    )

    unknown = EmployeeId(uuid.uuid4())
    with pytest.raises(OperationNotPermittedError, match="dual-control"):
        ctx.leave_uc().approve_dual_control(
            tenant_id=TENANT, approver_id=unknown, request_id=request_id
        )


# --------------------------------------------------------------------------- #
# M-3 — gecikmə OPERATORUN saatından hesablanmır
# --------------------------------------------------------------------------- #


async def test_late_operator_click_does_not_fine_the_employee(ctx: Ctx) -> None:
    """İşçi vaxtında qayıdıb, operator 40 dəqiqə sonra baxıb → cərimə YOXDUR.

    Bu, M-3-ün bütün mahiyyətidir: `DELAY_FINE_RATE_PER_MINUTE` təyin
    edilibsə, əvvəlki davranış işçiyə 40 dəqiqəlik REAL PUL cəriməsi yazırdı
    — halbuki gecikmə tamamilə kamera növbəsinin yükündən doğmuşdu.
    """
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)  # 12:00, 60 dəqiqəlik nahar
    ctx.clock.set(at(13, 0))  # işçi TAM vaxtında qayıdıb PIN vurur
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    ctx.clock.set(at(13, 40))  # operator yalnız indi ekrana baxır
    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    assert outcome.succeeded is True
    assert outcome.penalty.delay_minutes == 0
    assert outcome.fine is None, "operatorun gecikməsi cəriməyə çevrilməməlidir"
    assert outcome.leave_request.verified_at == at(13, 40)  # möhür saxlanılır
    assert outcome.leave_request.actual_return_time == at(13, 0)


async def test_the_audit_entry_names_the_time_source(ctx: Ctx) -> None:
    """«Niyə bu qədər gecikmə yazıldı?» sualı audit sətrindən cavablanmalıdır."""
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    await ctx.leave_uc().verify_return(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=next(iter(ctx.leave_requests.items)),
    )

    entry = next(e for e in ctx.audit.entries if e["action"] == "LEAVE_VERIFIED")
    assert entry["after_state"]["return_time_source"] == "EMPLOYEE_CLAIM"
    assert entry["after_state"]["actual_return_time"] == at(13, 30).isoformat()


async def test_explicit_return_time_requires_the_override_flag(ctx: Ctx) -> None:
    """Vaxtı arqumentlə ötürmək DƏ manual düzəlişdir (M-5).

    Yalnız `can_verify_returns` daşıyan operator bu yolla dual-control
    qaydasını yan keçə bilməməlidir.
    """
    open_leave(ctx)
    ctx.clock.set(at(13, 30))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    verifier = EmployeeId(uuid.uuid4())
    ctx.employees.save(make_employee(verifier, SystemRole.CAMERA_OPERATOR, flags=[VERIFY_FLAG]))
    ctx.cameras.mapping[verifier] = [STORE]

    with pytest.raises(OperationNotPermittedError, match="can_override_return_time"):
        await ctx.leave_uc().verify_return(
            tenant_id=TENANT,
            operator_id=verifier,
            request_id=next(iter(ctx.leave_requests.items)),
            actual_return_time=at(12, 30),
        )


# --------------------------------------------------------------------------- #
# M-5 — gözləyən / rədd edilən / müddəti bitən vaxt düzəlişi
# --------------------------------------------------------------------------- #


async def test_auto_approved_override_time_reaches_the_penalty(ctx: Ctx) -> None:
    """30 dəqiqədən az düzəliş ikinci təsdiq istəmir və DƏRHAL qüvvəyə minir.

    Əvvəl `apply_override` yalnız qeyd yazırdı: `verify_return` düzəlişə HEÇ
    BAXMIRDI, yəni `[Vaxtı Əllə Təyin Et]` düyməsi cəriməyə təsir etmirdi.
    """
    ctx.limits.set(SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE, "0.50")
    open_leave(ctx)
    ctx.clock.set(at(13, 20))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))

    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),  # 20 dəqiqəlik fərq → dual-control YOX
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )
    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    assert outcome.leave_request.actual_return_time == at(13, 0)
    assert outcome.penalty.delay_minutes == 0
    assert outcome.fine is None


async def test_pending_override_does_not_change_the_penalty(ctx: Ctx) -> None:
    """M-5, sual 1: gözləmə vəziyyətində ORİJİNAL vaxt keçərlidir (fail-closed)."""
    open_leave(ctx)
    ctx.clock.set(at(13, 40))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))

    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),  # 40 dəqiqəlik fərq → ikinci təsdiq lazımdır
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )
    request = ctx.leave_requests.items[request_id]
    assert request.override is not None
    assert request.override.is_pending_approval is True
    assert request.override.is_effective is False

    outcome = await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    # Təsdiqlənməmiş düzəliş TƏSİR ETMİR — baza işçinin öz möhürüdür.
    assert outcome.leave_request.actual_return_time == at(13, 40)
    assert outcome.penalty.delay_minutes == 40


def test_approved_override_is_effective_only_after_the_second_approval(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 40))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )

    request = ctx.leave_uc().approve_dual_control(
        tenant_id=TENANT, approver_id=_with_approver(ctx), request_id=request_id
    )

    assert request.override is not None
    assert request.override.is_effective is True
    assert request.resolved_return_time(fallback=at(13, 40)) == at(13, 0)


def test_dual_control_can_be_rejected_with_a_mandatory_reason(ctx: Ctx) -> None:
    """M-5, sual 2: təsdiqçi «yox» da deyə bilər — və səbəb məcburidir."""
    open_leave(ctx)
    ctx.clock.set(at(13, 40))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )

    with pytest.raises(DomainRuleError, match="10 simvol"):
        ctx.leave_uc().reject_dual_control(
            tenant_id=TENANT, approver_id=_with_approver(ctx), request_id=request_id, reason="yox"
        )

    request = ctx.leave_uc().reject_dual_control(
        tenant_id=TENANT,
        approver_id=APPROVER,  # `_with_approver` yuxarıda çağırılıb
        request_id=request_id,
        reason="Görüntüdə 13:00 deyil, 13:40 görünür — düzəliş əsassızdır",
    )

    assert request.override is not None
    assert request.override.is_rejected is True
    assert request.override.is_effective is False
    # Orijinal vaxt qüvvədə qalır.
    assert request.resolved_return_time(fallback=at(13, 40)) == at(13, 40)
    assert "DUAL_CONTROL_REJECTED" in ctx.audit.actions()
    # Sorğunu yazan operator cavabı BİLMƏLİDİR.
    closed = next(m for m in ctx.notifier.messages if m["category"] == "DUAL_CONTROL_CLOSED")
    assert closed["recipient_id"] == OPERATOR


def test_rejecting_requires_the_dual_control_flag(ctx: Ctx) -> None:
    """Rədd təsdiqlə EYNİ qapıdan keçir — «yalnız hə deyə bilən» təsdiqçi olmaz."""
    open_leave(ctx)
    ctx.clock.set(at(13, 40))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )

    with pytest.raises(OperationNotPermittedError, match="dual-control"):
        ctx.leave_uc().reject_dual_control(
            tenant_id=TENANT,
            approver_id=EmployeeId(uuid.uuid4()),
            request_id=request_id,
            reason="Səlahiyyətim olmasa da rədd etmək istəyirəm",
        )


def test_pending_override_expires_instead_of_being_auto_approved(ctx: Ctx) -> None:
    """M-5, sual 3: müddət dolanda sorğu LƏĞV olunur, avtomatik TƏSDİQLƏNMİR."""
    open_leave(ctx)
    ctx.clock.set(at(13, 40))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )

    ctx.limits.set(SystemLimitKey.DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES, "60")
    ctx.clock.set(at(14, 41))  # 61 dəqiqə sonra
    expired = ctx.leave_uc().expire_pending_overrides(TENANT)

    assert expired == 1
    request = ctx.leave_requests.items[request_id]
    assert request.override is not None
    assert request.override.is_rejected is True
    assert request.override.approved_by is None, "timeout TƏSDİQ deyil"
    assert request.resolved_return_time(fallback=at(13, 40)) == at(13, 40)
    assert "DUAL_CONTROL_EXPIRED" in ctx.audit.actions()
    assert "DUAL_CONTROL_CLOSED" in ctx.notifier.categories()
    # Təkrar icra ikinci ləğv/bildiriş yaratmır.
    assert ctx.leave_uc().expire_pending_overrides(TENANT) == 0


def test_expired_override_cannot_be_approved_afterwards(ctx: Ctx) -> None:
    """Müddəti bitmiş sorğu təsdiq düyməsi ilə dirildilə bilməz."""
    open_leave(ctx)
    ctx.clock.set(at(13, 40))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )

    ctx.limits.set(SystemLimitKey.DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES, "60")
    ctx.clock.set(at(14, 41))

    with pytest.raises(InvalidStateTransitionError, match="müddəti bitmiş"):
        ctx.leave_uc().approve_dual_control(
            tenant_id=TENANT, approver_id=_with_approver(ctx), request_id=request_id
        )


async def test_approval_after_verification_is_refused(ctx: Ctx) -> None:
    """Təsdiq edilmiş icazəyə sonradan gələn təsdiq SÜKUTLA qəbul edilmir.

    Cərimə artıq yazılıb; geriyə dönük düzəliş yolu spesifikasiyada BAŞQADIR
    (72 saatlıq etiraz), ona görə bu keçid açıq istisna ilə rədd edilir.
    """
    open_leave(ctx)
    ctx.clock.set(at(13, 40))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)
    request_id = next(iter(ctx.leave_requests.items))
    ctx.leave_uc().apply_override(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        request_id=request_id,
        overridden_time=at(13, 0),
        reason="Kamera görüntüsündə işçi 13:00-da içəri girir",
    )
    await ctx.leave_uc().verify_return(
        tenant_id=TENANT, operator_id=OPERATOR, request_id=request_id
    )

    with pytest.raises(InvalidStateTransitionError, match="artıq təsdiqlənib"):
        ctx.leave_uc().approve_dual_control(
            tenant_id=TENANT, approver_id=_with_approver(ctx), request_id=request_id
        )


# ------------------------------- timeout ------------------------------------ #


def test_leave_timeout_escalation(ctx: Ctx) -> None:
    open_leave(ctx)
    ctx.clock.set(at(13, 0))
    ctx.leave_uc().claim_return(tenant_id=TENANT, employee_id=WORKER)

    ctx.clock.set(at(13, 46))
    count = ctx.leave_uc().escalate_timeouts(TENANT)

    assert count == 1
    assert "VERIFICATION_TIMEOUT" in ctx.notifier.categories()
    # Təkrar çağırış yeni bildiriş yaratmır
    assert ctx.leave_uc().escalate_timeouts(TENANT) == 0


# --------------------------------------------------------------------------- #
# Morning Check-in
# --------------------------------------------------------------------------- #


def test_check_in_flow(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 5))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    assert uc.employee_can_request_leave(WORKER, DAY) is False

    ctx.shifts.starts[(WORKER, DAY)] = at(8, 0)
    outcome = uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    assert outcome.record.status is CheckInStatus.VERIFIED
    assert outcome.lateness is not None
    assert outcome.lateness.is_late is False  # 15 dəq tolerantlıq
    assert uc.employee_can_request_leave(WORKER, DAY) is True


def test_check_in_late_beyond_tolerance(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 40))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    ctx.shifts.starts[(WORKER, DAY)] = at(8, 0)

    outcome = uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    assert outcome.lateness is not None
    assert outcome.lateness.is_late is True
    assert outcome.lateness.late_minutes == 25
    assert outcome.lateness.creates_fine is False  # gecikmə cərimə yaratmır


def test_check_in_reject_notifies_hr(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    outcome = uc.reject(
        tenant_id=TENANT,
        operator_id=OPERATOR,
        employee_id=WORKER,
        reason="Görüntüdə başqa şəxs PIN-dən istifadə edib",
        work_date=DAY,
    )

    assert outcome.was_rejected is True
    assert outcome.record.status is CheckInStatus.NOT_STARTED
    assert "CHECK_IN_REJECTED" in ctx.notifier.categories()


def test_check_in_decision_reads_the_row_under_lock(ctx: Ctx) -> None:
    """STEP C yazma axını kilidli oxudan keçir, oxu-yalnız yol isə YOX."""
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    # `employee_can_request_leave` və növbə siyahısı kilid tələb etmir.
    uc.employee_can_request_leave(WORKER, DAY)
    uc.pending_queue(OPERATOR)
    assert ctx.attendance.locked_reads == []

    uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    assert ctx.attendance.locked_reads == [(WORKER, DAY)]


def test_second_check_in_decision_is_blocked_before_audit(ctx: Ctx) -> None:
    """Paralel təsdiq/rədd — İKİNCİ qərar audit-ə DÜŞMÜR.

    Yarış qapağı olmasaydı hər iki operator `PENDING_VERIFICATION` görər,
    hər ikisi audit yazar və DB-də yalnız sonuncu status qalardı — yəni
    jurnal ilə faktiki vəziyyət bir-birini təkzib edərdi. Test məhz bunu
    yoxlayır: ikinci qərar istisna atır və YENİ audit sətri yaranmır.
    """
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    audit_count = len(ctx.audit.entries)

    with pytest.raises(OperationNotPermittedError, match="PENDING_VERIFICATION"):
        uc.reject(
            tenant_id=TENANT,
            operator_id=OPERATOR,
            employee_id=WORKER,
            reason="İkinci operator eyni anda rədd etməyə çalışır",
            work_date=DAY,
        )

    assert len(ctx.audit.entries) == audit_count
    assert ctx.attendance.items[next(iter(ctx.attendance.items))].status is CheckInStatus.VERIFIED
    assert "CHECK_IN_REJECTED" not in ctx.notifier.categories()


def test_pending_queue_is_fail_safe_without_assignment(ctx: Ctx) -> None:
    """Bölmə 4: təyinatsız operator HEÇ NƏ görmür."""
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    assert uc.pending_queue(EmployeeId(uuid.uuid4())) == []
    assert len(uc.pending_queue(OPERATOR)) == 1


def test_pending_queue_excludes_other_stores(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    other_worker = EmployeeId(uuid.uuid4())
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    uc.start_day(tenant_id=TENANT, employee_id=other_worker, store_id=OTHER_STORE, work_date=DAY)

    queue = uc.pending_queue(OPERATOR)
    assert len(queue) == 1
    assert queue[0].employee_id == WORKER


def test_check_in_timeout_escalation(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    ctx.clock.set(at(8, 46))
    assert uc.escalate_timeouts(TENANT, OPERATOR) == 1
    assert "CHECK_IN_TIMEOUT" in ctx.notifier.categories()
    assert uc.escalate_timeouts(TENANT, OPERATOR) == 0


def test_absence_detection(ctx: Ctx) -> None:
    """Bölmə 4: off-day deyil VƏ VERIFIED yoxdur → İcazəsiz Qayıb."""
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)

    assert uc.detect_absences(TENANT, DAY) == 1
    assert "UNAUTHORIZED_ABSENCE_DETECTED" in ctx.audit.actions()
    assert uc.detect_absences(TENANT, DAY) == 0  # təkrar işarələmə yoxdur


def test_off_day_is_not_absence(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    ctx.shifts.off_days.add((WORKER, DAY))

    assert uc.detect_absences(TENANT, DAY) == 0


def test_verified_day_is_not_absence(ctx: Ctx) -> None:
    ctx.clock.set(at(8, 0))
    uc = ctx.checkin_uc()
    uc.start_day(tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY)
    uc.verify(tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY)

    assert uc.detect_absences(TENANT, DAY) == 0


def test_check_in_time_drift_blocked(ctx: Ctx) -> None:
    ctx.ntp.verified = False
    ctx.ntp.drift = 120.0

    with pytest.raises(TimeDriftError):
        ctx.checkin_uc().start_day(
            tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY
        )


def test_verify_requires_pending_record(ctx: Ctx) -> None:
    with pytest.raises(OperationNotPermittedError, match="davamiyyət qeydi yoxdur"):
        ctx.checkin_uc().verify(
            tenant_id=TENANT, operator_id=OPERATOR, employee_id=WORKER, work_date=DAY
        )


def test_ntp_drift_limit_is_configurable(ctx: Ctx) -> None:
    """Sürüşmə həddi `system_limits`-dən oxunur (bölmə 3)."""
    ctx.limits.set(SystemLimitKey.NTP_MAX_DRIFT_SECONDS, "300")
    ctx.ntp.verified = False
    ctx.ntp.drift = 120.0

    record = ctx.checkin_uc().start_day(
        tenant_id=TENANT, employee_id=WORKER, store_id=STORE, work_date=DAY
    )
    assert record.status is CheckInStatus.PENDING_VERIFICATION


def test_clock_advance_helper() -> None:
    clock = FakeClock(at(9, 0))
    clock.advance(minutes=30)
    assert clock.now() == at(9, 30)
    assert timedelta(minutes=30) == at(9, 30) - at(9, 0)


# --------------------------------------------------------------------------- #
# Aylıq icazə limiti — ROOT Control Center parametri (bölmə 3, bənd 1)
# --------------------------------------------------------------------------- #


def _verified_minutes(ctx: Ctx, minutes: int) -> None:
    """Cari ayda TƏSDİQLƏNMİŞ icazə kimi sayılan süni istifadə yaradır.

    Sorğu use case-dən KEÇMİR: STEP 1→3 axını qurmaq bu testin mövzusu deyil
    və eyni anda yalnız bir açıq icazə qaydası ilə toqquşardı. Repo-ya birbaşa
    yazmaq aqreqasiyanın girişini dəqiq idarə etməyə imkan verir.
    """
    from src.domain.entities.leave_request import LeaveRequest, LeaveStatus
    from src.domain.value_objects.penalty import LeavePenalty

    request = LeaveRequest(
        request_id=LeaveRequestId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE,
        requested_time=ctx.clock.now(),
        status=LeaveStatus.VERIFIED,
    )
    request.penalty = LeavePenalty(
        elapsed_minutes=minutes,
        allowance_minutes=0,
        delay_minutes=0,
        total_minutes=minutes,
    )
    ctx.leave_requests.items[request.id] = request


def test_monthly_usage_reads_the_limit_from_system_limits(ctx: Ctx) -> None:
    """Limit KODDA deyil, `system_limits`-dədir — Root onu dəyişə bilir."""
    usage = ctx.leave_uc().monthly_usage(tenant_id=TENANT, employee_id=WORKER, at=ctx.clock.now())
    assert usage.limit_minutes == 240, "Defolt `DEFAULT_LIMITS`-dən gəlməlidir"

    ctx.limits.set(SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT, "90")
    changed = ctx.leave_uc().monthly_usage(tenant_id=TENANT, employee_id=WORKER, at=ctx.clock.now())
    assert changed.limit_minutes == 90, "Root-un yazdığı dəyər dərhal qüvvəyə minməlidir"


def test_monthly_usage_counts_only_verified_requests(ctx: Ctx) -> None:
    """Açıq (təsdiqlənməmiş) sorğu büdcəni yeməməlidir."""
    open_leave(ctx)
    assert (
        ctx.leave_uc()
        .monthly_usage(tenant_id=TENANT, employee_id=WORKER, at=ctx.clock.now())
        .used_minutes
        == 0
    )


def test_exceeding_the_monthly_limit_warns_but_never_blocks(ctx: Ctx) -> None:
    """Bölmə 3 limiti sadalayır, lakin AŞILDIQDA QADAĞA təyin etmir.

    Ona görə sorğu qəbul olunur; aşılma audit-ə və bildirişə düşür. Bloklamaq
    spesifikasiyada olmayan qadağa yaratmaq, susmaq isə Root-un dəyişdirdiyi
    limiti mənasız etmək olardı (bax `MonthlyLeaveUsage` docstring).
    """
    ctx.limits.set(SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT, "30")
    _verified_minutes(ctx, 100)

    request = open_leave(ctx)

    assert request is not None, "Limit aşılsa da STEP 1 bloklanmır"
    assert "MONTHLY_LEAVE_LIMIT_EXCEEDED" in ctx.notifier.categories()
    last = [e for e in ctx.audit.entries if e["action"] == "LEAVE_REQUESTED"][-1]
    assert last["after_state"]["monthly_limit_minutes"] == 30
    assert last["after_state"]["monthly_used_minutes"] == 100


def test_zero_limit_disables_the_warning(ctx: Ctx) -> None:
    """0 = "limit qoyulmayıb" — hər sorğuda yalançı xəbərdarlıq olmamalıdır."""
    ctx.limits.set(SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT, "0")
    _verified_minutes(ctx, 100)

    open_leave(ctx)
    assert "MONTHLY_LEAVE_LIMIT_EXCEEDED" not in ctx.notifier.categories()


def test_monthly_limit_is_exceeded_only_strictly_above_240() -> None:
    """TAM SƏRHƏD: 240 dəqiqə limitin İÇİNDƏDİR, 241 isə aşılmadır.

    ──────────────────────────────────────────────────────────────────────────
    OPERATOR SEÇİMİ VƏ ONUN ƏSASI
    ──────────────────────────────────────────────────────────────────────────
    `MonthlyLeaveUsage.is_exceeded` `used > limit` yazır, yəni `>` (`>=` YOX).
    Spesifikasiya bölmə 3 bunu *"Aylıq İcazə Müddəti Limiti (defolt 240 dəq.)"*
    kimi verir — 240 icazə verilən MAKSİMUMdur, qadağan olunan ilk dəyər deyil.
    `>=` seçilsəydi, büdcəsini DƏQİQ işlətmiş işçi "limiti aşıb" kimi HR-a
    bildirilərdi; bu, xəbərdarlığın etibarını itirər və hər ay onlarla yalançı
    siqnal yaradardı.

    Sərhəd `remaining_minutes` ilə də uzlaşmalıdır: tam 240-da qalıq 0-dır,
    lakin bu "aşılma" DEYİL.
    """
    exactly_at_limit = MonthlyLeaveUsage(used_minutes=240, limit_minutes=240)
    one_over = MonthlyLeaveUsage(used_minutes=241, limit_minutes=240)
    one_under = MonthlyLeaveUsage(used_minutes=239, limit_minutes=240)

    assert one_under.is_exceeded is False
    assert exactly_at_limit.is_exceeded is False, "240 dəq. limitin İÇİNDƏDİR"
    assert one_over.is_exceeded is True

    assert one_under.remaining_minutes == 1
    assert exactly_at_limit.remaining_minutes == 0
    # Aşılmada qalıq MƏNFİ olmur — sıfırda kəsilir.
    assert one_over.remaining_minutes == 0


def test_monthly_limit_boundary_reaches_the_notification(ctx: Ctx) -> None:
    """Sərhəd qərarı use case axınında da eyni tərəfə düşür.

    `MonthlyLeaveUsage` təkbaşına doğru olsa da, bildiriş şərti ayrıca yerdə
    (`request_leave`) yazılıb. Bu test ikisinin bir-birindən sürüşmədiyini
    təsbit edir: TAM limitdə bildiriş YOXDUR, bir dəqiqə sonra VAR.
    """
    ctx.limits.set(SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT, "240")
    _verified_minutes(ctx, 240)

    open_leave(ctx)
    assert "MONTHLY_LEAVE_LIMIT_EXCEEDED" not in ctx.notifier.categories()

    # Açıq sorğu bağlanır (ikinci STEP 1 üçün şərt), sonra cəm 241-ə çatır.
    for request in ctx.leave_requests.items.values():
        if request.status.is_open:
            request.status = LeaveStatus.CANCELLED
    _verified_minutes(ctx, 1)

    open_leave(ctx)
    assert "MONTHLY_LEAVE_LIMIT_EXCEEDED" in ctx.notifier.categories()
