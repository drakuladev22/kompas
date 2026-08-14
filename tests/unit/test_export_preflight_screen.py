"""Export təcrübəsinin GUI tərəfi — kompas1.md Faza 8 (A, D, E, F, G).

İKİ təbəqə ayrıca yoxlanılır (`test_bulk_operations_screen.py` naxışı):

    * KÖMƏKÇİ funksiyalar (`_finding_rows`, `_comparison_rows`,
      `_correction_rows`, `_role_rows`, `_row_values`) və KONTROLLER metodları
      — Qt TƏLƏB ETMİR, sahtə `Session`/`Context` ilə birbaşa çağırılır;
    * ekranın ÖZÜ (`ReportExportScreen`, `ExportCorrectionDialog`) — Qt TƏLƏB
      EDİR, çünki real `Card`/`DataTable`/`QComboBox` qurulur. HƏR İKİ TEMA
      (light + dark) yoxlanılır: dizayn qapısı hər iki rejimi tələb edir.

Dialoqun `.exec()`-i HEÇ VAXT çağırılmır (layihə boyu heç bir test bunu
etmir): modal event loop-u avtomatik bağlayan heç nə yoxdur.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import pytest

from src.application.use_cases.export_preflight import (
    EXPORT_CORRECTIONS_FLAG,
    EmployeeRosterStatus,
    ExportPreflightReview,
    MetricDelta,
    RoleOption,
)
from src.application.use_cases.reporting import (
    EXPORT_REPORTS_FLAG,
    AttendanceRow,
    ReportRange,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.export_validation import (
    ExportValidationCode,
    ExportValidationFinding,
)
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.export_corrections import (
    EXPORT_TYPE_ATTENDANCE,
    EXPORT_TYPE_BONUS_PENALTY,
    ExportCorrection,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    TenantId,
    new_employee_id,
)
from src.presentation import preview_data
from src.presentation.controllers.report_export import (
    ReportExportController,
    _comparison_caption,
    _comparison_rows,
    _correction_rows,
    _finding_rows,
    _role_rows,
    _row_values,
)
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)
AUGUST: Final = ReportRange(date(2026, 8, 1), date(2026, 8, 31))


class _DeniedError(KompasOSError):
    """`ReportPermissionError` müqaviləsinin yerli əvəzi."""

    user_message = "Hesabat çıxarmaq səlahiyyətiniz yoxdur."


# --------------------------------------------------------------------------- #
# Aktorlar
# --------------------------------------------------------------------------- #


def _employee(*, flags: tuple[str, ...]) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    for flag in flags:
        position.grant(PermissionFlag(code=flag, category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )


def _hr_admin() -> Employee:
    return _employee(flags=(EXPORT_REPORTS_FLAG, EXPORT_CORRECTIONS_FLAG))


def _reader_only() -> Employee:
    """Hesabatı görür, DÜZƏLİŞ flag-i YOXDUR — düyməni GÖRMƏMƏLİDİR."""
    return _employee(flags=(EXPORT_REPORTS_FLAG,))


# --------------------------------------------------------------------------- #
# Məlumat qurucuları
# --------------------------------------------------------------------------- #


def _row(
    *,
    employee_id: EmployeeId | None = None,
    name: str = "Rəşad Məmmədov",
    absences: int = 2,
) -> AttendanceRow:
    return AttendanceRow(
        employee_id=employee_id or new_employee_id(),
        full_name=name,
        store_name="Bellona 28 May",
        position_name="Satıcı",
        norm_work_days=22,
        actual_worked_days=20,
        off_days=8,
        unauthorized_absences=absences,
    )


def _correction(employee_id: EmployeeId) -> ExportCorrection:
    return ExportCorrection(
        tenant_id=TENANT,
        export_type=EXPORT_TYPE_ATTENDANCE,
        employee_id=employee_id,
        target_date=date(2026, 8, 4),
        field="FAKTIKI_GUN",
        old_value="34",
        new_value="31",
        reason="Kassa sistemində təkrar giriş qeydi aşkarlandı",
        corrected_by=new_employee_id(),
        corrected_at=NOW,
    )


def _review(
    *,
    rows: list[AttendanceRow] | None = None,
    findings: tuple[ExportValidationFinding, ...] = (),
    deltas: tuple[MetricDelta, ...] = (),
    corrections: tuple[ExportCorrection, ...] = (),
    previous_range: ReportRange | None = None,
) -> ExportPreflightReview:
    return ExportPreflightReview(
        rows=list(rows or []),
        findings=findings,
        deltas=deltas,
        role_options=(RoleOption(code="SATICI", name_az="Satıcı"),),
        corrections=corrections,
        notes={},
        previous_range=previous_range,
        total_row_count=len(rows or []),
    )


# --------------------------------------------------------------------------- #
# Sahtələr — Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


class _PreflightUseCase:
    def __init__(
        self,
        *,
        review: ExportPreflightReview | None = None,
        review_error: Exception | None = None,
        record_error: Exception | None = None,
    ) -> None:
        self.review_result = review or _review(rows=[_row()])
        self.review_error = review_error
        self.record_error = record_error
        self.review_calls: list[dict[str, Any]] = []
        self.recorded: list[dict[str, Any]] = []

    def review(self, **kwargs: Any) -> ExportPreflightReview:
        self.review_calls.append(kwargs)
        if self.review_error is not None:
            raise self.review_error
        return self.review_result

    def record_correction(self, **kwargs: Any) -> Any:
        if self.record_error is not None:
            raise self.record_error
        self.recorded.append(kwargs)
        return object()

    @staticmethod
    def previous_range(report_range: ReportRange) -> ReportRange:
        from src.application.use_cases.export_preflight import ExportPreflightUseCase

        return ExportPreflightUseCase.previous_range(report_range)


class _Reports:
    """`MonthlyReportUseCase` sahtəsi.

    `resolve_month`/`resolve_range` REAL sinifə HƏVALƏ EDİLİR (öz nüsxəsi
    yazılmır): aralıq həddi (`REPORT_RANGE_MAX_DAYS`) və `ReportRange`
    invariantları məhz orada yaşayır və testin onları təkrarlaması qapını kor
    edərdi.
    """

    def __init__(
        self,
        rows: list[AttendanceRow] | None = None,
        *,
        limits: Any = None,
        selection: Any = None,
    ) -> None:
        self.rows = list(rows or [_row()])
        self.selection = selection
        self.marked: list[tuple[Any, str]] = []
        from src.application.use_cases.reporting import MonthlyReportUseCase

        self._real = MonthlyReportUseCase(limits=limits)

    def build_attendance_rows_for_range(self, **kwargs: Any) -> list[AttendanceRow]:
        return list(self.rows)

    def resolve_month(self, *, year: int, month: int) -> ReportRange:
        return self._real.resolve_month(year=year, month=month)

    def resolve_range(self, *, tenant_id: Any, start: date, end: date) -> ReportRange:
        return self._real.resolve_range(tenant_id=tenant_id, start=start, end=end)

    def build_bonus_penalty(self, *, actor: Any, facts: Any, fines: Any, now: Any) -> Any:
        """LOCK QƏRARI SAHTƏLƏNMİR — REAL use case çağırılır.

        Sahtə nəticə qaytarsaydı, «açıq etiraz pəncərəsindəki cərimə xaric
        edilir» testi yalnız sahtənin doldurulmasını yoxlayardı.
        """
        self.bonus_facts = list(facts)
        self.bonus_fines = list(fines)
        return self._real.build_bonus_penalty(actor=actor, facts=facts, fines=fines, now=now)

    def mark_exported(self, *, selection: Any, period: Any, now: Any) -> int:
        marked = self._real.mark_exported(selection=selection, period=period, now=now)
        self.marked.append((selection, period.key))
        return marked


class _ReportFacts:
    def __init__(self, sales: list[Any] | None = None) -> None:
        self.sales = list(sales or [])

    def attendance_facts(self, tenant_id: Any, **kwargs: Any) -> list[Any]:
        return []

    def plan_facts(self, tenant_id: Any, **kwargs: Any) -> list[Any]:
        return []

    def sales_facts(self, tenant_id: Any, **kwargs: Any) -> list[Any]:
        return list(self.sales)


class _FineRepo:
    """`RangeScopedFineReader` sahtəsi — aralığı QEYDƏ ALIR."""

    def __init__(self, fines: list[Any] | None = None) -> None:
        self.fines = list(fines or [])
        self.calls: list[tuple[date, date]] = []

    def list_in_range(self, tenant_id: Any, *, start: date, end: date) -> list[Any]:
        self.calls.append((start, end))
        return list(self.fines)


class _Uow:
    def __init__(self, fines: _FineRepo) -> None:
        self.fines = fines


class _RosterRepo:
    def __init__(self, entries: list[EmployeeRosterStatus] | None = None) -> None:
        self.entries = list(entries or [])

    def roster_status(self, tenant_id: Any, **kwargs: Any) -> list[EmployeeRosterStatus]:
        return list(self.entries)


class _Limits:
    def __init__(self, value: int = 10) -> None:
        self._value = value

    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        return self._value


class _Session:
    def __init__(
        self,
        *,
        preflight: _PreflightUseCase,
        reports: _Reports | None = None,
        roster: _RosterRepo | None = None,
        report_facts: _ReportFacts | None = None,
        fines: _FineRepo | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.export_preflight = preflight
        self.reports = reports or _Reports()
        self.report_facts = report_facts or _ReportFacts()
        self.export_roster = roster or _RosterRepo()
        self.uow = _Uow(fines or _FineRepo())
        self.limits = _Limits()
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: _Session) -> None:
        self._session = session
        self.tenant_id = TENANT
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


class _FakeSignal:
    """`Signal.connect()` müqaviləsinin minimal əvəzi.

    Qt siqnalı sahtələnir, çünki `attach()` YALNIZ bağlama qurur — testlər
    isə kontroller metodlarını BİRBAŞA çağırır. Real `QObject` qurmaq bu
    testlərə Qt asılılığı gətirərdi, halbuki yoxlanan məntiq Qt-siz işləyir.
    """

    def __init__(self) -> None:
        self.slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self.slots.append(slot)


class _ScreenStub:
    """`ReportExportScreen`-in setter API-sinin sahtəsi (Qt-siz)."""

    def __init__(
        self,
        *,
        role: str = "",
        active_report: str = "attendance",
        date_range: tuple[str, str] = ("", ""),
    ) -> None:
        self.theme = object()
        self.preflight_requested = _FakeSignal()
        self.export_requested = _FakeSignal()
        self.role_filter_changed = _FakeSignal()
        self.range_changed = _FakeSignal()
        self.correction_requested = _FakeSignal()
        self.role = role
        self.date_range = date_range
        self._active_report = active_report
        self.role_options: list[tuple[list[dict[str, str]], str]] = []
        self.findings: list[list[dict[str, str]]] = []
        self.comparisons: list[tuple[list[dict[str, str]], str]] = []
        self.corrections: list[list[dict[str, str]]] = []
        self.messages: list[tuple[str, bool]] = []
        self.range_messages: list[tuple[str, bool]] = []
        self.range_selections: list[tuple[bool, str, str]] = []
        self.lock_summaries: list[tuple[int, int, str]] = []
        self.correction_access: list[bool] = []
        self.row_values: dict[str, dict[str, str]] = {}
        self.section_shown = 0

    # --- ekranın oxunan tərəfi --- #
    def selected_role(self) -> str:
        return self.role

    def selected_range(self) -> tuple[str, str]:
        return self.date_range

    def active_report(self) -> str:
        return self._active_report

    def current_value(self, employee_id: object, field: str) -> str | None:
        return self.row_values.get(str(employee_id), {}).get(field)

    # --- setter API --- #
    def set_range_selection(self, *, custom: bool, start: str = "", end: str = "") -> None:
        self.range_selections.append((custom, start, end))

    def set_range_message(self, message: str, *, error: bool = False) -> None:
        self.range_messages.append((message, error))

    def set_lock_summary(
        self, deferred_fines: int, *, already_exported: int = 0, overlap_notice: str = ""
    ) -> None:
        self.lock_summaries.append((deferred_fines, already_exported, overlap_notice))

    def set_role_options(self, options: list[dict[str, str]], *, selected: str = "") -> None:
        self.role_options.append((options, selected))

    def set_validation_findings(self, rows: list[dict[str, str]]) -> None:
        self.findings.append(rows)

    def set_period_comparison(self, rows: list[dict[str, str]], *, caption: str = "") -> None:
        self.comparisons.append((rows, caption))

    def set_corrections(self, rows: list[dict[str, str]]) -> None:
        self.corrections.append(rows)

    def set_correction_access(self, *, allowed: bool) -> None:
        self.correction_access.append(allowed)

    def set_preflight_message(self, message: str, *, error: bool = False) -> None:
        self.messages.append((message, error))

    def set_row_values(self, values: dict[str, dict[str, str]]) -> None:
        self.row_values = values

    def show_preflight_section(self) -> None:
        self.section_shown += 1


def _controller(session: _Session, actor: Employee | None = None) -> ReportExportController:
    return ReportExportController(_Context(session), actor or _hr_admin())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Sətir çeviriciləri — Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


def test_finding_rows_carry_the_rule_label_subject_and_detail() -> None:
    review = _review(
        findings=(
            ExportValidationFinding(
                code=ExportValidationCode.EXCESS_WORK_DAYS,
                subject_az="Kamran Vəliyev",
                detail_az="34 iş günü qeydə alınıb...",
                employee_id=new_employee_id(),
            ),
        )
    )

    rows = _finding_rows(review)

    assert rows == [
        {
            "rule": "Aralıqdan çox iş günü",
            "subject": "Kamran Vəliyev",
            "detail": "34 iş günü qeydə alınıb...",
        }
    ]


def test_comparison_rows_mark_only_the_significant_delta() -> None:
    review = _review(
        deltas=(
            MetricDelta("unauthorized_absences", "İcazəsiz qayıb", 17, 14, True, True),
            MetricDelta("off_days", "Off-day sayı", 180, 179, True, False),
        )
    )

    rows = _comparison_rows(review)

    assert rows[0]["delta"] == "+3"
    assert rows[0]["significant"] == "1"
    assert rows[1]["significant"] == ""


def test_comparison_rows_are_empty_when_there_is_no_baseline() -> None:
    """Keçən dövr yoxdursa cədvəl QURULMUR — sıfırlar «keçən dövr sıfır idi»
    kimi oxunardı."""
    review = _review(
        deltas=(MetricDelta("unauthorized_absences", "İcazəsiz qayıb", 17, 0, False, False),)
    )

    assert _comparison_rows(review) == []
    assert "məlumat yoxdur" in _comparison_caption(review)


def test_comparison_caption_names_the_previous_range() -> None:
    review = _review(previous_range=ReportRange(date(2026, 7, 1), date(2026, 7, 31)))

    assert "İyul 2026" in _comparison_caption(review)


def test_correction_rows_resolve_the_employee_name() -> None:
    row = _row(name="Kamran Vəliyev")
    review = _review(rows=[row], corrections=(_correction(row.employee_id),))

    rows = _correction_rows(review, names={row.employee_id: "Kamran Vəliyev"})

    assert rows[0]["employee"] == "Kamran Vəliyev"
    assert rows[0]["date"] == "2026-08-04"
    assert rows[0]["change"] == "Faktiki işlənilən gün: 34 → 31"
    assert rows[0]["reason"].startswith("Kassa")


def test_role_rows_are_unique_and_sorted() -> None:
    roster = [
        EmployeeRosterStatus(new_employee_id(), True, "SATICI", "Satıcı"),
        EmployeeRosterStatus(new_employee_id(), True, "MAGAZA_MENECERI", "Mağaza Meneceri"),
        EmployeeRosterStatus(new_employee_id(), True, "SATICI", "Satıcı"),
        EmployeeRosterStatus(new_employee_id(), True, "", "—"),
    ]

    assert _role_rows(roster) == [
        {"code": "MAGAZA_MENECERI", "name": "Mağaza Meneceri"},
        {"code": "SATICI", "name": "Satıcı"},
    ]


def test_row_values_use_the_same_field_codes_as_the_correction_catalog() -> None:
    """Açar uyğunluğu təsadüf DEYİL — düzəliş dialoqu bu sözlükdən oxuyur."""
    from src.domain.value_objects.export_corrections import CORRECTABLE_FIELDS, NOTE_FIELD

    row = _row()
    values = _row_values(_review(rows=[row]))

    numeric = {code for code, (_label, is_numeric) in CORRECTABLE_FIELDS.items() if is_numeric}
    assert set(values[str(row.employee_id)]) == numeric
    assert NOTE_FIELD not in values[str(row.employee_id)]


# --------------------------------------------------------------------------- #
# Kontroller — Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


def test_flagless_user_never_gets_the_correction_section() -> None:
    """GÖRMƏK = SƏLAHİYYƏTİN OLMASI — düymə söndürülmür, bölmə GİZLƏNİR."""
    session = _Session(preflight=_PreflightUseCase())
    screen = _ScreenStub()

    _controller(session, _reader_only()).attach(screen)  # type: ignore[arg-type]

    assert screen.correction_access == [False]


def test_the_flag_holder_gets_the_correction_section() -> None:
    session = _Session(preflight=_PreflightUseCase())
    screen = _ScreenStub()

    _controller(session, _hr_admin()).attach(screen)  # type: ignore[arg-type]

    assert screen.correction_access == [True]


def test_attach_loads_the_role_catalog() -> None:
    roster = _RosterRepo([EmployeeRosterStatus(new_employee_id(), True, "SATICI", "Satıcı")])
    session = _Session(preflight=_PreflightUseCase(), roster=roster)
    screen = _ScreenStub()

    _controller(session).attach(screen)  # type: ignore[arg-type]

    assert screen.role_options[-1][0] == [{"code": "SATICI", "name": "Satıcı"}]


def test_preflight_renders_findings_comparison_and_corrections() -> None:
    row = _row()
    review = _review(
        rows=[row],
        findings=(
            ExportValidationFinding(
                code=ExportValidationCode.ZERO_ACTIVITY_CONFLICT,
                subject_az="Nigar Əliyeva",
                detail_az="22 gün planlaşdırılıb...",
            ),
        ),
        deltas=(MetricDelta("unauthorized_absences", "İcazəsiz qayıb", 17, 14, True, True),),
        corrections=(_correction(row.employee_id),),
        previous_range=ReportRange(date(2026, 7, 1), date(2026, 7, 31)),
    )
    session = _Session(preflight=_PreflightUseCase(review=review))
    screen = _ScreenStub()

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert len(screen.findings[-1]) == 1
    assert len(screen.comparisons[-1][0]) == 1
    assert len(screen.corrections[-1]) == 1
    assert screen.row_values[str(row.employee_id)]["FAKTIKI_GUN"] == "20"


def test_preflight_passes_the_selected_role_to_the_use_case() -> None:
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub(role="SATICI")

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert use_case.review_calls[-1]["role_code"] == "SATICI"


def test_preflight_requests_an_equal_length_previous_period() -> None:
    """Kontroller ƏVVƏLKİ aralığı use case-in öz düsturundan alır."""
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub()

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert "previous_rows" in use_case.review_calls[-1]


def test_a_domain_error_is_shown_and_the_section_is_revealed() -> None:
    """Xəta SÜKUTLA udulmur — mesaj görünən bölmədə göstərilir."""
    session = _Session(preflight=_PreflightUseCase(review_error=_DeniedError("yox")))
    screen = _ScreenStub()

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert screen.messages[-1] == ("Hesabat çıxarmaq səlahiyyətiniz yoxdur.", True)
    assert screen.section_shown == 1


def test_an_unexpected_error_never_leaks_its_raw_text() -> None:
    session = _Session(preflight=_PreflightUseCase(review_error=RuntimeError("psycopg detail")))
    screen = _ScreenStub()

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    message, is_error = screen.messages[-1]
    assert is_error is True
    assert "psycopg" not in message


def test_an_empty_role_filter_result_does_not_crash_the_screen() -> None:
    """Rol filtri boş nəticə verəndə ekran normal şəkildə boş göstərilir."""
    session = _Session(preflight=_PreflightUseCase(review=_review(rows=[])))
    screen = _ScreenStub(role="KAMERA_NEZARETCISI")

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert screen.findings[-1] == []
    assert screen.corrections[-1] == []
    assert screen.row_values == {}


def test_a_correction_is_submitted_with_the_visible_old_value() -> None:
    row = _row()
    use_case = _PreflightUseCase(review=_review(rows=[row]))
    session = _Session(preflight=use_case)
    screen = _ScreenStub()
    screen.row_values = {str(row.employee_id): {"FAKTIKI_GUN": "20"}}

    _controller(session)._submit_correction(
        screen,  # type: ignore[arg-type]
        employee_id=str(row.employee_id),
        target_date="2026-08-04",
        field_code="FAKTIKI_GUN",
        new_value="18",
        reason="Kassa sistemində təkrar giriş qeydi aşkarlandı",
    )

    assert use_case.recorded[-1]["old_value"] == "20"
    assert use_case.recorded[-1]["new_value"] == "18"
    assert session.commits >= 1


def test_a_correction_refreshes_the_list_afterwards() -> None:
    """CLAUDE.md §6 — hər yazıdan SONRA siyahı yenidən oxunur."""
    row = _row()
    use_case = _PreflightUseCase(review=_review(rows=[row]))
    session = _Session(preflight=use_case)
    screen = _ScreenStub()

    _controller(session)._submit_correction(
        screen,  # type: ignore[arg-type]
        employee_id=str(row.employee_id),
        target_date="2026-08-04",
        field_code="FAKTIKI_GUN",
        new_value="18",
        reason="Kassa sistemində təkrar giriş qeydi aşkarlandı",
    )

    assert use_case.review_calls, "düzəlişdən sonra doğrulama yenidən işləməlidir"


def test_a_rejected_correction_shows_the_domain_message() -> None:
    """Səbəbsiz düzəliş use case-də rədd edilir — mesaj ekrana çatır."""
    from src.application.use_cases.export_preflight import ExportCorrectionReasonError

    use_case = _PreflightUseCase(
        record_error=ExportCorrectionReasonError("qısa", user_message="Səbəb qısadır.")
    )
    session = _Session(preflight=use_case)
    screen = _ScreenStub()

    _controller(session)._submit_correction(
        screen,  # type: ignore[arg-type]
        employee_id=str(new_employee_id()),
        target_date="2026-08-04",
        field_code="FAKTIKI_GUN",
        new_value="18",
        reason="qısa",
    )

    assert screen.messages[-1] == ("Səbəb qısadır.", True)
    assert use_case.recorded == []


def test_a_malformed_date_is_rejected_before_the_session_opens() -> None:
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub()

    _controller(session)._submit_correction(
        screen,  # type: ignore[arg-type]
        employee_id=str(new_employee_id()),
        target_date="04.08.2026",
        field_code="FAKTIKI_GUN",
        new_value="18",
        reason="Kassa sistemində təkrar giriş qeydi aşkarlandı",
    )

    assert use_case.recorded == []
    assert screen.messages[-1][1] is True


def test_export_writes_a_file_after_confirmation(tmp_path: Any, monkeypatch: Any) -> None:
    """«Təsdiqlə və Export Et» — XƏBƏRDARLIQ OLSA DA fayl yazılır (bloklama yox)."""
    row = _row()
    review = _review(
        rows=[row],
        findings=(
            ExportValidationFinding(
                code=ExportValidationCode.EXCESS_WORK_DAYS,
                subject_az="Rəşad Məmmədov",
                detail_az="34 iş günü...",
                employee_id=row.employee_id,
            ),
        ),
    )
    session = _Session(preflight=_PreflightUseCase(review=review))
    screen = _ScreenStub()
    controller = _controller(session)
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    controller._on_export(screen, "attendance")  # type: ignore[arg-type]

    written = list(tmp_path.glob("Davamiyyet_*.xlsx"))
    assert written, "doğrulama xəbərdarlığı export-u BLOKLAMAMALIDIR"
    assert screen.messages[-1][1] is False


def test_cancelling_the_folder_dialog_does_not_write_anything(
    tmp_path: Any, monkeypatch: Any
) -> None:
    session = _Session(preflight=_PreflightUseCase(review=_review(rows=[_row()])))
    screen = _ScreenStub()
    monkeypatch.setattr(ReportExportController, "_choose_output_dir", lambda self, _screen: None)

    _controller(session)._on_export(screen, "attendance")  # type: ignore[arg-type]

    assert list(tmp_path.glob("*.xlsx")) == []
    assert "ləğv" in screen.messages[-1][0]


# --------------------------------------------------------------------------- #
# BOŞLUQ 1 — TARİX ARALIĞI SEÇİCİSİ (kompas1.md Faza 7, bənd 1)
# --------------------------------------------------------------------------- #


def test_the_default_mode_is_the_full_current_month() -> None:
    """`[Tam Ay]` DEFOLTDUR — `exported_period` açarı `YYYY-MM` qalır."""
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub(date_range=("", ""))

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    today = date.today()  # noqa: DTZ011
    chosen = use_case.review_calls[-1]["report_range"]
    assert chosen.key == f"{today.year:04d}-{today.month:02d}"
    assert chosen.is_full_month is True


def test_attach_initialises_the_picker_in_full_month_mode() -> None:
    """Kontroller maketlə EYNİ setter-i çağırır (CLAUDE.md §6)."""
    session = _Session(preflight=_PreflightUseCase())
    screen = _ScreenStub()

    _controller(session).attach(screen)  # type: ignore[arg-type]

    assert screen.range_selections == [(False, "", "")]


def test_a_custom_range_reaches_the_use_case_with_its_own_key() -> None:
    """Xüsusi aralıq `YYYY-MM-DD_YYYY-MM-DD` açarını yazır (Faza 7)."""
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub(date_range=("2026-04-01", "2026-04-15"))

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    chosen = use_case.review_calls[-1]["report_range"]
    assert chosen.key == "2026-04-01_2026-04-15"
    assert chosen.day_count == 15


def test_a_range_longer_than_the_root_limit_is_refused_with_a_clear_message() -> None:
    """`REPORT_RANGE_MAX_DAYS` aşılanda mesaj SEÇİCİNİN yanında görünür."""
    from tests.fixtures.fakes import FakeSystemLimits

    limits = FakeSystemLimits({SystemLimitKey.REPORT_RANGE_MAX_DAYS.value: "31"})
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case, reports=_Reports(limits=limits))
    screen = _ScreenStub(date_range=("2026-01-01", "2026-12-31"))

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert use_case.review_calls == [], "hədd aşılıbsa baxış ÜMUMİYYƏTLƏ qurulmur"
    message, is_error = screen.range_messages[-1]
    assert is_error is True
    assert "31" in message and "365" in message
    # Doğrulama kartına səs-küy YAZILMIR — səhv tarix sahəsindədir.
    assert screen.messages == []


def test_a_malformed_date_is_reported_next_to_the_picker() -> None:
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub(date_range=("01.04.2026", "15.04.2026"))

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert use_case.review_calls == []
    assert screen.range_messages[-1][1] is True
    assert "İL-AY-GÜN" in screen.range_messages[-1][0]


def test_an_inverted_range_is_refused_by_the_domain_rule() -> None:
    """Bitmə < başlanğıc — qayda `ReportRange`-dədir, ekranda TƏKRARLANMIR."""
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub(date_range=("2026-04-15", "2026-04-01"))

    _controller(session)._on_preflight(screen, "attendance")  # type: ignore[arg-type]

    assert use_case.review_calls == []
    assert screen.range_messages[-1][1] is True


def test_changing_the_range_reloads_both_the_roles_and_the_review() -> None:
    """Aralıq tətbiq olunanda baxış YENİDƏN yüklənir (rol kataloqu ilə birlikdə)."""
    use_case = _PreflightUseCase()
    roster = _RosterRepo([EmployeeRosterStatus(new_employee_id(), True, "SATICI", "Satıcı")])
    session = _Session(preflight=use_case, roster=roster)
    screen = _ScreenStub(date_range=("2026-04-01", "2026-04-15"))

    _controller(session)._on_range_changed(screen)  # type: ignore[arg-type]

    assert screen.role_options[-1][0] == [{"code": "SATICI", "name": "Satıcı"}]
    assert len(use_case.review_calls) == 1
    assert use_case.review_calls[-1]["report_range"].key == "2026-04-01_2026-04-15"


def test_changing_the_range_without_a_chosen_report_only_reloads_the_roles() -> None:
    """Hesabat hələ seçilməyibsə aqreqasiya sorğusu göndərilmir."""
    use_case = _PreflightUseCase()
    session = _Session(preflight=use_case)
    screen = _ScreenStub(active_report="")

    _controller(session)._on_range_changed(screen)  # type: ignore[arg-type]

    assert use_case.review_calls == []


def test_the_file_name_carries_the_selected_range_key(tmp_path: Any, monkeypatch: Any) -> None:
    """Fayl adı seçilmiş aralığı daşıyır — iki kəsik eyni qovluqda qarışmır."""
    session = _Session(preflight=_PreflightUseCase(review=_review(rows=[_row()])))
    screen = _ScreenStub(date_range=("2026-04-01", "2026-04-15"))
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    _controller(session)._on_export(screen, "attendance")  # type: ignore[arg-type]

    assert [p.name for p in tmp_path.glob("*.xlsx")] == ["Davamiyyet_2026-04-01_2026-04-15.xlsx"]


# --------------------------------------------------------------------------- #
# BOŞLUQ 2 — PREMİYA & CƏRİMƏ FAYLI + LOCK MEXANİZMİ
# --------------------------------------------------------------------------- #


def _sales_fact(employee_id: EmployeeId, name: str = "Rəşad Məmmədov") -> Any:
    from src.application.use_cases.reporting import EmployeeSalesFacts
    from src.domain.value_objects.money import Money

    return EmployeeSalesFacts(
        employee_id=employee_id,
        full_name=name,
        store_name="Bellona 28 May",
        gross_sales=Money(Decimal("18450.00")),
        earned_points=320,
    )


def _published_fine(employee_id: EmployeeId, *, published_at: datetime) -> Any:
    from src.domain.entities.fine import Fine, FineSource
    from src.domain.value_objects.identifiers import FineId, FineTypeId, StoreId
    from src.domain.value_objects.money import Money

    fine = Fine(
        fine_id=FineId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=employee_id,
        store_id=StoreId(uuid.uuid4()),
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal("25.00")),
        issued_at=published_at - timedelta(hours=1),
        fine_type_id=FineTypeId(uuid.uuid4()),
        issued_by=new_employee_id(),
        photo_evidence_url="https://drive/evidence.jpg",
    )
    fine.publish(reviewed_by=new_employee_id(), published_at=published_at)
    return fine


def _bonus_session(
    *,
    fines: list[Any],
    facts: list[Any],
    review_rows: list[AttendanceRow] | None = None,
) -> _Session:
    rows = review_rows if review_rows is not None else [_row()]
    return _Session(
        preflight=_PreflightUseCase(review=_review(rows=rows)),
        report_facts=_ReportFacts(sales=facts),
        fines=_FineRepo(fines),
    )


def test_the_bonus_file_is_written_from_the_selected_range(tmp_path: Any, monkeypatch: Any) -> None:
    """FAYL 2 artıq bu ekrandan yazılır — aralıq `list_in_range`-ə ötürülür."""
    employee_id = new_employee_id()
    fine = _published_fine(employee_id, published_at=datetime(2026, 4, 2, 9, tzinfo=UTC))
    session = _bonus_session(fines=[fine], facts=[_sales_fact(employee_id)])
    screen = _ScreenStub(date_range=("2026-04-01", "2026-04-15"))
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    _controller(session)._on_export(screen, "bonus_penalty")  # type: ignore[arg-type]

    assert [p.name for p in tmp_path.glob("*.xlsx")] == [
        "Premiya_Cerime_2026-04-01_2026-04-15.xlsx"
    ]
    assert session.uow.fines.calls == [(date(2026, 4, 1), date(2026, 4, 15))]
    assert session.commits >= 1


def test_an_open_appeal_window_fine_never_reaches_the_bonus_file(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """LOCK MEXANİZMİ: 72 saatlıq pəncərə AÇIQDIRSA cərimə xaric edilir.

    Aralığın seçilməsi bu qaydanı BAYPAS ETMİR — cərimə aralığın İÇİNDƏDİR,
    lakin `Fine.is_exportable(now=...)` onu buraxmır.
    """
    employee_id = new_employee_id()
    # Nəşr İNDİ olub → pəncərə hələ açıqdır.
    fine = _published_fine(employee_id, published_at=datetime.now(UTC))
    session = _bonus_session(fines=[fine], facts=[_sales_fact(employee_id)])
    screen = _ScreenStub()
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    _controller(session)._on_export(screen, "bonus_penalty")  # type: ignore[arg-type]

    selection, _period = session.reports.marked[-1]
    assert selection.included_fines == []
    assert selection.deferred_fine_count == 1
    assert fine.exported_period is None, "təxirə salınmış cərimə İŞARƏLƏNMİR"
    assert "açıq etiraz pəncərəsinə görə xaric" in screen.messages[-1][0]


def test_a_reversed_fine_never_reaches_the_bonus_file(tmp_path: Any, monkeypatch: Any) -> None:
    employee_id = new_employee_id()
    fine = _published_fine(employee_id, published_at=datetime(2026, 4, 2, 9, tzinfo=UTC))
    fine.reverse(
        decided_by=new_employee_id(),
        decided_at=datetime(2026, 4, 3, 9, tzinfo=UTC),
        reason="Etiraz qəbul olundu, kamera qeydi işçini təsdiqlədi",
    )
    session = _bonus_session(fines=[fine], facts=[_sales_fact(employee_id)])
    screen = _ScreenStub()
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    _controller(session)._on_export(screen, "bonus_penalty")  # type: ignore[arg-type]

    selection, _period = session.reports.marked[-1]
    assert selection.included_fines == []
    assert selection.already_exported_count == 0


def test_two_overlapping_ranges_never_charge_the_same_fine_twice(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """1–15 aprel export edilir, sonra 10–20 aprel — cərimə İKİNCİ DƏFƏ tutulmur."""
    employee_id = new_employee_id()
    fine = _published_fine(employee_id, published_at=datetime(2026, 4, 2, 9, tzinfo=UTC))
    session = _bonus_session(fines=[fine], facts=[_sales_fact(employee_id)])
    controller = _controller(session)
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    first = _ScreenStub(date_range=("2026-04-01", "2026-04-15"))
    controller._on_export(first, "bonus_penalty")  # type: ignore[arg-type]
    assert fine.exported_period == "2026-04-01_2026-04-15"

    second = _ScreenStub(date_range=("2026-04-10", "2026-04-20"))
    controller._on_export(second, "bonus_penalty")  # type: ignore[arg-type]

    selection, _period = session.reports.marked[-1]
    assert selection.included_fines == []
    assert selection.already_exported_count == 1
    # Dövr açarı DƏYİŞMİR — pul iki dəfə kəsilmir.
    assert fine.exported_period == "2026-04-01_2026-04-15"
    assert "artıq əvvəlki dövrdə tutulub" in second.messages[-1][0]


def test_the_lock_summary_separates_the_two_reasons(tmp_path: Any, monkeypatch: Any) -> None:
    """Təxirə salınan VƏ artıq tutulmuş cərimələr AYRI sayğaclarla göstərilir."""
    employee_id = new_employee_id()
    deferred = _published_fine(employee_id, published_at=datetime.now(UTC))
    charged = _published_fine(employee_id, published_at=datetime(2026, 4, 2, 9, tzinfo=UTC))
    charged.mark_exported(period="2026-03", now=datetime(2026, 4, 20, 9, tzinfo=UTC))
    session = _bonus_session(fines=[deferred, charged], facts=[_sales_fact(employee_id)])
    screen = _ScreenStub()
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    _controller(session)._on_export(screen, "bonus_penalty")  # type: ignore[arg-type]

    deferred_count, already, notice = screen.lock_summaries[-1]
    assert (deferred_count, already) == (1, 1)
    assert "2026-03" in notice


def test_the_role_filter_scopes_the_sales_facts_so_no_fine_is_marked_silently(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """Fayldan kənarda qalan işçinin cəriməsi TUTULMUŞ işarələnmir.

    Filtri sətirlərə sonradan tətbiq etsəydik, pul kəsilər, sənəd isə olmazdı.
    """
    kept, dropped = new_employee_id(), new_employee_id()
    kept_fine = _published_fine(kept, published_at=datetime(2026, 4, 2, 9, tzinfo=UTC))
    dropped_fine = _published_fine(dropped, published_at=datetime(2026, 4, 2, 9, tzinfo=UTC))
    session = _bonus_session(
        fines=[kept_fine, dropped_fine],
        facts=[_sales_fact(kept, "Satıcı A"), _sales_fact(dropped, "Menecer B")],
    )
    session.export_roster.entries = [
        EmployeeRosterStatus(kept, True, "SATICI", "Satıcı"),
        EmployeeRosterStatus(dropped, True, "MAGAZA_MENECERI", "Mağaza Meneceri"),
    ]
    screen = _ScreenStub(role="SATICI", date_range=("2026-04-01", "2026-04-15"))
    monkeypatch.setattr(
        ReportExportController, "_choose_output_dir", lambda self, _screen: tmp_path
    )

    _controller(session)._on_export(screen, "bonus_penalty")  # type: ignore[arg-type]

    selection, _period = session.reports.marked[-1]
    assert [row.employee_id for row in selection.rows] == [kept]
    assert kept_fine.exported_period == "2026-04-01_2026-04-15"
    assert dropped_fine.exported_period is None, "fayla düşməyən cərimə tutulmuş sayılmır"


def test_the_bonus_correction_dialog_offers_only_the_note_field() -> None:
    """Premiya faylında davamiyyət sütunlarını düzəltmək MƏNASIZDIR."""
    from src.presentation.controllers.report_export import _correction_fields

    codes = [code for code, _label in _correction_fields("bonus_penalty")]

    assert codes == ["QEYD"]
    assert len(_correction_fields("attendance")) > 1


def test_the_export_type_follows_the_selected_report() -> None:
    """Davamiyyət düzəlişi premiya faylının «Qeyd» sütununa sızmır."""
    from src.presentation.controllers.report_export import _export_type_for

    assert _export_type_for("attendance") == EXPORT_TYPE_ATTENDANCE
    assert _export_type_for("bonus_penalty") == EXPORT_TYPE_BONUS_PENALTY


# --------------------------------------------------------------------------- #
# Maket ↔ canlı yol: EYNİ AÇARLAR (CLAUDE.md §6)
# --------------------------------------------------------------------------- #


def test_preview_finding_keys_match_the_live_controller() -> None:
    live = _finding_rows(
        _review(
            findings=(
                ExportValidationFinding(
                    code=ExportValidationCode.EXCESS_WORK_DAYS,
                    subject_az="X",
                    detail_az="Y",
                ),
            )
        )
    )[0]

    assert set(live) == set(preview_data.EXPORT_VALIDATION_FINDINGS[0])


def test_preview_comparison_keys_match_the_live_controller() -> None:
    live = _comparison_rows(
        _review(
            deltas=(MetricDelta("unauthorized_absences", "İcazəsiz qayıb", 17, 14, True, True),)
        )
    )[0]

    assert set(live) == set(preview_data.EXPORT_PERIOD_COMPARISON[0])


def test_preview_correction_keys_match_the_live_controller() -> None:
    row = _row()
    live = _correction_rows(
        _review(rows=[row], corrections=(_correction(row.employee_id),)),
        names={row.employee_id: "Rəşad Məmmədov"},
    )[0]

    assert set(live) == set(preview_data.EXPORT_CORRECTIONS[0])


def test_preview_role_option_keys_match_the_live_controller() -> None:
    live = _role_rows([EmployeeRosterStatus(new_employee_id(), True, "SATICI", "Satıcı")])[0]

    assert set(live) == set(preview_data.EXPORT_ROLE_OPTIONS[0])


# --------------------------------------------------------------------------- #
# Ekranın ÖZÜ — Qt tələb edir, HƏR İKİ TEMA
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["light", "dark"])
def theme(request, qt_app):  # type: ignore[no-untyped-def]
    """Dizayn qapısı: ekran HƏR İKİ temada qurulmalıdır.

    Parametrləşdirilmiş fixture: aşağıdakı hər Qt testi İKİ DƏFƏ işləyir.
    Ayrı-ayrı "light" və "dark" testləri yazmaq eyni gövdəni iki dəfə
    təkrarlayardı.
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    mode = ThemeMode.LIGHT if request.param == "light" else ThemeMode.DARK
    manager = ThemeManager(preference=mode)
    manager.apply(qt_app)
    return manager


@requires_qt
def test_the_screen_builds_in_both_themes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_period("Avqust 2026")
    screen.set_lock_summary(4)

    assert screen.selected_role() == ""
    assert screen.active_report() == ""
    # `[Tam Ay]` DEFOLTDUR və tarix sahələri GİZLİDİR — görünüş Faza 8-in ilk
    # buraxılışı ilə eynidir.
    assert screen.selected_range() == ("", "")
    assert screen._custom_range_row.isVisibleTo(screen) is False


@requires_qt
def test_the_lock_summary_shows_both_reasons_in_one_note(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_lock_summary(
        4, already_exported=2, overlap_notice="2 cərimə artıq tutulub (2026-07)"
    )

    text = screen._lock_note.text()
    assert "72 saatlıq" in text
    assert "2026-07" in text


@requires_qt
def test_switching_to_a_custom_range_reveals_the_date_fields(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_range_selection(custom=True, start="2026-04-01", end="2026-04-15")

    assert screen._custom_range_row.isVisibleTo(screen) is True
    assert screen.selected_range() == ("2026-04-01", "2026-04-15")


@requires_qt
def test_setting_the_range_selection_does_not_emit_a_change_signal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Proqram yolu ilə qurma sonsuz yenidən-oxu dövrəsi yaratmır."""
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    emitted: list[tuple[str, str]] = []
    screen.range_changed.connect(lambda start, end: emitted.append((start, end)))

    screen.set_range_selection(custom=True, start="2026-04-01", end="2026-04-15")

    assert emitted == []


@requires_qt
def test_applying_an_incomplete_custom_range_marks_the_empty_field(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    emitted: list[tuple[str, str]] = []
    screen.range_changed.connect(lambda start, end: emitted.append((start, end)))
    screen.set_range_selection(custom=True, start="2026-04-01", end="")

    screen._on_range_applied()

    assert emitted == []
    assert screen._range_end.has_error is True


@requires_qt
def test_applying_a_complete_custom_range_emits_both_dates(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    emitted: list[tuple[str, str]] = []
    screen.range_changed.connect(lambda start, end: emitted.append((start, end)))
    screen.set_range_selection(custom=True, start="2026-04-01", end="2026-04-15")

    screen._on_range_applied()

    assert emitted == [("2026-04-01", "2026-04-15")]


@requires_qt
def test_returning_to_the_full_month_mode_emits_an_empty_pair(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`[Tam Ay]`-a qayıdış ikinci klik TƏLƏB ETMİR."""
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    screen.set_range_selection(custom=True, start="2026-04-01", end="2026-04-15")
    emitted: list[tuple[str, str]] = []
    screen.range_changed.connect(lambda start, end: emitted.append((start, end)))

    screen._range_mode.setCurrentIndex(0)

    assert emitted == [("", "")]
    assert screen.selected_range() == ("", "")
    assert screen._custom_range_row.isVisibleTo(screen) is False


@requires_qt
def test_the_range_message_is_shown_next_to_the_picker(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_range_message("Seçilmiş aralıq 365 gündür — icazə verilən maksimum 31 gündür.")
    assert screen._range_message.isVisibleTo(screen) is True

    screen.set_range_message("")
    assert screen._range_message.isVisibleTo(screen) is False


@requires_qt
def test_findings_render_as_rows_and_never_disable_the_confirm_button(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_validation_findings(list(preview_data.EXPORT_VALIDATION_FINDINGS))

    assert screen._finding_table.row_count == 4
    assert screen._confirm_button.isEnabled() is True, "xəbərdarlıq export-u BLOKLAMIR"
    assert screen._preflight_message.text().startswith("4 şübhəli")


@requires_qt
def test_no_findings_shows_a_positive_message_instead_of_an_empty_table(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_validation_findings([])

    assert screen._finding_table.row_count == 0
    assert screen._finding_table.isVisibleTo(screen) is False
    assert "tapılmadı" in screen._preflight_message.text()


@requires_qt
def test_the_correction_section_is_hidden_without_the_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    screen.set_validation_findings([])

    screen.set_correction_access(allowed=False)
    assert screen._corrections_card.isVisibleTo(screen) is False

    screen.set_correction_access(allowed=True)
    assert screen._corrections_card.isVisibleTo(screen) is True


@requires_qt
def test_role_filter_lists_the_catalog_and_reports_the_selection(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_role_options(list(preview_data.EXPORT_ROLE_OPTIONS), selected="SATICI")

    assert screen._role_filter.count() == 4  # «Bütün rollar» + üç rol
    assert screen.selected_role() == "SATICI"


@requires_qt
def test_filling_the_role_filter_does_not_emit_a_change_signal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Doldurma zamanı siqnal sonsuz yenidən-oxu dövrəsi yaradardı."""
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    emitted: list[str] = []
    screen.role_filter_changed.connect(emitted.append)

    screen.set_role_options(list(preview_data.EXPORT_ROLE_OPTIONS))

    assert emitted == []


@requires_qt
def test_a_missing_role_falls_back_to_all_roles(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Seçilmiş rol kataloqdan çıxıbsa filtr AÇIQ şəkildə sıfırlanır."""
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_role_options(list(preview_data.EXPORT_ROLE_OPTIONS), selected="SILINMIS_ROL")

    assert screen.selected_role() == ""


@requires_qt
def test_the_comparison_table_hides_itself_without_a_baseline(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_period_comparison([])

    assert screen._comparison_table.row_count == 0
    assert "məlumat yoxdur" in screen._comparison_caption.text()

    screen.set_period_comparison(
        list(preview_data.EXPORT_PERIOD_COMPARISON),
        caption=preview_data.EXPORT_COMPARISON_CAPTION,
    )
    assert screen._comparison_table.row_count == 4


@requires_qt
def test_the_card_button_asks_for_validation_not_for_the_file(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Kart düyməsi `preflight_requested` verir — fayl HƏLƏ yaranmır."""
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    preflight: list[str] = []
    exported: list[str] = []
    screen.preflight_requested.connect(preflight.append)
    screen.export_requested.connect(exported.append)

    screen._on_preflight("attendance")

    assert preflight == ["attendance"]
    assert exported == []
    assert screen.active_report() == "attendance"


@requires_qt
def test_confirmation_emits_the_export_signal_for_the_active_report(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)
    exported: list[str] = []
    screen.export_requested.connect(exported.append)

    screen._on_confirm()  # doğrulama işlədilməyib — heç nə baş vermir
    assert exported == []

    screen._on_preflight("attendance")
    screen._confirm_button.click()
    assert exported == ["attendance"]


@requires_qt
def test_the_correction_dialog_requires_a_reason_of_the_root_length(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ExportCorrectionDialog

    dialog = ExportCorrectionDialog(
        theme,
        employees=[(str(new_employee_id()), "Rəşad Məmmədov")],
        fields=[("FAKTIKI_GUN", "Faktiki işlənilən gün")],
        default_date="2026-08-01",
        reason_min_length=10,
        parent=None,
    )
    qtbot.addWidget(dialog)
    submitted: list[tuple[str, ...]] = []
    dialog.submitted.connect(lambda *args: submitted.append(args))

    dialog._value.set_text("18")
    dialog._reason.setPlainText("qısa")
    dialog._on_submit()

    assert submitted == []
    assert dialog._reason_error.isVisibleTo(dialog) is True


@requires_qt
def test_the_correction_dialog_submits_a_complete_form(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ExportCorrectionDialog

    employee_id = str(new_employee_id())
    dialog = ExportCorrectionDialog(
        theme,
        employees=[(employee_id, "Rəşad Məmmədov")],
        fields=[("FAKTIKI_GUN", "Faktiki işlənilən gün")],
        default_date="2026-08-01",
        reason_min_length=10,
        parent=None,
    )
    qtbot.addWidget(dialog)
    submitted: list[tuple[str, ...]] = []
    dialog.submitted.connect(lambda *args: submitted.append(args))

    dialog._value.set_text("18")
    dialog._reason.setPlainText("Kassa sistemində təkrar giriş qeydi aşkarlandı")
    dialog._on_submit()

    assert submitted == [
        (
            employee_id,
            "2026-08-01",
            "FAKTIKI_GUN",
            "18",
            "Kassa sistemində təkrar giriş qeydi aşkarlandı",
        )
    ]


@requires_qt
def test_the_correction_dialog_rejects_a_non_iso_date(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import ExportCorrectionDialog

    dialog = ExportCorrectionDialog(
        theme,
        employees=[(str(new_employee_id()), "Rəşad Məmmədov")],
        fields=[("FAKTIKI_GUN", "Faktiki işlənilən gün")],
        default_date="04.08.2026",
        reason_min_length=10,
        parent=None,
    )
    qtbot.addWidget(dialog)
    submitted: list[tuple[str, ...]] = []
    dialog.submitted.connect(lambda *args: submitted.append(args))

    dialog._value.set_text("18")
    dialog._reason.setPlainText("Kassa sistemində təkrar giriş qeydi aşkarlandı")
    dialog._on_submit()

    assert submitted == []
    assert dialog._date.has_error is True


@requires_qt
def test_the_preview_path_fills_the_same_setters_as_the_controller(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Maket yolu ekranı TAM doldurur — canlı yolla EYNİ setter-lərlə."""
    from src.presentation.preview_screens import populate
    from src.presentation.screens.group_h import ReportExportScreen

    screen = ReportExportScreen(theme)
    qtbot.addWidget(screen)

    populate("reports", screen)

    assert screen._finding_table.row_count == 4
    assert screen._comparison_table.row_count == 4
    assert screen._correction_table.row_count == 2
    assert screen._corrections_card.isVisibleTo(screen) is True
    assert screen._role_filter.count() == 4
    # Maket də `[Tam Ay]` rejimindədir — canlı yolla EYNİ setter, eyni dəyər.
    assert screen.selected_range() == ("", "")
    assert screen._custom_range_row.isVisibleTo(screen) is False
    # LOCK xülasəsinin HƏR İKİ cümləsi maketdə görünür.
    assert "2026-07" in screen._lock_note.text()
