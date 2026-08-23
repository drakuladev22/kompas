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
from src.domain.entities.open_shift import (
    EXPIRED_CANCEL_REASON,
    OpenShiftPosting,
    OpenShiftSlot,
    OpenShiftStatus,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    OpenShiftPostingId,
    StoreId,
    TenantId,
    WorkModeId,
)
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import date, datetime

_log = get_logger(__name__)


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
        # INF2-02: `tenant_id` arqumenti bağlantının ÖZ kontekstiylə UYĞUN
        # olmalıdır — uyğunsuzluqda GURULTULU xəta (bax `_require_matching_
        # tenant` şərhi, `repositories.py`).
        clauses = ["tenant_id = %s", "status = 'OPEN'"]
        params: list[Any] = [self._require_matching_tenant(tenant_id)]
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

    def list_claimed(
        self,
        *,
        employee_id: EmployeeId | None = None,
        from_date: date | None = None,
        limit: int = 100,
    ) -> list[OpenShiftPosting]:
        """TUTULMUŞ elanlar — «Tutduğum növbələr» kartının oxu yolu (OP-4).

        ──────────────────────────────────────────────────────────────────────
        `tenant_id` ARQUMENTİ YOXDUR — QONŞU METODLARDAN FƏRQLİ
        ──────────────────────────────────────────────────────────────────────
        Süzgəc bağlantının ÖZ kontekstindən (`self._tenant`) gəlir. Qonşu
        `list_open`/`find_open_for_slot` köhnə imza ilə (`tenant_id` +
        `_require_matching_tenant`) qalır və onları köçürmək AYRI işdir —
        lakin YENİ metod həmin borcu ARTIRA BİLMƏZ: sayğac
        (`tenant_argument_audit.py`, tavan 123) yalnız aşağı düşür.
        Nəticə eynidir (sorğu bağlantının kirayəçisi ilə gedir), FƏRQ
        yalnız səhv `tenant_id` ötürmək İMKANININ olmamasıdır.

        ──────────────────────────────────────────────────────────────────────
        İNDEKS
        ──────────────────────────────────────────────────────────────────────
        `uq_open_shift_one_claim_per_employee_day` (`tenant_id, claimed_by,
        shift_date`, `WHERE status = 'CLAIMED'`) — o, unikallıq üçün
        yaradılıb, lakin qismən indeks olduğu üçün bu sorğunun da yoludur:
        `employee_id` verildikdə üç sütunun hamısı, verilmədikdə isə
        birinci sütun (`tenant_id`) işləyir. Ona görə AYRI indeks əlavə
        EDİLMƏDİ — mövcud olanı təkrarlayardı.

        `count_claims_in_month` ilə EYNİ indeksi paylaşır, lakin BİRLƏŞDİRİLMİR:
        o, SAY qaytarır (tavan yoxlaması), bu isə SƏTİRLƏRİ (ekran siyahısı).

        Args:
            employee_id: `None` = kirayəçidəki BÜTÜN tutulmuş elanlar (admin
                görünüşü). Doludursa yalnız həmin işçinin tutduqları.
            from_date: `None` = tarix süzgəci YOXDUR. «Bugündən etibarən»
                qərarını ÇAĞIRAN verir (port docstring-i: bu, repo-nun deyil,
                iş qaydasının qərarıdır) — keçmiş növbəni geri vermək
                mənasızdır, lakin həmin qayda use case-dədir.
        """
        clauses = ["tenant_id = %s", "status = 'CLAIMED'"]
        params: list[Any] = [self._tenant]
        if employee_id is not None:
            clauses.append("claimed_by = %s")
            params.append(employee_id)
        if from_date is not None:
            clauses.append("shift_date >= %s")
            params.append(from_date)
        params.append(limit)

        # `clauses` SABİT sətir siyahısındandır (kənardan gələn mətn yoxdur),
        # bütün dəyərlər `%s` ilə bağlanır — `list_open`-dakı eyni qərar.
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
        # INF2-02: bax `list_open`-dəki eyni izah.
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND store_id = %s AND shift_date = %s
              AND work_mode_id = %s AND status = 'OPEN'
            """,
            (
                self._require_matching_tenant(tenant_id),
                slot.store_id,
                slot.shift_date,
                slot.work_mode_id,
            ),
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

    def release(
        self,
        *,
        posting_id: OpenShiftPostingId,
        released_by: EmployeeId,
        released_at: datetime,
    ) -> bool:
        """ŞƏRTLİ `UPDATE ... WHERE status = 'CLAIMED'` — tutma geri alınır (OP-4).

        `claim()`-in GÜZGÜSÜDÜR və eyni səbəbdən şərtlidir: geri buraxma ilə
        ləğv YARIŞIR (işçi «geri verirəm» düyməsini basdığı anda admin elanı
        ləğv edə bilər). Qalibi DB seçir, uduzan tərəf `False` alır.

        ──────────────────────────────────────────────────────────────────────
        `released_by` SƏTRƏ YAZILMIR
        ──────────────────────────────────────────────────────────────────────
        Cədvəldə belə sütun YOXDUR və əlavə edilməsi də lazım deyil: sətir
        yenidən `OPEN` olur, `chk_open_shift_claim` isə `OPEN` sətirdə
        sahiblik sütunlarının `NULL` olmasını TƏLƏB EDİR — yəni «kim geri
        verdi» məlumatını ora yazmaq invariantı pozardı. Cavab audit
        sətrindədir (`OPEN_SHIFT_RELEASED`). Parametr yalnız bu qatın öz
        jurnalı üçün qəbul edilir (port docstring-i ilə eyni qərar).

        `released_at` SƏTRƏ DƏ YAZILMIR: `updated_at` trigger-i (`set_updated_
        at`) həmin anı onsuz da yazır və ikinci vaxt sütunu iki mənbə yaradardı.

        ──────────────────────────────────────────────────────────────────────
        DB QATI (migrations/085)
        ──────────────────────────────────────────────────────────────────────
        `enforce_open_shift_claim_transition()` `CLAIMED → OPEN` keçidinə məhz
        bu metod üçün icazə verir və HƏMİN keçiddə sahiblik sütunlarının
        `NULL`-a düşməsini TƏLƏB EDİR. «İlk basan qazanır» qadağası
        (`CLAIMED → CLAIMED` sahib dəyişikliyi) toxunulmaz qalır.
        """
        affected = self._execute(
            """
            UPDATE open_shift_postings
               SET status     = 'OPEN',
                   claimed_by = NULL,
                   claimed_at = NULL
             WHERE id = %s
               AND tenant_id = %s
               AND status = 'CLAIMED'
            """,
            (posting_id, self._tenant),
        )
        _log.info(
            "OPEN_SHIFT_RELEASE_ATTEMPTED",
            extra={
                "posting_id": str(posting_id),
                "released_by": str(released_by),
                "released_at": released_at.isoformat(),
                "released": affected == 1,
            },
        )
        return affected == 1

    def expire(self, *, posting_id: OpenShiftPostingId, expired_at: datetime) -> bool:
        """ŞƏRTLİ `UPDATE ... WHERE status = 'OPEN'` — tarixi keçmiş elanı bağlayır (OP-4).

        `cancel()` ilə EYNİ şərt (`status = 'OPEN'`) və eyni yarış məntiqi:
        planlaşdırılmış iş elanı bağlamağa çalışarkən işçi onu tuta bilər —
        həmin halda 0 sətir toxunur və iş `False` alır. Tutulmuş növbə
        AVTOMATİK bağlanmır: işçi artıq həmin günə söz verib.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `cancel()`-a `cancelled_by=None` ÖTÜRMÜR
        ──────────────────────────────────────────────────────────────────────
        Port başlığındakı qərarın davamı: `cancel()`-un imzası `cancelled_by:
        EmployeeId` (məcburi) qalmalıdır ki, İNSAN yolunda aktoru buraxmaq
        mümkün olmasın. Ayrı metod həmin imzanı toxunulmaz saxlayır.

        `cancel_reason` domendəki `EXPIRED_CANCEL_REASON` sabitindən gəlir —
        burada mətn TƏKRAR YAZILMIR: ekran həmin sətri oxuyub istifadəçiyə
        göstərir və iki nüsxə bir gün fərqlənərdi.

        ──────────────────────────────────────────────────────────────────────
        DB QATI (migrations/085)
        ──────────────────────────────────────────────────────────────────────
        `chk_open_shift_cancel` `cancelled_by IS NOT NULL` tələb edirdi — bu
        `UPDATE` həmin şərtlə İŞLƏMƏZDİ. Şərt `cancelled_at`-a köklənib
        (domendəki `_require_consistent_state()` ilə eyni formada).
        """
        affected = self._execute(
            """
            UPDATE open_shift_postings
               SET status        = 'CANCELLED',
                   cancelled_by  = NULL,
                   cancelled_at  = %s,
                   cancel_reason = %s
             WHERE id = %s
               AND tenant_id = %s
               AND status = 'OPEN'
            """,
            (expired_at, EXPIRED_CANCEL_REASON, posting_id, self._tenant),
        )
        if affected == 1:
            _log.info(
                "OPEN_SHIFT_EXPIRED",
                extra={"posting_id": str(posting_id), "expired_at": expired_at.isoformat()},
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
