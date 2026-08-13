"""Diskret texniki dəstək chat-i — TENANT tərəfi (spesifikasiya bölmə 8).

    "Tenant tərəfdəki tətbiqdə, ekranın küncündə kiçik, diqqət çəkməyən bir
     dəstək ikonu yerləşir... uyğun icazəsi olan istifadəçi (`can_contact_support`)
     birbaşa hazırlayıcıya mesaj yaza bilir. Digər rollar üçün bu ikon UI-dan
     ümumiyyətlə render olunmur."

──────────────────────────────────────────────────────────────────────────────
İKİ TƏRƏF, BİR CƏDVƏL
──────────────────────────────────────────────────────────────────────────────
Hazırlayıcı tərəfi (`application/use_cases/developer_console.py` → `SupportInbox`)
EYNİ `support_tickets`/`support_messages` cədvəllərini OXUYUR, amma
`service_role` açarı ilə və bütün tenant-lar üzrə. Bu modul isə tenant-ın öz
`anon` kontekstindədir və YALNIZ öz sətirlərini görür (RLS + açıq `tenant_id`
şərti).

Ona görə burada SLA hesablaması YOXDUR — o, hazırlayıcının göstəricisidir və
müştəriyə göstərilmir. Müştəri yalnız "cavab gəldi/gəlmədi" bilir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ MESAJ AUDİT-LƏNMİR
──────────────────────────────────────────────────────────────────────────────
Digər use case-lərdən fərqli olaraq burada `audit_logs`-a yazı YOXDUR.
Səbəb: mesajın ÖZÜ artıq `support_messages`-də saxlanılır (kim, nə vaxt, nə
yazdı) və audit sətri onu sözbəsöz təkrarlayardı. Audit izi məlumatın İKİNCİ
nüsxəsi üçün deyil, dəyişdirilə bilən vəziyyət üçün lazımdır — bu cədvəl isə
onsuz da append-only istifadə olunur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.application.root_limits import fallback_int, limit_int
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.identifiers import (
    new_support_message_id,
    new_support_ticket_id,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import Clock, FeatureToggles, SystemLimits
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        SupportMessageId,
        SupportTicketId,
        TenantId,
    )

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

CONTACT_SUPPORT_FLAG = "can_contact_support"

MIN_SUBJECT_LENGTH = 3
MAX_SUBJECT_LENGTH = 200
MIN_BODY_LENGTH = 2
MAX_BODY_LENGTH = 4000

#: Widget-in bir oxunuşda gətirdiyi mövzu sayı.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE`, seed: migrations/034). Mətn
#: uzunluğu sabitləri (yuxarıda) QƏSDƏN köçürülmür: onlar `support_messages`
#: sxeminin öz `CHECK` hüdudlarının güzgüsüdür, səhifə ölçüsü isə yalnız
#: üzən panelin nə qədər sətir çəkəcəyini təyin edir.
DEFAULT_THREAD_PAGE_SIZE = fallback_int(SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE)


class SupportAccessError(KompasOSError):
    """Dəstək chat-inə çıxış səlahiyyəti yoxdur."""

    user_message = "Texniki dəstəklə əlaqə səlahiyyətiniz yoxdur."


class SupportMessageError(KompasOSError):
    """Mesaj yararsızdır."""

    user_message = "Mesaj göndərilə bilmədi."


class TicketNotFoundError(SupportMessageError):
    user_message = "Müraciət tapılmadı."


@dataclass(frozen=True)
class SupportMessage:
    """Bir chat balonu."""

    message_id: SupportMessageId
    ticket_id: SupportTicketId
    body: str
    created_at: datetime
    is_from_developer: bool
    sender_id: EmployeeId | None = None


@dataclass(frozen=True)
class SupportThread:
    """Bir müraciət və onun bütün mesajları."""

    ticket_id: SupportTicketId
    subject: str
    status: str
    created_at: datetime
    messages: list[SupportMessage]
    unread_from_developer: int = 0

    @property
    def is_open(self) -> bool:
        return self.status != "CLOSED"

    @property
    def last_message(self) -> SupportMessage | None:
        return self.messages[-1] if self.messages else None


@runtime_checkable
class SupportTicketRepository(Protocol):
    """`support_tickets` + `support_messages` — tenant tərəfi."""

    def open_ticket(
        self,
        *,
        ticket_id: SupportTicketId,
        tenant_id: TenantId,
        opened_by: EmployeeId,
        subject: str,
    ) -> None: ...

    def get_thread(self, ticket_id: SupportTicketId) -> SupportThread | None: ...

    def list_threads(
        self, tenant_id: TenantId, *, limit: int = DEFAULT_THREAD_PAGE_SIZE
    ) -> list[SupportThread]: ...

    def find_open_ticket(self, tenant_id: TenantId) -> SupportTicketId | None:
        """Açıq müraciət varsa onu qaytarır — yeni thread yaratmamaq üçün."""
        ...

    def append_message(
        self,
        *,
        message_id: SupportMessageId,
        ticket_id: SupportTicketId,
        sender_id: EmployeeId | None,
        body: str,
        is_from_developer: bool,
    ) -> None: ...

    def mark_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        """Oxunmamış nişanını (badge) təmizləyir."""
        ...


class SupportChatUseCase:
    """Diskret dəstək widget-inin arxa tərəfi."""

    def __init__(
        self,
        *,
        tickets: SupportTicketRepository,
        toggles: FeatureToggles,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        # `limits` İSTƏYƏ BAĞLIDIR: `None` halında mövzu səhifəsi
        # `DEFAULT_THREAD_PAGE_SIZE` fallback-ıdır — davranış köçürmədən
        # ƏVVƏLKİ ilə HƏRFƏN eynidir.
        self._tickets = tickets
        self._toggles = toggles
        self._clock = clock
        self._limits = limits

    # ------------------------------ görünürlük ------------------------------- #

    def is_available(self, *, tenant_id: TenantId, actor: Employee) -> bool:
        """Widget ümumiyyətlə render olunmalıdırmı (bölmə 8).

        İSTİSNA ATMIR: bu, "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipinin UI
        tərəfidir — səlahiyyəti olmayan istifadəçi üçün ikon SADƏCƏ YOXDUR,
        xəta mesajı görmür.
        """
        if not self._toggles.is_enabled(tenant_id, FeatureModule.SUPPORT_CHAT.value):
            return False
        return actor.has_permission(CONTACT_SUPPORT_FLAG, now=self._clock.now())

    # ------------------------------- oxuma ----------------------------------- #

    def threads(self, *, tenant_id: TenantId, actor: Employee) -> list[SupportThread]:
        self._require_access(tenant_id, actor)
        return self._tickets.list_threads(tenant_id, limit=self._thread_page_size(tenant_id))

    def thread(
        self, *, tenant_id: TenantId, actor: Employee, ticket_id: SupportTicketId
    ) -> SupportThread:
        self._require_access(tenant_id, actor)
        return self._require_thread(ticket_id)

    def unread_count(self, *, tenant_id: TenantId, actor: Employee) -> int:
        """Bildiriş nöqtəsi (badge) üçün — "kiçik, nəzakətli" (bölmə 8)."""
        if not self.is_available(tenant_id=tenant_id, actor=actor):
            return 0
        return sum(
            thread.unread_from_developer
            for thread in self._tickets.list_threads(
                tenant_id, limit=self._thread_page_size(tenant_id)
            )
        )

    def _thread_page_size(self, tenant_id: TenantId) -> int:
        """ROOT limiti — mənbə `system_limits`, modul sabiti yalnız fallback."""
        return limit_int(self._limits, tenant_id, SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE)

    # ------------------------------ göndərmə --------------------------------- #

    def send(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        body: str,
        subject: str = "",
    ) -> SupportThread:
        """Mesaj göndərir; açıq müraciət yoxdursa yenisini açır.

        Hər mesaj üçün yeni thread YARADILMIR — bölmə 8 hazırlayıcı tərəfdə
        "tenant-üzrə ayrı thread-lər" tələb edir, yəni söhbət davam edən bir
        xətdir. Yeni thread yalnız əvvəlki bağlandıqdan sonra açılır.
        """
        self._require_access(tenant_id, actor)
        cleaned_body = _clean(body, MIN_BODY_LENGTH, MAX_BODY_LENGTH, label="Mesaj")

        ticket_id = self._tickets.find_open_ticket(tenant_id)
        if ticket_id is None:
            resolved_subject = subject.strip() or _subject_from(cleaned_body)
            resolved_subject = _clean(
                resolved_subject, MIN_SUBJECT_LENGTH, MAX_SUBJECT_LENGTH, label="Mövzu"
            )
            ticket_id = new_support_ticket_id()
            self._tickets.open_ticket(
                ticket_id=ticket_id,
                tenant_id=tenant_id,
                opened_by=actor.id,
                subject=resolved_subject,
            )

        self._tickets.append_message(
            message_id=new_support_message_id(),
            ticket_id=ticket_id,
            sender_id=actor.id,
            body=cleaned_body,
            is_from_developer=False,
        )
        return self._require_thread(ticket_id)

    def mark_read(
        self, *, tenant_id: TenantId, actor: Employee, ticket_id: SupportTicketId
    ) -> None:
        """İstifadəçi paneli açdı — badge sıfırlanır."""
        self._require_access(tenant_id, actor)
        self._tickets.mark_read(ticket_id, up_to=self._clock.now())

    # ------------------------------- köməkçi --------------------------------- #

    def _require_thread(self, ticket_id: SupportTicketId) -> SupportThread:
        thread = self._tickets.get_thread(ticket_id)
        if thread is None:
            raise TicketNotFoundError(
                "Dəstək müraciəti tapılmadı", context={"ticket_id": str(ticket_id)}
            )
        return thread

    def _require_access(self, tenant_id: TenantId, actor: Employee) -> None:
        if not self._toggles.is_enabled(tenant_id, FeatureModule.SUPPORT_CHAT.value):
            raise SupportAccessError(
                "SUPPORT_CHAT modulu deaktiv edilib",
                user_message="Dəstək chat-i hazırda aktiv deyil.",
                context={"module": FeatureModule.SUPPORT_CHAT.value},
            )
        if not actor.has_permission(CONTACT_SUPPORT_FLAG, now=self._clock.now()):
            _security_log.warning(
                "SUPPORT_ACCESS_DENIED",
                extra={"actor_id": str(actor.id), "flag": CONTACT_SUPPORT_FLAG},
            )
            raise SupportAccessError(
                f"«{CONTACT_SUPPORT_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


def _clean(raw: str, minimum: int, maximum: int, *, label: str) -> str:
    cleaned = " ".join(raw.split())
    if len(cleaned) < minimum:
        raise SupportMessageError(
            f"{label} minimum {minimum} simvol olmalıdır",
            user_message=f"{label} çox qısadır.",
            context={"length": len(cleaned)},
        )
    if len(cleaned) > maximum:
        raise SupportMessageError(
            f"{label} maksimum {maximum} simvol ola bilər",
            user_message=f"{label} çox uzundur.",
            context={"length": len(cleaned)},
        )
    return cleaned


def _subject_from(body: str) -> str:
    """Mövzu verilməyibsə mesajın ilk hissəsindən düzəldilir.

    Boş mövzu ilə müraciət açmaq hazırlayıcı inbox-unda "(başlıqsız)" sətirlər
    yaradardı və 21 tenant-ın müraciətini bir-birindən ayırmaq çətinləşərdi.
    """
    words = body.split()
    snippet = " ".join(words[:8])
    return snippet if len(snippet) <= MAX_SUBJECT_LENGTH else snippet[:MAX_SUBJECT_LENGTH]


__all__ = [
    "CONTACT_SUPPORT_FLAG",
    "DEFAULT_THREAD_PAGE_SIZE",
    "SupportAccessError",
    "SupportChatUseCase",
    "SupportMessage",
    "SupportMessageError",
    "SupportThread",
    "SupportTicketRepository",
    "TicketNotFoundError",
]
