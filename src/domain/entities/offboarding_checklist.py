"""Struktur offboarding checklist-i (`v2backlog.md` Faza 3.4).

──────────────────────────────────────────────────────────────────────────────
BU AQREQAT DEAKTİVASİYANI BLOKLAMIR — LAKİN ÖZ TAMAMLANMASINI BLOKLAYIR
──────────────────────────────────────────────────────────────────────────────
DİZAYN QƏRARI (komanda rəhbərinin açıq buraxdığı sual): `UserManagementUseCase.
deactivate_employee()` HEÇ VAXT BLOKLAMIR (`OffboardingReview` modul başlığı,
CLAUDE.md-nin "işdən çıxarma hüquqi faktdır" prinsipi) — bu checklist onu
DƏYİŞMİR, `deactivate_employee()` uğurla bitdikdən SONRA `IN_PROGRESS`
statusunda YARADILIR və deaktivasiyanın nəticəsini GERİ QAYTARMIR.

LAKİN `complete()` metodunun ÖZÜ `is_blocking` bəndləri yoxlayır və hamısı
`passed=True` olmayana qədər rədd edir. Bu, `field_report.py`-dakı `close()`
naxışından FƏRQLİDİR (o, bloklanan bəndi AYRI düzəliş-tapşırığına yönləndirir
və auditin özünü bağlamağa qoyur) — səbəb domendəki fərqdir: sahə auditinin
"bağlanması" HADİSƏNİN qeydə alınmasıdır (baş verdi, nəticəsi nə olursa olsun),
offboarding checklist-in "tamamlanması" isə ONUN BÜTÜN MƏQSƏDİDİR — "avadanlıq
geri qaytarıldı, son haqq-hesab bağlandı" YOXLANMADAN checklist-i "tamamlandı"
kimi işarələmək, checklist-in ÖZÜNÜ mənasız edərdi. Offboarding üçün ayrıca
"düzəliş tapşırığı" mexanizmi YOXDUR (field_reports-dan fərqli olaraq) —
bloklanan bənd YALNIZ checklist-in tamamlanmasını gecikdirməklə görünən qalır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİ SİNİF (`ChecklistItem` `AggregateRoot` DEYİL)
──────────────────────────────────────────────────────────────────────────────
`FieldReportChecklistItem` ilə EYNİ qərar: bəndin müstəqil həyat dövrü yoxdur,
valideynlə birlikdə yaranır və yazılır (birləşmiş FK, migrations/088). Hadisəni
də valideyn yayır.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError, InvalidStateTransitionError
from src.domain.value_objects.catalogs import ChecklistItemCategory
from src.domain.value_objects.identifiers import (
    EmployeeId,
    OffboardingChecklistId,
    OffboardingChecklistItemId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: `employee_offboarding_checklist_items.item_text` CHECK-inin güzgüsü (`>= 3`).
SCHEMA_MIN_ITEM_TEXT_LENGTH: Final = 3

#: Bura yenidən EXPORT edilir ki, `entities/offboarding_checklist.py`-a
#: baxan kod (`ChecklistItemCategory` istifadəçiləri) `value_objects/catalogs.py`-a
#: birbaşa getməli olmasın — `field_report.py`-dakı oxşar naxışlarla eyni,
#: MÖVQE hissəsinin ÖZÜ isə `catalogs.py`-dadır (təkrarlanmır, bax
#: `ChecklistItemTemplate.category`).


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class OffboardingStatus(str, Enum):
    """`employee_offboarding_checklists.status` — DB `CHECK` ilə EYNİ."""

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ChecklistNotCompletableError(DomainRuleError):
    """`is_blocking` bəndlər həll olunmadan checklist tamamlana bilməz."""

    user_message = "Bağlayıcı bəndlər hələ tamamlanmayıb — checklist bağlana bilməz."


class OffboardingChecklistItem:
    """Offboarding checklist-in BİR bəndi (`employee_offboarding_checklist_items`)."""

    def __init__(
        self,
        *,
        item_id: OffboardingChecklistItemId,
        tenant_id: TenantId,
        checklist_id: OffboardingChecklistId,
        position_no: int,
        category: ChecklistItemCategory,
        item_text: str,
        created_at: datetime,
        updated_at: datetime,
        passed: bool | None = None,
        is_blocking: bool = False,
        notes: str | None = None,
    ) -> None:
        cleaned_text = normalise_decision_text(item_text)
        if len(cleaned_text) < SCHEMA_MIN_ITEM_TEXT_LENGTH:
            raise DomainRuleError(
                f"Checklist bəndinin mətni minimum {SCHEMA_MIN_ITEM_TEXT_LENGTH} simvol olmalıdır",
                user_message="Checklist bəndinin mətni çox qısadır.",
                context={"item_text": item_text},
            )
        if position_no < 1:
            raise DomainRuleError(
                "Checklist bəndinin sırası 1-dən kiçik ola bilməz",
                user_message="Checklist sırası düzgün deyil.",
                context={"position_no": position_no},
            )

        self.id = item_id
        self.tenant_id = tenant_id
        self.checklist_id = checklist_id
        self.position_no = position_no
        self.category = category
        self.item_text = cleaned_text
        self.is_blocking = is_blocking
        self.passed = passed
        self.notes = _clean_optional(notes)
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")

    def answer(self, *, passed: bool, now: datetime, notes: str | None = None) -> None:
        """Bəndi cavablayır (tamamlandı/tamamlanmadı)."""
        self.passed = passed
        if notes is not None:
            self.notes = _clean_optional(notes)
        self.updated_at = require_aware(now, field="now")

    @property
    def is_answered(self) -> bool:
        return self.passed is not None

    @property
    def blocks_completion(self) -> bool:
        """Bu bənd checklist-in bağlanmasını GECİKDİRİRMİ.

        Cavabsız (`None`) VƏ `passed=False` — hər ikisi bağlayıcıdır: "hələ
        yoxlanılmayıb" da "avadanlıq geri qaytarıldı" demək DEYİL.
        `FieldReportChecklistItem.is_blocking_failure`-dan FƏRQ budur (orada
        yalnız `passed is False` sayılır) — səbəb modul başlığındakı fərqdir.
        """
        return self.is_blocking and self.passed is not True

    def __repr__(self) -> str:
        return (
            f"OffboardingChecklistItem(no={self.position_no}, "
            f"passed={self.passed}, blocking={self.is_blocking})"
        )


class EmployeeOffboardingChecklist(AggregateRoot):
    """Bir işdən-çıxma dövrünün checklist-i (`employee_offboarding_checklists`)."""

    def __init__(
        self,
        *,
        checklist_id: OffboardingChecklistId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        initiated_by: EmployeeId,
        created_at: datetime,
        updated_at: datetime,
        items: tuple[OffboardingChecklistItem, ...] = (),
        status: OffboardingStatus = OffboardingStatus.IN_PROGRESS,
        completed_by: EmployeeId | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self.id = checklist_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.initiated_by = initiated_by
        self.items = items
        self.status = status
        self.completed_by = completed_by
        self.completed_at = completed_at
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")

    @property
    def blocking_open_items(self) -> tuple[OffboardingChecklistItem, ...]:
        """Checklist-in bağlanmasını gecikdirən bəndlər — ekranın göstərdiyi siyahı."""
        return tuple(item for item in self.items if item.blocks_completion)

    @property
    def is_completable(self) -> bool:
        return not self.blocking_open_items

    def answer_item(
        self,
        *,
        item_id: OffboardingChecklistItemId,
        passed: bool,
        now: datetime,
        notes: str | None = None,
    ) -> OffboardingChecklistItem:
        if self.status is OffboardingStatus.COMPLETED:
            raise InvalidStateTransitionError(
                "Tamamlanmış checklist-in bəndi dəyişdirilə bilməz",
                user_message="Bu checklist artıq bağlanıb.",
                context={"checklist_id": str(self.id)},
            )
        for item in self.items:
            if item.id == item_id:
                item.answer(passed=passed, now=now, notes=notes)
                self.updated_at = require_aware(now, field="now")
                return item
        raise DomainRuleError(
            "Checklist bəndi tapılmadı",
            user_message="Bu bənd checklist-də mövcud deyil.",
            context={"checklist_id": str(self.id), "item_id": str(item_id)},
        )

    def complete(self, *, completed_by: EmployeeId, now: datetime) -> None:
        """Checklist-i bağlayır — `is_blocking` bəndlər HƏLL OLUNMAYIBSA rədd edir.

        `chk_offboarding_completion` DB məhdudiyyəti (migrations/088:
        `COMPLETED` → `completed_at`/`completed_by` MƏCBURİ) burada domen
        səviyyəsində GÜCLƏNDİRİLİR — modul başlığındakı əsaslandırma.
        """
        if self.status is OffboardingStatus.COMPLETED:
            raise InvalidStateTransitionError(
                "Checklist artıq tamamlanıb",
                user_message="Bu checklist artıq bağlanıb.",
                context={"checklist_id": str(self.id)},
            )
        blocking = self.blocking_open_items
        if blocking:
            names = ", ".join(item.item_text for item in blocking)
            raise ChecklistNotCompletableError(
                f"Bağlayıcı bəndlər hələ həll olunmayıb: {names}",
                context={"checklist_id": str(self.id), "blocking_count": len(blocking)},
            )
        self.status = OffboardingStatus.COMPLETED
        self.completed_by = completed_by
        self.completed_at = require_aware(now, field="now")
        self.updated_at = self.completed_at

    def __repr__(self) -> str:
        return (
            f"EmployeeOffboardingChecklist(id={self.id}, employee={self.employee_id}, "
            f"status={self.status.value}, items={len(self.items)})"
        )


__all__ = [
    "SCHEMA_MIN_ITEM_TEXT_LENGTH",
    "ChecklistItemCategory",
    "ChecklistNotCompletableError",
    "EmployeeOffboardingChecklist",
    "OffboardingChecklistItem",
    "OffboardingStatus",
]
