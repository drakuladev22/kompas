"""#20 Performans Qiymətləndirməsi — kompasos11.md Faza 8.

BAZA LAZIM DEYİL: bütün portlar sahtə obyektlərlə əvəz olunur.

──────────────────────────────────────────────────────────────────────────────
NƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
1. ÖZ-ÖZÜNÜ QİYMƏTLƏNDİRMƏ BLOKU — həm use case-in erkən yoxlaması, həm
   entity-nin `SelfReviewNotAllowedError`-u.
2. STRICT HIERARCHY GUARD — `Employee.outranks()` birbaşa çağırılır; bərabər
   və ya yuxarı pillə BLOKLANIR.
3. SƏLAHİYYƏT — `can_conduct_performance_review` olmadan yazı BLOKLANIR.
4. ROOT PARAMETRİ (dövr) — `default_period()` `PERFORMANCE_REVIEW_PERIOD_TYPE`-a
   görə "YYYY-MM" (aylıq) və ya "YYYY-Qn" (rüblük) qaytarır.
5. KPI KATALOQU ROOT-DAN GƏLİR — koda hardcode edilməyib, naməlum kod
   sükutla süzülür (ekranı çökdürmür).
6. EYNİ DÖVR ÜÇÜN TƏKRAR GÖNDƏRİŞ — YENİ sətir yaratmır, MÖVCUDU yeniləyir
   (qərar: `migrations/020` "düzəliş mövcud sətri yeniləyir" — SƏHV DEYİL).
7. BAL ŞKALASI (1-5) — hüduddan kənar dəyər rədd edilir.
8. BOŞ SİYAHI HALLARI.
9. AUDIT — hər yazı `audit_logs`-a düşür, bildiriş işçiyə ŞƏXSİ sətirlə gedir.

SAHTƏLƏR: `InMemoryPerformanceReviews`/`InMemoryEmployeeDirectory` BU FAYLDA
təyin olunub (paylaşılan `tests/fixtures/fakes.py` dəyişdirilmir).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.application.use_cases.performance_reviews import (
    CONDUCT_PERFORMANCE_REVIEW_FLAG,
    PerformanceReviewError,
    PerformanceReviewSubjectNotFoundError,
    PerformanceReviewUseCase,
)
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.performance_review import (
    KPI_SCORE_MAX,
    KPI_SCORE_MIN,
    PerformanceReview,
    SelfReviewNotAllowedError,
)
from src.domain.entities.position import Position
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionEffect,
    RolePriority,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PerformanceReviewId,
    TenantId,
    new_performance_review_id,
)
from tests.fixtures.fakes import FakeClock, FakeSystemLimits, RecordingAudit, RecordingNotifier

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
OTHER_TENANT = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


class InMemoryPerformanceReviews:
    """`PerformanceReviewRepository`-nin yaddaş versiyası — `(tenant_id,
    employee_id, period)` ÜÇLÜYÜNƏ görə UPSERT edir (`pos_permission_
    thresholds` naxışının eynisi)."""

    def __init__(self) -> None:
        self.items: dict[PerformanceReviewId, PerformanceReview] = {}

    def get(
        self, tenant_id: TenantId, employee_id: EmployeeId, period: str
    ) -> PerformanceReview | None:
        for item in self.items.values():
            if (
                item.tenant_id == tenant_id
                and item.employee_id == employee_id
                and item.period == period
            ):
                return item
        return None

    def list_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> list[PerformanceReview]:
        rows = [
            item
            for item in self.items.values()
            if item.tenant_id == tenant_id and item.employee_id == employee_id
        ]
        rows.sort(key=lambda item: item.period, reverse=True)
        return rows

    def save(self, record: PerformanceReview) -> None:
        self.items[record.id] = record


class InMemoryEmployeeDirectory:
    """`EmployeeRepository`-nin YALNIZ `get()` işlədən minimal versiyası."""

    def __init__(self, employees: list[Employee]) -> None:
        self._by_id = {employee.id: employee for employee in employees}

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._by_id.get(employee_id)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee(
    *,
    priority: RolePriority = RolePriority.OPERATIONAL,
    flags: tuple[str, ...] = (CONDUCT_PERFORMANCE_REVIEW_FLAG,),
    tenant_id: TenantId = TENANT,
) -> Employee:
    position = Position(
        position_id=uuid.uuid4(),  # type: ignore[arg-type]
        code=f"ROLE_{priority.name}_{uuid.uuid4().hex[:6]}",
        name_az="Sınaq rolu",
        priority=priority,
        tenant_id=tenant_id,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name="Aynur",
        last_name="Hüseynova",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


def _use_case(
    *, employees: list[Employee], limits: dict[str, str] | None = None
) -> tuple[PerformanceReviewUseCase, InMemoryPerformanceReviews, RecordingAudit, RecordingNotifier]:
    repository = InMemoryPerformanceReviews()
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    use_case = PerformanceReviewUseCase(
        reviews=repository,
        employees=InMemoryEmployeeDirectory(employees),
        limits=FakeSystemLimits(limits),
        audit=audit,
        clock=FakeClock(NOW),
        notifier=notifier,
    )
    return use_case, repository, audit, notifier


_RATINGS = {"KEYFIYYET": 4, "MEHSULDARLIQ": 5}


# --------------------------------------------------------------------------- #
# 1. AQREQAT — ÖZ-ÖZÜNÜ QİYMƏTLƏNDİRMƏ VƏ ŞKALA
# --------------------------------------------------------------------------- #


def test_entity_blocks_self_review() -> None:
    employee_id = EmployeeId(uuid.uuid4())
    with pytest.raises(SelfReviewNotAllowedError):
        PerformanceReview(
            review_id=new_performance_review_id(),
            tenant_id=TENANT,
            employee_id=employee_id,
            reviewer_id=employee_id,
            period="2026-Q3",
            ratings=_RATINGS,
            notes=None,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.parametrize("score", [KPI_SCORE_MIN - 1, KPI_SCORE_MAX + 1, -5, 100])
def test_score_outside_scale_is_rejected(score: int) -> None:
    with pytest.raises(DomainRuleError):
        PerformanceReview(
            review_id=new_performance_review_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            reviewer_id=EmployeeId(uuid.uuid4()),
            period="2026-Q3",
            ratings={"KEYFIYYET": score},
            notes=None,
            created_at=NOW,
            updated_at=NOW,
        )


def test_boolean_score_is_rejected() -> None:
    """`bool` Python-da `int`-in alt-sinfidir (`isinstance(True, int)` → `True`) —
    entity onu açıq şəkildə RƏDD edir, əks halda "5-ci KPI: True" mənasız sətir yazılardı.
    """
    with pytest.raises(DomainRuleError, match="tam ədəd"):
        PerformanceReview(
            review_id=new_performance_review_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            reviewer_id=EmployeeId(uuid.uuid4()),
            period="2026-Q3",
            ratings={"KEYFIYYET": True},
            notes=None,
            created_at=NOW,
            updated_at=NOW,
        )


def test_empty_ratings_dict_is_rejected_at_construction() -> None:
    with pytest.raises(DomainRuleError, match="KPI"):
        PerformanceReview(
            review_id=new_performance_review_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            reviewer_id=EmployeeId(uuid.uuid4()),
            period="2026-Q3",
            ratings={},
            notes=None,
            created_at=NOW,
            updated_at=NOW,
        )


def test_update_ratings_blocks_self_review_at_entity_level() -> None:
    """Üçüncü qat: `update_ratings` da `SelfReviewNotAllowedError` atır —
    yalnız `__init__`-də yox (bax modul başlığı, "ÜÇ QAT")."""
    employee_id = EmployeeId(uuid.uuid4())
    review = PerformanceReview(
        review_id=new_performance_review_id(),
        tenant_id=TENANT,
        employee_id=employee_id,
        reviewer_id=EmployeeId(uuid.uuid4()),
        period="2026-Q3",
        ratings=_RATINGS,
        notes=None,
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(SelfReviewNotAllowedError):
        review.update_ratings(reviewer_id=employee_id, ratings=_RATINGS, notes=None, now=NOW)


def test_invalid_period_format_is_rejected() -> None:
    with pytest.raises(DomainRuleError, match="format"):
        PerformanceReview(
            review_id=new_performance_review_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            reviewer_id=EmployeeId(uuid.uuid4()),
            period="Q3 2026",
            ratings=_RATINGS,
            notes=None,
            created_at=NOW,
            updated_at=NOW,
        )


def test_overall_score_maps_min_and_max_of_scale() -> None:
    lowest = PerformanceReview(
        review_id=new_performance_review_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        reviewer_id=EmployeeId(uuid.uuid4()),
        period="2026-Q3",
        ratings={"KEYFIYYET": KPI_SCORE_MIN},
        notes=None,
        created_at=NOW,
        updated_at=NOW,
    )
    highest = PerformanceReview(
        review_id=new_performance_review_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        reviewer_id=EmployeeId(uuid.uuid4()),
        period="2026-Q3",
        ratings={"KEYFIYYET": KPI_SCORE_MAX},
        notes=None,
        created_at=NOW,
        updated_at=NOW,
    )
    assert lowest.overall_score == 0
    assert highest.overall_score == 100


# --------------------------------------------------------------------------- #
# 2. USE CASE — SƏLAHİYYƏT, ÖZÜNÜ QİYMƏTLƏNDİRMƏ, HİYERARXİYA
# --------------------------------------------------------------------------- #


def test_submit_without_flag_is_blocked() -> None:
    subject = _employee(priority=RolePriority.STAFF)
    actor = _employee(priority=RolePriority.EXECUTIVE, flags=())
    use_case, repository, audit, _ = _use_case(employees=[subject])

    with pytest.raises(AuthorizationError, match=CONDUCT_PERFORMANCE_REVIEW_FLAG):
        use_case.submit_review(
            tenant_id=TENANT,
            actor=actor,
            employee_id=subject.id,
            period="2026-Q3",
            ratings=_RATINGS,
            notes=None,
        )
    assert repository.items == {}
    assert audit.entries == []


def test_self_review_is_blocked_by_use_case_before_touching_the_repository() -> None:
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, repository, audit, _ = _use_case(employees=[actor])

    with pytest.raises(AuthorizationError, match="VƏZİFƏ AYRILIĞI"):
        use_case.submit_review(
            tenant_id=TENANT,
            actor=actor,
            employee_id=actor.id,
            period="2026-Q3",
            ratings=_RATINGS,
            notes=None,
        )
    assert repository.items == {}
    assert audit.entries == []


def test_equal_rank_is_blocked_by_strict_hierarchy() -> None:
    subject = _employee(priority=RolePriority.ADMIN)
    actor = _employee(priority=RolePriority.ADMIN)
    use_case, repository, audit, _ = _use_case(employees=[subject])

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        use_case.submit_review(
            tenant_id=TENANT,
            actor=actor,
            employee_id=subject.id,
            period="2026-Q3",
            ratings=_RATINGS,
            notes=None,
        )
    assert repository.items == {}
    assert audit.entries == []


def test_lower_actor_cannot_review_higher_subject() -> None:
    subject = _employee(priority=RolePriority.EXECUTIVE)
    actor = _employee(priority=RolePriority.STAFF)
    use_case, _, _, _ = _use_case(employees=[subject])

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        use_case.submit_review(
            tenant_id=TENANT,
            actor=actor,
            employee_id=subject.id,
            period="2026-Q3",
            ratings=_RATINGS,
            notes=None,
        )


def test_higher_actor_can_review_lower_subject() -> None:
    subject = _employee(priority=RolePriority.STAFF)
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, repository, audit, notifier = _use_case(employees=[subject])

    review = use_case.submit_review(
        tenant_id=TENANT,
        actor=actor,
        employee_id=subject.id,
        period="2026-Q3",
        ratings=_RATINGS,
        notes="Yaxşı nəticə",
    )

    assert repository.items[review.id].reviewer_id == actor.id
    assert audit.actions() == ["PERFORMANCE_REVIEW_SUBMITTED"]
    assert notifier.categories() == ["PERFORMANCE_REVIEW_RECORDED"]
    assert notifier.messages[0]["recipient_id"] == subject.id


def test_unknown_subject_raises_not_found() -> None:
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, _, _, _ = _use_case(employees=[])

    with pytest.raises(PerformanceReviewSubjectNotFoundError):
        use_case.submit_review(
            tenant_id=TENANT,
            actor=actor,
            employee_id=EmployeeId(uuid.uuid4()),
            period="2026-Q3",
            ratings=_RATINGS,
            notes=None,
        )


def test_subject_from_another_tenant_is_rejected() -> None:
    subject = _employee(priority=RolePriority.STAFF, tenant_id=OTHER_TENANT)
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, _, _, _ = _use_case(employees=[subject])

    with pytest.raises(AuthorizationError, match="Hədəf işçi"):
        use_case.submit_review(
            tenant_id=TENANT,
            actor=actor,
            employee_id=subject.id,
            period="2026-Q3",
            ratings=_RATINGS,
            notes=None,
        )


# --------------------------------------------------------------------------- #
# 3. KPI KATALOQU — ROOT-DAN GƏLİR, HARDCODE DEYİL
# --------------------------------------------------------------------------- #


def test_unknown_kpi_codes_are_silently_filtered() -> None:
    subject = _employee(priority=RolePriority.STAFF)
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, repository, _, _ = _use_case(
        employees=[subject],
        limits={SystemLimitKey.PERFORMANCE_REVIEW_KPI_CATALOG.value: "KEYFIYYET:Keyfiyyət"},
    )

    review = use_case.submit_review(
        tenant_id=TENANT,
        actor=actor,
        employee_id=subject.id,
        period="2026-Q3",
        ratings={"KEYFIYYET": 5, "NAMELUM_KOD": 1},
        notes=None,
    )

    assert repository.items[review.id].ratings == {"KEYFIYYET": 5}


def test_all_unknown_kpi_codes_raise_a_clear_error() -> None:
    subject = _employee(priority=RolePriority.STAFF)
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, repository, audit, _ = _use_case(
        employees=[subject],
        limits={SystemLimitKey.PERFORMANCE_REVIEW_KPI_CATALOG.value: "KEYFIYYET:Keyfiyyət"},
    )

    with pytest.raises(PerformanceReviewError, match="KPI"):
        use_case.submit_review(
            tenant_id=TENANT,
            actor=actor,
            employee_id=subject.id,
            period="2026-Q3",
            ratings={"NAMELUM_KOD": 3},
            notes=None,
        )
    assert repository.items == {}
    assert audit.entries == []


def test_default_period_follows_the_root_period_type() -> None:
    subject = _employee(priority=RolePriority.STAFF)
    use_case, _, _, _ = _use_case(
        employees=[subject],
        limits={SystemLimitKey.PERFORMANCE_REVIEW_PERIOD_TYPE.value: "QUARTERLY"},
    )
    # NOW = 2026-08-12 → Avqust 3-cü rübdədir (İyul-Sentyabr).
    assert use_case.default_period(TENANT) == "2026-Q3"


def test_default_period_defaults_to_monthly() -> None:
    subject = _employee(priority=RolePriority.STAFF)
    use_case, _, _, _ = _use_case(employees=[subject])
    assert use_case.default_period(TENANT) == "2026-08"


# --------------------------------------------------------------------------- #
# 4. EYNİ DÖVR ÜÇÜN TƏKRAR GÖNDƏRİŞ — YENİLƏYİR, TƏKRARLAMIR
# --------------------------------------------------------------------------- #


def test_resubmitting_the_same_period_updates_the_existing_row() -> None:
    """QƏRAR: eyni (işçi, dövr) cütü üçün ikinci göndəriş sükutla RƏDD
    EDİLMİR və YENİ sətir DƏ yaratmır — mövcud sətri YENİLƏYİR
    (`migrations/020`: "düzəliş mövcud sətri yeniləyir, dəyişiklik izi
    audit_logs-a düşür"). Bu, real HR təcrübəsinə uyğundur: "illik görüş
    yenidən planlaşdırılıb" halında köhnə səhv qiyməti əbədi saxlamaqdansa,
    düzəldilmiş nəticəni saxlamaq üstünlük təşkil edir.
    """
    subject = _employee(priority=RolePriority.STAFF)
    first_reviewer = _employee(priority=RolePriority.EXECUTIVE)
    second_reviewer = _employee(priority=RolePriority.ADMIN)
    use_case, repository, audit, _ = _use_case(employees=[subject, first_reviewer, second_reviewer])

    first = use_case.submit_review(
        tenant_id=TENANT,
        actor=first_reviewer,
        employee_id=subject.id,
        period="2026-Q3",
        ratings={"KEYFIYYET": 3},
        notes="İlkin qeyd",
    )
    second = use_case.submit_review(
        tenant_id=TENANT,
        actor=second_reviewer,
        employee_id=subject.id,
        period="2026-Q3",
        ratings={"KEYFIYYET": 5},
        notes="Düzəldilmiş qeyd",
    )

    # YENİ sətir YARANMAYIB — eyni `id`, eyni tək sətir.
    assert first.id == second.id
    assert len(repository.list_for_employee(TENANT, subject.id)) == 1

    stored = repository.get(TENANT, subject.id, "2026-Q3")
    assert stored is not None
    assert stored.reviewer_id == second_reviewer.id
    assert stored.ratings == {"KEYFIYYET": 5}
    assert stored.notes == "Düzəldilmiş qeyd"

    assert audit.actions() == ["PERFORMANCE_REVIEW_SUBMITTED", "PERFORMANCE_REVIEW_UPDATED"]
    assert audit.entries[1]["before_state"]["ratings"] == {"KEYFIYYET": 3}
    assert audit.entries[1]["after_state"]["ratings"] == {"KEYFIYYET": 5}


def test_different_periods_create_separate_rows() -> None:
    subject = _employee(priority=RolePriority.STAFF)
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, repository, _, _ = _use_case(employees=[subject])

    use_case.submit_review(
        tenant_id=TENANT,
        actor=actor,
        employee_id=subject.id,
        period="2026-Q2",
        ratings=_RATINGS,
        notes=None,
    )
    use_case.submit_review(
        tenant_id=TENANT,
        actor=actor,
        employee_id=subject.id,
        period="2026-Q3",
        ratings=_RATINGS,
        notes=None,
    )

    assert len(repository.list_for_employee(TENANT, subject.id)) == 2


# --------------------------------------------------------------------------- #
# 5. OXU — ÖZ TARİXÇƏSİ, BOŞ SİYAHI HALLARI
# --------------------------------------------------------------------------- #


def test_list_own_requires_no_permission() -> None:
    """Profil ekranı — self-service, `EmployeeProfileAccessUseCase` ilə eyni ruh."""
    subject = _employee(priority=RolePriority.STAFF, flags=())
    actor = _employee(priority=RolePriority.EXECUTIVE)
    use_case, _, _, _ = _use_case(employees=[subject])
    use_case.submit_review(
        tenant_id=TENANT,
        actor=actor,
        employee_id=subject.id,
        period="2026-Q3",
        ratings=_RATINGS,
        notes=None,
    )

    views = use_case.list_own(tenant_id=TENANT, employee=subject)
    assert len(views) == 1
    assert views[0].period == "2026-Q3"


def test_list_own_is_empty_when_no_reviews_exist() -> None:
    subject = _employee(priority=RolePriority.STAFF, flags=())
    use_case, _, _, _ = _use_case(employees=[subject])
    assert use_case.list_own(tenant_id=TENANT, employee=subject) == []


def test_list_for_employee_requires_hierarchy_for_non_self_viewer() -> None:
    subject = _employee(priority=RolePriority.EXECUTIVE)
    viewer = _employee(priority=RolePriority.STAFF)
    use_case, _, _, _ = _use_case(employees=[subject])

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        use_case.list_for_employee(tenant_id=TENANT, actor=viewer, employee_id=subject.id)


# --------------------------------------------------------------------------- #
# 6. MENYU — GÖRMƏK = SƏLAHİYYƏTİN OLMASI
# --------------------------------------------------------------------------- #


def test_menu_entry_is_gated_by_the_conduct_review_flag() -> None:
    from src.presentation.shell.menu import DEFAULT_ENTRIES

    entry = next(e for e in DEFAULT_ENTRIES if e.key == "performance_reviews")
    assert entry.required_flag == CONDUCT_PERFORMANCE_REVIEW_FLAG
