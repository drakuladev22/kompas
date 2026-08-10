"""Drive kvota nəzarəti — Faza 3.9.

Tələb: *"Arxa planda dövri bir job aktiv Drive connection-un kvotasını
yoxlayır. 90%-ə çatanda Root/CEO-ya xəbərdarlıq göndərilir... Kvota 100%-ə
çatarsa: status avtomatik QUOTA_EXCEEDED olur."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ MÖVCUD BİLDİRİŞ SİSTEMİ İSTİFADƏ OLUNUR
──────────────────────────────────────────────────────────────────────────────
Tələb bunu açıq deyir və səbəbi var: `Notifier` portu onsuz da in-app +
kritik hallarda e-poçt fallback-ini idarə edir (bölmə 7). Drive üçün ayrıca
kanal qurulsaydı, admin bildirişləri iki fərqli yerdə axtarmalı olardı.

──────────────────────────────────────────────────────────────────────────────
TƏKRAR XƏBƏRDARLIQ QORUNMASI
──────────────────────────────────────────────────────────────────────────────
Job gündəlik işləyir. Sadə "90%-i keçib?" yoxlaması hər gün eyni bildirişi
göndərərdi və admin onları oxumağı dayandırardı (alarm yorğunluğu).
`quota_warning_sent_at` sahəsi ilə xəbərdarlıq eyni hədd üçün bir dəfə
göndərilir; kvota aşağı düşüb yenidən qalxarsa yenidən göndərilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from src.domain.value_objects.storage import QuotaStatus
from src.infrastructure.storage.connections import DriveConnection, DriveConnectionStatus
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.interfaces.ports import Notifier
    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.storage.connections import (
        DriveConnectionRepository,
        DriveProviderFactory,
    )

_log = get_logger(__name__)

#: Bu həddi keçəndə xəbərdarlıq göndərilir.
WARNING_THRESHOLD: Final[float] = 0.90
#: Xəbərdarlıq bu müddətdən tez təkrarlanmır.
WARNING_COOLDOWN: Final[timedelta] = timedelta(days=7)


@dataclass
class QuotaCheckResult:
    checked: bool = False
    quota: QuotaStatus | None = None
    warning_sent: bool = False
    marked_exceeded: bool = False
    error: str | None = None


class DriveQuotaMonitor:
    """Aktiv bağlantının kvotasını yoxlayır və lazım olduqda xəbərdarlıq edir."""

    def __init__(
        self,
        *,
        repository: DriveConnectionRepository,
        provider_factory: DriveProviderFactory,
        notifier: Notifier,
        tenant_id: TenantId,
        warning_threshold: float = WARNING_THRESHOLD,
        cooldown: timedelta = WARNING_COOLDOWN,
    ) -> None:
        self._repository = repository
        self._factory = provider_factory
        self._notifier = notifier
        self._tenant_id = tenant_id
        self._threshold = warning_threshold
        self._cooldown = cooldown

    def check(self, *, now: datetime | None = None) -> QuotaCheckResult:
        moment = now or datetime.now(UTC)
        result = QuotaCheckResult()

        connection = self._repository.get_active()
        if connection is None:
            # Bağlantı yoxdursa yoxlanacaq bir şey də yoxdur — bu, XƏTA
            # deyil: tenant hələ Drive qoşmamış ola bilər.
            _log.debug("DRIVE_QUOTA_NO_ACTIVE_CONNECTION")
            return result

        try:
            quota = self._factory.for_connection(connection.id).quota()
        except Exception as exc:  # şəbəkə/token nasazlığı monitoru öldürməməlidir
            result.error = str(exc)
            self._repository.record_error(connection.id, f"Kvota yoxlaması: {exc}")
            _log.error("DRIVE_QUOTA_CHECK_FAILED", extra={"error": str(exc)})
            return result

        result.checked = True
        result.quota = quota
        exceeded = quota.is_full
        self._repository.update_quota(connection.id, quota, now=moment, mark_exceeded=exceeded)
        result.marked_exceeded = exceeded

        if exceeded:
            self._notify(
                title="Google Drive dolub",
                body=(
                    f"'{connection.google_account_email}' hesabında yer qalmayıb "
                    f"({quota.percent}%). Yeni cərimə şəkilləri lokal növbədə "
                    f"gözləyir və yeni hesab qoşulan kimi avtomatik yüklənəcək. "
                    f"Cərimə yaratmaq BLOKLANMAYIB."
                ),
                critical=True,
            )
            self._repository.mark_quota_warning_sent(connection.id, now=moment)
            result.warning_sent = True
            _log.error(
                "DRIVE_QUOTA_EXCEEDED",
                extra={
                    "connection_id": str(connection.id),
                    "used_bytes": quota.used_bytes,
                    "total_bytes": quota.total_bytes,
                },
            )
            return result

        if quota.usage_ratio >= self._threshold and self._should_warn(connection, moment):
            self._notify(
                title="Google Drive dolmaq üzrədir",
                body=(
                    f"'{connection.google_account_email}' hesabı {quota.percent}% "
                    f"doludur. Dolmadan əvvəl yeni Drive hesabı qoşun — "
                    f"Ayarlar → Drive Bağlantısı."
                ),
                critical=True,
            )
            self._repository.mark_quota_warning_sent(connection.id, now=moment)
            result.warning_sent = True
            _log.warning(
                "DRIVE_QUOTA_WARNING",
                extra={"connection_id": str(connection.id), "percent": quota.percent},
            )

        return result

    def _should_warn(self, connection: DriveConnection, now: datetime) -> bool:
        sent_at = connection.quota_warning_sent_at
        if sent_at is None:
            return True
        return bool(now - sent_at >= self._cooldown)

    def _notify(self, *, title: str, body: str, critical: bool) -> None:
        # `recipient_id=None` → bildiriş tenant səviyyəsindədir; marşrutlaşdırma
        # `can_manage_drive_connection` flag-inə görə Root/CEO-ya edilir.
        self._notifier.notify(
            tenant_id=self._tenant_id,
            recipient_id=None,
            category="DRIVE_QUOTA",
            title_az=title,
            body_az=body,
            is_critical=critical,
        )


def status_label(status: DriveConnectionStatus) -> str:
    """UI üçün Azərbaycanca etiket (bölmə 9: yeganə interfeys dili)."""
    return {
        DriveConnectionStatus.ACTIVE: "Aktiv",
        DriveConnectionStatus.ARCHIVED: "Arxivlənib",
        DriveConnectionStatus.QUOTA_EXCEEDED: "Yer qalmayıb",
    }[status]


__all__ = [
    "WARNING_COOLDOWN",
    "WARNING_THRESHOLD",
    "DriveQuotaMonitor",
    "QuotaCheckResult",
    "status_label",
]
