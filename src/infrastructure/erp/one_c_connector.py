"""1C:Enterprise 8.3 OData (HTTP) klienti və konnektor fabriki — Faza 3.10.

Spesifikasiya bölmə 7 hər server üçün `host`, `port`, `istifadəçi adı`,
`şifrə` sahələrini tələb edir. Protokol seçiminin əsaslandırması
`src/domain/value_objects/erp.py` modul başlığındadır (qısaca: OData 1C-nin
standart HTTP interfeysidir, COM Windows-a və lokal 1C quraşdırmasına bağlıdır,
birbaşa SQL isə 1C-nin biznes məntiqini yan keçir).

──────────────────────────────────────────────────────────────────────────────
ADLANDIRMA: `OneCConnector` → `OneCHttpConnector`
──────────────────────────────────────────────────────────────────────────────
1c.md üç konnektor tələb edir, yəni "1C konnektoru" adı artıq bir tipi
göstərmir. Sinif ADI dəqiqləşdirildi, MƏNTİQİ isə olduğu kimi qaldı — bir
sətir də silinmədi, yalnız ortaq hissə `connector_base`-ə çıxarıldı.

`OneCConnector` adı ALİAS kimi saxlanılır: onu dərhal silsəydik, mövcud
testlər və üçüncü tərəf plugin-ləri (Plugin API `ERP_TRANSFORM` qabiliyyəti)
sükutla qırılardı, halbuki davranış heç dəyişməyib.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAHƏ ADLARI KONFİQURASİYA EDİLİR
──────────────────────────────────────────────────────────────────────────────
OData-nın ÖZÜ standartdır, lakin sənəd və rekvizit adları 1C
KONFİQURASİYASINDAN asılıdır: "Розница", "Управление Торговлей" və fərdi
konfiqurasiyalarda satış sənədi fərqli adlanır. Müştəri dörd brendlə
(Bellona, İstikbal, Yataş, Enza Home) işləyir və hər birinin öz 1C bazası ola
bilər.

Adları koda bərk-yazsaydıq, hər yeni baza üçün müştəri BİZƏ müraciət etməli
olardı — bu, bölmə 7-nin "hazırlayıcı ilə əlaqə yalnız yeni funksionallıq
üçün lazımdır" prinsipinin birbaşa pozulmasıdır. Ona görə adlar server
qeydində saxlanılır (`document_mapping_json`), defolt dəyərlər isə tipik
konfiqurasiyaya uyğun gəlir və Bağlantı Sihirbazında yoxlanıla bilir.

`Ref_Key` və `Date` istisnadır — onlar 1C OData-nın PLATFORMA səviyyəli
sahələridir, konfiqurasiyadan asılı deyil.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YALNIZ `Posted = true`
──────────────────────────────────────────────────────────────────────────────
1C-də sənəd yazıla bilər, amma "keçirilmiş" (posted) olmaya bilər — yəni
uçota düşməyib, hələ layihədir. Keçirilməmiş sənədə görə işçiyə satış xalı
vermək, sonra sənəd silindikdə isə xalı geri almaq lazım gələrdi. Xal
etirazı mexanizmi (bölmə 6) bunun üçün nəzərdə tutulmayıb — filtr mənbədə
tətbiq olunur.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote

import httpx

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.erp import (
    DEFAULT_PAGE_SIZE,
    ONE_C_ODATA_PATH,
    ConnectionTestResult,
    ConnectorConfig,
    ConnectorType,
    ErpAuthenticationError,
    ErpConnectionError,
    ErpProtocolError,
    OneCDocumentMapping,
    OneCSaleRecord,
)
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_float,
    fallback_int,
)
from src.infrastructure.erp.com_connector import OneCComConnector
from src.infrastructure.erp.connector_base import (
    OneCConnectorBase,
    elapsed_ms,
    optional_text,
    to_datetime,
    to_decimal,
)
from src.infrastructure.erp.file_exchange_connector import OneCFileExchangeConnector
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from src.domain.value_objects.erp import ErpServerDraft, SyncCursor
    from src.domain.value_objects.identifiers import ErpServerId

_log = get_logger(__name__)

#: HƏR İKİSİ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`ERP_REQUEST_TIMEOUT_SECONDS`, `ERP_MAX_RETRIES`; seed: migrations/032).
#: 1C serveri müəssisənin öz binasında da ola bilər (millisaniyələr), VPN
#: arxasında da (saniyələr) — sabit 30 saniyə ikinci halda dövrü uzadır,
#: birinci halda isə nasazlığın aşkarlanmasını gecikdirir.
FALLBACK_TIMEOUT_SECONDS: Final[float] = fallback_float(SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS)
#: 1C serveri yüklü olduqda 503 qaytarır; şəbəkə proxy-ləri 502/504 verir.
#: SİYAHININ ÖZÜ KÖÇÜRÜLMÜR: bunlar HTTP standart kodlarıdır, siyasət deyil.
RETRY_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
FALLBACK_MAX_RETRIES: Final[int] = fallback_int(SystemLimitKey.ERP_MAX_RETRIES)
HTTP_UNAUTHORIZED: Final[int] = 401
HTTP_FORBIDDEN: Final[int] = 403


@dataclass(frozen=True)
class OneCServerConfig:
    """Bir 1C mənbəyinin HƏLL EDİLMİŞ (deşifrə olunmuş) bağlantı parametrləri.

    `password` BURADA AÇIQ MƏTNDİR — obyekt yalnız işlək yaddaşda mövcuddur,
    `erp_servers.password_encrypted` sütunundan AES-256-GCM ilə açılaraq
    qurulur (bax `servers.ErpServerRepository.credentials_for`).

    ──────────────────────────────────────────────────────────────────────
    NİYƏ TİP-NEYTRALDIR, HALBUKİ SAHƏ ADLARI HTTP-DƏNDİR
    ──────────────────────────────────────────────────────────────────────
    1c.md üç konnektor tələb edir, lakin `ErpConnectorFactory` portu TƏK bir
    "credential həlledici" ilə işləyir (`Callable[[ErpServerId],
    OneCServerConfig]`). Hər tip üçün ayrıca konfiqurasiya sinfi qursaydıq,
    fabrikin imzası `Union` olardı və deşifrə məntiqi üç yerə bölünərdi —
    halbuki sirr HƏMİŞƏ eyni iki sütundan gəlir.

    Ona görə sütunlar OLDUĞU KİMİ daşınır və mənası tipə görə oxunur:

        HTTP           `host`+`port` = şəbəkə ünvanı, `infobase` = publikasiya
        COM            `host` = 1C server adı / baza qovluğu, `port` = 0
        FILE_EXCHANGE  `host` = mübadilə qovluğu, `port` = 0, `infobase` boş

    Tipə XAS qalan parametrlər `connector_config` sözlüyündədir.
    """

    host: str
    port: int
    username: str
    password: str
    #: 1C infobase (publikasiya) adı — OData yolunun tərkib hissəsi.
    infobase: str
    use_https: bool = False
    mapping: OneCDocumentMapping = field(default_factory=OneCDocumentMapping)
    #: `None` = taymaut ROOT-dan (`ERP_REQUEST_TIMEOUT_SECONDS`) oxunur.
    #: Açıq ədəd verilərsə O QALIR — çağıran onu bilərəkdən təyin edib.
    timeout_seconds: float | None = None
    connector_type: ConnectorType = ConnectorType.HTTP
    connector_config: ConnectorConfig = field(default_factory=ConnectorConfig)

    @classmethod
    def from_draft(cls, draft: ErpServerDraft) -> OneCServerConfig:
        """Sihirbazdakı (hələ saxlanmamış) konfiqurasiyadan qurur."""
        return cls(
            host=draft.host,
            port=draft.port,
            username=draft.username,
            password=draft.password,
            infobase=draft.infobase,
            use_https=draft.use_https,
            mapping=draft.mapping,
            connector_type=draft.connector_type,
            connector_config=draft.connector_config,
        )

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}:{self.port}/{quote(self.infobase)}/{ONE_C_ODATA_PATH}"

    def __repr__(self) -> str:
        # Şifrə `repr`-də görünməməlidir: bu obyekt xəta konteksti və
        # debug çıxışı ilə log-a düşə bilər (SEC-013). `connector_config`
        # öz `__repr__`-ində sirr açarlarını onsuz da maskalayır.
        return (
            f"OneCServerConfig(type={self.connector_type.value}, host={self.host}, "
            f"port={self.port}, infobase={self.infobase}, username={self.username}, "
            f"config={self.connector_config!r})"
        )


class OneCHttpConnector(OneCConnectorBase):
    """Bir 1C serveri üçün nazik OData örtüyü. Thread-safe (state saxlamır)."""

    connector_type = ConnectorType.HTTP

    def __init__(
        self,
        config: OneCServerConfig,
        *,
        transport: httpx.Client | None = None,
        sleep: Any = time.sleep,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.

        Taymaut BURADA — `httpx.Client` qurularkən — həll olunur, çünki həmin
        klient dəyəri sonradan qəbul etmir. Bu, ROOT nəzarətini itirmir:
        konnektor QISA ÖMÜRLÜDÜR (`OneCConnectorFactory` hər sinxronizasiya
        dövründə yenisini qurur), yəni Root-un dəyişikliyi növbəti dövrdə
        qüvvəyə minir. Təkrar cəhd sayı isə hər sorğuda oxunur.
        """
        self._config = config
        self._limits = limits or InfrastructureLimits()
        self._timeout = (
            config.timeout_seconds
            if config.timeout_seconds is not None
            else self._limits.float_of(SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS)
        )
        self._http = transport or httpx.Client(
            timeout=self._timeout,
            auth=httpx.BasicAuth(config.username, config.password),
            headers={"Accept": "application/json"},
        )
        self._owns_transport = transport is None
        self._sleep = sleep

    def _max_retries(self) -> int:
        """Təkrar cəhd sayı — HƏR SORĞUDA oxunur."""
        return self._limits.int_of(SystemLimitKey.ERP_MAX_RETRIES)

    def close(self) -> None:
        if self._owns_transport:
            self._http.close()

    @property
    def config(self) -> OneCServerConfig:
        return self._config

    # ------------------------------- sorğu ----------------------------------- #

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._config.base_url}/{path}" if path else self._config.base_url
        last_error = ""

        max_retries = self._max_retries()
        for attempt in range(max_retries):
            try:
                response = self._http.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise ErpConnectionError(
                    f"1C serveri vaxtında cavab vermədi ({self._config.host})",
                    context={"host": self._config.host, "timeout": self._timeout},
                ) from exc
            except httpx.HTTPError as exc:
                raise ErpConnectionError(
                    f"1C serverinə qoşulmaq mümkün olmadı ({self._config.host})",
                    context={"host": self._config.host, "error": str(exc)},
                ) from exc

            if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                # Təkrar cəhd MƏNASIZDIR — credential dəyişmir. Üstəlik 1C
                # ardıcıl uğursuz girişlərdə istifadəçini bloklaya bilər.
                raise ErpAuthenticationError(
                    f"1C autentifikasiyası rədd edildi (HTTP {response.status_code})",
                    context={"host": self._config.host, "username": self._config.username},
                )

            if response.status_code in RETRY_STATUS:
                delay = 2**attempt
                last_error = f"HTTP {response.status_code}"
                _log.warning(
                    "ERP_REQUEST_RETRY",
                    extra={
                        "host": self._config.host,
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                        "delay_seconds": delay,
                    },
                )
                self._sleep(delay)
                continue

            if response.status_code >= httpx.codes.BAD_REQUEST:
                raise ErpProtocolError(
                    f"1C xətası (HTTP {response.status_code})",
                    context={
                        "host": self._config.host,
                        "status_code": response.status_code,
                        "body": response.text[:200],
                    },
                )

            return self._parse_json(response)

        raise ErpConnectionError(
            f"1C serveri cavab vermədi ({last_error})",
            context={"host": self._config.host, "attempts": max_retries},
        )

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
        """Cavabı JSON kimi oxuyur; HTML xəta səhifəsini sükutla ötürmür."""
        try:
            payload = response.json()
        except ValueError as exc:
            # Ən çox rast gəlinən hal: infobase adı səhvdir və veb-server
            # 200 statusu ilə HTML səhifə qaytarır.
            raise ErpProtocolError(
                "1C cavabı JSON deyil — baza adı (infobase) səhv ola bilər",
                context={"host": self._config.host, "body": response.text[:200]},
            ) from exc
        if not isinstance(payload, dict):
            raise ErpProtocolError(
                "1C cavabı gözlənilən obyekt formatında deyil",
                context={"host": self._config.host, "type": type(payload).__name__},
            )
        return payload

    # ------------------------------- test ------------------------------------ #

    def test_connection(self) -> ConnectionTestResult:
        """Host + autentifikasiya + infobase + sənəd adını BİR addımda yoxlayır.

        Sihirbaz "yadda saxlamazdan ƏVVƏL" bunu çağırır (bölmə 7): yalnız
        uğurlu test edilmiş konfiqurasiya aktivləşir.
        """
        started = time.monotonic()
        entity = self._config.mapping.entity_name
        try:
            payload = self._request(
                entity,
                {"$top": 1, "$format": "json", "$select": self._config.mapping.selected_fields()},
            )
        except ErpAuthenticationError as exc:
            return self._failed_test(exc, started)
        except ErpConnectionError as exc:
            return self._failed_test(exc, started)
        except ErpProtocolError as exc:
            return self._failed_test(exc, started)

        if "value" not in payload:
            return ConnectionTestResult(
                ok=False,
                message=(
                    f"Server cavab verdi, lakin «{entity}» sənəd növü tapılmadı. "
                    "Sənəd adını yoxlayın."
                ),
                detail=f"cavabda `value` sahəsi yoxdur: {sorted(payload)[:5]}",
                elapsed_ms=elapsed_ms(started),
            )

        return ConnectionTestResult(
            ok=True,
            message="Bağlantı uğurludur — 1C serveri cavab verir.",
            entity_verified=entity,
            elapsed_ms=elapsed_ms(started),
        )

    # ------------------------------ satışlar ---------------------------------- #

    def fetch_sales(
        self, cursor: SyncCursor, *, page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[OneCSaleRecord]:
        """Kursordan sonrakı KEÇİRİLMİŞ satış sənədlərini gətirir.

        Sərhəd sənədlərinin itməməsi üçün filtr `ge` (>=) istifadə edir —
        təkrar gələn sənəd DB-də `UNIQUE (server_id, one_c_document_id)`
        ilə süzülür (bax `SyncCursor` docstring-i).
        """
        mapping = self._config.mapping
        params: dict[str, Any] = {
            "$format": "json",
            "$top": page_size,
            "$orderby": "Date asc",
            "$select": mapping.selected_fields(),
        }
        filters = ["Posted eq true"]
        if cursor.last_document_at is not None:
            filters.append(f"Date ge datetime'{_odata_datetime(cursor.last_document_at)}'")
        params["$filter"] = " and ".join(filters)

        payload = self._request(mapping.entity_name, params)
        rows = payload.get("value")
        if not isinstance(rows, list):
            raise ErpProtocolError(
                "1C cavabında `value` massivi yoxdur",
                context={"host": self._config.host, "entity": mapping.entity_name},
            )

        parsed = list(self._to_records(rows))
        # Sərhəd saniyəsində artıq emal olunmuş sənədlər burada süzülür —
        # `>=` filtrinin qaçılmaz təkrarı (bax `SyncCursor` docstring-i).
        records = self._new_records(parsed, cursor)
        _log.info(
            "ERP_SALES_FETCHED",
            extra={
                "host": self._config.host,
                "infobase": self._config.infobase,
                "returned": len(rows),
                "new": len(records),
                "boundary_skipped": len(parsed) - len(records),
                "since": cursor.last_document_at.isoformat() if cursor.last_document_at else None,
            },
        )
        return records

    def _to_records(self, rows: Iterable[dict[str, Any]]) -> Iterable[OneCSaleRecord]:
        mapping = self._config.mapping
        for row in rows:
            document_id = str(row.get("Ref_Key", "")).strip()
            if not document_id:
                # Sənəd ID-siz gəlirsə onu emal etmək təhlükəlidir: təkrar
                # qorunması işləməzdi. Atlanır, lakin GÖRÜNƏN şəkildə.
                _log.warning(
                    "ERP_DOCUMENT_WITHOUT_ID",
                    extra={"host": self._config.host, "entity": mapping.entity_name},
                )
                continue
            yield OneCSaleRecord(
                document_id=document_id,
                seller_id=str(row.get(mapping.seller_field, "") or "").strip(),
                store_code=str(row.get(mapping.store_field, "") or "").strip(),
                gross_amount=to_decimal(row.get(mapping.amount_field), document_id),
                document_at=to_datetime(row.get("Date"), document_id),
                seller_name=optional_text(row, mapping.seller_name_field),
            )


#: `OneCConnector` — ADI DƏYİŞDİ, məntiqi yox (bax modul başlığı).
#: Alias mövcud idxalları qırmamaq üçün saxlanılır.
OneCConnector = OneCHttpConnector


class OneCConnectorFactory:
    """`ErpConnectorFactory` portunun tətbiqi — TİPƏ GÖRƏ konnektor seçir.

    Credential-ların DEŞİFRƏSİ burada bitir: ondan yuxarı qatlar (use case,
    sync worker) `EncryptionService`-i heç vaxt görmür və şifrəni əlində
    saxlamır.

    ──────────────────────────────────────────────────────────────────────
    SEÇİM NİYƏ MƏHZ BURADADIR
    ──────────────────────────────────────────────────────────────────────
    1c.md: *"yuxarı səviyyəli kod HANSI connector işlədiyini BİLMİR/BİLMƏLİ
    DEYİL"*. `SalesSyncService` yalnız `for_server(...)` çağırır və qaytarılan
    obyektin üç metodunu tanıyır. Seçim məntiqi burada, TƏK bir yerdə qalır:
    onu sync worker-ə qoysaydıq, sihirbazın `for_draft` yolu ilə iki fərqli
    seçim qaydası yaranardı və biri gec-tez digərindən ayrılardı.

    `transport` YALNIZ HTTP konnektoruna ötürülür — COM və fayl mübadiləsində
    `httpx.Client`-in mənası yoxdur. Testlər onları öz sahtələri ilə
    (`dispatcher`, müvəqqəti qovluq) əvəz edir.
    """

    def __init__(
        self,
        credentials: Callable[[ErpServerId], OneCServerConfig],
        *,
        transport: httpx.Client | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._credentials = credentials
        self._transport = transport
        self._limits = limits or InfrastructureLimits()

    def for_draft(self, draft: ErpServerDraft) -> OneCConnectorBase:
        return self._build(OneCServerConfig.from_draft(draft))

    def for_server(self, server_id: ErpServerId) -> OneCConnectorBase:
        return self._build(self._credentials(server_id))

    def _build(self, config: OneCServerConfig) -> OneCConnectorBase:
        """`connector_type` → konkret sinif.

        NAMƏLUM TİP OLA BİLMƏZ: `ConnectorType` qapalı enum-dur və DB CHECK-i
        eyni üç dəyəri saxlayır; oxuma anında naməlum mətn `HTTP`-yə düşür
        (`ConnectorType.parse`, geriyə uyğunluq). Ona görə burada `else`
        budağı HTTP-dir və "naməlum tip" istisnası lazım deyil.
        """
        if config.connector_type is ConnectorType.COM:
            return OneCComConnector(config)
        if config.connector_type is ConnectorType.FILE_EXCHANGE:
            return OneCFileExchangeConnector(config)
        return OneCHttpConnector(config, transport=self._transport, limits=self._limits)


# --------------------------------------------------------------------------- #
# Çevirmə köməkçiləri
# --------------------------------------------------------------------------- #
#
# `_elapsed_ms`, `_to_decimal`, `_to_datetime`, `_optional_name` BU FAYLDAN
# `connector_base`-ə KÖÇDÜ (silinmədi): eyni çevirmələr COM və fayl
# konnektorlarında da lazımdır və üç nüsxə saxlamaq onların bir gün
# ayrılmasını qaçılmaz edərdi. Aşağıdakı `_odata_datetime` isə OData-ya XASdır
# və qəsdən burada qalır.


def _odata_datetime(moment: datetime) -> str:
    """1C OData v3 `datetime'...'` literalı — SAAT QURŞAĞI OLMADAN.

    1C sənəd tarixlərini server saatı ilə, qurşaq məlumatı olmadan saxlayır.
    UTC-yə çevrilmiş dəyər göndərsək sərhəd sənədləri sürüşərdi, ona görə
    kursor da server saatı ilə saxlanılır və olduğu kimi qaytarılır.
    """
    naive = moment.replace(tzinfo=None) if moment.tzinfo else moment
    return naive.strftime("%Y-%m-%dT%H:%M:%S")


__all__ = [
    "OneCConnector",
    "OneCConnectorFactory",
    "OneCHttpConnector",
    "OneCServerConfig",
]
