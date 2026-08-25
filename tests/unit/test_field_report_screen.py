"""Sahə hesabatı ekranı və kontrolleri — #26+#27-nin GUI tərəfi (kompas1.md Faza 3).

Testlər İKİ təbəqəni ayrıca yoxlayır:

    * ekranın ÖZÜ (üç vəziyyətli cavab, foto qapısı, boş siyahı) — Qt TƏLƏB
      EDİR, çünki `set_open_reports`/`_render_step` real `Chip`/`DataTable`/
      `QRadioButton` qurur;
    * kontroller (açar paritetı, yazıdan sonra yenidən oxuma, səlahiyyət
      izahı) — Qt TƏLƏB ETMİR, `test_exception_screen.py`-dəki duck-typing
      naxışını təkrarlayır.

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py`-a TOXUNULMUR (eyni
qərar `test_exception_screen.py`-də də verilib: paralel işlər həmin ortaq
faylı dəyişə bilər).
"""

from __future__ import annotations

import ast
import inspect
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.field_reports import FieldReportSubmission
from src.domain.entities.employee import Employee
from src.domain.entities.field_report import FieldReport
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.field_reports import (
    ChecklistItemDraft,
    FieldReportCategory,
    FieldReportTemplate,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
    new_field_report_id,
)
from src.presentation import preview_data
from src.presentation.controllers.field_reports import (
    LIST_RESTRICTED_NOTICE,
    SCREEN_TEMPLATE_FAMILY,
    FieldReportsController,
)
from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
STORE: Final = StoreId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 42, tzinfo=UTC)

AUDIT_TEMPLATE: Final = FieldReportTemplate(
    code="STORE_AUDIT",
    name_az="Mağaza ziyarəti / audit",
    description_az="Checklist üzrə yoxlama.",
    requires_checklist=True,
)
INCIDENT_TEMPLATE: Final = FieldReportTemplate(
    code="INCIDENT",
    name_az="İnsident bildirişi",
    description_az="Baş vermiş hadisə.",
    requires_checklist=False,
)
AUDIT_CATEGORY: Final = FieldReportCategory(
    code="TEMIZLIK",
    report_type="STORE_AUDIT",
    name_az="Təmizlik və gigiyena",
)
INCIDENT_CATEGORY: Final = FieldReportCategory(
    code="OGURLUQ",
    report_type="INCIDENT",
    name_az="Oğurluq şübhəsi",
    route_to_role="TEHLUKESIZLIK",
)


class _DeniedError(KompasOSError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


# --------------------------------------------------------------------------- #
# Aktorlar
# --------------------------------------------------------------------------- #


def _employee(
    *, code: str, name_az: str, priority: RolePriority, flags: tuple[str, ...]
) -> Employee:
    tenant_id = TenantId(uuid.uuid4())
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=name_az,
        priority=priority,
        tenant_id=tenant_id,
        is_system=True,
    )
    for flag in flags:
        position.grant(PermissionFlag(code=flag, category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )


def _seller() -> Employee:
    """`Satıcı` — migrations/038-ə görə YALNIZ `can_report_incident` daşıyır."""
    return _employee(
        code="SATICI",
        name_az="Satıcı",
        priority=RolePriority.STAFF,
        flags=("can_report_incident",),
    )


def _auditor() -> Employee:
    return _employee(
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        flags=("can_conduct_store_audit", "can_report_incident"),
    )


# --------------------------------------------------------------------------- #
# Menyu: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (CLAUDE.md bölmə 3)
# --------------------------------------------------------------------------- #


def test_menu_entries_use_the_two_phase_three_flags() -> None:
    """Audit → `can_conduct_store_audit`, insident → `can_report_incident`."""
    audit = next(e for e in DEFAULT_ENTRIES if e.key == "store_audit")
    incident = next(e for e in DEFAULT_ENTRIES if e.key == "incident_report")

    assert audit.required_flag == "can_conduct_store_audit"
    assert incident.required_flag == "can_report_incident"


def test_navigation_hides_both_entries_without_flags() -> None:
    """Heç bir sahə-hesabatı flag-i olmayan aktor NƏ birini, NƏ digərini görür."""
    registry = build_default_registry()
    operator = preview_data.build_camera_operator()

    assert registry.is_visible("store_audit", operator, now=NOW) is False
    assert registry.is_visible("incident_report", operator, now=NOW) is False


def test_seller_sees_the_incident_entry_but_not_the_audit_entry() -> None:
    """038 "Tələ 3": hər kəs insident bildirə bilər, YALNIZ həlli məhduddur.

    Bu, kompas1.md-nin "admin/manager-tier" ifadəsi ilə flag-in universallığı
    arasındakı ziddiyyətin həllidir: forma ADMİN ÖRTÜYÜNDƏ yaşayır (kiosk
    şassisində yox), lakin AUDİTORİYASI admin-tier DEYİL — flag-i olan `Satıcı`
    maddəni görür və bildirişi yaza bilir.
    """
    registry = build_default_registry()
    seller = _seller()

    assert registry.is_visible("incident_report", seller, now=NOW) is True
    assert registry.is_visible("store_audit", seller, now=NOW) is False


def test_screen_family_table_covers_exactly_the_two_menu_keys() -> None:
    """`SCREEN_TEMPLATE_FAMILY` menyu ilə sinxron qalmalıdır."""
    keys = {entry.key for entry in DEFAULT_ENTRIES}
    assert set(SCREEN_TEMPLATE_FAMILY) <= keys
    assert SCREEN_TEMPLATE_FAMILY == {"store_audit": True, "incident_report": False}


# --------------------------------------------------------------------------- #
# Ekranın özü — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _audit_screen(theme: Any) -> Any:
    from src.presentation.screens.field_reports import FieldReportScreen

    screen = FieldReportScreen(theme)
    screen.set_templates(list(preview_data.FIELD_REPORT_AUDIT_TEMPLATES))
    screen.set_categories(list(preview_data.FIELD_REPORT_AUDIT_CATEGORIES))
    screen.set_stores(list(preview_data.FIELD_REPORT_STORES))
    screen.set_detail_min_length(preview_data.FIELD_REPORT_MIN_DETAIL)
    screen.set_photo_limit(preview_data.FIELD_REPORT_MAX_PHOTOS)
    return screen


@requires_qt
def test_checklist_expresses_the_third_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Üç vəziyyət: `True` / `False` / `None` — sonuncusu DEFOLTDUR."""
    screen = _audit_screen(theme)
    qtbot.addWidget(screen)

    screen._item_text.set_text("Soyuducunun temperaturu")
    assert screen.add_checklist_item() is True

    # Defolt: cavab YOXDUR — cavabsız bənd təsadüfən "keçdi" sayılmır.
    assert screen.checklist_entries()[0].passed is None

    screen.select_answer(True)
    assert screen.checklist_entries()[0].passed is True

    screen.select_answer(False)
    assert screen.checklist_entries()[0].passed is False

    # Üçüncü vəziyyətə GERİ qayıtmaq da mümkündür — iki-vəziyyətli checkbox
    # bunu ifadə edə bilməzdi (bax ekran modulunun başlığı).
    screen.select_answer(None)
    assert screen.checklist_entries()[0].passed is None


@requires_qt
def test_photo_required_item_blocks_navigation_without_a_photo(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Foto tələb edən CAVABLANMIŞ bənd şəkilsiz irəli buraxmır."""
    screen = _audit_screen(theme)
    qtbot.addWidget(screen)

    screen._item_text.set_text("Soyuducunun temperaturu")
    screen._item_photo_required.setChecked(True)
    screen.add_checklist_item()
    screen._item_text.set_text("Kassa arxası təmizliyi")
    screen.add_checklist_item()

    screen._step = 0
    screen._render_step()
    screen.select_answer(False)

    assert screen.go_next() is False, "Foto olmadan növbəti bəndə keçmək olmamalıdır"
    assert screen._step == 0


@requires_qt
def test_photo_required_item_without_an_answer_does_not_block(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """CAVABSIZ bənd boşluq SAYILMIR — domen də onu rədd etmir."""
    screen = _audit_screen(theme)
    qtbot.addWidget(screen)

    screen._item_text.set_text("Soyuducunun temperaturu")
    screen._item_photo_required.setChecked(True)
    screen.add_checklist_item()
    screen._item_text.set_text("Kassa arxası təmizliyi")
    screen.add_checklist_item()

    screen._step = 0
    screen._render_step()

    assert screen.go_next() is True
    assert screen._step == 1


@requires_qt
def test_submit_is_blocked_while_a_photo_is_missing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """İstifadəçi domen xətasına QƏDƏR aparılmır — siqnal ÜMUMİYYƏTLƏ atılmır."""
    screen = _audit_screen(theme)
    qtbot.addWidget(screen)

    emitted: list[Any] = []
    screen.submit_requested.connect(emitted.append)

    screen._detail.setPlainText("Anbar arxasında qablaşdırma tullantısı yığılıb.")
    screen._item_text.set_text("Soyuducunun temperaturu")
    screen._item_photo_required.setChecked(True)
    screen.add_checklist_item()
    screen.select_answer(False)

    screen._on_submit()

    assert emitted == []
    # Səbəb ekranda YAZILIR (pəncərə göstərilmədiyi üçün `isVisible()` deyil,
    # mətnin özü yoxlanılır — `isVisibleTo` naxışı ilə eyni səbəb).
    assert "foto-sübut məcburidir" in screen._form_message.text()


@requires_qt
def test_submit_emits_the_form_values_when_complete(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Tam doldurulmuş forma siqnalı ATIR və üç vəziyyəti daşıyır."""
    from src.presentation.screens.field_reports import FieldReportFormValues

    screen = _audit_screen(theme)
    qtbot.addWidget(screen)

    emitted: list[Any] = []
    screen.submit_requested.connect(emitted.append)

    screen._detail.setPlainText("Anbar arxasında qablaşdırma tullantısı yığılıb.")
    screen._item_text.set_text("Soyuducunun temperaturu")
    screen._item_blocking.setChecked(True)
    screen.add_checklist_item()
    screen.select_answer(False)

    screen._on_submit()

    assert len(emitted) == 1
    values = emitted[0]
    assert isinstance(values, FieldReportFormValues)
    assert values.template_code == "STORE_AUDIT"
    assert values.category_code == "TEMIZLIK"
    assert values.checklist[0].is_blocking is True
    assert values.checklist[0].passed is False


@requires_qt
def test_incident_template_hides_the_checklist_section(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Checklist bölməsi KATALOQDAN idarə olunur — `if code == ...` yoxdur."""
    from src.presentation.screens.field_reports import FieldReportScreen

    screen = FieldReportScreen(theme)
    qtbot.addWidget(screen)

    screen.set_templates(list(preview_data.FIELD_REPORT_INCIDENT_TEMPLATES))
    assert screen.requires_checklist() is False
    assert screen._checklist_holder.isVisibleTo(screen) is False

    screen.set_templates(list(preview_data.FIELD_REPORT_AUDIT_TEMPLATES))
    assert screen.requires_checklist() is True
    assert screen._checklist_holder.isVisibleTo(screen) is True


@requires_qt
def test_empty_open_list_keeps_the_form_usable(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş siyahı ÇÖKMÜR və formanı gizlətmir (bax `set_open_reports` başlığı)."""
    screen = _audit_screen(theme)
    qtbot.addWidget(screen)

    screen.set_open_reports([])

    assert screen.switcher().current_state() == "content"
    assert screen.table().row_count == 0


@requires_qt
def test_preview_rows_render_without_a_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Maket sətirləri (naməlum status daxil) ekranı çökdürmür."""
    screen = _audit_screen(theme)
    qtbot.addWidget(screen)

    rows = [*preview_data.FIELD_REPORT_OPEN_AUDITS, {"id": "x", "status": "FUTURE_STATUS"}]
    screen.set_open_reports(rows)

    assert screen.table().row_count == len(rows)


# --------------------------------------------------------------------------- #
# Kontroller — Qt tələb ETMİR (duck-typing)
# --------------------------------------------------------------------------- #


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def execute(self, sql: str, params: Any = None) -> _Cursor:
        return _Cursor([{"id": str(STORE), "name": "Bellona 28 May"}])


class _Uow:
    def __init__(self) -> None:
        self.connection = _Connection()


class _Limits:
    def get_int(self, tenant_id: Any, key: str, fallback: int) -> int:
        return fallback


def _report(detail: str = "Anbar arxasında tullantı yığılıb.") -> FieldReport:
    return FieldReport(
        report_id=new_field_report_id(),
        tenant_id=TENANT,
        report_type="STORE_AUDIT",
        category="TEMIZLIK",
        store_id=STORE,
        reported_by=EmployeeId(uuid.uuid4()),
        detail=detail,
        created_at=NOW,
        updated_at=NOW,
        emit_created_event=False,
    )


class _UseCase:
    """`FieldReportUseCase` müqaviləsinin minimal təkrarı."""

    def __init__(
        self,
        *,
        templates: list[FieldReportTemplate],
        categories: list[FieldReportCategory],
        reports: list[FieldReport] | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self.templates = templates
        self.categories = categories
        self.reports = list(reports or [])
        self.list_error = list_error
        self.list_open_calls = 0
        self.submitted: list[Any] = []
        self.closed: list[tuple[Any, Any, str]] = []
        self.started: list[Any] = []

    def list_templates(self, *, tenant_id: Any, actor: Any) -> list[FieldReportTemplate]:
        return list(self.templates)

    def list_categories(
        self, *, tenant_id: Any, actor: Any, report_type: str
    ) -> list[FieldReportCategory]:
        return [c for c in self.categories if c.report_type == report_type]

    def checklist_draft_for_type(
        self, *, tenant_id: Any, actor: Any, report_type: str
    ) -> list[ChecklistItemDraft]:
        """`v2backlog.md` Faza 4.1 — bu fayldakı ekranlar checklist kataloqunu
        AYRICA sınamır (`test_field_reports.py`-in predmetidir), ona görə
        BOŞ siyahı KÖHNƏ sərbəst-mətn rejimini SÜKUTLA saxlayır (bax
        `controllers/field_reports.py` modul başlığı)."""
        return []

    def list_open(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        store_ids: Any = None,
        report_type: str | None = None,
    ) -> list[FieldReport]:
        self.list_open_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return [r for r in self.reports if report_type is None or r.report_type == report_type]

    def submit(self, *, tenant_id: Any, actor: Any, draft: Any) -> FieldReportSubmission:
        self.submitted.append(draft)
        report = _report(draft.detail)
        self.reports.append(report)
        return FieldReportSubmission(report=report, corrective_task_ids=(), routed_role=None)

    def start_progress(self, *, tenant_id: Any, actor: Any, report_id: Any) -> FieldReport:
        self.started.append(report_id)
        return self.reports[0]

    def close(
        self, *, tenant_id: Any, actor: Any, report_id: Any, status: Any, note: str
    ) -> FieldReport:
        self.closed.append((report_id, status, note))
        self.reports = [r for r in self.reports if r.id != report_id]
        return _report()


def _session_field_reports_call_sites(module_source: str) -> set[str]:
    """`session.field_reports.<metod>(...)` çağırış yerlərinin adları.

    Protokolun TAM səthini YOX — bu ekranın FAKTİKİ çağırdığı metodları
    axtarır (`FieldReportUseCase`-in `notify_overdue_audits`/`attach_
    uploaded_photo`/`list_all_report_types` kimi metodları bu ekranda
    ÜMUMİYYƏTLƏ istifadə olunmur, ona görə `_UseCase` sahtəsi onları QƏSDƏN
    daşımır — «Protokolun HAMISI» qapısı burada SƏHV OLARDI, saxta İSTİSNA
    zibilliyi ilə dolardı).
    """
    tree = ast.parse(module_source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "field_reports"
        ):
            called.add(func.attr)
    return called


def test_the_fake_use_case_implements_every_method_the_controller_actually_calls() -> None:
    """`ui`-nin bu gün tapdığı qüsur sinfinin REQRESSİYA QIFILI.

    `controllers/field_reports.py`-ə `checklist_draft_for_type()` çağırışı
    əlavə olundu, bu faylın `_UseCase` sahtəsi isə geri qaldı — nəticə
    `AttributeError` idi, kodun ÖZÜNDƏ qüsur YOX idi (`FieldReportUseCase`-
    də metod tam mövcud idi). Bu qapı KONTROLLERİN faktiki çağırdığı hər
    metodun sahtədə OLDUĞUNU təsdiqləyir ki, sahtə YENİDƏN geri qalmasın.
    """
    from src.presentation.controllers import field_reports as field_reports_controller

    called = _session_field_reports_call_sites(inspect.getsource(field_reports_controller))
    implemented = {
        name
        for name, value in vars(_UseCase).items()
        if callable(value) and not name.startswith("_")
    }

    missing = sorted(called - implemented)
    assert missing == [], (
        "`controllers/field_reports.py` bu metodları `session.field_reports`"
        f"-də ÇAĞIRIR, lakin bu faylın `_UseCase` sahtəsində YOXDUR: {missing}."
    )


class _Session:
    def __init__(self, use_case: _UseCase) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow()
        self.limits = _Limits()
        self.field_reports = use_case
        self.commits = 0

    def max_upload_bytes(self) -> int:
        return 5 * 1024 * 1024

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: _Session) -> None:
        self._session = session
        self.tenant_id = TENANT
        self.upload_runs = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session

    def run_evidence_uploads(self) -> None:  # pragma: no cover - şəkilsiz axında çağırılmır
        self.upload_runs += 1


class _ScreenStub:
    """Ekranın setter API-sinin sahtəsi — Qt qurulmadan açarları tutur."""

    def __init__(self) -> None:
        self.templates: list[dict[str, str]] = []
        self.categories: list[dict[str, str]] = []
        self.checklist_drafts: dict[str, list[dict[str, str]]] = {}
        self.stores: list[tuple[str, str]] = []
        self.reports: list[dict[str, str]] = []
        self.notice = ""
        self.messages: list[tuple[str, bool]] = []
        self.errors: list[tuple[str, str]] = []
        self.detail_min = 0
        self.photo_limit = 0
        self.cleared = 0

    def set_templates(self, rows: list[dict[str, str]]) -> None:
        self.templates = rows

    def set_categories(self, rows: list[dict[str, str]]) -> None:
        self.categories = rows

    def set_checklist_drafts(self, drafts: dict[str, list[dict[str, str]]]) -> None:
        """`v2backlog.md` Faza 4.1 — bax `FieldReportScreen.set_checklist_drafts`."""
        self.checklist_drafts = dict(drafts)

    def set_stores(self, stores: list[tuple[str, str]]) -> None:
        self.stores = stores

    def set_detail_min_length(self, value: int) -> None:
        self.detail_min = value

    def set_photo_limit(self, value: int) -> None:
        self.photo_limit = value

    def set_open_reports(self, rows: list[dict[str, str]]) -> None:
        self.reports = rows

    def set_list_notice(self, message: str) -> None:
        self.notice = message

    def set_form_message(self, message: str, *, error: bool = False) -> None:
        self.messages.append((message, error))

    def clear_form(self) -> None:
        self.cleared += 1

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


def _controller(use_case: _UseCase, *, requires_checklist: bool = True) -> Any:
    return FieldReportsController(
        _Context(_Session(use_case)),  # type: ignore[arg-type]
        _auditor(),
        requires_checklist=requires_checklist,
    )


def _audit_use_case(**overrides: Any) -> _UseCase:
    defaults: dict[str, Any] = {
        "templates": [AUDIT_TEMPLATE, INCIDENT_TEMPLATE],
        "categories": [AUDIT_CATEGORY, INCIDENT_CATEGORY],
        "reports": [_report()],
    }
    defaults.update(overrides)
    return _UseCase(**defaults)


def test_refresh_filters_templates_by_the_catalog_property() -> None:
    """Ailə `requires_checklist` ilə seçilir — şablon KODU ilə yox."""
    use_case = _audit_use_case()
    screen = _ScreenStub()

    _controller(use_case, requires_checklist=False).refresh(screen)  # type: ignore[arg-type]

    assert [row["code"] for row in screen.templates] == ["INCIDENT"]
    assert [row["code"] for row in screen.categories] == ["OGURLUQ"]


def test_preview_and_live_paths_share_the_same_keys() -> None:
    """Maket və canlı yol EYNİ açarları işlətməlidir (CLAUDE.md §6)."""
    use_case = _audit_use_case()
    screen = _ScreenStub()

    _controller(use_case).refresh(screen)  # type: ignore[arg-type]

    assert set(screen.templates[0]) == set(preview_data.FIELD_REPORT_AUDIT_TEMPLATES[0])
    assert set(screen.categories[0]) == set(preview_data.FIELD_REPORT_AUDIT_CATEGORIES[0])
    assert set(screen.reports[0]) == set(preview_data.FIELD_REPORT_OPEN_AUDITS[0])
    # Mağaza siyahısı cüt formasındadır (`open_shift.OpenShiftPostDialog` naxışı).
    assert len(screen.stores[0]) == len(preview_data.FIELD_REPORT_STORES[0]) == 2


def test_preview_incident_keys_match_the_live_incident_keys() -> None:
    """İnsident ailəsi üçün də eyni paritet — iki maket dəsti sürüşməməlidir."""
    use_case = _audit_use_case()
    screen = _ScreenStub()

    _controller(use_case, requires_checklist=False).refresh(screen)  # type: ignore[arg-type]

    assert set(screen.templates[0]) == set(preview_data.FIELD_REPORT_INCIDENT_TEMPLATES[0])
    assert set(screen.categories[0]) == set(preview_data.FIELD_REPORT_INCIDENT_CATEGORIES[0])


def test_missing_audit_permission_is_explained_not_crashed() -> None:
    """`list_open` səlahiyyət tələb edir — forma AÇIQ qalır, izah verilir."""
    use_case = _audit_use_case(list_error=_DeniedError("səlahiyyət yoxdur"))
    screen = _ScreenStub()

    _controller(use_case, requires_checklist=False).refresh(screen)  # type: ignore[arg-type]

    assert screen.reports == []
    assert screen.notice == LIST_RESTRICTED_NOTICE
    assert screen.errors == [], "Gözlənilən hal qırmızı xəta ekranı OLMAMALIDIR"
    # Forma yenə doldurulub — `Satıcı` insidenti yaza bilir.
    assert screen.templates and screen.stores


def test_empty_catalog_does_not_crash() -> None:
    """Boş kataloq normal haldır (yeni kirayəçi) — ekran boş forma alır."""
    use_case = _UseCase(templates=[], categories=[], reports=[])
    screen = _ScreenStub()

    _controller(use_case).refresh(screen)  # type: ignore[arg-type]

    assert screen.templates == []
    assert screen.reports == []
    assert screen.errors == []


def test_submit_writes_commits_and_rereads_the_list() -> None:
    """Yazıdan SONRA siyahı YENİDƏN oxunur (CLAUDE.md §6)."""
    from src.presentation.screens.field_reports import ChecklistEntry, FieldReportFormValues

    use_case = _audit_use_case(reports=[])
    context = _Context(_Session(use_case))
    controller = FieldReportsController(
        context,  # type: ignore[arg-type]
        _auditor(),
        requires_checklist=True,
    )
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]
    assert screen.reports == []

    controller._on_submit(
        screen,  # type: ignore[arg-type]
        FieldReportFormValues(
            template_code="STORE_AUDIT",
            category_code="TEMIZLIK",
            store_id=str(STORE),
            detail="Anbar arxasında qablaşdırma tullantısı yığılıb.",
            checklist=(ChecklistEntry(item_text="Soyuducunun temperaturu", passed=False),),
        ),
    )

    assert len(use_case.submitted) == 1
    assert context._session.commits == 1
    assert screen.cleared == 1
    # Siyahı təzə sorğu ilə doldurulub — yeni hesabat ARTIQ görünür.
    assert len(screen.reports) == 1
    assert use_case.list_open_calls == 2


def test_submit_failure_keeps_the_form_and_explains_the_reason() -> None:
    """Domen istisnası sükutla udulmur və forma ekrandan SİLİNMİR."""
    from src.presentation.screens.field_reports import FieldReportFormValues

    class _FailingUseCase(_UseCase):
        def submit(self, *, tenant_id: Any, actor: Any, draft: Any) -> FieldReportSubmission:
            raise _DeniedError("səlahiyyət yoxdur")

    use_case = _FailingUseCase(templates=[AUDIT_TEMPLATE], categories=[AUDIT_CATEGORY], reports=[])
    context = _Context(_Session(use_case))
    controller = FieldReportsController(
        context,  # type: ignore[arg-type]
        _auditor(),
        requires_checklist=True,
    )
    screen = _ScreenStub()

    controller._on_submit(
        screen,  # type: ignore[arg-type]
        FieldReportFormValues(
            template_code="STORE_AUDIT",
            category_code="TEMIZLIK",
            store_id=str(STORE),
            detail="Anbar arxasında qablaşdırma tullantısı yığılıb.",
        ),
    )

    assert context._session.commits == 0
    assert screen.cleared == 0
    assert screen.messages == [(_DeniedError.user_message, True)]
    assert screen.errors == []


def test_malformed_store_id_is_reported_inline() -> None:
    """Yanlış identifikator sessiya AÇMADAN tutulur."""
    from src.presentation.screens.field_reports import FieldReportFormValues

    use_case = _audit_use_case(reports=[])
    controller = _controller(use_case)
    screen = _ScreenStub()

    controller._on_submit(
        screen,  # type: ignore[arg-type]
        FieldReportFormValues(
            template_code="STORE_AUDIT",
            category_code="TEMIZLIK",
            store_id="mağaza-yox",
            detail="Anbar arxasında qablaşdırma tullantısı yığılıb.",
        ),
    )

    assert use_case.submitted == []
    assert screen.messages and screen.messages[-1][1] is True


def test_close_requires_a_note_and_rereads_the_list(monkeypatch: Any) -> None:
    """Bağlanma qeydi MƏCBURİDİR; boş cavab yazı yoluna GETMİR."""
    from src.presentation.controllers import field_reports as module

    use_case = _audit_use_case()
    controller = _controller(use_case)
    screen = _ScreenStub()
    report_id = str(use_case.reports[0].id)

    monkeypatch.setattr(module.FieldReportsController, "_ask_note", staticmethod(lambda *_: None))
    controller._on_close(screen, report_id, "RESOLVED")  # type: ignore[arg-type]
    assert use_case.closed == []

    monkeypatch.setattr(
        module.FieldReportsController,
        "_ask_note",
        staticmethod(lambda *_: "Təmizlik briqadası göndərildi, tullantı çıxarıldı."),
    )
    controller._on_close(screen, report_id, "RESOLVED")  # type: ignore[arg-type]

    assert len(use_case.closed) == 1
    assert use_case.closed[0][1].value == "RESOLVED"
    # Bağlanmış hesabat açıq siyahıda QALMIR — yenidən oxuma bunu göstərir.
    assert screen.reports == []
