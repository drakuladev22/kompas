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
from typing import TYPE_CHECKING

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionEffect,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import EmailAddress, Username
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.domain.value_objects.scheduling import require_aware

if TYPE_CHECKING:
    from collections.abc import Mapping

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
        scheduled_deactivation_date: date | None = None,
        referred_by_employee_id: EmployeeId | None = None,
        data_anonymized_at: datetime | None = None,
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
        #: `v2backlog.md` Faza 3.1 — mövsümi/müvəqqəti işçi üçün istəyə-bağlı
        #: planlaşdırılmış deaktivasiya tarixi. `None` = müddətsiz. Gecəlik
        #: cron (`UserManagementUseCase.deactivate_scheduled_employees`) bu
        #: tarixi keçmiş aktiv işçini tapıb deaktiv edir (migrations/088).
        self.scheduled_deactivation_date = scheduled_deactivation_date
        #: Faza 3.5 — işçi yaradılarkən "kim tövsiyə etdi" sahəsi. Bonus-xal
        #: `UserManagementUseCase.create_employee`-də YALNIZ BİR DƏFƏ, yaranış
        #: anında yazılır — sahənin ÖZÜ isə tarixi fakt olaraq daimi qalır.
        self.referred_by_employee_id = referred_by_employee_id
        #: Faza 3.2 — retensiya müddəti (ROOT PARAMETRİ) keçmiş DEAKTİV işçinin
        #: PII sahələrinin anonimləşdirildiyi AN. `None` = hələ
        #: anonimləşdirilməyib. `anonymize_personal_data()` bunu doldurur.
        self.data_anonymized_at = data_anonymized_at

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

    def change_position(
        self, position: Position, *, catalog: Mapping[str, PermissionFlag]
    ) -> list[str]:
        """Rolu dəyişir və YENİ rolda QADAĞAN olan override-ları silir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ SADƏ `employee.position = ...` KİFAYƏT DEYİL
        ──────────────────────────────────────────────────────────────────────
        Anti-fraud qadağası (bölmə 3, sətir 76) yalnız flag VERİLDİYİ anda
        yoxlanılırdı. Nəticədə belə bir yol qalırdı:

            1. CEO `can_approve_dual_control_override`-ı HR_Admin-ə verir
               (qanuni — HR_Admin qadağan rollardan deyil);
            2. həmin işçinin rolu sonradan `Mağaza_Meneceri`-yə dəyişdirilir;
            3. override QALIR, `has_permission` isə override-a rol-defoltdan
               ƏVVƏL baxır — yəni mağaza meneceri öz filialının Kamera
               Operatorunun override-larını ÖZÜ təsdiqləyir.

        Bu, məhz həmin flag-in hardlock siyahısına salınma səbəbidir: bütün
        Dual-Control mexanizmi mənasız olurdu. Qayda ENTİTY-dədir, çünki bu,
        aqreqatın invariantıdır — hansı use case rolu dəyişməsindən asılı
        olmamalıdır.

        Returns:
            Silinən flag kodları — çağıran onları audit-ə yazır.
        """
        self.position = position
        removed: list[str] = []
        for flag_code in list(self._overrides):
            flag = catalog.get(flag_code)
            if flag is None:
                # Kataloqda olmayan flag (köhnə sətir) toxunulmur — silmək
                # məlumat itkisi olardı, saxlamaq isə risk yaratmır, çünki
                # `has_permission` onu yalnız override kimi görür.
                continue
            try:
                # `is_camera_type_role` AÇIQ ÖTÜRÜLMƏLİDİR: CUSTOM kamera-tipli
                # rol (`Position.is_camera_type=True`) `effective_system_role`
                # ilə yalnız prioritetinə görə ən yaxın SİSTEM roluna (məs.
                # `HR_ADMIN`) düşür və həmin sistem rolunun özü kamera-tipli
                # DEYİL. Parametr ötürülməsə `assert_grantable_to` bunu adi
                # rol sayır və SEC-001-in "kamera-tipli rol dual-control
                # təsdiqini daşıya bilməz" bloku YAN KEÇİLİR — `grant()`
                # (`position.py`) və `_assert_flag_grantable_to_subject`
                # (`permission_guards.py`) bu parametri artıq ötürür, burada
                # unudulmuşdu.
                #
                # `is_store_tier_role` EYNİ NAXIŞDIR (T6): custom mağaza-pilləli
                # rol da `effective_system_role` ilə ən yaxın sistem roluna
                # düşür və həmin sistem rolun özü `ANTI_FRAUD_FORBIDDEN_ROLES`-də
                # olmaya bilər. Parametr ötürülməsə anti-fraud vəzifə ayrılığı
                # kataloqdan silinmiş flag-in TƏMİZLƏNMƏ yolunda yan keçilə bilər
                # — bu yol nadir işləsə də (flag kataloqdan silinəndə), SEC-001
                # ilə eyni səbəbdən mütləq bağlı qalmalıdır.
                flag.assert_grantable_to(
                    position.effective_system_role,
                    is_camera_type_role=position.is_camera_type,
                    is_store_tier_role=position.is_store_tier,
                )
            except AuthorizationError:
                del self._overrides[flag_code]
                removed.append(flag_code)
        return removed

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

    def activate(self) -> bool:
        """İşçini YENİDƏN aktivləşdirir (HR-4) — qayıdan işçinin simmetriyası.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ LAZIMDIR
        ──────────────────────────────────────────────────────────────────────
        `deactivate()` var idi, əksi YOX. Mövsümi işçi, uzunmüddətli
        xəstəlikdən qayıdan və ya səhvən deaktiv edilmiş hesab üçün yeganə yol
        bazada `UPDATE employees SET is_active = true` idi — auditsiz və
        adsız. Halbuki hesabın YENİDƏN yaradılması variantı DAHA PİSDİR: yeni
        `employees.id` bütün keçmiş cərimə, xal, davamiyyət və məzuniyyət
        tarixçəsini köhnə sətirdə qoyub gedərdi, yəni işçinin tarixçəsi ikiyə
        bölünərdi.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `bool` QAYTARIR
        ──────────────────────────────────────────────────────────────────────
        `FineAppeal.expire()` ilə eyni naxış: artıq aktiv hesabı yenidən
        aktivləşdirmək XƏTA DEYİL (ekranda iki dəfə basmaq, at-least-once
        icra), lakin çağıran tərəf audit sətrini və bildirişi YALNIZ HƏQİQİ
        dəyişiklikdə yazmalıdır — əks halda jurnal heç nə dəyişməyən
        «aktivləşdirildi» sətirləri ilə dolar.

        SƏLAHİYYƏT, SƏBƏB VƏ AUDİT BURADA YOXDUR: onlar use case qatındadır
        (`UserManagementUseCase.reactivate_employee`) — `deactivate()` ilə
        tam simmetrik, çünki entity nə aktoru, nə də audit portunu tanıyır.
        """
        if self.is_active:
            return False
        self.is_active = True
        return True

    def anonymize_personal_data(self, *, now: datetime) -> bool:
        """`v2backlog.md` Faza 3.2 — retensiya müddəti keçmiş PII-ni təmizləyir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ YALNIZ DEAKTİV İŞÇİ
        ──────────────────────────────────────────────────────────────────────
        Aktiv işçinin adı hər ekranda göstərilir; onu anonimləşdirmək tətbiqi
        işlətdiyi HALDA istifadəçini adsız qoyardı. Retensiya siyasəti YALNIZ
        "artıq sistemdən çıxmış" işçiyə aiddir (migrations/088 başlığı).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ İDEMPOTENTDİR (`bool` qaytarır, istisna atmır)
        ──────────────────────────────────────────────────────────────────────
        Gecəlik cron eyni işçini iki dəfə görə bilər (icarəsi bitmiş instansiya
        — `job_runner.py` `at-least-once` zəmanəti). İkinci çağırış xəta
        versəydi, bütün gecə dövrəsi bir sətrə görə dayanardı (`activate()`
        ilə eyni naxış).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `username`/`hire_date`/`position` TOXUNULMUR
        ──────────────────────────────────────────────────────────────────────
        Migrations/088: "FK-lar saxlanılır, aqreqat statistika (say, məbləğ,
        tarix) qorunur, YALNIZ şəxsi identifikasiya itir". `username` giriş
        identifikatorudur (UNIQUE) və deaktiv işçi onsuz da giriş edə bilmir
        (`assert_admin_login_allowed`) — onu boşaltmaq gələcəkdə eyni adın
        YENİDƏN istifadəsinə mane olardı, heç bir PII faydası vermədən.
        `hire_date`/`position` fərdi identifikasiya deyil, statistik fakt kimi
        qalır (məs. rotasiya hesabatları).
        """
        if self.is_active:
            raise DomainRuleError(
                "Aktiv işçinin şəxsi məlumatı anonimləşdirilə bilməz",
                user_message="Yalnız deaktiv işçinin məlumatı anonimləşdirilə bilər.",
                context={"employee_id": str(self.id)},
            )
        if self.data_anonymized_at is not None:
            return False
        self.first_name = "Anonimləşdirilib"
        self.last_name = ""
        self.notification_email = None
        self.profile_photo_url = None
        self.date_of_birth = None
        self.data_anonymized_at = require_aware(now, field="now")
        return True

    def __repr__(self) -> str:
        return f"Employee(id={self.id}, role={self.position.code})"


__all__ = ["ADMIN_TIER_ROLES", "Employee", "PermissionOverride", "PinSecurityState"]
