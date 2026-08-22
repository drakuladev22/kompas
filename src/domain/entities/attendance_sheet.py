"""Gündəlik Mağaza Tabeli aqreqatı (spesifikasiya bölmə 3 — Store Manager-in əsas funksiyası).

──────────────────────────────────────────────────────────────────────────────
TABEL BOŞ BAŞLAMIR — BU, ƏSAS QAYDADIR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3 (ÇATIŞMAZLIQ DÜZƏLİŞİ — İKİQAT MƏLUMAT DAXİLETMƏ RİSKİNİN QARŞISI):

    "Tabel BOŞ başlamır — Morning Check-in və Leave-Verification qeydlərindən
    avtomatik doldurulur. Store Manager bunu YENİDƏN əl ilə doldurmur, yalnız
    NƏZƏRDƏN KEÇİRİR, təsdiqləyir və lazım gələrsə qeyd/kontekst əlavə edir."

Ona görə bu aqreqatda **sətir əlavə edən açıq metod yoxdur** — sətirlər yalnız
`prefill()` ilə, davamiyyət qeydlərindən yaranır. Store Manager-in edə biləcəyi
iki şey var: sətrə qeyd yazmaq (`annotate()`) və tabeli təsdiqləmək
(`confirm()`). Əl ilə status dəyişdirmə QƏSDƏN yoxdur: menecerə statusu
sərbəst yazmaq imkanı versəydik, kamera-təsdiqli davamiyyət qeydi ilə
tabeldəki status ziddiyyət təşkil edə bilərdi və hansının doğru olduğu
sual altına düşərdi.

──────────────────────────────────────────────────────────────────────────────
UYĞUNSUZLUQ (MISMATCH) NƏDİR
──────────────────────────────────────────────────────────────────────────────
"Tabel HR-ın təyin etdiyi planlaşdırılmış Shift Matrix ilə avtomatik müqayisə
olunur — uyğunsuzluq aşkar edilərsə (məs. plan üzrə işə çıxmalı idi, amma heç
bir check-in qeydi yoxdur) HR_Admin-ə xəbərdarlıq göstərilir."

Uyğunsuzluğun İKİ istiqaməti var və hər ikisi tutulur:
    * plan = iş günü, fakt = qeyd yoxdur   → `ABSENT`  (işə çıxmayıb)
    * plan = istirahət, fakt = işdə görünüb → `UNPLANNED` (planlanmamış iş)

İkincisi ilk baxışda zərərsiz görünür, amma əmək haqqı hesabatında "off-day
sayı" səhv çıxır — ona görə o da uyğunsuzluqdur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import DailyAttendanceSheetConfirmedEvent
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import (
    DailySheetId,
    EmployeeId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text


class AutoAttendanceStatus(str, Enum):
    """`daily_attendance_sheet_lines.auto_status` — avtomatik təyin olunan vəziyyət.

    Dəyərlər `schema.sql`-dakı şərhlə eynidir:
    `VERIFIED | LATE | OUTSIDE | ABSENT | OFF_DAY`, üstəgəl `PENDING`,
    `UNPLANNED` və `ANNUAL_LEAVE`.

    `PENDING` niyə lazımdır: tabel gün ƏRZİNDƏ də açıla bilər və o zaman bəzi
    işçilər hələ operator təsdiqini gözləyir. Onları `ABSENT` yazmaq səhv
    olardı — hələ günün sonu deyil.

    ──────────────────────────────────────────────────────────────────────────
    `ANNUAL_LEAVE` NİYƏ AYRI STATUSDUR (DEEP-GAP D1)
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl HR-ın təsdiqlədiyi illik məzuniyyət tabeldə HEÇ VAXT görünmürdü:
    `AttendanceFact`-in illik məzuniyyət sahəsi yox idi, `facts_for` yalnız
    növbə/davamiyyət/qısa-icazə qeydlərini oxuyurdu (`annual_leave_requests`
    sözü faylında SIFIR dəfə keçirdi). Nəticədə HR-ın təsdiqlədiyi 14 günlük
    məzuniyyət tabeldə `ABSENT` ("🔴 İcazəsiz qayıb") kimi düşürdü — sistem
    ÖZ TƏSDİQ ETDİYİ qərarı intizam pozuntusu kimi göstərirdi. `OFF_DAY`-a
    yönləndirmək də yalnışdır: `OFF_DAY` "istirahət günü" deməkdir, illik
    məzuniyyət isə AYRI hüquqi kateqoriyadır (ödənişli, HR-təsdiqli) və
    hesabatda qarışdırılmamalıdır.
    """

    VERIFIED = "VERIFIED"
    LATE = "LATE"
    OUTSIDE = "OUTSIDE"
    ABSENT = "ABSENT"
    OFF_DAY = "OFF_DAY"
    PENDING = "PENDING"
    UNPLANNED = "UNPLANNED"
    ANNUAL_LEAVE = "ANNUAL_LEAVE"

    @property
    def counts_as_worked(self) -> bool:
        """Davamiyyət hesabatında "faktiki işlənilən gün" sayılırmı.

        `ANNUAL_LEAVE` QƏSDƏN BURADA YOXDUR: bu sual üçün cavab sabit deyil —
        Root parametridir (`SystemLimitKey.ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY`),
        çünki `@property` sabit qiymətdən başqa heç nə oxuya bilməz. Onu
        nəzərə alan çağırış `counts_as_worked_with()` istifadə etməlidir.
        """
        return self in (
            AutoAttendanceStatus.VERIFIED,
            AutoAttendanceStatus.LATE,
            AutoAttendanceStatus.OUTSIDE,
            AutoAttendanceStatus.UNPLANNED,
        )

    def counts_as_worked_with(self, policy: AttendanceCountingPolicy) -> bool:
        """`counts_as_worked`-in Root-parametrli variantı (yalnız `ANNUAL_LEAVE` fərqlənir)."""
        if self is AutoAttendanceStatus.ANNUAL_LEAVE:
            return policy.annual_leave_counts_as_worked
        return self.counts_as_worked

    @property
    def label_az(self) -> str:
        return _STATUS_LABELS[self]


_STATUS_LABELS: dict[AutoAttendanceStatus, str] = {
    AutoAttendanceStatus.VERIFIED: "🟢 Mağazada",
    AutoAttendanceStatus.LATE: "🟢 Gecikib",
    AutoAttendanceStatus.OUTSIDE: "🔵 Xaricdə",
    AutoAttendanceStatus.ABSENT: "🔴 İcazəsiz qayıb",
    AutoAttendanceStatus.OFF_DAY: "⚪ İstirahət",
    AutoAttendanceStatus.PENDING: "🟡 Təsdiq gözləyir",
    AutoAttendanceStatus.UNPLANNED: "⚠️ Planlanmamış iş",
    AutoAttendanceStatus.ANNUAL_LEAVE: "🟣 Məzuniyyətdə",
}


@dataclass(frozen=True)
class AttendanceCountingPolicy:
    """`ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY` Root parametrinin daşıyıcısı.

    Ayrıca dataclass olması `LaborLimits`/`AttritionWeights` ilə EYNİ naxışdır
    (bax `domain.labor_rules.LaborLimits`): pəncərəni oxuyan use case bunu BİR
    dəfə `SystemLimits` portundan qurur və pəncərədəki BÜTÜN sətirlərə eyni
    dəyəri tətbiq edir — hər sətir üçün ayrıca oxusaydıq, Root dəyəri
    dəyişdirən an eyni tabeldə iki sətir fərqli qaydayla sayıla bilərdi.
    """

    annual_leave_counts_as_worked: bool

    @classmethod
    def defaults(cls) -> AttendanceCountingPolicy:
        """`DEFAULT_LIMITS` dəyəri — YALNIZ fallback (limit portu yoxdursa)."""
        key = SystemLimitKey.ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY
        return cls(annual_leave_counts_as_worked=DEFAULT_LIMITS[key] != "0")


@dataclass
class SheetLine:
    """Tabelin bir sətri — bir işçinin həmin günü."""

    employee_id: EmployeeId
    auto_status: AutoAttendanceStatus
    planned_off: bool = False
    manager_note: str | None = None
    #: Gecikmə dəqiqəsi — yalnız `LATE` statusunda mənalıdır (hesabat üçün).
    late_minutes: int = 0

    @property
    def has_mismatch(self) -> bool:
        """Plan ↔ fakt uyğunsuzluğu (bölmə 3).

        Hesablanmış xüsusiyyətdir, saxlanan bayraq DEYİL: `planned_off` və
        `auto_status` dəyişdikdə uyğunsuzluq da avtomatik yenilənir. Ayrıca
        sahə saxlansaydı, ikisi bir-birindən ayrı düşə bilərdi.

        `ANNUAL_LEAVE` HEÇ VAXT uyğunsuzluq sayılmır (DEEP-GAP D1): aşağıdakı
        iki şərtdən heç biri bu statusla üst-üstə düşmür (nə `UNPLANNED`, nə
        `ABSENT`), ona görə əlavə xüsusi hal YAZILMAYIB — sıralamanın özü
        kifayət edir. HR-ın təsdiqlədiyi məzuniyyət "plana uyğunsuz" ola
        bilməz, çünki о, planın ÖZÜNDƏN üstün bir təsdiqdir.
        """
        if self.planned_off:
            return self.auto_status is AutoAttendanceStatus.UNPLANNED
        return self.auto_status is AutoAttendanceStatus.ABSENT

    def to_audit_state(self) -> dict[str, object]:
        return {
            "employee_id": str(self.employee_id),
            "auto_status": self.auto_status.value,
            "planned_off": self.planned_off,
            "has_mismatch": self.has_mismatch,
        }


class DailyAttendanceSheet(AggregateRoot):
    """Bir mağazanın bir gününə aid tabel (`daily_attendance_sheets`)."""

    def __init__(
        self,
        *,
        sheet_id: DailySheetId,
        tenant_id: TenantId,
        store_id: StoreId,
        sheet_date: date,
        lines: list[SheetLine] | None = None,
        is_confirmed: bool = False,
        confirmed_by: EmployeeId | None = None,
        confirmed_at: datetime | None = None,
        manager_note: str | None = None,
    ) -> None:
        super().__init__()
        self.id = sheet_id
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.sheet_date = sheet_date
        self.lines: list[SheetLine] = lines or []
        self.is_confirmed = is_confirmed
        self.confirmed_by = confirmed_by
        self.confirmed_at = confirmed_at
        self.manager_note = manager_note

    # ----------------------------- ön-doldurma ------------------------------- #

    def prefill(self, lines: list[SheetLine]) -> None:
        """Avtomatik doldurma — Morning Check-in + Leave qeydlərindən.

        Təsdiqlənmiş tabel YENİDƏN doldurulmur: menecer nəzərdən keçirib
        imzalayıb, sonradan altındakı məlumatın dəyişməsi imzanı mənasız
        edərdi. Dəyişiklik lazımdırsa HR yeni gün üçün araşdırma aparır.
        """
        if self.is_confirmed:
            raise DomainRuleError(
                "Təsdiqlənmiş tabel yenidən doldurula bilməz",
                user_message="Bu tabel artıq təsdiqlənib.",
                context={"sheet_date": self.sheet_date.isoformat()},
            )
        # Menecerin əvvəllər yazdığı qeydlər İTMİR — yenidən açılan tabeldə
        # onları yazmağa məcbur etmək iki dəfə iş deməkdir.
        existing_notes = {line.employee_id: line.manager_note for line in self.lines}
        for line in lines:
            if line.manager_note is None:
                line.manager_note = existing_notes.get(line.employee_id)
        self.lines = lines

    # -------------------------------- qeyd ----------------------------------- #

    def annotate(self, employee_id: EmployeeId, note: str) -> None:
        """Sətrə kontekst qeydi (məs. "PIN sistemi işləmirdi, şifahi təsdiq")."""
        self._require_open()
        cleaned = normalise_decision_text(note)
        for line in self.lines:
            if line.employee_id == employee_id:
                line.manager_note = cleaned or None
                return
        raise DomainRuleError(
            "Bu işçi tabeldə yoxdur",
            user_message="İşçi bu tabeldə tapılmadı.",
            context={"employee_id": str(employee_id)},
        )

    def set_manager_note(self, note: str) -> None:
        """Bütün tabelə aid ümumi qeyd."""
        self._require_open()
        cleaned = normalise_decision_text(note)
        self.manager_note = cleaned or None

    # ------------------------------- təsdiq ---------------------------------- #

    def confirm(self, *, manager_id: EmployeeId, confirmed_at: datetime) -> None:
        """Store Manager tabeli təsdiqləyir."""
        self._require_open()
        if not self.lines:
            raise DomainRuleError(
                "Boş tabel təsdiqlənə bilməz",
                user_message="Tabeldə heç bir işçi yoxdur.",
                context={"sheet_date": self.sheet_date.isoformat()},
            )

        self.is_confirmed = True
        self.confirmed_by = manager_id
        self.confirmed_at = require_aware(confirmed_at, field="confirmed_at")
        self.record_event(
            DailyAttendanceSheetConfirmedEvent(
                tenant_id=self.tenant_id,
                sheet_id=self.id,
                store_id=self.store_id,
                sheet_date=self.sheet_date,
                confirmed_by=manager_id,
                mismatch_count=self.mismatch_count,
            )
        )

    # ------------------------------ göstəricilər ------------------------------ #

    @property
    def mismatch_count(self) -> int:
        """HR_Admin-ə xəbərdarlıq göstərilməsinin əsası."""
        return sum(1 for line in self.lines if line.has_mismatch)

    @property
    def mismatched_lines(self) -> list[SheetLine]:
        return [line for line in self.lines if line.has_mismatch]

    @property
    def worked_count(self) -> int:
        """DEFOLT siyasətlə sayır (`AttendanceCountingPolicy.defaults()`).

        Tenant-a görə Root dəyərini nəzərə alan çağırış `worked_count_with()`
        istifadə etməlidir (bax `DailyAttendanceSheetUseCase`).
        """
        return self.worked_count_with(AttendanceCountingPolicy.defaults())

    def worked_count_with(self, policy: AttendanceCountingPolicy) -> int:
        return sum(1 for line in self.lines if line.auto_status.counts_as_worked_with(policy))

    def _require_open(self) -> None:
        if self.is_confirmed:
            raise DomainRuleError(
                "Təsdiqlənmiş tabel dəyişdirilə bilməz",
                user_message="Bu tabel artıq təsdiqlənib.",
                context={"sheet_date": self.sheet_date.isoformat()},
            )

    def __repr__(self) -> str:
        return (
            f"DailyAttendanceSheet(store={self.store_id}, date={self.sheet_date}, "
            f"lines={len(self.lines)}, confirmed={self.is_confirmed})"
        )


@dataclass(frozen=True)
class AttendanceFact:
    """Ön-doldurma üçün bir işçinin xam faktları.

    Use case bu strukturu davamiyyət/icazə/növbə repo-larından yığır və
    `derive_status()` onu tabel statusuna çevirir. Ayrı olması qəsdəndir:
    çevirmə qaydası SAF funksiyadır və testdə DB olmadan yoxlana bilir.
    """

    employee_id: EmployeeId
    planned_off: bool
    has_verified_check_in: bool = False
    is_pending_verification: bool = False
    is_currently_outside: bool = False
    is_late: bool = False
    late_minutes: int = 0
    day_is_over: bool = True
    #: DEEP-GAP D1 — bu gün üçün TƏSDİQLƏNMİŞ illik məzuniyyət var (bax
    #: `AnnualLeaveRequestRepository.find_overlapping_approved`, EYNİ sorğu
    #: `shift_scheduling.ANNUAL_LEAVE_CONFLICT_KIND`-in oxu tərəfi ilə).
    #: Defolt `False`: mövcud çağıranlar (testlər, sahtələr) bu sahəni
    #: BİLMİR və köhnə davranış (illik məzuniyyət nəzərə alınmır) DƏYİŞMİR.
    on_annual_leave: bool = False

    def derive_status(self) -> AutoAttendanceStatus:  # noqa: PLR0911 - hər `return` AYRI status qapısıdır
        """Faktlardan tabel statusunu çıxarır (bölmə 3, 4).

        Sıralama vacibdir: "hazırda xaricdə" olmaq işə gəlməyi ƏVƏZ ETMİR —
        işçi əvvəlcə təsdiqlənib, sonra icazəyə çıxıb. Ona görə `OUTSIDE`
        yoxlaması `VERIFIED`-dən ƏVVƏL gəlir, amma yalnız təsdiqlənmiş
        işçilər üçün mənalıdır (STEP 1 yalnız `🟢`-dan işə düşür).

        `ANNUAL_LEAVE` `OUTSIDE`-dan DƏRHAL SONRA, hər cür check-in
        siqnalından ƏVVƏL yoxlanır (DEEP-GAP D1): HR-ın TƏSDİQLƏDİYİ
        məzuniyyət qeydi ötəri/qeyri-müəyyən check-in siqnallarından üstündür
        — məhz D1-in kök səbəbi bunun əksi idi (sistem öz təsdiqini
        e'tibarsız sayıb "qayıb" yazırdı). Yalnız fiziki iştirak faktı
        (`is_currently_outside`, artıq mağazada QEYDİYYATDAN keçmiş insan)
        onu üstələyə bilər.
        """
        if self.is_currently_outside:
            return AutoAttendanceStatus.OUTSIDE
        if self.on_annual_leave:
            return AutoAttendanceStatus.ANNUAL_LEAVE
        if self.has_verified_check_in:
            if self.planned_off:
                return AutoAttendanceStatus.UNPLANNED
            return AutoAttendanceStatus.LATE if self.is_late else AutoAttendanceStatus.VERIFIED
        if self.is_pending_verification:
            return AutoAttendanceStatus.PENDING
        if self.planned_off:
            return AutoAttendanceStatus.OFF_DAY
        # Gün hələ bitməyibsə "qayıb" demək tezdir — işçi sonra gələ bilər.
        return AutoAttendanceStatus.ABSENT if self.day_is_over else AutoAttendanceStatus.PENDING

    def to_line(self) -> SheetLine:
        status = self.derive_status()
        return SheetLine(
            employee_id=self.employee_id,
            auto_status=status,
            planned_off=self.planned_off,
            late_minutes=self.late_minutes if status is AutoAttendanceStatus.LATE else 0,
        )


def build_lines(facts: list[AttendanceFact]) -> list[SheetLine]:
    """Faktlar → tabel sətirləri (ön-doldurmanın saf hissəsi)."""
    return [fact.to_line() for fact in facts]


__all__ = [
    "AttendanceCountingPolicy",
    "AttendanceFact",
    "AutoAttendanceStatus",
    "DailyAttendanceSheet",
    "SheetLine",
    "build_lines",
]
