"""Dəyişdirilə bilən (pluggable) 1C konnektorları — 1c.md.

Bu fayl 1c.md-nin gətirdiyi ÜÇ bağlantı növünü və onların ətrafındakı
qərarları qapı halına gətirir:

    * üç konnektorun da EYNİ portu ödəməsi (yuxarı qat tipi bilmir),
    * `test_connection`-un hər tip üçün KONKRET texniki səbəb qaytarması
      (1c.md tələb 3: generic "xəta baş verdi" QADAĞANDIR),
    * COM-un qeyri-Windows mühitdə aydın xəta verməsi və ÇÖKMƏMƏSİ,
    * fayl konnektorunun çatışan qovluq / səhv format / çatışan sütun
      hallarında fərqli səbəblər verməsi,
    * fabrikin `connector_type`-a görə doğru sinfi seçməsi,
    * `connector_type` yazılmamış KÖHNƏ sətrin HTTP kimi oxunması,
    * konfiqurasiyadakı sirrin `repr`-ə və audit sətrinə SIZMAMASI.

Real 1C YOXDUR: COM sahtə `Dispatch` obyekti ilə, fayl mübadiləsi isə
`tmp_path`-dakı həqiqi fayllarla yoxlanılır.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from src.application.use_cases.erp_connection import (
    MANAGE_ERP_SERVERS_FLAG,
    ErpConnectionError,
    ErpConnectionWizardUseCase,
)
from src.domain.entities import Employee, Position
from src.domain.interfaces.ports import SalesDataConnector
from src.domain.policies import SystemLimitKey
from src.domain.value_objects import PermissionFlag, SystemRole, Username
from src.domain.value_objects.erp import (
    DEFAULT_SYNC_INTERVAL_SECONDS,
    FILE_EXCHANGE_SYNC_INTERVAL_SECONDS,
    ConnectorConfig,
    ConnectorType,
    ErpConfigurationError,
    ErpPlatformError,
    ErpServer,
    ErpServerDraft,
    ErpServerStatus,
    SyncCursor,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ErpServerId,
    PositionId,
    StoreId,
    TenantId,
)
from src.infrastructure.erp.com_connector import (
    COM_CONNECTOR_PROG_ID,
    ComConnectionSettings,
    OneCComConnector,
)
from src.infrastructure.erp.file_exchange_connector import (
    SYNTHETIC_ID_PREFIX,
    FileExchangeSettings,
    OneCFileExchangeConnector,
)
from src.infrastructure.erp.health import ServerHealth, ServerHealthRow
from src.infrastructure.erp.one_c_connector import (
    OneCConnectorFactory,
    OneCHttpConnector,
    OneCServerConfig,
)
from src.infrastructure.erp.servers import _draft_from_payload, _row_to_server
from src.infrastructure.erp.sync_worker import ErpSyncManager
from tests.fixtures.fakes import FakeSystemLimits, RecordingAudit

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
SERVER_A = ErpServerId(uuid.uuid4())
SERVER_B = ErpServerId(uuid.uuid4())
STORE_A = StoreId(uuid.uuid4())
MOMENT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Ortaq köməkçilər
# --------------------------------------------------------------------------- #


def http_config(**overrides: Any) -> OneCServerConfig:
    defaults: dict[str, Any] = {
        "host": "10.0.0.5",
        "port": 8080,
        "username": "kompasos",
        "password": "s3cret",
        "infobase": "trade",
    }
    return OneCServerConfig(**{**defaults, **overrides})


def com_config(**values: Any) -> OneCServerConfig:
    """COM konfiqurasiyası — port sentinel `0`."""
    return OneCServerConfig(
        host=values.pop("host", "1c-srv"),
        port=0,
        username=values.pop("username", "kompasos"),
        password=values.pop("password", "s3cret"),
        infobase=values.pop("infobase", "trade"),
        connector_type=ConnectorType.COM,
        connector_config=ConnectorConfig(values=values),
    )


def file_config(folder: str, **values: Any) -> OneCServerConfig:
    return OneCServerConfig(
        host=folder,
        port=0,
        username="",
        password="",
        infobase="",
        connector_type=ConnectorType.FILE_EXCHANGE,
        connector_config=ConnectorConfig(values=values),
    )


def make_employee(*flags: str) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.CEO.value,
        name_az="CEO",
        priority=SystemRole.CEO.default_priority,
        is_system=True,
    )
    for code in flags:
        position.grant(PermissionFlag(code=code, category="ERP_INFRA"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Test",
        last_name="CEO",
        store_id=STORE_A,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def make_server(**overrides: Any) -> ErpServer:
    defaults: dict[str, Any] = {
        "id": SERVER_A,
        "tenant_id": TENANT,
        "server_name": "Bellona — Bakı",
        "host": "10.0.0.5",
        "port": 8080,
        "username": "kompasos",
        "infobase": "trade",
        "status": ErpServerStatus.ACTIVE,
    }
    return ErpServer(**{**defaults, **overrides})


CSV_HEADER = "Sənəd;Дата;Продавец;Склад;Сумма;Ad"


def write_csv(folder: Path, name: str = "satis.csv", rows: tuple[str, ...] = ()) -> Path:
    path = folder / name
    body = rows or (
        "DOC-1;2026-08-15T10:00:00;SELLER-1;STORE-01;1 250,50;Əliyev Elvin",
        "DOC-2;2026-08-15T11:00:00;SELLER-2;STORE-01;99.00;Məmmədov Ramin",
    )
    path.write_text("\n".join([CSV_HEADER, *body]) + "\n", encoding="utf-8")
    return path


def csv_columns() -> dict[str, str]:
    return {
        "document_id_column": "Sənəd",
        "date_column": "Дата",
        "seller_column": "Продавец",
        "store_column": "Склад",
        "amount_column": "Сумма",
        "seller_name_column": "Ad",
    }


# --------------------------------------------------------------------------- #
# 1. Domen: bağlantı növü, konfiqurasiya, ünvan
# --------------------------------------------------------------------------- #


class TestConnectorType:
    def test_kohne_setir_http_kimi_oxunur(self) -> None:
        """GERİYƏ UYĞUNLUQ: sütun yoxdursa sətir OData ilə qurulub."""
        assert ConnectorType.parse(None) is ConnectorType.HTTP
        assert ConnectorType.parse("") is ConnectorType.HTTP
        assert ConnectorType.parse("   ") is ConnectorType.HTTP

    def test_namelum_tip_sinxronizasiyani_dayandirmir(self) -> None:
        # Naməlum mətn istisna atsaydı, bir səhv sətir bütün dövrü qırardı.
        assert ConnectorType.parse("SOAP") is ConnectorType.HTTP

    def test_kicik_herfli_deyer_qebul_edilir(self) -> None:
        assert ConnectorType.parse("file_exchange") is ConnectorType.FILE_EXCHANGE

    def test_yalniz_http_port_isledir(self) -> None:
        assert ConnectorType.HTTP.uses_port
        assert not ConnectorType.COM.uses_port
        assert not ConnectorType.FILE_EXCHANGE.uses_port

    def test_yalniz_com_windows_teleb_edir(self) -> None:
        assert ConnectorType.COM.requires_windows
        assert not ConnectorType.HTTP.requires_windows

    def test_fayl_mubadilesi_real_vaxt_deyil(self) -> None:
        # İstifadəçiyə göstərilən vəd budur (1c.md kart izahı).
        assert not ConnectorType.FILE_EXCHANGE.is_real_time
        assert "real-vaxt DEYİL" in ConnectorType.FILE_EXCHANGE.card_description_az

    def test_fayl_mubadilesi_infobase_teleb_etmir(self) -> None:
        assert not ConnectorType.FILE_EXCHANGE.requires_infobase
        assert ConnectorType.HTTP.requires_infobase
        assert ConnectorType.COM.requires_infobase

    def test_defolt_dovr_tipe_gore_ferqlenir(self) -> None:
        assert ConnectorType.HTTP.default_sync_interval_seconds == DEFAULT_SYNC_INTERVAL_SECONDS
        assert ConnectorType.COM.default_sync_interval_seconds == DEFAULT_SYNC_INTERVAL_SECONDS
        assert (
            ConnectorType.FILE_EXCHANGE.default_sync_interval_seconds
            == FILE_EXCHANGE_SYNC_INTERVAL_SECONDS
        )

    def test_gecikmenin_menasi_tipe_gore_yazilir(self) -> None:
        # Fayl mübadiləsində ŞƏBƏKƏ gecikməsi anlayışı yoxdur.
        assert "Şəbəkə" in ConnectorType.HTTP.latency_meaning_az
        assert "Qovluğun" in ConnectorType.FILE_EXCHANGE.latency_meaning_az
        assert "COM" in ConnectorType.COM.latency_meaning_az

    def test_her_tipin_oz_nisani_ve_izahi_var(self) -> None:
        labels = {tip.label_az for tip in ConnectorType}
        assert len(labels) == len(ConnectorType)
        assert all(tip.card_description_az.strip() for tip in ConnectorType)
        assert all(tip.address_label_az.strip() for tip in ConnectorType)


class TestConnectorConfigSecrets:
    def test_sirr_repr_de_gorunmur(self) -> None:
        config = ConnectorConfig(values={"server": "1c-srv", "password": "çox-gizli"})
        assert "çox-gizli" not in repr(config)
        assert "1c-srv" in repr(config)

    def test_sirr_audit_gorunusunde_yalniz_ad_kimi_qalir(self) -> None:
        config = ConnectorConfig(
            values={"folder": "\\\\srv\\exchange", "share_password": "qorunan-deyer-123"}
        )
        auditable = config.auditable()
        assert "qorunan-deyer-123" not in str(auditable)
        # Lakin sirrin VERİLDİYİ faktı itməməlidir.
        assert auditable["gizli_sahələr"] == ["share_password"]
        assert auditable["folder"] == "\\\\srv\\exchange"

    def test_sirr_draft_auditinde_de_gorunmur(self) -> None:
        draft = make_draft(
            connector_type=ConnectorType.COM,
            connector_config=ConnectorConfig(values={"password": "çox-gizli"}),
        )
        assert "çox-gizli" not in str(draft.auditable())
        assert "çox-gizli" not in repr(draft)

    def test_server_konfiqurasiyasinin_repr_i_sirri_gizledir(self) -> None:
        config = com_config(password="parol-123")
        assert "parol-123" not in repr(config)

    def test_com_parametrlerinin_repr_i_sirri_gizledir(self) -> None:
        settings = ComConnectionSettings.from_config(com_config(password="parol-123"))
        assert "parol-123" not in repr(settings)


def make_draft(**overrides: Any) -> ErpServerDraft:
    defaults: dict[str, Any] = {
        "server_name": "Bellona — Bakı",
        "host": "10.0.0.5",
        "port": 8080,
        "username": "kompasos",
        "password": "s3cret",
        "infobase": "trade",
    }
    return ErpServerDraft(**{**defaults, **overrides})


class TestDraftNormalization:
    def test_qeyri_http_tipde_port_sifirlanir(self) -> None:
        """Sihirbaz tip dəyişəndə köhnə portu daşıyır — sətir rədd EDİLMİR."""
        draft = make_draft(connector_type=ConnectorType.FILE_EXCHANGE, port=8080)
        assert draft.port == 0

    def test_http_portu_toxunulmur(self) -> None:
        assert make_draft(port=8080).port == 8080

    def test_unvan_portsuz_gosterilir(self) -> None:
        # «\\anbar\exchange:0» YANILDICI olardı.
        draft = make_draft(connector_type=ConnectorType.FILE_EXCHANGE, host="\\\\anbar\\exchange")
        assert draft.display_address == "\\\\anbar\\exchange"
        assert make_draft().display_address == "10.0.0.5:8080"

    def test_bos_unvan_tire_ile_gosterilir(self) -> None:
        assert make_draft(host="", connector_type=ConnectorType.COM).display_address == "—"

    def test_dovr_verilmeyibse_tipin_defoltu_isleyir(self) -> None:
        assert make_draft().effective_sync_interval_seconds == DEFAULT_SYNC_INTERVAL_SECONDS
        assert (
            make_draft(connector_type=ConnectorType.FILE_EXCHANGE).effective_sync_interval_seconds
            == FILE_EXCHANGE_SYNC_INTERVAL_SECONDS
        )

    def test_cox_kicik_dovr_db_check_inin_heddine_qaldirilir(self) -> None:
        # DB `sync_interval_seconds >= 30` tələb edir; sətir `psycopg` xətası
        # ilə qırılmamalıdır.
        assert make_draft(sync_interval_seconds=5).effective_sync_interval_seconds == 30

    def test_aciq_verilmis_dovr_qalir(self) -> None:
        assert make_draft(sync_interval_seconds=900).effective_sync_interval_seconds == 900


class TestServerReadModel:
    def test_kohne_setirde_tip_http_olur(self) -> None:
        row = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "server_name": "Köhnə server",
            "host": "10.0.0.9",
            "port": 8080,
            "username": "u",
            "infobase": "trade",
            "status": "ACTIVE",
            # `connector_type` AÇARI YOXDUR — migrations/050-dən əvvəlki sətir.
        }
        server = _row_to_server(row)
        assert server.connector_type is ConnectorType.HTTP
        assert server.display_address == "10.0.0.9:8080"

    def test_fayl_serverinin_unvani_portsuzdur(self) -> None:
        server = make_server(
            connector_type=ConnectorType.FILE_EXCHANGE, host="\\\\anbar\\exchange", port=0
        )
        assert server.display_address == "\\\\anbar\\exchange"
        assert server.auditable()["connector_type"] == "FILE_EXCHANGE"

    def test_kohne_backup_http_kimi_berpa_olunur(self) -> None:
        """migrations/050-dən əvvəlki backup-da `connector_type` yoxdur."""
        draft = _draft_from_payload(
            {
                "server_name": "Köhnə",
                "host": "10.0.0.9",
                "port": 8080,
                "username": "u",
                "password": "p",
                "infobase": "trade",
            }
        )
        assert draft.connector_type is ConnectorType.HTTP
        assert not draft.connector_config

    def test_yeni_backup_tipi_ve_konfiqurasiyani_saxlayir(self) -> None:
        # Tip backup-a düşməsəydi, "geri qaytar" COM serverini HTTP kimi
        # bərpa edərdi.
        draft = _draft_from_payload(
            {
                "server_name": "COM server",
                "host": "1c-srv",
                "port": 0,
                "username": "u",
                "password": "p",
                "infobase": "trade",
                "connector_type": "COM",
                "connector_config": {"query_language": "EN"},
            }
        )
        assert draft.connector_type is ConnectorType.COM
        assert draft.connector_config.text("query_language") == "EN"


# --------------------------------------------------------------------------- #
# 2. Ortaq interfeys və fabrik
# --------------------------------------------------------------------------- #


class TestConnectorPortConformance:
    def test_uc_konnektor_da_eyni_portu_odeyir(self, tmp_path: Path) -> None:
        """Yuxarı qat (sync worker) yalnız bu üç metodu tanıyır."""
        connectors = [
            OneCHttpConnector(http_config()),
            OneCComConnector(com_config(), system_name="Linux"),
            OneCFileExchangeConnector(file_config(str(tmp_path))),
        ]
        for connector in connectors:
            assert isinstance(connector, SalesDataConnector)
            connector.close()

    def test_fabrik_tipe_gore_sinifi_secir(self, tmp_path: Path) -> None:
        configs = {
            SERVER_A: com_config(),
            SERVER_B: file_config(str(tmp_path)),
        }
        factory = OneCConnectorFactory(lambda server_id: configs[server_id])

        assert isinstance(factory.for_server(SERVER_A), OneCComConnector)
        assert isinstance(factory.for_server(SERVER_B), OneCFileExchangeConnector)

    def test_fabrik_defolt_olaraq_http_secir(self) -> None:
        factory = OneCConnectorFactory(lambda _server_id: http_config())
        assert isinstance(factory.for_server(SERVER_A), OneCHttpConnector)

    def test_sihirbaz_yolu_da_eyni_secimi_edir(self, tmp_path: Path) -> None:
        # `for_draft` və `for_server` iki fərqli qayda işlətsəydi, sihirbazda
        # test edilən konnektor sinxronizasiyadakından fərqli olardı.
        factory = OneCConnectorFactory(lambda _server_id: http_config())
        draft = make_draft(
            connector_type=ConnectorType.FILE_EXCHANGE,
            host=str(tmp_path),
            infobase="",
        )
        assert isinstance(factory.for_draft(draft), OneCFileExchangeConnector)


# --------------------------------------------------------------------------- #
# 3. COM konnektoru
# --------------------------------------------------------------------------- #


#: 1C obyekt modelinin metod adları — platformanın DİLİNƏ görə.
#:
#: Sahtələr adları DİNAMİK (`setattr`) təyin edir, `def Выполнить(...)` kimi
#: yazmır: ruff qeyri-ASCII identifikatoru qadağan edir (PLC2401) və qayda
#: doğrudur — həqiqi kodumuzda belə adlar OLMAMALIDIR. Sahtənin isə məhz o
#: adları daşıması VACİBDİR, çünki konnektorun alias həlli (`_resolve`) yalnız
#: belə yoxlanıla bilər.
_COM_NAMES: dict[str, dict[str, str]] = {
    "RU": {
        "new_object": "НовыйОбъект",
        "query": "Запрос",
        "text": "Текст",
        "set_parameter": "УстановитьПараметр",
        "execute": "Выполнить",
        "select": "Выбрать",
        "next": "Следующий",
    },
    "EN": {
        "new_object": "NewObject",
        "query": "Query",
        "text": "Text",
        "set_parameter": "SetParameter",
        "execute": "Execute",
        "select": "Choose",
        "next": "Next",
    },
}


class FakeSelection:
    """1C sorğu nəticəsinin sahtəsi — `Следующий()` ilə sətir-sətir gəzilir."""

    def __init__(self, rows: list[dict[str, Any]], *, language: str = "RU") -> None:
        self._rows = list(rows)
        self._current: dict[str, Any] = {}
        setattr(self, _COM_NAMES[language]["next"], self._next)

    def _next(self) -> bool:
        if not self._rows:
            return False
        self._current = self._rows.pop(0)
        return True

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["_current"][name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class FakeQueryResult:
    def __init__(self, rows: list[dict[str, Any]], *, language: str = "RU") -> None:
        self._rows = rows
        self._language = language
        setattr(self, _COM_NAMES[language]["select"], self._select)

    def _select(self) -> FakeSelection:
        return FakeSelection(self._rows, language=self._language)


class FakeQuery:
    def __init__(self, rows: list[dict[str, Any]], *, language: str = "RU") -> None:
        self.parameters: dict[str, Any] = {}
        self._rows = rows
        self._language = language
        names = _COM_NAMES[language]
        # Mətn XASSƏSİ əvvəlcədən mövcud olmalıdır: konnektor `hasattr` ilə
        # yoxlayıb sonra yazır (bax `com_connector._set`).
        setattr(self, names["text"], "")
        setattr(self, names["set_parameter"], self._set_parameter)
        setattr(self, names["execute"], self._execute)

    @property
    def text(self) -> str:
        """Konnektorun yazdığı sorğu mətni."""
        value: str = getattr(self, _COM_NAMES[self._language]["text"])
        return value

    def _set_parameter(self, name: str, value: Any) -> None:
        self.parameters[name] = value

    def _execute(self) -> FakeQueryResult:
        return FakeQueryResult(self._rows, language=self._language)


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None, *, language: str = "RU") -> None:
        self.query = FakeQuery(rows or [], language=language)
        self._language = language
        setattr(self, _COM_NAMES[language]["new_object"], self._new_object)

    def _new_object(self, name: str) -> FakeQuery:
        if name != _COM_NAMES[self._language]["query"]:
            raise AttributeError(name)
        return self.query


class FakeComConnector:
    """`V83.COMConnector` sahtəsi."""

    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
        language: str = "RU",
    ) -> None:
        self._rows = rows or []
        self._error = error
        self.connection_strings: list[str] = []
        self.connection = FakeConnection(self._rows, language=language)

    def Connect(self, connection_string: str) -> FakeConnection:  # noqa: N802 — 1C API adı
        self.connection_strings.append(connection_string)
        if self._error is not None:
            raise self._error
        return self.connection


def com_row(ref: str, *, moment: datetime = MOMENT, amount: str = "100") -> dict[str, Any]:
    return {
        "DocumentId": ref,
        "DocumentDate": moment,
        "SellerId": "SELLER-1",
        "StoreCode": "STORE-01",
        "Amount": amount,
        "SellerName": "Əliyev Elvin",
    }


class TestComPlatformGate:
    def test_windows_olmayan_sistemde_aydin_xeta_verilir_cokmur(self) -> None:
        """1c.md: COM YALNIZ Windows-dadır — bu, ÇÖKMƏ ilə bildirilməməlidir."""
        connector = OneCComConnector(com_config(), system_name="Linux")

        result = connector.test_connection()

        assert not result.ok
        assert "Windows" in result.message
        # Səbəb KONKRETDİR: hansı sistemdə olduğumuz və nə etməli olduğumuz.
        assert "Linux" in result.message
        assert "HTTP" in result.message

    def test_windows_olmayan_sistemde_fetch_sales_istisna_atir(self) -> None:
        # Test uğursuzdursa sinxronizasiya da işləməməlidir — sükutla boş
        # siyahı qaytarmaq "satış yoxdur" kimi oxunardı.
        connector = OneCComConnector(com_config(), system_name="Linux")
        with pytest.raises(ErpPlatformError):
            connector.fetch_sales(SyncCursor())

    def test_dispatcher_verilende_platforma_qapisi_kecilir(self) -> None:
        # Testlər real COM olmadan bütün axını yoxlaya bilməlidir.
        connector = OneCComConnector(
            com_config(), dispatcher=lambda _prog_id: FakeComConnector(), system_name="Linux"
        )
        assert connector.is_supported


class TestComConnection:
    def test_ugurlu_test_baglantisi(self) -> None:
        fake = FakeComConnector()
        connector = OneCComConnector(com_config(), dispatcher=lambda _p: fake)

        result = connector.test_connection()

        assert result.ok
        assert "COM" in result.message
        assert fake.connection_strings == ['Srvr="1c-srv";Ref="trade";Usr="kompasos";Pwd="s3cret"']

    def test_fayl_bazasi_rejiminde_baglanti_setri_ferqlidir(self) -> None:
        fake = FakeComConnector()
        connector = OneCComConnector(
            com_config(file_mode=True, server="C:\\Bazalar\\Ticaret"), dispatcher=lambda _p: fake
        )

        connector.test_connection()

        assert fake.connection_strings[0].startswith('File="C:\\Bazalar\\Ticaret"')

    def test_istifadeci_parol_sehvi_konkret_sebeb_verir(self) -> None:
        fake = FakeComConnector(
            error=RuntimeError("Идентификация пользователя не выполнена. Неверные имя или пароль")
        )
        connector = OneCComConnector(com_config(), dispatcher=lambda _p: fake)

        result = connector.test_connection()

        assert not result.ok
        assert "şifrə" in result.message.lower()

    def test_baza_tapilmadiqda_baza_adi_gosterilir(self) -> None:
        fake = FakeComConnector(error=RuntimeError("Информационная база не обнаружена"))
        connector = OneCComConnector(com_config(infobase="anbar"), dispatcher=lambda _p: fake)

        result = connector.test_connection()

        assert not result.ok
        assert "anbar" in result.message
        assert "Ref" in result.message

    def test_qeydiyyatsiz_komponent_konkret_sebeb_verir(self) -> None:
        fake = FakeComConnector(error=RuntimeError("Invalid class string"))
        connector = OneCComConnector(com_config(), dispatcher=lambda _p: fake)

        result = connector.test_connection()

        assert not result.ok
        assert "qeydiyyat" in result.message.lower()

    def test_namelum_com_xetasi_generic_mesaja_cevrilmir(self) -> None:
        # Səbəb naməlum olsa belə TEXNİKİ mətn `detail`-də qalmalıdır.
        fake = FakeComConnector(error=RuntimeError("Ошибка 0x80004005"))
        connector = OneCComConnector(com_config(), dispatcher=lambda _p: fake)

        result = connector.test_connection()

        assert not result.ok
        assert "0x80004005" in result.detail

    def test_bos_baza_adi_konfiqurasiya_xetasi_verir(self) -> None:
        connector = OneCComConnector(
            com_config(infobase=""), dispatcher=lambda _p: FakeComConnector()
        )

        result = connector.test_connection()

        assert not result.ok
        assert "baza" in result.message.lower()

    def test_bos_server_adi_konfiqurasiya_xetasi_verir(self) -> None:
        with pytest.raises(ErpConfigurationError):
            ComConnectionSettings.from_config(com_config(host=""))

    def test_uc_ferqli_sebeb_uc_ferqli_metn_verir(self) -> None:
        """1c.md tələb 3: generic «xəta baş verdi» QADAĞANDIR."""
        messages = set()
        for error in (
            RuntimeError("Идентификация пользователя не выполнена"),
            RuntimeError("Информационная база не обнаружена"),
            RuntimeError("Class not registered"),
        ):
            connector = OneCComConnector(
                com_config(), dispatcher=lambda _p, exc=error: FakeComConnector(error=exc)
            )
            messages.add(connector.test_connection().message)
        assert len(messages) == 3


class TestComSales:
    def test_senedler_oxunur(self) -> None:
        fake = FakeComConnector(rows=[com_row("DOC-1"), com_row("DOC-2")])
        connector = OneCComConnector(
            com_config(seller_name_field="Ответственный"), dispatcher=lambda _p: fake
        )

        records = connector.fetch_sales(SyncCursor())

        assert [record.document_id for record in records] == ["DOC-1", "DOC-2"]
        assert records[0].gross_amount == Decimal("100")
        assert records[0].seller_name == "Əliyev Elvin"

    def test_id_siz_sened_atlanir_qalanlari_emal_olunur(self) -> None:
        rows = [com_row(""), com_row("DOC-9")]
        connector = OneCComConnector(
            com_config(), dispatcher=lambda _p: FakeComConnector(rows=rows)
        )

        records = connector.fetch_sales(SyncCursor())

        assert [record.document_id for record in records] == ["DOC-9"]

    def test_serhed_senedleri_tekrar_qaytarilmir(self) -> None:
        rows = [com_row("DOC-1"), com_row("DOC-2")]
        connector = OneCComConnector(
            com_config(), dispatcher=lambda _p: FakeComConnector(rows=rows)
        )
        cursor = SyncCursor(last_document_at=MOMENT, boundary_document_ids=frozenset({"DOC-1"}))

        records = connector.fetch_sales(cursor)

        assert [record.document_id for record in records] == ["DOC-2"]

    def test_sorgu_yalniz_kecirilmis_senedleri_isteyir(self) -> None:
        fake = FakeComConnector(rows=[])
        connector = OneCComConnector(com_config(), dispatcher=lambda _p: fake)

        connector.fetch_sales(SyncCursor())

        assert "Проведен" in fake.connection.query.text
        # İlk dövrdə tarix şərti YOXDUR — əks halda ondan əvvəlki sənədlər
        # həmişəlik atlanardı.
        assert "&Период" not in fake.connection.query.text

    def test_kursor_verilende_tarix_parametri_qoyulur(self) -> None:
        fake = FakeComConnector(rows=[])
        connector = OneCComConnector(com_config(), dispatcher=lambda _p: fake)

        connector.fetch_sales(SyncCursor(last_document_at=MOMENT))

        assert "&Период" in fake.connection.query.text
        assert fake.connection.query.parameters["Период"] == MOMENT

    def test_ingilis_sorgu_dili_secile_bilir(self) -> None:
        # Beynəlxalq 1C buraxılışında açar sözlər ingiliscədir.
        fake = FakeComConnector(rows=[])
        connector = OneCComConnector(com_config(query_language="EN"), dispatcher=lambda _p: fake)

        connector.fetch_sales(SyncCursor())

        assert fake.connection.query.text.startswith("SELECT TOP")
        assert "Posted" in fake.connection.query.text

    def test_beynelxalq_buraxilisin_ingilis_metod_adlari_da_islenir(self) -> None:
        """1C obyekt modelinin adları platformanın dilindən asılıdır.

        Rus buraxılışı `Запрос`/`Выполнить`, beynəlxalq buraxılış isə
        `Query`/`Execute` verir. Birini seçib digərini nəzərə almasaydıq,
        konnektor müştərilərin bir hissəsində `AttributeError` ilə dayanardı.
        """
        fake = FakeComConnector(rows=[com_row("DOC-1")], language="EN")
        connector = OneCComConnector(com_config(), dispatcher=lambda _p: fake)

        records = connector.fetch_sales(SyncCursor())

        assert [record.document_id for record in records] == ["DOC-1"]

    def test_prog_id_1c_83_sabitidir(self) -> None:
        seen: list[str] = []
        connector = OneCComConnector(
            com_config(), dispatcher=lambda prog_id: seen.append(prog_id) or FakeComConnector()
        )
        connector.test_connection()
        assert seen == [COM_CONNECTOR_PROG_ID]


# --------------------------------------------------------------------------- #
# 4. Fayl-mübadiləsi konnektoru
# --------------------------------------------------------------------------- #


class TestFileExchangeTest:
    def test_catismayan_qovluq_konkret_sebeb_verir(self, tmp_path: Path) -> None:
        connector = OneCFileExchangeConnector(
            file_config(str(tmp_path / "yoxdur"), **csv_columns())
        )

        result = connector.test_connection()

        assert not result.ok
        assert "tapılmadı" in result.message
        assert "yoxdur" in result.message

    def test_qovluq_evezine_fayl_verilse_ayrica_sebeb_verilir(self, tmp_path: Path) -> None:
        path = write_csv(tmp_path)
        connector = OneCFileExchangeConnector(file_config(str(path), **csv_columns()))

        result = connector.test_connection()

        assert not result.ok
        assert "qovluq deyil" in result.message

    def test_uygun_fayl_yoxdursa_ixrac_tapsirigi_teklif_olunur(self, tmp_path: Path) -> None:
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        result = connector.test_connection()

        assert not result.ok
        assert "ixrac" in result.message

    def test_catismayan_sutun_adlari_siyahilanir(self, tmp_path: Path) -> None:
        write_csv(tmp_path)
        columns = {**csv_columns(), "amount_column": "Məbləğ"}
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        result = connector.test_connection()

        assert not result.ok
        assert "Məbləğ" in result.message

    def test_namelum_format_redd_edilir(self, tmp_path: Path) -> None:
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), file_format="JSON"))

        result = connector.test_connection()

        assert not result.ok
        assert "JSON" in result.message
        assert "CSV" in result.message

    def test_bos_qovluq_yolu_konfiqurasiya_xetasi_verir(self) -> None:
        connector = OneCFileExchangeConnector(file_config(""))

        result = connector.test_connection()

        assert not result.ok
        assert "qovluğ" in result.message.lower()

    def test_ugurlu_test_fayl_adini_qaytarir(self, tmp_path: Path) -> None:
        write_csv(tmp_path)
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        result = connector.test_connection()

        assert result.ok
        assert result.entity_verified == "satis.csv"

    def test_yalniz_basliqli_fayl_ugurlu_sayilir(self, tmp_path: Path) -> None:
        """Boş gündən sonra ixrac yalnız başlıqla gəlir — bu NORMALDIR."""
        (tmp_path / "satis.csv").write_text(CSV_HEADER + "\n", encoding="utf-8")
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        assert connector.test_connection().ok

    def test_bes_ferqli_nasazliq_bes_ferqli_metn_verir(self, tmp_path: Path) -> None:
        """1c.md tələb 3: hər səbəb AYRICA düzəliş tələb edir."""
        empty = tmp_path / "boş"
        empty.mkdir()
        wrong_columns = tmp_path / "sütunlar"
        wrong_columns.mkdir()
        write_csv(wrong_columns)

        messages = {
            OneCFileExchangeConnector(file_config(str(tmp_path / "yoxdur"), **csv_columns()))
            .test_connection()
            .message,
            OneCFileExchangeConnector(file_config(str(write_csv(tmp_path)), **csv_columns()))
            .test_connection()
            .message,
            OneCFileExchangeConnector(file_config(str(empty), **csv_columns()))
            .test_connection()
            .message,
            OneCFileExchangeConnector(
                file_config(str(wrong_columns), **{**csv_columns(), "amount_column": "Məbləğ"})
            )
            .test_connection()
            .message,
            OneCFileExchangeConnector(file_config(str(tmp_path), file_format="JSON"))
            .test_connection()
            .message,
        }
        assert len(messages) == 5


class TestFileExchangeSales:
    def test_csv_setirleri_senede_cevrilir(self, tmp_path: Path) -> None:
        write_csv(tmp_path)
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        records = connector.fetch_sales(SyncCursor())

        assert [record.document_id for record in records] == ["DOC-1", "DOC-2"]
        # "1 250,50" — 1C-nin regional ixracı (boşluq minlik, vergül onluq).
        assert records[0].gross_amount == Decimal("1250.50")
        assert records[0].store_code == "STORE-01"
        assert records[0].seller_name == "Əliyev Elvin"

    def test_yerli_tarix_sablonu_konfiqurasiya_edilir(self, tmp_path: Path) -> None:
        write_csv(
            tmp_path,
            rows=("DOC-1;15.08.2026 10:30;SELLER-1;STORE-01;100;Əliyev Elvin",),
        )
        columns = {**csv_columns(), "date_format": "%d.%m.%Y %H:%M"}
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        records = connector.fetch_sales(SyncCursor())

        assert records[0].document_at == datetime(2026, 8, 15, 10, 30, tzinfo=UTC)

    def test_bos_setir_xeta_saymir(self, tmp_path: Path) -> None:
        write_csv(
            tmp_path,
            rows=("DOC-1;2026-08-15T10:00:00;SELLER-1;STORE-01;100;Ad", ";;;;;"),
        )
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        assert len(connector.fetch_sales(SyncCursor())) == 1

    def test_sened_id_sutunu_yoxdursa_id_sintez_olunur(self, tmp_path: Path) -> None:
        write_csv(tmp_path)
        columns = {**csv_columns()}
        columns.pop("document_id_column")
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        records = connector.fetch_sales(SyncCursor())

        assert all(record.document_id.startswith(SYNTHETIC_ID_PREFIX) for record in records)

    def test_sintez_id_tekrar_oxumada_eyni_qalir(self, tmp_path: Path) -> None:
        """Eyni fayl iki dəfə oxunanda sətir DUBLİKAT kimi süzülməlidir."""
        write_csv(tmp_path)
        columns = {**csv_columns()}
        columns.pop("document_id_column")
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        first = [record.document_id for record in connector.fetch_sales(SyncCursor())]
        second = [record.document_id for record in connector.fetch_sales(SyncCursor())]

        assert first == second

    def test_eyni_setir_iki_defe_yazilibsa_iki_sened_olur(self, tmp_path: Path) -> None:
        """İki tamamilə eyni satış REALDIR — biri itməməlidir."""
        row = "2026-08-15T10:00:00;SELLER-1;STORE-01;100;Ad"
        (tmp_path / "satis.csv").write_text(
            "\n".join(["Дата;Продавец;Склад;Сумма;Ad", row, row]) + "\n", encoding="utf-8"
        )
        columns = {**csv_columns()}
        columns.pop("document_id_column")
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        records = connector.fetch_sales(SyncCursor())

        assert len({record.document_id for record in records}) == 2

    def test_kursordan_kohne_senedler_suzulur(self, tmp_path: Path) -> None:
        write_csv(tmp_path)
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        records = connector.fetch_sales(
            SyncCursor(last_document_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC))
        )

        assert [record.document_id for record in records] == ["DOC-2"]

    def test_sehife_heddi_gozlenilir(self, tmp_path: Path) -> None:
        write_csv(tmp_path)
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        assert len(connector.fetch_sales(SyncCursor(), page_size=1)) == 1

    def test_emal_olunmus_fayl_novbetinin_qarsisini_kesmir(self, tmp_path: Path) -> None:
        """Səhifə tavanı XAM sətirlə ölçülsəydi, ikinci fayl HEÇ VAXT oxunmazdı.

        Ssenari: birinci fayl artıq emal olunub (kursor ondan sonradır).
        Tavan bir sənəddir. Xam say tavana dərhal çatsaydı, partiya süzgəcdən
        sonra BOŞ qalar, sinxronizasiya "yeni sənəd yoxdur" ilə bitər və
        qovluqdakı ikinci fayl heç vaxt növbəyə çatmazdı.
        """
        first = write_csv(
            tmp_path,
            name="01_kohne.csv",
            rows=("DOC-1;2026-08-15T10:00:00;SELLER-1;STORE-01;100;Ad",),
        )
        second = write_csv(
            tmp_path,
            name="02_yeni.csv",
            rows=("DOC-2;2026-08-15T11:00:00;SELLER-2;STORE-01;200;Ad",),
        )
        # Oxu sırası dəyişmə vaxtına görədir — köhnə fayl birinci olmalıdır.
        os.utime(first, (1_000_000, 1_000_000))
        os.utime(second, (2_000_000, 2_000_000))
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))
        cursor = SyncCursor(
            last_document_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
            boundary_document_ids=frozenset({"DOC-1"}),
        )

        records = connector.fetch_sales(cursor, page_size=1)

        assert [record.document_id for record in records] == ["DOC-2"]

    def test_fayl_silinmir_ve_kocurulmur(self, tmp_path: Path) -> None:
        # Qovluq MÜŞTƏRİNİNDİR — bax modul başlığı.
        path = write_csv(tmp_path)
        before = path.read_text(encoding="utf-8")
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        connector.fetch_sales(SyncCursor())

        assert path.exists()
        assert path.read_text(encoding="utf-8") == before
        # `processed/`, `arxiv/` və s. YARADILMIR — konnektor yalnız OXUYUR.
        assert [item.name for item in tmp_path.glob("*.csv")] == ["satis.csv"]

    def test_yararsiz_meblegh_konkret_xeta_verir(self, tmp_path: Path) -> None:
        write_csv(tmp_path, rows=("DOC-1;2026-08-15T10:00:00;SELLER-1;STORE-01;rəqəm-deyil;Ad",))
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))

        with pytest.raises(Exception, match="rəqəm"):
            connector.fetch_sales(SyncCursor())


class TestFileExchangeXml:
    def test_xml_senedleri_oxunur(self, tmp_path: Path) -> None:
        (tmp_path / "satis.xml").write_text(
            """<?xml version="1.0" encoding="utf-8"?>
            <Satışlar>
              <Документ>
                <Sənəd>DOC-1</Sənəd>
                <Дата>2026-08-15T10:00:00</Дата>
                <Продавец>SELLER-1</Продавец>
                <Склад>STORE-01</Склад>
                <Сумма>150.75</Сумма>
              </Документ>
            </Satışlar>
            """,
            encoding="utf-8",
        )
        columns = {**csv_columns(), "file_format": "XML", "file_pattern": "*.xml"}
        columns.pop("seller_name_column")
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        records = connector.fetch_sales(SyncCursor())

        assert records[0].document_id == "DOC-1"
        assert records[0].gross_amount == Decimal("150.75")

    def test_pozuq_xml_konkret_sebeb_verir(self, tmp_path: Path) -> None:
        (tmp_path / "satis.xml").write_text("<Satışlar><Документ>", encoding="utf-8")
        columns = {**csv_columns(), "file_format": "XML", "file_pattern": "*.xml"}
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        result = connector.test_connection()

        assert not result.ok
        assert "XML" in result.message

    def test_element_adi_uygun_deyilse_ayrica_sebeb_verilir(self, tmp_path: Path) -> None:
        (tmp_path / "satis.xml").write_text(
            "<Satışlar><Sale><Сумма>1</Сумма></Sale></Satışlar>", encoding="utf-8"
        )
        columns = {**csv_columns(), "file_format": "XML", "file_pattern": "*.xml"}
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **columns))

        result = connector.test_connection()

        assert not result.ok
        assert "Документ" in result.message

    def test_xml_defolt_sablonu_avtomatik_secilir(self, tmp_path: Path) -> None:
        settings = FileExchangeSettings.from_config(file_config(str(tmp_path), file_format="XML"))
        assert settings.file_pattern == "*.xml"


# --------------------------------------------------------------------------- #
# 5. Sinxronizasiya dövrü — tipə görə ritm
# --------------------------------------------------------------------------- #


class DueRegistry:
    """`ErpServerRegistry`-nin yalnız `syncable()` hissəsi lazımdır."""

    def __init__(self, servers: list[ErpServer]) -> None:
        self._servers = servers
        self.synced: list[str] = []

    def syncable(self) -> list[ErpServer]:
        return list(self._servers)


class RecordingService:
    def __init__(self, registry: DueRegistry) -> None:
        self._registry = registry

    def sync(self, server: ErpServer, *, now: datetime | None = None) -> Any:
        from src.infrastructure.erp.sync_worker import SyncReport

        self._registry.synced.append(server.server_name)
        return SyncReport(server_id=str(server.id), server_name=server.server_name)


class TestSyncInterval:
    def _manager(self, servers: list[ErpServer]) -> tuple[ErpSyncManager, DueRegistry]:
        registry = DueRegistry(servers)
        manager = ErpSyncManager(
            servers=registry,  # type: ignore[arg-type] — yalnız `syncable` lazımdır
            service_factory=lambda: RecordingService(registry),  # type: ignore[arg-type]
        )
        return manager, registry

    def test_gecelik_fayl_serveri_her_dovrde_oxunmur(self) -> None:
        """1c.md: fayl mübadiləsi «hər gecə bir dəfə» sinxronlaşır."""
        server = make_server(
            server_name="Fayl serveri",
            connector_type=ConnectorType.FILE_EXCHANGE,
            sync_interval_seconds=86_400,
            last_successful_sync=MOMENT,
            port=0,
        )
        manager, registry = self._manager([server])

        manager.run_cycle(now=MOMENT.replace(hour=12, minute=10))

        assert registry.synced == []

    def test_vaxti_catan_server_dovreye_daxil_olur(self) -> None:
        server = make_server(
            server_name="HTTP serveri",
            sync_interval_seconds=300,
            last_successful_sync=MOMENT,
        )
        manager, registry = self._manager([server])

        manager.run_cycle(now=MOMENT.replace(minute=10))

        assert registry.synced == ["HTTP serveri"]

    def test_hec_vaxt_sinxronlasmayan_server_derhal_novbededir(self) -> None:
        # Yeni əlavə edilmiş konfiqurasiya bir gün gözləməməlidir.
        server = make_server(
            server_name="Yeni fayl serveri",
            connector_type=ConnectorType.FILE_EXCHANGE,
            sync_interval_seconds=86_400,
            last_successful_sync=None,
            port=0,
        )
        manager, registry = self._manager([server])

        manager.run_cycle(now=MOMENT)

        assert registry.synced == ["Yeni fayl serveri"]

    def test_force_gozleme_muddetini_yan_kecir(self) -> None:
        """«İndi sinxronlaşdır» istifadəçinin şüurlu tələbidir."""
        server = make_server(
            server_name="Fayl serveri",
            connector_type=ConnectorType.FILE_EXCHANGE,
            sync_interval_seconds=86_400,
            last_successful_sync=MOMENT,
            port=0,
        )
        manager, registry = self._manager([server])

        manager.run_cycle(now=MOMENT.replace(minute=10), force=True)

        assert registry.synced == ["Fayl serveri"]

    def test_muxtelif_tipli_serverler_eyni_kirayecide_yasaya_bilir(self) -> None:
        """Bir mağaza HTTP, digəri FILE — dövr hər ikisini öz ritmi ilə oxuyur."""
        http_server = make_server(
            server_name="HTTP", sync_interval_seconds=300, last_successful_sync=MOMENT
        )
        file_server = make_server(
            id=SERVER_B,
            server_name="Fayl",
            connector_type=ConnectorType.FILE_EXCHANGE,
            sync_interval_seconds=86_400,
            last_successful_sync=MOMENT,
            port=0,
        )
        manager, registry = self._manager([http_server, file_server])

        manager.run_cycle(now=MOMENT.replace(minute=10))

        assert registry.synced == ["HTTP"]


# --------------------------------------------------------------------------- #
# 6. Sağlamlıq monitoru — tipə görə diaqnoz
# --------------------------------------------------------------------------- #


def health_row(health: ServerHealth, **overrides: Any) -> ServerHealthRow:
    defaults: dict[str, Any] = {
        "server_id": str(SERVER_A),
        "server_name": "Bellona — Bakı",
        "host": "10.0.0.5",
        "health": health,
        "status": "ACTIVE",
        "consecutive_failures": 0,
        "mapped_stores": 2,
        "sync_interval_seconds": 300,
        "port": 8080,
    }
    return ServerHealthRow(**{**defaults, **overrides})


class TestHealthByConnectorType:
    def test_fayl_serverine_sebeke_meslehet_verilmir(self) -> None:
        row = health_row(
            ServerHealth.STALE,
            connector_type=ConnectorType.FILE_EXCHANGE,
            host="\\\\anbar\\exchange",
            port=0,
        )
        assert "ixrac" in row.diagnosis
        assert "şəbəkə" not in row.diagnosis.lower()

    def test_com_serverinde_platforma_teklif_olunur(self) -> None:
        row = health_row(ServerHealth.STALE, connector_type=ConnectorType.COM, port=0)
        assert "1C platformasının" in row.diagnosis

    def test_http_diaqnozu_deyismir(self) -> None:
        # Mövcud davranış qorunur (reqressiya qapısı).
        assert "şəbəkə" in health_row(ServerHealth.STALE).diagnosis.lower()

    def test_ardicil_xetanin_sebebi_de_tipe_gore_ferqlenir(self) -> None:
        files = health_row(
            ServerHealth.DEGRADED,
            consecutive_failures=3,
            connector_type=ConnectorType.FILE_EXCHANGE,
        )
        http = health_row(ServerHealth.DEGRADED, consecutive_failures=3)
        assert "3" in files.diagnosis
        assert files.diagnosis != http.diagnosis
        assert "qovluğ" in files.diagnosis.lower()

    def test_unvan_fayl_serverinde_portsuzdur(self) -> None:
        row = health_row(
            ServerHealth.HEALTHY,
            connector_type=ConnectorType.FILE_EXCHANGE,
            host="\\\\anbar\\exchange",
            port=0,
        )
        assert row.address == "\\\\anbar\\exchange"
        assert health_row(ServerHealth.HEALTHY).address == "10.0.0.5:8080"

    def test_gecikmenin_menasi_setirden_oxunur(self) -> None:
        row = health_row(ServerHealth.HEALTHY, connector_type=ConnectorType.FILE_EXCHANGE, port=0)
        assert row.latency_meaning_az == "Qovluğun oxunma müddəti"


# --------------------------------------------------------------------------- #
# 7. Sihirbaz — tipə bağlı qaydalar
# --------------------------------------------------------------------------- #


class WizardRegistry:
    def __init__(self, servers: list[ErpServer]) -> None:
        self._servers = {server.id: server for server in servers}
        self.created: list[ErpServerDraft] = []
        self.status_changes: list[tuple[ErpServerId, ErpServerStatus]] = []

    def require(self, server_id: ErpServerId) -> ErpServer:
        return self._servers[server_id]

    def list_all(self) -> list[ErpServer]:
        return list(self._servers.values())

    def syncable(self) -> list[ErpServer]:
        return [server for server in self._servers.values() if server.is_syncable]

    def create(
        self, draft: ErpServerDraft, *, created_by: Any = None, activate: bool = True
    ) -> ErpServer:
        self.created.append(draft)
        server = make_server(server_name=draft.server_name, host=draft.host)
        self._servers[server.id] = server
        return server

    def update(
        self,
        server_id: ErpServerId,
        draft: ErpServerDraft,
        *,
        updated_by: Any = None,
        backup_previous: bool = True,
    ) -> ErpServer:
        return self._servers[server_id]

    def set_status(
        self,
        server_id: ErpServerId,
        status: ErpServerStatus,
        *,
        changed_by: Any = None,
        reason: str | None = None,
    ) -> None:
        self.status_changes.append((server_id, status))

    def rollback(self, server_id: ErpServerId, *, actor_id: Any = None) -> ErpServer:
        return self._servers[server_id]

    def mark_sync_started(self, server_id: ErpServerId, *, now: datetime | None = None) -> None:
        return None

    def record_success(self, server_id: ErpServerId, cursor: Any, *, now: Any = None) -> None:
        return None

    def record_failure(self, server_id: ErpServerId, message: str, *, now: Any = None) -> None:
        return None


class PassingConnector:
    def test_connection(self) -> Any:
        from src.domain.value_objects.erp import ConnectionTestResult

        return ConnectionTestResult(ok=True, message="uğurlu")

    def fetch_sales(self, cursor: Any, *, page_size: int = 500) -> list[Any]:
        return []

    def close(self) -> None:
        return None


class PassingFactory:
    def for_draft(self, draft: ErpServerDraft) -> PassingConnector:
        return PassingConnector()

    def for_server(self, server_id: ErpServerId) -> PassingConnector:
        return PassingConnector()


class TestMatchingIsTransportAgnostic:
    """Uyğunlaşma qaydası ÜÇ tipdə də eynidir (1c.md: ortaq interfeys).

    `SalesMatcher` `OneCSaleRecord` ilə işləyir — sənədin HANSI yolla gəldiyini
    bilmir. Fayl mübadiləsində «1C Unikal Satıcı ID» sütunu OLMAYA BİLƏR; bu
    halda composite açarın birinci hissəsi boş qalır və qayda dəyişmədən
    ad-fallback-a düşür, yəni sətir «Şübhəli Uyğunlaşma» növbəsinə gedir.
    """

    def _matcher(self, staff: list[tuple[EmployeeId, str]]) -> Any:
        from src.infrastructure.erp.matching import SalesMatcher

        class Directory:
            def store_for(self, server_id: ErpServerId, store_code: str) -> StoreId | None:
                return STORE_A if store_code == "STORE-01" else None

            def employee_by_seller_id(self, store_id: StoreId, seller_id: str) -> None:
                return None

            def employees_in_store(self, store_id: StoreId) -> list[tuple[EmployeeId, str]]:
                return staff

        return SalesMatcher(Directory())

    def test_satici_id_sutunu_olmayan_fayl_ad_ile_uygunlasir(self, tmp_path: Path) -> None:
        from src.domain.value_objects.erp import MatchConfidence

        write_csv(tmp_path, rows=("DOC-1;2026-08-15T10:00:00;;STORE-01;100;Aliyev Elvin",))
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))
        record = connector.fetch_sales(SyncCursor())[0]
        elvin = EmployeeId(uuid.uuid4())

        result = self._matcher([(elvin, "Əliyev Elvin")]).match(record, SERVER_A)

        assert record.seller_id == ""
        assert result.confidence is MatchConfidence.LOW_CONFIDENCE_MATCH
        assert result.confidence.needs_review
        assert result.employee_id == elvin

    def test_ne_id_ne_ad_varsa_novbeye_dusur(self, tmp_path: Path) -> None:
        from src.domain.value_objects.erp import MatchConfidence

        write_csv(tmp_path, rows=("DOC-1;2026-08-15T10:00:00;;STORE-01;100;",))
        connector = OneCFileExchangeConnector(file_config(str(tmp_path), **csv_columns()))
        record = connector.fetch_sales(SyncCursor())[0]

        result = self._matcher([(EmployeeId(uuid.uuid4()), "Əliyev Elvin")]).match(record, SERVER_A)

        assert result.confidence is MatchConfidence.UNASSIGNED
        assert result.confidence.needs_review


class TestMigrationContract:
    """SQL qaydaları ilə domen qaydalarının PARİTETİ (CLAUDE.md bölmə 5).

    Hər qayda İKİ yerdədir — domen (istifadəçiyə mesaj) və DB (ekranı yan
    keçən skript). Aşağıdakı yoxlamalar SQL tərəfin sürüşməsini tutur.
    """

    def _migration(self) -> str:
        from pathlib import Path as _Path

        path = (
            _Path(__file__).resolve().parents[2]
            / "database"
            / "migrations"
            / "050_erp_pluggable_connectors.sql"
        )
        assert path.exists(), "migrations/050 tapılmadı"
        return path.read_text(encoding="utf-8")

    def test_mevcud_setirler_http_defoltu_alir(self) -> None:
        assert "connector_type TEXT NOT NULL DEFAULT 'HTTP'" in self._migration()

    def test_check_domen_enum_u_ile_eyni_uc_deyeri_saxlayir(self) -> None:
        sql = self._migration()
        for value in (tip.value for tip in ConnectorType):
            assert f"'{value}'" in sql

    def test_konfiqurasiya_sutunu_sifreli_adla_gelir(self) -> None:
        # Ad `_encrypted` ilə bitməsəydi, növbəti inkişafçı ora açıq JSON
        # yazardı (SEC-013).
        assert "connector_config_encrypted TEXT" in self._migration()

    def test_port_sentineli_check_ile_mecburidir(self) -> None:
        sql = self._migration()
        assert "chk_erp_port_matches_connector_type" in sql
        assert "connector_type <> 'HTTP' AND port = 0" in sql

    def test_aktivlesme_qapisi_fayl_mubadilesini_nezere_alir(self) -> None:
        sql = self._migration()
        assert "chk_erp_active_requires_config" in sql
        assert "connector_type = 'FILE_EXCHANGE' AND length(trim(host)) > 0" in sql

    def test_saglamliq_gorunusu_tipi_ve_portu_verir(self) -> None:
        sql = self._migration()
        assert "s.connector_type" in sql
        assert "s.port" in sql
        # Görünüş RLS-i yan keçməməlidir (migrations/004 ilə eyni qayda).
        assert "security_invoker = true" in sql

    def test_root_parametri_seed_edilir(self) -> None:
        sql = self._migration()
        assert SystemLimitKey.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS.value in sql
        # Yeni kirayəçi də EYNİ sətri almalıdır.
        assert "seed_erp_connector_limits_for_new_tenant" in sql


class TestWizardConnectorRules:
    def _wizard(
        self, registry: WizardRegistry, limits: FakeSystemLimits | None = None
    ) -> ErpConnectionWizardUseCase:
        return ErpConnectionWizardUseCase(
            servers=registry,  # type: ignore[arg-type]
            connectors=PassingFactory(),  # type: ignore[arg-type]
            audit=RecordingAudit(),
            limits=limits,  # type: ignore[arg-type]
        )

    def test_fayl_serverinin_dovru_root_dan_gelir(self) -> None:
        registry = WizardRegistry([])
        limits = FakeSystemLimits()
        limits.set(SystemLimitKey.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS, "43200")
        wizard = self._wizard(registry, limits)

        wizard.save_new(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
            draft=make_draft(
                connector_type=ConnectorType.FILE_EXCHANGE, host="\\\\srv\\exchange", infobase=""
            ),
            now=MOMENT,
        )

        assert registry.created[0].sync_interval_seconds == 43_200

    def test_root_dan_gelen_deyer_db_heddinden_asagi_dusmur(self) -> None:
        registry = WizardRegistry([])
        limits = FakeSystemLimits()
        limits.set(SystemLimitKey.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS, "5")
        wizard = self._wizard(registry, limits)

        wizard.save_new(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
            draft=make_draft(
                connector_type=ConnectorType.FILE_EXCHANGE, host="\\\\srv\\exchange", infobase=""
            ),
            now=MOMENT,
        )

        assert registry.created[0].effective_sync_interval_seconds == 30

    def test_http_serveri_root_parametrini_oxumur(self) -> None:
        registry = WizardRegistry([])
        limits = FakeSystemLimits()
        limits.set(SystemLimitKey.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS, "43200")
        wizard = self._wizard(registry, limits)

        wizard.save_new(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG), draft=make_draft(), now=MOMENT
        )

        assert registry.created[0].sync_interval_seconds == DEFAULT_SYNC_INTERVAL_SECONDS

    def test_limit_portu_yoxdursa_domen_defoltu_isleyir(self) -> None:
        # Server əlavə etmək `system_limits` sətrinin mövcudluğundan ASILI
        # OLMAMALIDIR.
        registry = WizardRegistry([])
        wizard = self._wizard(registry)

        wizard.save_new(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
            draft=make_draft(
                connector_type=ConnectorType.FILE_EXCHANGE, host="\\\\srv\\exchange", infobase=""
            ),
            now=MOMENT,
        )

        assert registry.created[0].sync_interval_seconds == FILE_EXCHANGE_SYNC_INTERVAL_SECONDS

    def test_fayl_serveri_infobase_olmadan_aktivlesir(self) -> None:
        """Köhnə qayda saxlansaydı fayl serveri HEÇ VAXT aktivləşməzdi."""
        registry = WizardRegistry(
            [
                make_server(
                    connector_type=ConnectorType.FILE_EXCHANGE,
                    host="\\\\srv\\exchange",
                    port=0,
                    infobase="",
                )
            ]
        )
        wizard = self._wizard(registry)

        wizard.set_status(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
            server_id=SERVER_A,
            status=ErpServerStatus.ACTIVE,
            now=MOMENT,
        )

        assert registry.status_changes == [(SERVER_A, ErpServerStatus.ACTIVE)]

    def test_qovluqsuz_fayl_serveri_aktivlesmir(self) -> None:
        registry = WizardRegistry(
            [
                make_server(
                    connector_type=ConnectorType.FILE_EXCHANGE, host="   ", port=0, infobase=""
                )
            ]
        )
        wizard = self._wizard(registry)

        with pytest.raises(ErpConnectionError, match="qovluğ"):
            wizard.set_status(
                actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
                server_id=SERVER_A,
                status=ErpServerStatus.ACTIVE,
                now=MOMENT,
            )
        assert registry.status_changes == []

    def test_http_serverinde_infobase_qapisi_deyismir(self) -> None:
        # Mövcud davranışın reqressiya qapısı.
        registry = WizardRegistry([make_server(infobase="  ")])
        wizard = self._wizard(registry)

        with pytest.raises(ErpConnectionError):
            wizard.set_status(
                actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
                server_id=SERVER_A,
                status=ErpServerStatus.ACTIVE,
                now=MOMENT,
            )

    def test_com_serverinde_de_infobase_teleb_olunur(self) -> None:
        registry = WizardRegistry(
            [make_server(connector_type=ConnectorType.COM, port=0, infobase="")]
        )
        wizard = self._wizard(registry)

        with pytest.raises(ErpConnectionError, match="infobase"):
            wizard.set_status(
                actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
                server_id=SERVER_A,
                status=ErpServerStatus.ACTIVE,
                now=MOMENT,
            )
