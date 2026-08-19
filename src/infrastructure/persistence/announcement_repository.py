"""#19 Elan (Broadcast) saxlama qatı — `announcements` + `announcement_targets`.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — tətbiq səhvən owner rolu ilə qoşulsa
(RLS onda tətbiq olunmur), izolyasiya bu şərtlə qalır (`pos_policy_repository.py`
ilə eyni naxış).

STORE-SCOPING SORĞUSU (`list_visible_for_store`) — NİYƏ `store_id IS NULL`-DA
DA İŞLƏYİR: `EXISTS (... WHERE t.store_id = %s)` ifadəsində `%s = NULL`
ötürülsə, SQL-də `sütun = NULL` HƏMİŞƏ UNKNOWN (yəni yalançı) qiymətləndirilir
— beləliklə mağazası olmayan işçi üçün `EXISTS` heç vaxt doğru olmur və yalnız
`scope = 'ALL'` sətirlər qalır. Bu, `Announcement.visible_to_store`-un domen
qaydasının SQL güzgüsüdür — Python-da ayrıca budaq yazmağa EHTİYAC yoxdur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.entities.announcement import Announcement, AnnouncementScope
from src.domain.value_objects.identifiers import AnnouncementId, EmployeeId, StoreId, TenantId
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import datetime


class PostgresAnnouncementRepository(_BaseRepository):
    """`announcements` — elan yaradılır (`post`) və geri çəkilir (`withdraw`)."""

    _SELECT = """
        SELECT id, tenant_id, created_by, title_az, message, scope,
               is_active, deactivated_at, deactivated_by, created_at, updated_at
        FROM announcements
    """

    # -------------------------------- oxu ------------------------------------- #

    def get(self, tenant_id: TenantId, announcement_id: AnnouncementId) -> Announcement | None:
        # INF2-02: bax `repositories.py::_require_matching_tenant` şərhi.
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (announcement_id, self._require_matching_tenant(tenant_id)),
        )
        if row is None:
            return None
        return self._attach_targets([row])[0]

    def list_recent(self, tenant_id: TenantId, *, limit: int = 50) -> list[Announcement]:
        """Admin panelinin siyahısı — YARADAN görür, əhatədən ASILI OLMADAN."""
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
            (self._require_matching_tenant(tenant_id), limit),
        )
        return self._attach_targets(rows)

    def list_visible_for_store(
        self, tenant_id: TenantId, store_id: StoreId | None, *, created_after: datetime
    ) -> list[Announcement]:
        """İşçi Ana Ekranının store-scoping oxusu — modul başlığındakı `EXISTS` naxışı."""
        rows = self._fetch_all(
            f"""{self._SELECT.strip()} a
            WHERE a.tenant_id = %s
              AND a.is_active
              AND a.created_at >= %s
              AND (
                    a.scope = 'ALL'
                    OR EXISTS (
                        SELECT 1 FROM announcement_targets t
                         WHERE t.tenant_id = a.tenant_id
                           AND t.announcement_id = a.id
                           AND t.store_id = %s
                    )
                  )
            ORDER BY a.created_at DESC
            """,  # noqa: S608 — sabit sətir, dəyərlər %s ilə bağlanır
            (self._require_matching_tenant(tenant_id), created_after, store_id),
        )
        return self._attach_targets(rows)

    # -------------------------------- yazı ------------------------------------ #

    def post(self, record: Announcement) -> None:
        """Yeni elanı yazır — parent sətir + hədəf sətirləri (modul başlığı)."""
        self._execute(
            """
            INSERT INTO announcements
                (id, tenant_id, created_by, title_az, message, scope, is_active,
                 deactivated_at, deactivated_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.id,
                record.tenant_id,
                record.created_by,
                record.title_az,
                record.message,
                record.scope.value,
                record.is_active,
                record.deactivated_at,
                record.deactivated_by,
                record.created_at,
                record.updated_at,
            ),
        )
        for store_id in record.target_store_ids:
            self._execute(
                """
                INSERT INTO announcement_targets (tenant_id, announcement_id, store_id, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (record.tenant_id, record.id, store_id, record.created_at),
            )

    def withdraw(
        self,
        *,
        tenant_id: TenantId,
        announcement_id: AnnouncementId,
        deactivated_by: EmployeeId,
        deactivated_at: datetime,
    ) -> bool:
        """ŞƏRTLİ `UPDATE ... WHERE is_active` (`OpenShiftPostingRepository.cancel` naxışı)."""
        # INF2-02: bax `repositories.py::_require_matching_tenant` şərhi.
        affected = self._execute(
            """
            UPDATE announcements
               SET is_active      = FALSE,
                   deactivated_at = %s,
                   deactivated_by = %s,
                   updated_at     = %s
             WHERE id = %s
               AND tenant_id = %s
               AND is_active
            """,
            (
                deactivated_at,
                deactivated_by,
                deactivated_at,
                announcement_id,
                self._require_matching_tenant(tenant_id),
            ),
        )
        return affected == 1

    # ------------------------------- köməkçi ----------------------------------- #

    def _attach_targets(self, rows: list[dict[str, Any]]) -> list[Announcement]:
        """Sətirlərə uyğun `announcement_targets`-i BİR sorğuda gətirir.

        Sətir-sətir sorğu N+1 problemi yaradardı — admin siyahısı 50 elana
        qədər göstərə bilər (`list_recent` defolt limiti).
        """
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        target_rows = self._fetch_all(
            """
            SELECT announcement_id, store_id
            FROM announcement_targets
            WHERE announcement_id = ANY(%s)
            """,
            (ids,),
        )
        targets_by_announcement: dict[Any, set[StoreId]] = {}
        for target_row in target_rows:
            targets_by_announcement.setdefault(target_row["announcement_id"], set()).add(
                StoreId(target_row["store_id"])
            )
        return [
            _row_to_announcement(row, frozenset(targets_by_announcement.get(row["id"], set())))
            for row in rows
        ]


def _row_to_announcement(row: dict[str, Any], target_store_ids: frozenset[StoreId]) -> Announcement:
    return Announcement(
        announcement_id=AnnouncementId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        created_by=EmployeeId(row["created_by"]),
        title_az=row["title_az"],
        message=row["message"],
        scope=AnnouncementScope(row["scope"]),
        target_store_ids=target_store_ids,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_active=bool(row["is_active"]),
        deactivated_at=row["deactivated_at"],
        deactivated_by=(
            None if row["deactivated_by"] is None else EmployeeId(row["deactivated_by"])
        ),
        # BƏRPA hadisə YAYMIR — əks halda hər siyahı oxunuşu "yeni elan
        # dərc olundu" bildirişi doğurardı.
        emit_created_event=False,
    )


__all__ = ["PostgresAnnouncementRepository"]
