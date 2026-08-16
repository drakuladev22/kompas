"""1C server paneli və Sistem Sağlamlığı — canlı bağlama.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR
──────────────────────────────────────────────────────────────────────────────
İki fərqli risk bağlanır:

1. SEC-013 — 1C şifrəsi ekrana çıxan sətirlərin HEÇ BİRİNDƏ olmamalıdır.
   Sürüşmə bir sözlük açarı qədər asandır və heç bir test onu tutmurdu.
2. «Sistem Sağlamlığı» UYDURMA metrik göstərməməlidir: ölçülə bilməyən
   göstərici (NTP sürüşməsi ölçülməyibsə) kart kimi ÜMUMİYYƏTLƏ qurulmamalıdır
   — `0` göstərmək "saat dəqiqdir" kimi oxunardı.

Testlər Qt TƏLƏB ETMİR: ekranlar duck-typing ilə əvəzlənir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.presentation.controllers.erp_servers import ErpServersController, _draft_from
from src.presentation.controllers.screen_data import ScreenDataBinder

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 40, tzinfo=UTC)


def _actor() -> Any:
    """Flag daşımayan aktor.

    `has_permission` MÜTLƏQ olmalıdır: bildiriş auditoriyası süzgəci
    (`hidden_categories_for`) onu çağırır və metod olmasaydı sorğu `except`
    blokunda udulub siyahı boş qayıdardı — test yaşıl, yol isə ölü olardı.
    """
    return type(
        "_Actor",
        (),
        {"id": EmployeeId(uuid.uuid4()), "has_permission": lambda self, flag, *, now: False},
    )()


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Context:
    def __init__(self, session: Any, *, drift: float | None = None) -> None:
        self._session = session
        self._drift = drift

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session

    def ntp_drift_seconds(self) -> float | None:
        return self._drift

    def offline_drain(self) -> Any:
        class _Drain:
            def pending_count(self, tenant_id: Any) -> int:
                return 3

        return _Drain()


# --------------------------------------------------------------------------- #
# ERP server paneli
# --------------------------------------------------------------------------- #


class _ErpScreen:
    theme = object()

    def __init__(self) -> None:
        self.servers: list[dict[str, str]] = []
        self.mapped = 0
        self.mapping: list[tuple[str, str]] = []
        self.note = ""
        self.sync: list[tuple[str, str, str]] = []
        self.errors: list[tuple[str, str]] = []

    def set_servers(self, servers: list[dict[str, str]], *, mapped_stores: int) -> None:
        self.servers = servers
        self.mapped = mapped_stores

    def set_mapping(self, mapping: list[tuple[str, str]], *, note: str) -> None:
        self.mapping = mapping
        self.note = note

    def set_last_sync(self, entries: list[tuple[str, str, str]]) -> None:
        self.sync = entries

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _ErpUseCase:
    def __init__(self, *, links: list[Any] | None = None, error: Exception | None = None) -> None:
        self.links = links or []
        self.error = error

    def mappings_for(self, *, actor: Any, now: Any) -> list[Any]:
        if self.error is not None:
            raise self.error
        return list(self.links)


class _ErpConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statements: list[str] = []

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.statements.append(sql)
        return _Cursor(self.rows)


class _ErpUow:
    def __init__(self, connection: _ErpConnection) -> None:
        self.connection = connection


class _ErpSession:
    def __init__(self, use_case: _ErpUseCase, rows: list[dict[str, Any]]) -> None:
        self.tenant_id = TENANT
        self.erp_connections = use_case
        self.connection = _ErpConnection(rows)
        self.uow = _ErpUow(self.connection)


def _server_row(**overrides: Any) -> dict[str, Any]:
    #: Sütun dəsti `_server_rows()` sorğusu ilə EYNİDİR — sihirbazın redaktə
    #: axını `connector_type`/`infobase`/`username`/`sync_interval_seconds`
    #: sütunlarını da oxuyur (1c.md GUI fazası).
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "server_name": "1C-BAKI-01",
        "host": "10.20.1.14",
        "port": 1541,
        "status": "ACTIVE",
        "last_successful_sync": NOW,
        "connector_type": "HTTP",
        "infobase": "kompas_prod",
        "username": "kompas_sync",
        "sync_interval_seconds": 300,
        "health": "HEALTHY",
        "sync_delay_seconds": 42,
        "mapped_stores": 9,
    }
    row.update(overrides)
    return row


def _link(store: str, server: str) -> Any:
    from src.application.use_cases.erp_connection import StoreServerLink

    return StoreServerLink(
        store_id=uuid.uuid4(),
        store_name=store,
        server_id=uuid.uuid4(),
        server_name=server,
        one_c_store_code="BAKI-01",
    )


def test_erp_rows_never_carry_credentials() -> None:
    """SEC-013: ekran sətirlərində şifrə/kredensial sahəsi OLMAMALIDIR."""
    session = _ErpSession(_ErpUseCase(links=[_link("Bellona", "1C-BAKI-01")]), [_server_row()])
    controller = ErpServersController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _ErpScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert set(screen.servers[0]) == {
        "name",
        "type",
        "address",
        "stores",
        "latency",
        "latency_meaning",
        "status",
    }
    serialized = str(screen.servers) + str(screen.sync) + str(screen.mapping)
    for forbidden in ("password", "şifrə", "secret", "password_encrypted"):
        assert forbidden.lower() not in serialized.lower()
    # Sorğu da şifrə sütununu SEÇMİR.
    assert all("password" not in sql for sql in session.connection.statements)


def test_erp_status_and_latency_come_from_the_health_view() -> None:
    session = _ErpSession(
        _ErpUseCase(links=[]),
        [_server_row(health="STALE", sync_delay_seconds=7200)],
    )
    controller = ErpServersController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _ErpScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.servers[0]["status"] == "Gecikmə yüksəkdir"
    assert screen.servers[0]["latency"] == "2 saat"
    # Xəritə boşdursa istifadəçi nəticəni GÖRMƏLİDİR.
    assert "Şübhəli Satışlar" in screen.note


def test_erp_permission_denial_is_explained() -> None:
    """`mappings_for()` qapısı bağlıdırsa siyahı OXUNMUR, səbəb göstərilir."""
    from src.application.use_cases.erp_connection import ErpConnectionError

    session = _ErpSession(_ErpUseCase(error=ErpConnectionError("flag yoxdur")), [_server_row()])
    controller = ErpServersController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _ErpScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.servers == []
    assert screen.errors[0][0] == "Panel açıla bilmədi"


def test_draft_requires_the_mandatory_fields() -> None:
    """Ünvan və baza adı boşdursa draft QURULMUR — test də göndərilmir."""
    assert _draft_from({"name": "1C", "host": "", "database": "kompas"}) is None
    assert _draft_from({"name": "1C", "host": "10.0.0.1:1541", "database": ""}) is None

    draft = _draft_from(
        {
            "name": "1C-BAKI-03",
            "host": "10.20.1.16:1541",
            "database": "kompas_prod",
            "username": "sync",
            "password": "gizli",
        }
    )
    assert draft is not None
    assert (draft.host, draft.port) == ("10.20.1.16", 1541)
    # Şifrə draft-da qalır (yaddaşda), lakin audit görünüşünə DÜŞMÜR.
    assert "gizli" not in str(draft.auditable())
    assert "gizli" not in repr(draft)


# --------------------------------------------------------------------------- #
# Sistem Sağlamlığı
# --------------------------------------------------------------------------- #


class _HealthScreen:
    def __init__(self) -> None:
        self.last_check = ""
        self.metrics: list[tuple[str, str, str, str]] = []
        self.latencies: list[tuple[str, str, str]] = []
        self.alerts: list[tuple[str, str, str]] = []

    def set_last_check(self, text: str) -> None:
        self.last_check = text

    def set_metrics(self, items: list[tuple[str, str, str, str]]) -> None:
        self.metrics = items

    def set_latencies(self, entries: list[tuple[str, str, str]]) -> None:
        self.latencies = entries

    def set_alerts(self, alerts: list[tuple[str, str, str]]) -> None:
        self.alerts = alerts


class _HealthConnection:
    def __init__(self, health_rows: list[dict[str, Any]]) -> None:
        self._health_rows = health_rows

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if "v_erp_server_health" in sql and "DEGRADED" in sql:
            return _Cursor([row for row in self._health_rows if row["health"] != "HEALTHY"])
        if "v_erp_server_health" in sql:
            return _Cursor(self._health_rows)
        return _Cursor([{"?column?": 1}])


class _Conflicts:
    def open_count(self, tenant_id: Any) -> int:
        return 2


class _HealthUow:
    def __init__(self, connection: _HealthConnection) -> None:
        self.connection = connection

    def repository(self, name: str) -> Any:
        assert name == "sync_conflicts"
        return _Conflicts()


class _Notifications:
    def list_for_recipient(self, employee_id: Any, *, hidden_categories: Any) -> list[Any]:
        # Süzgəc imzada MƏCBURİDİR — çağırışı unutmaq auditoriya qaydasını
        # sükutla söndürərdi (bax `notification_repositories` başlığı).
        assert hidden_categories is not None
        return []


class _Limits:
    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        return default


class _HealthSession:
    def __init__(self, health_rows: list[dict[str, Any]]) -> None:
        self.tenant_id = TENANT
        self.uow = _HealthUow(_HealthConnection(health_rows))
        self.limits = _Limits()
        self.notifications = _Notifications()


def _health_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "server_name": "1C-BAKI-01",
        "health": "HEALTHY",
        "sync_delay_seconds": 42,
        "last_error_at": None,
        "consecutive_failures": 0,
        "mapped_stores": 9,
    }
    row.update(overrides)
    return row


def _health_binder(session: _HealthSession, *, drift: float | None) -> ScreenDataBinder:
    return ScreenDataBinder(_Context(session, drift=drift), _actor())  # type: ignore[arg-type]


def test_unmeasured_ntp_drift_is_not_rendered_as_zero() -> None:
    """MƏCBURİ: ölçülməyən göstərici kart kimi QURULMUR (uydurma metrik yoxdur)."""
    session = _HealthSession([_health_row()])
    screen = _HealthScreen()

    _health_binder(session, drift=None).populate("health", screen)  # type: ignore[arg-type]

    names = [name for name, *_rest in screen.metrics]
    assert "NTP sapması" not in names
    # Ölçülə bilən göstəricilər isə GÖSTƏRİLİR.
    assert "Baza (DB Ping)" in names
    assert "Sinxronlaşmamış yazı" in names


def test_measured_ntp_drift_is_rendered_with_the_root_limit() -> None:
    session = _HealthSession([_health_row()])
    screen = _HealthScreen()

    _health_binder(session, drift=2.4).populate("health", screen)  # type: ignore[arg-type]

    drift = next(item for item in screen.metrics if item[0] == "NTP sapması")
    assert drift[1] == "+2.4 san"
    assert drift[3] == "success"


def test_problem_servers_become_alerts_with_the_domain_diagnosis() -> None:
    """Xəbərdarlıq mətni domendəki `ServerHealthRow.diagnosis`-dən gəlir."""
    session = _HealthSession(
        [_health_row(health="NEVER_SYNCED", sync_delay_seconds=None, mapped_stores=0)]
    )
    screen = _HealthScreen()

    _health_binder(session, drift=None).populate("health", screen)  # type: ignore[arg-type]

    assert screen.alerts, "Problemli server xəbərdarlıq yaratmalıdır"
    text, _time, tone = screen.alerts[0]
    assert "1C-BAKI-01" in text
    assert "xəritələməsini qurun" in text
    assert tone == "danger"
    # Sinxronlaşmayan server üçün gecikmə "0 san" DEYİL.
    assert screen.latencies[0][1] == "sinxronlaşmayıb"


def test_open_sync_conflicts_appear_as_a_metric_and_an_alert() -> None:
    session = _HealthSession([_health_row()])
    screen = _HealthScreen()

    _health_binder(session, drift=None).populate("health", screen)  # type: ignore[arg-type]

    conflicts = next(item for item in screen.metrics if item[0] == "Sync konflikti")
    assert conflicts[1] == "2"
    assert conflicts[3] == "warning"
    assert any("sinxronizasiya konflikti" in text for text, *_rest in screen.alerts)
