"""Təhlükəsizlik infrastrukturu (spesifikasiya bölmə 2).

Qərarlar və əsaslandırma: `docs/security_decisions.md`.

QEYD (SEC-016): TOTP/2FA servisi ÇIXARILIB — admin girişi artıq istifadəçi
adı + şifrədən ibarətdir. `totp.py` və onun testləri silinib,
`pyotp` asılılığı layihədən çıxarılıb.

QEYD (`facecontrol.md` Faza 3): `face_matcher.py` BURADAN RE-EXPORT EDİLMİR
və bu, qəsdli qərardır. Onun idxalı `face_recognition` (Dlib) modulunu — yəni
~132 MB model faylını — yükləyir; bu paketi isə `conftest.py`-dan tutmuş hər
şifrələmə/hash testinə qədər onlarla yol idxal edir. Re-export etsəydik, üz
təsdiqinə heç bir aidiyyəti olmayan yollar da həmin qiyməti ödəyərdi.
İstehlakçı (`composition.py`) modulu BİRBAŞA idxal edir.
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
