"""Dəstək kanalları — işçi KİMƏ yazdığını ÖZÜ seçir (CHAT-1, Faza 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ KANAL SEÇİMİ İŞÇİYƏ VERİLİR
──────────────────────────────────────────────────────────────────────────────
Əvvəlki quruluşda dəstək chat-inin BİR ünvanı var idi — hazırlayıcı. Nəticədə
«məzuniyyətim təsdiqlənmir» və «kiosk PC açılmır» eyni qutuya düşürdü:
birincisi şirkətin öz kadr məsələsidir və hazırlayıcının onu OXUMASI belə
lazımsız məlumat çıxışıdır; ikincisi isə CEO-nun həll edə bilmədiyi texniki
nasazlıqdır.

Avtomatik təsnifat (açar sözlərlə «cərimə» → daxili, «xəta» → texniki) rədd
edildi: səhv təsnifat mesajı YANLIŞ auditoriyaya çatdırardı və işçi bunu
görməzdi. İnsan bir kliklə düzgün cavabı verir — maşın təxmini isə sükutla
səhv edir.

──────────────────────────────────────────────────────────────────────────────
KANAL «GÖRÜNÜŞ» DEYİL, MARŞRUTDUR
──────────────────────────────────────────────────────────────────────────────
Kanal həm oxucunu (`viewer_flag`), həm də xarici bildirişi
(`notifies_telegram`) təyin edir. İkisi bir yerdə saxlanılır ki, yeni kanal
əlavə edən adam «bunu Telegram-a göndərməli idikmi?» sualını UNUDA bilməsin —
sual sinifin özündə cavablanır.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

#: Widget-dən mesaj yazmaq — DEFOLT bütün rollarda (Satıcı daxil).
#:
#: Kanal seçimindən ASILI DEYİL: hər iki kanal eyni widget-dən açılır və
#: ayrıca «daxili yazmaq» icazəsi işçini öz kadr sualını verməkdən
#: məhrum edərdi.
CONTACT_SUPPORT_FLAG: Final = "can_contact_support"

#: «Daxili Müraciətlər» bölməsi — defolt CEO, Admin, HR_Admin.
VIEW_INTERNAL_FLAG: Final = "can_view_internal_requests"

#: «Texniki Dəstək» bölməsi — defolt YALNIZ Root (fərdi override mümkündür).
VIEW_TECHNICAL_FLAG: Final = "can_view_technical_support"

#: Telegram ayarları — YALNIZ Root, hardlock (CEO-ya belə verilə bilməz).
MANAGE_TELEGRAM_FLAG: Final = "can_manage_telegram_config"


class SupportChannel(str, Enum):
    """Müraciətin marşrutu.

    `str, Enum` qəsdəndir (`CLAUDE.md` §4): dəyər `support_tickets.channel`
    PostgreSQL enum-una sözbəsöz yazılır və `str(X)` çıxışının dəyişməsi
    audit sətrinin formatını dəyişərdi.
    """

    #: Növbə, cərimə, kadr, məzuniyyət — şirkətin ÖZ CEO/Admin/HR_Admin-inə.
    INTERNAL = "INTERNAL"

    #: Proqram işləmir, xəta, donur — hazırlayıcıya (Root) + Telegram-a.
    TECHNICAL = "TECHNICAL"

    @property
    def label_az(self) -> str:
        """Seçim kartının başlığı (Faza 1: «uzun izahat yox»)."""
        return _LABELS[self]

    @property
    def hint_az(self) -> str:
        """Kartın altındakı bir sətirlik nümunə siyahısı."""
        return _HINTS[self]

    @property
    def viewer_flag(self) -> str:
        """Bu kanalın gələnlər qutusunu AÇAN icazə flag-i."""
        return _VIEWER_FLAGS[self]

    @property
    def section_title_az(self) -> str:
        """Sol naviqasiyadakı bölmə adı."""
        return _SECTION_TITLES[self]

    @property
    def notifies_telegram(self) -> bool:
        """Telegram-a YALNIZ texniki kanal düşür.

        Daxili müraciət hazırlayıcının Telegram-ına düşsəydi, şirkətin kadr
        yazışması kənar şəxsin telefonunda olardı — bu, funksional qüsur
        deyil, MƏLUMAT SIZMASIdır. Ona görə qayda burada, kanalın öz
        tərifindədir, çağırış yerlərində deyil.
        """
        return self is SupportChannel.TECHNICAL

    @classmethod
    def parse(cls, raw: str | SupportChannel) -> SupportChannel:
        """Bazadan/ekrandan gələn sətri kanal-a çevirir.

        Naməlum dəyər `TECHNICAL`-a DÜŞMÜR — istisna atır. Səbəb: sükutla
        texnikiyə düşən daxili müraciət məhz yuxarıdakı sızmadır, yəni
        «təhlükəsiz defolt» burada ən təhlükəli seçimdir.
        """
        if isinstance(raw, cls):
            return raw
        try:
            return cls(str(raw).strip().upper())
        except ValueError as error:
            raise ValueError(f"naməlum dəstək kanalı: {raw!r}") from error


class SupportTicketStatus(str, Enum):
    """Müraciətin vəziyyəti — «KİM hərəkət etməlidir?» sualının cavabı.

    ──────────────────────────────────────────────────────────────────────────
    STATUS OXUNMA VƏZİYYƏTİ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Söhbəti AÇMAQ statusu dəyişmir — yalnız «oxundu» nişanını silir. İkisini
    birləşdirmək cazibədar görünürdü («açdım, deməli işləyirəm»), lakin
    nəticəsi belə olardı: siyahını gözdən keçirən Root bütün müraciətləri
    sükutla öz üzərinə götürərdi və «məndə nə qalıb?» sualının cavabı
    itərdi. Ona görə status YALNIZ AÇIQ əməliyyatla dəyişir.

    ──────────────────────────────────────────────────────────────────────────
    `WAITING` = MƏN GÖZLƏYİRƏM, «CAVAB YAZMAMIŞAM» DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Ən çox qarışdırılan bənd (tg1.md xəbərdarlığı). Cavab yazılmamış müraciət
    `OPEN` qalır; `WAITING` isə cavab YAZILDIQDAN sonra işçidən əlavə
    məlumat gözlənildiyini bildirir. Fərq praktikdir: nişan yalnız `OPEN`
    sayır, yəni səhv işarələnmiş `WAITING` müraciəti gözdən İTİRƏRDİ.

    ──────────────────────────────────────────────────────────────────────────
    DƏYƏRLƏR SXEMDƏN GƏLİR
    ──────────────────────────────────────────────────────────────────────────
    `WAITING` üzvünün dəyəri `WAITING_CUSTOMER`-dir, çünki `ticket_status`
    enum-u `schema.sql`-də məhz belə adlandırılıb və mövcud sətirlər həmin
    dəyəri daşıyır. Adı Python tərəfdə qısaltmaq oxunaqlıdır; DB dəyərini
    dəyişmək isə miqrasiya tələb edərdi və heç bir fayda verməzdi.
    """

    #: Yeni mesaj VƏ YA işçi cavab yazıb — TOP MƏNDƏDİR.
    OPEN = "OPEN"
    #: Cavab yazıldı, işçidən əlavə məlumat/təsdiq gözlənilir — TOP İŞÇİDƏDİR.
    WAITING = "WAITING_CUSTOMER"
    #: Problem həll edildi, təsdiq gözlənilir (avtomatik bağlanma taymeri işləyir).
    RESOLVED = "RESOLVED"
    #: Arxiv.
    CLOSED = "CLOSED"

    @property
    def label_az(self) -> str:
        return _STATUS_LABELS[self]

    @property
    def dot(self) -> str:
        """Rəngli nöqtə — FORMA + RƏNG birlikdə.

        Yalnız rəng kifayət etmirdi: `Chip` sinfinin başlığında yazıldığı
        kimi rəng korluğunda iki status eyni görünür və ağ-qara çapda fərq
        tamamilə itir. Emoji həm rəng, həm də ayırd edilə bilən forma daşıyır.
        """
        return _STATUS_DOTS[self]

    @property
    def sort_rank(self) -> int:
        """Siyahıdakı qrup sırası: Açıq → Gözləmədə → Həll olundu → Bağlandı.

        Sıra «mənim işim əvvəl» prinsipindədir — vaxt sırası İKİNCİ açardır.
        Yalnız vaxta görə sıralasaydıq, bir həftə əvvəl bağlanmış söhbət
        bugünkü yeni müraciətin üstündə görünə bilərdi.
        """
        return _STATUS_RANK[self]

    @property
    def counts_toward_badge(self) -> bool:
        """Naviqasiya sayğacına YALNIZ `OPEN` düşür (tg1.md Faza 6).

        Sayğac «mənim işim» deməkdir. `WAITING` topu işçidədir, `RESOLVED`
        taymer gözləyir, `CLOSED` bitib — üçünü də saysaydıq, rəqəm heç vaxt
        sıfıra düşməz və nişan mənasını itirərdi.
        """
        return self is SupportTicketStatus.OPEN

    @property
    def is_open(self) -> bool:
        """«Söhbət hələ canlıdırmı» — cavab yazıla bilərmi.

        `RESOLVED` də canlıdır: işçi etiraz edə bilər və o, söhbəti yenidən
        `OPEN`-a qaytarır (avtomatik keçid 1).
        """
        return self is not SupportTicketStatus.CLOSED

    @classmethod
    def parse(cls, raw: str | SupportTicketStatus) -> SupportTicketStatus:
        """Bazadan gələn sətri statusa çevirir.

        NAMƏLUM DƏYƏR → `OPEN`: `ticket_status` enum-unda bu axının
        işlətmədiyi `IN_PROGRESS` də var (sxem onu başqa məqsədlə saxlayır).
        Belə sətri gizlətmək müraciəti gözdən itirərdi — `OPEN`-a düşməsi isə
        ən pis halda artıq bir sətir göstərir.
        """
        if isinstance(raw, cls):
            return raw
        try:
            return cls(str(raw).strip().upper())
        except ValueError:
            return cls.OPEN


_STATUS_LABELS: Final[dict[SupportTicketStatus, str]] = {
    SupportTicketStatus.OPEN: "Açıq",
    SupportTicketStatus.WAITING: "Gözləmədə",
    SupportTicketStatus.RESOLVED: "Həll olundu",
    SupportTicketStatus.CLOSED: "Bağlandı",
}

_STATUS_DOTS: Final[dict[SupportTicketStatus, str]] = {
    SupportTicketStatus.OPEN: "🔴",
    SupportTicketStatus.WAITING: "🟡",
    SupportTicketStatus.RESOLVED: "🟢",
    SupportTicketStatus.CLOSED: "⚫",
}

_STATUS_RANK: Final[dict[SupportTicketStatus, int]] = {
    SupportTicketStatus.OPEN: 0,
    SupportTicketStatus.WAITING: 1,
    SupportTicketStatus.RESOLVED: 2,
    SupportTicketStatus.CLOSED: 3,
}


_LABELS: Final[dict[SupportChannel, str]] = {
    SupportChannel.INTERNAL: "Daxili Müraciət",
    SupportChannel.TECHNICAL: "Texniki Dəstək",
}

_HINTS: Final[dict[SupportChannel, str]] = {
    SupportChannel.INTERNAL: "Növbə, cərimə, kadr, məzuniyyət",
    SupportChannel.TECHNICAL: "Proqram işləmir, xəta, donur",
}

_VIEWER_FLAGS: Final[dict[SupportChannel, str]] = {
    SupportChannel.INTERNAL: VIEW_INTERNAL_FLAG,
    SupportChannel.TECHNICAL: VIEW_TECHNICAL_FLAG,
}

_SECTION_TITLES: Final[dict[SupportChannel, str]] = {
    SupportChannel.INTERNAL: "Daxili Müraciətlər",
    SupportChannel.TECHNICAL: "Texniki Dəstək",
}


__all__ = [
    "CONTACT_SUPPORT_FLAG",
    "MANAGE_TELEGRAM_FLAG",
    "VIEW_INTERNAL_FLAG",
    "VIEW_TECHNICAL_FLAG",
    "SupportChannel",
    "SupportTicketStatus",
]
