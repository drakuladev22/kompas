"""Aylıq Cərimə İcmalı və kütləvi nəşr — Faza 2.7 (qərar dəyişikliyi).

Axın:

    1. Cərimələr (AUTO_DELAY + MANUAL_CAMERA) `PENDING_REVIEW` doğulur —
       işçi, mağaza meneceri və HR onları GÖRMÜR.
    2. Ayın əvvəlində `can_publish_fines` sahibi 21 filialın həmin ay üçün
       nəşr gözləyən cərimələrini BİR cədvəldə görür.
    3. Hər sətrə "Saxla" (defolt) / "Sil" qərarı verilir.
    4. TƏK "[Bütün Filiallara Göndər]" düyməsi: saxlananlar `PUBLISHED`,
       silinənlər `REVERSED` olur və HƏMİN AN bütün filiallarda görünür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BİR TRANZAKSİYADA
──────────────────────────────────────────────────────────────────────────────
"Bir andan" tələbi texniki tələbdir, təsviri deyil: yarımçıq nəşr bəzi
filialların cəriməni görməsi, bəzilərinin görməməsi demək olardı. Ona görə
bütün qərarlar tək `commit()`-də tətbiq olunur — biri uğursuz olarsa HEÇ
BİRİ tətbiq olunmur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ "SİL" FİZİKİ SİLMƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Bölmə 4: "orijinal qeyd heç vaxt silinmir". Operatorun səhvən yazdığı cərimə
də auditin bir hissəsidir — kimin nə qeyd etdiyi və kimin onu ləğv etdiyi
sonradan sual olunanda cavab verilə bilməlidir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from src.domain.entities.fine import Fine, FineStatus
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock, Notifier
    from src.domain.value_objects.identifiers import FineId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Cərimələri filiallara açan icazə. Kamera operatoruna, mağaza menecerinə və
#: satıcıya HEÇ VAXT verilə bilməz — DB trigger-i də bunu bloklayır
#: (`is_anti_fraud` + `excludes_camera_role`, migration 003).
PUBLISH_FINES_FLAG = "can_publish_fines"

MIN_DISCARD_REASON_LENGTH = 10


class FineReviewError(KompasOSError):
    """İcmal/nəşr əməliyyatı qadağandır və ya yararsızdır."""

    user_message = "Bu əməliyyat icra edilə bilmədi."


class ReviewDecision(str, Enum):
    KEEP = "KEEP"
    DISCARD = "DISCARD"


@dataclass(frozen=True)
class FineDecision:
    """İcmal cədvəlinin bir sətri üzrə qərar."""

    fine_id: FineId
    decision: ReviewDecision = ReviewDecision.KEEP
    reason: str | None = None


@dataclass
class PublishResult:
    """Kütləvi nəşrin nəticəsi — audit və UI təsdiq mesajı üçün."""

    batch_id: UUID
    review_month: str
    published: list[FineId] = field(default_factory=list)
    discarded: list[FineId] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.published) + len(self.discarded)


class MonthlyFineReviewUseCase:
    """Aylıq icmal + kütləvi nəşr."""

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditTrail,
        notifier: Notifier,
    ) -> None:
        self._clock = clock
        self._audit = audit
        self._notifier = notifier

    # ------------------------------ görünmə ---------------------------------- #

    @staticmethod
    def visible_to_employee(fines: list[Fine]) -> list[Fine]:
        """İşçinin "Cərimələrim" görünüşü — nəşr olunmayanlar süzülür."""
        return [fine for fine in fines if fine.is_visible_to_employee]

    @staticmethod
    def recorded_by_operator(fines: list[Fine], operator_id: object) -> list[Fine]:
        """Kamera operatorunun ÖZ fəaliyyət siyahısı.

        İSTİSNA: burada status süzgəci YOXDUR — operator öz qeyd etdiyi
        cəriməni nəşrdən əvvəl də görür. Bu, işçi-görünüşü deyil, öz iş
        jurnalıdır.
        """
        return [fine for fine in fines if fine.issued_by == operator_id]

    # ------------------------------- nəşr ------------------------------------ #

    def publish_batch(
        self,
        *,
        actor: Employee,
        tenant_id: TenantId,
        review_month: str,
        fines: dict[FineId, Fine],
        decisions: list[FineDecision],
    ) -> PublishResult:
        """Bütün qərarları tətbiq edir.

        Args:
            fines: İcmalda göstərilən cərimələr (`id → Fine`).
            decisions: Sətir qərarları. Siyahıda OLMAYAN cərimə "Saxla"
                sayılır — UI-dakı defolt ilə eynidir.
        """
        now = self._clock.now()
        self._assert_may_publish(actor, now=now)
        _require_month(review_month)

        by_id = {decision.fine_id: decision for decision in decisions}
        unknown = set(by_id) - set(fines)
        if unknown:
            raise FineReviewError(
                f"İcmalda olmayan cərimə üçün qərar verildi: {sorted(map(str, unknown))}",
                context={"unknown_count": len(unknown)},
            )

        pending = {
            fine_id: fine
            for fine_id, fine in fines.items()
            if fine.status is FineStatus.PENDING_REVIEW
        }
        if not pending:
            raise FineReviewError(
                "Nəşr gözləyən cərimə yoxdur",
                user_message="Bu ay üçün göndəriləcək cərimə yoxdur.",
            )

        batch_id = uuid4()
        result = PublishResult(batch_id=batch_id, review_month=review_month)

        for fine_id, fine in pending.items():
            decision = by_id.get(fine_id, FineDecision(fine_id=fine_id))
            if decision.decision is ReviewDecision.DISCARD:
                reason = (decision.reason or "").strip()
                if len(reason) < MIN_DISCARD_REASON_LENGTH:
                    raise FineReviewError(
                        f"'Sil' qərarı üçün səbəb məcburidir "
                        f"(minimum {MIN_DISCARD_REASON_LENGTH} simvol)",
                        user_message="Silinən cərimə üçün səbəb yazılmalıdır.",
                        context={"fine_id": str(fine_id)},
                    )
                fine.discard_in_review(reviewed_by=actor.id, reviewed_at=now, reason=reason)
                result.discarded.append(fine_id)
            else:
                fine.publish(reviewed_by=actor.id, published_at=now)
                result.published.append(fine_id)

        self._record(actor, tenant_id, result, now=now)
        return result

    # ------------------------------ köməkçi ---------------------------------- #

    def _assert_may_publish(self, actor: Employee, *, now: datetime) -> None:
        if not actor.has_permission(PUBLISH_FINES_FLAG, now=now):
            _security_log.warning(
                "FINE_PUBLISH_DENIED",
                extra={
                    "actor_id": str(actor.id),
                    "role": actor.position.code,
                    "reason": "MISSING_FLAG",
                },
            )
            raise FineReviewError(
                f"'{PUBLISH_FINES_FLAG}' səlahiyyəti yoxdur",
                user_message="Cərimələri göndərmək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )

    def _record(
        self,
        actor: Employee,
        tenant_id: TenantId,
        result: PublishResult,
        *,
        now: datetime,
    ) -> None:
        _audit_log.warning(
            "MONTHLY_FINES_PUBLISHED",
            extra={
                "batch_id": str(result.batch_id),
                "review_month": result.review_month,
                "actor_id": str(actor.id),
                "published_count": len(result.published),
                "discarded_count": len(result.discarded),
            },
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="MONTHLY_FINES_PUBLISHED",
            entity_type="monthly_fine_review_batches",
            entity_id=None,
            after_state={
                "batch_id": str(result.batch_id),
                "review_month": result.review_month,
                "kept": len(result.published),
                "reversed": len(result.discarded),
                "published_at": now.isoformat(),
            },
        )
        if result.published:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="MONTHLY_FINES_PUBLISHED",
                title_az="Aylıq cərimələr göndərildi",
                body_az=(
                    f"{result.review_month} ayı üzrə {len(result.published)} cərimə "
                    f"bütün filiallara göndərildi və işçilərin 'Cərimələrim' "
                    f"bölməsində göründü."
                ),
                is_critical=False,
            )


def _require_month(value: str) -> None:
    """`YYYY-MM` — DB-dəki `chk_batch_month` ilə eyni qayda."""
    parts = value.split("-")
    valid = (
        len(parts) == 2  # noqa: PLR2004 - il və ay
        and len(parts[0]) == 4  # noqa: PLR2004 - dörd rəqəmli il
        and parts[0].isdigit()
        and len(parts[1]) == 2  # noqa: PLR2004 - iki rəqəmli ay
        and parts[1].isdigit()
        and 1 <= int(parts[1]) <= 12  # noqa: PLR2004 - ay aralığı
    )
    if not valid:
        raise FineReviewError(f"Ay formatı 'YYYY-MM' olmalıdır: {value!r}")


__all__ = [
    "PUBLISH_FINES_FLAG",
    "FineDecision",
    "FineReviewError",
    "MonthlyFineReviewUseCase",
    "PublishResult",
    "ReviewDecision",
]
