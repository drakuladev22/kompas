"""Kataloq idarəetməsi — İş Rejimləri, Cərimə Növləri, İcazə Növləri (bölmə 4).

──────────────────────────────────────────────────────────────────────────────
ÜÇ KATALOQ, ÜÇ AYRI SƏLAHİYYƏT
──────────────────────────────────────────────────────────────────────────────
    * `can_manage_work_modes`  — defolt `Root`/`CEO`
    * `can_manage_fine_types`  — defolt `Root`/`CEO`
    * `can_manage_leave_types` — defolt `Root`/`CEO`/`HR_Admin`

Ayrı olması təsadüfi deyil: İcazə Növləri HR-ın gündəlik işidir ("Nahar
Fasiləsi" əlavə etmək zərərsizdir), Cərimə Növləri isə PUL təyin edir və HR-a
verilə bilməz — əks halda `can_issue_fines` sahibi ilə HR sövdələşərək məbləği
qaldıra bilərdi. Ona görə burada hər kataloq öz flag-ını AYRICA yoxlayır və
"biri var, deməli hamısı var" fərziyyəsi qurulmur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR ƏMƏLİYYAT AUDİT-LƏNİR
──────────────────────────────────────────────────────────────────────────────
Cərimə növünün standart qiymətinin dəyişdirilməsi keçmiş cərimələrə təsir
etmir, LAKİN gələcək bütün cərimələrin məbləğini təyin edir. Kimin nə vaxt
50 AZN-i 150 AZN-ə qaldırdığı sual olunduqda cavab verilə bilməlidir — bu,
`can_issue_fines` sui-istifadəsini aşkarlamağın yeganə yoludur.

──────────────────────────────────────────────────────────────────────────────
SİLMƏ NİYƏ YOXDUR
──────────────────────────────────────────────────────────────────────────────
`delete()` metodu QƏSDƏN mövcud deyil — yalnız `deactivate()`. Bax
`domain/value_objects/catalogs.py` modul başlığı: fiziki silmə keçmiş
cərimənin səbəbini "naməlum"a çevirərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.application.use_cases.offboarding_checklist import MANAGE_OFFBOARDING_FLAG
from src.domain.value_objects.catalogs import (
    ChecklistItemTemplate,
    ChecklistOwnerType,
    FineType,
    LeaveType,
    WorkMode,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        ChecklistItemTemplateRepository,
        Clock,
        FineTypeRepository,
        LeaveTypeRepository,
        WorkModeRepository,
    )
    from src.domain.value_objects.identifiers import (
        ChecklistItemTemplateId,
        FineTypeId,
        LeaveTypeId,
        TenantId,
        WorkModeId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

WORK_MODES_FLAG = "can_manage_work_modes"
FINE_TYPES_FLAG = "can_manage_fine_types"
LEAVE_TYPES_FLAG = "can_manage_leave_types"
#: `checklist_item_templates` (owner_type=OFFBOARDING) idarəetməsi —
#: `offboarding_checklist.py`-dakı EYNİ flag: Faza 3.4 yeni icazə TƏLƏB ETMİR,
#: HR-in işdən çıxarma səlahiyyəti onsuz da checklist mətnini əhatə edir. Yeni
#: `owner_type=FIELD_REPORT` şablonları (Faza 4.1, BU sahənin hələlik işi
#: DEYİL) fərqli flag tələb edə bilər — o zaman bu sabit ARTIQ tək başına
#: kifayət etməyəcək və owner_type-a görə budaqlanmalı olacaq.
CHECKLIST_TEMPLATES_FLAG = MANAGE_OFFBOARDING_FLAG


class CatalogPermissionError(KompasOSError):
    """Kataloqu dəyişdirmək üçün səlahiyyət yoxdur."""

    user_message = "Bu kataloqu dəyişdirmək səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class CatalogChange:
    """Bir kataloq əməliyyatının nəticəsi — ekranın göstərdiyi təsdiq."""

    entry_name: str
    action: str
    audited: bool = True


def _require(actor: Employee, flag: str, *, now: datetime) -> None:
    """Səlahiyyəti yoxlayır — yoxdursa açıq istisna.

    Sükutla "heç nə etmə" seçilmir: istifadəçi düyməni basıb və nəticəni
    gözləyir; heç nə olmaması onu eyni əməliyyatı təkrar-təkrar sınamağa
    məcbur edərdi.
    """
    if not actor.has_permission(flag, now=now):
        _audit_log.warning(
            "CATALOG_PERMISSION_DENIED",
            extra={"actor_id": str(actor.id), "flag": flag},
        )
        raise CatalogPermissionError(
            f"«{flag}» səlahiyyəti yoxdur",
            context={"actor_id": str(actor.id), "flag": flag},
        )


class WorkModeCatalogUseCase:
    """İş Rejimləri kataloqu — Shift Matrix-in şablon mənbəyi."""

    def __init__(
        self,
        *,
        repository: WorkModeRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    def list_for_management(self, tenant_id: TenantId, actor: Employee) -> list[WorkMode]:
        """İdarəetmə ekranı — deaktivlər DƏ görünür (yenidən aktivləşdirmək üçün)."""
        _require(actor, WORK_MODES_FLAG, now=self._clock.now())
        return self._repository.list_all(tenant_id, include_inactive=True)

    def list_for_selection(self, tenant_id: TenantId) -> list[WorkMode]:
        """Növbə matrisi üçün — YALNIZ aktivlər, səlahiyyət tələb olunmur.

        Növbə planlayan `can_manage_shifts` sahibinin `can_manage_work_modes`
        səlahiyyəti olmaya bilər; o, kataloqu dəyişmir, sadəcə seçir.
        """
        return self._repository.list_all(tenant_id, include_inactive=False)

    def save(self, tenant_id: TenantId, actor: Employee, entry: WorkMode) -> CatalogChange:
        now = self._clock.now()
        _require(actor, WORK_MODES_FLAG, now=now)

        self._repository.save(tenant_id, entry, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="WORK_MODE_SAVED",
            entity_type="work_mode",
            entity_id=entry.work_mode_id,
            after_state={
                "name": entry.name,
                "schedule": entry.scheduled_start_label(),
                "is_active": entry.is_active,
            },
        )
        return CatalogChange(entry_name=entry.name, action="saved")

    def deactivate(
        self, tenant_id: TenantId, actor: Employee, work_mode_id: WorkModeId
    ) -> CatalogChange:
        now = self._clock.now()
        _require(actor, WORK_MODES_FLAG, now=now)

        existing = self._repository.get(work_mode_id)
        name = existing.name if existing is not None else str(work_mode_id)

        self._repository.deactivate(tenant_id, work_mode_id, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="WORK_MODE_DEACTIVATED",
            entity_type="work_mode",
            entity_id=work_mode_id,
            before_state={"name": name, "is_active": True},
            after_state={"name": name, "is_active": False},
        )
        return CatalogChange(entry_name=name, action="deactivated")


class FineTypeCatalogUseCase:
    """Cərimə Növləri kataloqu — anti-fraud nəzarətinin mərkəzi (bölmə 4)."""

    def __init__(
        self,
        *,
        repository: FineTypeRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    def list_for_management(self, tenant_id: TenantId, actor: Employee) -> list[FineType]:
        _require(actor, FINE_TYPES_FLAG, now=self._clock.now())
        return self._repository.list_all(tenant_id, include_inactive=True)

    def list_for_selection(self, tenant_id: TenantId) -> list[FineType]:
        """Kamera Operatorunun cərimə ekranındakı açılan siyahı.

        Səlahiyyət YOXLANMIR: operatorun `can_manage_fine_types` flag-i
        olmamalıdır (o, qiyməti təyin edən deyil, seçəndir) — yoxlama
        burada olsaydı, cərimə ekranı boş qalardı.
        """
        return self._repository.list_all(tenant_id, include_inactive=False)

    def save(self, tenant_id: TenantId, actor: Employee, entry: FineType) -> CatalogChange:
        now = self._clock.now()
        _require(actor, FINE_TYPES_FLAG, now=now)

        previous = (
            self._repository.get(entry.fine_type_id) if entry.fine_type_id is not None else None
        )
        self._repository.save(tenant_id, entry, changed_by=actor.id)

        # Qiymət dəyişikliyi AYRICA görünsün deyə əvvəlki dəyər də yazılır.
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FINE_TYPE_SAVED",
            entity_type="fine_type",
            entity_id=entry.fine_type_id,
            before_state=(
                None
                if previous is None
                else {
                    "name": previous.name,
                    "standard_amount": str(previous.standard_amount.amount),
                    "is_active": previous.is_active,
                }
            ),
            after_state={
                "name": entry.name,
                "standard_amount": str(entry.standard_amount.amount),
                "is_active": entry.is_active,
            },
        )
        return CatalogChange(entry_name=entry.name, action="saved")

    def deactivate(
        self, tenant_id: TenantId, actor: Employee, fine_type_id: FineTypeId
    ) -> CatalogChange:
        now = self._clock.now()
        _require(actor, FINE_TYPES_FLAG, now=now)

        existing = self._repository.get(fine_type_id)
        name = existing.name if existing is not None else str(fine_type_id)

        self._repository.deactivate(tenant_id, fine_type_id, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FINE_TYPE_DEACTIVATED",
            entity_type="fine_type",
            entity_id=fine_type_id,
            before_state={"name": name, "is_active": True},
            after_state={"name": name, "is_active": False},
            reason="Yeni cərimələrdə seçilə bilməz; tarixi qeydlər dəyişmir",
        )
        return CatalogChange(entry_name=name, action="deactivated")


class LeaveTypeCatalogUseCase:
    """İcazə Növləri kataloqu — HR-ın idarə etdiyi kateqoriyalar (bölmə 4)."""

    def __init__(
        self,
        *,
        repository: LeaveTypeRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    def list_for_management(self, tenant_id: TenantId, actor: Employee) -> list[LeaveType]:
        _require(actor, LEAVE_TYPES_FLAG, now=self._clock.now())
        return self._repository.list_all(tenant_id, include_inactive=True)

    def list_for_selection(self, tenant_id: TenantId) -> list[LeaveType]:
        """STEP 1 `[İcazə İstəyirəm]` ekranındakı seçim siyahısı."""
        return self._repository.list_all(tenant_id, include_inactive=False)

    def save(self, tenant_id: TenantId, actor: Employee, entry: LeaveType) -> CatalogChange:
        now = self._clock.now()
        _require(actor, LEAVE_TYPES_FLAG, now=now)

        self._repository.save(tenant_id, entry, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="LEAVE_TYPE_SAVED",
            entity_type="leave_type",
            entity_id=entry.leave_type_id,
            after_state={
                "name": entry.name,
                "default_duration_minutes": entry.default_duration_minutes,
                "is_active": entry.is_active,
            },
        )
        return CatalogChange(entry_name=entry.name, action="saved")

    def deactivate(
        self, tenant_id: TenantId, actor: Employee, leave_type_id: LeaveTypeId
    ) -> CatalogChange:
        now = self._clock.now()
        _require(actor, LEAVE_TYPES_FLAG, now=now)

        self._repository.deactivate(tenant_id, leave_type_id, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="LEAVE_TYPE_DEACTIVATED",
            entity_type="leave_type",
            entity_id=leave_type_id,
            after_state={"is_active": False},
        )
        return CatalogChange(entry_name=str(leave_type_id), action="deactivated")


class ChecklistItemTemplateUseCase:
    """Checklist bənd şablonları kataloqu (Faza 3.4 + 4.1 ORTAQ) — Root idarə edir.

    `owner_type`/`owner_key` HAMI ÇAĞIRIŞLARDA açıq ötürülür (digər üç
    kataloqdan FƏRQLİ olaraq bu, TƏK ad-məkanı deyil, İKİ domenin ORTAQ
    infrastrukturudur — bax `migrations/088` başlığı).
    """

    def __init__(
        self,
        *,
        repository: ChecklistItemTemplateRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    def list_for_management(
        self,
        tenant_id: TenantId,
        actor: Employee,
        *,
        owner_type: ChecklistOwnerType,
        owner_key: str,
    ) -> list[ChecklistItemTemplate]:
        _require(actor, CHECKLIST_TEMPLATES_FLAG, now=self._clock.now())
        return self._repository.list_for_owner(
            tenant_id, owner_type=owner_type, owner_key=owner_key, include_inactive=True
        )

    def list_for_instantiation(
        self, tenant_id: TenantId, *, owner_type: ChecklistOwnerType, owner_key: str
    ) -> list[ChecklistItemTemplate]:
        """Yeni checklist YARADILARKƏN köçürülən aktiv bəndlər.

        Səlahiyyət YOXLANMIR: bu, insan düyməsi DEYİL — `deactivate_employee`
        axınının bir hissəsidir (`list_for_selection` naxışları ilə eyni
        əsaslandırma: seçən deyil, sistemin ÖZÜ oxuyur).
        """
        return self._repository.list_for_owner(
            tenant_id, owner_type=owner_type, owner_key=owner_key, include_inactive=False
        )

    def save(
        self, tenant_id: TenantId, actor: Employee, entry: ChecklistItemTemplate
    ) -> CatalogChange:
        now = self._clock.now()
        _require(actor, CHECKLIST_TEMPLATES_FLAG, now=now)

        self._repository.save(entry, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="CHECKLIST_ITEM_TEMPLATE_SAVED",
            entity_type="checklist_item_templates",
            entity_id=entry.template_id,
            after_state={
                "owner_type": entry.owner_type.value,
                "owner_key": entry.owner_key,
                "position_no": entry.position_no,
                "item_text": entry.item_text,
                "is_blocking": entry.is_blocking,
                "is_active": entry.is_active,
            },
        )
        return CatalogChange(entry_name=entry.item_text, action="saved")

    def deactivate(
        self, tenant_id: TenantId, actor: Employee, template_id: ChecklistItemTemplateId
    ) -> CatalogChange:
        now = self._clock.now()
        _require(actor, CHECKLIST_TEMPLATES_FLAG, now=now)

        existing = self._repository.get(template_id)
        name = existing.item_text if existing is not None else str(template_id)

        self._repository.deactivate(tenant_id, template_id, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="CHECKLIST_ITEM_TEMPLATE_DEACTIVATED",
            entity_type="checklist_item_templates",
            entity_id=template_id,
            before_state={"item_text": name, "is_active": True},
            after_state={"item_text": name, "is_active": False},
            reason="Yeni checklist-lərdə köçürülmür; keçmiş instansiyalar dəyişmir",
        )
        return CatalogChange(entry_name=name, action="deactivated")


__all__ = [
    "CHECKLIST_TEMPLATES_FLAG",
    "FINE_TYPES_FLAG",
    "LEAVE_TYPES_FLAG",
    "WORK_MODES_FLAG",
    "CatalogChange",
    "CatalogPermissionError",
    "ChecklistItemTemplateUseCase",
    "FineTypeCatalogUseCase",
    "LeaveTypeCatalogUseCase",
    "WorkModeCatalogUseCase",
]
