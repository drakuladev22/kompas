"""Telegram Bot API şlüzü — texniki dəstəyin XARİCİ ucu (CHAT-1 Faza 4-5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ WEBHOOK DEYİL, POLLING
──────────────────────────────────────────────────────────────────────────────
Webhook Telegram-ın BİZƏ zəng edə biləcəyi ictimai HTTPS ünvanı tələb edir.
Bu tətbiq isə mağaza şəbəkəsindəki Windows PC-də işləyir: sabit IP yoxdur,
NAT arxasındadır, sertifikat idarəçiliyi yoxdur. Webhook üçün ayrıca bulud
xidməti qurmaq CHAT-1-in «proqramdan kənarda heç nə» prinsipini pozardı.

`getUpdates` isə ÇIXAN bağlantıdır — eyni istiqamətdə işləyən Supabase və
Drive çağırışları ilə eyni şəbəkə tələbləri.

──────────────────────────────────────────────────────────────────────────────
POLLING YALNIZ BİR YERDƏ İŞLƏMƏLİDİR
──────────────────────────────────────────────────────────────────────────────
`getUpdates` bir yeniliyi YALNIZ BİR dəfə verir: onu oxuyan ikinci nüsxə
həmin cavabı görməyəcək. Ona görə sorğu `TelegramReplyPoller`-dədir və o,
YALNIZ «Texniki Dəstək» bölməsi açıq olan sessiyada işə düşür — həmin
bölmə isə `can_view_technical_support` ilə qorunur və praktikada tək
Root maşınındadır (`presentation/controllers/support_inbox.py`).

Bu, texniki məhdudiyyət deyil, QƏSDLİ yerləşdirmədir: sorğunu hər kassa
PC-sindən aparsaydıq, cavab hansı maşının növbəsinə düşdüsə orada
görünərdi və digərləri onu HEÇ VAXT almazdı.

──────────────────────────────────────────────────────────────────────────────
İSTİNAD MƏTNDƏDİR, ÇÜNKİ TELEGRAM-DA THREAD YOXDUR
──────────────────────────────────────────────────────────────────────────────
Qrup söhbətində mesajlar düz siyahıdır. Cavabın hansı müraciətə aid olduğunu
YALNIZ `reply_to_message` göstərir; onun içindən isə `#msg_XXXX` istinadı
oxunur. İstinad Telegram-ın öz `message_id`-si ilə TAMAMLANIR (ikisi də
saxlanılır) — birincisi insan üçün, ikincisi maşın üçün.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import httpx

from src.application.use_cases.support_chat import (
    MESSAGE_REF_PREFIX,
    TelegramDelivery,
    TelegramOutgoing,
)
from src.domain.policies import SystemLimitKey
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.application.use_cases.telegram_config import TelegramSettings
    from src.infrastructure.config.limits import InfrastructureLimits

_log = get_logger(__name__, channel=LogChannel.APP)

API_ROOT: Final = "https://api.telegram.org"

#: Telegram bir mesajda 4096 simvol qəbul edir. Bizim öz hədimiz 4000-dir
#: (`support_chat.MAX_BODY_LENGTH`), başlıq isə ~120 simvol tutur — ona görə
#: gövdə kəsilə bilər. Kəsmə SÜKUTLA olmur: sonuna işarə qoyulur, çünki
#: yarımçıq mesaj oxuyan adam nəyisə qaçırdığını BİLMƏLİDİR.
MAX_TELEGRAM_TEXT = 4000
TRUNCATION_SUFFIX = " […kəsildi — tam mətn proqramdadır]"

#: İki sətir arası — istinad blokdan AYRILIR (Telegram mətni birləşdirir).
_BLANK_LINE = "\n\n"

#: Telegram `caption` həddi — mətn həddindən (4096) qat-qat azdır.
MAX_TELEGRAM_CAPTION = 1024

#: `#msg_1234` — yalnız rəqəm, çünki nömrə DB ardıcıllığındandır.
_REFERENCE_PATTERN: Final = re.compile(rf"{re.escape(MESSAGE_REF_PREFIX)}(\d+)")


class TelegramApiError(RuntimeError):
    """Telegram cavabı uğursuzdur.

    `KompasOSError` DEYİL: bu istisna istifadəçiyə heç vaxt göstərilmir —
    şlüzün bütün çağırış yerləri onu tutur və `None` ilə davam edir
    (bax `SupportChatUseCase._push_to_telegram` başlığı).
    """


@dataclass(frozen=True)
class TelegramReply:
    """Telegram-dan gələn, MÜRACİƏTƏ BAĞLANA BİLƏN cavab."""

    body: str
    reference: str
    reply_to_message_id: int | None
    update_id: int


def format_support_message(payload: TelegramOutgoing) -> str:
    """Faza 4 formatı.

    Emoji-lər dekorasiya DEYİL: Telegram mobil ekranında sətir başlıqları
    yalnız onlarla bir baxışda seçilir — «Filial:» / «İşçi:» kimi mətn
    etiketləri eyni yeri tutur, amma göz onları sıralamır.

    Boş sahə (silinmiş mağaza/işçi) SƏTRİ TAM ÇIXARIR: «🏪 —» sətri
    məlumat vermir, yalnız yer tutur.
    """
    lines: list[str] = []
    if payload.is_urgent:
        lines.append("🔴 TƏCİLİ")
    if payload.is_reply:
        # Cavab öz Telegram-ımıza geri düşür (Faza 5: «bir tarixçə»).
        # İşarə olmasaydı, hazırlayıcı öz cavabını yeni müraciət sanardı.
        lines.append("↩️ Proqramdan cavab")
    if payload.store_name:
        lines.append(f"🏪 {payload.store_name}")
    if payload.sender_name:
        who = payload.sender_name
        if payload.sender_position:
            who = f"{who} — {payload.sender_position}"
        lines.append(f"👤 {who}")
    lines.append(f"🕐 {payload.sent_at.strftime('%H:%M')}")
    lines.append("")
    lines.append(payload.body)
    lines.append("")
    lines.append(payload.reference)
    return _truncate("\n".join(lines))


def extract_reference(text: str) -> str:
    """Mesaj mətnindən `#msg_XXXX` istinadını çıxarır.

    SONUNCU uyğunluq götürülür: istifadəçi köhnə mesajı sitat gətirib öz
    istinadını sona yazdıqda niyyəti sonuncudur.
    """
    matches = _REFERENCE_PATTERN.findall(text or "")
    return f"{MESSAGE_REF_PREFIX}{matches[-1]}" if matches else ""


def _truncate(text: str) -> str:
    if len(text) <= MAX_TELEGRAM_TEXT:
        return text
    keep = MAX_TELEGRAM_TEXT - len(TRUNCATION_SUFFIX)
    return text[:keep] + TRUNCATION_SUFFIX


def _caption(text: str) -> str:
    """Şəkil altyazısı — İSTİNAD SONDA saxlanılır.

    Adi kəsmə sonu atardı, halbuki `#msg_XXXX` məhz orada durur və onsuz
    cavab yönləndirməsi işləməz. Ona görə uzun mətn ORTADAN kəsilir.
    """
    if len(text) <= MAX_TELEGRAM_CAPTION:
        return text
    reference = extract_reference(text)
    tail = _BLANK_LINE + reference if reference else ""
    keep = MAX_TELEGRAM_CAPTION - len(TRUNCATION_SUFFIX) - len(tail)
    return text[:keep] + TRUNCATION_SUFFIX + tail


class TelegramApiClient:
    """Bot API-nin lazım olan ÜÇ metodu — artığı yazılmır.

    Tam SDK əlavə etmək (python-telegram-bot) rədd edildi: paket asılılığı
    `.exe` ölçüsünü və PyInstaller gizli-idxal siyahısını böyüdərdi, halbuki
    istifadə etdiyimiz səth üç HTTP çağırışıdır.
    """

    def __init__(
        self,
        *,
        limits: InfrastructureLimits | None = None,
        client: httpx.Client | None = None,
        api_root: str = API_ROOT,
    ) -> None:
        # Taymaut ÇAĞIRIŞ ANINDA oxunur (`catalog.py` ilə eyni qərar): Root
        # dəyəri dəyişəndə tətbiqin yenidən başladılması tələb olunmamalıdır.
        self._limits = limits
        self._client = client
        self._api_root = api_root.rstrip("/")

    def _timeout(self) -> float:
        if self._limits is None:
            return 15.0
        return self._limits.float_of(SystemLimitKey.TELEGRAM_REQUEST_TIMEOUT_SECONDS)

    def _call(self, token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._api_root}/bot{token}/{method}"
        client = self._client or httpx.Client(timeout=self._timeout())
        try:
            response = client.post(url, json=payload)
        except httpx.HTTPError as error:
            raise TelegramApiError(f"Telegram sorğusu alınmadı: {error}") from error
        finally:
            if self._client is None:
                client.close()
        # TOKEN HEÇ BİR XƏTA MƏTNİNDƏ GÖRÜNMÜR: `url` dəyişəni jurnala
        # yazılmır, yalnız metod adı yazılır — Telegram URL-i token-i
        # YOLUNDA daşıyır və adi bir `exception` sətri onu jurnala tökərdi.
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise TelegramApiError(f"{method}: HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict) or not body.get("ok"):
            description = ""
            if isinstance(body, dict):
                description = str(body.get("description", ""))
            raise TelegramApiError(f"{method}: {description or 'naməlum xəta'}")
        result = body.get("result")
        if isinstance(result, dict):
            return result
        return {"result": result}

    def send_message(self, token: str, *, chat_id: str, text: str) -> int | None:
        """Mesaj göndərir və Telegram-ın mesaj nömrəsini qaytarır."""
        result = self._call(token, "sendMessage", {"chat_id": chat_id, "text": text})
        raw = result.get("message_id")
        return int(raw) if isinstance(raw, int) else None

    def send_photo(
        self, token: str, *, chat_id: str, caption: str, content: bytes, filename: str
    ) -> int | None:
        """Şəkli MƏTNLƏ BİRLİKDƏ göndərir (Faza 4: «şəkil əlavəsi varsa»).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRI MESAJ DEYİL, `caption`
        ──────────────────────────────────────────────────────────────────────
        Şəkli ayrıca göndərsəydik, qrupda iki mesaj yaranardı və `#msg_XXXX`
        istinadı yalnız birində olardı — cavab verən adam şəklə reply etsə,
        bot istinadı tapa bilməzdi. `caption` ikisini BİR mesajda saxlayır.

        TELEGRAM `caption` HƏDDİ 1024 SİMVOLDUR (mətn həddindən qat-qat az):
        uzun mesaj kəsilir və işarələnir — tam mətn onsuz da proqramdadır.
        """
        url = f"{self._api_root}/bot{token}/sendPhoto"
        client = self._client or httpx.Client(timeout=self._timeout())
        try:
            response = client.post(
                url,
                data={"chat_id": chat_id, "caption": _caption(caption)},
                files={"photo": (filename or "attachment.jpg", content)},
            )
        except httpx.HTTPError as error:
            raise TelegramApiError(f"sendPhoto alınmadı: {error}") from error
        finally:
            if self._client is None:
                client.close()
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise TelegramApiError(f"sendPhoto: HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramApiError("sendPhoto: naməlum xəta")
        result = body.get("result")
        raw = result.get("message_id") if isinstance(result, dict) else None
        return int(raw) if isinstance(raw, int) else None

    def get_updates(self, token: str, *, offset: int) -> list[dict[str, Any]]:
        """Yeni yenilikləri gətirir.

        `timeout=0` (qısa sorğu) QƏSDƏNdir: uzun sorğu (long polling) fon
        sapını 30 saniyəyə qədər saxlayardı və tətbiq bağlananda həmin sap
        gözləməkdə qalardı. Qısa sorğu + `TELEGRAM_POLL_INTERVAL_SECONDS`
        eyni gecikməni verir, lakin hər dövr sərbəst bitir.

        `allowed_updates` yalnız `message`: bot qrupa əlavə olunanda gələn
        onlarla xidmət yeniliyi (`my_chat_member` və s.) növbəni doldurar və
        cavabları gec göstərərdi.
        """
        payload: dict[str, Any] = {
            "offset": offset,
            "timeout": 0,
            "allowed_updates": ["message"],
        }
        result = self._call(token, "getUpdates", payload)
        updates = result.get("result", [])
        return [item for item in updates if isinstance(item, dict)]


class TelegramSupportGateway:
    """`SupportTelegramGateway` + `TelegramProbe` implementasiyası.

    Ayarları HƏR ÇAĞIRIŞDA yenidən oxuyur (`settings_provider`): Root botu
    dəyişdikdən sonra növbəti mesaj YENİ bota getməlidir. Keşləsəydik,
    dəyişiklik yalnız tətbiqin yenidən başladılmasından sonra qüvvəyə minər
    və «dəyişdirdim, işləmir» şikayəti yaranardı.
    """

    def __init__(
        self,
        *,
        settings_provider: Callable[[], TelegramSettings | None],
        client: TelegramApiClient | None = None,
        limits: InfrastructureLimits | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._client = client or TelegramApiClient(limits=limits)
        # `now` TEST ÜÇÜN DEYİL, DOĞRULUQ ÜÇÜNDÜR: göndərilmə anı
        # `support_messages.telegram_sent_at`-a yazılır və server-lövbərli
        # vaxtdan gəlməlidir (TIME-1) — Windows saatı sürüşsə də sıra pozulmur.
        self._now = now or (lambda: datetime.now(UTC))

    def send_support_message(self, payload: TelegramOutgoing) -> TelegramDelivery | None:
        settings = self._settings_provider()
        if settings is None or not settings.is_usable:
            return None
        text = format_support_message(payload)
        try:
            if payload.attachment:
                message_id = self._client.send_photo(
                    settings.bot_token,
                    chat_id=settings.chat_id,
                    caption=text,
                    content=payload.attachment,
                    filename=payload.attachment_name,
                )
            else:
                message_id = self._client.send_message(
                    settings.bot_token, chat_id=settings.chat_id, text=text
                )
        except TelegramApiError as error:
            # Səbəb JURNALA yazılır, istifadəçiyə ÇIXMIR: mesaj onsuz da
            # bazaya düşüb və işçi üçün heç nə dəyişmir.
            _log.warning("TELEGRAM_SEND_FAILED", extra={"reason": str(error)})
            return None
        return TelegramDelivery(telegram_message_id=message_id, sent_at=self._now())

    def send_test_message(self, settings: TelegramSettings, text: str) -> bool:
        """`[Test Mesajı Göndər]` — `is_active` YOXLANMIR (bax use case).

        İstisna UDULMUR-ammA yuxarı da ötürülmür: Root düyməni basıb və
        «getdi/getmədi» cavabını gözləyir; səbəb jurnaldadır.
        """
        try:
            self._client.send_message(settings.bot_token, chat_id=settings.chat_id, text=text)
        except TelegramApiError as error:
            _log.warning("TELEGRAM_TEST_FAILED", extra={"reason": str(error)})
            return False
        return True


class TelegramReplyPoller:
    """Telegram-dan gələn REPLY-ları oxuyur (Faza 5).

    ──────────────────────────────────────────────────────────────────────────
    REPLY OLMAYAN MESAJ GÖRMƏZDƏN GƏLİNİR
    ──────────────────────────────────────────────────────────────────────────
    Faza 5-in açıq tələbi. Səbəb: qrupda adi söhbət də gedir («sabah
    gəlirəm», «oldu»). Onları müraciətə yazsaydıq, işçi öz söhbətində
    tamamilə yad mətnlər görərdi. Daha pisi — hansı müraciətə yazılacağını
    təxmin etmək məlumatı SƏHV işçiyə çatdırardı.

    ──────────────────────────────────────────────────────────────────────────
    OFFSET YERLİ DEYİL, SERVER TƏRƏFİNDƏDİR
    ──────────────────────────────────────────────────────────────────────────
    Hər sorğu əvvəlki paketi TƏSDİQLƏYİR (`offset = son + 1`) və Telegram
    onları bir daha vermir. Ona görə fayl/DB-də offset saxlanmır: yenidən
    başladılan tətbiq təkrar cavab almır. Yaddaşdakı `_offset` yalnız cari
    sessiyanın davamıdır.
    """

    def __init__(
        self,
        *,
        settings_provider: Callable[[], TelegramSettings | None],
        client: TelegramApiClient | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._client = client or TelegramApiClient(limits=limits)
        self._offset = 0

    @property
    def offset(self) -> int:
        return self._offset

    def poll(self) -> list[TelegramReply]:
        """Növbəti cavab paketi. Şəbəkə xətası halında BOŞ siyahı."""
        settings = self._settings_provider()
        if settings is None or not settings.is_usable:
            return []
        try:
            updates = self._client.get_updates(settings.bot_token, offset=self._offset)
        except TelegramApiError as error:
            _log.warning("TELEGRAM_POLL_FAILED", extra={"reason": str(error)})
            return []

        replies: list[TelegramReply] = []
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                # Offset UYĞUNSUZ yenilikdən sonra da irəliləyir: əks halda
                # qrupdakı adi bir mesaj növbəni əbədi bloklayardı.
                self._offset = max(self._offset, update_id + 1)
            reply = _as_reply(update)
            if reply is not None:
                replies.append(reply)
        return replies


def _as_reply(update: dict[str, Any]) -> TelegramReply | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    original = message.get("reply_to_message")
    if not isinstance(original, dict):
        return None
    body = str(message.get("text") or "").strip()
    if not body:
        # Yalnız şəkil/stiker olan reply — mətnsiz cavabı söhbətə yazmaq
        # işçiyə boş balon göstərərdi.
        return None
    reference = extract_reference(str(original.get("text") or ""))
    raw_id = original.get("message_id")
    original_id = raw_id if isinstance(raw_id, int) else None
    if not reference and original_id is None:
        return None
    update_id = update.get("update_id")
    return TelegramReply(
        body=body,
        reference=reference,
        reply_to_message_id=original_id,
        update_id=update_id if isinstance(update_id, int) else 0,
    )


__all__ = [
    "API_ROOT",
    "MAX_TELEGRAM_CAPTION",
    "MAX_TELEGRAM_TEXT",
    "TelegramApiClient",
    "TelegramApiError",
    "TelegramReply",
    "TelegramReplyPoller",
    "TelegramSupportGateway",
    "extract_reference",
    "format_support_message",
]
