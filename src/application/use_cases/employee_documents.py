"""İşçi Sənəd/Müqavilə İdarəetməsi (#17, kompasos11.md Faza 7).

`can_manage_employee_documents` sahibi sənəd qeydini yaradır, redaktə edir,
fayl bağlayır və (soft) deaktiv edir. CLAUDE.md §6 use case naxışı: hər yazı
metodu səlahiyyət → domen qaydası (entity-də) → yazma → audit ardıcıllığı ilə
işləyir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SELF-ESCALATION/HİYERARXİYA QAYDASI YOXDUR (`pos_threshold.py`-dan FƏRQ)
──────────────────────────────────────────────────────────────────────────────
POS həddi funksional SƏLAHİYYƏT qeydidir ("bu işçi endirim edə bilərmi?") və
ona görə Strict Hierarchy/Self-Escalation Guard tələb edir. Sənəd qeydi isə
uyğunluq (compliance) SƏNƏDİDİR — "bu işçinin müqaviləsi nə vaxt bitir?"
sualının cavabı HR-ın ÖZÜNƏ də aid ola bilər (öz müqaviləsini qeydə ala bilər)
və pillə fərqi bu əməliyyatda risk yaratmır (heç bir icazə/səlahiyyət
GENİŞLƏNMİR). Yeganə qapı `can_manage_employee_documents` flag-idir.

──────────────────────────────────────────────────────────────────────────────
BİTMƏ XƏBƏRDARLIĞININ TƏKRARSIZLIĞI — ƏLAVƏ DB SÜTUNU YOXDUR
──────────────────────────────────────────────────────────────────────────────
`notify_expiring_documents` "artıq bildirildi" sütunu/cədvəli YARATMIR (Faza 7
tapşırığının "yeni bildiriş mexanizmi yazma" tələbi). Əvəzinə BƏRABƏRLİK
yoxlanır: `günlər_qalıb == hədd`. Sənədin bitmə tarixi SABİTDİR, ona görə hər
hədd (30/14/7) YALNIZ BİR təqvim günündə bərabərliyi təmin edir — iş gündə bir
dəfə işlədiyi müddətcə bu, əlavə vəziyyət saxlamadan təbii təkrarsızlıqdır.
Güzəşt: iş bir gün buraxılarsa (server dayanıqlığı və s.) həmin günün
xəbərdarlığı itə bilər — bu, yeni DB sütunu əlavə etməkdən (migrations/028-in
əhatəsi YALNIZ `system_limits` seed-idir, bax miqrasiya başlığı) daha ucuz
güzəşt sayılıb.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from src.domain.document_rules import ATTENTION_FLAG_LABEL_INLINE_AZ
from src.domain.entities.employee_document import EmployeeDocument
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import AuthorizationError
from src.domain.value_objects.identifiers import new_employee_document_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import date

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        EmployeeDocumentRepository,
        EmployeeRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeDocumentId, EmployeeId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Faza 2-də kataloqa əlavə edilmiş flag (migrations/021).
MANAGE_EMPLOYEE_DOCUMENTS_FLAG = "can_manage_employee_documents"

#: `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` üçün FALLBACK. HƏQİQİ MƏNBƏ
#: `system_limits`-dir (migrations/028 seed edir) — bax `policies.py`.
_FALLBACK_WARNING_DAYS: Final = DEFAULT_LIMITS[SystemLimitKey.EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS]

#: Bitmə xəbərdarlığının bildiriş kateqoriyası — auditoriyası
#: `TENANT_NOTIFICATION_AUDIENCE`-də qeydiyyatdadır (`domain/value_objects/notifications.py`).
EXPIRY_NOTIFICATION_CATEGORY = "EMPLOYEE_DOCUMENT_EXPIRING"


class EmployeeDocumentError(KompasOSError):
    """Sənəd əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Sənəd qeydi ilə bağlı əməliyyat icra edilə bilmədi."


class EmployeeDocumentNotFoundError(EmployeeDocumentError):
    user_message = "Bu sənəd qeydi tapılmadı."


@dataclass(frozen=True)
class EmployeeDocumentDraft:
    """Yeni sənəd formasının məzmunu."""

    doc_type: str
    doc_number: str | None
    expiry_date: date | None
    is_blocking: bool
    #: Artıq yüklənmiş faylın istinadı (`str(StorageReference)`) — YÜKLƏMƏ
    #: MƏNTİQİ BURADA DEYİL. Kontroller `EvidenceStorageProvider.upload()`-u
    #: ÖZÜ çağırır (bax `controllers/employee_documents.py` başlığı) və
    #: nəticəni bura ötürür — use case Drive-ı TANIMIR (domen/tətbiq qatı
    #: `psycopg`/Drive API idxal etmir, CLAUDE.md §3).
    file_ref: str | None = None


class EmployeeDocumentUseCase:
    """`can_manage_employee_documents` sahibi sənəd qeydlərini yazır/oxuyur."""

    def __init__(
        self,
        *,
        documents: EmployeeDocumentRepository,
        employees: EmployeeRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._documents = documents
        self._employees = employees
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # -------------------------------- oxuma ------------------------------------ #

    def list_for_employee(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        include_inactive: bool = False,
    ) -> list[EmployeeDocument]:
        """İşçi redaktə ekranının "Sənədlər" bölməsi."""
        self._require_permission(actor, tenant_id)
        return self._documents.list_for_employee(
            tenant_id, employee_id, include_inactive=include_inactive
        )

    # -------------------------------- yazı ------------------------------------- #

    def create_document(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        draft: EmployeeDocumentDraft,
    ) -> EmployeeDocument:
        """Yeni sənəd sətri yaradır — UPSERT DEYİL (bir işçinin ÇOX sənədi ola bilər)."""
        self._require_permission(actor, tenant_id)
        now = self._clock.now()
        document = EmployeeDocument(
            document_id=new_employee_document_id(),
            tenant_id=tenant_id,
            employee_id=employee_id,
            doc_type=draft.doc_type,
            doc_number=draft.doc_number,
            file_ref=draft.file_ref,
            expiry_date=draft.expiry_date,
            is_blocking=draft.is_blocking,
            uploaded_by=actor.id,
            created_at=now,
            updated_at=now,
        )
        self._documents.save(document)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_DOCUMENT_CREATED",
            entity_type="employee_documents",
            entity_id=document.id,
            before_state=None,
            after_state=_snapshot(document),
        )
        return document

    def update_document(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        document_id: EmployeeDocumentId,
        doc_number: str | None,
        expiry_date: date | None,
        is_blocking: bool,
    ) -> EmployeeDocument:
        """Redaktə edilə bilən sahələri yeniləyir (`doc_type` DƏYİŞMİR)."""
        self._require_permission(actor, tenant_id)
        document = self._require_document(document_id)
        before_state = _snapshot(document)
        document.update(
            doc_number=doc_number,
            expiry_date=expiry_date,
            is_blocking=is_blocking,
            now=self._clock.now(),
        )
        self._documents.save(document)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_DOCUMENT_UPDATED",
            entity_type="employee_documents",
            entity_id=document.id,
            before_state=before_state,
            after_state=_snapshot(document),
        )
        return document

    def attach_file(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        document_id: EmployeeDocumentId,
        file_ref: str,
    ) -> EmployeeDocument:
        """Skanı bağlayır — `file_ref` NULL-dan dolur (HR faylı sonra əlavə edə bilər)."""
        self._require_permission(actor, tenant_id)
        document = self._require_document(document_id)
        before_state = _snapshot(document)
        document.attach_file(file_ref=file_ref, now=self._clock.now())
        self._documents.save(document)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_DOCUMENT_FILE_ATTACHED",
            entity_type="employee_documents",
            entity_id=document.id,
            before_state=before_state,
            after_state=_snapshot(document),
        )
        return document

    def attach_uploaded_file(
        self,
        *,
        tenant_id: TenantId,
        document_id: EmployeeDocumentId,
        file_ref: str,
    ) -> None:
        """Sübut yükləmə NÖVBƏSİ (`EvidenceUploadWorker`) bitdikdə çağırılır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `attach_file`-DAN AYRI METOD, `actor` YOXDUR
        ──────────────────────────────────────────────────────────────────────
        Fayl HR ekranında SEÇİLƏN anda `can_manage_employee_documents` artıq
        yoxlanılıb (`controllers/employee_documents.py`, sənəd yaradılan
        tranzaksiyada). Faylın Drive-a yüklənməsi isə arxa planda, bir neçə
        saniyə/dəqiqə SONRA bitir — həmin anda ekran qarşısında oturan aktor
        obyekti ARTIQ YOXDUR (`composition.py: _attach_evidence` geri-çağırışı
        `EvidenceUploadWorker`-dən gəlir, istifadəçi sessiyasından deyil).
        İkinci dəfə səlahiyyət yoxlamaq mümkün deyil və lazım da deyil —
        əməliyyat artıq TƏSDİQLƏNİB, bura yalnız NƏTİCƏNİN gəlib çatmasıdır
        (`repositories.py`-dəki `Fine.attach_drive_evidence`-in EYNİ qərarı:
        infrastruktur tamamlanması, yeni iş qərarı DEYİL).

        Domen qaydası (`_require_active`, boş `file_ref` qadağası) YENƏ DƏ
        `EmployeeDocument.attach_file()` ÜZƏRİNDƏN tətbiq olunur — bura yalnız
        SƏLAHİYYƏT qatını buraxır, DOMEN qaydasını yox.

        Audit YENƏ DƏ yazılır (fərqli əməliyyat adı ilə): kimin sənədi HANSI
        vaxt fiziki əlçatan olduğu HR uyğunluq yoxlamasında sual doğura bilər,
        ona görə "yazılmayıb" sükutu qəbul edilməzdir (CLAUDE.md §5).
        `actor_id` sənədi YARADAN şəxsdir (`uploaded_by`) — canlı aktor yoxdur.
        """
        document = self._require_document(document_id)
        before_state = _snapshot(document)
        document.attach_file(file_ref=file_ref, now=self._clock.now())
        self._documents.save(document)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=document.uploaded_by,
            action="EMPLOYEE_DOCUMENT_FILE_UPLOAD_COMPLETED",
            entity_type="employee_documents",
            entity_id=document.id,
            before_state=before_state,
            after_state=_snapshot(document),
        )

    def deactivate_document(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        document_id: EmployeeDocumentId,
        reason: str,
    ) -> EmployeeDocument:
        """Soft delete — sətir SİLİNMİR (migrations/020 başlığı)."""
        self._require_permission(actor, tenant_id)
        document = self._require_document(document_id)
        before_state = _snapshot(document)
        document.deactivate(reason=reason, deactivated_by=actor.id, now=self._clock.now())
        self._documents.save(document)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_DOCUMENT_DEACTIVATED",
            entity_type="employee_documents",
            entity_id=document.id,
            before_state=before_state,
            after_state=_snapshot(document),
            reason=document.deactivation_reason,
        )
        return document

    # ------------------------------ planlanmış -------------------------------- #

    def notify_expiring_documents(self, tenant_id: TenantId) -> int:
        """Bitmə tarixinə 30/14/7 gün qalan sənədlər üçün xəbərdarlıq göndərir.

        PLANLAŞDIRILMIŞ İŞDİR (bax `fine_management.expire_stale`,
        `behavior_baseline.recalculate_all` ilə EYNİ forma) — actor YOXDUR,
        çünki bunu bir istifadəçi düyməsi yox, gecə işi çağırır.

        Returns:
            Göndərilən xəbərdarlıq sayı.
        """
        thresholds = self._expiry_warning_days(tenant_id)
        if not thresholds:
            return 0

        today = self._clock.now().date()
        horizon = today + timedelta(days=max(thresholds))
        sent = 0
        for document in self._documents.list_expiring(tenant_id, on_or_before=horizon):
            if document.expiry_date is None:
                continue  # müdafiə xətti — repo sorğusu onsuz da süzür
            days_left = (document.expiry_date - today).days
            if days_left not in thresholds:
                continue  # bax modul başlığı: bərabərlik = təkrarsızlıq
            self._send_expiry_warning(tenant_id=tenant_id, document=document, days_left=days_left)
            sent += 1
        return sent

    def _send_expiry_warning(
        self, *, tenant_id: TenantId, document: EmployeeDocument, days_left: int
    ) -> None:
        employee = self._employees.get(document.employee_id)
        employee_label = employee.full_name if employee is not None else str(document.employee_id)
        # « (BLOKLAYICI)» YAZILMIR: sənəd bitəndə heç nə bloklanmır, yalnız
        # növbə təyinatında xəbərdarlıq görünür (bax `domain/document_rules.py`
        # başlığı). Köhnə söz HR-a "işçi işə buraxılmayacaq" vəd edirdi və
        # gecəlik iş həmin vədi hər 30/14/7 gündə təkrarlayırdı.
        blocking_note = f" ({ATTENTION_FLAG_LABEL_INLINE_AZ})" if document.is_blocking else ""
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category=EXPIRY_NOTIFICATION_CATEGORY,
            title_az="İşçi sənədinin bitmə tarixi yaxınlaşır",
            body_az=(
                f"{employee_label} işçisinin «{document.doc_type}»{blocking_note} sənədinin "
                f"bitmə tarixinə {days_left} gün qalıb "
                f"({document.expiry_date.isoformat() if document.expiry_date else '-'})."
            ),
            # Gecə işi ekran qarşısında gözləyən yoxdur — "mövcud e-poçt
            # fallback-ını çağır" tələbinin icrası MƏHZ budur (`notify()`
            # yalnız `is_critical=True` olduqda dərhal e-poçt cəhdi edir,
            # bax `infrastructure/notifications/notifier.py`).
            is_critical=True,
        )

    # ------------------------------- köməkçi ------------------------------------ #

    def _require_permission(self, actor: Employee, tenant_id: TenantId) -> None:
        if actor.tenant_id != tenant_id:
            # Üçüncü izolyasiya qatı (RLS və repo `tenant_id` şərtindən sonra).
            raise AuthorizationError(
                "Aktor bu kirayəçiyə aid deyil",
                context={"actor_id": str(actor.id)},
            )
        now = self._clock.now()
        if not actor.has_permission(MANAGE_EMPLOYEE_DOCUMENTS_FLAG, now=now):
            _security_log.warning(
                "EMPLOYEE_DOCUMENT_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_EMPLOYEE_DOCUMENTS_FLAG},
            )
            raise AuthorizationError(
                f"«{MANAGE_EMPLOYEE_DOCUMENTS_FLAG}» səlahiyyəti yoxdur",
                context={"flag": MANAGE_EMPLOYEE_DOCUMENTS_FLAG},
            )

    def _require_document(self, document_id: EmployeeDocumentId) -> EmployeeDocument:
        document = self._documents.get(document_id)
        if document is None:
            raise EmployeeDocumentNotFoundError(
                "Sənəd qeydi tapılmadı", context={"document_id": str(document_id)}
            )
        return document

    def _expiry_warning_days(self, tenant_id: TenantId) -> frozenset[int]:
        """`EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`-i tam ədəd dəstinə çevirir.

        Yararsız/mənfi hissələr sükutla ATILIR — konfiqurasiya səhvi
        (məs. Root səhvən "30,,7" yazsa) bütün gecəlik işi dayandırmamalıdır
        (`get_int`-in "defolt qaytar, jurnal et" fəlsəfəsi ilə eyni ruh).
        """
        raw = self._limits.get_str(
            tenant_id,
            SystemLimitKey.EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS.value,
            _FALLBACK_WARNING_DAYS,
        )
        days: set[int] = set()
        for piece in raw.split(","):
            cleaned = piece.strip()
            if not cleaned:
                continue
            try:
                value = int(cleaned)
            except ValueError:
                continue
            if value > 0:
                days.add(value)
        return frozenset(days)


def _snapshot(document: EmployeeDocument) -> dict[str, object]:
    return {
        "doc_type": document.doc_type,
        "doc_number": document.doc_number,
        "file_ref": document.file_ref,
        "expiry_date": document.expiry_date.isoformat() if document.expiry_date else None,
        "is_blocking": document.is_blocking,
        "is_active": document.is_active,
    }


__all__ = [
    "EXPIRY_NOTIFICATION_CATEGORY",
    "MANAGE_EMPLOYEE_DOCUMENTS_FLAG",
    "EmployeeDocumentDraft",
    "EmployeeDocumentError",
    "EmployeeDocumentNotFoundError",
    "EmployeeDocumentUseCase",
]
