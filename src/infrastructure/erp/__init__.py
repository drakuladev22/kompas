"""Çoxsaylı 1C konnektorları və izolyasiya olunmuş sync worker-lər — Faza 3.10."""

from typing import TYPE_CHECKING

from src.infrastructure.erp.health import ErpHealthMonitor, ServerHealth, ServerHealthRow
from src.infrastructure.erp.matching import (
    FALLBACK_AMBIGUITY_MARGIN,
    MatchDirectory,
    SalesMatcher,
    name_similarity,
    normalize_name,
)
from src.infrastructure.erp.one_c_connector import (
    OneCConnector,
    OneCConnectorFactory,
    OneCServerConfig,
)
from src.infrastructure.erp.sales import PostgresMatchDirectory, SalesTransactionRepository
from src.infrastructure.erp.servers import (
    ConfigBackup,
    ErpServerNotFoundError,
    ErpServerRepository,
    NoVerifiedBackupError,
)
from src.infrastructure.erp.sync_worker import (
    FALLBACK_MAX_PARALLEL_SERVERS,
    ErpSyncManager,
    SalesSyncService,
    SyncCycleReport,
    SyncReport,
)

if TYPE_CHECKING:  # pragma: no cover
    # PORT UYĞUNLUĞUNUN STATİK YOXLAMASI
    #
    # `Protocol` structural typing-dir: implementasiya portdan miras almır,
    # ona görə imza sürüşməsi (məs. porta yeni arqument əlavə olunması) heç
    # bir yerdə xəta vermir — nasazlıq yalnız işlək zamanda, DI qoşulanda
    # üzə çıxardı. Aşağıdakı funksiya HEÇ VAXT çağırılmır; onun yeganə işi
    # MyPy-a "bu siniflər bu portları ödəyirmi?" sualını verdirməkdir.
    from src.domain.interfaces.ports import ErpConnectorFactory, ErpServerRegistry

    def _assert_port_conformance(
        repository: ErpServerRepository, factory: OneCConnectorFactory
    ) -> None:
        _registry: ErpServerRegistry = repository
        _connectors: ErpConnectorFactory = factory


__all__ = [
    "FALLBACK_AMBIGUITY_MARGIN",
    "FALLBACK_MAX_PARALLEL_SERVERS",
    "ConfigBackup",
    "ErpHealthMonitor",
    "ErpServerNotFoundError",
    "ErpServerRepository",
    "ErpSyncManager",
    "MatchDirectory",
    "NoVerifiedBackupError",
    "OneCConnector",
    "OneCConnectorFactory",
    "OneCServerConfig",
    "PostgresMatchDirectory",
    "SalesMatcher",
    "SalesSyncService",
    "SalesTransactionRepository",
    "ServerHealth",
    "ServerHealthRow",
    "SyncCycleReport",
    "SyncReport",
    "name_similarity",
    "normalize_name",
]
