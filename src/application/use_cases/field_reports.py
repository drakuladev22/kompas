"""Sahə hesabatları — VAHİD NÜVƏ, İKİ ŞABLON (#26+#27, kompas1.md Faza 3).

──────────────────────────────────────────────────────────────────────────────
STRUKTUR QƏRAR A — NİYƏ BİR USE CASE, İKİ ŞABLON
──────────────────────────────────────────────────────────────────────────────
Mağaza ziyarəti/auditi (#26) və insident bildirişi (#27) ekranda fərqli
görünür, LAKİN eyni axındır::

    forma → (istəyə görə) foto → avtomatik düzəliş-tapşırığı → Dashboard

İki paralel use case (`StoreAuditUseCase` + `IncidentReportUseCase`) yazsaydıq,
foto qaydası, status keçidləri, marşrutlama və audit yazısı İKİ nüsxədə
yaşayardı — və üçüncü şablon ("Təchizat yoxlaması", "Təhlükəsizlik reydi")
lazım olanda hər ikisi dəyişməli olardı. `migrations/037` DB tərəfində məhz
bu qərarı verib: `type`/`category` sərt `CHECK` DEYİL, KATALOQDUR.

Ona görə bu faylda **`if report_type == "STORE_AUDIT"` zənciri YOXDUR**.
Şablonlar arasındakı BÜTÜN fərqlər MƏLUMATDAN oxunur:

  * checklist tələb olunurmu → `FieldReportTemplate.requires_checklist`
  * hansı səlahiyyət lazımdır → HƏMİN sahədən çıxarılır (aşağı bax)
  * hesabat hansı rola gedir → `FieldReportCategory.route_to_role`

Presedent: `domain/exception_rules.py` (rule-registry) və `migrations/018`-in
`exceptions.source` qərarı.

──────────────────────────────────────────────────────────────────────────────
SƏLAHİYYƏT ŞABLONUN ADINDAN YOX, TƏBİƏTİNDƏN ÇIXIR
──────────────────────────────────────────────────────────────────────────────
İki flag var (`migrations/038`): `can_conduct_store_audit` YALNIZ
Root/CEO/Admin/HR_Admin-də, `can_report_incident` isə BÜTÜN rollarda.

`{"STORE_AUDIT": ..., "INCIDENT": ...}` sözlüyü yazmaq ən qısa yol olardı,
lakin o, şablon KODUNU koda bağlayardı — yeni şablon əlavə edən adam sözlüyü
də yeniləməyi unudanda hesabat "naməlum şablon" ilə rədd edilərdi.

Əvəzinə sual belə qoyulur: **bu, strukturlaşdırılmış YOXLAMADIR, yoxsa
sərbəst MÜŞAHİDƏ?** Cavabı kataloq onsuz da saxlayır — `requires_checklist`.
Strukturlaşdırılmış yoxlama auditdir və məhdud səlahiyyət tələb edir; sərbəst
müşahidə isə hər kəsin bildirə bilməli olduğu şeydir (038, Tələ 3: "hər kəs
insident bildirə bilməlidir, YALNIZ HƏLLİ məhduddur"). Beləliklə gələcək
checklist-li şablon avtomatik olaraq audit səlahiyyəti tələb edir, sərbəst
şablon isə hamıya açıq qalır — KOD DƏYİŞMİR.

BAĞLANMA (`start_progress`/`close`) HƏMİŞƏ `can_conduct_store_audit` tələb
edir, şablondan ASILI OLMADAN: 038 bunu açıq yazır — bildirmək sərbəstdir,
həll etmək deyil.

──────────────────────────────────────────────────────────────────────────────
STRUKTUR QƏRAR B — TAPŞIRIQ MÜHƏRRİKİ ÇAĞIRILIR, YENİSİ YAZILMIR
──────────────────────────────────────────────────────────────────────────────
Uğursuz BLOKLAYICI bənd mövcud `TaskWorkflowUseCase.assign()`-ı çağırır. Yeni
status maşını, yeni təsdiq axını, yeni cədvəl YOXDUR — düzəliş tapşırığı
mövcud `can_assign_tasks` / `can_approve_task_evidence` axınında davam edir.

TAPŞIRIQ YALNIZ `passed IS FALSE AND is_blocking` halında yaranır. `None`
(hələ yoxlanılmayıb) tapşırıq YARATMIR — `migrations/037`-dəki qismən
indeksin predikatı ilə EYNİ (`FieldReportChecklistItem.is_blocking_failure`).

TAPŞIRIQ YARADILA BİLMİRSƏ HESABAT DA YAZILMIR: `assign()` istisnası
UDULMUR. Səbəb — sükutla atlanan tapşırıq "yanğın çıxışı bağlıdır" tapıntısını
heç kimə çatmadan itirərdi; aktora aydın xəta göstərmək (və tranzaksiyanı geri
qaytarmaq) yeganə dürüst davranışdır. Praktikada bu vəziyyət yalnız səhv
konfiqurasiyada yaranır: `can_conduct_store_audit` daşıyan dörd rolun
HAMISINDA `can_assign_tasks` var (`schema.sql` §23).

──────────────────────────────────────────────────────────────────────────────
#27 MARŞRUTLAMA — KATALOQDAN, `if` İLƏ YOX
──────────────────────────────────────────────────────────────────────────────
`field_report_categories.route_to_role` bir `positions.code` dəyəridir.
Marşrutlama iki addımdır və hər ikisi FAIL-SAFE-dir:

  1. Rol kodu AKTİV işçilərə çevrilir (`list_route_recipients`). Hər birinə
     ŞƏXSİ bildiriş gedir — şəxsi sətir auditoriya süzgəcindən ASILI DEYİL
     (`notifications.py` başlığı, "ŞƏXSİ SƏTİR").
  2. Marşrut boşdursa (audit kateqoriyaları belədir) VƏ YA həmin rolda aktiv
     işçi yoxdursa, bildiriş tenant-broadcast kimi gedir və
     `TENANT_NOTIFICATION_AUDIENCE["FIELD_REPORT_ROUTED"]` onu
     `can_conduct_store_audit` sahiblərinə daraldır. Süzgəcsiz sətir
     FAIL-OPEN olardı — `Satıcı` "oğurluq şübhəsi" bildirişini görərdi.

NAMƏLUM/DEAKTİV KATEQORİYA: YENİ hesabat üçün rədd edilir (aydın mesajla —
soft delete-in bütün mənası "artıq seçilməsin"dir), MÖVCUD hesabatın
marşrutlanması isə çökmür (kateqoriya sonradan söndürülə bilər; həmin an
bildirişi partlatmaq keçmiş sətri oxunmaz edərdi).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from src.application.use_cases.task_workflow import TaskDraft
from src.domain.entities.field_report import (
    FieldReport,
    FieldReportChecklistItem,
)
from src.domain.entities.task import TaskPriority
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import AuthorizationError
from src.domain.value_objects.field_reports import FieldReportStatus
from src.domain.value_objects.identifiers import (
    FieldReportId,
    new_field_report_id,
    new_field_report_item_id,
    new_task_id,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.application.use_cases.task_workflow import TaskWorkflowUseCase
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        FieldReportCatalog,
        FieldReportRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.field_reports import (
        ChecklistItemDraft,
        FieldReportCategory,
        FieldReportTemplate,
    )
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        FieldReportItemId,
        StoreId,
        TaskId,
        TenantId,
    )

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_app_log = get_logger(__name__)

#: Faza 2-də kataloqa əlavə edilmiş flag-lər (migrations/038).
CONDUCT_AUDIT_FLAG = "can_conduct_store_audit"
REPORT_INCIDENT_FLAG = "can_report_incident"

#: Bildiriş kateqoriyaları — auditoriyası `TENANT_NOTIFICATION_AUDIENCE`-də
#: qeydiyyatdadır (`domain/value_objects/notifications.py`).
ROUTED_NOTIFICATION_CATEGORY = "FIELD_REPORT_ROUTED"
AUDIT_DUE_NOTIFICATION_CATEGORY = "FIELD_REPORT_AUDIT_DUE"

#: FALLBACK-lar — HƏQİQİ MƏNBƏ `system_limits` (seed: migrations/039).
#: Sinifdə sabit YALNIZ bu formada ola bilər (CLAUDE.md §5).
_FALLBACK_MAX_PHOTOS: Final = int(DEFAULT_LIMITS[SystemLimitKey.FIELD_REPORT_MAX_PHOTOS])
_FALLBACK_MIN_DETAIL: Final = int(DEFAULT_LIMITS[SystemLimitKey.FIELD_REPORT_MIN_DETAIL_LENGTH])
_FALLBACK_TASK_DEADLINE_DAYS: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.FIELD_REPORT_TASK_DEADLINE_DAYS]
)
_FALLBACK_AUDIT_INTERVAL_DAYS: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.FIELD_REPORT_AUDIT_INTERVAL_DAYS]
)
_FALLBACK_TASK_ASSIGNEE_ROLE: Final = DEFAULT_LIMITS[SystemLimitKey.FIELD_REPORT_TASK_ASSIGNEE_ROLE]


class FieldReportError(KompasOSError):
    """Sahə hesabatı əməliyyatı icra edilə bilmədi."""

    user_message = "Sahə hesabatı ilə bağlı əməliyyat icra edilə bilmədi."


class FieldReportNotFoundError(FieldReportError):
    user_message = "Bu sahə hesabatı tapılmadı."


class UnknownFieldReportTemplateError(FieldReportError):
    """Şablon/kateqoriya kataloqda yoxdur və ya söndürülüb."""

    user_message = "Seçilmiş hesabat növü və ya kateqoriya artıq mövcud deyil."


@dataclass(frozen=True)
class FieldReportDraft:
    """Formanın topladığı sahələr — HƏR İKİ şablon üçün EYNİ struktur.

    `checklist` boş ola bilər: insident şablonunda checklist YOXDUR və bu,
    `if` ilə yox, kataloqun `requires_checklist` dəyəri ilə yoxlanılır.
    """

    report_type: str
    category: str
    store_id: StoreId
    detail: str
    photo_refs: tuple[str, ...] = ()
    checklist: tuple[ChecklistItemDraft, ...] = ()


@dataclass(frozen=True)
class FieldReportSubmission:
    """Təqdimatın nəticəsi — ekranın istifadəçiyə göstərəcəyi xülasə."""

    report: FieldReport
    #: Uğursuz BLOKLAYICI bəndlərdən doğan düzəliş tapşırıqları (Qərar B).
    corrective_task_ids: tuple[TaskId, ...] = ()
    #: Kataloqdan oxunan marşrut rolu — `None` = marşrutlanmır (audit).
    routed_role: str | None = None
    #: Neçə nəfərə ŞƏXSİ bildiriş getdi. 0 = broadcast ehtiyat yolu işlədi.
    routed_recipients: int = 0


@dataclass
class AuditReminderResult:
    """Gecəlik xatırlatma işinin nəticəsi — planlayıcının `result_detail`-i."""

    checked: int = 0
    overdue: list[str] = field(default_factory=list)

    @property
    def overdue_count(self) -> int:
        return len(self.overdue)


class FieldReportUseCase:
    """#26 və #27-nin VAHİD nüvəsi — şablon fərqi kataloqdan oxunur."""

    def __init__(
        self,
        *,
        reports: FieldReportRepository,
        catalog: FieldReportCatalog,
        tasks: TaskWorkflowUseCase,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._reports = reports
        self._catalog = catalog
        # TAPŞIRIQ MÜHƏRRİKİ USE CASE KİMİ ÖTÜRÜLÜR, repo kimi YOX: tapşırığın
        # audit yazısı, bildirişi və `TASK_ENGINE` toggle yoxlaması onun
        # daxilindədir (`TaskWorkflowUseCase.assign`). Repo-ya birbaşa yazsaydıq,
        # düzəliş tapşırıqları həmin üç qatı YAN KEÇƏRDİ — yəni "mövcud motoru
        # çağır" tələbi formal olaraq yerinə yetirilər, faktiki olaraq isə
        # ikinci, zəif bir yol açılardı.
        self._tasks = tasks
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # -------------------------------- oxuma ------------------------------------ #

    def list_templates(self, *, tenant_id: TenantId, actor: Employee) -> list[FieldReportTemplate]:
        """Forma seçicisi — aktorun YAZA BİLDİYİ şablonlar.

        Süzgəc "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipidir (bölmə 3): `Satıcı`
        audit şablonunu siyahıda görməməlidir, çünki seçsə də təqdim edə
        bilməz — göstərmək yalnız rədd mesajı yaradardı.
        """
        now = self._clock.now()
        return [
            template
            for template in self._catalog.list_templates(tenant_id)
            if actor.has_permission(self._flag_for(template), now=now)
        ]

    def list_categories(
        self, *, tenant_id: TenantId, actor: Employee, report_type: str
    ) -> list[FieldReportCategory]:
        """Seçilmiş şablonun AKTİV kateqoriyaları."""
        template = self._require_template(tenant_id, report_type)
        self._require(actor, tenant_id, self._flag_for(template))
        return self._catalog.list_categories(tenant_id, report_type=template.code)

    def list_open(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_ids: list[StoreId] | None = None,
        report_type: str | None = None,
    ) -> list[FieldReport]:
        """Açıq hesabatlar — YALNIZ həll edə bilən rol görür.

        Oxu qapısı `can_conduct_store_audit`-dir, `can_report_incident` YOX:
        ikincisi bütün rollarda var (038), yəni onunla qapılan siyahı hər
        `Satıcı`-ya bütün filialların insidentlərini göstərərdi.
        """
        self._require(actor, tenant_id, CONDUCT_AUDIT_FLAG)
        return self._reports.list_open(
            tenant_id,
            store_ids=store_ids,
            report_type=report_type,
            limit=self._page_size(tenant_id),
        )

    # -------------------------------- yazı ------------------------------------- #

    def submit(
        self, *, tenant_id: TenantId, actor: Employee, draft: FieldReportDraft
    ) -> FieldReportSubmission:
        """Hesabatı yazır, düzəliş tapşırıqlarını yaradır və marşrutlayır.

        HƏR İKİ ŞABLON BU METODDAN KEÇİR (Struktur Qərar A). Ardıcıllıq
        CLAUDE.md §6 naxışıdır: səlahiyyət → domen qaydası (entity-də) →
        yazma → tapşırıq → audit → bildiriş.
        """
        template = self._require_template(tenant_id, draft.report_type)
        category = self._require_category(tenant_id, draft.category, template=template)
        self._require(actor, tenant_id, self._flag_for(template))

        now = self._clock.now()
        report_id = new_field_report_id()
        items = self._build_items(
            tenant_id=tenant_id, report_id=report_id, drafts=draft.checklist, now=now
        )
        # Checklist tələbi KATALOQDAN gəlir — `if type == "STORE_AUDIT"` YOX.
        if template.requires_checklist and not items:
            raise FieldReportError(
                f"«{template.name_az}» şablonu checklist olmadan təqdim edilə bilməz",
                user_message="Bu forma ən azı bir checklist bəndi tələb edir.",
                context={"report_type": template.code},
            )

        report = FieldReport(
            report_id=report_id,
            tenant_id=tenant_id,
            report_type=template.code,
            category=category.code,
            store_id=draft.store_id,
            reported_by=actor.id,
            detail=draft.detail,
            created_at=now,
            updated_at=now,
            photo_refs=draft.photo_refs,
            items=items,
            min_detail_length=self._min_detail_length(tenant_id),
        )
        max_photos = self._max_photos(tenant_id)
        if len(report.photo_refs) > max_photos:
            raise FieldReportError(
                f"Bir hesabata maksimum {max_photos} şəkil əlavə edilə bilər",
                user_message=f"Bir hesabata ən çoxu {max_photos} şəkil əlavə edilə bilər.",
                context={"photo_count": len(report.photo_refs)},
            )
        self._reports.save(report)

        task_ids = self._raise_corrective_tasks(
            tenant_id=tenant_id, actor=actor, report=report, now=now
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FIELD_REPORT_SUBMITTED",
            entity_type="field_reports",
            entity_id=report.id,
            before_state=None,
            after_state=_snapshot(report, corrective_tasks=len(task_ids)),
        )
        recipients = self._route(tenant_id=tenant_id, report=report, category=category)
        return FieldReportSubmission(
            report=report,
            corrective_task_ids=task_ids,
            routed_role=category.route_to_role,
            routed_recipients=recipients,
        )

    def start_progress(
        self, *, tenant_id: TenantId, actor: Employee, report_id: FieldReportId
    ) -> FieldReport:
        """ "[İcraya götür]" — `SUBMITTED` → `IN_PROGRESS`."""
        self._require(actor, tenant_id, CONDUCT_AUDIT_FLAG)
        report = self._require_report(report_id)
        before_state = _snapshot(report)
        report.start_progress(now=self._clock.now())
        self._reports.save(report)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FIELD_REPORT_IN_PROGRESS",
            entity_type="field_reports",
            entity_id=report.id,
            before_state=before_state,
            after_state=_snapshot(report),
        )
        return report

    def close(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        report_id: FieldReportId,
        status: FieldReportStatus,
        note: str,
    ) -> FieldReport:
        """ "[Həll edildi]" / "[Əsassızdır]" — TERMİNAL keçid.

        İKİ METOD ƏVƏZİNƏ status ARQUMENTİ: hər iki qərar eyni üç sütunu eyni
        qaydalarla doldurur (bax `FieldReport.close` başlığı) və ekran onsuz
        da iki düymə göstərir — fərq düymədədir, axında yox.
        """
        self._require(actor, tenant_id, CONDUCT_AUDIT_FLAG)
        report = self._require_report(report_id)
        before_state = _snapshot(report)
        report.close(
            status=status,
            closed_by=actor.id,
            note=note,
            now=self._clock.now(),
            min_note_length=self._min_detail_length(tenant_id),
        )
        self._reports.save(report)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FIELD_REPORT_CLOSED",
            entity_type="field_reports",
            entity_id=report.id,
            before_state=before_state,
            after_state=_snapshot(report),
            reason=report.resolution_note,
        )
        return report

    def attach_uploaded_photo(
        self, *, tenant_id: TenantId, owner_id: FieldReportId | FieldReportItemId, photo_ref: str
    ) -> bool:
        """Sübut yükləmə NÖVBƏSİ (`EvidenceUploadWorker`) bitdikdə çağırılır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `actor` YOXDUR
        ──────────────────────────────────────────────────────────────────────
        Səlahiyyət şəkil SEÇİLƏN anda artıq yoxlanılıb (`submit`); Drive-a
        yükləmə isə arxa planda, dəqiqələr sonra bitir və həmin anda ekran
        qarşısında aktor YOXDUR. Eyni qərar `EmployeeDocumentUseCase.
        attach_uploaded_file`-dadır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ ƏVVƏLCƏ HESABAT, SONRA BƏND
        ──────────────────────────────────────────────────────────────────────
        Növbə yalnız TƏK `owner_id` daşıyır və o, ya hesabatın, ya da checklist
        bəndinin İD-sidir. Hər ikisi `gen_random_uuid()`-dir, yəni QLOBAL
        unikaldır — bir UUID hər iki cədvəldə eyni anda mövcud ola bilməz.
        Ona görə ardıcıl cəhd BİRMƏNALIDIR (ikinci sahib tipi əlavə etmək isə
        `allowed_extensions_for` ağ siyahısını, işçi geri-çağırışını və
        miqrasiya tarixçəsini ikiqat artırardı).

        Returns:
            İstinad yazıldımı. `False` = sahib tapılmadı (hesabat silinmiş
            ola bilməz — `REVOKE DELETE` — lakin köhnə növbə faylı BAŞQA
            kirayəçinin sətrinə işarə edə bilər).
        """
        now = self._clock.now()
        report = self._reports.get(FieldReportId(owner_id))
        if report is not None:
            report.add_photo(photo_ref=photo_ref, now=now, max_photos=self._max_photos(tenant_id))
            self._reports.save(report)
            self._record_photo_audit(tenant_id=tenant_id, report=report, owner_id=owner_id)
            return True

        report = self._reports.find_by_item(tenant_id, owner_id)  # type: ignore[arg-type]
        if report is None:
            _app_log.warning(
                "FIELD_REPORT_PHOTO_OWNER_NOT_FOUND",
                extra={"owner_id": str(owner_id)},
            )
            return False
        for item in report.items:
            if item.id == owner_id:
                item.attach_photo(photo_ref=photo_ref, now=now)
                break
        self._reports.save(report)
        self._record_photo_audit(tenant_id=tenant_id, report=report, owner_id=owner_id)
        return True

    # ------------------------------ planlanmış -------------------------------- #

    def notify_overdue_audits(self, tenant_id: TenantId) -> AuditReminderResult:
        """Audit intervalı keçmiş filiallar üçün xatırlatma göndərir.

        PLANLAŞDIRILMIŞ İŞDİR (`FIELD_REPORT_AUDIT_REMINDER`, gündəlik,
        YÜNGÜL) — `actor` YOXDUR, çünki bunu düymə yox, planlayıcı çağırır
        (`employee_documents.notify_expiring_documents` ilə eyni forma).

        BİR FİLİAL = BİR BİLDİRİŞ: filial başına ayrı sətir yazılır, çünki
        "5 filial gecikib" mətni hansı filialın gecikdiyini demir və menecer
        siyahını yenidən açmalı olardı. Sətir sayı filial sayı ilə
        məhdudlaşır (21) — bildiriş kanalını doldurmur.
        """
        interval_days = self._audit_interval_days(tenant_id)
        gaps = self._reports.stores_missing_audit(
            tenant_id, now=self._clock.now(), interval_days=interval_days
        )
        result = AuditReminderResult(checked=len(gaps))
        for gap in gaps:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category=AUDIT_DUE_NOTIFICATION_CATEGORY,
                title_az="Mağaza auditi gecikib",
                body_az=(
                    f"«{gap.store_name}» filialı sonuncu dəfə "
                    + (
                        f"{gap.days_since} gün əvvəl auditə çəkilib"
                        if gap.days_since is not None
                        else "HEÇ VAXT auditə çəkilməyib"
                    )
                    + f" (interval: {interval_days} gün)."
                ),
                # Gecə işidir, ekran qarşısında gözləyən yoxdur — e-poçt
                # ehtiyat kanalı `is_critical=True` ilə açılır
                # (`employee_documents._send_expiry_warning` ilə eyni qərar).
                is_critical=True,
            )
            result.overdue.append(gap.store_name)
        return result

    # ------------------------------- köməkçi ---------------------------------- #

    def _flag_for(self, template: FieldReportTemplate) -> str:
        """Şablonun tələb etdiyi səlahiyyət — ADINDAN YOX, TƏBİƏTİNDƏN.

        Bax modul başlığı: `requires_checklist` "strukturlaşdırılmış yoxlama"
        ilə "sərbəst müşahidə" arasındakı fərqi onsuz da saxlayır və
        səlahiyyət fərqi məhz həmin fərqdir.
        """
        return CONDUCT_AUDIT_FLAG if template.requires_checklist else REPORT_INCIDENT_FLAG

    def _build_items(
        self,
        *,
        tenant_id: TenantId,
        report_id: FieldReportId,
        drafts: tuple[ChecklistItemDraft, ...],
        now: datetime,
    ) -> tuple[FieldReportChecklistItem, ...]:
        """Draft-ları bəndlərə çevirir — sıra siyahının ÖZ ardıcıllığındandır.

        `enumerate(..., start=1)`: `UNIQUE (report_id, position_no)` və
        `CHECK (position_no >= 1)` güzgüsü. Sıranı forma sahəsi kimi qəbul
        etsəydik, iki bənd eyni nömrə ala bilər və DB çökərdi.
        """
        return tuple(
            FieldReportChecklistItem(
                item_id=new_field_report_item_id(),
                tenant_id=tenant_id,
                report_id=report_id,
                position_no=index,
                item_text=item.item_text,
                created_at=now,
                updated_at=now,
                passed=item.passed,
                is_blocking=item.is_blocking,
                photo_required=item.photo_required,
                photo_ref=item.photo_ref,
                note=item.note,
            )
            for index, item in enumerate(drafts, start=1)
        )

    def _raise_corrective_tasks(
        self, *, tenant_id: TenantId, actor: Employee, report: FieldReport, now: datetime
    ) -> tuple[TaskId, ...]:
        """Uğursuz BLOKLAYICI bənd başına BİR düzəliş tapşırığı (Qərar B).

        BƏND BAŞINA AYRI TAPŞIRIQ, HESABAT BAŞINA TƏK TAPŞIRIQ YOX: hər bənd
        ayrı bir düzəlişdir və ayrıca sübutla bağlanır. Vahid tapşırıq
        "hamısını düzəlt" olardı və qismən icra izlənə bilməzdi.
        """
        failures = report.blocking_failures
        if not failures:
            return ()
        assignee = self._corrective_assignee(tenant_id=tenant_id, actor=actor, report=report)
        deadline = now + timedelta(days=self._task_deadline_days(tenant_id))
        task_ids: list[TaskId] = []
        for item in failures:
            task = self._tasks.assign(
                tenant_id=tenant_id,
                actor=actor,
                task_id=new_task_id(),
                draft=TaskDraft(
                    title=f"Düzəliş: {item.item_text}",
                    assignee_id=assignee,
                    deadline=deadline,
                    description=(
                        f"Sahə hesabatı ({report.report_type} / {report.category}) "
                        f"{item.position_no}-ci bəndi uğursuzdur."
                        + (f" Qeyd: {item.note}" if item.note else "")
                    ),
                    # BLOKLAYICI bəndin tərifi elə "gecikdirilə bilməz"dir —
                    # prioritet `is_blocking` sahəsindən çıxır, ayrıca forma
                    # sahəsindən yox (istifadəçi onu aşağı sala bilməməlidir).
                    priority=TaskPriority.HIGH,
                    store_id=report.store_id,
                    requires_evidence=True,
                ),
            )
            task_ids.append(task.id)
        return tuple(task_ids)

    def _corrective_assignee(
        self, *, tenant_id: TenantId, actor: Employee, report: FieldReport
    ) -> EmployeeId:
        """Düzəlişin sahibi — ROOT parametrindəki rol, HƏMİN filialda.

        Rol boşdursa və ya filialda həmin roldan aktiv işçi yoxdursa,
        tapşırıq hesabatı YAZAN şəxsə qalır. Sahibsiz tapşırıq mümkün deyil
        (`Task.assignee_id` məcburidir) və "heç kimə verilmədi" ən pis
        nəticədir — auditor ən azı eskalasiya edə bilər.
        """
        role_code = self._limits.get_str(
            tenant_id,
            SystemLimitKey.FIELD_REPORT_TASK_ASSIGNEE_ROLE.value,
            _FALLBACK_TASK_ASSIGNEE_ROLE,
        ).strip()
        if role_code:
            candidates = self._reports.list_route_recipients(
                tenant_id, role_code=role_code, store_id=report.store_id
            )
            if candidates:
                return candidates[0]
        _app_log.info(
            "FIELD_REPORT_TASK_ASSIGNEE_FALLBACK",
            extra={"role_code": role_code, "store_id": str(report.store_id)},
        )
        return actor.id

    def _route(
        self, *, tenant_id: TenantId, report: FieldReport, category: FieldReportCategory
    ) -> int:
        """#27 marşrutlaması — kataloqdakı `route_to_role`-a görə.

        `if category == ...` YOXDUR: rol kodu MƏLUMATDIR və burada yalnız
        işçilərə çevrilir. Boş nəticə broadcast ehtiyat yoluna düşür (bax
        modul başlığı).
        """
        title = f"Yeni sahə hesabatı: {category.name_az}"
        body = (
            f"{report.report_type} / {category.name_az} — {report.detail}"
            if len(report.detail) <= _NOTIFICATION_DETAIL_CHARS
            else f"{report.report_type} / {category.name_az} — "
            f"{report.detail[:_NOTIFICATION_DETAIL_CHARS]}…"
        )
        recipients: list[EmployeeId] = []
        if category.route_to_role:
            recipients = self._reports.list_route_recipients(
                tenant_id, role_code=category.route_to_role
            )
        for recipient in recipients:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=recipient,
                category=ROUTED_NOTIFICATION_CATEGORY,
                title_az=title,
                body_az=body,
                is_critical=False,
            )
        if not recipients:
            # Ehtiyat yolu: auditoriya süzgəci `TENANT_NOTIFICATION_AUDIENCE`
            # ilə `can_conduct_store_audit`-a daralır — süzgəcsiz sətir
            # fail-open olardı (bax modul başlığı).
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category=ROUTED_NOTIFICATION_CATEGORY,
                title_az=title,
                body_az=body,
                is_critical=False,
            )
        return len(recipients)

    def _record_photo_audit(
        self,
        *,
        tenant_id: TenantId,
        report: FieldReport,
        owner_id: FieldReportId | FieldReportItemId,
    ) -> None:
        """Foto istinadının yazılması audit izinə düşür.

        `actor_id` hesabatı YAZAN şəxsdir — canlı aktor yoxdur (bax
        `attach_uploaded_photo` başlığı). "Sübut nə vaxt fiziki əlçatan
        oldu?" sualı mübahisədə soruşula bilər, ona görə sükut qəbul edilməzdir.
        """
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=report.reported_by,
            action="FIELD_REPORT_PHOTO_ATTACHED",
            entity_type="field_reports",
            entity_id=report.id,
            after_state={"owner_id": str(owner_id), "photo_count": len(report.photo_refs)},
        )

    def _require(self, actor: Employee, tenant_id: TenantId, flag: str) -> None:
        if actor.tenant_id != tenant_id:
            # Üçüncü izolyasiya qatı (RLS və repo `tenant_id` şərtindən sonra).
            raise AuthorizationError(
                "Aktor bu kirayəçiyə aid deyil",
                context={"actor_id": str(actor.id)},
            )
        if not actor.has_permission(flag, now=self._clock.now()):
            # Sükutla "heç nə etmə" DEYİL (CLAUDE.md §6): istifadəçi düyməni
            # basıb və nəticə gözləyir.
            _security_log.warning(
                "FIELD_REPORT_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": flag},
            )
            raise AuthorizationError(
                f"«{flag}» səlahiyyəti yoxdur",
                context={"flag": flag},
            )

    def _require_report(self, report_id: FieldReportId) -> FieldReport:
        report = self._reports.get(report_id)
        if report is None:
            raise FieldReportNotFoundError(
                "Sahə hesabatı tapılmadı", context={"report_id": str(report_id)}
            )
        return report

    def _require_template(self, tenant_id: TenantId, code: str) -> FieldReportTemplate:
        template = self._catalog.get_template(tenant_id, code)
        if template is None or not template.is_active:
            raise UnknownFieldReportTemplateError(
                "Hesabat şablonu kataloqda yoxdur və ya söndürülüb",
                context={"report_type": code},
            )
        return template

    def _require_category(
        self, tenant_id: TenantId, code: str, *, template: FieldReportTemplate
    ) -> FieldReportCategory:
        """Kateqoriyanı yoxlayır — DB-nin BİRLƏŞMİŞ FK-sının kod tərəfi.

        Şablona aid olmayan kateqoriya DB-də onsuz da bloklanır
        (`FOREIGN KEY (type, category)`), lakin ORADA dayandırmaq ekrana
        anlaşılmaz sürücü xətası verərdi. Bu yoxlama həmin qadağanı ƏVƏZ
        ETMİR — onu istifadəçi dilinə çevirir.
        """
        category = self._catalog.get_category(tenant_id, code)
        if category is None or not category.is_active:
            raise UnknownFieldReportTemplateError(
                "Kateqoriya kataloqda yoxdur və ya söndürülüb",
                context={"category": code},
            )
        if category.report_type != template.code:
            raise UnknownFieldReportTemplateError(
                "Kateqoriya bu şablona aid deyil",
                user_message="Seçilmiş kateqoriya bu hesabat növünə uyğun deyil.",
                context={"category": code, "report_type": template.code},
            )
        return category

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey, fallback: int) -> int:
        return self._limits.get_int(tenant_id, key.value, fallback)

    def _max_photos(self, tenant_id: TenantId) -> int:
        # Sıfır/mənfi dəyər tavanı SÖNDÜRMÜR, fallback-a qaytarır — səhv
        # konfiqurasiya qorumanı sükutla itirməməlidir (`upload_queue`-dakı
        # eyni qərar).
        value = self._limit_int(
            tenant_id, SystemLimitKey.FIELD_REPORT_MAX_PHOTOS, _FALLBACK_MAX_PHOTOS
        )
        return value if value > 0 else _FALLBACK_MAX_PHOTOS

    def _min_detail_length(self, tenant_id: TenantId) -> int:
        return self._limit_int(
            tenant_id, SystemLimitKey.FIELD_REPORT_MIN_DETAIL_LENGTH, _FALLBACK_MIN_DETAIL
        )

    def _task_deadline_days(self, tenant_id: TenantId) -> int:
        value = self._limit_int(
            tenant_id,
            SystemLimitKey.FIELD_REPORT_TASK_DEADLINE_DAYS,
            _FALLBACK_TASK_DEADLINE_DAYS,
        )
        # Sıfır/mənfi möhlət KEÇMİŞ son tarix deməkdir: tapşırıq yaranan
        # anda gecikmiş sayılar və eskalasiya dövrəsi dərhal işə düşərdi.
        return value if value > 0 else _FALLBACK_TASK_DEADLINE_DAYS

    def _audit_interval_days(self, tenant_id: TenantId) -> int:
        value = self._limit_int(
            tenant_id,
            SystemLimitKey.FIELD_REPORT_AUDIT_INTERVAL_DAYS,
            _FALLBACK_AUDIT_INTERVAL_DAYS,
        )
        return value if value > 0 else _FALLBACK_AUDIT_INTERVAL_DAYS

    def _page_size(self, tenant_id: TenantId) -> int:
        """Siyahı tavanı — YENİ açar YARADILMIR.

        `EXCEPTION_PAGE_SIZE` (#9) EYNİ sualın cavabıdır: "bir ekranın
        oxuduğu açıq sətir sayı". İkinci açar Root panelində eyni qərarı iki
        dəfə soruşardı və ikisi sürüşəndə hansının hansı ekrana aid olduğu
        aydın olmazdı.
        """
        value = self._limit_int(
            tenant_id,
            SystemLimitKey.EXCEPTION_PAGE_SIZE,
            int(DEFAULT_LIMITS[SystemLimitKey.EXCEPTION_PAGE_SIZE]),
        )
        return value if value > 0 else int(DEFAULT_LIMITS[SystemLimitKey.EXCEPTION_PAGE_SIZE])


#: Bildiriş mətnindəki təsvirin simvol tavanı. Uzun mətn bildiriş panelini
#: doldurur və ekrandakı digər sətirləri sıxışdırır; tam mətn hesabatın
#: ÖZÜNDƏDİR və bir kliklə açılır.
_NOTIFICATION_DETAIL_CHARS: Final = 160


def _snapshot(report: FieldReport, *, corrective_tasks: int | None = None) -> dict[str, object]:
    """Audit `before_state`/`after_state` görünüşü.

    `detail` TAM yazılır (kəsilmir): audit izinin bütün məqsədi "o anda nə
    yazılmışdı?" sualına cavab verməkdir və kəsilmiş mətn mübahisədə
    yararsızdır (bildiriş mətni ilə QARIŞDIRILMAMALIDIR — o, diqqət çəkmək
    üçündür, sübut üçün yox).
    """
    state: dict[str, object] = {
        "type": report.report_type,
        "category": report.category,
        "store_id": str(report.store_id),
        "status": report.status.value,
        "detail": report.detail,
        "photo_count": len(report.photo_refs),
        "checklist_items": len(report.items),
        "blocking_failures": len(report.blocking_failures),
    }
    if report.audit_score is not None:
        state["audit_score"] = round(report.audit_score, 2)
    if corrective_tasks is not None:
        state["corrective_tasks"] = corrective_tasks
    return state


__all__ = [
    "AUDIT_DUE_NOTIFICATION_CATEGORY",
    "CONDUCT_AUDIT_FLAG",
    "REPORT_INCIDENT_FLAG",
    "ROUTED_NOTIFICATION_CATEGORY",
    "AuditReminderResult",
    "FieldReportDraft",
    "FieldReportError",
    "FieldReportNotFoundError",
    "FieldReportSubmission",
    "FieldReportUseCase",
    "UnknownFieldReportTemplateError",
]
