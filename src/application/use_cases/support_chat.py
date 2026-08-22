"""İki-kanallı dəstək chat-i — TENANT tərəfi (spesifikasiya bölmə 8 + CHAT-1).

    "Tenant tərəfdəki tətbiqdə, ekranın küncündə kiçik, diqqət çəkməyən bir
     dəstək ikonu yerləşir... uyğun icazəsi olan istifadəçi (`can_contact_support`)
     birbaşa hazırlayıcıya mesaj yaza bilir. Digər rollar üçün bu ikon UI-dan
     ümumiyyətlə render olunmur."

──────────────────────────────────────────────────────────────────────────────
CHAT-1: BİR ÜNVAN → İKİ KANAL
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı tələb dəyişmədi, lakin ÜNVAN ikiyə bölündü (`SupportChannel`):
işçi mesajı yazmazdan əvvəl kimə yazdığını seçir. Səbəb və rədd edilən
alternativ (avtomatik təsnifat) `value_objects/support.py` başlığındadır.

Modul İKİ use case saxlayır, çünki onlar EYNİ cədvəlin iki ucudur:

    `SupportChatUseCase`  — İŞÇİ ucu: yazır, öz söhbətini oxuyur.
    `SupportInboxUseCase` — CAVABLAYAN uc: kanalın bütün söhbətlərini görür,
                            cavab yazır, bağlayır/yenidən açır.

Ayrı modullara bölünsəydilər `SupportThread` və repository protokolu ya
təkrarlanar, ya da üçüncü "shared" modul yaranardı — hər ikisi eyni cədvəlin
tərifini iki yerə səpərdi.

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

İSTİSNA: söhbəti BAĞLAMAQ/YENİDƏN AÇMAQ audit-lənir. O, mesaj deyil,
vəziyyət dəyişikliyidir — «müraciətimi kim bağladı?» sualının cavabı başqa
heç bir yerdə qalmır.

──────────────────────────────────────────────────────────────────────────────
TELEGRAM ŞLÜZÜ NİYƏ `None` OLA BİLƏR
──────────────────────────────────────────────────────────────────────────────
`telegram=None` = bot qurulmayıb. Bu, XƏTA DEYİL: müştərinin çoxu Telegram
istifadə etmir və onların texniki müraciəti yalnız proqramdakı bölmədə
görünür. Şlüz məcburi olsaydı, hər quraşdırma bot token tələb edərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.application.root_limits import fallback_int, limit_int, limit_str
from src.domain.policies import FeatureModule, SystemLimitKey, TelegramNotifyMode
from src.domain.value_objects.identifiers import (
    new_support_message_id,
    new_support_ticket_id,
)
from src.domain.value_objects.support import (
    CONTACT_SUPPORT_FLAG,
    VIEW_INTERNAL_FLAG,
    VIEW_TECHNICAL_FLAG,
    SupportChannel,
    SupportTicketStatus,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.text import normalise_decision_text

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        FeatureToggles,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        StoreId,
        SupportMessageId,
        SupportTicketId,
        TenantId,
    )

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

MIN_SUBJECT_LENGTH = 3
MAX_SUBJECT_LENGTH = 200
MIN_BODY_LENGTH = 2
MAX_BODY_LENGTH = 4000

#: `#msg_XXXX` istinadının prefiksi.
#:
#: TƏTBİQ QATINDADIR, infrastrukturda YOX: onu HƏM repozitoriya (nömrə
#: yaradarkən), HƏM Telegram şlüzü (mətnə yazarkən), HƏM də cavab oxuyucusu
#: (mətndən çıxararkən) işlədir. Üç yerin ikisi infrastrukturdadır, üçüncüsü
#: isə burada — sabit onların ORTAQ nöqtəsində saxlanılır ki, formatı bir
#: yerdə dəyişmək kifayət etsin.
MESSAGE_REF_PREFIX = "#msg_"

#: Bağlanmış/açıq söhbətin statusu — TARİXİ ADLAR.
#:
#: Yeni kod `SupportTicketStatus` işlədir; bu iki sabit `_hydrate` və mövcud
#: testlərin işlətdiyi xam sətirlərdir və geriyə uyğunluq üçün qalır.
STATUS_CLOSED = SupportTicketStatus.CLOSED.value
STATUS_OPEN = SupportTicketStatus.OPEN.value

#: İşçiyə gedən xatırlatmanın kateqoriyası (`Notifier.notify`).
REMINDER_CATEGORY = "SUPPORT_WAITING_REMINDER"

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
    """Bir chat balonu.

    `is_from_developer` adı sxemdən gəlir (`support_messages`) və CAVABLAYAN
    TƏRƏFİ bildirir — texniki kanalda bu, hazırlayıcıdır, daxili kanalda isə
    şirkətin öz CEO/Admin/HR-ıdır. Sütunu adlandırmaqdan imtina etmək
    miqrasiya tarixçəsini pozardı, ona görə ad qalır və mənası burada
    yazılır.
    """

    message_id: SupportMessageId
    ticket_id: SupportTicketId
    body: str
    created_at: datetime
    is_from_developer: bool
    sender_id: EmployeeId | None = None
    #: `#msg_XXXX` istinadı — YALNIZ Telegram-a göndərilmiş mesajlarda.
    telegram_ref: str | None = None
    #: `None` = Telegram-a getməyib (ekrandakı sinxronluq göstəricisi).
    telegram_sent_at: datetime | None = None
    #: Telegram-dan REPLY ilə gəlmiş cavab. Ekranda mənbə göstərilir ki,
    #: işçi cavabın haradan yazıldığını bilsin — eyni söhbətdə iki fərqli
    #: yazı yeri var və bunu gizlətmək «kim yazdı?» sualını doğurardı.
    from_telegram: bool = False
    #: Drive istinadı — şəkil YÜKLƏNDİKDƏN sonra dolur (migrations/068).
    #:
    #: BOŞ OLMASI XƏTA DEYİL: fayl əvvəlcə lokal növbəyə düşür və internet
    #: qayıdanda yüklənir. Ekran bu aralığı «yüklənir» kimi göstərir.
    attachment_ref: str = ""
    attachment_name: str = ""

    @property
    def has_attachment(self) -> bool:
        return bool(self.attachment_name)


@dataclass(frozen=True)
class SupportThread:
    """Bir müraciət və onun bütün mesajları."""

    ticket_id: SupportTicketId
    subject: str
    status: str
    created_at: datetime
    messages: list[SupportMessage]
    unread_from_developer: int = 0
    channel: SupportChannel = SupportChannel.TECHNICAL
    is_urgent: bool = False
    #: Cavablayan tərəfin nişanı — işçidən gələn oxunmamış mesaj sayı.
    unread_from_staff: int = 0
    opened_by: EmployeeId | None = None
    #: Gələnlər qutusunun sol paneli üçün (Faza 6). Boş sətir = məlumat
    #: yoxdur (silinmiş işçi/mağaza) — `None` yerinə boş sətir seçildi ki,
    #: ekran hər yerdə `or "—"` yazmasın.
    sender_name: str = ""
    sender_position: str = ""
    #: Vəzifə KODU (`positions.code`) — «vəzifə üzrə» süzgəci adı deyil, kodu
    #: işlədir: ad Root tərəfindən dəyişdirilə bilər, kod isə sabitdir.
    sender_position_code: str = ""
    store_name: str = ""
    store_id: StoreId | None = None

    @property
    def ticket_status(self) -> SupportTicketStatus:
        """Xam sətir → status.

        `status` sahəsi SƏTİR olaraq qalır (repozitoriya və mövcud testlər
        onu belə doldurur); çevirmə tək yerdə, burada aparılır.
        """
        return SupportTicketStatus.parse(self.status)

    @property
    def is_open(self) -> bool:
        """«Cavab yazıla bilərmi» — `RESOLVED` də açıq sayılır (bax status enum)."""
        return self.ticket_status.is_open

    @property
    def last_message(self) -> SupportMessage | None:
        return self.messages[-1] if self.messages else None

    @property
    def has_unread(self) -> bool:
        """Qalın şrift göstəricisi — STATUS DEYİL (tg1.md Faza 6)."""
        return self.unread_from_staff > 0


@dataclass(frozen=True)
class TelegramOutgoing:
    """Telegram-a göndəriləcək texniki müraciət (Faza 4 formatının girişi)."""

    store_name: str
    sender_name: str
    sender_position: str
    sent_at: datetime
    body: str
    reference: str
    is_urgent: bool
    #: Cavab mesajıdırsa TRUE — format başlığı fərqlənir (işçi görmür ki,
    #: hazırlayıcı öz cavabını yenidən özünə göndərib).
    is_reply: bool = False
    #: Şəkil BAYTLARI — Telegram-a `sendPhoto` ilə gedir.
    #:
    #: URL DEYİL, BAYTLAR: Drive linki ictimai deyil və Telegram serveri onu
    #: yükləyə bilməz. Baytlar isə göndərmə anında onsuz da əlimizdədir
    #: (işçi faylı indicə seçib), yəni əlavə oxu tələb olunmur.
    attachment: bytes | None = None
    attachment_name: str = ""


@dataclass(frozen=True)
class TelegramDelivery:
    """Şlüzün nəticəsi — `None` qaytarmaq «göndərilmədi» deməkdir."""

    telegram_message_id: int | None
    sent_at: datetime


@runtime_checkable
class SupportTelegramGateway(Protocol):
    """Telegram Bot API-yə ÇIXAN yol (`infrastructure/notifications/telegram.py`).

    Application qatında təyin olunur, `ports.py`-da YOX: `TelegramOutgoing`
    domen tipi deyil, bu modulun öz strukturudur (CLAUDE.md §3).
    """

    def send_support_message(self, payload: TelegramOutgoing) -> TelegramDelivery | None: ...


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
        channel: SupportChannel,
        is_urgent: bool,
    ) -> None: ...

    def get_thread(self, ticket_id: SupportTicketId) -> SupportThread | None: ...

    def list_threads(
        self,
        tenant_id: TenantId,
        *,
        limit: int = DEFAULT_THREAD_PAGE_SIZE,
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
    ) -> list[SupportThread]: ...

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
        """Süzgəc zolağındakı saylar — STATUS SÜZGƏCİNDƏN BAŞQA hamısı tətbiq olunur.

        Səbəb: say `🔴 Açıq (12)` şəklində GÖSTƏRİLİR, yəni istifadəçi hələ
        həmin statusu SEÇMƏYİB. Statusu da tətbiq etsəydik, seçilməmiş
        bəndlərin sayı həmişə sıfır olardı.
        """
        ...

    def position_options(self, tenant_id: TenantId) -> list[tuple[str, str]]:
        """`(code, ad)` cütləri — «vəzifə üzrə» süzgəci üçün."""
        ...

    def find_open_ticket(
        self, tenant_id: TenantId, *, channel: SupportChannel, opened_by: EmployeeId
    ) -> SupportTicketId | None:
        """Həmin işçinin həmin kanaldakı açıq müraciəti.

        `opened_by` şərti QƏSDƏNdir: kanal üzrə TƏK açıq müraciət olsaydı,
        ikinci işçinin sualı birincinin söhbətinə düşərdi və hər ikisi
        digərinin yazışmasını oxuyardı.
        """
        ...

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
    ) -> None: ...

    def mark_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        """İşçi tərəfin oxunmamış nişanını (badge) təmizləyir."""
        ...

    def mark_staff_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        """Cavablayan tərəfin nişanını təmizləyir."""
        ...

    def set_status(
        self, ticket_id: SupportTicketId, *, status: SupportTicketStatus, at: datetime
    ) -> None:
        """Statusu və ONA AİD taymer sütununu birlikdə yazır.

        İkisi ayrı metod olsaydı, biri çağırılıb digəri unudulduqda söhbət
        «Həll olundu» görünər, lakin heç vaxt avtomatik bağlanmazdı.
        """
        ...

    def due_for_auto_close(self, tenant_id: TenantId, *, before: datetime) -> list[SupportTicketId]:
        """`RESOLVED` statusda `before`-dan əvvəl həll edilmiş müraciətlər."""
        ...

    def due_for_reminder(
        self, tenant_id: TenantId, *, before: datetime
    ) -> list[tuple[SupportTicketId, EmployeeId | None, str]]:
        """(ticket_id, işçi, mövzu) — xatırlatma gözləyən `WAITING` müraciətlər."""
        ...

    def mark_reminded(self, ticket_id: SupportTicketId, *, at: datetime) -> None: ...

    def raise_urgency(self, ticket_id: SupportTicketId) -> None:
        """Təcililik SÖNMÜR — bax migrations/068 §1b."""
        ...

    def next_message_reference(self) -> str:
        """Növbəti `#msg_XXXX` istinadı (DB ardıcıllığından)."""
        ...

    def record_telegram_delivery(
        self,
        message_id: SupportMessageId,
        *,
        reference: str,
        telegram_message_id: int | None,
        sent_at: datetime,
    ) -> None: ...

    def attach_file(self, message_id: SupportMessageId, *, reference: str, filename: str) -> None:
        """Yüklənmiş şəklin istinadını mesaja yazır (fon işçisindən çağırılır)."""
        ...

    def find_ticket_by_reference(
        self, *, reference: str = "", telegram_message_id: int | None = None
    ) -> SupportTicketId | None:
        """Telegram cavabının hansı müraciətə aid olduğu."""
        ...

    def sender_profile(self, employee_id: EmployeeId) -> tuple[str, str, str]:
        """(ad soyad, vəzifə, filial adı) — Telegram başlığı üçün."""
        ...


class _SupportBase:
    """İki use case-in ORTAQ hissəsi: modul qapısı, limitlər, Telegram itələməsi."""

    def __init__(
        self,
        *,
        tickets: SupportTicketRepository,
        toggles: FeatureToggles,
        clock: Clock,
        limits: SystemLimits | None = None,
        telegram: SupportTelegramGateway | None = None,
    ) -> None:
        # `limits` İSTƏYƏ BAĞLIDIR: `None` halında mövzu səhifəsi
        # `DEFAULT_THREAD_PAGE_SIZE` fallback-ıdır — davranış köçürmədən
        # ƏVVƏLKİ ilə HƏRFƏN eynidir.
        self._tickets = tickets
        self._toggles = toggles
        self._clock = clock
        self._limits = limits
        self._telegram = telegram

    # ------------------------------- köməkçi --------------------------------- #

    def _thread_page_size(self, tenant_id: TenantId) -> int:
        """ROOT limiti — mənbə `system_limits`, modul sabiti yalnız fallback."""
        return limit_int(self._limits, tenant_id, SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE)

    def _notify_mode(self, tenant_id: TenantId) -> TelegramNotifyMode:
        return TelegramNotifyMode.from_value(
            limit_str(self._limits, tenant_id, SystemLimitKey.TELEGRAM_NOTIFY_MODE)
        )

    def _module_enabled(self, tenant_id: TenantId) -> bool:
        return self._toggles.is_enabled(tenant_id, FeatureModule.SUPPORT_CHAT.value)

    def _require_thread(self, ticket_id: SupportTicketId) -> SupportThread:
        thread = self._tickets.get_thread(ticket_id)
        if thread is None:
            raise TicketNotFoundError(
                "Dəstək müraciəti tapılmadı", context={"ticket_id": str(ticket_id)}
            )
        return thread

    # ------------------------------- Telegram -------------------------------- #

    def _push_to_telegram(
        self,
        *,
        tenant_id: TenantId,
        thread: SupportThread,
        message_id: SupportMessageId,
        body: str,
        author_id: EmployeeId | None,
        is_reply: bool,
        attachment: bytes | None = None,
        attachment_name: str = "",
    ) -> None:
        """Texniki mesajı Telegram-a itələyir — UĞURSUZLUQ İŞİ DAYANDIRMIR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ İSTİSNA UDULUR
        ──────────────────────────────────────────────────────────────────────
        Bu, CLAUDE.md §5-dəki «audit istisna udmur» qaydasının ƏKSİ deyil,
        onun tamamlayıcısıdır: audit MƏCBURİ daxili zəmanətdir, Telegram isə
        XARİCİ rahatlıq kanalıdır. İnternet kəsiləndə işçinin müraciəti
        `support_messages`-də QALIR və proqramdakı bölmədə görünür — yəni
        heç nə itmir. Tranzaksiyanı geri qaytarsaydıq, əksinə, işçi
        Telegram-ın işlədiyi ana qədər ümumiyyətlə mesaj yaza bilməzdi.

        Göndərilməmə GİZLƏDİLMİR: `telegram_sent_at` NULL qalır və ekran
        bunu «Telegram: göndərilmədi» kimi göstərir (Faza 6).
        """
        if not self._should_notify(tenant_id=tenant_id, thread=thread):
            return
        gateway = self._telegram
        if gateway is None:
            return

        sender_name, sender_position, store_name = self._profile(author_id, thread)
        reference = self._tickets.next_message_reference()
        payload = TelegramOutgoing(
            store_name=store_name,
            sender_name=sender_name,
            sender_position=sender_position,
            sent_at=self._clock.now(),
            body=body,
            reference=reference,
            is_urgent=thread.is_urgent,
            is_reply=is_reply,
            attachment=attachment,
            attachment_name=attachment_name,
        )
        try:
            delivery = gateway.send_support_message(payload)
        except Exception:
            _error_log.exception(
                "TELEGRAM_SUPPORT_PUSH_FAILED",
                extra={"ticket_id": str(thread.ticket_id)},
            )
            return
        if delivery is None:
            return
        self._tickets.record_telegram_delivery(
            message_id,
            reference=reference,
            telegram_message_id=delivery.telegram_message_id,
            sent_at=delivery.sent_at,
        )

    def _should_notify(self, *, tenant_id: TenantId, thread: SupportThread) -> bool:
        """Telegram qapısı — ÜÇ şərtin hamısı ödənməlidir.

        Kanal yoxlaması `SupportChannel.notifies_telegram`-dadır (tərifin öz
        yerində, CLAUDE.md §5 «qayda iki yerdə» prinsipi: burada TƏTBİQ,
        orada TƏRİF).
        """
        if not thread.channel.notifies_telegram:
            return False
        # Faza 7.2: bağlanmış söhbətə yazılan qeyd Telegram-a TƏKRAR düşmür —
        # məsələ həll olunub, bildiriş isə yenidən diqqət tələb edərdi.
        if not thread.is_open:
            return False
        mode = self._notify_mode(tenant_id)
        if mode is TelegramNotifyMode.DISABLED:
            return False
        return not (mode is TelegramNotifyMode.URGENT_ONLY and not thread.is_urgent)

    def _profile(self, author_id: EmployeeId | None, thread: SupportThread) -> tuple[str, str, str]:
        """Telegram başlığındakı üç sətir (filial, ad, vəzifə).

        Mənbə SÖHBƏTİN SAHİBİDİR, mesajın müəllifi deyil: hazırlayıcı öz
        cavabını Telegram-da görəndə də başlıqda MÜRACİƏT EDƏNİ görməlidir —
        əks halda qrup söhbətində «kimin işi idi?» cavabsız qalardı.
        """
        if thread.sender_name or thread.store_name:
            return thread.sender_name, thread.sender_position, thread.store_name
        if thread.opened_by is None:
            return "", "", ""
        try:
            return self._tickets.sender_profile(thread.opened_by)
        except Exception:
            _error_log.exception("SUPPORT_SENDER_PROFILE_FAILED")
            return "", "", ""


class SupportChatUseCase(_SupportBase):
    """Diskret dəstək widget-inin arxa tərəfi — İŞÇİ ucu."""

    # ------------------------------ görünürlük ------------------------------- #

    def is_available(self, *, tenant_id: TenantId, actor: Employee) -> bool:
        """Widget ümumiyyətlə render olunmalıdırmı (bölmə 8).

        İSTİSNA ATMIR: bu, "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipinin UI
        tərəfidir — səlahiyyəti olmayan istifadəçi üçün ikon SADƏCƏ YOXDUR,
        xəta mesajı görmür.
        """
        if not self._module_enabled(tenant_id):
            return False
        return actor.has_permission(CONTACT_SUPPORT_FLAG, now=self._clock.now())

    # ------------------------------- oxuma ----------------------------------- #

    def threads(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        channel: SupportChannel | None = None,
    ) -> list[SupportThread]:
        """İşçinin ÖZ söhbətləri.

        `opened_by` şərti burada məcburidir: widget şəxsi yazışmadır və
        ikinci satıcının müraciətini göstərmək məlumat sızmasıdır.
        """
        self._require_access(tenant_id, actor)
        return self._tickets.list_threads(
            tenant_id,
            limit=self._thread_page_size(tenant_id),
            channel=channel,
            opened_by=actor.id,
        )

    def thread(
        self, *, tenant_id: TenantId, actor: Employee, ticket_id: SupportTicketId
    ) -> SupportThread:
        self._require_access(tenant_id, actor)
        found = self._require_thread(ticket_id)
        if found.opened_by is not None and found.opened_by != actor.id:
            raise SupportAccessError(
                "Başqa işçinin müraciəti",
                user_message="Bu müraciət sizə aid deyil.",
                context={"ticket_id": str(ticket_id)},
            )
        return found

    def unread_count(self, *, tenant_id: TenantId, actor: Employee) -> int:
        """Bildiriş nöqtəsi (badge) üçün — "kiçik, nəzakətli" (bölmə 8)."""
        if not self.is_available(tenant_id=tenant_id, actor=actor):
            return 0
        return sum(
            thread.unread_from_developer
            for thread in self._tickets.list_threads(
                tenant_id, limit=self._thread_page_size(tenant_id), opened_by=actor.id
            )
        )

    # ------------------------------ göndərmə --------------------------------- #

    def send(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        body: str,
        channel: SupportChannel = SupportChannel.TECHNICAL,
        subject: str = "",
        urgent: bool = False,
        attachment: bytes | None = None,
        attachment_name: str = "",
    ) -> SupportThread:
        """Mesaj göndərir; həmin kanalda açıq müraciət yoxdursa yenisini açır.

        Hər mesaj üçün yeni thread YARADILMIR — bölmə 8 hazırlayıcı tərəfdə
        "tenant-üzrə ayrı thread-lər" tələb edir, yəni söhbət davam edən bir
        xətdir (Faza 7.3: «eyni işçidən ardıcıl mesajlar bir thread kimi
        qalsın»). Yeni thread yalnız əvvəlki bağlandıqdan sonra açılır.

        KANAL DƏYİŞMİR: açıq müraciət tapılırsa mesaj ONUN kanalına düşür.
        İşçi «Daxili»dən «Texniki»yə keçmək istəsə, əvvəlki söhbət bağlanmalı
        və ya AYRI kanal seçilməlidir — çünki kanal orta yerdə dəyişsəydi,
        yazışmanın yarısı CEO-nun, yarısı hazırlayıcının qutusunda görünərdi.
        """
        self._require_access(tenant_id, actor)
        cleaned_body = _clean(body, MIN_BODY_LENGTH, MAX_BODY_LENGTH, label="Mesaj")

        ticket_id = self._tickets.find_open_ticket(tenant_id, channel=channel, opened_by=actor.id)
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
                channel=channel,
                is_urgent=urgent,
            )
        elif urgent:
            self._tickets.raise_urgency(ticket_id)

        message_id = new_support_message_id()
        self._tickets.append_message(
            message_id=message_id,
            ticket_id=ticket_id,
            sender_id=actor.id,
            body=cleaned_body,
            is_from_developer=False,
            attachment_name=attachment_name,
        )
        thread = self._require_thread(ticket_id)
        # AVTOMATİK KEÇİD 1 (tg1.md Faza 6): işçi HƏR hansı statusda cavab
        # yazsa söhbət «Açıq»a qayıdır. Bu, `find_open_ticket`-in tapdığı
        # `WAITING`/`RESOLVED` söhbətlərə də aiddir — əks halda cavab
        # yazılmış müraciət nişanda görünməz və sükutla gözlənilərdi.
        if thread.ticket_status is not SupportTicketStatus.OPEN:
            self._tickets.set_status(
                ticket_id, status=SupportTicketStatus.OPEN, at=self._clock.now()
            )
            thread = self._require_thread(ticket_id)
        self._push_to_telegram(
            tenant_id=tenant_id,
            thread=thread,
            message_id=message_id,
            body=cleaned_body,
            author_id=actor.id,
            is_reply=False,
            attachment=attachment,
            attachment_name=attachment_name,
        )
        return self._require_thread(ticket_id)

    def mark_read(
        self, *, tenant_id: TenantId, actor: Employee, ticket_id: SupportTicketId
    ) -> None:
        """İstifadəçi paneli açdı — badge sıfırlanır."""
        self._require_access(tenant_id, actor)
        self._tickets.mark_read(ticket_id, up_to=self._clock.now())

    # ------------------------------- köməkçi --------------------------------- #

    def _require_access(self, tenant_id: TenantId, actor: Employee) -> None:
        if not self._module_enabled(tenant_id):
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


@dataclass(frozen=True)
class InboxFilter:
    """Sol panelin süzgəcləri (tg1.md Faza 6).

    ──────────────────────────────────────────────────────────────────────────
    SÜZGƏCLƏR BİR-BİRİNİ ƏVƏZ ETMİR, ÜST-ÜSTƏ DÜŞÜR
    ──────────────────────────────────────────────────────────────────────────
    Hamısı BİR strukturdadır və repozitoriyaya BİRLİKDƏ ötürülür — «Yataş
    Babək + Yataş Mərkəzi filiallarında, Mağaza Menecerlərindən gələn, bu
    həftə, açıq statuslu» kəsimi tək sorğu ilə alınır. Ayrı-ayrı arqumentlər
    kimi ötürsəydik, çağırış yeri səkkiz parametrlik siyahıya çevrilər və
    hansısa birinin unudulması SÜKUTLA daha geniş nəticə qaytarardı.

    `status=None` «Hamısı» deməkdir. Ekranın DEFOLT seçimi isə `OPEN`-dir
    (tg1.md): panel açılanda «mənim işim» görünməlidir, arxiv yox.
    """

    status: SupportTicketStatus | None = None
    #: Çox-seçimli: boş dəst = bütün filiallar.
    store_ids: tuple[StoreId, ...] = ()
    #: `positions.code` dəyərləri; boş dəst = bütün vəzifələr.
    position_codes: tuple[str, ...] = ()
    created_from: datetime | None = None
    created_to: datetime | None = None
    #: Status süzgəcindən AYRI (tg1.md: «oxunmamış status deyil»).
    unread_only: bool = False
    search: str = ""
    newest_first: bool = True

    @property
    def is_empty(self) -> bool:
        """«Filtrləri Təmizlə» düyməsinin aktivliyi üçün."""
        return not (
            self.status is not None
            or self.store_ids
            or self.position_codes
            or self.created_from is not None
            or self.created_to is not None
            or self.unread_only
            or self.search.strip()
        )


class SupportInboxUseCase(_SupportBase):
    """«Daxili Müraciətlər» və «Texniki Dəstək» bölmələrinin arxa tərəfi.

    HƏR İKİ BÖLMƏ EYNİ SİNİFDƏNDİR (Faza 6: «eyni komponent şablonu»): fərq
    yalnız `channel` arqumentindədir. İki ayrı sinif yazsaydıq, «cavab yaz»
    və «bağla» məntiqini iki yerdə saxlamalı olardıq və Telegram qaydası
    yalnız birində olardı — bu isə məhz CHAT-1-in aradan qaldırdığı
    ikiləşmədir.
    """

    def __init__(
        self,
        *,
        tickets: SupportTicketRepository,
        toggles: FeatureToggles,
        clock: Clock,
        audit: AuditTrail,
        limits: SystemLimits | None = None,
        telegram: SupportTelegramGateway | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        super().__init__(
            tickets=tickets, toggles=toggles, clock=clock, limits=limits, telegram=telegram
        )
        self._audit = audit
        # `notifier` İSTƏYƏ BAĞLIDIR: yalnız «Gözləmədə» xatırlatması üçün
        # lazımdır. Məcburi olsaydı, bildiriş qatı qurulmayan hər test və
        # hər skript bu use case-i ümumiyyətlə qura bilməzdi — halbuki
        # bölmənin bütün qalan işi bildirişsiz də tamdır.
        self._notifier = notifier

    # ------------------------------ görünürlük ------------------------------- #

    def visible_channels(self, *, tenant_id: TenantId, actor: Employee) -> list[SupportChannel]:
        """Bu istifadəçinin naviqasiyasında hansı bölmələr görünür.

        Sıra SABİTdir (daxili → texniki), çünki menyu maddələrinin yeri
        istifadəçinin əzbərlədiyi şeydir və rol dəyişəndə sıçramamalıdır.
        """
        if not self._module_enabled(tenant_id):
            return []
        now = self._clock.now()
        return [
            channel
            for channel in (SupportChannel.INTERNAL, SupportChannel.TECHNICAL)
            if actor.has_permission(channel.viewer_flag, now=now)
        ]

    def can_view(self, *, tenant_id: TenantId, actor: Employee, channel: SupportChannel) -> bool:
        return channel in self.visible_channels(tenant_id=tenant_id, actor=actor)

    # ------------------------------- oxuma ----------------------------------- #

    def threads(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        channel: SupportChannel,
        filters: InboxFilter | None = None,
    ) -> list[SupportThread]:
        self._require_view(tenant_id, actor, channel)
        applied = filters or InboxFilter()
        return self._tickets.list_threads(
            tenant_id,
            limit=self._thread_page_size(tenant_id),
            channel=channel,
            status=applied.status,
            store_ids=applied.store_ids,
            position_codes=applied.position_codes,
            created_from=applied.created_from,
            created_to=applied.created_to,
            unread_only=applied.unread_only,
            search=applied.search.strip(),
            newest_first=applied.newest_first,
        )

    def status_counts(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        channel: SupportChannel,
        filters: InboxFilter | None = None,
    ) -> dict[SupportTicketStatus, int]:
        """Süzgəc zolağındakı saylar. Səlahiyyət yoxdursa hamısı sıfırdır."""
        empty = dict.fromkeys(SupportTicketStatus, 0)
        if not self.can_view(tenant_id=tenant_id, actor=actor, channel=channel):
            return empty
        applied = filters or InboxFilter()
        raw = self._tickets.status_counts(
            tenant_id,
            channel=channel,
            store_ids=applied.store_ids,
            position_codes=applied.position_codes,
            created_from=applied.created_from,
            created_to=applied.created_to,
            unread_only=applied.unread_only,
            search=applied.search.strip(),
        )
        for key, value in raw.items():
            empty[SupportTicketStatus.parse(key)] = int(value)
        return empty

    def position_options(self, *, tenant_id: TenantId, actor: Employee) -> list[tuple[str, str]]:
        """«Vəzifə üzrə» süzgəcinin siyahısı — səlahiyyətsiz aktorda boş."""
        now = self._clock.now()
        if not any(
            actor.has_permission(channel.viewer_flag, now=now) for channel in SupportChannel
        ):
            return []
        return self._tickets.position_options(tenant_id)

    def thread(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        channel: SupportChannel,
        ticket_id: SupportTicketId,
    ) -> SupportThread:
        self._require_view(tenant_id, actor, channel)
        return self._require_channel_thread(ticket_id, channel)

    def actionable_count(
        self, *, tenant_id: TenantId, actor: Employee, channel: SupportChannel
    ) -> int:
        """Naviqasiyadakı sayğac — YALNIZ `🔴 Açıq` (tg1.md Faza 6).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ OXUNMAMIŞ SAYI DEYİL
        ──────────────────────────────────────────────────────────────────────
        Oxunmamış say «baxmadığım» deməkdir; nişan isə «məndə iş qalıb»
        deməlidir. İkisi ayrılmasaydı, söhbəti AÇIB cavab yazmayan Root üçün
        nişan sıfıra düşərdi — yəni gözdən keçirmək işi bitirmiş kimi
        görünərdi. Ona görə sayğac STATUSA baxır, oxunma vəziyyətinə yox.

        Səlahiyyət yoxdursa sıfırdır (`can_view`) — maddə onsuz da menyuda
        görünmür.
        """
        counts = self.status_counts(tenant_id=tenant_id, actor=actor, channel=channel)
        return sum(value for status, value in counts.items() if status.counts_toward_badge)

    # -------------------------------- yazı ----------------------------------- #

    def reply(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        channel: SupportChannel,
        ticket_id: SupportTicketId,
        body: str,
    ) -> SupportThread:
        """Cavab yazır və (texniki kanalda) Telegram-da da göstərir."""
        self._require_view(tenant_id, actor, channel)
        thread = self._require_channel_thread(ticket_id, channel)
        cleaned = _clean(body, MIN_BODY_LENGTH, MAX_BODY_LENGTH, label="Cavab")

        message_id = new_support_message_id()
        self._tickets.append_message(
            message_id=message_id,
            ticket_id=ticket_id,
            sender_id=actor.id,
            body=cleaned,
            is_from_developer=True,
        )
        self._push_to_telegram(
            tenant_id=tenant_id,
            thread=thread,
            message_id=message_id,
            body=cleaned,
            author_id=thread.opened_by,
            is_reply=True,
        )
        return self._require_thread(ticket_id)

    def set_status(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        channel: SupportChannel,
        ticket_id: SupportTicketId,
        status: SupportTicketStatus,
    ) -> SupportThread:
        """Statusu dəyişir — AUDİT-LƏNİR (bax modul başlığı).

        DÖRD DÜYMƏNİN HAMISI BU METODDAN KEÇİR (`[Gözləmədəyə Keç]`,
        `[Həll Olundu]`, `[Bağla]`, `[Yenidən Aç]`). Hər biri üçün ayrı metod
        yazsaydıq, audit sətri və taymer sütunu dörd yerdə təkrarlanardı və
        biri unudulduqda söhbət avtomatikadan sükutla düşərdi.

        KEÇİD QAYDASI BURADA DEYİL (D-R2-03, dövrə 2): "hansı statusdan
        hansına keçilə bilər" sualının cavabı `SupportTicketStatus.
        assert_transition_allowed`-dədir (CLAUDE.md §6: domen qaydası
        entity-də/dəyər obyektində, use case-də yox) — bu metod YALNIZ
        səlahiyyəti yoxlayır və domen qərarını tətbiq edir.
        """
        self._require_view(tenant_id, actor, channel)
        thread = self._require_channel_thread(ticket_id, channel)
        current = thread.ticket_status
        current.assert_transition_allowed(status)
        if current is status:
            # Düymənin təkrar basılması İSTİFADƏÇİ səhvidir, SİSTEM
            # pozuntusu deyil (bax domen metodunun öz şərhi) — nə DB yazısı,
            # nə audit sətri təkrarlanır, sadəcə cari vəziyyət qaytarılır.
            return thread
        self._tickets.set_status(ticket_id, status=status, at=self._clock.now())
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action=f"SUPPORT_TICKET_{status.name}",
            entity_type="support_ticket",
            entity_id=str(ticket_id),
            after_state={"status": status.value},
            reason=f"Kanal: {channel.section_title_az}",
        )
        return self._require_thread(ticket_id)

    def run_maintenance(
        self, *, tenant_id: TenantId, now: datetime | None = None
    ) -> dict[str, int]:
        """İki avtomatik keçid (tg1.md Faza 6) — PLANLAYICI ÇAĞIRIR, EKRAN YOX.

        ──────────────────────────────────────────────────────────────────────
        AKTOR YOXDUR — SİSTEM ƏMƏLİYYATIDIR
        ──────────────────────────────────────────────────────────────────────
        `actor` tələb etsəydik, keçid Root-un panelə girməsindən asılı olardı:
        tətbiq bağlı qalan həftə sonu heç bir müraciət bağlanmazdı. Audit
        sətrində `actor_id=None` yazılır və bu, sxemdə icazəlidir (sistem
        yazıları üçün).

        MODUL SÖNDÜRÜLƏNDƏ İŞLƏMİR: Feature Toggle-ın retroaktiv-təsirsizlik
        qaydası (CLAUDE.md §5) yeni İNSTANSİYA yaratmağı bloklayır, bu isə
        instansiya yaratmır — lakin söndürülmüş modulda status dəyişdirmək
        istifadəçinin görmədiyi bir yerdə məlumatı dəyişmək olardı.
        """
        moment = now or self._clock.now()
        if not self._module_enabled(tenant_id):
            return {"closed": 0, "reminded": 0}

        closed = self._auto_close(tenant_id=tenant_id, now=moment)
        reminded = self._send_reminders(tenant_id=tenant_id, now=moment)
        return {"closed": closed, "reminded": reminded}

    def _auto_close(self, *, tenant_id: TenantId, now: datetime) -> int:
        """`RESOLVED` → `CLOSED`, Root parametrindəki müddətdən sonra."""
        days = limit_int(self._limits, tenant_id, SystemLimitKey.SUPPORT_AUTO_CLOSE_DAYS)
        cutoff = now - timedelta(days=days)
        closed = 0
        for ticket_id in self._tickets.due_for_auto_close(tenant_id, before=cutoff):
            self._tickets.set_status(ticket_id, status=SupportTicketStatus.CLOSED, at=now)
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="SUPPORT_TICKET_AUTO_CLOSED",
                entity_type="support_ticket",
                entity_id=str(ticket_id),
                after_state={"status": SupportTicketStatus.CLOSED.value, "after_days": days},
                reason="Etiraz pəncərəsi bitdi",
            )
            closed += 1
        return closed

    def _send_reminders(self, *, tenant_id: TenantId, now: datetime) -> int:
        """`WAITING` müraciətdə işçiyə xatırlatma — HƏR MÜRACİƏTƏ BİR DƏFƏ.

        `mark_reminded` YAZILMASA dövrə hər planlayıcı işində eyni bildirişi
        göndərərdi və işçi onu spam kimi qəbul edərdi — nəticədə həqiqi
        xatırlatma da gözdən düşərdi.
        """
        if self._notifier is None:
            return 0
        days = limit_int(self._limits, tenant_id, SystemLimitKey.SUPPORT_WAITING_REMINDER_DAYS)
        cutoff = now - timedelta(days=days)
        sent = 0
        for ticket_id, employee_id, subject in self._tickets.due_for_reminder(
            tenant_id, before=cutoff
        ):
            try:
                self._notifier.notify(
                    tenant_id=tenant_id,
                    recipient_id=employee_id,
                    category=REMINDER_CATEGORY,
                    title_az="Dəstək müraciətiniz cavab gözləyir",
                    body_az=(
                        f"«{subject}» müraciətində sizdən əlavə məlumat gözlənilir. "
                        "Dəstək panelini açıb cavab yazın."
                    ),
                )
            except Exception:
                # Bildiriş uğursuzluğu QALAN müraciətləri dayandırmır: biri
                # üçün e-poçt serveri cavab verməsə, digərləri xatırlatmasız
                # qalardı.
                _error_log.exception("SUPPORT_REMINDER_FAILED", extra={"ticket_id": str(ticket_id)})
                continue
            self._tickets.mark_reminded(ticket_id, at=now)
            sent += 1
        return sent

    def mark_read(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        channel: SupportChannel,
        ticket_id: SupportTicketId,
    ) -> None:
        self._require_view(tenant_id, actor, channel)
        self._tickets.mark_staff_read(ticket_id, up_to=self._clock.now())

    # --------------------------- Telegram → proqram --------------------------- #

    def deliver_telegram_reply(
        self,
        *,
        tenant_id: TenantId,
        body: str,
        reference: str = "",
        telegram_message_id: int | None = None,
    ) -> SupportTicketId | None:
        """Telegram-dan gələn REPLY-ı söhbətə yazır (Faza 5).

        AKTOR YOXDUR — mesaj proqramdan kənardan gəlir və `sender_id` NULL
        qalır (sxemdə bu, «hazırlayıcı tərəf» deməkdir). Səlahiyyət yoxlaması
        burada mənasızdır: Telegram tərəfində qapı BOT TOKEN-in özüdür,
        yəni qrupa çıxışı olan şəxs artıq etibarlıdır.

        Uyğun müraciət tapılmasa `None` qaytarır və HEÇ NƏ yazmır: Faza 5
        «reply olmayan sadə mesajları görməzdən gəl» tələbinin davamıdır —
        naməlum istinadlı cavabı təsadüfi söhbətə yazmaq onu SƏHV işçiyə
        çatdırardı.
        """
        if not self._module_enabled(tenant_id):
            return None
        cleaned = _clean(body, MIN_BODY_LENGTH, MAX_BODY_LENGTH, label="Cavab")
        ticket_id = self._tickets.find_ticket_by_reference(
            reference=reference, telegram_message_id=telegram_message_id
        )
        if ticket_id is None:
            return None
        thread = self._tickets.get_thread(ticket_id)
        if thread is None or not thread.channel.notifies_telegram:
            # Daxili kanalın söhbətinə Telegram-dan cavab yazıla bilməz —
            # o kanal Telegram-a heç vaxt çıxmır, deməli belə bir istinad
            # yalnız səhv/uydurma ola bilər.
            return None
        self._tickets.append_message(
            message_id=new_support_message_id(),
            ticket_id=ticket_id,
            sender_id=None,
            body=cleaned,
            is_from_developer=True,
            from_telegram=True,
        )
        return ticket_id

    # ------------------------------- köməkçi --------------------------------- #

    def _require_channel_thread(
        self, ticket_id: SupportTicketId, channel: SupportChannel
    ) -> SupportThread:
        """Söhbət DOĞRU kanaldadırmı.

        `can_view_internal_requests` olan CEO texniki müraciətin ID-sini əl
        ilə ötürüb onu oxuya bilməməlidir — kanal ayrılığı yalnız siyahı
        sorğusunda tətbiq olunsaydı, tək sətirlik keçid onu yan keçərdi.
        """
        thread = self._require_thread(ticket_id)
        if thread.channel is not channel:
            raise SupportAccessError(
                "Müraciət başqa kanaldadır",
                user_message="Bu müraciət bu bölməyə aid deyil.",
                context={"ticket_id": str(ticket_id), "channel": thread.channel.value},
            )
        return thread

    def _require_view(self, tenant_id: TenantId, actor: Employee, channel: SupportChannel) -> None:
        if not self._module_enabled(tenant_id):
            raise SupportAccessError(
                "SUPPORT_CHAT modulu deaktiv edilib",
                user_message="Dəstək bölməsi hazırda aktiv deyil.",
                context={"module": FeatureModule.SUPPORT_CHAT.value},
            )
        if not actor.has_permission(channel.viewer_flag, now=self._clock.now()):
            _security_log.warning(
                "SUPPORT_INBOX_DENIED",
                extra={"actor_id": str(actor.id), "flag": channel.viewer_flag},
            )
            raise SupportAccessError(
                f"«{channel.viewer_flag}» səlahiyyəti yoxdur",
                user_message=f"«{channel.section_title_az}» bölməsinə çıxışınız yoxdur.",
                context={"actor_id": str(actor.id)},
            )


def _clean(raw: str, minimum: int, maximum: int, *, label: str) -> str:
    cleaned = normalise_decision_text(raw)
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


#: Geriyə uyğunluq: flag adları CHAT-1-də domenə köçdü, lakin bu modul onların
#: tarixi ünvanıdır və `app.py` hələ buradan idxal edir.
__all__ = [
    "CONTACT_SUPPORT_FLAG",
    "DEFAULT_THREAD_PAGE_SIZE",
    "MAX_BODY_LENGTH",
    "MESSAGE_REF_PREFIX",
    "MIN_BODY_LENGTH",
    "REMINDER_CATEGORY",
    "STATUS_CLOSED",
    "STATUS_OPEN",
    "VIEW_INTERNAL_FLAG",
    "VIEW_TECHNICAL_FLAG",
    "InboxFilter",
    "SupportAccessError",
    "SupportChannel",
    "SupportChatUseCase",
    "SupportInboxUseCase",
    "SupportMessage",
    "SupportMessageError",
    "SupportTelegramGateway",
    "SupportThread",
    "SupportTicketRepository",
    "SupportTicketStatus",
    "TelegramDelivery",
    "TelegramOutgoing",
    "TicketNotFoundError",
]
