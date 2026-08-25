"""Struktur offboarding checklist-i (`v2backlog.md` Faza 3.4).

Bax `entities/offboarding_checklist.py` başlığı — checklist DEAKTİVASİYANI
bloklamır, öz TAMAMLANMASINI bloklayır. `start_checklist()` `UserManagementUseCase.
deactivate_employee()`/`deactivate_scheduled_employees()`-in İÇİNDƏN, deaktivasiya
UĞURLA bitdikdən SONRA çağırılır (`composition.py`-da bağlanır) — bax
`user_management.py`-dakı `_offboarding_checklists` portu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.entities.offboarding_checklist import (
    EmployeeOffboardingChecklist,
    OffboardingChecklistItem,
)
from src.domain.value_objects.catalogs import (
    OFFBOARDING_OWNER_KEY,
    ChecklistOwnerType,
)
from src.domain.value_objects.identifiers import (
    new_offboarding_checklist_id,
    new_offboarding_checklist_item_id,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        ChecklistItemTemplateRepository,
        Clock,
        EmployeeOffboardingChecklistRepository,
        Notifier,
    )
    from src.domain.value_objects.catalogs import ChecklistItemCategory, ChecklistItemTemplate
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        OffboardingChecklistId,
        OffboardingChecklistItemId,
        TenantId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Checklist bəndini cavablamaq/tamamlamaq — `deactivate_employee` ilə EYNİ
#: qapı (`v2backlog.md` Faza 3.4 yeni flag TƏLƏB ETMİR: HR-in işdən çıxarma
#: səlahiyyəti onsuz da bu prosesi əhatə edir).
MANAGE_OFFBOARDING_FLAG = "can_manage_employees"


def _require_category(template: ChecklistItemTemplate) -> ChecklistItemCategory:
    """`template.category`-ni `None`-siz qaytarır.

    Kateqoriya zəmanəti artıq İKİ yerdədir (CLAUDE.md §5): domendə
    `ChecklistItemTemplate.__post_init__` VƏ DB-də `chk_checklist_template_
    category_by_owner` (migrations/094) — `owner_type=OFFBOARDING`
    şablonu `category=None` ilə ÜMUMİYYƏTLƏ QURULA BİLMİR. Üçüncü, işə
    düşməyən müdafiə qatı (fallback dəyər) buna görə YOXDUR — `assert`
    yalnız mypy-ə tipi daraltmaq üçündür, real qorunma deyil.
    """
    assert template.category is not None, (
        "OFFBOARDING şablonunun kateqoriyası olmalıdır — domen invariantı pozulub"
    )
    return template.category


class OffboardingChecklistError(KompasOSError):
    """Offboarding checklist əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Offboarding checklist əməliyyatı icra edilə bilmədi."


class OffboardingChecklistNotFoundError(OffboardingChecklistError):
    user_message = "Bu checklist tapılmadı."


class EmployeeOffboardingChecklistUseCase:
    """Checklist-in başladılması, bəndlərin cavablanması, tamamlanması."""

    def __init__(
        self,
        *,
        checklists: EmployeeOffboardingChecklistRepository,
        templates: ChecklistItemTemplateRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._checklists = checklists
        self._templates = templates
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------- başlatma --------------------------------- #

    def start_checklist(
        self, *, tenant_id: TenantId, initiated_by: EmployeeId, employee_id: EmployeeId
    ) -> EmployeeOffboardingChecklist | None:
        """Deaktivasiyadan SONRA çağırılır — Root şablonundan bəndləri köçürür.

        Returns:
            `None` — aktiv şablon yoxdursa (Root hələ heç bir bənd
            yazmayıb). Boş checklist yaratmaq `IN_PROGRESS` sətri MƏNASIZ
            saxlayardı və `uq_offboarding_active_per_employee` indeksini
            hədər yerə tutardı.
        """
        now = self._clock.now()
        templates = self._templates.list_for_owner(
            tenant_id,
            owner_type=ChecklistOwnerType.OFFBOARDING,
            owner_key=OFFBOARDING_OWNER_KEY,
        )
        if not templates:
            return None

        checklist_id = new_offboarding_checklist_id()
        checklist_items = tuple(
            OffboardingChecklistItem(
                item_id=new_offboarding_checklist_item_id(),
                tenant_id=tenant_id,
                checklist_id=checklist_id,
                position_no=template.position_no,
                # `ChecklistItemTemplate.__post_init__` (`value_objects/catalogs.py`)
                # `owner_type=OFFBOARDING` üçün `category`-ni MƏCBURİ edir —
                # DB `CHECK chk_checklist_template_category_by_owner`
                # (migrations/094) ilə İKİ QATLI zəmanət. `list_for_owner`
                # yuxarıda YALNIZ OFFBOARDING şablonlarını gətirdiyi üçün
                # `None` BURAYA HEÇ VAXT ÇATA BİLMƏZ.
                category=_require_category(template),
                item_text=template.item_text,
                is_blocking=template.is_blocking,
                created_at=now,
                updated_at=now,
            )
            for template in templates
        )
        checklist = EmployeeOffboardingChecklist(
            checklist_id=checklist_id,
            tenant_id=tenant_id,
            employee_id=employee_id,
            initiated_by=initiated_by,
            created_at=now,
            updated_at=now,
            items=checklist_items,
        )
        self._checklists.save(checklist)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=initiated_by,
            action="OFFBOARDING_CHECKLIST_STARTED",
            entity_type="employee_offboarding_checklists",
            entity_id=checklist.id,
            after_state={
                "employee_id": str(employee_id),
                "item_count": len(checklist_items),
            },
        )
        return checklist

    # -------------------------------- bəndlər ---------------------------------- #

    def answer_item(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        checklist_id: OffboardingChecklistId,
        item_id: OffboardingChecklistItemId,
        passed: bool,
        notes: str | None = None,
    ) -> EmployeeOffboardingChecklist:
        self._require(actor)
        checklist = self._require_checklist(checklist_id)
        now = self._clock.now()
        item = checklist.answer_item(item_id=item_id, passed=passed, now=now, notes=notes)
        self._checklists.save(checklist)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="OFFBOARDING_ITEM_ANSWERED",
            entity_type="employee_offboarding_checklist_items",
            entity_id=item.id,
            after_state={"passed": passed, "item_text": item.item_text},
        )
        return checklist

    def complete(
        self, *, tenant_id: TenantId, actor: Employee, checklist_id: OffboardingChecklistId
    ) -> EmployeeOffboardingChecklist:
        """`[Checklist-i Bağla]` — bloklayıcı bəndlər həll olunmayıbsa RƏDD edir."""
        self._require(actor)
        checklist = self._require_checklist(checklist_id)
        checklist.complete(completed_by=actor.id, now=self._clock.now())
        self._checklists.save(checklist)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="OFFBOARDING_CHECKLIST_COMPLETED",
            entity_type="employee_offboarding_checklists",
            entity_id=checklist.id,
            after_state={"employee_id": str(checklist.employee_id)},
        )
        return checklist

    # -------------------------------- oxuma ------------------------------------ #

    def get_active_for_employee(
        self, *, actor: Employee, employee_id: EmployeeId
    ) -> EmployeeOffboardingChecklist | None:
        self._require(actor)
        return self._checklists.get_active_for_employee(employee_id)

    # ------------------------------- köməkçi ----------------------------------- #

    def _require(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_OFFBOARDING_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "OFFBOARDING_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_OFFBOARDING_FLAG},
            )
            raise OffboardingChecklistError(
                f"«{MANAGE_OFFBOARDING_FLAG}» səlahiyyəti yoxdur",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )

    def _require_checklist(
        self, checklist_id: OffboardingChecklistId
    ) -> EmployeeOffboardingChecklist:
        checklist = self._checklists.get(checklist_id)
        if checklist is None:
            raise OffboardingChecklistNotFoundError(
                "Checklist tapılmadı", context={"checklist_id": str(checklist_id)}
            )
        return checklist


__all__ = [
    "MANAGE_OFFBOARDING_FLAG",
    "EmployeeOffboardingChecklistUseCase",
    "OffboardingChecklistError",
    "OffboardingChecklistNotFoundError",
]
