"""Mağaza/ay qovluqlarının həlli və lazy yaradılması — Faza 3.9.

Tələb: *"Cərimə formasında Mağaza seçiləndə, şəkil AVTOMATİK olaraq həmin
mağazanın Drive qovluğuna düşməlidir — admin heç bir qovluğu əl ilə
yaratmamalıdır."*

──────────────────────────────────────────────────────────────────────────────
AYLIQ ROTASİYA "ƏMƏLİYYAT" DEYİL, AD SXEMİNİN NƏTİCƏSİDİR
──────────────────────────────────────────────────────────────────────────────
Qovluq yolu `KompasOS/{Mağaza}/{İl-Ay}/` olduğu üçün ay dəyişəndə axtarış
açarı da dəyişir: keşdə tapılmır, yeni qovluq yaradılır. Əvvəlki ayın
qovluğuna daha heç nə yazılmır — yəni "bağlanma" öz-özünə baş verir.
Ayrıca cron, ayrıca "arxivlə" düyməsi və ya vəziyyət sahəsi LAZIM DEYİL.

Bunun praktik faydası: ayın 1-də cron işləməsə belə sistem düzgün davranır.
Vəziyyət saxlayan həll isə cron uğursuz olanda sükutla səhv qovluğa yazardı.

──────────────────────────────────────────────────────────────────────────────
KEŞ NİYƏ DB-DƏDİR, YADDAŞDA DEYİL
──────────────────────────────────────────────────────────────────────────────
Eyni tenant-ın bir neçə mağaza PC-si var. Yaddaş keşi hər PC-də ayrıca
olardı və hər biri Drive-da eyni qovluğu axtarardı. DB keşi bütün PC-lər
üçün ortaqdır — Drive API-yə sorğu mağaza/ay başına BİR dəfə gedir.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from src.domain.value_objects.storage import DRIVE_ROOT_FOLDER_NAME
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import StoreId, TenantId
    from src.infrastructure.persistence.connection import Database
    from src.infrastructure.storage.drive_api import DriveApiClient

_log = get_logger(__name__)


def year_month(moment: datetime) -> str:
    """`datetime` → `'YYYY-MM'` (DB-dəki `chk_folder_year_month` ilə eyni format)."""
    return f"{moment.year:04d}-{moment.month:02d}"


def sanitize_folder_name(name: str) -> str:
    """Drive qovluq adı üçün təhlükəsiz ad.

    Azərbaycan hərfləri SAXLANILIR — bu, insanın Drive-da baxdığı addır və
    "Yataş Babək" yazısı "Yatas Babek"-ə çevrilməməlidir. Yalnız Drive
    axtarış sorğusunu poza bilən simvollar təmizlənir.
    """
    cleaned = "".join(ch for ch in name if ch not in "\\/'\"\n\r\t").strip()
    return cleaned[:100] or "Adsız Mağaza"


class DriveFolderCache(Protocol):
    """`drive_folder_cache` cədvəlinin portu."""

    def get(self, connection_id: UUID, store_id: StoreId, period: str) -> str | None: ...

    def put(self, connection_id: UUID, store_id: StoreId, period: str, folder_id: str) -> None: ...


class InMemoryDriveFolderCache:
    """Testlər və tək-maşınlı işləmə üçün."""

    def __init__(self) -> None:
        self.entries: dict[tuple[UUID, str, str], str] = {}
        self._lock = threading.Lock()

    def get(self, connection_id: UUID, store_id: StoreId, period: str) -> str | None:
        with self._lock:
            return self.entries.get((connection_id, str(store_id), period))

    def put(self, connection_id: UUID, store_id: StoreId, period: str, folder_id: str) -> None:
        with self._lock:
            self.entries[(connection_id, str(store_id), period)] = folder_id


class PostgresDriveFolderCache:
    """`drive_folder_cache` cədvəli üzərində keş."""

    def __init__(self, database: Database, tenant_id: TenantId) -> None:
        self._database = database
        self._tenant_id = tenant_id

    def get(self, connection_id: UUID, store_id: StoreId, period: str) -> str | None:
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(
                """
                SELECT drive_folder_id FROM drive_folder_cache
                 WHERE drive_connection_id = %s AND store_id = %s AND year_month = %s
                """,
                (connection_id, store_id, period),
            )
            row: dict[str, Any] | None = cur.fetchone()
        return str(row["drive_folder_id"]) if row else None

    def put(self, connection_id: UUID, store_id: StoreId, period: str, folder_id: str) -> None:
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO drive_folder_cache
                        (tenant_id, drive_connection_id, store_id, year_month, drive_folder_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (drive_connection_id, store_id, year_month) DO NOTHING
                    """,
                    (self._tenant_id, connection_id, store_id, period, folder_id),
                )
            uow.commit()


class FolderResolver:
    """`KompasOS/{Mağaza}/{İl-Ay}/` qovluğunu tapır və ya yaradır."""

    def __init__(
        self,
        *,
        api: DriveApiClient,
        cache: DriveFolderCache,
        connection_id: UUID,
        root_folder_id: str | None = None,
    ) -> None:
        self._api = api
        self._cache = cache
        self._connection_id = connection_id
        self._root_folder_id = root_folder_id
        #: Eyni prosesdə paralel yükləmələr eyni qovluğu İKİ dəfə
        #: yaratmasın deyə (Drive eyniadlı iki qovluğa icazə verir).
        self._creation_lock = threading.Lock()

    @property
    def root_folder_id(self) -> str | None:
        """Kök qovluğun ID-si — `drive_connections`-a geri yazmaq üçün."""
        return self._root_folder_id

    def resolve(self, *, store_id: StoreId, store_name: str, moment: datetime) -> str:
        period = year_month(moment)

        cached = self._cache.get(self._connection_id, store_id, period)
        if cached is not None:
            return cached

        with self._creation_lock:
            # İkiqat yoxlama: kilidi gözləyərkən başqa sap yaratmış ola bilər.
            cached = self._cache.get(self._connection_id, store_id, period)
            if cached is not None:
                return cached

            root = self._ensure_root()
            store_folder = self._api.ensure_folder(sanitize_folder_name(store_name), parent_id=root)
            month_folder = self._api.ensure_folder(period, parent_id=store_folder)

            self._cache.put(self._connection_id, store_id, period, month_folder)
            _log.info(
                "DRIVE_FOLDER_RESOLVED",
                extra={
                    "store_id": str(store_id),
                    "period": period,
                    "folder_id": month_folder,
                    "created": True,
                },
            )
            return month_folder

    def _ensure_root(self) -> str:
        if self._root_folder_id is None:
            self._root_folder_id = self._api.ensure_folder(DRIVE_ROOT_FOLDER_NAME)
        return self._root_folder_id

    def prewarm(self, stores: list[tuple[StoreId, str]], moment: datetime) -> int:
        """Ayın qovluqlarını əvvəlcədən yaradır (İSTƏYƏ BAĞLI optimallaşdırma).

        Lazy yaradılma onsuz da düzgün işləyir; bu, sadəcə ayın ilk
        cəriməsində gecikməni aradan qaldırır. Uğursuzluq HEÇ NƏYİ pozmur —
        növbəti yükləmə qovluğu özü yaradacaq.
        """
        created = 0
        for store_id, store_name in stores:
            try:
                self.resolve(store_id=store_id, store_name=store_name, moment=moment)
                created += 1
            except Exception as exc:  # bir mağazanın nasazlığı digərlərini dayandırmasın
                _log.warning(
                    "DRIVE_FOLDER_PREWARM_FAILED",
                    extra={"store_id": str(store_id), "error": str(exc)},
                )
        return created


__all__ = [
    "DriveFolderCache",
    "FolderResolver",
    "InMemoryDriveFolderCache",
    "PostgresDriveFolderCache",
    "sanitize_folder_name",
    "year_month",
]
