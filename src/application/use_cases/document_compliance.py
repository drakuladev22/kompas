"""Sənəd bloklama xəbərdarlığının MƏLUMAT YIĞIMI (#17, Faza 7).

`labor_compliance.py` (#14) ilə EYNİ bölgü, EYNİ səbəb: `ShiftPlanningUseCase`
Shift Matrix-in YEGANƏ yazma nöqtəsidir və kompasos11.md-nin qırmızı xətti
onun əsas məntiqinin SİLİNMƏMƏSİ/YENİDƏN YAZILMAMASIdır. Ona görə #17-nin
bütün yeni kodu BURADA yaşayır və planlama use case-inə YALNIZ bir sətirlə
(`self._document_conflicts(...)`) qoşulur:

    * asılılıq İSTƏYƏ BAĞLIDIR (`documents: DocumentComplianceAdvisor | None
      = None`) — mövcud çağırış yerləri və Faza 5/6 testləri imzada heç nə
      dəyişmədən işləyir;
    * qoşulmayıb → `apply_assignment` əvvəlki kimi davranır (fail-open —
      susan qayda admin-in işini dayandırmamalıdır, `labor_compliance.py`-la
      eyni fəlsəfə).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `Clock`, NİYƏ `shift_date` DEYİL
──────────────────────────────────────────────────────────────────────────────
`LaborComplianceAdvisor.review()` `shift_date`-i istinad nöqtəsi kimi işlədir
(gələcək təyinatlar da yoxlanmalıdır). Sənəd bloklaması isə FƏRQLİ sualdır:
"bu işçinin BLOKLAYICI sənədi HAZIRDA (indi) bitibmi?" — HR-ın narahatlığı
gələcək bir tarixdə deyil, işçinin BU AN mağazada olub-olmaması ilə bağlıdır
(sanitar kitabçası, iş icazəsi və s. HAZIRDA qüvvədə olmalıdır). Ona görə
istinad nöqtəsi `Clock.now().date()`-dir, `shift_date` DEYİL — CLAUDE.md §4-ün
"`datetime.now()` YOX, `Clock` portu" tələbi məhz bu determinizm üçündür.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.document_rules import BlockingDocumentSnapshot, evaluate_document_rules

if TYPE_CHECKING:
    from src.domain.document_rules import DocumentRuleFinding
    from src.domain.interfaces.ports import Clock, EmployeeDocumentRepository
    from src.domain.value_objects.identifiers import EmployeeId, TenantId


class DocumentComplianceAdvisor:
    """Bir işçinin aktiv bloklayıcı sənədlərini yoxlayır (yazmır).

    YAZMIR: `LaborComplianceAdvisor`-la eyni əsaslandırma — xəbərdarlıq
    təyinatın NƏTİCƏSİ deyil, ONUN HAQQINDA fikirdir. Audit izi onsuz da
    `apply_assignment`-in `after_state["conflicts"]` sahəsindədir.
    """

    def __init__(
        self,
        *,
        documents: EmployeeDocumentRepository,
        clock: Clock,
    ) -> None:
        self._documents = documents
        self._clock = clock

    def review(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
    ) -> list[DocumentRuleFinding]:
        """İşçinin aktiv, bloklayıcı, bitmə-tarixli sənədlərini yoxlayır.

        `list_blocking_for_employee` artıq süzülmüş qaytarır (aktiv,
        `is_blocking=TRUE`) — `idx_employee_documents_blocking` indeksinin
        oxu tərəfi (migrations/020 başlığı). `expiry_date IS NULL`
        (müddətsiz) sətirlər burada əlavə süzgəclə kənarda qalır, çünki
        onlar heç vaxt "bitmiş" ola bilməz.
        """
        records = self._documents.list_blocking_for_employee(tenant_id, employee_id)
        reference_date = self._clock.now().date()
        snapshots = [
            BlockingDocumentSnapshot(
                doc_type=record.doc_type,
                doc_number=record.doc_number,
                expiry_date=record.expiry_date,
            )
            for record in records
            if record.expiry_date is not None
        ]
        return evaluate_document_rules(reference_date=reference_date, blocking_documents=snapshots)


__all__ = ["DocumentComplianceAdvisor"]
