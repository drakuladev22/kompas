"""Sənəd bitmə xəbərdarlığı (#17, kompasos11.md Faza 7) — SAF QAYDA.

──────────────────────────────────────────────────────────────────────────────
BU MODUL BLOKLAMIR — YALNIZ XƏBƏRDARLIQ ÜRƏTİR
──────────────────────────────────────────────────────────────────────────────
kompasos11.md Faza 7 #17 açıq deyir: "admin növbə təyin edərkən xəbərdarlıq
göstərilsin" — BLOKLAMA sözü yoxdur. Bu, #14 Əmək Qanunu Xəbərdarlığı ilə
(`domain.labor_rules`) EYNİ qərardır və eyni səbəbdən: real mağazada işçinin
bloklayıcı sənədi (məs. sanitar kitabçası) bitibsə, admin yenə də onu növbəyə
qoymaq MƏCBURİYYƏTİNDƏ qala bilər (əvəzedici yoxdur) — sistem bunu FİZİKİ
mümkünsüz etsəydi, admin təyinatı KompasOS-dan KƏNARDA (kağızda) edərdi və
sistem məlumatsız qalardı. Xəbərdarlıq isə qərarı MƏLUMATLI edir və audit
izində qalır (son qərar admindədir).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAF DOMEN MODULU — I/O YOXDUR
──────────────────────────────────────────────────────────────────────────────
`labor_rules.py`-la EYNİ bölgü: qayda repository/`Clock` tanımır, ona hazır
`BlockingDocumentSnapshot` siyahısı və hazır `reference_date` verilir.
Məlumat yığımı `application.use_cases.document_compliance.
DocumentComplianceAdvisor`-dadır — beləliklə qayda testləri bazasız və
determinstikdir.

──────────────────────────────────────────────────────────────────────────────
SƏRHƏD GÜNÜ: `expiry_date == reference_date` → HƏLƏ BİTMƏYİB
──────────────────────────────────────────────────────────────────────────────
`EmployeeDocument.is_expired_on` ilə EYNİ konvensiya: sənəd bitmə tarixinin
ÖZÜ boyunca qüvvədədir, yalnız ONDAN SONRAKI gündən "bitmiş" sayılır. Əks
konvensiya (bərabərlik = bitmiş) HR-ın "bu gün bitir" kimi başa düşdüyü
sənədi artıq keçmişdə saya bilərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class DocumentRuleKind(str, Enum):
    """`ScheduleConflict.kind` dəyəri kimi işlədilir (`LaborRuleKind` üslubu)."""

    #: Bloklayıcı sənəd bitib, işçi yenə də təyin edilir (xəbərdarlıqla).
    EXPIRED_BLOCKING_DOCUMENT = "DOCUMENT_EXPIRED_BLOCKING"


@dataclass(frozen=True)
class BlockingDocumentSnapshot:
    """Bir bloklayıcı sənədin YOXLAMA üçün minimal görünüşü.

    `EmployeeDocument` birbaşa işlədilmir — qaydaya nə `id`, nə `file_ref`,
    nə də `uploaded_by` lazımdır (`labor_rules.PlannedShift` ilə eyni əsaslandırma:
    ayrı görüntü aqreqatın DAXİLİ sahələrini qayda mühərrikindən gizlədir).
    """

    doc_type: str
    doc_number: str | None
    expiry_date: date


@dataclass(frozen=True)
class DocumentRuleFinding:
    """Bir bloklayıcı sənədin bitməsi — BLOKLAYICI DEYİL, xəbərdarlıqdır."""

    kind: DocumentRuleKind
    doc_type: str
    expiry_date: date
    message_az: str


def evaluate_document_rules(
    *,
    reference_date: date,
    blocking_documents: Sequence[BlockingDocumentSnapshot],
) -> list[DocumentRuleFinding]:
    """`blocking_documents`-i `reference_date`-ə qarşı yoxlayır.

    Args:
        reference_date: Yoxlamanın aparıldığı gün (adətən `Clock.now().date()`
            — bax `DocumentComplianceAdvisor`). Bir işçinin bir NEÇƏ
            bloklayıcı sənədi ola bilər — hər biri AYRI tapıntı yaradır ki,
            admin HANSI sənədin bitdiyini görsün.
        blocking_documents: Artıq süzülmüş sətirlər (aktiv, `is_blocking=TRUE`,
            `expiry_date IS NOT NULL`) — bax repository `list_blocking_for_employee`.

    Returns:
        Bitmiş bloklayıcı sənədlərin siyahısı. Boş siyahı = pozuntu görünmür.
    """
    findings: list[DocumentRuleFinding] = []
    for document in blocking_documents:
        if document.expiry_date >= reference_date:
            continue
        number_suffix = f" (№{document.doc_number})" if document.doc_number else ""
        findings.append(
            DocumentRuleFinding(
                kind=DocumentRuleKind.EXPIRED_BLOCKING_DOCUMENT,
                doc_type=document.doc_type,
                expiry_date=document.expiry_date,
                message_az=(
                    f"Sənəd xəbərdarlığı: işçinin bloklayıcı «{document.doc_type}»"
                    f"{number_suffix} sənədi {document.expiry_date.isoformat()} tarixində "
                    "bitib. Təyinat bloklanmadı — qərar sizindir."
                ),
            )
        )
    return findings


__all__ = [
    "BlockingDocumentSnapshot",
    "DocumentRuleFinding",
    "DocumentRuleKind",
    "evaluate_document_rules",
]
