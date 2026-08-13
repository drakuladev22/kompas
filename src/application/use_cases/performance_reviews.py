"""Performans Qiymətləndirməsi — #20, kompasos11.md Faza 8.

`can_conduct_performance_review` sahibi dövri (rüb/ay — ROOT parametri) sadə
forma doldurur: bir neçə KPI + qeyd sahəsi. Nəticə işçinin ÖZ tarixçəsində
görünür (`group_g.ProfileScreen`). CLAUDE.md §6 use case naxışı: səlahiyyət →
domen qaydası (entity-də) → yazma → audit → bildiriş.

──────────────────────────────────────────────────────────────────────────────
STRICT HIERARCHY GUARD — MÖVCUD `Employee.outranks()` BİRBAŞA ÇAĞIRILIR
──────────────────────────────────────────────────────────────────────────────
`pos_threshold.py`-dəki QIRMIZI XƏTT eyni budur: `PermissionHierarchyGuardUseCase`
ÖZÜ işlədilmir, çünki onun bütün API-si `PermissionFlag` + grant/deny
effektinə (fərdi icazə override-i) qurulub — performans qiyməti isə flag
deyil, KPI/bal cütüdür. Eyni PRİNSİP (guard-ı çağır, təkrarlama) burada
guard-ın ƏSAS metoduna (`Employee.outranks`) birbaşa müraciətlə tətbiq olunur.
ROOT ÜÇÜN İSTİSNA YOXDUR (`pos_threshold.py` ilə EYNİ əsaslandırma, SEC-006-dan
fərqli): bu, funksional icazənin ötürülməsi DEYİL, "kim kimi qiymətləndirə
bilər" struktur qaydasıdır.

──────────────────────────────────────────────────────────────────────────────
ÖZ-ÖZÜNÜ QİYMƏTLƏNDİRMƏ — ÜÇ QAT
──────────────────────────────────────────────────────────────────────────────
1) Bu use case-də ERKƏN yoxlama (`_require_not_self`) — DB-yə yararsız sorğu
getmədən aydın mesaj verir (`pos_threshold._require_not_self` ilə eyni naxış).
2) Domen (`PerformanceReview.__init__`/`update_ratings` → `SelfReviewNotAllowedError`).
3) DB `CHECK (employee_id <> reviewer_id)` (migrations/020) — ekranı yan
keçən skript də bloklanır.

──────────────────────────────────────────────────────────────────────────────
EYNİ DÖVR ÜÇÜN TƏKRAR QİYMƏTLƏNDİRMƏ — SÜKUTLA RƏDD YOX, YENİLƏYİR
──────────────────────────────────────────────────────────────────────────────
`migrations/020`: "Düzəliş mövcud sətri yeniləyir, dəyişiklik izi
`audit_logs`-a düşür." `submit_review()` mövcud sətri ƏVVƏLCƏ TAPIR (`get()`)
və tapılsa `update_ratings()` çağırır — YENİ sətir YARANMIR, `UNIQUE (tenant_id,
employee_id, period)` pozulmur. Bu, SƏHV DEYİL: "illik görüş yenidən
planlaşdırılıb" real HR təcrübəsidir və köhnə səhv qiyməti əbədi saxlamaqdansa
DÜZƏLDİLMİŞ nəticəni saxlamaq üstünlük təşkil edir — audit before/after bu
düzəlişi HƏMİŞƏ izləyir, itki YOXDUR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.domain.entities.performance_review import PerformanceReview
from src.domain.policies import DEFAULT_LIMITS, PerformanceReviewPeriodType, SystemLimitKey
from src.domain.value_objects.authorization import AuthorizationError
from src.domain.value_objects.identifiers import new_performance_review_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        EmployeeRepository,
        Notifier,
        PerformanceReviewRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeId, PerformanceReviewId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Faza 2-də kataloqa əlavə edilmiş flag (migrations/021).
CONDUCT_PERFORMANCE_REVIEW_FLAG = "can_conduct_performance_review"

#: FALLBACK-lar — həqiqi mənbə `system_limits` (migrations/029 seed edir).
_FALLBACK_PERIOD_TYPE: Final = DEFAULT_LIMITS[SystemLimitKey.PERFORMANCE_REVIEW_PERIOD_TYPE]
_FALLBACK_KPI_CATALOG: Final = DEFAULT_LIMITS[SystemLimitKey.PERFORMANCE_REVIEW_KPI_CATALOG]

#: Qiymətləndirmə yazıldığında işçiyə göndərilən ŞƏXSİ bildiriş kateqoriyası.
#: `recipient_id` DOLU olduğu üçün `TENANT_NOTIFICATION_AUDIENCE` süzgəcindən
#: ASILI DEYİL (`domain/value_objects/notifications.py` başlığı: "ŞƏXSİ SƏTİR
#: HƏMİŞƏ öz sahibinə görünür").
REVIEW_RECORDED_NOTIFICATION_CATEGORY = "PERFORMANCE_REVIEW_RECORDED"


class PerformanceReviewError(KompasOSError):
    """Performans qiymətləndirməsi əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Performans qiymətləndirməsi icra edilə bilmədi."


class PerformanceReviewSubjectNotFoundError(PerformanceReviewError):
    user_message = "Qiymətləndiriləcək işçi tapılmadı."


@dataclass(frozen=True)
class KpiDefinition:
    """`system_limits.PERFORMANCE_REVIEW_KPI_CATALOG`-dan parçalanmış BİR göstərici."""

    code: str
    label_az: str


@dataclass(frozen=True)
class PerformanceReviewView:
    """Ekranların oxuduğu düz görünüş (composer tarixçəsi və Profil ekranı)."""

    review_id: PerformanceReviewId
    employee_id: EmployeeId
    reviewer_id: EmployeeId
    period: str
    ratings: dict[str, int]
    overall_score: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PerformanceReviewUseCase:
    """`can_conduct_performance_review` sahibi qiymətləndirmə yazır/oxuyur."""

    def __init__(
        self,
        *,
        reviews: PerformanceReviewRepository,
        employees: EmployeeRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._reviews = reviews
        self._employees = employees
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # -------------------------------- forma köməkçiləri ------------------------ #

    def kpi_catalog(self, tenant_id: TenantId) -> list[KpiDefinition]:
        """Formanın göstərəcəyi KPI siyahısı — koda HARDCODE EDİLMİR (ROOT parametri)."""
        raw = self._limits.get_str(
            tenant_id, SystemLimitKey.PERFORMANCE_REVIEW_KPI_CATALOG.value, _FALLBACK_KPI_CATALOG
        )
        return _parse_kpi_catalog(raw) or _parse_kpi_catalog(_FALLBACK_KPI_CATALOG)

    def default_period(self, tenant_id: TenantId) -> str:
        """Formanın ilkin təklif etdiyi dövr — `PERFORMANCE_REVIEW_PERIOD_TYPE`-a görə."""
        raw = self._limits.get_str(
            tenant_id, SystemLimitKey.PERFORMANCE_REVIEW_PERIOD_TYPE.value, _FALLBACK_PERIOD_TYPE
        )
        period_type = PerformanceReviewPeriodType.from_value(raw)
        today = self._clock.now().date()
        return period_type.format_period(year=today.year, month=today.month)

    # -------------------------------- yazı -------------------------------------- #

    def submit_review(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        period: str,
        ratings: dict[str, int],
        notes: str | None,
    ) -> PerformanceReview:
        """Formanın `[Yadda Saxla]` düyməsi — yeni dövr YARADIR VƏ YA mövcudu YENİLƏYİR."""
        self._require_permission(actor, tenant_id)
        self._require_not_self(actor, employee_id)
        subject = self._employees.get(employee_id)
        if subject is None:
            raise PerformanceReviewSubjectNotFoundError(
                "Qiymətləndiriləcək işçi tapılmadı", context={"employee_id": str(employee_id)}
            )
        self._require_same_tenant(subject, tenant_id)
        self._require_hierarchy(actor, subject)

        filtered_ratings = self._filter_to_catalog(tenant_id, ratings)
        if not filtered_ratings:
            raise PerformanceReviewError(
                "Heç bir tanınan KPI göndərilməyib",
                user_message="Ən azı bir göstərici üçün qiymət seçin.",
                context={"period": period},
            )

        now = self._clock.now()
        existing = self._reviews.get(tenant_id, employee_id, period)
        before_state = existing.to_audit_state() if existing is not None else None

        if existing is not None:
            review = existing
            review.update_ratings(
                reviewer_id=actor.id, ratings=filtered_ratings, notes=notes, now=now
            )
            action = "PERFORMANCE_REVIEW_UPDATED"
        else:
            review = PerformanceReview(
                review_id=new_performance_review_id(),
                tenant_id=tenant_id,
                employee_id=employee_id,
                reviewer_id=actor.id,
                period=period,
                ratings=filtered_ratings,
                notes=notes,
                created_at=now,
                updated_at=now,
            )
            action = "PERFORMANCE_REVIEW_SUBMITTED"

        self._reviews.save(review)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action=action,
            entity_type="performance_reviews",
            entity_id=review.id,
            before_state=before_state,
            after_state=review.to_audit_state(),
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=employee_id,
            category=REVIEW_RECORDED_NOTIFICATION_CATEGORY,
            title_az="Performans qiymətləndirməniz yazıldı",
            body_az=(
                f"{period} dövrü üçün performans qiymətləndirməniz "
                f"{subject.full_name} adına yeniləndi."
            ),
            is_critical=False,
        )
        return review

    # -------------------------------- oxu ---------------------------------------- #

    def list_own(self, *, tenant_id: TenantId, employee: Employee) -> list[PerformanceReviewView]:
        """Profil ekranının "Performans Tarixçəm" bölməsi.

        SƏLAHİYYƏT FLAG-İ TƏLƏB OLUNMUR — bu, işçinin ÖZ tarixçəsidir
        (`OpenShiftMarketUseCase.list_for_employee` ilə eyni qərar).
        """
        return [
            _to_view(review) for review in self._reviews.list_for_employee(tenant_id, employee.id)
        ]

    def list_for_employee(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId
    ) -> list[PerformanceReviewView]:
        """Composer ekranının keçmiş-dövrlər siyahısı — yeni forma açmazdan əvvəl.

        Reviewer YALNIZ hiyerarxiyaca aşağı işçinin tarixçəsinə baxa bilər —
        `submit_review`-dəki EYNİ `_require_hierarchy` çağırışı (oxu da yazı
        qədər həssasdır: keçmiş qiymətlər performans tarixçəsidir).
        """
        self._require_permission(actor, tenant_id)
        if actor.id != employee_id:
            subject = self._employees.get(employee_id)
            if subject is None:
                raise PerformanceReviewSubjectNotFoundError(
                    "Qiymətləndiriləcək işçi tapılmadı", context={"employee_id": str(employee_id)}
                )
            self._require_hierarchy(actor, subject)
        return [
            _to_view(review) for review in self._reviews.list_for_employee(tenant_id, employee_id)
        ]

    # ------------------------------- köməkçi -------------------------------------- #

    def _filter_to_catalog(self, tenant_id: TenantId, ratings: dict[str, int]) -> dict[str, int]:
        """Formadan gələn qiymətləri Root-un CARİ KPI kataloquna görə süzür.

        Kataloqdan çıxarılmış (köhnə) kod göndərilsə sükutla ATILIR — forma
        açılan andan yazılana qədər Root kataloqu dəyişə bilər, bu, gözlənilən
        (nadir) haldır və bütün göndərişi rədd etmək yerinə yalnız naməlum
        kodu kənarlaşdırmaq daha az zərərlidir.
        """
        catalog_codes = {kpi.code for kpi in self.kpi_catalog(tenant_id)}
        return {
            code.strip().upper(): score
            for code, score in ratings.items()
            if code.strip().upper() in catalog_codes
        }

    def _require_permission(self, actor: Employee, tenant_id: TenantId) -> None:
        if actor.tenant_id != tenant_id:
            # Üçüncü izolyasiya qatı (RLS və repo `tenant_id` şərtindən sonra).
            raise AuthorizationError(
                "Aktor bu kirayəçiyə aid deyil",
                context={"actor_id": str(actor.id)},
            )
        now = self._clock.now()
        if not actor.has_permission(CONDUCT_PERFORMANCE_REVIEW_FLAG, now=now):
            _security_log.warning(
                "PERFORMANCE_REVIEW_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": CONDUCT_PERFORMANCE_REVIEW_FLAG},
            )
            raise AuthorizationError(
                f"«{CONDUCT_PERFORMANCE_REVIEW_FLAG}» səlahiyyəti yoxdur",
                context={"flag": CONDUCT_PERFORMANCE_REVIEW_FLAG},
            )

    def _require_not_self(self, actor: Employee, employee_id: EmployeeId) -> None:
        """Vəzifə ayrılığı: qiymətləndirən özünü qiymətləndirə bilməz (`pos_threshold` naxışı)."""
        if actor.id == employee_id:
            _security_log.warning(
                "PERFORMANCE_REVIEW_SELF_ASSIGNMENT_BLOCKED",
                extra={"actor_id": str(actor.id)},
            )
            raise AuthorizationError(
                "VƏZİFƏ AYRILIĞI: qiymətləndirən özünü qiymətləndirə bilməz",
                user_message="Özünüzü qiymətləndirə bilməzsiniz.",
                context={"actor_id": str(actor.id)},
            )

    def _require_hierarchy(self, actor: Employee, subject: Employee) -> None:
        """Strict Hierarchy Guard — `Employee.outranks()` birbaşa çağırılır (modul başlığı)."""
        if not actor.outranks(subject):
            _security_log.warning(
                "PERFORMANCE_REVIEW_HIERARCHY_DENIED",
                extra={"actor_id": str(actor.id), "subject_id": str(subject.id)},
            )
            raise AuthorizationError(
                "STRICT HIERARCHY GUARD: yalnız CİDDİ ŞƏKİLDƏ aşağı pilləni qiymətləndirmək olar",
                user_message=("Bu işçi sizinlə eyni və ya daha yüksək səlahiyyət pilləsindədir."),
                context={"actor_id": str(actor.id), "subject_id": str(subject.id)},
            )

    def _require_same_tenant(self, subject: Employee, tenant_id: TenantId) -> None:
        if subject.tenant_id != tenant_id:
            raise AuthorizationError(
                "Hədəf işçi bu kirayəçiyə aid deyil",
                context={"subject_id": str(subject.id)},
            )


def _parse_kpi_catalog(raw: str) -> list[KpiDefinition]:
    """`"KOD:Ad;KOD:Ad"` sətrini `KpiDefinition` siyahısına çevirir.

    Yararsız/boş hissələr sükutla ATILIR (`employee_documents._expiry_warning_days`
    ilə eyni fəlsəfə) — konfiqurasiya səhvi bütün formanı çökdürməməlidir.
    """
    catalog: list[KpiDefinition] = []
    for entry in raw.split(";"):
        cleaned = entry.strip()
        if not cleaned:
            continue
        code, _, label = cleaned.partition(":")
        code = code.strip().upper()
        if not code:
            continue
        catalog.append(KpiDefinition(code=code, label_az=label.strip() or code))
    return catalog


def _to_view(review: PerformanceReview) -> PerformanceReviewView:
    return PerformanceReviewView(
        review_id=review.id,
        employee_id=review.employee_id,
        reviewer_id=review.reviewer_id,
        period=review.period,
        ratings=dict(review.ratings),
        overall_score=review.overall_score,
        notes=review.notes,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


__all__ = [
    "CONDUCT_PERFORMANCE_REVIEW_FLAG",
    "REVIEW_RECORDED_NOTIFICATION_CATEGORY",
    "KpiDefinition",
    "PerformanceReviewError",
    "PerformanceReviewSubjectNotFoundError",
    "PerformanceReviewUseCase",
    "PerformanceReviewView",
]
