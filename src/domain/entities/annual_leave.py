"""İllik məzuniyyət aqreqatları (#28, kompas1.md Faza 4).

──────────────────────────────────────────────────────────────────────────────
ÜÇ AYRI KONSEPT — BU FAYL ÜÇÜNCÜSÜDÜR
──────────────────────────────────────────────────────────────────────────────
KompasOS-da "işə gəlməmək" ÜÇ müxtəlif mexanizmlə ifadə olunur. Onlar
oxşar səslənir, lakin nə vahidləri, nə qaydaları, nə də nəticələri eynidir:

┌───────────────────────────┬──────────────┬───────────────────────────────────┐
│ Mexanizm                  │ Vahid        │ Harada                            │
├───────────────────────────┼──────────────┼───────────────────────────────────┤
│ STEP1/STEP2 gündaxili     │ DƏQİQƏ       │ `leave_verification.py`,          │
│ icazə (iş günü ərzində)   │ (+ cərimə)   │ `morning_check_in.py`,            │
│                           │              │ `entities/leave_request.py`       │
│ Shift Matrix off-day      │ PLAN         │ `shift_scheduling.py`,            │
│ (növbədə istirahət günü)  │ (haqq deyil) │ `entities/shift.py`               │
│ **İllik məzuniyyət (BU)** │ **GÜN**      │ bu fayl + `annual_leave_rules.py` │
└───────────────────────────┴──────────────┴───────────────────────────────────┘

BU FAYL BİRİNCİ İKİSİNİN MƏNTİQİNƏ TOXUNMUR. Konkret olaraq:
  * `MonthlyLeaveUsage` (aylıq 240 dəqiqə) BURAYA AİD DEYİL — o, gündaxili
    icazənin tavanıdır və illik məzuniyyət ondan heç nə çıxmır.
  * `LeaveTypeCatalog` (İcazə Növləri) gündaxili icazə növləridir; illik
    məzuniyyətin "növü" yoxdur, `annual_leave_requests` cədvəlində belə sütun
    da yoxdur (migrations/037).
  * Shift Matrix YALNIZ OXUNUR: təsdiqlənmiş məzuniyyət növbə cədvəlini
    dəyişmir — dəyişsəydi, iki fərqli mənbə eyni günə "kim qərar verdi?"
    sualının iki cavabını yazardı.

BİRLƏŞDİRMƏ CƏHDİ NİYƏ YANLIŞDIR: vahid model qurulsaydı, 60 dəqiqəlik nahar
fasiləsi illik məzuniyyət balansından gün çıxarardı və ya iki həftəlik
məzuniyyət aylıq 240 dəqiqəlik limiti ilk günündə doldurardı.

──────────────────────────────────────────────────────────────────────────────
TƏSDİQ AXINI — MÖVCUD SHIFT SWAP NAXIŞI
──────────────────────────────────────────────────────────────────────────────
`PENDING_APPROVAL → APPROVED / REJECTED` maşını YENİDƏN İCAD EDİLMİR:
`entities/shift.py::ShiftSwapRequest` naxışı hərfən təkrarlanır — terminal
qərar, məcburi rədd səbəbi, `_require_pending()` mühafizəsi və özünü-təsdiq
qadağası. Səbəb sadədir: iki ayrı təsdiq maşını olsaydı, biri özünü-təsdiqi
bağlayar, digəri bağlamazdı və hansının hansı olduğu yalnız audit zamanı üzə
çıxardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `CANCELLED` STATUSU YOXDUR
──────────────────────────────────────────────────────────────────────────────
`migrations/037` `status`-u ÜÇ dəyərlə bağlayır (`CHECK (status IN
('PENDING_APPROVAL', 'APPROVED', 'REJECTED'))`) və `EXCLUDE` qapağı
`WHERE (status = 'APPROVED')` predikatı ilə işləyir. Dördüncü dəyər əlavə
etmək həm `CHECK`-i, həm də mövcud sətirləri toxunmaq demək olardı.

Ona görə TƏSDİQLƏNMİŞ məzuniyyətin ləğvi `APPROVED → REJECTED` keçididir
(`cancel_approved()`), qərar qeydi isə `LƏĞV_PREFIX` ilə başlayır. Bu, məlumat
itkisi DEYİL: (a) audit sətri ayrıca hərəkət adı daşıyır
(`ANNUAL_LEAVE_CANCELLED`), (b) `AnnualLeaveCancelledEvent` ayrıca hadisədir,
(c) `is_cancelled` xassəsi qeydin özündən oxunur. Praktik faydası isə odur ki,
statusun `APPROVED` olmaqdan çıxması `EXCLUDE` qapağını DƏRHAL boşaldır və
işçi həmin tarixlərə yeni sorğu verə bilir.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Final

from src.domain.annual_leave_rules import quantize_days
from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import (
    AnnualLeaveCancelledEvent,
    AnnualLeaveDecidedEvent,
    AnnualLeaveEarlyReturnEvent,
    AnnualLeaveRequestedEvent,
)
from src.domain.value_objects.identifiers import (
    AnnualLeaveBalanceId,
    AnnualLeaveRequestId,
    EmployeeId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: Rədd/ləğv qərarının izahı — `ShiftSwapRequest.MIN_DECISION_REASON_LENGTH`
#: ilə EYNİ dəyər və eyni səbəb: "yox" cavabı işçiyə izah edilməlidir.
MIN_DECISION_REASON_LENGTH: Final[int] = 10

#: Ləğv qeydinin prefiksi — bax modul başlığı ("NİYƏ `CANCELLED` YOXDUR").
CANCELLATION_PREFIX: Final[str] = "LƏĞV EDİLDİ:"

#: Erkən qayıdış qeydinin prefiksi — `CANCELLATION_PREFIX`-dən AYRIDIR.
#:
#: Eyni prefiksi işlətsəydik `is_cancelled` erkən qayıdışı da "ləğv edilmiş"
#: sayardı, halbuki sətir `APPROVED` qalır və xərclənmiş günlər balansdan
#: çıxılmış vəziyyətdədir — ekranda "məzuniyyətiniz ləğv edildi" yazılması
#: işçini yanıldardı (`return_early()` şərhinə bax).
EARLY_RETURN_PREFIX: Final[str] = "ERKƏN QAYIDIŞ:"

#: Xəstəlik icazəsi qeydinin prefiksi (HR-5).
#:
#: ──────────────────────────────────────────────────────────────────────────
#: NİYƏ PREFİKS, NİYƏ YENİ SÜTUN / YENİ MODUL DEYİL
#: ──────────────────────────────────────────────────────────────────────────
#: Xəstəlik icazəsi ÜÇÜNCÜ bir mexanizm TƏLƏB ETMİR — o, GÜN əsaslıdır (yəni
#: gündaxili icazə deyil) və balansdan gün ÇIXARMIR (yəni adi illik məzuniyyət
#: deyil). Hər iki xüsusiyyət bu aqreqatda ARTIQ mövcuddur:
#:   * `approve(deducted_days=0)` — sıfır çıxım AÇIQ şəkildə icazəlidir
#:     (bax həmin metodun «SIFIR İCAZƏLİDİR» şərhi);
#:   * tabel `find_overlapping_approved` sayəsində günü `ANNUAL_LEAVE` yazır,
#:     yəni işçi «🔴 İcazəsiz qayıb» kimi görünmür (DEEP-GAP D1).
#: Çatışmayan yeganə şey qeydin ÖZÜNÜN «bu, xəstəlikdir» deməsi idi.
#:
#: Sütun əlavə etmək RƏDD EDİLDİ, çünki `CANCELLATION_PREFIX` üçün verilmiş
#: qərarın EYNİSİ burada da keçərlidir (bax modul başlığı «NİYƏ `CANCELLED`
#: STATUSU YOXDUR»): `annual_leave_requests`-də növ sütunu QƏSDƏN yoxdur və
#: sub-vəziyyət qərar qeydində saxlanılır. Üçüncü prefiks həmin naxışın
#: təkrarıdır, yeni naxış deyil.
SICK_LEAVE_PREFIX: Final[str] = "XƏSTƏLİK İCAZƏSİ:"

#: Xəstəlik vərəqəsinin istinadı üçün minimum uzunluq (HR-5).
#:
#: Sənəd TƏLƏB OLUNUR və bu, formal deyil: balansdan gün çıxmayan, lakin
#: davamiyyətdə «qayıb» sayılmayan gün YALNIZ sənədlə əsaslandırıla bilər —
#: əks halda «xəstəlik icazəsi» limitsiz və izsiz bir istisnaya çevrilərdi.
#: Ədəd digər qərar izahları ilə eynidir (`MIN_DECISION_REASON_LENGTH`),
#: LAKİN ondan İDXAL EDİLMİR: bu, izah deyil, SƏNƏD İSTİNADIDIR («B-2024/117»
#: kimi) və gələcəkdə formatı ayrıca dəyişə bilər.
MIN_SICK_DOCUMENT_REFERENCE_LENGTH: Final[int] = 5

#: `annual_leave_balances.year` — sxemdəki `CHECK (year BETWEEN 2000 AND 2100)`
#: burada təkrarlanır (defense-in-depth): ekranı yan keçən skript də ona tabedir.
MIN_BALANCE_YEAR: Final[int] = 2000
MAX_BALANCE_YEAR: Final[int] = 2100

_ZERO: Final[Decimal] = Decimal("0")


class AnnualLeaveStatus(str, Enum):
    """`annual_leave_requests.status` — DB `CHECK` siyahısı ilə EYNİ.

    `SwapStatus` ilə eyni formadadır, lakin AYRI enum-dur: birləşdirilsəydi,
    növbə dəyişmə sorğusu ilə illik məzuniyyət sorğusu eyni tip kimi
    ötürülə bilərdi və mypy səhvi tuta bilməzdi.
    """

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    @property
    def is_decided(self) -> bool:
        return self is not AnnualLeaveStatus.PENDING_APPROVAL


class AnnualLeaveRequest(AggregateRoot):
    """İşçinin illik məzuniyyət sorğusu (`annual_leave_requests` sətri).

        PENDING_APPROVAL ──approve()──> APPROVED ──cancel_approved()──┐
                 │                          │                         │
                 │                          └──return_early()──> APPROVED
                 │                             (end_date qısalır)
                 └────reject(səbəb)──> REJECTED <─────────────────────┘

    `approve()` və `reject()` `ShiftSwapRequest` ilə eyni qaydalara tabedir:
    qərar TERMİNALDIR, rədd səbəbi MƏCBURİDİR, işçi ÖZ sorğusuna qərar verə
    BİLMƏZ. `cancel_approved()` isə əlavə keçiddir (bax modul başlığı) və
    yalnız məzuniyyət HƏLƏ BAŞLAMAMIŞSA mümkündür.

    `return_early()` DÖRDÜNCÜ keçiddir və statusu DƏYİŞMİR: məzuniyyət
    başlayıb, bir hissəsi xərclənib, qalanı balansa qayıdır. `cancel_
    approved()` ilə qarışdırılmamalıdır — ikisinin qapıları bir-birini
    tamamlayır (`start_date > today` ↔ `start_date <= return_date <=
    end_date`) və birlikdə ƏBƏDİ KİLİD qalmır.
    """

    def __init__(
        self,
        *,
        request_id: AnnualLeaveRequestId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        start_date: date,
        end_date: date,
        created_at: datetime,
        status: AnnualLeaveStatus = AnnualLeaveStatus.PENDING_APPROVAL,
        deducted_days: Decimal | None = None,
        approved_by: EmployeeId | None = None,
        decided_at: datetime | None = None,
        decision_note: str | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        if end_date < start_date:
            # DB `chk_annual_leave_request_range` burada təkrarlanır: səhv
            # aralıq ekranda DƏRHAL aydın mesaj almalıdır, sürücü xətası yox.
            raise DomainRuleError(
                "Məzuniyyətin son tarixi başlanğıcdan əvvəl ola bilməz",
                user_message="Bitmə tarixi başlanğıc tarixindən əvvəl ola bilməz.",
                context={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )

        self.id = request_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.start_date = start_date
        self.end_date = end_date
        self.status = status
        self.deducted_days = None if deducted_days is None else quantize_days(deducted_days)
        self.approved_by = approved_by
        self.decided_at = (
            None if decided_at is None else require_aware(decided_at, field="decided_at")
        )
        self.decision_note = decision_note
        self.created_at = require_aware(created_at, field="created_at")

        # Repository-dən BƏRPA edilən obyekt hadisə YAYMAMALIDIR — əks halda
        # HR panelinin hər açılışı bütün gözləyən sorğular üçün yenidən
        # "yeni sorğu" bildirişi göndərərdi.
        if emit_created_event and status is AnnualLeaveStatus.PENDING_APPROVAL:
            self.record_event(
                AnnualLeaveRequestedEvent(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    employee_id=employee_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )

    # ------------------------------- xassələr -------------------------------- #

    @property
    def calendar_days(self) -> int:
        """Aralıqdakı TƏQVİM günü sayı (hər iki uc DAXİLDİR).

        Bu, balansdan çıxılan gün DEYİL — `deducted_days` Shift Matrix-ə görə
        hesablanır (bax `LeaveDayCountMode`). Sahə yalnız ekranda "12 günlük
        məzuniyyət" cümləsini qurmaq üçündür.
        """
        return (self.end_date - self.start_date).days + 1

    @property
    def is_cancelled(self) -> bool:
        """Rədd qeydi LƏĞV keçidindən gəlirmi (bax modul başlığı)."""
        return bool(self.decision_note and self.decision_note.startswith(CANCELLATION_PREFIX))

    @property
    def is_sick_leave(self) -> bool:
        """Qeyd XƏSTƏLİK icazəsidirmi (HR-5).

        `is_cancelled`/`is_early_return` ilə eyni formadadır və üçü də
        BİR-BİRİNİ İSTİSNA EDİR — hər keçid `decision_note`-a yalnız BİR
        prefiks yazır.
        """
        return bool(self.decision_note and self.decision_note.startswith(SICK_LEAVE_PREFIX))

    @property
    def is_early_return(self) -> bool:
        """Məzuniyyət ERKƏN QAYIDIŞLA kəsilibmi (`return_early()`).

        `is_cancelled` ilə birlikdə HEÇ VAXT `True` olmur — prefikslər
        ayrıdır və hər keçid yalnız birini yazır.
        """
        return bool(self.decision_note and self.decision_note.startswith(EARLY_RETURN_PREFIX))

    def covers(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date

    # -------------------------------- qərar ---------------------------------- #

    def approve(
        self, *, approver_id: EmployeeId, decided_at: datetime, deducted_days: Decimal
    ) -> None:
        """`[Təsdiqlə]` — çıxılan gün TƏSDİQ ANINDA dondurulur.

        `deducted_days` arqumentdir, hesablanmır: hesablama Shift Matrix
        sorğusu tələb edir və domen qatı I/O tanımır (CLAUDE.md §3). Dəyərin
        DONDURULMASI isə `migrations/037`-nin tələbidir — matris sonradan
        dəyişsə, keçmiş sorğunun rəqəmi dəyişməməlidir.

        SIFIR İCAZƏLİDİR: tam olaraq istirahət günlərinə düşən sorğu
        balansdan heç nə çıxarmır və bu, qanuni haldır (DB `CHECK` də
        `>= 0` yazır, `> 0` yox).
        """
        if deducted_days < 0:
            raise DomainRuleError(
                "Çıxılan gün mənfi ola bilməz — balans artardı",
                user_message="Məzuniyyət günü mənfi hesablana bilməz.",
                context={"deducted_days": str(deducted_days)},
            )
        self._decide(approved=True, approver_id=approver_id, decided_at=decided_at, note=None)
        self.deducted_days = quantize_days(deducted_days)

    def approve_as_sick_leave(
        self, *, approver_id: EmployeeId, decided_at: datetime, document_reference: str
    ) -> None:
        """`[Xəstəlik İcazəsi Kimi Təsdiqlə]` — BALANSDAN GÜN ÇIXMIR (HR-5).

        ──────────────────────────────────────────────────────────────────────
        `approve()`-DAN YEGANƏ FƏRQ: ÇIXILAN GÜN SIFIRDIR
        ──────────────────────────────────────────────────────────────────────
        Qalan hər şey eynidir — eyni `_decide()` qapısı, eyni özünü-təsdiq
        qadağası, eyni terminal qərar, eyni `AnnualLeaveDecidedEvent`. Ona
        görə də bu, YENİ İŞ AXINI deyil: mövcud təsdiqin sıfır-çıxımlı halıdır
        və həmin hal `approve()`-un öz şərhində ARTIQ icazəlidir.

        BALANS TOXUNULMUR VƏ TOXUNULMAMALIDIR: xəstəlik günü işçinin illik
        istirahət haqqından oğurlanmır. Eyni zamanda gün davamiyyətdə
        «icazəsiz qayıb» da olmur — tabel təsdiqlənmiş aralığı `ANNUAL_LEAVE`
        kimi görür (DEEP-GAP D1).

        SƏNƏD MƏCBURİDİR (`document_reference`): bax
        `MIN_SICK_DOCUMENT_REFERENCE_LENGTH` şərhi.

        Args:
            document_reference: Xəstəlik vərəqəsinin nömrəsi/istinadı. Sənədin
                ÖZÜ burada saxlanmır — fayl `employee_documents` axınının
                işidir; bu sətir yalnız «hansı sənədə əsasən?» sualına cavab
                verir və qərarla BİRLİKDƏ, ayrılmaz şəkildə qalır.
        """
        cleaned = normalise_decision_text(document_reference)
        if len(cleaned) < MIN_SICK_DOCUMENT_REFERENCE_LENGTH:
            raise DomainRuleError(
                f"Xəstəlik vərəqəsinin istinadı minimum "
                f"{MIN_SICK_DOCUMENT_REFERENCE_LENGTH} simvol olmalıdır",
                user_message="Xəstəlik vərəqəsinin nömrəsini yazın.",
                context={"length": len(cleaned)},
            )
        self._decide(
            approved=True,
            approver_id=approver_id,
            decided_at=decided_at,
            note=f"{SICK_LEAVE_PREFIX} {cleaned}",
        )
        # `_decide()`-dən SONRA yazılır: o, `deducted_days`-ə toxunmur
        # (`approve()` da elə edir) və sıfır AÇIQ şəkildə qeyd olunmalıdır —
        # `None` qalsaydı `cancel_approved()`/`return_early()` onu «hesablanmayıb»
        # kimi oxuyardı və qaytarılacaq gün sualı qeyri-müəyyən olardı.
        self.deducted_days = _ZERO

    def reject(self, *, approver_id: EmployeeId, decided_at: datetime, reason: str) -> None:
        """`[Rədd Et]` — səbəb MƏCBURİDİR (işçiyə bildirişdə göstərilir)."""
        self._decide(
            approved=False,
            approver_id=approver_id,
            decided_at=decided_at,
            note=_require_reason(reason),
        )

    def ensure_decidable(self, *, approver_id: EmployeeId) -> None:
        """Qərar verilə bilərmi — HEÇ NƏ DƏYİŞDİRMİR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA, İCTİMAİ METOD
        ──────────────────────────────────────────────────────────────────────
        Təsdiq axını balansı sorğunun statusundan ƏVVƏL azaldır (bax
        `AnnualLeaveUseCase.approve` addım sırası). Yoxlamalar yalnız
        `approve()`-un içində olsaydı, çağıran tərəf ya balansa toxunmadan
        özünü-təsdiqi kəsə bilməzdi, ya da aqreqatı MUTASİYA edib sonra
        balansda uduzardı — yəni yaddaşdakı obyekt "təsdiqlənmiş", bazadakı
        sətir isə "gözləyən" qalardı.

        `_decide()` bu metodu YENƏ DƏ çağırır: yoxlama iki yerə
        BÖLÜNMÜR, sadəcə əvvəlcədən soruşula bilir.
        """
        self._require_pending("Bu sorğu artıq qərar alıb")
        if approver_id == self.employee_id:
            # VƏZİFƏ AYRILIĞI: `ShiftSwapRequest._decide` ilə eyni qayda.
            # Entity-də olmasının səbəbi budur ki, ekranı yan keçən skript
            # də ona tabe olsun — səlahiyyət flag-i tək başına kifayət etməz,
            # çünki HR işçisinin ÖZÜNDƏ də `can_manage_leave_balances` var.
            raise DomainRuleError(
                "İşçi öz məzuniyyət sorğusunu özü təsdiqləyə/rədd edə bilməz",
                user_message="Öz sorğunuza qərar verə bilməzsiniz.",
                context={"employee_id": str(self.employee_id)},
            )

    def _decide(
        self,
        *,
        approved: bool,
        approver_id: EmployeeId,
        decided_at: datetime,
        note: str | None,
    ) -> None:
        self.ensure_decidable(approver_id=approver_id)
        self.status = AnnualLeaveStatus.APPROVED if approved else AnnualLeaveStatus.REJECTED
        self.approved_by = approver_id
        self.decided_at = require_aware(decided_at, field="decided_at")
        self.decision_note = note
        self.record_event(
            AnnualLeaveDecidedEvent(
                tenant_id=self.tenant_id,
                request_id=self.id,
                approver_id=approver_id,
                approved=approved,
                reason=note,
                deducted_days=None if self.deducted_days is None else str(self.deducted_days),
            )
        )

    # -------------------------------- ləğv ----------------------------------- #

    def cancel_approved(
        self, *, cancelled_by: EmployeeId, cancelled_at: datetime, reason: str, today: date
    ) -> Decimal:
        """Təsdiqlənmiş məzuniyyəti ləğv edir və GERİ QAYTARILACAQ günü verir.

        Qaytarılan dəyər DONDURULMUŞ `deducted_days`-dir, yenidən hesablanmış
        rəqəm YOX: təsdiqdən sonra Shift Matrix dəyişmiş ola bilər və yenidən
        hesablama balansa çıxılandan FƏRQLİ gün qaytarardı — yəni ləğv balansı
        ya artırar, ya azaldardı.

        BAŞLAMIŞ MƏZUNİYYƏT LƏĞV EDİLMİR: `start_date` bugünə və ya keçmişə
        düşürsə günlərin bir hissəsi FAKTİKİ istifadə olunub və onları tam
        geri qaytarmaq işçiyə pulsuz gün bağışlamaq olardı. Qismən qaytarma
        qəsdən qurulmadı — o, "neçə gün istifadə olundu?" sualını gündaxili
        davamiyyət qeydlərindən çıxarmağı tələb edərdi və iki mexanizmi
        bir-birinə bağlayardı (bax modul başlığı).
        """
        if self.status is not AnnualLeaveStatus.APPROVED:
            raise DomainRuleError(
                "Yalnız TƏSDİQLƏNMİŞ məzuniyyət ləğv edilə bilər",
                user_message="Yalnız təsdiqlənmiş məzuniyyəti ləğv etmək olar.",
                context={"status": self.status.value},
            )
        if self.start_date <= today:
            raise DomainRuleError(
                "Başlamış məzuniyyət ləğv edilə bilməz",
                user_message="Başlamış məzuniyyəti ləğv etmək mümkün deyil.",
                context={"start_date": self.start_date.isoformat(), "today": today.isoformat()},
            )

        restored = self.deducted_days if self.deducted_days is not None else _ZERO
        self.status = AnnualLeaveStatus.REJECTED
        self.approved_by = cancelled_by
        self.decided_at = require_aware(cancelled_at, field="cancelled_at")
        self.decision_note = f"{CANCELLATION_PREFIX} {_require_reason(reason)}"
        self.record_event(
            AnnualLeaveCancelledEvent(
                tenant_id=self.tenant_id,
                request_id=self.id,
                employee_id=self.employee_id,
                cancelled_by=cancelled_by,
                restored_days=str(restored),
            )
        )
        return restored

    def return_early(
        self,
        *,
        cancelled_by: EmployeeId,
        cancelled_at: datetime,
        reason: str,
        return_date: date,
        consumed_days: Decimal,
    ) -> Decimal:
        """ERKƏN QAYIDIŞ — işçi məzuniyyəti YARIMÇIQ kəsir, QALAN gün qayıdır.

        ──────────────────────────────────────────────────────────────────────
        BU, `cancel_approved()` DEYİL — İKİ AYRI KEÇİD
        ──────────────────────────────────────────────────────────────────────
        `cancel_approved()` HƏLƏ BAŞLAMAMIŞ məzuniyyəti tamamilə ləğv edir və
        dondurulmuş `deducted_days`-in HAMISINI qaytarır. Onun `start_date <=
        today` qapısı DOĞRUDUR və olduğu kimi qalır: başlamış məzuniyyətin
        günlərinin bir hissəsi FAKTİKİ istifadə olunub və hamısını qaytarmaq
        işçiyə pulsuz gün bağışlamaq olardı.

        Lakin həmin qapı arxasında ÇIXIŞ QALMAMIŞDI: iki həftəlik məzuniyyətin
        üçüncü günü işə qayıdan işçinin qalan 9 günü nə balansa dönürdü, nə də
        başqa yolla bərpa oluna bilirdi — sətir `APPROVED` qalır, `EXCLUDE`
        qapağı həmin tarixləri tutur və yeganə çıxış bazaya əl ilə müdaxilə
        olurdu (auditsiz). Bu metod məhz həmin çıxışı açır.

        ──────────────────────────────────────────────────────────────────────
        `consumed_days` NİYƏ ARQUMENTDİR, BURADA HESABLANMIR
        ──────────────────────────────────────────────────────────────────────
        `approve(deducted_days=...)` ilə EYNİ səbəb və eyni naxış: neçə günün
        faktiki xərcləndiyi `ANNUAL_LEAVE_DAY_COUNT_MODE`-a və Shift Matrix-ə
        baxmaqla tapılır, domen qatı isə I/O tanımır (CLAUDE.md §3). Rəqəmi
        use case `_deducted_days()` ilə — TƏSDİQ ANINDAKI EYNİ DÜSTURLA,
        yalnız qısaldılmış aralıq üçün — hesablayır. Yeni qayda İCAD
        EDİLMİR: mövcud qayda daha qısa aralığa tətbiq olunur.

        `end_date` QISALDILIR (`return_date`-dən əvvəlki gün): əks halda qeyd
        işçinin hələ də məzuniyyətdə olduğunu iddia edərdi — tabel onu
        `ANNUAL_LEAVE` yazar (`AttendanceFact.on_annual_leave`), halbuki o,
        işdədir və həmin günlər balansdan çıxılmayıb.

        Args:
            return_date: işə QAYIDIŞ günü (bu gün artıq məzuniyyət DEYİL).
            consumed_days: qayıdışa qədər faktiki xərclənmiş gün.

        Returns:
            Balansa GERİ QAYTARILACAQ gün (`deducted_days - consumed_days`).
        """
        if self.status is not AnnualLeaveStatus.APPROVED:
            raise DomainRuleError(
                "Yalnız TƏSDİQLƏNMİŞ məzuniyyətdən erkən qayıdış mümkündür",
                user_message="Yalnız təsdiqlənmiş məzuniyyətdən erkən qayıtmaq olar.",
                context={"status": self.status.value},
            )
        if return_date < self.start_date:
            # Məzuniyyət HƏLƏ BAŞLAMAYIB — bu, tam ləğvdir və onun ÖZ keçidi
            # var. İki yolu birləşdirmək `cancel_approved()`-un "başlamış
            # məzuniyyət ləğv edilmir" qapısını sükutla yan keçmək olardı.
            raise DomainRuleError(
                "Məzuniyyət hələ başlamayıb — tam ləğv `cancel_approved()` ilə edilir",
                user_message="Bu məzuniyyət hələ başlamayıb, onu tam ləğv edin.",
                context={
                    "start_date": self.start_date.isoformat(),
                    "return_date": return_date.isoformat(),
                },
            )
        if return_date > self.end_date:
            raise DomainRuleError(
                "Məzuniyyət artıq bitib — qaytarılacaq gün qalmayıb",
                user_message="Bu məzuniyyət artıq başa çatıb.",
                context={
                    "end_date": self.end_date.isoformat(),
                    "return_date": return_date.isoformat(),
                },
            )

        frozen = self.deducted_days if self.deducted_days is not None else _ZERO
        consumed = quantize_days(consumed_days)
        if consumed < _ZERO:
            raise DomainRuleError(
                "Xərclənmiş gün mənfi ola bilməz",
                user_message="Məzuniyyət günü mənfi hesablana bilməz.",
                context={"consumed_days": str(consumed)},
            )
        if consumed > frozen:
            # Shift Matrix qısaldılmış aralıq üçün DAHA ÇOX iş günü verirsə,
            # hesablama ilə dondurulmuş dəyər arasında ziddiyyət var. Sükutla
            # sıfıra sıxmaq balansı gizlicə yeyərdi — istifadəçi düyməni basıb
            # və nəticə gözləyir (CLAUDE.md §6).
            raise DomainRuleError(
                "Xərclənmiş gün təsdiq anında dondurulmuş gündən çox ola bilməz",
                user_message="Məzuniyyət günləri hesablanarkən uyğunsuzluq yarandı.",
                context={"consumed_days": str(consumed), "deducted_days": str(frozen)},
            )

        restored = quantize_days(frozen - consumed)
        # `start_date` HEÇ VAXT KEÇİLMİR: elə birinci gün qayıdan işçidə qeyd
        # bir günlük qalır və çıxılan gün sıfırlanır. Sətir SİLİNMİR — hansı
        # tarixə məzuniyyət verildiyi və nə vaxt kəsildiyi auditdə qalmalıdır.
        self.end_date = max(self.start_date, date.fromordinal(return_date.toordinal() - 1))
        self.deducted_days = consumed
        # STATUS `APPROVED` QALIR — bu, ləğv DEYİL: xərclənmiş günlər həqiqətən
        # istifadə olunub və `REJECTED` yazsaydıq həmin günlər "verilməmiş"
        # görünərdi. Qərar izi `decision_note`-da və audit sətrindədir.
        self.approved_by = cancelled_by
        self.decided_at = require_aware(cancelled_at, field="cancelled_at")
        self.decision_note = f"{EARLY_RETURN_PREFIX} {_require_reason(reason)}"
        self.record_event(
            AnnualLeaveEarlyReturnEvent(
                tenant_id=self.tenant_id,
                request_id=self.id,
                employee_id=self.employee_id,
                returned_by=cancelled_by,
                return_date=return_date,
                consumed_days=str(consumed),
                restored_days=str(restored),
            )
        )
        return restored

    # ------------------------------- köməkçi --------------------------------- #

    def _require_pending(self, message: str) -> None:
        if self.status.is_decided:
            raise DomainRuleError(
                message,
                user_message="Bu sorğu artıq emal edilib.",
                context={"status": self.status.value},
            )

    def to_audit_state(self) -> dict[str, object]:
        """Audit `before_state`/`after_state` üçün düz sözlük."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status.value,
            "deducted_days": None if self.deducted_days is None else str(self.deducted_days),
        }

    def __repr__(self) -> str:
        return (
            f"AnnualLeaveRequest(id={self.id}, employee={self.employee_id}, "
            f"{self.start_date}..{self.end_date}, status={self.status.value})"
        )


class AnnualLeaveBalance(AggregateRoot):
    """İşçinin bir təqvim ilindəki haqqı və istifadəsi.

    ──────────────────────────────────────────────────────────────────────────
    MƏNFİ BALANS STRUKTUR OLARAQ MÜMKÜN DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Qayda İKİ yerdədir (CLAUDE.md §5): DB-də
    `chk_annual_leave_balance_not_negative` (`used_days <= entitled_days +
    carried_over_days`) və burada `consume()` içində. İkisi də lazımdır —
    DB paralel yazıları serializasiya edir, entity isə səbəbi izah edən
    mesajı verir ("7 gün qalıb, 10 gün istənilir").

    ──────────────────────────────────────────────────────────────────────────
    BU ENTITY YAZMA YOLUNUN TƏK MƏNBƏYİ DEYİL — QƏSDƏN
    ──────────────────────────────────────────────────────────────────────────
    Balansın AZALMASI (`consume`) yarış nöqtəsidir: iki paralel təsdiq eyni
    balansı oxuyub hər ikisi "kifayətdir" deyə bilər. Ona görə həqiqi çıxma
    `AnnualLeaveBalanceRepository.consume()` — ŞƏRTLİ `UPDATE` + `rowcount`
    (`open_shift_repository.claim` naxışı) ilə edilir və bu sinif YALNIZ
    oxu/izah tərəfidir. Entity metodu isə vahid testlərdə və izah mesajında
    həmin qaydanın oxunaqlı formasıdır.
    """

    def __init__(
        self,
        *,
        balance_id: AnnualLeaveBalanceId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        year: int,
        entitled_days: Decimal = _ZERO,
        used_days: Decimal = _ZERO,
        carried_over_days: Decimal = _ZERO,
        updated_by: EmployeeId | None = None,
    ) -> None:
        super().__init__()
        if not MIN_BALANCE_YEAR <= year <= MAX_BALANCE_YEAR:
            raise DomainRuleError(
                f"Balans ili {MIN_BALANCE_YEAR}–{MAX_BALANCE_YEAR} aralığında olmalıdır",
                user_message="Seçilmiş il düzgün deyil.",
                context={"year": year},
            )
        self.id = balance_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.year = year
        self.entitled_days = _non_negative(entitled_days)
        self.used_days = _non_negative(used_days)
        self.carried_over_days = _non_negative(carried_over_days)
        self.updated_by = updated_by

    # ------------------------------- xassələr -------------------------------- #

    @property
    def total_days(self) -> Decimal:
        """Cari il üçün ƏLÇATAN ümumi gün = qazanılmış + köçürülmüş."""
        return quantize_days(self.entitled_days + self.carried_over_days)

    @property
    def available_days(self) -> Decimal:
        """QALAN gün. HEÇ VAXT MƏNFİ olmur — `max(0, ...)` sonuncu qapıdır.

        DB `CHECK`-i mənfini onsuz da rədd edir; buradakı sıxma tarixi
        məlumat idxalı ilə gələn uyğunsuz sətrin ekranda "-3 gün qalıb"
        kimi görünməsinin qarşısını alır.
        """
        return quantize_days(max(_ZERO, self.total_days - self.used_days))

    # ------------------------------- əməliyyat ------------------------------- #

    def consume(self, days: Decimal) -> None:
        """Balansdan gün çıxarır (bax sinif şərhi: həqiqi qapaq repo-dadır)."""
        if days < 0:
            raise DomainRuleError(
                "Mənfi gün çıxıla bilməz",
                user_message="Məzuniyyət günü mənfi ola bilməz.",
                context={"days": str(days)},
            )
        if days > self.available_days:
            raise DomainRuleError(
                "İllik məzuniyyət balansı kifayət etmir",
                user_message=(
                    f"Balansınızda {self.available_days} gün var, "
                    f"{quantize_days(days)} gün tələb olunur."
                ),
                context={"available": str(self.available_days), "requested": str(days)},
            )
        self.used_days = quantize_days(self.used_days + days)

    def release(self, days: Decimal) -> None:
        """Ləğv edilmiş məzuniyyətin gününü GERİ QAYTARIR.

        `max(0, ...)`: iki dəfə çağırılsa (təkrar ləğv, planlayıcının
        at-least-once icrası) `used_days` mənfiyə düşməməlidir — DB `CHECK
        (used_days >= 0)` onu onsuz da rədd edərdi, lakin istifadəçi
        anlaşılmaz sürücü xətası görərdi.
        """
        self.used_days = quantize_days(max(_ZERO, self.used_days - _non_negative(days)))

    def set_entitlement(
        self, *, entitled_days: Decimal, carried_over_days: Decimal, updated_by: EmployeeId | None
    ) -> None:
        """Haqqı və köçürməni TƏYİN EDİR (ARTIRMIR) — idempotentliyin əsası.

        `+=` YAZILMIR VƏ YAZILMAMALIDIR: il dönümü işi at-least-once icra
        olunur (bax `job_runner.py` başlığı) və eyni il üçün ikinci icra
        balansı İKİQAT artırardı. Təyinetmə isə neçə dəfə çağırılsa da eyni
        nəticəni verir.
        """
        self.entitled_days = _non_negative(entitled_days)
        self.carried_over_days = _non_negative(carried_over_days)
        self.updated_by = updated_by

    def expire_carryover(self) -> Decimal:
        """ "İstifadə et ya itir" son tarixindən sonra qalan köçürməni SİLİR.

        KÖÇÜRÜLMÜŞ GÜN ƏVVƏL XƏRCLƏNİR (yayılmış HR qaydası): ona görə
        qalıq `carried_over - used`-dir və silinmədən sonra `carried_over`
        `min(carried_over, used)` olur. Bu düstur İDEMPOTENTDİR (ikinci
        icrada dəyər dəyişmir) və `used_days <= entitled + carried_over`
        `CHECK`-ini heç vaxt poza bilmir.
        """
        remaining = max(_ZERO, self.carried_over_days - self.used_days)
        if remaining > 0:
            self.carried_over_days = quantize_days(min(self.carried_over_days, self.used_days))
        return quantize_days(remaining)

    def __repr__(self) -> str:
        return (
            f"AnnualLeaveBalance(employee={self.employee_id}, year={self.year}, "
            f"available={self.available_days}/{self.total_days})"
        )


def _non_negative(value: Decimal) -> Decimal:
    """Mənfi dəyəri SƏSSİZCƏ sıfıra endirir — `consume()`-dəki `raise` İLƏ QƏSDƏN FƏRQLİDİR.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BURADA SÜKUTLU SIFIRLAMA, `consume()`-DA İSƏ AÇIQ İSTİSNA
    ──────────────────────────────────────────────────────────────────────────
    `consume()` İSTİFADƏÇİ ƏMƏLİYYATINI yoxlayır (təsdiq zamanı balansdan
    çıxılan gün) — mənfi dəyər ORADA proqramçı/UI səhvinin ƏLAMƏTİDİR və
    əməliyyat DƏRHAL AYDIN mesajla dayandırılmalıdır (istifadəçi düyməni basıb,
    nəticə gözləyir — CLAUDE.md §6).

    Bu funksiya isə YALNIZ `__init__`/`set_entitlement()`-dən çağırılır —
    SİSTEM-HESABLANMIŞ dəyər qəbul edir: `AnnualLeaveBalance` DB SƏTRİNDƏN
    hidratasiya olunanda (`annual_leave_repository.py::_row_to_balance`)
    işə düşür. Bu yol ARTIQ DB `chk_annual_leave_balance_not_negative`
    `CHECK`-i ilə qorunur (sinif başlığı) — normal işləyən sistemdə BURAYA
    mənfi dəyər HEÇ VAXT ÇATMAMALIDIR. Əgər çatarsa (köhnə/korlanmış sətir,
    əl ilə SQL, miqrasiya səhvi), `raise` seçilsəydi HR balans ekranını
    sadəcə AÇMAQ tətbiqi qəzalandırardı — mühafizə mövqeyi isə YALNIZ
    BALANSI AZALDA bilir (heç vaxt artırmır), yəni TƏHLÜKƏSİZ tərəfə düşür:
    işçi əskik gün görər, artıq gün ALA BİLMƏZ. Ona görə `adjust_balance()`
    (use case, İSTİFADƏÇİ girişi) əvvəlcədən açıq `raise` edir, BURADA isə
    son sətir sükutla 0-a düşür — iki qapı EYNİ NƏTİCƏNİ fərqli səviyyələrdə
    həll edir.
    """
    return quantize_days(value) if value > 0 else _ZERO


def _require_reason(reason: str) -> str:
    cleaned = normalise_decision_text(reason)
    if len(cleaned) < MIN_DECISION_REASON_LENGTH:
        raise DomainRuleError(
            f"Qərar səbəbi minimum {MIN_DECISION_REASON_LENGTH} simvol olmalıdır",
            user_message="Səbəbi ətraflı yazın.",
            context={"length": len(cleaned)},
        )
    return cleaned


__all__ = [
    "CANCELLATION_PREFIX",
    "EARLY_RETURN_PREFIX",
    "MAX_BALANCE_YEAR",
    "MIN_BALANCE_YEAR",
    "MIN_DECISION_REASON_LENGTH",
    "MIN_SICK_DOCUMENT_REFERENCE_LENGTH",
    "SICK_LEAVE_PREFIX",
    "AnnualLeaveBalance",
    "AnnualLeaveRequest",
    "AnnualLeaveStatus",
]
