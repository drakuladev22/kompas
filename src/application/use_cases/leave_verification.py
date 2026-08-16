"""3-STEP LEAVE VERIFICATION use case-i (spesifikasiya bölmə 1, 4) — Faza 2.5.

SAGA QAYDASI (bölmə 1): STEP 3 çox-aqreqatlı əməliyyatdır —
`leave status` + `fine hesablama` + `audit log`. Zəncirin hər hansı addımı
uğursuz olarsa kompensasiya işə düşür və əməliyyat `PENDING_RECONCILIATION`
statusuna keçir (`saga_policies` reyestrində `LeaveVerification` audit-kritik
kimi qeydiyyatdadır).

NTP QAYDASI (bölmə 2): saat sürüşməsi 60 saniyəni keçirsə, PIN handshake və
override kimi vaxt-kritik əməliyyatlar BLOKLANIR.

──────────────────────────────────────────────────────────────────────────────
GECİKMƏ KİMİN SAATINDAN HESABLANIR (M-3)
──────────────────────────────────────────────────────────────────────────────
`verify_return()` `actual_return_time` almadıqda gecikmə ARTIQ operatorun
klik anına görə hesablanmır — zəncir `LeaveRequest.resolved_return_time()`-dədir
(qüvvədə olan düzəliş → işçinin STEP 2 möhürü → klik anı). Səbəb və rədd
edilən alternativ `entities/leave_request.py` başlığındadır.

──────────────────────────────────────────────────────────────────────────────
`actual_return_time` ARQUMENTİ NİYƏ FLAG TƏLƏB EDİR (M-5)
──────────────────────────────────────────────────────────────────────────────
Bu parametr vaxtı ƏLLƏ təyin etməyin İKİNCİ yolu idi — və birincidən
(`apply_override`) fərqli olaraq nə səbəb, nə dual-control, nə də ayrıca
audit sətri tələb edirdi. Yəni 30+ dəqiqəlik düzəlişin ikinci təsdiq qaydası
bir arqumentlə yan keçilə bilərdi (GUI bunu etmirdi, lakin skript və plugin
edə bilərdi).

İndi parametr `can_override_return_time` tələb edir və auditdə açıq görünür.
Kamera operatorunun ekrandan etdiyi düzəliş isə YENƏ `apply_override`-dan
keçir — bu arqument insan yazısı üçün deyil, təsdiqlənmiş xarici siqnal
(kiosk/kamera qeydi) üçün nəzərdə tutulub.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.entities.leave_request import LeaveRequest, LeaveStatus
from src.domain.interfaces.ports import (
    AuditTrail,
    CameraAssignmentRepository,
    Clock,
    DailyBreakUsageRepository,
    EmployeeRepository,
    FeatureToggles,
    FineRepository,
    LeaveRequestRepository,
    LeaveTypeRepository,
    Notifier,
    NtpVerifier,
    RowLockingLeaveRequests,
    SystemLimits,
)
from src.domain.policies import (
    DEFAULT_LIMITS,
    BreakAllowance,
    BreakKind,
    DelayFinePolicy,
    FeatureModule,
    LeaveAllowancePolicy,
    SystemLimitKey,
)
from src.domain.value_objects.authorization import DUAL_CONTROL_APPROVAL_FLAG
from src.domain.value_objects.identifiers import (
    EmployeeId,
    LeaveRequestId,
    LeaveTypeId,
    StoreId,
    TenantId,
    new_fine_id,
    new_leave_request_id,
)
from src.domain.value_objects.penalty import LeavePenalty
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.saga_orchestrator import SagaOrchestrator, SagaResult, SagaStep

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)


class TimeDriftError(KompasOSError):
    """`TIME_DRIFT_DETECTED` — vaxt-kritik əməliyyat bloklandı (bölmə 2)."""

    user_message = (
        "Kompüterin saatı serverlə uyğun deyil. Əməliyyat müvəqqəti bloklanıb — "
        "administratorla əlaqə saxlayın."
    )


class ModuleDisabledError(KompasOSError):
    """Feature Toggle ilə söndürülmüş modul (bölmə 3)."""

    user_message = "Bu funksiya hazırda deaktiv edilib."


class OperationNotPermittedError(KompasOSError):
    """Əməliyyat üçün səlahiyyət və ya scope yoxdur."""

    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class MonthlyLeaveUsage:
    """İşçinin cari aydakı icazə istifadəsi (bölmə 3 limiti).

    ──────────────────────────────────────────────────────────────────────
    NİYƏ BLOKLAMIR, YALNIZ XƏBƏRDARLIQ EDİR
    ──────────────────────────────────────────────────────────────────────
    Bölmə 3 "Aylıq İcazə Müddəti Limiti (defolt 240 dəq.)"-ni ROOT Control
    Center-dən idarə olunan PARAMETR kimi sadalayır, lakin aşıldıqda nə baş
    verdiyini HEÇ YERDƏ təyin etmir — nə STEP 1-in bloklanmasını, nə cərimə
    yaranmasını.

    Ona görə burada spesifikasiyanın YAZDIĞI qədəri edilir: limit oxunur,
    istifadə hesablanır, aşılma audit-ə düşür və HR-a bildiriş gedir. İşçini
    mağazadan çıxmağa qoymamaq spesifikasiyada olmayan bir qadağa yaratmaq
    olardı; susmaq isə Root-un dəyişdirdiyi limiti mənasız edərdi.

    Eyni istiqamət layihədə artıq var: `ScheduleConflict` xəbərdarlıq edir,
    bloklamır; `LatenessAssessment.creates_fine` həmişə `False`-dur.
    """

    used_minutes: int
    limit_minutes: int

    @property
    def is_exceeded(self) -> bool:
        return self.limit_minutes > 0 and self.used_minutes > self.limit_minutes

    @property
    def remaining_minutes(self) -> int:
        """Qalan büdcə — mənfi olmur (aşılma `is_exceeded` ilə bildirilir)."""
        return max(0, self.limit_minutes - self.used_minutes)


@dataclass(frozen=True)
class EmployeeBreakUsage:
    """Bir işçinin bir gündəki bir fasilə növü üzrə vəziyyəti.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `ports.py`-DA DEYİL, BURADA
    ──────────────────────────────────────────────────────────────────────────
    CLAUDE.md §3: port yalnız domen tipləri qaytarırsa `ports.py`-a gedir.
    Bu struktur isə TƏTBİQ qatının oxu-modelidir — `employee_id`-ni ROOT
    parametrləri ilə hesablanmış `BreakAllowance`-a bağlayır, yəni iki qatın
    birləşməsidir. Onu `ports.py`-a yazsaydıq, domen tətbiq qatının
    strukturunu tanıyardı (`ReportFactProvider` ilə eyni əsaslandırma).
    """

    employee_id: EmployeeId
    allowance: BreakAllowance

    @property
    def is_exceeded(self) -> bool:
        return self.allowance.is_exceeded


@dataclass(frozen=True)
class VerificationOutcome:
    """STEP 3-ün nəticəsi."""

    leave_request: LeaveRequest
    penalty: LeavePenalty
    fine: Fine | None
    saga: SagaResult
    requires_dual_control: bool = False

    @property
    def succeeded(self) -> bool:
        return self.saga.succeeded


class LeaveVerificationUseCase:
    """3-STEP axınının orkestrasiyası."""

    def __init__(
        self,
        *,
        leave_requests: LeaveRequestRepository,
        fines: FineRepository,
        employees: EmployeeRepository,
        leave_types: LeaveTypeRepository,
        camera_assignments: CameraAssignmentRepository,
        break_usage: DailyBreakUsageRepository,
        clock: Clock,
        ntp: NtpVerifier,
        limits: SystemLimits,
        toggles: FeatureToggles,
        saga: SagaOrchestrator,
        audit: AuditTrail,
        notifier: Notifier,
    ) -> None:
        self._leave_requests = leave_requests
        self._fines = fines
        self._employees = employees
        self._leave_types = leave_types
        self._camera_assignments = camera_assignments
        self._break_usage = break_usage
        self._clock = clock
        self._ntp = ntp
        self._limits = limits
        self._toggles = toggles
        self._saga = saga
        self._audit = audit
        self._notifier = notifier

    # ------------------------------ STEP 1 ---------------------------------- #

    def request_leave(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        leave_type_id: LeaveTypeId | None,
        employee_is_in_store: bool,
    ) -> LeaveRequest:
        """`[İcazə İstəyirəm]` — NTP-yə qarşı yoxlanılmış möhür yazılır."""
        self._require_module(tenant_id, FeatureModule.CAMERA_VERIFICATION)
        requested_time, ntp_ok = self._verified_now(tenant_id, operation="STEP_1")

        # Eyni anda yalnız BİR açıq icazə (DB-dəki unikal indekslə eyni qayda).
        existing = self._leave_requests.find_open_for_employee(employee_id)
        if existing is not None and existing.status.is_open:
            raise OperationNotPermittedError(
                "İşçinin artıq açıq icazə sorğusu var",
                user_message="Sizin artıq açıq icazəniz var. Əvvəlcə qayıdışı təsdiqləyin.",
                context={"existing_request_id": str(existing.id)},
            )

        allowance = self._resolve_allowance(tenant_id, leave_type_id)
        request = LeaveRequest.open(
            request_id=new_leave_request_id(),
            tenant_id=tenant_id,
            employee_id=employee_id,
            store_id=store_id,
            requested_time=requested_time,
            leave_type_id=leave_type_id,
            allowance_minutes=allowance,
            ntp_verified=ntp_ok,
            employee_is_in_store=employee_is_in_store,
        )
        self._leave_requests.save(request)

        # SAYĞAC SAVE-DƏN SONRADIR: sorğu yaranmadan fasilə "istifadə edilmiş"
        # sayıla bilməz. İkisi eyni tranzaksiyadadır (GUI sessiyası commit
        # edir), yəni rollback halında sayğac da geri qayıdır — əks halda
        # uğursuz STEP1 işçinin gündəlik haqqını yeyərdi.
        break_usage = self._record_break_use(
            tenant_id=tenant_id,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            at=requested_time,
        )

        monthly = self._monthly_usage(employee_id, at=requested_time, tenant_id=tenant_id)
        after_state: dict[str, object] = {
            "requested_time": requested_time.isoformat(),
            "allowance_minutes": allowance,
            "ntp_verified": ntp_ok,
            "monthly_used_minutes": monthly.used_minutes,
            "monthly_limit_minutes": monthly.limit_minutes,
        }
        if break_usage is not None:
            # AUDİTƏ DÜŞÜR, ÇÜNKİ XƏBƏRDARLIQ GÖSTƏRİLİB: "işçiyə limit
            # aşıldığı bildirildimi?" sualının sonradan cavablana bilməsi üçün
            # sayğacın həmin andakı dəyəri qeydə alınır. Sayğacın özü sonrakı
            # günlərdə dəyişir, audit sətri isə dəyişmir.
            after_state["break_kind"] = break_usage.kind.value
            after_state["break_used_count"] = break_usage.used_count
            after_state["break_daily_count"] = break_usage.daily_count
            after_state["break_limit_exceeded"] = break_usage.is_exceeded

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee_id,
            action="LEAVE_REQUESTED",
            entity_type="leave_requests",
            entity_id=request.id,
            after_state=after_state,
        )
        if break_usage is not None and break_usage.is_exceeded:
            # BLOKLAMA YOX, BİLDİRİŞ (nahar.md §MƏNTİQ, bənd 2): işçi mağazadan
            # çıxıb və əməliyyat davam edir; HR_Admin isə bunu GÖRMƏLİDİR.
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,  # HR_Admin + Store Manager
                category="BREAK_DAILY_LIMIT_EXCEEDED",
                title_az="Gündəlik fasilə həddi aşılıb",
                body_az=(
                    f"İşçi bu gün {break_usage.warning_az()} — "
                    f"əməliyyat bloklanmadı, yalnız qeydə alındı."
                ),
                is_critical=False,
            )
        if monthly.is_exceeded:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,  # HR_Admin + Store Manager
                category="MONTHLY_LEAVE_LIMIT_EXCEEDED",
                title_az="Aylıq icazə limiti aşılıb",
                body_az=(
                    f"İşçinin bu ayda istifadə etdiyi icazə vaxtı "
                    f"{monthly.used_minutes} dəqiqədir və "
                    f"{monthly.limit_minutes} dəqiqəlik aylıq limiti aşır."
                ),
                is_critical=False,
            )
        return request

    # ------------------------------ STEP 2 ---------------------------------- #

    def claim_return(self, *, tenant_id: TenantId, employee_id: EmployeeId) -> LeaveRequest:
        """`[Mən Qayıtdım]` — status `🟡 Gözləyir` olur."""
        claimed_at, _ = self._verified_now(tenant_id, operation="STEP_2")
        request = self._require_open_request(employee_id)

        request.claim_return(claimed_at=claimed_at)
        self._leave_requests.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee_id,
            action="LEAVE_RETURN_CLAIMED",
            entity_type="leave_requests",
            entity_id=request.id,
            after_state={"claimed_at": claimed_at.isoformat()},
        )
        return request

    # ------------------------------ STEP 3 ---------------------------------- #

    async def verify_return(
        self,
        *,
        tenant_id: TenantId,
        operator_id: EmployeeId,
        request_id: LeaveRequestId,
        actual_return_time: datetime | None = None,
    ) -> VerificationOutcome:
        """`[Təsdiqlə]` — SAGA ilə: status + cərimə + audit.

        Zəncirin hər hansı addımı çökərsə kompensasiya işə düşür və əməliyyat
        `PENDING_RECONCILIATION` statusuna keçir (bölmə 1).
        """
        # Sətir KİLİDLİ oxunur: iki operator eyni sorğunu eyni anda
        # təsdiqləyəndə ikincisi birincinin commit-ini gözləyir, sonra TƏZƏ
        # statusu (`VERIFIED`) görür və `verify_return()` onu rədd edir —
        # yəni ikinci cərimə heç yaranmır (bax `RowLockingLeaveRequests`).
        request = self._require_request_locked(request_id)
        # Bölmə 3: `can_verify_returns` — YALNIZ kamera-tipli rollarda ola bilər.
        # Timeout keçibsə HR_Admin/CEO operator əvəzinə təsdiq edə bilər (bölmə 4).
        self._require_camera_permission(
            operator_id,
            "can_verify_returns",
            allow_timeout_override=request.status is LeaveStatus.TIMEOUT_ESCALATED,
        )
        if actual_return_time is not None:
            # Modul başlığı: açıq vaxt ötürmək manual düzəlişdir və eyni
            # flag-i tələb edir. Timeout halında HR_Admin/CEO əvəzedici ola
            # bilir — `_require_camera_permission` bunu onsuz da bilir.
            self._require_camera_permission(
                operator_id,
                "can_override_return_time",
                allow_timeout_override=request.status is LeaveStatus.TIMEOUT_ESCALATED,
            )
        self._require_operator_scope(operator_id, request.store_id)
        verified_at, _ = self._verified_now(tenant_id, operation="STEP_3")

        previous_status = request.status
        created_fine: list[Fine] = []

        def step_update_status(_: dict[str, object]) -> LeavePenalty:
            penalty = request.verify_return(
                operator_id=operator_id,
                verified_at=verified_at,
                actual_return_time=actual_return_time,
            )
            self._leave_requests.save(request)
            return penalty

        def undo_update_status(_: dict[str, object]) -> None:
            request.status = previous_status
            request.actual_return_time = None
            request.verified_at = None
            request.verified_by = None
            request.penalty = None
            request.discard_events()
            self._leave_requests.save(request)

        def step_create_fine(context: dict[str, object]) -> Fine | None:
            penalty: LeavePenalty = context["update_status_result"]  # type: ignore[assignment]
            fine_policy = self._delay_fine_policy(tenant_id)
            amount = fine_policy.amount_for(penalty.delay_minutes)
            if amount.is_zero:
                # BR-002: dərəcə təyin edilməyibsə pul cəriməsi YARANMIR —
                # gecikmə yalnız dəqiqə kimi aylıq limitdən çıxılır.
                return None

            fine = Fine(
                fine_id=new_fine_id(),
                tenant_id=tenant_id,
                employee_id=request.employee_id,
                store_id=request.store_id,
                source=FineSource.AUTO_DELAY,
                amount=amount,
                issued_at=verified_at,
                appeal_window_hours=self._appeal_window_hours(tenant_id),
                leave_request_id=request.id,
            )
            self._fines.save(fine)
            created_fine.append(fine)
            return fine

        def undo_create_fine(_: dict[str, object]) -> None:
            # ────────────────────────────────────────────────────────────────
            # NİYƏ `reverse()` DEYİL, `discard_in_review()`
            # ────────────────────────────────────────────────────────────────
            # `Fine` HƏMİŞƏ `PENDING_REVIEW` doğulur (bax `fine.py` — iki
            # mərhələli görünmə), `reverse()` isə `PUBLISHED` tələb edir.
            # Kompensasiya `reverse()` çağırdığı müddətdə o, HƏR dəfə
            # `DomainRuleError` atırdı: saga kompensasiyanı "uğursuz" sayır,
            # cərimə isə DB-də `PENDING_REVIEW` yetim sətir kimi qalırdı.
            # Aylıq icmal onu görüb `publish()` edə bilərdi — yəni ləğv olunmuş
            # icazə təsdiqinə görə İKİQAT PUL KƏSİNTİSİ.
            #
            # Doğru yol `fine_review.py`-dakı "Sil" qərarı ilə eynidir:
            # `discard_in_review()` — şərti məhz `PENDING_REVIEW`-dur, qeyd
            # fiziki SİLİNMİR, `REVERSED` statusuna keçir və məbləği sıfırlanır
            # (bölmə 4: "orijinal qeyd heç vaxt silinmir").
            reason = "Saga kompensasiyası — icazə təsdiqi geri qaytarıldı"
            for fine in created_fine:
                if fine.status is FineStatus.PENDING_REVIEW:
                    fine.discard_in_review(
                        reviewed_by=operator_id,
                        reviewed_at=verified_at,
                        reason=reason,
                    )
                elif fine.status is FineStatus.PUBLISHED:
                    # Nəzəri hal: saga icrası aylıq icmalla üst-üstə düşüb və
                    # cərimə artıq işçiyə görünüb. O zaman yeganə düzgün yol
                    # etiraz qərarı ilə eyni `reverse()`-dur.
                    fine.reverse(
                        decided_by=operator_id,
                        decided_at=verified_at,
                        reason=reason,
                    )
                else:
                    # `REVERSED`/`REDUCED` — artıq qərar verilib. Təkrar ləğv
                    # istisna atardı və kompensasiyanı sükutla uğursuz edərdi;
                    # idempotentlik naminə addım atlanılır.
                    continue
                self._fines.save(fine)
            created_fine.clear()

        def step_write_audit(context: dict[str, object]) -> None:
            penalty: LeavePenalty = context["update_status_result"]  # type: ignore[assignment]
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=operator_id,
                action="LEAVE_VERIFIED",
                entity_type="leave_requests",
                entity_id=request.id,
                before_state={"status": previous_status.value},
                after_state={
                    "status": LeaveStatus.VERIFIED.value,
                    **penalty.to_dict(),
                    "was_manual_override": request.override is not None,
                    # M-3: hesablamanın MƏNBƏYİ auditdə açıq yazılır. "Niyə
                    # bu işçiyə 30 dəqiqə gecikmə yazıldı?" sualının cavabı
                    # bir sətirdə görünməlidir — operatorun klik anı ilə
                    # faktiki qayıdış anı arasındakı fərq mübahisənin ən
                    # tez-tez rast gəlinən mövzusudur.
                    "verified_at": verified_at.isoformat(),
                    "actual_return_time": (
                        request.actual_return_time.isoformat()
                        if request.actual_return_time
                        else None
                    ),
                    "return_time_source": _return_time_source(request, explicit=actual_return_time),
                },
            )

        result = await self._saga.execute(
            name="LeaveVerification",
            steps=[
                SagaStep(
                    "update_status",
                    action=step_update_status,
                    compensation=undo_update_status,
                ),
                SagaStep("create_fine", action=step_create_fine, compensation=undo_create_fine),
                # Audit yazısı QƏSDƏN kompensasiyasızdır — bölmə 4:
                # "orijinal qeyd heç vaxt silinmir".
                SagaStep("write_audit", action=step_write_audit, compensation=None),
            ],
            tenant_id=tenant_id,
            actor_id=operator_id,
        )

        # Saga uğursuz olduqda kompensasiya `penalty`-ni sıfırlayır — çağıran
        # tərəf `outcome.saga.status` ilə vəziyyəti yoxlamalıdır.
        penalty = request.penalty or LeavePenalty(
            elapsed_minutes=0,
            allowance_minutes=request.allowance_minutes,
            delay_minutes=0,
            total_minutes=request.allowance_minutes,
        )

        return VerificationOutcome(
            leave_request=request,
            penalty=penalty,
            fine=created_fine[0] if created_fine else None,
            saga=result,
        )

    def apply_override(
        self,
        *,
        tenant_id: TenantId,
        operator_id: EmployeeId,
        request_id: LeaveRequestId,
        overridden_time: datetime,
        reason: str,
    ) -> LeaveRequest:
        """`[Vaxtı Əllə Təyin Et]` — 30+ dəqiqə dual-control-a düşür."""
        # Yazma axını — kilidli oxu (təsdiqlə override eyni sətrə yazır).
        request = self._require_request_locked(request_id)
        self._require_camera_permission(
            operator_id,
            "can_override_return_time",
            allow_timeout_override=request.status is LeaveStatus.TIMEOUT_ESCALATED,
        )
        self._require_operator_scope(operator_id, request.store_id)
        system_time, _ = self._verified_now(tenant_id, operation="OVERRIDE")

        threshold = self._limit_int(tenant_id, SystemLimitKey.DUAL_CONTROL_THRESHOLD_MINUTES)
        dual_control_on = self._toggles.is_enabled(tenant_id, FeatureModule.DUAL_CONTROL.value)

        override = request.apply_manual_override(
            operator_id=operator_id,
            overridden_time=overridden_time,
            system_time=system_time,
            reason=reason,
            # Modul söndürülübsə hədd əlçatmaz edilir — RETROAKTİV TƏSİR
            # QAYDASI: mövcud gözləyən sorğular öz axınını tamamlayır,
            # yalnız YENİ override-lar ikinci təsdiq tələb etmir (bölmə 3).
            dual_control_threshold_minutes=threshold if dual_control_on else 10**9,
        )
        self._leave_requests.save(request)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=operator_id,
            action="MANUAL_TIME_OVERRIDE",
            entity_type="leave_requests",
            entity_id=request.id,
            after_state={
                "system_time": system_time.isoformat(),
                "overridden_time": overridden_time.isoformat(),
                "delta_minutes": override.delta_minutes,
                "reason": override.reason,
                "requires_dual_control": override.requires_dual_control,
            },
            reason=override.reason,
        )

        if override.is_pending_approval:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="DUAL_CONTROL_PENDING",
                title_az="Manual vaxt düzəlişi təsdiq gözləyir",
                body_az=(
                    f"{override.delta_minutes} dəqiqəlik manual düzəliş ikinci "
                    f"təsdiq tələb edir. Səbəb: {override.reason}"
                ),
                is_critical=True,
            )
        return request

    def approve_dual_control(
        self,
        *,
        tenant_id: TenantId,
        approver_id: EmployeeId,
        request_id: LeaveRequestId,
    ) -> LeaveRequest:
        """İkinci təsdiq — təsdiqçinin flag-i və özünü-təsdiq qadağası yoxlanılır."""
        # Yazma axını — kilidli oxu (iki təsdiqçinin eyni anda basması).
        request = self._require_request_locked(request_id)
        now = self._clock.now()
        self._require_dual_control_approver(approver_id, now=now)

        # TIMEOUT ƏVVƏLCƏ YOXLANILIR (M-5): planlaşdırılmış iş saatda bir dəfə
        # işləyir, təsdiqçi isə düyməni istənilən an basa bilər. Yoxlama
        # yalnız işdə olsaydı, iki icra arasındakı pəncərədə müddəti bitmiş
        # sorğu təsdiqlənərdi — yəni hədd praktikada təsadüfi işləyərdi.
        timeout = self._limit_int(tenant_id, SystemLimitKey.DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES)
        if request.expire_override(now=now, timeout_minutes=timeout):
            self._leave_requests.save(request)
            self._record_override_closure(
                tenant_id=tenant_id,
                actor_id=None,
                request=request,
                action="DUAL_CONTROL_EXPIRED",
            )
            self._notify_override_closed(tenant_id=tenant_id, request=request)

        request.approve_override(approver_id=approver_id, approved_at=now)
        self._leave_requests.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver_id,
            action="DUAL_CONTROL_APPROVED",
            entity_type="leave_requests",
            entity_id=request.id,
            after_state={"approved_at": now.isoformat()},
        )
        return request

    def reject_dual_control(
        self,
        *,
        tenant_id: TenantId,
        approver_id: EmployeeId,
        request_id: LeaveRequestId,
        reason: str,
    ) -> LeaveRequest:
        """İkinci təsdiqin «yox» cavabı (M-5) — səbəb MƏCBURİDİR.

        `approve_dual_control` ilə EYNİ qapıdan keçir: təsdiq etmək və rədd
        etmək eyni səlahiyyətin iki üzüdür. Ayrı flag yaratmaq "təsdiqləyə
        bilirsən, amma imtina edə bilmirsən" kimi mənasız bir vəziyyət
        yaradardı — və praktikada təsdiqçini «hə» deməyə məcbur edərdi.
        """
        request = self._require_request_locked(request_id)
        now = self._clock.now()
        self._require_dual_control_approver(approver_id, now=now)

        request.reject_override(approver_id=approver_id, rejected_at=now, reason=reason)
        self._leave_requests.save(request)
        self._record_override_closure(
            tenant_id=tenant_id,
            actor_id=approver_id,
            request=request,
            action="DUAL_CONTROL_REJECTED",
        )
        self._notify_override_closed(tenant_id=tenant_id, request=request)
        return request

    def expire_pending_overrides(self, tenant_id: TenantId) -> int:
        """Təsdiqsiz qalmış vaxt düzəlişlərini ləğv edir (planlaşdırılmış iş, M-5).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AVTOMATİK TƏSDİQ YOX
        ──────────────────────────────────────────────────────────────────────
        "Heç kim baxmadısa təsdiqlənmiş say" qaydası dual-control-u tamamilə
        mənasız edərdi: operator sadəcə gözləməklə istənilən düzəlişi keçirə
        bilərdi. Ona görə timeout LƏĞV edir — orijinal vaxt qüvvədə qalır və
        sorğunu yazan operator bildiriş alır ki, lazımdırsa yenidən müraciət
        etsin (bölmə 3: "gözləyən override-lar sonsuza qədər təsdiqsiz
        qalmasın").

        Returns:
            Ləğv edilmiş sorğu sayı.
        """
        now = self._clock.now()
        timeout = self._limit_int(tenant_id, SystemLimitKey.DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES)
        expired = 0

        for request in self._leave_requests.list_pending_dual_control(tenant_id):
            if not request.expire_override(now=now, timeout_minutes=timeout):
                continue
            self._leave_requests.save(request)
            expired += 1
            self._record_override_closure(
                tenant_id=tenant_id,
                actor_id=None,
                request=request,
                action="DUAL_CONTROL_EXPIRED",
            )
            self._notify_override_closed(tenant_id=tenant_id, request=request)

        if expired:
            _log.warning(
                "DUAL_CONTROL_OVERRIDES_EXPIRED",
                extra={"tenant_id": str(tenant_id), "count": expired, "timeout_minutes": timeout},
            )
        return expired

    def _require_dual_control_approver(self, approver_id: EmployeeId, *, now: datetime) -> None:
        """`can_approve_dual_control_override` qapısı — təsdiq və rədd üçün eyni."""
        approver = self._employees.get(approver_id)
        if approver is None or not approver.has_permission(DUAL_CONTROL_APPROVAL_FLAG, now=now):
            raise OperationNotPermittedError(
                f"'{DUAL_CONTROL_APPROVAL_FLAG}' səlahiyyəti olmadan dual-control "
                f"qərarı mümkün deyil",
                context={"approver_id": str(approver_id)},
            )

    def _record_override_closure(
        self,
        *,
        tenant_id: TenantId,
        actor_id: EmployeeId | None,
        request: LeaveRequest,
        action: str,
    ) -> None:
        """Rədd/ləğv izini auditə yazır — hər iki yol üçün TƏK yer.

        `actor_id=None` "qərarı sistem verdi" deməkdir (timeout). Audit
        sətrini buraxmaq olmazdı: işçinin vaxtı düzəldilməyibsə, bunun
        SƏBƏBİ sonradan soruşulacaq.
        """
        override = request.override
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type="leave_requests",
            entity_id=request.id,
            after_state={
                "overridden_time": (
                    override.overridden_time.isoformat() if override is not None else None
                ),
                "delta_minutes": override.delta_minutes if override is not None else None,
                "rejected_at": (
                    override.rejected_at.isoformat()
                    if override is not None and override.rejected_at
                    else None
                ),
                # Ləğvdən SONRA hansı vaxt qüvvədədir — sual məhz budur.
                "effective_return_time": request.resolved_return_time(
                    fallback=self._clock.now()
                ).isoformat(),
            },
            reason=override.rejection_reason if override is not None else None,
        )

    def _notify_override_closed(self, *, tenant_id: TenantId, request: LeaveRequest) -> None:
        """Sorğunu YAZAN operatora bildiriş (M-5).

        Ünvan `recipient_id=None` DEYİL: bu, ümumi xəbərdarlıq deyil, konkret
        operatorun gözlədiyi cavabdır. O, düzəlişin tətbiq olunduğunu güman
        edib növbəti sorğuya keçib ola bilər.
        """
        override = request.override
        if override is None:  # pragma: no cover - çağırış yalnız ləğvdən sonradır
            return
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=override.operator_id,
            category="DUAL_CONTROL_CLOSED",
            title_az="Manual vaxt düzəlişi tətbiq olunmadı",
            body_az=(
                f"{override.delta_minutes} dəqiqəlik vaxt düzəlişi sorğunuz "
                f"tətbiq edilmədi. Səbəb: {override.rejection_reason}. "
                f"İcazənin orijinal vaxtı qüvvədə qalır."
            ),
            is_critical=False,
        )

    # ----------------------------- TIMEOUT ---------------------------------- #

    def escalate_timeouts(self, tenant_id: TenantId) -> int:
        """45 dəqiqədən çox gözləyən sorğuları eskalasiya edir (bölmə 4)."""
        now = self._clock.now()
        timeout = self._limit_int(tenant_id, SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES)
        escalated = 0

        for request in self._leave_requests.list_due_for_timeout(
            tenant_id, now=now, timeout_minutes=timeout
        ):
            if not request.escalate_timeout(now=now, timeout_minutes=timeout):
                continue
            self._leave_requests.save(request)
            escalated += 1
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="VERIFICATION_TIMEOUT",
                title_az="İcazə qayıdışı təsdiqsiz qalıb",
                body_az=(
                    f"İşçinin qayıdış təsdiqi {timeout} dəqiqədən çoxdur "
                    f"gözləyir. HR_Admin və ya CEO manual təsdiq edə bilər."
                ),
                is_critical=True,
            )

        if escalated:
            _log.warning(
                "LEAVE_TIMEOUTS_ESCALATED",
                extra={"tenant_id": str(tenant_id), "count": escalated},
            )
        return escalated

    # ------------------------------ köməkçi --------------------------------- #

    def _verified_now(self, tenant_id: TenantId, *, operation: str) -> tuple[datetime, bool]:
        """NTP-yə qarşı yoxlanılmış vaxt; sürüşmə həddi aşılıbsa bloklayır."""
        moment, ntp_ok = self._ntp.verified_now()
        if ntp_ok:
            return moment, True

        drift = self._ntp.drift_seconds()
        max_drift = self._limit_int(tenant_id, SystemLimitKey.NTP_MAX_DRIFT_SECONDS)
        if drift is not None and abs(drift) > max_drift:
            _audit_log.critical(
                "TIME_DRIFT_DETECTED",
                extra={
                    "operation": operation,
                    "drift_seconds": drift,
                    "max_allowed": max_drift,
                },
            )
            raise TimeDriftError(
                f"Saat sürüşməsi {drift:.1f} s — icazə verilən hədd {max_drift} s. "
                f"'{operation}' əməliyyatı bloklandı.",
                context={"drift_seconds": drift, "operation": operation},
            )
        # NTP əlçatmazdır, lakin ölçülmüş sürüşmə həddi aşmır → davam.
        return moment, False

    def _require_module(self, tenant_id: TenantId, module: FeatureModule) -> None:
        if not self._toggles.is_enabled(tenant_id, module.value):
            raise ModuleDisabledError(
                f"'{module.value}' modulu Root tərəfindən deaktiv edilib",
                context={"module": module.value},
            )

    def _require_request(self, request_id: LeaveRequestId) -> LeaveRequest:
        request = self._leave_requests.get(request_id)
        if request is None:
            raise OperationNotPermittedError(
                "İcazə sorğusu tapılmadı",
                user_message="Sorğu tapılmadı.",
                context={"request_id": str(request_id)},
            )
        return request

    def _require_request_locked(self, request_id: LeaveRequestId) -> LeaveRequest:
        """`_require_request`-in YAZMA axını üçün sətir-kilidli variantı.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ MÖVCUD METOD DƏYİŞDİRİLMİR
        ──────────────────────────────────────────────────────────────────────
        `_require_request` oxu-yalnız yollarda da işlədilə bilər; ona kilid
        qoymaq hər sadə baxışı yazı-kilidinə çevirərdi. Ona görə kilid AYRICA
        metoddadır və yalnız STEP 3 / override / dual-control axınları onu
        çağırır.

        Repo kilidi dəstəkləmirsə (sahtə repo, gələcək adapter) davranış
        DƏYİŞMİR — mövcud `_require_request` yolu işləyir. Belə halda qoruma
        DB-dəki qismən unikal indeksdə qalır (miqrasiya 015): kilidin itməsi
        səssiz ikiqat cərimə demək DEYİL.

        Sətir tapılmadıqda da `_require_request`-ə ötürülür — istisna mətni
        TƏK YERDƏ qalsın deyə (bir əlavə SELECT yalnız "tapılmadı" halında).
        """
        repository = self._leave_requests
        if not isinstance(repository, RowLockingLeaveRequests):
            return self._require_request(request_id)
        request = repository.get_for_update(request_id)
        if request is None:
            return self._require_request(request_id)
        return request

    def _require_open_request(self, employee_id: EmployeeId) -> LeaveRequest:
        request = self._leave_requests.find_open_for_employee(employee_id)
        if request is None:
            raise OperationNotPermittedError(
                "Açıq icazə sorğusu yoxdur",
                user_message="Açıq icazəniz yoxdur.",
                context={"employee_id": str(employee_id)},
            )
        return request

    def _require_camera_permission(
        self, operator_id: EmployeeId, flag: str, *, allow_timeout_override: bool = False
    ) -> None:
        """Kamera əməliyyat flag-ini yoxlayır (bölmə 3).

        Mağaza scope-u ilə BİRLİKDƏ işləyir, onu ƏVƏZ ETMİR: təyinat "hansı
        filialları görürsən" sualına cavab verir, flag isə "bu əməliyyatı edə
        bilərsənmi" sualına. İkisini bir yoxlamaya yığmaq olmazdı — Root/CEO
        heç bir mağazaya təyin edilmir, amma timeout sonrası müdaxilə edə bilir.

        Args:
            allow_timeout_override: Bölmə 4 TIMEOUT QAYDASI — 45 dəqiqədən sonra
                `HR_Admin`/`CEO` Kamera Operatoru ƏVƏZİNƏ təsdiq/override edə
                bilər (Store Manager YOX). Həmin hal üçün kamera flag-i deyil,
                `can_approve_dual_control_override` kifayətdir: o flag anti-fraud
                qaydasına görə onsuz da Mağaza_Meneceri/Satıcı-ya verilə bilmir,
                yəni dual-control tiering-i qorunur.
        """
        operator = self._employees.get(operator_id)
        if operator is None:
            raise OperationNotPermittedError(
                "Əməliyyatı aparan istifadəçi tapılmadı",
                context={"operator_id": str(operator_id)},
            )

        now = self._clock.now()
        if operator.has_permission(flag, now=now):
            return
        if allow_timeout_override and operator.has_permission(DUAL_CONTROL_APPROVAL_FLAG, now=now):
            _log.info(
                "TIMEOUT_ESCALATION_ACTOR",
                extra={"actor_id": str(operator_id), "instead_of_flag": flag},
            )
            return

        raise OperationNotPermittedError(
            f"'{flag}' səlahiyyəti olmadan bu əməliyyat mümkün deyil",
            user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
            context={"operator_id": str(operator_id), "flag": flag},
        )

    def _require_operator_scope(self, operator_id: EmployeeId, store_id: StoreId) -> None:
        """FAIL-SAFE (bölmə 4): təyinat yoxdursa operator heç nə görmür/edə bilmir."""
        allowed = self._camera_assignments.stores_for_operator(operator_id)
        if store_id not in allowed:
            raise OperationNotPermittedError(
                "Operator bu mağazaya təyin edilməyib",
                user_message="Bu mağaza sizin nəzarətinizdə deyil.",
                context={
                    "operator_id": str(operator_id),
                    "store_id": str(store_id),
                    "assigned_count": len(allowed),
                },
            )

    def _resolve_allowance(self, tenant_id: TenantId, leave_type_id: LeaveTypeId | None) -> int:
        policy = LeaveAllowancePolicy.from_limits(self._limits.all_for(tenant_id))
        duration = (
            self._leave_types.get_default_duration(leave_type_id)
            if leave_type_id is not None
            else None
        )
        return policy.resolve(leave_type_minutes=duration)

    def _delay_fine_policy(self, tenant_id: TenantId) -> DelayFinePolicy:
        return DelayFinePolicy.from_limits(self._limits.all_for(tenant_id))

    # ------------------------- Nahar / Çay fasiləsi --------------------------- #
    #
    # BU ÜÇ METOD MÖVCUD AXINI DƏYİŞMİR — ÜSTÜNƏ QAT ƏLAVƏ EDİR (nahar.md
    # QIRMIZI XƏTT). `request_leave` imzası, `LeaveRequest` entity-si və
    # `Delay`/`Total` düsturu olduğu kimi qalır; fasilə sayğacı ayrı cədvəldə
    # yaşayır və heç bir qərarı BLOKLAMIR.

    def _record_break_use(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        leave_type_id: LeaveTypeId | None,
        at: datetime,
    ) -> BreakAllowance | None:
        """Seçim sistem fasiləsidirsə sayğacı artırır; deyilsə `None`.

        `None` qaytarmaq SÜKUTLA UĞURSUZLUQ DEYİL: adi icazə növü ("Bank
        işi") ROOT fasilə parametrlərinə tabe deyil və sayğaca düşməməlidir
        — nahar.md Nahar/Çay-ı ümumi kataloqdan AYRI qat kimi təyin edir.

        GÜN SEÇİMİ: `at.date()`, yəni möhürün öz günü. Mövcud
        `_monthly_usage` da eyni prinsiplə (`at.year`, `at.month`) işləyir —
        iki fərqli təqvim qaydası eyni ekranda ziddiyyətli rəqəmlər verərdi.
        """
        if leave_type_id is None:
            return None
        kind = self._leave_types.break_kind_of(leave_type_id)
        if kind is None:
            return None

        used = self._break_usage.record_use(
            tenant_id,
            employee_id,
            kind=kind,
            on_date=at.date(),
            at=at,
        )
        allowance = BreakAllowance.from_limits(
            kind, self._limits.all_for(tenant_id), used_count=used
        )
        if allowance.is_exceeded:
            _log.info(
                "BREAK_DAILY_LIMIT_EXCEEDED",
                extra={
                    "employee_id": str(employee_id),
                    "break_kind": kind.value,
                    "used_count": used,
                    "daily_count": allowance.daily_count,
                },
            )
        return allowance

    def break_status(
        self, *, tenant_id: TenantId, employee_id: EmployeeId, on_date: date
    ) -> dict[BreakKind, BreakAllowance]:
        """İşçi Ana Ekranının göstəricisi — HƏR İKİ növ, həmişə.

        Sətri olmayan növ də `0` istifadə ilə qaytarılır: ekran «Nahar
        fasiləniz: 60 dəqiqə / Bu gün: 0/1» yazmalıdır, boş qalmamalıdır —
        işçi haqqının nə olduğunu istifadə etməmişdən ƏVVƏL bilməlidir.
        """
        limits = self._limits.all_for(tenant_id)
        usage = self._break_usage.usage_for_day(employee_id, on_date=on_date)
        return {
            kind: BreakAllowance.from_limits(kind, limits, used_count=usage.get(kind, 0))
            for kind in BreakKind
        }

    def break_overuse_for_day(
        self, *, tenant_id: TenantId, on_date: date
    ) -> list[EmployeeBreakUsage]:
        """HR_Admin panelinin xəbərdarlıq siyahısı — YALNIZ həddi aşanlar.

        Süzgəc SQL-də deyil, BURADA tətbiq olunur: hədd `system_limits`-dədir
        və Root onu gün ərzində dəyişə bilər. Sorğuya yazılsaydı, dəyişiklik
        yalnız növbəti miqrasiyadan sonra təsir edərdi (bax portun izahı).
        """
        limits = self._limits.all_for(tenant_id)
        rows = self._break_usage.usage_rows_for_day(tenant_id, on_date=on_date)
        usages = [
            EmployeeBreakUsage(
                employee_id=employee_id,
                allowance=BreakAllowance.from_limits(kind, limits, used_count=count),
            )
            for employee_id, kind, count in rows
        ]
        return [usage for usage in usages if usage.is_exceeded]

    def monthly_usage(
        self, *, tenant_id: TenantId, employee_id: EmployeeId, at: datetime
    ) -> MonthlyLeaveUsage:
        """Aylıq icazə istifadəsi vs ROOT limiti — ekranlar üçün açıq metod."""
        return self._monthly_usage(employee_id, at=at, tenant_id=tenant_id)

    def _monthly_usage(
        self, employee_id: EmployeeId, *, at: datetime, tenant_id: TenantId
    ) -> MonthlyLeaveUsage:
        """Limit `system_limits`-dən, istifadə isə repo aqreqasiyasından gəlir."""
        limit = self._limit_int(tenant_id, SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT)
        used = self._leave_requests.monthly_used_minutes(employee_id, year=at.year, month=at.month)
        return MonthlyLeaveUsage(used_minutes=used, limit_minutes=limit)

    def _appeal_window_hours(self, tenant_id: TenantId) -> int:
        return self._limit_int(tenant_id, SystemLimitKey.FINE_APPEAL_WINDOW_HOURS)

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))


def _return_time_source(request: LeaveRequest, *, explicit: datetime | None) -> str:
    """Cərimə bazasının MƏNBƏ ETİKETİ — audit sətri üçün (M-3).

    Etiket hesablamadan SONRA, `LeaveRequest.resolved_return_time()` ilə eyni
    sıra ilə oxunur. Ayrı bir "mənbə" sahəsini entity-yə əlavə etmək RƏDD
    EDİLDİ: o, `leave_requests` cədvəlində saxlanmalı olan yeni sütun demək
    olardı, halbuki dəyər mövcud sahələrdən birmənalı çıxarılır.
    """
    if explicit is not None:
        return "EXPLICIT_ARGUMENT"
    if request.override is not None and request.override.is_effective:
        return "MANUAL_OVERRIDE"
    if request.return_claimed_time is not None:
        return "EMPLOYEE_CLAIM"
    return "OPERATOR_CLICK"


__all__ = [
    "EmployeeBreakUsage",
    "LeaveVerificationUseCase",
    "ModuleDisabledError",
    "MonthlyLeaveUsage",
    "OperationNotPermittedError",
    "TimeDriftError",
    "VerificationOutcome",
]
