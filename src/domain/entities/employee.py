"""İşçi aqreqatı (spesifikasiya bölmə 2, 3, 4).

İKİ AYRI AUTENTİFİKASİYA KONTEKSTİ (bölmə 2):

* **Kiosk PIN** — 4 rəqəm, YALNIZ İcazə/Qayıdış və Morning Check-in axını üçün.
  Mağaza Meneceri daxil HƏR işçi rolunu əhatə edir (menecer də mağazadan
  çıxıb-qayıda bilər). Admin panelə giriş üçün İSTİFADƏ OLUNMUR.
* **Admin-tier** — istifadəçi adı + güclü şifrə (qərar SEC-016).
  `Kamera_Nəzarətçisi` DƏ bu tier-dədir (bölmə 2 düzəlişi): rol birbaşa
  maliyyə nəticəli qərarlar verdiyi üçün sadə PIN kifayət qədər güclü
  "kim etdi" sübutu (non-repudiation) vermir.

E-POÇT AUTENTİFİKASİYADAN AYRILIB (SEC-016): `notification_email` yalnız
bildiriş ünvanıdır, girişə HEÇ BİR təsiri yoxdur və boş ola bilər.

EFFEKTİV İCAZƏ = rol-defolt + fərdi override (override ÜSTÜNDÜR).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    PermissionEffect,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import EmailAddress, Username
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.domain.value_objects.scheduling import require_aware

#: Kiosk PIN-i olmayan, YALNIZ admin-tier ilə girən rollar (bölmə 2 düzəlişi).
ADMIN_TIER_ROLES = frozenset(
    {
        SystemRole.ROOT,
        SystemRole.CEO,
        SystemRole.ADMIN,
        SystemRole.HR_ADMIN,
        SystemRole.CAMERA_OPERATOR,
    }
)


@dataclass(frozen=True)
class PermissionOverride:
    """Fərdi grant/deny — rol-defoltdan üstündür."""

    flag_code: str
    effect: PermissionEffect
    granted_by: EmployeeId
    expires_at: datetime | None = None

    def is_active(self, *, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at


@dataclass
class PinSecurityState:
    """PIN lockout vəziyyəti (bölmə 2: 5 səhv → 15 dəqiqə)."""

    failed_attempts: int = 0
    locked_until: datetime | None = None
    pepper_version: int = 1

    def is_locked(self, *, now: datetime) -> bool:
        return self.locked_until is not None and now < self.locked_until


class Employee(AggregateRoot):
    """İşçi aqreqatı."""

    def __init__(
        self,
        *,
        employee_id: EmployeeId,
        tenant_id: TenantId,
        position: Position,
        first_name: str,
        last_name: str,
        store_id: StoreId | None = None,
        username: Username | None = None,
        notification_email: EmailAddress | None = None,
        has_password: bool = False,
        has_pin: bool = False,
        must_change_password: bool = False,
        is_active: bool = True,
        profile_photo_url: str | None = None,
        hire_date: date | None = None,
        date_of_birth: date | None = None,
    ) -> None:
        super().__init__()
        self.id = employee_id
        self.tenant_id = tenant_id
        self.position = position
        self.first_name = first_name.strip()
        self.last_name = last_name.strip()
        self.store_id = store_id
        #: Admin-tier giriş identifikatoru. Kiosk-yalnız işçilərdə `None`.
        self.username = username
        #: YALNIZ bildiriş üçün — girişə təsiri YOXDUR (SEC-016).
        self.notification_email = notification_email
        self.has_password = has_password
        self.has_pin = has_pin
        self.must_change_password = must_change_password
        self.is_active = is_active
        self.profile_photo_url = profile_photo_url
        self.hire_date = hire_date
        #: HƏSSAS SAHƏ (İşçi Detal Paneli): yalnız öz profilində və ya
        #: `can_view_employee_reports` ilə göstərilir — bax
        #: `EmployeeProfileAccessUseCase`.
        self.date_of_birth = date_of_birth

        self.pin_security = PinSecurityState()
        self._overrides: dict[str, PermissionOverride] = {}
        #: Kamera Operatoru üçün çox-mağazalı təyinat (bölmə 4).
        self._assigned_store_ids: set[StoreId] = set()

        self._assert_has_authentication_method()

    # --------------------------- autentifikasiya ---------------------------- #

    def _assert_has_authentication_method(self) -> None:
        """DB-dəki `chk_employee_auth` ilə eyni invariant."""
        if not self.has_pin and not (self.username and self.has_password):
            raise DomainRuleError(
                "İşçinin ən azı bir autentifikasiya vasitəsi olmalıdır "
                "(PIN, və ya istifadəçi adı + şifrə)",
                user_message="İşçi üçün PIN və ya istifadəçi adı/şifrə təyin edilməlidir.",
                context={"employee_id": str(self.id)},
            )

    @property
    def requires_admin_tier_auth(self) -> bool:
        """Bu rol admin panelinə istifadəçi adı + şifrə ilə girməlidirmi (bölmə 2)."""
        role = self.position.effective_system_role
        return role in ADMIN_TIER_ROLES

    @property
    def can_use_kiosk_pin(self) -> bool:
        """Kiosk PIN handshake-i bu işçi üçün mümkündürmü.

        Bölmə 2: `Kamera_Nəzarətçisi` sadə PIN-dən İSTİSNA edilib. Digər bütün
        rollar (Mağaza_Meneceri daxil) kiosk-dan istifadə edir, çünki onlar da
        mağazadan çıxıb-qayıdır.
        """
        return (
            self.has_pin and self.position.effective_system_role is not SystemRole.CAMERA_OPERATOR
        )

    def assert_admin_login_allowed(self) -> None:
        """Admin panelə giriş ön-şərtləri."""
        if not self.is_active:
            raise DomainRuleError("Deaktiv edilmiş hesab", user_message="Hesabınız deaktiv edilib.")
        if self.username is None or not self.has_password:
            raise DomainRuleError(
                "Admin girişi üçün istifadəçi adı və şifrə təyin edilməlidir",
                user_message="Hesabınız üçün istifadəçi adı və şifrə təyin edilməyib.",
            )

    # ------------------------------ PIN lockout ----------------------------- #

    def register_failed_pin_attempt(
        self, *, now: datetime, max_attempts: int = 5, lockout_minutes: int = 15
    ) -> bool:
        """Səhv PIN cəhdini qeyd edir.

        Returns:
            Bu cəhd hesabı BLOKLADISA `True`.
        """
        require_aware(now, field="now")
        self.pin_security.failed_attempts += 1
        if self.pin_security.failed_attempts >= max_attempts:
            self.pin_security.locked_until = now + timedelta(minutes=lockout_minutes)
            return True
        return False

    def register_successful_pin_attempt(self) -> None:
        """Uğurlu girişdə sayğac sıfırlanır."""
        self.pin_security.failed_attempts = 0
        self.pin_security.locked_until = None

    def is_pin_locked(self, *, now: datetime) -> bool:
        require_aware(now, field="now")
        return self.pin_security.is_locked(now=now)

    # ------------------------------- icazələr ------------------------------- #

    def apply_override(self, override: PermissionOverride) -> None:
        """Fərdi grant/deny əlavə edir.

        QEYD: kim-kimə toxuna bilər qaydası (Hierarchy/Self-Escalation Guard)
        BURADA yoxlanılmır — o, use case səviyyəsindədir
        (`PermissionHierarchyGuardUseCase`), çünki AKTOR məlumatı lazımdır.
        Burada yalnız flag-in bu ROLA ümumiyyətlə verilə bilməsi vacibdir.
        """
        self._overrides[override.flag_code] = override

    def remove_override(self, flag_code: str) -> None:
        self._overrides.pop(flag_code, None)

    @property
    def overrides(self) -> tuple[PermissionOverride, ...]:
        return tuple(self._overrides.values())

    def has_permission(self, flag_code: str, *, now: datetime) -> bool:
        """EFFEKTİV icazə: fərdi override → rol-defolt → `False`.

        Bölmə 3: "Fərdi override rol-səviyyəli defolt icazədən üstün olur."
        """
        require_aware(now, field="now")
        override = self._overrides.get(flag_code)
        if override is not None and override.is_active(now=now):
            return override.effect is PermissionEffect.GRANT
        return self.position.has_flag(flag_code)

    @property
    def priority(self) -> RolePriority:
        return self.position.priority

    def outranks(self, other: Employee) -> bool:
        """Strict Hierarchy Guard: bərabər pillə `False` qaytarır."""
        return self.position.outranks(other.position)

    # --------------------- kamera operatoru: mağaza scope -------------------- #

    def assign_store(self, store_id: StoreId) -> None:
        """Kamera Operatoruna mağaza təyin edir (bölmə 4, çox-mağazalı)."""
        if self.position.effective_system_role is not SystemRole.CAMERA_OPERATOR:
            raise DomainRuleError(
                "Mağaza təyinatı yalnız Kamera Operatoru üçündür — "
                "digər rollar tək `store_id` sahəsi ilə bağlanır",
                context={"role": self.position.code},
            )
        self._assigned_store_ids.add(store_id)

    def unassign_store(self, store_id: StoreId) -> None:
        self._assigned_store_ids.discard(store_id)

    @property
    def assigned_store_ids(self) -> frozenset[StoreId]:
        return frozenset(self._assigned_store_ids)

    def can_see_store(self, store_id: StoreId) -> bool:
        """DEFOLT-TƏHLÜKƏSİZ (bölmə 4): təyinat yoxdursa HEÇ NƏ görünmür.

        "defolt «hər şeyi göstər» DEYİL, defolt «heç nəyi göstərmə» olmalıdır."
        """
        if self.position.effective_system_role is SystemRole.CAMERA_OPERATOR:
            return store_id in self._assigned_store_ids
        return self.store_id == store_id

    # -------------------------------- profil -------------------------------- #

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def deactivate(self) -> None:
        self.is_active = False

    def __repr__(self) -> str:
        return f"Employee(id={self.id}, role={self.position.code})"


__all__ = ["ADMIN_TIER_ROLES", "Employee", "PermissionOverride", "PinSecurityState"]
