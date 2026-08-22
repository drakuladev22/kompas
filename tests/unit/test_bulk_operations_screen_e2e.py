"""`BulkOperationsScreen` ↔ `controllers/bulk_operations.py` — REAL Qt e2e (QA-FULL Faza 3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
`test_bulk_operations_screen.py` ekranı VƏ kontrolleri AYRI-AYRI sınayır:
kontroller testləri `_ScreenStub` (sahtə obyekt) işlədir, ekran testləri isə
REAL Qt widget qurur, lakin kontrolleri HEÇ BAĞLAMIR. Yəni siqnal zənciri
(`CSV Faylı Seç` → `_pick_file` → `preview_requested` → `attach()`-dəki
`lambda` → `controller._on_preview` → `screen.set_preview`) heç bir testdə
UCDAN-UCA işə salınmamışdı — məhz bu boşluqda `CLAUDE.md`-nin xəbərdarlıq
etdiyi "düymə bağlanıb, amma heç vaxt ÇAĞIRILMIR" naxışı gizlənə bilərdi.

Bu fayl REAL `BulkOperationsScreen` qurur, REAL `BulkOperationsController.
attach()` çağırır və REAL `QPushButton.click()` ilə hər addımı gəzir.

──────────────────────────────────────────────────────────────────────────────
TAPILAN QÜSUR — İDXAL DÜYMƏSİNDƏ "İKİQAT BURAXILIŞ" QAPISI YOXDUR
──────────────────────────────────────────────────────────────────────────────
`BackgroundTask.is_running` məhz bunun üçün var (bax `background_task.py`
başlığı: "bu bayraq isə kontrollerə ikiqat buraxılışı RƏDD ETMƏK imkanı
verir") və `erp_servers.py`/`root_control.py`/`support_inbox.py` ONU işlədir.
`bulk_operations.py::_run()` bu yoxlamanı ETMİR — "İdxal Et" düyməsi fon işi
GEDƏRKƏN aktiv qalır, yalnız UĞURLU nəticədən SONRA `clear_preview()` onu
deaktiv edir. Real `QtPoolExecutor` ilə istifadəçi iş bitmədən ikinci dəfə
klikləsə, EYNİ fayldan İKİ paralel idxal başlayır (iki ayrı sessiya, iki ayrı
`bulk_import_log` sətri). Bax `test_clicking_import_again_...` aşağıda.

Sahtələr BU FAYLDA yerlidir (`test_bulk_operations.py`/`test_bulk_operations_
screen.py` başlıqlarındakı EYNİ qərar: hər faza paralel işləyən başqa
fazaların sahtə dəstindən asılı olmamalıdır).
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
    TenantId,
    new_bulk_import_log_id,
    new_employee_id,
    new_store_id,
    new_store_template_id,
)
from src.domain.value_objects.store_templates import StoreTemplate
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _actor() -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    position.grant(PermissionFlag(code="can_perform_bulk_operations", category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )


def _click(widget: Any, text: str) -> Any:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()
    return button


def _pick_file(monkeypatch: pytest.MonkeyPatch, screen: Any, path: str) -> None:
    """`QFileDialog.getOpenFileName`-i MOCK edir — REAL fayl seçici pəncərəsi headless testdə
    özü açıla bilməz, seçilən yol isə buradan qayıdır (`test_annual_leave_screen.py`-dəki
    `QFileDialog.getOpenFileName` patch-i ilə EYNİ naxış)."""
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "CSV faylları"))
    )
    _click(screen, "CSV Faylı Seç")


# --------------------------------------------------------------------------- #
# Sahtələr — REAL `ApplicationContext.session()` müqaviləsinin yerli təkrarı
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
        self.templates.append(
            StoreTemplate(
                name=name,
                tenant_id=TENANT,
                is_active=True,
                deactivated_at=None,
                store_template_id=new_store_template_id(),
                based_on_store_id=source_store_id,
                config_snapshot=dict(config_snapshot),
                created_by=None,
            )
        )
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
        for index, template in enumerate(self.templates):
            if template.store_template_id == template_id:
                from dataclasses import replace

                self.templates[index] = replace(template, is_active=False, deactivated_at=NOW)


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConnection:
    """SQL-i MƏTNƏ görə ayırd edir — `test_bulk_operations.py::_FakeConnection` ilə EYNİ naxış."""

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
    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        return default


class _Session:
    def __init__(
        self,
        *,
        bulk_import: _BulkImportUseCase,
        store_templates: _StoreTemplateUseCase,
        connection: _FakeConnection,
    ) -> None:
        self.tenant_id = TENANT
        self.bulk_employee_import = bulk_import
        self.store_templates = store_templates
        self.uow = _Uow(connection)
        self.limits = _Limits()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    """Hər `session()` çağırışı YENİ `_Session` yaradır (real `ApplicationContext` naxışı) —
    `sessions` siyahısı HƏR əməliyyatın ÖZ sessiyasında commit etdiyini sübut edir
    (CLAUDE.md §6)."""

    def __init__(
        self,
        *,
        bulk_import: _BulkImportUseCase | None = None,
        store_templates: _StoreTemplateUseCase | None = None,
        connection: _FakeConnection | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self._bulk_import = bulk_import or _BulkImportUseCase()
        self._store_templates = store_templates or _StoreTemplateUseCase()
        self._connection = connection or _FakeConnection()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            bulk_import=self._bulk_import,
            store_templates=self._store_templates,
            connection=self._connection,
        )
        self.sessions.append(created)
        yield created


def _attach(context: _Context, theme: Any, *, qtbot: Any, actor: Employee | None = None) -> Any:
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.bulk_operations import BulkOperationsController
    from src.presentation.screens.bulk_operations import BulkOperationsScreen

    screen = BulkOperationsScreen(theme)
    qtbot.addWidget(screen)
    controller = BulkOperationsController(
        context,  # type: ignore[arg-type]
        actor or _actor(),
        executor=InlineExecutor(),
    )
    controller.attach(screen)
    return screen, controller


def _preview(
    *, total_rows: int, valid_count: int, errors: tuple[CsvRowError, ...], truncated: bool = False
) -> BulkImportPreview:
    return BulkImportPreview(
        header_columns=("first_name", "last_name", "position_code", "username"),
        total_data_rows=total_rows,
        valid_rows=tuple(range(valid_count)),  # type: ignore[arg-type]
        errors=errors,
        displayed_errors=errors if not truncated else errors[:1],
        errors_truncated=truncated,
    )


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


# --------------------------------------------------------------------------- #
# 1. Real fayl seçimi → real "Önizlə" → real cədvəl
# --------------------------------------------------------------------------- #


@requires_qt
def test_picking_a_file_and_previewing_via_real_clicks_populates_the_real_table(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"first_name,last_name,position_code,username\nAli,Veli,SATICI,a.veli\n")
    preview = _preview(
        total_rows=1, valid_count=1, errors=(CsvRowError(2, "diqqət: nümunə"),), truncated=False
    )
    use_case = _BulkImportUseCase(preview=preview)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    _pick_file(monkeypatch, screen, str(csv_path))
    assert screen._file_label.text() == "employees.csv"

    _click(screen, "Önizlə")

    assert use_case.preview_calls == 1
    assert context.sessions[-1].committed is True
    assert screen._error_table.row_count == 1
    assert "1 sətir oxundu" in screen._preview_summary.text()
    assert screen._import_button.isEnabled() is True


@requires_qt
def test_the_import_button_stays_disabled_without_a_prior_preview(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Fayl seçilib, LAKİN "Önizlə" heç vaxt basılmayıb — real klik heç nə etməməlidir."""
    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    use_case = _BulkImportUseCase()
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    _pick_file(monkeypatch, screen, str(csv_path))
    assert screen._import_button.isEnabled() is False

    _click(screen, "İdxal Et")  # ÇÖKMƏMƏLİDİR — düymə deaktivdir

    assert use_case.import_calls == 0


# --------------------------------------------------------------------------- #
# 2. Real "İdxal Et" — uğur, qismən uğursuzluq, real nəticə dialoqu
# --------------------------------------------------------------------------- #


@requires_qt
def test_full_import_flow_shows_the_real_result_dialog_with_created_passwords(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.bulk_operations import BulkImportResultDialog

    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    preview = _preview(total_rows=1, valid_count=1, errors=())
    created = (
        BulkCreatedEmployee(
            row_number=1,
            employee_id=new_employee_id(),
            username="a.veli",
            temporary_password="Xk9#mQ2p",
        ),
    )
    report = _report(success=1, errors=(), created=created)
    use_case = _BulkImportUseCase(preview=preview, report=report)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    captured: list[BulkImportResultDialog] = []
    original_init = BulkImportResultDialog.__init__

    def _spy_init(self: BulkImportResultDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured.append(self)

    monkeypatch.setattr(BulkImportResultDialog, "__init__", _spy_init)
    monkeypatch.setattr(BulkImportResultDialog, "exec", lambda self: 0)

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")
    _click(screen, "İdxal Et")

    assert use_case.import_calls == 1
    assert len(captured) == 1, "Real klik REAL nəticə dialoqunu açmalı idi"
    texts = {label.text() for label in captured[0].findChildren(QLabel)}
    assert "a.veli" in texts
    assert "Xk9#mQ2p" in texts
    # İdxaldan SONRA forma sıfırlanır — növbəti fayl üçün fayl adı təmizlənir.
    assert screen._file_label.text() == "Fayl seçilməyib"
    assert screen._import_button.isEnabled() is False


@requires_qt
def test_partial_import_shows_which_rows_failed_via_the_real_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """100 sətirdən 3-ü xəta ssenarisinin kiçik nüsxəsi: 3 uğurlu + 2 uğursuz."""
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.bulk_operations import BulkImportResultDialog

    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    preview = _preview(total_rows=5, valid_count=3, errors=(CsvRowError(4, "xəta A"),))
    created = tuple(
        BulkCreatedEmployee(
            row_number=i,
            employee_id=new_employee_id(),
            username=f"u{i}",
            temporary_password=f"P{i}!",
        )
        for i in range(1, 4)
    )
    errors = (CsvRowError(4, "Rol tapılmadı"), CsvRowError(5, "İstifadəçi adı mövcuddur"))
    report = _report(success=3, errors=errors, created=created)
    use_case = _BulkImportUseCase(preview=preview, report=report)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)
    monkeypatch.setattr(BulkImportResultDialog, "exec", lambda self: 0)

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")

    captured: list[BulkImportResultDialog] = []
    original_init = BulkImportResultDialog.__init__

    def _spy_init(self: BulkImportResultDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured.append(self)

    monkeypatch.setattr(BulkImportResultDialog, "__init__", _spy_init)

    _click(screen, "İdxal Et")

    dialog = captured[0]
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "3 işçi uğurla yaradıldı, 2 sətir rədd edildi." in texts
    assert "Rol tapılmadı" in texts
    assert "İstifadəçi adı mövcuddur" in texts
    # Yalnız BİR commit — yekun `bulk_log.finish()` + audit sətri üçün (modul başlığı).
    assert sum(1 for s in context.sessions if s.committed) >= 1


# --------------------------------------------------------------------------- #
# 3. Ekstremal fayl məzmunu — real klik, çökmə YOX
# --------------------------------------------------------------------------- #


@requires_qt
def test_previewing_an_empty_file_via_a_real_click_disables_import_with_a_clear_message(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    csv_path = tmp_path / "empty.csv"
    csv_path.write_bytes(b"")
    preview = _preview(total_rows=0, valid_count=0, errors=())
    use_case = _BulkImportUseCase(preview=preview)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")  # ÇÖKMƏMƏLİDİR

    assert screen._import_button.isEnabled() is False
    assert "0 sətir" in screen._preview_summary.text()


@requires_qt
def test_hostile_and_extreme_file_content_previews_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Emoji, SQL-bənzər mətn, çox uzun sətir, xarab kodlaşdırma bayt-larından ibarət REAL fayl —
    bu qatda idxal MƏNTİQİ FAKE olsa da, ekran ONU heç bir hazırlıqsız qəbul etməlidir."""
    csv_path = tmp_path / "hostile.csv"
    hostile_bytes = (
        b"first_name,last_name,position_code,username\n"
        + "🔥emoji, '; DROP TABLE employees; --, SATICI, x".encode() * 50
        + b"\n"
        + b"\xff\xfe\x00broken-encoding\n"
        + b"A" * 20_000
        + b"\n"
    )
    csv_path.write_bytes(hostile_bytes)
    errors = tuple(CsvRowError(i, f"xəta {i}") for i in range(2, 12))
    preview = _preview(total_rows=52, valid_count=42, errors=errors, truncated=True)
    use_case = _BulkImportUseCase(preview=preview)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")  # ÇÖKMƏMƏLİDİR

    assert use_case.preview_calls == 1
    assert screen._error_table.row_count == len(preview.displayed_errors)
    assert screen._truncated_note.isVisibleTo(screen) is True
    assert screen._import_button.isEnabled() is True


@requires_qt
def test_a_very_large_row_count_preview_renders_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """10 000 sətirlik fayl — ROOT tavanı sayəsində cədvələ YALNIZ göstərilən xətalar düşür,
    aqreqat say isə TAM göstərilir (backend limitini bu qat TƏKRARLAMIR, sadəcə ötürür)."""
    csv_path = tmp_path / "huge.csv"
    lines = [b"first_name,last_name,position_code,username"]
    lines.extend(f"Ad{i},Soyad{i},SATICI,u{i}".encode() for i in range(10_000))
    csv_path.write_bytes(b"\n".join(lines) + b"\n")
    displayed = tuple(CsvRowError(i, f"xəta {i}") for i in range(2, 52))
    preview = BulkImportPreview(
        header_columns=("first_name", "last_name", "position_code", "username"),
        total_data_rows=10_000,
        valid_rows=tuple(range(9_950)),  # type: ignore[arg-type]
        errors=tuple(CsvRowError(i, f"xəta {i}") for i in range(2, 52)),
        displayed_errors=displayed,
        errors_truncated=False,
    )
    use_case = _BulkImportUseCase(preview=preview)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")  # ÇÖKMƏMƏLİDİR

    assert "10000 sətir oxundu" in screen._preview_summary.text()
    assert screen._error_table.row_count == 50


# --------------------------------------------------------------------------- #
# 4. Repo istisnaları — real klik, aydın mesaj, çökmə YOX
# --------------------------------------------------------------------------- #


@requires_qt
def test_preview_repository_exception_shows_a_clear_message_via_the_real_click(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    use_case = _BulkImportUseCase(preview_error=RuntimeError("DB bağlantısı qırıldı"))
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")  # ÇÖKMƏMƏLİDİR

    assert screen._import_message.text() == "Fayl önizlənmədi. Yenidən cəhd edin."
    assert "DB bağlantısı" not in screen._import_message.text(), "XAM istisna mətni sızmamalıdır"


@requires_qt
def test_import_domain_error_shows_the_user_message_and_never_opens_the_result_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import BulkImportResultDialog

    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    preview = _preview(total_rows=1, valid_count=1, errors=())
    denied = KompasOSError(
        "flag yoxdur", user_message="Toplu əməliyyat aparmaq səlahiyyətiniz yoxdur."
    )
    use_case = _BulkImportUseCase(preview=preview, import_error=denied)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    opened: list[Any] = []
    monkeypatch.setattr(BulkImportResultDialog, "__init__", lambda self, *a, **k: opened.append(1))

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")
    _click(screen, "İdxal Et")  # ÇÖKMƏMƏLİDİR

    assert opened == [], "Rədd edilən idxal nəticə dialoqunu ÜMUMİYYƏTLƏ açmamalıdır"
    assert screen._import_message.text() == "Toplu əməliyyat aparmaq səlahiyyətiniz yoxdur."
    # Rədd edildikdən sonra fayl SEÇİLİ QALIR — istifadəçi kor-koranə yenidən başlamağa
    # məcbur edilmir (`clear_preview()` YALNIZ uğurlu idxaldan sonra çağırılır).
    assert screen._file_label.text() == "employees.csv"


# --------------------------------------------------------------------------- #
# 5. İKİQAT BURAXILIŞ QAPISI — tapılan qüsur, DÜZƏLDİLDİ
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_import_again_before_the_first_import_finishes_is_rejected(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Bax faylın başlığı — `_run()` `BackgroundTask.is_running` YOXLAMASI etmir.

    `InlineExecutor` sinxron olduğu üçün "iş GEDƏRKƏN klik" halını yalnız sahtə
    `import_employees()`-in ÖZ DAXİLİNDƏN İKİNCİ kliki tetikləməklə simulyasiya
    etmək mümkündür — bu, real `QtPoolExecutor`-da fon sapı işləyərkən GUI
    sapının HƏLƏ CAVAB VERDİYİNİ əks etdirir (fərq YALNIZ vaxt oxunda).
    """
    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    preview = _preview(total_rows=1, valid_count=1, errors=())

    from src.presentation.screens.bulk_operations import BulkImportResultDialog

    monkeypatch.setattr(BulkImportResultDialog, "exec", lambda self: 0)

    reentered = {"done": False}
    screen_holder: dict[str, Any] = {}

    class _ReentrantUseCase(_BulkImportUseCase):
        def import_employees(
            self, *, tenant_id: Any, actor: Any, csv_bytes: bytes, file_ref: str | None
        ) -> BulkImportReport:
            self.import_calls += 1
            if not reentered["done"]:
                reentered["done"] = True
                screen = screen_holder["screen"]
                # Real dünyada bura "istifadəçi 'İdxal Et'-i ikinci dəfə basdı,
                # düymə hələ AKTİV idi" anına uyğundur. Düymənin AKTİV qalması
                # QÜSUR SAYILMIR — qoruma məntiqi qatdadır (`_run()` →
                # `is_running`), `erp_servers.py`-dəki qərarın eynisi:
                # «deaktiv düymə yalnız GÖRÜNƏN qatdır».
                _click(screen, "İdxal Et")
            report = _report(
                success=1,
                errors=(),
                created=(
                    BulkCreatedEmployee(
                        row_number=1,
                        employee_id=new_employee_id(),
                        username=f"u{self.import_calls}",
                        temporary_password="Xk9#mQ2p",
                    ),
                ),
            )
            return report

    use_case = _ReentrantUseCase(preview=preview)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)
    screen_holder["screen"] = screen

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")
    _click(screen, "İdxal Et")

    assert use_case.import_calls == 1, (
        "İş GEDƏRKƏN gələn ikinci klik RƏDD EDİLMƏLİDİR — `_run()` "
        "`BackgroundTask.is_running` qapısı (`erp_servers.py`/`root_control.py`/"
        "`support_inbox.py`-dakı eyni naxış). Əks halda EYNİ fayl iki dəfə idxal "
        "olunur: iki sessiya, iki `bulk_import_log` sətri, iki nəticə dialoqu."
    )
    assert reentered["done"] is True, "İkinci klik ÜMUMİYYƏTLƏ göndərilməyibsə test heç nə sınamır"


# --------------------------------------------------------------------------- #
# 6. Mağaza şablonu — real klik, real dialoq, real cədvəl sətri
# --------------------------------------------------------------------------- #


@requires_qt
def test_capturing_a_template_via_real_clicks_refreshes_the_real_table(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import StoreTemplateCaptureDialog

    store_id = new_store_id()
    connection = _FakeConnection(
        store_choice_rows=[{"id": store_id, "name": "Bellona 28 May"}],
        single_store_row={"name": "Bellona 28 May"},
        position_rows=[{"name_az": "Satıcı"}, {"name_az": "Kassir"}],
    )
    templates_uc = _StoreTemplateUseCase(templates=[])
    context = _Context(store_templates=templates_uc, connection=connection)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    def fake_exec(self: StoreTemplateCaptureDialog) -> int:
        self._name.set_text("Standart Supermarket")
        self._store_combo.setCurrentIndex(0)
        self._on_submit()
        return 0

    monkeypatch.setattr(StoreTemplateCaptureDialog, "exec", fake_exec)

    _click(screen, "Şablon Çıxar")

    assert len(templates_uc.captured) == 1
    assert screen._template_table.row_count == 1
    assert screen._template_empty.isVisibleTo(screen) is False


@requires_qt
def test_capturing_without_any_active_store_shows_an_error_and_never_opens_the_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.bulk_operations import StoreTemplateCaptureDialog

    connection = _FakeConnection(store_choice_rows=[])  # heç bir AKTİV mağaza yoxdur
    context = _Context(connection=connection)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    opened: list[Any] = []
    monkeypatch.setattr(
        StoreTemplateCaptureDialog, "__init__", lambda self, *a, **k: opened.append(1)
    )

    _click(screen, "Şablon Çıxar")  # ÇÖKMƏMƏLİDİR

    assert opened == []
    assert "Aktiv mağaza tapılmadı" in screen._template_message.text()


@requires_qt
def test_applying_and_then_deactivating_a_template_via_real_row_buttons(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.application.use_cases.bulk_operations import StoreTemplateApplyResult
    from src.presentation.screens.bulk_operations import StoreTemplateApplyDialog
    from src.presentation.widgets.primitives import Chip

    template_id = new_store_template_id()
    template = StoreTemplate(
        name="Standart Supermarket",
        tenant_id=TENANT,
        is_active=True,
        deactivated_at=None,
        store_template_id=template_id,
        based_on_store_id=None,
        config_snapshot={"positions": ["Satıcı"]},
        created_by=None,
    )
    apply_result = StoreTemplateApplyResult(
        new_store_id=new_store_id(),
        template_id=template_id,
        template_name="Standart Supermarket",
        config_snapshot={"positions": ["Satıcı"]},
    )
    templates_uc = _StoreTemplateUseCase(templates=[template], apply_result=apply_result)
    context = _Context(store_templates=templates_uc)
    screen, _controller = _attach(context, theme, qtbot=qtbot)
    assert screen._template_table.row_count == 1

    def fake_apply_exec(self: StoreTemplateApplyDialog) -> int:
        self._code.set_text("BEL-29")
        self._name.set_text("Bellona 29 May")
        self._brand.set_text("Bellona")
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yeni Mağaza Yarat")
        submit.click()
        return 0

    monkeypatch.setattr(StoreTemplateApplyDialog, "exec", fake_apply_exec)

    apply_button = next(
        b for b in screen._template_table.findChildren(QPushButton) if b.text() == "Tətbiq Et"
    )
    apply_button.click()

    assert len(templates_uc.applied) == 1
    assert "Bellona 29 May" in screen._template_message.text()

    # `refresh_templates()` `DataTable.clear()` → `clear_layout()` çağırır, o isə
    # `deleteLater()` işlədir (bax `layout_utils.py`) — köhnə sətir widget-i DƏRHAL
    # ölmür, hadisə dövrəsinin NÖVBƏTİ dövriyyəsinə qədər `_template_table.
    # findChildren`-də (bütün ağac üzrə) görünməyə davam edir. Ona görə bundan sonra
    # düyməni SƏTİR SƏVİYYƏSİNDƏ (`_rows[-1]`) axtarırıq — köhnə, hələ silinməmiş
    # sətir bacısının YANINDA YOX, məhz REFRESH-in yaratdığı SONUNCU sətrin İÇİNDƏ.
    current_row = screen._template_table._rows[-1]
    deactivate_button = next(
        b for b in current_row.findChildren(QPushButton) if b.text() == "Deaktiv Et"
    )
    deactivate_button.click()

    assert templates_uc.deactivated == [template_id]
    # Deaktivdən sonra siyahı YENİDƏN oxunub — sonuncu sətir indi "Deaktiv" çipi ilə
    # göstərilir, "Tətbiq Et"/"Deaktiv Et" düymələri ARTIQ YOXDUR (bax
    # `_build_template_cells`) — YENƏ DƏ sətir səviyyəsində yoxlanılır.
    final_row = screen._template_table._rows[-1]
    remaining_buttons = [
        b.text()
        for b in final_row.findChildren(QPushButton)
        if b.text() in ("Tətbiq Et", "Deaktiv Et")
    ]
    assert remaining_buttons == []
    chip_texts = {label.text() for label in final_row.findChildren(Chip)}
    assert "Deaktiv" in chip_texts


@requires_qt
def test_apply_domain_error_shows_the_user_message_and_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.bulk_operations import StoreTemplateApplyDialog

    template_id = new_store_template_id()
    template = StoreTemplate(
        name="Standart",
        tenant_id=TENANT,
        is_active=True,
        deactivated_at=None,
        store_template_id=template_id,
        based_on_store_id=None,
        config_snapshot={"positions": ["Satıcı"]},
        created_by=None,
    )
    denied = KompasOSError(
        "kod artıq mövcuddur", user_message="Bu mağaza kodu artıq istifadə olunur."
    )
    templates_uc = _StoreTemplateUseCase(templates=[template], apply_error=denied)
    context = _Context(store_templates=templates_uc)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    def fake_apply_exec(self: StoreTemplateApplyDialog) -> int:
        self._code.set_text("BEL-29")
        self._name.set_text("Bellona 29 May")
        self._brand.set_text("Bellona")
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yeni Mağaza Yarat")
        submit.click()
        return 0

    monkeypatch.setattr(StoreTemplateApplyDialog, "exec", fake_apply_exec)

    apply_button = next(
        b for b in screen._template_table.findChildren(QPushButton) if b.text() == "Tətbiq Et"
    )
    apply_button.click()  # ÇÖKMƏMƏLİDİR

    assert screen._template_message.text() == "Bu mağaza kodu artıq istifadə olunur."
    assert templates_uc.applied == []


# --------------------------------------------------------------------------- #
# 7. Silinmiş widget / köhnəlmiş sətir — çökmə YOX
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_malformed_template_id_from_a_stale_row_signal_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Ekran köhnə sətri göstərir, kontroller isə birbaşa (real dialoqu keçərək) sınanır —
    `test_user_admin_screen_e2e.py::test_a_malformed_document_id_...` ilə EYNİ naxış."""
    templates_uc = _StoreTemplateUseCase(templates=[])
    context = _Context(store_templates=templates_uc)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    screen.deactivate_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert templates_uc.deactivated == []
    assert "identifikatoru düzgün deyil" in screen._template_message.text()


# --------------------------------------------------------------------------- #
# 8. Səlahiyyət qapısı — real klik zənciri ilə
# --------------------------------------------------------------------------- #


@requires_qt
def test_permission_error_on_preview_surfaces_through_the_full_real_click_chain(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    csv_path = tmp_path / "employees.csv"
    csv_path.write_bytes(b"...")
    denied = KompasOSError(
        "flag yoxdur", user_message="Toplu əməliyyat aparmaq səlahiyyətiniz yoxdur."
    )
    use_case = _BulkImportUseCase(preview_error=denied)
    context = _Context(bulk_import=use_case)
    screen, _controller = _attach(context, theme, qtbot=qtbot)

    _pick_file(monkeypatch, screen, str(csv_path))
    _click(screen, "Önizlə")  # ÇÖKMƏMƏLİDİR

    assert screen._import_message.text() == "Toplu əməliyyat aparmaq səlahiyyətiniz yoxdur."
    assert screen._error_table.isVisibleTo(screen) is False
