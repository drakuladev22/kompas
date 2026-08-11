"""pytest-qt karkasının smoke testi + tam-yığın E2E ssenariləri (bölmə 1, 5).

Fayl iki işi görür:

    1. `pytest-qt` karkasının işlək olduğunu təsdiqləyir (QApplication + widget).
    2. Bu faylda yeri rəsmiləşdirilmiş üç E2E ssenarisini saxlayır:
       PIN handshake → cərimə → sync · dual-control eskalasiyası ·
       offline → online konflikt həlli.

PySide6 quraşdırılmayıbsa Qt testləri `skip` olunur (`requires_qt`).

──────────────────────────────────────────────────────────────────────────────
SSENARİLƏRİN CARİ VƏZİYYƏTİ
──────────────────────────────────────────────────────────────────────────────
Üçüncü ssenari (offline → konflikt → HR həlli) ARTIQ İŞLƏYİR: bufer SQLite
faylıdır və konflikt aşkarlanması yalnız uzaq sətri OXUMAĞA ehtiyac duyur,
yəni sahtə bağlantı ilə tam axın keçilə bilir (aşağı bax).

Qalan ikisi hələ `skip`-dədir və səbəb FAZA deyil, konkret asılılıqdır:
onların yoxlamalı olduğu hissə məhz PostgreSQL-ə YAZILAN nəticədir
(repository round-trip + 1C sinxronizasiyası), yəni `DATABASE_URL` tələb
edir — layihədə bütün belə testlər `tests/integration/`-dadır və eyni qapı
ilə atlanır. İnterfeys tərəfi `tests/e2e/test_antifraud_flow_e2e.py`-də
onsuz da yoxlanılır.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from tests.conftest import requires_qt

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.e2e, pytest.mark.qt]


@requires_qt
def test_qapp_fixture_available(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`pytest-qt` işləyir və QApplication yaradıla bilir."""
    assert qt_app is not None


@requires_qt
def test_widget_can_be_shown(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Widget yaradılıb göstərilə bilir (offscreen platformada da)."""
    from PySide6.QtWidgets import QLabel

    label = QLabel("KompasOS")
    qtbot.addWidget(label)
    label.show()

    assert label.text() == "KompasOS"


@pytest.mark.skip(
    reason="Cərimənin BAZAYA yazılması və 1C sinxronizasiyası canlı Postgres "
    "tələb edir (DATABASE_URL). İnterfeys tərəfi hazırdır: "
    "tests/e2e/test_antifraud_flow_e2e.py; hesablama qaydası: "
    "tests/unit/test_use_cases.py"
)
def test_pin_handshake_to_fine_calculation_e2e() -> None:
    """PLACEHOLDER: STEP 1 → STEP 2 → STEP 3 → cərimə → sync tam axını.

    ARTIQ YOXLANILAN hissə (`test_antifraud_flow_e2e.py`):
        * PIN daxil edilməsi və 4 rəqəmdən sonra göndərilməsi,
        * səhv PIN / lockout davranışı,
        * PIN → İşçi Ana Ekranı keçidi,
        * cərimə formasının foto sübutu olmadan göndərilməməsi.

    Cərimə düsturu və status keçidləri `tests/unit/test_use_cases.py`-də
    yaddaşdaxili repo-larla tam yoxlanılır.

    BURADA QALAN hissə: eyni axının REAL repository üzərindən keçməsi və
    1C-yə sinxronizasiyası — hər ikisi canlı baza tələb edir.
    """


@pytest.mark.skip(
    reason="İkinci təsdiqin BAZADA saxlanması canlı Postgres tələb edir "
    "(DATABASE_URL). Hədd hesablaması və təsdiq qaydası yaddaşdaxili "
    "repo-larla yoxlanılır: tests/unit/test_use_cases.py"
)
def test_dual_control_escalation_e2e() -> None:
    """PLACEHOLDER: 30+ dəqiqəlik manual override → HR_Admin/CEO ikinci təsdiqi.

    ARTIQ YOXLANILAN hissə: 30 dəqiqə həddinin hesablanması, modalın
    "Dual-Control tələb olunacaq" xəbərdarlığı və məcburi səbəb sahəsi
    (`test_antifraud_flow_e2e.py`), təsdiq qapısı və özünü-təsdiq qadağası
    (`test_use_cases.py`).

    BURADA QALAN hissə: gözləmə vəziyyətinin və ikinci təsdiqin bazada
    saxlanması (`leave_requests` round-trip).
    """


# --------------------------------------------------------------------------- #
# Offline → online → CONFLICT → HR_Admin manual həlli (bölmə 5)
# --------------------------------------------------------------------------- #
#
# NİYƏ BU SSENARİ QT TƏLƏB ETMİR — axın tamamilə məlumat qatındadır: bufer
# (SQLite) → sinxronizasiya → `sync_conflicts` → HR qərarı. Ekran yalnız
# nəticəni göstərir və onun bağlantısı `screen_data`/`sync_conflicts`
# testlərindədir. Ssenari isə bu faylda vəd edilib, ona görə burada qalır.
#
# NİYƏ SAHTƏ BAĞLANTI KİFAYƏTDİR — konflikt yolu uzaq sətri yalnız OXUYUR
# (`SELECT * FROM ... WHERE id = %s` + `information_schema`) və `INSERT`-i
# `sync_conflicts`-ə yazır. Yerli tərəfdəki bütün vəziyyət dəyişikliyi isə
# REAL SQLite buferindədir — yəni testin yoxladığı hissə saxta deyil.
# Postgres-ə faktiki yazılışın düzgünlüyü `tests/integration/`-ın işidir.


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self._conn = connection
        self._rows: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: Any, params: tuple[Any, ...] = ()) -> None:
        text = str(query)
        self._conn.statements.append(text)
        if "information_schema.columns" in text:
            self._rows = [
                {"column_name": name, "udt_schema": "pg_catalog", "udt_name": "text"}
                for name in ("id", "status", "updated_at")
            ]
        elif text.strip().upper().startswith("INSERT INTO SYNC_CONFLICTS"):
            self._conn.recorded_conflicts.append(params)
            self._rows = []
        else:
            self._rows = [dict(self._conn.remote_row)] if self._conn.remote_row else []

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    def __init__(self, remote_row: dict[str, Any] | None) -> None:
        self.remote_row = remote_row
        self.statements: list[str] = []
        self.recorded_conflicts: list[tuple[Any, ...]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


class _FakeUnitOfWork:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakeDatabase:
    """`Database.unit_of_work()` müqaviləsinin minimal təkrarı."""

    def __init__(self, remote_row: dict[str, Any] | None) -> None:
        self.connection = _FakeConnection(remote_row)
        self.uow = _FakeUnitOfWork(self.connection)

    def health_check(self) -> bool:
        return True

    @contextmanager
    def unit_of_work(self, tenant_id: Any) -> Any:
        yield self.uow


class _ConflictRepository:
    """`sync_conflicts` cədvəlinin yaddaşdaxili əvəzi."""

    def __init__(self, item: Any) -> None:
        self._item = item
        self.resolved: list[tuple[Any, Any, str]] = []

    def list_open(self, tenant_id: Any, *, limit: int = 100) -> list[Any]:
        return [] if self.resolved else [self._item]

    def get(self, conflict_id: Any) -> Any:
        return self._item

    def open_count(self, tenant_id: Any) -> int:
        return 0 if self.resolved else 1

    def resolve(
        self,
        conflict_id: Any,
        *,
        resolution: Any,
        resolved_by: Any,
        resolved_at: datetime,
        note: str,
    ) -> None:
        self.resolved.append((conflict_id, resolution, note))


def _new_buffer(path: Path) -> Any:
    """Şifrələnmiş SQLite buferi — istehsalatdakı ilə eyni sinif, müvəqqəti fayl."""
    from src.infrastructure.offline.buffer import OfflineBuffer
    from src.infrastructure.security.encryption import (
        EncryptionService,
        KeyMaterial,
        generate_key,
    )

    class _Provider:
        name = "static"

        def load(self) -> KeyMaterial:
            return KeyMaterial(primary=generate_key())

    return OfflineBuffer(path, encryption=EncryptionService(_Provider()))  # type: ignore[arg-type]


def _hr_actor(tenant_id: Any) -> Any:
    """Konflikti həll edən HR_Admin — `can_view_employee_reports` qapısı ilə.

    Flag `sync_conflicts.RESOLVE_CONFLICT_FLAG`-dən götürülür, əl ilə
    yazılmır: qapı dəyişsə test onunla birlikdə dəyişməlidir.
    """
    from src.application.use_cases.sync_conflicts import RESOLVE_CONFLICT_FLAG
    from src.domain.entities.employee import Employee
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import PermissionFlag, RolePriority
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import EmployeeId, PositionId

    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=tenant_id,
        is_system=True,
    )
    position.grant(PermissionFlag(code=RESOLVE_CONFLICT_FLAG, category="HR"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name="Aysel",
        last_name="Hüseynova",
        username=Username.parse("a.huseynova"),
        has_password=True,
    )


def test_offline_to_online_conflict_resolution_e2e(tmp_path: Path) -> None:
    """Offline yazı → online sync → CONFLICT → HR manual həlli (bölmə 5).

    Bölmə 5: *"audit-kritik cədvəllər üçün last-write-wins qəbul edilmir.
    Konflikt aşkarlandıqda hər iki versiya saxlanılır, `CONFLICT` statusu ilə
    HR_Admin-ə manual həll üçün göndərilir."*

    Zəncirin hər halqası bir-birinə BAĞLI yoxlanılır: buferdəki yazı
    sinxronizasiyada divergensiya ilə qarşılaşır, `sync_conflicts` sətri
    yaradılır, HR qərar verir və bufer həmin qərara uyğun vəziyyətə keçir.
    Halqaları ayrı-ayrı test etmək (hər biri onsuz da test olunur) "hamısı
    işləyir, amma bir-birinə qoşulmayıb" halını tutmazdı.
    """
    from src.application.use_cases.sync_conflicts import (
        ConflictItem,
        Resolution,
        SyncConflictUseCase,
    )
    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.offline.buffer import Operation, SyncStatus
    from src.infrastructure.offline.sync import OfflineSyncService
    from tests.fixtures.fakes import FakeClock, RecordingAudit

    tenant_uuid = uuid.uuid4()
    tenant_id = TenantId(tenant_uuid)
    record_id = str(uuid.uuid4())
    offline_moment = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    # Mağaza offline düşməzdən ƏVVƏL oxuduğu versiya.
    base_version = offline_moment - timedelta(hours=2)

    buffer = _new_buffer(tmp_path / "offline.db")
    try:
        # 1. OFFLINE: mağazada icazə sorğusu təsdiqlənir, bufer sətri yazılır.
        entry_id = buffer.enqueue(
            tenant_id=str(tenant_uuid),
            table_name="leave_requests",
            record_id=record_id,
            operation=Operation.UPDATE,
            payload={"status": "VERIFIED"},
            base_version=base_version,
            now=offline_moment,
        )
        assert buffer.counts()["PENDING"] == 1

        # 2. ONLINE: buludda EYNİ sətir artıq dəyişdirilib (daha yeni versiya).
        database = _FakeDatabase(
            {
                "id": record_id,
                "status": "TIMEOUT_ESCALATED",
                "updated_at": offline_moment + timedelta(minutes=30),
            }
        )
        service = OfflineSyncService(
            buffer=buffer,
            database=database,  # type: ignore[arg-type]
            is_online=lambda: True,
        )
        report = service.run_once(now=offline_moment + timedelta(hours=1))

        # 3. KONFLİKT: last-write-wins TƏTBİQ EDİLMİR — sətir üzərinə yazılmır.
        assert report.conflicts == 1
        assert report.synced == 0
        assert database.connection.recorded_conflicts, "`sync_conflicts` sətri yazılmalıdır"
        assert not any(
            statement.strip().upper().startswith('INSERT INTO "LEAVE_REQUESTS"')
            for statement in database.connection.statements
        ), "Audit-kritik cədvəl konfliktdə ÜZƏRİNƏ yazılmamalıdır"

        conflicted = buffer.conflicts()
        assert len(conflicted) == 1
        assert conflicted[0].id == entry_id
        assert conflicted[0].status is SyncStatus.CONFLICT
        assert buffer.pending(now=offline_moment + timedelta(days=1)) == [], (
            "Konfliktdəki sətir təkrar cəhdə düşməməlidir"
        )

        # Hər iki versiya saxlanılıb — HR ekranı onları yan-yana göstərir.
        local_payload, remote_payload = database.connection.recorded_conflicts[0][3:5]
        assert json.loads(local_payload)["status"] == "VERIFIED"
        assert json.loads(remote_payload)["status"] == "TIMEOUT_ESCALATED"

        # 4. HR_ADMIN MANUAL HƏLLİ.
        item = ConflictItem(
            conflict_id=uuid.uuid4(),
            table_name="leave_requests",
            record_id=record_id,
            local_version=json.loads(local_payload),
            remote_version=json.loads(remote_payload),
            detected_at=offline_moment + timedelta(hours=1),
        )
        assert item.is_audit_critical
        assert "status" in item.differing_fields()

        repository = _ConflictRepository(item)
        audit = RecordingAudit()
        use_case = SyncConflictUseCase(
            repository=repository,  # type: ignore[arg-type]
            audit=audit,  # type: ignore[arg-type]
            clock=FakeClock(offline_moment + timedelta(hours=2)),  # type: ignore[arg-type]
        )
        actor = _hr_actor(tenant_id)

        assert use_case.inbox(tenant_id=tenant_id, actor=actor) == [item]
        use_case.resolve(
            tenant_id=tenant_id,
            actor=actor,
            conflict_id=item.conflict_id,
            resolution=Resolution.KEPT_REMOTE,
            note="Kamera qeydinə görə bulud versiyası doğrudur",
        )

        assert repository.resolved[0][1] is Resolution.KEPT_REMOTE
        assert "SYNC_CONFLICT_RESOLVED" in audit.actions()

        # 5. QƏRAR BUFERƏ TƏTBİQ OLUNUR: yerli versiya atılır, növbə boşalır.
        buffer.resolve_conflict(entry_id, keep_local=False)

        assert buffer.conflicts() == []
        assert buffer.counts()["CONFLICT"] == 0
        assert buffer.pending(now=offline_moment + timedelta(days=1)) == []
    finally:
        buffer.close()
