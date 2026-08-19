"""Audit jurnalının «Excel-ə İxrac Et» yolu (`controllers/audit_log.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
Düymə ekranda VARDI və `export_requested` yayırdı, lakin heç kim dinləmirdi:
auditor basırdı, heç nə olmurdu. Audit jurnalı məhz KƏNAR yoxlamaya təqdim
edilmək üçündür — ixracsız o, yalnız ekranda qalır.

İki şey ayrıca kilidlənir:

* **Sükutlu kəsilmə yoxdur.** ROOT tavanı (`AUDIT_LOG_MAX_PAGE_SIZE`) nəticəni
  kəsə bilər; kəsilmiş fayl «tam jurnal» kimi görünsəydi, yoxlayan şəxs olmayan
  sətri «yoxdur» sayardı. Ona görə həm faylın izah sətrində, həm bitmə
  mesajında AÇIQ deyilir.
* **GUI donmur.** Oxu + `.xlsx` yazısı fon sapındadır; sessiya HƏMİN sapda
  açılır (`psycopg` sap-təhlükəsiz deyil).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import pytest

from src.presentation.controllers import audit_log as audit_log_module
from src.presentation.controllers.audit_log import EXPORT_HEADERS, AuditLogController

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Entry:
    def __init__(self, action: str) -> None:
        self.occurred_at = None
        self.actor_name = "Aysel Quliyeva"
        self.action = action
        self.entity_type = "fines"
        self.reason = "izah"


class _Page:
    def __init__(self, entries: list[_Entry], total: int) -> None:
        self.entries = entries
        self.total = total
        self.filters = type("_F", (), {"limit": 100})()


class _AuditQuery:
    def __init__(self, page: _Page) -> None:
        self.page = page
        self.calls: list[Any] = []

    def search(self, *, tenant_id: Any, actor: Any, filters: Any) -> _Page:
        self.calls.append(filters)
        return self.page


class _Limits:
    def __init__(self, values: dict[str, int]) -> None:
        self._values = values

    def get_int(self, _tenant: Any, key: str, default: int) -> int:
        return self._values.get(key, default)


class _Session:
    def __init__(self, *, page: _Page, limits: _Limits) -> None:
        self.tenant_id = TENANT
        self.audit_query = _AuditQuery(page)
        self.limits = limits
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, *, page: _Page, limits: _Limits) -> None:
        self._page = page
        self._limits = limits
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(page=self._page, limits=self._limits)
        self.sessions.append(created)
        yield created


class _Actor:
    id = uuid.uuid4()


class _Writer:
    """Sahtə `ExcelReportWriter` — nə yazıldığını yığır, fayl YARATMIR."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, output_dir: Path) -> None:
        self.output_dir = output_dir

    def write_table(self, rows: list[dict[str, str]], **kwargs: Any) -> Path:
        _Writer.calls.append({"rows": rows, **kwargs})
        return self.output_dir / str(kwargs["file_name"])


@pytest.fixture(autouse=True)
def _writer(monkeypatch: pytest.MonkeyPatch) -> type[_Writer]:
    _Writer.calls = []
    import src.infrastructure.reporting.excel as excel_module

    monkeypatch.setattr(excel_module, "ExcelReportWriter", _Writer)
    return _Writer


def _build(*, written: int = 3, total: int = 3, cap: int = 500) -> tuple[Any, _Context]:
    page = _Page([_Entry(f"ACTION_{index}") for index in range(written)], total)
    context = _Context(page=page, limits=_Limits({"AUDIT_LOG_MAX_PAGE_SIZE": cap}))
    controller = AuditLogController(context, _Actor())  # type: ignore[arg-type]
    return controller, context


# --------------------------------------------------------------------------- #
# İxrac
# --------------------------------------------------------------------------- #


def test_export_reads_from_the_first_row_not_the_current_page() -> None:
    """Ekranda 2-ci səhifə açıq olsa da, fayl BÜTÜN dəstlə başlayır."""
    controller, context = _build()
    controller._page = 3

    controller._write_export(Path("C:/tmp"))

    filters = context.sessions[0].audit_query.calls[0]
    assert filters.offset == 0


def test_export_keeps_the_screen_filters() -> None:
    """Faylda ekranda görünəndən BAŞQA dəst olmamalıdır."""
    controller, context = _build()
    controller._filters = {"search": "cərimə", "module": "fines"}

    controller._write_export(Path("C:/tmp"))

    filters = context.sessions[0].audit_query.calls[0]
    assert filters.search == "cərimə"
    assert filters.entity_type == "fines"


def test_export_uses_the_shared_row_shape() -> None:
    """Sütunlar `entry_row()`-dan gəlir — ekranla fayl ayrılmır."""
    controller, _ = _build(written=2, total=2)

    controller._write_export(Path("C:/tmp"))

    call = _Writer.calls[0]
    assert call["headers"] == EXPORT_HEADERS
    assert set(call["rows"][0]) == {key for key, _label in EXPORT_HEADERS}


def test_the_view_is_audited_so_the_session_is_committed() -> None:
    """`search()` baxışı jurnala yazır — commit unudulsa iz İTƏRDİ."""
    controller, context = _build()

    controller._write_export(Path("C:/tmp"))

    assert context.sessions[0].committed is True


def test_a_complete_export_says_nothing_about_truncation() -> None:
    controller, _ = _build(written=3, total=3)

    result = controller._write_export(Path("C:/tmp"))

    assert result.written == 3
    assert result.total == 3
    assert "DİQQƏT" not in _Writer.calls[0]["note"]


def test_a_truncated_export_is_never_silent() -> None:
    """Kəsilmə HƏM faylın içində, HƏM nəticədə görünür."""
    controller, _ = _build(written=500, total=1200, cap=500)

    result = controller._write_export(Path("C:/tmp"))

    assert result.written == 500
    assert result.total == 1200
    note = _Writer.calls[0]["note"]
    assert "DİQQƏT" in note
    assert "1200" in note


def test_cancelling_the_folder_dialog_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qovluq seçilməyibsə nə sessiya açılır, nə fayl yazılır."""
    controller, context = _build()
    monkeypatch.setattr(AuditLogController, "_choose_output_dir", lambda _self, _screen: None)

    controller._on_export(object())  # type: ignore[arg-type]

    assert context.sessions == []
    assert _Writer.calls == []


def test_the_export_runs_off_the_gui_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """`run_job` çağırılır — oxu/yazı GUI sapında qalmır."""
    controller, _ = _build()
    monkeypatch.setattr(
        AuditLogController, "_choose_output_dir", lambda _self, _screen: Path("C:/tmp")
    )
    started: list[str] = []

    def _fake_run_job(job: Any, **kwargs: Any) -> Any:
        started.append(str(kwargs.get("name", "")))
        return object()

    import src.presentation.background_task as background_task_module

    monkeypatch.setattr(background_task_module, "run_job", _fake_run_job)

    class _Screen:
        def show_loading(self) -> None:
            return None

    controller._on_export(_Screen())  # type: ignore[arg-type]

    assert started == ["audit-export"]


def test_the_module_exports_the_header_map() -> None:
    assert "EXPORT_HEADERS" in audit_log_module.__all__
