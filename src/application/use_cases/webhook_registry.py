"""Webhook reyestri — ÜMUMİ genişlənmə səthi (`v2backlog.md` Faza 12.2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ İNTEQRASİYA YOX, YALNIZ REYESTR
──────────────────────────────────────────────────────────────────────────────
Sənəd bu bənddə qəsdən məhdudlaşdırıcıdır: «İNDİ konkret bir inteqrasiya
YAZMA, YALNIZ struktur». Ona görə burada NƏ göndərən kod, NƏ də təkrar-cəhd
növbəsi var — yalnız «hansı hadisə baş verəndə hansı URL çağırılacaq»
qeydiyyatı. Çatdırma qatı gələcəkdə bu reyestri OXUYACAQ; reyestrin özü isə
onsuz da tam mənalıdır, çünki Root inteqrasiyanı ƏVVƏLCƏDƏN qura bilir.

──────────────────────────────────────────────────────────────────────────────
URL YOXLAMASI NİYƏ BURADADIR, ÇATDIRMA QATINDA YOX
──────────────────────────────────────────────────────────────────────────────
`migrations/091` başlığı SSRF qorunmasını «çatdırma qatının işi» adlandırır —
və bu, göndərmə anı üçün doğrudur. Lakin çatdırma qatı HƏLƏ YOXDUR, sətir isə
İNDİ yazılır: yoxlamasız reyestr `http://169.254.169.254/...` kimi bir hədəfi
sükutla qəbul edər, qüsur isə yalnız aylar sonra, ilk göndərişdə üzə çıxardı.
Ona görə qapı YAZI anındadır. Bu, çatdırma qatının öz yoxlamasını ƏVƏZ ETMİR
(CLAUDE.md §5: hər qayda İKİ yerdə) — sətir bazadan sonra da dəyişdirilə
bilər (birbaşa SQL), yəni göndərən kod onu yenidən yoxlamalıdır.

Qadağan edilənlər və SƏBƏBLƏRİ:

  * `https` OLMAYAN sxem — payload-da işçi adı, cərimə məbləği kimi şəxsi
    məlumat ola bilər; `http` onu şəbəkədə açıq daşıyardı.
  * loopback / private / link-local / ULA ünvanlar — bunlar İNTERNETDƏ
    deyil, KİOSKUN ÖZ şəbəkəsindədir. Belə hədəf «xarici inteqrasiya» deyil,
    daxili şəbəkəni skan etmək üçün istifadə oluna bilən bir alətdir (SSRF).
  * URL-də kimlik məlumatı (`istifadəçi:parol@host`) — o, jurnala və audit
    sətrinə düşərdi; imza üçün onsuz da ayrıca `secret` var.

──────────────────────────────────────────────────────────────────────────────
SİLMƏ YOX, DEAKTİVASİYA
──────────────────────────────────────────────────────────────────────────────
`catalogs.py`-ın eyni qərarı: sətir silinsəydi, «bu hadisə keçmişdə hara
göndərilirdi?» sualı cavabsız qalardı. Səhv URL deaktiv edilir, düzgünü isə
yeni sətir kimi əlavə olunur (unikal açar `tenant + hadisə + URL` olduğuna
görə ikisi yan-yana yaşayır).

──────────────────────────────────────────────────────────────────────────────
SİRR GERİ QAYTARILMIR
──────────────────────────────────────────────────────────────────────────────
`TelegramConfigUseCase`-in eyni qərarı: `WebhookEndpointView` imza açarını
DAŞIMIR. Root paneli demo və ekran-paylaşımı zamanı açıq olur; açarı ekrana
qaytarmaq onu həmin anların hamısında ifşa edərdi.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlsplit

from src.domain.value_objects.authorization import SystemRole
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: `migrations/093` — `hardlock_level = 1`, yəni DB səviyyəsində YALNIZ Root.
MANAGE_WEBHOOKS_FLAG = "can_manage_webhooks"

#: `webhook_endpoints.event_type` CHECK-inin güzgüsü (>= 3 simvol, BÖYÜK hərf).
MIN_EVENT_TYPE_LENGTH = 3

#: Hadisə adının icazəli əlifbası — normallaşdırmadan SONRA yoxlanılır.
#:
#: NİYƏ MƏHDUD: ad gələcəkdə HTTP başlığına (`X-KompasOS-Event`) düşəcək və
#: boşluq/nəzarət simvolu orada sətir bölünməsinə (header injection) səbəb ola
#: bilər. Nöqtə və alt-xətt saxlanılır, çünki `FINE.PUBLISHED` kimi ad ağacları
#: praktikada ən çox işlənən formadır.
_EVENT_TYPE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_.]*$")

#: HMAC imza açarının minimal uzunluğu.
#:
#: ROOT PARAMETRİ DEYİL: bu, kriptoqrafik minimumdur, əməliyyat siyasəti yox.
#: Root onu 4-ə endirsəydi imza mexanizminin ÖZÜ mənasız olardı — açar brute
#: force ilə tapılar və hədəf server saxta payload-u KompasOS-dan gəlmiş kimi
#: qəbul edərdi. (`SHORT_CODE_LENGTH`-in tərs halı: orada insan erqonomikası
#: həll edir, burada riyazi güc.)
MIN_SECRET_LENGTH = 16

#: `target_url` sütununun `CHECK` şərtinin güzgüsü (migrations/091).
MIN_TARGET_URL_LENGTH = 8


class WebhookRegistryError(KompasOSError):
    """Webhook qeydiyyatı yazıla bilmədi."""

    user_message = "Webhook qeydiyyatı saxlanmadı."


class WebhookAccessError(KompasOSError):
    """Reyestr YALNIZ Root-dadır."""

    user_message = "Webhook reyestrini yalnız Root idarə edə bilər."


@dataclass(frozen=True)
class WebhookEndpointView:
    """Root ekranının gördüyü sətir — SİRR DAŞIMIR (bax modul başlığı)."""

    endpoint_id: str
    event_type: str
    target_url: str
    is_active: bool
    created_at: datetime | None = None
    created_by_name: str = ""


@runtime_checkable
class WebhookEndpointRepository(Protocol):
    """`webhook_endpoints` (migrations/091).

    ŞİFRƏLƏMƏ BU PORTUN ARXASINDADIR — use case açıq mətnli `secret` ilə
    işləyir, `secret_encrypted` sütununu implementasiya doldurur
    (`TelegramConfigRepository` ilə eyni naxış).

    Port `ports.py`-a DEYİL, BURAYA yazılıb: qaytardığı `WebhookEndpointView`
    tətbiq qatının strukturudur, domen tipi deyil (CLAUDE.md §3).
    """

    def list_all(self, tenant_id: TenantId) -> list[WebhookEndpointView]: ...

    def add(
        self,
        tenant_id: TenantId,
        *,
        event_type: str,
        target_url: str,
        secret: str,
        created_by: EmployeeId,
        at: datetime,
    ) -> WebhookEndpointView: ...

    def set_active(self, tenant_id: TenantId, *, endpoint_id: str, is_active: bool) -> bool:
        """Sətir yoxdursa `False` — çağıran «tapılmadı»nı ayırd edə bilməlidir."""
        ...


class WebhookRegistryUseCase:
    """«Webhook Reyestri» kartının arxa tərəfi (ROOT İdarə Mərkəzi)."""

    def __init__(
        self,
        *,
        repository: WebhookEndpointRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    # ------------------------------ görünürlük ------------------------------- #

    def may_manage(self, actor: Employee) -> bool:
        """Kart ekranda görünsünmü.

        İKİ ŞƏRT: sistem rolu VƏ flag — `TelegramConfigUseCase.may_manage` ilə
        eyni əsaslandırma. Flag `hardlock_level = 1` ilə qorunur
        (migrations/093), yəni DB onu Root-dan başqasına verməyə icazə vermir;
        buradakı rol yoxlaması həmin qapının İKİNCİ nüsxəsidir və `schema.sql`
        ilə təmiz quraşdırmada da işləyir (CLAUDE.md §5).
        """
        if actor.position.effective_system_role is not SystemRole.ROOT:
            return False
        return actor.has_permission(MANAGE_WEBHOOKS_FLAG, now=self._clock.now())

    # -------------------------------- oxuma ---------------------------------- #

    def list_endpoints(self, *, tenant_id: TenantId, actor: Employee) -> list[WebhookEndpointView]:
        """Qeydiyyatdan keçmiş bütün hədəflər — DEAKTİVLƏR DƏ daxil.

        Deaktivlər gizlədilsəydi, eyni URL ikinci dəfə əlavə edilməyə çalışılar
        və unikal açar pozuntusu istifadəçiyə anlaşılmaz xəta kimi görünərdi.
        """
        self._require(actor)
        return self._repository.list_all(tenant_id)

    # --------------------------------- yazı ---------------------------------- #

    def register(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        event_type: str,
        target_url: str,
        secret: str,
    ) -> WebhookEndpointView:
        """Yeni hədəf əlavə edir — hadisə adı normallaşır, URL yoxlanılır."""
        self._require(actor)
        normalized_event = _normalized_event_type(event_type)
        normalized_url = _validated_url(target_url)
        key = secret.strip()
        if len(key) < MIN_SECRET_LENGTH:
            raise WebhookRegistryError(
                f"İmza açarı minimum {MIN_SECRET_LENGTH} simvol olmalıdır",
                user_message=(
                    f"İmza açarı çox qısadır — minimum {MIN_SECRET_LENGTH} simvol yazın."
                ),
                context={"length": len(key)},
            )

        now = self._clock.now()
        view = self._repository.add(
            tenant_id,
            event_type=normalized_event,
            target_url=normalized_url,
            secret=key,
            created_by=actor.id,
            at=now,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="WEBHOOK_ENDPOINT_REGISTERED",
            entity_type="webhook_endpoint",
            entity_id=view.endpoint_id,
            # İMZA AÇARI AUDİTƏ DÜŞMÜR: audit jurnalı ekranda oxunur (Audit Log
            # ekranı) — açarı ora yazmaq onu maskasız göstərmək olardı.
            after_state={
                "event_type": normalized_event,
                "target_url": normalized_url,
                "is_active": True,
            },
        )
        _security_log.info(
            "WEBHOOK_ENDPOINT_REGISTERED",
            extra={
                "tenant_id": str(tenant_id),
                "actor_id": str(actor.id),
                "event_type": normalized_event,
                "target_url": normalized_url,
            },
        )
        return view

    def set_active(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        endpoint_id: str,
        is_active: bool,
    ) -> None:
        """Hədəfi açır/söndürür — SİLMİR (bax modul başlığı)."""
        self._require(actor)
        if not self._repository.set_active(tenant_id, endpoint_id=endpoint_id, is_active=is_active):
            raise WebhookRegistryError(
                f"Webhook sətri tapılmadı: {endpoint_id}",
                user_message="Bu webhook artıq mövcud deyil — siyahını yeniləyin.",
                context={"endpoint_id": endpoint_id},
            )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="WEBHOOK_ENDPOINT_TOGGLED",
            entity_type="webhook_endpoint",
            entity_id=endpoint_id,
            after_state={"is_active": is_active},
        )
        _security_log.info(
            "WEBHOOK_ENDPOINT_TOGGLED",
            extra={
                "tenant_id": str(tenant_id),
                "actor_id": str(actor.id),
                "endpoint_id": endpoint_id,
                "is_active": is_active,
            },
        )

    # ------------------------------- daxili ---------------------------------- #

    def _require(self, actor: Employee) -> None:
        if not self.may_manage(actor):
            _security_log.warning(
                "WEBHOOK_ACCESS_DENIED",
                extra={
                    "actor_id": str(actor.id),
                    "role": actor.position.effective_system_role.value,
                },
            )
            raise WebhookAccessError(
                "Webhook reyestri yalnız Root üçündür",
                context={"actor_id": str(actor.id)},
            )


def _normalized_event_type(raw: str) -> str:
    """`  fine.published ` → `FINE.PUBLISHED`.

    NORMALLAŞMA YOXLAMADAN ƏVVƏLDİR: DB CHECK-i `event_type = upper(...)`
    tələb edir, yəni kiçik hərflə yazılmış ad bazada RƏDD olunardı və
    istifadəçi səbəbini anlamazdı. Burada ad əvvəlcə düzəldilir, sonra əlifba
    yoxlanılır — istifadəçi xəbərdarlıq əvəzinə işləyən nəticə alır.
    """
    normalized = raw.strip().upper()
    if len(normalized) < MIN_EVENT_TYPE_LENGTH:
        raise WebhookRegistryError(
            f"Hadisə tipi minimum {MIN_EVENT_TYPE_LENGTH} simvol olmalıdır",
            user_message="Hadisə tipi çox qısadır.",
            context={"event_type": normalized},
        )
    if not _EVENT_TYPE_PATTERN.match(normalized):
        raise WebhookRegistryError(
            f"Hadisə tipində icazəsiz simvol var: {normalized}",
            user_message=(
                "Hadisə tipində yalnız hərf, rəqəm, nöqtə və alt-xətt ola bilər "
                "(məsələn: FINE.PUBLISHED)."
            ),
            context={"event_type": normalized},
        )
    return normalized


def _validated_url(raw: str) -> str:
    """HTTPS + xarici ünvan qapısı (bax modul başlığı, SSRF)."""
    url = raw.strip()
    if len(url) < MIN_TARGET_URL_LENGTH:
        raise WebhookRegistryError(
            "Hədəf URL çox qısadır",
            user_message="Hədəf URL düzgün görünmür.",
            context={"target_url": url},
        )
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise WebhookRegistryError(
            f"Yalnız HTTPS qəbul edilir: {parts.scheme or '(sxem yoxdur)'}",
            user_message="Hədəf ünvan `https://` ilə başlamalıdır.",
            context={"scheme": parts.scheme},
        )
    if parts.username or parts.password:
        raise WebhookRegistryError(
            "URL-də kimlik məlumatı var",
            user_message=(
                "Ünvanda istifadəçi adı/parol olmamalıdır — imza açarından istifadə edin."
            ),
        )
    host = (parts.hostname or "").strip()
    if not host:
        raise WebhookRegistryError(
            "URL-də host yoxdur",
            user_message="Hədəf ünvanda domen adı yoxdur.",
        )
    if _is_internal_host(host):
        raise WebhookRegistryError(
            f"Daxili şəbəkə ünvanı qadağandır: {host}",
            user_message=(
                "Bu ünvan daxili şəbəkəyə aiddir. Webhook yalnız xarici, "
                "internetdə əlçatan ünvana göndərilə bilər."
            ),
            context={"host": host},
        )
    return url


def _is_internal_host(host: str) -> bool:
    """Loopback / private / link-local / ULA — həm ad, həm IP formasında.

    AD SƏVİYYƏSİNDƏ YOXLAMA TAM DEYİL və bu, bilərəkdəndir: `internal.corp`
    kimi bir ad DNS-də daxili ünvana həll oluna bilər və onu YAZI anında bilmək
    mümkün deyil (DNS sorğusu atmaq isə yazı yolunu şəbəkədən asılı edərdi).
    Ona görə burada YALNIZ birmənalı hallar tutulur; qalanını göndərmə anındakı
    ikinci yoxlama tutmalıdır (bax modul başlığı).
    """
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


__all__ = [
    "MANAGE_WEBHOOKS_FLAG",
    "MIN_SECRET_LENGTH",
    "WebhookAccessError",
    "WebhookEndpointRepository",
    "WebhookEndpointView",
    "WebhookRegistryError",
    "WebhookRegistryUseCase",
]
