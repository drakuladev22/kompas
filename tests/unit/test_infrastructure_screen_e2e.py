"""`InfrastructureScreen` ↔ `InfrastructureController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, infra dalğası)
──────────────────────────────────────────────────────────────────────────────
`test_infrastructure_controllers.py` kontrolleri Qt TƏLƏB ETMİR — ekran duck-
typing sahə obyekti (`_InfraScreen`) ilə əvəzlənir və `controller._on_switch`/
`controller._execute` DÜZ metod çağırışı ilə tetiklənir, `MigrationConfirmDialog`
heç vaxt qurulmur. Yəni "Digər bazaya keç" düyməsinin REAL kliki, REAL modalın
FormField-inə yazılan mətn, "Keçidi Başlat" düyməsinin REAL kliki — heç biri
sınanmır. Bu, LAYİHƏNİN ƏN DAĞIDICI ƏMƏLİYYATIDIR (bax `controllers/
infrastructure.py` modul başlığı) və məhz buna görə REAL widget zənciri
sınanmalıdır (`test_erp_backup_screens_e2e.py`-dəki `RestoreConfirmDialog.exec`
monkeypatch naxışı təkrarlanır).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from src.domain.value_objects.infrastructure import (
    ALL_PHASES,
    DatabaseTarget,
    MigrationError,
    MigrationPlan,
)
from src.presentation.controllers.infrastructure import InfrastructureController
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = uuid.uuid4()
ACTOR_ID: Final = uuid.uuid4()
NOW: Final = datetime(2026, 8, 20, 3, 0, tzinfo=UTC)


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


class _Actor:
    id = ACTOR_ID


# --------------------------------------------------------------------------- #
# `db_switch` + `migration_events` sahtələri — `test_infrastructure_
# controllers.py`-dəki müqavilənin yerli təkrarı (CLAUDE.md bölmə 6: paralel
# işlərin ortaq faylı dəyişməsinin qarşısını almaq üçün hər fayl öz sahtəsini
# saxlayır).
# --------------------------------------------------------------------------- #


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(
        self, *, active: DatabaseTarget | None = None, error: Exception | None = None
    ) -> None:
        self._active = active
        self.error = error

    def execute(self, _sql: str, _params: Any = None) -> _Cursor:
        if self.error is not None:
            raise self.error
        if self._active is None:
            return _Cursor([])
        return _Cursor([{"destination_target": self._active.value}])


class _EventLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def history(self, _tenant_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
        return list(self.rows)


class _Uow:
    def __init__(self, connection: _Connection, events: _EventLog) -> None:
        self.connection = connection
        self._events = events

    def repository(self, name: str) -> Any:
        assert name == "migration_events"
        return self._events


class _SwitchUseCase:
    def __init__(self, *, warnings: list[str] | None = None) -> None:
        self.warnings = warnings or []
        self.preflight_error: Exception | None = None
        self.execute_error: Exception | None = None
        self.preflights: list[MigrationPlan] = []
        self.executed: list[MigrationPlan] = []

    def preflight(self, *, tenant_id: Any, actor: Any, plan: MigrationPlan) -> list[str]:
        self.preflights.append(plan)
        if self.preflight_error is not None:
            raise self.preflight_error
        return list(self.warnings)

    def execute(self, *, tenant_id: Any, actor: Any, plan: MigrationPlan) -> Any:
        from src.application.use_cases.db_switch import MigrationReport

        self.executed.append(plan)
        if self.execute_error is not None:
            raise self.execute_error

        report = MigrationReport(plan=plan)
        report.status = _completed_status()
        report.completed_phases = list(ALL_PHASES)
        return report


def _completed_status() -> Any:
    from src.domain.value_objects.infrastructure import MigrationStatus

    return MigrationStatus.COMPLETED


class _Session:
    def __init__(
        self, use_case: _SwitchUseCase, connection: _Connection, events: _EventLog
    ) -> None:
        self.tenant_id = TENANT
        self.db_switch = use_case
        self.uow = _Uow(connection, events)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.opens = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opens += 1
        yield self._session


def _build(
    use_case: _SwitchUseCase, theme: Any, *, active: DatabaseTarget = DatabaseTarget.CLOUD
) -> tuple[Any, _Session, _EventLog]:
    from src.presentation.screens.group_i import InfrastructureScreen

    connection = _Connection(active=active)
    events = _EventLog()
    session = _Session(use_case, connection, events)
    screen = InfrastructureScreen(theme)
    InfrastructureController(_Context(session), _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen, session, events


def _phase_chip_texts(screen: Any) -> list[str]:
    return [row._chip.text() for row in screen._phase_rows.values()]


# --------------------------------------------------------------------------- #
# 1. Real klik → real modal → yanlış ad EDİLƏN YAZIYA MANE OLUR
# --------------------------------------------------------------------------- #


@requires_qt
def test_wrong_confirmation_text_blocks_execution_and_correct_text_runs_it(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import MigrationConfirmDialog

    use_case = _SwitchUseCase(warnings=["12 sinxronlaşmamış yazı var."])
    screen, session, events = _build(use_case, theme, active=DatabaseTarget.CLOUD)
    qtbot.addWidget(screen)

    captured: list[Any] = []
    monkeypatch.setattr(
        MigrationConfirmDialog,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif metodu kimi `self` LAZIMDIR
    )

    assert screen._switch_button.text() == "Şəxsi server-ə keç"
    qtbot.mouseClick(screen._switch_button, Qt.MouseButton.LeftButton)

    assert use_case.preflights, "Modal açılmazdan ƏVVƏL ön yoxlama aparılmalıdır"
    assert len(captured) == 1
    dialog = captured[0]

    dialog._input.set_text("səhv ad")
    _click(dialog, "Keçidi Başlat")
    assert use_case.executed == [], "SƏHV ad ilə İCRA BAŞLAMAMALIDIR"
    assert dialog._input.has_error is True

    dialog._input.clear_error()
    dialog._input.set_text(DatabaseTarget.PRIVATE_SERVER.label_az)
    _click(dialog, "Keçidi Başlat")

    assert len(use_case.executed) == 1
    assert session.commits == 1
    # Gedişat REAL widget-lərdə TAMAMLANDI göstərir.
    assert all(text == "Tamamlandı" for text in _phase_chip_texts(screen))
    # `_execute()` uğurdan SONRA `refresh()` çağırır (`controllers/
    # infrastructure.py::_execute`) — sahtə `_EventLog` DƏYİŞMƏSƏ də (real
    # yazı burada simulyasiya olunmur) yenidən oxuma ÇÖKMƏMƏLİDİR.
    assert events.history(TENANT) == []
    assert "12 sinxronlaşmamış yazı var." in screen._warning_label.text()


# --------------------------------------------------------------------------- #
# 2. Ön yoxlama rədd edir (səlahiyyət) — modal ÜMUMİYYƏTLƏ AÇILMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_preflight_denial_never_opens_the_real_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import MigrationConfirmDialog

    use_case = _SwitchUseCase()
    use_case.preflight_error = KompasOSError(
        "denied", user_message="Baza keçidi üçün səlahiyyətiniz yoxdur."
    )
    screen, _session, _events = _build(use_case, theme)
    qtbot.addWidget(screen)
    screen.show()

    captured: list[Any] = []
    monkeypatch.setattr(
        MigrationConfirmDialog, "__init__", lambda self, *a, **k: captured.append(True)
    )

    qtbot.mouseClick(screen._switch_button, Qt.MouseButton.LeftButton)

    assert captured == [], "Səlahiyyətsiz istifadəçi TƏSDİQ MODALINI görməməlidir"
    assert use_case.executed == []


# --------------------------------------------------------------------------- #
# 3. İcra uğursuz olur — fazalar YARIMÇIQ QALMIR, real xəbərdarlıq göstərilir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_execution_does_not_leave_phases_stuck_mid_way(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`execute()` HEÇ VAXT yarımçıq vəziyyət qoymur (bax use case başlığı) —
    burada REAL `PhaseRow` widget-ləri üzərində sübut edilir."""
    from src.presentation.screens.group_i import MigrationConfirmDialog

    use_case = _SwitchUseCase()
    use_case.execute_error = MigrationError(
        "checksum uyğun gəlmir",
        user_message="Barmaq izləri uyğun gəlmədi. Aktiv baza dəyişmədi.",
    )
    screen, session, _events = _build(use_case, theme)
    qtbot.addWidget(screen)
    screen.show()

    captured: list[Any] = []
    monkeypatch.setattr(
        MigrationConfirmDialog,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108
    )

    qtbot.mouseClick(screen._switch_button, Qt.MouseButton.LeftButton)
    dialog = captured[0]
    dialog._input.set_text(DatabaseTarget.PRIVATE_SERVER.label_az)
    _click(dialog, "Keçidi Başlat")  # ÇÖKMƏMƏLİDİR

    assert session.commits == 0, "Uğursuz icra COMMIT EDİLMƏMƏLİDİR"
    # `reset_phases()` HAMISINI "Gözləyir"ə qaytarır — `execute()` istisna
    # atdığı üçün `_apply_report` heç çağırılmır, YARIMÇIQ vəziyyət (bəziləri
    # "Tamamlandı", biri "Uğursuz") EKRANDA GÖRÜNMƏMƏLİDİR.
    assert all(text == "Gözləyir" for text in _phase_chip_texts(screen))


# --------------------------------------------------------------------------- #
# 4. Real "Yenilə" kliki (tarixçə) — REAL `DataTable` yenidən dolur
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_history_refresh_button_reloads_the_real_table(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _SwitchUseCase()
    screen, _session, events = _build(use_case, theme)
    qtbot.addWidget(screen)

    from PySide6.QtWidgets import QLabel

    assert any(
        label.text() == "Hələ heç bir baza keçidi olmayıb."
        for label in screen._history_host.findChildren(QLabel)
    )

    events.rows = [
        {
            "created_at": NOW,
            "source_target": "CLOUD",
            "destination_target": "PRIVATE_SERVER",
            "status": "COMPLETED",
            "preflight_checksum": "abcdef1234567890",
            "checksum_matched": True,
        }
    ]
    _click(screen, "Yenilə")

    from src.presentation.widgets.data_table import DataTable

    tables = screen._history_host.findChildren(DataTable)
    assert len(tables) == 1
    assert tables[0].row_count == 1


# --------------------------------------------------------------------------- #
# 5. İlkin yükləmə sınır — çökmür, REAL xəta vəziyyəti göstərilir
# --------------------------------------------------------------------------- #


@requires_qt
def test_initial_load_failure_shows_a_real_error_state_without_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import InfrastructureScreen

    use_case = _SwitchUseCase()
    connection = _Connection(error=RuntimeError("baza əlaqəsi kəsildi"))
    events = _EventLog()
    session = _Session(use_case, connection, events)
    screen = InfrastructureScreen(theme)
    qtbot.addWidget(screen)

    InfrastructureController(_Context(session), _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 6. Ekstremal giriş — SQL-bənzər/çox uzun mətn təsdiq sahəsində ÇÖKMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_sql_like_and_extremely_long_confirmation_text_is_rejected_not_crashed(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import MigrationConfirmDialog

    use_case = _SwitchUseCase()
    screen, _session, _events = _build(use_case, theme)
    qtbot.addWidget(screen)

    captured: list[Any] = []
    monkeypatch.setattr(
        MigrationConfirmDialog,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108
    )
    qtbot.mouseClick(screen._switch_button, Qt.MouseButton.LeftButton)
    dialog = captured[0]

    for hostile in ("'; DROP TABLE db_migration_events; --", "a" * 10_000, "😀" * 50, "   "):
        dialog._input.clear_error()
        dialog._input.set_text(hostile)
        _click(dialog, "Keçidi Başlat")  # ÇÖKMƏMƏLİDİR
        assert dialog._input.has_error is True
        assert use_case.executed == []
