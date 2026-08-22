"""Autentifikasiya use case-ləri (spesifikasiya bölmə 2) — Faza 2.6.

İKİ AYRI KONTEKST:

* **Admin-tier** (`AdminLoginUseCase`) — istifadəçi adı + Argon2id şifrə.
  `Root`/`CEO`/`Admin`/`HR_Admin`/`Mağaza_Meneceri`/`Kamera_Nəzarətçisi`
  bu yolla girir.
* **Kiosk PIN** (`PinHandshakeUseCase`) — 4 rəqəm, yalnız İcazə/Qayıdış və
  Morning Check-in axını üçün. `Kamera_Nəzarətçisi` bundan İSTİSNADIR.

──────────────────────────────────────────────────────────────────────────────
SEC-016: 2FA ÇIXARILDI, GİRİŞ İDENTİFİKATORU E-POÇTDAN USERNAME-Ə KEÇDİ
──────────────────────────────────────────────────────────────────────────────
Əvvəlki model e-poçt + şifrə + məcburi TOTP idi. Qərar dəyişikliyi ilə admin
girişi bir addıma endirildi: **istifadəçi adı + şifrə → dərhal sessiya**.

Bunun təhlükəsizliyə real təsiri var və gizlədilmir: TOTP oğurlanmış şifrəyə
qarşı ikinci maneə idi, indi o maneə yoxdur. Kompensasiya edən mövcud
tədbirlər:

    * Argon2id + `employee_id`-yə bağlı pepper (SEC-005) — sızmış hash-lərin
      kütləvi açılması praktik deyil;
    * admin-tərəfindən sıfırlama + `must_change_password` (e-poçt token axını
      YOXDUR, yəni poçt qutusunun ələ keçirilməsi giriş vermir);
    * hər cəhdin `security.log`-a və `security_events`-ə yazılması;
    * sessiya müddətləri (`auth_sessions`) və audit izi.

`AuthenticationError` mesajı QƏSDƏN ümumidir — "belə istifadəçi yoxdur" ilə
"şifrə səhvdir" ayrılsaydı, hesab adlarını sadalamaq mümkün olardı.

ŞİFRƏ YENİLƏNMƏSİ ADMİN-TƏRƏFİNDƏNDİR (bölmə 2): daha yüksək və ya bərabər
səlahiyyətli admin müvəqqəti şifrə təyin edir, istifadəçi ilk girişdə onu
MƏCBURİ dəyişir. Bu, e-poçt göndərmə infrastrukturuna asılılığı aradan
qaldırır.

LAZY PEPPER MIGRATION (SEC-005): uğurlu yoxlamadan sonra hash köhnə pepper
versiyası ilə yaradılıbsa, avtomatik yenidən yazılır.

──────────────────────────────────────────────────────────────────────────────
SEC-011 SESSİYA MÜDDƏTİ — SEC-5 AUDİT TAPINTISININ DÜZƏLİŞİ
──────────────────────────────────────────────────────────────────────────────
`docs/security_decisions.md` SEC-011 "Tətbiq: schema.sql §17b" yazırdı, lakin
`auth_sessions` cədvəli kod tərəfindən HEÇ VAXT yazılmır/oxunmurdu — sənəd
qorunduğunu iddia edirdi, qoruma faktiki YOX idi (dövrə debatı, SEC-5).
`SessionManagementUseCase` bu boşluğu bağlayır: `issue`/`validate`/`touch`/
`revoke`. Əsas invariant `AuthSession.touch()`-dadır (`entities/auth_session.py`)
— hərəkətsizlik pəncərəsi uzanır, mütləq tavan ƏSLA uzanmır.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from src.domain.entities.auth_session import AuthSession, SessionContext
from src.domain.entities.employee import Employee
from src.domain.interfaces.ports import (
    AuditTrail,
    AuthSessionRepository,
    Clock,
    EmployeeRepository,
    Notifier,
    PinThrottleRepository,
    SecurityEventRepository,
    SystemLimits,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    StoreId,
    TenantId,
    new_session_id,
)
from src.domain.value_objects.machine_identity import MachineIdentityHash
from src.infrastructure.security.hashing import HashingService, evaluate_pin_attempt
from src.infrastructure.security.hashing import PinPolicy as HashPinPolicy
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.text import normalise_decision_text

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Admin-tier istifadəçinin şifrəsini yeniləyə bilən flag (bölmə 2).
#: `noqa: S105` — bunlar icazə flag ADLARIdır, şifrə deyil.
RESET_PASSWORD_FLAG = "can_reset_password"  # noqa: S105
RESET_PIN_FLAG = "can_reset_pin"

#: Emergency Access Recovery üçün kimlik təsdiqi istinadının minimum uzunluğu.
MIN_RECOVERY_REFERENCE_LENGTH = 5

#: Telefon müqayisəsində nəzərə alınan son rəqəm sayı (AZ nömrəsi: 9 rəqəm).
#: Səbəb: eyni nömrə "+994 50 123 45 67", "0501234567", "994501234567" kimi
#: yazıla bilər — ölkə kodu və sıfır prefiksi normallaşdırmadan sonra da fərqli
#: qalır, ona görə müqayisə abunəçi hissəsi üzrə aparılır.
PHONE_SIGNIFICANT_DIGITS = 9


class AuthenticationError(KompasOSError):
    """Giriş uğursuz oldu.

    QƏSDƏN ÜMUMİ MESAJ: "belə istifadəçi yoxdur" və "şifrə yanlışdır"
    ayrılmır — əks halda hücumçu hansı hesab adlarının sistemdə olduğunu
    öyrənə bilər (user enumeration).
    """

    user_message = "İstifadəçi adı və ya şifrə yanlışdır."


class AccountLockedError(KompasOSError):
    """PIN lockout aktivdir (bölmə 2: 5 səhv → 15 dəqiqə)."""

    user_message = "Hesab müvəqqəti bloklanıb. Bir az sonra yenidən cəhd edin."


class TerminalLockedError(KompasOSError):
    """Terminal/maşın PIN throttle aktivdir (SEC-01/SEC-05, dövrə 3 audit).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TERMİNAL-SƏVİYYƏLİ QORUMA LAZIMDIR — VƏ NİYƏ MƏHZ BURADA
    ──────────────────────────────────────────────────────────────────────────
    PIN ANONİMDİR: `authenticate()` bütün namizədləri sınayır, heç biri
    uyğun gəlməyəndə HANSI işçinin cəhd etdiyini BİLMİR (mağazada onlarla
    işçi ola bilər). Ona görə İŞÇİ-BAŞINA lockout (`AccountLockedError`,
    `register_failure`) bu axında PRİNSİPCƏ ƏLÇATMAZDIR — sənəd "bloklama
    işçi-başınadır" deyirdi, kod isə HEÇ VAXT bunu yaza bilmirdi, çünki
    bloklanacaq KONKRET işçi yoxdur (bax `group_a_kiosk.py:364`). Bu, o
    boşluğu bağlayan İKİNCİ, MÜSTƏQİL qatdır: sayğac konkret işçiyə yox,
    `(tenant_id, machine_key)` cütünə bağlıdır — NİYƏ `store_id` DEYİL:
    bax `MachineIdentityHash`-in öz modul başlığı (SEC-05).

    ──────────────────────────────────────────────────────────────────────────
    MESAJ NİYƏ İŞÇİ KİMLİYİNİ, İŞÇİ SAYINI VƏ DƏQİQ VAXTI AÇMIR (SEC-06)
    ──────────────────────────────────────────────────────────────────────────
    `AccountLockedError` ilə EYNİ ümumi tonda — "kim bloklandı" sualının
    cavabı burada MƏNASIZ (terminal bloklanıb, konkret işçi deyil), amma
    yenə də KONKRET SƏBƏBİ (neçə cəhd, kimin, hansı mağazada) açıqlamaq
    sızma olardı. Qalan vaxt DƏQİQ saniyə ilə DEYİL, təxmini ifadə ilə
    verilir — dəqiq ədəd hücumçuya "nə vaxt yenidən sınamaq" cədvəli verərdi.
    """

    user_message = "Bu terminalda ardıcıl yanlış PIN cəhdləri oldu. Bir az sonra yenidən cəhd edin."


class TerminalThrottleUnavailableError(KompasOSError):
    """Terminal PIN throttle sətri oxuna bilmədi — FAIL-CLOSED (SEC-06).

    `_require_unlocked_throttle`-ın DB istisnasını tutub burada YENİDƏN
    atması QƏSDƏNDİR: throttle-ın ÖZÜ oxuna bilmirsə, "bloklanıbmı?"
    sualının cavabı BİLİNMİR — fail-OPEN (naməlum halı "bloklanmayıb" fərz
    edib davam etmək) SEC-01-in bütün qorumasını sükutla ləğv edərdi. Bunun
    əvəzinə PIN cəhdinin ÖZÜ rədd edilir: dayanmış kiosk DƏRHAL görünür
    (mağaza işçisi dəstəyə zəng edir), halbuki sükutla söndürülmüş qoruma
    aylarla görünməz qala bilərdi (bu auditin bütün mövzusu).
    """

    user_message = (
        "Sistem hazır deyil. Bir az sonra yenidən cəhd edin və ya administratora bildirin."
    )


class LoginStage(str, Enum):
    """Girişin nəticə vəziyyəti.

    SEC-016-dan sonra "aralıq" mərhələ YOXDUR: uğurlu istifadəçi adı + şifrə
    birbaşa `AUTHENTICATED` verir. `MUST_CHANGE_PASSWORD` isə mərhələ deyil,
    məcburi ilk-giriş şərtidir.

    `noqa: S105` — bunlar vəziyyət adlarıdır, sirr deyil.
    """

    AUTHENTICATED = "AUTHENTICATED"
    MUST_CHANGE_PASSWORD = "MUST_CHANGE_PASSWORD"  # noqa: S105


@dataclass(frozen=True)
class LoginResult:
    """Admin girişinin nəticəsi."""

    employee: Employee
    stage: LoginStage
    needs_pepper_rehash: bool = False

    @property
    def is_complete(self) -> bool:
        return self.stage is LoginStage.AUTHENTICATED


@dataclass(frozen=True)
class PinResult:
    """Kiosk PIN handshake nəticəsi."""

    employee: Employee
    remaining_attempts: int
    needs_pepper_rehash: bool = False


@dataclass(frozen=True)
class TemporaryCredential:
    """Admin tərəfindən təyin edilən müvəqqəti sirr — BİR DƏFƏ göstərilir."""

    plaintext: str
    hashed: str
    pepper_version: int


@dataclass(frozen=True)
class TenantContact:
    """`license_tenants.company_contact_email` / `_phone` (bölmə 2, 8).

    ŞİRKƏT-SƏVİYYƏLİ əlaqədir — fərdi işçi hesabından TAM AYRI. Emergency
    Access Recovery-də kimlik təsdiqinin YEGANƏ mənbəyidir.

    Niyə fərdi e-poçt DEYİL: bərpa məhz bütün admin hesabları itiriləndə
    işə düşür. Həmin hesablardan birinin e-poçtuna güvənmək məntiqsizdir —
    hesab artıq əlçatmazdır və ya ələ keçirilib. Müqavilə imzalanarkən qeyd
    olunan şirkət əlaqəsi isə hesablardan asılı deyil.
    """

    email: str
    phone: str | None = None

    def matches(self, claimed: str) -> bool:
        """Təqdim olunan əlaqə qeydiyyatdakı ilə üst-üstə düşürmü."""
        candidate = claimed.strip()
        if not candidate:
            return False
        if candidate.casefold() == self.email.strip().casefold():
            return True
        if self.phone is None:
            return False
        registered_digits = _phone_digits(self.phone)
        claimed_digits = _phone_digits(candidate)
        if not registered_digits or not claimed_digits:
            return False
        return registered_digits == claimed_digits


def _phone_digits(value: str) -> str:
    """Telefonun müqayisə üçün normallaşdırılmış son rəqəmləri."""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits[-PHONE_SIGNIFICANT_DIGITS:] if len(digits) >= PHONE_SIGNIFICANT_DIGITS else ""


# --------------------------------------------------------------------------- #
# Admin-tier giriş
# --------------------------------------------------------------------------- #


class AdminLoginUseCase:
    """İstifadəçi adı + şifrə girişi (bölmə 2, qərar SEC-016).

    TƏK ADDIM: uğurlu yoxlama birbaşa sessiya yaradır — 2FA mərhələsi yoxdur.
    """

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        hashing: HashingService,
        clock: Clock,
        audit: AuditTrail,
        security_events: SecurityEventRepository,
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._audit = audit
        # SEC-7: kompozisiya kökündə YALNIZ `FailSoftSecurityEventRecorder`
        # bağlanmalıdır (`src.shared.security_events`) — bax portun öz
        # şərhi. MƏCBURİ arqumentdir (`None` fallback-ı YOXDUR): bu, EYNİ
        # dövrə debatında "opsional = sükutla ləğv" səhvinin (SEC-8) TƏKRARI
        # olardı — yazılmayan `security_events` SEC-016-nın bütün
        # kompensasiya iddiasını yenidən boşaldardı.
        self._security_events = security_events

    def login(
        self,
        *,
        tenant_id: TenantId,
        username: Username,
        password: str,
        stored_hash: str | None,
        pepper_version: int = 1,
        ip_address: str | None = None,
        machine_name: str | None = None,
    ) -> LoginResult:
        """İstifadəçi adı + şifrə yoxlaması.

        `stored_hash` repo-dan AYRICA ötürülür: hash domen entity-sində
        saxlanılmır ki, təsadüfən log-a və ya DTO-ya düşməsin.

        Args:
            ip_address, machine_name: SEC-7 — `security_events` sətrinin
                mənşə sahələri. OPSİONALDIR: `None` "bilinmir" deməkdir
                (şəbəkə qatı bunu hələ ötürmür), sükutla ləğv etmək DEYİL —
                sahə `security_events`-də NULL qala bilər, bu, sxemdə
                artıq nəzərdə tutulub.
        """
        employee = self._employees.get_by_username(tenant_id, username)

        # Hesab yoxdursa belə Argon2 hesablaması APARILIR: əks halda mövcud
        # olmayan hesab ~milisaniyələrlə daha tez cavab verər və hücumçu
        # cavab müddətinə görə hesabları sadalaya bilərdi (timing oracle).
        password_ok = self._hashing.verify_password(
            stored_hash, password, pepper_version=pepper_version
        )
        if employee is None or not password_ok:
            reason = "UNKNOWN_ACCOUNT" if employee is None else "BAD_PASSWORD"
            _security_log.warning(
                "LOGIN_FAILED",
                extra={
                    "username_attempt": str(username),
                    "tenant_id": str(tenant_id),
                    "reason": reason,
                },
            )
            self._security_events.record(
                tenant_id=tenant_id,
                event_type="LOGIN_FAILED",
                employee_id=employee.id if employee is not None else None,
                username_attempt=str(username),
                ip_address=ip_address,
                machine_name=machine_name,
                details={"reason": reason},
            )
            raise AuthenticationError(
                "İstifadəçi adı və ya şifrə yanlışdır",
                context={"username": str(username)},
            )

        employee.assert_admin_login_allowed()

        needs_rehash = self._hashing.needs_pepper_rehash(pepper_version)

        if employee.must_change_password:
            _security_log.info(
                "LOGIN_PASSWORD_CHANGE_REQUIRED", extra={"employee_id": str(employee.id)}
            )
            return LoginResult(
                employee=employee,
                stage=LoginStage.MUST_CHANGE_PASSWORD,
                needs_pepper_rehash=needs_rehash,
            )

        self._record_login(
            employee, method="USERNAME_PASSWORD", ip_address=ip_address, machine_name=machine_name
        )
        return LoginResult(
            employee=employee,
            stage=LoginStage.AUTHENTICATED,
            needs_pepper_rehash=needs_rehash,
        )

    def _record_login(
        self,
        employee: Employee,
        *,
        method: str,
        ip_address: str | None = None,
        machine_name: str | None = None,
    ) -> None:
        _security_log.info(
            "LOGIN_SUCCESS",
            extra={
                "employee_id": str(employee.id),
                "role": employee.position.code,
                "method": method,
            },
        )
        self._audit.record(
            tenant_id=employee.tenant_id,
            actor_id=employee.id,
            action="ADMIN_LOGIN",
            entity_type="employees",
            entity_id=employee.id,
            after_state={"method": method},
        )
        self._security_events.record(
            tenant_id=employee.tenant_id,
            event_type="LOGIN_SUCCESS",
            employee_id=employee.id,
            ip_address=ip_address,
            machine_name=machine_name,
            details={"method": method},
        )


# --------------------------------------------------------------------------- #
# Kiosk PIN
# --------------------------------------------------------------------------- #


class PinHandshakeUseCase:
    """Kiosk PIN yoxlaması + lockout (bölmə 2, 4)."""

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        hashing: HashingService,
        clock: Clock,
        limits: SystemLimits,
        audit: AuditTrail,
        security_events: SecurityEventRepository,
        pin_throttle: PinThrottleRepository,
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._limits = limits
        self._audit = audit
        self._security_events = security_events  # SEC-7 — bax `AdminLoginUseCase`-in şərhi
        # SEC-01, dövrə 3 — bax `TerminalLockedError`-in şərhi VƏ `authenticate()`-in
        # "TERMİNAL THROTTLE" bölməsi. MƏCBURİ arqumentdir (`None` fallback-ı
        # YOXDUR) — SEC-7/SEC-8-dəki eyni dərs: yazılmayan asılılıq sükutla
        # BÜTÜN qorumanı ləğv edərdi.
        self._pin_throttle = pin_throttle

    def authenticate(
        self,
        *,
        tenant_id: TenantId,
        store_id: StoreId,
        machine_key: MachineIdentityHash,
        pin: str,
        pin_hashes: dict[EmployeeId, tuple[str, int]],
        ip_address: str | None = None,
        machine_name: str | None = None,
    ) -> PinResult:
        """Mağazadakı işçilər arasında PIN sahibini tapır.

        Args:
            pin_hashes: `{employee_id: (hash, pepper_version)}` — repo-dan gəlir.
            machine_key: Terminalın aparat kimliyinin heşi (SEC-05) — bax
                `_require_unlocked_throttle`-ın şərhi. Çağıran (kiosk
                kontrolleri) bunu XAM `MachineGuid`-i OXUMADAN, artıq
                heşlənmiş şəkildə ötürür (`device_identity.py`-nin işi,
                domen/tətbiq qatı `winreg` idxal ETMİR).

        PIN `employee_id`-yə bağlı hash-ləndiyi üçün (SEC-005) hər namizəd
        AYRICA yoxlanılır. Bu, mağazadakı işçi sayı qədər Argon2 hesablaması
        deməkdir — mağaza başına onlarla işçi olduğu üçün qəbul ediləndir.

        ──────────────────────────────────────────────────────────────────────
        TERMİNAL THROTTLE (SEC-01/SEC-05, dövrə 3) — NAMİZƏD DÖVRƏSİNDƏN ƏVVƏL
        ──────────────────────────────────────────────────────────────────────
        `_require_unlocked_throttle()` KİLİDLİ oxu ilə terminal ARTIQ
        bloklanıbsa dərhal `TerminalLockedError` atır — namizəd dövrəsi HEÇ
        BAŞLAMIR, yəni bloklanmış terminalda hər klaviatura basışı üçün
        onlarla Argon2 hesablaması BOŞA getmir.
        """
        now = self._clock.now()
        self._require_unlocked_throttle(
            tenant_id,
            machine_key,
            store_id=store_id,
            now=now,
            ip_address=ip_address,
            machine_name=machine_name,
        )
        policy = self._pin_policy(tenant_id)
        candidates = self._employees.find_by_pin_candidates(tenant_id, store_id)

        for employee in candidates:
            entry = pin_hashes.get(employee.id)
            if entry is None or not employee.can_use_kiosk_pin:
                continue

            stored_hash, pepper_version = entry
            if employee.is_pin_locked(now=now):
                # Bloklanmış hesabda DOĞRU PIN də qəbul edilmir.
                if self._hashing.verify_pin(
                    stored_hash,
                    pin,
                    employee_id=str(employee.id),
                    pepper_version=pepper_version,
                ):
                    self._log_attempt(employee, success=False, reason="ACCOUNT_LOCKED")
                    raise AccountLockedError(
                        "Hesab müvəqqəti bloklanıb",
                        context={"employee_id": str(employee.id)},
                    )
                continue

            if not self._hashing.verify_pin(
                stored_hash,
                pin,
                employee_id=str(employee.id),
                pepper_version=pepper_version,
            ):
                continue

            decision = evaluate_pin_attempt(
                success=True,
                current_failed_attempts=employee.pin_security.failed_attempts,
                current_locked_until=employee.pin_security.locked_until,
                policy=policy,
                now=now,
            )
            employee.register_successful_pin_attempt()
            self._employees.save(employee)
            self._log_attempt(employee, success=True, reason="OK")
            # SEC-01, dövrə 3 — TERMİNAL sayğacı BURADA QƏSDƏN TOXUNULMUR.
            # "Uğurlu giriş sıfırlamalıdırmı?" qərarı `PinThrottleRepository`-
            # nin öz şərhindədir (`ports.py`): sıfırlama olsaydı, hücumçu
            # N-1 cəhd edib növbəti qanuni girişi gözləməklə sayğacı PULSUZ
            # təmizləyərdi. Sabit pəncərə (DB-də) təbii decay verir.

            return PinResult(
                employee=employee,
                remaining_attempts=decision.remaining_attempts,
                needs_pepper_rehash=self._hashing.needs_pepper_rehash(pepper_version),
            )

        # Heç bir namizədə uyğun gəlmədi.
        _security_log.warning(
            "PIN_FAILED",
            extra={
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "candidate_count": len(candidates),
            },
        )
        # `employee_id`/`username_attempt` YOXDUR: PIN heç bir işçiyə uyğun
        # gəlmədi, yəni "kim cəhd etdi" sualının domen səviyyəsində cavabı
        # yoxdur (bölmə 2-nin PIN-in özü identifikator olmaması qərarı).
        self._security_events.record(
            tenant_id=tenant_id,
            event_type="PIN_FAILED",
            ip_address=ip_address,
            machine_name=machine_name,
            details={"store_id": str(store_id), "candidate_count": len(candidates)},
        )
        # SEC-01, dövrə 3 — TERMİNAL sayğacı BURADA artırılır: bu, ANONİM
        # uğursuzluqdur (heç bir işçiyə uyğun gəlmədi), yəni məhz throttle-ın
        # qorumaq istədiyi hal. Artırma DB-də ATOMİKDİR (`record_failure`) —
        # `_require_unlocked_throttle`-dakı kilidli oxu YALNIZ "bloklanıbmı?"
        # sualına cavab verir, sayğacı ÖZÜ dəyişmir.
        self._record_throttle_failure(
            tenant_id,
            machine_key,
            store_id=store_id,
            ip_address=ip_address,
            machine_name=machine_name,
        )
        raise AuthenticationError(
            "PIN heç bir işçiyə uyğun gəlmədi",
            user_message="PIN yanlışdır.",
        )

    def register_failure(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        ip_address: str | None = None,
        machine_name: str | None = None,
    ) -> tuple[bool, int]:
        """Konkret işçi üçün səhv cəhdi qeyd edir (UI PIN sahibini bilirsə).

        Returns:
            `(bloklandı, qalan cəhd sayı)`.
        """
        now = self._clock.now()
        policy = self._pin_policy(tenant_id)
        decision = evaluate_pin_attempt(
            success=False,
            current_failed_attempts=employee.pin_security.failed_attempts,
            current_locked_until=employee.pin_security.locked_until,
            policy=policy,
            now=now,
        )
        employee.pin_security.failed_attempts = decision.failed_attempts
        employee.pin_security.locked_until = decision.locked_until
        self._employees.save(employee)

        self._log_attempt(employee, success=False, reason=decision.reason)
        if decision.is_locked:
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="PIN_LOCKOUT",
                entity_type="employees",
                entity_id=employee.id,
                after_state={
                    "failed_attempts": decision.failed_attempts,
                    "locked_until": decision.locked_until.isoformat()
                    if decision.locked_until
                    else None,
                },
            )
            # SEC-7 audit tapıntısı: bu HADİSƏ ƏVVƏL yalnız DB `audit_logs`-a
            # düşürdü, `security.log` FAYL kanalına HEÇ VAXT — lockout məhz
            # izlənməli hadisədir (qəbul edilmiş boşluq, bağlanır).
            _security_log.warning(
                "PIN_LOCKOUT",
                extra={
                    "employee_id": str(employee.id),
                    "failed_attempts": decision.failed_attempts,
                },
            )
            self._security_events.record(
                tenant_id=tenant_id,
                event_type="PIN_LOCKOUT",
                employee_id=employee.id,
                ip_address=ip_address,
                machine_name=machine_name,
                details={"failed_attempts": decision.failed_attempts},
            )
        return decision.is_locked, decision.remaining_attempts

    def _pin_policy(self, tenant_id: TenantId) -> HashPinPolicy:
        return HashPinPolicy(
            max_attempts=self._limit_int(tenant_id, SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS),
            lockout_minutes=self._limit_int(tenant_id, SystemLimitKey.PIN_LOCKOUT_MINUTES),
        )

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))

    def _require_unlocked_throttle(
        self,
        tenant_id: TenantId,
        machine_key: MachineIdentityHash,
        *,
        store_id: StoreId,
        now: datetime,
        ip_address: str | None,
        machine_name: str | None,
    ) -> None:
        """KİLİDLİ oxu — terminal ARTIQ bloklanıbsa `TerminalLockedError` atır.

        ──────────────────────────────────────────────────────────────────────
        FAIL-CLOSED (SEC-06 tövsiyəsi)
        ──────────────────────────────────────────────────────────────────────
        Throttle sətri OXUNA BİLMİRSƏ (DB nasazlığı) PIN cəhdi RƏDD EDİLİR —
        fail-OPEN (yoxlamanı keçib davam etmək) YOX. Səbəb: sükutla
        söndürülmüş qoruma məhz SEC-01-in ÖZÜDÜR (bu auditin bütün mövzusu)
        və aylarla görünmədən qala bilər — halbuki dayanmış kiosk DƏRHAL
        bildirilir (mağaza işçisi dərhal dəstəyə zəng edir). Səhv `critical`
        səviyyəsində loglanır ki, monitorinqdə görünməz qalmasın.

        ──────────────────────────────────────────────────────────────────────
        KLON AŞKARLAMASI (team-lead-in əlavə tapşırığı)
        ──────────────────────────────────────────────────────────────────────
        `MachineIdentityHash` sysprep edilməmiş klon disk imicində N maşında
        EYNİ ola bilər (Windows-un tanınmış qüsuru) — belə olduqda N mağaza
        EYNİ throttle sətrini paylaşar, bir mağazanın yazı səhvləri hamısını
        kilidləyə bilər. BLOKLAMIRIQ (kilid 15 dəq-dən sonra öz-özünə
        sağalır, DAYANDIRICI DEYİL), AMMA sükutla keçmirik: sətirdə saxlanmış
        `store_id` CARİ `store_id`-dən FƏRQLİDİRSƏ, bu, HƏMİN maşının BAŞQA
        mağazadan da PIN cəhdi göndərdiyinin işarəsidir — bir dəfə iz
        buraxılır və sətir YENİLƏNİR (təkrar siqnal göndərməmək üçün).
        Qərarı VERƏN bu use case-dir, repo YOX (qat sırası: repo yalnız
        saxlanmış dəyəri qaytarır).
        """
        try:
            throttle = self._pin_throttle.get_for_update(tenant_id, machine_key)
        except Exception as exc:
            _security_log.critical(
                "PIN_TERMINAL_THROTTLE_UNAVAILABLE",
                extra={"tenant_id": str(tenant_id), "store_id": str(store_id)},
                exc_info=True,
            )
            raise TerminalThrottleUnavailableError(
                "Terminal PIN throttle sətri oxuna bilmədi",
                context={"tenant_id": str(tenant_id), "store_id": str(store_id)},
            ) from exc

        if throttle is None:
            return

        if throttle.store_id != store_id:
            _security_log.warning(
                "SUSPECTED_CLONED_MACHINE_GUID",
                extra={
                    "tenant_id": str(tenant_id),
                    "previous_store_id": str(throttle.store_id),
                    "current_store_id": str(store_id),
                },
            )
            self._security_events.record(
                tenant_id=tenant_id,
                event_type="SUSPECTED_CLONED_MACHINE_GUID",
                ip_address=ip_address,
                machine_name=machine_name,
                details={
                    "previous_store_id": str(throttle.store_id),
                    "current_store_id": str(store_id),
                },
            )
            self._pin_throttle.update_last_seen_store(tenant_id, machine_key, store_id=store_id)

        if throttle.is_locked(now=now):
            _security_log.warning(
                "PIN_TERMINAL_LOCKED",
                extra={
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "trigger": "REJECTED_WHILE_LOCKED",
                },
            )
            self._security_events.record(
                tenant_id=tenant_id,
                event_type="PIN_TERMINAL_LOCKED",
                ip_address=ip_address,
                machine_name=machine_name,
                details={
                    "store_id": str(store_id),
                    "trigger": "REJECTED_WHILE_LOCKED",
                    "locked_until": throttle.locked_until.isoformat()
                    if throttle.locked_until
                    else None,
                },
            )
            raise TerminalLockedError(
                "Terminal PIN throttle aktivdir",
                context={"tenant_id": str(tenant_id), "store_id": str(store_id)},
            )

    def _record_throttle_failure(
        self,
        tenant_id: TenantId,
        machine_key: MachineIdentityHash,
        *,
        store_id: StoreId,
        ip_address: str | None,
        machine_name: str | None,
    ) -> None:
        """Anonim uğursuz cəhdi terminal sayğacına ATOMİK yazır — pəncərə/kilid
        hesablaması DB trigger-indədir (bax `PinThrottleRepository.
        record_failure`-in şərhi, TIME-1).

        `_require_unlocked_throttle` bu çağırışdan ƏVVƏL ARTIQ "bloklanmayıb"
        olduğunu təsdiqləyib — ona görə NƏTİCƏDƏ `locked_until` DOLUDURSA,
        MƏHZ BU cəhd həddi keçdi (köhnə/yeni müqayisəsinə ehtiyac yoxdur).
        """
        result = self._pin_throttle.record_failure(tenant_id, machine_key, store_id=store_id)
        if result.locked_until is not None:
            _security_log.warning(
                "PIN_TERMINAL_LOCKED",
                extra={
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "trigger": "NEW_LOCKOUT",
                    "failed_count": result.failed_count,
                },
            )
            self._security_events.record(
                tenant_id=tenant_id,
                event_type="PIN_TERMINAL_LOCKED",
                ip_address=ip_address,
                machine_name=machine_name,
                details={
                    "store_id": str(store_id),
                    "trigger": "NEW_LOCKOUT",
                    "failed_count": result.failed_count,
                    "locked_until": result.locked_until.isoformat(),
                },
            )

    @staticmethod
    def _log_attempt(employee: Employee, *, success: bool, reason: str) -> None:
        _security_log.info(
            "PIN_ATTEMPT",
            extra={
                "employee_id": str(employee.id),
                "success": success,
                "reason": reason,
            },
        )


# --------------------------------------------------------------------------- #
# Sessiya müddəti (SEC-011)
# --------------------------------------------------------------------------- #

#: `secrets.token_urlsafe(32)` → 256 bit entropiya (SEC-5 müqaviləsi).
SESSION_TOKEN_BYTES: Final = 32

#: Uzaqdan sessiya ləğvini bağlayan flag — AYRICADIR, `can_reset_password`
#: DEYİL (security2 verdikti, SEC-5 debatı).
#:
#: NİYƏ BİRLƏŞDİRİLMİR — layihənin ÖZ PRESEDENTİ buna qarşıdır: `can_reset_pin`
#: və `can_reset_password` da "kimliyi sıfırlama" mənasında OXŞARDIR, amma
#: BİRLƏŞDİRİLMƏYİB, çünki risk dairələri fərqlidir. Sessiya ləğvi ilə şifrə
#: sıfırlanması arasındakı risk fərqi BUNDAN DA BÖYÜKDÜR: şifrəni sıfırlayan
#: admin subyektin hesabına TAM giriş əldə edir (kimlik oğurluğu ekvivalenti —
#: yeni şifrəni bilən istənilən kəs daxil ola bilər), sessiya ləğv edən isə
#: YALNIZ məcburi yenidən-giriş tələb edir (məlumat itkisi YOXDUR, səlahiyyət
#: artımı YOXDUR — subyekt sadəcə şifrəsi ilə YENİDƏN daxil olur).
#: `can_reset_password` təkrar işlətmək desək, "şübhəli sessiyanı bağla"
#: səlahiyyəti verən Root eyni zamanda subyektin hesabını ələ keçirmə
#: səlahiyyəti də vermiş olardı — bu, tələb olunan səlahiyyətdən QAT-QAT
#: genişdir (Least Privilege pozuntusu).
#:
#: Hardlock səviyyəsi `can_reset_password` ilə EYNİDİR (infra miqrasiyası),
#: defolt olaraq HEÇ BİR rola avtomatik verilmir — Root əl ilə təyin edir.
REVOKE_SESSION_FLAG = "can_revoke_sessions"

_IDLE_TIMEOUT_KEYS: Final[dict[SessionContext, SystemLimitKey]] = {
    SessionContext.ADMIN_PANEL: SystemLimitKey.ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES,
}
_ABSOLUTE_TIMEOUT_KEYS: Final[dict[SessionContext, SystemLimitKey]] = {
    SessionContext.ADMIN_PANEL: SystemLimitKey.ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS,
    SessionContext.CAMERA_DASHBOARD: SystemLimitKey.CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS,
}


def _hash_session_token(token: str) -> str:
    """Sessiya tokeninin SHA-256 daycesti (SEC-011: DB açıq token saxlamır).

    Argon2/pepper İŞLƏDİLMİR — bu, `hash_password`/`hash_pin`-dən QƏSDƏN
    FƏRQLİDİR: token insanın seçdiyi aşağı-entropiyalı sirr DEYİL,
    `secrets.token_urlsafe(32)`-nin 256 bitlik təsadüfi çıxışıdır. Yavaş
    (Argon2) heşləmə burada FAYDA vermir (brute-force onsuz da praktik
    deyil), YALNIZ hər `validate()` çağırışını lazımsız ləngidərdi — sessiya
    yoxlaması HƏR sorğuda işləyən yoldur (bax `touch()` çağırış tezliyi).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionExpiredError(KompasOSError):
    """Sessiya etibarsızdır: müddəti bitib, ya da ləğv edilib (SEC-011)."""

    user_message = "Sessiyanızın müddəti bitdi. Yenidən daxil olun."


class SessionContextNotSupportedError(KompasOSError):
    """`KIOSK` kontekstinə sessiya ISSUE edilmək İSTƏNİB (SEC-011: PIN, sessiya yox)."""

    user_message = "Bu giriş növü sessiya tələb etmir."


@dataclass(frozen=True)
class IssuedSession:
    """`issue()`-nin BİR DƏFƏLİK nəticəsi.

    Açıq `token` YALNIZ burada mövcuddur — `AuthSession.token_hash` ondan
    GERİ hesablana bilməz. GUI onu yaddaşda saxlayır, diskə YAZMIR (SEC-5
    müqaviləsi, ui bölməsi).
    """

    session: AuthSession
    token: str


class SessionManagementUseCase:
    """SEC-011 sessiya müddəti idarəsi — `auth_sessions` (schema.sql §17b).

    Dörd əməliyyat: `issue` (giriş), `validate` (hər qorunan sorğu),
    `touch` (fəaliyyət → hərəkətsizlik pəncərəsini uzadır), `revoke`
    (çıxış/admin ləğvi). Əsas invariantın (`absolute_expiry` uzanmır) həqiqi
    yeri `AuthSession.touch()`-dadır (entity) — bu sinif YALNIZ limitləri
    `system_limits`-dən oxuyub entity-yə ötürür və audit yazır.

    ──────────────────────────────────────────────────────────────────────────
    "MÜDDƏT BİTMƏSİ" AUDİTİ NİYƏ `revoke()`-Ə YÖNLƏNDİRİLİR
    ──────────────────────────────────────────────────────────────────────────
    SEC-5 müqaviləsi: "giriş, ləğv VƏ müddət bitməsi audit izi almalıdır."
    Ayrıca "expired" bayrağı sxemdə YOXDUR (yalnız `revoked_at`), ona görə
    `validate()` müddəti bitmiş, lakin HƏLƏ `revoked_at`-i boş olan sessiyanı
    TAPAN KİMİ onu `revoked_by=None` ilə ləğv edir və BİR DƏFƏLİK audit yazır.
    Növbəti `validate()` çağırışında `is_revoked` artıq `True`-dur — təkrar
    audit YAZILMIR (sükutla dublikat yaratmadan, `SESSION_REVOKED`-in özü
    kimi tək dəfəlik iz qalır).
    """

    def __init__(
        self,
        *,
        sessions: AuthSessionRepository,
        clock: Clock,
        limits: SystemLimits,
        audit: AuditTrail,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._limits = limits
        self._audit = audit

    def issue(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        context: SessionContext,
        machine_name: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedSession:
        """Girişdən SONRA çağırılır — token yaradır, `token_hash`-i yazır."""
        if context not in _ABSOLUTE_TIMEOUT_KEYS:
            raise SessionContextNotSupportedError(
                f"'{context.value}' konteksti sessiya ilə idarə olunmur",
                context={"context": context.value},
            )
        now = self._clock.now()
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        absolute_expiry = now + self._absolute_timeout(tenant_id, context)
        idle_expiry = (
            now + self._idle_timeout(tenant_id, context)
            if context.has_idle_timeout
            else absolute_expiry
        )
        session = AuthSession(
            id=new_session_id(),
            tenant_id=tenant_id,
            user_id=employee.id,
            token_hash=_hash_session_token(token),
            context=context,
            issued_at=now,
            expires_at=min(idle_expiry, absolute_expiry),
            last_seen_at=now,
            absolute_expiry=absolute_expiry,
            machine_name=machine_name,
            ip_address=ip_address,
        )
        self._sessions.save(session)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="SESSION_ISSUED",
            entity_type="auth_sessions",
            entity_id=session.id,
            after_state={
                "context": context.value,
                "expires_at": session.expires_at.isoformat(),
                "absolute_expiry": absolute_expiry.isoformat(),
            },
        )
        return IssuedSession(session=session, token=token)

    def validate(self, *, tenant_id: TenantId, token: str) -> AuthSession:
        """Hər qorunan sorğuda çağırılır. Etibarsızdırsa `SessionExpiredError`."""
        now = self._clock.now()
        session = self._sessions.get_by_token_hash(tenant_id, _hash_session_token(token))
        if session is None:
            raise SessionExpiredError("Sessiya tapılmadı", context={"tenant_id": str(tenant_id)})
        if not session.is_valid(now=now):
            self._expire_if_needed(tenant_id, session, now=now)
            raise SessionExpiredError(
                "Sessiyanın müddəti bitib və ya ləğv edilib",
                context={"session_id": str(session.id)},
            )
        return session

    def touch(self, *, tenant_id: TenantId, session: AuthSession) -> AuthSession:
        """İstifadəçi fəaliyyəti — hərəkətsizlik pəncərəsini uzadır.

        `CAMERA_DASHBOARD` üçün SÜKUTLA HEÇ NƏ YAZMIR: `AuthSession.touch()`
        özü no-op edir (bax entity docstring-i), lazımsız DB yazısının
        qarşısını burada, sorğu getmədən ALIRIQ (PERF-1/2/3 fəlsəfəsi).
        """
        if not session.context.has_idle_timeout:
            return session
        now = self._clock.now()
        session.touch(now=now, idle_timeout=self._idle_timeout(tenant_id, session.context))
        self._sessions.save(session)
        return session

    def revoke(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        target: AuthSession,
        reason: str,
    ) -> None:
        """Çıxış (özü) və ya admin uzaqdan ləğvi.

        Özünü ləğv etmək HƏR KƏSƏ açıqdır — `CredentialResetUseCase`-dən
        FƏRQLİ olaraq özü-özünü istisna ETMİR, çünki "Çıxış" düyməsi məhz
        budur.
        """
        self._require_may_revoke(actor, target)
        now = self._clock.now()
        target.revoke(revoked_by=actor.id, reason=reason, now=now)
        self._sessions.save(target)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="SESSION_REVOKED",
            entity_type="auth_sessions",
            entity_id=target.id,
            after_state={
                "reason": target.revocation_reason,
                "subject_user_id": str(target.user_id),
            },
        )

    def _expire_if_needed(
        self, tenant_id: TenantId, session: AuthSession, *, now: datetime
    ) -> None:
        if session.is_revoked:
            # Artıq ləğv edilib (əl ilə və ya əvvəlki `_expire_if_needed` çağırışı
            # ilə) — təkrar audit yazılmır, dublikat yaratmır.
            return
        session.revoke(revoked_by=None, reason="Sessiya müddəti bitdi (timeout)", now=now)
        self._sessions.save(session)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=session.user_id,
            action="SESSION_EXPIRED",
            entity_type="auth_sessions",
            entity_id=session.id,
            after_state={"reason": "IDLE_OR_ABSOLUTE_TIMEOUT"},
        )

    def _require_may_revoke(self, actor: Employee, target: AuthSession) -> None:
        if actor.id == target.user_id:
            return
        if not actor.has_permission(REVOKE_SESSION_FLAG, now=self._clock.now()):
            raise AuthenticationError(
                f"'{REVOKE_SESSION_FLAG}' səlahiyyəti olmadan başqasının sessiyası "
                f"ləğv edilə bilməz",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id), "target_session_id": str(target.id)},
            )

    def _idle_timeout(self, tenant_id: TenantId, context: SessionContext) -> timedelta:
        key = _IDLE_TIMEOUT_KEYS[context]
        minutes = self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        return timedelta(minutes=minutes)

    def _absolute_timeout(self, tenant_id: TenantId, context: SessionContext) -> timedelta:
        key = _ABSOLUTE_TIMEOUT_KEYS[context]
        hours = self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        return timedelta(hours=hours)


# --------------------------------------------------------------------------- #
# Admin-tərəfindən sıfırlama (bölmə 2)
# --------------------------------------------------------------------------- #


class CredentialResetUseCase:
    """Şifrə/PIN sıfırlanması — E-POÇT TOKEN AXINI YOXDUR (bölmə 2).

    Daha yüksək və ya bərabər səlahiyyətli admin müvəqqəti sirr təyin edir,
    istifadəçi ilk girişdə onu MƏCBURİ dəyişir. Eyni model həm şifrə, həm PIN
    üçün istifadə olunur.

    ──────────────────────────────────────────────────────────────────────────
    BU SİNİF İSTEHSALAT YOLUNA QOŞULU DEYİL — ÖLÜ KOD DEYİL, ALTERNATİV YOLDUR
    ──────────────────────────────────────────────────────────────────────────
    `src/` boyu onu quran heç bir yer YOXDUR: GUI-dəki `[Şifrəni Yenilə]`
    düyməsi `UserManagementUseCase.reset_password`-a gedir, çünki oradakı axın
    admin tərəfindən YAZILAN şifrəni qəbul edir. Burada isə şifrəni SİSTEM
    generasiya edir (`generate_temporary_password`) — bu, sonradan lazım olan
    ayrıca ssenaridir (toplu sıfırlama, kiosk PIN-lərinin kütləvi yenilənməsi)
    və `bulk_operations.py` başlığı ona istinad edir. Ona görə SİLİNMİR.

    Lakin qoşulmaması onun daxilindəki qüsuru bağışlamır: hər iki metod heşi
    ARTIQ `update_credentials()` ilə yazır (`recover()` ilə eyni səbəb). Əks
    halda gələcəkdə bu sinfi qoşan adam eyni "şifrə göstərildi, yazılmadı"
    tələsinə düşərdi.
    """

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        hashing: HashingService,
        clock: Clock,
        audit: AuditTrail,
        notifier: Notifier,
        security_events: SecurityEventRepository,
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._audit = audit
        self._notifier = notifier
        self._security_events = security_events  # SEC-7 — bax `AdminLoginUseCase`-in şərhi

    def reset_password(self, *, actor: Employee, subject: Employee) -> TemporaryCredential:
        """Admin-tier istifadəçi üçün müvəqqəti şifrə təyin edir."""
        self._assert_may_reset(actor, subject, flag=RESET_PASSWORD_FLAG, kind="şifrə")

        temporary = self._hashing.generate_temporary_password()
        hashed = self._hashing.hash_password(temporary)
        subject.must_change_password = True
        self._employees.save(subject)
        # `save()` sirrlərə toxunmur — heş AYRICA yazılmalıdır (bax sinif
        # başlığı və `EmployeeRepository.update_credentials`).
        self._employees.update_credentials(
            subject.id,
            password_hash=hashed,
            pepper_version=self._hashing.current_pepper_version,
        )

        self._audit_reset(actor, subject, action="PASSWORD_RESET")
        return TemporaryCredential(
            plaintext=temporary,
            hashed=hashed,
            pepper_version=self._hashing.current_pepper_version,
        )

    def reset_pin(self, *, actor: Employee, subject: Employee) -> TemporaryCredential:
        """İşçi üçün müvəqqəti PIN təyin edir."""
        self._assert_may_reset(actor, subject, flag=RESET_PIN_FLAG, kind="PIN")

        temporary = self._hashing.generate_temporary_pin()
        hashed = self._hashing.hash_pin(temporary, employee_id=str(subject.id))
        subject.register_successful_pin_attempt()  # lockout sıfırlanır
        self._employees.save(subject)
        # PIN heşi `employee_id`-yə bağlıdır (SEC-005), ona görə `pepper_version`
        # onunla birlikdə yazılır — köhnə versiya qalsaydı yoxlama uyğun gəlməzdi.
        self._employees.update_credentials(
            subject.id,
            pin_hash=hashed,
            pepper_version=self._hashing.current_pepper_version,
        )

        self._audit_reset(actor, subject, action="PIN_RESET")
        return TemporaryCredential(
            plaintext=temporary,
            hashed=hashed,
            pepper_version=self._hashing.current_pepper_version,
        )

    def _assert_may_reset(
        self, actor: Employee, subject: Employee, *, flag: str, kind: str
    ) -> None:
        now = self._clock.now()
        if actor.id == subject.id:
            raise AuthenticationError(
                f"İstifadəçi öz {kind}sini bu axınla sıfırlaya bilməz",
                user_message=f"Öz {kind}nizi bu yolla sıfırlaya bilməzsiniz.",
            )
        if not actor.has_permission(flag, now=now):
            raise AuthenticationError(
                f"'{flag}' səlahiyyəti olmadan {kind} sıfırlana bilməz",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id), "flag": flag},
            )
        # Bölmə 2: "daha yüksək və ya BƏRABƏR səlahiyyətli başqa bir admin".
        # Ona görə burada `outranks` DEYİL, `<=` müqayisəsi istifadə olunur —
        # Hierarchy Guard-dan (icazə dəyişikliyi) FƏRQLİ qayda.
        #
        # ROOT/CEO PRİORİTET AYRILIĞININ BİRBAŞA NƏTİCƏSİ: `CEO` artıq `Root`
        # hesabının sirrini sıfırlaya BİLMİR. Köhnə modeldə ikisi də 0 idi,
        # yəni `0 > 0` yanlış çıxır və CEO `Root`-a müvəqqəti şifrə təyin edə
        # bilirdi — həmin şifrə ilə isə `Root` hesabına GİRMƏK mümkündür, yəni
        # bütün `ROOT_ONLY` hardlock-ları bir addımla dolayı yan keçilirdi.
        # Bərabər pillə istisnası qalır (Root → Root), əks halda tək Root-lu
        # tenant unudulmuş şifrə ilə kilidlənərdi.
        if actor.priority > subject.priority:
            raise AuthenticationError(
                f"Aktor daha aşağı səlahiyyət pilləsindədir "
                f"({actor.priority.name} > {subject.priority.name})",
                user_message="Bu istifadəçinin sirrini sıfırlaya bilməzsiniz.",
            )

    def _audit_reset(self, actor: Employee, subject: Employee, *, action: str) -> None:
        _security_log.warning(
            action,
            extra={
                "actor_id": str(actor.id),
                "actor_role": actor.position.code,
                "subject_id": str(subject.id),
            },
        )
        self._audit.record(
            tenant_id=subject.tenant_id,
            actor_id=actor.id,
            action=action,
            entity_type="employees",
            entity_id=subject.id,
            after_state={"must_change_password": subject.must_change_password},
        )
        # SEC-7, Tier 2: `audit_logs`-da ARTIQ var — `security_events` IP/
        # cihaz qatını ƏLAVƏ edir (bura hələ ötürülmür, `None` qalır; UI
        # bu axına qoşulanda doldurar).
        self._security_events.record(
            tenant_id=subject.tenant_id,
            event_type=action,
            employee_id=subject.id,
            details={"actor_id": str(actor.id), "actor_role": actor.position.code},
        )
        self._notifier.notify(
            tenant_id=subject.tenant_id,
            recipient_id=subject.id,
            category=action,
            title_az="Giriş məlumatlarınız sıfırlandı",
            body_az=(
                "Administrator sizin üçün müvəqqəti giriş məlumatı təyin etdi. "
                "İlk girişdə onu dəyişməlisiniz."
            ),
            is_critical=False,
        )


class EmergencyAccessRecoveryUseCase:
    """Son tədbir: tenant-ın BÜTÜN admin hesabları itirilibsə (bölmə 2).

    Developer Panelindən, kimlik təsdiqi əsasında, BİR DƏFƏLİK işə salınır.
    Tam audit-lənir və tenant-a bildiriş göndərilir.

    ÜÇ QORUYUCU BİRLİKDƏ İŞLƏYİR:

        1. Tenant-da AKTİV admin-tier hesab QALMAMALIDIR — əks halda bu
           prosedur adi "arxa qapı"ya çevrilərdi.
        2. Müraciət edən şəxs `license_tenants.company_contact_email` və ya
           `company_contact_phone` ilə təsdiqlənməlidir (SEC-016) — fərdi
           işçi e-poçtu ilə DEYİL.
        3. Kimlik təsdiqinin izi (`developer_reference`) məcburidir və
           audit-ə yazılır.
    """

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        hashing: HashingService,
        clock: Clock,
        audit: AuditTrail,
        notifier: Notifier,
        security_events: SecurityEventRepository,
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._audit = audit
        self._notifier = notifier
        self._security_events = security_events  # SEC-7 — bax `AdminLoginUseCase`-in şərhi

    def recover(
        self,
        *,
        tenant_id: TenantId,
        target: Employee,
        developer_reference: str,
        active_admin_count: int,
        tenant_contact: TenantContact,
        verified_contact: str,
    ) -> TemporaryCredential:
        """Args:
        active_admin_count: Tenant-da qalan aktiv admin-tier hesab sayı.
            Sıfırdan böyükdürsə prosedur RƏDD edilir.
        developer_reference: Kimlik təsdiqinin izi (ticket/əlaqə qeydi) —
            audit üçün MƏCBURİDİR.
        tenant_contact: `license_tenants`-dəki qeydiyyatlı şirkət əlaqəsi.
        verified_contact: Müraciət edənin təsdiqləndiyi kanal (e-poçt və ya
            telefon). `tenant_contact` ilə üst-üstə düşməlidir.
        """
        if active_admin_count > 0:
            raise AuthenticationError(
                f"Emergency Access Recovery yalnız aktiv admin hesab QALMADIQDA "
                f"mümkündür (qalan: {active_admin_count})",
                user_message="Tenant-da hələ aktiv admin hesab var.",
                context={"active_admin_count": active_admin_count},
            )
        if len(normalise_decision_text(developer_reference)) < MIN_RECOVERY_REFERENCE_LENGTH:
            raise AuthenticationError(
                f"Kimlik təsdiqi istinadı məcburidir "
                f"(minimum {MIN_RECOVERY_REFERENCE_LENGTH} simvol)",
                user_message="Prosedur üçün istinad nömrəsi göstərilməlidir.",
            )
        if not tenant_contact.matches(verified_contact):
            # Bu, prosedurun ƏSAS qapısıdır: uyğunsuzluq halında bərpa
            # istənilən şəxsə admin hesabı verən arxa qapıya çevrilərdi.
            _security_log.critical(
                "EMERGENCY_RECOVERY_CONTACT_MISMATCH",
                extra={
                    "tenant_id": str(tenant_id),
                    "target_id": str(target.id),
                    "impact": "bərpa cəhdi rədd edildi",
                },
            )
            # SEC-7 QƏRARI (team-lead-in tələb etdiyi əsaslandırma): bu ikisi
            # ("tenant-ın ən ciddi hadisəsi") ÜÇÜN DƏ 1-ci şərt (DB yazısı
            # əməliyyatı DAYANDIRMIR) DƏYİŞMİR — `FailSoftSecurityEventRecorder`
            # EYNİ, UNİFORM siyasətlə çağırılır. Səbəb: bu qərarın ÖZÜ ARTIQ
            # `self._audit.record()` (DB `audit_logs`, aşağıda, "audit
            # istisna udmur") ilə SƏRT ZƏMANƏT altındadır — o, kompliyansı
            # artıq TƏMİN EDİR. `security_events`-i BURADA ayrıca sərt etmək
            # eyni əməliyyata İKİNCİ, LÜZUMSUZ uğursuzluq nöqtəsi əlavə edərdi:
            # tenant-ın YEGANƏ bərpa yolu YALNIZ telemetriya cədvəli əlçatmaz
            # olduğu üçün bloklanardı — bu, DB-yə bağlı DoS-un məhz bu
            # ssenaridəki ən pis forması olardı (bərpa YOLUNUN ÖZÜ bağlanır).
            self._security_events.record(
                tenant_id=tenant_id,
                event_type="EMERGENCY_RECOVERY_CONTACT_MISMATCH",
                employee_id=target.id,
                details={"impact": "bərpa cəhdi rədd edildi"},
            )
            raise AuthenticationError(
                "Təqdim olunan əlaqə tenant-ın qeydiyyatdakı şirkət əlaqəsi ilə üst-üstə düşmür",
                user_message="Kimlik təsdiqi alınmadı — şirkət əlaqə məlumatı uyğun gəlmir.",
                context={"tenant_id": str(tenant_id)},
            )
        if target.position.effective_system_role not in (
            SystemRole.ROOT,
            SystemRole.CEO,
        ):
            raise AuthenticationError(
                "Bərpa yalnız Root/CEO hesabı üçün mümkündür",
                context={"role": target.position.code},
            )

        temporary = self._hashing.generate_temporary_password()
        hashed = self._hashing.hash_password(temporary)
        target.must_change_password = True
        target.is_active = True
        self._employees.save(target)
        # HEŞ FAKTİKİ OLARAQ BURADA YAZILIR — `save()` sirrlərə TOXUNMUR
        # (bax `EmployeeRepository.save()` docstring-i). Bu sətir olmadan
        # prosedur hesabı aktivləşdirir, "şifrəni dəyiş" bayrağını qoyur və
        # ekranda bir şifrə göstərirdi, lakin `employees.password_hash`
        # DƏYİŞMİRDİ — yəni fövqəladə bərpa məhz lazım olduğu anda giriş
        # vermirdi. `pepper_version` də yazılır, əks halda yeni heş köhnə
        # pepper versiyası ilə yoxlanardı (SEC-005) və uyğunluq baş tutmazdı.
        self._employees.update_credentials(
            target.id,
            password_hash=hashed,
            pepper_version=self._hashing.current_pepper_version,
        )

        _security_log.critical(
            "EMERGENCY_ACCESS_RECOVERY",
            extra={
                "tenant_id": str(tenant_id),
                "target_id": str(target.id),
                "developer_reference": developer_reference,
                "verified_via": "COMPANY_CONTACT",
            },
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,  # hazırlayıcı tərəf — tenant istifadəçisi deyil
            action="EMERGENCY_ACCESS_RECOVERY",
            entity_type="employees",
            entity_id=target.id,
            after_state={
                "developer_reference": developer_reference,
                "verified_via": "COMPANY_CONTACT",
            },
            reason="Bütün admin hesabları itirilib — Developer Panelindən bərpa",
        )
        # SEC-7: `_audit.record()` yuxarıda ARTIQ sərt zəmanətdir (uğursuz
        # olsa bütün əməliyyat geri qayıdır) — `security_events` UNİFORM
        # fail-soft siyasəti ilə ƏLAVƏ yazılır, əsaslandırma yuxarı
        # (`EMERGENCY_RECOVERY_CONTACT_MISMATCH` şərhi) ilə EYNİDİR.
        self._security_events.record(
            tenant_id=tenant_id,
            event_type="EMERGENCY_ACCESS_RECOVERY",
            employee_id=target.id,
            details={
                "developer_reference": developer_reference,
                "verified_via": "COMPANY_CONTACT",
            },
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category="EMERGENCY_ACCESS_RECOVERY",
            title_az="Təcili giriş bərpası icra edildi",
            body_az=(
                f"Hazırlayıcı tərəf tərəfindən təcili giriş bərpası icra olundu. "
                f"İstinad: {developer_reference}. Bu əməliyyat tam audit-lənib."
            ),
            is_critical=True,
        )
        return TemporaryCredential(
            plaintext=temporary,
            hashed=hashed,
            pepper_version=self._hashing.current_pepper_version,
        )


__all__ = [
    "RESET_PASSWORD_FLAG",
    "RESET_PIN_FLAG",
    "REVOKE_SESSION_FLAG",
    "SESSION_TOKEN_BYTES",
    "AccountLockedError",
    "AdminLoginUseCase",
    "AuthenticationError",
    "CredentialResetUseCase",
    "EmergencyAccessRecoveryUseCase",
    "IssuedSession",
    "LoginResult",
    "LoginStage",
    "PinHandshakeUseCase",
    "PinResult",
    "SessionContextNotSupportedError",
    "SessionExpiredError",
    "SessionManagementUseCase",
    "TemporaryCredential",
    "TenantContact",
    "TerminalLockedError",
    "TerminalThrottleUnavailableError",
]
