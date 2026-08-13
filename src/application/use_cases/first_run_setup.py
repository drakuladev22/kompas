"""İlk Quraşdırma Sihirbazı (spesifikasiya bölmə 7) — Faza 4.3.

    "(1) ilk Root/CEO hesabının yaradılması (ad soyad + e-poçt + istifadəçi adı
     + şifrə — SEC-016: 2FA YOXDUR; e-poçt burada BƏRPA KANALI kimi soruşulur,
     giriş identifikatoru istifadəçi adıdır), (2) ilk mağaza(lar)ın əlavə
     edilməsi, (3) 1C server bağlantısının (istəyə görə, keçilə bilər)
     qurulması, (4) HR_Admin/Store Manager dəvəti."

──────────────────────────────────────────────────────────────────────────────
NİYƏ `UserManagementUseCase` İSTİFADƏ EDİLMİR
──────────────────────────────────────────────────────────────────────────────
Həmin use case HƏR əməliyyatda `actor: Employee` tələb edir və
`can_manage_employees` yoxlayır — çünki adi işləmə rejimində işçi yaradan
HƏMİŞƏ bir başqa istifadəçidir.

İlk quraşdırmada isə HEÇ BİR istifadəçi yoxdur. "Sistem aktoru" uydurmaq
təhlükəli olardı: o aktor sonradan da mövcud qalar və səlahiyyət yoxlamasını
yan keçən daimi bir yol yaradardı. Ona görə bu use case AYRIDIR və öz
qapısı var: **yalnız tenant BOŞDURSA işləyir**.

──────────────────────────────────────────────────────────────────────────────
BİR DƏFƏLİK OLMASI NECƏ ZƏMANƏT EDİLİR
──────────────────────────────────────────────────────────────────────────────
`is_required()` tenant-da aktiv admin hesabı olub-olmadığını yoxlayır və
`complete()` eyni yoxlamanı YENİDƏN, yazmadan DƏRHAL əvvəl edir. Yalnız
ekranın "sihirbaz göstərilsinmi?" sualına güvənmək kifayət etməzdi: sihirbaz
səhifəsi açıq qalıb, arada başqa bir cihazda quraşdırma bitirilə bilər.

──────────────────────────────────────────────────────────────────────────────
İKİNCİ ROOT HESABI — TÖVSİYƏ, MƏCBURİYYƏT DEYİL
──────────────────────────────────────────────────────────────────────────────
Bölmə 2: "Hər tenant-da quraşdırma zamanı ən azı İKİ müstəqil Root/CEO
səviyyəli hesab yaradılması UI tərəfindən TÖVSİYƏ olunur (tək hesab qalıb
bloklana bilməsin deyə)."

"Tövsiyə" sözü qəsdlidir — məcburi etsək, tək nəfərlik biznes quraşdırmanı
tamamlaya bilməzdi. Ona görə `SetupOutcome.single_admin_warning` qaytarılır
və ekran onu göstərir, amma heç nə bloklanmır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.application.root_limits import fallback_int, limit_int
from src.domain.entities.employee import Employee
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import SystemRole
from src.domain.value_objects.identifiers import new_employee_id, new_store_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.user_management import CredentialWriter
    from src.domain.entities.position import Position
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        EmployeeRepository,
        PositionRepository,
        SystemLimits,
    )
    from src.domain.value_objects.credentials import EmailAddress, Username
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Sihirbazın işə düşməsini müəyyən edən rollar — bunlardan biri varsa
#: quraşdırma artıq tamamlanıb.
ADMIN_ROLE_CODES = frozenset({SystemRole.ROOT.value, SystemRole.CEO.value})

#: Bölmə 2 tövsiyəsi — bundan az admin qalarsa xəbərdarlıq göstərilir.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT`, seed: migrations/034).
#: Bu, STRUKTUR ZƏMANƏT DEYİL və `system_limits`-ə köçürülməsi CLAUDE.md §5-ə
#: uyğundur: qayda heç nə bloklamır (bax modul başlığı — "tövsiyə sözü
#: qəsdlidir"), yalnız mətn göstərir. 21 filiallı şəbəkə "ən azı üç admin"
#: siyasəti qoya bilər, tək nəfərlik biznes isə xəbərdarlığı bir admində
#: saxlamaq istəyər — hər ikisi Root panelindən həll olunur.
RECOMMENDED_ADMIN_COUNT = fallback_int(SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT)


class SetupAlreadyCompletedError(KompasOSError):
    """Tenant-da artıq admin hesabı var — sihirbaz təkrar işlədilə bilməz."""

    user_message = "Bu quraşdırma artıq tamamlanıb."


class SetupValidationError(KompasOSError):
    """Sihirbazın forması yararsızdır."""

    user_message = "Quraşdırma məlumatları düzgün deyil."


@dataclass(frozen=True)
class StoreDraft:
    """Sihirbazın 2-ci addımı — ilk mağaza(lar)."""

    code: str
    name: str
    brand: str
    address: str = ""


@dataclass(frozen=True)
class RootAccountDraft:
    """Sihirbazın 1-ci addımı — ilk Root/CEO hesabı (SEC-016)."""

    first_name: str
    last_name: str
    username: Username
    password: str
    #: BƏRPA KANALI — giriş identifikatoru DEYİL (bölmə 2, SEC-016).
    recovery_email: EmailAddress | None = None


@dataclass(frozen=True)
class InviteDraft:
    """Sihirbazın 4-cü addımı — HR_Admin / Store Manager dəvəti."""

    first_name: str
    last_name: str
    username: Username
    role_code: str
    temporary_password: str
    store_id: StoreId | None = None
    notification_email: EmailAddress | None = None


@dataclass
class SetupOutcome:
    """Sihirbazın nəticəsi — ekranın göstərdiyi xülasə."""

    root_employee_id: EmployeeId
    store_ids: list[StoreId] = field(default_factory=list)
    invited_employee_ids: list[EmployeeId] = field(default_factory=list)
    single_admin_warning: str | None = None

    @property
    def has_warning(self) -> bool:
        return self.single_admin_warning is not None


@runtime_checkable
class StoreWriter(Protocol):
    """`stores` cədvəlinə yazma — minimal port.

    Ayrıca tam `StoreRepository` yaratmaq əvəzinə burada minimal protokol
    saxlanılır, çünki mağaza YARATMAQ yalnız iki yerdə baş verir: bu sihirbaz
    və İnfrastruktur paneli. Oxuma tərəfi isə mövcud sorğularda `JOIN` ilə
    həll olunur — ayrıca aqreqat repo-su hələ heç yerdə lazım deyil.
    """

    def create(
        self,
        *,
        store_id: StoreId,
        tenant_id: TenantId,
        code: str,
        name: str,
        brand: str,
        address: str,
    ) -> None: ...


class FirstRunSetupUseCase:
    """İlk quraşdırma — tenant-ı işlək vəziyyətə gətirir."""

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        positions: PositionRepository,
        stores: StoreWriter,
        credentials: CredentialWriter,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        # `limits` İSTƏYƏ BAĞLIDIR: sihirbaz ƏN ERKƏN axındır və `system_limits`
        # sətirləri o anda hələ oxunmaya bilər (yeni tenant, seed trigger-i
        # işləyib, lakin bağlantı konteksti quraşdırma sihirbazınındır). `None`
        # halında `RECOMMENDED_ADMIN_COUNT` fallback-ı işləyir — davranış
        # köçürmədən ƏVVƏLKİ ilə HƏRFƏN eynidir.
        self._employees = employees
        self._positions = positions
        self._stores = stores
        self._credentials = credentials
        self._audit = audit
        self._clock = clock
        self._limits = limits

    # ------------------------------ yoxlama ---------------------------------- #

    def is_required(self, tenant_id: TenantId) -> bool:
        """Sihirbaz göstərilməlidirmi — tenant-da admin hesabı yoxdursa `True`."""
        return self._admin_count(tenant_id) == 0

    def admin_count(self, tenant_id: TenantId) -> int:
        """Mövcud Root/CEO sayı — ikinci hesab tövsiyəsi üçün."""
        return self._admin_count(tenant_id)

    # ------------------------------ tamamlama -------------------------------- #

    def complete(
        self,
        *,
        tenant_id: TenantId,
        root: RootAccountDraft,
        stores: list[StoreDraft],
        invites: list[InviteDraft] | None = None,
    ) -> SetupOutcome:
        """Sihirbazın bütün addımlarını BİR əməliyyatda tətbiq edir.

        Addımlar bir-birindən asılıdır (dəvət olunan HR-a mağaza təyin
        edilir), ona görə ayrı-ayrı çağırışlara bölünmür: yarımçıq
        quraşdırma "işçi var, mağaza yox" kimi izahsız vəziyyət yaradardı.
        """
        if self._admin_count(tenant_id) > 0:
            _security_log.warning(
                "FIRST_RUN_SETUP_REPEAT_BLOCKED", extra={"tenant_id": str(tenant_id)}
            )
            raise SetupAlreadyCompletedError(
                "Tenant-da artıq admin hesabı mövcuddur",
                context={"tenant_id": str(tenant_id)},
            )
        if not stores:
            raise SetupValidationError(
                "Ən azı bir mağaza əlavə edilməlidir",
                user_message="Ən azı bir mağaza əlavə edin.",
            )

        root_position = self._require_position(tenant_id, SystemRole.ROOT.value)

        # 1. Mağazalar — işçi onlara bağlanacağı üçün ƏVVƏLCƏ yaradılır.
        store_ids: list[StoreId] = []
        for draft in stores:
            store_id = new_store_id()
            self._stores.create(
                store_id=store_id,
                tenant_id=tenant_id,
                code=_require_text(draft.code, label="Mağaza kodu"),
                name=_require_text(draft.name, label="Mağaza adı"),
                brand=_require_text(draft.brand, label="Brend"),
                address=draft.address.strip(),
            )
            store_ids.append(store_id)

        # 2. Root hesabı.
        root_id = new_employee_id()
        root_employee = Employee(
            employee_id=root_id,
            tenant_id=tenant_id,
            position=root_position,
            first_name=_require_text(root.first_name, label="Ad"),
            last_name=_require_text(root.last_name, label="Soyad"),
            store_id=None,  # Root filiala bağlanmır — bütün şəbəkəyə baxır.
            username=root.username,
            notification_email=root.recovery_email,
            has_password=True,
            # İLK Root hesabı istisnadır: şifrəni ÖZÜ təyin edir, ona görə
            # məcburi dəyişmə YOXDUR. Sonrakı bütün hesablarda admin təyin
            # etdiyi üçün `must_change_password=True` qalır.
            must_change_password=False,
        )
        self._employees.save(root_employee)
        self._credentials.set_password(root_id, raw_password=root.password, must_change=False)

        # 3. Dəvətlər.
        invited: list[EmployeeId] = []
        for invite in invites or []:
            invited.append(
                self._create_invited(tenant_id=tenant_id, invite=invite, created_by=root_id)
            )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=root_id,
            action="FIRST_RUN_SETUP_COMPLETED",
            entity_type="license_tenants",
            entity_id=tenant_id,
            after_state={
                "root_employee_id": str(root_id),
                "store_count": len(store_ids),
                "invited_count": len(invited),
                "recovery_email_set": root.recovery_email is not None,
            },
        )

        return SetupOutcome(
            root_employee_id=root_id,
            store_ids=store_ids,
            invited_employee_ids=invited,
            single_admin_warning=self._warning_for(tenant_id),
        )

    # ------------------------------- köməkçi --------------------------------- #

    def _create_invited(
        self, *, tenant_id: TenantId, invite: InviteDraft, created_by: EmployeeId
    ) -> EmployeeId:
        position = self._require_position(tenant_id, invite.role_code)
        employee_id = new_employee_id()
        employee = Employee(
            employee_id=employee_id,
            tenant_id=tenant_id,
            position=position,
            first_name=_require_text(invite.first_name, label="Ad"),
            last_name=_require_text(invite.last_name, label="Soyad"),
            store_id=invite.store_id,
            username=invite.username,
            notification_email=invite.notification_email,
            has_password=True,
            # Müvəqqəti şifrə — ilk girişdə MƏCBURİ dəyişdirilir (bölmə 2).
            must_change_password=True,
        )
        self._employees.save(employee)
        self._credentials.set_password(
            employee_id, raw_password=invite.temporary_password, must_change=True
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=created_by,
            action="EMPLOYEE_INVITED",
            entity_type="employee",
            entity_id=employee_id,
            after_state={"role": invite.role_code, "must_change_password": True},
        )
        return employee_id

    def _warning_for(self, tenant_id: TenantId) -> str | None:
        """Bölmə 2 tövsiyəsi — bloklamayan xəbərdarlıq."""
        recommended = limit_int(
            self._limits, tenant_id, SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT
        )
        if self._admin_count(tenant_id) >= recommended:
            return None
        return (
            "Hazırda yalnız bir Root/CEO hesabı var. Bu hesab bloklanarsa "
            "sistemə heç kim daxil ola bilməyəcək — ikinci müstəqil Root/CEO "
            "hesabı yaratmaq tövsiyə olunur."
        )

    def _admin_count(self, tenant_id: TenantId) -> int:
        """Aktiv Root/CEO sayı.

        Sayğac `can_manage_license` flag-i ilə hesablanır: həmin flag
        səviyyə-1 hardlock-dur, yəni YALNIZ `Root`-da (və defolt olaraq
        CEO-ya verilmir) ola bilər — beləliklə "admin var?" sualı rol adına
        deyil, struktur zəmanətə bağlanır.
        """
        return self._employees.count_active_with_flag(tenant_id, "can_manage_license")

    def _require_position(self, tenant_id: TenantId, code: str) -> Position:
        position = self._positions.get_by_code(tenant_id, code)
        if position is None:
            raise SetupValidationError(
                f"'{code}' rolu tapılmadı — baza seed-i tətbiq olunmayıb",
                user_message="Sistem rolları qurulmayıb. Baza quraşdırmasını yoxlayın.",
                context={"role_code": code},
            )
        return position


def _require_text(raw: str, *, label: str) -> str:
    cleaned = " ".join(raw.split())
    if not cleaned:
        raise SetupValidationError(
            f"{label} boş ola bilməz", user_message=f"{label} sahəsini doldurun."
        )
    return cleaned


__all__ = [
    "ADMIN_ROLE_CODES",
    "RECOMMENDED_ADMIN_COUNT",
    "FirstRunSetupUseCase",
    "InviteDraft",
    "RootAccountDraft",
    "SetupAlreadyCompletedError",
    "SetupOutcome",
    "SetupValidationError",
    "StoreDraft",
    "StoreWriter",
]
