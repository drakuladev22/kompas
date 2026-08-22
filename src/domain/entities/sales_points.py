"""Satış xalı aqreqatları (spesifikasiya bölmə 6).

──────────────────────────────────────────────────────────────────────────────
XAL SƏTRİ NİYƏ CƏRİMƏ İLƏ EYNİ MODELDƏDİR
──────────────────────────────────────────────────────────────────────────────
Bölmə 6: "Cərimələrdəki 72-saatlıq etiraz prinsipi ilə EYNİ məntiqlə ... Qərar
audit-lənir, xal korreksiya oluna bilər, amma orijinal əməliyyat qeydi silinmir
(yalnız «REVERSED»/«CORRECTED» statusu əlavə olunur) — cərimə etirazı ilə eyni
audit-təhlükəsizlik modeli."

Bu, təsadüfi oxşarlıq deyil, QƏSDƏN eyniliyidir: hər iki halda söhbət işçinin
pulundan gedir (cərimə tutulur, xal isə mükafata çevrilir) və hər ikisində
səhvin "sükutla düzəldilməsi" etibar problemidir. Ona görə burada da fiziki
`UPDATE points = X` yoxdur — `correct()` orijinal dəyəri saxlayır.

──────────────────────────────────────────────────────────────────────────────
LOW_CONFIDENCE_MATCH NİYƏ DƏRHAL XAL QAZANDIRIR
──────────────────────────────────────────────────────────────────────────────
`MatchConfidence.awards_points` (bölmə 6) `UNASSIGNED`-dən başqa hamısına xal
verir. Səbəb: nəzərdən keçirmə növbəsi insan sürəti ilə işləyir və "əvvəlcə
təsdiqlə, sonra xal ver" modeli işçinin xalını günlərlə gecikdirərdi. Səhv
çıxarsa, bu modul onu geri qaytarır — və 72 saatlıq etiraz pəncərəsi işçiyə
səhvi ÖZÜNÜN göstərmək imkanı verir.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.gamification import (
    POINTS_DISPUTE_WINDOW_HOURS,
    InvalidPointsError,
    PointsAppealStatus,
    PointsEntryStatus,
    PointsPeriod,
    RedemptionStatus,
    RewardItem,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PointsEntryId,
    RedemptionId,
    RewardId,
    SalesTransactionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: Etiraz/rədd səbəbi üçün minimum uzunluq — cərimə modeli ilə eyni.
MIN_REASON_LENGTH: Final[int] = 10


class PointsEntry(AggregateRoot):
    """`points_ledger` sətri — bir satışdan qazanılan xal."""

    def __init__(
        self,
        *,
        entry_id: PointsEntryId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        points: int,
        awarded_at: datetime,
        confidence: MatchConfidence = MatchConfidence.EXACT_MATCH,
        sales_transaction_id: SalesTransactionId | None = None,
        gross_amount: Money | None = None,
        dispute_window_hours: int = POINTS_DISPUTE_WINDOW_HOURS,
    ) -> None:
        super().__init__()
        require_aware(awarded_at, field="awarded_at")

        if points <= 0:
            raise InvalidPointsError(
                "Xal sətri müsbət olmalıdır — düzəliş `correct()` ilə edilir, "
                "sıfır/mənfi sətir yaradılmır",
                context={"points": points},
            )
        if not confidence.awards_points:
            raise DomainRuleError(
                f"«{confidence.value}» uyğunlaşması xal qazandırmır — sətir yaradılmamalıdır",
                context={"confidence": confidence.value},
            )

        self.id = entry_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.confidence = confidence
        self.sales_transaction_id = sales_transaction_id
        self.gross_amount = gross_amount
        self.awarded_at = awarded_at
        self.dispute_window_hours = dispute_window_hours

        self.status = PointsEntryStatus.ACTIVE
        #: İlk verilmiş dəyər — DƏYİŞMİR (audit üçün).
        self.original_points = points
        #: Cari (korreksiyadan sonrakı) dəyər.
        self.points = points
        #: Etiraz AYRICA `points_appeals` sətridir; burada onun XÜLASƏSİ
        #: saxlanılır ki, aqreqat «açıq etiraz varmı?» sualına özü cavab
        #: verə bilsin və ikinci etiraz bloklansın.
        self.appeal_status: PointsAppealStatus | None = None
        self.dispute_reason: str | None = None
        self.disputed_at: datetime | None = None
        self.decided_by: EmployeeId | None = None
        self.decided_at: datetime | None = None
        self.decision_reason: str | None = None

    # -------------------------------- pəncərə -------------------------------- #

    @property
    def dispute_window_closes_at(self) -> datetime:
        """Etiraz pəncərəsinin bağlanma anı — xal verildiyi andan sayılır.

        Cərimədən FƏRQ: cərimə pəncərəsi `publish()` anından başlayır, çünki
        cərimə əvvəlcə gizli icmalda dayanır. Xal isə dərhal görünür, ona görə
        sayğac `awarded_at`-dan başlayır.
        """
        return self.awarded_at + timedelta(hours=self.dispute_window_hours)

    def is_dispute_window_open(self, *, now: datetime) -> bool:
        require_aware(now, field="now")
        return now < self.dispute_window_closes_at

    @property
    def effective_points(self) -> int:
        """Balansa daxil olan xal — `REVERSED` sıfır sayılır."""
        return self.points if self.status.counts_toward_balance else 0

    @property
    def has_open_dispute(self) -> bool:
        """Qərar gözləyən etiraz varmı."""
        return self.appeal_status is PointsAppealStatus.PENDING

    def belongs_to(self, period: PointsPeriod) -> bool:
        """Sətir verilmiş 6 aylıq dövrə düşürmü (sıfırlanma məntiqi)."""
        return period.contains(self.awarded_at)

    # -------------------------------- etiraz --------------------------------- #

    def open_dispute(self, *, reason: str, disputed_at: datetime) -> None:
        """İşçi 72 saat ərzində etiraz göndərir (bölmə 6).

        Ledger STATUSU DƏYİŞMİR — xal qərara qədər qüvvədə qalır (cərimədəki
        günahsızlıq prezumpsiyasının xal tərəfindəki qarşılığı). Dəyişən
        yalnız etiraz sətridir.
        """
        require_aware(disputed_at, field="disputed_at")
        if self.status is not PointsEntryStatus.ACTIVE:
            raise DomainRuleError(
                f"Yalnız qüvvədə olan xal sətrinə etiraz edilə bilər, "
                f"cari status: {self.status.value}",
                context={"entry_id": str(self.id), "status": self.status.value},
            )
        if self.has_open_dispute:
            raise DomainRuleError(
                "Bu qeyd üzrə etiraz artıq göndərilib",
                user_message="Bu qeyd üçün etirazınız artıq qeydə alınıb.",
                context={"entry_id": str(self.id)},
            )
        if not self.is_dispute_window_open(now=disputed_at):
            raise DomainRuleError(
                f"{self.dispute_window_hours} saatlıq etiraz pəncərəsi bağlanıb",
                user_message="Bu qeyd üçün etiraz müddəti bitib.",
                context={"closes_at": self.dispute_window_closes_at.isoformat()},
            )

        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_REASON_LENGTH:
            raise DomainRuleError(
                f"Etiraz səbəbi minimum {MIN_REASON_LENGTH} simvol olmalıdır",
                user_message="Etirazın səbəbini daha ətraflı yazın.",
            )

        self.appeal_status = PointsAppealStatus.PENDING
        self.dispute_reason = cleaned
        self.disputed_at = disputed_at

    def correct(
        self, *, new_points: int, decided_by: EmployeeId, decided_at: datetime, reason: str
    ) -> None:
        """Etiraz qəbul olunur, xal sayı DÜZƏLDİLİR — sətir qalır.

        `can_manage_sales_points` sahibi bunu etiraz OLMADAN da edə bilər
        (bölmə 3: "xalları əl ilə düzəltmək"), ona görə `AWARDED` statusu da
        qəbul edilir.
        """
        require_aware(decided_at, field="decided_at")
        self._require_decidable()

        if new_points < 0:
            raise InvalidPointsError("Düzəldilmiş xal mənfi ola bilməz")
        if new_points == 0:
            raise DomainRuleError(
                "Sıfır xal `correct()` ilə deyil, `reverse()` ilə qeyd olunur — "
                "tam ləğv ayrıca statusla izlənilməlidir"
            )

        cleaned = self._clean_reason(reason)
        self.status = PointsEntryStatus.CORRECTED
        if self.has_open_dispute:
            self.appeal_status = PointsAppealStatus.APPROVED
        self.points = new_points
        self.decided_by = decided_by
        self.decided_at = decided_at
        self.decision_reason = cleaned

    def reverse(self, *, decided_by: EmployeeId, decided_at: datetime, reason: str) -> None:
        """Xal TAM ləğv edilir — sətir silinmir, `REVERSED` olur."""
        require_aware(decided_at, field="decided_at")
        self._require_decidable()

        cleaned = self._clean_reason(reason)
        self.status = PointsEntryStatus.REVERSED
        if self.has_open_dispute:
            self.appeal_status = PointsAppealStatus.APPROVED
        self.decided_by = decided_by
        self.decided_at = decided_at
        self.decision_reason = cleaned
        # `points` DƏYİŞMİR — nə qədər xal ləğv olunduğu auditdə görünməlidir.

    def reject_dispute(self, *, decided_by: EmployeeId, decided_at: datetime, reason: str) -> None:
        """Etiraz rədd edilir — xal sətri OLDUĞU KİMİ qalır."""
        require_aware(decided_at, field="decided_at")
        if not self.has_open_dispute:
            raise DomainRuleError(
                "Bu sətir üzrə qərar gözləyən etiraz yoxdur",
                context={"entry_id": str(self.id)},
            )
        cleaned = self._clean_reason(reason)
        self.appeal_status = PointsAppealStatus.REJECTED
        self.decided_by = decided_by
        self.decided_at = decided_at
        self.decision_reason = cleaned

    def _require_decidable(self) -> None:
        if self.status in (PointsEntryStatus.REVERSED, PointsEntryStatus.CORRECTED):
            raise DomainRuleError(
                f"Bu sətir üzrə qərar artıq verilib: {self.status.value}",
                context={"entry_id": str(self.id)},
            )

    @staticmethod
    def _clean_reason(reason: str) -> str:
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_REASON_LENGTH:
            raise DomainRuleError(
                f"Qərar səbəbi minimum {MIN_REASON_LENGTH} simvol olmalıdır",
                user_message="Qərarın səbəbini daha ətraflı yazın.",
            )
        return cleaned

    def __repr__(self) -> str:
        return f"PointsEntry(id={self.id}, points={self.points}, status={self.status.value})"


class RewardRedemption(AggregateRoot):
    """Mükafat mübadiləsi — işçi xalını mükafata dəyişir (bölmə 6)."""

    def __init__(
        self,
        *,
        redemption_id: RedemptionId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        reward_id: RewardId,
        reward: RewardItem,
        available_points: int,
        requested_at: datetime,
    ) -> None:
        super().__init__()
        require_aware(requested_at, field="requested_at")
        # Balans yoxlaması MÜBADİLƏ ANINDA edilir — sonradan xal `REVERSED`
        # olsa belə, artıq verilmiş mükafat geri alınmır (bu, ayrı biznes
        # qərarıdır və sükutla burada həll edilmir).
        reward.require_affordable(available_points)

        self.id = redemption_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.reward_id = reward_id
        #: Mükafatın MÜBADİLƏ ANINDAKI vəziyyəti — kataloq sonradan dəyişsə də,
        #: işçidən nə qədər xal tutulduğu dəyişmir.
        self.reward_name = reward.name
        self.cost_points = reward.cost_points
        self.requested_at = requested_at

        self.status = RedemptionStatus.REQUESTED
        self.decided_by: EmployeeId | None = None
        self.decided_at: datetime | None = None
        self.decision_reason: str | None = None
        self.fulfilled_at: datetime | None = None

    @property
    def holds_points(self) -> bool:
        """Xallar bloklanmış vəziyyətdədirmi (`PointsBalance.held` mənbəyi)."""
        return self.status.holds_points

    def approve(self, *, decided_by: EmployeeId, decided_at: datetime) -> None:
        require_aware(decided_at, field="decided_at")
        self._require_pending()
        self.status = RedemptionStatus.APPROVED
        self.decided_by = decided_by
        self.decided_at = decided_at

    def reject(self, *, decided_by: EmployeeId, decided_at: datetime, reason: str) -> None:
        """Rədd — bloklanmış xallar işçiyə QAYTARILIR."""
        require_aware(decided_at, field="decided_at")
        self._require_pending()
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_REASON_LENGTH:
            raise DomainRuleError(
                f"Rədd səbəbi minimum {MIN_REASON_LENGTH} simvol olmalıdır",
                user_message="Rəddin səbəbini daha ətraflı yazın.",
            )
        self.status = RedemptionStatus.REJECTED
        self.decided_by = decided_by
        self.decided_at = decided_at
        self.decision_reason = cleaned

    def fulfil(self, *, fulfilled_at: datetime) -> None:
        """Mükafat işçiyə təhvil verildi — terminal vəziyyət."""
        require_aware(fulfilled_at, field="fulfilled_at")
        if self.status is not RedemptionStatus.APPROVED:
            raise DomainRuleError(
                f"Yalnız təsdiqlənmiş mübadilə təhvil verilə bilər, "
                f"cari status: {self.status.value}"
            )
        self.status = RedemptionStatus.FULFILLED
        self.fulfilled_at = fulfilled_at

    def _require_pending(self) -> None:
        if self.status is not RedemptionStatus.REQUESTED:
            raise DomainRuleError(
                f"Bu mübadilə üzrə qərar artıq verilib: {self.status.value}",
                context={"redemption_id": str(self.id)},
            )

    def __repr__(self) -> str:
        return (
            f"RewardRedemption(id={self.id}, reward={self.reward_name!r}, "
            f"status={self.status.value})"
        )


__all__ = ["MIN_REASON_LENGTH", "PointsEntry", "RewardRedemption"]
