"""İstifadəçi & Rol İdarəetməsi (spesifikasiya bölmə 3 və 5-ci faza, bənd 6).

──────────────────────────────────────────────────────────────────────────────
BU MODUL NƏYİ ƏHATƏ EDİR
──────────────────────────────────────────────────────────────────────────────
    * işçi yaratmaq / redaktə etmək / deaktiv etmək (`can_manage_employees`)
    * admin-vasitəçili şifrə yeniləmə `[Şifrəni Yenilə]` (`can_reset_password`)
    * PIN sıfırlama (`can_reset_pin`)
    * rol təyinatı (`can_manage_roles`)
    * Kamera Operatoru üçün ÇOX-SEÇİMLİ mağaza təyinatı (bölmə 4)

İcazə matrisi (`PermissionMatrix`) BU MODULDA DEYİL — o,
`PermissionHierarchyGuardUseCase`-in işidir və orada bütün iyerarxiya
qoruyucuları var. Burada onu təkrarlamaq həmin qoruyucuların ikinci, zəif
kopyasını yaradardı.

──────────────────────────────────────────────────────────────────────────────
İYERARXİYA QAYDASI BURADA DA TƏTBİQ OLUNUR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3-ün Strict Hierarchy Guard-ı yalnız icazə dəyişikliyinə deyil, İŞÇİ
üzərindəki hər idarəetmə əməliyyatına aiddir: `HR_Admin` `CEO`-nun şifrəsini
sıfırlaya bilməməlidir, əks halda icazə iyerarxiyası şifrə sıfırlama yolu ilə
yan keçilərdi (aşağı rütbəli şəxs yuxarıdakının hesabını ələ keçirir).
`_assert_may_manage()` bunu hər əməliyyatda yoxlayır.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ NİYƏ BURADA HASH-LƏNMİR
──────────────────────────────────────────────────────────────────────────────
Hash-ləmə `HashingService`-in (infrastruktur) işidir; bu use case yalnız
"kim kimə nə edə bilər" qaydasını qoruyur və nəticəni `CredentialWriter`
portuna ötürür. Beləliklə Argon2 parametrləri dəyişdikdə burada heç nə
dəyişmir.

──────────────────────────────────────────────────────────────────────────────
DEAKTİV ETMƏ ≠ SİLMƏ
──────────────────────────────────────────────────────────────────────────────
İşçi silinmir — `is_active = False` olur. Səbəb cərimə/xal/audit sətirlərinin
hamısının `employee_id`-yə bağlı olmasıdır: fiziki silmə keçmiş cərimənin
"kimə yazıldığı" sualını cavabsız qoyardı. Üstəlik Dual-Control Deadlock
qoruyucusu (bölmə 3) deaktivləşdirmədən ƏVVƏL işə düşür.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from src.domain.entities.employee import Employee
from src.domain.value_objects.authorization import AuthorizationError, SystemRole
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.application.use_cases.dual_control_guard import (
        DualControlDeadlockGuardUseCase,
    )
    from src.domain.entities.position import Position
    from src.domain.interfaces.ports import (
        AuditTrail,
        CameraAssignmentRepository,
        Clock,
        EmployeeRepository,
        Notifier,
        PermissionFlagRepository,
    )
    from src.domain.value_objects.authorization import PermissionFlag
    from src.domain.value_objects.credentials import EmailAddress, Username
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

MANAGE_EMPLOYEES_FLAG = "can_manage_employees"
#: Bu, şifrənin ÖZÜ deyil, icazə flag-inin adıdır (ona görə `S105` susdurulur).
RESET_PASSWORD_FLAG = "can_reset_password"  # noqa: S105
RESET_PIN_FLAG = "can_reset_pin"
MANAGE_ROLES_FLAG = "can_manage_roles"


class UserManagementError(KompasOSError):
    """İstifadəçi əməliyyatı qadağandır və ya yararsızdır."""

    user_message = "Bu əməliyyat icra edilə bilmədi."


class EmployeeNotFoundError(UserManagementError):
    user_message = "İşçi tapılmadı."


class CredentialWriter(Protocol):
    """Şifrə/PIN hash-larını yazan mənbə (`PostgresEmployeeRepository` ödəyir).

    Hash-lar `Employee` entity-sinə QOYULMUR (təsadüfən log-a düşməsin deyə),
    ona görə onları yazmaq üçün ayrıca port lazımdır.
    """

    def set_password(
        self, employee_id: EmployeeId, *, raw_password: str, must_change: bool
    ) -> None: ...

    def set_pin(self, employee_id: EmployeeId, *, raw_pin: str) -> None: ...

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None: ...


@dataclass(frozen=True)
class EmployeeDraft:
    """Yeni/redaktə olunan işçi forması — ekranın topladığı sahələr."""

    first_name: str
    last_name: str
    position: Position
    store_id: StoreId | None = None
    username: Username | None = None
    notification_email: EmailAddress | None = None
    hire_date: date | None = None
    date_of_birth: date | None = None
    profile_photo_url: str | None = None
    #: Kamera Operatoru üçün çox-seçimli mağaza təyinatı (bölmə 4).
    camera_store_ids: tuple[StoreId, ...] = ()


class UserManagementUseCase:
    """İşçi yaratma/redaktə, şifrə & PIN sıfırlama, mağaza təyinatı."""

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        credentials: CredentialWriter,
        audit: AuditTrail,
        clock: Clock,
        camera_assignments: CameraAssignmentRepository | None = None,
        flags: PermissionFlagRepository | None = None,
        notifier: Notifier | None = None,
        deadlock_guard: DualControlDeadlockGuardUseCase | None = None,
    ) -> None:
        self._employees = employees
        self._credentials = credentials
        self._audit = audit
        self._clock = clock
        self._camera_assignments = camera_assignments
        # Flag kataloqu rol dəyişikliyində anti-fraud override-larını süzmək
        # üçündür (bax `Employee.change_position`). `None` olduqda süzgəc
        # TƏTBİQ EDİLMİR — bu, yalnız kataloqsuz test yollarıdır; istehsalat
        # qrafı onu HƏMİŞƏ ötürür (`composition.py`).
        self._flags = flags
        # PIN/şifrə sıfırlaması sahibinə bildiriş göndərir (bölmə 2, sətir 42).
        self._notifier = notifier
        # Dual-Control deadlock qoruyucusu (bölmə 3, sətir 56). Modul başlığı
        # onun deaktivləşdirmədən ƏVVƏL işə düşdüyünü iddia edirdi, lakin
        # çağırış YOX İDİ — sistemin son təsdiqçisini deaktiv etmək mümkün idi
        # və gözləyən override-lar sonsuza qədər təsdiqsiz qalardı.
        self._deadlock_guard = deadlock_guard

    # ------------------------------- yaratma --------------------------------- #

    def create_employee(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        draft: EmployeeDraft,
        initial_password: str | None = None,
        initial_pin: str | None = None,
    ) -> Employee:
        """Yeni işçi — ən azı bir autentifikasiya vasitəsi ilə.

        `Employee` konstruktoru "PIN, VƏ YA istifadəçi adı + şifrə" invariantını
        özü yoxlayır; burada yalnız hansının veriləcəyi həll olunur.
        """
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)
        self._assert_may_assign_position(actor, draft.position, now=now)

        employee = Employee(
            employee_id=employee_id,
            tenant_id=tenant_id,
            position=draft.position,
            first_name=draft.first_name,
            last_name=draft.last_name,
            store_id=draft.store_id,
            username=draft.username,
            notification_email=draft.notification_email,
            has_password=initial_password is not None,
            has_pin=initial_pin is not None,
            # Admin ilk şifrəni təyin edirsə, işçi onu DƏYİŞMƏLİDİR (bölmə 2).
            must_change_password=initial_password is not None,
            profile_photo_url=draft.profile_photo_url,
            hire_date=draft.hire_date,
            date_of_birth=draft.date_of_birth,
        )
        self._apply_camera_stores(employee, draft.camera_store_ids, actor=actor)
        self._employees.save(employee)

        if initial_password is not None:
            self._credentials.set_password(
                employee_id, raw_password=initial_password, must_change=True
            )
        if initial_pin is not None:
            self._credentials.set_pin(employee_id, raw_pin=initial_pin)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_CREATED",
            entity_type="employee",
            entity_id=employee_id,
            after_state={
                "full_name": employee.full_name,
                "position": draft.position.code,
                "has_password": employee.has_password,
                "has_pin": employee.has_pin,
                "camera_stores": len(draft.camera_store_ids),
            },
        )
        return employee

    # ------------------------------- redaktə --------------------------------- #

    def update_employee(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        draft: EmployeeDraft,
    ) -> Employee:
        """Mövcud işçini yeniləyir — rol dəyişikliyi də daxil."""
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        before: dict[str, object] = {
            "full_name": employee.full_name,
            "position": employee.position.code,
            "store_id": str(employee.store_id) if employee.store_id else None,
        }

        role_changed = employee.position.code != draft.position.code
        removed_overrides: list[str] = []
        if role_changed:
            self._require(actor, MANAGE_ROLES_FLAG, now=now)
            self._assert_may_assign_position(actor, draft.position, now=now)
            # ANTI-FRAUD İNVARİANTI: yeni rolda qadağan olan fərdi override
            # SİLİNİR. Əks halda HR_Admin ikən verilmiş
            # `can_approve_dual_control_override` işçi Mağaza_Menecerinə
            # keçiriləndə qüvvədə qalır və Dual-Control mexanizmi mənasız olur
            # (bax `Employee.change_position` docstring-i).
            removed_overrides = employee.change_position(
                draft.position, catalog=self._flag_catalog()
            )

        employee.first_name = draft.first_name.strip()
        employee.last_name = draft.last_name.strip()
        employee.store_id = draft.store_id
        employee.notification_email = draft.notification_email
        employee.hire_date = draft.hire_date
        employee.date_of_birth = draft.date_of_birth
        if draft.profile_photo_url is not None:
            employee.profile_photo_url = draft.profile_photo_url

        self._apply_camera_stores(employee, draft.camera_store_ids, actor=actor)
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_UPDATED",
            entity_type="employee",
            entity_id=employee_id,
            before_state=before,
            after_state={
                "full_name": employee.full_name,
                "position": employee.position.code,
                "store_id": str(employee.store_id) if employee.store_id else None,
                "role_changed": role_changed,
                # Silinən override-lar audit-də AÇIQ görünməlidir: bu, işçinin
                # səlahiyyətinin AZALMASIDIR və mübahisə halında nəyin nə vaxt
                # götürüldüyü sübut edilə bilməlidir.
                "removed_overrides": removed_overrides,
            },
        )
        if removed_overrides:
            _security_log.warning(
                "ANTI_FRAUD_OVERRIDES_REVOKED",
                extra={
                    "employee_id": str(employee_id),
                    "new_position": employee.position.code,
                    "flags": removed_overrides,
                },
            )
        return employee

    def deactivate_employee(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId, reason: str
    ) -> Employee:
        """İşçini deaktiv edir — SİLMİR (modul başlığına bax)."""
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        if employee.id == actor.id:
            raise UserManagementError(
                "İstifadəçi öz hesabını deaktiv edə bilməz — sistemin son adminini itirmək riski",
                user_message="Öz hesabınızı deaktiv edə bilməzsiniz.",
            )

        deadlock = self._check_deadlock(tenant_id, subject=employee)
        employee.deactivate()
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_DEACTIVATED",
            entity_type="employee",
            entity_id=employee_id,
            before_state={"is_active": True},
            after_state={
                "is_active": False,
                # Deadlock vəziyyəti audit-də görünməlidir: sonradan "niyə
                # override-lar təsdiqsiz qaldı" sualının cavabı budur.
                "dual_control_approvers_left": deadlock.approver_count
                if deadlock is not None
                else None,
            },
            reason=reason,
        )
        _security_log.info(
            "EMPLOYEE_DEACTIVATED",
            extra={"actor_id": str(actor.id), "employee_id": str(employee_id)},
        )
        return employee

    # -------------------------- şifrə & PIN sıfırlama ------------------------ #

    def reset_password(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId, new_password: str
    ) -> None:
        """ "[Şifrəni Yenilə]" — admin-vasitəçili sıfırlama (bölmə 2).

        Yeni şifrə HƏMİŞƏ `must_change=True` ilə yazılır: adminin bildiyi
        şifrə daimi qalsaydı, hesab faktiki olaraq iki nəfərə aid olardı və
        audit izi "kim etdi" sualına cavab verə bilməzdi.
        """
        now = self._clock.now()
        self._require(actor, RESET_PASSWORD_FLAG, now=now)
        self._assert_not_self(actor, employee_id, operation="şifrə")

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        self._credentials.set_password(employee_id, raw_password=new_password, must_change=True)
        employee.has_password = True
        employee.must_change_password = True
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PASSWORD_RESET_BY_ADMIN",
            entity_type="employee",
            entity_id=employee_id,
            after_state={"must_change_password": True},
        )
        _security_log.warning(
            "PASSWORD_RESET_BY_ADMIN",
            extra={"actor_id": str(actor.id), "employee_id": str(employee_id)},
        )
        self._notify_owner(
            tenant_id=tenant_id,
            employee_id=employee_id,
            title="Şifrəniz sıfırlandı",
            body=(
                "Admin şifrənizi müvəqqəti şifrə ilə əvəz etdi və ilk girişdə "
                "onu dəyişməlisiniz. Bu, sizin xahişinizlə olmayıbsa dərhal "
                "rəhbərliyinizə məlumat verin."
            ),
        )

    def reset_pin(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId, new_pin: str
    ) -> None:
        """PIN sıfırlama — YALNIZ HR_Admin/Root (bölmə 2).

        Lockout da təmizlənir: işçi 5 səhv cəhddən sonra bloklanıbsa, yeni PIN
        ona kömək etməzdi — 15 dəqiqə hələ də gözləməli olardı.
        """
        now = self._clock.now()
        self._require(actor, RESET_PIN_FLAG, now=now)
        self._assert_not_self(actor, employee_id, operation="PIN")

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        self._credentials.set_pin(employee_id, raw_pin=new_pin)
        self._credentials.clear_pin_lockout(employee_id)
        employee.has_pin = True
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PIN_RESET_BY_ADMIN",
            entity_type="employee",
            entity_id=employee_id,
        )
        _security_log.warning(
            "PIN_RESET_BY_ADMIN",
            extra={"actor_id": str(actor.id), "employee_id": str(employee_id)},
        )
        self._notify_owner(
            tenant_id=tenant_id,
            employee_id=employee_id,
            title="PIN-iniz sıfırlandı",
            body=(
                "Admin PIN kodunuzu sıfırladı. Bu, sizin xahişinizlə olmayıbsa "
                "dərhal rəhbərliyinizə məlumat verin."
            ),
        )

    # ------------------------ kamera mağaza təyinatı ------------------------- #

    def assign_camera_stores(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        store_ids: tuple[StoreId, ...],
    ) -> Employee:
        """Kamera Operatoruna mağaza(lar) təyin edir (bölmə 4, çox-seçimli).

        BOŞ siyahı icazəlidir və mənası "heç nə görməsin"dir — fail-safe
        istiqamət budur (`CameraAssignmentRepository` izahına bax).
        """
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)
        self._apply_camera_stores(employee, store_ids, actor=actor)
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="CAMERA_STORES_ASSIGNED",
            entity_type="employee",
            entity_id=employee_id,
            after_state={"store_count": len(store_ids)},
        )
        return employee

    # ------------------------------- köməkçilər ------------------------------ #

    def _apply_camera_stores(
        self, employee: Employee, store_ids: tuple[StoreId, ...], *, actor: Employee
    ) -> None:
        """Təyinatı entity-yə və (varsa) repository-yə yazır."""
        if employee.position.effective_system_role is not SystemRole.CAMERA_OPERATOR:
            if store_ids:
                raise UserManagementError(
                    "Çox-mağazalı təyinat yalnız Kamera Nəzarətçisi üçündür",
                    user_message="Bu rol üçün çoxlu mağaza təyin edilə bilməz.",
                    context={"role": employee.position.code},
                )
            return

        for previous in employee.assigned_store_ids:
            employee.unassign_store(previous)
        for store_id in store_ids:
            employee.assign_store(store_id)
            if self._camera_assignments is not None:
                self._camera_assignments.assign(employee.id, store_id, assigned_by=actor.id)

    def _check_deadlock(self, tenant_id: TenantId, *, subject: Employee) -> Any:
        """Dual-Control təsdiqçisi itirilirsə XƏBƏRDARLIQ verir (bölmə 3, 56).

        BLOKLAMIR — spesifikasiya "xəbərdarlıq göstərilir" deyir, qadağa yox.
        Bloklamaq son HR_Admin-i işdən çıxaran şirkətdə istifadəçi silməyi
        tamamilə mümkünsüz edərdi; xəbərdarlıq isə problemi görünən edir.
        Bildirişi qoruyucunun özü göndərir (`Notifier` ona verilib).
        """
        if self._deadlock_guard is None:
            return None
        approver_roles = (SystemRole.HR_ADMIN, SystemRole.CEO, SystemRole.ROOT)
        removing = subject.position.effective_system_role in approver_roles
        return self._deadlock_guard.check_before_change(tenant_id, removing_approver=removing)

    @staticmethod
    def _assert_not_self(actor: Employee, employee_id: EmployeeId, *, operation: str) -> None:
        """Öz PIN/şifrəsini BU AXINLA sıfırlamaq qadağandır (bölmə 2, sətir 42).

        SEC-016 TOTP-ni çıxaranda onun yerini üç struktur qorunma tutdu və
        BİRİNCİSİ məhz budur: sıfırlamanı HƏMİŞƏ BAŞQA autentifikasiya olunmuş
        admin edir, yəni vəzifə ayrılığı qorunur. Əks halda `can_reset_pin`
        sahibi öz lockout-unu özü açardı (`clear_pin_lockout` bu axındadır) —
        yəni 5 səhv cəhd + 15 dəqiqəlik bloklama qaydası öz-özünə yan keçilərdi.

        Öz şifrəsini dəyişmək AYRI axındır (`CredentialResetUseCase`) və orada
        köhnə şifrənin bilinməsi tələb olunur.
        """
        if actor.id != employee_id:
            return
        _security_log.warning(
            "SELF_CREDENTIAL_RESET_BLOCKED",
            extra={"actor_id": str(actor.id), "operation": operation},
        )
        raise UserManagementError(
            f"İstifadəçi öz {operation} məlumatını bu axınla sıfırlaya bilməz "
            f"— sıfırlamanı başqa admin etməlidir (bölmə 2)",
            user_message=(
                f"Öz {operation} məlumatınızı bu ekrandan sıfırlaya bilməzsiniz. "
                f"Başqa admin müraciət etməlidir."
            ),
        )

    def _notify_owner(
        self, *, tenant_id: TenantId, employee_id: EmployeeId, title: str, body: str
    ) -> None:
        """Sıfırlamadan sahibin XƏBƏRİ olmalıdır (bölmə 2, sətir 42).

        Bildiriş uğursuz olarsa əməliyyat GERİ QAYTARILMIR: sıfırlama artıq baş
        verib və onu ləğv etmək işçini girişsiz qoyardı. Audit yazısından
        fərqi budur — audit məcburidir, bildiriş isə xəbərdarlıqdır.
        """
        if self._notifier is None:
            return
        try:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=employee_id,
                category="CREDENTIAL_RESET",
                title_az=title,
                body_az=body,
                is_critical=True,
            )
        except Exception:
            _security_log.exception(
                "CREDENTIAL_RESET_NOTIFY_FAILED", extra={"employee_id": str(employee_id)}
            )

    def _flag_catalog(self) -> dict[str, PermissionFlag]:
        """`kod → PermissionFlag` — rol dəyişikliyində süzgəc üçün.

        Kataloq verilməyibsə BOŞ lüğət qaytarılır: `change_position` naməlum
        flag-ə toxunmur, yəni davranış əvvəlki kimi qalır. Bu, qəsdən
        fail-open-dur — kataloqa çatmamaq rol dəyişikliyini bloklamamalıdır,
        lakin istehsalat qrafı kataloqu HƏMİŞƏ verir.
        """
        if self._flags is None:
            return {}
        return {flag.code: flag for flag in self._flags.list_all()}

    def _load(self, employee_id: EmployeeId) -> Employee:
        employee = self._employees.get(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(
                f"İşçi tapılmadı: {employee_id}", context={"employee_id": str(employee_id)}
            )
        return employee

    def _require(self, actor: Employee, flag: str, *, now: datetime) -> None:
        if not actor.has_permission(flag, now=now):
            _security_log.warning(
                "USER_MANAGEMENT_DENIED",
                extra={"actor_id": str(actor.id), "flag": flag},
            )
            raise UserManagementError(
                f"«{flag}» səlahiyyəti yoxdur",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
                context={"flag": flag},
            )

    @staticmethod
    def _assert_may_manage(actor: Employee, subject: Employee, *, now: datetime) -> None:
        """STRICT HIERARCHY GUARD — modul başlığındakı izaha bax.

        Öz-özünə tətbiq olunmur: istifadəçi öz profilini redaktə edə bilər
        (`EmployeeProfileUseCase`), lakin ora ayrı yoldur.
        """
        if actor.id == subject.id:
            return
        if not actor.outranks(subject):
            _security_log.warning(
                "USER_MANAGEMENT_HIERARCHY_BLOCKED",
                extra={
                    "actor_id": str(actor.id),
                    "actor_priority": actor.priority.value,
                    "subject_id": str(subject.id),
                    "subject_priority": subject.priority.value,
                },
            )
            raise AuthorizationError(
                "STRICT HIERARCHY GUARD: eyni və ya daha yüksək pillədəki "
                "istifadəçini idarə etmək olmaz (bölmə 3)",
                user_message="Bu istifadəçini idarə etmək səlahiyyətiniz yoxdur.",
                context={"subject_id": str(subject.id)},
            )

    @staticmethod
    def _assert_may_assign_position(actor: Employee, position: Position, *, now: datetime) -> None:
        """Aktor ÖZÜNDƏN yüksək (və ya bərabər) rol təyin edə bilməz.

        Bu, iyerarxiyanın "yaratma" tərəfindəki qapağıdır: onsuz `HR_Admin`
        yeni bir `Root` yaradıb həmin hesabla daxil ola bilərdi.
        """
        if not actor.position.outranks(position):
            _security_log.warning(
                "POSITION_ASSIGNMENT_BLOCKED",
                extra={"actor_id": str(actor.id), "position": position.code},
            )
            raise AuthorizationError(
                "Özündən yüksək və ya bərabər pilləli rol təyin edilə bilməz (bölmə 3)",
                user_message="Bu vəzifəni təyin etmək səlahiyyətiniz yoxdur.",
                context={"position": position.code},
            )


__all__ = [
    "MANAGE_EMPLOYEES_FLAG",
    "MANAGE_ROLES_FLAG",
    "RESET_PASSWORD_FLAG",
    "RESET_PIN_FLAG",
    "CredentialWriter",
    "EmployeeDraft",
    "EmployeeNotFoundError",
    "UserManagementError",
    "UserManagementUseCase",
]
