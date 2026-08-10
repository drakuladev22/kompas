"""Aylıq Cərimə İcmalı + İşçi Detal Paneli testləri (qərar dəyişikliyi).

Tələbin YOXLAMA bölmələrindəki hər bənd burada yoxlanılır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from src.application.use_cases.employee_profile import (
    VIEW_EMPLOYEE_REPORTS_FLAG,
    EmployeeProfileAccessUseCase,
    ProfileAccessDeniedError,
    visible_employee_ids,
)
from src.application.use_cases.fine_review import (
    PUBLISH_FINES_FLAG,
    FineDecision,
    FineReviewError,
    MonthlyFineReviewUseCase,
    ReviewDecision,
)
from src.domain.entities import Employee, Fine, FineSource, FineStatus, Position
from src.domain.entities.base import DomainRuleError
from src.domain.value_objects import (
    AuthorizationError,
    Money,
    PermissionFlag,
    SystemRole,
    Username,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FineId,
    FineTypeId,
    PositionId,
    StoreId,
    TenantId,
)
from tests.fixtures.fakes import FakeClock, RecordingAudit, RecordingNotifier

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE_A = StoreId(uuid.uuid4())
STORE_B = StoreId(uuid.uuid4())
OPERATOR = EmployeeId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())

CREATED = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
#: Nəşr yaradılışdan 4 HƏFTƏ sonra — icmalın real gecikməsi.
PUSHED = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)


def make_position(role: SystemRole, *flags: str) -> Position:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for code in flags:
        position.grant(PermissionFlag(code=code, category="HR"))
    return position


def make_employee(
    role: SystemRole,
    *flags: str,
    store_id: StoreId | None = STORE_A,
    employee_id: EmployeeId | None = None,
    birth: date | None = None,
) -> Employee:
    return Employee(
        employee_id=employee_id or EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=make_position(role, *flags),
        first_name="Test",
        last_name=role.value,
        store_id=store_id,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
        date_of_birth=birth,
    )


def make_fine(*, store_id: StoreId = STORE_A, created: datetime = CREATED) -> Fine:
    return Fine(
        fine_id=FineId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=store_id,
        source=FineSource.MANUAL_CAMERA,
        amount=Money.parse("25.00"),
        issued_at=created,
        fine_type_id=FineTypeId(uuid.uuid4()),
        issued_by=OPERATOR,
        photo_evidence_url="https://storage/evidence.jpg",
    )


@pytest.fixture
def review_uc() -> tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier]:
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    use_case = MonthlyFineReviewUseCase(
        clock=FakeClock(PUSHED),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
    )
    return use_case, audit, notifier


# --------------------------------------------------------------------------- #
# 1. PENDING_REVIEW heç bir işçi-görünüşündə görünmür
# --------------------------------------------------------------------------- #


def test_new_fine_is_not_visible_to_employee() -> None:
    fine = make_fine()

    assert fine.status is FineStatus.PENDING_REVIEW
    assert fine.is_visible_to_employee is False


def test_employee_view_filters_out_pending_fines(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    use_case, _, _ = review_uc
    pending = make_fine()
    published = make_fine()
    published.publish(reviewed_by=EmployeeId(uuid.uuid4()), published_at=PUSHED)

    visible = use_case.visible_to_employee([pending, published])

    assert visible == [published]


def test_camera_operator_sees_own_pending_fines(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    """İSTİSNA: operatorun öz fəaliyyət jurnalı statusdan asılı deyil."""
    use_case, _, _ = review_uc
    own = make_fine()

    recorded = use_case.recorded_by_operator([own], OPERATOR)

    assert recorded == [own]
    assert own.is_visible_to_employee is False


def test_pending_fine_cannot_be_appealed() -> None:
    """İşçi görmədiyi cəriməyə etiraz edə bilməz."""
    fine = make_fine()

    with pytest.raises(DomainRuleError, match="nəşr olunmuş cərimə"):
        fine.reverse(
            decided_by=EmployeeId(uuid.uuid4()),
            decided_at=PUSHED,
            reason="Etiraz təsdiqləndi tam",
        )


# --------------------------------------------------------------------------- #
# 2. published_at yalnız push anında dolur
# --------------------------------------------------------------------------- #


def test_published_at_is_empty_before_push() -> None:
    fine = make_fine()

    assert fine.published_at is None
    assert fine.appeal_window_closes_at is None


def test_published_at_can_be_weeks_after_created_at(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    use_case, _, _ = review_uc
    actor = make_employee(SystemRole.HR_ADMIN, PUBLISH_FINES_FLAG)
    fine = make_fine(created=CREATED)

    use_case.publish_batch(
        actor=actor,
        tenant_id=TENANT,
        review_month="2026-08",
        fines={fine.id: fine},
        decisions=[],
    )

    assert fine.issued_at == CREATED
    assert fine.published_at == PUSHED
    assert (fine.published_at - fine.issued_at) > timedelta(days=27)


# --------------------------------------------------------------------------- #
# 3. 72 saat `published_at`-dan hesablanır — ƏSAS DÜZƏLİŞ
# --------------------------------------------------------------------------- #


def test_appeal_window_starts_at_publish_not_creation() -> None:
    fine = make_fine(created=CREATED)
    fine.publish(reviewed_by=EmployeeId(uuid.uuid4()), published_at=PUSHED)

    assert fine.appeal_window_closes_at == PUSHED + timedelta(hours=72)
    # Yaradılışdan 72 saat sonra pəncərə HƏLƏ AÇIQDIR.
    assert fine.is_appeal_window_open(now=CREATED + timedelta(hours=73)) is True
    # Nəşrdən 71 saat sonra açıq, 73 saat sonra bağlı.
    assert fine.is_appeal_window_open(now=PUSHED + timedelta(hours=71)) is True
    assert fine.is_appeal_window_open(now=PUSHED + timedelta(hours=73)) is False


def test_unpublished_fine_window_counts_as_open() -> None:
    """Nəşr olunmamış cərimənin pəncərəsi "bağlanmış" sayılsaydı export açılardı."""
    fine = make_fine(created=CREATED)

    assert fine.is_appeal_window_open(now=CREATED + timedelta(days=365)) is True


# --------------------------------------------------------------------------- #
# 4. Export PENDING_REVIEW-i HEÇ VAXT daxil etmir
# --------------------------------------------------------------------------- #


def test_pending_fine_is_never_exportable_even_after_months() -> None:
    fine = make_fine(created=CREATED)

    assert fine.is_exportable(now=CREATED + timedelta(days=180)) is False


def test_fine_pushed_on_first_of_month_misses_that_month_export() -> None:
    """Tələbdəki GÖZLƏNİLƏN davranış: sentyabrın 1-də push → sentyabr export-una düşmür."""
    fine = make_fine(created=datetime(2026, 8, 20, 10, 0, tzinfo=UTC))
    pushed = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    fine.publish(reviewed_by=EmployeeId(uuid.uuid4()), published_at=pushed)

    # Sentyabrın 2-də (həmin ayın export günü) 72 saat hələ keçməyib.
    assert fine.is_exportable(now=datetime(2026, 9, 2, 10, 0, tzinfo=UTC)) is False
    # Oktyabrın 1-də (növbəti ay) düşür.
    assert fine.is_exportable(now=datetime(2026, 10, 1, 10, 0, tzinfo=UTC)) is True


def test_discarded_fine_is_never_exportable() -> None:
    fine = make_fine()
    fine.discard_in_review(
        reviewed_by=EmployeeId(uuid.uuid4()),
        reviewed_at=PUSHED,
        reason="Operator səhvən qeyd edib",
    )

    assert fine.status is FineStatus.REVERSED
    assert fine.amount == Money.zero()
    assert fine.is_exportable(now=PUSHED + timedelta(days=30)) is False


# --------------------------------------------------------------------------- #
# Kütləvi nəşr
# --------------------------------------------------------------------------- #


def test_publish_batch_applies_keep_and_discard(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    use_case, audit, notifier = review_uc
    actor = make_employee(SystemRole.HR_ADMIN, PUBLISH_FINES_FLAG)
    keep = make_fine(store_id=STORE_A)
    drop = make_fine(store_id=STORE_B)

    result = use_case.publish_batch(
        actor=actor,
        tenant_id=TENANT,
        review_month="2026-08",
        fines={keep.id: keep, drop.id: drop},
        decisions=[
            FineDecision(
                fine_id=drop.id, decision=ReviewDecision.DISCARD, reason="Səhv qeyd edilib"
            )
        ],
    )

    assert result.published == [keep.id]
    assert result.discarded == [drop.id]
    assert keep.status is FineStatus.PUBLISHED
    assert drop.status is FineStatus.REVERSED
    assert "MONTHLY_FINES_PUBLISHED" in audit.actions()
    assert len(notifier.messages) == 1


def test_default_decision_is_keep(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    """UI defoltu "Saxla"-dır — qərar verilməyən sətir nəşr olunur."""
    use_case, _, _ = review_uc
    actor = make_employee(SystemRole.CEO, PUBLISH_FINES_FLAG)
    fine = make_fine()

    result = use_case.publish_batch(
        actor=actor,
        tenant_id=TENANT,
        review_month="2026-08",
        fines={fine.id: fine},
        decisions=[],
    )

    assert result.published == [fine.id]


def test_discard_requires_reason(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    use_case, _, _ = review_uc
    actor = make_employee(SystemRole.HR_ADMIN, PUBLISH_FINES_FLAG)
    fine = make_fine()

    with pytest.raises(FineReviewError, match="səbəb"):
        use_case.publish_batch(
            actor=actor,
            tenant_id=TENANT,
            review_month="2026-08",
            fines={fine.id: fine},
            decisions=[
                FineDecision(fine_id=fine.id, decision=ReviewDecision.DISCARD, reason="qısa")
            ],
        )


def test_publish_requires_flag(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    use_case, _, _ = review_uc
    actor = make_employee(SystemRole.HR_ADMIN)  # flag YOXDUR
    fine = make_fine()

    with pytest.raises(FineReviewError, match="səlahiyyəti"):
        use_case.publish_batch(
            actor=actor,
            tenant_id=TENANT,
            review_month="2026-08",
            fines={fine.id: fine},
            decisions=[],
        )
    assert fine.status is FineStatus.PENDING_REVIEW


def test_decision_for_unknown_fine_is_rejected(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    """İcmalda olmayan cərimə üçün qərar — səhv/manipulyasiya əlaməti."""
    use_case, _, _ = review_uc
    actor = make_employee(SystemRole.ROOT, PUBLISH_FINES_FLAG)
    fine = make_fine()

    with pytest.raises(FineReviewError, match="İcmalda olmayan"):
        use_case.publish_batch(
            actor=actor,
            tenant_id=TENANT,
            review_month="2026-08",
            fines={fine.id: fine},
            decisions=[FineDecision(fine_id=FineId(uuid.uuid4()))],
        )


def test_already_published_fine_is_not_republished(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier],
) -> None:
    use_case, _, _ = review_uc
    actor = make_employee(SystemRole.ROOT, PUBLISH_FINES_FLAG)
    already = make_fine()
    already.publish(reviewed_by=actor.id, published_at=CREATED)

    with pytest.raises(FineReviewError, match="Nəşr gözləyən cərimə yoxdur"):
        use_case.publish_batch(
            actor=actor,
            tenant_id=TENANT,
            review_month="2026-08",
            fines={already.id: already},
            decisions=[],
        )
    assert already.published_at == CREATED


@pytest.mark.parametrize("bad", ["2026-13", "26-08", "2026/08", "avqust", ""])
def test_invalid_review_month_rejected(
    review_uc: tuple[MonthlyFineReviewUseCase, RecordingAudit, RecordingNotifier], bad: str
) -> None:
    use_case, _, _ = review_uc
    actor = make_employee(SystemRole.ROOT, PUBLISH_FINES_FLAG)

    with pytest.raises(FineReviewError, match="YYYY-MM"):
        use_case.publish_batch(
            actor=actor, tenant_id=TENANT, review_month=bad, fines={}, decisions=[]
        )


# --------------------------------------------------------------------------- #
# `can_publish_fines` HARDLOCK
# --------------------------------------------------------------------------- #


def test_publish_flag_cannot_be_granted_to_store_manager() -> None:
    flag = PermissionFlag(
        code=PUBLISH_FINES_FLAG,
        category="KAMERA_CERIME",
        is_anti_fraud=True,
        excludes_camera_role=True,
    )

    with pytest.raises(AuthorizationError, match="ANTI-FRAUD"):
        flag.assert_grantable_to(SystemRole.STORE_MANAGER)


def test_publish_flag_cannot_be_granted_to_camera_operator() -> None:
    """Cərimə YARADAN ilə TƏSDİQ EDƏN eyni şəxs ola bilməz."""
    flag = PermissionFlag(
        code=PUBLISH_FINES_FLAG,
        category="KAMERA_CERIME",
        is_anti_fraud=True,
        excludes_camera_role=True,
    )

    with pytest.raises(AuthorizationError, match="kamera-tipli"):
        flag.assert_grantable_to(SystemRole.CAMERA_OPERATOR)


def test_publish_flag_cannot_be_granted_to_custom_camera_type_role() -> None:
    """Custom "kamera-tipli" rol da bloklanmalıdır — arxa qapı qalmasın."""
    flag = PermissionFlag(
        code=PUBLISH_FINES_FLAG,
        category="KAMERA_CERIME",
        is_anti_fraud=True,
        excludes_camera_role=True,
    )

    with pytest.raises(AuthorizationError, match="kamera-tipli"):
        flag.assert_grantable_to(SystemRole.ADMIN, is_camera_type_role=True)


def test_publish_flag_is_grantable_to_hr_admin() -> None:
    flag = PermissionFlag(
        code=PUBLISH_FINES_FLAG,
        category="KAMERA_CERIME",
        is_anti_fraud=True,
        excludes_camera_role=True,
    )

    flag.assert_grantable_to(SystemRole.HR_ADMIN)  # istisna atmamalıdır


def test_camera_only_and_excludes_camera_together_is_a_dead_flag() -> None:
    """Heç bir rola verilə bilməyən flag sükutla ölü qalardı."""
    with pytest.raises(ValueError, match="eyni anda"):
        PermissionFlag(
            code="can_impossible",
            category="X",
            is_anti_fraud=True,
            is_camera_only=True,
            excludes_camera_role=True,
        )


# --------------------------------------------------------------------------- #
# İşçi Detal Paneli — icazə qaydası
# --------------------------------------------------------------------------- #


@pytest.fixture
def profile_uc() -> EmployeeProfileAccessUseCase:
    return EmployeeProfileAccessUseCase(clock=FakeClock(PUSHED))  # type: ignore[arg-type]


def test_seller_can_open_own_profile_without_any_flag(
    profile_uc: EmployeeProfileAccessUseCase,
) -> None:
    seller = make_employee(SystemRole.SELLER, birth=date(1998, 5, 12))

    view = profile_uc.build_view(viewer=seller, subject=seller)

    assert view.is_self is True
    assert view.date_of_birth == date(1998, 5, 12)


def test_seller_cannot_open_another_profile(
    profile_uc: EmployeeProfileAccessUseCase,
) -> None:
    seller = make_employee(SystemRole.SELLER)
    other = make_employee(SystemRole.SELLER)

    assert profile_uc.can_view(viewer=seller, subject=other) is False
    with pytest.raises(ProfileAccessDeniedError):
        profile_uc.build_view(viewer=seller, subject=other)


def test_camera_operator_cannot_open_profiles_from_the_queue(
    profile_uc: EmployeeProfileAccessUseCase,
) -> None:
    """Növbədə adı görmək ≠ şəxsi məlumatı görmək."""
    operator = make_employee(SystemRole.CAMERA_OPERATOR)
    worker = make_employee(SystemRole.SELLER)

    assert profile_uc.can_view(viewer=operator, subject=worker) is False


def test_store_manager_sees_own_store_employee(
    profile_uc: EmployeeProfileAccessUseCase,
) -> None:
    manager = make_employee(SystemRole.STORE_MANAGER, VIEW_EMPLOYEE_REPORTS_FLAG, store_id=STORE_A)
    worker = make_employee(SystemRole.SELLER, store_id=STORE_A)

    assert profile_uc.can_view(viewer=manager, subject=worker) is True


def test_store_manager_is_denied_other_store_employee(
    profile_uc: EmployeeProfileAccessUseCase,
) -> None:
    """Lider-lövhədə başqa mağazanın adı görünə bilər — profili YOX."""
    manager = make_employee(SystemRole.STORE_MANAGER, VIEW_EMPLOYEE_REPORTS_FLAG, store_id=STORE_A)
    worker = make_employee(SystemRole.SELLER, store_id=STORE_B)

    assert profile_uc.can_view(viewer=manager, subject=worker) is False
    with pytest.raises(ProfileAccessDeniedError):
        profile_uc.build_view(viewer=manager, subject=worker)


def test_store_manager_can_always_see_self_even_without_store(
    profile_uc: EmployeeProfileAccessUseCase,
) -> None:
    manager = make_employee(SystemRole.STORE_MANAGER, VIEW_EMPLOYEE_REPORTS_FLAG, store_id=None)

    assert profile_uc.can_view(viewer=manager, subject=manager) is True


@pytest.mark.parametrize(
    "role", [SystemRole.HR_ADMIN, SystemRole.ADMIN, SystemRole.CEO, SystemRole.ROOT]
)
def test_company_wide_roles_see_any_store(
    profile_uc: EmployeeProfileAccessUseCase, role: SystemRole
) -> None:
    viewer = make_employee(role, VIEW_EMPLOYEE_REPORTS_FLAG, store_id=STORE_A)
    worker = make_employee(SystemRole.SELLER, store_id=STORE_B)

    assert profile_uc.can_view(viewer=viewer, subject=worker) is True


def test_birthday_is_exposed_only_with_access(
    profile_uc: EmployeeProfileAccessUseCase,
) -> None:
    """Həssas sahə sorğu qatında süzülür, təkcə UI-da gizlədilmir."""
    hr = make_employee(SystemRole.HR_ADMIN, VIEW_EMPLOYEE_REPORTS_FLAG)
    worker = make_employee(SystemRole.SELLER, birth=date(1995, 1, 20))

    assert profile_uc.build_view(viewer=hr, subject=worker).date_of_birth == date(1995, 1, 20)

    seller = make_employee(SystemRole.SELLER)
    with pytest.raises(ProfileAccessDeniedError):
        profile_uc.build_view(viewer=seller, subject=worker)


def test_clickable_names_are_precomputed_for_lists() -> None:
    """UI kliklənən, sonra "icazəniz yoxdur" deyən ad göstərməməlidir."""
    manager = make_employee(SystemRole.STORE_MANAGER, VIEW_EMPLOYEE_REPORTS_FLAG, store_id=STORE_A)
    same_store = make_employee(SystemRole.SELLER, store_id=STORE_A)
    other_store = make_employee(SystemRole.SELLER, store_id=STORE_B)

    clickable = visible_employee_ids(
        viewer=manager, candidates=[manager, same_store, other_store], now=PUSHED
    )

    assert str(same_store.id) in clickable
    assert str(other_store.id) not in clickable
    assert str(manager.id) in clickable


def test_seller_list_only_contains_self() -> None:
    seller = make_employee(SystemRole.SELLER)
    other = make_employee(SystemRole.SELLER)

    clickable = visible_employee_ids(viewer=seller, candidates=[seller, other], now=PUSHED)

    assert clickable == [str(seller.id)]
