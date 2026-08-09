"""Təhlükəsizlik infrastrukturu (spesifikasiya bölmə 2).

Qərarlar və əsaslandırma: `docs/security_decisions.md`.

QEYD (SEC-016): TOTP/2FA servisi ÇIXARILIB — admin girişi artıq istifadəçi
adı + şifrədən ibarətdir. `totp.py` və onun testləri silinib,
`pyotp` asılılığı layihədən çıxarılıb.
"""

from src.infrastructure.security.encryption import (
    ChainedKeyProvider,
    EncryptionService,
    EnvironmentKeyProvider,
    KeyMaterial,
    KeyProvider,
    WindowsDpapiKeyProvider,
    default_key_provider,
    generate_key,
)
from src.infrastructure.security.hashing import (
    AccountLockedError,
    HashingService,
    LockoutDecision,
    PasswordPolicy,
    PepperProvider,
    PepperSet,
    PinPolicy,
    WeakSecretError,
    evaluate_pin_attempt,
    generate_pepper,
)

__all__ = [
    "AccountLockedError",
    "ChainedKeyProvider",
    "EncryptionService",
    "EnvironmentKeyProvider",
    "HashingService",
    "KeyMaterial",
    "KeyProvider",
    "LockoutDecision",
    "PasswordPolicy",
    "PepperProvider",
    "PepperSet",
    "PinPolicy",
    "WeakSecretError",
    "WindowsDpapiKeyProvider",
    "default_key_provider",
    "evaluate_pin_attempt",
    "generate_key",
    "generate_pepper",
]
