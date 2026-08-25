"""Kampaniya dövr-ləri — `v2backlog.md` Faza 6.4.

    "Promosyon-Dövrü Heyət-Fərqindəliyi: istəyə-bağlı «kampaniya tarixi»
     qeydi (Root/CEO daxil edir), bu tarixlərdə ... tarixi-nümunə-təklifinə
     əlavə çəki."

`campaign_periods` cədvəli Faza 1-in konsolidasiya dəstində yaranmışdı
(migrations/089), lakin istehsal EDƏN heç bir yol yox idi — cədvəl öz
başlığındakı vədi («istehlak olunur») yerinə yetirə bilməzdən əvvəl kiminsə
onu DOLDURMASI lazımdır. Bu modul həmin yazı yoludur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA DEYİL
──────────────────────────────────────────────────────────────────────────────
Hər əməliyyat TƏK aqreqata (bir `campaign_periods` sətrinə) toxunur; audit
yazısı ilə birlikdə eyni tranzaksiyadadır. Uğursuzluqda rollback tam
bərpadır — kompensasiya addımı yoxdur (`morning_check_in.py` meyarı).

──────────────────────────────────────────────────────────────────────────────
TARİX YOXLAMASI NİYƏ İKİ YERDƏDİR
──────────────────────────────────────────────────────────────────────────────
`end_date >= start_date` DB-də CHECK-dir (`chk_campaign_period_dates`,
migrations/089) və burada da yoxlanılır — CLAUDE.md §5-in «hər qayda iki
yerdə» prinsipinin adi tətbiqi: ekranı yan keçən skript DB CHECK-ə düşür,
GUI isə səbəbi ANLAŞILIR formada görür.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Final, Protocol

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock
    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Spesifikasiyanın açıq sözü: «Root/CEO daxil edir». Flag migrations/102-də.
MANAGE_CAMPAIGNS_FLAG: Final = "can_manage_campaign_periods"

#: Adın minimum uzunluğu — DB `CHECK (char_length(trim(name)) >= 2)` güzgüsü.
MIN_CAMPAIGN_NAME_LENGTH: Final = 2


class CampaignPeriodError(KompasOSError):
    """Kampaniya dövrü əməliyyatı icra edilə bilmədi."""

    user_message = "Kampaniya dövrü yazıla bilmədi."


class CampaignPermissionError(CampaignPeriodError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class CampaignPeriod:
    """Bir kampaniya tarix-aralığının oxu-modeli.

    Tətbiq qatının strukturudur — `ports.py`-da DEYİL (CLAUDE.md bölmə 3:
    port yalnız domen tipləri qaytarır). Tarixlər domen tipli deyil, çünki
    bu sətir planlama GİRİŞİdir, zaman-həssas domen qaydası deyil.
    """

    period_id: str
    name: str
    start_date: date
    end_date: date
    is_active: bool


class CampaignPeriodRepository(Protocol):
    """Yalnız bu use case-in istifadə etdiyi oxu/yazı səthi."""

    def list_periods(
        self, tenant_id: TenantId, *, include_inactive: bool
    ) -> list[CampaignPeriod]: ...

    def create(
        self,
        tenant_id: TenantId,
        *,
        name: str,
        start_date: date,
        end_date: date,
        created_by_id: object,
    ) -> CampaignPeriod: ...

    def deactivate(self, tenant_id: TenantId, period_id: str) -> bool: ...


class CampaignPeriodsUseCase:
    """Root/CEO kampaniya aralıqlarını daxil edir, siyahısını görür, söndürür."""

    def __init__(
        self,
        *,
        repository: CampaignPeriodRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock

    def create_period(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        name: str,
        start_date: date,
        end_date: date,
    ) -> CampaignPeriod:
        self._require(actor)
        cleaned = name.strip()
        if len(cleaned) < MIN_CAMPAIGN_NAME_LENGTH:
            raise CampaignPeriodError(
                "Kampaniya adı çox qısadır",
                user_message=f"Ad ən azı {MIN_CAMPAIGN_NAME_LENGTH} simvol olmalıdır.",
            )
        if end_date < start_date:
            raise CampaignPeriodError(
                "Bitmə tarixi başlanğıcdan əvvəldir",
                user_message="Bitmə tarixi başlanğıc tarixindən əvvəl ola bilməz.",
                context={"start": start_date.isoformat(), "end": end_date.isoformat()},
            )
        created = self._repository.create(
            tenant_id,
            name=cleaned,
            start_date=start_date,
            end_date=end_date,
            created_by_id=actor.id,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="CAMPAIGN_PERIOD_CREATED",
            entity_type="campaign_periods",
            entity_id=None,
            after_state={
                "name": created.name,
                "start_date": created.start_date.isoformat(),
                "end_date": created.end_date.isoformat(),
            },
        )
        return created

    def periods(self, *, tenant_id: TenantId, actor: Employee) -> list[CampaignPeriod]:
        """Siyahı EYNİ flag ilə açılır — kampaniya planı həssas HR məlumatıdır."""
        self._require(actor)
        return self._repository.list_periods(tenant_id, include_inactive=True)

    def deactivate_period(self, *, tenant_id: TenantId, actor: Employee, period_id: str) -> None:
        """Soft-delete — köhnə kampaniya keçmiş nümunənin HİSSƏSİDİR (089)."""
        self._require(actor)
        if not self._repository.deactivate(tenant_id, period_id):
            raise CampaignPeriodError(
                "Kampaniya dövrü tapılmadı",
                user_message="Bu kampaniya dövrü mövcud deyil.",
                context={"period_id": period_id},
            )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="CAMPAIGN_PERIOD_DEACTIVATED",
            entity_type="campaign_periods",
            entity_id=None,
            after_state={"period_id": period_id, "is_active": False},
        )

    def _require(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_CAMPAIGNS_FLAG, now=self._clock.now()):
            raise CampaignPermissionError(
                "Kampaniya dövrlərini idarə etmək üçün səlahiyyət yoxdur",
                context={"actor_id": str(actor.id)},
            )


__all__ = [
    "MANAGE_CAMPAIGNS_FLAG",
    "MIN_CAMPAIGN_NAME_LENGTH",
    "CampaignPeriod",
    "CampaignPeriodError",
    "CampaignPeriodRepository",
    "CampaignPeriodsUseCase",
    "CampaignPermissionError",
]
