"""1C Bağlantı Sihirbazı — Faza 3.10 (spesifikasiya bölmə 7).

Axın (hər server üçün eynidir):

    1. `[+ Yeni Server Əlavə Et]` / `[Redaktə Et]` — host, port, istifadəçi,
       şifrə, baza adı daxil edilir.
    2. `[Bağlantını Test Et]` — YADDA SAXLAMAZDAN ƏVVƏL.
    3. Yalnız test uğurlu olduqda ayar aktivləşir; əvvəlki İŞLƏK
       konfiqurasiya avtomatik backup-a düşür.
    4. Bir kliklə geri qaytarma.
    5. Hər əməliyyat `audit_logs`-a yazılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ TEST NƏTİCƏSİ ÇAĞIRANDAN QƏBUL EDİLMİR
──────────────────────────────────────────────────────────────────────────────
`save_new(..., test_result=...)` imzası cazibədar görünür: GUI onsuz da testi
işlədib nəticəni əlində saxlayır. Lakin belə olsaydı, "test uğurlu olmalıdır"
qaydası GUI-nin düzgün davranışından ASILI olardı — bir ekran onu ötürməyi
unudarsa, işləməyən konfiqurasiya sükutla aktiv olardı və nasazlıq yalnız
növbəti sinxronizasiya dövründə, tamam başqa yerdə üzə çıxardı.

Ona görə use case testi ÖZÜ işlədir. GUI-nin ayrıca `test_connection()`
çağırışı isə istifadəçiyə dərhal rəy vermək üçündür — saxlama qərarına təsir
etmir.

──────────────────────────────────────────────────────────────────────────────
ADLANDIRMA
──────────────────────────────────────────────────────────────────────────────
İcazə flag-i `can_manage_erp_servers`-dir (`ERP_INFRA` qrupu). Kataloqda
`can_manage_erp_connections` adlı AYRI flag də var — o, baza/infrastruktur
bağlantısı sihirbazına aiddir (bölmə 7, «[İnfrastruktur Və Baza Ayarları]»),
1C server siyahısına yox. İkisini qarışdırmaq mağaza menecerinə 1C
credential-larına çıxış verə bilərdi.

──────────────────────────────────────────────────────────────────────────────
ÜÇ BAĞLANTI NÖVÜ — AXIN DƏYİŞMİR (1c.md)
──────────────────────────────────────────────────────────────────────────────
Sihirbazın addımları HTTP, COM və fayl mübadiləsi üçün EYNİDİR: doldur → test
et → saxla. Fərq yalnız `ErpServerDraft.connector_type` və `connector_config`
sahələrindədir və onları use case OXUMUR — testi konnektor fabriki seçir,
konkret səbəb mətnini isə konnektorun özü verir.

BURADA əlavə olunan İKİ tipə-bağlı qayda var və hər ikisinin səbəbi eynidir:
sətri DB-yə çatmazdan ƏVVƏL anlaşılan mesajla dayandırmaq.

    1. Sinxronizasiya dövrü verilməyibsə TİPİN defoltu tətbiq olunur; fayl
       mübadiləsində bu defolt ROOT parametrindən oxunur.
    2. Aktivləşdirmə qapısı tipə görə fərqlidir: HTTP/COM üçün baza adı
       (infobase), fayl mübadiləsi üçün isə QOVLUQ yolu məcburidir.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.erp import ConnectorType, ErpServerStatus
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        ErpConnectorFactory,
        ErpServerRegistry,
        SystemLimits,
    )
    from src.domain.value_objects.erp import (
        ConnectionTestResult,
        ErpServer,
        ErpServerDraft,
    )
    from src.domain.value_objects.identifiers import ErpServerId, StoreId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: 1C server siyahısını idarə etmə icazəsi (bax modul başlığı, ADLANDIRMA).
MANAGE_ERP_SERVERS_FLAG = "can_manage_erp_servers"


class ErpConnectionError(KompasOSError):
    """Sihirbaz əməliyyatı icra edilə bilmədi."""

    user_message = "Server konfiqurasiyası yadda saxlanmadı."


class ConnectionNotVerifiedError(ErpConnectionError):
    """Test uğursuz olduğu üçün konfiqurasiya aktivləşdirilmədi."""

    user_message = (
        "Bağlantı testi uğursuz oldu — konfiqurasiya yadda saxlanmadı. "
        "Parametrləri yoxlayıb yenidən cəhd edin."
    )


@dataclass(frozen=True)
class SaveOutcome:
    """Saxlama nəticəsi — sihirbazın son ekranı üçün."""

    server: ErpServer
    test: ConnectionTestResult
    backed_up_previous: bool = False


@dataclass(frozen=True)
class StoreServerLink:
    """`store_server_mapping` sətri — ekranın göstərdiyi forma."""

    store_id: StoreId
    store_name: str
    server_id: ErpServerId
    server_name: str
    one_c_store_code: str


@runtime_checkable
class StoreServerMappingRepository(Protocol):
    """`store_server_mapping` — mağaza ↔ 1C server bağlantısı (bölmə 7)."""

    def list_all(self) -> list[StoreServerLink]: ...

    def upsert(
        self, *, store_id: StoreId, server_id: ErpServerId, one_c_store_code: str
    ) -> None: ...

    def delete(self, *, store_id: StoreId, server_id: ErpServerId) -> None: ...


class ErpConnectionWizardUseCase:
    """Server əlavə etmə/redaktə/geri qaytarma axını."""

    def __init__(
        self,
        *,
        servers: ErpServerRegistry,
        connectors: ErpConnectorFactory,
        audit: AuditTrail,
        mappings: StoreServerMappingRepository | None = None,
        limits: SystemLimits | None = None,
    ) -> None:
        self._servers = servers
        self._connectors = connectors
        # AUDİT MƏCBURİ ASILILIQDIR, `None` DEYİL (`mappings`-dən fərqli
        # olaraq). Səbəb: modul başlığının 5-ci bəndi «hər əməliyyat
        # `audit_logs`-a yazılır» deyir və 1C serverinin host/kredensial
        # dəyişikliyi mağazanın bütün satış axınını başqa mənbəyə yönəldə
        # bilər. Onu istəyə bağlı etsəydik, bir qurma yerində unudulmaq
        # qaydanı sükutla ləğv edərdi — halbuki fayl jurnalı rotasiya ilə
        # itir, `audit_logs` isə qalır.
        self._audit = audit
        # `None` → xəritələmə ekranı qoşulmayıb (məs. testlərdə). Server
        # idarəetməsi ondan ASILI DEYİL, ona görə məcburi arqument deyil.
        self._mappings = mappings
        # `None` → ROOT dəyəri oxuna bilmir və tipin domen defoltu işləyir
        # (`ConnectorType.default_sync_interval_seconds`). Limit oxusu MƏCBURİ
        # ola bilməz: server əlavə etmək `system_limits` sətrinin mövcud
        # olmasından asılı olsaydı, bir seed nasazlığı bütün sihirbazı
        # bağlayardı.
        self._limits = limits

    # -------------------------------- test ----------------------------------- #

    def test_connection(
        self, *, actor: Employee, draft: ErpServerDraft, now: datetime
    ) -> ConnectionTestResult:
        """`[Bağlantını Test Et]` — heç nə yazmır."""
        self._assert_may_manage(actor, now=now, operation="TEST")
        return self._run_test(draft)

    # ------------------------------- saxlama --------------------------------- #

    def save_new(self, *, actor: Employee, draft: ErpServerDraft, now: datetime) -> SaveOutcome:
        """Yeni server — YALNIZ test uğurlu olduqda aktiv yaradılır."""
        self._assert_may_manage(actor, now=now, operation="CREATE")
        draft = self._with_resolved_interval(draft, tenant_id=actor.tenant_id)
        test = self._require_successful_test(draft, server_id=None)
        server = self._servers.create(draft, created_by=actor.id, activate=True)
        self._audit.record(
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            action="ERP_SERVER_ADDED",
            entity_type="erp_servers",
            entity_id=server.id,
            after_state=_config_state(draft),
        )
        _audit_log.info(
            "ERP_WIZARD_SERVER_ADDED",
            extra={
                "server_id": str(server.id),
                "server_name": server.server_name,
                "actor_id": str(actor.id),
            },
        )
        return SaveOutcome(server=server, test=test)

    def save_existing(
        self,
        *,
        actor: Employee,
        server_id: ErpServerId,
        draft: ErpServerDraft,
        now: datetime,
    ) -> SaveOutcome:
        """Mövcud serverin konfiqurasiyasını əvəz edir (əvvəlki backup-a düşür)."""
        self._assert_may_manage(actor, now=now, operation="UPDATE")
        existing = self._servers.require(server_id)
        draft = self._with_resolved_interval(draft, tenant_id=actor.tenant_id)
        test = self._require_successful_test(draft, server_id=server_id)
        server = self._servers.update(server_id, draft, updated_by=actor.id, backup_previous=True)
        self._audit.record(
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            action="ERP_SERVER_UPDATED",
            entity_type="erp_servers",
            entity_id=server_id,
            before_state=_server_state(existing),
            after_state=_config_state(draft),
        )
        _audit_log.info(
            "ERP_WIZARD_SERVER_UPDATED",
            extra={
                "server_id": str(server_id),
                "actor_id": str(actor.id),
                "host_changed": existing.host != draft.host,
            },
        )
        return SaveOutcome(
            server=server, test=test, backed_up_previous=existing.has_verified_config
        )

    # ------------------------------ geri qaytarma ----------------------------- #

    def rollback(self, *, actor: Employee, server_id: ErpServerId, now: datetime) -> ErpServer:
        """«Bir kliklə geri qaytar» — sonuncu İŞLƏK konfiqurasiya bərpa olunur.

        Bərpadan sonra test QƏSDƏN tələb olunmur: bu konfiqurasiya artıq bir
        dəfə uğurla işləyib və geri qaytarma məhz "indi heç nə işləmir"
        vəziyyətində istifadə olunur. Test tələb etsəydik, 1C serveri
        müvəqqəti sönmüş olduqda geri qaytarma da mümkün olmazdı — yəni alət
        ən çox lazım olan anda işləməzdi.
        """
        self._assert_may_manage(actor, now=now, operation="ROLLBACK")
        restored = self._servers.rollback(server_id, actor_id=actor.id)
        self._audit.record(
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            action="ERP_SERVER_ROLLED_BACK",
            entity_type="erp_servers",
            entity_id=server_id,
            after_state=_server_state(restored),
            # Geri qaytarma TEST TƏLƏB ETMİR (bax metodun docstring-i), yəni
            # audit oxuyan adam "niyə yoxlanmadan aktivləşdi" sualını verəcək
            # — səbəb sətrin ÖZÜNDƏ yazılır, sənəddə deyil.
            reason="Sonuncu işlək konfiqurasiya bərpa edildi (test tələb olunmur)",
        )
        _audit_log.warning(
            "ERP_WIZARD_ROLLED_BACK",
            extra={"server_id": str(server_id), "actor_id": str(actor.id)},
        )
        return restored

    # ------------------------------- status ---------------------------------- #

    def set_status(
        self,
        *,
        actor: Employee,
        server_id: ErpServerId,
        status: ErpServerStatus,
        now: datetime,
        reason: str | None = None,
    ) -> None:
        """Aktivləşdirir/deaktiv edir — sətir SİLİNMİR (tarixi satışlar qalır)."""
        self._assert_may_manage(actor, now=now, operation="STATUS")
        # Sətir BİR DƏFƏ oxunur və iki məqsədə xidmət edir: `infobase` qapısı
        # və audit-in `before_state`-i. Statusun ƏVVƏLKİ dəyəri olmadan audit
        # sətri "nə dəyişdi" sualına cavab verməzdi — yalnız "nə oldu"ya.
        previous = self._servers.require(server_id)
        if status is ErpServerStatus.ACTIVE:
            self._assert_activatable(previous)
        self._servers.set_status(server_id, status, changed_by=actor.id, reason=reason)
        # Deaktivləşdirmə sətri SİLMİR, lakin həmin serverdən gələn satış
        # axınını DAYANDIRIR — yəni "hesabatda rəqəmlər niyə azaldı" sualının
        # cavabı məhz burada qalmalıdır.
        self._audit.record(
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            action="ERP_SERVER_STATUS_CHANGED",
            entity_type="erp_servers",
            entity_id=server_id,
            before_state={"status": previous.status.value},
            after_state={"status": status.value},
            reason=reason,
        )
        _audit_log.info(
            "ERP_WIZARD_STATUS_CHANGED",
            extra={
                "server_id": str(server_id),
                "actor_id": str(actor.id),
                "status": status.value,
            },
        )

    # ------------------- Mağaza ↔ Server xəritələməsi (bölmə 7) --------------- #

    def mappings_for(self, *, actor: Employee, now: datetime) -> list[StoreServerLink]:
        """Cari xəritələmə siyahısı — «hansı mağaza hansı serverdən oxuyur».

        Bu xəritə 1C composite matching-in BİRİNCİ addımıdır
        (`(server_id, one_c_store_code) → store_id`, bax `erp/matching.py`).
        Boş qalsa, gələn hər sənəd `UNASSIGNED` olur və növbəyə düşür — yəni
        səhv konfiqurasiya sükutla deyil, şübhəli satışlar növbəsində görünür.
        """
        self._assert_may_manage(actor, now=now, operation="MAPPING_VIEW")
        if self._mappings is None:
            return []
        return self._mappings.list_all()

    def map_store(
        self,
        *,
        actor: Employee,
        server_id: ErpServerId,
        store_id: StoreId,
        one_c_store_code: str,
        now: datetime,
    ) -> None:
        """Mağazanı serverə bağlayır (və ya 1C kodunu yeniləyir)."""
        self._assert_may_manage(actor, now=now, operation="MAPPING_SAVE")
        code = " ".join(one_c_store_code.split())
        if not code:
            raise ErpConnectionError(
                "1C mağaza kodu boş ola bilməz",
                user_message="1C-dəki mağaza kodunu daxil edin.",
                context={"store_id": str(store_id)},
            )
        if self._mappings is None:
            raise ErpConnectionError(
                "Xəritələmə repo-su qoşulmayıb",
                user_message="Bu funksiya hazırda əlçatan deyil.",
            )

        self._mappings.upsert(store_id=store_id, server_id=server_id, one_c_store_code=code)

    def unmap_store(
        self,
        *,
        actor: Employee,
        server_id: ErpServerId,
        store_id: StoreId,
        now: datetime,
    ) -> None:
        """Bağlantını silir — TARİXİ satışlar toxunulmaz qalır.

        `sales_transactions` sətirləri öz `store_id`-sini artıq saxlayır, ona
        görə xəritənin silinməsi keçmiş hesabatları dəyişmir; yalnız BUNDAN
        SONRAKI sənədlər uyğunlaşmayacaq.
        """
        self._assert_may_manage(actor, now=now, operation="MAPPING_DELETE")
        if self._mappings is not None:
            self._mappings.delete(store_id=store_id, server_id=server_id)

    # ------------------------------ köməkçilər -------------------------------- #

    def _assert_activatable(self, server: ErpServer) -> None:
        """Aktivləşdirmə qapısı — TİPƏ GÖRƏ (1c.md).

        DB-də `chk_erp_active_requires_config` eyni qaydanı saxlayır
        (migrations/050); burada isə istifadəçi anlaşılan mesaj alır. Qayda
        İKİ yerdədir, çünki ekranı yan keçən skript də ona tabe olmalıdır
        (CLAUDE.md bölmə 5 naxışı).

        Fayl mübadiləsində `infobase` MƏNASIZDIR — 1C bazası ilə birbaşa
        əlaqə yoxdur. Orada məcburi olan mübadilə qovluğudur (`host`). Köhnə
        qaydanı olduğu kimi saxlasaydıq, düzgün qurulmuş fayl serveri heç vaxt
        aktivləşməzdi.
        """
        if server.connector_type.requires_infobase:
            if server.infobase.strip():
                return
            raise ErpConnectionError(
                "Baza adı (infobase) boş olan server aktivləşdirilə bilməz",
                user_message=(
                    "Serveri aktivləşdirmək üçün əvvəlcə baza adını (infobase) "
                    "daxil edib bağlantını test edin."
                ),
                context={
                    "server_id": str(server.id),
                    "connector_type": server.connector_type.value,
                },
            )

        if server.host.strip():
            return
        raise ErpConnectionError(
            "Mübadilə qovluğu boş olan server aktivləşdirilə bilməz",
            user_message=(
                "Serveri aktivləşdirmək üçün əvvəlcə mübadilə qovluğunun yolunu "
                "daxil edib bağlantını test edin."
            ),
            context={"server_id": str(server.id), "connector_type": server.connector_type.value},
        )

    def _with_resolved_interval(
        self, draft: ErpServerDraft, *, tenant_id: TenantId
    ) -> ErpServerDraft:
        """Dövr göstərilməyibsə tipin defoltunu yazır.

        FAYL MÜBADİLƏSİ ROOT-DAN OXUNUR: "gecədə bir dəfə" bir siyasətdir və
        müəssisə onu dəyişə bilməlidir (`ERP_FILE_EXCHANGE_SYNC_INTERVAL_
        SECONDS`). HTTP/COM üçün isə oxu APARILMIR — onların dövrü hər server
        üçün ayrıca saxlanılır və sistem səviyyəsində bir dəyəri yoxdur.

        Dəyəri həmişə açıq şəkildə yazırıq (draft `None` saxlamır), çünki
        `erp_servers.sync_interval_seconds` `NOT NULL`-dur və sətrin oxunuşu
        (`v_erp_server_health`) həmin ədədi STALE həddi kimi işlədir.
        """
        if draft.sync_interval_seconds is not None:
            return draft
        if draft.connector_type is not ConnectorType.FILE_EXCHANGE or self._limits is None:
            return replace(draft, sync_interval_seconds=draft.effective_sync_interval_seconds)

        seconds = self._limits.get_int(
            tenant_id,
            SystemLimitKey.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS.value,
            draft.connector_type.default_sync_interval_seconds,
        )
        return replace(draft, sync_interval_seconds=seconds)

    def _require_successful_test(
        self, draft: ErpServerDraft, *, server_id: ErpServerId | None
    ) -> ConnectionTestResult:
        test = self._run_test(draft)
        if not test.ok:
            _security_log.info(
                "ERP_CONFIG_REJECTED",
                extra={
                    "server_id": str(server_id) if server_id else None,
                    "host": draft.host,
                    "detail": test.detail[:200],
                },
            )
            raise ConnectionNotVerifiedError(
                f"Bağlantı testi uğursuz: {test.detail or test.message}",
                user_message=test.message,
                context={"host": draft.host, "port": draft.port},
            )
        return test

    def _run_test(self, draft: ErpServerDraft) -> ConnectionTestResult:
        connector = self._connectors.for_draft(draft)
        try:
            return connector.test_connection()
        finally:
            connector.close()

    def _assert_may_manage(self, actor: Employee, *, now: datetime, operation: str) -> None:
        if not actor.has_permission(MANAGE_ERP_SERVERS_FLAG, now=now):
            _security_log.warning(
                "ERP_SERVER_MANAGEMENT_DENIED",
                extra={
                    "actor_id": str(actor.id),
                    "role": actor.position.code,
                    "operation": operation,
                    "reason": "MISSING_FLAG",
                },
            )
            raise ErpConnectionError(
                f"`{MANAGE_ERP_SERVERS_FLAG}` icazəsi yoxdur",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id), "operation": operation},
            )


# --------------------------------------------------------------------------- #
# Audit vəziyyəti — ŞİFRƏ HEÇ VAXT DAXİL DEYİL
# --------------------------------------------------------------------------- #
#
# Görünüşün ÖZÜ artıq domendə həll olunub: `ErpServerDraft.auditable()` və
# `ErpServer.auditable()` şifrəni QƏSDƏN kənarda saxlayır (SEC-013). Burada
# ikinci nüsxə qurmaq həmin qərarı bir gün fərqləndirərdi, ona görə mövcud
# metod işlədilir və üzərinə YALNIZ audit-ə xas iki sahə əlavə olunur.
#
# `credentials_supplied`: şifrənin DƏYƏRİ yox, dəyişdirilib-dəyişdirilmədiyi
# faktı. Host eyni qalıb yalnız şifrə dəyişəndə audit sətri əks halda
# "heç nə dəyişməyib" kimi görünərdi.


def _config_state(draft: ErpServerDraft) -> dict[str, object]:
    """Sihirbazdan gələn konfiqurasiyanın audit təsviri."""
    state: dict[str, object] = dict(draft.auditable())
    state["credentials_supplied"] = bool(draft.password)
    return state


def _server_state(server: ErpServer) -> dict[str, object]:
    """Mövcud sətrin audit təsviri — `before_state` üçün."""
    state: dict[str, object] = dict(server.auditable())
    state["status"] = server.status.value
    return state


__all__ = [
    "MANAGE_ERP_SERVERS_FLAG",
    "ConnectionNotVerifiedError",
    "ErpConnectionError",
    "ErpConnectionWizardUseCase",
    "SaveOutcome",
    "StoreServerLink",
    "StoreServerMappingRepository",
]
