"""`telegram_config` + `telegram_config_history` (CHAT-1 Faza 3, migrations/068).

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏLƏMƏ BURADADIR, USE CASE-DƏ YOX
──────────────────────────────────────────────────────────────────────────────
`TelegramConfigUseCase` açıq mətnli token ilə işləyir; onun şifrəli sütuna
necə düşdüyünü BU sinif bilir. Alternativ — tətbiq qatında şifrələmək —
rədd edildi: onda application qatı infrastruktur sinfini birbaşa idxal
edərdi və «hansı sütun şifrəlidir?» qərarı iki qatda yaşayardı (eyni naxış
`FaceEmbeddingRepository` və `ErpServerRegistry`-də).

──────────────────────────────────────────────────────────────────────────────
AAD (KONTEKST) NİYƏ KİRAYƏÇİ İD-Sİdir
──────────────────────────────────────────────────────────────────────────────
`context=f"telegram_config:{tenant_id}"` şifrəli dəyəri ÖZ sətrinə bağlayır:
bir kirayəçinin token sətrini digərinin sətrinə köçürmək (baza faylına
birbaşa çıxışı olan hücumçu üçün mümkün əməliyyat) deşifrə mərhələsində
uğursuz olur. Kontekstsiz şifrələmə bu köçürməni sükutla qəbul edərdi.

`tenant_id` BURADA `self._tenant`-dəndir (metod arqumentindən DEYİL) — bax
sinif başlığındakı "İKİNCİ-QAT" bölməsi. `save()`-in şifrələdiyi kontekstlə
`load()`/`describe()`-in deşifrə etdiyi kontekst EYNİ mənbədən (bağlantının
`TenantContext`-i) gəlməlidir, əks halda arqument təsadüfən fərqli
ötürülən bir çağırış AAD uyğunsuzluğu ÜZÜNDƏN deşifrəni sükutla
uğursuz edərdi (bax `load()` və `describe()`-dəki "DEŞİFRƏ UĞURSUZLUĞU"
şərhi) — düzgün sətir tapılsa belə.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.use_cases.telegram_config import (
    TelegramConfigView,
    TelegramSettings,
    mask_token,
)
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Any

    from psycopg import Connection

    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.persistence.connection import TenantContext
    from src.infrastructure.security.encryption import EncryptionService

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


def _context_of(tenant_id: TenantId) -> str:
    return f"telegram_config:{tenant_id}"


class PostgresTelegramConfigRepository(_BaseRepository):
    """Kirayəçi başına BİR sətir + dəyişiklik arxivi.

    ──────────────────────────────────────────────────────────────────────────
    `tenant_id` ARQUMENTİ İKİNCİ-QAT ÜÇÜN DEYİL — `self._tenant` ƏSAS MƏNBƏDİR
    ──────────────────────────────────────────────────────────────────────────
    CLAUDE.md §6 "Repository" naxışı `self._tenant`-i RLS-ə ƏLAVƏ ikinci qat
    kimi tələb edir (bax `support_repositories.py`-dakı eyni naxış — entity
    ID-si ilə çağırılan metodlar `self._tenant`-i ƏLAVƏ `WHERE` şərti kimi
    işlədir). Əvvəl bu sinif hər metodda ÇAĞIRANIN ötürdüyü `tenant_id`
    arqumentini birbaşa `WHERE`/`INSERT`-ə yazırdı — RLS bu cədvəl üçün TƏK
    qalan qoruma idi.

    İndi BEŞ metodun (`load`/`describe`/`save`/`set_active`/`archive`)
    hamısı `self._tenant`-i (bağlantının ÖZ `TenantContext`-i, çağırandan
    ASILI OLMAYAN mənbə) işlədir. `tenant_id` arqumenti imza uyğunluğu üçün
    QALIR (`TelegramConfigRepository` Protocol-u onu tələb edir, çağıran isə
    `composition.py`-dır — `ui` sahəsi, buradan toxunulmur), amma sorğunun
    NƏTİCƏSİNƏ artıq TƏSİR ETMİR.

    ARQUMENT İLƏ `self._tenant` FƏRQLİ OLARSA NƏ BAŞ VERİR: sorğu/yazı YENƏ
    `self._tenant`-ə görə gedir — çağıran səhvən başqa kirayəçinin ID-sini
    ötürsə belə, bu repo YALNIZ ÖZ bağlantısının kirayəçisinə aid sətri
    oxuyur/dəyişir, arqumentdəkini HEÇ VAXT. Praktiki fərq HAZIRDA yoxdur
    (yeganə çağırış yeri, `composition.py:2501`, həmişə `self._tenant_id`
    ötürür), amma bu dəyişiklik gələcək bir çağırış səhvini SÜKUTLA
    cross-tenant sızıntıya çevirmək əvəzinə zərərsiz nəticəsizliyə (boş
    oxu / toxunmayan yazı) çevirir.
    """

    def __init__(
        self,
        conn: Connection[dict[str, Any]],
        context: TenantContext,
        *,
        encryption: EncryptionService,
    ) -> None:
        """`encryption` DEFOLTSUZDUR — açıq ötürülməlidir.

        `EncryptionService()` defolt kimi qoyulsaydı, kompozisiya kökü onu
        unutduqda repozitoriya SÜKUTLA ikinci, fərqli açar nüsxəsi qurardı
        və köhnə sətirlər deşifrə edilə bilməzdi (eyni qərar
        `face_repository.py`-dadır).
        """
        super().__init__(conn, context)
        self._encryption = encryption

    def load(self, tenant_id: TenantId) -> TelegramSettings | None:
        # `tenant_id` bu sorğuda İŞLƏNMİR — bax sinif başlığı.
        row = self._fetch_one(
            """
            SELECT bot_token_encrypted, chat_id, is_active
            FROM telegram_config
            WHERE tenant_id = %s
            """,
            (self._tenant,),
        )
        if not row:
            return None
        try:
            token = self._encryption.decrypt(
                row["bot_token_encrypted"], context=_context_of(self._tenant)
            )
        except Exception:
            # DEŞİFRƏ UĞURSUZLUĞU ÇÖKMƏ DEYİL: açar dəyişdirilibsə (yeni
            # quraşdırma, itmiş `KOMPASOS_FERNET_KEY`) bot işləməyəcək,
            # amma dəstək chat-i işləməyə DAVAM etməlidir — mesaj yenə də
            # bazaya yazılır, sadəcə Telegram-a getmir.
            _error_log.exception("TELEGRAM_TOKEN_DECRYPT_FAILED")
            return None
        return TelegramSettings(
            bot_token=token,
            chat_id=str(row["chat_id"]),
            is_active=bool(row["is_active"]),
        )

    def describe(self, tenant_id: TenantId) -> TelegramConfigView | None:
        """Ekran görünüşü — token MASKALANMIŞ.

        Maska şifrəli mətndən deyil, DEŞİFRƏ edilmiş token-dən qurulur:
        şifrəli sətrin son dörd simvolu təsadüfi base64 hərfləridir və Root
        onunla öz botunu tanıya bilməzdi. Deşifrə uğursuz olarsa maska boş
        qalır — «qurulub, amma oxunmur» vəziyyəti gizlədilmir.
        """
        # `tenant_id` bu sorğuda İŞLƏNMİR — bax sinif başlığı.
        row = self._fetch_one(
            """
            SELECT c.bot_token_encrypted, c.chat_id, c.is_active, c.updated_at,
                   e.first_name, e.last_name
            FROM telegram_config c
            LEFT JOIN employees e ON e.id = c.updated_by
            WHERE c.tenant_id = %s
            """,
            (self._tenant,),
        )
        if not row:
            return None
        try:
            token = self._encryption.decrypt(
                row["bot_token_encrypted"], context=_context_of(self._tenant)
            )
        except Exception:
            _error_log.exception("TELEGRAM_TOKEN_DECRYPT_FAILED")
            token = ""
        first = str(row["first_name"] or "").strip()
        last = str(row["last_name"] or "").strip()
        return TelegramConfigView(
            masked_token=mask_token(token),
            chat_id=str(row["chat_id"]),
            is_active=bool(row["is_active"]),
            updated_at=row["updated_at"],
            updated_by_name=f"{first} {last}".strip(),
        )

    def save(
        self,
        tenant_id: TenantId,
        *,
        bot_token: str,
        chat_id: str,
        is_active: bool,
        updated_by: EmployeeId,
        at: datetime,
    ) -> None:
        # `tenant_id` YAZILAN sətrin açarı üçün İŞLƏNMİR — bax sinif başlığı:
        # yeni sətir də HƏMİŞƏ bağlantının ÖZ kirayəçisinə (`self._tenant`)
        # aid yaranır, arqumentin dəyərindən asılı olmayaraq.
        sealed = self._encryption.encrypt(bot_token, context=_context_of(self._tenant))
        self._execute(
            """
            INSERT INTO telegram_config
                (tenant_id, bot_token_encrypted, chat_id, is_active, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                bot_token_encrypted = EXCLUDED.bot_token_encrypted,
                chat_id             = EXCLUDED.chat_id,
                is_active           = EXCLUDED.is_active,
                updated_by          = EXCLUDED.updated_by,
                updated_at          = EXCLUDED.updated_at
            """,
            (self._tenant, sealed, chat_id, is_active, updated_by, at),
        )

    def set_active(
        self, tenant_id: TenantId, *, is_active: bool, updated_by: EmployeeId, at: datetime
    ) -> None:
        # `tenant_id` bu sorğuda İŞLƏNMİR — bax sinif başlığı.
        self._execute(
            """
            UPDATE telegram_config
            SET is_active = %s, updated_by = %s, updated_at = %s
            WHERE tenant_id = %s
            """,
            (is_active, updated_by, at, self._tenant),
        )

    def archive(self, tenant_id: TenantId, *, replaced_by: EmployeeId, at: datetime) -> bool:
        """Cari sətri tarixçəyə köçürür (silmədən).

        `INSERT ... SELECT` istifadə olunur: şifrəli dəyər DEŞİFRƏ EDİLMƏDƏN
        köçürülür. Deşifrə edib yenidən şifrələsəydik, açıq token bir anlıq
        prosesin yaddaşına düşərdi — halbuki arxiv üçün buna ehtiyac yoxdur.

        `tenant_id` bu sorğuda İŞLƏNMİR — bax sinif başlığı.
        """
        affected = self._execute(
            """
            INSERT INTO telegram_config_history
                (tenant_id, bot_token_encrypted, chat_id, replaced_by, replaced_at)
            SELECT tenant_id, bot_token_encrypted, chat_id, %s, %s
            FROM telegram_config
            WHERE tenant_id = %s
            """,
            (replaced_by, at, self._tenant),
        )
        return affected > 0


__all__ = ["PostgresTelegramConfigRepository"]
