"""İllik Məzuniyyət Balansı (#28) — kompas1.md Faza 4.

──────────────────────────────────────────────────────────────────────────────
BU MODUL MÖVCUD İKİ MEXANİZMƏ TOXUNMUR
──────────────────────────────────────────────────────────────────────────────
Ayrılığın tam cədvəli `domain/entities/annual_leave.py` başlığındadır. Tətbiq
qatı üçün praktik nəticələri bunlardır:

  * `LeaveVerificationUseCase` / `MorningCheckInUseCase` ÇAĞIRILMIR və
    onların heç bir sətri dəyişmir. Gündaxili icazənin aylıq 240 dəqiqəlik
    tavanı (`MonthlyLeaveUsage`) illik balansdan ASILI DEYİL və əksi də
    doğrudur.
  * `ShiftPlanningUseCase` ÇAĞIRILMIR. Təsdiqlənmiş məzuniyyət Shift
    Matrix-i YENİLƏMİR — yalnız OXUYUR (hansı gün istirahətdir?). Bu,
    `ShiftSwapUseCase.approve`-dan qəsdən fərqlidir: orada sorğunun MƏNASI
    təqvimi dəyişməkdir, burada isə məzuniyyət haqqın istifadəsidir və
    təqvimi HR ayrıca planlaşdırır. Əks halda eyni günə iki mənbə yazardı
    (`ShiftSource` "kim dəyişdi?" sualını cavablandıra bilməzdi).

──────────────────────────────────────────────────────────────────────────────
LAKİN SÜKUT DA CAVAB DEYİL — TƏSDİQ PLANI BOŞ QOYA BİLƏR
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı qərarın (matris YENİLƏNMİR) ödənilməmiş qiyməti var: işçi ARTIQ
növbəyə salınmışsa və məzuniyyət SONRA təsdiqlənirsə, matrisdə həmin günlər
iş günü olaraq qalır. Mağaza həmin günə adam gözləyir, işçi isə qanuni
məzuniyyətdədir — yəni növbə SÜKUTLA boş qalır.

Qərar `_warn_planned_shifts`-dədir və o, matrisi DƏYİŞMİR (yuxarıdakı qayda
qüvvədədir), yalnız MÖVCUD `SHIFT_CHANGE_CONFLICT` bildiriş kanalına sətir
yazır. Həmin kanalın auditoriyası `can_manage_shifts`-dir
(`value_objects/notifications.py`) — yəni günü YENİDƏN PLANLAYA BİLƏN şəxs.
Yeni kateqoriya YARADILMADI: kanalın mövcud tərifi elə "növbə PLANI ilə
faktiki vəziyyət arasındakı fərq"dir və bu, məhz o fərqdir.

TƏSDİQ BLOKLANMIR: işçinin qanuni haqqını mağazanın planlaşdırma boşluğuna
görə rədd etmək qaydanı tərsinə çevirərdi. Planlaşdırma problemi
planlayıcının həll edəcəyi problemdir və ona görə ona xəbər verilir.

──────────────────────────────────────────────────────────────────────────────
TƏSDİQ AXINI — SHIFT SWAP NAXIŞININ TƏKRARI
──────────────────────────────────────────────────────────────────────────────
`submit` / `pending_inbox` / `my_requests` / `approve` / `reject` metod dəsti
və onların daxili sırası `ShiftSwapUseCase`-dən götürülüb: səlahiyyət → domen
qaydası (entity) → yazma → audit → bildiriş. Yeni təsdiq mexanizmi
YAZILMAYIB.

`add_manager_note()` QƏSDƏN YOXDUR: `annual_leave_requests` cədvəlində
`manager_note`/`manager_id` sütunları yoxdur (migrations/037) və qeydi
`decision_note`-a yazmaq onu qərar mətni ilə qarışdırardı — həmin sütunun
sahibi QƏRARDIR (`chk_annual_leave_request_decision`).

──────────────────────────────────────────────────────────────────────────────
YARIŞ QAPAĞI TƏTBİQ QATINDA DEYİL
──────────────────────────────────────────────────────────────────────────────
İki paralel təsdiq balansı mənfiyə salmamalıdır. Burada HEÇ BİR yerdə
"əvvəlcə oxu, sonra yaz" yoxlaması qərar vermir: `AnnualLeaveBalance
Repository.consume()` ŞƏRTLİ `UPDATE` icra edir və `rowcount` qaytarır
(`open_shift_repository.claim` naxışı). Oxu yalnız İZAH üçündür — "7 gün
qalıb, 10 gün istənilir" mesajını qurmaq üçün.

Üst-üstə düşən TƏSDİQLƏNMİŞ aralıqların qapağı isə tamamilə DB-dədir
(`excl_annual_leave_no_overlap`, `EXCLUDE USING gist`); repo həmin pozuntunu
tutub izaha çevirir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA YOX
──────────────────────────────────────────────────────────────────────────────
Təsdiq İKİ aqreqata toxunur (sorğu + balans), lakin `SagaOrchestrator`
işlədilmir — `ShiftSwapUseCase.approve` ilə eyni qərar. Səbəb: hər iki yazı
EYNİ tranzaksiyadadır (`Session`), yəni atomiklik onsuz da təmin olunur;
Saga isə xarici sistemə (Drive, 1C, e-poçt) çıxan, tranzaksiya ilə örtülə
BİLMƏYƏN addımlar üçündür (`LeaveVerificationUseCase.verify_return`).
Buna baxmayaraq `approve()` uğursuzluq yolunda AÇIQ kompensasiya edir
(`_release_quietly`) — çünki use case tranzaksiyasız (yaddaş repo-su ilə)
də çağırıla bilər və o halda balans sükutla azalmış qalardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.domain.annual_leave_rules import (
    AnnualLeavePolicy,
    LeaveDayCountMode,
    quantize_days,
)
from src.domain.entities.annual_leave import (
    AnnualLeaveBalance,
    AnnualLeaveRequest,
    AnnualLeaveStatus,
)
from src.domain.value_objects.identifiers import (
    new_annual_leave_balance_id,
    new_annual_leave_request_id,
)
from src.domain.value_objects.scheduling import DEFAULT_TIMEZONE
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AnnualLeaveBalanceRepository,
        AnnualLeaveRequestRepository,
        AuditTrail,
        Clock,
        Notifier,
        ShiftRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import (
        AnnualLeaveRequestId,
        EmployeeId,
        TenantId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: `migrations/038`-də yaradılmış flag. YENİSİ YARADILMIR: həm balansın əl
#: ilə düzəldilməsi, həm sorğunun təsdiqi eyni məsuliyyətdir (HR) və iki flag
#: "təsdiq edə bilir, amma balansı görə bilmir" kimi mənasız kombinasiyalar
#: yaradardı.
MANAGE_LEAVE_BALANCES_FLAG = "can_manage_leave_balances"

#: Bildiriş kateqoriyaları — `SHIFT_SWAP_*` naxışı (kanal adı ekranda süzgəcdir).
PENDING_NOTIFICATION_CATEGORY = "ANNUAL_LEAVE_PENDING"
DECIDED_NOTIFICATION_CATEGORY = "ANNUAL_LEAVE_DECIDED"

#: MÖVCUD kanal — `shift_scheduling` ilə EYNİ sətir (bax modul başlığı:
#: "SÜKUT DA CAVAB DEYİL"). Auditoriyası `can_manage_shifts`-dir, yəni günü
#: yenidən planlaya bilən şəxs. Yeni kateqoriya yaratsaydıq, o,
#: `TENANT_NOTIFICATION_AUDIENCE`-də olmadığı üçün fail-open ilə HAMIYA —
#: o cümlədən `Satıcı`-ya — görünərdi.
SHIFT_CONFLICT_NOTIFICATION_CATEGORY = "SHIFT_CHANGE_CONFLICT"

#: Bütün TƏQVİM qərarları (hansı il? son tarix keçibmi?) MAĞAZANIN yerli
#: gününə görə verilir, UTC-yə görə YOX. `Clock` UTC qaytarır və Bakı UTC+4
#: olduğu üçün 31 dekabr saat 21:00 (yerli 1 yanvar 01:00) UTC ilə hesablansaydı
#: köçürmə BİR GÜN gec işləyərdi — `checkin_minutes_since_midnight` ilə eyni
#: əsaslandırma (`value_objects/scheduling.py`).
_LOCAL_TZ = ZoneInfo(DEFAULT_TIMEZONE)

_ZERO = Decimal("0")


class AnnualLeaveError(KompasOSError):
    """İllik məzuniyyət qaydası pozuldu (balans, tarix, status)."""

    user_message = "Məzuniyyət sorğusu emal edilə bilmədi."


class AnnualLeavePermissionError(KompasOSError):
    """`can_manage_leave_balances` yoxdur."""

    user_message = "Məzuniyyət balanslarını idarə etmək səlahiyyətiniz yoxdur."


class AnnualLeaveRequestNotFoundError(AnnualLeaveError):
    """Sorğu tapılmadı."""

    user_message = "Məzuniyyət sorğusu tapılmadı."


@dataclass(frozen=True)
class AnnualLeaveBalanceView:
    """İşçi Ana Ekranındakı balans kartının məlumatı ("14/21 gün qalıb").

    `available`/`total` AYRI sahələrdir və hesablanmış mətn DEYİL: ekran
    onları öz dilində birləşdirir (GUI qatının işi), tətbiq qatı isə
    rəqəmləri verir. Mətn burada qurulsaydı, HR paneli və işçi kartı eyni
    cümləni fərqli formatda göstərmək istəyəndə use case dəyişməli olardı.
    """

    year: int
    entitled_days: Decimal
    carried_over_days: Decimal
    used_days: Decimal
    available_days: Decimal
    total_days: Decimal
    carryover_deadline: date
    carryover_expired: bool


@dataclass(frozen=True)
class YearRolloverReport:
    """`ANNUAL_LEAVE_YEAR_ROLLOVER` işinin nəticəsi — sağlamlıq ekranı üçün."""

    year: int
    employees_processed: int
    balances_written: int
    manual_rows_skipped: int
    carried_over_days: Decimal
    forfeited_days: Decimal
    expired_carryover_rows: int


class AnnualLeaveUseCase:
    """İllik məzuniyyət haqqı, sorğusu və təsdiqi (#28)."""

    def __init__(
        self,
        *,
        balances: AnnualLeaveBalanceRepository,
        requests: AnnualLeaveRequestRepository,
        shifts: ShiftRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        limits: SystemLimits | None = None,
    ) -> None:
        """
        Args:
            shifts: Shift Matrix — YALNIZ OXUNUR (`list_range`). Yazma metodu
                heç vaxt çağırılmır: təsdiqlənmiş məzuniyyət növbə planını
                dəyişmir (bax modul başlığı).
            limits: ROOT parametrlərinə açılan pəncərə. `None` = fallback
                (`AnnualLeavePolicy.defaults()`) — `ShiftSwapUseCase` ilə eyni
                naxış: port bağlanmayan çağırış yolları davranışını dəyişmir.
        """
        self._balances = balances
        self._requests = requests
        self._shifts = shifts
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        self._limits = limits

    # ------------------------------- siyasət --------------------------------- #

    def policy(self, tenant_id: TenantId) -> AnnualLeavePolicy:
        """ROOT parametrlərindən qurulmuş siyasət — HƏR ÇAĞIRIŞDA yenidən oxunur.

        Konstruktorda bir dəfə qurulsaydı, Root dəyəri dəyişəndə mövcud
        sessiya köhnə siyasətlə işləməyə davam edərdi və dəyişikliyin təsiri
        proqramın yenidən başladılmasına bağlanardı (`ShiftSwapUseCase.submit`
        ilə eyni əsaslandırma).
        """
        if self._limits is None:
            return AnnualLeavePolicy.defaults()
        try:
            return AnnualLeavePolicy.from_limits(self._limits.all_for(tenant_id))
        except Exception as exc:
            # Oxu uğursuzluğu ƏMƏLİYYATI DAYANDIRMIR (bax `root_limits._raw`):
            # verilməli cavab "işləsinmi" deyil, "hansı siyasətlə" idi.
            _audit_log.warning("ANNUAL_LEAVE_POLICY_READ_FAILED", extra={"error": str(exc)})
            return AnnualLeavePolicy.defaults()

    # -------------------------------- balans --------------------------------- #

    def my_balance(self, *, tenant_id: TenantId, employee: Employee) -> AnnualLeaveBalanceView:
        """İşçinin ÖZ balansı — səlahiyyət TƏLƏB OLUNMUR.

        Öz haqqını görmək üçün `can_manage_leave_balances` istəmək işçiyə
        BAŞQALARININ balansını dəyişmək hüququ vermək demək olardı
        (`ShiftSwapUseCase.my_requests` ilə eyni qərar).
        """
        return self._view(tenant_id=tenant_id, employee=employee)

    def balance_for(
        self, *, tenant_id: TenantId, actor: Employee, employee: Employee, year: int | None = None
    ) -> AnnualLeaveBalanceView:
        """HR panelinin "işçinin balansı" görünüşü — flag TƏLƏB OLUNUR."""
        self._require_manager(actor)
        return self._view(tenant_id=tenant_id, employee=employee, year=year)

    def list_balances(
        self, *, tenant_id: TenantId, actor: Employee, year: int | None = None
    ) -> list[AnnualLeaveBalance]:
        """HR panelinin il üzrə balans siyahısı."""
        self._require_manager(actor)
        return self._balances.list_for_year(tenant_id, year=year or self._today().year)

    def adjust_balance(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee: Employee,
        year: int,
        entitled_days: Decimal,
        carried_over_days: Decimal,
        reason: str,
    ) -> AnnualLeaveBalanceView:
        """Balansın ƏL İLƏ düzəlişi (miras haqq, məhkəmə qərarı, idxal səhvi).

        `updated_by` MƏCBURİ doldurulur — `migrations/037`: "bu rəqəmi kim
        dəyişdi?" mübahisədə ilk sualdır və rəqəm PUL dəyəri daşıyır. Həmin
        sütun eyni zamanda il dönümü işinin qoruyucusudur: `updated_by IS NOT
        NULL` olan sətir gecə işi tərəfindən üstündən yazılmır (bax
        `AnnualLeaveBalanceRepository.set_entitlement`).
        """
        self._require_manager(actor)
        if entitled_days < 0 or carried_over_days < 0:
            raise AnnualLeaveError(
                "Balans dəyərləri mənfi ola bilməz",
                user_message="Gün sayı mənfi ola bilməz.",
                context={"entitled": str(entitled_days), "carried_over": str(carried_over_days)},
            )
        before = self._balances.get(employee.id, year=year)
        self._balances.set_entitlement(
            tenant_id=tenant_id,
            employee_id=employee.id,
            year=year,
            entitled_days=quantize_days(entitled_days),
            carried_over_days=quantize_days(carried_over_days),
            updated_by=actor.id,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ANNUAL_LEAVE_BALANCE_ADJUSTED",
            entity_type="annual_leave_balances",
            entity_id=employee.id,
            before_state=None if before is None else _balance_state(before),
            after_state={
                "year": year,
                "entitled_days": str(quantize_days(entitled_days)),
                "carried_over_days": str(quantize_days(carried_over_days)),
            },
            reason=reason,
        )
        return self._view(tenant_id=tenant_id, employee=employee, year=year)

    # ------------------------------- göndər ---------------------------------- #

    def submit(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        start_date: date,
        end_date: date,
    ) -> AnnualLeaveRequest:
        """İşçi Ana Ekranındakı `[Məzuniyyət Sorğusu]`.

        BALANS BURADA ÇIXILMIR — yalnız təsdiqdə. Səbəb `ShiftSwapRequest`
        docstring-indəki qərarın eynisidir: gözləyən sorğu heç nəyi
        dəyişməməlidir, əks halda rədd edilən sorğu balansı müvəqqəti
        bloklayardı və işçi "günlərim hara getdi?" sualı ilə qalardı.

        Yoxlama isə EDİLİR (`available_days`), çünki balansı onsuz da
        çatmayan sorğunu HR-ın növbəsinə salmaq hər iki tərəfin vaxtını
        itirməkdir.
        """
        now = self._clock.now()
        today = now.astimezone(_LOCAL_TZ).date()

        if start_date < today:
            raise AnnualLeaveError(
                "Keçmiş tarix üçün məzuniyyət sorğusu göndərilə bilməz",
                user_message="Keçmiş tarixə məzuniyyət sorğusu göndərmək olmaz.",
                context={"start_date": start_date.isoformat()},
            )

        overlapping = self._requests.find_overlapping_approved(
            employee.id, start=start_date, end=end_date
        )
        if overlapping is not None:
            # `EXCLUDE` qapağının ERKƏN, izahlı forması — qapağı əvəz etmir.
            raise AnnualLeaveError(
                "Bu tarixlər üçün artıq təsdiqlənmiş məzuniyyət var",
                user_message=(
                    "Bu tarixlər üçün artıq təsdiqlənmiş məzuniyyətiniz var "
                    f"({overlapping.start_date.isoformat()} – "
                    f"{overlapping.end_date.isoformat()})."
                ),
                context={"conflicting_request_id": str(overlapping.id)},
            )

        request = AnnualLeaveRequest(
            request_id=new_annual_leave_request_id(),
            tenant_id=tenant_id,
            employee_id=employee.id,
            start_date=start_date,
            end_date=end_date,
            created_at=now,
        )

        policy = self.policy(tenant_id)
        requested_days = self._deducted_days(tenant_id=tenant_id, request=request, policy=policy)
        balance = self._ensure_balance(
            tenant_id=tenant_id, employee=employee, year=start_date.year, policy=policy
        )
        if requested_days > balance.available_days:
            raise AnnualLeaveError(
                "İllik məzuniyyət balansı kifayət etmir",
                user_message=(
                    f"Balansınızda {balance.available_days} gün qalıb, "
                    f"bu sorğu {requested_days} gün tələb edir."
                ),
                context={
                    "available": str(balance.available_days),
                    "requested": str(requested_days),
                },
            )

        self._requests.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="ANNUAL_LEAVE_REQUESTED",
            entity_type="annual_leave_requests",
            entity_id=request.id,
            after_state={**request.to_audit_state(), "estimated_days": str(requested_days)},
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # `can_manage_leave_balances` sahibləri
            category=PENDING_NOTIFICATION_CATEGORY,
            title_az="Yeni illik məzuniyyət sorğusu",
            body_az=(
                f"{start_date.isoformat()} – {end_date.isoformat()} tarixləri üçün "
                f"məzuniyyət sorğusu təsdiq gözləyir ({requested_days} gün)."
            ),
            is_critical=False,
        )
        return request

    # -------------------------------- inbox ---------------------------------- #

    def pending_inbox(
        self, *, tenant_id: TenantId, actor: Employee, limit: int = 200
    ) -> list[AnnualLeaveRequest]:
        """`can_manage_leave_balances` sahibinin təsdiq növbəsi."""
        self._require_manager(actor)
        return self._requests.list_pending(tenant_id, limit=limit)

    def my_requests(self, employee: Employee, *, limit: int = 50) -> list[AnnualLeaveRequest]:
        """İşçinin öz sorğu tarixçəsi — səlahiyyət tələb olunmur."""
        return self._requests.list_for_employee(employee.id, limit=limit)

    # -------------------------------- qərar ---------------------------------- #

    def approve(
        self,
        *,
        tenant_id: TenantId,
        approver: Employee,
        request_id: AnnualLeaveRequestId,
        employee: Employee,
    ) -> AnnualLeaveRequest:
        """`[Təsdiqlə]` — çıxılan gün DONDURULUR, balans DB qatında azalır.

        `employee` arqumentdir (repo-dan oxunmur): use case `EmployeeRepository`
        ASILILIĞI GÖTÜRMÜR, çünki ona yalnız `hire_date` lazımdır və həmin
        dəyəri çağıran tərəf onsuz da əlində saxlayır (HR paneli sorğu ilə
        birlikdə işçini yükləyir). Əlavə repo asılılığı bu use case-i
        `user_management` axını ilə bağlayardı.

        ADDIM SIRASI QƏSDƏNDİR:
          1. səlahiyyət → 2. entity qaydası (özünü-təsdiq, status) →
          3. balansın ŞƏRTLİ azalması → 4. sorğunun yazılması (`EXCLUDE`) →
          5. audit → 6. bildiriş.
        Balans sorğudan ƏVVƏL azalır ki, `EXCLUDE` pozuntusunda kompensasiya
        ediləcək TƏK addım qalsın; tərsi olsaydı, balans azalmadan qalmış
        təsdiqlənmiş sorğu yaranardı — yəni işçi pulsuz gün alardı.
        """
        self._require_manager(approver)
        request = self._require_request(request_id)
        now = self._clock.now()
        policy = self.policy(tenant_id)

        # Entity QAYDALARI ƏVVƏL, LAKİN MUTASİYASIZ: özünü-təsdiq və "artıq
        # qərar alıb" halları balansa ümumiyyətlə toxunmadan kəsilməlidir.
        # `approve()` isə yalnız balans azaldıqdan SONRA çağırılır — əks halda
        # uduzan təsdiqdə yaddaşdakı aqreqat "təsdiqlənmiş", bazadakı sətir
        # isə "gözləyən" qalardı (bax `AnnualLeaveRequest.ensure_decidable`).
        request.ensure_decidable(approver_id=approver.id)
        deducted = self._deducted_days(tenant_id=tenant_id, request=request, policy=policy)

        year = self._charge_year(request)
        self._ensure_balance(tenant_id=tenant_id, employee=employee, year=year, policy=policy)
        if not self._balances.consume(employee_id=request.employee_id, year=year, days=deducted):
            # ŞƏRTLİ `UPDATE` 0 sətir toxundu: ya balans çatmır, ya da paralel
            # təsdiq bizi qabaqladı. İkisi də istifadəçi üçün eyni cavabdır.
            available = self._available_days(employee_id=request.employee_id, year=year)
            raise AnnualLeaveError(
                "Balans çatmır və ya paralel təsdiq qabaqladı",
                user_message=(
                    f"Balansda {available} gün qalıb, bu sorğu {deducted} gün tələb edir."
                ),
                context={
                    "request_id": str(request.id),
                    "requested": str(deducted),
                    "available": str(available),
                    "year": year,
                },
            )

        try:
            request.approve(approver_id=approver.id, decided_at=now, deducted_days=deducted)
            self._requests.save(request)
        except Exception:
            # KOMPENSASİYA (bax modul başlığı: "NİYƏ SAGA YOX"). Tranzaksiyalı
            # yolda rollback onsuz da işləyir; bu blok tranzaksiyasız
            # çağırışlarda balansın sükutla azalmış qalmamasını təmin edir.
            self._release_quietly(employee_id=request.employee_id, year=year, days=deducted)
            # `request.approve()` `AnnualLeaveDecidedEvent`-i ARTIQ toplayıb —
            # yazı UĞURSUZ olduğu üçün bu hadisə HEÇ VAXT baş verməmiş kimi
            # atılmalıdır (`AggregateRoot.discard_events()`, CLAUDE.md §3:
            # "Rollback halında hadisə heç vaxt yayılmır"). Bu use case-ə
            # Event Bus qoşulmasa da (`_drain()` naxışı BURADA YOXDUR —
            # bax dövrə-4 auditinin nəticəsi: o cür çağırışlar nəticəsiz
            # idi), `discard_events()` fərqlidir: o, aqreqatın ÖZ
            # invariantını qoruyur — çağıran gələcəkdə bu obyekti YENİDƏN
            # istifadə etsə (məs. eyni instansı başqa yazıya versə),
            # köhnə/etibarsız hadisə YENİ yazıyla qarışıb yayılmamalıdır.
            request.discard_events()
            raise

        # Planlanmış növbələr AUDİTDƏN ƏVVƏL oxunur ki, "təsdiq neçə iş gününü
        # boş qoydu?" rəqəmi `after_state`-də QALSIN. Bildirişin özü sonra
        # gedir — bildiriş uçur, audit sətri qalır.
        stranded = self._planned_work_days(tenant_id=tenant_id, request=request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="ANNUAL_LEAVE_APPROVED",
            entity_type="annual_leave_requests",
            entity_id=request.id,
            after_state={
                **request.to_audit_state(),
                "charged_year": year,
                "stranded_shift_days": len(stranded),
            },
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=request.employee_id,
            category=DECIDED_NOTIFICATION_CATEGORY,
            title_az="Məzuniyyət sorğunuz təsdiqləndi",
            body_az=(
                f"{request.start_date.isoformat()} – {request.end_date.isoformat()} "
                f"tarixləri üçün məzuniyyətiniz təsdiqləndi ({deducted} gün balansdan çıxıldı)."
            ),
            is_critical=False,
        )
        self._warn_planned_shifts(tenant_id=tenant_id, request=request, stranded=stranded)
        return request

    def reject(
        self,
        *,
        tenant_id: TenantId,
        approver: Employee,
        request_id: AnnualLeaveRequestId,
        reason: str,
    ) -> AnnualLeaveRequest:
        """`[Rədd Et]` — səbəb MƏCBURİDİR, balansa TOXUNULMUR."""
        self._require_manager(approver)
        request = self._require_request(request_id)

        request.reject(approver_id=approver.id, decided_at=self._clock.now(), reason=reason)
        self._requests.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="ANNUAL_LEAVE_REJECTED",
            entity_type="annual_leave_requests",
            entity_id=request.id,
            after_state=request.to_audit_state(),
            reason=request.decision_note,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=request.employee_id,
            category=DECIDED_NOTIFICATION_CATEGORY,
            title_az="Məzuniyyət sorğunuz rədd edildi",
            body_az=(
                f"{request.start_date.isoformat()} – {request.end_date.isoformat()} "
                f"tarixləri üçün sorğunuz rədd edildi. Səbəb: {request.decision_note}"
            ),
            # Kritikdir: işçi həmin günlərdə İŞƏ ÇIXMALI olduğunu MÜTLƏQ
            # bilməlidir (`ShiftSwapUseCase.reject` ilə eyni qərar).
            is_critical=True,
        )
        return request

    def cancel(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        request_id: AnnualLeaveRequestId,
        reason: str,
    ) -> AnnualLeaveRequest:
        """Təsdiqlənmiş məzuniyyətin ləğvi — BALANS GERİ QAYTARILIR.

        KİM LƏĞV EDƏ BİLƏR: sorğunun SAHİBİ (planı dəyişdi) və ya
        `can_manage_leave_balances` sahibi (əməliyyat zərurəti). Üçüncü şəxs
        edə BİLMƏZ — məzuniyyət işçinin haqqıdır.

        Geri qaytarılan gün DONDURULMUŞ `deducted_days`-dir (bax
        `AnnualLeaveRequest.cancel_approved`).
        """
        request = self._require_request(request_id)
        is_owner = actor.id == request.employee_id
        if not is_owner:
            self._require_manager(actor)

        now = self._clock.now()
        today = now.astimezone(_LOCAL_TZ).date()
        year = self._charge_year(request)
        restored = request.cancel_approved(
            cancelled_by=actor.id, cancelled_at=now, reason=reason, today=today
        )

        self._requests.save(request)
        self._balances.release(employee_id=request.employee_id, year=year, days=restored)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ANNUAL_LEAVE_CANCELLED",
            entity_type="annual_leave_requests",
            entity_id=request.id,
            after_state={
                **request.to_audit_state(),
                "restored_days": str(restored),
                "charged_year": year,
            },
            reason=request.decision_note,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=request.employee_id,
            category=DECIDED_NOTIFICATION_CATEGORY,
            title_az="Məzuniyyətiniz ləğv edildi",
            body_az=(
                f"{request.start_date.isoformat()} – {request.end_date.isoformat()} "
                f"tarixli məzuniyyətiniz ləğv edildi, {restored} gün balansa qaytarıldı."
            ),
            is_critical=True,
        )
        return request

    # --------------------------- planlaşdırılmış iş --------------------------- #

    def run_year_rollover(self, *, tenant_id: TenantId, now: datetime) -> YearRolloverReport:
        """`ANNUAL_LEAVE_YEAR_ROLLOVER` — accrual + köçürmə + "istifadə et ya itir".

        ──────────────────────────────────────────────────────────────────────
        İDEMPOTENTLİK — REYESTRİN MÜQAVİLƏSİ
        ──────────────────────────────────────────────────────────────────────
        Planlayıcı **at-least-once** icra edir (`job_runner.py` başlığı): iş
        bitib, `mark_succeeded` şəbəkə qırılmasına düşsə, icarə bitəndən sonra
        eyni iş TƏKRAR işləyəcək. Ona görə bu metodun HƏR addımı təyinedicidir:

          * haqq `set_entitlement()` ilə **TƏYİN EDİLİR**, `+=` YOXDUR —
            ikinci icra eyni ədədi yazır;
          * köçürmə keçən ilin qalığından HƏR DƏFƏ yenidən hesablanır və
            eyni giriş eyni nəticəni verir;
          * `expire_carryover()` `LEAST(carried_over, used)` yazır — ikinci
            icrada dəyər artıq bu şərti ödədiyi üçün heç nə dəyişmir.

        İL SƏRHƏDİ: iş GÜNDƏLİKDİR və `now`-un ilini işlədir. 31 dekabr
        gecəsi 2025-i, 1 yanvar gecəsi 2026-nı hesablayır — yəni yeni ilin
        balansı ilk gecə avtomatik yaranır və köçürmə orada görünür. Ayrıca
        "yalnız 1 yanvarda işlə" şərti QOYULMUR: terminal həmin gecə
        söndürülmüş ola bilər və şərt qoyulsaydı, köçürmə BÜTÜN İL üçün itərdi
        (`job_runner.py`: "GECİKMİŞ İCRA").
        """
        local_now = now.astimezone(_LOCAL_TZ)
        today = local_now.date()
        year = today.year
        policy = self.policy(tenant_id)

        rows = self._balances.list_rollover_inputs(tenant_id, year=year)
        written = 0
        skipped = 0
        carried_total = _ZERO
        forfeited_total = _ZERO

        for row in rows:
            carried = policy.carry_over(unused_days=row.previous_available_days)
            forfeited = policy.forfeited_days(unused_days=row.previous_available_days)
            entitlement = policy.entitlement_for_year(
                year=year, hire_date=row.hire_date, as_of=today
            )
            updated = self._balances.set_entitlement(
                tenant_id=tenant_id,
                employee_id=_as_employee_id(row.employee_id),
                year=year,
                entitled_days=entitlement.days,
                carried_over_days=carried,
                # `None` = SİSTEM yazısı; əl ilə düzəldilmiş sətir toxunulmur.
                updated_by=None,
            )
            if updated:
                written += 1
                carried_total += carried
                forfeited_total += forfeited
            else:
                skipped += 1

        expired = 0
        if policy.is_carryover_expired(year=year, as_of=today):
            expired = self._balances.expire_carryover(tenant_id=tenant_id, year=year)

        report = YearRolloverReport(
            year=year,
            employees_processed=len(rows),
            balances_written=written,
            manual_rows_skipped=skipped,
            carried_over_days=quantize_days(carried_total),
            forfeited_days=quantize_days(forfeited_total),
            expired_carryover_rows=expired,
        )
        self._audit.record(
            tenant_id=tenant_id,
            # Sistem işidir, aktoru yoxdur (`JobRunner._record_audit` ilə eyni).
            actor_id=None,
            action="ANNUAL_LEAVE_YEAR_ROLLOVER",
            entity_type="annual_leave_balances",
            entity_id=None,
            after_state={
                "year": year,
                "employees_processed": report.employees_processed,
                "balances_written": report.balances_written,
                "manual_rows_skipped": report.manual_rows_skipped,
                "carried_over_days": str(report.carried_over_days),
                "forfeited_days": str(report.forfeited_days),
                "expired_carryover_rows": report.expired_carryover_rows,
            },
        )
        return report

    # ------------------------------- köməkçi --------------------------------- #

    def _deducted_days(
        self, *, tenant_id: TenantId, request: AnnualLeaveRequest, policy: AnnualLeavePolicy
    ) -> Decimal:
        """Balansdan çıxılacaq gün — `ANNUAL_LEAVE_DAY_COUNT_MODE`-a görə.

        ──────────────────────────────────────────────────────────────────────
        İSTİRAHƏT/BAYRAM GÜNÜ SAYILIRMI
        ──────────────────────────────────────────────────────────────────────
        Defolt `WORKING_DAYS`: Shift Matrix-də istirahət günü kimi işarələnmiş
        gün balansdan ÇIXILMIR. Tam əsaslandırma `LeaveDayCountMode`
        docstring-indədir (ayrıca bayram təqvimi cədvəli NİYƏ yaradılmadı).

        PLANLAŞDIRILMAMIŞ GÜN İŞ GÜNÜ SAYILIR. Bu, ayrıca qərardır: Shift
        Matrix adətən bir neçə həftə irəli doldurulur, məzuniyyət sorğusu isə
        aylar sonrasına verilir. "Sətri yoxdursa istirahətdir" qaydası
        seçilsəydi, yayın ortasına verilən iki həftəlik sorğu balansdan SIFIR
        gün çıxarardı — yəni məzuniyyət faktiki olaraq pulsuz olardı.

        BİR SORĞU = BİR SQL SORĞUSU: `list_range()` bütün aralığı bir dəfə
        oxuyur. Gün-gün `is_off_day()` çağırmaq 21 günlük sorğuda 21 sorğu
        demək olardı.
        """
        if policy.day_count_mode is LeaveDayCountMode.CALENDAR_DAYS:
            return quantize_days(Decimal(request.calendar_days))

        assignments = self._shifts.list_range(
            tenant_id,
            start=request.start_date,
            end=request.end_date,
            employee_ids=[request.employee_id],
        )
        off_days = {
            assignment.shift_date
            for assignment in assignments
            if assignment.employee_id == request.employee_id and assignment.is_off_day
        }
        working = sum(
            1
            for offset in range(request.calendar_days)
            if (request.start_date + timedelta(days=offset)) not in off_days
        )
        return quantize_days(Decimal(working))

    def _planned_work_days(self, *, tenant_id: TenantId, request: AnnualLeaveRequest) -> list[date]:
        """Məzuniyyət aralığında PLANLAŞDIRILMIŞ İŞ günləri (bax modul başlığı).

        SƏTRİ OLMAYAN GÜN SAYILMIR. `shift_scheduling.clear_day` şərhi qaydanı
        yazır: planlaşdırılmamış gün istirahət günü DEYİL, lakin o, həm də
        heç kimin GÖZLƏDİYİ gün deyil — yenidən planlanmalı növbə yoxdur.
        Bura yalnız AÇIQ `is_off_day = FALSE` sətirləri düşür, yəni matrisdə
        real olaraq "bu adam bu gün işləyir" yazılmış günlər.

        Oxu uğursuzluğu TƏSDİQİ DAYANDIRMIR (bax `policy()` ilə eyni fəlsəfə):
        verilməli cavab "məzuniyyət verilsinmi" deyil, "planlayıcı xəbərdar
        edilsinmi" idi. Matris oxunmursa xəbərdarlıq itir, işçinin haqqı isə
        yerində qalır.
        """
        try:
            assignments = self._shifts.list_range(
                tenant_id,
                start=request.start_date,
                end=request.end_date,
                employee_ids=[request.employee_id],
            )
        except Exception as exc:  # pragma: no cover — repo çökməsi
            _audit_log.warning(
                "ANNUAL_LEAVE_SHIFT_SCAN_FAILED",
                extra={"request_id": str(request.id), "error": str(exc)},
            )
            return []

        return sorted(
            assignment.shift_date
            for assignment in assignments
            if assignment.employee_id == request.employee_id and not assignment.is_off_day
        )

    def _warn_planned_shifts(
        self, *, tenant_id: TenantId, request: AnnualLeaveRequest, stranded: list[date]
    ) -> None:
        """Boş qalacaq növbələr barədə PLAN SAHİBİNƏ xəbər verir.

        `recipient_id=None` — konkret alıcı yoxdur, kateqoriya auditoriyası
        (`can_manage_shifts`) süzgəcdir. `is_critical=True`: bu sətir bir
        məlumat deyil, İCRA TƏLƏB EDƏN tapşırıqdır (günü yenidən planla) və
        e-poçt ehtiyat kanalı ilə getməlidir — planlayıcı tətbiqi həmin gün
        açmaya bilər, növbə isə onsuz da boş qalacaq.
        """
        if not stranded:
            return
        days = ", ".join(day.isoformat() for day in stranded)
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # `can_manage_shifts` sahibləri
            category=SHIFT_CONFLICT_NOTIFICATION_CATEGORY,
            title_az="Təsdiqlənmiş məzuniyyət planlanmış növbələrə düşür",
            body_az=(
                f"{request.start_date.isoformat()} – {request.end_date.isoformat()} "
                "tarixləri üçün illik məzuniyyət təsdiqləndi, lakin Növbə Matrisində "
                f"həmin işçi üçün iş günü kimi planlanmış tarixlər var: {days}. "
                "Növbə cədvəli avtomatik dəyişmir — həmin günləri yenidən planlayın."
            ),
            is_critical=True,
        )

    def _charge_year(self, request: AnnualLeaveRequest) -> int:
        """Sorğu HANSI ilin balansından çıxılır.

        QƏRAR: BAŞLANĞIC tarixinin ili — sorğu il sərhədini kəssə belə
        (28 dekabr – 3 yanvar) BÜTÜNLÜKLƏ həmin ilə yazılır.

        NİYƏ BÖLÜNMÜR: `annual_leave_requests.deducted_days` TƏK sütundur və
        illər arası bölgü orada DONDURULA bilməzdi. Ləğv zamanı isə balansa
        DƏQİQ çıxılan ədəd qaytarılmalıdır — bölgü yenidən hesablansaydı və
        Shift Matrix bu arada dəyişsəydi, iki ilin balansı arasında sükutla
        gün itər və ya artardı. Tək ilə yazmaq ən pis halda ilin son
        günlərində bir neçə günün "keçən ilin haqqından" çıxması deməkdir —
        bu, HR praktikasında normal və izah edilə biləndir.
        """
        return request.start_date.year

    def _ensure_balance(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        year: int,
        policy: AnnualLeavePolicy,
    ) -> AnnualLeaveBalance:
        """Balans sətri yoxdursa YARADIR (accrual ilk toxunuşda baş verir).

        İl dönümü işi onsuz da gecə bunu edir; bu metod isə "işə yeni düşən
        işçi ilk gün sorğu verir" halını bağlayır — planlayıcının növbəti
        icrasını gözləmək işçini bir gecə balanssız qoyardı.

        `set_entitlement()` İDEMPOTENTDİR, yəni bu çağırış planlayıcının
        yazdığı sətri təkrarən yazsa da nəticə dəyişmir; əl ilə düzəldilmiş
        sətrə isə ümumiyyətlə toxunmur.
        """
        existing = self._balances.get(employee.id, year=year)
        if existing is not None:
            return existing

        entitlement = policy.entitlement_for_year(
            year=year,
            hire_date=employee.hire_date,
            as_of=self._clock.now().astimezone(_LOCAL_TZ).date(),
        )
        # Köçürmə BURADA hesablanmır: keçən ilin qalığı il dönümü işinin
        # məlumatıdır (`list_rollover_inputs`) və onu hər sorğuda yenidən
        # oxumaq balansı iki fərqli yerdə hesablamaq olardı.
        self._balances.set_entitlement(
            tenant_id=tenant_id,
            employee_id=employee.id,
            year=year,
            entitled_days=entitlement.days,
            carried_over_days=_ZERO,
            updated_by=None,
        )
        created = self._balances.get(employee.id, year=year)
        if created is not None:
            return created
        # Sahtə/oxunmayan repo halı: hesablanmış dəyərlə yaddaş obyektini
        # qaytarırıq ki, çağıran tərəf `None` yoxlaması etməli olmasın.
        return AnnualLeaveBalance(
            balance_id=new_annual_leave_balance_id(),
            tenant_id=tenant_id,
            employee_id=employee.id,
            year=year,
            entitled_days=entitlement.days,
        )

    def _view(
        self, *, tenant_id: TenantId, employee: Employee, year: int | None = None
    ) -> AnnualLeaveBalanceView:
        policy = self.policy(tenant_id)
        today = self._today()
        target_year = year or today.year
        balance = self._ensure_balance(
            tenant_id=tenant_id, employee=employee, year=target_year, policy=policy
        )
        return AnnualLeaveBalanceView(
            year=target_year,
            entitled_days=balance.entitled_days,
            carried_over_days=balance.carried_over_days,
            used_days=balance.used_days,
            available_days=balance.available_days,
            total_days=balance.total_days,
            carryover_deadline=policy.carryover_deadline(target_year),
            carryover_expired=policy.is_carryover_expired(year=target_year, as_of=today),
        )

    def _available_days(self, *, employee_id: EmployeeId, year: int) -> Decimal:
        balance = self._balances.get(employee_id, year=year)
        return _ZERO if balance is None else balance.available_days

    def _release_quietly(self, *, employee_id: EmployeeId, year: int, days: Decimal) -> None:
        """Kompensasiya — ÖZ istisnasını UDUR.

        Burada atılan ikinci istisna ORİJİNAL səbəbi (məs. `EXCLUDE`
        pozuntusu) gizlədərdi və istifadəçi əsl problemi heç vaxt görməzdi.
        Uğursuz kompensasiya isə loga düşür və tranzaksiyalı yolda rollback
        onsuz da işləyir.
        """
        try:
            self._balances.release(employee_id=employee_id, year=year, days=days)
        except Exception as exc:  # pragma: no cover — repo çökməsi
            _audit_log.error(
                "ANNUAL_LEAVE_COMPENSATION_FAILED",
                extra={"employee_id": str(employee_id), "year": year, "error": str(exc)},
            )

    def _today(self) -> date:
        """Yerli təqvim günü — `datetime.now()` HEÇ YERDƏ çağırılmır."""
        return self._clock.now().astimezone(_LOCAL_TZ).date()

    def _require_request(self, request_id: AnnualLeaveRequestId) -> AnnualLeaveRequest:
        request = self._requests.get_for_update(request_id)
        if request is None:
            raise AnnualLeaveRequestNotFoundError(
                "İllik məzuniyyət sorğusu tapılmadı",
                context={"request_id": str(request_id)},
            )
        return request

    def _require_manager(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_LEAVE_BALANCES_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "ANNUAL_LEAVE_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_LEAVE_BALANCES_FLAG},
            )
            raise AnnualLeavePermissionError(
                f"«{MANAGE_LEAVE_BALANCES_FLAG}» səlahiyyəti yoxdur",
                user_message="Məzuniyyət sorğusuna qərar vermək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )


def _balance_state(balance: AnnualLeaveBalance) -> dict[str, object]:
    return {
        "year": balance.year,
        "entitled_days": str(balance.entitled_days),
        "carried_over_days": str(balance.carried_over_days),
        "used_days": str(balance.used_days),
    }


def _as_employee_id(value: object) -> EmployeeId:
    """`AnnualLeaveRolloverInput.employee_id` → `EmployeeId`.

    Value object `object` saxlayır, çünki saf domen modulu (`annual_leave_
    rules.py`) identifikator tiplərini idxal etsəydi, qayda faylı ilə
    identifikator modulu arasında lazımsız asılılıq yaranardı. Çevrilmə
    `NewType` üçün icra zamanı NO-OP-dur — yalnız mypy üçün mövcuddur.
    """
    from src.domain.value_objects.identifiers import EmployeeId as _EmployeeId  # noqa: PLC0415

    return _EmployeeId(value)  # type: ignore[arg-type]


__all__ = [
    "DECIDED_NOTIFICATION_CATEGORY",
    "MANAGE_LEAVE_BALANCES_FLAG",
    "PENDING_NOTIFICATION_CATEGORY",
    "SHIFT_CONFLICT_NOTIFICATION_CATEGORY",
    "AnnualLeaveBalanceView",
    "AnnualLeaveError",
    "AnnualLeavePermissionError",
    "AnnualLeaveRequestNotFoundError",
    "AnnualLeaveStatus",
    "AnnualLeaveUseCase",
    "YearRolloverReport",
]
