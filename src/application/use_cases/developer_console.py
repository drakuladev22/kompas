"""Developer Panel oxu-modelləri — çökmə paneli və dəstək inbox-u (bölmə 8).

Faza 6, bənd 4-ün son iki alt-bəndi:

    * "anonymized Crash/Error Reporting dashboard grouped by frequency"
    * "centralized Support Ticket inbox (per-tenant threads, SLA tracking)"

──────────────────────────────────────────────────────────────────────────────
NİYƏ "OXU-MODEL", USE CASE DEYİL
──────────────────────────────────────────────────────────────────────────────
Burada heç bir vəziyyət DƏYİŞMİR — yalnız artıq yazılmış sətirlər sıralanır,
qruplaşdırılır və SLA hesablanır. Yazma tərəfi (`report_crash`,
`support_messages`) Faza 3-də mövcuddur və TƏKRAR YAZILMIR (spesifikasiya:
"backend məntiqi təkrar yazılmır").

──────────────────────────────────────────────────────────────────────────────
"ANONİMLƏŞDİRİLMİŞ" NƏ DEMƏKDİR
──────────────────────────────────────────────────────────────────────────────
`crash_reports` cədvəlində `tenant_id` YOXDUR — yalnız `anonymous_tenant_ref`
(hash) var. Bu qat həmin qərarı POZMUR: qruplaşdırma `fingerprint` üzrədir,
hansı müştərinin çökdüyü isə YALNIZ "neçə fərqli quraşdırma" sayı kimi
göstərilir. Beləliklə hazırlayıcı problemin miqyasını görür, müştərinin
şəxsiyyətini yox.

──────────────────────────────────────────────────────────────────────────────
SLA NİYƏ İKİ FƏRQLİ SAYĞACDIR
──────────────────────────────────────────────────────────────────────────────
"Cavab müddəti" (ilk cavaba qədər) və "həll müddəti" (bağlanana qədər) fərqli
öhdəliklərdir: sürətli cavab müştərini sakitləşdirir, sürətli həll problemi
bitirir. Tək sayğac olsaydı, saatlarla susub sonra bir dəqiqəyə bağlanan
müraciət "yaxşı xidmət" kimi görünərdi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Final

from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Iterable

#: İlk cavab üçün hədəf (bölmə 8) — aşılarsa müraciət ekranda nişanlanır.
FIRST_RESPONSE_SLA_HOURS: Final[int] = 24
#: Tam həll üçün hədəf.
RESOLUTION_SLA_HOURS: Final[int] = 72
#: Çökmə "kütləvi" sayılırsa (bu qədər fərqli quraşdırmada təkrarlanıb).
WIDESPREAD_INSTALLATION_THRESHOLD: Final[int] = 3


class DeveloperConsoleError(KompasOSError):
    """Konsol oxu-modeli yararsız məlumat aldı."""

    user_message = "Panel məlumatı oxuna bilmədi."


class SlaState(str, Enum):
    """Bir müraciətin SLA vəziyyəti."""

    ON_TRACK = "ON_TRACK"
    #: Hədəfin son 25%-inə girib — hələ pozulmayıb.
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    #: Bağlanıb və hədəf pozulmayıb.
    MET = "MET"

    @property
    def label_az(self) -> str:
        return {
            SlaState.ON_TRACK: "Vaxtında",
            SlaState.AT_RISK: "Risk altında",
            SlaState.BREACHED: "SLA pozulub",
            SlaState.MET: "Yerinə yetirildi",
        }[self]

    @property
    def needs_attention(self) -> bool:
        return self in (SlaState.AT_RISK, SlaState.BREACHED)


def _sla_state(
    *, opened_at: datetime, satisfied_at: datetime | None, now: datetime, target_hours: int
) -> SlaState:
    """Bir SLA sayğacının vəziyyəti.

    Bağlanmış müraciət üçün "vaxtında bitdimi" sualı FAKTİKİ vaxta görə
    cavablanır — sonradan `now` irəlilədikcə keçmiş nəticə dəyişməməlidir.
    """
    deadline = opened_at + timedelta(hours=target_hours)
    if satisfied_at is not None:
        return SlaState.MET if satisfied_at <= deadline else SlaState.BREACHED
    if now > deadline:
        return SlaState.BREACHED
    # Son 25% — "risk altında" zolağı.
    warning_point = opened_at + timedelta(hours=target_hours * 0.75)
    return SlaState.AT_RISK if now >= warning_point else SlaState.ON_TRACK


# --------------------------------------------------------------------------- #
# Çökmə paneli
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CrashRecord:
    """Bir `crash_reports` sətri — panelin girişi."""

    fingerprint: str
    exception_type: str
    app_version: str
    anonymous_tenant_ref: str
    occurred_at: datetime
    os_version: str = ""


@dataclass(frozen=True)
class CrashGroup:
    """Tezliyə görə qruplaşdırılmış çökmə (bölmə 8)."""

    fingerprint: str
    exception_type: str
    occurrences: int
    affected_installations: int
    first_seen: datetime
    last_seen: datetime
    app_versions: tuple[str, ...]

    @property
    def is_widespread(self) -> bool:
        """Bir neçə quraşdırmada təkrarlanırmı.

        Tək quraşdırmadakı çökmə çox vaxt lokal problemdir (sürücü, antivirus);
        bir neçə quraşdırmada təkrarlanan isə KOD problemidir. Bu fərq
        prioritetləşdirmənin əsasıdır.
        """
        return self.affected_installations >= WIDESPREAD_INSTALLATION_THRESHOLD

    @property
    def is_regression(self) -> bool:
        """Yalnız SON versiyada görünürmü — yəni yeni buraxılış gətirib.

        Bir versiyada məhdud qalan çökmə buraxılışın özünə bağlıdır; bir neçə
        versiyada davam edən isə köhnə, hələ həll olunmamış problemdir.
        """
        return len(self.app_versions) == 1

    @property
    def summary_az(self) -> str:
        return (
            f"{self.exception_type} — {self.occurrences} dəfə, "
            f"{self.affected_installations} quraşdırmada"
        )


def group_crashes(records: Iterable[CrashRecord]) -> list[CrashGroup]:
    """Çökmələri `fingerprint` üzrə qruplaşdırır və TEZLİYƏ görə sıralayır.

    Sıralama açarı iki mərtəbəlidir: əvvəlcə təsirlənmiş quraşdırma sayı,
    sonra ümumi təkrar sayı. Yalnız təkrar sayına baxsaq, bir mağazada 500
    dəfə çökən lokal problem 20 mağazada 3 dəfə çökən kod xətasını üstələyərdi.
    """
    buckets: dict[str, list[CrashRecord]] = {}
    for record in records:
        buckets.setdefault(record.fingerprint, []).append(record)

    groups = [
        CrashGroup(
            fingerprint=fingerprint,
            exception_type=items[0].exception_type,
            occurrences=len(items),
            affected_installations=len({item.anonymous_tenant_ref for item in items}),
            first_seen=min(item.occurred_at for item in items),
            last_seen=max(item.occurred_at for item in items),
            app_versions=tuple(sorted({item.app_version for item in items})),
        )
        for fingerprint, items in buckets.items()
    ]
    groups.sort(key=lambda g: (g.affected_installations, g.occurrences, g.last_seen), reverse=True)
    return groups


@dataclass
class CrashDashboard:
    """Panelin yekun görünüşü."""

    groups: list[CrashGroup] = field(default_factory=list)

    @property
    def total_crashes(self) -> int:
        return sum(group.occurrences for group in self.groups)

    @property
    def widespread(self) -> list[CrashGroup]:
        """Dərhal baxılmalı qruplar — siyahının başında göstərilir."""
        return [group for group in self.groups if group.is_widespread]

    def top(self, limit: int = 10) -> list[CrashGroup]:
        return self.groups[:limit]

    @classmethod
    def from_records(cls, records: Iterable[CrashRecord]) -> CrashDashboard:
        return cls(groups=group_crashes(records))


# --------------------------------------------------------------------------- #
# Dəstək inbox-u
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TicketRecord:
    """Bir `support_tickets` sətri + sayğacları."""

    ticket_id: str
    tenant_name: str
    subject: str
    status: str
    created_at: datetime
    first_response_at: datetime | None = None
    closed_at: datetime | None = None
    message_count: int = 0
    last_message_at: datetime | None = None


@dataclass(frozen=True)
class TicketView:
    """İnbox sətri — SLA vəziyyəti hesablanmış."""

    record: TicketRecord
    response_sla: SlaState
    resolution_sla: SlaState
    #: Hesablama anı — açıq müraciətin yaşı buna qədər ölçülür.
    evaluated_at: datetime

    @property
    def needs_attention(self) -> bool:
        return self.response_sla.needs_attention or self.resolution_sla.needs_attention

    @property
    def is_awaiting_first_reply(self) -> bool:
        return self.record.first_response_at is None and self.record.closed_at is None

    @property
    def age_hours(self) -> float:
        """Müraciətin yaşı.

        AÇIQ müraciətdə sayğac İŞLƏYİR — ölçü `evaluated_at`-a qədərdir.
        Son mesaja qədər ölçsəydik, heç cavab almamış müraciət (məhz diqqət
        tələb edən hal) inboxda «0 saat» görünərdi və sütun ən çox lazım
        olduğu yerdə mənasız olardı.

        BAĞLANMIŞ müraciətdə isə ölçü bağlanma anına qədərdir — sonradan
        vaxt keçdikcə keçmiş nəticə şişməməlidir.
        """
        end = self.record.closed_at or self.evaluated_at
        return max(0.0, (end - self.record.created_at).total_seconds() / 3600)


@dataclass
class SupportInbox:
    """Mərkəzi dəstək inbox-u — tenant üzrə mövzular (bölmə 8)."""

    tickets: list[TicketView] = field(default_factory=list)

    @classmethod
    def from_records(
        cls,
        records: Iterable[TicketRecord],
        *,
        now: datetime,
        response_sla_hours: int = FIRST_RESPONSE_SLA_HOURS,
        resolution_sla_hours: int = RESOLUTION_SLA_HOURS,
    ) -> SupportInbox:
        views = [
            TicketView(
                record=record,
                response_sla=_sla_state(
                    opened_at=record.created_at,
                    satisfied_at=record.first_response_at,
                    now=now,
                    target_hours=response_sla_hours,
                ),
                resolution_sla=_sla_state(
                    opened_at=record.created_at,
                    satisfied_at=record.closed_at,
                    now=now,
                    target_hours=resolution_sla_hours,
                ),
                evaluated_at=now,
            )
            for record in records
        ]
        # Diqqət tələb edənlər ƏVVƏLDƏ, sonra köhnəlik sırası ilə. Adi tarix
        # sıralaması SLA-sı pozulmuş müraciəti siyahının ortasında gizlədərdi.
        views.sort(key=lambda view: (not view.needs_attention, view.record.created_at))
        return cls(tickets=views)

    @property
    def attention_count(self) -> int:
        return sum(1 for view in self.tickets if view.needs_attention)

    @property
    def awaiting_first_reply(self) -> list[TicketView]:
        return [view for view in self.tickets if view.is_awaiting_first_reply]

    def for_tenant(self, tenant_name: str) -> list[TicketView]:
        """Bir müştərinin bütün mövzuları — "per-tenant threads"."""
        return [view for view in self.tickets if view.record.tenant_name == tenant_name]

    def tenants(self) -> list[str]:
        """İnbox-da mövcud müştərilər — süzgəc siyahısı üçün."""
        return sorted({view.record.tenant_name for view in self.tickets})


__all__ = [
    "FIRST_RESPONSE_SLA_HOURS",
    "RESOLUTION_SLA_HOURS",
    "WIDESPREAD_INSTALLATION_THRESHOLD",
    "CrashDashboard",
    "CrashGroup",
    "CrashRecord",
    "DeveloperConsoleError",
    "SlaState",
    "SupportInbox",
    "TicketRecord",
    "TicketView",
    "group_crashes",
]
