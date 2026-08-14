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

──────────────────────────────────────────────────────────────────────────────
`plan_facts` NİYƏ AQREQAT DEYİL, GÜN-GÜN DETALDIR (Faza 7)
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı iki metod `GROUP BY` ilə 235 sətrə enir; `plan_facts` isə hər işçi
üçün hər günü ayrıca qaytarır. Bu, yuxarıdakı əsaslandırmaya ZİDD DEYİL —
başqa sualı cavablandırır:

  * "neçə iş günü planlaşdırılıb?" — SAY, `count(*)` kifayətdir.
  * "neçə NORMA SAAT planlaşdırılıb?" — hər günün ÖZ iş rejimi lazımdır,
    çünki rejim gün-gün dəyişə bilər (səhər növbəsindən gecə növbəsinə keçid)
    və hər rejimin saat müddəti fərqlidir.

Cəmi SQL-də (`sum(end_time - start_time)`) hesablamaq mümkün idi, lakin rədd
edildi: gecə növbəsində fərq MƏNFİ çıxır (06:00 − 22:00) və hüquqi gündəlik
tavanla sıxılma da SQL-də təkrarlanmalı olardı. Hər ikisi artıq domendədir
(`TimeRange.duration`, `work_norm.calculate_work_norm`) — SQL-də ikinci
nüsxəsi iki mənbə yaradardı.

Həcm hesabı: 31 gün × 235 işçi ≈ 7000 sətir, yəni bir ekran yüklənməsinin
oxuduğu adi cədvəl ölçüsü. Aralığın uzunluğunu isə ROOT parametri cilovlayır
(`REPORT_RANGE_MAX_DAYS`, seed: migrations/043).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.application.use_cases.reporting import (
    EmployeeAttendanceFacts,
    EmployeePlanFacts,
    EmployeeSalesFacts,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import DEFAULT_TIMEZONE, TimeRange
from src.domain.work_norm import EmploymentWindow, PlannedDay
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId


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

    # -------------------- FAYL 1 — DİNAMİK NORMA (Faza 7) -------------------- #

    def plan_facts(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeePlanFacts]:
        """Shift Matrix planı + məşğulluq pəncərəsi — işçi başına bir struktur.

        ──────────────────────────────────────────────────────────────────────
        `LEFT JOIN`, `INNER JOIN` YOX
        ──────────────────────────────────────────────────────────────────────
        Planı olmayan işçi də SƏTİR QAYTARIR (`shift_date IS NULL`): onun
        norması 0-dır və bu, HR üçün "plan qurulmayıb" siqnalıdır. `INNER
        JOIN` həmin işçini siyahıdan tamamilə çıxarardı və problem GÖRÜNMƏZ
        qalardı.

        ──────────────────────────────────────────────────────────────────────
        `work_modes` SÜZÜLMÜR (`is_active` ŞƏRTİ YOXDUR) — QƏSDƏN
        ──────────────────────────────────────────────────────────────────────
        Deaktiv edilmiş iş rejimi KEÇMİŞ növbələrdə oxunmağa davam etməlidir
        (`catalogs.py` soft delete əsaslandırması). Aktivlik şərti qoyulsaydı,
        rejim deaktiv edilən kimi keçmiş ayların norma saatı sükutla dəyişərdi
        — yəni artıq imzalanmış hesabat yenidən çıxarılanda FƏRQLİ rəqəm
        verərdi.

        ──────────────────────────────────────────────────────────────────────
        MƏŞĞULLUQ PƏNCƏRƏSİ VƏ SAAT QURŞAĞI
        ──────────────────────────────────────────────────────────────────────
        `deactivated_at` `TIMESTAMPTZ`-dir; onu birbaşa `::date`-ə çevirmək
        sessiya qurşağından asılı olardı və UTC-də gecə saat 22:00-da çıxan
        işçinin son iş günü BİR GÜN İRƏLİ sürüşərdi. Ona görə mağazanın öz
        qurşağı tətbiq olunur — `overtime_repositories.py`-dakı eyni naxış.

        `hire_date` `DATE`-dir və çevrilməyə ehtiyacı yoxdur.
        """
        rows = self._fetch_all(
            """
            SELECT e.id                                  AS employee_id,
                   e.hire_date                           AS hire_date,
                   e.is_active                           AS is_active,
                   (e.deactivated_at AT TIME ZONE COALESCE(s.timezone, %s))::date
                                                         AS ended_on,
                   sa.shift_date                         AS shift_date,
                   sa.is_off_day                         AS is_off_day,
                   wm.start_time                         AS start_time,
                   wm.end_time                           AS end_time
            FROM employees e
            LEFT JOIN stores s ON s.id = e.store_id
            LEFT JOIN shift_assignments sa
                   ON sa.employee_id = e.id
                  AND sa.shift_date BETWEEN %s AND %s
            LEFT JOIN work_modes wm ON wm.id = sa.work_mode_id
            WHERE e.tenant_id = %s
              AND (%s::uuid IS NULL OR e.store_id = %s::uuid)
            ORDER BY e.id, sa.shift_date
            """,
            (DEFAULT_TIMEZONE, start, end, tenant_id, store_id, store_id),
        )

        plans: dict[EmployeeId, list[PlannedDay]] = {}
        windows: dict[EmployeeId, EmploymentWindow] = {}
        for row in rows:
            employee_id: EmployeeId = row["employee_id"]
            if employee_id not in windows:
                windows[employee_id] = EmploymentWindow(
                    started_on=row["hire_date"],
                    # AKTİV işçinin bitmə tarixi YOXDUR: `deactivated_at`
                    # köhnə bir dayandırmadan qalmış ola bilər və onu son
                    # gün saymaq işçini öz normasından məhrum edərdi.
                    ended_on=None if row["is_active"] else row["ended_on"],
                )
                plans[employee_id] = []
            if row["shift_date"] is None:
                continue
            plans[employee_id].append(
                PlannedDay(
                    day=row["shift_date"],
                    is_off_day=bool(row["is_off_day"]),
                    schedule=_time_range(row["start_time"], row["end_time"]),
                )
            )

        return [
            EmployeePlanFacts(
                employee_id=employee_id,
                planned_days=tuple(plans[employee_id]),
                employment=window,
            )
            for employee_id, window in windows.items()
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


def _time_range(start: Any, end: Any) -> TimeRange | None:
    """`work_modes` saatlarını `TimeRange`-ə çevirir.

    `None` qaytarılan İKİ hal var və hər ikisi qanunidir:
      * növbəyə iş rejimi TƏYİN EDİLMƏYİB (`work_mode_id IS NULL` — istirahət
        günü və ya sərbəst gün);
      * rejimin başlanğıcı və bitməsi EYNİDİR — `TimeRange` bunu qəbul etmir
        (24 saatlıq növbə ilə 0 saatlıq növbə fərqləndirilə bilməzdi).

    Hər iki halda gündəlik norma hüquqi normadan götürülür
    (`work_norm.calculate_work_norm`) — hesabat çökmür, rəqəm uydurulmur.
    """
    if start is None or end is None or start == end:
        return None
    return TimeRange(start=start, end=end)


def _as_decimal(raw: Any) -> Decimal:
    """`sum()` `None`, `int` və ya `Decimal` qaytara bilər — hamısını normallaşdırır."""
    if raw is None:
        return Decimal("0.00")
    if isinstance(raw, Decimal):
        return raw
    return Decimal(str(raw))


__all__ = ["PostgresReportFactProvider"]
