"""Drive bağlantılarının reyestri — Faza 3.9.

Tələb: *"Sistem TƏK bir Google Drive hesabına bərk-kodlanmamalıdır. Admin
istənilən vaxt yeni bir Drive hesabı qoşub 'aktiv' edə bilməlidir, köhnə
hesabdakı şəkillərə keçidlər isə pozulmamalıdır."*

──────────────────────────────────────────────────────────────────────────────
HESAB DƏYİŞİKLİYİNİN İŞLƏMƏ MƏNTİQİ
──────────────────────────────────────────────────────────────────────────────
    yeni hesab qoşulur  →  köhnəsi ARCHIVED, yenisi ACTIVE (bir tranzaksiyada)
    YENİ yükləmələr     →  ACTIVE bağlantıya
    KÖHNƏ şəkillər      →  `fines.evidence_drive_connection_id` göstərdiyi
                            bağlantıdan oxunur — həmin sətir DƏYİŞMİR

Yəni "keçid qırılması" struktur olaraq mümkün deyil: oxuma heç vaxt "aktiv
bağlantı"dan istifadə etmir, həmişə sətirdə yazılmış bağlantıdan.

Arxivlənmiş bağlantının refresh token-i SAXLANILIR — silinsəydi oradakı
şəkillər əbədi əlçatmaz olardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.value_objects.storage import QuotaStatus, StorageError
from src.infrastructure.config.limits import InfrastructureLimits
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.persistence.connection import Database
    from src.infrastructure.security.encryption import EncryptionService
    from src.infrastructure.storage.drive_api import OAuthClient
    from src.infrastructure.storage.google_drive import (
        GoogleDriveStorageProvider,
        StoreNameResolver,
    )
    from src.infrastructure.storage.image_cache import ImageCache

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


class DriveConnectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    #: İstifadəçi Google hesabının təhlükəsizlik səhifəsindən razılığı GERİ ALDI.
    #:
    #: NİYƏ AYRICA VƏZİYYƏT — `ARCHIVED` KİFAYƏT ETMİRDİ: arxivləmə ADMİNİN
    #: qərarıdır (yeni hesab qoşuldu, köhnəsi oxunmağa davam edir) və oradakı
    #: şəkillər HƏLƏ DƏ açılır. Razılıq ləğvi isə XARİCİ hadisədir və nəticəsi
    #: fərqlidir: token artıq işləmir, yəni həmin hesabdakı şəkillər NƏ yazıla,
    #: NƏ də oxuna bilir. İkisini eyni vəziyyətdə birləşdirsəydik, ekran
    #: «Arxivlənib» yazar və administrator bunu normal hal sanardı.
    #:
    #: Ekran mətni (`controllers/drive_connection.STATUS_TEXT`) bu vəziyyət üçün
    #: ƏVVƏLCƏDƏN yazılmışdı, lakin enum-da qarşılığı YOX İDİ və heç bir kod
    #: ora keçirmirdi — yəni istifadəçi razılığı geri alanda ekran hələ də
    #: «Aktiv» göstərirdi və həqiqət yalnız növbəti yükləmə çökəndə üzə çıxırdı.
    REVOKED = "REVOKED"


class NoActiveDriveConnectionError(StorageError):
    """Tenant-da aktiv Drive bağlantısı yoxdur."""

    user_message = (
        "Cərimə şəkilləri üçün Google Drive hesabı qoşulmayıb — "
        "administrator Ayarlar → Drive Bağlantısı bölməsindən qoşmalıdır."
    )


@dataclass(frozen=True)
class DriveConnection:
    """`drive_connections` sətri (refresh token DAXİL DEYİL)."""

    id: UUID
    tenant_id: UUID
    google_account_email: str
    status: DriveConnectionStatus
    root_folder_id: str | None = None
    quota_used_bytes: int | None = None
    quota_total_bytes: int | None = None
    quota_checked_at: datetime | None = None
    quota_warning_sent_at: datetime | None = None
    connected_at: datetime | None = None
    archived_at: datetime | None = None

    @property
    def accepts_uploads(self) -> bool:
        return self.status is DriveConnectionStatus.ACTIVE

    @property
    def quota(self) -> QuotaStatus | None:
        if self.quota_used_bytes is None:
            return None
        return QuotaStatus(used_bytes=self.quota_used_bytes, total_bytes=self.quota_total_bytes)

    def __repr__(self) -> str:
        return (
            f"DriveConnection(id={self.id}, email={self.google_account_email}, "
            f"status={self.status.value})"
        )


class DriveConnectionRepository:
    """`drive_connections` üzərində əməliyyatlar (RLS-ə tabedir)."""

    #: Token SÜTUNU burada QƏSDƏN yoxdur — o, yalnız `refresh_token_for()`
    #: ilə, açıq şəkildə istənildikdə oxunur. Beləliklə siyahı sorğusu
    #: təsadüfən sirri yaddaşa gətirmir.
    _SELECT = """
        SELECT id, tenant_id, google_account_email, status, root_folder_id,
               quota_used_bytes, quota_total_bytes, quota_checked_at,
               quota_warning_sent_at, connected_at, archived_at
        FROM drive_connections
    """

    def __init__(self, database: Database, tenant_id: TenantId) -> None:
        self._database = database
        self._tenant_id = tenant_id

    def list_all(self) -> list[DriveConnection]:
        rows = self._fetch_all(self._SELECT + " ORDER BY connected_at DESC")
        return [_row_to_connection(row) for row in rows]

    def get(self, connection_id: UUID) -> DriveConnection | None:
        rows = self._fetch_all(self._SELECT + " WHERE id = %s", (connection_id,))
        return _row_to_connection(rows[0]) if rows else None

    def get_active(self) -> DriveConnection | None:
        rows = self._fetch_all(self._SELECT + " WHERE status = 'ACTIVE'")
        return _row_to_connection(rows[0]) if rows else None

    def require_active(self) -> DriveConnection:
        connection = self.get_active()
        if connection is None:
            raise NoActiveDriveConnectionError(
                "Aktiv Drive bağlantısı yoxdur",
                context={"tenant_id": str(self._tenant_id)},
            )
        return connection

    def connect(
        self,
        *,
        google_account_email: str,
        refresh_token: str,
        encryption: EncryptionService,
        connected_by: EmployeeId | None = None,
        now: datetime | None = None,
    ) -> DriveConnection:
        """Yeni hesabı qoşur və AKTİV edir; köhnəsi ARXİVLƏNİR.

        Hər ikisi EYNİ tranzaksiyadadır: `uq_drive_one_active_per_tenant`
        unikal indeksi iki aktiv sətrin bir an belə mövcud olmasına imkan
        vermir, ona görə arxivləmə YAZILIŞDAN ƏVVƏL olmalıdır.
        """
        moment = now or datetime.now(UTC)
        new_id = _new_uuid()
        # AAD kontekstinə bağlantı ID-si bağlanır: şifrəli token başqa
        # sətrə köçürülsə deşifrə OLUNMUR (SEC-002 ilə eyni model).
        token_encrypted = encryption.encrypt(refresh_token, context=f"drive_connection:{new_id}")

        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE drive_connections
                       SET status = 'ARCHIVED', archived_at = %s
                     WHERE tenant_id = %s
                       AND status IN ('ACTIVE', 'QUOTA_EXCEEDED', 'REVOKED')
                    """,
                    (moment, self._tenant_id),
                )
                archived = cur.rowcount
                cur.execute(
                    """
                    INSERT INTO drive_connections
                        (id, tenant_id, google_account_email, oauth_refresh_token,
                         status, connected_by, connected_at)
                    VALUES (%s, %s, %s, %s, 'ACTIVE', %s, %s)
                    """,
                    (
                        new_id,
                        self._tenant_id,
                        google_account_email,
                        token_encrypted,
                        connected_by,
                        moment,
                    ),
                )
            uow.commit()

        _security_log.warning(
            "DRIVE_CONNECTION_SWITCHED",
            extra={
                "tenant_id": str(self._tenant_id),
                "new_connection_id": str(new_id),
                "archived_count": archived,
                "account": google_account_email,
                "impact": "yeni şəkillər yeni hesaba gedir; köhnələr yerində qalır",
            },
        )
        connection = self.get(new_id)
        if connection is None:  # pragma: no cover - invariant
            raise StorageError("Yeni bağlantı yazıldı, lakin oxuna bilmədi")
        return connection

    def refresh_token_for(self, connection_id: UUID, encryption: EncryptionService) -> str:
        """Şifrəli token-i deşifrə edir. Çağırış `security.log`-a düşür."""
        rows = self._fetch_all(
            "SELECT oauth_refresh_token FROM drive_connections WHERE id = %s",
            (connection_id,),
        )
        if not rows:
            raise StorageError(
                "Drive bağlantısı tapılmadı", context={"connection_id": str(connection_id)}
            )
        _security_log.info("DRIVE_TOKEN_ACCESSED", extra={"connection_id": str(connection_id)})
        return encryption.decrypt(
            rows[0]["oauth_refresh_token"], context=f"drive_connection:{connection_id}"
        )

    def update_quota(
        self,
        connection_id: UUID,
        quota: QuotaStatus,
        *,
        now: datetime | None = None,
        mark_exceeded: bool = False,
    ) -> None:
        moment = now or datetime.now(UTC)
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE drive_connections
                       SET quota_used_bytes = %s,
                           quota_total_bytes = %s,
                           quota_checked_at = %s,
                           status = CASE
                               WHEN %s AND status = 'ACTIVE' THEN 'QUOTA_EXCEEDED'
                               ELSE status
                           END
                     WHERE id = %s
                    """,
                    (
                        quota.used_bytes,
                        quota.total_bytes,
                        moment,
                        mark_exceeded,
                        connection_id,
                    ),
                )
            uow.commit()

    def mark_revoked(self, connection_id: UUID, *, now: datetime | None = None) -> bool:
        """Razılıq geri alınıb — bağlantını `REVOKED` edir. Qaytarır: dəyişdimi.

        YALNIZ `ACTIVE`/`QUOTA_EXCEEDED` sətrə toxunur (`WHERE` şərti):
        `ARCHIVED` bağlantının token-i onsuz da işlədilmir və onu `REVOKED`-a
        keçirsəydik, KÖHNƏ şəkillərin oxunmasının niyə dayandığı sualı ortaya
        çıxardı. İDEMPOTENTDİR — ikinci çağırış heç bir sətri dəyişmir və
        `False` qaytarır, yəni gündəlik iş təkrar-təkrar bildiriş göndərmir.

        `last_error` də yazılır: administrator ekranda «İcazə ləğv edilib»
        görəndə növbəti sualı «nə vaxt və niyə?» olur.
        """
        moment = now or datetime.now(UTC)
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE drive_connections
                       SET status = 'REVOKED',
                           last_error = %s,
                           last_error_at = %s
                     WHERE id = %s AND status IN ('ACTIVE', 'QUOTA_EXCEEDED')
                    """,
                    ("Google razılığı geri alınıb (invalid_grant)", moment, connection_id),
                )
                changed = cur.rowcount
            uow.commit()

        if changed:
            _security_log.warning(
                "DRIVE_CONSENT_REVOKED",
                extra={
                    "tenant_id": str(self._tenant_id),
                    "connection_id": str(connection_id),
                    "impact": "yeni şəkillər lokal növbədə gözləyir; hesab yenidən qoşulmalıdır",
                },
            )
        return bool(changed)

    def mark_quota_warning_sent(self, connection_id: UUID, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    "UPDATE drive_connections SET quota_warning_sent_at = %s WHERE id = %s",
                    (moment, connection_id),
                )
            uow.commit()

    def set_root_folder(self, connection_id: UUID, folder_id: str) -> None:
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    "UPDATE drive_connections SET root_folder_id = %s WHERE id = %s",
                    (folder_id, connection_id),
                )
            uow.commit()

    def record_error(self, connection_id: UUID, message: str) -> None:
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """UPDATE drive_connections
                          SET last_error = %s, last_error_at = now()
                        WHERE id = %s""",
                    (message[:500], connection_id),
                )
            uow.commit()

    def _fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


class DriveProviderFactory:
    """Bağlantı → hazır `GoogleDriveStorageProvider`.

    Provider-lər bağlantı ID-sinə görə keşlənir: hər cərimə üçün yeni HTTP
    klienti və token yeniləməsi lazımsız yükdür. OXUMA üçün ARXİVLƏNMİŞ
    bağlantının provider-i də yaradıla bilir — köhnə şəkillər açılmalıdır.
    """

    def __init__(
        self,
        *,
        repository: DriveConnectionRepository,
        encryption: EncryptionService,
        oauth: OAuthClient,
        cache: ImageCache,
        store_names: StoreNameResolver | None = None,
        folder_cache_factory: Any = None,
        max_upload_bytes: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._repository = repository
        self._encryption = encryption
        self._oauth = oauth
        self._cache = cache
        self._store_names = store_names
        self._folder_cache_factory = folder_cache_factory
        # ROOT pəncərəsi provider-ə və HTTP klientinə ÖTÜRÜLÜR: sübut şəklinin
        # JPEG keyfiyyəti, Drive taymautu, token marjası və təkrar cəhd sayı
        # oradan oxunur (bax `google_drive`/`drive_api` fallback şərhləri).
        self._limits = limits or InfrastructureLimits()
        # `system_limits.MAX_UPLOAD_SIZE_BYTES` (bölmə 3) — kompozisiya kökü
        # tenant üçün oxuyub ötürür. `None` → provider öz defoltunu (5 MB)
        # işlədir; fabrika limiti UYDURMUR.
        self._max_upload_bytes = max_upload_bytes
        self._providers: dict[UUID, GoogleDriveStorageProvider] = {}

    def for_connection(self, connection_id: UUID) -> GoogleDriveStorageProvider:
        cached = self._providers.get(connection_id)
        if cached is not None:
            return cached

        from src.infrastructure.storage.drive_api import DriveApiClient  # noqa: PLC0415
        from src.infrastructure.storage.folder_resolver import (  # noqa: PLC0415
            FolderResolver,
            InMemoryDriveFolderCache,
        )
        from src.infrastructure.storage.google_drive import (  # noqa: PLC0415
            GoogleDriveStorageProvider,
            StoreNameResolver,
        )

        connection = self._repository.get(connection_id)
        if connection is None:
            raise StorageError(
                "Drive bağlantısı tapılmadı", context={"connection_id": str(connection_id)}
            )

        api = DriveApiClient(
            oauth=self._oauth,
            refresh_token=self._repository.refresh_token_for(connection_id, self._encryption),
            # HTTP taymautu, təkrar cəhd sayı və token yeniləmə marjası
            # ROOT-dandır — fabrik onu klientə də ÖTÜRMƏLİDİR, əks halda
            # yalnız provider Root dəyərini görər, sorğunu edən klient isə
            # fallback ilə işləyərdi (yəni Root taymautu heç vaxt tətbiq
            # olunmazdı).
            limits=self._limits,
        )
        folder_cache = (
            self._folder_cache_factory()
            if self._folder_cache_factory
            else InMemoryDriveFolderCache()
        )
        # Limit `None` olduqda arqument ÜMUMİYYƏTLƏ ötürülmür ki, provider öz
        # defoltunu (5 MB) işlətsin — burada ikinci bir defolt yazmaq iki
        # mənbə yaradardı. `dict[str, Any]`: `**` açılışı provider-in BÜTÜN
        # qalan parametrlərinə qarşı yoxlanılır və onların hamısı `int` deyil.
        upload_limit: dict[str, Any] = (
            {} if self._max_upload_bytes is None else {"max_upload_bytes": self._max_upload_bytes}
        )
        provider = GoogleDriveStorageProvider(
            api=api,
            folders=FolderResolver(
                api=api,
                cache=folder_cache,
                connection_id=connection_id,
                root_folder_id=connection.root_folder_id,
            ),
            cache=self._cache,
            connection_id=connection_id,
            store_names=self._store_names or StoreNameResolver(),
            limits=self._limits,
            **upload_limit,
        )
        self._providers[connection_id] = provider
        return provider

    def active(self) -> GoogleDriveStorageProvider:
        return self.for_connection(self._repository.require_active().id)

    def invalidate(self, connection_id: UUID) -> None:
        self._providers.pop(connection_id, None)


def _row_to_connection(row: dict[str, Any]) -> DriveConnection:
    return DriveConnection(
        id=row["id"],
        tenant_id=row["tenant_id"],
        google_account_email=row["google_account_email"],
        status=DriveConnectionStatus(row["status"]),
        root_folder_id=row.get("root_folder_id"),
        quota_used_bytes=row.get("quota_used_bytes"),
        quota_total_bytes=row.get("quota_total_bytes"),
        quota_checked_at=row.get("quota_checked_at"),
        quota_warning_sent_at=row.get("quota_warning_sent_at"),
        connected_at=row.get("connected_at"),
        archived_at=row.get("archived_at"),
    )


def _new_uuid() -> UUID:
    from uuid import uuid4  # noqa: PLC0415

    return uuid4()


__all__ = [
    "DriveConnection",
    "DriveConnectionRepository",
    "DriveConnectionStatus",
    "DriveProviderFactory",
    "NoActiveDriveConnectionError",
]
