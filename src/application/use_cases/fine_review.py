"""Aylıq Cərimə İcmalı və kütləvi nəşr — Faza 2.7 (qərar dəyişikliyi).

Axın:

    1. Cərimələr (AUTO_DELAY + MANUAL_CAMERA) `PENDING_REVIEW` doğulur —
       işçi, mağaza meneceri və HR onları GÖRMÜR.
    2. Ayın əvvəlində `can_publish_fines` sahibi 21 filialın həmin ay üçün
       nəşr gözləyən cərimələrini BİR cədvəldə görür.
    3. Hər sətrə "Saxla" (defolt) / "Sil" qərarı verilir.
    4. TƏK "[Bütün Filiallara Göndər]" düyməsi: saxlananlar `PUBLISHED`,
       silinənlər `REVERSED` olur və HƏMİN AN bütün filiallarda görünür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BİR TRANZAKSİYADA
──────────────────────────────────────────────────────────────────────────────
"Bir andan" tələbi texniki tələbdir, təsviri deyil: yarımçıq nəşr bəzi
filialların cəriməni görməsi, bəzilərinin görməməsi demək olardı. Ona görə
bütün qərarlar tək `commit()`-də tətbiq olunur — biri uğursuz olarsa HEÇ
BİRİ tətbiq olunmur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ "SİL" FİZİKİ SİLMƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Bölmə 4: "orijinal qeyd heç vaxt silinmir". Operatorun səhvən yazdığı cərimə
də auditin bir hissəsidir — kimin nə qeyd etdiyi və kimin onu ləğv etdiyi
sonradan sual olunanda cavab verilə bilməlidir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import new_fine_review_batch_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.text import normalise_decision_text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        EmployeeRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeId, FineId, FineReviewBatchId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Cərimələri filiallara açan icazə. Kamera operatoruna, mağaza menecerinə və
#: satıcıya HEÇ VAXT verilə bilməz — DB trigger-i də bunu bloklayır
#: (`is_anti_fraud` + `excludes_camera_role`, migration 003).
PUBLISH_FINES_FLAG = "can_publish_fines"

MIN_DISCARD_REASON_LENGTH = 10


class FineReviewError(KompasOSError):
    """İcmal/nəşr əməliyyatı qadağandır və ya yararsızdır."""

    user_message = "Bu əməliyyat icra edilə bilmədi."


class ReviewDecision(str, Enum):
    KEEP = "KEEP"
    DISCARD = "DISCARD"


@dataclass(frozen=True)
class FineDecision:
    """İcmal cədvəlinin bir sətri üzrə qərar."""

    fine_id: FineId
    decision: ReviewDecision = ReviewDecision.KEEP
    reason: str | None = None


@dataclass
class PublishResult:
    """Kütləvi nəşrin nəticəsi — audit və UI təsdiq mesajı üçün."""

    batch_id: FineReviewBatchId
    review_month: str
    published: list[FineId] = field(default_factory=list)
    discarded: list[FineId] = field(default_factory=list)
    #: DEEP-GAP D2 — "Saxla" qərarı verilib, LAKİN nəşr edilməyib: işçi
    #: `publish_batch` anında deaktivdir. Sətir `PENDING_REVIEW`-də QALIR
    #: (nə `published`-ə, nə `discarded`-ə düşür, `Fine` obyekti heç
    #: mutasiya olunmur) — HR əl ilə qərar verməlidir (bax `publish_batch`
    #: başlığı).
    held_inactive_employee: list[FineId] = field(default_factory=list)
    #: DEEP-GAP T3 — MANUAL_CAMERA cəriməsinin sübut şəkli HƏLƏ Drive-a
    #: yüklənməyib (`evidence_upload_status <> 'SYNCED'`). `held_inactive_
    #: employee` ilə EYNİ semantika: sətir `PENDING_REVIEW`-də QALIR, `Fine`
    #: obyekti mutasiya OLUNMUR, növbəti icmalda YENİDƏN görünür — yəni bu,
    #: rədd deyil, TƏXİRƏ SALMADIR (şəkil yüklənən kimi öz-özünə nəşr olunacaq).
    held_missing_evidence: list[FineId] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.published) + len(self.discarded)


@dataclass(frozen=True)
class FineReviewBatch:
    """`monthly_fine_review_batches` sətrinin güzgüsü (SEC-8 audit tapıntısı).

    Sadə audit sətridir — heç bir keçidi/qaydası yoxdur, `PublishResult` kimi
    BU FAYLDA yaşayır (`ports.py`-DA DEYİL): CLAUDE.md §3-ün `ReportFactProvider`
    əsaslandırması ilə eyni — bu, TƏTBİQ qatının strukturudur, domen tipi deyil.
    """

    id: FineReviewBatchId
    tenant_id: TenantId
    reviewed_by: EmployeeId
    review_month: str
    pushed_at: datetime
    total_kept_count: int
    total_reversed_count: int


@runtime_checkable
class FineReviewBatchRepository(Protocol):
    """`monthly_fine_review_batches`-in yazma portu (SEC-8)."""

    def save(self, batch: FineReviewBatch) -> None: ...


@runtime_checkable
class FineEvidenceSyncReader(Protocol):
    """Sübut şəklinin Drive-a HƏQİQƏTƏN yüklənib-yüklənmədiyini oxuyur (T3).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA PORT — NİYƏ `Fine` ENTITY-SİNƏ SAHƏ ƏLAVƏ EDİLMİR
    ──────────────────────────────────────────────────────────────────────────
    `evidence_drive_*` sütunlarının domendən KƏNARDA saxlanması ŞÜURLU
    qərardır və `repositories.py`-ın "NİYƏ BUNLAR `save()`-dan KEÇMİR"
    bölməsində yazılıb: cərimə yaradılan anda fayl ID-si hələ yoxdur, yəni
    "yüklənmə vəziyyəti" domen anlayışı DEYİL, infrastruktur detalıdır. Həmin
    qərarı pozub entity-yə iki sahə əlavə etsəydik, `Fine`-ın hər bərpası
    (mapper, sahtələr, testlər) Drive vəziyyətini daşımalı olardı.

    Ona görə use case SUALI verir ("bu id-lərdən hansının şəkli hələ
    yüklənməyib?"), CAVABI isə repo-dan alır — domen tipi qaytarılmır, yəni
    port `ports.py`-a DEYİL, use case-in yanına yazılır (CLAUDE.md §3-ün
    `ReportFactProvider` əsaslandırması, `FineReviewBatchRepository` ilə eyni).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ DƏSTLƏ, TƏK-TƏK YOX
    ──────────────────────────────────────────────────────────────────────────
    Aylıq icmalda 21 filialın yüzlərlə sətri olur. Hər sətir üçün ayrıca sorğu
    "[Bütün Filiallara Göndər]" düyməsini N+1 gediş-gəlişə çevirərdi
    (`docs/performance_notes.md` büdcəsi) — bir `id = ANY(...)` sorğusu
    kifayətdir.
    """

    def unsynced_evidence_ids(self, fine_ids: Sequence[FineId]) -> set[FineId]:
        """Verilən id-lərdən şəkli HƏLƏ `SYNCED` OLMAYANLARI qaytarır.

        MƏNBƏ SÜTUNU `evidence_upload_status`-dur (miqrasiya 002), NƏ
        `photo_evidence_url` — sonuncu MANUAL_CAMERA axınında LOKAL növbə
        açarını saxlayır (`fine_entry.py` şəkli əvvəlcə diskə yazır), yəni
        "dolu" olması şəklin Drive-da olduğunu SÜBUT ETMİR. T3 qüsurunun kök
        səbəbi məhz bu iki sahənin qarışdırılması idi.

        SIRA/TAM DƏST ZƏMANƏTİ YOXDUR: tapılmayan id sadəcə nəticəyə düşmür
        (başqa tenant-a aid ola bilər — RLS + açıq `tenant_id` şərti).
        """
        ...


class MonthlyFineReviewUseCase:
    """Aylıq icmal + kütləvi nəşr.

    ──────────────────────────────────────────────────────────────────────────
    `review_batches` MƏCBURİDİR — `fines` REPOSİTORİYASI İSƏ YENƏ DƏ YOXDUR
    ──────────────────────────────────────────────────────────────────────────
    Bu, `publish_batch`-ın "repository almır" qərarını POZMUR — həmin qərar
    YALNIZ `Fine` sətirlərinə aiddir (çağıran onları oxuyub yazır, bax
    `controllers/fine_review.py`). `monthly_fine_review_batches` isə FƏRQLİ
    bir yazıdır: HEÇ bir mövcud `Fine` obyektinin üstündə yaşamır, TƏK
    mənbəyi bu use case-in ÖZÜdür (SEC-8 audit tapıntısı — "bu cərimə hansı
    partiyada nəşr olundu?" sualı əvvəllər cavabsız idi, çünki batch sətri
    HEÇ VAXT yazılmırdı, `batch_id` yalnız yaddaşda yaranırdı).
    `limits` ilə EYNİ səbəbdən `None` fallback-ı YOXDUR: audit sətri
    yazılmayan bir "nəşr" səssizcə iz itirmiş olardı.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditTrail,
        notifier: Notifier,
        limits: SystemLimits,
        review_batches: FineReviewBatchRepository,
        employees: EmployeeRepository | None = None,
        evidence_sync: FineEvidenceSyncReader | None = None,
    ) -> None:
        self._clock = clock
        self._audit = audit
        self._notifier = notifier
        # `limits` MƏCBURİDİR (`None` fallback-ı YOXDUR): etiraz pəncərəsi
        # nəşr anında DONDURULUR və sonradan düzəldilə bilmir. Limit mənbəyi
        # olmayan bir nəşr işçinin etiraz hüququnu səssizcə 72 saata
        # sabitləyərdi — ona görə asılılıq açıq tələb olunur.
        self._limits = limits
        self._review_batches = review_batches
        # DEEP-GAP D2 — `None` = kompozisiya kökü hələ ötürməyib. Bu halda
        # köhnə davranış (deaktiv işçinin cəriməsi də nəşr olunur) DƏYİŞMİR:
        # yoxlama YALNIZ port varsa aparılır, sükutla YENİ bloklama YARANMIR.
        self._employees = employees
        # DEEP-GAP T3 — `employees` ilə EYNİ naxış və EYNİ səbəb: port hələ
        # bağlanmayıbsa köhnə davranış DƏYİŞMİR. Bu, "sükutla söndürülmüş
        # qoruma" DEYİL, çünki qapının İKİNCİ (və struktur) nüsxəsi DB-dədir:
        # `chk_fine_published` məhdudiyyəti `infra`-nın tapşırığındadır və
        # ekranı yan keçən skript də ona tabedir (CLAUDE.md §5: hər qayda İKİ
        # yerdə). Buradakı qat isə İSTİFADƏÇİYƏ İZAH verən qatdır — DB rəddi
        # "əməliyyat alınmadı" deyərdi, bu isə hansı cərimənin niyə
        # gözlədiyini adbaad sadalayır.
        self._evidence_sync = evidence_sync

    # ------------------------------ görünmə ---------------------------------- #

    @staticmethod
    def visible_to_employee(fines: list[Fine]) -> list[Fine]:
        """İşçinin "Cərimələrim" görünüşü — nəşr olunmayanlar süzülür."""
        return [fine for fine in fines if fine.is_visible_to_employee]

    @staticmethod
    def recorded_by_operator(fines: list[Fine], operator_id: object) -> list[Fine]:
        """Kamera operatorunun ÖZ fəaliyyət siyahısı.

        İSTİSNA: burada status süzgəci YOXDUR — operator öz qeyd etdiyi
        cəriməni nəşrdən əvvəl də görür. Bu, işçi-görünüşü deyil, öz iş
        jurnalıdır.
        """
        return [fine for fine in fines if fine.issued_by == operator_id]

    # ------------------------------- nəşr ------------------------------------ #

    def publish_batch(
        self,
        *,
        actor: Employee,
        tenant_id: TenantId,
        review_month: str,
        fines: dict[FineId, Fine],
        decisions: list[FineDecision],
    ) -> PublishResult:
        """Bütün qərarları tətbiq edir.

        Args:
            fines: İcmalda göstərilən cərimələr (`id → Fine`).
            decisions: Sətir qərarları. Siyahıda OLMAYAN cərimə "Saxla"
                sayılır — UI-dakı defolt ilə eynidir.
        """
        now = self._clock.now()
        self._assert_may_publish(actor, now=now)
        _require_month(review_month)

        by_id = {decision.fine_id: decision for decision in decisions}
        unknown = set(by_id) - set(fines)
        if unknown:
            raise FineReviewError(
                f"İcmalda olmayan cərimə üçün qərar verildi: {sorted(map(str, unknown))}",
                context={"unknown_count": len(unknown)},
            )

        pending = {
            fine_id: fine
            for fine_id, fine in fines.items()
            if fine.status is FineStatus.PENDING_REVIEW
        }
        if not pending:
            raise FineReviewError(
                "Nəşr gözləyən cərimə yoxdur",
                user_message="Bu ay üçün göndəriləcək cərimə yoxdur.",
            )

        batch_id = new_fine_review_batch_id()
        result = PublishResult(batch_id=batch_id, review_month=review_month)
        # Limit BİR DƏFƏ oxunur: eyni "[Bütün Filiallara Göndər]" basışında
        # nəşr olunan cərimələrin pəncərəsi eyni uzunluqda olmalıdır. Hər
        # sətir üçün ayrıca oxusaydıq, dəst ortasında Root limiti dəyişdikdə
        # eyni partiyadakı iki cərimə fərqli müddət alardı.
        window_hours = self._appeal_window_hours(tenant_id)
        # T3 — BİR sorğu, dövrədən ƏVVƏL (bax `FineEvidenceSyncReader`).
        unsynced_evidence = self._unsynced_evidence(pending)

        for fine_id, fine in pending.items():
            decision = by_id.get(fine_id, FineDecision(fine_id=fine_id))
            if decision.decision is ReviewDecision.DISCARD:
                reason = normalise_decision_text(decision.reason or "")
                if len(reason) < MIN_DISCARD_REASON_LENGTH:
                    raise FineReviewError(
                        f"'Sil' qərarı üçün səbəb məcburidir "
                        f"(minimum {MIN_DISCARD_REASON_LENGTH} simvol)",
                        user_message="Silinən cərimə üçün səbəb yazılmalıdır.",
                        context={"fine_id": str(fine_id)},
                    )
                fine.discard_in_review(
                    reviewed_by=actor.id,
                    reviewed_at=now,
                    reason=reason,
                    review_batch_id=batch_id,
                )
                result.discarded.append(fine_id)
            elif self._is_employee_inactive(fine.employee_id):
                # DEEP-GAP D2 — ƏSAS HƏLL: işçi nəşr ANINDA deaktivdirsə cərimə
                # nəşr EDİLMİR. Səbəb: etiraz pəncərəsi `published_at`-dan
                # başlayır (bax `Fine.is_appeal_window_open`), deaktiv hesab
                # isə giriş edə bilmir (`assert_admin_login_allowed`/PIN
                # namizədləri `is_active` süzgəcindən keçir) — yəni pəncərə
                # AÇILA BİLMƏYƏN bir cərimə struktur olaraq NATAMAMDIR. Sətir
                # `PENDING_REVIEW`-də qalır (mutasiya YOXDUR, `save()` bu
                # sətri YENİDƏN yazmayacaq), HR əl ilə qərar verir.
                result.held_inactive_employee.append(fine_id)
            elif fine_id in unsynced_evidence:
                # DEEP-GAP T3 — sübut şəkli HƏLƏ Drive-da deyil. Nəşr işçiyə
                # 72 saatlıq etiraz pəncərəsi açır (`Fine.publish`), etiraza
                # baxan şəxs isə şəkli HEÇ YERDƏN tapa bilməzdi: `photo_
                # evidence_url` MANUAL_CAMERA axınında LOKAL növbə açarıdır və
                # o növbə faylı (`%PROGRAMDATA%\KompasOS\data`) admin hüququ
                # OLMADAN silinə bilər. Yəni "sübutu olmayan cərimə" nəşr
                # oluna bilirdi — bu qol onu bloklamır, TƏXİRƏ SALIR.
                #
                # `held_inactive_employee` ilə EYNİ ZƏNCİRDƏ və EYNİ formada:
                # sətir `PENDING_REVIEW`-də qalır, `Fine` mutasiya olunmur,
                # növbəti icmalda yenidən görünür. Sıra ƏHƏMİYYƏTLİDİR —
                # deaktiv işçi yoxlaması ÖNCƏ gəlir, çünki o, ŞƏXSİN
                # vəziyyətidir və şəkil yüklənsə belə həll olunmur.
                result.held_missing_evidence.append(fine_id)
            else:
                # Pəncərə uzunluğu TENANT-dan gəlir, `Fine` sinfinin
                # defoltundan yox: icmaldan gələn obyekt repository-dən bərpa
                # olunub və bərpa yolunda bu sahə HƏMİŞƏ 72 qalır (bax
                # `Fine.publish` və `mappers.fine_from_row` şərhləri).
                fine.publish(
                    reviewed_by=actor.id,
                    published_at=now,
                    appeal_window_hours=window_hours,
                    review_batch_id=batch_id,
                )
                result.published.append(fine_id)

        self._record(actor, tenant_id, result, now=now)
        return result

    # ------------------------------ köməkçi ---------------------------------- #

    def _is_employee_inactive(self, employee_id: EmployeeId) -> bool:
        """DEEP-GAP D2: `employees` portu yoxdursa (kompozisiya köhnədir) YOXLAMA APARILMIR.

        Tapılmayan işçi də "deaktiv" sayılır — silinmiş/köçürülmüş sətir üçün
        eyni əsaslandırma tətbiq olunur: pəncərə açıla bilməyəcək bir cəriməni
        NƏŞR ETMƏMƏK həmişə TƏHLÜKƏSİZ tərəfdir (HR sonra əl ilə qərar verir).
        """
        if self._employees is None:
            return False
        employee = self._employees.get(employee_id)
        return employee is None or not employee.is_active

    def _unsynced_evidence(self, pending: dict[FineId, Fine]) -> set[FineId]:
        """Şəkli hələ yüklənməmiş MANUAL_CAMERA cərimələri (T3).

        SÜZGƏC BURADADIR, REPO-DA YOX: "hansı mənbənin sübutu MƏCBURİDİR"
        biznes qaydasıdır (`Fine.__init__`-dəki `chk_fine_manual_requires_
        evidence` güzgüsü) — onu SQL-ə köçürsəydik qayda İKİ yerdə YAŞAYARDI
        və mənbə növü artanda (məs. gələcək "MANUAL_MANAGER") sükutla
        ayrılardı. Repo yalnız sütunu oxuyur.

        AUTO_DELAY cəriməsinin şəkli YOXDUR və olmamalıdır — onu bu dəstə
        salsaydıq, gecikmə cərimələrinin HAMISI əbədi gözləyən qalardı.
        """
        if self._evidence_sync is None:
            return set()
        camera_ids = [
            fine_id for fine_id, fine in pending.items() if fine.source is FineSource.MANUAL_CAMERA
        ]
        if not camera_ids:
            return set()
        return self._evidence_sync.unsynced_evidence_ids(camera_ids)

    def _assert_may_publish(self, actor: Employee, *, now: datetime) -> None:
        if not actor.has_permission(PUBLISH_FINES_FLAG, now=now):
            _security_log.warning(
                "FINE_PUBLISH_DENIED",
                extra={
                    "actor_id": str(actor.id),
                    "role": actor.position.code,
                    "reason": "MISSING_FLAG",
                },
            )
            raise FineReviewError(
                f"'{PUBLISH_FINES_FLAG}' səlahiyyəti yoxdur",
                user_message="Cərimələri göndərmək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )

    def _appeal_window_hours(self, tenant_id: TenantId) -> int:
        """Tenant-ın etiraz pəncərəsi (saat) — `ManualFineUseCase` ilə eyni naxış.

        Defolt sinifdə DEYİL, `DEFAULT_LIMITS`-dədir: həqiqi mənbə
        `system_limits` cədvəlidir (ROOT İdarə Mərkəzi), buradakı dəyər yalnız
        cədvəl sətri olmadıqda işə düşən fallback-dır.
        """
        key = SystemLimitKey.FINE_APPEAL_WINDOW_HOURS
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))

    def _record(
        self,
        actor: Employee,
        tenant_id: TenantId,
        result: PublishResult,
        *,
        now: datetime,
    ) -> None:
        # SEC-8: batch sətri BURADA davamlı yazılır — əvvəllər `batch_id`
        # yalnız yaddaşda yaranıb istinadsız qalırdı (`entity_id=None` bunun
        # izi idi, indi HƏQİQİ sətrə işarə edir). Audit sətrindən ƏVVƏL
        # yazılır: batch əlçatmaz olsa (DB nasazlığı) `self._audit.record()`
        # də uğursuz olacaq (eyni tranzaksiya, eyni bağlantı) — bu, İKİSİNİN
        # DƏ rollback edilməsini TƏMİN edir, yarımçıq iz qalmır.
        self._review_batches.save(
            FineReviewBatch(
                id=result.batch_id,
                tenant_id=tenant_id,
                reviewed_by=actor.id,
                review_month=result.review_month,
                pushed_at=now,
                total_kept_count=len(result.published),
                total_reversed_count=len(result.discarded),
            )
        )
        _audit_log.warning(
            "MONTHLY_FINES_PUBLISHED",
            extra={
                "batch_id": str(result.batch_id),
                "review_month": result.review_month,
                "actor_id": str(actor.id),
                "published_count": len(result.published),
                "discarded_count": len(result.discarded),
                "held_inactive_employee_count": len(result.held_inactive_employee),
                "held_missing_evidence_count": len(result.held_missing_evidence),
            },
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="MONTHLY_FINES_PUBLISHED",
            entity_type="monthly_fine_review_batches",
            entity_id=result.batch_id,
            after_state={
                "batch_id": str(result.batch_id),
                "review_month": result.review_month,
                "kept": len(result.published),
                "reversed": len(result.discarded),
                # DEEP-GAP D2 — bu ay saxlanan (nə nəşr, nə ləğv olunmuş)
                # sətirlərin sayı. Sıfırdan böyükdürsə HR əl ilə baxmalıdır.
                "held_inactive_employee": len(result.held_inactive_employee),
                # T3 — sıfırdan böyükdürsə şəkil növbəsi geri qalıb və ya
                # spool faylı itib; nəşr edən şəxs SƏBƏBİ auditdən görməlidir.
                "held_missing_evidence": len(result.held_missing_evidence),
                "published_at": now.isoformat(),
            },
        )
        if result.held_inactive_employee:
            # BLOKLAMIR, YALNIZ XƏBƏRDARLIQ: bu sətirlər `PENDING_REVIEW`-də
            # qalıb və növbəti aylıq icmalda YENƏ görünəcək — susdurulan bir
            # xəbərdarlıq onları əbədi "gözləyən" saxlaya bilərdi.
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="MONTHLY_FINES_HELD_INACTIVE_EMPLOYEE",
                title_az="Deaktiv işçinin cəriməsi nəşr edilmədi",
                body_az=(
                    f"{result.review_month} ayı üzrə {len(result.held_inactive_employee)} "
                    f"cərimə nəşr edilmədi, çünki işçi artıq deaktivdir (etiraz "
                    f"pəncərəsi açıla bilməz). Bu cərimələr 'Gözləyən' siyahısında "
                    f"qalır — əl ilə qərar tələb olunur."
                ),
                is_critical=True,
            )
        if result.held_missing_evidence:
            # T3 — `held_inactive_employee` ilə EYNİ ton: bloklama deyil,
            # XƏBƏRDARLIQ. AYRI kateqoriya QƏSDƏNDİR: iki saxlamanın HƏLLİ
            # tamam fərqlidir — deaktiv işçi HR qərarı tələb edir, itmiş şəkil
            # isə TEXNİKİ araşdırma (Drive bağlantısı, növbə faylı). Eyni
            # kateqoriyaya yığsaydıq, bildirişi alan adam hansı işi görəcəyini
            # bilməzdi.
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="MONTHLY_FINES_HELD_MISSING_EVIDENCE",
                title_az="Sübut şəkli olmayan cərimə nəşr edilmədi",
                body_az=(
                    f"{result.review_month} ayı üzrə {len(result.held_missing_evidence)} "
                    f"cərimə nəşr edilmədi, çünki sübut şəkli hələ Google Drive-a "
                    f"yüklənməyib. Şəkil yüklənən kimi cərimə növbəti icmalda "
                    f"normal nəşr olunacaq — yüklənmə dayanıbsa Drive bağlantısını "
                    f"yoxlayın."
                ),
                is_critical=True,
            )
        if result.published:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="MONTHLY_FINES_PUBLISHED",
                title_az="Aylıq cərimələr göndərildi",
                body_az=(
                    f"{result.review_month} ayı üzrə {len(result.published)} cərimə "
                    f"bütün filiallara göndərildi və işçilərin 'Cərimələrim' "
                    f"bölməsində göründü."
                ),
                is_critical=False,
            )


def _require_month(value: str) -> None:
    """`YYYY-MM` — DB-dəki `chk_batch_month` ilə eyni qayda."""
    parts = value.split("-")
    valid = (
        len(parts) == 2  # noqa: PLR2004 - il və ay
        and len(parts[0]) == 4  # noqa: PLR2004 - dörd rəqəmli il
        and parts[0].isdigit()
        and len(parts[1]) == 2  # noqa: PLR2004 - iki rəqəmli ay
        and parts[1].isdigit()
        and 1 <= int(parts[1]) <= 12  # noqa: PLR2004 - ay aralığı
    )
    if not valid:
        raise FineReviewError(f"Ay formatı 'YYYY-MM' olmalıdır: {value!r}")


__all__ = [
    "PUBLISH_FINES_FLAG",
    "FineDecision",
    "FineReviewBatch",
    "FineReviewBatchRepository",
    "FineReviewError",
    "MonthlyFineReviewUseCase",
    "PublishResult",
    "ReviewDecision",
]
