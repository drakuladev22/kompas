"""İcazə sisteminin value object-ləri (spesifikasiya bölmə 3).

Burada Discord-tərzi icazə modelinin DƏYİŞMƏZ QAYDALARI kodlaşdırılır:

* **İyerarxiya prioriteti** — `Root`/`CEO`=0, `Admin`=1, operativ rollar=2,
  `Satıcı`=3. Kiçik rəqəm = yüksək səlahiyyət.
* **Dörd-səviyyəli hardlock** — hansı flag-in kimə verilə biləcəyi.
* **Anti-fraud vəzifə ayrılığı** — kamera flag-ləri heç vaxt
  `Mağaza_Meneceri`/`Satıcı`-ya verilmir; təsdiq flag-i isə kamera roluna
  verilmir (SEC-001).

Bu qaydalar `docs/security_decisions.md`-də HARDCODED elan olunub və Feature
Toggle ilə söndürülə bilməz. DB tərəfində eyni qaydalar trigger kimi təkrarlanır
(defense-in-depth, `schema.sql` §18).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Final

from src.shared.exceptions import KompasOSError


class AuthorizationError(KompasOSError):
    """İcazə qaydası pozuldu."""

    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


# --------------------------------------------------------------------------- #
# İyerarxiya
# --------------------------------------------------------------------------- #


class RolePriority(IntEnum):
    """Rol iyerarxiyası — KİÇİK rəqəm DAHA YÜKSƏK səlahiyyət deməkdir.

    Spesifikasiya bölmə 3: "Root/CEO = ən üst pillə (0) → Admin = CEO-dan bir
    pillə aşağı (1) → HR_Admin/Mağaza_Meneceri/Kamera_Nəzarətçisi = operativ
    rollar (2) → Satıcı/digər personel = ən aşağı pillə (3)."
    """

    EXECUTIVE = 0  # Root, CEO
    ADMIN = 1  # Admin
    OPERATIONAL = 2  # HR_Admin, Mağaza_Meneceri, Kamera_Nəzarətçisi
    STAFF = 3  # Satıcı və digər personel

    def outranks(self, other: RolePriority) -> bool:
        """`self` `other`-dan CİDDİ ŞƏKİLDƏ yüksəkdirmi.

        Strict Hierarchy Guard-ın əsası: bərabər pillə `False` qaytarır.
        """
        return self.value < other.value


class SystemRole(str, Enum):
    """7 defolt sistem rolu (spesifikasiya bölmə 3)."""

    ROOT = "ROOT"
    CEO = "CEO"
    ADMIN = "ADMIN"
    HR_ADMIN = "HR_ADMIN"
    STORE_MANAGER = "MAGAZA_MENECERI"
    CAMERA_OPERATOR = "KAMERA_NEZARETCISI"
    SELLER = "SATICI"

    @property
    def default_priority(self) -> RolePriority:
        return _DEFAULT_PRIORITIES[self]

    @property
    def is_camera_type(self) -> bool:
        """Kamera-əməliyyat flag-lərini daşıya bilən rol."""
        return self is SystemRole.CAMERA_OPERATOR


_DEFAULT_PRIORITIES: Final[dict[SystemRole, RolePriority]] = {
    SystemRole.ROOT: RolePriority.EXECUTIVE,
    SystemRole.CEO: RolePriority.EXECUTIVE,
    SystemRole.ADMIN: RolePriority.ADMIN,
    SystemRole.HR_ADMIN: RolePriority.OPERATIONAL,
    SystemRole.STORE_MANAGER: RolePriority.OPERATIONAL,
    SystemRole.CAMERA_OPERATOR: RolePriority.OPERATIONAL,
    SystemRole.SELLER: RolePriority.STAFF,
}

#: Anti-fraud flag-lərinin HEÇ VAXT verilə bilməyəcəyi rollar (bölmə 3).
ANTI_FRAUD_FORBIDDEN_ROLES: Final[frozenset[SystemRole]] = frozenset(
    {SystemRole.STORE_MANAGER, SystemRole.SELLER}
)


# --------------------------------------------------------------------------- #
# Hardlock
# --------------------------------------------------------------------------- #


class HardlockLevel(IntEnum):
    """Dörd-səviyyəli hardlock iyerarxiyası (spesifikasiya bölmə 3).

    NONE:      adi operativ flag — rol-defolt + fərdi override.
    ROOT_ONLY: yalnız `Root` — `CEO`-ya belə verilmir.
    ROOT_CEO:  `Root` VƏ `CEO`.
    DELEGABLE: Root/CEO tərəfindən `Admin`-ə həvalə edilə bilər
               (Hierarchy + Self-Escalation Guard-a tabe).
    """

    NONE = 0
    ROOT_ONLY = 1
    ROOT_CEO = 2
    DELEGABLE = 3

    def allows(self, role: SystemRole) -> bool:
        """Bu hardlock səviyyəsi verilmiş rola icazə verirmi."""
        if self is HardlockLevel.NONE:
            return True
        if self is HardlockLevel.ROOT_ONLY:
            return role is SystemRole.ROOT
        if self is HardlockLevel.ROOT_CEO:
            return role in (SystemRole.ROOT, SystemRole.CEO)
        return role.default_priority <= RolePriority.ADMIN


class PermissionEffect(str, Enum):
    """Fərdi override effekti — rol-defoltdan ÜSTÜNDÜR."""

    GRANT = "GRANT"
    DENY = "DENY"


# --------------------------------------------------------------------------- #
# Flag
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PermissionFlag:
    """Bir icazə flag-inin tam tərifi (`permission_flags` cədvəlinin əksi).

    Attributes:
        code: `can_issue_fines` kimi maşın-oxunaqlı açar.
        category: Admin panelində qruplaşdırma üçün.
        hardlock: Kimə verilə biləcəyini məhdudlaşdırır.
        is_anti_fraud: `Mağaza_Meneceri`/`Satıcı`-ya HEÇ VAXT verilmir.
        is_camera_only: ƏLAVƏ OLARAQ yalnız kamera-tipli rollarda ola bilər.
    """

    code: str
    category: str
    hardlock: HardlockLevel = HardlockLevel.NONE
    is_anti_fraud: bool = False
    is_camera_only: bool = False

    def __post_init__(self) -> None:
        if not self.code or not self.code.startswith("can_"):
            raise ValueError(f"Flag kodu 'can_' ilə başlamalıdır: {self.code!r}")
        if self.is_camera_only and not self.is_anti_fraud:
            raise ValueError(
                f"{self.code}: `is_camera_only` yalnız anti-fraud flag-lərdə mənalıdır (SEC-001)"
            )

    # --------------------------- qoruyucu qaydalar -------------------------- #

    def assert_grantable_to(self, role: SystemRole, *, is_camera_type_role: bool = False) -> None:
        """Flag-in bu rola verilə biləcəyini yoxlayır, əks halda istisna atır.

        Args:
            role: Hədəf rol (custom rol üçün ən yaxın sistem rolu semantikası).
            is_camera_type_role: Custom rol açıq şəkildə "kamera-tipli"
                işarələnibsə `True`.
        """
        camera_capable = is_camera_type_role or role.is_camera_type

        if self.is_anti_fraud and role in ANTI_FRAUD_FORBIDDEN_ROLES:
            raise AuthorizationError(
                f"ANTI-FRAUD: '{self.code}' flag-i '{role.value}' rolunda ola bilməz "
                f"— vəzifə ayrılığı (bölmə 3)",
                context={"flag": self.code, "role": role.value},
            )

        if self.is_camera_only and not camera_capable:
            raise AuthorizationError(
                f"ANTI-FRAUD: '{self.code}' yalnız kamera-tipli rollarda ola bilər",
                context={"flag": self.code, "role": role.value},
            )

        # SEC-001: override YARADAN rol onu TƏSDİQLƏYƏ bilməz.
        if self.code == DUAL_CONTROL_APPROVAL_FLAG and camera_capable:
            raise AuthorizationError(
                "VƏZİFƏ AYRILIĞI: kamera-tipli rol dual-control təsdiqini daşıya "
                "bilməz — operator öz override-ını özü təsdiqləyərdi (SEC-001)",
                context={"flag": self.code, "role": role.value},
            )

        if not self.hardlock.allows(role):
            raise AuthorizationError(
                f"HARDLOCK (səviyyə {self.hardlock.value}): '{self.code}' flag-i "
                f"'{role.value}' rolunda ola bilməz",
                context={"flag": self.code, "role": role.value},
            )

    def is_grantable_to(self, role: SystemRole, *, is_camera_type_role: bool = False) -> bool:
        """İstisna atmayan variant — UI-da elementi gizlətmək üçün."""
        try:
            self.assert_grantable_to(role, is_camera_type_role=is_camera_type_role)
        except AuthorizationError:
            return False
        return True


DUAL_CONTROL_APPROVAL_FLAG: Final[str] = "can_approve_dual_control_override"


__all__ = [
    "ANTI_FRAUD_FORBIDDEN_ROLES",
    "DUAL_CONTROL_APPROVAL_FLAG",
    "AuthorizationError",
    "HardlockLevel",
    "PermissionEffect",
    "PermissionFlag",
    "RolePriority",
    "SystemRole",
]
