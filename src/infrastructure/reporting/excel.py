"""Excel Export Engine — İKİ AYRI `.xlsx` faylı (spesifikasiya bölmə 6).

──────────────────────────────────────────────────────────────────────────────
İKİ FAYL, İKİ METOD — BİR "HAMISI BİR YERDƏ" METODU YOXDUR
──────────────────────────────────────────────────────────────────────────────
`write_attendance()` və `write_bonus_penalty()` AYRI metodlardır və ortaq
"hər ikisini yaz" metodu QƏSDƏN yoxdur. Bölmə 6: iki fayl "ayrı məqsədə
xidmət edir və QARIŞDIRILMAMALIDIR". Bir metod hər iki vərəqi eyni iş
kitabına yazsaydı, mühasib cərimə sütununu maaş cədvəlinin yanında görərdi —
məhz spesifikasiyanın bağladığı səhv.

──────────────────────────────────────────────────────────────────────────────
MƏBLƏĞ NİYƏ `Decimal` KİMİ YAZILIR, MƏTN KİMİ YOX
──────────────────────────────────────────────────────────────────────────────
Mühasib faylda cəm çıxarır. Məbləğ "12.50 AZN" mətni olsaydı, `SUM()`
sıfır qaytarardı və səhv sükutla keçərdi. Ona görə hüceyrə ƏDƏD-dir,
"AZN" isə format maskasındadır (`#,##0.00" AZN"`).

──────────────────────────────────────────────────────────────────────────────
FAYL ADI NİYƏ DÖVR AÇARINI DAŞIYIR
──────────────────────────────────────────────────────────────────────────────
`Davamiyyet_2026-08.xlsx` — iki fərqli ayın faylı eyni qovluqda qarışmasın.
Latın hərfləri ilə: fayl adı Windows/e-poçt/1C arasında gəzir və `ə/ı/ş`
bəzi köhnə sistemlərdə pozulur. Fayl DAXİLİ isə tam Azərbaycan dilindədir.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.reporting import (
        AttendanceRow,
        BonusPenaltyRow,
        ReportPeriod,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: FAYL 1 sütunları — bölmə 6-dakı ardıcıllıqla.
ATTENDANCE_HEADERS: Final[tuple[str, ...]] = (
    "İşçi ID",
    "Ad Soyad",
    "Mağaza",
    "Vəzifə",
    "Norma İş Günləri",
    "Faktiki İşlənilən Gün Sayı",
    "Off-Day Sayı",
    "İcazəsiz Qayıb",
)

#: FAYL 2 sütunları — bölmə 6-dakı ardıcıllıqla.
#: Sonuncu sütun spesifikasiyada sadalanmır, lakin oradakı tələbdən doğur:
#: "hər sətir üçün «etiraz pəncərəsi vəziyyəti» (bağlı/açıq) aydın göstərilir".
BONUS_PENALTY_HEADERS: Final[tuple[str, ...]] = (
    "İşçi ID",
    "Ad Soyad",
    "Mağaza",
    "Brutto Satış Məbləği",
    "Qazanılan Satış Xalları",
    "Təsdiqlənmiş Cərimə Sayı",
    "Premiyadan Tutulacaq Yekun Cərimə Məbləği",
    "Etiraz Pəncərəsi",
)

_MONEY_FORMAT: Final[str] = '#,##0.00" AZN"'
_HEADER_FILL = PatternFill("solid", fgColor="0B1D3A")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_MIN_COLUMN_WIDTH: Final[int] = 12
_MAX_COLUMN_WIDTH: Final[int] = 46


class ExcelExportError(KompasOSError):
    """Fayl yazıla bilmədi."""

    user_message = "Hesabat faylı yazıla bilmədi. Qovluğa yazma icazəsini yoxlayın."


class ExcelReportWriter:
    """İki aylıq hesabatı `.xlsx` kimi yazır."""

    def __init__(self, *, output_dir: Path) -> None:
        self._output_dir = output_dir

    # ------------------------------- FAYL 1 ---------------------------------- #

    def write_attendance(self, rows: list[AttendanceRow], *, period: ReportPeriod) -> Path:
        """Aylıq Davamiyyət Hesabatı — YALNIZ fiks maaş üçün."""
        workbook = Workbook()
        sheet = workbook.active
        if sheet is None:  # pragma: no cover — openpyxl həmişə vərəq yaradır
            raise ExcelExportError("Boş iş kitabı yaradıla bilmədi")
        sheet.title = "Davamiyyət"

        self._write_headers(sheet, ATTENDANCE_HEADERS)
        for row in rows:
            sheet.append(
                [
                    str(row.employee_id),
                    row.full_name,
                    row.store_name,
                    row.position_name,
                    row.norm_work_days,
                    row.actual_worked_days,
                    row.off_days,
                    row.unauthorized_absences,
                ]
            )

        self._add_period_note(
            sheet,
            column_count=len(ATTENDANCE_HEADERS),
            note=(
                f"{period.label_az()} — yalnız fiks maaş uçotu üçün. "
                f"Cərimə məlumatı bu faylda YOXDUR."
            ),
        )
        self._finalize(sheet, len(ATTENDANCE_HEADERS))
        return self._save(workbook, f"Davamiyyet_{period.key}.xlsx", report="attendance")

    # ------------------------------- FAYL 2 ---------------------------------- #

    def write_bonus_penalty(self, rows: list[BonusPenaltyRow], *, period: ReportPeriod) -> Path:
        """Premiya & Cərimə Hesabatı — cərimələr PREMİYADAN tutulur."""
        workbook = Workbook()
        sheet = workbook.active
        if sheet is None:  # pragma: no cover
            raise ExcelExportError("Boş iş kitabı yaradıla bilmədi")
        sheet.title = "Premiya və Cərimə"

        self._write_headers(sheet, BONUS_PENALTY_HEADERS)
        for row in rows:
            sheet.append(
                [
                    str(row.employee_id),
                    row.full_name,
                    row.store_name,
                    row.gross_sales.amount,
                    row.earned_points,
                    row.confirmed_fine_count,
                    row.total_fine_amount.amount,
                    (
                        f"{row.open_appeal_count} cərimə gözləyir"
                        if row.has_deferred_fines
                        else "Bağlı"
                    ),
                ]
            )

        # Pul sütunları: D (brutto satış) və G (yekun cərimə).
        for column in ("D", "G"):
            for cell in sheet[column][1:]:
                cell.number_format = _MONEY_FORMAT

        self._add_period_note(
            sheet,
            column_count=len(BONUS_PENALTY_HEADERS),
            note=(
                f"{period.label_az()} — cərimələr ƏSAS MAAŞDAN DEYİL, aylıq "
                f"PREMİYADAN kəsilir. Etiraz pəncərəsi açıq olan və ləğv "
                f"edilmiş cərimələr bu fayla DAXİL EDİLMƏYİB."
            ),
        )
        self._finalize(sheet, len(BONUS_PENALTY_HEADERS))
        return self._save(workbook, f"Premiya_Cerime_{period.key}.xlsx", report="bonus_penalty")

    # ------------------------------- köməkçilər ------------------------------ #

    @staticmethod
    def _write_headers(sheet: Worksheet, headers: tuple[str, ...]) -> None:
        sheet.append(list(headers))
        for cell in sheet[1]:
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.freeze_panes = "A2"

    @staticmethod
    def _add_period_note(sheet: Worksheet, *, column_count: int, note: str) -> None:
        """Faylın altına izah sətri — faylı açan mühasib məqsədi görsün.

        Başlıqda deyil, ALTDA: yuxarıda olsaydı `SUM()` və filtr aralıqları
        sürüşərdi və mühasibin adi Excel vərdişləri pozulardı.
        """
        sheet.append([])
        sheet.append([note])
        last_row = sheet.max_row
        sheet.merge_cells(
            start_row=last_row, start_column=1, end_row=last_row, end_column=column_count
        )
        sheet.cell(row=last_row, column=1).font = Font(italic=True)

    @staticmethod
    def _finalize(sheet: Worksheet, column_count: int) -> None:
        """Sütun enlərini məzmuna görə tənzimləyir və avtofiltr qoyur."""
        for index in range(1, column_count + 1):
            letter = get_column_letter(index)
            longest = max(
                (len(str(cell.value)) for cell in sheet[letter] if cell.value is not None),
                default=_MIN_COLUMN_WIDTH,
            )
            width = min(max(longest + 2, _MIN_COLUMN_WIDTH), _MAX_COLUMN_WIDTH)
            sheet.column_dimensions[letter].width = width

        # Filtr YALNIZ məlumat aralığına qoyulur — izah sətri daxil edilsəydi,
        # süzgəc onu da gizlədə bilərdi.
        data_rows = max(sheet.max_row - 2, 1)
        sheet.auto_filter.ref = f"A1:{get_column_letter(column_count)}{data_rows}"

    def _save(self, workbook: Workbook, filename: str, *, report: str) -> Path:
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            target = self._output_dir / filename
            workbook.save(target)
        except OSError as exc:
            raise ExcelExportError(
                f"Hesabat faylı yazıla bilmədi: {filename}",
                context={"path": str(self._output_dir), "error": str(exc)},
            ) from exc

        _audit_log.info("REPORT_FILE_WRITTEN", extra={"report": report, "path": str(target)})
        return target


__all__ = [
    "ATTENDANCE_HEADERS",
    "BONUS_PENALTY_HEADERS",
    "ExcelExportError",
    "ExcelReportWriter",
]
