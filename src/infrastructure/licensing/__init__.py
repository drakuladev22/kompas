"""Lisenziya klienti, yerli vəziyyət keşi və Developer Panel qatı — Faza 3.11.

Ayrıca lisenziya serveri, VPS, domen və ya HTTP API YOXDUR — hər şey mövcud
Supabase layihəsi üzərindədir (bax `domain/value_objects/licensing.py` başlığı).

    `gateway.py`              müştəri tərəfi — `anon` açar, YALNIZ OXUMA
    `developer_directory.py`  developer tərəfi — `service_role`, yazma
"""

from typing import TYPE_CHECKING

from src.infrastructure.licensing.client import LicenseClient
from src.infrastructure.licensing.developer_directory import (
    DEVELOPER_MODE_ENV,
    SERVICE_ROLE_ENV,
    DeveloperModeRequiredError,
    DeveloperTenantDirectory,
    ExtensionResult,
    TenantNotFoundError,
    TenantRow,
    developer_mode_enabled,
)
from src.infrastructure.licensing.gateway import SupabaseLicenseGateway
from src.infrastructure.licensing.state_store import (
    STATE_FILE_NAME,
    EncryptedLicenseStateStore,
    default_state_dir,
)

if TYPE_CHECKING:  # pragma: no cover
    # PORT UYĞUNLUĞUNUN STATİK YOXLAMASI — `erp/__init__.py` ilə eyni üsul.
    # `Protocol` structural typing olduğu üçün imza sürüşməsi işlək zamana
    # qədər gizli qalardı; bu funksiya HEÇ VAXT çağırılmır, yalnız MyPy-a
    # sual verdirir.
    from src.domain.interfaces.ports import LicenseGateway, LicenseStateStore

    def _assert_port_conformance(
        gateway: SupabaseLicenseGateway, store: EncryptedLicenseStateStore
    ) -> None:
        _gateway: LicenseGateway = gateway
        _store: LicenseStateStore = store


__all__ = [
    "DEVELOPER_MODE_ENV",
    "SERVICE_ROLE_ENV",
    "STATE_FILE_NAME",
    "DeveloperModeRequiredError",
    "DeveloperTenantDirectory",
    "EncryptedLicenseStateStore",
    "ExtensionResult",
    "LicenseClient",
    "SupabaseLicenseGateway",
    "TenantNotFoundError",
    "TenantRow",
    "default_state_dir",
    "developer_mode_enabled",
]
