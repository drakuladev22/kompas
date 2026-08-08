"""Rol/vəzifə aqreqatı (spesifikasiya bölmə 3).

7 defolt sistem rolu + Root/CEO-nun yaratdığı istənilən sayda custom rol.
Hər rol bir iyerarxiya prioriteti daşıyır və bu, Strict Hierarchy Guard-ın
əsasını təşkil edir.
"""

from __future__ import annotations

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.value_objects.authorization import (
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import PositionId, TenantId


class Position(AggregateRoot):
    """Rol (vəzifə) — sistem və ya custom."""

    def __init__(
        self,
        *,
        position_id: PositionId,
        code: str,
        name_az: str,
        priority: RolePriority,
        tenant_id: TenantId | None = None,
        is_system: bool = False,
        is_camera_type: bool = False,
        is_active: bool = True,
    ) -> None:
        super().__init__()
        if not code.strip():
            raise DomainRuleError("Rol kodu boş ola bilməz")

        self.id = position_id
        self.tenant_id = tenant_id
        self.code = code.strip().upper()
        self.name_az = name_az.strip()
        self.priority = priority
        self.is_system = is_system
        self.is_camera_type = is_camera_type
        self.is_active = is_active
        self._granted_flags: set[str] = set()

    # ----------------------------- sistem rolu ------------------------------ #

    @property
    def system_role(self) -> SystemRole | None:
        """Kod 7 defolt roldan birinə uyğun gəlirsə həmin rolu qaytarır."""
        try:
            return SystemRole(self.code)
        except ValueError:
            return None

    @property
    def effective_system_role(self) -> SystemRole:
        """Qoruyucu qaydaların tətbiqi üçün ən yaxın sistem rolu semantikası.

        Custom rol üçün prioritetinə görə ən yaxın sistem rolu seçilir —
        beləliklə hardlock/anti-fraud qaydaları custom rollara da tətbiq olunur
        və "custom rol yaradıb qadağanı yan keçmək" yolu bağlanır.
        """
        known = self.system_role
        if known is not None:
            return known
        return _PRIORITY_TO_ROLE[self.priority]

    # ------------------------------ icazələr -------------------------------- #

    def grant(self, flag: PermissionFlag) -> None:
        """Rola flag verir — bütün qoruyucu qaydalar yoxlanılır."""
        flag.assert_grantable_to(
            self.effective_system_role, is_camera_type_role=self.is_camera_type
        )
        self._granted_flags.add(flag.code)

    def revoke(self, flag_code: str) -> None:
        self._granted_flags.discard(flag_code)

    def has_flag(self, flag_code: str) -> bool:
        return flag_code in self._granted_flags

    @property
    def granted_flags(self) -> frozenset[str]:
        return frozenset(self._granted_flags)

    # ------------------------------ iyerarxiya ------------------------------ #

    def outranks(self, other: Position) -> bool:
        """Strict Hierarchy Guard: CİDDİ ŞƏKİLDƏ yüksəkdirmi (bərabər → False)."""
        return self.priority.outranks(other.priority)

    def deactivate(self) -> None:
        if self.is_system:
            raise DomainRuleError(
                f"Sistem rolu '{self.code}' deaktiv edilə bilməz",
                user_message="Sistem rolları silinə və ya deaktiv edilə bilməz.",
            )
        self.is_active = False

    def __repr__(self) -> str:
        return f"Position(code={self.code}, priority={self.priority.name})"


_PRIORITY_TO_ROLE: dict[RolePriority, SystemRole] = {
    RolePriority.EXECUTIVE: SystemRole.CEO,
    RolePriority.ADMIN: SystemRole.ADMIN,
    RolePriority.OPERATIONAL: SystemRole.HR_ADMIN,
    RolePriority.STAFF: SystemRole.SELLER,
}


__all__ = ["Position"]
