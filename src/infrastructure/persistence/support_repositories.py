"""Dəstək chat-i repository-si — TENANT tərəfi (bölmə 8 + CHAT-1).

`developer_directory.support_tickets()` EYNİ cədvəlləri oxuyur, amma
`service_role` ilə və bütün tenant-lar üzrə. Buradakı sinif isə müştərinin öz
`anon` kontekstindədir: hər sorğuda açıq `tenant_id` şərti var və RLS ikinci
qat kimi işləyir (bax `config_repositories.py` başlığı, defense-in-depth).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SİYAHI SORĞUSU İŞÇİ/VƏZİFƏ/MAĞAZA İLƏ BİRLƏŞDİRİLİR
──────────────────────────────────────────────────────────────────────────────
Gələnlər qutusunun sol paneli hər sətirdə filial, işçi adı və vəzifə göstərir
(Faza 6), Telegram başlığı isə eyni üç sahəni tələb edir (Faza 4). Bu
məlumatı sonradan sətir-sətir soruşmaq 20 söhbət üçün 60 əlavə sorğu
demək olardı (N+1) — halbuki `LEFT JOIN` onu bir sorğuda gətirir.

`LEFT` qəsdəndir: işçi deaktiv edilə və ya mağazası silinə bilər
(`ON DELETE SET NULL`), amma onun MÜRACİƏTİ qalmalıdır. `INNER JOIN`
belə söhbətləri siyahıdan sükutla çıxarardı.

──────────────────────────────────────────────────────────────────────────────
MESAJ SƏTİRLƏRİ NİYƏ AYRI SORĞUDADIR
──────────────────────────────────────────────────────────────────────────────
Söhbət başına orta 10 mesaj var; onları eyni `JOIN`-ə qatsaydıq, hər ticket
sətri mesaj sayı qədər təkrarlanar və 20 söhbətlik siyahı 200 sətir gətirərdi.
Sətirlərin çoxu isə YALNIZ son mesajı göstərən sol paneldə istifadə
olunmayacaqdı. Ona görə `_hydrate` mesajları AYRI, TƏK sorğu ilə gətirir
(`WHERE ticket_id = ANY(...)`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.application.use_cases.support_chat import (
    MESSAGE_REF_PREFIX,
    SupportMessage,
    SupportThread,
)
from src.domain.value_objects.identifiers import SupportTicketId
from src.domain.value_objects.support import SupportChannel, SupportTicketStatus
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import (
        EmployeeId,
        StoreId,
        SupportMessageId,
        TenantId,
    )


class PostgresSupportTicketRepository(_BaseRepository):
    """`support_tickets` + `support_messages` (tenant görünüşü)."""

    _SELECT_TICKET = """
        SELECT t.id, t.subject, t.status, t.created_at, t.customer_last_read_at,
               t.staff_last_read_at, t.channel, t.is_urgent, t.opened_by,
               t.updated_at,
               e.first_name, e.last_name, e.store_id,
               p.name_az AS position_name, p.code AS position_code,
               s.name AS store_name
        FROM support_tickets t
        LEFT JOIN employees e ON e.id = t.opened_by
        LEFT JOIN positions p ON p.id = e.position_id
        LEFT JOIN stores    s ON s.id = e.store_id
    """

    #: «Oxunmamış» şərti — SƏTİR kimi saxlanılır, çünki HƏM siyahı sorğusunda,
    #: HƏM say sorğusunda EYNİ olmalıdır. İki yerdə ayrıca yazılsaydı, biri
    #: dəyişəndə süzgəc və say bir-birindən sükutla ayrılardı.
    _UNREAD_CONDITION = """EXISTS (
        SELECT 1 FROM support_messages m
         WHERE m.ticket_id = t.id
           AND m.is_from_developer = FALSE
           AND (t.staff_last_read_at IS NULL OR m.created_at > t.staff_last_read_at)
    )"""

    def open_ticket(
        self,
        *,
        ticket_id: SupportTicketId,
        tenant_id: TenantId,
        opened_by: EmployeeId,
        subject: str,
        channel: SupportChannel = SupportChannel.TECHNICAL,
        is_urgent: bool = False,
    ) -> None:
        self._execute(
            """
            INSERT INTO support_tickets
                (id, tenant_id, opened_by, subject, status, channel, is_urgent)
            VALUES (%s, %s, %s, %s, 'OPEN', %s, %s)
            """,
            (ticket_id, tenant_id, opened_by, subject, channel.value, is_urgent),
        )

    def find_open_ticket(
        self,
        tenant_id: TenantId,
        *,
        channel: SupportChannel = SupportChannel.TECHNICAL,
        opened_by: EmployeeId | None = None,
    ) -> SupportTicketId | None:
        """Həmin işçinin həmin kanaldakı ən son AÇIQ müraciəti.

        `WAITING_CUSTOMER` də "açıq" sayılır: cavablayan tərəf sual verib
        cavab gözləyir, yəni işçinin növbəti mesajı məhz həmin söhbətin
        davamıdır.
        """
        # INF2-02: bax `_filter_sql`-dəki eyni izah.
        conditions = ["tenant_id = %s", "status <> 'CLOSED'", "channel = %s"]
        params: list[Any] = [self._require_matching_tenant(tenant_id), channel.value]
        if opened_by is not None:
            conditions.append("opened_by = %s")
            params.append(opened_by)
        # Şərtlər SABİT sətir siyahısındandır; hər dəyər %s ilə bağlanır.
        where = " AND ".join(conditions)
        row = self._fetch_one(
            f"""
            SELECT id FROM support_tickets
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT 1
            """,  # noqa: S608 — şərtlər sabit siyahıdandır, dəyərlər %s ilə bağlanır
            tuple(params),
        )
        return _ticket_id(row)

    def get_thread(self, ticket_id: SupportTicketId) -> SupportThread | None:
        row = self._fetch_one(
            f"{self._SELECT_TICKET} WHERE t.id = %s AND t.tenant_id = %s",
            (ticket_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def _filter_sql(
        self,
        tenant_id: TenantId,
        *,
        channel: SupportChannel | None,
        opened_by: EmployeeId | None = None,
        status: SupportTicketStatus | None = None,
        store_ids: tuple[StoreId, ...] = (),
        position_codes: tuple[str, ...] = (),
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        unread_only: bool = False,
        search: str = "",
    ) -> tuple[str, list[Any]]:
        """Kombinə süzgəclərin `WHERE` hissəsi — SİYAHI və SAY üçün ORTAQ.

        Ayrı-ayrı qursaydıq, `🔴 Açıq (12)` yazan sayğac başqa şərtlərlə
        işləyə bilər və istifadəçi 12 yazan düyməni basıb 9 sətir görərdi.
        """
        # INF2-02: `tenant_id` arqumenti bağlantının ÖZ kontekstiylə UYĞUN
        # olmalıdır — uyğunsuzluqda GURULTULU xəta (bax `_require_matching_
        # tenant` şərhi, `repositories.py`). Bu, HƏM `list_threads`, HƏM DƏ
        # `count_by_status`-un ORTAQ yoludur — bir yerdə düzəliş ikisini əhatə edir.
        conditions = ["t.tenant_id = %s"]
        params: list[Any] = [self._require_matching_tenant(tenant_id)]
        if channel is not None:
            conditions.append("t.channel = %s")
            params.append(channel.value)
        if opened_by is not None:
            conditions.append("t.opened_by = %s")
            params.append(opened_by)
        if status is not None:
            conditions.append("t.status = %s")
            params.append(status.value)
        if store_ids:
            # `= ANY(%s)` — çox-seçimli filial süzgəci TƏK parametrlə
            # bağlanır; `IN (...)` dinamik sayda `%s` tələb edərdi.
            conditions.append("e.store_id = ANY(%s)")
            params.append(list(store_ids))
        if position_codes:
            conditions.append("p.code = ANY(%s)")
            params.append(list(position_codes))
        if created_from is not None:
            # TARİX SÜZGƏCİ `updated_at`-A BAXIR, `created_at`-a YOX.
            #
            # Bu, gələnlər qutusudur: «bu həftə» sualının mənası «bu həftə
            # HƏRƏKƏT olan müraciətlər»dir. `created_at` seçsəydik, keçən ay
            # açılıb bu gün cavab yazılan söhbət «bu həftə» kəsimindən
            # düşərdi — halbuki məhz o, diqqət tələb edir.
            conditions.append("t.updated_at >= %s")
            params.append(created_from)
        if created_to is not None:
            conditions.append("t.updated_at <= %s")
            params.append(created_to)
        if unread_only:
            conditions.append(self._UNREAD_CONDITION)
        if search:
            # Ad, vəzifə, filial, mövzu VƏ mesaj mətni üzrə — istifadəçi
            # hansı sözü yazdığını əvvəlcədən seçmir (tg1.md: «işçi adı VƏ
            # mesaj mətni üzrə»).
            conditions.append(
                "(t.subject ILIKE %s OR s.name ILIKE %s"
                " OR (e.first_name || ' ' || e.last_name) ILIKE %s"
                " OR EXISTS (SELECT 1 FROM support_messages sm"
                "            WHERE sm.ticket_id = t.id AND sm.body ILIKE %s))"
            )
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern, pattern])
        # Şərtlər SABİT sətir siyahısındandır; hər dəyər %s ilə bağlanır.
        return " AND ".join(conditions), params

    def list_threads(
        self,
        tenant_id: TenantId,
        *,
        limit: int = 20,
        channel: SupportChannel | None = None,
        opened_by: EmployeeId | None = None,
        status: SupportTicketStatus | None = None,
        store_ids: tuple[StoreId, ...] = (),
        position_codes: tuple[str, ...] = (),
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        unread_only: bool = False,
        search: str = "",
        newest_first: bool = True,
    ) -> list[SupportThread]:
        where, params = self._filter_sql(
            tenant_id,
            channel=channel,
            opened_by=opened_by,
            status=status,
            store_ids=store_ids,
            position_codes=position_codes,
            created_from=created_from,
            created_to=created_to,
            unread_only=unread_only,
            search=search,
        )
        # SIRALAMA İKİ AÇARLIDIR: əvvəl status qrupu («mənim işim» yuxarıda),
        # sonra vaxt. `CASE` sırası `SupportTicketStatus.sort_rank` ilə EYNİ
        # olmalıdır — ikisi ayrılsaydı, siyahı ekranda gözlənilməz sıçrayardı.
        direction = "DESC" if newest_first else "ASC"
        params.append(limit)
        rows = self._fetch_all(
            f"""{self._SELECT_TICKET}
            WHERE {where}
            ORDER BY CASE t.status
                         WHEN 'OPEN' THEN 0
                         WHEN 'WAITING_CUSTOMER' THEN 1
                         WHEN 'RESOLVED' THEN 2
                         WHEN 'CLOSED' THEN 3
                         ELSE 0
                     END,
                     t.updated_at {direction}
            LIMIT %s
            """,
            tuple(params),
        )
        return [self._hydrate(row) for row in rows]

    def status_counts(
        self,
        tenant_id: TenantId,
        *,
        channel: SupportChannel,
        store_ids: tuple[StoreId, ...] = (),
        position_codes: tuple[str, ...] = (),
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        unread_only: bool = False,
        search: str = "",
    ) -> dict[str, int]:
        """Status üzrə saylar — `t.status` ÜZRƏ QRUPLAŞDIRMA, TƏK sorğu.

        Dörd ayrı `count(*)` sorğusu yazmaq daha oxunaqlı görünürdü, lakin
        onlar arasında qısa müddət keçir və eyni anda gələn mesaj sayları
        bir-birinə uyğunsuz göstərə bilərdi.
        """
        where, params = self._filter_sql(
            tenant_id,
            channel=channel,
            store_ids=store_ids,
            position_codes=position_codes,
            created_from=created_from,
            created_to=created_to,
            unread_only=unread_only,
            search=search,
        )
        rows = self._fetch_all(
            f"""
            SELECT t.status AS status, count(*) AS total
            FROM support_tickets t
            LEFT JOIN employees e ON e.id = t.opened_by
            LEFT JOIN positions p ON p.id = e.position_id
            LEFT JOIN stores    s ON s.id = e.store_id
            WHERE {where}
            GROUP BY t.status
            """,  # noqa: S608 — şərtlər sabit siyahıdandır, dəyərlər %s ilə bağlanır
            tuple(params),
        )
        return {str(row["status"]): int(row["total"]) for row in rows}

    def position_options(self, tenant_id: TenantId) -> list[tuple[str, str]]:
        """«Vəzifə üzrə» süzgəci — YALNIZ MÜRACİƏTİ OLAN vəzifələr.

        Bütün vəzifələri göstərsəydik, siyahının çoxu həmişə boş nəticə verən
        bəndlərdən ibarət olardı (kirayəçidə 20+ custom rol ola bilər).
        """
        rows = self._fetch_all(
            """
            SELECT DISTINCT p.code AS code, p.name_az AS name
            FROM support_tickets t
            JOIN employees e ON e.id = t.opened_by
            JOIN positions p ON p.id = e.position_id
            WHERE t.tenant_id = %s
            ORDER BY p.name_az
            """,
            (tenant_id,),
        )
        return [(str(row["code"]), str(row["name"])) for row in rows]

    def append_message(
        self,
        *,
        message_id: SupportMessageId,
        ticket_id: SupportTicketId,
        sender_id: EmployeeId | None,
        body: str,
        is_from_developer: bool,
        from_telegram: bool = False,
        attachment_name: str = "",
    ) -> None:
        self._execute(
            """
            INSERT INTO support_messages
                (id, ticket_id, sender_id, body, is_from_developer, from_telegram,
                 attachment_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                message_id,
                ticket_id,
                sender_id,
                body,
                is_from_developer,
                from_telegram,
                attachment_name or None,
            ),
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

    def mark_staff_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        self._execute(
            """
            UPDATE support_tickets
            SET staff_last_read_at = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (up_to, ticket_id, self._tenant),
        )

    def set_status(
        self, ticket_id: SupportTicketId, *, status: SupportTicketStatus, at: datetime
    ) -> None:
        """Statusu VƏ ona aid taymer sütunlarını birlikdə yazır.

        HƏR KEÇİDDƏ ÜÇ SÜTUN DA YAZILIR (biri dəyər, ikisi `NULL`), çünki
        köhnə taymer qalsaydı avtomatika səhv işləyərdi: `RESOLVED`-dən
        `OPEN`-a qayıdan söhbətin köhnə `resolved_at`-i onu dərhal yenidən
        bağlanmağa namizəd edərdi.

        `reminded_at` da sıfırlanır: `WAITING`-ə YENİDƏN düşən söhbət yeni
        xatırlatma haqqı qazanır — əks halda ikinci gözləmə dövrü sükutla
        xatırlatmasız qalardı.
        """
        closed_at = at if status is SupportTicketStatus.CLOSED else None
        resolved_at = at if status is SupportTicketStatus.RESOLVED else None
        waiting_since = at if status is SupportTicketStatus.WAITING else None
        self._execute(
            """
            UPDATE support_tickets
            SET status = %s, closed_at = %s, resolved_at = %s,
                waiting_since = %s, reminded_at = NULL
            WHERE id = %s AND tenant_id = %s
            """,
            (status.value, closed_at, resolved_at, waiting_since, ticket_id, self._tenant),
        )

    def due_for_auto_close(self, tenant_id: TenantId, *, before: datetime) -> list[SupportTicketId]:
        rows = self._fetch_all(
            """
            SELECT id FROM support_tickets
            WHERE tenant_id = %s AND status = 'RESOLVED'
              AND resolved_at IS NOT NULL AND resolved_at <= %s
            """,
            (tenant_id, before),
        )
        return [SupportTicketId(row["id"]) for row in rows]

    def due_for_reminder(
        self, tenant_id: TenantId, *, before: datetime
    ) -> list[tuple[SupportTicketId, EmployeeId | None, str]]:
        """`reminded_at IS NULL` şərti xatırlatmanı BİR dəfəyə məhdudlaşdırır."""
        rows = self._fetch_all(
            """
            SELECT id, opened_by, subject FROM support_tickets
            WHERE tenant_id = %s AND status = 'WAITING_CUSTOMER'
              AND waiting_since IS NOT NULL AND waiting_since <= %s
              AND reminded_at IS NULL
            """,
            (tenant_id, before),
        )
        return [(SupportTicketId(row["id"]), row["opened_by"], str(row["subject"])) for row in rows]

    def mark_reminded(self, ticket_id: SupportTicketId, *, at: datetime) -> None:
        self._execute(
            """
            UPDATE support_tickets
            SET reminded_at = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (at, ticket_id, self._tenant),
        )

    def raise_urgency(self, ticket_id: SupportTicketId) -> None:
        self._execute(
            """
            UPDATE support_tickets
            SET is_urgent = TRUE
            WHERE id = %s AND tenant_id = %s
            """,
            (ticket_id, self._tenant),
        )

    def next_message_reference(self) -> str:
        """`#msg_XXXX` — nömrə DB ardıcıllığındandır (migrations/068 §6)."""
        row = self._fetch_one("SELECT nextval('support_message_ref_seq') AS value", ())
        number = int(row["value"]) if row else 0
        return f"{MESSAGE_REF_PREFIX}{number}"

    def record_telegram_delivery(
        self,
        message_id: SupportMessageId,
        *,
        reference: str,
        telegram_message_id: int | None,
        sent_at: datetime,
    ) -> None:
        self._execute(
            """
            UPDATE support_messages
            SET telegram_ref = %s, telegram_message_id = %s, telegram_sent_at = %s
            WHERE id = %s
            """,
            (reference, telegram_message_id, sent_at, message_id),
        )

    def attach_file(self, message_id: SupportMessageId, *, reference: str, filename: str) -> None:
        """Yüklənmiş şəklin Drive istinadını yazır.

        `attachment_name` DA yenilənir: fayl adı `enqueue` anında da yazılır,
        lakin fon işçisi Drive-ın qaytardığı adı bilir və ikisi fərqlənə
        bilər (provider adı təmizləyir). Ekranda FAKTİKİ ad görünməlidir.
        """
        self._execute(
            """
            UPDATE support_messages
            SET attachment_ref = %s, attachment_name = %s
            WHERE id = %s
            """,
            (reference, filename, message_id),
        )

    def find_ticket_by_reference(
        self, *, reference: str = "", telegram_message_id: int | None = None
    ) -> SupportTicketId | None:
        """Telegram cavabının aid olduğu müraciət.

        SIRA VACİBDİR: əvvəlcə Telegram-ın ÖZ mesaj nömrəsi yoxlanılır
        (dəqiq uyğunluq), sonra mətn istinadı. Tərsi olsaydı, istifadəçinin
        əl ilə kopyaladığı köhnə `#msg_` sətri düzgün reply-dan ÜSTÜN
        tutulardı.

        `tenant_id` şərti `support_tickets` üzərindədir: `support_messages`-də
        belə sütun yoxdur və istinad yalnız ticket vasitəsilə kirayəçiyə
        bağlanır.
        """
        if telegram_message_id is not None:
            row = self._fetch_one(
                """
                SELECT m.ticket_id AS id
                FROM support_messages m
                JOIN support_tickets t ON t.id = m.ticket_id
                WHERE m.telegram_message_id = %s AND t.tenant_id = %s
                LIMIT 1
                """,
                (telegram_message_id, self._tenant),
            )
            if row:
                return _ticket_id(row)
        if reference:
            row = self._fetch_one(
                """
                SELECT m.ticket_id AS id
                FROM support_messages m
                JOIN support_tickets t ON t.id = m.ticket_id
                WHERE m.telegram_ref = %s AND t.tenant_id = %s
                LIMIT 1
                """,
                (reference, self._tenant),
            )
            if row:
                return _ticket_id(row)
        return None

    def sender_profile(self, employee_id: EmployeeId) -> tuple[str, str, str]:
        row = self._fetch_one(
            """
            SELECT e.first_name, e.last_name, p.name_az AS position_name,
                   s.name AS store_name
            FROM employees e
            LEFT JOIN positions p ON p.id = e.position_id
            LEFT JOIN stores    s ON s.id = e.store_id
            WHERE e.id = %s AND e.tenant_id = %s
            """,
            (employee_id, self._tenant),
        )
        if not row:
            return "", "", ""
        return _full_name(row), str(row["position_name"] or ""), str(row["store_name"] or "")

    # ------------------------------- köməkçi --------------------------------- #

    def _hydrate(self, row: dict[str, Any]) -> SupportThread:
        message_rows = self._fetch_all(
            """
            SELECT id, ticket_id, sender_id, body, is_from_developer, created_at,
                   telegram_ref, telegram_sent_at, from_telegram,
                   attachment_ref, attachment_name
            FROM support_messages
            WHERE ticket_id = %s
            ORDER BY created_at
            """,
            (row["id"],),
        )
        messages = [
            SupportMessage(
                message_id=item["id"],
                ticket_id=item["ticket_id"],
                body=item["body"],
                created_at=item["created_at"],
                is_from_developer=bool(item["is_from_developer"]),
                sender_id=item["sender_id"],
                telegram_ref=item.get("telegram_ref"),
                telegram_sent_at=item.get("telegram_sent_at"),
                from_telegram=bool(item.get("from_telegram")),
                attachment_ref=str(item.get("attachment_ref") or ""),
                attachment_name=str(item.get("attachment_name") or ""),
            )
            for item in message_rows
        ]
        return SupportThread(
            ticket_id=row["id"],
            subject=row["subject"],
            status=row["status"],
            created_at=row["created_at"],
            messages=messages,
            unread_from_developer=_unread(
                messages, since=row.get("customer_last_read_at"), from_developer=True
            ),
            channel=SupportChannel.parse(row.get("channel") or SupportChannel.TECHNICAL.value),
            is_urgent=bool(row.get("is_urgent")),
            unread_from_staff=_unread(
                messages, since=row.get("staff_last_read_at"), from_developer=False
            ),
            opened_by=row.get("opened_by"),
            sender_name=_full_name(row),
            sender_position=str(row.get("position_name") or ""),
            sender_position_code=str(row.get("position_code") or ""),
            store_name=str(row.get("store_name") or ""),
            store_id=row.get("store_id"),
        )


def _ticket_id(row: dict[str, Any] | None) -> SupportTicketId | None:
    """Sətirdəki `id` sütununu tiplənmiş İD-yə çevirir.

    Ayrıca funksiya kimi yazılıb, çünki `psycopg` sətir sözlüyü `Any`
    qaytarır və hər çağırış yerində eyni kastı təkrarlamaq lazım gələrdi.
    """
    return SupportTicketId(row["id"]) if row else None


def _unread(messages: list[SupportMessage], *, since: datetime | None, from_developer: bool) -> int:
    """Oxunmamış sayı — hər iki tərəf üçün EYNİ düstur.

    `since is None` = heç vaxt açılmayıb, yəni HAMISI oxunmamışdır. Sıfır
    qaytarsaydıq, ilk mesaj heç vaxt nişan yaratmazdı.
    """
    return sum(
        1
        for item in messages
        if item.is_from_developer is from_developer and (since is None or item.created_at > since)
    )


def _full_name(row: dict[str, Any]) -> str:
    first = str(row.get("first_name") or "").strip()
    last = str(row.get("last_name") or "").strip()
    return f"{first} {last}".strip()


__all__ = ["PostgresSupportTicketRepository"]
