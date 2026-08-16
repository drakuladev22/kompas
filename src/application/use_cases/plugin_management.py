"""Plugin idarəetməsi — quraşdırma, aktivləşdirmə, silmə (bölmə 1).

Bölmə 1: *"Plugin-lər ayrıca prosesdə icra olunur, birbaşa DB credentials-a
çıxışı olmur, yalnız whitelisted API səthi üzərindən işləyir. Yalnız Root/CEO
tərəfindən [quraşdırıla/aktivləşdirilə bilər]."*

Yuxarıdakı sitatdakı "Root/CEO" spesifikasiyanın ÜMUMİ ifadəsidir; icazə
kataloqu (`schema.sql` §22) onu DƏQİQLƏŞDİRİR və `can_manage_plugins`-ə
`hardlock_level = 1` (`ROOT_ONLY`) verir. Kataloq bağlayıcıdır — `_require`
buna uyğun olaraq YALNIZ `Root` buraxır (bax həmin metodun docstring-i).

Sandbox, imza yoxlaması və capability whitelist-i ARTIQ Faza 2-dədir
(`infrastructure/plugins/`). Bu modul onların üzərinə YALNIZ idarəetmə
qərarlarını əlavə edir — həmin məntiq təkrar yazılmır.

──────────────────────────────────────────────────────────────────────────────
İMZASIZ PLUGIN NİYƏ QURAŞDIRILMIR
──────────────────────────────────────────────────────────────────────────────
Sandbox plugin-in NƏ EDƏ BİLƏCƏYİNİ məhdudlaşdırır, lakin onun KİM TƏRƏFİNDƏN
yazıldığını demir. İmzasız paket "məhdud səlahiyyətli, mənbəyi naməlum kod"
deməkdir — sandbox səhvi aşkarlanarsa, kimin məsuliyyət daşıdığı da bilinməz.
Ona görə imza yoxlaması quraşdırmanın ÖN ŞƏRTİDİR, xəbərdarlıq deyil.

──────────────────────────────────────────────────────────────────────────────
YENİ PLUGIN NİYƏ DƏRHAL AKTİV OLMUR
──────────────────────────────────────────────────────────────────────────────
Quraşdırılan plugin `PENDING_APPROVAL` doğulur və ayrıca `approve()` tələb
edir. Bir addımda aktivləşsəydi, "səhvən quraşdırdım" ilə "işlətməyə razıyam"
arasında fərq qalmazdı — geri qaytarılması ən çətin qərar bir klikə düşərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from src.domain.value_objects.authorization import SystemRole
from src.infrastructure.plugins.contracts import (
    PluginError,
    PluginSignatureError,
    PluginStatus,
)
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock
    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.plugins.contracts import PluginManifest

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

MANAGE_PLUGINS_FLAG = "can_manage_plugins"


class PluginManagementError(PluginError):
    """Plugin əməliyyatı qadağandır."""

    user_message = "Bu plugin əməliyyatı icra edilə bilmədi."


@dataclass(frozen=True)
class InstalledPlugin:
    """`plugins` cədvəlinin bir sətri — ekranın gözlədiyi formada."""

    plugin_id: str
    name: str
    version: str
    publisher: str
    status: PluginStatus
    signature_verified: bool
    #: Sətrin `manifest` sütunu (audit G-3). DEFOLT `None` VƏ BU, QƏSDƏNDİR:
    #: sahə mövcud çağırış nöqtələrinin heç birini dəyişmir (`as_row`, ekran,
    #: testlər) və yalnız İNTERFEYS SƏTHİNƏ (`presentation/plugin_surface.py`)
    #: lazımdır — plugin-in hansı qabiliyyəti və hansı icazə flag-lərini elan
    #: etdiyi YALNIZ manifestdə yaşayır. Oxuna bilməyən/boş manifest `None`
    #: qalır və həmin plugin səth VERMİR (fail-closed).
    manifest: PluginManifest | None = None
    #: Paketin fayl sistemindəki yolu (`plugins.package_path`, migrations/055).
    #: DEFOLT BOŞ VƏ BU, QƏSDƏNDİR — `manifest` ilə eyni əsaslandırma: sahə
    #: mövcud çağırış nöqtələrinin heç birini dəyişmir və yalnız plugin
    #: SƏHİFƏSİNİN icra yoluna lazımdır (`PluginSandbox` alt-prosesi məhz bu
    #: faylı işə salır). Boş sətir "yol qeydə alınmayıb" deməkdir və
    #: FAIL-CLOSED oxunur: kod icra OLUNMUR, istifadəçi səbəbi görür (bax
    #: `presentation/controllers/plugin_page.py`).
    package_path: str = ""

    @property
    def is_enabled(self) -> bool:
        return self.status is PluginStatus.APPROVED

    @property
    def signature_label(self) -> str:
        """Ekrandakı imza nişanı — `group_i.PluginScreen` ilə eyni dəyərlər."""
        return "valid" if self.signature_verified else "unsigned"

    def as_row(self) -> dict[str, str]:
        return {
            "id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "enabled": "1" if self.is_enabled else "0",
            "signature": self.signature_label,
        }


class PluginRegistry(Protocol):
    """`plugins` cədvəli."""

    def list_all(self, tenant_id: TenantId) -> list[InstalledPlugin]: ...

    def get(self, plugin_id: str) -> InstalledPlugin | None: ...

    def install(
        self,
        tenant_id: TenantId,
        *,
        manifest: PluginManifest,
        digest: str,
        installed_by: object,
        package_path: str = "",
    ) -> str: ...

    def set_status(self, plugin_id: str, status: PluginStatus, *, changed_by: object) -> None: ...

    def remove(self, plugin_id: str) -> None: ...


class SignatureVerifier(Protocol):
    """`PluginSignatureVerifier`-in lazım olan hissəsi."""

    def verify(self, *, plugin_path: Path, manifest: PluginManifest, signature_hex: str) -> str: ...


class PluginManagementUseCase:
    """Quraşdırma, təsdiq, söndürmə və silmə — hamısı audit-lənir."""

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        verifier: SignatureVerifier,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._verifier = verifier
        self._audit = audit
        self._clock = clock

    def list_plugins(self, *, tenant_id: TenantId, actor: Employee) -> list[InstalledPlugin]:
        self._require(actor, now=self._clock.now())
        return self._registry.list_all(tenant_id)

    # ------------------------------ quraşdırma ------------------------------- #

    def install(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        plugin_path: Path,
        manifest: PluginManifest,
        signature_hex: str,
    ) -> InstalledPlugin:
        """Paketi quraşdırır — İMZA YOXLAMASI ÖN ŞƏRTDİR (modul başlığına bax)."""
        now = self._clock.now()
        self._require(actor, now=now)

        try:
            digest = self._verifier.verify(
                plugin_path=plugin_path, manifest=manifest, signature_hex=signature_hex
            )
        except PluginSignatureError:
            _security_log.warning(
                "PLUGIN_INSTALL_BLOCKED_SIGNATURE",
                extra={"actor_id": str(actor.id), "plugin": manifest.name},
            )
            # Orijinal istisna OLDUĞU KİMİ ötürülür: onun mesajı imzanın
            # NİYƏ rədd edildiyini deyir (naşir tanınmır / dayces uyğun gəlmir),
            # burada onu ümumiləşdirmək diaqnostikanı korlayardı.
            raise

        # YOL DA YAZILIR (migrations/055): `plugin_path` ƏVVƏL yalnız imza
        # yoxlamasına girirdi və heç yerə düşmürdü, yəni quraşdırmadan sonra
        # host paketin harada olduğunu bilmirdi və plugin KODU heç vaxt icra
        # oluna bilmirdi. Yoxlamadan SONRA yazılır: imza rədd edilibsə sətir
        # ümumiyyətlə yaranmır, yəni etibarsız paketin yolu bazaya düşmür.
        plugin_id = self._registry.install(
            tenant_id,
            manifest=manifest,
            digest=digest,
            installed_by=actor.id,
            package_path=str(plugin_path),
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PLUGIN_INSTALLED",
            entity_type="plugin",
            entity_id=plugin_id,
            after_state={
                "name": manifest.name,
                "version": manifest.version,
                "publisher": manifest.publisher,
                "capabilities": sorted(c.value for c in manifest.capabilities),
                "status": PluginStatus.PENDING_APPROVAL.value,
            },
        )
        _security_log.warning(
            "PLUGIN_INSTALLED",
            extra={"actor_id": str(actor.id), "plugin": manifest.name, "digest": digest[:12]},
        )
        return InstalledPlugin(
            plugin_id=plugin_id,
            name=manifest.name,
            version=manifest.version,
            publisher=manifest.publisher,
            status=PluginStatus.PENDING_APPROVAL,
            signature_verified=True,
            package_path=str(plugin_path),
        )

    # -------------------------------- qərarlar -------------------------------- #

    def set_enabled(
        self, *, tenant_id: TenantId, actor: Employee, plugin_id: str, enabled: bool
    ) -> InstalledPlugin:
        """Plugin-i aktivləşdirir/söndürür."""
        now = self._clock.now()
        self._require(actor, now=now)

        plugin = self._load(plugin_id)
        if enabled and not plugin.signature_verified:
            raise PluginManagementError(
                f"'{plugin.name}': imzası doğrulanmamış plugin aktivləşdirilə bilməz",
                user_message="İmzası doğrulanmamış plugin işə salına bilməz.",
            )

        status = PluginStatus.APPROVED if enabled else PluginStatus.DISABLED
        self._registry.set_status(plugin_id, status, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PLUGIN_ENABLED" if enabled else "PLUGIN_DISABLED",
            entity_type="plugin",
            entity_id=plugin_id,
            before_state={"status": plugin.status.value},
            after_state={"status": status.value},
        )
        return InstalledPlugin(
            plugin_id=plugin.plugin_id,
            name=plugin.name,
            version=plugin.version,
            publisher=plugin.publisher,
            status=status,
            signature_verified=plugin.signature_verified,
            # Yol OXUNAN sətirdən daşınır: `set_status` onu bazada dəyişmir,
            # ona görə qaytarılan obyekt də onu İTİRMƏMƏLİDİR — əks halda
            # aktivləşdirmədən sonra qayıdan nüsxə "yolu yoxdur" deyərdi.
            package_path=plugin.package_path,
        )

    def remove(self, *, tenant_id: TenantId, actor: Employee, plugin_id: str) -> None:
        """Plugin-i silir.

        Burada soft delete YOXDUR — kataloqdan fərqli olaraq plugin BİR KOD
        parçasıdır, tarixi qeydlərə istinad etmir. Onu saxlamaq yalnız
        söndürülmüş kodu diskdə qoymaq demək olardı.
        """
        now = self._clock.now()
        self._require(actor, now=now)

        plugin = self._load(plugin_id)
        self._registry.remove(plugin_id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PLUGIN_REMOVED",
            entity_type="plugin",
            entity_id=plugin_id,
            before_state={"name": plugin.name, "status": plugin.status.value},
        )
        _security_log.warning(
            "PLUGIN_REMOVED", extra={"actor_id": str(actor.id), "plugin": plugin.name}
        )

    # ------------------------------- köməkçilər ------------------------------ #

    def _load(self, plugin_id: str) -> InstalledPlugin:
        plugin = self._registry.get(plugin_id)
        if plugin is None:
            raise PluginManagementError(
                f"Plugin tapılmadı: {plugin_id}",
                user_message="Plugin tapılmadı — siyahını yeniləyin.",
            )
        return plugin

    def _require(self, actor: Employee, *, now: datetime) -> None:
        """`can_manage_plugins` + `Root` rolu (bölmə 1).

        Baza keçidindəki ilə eyni iki qatlı qoruma: plugin host prosesinə kod
        əlavə edir, yəni nəticələri bütün tenant-a yayılır.

        BAĞLAYICI QAT BİRİNCİSİDİR: `can_manage_plugins` `hardlock_level = 1`
        (`ROOT_ONLY`) daşıyır, yəni `CEO` onu nə rol dəsti, nə fərdi override
        ilə ala bilmir — nə domendə, nə DB trigger-ində.

        Rol şərti əvvəl «Root VƏ CEO» idi və bölmə 1-in ümumi mətnini
        güzgüləyirdi. O budaq DARALDILDI, çünki iki qat FƏRQLİ qərar verirdi
        (flag qatı «yalnız Root», rol qatı «Root+CEO») — CLAUDE.md §5 isə
        qaydanın hər iki yerdə EYNİ olmasını tələb edir. İmkan İTMİR: `CEO`
        bu flag-i onsuz da daşıya bilmədiyi üçün rol şərtinə heç vaxt `CEO`
        ilə çatılmırdı. Ətraflı əsaslandırma `db_switch._require_permission`
        docstring-indədir (eyni qərar, eyni səbəb).
        """
        if not actor.has_permission(MANAGE_PLUGINS_FLAG, now=now):
            _security_log.warning(
                "PLUGIN_MANAGEMENT_DENIED_FLAG", extra={"actor_id": str(actor.id)}
            )
            raise PluginManagementError(
                f"«{MANAGE_PLUGINS_FLAG}» səlahiyyəti yoxdur",
                user_message="Plugin-ləri idarə etmək səlahiyyətiniz yoxdur.",
            )
        if actor.position.effective_system_role is not SystemRole.ROOT:
            _security_log.warning(
                "PLUGIN_MANAGEMENT_DENIED_ROLE",
                extra={"actor_id": str(actor.id), "role": actor.position.code},
            )
            raise PluginManagementError(
                "Plugin idarəetməsi YALNIZ Root üçündür (bölmə 1)",
                user_message="Bu əməliyyat yalnız Root üçündür.",
                context={"role": actor.position.code},
            )


__all__ = [
    "MANAGE_PLUGINS_FLAG",
    "InstalledPlugin",
    "PluginManagementError",
    "PluginManagementUseCase",
    "PluginRegistry",
    "SignatureVerifier",
]
