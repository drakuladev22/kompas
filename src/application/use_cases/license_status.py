"""Lisenziya statusuna baxış və aktivasiya açarının daxil edilməsi — Faza 3.11.

Spesifikasiya bölmə 8: *"`can_manage_license` flag-i müştərinin öz CEO/Root
panelində **yalnız** cari lisenziya statusuna baxmağa, aktivasiya açarını ilkin
quraşdırma zamanı daxil etməyə və «ÖDƏNİŞ TƏLƏB OLUNUR»/«LICENSE_INACTIVE»
xəbərdarlıqlarını görməyə icazə verir."*

──────────────────────────────────────────────────────────────────────────────
BURADA "AKTİVLƏŞDİR" METODU YOXDUR — VƏ BU, QƏSDƏNDİR
──────────────────────────────────────────────────────────────────────────────
Ən aydın çatışmayan metod `set_status()`-dur. Spesifikasiya onu birbaşa
qadağan edir: *"Tenant-ın aktiv/deaktiv statusunu dəyişmək ... istisnasız
olaraq yalnız sizin Developer Panelinizin səlahiyyətindədir — müştərinin öz
CEO/Root rolu, `can_manage_license` flag-i olsa belə, heç vaxt öz abunəsini
«aktivləşdirə» və ya söndürə bilməz."*

Bunu "icazə yoxlaması ilə qorunan metod" kimi yazmaq YANLIŞ olardı: onda
qoruma bir `if`-in düzgünlüyündən asılı qalardı. Metodun ÜMUMİYYƏTLƏ
mövcud olmaması isə strukturdur — statusu dəyişən kod (`PostgresTenantRegistry.
set_status`) yalnız lisenziya SERVERİNDƏ qurulur və müştəri tərəfdəki DI
qrafında heç vaxt görünmür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ "İNDİ YOXLA" DÜYMƏSİ VAR ("Force Sync")
──────────────────────────────────────────────────────────────────────────────
Developer Panelindən `[1 Ay Uzat]` basıldıqdan sonra müştəri proqramın
dərhal açılmasını gözləyir; növbəti avtomatik yoxlamaya 24 saat qalmış olsa,
telefon zəngi sizə gələcək. Əl ilə yoxlama düyməsi bu zəngi aradan qaldırır —
uzatma Supabase-də artıq görünür, klientə sadəcə "indi oxu" demək lazımdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.value_objects.licensing import (
    LicenseStatus,
    RestrictionKind,
    payment_warning,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.value_objects.licensing import LicenseSnapshot, LicenseState, Restriction

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Bölmə 3, "Lisenziya, Backup & Sistem" qrupu.
MANAGE_LICENSE_FLAG = "can_manage_license"


class LicenseViewError(KompasOSError):
    """Lisenziya panelinə müraciət rədd edildi."""

    user_message = "Bu bölməyə baxmaq üçün səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class LicenseOverview:
    """CEO/Root panelindəki "Lisenziya" ekranının bütün məzmunu."""

    status: LicenseStatus | None
    status_label_az: str
    tenant_name: str
    last_check_in_at: datetime | None
    last_payment_date: object | None
    next_payment_date: object | None
    expires_at: datetime | None
    license_days_left: int | None
    offline_grace_days_left: int | None
    payment_banner_az: str
    restrictions: tuple[Restriction, ...]
    is_blocked: bool

    @property
    def blocking_restriction(self) -> Restriction | None:
        return next((item for item in self.restrictions if item.blocks_everything), None)

    @property
    def is_healthy(self) -> bool:
        """Heç bir lisenziya xəbərdarlığı yoxdur (saat sürüşməsi ayrıca statusdur)."""
        return self.status is LicenseStatus.AKTIV and not any(
            item.kind in {RestrictionKind.LICENSE_INACTIVE, RestrictionKind.LICENSE_UNVERIFIED}
            for item in self.restrictions
        )


class LicenseStatusUseCase:
    """Lisenziya statusuna baxış + əl ilə yoxlama.

    Asılılıq YALNIZ `LicenseClient` protokoluna bənzər üç metoddur; konkret
    HTTP və ya DB tipi bura gəlmir (qat qaydası — `use_cases/__init__.py`).
    """

    def __init__(self, client: _LicenseClientLike) -> None:
        self._client = client

    def overview(self, actor: Employee, *, now: datetime) -> LicenseOverview:
        """Ekranın məzmunu. `can_manage_license` TƏLƏB OLUNUR."""
        self._require_permission(actor, operation="VIEW_LICENSE", now=now)
        state = self._client.current_state()
        return _build_overview(state, banner=self._client.payment_banner())

    def refresh(self, actor: Employee, *, now: datetime) -> LicenseOverview:
        """ "İndi yoxla" — dərhal check-in edir, sonra yenilənmiş ekranı qaytarır.

        Check-in uğursuz olsa belə XƏTA ATMIR: ekran keşlənmiş vəziyyəti və
        səbəb mətnini göstərir. "Yoxlaya bilmədik" ekranı boş xəta dialoqundan
        istifadəçi üçün daha faydalıdır.
        """
        self._require_permission(actor, operation="REFRESH_LICENSE", now=now)
        self._client.check_in()
        state = self._client.current_state()
        return _build_overview(state, banner=self._client.payment_banner())

    # ------------------------------- icazə ----------------------------------- #

    def _require_permission(self, actor: Employee, *, operation: str, now: datetime) -> None:
        if not actor.has_permission(MANAGE_LICENSE_FLAG, now=now):
            _security_log.warning(
                "LICENSE_VIEW_DENIED",
                extra={
                    "actor_id": str(actor.id),
                    "role": actor.position.code,
                    "operation": operation,
                    "reason": "MISSING_FLAG",
                },
            )
            raise LicenseViewError(
                f"`{MANAGE_LICENSE_FLAG}` icazəsi yoxdur",
                context={"actor_id": str(actor.id), "operation": operation},
            )


def _build_overview(state: LicenseState, *, banner: str) -> LicenseOverview:
    snapshot: LicenseSnapshot | None = state.snapshot
    status = snapshot.status if snapshot else None
    return LicenseOverview(
        status=status,
        status_label_az=status.label_az if status else "Naməlum",
        tenant_name=snapshot.tenant_name if snapshot else "",
        last_check_in_at=snapshot.checked_at if snapshot else None,
        last_payment_date=snapshot.last_payment_date if snapshot else None,
        next_payment_date=snapshot.next_payment_date if snapshot else None,
        expires_at=snapshot.expires_at if snapshot else None,
        license_days_left=state.license_days_left,
        offline_grace_days_left=state.offline_grace_days_left,
        payment_banner_az=banner,
        restrictions=state.restrictions,
        is_blocked=state.is_blocked,
    )


class _LicenseClientLike:
    """Use case-in `LicenseClient`-dən gözlədiyi minimal səth.

    Ayrıca `Protocol` kimi `ports.py`-a əlavə EDİLMİR: bu, bir use case-in
    daxili detalıdır və domenin portlar kataloqunu şişirtməyə dəyməz.
    """

    def current_state(self) -> LicenseState:  # pragma: no cover - imza
        raise NotImplementedError

    def payment_banner(self) -> str:  # pragma: no cover - imza
        raise NotImplementedError

    def check_in(self) -> LicenseSnapshot | None:  # pragma: no cover - imza
        raise NotImplementedError


def blocked_screen_text(state: LicenseState) -> tuple[str, str, str]:
    """`LICENSE_INACTIVE` ekranının üç hissəsi: başlıq, izah, əlaqə.

    Bölmə 8: ekran ümumi xəta mesajı OLMAMALIDIR. Mətnin özü domendə
    (`licensing.evaluate`) formalaşır — burada yalnız UI üçün açılır.
    """
    restriction = state.blocking_restriction
    if restriction is None:
        return ("", "", "")
    contact = restriction.contact_az or "Təchizatçı ilə əlaqə saxlayın."
    return (restriction.headline_az, restriction.detail_az, contact)


__all__ = [
    "MANAGE_LICENSE_FLAG",
    "LicenseOverview",
    "LicenseStatusUseCase",
    "LicenseViewError",
    "blocked_screen_text",
    "payment_warning",
]
