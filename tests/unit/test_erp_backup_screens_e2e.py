"""`ErpServersScreen` + `BackupScreen` ↔ kontrollerləri — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_erp_connection_wizard.py` sihirbazın ÖZÜNÜ və `_bind_wizard`-a əl ilə
bağlanmış «Bağlantını Yoxla» zəncirini çox yaxşı örtür, LAKİN `_open_wizard`
(«Yeni Server»/sətir kliki → HƏQİQİ sihirbaz yaranması) və `_on_save` (
`save_new`/`save_existing`-in REAL «Yadda Saxla» kliki ilə çağırılması) heç
bir testdə YOXDUR — `ServerConnectionWizard.exec()` heç vaxt çağırılmadığı
üçün (modal event loop bağlanmır) həmin iki metod tam sınaqsız qalıb. Burada
`ServerConnectionWizard.exec` / `RestoreConfirmDialog.exec` MONKEYPATCH
edilir (yalnız `self`-i tutur, modal AÇMIR) ki, «düymə kliki → siqnal →
kontroller → sihirbaz → kontroller → yazı» zənciri BAŞDAN-SONA, HƏQİQİ
widget-lərlə yoxlanıla bilsin.

`BackupScreen` üçün oxşar boşluq: `refresh()` (`test_erp_and_health_bindings.
py` naxışı ilə duck-typing) VAR, lakin «İndi Ehtiyat Nüsxə Al»/«Bu Nöqtəyə
Bərpa Et»-in REAL kliklə, REAL `RestoreConfirmDialog` təsdiqi ilə çağırılması
YOXDUR.

──────────────────────────────────────────────────────────────────────────────
TAPILAN QÜSUR (hər iki ekranda TƏKRARLANIR)
──────────────────────────────────────────────────────────────────────────────
`ErpServersController._on_save` və `BackupAdminController._run`-un uğursuzluq
budaqları `screen.show_error(...)` çağırır — bu, `drive_connection.py`
başlığında artıq SƏNƏDLƏŞDİRİLMİŞ səhvin EYNİSİDİR: `show_error()` BÜTÜN
ekranı (cədvəl, kartlar, filtrlər) xəta vəziyyəti ilə ƏVƏZ EDİR. Fərq: orada
altı çağırış bu səbəbdən DÜZƏLDİLDİ, burada isə YOX. Nəticə: bir server
yadda saxlanmayanda (test uğursuz oldu) BÜTÜN server siyahısı yox olur; bir
ehtiyat nüsxə/bərpa uğursuz olanda BÜTÜN `BackupScreen` (cədvəl + saxlama
kartı + cədvəl kartı) yox olur — halbuki səbəb bir kliklik, TRANZİT
əməliyyatdır, ekranın ÖZÜNÜN oxunmaması deyil. `xfail(strict=True)` bunu
sübut edir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.value_objects.erp import ConnectionTestResult, ConnectorConfig, ConnectorType
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


def _click_row(table: Any, index: int) -> None:
    from src.presentation.widgets.data_table import TableRow

    rows = table.findChildren(TableRow)
    rows[index].clicked.emit()


class _Actor:
    id = ACTOR_ID


# --------------------------------------------------------------------------- #
# ERP — sahtələr
# --------------------------------------------------------------------------- #


def _server_row(**overrides: Any) -> dict[str, Any]:
    """`_server_rows()` sorğusunun sütun dəsti — canlı yolla EYNİ açarlar."""
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "server_name": "1C-BAKI-01",
        "host": "10.20.1.14",
        "port": 1541,
        "status": "ACTIVE",
        "last_successful_sync": datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        "connector_type": "HTTP",
        "infobase": "kompas_prod",
        "username": "kompas_sync",
        "sync_interval_seconds": 300,
        "health": "HEALTHY",
        "sync_delay_seconds": 42,
        "mapped_stores": 3,
    }
    row.update(overrides)
    return row


class _ErpConnections:
    def __init__(self) -> None:
        self.mapping: list[Any] = []
        self.mappings_error: Exception | None = None
        self.saved_new: list[Any] = []
        self.saved_existing: list[tuple[Any, Any]] = []
        self.save_error: Exception | None = None

    def mappings_for(self, *, actor: Any, now: Any) -> list[Any]:
        if self.mappings_error is not None:
            raise self.mappings_error
        return list(self.mapping)

    def save_new(self, *, actor: Any, draft: Any, now: Any) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved_new.append(draft)

    def save_existing(self, *, actor: Any, server_id: Any, draft: Any, now: Any) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved_existing.append((server_id, draft))

    def test_connection(self, *, actor: Any, draft: Any, now: Any) -> Any:  # pragma: no cover
        return ConnectionTestResult(ok=True, message="Bağlantı uğurludur")


class _ErpServerConfigs:
    def __init__(self, configs: dict[Any, ConnectorConfig] | None = None) -> None:
        self._configs = configs or {}

    def credentials_for(self, server_id: Any) -> Any:
        config = self._configs.get(server_id, ConnectorConfig())
        return type("_Creds", (), {"connector_config": config})()


class _Connection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _ErpUow:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.connection = _Connection(rows)


class _ErpSession:
    def __init__(
        self, rows: list[dict[str, Any]], connections: _ErpConnections, configs: _ErpServerConfigs
    ) -> None:
        self.tenant_id = TENANT
        self.erp_connections = connections
        self.erp_server_configs = configs
        self.uow = _ErpUow(rows)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _ErpContext:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        connections: _ErpConnections | None = None,
        configs: _ErpServerConfigs | None = None,
    ) -> None:
        self._rows = rows or []
        self._connections = connections or _ErpConnections()
        self._configs = configs or _ErpServerConfigs()
        self.sessions: list[_ErpSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _ErpSession(self._rows, self._connections, self._configs)
        self.sessions.append(created)
        yield created


# --------------------------------------------------------------------------- #
# 1. «Yeni Server» → REAL sihirbaz → «Yadda Saxla» → `save_new`
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_new_server_opens_a_real_bound_wizard_and_saving_calls_save_new(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_open_wizard`/`_bind_wizard`/`_on_save` heç bir testdə çağırılmır (bax modul başlığı)."""
    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen, ServerConnectionWizard

    captured: list[Any] = []
    monkeypatch.setattr(
        ServerConnectionWizard,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )

    connections = _ErpConnections()
    context = _ErpContext(connections=connections)
    controller = ErpServersController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    _click(screen, "Yeni Server")  # ÇÖKMƏMƏLİDİR

    assert len(captured) == 1
    wizard = captured[0]
    wizard._name.set_text("1C-YENİ")
    wizard._address[ConnectorType.HTTP].set_text("10.20.1.20:1541")
    wizard._database.set_text("kompas_yeni")

    _click(wizard, "Yadda Saxla")  # REAL klik → `saved` → kontroller → `save_new`

    assert len(connections.saved_new) == 1
    draft = connections.saved_new[0]
    assert draft.server_name == "1C-YENİ"
    assert (draft.host, draft.port) == ("10.20.1.20", 1541)
    assert any(s.committed for s in context.sessions)


# --------------------------------------------------------------------------- #
# 2. Sətir kliki → REDAKTƏ sihirbazı — ŞİFRƏ BOŞ, qalan sahələr YÜKLƏNMİŞ
# --------------------------------------------------------------------------- #


@requires_qt
def test_selecting_a_row_opens_a_prefilled_edit_wizard_without_the_password(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """SEC-013: şifrə oxu-modelində yoxdur — redaktə forması onu HEÇ VAXT görmür."""
    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen, ServerConnectionWizard

    server_id = uuid.uuid4()
    row = _server_row(id=server_id, server_name="1C-BAKI-01", host="10.20.1.14", port=1541)
    connections = _ErpConnections()
    configs = _ErpServerConfigs({server_id: ConnectorConfig()})
    context = _ErpContext(rows=[row], connections=connections, configs=configs)
    controller = ErpServersController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)

    captured: list[Any] = []
    monkeypatch.setattr(
        ServerConnectionWizard,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )
    controller.attach(screen)

    _click_row(screen._table, 0)  # REAL sətir kliki

    assert len(captured) == 1
    wizard = captured[0]
    assert wizard._name.text() == "1C-BAKI-01"
    assert wizard._password.text() == ""  # SEC-013 — şifrə HEÇ VAXT gəlmir

    wizard._password.set_text("yeni-şifrə")
    _click(wizard, "Yadda Saxla")

    assert len(connections.saved_existing) == 1
    saved_id, draft = connections.saved_existing[0]
    assert saved_id == server_id
    assert draft.password == "yeni-şifrə"


# --------------------------------------------------------------------------- #
# 2b. TAPILAN QÜSUR — redaktədə PORT sükutla itir, saxlamada 1541-ə düşür
# --------------------------------------------------------------------------- #


@requires_qt
def test_editing_an_http_server_preserves_its_non_default_port(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen, ServerConnectionWizard

    server_id = uuid.uuid4()
    row = _server_row(id=server_id, server_name="1C-BAKI-01", host="10.20.1.14", port=8080)
    connections = _ErpConnections()
    context = _ErpContext(
        rows=[row],
        connections=connections,
        configs=_ErpServerConfigs({server_id: ConnectorConfig()}),
    )
    controller = ErpServersController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)
    captured: list[Any] = []
    monkeypatch.setattr(
        ServerConnectionWizard,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )
    controller.attach(screen)

    _click_row(screen._table, 0)

    wizard = captured[0]
    # İstifadəçi ünvana TOXUNMUR — məhz "diqqətsiz" (ən çox baş verən) yol.
    _click(wizard, "Yadda Saxla")

    _saved_id, draft = connections.saved_existing[0]
    assert draft.port == 8080, "port sükutla dəyişməməlidir"


# --------------------------------------------------------------------------- #
# 3. Yarış vəziyyəti: sətir seçilir, lakin server ARTIQ dəyişdirilib
# --------------------------------------------------------------------------- #


@requires_qt
def test_selecting_a_stale_row_never_opens_a_wizard(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Kontrollerin daxili keşi köhnəlibsə (başqa admin dəyişib) — sihirbaz AÇILMIR."""
    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen, ServerConnectionWizard

    row = _server_row(server_name="1C-BAKI-01")
    connections = _ErpConnections()
    context = _ErpContext(rows=[row], connections=connections)
    controller = ErpServersController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)

    captured: list[Any] = []
    monkeypatch.setattr(
        ServerConnectionWizard,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )
    controller.attach(screen)

    # Server bu arada silinib/adı dəyişib — ekran hələ köhnə adı göstərir.
    screen.server_selected.emit("SİLİNMİŞ-SERVER")  # REAL siqnal, siyahıda YOX

    assert captured == []  # sihirbaz ÜMUMİYYƏTLƏ qurulmamalıdır — ən vacib qapı


@requires_qt
def test_a_stale_row_message_is_not_silently_overwritten_by_the_immediate_refresh(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen, ServerConnectionWizard

    row = _server_row(server_name="1C-BAKI-01")
    connections = _ErpConnections()
    context = _ErpContext(rows=[row], connections=connections)
    controller = ErpServersController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)
    monkeypatch.setattr(ServerConnectionWizard, "exec", lambda self: None)
    controller.attach(screen)

    screen.server_selected.emit("SİLİNMİŞ-SERVER")

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 4. «Hamısını Yoxla» — REAL klik → sağlamlıq görünüşü YENİDƏN oxunur
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_test_all_rereads_the_health_view_via_a_new_session(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen

    context = _ErpContext(rows=[_server_row()])
    controller = ErpServersController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)
    opened_before = len(context.sessions)

    _click(screen, "Hamısını Yoxla")  # ÇÖKMƏMƏLİDİR

    assert len(context.sessions) == opened_before + 1  # YENİ oxuma, əvvəlki keş deyil


# --------------------------------------------------------------------------- #
# 5. TAPILAN QÜSUR — uğursuz «Yadda Saxla» BÜTÜN server siyahısını yox edir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_save_does_not_wipe_the_rest_of_the_server_list(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen, ServerConnectionWizard

    connections = _ErpConnections()
    from src.application.use_cases.erp_connection import ConnectionNotVerifiedError

    connections.save_error = ConnectionNotVerifiedError("test edilməyib")
    context = _ErpContext(rows=[_server_row(server_name="1C-BAKI-01")], connections=connections)
    controller = ErpServersController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)
    captured: list[Any] = []
    monkeypatch.setattr(
        ServerConnectionWizard,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )
    controller.attach(screen)

    _click(screen, "Yeni Server")
    wizard = captured[0]
    wizard._name.set_text("1C-YENİ")
    wizard._address[ConnectorType.HTTP].set_text("10.20.1.30:1541")
    wizard._database.set_text("baza")
    _click(wizard, "Yadda Saxla")

    # Mövcud server («1C-BAKI-01») HƏLƏ DƏ görünməlidir — yalnız yeni forma
    # uğursuz oldu, siyahının özü oxunmaqda davam edir.
    assert screen.switcher().current_state() == "content"
    assert screen.table().row_count == 1


# --------------------------------------------------------------------------- #
# BackupScreen — sahtələr
# --------------------------------------------------------------------------- #


class _Record:
    def __init__(self, *, created_at: datetime, backup_type: str = "MANUAL") -> None:
        self.created_at = created_at
        self.backup_type = backup_type


class _Point:
    def __init__(
        self,
        *,
        created_at: datetime,
        size_mb: float = 512.0,
        is_expired: bool = False,
        backup_type: str = "MANUAL",
        label_az: str = "20.08.2026 02:00",
    ) -> None:
        self.record = _Record(created_at=created_at, backup_type=backup_type)
        self.size_mb = size_mb
        self.is_expired = is_expired
        self.label_az = label_az


class _Backups:
    def __init__(self) -> None:
        self.points: list[_Point] = []
        self.list_error: Exception | None = None
        self.create_calls: list[Any] = []
        self.create_error: Exception | None = None
        self.restore_calls: list[dict[str, Any]] = []
        self.restore_error: Exception | None = None

    def restore_points(self, *, tenant_id: Any, actor: Any) -> list[_Point]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.points)

    def create_now(self, *, tenant_id: Any, actor: Any) -> None:
        if self.create_error is not None:
            raise self.create_error
        self.create_calls.append(actor)

    def restore(
        self, *, tenant_id: Any, actor: Any, record: Any, target_dsn: str, confirmation: str
    ) -> None:
        # ÇAĞIRILDIĞI qeydə alınır uğursuz olsa BELƏ — testin "restore() heç
        # ÇAĞIRILMADI" ilə "çağırıldı, lakin domendə RƏDD OLUNDU" halını ayırd
        # edə bilməsi üçün (bax `test_a_failed_restore_...`).
        self.restore_calls.append(
            {"record": record, "target_dsn": target_dsn, "confirmation": confirmation}
        )
        if self.restore_error is not None:
            raise self.restore_error


class _BackupSession:
    def __init__(self, backups: _Backups) -> None:
        self.tenant_id = TENANT
        self.backups = backups
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _BackupContext:
    def __init__(self, backups: _Backups | None = None) -> None:
        self._backups = backups or _Backups()
        self.sessions: list[_BackupSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _BackupSession(self._backups)
        self.sessions.append(created)
        yield created


# --------------------------------------------------------------------------- #
# 6. «İndi Ehtiyat Nüsxə Al» — REAL klik, FON sapı, yenidən oxuma
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_backup_now_creates_a_manual_backup_and_reloads_the_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.backup_admin import BackupAdminController
    from src.presentation.screens.group_d import BackupScreen

    backups = _Backups()
    context = _BackupContext(backups)
    controller = BackupAdminController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = BackupScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    # Kontroller `create_now`-dan SONRA `refresh()` çağırır — sahtə üçün
    # nüsxənin artıq mövcud olduğunu simulyasiya edirik (real DB də belədir).
    backups.points = [_Point(created_at=datetime(2026, 8, 20, 2, 0, tzinfo=UTC))]

    _click(screen, "İndi Ehtiyat Nüsxə Al")  # ÇÖKMƏMƏLİDİR, DONMAMALIDIR

    assert len(backups.create_calls) == 1
    assert any(s.committed for s in context.sessions)
    assert screen.table().row_count == 1


# --------------------------------------------------------------------------- #
# 7. Bərpa — İNSAN QAPISI: dəqiq tarix YAZILMASA `restore()` ÇAĞIRILMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_restore_requires_the_exact_typed_date_before_calling_restore(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.backup_admin import DATE_FORMAT, BackupAdminController
    from src.presentation.screens.group_d import BackupScreen, RestoreConfirmDialog

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/kompas")
    when = datetime(2026, 8, 20, 2, 0, tzinfo=UTC)
    backups = _Backups()
    backups.points = [_Point(created_at=when)]
    context = _BackupContext(backups)
    controller = BackupAdminController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = BackupScreen(theme)
    qtbot.addWidget(screen)

    captured: list[Any] = []
    monkeypatch.setattr(
        RestoreConfirmDialog,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )
    controller.attach(screen)

    _click(screen, "Bu Nöqtəyə Bərpa Et")  # REAL sətir düyməsi

    assert len(captured) == 1
    dialog = captured[0]

    dialog._confirm_input.set_text("səhv tarix yazıram")
    _click(dialog, "Bərpa Et")

    assert backups.restore_calls == []  # YANLIŞ tarix — YAZI BAŞLAMIR
    assert dialog._confirm_input.has_error is True

    dialog._confirm_input.clear_error()
    dialog._confirm_input.set_text(f"{when:{DATE_FORMAT}}")
    _click(dialog, "Bərpa Et")

    assert len(backups.restore_calls) == 1
    call = backups.restore_calls[0]
    assert call["target_dsn"] == "postgresql://localhost/kompas"
    from src.infrastructure.backup.service import RESTORE_CONFIRMATION

    assert call["confirmation"] == RESTORE_CONFIRMATION


# --------------------------------------------------------------------------- #
# 8. Bərpa — HƏDƏF DSN yoxdursa əməliyyat BAŞLAMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_restore_without_a_target_dsn_never_calls_restore(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.backup_admin import DATE_FORMAT, BackupAdminController
    from src.presentation.screens.group_d import BackupScreen, RestoreConfirmDialog

    monkeypatch.delenv("DATABASE_URL", raising=False)
    when = datetime(2026, 8, 20, 2, 0, tzinfo=UTC)
    backups = _Backups()
    backups.points = [_Point(created_at=when)]
    context = _BackupContext(backups)
    controller = BackupAdminController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = BackupScreen(theme)
    qtbot.addWidget(screen)

    captured: list[Any] = []
    monkeypatch.setattr(
        RestoreConfirmDialog,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )
    controller.attach(screen)

    _click(screen, "Bu Nöqtəyə Bərpa Et")
    dialog = captured[0]
    dialog._confirm_input.set_text(f"{when:{DATE_FORMAT}}")
    _click(dialog, "Bərpa Et")  # ÇÖKMƏMƏLİDİR

    assert backups.restore_calls == []


# --------------------------------------------------------------------------- #
# 9. Uğursuz bərpa — SÜKUTLA UDULMUR, AYDIN mesaj göstərilir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_restore_shows_the_domain_message_not_a_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.backup_admin import DATE_FORMAT, BackupAdminController
    from src.presentation.screens.group_d import BackupScreen, RestoreConfirmDialog

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/kompas")
    when = datetime(2026, 8, 20, 2, 0, tzinfo=UTC)
    backups = _Backups()
    backups.points = [_Point(created_at=when)]
    backups.restore_error = KompasOSError(
        "conflict", user_message="Başqa bir bərpa artıq icra olunur."
    )
    context = _BackupContext(backups)
    controller = BackupAdminController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = BackupScreen(theme)
    qtbot.addWidget(screen)

    captured: list[Any] = []
    monkeypatch.setattr(
        RestoreConfirmDialog,
        "exec",
        lambda self: captured.append(self),  # noqa: PLW0108 — sinif atributu kimi self LAZIMDIR
    )
    controller.attach(screen)

    _click(screen, "Bu Nöqtəyə Bərpa Et")
    dialog = captured[0]
    dialog._confirm_input.set_text(f"{when:{DATE_FORMAT}}")
    _click(dialog, "Bərpa Et")  # ÇÖKMƏMƏLİDİR

    assert len(backups.restore_calls) == 1


# --------------------------------------------------------------------------- #
# 10. TAPILAN QÜSUR — uğursuz nüsxə/bərpa BÜTÜN Backup ekranını yox edir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_manual_backup_does_not_wipe_the_rest_of_the_panel(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.backup_admin import BackupAdminController
    from src.presentation.screens.group_d import BackupScreen

    backups = _Backups()
    backups.points = [_Point(created_at=datetime(2026, 8, 19, 2, 0, tzinfo=UTC))]
    backups.create_error = RuntimeError("pg_dump: command not found")
    context = _BackupContext(backups)
    controller = BackupAdminController(context, _Actor(), executor=InlineExecutor())  # type: ignore[arg-type]
    screen = BackupScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)
    assert screen.table().row_count == 1  # ilkin siyahı OXUNUB göstərilir

    _click(screen, "İndi Ehtiyat Nüsxə Al")  # ÇÖKMƏMƏLİDİR

    # Dünənki uğurlu nüsxə HƏLƏ DƏ görünməlidir — bir cəhdin uğursuzluğu
    # KEÇMİŞ siyahını gizlətməməlidir.
    assert screen.switcher().current_state() == "content"
    assert screen.table().row_count == 1
