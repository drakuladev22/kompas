"""Aylıq hesabat fakt-mənbəyi — SQL aqreqasiyası (bölmə 6) — Faza 6.

`MonthlyReportUseCase` sətirləri QURUR, amma rəqəmləri hesablamır: o,
`EmployeeAttendanceFacts` / `EmployeeSalesFacts` siyahısını hazır alır. Bu
modul həmin siyahıları verir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AQREQASİYA SQL-DƏDİR
──────────────────────────────────────────────────────────────────────────────
Use case-in öz şərhi: "Hesablamanı bura köçürmək 21 filialın bütün davamiyyət
qeydlərini yaddaşa yükləmək demək olardı." 235 işçi × 30 gün ≈ 7000 sətir
davamiyyət + 3000 sətir satış — hər ay, hər hesabat üçün. `GROUP BY` bunu
235 sətrə endirir.

──────────────────────────────────────────────────────────────────────────────
"NORMA İŞ GÜNLƏRİ" NƏDİR
──────────────────────────────────────────────────────────────────────────────
Bölmə 6 sütunu adlandırır, amma tərifini vermir. Burada seçilən təriflə:
**həmin ay üçün Shift Matrix-də iş günü kimi planlaşdırılmış günlərin sayı**.

Alternativ (təqvim iş günləri, 5/2) rədd edildi: mağazalar həftənin 7 günü
işləyir və növbə qrafiki fərdi olur — "ayda 22 iş günü" heç bir işçiyə uyğun
gəlmir. Plan yoxdursa (heç bir sətir) norma 0 olur və `actual_worked_days`
onu üstələyə bilər; bu, HR üçün "bu işçiyə plan qurulmayıb" siqnalıdır və
uydurma norma göstərməkdən daha dürüstdür.

──────────────────────────────────────────────────────────────────────────────
FAKTİKİ GÜN NİYƏ `attendance_records`-DAN GƏLİR
──────────────────────────────────────────────────────────────────────────────
Bölmə 6, FAYL 1: "Faktiki İşlənilən Gün Sayı (yuxarıdakı Morning Check-in
`🟢 Verified` qeydlərinə əsaslanır)". Yəni mənbə Gündəlik Tabel DEYİL —
tabel menecerin təsdiqidir, davamiyyət qeydi isə kamera-təsdiqli faktdır.
Tabel təsdiqlənməsə belə maaş hesablanmalıdır.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.application.use_cases.reporting import (
    EmployeeAttendanceFacts,
    EmployeeSalesFacts,
)
from src.domain.value_objects.money import Money
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import StoreId, TenantId


class PostgresReportFactProvider(_BaseRepository):
    """İki hesabatın rəqəm mənbəyi."""

    # ------------------------------- FAYL 1 ---------------------------------- #

    def attendance_facts(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeeAttendanceFacts]:
        """Davamiyyət Hesabatının sətir faktları.

        Dörd sayğac dörd fərqli mənbədən gəlir və hamısı `LEFT JOIN LATERAL`
        ilə bir sorğuda toplanır — işçi siyahısı ƏSASDIR, sayğacı olmayan
        işçi sıfırla görünür (sətirdən düşmür).
        """
        rows = self._fetch_all(
            """
            SELECT e.id                              AS employee_id,
                   (e.first_name || ' ' || e.last_name) AS full_name,
                   COALESCE(s.name, '—')             AS store_name,
                   COALESCE(p.name_az, '—')          AS position_name,
                   COALESCE(plan.norm_days, 0)       AS norm_work_days,
                   COALESCE(plan.off_days, 0)        AS off_days,
                   COALESCE(fact.worked_days, 0)     AS actual_worked_days,
                   COALESCE(fact.absences, 0)        AS unauthorized_absences
            FROM employees e
            LEFT JOIN stores s    ON s.id = e.store_id
            LEFT JOIN positions p ON p.id = e.position_id
            LEFT JOIN LATERAL (
                SELECT count(*) FILTER (WHERE NOT sa.is_off_day) AS norm_days,
                       count(*) FILTER (WHERE sa.is_off_day)     AS off_days
                FROM shift_assignments sa
                WHERE sa.employee_id = e.id
                  AND sa.shift_date BETWEEN %s AND %s
            ) plan ON TRUE
            LEFT JOIN LATERAL (
                SELECT count(*) FILTER (WHERE ar.check_in_status = 'VERIFIED')
                           AS worked_days,
                       count(*) FILTER (WHERE ar.is_unauthorized_absence)
                           AS absences
                FROM attendance_records ar
                WHERE ar.employee_id = e.id
                  AND ar.work_date BETWEEN %s AND %s
            ) fact ON TRUE
            WHERE e.tenant_id = %s
              AND (%s::uuid IS NULL OR e.store_id = %s::uuid)
            ORDER BY s.name NULLS LAST, e.last_name, e.first_name
            """,
            (start, end, start, end, tenant_id, store_id, store_id),
        )
        return [
            EmployeeAttendanceFacts(
                employee_id=row["employee_id"],
                full_name=row["full_name"],
                store_name=row["store_name"],
                position_name=row["position_name"],
                norm_work_days=int(row["norm_work_days"]),
                actual_worked_days=int(row["actual_worked_days"]),
                off_days=int(row["off_days"]),
                unauthorized_absences=int(row["unauthorized_absences"]),
            )
            for row in rows
        ]

    # ------------------------------- FAYL 2 ---------------------------------- #

    def sales_facts(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeeSalesFacts]:
        """Premiya & Cərimə Hesabatının satış tərəfi.

        `points_ledger`-dən YALNIZ `ACTIVE` sətirlər sayılır: `REVERSED`
        (uğurlu xal etirazı) və `CORRECTED` xallar premiyaya getməməlidir —
        cərimə tərəfindəki `REVERSED` qaydası ilə eyni məntiq (bölmə 6).
        """
        rows = self._fetch_all(
            """
            SELECT e.id                             AS employee_id,
                   (e.first_name || ' ' || e.last_name) AS full_name,
                   COALESCE(s.name, '—')            AS store_name,
                   COALESCE(sales.gross, 0)         AS gross_sales,
                   COALESCE(points.earned, 0)       AS earned_points
            FROM employees e
            LEFT JOIN stores s ON s.id = e.store_id
            LEFT JOIN LATERAL (
                SELECT COALESCE(sum(st.gross_amount), 0) AS gross
                FROM sales_transactions st
                WHERE st.employee_id = e.id
                  AND st.transaction_date BETWEEN %s AND %s
            ) sales ON TRUE
            LEFT JOIN LATERAL (
                SELECT COALESCE(sum(pl.delta_points), 0) AS earned
                FROM points_ledger pl
                WHERE pl.employee_id = e.id
                  AND pl.status = 'ACTIVE'
                  AND pl.created_at::date BETWEEN %s AND %s
            ) points ON TRUE
            WHERE e.tenant_id = %s
              AND (%s::uuid IS NULL OR e.store_id = %s::uuid)
            ORDER BY s.name NULLS LAST, e.last_name, e.first_name
            """,
            (start, end, start, end, tenant_id, store_id, store_id),
        )
        return [
            EmployeeSalesFacts(
                employee_id=row["employee_id"],
                full_name=row["full_name"],
                store_name=row["store_name"],
                gross_sales=Money(_as_decimal(row["gross_sales"])),
                earned_points=int(row["earned_points"]),
            )
            for row in rows
        ]


def _as_decimal(raw: Any) -> Decimal:
    """`sum()` `None`, `int` və ya `Decimal` qaytara bilər — hamısını normallaşdırır."""
    if raw is None:
        return Decimal("0.00")
    if isinstance(raw, Decimal):
        return raw
    return Decimal(str(raw))


__all__ = ["PostgresReportFactProvider"]
