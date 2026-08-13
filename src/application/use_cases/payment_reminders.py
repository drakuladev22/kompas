"""Ödəniş xatırlatmaları — Master Lisenziya Paneli (Faza 6, bənd 4).

Bölmə 8 lisenziya statusunu üç vəziyyətə bölür: `Aktiv` / `Ödəniş Gözlənilir` /
`Deaktiv`. Xatırlatma məhz ortadakı vəziyyəti idarə edir — müştəriyə ödənişin
yaxınlaşdığını (və ya gecikdiyini) vaxtında bildirmək.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SABİT CƏDVƏL, "HƏR GÜN" DEYİL
──────────────────────────────────────────────────────────────────────────────
Hər gün göndərilən xatırlatma bir həftədə "spam" kimi qəbul edilir və müştəri
onu süzgəcə salır — nəticədə ƏSL kritik bildirişi də görməz. Ona görə
xatırlatma yalnız SEÇİLMİŞ günlərdə gedir:

    T-7, T-3, T-1  → bitməzdən əvvəl (planlaşdırma üçün vaxt qalır)
    T+1, T+7       → bitdikdən sonra (deaktivləşdirmədən əvvəl son şans)

──────────────────────────────────────────────────────────────────────────────
İDEMPOTENTLİK NİYƏ KRİTİKDİR
──────────────────────────────────────────────────────────────────────────────
Planlayıcı gündə bir dəfə işləyir, lakin proses yenidən başladıla, əl ilə
təkrar çağırıla və ya iki instansiyada eyni anda işə düşə bilər. Ona görə
"bu tenant üçün bu mərhələ göndərilibmi?" sualı `SentReminderLog` ilə
cavablanır — eyni mərhələ İKİNCİ DƏFƏ göndərilmir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Final, Protocol

from src.application.root_limits import fallback_int_tuple, limit_int_tuple
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.notifications import NotificationCategory
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from src.domain.interfaces.ports import SystemLimits
    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Xatırlatma günləri: mənfi = bitmədən ƏVVƏL, müsbət = SONRA (modul başlığı).
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS`, seed: migrations/034).
#: Cədvəl TƏK SƏTİRDƏ saxlanılır ("-7,-3,-1,1,7"), beş ayrı açarda YOX: beş
#: mərhələ BİRGƏ bir xatırlatma cədvəli təşkil edir və ayrı açarlarda Root
#: onları yanlış sıraya (məs. T+7-ni T-7-dən əvvələ) yaza bilərdi —
#: `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` ilə eyni əsaslandırma.
REMINDER_OFFSETS: Final[tuple[int, ...]] = fallback_int_tuple(
    SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS
)


def reminder_offsets(limits: SystemLimits | None, tenant_id: TenantId) -> tuple[int, ...]:
    """Xatırlatma cədvəlini ROOT-dan oxuyur (port yoxdursa fallback).

    NİYƏ AYRICA FUNKSİYA: Master Lisenziya Paneli kirayəçi kontekstindən
    KƏNARDA işləyir (bütün müştərilərin sətirlərini bir siyahıda görür) və
    `system_limits` per-tenant cədvəldir — orada oxunacaq "bir" tenant yoxdur.
    Ona görə cədvəl `PaymentReminderUseCase`-ə HAZIR şəkildə ötürülür və bu
    funksiya onu kirayəçi kontekstində hesablayan yeganə yerdir (eyni vəziyyət
    `developer_console.ConsoleThresholds.from_limits`-dədir).
    """
    return limit_int_tuple(limits, tenant_id, SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS)


@dataclass(frozen=True)
class TenantBilling:
    """Bir müştərinin ödəniş vəziyyəti — paneldəki sətrin məlumat mənbəyi."""

    tenant_id: str
    tenant_name: str
    contact_email: str
    expires_on: date | None

    def days_until_expiry(self, *, today: date) -> int | None:
        """Müsbət = qalan gün, mənfi = keçmiş gün, `None` = müddətsiz."""
        if self.expires_on is None:
            return None
        return (self.expires_on - today).days


@dataclass(frozen=True)
class ReminderMessage:
    """Göndəriləcək bir xatırlatma."""

    tenant_id: str
    tenant_name: str
    contact_email: str
    offset_days: int
    title_az: str
    body_az: str

    @property
    def is_overdue(self) -> bool:
        """Müddət ARTIQ bitibmi — bu, kritik bildirişdir."""
        return self.offset_days > 0

    @property
    def stage_key(self) -> str:
        """İdempotentlik açarı — `tenant + mərhələ`."""
        return f"{self.tenant_id}:{self.offset_days:+d}"


class SentReminderLog(Protocol):
    """Göndərilmiş mərhələlərin qeydi (idempotentlik üçün)."""

    def was_sent(self, stage_key: str) -> bool: ...

    def mark_sent(self, stage_key: str, *, sent_at: datetime) -> None: ...


class ReminderSender(Protocol):
    """E-poçt/bildiriş göndərən — `Notifier` və ya SMTP adapteri."""

    def send(self, message: ReminderMessage) -> None: ...


@dataclass
class ReminderRun:
    """Bir planlayıcı dövrünün nəticəsi."""

    sent: list[ReminderMessage] = field(default_factory=list)
    skipped_already_sent: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def sent_count(self) -> int:
        return len(self.sent)


def build_message(
    billing: TenantBilling, *, today: date, offsets: Sequence[int] | None = None
) -> ReminderMessage | None:
    """Bugün bu müştəriyə xatırlatma düşürmü.

    `None` → bugün onun üçün mərhələ yoxdur. Müddətsiz lisenziya (`None`)
    heç vaxt xatırlatma almır — orada xatırlanacaq tarix yoxdur.

    Args:
        offsets: ROOT-dan gələn cədvəl; verilməzsə `REMINDER_OFFSETS` fallback-ı.
    """
    days_left = billing.days_until_expiry(today=today)
    if days_left is None:
        return None

    # `days_left` müsbətdirsə bitməyə var; offset isə mənfi işarə ilə yazılıb.
    offset = -days_left
    if offset not in (REMINDER_OFFSETS if offsets is None else tuple(offsets)):
        return None

    if offset < 0:
        title = "Lisenziya müddəti yaxınlaşır"
        body = (
            f"«{billing.tenant_name}» lisenziyasının müddəti {abs(offset)} gün sonra "
            f"({billing.expires_on:%d.%m.%Y}) bitir. Fasiləsiz iş üçün ödənişi "
            f"vaxtında tamamlayın."
        )
    else:
        title = "Lisenziya müddəti bitib"
        body = (
            f"«{billing.tenant_name}» lisenziyasının müddəti {offset} gün əvvəl "
            f"({billing.expires_on:%d.%m.%Y}) bitib. Ödəniş edilməzsə giriş "
            f"məhdudlaşdırılacaq."
        )

    return ReminderMessage(
        tenant_id=billing.tenant_id,
        tenant_name=billing.tenant_name,
        contact_email=billing.contact_email,
        offset_days=offset,
        title_az=title,
        body_az=body,
    )


class PaymentReminderUseCase:
    """Gündəlik xatırlatma dövrü — idempotent və qismən uğursuzluğa dözümlü."""

    def __init__(
        self,
        *,
        sender: ReminderSender,
        log: SentReminderLog,
        offsets: Sequence[int] | None = None,
    ) -> None:
        """
        Args:
            offsets: ROOT xatırlatma cədvəli (`reminder_offsets()` ilə oxunur).
                `None` → `REMINDER_OFFSETS` fallback-ı, yəni davranış
                köçürmədən ƏVVƏLKİ ilə HƏRFƏN eynidir.
        """
        self._sender = sender
        self._log = log
        self._offsets = REMINDER_OFFSETS if offsets is None else tuple(offsets)

    def run(self, tenants: Iterable[TenantBilling], *, now: datetime) -> ReminderRun:
        """Bugünə düşən bütün xatırlatmaları göndərir.

        BİR müştəriyə göndərmə uğursuz olarsa qalanlar DAVAM EDİR: bir səhv
        e-poçt ünvanı bütün digər müştəriləri xəbərsiz qoymamalıdır. Uğursuz
        olan mərhələ `mark_sent` ALMIR — növbəti dövrdə yenidən cəhd edilir.
        """
        today = now.date()
        run = ReminderRun()

        for billing in tenants:
            message = build_message(billing, today=today, offsets=self._offsets)
            if message is None:
                continue

            if self._log.was_sent(message.stage_key):
                run.skipped_already_sent += 1
                continue

            try:
                self._sender.send(message)
            except Exception as exc:
                run.failed.append(message.tenant_id)
                _log.error(
                    "PAYMENT_REMINDER_FAILED",
                    extra={"tenant_id": message.tenant_id, "error": str(exc)},
                )
                continue

            self._log.mark_sent(message.stage_key, sent_at=now)
            run.sent.append(message)

        _audit_log.info(
            "PAYMENT_REMINDERS_RUN",
            extra={
                "sent": run.sent_count,
                "skipped": run.skipped_already_sent,
                "failed": len(run.failed),
            },
        )
        return run


class NotifierReminderSender:
    """`Notifier` portunu `ReminderSender`-ə uyğunlaşdırır.

    Xatırlatma HƏMİŞƏ kritikdir (`is_critical=True`): `PAYMENT_REMINDER`
    bölmə 7-də e-poçt fallback-ı məcburi olan kateqoriyalardandır — in-app
    bildiriş kifayət etmir, çünki lisenziya bitəndə istifadəçi tətbiqə
    ümumiyyətlə girə bilməyəcək.
    """

    def __init__(self, notifier: object) -> None:
        self._notifier = notifier

    def send(self, message: ReminderMessage) -> None:
        self._notifier.notify(  # type: ignore[attr-defined]
            tenant_id=message.tenant_id,
            recipient_id=None,
            category=NotificationCategory.PAYMENT_REMINDER.value,
            title_az=message.title_az,
            body_az=message.body_az,
            is_critical=True,
        )


__all__ = [
    "REMINDER_OFFSETS",
    "NotifierReminderSender",
    "PaymentReminderUseCase",
    "ReminderMessage",
    "ReminderRun",
    "ReminderSender",
    "SentReminderLog",
    "TenantBilling",
    "build_message",
    "reminder_offsets",
]
