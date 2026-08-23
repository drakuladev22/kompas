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
    EXPIRED_CANCEL_REASON,
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

#: `expire_stale_postings` bir icrada neçə açıq elan oxuyur — «Root parametri
#: DEYİL».
#:
#: Bu, SORĞU ölçüsüdür, biznes həddi deyil: elan `OPEN_SHIFT_MAX_LEAD_DAYS`
#: qədər irəli verilə bildiyi üçün bir kirayəçidə eyni anda açıq elanların
#: sayı onsuz da təbii olaraq məhduddur. Tavanın YEGANƏ rolu bir gecəlik
#: icranın bütün cədvəli yaddaşa çəkməməsidir; qalanlar NÖVBƏTİ icrada
#: bağlanır (iş at-least-once işləyir). Root-a verilsəydi, onu kiçildən adam
#: təmizliyi sükutla dayandıra bilərdi.
_EXPIRY_SCAN_LIMIT: Final[int] = 500

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

    def list_claimed_for_employee(
        self, *, tenant_id: TenantId, employee: Employee
    ) -> list[OpenShiftView]:
        """«Tutduğum növbələr» — `[Geri Ver]` düyməsinin sətirləri (OP-4).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA OXU YOLU LAZIM İDİ
        ──────────────────────────────────────────────────────────────────────
        `list_for_employee` işçinin TUTA BİLƏCƏYİ açıq elanları göstərir və
        tutulmuş sətir oradan DƏRHAL yox olur (`list_open` yalnız `OPEN`
        gətirir). Yəni `release_claim()` yazılsa da, onu çağıracaq bir sətir
        heç bir ekranda görünmürdü — funksiya ölü qalırdı.

        SƏLAHİYYƏT TƏLƏB OLUNMUR: bu, işçinin ÖZ ekranıdır və yalnız ÖZ
        sətirlərini qaytarır (`list_for_employee` ilə eyni qərar). Süzgəc
        repo-da `employee_id` ilə qoyulur, yəni başqasının sətri buraya
        struktur olaraq düşə bilmir.

        ──────────────────────────────────────────────────────────────────────
        KEÇMİŞ TARİXLƏR NİYƏ SÜZÜLÜR — VƏ NİYƏ MƏHZ BURADA
        ──────────────────────────────────────────────────────────────────────
        Keçmiş növbəni «geri vermək» mənasızdır: gün ARTIQ baş verib, işçi ya
        işləyib, ya işləməyib və hər iki halda faktı sonradan dəyişdirmək
        davamiyyət tarixçəsini yenidən yazmaq olardı.

        Süzgəc AQREQATDA deyil, BURADA-dır: `OpenShiftPosting.release()`
        qəsdən tarixə baxmır, çünki aqreqatın öhdəliyi vəziyyət maşınının
        bütövlüyüdür — «hansı tarix aralığı iş üçün mənalıdır?» sualı isə
        tətbiq qaydasıdır (eyni ayrım `_require_eligible`-dədir: orada da
        tarix şərti use case qatındadır).
        """
        postings = self._postings.list_claimed(
            employee_id=employee.id, from_date=self._clock.now().date()
        )
        return [_to_view(item) for item in self._same_tenant_only(postings, tenant_id)]

    def list_claimed_for_store(
        self, *, tenant_id: TenantId, actor: Employee, store_id: StoreId | None = None
    ) -> list[OpenShiftView]:
        """Admin görünüşü — kirayəçidəki BÜTÜN tutulmuş, hələ baş verməmiş növbələr.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BU DA LAZIMDIR
        ──────────────────────────────────────────────────────────────────────
        `release_claim()` iki aktora icazə verir: növbəni tutan işçi VƏ
        `can_manage_shifts` sahibi. İkinci qol yalnız işçi-ekranı olsaydı
        ÇAĞIRILA BİLMƏZDİ — yəni eyni «ölü funksiya» problemi menecer
        tərəfində qalardı. Bu metod həmin qolu bağlayır.

        `list_active` (açıq elanlar) İLƏ QARIŞDIRILMIR: o, «hələ kimsə
        götürməyib» siyahısıdır və menecerin işi orada slotu ELAN ETMƏKDİR;
        burada isə slot DOLUDUR və menecerin işi lazım gəldikdə onu
        BOŞALTMAQDIR (işçi xəstələnib, xəbər verə bilmir).
        """
        self._require_manage(actor)
        postings = self._postings.list_claimed(from_date=self._clock.now().date())
        rows = self._same_tenant_only(postings, tenant_id)
        if store_id is not None:
            rows = [item for item in rows if item.store_id == store_id]
        return [_to_view(item) for item in rows]

    def _same_tenant_only(
        self, postings: list[OpenShiftPosting], tenant_id: TenantId
    ) -> list[OpenShiftPosting]:
        """Kirayəçi süzgəcinin ÜÇÜNCÜ qatı — `_require_same_tenant`-in siyahı qarşılığı.

        `list_claimed` SAAS-1-ə görə `tenant_id` arqumenti ALMIR: süzgəc
        bağlantının öz kontekstindən (`self._tenant`) gəlir. Həmin arqumenti
        itirməklə bu use case-in digər yollarındakı açıq yoxlamanı da
        itirmək DÜZGÜN OLMAZDI — RLS və repo şərti onsuz da işləyir, lakin
        yanlış konteksli bağlantı DİAQNOSTİKA baxımından görünməz qalardı
        (`tenant_argument_audit.py` başlığındakı eyni əsaslandırma).

        Yad sətir SÜKUTLA atılmır: jurnala düşür, çünki bura düşməsi
        proqram xətasının əlamətidir.
        """
        kept: list[OpenShiftPosting] = []
        for posting in postings:
            if posting.tenant_id == tenant_id:
                kept.append(posting)
                continue
            _audit_log.warning(
                "OPEN_SHIFT_FOREIGN_TENANT_ROW",
                extra={"posting_id": str(posting.id), "expected_tenant": str(tenant_id)},
            )
        return kept

    def release_claim(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        posting_id: OpenShiftPostingId,
        reason: str,
    ) -> OpenShiftPosting:
        """`[Növbəni Geri Ver]` — tutulmuş slot bazara QAYIDIR (OP-4).

        ──────────────────────────────────────────────────────────────────────
        BOŞLUQ NƏ İDİ
        ──────────────────────────────────────────────────────────────────────
        `claim()` TERMİNAL idi. İşçi növbəni götürüb sonra xəstələnsə, nə o,
        nə admin onu geri qaytara bilirdi: slot təqvimdə DOLU görünürdü,
        faktiki isə boş qalırdı və heç kim onun yenidən doldurulmalı olduğunu
        BİLMİRDİ.

        ──────────────────────────────────────────────────────────────────────
        KİM GERİ VERƏ BİLƏR — VƏ NİYƏ MƏHZ BU İKİSİ
        ──────────────────────────────────────────────────────────────────────
        Növbəni TUTAN işçinin ÖZÜ, **və ya** `can_manage_shifts` sahibi.
        Bu, YENİ qayda deyil — `AnnualLeaveUseCase.cancel`-ın mövcud
        qaydasının eynisidir («sorğunun SAHİBİ və ya idarəçi; ÜÇÜNCÜ şəxs
        YOX») və eyni səbəbə görə: götürülmüş öhdəlik işçinin ÖZ öhdəliyidir,
        onu üçüncü bir işçinin əlindən alması isə məhz `OpenShiftStatus`
        başlığındakı köhnə qadağanın qorumaq istədiyi haldır.

        ──────────────────────────────────────────────────────────────────────
        NÖVBƏ MATRİSİ TƏK YAZMA NÖQTƏSİNDƏN GERİ ALINIR
        ──────────────────────────────────────────────────────────────────────
        `claim()` təyinatı `apply_assignment(is_off_day=False)` ilə yazır;
        burada eyni metod `is_off_day=True` ilə çağırılır. Matrisə BİRBAŞA
        toxunmuruq (bölmə 3 «məntiq təkrarlanmır») — konflikt yoxlaması,
        audit sətri və açıq icazə sorğularının yenidən qiymətləndirilməsi
        AVTOMATİK işləyir.

        TƏYİNAT TUTAN İŞÇİNİN ADINA geri alınır, aktorun adına YOX: menecer
        geri verəndə matrisdə dəyişməli olan sətir MENECERİN yox, növbəni
        götürmüş işçinin sətridir. `claimed_by` `release()` çağırışından ƏVVƏL
        oxunur, çünki həmin metod onu təmizləyir (invariant tələbi).

        `is_off_day=True` SEÇİMİ: `_require_eligible` tutma anında işçinin
        həmin gün İŞ növbəsi OLMADIĞINI təmin edib (ya sətir yox idi, ya da
        istirahət günü idi). Deməli «işləmir» vəziyyətinə qaytarmaq doğru
        istiqamətdir. Fərq yalnız birinci halda qalır — əvvəl SƏTİR YOX idi,
        indi «istirahət» sətri yaranır; nəticə eynidir (işçi həmin gün
        işləmir), sətrin özü isə auditdə izi saxlayır.
        """
        now = self._clock.now()
        posting = self._require_posting(posting_id, locked=True)
        self._require_same_tenant(posting, tenant_id)
        claimed_by = self._require_release_rights(actor, posting)
        if posting.shift_date < now.date():
            # EKRANI YAN KEÇƏN YOL DA EYNİ QAPIYA ÇIRPILIR: siyahı keçmiş
            # növbələri onsuz da göstərmir (`list_claimed_for_employee`),
            # lakin süzgəcə GÜVƏNMƏK kifayət deyil — skript/plugin birbaşa
            # bu metodu çağıra bilər. Keçmiş növbəni geri vermək təqvimi
            # geriyə dönük «istirahət» edərdi, yəni davamiyyət tarixçəsi
            # sonradan yenidən yazılardı.
            raise OpenShiftError(
                "Keçmiş tarixli növbə geri verilə bilməz",
                user_message="Bu növbənin tarixi keçib.",
                context={
                    "posting_id": str(posting_id),
                    "shift_date": posting.shift_date.isoformat(),
                },
            )
        before_state = posting.to_audit_state()

        # Domen qaydası ƏVVƏLCƏ (status + səbəbin uzunluğu) — DB-yə yararsız
        # sorğu göndərməmək üçün (`cancel_posting` ilə eyni sıra).
        posting.release(released_by=actor.id, released_at=now, reason=reason)
        if not self._postings.release(posting_id=posting_id, released_by=actor.id, released_at=now):
            # Kilid alınana qədər başqa tranzaksiya sətri dəyişib (məs. admin
            # elanı ləğv edib). Aqreqat yaddaşda `OPEN` göstərir, bazada isə
            # yox — hadisə HEÇ VAXT baş verməmiş sayılmalıdır (CLAUDE.md §3).
            posting.discard_events()
            raise OpenShiftError(
                "Elan geri buraxılmazdan əvvəl dəyişib",
                user_message="Bu elan artıq dəyişib — səhifəni yeniləyin.",
                context={"posting_id": str(posting_id)},
            )

        self._planning.apply_assignment(
            tenant_id=tenant_id,
            actor_id=actor.id,
            employee_id=claimed_by,
            shift_date=posting.shift_date,
            is_off_day=True,
            work_mode_id=None,
            source=ShiftSource.SHIFT_SWAP,
        )
        self._drain(posting)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="OPEN_SHIFT_RELEASED",
            entity_type="open_shift_postings",
            entity_id=posting.id,
            before_state=before_state,
            after_state={**posting.to_audit_state(), "released_employee": str(claimed_by)},
            reason=reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            # Elanı AÇAN şəxs XƏBƏR TUTMALIDIR: slot yenidən boşdur və onu
            # doldurmaq onun məsuliyyətidir (`claim`-in eyni qərarı).
            recipient_id=posting.posted_by,
            category="OPEN_SHIFT_RELEASED",
            title_az="Açıq növbə geri verildi",
            body_az=(
                f"{posting.shift_date.isoformat()} tarixli açıq növbə geri verildi. "
                f"Səbəb: {reason}. Slot yenidən açıqdır və doldurulmalıdır."
            ),
            is_critical=True,
        )
        return posting

    def expire_stale_postings(self, tenant_id: TenantId) -> int:
        """Tarixi KEÇMİŞ açıq elanları bağlayır (planlaşdırılmış iş, OP-4).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ EKRAN SÜZGƏCİ KİFAYƏT ETMİR
        ──────────────────────────────────────────────────────────────────────
        `list_active`/`list_for_employee` onsuz da `from_date=bugün` ötürür,
        yəni işçi keçmiş elan GÖRMÜR. Lakin sətir bazada əbədi `OPEN` qalır:
        «neçə açıq elan var?» sualı hesabatda ildən-ilə böyüyən yalan rəqəm
        verir və qismən unikal indeks heç vaxt təkrarlanmayacaq slotlar üçün
        yer tutmağa davam edir.

        SƏLAHİYYƏT YOXLANMIR: insan aktoru olmayan planlayıcı işidir
        (`FineAppealUseCase.expire_stale` ilə eyni forma). Audit
        `actor_id=None` ilə yazılır — qərarı insan vermir, müddət bitir.

        FEATURE TOGGLE YOXLANMIR: modul söndürülsə də köhnə sətirlər
        təmizlənməlidir (retroaktivlik qaydası — söndürmə YALNIZ YENİ elanı
        bloklayır, mövcudların axınını tamamlamağa mane olmur).

        Returns:
            Bağlanan elan sayı — planlayıcının icra hesabatı üçün.
        """
        now = self._clock.now()
        closed = 0
        for posting in self._postings.list_open(tenant_id, limit=_EXPIRY_SCAN_LIMIT):
            if not posting.expire(now=now):
                continue
            if not self._postings.expire(posting_id=posting.id, expired_at=now):
                # Paralel tutma/ləğv qabaqlayıb — sətir artıq `OPEN` deyil.
                continue
            closed += 1
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="OPEN_SHIFT_EXPIRED",
                entity_type="open_shift_postings",
                entity_id=posting.id,
                after_state=posting.to_audit_state(),
                reason=EXPIRED_CANCEL_REASON,
            )
        if closed:
            _audit_log.info(
                "OPEN_SHIFTS_EXPIRED",
                extra={"tenant_id": str(tenant_id), "count": closed},
            )
        return closed

    def _require_release_rights(self, actor: Employee, posting: OpenShiftPosting) -> EmployeeId:
        """Geri buraxma hüququ: TUTAN işçinin ÖZÜ və ya `can_manage_shifts`.

        Returns:
            Növbəni TUTAN işçinin identifikatoru — çağıran onu təqvimi geri
            almaq üçün işlədir (`release()` sahəni təmizləməzdən ƏVVƏL).
        """
        claimed_by = posting.claimed_by
        if claimed_by is None:
            # Tutulmamış elan geri buraxıla bilməz. Domen də bunu kəsir, lakin
            # burada AYRICA yoxlanılır: mesaj konkret olmalıdır və `None`
            # sahibi ilə sahiblik müqayisəsi mənasızdır.
            raise OpenShiftError(
                "Tutulmamış elan geri buraxıla bilməz",
                user_message="Bu növbə tutulmayıb.",
                context={"posting_id": str(posting.id), "status": posting.status.value},
            )
        if actor.id == claimed_by:
            return claimed_by
        self._require_manage(actor)
        return claimed_by

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
