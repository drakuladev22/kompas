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
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.entities.employee import Employee
from src.domain.interfaces.ports import (
    AuditTrail,
    Clock,
    EmployeeRepository,
    Notifier,
    SystemLimits,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.infrastructure.security.hashing import HashingService, evaluate_pin_attempt
from src.infrastructure.security.hashing import PinPolicy as HashPinPolicy
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

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
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._audit = audit

    def login(
        self,
        *,
        tenant_id: TenantId,
        username: Username,
        password: str,
        stored_hash: str | None,
        pepper_version: int = 1,
    ) -> LoginResult:
        """İstifadəçi adı + şifrə yoxlaması.

        `stored_hash` repo-dan AYRICA ötürülür: hash domen entity-sində
        saxlanılmır ki, təsadüfən log-a və ya DTO-ya düşməsin.
        """
        employee = self._employees.get_by_username(tenant_id, username)

        # Hesab yoxdursa belə Argon2 hesablaması APARILIR: əks halda mövcud
        # olmayan hesab ~milisaniyələrlə daha tez cavab verər və hücumçu
        # cavab müddətinə görə hesabları sadalaya bilərdi (timing oracle).
        password_ok = self._hashing.verify_password(
            stored_hash, password, pepper_version=pepper_version
        )
        if employee is None or not password_ok:
            _security_log.warning(
                "LOGIN_FAILED",
                extra={
                    "username_attempt": str(username),
                    "tenant_id": str(tenant_id),
                    "reason": "UNKNOWN_ACCOUNT" if employee is None else "BAD_PASSWORD",
                },
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

        self._record_login(employee, method="USERNAME_PASSWORD")
        return LoginResult(
            employee=employee,
            stage=LoginStage.AUTHENTICATED,
            needs_pepper_rehash=needs_rehash,
        )

    def _record_login(self, employee: Employee, *, method: str) -> None:
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
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._limits = limits
        self._audit = audit

    def authenticate(
        self,
        *,
        tenant_id: TenantId,
        store_id: StoreId,
        pin: str,
        pin_hashes: dict[EmployeeId, tuple[str, int]],
    ) -> PinResult:
        """Mağazadakı işçilər arasında PIN sahibini tapır.

        Args:
            pin_hashes: `{employee_id: (hash, pepper_version)}` — repo-dan gəlir.

        PIN `employee_id`-yə bağlı hash-ləndiyi üçün (SEC-005) hər namizəd
        AYRICA yoxlanılır. Bu, mağazadakı işçi sayı qədər Argon2 hesablaması
        deməkdir — mağaza başına onlarla işçi olduğu üçün qəbul ediləndir.
        """
        now = self._clock.now()
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
        raise AuthenticationError(
            "PIN heç bir işçiyə uyğun gəlmədi",
            user_message="PIN yanlışdır.",
        )

    def register_failure(self, *, tenant_id: TenantId, employee: Employee) -> tuple[bool, int]:
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
        return decision.is_locked, decision.remaining_attempts

    def _pin_policy(self, tenant_id: TenantId) -> HashPinPolicy:
        return HashPinPolicy(
            max_attempts=self._limit_int(tenant_id, SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS),
            lockout_minutes=self._limit_int(tenant_id, SystemLimitKey.PIN_LOCKOUT_MINUTES),
        )

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))

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
# Admin-tərəfindən sıfırlama (bölmə 2)
# --------------------------------------------------------------------------- #


class CredentialResetUseCase:
    """Şifrə/PIN sıfırlanması — E-POÇT TOKEN AXINI YOXDUR (bölmə 2).

    Daha yüksək və ya bərabər səlahiyyətli admin müvəqqəti sirr təyin edir,
    istifadəçi ilk girişdə onu MƏCBURİ dəyişir. Eyni model həm şifrə, həm PIN
    üçün istifadə olunur.
    """

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        hashing: HashingService,
        clock: Clock,
        audit: AuditTrail,
        notifier: Notifier,
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._audit = audit
        self._notifier = notifier

    def reset_password(self, *, actor: Employee, subject: Employee) -> TemporaryCredential:
        """Admin-tier istifadəçi üçün müvəqqəti şifrə təyin edir."""
        self._assert_may_reset(actor, subject, flag=RESET_PASSWORD_FLAG, kind="şifrə")

        temporary = self._hashing.generate_temporary_password()
        hashed = self._hashing.hash_password(temporary)
        subject.must_change_password = True
        self._employees.save(subject)

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
    ) -> None:
        self._employees = employees
        self._hashing = hashing
        self._clock = clock
        self._audit = audit
        self._notifier = notifier

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
        if len(developer_reference.strip()) < MIN_RECOVERY_REFERENCE_LENGTH:
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
    "AccountLockedError",
    "AdminLoginUseCase",
    "AuthenticationError",
    "CredentialResetUseCase",
    "EmergencyAccessRecoveryUseCase",
    "LoginResult",
    "LoginStage",
    "PinHandshakeUseCase",
    "PinResult",
    "TemporaryCredential",
    "TenantContact",
]
