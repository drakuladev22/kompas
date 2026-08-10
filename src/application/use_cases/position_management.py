"""Custom rol/vəzifə idarəetməsi — `can_manage_positions` (bölmə 3) — Faza 5.

    "Sistem 7 defolt rola əlavə olaraq, Root/CEO-ya **istənilən sayda xüsusi
     (custom) rol/vəzifə yaratmaq** imkanı verir (məs. «Anbar Nəzarətçisi»,
     «Bölgə Meneceri») — Discord-da custom rol yaratmaq kimi."

──────────────────────────────────────────────────────────────────────────────
İKİ FLAG, İKİ FƏRQLİ İŞ (QARIŞDIRILMAMALIDIR)
──────────────────────────────────────────────────────────────────────────────
    `can_manage_permissions`  → YENİ FLAG yaratmaq. YALNIZ `Root`.
                                (`root_control.py` — Permission Registry)
    `can_manage_positions`    → MÖVCUD flag-lərdən YENİ ROL tərtib etmək.
                                `Root` VƏ `CEO`.

Bu modul İKİNCİSİDİR. Fərq bölmə 3-də açıq yazılıb: "CEO mövcud flag-lərdən
yeni ROL təşkil edə bilər, sadəcə yeni FLAG yarada bilməz".

──────────────────────────────────────────────────────────────────────────────
CUSTOM ROL QADAĞANI YAN KEÇƏ BİLMİR
──────────────────────────────────────────────────────────────────────────────
Ən aşkar hücum yolu budur: "Mağaza_Meneceri kamera flag-i ala bilmirsə, ona
kamera flag-i olan CUSTOM rol verərəm". Bu bağlıdır və üç qatda:

    1. `Position.effective_system_role` — custom rol prioritetinə görə ən yaxın
       sistem rolu kimi qiymətləndirilir, yəni prioritet 2-li custom rol
       operativ rol qaydalarına tabedir.
    2. `PermissionFlag.assert_grantable_to()` — hardlock + anti-fraud.
    3. `is_camera_type` bayrağı — kamera flag-ləri YALNIZ açıq şəkildə
       "kamera-tipli" işarələnmiş rollarda ola bilər (bölmə 3).

Bu modul həmin qatları ÇAĞIRIR, təkrar yazmır.

──────────────────────────────────────────────────────────────────────────────
KAMERA-TİPLİ ROL YARATMAQ NİYƏ ƏLAVƏ ŞƏRTLƏ MƏHDUDDUR
──────────────────────────────────────────────────────────────────────────────
`is_camera_type=True` custom rol praktikada `Kamera_Nəzarətçisi`-nin
ekvivalentidir və maliyyə nəticəli səlahiyyət daşıya bilər. Ona görə onu
yalnız prioritet ≤ OPERATIONAL (2) səviyyəsində yaratmağa icazə verilir:
`Satıcı` pilləsində kamera-tipli rol yaratmaq, satıcıya cərimə yazma hüququ
verməyin dolayı yolu olardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    AuthorizationError,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import new_position_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        PermissionFlagRepository,
        PositionRepository,
    )
    from src.domain.value_objects.identifiers import PositionId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

MANAGE_POSITIONS_FLAG = "can_manage_positions"

MIN_ROLE_NAME_LENGTH = 2
MAX_ROLE_NAME_LENGTH = 80

#: Kamera-tipli custom rol ən aşağı bu pillədə ola bilər (modul başlığına bax).
MAX_CAMERA_ROLE_PRIORITY = RolePriority.OPERATIONAL


class PositionManagementError(KompasOSError):
    """Rol əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Rol əməliyyatı icra edilə bilmədi."


class PositionNotFoundError(PositionManagementError):
    user_message = "Rol tapılmadı."


@dataclass(frozen=True)
class RoleDraft:
    """İcazə Matrisi ekranındakı "Yeni rol" formasının məzmunu."""

    code: str
    name_az: str
    priority: RolePriority
    is_camera_type: bool = False
    #: Rola dərhal veriləcək flag kodları (boş da ola bilər).
    flag_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoleSummary:
    """Matris ekranının sol panelindəki sətir."""

    position: Position
    is_editable: bool
    flag_count: int


class PositionManagementUseCase:
    """Custom rol yaratma/redaktə — İcazə Matrisi ekranının arxa tərəfi."""

    def __init__(
        self,
        *,
        positions: PositionRepository,
        flags: PermissionFlagRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._positions = positions
        self._flags = flags
        self._audit = audit
        self._clock = clock

    # -------------------------------- baxış ---------------------------------- #

    def list_roles(self, *, tenant_id: TenantId, actor: Employee) -> list[RoleSummary]:
        """Bütün rollar — sistem rolları "redaktə edilə bilməz" işarəsi ilə.

        Sistem rolu SİLİNMİR/DEAKTİV EDİLMİR (`Position.deactivate` bunu
        bloklayır), lakin ona flag vermək/almaq mümkündür — bölmə 3-dəki
        "rol-defolt" modeli məhz bunu nəzərdə tutur.
        """
        self._require_permission(actor)
        return [
            RoleSummary(
                position=position,
                is_editable=not position.is_system,
                flag_count=len(position.granted_flags),
            )
            for position in self._positions.list_for_tenant(tenant_id)
        ]

    # ------------------------------- yaratma --------------------------------- #

    def create_role(self, *, tenant_id: TenantId, actor: Employee, draft: RoleDraft) -> Position:
        """Yeni custom rol yaradır və seçilmiş flag-ləri təyin edir."""
        self._require_permission(actor)
        code = _clean_code(draft.code)
        name = _clean_name(draft.name_az)

        if _is_system_code(code):
            raise PositionManagementError(
                f"'{code}' sistem rol kodudur — custom rol bu adı daşıya bilməz",
                user_message="Bu ad sistem rolları üçün ayrılıb, başqa ad seçin.",
                context={"code": code},
            )
        if self._positions.get_by_code(tenant_id, code) is not None:
            raise PositionManagementError(
                f"'{code}' kodlu rol artıq mövcuddur",
                user_message="Bu adda rol artıq var.",
                context={"code": code},
            )
        if draft.is_camera_type and draft.priority > MAX_CAMERA_ROLE_PRIORITY:
            raise PositionManagementError(
                "Kamera-tipli rol ən aşağı operativ pillədə (2) ola bilər",
                user_message=(
                    "Kamera-tipli rol yalnız operativ və ya daha yüksək pillədə yaradıla bilər."
                ),
                context={"priority": draft.priority.name},
            )

        position = Position(
            position_id=new_position_id(),
            code=code,
            name_az=name,
            priority=draft.priority,
            tenant_id=tenant_id,
            is_system=False,
            is_camera_type=draft.is_camera_type,
        )
        granted = self._apply_flags(position, draft.flag_codes, actor=actor)
        self._positions.save(position)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_CREATED",
            entity_type="positions",
            entity_id=position.id,
            after_state={
                "code": code,
                "name_az": name,
                "priority": int(draft.priority),
                "is_camera_type": draft.is_camera_type,
                "flags": sorted(granted),
            },
        )
        return position

    # ------------------------------- redaktə --------------------------------- #

    def set_role_flags(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        position_id: PositionId,
        flag_codes: tuple[str, ...],
    ) -> Position:
        """Rolun flag dəstini TAM əvəzləyir (checkbox-grid-in "Yadda saxla"-sı).

        Fərqli yanaşma (yalnız dəyişənləri göndərmək) ekranı vəziyyət
        izləməyə məcbur edərdi; matris onsuz da bütün xanaları göndərir.
        """
        self._require_permission(actor)
        position = self._require_position(position_id)
        before = sorted(position.granted_flags)

        for code in before:
            position.revoke(code)
        granted = self._apply_flags(position, flag_codes, actor=actor)
        self._positions.save(position)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_FLAGS_UPDATED",
            entity_type="positions",
            entity_id=position.id,
            before_state={"flags": before},
            after_state={"flags": sorted(granted)},
        )
        return position

    def rename_role(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        position_id: PositionId,
        name_az: str,
    ) -> Position:
        """Rolun görünən adını dəyişir — kod TOXUNULMAZ qalır.

        Kod dəyişməsi mümkün deyil, çünki `position_permissions` və audit
        sətirləri ona istinad edir; ad isə sadəcə etiketdir.
        """
        self._require_permission(actor)
        position = self._require_position(position_id)
        if position.is_system:
            raise PositionManagementError(
                f"Sistem rolu '{position.code}' adlandırıla bilməz",
                user_message="Sistem rollarının adı dəyişdirilə bilməz.",
                context={"code": position.code},
            )

        before = position.name_az
        position.name_az = _clean_name(name_az)
        self._positions.save(position)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_RENAMED",
            entity_type="positions",
            entity_id=position.id,
            before_state={"name_az": before},
            after_state={"name_az": position.name_az},
        )
        return position

    def deactivate_role(
        self, *, tenant_id: TenantId, actor: Employee, position_id: PositionId
    ) -> Position:
        """Custom rolu deaktiv edir (sistem rolları üçün istisna atır)."""
        self._require_permission(actor)
        position = self._require_position(position_id)

        position.deactivate()
        self._positions.save(position)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_DEACTIVATED",
            entity_type="positions",
            entity_id=position.id,
            before_state={"is_active": True},
            after_state={"is_active": False, "code": position.code},
        )
        return position

    # ------------------------------- köməkçi --------------------------------- #

    def _apply_flags(
        self, position: Position, flag_codes: tuple[str, ...], *, actor: Employee
    ) -> set[str]:
        """Flag-ləri rola verir; qadağan olunan hər cəhd istisna atır.

        SELF-ESCALATION GUARD (bölmə 3): aktor YALNIZ ÖZÜNDƏ AKTİV OLAN
        flag-ləri rola verə bilər. Bu, `permission_guards.py`-dakı fərdi
        override qaydasının rol tərəfindəki qarşılığıdır — onsuz CEO özündə
        olmayan bir flag-i custom rola qoyub həmin rolu özünə təyin edə bilərdi.
        """
        now = self._clock.now()
        applied: set[str] = set()

        for code in flag_codes:
            flag = self._flags.get(code)
            if flag is None:
                raise PositionManagementError(
                    f"'{code}' icazə flag-i kataloqda yoxdur",
                    user_message="Seçilmiş icazə mövcud deyil.",
                    context={"flag": code},
                )
            if not actor.has_permission(code, now=now):
                _security_log.warning(
                    "POSITION_SELF_ESCALATION_BLOCKED",
                    extra={"actor_id": str(actor.id), "flag": code},
                )
                raise AuthorizationError(
                    f"SELF-ESCALATION: özünüzdə olmayan '{code}' flag-ini rola verə bilməzsiniz",
                    context={"actor_id": str(actor.id), "flag": code},
                )
            # Hardlock + anti-fraud + kamera qaydaları burada işə düşür.
            position.grant(flag)
            applied.add(code)

        return applied

    def _require_position(self, position_id: PositionId) -> Position:
        position = self._positions.get(position_id)
        if position is None:
            raise PositionNotFoundError("Rol tapılmadı", context={"position_id": str(position_id)})
        return position

    def _require_permission(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_POSITIONS_FLAG, now=self._clock.now()):
            _security_log.warning(
                "POSITION_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_POSITIONS_FLAG},
            )
            raise AuthorizationError(
                f"«{MANAGE_POSITIONS_FLAG}» səlahiyyəti yoxdur — rol idarəetməsi "
                f"yalnız Root/CEO-dadır (bölmə 3)",
                context={"actor_id": str(actor.id)},
            )


def _clean_code(raw: str) -> str:
    cleaned = "_".join(raw.strip().upper().split())
    if not cleaned:
        raise PositionManagementError(
            "Rol kodu boş ola bilməz", user_message="Rol adı boş ola bilməz."
        )
    return cleaned


def _clean_name(raw: str) -> str:
    cleaned = " ".join(raw.split())
    if len(cleaned) < MIN_ROLE_NAME_LENGTH:
        raise PositionManagementError(
            f"Rol adı minimum {MIN_ROLE_NAME_LENGTH} simvol olmalıdır",
            user_message="Rol adı çox qısadır.",
        )
    if len(cleaned) > MAX_ROLE_NAME_LENGTH:
        raise PositionManagementError(
            f"Rol adı maksimum {MAX_ROLE_NAME_LENGTH} simvol ola bilər",
            user_message="Rol adı çox uzundur.",
        )
    return cleaned


def _is_system_code(code: str) -> bool:
    try:
        SystemRole(code)
    except ValueError:
        return False
    return True


__all__ = [
    "MANAGE_POSITIONS_FLAG",
    "MAX_CAMERA_ROLE_PRIORITY",
    "PositionManagementError",
    "PositionManagementUseCase",
    "PositionNotFoundError",
    "RoleDraft",
    "RoleSummary",
]
