"""İllik məzuniyyətin saxlama qatı (#28) — kompas1.md Faza 4.

`annual_leave_balances` + `annual_leave_requests` (migrations/037).

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — tətbiq səhvən owner rolu ilə qoşulsa da
izolyasiya qalır (layihənin bütün repo-larında eyni naxış).

──────────────────────────────────────────────────────────────────────────────
İKİ AYRI YARIŞ, İKİ AYRI DB QAPAĞI
──────────────────────────────────────────────────────────────────────────────
1. **BALANS MƏNFİYƏ DÜŞMƏSİN** — `consume()` UPSERT DEYİL, ŞƏRTLİ `UPDATE`-dir:

       UPDATE annual_leave_balances
          SET used_days = used_days + %s
        WHERE employee_id = %s AND tenant_id = %s AND year = %s
          AND used_days + %s <= entitled_days + carried_over_days

   və `rowcount` qaytarılır. İki paralel təsdiqdən yalnız biri 1 sətir
   yeniləyə bilir: PostgreSQL READ COMMITTED-də ikinci `UPDATE` birinci
   commit olunandan sonra şərti YENİDƏN qiymətləndirir və qalıq artıq
   çatmadığı üçün 0 sətir toxunur (`open_shift_repository.claim` naxışının
   eynisi). Tətbiq qatında "əvvəlcə oxu, sonra yaz" yoxlaması QƏRAR VERMİR —
   o, yalnız istifadəçiyə göstəriləcək izahı qurur.

2. **ÜST-ÜSTƏ DÜŞƏN TƏSDİQLƏNMİŞ ARALIQ** — `excl_annual_leave_no_overlap`
   (`EXCLUDE USING gist ... WHERE status = 'APPROVED'`). Bu qapaq tamamilə
   DB-dədir və `save()` onun pozuntusunu TUTUR: xam `psycopg` xətası
   istifadəçiyə ÇATMAMALIDIR — o, texniki nasazlıq deyil, izah edilə bilən
   İŞ QAYDASIDIR (`PostgresOpenShiftPostingRepository.post` ilə eyni qərar).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `delete()` YOXDUR
──────────────────────────────────────────────────────────────────────────────
Balans PUL dəyəri daşıyır (istifadə edilməmiş gün kompensasiya oluna bilər),
məzuniyyət qeydi isə mübahisədə sübutdur. Metodu yazıb DB-nin/siyasətin rədd
etməsinə buraxmaq "niyə işləmir?" sualı yaradardı — ona görə metod
ÜMUMİYYƏTLƏ yoxdur (`field_report_repositories.py` ilə eyni qərar).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from psycopg import errors as pg_errors

from src.application.use_cases.annual_leave import AnnualLeaveError
from src.domain.annual_leave_rules import AnnualLeaveRolloverInput
from src.domain.entities.annual_leave import (
    AnnualLeaveBalance,
    AnnualLeaveRequest,
    AnnualLeaveStatus,
)
from src.domain.value_objects.identifiers import (
    AnnualLeaveBalanceId,
    AnnualLeaveRequestId,
    EmployeeId,
    TenantId,
)
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date

#: `list_rollover_inputs` — AKTİV işçi + işə qəbul + KEÇƏN ilin qalığı.
#:
#: `LEFT JOIN` MƏCBURİDİR: keçən il balans sətri OLMAYAN işçi (yeni işə
#: düşən, və ya sistemin ilk ili) `INNER JOIN` ilə nəticədən TAM DÜŞƏRDİ və
#: onun bu il üçün balansı HEÇ VAXT yaranmazdı.
#:
#: Qalıq SQL-də hesablanır (`entitled + carried_over - used`): 235 işçinin
#: sətrini yaddaşa gətirib Python-da çıxmaq gecə işi üçün mənasız yükdür
#: (`count_claims_in_month` ilə eyni qərar). `GREATEST(0, ...)` isə tarixi
#: idxaldan gələ biləcək uyğunsuz sətrin mənfi qalıq verməsini kəsir.
_ROLLOVER_INPUTS_QUERY: Final = """
    SELECT e.id AS employee_id,
           e.hire_date AS hire_date,
           GREATEST(
               0,
               COALESCE(b.entitled_days, 0)
             + COALESCE(b.carried_over_days, 0)
             - COALESCE(b.used_days, 0)
           ) AS previous_available_days
      FROM employees e
      LEFT JOIN annual_leave_balances b
             ON b.employee_id = e.id
            AND b.tenant_id = e.tenant_id
            AND b.year = %s
     WHERE e.tenant_id = %s
       AND e.is_active
     ORDER BY e.id
"""


class PostgresAnnualLeaveBalanceRepository(_BaseRepository):
    """`annual_leave_balances` — haqq, istifadə, köçürmə."""

    _SELECT = """
        SELECT id, tenant_id, employee_id, year,
               entitled_days, used_days, carried_over_days, updated_by
        FROM annual_leave_balances
    """

    # -------------------------------- oxu ------------------------------------- #

    def get(self, employee_id: EmployeeId, *, year: int) -> AnnualLeaveBalance | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE employee_id = %s AND tenant_id = %s AND year = %s",
            (employee_id, self._tenant, year),
        )
        return _row_to_balance(row) if row else None

    def list_for_year(
        self, tenant_id: TenantId, *, year: int, limit: int = 500
    ) -> list[AnnualLeaveBalance]:
        """`idx_annual_leave_balances_year` sorğusu — HR panelinin siyahısı."""
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND year = %s
            ORDER BY employee_id
            LIMIT %s
            """,
            (self._require_matching_tenant(tenant_id), year, limit),
        )
        return [_row_to_balance(row) for row in rows]

    def list_rollover_inputs(
        self, tenant_id: TenantId, *, year: int
    ) -> list[AnnualLeaveRolloverInput]:
        """İl dönümü işinin girişi (bax `_ROLLOVER_INPUTS_QUERY` şərhi)."""
        rows = self._fetch_all(
            _ROLLOVER_INPUTS_QUERY, (year - 1, self._require_matching_tenant(tenant_id))
        )
        return [
            AnnualLeaveRolloverInput(
                employee_id=EmployeeId(row["employee_id"]),
                hire_date=row["hire_date"],
                previous_available_days=Decimal(str(row["previous_available_days"])),
            )
            for row in rows
        ]

    # -------------------------------- yazı ------------------------------------ #

    def set_entitlement(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        year: int,
        entitled_days: Decimal,
        carried_over_days: Decimal,
        updated_by: EmployeeId | None,
    ) -> bool:
        """İDEMPOTENT UPSERT — haqqı TƏYİN edir, ARTIRMIR.

        `DO UPDATE SET ... = EXCLUDED....` (yəni `+=` YOX): planlayıcı
        at-least-once icra edir və toplama yazılsaydı ikinci icra balansı
        ikiqat artırardı (`job_runner.py` başlığı: "reyestrin müqaviləsi").

        `WHERE` ŞƏRTİ ƏL İLƏ DÜZƏLİŞİ QORUYUR: sistem yazısı (`updated_by IS
        NULL`) yalnız sistem tərəfindən yazılmış sətri yeniləyir. HR-ın
        düzəltdiyi rəqəm gecə işi tərəfindən sükutla geri qaytarılsaydı,
        "düzəltdim, səhər yenə köhnə dəyər" qüsuru yaranardı və səbəbi heç
        bir logdan görünməzdi.

        `used_days` TOXUNULMUR — o, yalnız `consume`/`release` ilə dəyişir.
        """
        affected = self._execute(
            """
            INSERT INTO annual_leave_balances
                (tenant_id, employee_id, year, entitled_days, carried_over_days, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, employee_id, year) DO UPDATE
               SET entitled_days     = EXCLUDED.entitled_days,
                   carried_over_days = EXCLUDED.carried_over_days,
                   updated_by        = EXCLUDED.updated_by
             WHERE annual_leave_balances.updated_by IS NULL
                OR EXCLUDED.updated_by IS NOT NULL
            """,
            (
                # SAAS-1 (birinci partiya): BALANS = PUL — səhv `tenant_id` ilə
                # yazı RLS tərəfindən rədd edilər, lakin çağıran "0 sətir
                # yeniləndi" cavabını "belə işçi yoxdur" kimi oxuyardı.
                self._require_matching_tenant(tenant_id),
                employee_id,
                year,
                entitled_days,
                carried_over_days,
                updated_by,
            ),
        )
        return affected == 1

    def consume(self, *, employee_id: EmployeeId, year: int, days: Decimal) -> bool:
        """ŞƏRTLİ `UPDATE` — mənfi balans STRUKTUR OLARAQ mümkün deyil.

        Şərt SORĞUNUN İÇİNDƏDİR (bax modul başlığı). `RETURNING` işlədilmir:
        bizə yalnız "yenilədimmi?" cavabı lazımdır və `rowcount` onu verir.
        """
        affected = self._execute(
            """
            UPDATE annual_leave_balances
               SET used_days = used_days + %s
             WHERE employee_id = %s
               AND tenant_id = %s
               AND year = %s
               AND used_days + %s <= entitled_days + carried_over_days
            """,
            (days, employee_id, self._tenant, year, days),
        )
        return affected == 1

    def release(self, *, employee_id: EmployeeId, year: int, days: Decimal) -> bool:
        """Ləğv edilmiş məzuniyyətin gününü geri qaytarır.

        `GREATEST(0, ...)`: təkrar ləğv (və ya planlayıcının təkrar icrası)
        `used_days`-i mənfiyə salmamalıdır — DB `CHECK (used_days >= 0)` onu
        onsuz da rədd edərdi, lakin istifadəçi anlaşılmaz sürücü xətası
        görərdi.
        """
        affected = self._execute(
            """
            UPDATE annual_leave_balances
               SET used_days = GREATEST(0, used_days - %s)
             WHERE employee_id = %s
               AND tenant_id = %s
               AND year = %s
            """,
            (days, employee_id, self._tenant, year),
        )
        return affected == 1

    def expire_carryover(self, *, tenant_id: TenantId, year: int) -> int:
        """ "İstifadə et ya itir" — istifadə olunmamış köçürməni sıfırlayır.

        `LEAST(carried_over_days, used_days)` İDEMPOTENTDİR: ikinci icrada
        `carried_over_days > used_days` şərti artıq doğru olmadığı üçün heç
        bir sətir toxunulmur. Düstur eyni zamanda `chk_annual_leave_balance_
        not_negative`-i poza bilmir (bax `AnnualLeaveBalance.expire_carryover`).

        KÖÇÜRÜLMÜŞ GÜN ƏVVƏL XƏRCLƏNİR fərziyyəsi buradadır və qəsdəndir:
        `used_days` tək sütundur, hansı gününün hansı "səbətdən" gəldiyini
        saxlamır. Əks fərziyyə (əvvəl cari il) işçinin ziyanına olardı —
        köçürülmüş günlər həmişə tam itərdi.
        """
        return self._execute(
            """
            UPDATE annual_leave_balances
               SET carried_over_days = LEAST(carried_over_days, used_days)
             WHERE tenant_id = %s
               AND year = %s
               AND carried_over_days > used_days
            """,
            (self._require_matching_tenant(tenant_id), year),
        )


class PostgresAnnualLeaveRequestRepository(_BaseRepository):
    """`annual_leave_requests` — sorğu, təsdiq, rədd, ləğv."""

    _SELECT = """
        SELECT id, tenant_id, employee_id, start_date, end_date, status,
               deducted_days, approved_by, decided_at, decision_note, created_at
        FROM annual_leave_requests
    """

    # -------------------------------- oxu ------------------------------------- #

    def get(self, request_id: AnnualLeaveRequestId) -> AnnualLeaveRequest | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (request_id, self._tenant),
        )
        return _row_to_request(row) if row else None

    def get_for_update(self, request_id: AnnualLeaveRequestId) -> AnnualLeaveRequest | None:
        """`get()`-in SƏTİR KİLİDLİ variantı — YALNIZ yazma axını üçün.

        `get()` siyahı və ekran yollarında işlədilir; ona `FOR UPDATE` qoymaq
        hər baxışı yazı-kilidinə çevirərdi (`PostgresOpenShiftPosting
        Repository.get_for_update` ilə eyni qərar).
        """
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (request_id, self._tenant),
        )
        return _row_to_request(row) if row else None

    def list_pending(self, tenant_id: TenantId, *, limit: int = 200) -> list[AnnualLeaveRequest]:
        """`idx_annual_leave_requests_pending` — ən erkən başlayan əvvəldə."""
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND status = 'PENDING_APPROVAL'
            ORDER BY start_date, created_at
            LIMIT %s
            """,
            (tenant_id, limit),
        )
        return [_row_to_request(row) for row in rows]

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int = 50
    ) -> list[AnnualLeaveRequest]:
        """`idx_annual_leave_requests_employee` — ən yenisi əvvəldə."""
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE employee_id = %s AND tenant_id = %s
            ORDER BY start_date DESC
            LIMIT %s
            """,
            (employee_id, self._tenant, limit),
        )
        return [_row_to_request(row) for row in rows]

    def find_overlapping_approved(
        self, employee_id: EmployeeId, *, start: date, end: date
    ) -> AnnualLeaveRequest | None:
        """`EXCLUDE` qapağının OXU tərəfi — `daterange ... && ...` eyni məntiqlə.

        Aralıq `'[]'`-dir (hər iki uc DAXİL), çünki sxemdəki qapaq da elədir:
        fərqli olsaydı, ekran "təsadüf yoxdur" deyər, DB isə təsdiqi rədd
        edərdi və istifadəçi səbəbi anlamazdı.
        """
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE employee_id = %s
              AND tenant_id = %s
              AND status = 'APPROVED'
              AND daterange(start_date, end_date, '[]') && daterange(%s, %s, '[]')
            ORDER BY start_date
            LIMIT 1
            """,
            (employee_id, self._tenant, start, end),
        )
        return _row_to_request(row) if row else None

    # -------------------------------- yazı ------------------------------------ #

    def save(self, request: AnnualLeaveRequest) -> None:
        """UPSERT — `ON CONFLICT (id) DO UPDATE`.

        `ExclusionViolation` TUTULUR VƏ TƏRCÜMƏ EDİLİR: `excl_annual_leave_
        no_overlap` pozuntusu istifadəçiyə xam DB mətni kimi çatsaydı
        ("conflicting key value violates exclusion constraint..."), HR nə baş
        verdiyini anlamazdı. Bu, texniki nasazlıq deyil — iş qaydasıdır.

        `CheckViolation` da tutulur: `chk_annual_leave_request_decision` və
        `chk_annual_leave_request_deduction` entity qaydalarının DB əkizidir
        və pozulmaları yalnız ekranı yan keçən yolda mümkündür — orada da
        aydın mesaj verilməlidir.
        """
        try:
            self._execute(
                """
                INSERT INTO annual_leave_requests
                    (id, tenant_id, employee_id, start_date, end_date, status,
                     deducted_days, approved_by, decided_at, decision_note, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                   SET status        = EXCLUDED.status,
                       -- ERKƏN QAYIDIŞ (HR-6): `return_early()` aralığı
                       -- QISALDIR, yəni `end_date` DƏYİŞİR. Sütun burada
                       -- yenilənməsəydi, qısaltma YALNIZ yaddaşda qalar,
                       -- testdə görünər, İSTEHSALATDA İSƏ İTƏRDİ —
                       -- növbəti oxunuşda işçi hələ də «məzuniyyətdə»
                       -- görünərdi.
                       end_date      = EXCLUDED.end_date,
                       deducted_days = EXCLUDED.deducted_days,
                       approved_by   = EXCLUDED.approved_by,
                       decided_at    = EXCLUDED.decided_at,
                       decision_note = EXCLUDED.decision_note
                """,
                (
                    request.id,
                    request.tenant_id,
                    request.employee_id,
                    request.start_date,
                    request.end_date,
                    request.status.value,
                    request.deducted_days,
                    request.approved_by,
                    request.decided_at,
                    request.decision_note,
                    request.created_at,
                ),
            )
        except pg_errors.ExclusionViolation as error:
            raise AnnualLeaveError(
                "Təsdiqlənmiş məzuniyyət aralıqları kəsişir (DB EXCLUDE qapağı)",
                user_message=(
                    "Bu tarixlər üçün artıq təsdiqlənmiş məzuniyyətiniz var. Başqa tarix seçin."
                ),
                context={
                    "request_id": str(request.id),
                    "start_date": request.start_date.isoformat(),
                    "end_date": request.end_date.isoformat(),
                    "constraint": getattr(error.diag, "constraint_name", None),
                },
            ) from error
        except pg_errors.CheckViolation as error:
            raise AnnualLeaveError(
                "Məzuniyyət sorğusu sxem qaydasını pozdu",
                user_message=(
                    "Məzuniyyət sorğusu saxlanıla bilmədi: tarix və ya qərar məlumatı natamamdır."
                ),
                context={
                    "request_id": str(request.id),
                    "constraint": getattr(error.diag, "constraint_name", None),
                },
            ) from error


def _row_to_balance(row: dict[str, Any]) -> AnnualLeaveBalance:
    return AnnualLeaveBalance(
        balance_id=AnnualLeaveBalanceId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        year=int(row["year"]),
        entitled_days=Decimal(str(row["entitled_days"])),
        used_days=Decimal(str(row["used_days"])),
        carried_over_days=Decimal(str(row["carried_over_days"])),
        # Balansı əl ilə dəyişən işçi silinibsə sütun NULL-dur
        # (`ON DELETE SET NULL`) — balans bundan asılı olmadan oxunmalıdır.
        updated_by=None if row["updated_by"] is None else EmployeeId(row["updated_by"]),
    )


def _row_to_request(row: dict[str, Any]) -> AnnualLeaveRequest:
    return AnnualLeaveRequest(
        request_id=AnnualLeaveRequestId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        start_date=row["start_date"],
        end_date=row["end_date"],
        created_at=row["created_at"],
        status=AnnualLeaveStatus(row["status"]),
        deducted_days=(
            None if row["deducted_days"] is None else Decimal(str(row["deducted_days"]))
        ),
        approved_by=None if row["approved_by"] is None else EmployeeId(row["approved_by"]),
        decided_at=row["decided_at"],
        decision_note=row["decision_note"],
        # Repository-dən BƏRPA hadisə YAYMIR — hər siyahı oxunuşu "yeni
        # məzuniyyət sorğusu" bildirişi göndərərdi.
        emit_created_event=False,
    )


__all__ = [
    "PostgresAnnualLeaveBalanceRepository",
    "PostgresAnnualLeaveRequestRepository",
]
