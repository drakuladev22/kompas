"""Avtomatik yenilənmə: kataloq, yayım, doğrulama, tətbiq və geri qaytarma — Faza 3.13.

`publisher` QƏSDƏN buradan idxal EDİLMİR: o, `service_role` tərəfidir və yalnız
Developer Panelində istifadə olunur. Paket səviyyəsində idxal edilsəydi,
müştəri quraşdırmasında da yüklənərdi — kod orada işləməsə belə, "yayım
məntiqinin müştəri `.exe`-sində olmaması" qaydası pozulardı.
İstifadə: `from src.infrastructure.updates.publisher import ReleasePublisher`.
"""

from src.infrastructure.updates.catalog import (
    DEFAULT_BUCKET,
    SUPABASE_URL_ENV,
    SupabaseReleaseCatalog,
)
from src.infrastructure.updates.client import (
    SILENT_ARGS,
    AutoUpdateClient,
    PreparedUpdate,
)
from src.infrastructure.updates.verification import (
    VALID_STATUS,
    AuthenticodeVerifier,
    file_sha256,
    verify_checksum,
    verify_package,
)

__all__ = [
    "DEFAULT_BUCKET",
    "SILENT_ARGS",
    "SUPABASE_URL_ENV",
    "VALID_STATUS",
    "AuthenticodeVerifier",
    "AutoUpdateClient",
    "PreparedUpdate",
    "SupabaseReleaseCatalog",
    "file_sha256",
    "verify_checksum",
    "verify_package",
]
