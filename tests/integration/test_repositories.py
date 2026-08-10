"""Repository inteqrasiya testləri — REAL PostgreSQL-ə qarşı (Faza 3.3).

Bu testlər `DATABASE_URL` təyin edilməyibsə ATLANIR — beləliklə unit test
dəsti DB olmadan da işləyir.

VACİB: testlər `kompasos_app` rolu ilə işləməlidir (owner DEYİL) — yalnız o
zaman RLS həqiqətən yoxlanılır. `conftest` bunu yoxlayır.

Hər test öz tenant-ını yaradır və sonda TAM təmizləyir — paralel icra və
təkrar çalışdırma təhlükəsizdir.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.domain.entities import (
    AttendanceRecord,
    CheckInStatus,
    Fine,
    FineSource,
    LeaveRequest,
    LeaveStatus,
    PermissionOverride,
)
from src.domain.value_objects import (
    Money,
    PermissionEffect,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
    new_attendance_record_id,
    new_employee_id,
    new_fine_id,
    new_leave_request_id,
)
from src.infrastructure.persistence import (
    Database,
    TenantContextError,
)

pytestmark = [pytest.mark.integration]

DATABASE_URL = os.environ.get("DATABASE_URL", "")

requires_db = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL təyin edilməyib — inteqrasiya testləri atlandı",
)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 8, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def database() -> Iterator[Database]:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL yoxdur")
    db = Database(DATABASE_URL, min_size=1, max_size=3)
    yield db
    db.close()


@pytest.fixture
def tenant(database: Database) -> Iterator[TenantId]:
    """İzolyasiya olunmuş test tenant-ı — sonda tam silinir."""
    tenant_id = TenantId(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]

    with database.system_scope() as conn:
        conn.execute(
            """
            INSERT INTO license_tenants
                (tenant_id, tenant_name, license_key_hash, status, company_contact_email)
            VALUES (%s, %s, 'test', 'AKTIV', %s)
            """,
            (tenant_id, f"IT-{suffix}", f"it-{suffix}@test.local"),
        )
        conn.execute("SELECT seed_tenant_defaults(%s)", (tenant_id,))
        conn.execute(
            """
            INSERT INTO stores (tenant_id, code, name, brand)
            VALUES (%s, %s, 'Test Mağaza', 'Yataş')
            """,
            (tenant_id, f"IT-{suffix}"),
        )
        conn.commit()

    yield tenant_id

    with database.system_scope() as conn:
        conn.execute("DELETE FROM license_tenants WHERE tenant_id = %s", (tenant_id,))
        conn.commit()


@pytest.fixture
def store_id(database: Database, tenant: TenantId) -> StoreId:
    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM stores WHERE tenant_id = %s LIMIT 1", (tenant,))
        row = cur.fetchone()
    assert row is not None
    return StoreId(row["id"])


def position_id_for(database: Database, tenant: TenantId, code: str) -> PositionId:
    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM positions WHERE tenant_id = %s AND code = %s",
            (tenant, code),
        )
        row = cur.fetchone()
    assert row is not None, f"Rol tapılmadı: {code}"
    return PositionId(row["id"])


def make_employee_row(
    database: Database,
    tenant: TenantId,
    store: StoreId,
    role: SystemRole,
    *,
    with_pin: bool = False,
) -> EmployeeId:
    """DB-də işçi yaradır və ID-sini qaytarır."""
    employee_id = new_employee_id()
    position_id = position_id_for(database, tenant, role.value)
    suffix = uuid.uuid4().hex[:8]

    with database.system_scope() as conn:
        conn.execute(
            """
            INSERT INTO employees
                (id, tenant_id, store_id, position_id, first_name, last_name,
                 username, password_hash, pin_hash, is_active)
            VALUES (%s, %s, %s, %s, 'Test', %s, %s, 'argon2-hash', %s, TRUE)
            """,
            (
                employee_id,
                tenant,
                store,
                position_id,
                role.value,
                f"u{suffix}",  # username — `chk_employee_username` qaydasına uyğun
                "argon2-pin" if with_pin else None,
            ),
        )
        conn.commit()
    return employee_id


# --------------------------------------------------------------------------- #
# SEC-008 — RLS və UnitOfWork müqaviləsi
# --------------------------------------------------------------------------- #


@requires_db
def test_repository_unavailable_outside_unit_of_work(database: Database, tenant: TenantId) -> None:
    """Repo-ya UoW-dan KƏNARDA müraciət struktur olaraq bloklanır."""
    uow = database.unit_of_work(tenant)

    with pytest.raises(TenantContextError, match="aktiv deyil"):
        _ = uow.employees


@requires_db
def test_tenant_context_is_applied(database: Database, tenant: TenantId) -> None:
    with database.unit_of_work(tenant) as uow, uow.connection.cursor() as cur:
        cur.execute("SELECT current_tenant_id() AS t")
        row = cur.fetchone()
        assert row is not None
        assert str(row["t"]) == str(tenant)


@requires_db
def test_cross_tenant_data_is_invisible(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """ƏSAS İZOLYASİYA TESTİ: başqa tenant-ın işçisi görünməməlidir."""
    employee_id = make_employee_row(database, tenant, store_id, SystemRole.HR_ADMIN)
    other_tenant = TenantId(uuid.uuid4())

    with database.unit_of_work(tenant) as uow:
        assert uow.employees.get(employee_id) is not None

    with database.unit_of_work(other_tenant) as uow:
        assert uow.employees.get(employee_id) is None


@requires_db
def test_rollback_is_default(database: Database, tenant: TenantId, store_id: StoreId) -> None:
    """`commit()` çağırılmazsa dəyişiklik SAXLANILMIR."""
    employee_id = make_employee_row(database, tenant, store_id, SystemRole.HR_ADMIN)

    with database.unit_of_work(tenant) as uow:
        employee = uow.employees.get(employee_id)
        assert employee is not None
        employee.first_name = "DəyişdirilmişAd"
        uow.employees.save(employee)
        # commit() QƏSDƏN çağırılmır

    with database.unit_of_work(tenant) as uow:
        reloaded = uow.employees.get(employee_id)
        assert reloaded is not None
        assert reloaded.first_name == "Test"


# --------------------------------------------------------------------------- #
# Employee repository
# --------------------------------------------------------------------------- #


@requires_db
def test_employee_roundtrip(database: Database, tenant: TenantId, store_id: StoreId) -> None:
    employee_id = make_employee_row(database, tenant, store_id, SystemRole.HR_ADMIN)

    with database.unit_of_work(tenant) as uow:
        employee = uow.employees.get(employee_id)

        assert employee is not None
        assert employee.tenant_id == tenant
        assert employee.position.code == "HR_ADMIN"
        assert employee.position.priority is RolePriority.OPERATIONAL
        # Seed rol-flag təyinatı bərpa olunub
        assert "can_manage_employees" in employee.position.granted_flags


@requires_db
def test_credentials_are_separate_from_entity(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Sirrlər entity-də DEYİL — ayrıca `Credentials` ilə gəlir."""
    employee_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)

    with database.unit_of_work(tenant) as uow:
        employee = uow.employees.get(employee_id)
        credentials = uow.employees.credentials_for(employee_id)

        assert employee is not None
        assert employee.has_pin is True
        assert not hasattr(employee, "pin_hash")

        assert credentials is not None
        assert credentials.pin_hash == "argon2-pin"
        # `repr` sirri açmır
        assert "argon2-pin" not in repr(credentials)


@requires_db
def test_save_does_not_touch_secrets(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Adi `save()` təsadüfən PIN/şifrəni sıfırlamamalıdır."""
    employee_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)

    with database.unit_of_work(tenant) as uow:
        employee = uow.employees.get(employee_id)
        assert employee is not None
        employee.first_name = "Yeni"
        uow.employees.save(employee)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        credentials = uow.employees.credentials_for(employee_id)
        assert credentials is not None
        assert credentials.pin_hash == "argon2-pin"  # toxunulmayıb


@requires_db
def test_update_credentials_is_selective(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """`None` verilən sahə TOXUNULMUR (COALESCE)."""
    employee_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)

    with database.unit_of_work(tenant) as uow:
        uow.employees.update_credentials(employee_id, pin_hash="yeni-pin-hash")
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        credentials = uow.employees.credentials_for(employee_id)
        assert credentials is not None
        assert credentials.pin_hash == "yeni-pin-hash"
        assert credentials.password_hash == "argon2-hash"  # dəyişməyib


@requires_db
def test_permission_override_roundtrip(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    actor_id = make_employee_row(database, tenant, store_id, SystemRole.ROOT)
    subject_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER)

    with database.unit_of_work(tenant, user_id=actor_id) as uow:
        subject = uow.employees.get(subject_id)
        assert subject is not None
        subject.apply_override(
            PermissionOverride(
                flag_code="can_view_employee_reports",
                effect=PermissionEffect.GRANT,
                granted_by=actor_id,
            )
        )
        uow.employees.save(subject)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        reloaded = uow.employees.get(subject_id)
        assert reloaded is not None
        assert reloaded.has_permission("can_view_employee_reports", now=at(12)) is True


@requires_db
def test_db_trigger_blocks_anti_fraud_override(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Domen qatı yan keçilsə belə DB trigger-i bloklayır (defense-in-depth)."""
    import psycopg

    actor_id = make_employee_row(database, tenant, store_id, SystemRole.ROOT)
    manager_id = make_employee_row(database, tenant, store_id, SystemRole.STORE_MANAGER)

    with database.unit_of_work(tenant, user_id=actor_id) as uow:
        manager = uow.employees.get(manager_id)
        assert manager is not None
        # Domen yoxlamasını yan keçib birbaşa override əlavə edirik
        manager.apply_override(
            PermissionOverride(
                flag_code="can_issue_fines",
                effect=PermissionEffect.GRANT,
                granted_by=actor_id,
            )
        )
        with pytest.raises(psycopg.errors.RaiseException, match="ANTI-FRAUD"):
            uow.employees.save(manager)


@requires_db
def test_camera_operator_store_assignment(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    operator_id = make_employee_row(database, tenant, store_id, SystemRole.CAMERA_OPERATOR)

    with database.unit_of_work(tenant, user_id=operator_id) as uow:
        operator = uow.employees.get(operator_id)
        assert operator is not None
        assert operator.assigned_store_ids == frozenset()  # fail-safe defolt

        operator.assign_store(store_id)
        uow.employees.save(operator)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        reloaded = uow.employees.get(operator_id)
        assert reloaded is not None
        assert reloaded.can_see_store(store_id) is True


@requires_db
def test_count_active_with_flag_uses_effective_permissions(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Dual-Control Deadlock Guard — seed HR_Admin təsdiqçi kimi sayılmalıdır."""
    make_employee_row(database, tenant, store_id, SystemRole.HR_ADMIN)

    with database.unit_of_work(tenant) as uow:
        count = uow.employees.count_active_with_flag(tenant, "can_approve_dual_control_override")
        assert count >= 1


# --------------------------------------------------------------------------- #
# LeaveRequest repository
# --------------------------------------------------------------------------- #


@requires_db
def test_leave_request_roundtrip(database: Database, tenant: TenantId, store_id: StoreId) -> None:
    worker_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)
    operator_id = make_employee_row(database, tenant, store_id, SystemRole.CAMERA_OPERATOR)

    request = LeaveRequest.open(
        request_id=new_leave_request_id(),
        tenant_id=tenant,
        employee_id=worker_id,
        store_id=store_id,
        requested_time=at(12, 0),
        allowance_minutes=60,
        ntp_verified=True,
        employee_is_in_store=True,
    )

    with database.unit_of_work(tenant, user_id=worker_id) as uow:
        uow.leave_requests.save(request)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        loaded = uow.leave_requests.find_open_for_employee(worker_id)
        assert loaded is not None
        assert loaded.status is LeaveStatus.OUTSIDE
        assert loaded.allowance_minutes == 60
        assert loaded.has_pending_events is False  # bərpa hadisə yaratmır

        loaded.claim_return(claimed_at=at(13, 30))
        uow.leave_requests.save(loaded)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        pending = uow.leave_requests.list_pending_verification([store_id])
        assert len(pending) == 1

        verified = pending[0]
        penalty = verified.verify_return(operator_id=operator_id, verified_at=at(13, 30))
        assert penalty.delay_minutes == 30
        assert penalty.total_minutes == 120
        uow.leave_requests.save(verified)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        final = uow.leave_requests.get(request.id)
        assert final is not None
        assert final.status is LeaveStatus.VERIFIED
        assert final.penalty is not None
        assert final.penalty.delay_minutes == 30


@requires_db
def test_pending_queue_is_fail_safe(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Boş mağaza siyahısı → boş nəticə (bölmə 4)."""
    with database.unit_of_work(tenant) as uow:
        assert uow.leave_requests.list_pending_verification([]) == []
        assert uow.attendance.list_pending_verification([]) == []


@requires_db
def test_manual_override_persisted(database: Database, tenant: TenantId, store_id: StoreId) -> None:
    worker_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)
    operator_id = make_employee_row(database, tenant, store_id, SystemRole.CAMERA_OPERATOR)

    request = LeaveRequest.open(
        request_id=new_leave_request_id(),
        tenant_id=tenant,
        employee_id=worker_id,
        store_id=store_id,
        requested_time=at(12, 0),
        allowance_minutes=60,
        employee_is_in_store=True,
    )
    request.claim_return(claimed_at=at(13, 0))
    request.apply_manual_override(
        operator_id=operator_id,
        overridden_time=at(12, 20),
        system_time=at(13, 0),
        reason="Kameradan təsdiqləndi, işçi 12:20-də qayıtdı",
    )

    with database.unit_of_work(tenant, user_id=operator_id) as uow:
        uow.leave_requests.save(request)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        loaded = uow.leave_requests.get(request.id)
        assert loaded is not None
        assert loaded.override is not None
        assert loaded.override.delta_minutes == 40
        assert loaded.override.requires_dual_control is True


# --------------------------------------------------------------------------- #
# Attendance repository
# --------------------------------------------------------------------------- #


@requires_db
def test_attendance_roundtrip(database: Database, tenant: TenantId, store_id: StoreId) -> None:
    worker_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)
    operator_id = make_employee_row(database, tenant, store_id, SystemRole.CAMERA_OPERATOR)
    work_date = date(2026, 8, 8)

    record = AttendanceRecord(
        record_id=new_attendance_record_id(),
        tenant_id=tenant,
        employee_id=worker_id,
        store_id=store_id,
        work_date=work_date,
    )
    record.request_check_in(requested_at=at(8, 5), ntp_verified=True)

    with database.unit_of_work(tenant, user_id=worker_id) as uow:
        uow.attendance.save(record)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        queue = uow.attendance.list_pending_verification([store_id])
        assert len(queue) == 1

        loaded = queue[0]
        assert loaded.status is CheckInStatus.PENDING_VERIFICATION
        loaded.verify(operator_id=operator_id, verified_at=at(8, 5), scheduled_start=at(8, 0))
        uow.attendance.save(loaded)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        final = uow.attendance.get_for_day(worker_id, work_date)
        assert final is not None
        assert final.status is CheckInStatus.VERIFIED
        assert final.can_request_leave is True


# --------------------------------------------------------------------------- #
# Fine repository
# --------------------------------------------------------------------------- #


@requires_db
def test_fine_export_lock(database: Database, tenant: TenantId, store_id: StoreId) -> None:
    """Bölmə 6 LOCK MEXANİZMİ — DB və domen eyni nəticəni verməlidir."""
    worker_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)
    operator_id = make_employee_row(database, tenant, store_id, SystemRole.CAMERA_OPERATOR)

    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM fine_types WHERE tenant_id = %s LIMIT 1", (tenant,))
        fine_type = cur.fetchone()
    if fine_type is None:
        with database.system_scope() as conn:
            conn.execute(
                """
                INSERT INTO fine_types (tenant_id, name_az, standard_amount)
                VALUES (%s, 'Test Növ', 10.00) RETURNING id
                """,
                (tenant,),
            )
            conn.commit()
        with database.system_scope() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM fine_types WHERE tenant_id = %s LIMIT 1", (tenant,))
            fine_type = cur.fetchone()
    assert fine_type is not None

    issued_at = datetime.now(tz=UTC) - timedelta(hours=100)  # pəncərə bağlanıb
    fine = Fine(
        fine_id=new_fine_id(),
        tenant_id=tenant,
        employee_id=worker_id,
        store_id=store_id,
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal("15.00")),
        issued_at=issued_at,
        fine_type_id=fine_type["id"],
        issued_by=operator_id,
        photo_evidence_url="https://storage/x.jpg",
    )

    with database.unit_of_work(tenant, user_id=operator_id) as uow:
        uow.fines.save(fine)
        uow.commit()

    now = datetime.now(tz=UTC)
    with database.unit_of_work(tenant) as uow:
        exportable = uow.fines.list_exportable(tenant, now=now)
        assert len(exportable) == 1
        assert exportable[0].id == fine.id

        # Ləğv edildikdən sonra export-dan ÇIXMALIDIR
        reversed_fine = exportable[0]
        reversed_fine.reverse(
            decided_by=operator_id,
            decided_at=now,
            reason="Etiraz təsdiqləndi, işçi haqlıdır",
        )
        uow.fines.save(reversed_fine)
        uow.commit()

    with database.unit_of_work(tenant) as uow:
        assert uow.fines.list_exportable(tenant, now=now) == []


@requires_db
def test_open_fine_within_window_not_exportable(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    worker_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)
    operator_id = make_employee_row(database, tenant, store_id, SystemRole.CAMERA_OPERATOR)

    with database.system_scope() as conn:
        conn.execute(
            "INSERT INTO fine_types (tenant_id, name_az, standard_amount) VALUES (%s, %s, 10.00)",
            (tenant, f"Növ-{uuid.uuid4().hex[:6]}"),
        )
        conn.commit()
    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM fine_types WHERE tenant_id = %s LIMIT 1", (tenant,))
        fine_type = cur.fetchone()
    assert fine_type is not None

    fine = Fine(
        fine_id=new_fine_id(),
        tenant_id=tenant,
        employee_id=worker_id,
        store_id=store_id,
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal("10.00")),
        issued_at=datetime.now(tz=UTC),  # pəncərə AÇIQDIR
        fine_type_id=fine_type["id"],
        issued_by=operator_id,
        photo_evidence_url="https://storage/y.jpg",
    )

    with database.unit_of_work(tenant, user_id=operator_id) as uow:
        uow.fines.save(fine)
        uow.commit()
        assert uow.fines.list_exportable(tenant, now=datetime.now(tz=UTC)) == []


# --------------------------------------------------------------------------- #
# Position repository
# --------------------------------------------------------------------------- #


@requires_db
def test_position_flags_roundtrip(database: Database, tenant: TenantId) -> None:
    with database.unit_of_work(tenant) as uow:
        positions = uow.positions.list_for_tenant(tenant)

        assert len(positions) == 7  # 7 defolt sistem rolu
        codes = {p.code for p in positions}
        assert codes == {
            "ROOT",
            "CEO",
            "ADMIN",
            "HR_ADMIN",
            "MAGAZA_MENECERI",
            "KAMERA_NEZARETCISI",
            "SATICI",
        }

        camera = next(p for p in positions if p.code == "KAMERA_NEZARETCISI")
        assert camera.is_camera_type is True
        assert "can_issue_fines" in camera.granted_flags

        seller = next(p for p in positions if p.code == "SATICI")
        assert seller.granted_flags == frozenset()


@requires_db
def test_health_check(database: Database) -> None:
    assert database.health_check() is True


# --------------------------------------------------------------------------- #
# Drive sübut sütunları (miqrasiya 002)
# --------------------------------------------------------------------------- #


@requires_db
def test_drive_evidence_columns_roundtrip(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Yükləmə bitdikdən sonra sətir SYNCED olur, növbə açarı isə QALIR.

    `photo_evidence_url` üzərindən yazılmır — o, hansı lokal yükləmənin bu
    sətri doldurduğunu göstərən yeganə izdir (bax `migrations/002` başlığı).
    """
    worker_id = make_employee_row(database, tenant, store_id, SystemRole.SELLER, with_pin=True)
    operator_id = make_employee_row(database, tenant, store_id, SystemRole.CAMERA_OPERATOR)

    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM fine_types WHERE tenant_id = %s LIMIT 1", (tenant,))
        fine_type = cur.fetchone()
    assert fine_type is not None

    fine = Fine(
        fine_id=new_fine_id(),
        tenant_id=tenant,
        employee_id=worker_id,
        store_id=store_id,
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal("15.00")),
        issued_at=datetime.now(tz=UTC),
        fine_type_id=fine_type["id"],
        issued_by=operator_id,
        photo_evidence_url="queue-entry-42",
    )

    with database.unit_of_work(tenant, user_id=operator_id) as uow:
        uow.fines.save(fine)
        uow.fines.mark_evidence_pending(fine.id)
        uow.commit()

    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT evidence_upload_status FROM fines WHERE id = %s", (fine.id,))
        row = cur.fetchone()
    assert row is not None
    assert row["evidence_upload_status"] == "PENDING"

    with database.unit_of_work(tenant, user_id=operator_id) as uow:
        uow.fines.attach_drive_evidence(fine.id, file_id="drive-file-1", connection_id=None)
        uow.commit()

    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT evidence_drive_file_id, evidence_upload_status, photo_evidence_url
                 FROM fines WHERE id = %s""",
            (fine.id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row["evidence_drive_file_id"] == "drive-file-1"
    assert row["evidence_upload_status"] == "SYNCED"
    assert row["photo_evidence_url"] == "queue-entry-42", "Növbə izi silinməməlidir"
