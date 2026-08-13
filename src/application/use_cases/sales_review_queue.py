"""«Təyin Olunmamış / Şübhəli Satışlar» növbəsi (bölmə 6, Faza 6.2) — Faza 6.

    "Fallback nəticəsində uyğunlaşan hər sətir «LOW_CONFIDENCE_MATCH» işarəsi
     ilə «Təyin Olunmamış / Şübhəli Uyğunlaşma» review queue-a düşür."

──────────────────────────────────────────────────────────────────────────────
NİYƏ XAL DƏRHAL VERİLİR, SONRA DÜZƏLDİLİR
──────────────────────────────────────────────────────────────────────────────
`domain/entities/sales_points.py` başlığındakı qərar: `LOW_CONFIDENCE_MATCH`
sətri xal QAZANDIRIR. Səbəb — əks halda satıcı öz xalını görmür və "sistem
işləmir" deyə şikayət edir; halbuki uyğunlaşma çox güman ki, DOĞRUDUR.

Bu modul həmin qərarın davamıdır: sətir səhv işçiyə düşübsə, `reassign()`
köhnə işçidən xalı geri alır (`REVERSED`) və yenisinə verir. Yəni növbə
"xal verilməmiş sətirlərin" siyahısı DEYİL, "təsdiqlənməmiş uyğunlaşmaların"
siyahısıdır.

──────────────────────────────────────────────────────────────────────────────
`can_manage_sales_points` NİYƏ EYNİ FLAG-dır
──────────────────────────────────────────────────────────────────────────────
Bölmə 3 həmin flag-i belə təsvir edir: "xalları əl ilə düzəltmək, mükafat
mübadiləsini təsdiqləmək". Şübhəli sətri əl ilə işçiyə bağlamaq məhz xal
düzəlişidir — ayrıca flag yaratmaq kataloqu şişirdər və eyni məsuliyyəti
iki yerə bölərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.application.root_limits import fallback_int, limit_int
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.erp import MatchConfidence
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock, SystemLimits
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        SalesTransactionId,
        StoreId,
        TenantId,
    )
    from src.domain.value_objects.money import Money

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

MANAGE_POINTS_FLAG = "can_manage_sales_points"

MIN_REASON_LENGTH = 5

#: Növbənin bir oxunuşda gətirdiyi sətir sayı.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE`, seed: migrations/034).
#: 21 filialın şübhəli uyğunlaşma növbəsi mövsümdən asılı olaraq böyüyür;
#: ekranın nə qədər sətir çəkəcəyi mağaza PC-sinin gücündən asılı qərardır.
DEFAULT_QUEUE_LIMIT = fallback_int(SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE)


class ReviewQueueError(KompasOSError):
    """Növbə əməliyyatı icra edilə bilmədi."""

    user_message = "Bu əməliyyat icra edilə bilmədi."


class QueueItemNotFoundError(ReviewQueueError):
    user_message = "Satış sətri tapılmadı."


@dataclass(frozen=True)
class ReviewQueueItem:
    """Növbədəki bir satış sətri — ekranın göstərdiyi forma."""

    transaction_id: SalesTransactionId
    server_name: str
    one_c_seller_id: str
    one_c_seller_name: str | None
    one_c_store_code: str
    one_c_document_id: str
    gross_amount: Money
    transaction_date: datetime
    confidence: MatchConfidence
    match_reason: str | None
    #: Sistemin təxmin etdiyi işçi — `UNASSIGNED` halında `None`.
    suggested_employee_id: EmployeeId | None = None
    suggested_employee_name: str = ""
    store_id: StoreId | None = None

    @property
    def is_unassigned(self) -> bool:
        return self.confidence is MatchConfidence.UNASSIGNED

    @property
    def badge_az(self) -> str:
        """Sətir nişanı — ekranda rəngli etiket."""
        if self.is_unassigned:
            return "Təyin olunmayıb"
        return "Şübhəli uyğunlaşma"


@runtime_checkable
class SalesReviewRepository(Protocol):
    """`sales_transactions` üzərində növbə əməliyyatları."""

    def list_queue(
        self,
        tenant_id: TenantId,
        *,
        server_id: object | None = None,
        limit: int = DEFAULT_QUEUE_LIMIT,
    ) -> list[ReviewQueueItem]: ...

    def get(self, transaction_id: SalesTransactionId) -> ReviewQueueItem | None: ...

    def queue_size(self, tenant_id: TenantId) -> int: ...

    def assign(
        self,
        transaction_id: SalesTransactionId,
        *,
        employee_id: EmployeeId,
        store_id: StoreId | None,
        matched_by: EmployeeId,
        matched_at: datetime,
    ) -> None:
        """Sətri işçiyə bağlayır və `confidence`-i `MANUAL_MATCH` edir."""
        ...

    def confirm(
        self,
        transaction_id: SalesTransactionId,
        *,
        matched_by: EmployeeId,
        matched_at: datetime,
    ) -> None:
        """Mövcud təxmini təsdiqləyir — işçi dəyişmir, yalnız `MANUAL_MATCH` olur."""
        ...


@runtime_checkable
class PointsAdjuster(Protocol):
    """Xal tərəfindəki düzəliş — `sales_points.py` use case-i bunu ödəyir."""

    def transfer_for_transaction(
        self,
        *,
        tenant_id: TenantId,
        transaction_id: SalesTransactionId,
        from_employee_id: EmployeeId | None,
        to_employee_id: EmployeeId,
        store_id: StoreId,
        gross_amount: Decimal,
        actor_id: EmployeeId,
        reason: str,
    ) -> None: ...


@dataclass
class QueueResolution:
    """Bir sətrin həlli — ekranın göstərdiyi nəticə."""

    item: ReviewQueueItem
    assigned_to: EmployeeId
    points_transferred: bool


class SalesReviewQueueUseCase:
    """«Şübhəli Satışlar» ekranının arxa tərəfi."""

    def __init__(
        self,
        *,
        repository: SalesReviewRepository,
        points: PointsAdjuster | None,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        # `limits` İSTƏYƏ BAĞLIDIR (`points` ilə eyni naxış): `None` halında
        # səhifə ölçüsü `DEFAULT_QUEUE_LIMIT` fallback-ıdır, yəni davranış
        # köçürmədən ƏVVƏLKİ ilə HƏRFƏN eynidir.
        self._limits = limits
        self._repository = repository
        # `None` ola bilər: xal modulu Feature Toggle ilə söndürülübsə növbə
        # yenə işləməlidir — satış uyğunlaşması xaldan ASILI DEYİL.
        self._points = points
        self._audit = audit
        self._clock = clock

    # -------------------------------- baxış ---------------------------------- #

    def queue(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        server_id: object | None = None,
        limit: int | None = None,
    ) -> list[ReviewQueueItem]:
        """Növbə siyahısı — server üzrə süzülə bilər (Faza 6.2: "per-server aware").

        `limit=None` → ROOT parametri (`SALES_REVIEW_QUEUE_PAGE_SIZE`). Açıq
        arqument onu ƏVƏZ EDİR: "daha 50 sətir göstər" düyməsi ekranın öz
        vəziyyətidir və Root parametri ilə mübahisə etməməlidir.
        """
        self._require_permission(actor)
        applied = (
            limit_int(self._limits, tenant_id, SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE)
            if limit is None
            else limit
        )
        return self._repository.list_queue(tenant_id, server_id=server_id, limit=applied)

    def queue_size(self, *, tenant_id: TenantId, actor: Employee) -> int:
        """Menyu nişanı üçün sayğac."""
        self._require_permission(actor)
        return self._repository.queue_size(tenant_id)

    # ------------------------------- həll et --------------------------------- #

    def reassign(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        transaction_id: SalesTransactionId,
        employee_id: EmployeeId,
        reason: str,
    ) -> QueueResolution:
        """Sətri BAŞQA işçiyə bağlayır və xalı köçürür."""
        self._require_permission(actor)
        cleaned = _clean_reason(reason)
        item = self._require_item(transaction_id)
        now = self._clock.now()

        self._repository.assign(
            transaction_id,
            employee_id=employee_id,
            store_id=item.store_id,
            matched_by=actor.id,
            matched_at=now,
        )

        transferred = False
        if (
            self._points is not None
            and item.store_id is not None
            and item.suggested_employee_id != employee_id
        ):
            self._points.transfer_for_transaction(
                tenant_id=tenant_id,
                transaction_id=transaction_id,
                from_employee_id=item.suggested_employee_id,
                to_employee_id=employee_id,
                store_id=item.store_id,
                gross_amount=item.gross_amount.amount,
                actor_id=actor.id,
                reason=cleaned,
            )
            transferred = True

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="SALES_MATCH_REASSIGNED",
            entity_type="sales_transactions",
            entity_id=transaction_id,
            before_state={
                "confidence": item.confidence.value,
                "employee_id": (
                    str(item.suggested_employee_id) if item.suggested_employee_id else None
                ),
            },
            after_state={
                "confidence": MatchConfidence.MANUAL_MATCH.value,
                "employee_id": str(employee_id),
                "points_transferred": transferred,
            },
            reason=cleaned,
        )
        return QueueResolution(item=item, assigned_to=employee_id, points_transferred=transferred)

    def confirm(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        transaction_id: SalesTransactionId,
    ) -> QueueResolution:
        """Sistemin təxminini təsdiqləyir — sətir növbədən çıxır, xal toxunulmur.

        Bu, ən çox istifadə olunacaq düymədir: `LOW_CONFIDENCE_MATCH` sətirlərin
        əksəriyyəti DOĞRUDUR (ad kiçik yazı fərqi, ikinci ad və s.), sadəcə
        avtomatik uyğunlaşma özünə əmin ola bilməyib.
        """
        self._require_permission(actor)
        item = self._require_item(transaction_id)
        if item.suggested_employee_id is None:
            raise ReviewQueueError(
                "Təyin olunmamış sətir təsdiqlənə bilməz — işçi seçilməlidir",
                user_message="Bu sətir üçün işçi seçin.",
                context={"transaction_id": str(transaction_id)},
            )

        self._repository.confirm(transaction_id, matched_by=actor.id, matched_at=self._clock.now())
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="SALES_MATCH_CONFIRMED",
            entity_type="sales_transactions",
            entity_id=transaction_id,
            before_state={"confidence": item.confidence.value},
            after_state={
                "confidence": MatchConfidence.MANUAL_MATCH.value,
                "employee_id": str(item.suggested_employee_id),
            },
        )
        return QueueResolution(
            item=item, assigned_to=item.suggested_employee_id, points_transferred=False
        )

    # ------------------------------- köməkçi --------------------------------- #

    def _require_item(self, transaction_id: SalesTransactionId) -> ReviewQueueItem:
        item = self._repository.get(transaction_id)
        if item is None:
            raise QueueItemNotFoundError(
                "Satış sətri tapılmadı",
                context={"transaction_id": str(transaction_id)},
            )
        return item

    def _require_permission(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_POINTS_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "SALES_QUEUE_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_POINTS_FLAG},
            )
            raise ReviewQueueError(
                f"«{MANAGE_POINTS_FLAG}» səlahiyyəti yoxdur",
                user_message="Satış uyğunlaşmalarını idarə etmək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )


def _clean_reason(raw: str) -> str:
    cleaned = " ".join(raw.split())
    if len(cleaned) < MIN_REASON_LENGTH:
        raise ReviewQueueError(
            f"Səbəb minimum {MIN_REASON_LENGTH} simvol olmalıdır",
            user_message="Dəyişikliyin səbəbini yazın.",
            context={"length": len(cleaned)},
        )
    return cleaned


__all__ = [
    "DEFAULT_QUEUE_LIMIT",
    "MANAGE_POINTS_FLAG",
    "PointsAdjuster",
    "QueueItemNotFoundError",
    "QueueResolution",
    "ReviewQueueError",
    "ReviewQueueItem",
    "SalesReviewQueueUseCase",
    "SalesReviewRepository",
]
