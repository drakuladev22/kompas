"""İkinci dalğa — istifadəçi idarəetməsi, 1C sihirbazı, dəstək chat-i.

Birinci fayl (`test_use_case_gap_coverage.py`) kataloq/növbə/tabel tərəfini
bağladı. Burada qalan üç modul var və hər üçündə əhatəsiz sahə eyni cinsdəndir:
UĞURLU YOL yoxlanılmayıb, yalnız rədd yolları test olunub.

    * `user_management` — `create_employee`/`update_employee` gövdəsi,
    * `erp_connection`  — mağaza↔server xəritələməsi,
    * `support_chat`    — mesaj göndərmə axını.

Uğurlu yolun yoxlanmaması ən bahalı boşluqdur: rədd yolu işləyəndə sistem
"təhlükəsiz" görünür, halbuki heç kim işçi yarada bilmir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.application.use_cases.dual_control_guard import DualControlDeadlockGuardUseCase
from src.application.use_cases.erp_connection import (
    ConnectionNotVerifiedError,
    ErpConnectionError,
    ErpConnectionWizardUseCase,
    StoreServerLink,
)
from src.application.use_cases.support_chat import (
    SupportAccessError,
    SupportChatUseCase,
    SupportMessage,
    SupportMessageError,
    SupportThread,
    TicketNotFoundError,
)
from src.application.use_cases.user_management import (
    EmployeeDraft,
    EmployeeNotFoundError,
    UserManagementUseCase,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.policies import FeatureModule
from src.domain.value_objects.authorization import (
    AuthorizationError,
    HardlockLevel,
    PermissionEffect,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.erp import (
    ConnectionTestResult,
    ErpServer,
    ErpServerDraft,
    ErpServerStatus,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ErpServerId,
    PositionId,
    StoreId,
    SupportTicketId,
    TenantId,
)
from tests.fixtures.fakes import (
    FakeClock,
    FakeFeatureToggles,
    InMemoryEmployees,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

MANAGE_EMPLOYEES = PermissionFlag(code="can_manage_employees", category="ISCI")
MANAGE_ROLES = PermissionFlag(code="can_manage_roles", category="ICAZE")
MANAGE_ERP = PermissionFlag(code="can_manage_erp_servers", category="ERP_INFRA")
CONTACT_SUPPORT = PermissionFlag(code="can_contact_support", category="SISTEM")
DUAL_CONTROL = PermissionFlag(
    code="can_approve_dual_control_override",
    category="ANTI_FRAUD",
    is_anti_fraud=True,
    hardlock=HardlockLevel.ROOT_CEO,
)


def _position(role: SystemRole) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )


def make_employee(
    role: SystemRole,
    *,
    flags: list[PermissionFlag] | None = None,
    store_id: StoreId | None = STORE,
    position: Position | None = None,
) -> Employee:
    resolved = position or _position(role)
    for flag in flags or []:
        resolved.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=resolved,
        first_name="T",
        last_name=role.value,
        store_id=store_id,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


# --------------------------------------------------------------------------- #
# İstifadəçi idarəetməsi (`user_management.py`)
# --------------------------------------------------------------------------- #


class _Credentials:
    def __init__(self) -> None:
        self.passwords: list[tuple[Any, str, bool]] = []
        self.pins: list[tuple[Any, str]] = []
        self.cleared: list[Any] = []

    def set_password(self, employee_id: Any, *, raw_password: str, must_change: bool) -> None:
        self.passwords.append((employee_id, raw_password, must_change))

    def set_pin(self, employee_id: Any, *, raw_pin: str) -> None:
        self.pins.append((employee_id, raw_pin))

    def clear_pin_lockout(self, employee_id: Any) -> None:
        self.cleared.append(employee_id)


class _CameraAssignments:
    def __init__(self) -> None:
        self.assigned: list[tuple[Any, StoreId]] = []

    def assign(self, employee_id: Any, store_id: StoreId, *, assigned_by: Any) -> None:
        self.assigned.append((employee_id, store_id))

    def stores_for_operator(self, operator_id: Any) -> list[StoreId]:
        return [store for owner, store in self.assigned if owner == operator_id]


class _FlagCatalog:
    def __init__(self, flags: list[PermissionFlag]) -> None:
        self._flags = flags

    def get(self, code: str) -> PermissionFlag | None:
        return next((f for f in self._flags if f.code == code), None)

    def list_all(self) -> list[PermissionFlag]:
        return list(self._flags)


class _UserCtx:
    def __init__(
        self,
        *,
        employees: list[Employee] | None = None,
        flags: list[PermissionFlag] | None = None,
        with_guard: bool = False,
        notifier: Any = None,
    ) -> None:
        self.employees = InMemoryEmployees(employees or [])
        self.credentials = _Credentials()
        self.camera = _CameraAssignments()
        self.audit = RecordingAudit()
        self.clock = FakeClock(NOW)
        self.notifier = notifier or RecordingNotifier()
        self.guard = (
            DualControlDeadlockGuardUseCase(self.employees, notifier=self.notifier)  # type: ignore[arg-type]
            if with_guard
            else None
        )
        self.flags = _FlagCatalog(flags) if flags is not None else None

    def use_case(self) -> UserManagementUseCase:
        return UserManagementUseCase(
            employees=self.employees,  # type: ignore[arg-type]
            credentials=self.credentials,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            camera_assignments=self.camera,  # type: ignore[arg-type]
            flags=self.flags,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            deadlock_guard=self.guard,
        )


def test_creating_an_employee_with_a_password_forces_a_change_on_first_login() -> None:
    """Bölmə 2: admin ilkin şifrə təyin edirsə işçi onu DƏYİŞMƏLİDİR."""
    ctx = _UserCtx()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])
    employee_id = EmployeeId(uuid.uuid4())

    created = ctx.use_case().create_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=employee_id,
        draft=EmployeeDraft(
            first_name="Aysel",
            last_name="Quliyeva",
            position=_position(SystemRole.SELLER),
            store_id=STORE,
            username=Username.parse("a.quliyeva"),
        ),
        initial_password="Muveqqeti-123",
    )

    assert created.must_change_password is True
    assert created.has_password is True
    assert created.has_pin is False
    # SİRR SƏTİRLƏ BİRLİKDƏ YAZILIR: `create_employee` artıq `save()` +
    # `set_password()` cütünü işlətmir, çünki `save()` `UPDATE`-dir və olmayan
    # sətri yaratmır (canlı bazada işçi ÜMUMİYYƏTLƏ yaranmırdı). `chk_employee_
    # auth` da sətrin ən azı bir autentifikasiya vasitəsi İLƏ doğulmasını tələb
    # edir. Zəmanət dəyişmir — ölçmə nöqtəsi `CredentialWriter`-dən `create()`-ə
    # keçir; «məcburi dəyişmə» bayrağı isə yuxarıdakı `must_change_password`
    # yoxlamasındadır.
    assert ctx.employees.created_secrets[employee_id] == ("Muveqqeti-123", None)
    assert ctx.credentials.passwords == [], "yaradılış anında ayrıca yazı OLMAMALIDIR"
    assert ctx.employees.get(employee_id) is created
    entry = ctx.audit.entries[0]
    assert entry["action"] == "EMPLOYEE_CREATED"
    assert entry["after_state"]["full_name"] == "Aysel Quliyeva"
    assert entry["after_state"]["position"] == SystemRole.SELLER.value


def test_creating_a_pin_only_employee_writes_no_password() -> None:
    """Sərhəd: yalnız PIN — «PIN, VƏ YA ad+şifrə» invariantının o biri ucu."""
    ctx = _UserCtx()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])
    employee_id = EmployeeId(uuid.uuid4())

    created = ctx.use_case().create_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=employee_id,
        draft=EmployeeDraft(
            first_name="Kamran",
            last_name="Vəliyev",
            position=_position(SystemRole.SELLER),
            store_id=STORE,
        ),
        initial_pin="4821",
    )

    assert created.has_pin is True
    assert created.must_change_password is False
    # PIN də sətirlə birlikdə yazılır (yuxarıdakı testin şərhinə bax).
    assert ctx.employees.created_secrets[employee_id] == (None, "4821")
    assert ctx.credentials.passwords == []
    assert ctx.credentials.pins == []


def test_camera_stores_are_recorded_for_a_camera_operator() -> None:
    """Bölmə 4: çox-mağazalı təyinat yalnız Kamera Nəzarətçisi üçündür."""
    ctx = _UserCtx()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])
    employee_id = EmployeeId(uuid.uuid4())

    created = ctx.use_case().create_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=employee_id,
        draft=EmployeeDraft(
            first_name="Operator",
            last_name="Bir",
            position=_position(SystemRole.CAMERA_OPERATOR),
            username=Username.parse("op.bir"),
            camera_store_ids=(STORE, OTHER_STORE),
        ),
        initial_password="Muveqqeti-123",
    )

    assert set(created.assigned_store_ids) == {STORE, OTHER_STORE}
    assert ctx.camera.assigned == [(employee_id, STORE), (employee_id, OTHER_STORE)]
    assert ctx.audit.entries[0]["after_state"]["camera_stores"] == 2


def test_updating_a_name_records_the_previous_value() -> None:
    """Audit «nə dəyişdi» sualına cavab verməlidir — `before_state` şərtdir."""
    subject = make_employee(SystemRole.SELLER)
    previous_name = subject.full_name
    ctx = _UserCtx(employees=[subject])
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])

    updated = ctx.use_case().update_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=subject.id,
        draft=EmployeeDraft(
            first_name="  Yeni  ",
            last_name="  Ad  ",
            position=subject.position,
            store_id=OTHER_STORE,
        ),
    )

    assert updated.first_name == "Yeni", "Kənar boşluqlar təmizlənməlidir"
    assert updated.last_name == "Ad"
    assert updated.store_id == OTHER_STORE
    entry = ctx.audit.entries[0]
    assert entry["action"] == "EMPLOYEE_UPDATED"
    assert entry["before_state"]["full_name"] == previous_name
    assert entry["after_state"]["full_name"] == "Yeni Ad"
    assert entry["after_state"]["role_changed"] is False
    assert entry["after_state"]["removed_overrides"] == []


def test_a_role_change_revokes_the_anti_fraud_override_and_says_so() -> None:
    """HR ikən verilmiş dual-control override menecerə keçəndə QALMAMALIDIR."""
    subject = make_employee(SystemRole.HR_ADMIN)
    subject.apply_override(
        PermissionOverride(
            flag_code=DUAL_CONTROL.code,
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
        )
    )
    ctx = _UserCtx(employees=[subject], flags=[DUAL_CONTROL])
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES, MANAGE_ROLES])

    updated = ctx.use_case().update_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=subject.id,
        draft=EmployeeDraft(
            first_name=subject.first_name,
            last_name=subject.last_name,
            position=_position(SystemRole.STORE_MANAGER),
            store_id=STORE,
        ),
    )

    assert updated.has_permission(DUAL_CONTROL.code, now=NOW) is False
    entry = ctx.audit.entries[0]
    assert entry["after_state"]["role_changed"] is True
    assert entry["after_state"]["removed_overrides"] == [DUAL_CONTROL.code]


def test_a_role_change_without_the_roles_flag_is_blocked() -> None:
    """`can_manage_employees` TƏK BAŞINA rol dəyişməyə icazə vermir."""
    subject = make_employee(SystemRole.SELLER)
    ctx = _UserCtx(employees=[subject])
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])

    with pytest.raises(Exception, match="can_manage_roles"):
        ctx.use_case().update_employee(
            tenant_id=TENANT,
            actor=root,
            employee_id=subject.id,
            draft=EmployeeDraft(
                first_name=subject.first_name,
                last_name=subject.last_name,
                position=_position(SystemRole.STORE_MANAGER),
            ),
        )
    assert ctx.audit.entries == []


def test_updating_an_unknown_employee_raises_a_dedicated_error() -> None:
    ctx = _UserCtx()
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])

    with pytest.raises(EmployeeNotFoundError, match="İşçi tapılmadı"):
        ctx.use_case().update_employee(
            tenant_id=TENANT,
            actor=root,
            employee_id=EmployeeId(uuid.uuid4()),
            draft=EmployeeDraft(
                first_name="A", last_name="B", position=_position(SystemRole.SELLER)
            ),
        )


def test_multi_store_assignment_is_refused_for_a_non_camera_role() -> None:
    subject = make_employee(SystemRole.SELLER)
    ctx = _UserCtx(employees=[subject])
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])

    with pytest.raises(Exception, match="Kamera Nəzarətçisi"):
        ctx.use_case().update_employee(
            tenant_id=TENANT,
            actor=root,
            employee_id=subject.id,
            draft=EmployeeDraft(
                first_name=subject.first_name,
                last_name=subject.last_name,
                position=subject.position,
                camera_store_ids=(STORE,),
            ),
        )


def test_reassigning_camera_stores_replaces_the_previous_set() -> None:
    """Köhnə təyinat qalsaydı operator artıq görməməli olduğu mağazanı görərdi."""
    operator = make_employee(SystemRole.CAMERA_OPERATOR, store_id=None)
    operator.assign_store(STORE)
    ctx = _UserCtx(employees=[operator])
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])

    updated = ctx.use_case().update_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=operator.id,
        draft=EmployeeDraft(
            first_name=operator.first_name,
            last_name=operator.last_name,
            position=operator.position,
            camera_store_ids=(OTHER_STORE,),
        ),
    )

    assert list(updated.assigned_store_ids) == [OTHER_STORE]


def test_an_employee_may_not_manage_a_peer_of_the_same_tier() -> None:
    """STRICT HIERARCHY GUARD — bərabər pillə də bloklanır."""
    subject = make_employee(SystemRole.HR_ADMIN)
    ctx = _UserCtx(employees=[subject])
    peer = make_employee(SystemRole.HR_ADMIN, flags=[MANAGE_EMPLOYEES])

    with pytest.raises(AuthorizationError, match="STRICT HIERARCHY GUARD"):
        ctx.use_case().update_employee(
            tenant_id=TENANT,
            actor=peer,
            employee_id=subject.id,
            draft=EmployeeDraft(first_name="X", last_name="Y", position=subject.position),
        )


def test_deactivating_the_last_approver_warns_but_does_not_block() -> None:
    """Bölmə 3: XƏBƏRDARLIQ göstərilir, QADAĞA yoxdur."""
    hr = make_employee(SystemRole.HR_ADMIN)
    ctx = _UserCtx(employees=[hr], with_guard=True)
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])

    updated = ctx.use_case().deactivate_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=hr.id,
        reason="İşdən çıxdı",
    )

    # HR-4 — İMZA DƏYİŞDİ: metod `Employee` YOX, `OffboardingReview`
    # qaytarır (işdən çıxma anında AÇIQ qalan bağlantıların siyahısı ilə).
    # İşçinin ÖZÜ `review.employee`-dədir, yəni məlumat İTMİR — səbəb
    # `user_management.py::OffboardingReview` başlığındadır.
    assert updated.employee.is_active is False, "Xəbərdarlıq əməliyyatı BLOKLAMAMALIDIR"
    assert "EMPLOYEE_DEACTIVATED" in ctx.audit.actions()


def test_an_unavailable_flag_catalog_does_not_block_a_role_change() -> None:
    """Fail-open: kataloqa çatmamaq rol dəyişikliyini dayandırmamalıdır."""
    subject = make_employee(SystemRole.SELLER)
    ctx = _UserCtx(employees=[subject], flags=None)
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES, MANAGE_ROLES])

    updated = ctx.use_case().update_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=subject.id,
        draft=EmployeeDraft(
            first_name=subject.first_name,
            last_name=subject.last_name,
            position=_position(SystemRole.STORE_MANAGER),
            store_id=STORE,
        ),
    )

    assert updated.position.code == SystemRole.STORE_MANAGER.value


# --------------------------------------------------------------------------- #
# 1C bağlantı sihirbazı (`erp_connection.py`)
# --------------------------------------------------------------------------- #


def _draft(*, host: str = "1c.local", infobase: str = "trade") -> ErpServerDraft:
    return ErpServerDraft(
        server_name="Bakı 1C",
        host=host,
        port=8080,
        username="odata",
        password="s3cret",
        infobase=infobase,
    )


def _server(
    *, status: ErpServerStatus = ErpServerStatus.ACTIVE, infobase: str = "trade"
) -> ErpServer:
    return ErpServer(
        id=ErpServerId(uuid.uuid4()),
        tenant_id=TENANT,
        server_name="Bakı 1C",
        host="1c.local",
        port=8080,
        username="odata",
        infobase=infobase,
        status=status,
    )


class _Registry:
    def __init__(self, server: ErpServer | None = None) -> None:
        self.server = server or _server()
        self.statuses: list[tuple[Any, ErpServerStatus, str | None]] = []
        self.rollbacks: list[Any] = []

    def require(self, server_id: Any) -> ErpServer:
        return self.server

    def create(self, draft: ErpServerDraft, *, created_by: Any, activate: bool) -> ErpServer:
        return self.server

    def update(
        self, server_id: Any, draft: ErpServerDraft, *, updated_by: Any, backup_previous: bool
    ) -> ErpServer:
        return self.server

    def set_status(
        self, server_id: Any, status: ErpServerStatus, *, changed_by: Any, reason: str | None
    ) -> None:
        self.statuses.append((server_id, status, reason))

    def rollback(self, server_id: Any, *, actor_id: Any) -> ErpServer:
        self.rollbacks.append(server_id)
        return self.server


class _Connector:
    def __init__(self, result: ConnectionTestResult) -> None:
        self._result = result
        self.closed = False

    def test_connection(self) -> ConnectionTestResult:
        return self._result

    def close(self) -> None:
        self.closed = True


class _ConnectorFactory:
    def __init__(self, *, ok: bool = True) -> None:
        self.result = ConnectionTestResult(
            ok=ok,
            message="Bağlantı quruldu" if ok else "Host cavab vermir",
            detail="" if ok else "timeout",
        )
        self.connectors: list[_Connector] = []

    def for_draft(self, draft: ErpServerDraft) -> _Connector:
        connector = _Connector(self.result)
        self.connectors.append(connector)
        return connector


class _Mappings:
    def __init__(self, links: list[StoreServerLink] | None = None) -> None:
        self.links = links or []
        self.upserts: list[tuple[StoreId, Any, str]] = []
        self.deletes: list[tuple[StoreId, Any]] = []

    def list_all(self) -> list[StoreServerLink]:
        return list(self.links)

    def upsert(self, *, store_id: StoreId, server_id: Any, one_c_store_code: str) -> None:
        self.upserts.append((store_id, server_id, one_c_store_code))

    def delete(self, *, store_id: StoreId, server_id: Any) -> None:
        self.deletes.append((store_id, server_id))


def _wizard(
    *,
    ok: bool = True,
    mappings: _Mappings | None = None,
    registry: _Registry | None = None,
) -> tuple[ErpConnectionWizardUseCase, _Registry, _ConnectorFactory, RecordingAudit]:
    reg = registry or _Registry()
    factory = _ConnectorFactory(ok=ok)
    audit = RecordingAudit()
    use_case = ErpConnectionWizardUseCase(
        servers=reg,  # type: ignore[arg-type]
        connectors=factory,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        mappings=mappings,  # type: ignore[arg-type]
    )
    return use_case, reg, factory, audit


def test_the_connector_is_closed_even_on_a_failed_test() -> None:
    """Açıq qalan soket 21 tenant-lıq sistemdə fayl deskriptorlarını yeyər."""
    use_case, _, factory, _ = _wizard(ok=False)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    result = use_case.test_connection(actor=actor, draft=_draft(), now=NOW)

    assert result.ok is False
    assert factory.connectors[0].closed is True


def test_a_failed_test_never_writes_the_configuration() -> None:
    """Bölmə 7, bənd 3: yalnız test UĞURLU olduqda ayar aktivləşir."""
    use_case, _, _, audit = _wizard(ok=False)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    with pytest.raises(ConnectionNotVerifiedError, match="Bağlantı testi uğursuz"):
        use_case.save_new(actor=actor, draft=_draft(), now=NOW)
    assert audit.entries == [], "Uğursuz testdən sonra audit sətri OLMAMALIDIR"


def test_the_saved_configuration_audit_never_contains_the_password() -> None:
    """SEC-013 — şifrə audit sətrində ASLA görünmür."""
    use_case, _, _, audit = _wizard()
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    use_case.save_new(actor=actor, draft=_draft(), now=NOW)

    state = audit.entries[0]["after_state"]
    assert state["credentials_supplied"] is True
    assert "s3cret" not in str(audit.entries)
    assert audit.entries[0]["action"] == "ERP_SERVER_ADDED"


def test_activating_a_server_without_an_infobase_is_refused_with_a_readable_reason() -> None:
    """DB `CHECK` onsuz da bloklayır — burada istifadəçi ANLAŞILAN mesaj alır."""
    registry = _Registry(_server(status=ErpServerStatus.INACTIVE, infobase="   "))
    use_case, reg, _, audit = _wizard(registry=registry)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    with pytest.raises(ErpConnectionError, match="infobase"):
        use_case.set_status(
            actor=actor,
            server_id=registry.server.id,
            status=ErpServerStatus.ACTIVE,
            now=NOW,
        )
    assert reg.statuses == []
    assert audit.entries == []


def test_deactivation_records_the_previous_status_in_the_audit() -> None:
    """«Hesabatda rəqəmlər niyə azaldı» sualının cavabı burada qalır."""
    registry = _Registry(_server(status=ErpServerStatus.ACTIVE))
    use_case, reg, _, audit = _wizard(registry=registry)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    use_case.set_status(
        actor=actor,
        server_id=registry.server.id,
        status=ErpServerStatus.INACTIVE,
        now=NOW,
        reason="Mağaza bağlandı",
    )

    assert reg.statuses[0][1] is ErpServerStatus.INACTIVE
    entry = audit.entries[0]
    assert entry["before_state"] == {"status": "ACTIVE"}
    assert entry["after_state"] == {"status": "INACTIVE"}
    assert entry["reason"] == "Mağaza bağlandı"


def test_rollback_explains_in_the_audit_why_no_test_was_required() -> None:
    use_case, reg, _, audit = _wizard()
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])
    server_id = reg.server.id

    use_case.rollback(actor=actor, server_id=server_id, now=NOW)

    assert reg.rollbacks == [server_id]
    assert "test tələb olunmur" in audit.entries[0]["reason"]


def test_the_mapping_list_is_empty_when_the_repository_is_not_wired() -> None:
    """Sərhəd: `mappings=None` — istisna deyil, boş siyahı."""
    use_case, _, _, _ = _wizard(mappings=None)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    assert use_case.mappings_for(actor=actor, now=NOW) == []


def test_the_mapping_list_requires_the_erp_flag() -> None:
    use_case, _, _, _ = _wizard(mappings=_Mappings())
    manager = make_employee(SystemRole.STORE_MANAGER)

    with pytest.raises(ErpConnectionError, match="can_manage_erp_servers"):
        use_case.mappings_for(actor=manager, now=NOW)


def test_a_store_mapping_is_normalised_before_being_written() -> None:
    mappings = _Mappings()
    use_case, reg, _, _ = _wizard(mappings=mappings)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    use_case.map_store(
        actor=actor,
        server_id=reg.server.id,
        store_id=STORE,
        one_c_store_code="  BAKI   01  ",
        now=NOW,
    )

    assert mappings.upserts == [(STORE, reg.server.id, "BAKI 01")]


@pytest.mark.parametrize("code", ["", "   ", "\n\t"])
def test_an_empty_one_c_store_code_is_refused(code: str) -> None:
    """Sərhəd: boş kod hər sənədi `UNASSIGNED` edərdi — yazı BAŞLAMIR."""
    mappings = _Mappings()
    use_case, reg, _, _ = _wizard(mappings=mappings)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    with pytest.raises(ErpConnectionError, match="boş ola bilməz"):
        use_case.map_store(
            actor=actor,
            server_id=reg.server.id,
            store_id=STORE,
            one_c_store_code=code,
            now=NOW,
        )
    assert mappings.upserts == []


def test_mapping_without_a_repository_says_so_instead_of_failing_silently() -> None:
    use_case, reg, _, _ = _wizard(mappings=None)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    with pytest.raises(ErpConnectionError, match="Xəritələmə repo-su"):
        use_case.map_store(
            actor=actor,
            server_id=reg.server.id,
            store_id=STORE,
            one_c_store_code="BAKI-01",
            now=NOW,
        )


def test_unmapping_a_store_leaves_historic_sales_untouched() -> None:
    """Xəritə silinir, `sales_transactions.store_id` isə sətirdə QALIR."""
    mappings = _Mappings()
    use_case, reg, _, _ = _wizard(mappings=mappings)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    use_case.unmap_store(actor=actor, server_id=reg.server.id, store_id=STORE, now=NOW)

    assert mappings.deletes == [(STORE, reg.server.id)]


def test_unmapping_without_a_repository_is_a_no_op_not_a_crash() -> None:
    use_case, reg, _, _ = _wizard(mappings=None)
    actor = make_employee(SystemRole.ROOT, flags=[MANAGE_ERP])

    use_case.unmap_store(actor=actor, server_id=reg.server.id, store_id=STORE, now=NOW)


# --------------------------------------------------------------------------- #
# Dəstək chat-i (`support_chat.py`)
# --------------------------------------------------------------------------- #


class _Tickets:
    def __init__(self, *, open_ticket_id: SupportTicketId | None = None) -> None:
        self.open_ticket_id = open_ticket_id
        self.opened: list[tuple[SupportTicketId, str]] = []
        self.messages: list[dict[str, Any]] = []
        self.reads: list[tuple[SupportTicketId, datetime]] = []
        self.threads_by_id: dict[SupportTicketId, SupportThread] = {}

    def open_ticket(
        self,
        *,
        ticket_id: SupportTicketId,
        tenant_id: TenantId,
        opened_by: Any,
        subject: str,
        channel: Any = None,
        is_urgent: bool = False,
    ) -> None:
        self.opened.append((ticket_id, subject))
        self.open_ticket_id = ticket_id
        self.threads_by_id[ticket_id] = SupportThread(
            ticket_id=ticket_id,
            subject=subject,
            status="OPEN",
            created_at=NOW,
            messages=[],
            opened_by=opened_by,
        )

    def find_open_ticket(self, tenant_id: TenantId, **_: Any) -> SupportTicketId | None:
        return self.open_ticket_id

    def get_thread(self, ticket_id: SupportTicketId) -> SupportThread | None:
        return self.threads_by_id.get(ticket_id)

    def list_threads(
        self, tenant_id: TenantId, *, limit: int = 20, **_: Any
    ) -> list[SupportThread]:
        return list(self.threads_by_id.values())

    def append_message(
        self,
        *,
        message_id: Any,
        ticket_id: SupportTicketId,
        sender_id: Any,
        body: str,
        is_from_developer: bool,
        from_telegram: bool = False,
        attachment_name: str = "",
    ) -> None:
        self.messages.append({"ticket_id": ticket_id, "body": body})
        thread = self.threads_by_id.get(ticket_id)
        if thread is not None:
            thread.messages.append(
                SupportMessage(
                    message_id=message_id,
                    ticket_id=ticket_id,
                    body=body,
                    created_at=NOW,
                    is_from_developer=is_from_developer,
                    sender_id=sender_id,
                )
            )

    def mark_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        self.reads.append((ticket_id, up_to))


def _support(tickets: _Tickets, *, disabled: bool = False) -> SupportChatUseCase:
    toggles = FakeFeatureToggles({FeatureModule.SUPPORT_CHAT.value} if disabled else set())
    return SupportChatUseCase(
        tickets=tickets,  # type: ignore[arg-type]
        toggles=toggles,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )


def test_the_first_message_opens_a_ticket_with_a_derived_subject() -> None:
    """Boş mövzu hazırlayıcı inbox-unda «(başlıqsız)» sətirlər yaradardı."""
    tickets = _Tickets()
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    thread = use_case.send(
        tenant_id=TENANT,
        actor=actor,
        body="  Sumqayıt   serveri dörd saatdır cavab vermir, satışlar düşmür.  ",
    )

    assert len(tickets.opened) == 1
    assert tickets.opened[0][1].startswith("Sumqayıt serveri dörd saatdır")
    assert tickets.messages[0]["body"].startswith("Sumqayıt serveri dörd saatdır")
    assert "  " not in tickets.messages[0]["body"], "Mətn normallaşdırılmalıdır"
    assert thread.is_open is True


def test_the_second_message_continues_the_same_thread() -> None:
    """Bölmə 8: söhbət DAVAM EDƏN bir xətdir, hər mesaj yeni bilet deyil."""
    tickets = _Tickets()
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    use_case.send(tenant_id=TENANT, actor=actor, body="Birinci mesaj burada")
    use_case.send(tenant_id=TENANT, actor=actor, body="İkinci mesaj burada")

    assert len(tickets.opened) == 1
    assert len({item["ticket_id"] for item in tickets.messages}) == 1


def test_an_explicit_subject_wins_over_the_derived_one() -> None:
    tickets = _Tickets()
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    use_case.send(
        tenant_id=TENANT,
        actor=actor,
        body="Ətraflı izah buradadır",
        subject="  1C bağlantısı  ",
    )

    assert tickets.opened[0][1] == "1C bağlantısı"


@pytest.mark.parametrize("body", ["", "   ", "a", "\n a \t"])
def test_a_too_short_message_is_refused_before_any_write(body: str) -> None:
    """Sərhəd: təmizlənmiş mətn minimumdan qısadırsa bilet AÇILMIR."""
    tickets = _Tickets()
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    with pytest.raises(SupportMessageError, match="minimum") as raised:
        use_case.send(tenant_id=TENANT, actor=actor, body=body)
    assert raised.value.user_message == "Mesaj çox qısadır."
    assert tickets.opened == []
    assert tickets.messages == []


def test_an_oversized_message_is_refused() -> None:
    """Sərhəd: maksimum uzunluq — kəsmək məlumatı SÜKUTLA itirərdi."""
    tickets = _Tickets()
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    with pytest.raises(SupportMessageError, match="maksimum") as raised:
        use_case.send(tenant_id=TENANT, actor=actor, body="a" * 10_000)
    assert raised.value.user_message == "Mesaj çox uzundur."
    assert tickets.messages == []


def test_the_widget_is_hidden_when_the_module_is_disabled() -> None:
    """`is_available` İSTİSNA ATMIR — səlahiyyətsiz istifadəçi ikon görmür."""
    use_case = _support(_Tickets(), disabled=True)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    assert use_case.is_available(tenant_id=TENANT, actor=actor) is False


def test_a_disabled_module_blocks_sending_with_a_clear_reason() -> None:
    tickets = _Tickets()
    use_case = _support(tickets, disabled=True)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    with pytest.raises(SupportAccessError, match="SUPPORT_CHAT modulu deaktiv"):
        use_case.send(tenant_id=TENANT, actor=actor, body="Kömək lazımdır burada")
    assert tickets.messages == []


def test_the_unread_badge_is_zero_when_the_widget_is_unavailable() -> None:
    """Nişan görünməyən widget üçün hesablanmamalıdır."""
    tickets = _Tickets()
    tickets.threads_by_id[SupportTicketId(uuid.uuid4())] = SupportThread(
        ticket_id=SupportTicketId(uuid.uuid4()),
        subject="x",
        status="OPEN",
        created_at=NOW,
        messages=[],
        unread_from_developer=4,
    )
    use_case = _support(tickets, disabled=True)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    assert use_case.unread_count(tenant_id=TENANT, actor=actor) == 0


def test_the_unread_badge_sums_every_thread() -> None:
    tickets = _Tickets()
    for count in (2, 3):
        ticket_id = SupportTicketId(uuid.uuid4())
        tickets.threads_by_id[ticket_id] = SupportThread(
            ticket_id=ticket_id,
            subject="x",
            status="OPEN",
            created_at=NOW,
            messages=[],
            unread_from_developer=count,
        )
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    assert use_case.unread_count(tenant_id=TENANT, actor=actor) == 5


def test_marking_read_uses_the_clock_not_the_wall_time() -> None:
    """Determinstik vaxt — `datetime.now()` çağırılmır (`Clock` portu)."""
    tickets = _Tickets()
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])
    ticket_id = SupportTicketId(uuid.uuid4())

    use_case.mark_read(tenant_id=TENANT, actor=actor, ticket_id=ticket_id)

    assert tickets.reads == [(ticket_id, NOW)]


def test_reading_a_missing_thread_raises_a_dedicated_error() -> None:
    tickets = _Tickets()
    use_case = _support(tickets)
    actor = make_employee(SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT])

    with pytest.raises(TicketNotFoundError, match="tapılmadı"):
        use_case.thread(tenant_id=TENANT, actor=actor, ticket_id=SupportTicketId(uuid.uuid4()))


def test_listing_threads_requires_the_support_flag() -> None:
    tickets = _Tickets()
    use_case = _support(tickets)
    seller = make_employee(SystemRole.SELLER)

    with pytest.raises(SupportAccessError, match="can_contact_support"):
        use_case.threads(tenant_id=TENANT, actor=seller)


def test_a_hire_date_survives_an_update() -> None:
    """Redaktə forması işə qəbul tarixini SORUŞMUR — o, itməməlidir."""
    subject = make_employee(SystemRole.SELLER)
    subject.hire_date = date(2024, 3, 1)
    ctx = _UserCtx(employees=[subject])
    root = make_employee(SystemRole.ROOT, flags=[MANAGE_EMPLOYEES])

    updated = ctx.use_case().update_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=subject.id,
        draft=EmployeeDraft(
            first_name=subject.first_name,
            last_name=subject.last_name,
            position=subject.position,
            hire_date=date(2024, 3, 1),
        ),
    )

    assert updated.hire_date == date(2024, 3, 1)
