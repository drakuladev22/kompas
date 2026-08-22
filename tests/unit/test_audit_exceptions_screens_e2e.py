"""`AuditScreen` + `ExceptionsScreen` ↔ kontrollerləri — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_audit_export.py` `AuditLogController`-i duck-typing ilə yoxlayır (fərdi
metodlar), `test_exception_screen.py` isə `ExceptionsController._decide()`-i
sahtə `_Screen`-lə çağırır — heç biri REAL `AuditScreen`/`ExceptionsScreen`
qurub, REAL düymə/sahə kliki ilə tam zənciri (widget → siqnal → kontroller →
sessiya → widget) sınamır. Burada məhz bu boşluq bağlanır.

──────────────────────────────────────────────────────────────────────────────
TAPILAN QÜSUR — Audit Jurnalı AÇILANDA HEÇ NƏ YÜKLƏMİR
──────────────────────────────────────────────────────────────────────────────
`AuditLogController.attach()` (bax fayl) YALNIZ siqnalları bağlayır —
`ErpServersController`/`BackupAdminController`/`ExceptionsController`-in
HAMISININ `attach()`-in SONUNDA çağırdığı ilkin `refresh()`/`_reload()`
çağırışı BURADA YOXDUR. Nəticə: panel açılanda cədvəl BOŞ qalır, istifadəçi
bir filtri (axtarış, modul, tarix) TOXUNANA qədər — ekran «Audit jurnalı»
adını daşıyır, amma açılan andan HEÇ BİR yazı göstərmir. `xfail(strict=True)`
bunu sübut edir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from src.domain.value_objects.identifiers import ExceptionId, TenantId
from src.presentation.background_task import InlineExecutor
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


class _Actor:
    id = ACTOR_ID


# ============================================================================ #
# AuditScreen — sahtələr
# ============================================================================ #


class _Entry:
    def __init__(
        self,
        action: str,
        *,
        occurred_at: datetime | None = None,
        actor_name: str = "Aysel Quliyeva",
        entity_type: str = "fines",
        reason: str = "izah",
    ) -> None:
        self.occurred_at = occurred_at
        self.actor_name = actor_name
        self.action = action
        self.entity_type = entity_type
        self.reason = reason


class _Page:
    def __init__(self, entries: list[_Entry], total: int, *, limit: int = 50) -> None:
        self.entries = entries
        self.total = total
        self.filters = type("_F", (), {"limit": limit})()


class _AuditQuery:
    def __init__(self, page: _Page) -> None:
        self.page = page
        self.calls: list[Any] = []
        self.error: Exception | None = None

    def search(self, *, tenant_id: Any, actor: Any, filters: Any) -> _Page:
        self.calls.append(filters)
        if self.error is not None:
            raise self.error
        return self.page


class _Limits:
    def __init__(self, values: dict[str, int] | None = None) -> None:
        self._values = values or {}

    def get_int(self, _tenant: Any, key: str, default: int) -> int:
        return self._values.get(key, default)


class _AuditSession:
    def __init__(self, query: _AuditQuery, limits: _Limits) -> None:
        self.tenant_id = TENANT
        self.audit_query = query
        self.limits = limits
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _AuditContext:
    def __init__(self, query: _AuditQuery, limits: _Limits | None = None) -> None:
        self._query = query
        self._limits = limits or _Limits()
        self.sessions: list[_AuditSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _AuditSession(self._query, self._limits)
        self.sessions.append(created)
        yield created


def _screen(theme: Any) -> Any:
    from src.presentation.screens.group_d import AuditScreen

    return AuditScreen(theme, modules=["fines", "leave"])


# --------------------------------------------------------------------------- #
# 1. TAPILAN QÜSUR — panel açılanda cədvəl BOŞDUR
# --------------------------------------------------------------------------- #


@requires_qt
def test_opening_the_audit_screen_loads_entries_without_any_filter_interaction(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import AuditLogController

    query = _AuditQuery(_Page([_Entry("FINE_ISSUED"), _Entry("LEAVE_APPROVED")], total=2))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)

    AuditLogController(context, _Actor(), executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]

    assert screen.table().row_count == 2
    assert screen.switcher().current_state() == "content"


# --------------------------------------------------------------------------- #
# 2. REAL axtarış yazısı → süzgəc dəyişir, BİRİNCİ səhifəyə qayıdır
# --------------------------------------------------------------------------- #


@requires_qt
def test_typing_in_the_search_box_reloads_filtered_entries_and_resets_to_page_one(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import AuditLogController

    query = _AuditQuery(_Page([_Entry("FINE_ISSUED")], total=1))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    controller = AuditLogController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    controller.attach(screen)
    controller._page = 4  # istifadəçi əvvəllər 4-cü səhifədə idi

    screen._search.setText("cərimə")  # REAL yazı — QLineEdit.textChanged

    assert query.calls[-1].search == "cərimə"
    assert query.calls[-1].offset == 0  # BİRİNCİ səhifəyə qayıdıb
    assert controller._page == 1


# --------------------------------------------------------------------------- #
# 3. Ekstremal/düşmən axtarış mətni — ÇÖKMÜR, olduğu kimi ötürülür
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_hostile_and_oversized_search_query_does_not_crash_the_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import AuditLogController

    query = _AuditQuery(_Page([], total=0))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    AuditLogController(context, _Actor(), executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]

    hostile = "'; DROP TABLE audit_log; --" + "🔥" * 50 + "A" * 10_000
    screen._search.setText(hostile)  # ÇÖKMƏMƏLİDİR

    assert query.calls[-1].search == hostile  # KƏSİLMİR, DƏYİŞDİRİLMİR
    assert screen.switcher().current_state() == "empty"  # boş nəticə — çökmə yox


# --------------------------------------------------------------------------- #
# 4. Modul seçimi VƏ kritik-yalnız açarı REAL widget-lərlə süzgəci dəyişir
# --------------------------------------------------------------------------- #


@requires_qt
def test_module_and_critical_toggles_change_the_real_filter_payload(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import AuditLogController

    query = _AuditQuery(_Page([], total=0))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    AuditLogController(context, _Actor(), executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]

    screen._module.setCurrentText("fines")  # REAL seçim
    assert query.calls[-1].entity_type == "fines"

    screen._critical_only.setChecked(True)  # REAL toggle klik
    assert screen._critical_only.isChecked() is True


# --------------------------------------------------------------------------- #
# 4b. TAPILAN QÜSUR — combo-nun "hamısı" mətni `ALL_MODULES`-la UYĞUN GƏLMİR
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_default_module_selection_is_not_sent_as_a_literal_filter(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import AuditLogController

    query = _AuditQuery(_Page([_Entry("FINE_ISSUED", entity_type="fines")], total=1))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    AuditLogController(context, _Actor(), executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]

    screen._search.setText("a")  # istənilən REAL sorğunu işə salır

    # Kombo TOXUNULMAYIB (defolt "hamısı" seçimi) — süzgəc heç bir modula
    # məhdudlaşdırılmamalıdır.
    assert query.calls[-1].entity_type is None


# --------------------------------------------------------------------------- #
# 5. Səhifələmə — REAL düymə kliki düzgün səhifəni göndərir, süzgəc QALIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_a_pagination_button_requests_that_page_and_keeps_the_filter(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.domain.policies import SystemLimitKey
    from src.presentation.controllers.audit_log import AuditLogController

    entries = [_Entry(f"ACTION_{i}") for i in range(5)]
    query = _AuditQuery(_Page(entries, total=150, limit=50))
    limits = _Limits({SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE.value: 50})
    context = _AuditContext(query, limits)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    controller = AuditLogController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    controller.attach(screen)
    screen._search.setText("cərimə")  # süzgəc qoyulur

    from PySide6.QtWidgets import QPushButton

    page_two = next(b for b in screen._pagination.findChildren(QPushButton) if b.text() == "2")
    page_two.click()  # REAL səhifələmə kliki

    assert controller._page == 2
    assert query.calls[-1].search == "cərimə"  # süzgəc İTMƏYİB
    assert query.calls[-1].offset == 50


# --------------------------------------------------------------------------- #
# 6. Uğurlu ilk oxumadan sonrakı süzgəc UĞURSUZLUĞU — BÜTÜN ekranı silir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_transient_filter_failure_does_not_wipe_the_filter_bar(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import AuditLogController

    query = _AuditQuery(_Page([_Entry("FINE_ISSUED")], total=1))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    AuditLogController(context, _Actor(), executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]
    screen._search.setText("cərimə")
    assert screen.table().row_count == 1

    query.error = KompasOSError("db blip", user_message="Baza əlaqəsi kəsildi.")
    screen._search.setText("cərimə ")  # bir hərf də — YENİ, TRANZİT sorğu

    # Filtr paneli (axtarış qutusu) HƏLƏ görünməlidir — bütün ekran silinməməli.
    assert screen.switcher().current_state() == "content"
    assert screen._search.isVisibleTo(screen) is True


# --------------------------------------------------------------------------- #
# 7. İxrac — REAL klik → fon işi → fayl yazılır, banner göstərilir
# --------------------------------------------------------------------------- #


class _Writer:
    """Sahtə `ExcelReportWriter` — REAL disk yazmır, çağırışı yığır."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, output_dir: Path) -> None:
        self.output_dir = output_dir

    def write_table(self, rows: list[dict[str, str]], **kwargs: Any) -> Path:
        _Writer.calls.append({"rows": rows, **kwargs})
        return self.output_dir / str(kwargs["file_name"])


@requires_qt
def test_clicking_export_writes_a_file_off_the_gui_thread_via_a_real_click(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers import audit_log as audit_log_module
    from src.presentation.controllers.audit_log import AuditLogController

    _Writer.calls = []
    monkeypatch.setattr(audit_log_module, "ExcelReportWriter", None, raising=False)
    import src.infrastructure.reporting.excel as excel_module

    monkeypatch.setattr(excel_module, "ExcelReportWriter", _Writer)

    # `_export_finished` → `_inform()` → REAL `QMessageBox.exec()` çağırır —
    # bunu MONKEYPATCH etmirik, sonsuza qədər modal event loop açılardı
    # (`audit_log.py::_inform` naxışı, `test_audit_export.py`-də ÇAĞIRILMIR).
    from PySide6.QtWidgets import QMessageBox

    informed: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda self: informed.append(self.text()) or QMessageBox.StandardButton.Ok,
    )

    query = _AuditQuery(_Page([_Entry("FINE_ISSUED"), _Entry("LEAVE_APPROVED")], total=2))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    controller = AuditLogController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    monkeypatch.setattr(AuditLogController, "_choose_output_dir", lambda _self, _screen: tmp_path)
    controller.attach(screen)

    _click(screen, "Excel-ə İxrac Et")  # ÇÖKMƏMƏLİDİR, DONMAMALIDIR

    assert len(_Writer.calls) == 1
    assert _Writer.calls[0]["rows"][0]["action"] == "FINE_ISSUED"
    assert any("2 sətir ixrac olundu" in text for text in informed)


@requires_qt
def test_cancelling_the_export_folder_dialog_writes_nothing_via_a_real_click(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.audit_log import AuditLogController

    query = _AuditQuery(_Page([_Entry("FINE_ISSUED")], total=1))
    context = _AuditContext(query)
    screen = _screen(theme)
    qtbot.addWidget(screen)
    controller = AuditLogController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    monkeypatch.setattr(AuditLogController, "_choose_output_dir", lambda _self, _screen: None)
    controller.attach(screen)
    sessions_before = len(context.sessions)

    _click(screen, "Excel-ə İxrac Et")  # ÇÖKMƏMƏLİDİR

    assert len(context.sessions) == sessions_before  # heç bir yeni sessiya AÇILMADI


# ============================================================================ #
# ExceptionsScreen — sahtələr
# ============================================================================ #


TENANT_ID: TenantId = TenantId(uuid.uuid4())


def _view(**overrides: Any) -> Any:
    from src.application.use_cases.exception_engine import ExceptionView

    defaults: dict[str, Any] = {
        "exception_id": ExceptionId(uuid.uuid4()),
        "source_code": "BEHAVIOR_ANOMALY",
        "source_name_az": "Davranış Anomaliyası",
        "employee_id": str(uuid.uuid4()),
        "store_id": str(uuid.uuid4()),
        "detail": "Son 30 günün orta check-in vaxtından 42 dəqiqə sapma.",
        "severity": "HIGH",
        "status": "OPEN",
        "created_at": datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ExceptionView(**defaults)


class _ExcCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _ExcConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or [{"name": "Bellona 28 May"}]

    def execute(self, _sql: str, _params: Any = None) -> _ExcCursor:
        return _ExcCursor(self.rows)


class _ExcEmployees:
    def get(self, _employee_id: Any) -> Any:
        return None


class _ExcUow:
    def __init__(self) -> None:
        self.employees = _ExcEmployees()
        self.connection = _ExcConnection()


class _ExceptionsUseCase:
    def __init__(self, views: list[Any], *, dismiss_error: Exception | None = None) -> None:
        self.views = list(views)
        self.dismiss_error = dismiss_error
        self.dismissed: list[tuple[Any, str]] = []
        self.reviewed: list[Any] = []

    def list_open(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        return list(self.views)

    def dismiss(self, *, tenant_id: Any, actor: Any, exception_id: Any, note: str) -> None:
        if self.dismiss_error is not None:
            raise self.dismiss_error
        self.dismissed.append((exception_id, note))
        self.views = [v for v in self.views if v.exception_id != exception_id]

    def mark_reviewed(
        self, *, tenant_id: Any, actor: Any, exception_id: Any, note: str | None = None
    ) -> None:
        self.reviewed.append(exception_id)
        self.views = [v for v in self.views if v.exception_id != exception_id]


class _ExcSession:
    def __init__(self, use_case: _ExceptionsUseCase) -> None:
        self.tenant_id = TENANT_ID
        self.uow = _ExcUow()
        self.exceptions = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _ExcContext:
    def __init__(self, use_case: _ExceptionsUseCase) -> None:
        self._use_case = use_case
        self.session_calls = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.session_calls += 1
        yield _ExcSession(self._use_case)


def _exc_screen(theme: Any) -> Any:
    from src.presentation.screens.group_i import ExceptionsScreen

    return ExceptionsScreen(theme)


def _dismiss_button(screen: Any) -> Any:
    from PySide6.QtWidgets import QPushButton

    return next(b for b in screen.findChildren(QPushButton) if b.text() == "Rədd Et")


def _review_button(screen: Any) -> Any:
    from PySide6.QtWidgets import QPushButton

    return next(b for b in screen.findChildren(QPushButton) if b.text() == "Nəzərdən Keçirildi")


# --------------------------------------------------------------------------- #
# 8. «Nəzərdən Keçirildi» — REAL klik, dialoqSUZ birbaşa yazılır
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_reviewed_writes_without_any_dialog_and_reloads_the_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.exceptions import ExceptionsController

    view = _view()
    use_case = _ExceptionsUseCase([view])
    context = _ExcContext(use_case)
    screen = _exc_screen(theme)
    qtbot.addWidget(screen)
    ExceptionsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    assert screen.table().row_count == 1

    _review_button(screen).click()  # REAL klik — QInputDialog AÇILMIR

    assert use_case.reviewed == [view.exception_id]
    assert screen.switcher().current_state() == "empty"  # bağlanmış istisna GETDİ


# --------------------------------------------------------------------------- #
# 9. «Rədd Et» — REAL klik açır real `QInputDialog`, səbəb MƏCBURİDİR
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_dismiss_asks_for_a_reason_via_the_real_dialog_and_writes_it(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.exceptions import ExceptionsController

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Kameradan yoxlanıldı, əsassız tapıntı.", True)),
    )

    view = _view()
    use_case = _ExceptionsUseCase([view])
    context = _ExcContext(use_case)
    screen = _exc_screen(theme)
    qtbot.addWidget(screen)
    ExceptionsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _dismiss_button(screen).click()  # REAL klik

    assert use_case.dismissed == [(view.exception_id, "Kameradan yoxlanıldı, əsassız tapıntı.")]


@requires_qt
def test_cancelling_the_reason_dialog_never_reaches_the_use_case(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.exceptions import ExceptionsController

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    view = _view()
    use_case = _ExceptionsUseCase([view])
    context = _ExcContext(use_case)
    screen = _exc_screen(theme)
    qtbot.addWidget(screen)
    ExceptionsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _dismiss_button(screen).click()  # REAL klik — dialoq LƏĞV OLUNUR

    assert use_case.dismissed == []
    assert screen.table().row_count == 1  # istisna HƏLƏ açıqdır


@requires_qt
def test_a_hostile_and_oversized_dismiss_reason_is_passed_through_untouched(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.exceptions import ExceptionsController

    hostile = "'; DROP TABLE exceptions; --\n" + "🔥" * 20 + "A" * 5_000
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (hostile, True))
    )

    view = _view()
    use_case = _ExceptionsUseCase([view])
    context = _ExcContext(use_case)
    screen = _exc_screen(theme)
    qtbot.addWidget(screen)
    ExceptionsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _dismiss_button(screen).click()  # ÇÖKMƏMƏLİDİR

    assert use_case.dismissed[0][1] == hostile.strip()


# --------------------------------------------------------------------------- #
# 10. Səlahiyyətsiz/naməlum identifikator — real siqnal, çökmə YOX
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_malformed_exception_id_from_a_stale_row_is_explained_not_crashed(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Sətir çürüyübsə (yarış vəziyyəti) `exception_id` UUID olmaya bilər."""
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.exceptions import ExceptionsController

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("səbəb", True))
    )

    view = _view()
    use_case = _ExceptionsUseCase([view])
    context = _ExcContext(use_case)
    screen = _exc_screen(theme)
    qtbot.addWidget(screen)
    ExceptionsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.dismissed_requested.emit("naməlum-id-1234")  # REAL siqnal, UUID DEYİL

    assert use_case.dismissed == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 11. TAPILAN QÜSUR — uğursuz rədd BÜTÜN açıq istisna siyahısını yox edir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_dismiss_does_not_wipe_the_other_open_exceptions(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from src.presentation.controllers.exceptions import ExceptionsController

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("qısa", True))
    )
    # `_inform()` MODAL göstərir — başsız mühitdə `exec()` sonsuza qədər
    # gözləyərdi (dəst bir dəfə məhz belə asıldı). Mətn tutulur ki, test
    # istifadəçinin HƏQİQƏTƏN səbəbi gördüyünü də yoxlaya bilsin.
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda box: shown.append(box.text()) or 0,  # type: ignore[arg-type]
    )

    class _DeniedError(KompasOSError):
        user_message = "Rədd səbəbini ətraflı yazın."

    broken, healthy = _view(), _view(detail="ikinci istisna")
    use_case = _ExceptionsUseCase([broken, healthy], dismiss_error=_DeniedError("qısa qeyd"))
    context = _ExcContext(use_case)
    screen = _exc_screen(theme)
    qtbot.addWidget(screen)
    ExceptionsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    assert screen.table().row_count == 2

    _dismiss_button(screen).click()  # BİRİNCİ sətrin düyməsi — RƏDD OLUNUR

    assert screen.switcher().current_state() == "content"
    assert screen.table().row_count == 2  # HEÇ BİRİ silinməyib — yazı UĞURSUZ OLDU
    # SƏBƏB İSTİFADƏÇİYƏ ÇATIR: banner «yüklənə bilmədi» cümləsi qurardı və
    # domenin dəqiq izahını atardı; `_inform()` onu olduğu kimi göstərir.
    assert shown == ["Rədd səbəbini ətraflı yazın."]
