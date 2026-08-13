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
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Final

from src.application.root_limits import (
    fallback_decimal,
    fallback_int,
    limit_decimal,
    limit_int,
)
from src.domain.policies import SystemLimitKey
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.domain.interfaces.ports import SystemLimits
    from src.domain.value_objects.identifiers import TenantId

# --------------------------------------------------------------------------- #
# ROOT PARAMETRLƏRİNİN FALLBACK DƏYƏRLƏRİ (Faza 10.2)
# --------------------------------------------------------------------------- #
# Aşağıdakı beş sabitin HƏQİQİ MƏNBƏYİ `system_limits` cədvəlidir
# (`SystemLimitKey.SUPPORT_*` / `CRASH_*`, seed: migrations/034) — burada
# yalnız ROOT sətri oxunmadıqda işə düşən fallback saxlanılır və ədəd
# `DEFAULT_LIMITS`-dən gəlir, bu faylda YAZILMIR.
#
# NİYƏ DEVELOPER PANELİ ÇOX VAXT MƏHZ FALLBACK-I GÖRÜR: panel kirayəçi
# kontekstindən KƏNARDA işləyir (`--developer-mode`, `service_role`, bütün
# tenant-ların sətirləri) və `system_limits` per-tenant cədvəldir — yəni orada
# oxunacaq "bir" tenant yoxdur. Eyni vəziyyət `DEVELOPER_DIRECTORY_STALE_DAYS`
# açarındadır (migrations/032). Dəyər buna baxmayaraq ROOT parametridir: bu
# oxu-modeli kirayəçi kontekstində də çağırıla bilir (`ConsoleThresholds.
# from_limits`) və SLA hədəfi kommersiya öhdəliyidir — müqavilə dəyişəndə
# kod buraxılışı gözlənilməməlidir.

#: İlk cavab üçün hədəf (bölmə 8) — aşılarsa müraciət ekranda nişanlanır.
FIRST_RESPONSE_SLA_HOURS: Final[int] = fallback_int(SystemLimitKey.SUPPORT_FIRST_RESPONSE_SLA_HOURS)
#: Tam həll üçün hədəf.
RESOLUTION_SLA_HOURS: Final[int] = fallback_int(SystemLimitKey.SUPPORT_RESOLUTION_SLA_HOURS)
#: Hədəfin son neçə hissəsi "risk altında" zolağıdır (0.75 → son 25%).
SLA_AT_RISK_RATIO: Final[Decimal] = fallback_decimal(SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO)
#: Çökmə "kütləvi" sayılırsa (bu qədər fərqli quraşdırmada təkrarlanıb).
WIDESPREAD_INSTALLATION_THRESHOLD: Final[int] = fallback_int(
    SystemLimitKey.CRASH_WIDESPREAD_INSTALLATION_THRESHOLD
)
#: Çökmə panelinin "ən çox təkrarlanan N qrup" siyahısının uzunluğu.
CRASH_DASHBOARD_TOP_LIMIT: Final[int] = fallback_int(SystemLimitKey.CRASH_DASHBOARD_TOP_LIMIT)


@dataclass(frozen=True)
class ConsoleThresholds:
    """Panelin beş ROOT parametri — bir yerdə, bir dəfə oxunur.

    BEŞ AYRI ARQUMENT ƏVƏZİNƏ BİR OBYEKT: `SupportInbox.from_records` və
    `CrashDashboard.from_records` eyni mənbədən qidalanır və hər yeni parametr
    əks halda hər iki imzaya ayrıca əlavə olunardı — imzalar bir gün ayrılar,
    inbox yeni həddi görər, panel görməzdi.

    Defoltlar `DEFAULT_LIMITS`-dən gəlir, yəni portsuz qurulan obyekt
    köçürmədən ƏVVƏLKİ davranışı HƏRFƏN təkrarlayır.
    """

    first_response_sla_hours: int = FIRST_RESPONSE_SLA_HOURS
    resolution_sla_hours: int = RESOLUTION_SLA_HOURS
    at_risk_ratio: Decimal = SLA_AT_RISK_RATIO
    widespread_installations: int = WIDESPREAD_INSTALLATION_THRESHOLD
    dashboard_top_limit: int = CRASH_DASHBOARD_TOP_LIMIT

    @classmethod
    def from_limits(cls, limits: SystemLimits | None, tenant_id: TenantId) -> ConsoleThresholds:
        """`system_limits`-dən oxuyur; port yoxdursa defoltlar qalır.

        HƏR ÇAĞIRIŞDA YENİDƏN OXUNUR (keş yoxdur): Root dəyəri dəyişdirən kimi
        növbəti panel yenilənməsi yeni hədəfi göstərməlidir, əks halda "niyə
        tətbiq olunmur?" sualının cavabı yalnız prosesin yenidən başladılması
        olardı.
        """
        return cls(
            first_response_sla_hours=limit_int(
                limits, tenant_id, SystemLimitKey.SUPPORT_FIRST_RESPONSE_SLA_HOURS
            ),
            resolution_sla_hours=limit_int(
                limits, tenant_id, SystemLimitKey.SUPPORT_RESOLUTION_SLA_HOURS
            ),
            at_risk_ratio=limit_decimal(
                limits, tenant_id, SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO
            ),
            widespread_installations=limit_int(
                limits, tenant_id, SystemLimitKey.CRASH_WIDESPREAD_INSTALLATION_THRESHOLD
            ),
            dashboard_top_limit=limit_int(
                limits, tenant_id, SystemLimitKey.CRASH_DASHBOARD_TOP_LIMIT
            ),
        )


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
    *,
    opened_at: datetime,
    satisfied_at: datetime | None,
    now: datetime,
    target_hours: int,
    at_risk_ratio: Decimal = SLA_AT_RISK_RATIO,
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
    # "Risk altında" zolağı — defolt hədəfin son 25%-i (ROOT parametri).
    warning_point = opened_at + timedelta(hours=float(Decimal(target_hours) * at_risk_ratio))
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
    #: Qrupun qurulduğu andakı ROOT həddi. SƏTRƏ YAZILIR, qlobal sabitdən
    #: OXUNMUR: panel açıq ikən Root həddi dəyişsə, artıq göstərilən sətirlərin
    #: nişanı sükutla sıçrayardı və istifadəçi eyni siyahıda iki fərqli qaydaya
    #: görə rənglənmiş sətirlər görərdi.
    widespread_threshold: int = WIDESPREAD_INSTALLATION_THRESHOLD

    @property
    def is_widespread(self) -> bool:
        """Bir neçə quraşdırmada təkrarlanırmı.

        Tək quraşdırmadakı çökmə çox vaxt lokal problemdir (sürücü, antivirus);
        bir neçə quraşdırmada təkrarlanan isə KOD problemidir. Bu fərq
        prioritetləşdirmənin əsasıdır.
        """
        return self.affected_installations >= self.widespread_threshold

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


def group_crashes(
    records: Iterable[CrashRecord],
    *,
    thresholds: ConsoleThresholds | None = None,
) -> list[CrashGroup]:
    """Çökmələri `fingerprint` üzrə qruplaşdırır və TEZLİYƏ görə sıralayır.

    Sıralama açarı iki mərtəbəlidir: əvvəlcə təsirlənmiş quraşdırma sayı,
    sonra ümumi təkrar sayı. Yalnız təkrar sayına baxsaq, bir mağazada 500
    dəfə çökən lokal problem 20 mağazada 3 dəfə çökən kod xətasını üstələyərdi.
    """
    applied = thresholds or ConsoleThresholds()
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
            widespread_threshold=applied.widespread_installations,
        )
        for fingerprint, items in buckets.items()
    ]
    groups.sort(key=lambda g: (g.affected_installations, g.occurrences, g.last_seen), reverse=True)
    return groups


@dataclass
class CrashDashboard:
    """Panelin yekun görünüşü."""

    groups: list[CrashGroup] = field(default_factory=list)
    #: Panelin qurulduğu andakı ROOT parametrləri — `top()` defoltu buradan
    #: oxunur (bax `CrashGroup.widespread_threshold` eyni əsaslandırma).
    thresholds: ConsoleThresholds = field(default_factory=ConsoleThresholds)

    @property
    def total_crashes(self) -> int:
        return sum(group.occurrences for group in self.groups)

    @property
    def widespread(self) -> list[CrashGroup]:
        """Dərhal baxılmalı qruplar — siyahının başında göstərilir."""
        return [group for group in self.groups if group.is_widespread]

    def top(self, limit: int | None = None) -> list[CrashGroup]:
        """İlk N qrup. `None` → ROOT parametri (`CRASH_DASHBOARD_TOP_LIMIT`).

        AÇIQ ARQUMENT ÜSTÜNDÜR: konsol rejimi öz sütun sayına görə fərqli
        uzunluq istəyə bilər (`developer_panel/console.py`) və o seçim ROOT
        parametri ilə mübahisə etməməlidir.
        """
        return self.groups[: self.thresholds.dashboard_top_limit if limit is None else limit]

    @classmethod
    def from_records(
        cls,
        records: Iterable[CrashRecord],
        *,
        thresholds: ConsoleThresholds | None = None,
    ) -> CrashDashboard:
        applied = thresholds or ConsoleThresholds()
        return cls(groups=group_crashes(records, thresholds=applied), thresholds=applied)


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
        thresholds: ConsoleThresholds | None = None,
        response_sla_hours: int | None = None,
        resolution_sla_hours: int | None = None,
    ) -> SupportInbox:
        """SLA hədəfləri: açıq arqument > `thresholds` > `DEFAULT_LIMITS`.

        Açıq arqumentlər SAXLANILIB (əvvəl defolt dəyərləri var idi), çünki
        testlər və hesabat skriptləri bir hədəfi süni şəkildə dəyişib
        sərhəd davranışını yoxlaya bilməlidir — ROOT sətrini dəyişdirmədən.
        """
        applied = thresholds or ConsoleThresholds()
        response_target = (
            applied.first_response_sla_hours if response_sla_hours is None else response_sla_hours
        )
        resolution_target = (
            applied.resolution_sla_hours if resolution_sla_hours is None else resolution_sla_hours
        )
        views = [
            TicketView(
                record=record,
                response_sla=_sla_state(
                    opened_at=record.created_at,
                    satisfied_at=record.first_response_at,
                    now=now,
                    target_hours=response_target,
                    at_risk_ratio=applied.at_risk_ratio,
                ),
                resolution_sla=_sla_state(
                    opened_at=record.created_at,
                    satisfied_at=record.closed_at,
                    now=now,
                    target_hours=resolution_target,
                    at_risk_ratio=applied.at_risk_ratio,
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
    "CRASH_DASHBOARD_TOP_LIMIT",
    "FIRST_RESPONSE_SLA_HOURS",
    "RESOLUTION_SLA_HOURS",
    "SLA_AT_RISK_RATIO",
    "WIDESPREAD_INSTALLATION_THRESHOLD",
    "ConsoleThresholds",
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
