"""Kirayəçi brendinqinin oxunması və dəyişdirilməsi (TENANT-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
OXUMAQ İCAZƏ TƏLƏB ETMİR, YAZMAQ EDİR
──────────────────────────────────────────────────────────────────────────────
`current()` hər kəsə açıqdır və olmalıdır: başlıq zolağı, splash ekranı və
giriş ekranı onu İSTİFADƏÇİ SEÇİLMƏMİŞDƏN ƏVVƏL oxuyur. İcazə tələb etsəydik,
tətbiq öz adını göstərmək üçün əvvəlcə kiminsə giriş etməsini gözləməli
olardı.

Yazma isə `can_manage_system_limits` tələb edir — eyni flag ROOT İdarə
Mərkəzini açır. Ayrı flag YARADILMADI: brendinq həmin panelin bir bölməsidir
və ikinci flag admin matrisinə praktiki fərqi olmayan bir sətir də əlavə
edərdi (`CLAUDE.md` §5: yeni flag yalnız yeni MƏSULİYYƏT üçün).

──────────────────────────────────────────────────────────────────────────────
UYĞUNSUZ RƏNG RƏDD EDİLMİR — İŞARƏLƏNİR
──────────────────────────────────────────────────────────────────────────────
Bax `value_objects/branding.py` başlığı: müştərinin rəsmi brend rəngi
həqiqətən açıq ola bilər və onu sistemə salmağı tamamilə qadağan etmək
qərarı bizim əvəzimizə müştəriyə verməkdir. Ona görə use case dəyəri YAZIR,
lakin nəticədə xəbərdarlıq qaytarır və audit yazısına da onu əlavə edir —
sonradan «niyə ekran oxunmur?» sualı cavabsız qalmasın.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.domain.value_objects.branding import BrandingError, TenantBranding
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, BrandingRepository, Clock
    from src.domain.value_objects.identifiers import TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: ROOT İdarə Mərkəzini açan flag — brendinq onun bölməsidir (bax modul başlığı).
MANAGE_BRANDING_FLAG: Final = "can_manage_system_limits"


class BrandingPermissionError(KompasOSError):
    """Səlahiyyətsiz brendinq dəyişikliyi cəhdi."""

    user_message = "Şirkət kimliyini dəyişmək səlahiyyətiniz yoxdur."


class BrandingValidationError(KompasOSError):
    """Format/ölçü qaydası pozuldu (PNG deyil, çox böyük, yanlış rəng)."""

    user_message = "Verilən dəyər qəbul edilmədi."


@dataclass(frozen=True)
class BrandingUpdateResult:
    """Yazma nəticəsi — xəbərdarlıq varsa ekran onu göstərir."""

    branding: TenantBranding
    #: Boş sətir = problem yoxdur.
    warning: str = ""


class TenantBrandingUseCase:
    """Şirkət adı, loqo və vurğu rənginin idarəsi."""

    def __init__(
        self,
        *,
        repository: BrandingRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    def current(self, tenant_id: TenantId) -> TenantBranding:
        """Cari brendinq — İCAZƏ TƏLƏB ETMİR (bax modul başlığı)."""
        return self._repository.get(tenant_id)

    def update(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        company_name: str | None = None,
        logo_png: bytes | None = None,
        accent_color: str | None = None,
        clear_logo: bool = False,
        clear_accent: bool = False,
    ) -> BrandingUpdateResult:
        """Brendinqi yeniləyir.

        `None` «dəyişmə» deməkdir, «sil» DEYİL — silmək üçün açıq `clear_*`
        bayraqları var. İkisini ayırmaq məcburidir: `None`-u «sil» saysaydıq,
        yalnız şirkət adını dəyişən ekran loqonu da sükutla silərdi.
        """
        self._require(actor)
        current = self._repository.get(tenant_id)

        try:
            updated = TenantBranding(
                company_name=(
                    current.company_name if company_name is None else company_name.strip()
                ),
                logo_png=None if clear_logo else (logo_png or current.logo_png),
                accent_color=None if clear_accent else (accent_color or current.accent_color),
            )
        except BrandingError as exc:
            raise BrandingValidationError(str(exc), user_message=str(exc)) from exc

        self._repository.save(tenant_id, updated, updated_by=actor.id)

        warning = updated.accessibility_warning()
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="TENANT_BRANDING_UPDATED",
            entity_type="tenant_branding",
            entity_id=str(tenant_id),
            before_state=_snapshot(current),
            after_state=_snapshot(updated),
            # Xəbərdarlıq audit izinə DÜŞÜR: sonradan «niyə ekran oxunmur?»
            # sualı verildikdə dəyərin qəbul anında bilinən olduğu görünsün.
            reason=warning or None,
        )
        return BrandingUpdateResult(branding=updated, warning=warning)

    def _require(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_BRANDING_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "BRANDING_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_BRANDING_FLAG},
            )
            raise BrandingPermissionError(
                f"«{MANAGE_BRANDING_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


def _snapshot(branding: TenantBranding) -> dict[str, object]:
    """Audit üçün surət — LOQONUN ÖZÜ yazılmır, yalnız həcmi.

    İkili məzmunu `audit_logs.after_state` JSONB sütununa yazmaq həm sətri
    yüzlərlə kilobayt böyüdərdi, həm də audit oxunuşunu praktiki olaraq
    mümkünsüz edərdi. «Loqo dəyişdi» faktı üçün həcm kifayətdir.
    """
    return {
        "company_name": branding.company_name,
        "logo_bytes": len(branding.logo_png) if branding.logo_png else 0,
        "accent_color": branding.accent_color,
    }


__all__ = [
    "MANAGE_BRANDING_FLAG",
    "BrandingPermissionError",
    "BrandingUpdateResult",
    "BrandingValidationError",
    "TenantBrandingUseCase",
]
