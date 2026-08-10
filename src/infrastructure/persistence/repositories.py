"""Supabase/PostgreSQL repository-ləri (spesifikasiya bölmə 2) — Faza 3.2.

QAYDA (bölmə 2): **100% Parameterized SQL Queries.** Bu faylda heç bir SQL
sətir birləşdirmə (`f"..."`, `+`, `%`) ilə qurulmur — bütün dəyərlər `%s`
placeholder-ları ilə ötürülür. Yeganə istisna: sabit sütun adları, onlar da
kod daxilində literal kimi yazılır, kənardan gəlmir.

RLS: bu repo-lar YALNIZ aktiv `PostgresUnitOfWork` daxilində yaradılır və
tranzaksiya artıq `SET LOCAL app.tenant_id` icra edib (SEC-008). Sorğularda
`tenant_id` şərti ƏLAVƏ olaraq yazılır — RLS sıradan çıxsa belə (məs. tətbiq
səhvən owner rolu ilə qoşulsa) izolyasiya qalsın.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.entities.attendance_record import AttendanceRecord, CheckInStatus
from src.domain.entities.employee import Employee
from src.domain.entities.fine import Fine
from src.domain.entities.leave_request import LeaveRequest, LeaveStatus
from src.domain.entities.position import Position
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    FineId,
    LeaveRequestId,
    PositionId,
    StoreId,
    TenantId,
)
from src.infrastructure.persistence.mappers import (
    Credentials,
    apply_overrides,
    apply_position_flags,
    apply_store_assignments,
    attendance_from_row,
    attendance_to_params,
    credentials_from_row,
    employee_from_row,
    fine_from_row,
    fine_to_params,
    leave_request_from_row,
    leave_request_to_params,
    position_from_row,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from psycopg import Connection

    from src.infrastructure.persistence.connection import TenantContext

_log = get_logger(__name__)


class _BaseRepository:
    """Ortaq bağlantı/kontekst saxlayıcısı."""

    def __init__(self, conn: Connection[dict[str, Any]], context: TenantContext) -> None:
        self._conn = conn
        self._context = context

    @property
    def _tenant(self) -> TenantId:
        return self._context.tenant_id

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def _execute(self, sql: str, params: tuple[Any, ...]) -> int:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


# --------------------------------------------------------------------------- #
# Position
# --------------------------------------------------------------------------- #


class PostgresPositionRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, code, name_az, priority, is_system,
               is_camera_type, is_active
        FROM positions
    """

    def get(self, position_id: PositionId) -> Position | None:
        row = self._fetch_one(self._SELECT + " WHERE id = %s", (position_id,))
        return self._hydrate(row) if row else None

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        row = self._fetch_one(
            self._SELECT + " WHERE tenant_id = %s AND code = %s", (tenant_id, code)
        )
        return self._hydrate(row) if row else None

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        rows = self._fetch_all(
            self._SELECT + " WHERE tenant_id = %s ORDER BY priority, code",
            (tenant_id,),
        )
        return [self._hydrate(row) for row in rows]

    def save(self, position: Position) -> None:
        self._execute(
            """
            INSERT INTO positions
                (id, tenant_id, code, name_az, priority, is_system,
                 is_camera_type, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name_az        = EXCLUDED.name_az,
                priority       = EXCLUDED.priority,
                is_camera_type = EXCLUDED.is_camera_type,
                is_active      = EXCLUDED.is_active
            """,
            (
                position.id,
                position.tenant_id,
                position.code,
                position.name_az,
                int(position.priority),
                position.is_system,
                position.is_camera_type,
                position.is_active,
            ),
        )
        self._sync_flags(position)

    def _sync_flags(self, position: Position) -> None:
        """Rol → flag təyinatını DB ilə uzlaşdırır.

        DB trigger-ləri (anti-fraud, hardlock) burada da işə düşür — yəni
        domen qatı yan keçilsə belə qadağan olunmuş flag DB-yə düşmür.
        """
        self._execute(
            "DELETE FROM position_permissions WHERE position_id = %s AND flag_code <> ALL(%s)",
            (position.id, list(position.granted_flags) or [""]),
        )
        for flag_code in position.granted_flags:
            self._execute(
                """
                INSERT INTO position_permissions (position_id, flag_code, granted)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (position_id, flag_code) DO UPDATE SET granted = TRUE
                """,
                (position.id, flag_code),
            )

    def _hydrate(self, row: dict[str, Any]) -> Position:
        position = position_from_row(row)
        flags = self._fetch_all(
            """
            SELECT flag_code FROM position_permissions
            WHERE position_id = %s AND granted
            """,
            (position.id,),
        )
        return apply_position_flags(position, [f["flag_code"] for f in flags])


# --------------------------------------------------------------------------- #
# Employee
# --------------------------------------------------------------------------- #


class PostgresEmployeeRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, store_id, position_id, first_name, last_name,
               username, notification_email, password_hash, must_change_password,
               pin_hash, pin_failed_attempts, pin_locked_until, pepper_version,
               profile_photo_url, hire_date, date_of_birth, is_active
        FROM employees
    """

    def get(self, employee_id: EmployeeId) -> Employee | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s",
            (employee_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        # `username` sütunu CITEXT-dir — böyük/kiçik hərf fərqi DB tərəfindən
        # nəzərə alınmır, ona görə burada əlavə `lower()` LAZIM DEYİL
        # (əlavə edilsəydi indeksdən istifadə də pozulardı).
        row = self._fetch_one(
            self._SELECT + " WHERE tenant_id = %s AND username = %s",
            (tenant_id, str(username)),
        )
        return self._hydrate(row) if row else None

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Employee]:
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND store_id = %s
              AND is_active AND pin_hash IS NOT NULL
            """,
            (tenant_id, store_id),
        )
        return [self._hydrate(row) for row in rows]

    def credentials_for(self, employee_id: EmployeeId) -> Credentials | None:
        """Sirr materialı — entity-dən AYRI (log-a düşməsin deyə)."""
        row = self._fetch_one(
            """
            SELECT id, pin_hash, password_hash, pepper_version
            FROM employees WHERE id = %s AND tenant_id = %s
            """,
            (employee_id, self._tenant),
        )
        return credentials_from_row(row) if row else None

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        """Dual-Control Deadlock Guard üçün — EFFEKTİV icazə (override daxil)."""
        row = self._fetch_one(
            """
            SELECT count(*)::int AS n
            FROM v_effective_permissions v
            JOIN employees e ON e.id = v.user_id
            WHERE v.tenant_id = %s AND v.flag_code = %s AND v.is_granted
              AND e.is_active
            """,
            (tenant_id, flag_code),
        )
        return int(row["n"]) if row else 0

    def save(self, employee: Employee) -> None:
        """Entity-dən gələn sahələri yeniləyir.

        SİRRLƏRƏ TOXUNMUR: `pin_hash`/`password_hash` burada YAZILMIR —
        onlar üçün ayrıca `update_credentials()` var. Beləliklə adi `save()`
        çağırışı təsadüfən sirri sıfırlaya bilməz.

        `username` DƏ BURADA YAZILMIR: giriş identifikatorunun dəyişməsi
        ayrıca, audit-lənən əməliyyatdır (`rename_username()`) — adi profil
        yeniləməsi ilə birlikdə sükutla baş verməməlidir.
        """
        self._execute(
            """
            UPDATE employees SET
                store_id             = %s,
                position_id          = %s,
                first_name           = %s,
                last_name            = %s,
                notification_email   = %s,
                must_change_password = %s,
                pin_failed_attempts  = %s,
                pin_locked_until     = %s,
                is_active            = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                employee.store_id,
                employee.position.id,
                employee.first_name,
                employee.last_name,
                str(employee.notification_email) if employee.notification_email else None,
                employee.must_change_password,
                employee.pin_security.failed_attempts,
                employee.pin_security.locked_until,
                employee.is_active,
                employee.id,
                self._tenant,
            ),
        )
        self._sync_overrides(employee)
        self._sync_store_assignments(employee)

    def insert(self, employee: Employee, credentials: Credentials) -> None:
        """Yeni işçi — sirrlərlə birlikdə (yalnız yaradılış anında)."""
        self._execute(
            """
            INSERT INTO employees
                (id, tenant_id, store_id, position_id, first_name, last_name,
                 username, notification_email, password_hash, must_change_password,
                 pin_hash, pepper_version, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                employee.id,
                employee.tenant_id,
                employee.store_id,
                employee.position.id,
                employee.first_name,
                employee.last_name,
                str(employee.username) if employee.username else None,
                str(employee.notification_email) if employee.notification_email else None,
                credentials.password_hash,
                employee.must_change_password,
                credentials.pin_hash,
                credentials.pepper_version,
                employee.is_active,
            ),
        )

    def update_credentials(
        self,
        employee_id: EmployeeId,
        *,
        pin_hash: str | None = None,
        password_hash: str | None = None,
        pepper_version: int | None = None,
    ) -> None:
        """Sirrləri AYRICA yeniləyir — `None` verilən sahə TOXUNULMUR.

        `COALESCE` ilə: yalnız açıq verilən dəyər yazılır, qalanı olduğu kimi
        qalır. Bu, "PIN-i yenilədim, təsadüfən şifrəni sıfırladım" səhvini
        struktur olaraq bağlayır.
        """
        self._execute(
            """
            UPDATE employees SET
                pin_hash       = COALESCE(%s, pin_hash),
                password_hash  = COALESCE(%s, password_hash),
                pepper_version = COALESCE(%s, pepper_version)
            WHERE id = %s AND tenant_id = %s
            """,
            (pin_hash, password_hash, pepper_version, employee_id, self._tenant),
        )

    def rename_username(self, employee_id: EmployeeId, username: Username) -> None:
        """Giriş identifikatorunu dəyişir — AYRICA əməliyyat.

        `save()`-dən qəsdən ayrılıb: giriş adının dəyişməsi istifadəçinin
        sistemə girə bilməməsi ilə nəticələnə bilər, ona görə profil
        redaktəsinin yan təsiri kimi baş verməməlidir.
        """
        self._execute(
            "UPDATE employees SET username = %s WHERE id = %s AND tenant_id = %s",
            (str(username), employee_id, self._tenant),
        )

    # ------------------------------ köməkçi --------------------------------- #

    def _sync_overrides(self, employee: Employee) -> None:
        codes = [o.flag_code for o in employee.overrides]
        self._execute(
            "DELETE FROM user_permission_overrides WHERE user_id = %s AND flag_code <> ALL(%s)",
            (employee.id, codes or [""]),
        )
        for override in employee.overrides:
            self._execute(
                """
                INSERT INTO user_permission_overrides
                    (user_id, flag_code, effect, granted_by, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, flag_code) DO UPDATE SET
                    effect     = EXCLUDED.effect,
                    granted_by = EXCLUDED.granted_by,
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    employee.id,
                    override.flag_code,
                    override.effect.value,
                    override.granted_by,
                    override.expires_at,
                ),
            )

    def _sync_store_assignments(self, employee: Employee) -> None:
        assigned = list(employee.assigned_store_ids)
        if not assigned:
            self._execute(
                "DELETE FROM camera_operator_store_assignment WHERE operator_id = %s",
                (employee.id,),
            )
            return
        self._execute(
            """
            DELETE FROM camera_operator_store_assignment
            WHERE operator_id = %s AND store_id <> ALL(%s)
            """,
            (employee.id, assigned),
        )
        for store_id in assigned:
            self._execute(
                """
                INSERT INTO camera_operator_store_assignment
                    (operator_id, store_id, assigned_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (operator_id, store_id) DO NOTHING
                """,
                (employee.id, store_id, self._context.user_id or employee.id),
            )

    def _hydrate(self, row: dict[str, Any]) -> Employee:
        position_row = self._fetch_one(
            """
            SELECT id, tenant_id, code, name_az, priority, is_system,
                   is_camera_type, is_active
            FROM positions WHERE id = %s
            """,
            (row["position_id"],),
        )
        if position_row is None:  # pragma: no cover - FK bunu qoruyur
            msg = f"Rol tapılmadı: {row['position_id']}"
            raise LookupError(msg)

        position = position_from_row(position_row)
        flags = self._fetch_all(
            "SELECT flag_code FROM position_permissions WHERE position_id = %s AND granted",
            (position.id,),
        )
        apply_position_flags(position, [f["flag_code"] for f in flags])

        employee = employee_from_row(row, position)

        overrides = self._fetch_all(
            """
            SELECT flag_code, effect, granted_by, expires_at
            FROM user_permission_overrides WHERE user_id = %s
            """,
            (employee.id,),
        )
        apply_overrides(employee, overrides)

        if position.is_camera_type or position.code == "KAMERA_NEZARETCISI":
            stores = self._fetch_all(
                "SELECT store_id FROM camera_operator_store_assignment WHERE operator_id = %s",
                (employee.id,),
            )
            apply_store_assignments(employee, [s["store_id"] for s in stores])

        employee.discard_events()
        return employee


# --------------------------------------------------------------------------- #
# LeaveRequest
# --------------------------------------------------------------------------- #


class PostgresLeaveRequestRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, employee_id, store_id, leave_type_id,
               requested_time, requested_ntp_verified, return_claimed_time,
               actual_return_time, verified_at, verified_by, status,
               requested_minutes, delay_minutes, total_minutes,
               was_manual_override, escalated_at
        FROM leave_requests
    """

    _OPEN_STATUSES = (
        LeaveStatus.OUTSIDE.value,
        LeaveStatus.PENDING_RETURN_VERIFICATION.value,
        LeaveStatus.TIMEOUT_ESCALATED.value,
    )

    def get(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s",
            (request_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def find_open_for_employee(self, employee_id: EmployeeId) -> LeaveRequest | None:
        row = self._fetch_one(
            self._SELECT
            + """
            WHERE employee_id = %s AND tenant_id = %s AND status = ANY(%s)
            ORDER BY requested_time DESC LIMIT 1
            """,
            (employee_id, self._tenant, list(self._OPEN_STATUSES)),
        )
        return self._hydrate(row) if row else None

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[LeaveRequest]:
        """FAIL-SAFE: boş mağaza siyahısı → boş nəticə (bölmə 4)."""
        if not store_ids:
            return []
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND store_id = ANY(%s) AND status = %s
            ORDER BY return_claimed_time
            """,
            (
                self._tenant,
                list(store_ids),
                LeaveStatus.PENDING_RETURN_VERIFICATION.value,
            ),
        )
        return [self._hydrate(row) for row in rows]

    def list_due_for_timeout(
        self, tenant_id: TenantId, *, now: datetime, timeout_minutes: int
    ) -> list[LeaveRequest]:
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND status = %s AND escalated_at IS NULL
              AND return_claimed_time < %s - make_interval(mins => %s)
            """,
            (
                tenant_id,
                LeaveStatus.PENDING_RETURN_VERIFICATION.value,
                now,
                timeout_minutes,
            ),
        )
        return [self._hydrate(row) for row in rows]

    def monthly_used_minutes(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        """Aylıq istifadə olunmuş icazə dəqiqələri (bölmə 3 limiti üçün).

        `total_minutes` sütunu cərimə düsturunun nəticəsidir (`allowance +
        2 × delay`) — yəni işçinin AYLIQ BÜDCƏDƏN faktiki yediyi vaxt.
        Aqreqasiya SQL-də edilir: bir ayın sorğularını yaddaşa gətirib
        Python-da toplamaq 21 filial üçün mənasız yük olardı.
        """
        row = self._fetch_one(
            """
            SELECT COALESCE(sum(total_minutes), 0) AS used
            FROM leave_requests
            WHERE employee_id = %s
              AND tenant_id = %s
              AND status = 'VERIFIED'
              AND date_part('year', requested_time) = %s
              AND date_part('month', requested_time) = %s
            """,
            (employee_id, self._tenant, year, month),
        )
        return int(row["used"]) if row else 0

    def save(self, request: LeaveRequest) -> None:
        params = leave_request_to_params(request)
        self._execute(
            """
            INSERT INTO leave_requests
                (id, tenant_id, employee_id, store_id, leave_type_id,
                 requested_time, requested_ntp_verified, return_claimed_time,
                 actual_return_time, verified_at, verified_by, status,
                 requested_minutes, delay_minutes, total_minutes,
                 was_manual_override, escalated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                return_claimed_time = EXCLUDED.return_claimed_time,
                actual_return_time  = EXCLUDED.actual_return_time,
                verified_at         = EXCLUDED.verified_at,
                verified_by         = EXCLUDED.verified_by,
                status              = EXCLUDED.status,
                delay_minutes       = EXCLUDED.delay_minutes,
                total_minutes       = EXCLUDED.total_minutes,
                was_manual_override = EXCLUDED.was_manual_override,
                escalated_at        = EXCLUDED.escalated_at
            """,
            (
                params["id"],
                params["tenant_id"],
                params["employee_id"],
                params["store_id"],
                params["leave_type_id"],
                params["requested_time"],
                params["requested_ntp_verified"],
                params["return_claimed_time"],
                params["actual_return_time"],
                params["verified_at"],
                params["verified_by"],
                params["status"],
                params["requested_minutes"],
                params["delay_minutes"],
                params["total_minutes"],
                params["was_manual_override"],
                params["escalated_at"],
            ),
        )
        if request.override is not None:
            self._save_override(request)

    def _save_override(self, request: LeaveRequest) -> None:
        override = request.override
        assert override is not None
        status = (
            "PENDING_DUAL_CONTROL"
            if override.is_pending_approval
            else ("APPROVED" if override.approved_by else "AUTO_APPROVED")
        )
        self._execute(
            """
            INSERT INTO manual_time_overrides
                (tenant_id, leave_request_id, operator_id, employee_id,
                 system_time, overridden_time, delta_minutes, reason,
                 status, approved_by, approved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request.tenant_id,
                request.id,
                override.operator_id,
                request.employee_id,
                override.system_time,
                override.overridden_time,
                override.delta_minutes,
                override.reason,
                status,
                override.approved_by,
                override.approved_at,
            ),
        )

    def _hydrate(self, row: dict[str, Any]) -> LeaveRequest:
        override_row = self._fetch_one(
            """
            SELECT operator_id, system_time, overridden_time, reason,
                   delta_minutes, status, approved_by, approved_at
            FROM manual_time_overrides
            WHERE leave_request_id = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (row["id"],),
        )
        return leave_request_from_row(row, override_row)


# --------------------------------------------------------------------------- #
# AttendanceRecord
# --------------------------------------------------------------------------- #


class PostgresAttendanceRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, employee_id, store_id, work_date, check_in_status,
               requested_at, verified_at, verified_by, reject_reason, rejected_at,
               is_late, late_minutes, is_unauthorized_absence, ntp_verified,
               escalated_at, created_at
        FROM attendance_records
    """

    def get(self, record_id: AttendanceRecordId) -> AttendanceRecord | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s",
            (record_id, self._tenant),
        )
        return attendance_from_row(row) if row else None

    def get_for_day(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord | None:
        row = self._fetch_one(
            self._SELECT + " WHERE employee_id = %s AND work_date = %s AND tenant_id = %s",
            (employee_id, work_date, self._tenant),
        )
        return attendance_from_row(row) if row else None

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[AttendanceRecord]:
        if not store_ids:
            return []
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND store_id = ANY(%s) AND check_in_status = %s
            ORDER BY requested_at
            """,
            (self._tenant, list(store_ids), CheckInStatus.PENDING_VERIFICATION.value),
        )
        return [attendance_from_row(row) for row in rows]

    def list_expected_on(self, tenant_id: TenantId, work_date: date) -> list[AttendanceRecord]:
        rows = self._fetch_all(
            self._SELECT + " WHERE tenant_id = %s AND work_date = %s",
            (tenant_id, work_date),
        )
        return [attendance_from_row(row) for row in rows]

    def save(self, record: AttendanceRecord) -> None:
        params = attendance_to_params(record)
        self._execute(
            """
            INSERT INTO attendance_records
                (id, tenant_id, employee_id, store_id, work_date, check_in_status,
                 requested_at, verified_at, verified_by, reject_reason, rejected_at,
                 is_late, late_minutes, is_unauthorized_absence, ntp_verified,
                 escalated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, work_date) DO UPDATE SET
                check_in_status         = EXCLUDED.check_in_status,
                requested_at            = EXCLUDED.requested_at,
                verified_at             = EXCLUDED.verified_at,
                verified_by             = EXCLUDED.verified_by,
                reject_reason           = EXCLUDED.reject_reason,
                rejected_at             = EXCLUDED.rejected_at,
                is_late                 = EXCLUDED.is_late,
                late_minutes            = EXCLUDED.late_minutes,
                is_unauthorized_absence = EXCLUDED.is_unauthorized_absence,
                ntp_verified            = EXCLUDED.ntp_verified,
                escalated_at            = EXCLUDED.escalated_at
            """,
            (
                params["id"],
                params["tenant_id"],
                params["employee_id"],
                params["store_id"],
                params["work_date"],
                params["check_in_status"],
                params["requested_at"],
                params["verified_at"],
                params["verified_by"],
                params["reject_reason"],
                params["rejected_at"],
                params["is_late"],
                params["late_minutes"],
                params["is_unauthorized_absence"],
                params["ntp_verified"],
                params["escalated_at"],
            ),
        )


# --------------------------------------------------------------------------- #
# Fine
# --------------------------------------------------------------------------- #


class PostgresFineRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, employee_id, store_id, source, fine_type_id,
               leave_request_id, amount, fine_date, issued_by, photo_evidence_url,
               status, reversed_by, reversed_at, reversal_reason,
               appeal_window_closes_at, exported_period, created_at AS issued_at
        FROM fines
    """

    def get(self, fine_id: FineId) -> Fine | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s", (fine_id, self._tenant)
        )
        return fine_from_row(row) if row else None

    def list_for_employee_month(
        self, employee_id: EmployeeId, *, year: int, month: int
    ) -> list[Fine]:
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE employee_id = %s AND tenant_id = %s
              AND EXTRACT(YEAR FROM fine_date) = %s
              AND EXTRACT(MONTH FROM fine_date) = %s
            ORDER BY fine_date DESC
            """,
            (employee_id, self._tenant, year, month),
        )
        return [fine_from_row(row) for row in rows]

    def list_exportable(self, tenant_id: TenantId, *, now: datetime) -> list[Fine]:
        """Bölmə 6 LOCK MEXANİZMİ — DB-dəki `v_exportable_fines` ilə eyni şərt."""
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND status <> 'REVERSED'
              AND exported_period IS NULL
              AND appeal_window_closes_at <= %s
            ORDER BY fine_date
            """,
            (tenant_id, now),
        )
        return [fine_from_row(row) for row in rows]

    # -------------------------- Drive sübut sütunları ------------------------ #
    #
    # NİYƏ BUNLAR `save()`-dan KEÇMİR
    # ────────────────────────────────────────────────────────────────────────
    # `evidence_drive_*` sütunları (miqrasiya 002) cərimə YARADILAN anda hələ
    # məlum deyil — şəkil arxa planda yüklənir. Onları `Fine` entity-sinə
    # əlavə etmək domenə "yüklənmə vəziyyəti" anlayışı gətirərdi, halbuki bu,
    # tamamilə infrastruktur detalıdır: domen üçün sübut VAR, harada
    # saxlandığı isə onun qərarı deyil. Ona görə iki hədəfli UPDATE.

    def mark_evidence_pending(self, fine_id: FineId) -> None:
        """Şəkil növbəyə düşdü — `idx_fines_evidence_pending` bunu görür."""
        self._execute(
            """UPDATE fines SET evidence_upload_status = 'PENDING'
                WHERE id = %s AND tenant_id = %s""",
            (fine_id, self._tenant),
        )

    def attach_drive_evidence(
        self, fine_id: FineId, *, file_id: str, connection_id: UUID | None
    ) -> None:
        """Yükləmə bitdi — istinad sətrə yazılır.

        `photo_evidence_url` ÜZƏRİNDƏN YAZILMIR: orada növbə açarı qalır və
        o, hansı lokal yükləmənin bu sətri doldurduğunu göstərən yeganə izdir
        (miqrasiya 002 başlığı: sütun məhz buna görə silinmir).
        """
        self._execute(
            """UPDATE fines
                  SET evidence_drive_file_id = %s,
                      evidence_drive_connection_id = %s,
                      evidence_upload_status = 'SYNCED'
                WHERE id = %s AND tenant_id = %s""",
            (file_id, connection_id, fine_id, self._tenant),
        )

    def save(self, fine: Fine) -> None:
        params = fine_to_params(fine)
        self._execute(
            """
            INSERT INTO fines
                (id, tenant_id, employee_id, store_id, source, fine_type_id,
                 leave_request_id, amount, fine_date, issued_by,
                 photo_evidence_url, status, reversed_by, reversed_at,
                 reversal_reason, appeal_window_closes_at, exported_period)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                amount          = EXCLUDED.amount,
                status          = EXCLUDED.status,
                reversed_by     = EXCLUDED.reversed_by,
                reversed_at     = EXCLUDED.reversed_at,
                reversal_reason = EXCLUDED.reversal_reason,
                exported_period = EXCLUDED.exported_period
            """,
            (
                params["id"],
                params["tenant_id"],
                params["employee_id"],
                params["store_id"],
                params["source"],
                params["fine_type_id"],
                params["leave_request_id"],
                params["amount"],
                params["fine_date"],
                params["issued_by"],
                params["photo_evidence_url"],
                params["status"],
                params["reversed_by"],
                params["reversed_at"],
                params["reversal_reason"],
                params["appeal_window_closes_at"],
                params["exported_period"],
            ),
        )


__all__ = [
    "PostgresAttendanceRepository",
    "PostgresEmployeeRepository",
    "PostgresFineRepository",
    "PostgresLeaveRequestRepository",
    "PostgresPositionRepository",
]
