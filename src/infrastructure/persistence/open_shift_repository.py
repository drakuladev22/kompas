"""Açıq Növbə Bazarının saxlama qatı (#16) — `open_shift_postings`.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — tətbiq səhvən owner rolu ilə qoşulsa da
izolyasiya qalır (layihənin bütün repo-larında eyni naxış).

──────────────────────────────────────────────────────────────────────────────
YARIŞ QAPAĞI BU FAYLDA YAŞAYIR
──────────────────────────────────────────────────────────────────────────────
`claim()` və `cancel()` UPSERT DEYİL — ŞƏRTLİ `UPDATE`-dir:

    UPDATE open_shift_postings
       SET status = 'CLAIMED', ...
     WHERE id = %s AND tenant_id = %s AND status = 'OPEN'

və TƏSİR OLUNMUŞ SƏTİR SAYI qaytarılır. İki paralel tranzaksiyadan yalnız
biri 1 sətir yeniləyə bilir: PostgreSQL READ COMMITTED-də ikinci `UPDATE`
birinci commit olunandan sonra şərti YENİDƏN qiymətləndirir və `status`
artıq `'OPEN'` olmadığı üçün 0 sətir toxunur.

`get_for_update()` bundan ƏVVƏL sətri kilidləyir. Kilid təkbaşına kifayət
etməzdi (kilidsiz oxu yolu qalır), şərti UPDATE isə təkbaşına "elan nə üçün
bağlandı?" sualını cavablaya bilməzdi — ikisi birlikdə həm serializasiya,
həm izah verir. Üçüncü qat DB trigger-idir (`migrations/019`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÜMUMİ `save()` YOXDUR
──────────────────────────────────────────────────────────────────────────────
Bax `ports.OpenShiftPostingRepository` başlığı: `save(posting)` imzası
çağıran tərəfi "oxu → dəyiş → yaz" naxışına dəvət edərdi və məhz bu naxış
yarışı UDUZUR. İmza səhv istifadəni struktur olaraq bağlayır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg import errors as pg_errors

from src.application.use_cases.open_shift_market import OpenShiftError
from src.domain.entities.open_shift import OpenShiftPosting, OpenShiftSlot, OpenShiftStatus
from src.domain.value_objects.identifiers import (
    EmployeeId,
    OpenShiftPostingId,
    StoreId,
    TenantId,
    WorkModeId,
)
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date, datetime


class PostgresOpenShiftPostingRepository(_BaseRepository):
    """`open_shift_postings` — elan yaradılır, tutulur, ləğv edilir."""

    _SELECT = """
        SELECT id, tenant_id, store_id, shift_date, work_mode_id, status,
               posted_by, claimed_by, claimed_at,
               cancelled_by, cancelled_at, cancel_reason, created_at
        FROM open_shift_postings
    """

    # -------------------------------- oxu ------------------------------------- #

    def get(self, posting_id: OpenShiftPostingId) -> OpenShiftPosting | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (posting_id, self._tenant),
        )
        return _row_to_posting(row) if row else None

    def get_for_update(self, posting_id: OpenShiftPostingId) -> OpenShiftPosting | None:
        """`get()`-in SƏTİR KİLİDLİ variantı — YALNIZ yazma axını üçün.

        `get()` siyahı və ekran yollarında işlədilir; ona `FOR UPDATE` qoymaq
        hər baxışı yazı-kilidinə çevirərdi (`PostgresLeaveRequestRepository.
        get_for_update` ilə eyni qərar və eyni əsaslandırma).
        """
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (posting_id, self._tenant),
        )
        return _row_to_posting(row) if row else None

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_id: StoreId | None = None,
        from_date: date | None = None,
        limit: int = 100,
    ) -> list[OpenShiftPosting]:
        """`idx_open_shift_postings_open` indeksinin sorğusu — ən yaxın tarix əvvəldə."""
        clauses = ["tenant_id = %s", "status = 'OPEN'"]
        params: list[Any] = [tenant_id]
        if store_id is not None:
            clauses.append("store_id = %s")
            params.append(store_id)
        if from_date is not None:
            clauses.append("shift_date >= %s")
            params.append(from_date)
        params.append(limit)

        # `clauses` SABİT sətir siyahısındandır (kənardan gələn mətn yoxdur),
        # bütün dəyərlər `%s` ilə bağlanır — bölmə 2-nin tələbi pozulmur.
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE {" AND ".join(clauses)}
            ORDER BY shift_date, created_at
            LIMIT %s
            """,
            tuple(params),
        )
        return [_row_to_posting(row) for row in rows]

    def find_open_for_slot(
        self, tenant_id: TenantId, slot: OpenShiftSlot
    ) -> OpenShiftPosting | None:
        """`uq_open_shift_one_open_per_slot` indeksinin oxu tərəfi."""
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND store_id = %s AND shift_date = %s
              AND work_mode_id = %s AND status = 'OPEN'
            """,
            (tenant_id, slot.store_id, slot.shift_date, slot.work_mode_id),
        )
        return _row_to_posting(row) if row else None

    def count_claims_in_month(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        """Aylıq tavan yoxlaması — sayma SQL-də edilir.

        Sətirləri yaddaşa gətirib Python-da saymaq 21 filialın bir aylıq
        elan axını üçün mənasız yük olardı (`monthly_used_minutes` ilə eyni
        qərar).
        """
        row = self._fetch_one(
            """
            SELECT count(*) AS taken
            FROM open_shift_postings
            WHERE claimed_by = %s
              AND tenant_id = %s
              AND status = 'CLAIMED'
              AND date_part('year', shift_date) = %s
              AND date_part('month', shift_date) = %s
            """,
            (employee_id, self._tenant, year, month),
        )
        return int(row["taken"]) if row else 0

    # -------------------------------- yazı ------------------------------------ #

    def post(self, posting: OpenShiftPosting) -> None:
        """Yeni elan — SADƏ `INSERT`, `ON CONFLICT` YOXDUR.

        `ON CONFLICT DO NOTHING` yazsaydıq, eyni slota ikinci elan sükutla
        "uğurlu" sayılardı və admin elanın yaranmadığını yalnız siyahıda
        görməklə başa düşərdi. Unikal indeks pozuntusu isə istifadəçiyə xam
        `UniqueViolation` kimi çatmamalıdır — o, texniki nasazlıq deyil, use
        case-dəki İŞ QAYDASIDIR (`PostgresLeaveRequestRepository.save` ilə
        eyni naxış).
        """
        try:
            self._execute(
                """
                INSERT INTO open_shift_postings
                    (id, tenant_id, store_id, shift_date, work_mode_id,
                     status, posted_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    posting.id,
                    posting.tenant_id,
                    posting.store_id,
                    posting.shift_date,
                    posting.work_mode_id,
                    posting.status.value,
                    posting.posted_by,
                    posting.created_at,
                ),
            )
        except pg_errors.UniqueViolation as error:
            raise OpenShiftError(
                "Bu slot üçün artıq açıq elan var (DB unikal indeksi)",
                user_message="Bu tarix və iş rejimi üçün artıq açıq elan var.",
                context={
                    "posting_id": str(posting.id),
                    "shift_date": posting.shift_date.isoformat(),
                    "constraint": getattr(error.diag, "constraint_name", None),
                },
            ) from error

    def claim(
        self,
        *,
        posting_id: OpenShiftPostingId,
        employee_id: EmployeeId,
        claimed_at: datetime,
    ) -> bool:
        """ŞƏRTLİ `UPDATE` — "ilk basan qazanır"ın tətbiq qatı (modul başlığı).

        `status = 'OPEN'` şərti SORĞUNUN İÇİNDƏDİR: onu Python-da yoxlamaq
        oxu ilə yazı arasında pəncərə qoyardı və hər iki işçi qalib sayılardı.

        `RETURNING` işlədilmir — bizə yalnız "yenilədimmi?" cavabı lazımdır
        və `rowcount` onu artıq verir.
        """
        affected = self._execute(
            """
            UPDATE open_shift_postings
               SET status     = 'CLAIMED',
                   claimed_by = %s,
                   claimed_at = %s
             WHERE id = %s
               AND tenant_id = %s
               AND status = 'OPEN'
            """,
            (employee_id, claimed_at, posting_id, self._tenant),
        )
        return affected == 1

    def cancel(
        self,
        *,
        posting_id: OpenShiftPostingId,
        cancelled_by: EmployeeId,
        cancelled_at: datetime,
        reason: str,
    ) -> bool:
        """ŞƏRTLİ `UPDATE` — tutulmuş elanı ləğv etmək MÜMKÜN DEYİL.

        Şərt tutma ilə EYNİDİR (`status = 'OPEN'`), çünki ləğv və tutma
        bir-biri ilə yarışır: işçi düyməni basdığı anda admin ləğv edə bilər.
        Qalib yenə DB-dir; uduzan tərəf `False` alır və açıq mesaj görür.
        """
        affected = self._execute(
            """
            UPDATE open_shift_postings
               SET status        = 'CANCELLED',
                   cancelled_by  = %s,
                   cancelled_at  = %s,
                   cancel_reason = %s
             WHERE id = %s
               AND tenant_id = %s
               AND status = 'OPEN'
            """,
            (cancelled_by, cancelled_at, reason, posting_id, self._tenant),
        )
        return affected == 1


def _row_to_posting(row: dict[str, Any]) -> OpenShiftPosting:
    return OpenShiftPosting(
        posting_id=OpenShiftPostingId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        slot=OpenShiftSlot(
            store_id=StoreId(row["store_id"]),
            shift_date=row["shift_date"],
            work_mode_id=WorkModeId(row["work_mode_id"]),
        ),
        # Elanı açan işçi silinibsə sütun NULL-dur (`ON DELETE SET NULL`) —
        # elan bundan asılı olmayaraq oxunmalıdır (bax entity şərhi).
        posted_by=None if row["posted_by"] is None else EmployeeId(row["posted_by"]),
        created_at=row["created_at"],
        status=OpenShiftStatus(row["status"]),
        claimed_by=None if row["claimed_by"] is None else EmployeeId(row["claimed_by"]),
        claimed_at=row["claimed_at"],
        cancelled_by=(None if row["cancelled_by"] is None else EmployeeId(row["cancelled_by"])),
        cancelled_at=row["cancelled_at"],
        cancel_reason=row["cancel_reason"],
        # Repository-dən BƏRPA hadisə YAYMIR — hər siyahı oxunuşu "yeni elan"
        # bildirişi göndərərdi.
        emit_created_event=False,
    )


__all__ = ["PostgresOpenShiftPostingRepository"]
