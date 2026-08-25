"""İşdən çıxma checklist-i — entity + `EmployeeOffboardingChecklistUseCase` +
`ChecklistItemTemplateUseCase` (`v2backlog.md` Faza 3.4).

──────────────────────────────────────────────────────────────────────────────
İKİ AYRI QAPI, İKİ AYRI TEST DƏSTİ
──────────────────────────────────────────────────────────────────────────────
1. `is_blocking` bənd checklist-in TAMAMLANMASINI bloklayır
   (`ChecklistNotCompletableError`), LAKİN `deactivate_employee()`-in özünü
   ƏSLA bloklamır — bu ikisi FƏRQLİ metodlardır (`entity.complete()` /
   `UserManagementUseCase.deactivate_employee()`), ona görə bu fayl YALNIZ
   birincini yoxlayır; ikincinin "bloklamadığı" faktı
   `test_employee_lifecycle_v2.py`-də əks tərəfdən sübut olunur.
2. Kateqoriya MƏCBURİLİYİ (CLAUDE.md §5, `ChecklistItemTemplate.__post_init__`) —
   `owner_type=OFFBOARDING` şablonu `category=None` ilə qurula BİLMİR,
   `owner_type=FIELD_REPORT` isə `category` DAŞIYA BİLMİR. Qayda İKİNCİ
   yerdə də var: DB `CHECK chk_checklist_template_category_by_owner`
   (migrations/094). Əvvəllər bu boşluq (sütun hələ yoxdursa) `start_
   checklist()`-də `EQUIPMENT` fallback-ı ilə ÖRTÜLÜRDÜ — fallback İNDİ
   ÖLÜ KOD idi (konstruksiya artıq baş vermir) və silinib; bu fayl indi
   fallback-ı YOX, məhz qadağanın ÖZÜNÜ hər iki istiqamətdə kilidləyir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.catalog_management import (
    FIELD_REPORT_CHECKLIST_TEMPLATES_FLAG,
    CatalogPermissionError,
    ChecklistItemTemplateUseCase,
)
from src.application.use_cases.offboarding_checklist import (
    MANAGE_OFFBOARDING_FLAG,
    EmployeeOffboardingChecklistUseCase,
    OffboardingChecklistError,
    OffboardingChecklistNotFoundError,
)
from src.domain.entities.base import InvalidStateTransitionError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.offboarding_checklist import (
    ChecklistNotCompletableError,
    EmployeeOffboardingChecklist,
    OffboardingChecklistItem,
    OffboardingStatus,
)
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.catalogs import (
    OFFBOARDING_OWNER_KEY,
    ChecklistItemCategory,
    ChecklistItemTemplate,
    ChecklistOwnerType,
    InvalidCatalogEntryError,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    TenantId,
    new_checklist_item_template_id,
    new_offboarding_checklist_id,
    new_offboarding_checklist_item_id,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Saxta portlar
# --------------------------------------------------------------------------- #


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)

    def last(self) -> dict[str, Any]:
        return self.records[-1]


class _Notifier:
    def notify(self, **kwargs: Any) -> None:
        pass


class _ChecklistRepo:
    def __init__(self) -> None:
        self.items: dict[Any, EmployeeOffboardingChecklist] = {}

    def get(self, checklist_id: Any) -> EmployeeOffboardingChecklist | None:
        return self.items.get(checklist_id)

    def get_active_for_employee(
        self, employee_id: EmployeeId
    ) -> EmployeeOffboardingChecklist | None:
        for checklist in self.items.values():
            if (
                checklist.employee_id == employee_id
                and checklist.status is OffboardingStatus.IN_PROGRESS
            ):
                return checklist
        return None

    def list_for_employee(self, employee_id: EmployeeId) -> list[EmployeeOffboardingChecklist]:
        return [c for c in self.items.values() if c.employee_id == employee_id]

    def save(self, checklist: EmployeeOffboardingChecklist) -> None:
        self.items[checklist.id] = checklist


class _TemplateRepo:
    """`ChecklistItemTemplateRepository` — yaddaşda."""

    def __init__(self, templates: list[ChecklistItemTemplate] | None = None) -> None:
        self.items: dict[Any, ChecklistItemTemplate] = {t.template_id: t for t in (templates or [])}

    def get(self, template_id: Any) -> ChecklistItemTemplate | None:
        return self.items.get(template_id)

    def list_for_owner(
        self,
        tenant_id: TenantId,
        *,
        owner_type: ChecklistOwnerType,
        owner_key: str,
        include_inactive: bool = False,
    ) -> list[ChecklistItemTemplate]:
        return [
            t
            for t in self.items.values()
            if t.tenant_id == tenant_id
            and t.owner_type is owner_type
            and t.owner_key == owner_key
            and (include_inactive or t.is_active)
        ]

    def save(self, template: ChecklistItemTemplate, *, changed_by: EmployeeId) -> None:
        self.items[template.template_id] = template

    def deactivate(self, tenant_id: TenantId, template_id: Any, *, changed_by: EmployeeId) -> None:
        existing = self.items[template_id]
        self.items[template_id] = ChecklistItemTemplate(
            template_id=existing.template_id,
            tenant_id=existing.tenant_id,
            owner_type=existing.owner_type,
            owner_key=existing.owner_key,
            position_no=existing.position_no,
            item_text=existing.item_text,
            is_blocking=existing.is_blocking,
            photo_required=existing.photo_required,
            is_active=False,
            deactivated_at=NOW,
            category=existing.category,
        )


def _position(code: str, priority: RolePriority) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=code.title(),
        priority=priority,
        tenant_id=TENANT,
        is_system=True,
    )


def _employee(*, flags: tuple[str, ...] = ()) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=_position("HR", RolePriority.OPERATIONAL),
        first_name="Ad",
        last_name="Soyad",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


def _template(
    *,
    position_no: int = 1,
    is_blocking: bool = False,
    category: ChecklistItemCategory | None = ChecklistItemCategory.EQUIPMENT,
) -> ChecklistItemTemplate:
    return ChecklistItemTemplate(
        template_id=new_checklist_item_template_id(),
        tenant_id=TENANT,
        owner_type=ChecklistOwnerType.OFFBOARDING,
        owner_key=OFFBOARDING_OWNER_KEY,
        position_no=position_no,
        item_text=f"Bənd {position_no}",
        is_blocking=is_blocking,
        category=category,
    )


class Ctx:
    def __init__(self) -> None:
        self.clock = _Clock()
        self.checklists = _ChecklistRepo()
        self.templates = _TemplateRepo()
        self.audit = _Audit()
        self.notifier = _Notifier()

    def checklist_uc(self) -> EmployeeOffboardingChecklistUseCase:
        return EmployeeOffboardingChecklistUseCase(
            checklists=self.checklists,  # type: ignore[arg-type]
            templates=self.templates,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def template_uc(self) -> ChecklistItemTemplateUseCase:
        return ChecklistItemTemplateUseCase(
            repository=self.templates,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
        )


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


def _item(*, is_blocking: bool = False, passed: bool | None = None) -> OffboardingChecklistItem:
    return OffboardingChecklistItem(
        item_id=new_offboarding_checklist_item_id(),
        tenant_id=TENANT,
        checklist_id=new_offboarding_checklist_id(),
        position_no=1,
        category=ChecklistItemCategory.EQUIPMENT,
        item_text="Noutbuku geri qaytar",
        is_blocking=is_blocking,
        passed=passed,
        created_at=NOW,
        updated_at=NOW,
    )


# --------------------------------------------------------------------------- #
# Entity: `is_blocking` YALNIZ TAMAMLANMANI bloklayır
# --------------------------------------------------------------------------- #


def test_an_unanswered_blocking_item_blocks_completion() -> None:
    checklist = EmployeeOffboardingChecklist(
        checklist_id=new_offboarding_checklist_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        initiated_by=EmployeeId(uuid.uuid4()),
        created_at=NOW,
        updated_at=NOW,
        items=(_item(is_blocking=True),),
    )
    assert checklist.is_completable is False

    with pytest.raises(ChecklistNotCompletableError):
        checklist.complete(completed_by=EmployeeId(uuid.uuid4()), now=NOW)


def test_a_blocking_item_marked_failed_still_blocks_completion() -> None:
    """`passed=False` — `is_answered` True olsa da HƏLƏ bloklayır (`FieldReport`-dan fərqli)."""
    item = _item(is_blocking=True, passed=False)
    checklist = EmployeeOffboardingChecklist(
        checklist_id=new_offboarding_checklist_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        initiated_by=EmployeeId(uuid.uuid4()),
        created_at=NOW,
        updated_at=NOW,
        items=(item,),
    )
    assert item.is_answered is True
    assert checklist.is_completable is False


def test_a_non_blocking_item_never_blocks_completion() -> None:
    checklist = EmployeeOffboardingChecklist(
        checklist_id=new_offboarding_checklist_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        initiated_by=EmployeeId(uuid.uuid4()),
        created_at=NOW,
        updated_at=NOW,
        items=(_item(is_blocking=False),),
    )
    assert checklist.is_completable is True
    checklist.complete(completed_by=EmployeeId(uuid.uuid4()), now=NOW)
    assert checklist.status is OffboardingStatus.COMPLETED


def test_a_blocking_item_answered_passed_true_unblocks_completion() -> None:
    checklist = EmployeeOffboardingChecklist(
        checklist_id=new_offboarding_checklist_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        initiated_by=EmployeeId(uuid.uuid4()),
        created_at=NOW,
        updated_at=NOW,
        items=(_item(is_blocking=True),),
    )
    checklist.answer_item(item_id=checklist.items[0].id, passed=True, now=NOW)

    assert checklist.is_completable is True
    checklist.complete(completed_by=EmployeeId(uuid.uuid4()), now=NOW)
    assert checklist.completed_at == NOW


def test_a_completed_checklist_cannot_be_answered_or_completed_again() -> None:
    checklist = EmployeeOffboardingChecklist(
        checklist_id=new_offboarding_checklist_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        initiated_by=EmployeeId(uuid.uuid4()),
        created_at=NOW,
        updated_at=NOW,
        items=(_item(is_blocking=False),),
    )
    checklist.complete(completed_by=EmployeeId(uuid.uuid4()), now=NOW)

    with pytest.raises(InvalidStateTransitionError):
        checklist.complete(completed_by=EmployeeId(uuid.uuid4()), now=NOW)
    with pytest.raises(InvalidStateTransitionError):
        checklist.answer_item(item_id=checklist.items[0].id, passed=True, now=NOW)


# --------------------------------------------------------------------------- #
# Use case: `start_checklist` — kateqoriya fallback sayğacı
# --------------------------------------------------------------------------- #


def test_start_checklist_returns_none_without_any_templates(ctx: Ctx) -> None:
    result = ctx.checklist_uc().start_checklist(
        tenant_id=TENANT,
        initiated_by=EmployeeId(uuid.uuid4()),
        employee_id=EmployeeId(uuid.uuid4()),
    )
    assert result is None
    assert ctx.audit.records == []


def test_start_checklist_builds_items_with_the_templates_real_category(ctx: Ctx) -> None:
    """Fallback ARTIQ YOXDUR — hər bənd ÖZ şablonunun kateqoriyasını daşıyır.

    `_template()` (aşağıda) `category=None` QURA BİLMİR (§5 qadağası), ona
    görə bu, indi TƏK mümkün ssenaridir — köhnə "sxem boşluğu" testi bunun
    yerinə keçib.
    """
    ctx.templates.items[uuid.uuid4()] = _template(
        position_no=1, category=ChecklistItemCategory.EQUIPMENT
    )
    ctx.templates.items[uuid.uuid4()] = _template(
        position_no=2, category=ChecklistItemCategory.SETTLEMENT
    )
    initiator = EmployeeId(uuid.uuid4())
    subject = EmployeeId(uuid.uuid4())

    checklist = ctx.checklist_uc().start_checklist(
        tenant_id=TENANT, initiated_by=initiator, employee_id=subject
    )

    assert checklist is not None
    categories = {item.item_text: item.category for item in checklist.items}
    assert categories == {
        "Bənd 1": ChecklistItemCategory.EQUIPMENT,
        "Bənd 2": ChecklistItemCategory.SETTLEMENT,
    }
    # Sayğac ARTIQ YAZILMIR — özü ölü kodla birlikdə silinib.
    assert "items_with_placeholder_category" not in ctx.audit.last()["after_state"]


# --------------------------------------------------------------------------- #
# `ChecklistItemTemplate.__post_init__` — kateqoriya qadağası, İKİ İSTİQAMƏT
# (CLAUDE.md §5: domen tərəfi, DB tərəfi `chk_checklist_template_category_
# by_owner`-dədir, migrations/094)
# --------------------------------------------------------------------------- #


def test_an_offboarding_template_without_a_category_is_rejected() -> None:
    with pytest.raises(InvalidCatalogEntryError, match="kateqoriya MƏCBURİDİR"):
        _template(category=None)


def test_a_field_report_template_with_a_category_is_rejected() -> None:
    with pytest.raises(InvalidCatalogEntryError, match="kateqoriya konsepti yoxdur"):
        ChecklistItemTemplate(
            template_id=new_checklist_item_template_id(),
            tenant_id=TENANT,
            owner_type=ChecklistOwnerType.FIELD_REPORT,
            owner_key="FIELD_REPORT_CLOSE",
            position_no=1,
            item_text="Kassa bağlandı",
            category=ChecklistItemCategory.EQUIPMENT,
        )


# --------------------------------------------------------------------------- #
# Use case: səlahiyyət — açıq istisna
# --------------------------------------------------------------------------- #


def test_answer_item_requires_the_flag(ctx: Ctx) -> None:
    outsider = _employee(flags=())
    checklist_id = new_offboarding_checklist_id()
    with pytest.raises(OffboardingChecklistError, match=MANAGE_OFFBOARDING_FLAG):
        ctx.checklist_uc().answer_item(
            tenant_id=TENANT,
            actor=outsider,
            checklist_id=checklist_id,
            item_id=new_offboarding_checklist_item_id(),
            passed=True,
        )


def test_complete_requires_the_flag(ctx: Ctx) -> None:
    outsider = _employee(flags=())
    with pytest.raises(OffboardingChecklistError, match=MANAGE_OFFBOARDING_FLAG):
        ctx.checklist_uc().complete(
            tenant_id=TENANT, actor=outsider, checklist_id=new_offboarding_checklist_id()
        )


def test_operating_on_an_unknown_checklist_id_raises_not_found(ctx: Ctx) -> None:
    manager = _employee(flags=(MANAGE_OFFBOARDING_FLAG,))
    with pytest.raises(OffboardingChecklistNotFoundError):
        ctx.checklist_uc().complete(
            tenant_id=TENANT, actor=manager, checklist_id=new_offboarding_checklist_id()
        )


def test_complete_via_use_case_still_enforces_the_blocking_rule(ctx: Ctx) -> None:
    """Use case qatı entity qaydasını YENİDƏN YAZMIR, ötürür."""
    manager = _employee(flags=(MANAGE_OFFBOARDING_FLAG,))
    checklist = EmployeeOffboardingChecklist(
        checklist_id=new_offboarding_checklist_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        initiated_by=manager.id,
        created_at=NOW,
        updated_at=NOW,
        items=(_item(is_blocking=True),),
    )
    ctx.checklists.save(checklist)

    with pytest.raises(ChecklistNotCompletableError):
        ctx.checklist_uc().complete(tenant_id=TENANT, actor=manager, checklist_id=checklist.id)


def test_answer_item_and_complete_are_audited(ctx: Ctx) -> None:
    manager = _employee(flags=(MANAGE_OFFBOARDING_FLAG,))
    checklist = EmployeeOffboardingChecklist(
        checklist_id=new_offboarding_checklist_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        initiated_by=manager.id,
        created_at=NOW,
        updated_at=NOW,
        items=(_item(is_blocking=True),),
    )
    ctx.checklists.save(checklist)

    ctx.checklist_uc().answer_item(
        tenant_id=TENANT,
        actor=manager,
        checklist_id=checklist.id,
        item_id=checklist.items[0].id,
        passed=True,
    )
    ctx.checklist_uc().complete(tenant_id=TENANT, actor=manager, checklist_id=checklist.id)

    actions = [r["action"] for r in ctx.audit.records]
    assert actions == ["OFFBOARDING_ITEM_ANSWERED", "OFFBOARDING_CHECKLIST_COMPLETED"]


# --------------------------------------------------------------------------- #
# `ChecklistItemTemplateUseCase` — Root kataloqu
# --------------------------------------------------------------------------- #


def test_list_for_management_requires_the_flag(ctx: Ctx) -> None:
    outsider = _employee(flags=())
    with pytest.raises(CatalogPermissionError):
        ctx.template_uc().list_for_management(
            TENANT,
            outsider,
            owner_type=ChecklistOwnerType.OFFBOARDING,
            owner_key=OFFBOARDING_OWNER_KEY,
        )


def test_list_for_instantiation_does_not_require_any_permission(ctx: Ctx) -> None:
    """Sistem daxili çağırışdır — insan düyməsi deyil (modul başlığı)."""
    ctx.templates.items[uuid.uuid4()] = _template()
    result = ctx.template_uc().list_for_instantiation(
        TENANT, owner_type=ChecklistOwnerType.OFFBOARDING, owner_key=OFFBOARDING_OWNER_KEY
    )
    assert len(result) == 1


def test_list_for_instantiation_excludes_inactive_templates(ctx: Ctx) -> None:
    manager = _employee(flags=(CHECKLIST_TEMPLATES_FLAG,))
    template = _template()
    ctx.templates.items[template.template_id] = template

    ctx.template_uc().deactivate(TENANT, manager, template.template_id)

    result = ctx.template_uc().list_for_instantiation(
        TENANT, owner_type=ChecklistOwnerType.OFFBOARDING, owner_key=OFFBOARDING_OWNER_KEY
    )
    assert result == []


def test_deactivated_templates_are_still_visible_to_management(ctx: Ctx) -> None:
    manager = _employee(flags=(CHECKLIST_TEMPLATES_FLAG,))
    template = _template()
    ctx.templates.items[template.template_id] = template

    ctx.template_uc().deactivate(TENANT, manager, template.template_id)

    result = ctx.template_uc().list_for_management(
        TENANT, manager, owner_type=ChecklistOwnerType.OFFBOARDING, owner_key=OFFBOARDING_OWNER_KEY
    )
    assert len(result) == 1
    assert result[0].is_active is False


def test_save_and_deactivate_are_audited(ctx: Ctx) -> None:
    manager = _employee(flags=(CHECKLIST_TEMPLATES_FLAG,))
    template = _template()

    ctx.template_uc().save(TENANT, manager, template)
    ctx.template_uc().deactivate(TENANT, manager, template.template_id)

    actions = [r["action"] for r in ctx.audit.records]
    assert actions == ["CHECKLIST_ITEM_TEMPLATE_SAVED", "CHECKLIST_ITEM_TEMPLATE_DEACTIVATED"]


# --------------------------------------------------------------------------- #
# `_flag_for_owner` — `owner_type`-a görə BUDAQLANMA (`v2backlog.md` Faza 4.1)
# --------------------------------------------------------------------------- #
#
# OFFBOARDING → `can_manage_employees` (HR-in işi), FIELD_REPORT →
# `can_conduct_store_audit` (auditor-un işi) — İKİSİ FƏRQLİ ROLDUR, ona görə
# BİR flag-in ikisini də ödəməsi TƏSADÜFİ ola bilməz, hər istiqamət ayrıca
# kilidlənir.


def _field_report_template(
    *, position_no: int = 1, owner_key: str = "STORE_AUDIT"
) -> ChecklistItemTemplate:
    return ChecklistItemTemplate(
        template_id=new_checklist_item_template_id(),
        tenant_id=TENANT,
        owner_type=ChecklistOwnerType.FIELD_REPORT,
        owner_key=owner_key,
        position_no=position_no,
        item_text=f"Bənd {position_no}",
        category=None,
    )


def test_field_report_templates_require_the_store_audit_flag_not_the_offboarding_one(
    ctx: Ctx,
) -> None:
    """HR-in `can_manage_employees`-i FIELD_REPORT şablonunu idarə etməyə KİFAYƏT ETMİR."""
    hr_manager = _employee(flags=(CHECKLIST_TEMPLATES_FLAG,))

    with pytest.raises(CatalogPermissionError, match=FIELD_REPORT_CHECKLIST_TEMPLATES_FLAG):
        ctx.template_uc().save(TENANT, hr_manager, _field_report_template())


def test_offboarding_templates_require_the_offboarding_flag_not_the_store_audit_one(
    ctx: Ctx,
) -> None:
    """Auditorun `can_conduct_store_audit`-i OFFBOARDING şablonunu idarə etməyə KİFAYƏT ETMİR."""
    auditor = _employee(flags=(FIELD_REPORT_CHECKLIST_TEMPLATES_FLAG,))

    with pytest.raises(CatalogPermissionError, match=CHECKLIST_TEMPLATES_FLAG):
        ctx.template_uc().save(TENANT, auditor, _template())


def test_an_auditor_can_manage_field_report_templates(ctx: Ctx) -> None:
    auditor = _employee(flags=(FIELD_REPORT_CHECKLIST_TEMPLATES_FLAG,))

    result = ctx.template_uc().save(TENANT, auditor, _field_report_template())

    assert result.action == "saved"


def test_deactivate_reads_the_owner_type_from_the_stored_row_not_the_actor(ctx: Ctx) -> None:
    """`deactivate()` `owner_type`-ı SƏTİRDƏN oxuyur — çağıran onu ötürmür."""
    auditor = _employee(flags=(FIELD_REPORT_CHECKLIST_TEMPLATES_FLAG,))
    template = _field_report_template()
    ctx.templates.items[template.template_id] = template

    result = ctx.template_uc().deactivate(TENANT, auditor, template.template_id)

    assert result.action == "deactivated"
    # HR flag-i ilə eyni sətri deaktiv etmək İSƏ RƏDD OLUNMALIDIR.
    hr_manager = _employee(flags=(CHECKLIST_TEMPLATES_FLAG,))
    other = _field_report_template(position_no=2)
    ctx.templates.items[other.template_id] = other
    with pytest.raises(CatalogPermissionError, match=FIELD_REPORT_CHECKLIST_TEMPLATES_FLAG):
        ctx.template_uc().deactivate(TENANT, hr_manager, other.template_id)


# `offboarding_checklist.MANAGE_OFFBOARDING_FLAG`-in ÖZÜ ilə eynidir (modul
# başlığı: Faza 3.4 yeni flag tələb etmir) — ayrı ad TƏSADÜFİ deyil, testin bu
# bərabərliyə (deyil ki, təsadüfən üst-üstə düşməsinə) etibar etdiyini göstərir.
CHECKLIST_TEMPLATES_FLAG = MANAGE_OFFBOARDING_FLAG
