"""Manual cərimə qeydiyyatı və 72-saatlıq etiraz axını (bölmə 4) — Faza 5.

──────────────────────────────────────────────────────────────────────────────
İKİ AKTOR, ÜÇ QAPI
──────────────────────────────────────────────────────────────────────────────
    `can_issue_fines`         → Kamera Operatoru cəriməni YARADIR
    (işçinin özü)             → 72 saat ərzində ETİRAZ göndərir
    `can_approve_leave_appeal`→ HR_Admin etiraza QƏRAR verir

Üçü də ayrı-ayrı yoxlanılır. Xüsusilə üçüncüsü: cəriməni yaradan onu ləğv edə
BİLMƏMƏLİDİR, əks halda operator səhvini sükutla düzəldib auditdən yayına
bilərdi. `can_issue_fines` `is_camera_only`, `can_approve_leave_appeal` isə
kamera roluna defolt verilmir — DB trigger-i də bunu qoruyur.

──────────────────────────────────────────────────────────────────────────────
MƏBLƏĞ HARDAN GƏLİR (ANTI-FRAUD)
──────────────────────────────────────────────────────────────────────────────
Bölmə 4: "Kamera Operatoru sərbəst məbləğ təyin edə bilmir — yalnız CEO-nun
əvvəlcədən təsdiqlədiyi növ və standart qiymətdən seçim edir."

Ona görə `issue_manual_fine()` məbləği ARQUMENT KİMİ QƏBUL ETMİR. O, yalnız
`fine_type_id` alır və qiyməti kataloqdan özü oxuyur. İmzada məbləğ sahəsi
olsaydı, bir gün kimsə onu ekrandan doldurardı və qayda sükutla pozulardı.

──────────────────────────────────────────────────────────────────────────────
FOTO SÜBUTU NİYƏ İKİ MƏNBƏLİDİR
──────────────────────────────────────────────────────────────────────────────
Şəkil Drive-a ASİNXRON yüklənir (migration 002), yəni cərimə yaradılan anda
`evidence_drive_file_id` hələ yoxdur. Ona görə burada yerli növbə istinadı
(`evidence_reference`) kifayət sayılır — `Fine` entity-si "hər hansı sübut
mənbəyi göstərilib" şərtini yoxlayır, konkret buludu yox.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from src.application.use_cases.leave_verification import (
    ModuleDisabledError,
    OperationNotPermittedError,
)
from src.domain.entities.appeal import AppealStatus, FineAppeal
from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.identifiers import new_appeal_id, new_fine_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        CameraAssignmentRepository,
        Clock,
        FeatureToggles,
        FineAppealRepository,
        FineRepository,
        FineTypeRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.catalogs import FineType
    from src.domain.value_objects.identifiers import (
        AppealId,
        EmployeeId,
        FineId,
        FineTypeId,
        StoreId,
        TenantId,
    )
    from src.domain.value_objects.money import Money

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

ISSUE_FINES_FLAG = "can_issue_fines"
APPROVE_APPEAL_FLAG = "can_approve_leave_appeal"


class FinePermissionError(KompasOSError):
    """Cərimə əməliyyatı üçün səlahiyyət yoxdur."""

    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


class FineNotFoundError(KompasOSError):
    user_message = "Cərimə tapılmadı."


class AppealNotFoundError(KompasOSError):
    user_message = "Etiraz tapılmadı."


class AppealWindowClosedError(KompasOSError):
    """72 saat keçib — etiraz qəbul edilmir."""

    user_message = "Etiraz müddəti (72 saat) bitib."


@dataclass(frozen=True)
class AppealDecision:
    """Qərarın nəticəsi — ekranın göstərdiyi xülasə."""

    appeal: FineAppeal
    fine: Fine
    was_approved: bool
    reversed_amount: Money | None = None


class ManualFineUseCase:
    """ "Cərimələr" modulu — Kamera Operatorunun `[+ Yeni Cərimə]` axını."""

    def __init__(
        self,
        *,
        fines: FineRepository,
        fine_types: FineTypeRepository,
        camera_assignments: CameraAssignmentRepository,
        limits: SystemLimits,
        toggles: FeatureToggles,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._fines = fines
        self._fine_types = fine_types
        self._camera_assignments = camera_assignments
        self._limits = limits
        self._toggles = toggles
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------ seçimlər --------------------------------- #

    def allowed_stores(self, operator: Employee) -> list[StoreId]:
        """Mağaza dropdown-u — YALNIZ operatorun izlədiyi filiallar (bölmə 4).

        FAIL-SAFE: təyinat yoxdursa boş siyahı → ekran "Sizə hələ mağaza təyin
        edilməyib" mesajı göstərir və cərimə yaradıla bilmir.
        """
        return self._camera_assignments.stores_for_operator(operator.id)

    def selectable_fine_types(self, tenant_id: TenantId) -> list[FineType]:
        """Cərimə Növü dropdown-u — yalnız aktiv kataloq sətirləri."""
        return list(self._fine_types.list_all(tenant_id, include_inactive=False))

    # ------------------------------ yaratma ---------------------------------- #

    def issue(
        self,
        *,
        tenant_id: TenantId,
        operator: Employee,
        employee_id: EmployeeId,
        store_id: StoreId,
        fine_type_id: FineTypeId,
        evidence_reference: str,
        occurred_on: date | None = None,
        fine_id: FineId | None = None,
    ) -> Fine:
        """`[+ Yeni Cərimə]` — manual cərimə qeydiyyatı.

        Args:
            evidence_reference: Foto sübutunun istinadı (Drive fayl ID-si və ya
                yerli yükləmə növbəsi açarı). MƏCBURİDİR — bölmə 4.
            occurred_on: Hadisə tarixi (defolt bugün). Cərimənin `issued_at`
                möhürü isə HƏMİŞƏ indiki andır — keçmişə tarixləmə auditi
                korlayardı.
            fine_id: Kənardan verilən identifikator. `TaskWorkflowUseCase.assign`
                ilə eyni naxışdır və şəkil növbəsi üçün LAZIMDIR: növbə sətri
                `fine_id` tələb edir, cərimə isə növbə açarını sübut istinadı
                kimi saxlayır — biri digərini gözləsəydi dövrə bağlanardı.
                Verilmədikdə yenisi yaradılır.
        """
        self._require_module(tenant_id)
        now = self._clock.now()
        self._require_issue_permission(operator, now=now)
        self._require_store_scope(operator, store_id)

        if not evidence_reference.strip():
            raise OperationNotPermittedError(
                "Manual cərimə üçün foto sübutu MƏCBURİDİR (bölmə 4)",
                user_message="Cərimə üçün foto şəkil sübutu əlavə edin.",
                context={"store_id": str(store_id)},
            )

        fine_type = self._fine_types.get(fine_type_id)
        if fine_type is None:
            raise OperationNotPermittedError(
                "Cərimə Növü tapılmadı",
                user_message="Seçilmiş cərimə növü mövcud deyil.",
                context={"fine_type_id": str(fine_type_id)},
            )

        # Məbləğ KATALOQDAN gəlir — deaktiv növ istisna atır (anti-fraud).
        amount = fine_type.amount_for_new_fine()

        fine = Fine(
            fine_id=fine_id or new_fine_id(),
            tenant_id=tenant_id,
            employee_id=employee_id,
            store_id=store_id,
            source=FineSource.MANUAL_CAMERA,
            amount=amount,
            issued_at=now,
            appeal_window_hours=self._appeal_window_hours(tenant_id),
            fine_type_id=fine_type_id,
            issued_by=operator.id,
            photo_evidence_url=evidence_reference,
        )
        self._fines.save(fine)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=operator.id,
            action="MANUAL_FINE_ISSUED",
            entity_type="fines",
            entity_id=fine.id,
            after_state={
                "employee_id": str(employee_id),
                "store_id": str(store_id),
                "fine_type": fine_type.name,
                "amount": str(amount.amount),
                "occurred_on": (occurred_on or now.date()).isoformat(),
                "evidence": evidence_reference,
                "status": fine.status.value,
            },
        )
        _audit_log.info(
            "MANUAL_FINE_ISSUED",
            extra={
                "operator_id": str(operator.id),
                "employee_id": str(employee_id),
                "fine_type": fine_type.name,
            },
        )
        return fine

    # ------------------------------- baxış ----------------------------------- #

    def my_fines(self, *, employee: Employee, year: int, month: int) -> list[Fine]:
        """İşçinin öz "Cərimələrim" görünüşü (İşçi Ana Ekranı, bölmə 3).

        Nəşr olunmamış cərimələr GÖSTƏRİLMİR — `Fine.is_visible_to_employee`
        qaydası burada tətbiq olunur.
        """
        return [
            fine
            for fine in self._fines.list_for_employee_month(employee.id, year=year, month=month)
            if fine.is_visible_to_employee
        ]

    def _require_issue_permission(self, operator: Employee, *, now: datetime) -> None:
        if not operator.has_permission(ISSUE_FINES_FLAG, now=now):
            _security_log.warning(
                "FINE_ISSUE_DENIED",
                extra={"actor_id": str(operator.id), "flag": ISSUE_FINES_FLAG},
            )
            raise FinePermissionError(
                f"«{ISSUE_FINES_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(operator.id)},
            )

    def _require_store_scope(self, operator: Employee, store_id: StoreId) -> None:
        allowed = self._camera_assignments.stores_for_operator(operator.id)
        if store_id not in allowed:
            _security_log.warning(
                "FINE_STORE_SCOPE_DENIED",
                extra={"actor_id": str(operator.id), "store_id": str(store_id)},
            )
            raise FinePermissionError(
                "Operator bu mağazaya təyin edilməyib",
                user_message="Bu mağaza sizin nəzarətinizdə deyil.",
                context={"operator_id": str(operator.id), "store_id": str(store_id)},
            )

    def _require_module(self, tenant_id: TenantId) -> None:
        if not self._toggles.is_enabled(tenant_id, FeatureModule.FINE_MODULE.value):
            raise ModuleDisabledError(
                "FINE_MODULE deaktiv edilib",
                context={"module": FeatureModule.FINE_MODULE.value},
            )

    def _appeal_window_hours(self, tenant_id: TenantId) -> int:
        key = SystemLimitKey.FINE_APPEAL_WINDOW_HOURS
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))


class FineAppealUseCase:
    """72-saatlıq etiraz mexanizmi — hər iki cərimə mənbəyi üçün (bölmə 4).

    Bölmə 4 açıq deyir: "Manual cərimələr də yuxarıdakı 72-saatlıq ETİRAZ
    mexanizminə tabedir — AYRICA bir etiraz sistemi qurulmur". Ona görə burada
    `source` üzrə heç bir şərt YOXDUR: `AUTO_DELAY` və `MANUAL_CAMERA` eyni
    yoldan keçir.
    """

    def __init__(
        self,
        *,
        appeals: FineAppealRepository,
        fines: FineRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._appeals = appeals
        self._fines = fines
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------ göndərmə --------------------------------- #

    def submit(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        fine_id: FineId,
        reason: str,
    ) -> FineAppeal:
        """İşçi etiraz göndərir — YALNIZ öz cəriməsinə, YALNIZ pəncərə açıqkən."""
        now = self._clock.now()
        fine = self._require_fine(fine_id)

        if fine.employee_id != employee.id:
            _security_log.warning(
                "APPEAL_FOREIGN_FINE",
                extra={"actor_id": str(employee.id), "fine_id": str(fine_id)},
            )
            raise FinePermissionError(
                "Başqasının cəriməsinə etiraz edilə bilməz",
                user_message="Yalnız öz cərimənizə etiraz edə bilərsiniz.",
                context={"fine_id": str(fine_id)},
            )

        if fine.status is FineStatus.PENDING_REVIEW:
            # İşçi cəriməni hələ GÖRMƏYİB — etiraz məntiqsizdir.
            raise OperationNotPermittedError(
                "Nəşr olunmamış cəriməyə etiraz edilə bilməz",
                user_message="Bu cərimə hələ sizə açılmayıb.",
                context={"status": fine.status.value},
            )
        if fine.status is FineStatus.REVERSED:
            raise OperationNotPermittedError(
                "Ləğv edilmiş cəriməyə etiraz edilə bilməz",
                user_message="Bu cərimə artıq ləğv olunub.",
                context={"status": fine.status.value},
            )
        if not fine.is_appeal_window_open(now=now):
            raise AppealWindowClosedError(
                "Etiraz pəncərəsi bağlanıb",
                context={
                    "fine_id": str(fine_id),
                    "closed_at": (
                        fine.appeal_window_closes_at.isoformat()
                        if fine.appeal_window_closes_at
                        else None
                    ),
                },
            )
        if self._existing(fine_id) is not None:
            raise OperationNotPermittedError(
                "Bu cəriməyə artıq etiraz göndərilib",
                user_message="Bu cərimə üçün artıq etirazınız var.",
                context={"fine_id": str(fine_id)},
            )

        appeal = FineAppeal(
            appeal_id=new_appeal_id(),
            tenant_id=tenant_id,
            fine_id=fine_id,
            employee_id=employee.id,
            reason=reason,
            created_at=now,
        )
        self._save(appeal)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="FINE_APPEAL_SUBMITTED",
            entity_type="fine_appeals",
            entity_id=appeal.id,
            after_state={"fine_id": str(fine_id), "status": appeal.status.value},
            reason=appeal.reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # `can_approve_leave_appeal` sahibləri
            category="FINE_APPEAL_PENDING",
            title_az="Yeni cərimə etirazı",
            body_az=(
                f"{fine.amount} məbləğində cəriməyə etiraz göndərildi. Səbəb: {appeal.reason}"
            ),
            is_critical=False,
        )
        return appeal

    # -------------------------------- inbox ---------------------------------- #

    def inbox(self, *, tenant_id: TenantId, actor: Employee) -> list[FineAppeal]:
        """HR_Admin-in etiraz növbəsi."""
        self._require_approver(actor)
        return list(self._appeals.list_pending(tenant_id))

    def my_appeals(self, employee: Employee) -> list[FineAppeal]:
        """İşçinin öz etiraz tarixçəsi — səlahiyyət tələb olunmur."""
        return list(self._appeals.list_for_employee(employee.id))

    # -------------------------------- qərar ---------------------------------- #

    def approve(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        appeal_id: AppealId,
        note: str,
        new_amount: Money | None = None,
    ) -> AppealDecision:
        """Etirazı qəbul edir — cərimə ləğv (`REVERSED`) və ya azaldılır (`REDUCED`).

        Orijinal qeyd SİLİNMİR (bölmə 4) — `Fine.reverse()` yalnız statusu
        dəyişir və `original_amount`-u saxlayır.
        """
        self._require_approver(actor)
        now = self._clock.now()
        appeal = self._require_appeal(appeal_id)
        fine = self._require_fine(appeal.fine_id)

        appeal.approve(
            decided_by=actor.id,
            decided_at=now,
            note=note,
            new_amount=new_amount,
        )
        fine.reverse(
            decided_by=actor.id,
            decided_at=now,
            reason=note,
            appeal_id=appeal.id,
            new_amount=new_amount,
        )
        self._save(appeal)
        self._fines.save(fine)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FINE_APPEAL_APPROVED",
            entity_type="fine_appeals",
            entity_id=appeal.id,
            before_state={"fine_status": FineStatus.PUBLISHED.value},
            after_state={
                "fine_status": fine.status.value,
                "original_amount": str(fine.original_amount.amount),
                "new_amount": str(fine.amount.amount),
            },
            reason=appeal.decision_note,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=appeal.employee_id,
            category="FINE_APPEAL_DECIDED",
            title_az="Cərimə etirazınız qəbul edildi",
            body_az=(
                f"Cəriməniz {'azaldıldı' if fine.status is FineStatus.REDUCED else 'ləğv edildi'}. "
                f"Yeni məbləğ: {fine.amount}. Qərar: {appeal.decision_note}"
            ),
            is_critical=False,
        )
        return AppealDecision(
            appeal=appeal,
            fine=fine,
            was_approved=True,
            reversed_amount=fine.amount,
        )

    def reject(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        appeal_id: AppealId,
        note: str,
    ) -> AppealDecision:
        """Etirazı rədd edir — cərimə toxunulmaz qalır, qeyd audit-lənir."""
        self._require_approver(actor)
        now = self._clock.now()
        appeal = self._require_appeal(appeal_id)
        fine = self._require_fine(appeal.fine_id)

        appeal.reject(decided_by=actor.id, decided_at=now, note=note)
        self._save(appeal)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FINE_APPEAL_REJECTED",
            entity_type="fine_appeals",
            entity_id=appeal.id,
            after_state={"status": appeal.status.value, "fine_id": str(fine.id)},
            reason=appeal.decision_note,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=appeal.employee_id,
            category="FINE_APPEAL_DECIDED",
            title_az="Cərimə etirazınız rədd edildi",
            body_az=f"Etirazınız rədd edildi. Səbəb: {appeal.decision_note}",
            is_critical=False,
        )
        return AppealDecision(appeal=appeal, fine=fine, was_approved=False)

    # ------------------------------ planlanmış ------------------------------- #

    def expire_stale(self, tenant_id: TenantId) -> int:
        """Cavabsız qalmış etirazları bağlayır (planlaşdırılmış iş).

        DB tərəfindəki `cron_close_expired_appeals` ilə eyni qaydadır —
        burada tətbiq qatında da mövcuddur ki, `pg_cron` olmayan quraşdırmada
        (bax `docs/scheduler_setup.md`, Variant B) eyni nəticə alınsın.
        """
        now = self._clock.now()
        closed = 0
        for appeal in self._appeals.list_pending(tenant_id):
            fine = self._fines.get(appeal.fine_id)
            if fine is None or fine.is_appeal_window_open(now=now):
                continue
            if not appeal.expire(now=now):
                continue
            self._save(appeal)
            closed += 1
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="FINE_APPEAL_EXPIRED",
                entity_type="fine_appeals",
                entity_id=appeal.id,
                after_state={"status": AppealStatus.EXPIRED.value},
                reason="Etiraz pəncərəsi cavabsız bağlandı",
            )
        return closed

    # ------------------------------- köməkçi --------------------------------- #

    def _existing(self, fine_id: FineId) -> FineAppeal | None:
        return self._appeals.get_for_fine(fine_id)

    def _save(self, appeal: FineAppeal) -> None:
        self._appeals.save(appeal)

    def _require_appeal(self, appeal_id: AppealId) -> FineAppeal:
        appeal = self._appeals.get(appeal_id)
        if appeal is None:
            raise AppealNotFoundError("Etiraz tapılmadı", context={"appeal_id": str(appeal_id)})
        return appeal

    def _require_fine(self, fine_id: FineId) -> Fine:
        fine = self._fines.get(fine_id)
        if fine is None:
            raise FineNotFoundError("Cərimə tapılmadı", context={"fine_id": str(fine_id)})
        return fine

    def _require_approver(self, actor: Employee) -> None:
        if not actor.has_permission(APPROVE_APPEAL_FLAG, now=self._clock.now()):
            _security_log.warning(
                "APPEAL_DECISION_DENIED",
                extra={"actor_id": str(actor.id), "flag": APPROVE_APPEAL_FLAG},
            )
            raise FinePermissionError(
                f"«{APPROVE_APPEAL_FLAG}» səlahiyyəti yoxdur",
                user_message="Etiraza qərar vermək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )


__all__ = [
    "APPROVE_APPEAL_FLAG",
    "ISSUE_FINES_FLAG",
    "AppealDecision",
    "AppealNotFoundError",
    "AppealWindowClosedError",
    "FineAppealUseCase",
    "FineNotFoundError",
    "FinePermissionError",
    "ManualFineUseCase",
]
