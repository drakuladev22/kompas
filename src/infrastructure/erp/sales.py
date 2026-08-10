"""Satış sənədlərinin yazılması və uyğunlaşma axtarışları — Faza 3.10.

İki məsuliyyət, hər ikisi DB-yə bağlıdır (ona görə `matching.py`-dən ayrıdır —
uyğunlaşma QAYDASI orada DB-siz test edilə bilir):

    * `PostgresMatchDirectory` — `MatchDirectory` protokolunun real tətbiqi.
    * `SalesTransactionRepository` — `sales_transactions`-a idempotent yazma.
    * `PostgresSalesReviewRepository` — «Şübhəli Satışlar» növbəsi (bölmə 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ KEŞ BİR SİNXRONİZASİYA DÖVRÜ ÜÇÜNDÜR
──────────────────────────────────────────────────────────────────────────────
Bir dövrdə 500 sənəd gələ bilər və onların çoxu eyni mağazaya aiddir. Hər
sənəd üçün mağaza/işçi siyahısını yenidən sorğulamaq 500 artıq gediş-gəliş
deməkdir. Keş `Directory` NÜSXƏSİNDƏ yaşayır və hər dövr üçün yenidən
qurulur — beləliklə dövr ərzində sabitlik, dövrlər arasında isə təzəlik
təmin olunur (işçi əlavə edildikdə növbəti dövr onu görür).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `ON CONFLICT DO NOTHING`
──────────────────────────────────────────────────────────────────────────────
Kursor `>=` ilə irəlilədiyi üçün sərhəd sənədləri təkrar gələ bilər (bax
`SyncCursor`). Təkrar sətir YENİDƏN xal qazandırmamalıdır, lakin xəta da
verməməlidir — normal haldır. `UNIQUE (server_id, one_c_document_id)` bunu
DB səviyyəsində zəmanət edir; burada yalnız sükutla ötürülür və SAYILIR
(hesabatda `duplicates` kimi görünür).

`DO UPDATE` QƏSDƏN istifadə OLUNMUR: sənəd bir dəfə uyğunlaşdırılandan sonra
HR_Admin onu əl ilə düzəltmiş ola bilər (`MANUAL_MATCH`). Avtomatik təkrar
yazma insanın qərarını sükutla ləğv edərdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.application.use_cases.sales_review_queue import ReviewQueueItem
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.identifiers import EmployeeId, StoreId
from src.domain.value_objects.money import Money
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from src.domain.value_objects.erp import MatchResult
    from src.domain.value_objects.identifiers import (
        ErpServerId,
        SalesTransactionId,
        TenantId,
    )
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)


class PostgresMatchDirectory:
    """`MatchDirectory` protokolunun DB tətbiqi (dövr ərzində keşlənir)."""

    def __init__(self, database: Database, tenant_id: TenantId) -> None:
        self._database = database
        self._tenant_id = tenant_id
        self._stores: dict[tuple[str, str], StoreId | None] = {}
        self._sellers: dict[tuple[str, str], EmployeeId | None] = {}
        self._staff: dict[str, tuple[tuple[EmployeeId, str], ...]] = {}

    def store_for(self, server_id: ErpServerId, store_code: str) -> StoreId | None:
        key = (str(server_id), store_code)
        if key in self._stores:
            return self._stores[key]
        rows = self._fetch_all(
            """
            SELECT store_id FROM store_server_mapping
             WHERE server_id = %s AND one_c_store_code = %s
             LIMIT 1
            """,
            (server_id, store_code),
        )
        resolved = StoreId(rows[0]["store_id"]) if rows else None
        self._stores[key] = resolved
        return resolved

    def employee_by_seller_id(self, store_id: StoreId, seller_id: str) -> EmployeeId | None:
        key = (str(store_id), seller_id)
        if key in self._sellers:
            return self._sellers[key]
        rows = self._fetch_all(
            """
            SELECT id FROM employees
             WHERE store_id = %s AND one_c_seller_id = %s AND is_active
             LIMIT 1
            """,
            (store_id, seller_id),
        )
        resolved = EmployeeId(rows[0]["id"]) if rows else None
        self._sellers[key] = resolved
        return resolved

    def employees_in_store(self, store_id: StoreId) -> Sequence[tuple[EmployeeId, str]]:
        key = str(store_id)
        cached = self._staff.get(key)
        if cached is not None:
            return cached
        rows = self._fetch_all(
            """
            SELECT id, first_name, last_name FROM employees
             WHERE store_id = %s AND is_active
            """,
            (store_id,),
        )
        staff = tuple(
            (EmployeeId(row["id"]), f"{row['first_name']} {row['last_name']}".strip())
            for row in rows
        )
        self._staff[key] = staff
        return staff

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


class SalesTransactionRepository:
    """`sales_transactions` cədvəlinə idempotent yazma."""

    def __init__(self, database: Database, tenant_id: TenantId) -> None:
        self._database = database
        self._tenant_id = tenant_id

    def insert_batch(self, server_id: ErpServerId, results: Sequence[MatchResult]) -> int:
        """Uyğunlaşdırılmış sətirləri yazır, TƏKRARLARI sükutla ötürür.

        Returns:
            Faktiki YAZILAN sətir sayı (təkrarlar daxil deyil).
        """
        return len(self.insert_batch_returning(server_id, results))

    def insert_batch_returning(
        self, server_id: ErpServerId, results: Sequence[MatchResult]
    ) -> list[tuple[SalesTransactionId, MatchResult]]:
        """Eyni yazma, lakin YENİ sətirlərin ID-lərini də qaytarır.

        NİYƏ LAZIMDIR: xal yalnız FAKTİKİ yazılmış sətir üçün verilməlidir.
        Sayğac (`rowcount`) hansı sətrin yeni olduğunu demir, ona görə təkrar
        gələn sənəd ikinci dəfə xal qazandırardı — `ON CONFLICT DO NOTHING`-in
        bütün mənası məhz bunun qarşısını almaqdır.
        """
        if not results:
            return []

        written: list[tuple[SalesTransactionId, MatchResult]] = []
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                for result in results:
                    record = result.record
                    cur.execute(
                        """
                        INSERT INTO sales_transactions
                            (tenant_id, server_id, one_c_seller_id, one_c_store_code,
                             one_c_document_id, one_c_seller_name, employee_id, store_id,
                             gross_amount, transaction_date, confidence, match_reason)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (server_id, one_c_document_id) DO NOTHING
                        RETURNING id
                        """,
                        (
                            self._tenant_id,
                            server_id,
                            record.seller_id,
                            record.store_code,
                            record.document_id,
                            record.seller_name,
                            result.employee_id,
                            result.store_id,
                            record.gross_amount,
                            record.transaction_date,
                            result.confidence.value,
                            result.reason or None,
                        ),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        written.append((row["id"], result))
            uow.commit()
        return written

    def review_queue_size(self) -> int:
        """ "Təyin Olunmamış / Şübhəli Uyğunlaşma" növbəsindəki sətir sayı."""
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS total FROM sales_transactions
                 WHERE confidence IN ('LOW_CONFIDENCE_MATCH', 'UNASSIGNED')
                """
            )
            row = cur.fetchone()
            return int(row["total"]) if row else 0


class PostgresSalesReviewRepository:
    """«Şübhəli Satışlar» növbəsinin oxu/yazma tərəfi (bölmə 6, Faza 6.2).

    `SalesTransactionRepository`-dən AYRIDIR: ora sync worker-in toplu yazma
    yoludur (saniyədə minlərlə sətir), bura isə insanın bir-bir baxdığı
    ekran. İkisini birləşdirmək sync-in isti yolunu ekran sorğuları ilə
    yükləyərdi.
    """

    _SELECT = """
        SELECT st.id, st.one_c_seller_id, st.one_c_seller_name, st.one_c_store_code,
               st.one_c_document_id, st.gross_amount, st.transaction_date,
               st.confidence, st.match_reason, st.employee_id, st.store_id,
               COALESCE(srv.server_name, '—') AS server_name,
               COALESCE(e.first_name || ' ' || e.last_name, '') AS employee_name
        FROM sales_transactions st
        LEFT JOIN erp_servers srv ON srv.id = st.server_id
        LEFT JOIN employees e     ON e.id = st.employee_id
    """

    def __init__(self, database: Database, tenant_id: TenantId) -> None:
        self._database = database
        self._tenant_id = tenant_id

    def list_queue(
        self,
        tenant_id: TenantId,
        *,
        server_id: object | None = None,
        limit: int = 200,
    ) -> list[ReviewQueueItem]:
        rows = self._fetch(
            f"""{self._SELECT}
            WHERE st.tenant_id = %s
              AND st.confidence IN ('LOW_CONFIDENCE_MATCH', 'UNASSIGNED')
              AND (%s::uuid IS NULL OR st.server_id = %s::uuid)
            ORDER BY st.transaction_date DESC, st.id
            LIMIT %s
            """,
            (tenant_id, server_id, server_id, limit),
        )
        return [_row_to_queue_item(row) for row in rows]

    def get(self, transaction_id: SalesTransactionId) -> ReviewQueueItem | None:
        rows = self._fetch(
            f"{self._SELECT} WHERE st.id = %s AND st.tenant_id = %s",
            (transaction_id, self._tenant_id),
        )
        return _row_to_queue_item(rows[0]) if rows else None

    def queue_size(self, tenant_id: TenantId) -> int:
        rows = self._fetch(
            """
            SELECT count(*) AS total FROM sales_transactions
             WHERE tenant_id = %s
               AND confidence IN ('LOW_CONFIDENCE_MATCH', 'UNASSIGNED')
            """,
            (tenant_id,),
        )
        return int(rows[0]["total"]) if rows else 0

    def assign(
        self,
        transaction_id: SalesTransactionId,
        *,
        employee_id: EmployeeId,
        store_id: StoreId | None,
        matched_by: EmployeeId,
        matched_at: datetime,
    ) -> None:
        self._execute(
            """
            UPDATE sales_transactions
               SET employee_id = %s,
                   store_id    = COALESCE(%s, store_id),
                   confidence  = 'MANUAL_MATCH',
                   matched_by  = %s,
                   matched_at  = %s
             WHERE id = %s AND tenant_id = %s
            """,
            (employee_id, store_id, matched_by, matched_at, transaction_id, self._tenant_id),
        )

    def confirm(
        self,
        transaction_id: SalesTransactionId,
        *,
        matched_by: EmployeeId,
        matched_at: datetime,
    ) -> None:
        """İşçi DƏYİŞMİR — yalnız uyğunlaşma insan tərəfindən təsdiqlənir."""
        self._execute(
            """
            UPDATE sales_transactions
               SET confidence = 'MANUAL_MATCH',
                   matched_by = %s,
                   matched_at = %s
             WHERE id = %s AND tenant_id = %s AND employee_id IS NOT NULL
            """,
            (matched_by, matched_at, transaction_id, self._tenant_id),
        )

    def _fetch(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(sql, params)
            uow.commit()


def _row_to_queue_item(row: dict[str, Any]) -> ReviewQueueItem:
    return ReviewQueueItem(
        transaction_id=row["id"],
        server_name=row["server_name"],
        one_c_seller_id=row["one_c_seller_id"],
        one_c_seller_name=row["one_c_seller_name"],
        one_c_store_code=row["one_c_store_code"],
        one_c_document_id=row["one_c_document_id"],
        gross_amount=Money(row["gross_amount"]),
        transaction_date=row["transaction_date"],
        confidence=MatchConfidence(row["confidence"]),
        match_reason=row["match_reason"],
        suggested_employee_id=row["employee_id"],
        suggested_employee_name=row["employee_name"],
        store_id=row["store_id"],
    )


__all__ = [
    "PostgresMatchDirectory",
    "PostgresSalesReviewRepository",
    "SalesTransactionRepository",
]
