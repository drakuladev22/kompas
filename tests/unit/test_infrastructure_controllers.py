"""ERP, ehtiyat nüsxə, baza keçidi və diaqnostika ekranlarının canlı yolu.

──────────────────────────────────────────────────────────────────────────────
İKİ DAĞIDICI ƏMƏLİYYAT — TƏSDİQSİZ İCRA BLOKLANMALIDIR
──────────────────────────────────────────────────────────────────────────────
`restore()` bir günlük davamiyyəti, cəriməni və satışı geri qaytarır;
`execute()` isə bütün tenant-ı yalnız-oxu rejiminə salıb bazanı köçürür. Hər
ikisində siqnal (`restore_requested`, `switch_requested`) YALNIZ təsdiq
modalını açmalıdır — birbaşa icra bir kliklə fəlakət deməkdir. Belə bir
sürüşmə heç bir tip xətası vermir, ona görə qapı testlə bağlanır.

Testlər Qt TƏLƏB ETMİR: ekranlar duck-typing ilə əvəzlənir və modal siniflər
`monkeypatch` ilə qeyd-aparan saxta ilə əvəzlənir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.presentation.background_task import InlineExecutor
from src.presentation.controllers.backup_admin import BackupAdminController
from src.presentation.controllers.infrastructure import InfrastructureController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 2, 0, tzinfo=UTC)


class _DeniedError(KompasOSError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


def _actor() -> Any:
    return type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()


class _Context:
    def __init__(self, session: Any) -> None:
        self._session = session
        self.user_ids: list[Any] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.user_ids.append(user_id)
        yield self._session


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


# --------------------------------------------------------------------------- #
# Backup / Bərpa
# --------------------------------------------------------------------------- #


class _BackupScreen:
    theme = object()

    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.schedule = ""
        self.storage: tuple[float, float, int] | None = None

    def set_schedule_label(self, text: str) -> None:
        self.schedule = text

    def set_backups(self, backups: list[dict[str, str]]) -> None:
        self.rows = backups

    def set_storage(self, used_gb: float, total_gb: float, *, count: int) -> None:
        self.storage = (used_gb, total_gb, count)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _BackupUseCase:
    def __init__(self, points: list[Any]) -> None:
        self.points = points
        self.created = 0
        self.restored: list[Any] = []

    def restore_points(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        return list(self.points)

    def create_now(self, *, tenant_id: Any, actor: Any) -> Any:
        self.created += 1
        return None

    def restore(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        record: Any,
        target_dsn: str,
        confirmation: str,
    ) -> None:
        self.restored.append((record, target_dsn, confirmation))


class _BackupSession:
    def __init__(self, use_case: _BackupUseCase) -> None:
        self.tenant_id = TENANT
        self.backups = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _restore_point(*, expired: bool = False) -> Any:
    from datetime import date

    from src.application.use_cases.backup_access import RestorePoint
    from src.infrastructure.backup.service import BackupRecord

    record = BackupRecord(
        tenant_id=str(TENANT),
        backup_type="NIGHTLY_AUTO",
        storage_ref="/var/backups/kompasos.dump",
        size_bytes=1_887_436_800,
        checksum="abc123",
        retention_until=date(2026, 9, 11),
        created_at=NOW,
    )
    return RestorePoint(record=record, label_az="Bu gün", is_expired=expired)


def _backup_controller(
    use_case: _BackupUseCase,
) -> tuple[BackupAdminController, _BackupSession]:
    session = _BackupSession(use_case)
    # `InlineExecutor`: bu testlər MƏNTİQİ ölçür, sapı yox — nəticə dərhal
    # çatdırılır və hadisə dövrəsi gözləməsi lazım olmur (sap davranışı
    # `test_background_job_funnel.py`-dadır).
    controller = BackupAdminController(
        _Context(session),  # type: ignore[arg-type]
        _actor(),
        executor=InlineExecutor(),
    )
    return (controller, session)


def test_restore_request_only_opens_the_confirmation_dialog(monkeypatch: Any) -> None:
    """MƏCBURİ QAPI: `restore_requested` bərpanı BAŞLATMIR.

    Siqnal yalnız modalı açır; use case-ə heç nə getmir. Bu sürüşmə baş
    versəydi, cədvəldəki bir klik bütün tenant-ın son günlərini silərdi.
    """
    use_case = _BackupUseCase([_restore_point()])
    controller, session = _backup_controller(use_case)
    screen = _BackupScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    opened: list[str] = []

    class _Dialog:
        def __init__(self, _theme: Any, *, backup_date: str, parent: Any = None) -> None:
            opened.append(backup_date)
            self.confirmed = _Signal()

        def exec(self) -> None:
            """Modal açılır və istifadəçi HEÇ NƏ təsdiqləmir."""

    monkeypatch.setattr(
        "src.presentation.screens.group_d.RestoreConfirmDialog", _Dialog, raising=True
    )

    controller._on_restore_requested(screen, screen.rows[0]["date"])  # type: ignore[arg-type]

    assert opened, "Təsdiq modalı açılmalıdır"
    assert use_case.restored == [], "Təsdiqsiz bərpa İCRA OLUNMAMALIDIR"
    assert session.commits == 0


class _Signal:
    """Qt siqnalının minimal əvəzi — `connect()` yalnız qeyd aparır."""

    def __init__(self) -> None:
        self.slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self.slots.append(slot)


def test_restore_passes_the_written_confirmation_phrase(monkeypatch: Any) -> None:
    """Təsdiqdən SONRA use case-ə `«BƏRPA ET»` ifadəsi gedir (proqram qapısı)."""
    from src.infrastructure.backup.service import RESTORE_CONFIRMATION

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    use_case = _BackupUseCase([_restore_point()])
    controller, session = _backup_controller(use_case)
    screen = _BackupScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._restore(screen, screen.rows[0]["date"])  # type: ignore[arg-type]

    assert len(use_case.restored) == 1
    _record, target_dsn, confirmation = use_case.restored[0]
    assert confirmation == RESTORE_CONFIRMATION
    assert target_dsn.startswith("postgresql://")
    assert session.commits == 1


def test_restore_without_a_target_dsn_is_refused(monkeypatch: Any) -> None:
    """Hədəf ünvanı yoxdursa bərpa BAŞLAMIR — səbəb aydın deyilir."""
    monkeypatch.setenv("DATABASE_URL", "")
    use_case = _BackupUseCase([_restore_point()])
    controller, session = _backup_controller(use_case)
    screen = _BackupScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._restore(screen, screen.rows[0]["date"])  # type: ignore[arg-type]

    assert use_case.restored == []
    assert session.commits == 0
    assert screen.errors[0][0] == "Bərpa başlamadı"


def test_expired_backup_has_no_restore_button() -> None:
    """Müddəti bitmiş nüsxə üçün `ok="0"` — ekran düymə göstərmir."""
    controller, _session = _backup_controller(_BackupUseCase([_restore_point(expired=True)]))
    screen = _BackupScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows[0]["ok"] == "0"
    assert screen.rows[0]["status"] == "Müddəti bitib"


def test_backup_creation_is_committed() -> None:
    use_case = _BackupUseCase([])
    controller, session = _backup_controller(use_case)
    screen = _BackupScreen()

    controller._on_create(screen)  # type: ignore[arg-type]

    assert use_case.created == 1
    assert session.commits == 1


# --------------------------------------------------------------------------- #
# Baza keçidi
# --------------------------------------------------------------------------- #


class _InfraScreen:
    theme = object()

    def __init__(self) -> None:
        self.active: Any = None
        self.warnings: list[str] = []
        self.history: list[dict[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.phases: list[tuple[Any, str]] = []
        self.resets = 0

    def set_active_target(self, target: Any) -> None:
        self.active = target

    def set_warnings(self, warnings: list[str]) -> None:
        self.warnings = warnings

    def set_history(self, rows: list[dict[str, str]]) -> None:
        self.history = rows

    def set_phase_state(self, phase: Any, state: str) -> None:
        self.phases.append((phase, state))

    def reset_phases(self) -> None:
        self.resets += 1

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _SwitchUseCase:
    def __init__(self, *, warnings: list[str] | None = None) -> None:
        self.warnings = warnings or []
        self.executed: list[Any] = []
        self.preflights: list[Any] = []

    def preflight(self, *, tenant_id: Any, actor: Any, plan: Any) -> list[str]:
        self.preflights.append(plan)
        return list(self.warnings)

    def execute(self, *, tenant_id: Any, actor: Any, plan: Any) -> Any:
        self.executed.append(plan)
        from src.application.use_cases.db_switch import MigrationReport
        from src.domain.value_objects.infrastructure import MigrationStatus

        report = MigrationReport(plan=plan)
        report.status = MigrationStatus.COMPLETED
        return report


class _EventLog:
    def history(self, tenant_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
        return []


class _InfraUow:
    def __init__(self) -> None:
        self.connection = _InfraConnection()

    def repository(self, name: str) -> Any:
        assert name == "migration_events"
        return _EventLog()


class _InfraConnection:
    def execute(self, sql: str, params: Any = None) -> _Cursor:
        # `_active_target` sorğusu — heç bir tamamlanmış keçid yoxdur.
        return _Cursor([])


class _InfraSession:
    def __init__(self, use_case: _SwitchUseCase) -> None:
        self.tenant_id = TENANT
        self.db_switch = use_case
        self.uow = _InfraUow()
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _infra_controller(
    use_case: _SwitchUseCase,
) -> tuple[InfrastructureController, _InfraSession]:
    session = _InfraSession(use_case)
    return (InfrastructureController(_Context(session), _actor()), session)  # type: ignore[arg-type]


def test_switch_request_only_opens_the_confirmation_dialog(monkeypatch: Any) -> None:
    """MƏCBURİ QAPI: `switch_requested` keçidi BAŞLATMIR.

    Ön yoxlama aparılır, modal açılır — `execute()` isə YALNIZ istifadəçi
    hədəf bazanın adını yazdıqdan sonra çağırılır.
    """
    use_case = _SwitchUseCase(warnings=["12 sinxronlaşmamış yazı var."])
    controller, session = _infra_controller(use_case)
    screen = _InfraScreen()

    opened: list[Any] = []

    class _Dialog:
        def __init__(
            self,
            _theme: Any,
            *,
            destination: Any,
            summary: str,
            warnings: list[str],
            parent: Any = None,
        ) -> None:
            opened.append((destination, warnings))
            self.confirmed = _Signal()

        def exec(self) -> None:
            """Modal açılır, istifadəçi təsdiqləmir."""

    monkeypatch.setattr(
        "src.presentation.screens.group_i.MigrationConfirmDialog", _Dialog, raising=True
    )

    controller._on_switch(screen, "PRIVATE_SERVER")  # type: ignore[arg-type]

    assert use_case.preflights, "Ön yoxlama aparılmalıdır"
    assert opened, "Təsdiq modalı açılmalıdır"
    # Ön yoxlama xəbərdarlıqları modal-a ötürülür — istifadəçi qərardan ƏVVƏL
    # görməlidir.
    assert opened[0][1] == ["12 sinxronlaşmamış yazı var."]
    assert use_case.executed == [], "Təsdiqsiz keçid İCRA OLUNMAMALIDIR"
    assert session.commits == 0


def test_preflight_denial_prevents_the_dialog_from_opening(monkeypatch: Any) -> None:
    """`can_switch_db` yoxdursa modal ÜMUMİYYƏTLƏ açılmır."""

    class _DeniedSwitch(_SwitchUseCase):
        def preflight(self, *, tenant_id: Any, actor: Any, plan: Any) -> list[str]:
            raise _DeniedError("flag yoxdur")

    use_case = _DeniedSwitch()
    controller, _session = _infra_controller(use_case)
    screen = _InfraScreen()

    opened: list[Any] = []

    class _Dialog:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            opened.append(True)
            self.confirmed = _Signal()

        def exec(self) -> None:  # pragma: no cover - açılmamalıdır
            pass

    monkeypatch.setattr(
        "src.presentation.screens.group_i.MigrationConfirmDialog", _Dialog, raising=True
    )

    controller._on_switch(screen, "PRIVATE_SERVER")  # type: ignore[arg-type]

    assert opened == [], "Səlahiyyətsiz istifadəçi təsdiq modalını görməməlidir"
    assert use_case.executed == []
    assert screen.errors[0][0] == "Keçid başlamadı"


def test_execute_runs_only_after_confirmation() -> None:
    """Təsdiqdən sonra keçid icra olunur və gedişat ekrana köçürülür."""
    from src.domain.value_objects.infrastructure import DatabaseTarget, MigrationPlan

    use_case = _SwitchUseCase()
    controller, session = _infra_controller(use_case)
    screen = _InfraScreen()
    plan = MigrationPlan(source=DatabaseTarget.CLOUD, destination=DatabaseTarget.PRIVATE_SERVER)

    controller._execute(screen, plan)  # type: ignore[arg-type]

    assert use_case.executed == [plan]
    assert session.commits == 1
    assert screen.resets == 1


def test_unknown_target_is_ignored_without_crashing() -> None:
    """Naməlum hədəf açarı `ValueError` ilə örtüyü çökdürmür."""
    use_case = _SwitchUseCase()
    controller, _session = _infra_controller(use_case)
    screen = _InfraScreen()

    controller._on_switch(screen, "NAMƏLUM")  # type: ignore[arg-type]

    assert use_case.preflights == []
    assert use_case.executed == []
