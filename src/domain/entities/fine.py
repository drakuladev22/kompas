"""Cərimə aqreqatı (spesifikasiya bölmə 4, 6).

İKİ MƏNBƏ:
    AUTO_DELAY    — 3-STEP axınından avtomatik (gecikmə düsturu).
    MANUAL_CAMERA — Kamera Operatorunun müşahidəsi (foto sübutu MƏCBURİ).

DƏYİŞMƏZLİK QAYDASI (bölmə 4): "orijinal qeyd heç vaxt silinmir (yalnız
«REVERSED» statusu əlavə olunur)".

EXPORT KİLİDİ (bölmə 6, HÜQUQİ RİSK): cərimə Premiya&Cərimə hesabatına YALNIZ
(a) 72-saatlıq etiraz pəncərəsi bağlandıqdan SONRA, VƏ (b) statusu `REVERSED`
olmadıqda düşür. Bu qayda olmadan uğurlu etirazdan sonra da işçinin
premiyasından səhvən pul kəsilə bilər.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import FineIssuedEvent, FineReversedEvent
from src.domain.value_objects.identifiers import (
    AppealId,
    EmployeeId,
    FineId,
    FineTypeId,
    LeaveRequestId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import require_aware

DEFAULT_APPEAL_WINDOW_HOURS = 72
MIN_REVERSAL_REASON_LENGTH = 10


class FineSource(str, Enum):
    AUTO_DELAY = "AUTO_DELAY"
    MANUAL_CAMERA = "MANUAL_CAMERA"


class FineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"
    REDUCED = "REDUCED"


class Fine(AggregateRoot):
    """Cərimə qeydi."""

    def __init__(
        self,
        *,
        fine_id: FineId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        source: FineSource,
        amount: Money,
        issued_at: datetime,
        appeal_window_hours: int = DEFAULT_APPEAL_WINDOW_HOURS,
        fine_type_id: FineTypeId | None = None,
        leave_request_id: LeaveRequestId | None = None,
        issued_by: EmployeeId | None = None,
        photo_evidence_url: str | None = None,
    ) -> None:
        super().__init__()
        require_aware(issued_at, field="issued_at")
        amount.require_non_negative(field="cərimə məbləği")

        # Mənbəyə görə məcburi sahələr (DB CHECK-ləri ilə eyni).
        if source is FineSource.MANUAL_CAMERA:
            if fine_type_id is None:
                raise DomainRuleError(
                    "Manual cərimə üçün Cərimə Növü seçilməlidir — operator "
                    "sərbəst məbləğ təyin edə bilməz (anti-fraud, bölmə 4)"
                )
            if not photo_evidence_url:
                raise DomainRuleError(
                    "Manual cərimə üçün foto sübutu MƏCBURİDİR (bölmə 4)",
                    user_message="Cərimə üçün foto şəkil sübutu əlavə edilməlidir.",
                )
            if issued_by is None:
                raise DomainRuleError("Manual cərimə üçün operator ID məcburidir")
        elif leave_request_id is None:
            raise DomainRuleError("AUTO_DELAY cəriməsi bir icazə sorğusuna bağlanmalıdır")

        self.id = fine_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.source = source
        self.amount = amount
        self.original_amount = amount
        self.issued_at = issued_at
        self.fine_type_id = fine_type_id
        self.leave_request_id = leave_request_id
        self.issued_by = issued_by
        self.photo_evidence_url = photo_evidence_url

        self.status = FineStatus.ACTIVE
        self.appeal_window_closes_at = issued_at + timedelta(hours=appeal_window_hours)
        self.reversed_by: EmployeeId | None = None
        self.reversed_at: datetime | None = None
        self.reversal_reason: str | None = None
        self.exported_period: str | None = None

        self.record_event(
            FineIssuedEvent(
                fine_id=fine_id,
                employee_id=employee_id,
                store_id=store_id,
                source=source.value,
                amount=amount.amount,
                issued_by=issued_by,
                fine_type_id=fine_type_id,
                tenant_id=tenant_id,
                actor_id=issued_by,
            )
        )

    # ------------------------------- etiraz --------------------------------- #

    def is_appeal_window_open(self, *, now: datetime) -> bool:
        require_aware(now, field="now")
        return now < self.appeal_window_closes_at

    def reverse(
        self,
        *,
        decided_by: EmployeeId,
        decided_at: datetime,
        reason: str,
        appeal_id: AppealId | None = None,
        new_amount: Money | None = None,
    ) -> None:
        """Etirazın nəticəsi: cərimə ləğv və ya azaldılır.

        Orijinal qeyd SİLİNMİR — `original_amount` saxlanılır və yalnız status
        dəyişir (bölmə 4).
        """
        require_aware(decided_at, field="decided_at")
        if self.status is not FineStatus.ACTIVE:
            raise DomainRuleError(
                f"Yalnız aktiv cərimə ləğv edilə bilər, cari status: {self.status.value}"
            )
        cleaned = reason.strip()
        if len(cleaned) < MIN_REVERSAL_REASON_LENGTH:
            raise DomainRuleError(
                f"Ləğv səbəbi minimum {MIN_REVERSAL_REASON_LENGTH} simvol olmalıdır"
            )

        if new_amount is not None and new_amount.is_positive:
            new_amount.require_non_negative(field="yeni məbləğ")
            if new_amount >= self.original_amount:
                raise DomainRuleError(
                    "Azaldılmış məbləğ orijinaldan kiçik olmalıdır",
                    context={
                        "original": str(self.original_amount),
                        "new": str(new_amount),
                    },
                )
            self.amount = new_amount
            self.status = FineStatus.REDUCED
        else:
            self.amount = Money.zero()
            self.status = FineStatus.REVERSED

        self.reversed_by = decided_by
        self.reversed_at = decided_at
        self.reversal_reason = cleaned

        self.record_event(
            FineReversedEvent(
                fine_id=self.id,
                appeal_id=appeal_id,
                decided_by=decided_by,
                new_amount=self.amount.amount,
                tenant_id=self.tenant_id,
                actor_id=decided_by,
            )
        )

    # ------------------------------- export --------------------------------- #

    def is_exportable(self, *, now: datetime) -> bool:
        """Premiya&Cərimə hesabatına düşə bilərmi (bölmə 6, LOCK MEXANİZMİ)."""
        require_aware(now, field="now")
        if self.status is FineStatus.REVERSED:
            return False
        if self.exported_period is not None:
            return False
        return not self.is_appeal_window_open(now=now)

    def mark_exported(self, *, period: str, now: datetime) -> None:
        """Export edilmiş kimi işarələyir (`YYYY-MM`) — təkrar tutulmanın qarşısını alır."""
        if not self.is_exportable(now=now):
            raise DomainRuleError(
                "Bu cərimə hələ export edilə bilməz — etiraz pəncərəsi açıqdır, "
                "cərimə ləğv edilib və ya artıq export olunub",
                context={
                    "status": self.status.value,
                    "window_closes_at": self.appeal_window_closes_at.isoformat(),
                    "already_exported": self.exported_period,
                },
            )
        self.exported_period = period

    def __repr__(self) -> str:
        return (
            f"Fine(id={self.id}, source={self.source.value}, "
            f"amount={self.amount}, status={self.status.value})"
        )


__all__ = [
    "DEFAULT_APPEAL_WINDOW_HOURS",
    "Fine",
    "FineSource",
    "FineStatus",
]
