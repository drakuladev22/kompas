"""Argon2id parol/PIN hash-ləmə və PIN lockout siyasəti (spesifikasiya bölmə 2).

QAYDA (spesifikasiyadan):
    "Passwords hashed (Argon2)."
    "4-rəqəmli PIN üçün 5 ardıcıl səhv cəhddən sonra 15 dəqiqəlik lockout,
    hər cəhd `security.log`-a yazılır."

──────────────────────────────────────────────────────────────────────────────
TƏHLÜKƏSİZLİK QƏRARI (SEC-005) — PIN ÜÇÜN MƏCBURİ PEPPER
──────────────────────────────────────────────────────────────────────────────
4-rəqəmli PIN-in CƏMİ 10 000 mümkün dəyəri var. Argon2id nə qədər güclü
konfiqurasiya edilsə də, **bazanın sızması halında** hücumçu offline rejimdə
işçi başına cəmi 10 000 variant sınamalıdır — 100 ms/hash-da bu, bir işçi üçün
~17 dəqiqədir. Yəni Argon2 TƏK BAŞINA 4-rəqəmli PIN üçün KİFAYƏT DEYİL.

Həll: **pepper** (`KOMPASOS_HASH_PEPPER`) — bazada YOX, yalnız mühit
dəyişənində/DPAPI-də saxlanılan gizli açar. PIN əvvəlcə
`HMAC-SHA256(pepper, "pin:" + employee_id + ":" + pin)` ilə emal olunur,
sonra Argon2id-yə verilir. Nəticə:

    * Yalnız DB sızarsa (pepper sızmadan) → PIN-lər praktiki olaraq bərpa
      OLUNA BİLMƏZ, çünki hücumçu HMAC açarını bilmir.
    * `employee_id` HMAC-a daxil edildiyi üçün eyni PIN fərqli işçilərdə
      fərqli daycest verir — "hansı işçilərdə eyni PIN var" analizi mümkün deyil.

Pepper OLMADAN sistem işləyir (deqradasiya rejimi), lakin startup zamanı
`security.log`-a KRİTİK xəbərdarlıq yazılır və `--check` bunu problem kimi
göstərir. İstehsalatda pepper MƏCBURİDİR.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Final

from argon2 import PasswordHasher, Type
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from src.domain.value_objects.credentials import (
    PIN_LENGTH,
    WEAK_PINS,
    InvalidPinError,
    Pin,
)
from src.shared.exceptions import ConfigurationError, KompasOSError
from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

ENV_PEPPER: Final[str] = "KOMPASOS_HASH_PEPPER"
ENV_PEPPER_PREVIOUS: Final[str] = "KOMPASOS_HASH_PEPPER_PREVIOUS"

#: Pepper konfiqurasiya edilməyibsə istifadə olunan versiya (DB defoltu ilə eyni).
DEFAULT_PEPPER_VERSION: Final[int] = 1

# OWASP 2024 tövsiyəsi (Argon2id): m=64 MiB, t=3, p=4.
# Kiosk PC-ləri zəif ola bilər, lakin PIN yoxlaması gündə bir neçə dəfə baş
# verir — 64 MiB / ~100 ms qəbul ediləndir.
ARGON2_TIME_COST: Final[int] = 3
ARGON2_MEMORY_COST_KIB: Final[int] = 64 * 1024
ARGON2_PARALLELISM: Final[int] = 4
ARGON2_HASH_LENGTH: Final[int] = 32
ARGON2_SALT_LENGTH: Final[int] = 16

DEFAULT_MAX_PIN_ATTEMPTS: Final[int] = 5
DEFAULT_PIN_LOCKOUT_MINUTES: Final[int] = 15

MIN_PASSWORD_LENGTH: Final[int] = 12


class WeakSecretError(KompasOSError):
    """Şifrə/PIN siyasətə uyğun deyil."""

    user_message = "Seçdiyiniz dəyər təhlükəsizlik tələblərinə cavab vermir."


class AccountLockedError(KompasOSError):
    """Hesab müvəqqəti bloklanıb (PIN lockout)."""

    user_message = "Hesab müvəqqəti bloklanıb. Bir az sonra yenidən cəhd edin."


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


# --------------------------------------------------------------------------- #
# Pepper
# --------------------------------------------------------------------------- #


#: Pepper üçün minimum uzunluq (128 bit entropiya).
MIN_PEPPER_LENGTH: Final[int] = 32
#: `generate_pepper()` neçə təsadüfi bayt yaradır (256 bit → 64 hex simvol).
PEPPER_BYTES: Final[int] = 32


def generate_pepper() -> str:
    """Yeni pepper yaradır (64 hex simvol = 256 bit).

    İstifadə::

        python -c "from src.infrastructure.security.hashing \
import generate_pepper; print(generate_pepper())"
    """
    return secrets.token_hex(PEPPER_BYTES)


@dataclass(frozen=True)
class PepperSet:
    """Cari + köhnə pepper-lər (lazy migration üçün).

    Versiya nömrələməsi AVTOMATİKDİR: `current_version = len(previous) + 1`.
    Rotasiya zamanı köhnə cari dəyər `PREVIOUS` siyahısının BAŞINA əlavə edilir
    və versiya öz-özünə artır — əl ilə versiya idarəetməsi lazım deyil.

    `__repr__` maskalanıb ki, pepper log/traceback-ə düşməsin.
    """

    current: bytes | None
    previous: tuple[bytes, ...] = ()

    @property
    def current_version(self) -> int:
        return len(self.previous) + 1

    def for_version(self, version: int) -> bytes | None:
        """Verilmiş versiyaya aid pepper-i qaytarır.

        Naməlum (çox köhnə və ya çox yeni) versiya üçün `None` — bu halda
        yoxlama uğursuz olur, lakin istisna atılmır (enumeration qorunması).
        """
        if self.current is None:
            return None
        if version == self.current_version:
            return self.current
        index = self.current_version - 1 - version
        if 0 <= index < len(self.previous):
            return self.previous[index]
        return None

    def __repr__(self) -> str:  # pragma: no cover - sadə maskalama
        state = "configured" if self.current else "missing"
        return f"PepperSet(current=***{state}***, version={self.current_version})"

    __str__ = __repr__


class PepperProvider:
    """Pepper-i mühit dəyişənindən oxuyur.

    Pepper DB-də saxlanılmır — məhz bu, onun bütün mənasıdır. İstehsalatda
    Windows DPAPI credential store və ya GitHub Secrets vasitəsilə təchiz olunur.

    Rotasiya::

        KOMPASOS_HASH_PEPPER=<yeni>
        KOMPASOS_HASH_PEPPER_PREVIOUS=<köhnə>,<daha köhnə>     # ən yenisi əvvəldə
    """

    def __init__(
        self,
        *,
        env_var: str = ENV_PEPPER,
        previous_env_var: str = ENV_PEPPER_PREVIOUS,
        required: bool = False,
    ) -> None:
        self._env_var = env_var
        self._previous_env_var = previous_env_var
        self._required = required

    def _validate(self, raw: str, source: str) -> bytes:
        if len(raw) < MIN_PEPPER_LENGTH:
            raise ConfigurationError(
                f"`{source}` çox qısadır (minimum {MIN_PEPPER_LENGTH} simvol / 128 bit)",
                context={"length": len(raw)},
            )
        return raw.encode("utf-8")

    def load(self) -> PepperSet:
        raw = os.environ.get(self._env_var, "").strip()
        if not raw:
            if self._required:
                raise ConfigurationError(
                    f"`{self._env_var}` təyin edilməyib — 4-rəqəmli PIN-lər üçün "
                    f"pepper istehsalat mühitində MƏCBURİDİR",
                    context={"env_var": self._env_var},
                )
            return PepperSet(current=None)

        current = self._validate(raw, self._env_var)
        raw_previous = os.environ.get(self._previous_env_var, "").strip()
        previous = tuple(
            self._validate(item.strip(), self._previous_env_var)
            for item in raw_previous.split(",")
            if item.strip()
        )
        return PepperSet(current=current, previous=previous)


# --------------------------------------------------------------------------- #
# Siyasətlər
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PinPolicy:
    """PIN siyasəti — dəyərlər `system_limits`-dən oxunur (bölmə 3)."""

    max_attempts: int = DEFAULT_MAX_PIN_ATTEMPTS
    lockout_minutes: int = DEFAULT_PIN_LOCKOUT_MINUTES
    reject_weak: bool = True

    def lockout_until(self, *, now: datetime | None = None) -> datetime:
        return (now or _utc_now()) + timedelta(minutes=self.lockout_minutes)

    def is_locked(self, locked_until: datetime | None, *, now: datetime | None = None) -> bool:
        if locked_until is None:
            return False
        return (now or _utc_now()) < locked_until

    def should_lock(self, failed_attempts: int) -> bool:
        return failed_attempts >= self.max_attempts

    def remaining_attempts(self, failed_attempts: int) -> int:
        return max(0, self.max_attempts - failed_attempts)


@dataclass(frozen=True)
class PasswordPolicy:
    """Admin-tier şifrə siyasəti (bölmə 2: "güclü şifrə")."""

    min_length: int = MIN_PASSWORD_LENGTH
    require_upper: bool = True
    require_lower: bool = True
    require_digit: bool = True
    require_symbol: bool = True

    def validate(self, password: str) -> None:
        """Siyasətə uyğun deyilsə `WeakSecretError` atır (AZ dilində səbəblə)."""
        problems: list[str] = []
        if len(password) < self.min_length:
            problems.append(f"minimum {self.min_length} simvol olmalıdır")
        if self.require_upper and not re.search(r"[A-ZƏÖÜĞIİŞÇ]", password):
            problems.append("ən azı bir böyük hərf olmalıdır")
        if self.require_lower and not re.search(r"[a-zəöüğıişç]", password):
            problems.append("ən azı bir kiçik hərf olmalıdır")
        if self.require_digit and not re.search(r"\d", password):
            problems.append("ən azı bir rəqəm olmalıdır")
        if self.require_symbol and not re.search(r"[^\w\s]", password):
            problems.append("ən azı bir xüsusi simvol olmalıdır")
        if password.strip() != password:
            problems.append("əvvəlində/sonunda boşluq ola bilməz")

        if problems:
            raise WeakSecretError(
                "Şifrə siyasətə uyğun deyil: " + ", ".join(problems),
                user_message="Şifrə tələblərə cavab vermir: " + ", ".join(problems),
                context={"problem_count": len(problems)},
            )


# --------------------------------------------------------------------------- #
# Hashing servisi
# --------------------------------------------------------------------------- #


class HashingService:
    """Argon2id əsaslı parol/PIN hash-ləmə servisi.

    Nümunə::

        hasher = HashingService()
        pin_hash = hasher.hash_pin("4821", employee_id="a1b2-...")
        ok = hasher.verify_pin(pin_hash, "4821", employee_id="a1b2-...")
    """

    def __init__(
        self,
        *,
        pepper_provider: PepperProvider | None = None,
        pin_policy: PinPolicy | None = None,
        password_policy: PasswordPolicy | None = None,
        time_cost: int = ARGON2_TIME_COST,
        memory_cost: int = ARGON2_MEMORY_COST_KIB,
        parallelism: int = ARGON2_PARALLELISM,
    ) -> None:
        """
        Args:
            time_cost / memory_cost / parallelism: Argon2id parametrləri.
                Defolt dəyərlər OWASP 2024 tövsiyəsidir və İSTEHSALATDA
                DƏYİŞDİRİLMƏMƏLİDİR. Yalnız test dəstində (sürət üçün) və
                zəif kiosk PC-lərində ölçmə əsasında tənzimlənə bilər —
                azaldılma qərarı `docs/security_decisions.md`-də qeyd olunmalıdır.
        """
        self._pepper_provider = pepper_provider or PepperProvider()
        self.pin_policy = pin_policy or PinPolicy()
        self.password_policy = password_policy or PasswordPolicy()
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=ARGON2_HASH_LENGTH,
            salt_len=ARGON2_SALT_LENGTH,
            type=Type.ID,  # Argon2id — GPU və side-channel müqaviməti balansı
        )
        self._peppers: PepperSet | None = None
        self._pepper_loaded = False
        self._lock = threading.Lock()
        #: İstifadəçi-sayma (enumeration) hücumuna qarşı sabit-vaxtlı "dummy" hash.
        self._dummy_hash = self._hasher.hash("dummy-value-for-timing-equalisation")

    # ------------------------------ pepper ---------------------------------- #

    def _is_pepper_loaded(self) -> bool:
        """Metod kimi ayrılıb — bax `EncryptionService._is_loaded` qeydi."""
        return self._pepper_loaded

    def _get_peppers(self) -> PepperSet:
        if self._is_pepper_loaded():
            assert self._peppers is not None
            return self._peppers
        with self._lock:
            # Başqa thread bu arada yükləmiş ola bilər.
            if self._is_pepper_loaded():
                assert self._peppers is not None
                return self._peppers

            peppers = self._pepper_provider.load()
            self._peppers = peppers
            self._pepper_loaded = True

            if peppers.current is None:
                _security_log.critical(
                    "HASH_PEPPER_MISSING",
                    extra={
                        "impact": (
                            "4-rəqəmli PIN-lər DB sızması halında brute-force ilə bərpa oluna bilər"
                        ),
                        "action": f"{ENV_PEPPER} mühit dəyişənini təyin edin",
                    },
                )
            else:
                _security_log.info(
                    "HASH_PEPPER_LOADED",
                    extra={
                        "configured": True,
                        "current_version": peppers.current_version,
                        "previous_count": len(peppers.previous),
                    },
                )
            return peppers

    @property
    def has_pepper(self) -> bool:
        """Startup health-check üçün — pepper konfiqurasiya edilibmi."""
        return self._get_peppers().current is not None

    @property
    def current_pepper_version(self) -> int:
        """Yeni hash-lər bu versiya ilə yazılır (`employees.pepper_version`)."""
        peppers = self._get_peppers()
        return peppers.current_version if peppers.current else DEFAULT_PEPPER_VERSION

    def needs_pepper_rehash(self, pepper_version: int) -> bool:
        """Saxlanılan hash köhnə pepper ilə yaradılıbsa `True`.

        LAZY MIGRATION (SEC-005): uğurlu yoxlamadan SONRA çağıran tərəf hash-i
        yenidən yaradıb `employees.pepper_version`-ı yeniləməlidir. Beləliklə
        pepper rotasiyası kütləvi PIN/şifrə sıfırlaması tələb etmir.
        """
        return pepper_version != self.current_pepper_version

    def _apply_pepper(
        self,
        secret: str,
        *,
        kind: str,
        subject_id: str | None,
        pepper_version: int | None = None,
    ) -> str | None:
        """Sirri pepper ilə HMAC-layır.

        Args:
            pepper_version: `None` → cari pepper. Rəqəm verilibsə həmin
                versiyanın pepper-i istifadə olunur (köhnə hash-i yoxlamaq üçün).

        Returns:
            Peppered dəyər; pepper ümumiyyətlə konfiqurasiya edilməyibsə sirrin
            özü; naməlum versiya tələb olunubsa `None` (yoxlama uğursuz olsun).
        """
        peppers = self._get_peppers()
        if peppers.current is None:
            return secret

        pepper = peppers.for_version(
            pepper_version if pepper_version is not None else peppers.current_version
        )
        if pepper is None:
            _security_log.warning(
                "HASH_PEPPER_VERSION_UNKNOWN",
                extra={
                    "requested_version": pepper_version,
                    "current_version": peppers.current_version,
                },
            )
            return None

        message = f"{kind}:{subject_id or ''}:{secret}".encode()
        return hmac.new(pepper, message, sha256).hexdigest()

    # ------------------------------ şifrə ----------------------------------- #

    def hash_password(self, password: str, *, validate: bool = True) -> str:
        """Admin-tier şifrəni Argon2id ilə hash-ləyir (CARİ pepper versiyası ilə)."""
        if validate:
            self.password_policy.validate(password)
        # Şifrə üçün də pepper tətbiq olunur (entropiyası yüksək olsa da,
        # DB sızması ssenarisində əlavə qat zərər vermir).
        peppered = self._apply_pepper(password, kind="pwd", subject_id=None)
        assert peppered is not None
        return self._hasher.hash(peppered)

    def verify_password(
        self,
        stored_hash: str | None,
        password: str,
        *,
        pepper_version: int | None = None,
    ) -> bool:
        """Şifrəni yoxlayır. `stored_hash is None` olduqda da SABİT vaxt sərf edir."""
        peppered = self._apply_pepper(
            password, kind="pwd", subject_id=None, pepper_version=pepper_version
        )
        if peppered is None:
            self._verify(None, "unknown-pepper-version")  # sabit vaxt
            return False
        return self._verify(stored_hash, peppered)

    # -------------------------------- PIN ----------------------------------- #

    def validate_pin_format(self, pin: str) -> None:
        """PIN formatını və zəiflik siyasətini yoxlayır.

        Qaydalar DOMEN qatındakı `Pin` value object-ində saxlanılır (tək
        həqiqət mənbəyi) — burada yalnız istisna tipi infrastruktur
        semantikasına uyğunlaşdırılır.
        """
        try:
            Pin.parse(pin, reject_weak=self.pin_policy.reject_weak)
        except InvalidPinError as exc:
            raise WeakSecretError(
                exc.message, user_message=exc.user_message, context=exc.context
            ) from exc

    def hash_pin(self, pin: str, *, employee_id: str, validate: bool = True) -> str:
        """PIN-i pepper + Argon2id ilə hash-ləyir.

        Args:
            pin: 4 rəqəmli PIN.
            employee_id: HMAC-a daxil edilir — eyni PIN fərqli işçilərdə fərqli
                daycest verir (rainbow/korrelyasiya analizinə qarşı).
        """
        if validate:
            self.validate_pin_format(pin)
        if not employee_id:
            raise ValueError("employee_id boş ola bilməz — PIN hash-i ona bağlanır")
        peppered = self._apply_pepper(pin, kind="pin", subject_id=employee_id)
        assert peppered is not None
        return self._hasher.hash(peppered)

    def verify_pin(
        self,
        stored_hash: str | None,
        pin: str,
        *,
        employee_id: str,
        pepper_version: int | None = None,
    ) -> bool:
        """PIN-i yoxlayır (sabit vaxtlı, hesab mövcud olmasa belə).

        Args:
            pepper_version: `employees.pepper_version` dəyəri. `None` → cari.
                Köhnə versiya verilibsə köhnə pepper ilə yoxlanılır; uğurlu
                olduqda çağıran tərəf `needs_pepper_rehash()` ilə yoxlayıb
                hash-i yeniləməlidir (lazy migration, SEC-005).
        """
        peppered = self._apply_pepper(
            pin, kind="pin", subject_id=employee_id, pepper_version=pepper_version
        )
        if peppered is None:
            self._verify(None, "unknown-pepper-version")  # sabit vaxt
            return False
        return self._verify(stored_hash, peppered)

    def generate_temporary_password(self, length: int = 16) -> str:
        """Admin tərəfindən təyin edilən müvəqqəti şifrə (bölmə 2).

        İstifadəçi ilk girişdə bunu MƏCBURİ dəyişir
        (`employees.must_change_password = TRUE`).
        """
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%&*"
        while True:
            candidate = "".join(secrets.choice(alphabet) for _ in range(length))
            try:
                self.password_policy.validate(candidate)
            except WeakSecretError:
                continue
            return candidate

    def generate_temporary_pin(self) -> str:
        """Admin tərəfindən sıfırlanan müvəqqəti PIN (zəif dəyərlərdən qaçır)."""
        while True:
            candidate = f"{secrets.randbelow(10**PIN_LENGTH):0{PIN_LENGTH}d}"
            if candidate not in WEAK_PINS:
                return candidate

    # ----------------------------- ümumi ------------------------------------ #

    def _verify(self, stored_hash: str | None, peppered_secret: str) -> bool:
        """Sabit-vaxtlı yoxlama.

        `stored_hash is None` (hesab yoxdur / PIN təyin edilməyib) halında da
        dummy hash yoxlanılır ki, cavab vaxtı "istifadəçi mövcuddur/yoxdur"
        məlumatını sızdırmasın.
        """
        target = stored_hash if stored_hash else self._dummy_hash
        try:
            self._hasher.verify(target, peppered_secret)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        return stored_hash is not None

    def needs_rehash(self, stored_hash: str) -> bool:
        """Argon2 parametrləri sərtləşdirilibsə `True` — girişdə yenidən hash-lə."""
        try:
            return self._hasher.check_needs_rehash(stored_hash)
        except InvalidHashError:
            return True


# --------------------------------------------------------------------------- #
# Lockout hesablaması (saf funksiya — Faza 2 use case-i bunu istifadə edir)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LockoutDecision:
    """PIN cəhdinin nəticəsi və hesabın yeni vəziyyəti."""

    accepted: bool
    is_locked: bool
    failed_attempts: int
    locked_until: datetime | None
    remaining_attempts: int
    reason: str


def evaluate_pin_attempt(
    *,
    success: bool,
    current_failed_attempts: int,
    current_locked_until: datetime | None,
    policy: PinPolicy,
    now: datetime | None = None,
) -> LockoutDecision:
    """PIN cəhdini qiymətləndirir və yeni lockout vəziyyətini qaytarır.

    Bu funksiya SAFDIR (yan təsirsiz) — DB yazısı Faza 2-dəki use case-in
    məsuliyyətidir. Beləliklə lockout məntiqi tam test oluna bilir.
    """
    moment = now or _utc_now()

    if policy.is_locked(current_locked_until, now=moment):
        return LockoutDecision(
            accepted=False,
            is_locked=True,
            failed_attempts=current_failed_attempts,
            locked_until=current_locked_until,
            remaining_attempts=0,
            reason="ACCOUNT_LOCKED",
        )

    if success:
        return LockoutDecision(
            accepted=True,
            is_locked=False,
            failed_attempts=0,  # uğurlu girişdə sayğac sıfırlanır
            locked_until=None,
            remaining_attempts=policy.max_attempts,
            reason="OK",
        )

    attempts = current_failed_attempts + 1
    if policy.should_lock(attempts):
        return LockoutDecision(
            accepted=False,
            is_locked=True,
            failed_attempts=attempts,
            locked_until=policy.lockout_until(now=moment),
            remaining_attempts=0,
            reason="LOCKED_AFTER_FAILED_ATTEMPTS",
        )

    return LockoutDecision(
        accepted=False,
        is_locked=False,
        failed_attempts=attempts,
        locked_until=None,
        remaining_attempts=policy.remaining_attempts(attempts),
        reason="WRONG_PIN",
    )
