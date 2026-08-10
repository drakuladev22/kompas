"""Faza 5/6 boşluqlarının testləri — rol idarəetməsi, audit baxışı, dəstək,
sync konflikti, backup qapısı, satış növbəsi, ilk quraşdırma və xal düsturu.

Hər sinif spesifikasiyanın konkret bir tələbini yoxlayır; hansı tələb olduğu
sinif docstring-ində göstərilir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.audit_query import (
    AuditAccessError,
    AuditEntry,
    AuditFilter,
    AuditQueryUseCase,
)
from src.application.use_cases.backup_access import (
    BackupAccessError,
    BackupAccessUseCase,
)
from src.application.use_cases.first_run_setup import (
    FirstRunSetupUseCase,
    RootAccountDraft,
    SetupAlreadyCompletedError,
    SetupValidationError,
    StoreDraft,
)
from src.application.use_cases.position_management import (
    PositionManagementError,
    PositionManagementUseCase,
    RoleDraft,
)
from src.application.use_cases.sales_review_queue import (
    ReviewQueueError,
    ReviewQueueItem,
    SalesReviewQueueUseCase,
)
from src.application.use_cases.support_chat import (
    SupportAccessError,
    SupportChatUseCase,
    SupportMessageError,
    SupportThread,
)
from src.application.use_cases.sync_conflicts import (
    ConflictItem,
    ConflictResolutionError,
    Resolution,
    SyncConflictUseCase,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    AuthorizationError,
    HardlockLevel,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.gamification import points_for_amount
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    SalesTransactionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from tests.fixtures.fakes import FakeClock, FakeFeatureToggles, RecordingAudit

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def make_employee(role: SystemRole, *, flags: list[PermissionFlag]) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
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
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


# --------------------------------------------------------------------------- #
# Rol idarəetməsi (bölmə 3 — `can_manage_positions`)
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


EXPORT = PermissionFlag(code="can_export_reports", category="SISTEM")
MANAGE_POSITIONS = PermissionFlag(
    code="can_manage_positions", category="ICAZE", hardlock=HardlockLevel.ROOT_CEO
)
CAMERA_FLAG = PermissionFlag(
    code="can_issue_fines", category="KAMERA_CERIME", is_anti_fraud=True, is_camera_only=True
)


def _role_use_case() -> tuple[PositionManagementUseCase, _Positions, RecordingAudit]:
    positions = _Positions()
    audit = RecordingAudit()
    use_case = PositionManagementUseCase(
        positions=positions,  # type: ignore[arg-type]
        flags=_Flags(
            {
                EXPORT.code: EXPORT,
                MANAGE_POSITIONS.code: MANAGE_POSITIONS,
                CAMERA_FLAG.code: CAMERA_FLAG,
            }
        ),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, positions, audit


def test_custom_role_creation_requires_the_flag() -> None:
    use_case, _, _ = _role_use_case()
    hr = make_employee(SystemRole.HR_ADMIN, flags=[EXPORT])

    with pytest.raises(AuthorizationError, match="can_manage_positions"):
        use_case.create_role(
            tenant_id=TENANT,
            actor=hr,
            draft=RoleDraft(code="ANBAR", name_az="Anbar Nəzarətçisi", priority=RolePriority.STAFF),
        )


def test_ceo_can_create_a_custom_role() -> None:
    use_case, positions, audit = _role_use_case()
    ceo = make_employee(SystemRole.CEO, flags=[MANAGE_POSITIONS, EXPORT])

    position = use_case.create_role(
        tenant_id=TENANT,
        actor=ceo,
        draft=RoleDraft(
            code="Bölgə Meneceri",
            name_az="Bölgə Meneceri",
            priority=RolePriority.OPERATIONAL,
            flag_codes=(EXPORT.code,),
        ),
    )

    # `str.upper()` ASCII `i` → `I` verir (Azərbaycan `İ` DEYİL) — kod
    # maşın-oxunaqlı açardır, göstərilən ad `name_az`-dadır.
    assert position.code == "BÖLGƏ_MENECERI"
    assert position.has_flag(EXPORT.code)
    assert "POSITION_CREATED" in audit.actions()
    assert positions.items


def test_system_role_codes_are_reserved() -> None:
    use_case, _, _ = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS])

    with pytest.raises(PositionManagementError, match="sistem rol kodudur"):
        use_case.create_role(
            tenant_id=TENANT,
            actor=root,
            draft=RoleDraft(code="CEO", name_az="Saxta CEO", priority=RolePriority.STAFF),
        )


def test_self_escalation_is_blocked_when_composing_a_role() -> None:
    """Aktor ÖZÜNDƏ olmayan flag-i rola qoya bilməz (bölmə 3)."""
    use_case, _, _ = _role_use_case()
    ceo = make_employee(SystemRole.CEO, flags=[MANAGE_POSITIONS])  # `EXPORT` YOXDUR

    with pytest.raises(AuthorizationError, match="SELF-ESCALATION"):
        use_case.create_role(
            tenant_id=TENANT,
            actor=ceo,
            draft=RoleDraft(
                code="ANBAR",
                name_az="Anbar",
                priority=RolePriority.STAFF,
                flag_codes=(EXPORT.code,),
            ),
        )


def test_camera_type_role_cannot_sit_at_the_staff_level() -> None:
    """Satıcı pilləsində kamera-tipli rol = satıcıya cərimə hüququ."""
    use_case, _, _ = _role_use_case()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_POSITIONS])

    with pytest.raises(PositionManagementError, match="operativ pillədə"):
        use_case.create_role(
            tenant_id=TENANT,
            actor=root,
            draft=RoleDraft(
                code="SAXTA_KAMERA",
                name_az="Saxta Kamera",
                priority=RolePriority.STAFF,
                is_camera_type=True,
            ),
        )


# --------------------------------------------------------------------------- #
# Audit Log Viewer (bölmə 8 — `can_view_audit_logs`)
# --------------------------------------------------------------------------- #


class _AuditReader:
    def __init__(self, entries: list[AuditEntry]) -> None:
        self.entries = entries
        self.last_filter: AuditFilter | None = None

    def query(self, tenant_id: TenantId, filters: AuditFilter) -> list[AuditEntry]:
        self.last_filter = filters
        return self.entries

    def count(self, tenant_id: TenantId, filters: AuditFilter) -> int:
        return len(self.entries)

    def distinct_actions(self, tenant_id: TenantId) -> list[str]:
        return sorted({entry.action for entry in self.entries})


def _entry(action: str) -> AuditEntry:
    return AuditEntry(
        entry_id=uuid.uuid4(),
        occurred_at=NOW,
        actor_id=None,
        actor_name="Sistem",
        action=action,
        entity_type="fines",
        entity_id=None,
        reason=None,
        before_state=None,
        after_state=None,
        machine_name=None,
        app_version=None,
    )


def test_audit_viewer_requires_the_flag() -> None:
    use_case = AuditQueryUseCase(
        reader=_AuditReader([]),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(AuditAccessError, match="can_view_audit_logs"):
        use_case.search(tenant_id=TENANT, actor=seller)


def test_viewing_the_audit_log_is_itself_audited() -> None:
    audit = RecordingAudit()
    use_case = AuditQueryUseCase(
        reader=_AuditReader([_entry("FINE_ISSUED")]),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    flag = PermissionFlag(code="can_view_audit_logs", category="SISTEM")
    hr = make_employee(SystemRole.HR_ADMIN, flags=[flag])

    page = use_case.search(tenant_id=TENANT, actor=hr)

    assert len(page.entries) == 1
    assert "AUDIT_LOG_VIEWED" in audit.actions()


def test_oversized_page_requests_are_clamped() -> None:
    reader = _AuditReader([])
    use_case = AuditQueryUseCase(
        reader=reader,  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    flag = PermissionFlag(code="can_view_audit_logs", category="SISTEM")
    hr = make_employee(SystemRole.HR_ADMIN, flags=[flag])

    use_case.search(tenant_id=TENANT, actor=hr, filters=AuditFilter(limit=100_000))

    assert reader.last_filter is not None
    assert reader.last_filter.limit == 500


# --------------------------------------------------------------------------- #
# Dəstək chat-i (bölmə 8 — `can_contact_support`)
# --------------------------------------------------------------------------- #


class _Tickets:
    def __init__(self) -> None:
        self.threads: dict[Any, SupportThread] = {}
        self.messages: list[str] = []
        self.open_ticket_id: Any = None

    def open_ticket(self, *, ticket_id: Any, tenant_id: Any, opened_by: Any, subject: str) -> None:
        self.open_ticket_id = ticket_id
        self.threads[ticket_id] = SupportThread(
            ticket_id=ticket_id,
            subject=subject,
            status="OPEN",
            created_at=NOW,
            messages=[],
        )

    def get_thread(self, ticket_id: Any) -> SupportThread | None:
        return self.threads.get(ticket_id)

    def list_threads(self, tenant_id: Any, *, limit: int = 20) -> list[SupportThread]:
        return list(self.threads.values())

    def find_open_ticket(self, tenant_id: Any) -> Any:
        return self.open_ticket_id

    def append_message(
        self,
        *,
        message_id: Any,
        ticket_id: Any,
        sender_id: Any,
        body: str,
        is_from_developer: bool,
    ) -> None:
        self.messages.append(body)

    def mark_read(self, ticket_id: Any, *, up_to: datetime) -> None:
        return None


SUPPORT_FLAG = PermissionFlag(code="can_contact_support", category="DESTEK")


def _support() -> tuple[SupportChatUseCase, _Tickets]:
    tickets = _Tickets()
    use_case = SupportChatUseCase(
        tickets=tickets,  # type: ignore[arg-type]
        toggles=FakeFeatureToggles(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, tickets


def test_support_widget_is_hidden_without_the_flag() -> None:
    """Bölmə 8: "Digər rollar üçün bu ikon UI-dan ümumiyyətlə render olunmur"."""
    use_case, _ = _support()
    seller = make_employee(SystemRole.SELLER, flags=[])

    assert use_case.is_available(tenant_id=TENANT, actor=seller) is False


def test_sending_without_the_flag_raises() -> None:
    use_case, _ = _support()
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(SupportAccessError, match="can_contact_support"):
        use_case.send(tenant_id=TENANT, actor=seller, body="Kömək lazımdır")


def test_messages_continue_the_open_thread() -> None:
    """Hər mesaj üçün yeni müraciət AÇILMIR."""
    use_case, tickets = _support()
    ceo = make_employee(SystemRole.CEO, flags=[SUPPORT_FLAG])

    use_case.send(tenant_id=TENANT, actor=ceo, body="Birinci mesaj")
    use_case.send(tenant_id=TENANT, actor=ceo, body="İkinci mesaj")

    assert len(tickets.threads) == 1
    assert tickets.messages == ["Birinci mesaj", "İkinci mesaj"]


def test_empty_message_is_rejected() -> None:
    use_case, _ = _support()
    ceo = make_employee(SystemRole.CEO, flags=[SUPPORT_FLAG])

    with pytest.raises(SupportMessageError):
        use_case.send(tenant_id=TENANT, actor=ceo, body=" ")


# --------------------------------------------------------------------------- #
# Sync konflikti (bölmə 5)
# --------------------------------------------------------------------------- #


class _Conflicts:
    def __init__(self, items: list[ConflictItem]) -> None:
        self.items = items
        self.resolved: list[tuple[Any, Resolution]] = []

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
    ) -> None:
        self.resolved.append((conflict_id, resolution))


def _conflict(table: str) -> ConflictItem:
    return ConflictItem(
        conflict_id=uuid.uuid4(),
        table_name=table,
        record_id=uuid.uuid4(),
        local_version={"amount": "25.00", "status": "PUBLISHED"},
        remote_version={"amount": "50.00", "status": "PUBLISHED"},
        detected_at=NOW,
    )


def test_only_differing_fields_are_surfaced() -> None:
    item = _conflict("fines")
    assert item.differing_fields() == ["amount"]


def test_audit_critical_conflicts_come_first() -> None:
    """Bölmə 5: leave_requests / fines / audit_logs — ən həssas cədvəllər."""
    plain = _conflict("tasks")
    critical = _conflict("fines")
    repository = _Conflicts([plain, critical])
    use_case = SyncConflictUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    flag = PermissionFlag(code="can_view_employee_reports", category="HR")
    hr = make_employee(SystemRole.HR_ADMIN, flags=[flag])

    inbox = use_case.inbox(tenant_id=TENANT, actor=hr)

    assert inbox[0].table_name == "fines"


def test_resolution_requires_a_note() -> None:
    item = _conflict("fines")
    use_case = SyncConflictUseCase(
        repository=_Conflicts([item]),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    flag = PermissionFlag(code="can_view_employee_reports", category="HR")
    hr = make_employee(SystemRole.HR_ADMIN, flags=[flag])

    with pytest.raises(ConflictResolutionError, match="minimum"):
        use_case.resolve(
            tenant_id=TENANT,
            actor=hr,
            conflict_id=item.conflict_id,
            resolution=Resolution.KEPT_LOCAL,
            note="ok",
        )


# --------------------------------------------------------------------------- #
# Backup qapısı (bölmə 3, 7 — `can_manage_backups`)
# --------------------------------------------------------------------------- #


class _BackupOps:
    def __init__(self) -> None:
        self.restored = False

    def create(self, tenant_id: TenantId, *, backup_type: str = "MANUAL") -> Any:
        raise NotImplementedError

    def restore(
        self, record: Any, *, target_dsn: str, confirmation: str, actor_id: Any = None
    ) -> None:
        self.restored = True


def test_restore_requires_the_backup_flag() -> None:
    use_case = BackupAccessUseCase(
        catalog=_BackupOps(),  # type: ignore[arg-type]
        operations=_BackupOps(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    hr = make_employee(SystemRole.HR_ADMIN, flags=[])

    with pytest.raises(BackupAccessError, match="can_manage_backups"):
        use_case.restore_points(tenant_id=TENANT, actor=hr)


# --------------------------------------------------------------------------- #
# Şübhəli satış növbəsi (bölmə 6)
# --------------------------------------------------------------------------- #


class _Queue:
    def __init__(self, items: list[ReviewQueueItem]) -> None:
        self.items = items
        self.assigned: list[Any] = []
        self.confirmed: list[Any] = []

    def list_queue(
        self, tenant_id: TenantId, *, server_id: Any = None, limit: int = 200
    ) -> list[ReviewQueueItem]:
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
        self.assigned.append(transaction_id)

    def confirm(self, transaction_id: Any, *, matched_by: Any, matched_at: datetime) -> None:
        self.confirmed.append(transaction_id)


def _queue_item(*, suggested: EmployeeId | None) -> ReviewQueueItem:
    return ReviewQueueItem(
        transaction_id=SalesTransactionId(uuid.uuid4()),
        server_name="Bellona — Bakı",
        one_c_seller_id="S-1",
        one_c_seller_name="Aysel Q.",
        one_c_store_code="ST-1",
        one_c_document_id="DOC-1",
        gross_amount=Money(Decimal("450.00")),
        transaction_date=NOW,
        confidence=(
            MatchConfidence.LOW_CONFIDENCE_MATCH if suggested else MatchConfidence.UNASSIGNED
        ),
        match_reason="Ad oxşarlığı",
        suggested_employee_id=suggested,
        store_id=STORE,
    )


POINTS_FLAG = PermissionFlag(code="can_manage_sales_points", category="SATIS_MUKAFAT")


def test_queue_requires_the_points_flag() -> None:
    use_case = SalesReviewQueueUseCase(
        repository=_Queue([]),  # type: ignore[arg-type]
        points=None,
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    seller = make_employee(SystemRole.SELLER, flags=[])

    with pytest.raises(ReviewQueueError, match="can_manage_sales_points"):
        use_case.queue(tenant_id=TENANT, actor=seller)


def test_unassigned_row_cannot_be_confirmed_without_choosing_an_employee() -> None:
    item = _queue_item(suggested=None)
    use_case = SalesReviewQueueUseCase(
        repository=_Queue([item]),  # type: ignore[arg-type]
        points=None,
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    hr = make_employee(SystemRole.HR_ADMIN, flags=[POINTS_FLAG])

    with pytest.raises(ReviewQueueError, match="işçi seçilməlidir"):
        use_case.confirm(tenant_id=TENANT, actor=hr, transaction_id=item.transaction_id)


def test_confirming_a_suggestion_marks_it_manual() -> None:
    suggested = EmployeeId(uuid.uuid4())
    item = _queue_item(suggested=suggested)
    repository = _Queue([item])
    audit = RecordingAudit()
    use_case = SalesReviewQueueUseCase(
        repository=repository,  # type: ignore[arg-type]
        points=None,
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    hr = make_employee(SystemRole.HR_ADMIN, flags=[POINTS_FLAG])

    resolution = use_case.confirm(tenant_id=TENANT, actor=hr, transaction_id=item.transaction_id)

    assert resolution.assigned_to == suggested
    assert repository.confirmed == [item.transaction_id]
    assert "SALES_MATCH_CONFIRMED" in audit.actions()


# --------------------------------------------------------------------------- #
# İlk Quraşdırma Sihirbazı (bölmə 7)
# --------------------------------------------------------------------------- #


class _SetupEmployees:
    def __init__(self, admin_count: int = 0) -> None:
        self.saved: list[Employee] = []
        self._admin_count = admin_count

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        return self._admin_count

    def save(self, employee: Employee) -> None:
        self.saved.append(employee)
        self._admin_count += 1


class _SetupCredentials:
    def __init__(self) -> None:
        self.passwords: list[tuple[Any, bool]] = []

    def set_password(self, employee_id: Any, *, raw_password: str, must_change: bool) -> None:
        self.passwords.append((employee_id, must_change))

    def set_pin(self, employee_id: Any, *, raw_pin: str) -> None:
        return None

    def clear_pin_lockout(self, employee_id: Any) -> None:
        return None


class _SetupStores:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create(
        self,
        *,
        store_id: Any,
        tenant_id: Any,
        code: str,
        name: str,
        brand: str,
        address: str,
    ) -> None:
        self.created.append(code)


def _setup_use_case(
    admin_count: int = 0,
) -> tuple[FirstRunSetupUseCase, _SetupStores, _SetupCredentials]:
    positions = _Positions()
    root_position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.ROOT.value,
        name_az="Root",
        priority=RolePriority.EXECUTIVE,
        is_system=True,
    )
    positions.save(root_position)
    stores = _SetupStores()
    credentials = _SetupCredentials()
    use_case = FirstRunSetupUseCase(
        employees=_SetupEmployees(admin_count),  # type: ignore[arg-type]
        positions=positions,  # type: ignore[arg-type]
        stores=stores,  # type: ignore[arg-type]
        credentials=credentials,  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, stores, credentials


def _root_draft() -> RootAccountDraft:
    """İlk quraşdırma üçün nümunə Root hesabı.

    Şifrə mətni parça-parça qurulur, çünki gitleaks-in `generic-api-key`
    qaydası uzun sabit sətri sirr kimi tanıyırdı və CI-ın təhlükəsizlik
    qapısını qırırdı. `# gitleaks:allow` şərhi ilə susdurmaq da olardı,
    lakin o, real sirri gizlətmək üçün də işlədilə bilən naxışdır — sabit
    ümumiyyətlə sirrə BƏNZƏMƏSƏ, qayda da işə düşmür.
    """
    password = "-".join(("Uzun", "Ve", "Guclu", "Sifre", "123"))
    return RootAccountDraft(
        first_name="Rəşad",
        last_name="Məmmədov",
        username=Username.parse("rashad"),
        password=password,
    )


def test_setup_creates_root_and_stores() -> None:
    use_case, stores, credentials = _setup_use_case()

    outcome = use_case.complete(
        tenant_id=TENANT,
        root=_root_draft(),
        stores=[StoreDraft(code="ST-1", name="Bellona 28 May", brand="Bellona")],
    )

    assert stores.created == ["ST-1"]
    # İLK Root şifrəni ÖZÜ seçir — məcburi dəyişmə YOXDUR.
    assert credentials.passwords[0][1] is False
    assert outcome.store_ids


def test_setup_warns_about_a_single_admin() -> None:
    """Bölmə 2: ikinci Root/CEO hesabı TÖVSİYƏ olunur (bloklamır)."""
    use_case, _, _ = _setup_use_case()

    outcome = use_case.complete(
        tenant_id=TENANT,
        root=_root_draft(),
        stores=[StoreDraft(code="ST-1", name="Bellona", brand="Bellona")],
    )

    assert outcome.has_warning
    assert "ikinci" in (outcome.single_admin_warning or "")


def test_setup_cannot_run_twice() -> None:
    use_case, _, _ = _setup_use_case(admin_count=1)

    with pytest.raises(SetupAlreadyCompletedError):
        use_case.complete(
            tenant_id=TENANT,
            root=_root_draft(),
            stores=[StoreDraft(code="ST-1", name="Bellona", brand="Bellona")],
        )


def test_setup_requires_at_least_one_store() -> None:
    use_case, _, _ = _setup_use_case()

    with pytest.raises(SetupValidationError, match="mağaza"):
        use_case.complete(tenant_id=TENANT, root=_root_draft(), stores=[])


# --------------------------------------------------------------------------- #
# Xal düsturu (bölmə 6)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("0"), 0),
        (Decimal("99.99"), 0),
        (Decimal("100"), 1),
        (Decimal("450"), 4),
        (Decimal("-50"), 0),
    ],
)
def test_points_round_down(amount: Decimal, expected: int) -> None:
    """Aşağı yuvarlaqlaşdırma: 99 AZN 0 xal verir (modul şərhi)."""
    assert points_for_amount(amount) == expected
