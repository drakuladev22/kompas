"""HR hesabat mühərriki — İKİ AYRI Excel faylı (spesifikasiya bölmə 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİ FAYL, BİR YOX
──────────────────────────────────────────────────────────────────────────────
Bölmə 6 bunu qeyd-şərtsiz tələb edir və səbəbi mühasibatlıq axınıdır:

    FAYL 1 — Aylıq Davamiyyət Hesabatı: YALNIZ FİKS MAAŞ üçün. Cərimə ilə
             ƏLAQƏSİ YOXDUR.
    FAYL 2 — Premiya & Cərimə Hesabatı: cərimələr əsas maaşdan DEYİL, aylıq
             PREMİYADAN kəsilir.

İki fayl birləşdirilsəydi, mühasib cərimə sütununu görüb onu maaşdan çıxara
bilərdi — bu, spesifikasiyanın açıq şəkildə düzəltdiyi səhvdir. Ayrılıq
texniki deyil, HÜQUQİ tələbdir.

──────────────────────────────────────────────────────────────────────────────
LOCK MEXANİZMİ (KRİTİK, HÜQUQİ RİSK)
──────────────────────────────────────────────────────────────────────────────
Bölmə 6: bir cərimə FAYL 2-yə YALNIZ (a) 72 saatlıq etiraz pəncərəsi
bağlandıqdan SONRA və (b) statusu `REVERSED` olmadıqda düşür. Qayda
`Fine.is_exportable()`-də yaşayır — burada TƏKRARLANMIR, çağırılır. Əks halda
iki yerdə eyni məntiq olardı və biri düzəldiləndə digəri arxada qalardı.

Pəncərə hələ açıqdırsa, cərimə həmin ayın export-undan xaric edilir və növbəti
dövrdə yenidən qiymətləndirilir — `Fine.mark_exported()` isə eyni cərimənin
İKİ ay ardıcıl tutulmasının qarşısını alır.

TARİX ARALIĞI SEÇİMİ BU QAYDANI BAYPAS ETMİR (Faza 7, Struktur Qərar D):
`[Xüsusi Aralıq]` seçilib aralığın son günü hələ açıq pəncərədə olan cərimələri
tutmaq CƏHDİ EDİLƏRSƏ, həmin cərimələr YENƏ DƏ xaric edilir — çünki süzgəc
tarixə görə deyil, `Fine.is_exportable(now=...)`-a görə işləyir və o funksiya
BURADA TƏKRARLANMIR. Aralığın seçilməsi «hansı cərimələrə BAXILIR» sualını
dəyişir, «hansı cərimə tutula BİLƏR» sualını YOX.

──────────────────────────────────────────────────────────────────────────────
ÜST-ÜSTƏ DÜŞƏN İKİ ARALIQ — QƏRAR VƏ ONUN ƏSASLANDIRMASI (Faza 7)
──────────────────────────────────────────────────────────────────────────────
Sabit aylarda dövrlər heç vaxt kəsişmirdi. İxtiyari aralıqlarda isə kəsişir:
1–15 aprel export edilir, sonra 10–20 aprel seçilir. İki səhv mümkündür və hər
ikisi qəbuledilməzdir — eyni cərimənin İKİ DƏFƏ tutulması (işçidən ikiqat pul
kəsilir) və ya SÜKUTLA atlanması (şirkət pulu itirir).

QƏRAR: **üst-üstə düşmə BLOKLANMIR; təkrar tutulma cərimə səviyyəsində
İDEMPOTENT şəkildə qarşısı alınır və atlanan sətirlər AÇIQ SAYĞACLA bildirilir.**

  * İKİQAT TUTULMA STRUKTURCA MÜMKÜN DEYİL: `Fine.is_exportable()` `exported_
    period` dolu sətri qaytarmır. Yəni 10–15 aprelin cərimələri ikinci export-a
    ÜMUMİYYƏTLƏ daxil olmur — bu, tarix süzgəcinin deyil, aqreqatın öz
    invariantının nəticəsidir və onu yan keçmək üçün domen qaydasını
    dəyişdirmək lazım gələrdi.
  * ATLANMA SÜKUTLA BAŞ VERMİR: `BonusPenaltySelection.already_exported_count`
    onları sayır, `already_exported_periods` isə HANSI dövrdə tutulduqlarını
    adlandırır; `overlap_notice_az()` bunu hazır Azərbaycan cümləsinə çevirir.

BLOKLAMA NİYƏ SEÇİLMƏDİ: fayl itirilib yenidən çıxarılanda, mağaza üzrə ayrıca
kəsik lazım olanda və ya aralıq bir gün uzadılanda bloklama qanuni əməliyyatı
dayandırardı. İstifadəçi onu yan keçmək üçün aralığı süni şəkildə daraldardı —
yəni qayda pozulmazdı, sadəcə hesabat parçalanardı. İdempotent atlama isə
nəticəni HƏR HALDA doğru saxlayır: hər cərimə dəqiq bir dəfə tutulur.

──────────────────────────────────────────────────────────────────────────────
BU MODUL FAYL YAZMIR
──────────────────────────────────────────────────────────────────────────────
Burada yalnız SƏTİRLƏR hesablanır. `.xlsx` yazma
`infrastructure/reporting/excel.py`-dədir — beləliklə hesabat məntiqi
openpyxl olmadan, adi siyahı müqayisəsi ilə test oluna bilir.

NORMA HESABLAMASI DA BURADA DEYİL: gün/saat arifmetikası `domain/work_norm.py`
saf funksiyasındadır (pul-kritik olduğu üçün domen coverage qapısının altında).
Bu modul yalnız məlumatı yığır və nəticəni sətrə çevirir.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.domain.entities.fine import Fine
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.money import Money
from src.domain.work_norm import (
    EmploymentWindow,
    PlannedDay,
    WorkNorm,
    WorkNormRequest,
    calculate_work_norm,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import SystemLimits
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

EXPORT_REPORTS_FLAG = "can_export_reports"

MONTHS_IN_YEAR = 12
#: Sistemin mövcud olduğu ən erkən il — yazı səhvini (məs. `20026`) tutur.
EARLIEST_REPORT_YEAR = 2000

#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.REPORT_RANGE_MAX_DAYS`
#: (seed: migrations/043). Modul sabiti ədəd SAXLAMIR: dəyər `DEFAULT_LIMITS`-dən
#: oxunur ki, kod və seed heç vaxt fərqli defoltla işləməsin.
FALLBACK_RANGE_MAX_DAYS: int = int(DEFAULT_LIMITS[SystemLimitKey.REPORT_RANGE_MAX_DAYS])
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.OVERTIME_DAILY_NORM_HOURS`
#: (seed: migrations/026). Norma saatın hüquqi tavanı; əsaslandırma
#: `domain/work_norm.py` başlığındadır ("ZİDDİYYƏT QƏRARI").
FALLBACK_LEGAL_DAILY_NORM_HOURS: Decimal = Decimal(
    DEFAULT_LIMITS[SystemLimitKey.OVERTIME_DAILY_NORM_HOURS]
)


class ReportPermissionError(KompasOSError):
    """Hesabat çıxarmaq üçün səlahiyyət yoxdur."""

    user_message = "Hesabat çıxarmaq səlahiyyətiniz yoxdur."


class ReportPeriodError(KompasOSError):
    """Hesabat dövrü yararsızdır."""

    user_message = "Hesabat dövrü düzgün deyil."


class ReportRangeTooLongError(ReportPeriodError):
    """Seçilmiş aralıq ROOT həddindən uzundur.

    AYRI SİNİF QƏSDƏNDİR: səbəb «tarix səhvdir» DEYİL — tarixlər tamamilə
    düzgündür, sadəcə aralıq çox uzundur və düzəlişi də fərqlidir (aralığı
    qısalt VƏ YA Root-dan həddi artır). Eyni istisna sinfi ilə göstərilsəydi,
    istifadəçi tarixi düzəltməyə çalışıb heç nə əldə etməzdi.

    `user_message` `raise` anında dəqiq rəqəmlərlə ƏVƏZLƏNİR — sükutla rədd
    etmə YOXDUR.
    """

    user_message = "Seçilmiş tarix aralığı icazə verilən maksimumdan uzundur."


@dataclass(frozen=True)
class ReportPeriod:
    """Hesabat ayı — `YYYY-MM` (fayl adında və `exported_period`-də istifadə olunur)."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= MONTHS_IN_YEAR:
            raise ReportPeriodError(f"Ay 1–{MONTHS_IN_YEAR} aralığında olmalıdır: {self.month}")
        if self.year < EARLIEST_REPORT_YEAR:
            raise ReportPeriodError(f"İl yararsızdır: {self.year}")

    @property
    def key(self) -> str:
        """`Fine.exported_period` üçün açar."""
        return f"{self.year:04d}-{self.month:02d}"

    def label_az(self) -> str:
        return f"{_MONTHS_AZ[self.month - 1]} {self.year}"

    def to_range(self) -> ReportRange:
        """Tam ayın gün aralığı — `[Tam Ay]` yolunun `ReportRange`-ə körpüsü."""
        return ReportRange.for_month(self.year, self.month)

    def __str__(self) -> str:
        return self.key


@dataclass(frozen=True)
class ReportRange:
    """İxtiyari hesabat aralığı — `[Tam Ay]` onun XÜSUSİ HALIDIR (Faza 7).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `ReportPeriod` SİLİNMİR VƏ DƏYİŞDİRİLMİR
    ──────────────────────────────────────────────────────────────────────────
    `ReportPeriod` `fines.exported_period`-də ONILLIKLƏRLƏ qalacaq `'YYYY-MM'`
    açarının sahibidir və mövcud sətirlərin mənasını daşıyır. Onu aralığa
    çevirmək köhnə sətirləri yenidən şərh etmək demək olardı. Ona görə tam-ay
    yolu OLDUĞU KİMİ qalır, `ReportRange` isə onun ÜSTÜNƏ qurulur.

    ──────────────────────────────────────────────────────────────────────────
    `key` NİYƏ İKİ FORMATLIDIR
    ──────────────────────────────────────────────────────────────────────────
    Tam ay üçün `key` DƏQİQ `'YYYY-MM'` qaytarır — yəni tam-ay export-u Faza 7-dən
    ƏVVƏLKİ ilə HƏRFƏN eyni açarı yazır və köhnə `exported_period` sətirləri ilə
    müqayisə edilə bilir. Yalnız qeyri-tam aralıq `'YYYY-MM-DD_YYYY-MM-DD'`
    formatına keçir.

    Ayırıcı `_` seçilib, `..` YOX: açar fayl adına da düşür
    (`Davamiyyet_<key>.xlsx`) və nöqtəli variant Windows-da uzantı kimi
    oxunma riski yaradardı.
    """

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ReportPeriodError(
                f"Aralığın bitmə tarixi başlanğıcdan əvvəl ola bilməz: "
                f"{self.start.isoformat()} > {self.end.isoformat()}",
                user_message="Bitmə tarixi başlanğıc tarixindən əvvəl ola bilməz.",
            )
        if self.start.year < EARLIEST_REPORT_YEAR:
            raise ReportPeriodError(f"İl yararsızdır: {self.start.year}")

    # ------------------------------ qurucular -------------------------------- #

    @classmethod
    def for_month(cls, year: int, month: int) -> ReportRange:
        """Tam ay — ayın uzunluğu `calendar`-dan gəlir (fevral/uzun il).

        Validasiya `ReportPeriod`-a HƏVALƏ EDİLİR (təkrar yazılmır): ay/il
        yoxlaması onsuz da orada var və iki yerdə saxlanılsaydı biri
        yenilənəndə digəri arxada qalardı.
        """
        period = ReportPeriod(year, month)
        last_day = calendar.monthrange(period.year, period.month)[1]
        return cls(date(period.year, period.month, 1), date(period.year, period.month, last_day))

    @classmethod
    def from_period(cls, period: ReportPeriod) -> ReportRange:
        return cls.for_month(period.year, period.month)

    # ------------------------------ xassələr --------------------------------- #

    @property
    def day_count(self) -> int:
        """Aralığın təqvim günü sayı — HƏR İKİ uc daxildir.

        Bir günlük aralıq (`start == end`) 1 qaytarır, 0 YOX: həmin günün
        tabelini çıxarmaq real HR ehtiyacıdır və 0 gün "boş hesabat" demək
        olardı.
        """
        return (self.end - self.start).days + 1

    @property
    def is_full_month(self) -> bool:
        """Aralıq DƏQİQ bir təqvim ayını əhatə edirmi."""
        if (self.start.year, self.start.month) != (self.end.year, self.end.month):
            return False
        last_day = calendar.monthrange(self.start.year, self.start.month)[1]
        return self.start.day == 1 and self.end.day == last_day

    @property
    def key(self) -> str:
        """`Fine.exported_period` üçün açar (sinif başlığındakı iki format)."""
        if self.is_full_month:
            return f"{self.start.year:04d}-{self.start.month:02d}"
        return f"{self.start.isoformat()}_{self.end.isoformat()}"

    def label_az(self) -> str:
        if self.is_full_month:
            return f"{_MONTHS_AZ[self.start.month - 1]} {self.start.year}"
        return f"{self.start:%d.%m.%Y} – {self.end:%d.%m.%Y}"

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def __str__(self) -> str:
        return self.key


_MONTHS_AZ = (
    "Yanvar",
    "Fevral",
    "Mart",
    "Aprel",
    "May",
    "İyun",
    "İyul",
    "Avqust",
    "Sentyabr",
    "Oktyabr",
    "Noyabr",
    "Dekabr",
)


# --------------------------------------------------------------------------- #
# FAYL 1 — Aylıq Davamiyyət Hesabatı
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AttendanceRow:
    """FAYL 1 sətri — bölmə 6-da sadalanan sütunlarla EYNİ ardıcıllıqda."""

    employee_id: EmployeeId
    full_name: str
    store_name: str
    position_name: str
    norm_work_days: int
    actual_worked_days: int
    off_days: int
    unauthorized_absences: int
    #: Norma SAAT — hər günün öz İş Rejimindən (Faza 7). Defolt `0.00` olması
    #: qəsdəndir: tam-ay yolu (`build_attendance_rows`) saat hesablamır və
    #: onu birdən məcburi etmək mövcud çağırışları qırardı. Aralıq yolu
    #: (`build_attendance_rows_for_range`) həmişə doldurur.
    norm_work_hours: Decimal = Decimal("0.00")
    #: Aralığın işçiyə AİD hissəsi. `1.0000` = tam dövr işləyib.
    pro_rata_ratio: Decimal = Decimal("1.0000")
    #: İş rejimi hüquqi gündəlik normadan uzun olduğu üçün SIXILAN gün sayı —
    #: fərq `overtime_log`-un payıdır (bax `domain/work_norm.py` başlığı).
    capped_norm_days: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("Norma iş günləri", self.norm_work_days),
            ("Faktiki işlənilən gün", self.actual_worked_days),
            ("Off-day sayı", self.off_days),
            ("İcazəsiz qayıb", self.unauthorized_absences),
            ("Sıxılmış norma günü", self.capped_norm_days),
        ):
            if value < 0:
                raise ReportPeriodError(f"{label} mənfi ola bilməz: {value}")
        if self.norm_work_hours < 0:
            raise ReportPeriodError(f"Norma saat mənfi ola bilməz: {self.norm_work_hours}")
        if not 0 <= self.pro_rata_ratio <= 1:
            raise ReportPeriodError(
                f"Pro-rata əmsalı 0–1 aralığında olmalıdır: {self.pro_rata_ratio}"
            )

    @property
    def is_partial_period(self) -> bool:
        """İşçi dövrün yalnız bir hissəsində işləyibmi (ekranda nişan üçün)."""
        return self.pro_rata_ratio < 1


# --------------------------------------------------------------------------- #
# FAYL 2 — Premiya & Cərimə Hesabatı
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BonusPenaltyRow:
    """FAYL 2 sətri.

    `open_appeal_count` spesifikasiyanın son cümləsindəndir: "Export ekranında
    hər sətir üçün «etiraz pəncərəsi vəziyyəti» (bağlı/açıq) aydın göstərilir".
    Yəni istifadəçi məbləğin niyə gözlədiyindən daha az olduğunu görməlidir.
    """

    employee_id: EmployeeId
    full_name: str
    store_name: str
    gross_sales: Money
    earned_points: int
    confirmed_fine_count: int
    total_fine_amount: Money
    #: Pəncərəsi HƏLƏ AÇIQ olduğu üçün bu aydan XARİC edilən cərimə sayı.
    open_appeal_count: int = 0
    #: ƏVVƏLKİ bir dövrdə ARTIQ tutulmuş və ona görə bu aralıqda TƏKRAR
    #: tutulmayan cərimə sayı (Faza 7, üst-üstə düşən aralıq). Sıfırdan
    #: böyük olması SƏHV DEYİL — aralıqların kəsişdiyinin göstəricisidir.
    already_exported_count: int = 0

    @property
    def has_deferred_fines(self) -> bool:
        """Ekranda "açıq pəncərə" nişanı göstərilməlidirmi."""
        return self.open_appeal_count > 0

    @property
    def has_overlap_with_previous_export(self) -> bool:
        """Bu sətirdə əvvəlki dövrdə tutulmuş cərimə varmı."""
        return self.already_exported_count > 0


@dataclass
class BonusPenaltySelection:
    """Hesablama nəticəsi — sətirlər + hansı cərimələrin daxil olduğu.

    `included_fines` sətirlərin özündən AYRI qaytarılır, çünki fayl uğurla
    yazıldıqdan SONRA onlar `mark_exported()` ilə işarələnməlidir. Sətirlərdən
    geri çıxarmaq mümkün olmazdı — orada yalnız cəmlər var.
    """

    rows: list[BonusPenaltyRow] = field(default_factory=list)
    included_fines: list[Fine] = field(default_factory=list)
    deferred_fine_count: int = 0
    #: Üst-üstə düşən aralıq: artıq tutulduğu üçün ATLANAN cərimə sayı.
    already_exported_count: int = 0
    #: Həmin cərimələrin tutulduğu dövr açarları (sıralanmış, təkrarsız).
    #: `list` (dəst deyil) — ekran və log ardıcıllığı sabit olmalıdır.
    already_exported_periods: list[str] = field(default_factory=list)

    def overlap_notice_az(self) -> str | None:
        """Üst-üstə düşmə barədə hazır Azərbaycan cümləsi (yoxdursa `None`).

        Mətn BURADA qurulur, ekranda yox: eyni cümlə həm export önizləməsində,
        həm də audit sətrində lazımdır və iki yerdə yazılsaydı biri
        yenilənəndə digəri fərqlənərdi.
        """
        if self.already_exported_count <= 0:
            return None
        periods = ", ".join(self.already_exported_periods)
        return (
            f"{self.already_exported_count} cərimə bu aralığa düşür, lakin artıq "
            f"əvvəlki dövr(lər)də tutulub ({periods}) — təkrar tutulmur."
        )


# --------------------------------------------------------------------------- #
# Use case
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EmployeeAttendanceFacts:
    """FAYL 1 üçün bir işçinin hazır sayğacları.

    Bu sayğacları repository hesablayır (SQL aqreqasiyası) — use case onları
    yalnız sətrə çevirir. Hesablamanı bura köçürmək 21 filialın bütün
    davamiyyət qeydlərini yaddaşa yükləmək demək olardı.
    """

    employee_id: EmployeeId
    full_name: str
    store_name: str
    position_name: str
    norm_work_days: int
    actual_worked_days: int
    off_days: int
    unauthorized_absences: int


@dataclass(frozen=True)
class EmployeeSalesFacts:
    """FAYL 2 üçün bir işçinin satış tərəfi (1C-dən sinxronlaşdırılmış)."""

    employee_id: EmployeeId
    full_name: str
    store_name: str
    gross_sales: Money
    earned_points: int


@runtime_checkable
class ReportFactProvider(Protocol):
    """Hesabat rəqəmlərinin mənbəyi (SQL aqreqasiyası).

    NİYƏ `domain/interfaces/ports.py`-DA DEYİL: qaytardığı tiplər
    (`EmployeeAttendanceFacts`, `EmployeeSalesFacts`) TƏTBİQ qatının
    strukturlarıdır. Portu domenə qoymaq domen → application asılılığı
    yaradardı və qat sırasını tərsinə çevirərdi.
    """

    def attendance_facts(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeeAttendanceFacts]: ...

    def sales_facts(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeeSalesFacts]: ...


@dataclass(frozen=True)
class EmployeePlanFacts:
    """Bir işçinin Shift Matrix planı + məşğulluq pəncərəsi (Faza 7).

    NİYƏ `EmployeeAttendanceFacts`-ə QOŞULMUR: davamiyyət faktları AQREQAT
    sayğaclardır (SQL `count(*)`), bu isə GÜN-GÜN detaldır. Birləşdirilsəydi,
    tam-ay yolu da hər dəfə 30 sətirlik detalı yükləməyə məcbur olardı —
    halbuki ona yalnız cəm lazımdır.
    """

    employee_id: EmployeeId
    planned_days: tuple[PlannedDay, ...] = ()
    employment: EmploymentWindow = field(default_factory=EmploymentWindow)


@runtime_checkable
class PlanFactProvider(Protocol):
    """Shift Matrix planının hesabat üçün oxunma portu.

    `ReportFactProvider` ilə EYNİ səbəbdən `domain/interfaces/ports.py`-da
    DEYİL: qaytardığı `EmployeePlanFacts` tətbiq qatının strukturudur.

    AYRI PROTOKOL, `ReportFactProvider`-ə METOD ƏLAVƏSİ DEYİL: mövcud
    protokola metod əlavə etmək onu ödəyən HƏR sinfi (o cümlədən testlərdəki
    sahtələri) dərhal uyğunsuz edərdi — halbuki tam-ay yolunun bu məlumata
    ehtiyacı yoxdur. Eyni repository sinfi hər iki protokolu ödəyə bilər.
    """

    def plan_facts(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeePlanFacts]: ...


class MonthlyReportUseCase:
    """İki hesabatın sətirlərini hazırlayır — fayl yazmadan.

    `Clock` portu ALMIR: hər metod `now`-u açıq arqument kimi qəbul edir.
    Səbəb LOCK MEXANİZMİ-dir — "hansı an üçün hesablanır" sualı hesabatın
    nəticəsini dəyişir (72 saatlıq pəncərə), ona görə həmin an gizli asılılıq
    deyil, GÖRÜNƏN parametr olmalıdır.

    `limits` İSƏ QƏBUL EDİLİR (Faza 7) və bu, yuxarıdakı qərara ZİDD DEYİL:
    ROOT həddi «hansı an» sualına cavab vermir, hesabatın RƏQƏMLƏRİNİ
    dəyişmir — yalnız hansı aralığın ÜMUMİYYƏTLƏ qəbul ediləcəyini müəyyən
    edir. `None` ötürülə bilər (test və maket yolu) — o halda `DEFAULT_LIMITS`
    fallback-ı işləyir və davranış dəyişmir.
    """

    def __init__(self, *, limits: SystemLimits | None = None) -> None:
        self._limits = limits

    # ------------------------------ dövr seçimi ------------------------------ #

    def resolve_month(self, *, year: int, month: int) -> ReportRange:
        """`[Tam Ay]` yolu — DAVRANIŞI DƏYİŞMƏYİB.

        MAKSİMUM ARALIQ HƏDDİ BURADA TƏTBİQ OLUNMUR və bu qəsdəndir: Root
        həddi 15 günə salsa belə, oktyabrın tam hesabatı çıxarıla bilməlidir.
        Hədd `[Xüsusi Aralıq]` seçiminin performans qoruyucusudur, mövcud
        aylıq axının qapısı deyil (`migrations/043` başlığı).
        """
        return ReportRange.for_month(year, month)

    def resolve_range(self, *, tenant_id: TenantId, start: date, end: date) -> ReportRange:
        """`[Xüsusi Aralıq]` yolu — ROOT həddi ilə birlikdə.

        Hədd aşıldıqda SÜKUTLA rədd etmə YOXDUR: istisnanın `user_message`-i
        həm faktiki, həm icazə verilən gün sayını göstərir ki, istifadəçi nə
        edəcəyini bilsin.
        """
        report_range = ReportRange(start, end)
        maximum = self._max_range_days(tenant_id)
        if report_range.day_count > maximum:
            raise ReportRangeTooLongError(
                f"Aralıq {report_range.day_count} gündür, icazə verilən maksimum {maximum}",
                user_message=(
                    f"Seçilmiş aralıq {report_range.day_count} gündür — icazə verilən "
                    f"maksimum {maximum} gündür. Aralığı qısaldın və ya ROOT İdarə "
                    f"Mərkəzindən «{SystemLimitKey.REPORT_RANGE_MAX_DAYS.value}» "
                    f"parametrini artırın."
                ),
                context={"day_count": report_range.day_count, "maximum": maximum},
            )
        return report_range

    # ------------------------------- FAYL 1 ---------------------------------- #

    def build_attendance_rows(
        self, *, actor: Employee, facts: list[EmployeeAttendanceFacts], now: datetime
    ) -> list[AttendanceRow]:
        """Davamiyyət sətirləri — cərimə məlumatı QƏSDƏN daxil edilmir."""
        self._require_export_permission(actor, now=now)
        return [
            AttendanceRow(
                employee_id=fact.employee_id,
                full_name=fact.full_name,
                store_name=fact.store_name,
                position_name=fact.position_name,
                norm_work_days=fact.norm_work_days,
                actual_worked_days=fact.actual_worked_days,
                off_days=fact.off_days,
                unauthorized_absences=fact.unauthorized_absences,
            )
            for fact in facts
        ]

    def build_attendance_rows_for_range(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        facts: list[EmployeeAttendanceFacts],
        plans: list[EmployeePlanFacts],
        report_range: ReportRange,
        now: datetime,
    ) -> list[AttendanceRow]:
        """İxtiyari aralıq üçün davamiyyət sətirləri — DİNAMİK norma + pro-rata.

        ──────────────────────────────────────────────────────────────────────
        NORMA HANSI MƏNBƏDƏN GƏLİR (İKİ MƏNBƏ QARIŞDIRILMIR)
        ──────────────────────────────────────────────────────────────────────
        `EmployeeAttendanceFacts.norm_work_days`/`off_days` SQL aqreqatıdır və
        pro-rata-nı, iş rejiminin saatını, aralıq ərzində rejim dəyişməsini
        BİLMİR. Bu yolda onlar QƏSDƏN İSTİFADƏ OLUNMUR — norma gün/saat
        `domain/work_norm.calculate_work_norm`-dan gəlir, yəni tək mənbədən.

        `actual_worked_days` və `unauthorized_absences` isə ƏKSİNƏ, yalnız
        SQL-dən gələ bilər: onlar plandan yox, kamera-təsdiqli davamiyyət
        qeydlərindən hesablanır (bax `report_repositories.py` başlığı).

        PLANI OLMAYAN İŞÇİ SƏTİRDƏN DÜŞMÜR: `plans` içində qarşılığı yoxdursa
        boş plan tətbiq olunur və norma 0 çıxır — bu, HR üçün "bu işçiyə plan
        qurulmayıb" siqnalıdır və sətri gizlətmək həmin siqnalı udardı.
        """
        self._require_export_permission(actor, now=now)
        legal_norm = self._legal_daily_norm_hours(tenant_id)
        by_employee = {plan.employee_id: plan for plan in plans}

        rows: list[AttendanceRow] = []
        for fact in facts:
            plan = by_employee.get(fact.employee_id)
            norm = calculate_work_norm(
                WorkNormRequest(
                    start=report_range.start,
                    end=report_range.end,
                    plan=() if plan is None else plan.planned_days,
                    employment=EmploymentWindow() if plan is None else plan.employment,
                    legal_daily_norm_hours=legal_norm,
                )
            )
            rows.append(
                AttendanceRow(
                    employee_id=fact.employee_id,
                    full_name=fact.full_name,
                    store_name=fact.store_name,
                    position_name=fact.position_name,
                    norm_work_days=norm.norm_work_days,
                    actual_worked_days=fact.actual_worked_days,
                    off_days=norm.off_days,
                    unauthorized_absences=fact.unauthorized_absences,
                    norm_work_hours=norm.norm_work_hours,
                    pro_rata_ratio=norm.pro_rata_ratio,
                    capped_norm_days=norm.capped_days,
                )
            )

        _audit_log.info(
            "ATTENDANCE_RANGE_REPORT_BUILT",
            extra={
                "actor_id": str(actor.id),
                "period": report_range.key,
                "days": report_range.day_count,
                "rows": len(rows),
                "prorated_rows": sum(1 for row in rows if row.is_partial_period),
            },
        )
        return rows

    def norm_for(
        self,
        *,
        tenant_id: TenantId,
        plan: EmployeePlanFacts,
        report_range: ReportRange,
    ) -> WorkNorm:
        """Tək işçinin norması — ekranın "niyə bu rəqəm?" izahı üçün.

        Sətir qurmadan eyni hesablamanı qaytarır ki, GUI detalları (sıxılan
        gün, plan saatı, pro-rata əmsalı) İKİNCİ DƏFƏ hesablanmasın.
        """
        return calculate_work_norm(
            WorkNormRequest(
                start=report_range.start,
                end=report_range.end,
                plan=plan.planned_days,
                employment=plan.employment,
                legal_daily_norm_hours=self._legal_daily_norm_hours(tenant_id),
            )
        )

    # ------------------------------- FAYL 2 ---------------------------------- #

    def build_bonus_penalty(
        self,
        *,
        actor: Employee,
        facts: list[EmployeeSalesFacts],
        fines: list[Fine],
        now: datetime,
    ) -> BonusPenaltySelection:
        """Premiya & Cərimə sətirləri — LOCK MEXANİZMİ ilə.

        `fines` bir dövrdəki BÜTÜN cərimələri ehtiva edə bilər; süzgəc burada
        tətbiq olunur ki, "neçəsi təxirə salındı" sayğacı da hesablansın.

        TARİX ARALIĞI ARQUMENT DEYİL — VƏ BU, QƏSDƏNDİR. Hansı cərimələrin
        BAXILDIĞINI çağıran tərəf seçir (`FineRepository.list_exportable` +
        aralıq süzgəci); hansının TUTULA BİLDİYİNİ isə yalnız
        `Fine.is_exportable(now=...)` müəyyən edir. Aralığı bura ötürüb
        "bu aralıqdadırsa tut" yazmaq LOCK MEXANİZMİNİ baypas edən yeganə yol
        olardı — ona görə belə bir parametr YOXDUR (Struktur Qərar D).
        """
        self._require_export_permission(actor, now=now)

        included: dict[EmployeeId, list[Fine]] = {}
        deferred: dict[EmployeeId, int] = {}
        already: dict[EmployeeId, int] = {}
        already_periods: set[str] = set()

        for fine in fines:
            if fine.is_exportable(now=now):
                included.setdefault(fine.employee_id, []).append(fine)
            elif fine.exported_period is not None:
                # ÜST-ÜSTƏ DÜŞƏN ARALIQ (modul başlığı): cərimə artıq başqa bir
                # dövrdə tutulub. Sükutla atılmır — sayılır və dövrü adlanır.
                already[fine.employee_id] = already.get(fine.employee_id, 0) + 1
                already_periods.add(fine.exported_period)
            elif self._is_deferred(fine, now=now):
                deferred[fine.employee_id] = deferred.get(fine.employee_id, 0) + 1

        selection = BonusPenaltySelection()
        selection.already_exported_periods = sorted(already_periods)
        for fact in facts:
            employee_fines = included.get(fact.employee_id, [])
            total = Money(
                sum((fine.amount.amount for fine in employee_fines), start=Decimal("0.00"))
            )
            selection.rows.append(
                BonusPenaltyRow(
                    employee_id=fact.employee_id,
                    full_name=fact.full_name,
                    store_name=fact.store_name,
                    gross_sales=fact.gross_sales,
                    earned_points=fact.earned_points,
                    confirmed_fine_count=len(employee_fines),
                    total_fine_amount=total,
                    open_appeal_count=deferred.get(fact.employee_id, 0),
                    already_exported_count=already.get(fact.employee_id, 0),
                )
            )
            selection.included_fines.extend(employee_fines)

        selection.deferred_fine_count = sum(deferred.values())
        selection.already_exported_count = sum(already.values())

        _audit_log.info(
            "BONUS_PENALTY_REPORT_BUILT",
            extra={
                "actor_id": str(actor.id),
                "rows": len(selection.rows),
                "included_fines": len(selection.included_fines),
                "deferred_fines": selection.deferred_fine_count,
                # Üst-üstə düşən aralıq auditdə də görünür: "niyə bu export-da
                # cərimə azdır?" sualı sonradan da cavablana bilməlidir.
                "already_exported_fines": selection.already_exported_count,
                "already_exported_periods": ",".join(selection.already_exported_periods),
            },
        )
        return selection

    def mark_exported(
        self,
        *,
        selection: BonusPenaltySelection,
        period: ReportPeriod | ReportRange,
        now: datetime,
    ) -> int:
        """Fayl UĞURLA yazıldıqdan SONRA çağırılır.

        Ayrı metod olması qəsdəndir: fayl yazma uğursuz olarsa cərimələr
        işarələnməməlidir, əks halda həmin dövr üçün heç vaxt tutulmazdılar.

        `ReportPeriod` VƏ `ReportRange` — hər ikisi qəbul edilir, çünki
        ikisinin də `key` xassəsi var və tam ay üçün onlar EYNİ sətri yazır
        (`ReportRange.key` sinif başlığına bax). Yəni tam-ay export-unun
        `exported_period` dəyəri Faza 7-dən sonra da dəyişmir.
        """
        marked = 0
        for fine in selection.included_fines:
            fine.mark_exported(period=period.key, now=now)
            marked += 1
        return marked

    # ------------------------------- köməkçilər ------------------------------ #

    def _max_range_days(self, tenant_id: TenantId) -> int:
        """ROOT həddi; port yoxdursa və ya dəyər mənasızdırsa fallback.

        `<= 0` dəyər HƏR aralığı bloklardı — yəni ROOT-dakı bir yazı səhvi
        bütün export axınını dayandırardı (`work_norm._usable_cap` ilə eyni
        müdafiə).
        """
        if self._limits is None:
            return FALLBACK_RANGE_MAX_DAYS
        value = self._limits.get_int(
            tenant_id, SystemLimitKey.REPORT_RANGE_MAX_DAYS.value, FALLBACK_RANGE_MAX_DAYS
        )
        return value if value > 0 else FALLBACK_RANGE_MAX_DAYS

    def _legal_daily_norm_hours(self, tenant_id: TenantId) -> Decimal:
        """Gündəlik hüquqi norma — `overtime_tracking.py` ilə EYNİ ROOT açarı.

        Açar QƏSDƏN təkrar istifadə olunur: ikinci açar yaradılsaydı, Root
        birini dəyişib digərini unudanda davamiyyət hesabatı ilə aşım jurnalı
        SÜKUTLA fərqlənərdi (bax `domain/work_norm.py` — "ZİDDİYYƏT QƏRARI").
        """
        if self._limits is None:
            return FALLBACK_LEGAL_DAILY_NORM_HOURS
        raw = self._limits.get_str(
            tenant_id,
            SystemLimitKey.OVERTIME_DAILY_NORM_HOURS.value,
            str(FALLBACK_LEGAL_DAILY_NORM_HOURS),
        )
        try:
            value = Decimal(str(raw).strip().replace(",", "."))
        except (InvalidOperation, ValueError, AttributeError):
            return FALLBACK_LEGAL_DAILY_NORM_HOURS
        return value if value > 0 else FALLBACK_LEGAL_DAILY_NORM_HOURS

    @staticmethod
    def _is_deferred(fine: Fine, *, now: datetime) -> bool:
        """Cərimə TƏXİRƏ salınıbmı (yoxsa tamamilə kənardadır).

        Fərq vacibdir: pəncərəsi açıq cərimə növbəti ay yenidən baxılacaq və
        istifadəçiyə "gözləyir" kimi göstərilməlidir. `REVERSED` və artıq
        export olunmuş cərimə isə heç vaxt qayıtmayacaq — onları "gözləyir"
        saymaq yanlış gözlənti yaradardı.
        """
        return fine.exported_period is None and fine.is_appeal_window_open(now=now)

    @staticmethod
    def _require_export_permission(actor: Employee, *, now: datetime) -> None:
        if not actor.has_permission(EXPORT_REPORTS_FLAG, now=now):
            _audit_log.warning(
                "REPORT_EXPORT_DENIED",
                extra={"actor_id": str(actor.id), "flag": EXPORT_REPORTS_FLAG},
            )
            raise ReportPermissionError(
                f"«{EXPORT_REPORTS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


__all__ = [
    "EXPORT_REPORTS_FLAG",
    "FALLBACK_LEGAL_DAILY_NORM_HOURS",
    "FALLBACK_RANGE_MAX_DAYS",
    "AttendanceRow",
    "BonusPenaltyRow",
    "BonusPenaltySelection",
    "EmployeeAttendanceFacts",
    "EmployeePlanFacts",
    "EmployeeSalesFacts",
    "MonthlyReportUseCase",
    "PlanFactProvider",
    "ReportFactProvider",
    "ReportPeriod",
    "ReportPeriodError",
    "ReportPermissionError",
    "ReportRange",
    "ReportRangeTooLongError",
]
