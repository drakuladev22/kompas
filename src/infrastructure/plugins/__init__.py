"""Dynamic Plugin API — sandbox + rəqəmsal imza (spesifikasiya bölmə 1).

Üç müdafiə qatı: imza yoxlaması → proses izolyasiyası → capability whitelist.
Ətraflı: `contracts.py`, `signature.py`, `sandbox.py`.
"""

from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginError,
    PluginManifest,
    PluginPermissionError,
    PluginRequest,
    PluginResponse,
    PluginSignatureError,
    PluginStatus,
    PluginTimeoutError,
)
from src.infrastructure.plugins.sandbox import (
    ALLOWED_ENV_KEYS,
    SECRET_ENV_PREFIXES,
    PluginSandbox,
    SandboxPolicy,
    build_sandbox_env,
)
from src.infrastructure.plugins.signature import (
    PluginSignatureVerifier,
    TrustedPublisher,
    TrustStore,
    canonical_payload,
    file_sha256,
    sign_plugin,
)

__all__ = [
    "ALLOWED_ENV_KEYS",
    "SECRET_ENV_PREFIXES",
    "PluginCapability",
    "PluginError",
    "PluginManifest",
    "PluginPermissionError",
    "PluginRequest",
    "PluginResponse",
    "PluginSandbox",
    "PluginSignatureError",
    "PluginSignatureVerifier",
    "PluginStatus",
    "PluginTimeoutError",
    "SandboxPolicy",
    "TrustStore",
    "TrustedPublisher",
    "build_sandbox_env",
    "canonical_payload",
    "file_sha256",
    "sign_plugin",
]
