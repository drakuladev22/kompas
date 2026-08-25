"""Sistem davamlılığı — `v2backlog.md` Faza 5 (5.1–5.4).

──────────────────────────────────────────────────────────────────────────────
BU QAPININ SUALLARI
──────────────────────────────────────────────────────────────────────────────
Hər bölmə funksiyanın «əsas iddiasını» sınayır, metodların siyahısını yox:

  5.1 — hədd aşılanda XƏBƏRDARLIQ olur, GİRİŞ dayanmır; təkrar-susma
        pəncərəsi prosesin yenidən başlamasından SAĞ ÇIXIR.
  5.2 — RAM ölçüsü oxunmayanda metrik «hər şey qaydasında» DEMİR.
  5.3 — təhvil qeydi növbəti işçiyə görünür, ÖZ müəllifinə yox; görünmə
        pəncərəsi Root dəyişikliyini DƏRHAL izləyir.
  5.4 — dörd struktur zəmanət: əvvəlcədən təyinat, ikinci şəxs, vaxt həddi,
        aylıq tavan. Hər biri AYRICA test ilə.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.application.use_cases.break_glass import (
    APPROVE_BREAK_GLASS_FLAG,
    MANAGE_BREAK_GLASS_FLAG,
    BreakGlassError,
    BreakGlassPermissionError,
    BreakGlassUseCase,
)
from src.application.use_cases.shift_handoff import (
    ShiftHandoffError,
    ShiftHandoffUseCase,
)
from src.domain.entities.base import DomainRuleError
from src.domain.entities.break_glass import (
    BreakGlassGrant,
    BreakGlassStatus,
    BreakGlassTrustee,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.entities.shift_handoff import ShiftHandoffNote
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    BreakGlassGrantId,
    EmployeeId,
    ShiftHandoffNoteId,
    StoreId,
    TenantId,
    new_break_glass_trustee_id,
    new_shift_handoff_note_id,
)
from src.infrastructure.erp.system_health import HealthLevel, memory_metric
from src.infrastructure.offline.backlog import OfflineBacklogMonitor
from tests.fixtures.fakes import FakeClock, FakeSystemLimits, RecordingAudit, RecordingNotifier

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Ortaq köməkçilər
# --------------------------------------------------------------------------- #


def _employee(
    *,
    code: str = "SATICI",
    priority: RolePriority = RolePriority.STAFF,
    flags: tuple[str, ...] = (),
    store_id: StoreId | None = STORE,
) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=Position(
            position_id=uuid.uuid4(),  # type: ignore[arg-type]
            code=code,
            name_az=code.title(),
            priority=priority,
            tenant_id=TENANT,
            is_system=True,
        ),
        first_name="Ad",
        last_name="Soyad",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
        store_id=store_id,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


class _Handoffs:
    """`ShiftHandoffRepository` sahtəsi."""

    def __init__(self) -> None:
        self.rows: dict[ShiftHandoffNoteId, ShiftHandoffNote] = {}

    def get(self, note_id: ShiftHandoffNoteId) -> ShiftHandoffNote | None:
        return self.rows.get(note_id)

    def list_open_for_store(
        self, tenant_id: TenantId, store_id: StoreId, *, limit: int
    ) -> list[ShiftHandoffNote]:
        rows = [
            row
            for row in self.rows.values()
            if row.tenant_id == tenant_id and row.store_id == store_id and not row.is_acknowledged
        ]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows[:limit]

    def save(self, note: ShiftHandoffNote) -> None:
        self.rows[note.id] = note


class _Grants:
    """`BreakGlassRepository` sahtəsi — reyestr + qrantlar."""

    def __init__(self) -> None:
        self.trustees: list[BreakGlassTrustee] = []
        self.grants: dict[BreakGlassGrantId, BreakGlassGrant] = {}

    def active_trustees(self, tenant_id: TenantId) -> list[BreakGlassTrustee]:
        return [t for t in self.trustees if t.tenant_id == tenant_id and t.is_active]

    def find_trustee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> BreakGlassTrustee | None:
        for trustee in self.active_trustees(tenant_id):
            if trustee.employee_id == employee_id:
                return trustee
        return None

    def save_trustee(self, trustee: BreakGlassTrustee) -> None:
        self.trustees = [t for t in self.trustees if t.id != trustee.id]
        self.trustees.append(trustee)

    def get_grant(self, grant_id: BreakGlassGrantId) -> BreakGlassGrant | None:
        return self.grants.get(grant_id)

    def find_open_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> BreakGlassGrant | None:
        open_rows = [
            g
            for g in self.grants.values()
            if g.tenant_id == tenant_id
            and g.requested_by == employee_id
            and g.status in (BreakGlassStatus.PENDING_APPROVAL, BreakGlassStatus.ACTIVE)
        ]
        open_rows.sort(key=lambda g: g.requested_at, reverse=True)
        return open_rows[0] if open_rows else None

    def list_pending(self, tenant_id: TenantId) -> list[BreakGlassGrant]:
        return [
            g
            for g in self.grants.values()
            if g.tenant_id == tenant_id and g.status is BreakGlassStatus.PENDING_APPROVAL
        ]

    def list_active(self, tenant_id: TenantId) -> list[BreakGlassGrant]:
        return [
            g
            for g in self.grants.values()
            if g.tenant_id == tenant_id and g.status is BreakGlassStatus.ACTIVE
        ]

    def count_since(self, tenant_id: TenantId, *, since: datetime) -> int:
        return sum(
            1 for g in self.grants.values() if g.tenant_id == tenant_id and g.requested_at >= since
        )

    def list_vendor_unsynced(self, tenant_id: TenantId, *, limit: int) -> list[BreakGlassGrant]:
        rows = [
            g
            for g in self.grants.values()
            if g.tenant_id == tenant_id and g.vendor_synced_at is None
        ]
        return rows[:limit]

    def save_grant(self, grant: BreakGlassGrant) -> None:
        self.grants[grant.id] = grant


class _Employees:
    def __init__(self, *people: Employee) -> None:
        self.rows = {person.id: person for person in people}

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.rows.get(employee_id)


class _Vendor:
    """`VendorBreakGlassReporter` sahtəsi — uğursuzluq simulyasiya edilə bilir."""

    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[BreakGlassGrantId] = []

    def report(self, grant: BreakGlassGrant) -> bool:
        if not self.ok:
            return False
        self.sent.append(grant.id)
        return True


def _handoff_use_case(
    repo: _Handoffs, clock: FakeClock, limits: FakeSystemLimits | None = None
) -> ShiftHandoffUseCase:
    return ShiftHandoffUseCase(
        handoffs=repo,  # type: ignore[arg-type]
        audit=RecordingAudit(),
        clock=clock,  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )


def _break_glass(
    repo: _Grants,
    clock: FakeClock,
    *,
    people: _Employees | None = None,
    limits: FakeSystemLimits | None = None,
    vendor: _Vendor | None = None,
    notifier: RecordingNotifier | None = None,
    audit: RecordingAudit | None = None,
) -> BreakGlassUseCase:
    return BreakGlassUseCase(
        grants=repo,  # type: ignore[arg-type]
        employees=people or _Employees(),  # type: ignore[arg-type]
        audit=audit or RecordingAudit(),
        clock=clock,  # type: ignore[arg-type]
        notifier=notifier or RecordingNotifier(),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
        vendor_reporter=vendor,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# 5.1 — Uzatılmış offline rejim
# --------------------------------------------------------------------------- #


class _Buffer:
    """`OfflineBuffer`-in ölçmə səthinin sahtəsi (SQLite açmadan)."""

    def __init__(self, *, pending: int = 0, oldest: datetime | None = None) -> None:
        self._pending = pending
        self._oldest = oldest
        self.meta: dict[str, str] = {}

    def counts(self, *, tenant_id: str | None = None) -> dict[str, int]:
        return {"PENDING": self._pending, "SYNCED": 0, "CONFLICT": 0}

    def oldest_pending_queued_at(self, *, tenant_id: str | None = None) -> datetime | None:
        return self._oldest

    def read_meta(self, key: str) -> str | None:
        return self.meta.get(key)

    def write_meta(self, key: str, value: str) -> None:
        self.meta[key] = value


def _monitor(buffer: _Buffer) -> OfflineBacklogMonitor:
    return OfflineBacklogMonitor(buffer)  # type: ignore[arg-type]


def test_offline_backlog_is_quiet_while_inside_the_limits() -> None:
    monitor = _monitor(_Buffer(pending=10, oldest=NOW - timedelta(hours=2)))
    assessment = monitor.assess(now=NOW)
    assert not assessment.is_exceeded
    assert "normaldır" in assessment.summary_az


def test_age_and_count_thresholds_are_independent() -> None:
    """AZ sətirlə UZUN offline ilə ÇOX sətirlə QISA offline fərqli nasazlıqdır."""
    old_but_small = _monitor(_Buffer(pending=3, oldest=NOW - timedelta(hours=40))).assess(now=NOW)
    assert old_but_small.age_exceeded and not old_but_small.count_exceeded

    fresh_but_large = _monitor(_Buffer(pending=900, oldest=NOW - timedelta(minutes=30))).assess(
        now=NOW
    )
    assert fresh_but_large.count_exceeded and not fresh_but_large.age_exceeded


def test_empty_buffer_is_never_reported_as_stale() -> None:
    """Sıfır sətirli buferdə «ən köhnə yazı» sualı MƏNASIZDIR."""
    assessment = _monitor(_Buffer(pending=0, oldest=None)).assess(now=NOW)
    assert not assessment.is_exceeded


def test_alert_cooldown_survives_a_restart() -> None:
    """Pəncərə `outbox_meta`-dadır — yaddaşda olsaydı hər açılış bildiriş yaradardı."""
    buffer = _Buffer(pending=900, oldest=NOW - timedelta(hours=1))
    first = _monitor(buffer)
    assessment = first.assess(now=NOW)
    assert first.should_alert(assessment, now=NOW)
    first.mark_alerted(now=NOW)

    # YENİ monitor nüsxəsi = prosesin yenidən başlaması.
    restarted = _monitor(buffer)
    assert not restarted.should_alert(assessment, now=NOW + timedelta(hours=1))
    assert restarted.should_alert(assessment, now=NOW + timedelta(hours=13))


def test_unreadable_cooldown_value_does_not_silence_the_alert() -> None:
    buffer = _Buffer(pending=900, oldest=NOW)
    buffer.meta["offline_backlog_alerted_at:ALL"] = "zibil"
    monitor = _monitor(buffer)
    assert monitor.should_alert(monitor.assess(now=NOW), now=NOW)


def test_marking_is_separate_from_deciding() -> None:
    """`should_alert()` yazı etsəydi, bildiriş çöksə də pəncərə bağlanardı."""
    buffer = _Buffer(pending=900, oldest=NOW)
    monitor = _monitor(buffer)
    monitor.should_alert(monitor.assess(now=NOW), now=NOW)
    assert buffer.meta == {}


# --------------------------------------------------------------------------- #
# 5.2 — Aparat (RAM) metriki
# --------------------------------------------------------------------------- #


def test_memory_metric_reports_unknown_when_it_cannot_measure() -> None:
    """SÜKUTLA «qaydasındadır» demək ən pis cavabdır."""
    metric = memory_metric(reader=lambda: None)
    assert metric.level is HealthLevel.UNKNOWN
    assert not metric.is_ok


@pytest.mark.parametrize(
    ("used_percent", "expected"),
    [
        (35.0, HealthLevel.OK),
        (88.0, HealthLevel.WARNING),
        (97.0, HealthLevel.CRITICAL),
    ],
)
def test_memory_metric_levels_follow_the_root_thresholds(
    used_percent: float, expected: HealthLevel
) -> None:
    metric = memory_metric(reader=lambda: (used_percent, 1.5))
    assert metric.level is expected


def test_memory_metric_shows_numbers_not_adjectives() -> None:
    """«Yaddaş azdır» heç nə demir — texniki-məsul rəqəmə görə qərar verir."""
    metric = memory_metric(reader=lambda: (91.0, 0.7))
    assert "91%" in metric.value_az
    assert "0.7 GB" in metric.value_az


# --------------------------------------------------------------------------- #
# 5.3 — Şift-handoff qeydi
# --------------------------------------------------------------------------- #


def test_handoff_note_is_visible_to_the_next_employee() -> None:
    repo, clock = _Handoffs(), FakeClock(NOW)
    use_case = _handoff_use_case(repo, clock)
    author = _employee()
    use_case.leave_note(tenant_id=TENANT, employee=author, note="Kassada 120 AZN qaldı.")

    clock.advance(hours=1)
    nextcomer = _employee()
    visible = use_case.pending_for_employee(tenant_id=TENANT, employee=nextcomer)
    assert [row.note for row in visible] == ["Kassada 120 AZN qaldı."]


def test_the_author_never_sees_their_own_note() -> None:
    repo, clock = _Handoffs(), FakeClock(NOW)
    use_case = _handoff_use_case(repo, clock)
    author = _employee()
    use_case.leave_note(tenant_id=TENANT, employee=author, note="Açıq tapşırıq: soyuducu.")
    assert use_case.pending_for_employee(tenant_id=TENANT, employee=author) == []


def test_visibility_window_follows_the_root_value_immediately() -> None:
    """Pəncərə SÜTUN olsaydı, Root dəyişikliyi köhnə sətirlərə TƏSİR ETMƏZDİ."""
    repo, clock = _Handoffs(), FakeClock(NOW)
    limits = FakeSystemLimits()
    use_case = _handoff_use_case(repo, clock, limits)
    use_case.leave_note(tenant_id=TENANT, employee=_employee(), note="Təhvil qeydi.")

    clock.advance(hours=20)
    reader = _employee()
    assert use_case.pending_for_employee(tenant_id=TENANT, employee=reader) == []

    limits.set(SystemLimitKey.SHIFT_HANDOFF_VISIBILITY_HOURS, "48")
    assert len(use_case.pending_for_employee(tenant_id=TENANT, employee=reader)) == 1


def test_note_length_limit_comes_from_root_not_from_the_class() -> None:
    repo, clock = _Handoffs(), FakeClock(NOW)
    limits = FakeSystemLimits({SystemLimitKey.SHIFT_HANDOFF_NOTE_MAX_CHARS.value: "50"})
    use_case = _handoff_use_case(repo, clock, limits)
    with pytest.raises(DomainRuleError, match="50 simvol"):
        use_case.leave_note(tenant_id=TENANT, employee=_employee(), note="x" * 51)


def test_acknowledgement_needs_a_second_person() -> None:
    repo, clock = _Handoffs(), FakeClock(NOW)
    use_case = _handoff_use_case(repo, clock)
    author = _employee()
    note = use_case.leave_note(tenant_id=TENANT, employee=author, note="Kassa təhvili.")

    with pytest.raises(DomainRuleError, match="öz təhvil qeydini"):
        use_case.acknowledge(tenant_id=TENANT, employee=author, note_id=note.id)

    taker = _employee()
    accepted = use_case.acknowledge(tenant_id=TENANT, employee=taker, note_id=note.id)
    assert accepted.acknowledged_by == taker.id
    assert use_case.pending_for_employee(tenant_id=TENANT, employee=taker) == []


def test_a_note_belongs_to_one_store_only() -> None:
    repo, clock = _Handoffs(), FakeClock(NOW)
    use_case = _handoff_use_case(repo, clock)
    with pytest.raises(ShiftHandoffError, match="öz filialının"):
        use_case.leave_note(
            tenant_id=TENANT, employee=_employee(), note="Yad filial.", store_id=OTHER_STORE
        )


def test_a_second_acknowledgement_is_rejected() -> None:
    note = ShiftHandoffNote(
        note_id=new_shift_handoff_note_id(),
        tenant_id=TENANT,
        store_id=STORE,
        author_employee_id=_employee().id,
        note="Təhvil.",
        work_date=NOW.date(),
        created_at=NOW,
        max_length=1000,
    )
    note.acknowledge(employee_id=_employee().id, acknowledged_at=NOW)
    with pytest.raises(DomainRuleError, match="artıq qəbul edilib"):
        note.acknowledge(employee_id=_employee().id, acknowledged_at=NOW)


# --------------------------------------------------------------------------- #
# 5.4 — Break-glass
# --------------------------------------------------------------------------- #


def _designated(repo: _Grants, employee: Employee, *, root: Employee) -> BreakGlassTrustee:
    trustee = BreakGlassTrustee(
        trustee_id=new_break_glass_trustee_id(),
        tenant_id=TENANT,
        employee_id=employee.id,
        designated_by=root.id,
        designated_at=NOW - timedelta(days=30),
    )
    repo.save_trustee(trustee)
    return trustee


def test_only_root_can_designate_a_trustee() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE)
    candidate = _employee()
    use_case = _break_glass(repo, clock, people=_Employees(candidate))
    with pytest.raises(BreakGlassPermissionError, match=MANAGE_BREAK_GLASS_FLAG):
        use_case.designate_trustee(tenant_id=TENANT, actor=ceo, employee_id=candidate.id)


def test_root_cannot_designate_itself() -> None:
    """Öz-təyinat mexanizmi «Root özünə ikinci qapı açdı»ya çevirərdi."""
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    use_case = _break_glass(repo, clock, people=_Employees(root))
    with pytest.raises(DomainRuleError, match="özünü ehtiyat-admin"):
        use_case.designate_trustee(tenant_id=TENANT, actor=root, employee_id=root.id)


def test_designation_notifies_the_person_themselves() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    candidate = _employee()
    notifier = RecordingNotifier()
    use_case = _break_glass(repo, clock, people=_Employees(candidate), notifier=notifier)
    use_case.designate_trustee(tenant_id=TENANT, actor=root, employee_id=candidate.id)
    assert notifier.messages[0]["recipient_id"] == candidate.id


def test_a_non_trustee_cannot_request_emergency_access() -> None:
    """MEXANİZMİN ƏSAS ZƏMANƏTİ: təyinat böhrandan ƏVVƏL verilir."""
    repo, clock = _Grants(), FakeClock(NOW)
    stranger = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    use_case = _break_glass(repo, clock)
    with pytest.raises(BreakGlassPermissionError, match="əvvəlcədən təyin"):
        use_case.request_access(tenant_id=TENANT, actor=stranger, reason="Sistem işləmir, təcili")
    assert not repo.grants


def test_request_requires_a_detailed_reason() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)
    with pytest.raises(DomainRuleError, match="10 simvol"):
        use_case.request_access(tenant_id=TENANT, actor=admin, reason="lazımdı")


def test_a_second_open_request_is_blocked() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)
    use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    with pytest.raises(BreakGlassError, match="artıq açıq"):
        use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")


def test_monthly_quota_counts_rejected_requests_too() -> None:
    """Tavan «neçə dəfə verildi» deyil, «neçə dəfə İSTƏNİLDİ» sualını qorumalıdır."""
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)

    for _ in range(2):
        grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Təcili nasazlıq")
        use_case.reject(
            tenant_id=TENANT, approver=ceo, grant_id=grant.id, reason="Lazım deyil, həll olundu"
        )

    with pytest.raises(BreakGlassError, match="həddi doldu"):
        use_case.request_access(tenant_id=TENANT, actor=admin, reason="Üçüncü cəhd, təcili")


def test_the_requester_can_never_approve_their_own_request() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)
    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")

    with pytest.raises(DomainRuleError, match="özü təsdiqləyə bilməz"):
        use_case.approve(tenant_id=TENANT, approver=admin, grant_id=grant.id)


def test_two_trustees_can_approve_each_other() -> None:
    """Root DA, CEO DA əlçatmaz ola bilər — «iki nəfər» zəmanəti POZULMUR."""
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    first = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    second = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    _designated(repo, first, root=root)
    _designated(repo, second, root=root)
    use_case = _break_glass(repo, clock)

    grant = use_case.request_access(tenant_id=TENANT, actor=first, reason="Şəbəkə tam qopub")
    approved = use_case.approve(tenant_id=TENANT, approver=second, grant_id=grant.id)
    assert approved.status is BreakGlassStatus.ACTIVE


def test_approval_window_closes_the_request() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)
    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")

    clock.advance(minutes=31)
    with pytest.raises(DomainRuleError, match="Təsdiq pəncərəsi"):
        use_case.approve(tenant_id=TENANT, approver=ceo, grant_id=grant.id)


def test_effective_authority_expires_by_the_clock_not_by_the_scheduler() -> None:
    """Planlayıcı gecikəndə də səlahiyyət UZANMIR."""
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)
    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    use_case.approve(tenant_id=TENANT, approver=ceo, grant_id=grant.id)

    assert use_case.has_effective_root(tenant_id=TENANT, employee_id=admin.id)
    clock.advance(minutes=121)
    # Status HƏLƏ `ACTIVE`-dir (planlayıcı işləməyib), lakin səlahiyyət YOXDUR.
    assert repo.get_grant(grant.id) is not None
    assert repo.get_grant(grant.id).status is BreakGlassStatus.ACTIVE  # type: ignore[union-attr]
    assert not use_case.has_effective_root(tenant_id=TENANT, employee_id=admin.id)


def test_scheduler_closes_both_kinds_of_expiry() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    unapproved_admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    active_admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, unapproved_admin, root=root)
    _designated(repo, active_admin, root=root)
    use_case = _break_glass(repo, clock)

    stale = use_case.request_access(
        tenant_id=TENANT, actor=unapproved_admin, reason="Cavabsız qalan sorğu"
    )
    live = use_case.request_access(tenant_id=TENANT, actor=active_admin, reason="Təsdiqlənən sorğu")
    use_case.approve(tenant_id=TENANT, approver=ceo, grant_id=live.id)

    clock.advance(hours=3)
    assert use_case.expire_due(tenant_id=TENANT) == 2
    assert repo.grants[stale.id].status is BreakGlassStatus.EXPIRED
    assert repo.grants[live.id].status is BreakGlassStatus.EXPIRED


def test_granted_authority_cannot_be_extended_only_reissued() -> None:
    """«Uzat» metodu OLSAYDI, müvəqqəti səlahiyyət daimiyə çevrilə bilərdi."""
    assert not hasattr(BreakGlassGrant, "extend")
    assert not hasattr(BreakGlassGrant, "renew")


def test_root_can_revoke_an_active_grant_early() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)
    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    use_case.approve(tenant_id=TENANT, approver=ceo, grant_id=grant.id)

    use_case.revoke(
        tenant_id=TENANT, actor=root, grant_id=grant.id, reason="Root qayıtdı, ehtiyac yoxdur"
    )
    assert repo.grants[grant.id].status is BreakGlassStatus.REVOKED
    assert not use_case.has_effective_root(tenant_id=TENANT, employee_id=admin.id)


def test_a_failed_vendor_report_does_not_block_the_grant() -> None:
    """Fövqəladə halda mərkəzi bazanın əlçatmazlığı sistemi işləməz etməməlidir."""
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    vendor = _Vendor(ok=False)
    use_case = _break_glass(repo, clock, vendor=vendor)
    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    approved = use_case.approve(tenant_id=TENANT, approver=ceo, grant_id=grant.id)

    assert approved.status is BreakGlassStatus.ACTIVE
    assert approved.vendor_synced_at is None

    # Şəbəkə qayıdanda gecəlik iş sətri göndərir.
    vendor.ok = True
    assert use_case.retry_vendor_reports(tenant_id=TENANT) == 1
    assert repo.grants[grant.id].vendor_synced_at is not None


def test_pending_requests_are_not_reported_to_the_vendor() -> None:
    """Gözləyən sorğu hələ heç bir səlahiyyət vermir və ölə bilər."""
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    _designated(repo, admin, root=root)
    vendor = _Vendor()
    use_case = _break_glass(repo, clock, vendor=vendor)
    use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    assert use_case.retry_vendor_reports(tenant_id=TENANT) == 0
    assert vendor.sent == []


def test_every_decision_is_audited() -> None:
    """Səlahiyyət verildi, jurnalda yoxdur — belə hal MÜMKÜN OLMAMALIDIR."""
    repo, clock = _Grants(), FakeClock(NOW)
    audit = RecordingAudit()
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock, audit=audit)
    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    use_case.approve(tenant_id=TENANT, approver=ceo, grant_id=grant.id)

    actions = [entry["action"] for entry in _audit_entries(audit)]
    assert "BREAK_GLASS_REQUESTED" in actions
    assert "BREAK_GLASS_APPROVED" in actions


def _audit_entries(audit: RecordingAudit) -> list[dict[str, Any]]:
    """`RecordingAudit`-in daxili siyahısı — sahtənin sahə adı dəyişsə burada tutulur."""
    entries = getattr(audit, "entries", None)
    if entries is None:  # pragma: no cover — sahtənin forması dəyişsə
        entries = audit.records  # type: ignore[attr-defined]
    return [dict(entry) for entry in entries]


# --------------------------------------------------------------------------- #
# 5.4 UI marşrutlaması — menyu görünürlüyü üçün oxu metodları
# --------------------------------------------------------------------------- #
# Ehtiyat-admin flag DAŞIMIR; menyu maddəsi onu reyestr üzvlüyünə görə görür
# (`alternate_admission`, bax `navigation.py`). Bu testlər həmin oxuların
# DOĞRU SUALI verməsini qoruyur: görünmə icazə deyil, amma yanlış cavab
# ekrana yanlış adamı salır.


def test_trustee_read_answers_the_routing_question() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    stranger = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)

    assert use_case.is_active_trustee(tenant_id=TENANT, employee_id=admin.id)
    assert not use_case.is_active_trustee(tenant_id=TENANT, employee_id=stranger.id)


def test_open_grant_read_returns_only_the_employee_own_row() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    other = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    use_case = _break_glass(repo, clock)

    assert use_case.open_grant_for(TENANT, admin.id) is None
    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    use_case.approve(tenant_id=TENANT, approver=ceo, grant_id=grant.id)

    mine = use_case.open_grant_for(TENANT, admin.id)
    assert mine is not None and mine.id == grant.id
    # Başqasının açıq sətri bu yoldan HEÇ VAXT çıxmır.
    assert use_case.open_grant_for(TENANT, other.id) is None


def test_active_grants_listing_is_approver_gated() -> None:
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    admin = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    second = _employee(code="ADMIN", priority=RolePriority.ADMIN)
    stranger = _employee(code="SATICI", priority=RolePriority.STAFF)
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    _designated(repo, admin, root=root)
    _designated(repo, second, root=root)
    use_case = _break_glass(repo, clock)

    grant = use_case.request_access(tenant_id=TENANT, actor=admin, reason="Baza bağlantısı qopub")
    use_case.approve(tenant_id=TENANT, approver=second, grant_id=grant.id)

    # Təsdiqləyici (flag) və iştirakçı ehtiyat-admin GÖRÜR; kənar görmür.
    assert len(use_case.active_grants(tenant_id=TENANT, actor=ceo)) == 1
    assert len(use_case.active_grants(tenant_id=TENANT, actor=admin)) == 1
    with pytest.raises(BreakGlassPermissionError):
        use_case.active_grants(tenant_id=TENANT, actor=stranger)


def test_may_manage_reads_the_same_gate_as_the_registry() -> None:
    """İKİNCİ sabit YAZILMADI — görünürlük sualı da `can_manage_break_glass`-dan."""
    repo, clock = _Grants(), FakeClock(NOW)
    root = _employee(code="ROOT", priority=RolePriority.ROOT, flags=(MANAGE_BREAK_GLASS_FLAG,))
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=(APPROVE_BREAK_GLASS_FLAG,))
    use_case = _break_glass(repo, clock)

    assert use_case.may_manage(tenant_id=TENANT, actor=root)
    assert not use_case.may_manage(tenant_id=TENANT, actor=ceo)
