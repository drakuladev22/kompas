"""TOTP əsaslı 2FA servisi (spesifikasiya bölmə 2).

QAYDA (spesifikasiyadan):
    "Root/CEO/HR_Admin/Mağaza_Meneceri kimi admin-səviyyəli rollar öz admin
    panelinə … e-poçt + güclü şifrə (+ məcburi TOTP-əsaslı 2FA) ilə daxil olur."
    Bölmə 2 həmçinin `Kamera_Nəzarətçisi`-ni bu tier-ə keçirir.

TƏHLÜKƏSİZLİK QƏRARLARI:

* **Sirr heç vaxt plaintext saxlanılmır.** `employees.totp_secret_encrypted`
  sütunu AES-256-GCM token saxlayır; AAD olaraq ``f"totp:{employee_id}"``
  istifadə olunur — beləliklə bir istifadəçinin şifrəli sirrini başqasının
  sətrinə köçürmək mümkün deyil.

* **Replay qorunması (KRİTİK).** TOTP kodu 30 saniyə etibarlıdır. Qoruma
  olmadan çiynin üstündən baxan (shoulder-surfing) və ya loglardan kodu görən
  şəxs həmin pəncərədə eyni kodla daxil ola bilər. Ona görə hər uğurlu
  təsdiqdə istifadə olunmuş **time-step counter** saxlanılır və eyni (və ya
  daha köhnə) counter bir daha qəbul edilmir.

* **Pəncərə (drift) tolerantlığı: ±1 addım (±30 s).** Mağaza PC-lərində saat
  sürüşməsi real problemdir (bax bölmə 2, TIME_DRIFT_DETECTED), lakin pəncərəni
  genişləndirmək brute-force səthini artırır. ±1 sənaye standartıdır.

* **Ehtiyat (backup) kodları.** Telefonu itən admin sistemdən tamamilə
  kənarda qalmasın deyə 10 birdəfəlik kod yaradılır. Kodlar Argon2id ilə
  hash-lənib saxlanılır (plaintext YOX) və hər biri yalnız bir dəfə işləyir.
  Bu, bölmə 2-dəki "Emergency Access Recovery" prosedurunun işə düşmə
  ehtimalını azaldır.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote

import pyotp

from src.infrastructure.security.encryption import EncryptionService
from src.infrastructure.security.hashing import HashingService
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

TOTP_DIGITS: Final[int] = 6
TOTP_INTERVAL_SECONDS: Final[int] = 30
TOTP_VALID_WINDOW: Final[int] = 1  # ±30 saniyə drift tolerantlığı
BACKUP_CODE_COUNT: Final[int] = 10
BACKUP_CODE_BYTES: Final[int] = 5  # 10 hex simvol
DEFAULT_ISSUER: Final[str] = "KompasOS"


class TotpError(KompasOSError):
    """2FA əməliyyatı uğursuz oldu."""

    user_message = "İki-faktorlu təsdiq uğursuz oldu."


@dataclass(frozen=True)
class TotpEnrollment:
    """Yeni 2FA qeydiyyatının nəticəsi — İlk Quraşdırma Sihirbazına verilir."""

    #: DB-yə yazılacaq şifrələnmiş sirr (`employees.totp_secret_encrypted`).
    encrypted_secret: str
    #: QR kod yaratmaq üçün otpauth:// URI — YALNIZ ekranda göstərilir, saxlanılmır.
    provisioning_uri: str
    #: QR skan edilə bilmirsə əl ilə daxil etmək üçün base32 sirr — saxlanılmır.
    manual_entry_key: str
    #: İstifadəçiyə BİR DƏFƏ göstərilən ehtiyat kodları (plaintext).
    backup_codes: tuple[str, ...]
    #: DB-yə yazılacaq hash-lənmiş ehtiyat kodları.
    backup_code_hashes: tuple[str, ...]


@dataclass(frozen=True)
class TotpVerification:
    """TOTP yoxlamasının nəticəsi."""

    is_valid: bool
    #: Uğurlu olduqda istifadə edilmiş time-step — DB-də saxlanılmalıdır (replay).
    used_counter: int | None
    reason: str


class TotpService:
    """TOTP sirlərinin yaradılması, şifrələnməsi və yoxlanması."""

    def __init__(
        self,
        encryption: EncryptionService,
        hashing: HashingService,
        *,
        issuer: str = DEFAULT_ISSUER,
    ) -> None:
        self._encryption = encryption
        self._hashing = hashing
        self._issuer = issuer

    # ----------------------------- kontekst --------------------------------- #

    @staticmethod
    def _aad_context(employee_id: str) -> str:
        """Şifrəli sirri konkret işçiyə bağlayan AAD."""
        return f"totp:{employee_id}"

    # ----------------------------- qeydiyyat -------------------------------- #

    def enroll(self, *, employee_id: str, account_label: str) -> TotpEnrollment:
        """Yeni 2FA sirri yaradır və qeydiyyat paketini qaytarır.

        Args:
            employee_id: Sirri bu işçiyə bağlayır (AAD).
            account_label: Authenticator tətbiqində görünəcək ad (adətən e-poçt).
        """
        if not employee_id:
            raise ValueError("employee_id boş ola bilməz")

        secret = pyotp.random_base32()
        encrypted = self._encryption.encrypt(secret, context=self._aad_context(employee_id))

        uri = pyotp.TOTP(
            secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS
        ).provisioning_uri(name=quote(account_label), issuer_name=quote(self._issuer))

        plain_codes, hashed_codes = self.generate_backup_codes(employee_id=employee_id)

        _security_log.info(
            "TOTP_ENROLLED",
            extra={"employee_id": employee_id, "backup_code_count": len(plain_codes)},
        )

        return TotpEnrollment(
            encrypted_secret=encrypted,
            provisioning_uri=uri,
            manual_entry_key=secret,
            backup_codes=plain_codes,
            backup_code_hashes=hashed_codes,
        )

    # ------------------------------ yoxlama --------------------------------- #

    def verify(
        self,
        *,
        encrypted_secret: str,
        code: str,
        employee_id: str,
        last_used_counter: int | None = None,
        at_time: float | None = None,
    ) -> TotpVerification:
        """TOTP kodunu yoxlayır və replay-i bloklayır.

        Args:
            encrypted_secret: DB-dəki şifrələnmiş sirr.
            code: İstifadəçinin daxil etdiyi 6 rəqəmli kod.
            employee_id: AAD yoxlaması üçün.
            last_used_counter: Bu istifadəçinin sonuncu uğurlu time-step-i.
                Eyni və ya daha köhnə counter rədd edilir.
            at_time: Test üçün sabit vaxt (Unix saniyə).
        """
        normalized = code.strip().replace(" ", "").replace("-", "")
        if not normalized.isdigit() or len(normalized) != TOTP_DIGITS:
            _security_log.warning("TOTP_INVALID_FORMAT", extra={"employee_id": employee_id})
            return TotpVerification(False, None, "INVALID_FORMAT")

        try:
            secret = self._encryption.decrypt(
                encrypted_secret, context=self._aad_context(employee_id)
            )
        except Exception as exc:
            _security_log.error(
                "TOTP_SECRET_DECRYPT_FAILED",
                extra={"employee_id": employee_id, "error": type(exc).__name__},
            )
            raise TotpError(
                "2FA sirri oxuna bilmədi — şifrələmə açarı və ya məlumat problemi",
                context={"employee_id": employee_id},
            ) from exc

        moment = at_time if at_time is not None else time.time()
        totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS)
        current_counter = int(moment // TOTP_INTERVAL_SECONDS)

        # Pəncərə daxilindəki hər addımı ayrıca yoxlayırıq ki, HANSI addımın
        # istifadə olunduğunu bilək — replay qorunması bunu tələb edir.
        for offset in range(-TOTP_VALID_WINDOW, TOTP_VALID_WINDOW + 1):
            candidate_counter = current_counter + offset
            # Vaxt-zonasından ASILI OLMAYAN hesablama: pyotp naive datetime
            # üçün lokal vaxta keçir (DST-də sürüşmə riski), tz-aware datetime
            # üçün isə birbaşa UTC istifadə edir.
            candidate_time = datetime.fromtimestamp(
                candidate_counter * TOTP_INTERVAL_SECONDS, tz=UTC
            )
            if not secrets.compare_digest(totp.at(candidate_time), normalized):
                continue

            if last_used_counter is not None and candidate_counter <= last_used_counter:
                _security_log.warning(
                    "TOTP_REPLAY_BLOCKED",
                    extra={
                        "employee_id": employee_id,
                        "counter": candidate_counter,
                        "last_used": last_used_counter,
                    },
                )
                return TotpVerification(False, None, "REPLAY_DETECTED")

            _security_log.info(
                "TOTP_VERIFIED",
                extra={"employee_id": employee_id, "counter": candidate_counter},
            )
            return TotpVerification(True, candidate_counter, "OK")

        _security_log.warning("TOTP_MISMATCH", extra={"employee_id": employee_id})
        return TotpVerification(False, None, "MISMATCH")

    # -------------------------- ehtiyat kodları ------------------------------ #

    def generate_backup_codes(
        self, *, employee_id: str, count: int = BACKUP_CODE_COUNT
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Birdəfəlik ehtiyat kodları yaradır.

        Returns:
            `(plaintext_codes, hashed_codes)` — plaintext YALNIZ bir dəfə
            istifadəçiyə göstərilir və heç yerdə saxlanılmır.
        """
        plain: list[str] = []
        hashed: list[str] = []
        for _ in range(count):
            raw = secrets.token_hex(BACKUP_CODE_BYTES).upper()
            formatted = f"{raw[:5]}-{raw[5:]}"
            plain.append(formatted)
            hashed.append(
                self._hashing.hash_pin(
                    formatted, employee_id=f"backup:{employee_id}", validate=False
                )
            )
        return tuple(plain), tuple(hashed)

    def verify_backup_code(
        self, *, code: str, stored_hashes: list[str], employee_id: str
    ) -> int | None:
        """Ehtiyat kodunu yoxlayır.

        Returns:
            İstifadə olunmuş kodun `stored_hashes` içindəki indeksi, uyğun
            gəlmirsə `None`. Çağıran tərəf həmin indeksi DB-dən SİLMƏLİDİR
            (birdəfəlik istifadə).
        """
        normalized = code.strip().upper()
        for index, stored in enumerate(stored_hashes):
            if self._hashing.verify_pin(stored, normalized, employee_id=f"backup:{employee_id}"):
                _security_log.warning(
                    "TOTP_BACKUP_CODE_USED",
                    extra={
                        "employee_id": employee_id,
                        "remaining": len(stored_hashes) - 1,
                    },
                )
                return index
        _security_log.warning("TOTP_BACKUP_CODE_MISMATCH", extra={"employee_id": employee_id})
        return None
