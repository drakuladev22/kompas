"""Drive bağlantıları — REAL PostgreSQL-ə qarşı inteqrasiya testləri (Faza 3.9).

Burada yoxlanılanlar məhz DB-nin təmin etməli olduğu zəmanətlərdir:
    * tenant başına yalnız BİR aktiv bağlantı (unikal indeks),
    * hesab dəyişikliyinin atomikliyi,
    * köhnə cərimə sətrinin bağlantı istinadının DƏYİŞMƏMƏSİ,
    * qovluq keşinin bağlantı üzrə ayrılması,
    * RLS izolyasiyası.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from src.domain.value_objects.identifiers import StoreId, TenantId
from src.infrastructure.persistence import Database
from src.infrastructure.security.encryption import EncryptionService
from src.infrastructure.storage.connections import (
    DriveConnectionRepository,
    DriveConnectionStatus,
    NoActiveDriveConnectionError,
)
from src.infrastructure.storage.folder_resolver import PostgresDriveFolderCache
from src.shared.exceptions import DecryptionError

pytestmark = [pytest.mark.integration]

DATABASE_URL = os.environ.get("DATABASE_URL", "")

requires_db = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL təyin edilməyib — inteqrasiya testləri atlandı",
)

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def database() -> Iterator[Database]:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL yoxdur")
    db = Database(DATABASE_URL, min_size=1, max_size=3)
    yield db
    db.close()


@pytest.fixture
def tenant(database: Database) -> Iterator[TenantId]:
    tenant_id = TenantId(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]
    with database.system_scope() as conn:
        conn.execute(
            """
            INSERT INTO license_tenants
                (tenant_id, tenant_name, license_key_hash, status, company_contact_email)
            VALUES (%s, %s, 'test', 'AKTIV', %s)
            """,
            (tenant_id, f"DRIVE-{suffix}", f"drive-{suffix}@test.local"),
        )
        conn.execute("SELECT seed_tenant_defaults(%s)", (tenant_id,))
        conn.execute(
            "INSERT INTO stores (tenant_id, code, name, brand) VALUES (%s, %s, %s, 'Yataş')",
            (tenant_id, f"DRV-{suffix}", "Yataş Babək"),
        )
        conn.commit()

    yield tenant_id

    with database.system_scope() as conn:
        conn.execute("DELETE FROM license_tenants WHERE tenant_id = %s", (tenant_id,))
        conn.commit()


@pytest.fixture
def store_id(database: Database, tenant: TenantId) -> StoreId:
    with database.system_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM stores WHERE tenant_id = %s LIMIT 1", (tenant,))
        row = cur.fetchone()
    assert row is not None
    return StoreId(row["id"])


@pytest.fixture
def encryption() -> EncryptionService:
    return EncryptionService()


@pytest.fixture
def repository(database: Database, tenant: TenantId) -> DriveConnectionRepository:
    return DriveConnectionRepository(database, tenant)


# --------------------------------------------------------------------------- #
# Aktiv bağlantı invariantı
# --------------------------------------------------------------------------- #


@requires_db
def test_no_connection_raises_actionable_error(repository: DriveConnectionRepository) -> None:
    """Mesaj operatora NƏ ETMƏLİ olduğunu deməlidir."""
    assert repository.get_active() is None
    with pytest.raises(NoActiveDriveConnectionError) as exc_info:
        repository.require_active()
    assert "Ayarlar" in exc_info.value.user_message


@requires_db
def test_connect_creates_active_connection(
    repository: DriveConnectionRepository, encryption: EncryptionService
) -> None:
    connection = repository.connect(
        google_account_email="birinci@sirket.az",
        refresh_token="refresh-token-1",
        encryption=encryption,
        now=NOW,
    )

    assert connection.status is DriveConnectionStatus.ACTIVE
    assert repository.get_active() is not None
    assert repository.get_active().id == connection.id  # type: ignore[union-attr]


@requires_db
def test_second_connect_archives_the_first(
    repository: DriveConnectionRepository, encryption: EncryptionService
) -> None:
    """Tələb 1: Drive dolanda admin yeni hesab qoşa bilməlidir."""
    first = repository.connect(
        google_account_email="birinci@sirket.az",
        refresh_token="token-1",
        encryption=encryption,
        now=NOW,
    )
    second = repository.connect(
        google_account_email="ikinci@sirket.az",
        refresh_token="token-2",
        encryption=encryption,
        now=NOW + timedelta(days=30),
    )

    assert repository.get_active().id == second.id  # type: ignore[union-attr]
    archived = repository.get(first.id)
    assert archived is not None
    assert archived.status is DriveConnectionStatus.ARCHIVED
    assert archived.archived_at is not None


@requires_db
def test_archived_connection_token_is_still_readable(
    repository: DriveConnectionRepository, encryption: EncryptionService
) -> None:
    """Arxivlənmiş hesabdakı ŞƏKİLLƏR oxunmalıdır — token silinməməlidir."""
    first = repository.connect(
        google_account_email="birinci@sirket.az",
        refresh_token="kohne-token",
        encryption=encryption,
        now=NOW,
    )
    repository.connect(
        google_account_email="ikinci@sirket.az",
        refresh_token="yeni-token",
        encryption=encryption,
        now=NOW + timedelta(days=1),
    )

    assert repository.refresh_token_for(first.id, encryption) == "kohne-token"


@requires_db
def test_two_active_connections_are_impossible(
    database: Database, tenant: TenantId, encryption: EncryptionService
) -> None:
    """Unikal indeks DB səviyyəsində qoruyur — kod səhvi belə sıza bilməz."""
    repository = DriveConnectionRepository(database, tenant)
    repository.connect(
        google_account_email="birinci@sirket.az",
        refresh_token="t1",
        encryption=encryption,
        now=NOW,
    )

    with pytest.raises(psycopg.errors.UniqueViolation), database.unit_of_work(tenant) as uow:
        uow.connection.execute(
            """
            INSERT INTO drive_connections
                (tenant_id, google_account_email, oauth_refresh_token, status)
            VALUES (%s, 'ikinci@sirket.az', 'x', 'ACTIVE')
            """,
            (tenant,),
        )


# --------------------------------------------------------------------------- #
# Token şifrələməsi
# --------------------------------------------------------------------------- #


@requires_db
def test_refresh_token_is_encrypted_at_rest(
    database: Database,
    tenant: TenantId,
    repository: DriveConnectionRepository,
    encryption: EncryptionService,
) -> None:
    repository.connect(
        google_account_email="gizli@sirket.az",
        refresh_token="ÇOX-GİZLİ-TOKEN",
        encryption=encryption,
        now=NOW,
    )

    with database.unit_of_work(tenant) as uow, uow.connection.cursor() as cur:
        cur.execute("SELECT oauth_refresh_token FROM drive_connections")
        stored = cur.fetchone()["oauth_refresh_token"]  # type: ignore[index]

    assert "ÇOX-GİZLİ-TOKEN" not in stored
    assert stored.startswith("v1.")


@requires_db
def test_token_cannot_be_moved_to_another_connection(
    database: Database,
    tenant: TenantId,
    repository: DriveConnectionRepository,
    encryption: EncryptionService,
) -> None:
    """AAD kontekstinə bağlantı ID-si bağlanıb (SEC-002 ilə eyni model)."""
    first = repository.connect(
        google_account_email="birinci@sirket.az",
        refresh_token="token-1",
        encryption=encryption,
        now=NOW,
    )
    second = repository.connect(
        google_account_email="ikinci@sirket.az",
        refresh_token="token-2",
        encryption=encryption,
        now=NOW + timedelta(days=1),
    )

    with database.unit_of_work(tenant) as uow:
        uow.connection.execute(
            """
            UPDATE drive_connections SET oauth_refresh_token =
                (SELECT oauth_refresh_token FROM drive_connections WHERE id = %s)
            WHERE id = %s
            """,
            (first.id, second.id),
        )
        uow.commit()

    with pytest.raises(DecryptionError):
        repository.refresh_token_for(second.id, encryption)


# --------------------------------------------------------------------------- #
# Qovluq keşi
# --------------------------------------------------------------------------- #


@requires_db
def test_folder_cache_roundtrip(
    database: Database,
    tenant: TenantId,
    store_id: StoreId,
    repository: DriveConnectionRepository,
    encryption: EncryptionService,
) -> None:
    connection = repository.connect(
        google_account_email="a@sirket.az",
        refresh_token="t",
        encryption=encryption,
        now=NOW,
    )
    cache = PostgresDriveFolderCache(database, tenant)

    assert cache.get(connection.id, store_id, "2026-08") is None
    cache.put(connection.id, store_id, "2026-08", "drive-folder-abc")
    assert cache.get(connection.id, store_id, "2026-08") == "drive-folder-abc"
    # Aylıq rotasiya: sentyabr üçün ayrıca sətir lazımdır.
    assert cache.get(connection.id, store_id, "2026-09") is None


@requires_db
def test_folder_cache_is_separated_per_connection(
    database: Database,
    tenant: TenantId,
    store_id: StoreId,
    repository: DriveConnectionRepository,
    encryption: EncryptionService,
) -> None:
    first = repository.connect(
        google_account_email="a@sirket.az",
        refresh_token="t1",
        encryption=encryption,
        now=NOW,
    )
    cache = PostgresDriveFolderCache(database, tenant)
    cache.put(first.id, store_id, "2026-08", "folder-in-first-account")

    second = repository.connect(
        google_account_email="b@sirket.az",
        refresh_token="t2",
        encryption=encryption,
        now=NOW + timedelta(days=1),
    )

    # Yeni hesabda həmin qovluq YOXDUR — yenidən yaradılmalıdır.
    assert cache.get(second.id, store_id, "2026-08") is None
    assert cache.get(first.id, store_id, "2026-08") == "folder-in-first-account"


@requires_db
def test_invalid_year_month_is_rejected_by_db(
    database: Database,
    tenant: TenantId,
    store_id: StoreId,
    repository: DriveConnectionRepository,
    encryption: EncryptionService,
) -> None:
    connection = repository.connect(
        google_account_email="a@sirket.az",
        refresh_token="t",
        encryption=encryption,
        now=NOW,
    )

    with pytest.raises(psycopg.errors.CheckViolation), database.unit_of_work(tenant) as uow:
        uow.connection.execute(
            """
            INSERT INTO drive_folder_cache
                (tenant_id, drive_connection_id, store_id, year_month, drive_folder_id)
            VALUES (%s, %s, %s, '2026-13', 'x')
            """,
            (tenant, connection.id, store_id),
        )


# --------------------------------------------------------------------------- #
# Cərimə sətri ilə əlaqə
# --------------------------------------------------------------------------- #


def _make_fine(
    database: Database,
    tenant: TenantId,
    store_id: StoreId,
    *,
    connection_id: uuid.UUID,
    file_id: str,
) -> uuid.UUID:
    """Kamera operatoru + cərimə növü ilə birlikdə tam cərimə sətri yaradır."""
    fine_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    with database.system_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM positions WHERE tenant_id = %s AND code = 'KAMERA_NEZARETCISI'",
                (tenant,),
            )
            position_id = cur.fetchone()["id"]  # type: ignore[index]
        operator_id = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO employees
                (id, tenant_id, store_id, position_id, first_name, last_name,
                 username, password_hash, is_active)
            VALUES (%s, %s, %s, %s, 'Kamera', 'Operator', %s, 'argon2', TRUE)
            """,
            (operator_id, tenant, store_id, position_id, f"op{suffix}"),
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fine_types (tenant_id, name_az, standard_amount)
                VALUES (%s, 'Test cərimə növü', 10.00) RETURNING id
                """,
                (tenant,),
            )
            fine_type_id = cur.fetchone()["id"]  # type: ignore[index]
        conn.execute(
            """
            INSERT INTO fines
                (id, tenant_id, employee_id, store_id, source, fine_type_id, amount,
                 issued_by, evidence_drive_file_id, evidence_drive_connection_id,
                 appeal_window_closes_at)
            VALUES (%s, %s, %s, %s, 'MANUAL_CAMERA', %s, %s, %s, %s, %s, %s)
            """,
            (
                fine_id,
                tenant,
                operator_id,
                store_id,
                fine_type_id,
                Decimal("25.00"),
                operator_id,
                file_id,
                connection_id,
                NOW + timedelta(hours=72),
            ),
        )
        conn.commit()
    return fine_id


@requires_db
def test_existing_fine_keeps_its_connection_after_swap(
    database: Database,
    tenant: TenantId,
    store_id: StoreId,
    repository: DriveConnectionRepository,
    encryption: EncryptionService,
) -> None:
    """ƏSAS TƏLƏB: hesab dəyişəndə köhnə şəklə keçid POZULMAMALIDIR."""
    first = repository.connect(
        google_account_email="birinci@sirket.az",
        refresh_token="t1",
        encryption=encryption,
        now=NOW,
    )
    fine_id = _make_fine(database, tenant, store_id, connection_id=first.id, file_id="drive-file-1")

    repository.connect(
        google_account_email="ikinci@sirket.az",
        refresh_token="t2",
        encryption=encryption,
        now=NOW + timedelta(days=30),
    )

    with database.unit_of_work(tenant) as uow, uow.connection.cursor() as cur:
        cur.execute(
            """SELECT evidence_drive_file_id, evidence_drive_connection_id
                 FROM fines WHERE id = %s""",
            (fine_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row["evidence_drive_file_id"] == "drive-file-1"
    assert row["evidence_drive_connection_id"] == first.id, "köhnə keçid qırıldı"


@requires_db
def test_manual_fine_accepts_pending_evidence_upload(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Asinxron yükləmə: cərimə şəkil Drive-a çatmadan ƏVVƏL yaradıla bilməlidir."""
    suffix = uuid.uuid4().hex[:8]
    with database.system_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM positions WHERE tenant_id = %s AND code = 'KAMERA_NEZARETCISI'",
                (tenant,),
            )
            position_id = cur.fetchone()["id"]  # type: ignore[index]
        operator_id = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO employees
                (id, tenant_id, store_id, position_id, first_name, last_name,
                 username, password_hash, is_active)
            VALUES (%s, %s, %s, %s, 'Kamera', 'Operator', %s, 'argon2', TRUE)
            """,
            (operator_id, tenant, store_id, position_id, f"op{suffix}"),
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fine_types (tenant_id, name_az, standard_amount)
                VALUES (%s, 'Test növ', 10.00) RETURNING id
                """,
                (tenant,),
            )
            fine_type_id = cur.fetchone()["id"]  # type: ignore[index]
        # Nə `photo_evidence_url`, nə `evidence_drive_file_id` var —
        # yalnız PENDING statusu. Məhdudiyyət buna icazə verməlidir.
        conn.execute(
            """
            INSERT INTO fines
                (tenant_id, employee_id, store_id, source, fine_type_id, amount,
                 issued_by, evidence_upload_status, appeal_window_closes_at)
            VALUES (%s, %s, %s, 'MANUAL_CAMERA', %s, 25.00, %s, 'PENDING', %s)
            """,
            (tenant, operator_id, store_id, fine_type_id, operator_id, NOW + timedelta(hours=72)),
        )
        conn.commit()

    with database.unit_of_work(tenant) as uow, uow.connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM fines WHERE evidence_upload_status = 'PENDING'")
        assert cur.fetchone()["n"] == 1  # type: ignore[index]


@requires_db
def test_manual_fine_without_any_evidence_is_still_rejected(
    database: Database, tenant: TenantId, store_id: StoreId
) -> None:
    """Məhdudiyyət GENİŞLƏNDİ, LƏĞV EDİLMƏDİ — sübutsuz cərimə hələ də olmaz."""
    suffix = uuid.uuid4().hex[:8]
    with database.system_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM positions WHERE tenant_id = %s AND code = 'KAMERA_NEZARETCISI'",
                (tenant,),
            )
            position_id = cur.fetchone()["id"]  # type: ignore[index]
        operator_id = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO employees
                (id, tenant_id, store_id, position_id, first_name, last_name,
                 username, password_hash, is_active)
            VALUES (%s, %s, %s, %s, 'Kamera', 'Operator', %s, 'argon2', TRUE)
            """,
            (operator_id, tenant, store_id, position_id, f"op{suffix}"),
        )
        conn.commit()

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        database.system_scope() as conn,
    ):
        conn.execute(
            """
            INSERT INTO fines
                (tenant_id, employee_id, store_id, source, amount, issued_by,
                 evidence_upload_status, appeal_window_closes_at)
            VALUES (%s, %s, %s, 'MANUAL_CAMERA', 25.00, %s, 'SYNCED', %s)
            """,
            (tenant, operator_id, store_id, operator_id, NOW + timedelta(hours=72)),
        )


# --------------------------------------------------------------------------- #
# RLS
# --------------------------------------------------------------------------- #


@requires_db
def test_drive_connection_is_invisible_to_other_tenant(
    database: Database,
    tenant: TenantId,
    repository: DriveConnectionRepository,
    encryption: EncryptionService,
) -> None:
    repository.connect(
        google_account_email="gizli@sirket.az",
        refresh_token="t",
        encryption=encryption,
        now=NOW,
    )
    other = DriveConnectionRepository(database, TenantId(uuid.uuid4()))

    assert other.list_all() == []
    assert other.get_active() is None


@requires_db
def test_permission_flag_is_granted_to_root_and_ceo(database: Database, tenant: TenantId) -> None:
    """`can_manage_drive_connection` yeni tenant-larda da olmalıdır."""
    with database.unit_of_work(tenant) as uow, uow.connection.cursor() as cur:
        cur.execute(
            """
            SELECT p.code
              FROM position_permissions pp
              JOIN positions p ON p.id = pp.position_id
             WHERE p.tenant_id = %s AND pp.flag_code = 'can_manage_drive_connection'
               AND pp.granted
             ORDER BY p.code
            """,
            (tenant,),
        )
        codes = {row["code"] for row in cur.fetchall()}

    assert {"ROOT", "CEO"} <= codes
