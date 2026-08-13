"""POS Səlahiyyət Siyasəti (#7, kompasos11.md Faza 4) — sənədləşdirmə/siyasət qeydi.

STRUKTUR QƏRARI A (kompasos11.md): bu use case YALNIZ "bu işçiyə hansı
endirim/ləğv/geri-qaytarma səlahiyyəti rəsmən verilib?" sualının HR/audit
cavabını SAXLAYIR. KompasOS-un öz kassa ekranı yoxdur, 1C-dən əməliyyat
sync-i GÖZLƏNMİR, Vahid İstisna Motoruna (#9) HEÇ NƏ göndərilmir (#7 artıq
mənbə deyil, bax `exception_engine.py` başlığı) və real POS əməliyyatını
yoxlayan/tutan məntiq YOXDUR — yalnız statik siyasət qeydi yazılır/oxunur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ HİYERARXİYA/SELF-ESCALATION MƏNTİQİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
Strict Hierarchy Guard `Employee.outranks()` — məhz `PermissionHierarchyGuardUseCase.
_assert_strict_hierarchy`-nin çağırdığı EYNİ metod — burada TƏKRAR YAZILMIR,
birbaşa çağırılır. `PermissionHierarchyGuardUseCase`-in ÖZÜ işlədilmir, çünki
onun bütün API-si `PermissionFlag` + grant/deny effektinə (fərdi icazə
override-i) qurulub — POS həddi isə flag deyil, rəqəm/bulean cütüdür. Eyni
PRİNSİP (guard-ı çağır, təkrarlama) burada guard-ın ƏSAS metoduna birbaşa
müraciətlə tətbiq olunur.

ROOT ÜÇÜN İSTİSNA YOXDUR (SEC-006-dan fərqli olaraq): `PermissionHierarchyGuardUseCase`
Root-u bərabər-pillə qadağasından azad edir, çünki tenant-ın ilk Root-u
başqasına flag verə bilməlidir (əks halda heç kimə heç nə verə bilməzdi).
POS həddində belə bir "toxum" problemi yoxdur — bu, funksional icazə deyil,
sənəd qeydidir — ona görə qayda HAMIYA (Root daxil) eyni sərtlikdə tətbiq
olunur: "aktor yalnız CİDDİ ŞƏKİLDƏ aşağı pilləyə hədd təyin edə bilər"
(kompasos11.md Faza 4, addım 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA YOXDUR
──────────────────────────────────────────────────────────────────────────────
Əməliyyat YALNIZ `pos_permission_thresholds` aqreqatına toxunur (+ audit,
eyni tranzaksiyada). `morning_check_in.py` başlığındakı meyar: Saga yalnız
BİR NEÇƏ aqreqata toxunan əməliyyat üçün lazımdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from src.domain.entities.pos_threshold import POSPermissionThreshold
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import AuthorizationError
from src.domain.value_objects.identifiers import new_pos_threshold_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        POSThresholdRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Faza 2-də kataloqa əlavə edilmiş flag (migrations/021).
MANAGE_POS_THRESHOLDS_FLAG = "can_manage_pos_thresholds"


class POSThresholdError(KompasOSError):
    """POS həddi əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "POS səlahiyyət qeydi ilə bağlı əməliyyat icra edilə bilmədi."


class POSThresholdNotFoundError(POSThresholdError):
    user_message = "Bu işçi üçün POS səlahiyyət qeydi tapılmadı."


@dataclass(frozen=True)
class POSThresholdDraft:
    """ "POS Səlahiyyət Siyasəti" formasının məzmunu."""

    max_discount_pct: Decimal
    can_void: bool
    can_refund: bool
    note: str | None = None


class POSThresholdUseCase:
    """`can_manage_pos_thresholds` sahibi işçi başına POS həddini yazır/oxuyur."""

    def __init__(
        self,
        *,
        thresholds: POSThresholdRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._thresholds = thresholds
        self._limits = limits
        self._audit = audit
        self._clock = clock

    # -------------------------------- oxuma ------------------------------------ #

    def get_threshold(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId
    ) -> POSPermissionThreshold | None:
        """Cari sənəd — dialoqun ilkin doldurulması üçün (sətir yoxdursa `None`)."""
        self._require_permission(actor, tenant_id)
        return self._thresholds.get_for_employee(tenant_id, employee_id)

    def discount_ceiling(self, tenant_id: TenantId) -> Decimal:
        """Ekranın "hədd" ipucu üçün cari `POS_MAX_DISCOUNT_PCT_CEILING`."""
        return self._discount_ceiling(tenant_id)

    # -------------------------------- yazı ------------------------------------- #

    def set_threshold(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        subject: Employee,
        draft: POSThresholdDraft,
    ) -> POSPermissionThreshold:
        """Həddi təyin edir/yeniləyir (yaradır YA DA UPSERT edir) — audit MƏCBURİ."""
        self._require_permission(actor, tenant_id)
        self._require_not_self(actor, subject)
        self._require_hierarchy(actor, subject)
        self._require_same_tenant(subject, tenant_id)

        ceiling = self._discount_ceiling(tenant_id)
        now = self._clock.now()
        existing = self._thresholds.get_for_employee(tenant_id, subject.id)
        before_state = _snapshot(existing)

        if existing is not None:
            threshold = existing
        else:
            # Sıfır/False dəyərlərlə qurulur — HƏQİQİ dəyərlər dərhal
            # aşağıdakı `set_threshold()` çağırışı ilə tətbiq olunur ki,
            # YARADILMA yolu da YENİLƏMƏ yolu ilə EYNİ tavan yoxlamasından
            # keçsin (ikili validasiya məntiqi yaranmasın).
            threshold = POSPermissionThreshold(
                threshold_id=new_pos_threshold_id(),
                tenant_id=tenant_id,
                employee_id=subject.id,
                max_discount_pct=Decimal("0"),
                can_void=False,
                can_refund=False,
                note=None,
                updated_by=actor.id,
                created_at=now,
                updated_at=now,
            )

        threshold.set_threshold(
            max_discount_pct=draft.max_discount_pct,
            can_void=draft.can_void,
            can_refund=draft.can_refund,
            note=draft.note,
            updated_by=actor.id,
            now=now,
            ceiling_pct=ceiling,
        )

        self._thresholds.save(threshold)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POS_THRESHOLD_SET",
            entity_type="pos_permission_thresholds",
            entity_id=threshold.id,
            before_state=before_state,
            after_state=_snapshot(threshold),
            reason=threshold.note,
        )
        return threshold

    def revoke_threshold(
        self, *, tenant_id: TenantId, actor: Employee, subject: Employee
    ) -> POSPermissionThreshold:
        """Səlahiyyəti geri alır (soft delete — sətir SİLİNMİR, migrations/018)."""
        self._require_permission(actor, tenant_id)
        self._require_not_self(actor, subject)
        self._require_hierarchy(actor, subject)
        self._require_same_tenant(subject, tenant_id)

        threshold = self._thresholds.get_for_employee(tenant_id, subject.id)
        if threshold is None:
            raise POSThresholdNotFoundError(
                "Geri alınacaq POS həddi tapılmadı",
                context={"employee_id": str(subject.id)},
            )
        before_state = _snapshot(threshold)
        threshold.revoke(deactivated_by=actor.id, now=self._clock.now())
        self._thresholds.save(threshold)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POS_THRESHOLD_REVOKED",
            entity_type="pos_permission_thresholds",
            entity_id=threshold.id,
            before_state=before_state,
            after_state=_snapshot(threshold),
        )
        return threshold

    # ------------------------------- köməkçi ------------------------------------ #

    def _require_permission(self, actor: Employee, tenant_id: TenantId) -> None:
        if actor.tenant_id != tenant_id:
            # Üçüncü izolyasiya qatı (RLS və repo `tenant_id` şərtindən sonra).
            raise AuthorizationError(
                "Aktor bu kirayəçiyə aid deyil",
                context={"actor_id": str(actor.id)},
            )
        now = self._clock.now()
        if not actor.has_permission(MANAGE_POS_THRESHOLDS_FLAG, now=now):
            _security_log.warning(
                "POS_THRESHOLD_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_POS_THRESHOLDS_FLAG},
            )
            raise AuthorizationError(
                f"«{MANAGE_POS_THRESHOLDS_FLAG}» səlahiyyəti yoxdur",
                context={"flag": MANAGE_POS_THRESHOLDS_FLAG},
            )

    def _require_not_self(self, actor: Employee, subject: Employee) -> None:
        """SELF-ESCALATION GUARD: aktor öz-özünə hədd təyin edə bilməz."""
        if actor.id == subject.id:
            _security_log.warning(
                "POS_THRESHOLD_SELF_ASSIGNMENT_BLOCKED",
                extra={"actor_id": str(actor.id)},
            )
            raise AuthorizationError(
                "SELF-ESCALATION GUARD: aktor öz POS həddini təyin edə bilməz",
                user_message="Özünüzə POS səlahiyyəti təyin edə bilməzsiniz.",
                context={"actor_id": str(actor.id)},
            )

    def _require_hierarchy(self, actor: Employee, subject: Employee) -> None:
        """Strict Hierarchy Guard — `Employee.outranks()` birbaşa çağırılır."""
        if not actor.outranks(subject):
            _security_log.warning(
                "POS_THRESHOLD_HIERARCHY_DENIED",
                extra={"actor_id": str(actor.id), "subject_id": str(subject.id)},
            )
            raise AuthorizationError(
                "STRICT HIERARCHY GUARD: yalnız CİDDİ ŞƏKİLDƏ aşağı pilləyə "
                "POS həddi təyin edilə bilər",
                user_message=("Bu işçi sizinlə eyni və ya daha yüksək səlahiyyət pilləsindədir."),
                context={"actor_id": str(actor.id), "subject_id": str(subject.id)},
            )

    def _require_same_tenant(self, subject: Employee, tenant_id: TenantId) -> None:
        if subject.tenant_id != tenant_id:
            raise AuthorizationError(
                "Hədəf işçi bu kirayəçiyə aid deyil",
                context={"subject_id": str(subject.id)},
            )

    def _discount_ceiling(self, tenant_id: TenantId) -> Decimal:
        """`POS_MAX_DISCOUNT_PCT_CEILING` — Root-dan idarə olunan yuxarı sərhəd.

        DB `CHECK`-i 0–100 arasındadır (sxem sərhədi, dəyişməz); bu isə
        ƏLAVƏ, Root-un öz biznes qərarı ilə daha da sərtləşdirə biləcəyi
        həddir. Fallback `DEFAULT_LIMITS`-dədir (bax `policies.py`).
        """
        key = SystemLimitKey.POS_MAX_DISCOUNT_PCT_CEILING
        raw = self._limits.get_str(tenant_id, key.value, str(DEFAULT_LIMITS[key]))
        try:
            return Decimal(str(raw).strip().replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(str(DEFAULT_LIMITS[key]))


def _snapshot(threshold: POSPermissionThreshold | None) -> dict[str, object] | None:
    if threshold is None:
        return None
    return {
        "max_discount_pct": str(threshold.max_discount_pct),
        "can_void": threshold.can_void,
        "can_refund": threshold.can_refund,
        "note": threshold.note,
        "is_active": threshold.is_active,
    }


__all__ = [
    "MANAGE_POS_THRESHOLDS_FLAG",
    "POSThresholdDraft",
    "POSThresholdError",
    "POSThresholdNotFoundError",
    "POSThresholdUseCase",
]
