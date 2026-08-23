"""Cərimə etirazı aqreqatı (spesifikasiya bölmə 4 — ETİRAZ MEXANİZMİ).

    "İşçi hər cərimə/override-a qarşı 72 saat ərzində etiraz göndərə bilər.
     Etiraz HR_Admin-ə düşür, qərar audit-lənir, cərimə ləğv/azaldıla bilər
     amma orijinal qeyd heç vaxt silinmir (yalnız «REVERSED» statusu əlavə
     olunur)."

──────────────────────────────────────────────────────────────────────────────
ETİRAZ NİYƏ AYRI AQREQATDIR
──────────────────────────────────────────────────────────────────────────────
`Fine`-ın öz sahəsi kimi saxlamaq cəlbedici olardı, amma iki şey buna manedir:

    1. Etirazın ÖZ həyat dövrü var (`PENDING` → `APPROVED`/`REJECTED`/`EXPIRED`)
       və o, cərimənin dövrü ilə üst-üstə düşmür — cərimə `PUBLISHED` qalır,
       etiraz isə qərar alır.
    2. Qərar VERƏN (`can_approve_leave_appeal` sahibi HR_Admin) cəriməni
       YARADANDAN (`can_issue_fines`, kamera) fərqlidir. İki aktoru bir
       aqreqatda saxlamaq "kim nə etdi" izini bulandırardı.

DB tərəfi də belədir: `fine_appeals` ayrıca cədvəldir, `UNIQUE (fine_id)` ilə
— bir cəriməyə BİR etiraz.

──────────────────────────────────────────────────────────────────────────────
`EXPIRED` NİYƏ VAR — VƏ NİYƏ SON SÖZ DEYİL (M-6)
──────────────────────────────────────────────────────────────────────────────
Pəncərə bağlananda cavabsız qalmış etiraz sükutla itmir: `cron_close_expired_appeals`
onu `EXPIRED` edir. Bu, "HR cavab vermədi" halını "işçi etiraz etmədi" halından
ayırır — birincisi proses problemidir və hesabatda görünməlidir.

LAKİN `EXPIRED` "rədd edildi" DEMƏK DEYİL. 72 saat İŞÇİNİN GÖNDƏRMƏ hüququnun
müddətidir (bölmə 4: "işçi ... 72 saat ərzində etiraz göndərə bilər") — HR-ın
cavab vermə borcunun müddəti deyil, spesifikasiya belə bir müddət təyin
ETMİR. Ona görə müddəti bitmiş etiraz da qərar ala bilir: `approve()` və
`reject()` həm `PENDING`, həm `EXPIRED` vəziyyətindən işləyir.

Əks qərar — "EXPIRED terminaldır" — HR-ın süstlüyünü işçi üçün avtomatik
məğlubiyyətə çevirərdi: cərimə qüvvədə qalar, export-a düşər, pul kəsilər və
etiraza HEÇ VAXT baxılmazdı. Cəriməni bu müddətdə export-dan saxlayan qayda
`Fine.is_exportable`-dədir (dördüncü şərt).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import FineAppealSubmittedEvent
from src.domain.value_objects.identifiers import (
    AppealId,
    EmployeeId,
    FineId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: `fine_appeals.reason` — DB `CHECK (char_length(trim(reason)) >= 10)`.
MIN_APPEAL_REASON_LENGTH: Final[int] = 10
#: Qərar izahı — cərimə ləğvi ilə eyni minimum.
MIN_DECISION_NOTE_LENGTH: Final[int] = 10

#: `is_overdue()` üçün fallback SLA. `DEFAULT_APPEAL_WINDOW_HOURS` ilə eyni
#: dəyər, lakin ONDAN İDXAL EDİLMİR: `appeal.py` `fine.py`-dan asılı deyil və
#: bu asılılığı bir sabit üçün yaratmaq iki aqreqatı bir-birinə bağlayardı.
MIN_APPEAL_SLA_HOURS: Final[int] = 72


class AppealStatus(str, Enum):
    """`fine_appeals.status` — DB `appeal_status` enum-u ilə EYNİ."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    @property
    def is_open(self) -> bool:
        return self is AppealStatus.PENDING

    @property
    def is_decided(self) -> bool:
        """HR QƏRAR VERDİMİ (M-6).

        `EXPIRED` burada `False`-dur: müddətin bitməsi qərar deyil, qərarın
        GECİKMƏSİDİR. Məhz bu fərq cərimənin export kilidini saxlayır
        (`Fine.is_exportable` dördüncü şərti).
        """
        return self in (AppealStatus.APPROVED, AppealStatus.REJECTED)


class FineAppeal(AggregateRoot):
    """İşçinin bir cəriməyə qarşı etirazı.

    PENDING ──approve(yeni məbləğ?)──> APPROVED  (cərimə REVERSED/REDUCED)
       │                                   ↑
       ├────reject(izah)────────────> REJECTED  (cərimə toxunulmaz qalır)
       │                                   ↑
       └────expire()────────────────> EXPIRED ──┘ (cron; qərar HƏLƏ mümkündür)
    """

    def __init__(
        self,
        *,
        appeal_id: AppealId,
        tenant_id: TenantId,
        fine_id: FineId,
        employee_id: EmployeeId,
        reason: str,
        created_at: datetime,
        status: AppealStatus = AppealStatus.PENDING,
        decided_by: EmployeeId | None = None,
        decision_note: str | None = None,
        decided_at: datetime | None = None,
        new_amount: Money | None = None,
        document_reference: str | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_APPEAL_REASON_LENGTH:
            raise DomainRuleError(
                f"Etiraz səbəbi minimum {MIN_APPEAL_REASON_LENGTH} simvol olmalıdır",
                user_message="Etirazınızı bir az ətraflı yazın.",
                context={"length": len(cleaned)},
            )

        self.id = appeal_id
        self.tenant_id = tenant_id
        self.fine_id = fine_id
        self.employee_id = employee_id
        self.reason = cleaned
        self.status = status
        self.decided_by = decided_by
        self.decision_note = decision_note
        self.decided_at = decided_at
        self.new_amount = new_amount
        #: İşçinin etiraza əlavə etdiyi SƏNƏDİN istinadı (UX-4).
        #:
        #: ────────────────────────────────────────────────────────────────
        #: NİYƏ İSTİNAD, NİYƏ FAYLIN ÖZÜ DEYİL
        #: ────────────────────────────────────────────────────────────────
        #: Dəyər `StorageReference` formatındadır
        #: (`GOOGLE_DRIVE:<connection_id>:<file_id>`) — `employee_documents.
        #: file_ref` və `support_messages.attachment_ref` ilə EYNİ naxış.
        #: Faylın ÖZÜ Drive-dadır; aqreqat yalnız «hansı sənəd?» sualına
        #: cavab verir. Sahə adı `document_reference`-dir, sütun isə
        #: `fine_appeals.document_ref` — `_url` DEYİL, çünki dəyər URL deyil.
        #:
        #: ────────────────────────────────────────────────────────────────
        #: NİYƏ GÖNDƏRMƏ ANINDA `None` OLUR
        #: ────────────────────────────────────────────────────────────────
        #: Kioskda seçilən fayl DƏRHAL Drive-a getmir — sübut yükləmə
        #: növbəsinə (`EvidenceUploadQueue`) düşür və şəbəkə qayıdanda
        #: yüklənir. Etirazın ÖZÜ isə gözləyə bilməz: 72 saatlıq pəncərə
        #: işləyir və zəif internetə görə itirilə bilməz. Ona görə sətir
        #: sənədsiz yaranır, istinad isə yükləmə bitəndə
        #: `attach_uploaded_document()` ilə yazılır
        #: (`FieldReportUseCase.attach_uploaded_photo` ilə eyni ayrım).
        #:
        #: SƏNƏD İSTƏYƏ BAĞLIDIR (`None` qanuni haldır): etiraz mətni tək
        #: başına kifayətdir — sənədi məcbur etmək internetsiz filialda
        #: işçini etiraz hüququndan məhrum edərdi.
        self.document_reference = _clean_reference(document_reference)
        self.created_at = require_aware(created_at, field="created_at")

        if emit_created_event and status is AppealStatus.PENDING:
            self.record_event(
                FineAppealSubmittedEvent(
                    tenant_id=tenant_id,
                    actor_id=employee_id,
                    appeal_id=appeal_id,
                    fine_id=fine_id,
                    employee_id=employee_id,
                    reason=cleaned,
                )
            )

    # -------------------------------- sənəd ---------------------------------- #

    def attach_document(self, *, document_reference: str) -> bool:
        """Yüklənmiş sənədin istinadını yazır — növbə bitdikdə çağırılır (UX-4).

        ──────────────────────────────────────────────────────────────────────
        QƏRAR VERİLMİŞ ETİRAZDA DA İCAZƏLİDİR — QƏSDƏN
        ──────────────────────────────────────────────────────────────────────
        `_require_decidable()` BURADA ÇAĞIRILMIR. Səbəb: bu, iş qərarı deyil,
        İNFRASTRUKTUR TAMAMLANMASIDIR (`FieldReportItem.attach_photo` ilə eyni
        ayrım). Yükləmə dəqiqələr, zəif şəbəkədə saatlar çəkə bilər və bu
        müddətdə HR qərar vermiş ola bilər — həmin halda istinadı ATMAQ
        istifadəçinin göndərdiyi sübutu sükutla itirmək olardı, halbuki sənəd
        məhz qərarın SƏNƏDLİ əsasıdır və mübahisə halında lazım olacaq.

        TƏKRAR ÇAĞIRIŞ İSTİSNA ATMIR: eyni yükləmə növbə tərəfindən iki dəfə
        təsdiqlənə bilər (`FieldReport.add_photo` ilə eyni əsaslandırma) —
        istisna atsaydıq geri-çağırış çökər və növbə elementi əbədi
        `PROCESSING`-də qalardı.

        Returns:
            İstinad DƏYİŞDİmi. `False` = eyni dəyər artıq yazılıb (çağıran
            yalnız `True` halında yazır və audit sətri qurur).
        """
        cleaned = _clean_reference(document_reference)
        if cleaned is None:
            raise DomainRuleError(
                "Sənəd istinadı boş ola bilməz",
                user_message="Sənəd istinadı boşdur.",
                context={"appeal_id": str(self.id)},
            )
        if cleaned == self.document_reference:
            return False
        self.document_reference = cleaned
        return True

    @property
    def has_document(self) -> bool:
        """Etiraza sənəd əlavə edilibmi (ekran nişanı üçün)."""
        return self.document_reference is not None

    # -------------------------------- qərar ---------------------------------- #

    def approve(
        self,
        *,
        decided_by: EmployeeId,
        decided_at: datetime,
        note: str,
        new_amount: Money | None = None,
    ) -> None:
        """Etiraz qəbul edildi — cərimə ləğv və ya azaldılır.

        `new_amount` `None` və ya sıfırdırsa cərimə TAM ləğv edilir; müsbətdirsə
        azaldılır (`REDUCED`). Cəriməyə faktiki toxunuş use case-dədir — etiraz
        aqreqatı `Fine`-ı birbaşa dəyişmir, çünki ikisi ayrı tranzaksiya
        obyektləridir və birinin digərini mutasiya etməsi asılılığı tərsinə
        çevirərdi.
        """
        self._require_decidable()
        self._require_note(note)
        if decided_by == self.employee_id:
            raise DomainRuleError(
                "İşçi öz etirazına özü qərar verə bilməz",
                user_message="Öz etirazınıza qərar verə bilməzsiniz.",
                context={"employee_id": str(self.employee_id)},
            )

        self.status = AppealStatus.APPROVED
        self.decided_by = decided_by
        self.decided_at = require_aware(decided_at, field="decided_at")
        self.decision_note = normalise_decision_text(note)
        self.new_amount = new_amount

    def reject(self, *, decided_by: EmployeeId, decided_at: datetime, note: str) -> None:
        """Etiraz rədd edildi — cərimə olduğu kimi qalır.

        İZAH MƏCBURİDİR (`_require_note`, min. 10 simvol): işçi nəyə görə
        rədd edildiyini bilməlidir — cərimə real pul kəsintisidir və
        "rədd edildi" sözü tək başına cavab deyil.
        """
        self._require_decidable()
        self._require_note(note)
        if decided_by == self.employee_id:
            raise DomainRuleError(
                "İşçi öz etirazına özü qərar verə bilməz",
                user_message="Öz etirazınıza qərar verə bilməzsiniz.",
                context={"employee_id": str(self.employee_id)},
            )

        self.status = AppealStatus.REJECTED
        self.decided_by = decided_by
        self.decided_at = require_aware(decided_at, field="decided_at")
        self.decision_note = normalise_decision_text(note)

    def expire(self, *, now: datetime) -> bool:
        """Cavabsız qalmış etirazı bağlayır (planlaşdırılmış iş).

        Returns:
            Vəziyyət dəyişdisə `True` — çağıran yalnız o zaman yazır.
        """
        if not self.status.is_open:
            return False
        self.status = AppealStatus.EXPIRED
        self.decided_at = require_aware(now, field="now")
        return True

    # ------------------------------ göstəricilər ------------------------------ #

    def age_hours(self, *, now: datetime) -> float:
        """Neçə saatdır cavab gözləyir — SLA göstəricisi."""
        require_aware(now, field="now")
        return (now - self.created_at).total_seconds() / 3600

    def is_overdue(self, *, now: datetime, sla_hours: int = MIN_APPEAL_SLA_HOURS) -> bool:
        """SLA aşılıbmı — HR inbox-unda vurğulanır.

        `sla_hours` DEFOLTU FALLBACK-dır, tək həqiqət mənbəyi DEYİL: pəncərə
        `system_limits.FINE_APPEAL_WINDOW_HOURS`-dan gəlir və Root onu dəyişə
        bilər (bölmə 3). Çağıran tərəf limiti AÇIQ ötürməlidir — defolt yalnız
        tenant konteksti olmayan yollar üçündür.

        ŞƏRT `is_open` DEYİL, `not is_decided`-dir (M-6): `EXPIRED` sətir məhz
        SLA-nı aşmış sətirdir və onu "gecikməyib" saymaq inbox-un ən vacib
        sətirlərini vurğusuz buraxardı.
        """
        return not self.status.is_decided and self.created_at + timedelta(hours=sla_hours) < now

    def _require_decidable(self) -> None:
        """Qərar YALNIZ verilməmiş etiraza (PENDING və ya EXPIRED) verilə bilər.

        `EXPIRED` QƏSDƏN BURAYA DAXİLDİR (M-6, sinif başlığı): müddətin
        bitməsi HR-ın cavabını əvəz etmir. `APPROVED`/`REJECTED` isə kənardadır
        — artıq verilmiş qərarın üstündən yazmaq audit izini bulandırardı və
        işçiyə iki fərqli nəticə bildirilərdi.
        """
        if self.status.is_decided:
            raise DomainRuleError(
                "Bu etiraz artıq qərar alıb",
                user_message="Bu etiraz artıq emal edilib.",
                context={"status": self.status.value},
            )

    @staticmethod
    def _require_note(note: str) -> None:
        if len(normalise_decision_text(note)) < MIN_DECISION_NOTE_LENGTH:
            raise DomainRuleError(
                f"Qərar izahı minimum {MIN_DECISION_NOTE_LENGTH} simvol olmalıdır",
                user_message="Qərarınızın səbəbini ətraflı yazın.",
            )

    def __repr__(self) -> str:
        return f"FineAppeal(id={self.id}, fine={self.fine_id}, status={self.status.value})"


def _clean_reference(value: str | None) -> str | None:
    """Boş/yalnız-boşluqlu istinadı `None`-a çevirir (UX-4).

    Boş sətri OLDUĞU KİMİ saxlamaq `has_document` xassəsini yalanlayardı:
    ekran «sənəd var» nişanı göstərər, açanda isə heç nə tapılmazdı.
    """
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


__all__ = [
    "MIN_APPEAL_REASON_LENGTH",
    "MIN_APPEAL_SLA_HOURS",
    "MIN_DECISION_NOTE_LENGTH",
    "AppealStatus",
    "FineAppeal",
]
