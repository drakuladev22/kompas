"""#19 Elan (Broadcast) — kompasos11.md Faza 8.

BAZA LAZIM DEYİL: bütün portlar sahtə obyektlərlə əvəz olunur.

──────────────────────────────────────────────────────────────────────────────
NƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
1. STORE-SCOPING — `STORE_LIST` elanı YALNIZ hədəf mağazanın işçisinə
   görünür, başqa mağazanın işçisinə GÖRÜNMÜR (`OpenShiftMarketUseCase.
   list_for_employee` ilə eyni prinsip, bax `Announcement.visible_to_store`).
2. `ALL` ƏHATƏSİ — hər mağazanın (və mağazası olmayan işçinin belə) işçisinə
   görünür.
3. SƏLAHİYYƏT — `can_broadcast_announcements` olmadan yayım BLOKLANIR.
4. ƏHATƏ ZİDDİYYƏTİ — `STORE_LIST` boş mağaza siyahısı ilə, `ALL` isə mağaza
   siyahısı ilə YARADILA BİLMƏZ (domen qaydası, `migrations/020` trigger-inin
   İKİNCİ yarısı).
5. BİR-TƏRƏFLİLİK — `AnnouncementUseCase`-də cavab/thread metodu YOXDUR
   (struktur sübutu: sinif imzasının özü).
6. GÖRÜNMƏ MÜDDƏTİ — `ANNOUNCEMENT_VISIBILITY_DAYS`-dən köhnə elan avtomatik
   gizlənir, LAKİN sətir aktiv qalır (soft-delete-dən müstəqil).
7. GERİ ÇƏKMƏ — soft delete, təkrar geri çəkmə rədd edilir.
8. BOŞ SİYAHI HALLARI — elan yoxdursa siyahı sükutla boş qayıdır (xəta yox).
9. AUDIT — yayım və geri çəkmə `audit_logs`-a düşür.

SAHTƏ: `InMemoryAnnouncements` BU FAYLDA təyin olunub (paylaşılan
`tests/fixtures/fakes.py` dəyişdirilmir, CLAUDE.md tapşırığı).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.application.use_cases.announcements import (
    BROADCAST_ANNOUNCEMENTS_FLAG,
    AnnouncementError,
    AnnouncementNotFoundError,
    AnnouncementUseCase,
)
from src.domain.entities.announcement import (
    Announcement,
    AnnouncementDraft,
    AnnouncementScope,
)
from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionEffect,
    RolePriority,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    AnnouncementId,
    EmployeeId,
    StoreId,
    TenantId,
    new_announcement_id,
)
from tests.fixtures.fakes import FakeClock, FakeSystemLimits, RecordingAudit

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
OTHER_TENANT = TenantId(uuid.uuid4())
STORE_A = StoreId(uuid.uuid4())
STORE_B = StoreId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Yerli sahtə — `announcements` + `announcement_targets`-in yaddaş versiyası
# --------------------------------------------------------------------------- #


class InMemoryAnnouncements:
    """`AnnouncementRepository`-nin yaddaş versiyası — SQL-in `EXISTS`
    süzgəcini (`Announcement.visible_to_store` vasitəsilə) Python-da təqlid edir.

    OXUMA HƏR DƏFƏ TƏZƏ OBYEKT QAYTARIR (`_hydrated`) — real Postgres
    repo-sunda `get()` HƏR sorğuda sətirdən YENİ `Announcement` qurur;
    çağıran tərəf həmin nüsxə üzərində domen metodu (`withdraw()`) çağırıb
    SONRA `repository.withdraw()`-u AYRICA çağırır. Sahtə `self.items`-dəki
    sətri BİRBAŞA qaytarsaydı, domen metodu artıq "saxlanmış" sətri
    sükutla dəyişdirərdi və `repository.withdraw()`-un ŞƏRTLİ yoxlaması
    (`is_active`) HƏMİŞƏ yalan görünərdi — `InMemoryOpenShiftPostings.
    _hydrate` ilə EYNİ qərar (`tests/unit/test_open_shift_market.py`).
    """

    def __init__(self) -> None:
        self.items: dict[AnnouncementId, Announcement] = {}

    def get(self, tenant_id: TenantId, announcement_id: AnnouncementId) -> Announcement | None:
        item = self.items.get(announcement_id)
        if item is None or item.tenant_id != tenant_id:
            return None
        return _hydrate(item)

    def list_recent(self, tenant_id: TenantId, *, limit: int = 50) -> list[Announcement]:
        rows = [_hydrate(item) for item in self.items.values() if item.tenant_id == tenant_id]
        rows.sort(key=lambda item: item.created_at, reverse=True)
        return rows[:limit]

    def list_visible_for_store(
        self, tenant_id: TenantId, store_id: StoreId | None, *, created_after: datetime
    ) -> list[Announcement]:
        return [
            _hydrate(item)
            for item in self.items.values()
            if item.tenant_id == tenant_id
            and item.is_active
            and item.created_at >= created_after
            and item.visible_to_store(store_id)
        ]

    def post(self, record: Announcement) -> None:
        self.items[record.id] = record

    def withdraw(
        self,
        *,
        tenant_id: TenantId,
        announcement_id: AnnouncementId,
        deactivated_by: EmployeeId,
        deactivated_at: datetime,
    ) -> bool:
        item = self.items.get(announcement_id)
        if item is None or item.tenant_id != tenant_id or not item.is_active:
            return False
        item.is_active = False
        item.deactivated_at = deactivated_at
        item.deactivated_by = deactivated_by
        item.updated_at = deactivated_at
        return True


def _hydrate(item: Announcement) -> Announcement:
    """`get`/`list_*`-in BƏRPA yolu — hadisə YAYMIR (`emit_created_event=False`)."""
    return Announcement(
        announcement_id=item.id,
        tenant_id=item.tenant_id,
        created_by=item.created_by,
        title_az=item.title_az,
        message=item.message,
        scope=item.scope,
        target_store_ids=item.target_store_ids,
        created_at=item.created_at,
        updated_at=item.updated_at,
        is_active=item.is_active,
        deactivated_at=item.deactivated_at,
        deactivated_by=item.deactivated_by,
        emit_created_event=False,
    )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee(
    *,
    priority: RolePriority = RolePriority.OPERATIONAL,
    flags: tuple[str, ...] = (BROADCAST_ANNOUNCEMENTS_FLAG,),
    tenant_id: TenantId = TENANT,
    store_id: StoreId | None = None,
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
        store_id=store_id,
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
    *, limits: dict[str, str] | None = None
) -> tuple[AnnouncementUseCase, InMemoryAnnouncements, RecordingAudit]:
    repository = InMemoryAnnouncements()
    audit = RecordingAudit()
    use_case = AnnouncementUseCase(
        announcements=repository,
        limits=FakeSystemLimits(limits),
        audit=audit,
        clock=FakeClock(NOW),
    )
    return use_case, repository, audit


def _draft(
    *,
    scope: AnnouncementScope = AnnouncementScope.ALL,
    store_ids: frozenset[StoreId] = frozenset(),
    title: str = "Bayram iş qrafiki",
    message: str = "20-22 Avqust tarixlərində iş saatları dəyişdirilib.",
) -> AnnouncementDraft:
    return AnnouncementDraft(title_az=title, message=message, scope=scope, store_ids=store_ids)


# --------------------------------------------------------------------------- #
# 1. AQREQAT — ƏHATƏ ZİDDİYYƏTİ (domen qaydası)
# --------------------------------------------------------------------------- #


def test_store_list_scope_without_stores_is_rejected() -> None:
    with pytest.raises(DomainRuleError, match="STORE_LIST"):
        Announcement(
            announcement_id=new_announcement_id(),
            tenant_id=TENANT,
            created_by=EmployeeId(uuid.uuid4()),
            title_az="Başlıq",
            message="Kifayət qədər uzun mətn",
            scope=AnnouncementScope.STORE_LIST,
            target_store_ids=frozenset(),
            created_at=NOW,
            updated_at=NOW,
        )


def test_all_scope_with_stores_is_rejected() -> None:
    with pytest.raises(DomainRuleError, match="ALL"):
        Announcement(
            announcement_id=new_announcement_id(),
            tenant_id=TENANT,
            created_by=EmployeeId(uuid.uuid4()),
            title_az="Başlıq",
            message="Kifayət qədər uzun mətn",
            scope=AnnouncementScope.ALL,
            target_store_ids=frozenset({STORE_A}),
            created_at=NOW,
            updated_at=NOW,
        )


def test_short_title_is_rejected() -> None:
    with pytest.raises(DomainRuleError, match="minimum"):
        Announcement(
            announcement_id=new_announcement_id(),
            tenant_id=TENANT,
            created_by=EmployeeId(uuid.uuid4()),
            title_az="Aa",
            message="Kifayət qədər uzun mətn",
            scope=AnnouncementScope.ALL,
            target_store_ids=frozenset(),
            created_at=NOW,
            updated_at=NOW,
        )


def test_withdraw_is_not_reentrant() -> None:
    announcement = Announcement(
        announcement_id=new_announcement_id(),
        tenant_id=TENANT,
        created_by=EmployeeId(uuid.uuid4()),
        title_az="Başlıq",
        message="Kifayət qədər uzun mətn",
        scope=AnnouncementScope.ALL,
        target_store_ids=frozenset(),
        created_at=NOW,
        updated_at=NOW,
    )
    announcement.withdraw(deactivated_by=EmployeeId(uuid.uuid4()), now=NOW)
    with pytest.raises(InvalidStateTransitionError):
        announcement.withdraw(deactivated_by=EmployeeId(uuid.uuid4()), now=NOW)


# --------------------------------------------------------------------------- #
# 2. USE CASE — SƏLAHİYYƏT
# --------------------------------------------------------------------------- #


def test_broadcast_without_flag_is_blocked_not_silently_ignored() -> None:
    use_case, repository, audit = _use_case()
    actor = _employee(flags=())

    with pytest.raises(AuthorizationError, match=BROADCAST_ANNOUNCEMENTS_FLAG):
        use_case.broadcast(tenant_id=TENANT, actor=actor, draft=_draft())

    assert repository.items == {}
    assert audit.entries == []


def test_broadcast_from_another_tenant_is_rejected() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(tenant_id=OTHER_TENANT)

    with pytest.raises(AuthorizationError, match="kirayəçiyə aid deyil"):
        use_case.broadcast(tenant_id=TENANT, actor=actor, draft=_draft())


def test_list_recent_requires_the_flag() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(flags=())

    with pytest.raises(AuthorizationError, match=BROADCAST_ANNOUNCEMENTS_FLAG):
        use_case.list_recent(tenant_id=TENANT, actor=actor)


# --------------------------------------------------------------------------- #
# 3. STORE-SCOPING — MÖVCUD NAXIŞIN TƏTBİQİ
# --------------------------------------------------------------------------- #


def test_store_list_announcement_is_visible_only_to_target_store_employee() -> None:
    use_case, _, _ = _use_case()
    admin = _employee()
    use_case.broadcast(
        tenant_id=TENANT,
        actor=admin,
        draft=_draft(scope=AnnouncementScope.STORE_LIST, store_ids=frozenset({STORE_A})),
    )

    in_target_store = _employee(store_id=STORE_A)
    in_other_store = _employee(store_id=STORE_B)

    visible = use_case.list_for_employee(tenant_id=TENANT, employee=in_target_store)
    hidden = use_case.list_for_employee(tenant_id=TENANT, employee=in_other_store)

    assert len(visible) == 1
    assert hidden == []


def test_store_list_announcement_is_hidden_from_employee_without_a_store() -> None:
    """FAIL-CLOSED: mağazası olmayan işçi `STORE_LIST` elanını GÖRMÜR."""
    use_case, _, _ = _use_case()
    admin = _employee()
    use_case.broadcast(
        tenant_id=TENANT,
        actor=admin,
        draft=_draft(scope=AnnouncementScope.STORE_LIST, store_ids=frozenset({STORE_A})),
    )

    storeless = _employee(store_id=None)
    assert use_case.list_for_employee(tenant_id=TENANT, employee=storeless) == []


def test_all_scope_is_visible_to_every_store_and_storeless_employee() -> None:
    use_case, _, _ = _use_case()
    admin = _employee()
    use_case.broadcast(tenant_id=TENANT, actor=admin, draft=_draft(scope=AnnouncementScope.ALL))

    for candidate in (
        _employee(store_id=STORE_A),
        _employee(store_id=STORE_B),
        _employee(store_id=None),
    ):
        views = use_case.list_for_employee(tenant_id=TENANT, employee=candidate)
        assert len(views) == 1
        assert views[0].scope == AnnouncementScope.ALL.value


def test_announcement_from_another_tenant_is_not_visible() -> None:
    use_case, repository, _ = _use_case()
    admin = _employee()
    use_case.broadcast(tenant_id=TENANT, actor=admin, draft=_draft(scope=AnnouncementScope.ALL))

    other_tenant_employee = _employee(tenant_id=OTHER_TENANT, store_id=STORE_A)
    assert use_case.list_for_employee(tenant_id=OTHER_TENANT, employee=other_tenant_employee) == []
    assert len(repository.items) == 1  # sətir SİLİNMƏYİB, yalnız görünmür


# --------------------------------------------------------------------------- #
# 4. GÖRÜNMƏ MÜDDƏTİ (ROOT parametri)
# --------------------------------------------------------------------------- #


def test_old_announcement_is_hidden_after_the_visibility_window() -> None:
    repository = InMemoryAnnouncements()
    audit = RecordingAudit()
    clock = FakeClock(NOW)
    use_case = AnnouncementUseCase(
        announcements=repository,
        limits=FakeSystemLimits({SystemLimitKey.ANNOUNCEMENT_VISIBILITY_DAYS.value: "7"}),
        audit=audit,
        clock=clock,
    )
    admin = _employee()
    use_case.broadcast(tenant_id=TENANT, actor=admin, draft=_draft(scope=AnnouncementScope.ALL))

    clock.set(NOW + timedelta(days=8))
    viewer = _employee(store_id=STORE_A)
    assert use_case.list_for_employee(tenant_id=TENANT, employee=viewer) == []

    # Sətir hələ AKTİVDİR (soft delete DEYİL) — admin panelində görünməyə davam edir.
    recent = use_case.list_recent(tenant_id=TENANT, actor=admin)
    assert len(recent) == 1
    assert recent[0].is_active is True


def test_visibility_window_zero_means_unbounded() -> None:
    repository = InMemoryAnnouncements()
    audit = RecordingAudit()
    clock = FakeClock(NOW)
    use_case = AnnouncementUseCase(
        announcements=repository,
        limits=FakeSystemLimits({SystemLimitKey.ANNOUNCEMENT_VISIBILITY_DAYS.value: "0"}),
        audit=audit,
        clock=clock,
    )
    admin = _employee()
    use_case.broadcast(tenant_id=TENANT, actor=admin, draft=_draft(scope=AnnouncementScope.ALL))

    clock.set(NOW + timedelta(days=3650))
    viewer = _employee(store_id=STORE_A)
    assert len(use_case.list_for_employee(tenant_id=TENANT, employee=viewer)) == 1


# --------------------------------------------------------------------------- #
# 5. GERİ ÇƏKMƏ VƏ AUDIT
# --------------------------------------------------------------------------- #


def test_withdraw_hides_announcement_from_employee_view() -> None:
    use_case, _, _ = _use_case()
    admin = _employee()
    announcement = use_case.broadcast(
        tenant_id=TENANT, actor=admin, draft=_draft(scope=AnnouncementScope.ALL)
    )

    viewer = _employee(store_id=STORE_A)
    assert len(use_case.list_for_employee(tenant_id=TENANT, employee=viewer)) == 1

    use_case.withdraw(tenant_id=TENANT, actor=admin, announcement_id=announcement.id)

    assert use_case.list_for_employee(tenant_id=TENANT, employee=viewer) == []


def test_withdraw_twice_is_rejected() -> None:
    use_case, _, _ = _use_case()
    admin = _employee()
    announcement = use_case.broadcast(
        tenant_id=TENANT, actor=admin, draft=_draft(scope=AnnouncementScope.ALL)
    )
    use_case.withdraw(tenant_id=TENANT, actor=admin, announcement_id=announcement.id)

    with pytest.raises((AnnouncementError, InvalidStateTransitionError)):
        use_case.withdraw(tenant_id=TENANT, actor=admin, announcement_id=announcement.id)


def test_withdraw_unknown_announcement_raises_not_found() -> None:
    use_case, _, _ = _use_case()
    admin = _employee()

    with pytest.raises(AnnouncementNotFoundError):
        use_case.withdraw(
            tenant_id=TENANT, actor=admin, announcement_id=AnnouncementId(uuid.uuid4())
        )


def test_broadcast_and_withdraw_write_audit_entries() -> None:
    use_case, _, audit = _use_case()
    admin = _employee()
    announcement = use_case.broadcast(
        tenant_id=TENANT, actor=admin, draft=_draft(scope=AnnouncementScope.ALL)
    )
    use_case.withdraw(tenant_id=TENANT, actor=admin, announcement_id=announcement.id)

    assert audit.actions() == ["ANNOUNCEMENT_BROADCAST", "ANNOUNCEMENT_WITHDRAWN"]
    assert audit.entries[0]["after_state"]["scope"] == "ALL"
    assert audit.entries[1]["after_state"]["is_active"] is False


# --------------------------------------------------------------------------- #
# 6. BOŞ SİYAHI HALLARI
# --------------------------------------------------------------------------- #


def test_list_for_employee_is_empty_when_no_announcements_exist() -> None:
    use_case, _, _ = _use_case()
    viewer = _employee(store_id=STORE_A)
    assert use_case.list_for_employee(tenant_id=TENANT, employee=viewer) == []


def test_list_recent_is_empty_when_no_announcements_exist() -> None:
    use_case, _, _ = _use_case()
    admin = _employee()
    assert use_case.list_recent(tenant_id=TENANT, actor=admin) == []


# --------------------------------------------------------------------------- #
# 7. BİR-TƏRƏFLİLİK (struktur sübutu)
# --------------------------------------------------------------------------- #


def test_use_case_has_no_reply_or_thread_capability() -> None:
    """kompasos11.md Faza 8: "dəstək çat-dən FƏRQLİ, bir-tərəflidir, cavab yoxdur".

    Bu, sinifin ictimai API-sini yoxlayan struktur testdir — reply/thread/
    reaction metodu ƏLAVƏ EDİLƏRSƏ bu test dərhal uğursuz olmalıdır.
    """
    public_methods = {
        name
        for name in dir(AnnouncementUseCase)
        if not name.startswith("_") and callable(getattr(AnnouncementUseCase, name))
    }
    forbidden = {"reply", "mark_read", "react", "thread", "comment"}
    assert not (public_methods & forbidden), (
        f"Elan bir-tərəflidir — {public_methods & forbidden} scope pozuntusudur"
    )


# --------------------------------------------------------------------------- #
# 8. MENYU — GÖRMƏK = SƏLAHİYYƏTİN OLMASI
# --------------------------------------------------------------------------- #


def test_menu_entry_is_gated_by_the_broadcast_flag() -> None:
    from src.presentation.shell.menu import DEFAULT_ENTRIES

    entry = next(e for e in DEFAULT_ENTRIES if e.key == "announcements")
    assert entry.required_flag == BROADCAST_ANNOUNCEMENTS_FLAG
