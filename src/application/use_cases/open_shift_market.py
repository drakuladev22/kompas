"""Açıq Növbə Bazarı (#16, kompasos11.md Faza 6) — "ilk basan qazanır".

──────────────────────────────────────────────────────────────────────────────
BU AXIN SHIFT SWAP-DAN FƏRQLİDİR — ONU GENİŞLƏNDİRMİR, ƏVƏZ ETMİR
──────────────────────────────────────────────────────────────────────────────
    Shift Swap  : KONKRET işçi ÖZ gününü dəyişmək İSTƏYİR → təsdiq gözləyir
                  → `can_approve_shift_swap` sahibi qərar verir.
    Açıq Növbə  : admin SAHİBSİZ slotu elan edir → təsdiq MƏRHƏLƏSİ YOXDUR
                  → uyğun işçilərdən İLK BASAN onu götürür.

`ShiftSwapUseCase` bu fayldan çağırılmır və dəyişdirilmir. Ortaq olan yeganə
şey Shift Matrix-in YEGANƏ yazma nöqtəsidir: elan tutulanda təyinat
`ShiftPlanningUseCase.apply_assignment()` ilə yazılır (bölmə 3 "məntiq
təkrarlanmır" tələbi) — beləliklə mövcud konflikt yoxlaması, audit yazısı və
açıq icazə sorğusunun yenidən qiymətləndirilməsi AVTOMATİK işləyir.

──────────────────────────────────────────────────────────────────────────────
YARIŞ VƏZİYYƏTİ — BU MODULUN ƏSAS RİSKİ
──────────────────────────────────────────────────────────────────────────────
İki işçi eyni anda `[Bu Növbəni Götür]` basanda YALNIZ BİRİ qazanmalıdır.
Tətbiq qatındakı "əvvəlcə oxu, sonra yaz" yoxlaması BU İŞİ GÖRMÜR: hər iki
tranzaksiya oxu anında statusu `OPEN` görür (məhz `migrations/015`-in
bağladığı qüsur növü). Ona görə burada ÜÇ qat işləyir:

  1. `get_for_update()` — `SELECT ... FOR UPDATE`, sətri kilidləyir; ikinci
     tranzaksiya birincinin commit-ini GÖZLƏYİR.
  2. `claim()` — ŞƏRTLİ `UPDATE ... WHERE status = 'OPEN'` və TƏSİR OLUNMUŞ
     SƏTİR SAYININ yoxlanması. Kilid olmasa belə (məs. gələcək oxu-replikası
     ssenarisi) uduzan tranzaksiya 0 sətir yeniləyir və `False` alır.
  3. DB trigger-i (`enforce_open_shift_claim_transition`, migrations/019) —
     `CLAIMED` sətrin sahibi ÜSTÜNDƏN yazıla bilmir.

Uduzan işçi SÜKUTLA uğursuz olmur: `OpenShiftAlreadyClaimedError` atılır və
onun `user_message`-i açıq Azərbaycan dilindədir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA YOXDUR
──────────────────────────────────────────────────────────────────────────────
`morning_check_in.py` başlığındakı meyar: Saga YALNIZ bir neçə aqreqata
toxunan və ARALIQDA uğursuz ola bilən əməliyyat üçündür. Burada elan
tutulması və təyinatın yazılması EYNİ tranzaksiyadadır (hər ikisi eyni
`UnitOfWork` bağlantısındadır) — `apply_assignment()` çökərsə tranzaksiya
bütövlükdə geri qaytarılır və elan yenidən `OPEN` qalır. Kompensasiya
yazmaq DB-nin onsuz da verdiyi zəmanəti təkrarlamaq olardı.

──────────────────────────────────────────────────────────────────────────────
FEATURE TOGGLE — `SHIFT_SWAP` NİYƏ TƏKRAR İSTİFADƏ OLUNUR
──────────────────────────────────────────────────────────────────────────────
`FeatureModule.SHIFT_SWAP` layihədə artıq "işçi-tərəfi növbə self-service"
açarı kimi işlədilir — `screen_data.HELP_TOPIC_MODULES` onunla "Növbə
planlaması və dəyişmə" mövzusunun HAMISINI bağlayır. Açıq bazar da məhz
işçinin öz təşəbbüsü ilə növbəsini dəyişdiyi ikinci kanaldır: modul sui-
istifadəyə görə söndürülübsə, paralel kanalın açıq qalması həmin açarı
mənasız edərdi.

Yeni `OPEN_SHIFT_MARKET` açarı yaratmaq alternativi RƏDD EDİLDİ: `feature_
toggles` sətri seed edilməmiş açar ROOT panelində GÖRÜNMÜR (`describe()`
yalnız mövcud sətirləri qaytarır), yəni "konfiqurasiya edilə bilən" olmaqdan
çıxıb sükutla sabitə çevrilərdi — migrations/022–024-ün bağladığı boşluğun
eynisi.

RETROAKTİVLİK QAYDASI (CLAUDE.md §5): yoxlama YALNIZ `post_open_shift()`-dədir.
Modul söndürüləndə MÖVCUD açıq elanlar öz axınını tamamlayır — işçi artıq
gördüyü elanı götürə bilir, çünki əks halda ekranda görünən düymə sükutla
işləməz olardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Final

from src.application.use_cases.shift_scheduling import (
    MANAGE_SHIFTS_FLAG,
    ShiftPermissionError,
)
from src.domain.entities.open_shift import (
    OpenShiftPosting,
    OpenShiftSlot,
    OpenShiftStatus,
)
from src.domain.entities.shift import ShiftSource
from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.identifiers import new_open_shift_posting_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.application.use_cases.shift_scheduling import (
        ShiftChangeResult,
        ShiftPlanningUseCase,
    )
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        FeatureToggles,
        Notifier,
        OpenShiftPostingRepository,
        ShiftRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        OpenShiftPostingId,
        StoreId,
        TenantId,
        WorkModeId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: FALLBACK — həqiqi mənbə `system_limits.OPEN_SHIFT_MAX_LEAD_DAYS`-dir
#: (`policies.SystemLimitKey`, seed: migrations/027). Sinifdəki bu sabit
#: yalnız DB sətri hələ yaradılmamış quraşdırmada işə düşür.
FALLBACK_MAX_LEAD_DAYS: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS])

#: FALLBACK — həqiqi mənbə `system_limits.OPEN_SHIFT_MAX_CLAIMS_PER_MONTH`.
FALLBACK_MAX_CLAIMS_PER_MONTH: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.OPEN_SHIFT_MAX_CLAIMS_PER_MONTH]
)


class OpenShiftError(KompasOSError):
    """Açıq növbə əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Açıq növbə əməliyyatı icra edilə bilmədi."


class OpenShiftNotFoundError(OpenShiftError):
    user_message = "Bu elan tapılmadı."


class OpenShiftAlreadyClaimedError(OpenShiftError):
    """YARIŞIN UDUZAN TƏRƏFİ — texniki nasazlıq DEYİL, normal nəticə.

    Mesaj qəsdən konkretdir: "əməliyyat alınmadı" işçini düyməni təkrar-
    təkrar basmağa sövq edərdi, halbuki nəticə dəyişməyəcək.
    """

    user_message = "Bu növbəni artıq başqası götürüb."


class OpenShiftNotEligibleError(OpenShiftError):
    user_message = "Bu növbəni götürə bilməzsiniz."


@dataclass(frozen=True)
class OpenShiftView:
    """Ekranların oxuduğu düz görünüş (işçi siyahısı və admin paneli).

    Entity BİRBAŞA ekrana verilmir: `OpenShiftPosting` aqreqatdır və onun
    metodları (`claim`, `cancel`) təsadüfən GUI kodundan çağırıla bilərdi.
    Görünüş obyekti yalnız oxunur.
    """

    posting_id: OpenShiftPostingId
    store_id: StoreId
    shift_date: date
    work_mode_id: WorkModeId
    status: str
    #: Elanı açan silinibsə `None` (DB: `ON DELETE SET NULL`) — ekran bu halda
    #: adı "—" göstərir, sətri GİZLƏTMİR.
    posted_by: EmployeeId | None
    claimed_by: EmployeeId | None
    created_at: datetime


class OpenShiftMarketUseCase:
    """Admin elan edir, işçi tutur — təsdiq mərhələsi YOXDUR."""

    def __init__(
        self,
        *,
        postings: OpenShiftPostingRepository,
        planning: ShiftPlanningUseCase,
        shifts: ShiftRepository,
        limits: SystemLimits,
        toggles: FeatureToggles,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._postings = postings
        self._planning = planning
        self._shifts = shifts
        self._limits = limits
        self._toggles = toggles
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------- admin ----------------------------------- #

    def post_open_shift(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_id: StoreId,
        shift_date: date,
        work_mode_id: WorkModeId,
    ) -> OpenShiftPosting:
        """`[Açıq Növbə Elan Et]` — slot bazara çıxır (status `OPEN`).

        Səlahiyyət `can_manage_shifts`-dir: açıq növbə elan etmək təqvimə
        boşluq açmaq deməkdir və eyni qərar hüququnu tələb edir. YENİ flag
        yaradılmır — kompasos11.md Faza 2 flag siyahısında açıq növbə üçün
        ayrıca flag YOXDUR və hər yeni flag icazə matrisini bir az daha
        oxunmaz edir.
        """
        self._require_manage(actor)
        self._require_module(tenant_id)

        now = self._clock.now()
        today = now.date()
        if shift_date < today:
            raise OpenShiftError(
                "Keçmiş tarix üçün açıq növbə elan edilə bilməz",
                user_message="Keçmiş tarixə növbə elan etmək olmaz.",
                context={"shift_date": shift_date.isoformat()},
            )
        max_lead = self._limit_int(
            tenant_id, SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS, FALLBACK_MAX_LEAD_DAYS
        )
        if (shift_date - today).days > max_lead:
            raise OpenShiftError(
                f"Elan ən çox {max_lead} gün irəli üçün verilə bilər",
                user_message=f"Ən çox {max_lead} gün irəli üçün elan verin.",
                context={"shift_date": shift_date.isoformat(), "max_lead_days": max_lead},
            )

        slot = OpenShiftSlot(store_id=store_id, shift_date=shift_date, work_mode_id=work_mode_id)
        if self._postings.find_open_for_slot(tenant_id, slot) is not None:
            # DB-də bunun ƏKİZİ var (`uq_open_shift_one_open_per_slot`). Burada
            # yoxlanılmasının səbəbi mesajdır: unikal indeks pozuntusu
            # istifadəçiyə "texniki xəta" kimi görünərdi, halbuki bu, sadə və
            # izah edilə bilən vəziyyətdir.
            raise OpenShiftError(
                "Bu slot üçün artıq açıq elan var",
                user_message="Bu tarix və iş rejimi üçün artıq açıq elan var.",
                context={"shift_date": shift_date.isoformat()},
            )

        posting = OpenShiftPosting(
            posting_id=new_open_shift_posting_id(),
            tenant_id=tenant_id,
            slot=slot,
            posted_by=actor.id,
            created_at=now,
        )
        self._postings.post(posting)
        self._drain(posting)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="OPEN_SHIFT_POSTED",
            entity_type="open_shift_postings",
            entity_id=posting.id,
            after_state=posting.to_audit_state(),
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            # Ünvan `None` = mağazadakı uyğun işçilər. Konkret alıcı seçmirik:
            # elanın MƏNASI məhz "kim istəyirsə" olmasıdır.
            recipient_id=None,
            category="OPEN_SHIFT_POSTED",
            title_az="Yeni açıq növbə elan olundu",
            body_az=(
                f"{shift_date.isoformat()} tarixi üçün açıq növbə elan olundu. "
                "İşçi Ana Ekranınızdan «Bu Növbəni Götür» ilə götürə bilərsiniz."
            ),
            is_critical=False,
        )
        return posting

    def cancel_posting(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        posting_id: OpenShiftPostingId,
        reason: str,
    ) -> OpenShiftPosting:
        """`[Elanı Ləğv Et]` — YALNIZ hələ tutulmamış elan geri çəkilə bilər."""
        self._require_manage(actor)
        now = self._clock.now()

        # Kilidli oxu burada da lazımdır: ləğv və tutma bir-biri ilə yarışır.
        posting = self._require_posting(posting_id, locked=True)
        self._require_same_tenant(posting, tenant_id)
        before_state = posting.to_audit_state()

        # Domen qaydası ƏVVƏLCƏ yoxlanılır (səbəbin uzunluğu, status) — DB-yə
        # yararsız sorğu göndərməmək üçün.
        posting.cancel(cancelled_by=actor.id, cancelled_at=now, reason=reason)
        cancelled = self._postings.cancel(
            posting_id=posting_id,
            cancelled_by=actor.id,
            cancelled_at=now,
            reason=posting.cancel_reason or reason,
        )
        if not cancelled:
            # Kilid alınana qədər başqa tranzaksiya elanı tutubsa buraya
            # düşürük. Admin AÇIQ cavab almalıdır: elan yoxa çıxmayıb, sahibi
            # var və növbə artıq təqvimə yazılıb.
            raise OpenShiftAlreadyClaimedError(
                "Elan ləğv edilməzdən əvvəl tutulub",
                user_message="Bu elan artıq götürülüb — ləğv edilə bilmir.",
                context={"posting_id": str(posting_id)},
            )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="OPEN_SHIFT_CANCELLED",
            entity_type="open_shift_postings",
            entity_id=posting.id,
            before_state=before_state,
            after_state=posting.to_audit_state(),
            reason=posting.cancel_reason,
        )
        return posting

    def list_active(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_id: StoreId | None = None,
    ) -> list[OpenShiftView]:
        """Admin panelinin siyahısı — bütün açıq elanlar (bugündən etibarən)."""
        self._require_manage(actor)
        postings = self._postings.list_open(
            tenant_id, store_id=store_id, from_date=self._clock.now().date()
        )
        return [_to_view(item) for item in postings]

    # ------------------------------- işçi ------------------------------------ #

    def list_for_employee(self, *, tenant_id: TenantId, employee: Employee) -> list[OpenShiftView]:
        """İşçi Ana Ekranındakı "Açıq Növbələr" siyahısı.

        SÜZGƏC (uyğunluq): yalnız İŞÇİNİN ÖZ MAĞAZASI, yalnız bugündən
        sonrakı tarixlər və yalnız işçinin həmin gün BOŞ olduğu slotlar.
        Səlahiyyət flag-i tələb OLUNMUR — bu, işçinin öz ekranıdır və
        `can_manage_shifts` tələb etmək bazarı yalnız adminlərə açardı.

        Aylıq tavan burada SÜZGƏC KİMİ İŞLƏDİLMİR: tavanı doldurmuş işçi
        siyahını görməli, lakin düyməni basdıqda aydın izah almalıdır.
        Elanı gizlətsəydik, o, "növbə yoxa çıxdı" nəticəsinə gələrdi.
        """
        if employee.store_id is None:
            # FAIL-CLOSED: mağazası təyin edilməmiş işçi (məs. mərkəzi ofis
            # rolu) HEÇ NƏ görmür. `store_id=None` ötürsəydik, repo süzgəci
            # söndürər və işçi BÜTÜN filialların elanlarını görərdi —
            # sonra hər tutma cəhdi `_require_eligible`-də rədd edilərdi,
            # yəni siyahı yalnız yalan ümid verərdi.
            return []

        postings = self._postings.list_open(
            tenant_id, store_id=employee.store_id, from_date=self._clock.now().date()
        )
        return [
            _to_view(item)
            for item in postings
            if not self._has_working_assignment(employee.id, item.shift_date)
        ]

    def claim(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        posting_id: OpenShiftPostingId,
    ) -> ShiftChangeResult:
        """`[Bu Növbəni Götür]` — İLK BASAN QAZANIR.

        Feature Toggle yoxlaması BURADA YOXDUR: toggle retroaktiv təsir
        etmir (modul başlığı). Səlahiyyət flag-i də yoxdur — elanı görmək
        onu götürmək hüququ deməkdir; ekranın süzgəci uyğunluğu artıq
        təmin edib və bütün SƏRT qaydalar aşağıda təkrar yoxlanılır (ekranı
        yan keçən çağırış da onlara tabedir).
        """
        now = self._clock.now()

        # 1. SƏTİR KİLİDİ — paralel ikinci `claim` burada gözləyir.
        posting = self._require_posting(posting_id, locked=True)
        self._require_same_tenant(posting, tenant_id)
        self._require_eligible(employee, posting, now=now)

        # 2. ŞƏRTLİ UPDATE — yarışın həqiqi həlli (modul başlığı, qat 2).
        won = self._postings.claim(posting_id=posting_id, employee_id=employee.id, claimed_at=now)
        if not won:
            _audit_log.info(
                "OPEN_SHIFT_CLAIM_LOST",
                extra={"posting_id": str(posting_id), "employee_id": str(employee.id)},
            )
            raise OpenShiftAlreadyClaimedError(
                "Elan başqa işçi tərəfindən tutulub",
                context={"posting_id": str(posting_id), "employee_id": str(employee.id)},
            )

        # 3. Aqreqatın vəziyyəti yazıdan SONRA yenilənir — hadisə yalnız
        #    həqiqətən qazanılmış tutma üçün toplanır.
        posting.claim(employee_id=employee.id, claimed_at=now)
        self._drain(posting)

        # 4. Təqvim MÖVCUD yeganə yazma funksiyası ilə yenilənir (bölmə 3).
        #    `source=SHIFT_SWAP` seçilib, `ADMIN_MATRIX` yox: `shift_assignments.
        #    source` DB `CHECK`-i yalnız bu iki dəyəri qəbul edir və üçüncüsünü
        #    əlavə etmək mövcud Shift Matrix cədvəlini dəyişdirmək olardı.
        #    İki mövcud dəyərdən DOĞRUSU budur — dəyişikliyin təşəbbüskarı
        #    işçidir, admin deyil. "NİYƏ dəyişdi?" sualının dəqiq cavabı isə
        #    audit jurnalındakı `OPEN_SHIFT_CLAIMED` sətridir.
        change = self._planning.apply_assignment(
            tenant_id=tenant_id,
            actor_id=employee.id,
            employee_id=employee.id,
            shift_date=posting.shift_date,
            is_off_day=False,
            work_mode_id=posting.work_mode_id,
            source=ShiftSource.SHIFT_SWAP,
        )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="OPEN_SHIFT_CLAIMED",
            entity_type="open_shift_postings",
            entity_id=posting.id,
            after_state=posting.to_audit_state(),
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            # Elanı AÇAN şəxs xəbər tutur: boşluğun doldurulub-doldurulmadığı
            # onun məsuliyyətidir (migrations/019 `posted_by` şərhi).
            recipient_id=posting.posted_by,
            category="OPEN_SHIFT_CLAIMED",
            title_az="Açıq növbə götürüldü",
            body_az=(
                f"{posting.shift_date.isoformat()} tarixli açıq növbəni "
                f"{employee.full_name} götürdü."
            ),
            is_critical=False,
        )
        return change

    # ------------------------------- köməkçi --------------------------------- #

    def _require_eligible(
        self, employee: Employee, posting: OpenShiftPosting, *, now: datetime
    ) -> None:
        """İşçinin bu elanı götürməyə uyğunluğu — HAMISI SƏRT qaydadır."""
        if posting.status is OpenShiftStatus.CANCELLED:
            # BU YOXLAMA YARIŞ QAPAĞI DEYİL (o, şərti UPDATE-dədir) — YALNIZ
            # MESAJ ÜÇÜNDÜR: ləğv edilmiş elana "başqası götürüb" demək işçini
            # olmayan bir rəqib axtarmağa yönəldərdi.
            raise OpenShiftError(
                "Elan ləğv edilib",
                user_message="Bu elan ləğv edilib.",
                context={"posting_id": str(posting.id)},
            )
        if posting.store_id != employee.store_id:
            raise OpenShiftNotEligibleError(
                "İşçi bu mağazaya aid deyil",
                user_message="Bu növbə başqa mağaza üçündür.",
                context={"posting_id": str(posting.id)},
            )
        if posting.shift_date < now.date():
            # Keçmiş tarixli elan (məs. ləğv edilməmiş köhnə sətir) tutulsaydı,
            # `shift_assignments`-ə keçmiş gün yazılar və gecikmə hesablaması
            # geriyə dönük dəyişərdi.
            raise OpenShiftNotEligibleError(
                "Keçmiş tarixli növbə tutula bilməz",
                user_message="Bu növbənin tarixi keçib.",
                context={"shift_date": posting.shift_date.isoformat()},
            )
        if self._has_working_assignment(employee.id, posting.shift_date):
            # `shift_assignments UNIQUE (employee_id, shift_date)` səbəbindən
            # yazı mövcud növbənin ÜSTÜNDƏN yazardı — işçi öz növbəsini
            # bilmədən itirərdi.
            raise OpenShiftNotEligibleError(
                "İşçinin həmin gün üçün artıq iş növbəsi var",
                user_message="Həmin gün üçün artıq növbəniz var.",
                context={"shift_date": posting.shift_date.isoformat()},
            )

        monthly_cap = self._limit_int(
            posting.tenant_id,
            SystemLimitKey.OPEN_SHIFT_MAX_CLAIMS_PER_MONTH,
            FALLBACK_MAX_CLAIMS_PER_MONTH,
        )
        taken = self._postings.count_claims_in_month(
            employee.id, year=posting.shift_date.year, month=posting.shift_date.month
        )
        if taken >= monthly_cap:
            raise OpenShiftNotEligibleError(
                f"Aylıq açıq növbə tavanı doldu ({taken}/{monthly_cap})",
                user_message=(f"Bu ay {monthly_cap} açıq növbə götürmüsünüz — aylıq hədd doldu."),
                context={"taken": taken, "cap": monthly_cap},
            )

    def _has_working_assignment(self, employee_id: EmployeeId, shift_date: date) -> bool:
        """Həmin gün İŞ növbəsi varmı.

        İSTİRAHƏT GÜNÜ MANE OLMUR — açıq bazarın bütün mənası məhz odur ki,
        işçi öz istirahət günündə könüllü olaraq növbə götürə bilsin. Yalnız
        artıq planlaşdırılmış İŞ günü blokdur.
        """
        existing = self._shifts.get_assignment(employee_id, shift_date)
        return existing is not None and existing.is_working_day

    def _require_posting(self, posting_id: OpenShiftPostingId, *, locked: bool) -> OpenShiftPosting:
        posting = (
            self._postings.get_for_update(posting_id) if locked else self._postings.get(posting_id)
        )
        if posting is None:
            raise OpenShiftNotFoundError(
                "Açıq növbə elanı tapılmadı",
                context={"posting_id": str(posting_id)},
            )
        return posting

    @staticmethod
    def _require_same_tenant(posting: OpenShiftPosting, tenant_id: TenantId) -> None:
        """RLS və repo şərtindən SONRAKI üçüncü izolyasiya qatı."""
        if posting.tenant_id != tenant_id:
            raise OpenShiftNotFoundError(
                "Elan başqa kirayəçiyə aiddir",
                context={"posting_id": str(posting.id)},
            )

    def _require_manage(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_SHIFTS_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "OPEN_SHIFT_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_SHIFTS_FLAG},
            )
            raise ShiftPermissionError(
                f"«{MANAGE_SHIFTS_FLAG}» səlahiyyəti yoxdur",
                user_message="Açıq növbə elan etmək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )

    def _require_module(self, tenant_id: TenantId) -> None:
        """Toggle YALNIZ yeni elan üçün — bax modul başlığı (retroaktivlik)."""
        if not self._toggles.is_enabled(tenant_id, FeatureModule.SHIFT_SWAP.value):
            raise OpenShiftError(
                "SHIFT_SWAP modulu deaktiv edilib",
                user_message="Növbə self-service modulu hazırda aktiv deyil.",
                context={"module": FeatureModule.SHIFT_SWAP.value},
            )

    @staticmethod
    def _drain(posting: OpenShiftPosting) -> None:
        """Aqreqatın topladığı hadisələri YAZIDAN SONRA boşaldır.

        Hadisə avtobusu bu use case-ə injeksiya edilmir: bazar çox-aqreqatlı
        saga deyil və hadisələr yalnız audit/telemetriya üçündür
        (`exception_engine._drain` ilə eyni qərar). Boşaltmaq isə vacibdir —
        eyni aqreqat obyekti təkrar işlədilsə (məs. elan yaradılıb dərhal
        ləğv ediləndə), hadisələr yığılıb ikinci dəfə yayımlanardı.
        """
        posting.collect_events()

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey, fallback: int) -> int:
        """ROOT limiti — mənbə `system_limits`, sinifdəki sabit yalnız fallback."""
        value = self._limits.get_int(tenant_id, key.value, fallback)
        return value if value > 0 else fallback


def _to_view(posting: OpenShiftPosting) -> OpenShiftView:
    return OpenShiftView(
        posting_id=posting.id,
        store_id=posting.store_id,
        shift_date=posting.shift_date,
        work_mode_id=posting.work_mode_id,
        status=posting.status.value,
        posted_by=posting.posted_by,
        claimed_by=posting.claimed_by,
        created_at=posting.created_at,
    )


__all__ = [
    "FALLBACK_MAX_CLAIMS_PER_MONTH",
    "FALLBACK_MAX_LEAD_DAYS",
    "OpenShiftAlreadyClaimedError",
    "OpenShiftError",
    "OpenShiftMarketUseCase",
    "OpenShiftNotEligibleError",
    "OpenShiftNotFoundError",
    "OpenShiftView",
]
