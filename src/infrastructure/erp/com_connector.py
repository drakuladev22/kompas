"""1C:Enterprise COM/OLE konnektoru (`V83.COMConnector`) — 1c.md.

Bağlantı növlərindən İKİNCİSİ: 1C platforması həmin kompüterdə quraşdırılıbsa,
veb-servis yayımlamadan birbaşa `comcntr.dll` üzərindən işləmək mümkündür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU YOL VAR — HALBUKİ `value_objects/erp.py` ONU RƏDD ETMİŞDİ
──────────────────────────────────────────────────────────────────────────────
Həmin rədd BİR müştəri üçün idi: "hər kassa PC-sinə 1C quraşdırmaq" tələbi
özünə-xidmət prinsipini pozurdu. Çox-müştərili reallıqda isə şərt tərsinə
çevrilir — bəzi müştəridə 1C ONSUZ DA hər kompüterdə quraşdırılıb, veb-server
isə yayımlanmayıb və IT şöbəsi onu açmağa razı deyil. Belə müştəri üçün COM
yeganə işləyən yoldur, HTTP isə mövcud olmayan bir seçimdir.

──────────────────────────────────────────────────────────────────────────────
YALNIZ WINDOWS — VƏ BU, İDXAL ANINDA ÇÖKMƏMƏLİDİR
──────────────────────────────────────────────────────────────────────────────
`win32com` modul səviyyəsində idxal edilsəydi, bu fayl Linux CI-da və
inkişafçı maşınında `ImportError` verərdi — halbuki fayl `erp/__init__.py`
vasitəsilə BÜTÜN ERP paketi ilə birlikdə idxal olunur, yəni HTTP konnektoru da
işləməz olardı. Ona görə idxal metod DAXİLİNDƏDİR və platforma yoxlaması
`platform.system()` ilə aparılır.

`sys.platform` QƏSDƏN İSTİFADƏ EDİLMİR: mypy konfiqurasiyası
`platform = "win32"` ilə işləyir (bax `pyproject.toml`) və `warn_unreachable`
həmin qapının `else` budağını "əlçatmaz kod" kimi işarələyərdi — halbuki kod
faktiki olaraq Linux CI-da İCRA OLUNUR. Eyni naxış `updates/verification.py`-da
da işlədilib.

──────────────────────────────────────────────────────────────────────────────
1C-nin COM API-si LOKALİZƏ OLUNUB
──────────────────────────────────────────────────────────────────────────────
1C obyekt modelinin metod adları platformanın dilindən asılıdır: rus buraxılışı
`НовыйОбъект`/`Запрос`/`Выполнить`, beynəlxalq buraxılış isə
`NewObject`/`Query`/`Execute` verir. Birini seçib digərini nəzərə almasaydıq,
konnektor müştərilərin təxminən yarısında `AttributeError` ilə dayanardı və
səbəb log-da "obyektdə belə atribut yoxdur" kimi görünərdi.

Ona görə hər çağırış ALİAS SİYAHISI ilə həll olunur (`_resolve`) və heç biri
tapılmasa KONKRET Azərbaycanca səbəb qaytarılır. Sorğu MƏTNİNİN dili isə
konfiqurasiyadadır (`query_language`), çünki sorğu dili sənədin metadata
adları ilə birlikdə gəlir və avtomatik təxmin edilə bilməz.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.erp import (
    DEFAULT_PAGE_SIZE,
    ConnectionTestResult,
    ConnectorType,
    ErpAuthenticationError,
    ErpConfigurationError,
    ErpConnectionError,
    ErpPlatformError,
    ErpProtocolError,
    OneCSaleRecord,
)
from src.infrastructure.erp.connector_base import (
    OneCConnectorBase,
    elapsed_ms,
    optional_text,
    to_datetime,
    to_decimal,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.domain.value_objects.erp import SyncCursor
    from src.infrastructure.erp.one_c_connector import OneCServerConfig

_log = get_logger(__name__)

#: 1C 8.3-ün COM sinif identifikatoru. PLATFORMA SABİTİDİR, siyasət deyil —
#: 1C-nin sənədləşməsində belə yazılıb və müəssisə seçimi ilə dəyişmir.
#: (8.2 üçün `V82.COMConnector` olardı, lakin məhsul 8.3-ə hədəflənib.)
COM_CONNECTOR_PROG_ID: Final[str] = "V83.COMConnector"

#: Sorğu nəticəsinin sütun adları — HƏMİŞƏ latın hərfləri ilə.
#: Sorğu mətnində `КАК DocumentId` (və ya `AS DocumentId`) yazıldığı üçün
#: sətri oxumaq platformanın dilindən ASILI DEYİL.
COLUMN_DOCUMENT_ID: Final[str] = "DocumentId"
COLUMN_DOCUMENT_DATE: Final[str] = "DocumentDate"
COLUMN_SELLER_ID: Final[str] = "SellerId"
COLUMN_STORE_CODE: Final[str] = "StoreCode"
COLUMN_AMOUNT: Final[str] = "Amount"
COLUMN_SELLER_NAME: Final[str] = "SellerName"

#: Metod/xassə adlarının alias siyahıları (rus buraxılışı → beynəlxalq).
_NEW_OBJECT_ALIASES: Final[tuple[str, ...]] = ("NewObject", "НовыйОбъект")
_QUERY_OBJECT_ALIASES: Final[tuple[str, ...]] = ("Запрос", "Query")
_QUERY_TEXT_ALIASES: Final[tuple[str, ...]] = ("Текст", "Text")
_SET_PARAMETER_ALIASES: Final[tuple[str, ...]] = ("УстановитьПараметр", "SetParameter")
_EXECUTE_ALIASES: Final[tuple[str, ...]] = ("Выполнить", "Execute")
_SELECT_ALIASES: Final[tuple[str, ...]] = ("Выбрать", "Choose", "Select")
_NEXT_ALIASES: Final[tuple[str, ...]] = ("Следующий", "Next")

#: COM xəta mətnindən səbəbi tanımaq üçün açar sözlər.
#:
#: NİYƏ MƏTN AXTARIŞI: 1C COM xətaları `HRESULT` kodu kimi deyil, mətn kimi
#: gəlir (`pywintypes.com_error` sonuncu elementi) və kod hər halda
#: `DISP_E_EXCEPTION`-dır — yəni koda görə təsnifat MÜMKÜN DEYİL. Açar sözlər
#: rus, ingilis və azərbaycan buraxılışlarını əhatə edir; heç biri uyğun
#: gəlməzsə səbəb "naməlum" deyil, XAM COM mətni ilə birlikdə qaytarılır.
_AUTH_MARKERS: Final[tuple[str, ...]] = (
    "идентификация пользователя не выполнена",
    "неверные имя или пароль",
    "authentication",
    "invalid user name or password",
)
_INFOBASE_MARKERS: Final[tuple[str, ...]] = (
    "информационная база не обнаружена",
    "не найден файл",
    "infobase",
    "не удалось открыть",
)
_REGISTRATION_MARKERS: Final[tuple[str, ...]] = (
    "invalid class string",
    "class not registered",
    "не зарегистрирован",
    "недопустимая строка с указанием класса",
)


@dataclass(frozen=True)
class ComConnectionSettings:
    """`connector_config` sözlüyünün COM üzü.

    Sahələrin bir hissəsi SÜTUNLARDAN gəlir (`host`, `infobase`, `username`,
    `password`) — bax `OneCServerConfig` başlığı: sirr həmişə eyni iki
    sütunda qalır ki, deşifrə məntiqi bölünməsin.
    """

    #: `Srvr=` (klient-server) və ya `File=` (fayl bazası) dəyəri.
    server: str
    #: `Ref=` — baza adı. Fayl rejimində istifadə OLUNMUR.
    infobase: str
    username: str
    password: str
    #: `True` → bağlantı sətri `File="..."` formasında qurulur.
    file_mode: bool = False
    #: Sorğu mətninin dili: `RU` (defolt) və ya `EN`.
    query_language: str = "RU"
    #: Sənədin metadata adı — `Документ.РеализацияТоваровУслуг`.
    query_source: str = "Документ.РеализацияТоваровУслуг"
    id_field: str = "Ссылка"
    date_field: str = "Дата"
    posted_field: str = "Проведен"
    seller_field: str = "Ответственный"
    store_field: str = "Склад"
    amount_field: str = "СуммаДокумента"
    #: İSTƏYƏ BAĞLI — yalnız ad-əsaslı fallback uyğunlaşması üçün.
    seller_name_field: str = ""

    @classmethod
    def from_config(cls, config: OneCServerConfig) -> ComConnectionSettings:
        """Sütunlar + `connector_config` → tam COM parametrləri.

        Raises:
            ErpConfigurationError: məcburi sahə boşdursa. Mesaj HANSI sahənin
                boş olduğunu deyir — "konfiqurasiya səhvdir" tək başına
                istifadəçiyə heç nə vermir (1c.md tələb 3).
        """
        extra = config.connector_config
        file_mode = extra.flag("file_mode")
        server = extra.text("server") or config.host
        infobase = extra.text("infobase") or config.infobase

        if not server.strip():
            raise ErpConfigurationError(
                "COM bağlantısı üçün server adı/qovluq yolu boşdur",
                user_message=(
                    "COM bağlantısı üçün 1C server adını (və ya fayl bazasının "
                    "qovluğunu) daxil edin."
                ),
            )
        if not file_mode and not infobase.strip():
            raise ErpConfigurationError(
                "COM bağlantısı üçün baza adı (Ref) boşdur",
                user_message=(
                    "COM bağlantısı üçün 1C baza adını (Ref) daxil edin — "
                    "server adı tək başına kifayət etmir."
                ),
            )

        language = extra.text("query_language", "RU").upper()
        defaults = _QUERY_DEFAULTS.get(language, _QUERY_DEFAULTS["RU"])
        return cls(
            server=server,
            infobase=infobase,
            username=extra.text("username") or config.username,
            password=extra.text("password") or config.password,
            file_mode=file_mode,
            query_language=language if language in _QUERY_DEFAULTS else "RU",
            query_source=extra.text("query_source", defaults["source"]),
            id_field=extra.text("id_field", defaults["id"]),
            date_field=extra.text("date_field", defaults["date"]),
            posted_field=extra.text("posted_field", defaults["posted"]),
            seller_field=extra.text("seller_field", defaults["seller"]),
            store_field=extra.text("store_field", defaults["store"]),
            amount_field=extra.text("amount_field", defaults["amount"]),
            seller_name_field=extra.text("seller_name_field"),
        )

    def connection_string(self) -> str:
        """`V83.COMConnector.Connect()` sətri.

        Dəyərlər dırnaq içindədir, çünki 1C server adında və qovluq yolunda
        boşluq ola bilər (`C:\\Bazalar\\Ticaret Bazasi`) — dırnaqsız sətir
        həmin halda kəsilərdi.
        """
        if self.file_mode:
            head = f'File="{self.server}"'
        else:
            head = f'Srvr="{self.server}";Ref="{self.infobase}"'
        return f'{head};Usr="{self.username}";Pwd="{self.password}"'

    def __repr__(self) -> str:
        # Şifrə `repr`-də görünməməlidir (SEC-013) — bu obyekt xəta konteksti
        # ilə log-a düşə bilər.
        return (
            f"ComConnectionSettings(server={self.server}, infobase={self.infobase}, "
            f"username={self.username}, file_mode={self.file_mode})"
        )


#: Sorğu dilinə görə DEFOLT metadata adları.
#:
#: Rus buraxılışı defoltdur, çünki Azərbaycanda satılan 1C konfiqurasiyaları
#: («Розница», «Управление Торговлей») rus platformasında gəlir. İngilis
#: variantı isə beynəlxalq buraxılış üçündür — hər ikisi sihirbazdan
#: dəyişdirilə bilir (bax `OneCDocumentMapping` üçün verilmiş eyni qərar).
_QUERY_DEFAULTS: Final[dict[str, dict[str, str]]] = {
    "RU": {
        "source": "Документ.РеализацияТоваровУслуг",
        "id": "Ссылка",
        "date": "Дата",
        "posted": "Проведен",
        "seller": "Ответственный",
        "store": "Склад",
        "amount": "СуммаДокумента",
    },
    "EN": {
        "source": "Document.GoodsSales",
        "id": "Ref",
        "date": "Date",
        "posted": "Posted",
        "seller": "Responsible",
        "store": "Warehouse",
        "amount": "DocumentAmount",
    },
}

#: Sorğu dilinin açar sözləri — mətn qurulması üçün.
_QUERY_KEYWORDS: Final[dict[str, dict[str, str]]] = {
    "RU": {
        "select": "ВЫБРАТЬ ПЕРВЫЕ",
        "as": "КАК",
        "from": "ИЗ",
        "where": "ГДЕ",
        "and": "И",
        "order": "УПОРЯДОЧИТЬ ПО",
        "asc": "ВОЗР",
        "period": "&Период",
    },
    "EN": {
        "select": "SELECT TOP",
        "as": "AS",
        "from": "FROM",
        "where": "WHERE",
        "and": "AND",
        "order": "ORDER BY",
        "asc": "ASC",
        "period": "&Period",
    },
}

#: `УстановитьПараметр` çağırışında istifadə olunan parametr adı (dilə görə).
_PERIOD_PARAMETER: Final[dict[str, str]] = {"RU": "Период", "EN": "Period"}


class OneCComConnector(OneCConnectorBase):
    """1C bazasına COM/OLE üzərindən qoşulur (YALNIZ Windows)."""

    connector_type = ConnectorType.COM

    def __init__(
        self,
        config: OneCServerConfig,
        *,
        dispatcher: Callable[[str], Any] | None = None,
        system_name: str | None = None,
    ) -> None:
        """
        Args:
            dispatcher: `win32com.client.Dispatch` əvəzedicisi. Verilərsə
                platforma qapısı KEÇİLİR — testlər real COM olmadan bütün
                axını yoxlaya bilsin deyə (eyni naxış:
                `updates/verification.AuthenticodeVerifier.runner`).
            system_name: `platform.system()` əvəzedicisi — "COM Windows-dan
                kənarda aydın xəta verir" qaydasını Windows maşınında da test
                etmək üçün.
        """
        self._config = config
        self._dispatcher = dispatcher
        self._system_name = system_name
        #: Açıq COM bağlantısı — `close()`-a qədər saxlanılır, çünki
        #: `Connect()` bahalı əməliyyatdır (1C serverinə seans açır) və bir
        #: sinxronizasiya dövründə bir neçə səhifə oxunur.
        self._connection: Any = None

    # ------------------------------ platforma --------------------------------- #

    @property
    def is_supported(self) -> bool:
        """COM bu mühitdə ümumiyyətlə mümkündürmü."""
        if self._dispatcher is not None:
            return True
        return (self._system_name or platform.system()) == "Windows"

    def _require_platform(self) -> None:
        if not self.is_supported:
            current = self._system_name or platform.system()
            raise ErpPlatformError(
                "COM bağlantısı bu əməliyyat sistemində mümkün deyil",
                user_message=(
                    f"COM bağlantısı yalnız Windows-da işləyir (cari sistem: {current}). "
                    "HTTP/OData və ya Fayl-Mübadiləsi növünü seçin."
                ),
                context={"platform": current},
            )

    # -------------------------------- bağlantı -------------------------------- #

    def _connect(self) -> Any:
        """COM obyektini qurur və bazaya qoşulur.

        Hər addım AYRICA tutulur, çünki səbəblər tamamilə fərqlidir:
        komponent qeydiyyatdan keçməyib ≠ istifadəçi/şifrə səhvdir ≠ baza
        tapılmadı. Üçünü bir `except`-də birləşdirsəydik, sihirbaz "1C ilə
        əlaqə qurulmadı" deyərdi və istifadəçi hansı sahəni düzəldəcəyini
        bilməzdi (1c.md tələb 3).
        """
        if self._connection is not None:
            return self._connection

        self._require_platform()
        settings = ComConnectionSettings.from_config(self._config)
        connector = self._create_com_object()

        try:
            connection = connector.Connect(settings.connection_string())
        except Exception as exc:
            raise self._classify(exc, settings) from exc

        if connection is None:
            raise ErpConnectionError(
                "1C COM konnektoru boş bağlantı qaytardı",
                user_message=(
                    "1C bazasına qoşulmaq mümkün olmadı — baza adını və istifadəçi "
                    "hüquqlarını yoxlayın."
                ),
                context={"server": settings.server, "infobase": settings.infobase},
            )
        self._connection = connection
        return connection

    def _create_com_object(self) -> Any:
        """`V83.COMConnector` obyektini yaradır (və ya sahtəni qaytarır)."""
        if self._dispatcher is not None:
            return self._dispatcher(COM_CONNECTOR_PROG_ID)

        try:
            from win32com.client import Dispatch  # noqa: PLC0415 — bax modul başlığı
        except ImportError as exc:
            raise ErpPlatformError(
                "`pywin32` kitabxanası mövcud deyil",
                user_message=(
                    "COM bağlantısı üçün lazım olan Windows komponenti tapılmadı. "
                    "Proqramı yenidən quraşdırın və ya HTTP/OData növünü seçin."
                ),
            ) from exc

        try:
            return Dispatch(COM_CONNECTOR_PROG_ID)
        except Exception as exc:
            raise ErpConnectionError(
                f"`{COM_CONNECTOR_PROG_ID}` COM obyekti yaradıla bilmədi",
                user_message=(
                    "1C-nin COM komponenti («V83.COMConnector») bu kompüterdə "
                    "qeydiyyatdan keçməyib. 1C platformasını quraşdırın və ya "
                    "«comcntr.dll» faylını qeydiyyata alın."
                ),
                context={"error": str(exc)[:200]},
            ) from exc

    @staticmethod
    def _classify(exc: Exception, settings: ComConnectionSettings) -> Exception:
        """COM xətasını KONKRET domen istisnasına çevirir."""
        text = str(exc).lower()
        if any(marker in text for marker in _AUTH_MARKERS):
            return ErpAuthenticationError(
                "1C COM autentifikasiyası rədd edildi",
                context={"username": settings.username, "server": settings.server},
            )
        if any(marker in text for marker in _INFOBASE_MARKERS):
            return ErpConnectionError(
                "1C bazası tapılmadı",
                user_message=(
                    f"«{settings.infobase or settings.server}» adlı baza tapılmadı — "
                    "baza adını (Ref) və server adını yoxlayın."
                ),
                context={"server": settings.server, "infobase": settings.infobase},
            )
        if any(marker in text for marker in _REGISTRATION_MARKERS):
            return ErpConnectionError(
                "1C COM komponenti qeydiyyatdan keçməyib",
                user_message=(
                    "1C-nin COM komponenti bu kompüterdə qeydiyyatdan keçməyib — "
                    "1C platformasını quraşdırın."
                ),
                context={"error": str(exc)[:200]},
            )
        # Naməlum COM xətası SÜKUTLA "ümumi problem"ə çevrilmir: mətnin özü
        # `detail`-ə düşür və `app.log`-da tam görünür.
        return ErpConnectionError(
            f"1C COM bağlantısı uğursuz oldu: {str(exc)[:200]}",
            user_message=(
                "1C bazasına COM üzərindən qoşulmaq mümkün olmadı. Server adını, "
                "baza adını və istifadəçi məlumatlarını yoxlayın."
            ),
            context={"server": settings.server, "infobase": settings.infobase},
        )

    def close(self) -> None:
        """COM seansını buraxır.

        1C bağlantısı LİSENZİYA yeri tutur: buraxılmasa, sinxronizasiya
        dövrləri bir-birinin ardınca yeni seans açar və müəssisənin 1C
        lisenziyaları tükənərdi. `None` təyinatı COM obyektini `refcount`
        sıfırlandıqda buraxır — `Disconnect` metodu `V83.COMConnector`-da
        MÖVCUD DEYİL, bağlantı obyektin ömrü ilə bağlıdır.
        """
        self._connection = None

    @property
    def config(self) -> OneCServerConfig:
        return self._config

    # ---------------------------------- test ---------------------------------- #

    def test_connection(self) -> ConnectionTestResult:
        """Platforma + COM obyekti + bağlantı — BİR addımda."""
        started = time.monotonic()
        try:
            settings = ComConnectionSettings.from_config(self._config)
            self._connect()
        except (
            ErpPlatformError,
            ErpConfigurationError,
            ErpAuthenticationError,
            ErpConnectionError,
        ) as exc:
            return self._failed_test(exc, started)

        return ConnectionTestResult(
            ok=True,
            message="Bağlantı uğurludur — 1C bazasına COM üzərindən qoşulundu.",
            entity_verified=settings.query_source,
            elapsed_ms=elapsed_ms(started),
        )

    # -------------------------------- satışlar -------------------------------- #

    def fetch_sales(
        self, cursor: SyncCursor, *, page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[OneCSaleRecord]:
        """Kursordan sonrakı KEÇİRİLMİŞ satış sənədlərini gətirir.

        Filtr `>=` (`ge`) ilə gedir — HTTP konnektoru ilə EYNİ səbəbdən: eyni
        saniyədə yazılmış çeklərin itməməsi üçün (bax `SyncCursor`). Sərhəd
        sənədləri `_new_records` ilə süzülür.
        """
        settings = ComConnectionSettings.from_config(self._config)
        connection = self._connect()
        query = self._new_query(connection, settings, cursor, page_size=page_size)
        selection = self._execute(query, settings)

        parsed: list[OneCSaleRecord] = []
        skipped_without_id = 0
        while _call(selection, _NEXT_ALIASES, settings):
            document_id = str(_column(selection, COLUMN_DOCUMENT_ID) or "").strip()
            if not document_id:
                # Sənəd ID-siz gəlirsə təkrar qorunması işləməzdi (HTTP
                # konnektoru ilə eyni qərar) — atlanır, lakin GÖRÜNƏN şəkildə.
                skipped_without_id += 1
                continue
            parsed.append(
                OneCSaleRecord(
                    document_id=document_id,
                    seller_id=str(_column(selection, COLUMN_SELLER_ID) or "").strip(),
                    store_code=str(_column(selection, COLUMN_STORE_CODE) or "").strip(),
                    gross_amount=to_decimal(_column(selection, COLUMN_AMOUNT), document_id),
                    document_at=to_datetime(_column(selection, COLUMN_DOCUMENT_DATE), document_id),
                    # Ad sütunu sorğuya YALNIZ konfiqurasiyada göstərilibsə
                    # düşür — göstərilməyibsə sətirdə ümumiyyətlə yoxdur.
                    seller_name=optional_text(
                        {COLUMN_SELLER_NAME: _column(selection, COLUMN_SELLER_NAME)},
                        COLUMN_SELLER_NAME if settings.seller_name_field else None,
                    ),
                )
            )

        records = self._new_records(parsed, cursor)
        if skipped_without_id:
            _log.warning(
                "ERP_COM_DOCUMENTS_WITHOUT_ID",
                extra={"server": settings.server, "skipped": skipped_without_id},
            )
        _log.info(
            "ERP_COM_SALES_FETCHED",
            extra={
                "server": settings.server,
                "infobase": settings.infobase,
                "returned": len(parsed),
                "new": len(records),
                "boundary_skipped": len(parsed) - len(records),
            },
        )
        return records

    # ------------------------------ sorğu qurma ------------------------------- #

    def _new_query(
        self,
        connection: Any,
        settings: ComConnectionSettings,
        cursor: SyncCursor,
        *,
        page_size: int,
    ) -> Any:
        """`Запрос` obyektini qurur və mətni/parametri təyin edir."""
        factory = _resolve(connection, _NEW_OBJECT_ALIASES)
        if factory is None:
            raise ErpProtocolError(
                "1C bağlantı obyektində `NewObject`/`НовыйОбъект` metodu yoxdur",
                user_message=(
                    "1C platformasının versiyası gözlənilməzdir — sorğu obyekti "
                    "yaradıla bilmədi. 1C-nin 8.3 buraxılışından istifadə edin."
                ),
                context={"server": settings.server},
            )

        query: Any = None
        for name in _QUERY_OBJECT_ALIASES:
            try:
                query = factory(name)
            except Exception:  # noqa: S112 — növbəti alias sınanır, bax aşağı
                continue
            if query is not None:
                break
        if query is None:
            raise ErpProtocolError(
                "1C-də `Запрос`/`Query` obyekti yaradıla bilmədi",
                user_message=(
                    "1C sorğu obyekti yaradıla bilmədi — platformanın dili "
                    "gözlənilməzdir. «Sorğu dili» parametrini yoxlayın."
                ),
                context={"server": settings.server, "language": settings.query_language},
            )

        _set(query, _QUERY_TEXT_ALIASES, _query_text(settings, cursor, page_size=page_size))
        if cursor.last_document_at is not None:
            setter = _resolve(query, _SET_PARAMETER_ALIASES)
            if setter is not None:
                setter(_PERIOD_PARAMETER[settings.query_language], cursor.last_document_at)
        return query

    @staticmethod
    def _execute(query: Any, settings: ComConnectionSettings) -> Any:
        """Sorğunu icra edib sətir seçimini qaytarır."""
        try:
            result = _call(query, _EXECUTE_ALIASES, settings)
            selection = _call(result, _SELECT_ALIASES, settings)
        except ErpProtocolError:
            raise
        except Exception as exc:
            raise ErpProtocolError(
                f"1C sorğusu icra olunmadı: {str(exc)[:200]}",
                user_message=(
                    "1C sorğusu icra olunmadı — sənəd adını və rekvizit adlarını "
                    "yoxlayın (məs. «Документ.РеализацияТоваровУслуг»)."
                ),
                context={"source": settings.query_source},
            ) from exc
        return selection


# --------------------------------------------------------------------------- #
# COM alias köməkçiləri
# --------------------------------------------------------------------------- #


def _resolve(target: Any, aliases: Sequence[str]) -> Any:
    """Obyektdə mövcud olan İLK alias-ı qaytarır (yoxdursa `None`)."""
    for name in aliases:
        attribute = getattr(target, name, None)
        if attribute is not None:
            return attribute
    return None


def _call(target: Any, aliases: Sequence[str], settings: ComConnectionSettings) -> Any:
    """Alias siyahısındakı metodu çağırır; heç biri yoxdursa KONKRET xəta."""
    method = _resolve(target, aliases)
    if method is None:
        raise ErpProtocolError(
            f"1C obyektində `{'`/`'.join(aliases)}` metodu tapılmadı",
            user_message=(
                "1C obyekt modeli gözlənilən metodları təqdim etmir — platformanın "
                "dili və ya versiyası uyğun deyil."
            ),
            context={"server": settings.server, "aliases": list(aliases)},
        )
    return method()


def _set(target: Any, aliases: Sequence[str], value: str) -> None:
    """Alias siyahısındakı XASSƏYƏ dəyər yazır.

    `_resolve` BURADA İŞLƏMİR: o, xassənin CARİ dəyərini oxuyar və yeni
    obyektdə xassə boş sətir (`""`) olduğu üçün `None` olmayan, lakin
    çağırıla bilməyən dəyər qaytarardı. Ona görə `hasattr` ilə yoxlanılır.
    """
    for name in aliases:
        if hasattr(target, name):
            setattr(target, name, value)
            return
    raise ErpProtocolError(
        f"1C sorğu obyektində `{'`/`'.join(aliases)}` xassəsi yoxdur",
        user_message=(
            "1C sorğu obyektinə mətn yazmaq mümkün olmadı — platformanın dili gözlənilməzdir."
        ),
        context={"aliases": list(aliases)},
    )


def _column(selection: Any, name: str) -> Any:
    """Sətrin sütununu oxuyur — sütun adı sorğudakı latın alias-ıdır."""
    return getattr(selection, name, None)


def _query_text(settings: ComConnectionSettings, cursor: SyncCursor, *, page_size: int) -> str:
    """1C sorğu mətnini qurur.

    KURSOR ŞƏRTİ YALNIZ LAZIM OLDUQDA ƏLAVƏ EDİLİR: ilk dövrdə (`is_initial`)
    tarix parametri yoxdur, çünki 1C-nin "boş tarix" dəyəri COM üzərindən
    etibarlı ötürülmür (`VT_DATE` 1-ci ili ifadə edə bilmir). Şərti həmişə
    saxlayıb süni bir "başlanğıc tarixi" seçsəydik, həmin tarixdən ƏVVƏLKİ
    sənədlər HEÇ VAXT oxunmazdı.
    """
    keywords = _QUERY_KEYWORDS[settings.query_language]
    columns = [
        f"    Док.{settings.id_field} {keywords['as']} {COLUMN_DOCUMENT_ID}",
        f"    Док.{settings.date_field} {keywords['as']} {COLUMN_DOCUMENT_DATE}",
        f"    Док.{settings.seller_field} {keywords['as']} {COLUMN_SELLER_ID}",
        f"    Док.{settings.store_field} {keywords['as']} {COLUMN_STORE_CODE}",
        f"    Док.{settings.amount_field} {keywords['as']} {COLUMN_AMOUNT}",
    ]
    if settings.seller_name_field:
        columns.append(
            f"    Док.{settings.seller_name_field} {keywords['as']} {COLUMN_SELLER_NAME}"
        )

    # Yalnız KEÇİRİLMİŞ sənədlər — filtr mənbədə tətbiq olunur (bax
    # `one_c_connector` modul başlığı: "NİYƏ YALNIZ `Posted = true`").
    conditions = [f"    Док.{settings.posted_field}"]
    if cursor.last_document_at is not None:
        conditions.append(
            f"    {keywords['and']} Док.{settings.date_field} >= {keywords['period']}"
        )

    return "\n".join(
        [
            f"{keywords['select']} {page_size}",
            ",\n".join(columns),
            keywords["from"],
            f"    {settings.query_source} {keywords['as']} Док",
            keywords["where"],
            "\n".join(conditions),
            keywords["order"],
            f"    Док.{settings.date_field} {keywords['asc']}",
        ]
    )


__all__ = [
    "COM_CONNECTOR_PROG_ID",
    "ComConnectionSettings",
    "OneCComConnector",
]
