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

──────────────────────────────────────────────────────────────────────────────
BU MODUL FAYL YAZMIR
──────────────────────────────────────────────────────────────────────────────
Burada yalnız SƏTİRLƏR hesablanır. `.xlsx` yazma
`infrastructure/reporting/excel.py`-dədir — beləliklə hesabat məntiqi
openpyxl olmadan, adi siyahı müqayisəsi ilə test oluna bilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.domain.entities.fine import Fine
from src.domain.value_objects.money import Money
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.domain.entities.employee import Employee
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

EXPORT_REPORTS_FLAG = "can_export_reports"

MONTHS_IN_YEAR = 12
#: Sistemin mövcud olduğu ən erkən il — yazı səhvini (məs. `20026`) tutur.
EARLIEST_REPORT_YEAR = 2000


class ReportPermissionError(KompasOSError):
    """Hesabat çıxarmaq üçün səlahiyyət yoxdur."""

    user_message = "Hesabat çıxarmaq səlahiyyətiniz yoxdur."


class ReportPeriodError(KompasOSError):
    """Hesabat dövrü yararsızdır."""

    user_message = "Hesabat dövrü düzgün deyil."


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

    def __post_init__(self) -> None:
        for label, value in (
            ("Norma iş günləri", self.norm_work_days),
            ("Faktiki işlənilən gün", self.actual_worked_days),
            ("Off-day sayı", self.off_days),
            ("İcazəsiz qayıb", self.unauthorized_absences),
        ):
            if value < 0:
                raise ReportPeriodError(f"{label} mənfi ola bilməz: {value}")


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

    @property
    def has_deferred_fines(self) -> bool:
        """Ekranda "açıq pəncərə" nişanı göstərilməlidirmi."""
        return self.open_appeal_count > 0


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


class MonthlyReportUseCase:
    """İki hesabatın sətirlərini hazırlayır — fayl yazmadan.

    VƏZİYYƏTSİZDİR və `Clock` portu ALMIR: hər metod `now`-u açıq arqument
    kimi qəbul edir. Səbəb LOCK MEXANİZMİ-dir — "hansı an üçün hesablanır"
    sualı hesabatın nəticəsini dəyişir (72 saatlıq pəncərə), ona görə həmin
    an gizli asılılıq deyil, GÖRÜNƏN parametr olmalıdır.
    """

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

        `fines` bir aydakı BÜTÜN cərimələri ehtiva edə bilər; süzgəc burada
        tətbiq olunur ki, "neçəsi təxirə salındı" sayğacı da hesablansın.
        """
        self._require_export_permission(actor, now=now)

        included: dict[EmployeeId, list[Fine]] = {}
        deferred: dict[EmployeeId, int] = {}

        for fine in fines:
            if fine.is_exportable(now=now):
                included.setdefault(fine.employee_id, []).append(fine)
            elif self._is_deferred(fine, now=now):
                deferred[fine.employee_id] = deferred.get(fine.employee_id, 0) + 1

        selection = BonusPenaltySelection()
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
                )
            )
            selection.included_fines.extend(employee_fines)

        selection.deferred_fine_count = sum(deferred.values())

        _audit_log.info(
            "BONUS_PENALTY_REPORT_BUILT",
            extra={
                "actor_id": str(actor.id),
                "rows": len(selection.rows),
                "included_fines": len(selection.included_fines),
                "deferred_fines": selection.deferred_fine_count,
            },
        )
        return selection

    def mark_exported(
        self, *, selection: BonusPenaltySelection, period: ReportPeriod, now: datetime
    ) -> int:
        """Fayl UĞURLA yazıldıqdan SONRA çağırılır.

        Ayrı metod olması qəsdəndir: fayl yazma uğursuz olarsa cərimələr
        işarələnməməlidir, əks halda həmin ay üçün heç vaxt tutulmazdılar.
        """
        marked = 0
        for fine in selection.included_fines:
            fine.mark_exported(period=period.key, now=now)
            marked += 1
        return marked

    # ------------------------------- köməkçilər ------------------------------ #

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
    "AttendanceRow",
    "BonusPenaltyRow",
    "BonusPenaltySelection",
    "EmployeeAttendanceFacts",
    "EmployeeSalesFacts",
    "MonthlyReportUseCase",
    "ReportFactProvider",
    "ReportPeriod",
    "ReportPeriodError",
    "ReportPermissionError",
]
