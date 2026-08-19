"""Telegram bot konfiqurasiyası — YALNIZ Root (CHAT-1 Faza 3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `.env` DEYİL, BAZA
──────────────────────────────────────────────────────────────────────────────
CHAT-1 bunu açıq qadağan edir: «HEÇ BİR `.env` / xarici config faylı İSTİFADƏ
ETMƏ». Səbəb texniki deyil, ƏMƏLİYYATdır — token-i dəyişmək müştəri
ofisindəki bir istifadəçinin işidir, o isə `Program Files` altındakı mətn
faylını redaktə edə bilmir (SETUP-1: qovluq yazıla bilmir) və etməli də
deyil. Bazada saxlanan dəyər üstəlik AUDİT-lənə bilir; fayl isə iz qoymur.

──────────────────────────────────────────────────────────────────────────────
TOKEN GERİ QAYTARILMIR
──────────────────────────────────────────────────────────────────────────────
`current()` token-in YALNIZ maskalanmış formasını verir. Root paneli demo,
ekran-paylaşımı və uzaqdan dəstək zamanı açıq olur; tam token-i ekrana
qaytarmaq onu həmin anların hamısında ifşa edərdi. Token yalnız YAZILIR
(«Botu Dəyiş») və yalnız şlüzün özü tərəfindən OXUNUR.

──────────────────────────────────────────────────────────────────────────────
KÖHNƏ BOT SİLİNMİR, ARXİVLƏNİR
──────────────────────────────────────────────────────────────────────────────
«Botu Dəyiş» köhnə sətri `telegram_config_history`-ə köçürür. Səbəb: bot
dəyişəndən sonra köhnə qrupda qalan yazışmanın hansı dövrə aid olduğu sual
oluna bilər, və «kim, nə vaxt dəyişdi» sualının cavabı audit sətrindən
başqa yerdə də qalmalıdır — audit mətndir, bu isə strukturdur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.domain.value_objects.authorization import SystemRole
from src.domain.value_objects.support import MANAGE_TELEGRAM_FLAG
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Telegram bot token-inin minimal uzunluğu.
#:
#: FORMAT YOXLAMASI DEYİL, SƏHV-YAPIŞDIRMA QAPISI: token `123456:ABC-DEF...`
#: şəklindədir və 40 simvoldan qısası heç vaxt keçərli olmur. Tam requlyar
#: ifadə yazmaqdan imtina edildi — Telegram formatı dəyişsə, qapı düzgün
#: token-i rədd edərdi və səbəbi tapmaq çətin olardı.
MIN_TOKEN_LENGTH = 40

#: Maskada göstərilən son simvol sayı — Root token-i TANIYA bilməlidir
#: («hansı botdur?»), amma onu OXUYA bilməməlidir.
TOKEN_VISIBLE_SUFFIX = 4


class TelegramConfigError(KompasOSError):
    """Konfiqurasiya yazıla bilmədi."""

    user_message = "Telegram ayarları saxlanmadı."


class TelegramAccessError(KompasOSError):
    """Telegram ayarlarına çıxış YALNIZ Root-dadır."""

    user_message = "Telegram ayarlarını yalnız Root idarə edə bilər."


@dataclass(frozen=True)
class TelegramSettings:
    """Şlüzün işləməsi üçün lazım olan HƏR ŞEY — token AÇIQ mətndə.

    Bu struktur EKRANA ÇIXMIR (bax `TelegramConfigView`); yalnız
    infrastruktur şlüzü onu alır.
    """

    bot_token: str
    chat_id: str
    is_active: bool

    @property
    def is_usable(self) -> bool:
        return bool(self.bot_token and self.chat_id and self.is_active)


@dataclass(frozen=True)
class TelegramConfigView:
    """Root ekranının gördüyü — token MASKALANMIŞ."""

    masked_token: str
    chat_id: str
    is_active: bool
    updated_at: datetime | None = None
    updated_by_name: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.masked_token and self.chat_id)


@runtime_checkable
class TelegramConfigRepository(Protocol):
    """`telegram_config` + `telegram_config_history` (migrations/068).

    ŞİFRƏLƏMƏ BU PORTUN ARXASINDADIR — implementasiya `EncryptionService`
    işlədir, use case isə açıq mətnlə işləyir (eyni naxış:
    `FaceEmbeddingRepository` başlığı).
    """

    def load(self, tenant_id: TenantId) -> TelegramSettings | None: ...

    def describe(self, tenant_id: TenantId) -> TelegramConfigView | None: ...

    def save(
        self,
        tenant_id: TenantId,
        *,
        bot_token: str,
        chat_id: str,
        is_active: bool,
        updated_by: EmployeeId,
        at: datetime,
    ) -> None: ...

    def set_active(
        self, tenant_id: TenantId, *, is_active: bool, updated_by: EmployeeId, at: datetime
    ) -> None: ...

    def archive(self, tenant_id: TenantId, *, replaced_by: EmployeeId, at: datetime) -> bool:
        """Cari sətri tarixçəyə köçürür. Sətir yoxdursa `False`."""
        ...


@runtime_checkable
class TelegramProbe(Protocol):
    """Test mesajı göndərən şlüz — `infrastructure/notifications/telegram.py`."""

    def send_test_message(self, settings: TelegramSettings, text: str) -> bool: ...


class TelegramConfigUseCase:
    """«Telegram Bildirişləri» bölməsinin arxa tərəfi."""

    def __init__(
        self,
        *,
        repository: TelegramConfigRepository,
        audit: AuditTrail,
        clock: Clock,
        probe: TelegramProbe | None = None,
    ) -> None:
        # `probe` İSTƏYƏ BAĞLIDIR: test mesajı ŞƏBƏKƏ tələb edir və
        # konfiqurasiyanı OXUMAQ ondan asılı olmamalıdır. Şlüz qurulmayıbsa
        # düymə səbəbi ilə birlikdə rədd cavabı verir, ekran isə açılır.
        self._repository = repository
        self._audit = audit
        self._clock = clock
        self._probe = probe

    # ------------------------------ görünürlük ------------------------------- #

    def may_manage(self, actor: Employee) -> bool:
        """Bölmə naviqasiyada görünsünmü.

        İKİ ŞƏRT: flag VƏ sistem rolu. Flag `hardlock_level = 1` ilə
        qorunur (migrations/068), yəni DB səviyyəsində Root-dan başqasına
        verilə bilmir — buradakı rol yoxlaması həmin qapının İKİNCİ nüsxəsidir
        (CLAUDE.md §5: hər qayda iki yerdə). Biri olmadan digəri kifayət
        etmirdi: hardlock DB-dədir və `schema.sql` ilə təmiz quraşdırmada
        miqrasiya zənciri fərqli ola bilər.
        """
        if actor.position.effective_system_role is not SystemRole.ROOT:
            return False
        return actor.has_permission(MANAGE_TELEGRAM_FLAG, now=self._clock.now())

    # ------------------------------- oxuma ----------------------------------- #

    def current(self, *, tenant_id: TenantId, actor: Employee) -> TelegramConfigView:
        """Cari ayarlar — token maskalanmış.

        Sətir yoxdursa BOŞ görünüş qaytarılır, istisna YOX: «hələ qurulmayıb»
        xəta deyil, ilk vəziyyətdir və ekran onu forma kimi göstərməlidir.
        """
        self._require(actor)
        return self._repository.describe(tenant_id) or TelegramConfigView(
            masked_token="", chat_id="", is_active=False
        )

    def settings_for_gateway(self, tenant_id: TenantId) -> TelegramSettings | None:
        """Şlüzün oxuduğu AÇIQ ayarlar — AKTOR YOXDUR.

        Səlahiyyət yoxlaması QƏSDƏN yoxdur: bu metodu istifadəçi çağırmır,
        onu bildiriş göndərən kod yolu çağırır və orada «aktor» anlayışı
        mövcud deyil (mesajı Telegram-a itələyən Root deyil, satıcıdır).
        Metod ekrana heç vaxt bağlanmır və nəticəsi göstərilmir.
        """
        settings = self._repository.load(tenant_id)
        if settings is None or not settings.is_usable:
            return None
        return settings

    # -------------------------------- yazı ----------------------------------- #

    def save(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        bot_token: str,
        chat_id: str,
        is_active: bool | None = None,
    ) -> TelegramConfigView:
        """Yeni token/chat ID yazır. Mövcud sətir varsa ƏVVƏLCƏ arxivlənir.

        ──────────────────────────────────────────────────────────────────────
        `is_active` DEFOLTU `True` DEYİL — MÖVCUD VƏZİYYƏTDİR
        ──────────────────────────────────────────────────────────────────────
        Əvvəl defolt `True` idi və nəticə sükutlu idi: Root inteqrasiyanı
        QƏSDƏN söndürüb (`set_active(False)`), sonra botu dəyişəndə
        («Botu Dəyiş» yalnız token/chat ID göndərir) inteqrasiya ÖZÜ-ÖZÜNƏ
        yenidən aktivləşirdi. Yəni bir ayarın dəyişməsi BAŞQA ayarı geri
        qaytarırdı və istifadəçi bunu yalnız Telegram-a mesaj düşəndə görərdi.

        `None` = «vəziyyətə toxunma». İLK konfiqurasiyada saxlanmış sətir
        yoxdur, ona görə `True` seçilir: bot qurmaq onu işlətmək niyyətidir.
        Açıq `True`/`False` ötürülərsə hörmət edilir — `set_active()` yolu
        dəyişmir.
        """
        self._require(actor)
        token = bot_token.strip()
        chat = chat_id.strip()
        if len(token) < MIN_TOKEN_LENGTH:
            raise TelegramConfigError(
                f"Bot token minimum {MIN_TOKEN_LENGTH} simvol olmalıdır",
                user_message="Bot token düzgün görünmür — tam kopyalandığını yoxlayın.",
                context={"length": len(token)},
            )
        if not chat:
            raise TelegramConfigError(
                "Chat ID boşdur",
                user_message="Chat ID boş ola bilməz.",
            )

        if is_active is None:
            existing = self._repository.load(tenant_id)
            is_active = existing.is_active if existing is not None else True

        now = self._clock.now()
        archived = self._repository.archive(tenant_id, replaced_by=actor.id, at=now)
        self._repository.save(
            tenant_id,
            bot_token=token,
            chat_id=chat,
            is_active=is_active,
            updated_by=actor.id,
            at=now,
        )
        # AUDİT SƏTRİNDƏ TOKEN YOXDUR — audit jurnalı ixrac edilə bilir və
        # sirri ora yazmaq onu şifrəli sütundan çıxarıb açıq mətnə köçürərdi.
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TELEGRAM_CONFIG_REPLACED" if archived else "TELEGRAM_CONFIG_CREATED",
            entity_type="telegram_config",
            entity_id=str(tenant_id),
            after_state={
                "chat_id": chat,
                "is_active": is_active,
                "token_suffix": mask_token(token),
            },
        )
        return self.current(tenant_id=tenant_id, actor=actor)

    def set_active(
        self, *, tenant_id: TenantId, actor: Employee, is_active: bool
    ) -> TelegramConfigView:
        """Aktiv/Deaktiv keçidi — token TOXUNULMUR.

        Deaktivləşdirmə token-i SİLMİR: Root botu müvəqqəti susdurub sonra
        yenidən qoşmaq istəyəndə hər dəfə token-i yenidən yapışdırmalı
        olsaydı, praktikada botu heç vaxt söndürməzdi.
        """
        self._require(actor)
        now = self._clock.now()
        self._repository.set_active(tenant_id, is_active=is_active, updated_by=actor.id, at=now)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TELEGRAM_CONFIG_ACTIVATED" if is_active else "TELEGRAM_CONFIG_DEACTIVATED",
            entity_type="telegram_config",
            entity_id=str(tenant_id),
            after_state={"is_active": is_active},
        )
        return self.current(tenant_id=tenant_id, actor=actor)

    def send_test_message(self, *, tenant_id: TenantId, actor: Employee, text: str = "") -> bool:
        """`[Test Mesajı Göndər]` — qoşulmanın FAKTİKİ yoxlanması.

        `is_active` YOXLANMIR: test mesajı məhz qoşulmanı yoxlamaq üçündür
        və deaktiv botu sınamaq qadağan olsaydı, Root «işləyirmi?» sualına
        cavab tapmadan aktivləşdirməyə məcbur qalardı.
        """
        self._require(actor)
        settings = self._repository.load(tenant_id)
        if settings is None or not settings.bot_token or not settings.chat_id:
            raise TelegramConfigError(
                "Telegram ayarları natamamdır",
                user_message="Əvvəlcə bot token və chat ID yazın.",
            )
        if self._probe is None:
            raise TelegramConfigError(
                "Telegram şlüzü qurulmayıb",
                user_message="Test mesajı göndərilə bilmədi — şlüz aktiv deyil.",
            )
        message = text.strip() or "KompasOS: test mesajı. Bot düzgün qoşulub."
        delivered = self._probe.send_test_message(settings, message)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TELEGRAM_TEST_MESSAGE",
            entity_type="telegram_config",
            entity_id=str(tenant_id),
            after_state={"delivered": delivered},
        )
        return delivered

    # ------------------------------- köməkçi --------------------------------- #

    def _require(self, actor: Employee) -> None:
        if self.may_manage(actor):
            return
        _security_log.warning(
            "TELEGRAM_CONFIG_DENIED",
            extra={"actor_id": str(actor.id), "flag": MANAGE_TELEGRAM_FLAG},
        )
        raise TelegramAccessError(
            f"«{MANAGE_TELEGRAM_FLAG}» səlahiyyəti yoxdur",
            context={"actor_id": str(actor.id)},
        )


def mask_token(token: str) -> str:
    """`1234567890:AAG...xyz` → `••••xyz9`.

    Boş token boş qalır — «•••• » göstərmək qurulmamış botu qurulmuş kimi
    göstərərdi.
    """
    cleaned = token.strip()
    if not cleaned:
        return ""
    suffix = cleaned[-TOKEN_VISIBLE_SUFFIX:]
    return f"{'•' * 8}{suffix}"


__all__ = [
    "MIN_TOKEN_LENGTH",
    "TOKEN_VISIBLE_SUFFIX",
    "TelegramAccessError",
    "TelegramConfigError",
    "TelegramConfigRepository",
    "TelegramConfigUseCase",
    "TelegramConfigView",
    "TelegramProbe",
    "TelegramSettings",
    "mask_token",
]
