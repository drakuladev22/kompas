"""«Nə Yeni?» dəyişiklik-jurnalı — `v2backlog.md` Faza 8.2.

    ""Nə Yeni?" Dəyişiklik-Jurnalı Ekranı: CEO/HR_Admin görünüşündə, sadə bir
     "versiya-qeydləri" ekranı (Root panelindən mətn-əlavə edilə bilən)."

──────────────────────────────────────────────────────────────────────────────
NİYƏ `app_versions.release_notes_az` İSTİFADƏ EDİLMİR
──────────────────────────────────────────────────────────────────────────────
Vendor-un `app_versions` cədvəli (migrations/008/009) BURAXILIŞ qeydləridir:
onun mənbəyi təchizatçıdır və Vendor Konsolu vasitəsilə yazılır. Spesifikasiya
isə KİRAYƏÇİ daxilində Root-un ÖZ qeydlərini istəyir («Root panelindən
mətn-əlavə edilə bilən») — məs. «bax bu buraxılışda cərimə ekranı dəyişdi,
menecerlərinizi məlumatlandırın». İki fərqli MÜƏLLİF iki fərqli cədvəldədir;
birləşdirsəydik, kirayəçi vendor cədvəlinə yazmağa çalışar və ya əksinə.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA DEYİL
──────────────────────────────────────────────────────────────────────────────
Hər əməliyyat TƏK aqreqata (bir sətrə) toxunur; audit EYNI tranzaksiyadadır.
Uğursuzluqda rollback tam bərpadır (`campaign_periods.py` ilə eyni meyar).

──────────────────────────────────────────────────────────────────────────────
İKİ FLAG NİYƏ BİRİNİN İKİ ROLO DEYİL
──────────────────────────────────────────────────────────────────────────────
Spesifikasiyanın İKİ ayrı cümləsi var: «Root panelindən mətn-əlavə edilə
bilən» (YAZAN: Root) və «CEO/HR_Admin görünüşündə» (OXUYAN: rəhbərlik).
Birləşdirilmiş bir flag-da oxumaq da yazmaq da verərdi — HR_Admin nəşr edərdi,
Root isə öz qeydini görə bilməzdi. `can_view_whats_new` + `can_publish_whats_
new` (migrations/104) bu iki rolu AYRI saxlayır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final, Protocol

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock
    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__, channel=LogChannel.AUDIT)

VIEW_WHATS_NEW_FLAG: Final = "can_view_whats_new"
PUBLISH_WHATS_NEW_FLAG: Final = "can_publish_whats_new"

#: Versiya etiketinin maksimum uzunluğu — DB `CHECK` güzgüsüdür (migrations/
#: 104): etiket başlıq ZOLAĞINDA görünür, "0.2.0 (avqust)" formasından uzun
#: mətn orada sığmır. Biznes həddidir və Root parametri deyil, çünki o, EKRANIN
#: ölçüsünün nəticəsidir (`PANEL_LIMIT` pretsedenti).
MAX_VERSION_LABEL_LENGTH: Final = 40

MIN_TITLE_LENGTH: Final = 3
MIN_BODY_LENGTH: Final = 10


class WhatsNewError(KompasOSError):
    """«Nə Yeni?» əməliyyatı icra edilə bilmədi."""

    user_message = "Versiya qeydi yazıla bilmədi."


class WhatsNewPermissionError(WhatsNewError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class WhatsNewEntry:
    """Bir versiya-qeydinin oxu-modeli — tətbiq qatının strukturudur."""

    entry_id: str
    version_label: str
    title_az: str
    body_az: str
    is_active: bool
    created_at: datetime


class WhatsNewRepository(Protocol):
    """Yalnız bu use case-in istifadə etdiyi oxu/yazı səthi."""

    def list_entries(
        self, tenant_id: TenantId, *, include_inactive: bool
    ) -> list[WhatsNewEntry]: ...

    def create(
        self,
        tenant_id: TenantId,
        *,
        version_label: str,
        title_az: str,
        body_az: str,
        created_by_id: object,
    ) -> WhatsNewEntry: ...

    def deactivate(self, tenant_id: TenantId, entry_id: str) -> bool: ...


class WhatsNewUseCase:
    """Root versiya-qeydi yazır; CEO/HR_Admin siyahısını oxuyur."""

    def __init__(
        self,
        *,
        repository: WhatsNewRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    # ------------------------------- yazı ------------------------------------ #

    def publish(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        version_label: str,
        title_az: str,
        body_az: str,
    ) -> WhatsNewEntry:
        self._require(actor, PUBLISH_WHATS_NEW_FLAG)

        label = version_label.strip()
        title = title_az.strip()
        body = body_az.strip()
        if not label or len(label) > MAX_VERSION_LABEL_LENGTH:
            raise WhatsNewError(
                "Versiya etiketi boşdur və ya çox uzundur",
                user_message=(
                    f"Etiket 1–{MAX_VERSION_LABEL_LENGTH} simvol olmalıdır (məs. «0.2.0 (avqust)»)."
                ),
                context={"length": len(label)},
            )
        if len(title) < MIN_TITLE_LENGTH:
            raise WhatsNewError(
                "Başlıq çox qısadır",
                user_message=f"Başlıq ən azı {MIN_TITLE_LENGTH} simvol olmalıdır.",
            )
        if len(body) < MIN_BODY_LENGTH:
            raise WhatsNewError(
                "Mətn çox qısadır",
                user_message=f"Mətn ən azı {MIN_BODY_LENGTH} simvol olmalıdır.",
            )

        created = self._repository.create(
            tenant_id,
            version_label=label,
            title_az=title,
            body_az=body,
            created_by_id=actor.id,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="WHATS_NEW_PUBLISHED",
            entity_type="whats_new_entries",
            entity_id=None,
            after_state={
                "version_label": created.version_label,
                "title_az": created.title_az,
            },
        )
        return created

    def deactivate(self, *, tenant_id: TenantId, actor: Employee, entry_id: str) -> None:
        """Soft-delete — köhnə qeyd dəyişiklik tarixçəsinin HİSSƏSİDİR."""
        self._require(actor, PUBLISH_WHATS_NEW_FLAG)
        if not self._repository.deactivate(tenant_id, entry_id):
            raise WhatsNewError(
                "Versiya qeydi tapılmadı",
                user_message="Bu qeyd mövcud deyil və ya artıq söndürülüb.",
                context={"entry_id": entry_id},
            )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="WHATS_NEW_DEACTIVATED",
            entity_type="whats_new_entries",
            entity_id=None,
            after_state={"entry_id": entry_id, "is_active": False},
        )

    # ------------------------------- oxu ------------------------------------- #

    def list_entries(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        include_inactive: bool = True,
    ) -> list[WhatsNewEntry]:
        """Siyahı VIEW flag-ilə açılır — nəşr flag-i TƏLƏB OLUNMUR.

        Root nəşr edə bilmirsə də (praktikada edir) oxuya bilməlidir; əks halda
        «yazdığım qeyd haradadır?» sualı cavabsız qalardı.
        """
        self._require(actor, VIEW_WHATS_NEW_FLAG)
        return self._repository.list_entries(tenant_id, include_inactive=include_inactive)

    # ------------------------------- qapı ------------------------------------ #

    def _require(self, actor: Employee, flag: str) -> None:
        if not actor.has_permission(flag, now=self._clock.now()):
            raise WhatsNewPermissionError(
                f"«{flag}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id), "flag": flag},
            )


__all__ = [
    "MAX_VERSION_LABEL_LENGTH",
    "MIN_BODY_LENGTH",
    "MIN_TITLE_LENGTH",
    "PUBLISH_WHATS_NEW_FLAG",
    "VIEW_WHATS_NEW_FLAG",
    "WhatsNewEntry",
    "WhatsNewError",
    "WhatsNewPermissionError",
    "WhatsNewRepository",
    "WhatsNewUseCase",
]
