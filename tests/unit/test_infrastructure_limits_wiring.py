"""ROOT limitlərinin FAKTİKİ istehlakçıya çatması (Faza 10.2, ikinci dalğa).

──────────────────────────────────────────────────────────────────────────────
BU FAYL NİYƏ VAR — «GÖRÜNÜR, LAKİN İŞLƏMİR» QÜSURU
──────────────────────────────────────────────────────────────────────────────
`tests/unit/test_infrastructure_root_limits.py` `InfrastructureLimits`-in ÖZÜNÜ
yoxlayır: açar var, defolt var, klamp işləyir. Lakin həmin sinif KİMSƏ onu
QURMASA heç nə etmir — 20 infrastruktur sinfi `limits=None` ilə qalır, hər oxu
`DEFAULT_LIMITS` fallback-ını qaytarır və Root sürüşdürücünü tərpədəndə HEÇ NƏ
baş vermir. Parametr ROOT ekranında görünər, faktiki olaraq isə hardcode qalar.

Ona görə buradakı testlər zənciri UCDAN-UCA gəzir:

    ROOT dəyəri (`system_limits`) → `ApplicationContext` → konkret sinif →
    həmin sinfin oxuduğu dəyər

Sahtə `Database` işlədilir: bağlantı yoxdur, lakin `repository("limits")`
zənciri REALdır — yəni test bağlantını deyil, MƏHZ QOŞULMANI yoxlayır.

──────────────────────────────────────────────────────────────────────────────
FALLBACK YOLU DA YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
Qoşulma məcburiyyətə ÇEVRİLMƏMƏLİDİR: kiosk ilk açılışda, offline rejimdə və
testlərdə `limits=None` yolu işləməyə davam etməlidir (bax
`InfrastructureLimits` başlığı). Aşağıdakı `..._without_a_port_...` testləri
məhz bunu bağlayır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Final

import pytest

import src.infrastructure.offline.buffer as buffer_module
import src.infrastructure.persistence.migration as migration_module
import src.infrastructure.security.encryption as encryption_module
import src.infrastructure.storage.image_cache as image_cache_module
import src.infrastructure.storage.upload_queue as upload_queue_module
import src.presentation.composition as composition_module
from src.application.use_cases.audit_query import AuditFilter
from src.application.use_cases.shift_scheduling import ShiftRequestError
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    SalesTransactionId,
    StoreId,
    TenantId,
)
from src.infrastructure.config.limits import InfrastructureLimits
from src.presentation.composition import ApplicationContext
from src.presentation.controllers.sales_review import _low_confidence_percent
from src.presentation.controllers.screen_data import matrix_window_days
from tests.fixtures.fakes import FakeFeatureToggles, FakeSystemLimits

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.UUID("11111111-1111-1111-1111-111111111111"))
STORE: Final = StoreId(uuid.UUID("22222222-2222-2222-2222-222222222222"))
NOW: Final = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _FakeUnitOfWork:
    """`repository("limits")` REAL, qalanı boş — test bağlantını yoxlamır."""

    def __init__(self, limits: FakeSystemLimits) -> None:
        self._limits = limits
        self.closed = False

    def repository(self, name: str) -> Any:
        return self._limits if name == "limits" else _AnyRepository()

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - sadə ötürücü
        return _AnyRepository()


class _AnyRepository:
    """Hər metod çağırışını udan repo əvəzi — use case-lər onu yalnız SAXLAYIR."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


class _FakeDatabase:
    """`unit_of_work()` verən minimal baza — SQL icra edilmir."""

    def __init__(self, limits: FakeSystemLimits) -> None:
        self.limits = limits
        self.opened_units = 0
        self.pool_windows: list[InfrastructureLimits] = []

    @contextmanager
    def unit_of_work(self, tenant_id: TenantId, *, user_id: Any = None) -> Iterator[Any]:
        self.opened_units += 1
        yield _FakeUnitOfWork(self.limits)

    def apply_root_pool_limits(self, limits: InfrastructureLimits) -> tuple[int, int]:
        self.pool_windows.append(limits)
        return (
            limits.int_of(SystemLimitKey.DB_POOL_MIN_SIZE),
            limits.int_of(SystemLimitKey.DB_POOL_MAX_SIZE),
        )


def _context(limits: FakeSystemLimits) -> ApplicationContext:
    """Canlı obyekt qrafı — sahtə baza üzərində."""
    return ApplicationContext(database=_FakeDatabase(limits), tenant_id=TENANT)  # type: ignore[arg-type]


class _Recorder:
    """Konstruktoruna verilən `limits` pəncərəsini yadda saxlayan sahtə."""

    seen: ClassVar[list[InfrastructureLimits | None]] = []

    def __init__(self, *args: Any, limits: InfrastructureLimits | None = None, **kwargs: Any):
        type(self).seen.append(limits)
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


def _fresh_recorder() -> type[_Recorder]:
    """Hər test üçün ayrı `seen` siyahısı — testlər bir-birini görməməlidir."""
    return type("_FreshRecorder", (_Recorder,), {"seen": []})


# --------------------------------------------------------------------------- #
# 1. Uzun ömürlü istehlakçılar
# --------------------------------------------------------------------------- #


def test_root_value_reaches_the_evidence_upload_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sübut növbəsi ROOT pəncərəsini alır və CANLI dəyəri oxuyur."""
    monkeypatch.setenv("KOMPASOS_EVIDENCE_QUEUE_PATH", str(tmp_path / "queue.db"))
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.UPLOAD_CLAIM_STALE_AFTER_SECONDS, "1800")
    recorder = _fresh_recorder()
    monkeypatch.setattr(upload_queue_module, "EvidenceUploadQueue", recorder)

    context = _context(limits)
    context.evidence_queue()

    assert len(recorder.seen) == 1
    window = recorder.seen[0]
    assert window is not None, "Növbə `limits=None` ilə qurulubsa ROOT dəyəri ölüdür"
    assert window.is_live is True
    assert window.int_of(SystemLimitKey.UPLOAD_CLAIM_STALE_AFTER_SECONDS) == 1800


def test_root_value_reaches_the_drive_factory_and_image_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive fabriki VƏ şəkil keşi — ikisi də eyni canlı pəncərəni alır."""
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_SECRET", "test-secret")
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.EVIDENCE_JPEG_QUALITY, "60")
    limits.set(SystemLimitKey.IMAGE_CACHE_TTL_SECONDS, "7200")

    factory_recorder = _fresh_recorder()
    cache_recorder = _fresh_recorder()
    connections = __import__(
        "src.infrastructure.storage.connections", fromlist=["DriveProviderFactory"]
    )
    drive_api = __import__("src.infrastructure.storage.drive_api", fromlist=["OAuthClient"])
    monkeypatch.setattr(connections, "DriveProviderFactory", factory_recorder)
    monkeypatch.setattr(connections, "DriveConnectionRepository", _AnyRepository)
    monkeypatch.setattr(drive_api, "OAuthClient", _AnyRepository)
    monkeypatch.setattr(image_cache_module, "ImageCache", cache_recorder)
    monkeypatch.setattr(encryption_module, "EncryptionService", _AnyRepository)

    context = _context(limits)
    monkeypatch.setattr(context, "_store_names", _AnyRepository)
    context.drive_providers(max_upload_bytes=1024)

    assert factory_recorder.seen and factory_recorder.seen[0] is not None
    assert factory_recorder.seen[0].int_of(SystemLimitKey.EVIDENCE_JPEG_QUALITY) == 60
    assert cache_recorder.seen and cache_recorder.seen[0] is not None
    assert cache_recorder.seen[0].int_of(SystemLimitKey.IMAGE_CACHE_TTL_SECONDS) == 7200


def test_root_value_reaches_the_offline_buffer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offline bufer də pəncərəni alır — təkrar cəhd cədvəli Root-dandır."""
    monkeypatch.setenv("KOMPASOS_SQLITE_PATH", str(tmp_path / "buffer.db"))
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS, "45,90,180")
    recorder = _fresh_recorder()
    monkeypatch.setattr(buffer_module, "OfflineBuffer", recorder)
    monkeypatch.setattr(migration_module, "BufferDrainAdapter", lambda buffer: buffer)
    monkeypatch.setattr(encryption_module, "EncryptionService", _AnyRepository)

    context = _context(limits)
    context.offline_drain()._ensure()

    assert recorder.seen and recorder.seen[0] is not None
    assert recorder.seen[0].int_tuple_of(SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS) == (
        45,
        90,
        180,
    )


# --------------------------------------------------------------------------- #
# 2. Sessiya ömürlü istehlakçılar
# --------------------------------------------------------------------------- #


def test_root_value_reaches_session_scoped_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bildirişçi, ehtiyat nüsxə xidməti və 1C fabriki — üçü də canlı pəncərə alır.

    Bu üçü sessiya ömürlüdür və pəncərəni AÇIQ bağlantının repo-sundan alır
    (bax `composition._build_session`) — yəni burada `Database.unit_of_work`
    ikinci dəfə çağırılmamalıdır.
    """
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.NOTIFY_MAX_ATTEMPTS, "9")
    limits.set(SystemLimitKey.BACKUP_DUMP_TIMEOUT_SECONDS, "7200")
    limits.set(SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS, "45.0")

    notifier_module = __import__(
        "src.infrastructure.notifications.notifier", fromlist=["PostgresNotifier"]
    )
    backup_module = __import__(
        "src.infrastructure.backup.service", fromlist=["NightlyBackupService"]
    )
    connector_module = __import__(
        "src.infrastructure.erp.one_c_connector", fromlist=["OneCConnectorFactory"]
    )
    notifier_recorder = _fresh_recorder()
    backup_recorder = _fresh_recorder()
    connector_recorder = _fresh_recorder()
    monkeypatch.setattr(notifier_module, "PostgresNotifier", notifier_recorder)
    monkeypatch.setattr(backup_module, "NightlyBackupService", backup_recorder)
    monkeypatch.setattr(connector_module, "OneCConnectorFactory", connector_recorder)

    context = _context(limits)
    database: Any = context.database
    before = database.opened_units
    session = context._build_session(_FakeUnitOfWork(limits))  # type: ignore[arg-type]

    assert session is not None
    for recorder, key, expected in (
        (notifier_recorder, SystemLimitKey.NOTIFY_MAX_ATTEMPTS, 9),
        (backup_recorder, SystemLimitKey.BACKUP_DUMP_TIMEOUT_SECONDS, 7200),
    ):
        assert recorder.seen and recorder.seen[0] is not None
        assert recorder.seen[0].int_of(key) == expected
    assert connector_recorder.seen and connector_recorder.seen[0] is not None
    assert connector_recorder.seen[0].float_of(SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS) == 45.0
    assert database.opened_units == before, (
        "Sessiya daxilindəki obyektlər AÇIQ bağlantıdan oxumalıdır — "
        "ikinci iş vahidi açılıbsa hər ekran əməliyyatı hovuzdan əlavə tutum alır."
    )


# --------------------------------------------------------------------------- #
# 3. Bootstrap paradoksu — DB hovuzu
# --------------------------------------------------------------------------- #


def test_pool_limits_are_applied_after_the_connection_works() -> None:
    """Hovuz fallback ilə qalxır, ROOT dəyəri SONRA tətbiq olunur."""
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.DB_POOL_MIN_SIZE, "2")
    limits.set(SystemLimitKey.DB_POOL_MAX_SIZE, "16")
    context = _context(limits)
    database: Any = context.database

    composition_module._apply_root_pool_limits(context)

    assert database.pool_windows, "`apply_root_pool_limits` heç çağırılmayıb"
    assert database.pool_windows[0].int_of(SystemLimitKey.DB_POOL_MIN_SIZE) == 2
    assert database.pool_windows[0].int_of(SystemLimitKey.DB_POOL_MAX_SIZE) == 16


def test_pool_limit_failure_does_not_stop_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Limit oxunmasa tətbiq İŞƏ DÜŞMƏYƏ DAVAM EDİR (fail-safe)."""
    context = _context(FakeSystemLimits())

    def _boom(_limits: InfrastructureLimits) -> tuple[int, int]:
        raise RuntimeError("hovuz əlçatmazdır")

    monkeypatch.setattr(context.database, "apply_root_pool_limits", _boom)

    composition_module._apply_root_pool_limits(context)  # istisna ATMAMALIDIR


# --------------------------------------------------------------------------- #
# 4. Canlı oxu — Root dəyişikliyi dərhal görünür
# --------------------------------------------------------------------------- #


def test_the_window_reads_the_root_value_at_call_time() -> None:
    """Keş YOXDUR: Root dəyəri dəyişən kimi növbəti oxu onu görür."""
    limits = FakeSystemLimits()
    window = _context(limits).infrastructure_limits()

    assert window.int_of(SystemLimitKey.DRIVE_MAX_RETRIES) == 3
    limits.set(SystemLimitKey.DRIVE_MAX_RETRIES, "7")
    assert window.int_of(SystemLimitKey.DRIVE_MAX_RETRIES) == 7


def test_a_failing_database_falls_back_instead_of_raising() -> None:
    """Bağlantı ölübsə oxu istisna ATMIR — fallback işləyir."""

    class _DeadDatabase:
        def unit_of_work(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("baza əlçatmazdır")

    context = ApplicationContext(database=_DeadDatabase(), tenant_id=TENANT)  # type: ignore[arg-type]

    assert context.infrastructure_limits().int_of(SystemLimitKey.DB_POOL_MAX_SIZE) == 8


def test_without_a_port_the_consumers_still_work() -> None:
    """`limits=None` yolu QALIR — kiosk/offline/test bağlantısız işləməlidir."""
    window = InfrastructureLimits()

    assert window.is_live is False
    assert window.int_of(SystemLimitKey.NOTIFY_MAX_ATTEMPTS) == int(
        DEFAULT_LIMITS[SystemLimitKey.NOTIFY_MAX_ATTEMPTS]
    )


# --------------------------------------------------------------------------- #
# 5. Təqdimat qatının YENİ açarları (migrations/035)
# --------------------------------------------------------------------------- #


class _FakeSession:
    """`session.limits` + `tenant_id` — ekran doldurucularının gördüyü qədəri."""

    def __init__(self, limits: FakeSystemLimits) -> None:
        self.limits = limits
        self.tenant_id = TENANT


@pytest.mark.parametrize(
    ("key", "previous_hardcode"),
    [
        (SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS, "14"),
        (SystemLimitKey.EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS, "120"),
        (SystemLimitKey.ERP_MATCH_LOW_CONFIDENCE_PERCENT, "50"),
        (SystemLimitKey.DEVELOPER_CRASH_ROW_LIMIT, "12"),
        (SystemLimitKey.DEVELOPER_TICKET_ROW_LIMIT, "12"),
    ],
)
def test_new_defaults_equal_the_previous_hardcode(
    key: SystemLimitKey, previous_hardcode: str
) -> None:
    """Köçürmə davranış dəyişikliyi DEYİL — defolt köhnə ədədlə eynidir.

    `EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS` istisna kimi görünə bilər (kodda
    120_000 ms idi) — vahid saniyəyə çevrilib, RİTM eynidir: 120 san = 120_000 ms.
    """
    assert DEFAULT_LIMITS[key] == previous_hardcode


def test_matrix_window_days_follows_root() -> None:
    """Növbə matrisinin pəncərəsi Root dəyərini oxuyur."""
    limits = FakeSystemLimits()
    session = _FakeSession(limits)

    assert matrix_window_days(session) == 14  # type: ignore[arg-type]
    limits.set(SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS, "30")
    assert matrix_window_days(session) == 30  # type: ignore[arg-type]


def test_matrix_window_never_collapses_to_zero() -> None:
    """`0` matrisi sütunsuz qoyardı — ən azı bir gün qaytarılır."""
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS, "0")

    assert matrix_window_days(_FakeSession(limits)) == 1  # type: ignore[arg-type]


def test_low_confidence_threshold_follows_root() -> None:
    """«Zəif uyğunluq» rəng həddi Root dəyərini oxuyur."""
    limits = FakeSystemLimits()
    session = _FakeSession(limits)

    assert _low_confidence_percent(session) == 50
    limits.set(SystemLimitKey.ERP_MATCH_LOW_CONFIDENCE_PERCENT, "80")
    assert _low_confidence_percent(session) == 80


def test_upload_poll_interval_follows_root() -> None:
    """Fon dövrəsinin ritmi Root-dandır; alt hədd taymeri fasiləsiz buraxmır."""
    from src.presentation.app import (
        FALLBACK_UPLOAD_POLL_INTERVAL_MS,
        KompasApplication,
    )

    limits = FakeSystemLimits()
    context = _context(limits)

    class _Stub:
        """`KompasApplication`-ın metodu üçün minimal `self` — Qt tələb etmir."""

        _context = context

    read = KompasApplication._upload_poll_interval_ms
    assert read(_Stub()) == FALLBACK_UPLOAD_POLL_INTERVAL_MS  # type: ignore[arg-type]

    limits.set(SystemLimitKey.EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS, "600")
    assert read(_Stub()) == 600_000  # type: ignore[arg-type]

    # `0` QTimer-i hər hadisə dövrəsində işə salardı — alt hədd bunu bağlayır.
    limits.set(SystemLimitKey.EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS, "0")
    assert read(_Stub()) == 10_000  # type: ignore[arg-type]


def test_upload_poll_interval_without_a_context_uses_the_fallback() -> None:
    """Önizləmə/dizayn rejimində kontekst yoxdur — sabit ritm işləyir."""
    from src.presentation.app import (
        FALLBACK_UPLOAD_POLL_INTERVAL_MS,
        KompasApplication,
    )

    class _Stub:
        _context = None

    assert (
        KompasApplication._upload_poll_interval_ms(_Stub())  # type: ignore[arg-type]
        == FALLBACK_UPLOAD_POLL_INTERVAL_MS
    )


# --------------------------------------------------------------------------- #
# 6. Sessiya use case-lərinin ROOT pəncərəsi (Faza 10.2, üçüncü dalğa)
# --------------------------------------------------------------------------- #
#
# ÜÇÜNCÜ DALĞANIN BAĞLADIĞI BOŞLUQ: səkkiz use case `limits` PARAMETRİNİ QƏBUL
# EDİRDİ, lakin `composition._build_session` onu ÖTÜRMÜRDÜ. Nəticə
# `test_application_root_limits.py`-ın gördüyündən fərqli idi: orada port ƏLLƏ
# verilir və davranış doğru dəyişir, CANLI qrafda isə `limits=None` qalırdı —
# yəni parametr ROOT ekranında görünür, Root onu dəyişir, sistem isə köhnə
# fallback ilə işləməyə davam edirdi.
#
# Buradakı testlər zənciri UCDAN-UCA gəzir:
#
#     `system_limits` sətri → `_build_session` → use case → repo çağırışı
#
# Yəni "use case-i əl ilə qursaq işləyir" deyil, "KOMPOZİSİYA KÖKÜ onu düzgün
# qurur" yoxlanılır. `limits=repo("limits")` sətri silinsə, testlər qırılır.


def _employee(role: SystemRole, *flags: str) -> Employee:
    """Verilmiş flag-lərə malik işçi — səlahiyyət qapılarını keçmək üçün."""
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for code in flags:
        position.grant(PermissionFlag(code=code, category="SISTEM"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


class _LimitSpy:
    """`limit=` arqumentini qeyd edən universal repo əvəzi.

    Hər metod boş siyahı (sayğaclar üçün `0`) qaytarır — testin marağı NƏ
    qaytarıldığı deyil, use case-in repo-ya HANSI həddi ötürdüyüdür.
    """

    def __init__(self) -> None:
        self.seen: list[int | None] = []

    def __getattr__(self, name: str) -> Any:
        def _call(*args: Any, **kwargs: Any) -> Any:
            if "limit" in kwargs:
                self.seen.append(kwargs["limit"])
            return 0 if name.startswith(("count", "queue_size")) else []

        return _call


class _AuditReaderSpy:
    """`AuditLogReader` sahtəsi — süzgəcin son `limit` dəyərini saxlayır."""

    def __init__(self) -> None:
        self.seen: list[int] = []

    def query(self, tenant_id: TenantId, filters: AuditFilter) -> list[Any]:
        self.seen.append(filters.limit)
        return []

    def count(self, tenant_id: TenantId, filters: AuditFilter) -> int:
        return 0

    def distinct_actions(self, tenant_id: TenantId) -> list[str]:
        return []


class _AdminCountSpy:
    """`uow.employees` — sihirbazın saydığı aktiv admin sayı."""

    def __init__(self, count: int) -> None:
        self._count = count

    def count_active_with_flag(self, tenant_id: TenantId, flag: str) -> int:
        return self._count

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


class _PointsSpy:
    """`sales_points` repo-su — yazılan sətri saxlayır (xal kursunun sübutu)."""

    def __init__(self) -> None:
        self.entries: list[Any] = []

    def find_by_transaction(self, tenant_id: TenantId, transaction_id: Any) -> Any:
        return None

    def save(self, entry: Any) -> None:
        self.entries.append(entry)

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: []


class _WiredUnitOfWork:
    """Adı verilmiş repo-lar üçün casus, qalanı üçün boş ötürücü."""

    def __init__(self, limits: FakeSystemLimits, repos: dict[str, Any]) -> None:
        self._limits = limits
        self._repos = repos
        self.employees = repos.get("employees_attr", _AnyRepository())
        self.leave_requests = _AnyRepository()
        self.fines = _AnyRepository()
        self.attendance = _AnyRepository()
        self.positions = _AnyRepository()
        self.audit = _AnyRepository()
        # TOGGLE-lar AÇIQ olmalıdır: `_AnyRepository.is_enabled` `None`
        # qaytarır, yəni HƏR modul "deaktiv" görünərdi və testlər limitə
        # çatmadan modul qapısında dayanardı.
        self._toggles = FakeFeatureToggles()

    def repository(self, name: str) -> Any:
        if name == "limits":
            return self._limits
        if name == "toggles":
            return self._repos.get(name, self._toggles)
        return self._repos.get(name, _AnyRepository())

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - sadə ötürücü
        return _AnyRepository()


def _session(limits: FakeSystemLimits, **repos: Any) -> Any:
    """CANLI kompozisiya kökü ilə qurulmuş sessiya — sahtə bağlantı üzərində."""
    unit_of_work: Any = _WiredUnitOfWork(limits, repos)
    return _context(limits)._build_session(unit_of_work)


def test_session_audit_query_reads_the_root_page_size() -> None:
    """`AuditQueryUseCase` — həm defolt səhifə, həm tavan ROOT-dan."""
    reader = _AuditReaderSpy()
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE, "7")
    limits.set(SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE, "9")
    session = _session(limits, audit_reader=reader)
    viewer = _employee(SystemRole.CEO, "can_view_audit_logs")

    session.audit_query.search(tenant_id=TENANT, actor=viewer)
    assert reader.seen[-1] == 7, "Kompozisiya kökü `limits=` ötürmür — açar ölü qalıb"

    session.audit_query.search(tenant_id=TENANT, actor=viewer, filters=AuditFilter(limit=500))
    assert reader.seen[-1] == 9, "ROOT tavanı canlı qrafda tətbiq olunmur"


def test_session_backup_history_reads_the_root_page_size() -> None:
    """`BackupAccessUseCase` — İKİ AYRI pəncərə: use case portu + xidmət örtüyü."""
    catalog = _LimitSpy()
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE, "12")
    session = _session(limits, backup_records=catalog)
    admin = _employee(SystemRole.ROOT, "can_manage_backups")

    session.backups.restore_points(tenant_id=TENANT, actor=admin)
    assert catalog.seen == [12]


def test_session_support_threads_read_the_root_page_size() -> None:
    tickets = _LimitSpy()
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE, "4")
    session = _session(limits, support=tickets)
    actor = _employee(SystemRole.CEO, "can_contact_support")

    session.support.threads(tenant_id=TENANT, actor=actor)
    assert tickets.seen == [4]


def test_session_sync_conflicts_read_the_root_page_size() -> None:
    conflicts = _LimitSpy()
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE, "6")
    session = _session(limits, sync_conflicts=conflicts)
    actor = _employee(SystemRole.ROOT, "can_view_employee_reports")

    session.sync_conflicts.inbox(tenant_id=TENANT, actor=actor)
    assert conflicts.seen == [6]


def test_session_setup_wizard_reads_the_root_admin_count() -> None:
    """`FirstRunSetupUseCase` — sihirbaz ERKƏNDİR, lakin sessiya AÇIQDIR."""
    limits = FakeSystemLimits()
    session = _session(limits, employees_attr=_AdminCountSpy(2))

    assert session.setup._warning_for(TENANT) is None
    limits.set(SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT, "3")
    assert session.setup._warning_for(TENANT) is not None


def test_session_shift_swap_reads_the_root_lead_window() -> None:
    """`ShiftSwapUseCase` — 90 günlük defolt 30-a enəndə 60 günlük sorğu RƏDD."""
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS, "30")
    session = _session(limits)
    seller = _employee(SystemRole.SELLER)

    with pytest.raises(ShiftRequestError, match="30 gün"):
        session.shift_swaps.submit(
            tenant_id=TENANT,
            employee=seller,
            # Sessiya REAL `Clock` işlədir, ona görə tarix sistem saatından
            # hesablanır — sabit tarix bir gün sonra "keçmiş" olardı.
            target_date=datetime.now(UTC).date() + timedelta(days=60),
            reason="Ailə vəziyyəti",
        )


def test_session_sales_points_read_the_root_currency_rate() -> None:
    """`SalesPointsUseCase` — 100 AZN/xal kursu 50-yə düşəndə xal İKİQATLANIR."""
    points = _PointsSpy()
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT, "50")
    session = _session(limits, sales_points=points)

    entry = session.sales_points.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId("1C-WIRING-1"),
        gross_amount=Decimal("500.00"),
        confidence=MatchConfidence.EXACT_MATCH,
    )
    assert entry is not None
    assert entry.points == 10, "Xal kursu canlı qrafda hələ də modul fallback-ındadır"


def test_session_sales_review_queue_reads_the_root_page_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SalesReviewQueueUseCase` — repo öz iş vahidini açır, limit isə sessiyadan."""
    queue = _LimitSpy()
    sales_module = __import__(
        "src.infrastructure.erp.sales", fromlist=["PostgresSalesReviewRepository"]
    )
    monkeypatch.setattr(
        sales_module, "PostgresSalesReviewRepository", lambda *args, **kwargs: queue
    )
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE, "8")
    session = _session(limits)
    actor = _employee(SystemRole.CEO, "can_manage_sales_points")

    session.sales_review.queue(tenant_id=TENANT, actor=actor)
    assert queue.seen == [8]


def test_offline_drain_receives_the_window_by_keyword() -> None:
    """`_LazyBufferDrain` pəncərəni AÇAR SÖZLƏ alır — statik audit üçün.

    Mövqeli arqument işləyərdi, lakin "limits qəbul edən hər sinif `limits=`
    almalıdır" yoxlamasını keçməzdi və sətir yalançı-boşluq kimi görünərdi.
    """
    drain = _context(FakeSystemLimits()).offline_drain()

    assert drain._limits.is_live is True


# --------------------------------------------------------------------------- #
# 7. Uzun ömürlü infrastruktur klientləri (Faza 10.2, üçüncü dalğa)
# --------------------------------------------------------------------------- #
#
# LİSENZİYA VƏ YENİLƏNMƏ KLİENTLƏRİ, VƏZİYYƏT FAYLI, DRIVE PROVIDER-İ VƏ
# YENİLƏNMƏ KATALOQU açarları `DEFAULT_LIMITS`-dən oxuyan MODUL SABİTLƏRİNDƏN
# alırdı — yəni ROOT ekranında görünən sürüşdürücü heç nəyə təsir etmirdi.
# İndi hər biri `InfrastructureLimits` pəncərəsi qəbul edir.
#
# İKİ QAPI BİRDƏN:
#   * `..._without_a_window_...` — pəncərə verilmədikdə davranış köçürmədən
#     ƏVVƏLKİ ilə HƏRFƏN eynidir (fallback = `DEFAULT_LIMITS`).
#   * `..._follows_root...` — pəncərə verildikdə Root dəyəri FAKTİKİ işləyir.


class _StubLicenseStore:
    """`LicenseStateStore` portunun minimal sahtəsi — I/O yoxdur."""

    def __init__(self, snapshot: Any = None) -> None:
        self._snapshot = snapshot

    def load(self) -> Any:
        return self._snapshot

    def save(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def first_run_at(self) -> Any:
        return None

    def clock_high_water(self) -> Any:
        return None

    def clock_rollback_detected(self, now: Any) -> bool:
        return False


def _license_client(limits: FakeSystemLimits | None, snapshot: Any = None) -> Any:
    from src.infrastructure.licensing.client import LicenseClient

    window = InfrastructureLimits(limits=limits, tenant_id=TENANT) if limits else None
    return LicenseClient(
        TENANT,
        _AnyRepository(),  # type: ignore[arg-type]
        _StubLicenseStore(snapshot),  # type: ignore[arg-type]
        app_version="1.0.0",
        limits=window,
        clock=lambda: NOW,
    )


def test_license_client_without_a_window_keeps_the_previous_rhythm() -> None:
    """Pəncərəsiz klient köhnə ritmi saxlayır — köçürmə davranışı dəyişmir."""
    client = _license_client(None)

    assert client._interval == float(
        DEFAULT_LIMITS[SystemLimitKey.LICENSE_CHECK_IN_INTERVAL_SECONDS]
    )
    assert client._retry_interval == float(
        DEFAULT_LIMITS[SystemLimitKey.LICENSE_RETRY_INTERVAL_SECONDS]
    )
    assert client._blocked_interval == float(
        DEFAULT_LIMITS[SystemLimitKey.LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS]
    )


def test_license_client_rhythm_follows_the_root_values() -> None:
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.LICENSE_CHECK_IN_INTERVAL_SECONDS, "43200")
    limits.set(SystemLimitKey.LICENSE_RETRY_INTERVAL_SECONDS, "900")
    limits.set(SystemLimitKey.LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS, "120")
    client = _license_client(limits)

    assert client._interval == 43200.0
    assert client._retry_interval == 900.0
    assert client._blocked_interval == 120.0


def test_license_client_grace_band_is_read_at_call_time() -> None:
    """Qrace bandı HƏR `current_state()` çağırışında oxunur — keş YOXDUR.

    Bandı konstruktorda dondursaydıq, «offline qrace 14 günə qaldırılsın»
    qərarı yalnız proqram yenidən başladıqdan sonra işləyərdi — halbuki həmin
    qərar məhz şəbəkəsi kəsilmiş filial üçün TƏCİLİ verilir.
    """
    from src.domain.value_objects.licensing import (
        LicenseSnapshot,
        LicenseStatus,
        RestrictionKind,
    )

    snapshot = LicenseSnapshot(
        status=LicenseStatus.AKTIV,
        checked_at=NOW - timedelta(days=10),
        vendor_contact="destek@kompas.az",
    )
    limits = FakeSystemLimits()
    client = _license_client(limits, snapshot)

    assert not client.current_state().has(RestrictionKind.LICENSE_UNVERIFIED)

    limits.set(SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS, "7")
    assert client.current_state().has(RestrictionKind.LICENSE_UNVERIFIED)


def test_license_payment_banner_follows_the_root_warning_days() -> None:
    from src.domain.value_objects.licensing import LicenseSnapshot, LicenseStatus

    snapshot = LicenseSnapshot(
        status=LicenseStatus.AKTIV,
        checked_at=NOW,
        expires_at=NOW + timedelta(days=20),
        vendor_contact="destek@kompas.az",
    )
    limits = FakeSystemLimits()
    client = _license_client(limits, snapshot)

    assert client.payment_banner() == ""

    limits.set(SystemLimitKey.LICENSE_EXPIRY_WARNING_DAYS, "30")
    assert "20 gün" in client.payment_banner()


def test_state_store_rollback_tolerance_follows_root(tmp_path: Path) -> None:
    """Saat-geri tolerantlığı ROOT-dandır; açıq arqument ondan ÜSTÜNDÜR."""
    from src.infrastructure.licensing.state_store import EncryptedLicenseStateStore

    key = SystemLimitKey.LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS
    limits = FakeSystemLimits()

    plain = EncryptedLicenseStateStore(
        TENANT,
        _AnyRepository(),  # type: ignore[arg-type]
        directory=tmp_path,
    )
    assert plain._tolerance == float(DEFAULT_LIMITS[key])

    limits.set(key, "600")
    from_root = EncryptedLicenseStateStore(
        TENANT,
        _AnyRepository(),  # type: ignore[arg-type]
        directory=tmp_path,
        limits=InfrastructureLimits(limits=limits, tenant_id=TENANT),
    )
    assert from_root._tolerance == 600.0

    explicit = EncryptedLicenseStateStore(
        TENANT,
        _AnyRepository(),  # type: ignore[arg-type]
        directory=tmp_path,
        rollback_tolerance_seconds=45.0,
        limits=InfrastructureLimits(limits=limits, tenant_id=TENANT),
    )
    assert explicit._tolerance == 45.0


def _update_client(limits: FakeSystemLimits | None, tmp_path: Path) -> Any:
    from src.infrastructure.updates.client import AutoUpdateClient

    window = InfrastructureLimits(limits=limits, tenant_id=TENANT) if limits else None
    return AutoUpdateClient(
        TENANT,
        _AnyRepository(),  # type: ignore[arg-type]
        _AnyRepository(),  # type: ignore[arg-type]
        current_version="1.0.0",
        staging_root=tmp_path,
        limits=window,
    )


def test_update_client_without_a_window_keeps_the_previous_rhythm(tmp_path: Path) -> None:
    client = _update_client(None, tmp_path)

    assert client._interval == float(DEFAULT_LIMITS[SystemLimitKey.UPDATE_CHECK_INTERVAL_SECONDS])
    assert client._retry_interval == float(
        DEFAULT_LIMITS[SystemLimitKey.UPDATE_RETRY_INTERVAL_SECONDS]
    )


def test_update_client_rhythm_follows_the_root_values(tmp_path: Path) -> None:
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.UPDATE_CHECK_INTERVAL_SECONDS, "3600")
    limits.set(SystemLimitKey.UPDATE_RETRY_INTERVAL_SECONDS, "300")
    client = _update_client(limits, tmp_path)

    assert client._interval == 3600.0
    assert client._retry_interval == 300.0


def test_update_package_ceiling_follows_root_on_both_sides() -> None:
    """Yayımçı VƏ yükləyici EYNİ həddi görməlidir — açar da eynidir."""
    from src.infrastructure.updates.catalog import SupabaseReleaseCatalog
    from src.infrastructure.updates.publisher import ReleasePublisher

    limits = FakeSystemLimits()
    window = InfrastructureLimits(limits=limits, tenant_id=TENANT)
    catalog = SupabaseReleaseCatalog(_AnyRepository(), limits=window)  # type: ignore[arg-type]
    publisher = ReleasePublisher(_AnyRepository(), limits=window)  # type: ignore[arg-type]

    fallback = int(DEFAULT_LIMITS[SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES])
    assert catalog._max_package_bytes() == fallback
    assert publisher._max_package_bytes() == fallback

    limits.set(SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES, "104857600")
    assert catalog._max_package_bytes() == 104857600
    assert publisher._max_package_bytes() == 104857600


def test_update_package_ceiling_ignores_an_unusable_root_value() -> None:
    """`0` həddi SÖNDÜRMÜR — diski dolduran yükləmə qapısı açıq qalmamalıdır."""
    from src.infrastructure.updates.catalog import SupabaseReleaseCatalog

    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES, "0")
    catalog = SupabaseReleaseCatalog(
        _AnyRepository(),  # type: ignore[arg-type]
        limits=InfrastructureLimits(limits=limits, tenant_id=TENANT),
    )

    assert catalog._max_package_bytes() == int(
        DEFAULT_LIMITS[SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES]
    )


def test_evidence_image_edges_follow_root() -> None:
    """Sübut şəklinin İKİ KƏNARI (tam + kiçik) ROOT-dandır."""
    from src.infrastructure.storage.google_drive import GoogleDriveStorageProvider

    limits = FakeSystemLimits()
    provider = GoogleDriveStorageProvider(
        api=_AnyRepository(),  # type: ignore[arg-type]
        folders=_AnyRepository(),  # type: ignore[arg-type]
        cache=_AnyRepository(),  # type: ignore[arg-type]
        connection_id=uuid.uuid4(),
        limits=InfrastructureLimits(limits=limits, tenant_id=TENANT),
    )

    assert provider._full_max_edge() == int(
        DEFAULT_LIMITS[SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX]
    )
    assert provider._thumbnail_max_edge() == int(
        DEFAULT_LIMITS[SystemLimitKey.EVIDENCE_THUMBNAIL_MAX_EDGE_PX]
    )

    limits.set(SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX, "2400")
    limits.set(SystemLimitKey.EVIDENCE_THUMBNAIL_MAX_EDGE_PX, "160")
    assert provider._full_max_edge() == 2400
    assert provider._thumbnail_max_edge() == 160

    # Sıfır kənar şəkli bir piksellik ləkəyə çevirərdi — fallback qoruyur.
    limits.set(SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX, "0")
    assert provider._full_max_edge() == int(
        DEFAULT_LIMITS[SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX]
    )
