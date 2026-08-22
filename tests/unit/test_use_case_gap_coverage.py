"""Tətbiq qatındakı ƏHATƏSİZ QALMIŞ qərar yolları — Faza 5/6 auditi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA FAYL
──────────────────────────────────────────────────────────────────────────────
Mövcud `test_phase5_use_cases.py` və `test_phase56_gaps.py` hər use case-in
ƏSAS axınını yoxlayır. Ölçmə göstərdi ki, əhatəsiz qalan sətirlər əsasən
İKİNCİ dərəcəli yollardır: səlahiyyət rəddi, "tapılmadı" istisnası, sərhəd
dəyəri (0, boş sətir, tam limit) və bildiriş uğursuzluğu. Məhz bu yollarda
gizlənən qüsur istehsalatda "heç nə olmadı" kimi görünür — istifadəçi düyməni
basır, nəticə yoxdur, log-da da iz yoxdur.

Mövcud testlərə TOXUNULMUR: burada yalnız ÇATIŞAN davranışlar yoxlanılır.
BAZA LAZIM DEYİL — bütün portlar sahtə obyektlərlə əvəz olunur.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.backup_access import (
    BackupAccessError,
    BackupAccessUseCase,
)
from src.application.use_cases.catalog_management import (
    CatalogChange,
    CatalogPermissionError,
    FineTypeCatalogUseCase,
    LeaveTypeCatalogUseCase,
    WorkModeCatalogUseCase,
)
from src.application.use_cases.daily_attendance import (
    DailyAttendanceSheetUseCase,
    SheetNotFoundError,
    SheetPermissionError,
)
from src.application.use_cases.position_management import (
    PositionManagementError,
    PositionManagementUseCase,
    PositionNotFoundError,
    RoleDraft,
)
from src.application.use_cases.root_control import RootControlError, RootControlUseCase
from src.application.use_cases.sales_points import (
    RedemptionNotFoundError,
    SalesPointsError,
    SalesPointsUseCase,
)
from src.application.use_cases.sales_review_queue import (
    QueueItemNotFoundError,
    ReviewQueueError,
    ReviewQueueItem,
    SalesReviewQueueUseCase,
)
from src.application.use_cases.sync_conflicts import (
    RESOLVE_CONFLICT_FLAG,
    ConflictItem,
    ConflictNotFoundError,
    ConflictResolutionError,
    Resolution,
    SyncConflictUseCase,
)
from src.domain.entities.attendance_sheet import AttendanceFact, AutoAttendanceStatus
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.entities.sales_points import PointsEntry
from src.domain.policies import FeatureModule
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.catalogs import FineType, LeaveType, WorkMode
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.gamification import RewardItem
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FineTypeId,
    LeaveTypeId,
    PointsEntryId,
    PositionId,
    RedemptionId,
    RewardId,
    SalesTransactionId,
    StoreId,
    TenantId,
    WorkModeId,
)
from src.domain.value_objects.money import Money
from tests.fixtures.fakes import (
    FakeAttendanceFacts,
    FakeClock,
    FakeFeatureToggles,
    InMemoryFaceExemptions,
    InMemorySheets,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
DAY = date(2026, 8, 10)
NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)

MANAGE_BACKUPS = PermissionFlag(code="can_manage_backups", category="SISTEM")
VIEW_REPORTS = PermissionFlag(code="can_view_employee_reports", category="HR")
#: Konflikt həlli qapısı (SEC-018) — ANTI-FRAUD işarəli YAZI flag-i.
#:
#: `is_anti_fraud=True` BURADA DA yazılır: `PermissionFlag(code=...)` sükutla
#: `False` işlədərdi və `position.grant()` `Mağaza_Meneceri`-yə icazə verərdi —
#: yəni test flag-in HƏQİQİ kataloq tərifindən (migrations/056) fərqli, daha
#: zəif bir nüsxəsini yoxlamış olardı.
RESOLVE_CONFLICTS = PermissionFlag(
    code=RESOLVE_CONFLICT_FLAG,
    category="ERP_INFRA",
    is_anti_fraud=True,
    excludes_camera_role=True,
)
FILL_ATTENDANCE = PermissionFlag(code="can_fill_daily_attendance", category="NOVBE")
MANAGE_POINTS = PermissionFlag(code="can_manage_sales_points", category="SATIS_MUKAFAT")
MANAGE_WORK_MODES = PermissionFlag(code="can_manage_work_modes", category="KATALOQ")
MANAGE_FINE_TYPES = PermissionFlag(code="can_manage_fine_types", category="KATALOQ")
MANAGE_LEAVE_TYPES = PermissionFlag(code="can_manage_leave_types", category="KATALOQ")
MANAGE_LIMITS = PermissionFlag(code="can_manage_system_limits", category="SISTEM")
MANAGE_PERMISSIONS = PermissionFlag(
    code="can_manage_permissions", category="ICAZE", hardlock=HardlockLevel.ROOT_ONLY
)
MANAGE_POSITIONS = PermissionFlag(
    code="can_manage_positions", category="ICAZE", hardlock=HardlockLevel.ROOT_CEO
)
EXPORT_REPORTS = PermissionFlag(code="can_export_reports", category="SISTEM")


def make_employee(
    role: SystemRole,
    *,
    flags: list[PermissionFlag],
    store_id: StoreId | None = STORE,
) -> Employee:
    """Rolun defolt pilləsi ilə işçi — flag-lər VƏZİFƏYƏ verilir."""
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for flag in flags:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=store_id,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


# --------------------------------------------------------------------------- #
# Ehtiyat nüsxə qapısı (`backup_access.py`)
# --------------------------------------------------------------------------- #


class _BackupRecordStub:
    """`BackupRecord`-un test üçün lazım olan hissəsi (frozen dataclass əvəzi).

    Real `BackupRecord` `infrastructure.backup.service`-dədir; use case ondan
    yalnız beş sahəni oxuyur. Sahtə həmin müqavilə ilə məhdudlaşır ki, test
    `pg_dump` qatına bağlanmasın.
    """

    def __init__(self, *, created_at: datetime, retention_until: date, size_bytes: int) -> None:
        self.storage_ref = "/nusxeler/2026-08-10.dump"
        self.size_bytes = size_bytes
        self.checksum = "sha256:abc"
        self.created_at = created_at
        self.retention_until = retention_until

    def is_expired(self, today: date) -> bool:
        return today > self.retention_until


class _BackupCatalog:
    def __init__(self, records: list[Any]) -> None:
        self.records = records

    def list_available(self, tenant_id: TenantId, *, limit: int = 60) -> list[Any]:
        return list(self.records)


class _BackupOperations:
    def __init__(self, *, restore_error: Exception | None = None) -> None:
        self.created: list[str] = []
        self.restored: list[tuple[str, str]] = []
        self._restore_error = restore_error

    def create(self, tenant_id: TenantId, *, backup_type: str = "MANUAL") -> Any:
        self.created.append(backup_type)
        return _BackupRecordStub(
            created_at=NOW, retention_until=date(2026, 9, 10), size_bytes=5 * 1024 * 1024
        )

    def restore(
        self, record: Any, *, target_dsn: str, confirmation: str, actor_id: Any = None
    ) -> None:
        if self._restore_error is not None:
            raise self._restore_error
        self.restored.append((target_dsn, confirmation))


def _backup_use_case(
    *, records: list[Any] | None = None, operations: _BackupOperations | None = None
) -> tuple[BackupAccessUseCase, _BackupOperations, RecordingAudit]:
    audit = RecordingAudit()
    ops = operations or _BackupOperations()
    use_case = BackupAccessUseCase(
        catalog=_BackupCatalog(records or []),  # type: ignore[arg-type]
        operations=ops,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, ops, audit


def test_restore_point_labels_cover_today_yesterday_and_older() -> None:
    """Etiket sərhədləri: 0 gün, 1 gün, N gün — üçü də AYRI mətn verir."""
    records = [
        _BackupRecordStub(created_at=NOW, retention_until=date(2026, 9, 1), size_bytes=1024 * 1024),
        _BackupRecordStub(
            created_at=NOW.replace(day=9), retention_until=date(2026, 9, 1), size_bytes=1024 * 1024
        ),
        _BackupRecordStub(
            created_at=NOW.replace(day=3), retention_until=date(2026, 8, 5), size_bytes=1024 * 1024
        ),
    ]
    use_case, _, _ = _backup_use_case(records=records)
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_BACKUPS])

    points = use_case.restore_points(tenant_id=TENANT, actor=root)

    assert [p.label_az for p in points] == ["Bu gün", "Dünən", "03.08.2026 (7 gün əvvəl)"]
    assert [p.is_expired for p in points] == [False, False, True], (
        "Saxlama müddəti keçmiş nüsxə ekranda AÇIQ işarələnməlidir"
    )


def test_restore_point_size_is_reported_in_megabytes() -> None:
    """Ekran bayt yox, MB göstərir — 3 MB-lıq nüsxə «3.0» olmalıdır."""
    use_case, _, _ = _backup_use_case(
        records=[
            _BackupRecordStub(
                created_at=NOW, retention_until=date(2026, 9, 1), size_bytes=3 * 1024 * 1024
            )
        ]
    )
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_BACKUPS])

    assert use_case.restore_points(tenant_id=TENANT, actor=root)[0].size_mb == 3.0


def test_manual_backup_requires_the_flag_and_creates_nothing_without_it() -> None:
    """Səlahiyyət yoxdursa `pg_dump` HEÇ VAXT başlamamalıdır."""
    use_case, operations, audit = _backup_use_case()
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[])

    with pytest.raises(BackupAccessError, match="can_manage_backups"):
        use_case.create_now(tenant_id=TENANT, actor=manager)

    assert operations.created == [], "Rədd edilən çağırışdan sonra nüsxə yaradılmamalıdır"
    assert audit.entries == []


def test_manual_backup_is_audited_with_the_checksum() -> None:
    """Nüsxənin bütövlüyü sonradan yoxlana bilsin deyə checksum audit-ə düşür."""
    use_case, operations, audit = _backup_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_BACKUPS])

    record = use_case.create_now(tenant_id=TENANT, actor=root)

    assert operations.created == ["MANUAL"], "Əl ilə nüsxənin tipi MANUAL olmalıdır"
    assert audit.actions() == ["BACKUP_CREATED_MANUALLY"]
    assert audit.entries[0]["after_state"]["checksum"] == record.checksum


def test_restore_masks_the_password_in_the_audit_trail() -> None:
    """DSN-dəki şifrə audit sətrində ASLA açıq yazılmır."""
    use_case, operations, audit = _backup_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_BACKUPS])
    record = _BackupRecordStub(created_at=NOW, retention_until=date(2026, 9, 1), size_bytes=1024)

    use_case.restore(
        tenant_id=TENANT,
        actor=root,
        record=record,  # type: ignore[arg-type]
        target_dsn="postgresql://kompas:GizliSifre123@db.local:5432/kompasos",
        confirmation="BƏRPA ET",
    )

    masked = audit.entries[0]["before_state"]["target_dsn_masked"]
    assert masked == "***@db.local:5432/kompasos"
    assert "GizliSifre123" not in str(audit.entries)
    assert operations.restored == [
        ("postgresql://kompas:GizliSifre123@db.local:5432/kompasos", "BƏRPA ET")
    ]


def test_dsn_without_credentials_is_left_untouched() -> None:
    """Şifrəsiz DSN maskalanmır — «***@» əlavə etmək izahı çətinləşdirərdi."""
    use_case, _, audit = _backup_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_BACKUPS])
    record = _BackupRecordStub(created_at=NOW, retention_until=date(2026, 9, 1), size_bytes=1)

    use_case.restore(
        tenant_id=TENANT,
        actor=root,
        record=record,  # type: ignore[arg-type]
        target_dsn="postgresql:///kompasos",
        confirmation="BƏRPA ET",
    )

    assert audit.entries[0]["before_state"]["target_dsn_masked"] == "postgresql:///kompasos"


def test_failed_restore_still_leaves_the_request_line_in_the_audit() -> None:
    """Uğursuz bərpa cəhdi də araşdırılası hadisədir — izi qalmalıdır."""
    operations = _BackupOperations(restore_error=RuntimeError("pg_restore çökdü"))
    use_case, _, audit = _backup_use_case(operations=operations)
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_BACKUPS])
    record = _BackupRecordStub(created_at=NOW, retention_until=date(2026, 9, 1), size_bytes=1)

    with pytest.raises(RuntimeError, match="pg_restore"):
        use_case.restore(
            tenant_id=TENANT,
            actor=root,
            record=record,  # type: ignore[arg-type]
            target_dsn="postgresql://u:p@h/db",
            confirmation="BƏRPA ET",
        )

    assert audit.actions() == ["BACKUP_RESTORE_REQUESTED"], (
        "«Kim basdı» sətri qalmalı, «tamamlandı» sətri isə YAZILMAMALIDIR"
    )


# --------------------------------------------------------------------------- #
# Sinxronizasiya konfliktləri (`sync_conflicts.py`)
# --------------------------------------------------------------------------- #


class _Conflicts:
    def __init__(self, items: list[ConflictItem]) -> None:
        self.items = items
        self.resolved: list[dict[str, Any]] = []
        self.applied: list[dict[str, Any]] = []

    def list_open(self, tenant_id: TenantId, *, limit: int = 100) -> list[ConflictItem]:
        return list(self.items)

    def get(self, conflict_id: Any) -> ConflictItem | None:
        return next((i for i in self.items if i.conflict_id == conflict_id), None)

    def open_count(self, tenant_id: TenantId) -> int:
        return len(self.items)

    def resolve(
        self,
        conflict_id: Any,
        *,
        resolution: Resolution,
        resolved_by: Any,
        resolved_at: datetime,
        note: str,
    ) -> bool:
        self.resolved.append(
            {
                "conflict_id": conflict_id,
                "resolution": resolution,
                "resolved_by": resolved_by,
                "resolved_at": resolved_at,
                "note": note,
            }
        )
        # `True` = konflikt SAHİBLƏNİLDİ (`resolved_at IS NULL` şərti tutdu).
        return True

    def apply_local_version(
        self, *, table_name: str, record_id: Any, local_version: dict[str, Any]
    ) -> int:
        self.applied.append(
            {"table_name": table_name, "record_id": record_id, "local_version": local_version}
        )
        return 1


def _conflict(table: str = "fines", **versions: dict[str, Any]) -> ConflictItem:
    return ConflictItem(
        conflict_id=uuid.uuid4(),
        table_name=table,
        record_id=uuid.uuid4(),
        local_version=versions.get("local", {"amount": "25.00", "status": "PUBLISHED"}),
        remote_version=versions.get("remote", {"amount": "50.00", "status": "PUBLISHED"}),
        detected_at=NOW,
    )


def _conflict_use_case(
    items: list[ConflictItem],
) -> tuple[SyncConflictUseCase, _Conflicts, RecordingAudit]:
    repository = _Conflicts(items)
    audit = RecordingAudit()
    use_case = SyncConflictUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, repository, audit


def test_conflict_badge_count_requires_the_flag() -> None:
    """Menyu nişanı da qorunur — sayğac özü də məlumat sızdırır."""
    use_case, _, _ = _conflict_use_case([_conflict()])
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(ConflictResolutionError, match=RESOLVE_CONFLICT_FLAG):
        use_case.open_count(tenant_id=TENANT, actor=seller)


def test_conflict_badge_count_is_read_from_the_repository() -> None:
    use_case, _, _ = _conflict_use_case([_conflict(), _conflict("tasks")])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[RESOLVE_CONFLICTS])

    assert use_case.open_count(tenant_id=TENANT, actor=hr) == 2


def test_resolution_keeps_both_versions_in_the_audit_before_state() -> None:
    """Bölmə 5: hər iki versiya SAXLANILIR — audit onların şahididir."""
    item = _conflict()
    use_case, repository, audit = _conflict_use_case([item])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[RESOLVE_CONFLICTS])

    resolved = use_case.resolve(
        tenant_id=TENANT,
        actor=hr,
        conflict_id=item.conflict_id,
        resolution=Resolution.KEPT_REMOTE,
        note="Buluddakı məbləğ kassa çekinə uyğundur",
    )

    assert resolved is item
    assert repository.resolved[0]["resolution"] is Resolution.KEPT_REMOTE
    assert repository.resolved[0]["resolved_by"] == hr.id
    assert repository.resolved[0]["resolved_at"] == NOW
    entry = audit.entries[0]
    assert entry["action"] == "SYNC_CONFLICT_RESOLVED"
    assert entry["before_state"] == {
        "local": item.local_version,
        "remote": item.remote_version,
        # Konflikt anında hədəf sətirdə UZAQ versiya durur — `KEPT_REMOTE`-un
        # boş əməliyyat olmasının səbəbi məhz budur.
        "standing": "REMOTE",
    }
    assert entry["after_state"] == {
        "resolution": "KEPT_REMOTE",
        "applied_version": "REMOTE",
        "target_table": "fines",
        "target_rows_written": 0,
        "manual_correction_required": False,
    }
    assert repository.applied == [], "`KEPT_REMOTE` hədəf sətrə TOXUNMUR"


def test_resolution_note_is_whitespace_normalised_before_storing() -> None:
    """Qeyd audit sətrinə düşür — sətir sonu və ikiqat boşluq təmizlənir."""
    item = _conflict()
    use_case, repository, audit = _conflict_use_case([item])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[RESOLVE_CONFLICTS])

    use_case.resolve(
        tenant_id=TENANT,
        actor=hr,
        conflict_id=item.conflict_id,
        resolution=Resolution.MERGED,
        note="  Məbləğ   yerlidən,\n status buluddan  ",
    )

    assert repository.resolved[0]["note"] == "Məbləğ yerlidən, status buluddan"
    assert audit.entries[0]["reason"] == "Məbləğ yerlidən, status buluddan"


def test_unknown_conflict_is_not_silently_ignored() -> None:
    """Yoxlama sırası: qeyd əvvəl, sonra mövcudluq — hər ikisi AÇIQ istisna."""
    use_case, repository, _ = _conflict_use_case([])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[RESOLVE_CONFLICTS])

    with pytest.raises(ConflictNotFoundError, match="tapılmadı"):
        use_case.resolve(
            tenant_id=TENANT,
            actor=hr,
            conflict_id=uuid.uuid4(),
            resolution=Resolution.KEPT_LOCAL,
            note="Yerli versiya doğrudur",
        )
    assert repository.resolved == []


def test_identical_versions_produce_no_differing_fields() -> None:
    """Sərhəd: iki eyni versiya — ekranda vurğulanacaq sahə YOXDUR."""
    same = {"amount": "25.00"}
    item = _conflict(local=same, remote=dict(same))

    assert item.differing_fields() == []


def test_a_field_present_on_only_one_side_counts_as_differing() -> None:
    """Yalnız bir tərəfdə olan sütun da fərqdir — `None` ilə müqayisə olunur."""
    item = _conflict(local={"amount": "25.00"}, remote={"amount": "25.00", "note": "x"})

    assert item.differing_fields() == ["note"]


def test_non_audit_critical_table_carries_no_warning_badge() -> None:
    assert _conflict("tasks").is_audit_critical is False
    assert _conflict("audit_logs").is_audit_critical is True


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [
        (Resolution.KEPT_LOCAL, "Mağazadakı versiya saxlanıldı"),
        (Resolution.KEPT_REMOTE, "Buluddakı versiya saxlanıldı"),
        (Resolution.MERGED, "Hər iki versiyadan birləşdirildi"),
    ],
)
def test_every_resolution_has_an_azerbaijani_label(resolution: Resolution, expected: str) -> None:
    """Bölmə 9: yeganə interfeys dili — etiketsiz variant qalmamalıdır."""
    assert resolution.label_az == expected


# --------------------------------------------------------------------------- #
# Şübhəli satış növbəsi (`sales_review_queue.py`)
# --------------------------------------------------------------------------- #


class _Queue:
    def __init__(self, items: list[ReviewQueueItem]) -> None:
        self.items = items
        self.assigned: list[dict[str, Any]] = []
        self.confirmed: list[Any] = []
        self.last_query: dict[str, Any] = {}

    def list_queue(
        self, tenant_id: TenantId, *, server_id: Any = None, limit: int = 200
    ) -> list[ReviewQueueItem]:
        self.last_query = {"server_id": server_id, "limit": limit}
        return list(self.items)

    def get(self, transaction_id: Any) -> ReviewQueueItem | None:
        return next((i for i in self.items if i.transaction_id == transaction_id), None)

    def queue_size(self, tenant_id: TenantId) -> int:
        return len(self.items)

    def assign(
        self,
        transaction_id: Any,
        *,
        employee_id: Any,
        store_id: Any,
        matched_by: Any,
        matched_at: datetime,
    ) -> None:
        self.assigned.append(
            {
                "transaction_id": transaction_id,
                "employee_id": employee_id,
                "store_id": store_id,
                "matched_by": matched_by,
                "matched_at": matched_at,
            }
        )

    def confirm(self, transaction_id: Any, *, matched_by: Any, matched_at: datetime) -> None:
        self.confirmed.append(transaction_id)


class _RecordingAdjuster:
    def __init__(self) -> None:
        self.transfers: list[dict[str, Any]] = []

    def transfer_for_transaction(self, **kwargs: Any) -> None:
        self.transfers.append(kwargs)


def _queue_item(
    *,
    suggested: EmployeeId | None,
    store_id: StoreId | None = STORE,
    amount: str = "450.00",
) -> ReviewQueueItem:
    return ReviewQueueItem(
        transaction_id=SalesTransactionId(uuid.uuid4()),
        server_name="Bellona — Bakı",
        one_c_seller_id="S-1",
        one_c_seller_name="Aysel Q.",
        one_c_store_code="ST-1",
        one_c_document_id="DOC-1",
        gross_amount=Money(Decimal(amount)),
        transaction_date=NOW,
        confidence=(
            MatchConfidence.LOW_CONFIDENCE_MATCH if suggested else MatchConfidence.UNASSIGNED
        ),
        match_reason="Ad oxşarlığı",
        suggested_employee_id=suggested,
        store_id=store_id,
    )


def _queue_use_case(
    items: list[ReviewQueueItem], *, points: _RecordingAdjuster | None = None
) -> tuple[SalesReviewQueueUseCase, _Queue, RecordingAudit]:
    repository = _Queue(items)
    audit = RecordingAudit()
    use_case = SalesReviewQueueUseCase(
        repository=repository,  # type: ignore[arg-type]
        points=points,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, repository, audit


def test_queue_size_badge_requires_the_points_flag() -> None:
    use_case, _, _ = _queue_use_case([_queue_item(suggested=None)])
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(ReviewQueueError, match="can_manage_sales_points"):
        use_case.queue_size(tenant_id=TENANT, actor=seller)


def test_queue_filter_is_passed_through_to_the_repository() -> None:
    """Faza 6.2 «per-server aware»: süzgəc repository-ə ÇATMALIDIR."""
    use_case, repository, _ = _queue_use_case([])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])
    server = uuid.uuid4()

    use_case.queue(tenant_id=TENANT, actor=hr, server_id=server, limit=7)

    assert repository.last_query == {"server_id": server, "limit": 7}


@pytest.mark.parametrize(
    ("suggested", "expected"),
    [(None, "Təyin olunmayıb"), ("present", "Şübhəli uyğunlaşma")],
)
def test_queue_badge_reflects_the_confidence(suggested: str | None, expected: str) -> None:
    item = _queue_item(suggested=EmployeeId(uuid.uuid4()) if suggested else None)

    assert item.badge_az == expected
    assert item.is_unassigned is (suggested is None)


@pytest.mark.parametrize("reason", ["", "   ", "qısa", "  a\n b "])
def test_reassignment_refuses_a_too_short_reason(reason: str) -> None:
    """Sərhəd: təmizlənmiş mətn 5 simvoldan qısadırsa yazı BAŞLAMIR."""
    item = _queue_item(suggested=EmployeeId(uuid.uuid4()))
    use_case, repository, _ = _queue_use_case([item])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])

    with pytest.raises(ReviewQueueError, match="minimum"):
        use_case.reassign(
            tenant_id=TENANT,
            actor=hr,
            transaction_id=item.transaction_id,
            employee_id=EmployeeId(uuid.uuid4()),
            reason=reason,
        )
    assert repository.assigned == [], "Səbəb qəbul edilməyibsə sətir toxunulmamalıdır"


def test_reassignment_moves_the_points_to_the_new_owner() -> None:
    previous = EmployeeId(uuid.uuid4())
    new_owner = EmployeeId(uuid.uuid4())
    item = _queue_item(suggested=previous)
    adjuster = _RecordingAdjuster()
    use_case, repository, audit = _queue_use_case([item], points=adjuster)
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])

    resolution = use_case.reassign(
        tenant_id=TENANT,
        actor=hr,
        transaction_id=item.transaction_id,
        employee_id=new_owner,
        reason="Sənəd başqa satıcının növbəsindədir",
    )

    assert resolution.points_transferred is True
    assert resolution.assigned_to == new_owner
    assert repository.assigned[0]["employee_id"] == new_owner
    assert adjuster.transfers[0]["from_employee_id"] == previous
    assert adjuster.transfers[0]["to_employee_id"] == new_owner
    assert adjuster.transfers[0]["gross_amount"] == Decimal("450.00")
    assert audit.entries[0]["after_state"]["points_transferred"] is True


def test_reassignment_to_the_same_employee_does_not_move_points_twice() -> None:
    """İdempotentlik: eyni işçiyə təkrar təyinat xalı İKİNCİ dəfə yazmır."""
    same = EmployeeId(uuid.uuid4())
    item = _queue_item(suggested=same)
    adjuster = _RecordingAdjuster()
    use_case, repository, _ = _queue_use_case([item], points=adjuster)
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])

    resolution = use_case.reassign(
        tenant_id=TENANT,
        actor=hr,
        transaction_id=item.transaction_id,
        employee_id=same,
        reason="Təxmin doğrudur, əl ilə təsdiqləyirəm",
    )

    assert adjuster.transfers == []
    assert resolution.points_transferred is False
    assert repository.assigned, "Uyğunlaşma yenə də MANUAL_MATCH olaraq yazılmalıdır"


def test_reassignment_without_a_points_module_still_assigns_the_row() -> None:
    """Xal modulu söndürülübsə də uyğunlaşma işləməlidir (`points=None`)."""
    item = _queue_item(suggested=EmployeeId(uuid.uuid4()))
    use_case, repository, audit = _queue_use_case([item], points=None)
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])

    resolution = use_case.reassign(
        tenant_id=TENANT,
        actor=hr,
        transaction_id=item.transaction_id,
        employee_id=EmployeeId(uuid.uuid4()),
        reason="Satıcı dəyişdirildi",
    )

    assert resolution.points_transferred is False
    assert len(repository.assigned) == 1
    assert audit.entries[0]["after_state"]["points_transferred"] is False


def test_a_row_without_a_store_transfers_no_points() -> None:
    """Sərhəd: `store_id is None` — xal sətri mağazasız yazıla bilməz."""
    item = _queue_item(suggested=EmployeeId(uuid.uuid4()), store_id=None)
    adjuster = _RecordingAdjuster()
    use_case, repository, _ = _queue_use_case([item], points=adjuster)
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])

    resolution = use_case.reassign(
        tenant_id=TENANT,
        actor=hr,
        transaction_id=item.transaction_id,
        employee_id=EmployeeId(uuid.uuid4()),
        reason="Mağaza kodu 1C-də boşdur",
    )

    assert adjuster.transfers == []
    assert resolution.points_transferred is False
    assert repository.assigned[0]["store_id"] is None


def test_reassigning_an_unknown_transaction_raises_not_found() -> None:
    use_case, repository, _ = _queue_use_case([])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])

    with pytest.raises(QueueItemNotFoundError, match="tapılmadı"):
        use_case.reassign(
            tenant_id=TENANT,
            actor=hr,
            transaction_id=SalesTransactionId(uuid.uuid4()),
            employee_id=EmployeeId(uuid.uuid4()),
            reason="Səhv sətir seçildi",
        )
    assert repository.assigned == []


def test_confirming_an_unknown_transaction_raises_not_found() -> None:
    use_case, repository, _ = _queue_use_case([])
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])

    with pytest.raises(QueueItemNotFoundError):
        use_case.confirm(
            tenant_id=TENANT, actor=hr, transaction_id=SalesTransactionId(uuid.uuid4())
        )
    assert repository.confirmed == []


# --------------------------------------------------------------------------- #
# Kataloq idarəetməsi (`catalog_management.py`)
# --------------------------------------------------------------------------- #


class _Catalog:
    def __init__(self, entries: list[Any] | None = None) -> None:
        self.entries = entries or []
        self.saved: list[Any] = []
        self.deactivated: list[Any] = []
        self._by_id: dict[Any, Any] = {}

    def register(self, entry_id: Any, entry: Any) -> None:
        self._by_id[entry_id] = entry

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        if include_inactive:
            return list(self.entries)
        return [entry for entry in self.entries if entry.is_active]

    def get(self, entry_id: Any) -> Any:
        return self._by_id.get(entry_id)

    def save(self, tenant_id: TenantId, entry: Any, *, changed_by: EmployeeId) -> None:
        self.saved.append(entry)

    def deactivate(self, tenant_id: TenantId, entry_id: Any, *, changed_by: EmployeeId) -> None:
        self.deactivated.append(entry_id)


def test_leave_type_management_list_needs_its_own_flag() -> None:
    """Üç kataloq, üç flag — «biri var, deməli hamısı var» fərziyyəsi yoxdur."""
    use_case = LeaveTypeCatalogUseCase(
        repository=_Catalog(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    ceo = make_employee(SystemRole.CEO, flags=[MANAGE_WORK_MODES, MANAGE_FINE_TYPES])

    with pytest.raises(CatalogPermissionError, match="can_manage_leave_types"):
        use_case.list_for_management(TENANT, ceo)


def test_leave_type_selection_list_is_open_to_every_employee() -> None:
    """STEP 1 `[İcazə İstəyirəm]` — satıcının kataloq flag-i YOXDUR."""
    active = LeaveType(name="Nahar", tenant_id=TENANT)
    inactive = LeaveType(name="Köhnə", tenant_id=TENANT, is_active=False, deactivated_at=NOW)
    use_case = LeaveTypeCatalogUseCase(
        repository=_Catalog([active, inactive]),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )

    assert use_case.list_for_selection(TENANT) == [active]


def test_leave_type_save_records_the_default_duration_in_the_audit() -> None:
    """Defolt müddət cərimə hesablamasına təsir edir — audit onu saxlamalıdır."""
    repository = _Catalog()
    audit = RecordingAudit()
    use_case = LeaveTypeCatalogUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_LEAVE_TYPES])

    change = use_case.save(
        TENANT, hr, LeaveType(name="Nahar Fasiləsi", tenant_id=TENANT, default_duration_minutes=45)
    )

    assert change == CatalogChange(entry_name="Nahar Fasiləsi", action="saved")
    assert repository.saved and repository.saved[0].name == "Nahar Fasiləsi"
    assert audit.entries[0]["after_state"]["default_duration_minutes"] == 45


def test_leave_type_deactivation_is_audited_not_deleted() -> None:
    repository = _Catalog()
    audit = RecordingAudit()
    use_case = LeaveTypeCatalogUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    hr = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_LEAVE_TYPES])
    leave_type_id = LeaveTypeId(uuid.uuid4())

    change = use_case.deactivate(TENANT, hr, leave_type_id)

    assert repository.deactivated == [leave_type_id]
    assert change.action == "deactivated"
    assert audit.entries[0]["action"] == "LEAVE_TYPE_DEACTIVATED"
    assert audit.entries[0]["after_state"] == {"is_active": False}


def test_work_mode_deactivation_falls_back_to_the_id_when_the_row_is_gone() -> None:
    """Sətir artıq yoxdursa audit ADI itirmir — ən azı ID yazılır."""
    repository = _Catalog()
    audit = RecordingAudit()
    use_case = WorkModeCatalogUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_WORK_MODES])
    work_mode_id = WorkModeId(uuid.uuid4())

    change = use_case.deactivate(TENANT, root, work_mode_id)

    assert change.entry_name == str(work_mode_id)
    assert audit.entries[0]["before_state"] == {"name": str(work_mode_id), "is_active": True}


def test_work_mode_deactivation_keeps_the_known_name() -> None:
    repository = _Catalog()
    work_mode_id = WorkModeId(uuid.uuid4())
    repository.register(work_mode_id, WorkMode(name="Səhər növbəsi", tenant_id=TENANT))
    audit = RecordingAudit()
    use_case = WorkModeCatalogUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_WORK_MODES])

    change = use_case.deactivate(TENANT, root, work_mode_id)

    assert change.entry_name == "Səhər növbəsi"
    assert audit.entries[0]["after_state"] == {"name": "Səhər növbəsi", "is_active": False}


def test_new_fine_type_records_no_previous_price() -> None:
    """Sərhəd: `fine_type_id is None` — «əvvəlki qiymət» mövcud DEYİL."""
    repository = _Catalog()
    audit = RecordingAudit()
    use_case = FineTypeCatalogUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_FINE_TYPES])

    use_case.save(
        TENANT,
        root,
        FineType(name="Gecikmə", tenant_id=TENANT, standard_amount=Money(Decimal("50.00"))),
    )

    assert audit.entries[0]["before_state"] is None
    assert audit.entries[0]["after_state"]["standard_amount"] == "50.00"


def test_fine_type_deactivation_explains_itself_in_the_audit_reason() -> None:
    """Səbəb sahəsi mübahisədə «niyə seçilə bilmir» sualını cavablandırır."""
    repository = _Catalog()
    fine_type_id = FineTypeId(uuid.uuid4())
    repository.register(
        fine_type_id,
        FineType(name="Köhnə qayda", tenant_id=TENANT, standard_amount=Money(Decimal("10.00"))),
    )
    audit = RecordingAudit()
    use_case = FineTypeCatalogUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_FINE_TYPES])

    use_case.deactivate(TENANT, root, fine_type_id)

    assert repository.deactivated == [fine_type_id]
    assert "tarixi qeydlər dəyişmir" in audit.entries[0]["reason"]


def test_fine_type_selection_list_is_open_to_the_camera_operator() -> None:
    """Operator qiyməti təyin etmir, SEÇİR — yoxlama ekranı boş qoyardı."""
    active = FineType(name="Gecikmə", tenant_id=TENANT, standard_amount=Money(Decimal("50.00")))
    inactive = FineType(
        name="Köhnə",
        tenant_id=TENANT,
        is_active=False,
        deactivated_at=NOW,
        standard_amount=Money(Decimal("10.00")),
    )
    use_case = FineTypeCatalogUseCase(
        repository=_Catalog([active, inactive]),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )

    assert use_case.list_for_selection(TENANT) == [active]


# --------------------------------------------------------------------------- #
# Gündəlik tabel (`daily_attendance.py`)
# --------------------------------------------------------------------------- #


class _SheetCtx:
    def __init__(self, facts: list[AttendanceFact] | None = None) -> None:
        self.clock = FakeClock(NOW)
        self.sheets = InMemorySheets()
        self.facts = FakeAttendanceFacts(facts)
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()

    def use_case(self) -> DailyAttendanceSheetUseCase:
        return DailyAttendanceSheetUseCase(
            sheets=self.sheets,  # type: ignore[arg-type]
            facts=self.facts,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )


def test_pending_sheet_list_is_refused_without_either_flag() -> None:
    ctx = _SheetCtx()
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(SheetPermissionError, match="səlahiyyət yoxdur"):
        ctx.use_case().pending_sheets(tenant_id=TENANT, actor=seller)


def test_pending_sheet_list_is_open_to_the_store_manager_too() -> None:
    """HR nəzarəti üçündür, lakin menecer də öz gecikmiş tabelini görməlidir."""
    ctx = _SheetCtx(facts=[AttendanceFact(employee_id=EmployeeId(uuid.uuid4()), planned_off=True)])
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL_ATTENDANCE])
    use_case = ctx.use_case()
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)

    pending = use_case.pending_sheets(tenant_id=TENANT, actor=manager)

    assert [sheet.sheet_date for sheet in pending] == [DAY]


def test_annotation_is_saved_and_audited_with_the_note_as_reason() -> None:
    """Qeyd audit sətrinin `reason` sahəsinə düşür — sonradan izah edilə bilsin."""
    worker = EmployeeId(uuid.uuid4())
    ctx = _SheetCtx(facts=[AttendanceFact(employee_id=worker, planned_off=False, day_is_over=True)])
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL_ATTENDANCE])
    use_case = ctx.use_case()
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)

    view = use_case.annotate_line(
        tenant_id=TENANT,
        actor=manager,
        store_id=STORE,
        sheet_date=DAY,
        employee_id=worker,
        note="PIN sistemi işləmirdi, şifahi təsdiq",
    )

    assert view.is_editable is True
    assert view.sheet.lines[0].manager_note == "PIN sistemi işləmirdi, şifahi təsdiq"
    entry = ctx.audit.entries[0]
    assert entry["action"] == "ATTENDANCE_SHEET_ANNOTATED"
    assert entry["reason"] == "PIN sistemi işləmirdi, şifahi təsdiq"
    assert entry["after_state"]["sheet_date"] == DAY.isoformat()


def test_annotating_a_sheet_that_was_never_opened_raises_not_found() -> None:
    ctx = _SheetCtx()
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL_ATTENDANCE])

    with pytest.raises(SheetNotFoundError, match="açılmayıb"):
        ctx.use_case().annotate_line(
            tenant_id=TENANT,
            actor=manager,
            store_id=STORE,
            sheet_date=DAY,
            employee_id=EmployeeId(uuid.uuid4()),
            note="Qeyd",
        )


def test_manager_note_is_stored_on_confirmation() -> None:
    worker = EmployeeId(uuid.uuid4())
    ctx = _SheetCtx(
        facts=[AttendanceFact(employee_id=worker, planned_off=False, has_verified_check_in=True)]
    )
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL_ATTENDANCE])
    use_case = ctx.use_case()
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)

    view = use_case.confirm(
        tenant_id=TENANT,
        actor=manager,
        store_id=STORE,
        sheet_date=DAY,
        manager_note="Gün problemsiz keçdi",
    )

    assert view.sheet.manager_note == "Gün problemsiz keçdi"
    assert view.is_editable is False
    assert ctx.audit.entries[-1]["reason"] == "Gün problemsiz keçdi"
    assert ctx.notifier.messages == [], "Uyğunsuzluq yoxdursa HR-a bildiriş getməməlidir"


def test_confirmed_sheet_is_not_refilled_when_reopened() -> None:
    """Təsdiqdən sonra açılış YALNIZ oxuyur — yenidən doldurma sətri pozardı."""
    worker = EmployeeId(uuid.uuid4())
    ctx = _SheetCtx(
        facts=[AttendanceFact(employee_id=worker, planned_off=False, has_verified_check_in=True)]
    )
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL_ATTENDANCE])
    use_case = ctx.use_case()
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)
    use_case.confirm(tenant_id=TENANT, actor=manager, store_id=STORE, sheet_date=DAY)

    ctx.facts.facts = [AttendanceFact(employee_id=EmployeeId(uuid.uuid4()), planned_off=False)]
    view = use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)

    assert len(view.sheet.lines) == 1, "Təsdiqlənmiş tabel yeni faktlarla dəyişməməlidir"
    assert view.is_editable is False


def test_worked_days_counts_only_statuses_that_mean_work() -> None:
    """Hesabat sərhədi: OFF_DAY və ABSENT sayılmır, VERIFIED/LATE sayılır."""
    present = EmployeeId(uuid.uuid4())
    absent = EmployeeId(uuid.uuid4())
    ctx = _SheetCtx(
        facts=[
            AttendanceFact(employee_id=present, planned_off=False, has_verified_check_in=True),
            AttendanceFact(employee_id=absent, planned_off=False, day_is_over=True),
        ]
    )
    manager = make_employee(SystemRole.STORE_MANAGER, flags=[FILL_ATTENDANCE])
    use_case = ctx.use_case()
    use_case.open_sheet(tenant_id=TENANT, actor=manager, store_id=STORE)

    totals = use_case.worked_days_in_period(tenant_id=TENANT, store_id=STORE, start=DAY, end=DAY)

    assert totals == {present: 1}
    assert AutoAttendanceStatus.ABSENT.counts_as_worked is False


def test_worked_days_over_an_empty_period_returns_nothing() -> None:
    """Sərhəd: heç bir tabel açılmayıbsa nəticə BOŞ lüğətdir, istisna deyil."""
    ctx = _SheetCtx()

    totals = ctx.use_case().worked_days_in_period(
        tenant_id=TENANT, store_id=STORE, start=DAY, end=date(2026, 8, 13)
    )

    assert totals == {}


# --------------------------------------------------------------------------- #
# Rol idarəetməsi (`position_management.py`)
# --------------------------------------------------------------------------- #


class _Positions:
    def __init__(self) -> None:
        self.items: dict[Any, Position] = {}

    def get(self, position_id: Any) -> Position | None:
        return self.items.get(position_id)

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        return next((p for p in self.items.values() if p.code == code), None)

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        return list(self.items.values())

    def save(self, position: Position) -> None:
        self.items[position.id] = position


class _Flags:
    def __init__(self, flags: dict[str, PermissionFlag]) -> None:
        self._flags = flags

    def get(self, code: str) -> PermissionFlag | None:
        return self._flags.get(code)

    def list_all(self) -> list[PermissionFlag]:
        return list(self._flags.values())

    def create(self, flag: PermissionFlag, *, created_by: EmployeeId) -> None:
        self._flags[flag.code] = flag


def _role_use_case() -> tuple[PositionManagementUseCase, _Positions, RecordingAudit]:
    positions = _Positions()
    audit = RecordingAudit()
    use_case = PositionManagementUseCase(
        positions=positions,  # type: ignore[arg-type]
        flags=_Flags(
            {
                EXPORT_REPORTS.code: EXPORT_REPORTS,
                MANAGE_POSITIONS.code: MANAGE_POSITIONS,
            }
        ),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, positions, audit


def _custom_role(use_case: PositionManagementUseCase, actor: Employee) -> Position:
    return use_case.create_role(
        tenant_id=TENANT,
        actor=actor,
        draft=RoleDraft(
            code="BAS_SATICI",
            name_az="Baş Satıcı",
            priority=RolePriority.OPERATIONAL,
            flag_codes=(EXPORT_REPORTS.code,),
        ),
    )


def test_system_role_cannot_be_renamed() -> None:
    """`positions.code` audit sətirlərinə istinaddır — sistem rolu toxunulmaz."""
    use_case, positions, audit = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])
    system = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.HR_ADMIN.value,
        name_az="HR Admin",
        priority=RolePriority.ADMIN,
        tenant_id=TENANT,
        is_system=True,
    )
    positions.save(system)

    with pytest.raises(PositionManagementError, match="adlandırıla bilməz"):
        use_case.rename_role(
            tenant_id=TENANT, actor=root, position_id=system.id, name_az="Kadrlar Şöbəsi"
        )
    assert audit.actions() == []


def test_custom_role_rename_keeps_the_code_and_is_audited() -> None:
    use_case, _, audit = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])
    role = _custom_role(use_case, root)

    renamed = use_case.rename_role(
        tenant_id=TENANT, actor=root, position_id=role.id, name_az="  Böyük   Satıcı  "
    )

    assert renamed.code == "BAS_SATICI", "Kod DƏYİŞMİR — istinadlar qırılardı"
    assert renamed.name_az == "Böyük Satıcı"
    rename_entry = next(e for e in audit.entries if e["action"] == "POSITION_RENAMED")
    assert rename_entry["before_state"] == {"name_az": "Baş Satıcı"}
    assert rename_entry["after_state"] == {"name_az": "Böyük Satıcı"}


@pytest.mark.parametrize("name", ["", "  ", "a", " b "])
def test_role_name_shorter_than_the_minimum_is_refused(name: str) -> None:
    use_case, _, _ = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])
    role = _custom_role(use_case, root)

    with pytest.raises(PositionManagementError, match="minimum"):
        use_case.rename_role(tenant_id=TENANT, actor=root, position_id=role.id, name_az=name)


def test_role_name_longer_than_the_maximum_is_refused() -> None:
    use_case, _, _ = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])
    role = _custom_role(use_case, root)

    with pytest.raises(PositionManagementError, match="maksimum"):
        use_case.rename_role(tenant_id=TENANT, actor=root, position_id=role.id, name_az="A" * 200)


def test_empty_role_code_is_refused_at_creation() -> None:
    """Sərhəd: yalnız boşluqdan ibarət kod — rol kodsuz yaradıla bilməz."""
    use_case, positions, _ = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])

    with pytest.raises(PositionManagementError, match="boş ola bilməz"):
        use_case.create_role(
            tenant_id=TENANT,
            actor=root,
            draft=RoleDraft(code="   ", name_az="Ad", priority=RolePriority.OPERATIONAL),
        )
    assert positions.items == {}


def test_deactivating_a_custom_role_is_audited_with_its_code() -> None:
    use_case, positions, audit = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])
    role = _custom_role(use_case, root)

    deactivated = use_case.deactivate_role(tenant_id=TENANT, actor=root, position_id=role.id)

    assert deactivated.is_active is False
    assert positions.items[role.id].is_active is False
    entry = next(e for e in audit.entries if e["action"] == "POSITION_DEACTIVATED")
    assert entry["after_state"] == {"is_active": False, "code": "BAS_SATICI"}


def test_operations_on_an_unknown_role_raise_not_found() -> None:
    use_case, _, _ = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])
    missing = PositionId(uuid.uuid4())

    with pytest.raises(PositionNotFoundError, match="Rol tapılmadı"):
        use_case.deactivate_role(tenant_id=TENANT, actor=root, position_id=missing)
    with pytest.raises(PositionNotFoundError):
        use_case.rename_role(tenant_id=TENANT, actor=root, position_id=missing, name_az="Yeni ad")


def test_rename_requires_the_position_flag() -> None:
    use_case, positions, _ = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS, EXPORT_REPORTS])
    role = _custom_role(use_case, root)
    hr = make_employee(SystemRole.HR_ADMIN, flags=[EXPORT_REPORTS])

    with pytest.raises(Exception, match="can_manage_positions"):
        use_case.rename_role(tenant_id=TENANT, actor=hr, position_id=role.id, name_az="Başqa ad")
    assert positions.items[role.id].name_az == "Baş Satıcı"


# --------------------------------------------------------------------------- #
# ROOT idarə mərkəzi (`root_control.py`)
# --------------------------------------------------------------------------- #


class _Limits:
    def __init__(self, stored: dict[str, str] | None = None) -> None:
        self.stored = stored or {}

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return int(self.stored.get(key, default))

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self.stored.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self.stored)

    def set_value(
        self, tenant_id: TenantId, key: str, value: str, *, changed_by: EmployeeId
    ) -> None:
        self.stored[key] = value


class _Toggles:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.changes: list[dict[str, Any]] = []

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        row = next((r for r in self.rows if r["module_key"] == module_key), None)
        return True if row is None else bool(row["is_enabled"])

    def is_structural(self, tenant_id: TenantId, module_key: str) -> bool:
        row = next((r for r in self.rows if r["module_key"] == module_key), None)
        return False if row is None else bool(row.get("is_structural", False))

    def describe(self, tenant_id: TenantId) -> list[dict[str, Any]]:
        return list(self.rows)

    def set_enabled(
        self,
        tenant_id: TenantId,
        module_key: str,
        *,
        enabled: bool,
        changed_by: EmployeeId,
        confirmation: str | None = None,
    ) -> None:
        self.changes.append(
            {"module_key": module_key, "enabled": enabled, "confirmation": confirmation}
        )


def _root_use_case(
    *, toggles: _Toggles | None = None, flags: dict[str, PermissionFlag] | None = None
) -> tuple[RootControlUseCase, RecordingAudit]:
    audit = RecordingAudit()
    use_case = RootControlUseCase(
        limits=_Limits(),  # type: ignore[arg-type]
        toggles=toggles or _Toggles(),  # type: ignore[arg-type]
        flags=_Flags(flags or {}),  # type: ignore[arg-type]
        # SEC-020 — bu faylın ssenarilərində aktiv üz-təsdiqi istisnası yoxdur,
        # yəni kompensasiya kilidi işə düşmür və davranış DƏYİŞMİR.
        face_exemptions=InMemoryFaceExemptions([]),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, audit


def test_module_without_a_stored_row_is_reported_as_enabled() -> None:
    """FAIL-SAFE: konfiqurasiya sətrinin olmaması sistemi SÖNDÜRMÜR."""
    use_case, _ = _root_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_LIMITS])

    views = use_case.list_modules(tenant_id=TENANT, actor=root)

    assert {view.module_key for view in views} == {module.value for module in FeatureModule}
    assert all(view.is_enabled for view in views)
    assert all(view.description_az == "Defolt: açıq (bazada yazılmayıb)" for view in views)


def test_stored_row_overrides_the_default_module_state() -> None:
    toggles = _Toggles(
        [
            {
                "module_key": FeatureModule.SALES_POINTS.value,
                "is_enabled": False,
                "is_structural": False,
                "description_az": "Müştəri istəyi ilə söndürülüb",
            }
        ]
    )
    use_case, _ = _root_use_case(toggles=toggles)
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_LIMITS])

    view = next(
        v
        for v in use_case.list_modules(tenant_id=TENANT, actor=root)
        if v.module_key == FeatureModule.SALES_POINTS.value
    )

    assert view.is_enabled is False
    assert view.description_az == "Müştəri istəyi ilə söndürülüb"


def test_an_unknown_stored_module_is_still_listed() -> None:
    """Kataloqda olmayan açar GİZLƏNMİR — plugin-in qoyduğu sətir də görünür."""
    toggles = _Toggles(
        [{"module_key": "PLUGIN_XYZ", "is_enabled": False, "description_az": "Plagin"}]
    )
    use_case, _ = _root_use_case(toggles=toggles)
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_LIMITS])

    views = use_case.list_modules(tenant_id=TENANT, actor=root)
    extra = next(v for v in views if v.module_key == "PLUGIN_XYZ")

    assert extra.is_enabled is False
    assert extra.is_structural is False


def test_module_list_requires_the_limits_flag() -> None:
    use_case, _ = _root_use_case()
    hr = make_employee(SystemRole.HR_ADMIN, flags=[VIEW_REPORTS])

    with pytest.raises(RootControlError, match="can_manage_system_limits"):
        use_case.list_modules(tenant_id=TENANT, actor=hr)


def test_flag_catalog_requires_the_permission_flag() -> None:
    use_case, _ = _root_use_case()
    ceo = make_employee(SystemRole.CEO, flags=[MANAGE_LIMITS])

    with pytest.raises(RootControlError, match="can_manage_permissions"):
        use_case.list_flags(actor=ceo)


def test_flag_catalog_is_returned_for_an_authorised_actor() -> None:
    use_case, _ = _root_use_case(flags={EXPORT_REPORTS.code: EXPORT_REPORTS})
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_PERMISSIONS])

    assert [flag.code for flag in use_case.list_flags(actor=root)] == [EXPORT_REPORTS.code]


def test_non_structural_module_needs_no_confirmation() -> None:
    toggles = _Toggles([{"module_key": "TASK_ENGINE", "is_enabled": True, "is_structural": False}])
    use_case, audit = _root_use_case(toggles=toggles)
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_LIMITS])

    view = use_case.set_module_enabled(
        tenant_id=TENANT, actor=root, module_key="TASK_ENGINE", enabled=False
    )

    assert view.is_enabled is False
    assert toggles.changes[0]["confirmation"] is None
    assert audit.entries[0]["before_state"] == {"is_enabled": True}


# --------------------------------------------------------------------------- #
# Satış xalları (`sales_points.py`)
# --------------------------------------------------------------------------- #


class _PointsRepo:
    def __init__(self, entries: list[PointsEntry] | None = None) -> None:
        self.entries = {entry.id: entry for entry in (entries or [])}
        self.saved: list[PointsEntry] = []

    def get(self, entry_id: PointsEntryId) -> PointsEntry | None:
        return self.entries.get(entry_id)

    def list_for_employee(self, employee_id: EmployeeId, *, period: Any) -> list[PointsEntry]:
        return [e for e in self.entries.values() if e.employee_id == employee_id]

    def list_disputes(self, tenant_id: TenantId) -> list[PointsEntry]:
        return [e for e in self.entries.values() if e.has_open_dispute]

    def save(self, entry: PointsEntry) -> None:
        self.entries[entry.id] = entry
        self.saved.append(entry)


class _RewardRepo:
    def __init__(self, rewards: dict[RewardId, RewardItem] | None = None) -> None:
        self.rewards = rewards or {}
        self.redemptions: dict[RedemptionId, Any] = {}

    def list_rewards(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[tuple[RewardId, RewardItem]]:
        return [
            (rid, item) for rid, item in self.rewards.items() if include_inactive or item.is_active
        ]

    def get_reward(self, reward_id: RewardId) -> RewardItem | None:
        return self.rewards.get(reward_id)

    def save_reward(self, tenant_id: TenantId, reward_id: RewardId, reward: RewardItem) -> None:
        self.rewards[reward_id] = reward

    def list_redemptions(self, tenant_id: TenantId, *, pending_only: bool = False) -> list[Any]:
        return list(self.redemptions.values())

    def get_redemption(self, redemption_id: RedemptionId) -> Any:
        return self.redemptions.get(redemption_id)

    def save_redemption(self, redemption: Any) -> None:
        self.redemptions[redemption.id] = redemption


class _FailingNotifier:
    """Bildiriş kanalı çökür — əsas əməliyyat GERİ QAYTARILMAMALIDIR."""

    def __init__(self) -> None:
        self.attempts = 0

    def notify(self, **kwargs: Any) -> None:
        self.attempts += 1
        raise RuntimeError("SMTP əlçatmazdır")


def _points_entry(
    *,
    employee: EmployeeId,
    points: int = 40,
    transaction_id: SalesTransactionId | None = None,
) -> PointsEntry:
    return PointsEntry(
        entry_id=PointsEntryId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=employee,
        store_id=STORE,
        points=points,
        awarded_at=NOW,
        sales_transaction_id=transaction_id,
        gross_amount=Money(Decimal("400.00")) if transaction_id else None,
    )


def _points_use_case(
    *,
    points: _PointsRepo,
    rewards: _RewardRepo,
    audit: RecordingAudit | None = None,
    notifier: Any = None,
    toggles: FakeFeatureToggles | None = None,
) -> SalesPointsUseCase:
    return SalesPointsUseCase(
        points=points,  # type: ignore[arg-type]
        rewards=rewards,  # type: ignore[arg-type]
        audit=audit or RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        notifier=notifier or RecordingNotifier(),  # type: ignore[arg-type]
        toggles=toggles,  # type: ignore[arg-type]
    )


def test_held_points_are_capped_at_the_earned_total() -> None:
    """Kataloq qiyməti qalxsa balans MƏNFİ görünməməlidir (sərhəd hadisəsi)."""
    worker = make_employee(SystemRole.SELLER, flags=[])
    reward_id = RewardId(uuid.uuid4())
    rewards = _RewardRepo({reward_id: RewardItem(name="Kupon", cost_points=100)})
    points = _PointsRepo([_points_entry(employee=worker.id, points=100)])
    use_case = _points_use_case(points=points, rewards=rewards)
    use_case.request_reward(
        tenant_id=TENANT,
        actor=worker,
        reward_id=reward_id,
        redemption_id=RedemptionId(uuid.uuid4()),
    )
    # Kataloq qiyməti mübadilədən SONRA qalxır.
    rewards.rewards[reward_id] = RewardItem(name="Kupon", cost_points=400)

    balance = use_case.balance_for(worker.id, tenant_id=TENANT)

    assert balance.held == balance.earned == 100
    assert balance.available == 0, "Balans mənfi göstərilməməlidir"


def test_requesting_an_unknown_reward_raises_not_found() -> None:
    worker = make_employee(SystemRole.SELLER, flags=[])
    rewards = _RewardRepo()
    use_case = _points_use_case(points=_PointsRepo(), rewards=rewards)

    with pytest.raises(RedemptionNotFoundError, match="Mükafat tapılmadı"):
        use_case.request_reward(
            tenant_id=TENANT,
            actor=worker,
            reward_id=RewardId(uuid.uuid4()),
            redemption_id=RedemptionId(uuid.uuid4()),
        )
    assert rewards.redemptions == {}


def test_pending_reward_inbox_requires_the_points_flag() -> None:
    worker = make_employee(SystemRole.SELLER, flags=[])
    use_case = _points_use_case(points=_PointsRepo(), rewards=_RewardRepo())

    with pytest.raises(SalesPointsError, match="can_manage_sales_points"):
        use_case.list_pending_rewards(tenant_id=TENANT, actor=worker)


def test_deciding_an_unknown_redemption_raises_not_found() -> None:
    manager = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])
    use_case = _points_use_case(points=_PointsRepo(), rewards=_RewardRepo())

    with pytest.raises(RedemptionNotFoundError, match="Mükafat sorğusu tapılmadı"):
        use_case.decide_reward(
            tenant_id=TENANT,
            actor=manager,
            redemption_id=RedemptionId(uuid.uuid4()),
            approve=True,
        )


def test_reward_rejection_is_audited_and_the_owner_is_notified() -> None:
    worker = make_employee(SystemRole.SELLER, flags=[])
    manager = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])
    reward_id = RewardId(uuid.uuid4())
    rewards = _RewardRepo({reward_id: RewardItem(name="Kupon", cost_points=50)})
    points = _PointsRepo([_points_entry(employee=worker.id, points=200)])
    notifier = RecordingNotifier()
    audit = RecordingAudit()
    use_case = _points_use_case(points=points, rewards=rewards, audit=audit, notifier=notifier)
    redemption_id = RedemptionId(uuid.uuid4())
    use_case.request_reward(
        tenant_id=TENANT, actor=worker, reward_id=reward_id, redemption_id=redemption_id
    )

    decided = use_case.decide_reward(
        tenant_id=TENANT,
        actor=manager,
        redemption_id=redemption_id,
        approve=False,
        reason="Anbarda qalmayıb",
    )

    assert decided.status.value == "REJECTED"
    assert "REWARD_REJECTED" in audit.actions()
    assert notifier.messages[-1]["recipient_id"] == worker.id


def test_a_failing_notifier_never_undoes_the_reward_decision() -> None:
    """Bildiriş XƏBƏRDARLIQDIR — audit kimi məcburi deyil (modul başlığı)."""
    worker = make_employee(SystemRole.SELLER, flags=[])
    manager = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_POINTS])
    reward_id = RewardId(uuid.uuid4())
    rewards = _RewardRepo({reward_id: RewardItem(name="Kupon", cost_points=50)})
    points = _PointsRepo([_points_entry(employee=worker.id, points=200)])
    notifier = _FailingNotifier()
    use_case = _points_use_case(points=points, rewards=rewards, notifier=notifier)
    redemption_id = RedemptionId(uuid.uuid4())
    use_case.request_reward(
        tenant_id=TENANT, actor=worker, reward_id=reward_id, redemption_id=redemption_id
    )

    decided = use_case.decide_reward(
        tenant_id=TENANT, actor=manager, redemption_id=redemption_id, approve=True
    )

    assert notifier.attempts == 1
    assert decided.status.value == "APPROVED", "Qərar bildiriş xətasından ASILI DEYİL"


def test_unassigned_sale_awards_nothing() -> None:
    """`UNASSIGNED` xal qazandırmır — ledger boş sətirlə dolmamalıdır."""
    points = _PointsRepo()
    use_case = _points_use_case(points=points, rewards=_RewardRepo())

    result = use_case.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId(uuid.uuid4()),
        gross_amount=Decimal("900.00"),
        confidence=MatchConfidence.UNASSIGNED,
    )

    assert result is None
    assert points.saved == []


def test_award_is_skipped_when_the_points_module_is_disabled() -> None:
    """Retroaktiv-təsirsizlik: YENİ xal yazılmır, köhnələr toxunulmur."""
    points = _PointsRepo()
    toggles = FakeFeatureToggles({FeatureModule.SALES_POINTS.value})
    use_case = _points_use_case(points=points, rewards=_RewardRepo(), toggles=toggles)

    result = use_case.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId(uuid.uuid4()),
        gross_amount=Decimal("900.00"),
    )

    assert result is None
    assert points.saved == []


@pytest.mark.parametrize("amount", ["0.00", "99.99", "-500.00"])
def test_a_sale_below_one_point_writes_no_ledger_row(amount: str) -> None:
    """Sərhəd: sıfır, bir xaldan az və MƏNFİ məbləğ — heç biri sətir yaratmır."""
    points = _PointsRepo()
    use_case = _points_use_case(points=points, rewards=_RewardRepo())

    result = use_case.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId(uuid.uuid4()),
        gross_amount=Decimal(amount),
    )

    assert result is None
    assert points.saved == []


def test_a_custom_currency_rate_changes_the_awarded_points() -> None:
    """BR: xal dərəcəsi konfiqurasiya olunur — 500 AZN / 50 = 10 xal."""
    points = _PointsRepo()
    use_case = _points_use_case(points=points, rewards=_RewardRepo())

    entry = use_case.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId(uuid.uuid4()),
        gross_amount=Decimal("500.00"),
        currency_per_point=Decimal("50.00"),
    )

    assert entry is not None
    assert entry.points == 10
    assert points.saved == [entry]


def test_transfer_reverses_the_previous_owner_row_instead_of_editing_it() -> None:
    """Ledger append-only-dır: köhnə sətir `REVERSED` olur, SİLİNMİR."""
    previous = EmployeeId(uuid.uuid4())
    new_owner = EmployeeId(uuid.uuid4())
    transaction_id = SalesTransactionId(uuid.uuid4())
    original = _points_entry(employee=previous, points=8, transaction_id=transaction_id)
    points = _PointsRepo([original])
    audit = RecordingAudit()
    use_case = _points_use_case(points=points, rewards=_RewardRepo(), audit=audit)

    use_case.transfer_for_transaction(
        tenant_id=TENANT,
        transaction_id=transaction_id,
        from_employee_id=previous,
        to_employee_id=new_owner,
        store_id=STORE,
        gross_amount=Decimal("400.00"),
        actor_id=EmployeeId(uuid.uuid4()),
        reason="Sənəd başqa satıcıya aiddir",
    )

    assert original.status.value == "REVERSED"
    replacement = points.saved[-1]
    assert replacement.employee_id == new_owner
    assert replacement.points == 8, "Köçürülən xal ORİJİNAL dəyəri saxlayır"
    assert replacement.confidence is MatchConfidence.MANUAL_MATCH
    assert audit.entries[-1]["action"] == "POINTS_TRANSFERRED"
    assert audit.entries[-1]["before_state"]["employee_id"] == str(previous)


def test_transfer_without_a_previous_owner_recomputes_from_the_amount() -> None:
    """`UNASSIGNED` sətrin köhnə sahibi yoxdur — xal məbləğdən hesablanır."""
    new_owner = EmployeeId(uuid.uuid4())
    points = _PointsRepo()
    use_case = _points_use_case(points=points, rewards=_RewardRepo())

    use_case.transfer_for_transaction(
        tenant_id=TENANT,
        transaction_id=SalesTransactionId(uuid.uuid4()),
        from_employee_id=None,
        to_employee_id=new_owner,
        store_id=STORE,
        gross_amount=Decimal("450.00"),
        actor_id=EmployeeId(uuid.uuid4()),
        reason="İlk dəfə təyin olunur",
    )

    assert len(points.saved) == 1
    assert points.saved[0].points == 4, "450 AZN / 100 = 4 xal (aşağı yuvarlaqlaşdırma)"


def test_transfer_of_a_sub_point_amount_writes_nothing() -> None:
    """Sərhəd: 99 AZN → 0 xal — mənasız sətir yaradılmır."""
    points = _PointsRepo()
    audit = RecordingAudit()
    use_case = _points_use_case(points=points, rewards=_RewardRepo(), audit=audit)

    use_case.transfer_for_transaction(
        tenant_id=TENANT,
        transaction_id=SalesTransactionId(uuid.uuid4()),
        from_employee_id=None,
        to_employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        gross_amount=Decimal("99.00"),
        actor_id=EmployeeId(uuid.uuid4()),
        reason="Kiçik satış",
    )

    assert points.saved == []
    assert audit.entries == [], "Yazılmayan xal audit sətri də doğurmamalıdır"


def test_transfer_ignores_rows_of_another_transaction() -> None:
    """Köhnə sahibin BAŞQA satışdan gələn xalı toxunulmaz qalmalıdır."""
    previous = EmployeeId(uuid.uuid4())
    target_transaction = SalesTransactionId(uuid.uuid4())
    unrelated = _points_entry(
        employee=previous, points=25, transaction_id=SalesTransactionId(uuid.uuid4())
    )
    points = _PointsRepo([unrelated])
    use_case = _points_use_case(points=points, rewards=_RewardRepo())

    use_case.transfer_for_transaction(
        tenant_id=TENANT,
        transaction_id=target_transaction,
        from_employee_id=previous,
        to_employee_id=EmployeeId(uuid.uuid4()),
        store_id=OTHER_STORE,
        gross_amount=Decimal("300.00"),
        actor_id=EmployeeId(uuid.uuid4()),
        reason="Yenidən təyinat",
    )

    assert unrelated.status.value == "ACTIVE", "Başqa satışın sətri REVERSED olmamalıdır"
    assert points.saved[-1].points == 3
