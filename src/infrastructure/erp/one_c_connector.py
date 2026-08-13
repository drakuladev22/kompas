"""1C:Enterprise 8.3 OData klienti — Faza 3.10.

Spesifikasiya bölmə 7 hər server üçün `host`, `port`, `istifadəçi adı`,
`şifrə` sahələrini tələb edir. Protokol seçiminin əsaslandırması
`src/domain/value_objects/erp.py` modul başlığındadır (qısaca: OData 1C-nin
standart HTTP interfeysidir, COM Windows-a və lokal 1C quraşdırmasına bağlıdır,
birbaşa SQL isə 1C-nin biznes məntiqini yan keçir).

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
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote

import httpx

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.erp import (
    DEFAULT_PAGE_SIZE,
    ONE_C_ODATA_PATH,
    ConnectionTestResult,
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
    """Bir 1C serverinin bağlantı parametrləri.

    `password` BURADA AÇIQ MƏTNDİR — obyekt yalnız işlək yaddaşda mövcuddur,
    `erp_servers.password_encrypted` sütunundan AES-256-GCM ilə açılaraq
    qurulur (bax `servers.ErpServerRepository.credentials_for`).
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
        )

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}:{self.port}/{quote(self.infobase)}/{ONE_C_ODATA_PATH}"

    def __repr__(self) -> str:
        # Şifrə `repr`-də görünməməlidir: bu obyekt xəta konteksti və
        # debug çıxışı ilə log-a düşə bilər (SEC-013).
        return (
            f"OneCServerConfig(host={self.host}, port={self.port}, "
            f"infobase={self.infobase}, username={self.username})"
        )


class OneCConnector:
    """Bir 1C serveri üçün nazik OData örtüyü. Thread-safe (state saxlamır)."""

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

    def __enter__(self) -> OneCConnector:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

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
                elapsed_ms=_elapsed_ms(started),
            )

        return ConnectionTestResult(
            ok=True,
            message="Bağlantı uğurludur — 1C serveri cavab verir.",
            entity_verified=entity,
            elapsed_ms=_elapsed_ms(started),
        )

    @staticmethod
    def _failed_test(exc: Exception, started: float) -> ConnectionTestResult:
        user_message = getattr(exc, "user_message", "1C serveri ilə əlaqə qurulmadı.")
        return ConnectionTestResult(
            ok=False,
            message=user_message,
            detail=str(exc),
            elapsed_ms=_elapsed_ms(started),
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
        records = [record for record in parsed if not cursor.already_seen(record)]
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
                gross_amount=_to_decimal(row.get(mapping.amount_field), document_id),
                document_at=_to_datetime(row.get("Date"), document_id),
                seller_name=_optional_name(row, mapping.seller_name_field),
            )


class OneCConnectorFactory:
    """`ErpConnectorFactory` portunun tətbiqi.

    Credential-ların DEŞİFRƏSİ burada bitir: ondan yuxarı qatlar (use case,
    sync worker) `EncryptionService`-i heç vaxt görmür və şifrəni əlində
    saxlamır.
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

    def for_draft(self, draft: ErpServerDraft) -> OneCConnector:
        return OneCConnector(
            OneCServerConfig.from_draft(draft), transport=self._transport, limits=self._limits
        )

    def for_server(self, server_id: ErpServerId) -> OneCConnector:
        return OneCConnector(
            self._credentials(server_id), transport=self._transport, limits=self._limits
        )


# --------------------------------------------------------------------------- #
# Çevirmə köməkçiləri
# --------------------------------------------------------------------------- #


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _odata_datetime(moment: datetime) -> str:
    """1C OData v3 `datetime'...'` literalı — SAAT QURŞAĞI OLMADAN.

    1C sənəd tarixlərini server saatı ilə, qurşaq məlumatı olmadan saxlayır.
    UTC-yə çevrilmiş dəyər göndərsək sərhəd sənədləri sürüşərdi, ona görə
    kursor da server saatı ilə saxlanılır və olduğu kimi qaytarılır.
    """
    naive = moment.replace(tzinfo=None) if moment.tzinfo else moment
    return naive.strftime("%Y-%m-%dT%H:%M:%S")


def _to_decimal(raw: Any, document_id: str) -> Decimal:
    if raw is None:
        return Decimal("0")
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ErpProtocolError(
            "Satış məbləği rəqəm deyil",
            context={"document_id": document_id, "value": str(raw)[:50]},
        ) from exc


def _to_datetime(raw: Any, document_id: str) -> datetime:
    """1C sənəd vaxtını oxuyur.

    1C tarixləri qurşaq məlumatı OLMADAN qaytarır (server saatı). Layihədə
    naive `datetime` qadağandır (ruff DTZ) və müqayisə üçün də təhlükəlidir,
    ona görə dəyər UTC etiketi ilə daşınır. Bu, "vaxt UTC-dir" demək DEYİL —
    müqayisə həmişə EYNİ serverin öz dəyərləri arasında aparılır, ona görə
    etiketin özü nəticəyə təsir etmir. Eyni səbəbdən sorğuya geri yazılarkən
    etiket kəsilir (`_odata_datetime`).
    """
    if not raw:
        raise ErpProtocolError("1C sənədində tarix yoxdur", context={"document_id": document_id})
    text = str(raw)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErpProtocolError(
            "1C sənədinin tarixi oxunmadı",
            context={"document_id": document_id, "value": text[:50]},
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _optional_name(row: dict[str, Any], field_name: str | None) -> str | None:
    if not field_name:
        return None
    value = row.get(field_name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "OneCConnector",
    "OneCConnectorFactory",
    "OneCServerConfig",
]
