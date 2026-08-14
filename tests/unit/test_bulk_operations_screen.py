"""Toplu Əməliyyatlar ekranı və kontrolleri — #29-un GUI tərəfi (kompas1.md Faza 5).

Testlər İKİ təbəqəni ayrıca yoxlayır (`test_annual_leave_screen.py`/`test_
field_report_screen.py` ilə eyni naxış):

    * KÖMƏKÇİ funksiyalar (`_preview_payload`, `_result_payload`, `_format_
      snapshot`, `_to_template_rows`, ...) və KONTROLLER metodları — Qt TƏLƏB
      ETMİR, sahtə `Session`/`Context`/use case ilə birbaşa çağırılır;
    * ekranların ÖZÜ (`BulkOperationsScreen`, üç dialoq) — Qt TƏLƏB EDİR,
      çünki real `Card`/`DataTable`/`QComboBox` qurulur.

Sahtələr BU FAYLDA yerlidir (`tests/fixtures/fakes.py`-a TOXUNULMUR — eyni
qərar `test_annual_leave_screen.py` başlığında izah olunub).

Dialoqun `.exec()`-i HEÇ VAXT çağırılmır (layihə boyu heç bir test bunu
etmir): modal event loop-u avtomatik bağlayan heç nə yoxdur, ona görə real
`.exec()` çağırışı testi ƏBƏDİ ASILI qoyardı. Onun ƏVƏZİNƏ:

    * dialoq SİNİFLƏRİ birbaşa qurulub (`.exec()` ÇAĞIRILMADAN) sahələri/
      mətnləri yoxlanılır;
    * kontrollerin dialoq AÇAN metodları (`_show_result`) test zamanı
      MONKEYPATCH edilir — `_submit_capture`/`_submit_apply`/`_on_deactivate`
      isə dialoqu ÜMUMİYYƏTLƏ keçməyərək BİRBAŞA çağırılır (`test_annual_
      leave_screen.py::controller._submit(...)` ilə eyni naxış).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.bulk_operations import (
    BulkCreatedEmployee,
    BulkImportPreview,
    BulkImportReport,
    CsvRowError,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    StoreTemplateId,
    TenantId,
    new_bulk_import_log_id,
    new_employee_id,
    new_store_id,
    new_store_template_id,
)
from src.domain.value_objects.store_templates import StoreTemplate
from src.presentation import preview_data
from src.presentation.controllers.bulk_operations import (
    BulkOperationsController,
    _capture_snapshot,
    _format_snapshot,
    _preview_payload,
    _result_payload,
    _store_choices,
    _to_template_rows,
)
from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)


class _DeniedError(KompasOSError):
    """`BulkOperationsPermissionError` müqaviləsinin yerli əvəzi."""

    user_message = "Toplu əməliyyat aparmaq səlahiyyətiniz yoxdur."


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
    return _employee(flags=("can_perform_bulk_operations",))


def _seller() -> Employee:
    """Heç bir flag daşımayan `Satıcı` — menyu bəndini GÖRMƏMƏLİDİR."""
    return _employee(flags=())


# --------------------------------------------------------------------------- #
# Sahtələr — Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


class _BulkImportUseCase:
    def __init__(
        self,
        *,
        preview: BulkImportPreview | None = None,
        preview_error: Exception | None = None,
        report: BulkImportReport | None = None,
        import_error: Exception | None = None,
    ) -> None:
        self.preview = preview
        self.preview_error = preview_error
        self.report = report
        self.import_error = import_error
        self.preview_calls = 0
        self.import_calls = 0

    def preview_csv(self, *, tenant_id: Any, actor: Any, csv_bytes: bytes) -> BulkImportPreview:
        self.preview_calls += 1
        if self.preview_error is not None:
            raise self.preview_error
        assert self.preview is not None
        return self.preview

    def import_employees(
        self, *, tenant_id: Any, actor: Any, csv_bytes: bytes, file_ref: str | None
    ) -> BulkImportReport:
        self.import_calls += 1
        if self.import_error is not None:
            raise self.import_error
        assert self.report is not None
        return self.report


class _StoreTemplateUseCase:
    def __init__(
        self,
        *,
        templates: list[StoreTemplate] | None = None,
        capture_error: Exception | None = None,
        apply_error: Exception | None = None,
        deactivate_error: Exception | None = None,
        apply_result: Any = None,
    ) -> None:
        self.templates = list(templates or [])
        self.capture_error = capture_error
        self.apply_error = apply_error
        self.deactivate_error = deactivate_error
        self.apply_result = apply_result
        self.captured: list[tuple[str, Any, dict[str, object]]] = []
        self.applied: list[tuple[Any, Any]] = []
        self.deactivated: list[Any] = []

    def list_templates(
        self, *, tenant_id: Any, actor: Any, include_inactive: bool = False
    ) -> list[StoreTemplate]:
        return list(self.templates)

    def capture(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        name: str,
        source_store_id: Any,
        config_snapshot: dict[str, object],
    ) -> Any:
        if self.capture_error is not None:
            raise self.capture_error
        self.captured.append((name, source_store_id, dict(config_snapshot)))
        return object()

    def apply(self, *, tenant_id: Any, actor: Any, template_id: Any, new_store: Any) -> Any:
        if self.apply_error is not None:
            raise self.apply_error
        self.applied.append((template_id, new_store))
        return self.apply_result

    def deactivate(self, *, tenant_id: Any, actor: Any, template_id: Any) -> None:
        if self.deactivate_error is not None:
            raise self.deactivate_error
        self.deactivated.append(template_id)


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConnection:
    """SQL sorğularını MƏTNƏ görə ayırd edir — real sürücü YOXDUR, TAM sahtədir."""

    def __init__(
        self,
        *,
        store_name_rows: list[dict[str, Any]] | None = None,
        store_choice_rows: list[dict[str, Any]] | None = None,
        single_store_row: dict[str, Any] | None = None,
        position_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._store_name_rows = store_name_rows or []
        self._store_choice_rows = store_choice_rows or []
        self._single_store_row = single_store_row
        self._position_rows = position_rows or []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _FakeCursor:
        self.calls.append((sql, params))
        text = " ".join(sql.split())
        if "employees e" in text:
            return _FakeCursor(self._position_rows)
        if "ANY(%s)" in text:
            return _FakeCursor(self._store_name_rows)
        if "is_active ORDER BY name" in text:
            return _FakeCursor(self._store_choice_rows)
        return _FakeCursor([self._single_store_row] if self._single_store_row else [])


class _Uow:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection


class _Limits:
    def __init__(self, value: int) -> None:
        self._value = value

    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        return self._value


class _Session:
    def __init__(
        self,
        *,
        bulk_import: _BulkImportUseCase,
        store_templates: _StoreTemplateUseCase,
        connection: _FakeConnection | None = None,
        limit_value: int = 50,
    ) -> None:
        self.tenant_id = TENANT
        self.bulk_employee_import = bulk_import
        self.store_templates = store_templates
        self.uow = _Uow(connection or _FakeConnection())
        self.limits = _Limits(limit_value)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: _Session) -> None:
        self._session = session
        self.tenant_id = TENANT

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


class _ScreenStub:
    """`BulkOperationsScreen`-in YAZI-yönlü setter API-sinin sahtəsi."""

    def __init__(self) -> None:
        self.theme = object()
        self.previews: list[dict[str, Any]] = []
        self.import_messages: list[tuple[str, bool]] = []
        self.templates: list[list[dict[str, str]]] = []
        self.template_messages: list[tuple[str, bool]] = []
        self.cleared_preview_calls = 0

    def set_preview(self, **kwargs: Any) -> None:
        self.previews.append(kwargs)

    def clear_preview(self, *, keep_file: bool = False) -> None:
        self.cleared_preview_calls += 1

    def set_import_message(self, message: str, *, error: bool = False) -> None:
        self.import_messages.append((message, error))

    def set_templates(self, rows: list[dict[str, str]]) -> None:
        self.templates.append(rows)

    def set_template_message(self, message: str, *, error: bool = False) -> None:
        self.template_messages.append((message, error))


def _controller(session: _Session, actor: Employee | None = None) -> BulkOperationsController:
    return BulkOperationsController(_Context(session), actor or _hr_admin())  # type: ignore[arg-type]


def _template(
    *,
    template_id: StoreTemplateId | None = None,
    based_on_store_id: StoreId | None = None,
    is_active: bool = True,
    config_snapshot: dict[str, object] | None = None,
) -> StoreTemplate:
    import datetime as dt

    snapshot = config_snapshot or {"store_name": "Bellona 28 May", "positions": ["Satıcı"]}
    deactivated_at = None if is_active else dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    return StoreTemplate(
        name="Standart Supermarket",
        tenant_id=TENANT,
        is_active=is_active,
        deactivated_at=deactivated_at,
        store_template_id=template_id or new_store_template_id(),
        based_on_store_id=based_on_store_id,
        config_snapshot=snapshot,
        created_by=None,
    )


# --------------------------------------------------------------------------- #
# Menyu: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (CLAUDE.md bölmə 3)
# --------------------------------------------------------------------------- #


def test_menu_entry_requires_the_bulk_operations_flag() -> None:
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "bulk_operations")
    assert entry.required_flag == "can_perform_bulk_operations"


def test_flagless_employee_does_not_see_the_menu_entry() -> None:
    registry = build_default_registry()
    assert registry.is_visible("bulk_operations", _seller(), now=NOW) is False
    assert registry.is_visible("bulk_operations", _hr_admin(), now=NOW) is True


# --------------------------------------------------------------------------- #
# `_preview_payload` / `_result_payload` — sətir-sütun + limit, Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


def _preview(
    *, total_rows: int, valid_count: int, errors: tuple[CsvRowError, ...], truncated: bool
) -> BulkImportPreview:
    return BulkImportPreview(
        header_columns=("first_name", "last_name", "position_code", "username"),
        total_data_rows=total_rows,
        # `valid_rows`-un DOMEN NÖVÜ (`ParsedEmployeeRow`) burada ƏHƏMİYYƏTSİZDİR
        # — `_preview_payload` yalnız `len()` işlədir (bax onun şərhi).
        valid_rows=tuple(range(valid_count)),  # type: ignore[arg-type]
        errors=errors,
        displayed_errors=errors if not truncated else errors[:1],
        errors_truncated=truncated,
    )


def test_preview_payload_shows_row_and_reason_for_each_error() -> None:
    """Önizləmə xətaları sətir + səbəb açarları ilə ekrana ötürülür."""
    errors = (
        CsvRowError(2, "Rol tapılmadı və ya deaktivdir: KASSIR2"),
        CsvRowError(4, "Bu istifadəçi adı artıq mövcuddur: e.mammadov"),
    )
    preview = _preview(total_rows=4, valid_count=2, errors=errors, truncated=False)

    payload = _preview_payload(preview)

    assert payload.total_rows == 4
    assert payload.valid_count == 2
    assert payload.error_count == 2
    assert payload.errors == [
        {"row": "2", "message": "Rol tapılmadı və ya deaktivdir: KASSIR2"},
        {"row": "4", "message": "Bu istifadəçi adı artıq mövcuddur: e.mammadov"},
    ]
    assert payload.truncated_extra == 0


def test_preview_payload_reports_truncation_only_when_flagged() -> None:
    """ROOT tavanı aşılanda `truncated_extra` > 0 — aksinə hesablanmır."""
    errors = tuple(CsvRowError(i, f"xəta {i}") for i in range(1, 4))
    preview = _preview(total_rows=3, valid_count=0, errors=errors, truncated=True)

    payload = _preview_payload(preview)

    assert payload.errors == [{"row": "1", "message": "xəta 1"}]
    assert payload.truncated_extra == 2  # 3 xəta - 1 göstərilən


def test_preview_payload_handles_the_header_only_file_without_crashing() -> None:
    """Boş fayl (yalnız başlıq) — `total_rows=0`, heç bir sətir siyahıya düşmür."""
    preview = _preview(total_rows=0, valid_count=0, errors=(), truncated=False)

    payload = _preview_payload(preview)

    assert payload.total_rows == 0
    assert payload.valid_count == 0
    assert payload.errors == []
    assert payload.truncated_extra == 0


def _report(
    *, success: int, errors: tuple[CsvRowError, ...], created: tuple[BulkCreatedEmployee, ...]
) -> BulkImportReport:
    return BulkImportReport(
        log_id=new_bulk_import_log_id(),
        row_count=success + len(errors),
        success_count=success,
        error_count=len(errors),
        errors=errors,
        created=created,
    )


def test_result_payload_shows_partial_import_counts_correctly() -> None:
    """3 uğurlu + 2 uğursuz — qismən idxal nəticəsi DÜZGÜN göstərilir."""
    created = tuple(
        BulkCreatedEmployee(
            row_number=i,
            employee_id=new_employee_id(),
            username=f"u{i}",
            temporary_password=f"P{i}!",
        )
        for i in range(1, 4)
    )
    errors = (CsvRowError(4, "xəta A"), CsvRowError(5, "xəta B"))
    report = _report(success=3, errors=errors, created=created)

    payload = _result_payload(report, limit=50)

    assert payload.success_count == 3
    assert payload.error_count == 2
    assert len(payload.errors) == 2
    assert payload.truncated_extra == 0
    assert [c["username"] for c in payload.created] == ["u1", "u2", "u3"]


def test_result_payload_carries_temporary_passwords_through_untouched() -> None:
    """Müvəqqəti şifrələr DƏYİŞMƏDƏN (heç bir hash/log çevrilməsi olmadan) daşınır."""
    created = (
        BulkCreatedEmployee(
            row_number=1,
            employee_id=new_employee_id(),
            username="a.mammadov",
            temporary_password="Xk9#mQ2p",
        ),
    )
    report = _report(success=1, errors=(), created=created)

    payload = _result_payload(report, limit=50)

    assert payload.created == [{"username": "a.mammadov", "temporary_password": "Xk9#mQ2p"}]


def test_result_payload_truncates_error_display_with_the_root_limit() -> None:
    """Yaratma anında yaranan ƏLAVƏ xətalar da limitə tabedir, aqreqat say İSƏ TAMDIR."""
    errors = tuple(CsvRowError(i, f"xəta {i}") for i in range(1, 8))
    report = _report(success=0, errors=errors, created=())

    payload = _result_payload(report, limit=3)

    assert payload.error_count == 7
    assert len(payload.errors) == 3
    assert payload.truncated_extra == 4


# --------------------------------------------------------------------------- #
# CSV idxalı — kontroller, Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


def test_preview_without_a_selected_file_shows_a_message_and_opens_no_session() -> None:
    use_case = _BulkImportUseCase()
    session = _Session(bulk_import=use_case, store_templates=_StoreTemplateUseCase())
    controller = _controller(session)
    screen = _ScreenStub()

    controller._on_preview(screen, "")  # type: ignore[arg-type]

    assert use_case.preview_calls == 0
    assert screen.import_messages[-1] == ("Zəhmət olmasa əvvəlcə CSV faylı seçin.", True)


def test_preview_missing_file_on_disk_is_reported_without_crashing(tmp_path: Any) -> None:
    use_case = _BulkImportUseCase()
    session = _Session(bulk_import=use_case, store_templates=_StoreTemplateUseCase())
    controller = _controller(session)
    screen = _ScreenStub()
    missing = tmp_path / "silinmis.csv"

    controller._on_preview(screen, str(missing))  # type: ignore[arg-type]

    assert use_case.preview_calls == 0
    assert screen.import_messages[-1][1] is True


def test_preview_success_populates_the_screen(tmp_path: Any) -> None:
    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"first_name,last_name,position_code,username\nAli,Veli,SATICI,a.veli\n")
    preview = _preview(total_rows=1, valid_count=1, errors=(), truncated=False)
    use_case = _BulkImportUseCase(preview=preview)
    session = _Session(bulk_import=use_case, store_templates=_StoreTemplateUseCase())
    controller = _controller(session)
    screen = _ScreenStub()

    controller._on_preview(screen, str(csv_path))  # type: ignore[arg-type]

    assert use_case.preview_calls == 1
    assert session.commits == 1
    assert screen.previews[-1]["total_rows"] == 1
    assert screen.previews[-1]["valid_count"] == 1


def test_preview_permission_error_reaches_the_screen_as_user_message(tmp_path: Any) -> None:
    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    use_case = _BulkImportUseCase(preview_error=_DeniedError("flag yoxdur"))
    session = _Session(bulk_import=use_case, store_templates=_StoreTemplateUseCase())
    controller = _controller(session)
    screen = _ScreenStub()

    controller._on_preview(screen, str(csv_path))  # type: ignore[arg-type]

    assert screen.import_messages[-1] == (_DeniedError.user_message, True)
    assert session.commits == 0


def test_import_partial_success_commits_once_and_hands_off_to_result_dialog(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """3 uğurlu + 2 uğursuz nəticə DÜZGÜN `_show_result`-a ötürülür, forma sıfırlanır."""
    from src.presentation.controllers import bulk_operations as module

    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")

    created = tuple(
        BulkCreatedEmployee(
            row_number=i,
            employee_id=new_employee_id(),
            username=f"u{i}",
            temporary_password=f"Şifrə{i}!",
        )
        for i in range(1, 4)
    )
    errors = (CsvRowError(4, "xəta A"), CsvRowError(5, "xəta B"))
    report = _report(success=3, errors=errors, created=created)
    use_case = _BulkImportUseCase(report=report)
    session = _Session(
        bulk_import=use_case, store_templates=_StoreTemplateUseCase(), limit_value=50
    )
    controller = _controller(session)
    screen = _ScreenStub()

    recorded: dict[str, Any] = {}

    def _fake_show_result(
        self: Any, screen_arg: Any, report_arg: Any, *, preview_error_limit: int
    ) -> None:
        recorded["report"] = report_arg
        recorded["limit"] = preview_error_limit

    monkeypatch.setattr(module.BulkOperationsController, "_show_result", _fake_show_result)

    controller._on_import(screen, str(csv_path))  # type: ignore[arg-type]

    assert use_case.import_calls == 1
    assert session.commits == 1, "Yekun `bulk_log.finish()` + audit sətri üçün BİR dəfə commit"
    assert recorded["report"] is report
    assert recorded["limit"] == 50
    assert screen.cleared_preview_calls == 1
    # Şifrə heç bir mesaj sətrinə SIZMIR — YALNIZ dialoqa (`_show_result`) ötürülür.
    assert all("Şifrə" not in message for message, _error in screen.import_messages)


def test_import_failure_never_opens_the_result_dialog(tmp_path: Any, monkeypatch: Any) -> None:
    from src.presentation.controllers import bulk_operations as module

    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    use_case = _BulkImportUseCase(import_error=_DeniedError("flag yoxdur"))
    session = _Session(bulk_import=use_case, store_templates=_StoreTemplateUseCase())
    controller = _controller(session)
    screen = _ScreenStub()

    called: list[bool] = []
    monkeypatch.setattr(
        module.BulkOperationsController,
        "_show_result",
        lambda *a, **k: called.append(True),
    )

    controller._on_import(screen, str(csv_path))  # type: ignore[arg-type]

    assert called == []
    assert screen.import_messages[-1] == (_DeniedError.user_message, True)
    assert screen.cleared_preview_calls == 0


# --------------------------------------------------------------------------- #
# Mağaza şablonu — kontroller, Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


def test_capture_snapshot_reads_store_name_and_active_position_names() -> None:
    store_id = new_store_id()
    connection = _FakeConnection(
        single_store_row={"name": "Bellona 28 May"},
        position_rows=[{"name_az": "Kassir"}, {"name_az": "Satıcı"}],
    )
    session = _Session(
        bulk_import=_BulkImportUseCase(),
        store_templates=_StoreTemplateUseCase(),
        connection=connection,
    )

    snapshot = _capture_snapshot(session, store_id)  # type: ignore[arg-type]

    assert snapshot == {"store_name": "Bellona 28 May", "positions": ["Kassir", "Satıcı"]}


def test_format_snapshot_lists_positions_or_falls_back_to_a_message() -> None:
    assert _format_snapshot({"positions": ["Satıcı", "Kassir"]}) == "Satıcı, Kassir"
    assert _format_snapshot({"positions": []}) == "Bu şablonda rol məlumatı saxlanmayıb."
    assert _format_snapshot({}) == "Bu şablonda rol məlumatı saxlanmayıb."


def test_submit_capture_builds_the_snapshot_from_the_source_store_and_refreshes() -> None:
    store_id = new_store_id()
    connection = _FakeConnection(
        single_store_row={"name": "Bellona 28 May"},
        position_rows=[{"name_az": "Satıcı"}],
        store_choice_rows=[],
    )
    templates_uc = _StoreTemplateUseCase(templates=[])
    session = _Session(
        bulk_import=_BulkImportUseCase(), store_templates=templates_uc, connection=connection
    )
    controller = _controller(session)
    screen = _ScreenStub()

    controller._submit_capture(screen, "Standart Supermarket", str(store_id))  # type: ignore[arg-type]

    assert len(templates_uc.captured) == 1
    name, captured_store_id, snapshot = templates_uc.captured[0]
    assert name == "Standart Supermarket"
    assert captured_store_id == store_id
    assert snapshot == {"store_name": "Bellona 28 May", "positions": ["Satıcı"]}
    # 2 commit: (1) `capture()` yazısı, (2) `refresh_templates()`-in YENİ
    # sessiyadakı oxu-commiti (`employee_documents.py::_load` ilə eyni naxış).
    assert session.commits == 2
    assert screen.templates, "capture-dan sonra siyahı YENİDƏN oxunmalıdır"


def test_submit_capture_with_malformed_store_id_never_opens_a_session() -> None:
    templates_uc = _StoreTemplateUseCase()
    session = _Session(bulk_import=_BulkImportUseCase(), store_templates=templates_uc)
    controller = _controller(session)
    screen = _ScreenStub()

    controller._submit_capture(screen, "Ad", "mağaza-yox")  # type: ignore[arg-type]

    assert templates_uc.captured == []
    assert session.commits == 0
    assert screen.template_messages[-1][1] is True


def test_submit_capture_domain_error_is_shown_as_the_user_message() -> None:
    templates_uc = _StoreTemplateUseCase(capture_error=_DeniedError("boş snapshot"))
    connection = _FakeConnection(single_store_row={"name": "X"}, position_rows=[])
    session = _Session(
        bulk_import=_BulkImportUseCase(), store_templates=templates_uc, connection=connection
    )
    controller = _controller(session)
    screen = _ScreenStub()

    controller._submit_capture(screen, "Ad", str(new_store_id()))  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.template_messages[-1] == (_DeniedError.user_message, True)


def test_submit_apply_builds_a_new_store_draft_and_refreshes() -> None:
    from src.application.use_cases.first_run_setup import StoreDraft

    template_id = new_store_template_id()
    apply_result = _apply_result(template_id)
    templates_uc = _StoreTemplateUseCase(apply_result=apply_result)
    session = _Session(bulk_import=_BulkImportUseCase(), store_templates=templates_uc)
    controller = _controller(session)
    screen = _ScreenStub()

    controller._submit_apply(
        screen,  # type: ignore[arg-type]
        template_id,
        code="BEL-29",
        name="Bellona 29 May",
        brand="Bellona",
        address="",
    )

    assert len(templates_uc.applied) == 1
    applied_template_id, new_store = templates_uc.applied[0]
    assert applied_template_id == template_id
    assert isinstance(new_store, StoreDraft)
    assert new_store.code == "BEL-29"
    assert new_store.name == "Bellona 29 May"
    assert new_store.brand == "Bellona"
    assert session.commits == 2  # (1) `apply()` yazısı, (2) `refresh_templates()` oxu-commiti
    assert any("Bellona 29 May" in message for message, _error in screen.template_messages)
    assert screen.templates, "tətbiqdən sonra siyahı YENİDƏN oxunmalıdır"


def _apply_result(template_id: StoreTemplateId) -> Any:
    from src.application.use_cases.bulk_operations import StoreTemplateApplyResult

    return StoreTemplateApplyResult(
        new_store_id=new_store_id(),
        template_id=template_id,
        template_name="Standart Supermarket",
        config_snapshot={"positions": ["Satıcı"]},
    )


def test_on_deactivate_soft_deletes_and_refreshes() -> None:
    template_id = new_store_template_id()
    templates_uc = _StoreTemplateUseCase(templates=[_template(template_id=template_id)])
    session = _Session(bulk_import=_BulkImportUseCase(), store_templates=templates_uc)
    controller = _controller(session)
    screen = _ScreenStub()

    controller._on_deactivate(screen, str(template_id))  # type: ignore[arg-type]

    assert templates_uc.deactivated == [template_id]
    assert session.commits == 2  # (1) `deactivate()` yazısı, (2) `refresh_templates()` oxu-commiti
    assert screen.templates, "deaktivdən sonra siyahı YENİDƏN oxunmalıdır"


def test_refresh_templates_resolves_source_store_names_and_status() -> None:
    active_id = new_store_template_id()
    inactive_id = new_store_template_id()
    store_id = new_store_id()
    templates_uc = _StoreTemplateUseCase(
        templates=[
            _template(template_id=active_id, based_on_store_id=store_id, is_active=True),
            _template(template_id=inactive_id, based_on_store_id=None, is_active=False),
        ]
    )
    connection = _FakeConnection(store_name_rows=[{"id": store_id, "name": "Bellona 28 May"}])
    session = _Session(
        bulk_import=_BulkImportUseCase(), store_templates=templates_uc, connection=connection
    )
    controller = _controller(session)
    screen = _ScreenStub()

    controller.refresh_templates(screen)  # type: ignore[arg-type]

    rows = {row["id"]: row for row in screen.templates[-1]}
    assert rows[str(active_id)]["source_store"] == "Bellona 28 May"
    assert rows[str(active_id)]["status"] == "Aktiv"
    assert rows[str(inactive_id)]["source_store"] == "—"
    assert rows[str(inactive_id)]["status"] == "Deaktiv"


def test_refresh_templates_with_an_empty_catalog_does_not_crash() -> None:
    session = _Session(
        bulk_import=_BulkImportUseCase(), store_templates=_StoreTemplateUseCase(templates=[])
    )
    controller = _controller(session)
    screen = _ScreenStub()

    controller.refresh_templates(screen)  # type: ignore[arg-type]

    assert screen.templates[-1] == []


def test_store_choices_are_scoped_to_the_tenant_and_active_stores() -> None:
    store_id = new_store_id()
    connection = _FakeConnection(store_choice_rows=[{"id": store_id, "name": "Bellona 28 May"}])
    session = _Session(
        bulk_import=_BulkImportUseCase(),
        store_templates=_StoreTemplateUseCase(),
        connection=connection,
    )

    choices = _store_choices(session)  # type: ignore[arg-type]

    assert choices == [(str(store_id), "Bellona 28 May")]
    assert connection.calls[0][1][0] == TENANT


def test_to_template_rows_with_no_templates_returns_an_empty_list() -> None:
    connection = _FakeConnection()
    session = _Session(
        bulk_import=_BulkImportUseCase(),
        store_templates=_StoreTemplateUseCase(),
        connection=connection,
    )

    assert _to_template_rows(session, []) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Maket / canlı paritet (CLAUDE.md §6)
# --------------------------------------------------------------------------- #


def test_preview_error_rows_share_the_same_keys_as_the_mockup() -> None:
    errors = (CsvRowError(2, "xəta"),)
    payload = _preview_payload(
        _preview(total_rows=1, valid_count=0, errors=errors, truncated=False)
    )
    assert set(payload.errors[0]) == set(preview_data.BULK_IMPORT_PREVIEW_ERRORS[0])


def test_template_rows_share_the_same_keys_as_the_mockup() -> None:
    store_id = new_store_id()
    connection = _FakeConnection(store_name_rows=[{"id": store_id, "name": "Bellona 28 May"}])
    session = _Session(
        bulk_import=_BulkImportUseCase(),
        store_templates=_StoreTemplateUseCase(),
        connection=connection,
    )
    live_row = _to_template_rows(  # type: ignore[arg-type]
        session, [_template(based_on_store_id=store_id, is_active=True)]
    )[0]

    assert set(live_row) == set(preview_data.STORE_TEMPLATES[0])


# --------------------------------------------------------------------------- #
# Ekranların ÖZÜ — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


@requires_qt
def test_empty_file_preview_does_not_crash_and_disables_import(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import BulkOperationsScreen

    screen = BulkOperationsScreen(theme)
    qtbot.addWidget(screen)

    screen.set_preview(total_rows=0, valid_count=0, error_count=0, errors=[], truncated_extra=0)

    assert screen._import_button.isEnabled() is False
    assert screen._error_table.row_count == 0


@requires_qt
def test_preview_errors_render_as_table_rows_and_gate_the_import_button(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import BulkOperationsScreen

    screen = BulkOperationsScreen(theme)
    qtbot.addWidget(screen)

    screen.set_preview(
        total_rows=3,
        valid_count=0,
        error_count=3,
        errors=[
            {"row": "2", "message": "xəta A"},
            {"row": "3", "message": "xəta B"},
            {"row": "4", "message": "xəta C"},
        ],
        truncated_extra=2,
    )

    assert screen._error_table.row_count == 3
    assert screen._import_button.isEnabled() is False, "Düzgün sətir yoxdursa idxal bloklanır"
    assert screen._truncated_note.isVisibleTo(screen) is True

    screen.set_preview(
        total_rows=2,
        valid_count=1,
        error_count=1,
        errors=[{"row": "2", "message": "xəta"}],
        truncated_extra=0,
    )
    assert screen._import_button.isEnabled() is True


@requires_qt
def test_empty_template_catalog_shows_the_empty_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import BulkOperationsScreen

    screen = BulkOperationsScreen(theme)
    qtbot.addWidget(screen)

    screen.set_templates([])

    assert screen._template_empty.isVisibleTo(screen) is True
    assert screen._template_table.row_count == 0


@requires_qt
def test_template_row_buttons_emit_apply_and_deactivate_with_the_row_id(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.bulk_operations import BulkOperationsScreen

    screen = BulkOperationsScreen(theme)
    qtbot.addWidget(screen)

    applied: list[str] = []
    deactivated: list[str] = []
    screen.apply_requested.connect(applied.append)
    screen.deactivate_requested.connect(deactivated.append)

    screen.set_templates(
        [
            {
                "id": "st-1",
                "name": "Standart",
                "source_store": "Bellona 28 May",
                "setting_count": "2",
                "captured_at": "2026-07-01",
                "status": "Aktiv",
            }
        ]
    )

    buttons = screen._template_table.findChildren(QPushButton)
    next(b for b in buttons if b.text() == "Tətbiq Et").click()
    next(b for b in buttons if b.text() == "Deaktiv Et").click()

    assert applied == ["st-1"]
    assert deactivated == ["st-1"]


@requires_qt
def test_capture_dialog_requires_a_name_and_a_source_store(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import StoreTemplateCaptureDialog

    dialog = StoreTemplateCaptureDialog(theme, stores=[])
    qtbot.addWidget(dialog)

    emitted: list[tuple[str, str]] = []
    dialog.submitted.connect(lambda name, store_id: emitted.append((name, store_id)))
    dialog._on_submit()
    assert emitted == []
    assert dialog._name.has_error is True

    dialog._name.set_text("Standart Supermarket")
    dialog._on_submit()
    assert emitted == [], "Boş mağaza siyahısından şablon çıxarıla bilməz"
    assert dialog._error.isVisibleTo(dialog) is True


@requires_qt
def test_capture_dialog_submits_the_chosen_store(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import StoreTemplateCaptureDialog

    dialog = StoreTemplateCaptureDialog(theme, stores=[("store-1", "Bellona 28 May")])
    qtbot.addWidget(dialog)

    emitted: list[tuple[str, str]] = []
    dialog.submitted.connect(lambda name, store_id: emitted.append((name, store_id)))
    dialog._name.set_text("Standart Supermarket")

    dialog._on_submit()

    assert emitted == [("Standart Supermarket", "store-1")]


@requires_qt
def test_apply_dialog_shows_what_does_not_transfer_before_submission(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.bulk_operations import (
        NOT_TRANSFERRED_TEXT,
        StoreTemplateApplyDialog,
    )

    dialog = StoreTemplateApplyDialog(
        theme, template_name="Standart Supermarket", snapshot_summary="Satıcı, Kassir"
    )
    qtbot.addWidget(dialog)

    texts = {label.text() for label in dialog.findChildren(QLabel)}
    assert NOT_TRANSFERRED_TEXT in texts
    assert "Satıcı, Kassir" in texts
    assert "işçilər" in NOT_TRANSFERRED_TEXT
    assert "cərimə" in NOT_TRANSFERRED_TEXT


@requires_qt
def test_apply_dialog_requires_code_name_and_brand(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import StoreTemplateApplyDialog

    dialog = StoreTemplateApplyDialog(theme, template_name="Standart", snapshot_summary="Satıcı")
    qtbot.addWidget(dialog)

    emitted: list[tuple[str, str, str, str]] = []
    dialog.submitted.connect(lambda *args: emitted.append(args))

    dialog._on_submit()
    assert emitted == []
    assert dialog._code.has_error is True

    dialog._code.set_text("BEL-29")
    dialog._on_submit()
    assert emitted == []
    assert dialog._name.has_error is True

    dialog._name.set_text("Bellona 29 May")
    dialog._on_submit()
    assert emitted == []
    assert dialog._brand.has_error is True

    dialog._brand.set_text("Bellona")
    dialog._on_submit()
    assert emitted == [("BEL-29", "Bellona 29 May", "Bellona", "")]


@requires_qt
def test_result_dialog_shows_passwords_with_a_one_time_warning(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.bulk_operations import BulkImportResultDialog

    dialog = BulkImportResultDialog(
        theme,
        success_count=3,
        error_count=2,
        errors=[{"row": "4", "message": "xəta A"}, {"row": "5", "message": "xəta B"}],
        truncated_extra=0,
        created=[
            {"username": "a.mammadov", "temporary_password": "Xk9#mQ2p"},
            {"username": "b.aliyev", "temporary_password": "Yt7$nR4w"},
        ],
    )
    qtbot.addWidget(dialog)

    texts = {label.text() for label in dialog.findChildren(QLabel)}
    assert "a.mammadov" in texts
    assert "Xk9#mQ2p" in texts
    assert "b.aliyev" in texts
    assert "Yt7$nR4w" in texts
    assert any("BİR DAHA GÖSTƏRİLMƏYƏCƏK" in text for text in texts)
    assert any("3 işçi uğurla yaradıldı" in text for text in texts)


@requires_qt
def test_result_dialog_without_created_rows_hides_the_password_section(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.bulk_operations import BulkImportResultDialog

    dialog = BulkImportResultDialog(
        theme,
        success_count=0,
        error_count=2,
        errors=[{"row": "2", "message": "xəta"}],
        truncated_extra=0,
        created=[],
    )
    qtbot.addWidget(dialog)

    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "BİR DAHA GÖSTƏRİLMƏYƏCƏK" not in texts
    assert "Hamısını Kopyala" not in texts


@requires_qt
def test_result_dialog_copy_all_writes_tab_separated_pairs(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import BulkImportResultDialog

    dialog = BulkImportResultDialog(
        theme,
        success_count=2,
        error_count=0,
        errors=[],
        truncated_extra=0,
        created=[
            {"username": "a.mammadov", "temporary_password": "Xk9#mQ2p"},
            {"username": "b.aliyev", "temporary_password": "Yt7$nR4w"},
        ],
    )
    qtbot.addWidget(dialog)

    dialog._copy_all()

    from PySide6.QtGui import QGuiApplication

    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "a.mammadov\tXk9#mQ2p\nb.aliyev\tYt7$nR4w"
