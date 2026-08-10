"""Çoxsaylı 1C konnektoru, uyğunlaşma və sync worker testləri (Faza 3.10).

Spesifikasiyanın bölmə 6 və 7 tələbləri burada yoxlanılır:
    * composite matching + ad-fallback → LOW_CONFIDENCE_MATCH növbəsi,
    * kursorun sərhəd saniyəsində nə atlaması, nə də təkrar emalı,
    * `[Bağlantını Test Et]` olmadan konfiqurasiyanın aktivləşməməsi,
    * bir serverin xətasının digərlərini DAYANDIRMAMASI,
    * konfiqurasiya backup-ı və bir kliklə geri qaytarma.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from src.application.use_cases.erp_connection import (
    MANAGE_ERP_SERVERS_FLAG,
    ConnectionNotVerifiedError,
    ErpConnectionError,
    ErpConnectionWizardUseCase,
)
from src.domain.entities import Employee, Position
from src.domain.value_objects import PermissionFlag, SystemRole, Username
from src.domain.value_objects.erp import (
    ConnectionTestResult,
    ErpAuthenticationError,
    ErpError,
    ErpProtocolError,
    ErpServer,
    ErpServerDraft,
    ErpServerStatus,
    MatchConfidence,
    OneCDocumentMapping,
    OneCSaleRecord,
    SyncCursor,
)
from src.domain.value_objects.erp import (
    ErpConnectionError as ErpTransportError,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ErpServerId,
    PositionId,
    StoreId,
    TenantId,
)
from src.infrastructure.erp.health import ServerHealth, ServerHealthRow
from src.infrastructure.erp.matching import SalesMatcher, name_similarity, normalize_name
from src.infrastructure.erp.one_c_connector import OneCConnector, OneCServerConfig
from src.infrastructure.erp.sync_worker import ErpSyncManager, SalesSyncService

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
SERVER_A = ErpServerId(uuid.uuid4())
SERVER_B = ErpServerId(uuid.uuid4())
STORE_A = StoreId(uuid.uuid4())
ELVIN = EmployeeId(uuid.uuid4())
ELNUR = EmployeeId(uuid.uuid4())

MOMENT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def make_config(**overrides: Any) -> OneCServerConfig:
    defaults: dict[str, Any] = {
        "host": "10.0.0.5",
        "port": 8080,
        "username": "kompasos",
        "password": "s3cret",
        "infobase": "trade",
    }
    return OneCServerConfig(**{**defaults, **overrides})


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


def make_record(
    document_id: str,
    *,
    seller_id: str = "SELLER-1",
    store_code: str = "STORE-01",
    amount: str = "100.00",
    at: datetime = MOMENT,
    seller_name: str | None = None,
) -> OneCSaleRecord:
    return OneCSaleRecord(
        document_id=document_id,
        seller_id=seller_id,
        store_code=store_code,
        gross_amount=Decimal(amount),
        document_at=at,
        seller_name=seller_name,
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


# --------------------------------------------------------------------------- #
# Value object-lər: kursor və sənəd
# --------------------------------------------------------------------------- #


class TestSaleRecord:
    def test_bos_sened_id_redd_edilir(self) -> None:
        # Sənəd ID-si təkrar yükləmənin YEGANƏ qarşısını alan sahədir.
        with pytest.raises(ErpProtocolError):
            make_record("   ")

    def test_menfi_mebleg_redd_edilir(self) -> None:
        with pytest.raises(ErpProtocolError):
            make_record("DOC-1", amount="-5")

    def test_transaction_date_sened_vaxtindan_alinir(self) -> None:
        record = make_record("DOC-1", at=datetime(2026, 3, 14, 23, 45, tzinfo=UTC))
        assert record.transaction_date.isoformat() == "2026-03-14"


class TestSyncCursor:
    def test_ilk_kursor_bosdur(self) -> None:
        assert SyncCursor().is_initial

    def test_kursor_en_yeni_vaxta_irelileyir(self) -> None:
        early = make_record("A", at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
        late = make_record("B", at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC))
        cursor = SyncCursor().advanced([early, late])
        assert cursor.last_document_at == late.document_at
        assert cursor.boundary_document_ids == frozenset({"B"})

    def test_eyni_saniyedeki_senedlerin_hamisi_serhedde_saxlanilir(self) -> None:
        same = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
        cursor = SyncCursor().advanced([make_record("A", at=same), make_record("B", at=same)])
        assert cursor.boundary_document_ids == frozenset({"A", "B"})

    def test_serhedde_qalanda_evvelki_idler_unudulmur(self) -> None:
        # Bu unudulsaydı, `>=` filtri sərhəd sənədlərini hər dövrdə təkrar
        # emal edərdi.
        same = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
        first = SyncCursor().advanced([make_record("A", at=same)])
        second = first.advanced([make_record("B", at=same)])
        assert second.boundary_document_ids == frozenset({"A", "B"})

    def test_bos_partiya_kursoru_deyismir(self) -> None:
        original = SyncCursor().advanced([make_record("A")])
        assert original.advanced([]).last_document_at == original.last_document_at

    def test_already_seen_yalniz_serhed_saniyesine_aiddir(self) -> None:
        same = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
        cursor = SyncCursor().advanced([make_record("A", at=same)])
        assert cursor.already_seen(make_record("A", at=same))
        # Eyni ID, FƏRQLİ vaxt — bu, başqa sənəddir.
        assert not cursor.already_seen(make_record("A", at=datetime(2026, 8, 1, 11, 0, tzinfo=UTC)))


class TestDocumentMapping:
    def test_defolt_sahaler_select_e_dusur(self) -> None:
        fields = OneCDocumentMapping().selected_fields()
        assert "Ref_Key" in fields
        assert "Date" in fields

    def test_namelum_sahe_sukutla_atilmir(self) -> None:
        with pytest.raises(ErpError):
            OneCDocumentMapping.from_dict({"entity_name": "X", "nə_bu": "?"})

    def test_bos_konfiqurasiya_defolt_qaytarir(self) -> None:
        assert OneCDocumentMapping.from_dict(None) == OneCDocumentMapping()


# --------------------------------------------------------------------------- #
# OData klienti
# --------------------------------------------------------------------------- #


def odata_client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def sale_row(ref: str, *, date_text: str = "2026-08-09T12:00:00", amount: str = "100") -> dict:
    return {
        "Ref_Key": ref,
        "Date": date_text,
        "Otvetstvennyj_Key": "SELLER-1",
        "Sklad_Key": "STORE-01",
        "SummaDokumenta": amount,
        "Otvetstvennyj": "Aliyev Elvin",
    }


class TestOneCConnector:
    def test_ugurlu_test_baglantisi(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "trade/odata/standard.odata" in str(request.url)
            return httpx.Response(200, json={"value": []})

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        result = connector.test_connection()
        assert result.ok
        assert result.entity_verified == OneCDocumentMapping().entity_name

    def test_html_cavab_infobase_sehvini_gosterir(self) -> None:
        # Ən çox rast gəlinən nasazlıq: baza adı səhvdir, veb-server 200 ilə
        # HTML qaytarır. Bu, "qoşuldu, məlumat yoxdur" kimi görünməməlidir.
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>404 Not Found</html>")

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        result = connector.test_connection()
        assert not result.ok
        assert "baza" in result.message.lower() or "infobase" in result.message.lower()

    def test_401_tekrar_cehd_etmir(self) -> None:
        calls: list[int] = []

        def handler(_: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(401)

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        with pytest.raises(ErpAuthenticationError):
            connector.fetch_sales(SyncCursor())
        # Credential dəyişmir — təkrar cəhd yalnız 1C-də hesabı bloklayardı.
        assert len(calls) == 1

    def test_503_eksponensial_gozleme_ile_tekrarlanir(self) -> None:
        attempts: list[int] = []
        delays: list[float] = []

        def handler(_: httpx.Request) -> httpx.Response:
            attempts.append(1)
            if len(attempts) < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"value": [sale_row("DOC-1")]})

        connector = OneCConnector(
            make_config(), transport=odata_client(handler), sleep=delays.append
        )
        records = connector.fetch_sales(SyncCursor())
        assert len(records) == 1
        assert delays == [1, 2]

    def test_filtr_yalniz_kecirilmis_senedleri_isteyir(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json={"value": []})

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        connector.fetch_sales(SyncCursor())
        assert "Posted eq true" in captured["$filter"]

    def test_kursor_verilende_filtr_ge_istifade_edir(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json={"value": []})

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        connector.fetch_sales(SyncCursor(last_document_at=MOMENT))
        # `gt` olsaydı eyni saniyədəki digər çeklər həmişəlik atlanardı.
        assert "Date ge datetime'2026-08-09T12:00:00'" in captured["$filter"]

    def test_serhed_senedleri_tekrar_qaytarilmir(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": [sale_row("DOC-1"), sale_row("DOC-2")]})

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        cursor = SyncCursor(
            last_document_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
            boundary_document_ids=frozenset({"DOC-1"}),
        )
        records = connector.fetch_sales(cursor)
        assert [record.document_id for record in records] == ["DOC-2"]

    def test_id_siz_sened_atlanir_qalanlari_emal_olunur(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            broken = sale_row("")
            return httpx.Response(200, json={"value": [broken, sale_row("DOC-9")]})

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        records = connector.fetch_sales(SyncCursor())
        assert [record.document_id for record in records] == ["DOC-9"]

    def test_sifre_repr_de_gorunmur(self) -> None:
        # Konfiqurasiya xəta konteksti ilə log-a düşə bilər (SEC-013).
        assert "s3cret" not in repr(make_config())
        assert "s3cret" not in repr(make_draft())

    def test_baglanti_xetasi_texniki_olmayan_mesaj_verir(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        connector = OneCConnector(make_config(), transport=odata_client(handler))
        with pytest.raises(ErpTransportError) as exc_info:
            connector.fetch_sales(SyncCursor())
        assert "qoşulmaq" in exc_info.value.user_message


# --------------------------------------------------------------------------- #
# Ad normalizasiyası və uyğunlaşma
# --------------------------------------------------------------------------- #


class TestNameMatching:
    def test_pasport_transliterasiyasi_eyni_ada_getirir(self) -> None:
        # 1C-də adlar rus/pasport sənədləşməsindən gəlir: Əliyev = Aliyev.
        assert normalize_name("Əliyev Elvin") == normalize_name("Aliyev Elvin")

    def test_nadir_e_yazilisi_da_hedd_kecir(self) -> None:
        # "Eliyev" nadir formadır — bir simvol fərqi həddi (0.87) keçir.
        assert name_similarity("Əliyev Elvin", "Eliyev Elvin") >= 0.87

    def test_soz_sirasi_neticeye_tesir_etmir(self) -> None:
        assert name_similarity("Elvin Əliyev", "Əliyev Elvin") == 1.0

    def test_qohum_adlar_tam_uygun_deyil(self) -> None:
        # "Elvin" ↔ "Elnur" fərqli adamlardır — 1.0 OLMAMALIDIR.
        assert name_similarity("Əliyev Elvin", "Əliyev Elnur") < 1.0


class FakeDirectory:
    """`MatchDirectory` protokolunun test əvəzi."""

    def __init__(
        self,
        *,
        stores: dict[tuple[str, str], StoreId] | None = None,
        sellers: dict[tuple[str, str], EmployeeId] | None = None,
        staff: dict[str, list[tuple[EmployeeId, str]]] | None = None,
    ) -> None:
        self.stores = stores or {}
        self.sellers = sellers or {}
        self.staff = staff or {}

    def store_for(self, server_id: ErpServerId, store_code: str) -> StoreId | None:
        return self.stores.get((str(server_id), store_code))

    def employee_by_seller_id(self, store_id: StoreId, seller_id: str) -> EmployeeId | None:
        return self.sellers.get((str(store_id), seller_id))

    def employees_in_store(self, store_id: StoreId) -> Sequence[tuple[EmployeeId, str]]:
        return self.staff.get(str(store_id), [])


class TestSalesMatcher:
    def test_xeritelenmemis_magaza_unassigned(self) -> None:
        matcher = SalesMatcher(FakeDirectory())
        result = matcher.match(make_record("DOC-1"), SERVER_A)
        assert result.confidence is MatchConfidence.UNASSIGNED
        assert "mağaza kodu" in result.reason

    def test_satici_id_uzre_deqiq_uygunluq(self) -> None:
        directory = FakeDirectory(
            stores={(str(SERVER_A), "STORE-01"): STORE_A},
            sellers={(str(STORE_A), "SELLER-1"): ELVIN},
        )
        result = SalesMatcher(directory).match(make_record("DOC-1"), SERVER_A)
        assert result.confidence is MatchConfidence.EXACT_MATCH
        assert result.employee_id == ELVIN

    def test_ad_fallback_low_confidence_verir(self) -> None:
        directory = FakeDirectory(
            stores={(str(SERVER_A), "STORE-01"): STORE_A},
            staff={str(STORE_A): [(ELVIN, "Əliyev Elvin")]},
        )
        record = make_record("DOC-1", seller_id="NAMƏLUM", seller_name="Aliyev Elvin")
        result = SalesMatcher(directory).match(record, SERVER_A)
        assert result.confidence is MatchConfidence.LOW_CONFIDENCE_MATCH
        assert result.employee_id == ELVIN
        assert result.confidence.needs_review

    def test_eyni_adli_iki_isci_secilmir(self) -> None:
        # 21 filiallı şəbəkədə eyni ad-soyad real haldır. Təxmin etmək boş
        # buraxmaqdan bahadır: səhv uyğunlaşma bir işçinin satışını
        # digərinin premiyasına yazır.
        directory = FakeDirectory(
            stores={(str(SERVER_A), "STORE-01"): STORE_A},
            staff={str(STORE_A): [(ELVIN, "Əliyev Elvin"), (ELNUR, "Əliyev Elvin")]},
        )
        record = make_record("DOC-1", seller_id="X", seller_name="Əliyev Elvin")
        result = SalesMatcher(directory).match(record, SERVER_A)
        assert result.confidence is MatchConfidence.UNASSIGNED
        assert result.employee_id is None
        assert "əl ilə" in result.reason

    def test_yazi_sehvi_tutulur_amma_tesdiqe_gonderilir(self) -> None:
        # Bir hərf səhvi (Elvun/Elvin) ən yaxın namizədi seçir, lakin nəticə
        # LOW_CONFIDENCE olduğu üçün insan nəzərdən keçirməsinə düşür.
        directory = FakeDirectory(
            stores={(str(SERVER_A), "STORE-01"): STORE_A},
            staff={str(STORE_A): [(ELVIN, "Əliyev Elvin"), (ELNUR, "Məmmədov Ramin")]},
        )
        record = make_record("DOC-1", seller_id="X", seller_name="Əliyev Elvun")
        result = SalesMatcher(directory).match(record, SERVER_A)
        assert result.confidence is MatchConfidence.LOW_CONFIDENCE_MATCH
        assert result.employee_id == ELVIN

    def test_zeif_oxsarliq_qebul_edilmir(self) -> None:
        directory = FakeDirectory(
            stores={(str(SERVER_A), "STORE-01"): STORE_A},
            staff={str(STORE_A): [(ELVIN, "Məmmədov Ramin")]},
        )
        record = make_record("DOC-1", seller_id="X", seller_name="Aliyev Elvin")
        result = SalesMatcher(directory).match(record, SERVER_A)
        assert result.confidence is MatchConfidence.UNASSIGNED

    def test_ad_yoxdursa_unassigned(self) -> None:
        directory = FakeDirectory(stores={(str(SERVER_A), "STORE-01"): STORE_A})
        result = SalesMatcher(directory).match(make_record("DOC-1"), SERVER_A)
        assert result.confidence is MatchConfidence.UNASSIGNED
        assert result.store_id == STORE_A

    def test_low_confidence_xal_qazandirir_unassigned_qazandirmir(self) -> None:
        assert MatchConfidence.LOW_CONFIDENCE_MATCH.awards_points
        assert not MatchConfidence.UNASSIGNED.awards_points


# --------------------------------------------------------------------------- #
# Sync worker
# --------------------------------------------------------------------------- #


class FakeConnector:
    """Əvvəlcədən proqramlaşdırılmış səhifələr qaytaran konnektor."""

    def __init__(
        self, pages: list[list[OneCSaleRecord]] | None = None, *, error: Exception | None = None
    ) -> None:
        self._pages = list(pages or [])
        self._error = error
        self.closed = False

    def test_connection(self) -> ConnectionTestResult:
        if self._error is not None:
            return ConnectionTestResult(ok=False, message="uğursuz", detail=str(self._error))
        return ConnectionTestResult(ok=True, message="uğurlu")

    def fetch_sales(self, cursor: SyncCursor, *, page_size: int = 500) -> list[OneCSaleRecord]:
        if self._error is not None:
            raise self._error
        return self._pages.pop(0) if self._pages else []

    def close(self) -> None:
        self.closed = True


class FakeRegistry:
    """`ErpServerRegistry` protokolunun test əvəzi."""

    def __init__(self, servers: list[ErpServer]) -> None:
        self._servers = {server.id: server for server in servers}
        self.successes: list[tuple[ErpServerId, SyncCursor]] = []
        self.failures: list[tuple[ErpServerId, str]] = []
        self.started: list[ErpServerId] = []
        self.status_changes: list[tuple[ErpServerId, ErpServerStatus]] = []
        self.created: list[ErpServerDraft] = []
        self.updated: list[tuple[ErpServerId, ErpServerDraft, bool]] = []
        self.rollbacks: list[ErpServerId] = []

    def require(self, server_id: ErpServerId) -> ErpServer:
        return self._servers[server_id]

    def list_all(self) -> list[ErpServer]:
        return list(self._servers.values())

    def syncable(self) -> list[ErpServer]:
        return [server for server in self._servers.values() if server.is_syncable]

    def create(
        self,
        draft: ErpServerDraft,
        *,
        created_by: EmployeeId | None = None,
        activate: bool = True,
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
        updated_by: EmployeeId | None = None,
        backup_previous: bool = True,
    ) -> ErpServer:
        self.updated.append((server_id, draft, backup_previous))
        server = make_server(id=server_id, server_name=draft.server_name, host=draft.host)
        self._servers[server_id] = server
        return server

    def set_status(
        self,
        server_id: ErpServerId,
        status: ErpServerStatus,
        *,
        changed_by: EmployeeId | None = None,
        reason: str | None = None,
    ) -> None:
        self.status_changes.append((server_id, status))

    def rollback(self, server_id: ErpServerId, *, actor_id: EmployeeId | None = None) -> ErpServer:
        self.rollbacks.append(server_id)
        return self._servers[server_id]

    def mark_sync_started(self, server_id: ErpServerId, *, now: datetime | None = None) -> None:
        self.started.append(server_id)

    def record_success(
        self, server_id: ErpServerId, cursor: SyncCursor, *, now: datetime | None = None
    ) -> None:
        self.successes.append((server_id, cursor))

    def record_failure(
        self, server_id: ErpServerId, message: str, *, now: datetime | None = None
    ) -> None:
        self.failures.append((server_id, message))


class FakeConnectorFactory:
    def __init__(self, connectors: dict[ErpServerId, FakeConnector] | None = None) -> None:
        self._connectors = connectors or {}
        self.draft_connector = FakeConnector()

    def for_draft(self, draft: ErpServerDraft) -> FakeConnector:
        return self.draft_connector

    def for_server(self, server_id: ErpServerId) -> FakeConnector:
        return self._connectors.setdefault(server_id, FakeConnector())


class FakeSales:
    def __init__(self, *, already_present: set[str] | None = None) -> None:
        self.rows: list[Any] = []
        self._present = already_present or set()

    def insert_batch(self, server_id: ErpServerId, results: Sequence[Any]) -> int:
        return len(self.insert_batch_returning(server_id, results))

    def insert_batch_returning(
        self, server_id: ErpServerId, results: Sequence[Any]
    ) -> list[tuple[uuid.UUID, Any]]:
        """Xal yalnız FAKTİKİ yazılmış sətrə verilir — ID-lər qaytarılır."""
        fresh = [r for r in results if r.record.document_id not in self._present]
        self.rows.extend(fresh)
        self._present.update(r.record.document_id for r in fresh)
        return [(uuid.uuid4(), r) for r in fresh]


def build_service(
    registry: FakeRegistry,
    connectors: FakeConnectorFactory,
    sales: FakeSales,
    directory: FakeDirectory | None = None,
    **kwargs: Any,
) -> SalesSyncService:
    return SalesSyncService(
        servers=registry,
        connectors=connectors,
        sales=sales,
        directory=directory or FakeDirectory(),
        **kwargs,
    )


class TestSalesSyncService:
    def test_senedler_yazilir_ve_kursor_irelileyir(self) -> None:
        server = make_server()
        registry = FakeRegistry([server])
        connector = FakeConnector([[make_record("DOC-1"), make_record("DOC-2")]])
        connectors = FakeConnectorFactory({SERVER_A: connector})
        sales = FakeSales()

        report = build_service(registry, connectors, sales).sync(server, now=MOMENT)

        assert report.ok
        assert report.fetched == 2
        assert report.inserted == 2
        assert registry.started == [SERVER_A]
        assert registry.successes[-1][1].last_document_at == MOMENT
        assert connector.closed

    def test_tekrar_sened_duplicate_kimi_sayilir(self) -> None:
        server = make_server()
        registry = FakeRegistry([server])
        connectors = FakeConnectorFactory({SERVER_A: FakeConnector([[make_record("DOC-1")]])})
        sales = FakeSales(already_present={"DOC-1"})

        report = build_service(registry, connectors, sales).sync(server, now=MOMENT)

        assert report.inserted == 0
        assert report.duplicates == 1

    def test_bir_nece_sehife_oxunur(self) -> None:
        server = make_server()
        registry = FakeRegistry([server])
        pages = [
            [
                make_record("A", at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC)),
                make_record("B", at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC)),
            ],
            [make_record("C", at=datetime(2026, 8, 1, 11, 0, tzinfo=UTC))],
        ]
        connectors = FakeConnectorFactory({SERVER_A: FakeConnector(pages)})
        sales = FakeSales()

        report = build_service(registry, connectors, sales, page_size=2).sync(server, now=MOMENT)

        assert report.pages == 2
        assert report.fetched == 3

    def test_yeni_sened_yoxdursa_da_ugurlu_sayilir(self) -> None:
        # Əks halda sakit bir gündən sonra Health Monitor serveri STALE sayardı.
        server = make_server()
        registry = FakeRegistry([server])
        connectors = FakeConnectorFactory({SERVER_A: FakeConnector([])})

        report = build_service(registry, connectors, FakeSales()).sync(server, now=MOMENT)

        assert report.ok
        assert report.pages == 0
        assert len(registry.successes) == 1

    def test_uygunlasma_statistikasi_hesablanir(self) -> None:
        server = make_server()
        registry = FakeRegistry([server])
        directory = FakeDirectory(
            stores={(str(SERVER_A), "STORE-01"): STORE_A},
            sellers={(str(STORE_A), "SELLER-1"): ELVIN},
        )
        records = [make_record("DOC-1"), make_record("DOC-2", store_code="NAMƏLUM")]
        connectors = FakeConnectorFactory({SERVER_A: FakeConnector([records])})

        report = build_service(registry, connectors, FakeSales(), directory).sync(
            server, now=MOMENT
        )

        assert report.exact_matches == 1
        assert report.unassigned == 1
        assert report.needs_review == 1


class TestErpSyncManager:
    def test_bir_serverin_xetasi_digerini_dayandirmir(self) -> None:
        healthy = make_server()
        broken = make_server(id=SERVER_B, server_name="İstikbal — Gəncə")
        registry = FakeRegistry([healthy, broken])
        connectors = FakeConnectorFactory(
            {
                SERVER_A: FakeConnector([[make_record("DOC-1")]]),
                SERVER_B: FakeConnector(error=ErpTransportError("şəbəkə yoxdur")),
            }
        )
        sales = FakeSales()
        manager = ErpSyncManager(
            servers=registry,
            service_factory=lambda: build_service(registry, connectors, sales),
        )

        cycle = manager.run_cycle(now=MOMENT)

        assert len(cycle.servers) == 2
        assert len(cycle.failed) == 1
        assert cycle.total_inserted == 1
        assert not cycle.all_ok
        assert registry.failures[0][0] == SERVER_B

    def test_gozlenilmez_xeta_da_izolyasiya_olunur(self) -> None:
        # `ErpError` olmayan xəta buraxılsaydı `pool.map` bütün dövrü qırardı.
        server = make_server()
        registry = FakeRegistry([server])
        connectors = FakeConnectorFactory({SERVER_A: FakeConnector(error=RuntimeError("boom"))})
        manager = ErpSyncManager(
            servers=registry,
            service_factory=lambda: build_service(registry, connectors, FakeSales()),
        )

        cycle = manager.run_cycle(now=MOMENT)

        assert len(cycle.failed) == 1
        assert registry.failures[0][0] == SERVER_A

    def test_deaktiv_server_dovreye_daxil_edilmir(self) -> None:
        active = make_server()
        inactive = make_server(id=SERVER_B, status=ErpServerStatus.INACTIVE)
        registry = FakeRegistry([active, inactive])
        connectors = FakeConnectorFactory()
        manager = ErpSyncManager(
            servers=registry,
            service_factory=lambda: build_service(registry, connectors, FakeSales()),
        )

        cycle = manager.run_cycle(now=MOMENT)

        assert [report.server_id for report in cycle.servers] == [str(SERVER_A)]

    def test_error_statuslu_server_dovreden_cixarilmir(self) -> None:
        # Bir şəbəkə kəsintisi serveri həmişəlik növbədən çıxarmamalıdır.
        assert ErpServerStatus.ERROR.is_syncable
        assert not ErpServerStatus.INACTIVE.is_syncable


# --------------------------------------------------------------------------- #
# Bağlantı Sihirbazı
# --------------------------------------------------------------------------- #


class TestConnectionWizard:
    def test_icaze_yoxdursa_qadagandir(self) -> None:
        registry = FakeRegistry([])
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=FakeConnectorFactory())
        with pytest.raises(ErpConnectionError):
            wizard.save_new(actor=make_employee(), draft=make_draft(), now=MOMENT)
        assert registry.created == []

    def test_test_ugursuzdursa_konfiqurasiya_saxlanmir(self) -> None:
        registry = FakeRegistry([])
        connectors = FakeConnectorFactory()
        connectors.draft_connector = FakeConnector(error=ErpTransportError("çatmır"))
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=connectors)

        with pytest.raises(ConnectionNotVerifiedError):
            wizard.save_new(
                actor=make_employee(MANAGE_ERP_SERVERS_FLAG), draft=make_draft(), now=MOMENT
            )
        assert registry.created == []

    def test_ugurlu_testden_sonra_server_yaradilir(self) -> None:
        registry = FakeRegistry([])
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=FakeConnectorFactory())

        outcome = wizard.save_new(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG), draft=make_draft(), now=MOMENT
        )

        assert outcome.test.ok
        assert len(registry.created) == 1

    def test_redakte_evvelki_konfiqurasiyani_backup_edir(self) -> None:
        server = make_server(last_successful_sync=MOMENT)
        registry = FakeRegistry([server])
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=FakeConnectorFactory())

        outcome = wizard.save_existing(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
            server_id=SERVER_A,
            draft=make_draft(host="10.0.0.9"),
            now=MOMENT,
        )

        assert registry.updated[0][2] is True
        assert outcome.backed_up_previous

    def test_hec_vaxt_islememis_konfiqurasiya_dogrulanmis_sayilmir(self) -> None:
        server = make_server(last_successful_sync=None)
        registry = FakeRegistry([server])
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=FakeConnectorFactory())

        outcome = wizard.save_existing(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
            server_id=SERVER_A,
            draft=make_draft(host="10.0.0.9"),
            now=MOMENT,
        )

        assert not outcome.backed_up_previous

    def test_geri_qaytarma_test_teleb_etmir(self) -> None:
        # 1C sönmüş olduqda da geri qaytarma işləməlidir.
        registry = FakeRegistry([make_server()])
        connectors = FakeConnectorFactory()
        connectors.draft_connector = FakeConnector(error=ErpTransportError("çatmır"))
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=connectors)

        wizard.rollback(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG), server_id=SERVER_A, now=MOMENT
        )

        assert registry.rollbacks == [SERVER_A]

    def test_bos_infobase_ile_aktivlesdirmek_olmaz(self) -> None:
        registry = FakeRegistry([make_server(infobase="  ")])
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=FakeConnectorFactory())

        with pytest.raises(ErpConnectionError):
            wizard.set_status(
                actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
                server_id=SERVER_A,
                status=ErpServerStatus.ACTIVE,
                now=MOMENT,
            )
        assert registry.status_changes == []

    def test_deaktiv_etmek_infobase_teleb_etmir(self) -> None:
        registry = FakeRegistry([make_server(infobase="")])
        wizard = ErpConnectionWizardUseCase(servers=registry, connectors=FakeConnectorFactory())

        wizard.set_status(
            actor=make_employee(MANAGE_ERP_SERVERS_FLAG),
            server_id=SERVER_A,
            status=ErpServerStatus.INACTIVE,
            now=MOMENT,
        )

        assert registry.status_changes == [(SERVER_A, ErpServerStatus.INACTIVE)]


# --------------------------------------------------------------------------- #
# Sağlamlıq monitoru
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
    }
    return ServerHealthRow(**{**defaults, **overrides})


class TestHealthDiagnosis:
    def test_deaktiv_server_problem_kimi_gosterilmir(self) -> None:
        row = health_row(ServerHealth.INACTIVE)
        assert not row.health.needs_attention
        assert not row.suggests_settings

    def test_xeritelenmemis_server_ucun_xerite_teklif_olunur(self) -> None:
        row = health_row(ServerHealth.NEVER_SYNCED, mapped_stores=0)
        assert "xəritələmə" in row.diagnosis.lower()
        assert row.suggests_settings

    def test_ardicil_xetalar_credential_ehtimali_verir(self) -> None:
        row = health_row(ServerHealth.DEGRADED, consecutive_failures=3)
        assert "3" in row.diagnosis
        assert row.suggests_settings

    def test_kohne_sync_server_sonub_ehtimali_verir(self) -> None:
        assert "şəbəkə" in health_row(ServerHealth.STALE).diagnosis.lower()

    def test_saglam_server_teklif_vermir(self) -> None:
        row = health_row(ServerHealth.HEALTHY)
        assert not row.suggests_settings
