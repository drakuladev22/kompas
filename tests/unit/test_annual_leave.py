"""İllik Məzuniyyət Balansı (#28) — kompas1.md Faza 4.

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR — VƏ NİYƏ MƏHZ BU
──────────────────────────────────────────────────────────────────────────────
Bu funksiyanın hesablamaları PUL dəyəri daşıyır (istifadə edilməmiş gün
kompensasiya oluna bilər), ona görə testlər "işləyirmi?" yox, "SƏHV HALDA nə
olur?" sualına cavab verir:

  A. İL SƏRHƏDİ — 31 dekabr → 1 yanvar keçidi və carry-over hesablanması.
  B. AYIN ORTASINDA İŞƏ DÜŞMƏ — proporsional haqq (GÜN dəqiqliyində).
  C. CARRY-OVER TAVANI — artıq gün İTİR, mənfi balans YARANMIR.
  D. LƏĞV — təsdiqlənmiş sorğu ləğv edilərsə balans GERİ QAYTARILIR.
  E. PARALEL SORĞU — balans mənfiyə düşmür; qapaq DB-dədir (şərti UPDATE +
     `rowcount`), tətbiq qatındakı oxu QƏRAR VERMİR.
  F. `EXCLUDE` POZUNTUSU — xam DB xətası deyil, aydın Azərbaycan mesajı.
  G. PLANLAYICI İDEMPOTENTLİYİ — at-least-once icra balansı ikiqat ARTIRMIR.
  H. VƏZİFƏ AYRILIĞI — flag-siz aktor təsdiq edə bilmir; işçi öz sorğusunu
     təsdiqləyə bilmir.
  I. ÜÇ KONSEPTİN AYRILIĞI — gündaxili icazənin aylıq 240 dəqiqəlik limiti və
     Shift Matrix-in yazma yolu TOXUNULMAMIŞ qalır.

Sahtələr BURADA, YERLİ təyin olunub (`tests/fixtures/fakes.py`-a əlavə
edilmir) — `test_field_reports.py`/`test_employee_documents.py` ilə eyni
əsaslandırma: bu fayl paralel işləyən başqa fazaların sahtə dəstindən asılı
olmamalıdır.

SAHTƏ BALANS REPO-SU DB DAVRANIŞINI GÜZGÜLƏYİR, SADƏLƏŞDİRMİR: `consume()`
şərti yoxlayıb `bool` qaytarır (`UPDATE ... WHERE used + d <= entitled +
carried` kimi), `set_entitlement()` isə TƏYİN edir və `updated_by IS NOT NULL`
sətrə toxunmur. Sahtə "həmişə uğurlu" olsaydı, E və G testləri yalançı-yaşıl
olardı.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.annual_leave import (
    DECIDED_NOTIFICATION_CATEGORY,
    MANAGE_LEAVE_BALANCES_FLAG,
    PENDING_NOTIFICATION_CATEGORY,
    AnnualLeaveError,
    AnnualLeavePermissionError,
    AnnualLeaveRequestNotFoundError,
    AnnualLeaveUseCase,
)
from src.domain.annual_leave_rules import (
    AccrualPeriod,
    AnnualLeavePolicy,
    LeaveDayCountMode,
)
from src.domain.entities.annual_leave import (
    CANCELLATION_PREFIX,
    AnnualLeaveBalance,
    AnnualLeaveRequest,
    AnnualLeaveStatus,
)
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.entities.shift import ShiftAssignment
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    AnnualLeaveBalanceId,
    AnnualLeaveRequestId,
    EmployeeId,
    PositionId,
    ShiftAssignmentId,
    StoreId,
    TenantId,
    WorkModeId,
    new_annual_leave_request_id,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
MODE = WorkModeId(uuid.uuid4())

#: Bakı UTC+4 — 09:00 UTC yerli 13:00-dır, yəni yerli gün UTC günü ilə eynidir.
#: Bu, təsadüfi seçim deyil: il sərhədi testləri məhz yerli günə baxır.
NOW = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)

MANAGE_FLAG = PermissionFlag(code=MANAGE_LEAVE_BALANCES_FLAG, category="HR")
OTHER_FLAG = PermissionFlag(code="can_fill_daily_attendance", category="HR")


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


@dataclass
class FakeClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


class FakeLimits:
    """`SystemLimits` — verilməyən açar üçün çağıranın defoltunu qaytarır."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def set(self, key: SystemLimitKey, value: str) -> None:
        self._values[key.value] = value

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return int(self._values.get(key, default))

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class FakeBalances:
    """`AnnualLeaveBalanceRepository` — DB davranışını GÜZGÜLƏYƏN sahtə.

    `consume()` şərti YOXLAYIR və `bool` qaytarır: real repo-da bu, şərti
    `UPDATE`-in `rowcount`-udur. Sahtə həmişə `True` qaytarsaydı, "iki paralel
    sorğu balansı mənfiyə salmır" testi heç nə sübut etməzdi.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, int], AnnualLeaveBalance] = {}
        #: `set_entitlement` çağırışlarının izi — idempotentlik testi üçün.
        self.entitlement_calls: list[tuple[uuid.UUID, int, Decimal, Decimal]] = []
        self.rollover_inputs: list[Any] = []
        self.expired_years: list[int] = []

    def seed(
        self,
        employee_id: EmployeeId,
        *,
        year: int,
        entitled: str = "21.00",
        used: str = "0.00",
        carried: str = "0.00",
        updated_by: EmployeeId | None = None,
    ) -> AnnualLeaveBalance:
        balance = AnnualLeaveBalance(
            balance_id=AnnualLeaveBalanceId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=employee_id,
            year=year,
            entitled_days=Decimal(entitled),
            used_days=Decimal(used),
            carried_over_days=Decimal(carried),
            updated_by=updated_by,
        )
        self.rows[(employee_id, year)] = balance
        return balance

    def get(self, employee_id: EmployeeId, *, year: int) -> AnnualLeaveBalance | None:
        return self.rows.get((employee_id, year))

    def list_for_year(
        self, tenant_id: TenantId, *, year: int, limit: int = 500
    ) -> list[AnnualLeaveBalance]:
        return [b for (_, y), b in self.rows.items() if y == year][:limit]

    def set_entitlement(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        year: int,
        entitled_days: Decimal,
        carried_over_days: Decimal,
        updated_by: EmployeeId | None,
    ) -> bool:
        self.entitlement_calls.append((employee_id, year, entitled_days, carried_over_days))
        existing = self.rows.get((employee_id, year))
        if existing is None:
            self.seed(
                employee_id,
                year=year,
                entitled=str(entitled_days),
                carried=str(carried_over_days),
                updated_by=updated_by,
            )
            return True
        # `WHERE annual_leave_balances.updated_by IS NULL OR EXCLUDED.updated_by
        # IS NOT NULL` — əl ilə düzəldilmiş sətrə SİSTEM yazısı toxunmur.
        if existing.updated_by is not None and updated_by is None:
            return False
        existing.set_entitlement(
            entitled_days=entitled_days,
            carried_over_days=carried_over_days,
            updated_by=updated_by,
        )
        return True

    def consume(self, *, employee_id: EmployeeId, year: int, days: Decimal) -> bool:
        balance = self.rows.get((employee_id, year))
        if balance is None:
            return False
        if balance.used_days + days > balance.entitled_days + balance.carried_over_days:
            return False
        balance.used_days = balance.used_days + days
        return True

    def release(self, *, employee_id: EmployeeId, year: int, days: Decimal) -> bool:
        balance = self.rows.get((employee_id, year))
        if balance is None:
            return False
        balance.release(days)
        return True

    def expire_carryover(self, *, tenant_id: TenantId, year: int) -> int:
        self.expired_years.append(year)
        touched = 0
        for (_, row_year), balance in self.rows.items():
            if row_year != year:
                continue
            if balance.carried_over_days > balance.used_days:
                balance.expire_carryover()
                touched += 1
        return touched

    def list_rollover_inputs(self, tenant_id: TenantId, *, year: int) -> list[Any]:
        return list(self.rollover_inputs)


class FakeRequests:
    """`AnnualLeaveRequestRepository` — `EXCLUDE` qapağı DA güzgülənir."""

    def __init__(self) -> None:
        self.rows: dict[AnnualLeaveRequestId, AnnualLeaveRequest] = {}
        self.locked: list[AnnualLeaveRequestId] = []
        #: `save()` növbəti çağırışda bu istisnanı atır — repo-nun `EXCLUDE`
        #: tərcüməsini use case səviyyəsində sınamaq üçün.
        self.raise_on_save: Exception | None = None

    def get(self, request_id: AnnualLeaveRequestId) -> AnnualLeaveRequest | None:
        return self.rows.get(request_id)

    def get_for_update(self, request_id: AnnualLeaveRequestId) -> AnnualLeaveRequest | None:
        self.locked.append(request_id)
        return self.rows.get(request_id)

    def list_pending(self, tenant_id: TenantId, *, limit: int = 200) -> list[AnnualLeaveRequest]:
        return sorted(
            (r for r in self.rows.values() if r.status is AnnualLeaveStatus.PENDING_APPROVAL),
            key=lambda r: r.start_date,
        )[:limit]

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int = 50
    ) -> list[AnnualLeaveRequest]:
        return [r for r in self.rows.values() if r.employee_id == employee_id][:limit]

    def find_overlapping_approved(
        self, employee_id: EmployeeId, *, start: date, end: date
    ) -> AnnualLeaveRequest | None:
        for request in self.rows.values():
            if request.employee_id != employee_id:
                continue
            if request.status is not AnnualLeaveStatus.APPROVED:
                continue
            if request.start_date <= end and start <= request.end_date:
                return request
        return None

    def save(self, request: AnnualLeaveRequest) -> None:
        if self.raise_on_save is not None:
            error, self.raise_on_save = self.raise_on_save, None
            raise error
        self.rows[request.id] = request


class FakeShifts:
    """`ShiftRepository` — YALNIZ `list_range()` çağırılmalıdır.

    Yazma metodları çağırılsa test DƏRHAL qırılır: təsdiqlənmiş məzuniyyət
    Shift Matrix-i DƏYİŞMİR (üç konseptin ayrılığı).
    """

    def __init__(self, off_days: set[date] | None = None) -> None:
        self.off_days = off_days or set()
        self.range_calls = 0

    def list_range(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
        employee_ids: list[EmployeeId] | None = None,
    ) -> list[ShiftAssignment]:
        self.range_calls += 1
        employee_id = (employee_ids or [EmployeeId(uuid.uuid4())])[0]
        result: list[ShiftAssignment] = []
        cursor = start
        while cursor <= end:
            if cursor in self.off_days:
                result.append(
                    ShiftAssignment(
                        assignment_id=ShiftAssignmentId(uuid.uuid4()),
                        tenant_id=tenant_id,
                        employee_id=employee_id,
                        shift_date=cursor,
                        is_off_day=True,
                    )
                )
            cursor += timedelta(days=1)
        return result

    def save_assignment(self, assignment: ShiftAssignment) -> None:  # pragma: no cover
        raise AssertionError("İllik məzuniyyət Shift Matrix-ə YAZMAMALIDIR")

    def clear_assignment(self, employee_id: EmployeeId, work_date: date) -> None:
        raise AssertionError("İllik məzuniyyət Shift Matrix-ə YAZMAMALIDIR")  # pragma: no cover


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(entry["action"]) for entry in self.entries]


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> None:
        self.messages.append(kwargs)

    def categories(self) -> list[str]:
        return [str(message["category"]) for message in self.messages]


@dataclass
class Harness:
    use_case: AnnualLeaveUseCase
    balances: FakeBalances
    requests: FakeRequests
    shifts: FakeShifts
    audit: RecordingAudit
    notifier: RecordingNotifier
    clock: FakeClock
    limits: FakeLimits
    employees: list[Employee] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def make_employee(
    *,
    flags: list[PermissionFlag] | None = None,
    role: SystemRole = SystemRole.SELLER,
    hire_date: date | None = date(2020, 1, 1),
) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value.title(),
        priority=role.default_priority,
        is_system=True,
    )
    for flag in flags or []:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="A",
        last_name="İşçi",
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
        hire_date=hire_date,
    )


def build(
    *,
    limits: dict[str, str] | None = None,
    off_days: set[date] | None = None,
    now: datetime = NOW,
) -> Harness:
    clock = FakeClock(now)
    balances = FakeBalances()
    requests = FakeRequests()
    shifts = FakeShifts(off_days)
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    fake_limits = FakeLimits(limits)
    use_case = AnnualLeaveUseCase(
        balances=balances,  # type: ignore[arg-type]
        requests=requests,  # type: ignore[arg-type]
        shifts=shifts,  # type: ignore[arg-type]
        limits=fake_limits,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
    )
    return Harness(
        use_case=use_case,
        balances=balances,
        requests=requests,
        shifts=shifts,
        audit=audit,
        notifier=notifier,
        clock=clock,
        limits=fake_limits,
    )


def approved_request(
    harness: Harness,
    *,
    employee: Employee,
    approver: Employee,
    start: date,
    end: date,
) -> AnnualLeaveRequest:
    request = harness.use_case.submit(
        tenant_id=TENANT, employee=employee, start_date=start, end_date=end
    )
    return harness.use_case.approve(
        tenant_id=TENANT, approver=approver, request_id=request.id, employee=employee
    )


# --------------------------------------------------------------------------- #
# A. İL SƏRHƏDİ VƏ CARRY-OVER
# --------------------------------------------------------------------------- #


class TestYearBoundary:
    def test_31_dekabrdan_1_yanvara_kecid_carry_over_yaradir(self) -> None:
        """Yeni ilin ilk gecəsi keçən ilin qalığı köçürülür.

        Bu, funksiyanın ən görünməz sərhədidir: iş `DAILY` işlədiyi üçün
        31 dekabr gecəsi 2026-nı, 1 yanvar gecəsi 2027-ni hesablayır.
        Köçürmə YENİ ilin sətrində görünməlidir — köhnə sətrə toxunulmamalıdır.
        """
        from src.domain.annual_leave_rules import AnnualLeaveRolloverInput

        employee = make_employee()
        # 1 yanvar 2027, yerli saat 03:00 (planlayıcının gecə slotu).
        harness = build(now=datetime(2026, 12, 31, 23, 0, tzinfo=UTC))
        harness.balances.rollover_inputs = [
            AnnualLeaveRolloverInput(
                employee_id=employee.id,
                hire_date=date(2020, 1, 1),
                previous_available_days=Decimal("4.00"),
            )
        ]

        report = harness.use_case.run_year_rollover(tenant_id=TENANT, now=harness.clock.now())

        assert report.year == 2027, "Yerli gün UTC+4-dədir — 1 yanvar hesablanmalıdır"
        new_balance = harness.balances.get(employee.id, year=2027)
        assert new_balance is not None
        assert new_balance.carried_over_days == Decimal("4.00")
        assert report.carried_over_days == Decimal("4.00")
        assert report.forfeited_days == Decimal("0.00")

    def test_il_serhedini_kesen_sorgu_baslangic_ilinden_cixilir(self) -> None:
        """28 dekabr – 3 yanvar sorğusu BÜTÜNLÜKLƏ 2026-dan çıxılır.

        Bölgü QƏSDƏN yoxdur: `deducted_days` TƏK sütundur və illər arası
        bölgü dondurula bilməzdi — ləğv zamanı balansa DƏQİQ çıxılan ədəd
        qaytarılmalıdır (bax `AnnualLeaveUseCase._charge_year`).
        """
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build(now=datetime(2026, 12, 1, 9, 0, tzinfo=UTC))
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        harness.balances.seed(employee.id, year=2027, entitled="21.00")

        approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 12, 28),
            end=date(2027, 1, 3),
        )

        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("7.00")
        assert harness.balances.get(employee.id, year=2027).used_days == Decimal("0.00")


# --------------------------------------------------------------------------- #
# B. AYIN ORTASINDA İŞƏ DÜŞMƏ — PROPORSİONAL HAQQ
# --------------------------------------------------------------------------- #


class TestProportionalAccrual:
    def test_ayin_ortasinda_ise_dusen_isci_proporsional_haqq_alir(self) -> None:
        """15 mart 2026-da işə düşən işçi ilin 292/365 hissəsini qazanır."""
        policy = AnnualLeavePolicy.defaults()

        entitlement = policy.entitlement_for_year(
            year=2026, hire_date=date(2026, 3, 15), as_of=date(2026, 12, 31)
        )

        # 15 mart – 31 dekabr = 292 gün. 21 × 292/365 = 16.8 → 16.80.
        assert entitlement.days == Decimal("16.80")
        assert entitlement.base_days == Decimal("21.00")

    def test_proporsiya_gun_deqiqliyindedir_ay_deqiqliyinde_yox(self) -> None:
        """Ayın 1-də və 28-də işə düşən iki işçi EYNİ haqqı almamalıdır.

        Ay yuvarlaqlaşdırması real pul fərqini gizlədərdi və mübahisə
        mövzusudur (bax `entitlement_for_year` docstring-i).
        """
        policy = AnnualLeavePolicy.defaults()

        first = policy.entitlement_for_year(
            year=2026, hire_date=date(2026, 3, 1), as_of=date(2026, 12, 31)
        )
        late = policy.entitlement_for_year(
            year=2026, hire_date=date(2026, 3, 28), as_of=date(2026, 12, 31)
        )

        assert first.days > late.days

    def test_ilden_evvel_ise_dusen_isci_tam_haqq_alir(self) -> None:
        """Keçən ilin heç bir günü bu ilin haqqına qatılmır."""
        policy = AnnualLeavePolicy.defaults()

        entitlement = policy.entitlement_for_year(
            year=2026, hire_date=date(2019, 7, 1), as_of=date(2026, 6, 15)
        )

        # 21 baza + 1 staj (7 il ÷ 5 il dövr = 1 addım).
        assert entitlement.days == Decimal("22.00")
        assert entitlement.seniority_days == Decimal("1.00")

    def test_gelecek_ilde_ise_duseceek_isci_haqq_almir(self) -> None:
        """Hələ işə düşməmiş işçi keçmiş ilin haqqını qabaqcadan almır."""
        policy = AnnualLeavePolicy.defaults()

        entitlement = policy.entitlement_for_year(
            year=2026, hire_date=date(2027, 2, 1), as_of=date(2026, 12, 31)
        )

        assert entitlement.days == Decimal("0")

    def test_staj_ildonumu_kecmeyibse_sayilmir(self) -> None:
        """31 dekabr 2025-də işə düşən işçi 1 yanvar 2026-da 1 illik STAJ QAZANMIR."""
        policy = AnnualLeavePolicy.defaults()

        bonus = policy.seniority_bonus(hire_date=date(2020, 12, 31), as_of=date(2025, 12, 30))

        assert bonus == Decimal("0"), "5 illik dövr hələ tamamlanmayıb"

    def test_staj_elavesi_tavanda_dayanir(self) -> None:
        """40 illik stajda əlavə tavandan (5 gün) YUXARI qalxmır."""
        policy = AnnualLeavePolicy.defaults()

        bonus = policy.seniority_bonus(hire_date=date(1986, 1, 1), as_of=date(2026, 6, 15))

        assert bonus == Decimal("5.00")

    def test_aylik_accrual_yalniz_tamamlanmis_dovru_sayir(self) -> None:
        """`MONTHLY` rejimində iyunun ortasında 5 tam ay qazanılıb."""
        policy = AnnualLeavePolicy.from_limits(
            {SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_PERIOD.value: "MONTHLY"}
        )

        entitlement = policy.entitlement_for_year(
            year=2026, hire_date=date(2020, 1, 1), as_of=date(2026, 6, 15)
        )

        assert policy.accrual_period is AccrualPeriod.MONTHLY
        # 22 (21 + 1 staj) × 5/12 = 9.166... → 9.17.
        assert entitlement.days == Decimal("9.17")


# --------------------------------------------------------------------------- #
# C. CARRY-OVER TAVANI — ARTIQ GÜN İTİR, MƏNFİ BALANS YARANMIR
# --------------------------------------------------------------------------- #


class TestCarryOverCeiling:
    def test_tavani_asan_gun_itir_menfi_balans_yaranmir(self) -> None:
        policy = AnnualLeavePolicy.defaults()

        carried = policy.carry_over(unused_days=Decimal("12.00"))
        forfeited = policy.forfeited_days(unused_days=Decimal("12.00"))

        assert carried == Decimal("5.00"), "Tavan `ANNUAL_LEAVE_CARRYOVER_MAX_DAYS`-dir"
        assert forfeited == Decimal("7.00"), "Artıq gün İTİR"
        assert carried + forfeited == Decimal("12.00"), "Heç bir gün sükutla yox olmur"

    def test_menfi_qaliq_hec_vaxt_kocurulmur(self) -> None:
        """Tarixi idxaldan gələ biləcək mənfi qalıq növbəti ili azaltmamalıdır."""
        policy = AnnualLeavePolicy.defaults()

        assert policy.carry_over(unused_days=Decimal("-3.00")) == Decimal("0.00")
        assert policy.forfeited_days(unused_days=Decimal("-3.00")) == Decimal("0.00")

    def test_kocurme_tavani_root_parametridir(self) -> None:
        """Root tavanı dəyişdikdə HESABLAMA DA DƏYİŞİR (hardcode yoxdur)."""
        policy = AnnualLeavePolicy.from_limits(
            {SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_MAX_DAYS.value: "10.00"}
        )

        assert policy.carry_over(unused_days=Decimal("12.00")) == Decimal("10.00")

    def test_istifade_et_ya_itir_son_tarixi_ayin_uzunluguna_sixilir(self) -> None:
        """Root "fevralın 31-i" yazsa, gecəlik iş ÇÖKMƏMƏLİDİR."""
        policy = AnnualLeavePolicy.from_limits(
            {
                SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH.value: "2",
                SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY.value: "31",
            }
        )

        assert policy.carryover_deadline(2026) == date(2026, 2, 28)
        assert policy.carryover_deadline(2028) == date(2028, 2, 29), "Uzun il"

    def test_son_tarix_daxildir(self) -> None:
        """31 martda hələ istifadə etmək olar, 1 apreldə yox."""
        policy = AnnualLeavePolicy.defaults()

        assert not policy.is_carryover_expired(year=2026, as_of=date(2026, 3, 31))
        assert policy.is_carryover_expired(year=2026, as_of=date(2026, 4, 1))

    def test_kocurmenin_silinmesi_balansi_menfiye_salmir(self) -> None:
        """`LEAST(carried, used)` `used <= entitled + carried` şərtini pozmur."""
        employee = make_employee()
        balances = FakeBalances()
        balance = balances.seed(
            employee.id, year=2026, entitled="21.00", used="2.00", carried="5.00"
        )

        expired = balance.expire_carryover()

        assert expired == Decimal("3.00")
        assert balance.carried_over_days == Decimal("2.00")
        assert balance.used_days <= balance.entitled_days + balance.carried_over_days
        assert balance.available_days >= Decimal("0")


# --------------------------------------------------------------------------- #
# D. LƏĞV — BALANS GERİ QAYTARILIR
# --------------------------------------------------------------------------- #


class TestCancellation:
    def test_tesdiqlenmis_sorgu_legv_edilerse_balans_geri_qayidir(self) -> None:
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 5),
        )
        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("5.00")

        harness.use_case.cancel(
            tenant_id=TENANT,
            actor=employee,
            request_id=request.id,
            reason="Səfər ləğv edildi, planlar dəyişdi",
        )

        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("0.00")
        assert "ANNUAL_LEAVE_CANCELLED" in harness.audit.actions()

    def test_legv_qeydi_redd_qerarindan_ferqlenir(self) -> None:
        """`CANCELLED` statusu yoxdur, lakin fərq İTMİR (bax entity başlığı)."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 5),
        )

        cancelled = harness.use_case.cancel(
            tenant_id=TENANT,
            actor=approver,
            request_id=request.id,
            reason="Mağazada kadr çatışmazlığı yarandı",
        )

        assert cancelled.status is AnnualLeaveStatus.REJECTED
        assert cancelled.is_cancelled
        assert cancelled.decision_note is not None
        assert cancelled.decision_note.startswith(CANCELLATION_PREFIX)

    def test_baslamis_mezuniyyet_legv_edilmir(self) -> None:
        """Günlərin bir hissəsi FAKTİKİ istifadə olunub — tam qaytarma səhv olardı."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 6, 15),
            end=date(2026, 6, 20),
        )

        with pytest.raises(DomainRuleError):
            harness.use_case.cancel(
                tenant_id=TENANT,
                actor=employee,
                request_id=request.id,
                reason="Fikrimi dəyişdim, işə qayıtmaq istəyirəm",
            )

        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("6.00")

    def test_ucuncu_sexs_basqasinin_mezuniyyetini_legv_ede_bilmir(self) -> None:
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        stranger = make_employee(flags=[OTHER_FLAG])
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 5),
        )

        with pytest.raises(AnnualLeavePermissionError):
            harness.use_case.cancel(
                tenant_id=TENANT,
                actor=stranger,
                request_id=request.id,
                reason="Mənim xoşuma gəlmədi, ləğv edirəm",
            )

    def test_legv_dondurulmus_gunu_qaytarir_yeniden_hesablamir(self) -> None:
        """Təsdiqdən sonra Shift Matrix dəyişsə də qaytarılan ədəd DƏYİŞMİR."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 5),
        )
        # Matris SONRADAN dəyişdi: indi üç gün istirahətdir.
        harness.shifts.off_days = {date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 4)}

        harness.use_case.cancel(
            tenant_id=TENANT,
            actor=employee,
            request_id=request.id,
            reason="Səfər təxirə salındı, tarix dəyişəcək",
        )

        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("0.00")


# --------------------------------------------------------------------------- #
# E. PARALEL SORĞU — DB-SƏVİYYƏLİ QORUMA
# --------------------------------------------------------------------------- #


class TestConcurrency:
    def test_iki_paralel_tesdiq_balansi_menfiye_salmir(self) -> None:
        """İkinci təsdiq `consume()` `False` qaytardığı üçün UDUZUR.

        Bu, tətbiq qatındakı "əvvəlcə oxu" yoxlamasının nəticəsi DEYİL: hər
        iki sorğu təsdiq anına qədər balansı "kifayətdir" görürdü. Qərarı
        şərti `UPDATE` verir (`open_shift_repository.claim` naxışı).
        """
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="8.00")

        first = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )
        second = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        harness.use_case.approve(
            tenant_id=TENANT, approver=approver, request_id=first.id, employee=employee
        )
        with pytest.raises(AnnualLeaveError) as exc:
            harness.use_case.approve(
                tenant_id=TENANT, approver=approver, request_id=second.id, employee=employee
            )

        balance = harness.balances.get(employee.id, year=2026)
        assert balance.used_days == Decimal("5.00")
        assert balance.available_days == Decimal("3.00")
        assert balance.available_days >= Decimal("0"), "Balans MƏNFİYƏ düşməməlidir"
        assert "gün" in exc.value.user_message

    def test_uduzan_tesdiq_sorgunu_tesdiqlenmis_kimi_yazmir(self) -> None:
        """Balans azalmadısa sorğu da təsdiqlənmiş sayılmamalıdır."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="2.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
        )
        # Balans sorğudan SONRA əl ilə sıfırlandı (HR düzəlişi).
        harness.balances.get(employee.id, year=2026).entitled_days = Decimal("0.00")

        with pytest.raises(AnnualLeaveError):
            harness.use_case.approve(
                tenant_id=TENANT, approver=approver, request_id=request.id, employee=employee
            )

        assert harness.requests.rows[request.id].status is AnnualLeaveStatus.PENDING_APPROVAL

    def test_yazma_yolu_setri_kilidleyir(self) -> None:
        """`get_for_update()` işlədilir — kilidsiz oxu yarışı udmazdı."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
        )

        harness.use_case.approve(
            tenant_id=TENANT, approver=approver, request_id=request.id, employee=employee
        )

        assert request.id in harness.requests.locked


# --------------------------------------------------------------------------- #
# F. `EXCLUDE` POZUNTUSU AYDIN AZƏRBAYCAN MESAJINA ÇEVRİLİR
# --------------------------------------------------------------------------- #


class TestOverlapGuard:
    def test_exclude_pozuntusu_xam_db_xetasi_kimi_gormunmur(self) -> None:
        """Repo `ExclusionViolation`-u tutub izahlı mesaja çevirir.

        Sahtə repo-nun ATDIĞI istisna REAL repo-nun tərcüməsidir: burada
        yoxlanan şey mesajın use case-dən keçib DƏYİŞMƏDƏN çıxmasıdır —
        yəni heç bir qat onu "gözlənilməz xəta"ya çevirmir.
        """
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )
        harness.requests.raise_on_save = AnnualLeaveError(
            "Təsdiqlənmiş məzuniyyət aralıqları kəsişir (DB EXCLUDE qapağı)",
            user_message=(
                "Bu tarixlər üçün artıq təsdiqlənmiş məzuniyyətiniz var. Başqa tarix seçin."
            ),
        )

        with pytest.raises(AnnualLeaveError) as exc:
            harness.use_case.approve(
                tenant_id=TENANT, approver=approver, request_id=request.id, employee=employee
            )

        assert "artıq təsdiqlənmiş məzuniyyətiniz var" in exc.value.user_message
        assert "EXCLUDE" not in exc.value.user_message, "Xam DB termini ekrana çıxmamalıdır"
        assert "conflicting key value" not in exc.value.user_message

    def test_exclude_pozuntusunda_balans_geri_qaytarilir(self) -> None:
        """Kompensasiya: sorğu yazılmadısa balans da azalmış qalmamalıdır."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )
        harness.requests.raise_on_save = AnnualLeaveError("EXCLUDE")

        with pytest.raises(AnnualLeaveError):
            harness.use_case.approve(
                tenant_id=TENANT, approver=approver, request_id=request.id, employee=employee
            )

        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("0.00")

    def test_ust_uste_dusen_sorgu_formada_erken_kesilir(self) -> None:
        """Qapağı ƏVƏZ ETMİR — istifadəçi səbəbi formanı doldurmadan görür."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 5),
        )

        with pytest.raises(AnnualLeaveError) as exc:
            harness.use_case.submit(
                tenant_id=TENANT,
                employee=employee,
                start_date=date(2026, 7, 4),
                end_date=date(2026, 7, 8),
            )

        assert "artıq təsdiqlənmiş məzuniyyətiniz var" in exc.value.user_message


# --------------------------------------------------------------------------- #
# G. PLANLAYICI İŞİ İDEMPOTENTDİR
# --------------------------------------------------------------------------- #


class TestSchedulerIdempotency:
    def test_eyni_il_ucun_ikinci_icra_balansi_ikiqat_artirmir(self) -> None:
        """`at-least-once` zəmanəti: haqq TƏYİN edilir, ARTIRILMIR.

        Saat 5 YANVARDIR, iyun deyil: "istifadə et ya itir" son tarixi
        (31 mart) hələ keçməyib, ona görə köçürmə sətirdə QALIR və testin
        ölçdüyü şey məhz idempotentlik olur, son tarixin təsiri yox.
        """
        from src.domain.annual_leave_rules import AnnualLeaveRolloverInput

        employee = make_employee()
        harness = build(now=datetime(2026, 1, 5, 3, 0, tzinfo=UTC))
        harness.balances.rollover_inputs = [
            AnnualLeaveRolloverInput(
                employee_id=employee.id,
                hire_date=date(2020, 1, 1),
                previous_available_days=Decimal("3.00"),
            )
        ]

        first = harness.use_case.run_year_rollover(tenant_id=TENANT, now=harness.clock.now())
        second = harness.use_case.run_year_rollover(tenant_id=TENANT, now=harness.clock.now())

        balance = harness.balances.get(employee.id, year=2026)
        assert balance.entitled_days == Decimal("22.00")
        assert balance.carried_over_days == Decimal("3.00")
        assert first.carried_over_days == second.carried_over_days
        assert len(harness.balances.entitlement_calls) == 2, "İkinci icra HƏQİQƏTƏN işlədi"

    def test_uc_icra_da_eyni_neticeni_verir(self) -> None:
        """İdempotentlik "iki dəfə"də deyil, İSTƏNİLƏN sayda icrada qalmalıdır."""
        from src.domain.annual_leave_rules import AnnualLeaveRolloverInput

        employee = make_employee()
        harness = build(now=datetime(2026, 1, 5, 3, 0, tzinfo=UTC))
        harness.balances.rollover_inputs = [
            AnnualLeaveRolloverInput(
                employee_id=employee.id,
                hire_date=date(2020, 1, 1),
                previous_available_days=Decimal("9.00"),
            )
        ]

        snapshots = []
        for _ in range(3):
            harness.use_case.run_year_rollover(tenant_id=TENANT, now=harness.clock.now())
            balance = harness.balances.get(employee.id, year=2026)
            snapshots.append((balance.entitled_days, balance.carried_over_days, balance.used_days))

        assert len(set(snapshots)) == 1, f"İcralar ayrıldı: {snapshots}"

    def test_el_ile_duzeldilmis_setre_gece_isi_toxunmur(self) -> None:
        """`updated_by IS NOT NULL` — HR düzəlişi səhər geri qaytarılmamalıdır."""
        from src.domain.annual_leave_rules import AnnualLeaveRolloverInput

        employee = make_employee()
        hr = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(
            employee.id, year=2026, entitled="30.00", carried="0.00", updated_by=hr.id
        )
        harness.balances.rollover_inputs = [
            AnnualLeaveRolloverInput(
                employee_id=employee.id,
                hire_date=date(2020, 1, 1),
                previous_available_days=Decimal("0.00"),
            )
        ]

        report = harness.use_case.run_year_rollover(tenant_id=TENANT, now=harness.clock.now())

        assert harness.balances.get(employee.id, year=2026).entitled_days == Decimal("30.00")
        assert report.manual_rows_skipped == 1
        assert report.balances_written == 0

    def test_istifade_et_ya_itir_yalniz_son_tarixden_sonra_islenir(self) -> None:
        employee = make_employee()
        early = build(now=datetime(2026, 3, 30, 9, 0, tzinfo=UTC))
        early.balances.seed(employee.id, year=2026, entitled="21.00", carried="5.00")
        late = build(now=datetime(2026, 4, 2, 9, 0, tzinfo=UTC))
        late.balances.seed(employee.id, year=2026, entitled="21.00", carried="5.00")

        early_report = early.use_case.run_year_rollover(tenant_id=TENANT, now=early.clock.now())
        late_report = late.use_case.run_year_rollover(tenant_id=TENANT, now=late.clock.now())

        assert early.balances.expired_years == []
        assert early_report.expired_carryover_rows == 0
        assert late.balances.expired_years == [2026]
        assert late_report.expired_carryover_rows == 1
        assert late.balances.get(employee.id, year=2026).carried_over_days == Decimal("0.00")

    def test_rollover_audit_setri_sistem_aktoru_ile_yazilir(self) -> None:
        """Gecə işinə süni "istifadəçi" uydurulmur (`JobRunner` ilə eyni qərar)."""
        harness = build()

        harness.use_case.run_year_rollover(tenant_id=TENANT, now=harness.clock.now())

        entry = harness.audit.entries[-1]
        assert entry["action"] == "ANNUAL_LEAVE_YEAR_ROLLOVER"
        assert entry["actor_id"] is None


# --------------------------------------------------------------------------- #
# H. VƏZİFƏ AYRILIĞI
# --------------------------------------------------------------------------- #


class TestSeparationOfDuties:
    def test_flagsiz_aktor_tesdiq_ede_bilmir(self) -> None:
        """Səlahiyyət yoxlaması sükutla "heç nə etmə" DEYİL — açıq istisna."""
        employee = make_employee()
        outsider = make_employee(flags=[OTHER_FLAG])
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )

        with pytest.raises(AnnualLeavePermissionError):
            harness.use_case.approve(
                tenant_id=TENANT, approver=outsider, request_id=request.id, employee=employee
            )

        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("0.00")
        assert harness.requests.rows[request.id].status is AnnualLeaveStatus.PENDING_APPROVAL

    def test_flagsiz_aktor_redd_de_ede_bilmir(self) -> None:
        employee = make_employee()
        outsider = make_employee(flags=[OTHER_FLAG])
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )

        with pytest.raises(AnnualLeavePermissionError):
            harness.use_case.reject(
                tenant_id=TENANT,
                approver=outsider,
                request_id=request.id,
                reason="Bu tarixlərdə kadr çatışmır",
            )

    def test_isci_oz_sorgusunu_tesdiqleye_bilmir(self) -> None:
        """Flag OLSA BELƏ — qayda entity-dədir, ekranı yan keçən skript də tabedir."""
        employee = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )

        with pytest.raises(DomainRuleError) as exc:
            harness.use_case.approve(
                tenant_id=TENANT, approver=employee, request_id=request.id, employee=employee
            )

        assert "Öz sorğunuza" in exc.value.user_message
        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("0.00")

    def test_isci_oz_sorgusunu_redd_de_ede_bilmir(self) -> None:
        employee = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )

        with pytest.raises(DomainRuleError):
            harness.use_case.reject(
                tenant_id=TENANT,
                approver=employee,
                request_id=request.id,
                reason="Özüm özümə icazə vermirəm",
            )

    def test_isci_oz_balansini_flagsiz_gore_bilir(self) -> None:
        """Öz haqqını görmək üçün idarəetmə flag-i tələb etmək səhv olardı."""
        employee = make_employee()
        harness = build()

        view = harness.use_case.my_balance(tenant_id=TENANT, employee=employee)

        assert view.year == 2026
        assert view.total_days > Decimal("0")

    def test_basqasinin_balansi_ucun_flag_teleb_olunur(self) -> None:
        employee = make_employee()
        outsider = make_employee(flags=[OTHER_FLAG])
        harness = build()

        with pytest.raises(AnnualLeavePermissionError):
            harness.use_case.balance_for(tenant_id=TENANT, actor=outsider, employee=employee)

    def test_redd_sebebi_mecburidir(self) -> None:
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )

        with pytest.raises(DomainRuleError):
            harness.use_case.reject(
                tenant_id=TENANT, approver=approver, request_id=request.id, reason="yox"
            )

    def test_qerar_terminaldir(self) -> None:
        """Təsdiqlənmiş sorğu sonradan RƏDD EDİLƏ bilməz (`ShiftSwapRequest` naxışı)."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 5),
        )

        with pytest.raises(DomainRuleError):
            harness.use_case.reject(
                tenant_id=TENANT,
                approver=approver,
                request_id=request.id,
                reason="Fikrimizi dəyişdik, təsdiqi geri alırıq",
            )

    def test_tapilmayan_sorgu_aydin_istisna_verir(self) -> None:
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        employee = make_employee()
        harness = build()

        with pytest.raises(AnnualLeaveRequestNotFoundError):
            harness.use_case.approve(
                tenant_id=TENANT,
                approver=approver,
                request_id=new_annual_leave_request_id(),
                employee=employee,
            )


# --------------------------------------------------------------------------- #
# I. GÜN SAYMA — İSTİRAHƏT/BAYRAM QƏRARI
# --------------------------------------------------------------------------- #


class TestDayCounting:
    def test_istirahet_gunu_balansdan_cixilmir(self) -> None:
        """Defolt `WORKING_DAYS`: Shift Matrix-dəki off-day ödənilmir."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build(off_days={date(2026, 7, 4), date(2026, 7, 5)})
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 7),
        )

        assert request.calendar_days == 7
        assert request.deducted_days == Decimal("5.00")
        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("5.00")

    def test_planlasdirilmamis_gun_is_gunu_sayilir(self) -> None:
        """Matrisdə sətri olmayan gün İSTİRAHƏT sayılsaydı məzuniyyət pulsuz olardı."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build(off_days=set())
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 9, 1),
            end=date(2026, 9, 10),
        )

        assert request.deducted_days == Decimal("10.00")

    def test_calendar_days_rejimi_root_parametridir(self) -> None:
        """Qanuni oxunuş (təqvim günü) kod dəyişikliyi olmadan seçilə bilir."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build(off_days={date(2026, 7, 4), date(2026, 7, 5)})
        harness.limits.set(SystemLimitKey.ANNUAL_LEAVE_DAY_COUNT_MODE, "CALENDAR_DAYS")
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 7),
        )

        assert request.deducted_days == Decimal("7.00")

    def test_tam_istirahete_dusen_sorgu_sifir_gun_cixarir(self) -> None:
        """SIFIR qanuni haldır — DB `CHECK`-i də `>= 0` yazır, `> 0` yox."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build(off_days={date(2026, 7, 4), date(2026, 7, 5)})
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 4),
            end=date(2026, 7, 5),
        )

        assert request.deducted_days == Decimal("0.00")
        assert request.status is AnnualLeaveStatus.APPROVED

    def test_gun_sayma_bir_sql_sorgusu_ile_aparilir(self) -> None:
        """21 günlük sorğu üçün 21 ayrı `is_off_day()` çağırışı olmamalıdır."""
        employee = make_employee()
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="30.00")

        harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 21),
        )

        assert harness.shifts.range_calls == 1


# --------------------------------------------------------------------------- #
# J. ÜÇ KONSEPTİN AYRILIĞI
# --------------------------------------------------------------------------- #


class TestThreeConceptsStaySeparate:
    def test_illik_mezuniyyet_shift_matrixe_yazmir(self) -> None:
        """`FakeShifts` yazma metodları çağırılsa DƏRHAL qırılır."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 3),
        )

        # Sınaq açıq olsun deyə metod BURADA da yoxlanılır: çağırılsaydı,
        # `AssertionError` yuxarıdakı təsdiqdə partlayardı.
        assert harness.shifts.range_calls > 0, "Matris YALNIZ OXUNMALIDIR"

    def test_aylik_240_deqiqelik_limit_illik_balansa_toxunmur(self) -> None:
        """`MONTHLY_LEAVE_MINUTES_LIMIT` gündaxili icazənindir — burada işlənmir."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.limits.set(SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT, "0")
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        request = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 3),
        )

        assert request.status is AnnualLeaveStatus.APPROVED
        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("3.00")

    def test_illik_mezuniyyet_ayri_bildiris_kanali_islediyir(self) -> None:
        """`SHIFT_SWAP_*` kateqoriyaları ilə qarışmır."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 3),
        )

        assert harness.notifier.categories() == [
            PENDING_NOTIFICATION_CATEGORY,
            DECIDED_NOTIFICATION_CATEGORY,
        ]
        assert not any("SHIFT_SWAP" in c for c in harness.notifier.categories())

    def test_repository_berpasi_hadise_yaymir(self) -> None:
        """Hər siyahı oxunuşu "yeni sorğu" bildirişi göndərməməlidir."""
        restored = AnnualLeaveRequest(
            request_id=new_annual_leave_request_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
            created_at=NOW,
            emit_created_event=False,
        )

        assert not restored.has_pending_events

    def test_yeni_sorgu_hadise_toplayir(self) -> None:
        """Aqreqat hadisəni TOPLAYIR (commit-dən sonra yayımlanacaq)."""
        fresh = AnnualLeaveRequest(
            request_id=new_annual_leave_request_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
            created_at=NOW,
        )

        assert fresh.has_pending_events


# --------------------------------------------------------------------------- #
# K. ROOT PARAMETRLƏRİ — HARDCODE QALMAYIB
# --------------------------------------------------------------------------- #


class TestRootParameters:
    def test_siyaset_defoltlari_default_limits_den_gelir(self) -> None:
        """`annual_leave_rules.py`-da ƏDƏDİ SABİT olmamalıdır."""
        policy = AnnualLeavePolicy.defaults()

        assert policy.base_entitlement_days == Decimal(
            DEFAULT_LIMITS[SystemLimitKey.ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS]
        )
        assert policy.carryover_max_days == Decimal(
            DEFAULT_LIMITS[SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_MAX_DAYS]
        )
        assert policy.accrual_period is AccrualPeriod(
            DEFAULT_LIMITS[SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_PERIOD]
        )
        assert policy.day_count_mode is LeaveDayCountMode(
            DEFAULT_LIMITS[SystemLimitKey.ANNUAL_LEAVE_DAY_COUNT_MODE]
        )

    def test_root_baza_haqqi_deyisdikde_hesablama_da_deyisir(self) -> None:
        """ "Görünür, dəyişdirilir, təsirsiz" qüsurunun qapısı."""
        employee = make_employee(hire_date=date(2020, 1, 1))
        harness = build()
        harness.limits.set(SystemLimitKey.ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS, "28.00")

        view = harness.use_case.my_balance(tenant_id=TENANT, employee=employee)

        # 28 baza + 1 staj (6 il ÷ 5 il).
        assert view.entitled_days == Decimal("29.00")

    def test_staj_qaydasinin_formasi_da_konfiqurasiya_edilir(self) -> None:
        """Dövrün uzunluğu, addımın böyüklüyü və tavan — üçü də ROOT-dadır."""
        policy = AnnualLeavePolicy.from_limits(
            {
                SystemLimitKey.ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS.value: "2",
                SystemLimitKey.ANNUAL_LEAVE_SENIORITY_BONUS_DAYS.value: "3.00",
                SystemLimitKey.ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS.value: "7.00",
            }
        )

        # 6 il ÷ 2 il = 3 addım × 3 gün = 9 → tavan 7.
        assert policy.seniority_bonus(hire_date=date(2020, 1, 1), as_of=date(2026, 6, 15)) == (
            Decimal("7.00")
        )

    def test_accrual_derecesi_acqi_deyerle_evez_edile_bilir(self) -> None:
        """`0` sentineli defoltdur, lakin Root açıq dərəcə yaza bilər."""
        derived = AnnualLeavePolicy.from_limits(
            {SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_PERIOD.value: "MONTHLY"}
        )
        explicit = AnnualLeavePolicy.from_limits(
            {
                SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_PERIOD.value: "MONTHLY",
                SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD.value: "3.00",
            }
        )

        derived_days = derived.entitlement_for_year(
            year=2026, hire_date=date(2020, 1, 1), as_of=date(2026, 12, 31)
        ).days
        explicit_days = explicit.entitlement_for_year(
            year=2026, hire_date=date(2020, 1, 1), as_of=date(2026, 12, 31)
        ).days

        assert derived_days == Decimal("22.00")
        assert explicit_days == Decimal("36.00")

    def test_yararsiz_root_deyeri_ekrani_cokdurmur(self) -> None:
        """Root panelinə "iyirmi bir" yazılsa da balans kartı açılmalıdır."""
        policy = AnnualLeavePolicy.from_limits(
            {
                SystemLimitKey.ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS.value: "iyirmi bir",
                SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_PERIOD.value: "HEFTELIK",
                SystemLimitKey.ANNUAL_LEAVE_DAY_COUNT_MODE.value: "NAMELUM",
            }
        )

        assert policy.base_entitlement_days == Decimal("21.00")
        assert policy.accrual_period is AccrualPeriod.ANNUAL
        assert policy.day_count_mode is LeaveDayCountMode.WORKING_DAYS

    def test_menfi_root_deyeri_sixilir_istisna_atilmir(self) -> None:
        policy = AnnualLeavePolicy.from_limits(
            {
                SystemLimitKey.ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS.value: "-5",
                SystemLimitKey.ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS.value: "0",
                SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH.value: "99",
            }
        )

        assert policy.base_entitlement_days == Decimal("0")
        assert policy.seniority_period_years == 1, "Sıfıra bölmə mümkün olmamalıdır"
        assert policy.carryover_deadline_month == 12

    def test_port_verilmediyinde_fallback_isleyir(self) -> None:
        """`limits=None` — davranış `DEFAULT_LIMITS` ilə eyni qalır."""
        use_case = AnnualLeaveUseCase(
            balances=FakeBalances(),  # type: ignore[arg-type]
            requests=FakeRequests(),  # type: ignore[arg-type]
            shifts=FakeShifts(),  # type: ignore[arg-type]
            audit=RecordingAudit(),  # type: ignore[arg-type]
            clock=FakeClock(),  # type: ignore[arg-type]
            notifier=RecordingNotifier(),  # type: ignore[arg-type]
        )

        assert use_case.policy(TENANT) == AnnualLeavePolicy.defaults()


# --------------------------------------------------------------------------- #
# L. SORĞU AXINI — SHIFT SWAP NAXIŞININ TƏKRARI
# --------------------------------------------------------------------------- #


class TestRequestFlow:
    def test_kecmis_tarixe_sorgu_gonderilmir(self) -> None:
        employee = make_employee()
        harness = build()

        with pytest.raises(AnnualLeaveError):
            harness.use_case.submit(
                tenant_id=TENANT,
                employee=employee,
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 5),
            )

    def test_bitme_tarixi_baslangicdan_evvel_ola_bilmez(self) -> None:
        employee = make_employee()
        harness = build()

        with pytest.raises(DomainRuleError):
            harness.use_case.submit(
                tenant_id=TENANT,
                employee=employee,
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 1),
            )

    def test_balans_catmayan_sorgu_hr_novbesine_dusmur(self) -> None:
        employee = make_employee()
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="2.00")

        with pytest.raises(AnnualLeaveError) as exc:
            harness.use_case.submit(
                tenant_id=TENANT,
                employee=employee,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
            )

        assert "2.00 gün qalıb" in exc.value.user_message
        assert harness.requests.rows == {}

    def test_sorgu_balansi_azaltmir_yalniz_tesdiq_azaldir(self) -> None:
        """Gözləyən sorğu heç nəyi bloklamamalıdır (`ShiftSwapRequest` naxışı)."""
        employee = make_employee()
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")

        harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )

        assert harness.balances.get(employee.id, year=2026).used_days == Decimal("0.00")

    def test_pending_inbox_flag_teleb_edir_ve_siralanir(self) -> None:
        first = make_employee()
        second = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(first.id, year=2026, entitled="21.00")
        harness.balances.seed(second.id, year=2026, entitled="21.00")
        harness.use_case.submit(
            tenant_id=TENANT,
            employee=first,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
        )
        harness.use_case.submit(
            tenant_id=TENANT,
            employee=second,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 3),
        )

        inbox = harness.use_case.pending_inbox(tenant_id=TENANT, actor=approver)

        assert [r.start_date for r in inbox] == [date(2026, 7, 1), date(2026, 9, 1)]
        with pytest.raises(AnnualLeavePermissionError):
            harness.use_case.pending_inbox(tenant_id=TENANT, actor=first)

    def test_my_requests_selahiyyet_teleb_etmir(self) -> None:
        employee = make_employee()
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 3),
        )

        assert len(harness.use_case.my_requests(employee)) == 1

    def test_butun_qerarlar_audit_izi_buraxir(self) -> None:
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        approved = approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 3),
        )
        rejected = harness.use_case.submit(
            tenant_id=TENANT,
            employee=employee,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
        )
        harness.use_case.reject(
            tenant_id=TENANT,
            approver=approver,
            request_id=rejected.id,
            reason="Həmin həftə inventar var, kadr çatışmır",
        )
        harness.use_case.cancel(
            tenant_id=TENANT,
            actor=employee,
            request_id=approved.id,
            reason="Səfər ləğv edildi, planlar dəyişdi",
        )

        assert harness.audit.actions() == [
            "ANNUAL_LEAVE_REQUESTED",
            "ANNUAL_LEAVE_APPROVED",
            "ANNUAL_LEAVE_REQUESTED",
            "ANNUAL_LEAVE_REJECTED",
            "ANNUAL_LEAVE_CANCELLED",
        ]

    def test_el_ile_duzelis_updated_by_yazir_ve_audit_qoyur(self) -> None:
        employee = make_employee()
        hr = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()

        view = harness.use_case.adjust_balance(
            tenant_id=TENANT,
            actor=hr,
            employee=employee,
            year=2026,
            entitled_days=Decimal("25.00"),
            carried_over_days=Decimal("2.00"),
            reason="Məhkəmə qərarı ilə əlavə gün",
        )

        assert view.entitled_days == Decimal("25.00")
        assert harness.balances.get(employee.id, year=2026).updated_by == hr.id
        assert "ANNUAL_LEAVE_BALANCE_ADJUSTED" in harness.audit.actions()

    def test_el_ile_duzelis_menfi_deyeri_qebul_etmir(self) -> None:
        employee = make_employee()
        hr = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()

        with pytest.raises(AnnualLeaveError):
            harness.use_case.adjust_balance(
                tenant_id=TENANT,
                actor=hr,
                employee=employee,
                year=2026,
                entitled_days=Decimal("-1.00"),
                carried_over_days=Decimal("0.00"),
                reason="Səhv düzəliş cəhdi",
            )

    def test_balans_karti_gui_ucun_hem_qaliq_hem_cemi_verir(self) -> None:
        """ "14/21 gün qalıb" kartı: mətn GUI-də qurulur, rəqəmlər burada."""
        employee = make_employee()
        approver = make_employee(flags=[MANAGE_FLAG], role=SystemRole.HR_ADMIN)
        harness = build()
        harness.balances.seed(employee.id, year=2026, entitled="21.00")
        approved_request(
            harness,
            employee=employee,
            approver=approver,
            start=date(2026, 7, 1),
            end=date(2026, 7, 7),
        )

        view = harness.use_case.my_balance(tenant_id=TENANT, employee=employee)

        assert view.available_days == Decimal("14.00")
        assert view.total_days == Decimal("21.00")
        assert view.carryover_deadline == date(2026, 3, 31)


# --------------------------------------------------------------------------- #
# M. BALANS ENTITY-Sİ — MƏNFİYƏ DÜŞMƏ QAPAĞI
# --------------------------------------------------------------------------- #


class TestBalanceEntity:
    def test_catmayan_balans_izahli_istisna_verir(self) -> None:
        balance = AnnualLeaveBalance(
            balance_id=AnnualLeaveBalanceId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            year=2026,
            entitled_days=Decimal("5.00"),
        )

        with pytest.raises(DomainRuleError) as exc:
            balance.consume(Decimal("6.00"))

        assert "5.00 gün var" in exc.value.user_message

    def test_release_used_days_i_menfiye_salmir(self) -> None:
        balance = AnnualLeaveBalance(
            balance_id=AnnualLeaveBalanceId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            year=2026,
            entitled_days=Decimal("5.00"),
            used_days=Decimal("2.00"),
        )

        balance.release(Decimal("5.00"))
        balance.release(Decimal("5.00"))

        assert balance.used_days == Decimal("0.00")

    def test_available_days_hec_vaxt_menfi_gorunmur(self) -> None:
        """Tarixi idxaldan gələn uyğunsuz sətir ekranda "-3 gün" göstərməməlidir."""
        balance = AnnualLeaveBalance(
            balance_id=AnnualLeaveBalanceId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            year=2026,
            entitled_days=Decimal("2.00"),
            used_days=Decimal("9.00"),
        )

        assert balance.available_days == Decimal("0")

    def test_serhedden_kenar_il_qebul_edilmir(self) -> None:
        """DB `CHECK (year BETWEEN 2000 AND 2100)` entity-də təkrarlanır."""
        with pytest.raises(DomainRuleError):
            AnnualLeaveBalance(
                balance_id=AnnualLeaveBalanceId(uuid.uuid4()),
                tenant_id=TENANT,
                employee_id=EmployeeId(uuid.uuid4()),
                year=1900,
            )

    def test_menfi_cixilan_gun_qebul_edilmir(self) -> None:
        """Mənfi `deducted_days` balansı ARTIRARDI ("məzuniyyət götürdüm, günüm çoxaldı")."""
        request = AnnualLeaveRequest(
            request_id=new_annual_leave_request_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
            created_at=NOW,
        )

        with pytest.raises(DomainRuleError):
            request.approve(
                approver_id=EmployeeId(uuid.uuid4()),
                decided_at=NOW,
                deducted_days=Decimal("-1.00"),
            )
