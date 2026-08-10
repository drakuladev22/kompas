"""Dəstək chat-i repository-si — TENANT tərəfi (bölmə 8) — Faza 5.

`developer_directory.support_tickets()` EYNİ cədvəlləri oxuyur, amma
`service_role` ilə və bütün tenant-lar üzrə. Buradakı sinif isə müştərinin öz
`anon` kontekstindədir: hər sorğuda açıq `tenant_id` şərti var və RLS ikinci
qat kimi işləyir (bax `config_repositories.py` başlığı, defense-in-depth).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.application.use_cases.support_chat import SupportMessage, SupportThread
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import (
        EmployeeId,
        SupportMessageId,
        SupportTicketId,
        TenantId,
    )


class PostgresSupportTicketRepository(_BaseRepository):
    """`support_tickets` + `support_messages` (tenant görünüşü)."""

    _SELECT_TICKET = """
        SELECT t.id, t.subject, t.status, t.created_at, t.customer_last_read_at
        FROM support_tickets t
    """

    def open_ticket(
        self,
        *,
        ticket_id: SupportTicketId,
        tenant_id: TenantId,
        opened_by: EmployeeId,
        subject: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO support_tickets (id, tenant_id, opened_by, subject, status)
            VALUES (%s, %s, %s, %s, 'OPEN')
            """,
            (ticket_id, tenant_id, opened_by, subject),
        )

    def find_open_ticket(self, tenant_id: TenantId) -> SupportTicketId | None:
        """Ən son AÇIQ müraciət.

        `WAITING_CUSTOMER` də "açıq" sayılır: hazırlayıcı sual verib cavab
        gözləyir, yəni müştərinin növbəti mesajı məhz həmin söhbətin davamıdır.
        """
        row = self._fetch_one(
            """
            SELECT id FROM support_tickets
            WHERE tenant_id = %s AND status <> 'CLOSED'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (tenant_id,),
        )
        return row["id"] if row else None

    def get_thread(self, ticket_id: SupportTicketId) -> SupportThread | None:
        row = self._fetch_one(
            f"{self._SELECT_TICKET} WHERE t.id = %s AND t.tenant_id = %s",
            (ticket_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def list_threads(self, tenant_id: TenantId, *, limit: int = 20) -> list[SupportThread]:
        rows = self._fetch_all(
            f"""{self._SELECT_TICKET}
            WHERE t.tenant_id = %s
            ORDER BY t.updated_at DESC
            LIMIT %s
            """,
            (tenant_id, limit),
        )
        return [self._hydrate(row) for row in rows]

    def append_message(
        self,
        *,
        message_id: SupportMessageId,
        ticket_id: SupportTicketId,
        sender_id: EmployeeId | None,
        body: str,
        is_from_developer: bool,
    ) -> None:
        self._execute(
            """
            INSERT INTO support_messages
                (id, ticket_id, sender_id, body, is_from_developer)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (message_id, ticket_id, sender_id, body, is_from_developer),
        )
        # `updated_at` trigger-i UPDATE tələb edir — mesaj əlavəsi ticket-i
        # siyahının başına qaldırmalıdır, əks halda yeni cavab köhnə
        # müraciətlərin altında qalardı.
        self._execute(
            "UPDATE support_tickets SET status = status WHERE id = %s",
            (ticket_id,),
        )

    def mark_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        self._execute(
            """
            UPDATE support_tickets
            SET customer_last_read_at = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (up_to, ticket_id, self._tenant),
        )

    # ------------------------------- köməkçi --------------------------------- #

    def _hydrate(self, row: dict[str, Any]) -> SupportThread:
        message_rows = self._fetch_all(
            """
            SELECT id, ticket_id, sender_id, body, is_from_developer, created_at
            FROM support_messages
            WHERE ticket_id = %s
            ORDER BY created_at
            """,
            (row["id"],),
        )
        last_read = row["customer_last_read_at"]
        messages = [
            SupportMessage(
                message_id=item["id"],
                ticket_id=item["ticket_id"],
                body=item["body"],
                created_at=item["created_at"],
                is_from_developer=bool(item["is_from_developer"]),
                sender_id=item["sender_id"],
            )
            for item in message_rows
        ]
        unread = sum(
            1
            for item in messages
            if item.is_from_developer and (last_read is None or item.created_at > last_read)
        )
        return SupportThread(
            ticket_id=row["id"],
            subject=row["subject"],
            status=row["status"],
            created_at=row["created_at"],
            messages=messages,
            unread_from_developer=unread,
        )


__all__ = ["PostgresSupportTicketRepository"]
