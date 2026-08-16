"""Növbə dəyişmə, gündəlik tabel və cərimə etirazı repository-ləri — Faza 5.

    PostgresShiftSwapRepository          — `shift_swap_requests`
    PostgresDailyAttendanceSheetRepository — `daily_attendance_sheets` + `_lines`
    PostgresAttendanceFactProvider       — tabelin ön-doldurma faktları
    PostgresFineAppealRepository         — `fine_appeals`

──────────────────────────────────────────────────────────────────────────────
NİYƏ `config_repositories.py`-DAN AYRI
──────────────────────────────────────────────────────────────────────────────
Oradakılar SKALYAR konfiqurasiya oxuyucularıdır (limit, toggle, off-day).
Buradakılar AQREQAT bərpa edir — hadisə toplayan, vəziyyət maşını olan
obyektlər. İki fərqli məsuliyyəti bir faylda saxlamaq həmin faylı 1500 sətrə
çatdırardı.

──────────────────────────────────────────────────────────────────────────────
BƏRPA EDİLƏN AQREQAT HADİSƏ YAYMIR
──────────────────────────────────────────────────────────────────────────────
`ShiftSwapRequest` və `FineAppeal` konstruktorları `emit_created_event=False`
ilə çağırılır. Onsuz hər `get()` çağırışı "yeni sorğu göndərildi" hadisəsi
yaradardı və HR eyni bildirişi hər ekran yeniləməsində alardı.

──────────────────────────────────────────────────────────────────────────────
FAKT PROVAYDERİ NİYƏ TƏK SORĞUDUR
──────────────────────────────────────────────────────────────────────────────
Tabelin ön-doldurulması üç mənbədən (davamiyyət + açıq icazə + növbə planı)
məlumat tələb edir. Use case bunları ayrı-ayrı repo çağırışları ilə yığsaydı,
30 işçilik mağazada 90 sorğu olardı. Burada hamısı bir `LEFT JOIN`-dur.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from src.domain.entities.appeal import AppealStatus, FineAppeal
from src.domain.entities.attendance_sheet import (
    AttendanceFact,
    AutoAttendanceStatus,
    DailyAttendanceSheet,
    SheetLine,
)
from src.domain.entities.shift import ShiftSwapRequest, SwapStatus
from src.domain.value_objects.money import Money
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import (
        AppealId,
        EmployeeId,
        FineId,
        ShiftSwapRequestId,
        StoreId,
        TenantId,
    )


# --------------------------------------------------------------------------- #
# ShiftSwapRepository
# --------------------------------------------------------------------------- #


class PostgresShiftSwapRepository(_BaseRepository):
    """`shift_swap_requests` (bölmə 3)."""

    _SELECT = """
        SELECT s.id, s.tenant_id, s.employee_id, s.target_date, s.requested_mode_id,
               s.reason, s.status, s.manager_note, s.manager_id, s.decided_by,
               s.decision_reason, s.decided_at, s.created_at, e.store_id
        FROM shift_swap_requests s
        JOIN employees e ON e.id = s.employee_id
    """

    def get(self, request_id: ShiftSwapRequestId) -> ShiftSwapRequest | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE s.id = %s AND s.tenant_id = %s",
            (request_id, self._tenant),
        )
        return _row_to_swap(row) if row else None

    def list_pending(
        self, tenant_id: TenantId, *, store_id: StoreId | None = None
    ) -> list[ShiftSwapRequest]:
        clauses = ["s.tenant_id = %s", "s.status = 'PENDING_APPROVAL'"]
        params: list[Any] = [tenant_id]
        if store_id is not None:
            clauses.append("e.store_id = %s")
            params.append(store_id)

        rows = self._fetch_all(
            f"{self._SELECT} WHERE {' AND '.join(clauses)} ORDER BY s.created_at",
            tuple(params),
        )
        return [_row_to_swap(row) for row in rows]

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int = 50
    ) -> list[ShiftSwapRequest]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE s.employee_id = %s AND s.tenant_id = %s
            ORDER BY s.created_at DESC
            LIMIT %s
            """,
            (employee_id, self._tenant, limit),
        )
        return [_row_to_swap(row) for row in rows]

    def find_open_for_date(
        self, employee_id: EmployeeId, target_date: date
    ) -> ShiftSwapRequest | None:
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE s.employee_id = %s AND s.target_date = %s
              AND s.tenant_id = %s AND s.status = 'PENDING_APPROVAL'
            """,
            (employee_id, target_date, self._tenant),
        )
        return _row_to_swap(row) if row else None

    def save(self, request: ShiftSwapRequest) -> None:
        self._execute(
            """
            INSERT INTO shift_swap_requests
                (id, tenant_id, employee_id, target_date, requested_mode_id,
                 reason, status, manager_note, manager_id, decided_by,
                 decision_reason, decided_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status          = EXCLUDED.status,
                    manager_note    = EXCLUDED.manager_note,
                    manager_id      = EXCLUDED.manager_id,
                    decided_by      = EXCLUDED.decided_by,
                    decision_reason = EXCLUDED.decision_reason,
                    decided_at      = EXCLUDED.decided_at
            """,
            (
                request.id,
                request.tenant_id,
                request.employee_id,
                request.target_date,
                request.requested_mode_id,
                request.reason,
                request.status.value,
                request.manager_note,
                request.manager_id,
                request.decided_by,
                request.decision_reason,
                request.decided_at,
                request.created_at,
            ),
        )


def _row_to_swap(row: dict[str, Any]) -> ShiftSwapRequest:
    return ShiftSwapRequest(
        request_id=row["id"],
        tenant_id=row["tenant_id"],
        employee_id=row["employee_id"],
        store_id=row.get("store_id"),
        target_date=row["target_date"],
        requested_mode_id=row["requested_mode_id"],
        reason=row["reason"],
        created_at=row["created_at"],
        status=SwapStatus(row["status"]),
        manager_note=row["manager_note"],
        manager_id=row["manager_id"],
        decided_by=row["decided_by"],
        decision_reason=row["decision_reason"],
        decided_at=row["decided_at"],
        emit_created_event=False,
    )


# --------------------------------------------------------------------------- #
# DailyAttendanceSheetRepository
# --------------------------------------------------------------------------- #


class PostgresDailyAttendanceSheetRepository(_BaseRepository):
    """`daily_attendance_sheets` + `daily_attendance_sheet_lines` (bölmə 3)."""

    _SELECT = """
        SELECT id, tenant_id, store_id, sheet_date, is_confirmed,
               confirmed_by, confirmed_at, manager_note
        FROM daily_attendance_sheets
    """

    def get_for_day(self, store_id: StoreId, sheet_date: date) -> DailyAttendanceSheet | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE store_id = %s AND sheet_date = %s AND tenant_id = %s",
            (store_id, sheet_date, self._tenant),
        )
        if row is None:
            return None
        return self._hydrate(row)

    def list_unconfirmed(self, tenant_id: TenantId, *, up_to: date) -> list[DailyAttendanceSheet]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND sheet_date <= %s AND NOT is_confirmed
            ORDER BY sheet_date DESC, store_id
            """,
            (tenant_id, up_to),
        )
        return [self._hydrate(row) for row in rows]

    def save(self, sheet: DailyAttendanceSheet) -> None:
        """Başlıq + sətirlər BİR tranzaksiyada.

        Sətirlər tam əvəzlənir (`DELETE` + `INSERT`), çünki ön-doldurma hər
        açılışda dəyişə bilir və hansı sətrin yeni, hansının köhnə olduğunu
        ayırmaq sətir-sətir müqayisə tələb edərdi — 30 sətir üçün bu, əlavə
        mürəkkəblikdən başqa bir şey vermir.
        """
        self._execute(
            """
            INSERT INTO daily_attendance_sheets
                (id, tenant_id, store_id, sheet_date, is_confirmed,
                 confirmed_by, confirmed_at, manager_note, mismatch_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (store_id, sheet_date) DO UPDATE
                SET is_confirmed   = EXCLUDED.is_confirmed,
                    confirmed_by   = EXCLUDED.confirmed_by,
                    confirmed_at   = EXCLUDED.confirmed_at,
                    manager_note   = EXCLUDED.manager_note,
                    mismatch_count = EXCLUDED.mismatch_count
            """,
            (
                sheet.id,
                sheet.tenant_id,
                sheet.store_id,
                sheet.sheet_date,
                sheet.is_confirmed,
                sheet.confirmed_by,
                sheet.confirmed_at,
                sheet.manager_note,
                sheet.mismatch_count,
            ),
        )

        # `ON CONFLICT` mövcud sətri saxladığı üçün id dəyişmiş ola bilər —
        # sətirləri həmişə FAKTİKİ id ilə yazırıq.
        row = self._fetch_one(
            "SELECT id FROM daily_attendance_sheets WHERE store_id = %s AND sheet_date = %s",
            (sheet.store_id, sheet.sheet_date),
        )
        sheet_id = row["id"] if row else sheet.id

        self._execute(
            "DELETE FROM daily_attendance_sheet_lines WHERE sheet_id = %s",
            (sheet_id,),
        )
        for line in sheet.lines:
            self._execute(
                """
                INSERT INTO daily_attendance_sheet_lines
                    (sheet_id, employee_id, auto_status, planned_off,
                     has_mismatch, manager_note)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    sheet_id,
                    line.employee_id,
                    line.auto_status.value,
                    line.planned_off,
                    line.has_mismatch,
                    line.manager_note,
                ),
            )

    def _hydrate(self, row: dict[str, Any]) -> DailyAttendanceSheet:
        line_rows = self._fetch_all(
            """
            SELECT employee_id, auto_status, planned_off, manager_note
            FROM daily_attendance_sheet_lines
            WHERE sheet_id = %s
            ORDER BY employee_id
            """,
            (row["id"],),
        )
        lines = [
            SheetLine(
                employee_id=line["employee_id"],
                auto_status=AutoAttendanceStatus(line["auto_status"]),
                planned_off=bool(line["planned_off"]),
                manager_note=line["manager_note"],
            )
            for line in line_rows
        ]
        return DailyAttendanceSheet(
            sheet_id=row["id"],
            tenant_id=row["tenant_id"],
            store_id=row["store_id"],
            sheet_date=row["sheet_date"],
            lines=lines,
            is_confirmed=bool(row["is_confirmed"]),
            confirmed_by=row["confirmed_by"],
            confirmed_at=row["confirmed_at"],
            manager_note=row["manager_note"],
        )


# --------------------------------------------------------------------------- #
# AttendanceFactProvider
# --------------------------------------------------------------------------- #


class PostgresAttendanceFactProvider(_BaseRepository):
    """Tabelin ön-doldurulması üçün faktlar — TƏK sorğu (modul başlığına bax)."""

    def facts_for(self, store_id: StoreId, work_date: date) -> list[AttendanceFact]:
        rows = self._fetch_all(
            """
            SELECT e.id                                   AS employee_id,
                   COALESCE(sa.is_off_day, FALSE)         AS planned_off,
                   ar.check_in_status                     AS check_in_status,
                   COALESCE(ar.is_late, FALSE)            AS is_late,
                   COALESCE(ar.late_minutes, 0)           AS late_minutes,
                   EXISTS (
                       SELECT 1 FROM leave_requests lr
                        WHERE lr.employee_id = e.id
                          AND lr.status IN ('OUTSIDE', 'PENDING_RETURN_VERIFICATION')
                          AND lr.requested_time::date = %s
                   )                                      AS is_outside
            FROM employees e
            LEFT JOIN shift_assignments sa
                   ON sa.employee_id = e.id AND sa.shift_date = %s
            LEFT JOIN attendance_records ar
                   ON ar.employee_id = e.id AND ar.work_date = %s
            WHERE e.store_id = %s AND e.tenant_id = %s AND e.is_active
            ORDER BY e.last_name, e.first_name
            """,
            (work_date, work_date, work_date, store_id, self._tenant),
        )

        # "Gün bitibmi" sualı SQL-də deyil, burada həll olunur: cavab çağırış
        # anından asılıdır və sorğunu determinstik saxlamaq testi asanlaşdırır.
        day_is_over = work_date < datetime.now(tz=UTC).date()

        facts: list[AttendanceFact] = []
        for row in rows:
            status = row["check_in_status"]
            facts.append(
                AttendanceFact(
                    employee_id=row["employee_id"],
                    planned_off=bool(row["planned_off"]),
                    has_verified_check_in=status == "VERIFIED",
                    is_pending_verification=status == "PENDING_VERIFICATION",
                    is_currently_outside=bool(row["is_outside"]),
                    is_late=bool(row["is_late"]),
                    late_minutes=int(row["late_minutes"] or 0),
                    day_is_over=day_is_over,
                )
            )
        return facts


# --------------------------------------------------------------------------- #
# FineAppealRepository
# --------------------------------------------------------------------------- #


class PostgresFineAppealRepository(_BaseRepository):
    """`fine_appeals` — 72-saatlıq etiraz (bölmə 4)."""

    _SELECT = """
        SELECT id, tenant_id, fine_id, employee_id, reason, status,
               decided_by, decision_note, decided_at, new_amount, created_at
        FROM fine_appeals
    """

    def get(self, appeal_id: AppealId) -> FineAppeal | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (appeal_id, self._tenant),
        )
        return _row_to_appeal(row) if row else None

    def get_for_fine(self, fine_id: FineId) -> FineAppeal | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE fine_id = %s AND tenant_id = %s",
            (fine_id, self._tenant),
        )
        return _row_to_appeal(row) if row else None

    def list_pending(self, tenant_id: TenantId) -> list[FineAppeal]:
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s AND status = 'PENDING' ORDER BY created_at",
            (tenant_id,),
        )
        return [_row_to_appeal(row) for row in rows]

    def list_undecided(self, tenant_id: TenantId) -> list[FineAppeal]:
        """QƏRARSIZ etirazlar — `PENDING` + `EXPIRED` (M-6).

        `idx_appeals_pending` yalnız `PENDING`-i əhatə edir, ona görə bu sorğu
        `(tenant_id, status)` üzrə adi indeks yolu ilə gedir. Ayrıca qismən
        indeks ƏLAVƏ EDİLMƏDİ: `EXPIRED` sətir SLA pozuntusudur, yəni sağlam
        quraşdırmada onlarla deyil, tək-tək olur — onun üçün indeks yazmaq
        problemi normallaşdırmaq olardı.
        """
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s"
            " AND status IN ('PENDING', 'EXPIRED') ORDER BY created_at",
            (tenant_id,),
        )
        return [_row_to_appeal(row) for row in rows]

    def list_for_employee(self, employee_id: EmployeeId, *, limit: int = 50) -> list[FineAppeal]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE employee_id = %s AND tenant_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (employee_id, self._tenant, limit),
        )
        return [_row_to_appeal(row) for row in rows]

    def save(self, appeal: FineAppeal) -> None:
        self._execute(
            """
            INSERT INTO fine_appeals
                (id, tenant_id, fine_id, employee_id, reason, status,
                 decided_by, decision_note, decided_at, new_amount, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status        = EXCLUDED.status,
                    decided_by    = EXCLUDED.decided_by,
                    decision_note = EXCLUDED.decision_note,
                    decided_at    = EXCLUDED.decided_at,
                    new_amount    = EXCLUDED.new_amount
            """,
            (
                appeal.id,
                appeal.tenant_id,
                appeal.fine_id,
                appeal.employee_id,
                appeal.reason,
                appeal.status.value,
                appeal.decided_by,
                appeal.decision_note,
                appeal.decided_at,
                appeal.new_amount.amount if appeal.new_amount is not None else None,
                appeal.created_at,
            ),
        )


def _row_to_appeal(row: dict[str, Any]) -> FineAppeal:
    raw_amount = row["new_amount"]
    return FineAppeal(
        appeal_id=row["id"],
        tenant_id=row["tenant_id"],
        fine_id=row["fine_id"],
        employee_id=row["employee_id"],
        reason=row["reason"],
        created_at=row["created_at"],
        status=AppealStatus(row["status"]),
        decided_by=row["decided_by"],
        decision_note=row["decision_note"],
        decided_at=row["decided_at"],
        new_amount=Money(raw_amount) if raw_amount is not None else None,
        emit_created_event=False,
    )


__all__ = [
    "PostgresAttendanceFactProvider",
    "PostgresDailyAttendanceSheetRepository",
    "PostgresFineAppealRepository",
    "PostgresShiftSwapRepository",
]
