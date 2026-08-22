"""İcazə qoruyucuları (spesifikasiya bölmə 3) — Faza 2.4.

BURADA TƏTBİQ OLUNAN DÖRD QAYDA:

1. **Strict Hierarchy Guard** — aktor YALNIZ öz iyerarxiya pilləsindən CİDDİ
   ŞƏKİLDƏ aşağı istifadəçilərə toxuna bilər. Bərabər pillə (məs. `Admin` →
   digər `Admin`, `CEO` → digər `CEO`) BLOKLANIR. Yeganə istisna: `Root`
   (SEC-006) — əks halda tenant-ın ilk Root-u heç kimə icazə verə bilməzdi.

2. **Self-Escalation Guard** — aktor yalnız ÖZÜNDƏ AKTİV OLAN flag-i başqasına
   verə bilər; öz hesabına heç nə əlavə edə bilməz.

3. **Hardlock** — dörd-səviyyəli iyerarxiya (`HardlockLevel`).

4. **Anti-fraud vəzifə ayrılığı** — kamera flag-ləri və dual-control təsdiqi.

Bu qaydalar HARDCODED-dır: Feature Toggle ilə söndürülə bilməz (bölmə 3).
DB tərəfində eyni qaydalar trigger kimi təkrarlanır (defense-in-depth).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionEffect,
    PermissionFlag,
    SystemRole,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.interfaces.ports import AuditTrail, Clock, SecurityEventRepository
    from src.domain.value_objects.identifiers import TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Fərdi override tətbiq etmək üçün lazım olan flag (bölmə 3).
CONTROL_PERMISSIONS_FLAG = "can_control_user_permissions"


class PermissionAuditUnavailableError(KompasOSError):
    """İcazə dəyişikliyi audit mənbəyi olmadan tətbiq edilə bilməz."""

    user_message = "Sistem konfiqurasiyası natamamdır — dəyişiklik yazıla bilmədi."


@dataclass(frozen=True)
class PermissionChangeRequest:
    """Bir fərdi grant/deny cəhdi."""

    actor: Employee
    subject: Employee
    flag: PermissionFlag
    effect: PermissionEffect
    now: datetime
    expires_at: datetime | None = None
    reason: str | None = None


class PermissionHierarchyGuardUseCase:
    """İcazə dəyişikliyinin bütün struktur qaydalarını yoxlayır.

    İstifadə::

        guard = PermissionHierarchyGuardUseCase(audit=audit, clock=clock)
        guard.assert_allowed(request)      # istisna atır
        # və ya
        if guard.is_allowed(request): ...  # UI-da elementi gizlətmək üçün

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `AuditTrail` MƏCBURİDİR
    ──────────────────────────────────────────────────────────────────────────
    Bölmə 3 (sətir 86): «Bütün rol/icazə yaratma, dəyişdirmə, silmə
    əməliyyatları `audit_logs`-da tam detallı qeyd olunur (kim, hansı flag,
    kimə, əvvəl/sonra)». Əvvəl bu sinif YALNIZ `security.log`-a yazırdı —
    o isə fayl-əsaslıdır və `audit_logs`-un DB-səviyyəli append-only
    zəmanətini (`schema.sql` §26) DAŞIMIR. Yəni sistemin ən həssas
    əməliyyatı — kimin nəyi kimə verməsi — auditdən kənarda qalırdı.

    `audit` istəyə görədir (`None`) yalnız ona görə ki, `is_allowed()` UI-da
    element gizlətmək üçün çağırılır və orada yazı olmamalıdır. `apply()` isə
    audit olmadan çağırılarsa istisna atır — məcburi olan bir şeyin sükutla
    buraxılması onu məcburi olmaqdan çıxarır (bölmə 5).
    """

    def __init__(
        self,
        *,
        audit: AuditTrail | None = None,
        clock: Clock | None = None,
        security_events: SecurityEventRepository | None = None,
    ) -> None:
        self._audit = audit
        self._clock = clock
        # `audit` İLƏ EYNİ NAXIŞ, EYNİ SƏBƏBDƏN OPSİONALDIR (SEC-7): bu sinfin
        # TƏK instansı HƏM `is_allowed()` (UI-da elementi gizlətmək üçün,
        # sükutla `bool` qaytarır — real "cəhd" DEYİL, render-zamanı
        # qabiliyyət yoxlamasıdır), HƏM `apply()` (real yazma) tərəfindən
        # işlədilir. `security_events`-i BURADA, ümumi `_deny()`-də yazsaydıq,
        # HƏR gizlədilən menyu maddəsi "PERMISSION_CHANGE_DENIED" hadisəsi
        # kimi qeydə düşərdi — bu, siyahını mənasız SƏS-KÜYLƏ doldurardı və
        # HƏQİQİ rədd cəhdlərini gizlədərdi. Ona görə yazı YALNIZ `apply()`-in
        # ÖZÜNDƏ, `assert_allowed()` istisna ATANDA baş verir (aşağı).
        self._security_events = security_events

    def assert_allowed(self, request: PermissionChangeRequest) -> None:
        """Bütün qoruyucuları sıra ilə tətbiq edir."""
        self._assert_actor_may_manage_permissions(request)
        self._assert_not_self(request)
        self._assert_strict_hierarchy(request)
        self._assert_actor_owns_flag(request)
        self._assert_flag_grantable_to_subject(request)

        _security_log.info(
            "PERMISSION_CHANGE_AUTHORISED",
            extra={
                "actor_id": str(request.actor.id),
                "subject_id": str(request.subject.id),
                "flag": request.flag.code,
                "effect": request.effect.value,
            },
        )

    def is_allowed(self, request: PermissionChangeRequest) -> bool:
        try:
            self.assert_allowed(request)
        except AuthorizationError:
            return False
        return True

    def apply(
        self, request: PermissionChangeRequest, *, tenant_id: TenantId | None = None
    ) -> PermissionOverride:
        """Yoxlayır, override-ı tətbiq edir və AUDİT-ə yazır.

        Raises:
            PermissionAuditUnavailableError: `audit` verilməyibsə. Səssiz
                davam etmək bölmə 3-ün audit tələbini sükutla pozardı.
        """
        try:
            self.assert_allowed(request)
        except AuthorizationError as exc:
            # SEC-7, Tier 2: BURADA yazılır, ümumi `_deny()`-də YOX — bax
            # konstruktorun şərhi (səs-küy qarşısı).
            if self._security_events is not None:
                self._security_events.record(
                    tenant_id=(tenant_id if tenant_id is not None else request.subject.tenant_id),
                    event_type="PERMISSION_CHANGE_DENIED",
                    employee_id=request.actor.id,
                    details={
                        **exc.context,
                        "subject_id": str(request.subject.id),
                        "effect": request.effect.value,
                    },
                )
            raise
        if self._audit is None or self._clock is None:
            raise PermissionAuditUnavailableError(
                "İcazə dəyişikliyi audit mənbəyi olmadan tətbiq edilə bilməz",
                context={"flag": request.flag.code},
            )

        before = request.subject.has_permission(request.flag.code, now=request.now)
        override = PermissionOverride(
            flag_code=request.flag.code,
            effect=request.effect,
            granted_by=request.actor.id,
            expires_at=request.expires_at,
        )
        request.subject.apply_override(override)

        self._audit.record(
            tenant_id=tenant_id if tenant_id is not None else request.subject.tenant_id,
            actor_id=request.actor.id,
            action="PERMISSION_OVERRIDE_APPLIED",
            entity_type="user_permission_overrides",
            entity_id=request.subject.id,
            before_state={"flag": request.flag.code, "effective": before},
            after_state={
                "flag": request.flag.code,
                "effect": request.effect.value,
                "effective": request.subject.has_permission(request.flag.code, now=request.now),
                "expires_at": (request.expires_at.isoformat() if request.expires_at else None),
            },
            reason=request.reason,
        )
        return override

    # ------------------------------ qaydalar -------------------------------- #

    def _assert_actor_may_manage_permissions(self, request: PermissionChangeRequest) -> None:
        actor_role = request.actor.position.effective_system_role
        if actor_role in (SystemRole.ROOT, SystemRole.CEO):
            return
        if not request.actor.has_permission(CONTROL_PERMISSIONS_FLAG, now=request.now):
            self._deny(
                request,
                reason="MISSING_CONTROL_FLAG",
                message=(
                    f"'{CONTROL_PERMISSIONS_FLAG}' flag-i olmadan başqasının "
                    f"icazələrini dəyişmək olmaz"
                ),
            )

    def _assert_not_self(self, request: PermissionChangeRequest) -> None:
        """SELF-ESCALATION GUARD, 1-ci hissə: özünə toxunmaq qadağandır."""
        if request.actor.id == request.subject.id:
            self._deny(
                request,
                reason="SELF_EDIT",
                message=(
                    "SELF-ESCALATION GUARD: istifadəçi öz icazələrini dəyişə bilməz (bölmə 3)"
                ),
                user_message="Öz icazələrinizi dəyişə bilməzsiniz.",
            )

    def _assert_strict_hierarchy(self, request: PermissionChangeRequest) -> None:
        """STRICT HIERARCHY GUARD — bərabər pillə də bloklanır (SEC-006)."""
        actor_role = request.actor.position.effective_system_role
        # SEC-006: yalnız ROOT bərabər-pillə qaydasından azaddır.
        if actor_role is SystemRole.ROOT:
            return

        if not request.actor.outranks(request.subject):
            self._deny(
                request,
                reason="HIERARCHY",
                message=(
                    f"STRICT HIERARCHY GUARD: yalnız CİDDİ ŞƏKİLDƏ aşağı pilləyə "
                    f"toxunmaq olar (aktor={request.actor.priority.name}, "
                    f"hədəf={request.subject.priority.name})"
                ),
                user_message=(
                    "Bu istifadəçi sizinlə eyni və ya daha yüksək səlahiyyət pilləsindədir."
                ),
            )

    def _assert_actor_owns_flag(self, request: PermissionChangeRequest) -> None:
        """SELF-ESCALATION GUARD, 2-ci hissə: özündə olmayan flag-i verə bilməz.

        DENY üçün tətbiq OLUNMUR — icazəni GERİ ALMAQ səlahiyyət artırması
        deyil, ona görə aktorun həmin flag-ə sahib olması tələb edilmir.
        """
        if request.effect is PermissionEffect.DENY:
            return
        actor_role = request.actor.position.effective_system_role
        if actor_role is SystemRole.ROOT:
            return

        if not request.actor.has_permission(request.flag.code, now=request.now):
            self._deny(
                request,
                reason="FLAG_NOT_OWNED",
                message=(
                    f"SELF-ESCALATION GUARD: '{request.flag.code}' flag-i aktorda "
                    f"aktiv deyil — özündə olmayan icazəni başqasına verə bilməz"
                ),
                user_message="Özünüzdə olmayan icazəni başqasına verə bilməzsiniz.",
            )

    def _assert_flag_grantable_to_subject(self, request: PermissionChangeRequest) -> None:
        """Hardlock + anti-fraud — DENY halında da yoxlanılır ki, yararsız
        override sətri ümumiyyətlə yaranmasın."""
        if request.effect is PermissionEffect.DENY:
            return
        try:
            request.flag.assert_grantable_to(
                request.subject.position.effective_system_role,
                is_camera_type_role=request.subject.position.is_camera_type,
                is_store_tier_role=request.subject.position.is_store_tier,
            )
        except AuthorizationError as exc:
            self._deny(request, reason="HARDLOCK_OR_ANTIFRAUD", message=exc.message)

    # ------------------------------- köməkçi -------------------------------- #

    def _deny(
        self,
        request: PermissionChangeRequest,
        *,
        reason: str,
        message: str,
        user_message: str | None = None,
    ) -> None:
        _security_log.warning(
            "PERMISSION_CHANGE_DENIED",
            extra={
                "denial_reason": reason,
                "actor_id": str(request.actor.id),
                "actor_role": request.actor.position.code,
                "subject_id": str(request.subject.id),
                "subject_role": request.subject.position.code,
                "flag": request.flag.code,
                "effect": request.effect.value,
            },
        )
        raise AuthorizationError(
            message,
            user_message=user_message or AuthorizationError.user_message,
            context={"denial_reason": reason, "flag": request.flag.code},
        )


__all__ = [
    "CONTROL_PERMISSIONS_FLAG",
    "PermissionChangeRequest",
    "PermissionHierarchyGuardUseCase",
]
