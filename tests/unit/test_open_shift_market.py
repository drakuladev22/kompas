"""#16 Açıq Növbə Bazarı (kompasos11.md Faza 6) — "ilk basan qazanır".

BAZA LAZIM DEYİL: bütün portlar sahtə obyektlərlə əvəz olunur.

──────────────────────────────────────────────────────────────────────────────
NƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
1.  YARIŞ VƏZİYYƏTİ — bu faylın ƏSAS testi. İki PARALEL `claim` yalnız bir
    qalib verməlidir və uduzan AÇIQ Azərbaycanca mesaj almalıdır.
2.  AYRI AXIN — açıq növbə Shift Swap sorğusu YARATMIR və onun statuslarına
    toxunmur; təsdiq mərhələsi YOXDUR.
3.  MÖVCUD YAZMA FUNKSİYASI — təyinat `ShiftPlanningUseCase.apply_assignment()`
    ilə yazılır (bölmə 3 "məntiq təkrarlanmır").
4.  ROOT PARAMETRLƏRİ — irəli-elan pəncərəsi və aylıq tavan `system_limits`-dən
    oxunur; sinifdəki sabitlər yalnız fallback-dır.
5.  FEATURE TOGGLE RETROAKTİV DEYİL — söndürmə YENİ elanı bloklayır, mövcud
    elanın tutulmasını YOX.
6.  UYĞUNLUQ — başqa mağaza, keçmiş tarix, həmin gün mövcud iş növbəsi və
    aylıq tavan rədd edilir; İSTİRAHƏT günü isə rədd EDİLMİR (bazarın mənası).
7.  VƏZİFƏ AYRILIĞI — elanı açan onu özü tuta bilməz.
8.  AUDIT — hər yazı `audit_logs`-a düşür.

SAHTƏLƏR: `InMemoryOpenShiftPostings` BU FAYLDA təyin olunub (paylaşılan
`tests/fixtures/fakes.py` dəyişdirilmir). O, DB-nin ŞƏRTLİ `UPDATE`
semantikasını təqlid edir: `claim()` daxili kilid altında statusu YENİDƏN
yoxlayır — yəni test tətbiq qatının "əvvəlcə oxu, sonra yaz" naxışına
söykənmədiyini sübut edə bilir.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.application.use_cases.open_shift_market import (
    FALLBACK_MAX_CLAIMS_PER_MONTH,
    FALLBACK_MAX_LEAD_DAYS,
    OpenShiftAlreadyClaimedError,
    OpenShiftError,
    OpenShiftMarketUseCase,
    OpenShiftNotEligibleError,
    OpenShiftNotFoundError,
)
from src.application.use_cases.shift_scheduling import (
    MANAGE_SHIFTS_FLAG,
    ShiftPermissionError,
    ShiftPlanningUseCase,
)
from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.open_shift import (
    OpenShiftPosting,
    OpenShiftSlot,
    OpenShiftStatus,
)
from src.domain.entities.position import Position
from src.domain.entities.shift import ShiftSource
from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    OpenShiftPostingId,
    StoreId,
    TenantId,
    WorkModeId,
    new_open_shift_posting_id,
)
from tests.fixtures.fakes import (
    FakeClock,
    FakeFeatureToggles,
    FakeSystemLimits,
    InMemoryLeaveRequests,
    InMemoryShiftMatrix,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TODAY = NOW.date()
TOMORROW = TODAY + timedelta(days=1)
TENANT = TenantId(uuid.uuid4())
OTHER_TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
MODE = WorkModeId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Yerli sahtə — DB-nin ŞƏRTLİ `UPDATE` semantikası
# --------------------------------------------------------------------------- #


class InMemoryOpenShiftPostings:
    """`OpenShiftPostingRepository`-nin yaddaş versiyası.

    ATOMİKLİK QƏSDƏN MODELLƏŞDİRİLİB: `claim()` və `cancel()` daxili
    `threading.Lock` altında statusu YENİDƏN yoxlayır — real DB-dəki
    `UPDATE ... WHERE status = 'OPEN'` şərtinin eynisi. Sadə sözlük
    yeniləməsi yazsaydıq, paralel test HƏMİŞƏ yaşıl olardı və yarış qüsuru
    testdən keçərdi.

    `read_barrier`: hər iki oxucunun `get_for_update()`-dən EYNİ ANDA çıxmasını
    təmin edir — yəni testdə hər iki iş axını statusu `OPEN` görür. Məhz bu,
    tətbiq qatındakı "oxu → yoxla → yaz" naxışının uduzduğu ssenaridir.
    """

    def __init__(self, *, read_barrier: threading.Barrier | None = None) -> None:
        self.items: dict[OpenShiftPostingId, OpenShiftPosting] = {}
        self.claim_attempts = 0
        self._lock = threading.Lock()
        self._read_barrier = read_barrier

    # --- oxu --- #

    def get(self, posting_id: OpenShiftPostingId) -> OpenShiftPosting | None:
        stored = self.items.get(posting_id)
        return None if stored is None else _hydrate(stored)

    def get_for_update(self, posting_id: OpenShiftPostingId) -> OpenShiftPosting | None:
        stored = self.items.get(posting_id)
        posting = None if stored is None else _hydrate(stored)
        if self._read_barrier is not None:
            self._read_barrier.wait(timeout=5)
        return posting

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_id: StoreId | None = None,
        from_date: date | None = None,
        limit: int = 100,
    ) -> list[OpenShiftPosting]:
        rows = [
            _hydrate(item)
            for item in self.items.values()
            if item.tenant_id == tenant_id
            and item.status is OpenShiftStatus.OPEN
            and (store_id is None or item.store_id == store_id)
            and (from_date is None or item.shift_date >= from_date)
        ]
        return sorted(rows, key=lambda item: item.shift_date)[:limit]

    def find_open_for_slot(
        self, tenant_id: TenantId, slot: OpenShiftSlot
    ) -> OpenShiftPosting | None:
        for item in self.items.values():
            if (
                item.tenant_id == tenant_id
                and item.status is OpenShiftStatus.OPEN
                and item.store_id == slot.store_id
                and item.shift_date == slot.shift_date
                and item.work_mode_id == slot.work_mode_id
            ):
                return _hydrate(item)
        return None

    def count_claims_in_month(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        return sum(
            1
            for item in self.items.values()
            if item.claimed_by == employee_id
            and item.status is OpenShiftStatus.CLAIMED
            and item.shift_date.year == year
            and item.shift_date.month == month
        )

    # --- yazı --- #

    def post(self, posting: OpenShiftPosting) -> None:
        # Saxlanılan sətir çağıranın obyektindən AYRIDIR — real repo sətri
        # bazaya yazır, obyekti saxlamır.
        self.items[posting.id] = _hydrate(posting)

    def claim(
        self,
        *,
        posting_id: OpenShiftPostingId,
        employee_id: EmployeeId,
        claimed_at: datetime,
    ) -> bool:
        with self._lock:
            self.claim_attempts += 1
            posting = self.items.get(posting_id)
            if posting is None or posting.status is not OpenShiftStatus.OPEN:
                return False
            posting.status = OpenShiftStatus.CLAIMED
            posting.claimed_by = employee_id
            posting.claimed_at = claimed_at
            return True

    def cancel(
        self,
        *,
        posting_id: OpenShiftPostingId,
        cancelled_by: EmployeeId,
        cancelled_at: datetime,
        reason: str,
    ) -> bool:
        with self._lock:
            posting = self.items.get(posting_id)
            if posting is None or posting.status is not OpenShiftStatus.OPEN:
                return False
            posting.status = OpenShiftStatus.CANCELLED
            posting.cancelled_by = cancelled_by
            posting.cancelled_at = cancelled_at
            posting.cancel_reason = reason
            return True


def _hydrate(posting: OpenShiftPosting) -> OpenShiftPosting:
    """Repo-nun HİDRASİYASI: hər oxu YENİ obyekt qaytarır.

    Real `PostgresOpenShiftPostingRepository` sətri bazadan oxuyub təzə
    aqreqat qurur. Sahtə eyni obyekti qaytarsaydı, `claim()`-in şərti UPDATE-i
    çağıranın əlindəki obyekti də dəyişdirərdi — yəni test real davranışdan
    uzaqlaşar və yarış ssenarisi süni şəkildə "həll olunmuş" görünərdi.
    """
    return OpenShiftPosting(
        posting_id=posting.id,
        tenant_id=posting.tenant_id,
        slot=posting.slot,
        posted_by=posting.posted_by,
        created_at=posting.created_at,
        status=posting.status,
        claimed_by=posting.claimed_by,
        claimed_at=posting.claimed_at,
        cancelled_by=posting.cancelled_by,
        cancelled_at=posting.cancelled_at,
        cancel_reason=posting.cancel_reason,
        emit_created_event=False,
    )


@dataclass
class Harness:
    """Testin bütün iştirakçıları — hər testdə təzədən qurulur."""

    use_case: OpenShiftMarketUseCase
    postings: InMemoryOpenShiftPostings
    shifts: InMemoryShiftMatrix
    audit: RecordingAudit
    notifier: RecordingNotifier
    limits: FakeSystemLimits
    toggles: FakeFeatureToggles
    clock: FakeClock


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee(
    *,
    flags: tuple[str, ...] = (),
    store_id: StoreId | None = STORE,
    tenant_id: TenantId = TENANT,
    name: str = "Aysel",
) -> Employee:
    position = Position(
        position_id=uuid.uuid4(),  # type: ignore[arg-type]
        code=f"ROLE_{uuid.uuid4().hex[:6]}",
        name_az="Sınaq rolu",
        priority=RolePriority.OPERATIONAL,
        tenant_id=tenant_id,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name=name,
        last_name="Quliyeva",
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


def _admin() -> Employee:
    return _employee(flags=(MANAGE_SHIFTS_FLAG,), name="Rəşad")


def _harness(
    *,
    read_barrier: threading.Barrier | None = None,
    limits: dict[str, str] | None = None,
) -> Harness:
    clock = FakeClock(NOW)
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    shifts = InMemoryShiftMatrix()
    postings = InMemoryOpenShiftPostings(read_barrier=read_barrier)
    system_limits = FakeSystemLimits(limits)
    toggles = FakeFeatureToggles()

    planning = ShiftPlanningUseCase(
        shifts=shifts,
        leave_requests=InMemoryLeaveRequests(),
        audit=audit,
        clock=clock,
        notifier=notifier,
    )
    use_case = OpenShiftMarketUseCase(
        postings=postings,
        planning=planning,
        shifts=shifts,
        limits=system_limits,
        toggles=toggles,
        audit=audit,
        clock=clock,
        notifier=notifier,
    )
    return Harness(
        use_case=use_case,
        postings=postings,
        shifts=shifts,
        audit=audit,
        notifier=notifier,
        limits=system_limits,
        toggles=toggles,
        clock=clock,
    )


def _post(harness: Harness, admin: Employee, *, day: date = TOMORROW) -> OpenShiftPosting:
    return harness.use_case.post_open_shift(
        tenant_id=TENANT,
        actor=admin,
        store_id=STORE,
        shift_date=day,
        work_mode_id=MODE,
    )


# --------------------------------------------------------------------------- #
# 1. YARIŞ VƏZİYYƏTİ — BU FAYLIN ƏSAS TESTİ
# --------------------------------------------------------------------------- #


def test_two_parallel_claims_produce_exactly_one_winner() -> None:
    """İki işçi EYNİ ANDA basır — YALNIZ biri qazanır.

    Barrier hər iki iş axınını `get_for_update()`-də saxlayır, yəni HƏR İKİSİ
    statusu `OPEN` görür. Əgər use case qərarı oxuduğu vəziyyətə görə versəydi,
    hər ikisi qalib olardı və təqvimə iki təyinat yazılardı.
    """
    barrier = threading.Barrier(2)
    harness = _harness(read_barrier=barrier)
    admin = _admin()
    posting = _post(harness, admin)

    first = _employee(name="Leyla")
    second = _employee(name="Nigar")
    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}

    def attempt(key: str, employee: Employee) -> None:
        try:
            results[key] = harness.use_case.claim(
                tenant_id=TENANT, employee=employee, posting_id=posting.id
            )
        except BaseException as error:  # test HƏR NƏTİCƏNİ yığır, birini də udmur
            errors[key] = error

    threads = [
        threading.Thread(target=attempt, args=("first", first)),
        threading.Thread(target=attempt, args=("second", second)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 1, "İki paralel tutmadan yalnız biri uğurlu olmalıdır"
    assert len(errors) == 1

    loser_error = next(iter(errors.values()))
    assert isinstance(loser_error, OpenShiftAlreadyClaimedError)
    # Uduzan SÜKUTLA uğursuz olmur — mesaj Azərbaycan dilində və konkretdir.
    assert loser_error.user_message == "Bu növbəni artıq başqası götürüb."

    winner_key = next(iter(results))
    winner = first if winner_key == "first" else second
    stored = harness.postings.items[posting.id]
    assert stored.status is OpenShiftStatus.CLAIMED
    assert stored.claimed_by == winner.id

    # Təqvimə YALNIZ bir təyinat düşür — uduzanın günü toxunulmamış qalır.
    assert len(harness.shifts.assignments) == 1
    assignment = harness.shifts.assignments[(winner.id, TOMORROW)]
    assert assignment.work_mode_id == MODE
    assert harness.postings.claim_attempts == 2, "Hər iki iş axını DB-yə müraciət etməlidir"


def test_second_claim_after_the_first_one_is_rejected() -> None:
    """Ardıcıl (paralel olmayan) ikinci tutma da eyni mesajı alır."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)

    harness.use_case.claim(
        tenant_id=TENANT, employee=_employee(name="Leyla"), posting_id=posting.id
    )
    with pytest.raises(OpenShiftAlreadyClaimedError):
        harness.use_case.claim(
            tenant_id=TENANT, employee=_employee(name="Nigar"), posting_id=posting.id
        )


def test_claiming_a_cancelled_posting_is_rejected() -> None:
    """Ləğv edilmiş elan da bağlıdır — LAKİN mesajı fərqlidir.

    "Başqası götürüb" demək işçini olmayan bir rəqib axtarmağa yönəldərdi.
    """
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)
    harness.use_case.cancel_posting(
        tenant_id=TENANT,
        actor=admin,
        posting_id=posting.id,
        reason="Mağaza həmin gün bağlıdır",
    )

    with pytest.raises(OpenShiftError) as error:
        harness.use_case.claim(tenant_id=TENANT, employee=_employee(), posting_id=posting.id)
    assert error.value.user_message == "Bu elan ləğv edilib."
    assert not isinstance(error.value, OpenShiftAlreadyClaimedError)


def test_cancelling_an_already_claimed_posting_is_rejected() -> None:
    """Ləğv və tutma da bir-biri ilə yarışır — qalib DB-dir."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)
    harness.use_case.claim(
        tenant_id=TENANT, employee=_employee(name="Leyla"), posting_id=posting.id
    )

    with pytest.raises(InvalidStateTransitionError):
        harness.use_case.cancel_posting(
            tenant_id=TENANT,
            actor=admin,
            posting_id=posting.id,
            reason="Artıq lazım deyil, plan dəyişdi",
        )


# --------------------------------------------------------------------------- #
# 2. ELAN VERMƏ (admin)
# --------------------------------------------------------------------------- #


def test_posting_writes_row_audit_and_notification() -> None:
    harness = _harness()
    admin = _admin()

    posting = _post(harness, admin)

    assert posting.status is OpenShiftStatus.OPEN
    assert harness.postings.items[posting.id].status is OpenShiftStatus.OPEN
    assert "OPEN_SHIFT_POSTED" in harness.audit.actions()
    assert "OPEN_SHIFT_POSTED" in harness.notifier.categories()


def test_posting_requires_manage_shifts_flag() -> None:
    """YENİ flag yaradılmır — mövcud `can_manage_shifts` işlədilir."""
    harness = _harness()

    with pytest.raises(ShiftPermissionError):
        _post(harness, _employee())


def test_posting_a_past_date_is_rejected() -> None:
    harness = _harness()
    with pytest.raises(OpenShiftError):
        _post(harness, _admin(), day=TODAY - timedelta(days=1))


def test_posting_today_is_allowed() -> None:
    """Səhər ləğv olunan növbəni elə həmin gün elan etmək bazarın əsas halıdır."""
    harness = _harness()
    posting = _post(harness, _admin(), day=TODAY)
    assert posting.shift_date == TODAY


def test_lead_window_comes_from_system_limits() -> None:
    """ROOT parametri — sinifdəki sabit yalnız fallback-dır."""
    harness = _harness(limits={SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS.value: "3"})
    admin = _admin()

    with pytest.raises(OpenShiftError):
        _post(harness, admin, day=TODAY + timedelta(days=4))

    assert _post(harness, admin, day=TODAY + timedelta(days=3)) is not None


def test_lead_window_falls_back_to_default_limits() -> None:
    """`system_limits` sətri yoxdursa `DEFAULT_LIMITS` işə düşür."""
    assert int(DEFAULT_LIMITS[SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS]) == FALLBACK_MAX_LEAD_DAYS
    harness = _harness()
    harness.limits.set(SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS, "0")
    admin = _admin()

    # Yararsız (0) dəyər sükutla bazarı bağlamır — fallback tətbiq olunur.
    assert _post(harness, admin, day=TODAY + timedelta(days=FALLBACK_MAX_LEAD_DAYS)) is not None


def test_duplicate_open_slot_is_rejected() -> None:
    """Eyni slota ikinci açıq elan — DB unikal indeksinin domen tərəfi."""
    harness = _harness()
    admin = _admin()
    _post(harness, admin)

    with pytest.raises(OpenShiftError):
        _post(harness, admin)


def test_feature_toggle_blocks_new_postings_only() -> None:
    """RETROAKTİV DEYİL: mövcud elan söndürmədən SONRA da tutula bilir."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)

    harness.toggles.disable(FeatureModule.SHIFT_SWAP.value)

    with pytest.raises(OpenShiftError):
        _post(harness, admin, day=TODAY + timedelta(days=2))

    change = harness.use_case.claim(
        tenant_id=TENANT, employee=_employee(name="Leyla"), posting_id=posting.id
    )
    assert change.assignment is not None


# --------------------------------------------------------------------------- #
# 3. TUTMA — MÖVCUD YAZMA FUNKSİYASI VƏ UYĞUNLUQ
# --------------------------------------------------------------------------- #


def test_claim_writes_the_assignment_through_shift_planning() -> None:
    """Təyinat Shift Matrix-in YEGANƏ yazma funksiyası ilə yaranır."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)
    worker = _employee(name="Leyla")

    change = harness.use_case.claim(tenant_id=TENANT, employee=worker, posting_id=posting.id)

    assert change.assignment is not None
    assert change.assignment.employee_id == worker.id
    assert change.assignment.is_off_day is False
    assert change.assignment.work_mode_id == MODE
    # `ShiftSource` DB `CHECK`-i ilə məhdudlaşır; dəyişikliyin təşəbbüskarı
    # işçidir, ona görə `SHIFT_SWAP` seçilib (bax use case şərhi).
    assert change.assignment.source is ShiftSource.SHIFT_SWAP
    # Shift Matrix-in öz audit yazısı da düşür — mövcud məntiq işləyir.
    assert "SHIFT_ASSIGNED" in harness.audit.actions()
    assert "OPEN_SHIFT_CLAIMED" in harness.audit.actions()


def test_claim_notifies_the_poster() -> None:
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)

    harness.use_case.claim(
        tenant_id=TENANT, employee=_employee(name="Leyla"), posting_id=posting.id
    )

    claimed = [m for m in harness.notifier.messages if m["category"] == "OPEN_SHIFT_CLAIMED"]
    assert len(claimed) == 1
    assert claimed[0]["recipient_id"] == admin.id


def test_employee_from_another_store_cannot_claim() -> None:
    harness = _harness()
    posting = _post(harness, _admin())

    with pytest.raises(OpenShiftNotEligibleError):
        harness.use_case.claim(
            tenant_id=TENANT,
            employee=_employee(store_id=OTHER_STORE),
            posting_id=posting.id,
        )


def test_existing_work_day_blocks_the_claim() -> None:
    """Mövcud iş növbəsi ÜSTÜNDƏN yazılmamalıdır."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)
    worker = _employee(name="Leyla")

    harness.use_case._planning.apply_assignment(  # hazırlıq addımı
        tenant_id=TENANT,
        actor_id=admin.id,
        employee_id=worker.id,
        shift_date=TOMORROW,
        is_off_day=False,
        work_mode_id=MODE,
        source=ShiftSource.ADMIN_MATRIX,
    )

    with pytest.raises(OpenShiftNotEligibleError):
        harness.use_case.claim(tenant_id=TENANT, employee=worker, posting_id=posting.id)


def test_off_day_does_not_block_the_claim() -> None:
    """Bazarın MƏNASI: işçi öz istirahət günündə könüllü növbə götürə bilər."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)
    worker = _employee(name="Leyla")

    harness.use_case._planning.apply_assignment(  # hazırlıq addımı
        tenant_id=TENANT,
        actor_id=admin.id,
        employee_id=worker.id,
        shift_date=TOMORROW,
        is_off_day=True,
        work_mode_id=None,
        source=ShiftSource.ADMIN_MATRIX,
    )

    change = harness.use_case.claim(tenant_id=TENANT, employee=worker, posting_id=posting.id)
    assert change.assignment is not None
    assert change.assignment.is_off_day is False


def test_monthly_cap_comes_from_system_limits() -> None:
    """ROOT parametri: aylıq tavan dolduqda tutma rədd edilir."""
    harness = _harness(limits={SystemLimitKey.OPEN_SHIFT_MAX_CLAIMS_PER_MONTH.value: "1"})
    admin = _admin()
    worker = _employee(name="Leyla")

    first = _post(harness, admin, day=TOMORROW)
    harness.use_case.claim(tenant_id=TENANT, employee=worker, posting_id=first.id)

    second = _post(harness, admin, day=TOMORROW + timedelta(days=1))
    with pytest.raises(OpenShiftNotEligibleError):
        harness.use_case.claim(tenant_id=TENANT, employee=worker, posting_id=second.id)


def test_monthly_cap_default_matches_policy_table() -> None:
    assert (
        int(DEFAULT_LIMITS[SystemLimitKey.OPEN_SHIFT_MAX_CLAIMS_PER_MONTH])
        == FALLBACK_MAX_CLAIMS_PER_MONTH
    )


def test_poster_cannot_claim_their_own_posting() -> None:
    """VƏZİFƏ AYRILIĞI — elanı açan onu özü tuta bilməz."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)

    with pytest.raises(DomainRuleError):
        harness.use_case.claim(tenant_id=TENANT, employee=admin, posting_id=posting.id)


def test_claim_of_another_tenant_posting_is_not_found() -> None:
    """Üçüncü izolyasiya qatı — RLS və repo şərtindən SONRA."""
    harness = _harness()
    posting = _post(harness, _admin())

    with pytest.raises(OpenShiftNotFoundError):
        harness.use_case.claim(tenant_id=OTHER_TENANT, employee=_employee(), posting_id=posting.id)


def test_claim_of_unknown_posting_is_not_found() -> None:
    harness = _harness()
    with pytest.raises(OpenShiftNotFoundError):
        harness.use_case.claim(
            tenant_id=TENANT,
            employee=_employee(),
            posting_id=new_open_shift_posting_id(),
        )


# --------------------------------------------------------------------------- #
# 4. SİYAHILAR
# --------------------------------------------------------------------------- #


def test_employee_list_is_filtered_by_store_and_free_days() -> None:
    harness = _harness()
    admin = _admin()
    worker = _employee(name="Leyla")

    mine = _post(harness, admin, day=TOMORROW)
    harness.use_case.post_open_shift(
        tenant_id=TENANT,
        actor=admin,
        store_id=OTHER_STORE,
        shift_date=TOMORROW,
        work_mode_id=MODE,
    )
    busy_day = TOMORROW + timedelta(days=2)
    _post(harness, admin, day=busy_day)
    harness.use_case._planning.apply_assignment(  # hazırlıq addımı
        tenant_id=TENANT,
        actor_id=admin.id,
        employee_id=worker.id,
        shift_date=busy_day,
        is_off_day=False,
        work_mode_id=MODE,
        source=ShiftSource.ADMIN_MATRIX,
    )

    views = harness.use_case.list_for_employee(tenant_id=TENANT, employee=worker)

    assert [view.posting_id for view in views] == [mine.id]


def test_employee_without_a_store_sees_nothing() -> None:
    """FAIL-CLOSED: mağazası olmayan işçi bütün filialların elanlarını GÖRMÜR."""
    harness = _harness()
    _post(harness, _admin())

    views = harness.use_case.list_for_employee(tenant_id=TENANT, employee=_employee(store_id=None))

    assert views == []


def test_admin_list_requires_manage_flag() -> None:
    harness = _harness()
    _post(harness, _admin())

    with pytest.raises(ShiftPermissionError):
        harness.use_case.list_active(tenant_id=TENANT, actor=_employee())


def test_admin_list_returns_open_postings() -> None:
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)

    views = harness.use_case.list_active(tenant_id=TENANT, actor=admin)

    assert [view.posting_id for view in views] == [posting.id]
    assert views[0].status == OpenShiftStatus.OPEN.value
    assert views[0].posted_by == admin.id


# --------------------------------------------------------------------------- #
# 5. LƏĞV
# --------------------------------------------------------------------------- #


def test_cancel_requires_a_reason() -> None:
    """Səbəb MƏCBURİDİR: elanı görmüş işçi izahsız qalmamalıdır."""
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)

    with pytest.raises(DomainRuleError):
        harness.use_case.cancel_posting(
            tenant_id=TENANT, actor=admin, posting_id=posting.id, reason="qısa"
        )
    assert harness.postings.items[posting.id].status is OpenShiftStatus.OPEN


def test_cancel_closes_the_posting_and_writes_audit() -> None:
    harness = _harness()
    admin = _admin()
    posting = _post(harness, admin)

    harness.use_case.cancel_posting(
        tenant_id=TENANT,
        actor=admin,
        posting_id=posting.id,
        reason="Mağaza həmin gün bağlıdır",
    )

    stored = harness.postings.items[posting.id]
    assert stored.status is OpenShiftStatus.CANCELLED
    assert stored.cancelled_by == admin.id
    assert "OPEN_SHIFT_CANCELLED" in harness.audit.actions()


def test_cancel_requires_manage_flag() -> None:
    harness = _harness()
    posting = _post(harness, _admin())

    with pytest.raises(ShiftPermissionError):
        harness.use_case.cancel_posting(
            tenant_id=TENANT,
            actor=_employee(),
            posting_id=posting.id,
            reason="Səbəb kifayət qədər uzundur",
        )


# --------------------------------------------------------------------------- #
# 6. AQREQAT QAYDALARI (DB CHECK-lərinin domen güzgüsü)
# --------------------------------------------------------------------------- #


def _raw_posting(**overrides: Any) -> OpenShiftPosting:
    params: dict[str, Any] = {
        "posting_id": new_open_shift_posting_id(),
        "tenant_id": TENANT,
        "slot": OpenShiftSlot(store_id=STORE, shift_date=TOMORROW, work_mode_id=MODE),
        "posted_by": EmployeeId(uuid.uuid4()),
        "created_at": NOW,
    }
    params.update(overrides)
    return OpenShiftPosting(**params)


def test_claimed_state_without_owner_is_rejected() -> None:
    """`chk_open_shift_claim` məhdudiyyətinin domen tərəfi."""
    with pytest.raises(DomainRuleError):
        _raw_posting(status=OpenShiftStatus.CLAIMED)


def test_cancelled_state_without_actor_is_rejected() -> None:
    """`chk_open_shift_cancel` məhdudiyyətinin domen tərəfi."""
    with pytest.raises(DomainRuleError):
        _raw_posting(status=OpenShiftStatus.CANCELLED, cancel_reason="Səbəb yazılıb")


def test_restored_posting_does_not_emit_events() -> None:
    """Repository-dən bərpa hadisə YAYMIR — hər oxu bildiriş göndərərdi."""
    posting = _raw_posting(emit_created_event=False)
    assert posting.has_pending_events is False


def test_naive_timestamp_is_rejected() -> None:
    """CLAUDE.md §4: bütün `datetime` tz-aware olmalıdır."""
    with pytest.raises(Exception, match=r"naive|zona"):
        _raw_posting(created_at=datetime(2026, 8, 12, 9, 0))  # noqa: DTZ001


def test_posting_survives_a_deleted_author() -> None:
    """`ON DELETE SET NULL` — sahibsiz elan oxuna bilməlidir."""
    posting = _raw_posting(posted_by=None, emit_created_event=False)
    assert posting.posted_by is None
    assert posting.is_open is True
