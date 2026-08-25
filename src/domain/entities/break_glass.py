"""Break-glass fövqəladə giriş — `v2backlog.md` Faza 5.4.

    "ROOT PARAMETRİ: ikinci-etibarlı-şəxs + vaxt-məhdud «böhran-açarı»
     mexanizmi — Root əlçatmaz olanda, ƏVVƏLCƏDƏN təyin edilmiş bir ehtiyat-
     admin, xüsusi audit-lənən bir axınla müvəqqəti Root-səlahiyyəti ala
     bilir. Bu, YÜKSƏK-RİSKLİ bir funksiyadır — hər istifadə mərkəzi vendor
     bazasına da yazılsın."

──────────────────────────────────────────────────────────────────────────────
ÜÇ QAYDA KODDA SABİTDİR — ROOT ONLARI SÖNDÜRƏ BİLMİR
──────────────────────────────────────────────────────────────────────────────
1. **Sorğu verən ƏVVƏLCƏDƏN təyin edilmiş ehtiyat-admin olmalıdır.** Böhran
   anında reyestrə əlavə etmək mümkün deyil (`can_manage_break_glass` YALNIZ
   Root-dadır) — mexanizmin bütün təhlükəsizliyi bu ardıcıllıqdadır.
2. **İkinci şəxs tələb olunur və o, sorğuçunun ÖZÜ ola bilməz.** Qayda İKİ
   yerdədir: burada və DB-də (`chk_break_glass_not_self`, migrations/099) —
   CLAUDE.md §5.
3. **Səlahiyyət VAXT-MƏHDUDDUR.** `expires_at` təsdiq anında hesablanır və
   sonradan UZADILA BİLMİR: uzatma metodu olsaydı, «müvəqqəti» səlahiyyət
   təkrar uzatmalarla daimi səlahiyyətə çevrilərdi. Lazım olarsa YENİ sorğu
   verilir — və o, aylıq tavana (`BREAK_GLASS_MAX_GRANTS_PER_MONTH`) düşür.

Root YALNIZ ƏDƏDLƏRİ tənzimləyir (müddət, təsdiq pəncərəsi, aylıq tavan).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `SystemRole.ROOT` VERİLMİR, «MÜVƏQQƏTİ SƏLAHİYYƏT» VERİLİR
──────────────────────────────────────────────────────────────────────────────
İşçinin `position`-u DƏYİŞDİRİLMİR. Səbəb: rol dəyişikliyi `positions`/
`position_permissions` üzərindən gedir və orada iz «kim vəzifəni dəyişdi»
kimi qalır — geri qaytarılması unudulsa səlahiyyət ƏBƏDİ qalar. Break-glass
sətri isə ÖZÜ vaxt daşıyır: `is_effective_at()` hər yoxlamada vaxtı ölçür,
yəni «geri qaytarmağı unutmaq» MÜMKÜN DEYİL.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import BreakGlassDecidedEvent, BreakGlassRequestedEvent
from src.domain.value_objects.identifiers import (
    BreakGlassGrantId,
    BreakGlassTrusteeId,
    EmployeeId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: `break_glass_grants.reason` — DB `CHECK (char_length(trim(reason)) >= 10)`.
#: `MIN_TRANSFER_REASON_LENGTH` (5) DEYİL: bu sətir audit sənədidir və «test»
#: kimi bir söz onu oxunmaz edərdi. `MIN_TRANSFER_DECISION_REASON_LENGTH` ilə
#: eyni standart.
MIN_BREAK_GLASS_REASON_LENGTH: Final[int] = 10

#: Rədd/dayandırma izahı — sorğu səbəbi ilə EYNİ standart, çünki hər ikisi
#: eyni audit sətrində yan-yana oxunur.
MIN_BREAK_GLASS_DECISION_REASON_LENGTH: Final[int] = 10


class BreakGlassStatus(str, Enum):
    """`break_glass_grants.status` — DB `CHECK` siyahısı ilə EYNİ.

    `StrEnum` DEYİL, `str, Enum` (CLAUDE.md §4): `str(X)` nəticəsi audit/log
    çıxışına düşür.
    """

    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"

    @property
    def is_terminal(self) -> bool:
        """Sətir bir daha dəyişməzmi.

        `ACTIVE` TERMİNAL DEYİL: o, ya vaxtı çatıb `EXPIRED` olacaq, ya da
        Root qayıdıb `REVOKED` edəcək.
        """
        return self in (
            BreakGlassStatus.EXPIRED,
            BreakGlassStatus.REJECTED,
            BreakGlassStatus.REVOKED,
        )


class BreakGlassTrustee:
    """Reyestr sətri — «bu işçi böhran anında fövqəladə səlahiyyət istəyə bilər».

    `AggregateRoot` DEYİL, sadə dəyər daşıyıcısıdır: reyestrin öz həyat
    dövrəsi yoxdur (yaradılır və ləğv edilir), hadisə yaymır — təyinatın
    özü `AuditTrail.record()` ilə yazılır, çünki auditoriyası bildiriş
    almalı işçilər deyil, AUDİT jurnalıdır.
    """

    def __init__(
        self,
        *,
        trustee_id: BreakGlassTrusteeId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        designated_by: EmployeeId,
        designated_at: datetime,
        is_active: bool = True,
        revoked_by: EmployeeId | None = None,
        revoked_at: datetime | None = None,
    ) -> None:
        if employee_id == designated_by:
            # Root özünü ehtiyat-admin təyin edə bilməz: mexanizm məhz
            # Root-un ƏLÇATMAZ olduğu hal üçündür — Root-un özü siyahıda
            # olsaydı, sətir heç bir yeni yol açmazdı və yalnız «Root özünə
            # ikinci qapı açdı» kimi görünərdi.
            raise DomainRuleError(
                "Root özünü ehtiyat-admin təyin edə bilməz",
                user_message="Ehtiyat-admin olaraq BAŞQA bir işçi seçin.",
                context={"employee_id": str(employee_id)},
            )
        self.id = trustee_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.designated_by = designated_by
        self.designated_at = require_aware(designated_at, field="designated_at")
        self.is_active = is_active
        self.revoked_by = revoked_by
        self.revoked_at = (
            require_aware(revoked_at, field="revoked_at") if revoked_at is not None else None
        )
        # DB `chk_trustee_revocation` güzgüsü (CLAUDE.md §5).
        if self.is_active != (self.revoked_at is None):
            raise DomainRuleError(
                "Ehtiyat-admin sətrinin ləğv vəziyyəti ziddiyyətlidir",
                user_message="Ehtiyat-admin siyahısı düzgün oxunmadı.",
            )

    def revoke(self, *, revoked_by: EmployeeId, revoked_at: datetime) -> None:
        """Təyinatı ləğv edir — sətir SİLİNMİR (soft delete, `catalogs.py` naxışı)."""
        require_aware(revoked_at, field="revoked_at")
        if not self.is_active:
            raise DomainRuleError(
                "Ehtiyat-admin təyinatı artıq ləğv edilib",
                user_message="Bu işçi artıq ehtiyat-admin deyil.",
                context={"employee_id": str(self.employee_id)},
            )
        self.is_active = False
        self.revoked_by = revoked_by
        self.revoked_at = revoked_at

    def __repr__(self) -> str:
        state = "aktiv" if self.is_active else "ləğv edilib"
        return f"<BreakGlassTrustee {self.employee_id} {state}>"


class BreakGlassGrant(AggregateRoot):
    """Fövqəladə səlahiyyətin BİR istifadəsi.

        PENDING_APPROVAL ──approve(ikinci şəxs)──> ACTIVE ──vaxt──> EXPIRED
                 │                                    │
                 ├──reject(səbəb)──> REJECTED         └──revoke()──> REVOKED
                 │
                 └──təsdiq pəncərəsi keçdi──> EXPIRED  (`expire_if_unapproved`)

    Təsdiqlənməmiş sorğu da `EXPIRED` olur, `REJECTED` YOX: rədd bir İNSANIN
    qərarıdır və auditdə belə oxunmalıdır; cavabsız qalmış sorğu isə heç
    kimin qərarı deyil. İkisini eyni statusa yığmaq «kim rədd etdi?» sualını
    yalan cavabla doldurardı.
    """

    def __init__(
        self,
        *,
        grant_id: BreakGlassGrantId,
        tenant_id: TenantId,
        requested_by: EmployeeId,
        reason: str,
        requested_at: datetime,
        approval_expires_at: datetime,
        status: BreakGlassStatus = BreakGlassStatus.PENDING_APPROVAL,
        approved_by: EmployeeId | None = None,
        approved_at: datetime | None = None,
        expires_at: datetime | None = None,
        revoked_by: EmployeeId | None = None,
        revoked_at: datetime | None = None,
        vendor_synced_at: datetime | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_BREAK_GLASS_REASON_LENGTH:
            raise DomainRuleError(
                f"Fövqəladə giriş səbəbi minimum {MIN_BREAK_GLASS_REASON_LENGTH} simvol olmalıdır",
                user_message=(
                    "Fövqəladə girişin səbəbini ətraflı yazın — bu mətn audit "
                    "jurnalına düşür və vendor bazasına göndərilir."
                ),
                context={"length": len(cleaned)},
            )

        self.id = grant_id
        self.tenant_id = tenant_id
        self.requested_by = requested_by
        self.reason = cleaned
        self.requested_at = require_aware(requested_at, field="requested_at")
        self.approval_expires_at = require_aware(approval_expires_at, field="approval_expires_at")
        self.status = status
        self.approved_by = approved_by
        self.approved_at = (
            require_aware(approved_at, field="approved_at") if approved_at is not None else None
        )
        self.expires_at = (
            require_aware(expires_at, field="expires_at") if expires_at is not None else None
        )
        self.revoked_by = revoked_by
        self.revoked_at = (
            require_aware(revoked_at, field="revoked_at") if revoked_at is not None else None
        )
        self.vendor_synced_at = (
            require_aware(vendor_synced_at, field="vendor_synced_at")
            if vendor_synced_at is not None
            else None
        )

        # Repository-dən BƏRPA edilən aqreqat hadisə YAYMAMALIDIR (CLAUDE.md §3).
        if emit_created_event and status is BreakGlassStatus.PENDING_APPROVAL:
            self.record_event(
                BreakGlassRequestedEvent(
                    tenant_id=tenant_id,
                    actor_id=requested_by,
                    grant_id=grant_id,
                    requested_by=requested_by,
                    reason=cleaned,
                    approval_expires_at=self.approval_expires_at,
                )
            )

    # ------------------------------ SORĞU ----------------------------------- #

    def is_effective_at(self, moment: datetime) -> bool:
        """Səlahiyyət BU ANDA qüvvədədirmi.

        STATUS TƏK BAŞINA KİFAYƏT ETMİR: `ACTIVE` sətir vaxtı keçmiş ola
        bilər və gecəlik iş hələ onu `EXPIRED`-ə çevirməmiş ola bilər. Vaxt
        yoxlaması BURADA, hər çağırışda edilir — «planlayıcı işləməyibsə
        səlahiyyət qüvvədə qalsın» davranışı break-glass-ı sonsuz səlahiyyətə
        çevirərdi.
        """
        require_aware(moment, field="moment")
        if self.status is not BreakGlassStatus.ACTIVE:
            return False
        if self.expires_at is None:  # pragma: no cover — `chk_break_glass_approval` mane olur
            return False
        return moment < self.expires_at

    @property
    def is_pending(self) -> bool:
        return self.status is BreakGlassStatus.PENDING_APPROVAL

    # ------------------------------ QƏRAR ----------------------------------- #

    def approve(
        self,
        *,
        approver_id: EmployeeId,
        approved_at: datetime,
        duration_minutes: int,
    ) -> None:
        """İkinci-etibarlı şəxs təsdiqləyir — səlahiyyət BU ANDAN başlayır.

        `duration_minutes` ÇAĞIRANDAN gəlir (`BREAK_GLASS_MAX_DURATION_MINUTES`,
        Root parametri) və `expires_at` BURADA — təsdiq anında — hesablanır,
        sorğu anında yox: sorğu ilə təsdiq arasında keçən müddət səlahiyyətin
        faktiki müddətini yeməməlidir.
        """
        require_aware(approved_at, field="approved_at")
        self._require_pending()
        if approver_id == self.requested_by:
            raise DomainRuleError(
                "Fövqəladə girişi sorğu verən şəxs özü təsdiqləyə bilməz",
                user_message="Fövqəladə girişi BAŞQA bir etibarlı şəxs təsdiqləməlidir.",
                context={"employee_id": str(approver_id)},
            )
        if approved_at > self.approval_expires_at:
            raise DomainRuleError(
                "Təsdiq pəncərəsi bağlanıb",
                user_message=("Təsdiq vaxtı keçib. Fövqəladə giriş üçün yeni sorğu göndərin."),
                context={"approval_expires_at": self.approval_expires_at.isoformat()},
            )
        if duration_minutes <= 0:
            raise DomainRuleError(
                "Fövqəladə səlahiyyət müddəti müsbət olmalıdır",
                user_message="Sistem parametrləri düzgün deyil — Root ilə əlaqə saxlayın.",
                context={"duration_minutes": duration_minutes},
            )

        self.status = BreakGlassStatus.ACTIVE
        self.approved_by = approver_id
        self.approved_at = approved_at
        self.expires_at = approved_at + timedelta(minutes=duration_minutes)
        self._record_decision(approver_id=approver_id, approved=True, reason=None)

    def reject(self, *, approver_id: EmployeeId, decided_at: datetime, reason: str) -> None:
        """İkinci-etibarlı şəxs RƏDD edir — sətir qalır, səbəb yazılır."""
        require_aware(decided_at, field="decided_at")
        self._require_pending()
        if approver_id == self.requested_by:
            raise DomainRuleError(
                "Fövqəladə girişi sorğu verən şəxs özü rədd edə bilməz",
                user_message="Bu sorğunu BAŞQA bir etibarlı şəxs qərara bağlamalıdır.",
                context={"employee_id": str(approver_id)},
            )
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_BREAK_GLASS_DECISION_REASON_LENGTH:
            raise DomainRuleError(
                f"Rədd səbəbi minimum {MIN_BREAK_GLASS_DECISION_REASON_LENGTH} simvol olmalıdır",
                user_message="Rədd səbəbini ətraflı yazın.",
                context={"length": len(cleaned)},
            )

        self.status = BreakGlassStatus.REJECTED
        self.approved_by = approver_id
        self._record_decision(approver_id=approver_id, approved=False, reason=cleaned)

    def expire_if_unapproved(self, *, moment: datetime) -> bool:
        """Təsdiq pəncərəsi keçmiş sorğunu bağlayır. Qaytarır: dəyişdimi.

        Bu metod PLANLAYICI üçündür (`job_runner`), lakin `is_effective_at()`
        ondan ASILI DEYİL — planlayıcı gecikəndə də səlahiyyət verilmir.
        Metodun mövcudluq səbəbi audit təmizliyidir: cavabsız qalmış sorğu
        əbədi «gözləyir» görünsəydi, ekranda həqiqi gözləyən sorğular
        arasında itərdi (`can_approve_shift_swap` dərsi).
        """
        require_aware(moment, field="moment")
        if not self.is_pending or moment <= self.approval_expires_at:
            return False
        self.status = BreakGlassStatus.EXPIRED
        return True

    def expire_if_elapsed(self, *, moment: datetime) -> bool:
        """Vaxtı çatmış AKTİV səlahiyyəti bağlayır. Qaytarır: dəyişdimi."""
        require_aware(moment, field="moment")
        if self.status is not BreakGlassStatus.ACTIVE:
            return False
        if self.expires_at is None or moment < self.expires_at:
            return False
        self.status = BreakGlassStatus.EXPIRED
        return True

    def revoke(self, *, revoked_by: EmployeeId, revoked_at: datetime, reason: str) -> None:
        """Root qayıdıb aktiv səlahiyyəti VAXTINDAN ƏVVƏL dayandırır."""
        require_aware(revoked_at, field="revoked_at")
        if self.status is not BreakGlassStatus.ACTIVE:
            raise DomainRuleError(
                "Yalnız aktiv fövqəladə səlahiyyət dayandırıla bilər",
                user_message="Bu səlahiyyət artıq aktiv deyil.",
                context={"status": self.status.value},
            )
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_BREAK_GLASS_DECISION_REASON_LENGTH:
            raise DomainRuleError(
                f"Dayandırma səbəbi minimum "
                f"{MIN_BREAK_GLASS_DECISION_REASON_LENGTH} simvol olmalıdır",
                user_message="Dayandırma səbəbini ətraflı yazın.",
                context={"length": len(cleaned)},
            )

        self.status = BreakGlassStatus.REVOKED
        self.revoked_by = revoked_by
        self.revoked_at = revoked_at
        self._record_decision(approver_id=revoked_by, approved=False, reason=cleaned)

    def mark_vendor_synced(self, *, synced_at: datetime) -> None:
        """Mərkəzi vendor bazasına yazıldı.

        İDEMPOTENT: təkrar çağırış ilk anı SAXLAYIR. Gecəlik təkrar-cəhd işi
        eyni sətri iki dəfə göndərsə, «nə vaxt bildirildi» cavabı sürüşməməlidir.
        """
        require_aware(synced_at, field="synced_at")
        if self.vendor_synced_at is None:
            self.vendor_synced_at = synced_at

    # ------------------------------ DAXİLİ ---------------------------------- #

    def _require_pending(self) -> None:
        if not self.is_pending:
            raise DomainRuleError(
                "Fövqəladə giriş sorğusu artıq qərara bağlanıb",
                user_message="Bu sorğu artıq cavablandırılıb.",
                context={"status": self.status.value},
            )

    def _record_decision(
        self, *, approver_id: EmployeeId, approved: bool, reason: str | None
    ) -> None:
        self.record_event(
            BreakGlassDecidedEvent(
                tenant_id=self.tenant_id,
                actor_id=approver_id,
                grant_id=self.id,
                approver_id=approver_id,
                approved=approved,
                reason=reason,
                expires_at=self.expires_at,
            )
        )

    def __repr__(self) -> str:
        return f"<BreakGlassGrant {self.id} {self.status.value}>"
