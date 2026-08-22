"""3-STEP LEAVE VERIFICATION aqreqatı (spesifikasiya bölmə 4).

VƏZİYYƏT MAŞINI::

    [STEP 1: İcazə İstəyirəm]                (yalnız 🟢 Mağazada statusundan)
              ↓
        🔵 OUTSIDE
              ↓  [STEP 2: Mən Qayıtdım]      (düymə yalnız 🔵 halında görünür)
        🟡 PENDING_RETURN_VERIFICATION
              ↓                    ↓
    [STEP 3A: Təsdiqlə]    [45 dəq. timeout]
              ↓                    ↓
         ✅ VERIFIED       ⚠️ TIMEOUT_ESCALATED
                                   ↓  [HR_Admin/CEO manual həlli]
                              ✅ VERIFIED

ANTI-FRAUD ZƏMANƏTLƏRİ:
    * `Requested_Time` YALNIZ STEP 1-də, NTP-yə qarşı yoxlanılmış vaxtla yazılır
      və sonra HEÇ VAXT dəyişmir.
    * Cərimə YALNIZ təsdiqlənmiş faktiki qayıdış vaxtına əsaslanır — operatorun
      düyməni kliklədiyi vaxta YOX.
    * Timeout-dan sonra Store Manager təsdiq EDƏ BİLMƏZ (dual-control tiering).

──────────────────────────────────────────────────────────────────────────────
QAYIDIŞ ANI KİMİN SAATINDAN OXUNUR (M-3 DÜZƏLİŞİ)
──────────────────────────────────────────────────────────────────────────────
Spesifikasiya bölmə 4 bu barədə İKİ sətir yazır və onlar hərfi oxunuşda
bir-birinə ziddir:

    "Option A: Clicks `[Təsdiqlə]` (Uses current system time)"
    "Cərimə strictly VERIFIED ACTUAL TIME əsasında hesablanır, operatorun
     düyməni kliklədiyi vaxt əsasında YOX."

Yeganə DAXİLƏN TUTARLI oxunuş: operatorun klik anı TƏSDİQ MÖHÜRÜDÜR
(`verified_at` — auditə düşür), cərimənin bazası isə işçinin FAKTİKİ qayıdış
siqnalıdır. Sistemdə belə siqnal onsuz da var: STEP 2-də işçi mağaza PC-sində
PIN daxil edib `[Mən Qayıtdım]` basır və o an NTP-yə qarşı yoxlanılmış vaxtla
`return_claimed_time`-a yazılır. Yəni "faktiki qayıdış" üçün ayrıca bir
mənbə İCAD ETMƏYƏ ehtiyac yoxdur — o, artıq qeydə alınıb.

Əvvəl `verified_at` fallback kimi işlədilirdi. Nəticə: işçi 13:00-da qayıdıb
PIN vurur, operator 13:20-də ekrana baxıb `[Təsdiqlə]` basır → işçiyə 20
dəqiqə gecikmə yazılır və (dərəcə təyin olunubsa) REAL PUL kəsilir. Operatorun
növbəsindəki yük işçinin cibindən ödənilə bilməz.

RƏDD EDİLƏN ALTERNATİV: "operator gecikməsi üçün ayrıca tolerantlıq dəqiqəsi
əlavə edək" — bu, spesifikasiyada olmayan YENİ bir güzəşt qaydası icad etmək
olardı və həqiqi qayıdış anı onsuz da məlum olduğu halda onu təxmin etməklə
əvəz edərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.domain.entities.base import (
    AggregateRoot,
    DomainRuleError,
    InvalidStateTransitionError,
)
from src.domain.events import (
    LeaveRequestedEvent,
    LeaveReturnClaimedEvent,
    LeaveVerifiedEvent,
    ManualTimeOverrideEvent,
    VerificationTimeoutEscalatedEvent,
)
from src.domain.value_objects.authorization import SystemRole
from src.domain.value_objects.identifiers import (
    EmployeeId,
    LeaveRequestId,
    LeaveTypeId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.penalty import LeavePenalty, calculate_leave_penalty
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: Bölmə 4, validasiya 3: manual override səbəbi üçün minimum uzunluq.
MIN_OVERRIDE_REASON_LENGTH = 10

#: Timeout-dan sonra manual həll edə bilən rollar.
#: Store Manager QƏSDƏN YOXDUR — bölmə 4: "HR_Admin/CEO (Store Manager YOX —
#: dual-control tiering-ə uyğun)".
TIMEOUT_RESOLVER_ROLES = frozenset({SystemRole.HR_ADMIN, SystemRole.CEO, SystemRole.ROOT})


class LeaveStatus(str, Enum):
    """İcazə sorğusunun vəziyyəti (`leave_requests.status` ilə eyni)."""

    OUTSIDE = "OUTSIDE"  # 🔵 Xaricdə
    PENDING_RETURN_VERIFICATION = "PENDING_RETURN_VERIFICATION"  # 🟡 Gözləyir
    VERIFIED = "VERIFIED"
    TIMEOUT_ESCALATED = "TIMEOUT_ESCALATED"
    CANCELLED = "CANCELLED"

    @property
    def is_open(self) -> bool:
        """İşçinin "açıq" icazəsi varmı — STEP 1-in təkrarlanmasını bloklayır."""
        return self in (
            LeaveStatus.OUTSIDE,
            LeaveStatus.PENDING_RETURN_VERIFICATION,
            LeaveStatus.TIMEOUT_ESCALATED,
        )


@dataclass
class ManualOverride:
    """`[Vaxtı Əllə Təyin Et]` qeydi (bölmə 4, Option B).

    ──────────────────────────────────────────────────────────────────────────
    ÜÇ SONLUQ, İKİSİ ƏVVƏL YOX İDİ (M-5)
    ──────────────────────────────────────────────────────────────────────────
    Spesifikasiya yalnız "30+ dəqiqəlik override → dual-control qaydasına
    düşür" deyir və təsdiqin GƏLMƏDİYİ halları açıq qoyur. DB isə onları
    ÖNCƏDƏN nəzərdə tutub: `override_status` enum-unda `REJECTED` dəyəri və
    `manual_time_overrides.rejection_reason` sütunu `schema.sql`-da EYNİ
    miqrasiyadan bəri mövcuddur, lakin domendə onlara aparan yol yox idi.
    Yəni bu bir icad deyil, yarımçıq qalmış qaydanın tamamlanmasıdır:

        PENDING_DUAL_CONTROL ──approve()──> APPROVED     (vaxt qüvvəyə minir)
                 │
                 ├──reject(səbəb)────────> REJECTED      (təsdiqçi «yox» dedi)
                 │
                 └──expire(timeout)──────> REJECTED      (heç kim baxmadı)

    Timeout AVTOMATİK TƏSDİQƏ çevrilmir — bu, dual-control-un özünü mənasız
    edərdi ("gözlə, özü təsdiqlənəcək"). Sorğu LƏĞV olunur və orijinal vaxt
    qüvvədə qalır (fail-closed).
    """

    operator_id: EmployeeId
    system_time: datetime
    overridden_time: datetime
    reason: str
    delta_minutes: int
    requires_dual_control: bool
    approved_by: EmployeeId | None = None
    approved_at: datetime | None = None
    #: Rədd/ləğv izi. `rejected_by is None`, lakin `rejected_at` doludursa —
    #: qərarı İNSAN deyil, timeout verib (planlaşdırılmış iş). İki halı bir
    #: statusda saxlamaq DB enum-unu genişləndirməkdən üstündür: `ALTER TYPE
    #: ... ADD VALUE` miqrasiyanı tranzaksiyadan kənara çıxarardı, halbuki
    #: fərq onsuz da `rejection_reason` mətnində və `rejected_by`-da görünür.
    rejected_by: EmployeeId | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None

    @property
    def is_rejected(self) -> bool:
        """Təsdiqçi rədd etdi VƏ YA təsdiq müddəti bitdi."""
        return self.rejected_at is not None

    @property
    def is_pending_approval(self) -> bool:
        return self.requires_dual_control and self.approved_by is None and not self.is_rejected

    @property
    def is_effective(self) -> bool:
        """Düzəliş vaxt hesablamasında NƏZƏRƏ ALINIRMI.

        FAIL-CLOSED: təsdiq gözləyən düzəliş HEÇ NƏYƏ təsir etmir — nə cərimə
        hesablamasına, nə ekrandakı vaxta. Əks halda operator 30+ dəqiqəlik
        düzəlişi yazıb dərhal `[Təsdiqlə]` basmaqla ikinci təsdiqi tamamilə
        yan keçə bilərdi.
        """
        return not self.is_rejected and not self.is_pending_approval

    def reject(self, *, rejected_by: EmployeeId | None, rejected_at: datetime, reason: str) -> None:
        """Rədd/ləğv qeydini yazır — səbəb HƏR İKİ yolda məcburidir.

        Səbəbsiz rədd işçi üçün "vaxtınız düzəldilmədi, niyəsi məlum deyil"
        demək olardı; həmin sətir isə onun cəriməsinin əsasıdır.
        """
        require_aware(rejected_at, field="rejected_at")
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_OVERRIDE_REASON_LENGTH:
            raise DomainRuleError(
                f"Rədd səbəbi minimum {MIN_OVERRIDE_REASON_LENGTH} simvol olmalıdır",
                user_message=f"Səbəb ən azı {MIN_OVERRIDE_REASON_LENGTH} simvol olmalıdır.",
            )
        self.rejected_by = rejected_by
        self.rejected_at = rejected_at
        self.rejection_reason = cleaned

    def waiting_minutes(self, *, now: datetime) -> int:
        """Neçə dəqiqədir ikinci təsdiq gözləyir (timeout ölçüsü)."""
        require_aware(now, field="now")
        return int((now - self.system_time).total_seconds() // 60)


class LeaveRequest(AggregateRoot):
    """İcazə sorğusu aqreqatı."""

    def __init__(
        self,
        *,
        request_id: LeaveRequestId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        requested_time: datetime,
        leave_type_id: LeaveTypeId | None = None,
        allowance_minutes: int = 0,
        ntp_verified: bool = False,
        status: LeaveStatus = LeaveStatus.OUTSIDE,
    ) -> None:
        super().__init__()
        require_aware(requested_time, field="requested_time")

        self.id = request_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.leave_type_id = leave_type_id
        self.allowance_minutes = allowance_minutes

        #: STEP 1-in NTP-yə qarşı yoxlanılmış anı — DƏYİŞMƏZ.
        self._requested_time = requested_time
        self.ntp_verified = ntp_verified

        self.status = status
        self.return_claimed_time: datetime | None = None
        self.actual_return_time: datetime | None = None
        self.verified_at: datetime | None = None
        self.verified_by: EmployeeId | None = None
        self.escalated_at: datetime | None = None
        self.override: ManualOverride | None = None
        self.penalty: LeavePenalty | None = None
        self.cancellation_reason: str | None = None

    # ------------------------------ STEP 1 ---------------------------------- #

    @classmethod
    def open(
        cls,
        *,
        request_id: LeaveRequestId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        requested_time: datetime,
        leave_type_id: LeaveTypeId | None = None,
        allowance_minutes: int = 0,
        ntp_verified: bool = False,
        employee_is_in_store: bool,
    ) -> LeaveRequest:
        """STEP 1 — `[İcazə İstəyirəm]`.

        Args:
            employee_is_in_store: İşçinin cari statusu `🟢 Mağazada`-dırmı.
                Bölmə 4: "STEP 1 yalnız `🟢 Mağazada` statusundan işə düşür,
                `⚪`/`🟡` statuslarından YOX (işçi günə başlamadan icazə
                istəyə bilməz)."
        """
        if not employee_is_in_store:
            raise DomainRuleError(
                "İcazə yalnız 'Mağazada' statusundan istənilə bilər — işçi hələ "
                "günə başlamayıb və ya giriş təsdiqi gözlənilir",
                user_message="İcazə istəmək üçün əvvəlcə işə giriş təsdiqlənməlidir.",
                context={"employee_id": str(employee_id)},
            )

        request = cls(
            request_id=request_id,
            tenant_id=tenant_id,
            employee_id=employee_id,
            store_id=store_id,
            requested_time=requested_time,
            leave_type_id=leave_type_id,
            allowance_minutes=allowance_minutes,
            ntp_verified=ntp_verified,
        )
        request.record_event(
            LeaveRequestedEvent(
                leave_request_id=request_id,
                employee_id=employee_id,
                store_id=store_id,
                leave_type_id=leave_type_id,  # type: ignore[arg-type]
                requested_time=requested_time,
                ntp_verified=ntp_verified,
                tenant_id=tenant_id,
                actor_id=employee_id,
            )
        )
        return request

    @property
    def requested_time(self) -> datetime:
        """STEP 1-in rəqəmsal möhürü — dəyişdirilə bilməz."""
        return self._requested_time

    # ------------------------------ STEP 2 ---------------------------------- #

    def claim_return(self, *, claimed_at: datetime) -> None:
        """STEP 2 — `[Mən Qayıtdım]`. Status `🟡 Gözləyir` olur."""
        require_aware(claimed_at, field="claimed_at")
        self._require_status(
            LeaveStatus.OUTSIDE,
            action="qayıdış bildirişi",
            hint="Bu düymə yalnız «Xaricdə» vəziyyətində görünür.",
        )
        if claimed_at < self._requested_time:
            raise DomainRuleError(
                "Qayıdış bildirişi icazə vaxtından əvvəl ola bilməz",
                user_message="Sistem vaxtında uyğunsuzluq var. Administratora bildirin.",
            )

        self.return_claimed_time = claimed_at
        self.status = LeaveStatus.PENDING_RETURN_VERIFICATION
        self.record_event(
            LeaveReturnClaimedEvent(
                leave_request_id=self.id,
                employee_id=self.employee_id,
                claimed_at=claimed_at,
                tenant_id=self.tenant_id,
                actor_id=self.employee_id,
            )
        )

    # ------------------------------ STEP 3 ---------------------------------- #

    def verify_return(
        self,
        *,
        operator_id: EmployeeId,
        verified_at: datetime,
        actual_return_time: datetime | None = None,
    ) -> LeavePenalty:
        """STEP 3, Option A — `[Təsdiqlə]`.

        Args:
            verified_at: Operatorun düyməni kliklədiyi an (audit üçün).
            actual_return_time: Faktiki qayıdış anı. `None` olduqda
                `resolved_return_time()` zənciri işə düşür (modul başlığı,
                M-3 DÜZƏLİŞİ). **Cərimə HƏMİŞƏ bu dəyərə əsaslanır,
                `verified_at`-a YOX.**
        """
        require_aware(verified_at, field="verified_at")
        self._require_verifiable()

        actual = actual_return_time or self.resolved_return_time(fallback=verified_at)
        require_aware(actual, field="actual_return_time")

        penalty = calculate_leave_penalty(
            requested_time=self._requested_time,
            actual_return_time=actual,
            allowance_minutes=self.allowance_minutes,
        )

        self.actual_return_time = actual
        self.verified_at = verified_at
        self.verified_by = operator_id
        self.status = LeaveStatus.VERIFIED
        self.penalty = penalty

        self.record_event(
            LeaveVerifiedEvent(
                leave_request_id=self.id,
                employee_id=self.employee_id,
                operator_id=operator_id,
                requested_time=self._requested_time,
                verified_actual_time=actual,
                delay_minutes=penalty.delay_minutes,
                total_minutes=penalty.total_minutes,
                was_manual_override=self.override is not None,
                tenant_id=self.tenant_id,
                actor_id=operator_id,
            )
        )
        return penalty

    def resolved_return_time(self, *, fallback: datetime) -> datetime:
        """Cərimənin bazası olan FAKTİKİ qayıdış anı (M-3, modul başlığı).

        Zəncir — ən güclü siqnatdan ən zəifə:

            1. QÜVVƏDƏ olan manual düzəliş (`is_effective`) — operator kamera
               görüntüsünə baxıb, səbəb yazıb, lazım olubsa ikinci təsdiqi
               alıb. Bu, sistemdəki ən yaxşı sübutdur.
            2. `return_claimed_time` — işçinin STEP 2-dəki PIN handshake-i.
               Fiziki mövcudluq siqnalıdır (mağaza PC-si) və NTP-yə qarşı
               yoxlanılıb.
            3. `fallback` (operatorun klik anı) — YALNIZ 1 və 2 yoxdursa.

        3-cü pillə vəziyyət maşınına görə ƏLÇATMAZDIR: `_require_verifiable`
        yalnız 🟡/⚠️ statuslarını buraxır, hər ikisinə isə ancaq
        `claim_return()` ilə çatılır. O, yalnız köhnə/qüsurlu sətir üçün
        (məs. miqrasiyadan əvvəlki qeyd) müdafiə xəttidir — `None` qaytarıb
        çağıranı `TypeError` ilə partlatmaqdansa müəyyən davranış seçilib.

        TƏSDİQ GÖZLƏYƏN düzəliş 1-ci pilləyə DÜŞMÜR (`is_effective` `False`
        qaytarır) — M-5: gözləmə vəziyyətində ORİJİNAL vaxt keçərlidir.
        """
        require_aware(fallback, field="fallback")
        if self.override is not None and self.override.is_effective:
            return self.override.overridden_time
        if self.return_claimed_time is not None:
            return self.return_claimed_time
        return fallback

    def apply_manual_override(
        self,
        *,
        operator_id: EmployeeId,
        overridden_time: datetime,
        system_time: datetime,
        reason: str,
        dual_control_threshold_minutes: int = 30,
    ) -> ManualOverride:
        """STEP 3, Option B — `[Vaxtı Əllə Təyin Et]`.

        Bölmə 4-dəki DÖRD validasiya qaydası burada tətbiq olunur:
            1. Daxil edilən vaxt sorğu vaxtından əvvəl ola bilməz;
            2. gələcək vaxt qəbul edilmir;
            3. səbəb sahəsi (min. 10 simvol) məcburidir;
            4. 30+ dəqiqəlik override → dual-control qaydasına düşür.
        """
        require_aware(overridden_time, field="overridden_time")
        require_aware(system_time, field="system_time")
        self._require_verifiable()

        # (1)
        if overridden_time < self._requested_time:
            raise DomainRuleError(
                "Override vaxtı sorğu vaxtından əvvəl ola bilməz",
                user_message="Daxil etdiyiniz vaxt icazə vaxtından əvvəldir.",
            )
        # (2)
        if overridden_time > system_time:
            raise DomainRuleError(
                "Gələcək vaxt qəbul edilmir",
                user_message="Gələcək vaxt daxil edilə bilməz.",
            )
        # (3)
        cleaned_reason = normalise_decision_text(reason)
        if len(cleaned_reason) < MIN_OVERRIDE_REASON_LENGTH:
            raise DomainRuleError(
                f"Override səbəbi minimum {MIN_OVERRIDE_REASON_LENGTH} simvol olmalıdır",
                user_message=(f"Səbəb ən azı {MIN_OVERRIDE_REASON_LENGTH} simvol olmalıdır."),
            )
        # (4)
        delta_minutes = int(abs((system_time - overridden_time).total_seconds()) // 60)
        requires_dual_control = delta_minutes >= dual_control_threshold_minutes

        override = ManualOverride(
            operator_id=operator_id,
            system_time=system_time,
            overridden_time=overridden_time,
            reason=cleaned_reason,
            delta_minutes=delta_minutes,
            requires_dual_control=requires_dual_control,
        )
        self.override = override

        self.record_event(
            ManualTimeOverrideEvent(
                leave_request_id=self.id,
                employee_id=self.employee_id,
                operator_id=operator_id,
                system_time=system_time,
                overridden_time=overridden_time,
                delta_minutes=delta_minutes,
                reason=cleaned_reason,
                requires_dual_control=requires_dual_control,
                tenant_id=self.tenant_id,
                actor_id=operator_id,
            )
        )
        return override

    def approve_override(self, *, approver_id: EmployeeId, approved_at: datetime) -> None:
        """Dual-control ikinci təsdiqi.

        Operator öz override-ını ÖZÜ təsdiqləyə bilməz — DB-dəki
        `chk_override_self_approval` ilə eyni qayda, domen qatında da.
        """
        require_aware(approved_at, field="approved_at")
        override = self._require_override()
        if approver_id == override.operator_id:
            raise DomainRuleError(
                "Operator öz override-ını özü təsdiqləyə bilməz (vəzifə ayrılığı)",
                user_message="Öz əməliyyatınızı özünüz təsdiqləyə bilməzsiniz.",
            )
        # RƏDD EDİLMİŞ/LƏĞV OLUNMUŞ SORĞU DİRİLDİLMİR (M-5). Sükutla təsdiq
        # etmək təsdiqçiyə "düzəliş qüvvəyə mindi" demək olardı, halbuki
        # cərimə artıq orijinal vaxta görə hesablanmış ola bilər.
        if override.is_rejected:
            raise InvalidStateTransitionError(
                "Rədd edilmiş və ya müddəti bitmiş vaxt düzəlişi təsdiqlənə bilməz",
                user_message=(
                    "Bu düzəliş sorğusu artıq bağlanıb. Lazımdırsa yenidən düzəliş edin."
                ),
                context={"rejection_reason": override.rejection_reason},
            )
        # TƏSDİQLƏNMİŞ SORĞUYA TƏKRAR TƏSDİQ — vəziyyət maşınında belə keçid
        # nəzərdə tutulmayıb, ona görə sükutla "heç nə etmə" DEYİL, açıq rədd.
        if override.approved_by is not None:
            raise InvalidStateTransitionError(
                "Bu vaxt düzəlişi artıq təsdiqlənib",
                user_message="Bu düzəliş artıq təsdiqlənib.",
                context={"approved_by": str(override.approved_by)},
            )
        # ARTIQ TƏSDİQLƏNMİŞ İCAZƏYƏ SONRADAN GƏLƏN TƏSDİQ (M-5). Cərimə
        # `verify_return` anında YAZILIB; indi gələn təsdiq onu geriyə dönük
        # düzəldə bilməz. İşçinin yolu var və o, spesifikasiyada yazılıb:
        # 72 saatlıq ETİRAZ mexanizmi (bölmə 4).
        if self.status is LeaveStatus.VERIFIED:
            raise InvalidStateTransitionError(
                "İcazə artıq təsdiqlənib — vaxt düzəlişi geriyə dönük tətbiq edilmir",
                user_message=(
                    "Bu icazə artıq təsdiqlənib. Düzəliş üçün cərimə etirazı yolundan "
                    "istifadə edin."
                ),
                context={"status": self.status.value},
            )
        override.approved_by = approver_id
        override.approved_at = approved_at

    def reject_override(
        self, *, approver_id: EmployeeId, rejected_at: datetime, reason: str
    ) -> None:
        """Dual-control «yox» cavabı (M-5).

        Təsdiqçi yalnız «hə» deyə bilsəydi, ikinci təsdiq bir nəzarət deyil,
        formal düymə olardı. Rədd edilən düzəliş SİLİNMİR — `REJECTED` izi ilə
        qalır, çünki "kim nə istədi və kim imtina etdi" sualı sonradan
        cavablana bilməlidir (bölmə 4 AUDIT qaydası).
        """
        override = self._require_override()
        if approver_id == override.operator_id:
            # Öz sorğusunu özü bağlamaq da vəzifə ayrılığını pozardı: operator
            # səhv düzəlişi audit izi olmadan "geri götürə" bilərdi.
            raise DomainRuleError(
                "Operator öz vaxt düzəlişini özü rədd edə bilməz (vəzifə ayrılığı)",
                user_message="Öz sorğunuza özünüz qərar verə bilməzsiniz.",
            )
        if not override.is_pending_approval:
            raise InvalidStateTransitionError(
                "Yalnız ikinci təsdiq gözləyən vaxt düzəlişi rədd edilə bilər",
                user_message="Bu düzəliş sorğusu artıq bağlanıb.",
            )
        override.reject(rejected_by=approver_id, rejected_at=rejected_at, reason=reason)

    def expire_override(self, *, now: datetime, timeout_minutes: int) -> bool:
        """Təsdiqsiz qalmış düzəlişi LƏĞV edir (planlaşdırılmış iş, M-5).

        Bölmə 3 (Dual-Control Deadlock Guard) açıq tələb edir ki, "gözləyən
        override-lar sonsuza qədər təsdiqsiz qalmasın". Guard yalnız
        XƏBƏRDARLIQ edirdi; bu metod həmin tələbin ikinci yarısıdır.

        Returns:
            Ləğv MƏHZ BU çağırışda baş verdisə `True` — çağıran yalnız o zaman
            yazır və bildiriş göndərir (təkrar bildiriş yoxdur).
        """
        require_aware(now, field="now")
        override = self.override
        if override is None or not override.is_pending_approval:
            return False
        waiting = override.waiting_minutes(now=now)
        if waiting < timeout_minutes:
            return False
        override.reject(
            rejected_by=None,  # qərarı insan vermədi — bax `ManualOverride` şərhi
            rejected_at=now,
            reason=(
                f"Təsdiq müddəti bitdi ({waiting} dəqiqə, hədd {timeout_minutes}) — "
                f"sorğu avtomatik ləğv olundu, orijinal vaxt qüvvədə qaldı"
            ),
        )
        return True

    def _require_override(self) -> ManualOverride:
        if self.override is None:
            raise DomainRuleError(
                "Təsdiqlənəcək override yoxdur",
                user_message="Bu sorğuda manual vaxt düzəlişi yoxdur.",
            )
        return self.override

    # ----------------------------- TIMEOUT ---------------------------------- #

    def escalate_timeout(self, *, now: datetime, timeout_minutes: int = 45) -> bool:
        """45 dəqiqəlik timeout eskalasiyası (bölmə 4).

        Returns:
            Eskalasiya BU çağırışda baş verdisə `True` (təkrar bildiriş yox).
        """
        require_aware(now, field="now")
        if self.status is not LeaveStatus.PENDING_RETURN_VERIFICATION:
            return False
        if self.escalated_at is not None:
            return False
        if self.return_claimed_time is None:  # pragma: no cover - invariant
            return False

        waiting = int((now - self.return_claimed_time).total_seconds() // 60)
        if waiting < timeout_minutes:
            return False

        self.escalated_at = now
        self.status = LeaveStatus.TIMEOUT_ESCALATED
        self.record_event(
            VerificationTimeoutEscalatedEvent(
                subject_type="LEAVE_RETURN",
                subject_id=self.id,
                employee_id=self.employee_id,
                store_id=self.store_id,
                waiting_minutes=waiting,
                tenant_id=self.tenant_id,
            )
        )
        return True

    @staticmethod
    def assert_can_resolve_timeout(role: SystemRole) -> None:
        """Timeout-dan sonra kim manual həll edə bilər (bölmə 4).

        `Mağaza_Meneceri` QƏSDƏN istisna edilib — dual-control tiering.
        """
        if role not in TIMEOUT_RESOLVER_ROLES:
            raise DomainRuleError(
                f"'{role.value}' rolu timeout-a düşmüş icazəni həll edə bilməz — "
                f"yalnız HR_Admin/CEO/Root (dual-control tiering, bölmə 4)",
                user_message="Bu əməliyyat üçün HR_Admin və ya CEO səlahiyyəti lazımdır.",
                context={"role": role.value},
            )

    # ------------------------------ köməkçi --------------------------------- #

    def cancel(self, *, reason: str) -> None:
        """İcazəni ləğv edir (məs. işçi səhvən açıb)."""
        if self.status is LeaveStatus.VERIFIED:
            raise InvalidStateTransitionError("Təsdiqlənmiş icazə ləğv edilə bilməz")
        self.status = LeaveStatus.CANCELLED
        self.cancellation_reason = reason

    def _require_status(self, expected: LeaveStatus, *, action: str, hint: str = "") -> None:
        if self.status is not expected:
            raise InvalidStateTransitionError(
                f"'{action}' üçün status '{expected.value}' olmalıdır, "
                f"cari status: '{self.status.value}'",
                user_message=hint or "Bu əməliyyat mövcud vəziyyətdə mümkün deyil.",
                context={"expected": expected.value, "actual": self.status.value},
            )

    def _require_verifiable(self) -> None:
        """Təsdiq/override yalnız 🟡 və ya timeout-a düşmüş sorğuda mümkündür."""
        allowed = (
            LeaveStatus.PENDING_RETURN_VERIFICATION,
            LeaveStatus.TIMEOUT_ESCALATED,
        )
        if self.status not in allowed:
            raise InvalidStateTransitionError(
                f"Təsdiq üçün status {[s.value for s in allowed]} olmalıdır, "
                f"cari: '{self.status.value}'",
                context={"actual": self.status.value},
            )

    def __repr__(self) -> str:
        return (
            f"LeaveRequest(id={self.id}, status={self.status.value}, employee={self.employee_id})"
        )


__all__ = [
    "MIN_OVERRIDE_REASON_LENGTH",
    "TIMEOUT_RESOLVER_ROLES",
    "LeaveRequest",
    "LeaveStatus",
    "ManualOverride",
]
