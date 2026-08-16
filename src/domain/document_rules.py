"""Sənəd bitmə xəbərdarlığı (#17, kompasos11.md Faza 7) — SAF QAYDA.

──────────────────────────────────────────────────────────────────────────────
BU MODUL BLOKLAMIR — YALNIZ XƏBƏRDARLIQ ÜRƏTİR
──────────────────────────────────────────────────────────────────────────────
kompasos11.md Faza 7 #17-nin İNTEQRASİYA bəndi açıq deyir: "admin növbə təyin
edərkən xəbərdarlıq göstərilsin" — BLOKLAMA sözü yoxdur. (Eyni #17-nin sahə
təsvirində mötərizədə "növbəyə təyin edilə bilməsin" yazılıb; iki cümlə
ziddiyyətlidir və İCRA bəndi əsas götürülüb — bax fayl başlığındakı
"İSTİFADƏÇİ MƏTNİNDƏ «BLOKLAYICI» SÖZÜ İŞLƏNMİR".) Bu, #14 Əmək Qanunu
Xəbərdarlığı ilə
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
İSTİFADƏÇİ MƏTNİNDƏ «BLOKLAYICI» SÖZÜ İŞLƏNMİR
──────────────────────────────────────────────────────────────────────────────
Sahənin texniki adı `is_blocking` olaraq qalır (sxem/repo/audit açarı), lakin
HR-ın oxuduğu cümlə həqiqəti deməlidir: heç nə bloklanmır. Əks halda HR
"işçi işə buraxılmır" zənn edər və faktiki nəzarəti heç kim aparmazdı — yəni
ad bir təhlükəsizlik illüziyası yaradardı. Tam əsaslandırma
`entities/employee_document.py`-dakı `ATTENTION_FLAG_LABEL_AZ` başlığındadır
və mətn həmin SABİTDƏN qurulur ki, iki yerdə iki fərqli söz yaranmasın.

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
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

# --------------------------------------------------------------------------- #
# `is_blocking` SAHƏSİNİN İNSAN ETİKETİ
# --------------------------------------------------------------------------- #
#
# Etiket SÜTUNUN yanında (`entities/employee_document.py`) deyil, QAYDANIN
# yanında yaşayır: söz sahənin adını yox, sahənin FAKTİKİ NƏTİCƏSİNİ təsvir
# edir və həmin nəticəni məhz bu modul təyin edir. Sütun bir gün başqa qayda
# üçün də işlənsəydi, etiket burada dəyişər, sxem isə toxunulmaz qalardı.
#
# SÜTUNUN ADI (`employee_documents.is_blocking`, migrations/020) DƏYİŞMİR:
# o, repo sorğusunda, qismən indeksdə (`idx_employee_documents_blocking`),
# domen hadisəsində və KEÇMİŞ audit sətirlərinin açarlarında yaşayır. Yenidən
# adlandırma miqrasiya + tarixi audit uyğunsuzluğu deməkdir və heç bir davranış
# problemini həll etmir — problem adın İNSANA nə vəd etdiyindədir.
#
# İKİ SABİT (böyük/kiçik hərf) QƏSDƏNDİR: `str.capitalize()` çoxsözlü ifadənin
# qalanını kiçildir, `str.title()` isə Azərbaycan `i/İ` qaydasında etibarsızdır
# — hər ikisi ekrandakı mətni sükutla korlayardı.
ATTENTION_FLAG_LABEL_AZ: Final = "Diqqət tələb edən"
ATTENTION_FLAG_LABEL_INLINE_AZ: Final = "diqqət tələb edən"


class DocumentRuleKind(str, Enum):
    """`ScheduleConflict.kind` dəyəri kimi işlədilir (`LaborRuleKind` üslubu).

    ENUM ÜZVÜNÜN ADI VƏ DƏYƏRİ DƏYİŞMİR: `DOCUMENT_EXPIRED_BLOCKING` sətri
    audit `after_state["conflicts"]` siyahısında ARTIQ yazılıb və ekran
    süzgəci ona baxır — dəyişdirmək keçmiş audit sətirlərini oxunmaz edərdi.
    Dəyişən yalnız İNSANIN oxuduğu `message_az`-dır (bax modul başlığı).
    """

    #: Diqqət tələb edən sənəd bitib, işçi yenə də təyin edilir (xəbərdarlıqla).
    EXPIRED_BLOCKING_DOCUMENT = "DOCUMENT_EXPIRED_BLOCKING"


@dataclass(frozen=True)
class BlockingDocumentSnapshot:
    """Diqqət tələb edən (`is_blocking`) bir sənədin YOXLAMA görünüşü.

    `EmployeeDocument` birbaşa işlədilmir — qaydaya nə `id`, nə `file_ref`,
    nə də `uploaded_by` lazımdır (`labor_rules.PlannedShift` ilə eyni əsaslandırma:
    ayrı görüntü aqreqatın DAXİLİ sahələrini qayda mühərrikindən gizlədir).
    """

    doc_type: str
    doc_number: str | None
    expiry_date: date


@dataclass(frozen=True)
class DocumentRuleFinding:
    """Diqqət tələb edən sənədin bitməsi — BLOKLAMIR, xəbərdarlıq edir."""

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
            — bax `DocumentComplianceAdvisor`). Bir işçinin bir NEÇƏ diqqət
            tələb edən sənədi ola bilər — hər biri AYRI tapıntı yaradır ki,
            admin HANSI sənədin bitdiyini görsün.
        blocking_documents: Artıq süzülmüş sətirlər (aktiv, `is_blocking=TRUE`,
            `expiry_date IS NOT NULL`) — bax repository `list_blocking_for_employee`.

    Returns:
        Bitmiş sənədlərin siyahısı. Boş siyahı = pozuntu görünmür.
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
                # Mətn NƏ BAŞ VERDİYİNİ və NƏ BAŞ VERMƏDİYİNİ birlikdə deyir:
                # ikinci hissə olmasa, admin təyinatın sistem tərəfindən
                # dayandırıldığını güman edə bilər (bax modul başlığı).
                message_az=(
                    f"Sənəd xəbərdarlığı: işçinin {ATTENTION_FLAG_LABEL_INLINE_AZ} "
                    f"«{document.doc_type}»{number_suffix} sənədi "
                    f"{document.expiry_date.isoformat()} tarixində bitib. "
                    "Təyinat bloklanmadı — sistem heç nəyi dayandırmır, qərar sizindir."
                ),
            )
        )
    return findings


__all__ = [
    "ATTENTION_FLAG_LABEL_AZ",
    "ATTENTION_FLAG_LABEL_INLINE_AZ",
    "BlockingDocumentSnapshot",
    "DocumentRuleFinding",
    "DocumentRuleKind",
    "evaluate_document_rules",
]
