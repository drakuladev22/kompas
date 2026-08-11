"""Cərimə aqreqatı (spesifikasiya bölmə 4, 6).

İKİ MƏNBƏ:
    AUTO_DELAY    — 3-STEP axınından avtomatik (gecikmə düsturu).
    MANUAL_CAMERA — Kamera Operatorunun müşahidəsi (foto sübutu MƏCBURİ).

DƏYİŞMƏZLİK QAYDASI (bölmə 4): "orijinal qeyd heç vaxt silinmir (yalnız
«REVERSED» statusu əlavə olunur)".

──────────────────────────────────────────────────────────────────────────────
İKİ MƏRHƏLƏLİ GÖRÜNMƏ (qərar dəyişikliyi — migration 003)
──────────────────────────────────────────────────────────────────────────────
Cərimə YARADILDIĞI AN işçiyə GÖRÜNMÜR:

    PENDING_REVIEW → (Aylıq İcmal, "Bütün Filiallara Göndər") → PUBLISHED
                   → (etiraz və ya idarə qərarı)              → REVERSED/REDUCED

`PENDING_REVIEW` mərhələsində yalnız cəriməni QEYDƏ ALAN kamera operatoru
onu öz fəaliyyət siyahısında görür — işçi, mağaza meneceri və HR görmür.

──────────────────────────────────────────────────────────────────────────────
72 SAAT `published_at`-DAN HESABLANIR — ƏN VACİB DETAL
──────────────────────────────────────────────────────────────────────────────
Cərimə həftələrlə icmalda qala bilər. Sayğac yaradılışdan başlasaydı, işçi
cəriməni GÖRMƏMİŞ onun etiraz müddəti bitə bilərdi — bu, həm ədalətsizlik,
həm hüquqi risk olardı. Ona görə pəncərə `publish()` anında açılır.

EXPORT KİLİDİ (bölmə 6, HÜQUQİ RİSK) — ÜÇ ŞƏRT: cərimə Premiya&Cərimə
hesabatına YALNIZ (a) statusu `PUBLISHED` olduqda, (b) etiraz pəncərəsi
`published_at`-dan hesablanaraq bağlandıqda, VƏ (c) əvvəllər export
olunmadıqda düşür. `PENDING_REVIEW` HEÇ VAXT export-a düşmür: işçi onu nə
görüb, nə də etiraz hüququ alıb.
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
    """DB-dəki `fine_status` enum-u ilə eynidir.

    Köhnə `ACTIVE` dəyəri ÇIXARILIB: yeni modeldə onun mənası `PUBLISHED`
    ilə üst-üstə düşürdü və iki sinonim status sorğularda "hansını
    yoxlamalıyam?" sualı yaradardı (migration 003 mövcud sətirləri
    `ACTIVE` → `PUBLISHED` çevirir).
    """

    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    REVERSED = "REVERSED"
    REDUCED = "REDUCED"


#: Premiya&Cərimə export-una düşə bilən statuslar (bölmə 6).
#: `REDUCED` daxildir — bax `Fine.is_exportable` izahı.
EXPORTABLE_STATUSES = frozenset({FineStatus.PUBLISHED, FineStatus.REDUCED})


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

        # Cərimə GÖRÜNMƏYƏN vəziyyətdə doğulur — `publish()` onu açır.
        self.status = FineStatus.PENDING_REVIEW
        self.appeal_window_hours = appeal_window_hours
        self.published_at: datetime | None = None
        self.reviewed_by: EmployeeId | None = None
        self.review_decision_reason: str | None = None
        #: Nəşrdən ƏVVƏL `None` — sayğac hələ başlamayıb.
        self.appeal_window_closes_at: datetime | None = None
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

    # ------------------------------- nəşr ----------------------------------- #

    @property
    def is_visible_to_employee(self) -> bool:
        """İşçi/mağaza meneceri/HR görünüşlərində göstərilə bilərmi.

        Kamera operatorunun ÖZ fəaliyyət siyahısı bu qaydadan İSTİSNADIR —
        orada cərimə statusundan asılı olmayaraq görünür (o, öz qeydidir).
        """
        return self.status is not FineStatus.PENDING_REVIEW

    def publish(self, *, reviewed_by: EmployeeId, published_at: datetime) -> None:
        """ "[Bütün Filiallara Göndər]" — cərimə işçiyə açılır.

        Etiraz pəncərəsi MƏHZ BURADA başlayır.
        """
        require_aware(published_at, field="published_at")
        if self.status is not FineStatus.PENDING_REVIEW:
            raise DomainRuleError(
                f"Yalnız icmal gözləyən cərimə nəşr edilə bilər, cari status: {self.status.value}",
                context={"fine_id": str(self.id), "status": self.status.value},
            )
        self.status = FineStatus.PUBLISHED
        self.published_at = published_at
        self.reviewed_by = reviewed_by
        self.appeal_window_closes_at = published_at + timedelta(hours=self.appeal_window_hours)

    def discard_in_review(
        self, *, reviewed_by: EmployeeId, reviewed_at: datetime, reason: str
    ) -> None:
        """İcmalda "Sil" seçimi — qeyd FİZİKİ SİLİNMİR, `REVERSED` olur.

        Bu, `reverse()`-dən fərqlidir: orada cərimə artıq işçiyə görünüb və
        etiraz nəticəsində ləğv olunur. Burada isə heç vaxt görünməyib.
        """
        require_aware(reviewed_at, field="reviewed_at")
        if self.status is not FineStatus.PENDING_REVIEW:
            raise DomainRuleError(
                f"Yalnız icmal gözləyən cərimə bu yolla ləğv edilə bilər, "
                f"cari status: {self.status.value}"
            )
        cleaned = reason.strip()
        if len(cleaned) < MIN_REVERSAL_REASON_LENGTH:
            raise DomainRuleError(
                f"Ləğv səbəbi minimum {MIN_REVERSAL_REASON_LENGTH} simvol olmalıdır"
            )
        self.status = FineStatus.REVERSED
        self.amount = Money.zero()
        self.reviewed_by = reviewed_by
        self.review_decision_reason = cleaned
        self.reversed_by = reviewed_by
        self.reversed_at = reviewed_at
        self.reversal_reason = cleaned

    # ------------------------------- etiraz --------------------------------- #

    def is_appeal_window_open(self, *, now: datetime) -> bool:
        """Nəşr olunmamış cərimənin pəncərəsi hələ AÇILMAYIB.

        `True` qaytarılır: "bağlanıb" demək export-a icazə vermək olardı.
        """
        require_aware(now, field="now")
        if self.appeal_window_closes_at is None:
            return True
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
        if self.status is not FineStatus.PUBLISHED:
            # Nəşr olunmamış cəriməyə etiraz ola bilməz — işçi onu görməyib.
            raise DomainRuleError(
                f"Yalnız nəşr olunmuş cərimə ləğv edilə bilər, cari status: {self.status.value}"
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
        """Premiya&Cərimə hesabatına düşə bilərmi (bölmə 6, LOCK MEXANİZMİ).

        Üç şərt: nəşr olunub + pəncərə bağlıdır + əvvəllər export olunmayıb.

        `REDUCED` DAXİLDİR: etiraz qismən qəbul olunubsa işçi AZALDILMIŞ
        məbləği yenə ödəyir — onu export-dan çıxarmaq cərimənin sükutla
        sıfırlanması demək olardı. Yalnız tam ləğv (`REVERSED`) kənardadır.
        """
        require_aware(now, field="now")
        if self.status not in EXPORTABLE_STATUSES:
            # PENDING_REVIEW — işçi hələ görməyib; REVERSED — tam ləğv olunub.
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
                    "published_at": self.published_at.isoformat() if self.published_at else None,
                    "window_closes_at": (
                        self.appeal_window_closes_at.isoformat()
                        if self.appeal_window_closes_at
                        else None
                    ),
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
    # Export filtri infrastruktur qatında da bu DƏSTDƏN qurulur — siyahını
    # SQL-də əl ilə təkrar yazmaq iki mənbə yaradardı (bax `repositories.py`).
    "EXPORTABLE_STATUSES",
    "Fine",
    "FineSource",
    "FineStatus",
]
