"""HR Lifecycle v2 repository-ləri (`v2backlog.md` Faza 3.3/3.4) — migrations/088+094.

    PostgresEmployeeTransferRequestRepository    — `employee_transfer_requests`
    PostgresEmployeeOffboardingChecklistRepository — `employee_offboarding_
                                                       checklists` + `..._items`
    PostgresChecklistItemTemplateRepository      — `checklist_item_templates`

──────────────────────────────────────────────────────────────────────────────
RLS-Ə ƏLAVƏ İKİNCİ QAT
──────────────────────────────────────────────────────────────────────────────
Hər sorğuda açıq `tenant_id` şərti var (`self._tenant`) — layihənin bütün
repo-larında olduğu kimi (`field_report_repositories.py` başlığı). RLS
sıradan çıxsa belə (tətbiq səhvən owner rolu ilə qoşulsa) izolyasiya qalır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÜÇÜ BİR FAYLDA
──────────────────────────────────────────────────────────────────────────────
Hər üçü EYNİ miqrasiyanın (088, + 094-ün `category` sütunu) məhsuludur və
kiçikdir — `workflow_repositories.py` ilə eyni əsaslandırma: eyni mənbədən
doğan, biri digərini çağırmayan bir neçə kiçik repo bir faylda saxlanılır.

──────────────────────────────────────────────────────────────────────────────
BƏRPA EDİLƏN AQREQAT HADİSƏ YAYMIR
──────────────────────────────────────────────────────────────────────────────
`EmployeeTransferRequest` və `EmployeeOffboardingChecklist` konstruktorları
`emit_created_event=False` ilə çağırılır (`ShiftSwapRequest`/`FieldReport`
ilə eyni qayda) — əks halda hər `get()` "yeni sorğu göndərildi" hadisəsi
yaradardı.

──────────────────────────────────────────────────────────────────────────────
OFFBOARDING CHECKLIST — İKİ CƏDVƏLLİ AQREQAT, `field_reports` NAXIŞI
──────────────────────────────────────────────────────────────────────────────
`save()` başlığı VƏ bəndlərini EYNİ tranzaksiyada yazır, bəndlər BİR sorğu
ilə (`checklist_id = ANY(...)`) hidratlanır (N+1-in qarşısı). Bəndlər üçün
`DELETE` YOXDUR — `field_report_checklist_items` ilə eyni qərar: audit
bəndinin ("yoxlandı, uğursuzdur") silinməsi bütövlüyü poza bilər.

──────────────────────────────────────────────────────────────────────────────
ŞABLON KATALOQU — `id`-Sİ HƏLƏ TƏYİN OLUNMAYAN OBYEKT
──────────────────────────────────────────────────────────────────────────────
`ChecklistItemTemplate.template_id` `None` ola bilər (yeni bənd hələ
saxlanmayıb). `PostgresWorkModeRepository.save()`-in EYNİ həlli:
`COALESCE(%s, gen_random_uuid())` — Postgres `NULL` göndərilən `id`-ni
avtomatik generasiya edir, Python tərəfində ayrıca ID-yaratma addımı
lazım deyil.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from src.domain.entities.employee_transfer import EmployeeTransferRequest, TransferStatus
from src.domain.entities.offboarding_checklist import (
    EmployeeOffboardingChecklist,
    OffboardingChecklistItem,
    OffboardingStatus,
)
from src.domain.value_objects.catalogs import (
    ChecklistItemCategory,
    ChecklistItemTemplate,
    ChecklistOwnerType,
)
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import date

    from src.domain.value_objects.identifiers import (
        ChecklistItemTemplateId,
        EmployeeId,
        OffboardingChecklistId,
        StoreId,
        TenantId,
        TransferRequestId,
    )

_log = get_logger(__name__)

#: `list_due_for_effect` sorğusu — açıq JOIN, `_SELECT`-in dinamik toxunulması
#: oxunuşu çətinləşdirdiyi üçün AYRI sabitə çıxarılıb (`field_report_
#: repositories.py`-dəki `_STORES_MISSING_AUDIT_QUERY` ilə eyni naxış).
_TRANSFER_DUE_QUERY: Final = """
    SELECT t.id, t.tenant_id, t.employee_id, t.from_store_id, t.to_store_id,
           t.effective_date, t.reason, t.status, t.requested_by, t.decided_by,
           t.decision_reason, t.decided_at, t.created_at
    FROM employee_transfer_requests t
    JOIN employees e ON e.id = t.employee_id
    WHERE t.tenant_id = %s AND t.status = 'APPROVED' AND t.effective_date <= %s
      AND e.store_id IS DISTINCT FROM t.to_store_id
    ORDER BY t.effective_date
"""


# --------------------------------------------------------------------------- #
# EmployeeTransferRequestRepository
# --------------------------------------------------------------------------- #


class PostgresEmployeeTransferRequestRepository(_BaseRepository):
    """`employee_transfer_requests` — `PostgresShiftSwapRepository` İLƏ EYNİ FORMA."""

    _SELECT = """
        SELECT id, tenant_id, employee_id, from_store_id, to_store_id,
               effective_date, reason, status, requested_by, decided_by,
               decision_reason, decided_at, created_at
        FROM employee_transfer_requests
    """

    def get(self, request_id: TransferRequestId) -> EmployeeTransferRequest | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (request_id, self._tenant),
        )
        return _row_to_transfer(row) if row else None

    def list_pending(
        self, tenant_id: TenantId, *, to_store_id: StoreId | None = None
    ) -> list[EmployeeTransferRequest]:
        clauses = ["tenant_id = %s", "status = 'PENDING_APPROVAL'"]
        params: list[Any] = [tenant_id]
        if to_store_id is not None:
            clauses.append("to_store_id = %s")
            params.append(to_store_id)
        # `clauses` SABİT sətir siyahısındandır (bölmə 2-nin S608 istisnası).
        rows = self._fetch_all(
            f"{self._SELECT} WHERE {' AND '.join(clauses)} ORDER BY created_at",
            tuple(params),
        )
        return [_row_to_transfer(row) for row in rows]

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int
    ) -> list[EmployeeTransferRequest]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE employee_id = %s AND tenant_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (employee_id, self._tenant, limit),
        )
        return [_row_to_transfer(row) for row in rows]

    def find_open_for_employee(self, employee_id: EmployeeId) -> EmployeeTransferRequest | None:
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE employee_id = %s AND tenant_id = %s AND status = 'PENDING_APPROVAL'
            """,
            (employee_id, self._tenant),
        )
        return _row_to_transfer(row) if row else None

    def list_due_for_effect(
        self, tenant_id: TenantId, *, as_of: date
    ) -> list[EmployeeTransferRequest]:
        """`APPROVED`, `effective_date <= as_of`, HƏLƏ İCRA OLUNMAYIB (ports.py kontraktı).

        `e.store_id IS DISTINCT FROM t.to_store_id` — `<>` DEYİL: `employees.
        store_id` NULLABLE-dir (`ON DELETE SET NULL`) və sadə `<>` NULL
        tərəfini SÜKUTLA aradan çıxarardı (üç-qiymətli SQL məntiqi) — işçinin
        cari filialı NULL-dursa köçürmə heç vaxt "icra olunmalı" sayılmazdı.
        """
        rows = self._fetch_all(_TRANSFER_DUE_QUERY, (tenant_id, as_of))
        return [_row_to_transfer(row) for row in rows]

    def save(self, request: EmployeeTransferRequest) -> None:
        """UPSERT. `employee_id`/`from_store_id`/`to_store_id`/`reason`/`requested_by`/
        `created_at` YENİLƏMƏDƏ TOXUNULMUR — bunlar MÜŞAHİDƏ ANININ faktıdır
        (`PostgresShiftSwapRepository.save` ilə eyni əsaslandırma)."""
        self._execute(
            """
            INSERT INTO employee_transfer_requests
                (id, tenant_id, employee_id, from_store_id, to_store_id,
                 effective_date, reason, status, requested_by, decided_by,
                 decision_reason, decided_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status          = EXCLUDED.status,
                    decided_by      = EXCLUDED.decided_by,
                    decision_reason = EXCLUDED.decision_reason,
                    decided_at      = EXCLUDED.decided_at
            """,
            (
                request.id,
                request.tenant_id,
                request.employee_id,
                request.from_store_id,
                request.to_store_id,
                request.effective_date,
                request.reason,
                request.status.value,
                request.requested_by,
                request.decided_by,
                request.decision_reason,
                request.decided_at,
                request.created_at,
            ),
        )


def _row_to_transfer(row: dict[str, Any]) -> EmployeeTransferRequest:
    return EmployeeTransferRequest(
        request_id=row["id"],
        tenant_id=row["tenant_id"],
        employee_id=row["employee_id"],
        from_store_id=row["from_store_id"],
        to_store_id=row["to_store_id"],
        reason=row["reason"],
        requested_by=row["requested_by"],
        created_at=row["created_at"],
        effective_date=row["effective_date"],
        status=TransferStatus(row["status"]),
        decided_by=row["decided_by"],
        decision_reason=row["decision_reason"],
        decided_at=row["decided_at"],
        emit_created_event=False,
    )


# --------------------------------------------------------------------------- #
# EmployeeOffboardingChecklistRepository
# --------------------------------------------------------------------------- #


class PostgresEmployeeOffboardingChecklistRepository(_BaseRepository):
    """`employee_offboarding_checklists` + `employee_offboarding_checklist_items` —
    VAHİD aqreqat."""

    _SELECT = """
        SELECT id, tenant_id, employee_id, status, initiated_by,
               completed_by, completed_at, created_at, updated_at
        FROM employee_offboarding_checklists
    """
    _ITEM_SELECT = """
        SELECT id, tenant_id, checklist_id, position_no, category, item_text,
               passed, notes, is_blocking, created_at, updated_at
        FROM employee_offboarding_checklist_items
    """

    def get(self, checklist_id: OffboardingChecklistId) -> EmployeeOffboardingChecklist | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (checklist_id, self._tenant),
        )
        if row is None:
            return None
        return self._hydrate([row])[0]

    def get_active_for_employee(
        self, employee_id: EmployeeId
    ) -> EmployeeOffboardingChecklist | None:
        """`uq_offboarding_active_per_employee` qismən indeksinin güzgüsü (migrations/088)."""
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE employee_id = %s AND tenant_id = %s AND status = 'IN_PROGRESS'
            """,
            (employee_id, self._tenant),
        )
        if row is None:
            return None
        return self._hydrate([row])[0]

    def list_for_employee(self, employee_id: EmployeeId) -> list[EmployeeOffboardingChecklist]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE employee_id = %s AND tenant_id = %s
            ORDER BY created_at DESC
            """,
            (employee_id, self._tenant),
        )
        return self._hydrate(rows)

    def save(self, checklist: EmployeeOffboardingChecklist) -> None:
        """UPSERT — başlıq, sonra bəndlər (aqreqat BİR tranzaksiyada, `field_reports` naxışı).

        `employee_id`/`initiated_by`/`created_at` YENİLƏMƏDƏ TOXUNULMUR —
        müşahidə anının faktıdır.
        """
        self._execute(
            """
            INSERT INTO employee_offboarding_checklists
                (id, tenant_id, employee_id, status, initiated_by,
                 completed_by, completed_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status       = EXCLUDED.status,
                    completed_by = EXCLUDED.completed_by,
                    completed_at = EXCLUDED.completed_at,
                    updated_at   = EXCLUDED.updated_at
            """,
            (
                checklist.id,
                checklist.tenant_id,
                checklist.employee_id,
                checklist.status.value,
                checklist.initiated_by,
                checklist.completed_by,
                checklist.completed_at,
                checklist.created_at,
                checklist.updated_at,
            ),
        )
        for item in checklist.items:
            self._save_item(item)

    def _save_item(self, item: OffboardingChecklistItem) -> None:
        """Bəndin UPSERT-i. `checklist_id`/`position_no`/`category`/`item_text`/
        `is_blocking`/`created_at` YENİLƏMƏDƏ TOXUNULMUR — mətn ŞABLONDAN
        yaradılış anında köçürülür (`field_report_checklist_items.item_text`
        ilə eyni qərar), sonradan şablon dəyişsə belə keçmiş bənd nəyin
        yoxlandığını dəyişməməlidir.
        """
        self._execute(
            """
            INSERT INTO employee_offboarding_checklist_items
                (id, tenant_id, checklist_id, position_no, category, item_text,
                 passed, notes, is_blocking, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET passed     = EXCLUDED.passed,
                    notes      = EXCLUDED.notes,
                    updated_at = EXCLUDED.updated_at
            """,
            (
                item.id,
                item.tenant_id,
                item.checklist_id,
                item.position_no,
                item.category.value,
                item.item_text,
                item.passed,
                item.notes,
                item.is_blocking,
                item.created_at,
                item.updated_at,
            ),
        )

    def _hydrate(self, rows: list[dict[str, Any]]) -> list[EmployeeOffboardingChecklist]:
        """Sətirləri bəndləri ilə birlikdə aqreqata çevirir — bəndlər TƏK sorğu ilə
        (`checklist_id = ANY(...)`), N+1-in qarşısı (`field_reports._hydrate` ilə eyni)."""
        if not rows:
            return []
        checklist_ids = [row["id"] for row in rows]
        item_rows = self._fetch_all(
            f"{self._ITEM_SELECT} WHERE tenant_id = %s AND checklist_id = ANY(%s) "
            "ORDER BY checklist_id, position_no",
            (self._tenant, checklist_ids),
        )
        by_checklist: dict[Any, list[OffboardingChecklistItem]] = {}
        for item_row in item_rows:
            by_checklist.setdefault(item_row["checklist_id"], []).append(_row_to_item(item_row))
        return [_row_to_checklist(row, tuple(by_checklist.get(row["id"], ()))) for row in rows]


def _row_to_item(row: dict[str, Any]) -> OffboardingChecklistItem:
    return OffboardingChecklistItem(
        item_id=row["id"],
        tenant_id=row["tenant_id"],
        checklist_id=row["checklist_id"],
        position_no=int(row["position_no"]),
        category=ChecklistItemCategory(row["category"]),
        item_text=row["item_text"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        # `passed` ÜÇ VƏZİYYƏTLİDİR — `bool(row[...])` YAZILA BİLMƏZ, `field_
        # report_checklist_items` oxucusu ilə EYNİ qayda.
        passed=None if row["passed"] is None else bool(row["passed"]),
        is_blocking=bool(row["is_blocking"]),
        notes=row["notes"],
    )


def _row_to_checklist(
    row: dict[str, Any], items: tuple[OffboardingChecklistItem, ...]
) -> EmployeeOffboardingChecklist:
    return EmployeeOffboardingChecklist(
        checklist_id=row["id"],
        tenant_id=row["tenant_id"],
        employee_id=row["employee_id"],
        initiated_by=row["initiated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        items=items,
        status=OffboardingStatus(row["status"]),
        completed_by=row["completed_by"],
        completed_at=row["completed_at"],
    )


# --------------------------------------------------------------------------- #
# ChecklistItemTemplateRepository
# --------------------------------------------------------------------------- #


class PostgresChecklistItemTemplateRepository(_BaseRepository):
    """`checklist_item_templates` — Root-un idarə etdiyi ORTAQ şablon kataloqu
    (Faza 3.4 + 4.1, migrations/088 + 094)."""

    _SELECT = """
        SELECT id, tenant_id, owner_type, owner_key, position_no, item_text,
               is_blocking, photo_required, is_active, deactivated_at, category
        FROM checklist_item_templates
    """

    def get(self, template_id: ChecklistItemTemplateId) -> ChecklistItemTemplate | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (template_id, self._tenant),
        )
        return _row_to_template(row) if row else None

    def list_for_owner(
        self,
        tenant_id: TenantId,
        *,
        owner_type: ChecklistOwnerType,
        owner_key: str,
        include_inactive: bool = False,
    ) -> list[ChecklistItemTemplate]:
        """`position_no` sırası ilə (ports.py kontraktı)."""
        clauses = ["tenant_id = %s", "owner_type = %s", "owner_key = %s"]
        params: list[Any] = [tenant_id, owner_type.value, owner_key]
        if not include_inactive:
            clauses.append("is_active")
        # `clauses` SABİT sətir siyahısındandır (bölmə 2-nin S608 istisnası).
        rows = self._fetch_all(
            f"{self._SELECT} WHERE {' AND '.join(clauses)} ORDER BY position_no",
            tuple(params),
        )
        return [_row_to_template(row) for row in rows]

    def save(self, template: ChecklistItemTemplate, *, changed_by: EmployeeId) -> None:
        """UPSERT. `id` `None`-dursa Postgres avtomatik generasiya edir —
        `PostgresWorkModeRepository.save`-in EYNİ `COALESCE` naxışı (fayl başlığı)."""
        self._execute(
            """
            INSERT INTO checklist_item_templates
                (id, tenant_id, owner_type, owner_key, position_no, item_text,
                 is_blocking, photo_required, is_active, deactivated_at, category)
            VALUES (COALESCE(%s, gen_random_uuid()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET position_no    = EXCLUDED.position_no,
                    item_text      = EXCLUDED.item_text,
                    is_blocking    = EXCLUDED.is_blocking,
                    photo_required = EXCLUDED.photo_required,
                    is_active      = EXCLUDED.is_active,
                    deactivated_at = EXCLUDED.deactivated_at,
                    category       = EXCLUDED.category
            """,
            (
                template.template_id,
                template.tenant_id,
                template.owner_type.value,
                template.owner_key,
                template.position_no,
                template.item_text,
                template.is_blocking,
                template.photo_required,
                template.is_active,
                template.deactivated_at,
                template.category.value if template.category is not None else None,
            ),
        )
        _log.info(
            "CHECKLIST_ITEM_TEMPLATE_SAVED",
            extra={"owner_type": template.owner_type.value, "changed_by": str(changed_by)},
        )

    def deactivate(
        self, tenant_id: TenantId, template_id: ChecklistItemTemplateId, *, changed_by: EmployeeId
    ) -> None:
        self._execute(
            """
            UPDATE checklist_item_templates
               SET is_active = FALSE, deactivated_at = now()
             WHERE id = %s AND tenant_id = %s
            """,
            (template_id, tenant_id),
        )
        _log.info(
            "CHECKLIST_ITEM_TEMPLATE_DEACTIVATED",
            extra={"template_id": str(template_id), "changed_by": str(changed_by)},
        )


def _row_to_template(row: dict[str, Any]) -> ChecklistItemTemplate:
    return ChecklistItemTemplate(
        template_id=row["id"],
        tenant_id=row["tenant_id"],
        owner_type=ChecklistOwnerType(row["owner_type"]),
        owner_key=str(row["owner_key"]),
        position_no=int(row["position_no"]),
        item_text=str(row["item_text"]),
        is_blocking=bool(row["is_blocking"]),
        photo_required=bool(row["photo_required"]),
        is_active=bool(row["is_active"]),
        deactivated_at=row["deactivated_at"],
        category=None if row["category"] is None else ChecklistItemCategory(row["category"]),
    )


__all__ = [
    "PostgresChecklistItemTemplateRepository",
    "PostgresEmployeeOffboardingChecklistRepository",
    "PostgresEmployeeTransferRequestRepository",
]
