"""Portların test implementasiyaları (Faza 2.5+).

Mock kitabxanası ƏVƏZİNƏ əl ilə yazılmış sahtə (fake) obyektlər istifadə
olunur: onlar real davranışı saxlayır (yaddaşda saxlama, axtarış), ona görə
testlər "metod çağırıldımı" deyil, "NƏTİCƏ DÜZGÜNDÜRMÜ" yoxlayır.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from src.domain.entities.attendance_record import AttendanceRecord, CheckInStatus
from src.domain.entities.auth_session import AuthSession
from src.domain.entities.employee import Employee
from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.entities.leave_request import LeaveRequest, LeaveStatus
from src.domain.policies import DEFAULT_LIMITS, BreakKind, SystemLimitKey
from src.domain.value_objects.authorization import RolePriority
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    FineId,
    LeaveRequestId,
    LeaveTypeId,
    SessionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.machine_identity import MachineIdentityHash
from src.domain.value_objects.pin_throttle import TerminalPinThrottle


class FakeClock:
    """Sabitlənə bilən vaxt mənbəyi."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def advance(self, **kwargs: float) -> None:
        self._moment += timedelta(**kwargs)

    def set(self, moment: datetime) -> None:
        self._moment = moment


class FakeNtp:
    """NTP yoxlayıcısı — sürüşməni testdə idarə etmək üçün."""

    def __init__(
        self, clock: FakeClock, *, verified: bool = True, drift: float | None = 0.0
    ) -> None:
        self._clock = clock
        self.verified = verified
        self.drift = drift

    def verified_now(self) -> tuple[datetime, bool]:
        return self._clock.now(), self.verified

    def drift_seconds(self) -> float | None:
        return self.drift


class FakeSystemLimits:
    """`system_limits` — defoltlar + testdə override."""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self._values: dict[str, str] = {key.value: value for key, value in DEFAULT_LIMITS.items()}
        self._values.update(overrides or {})

    def set(self, key: SystemLimitKey | str, value: str) -> None:
        self._values[key.value if isinstance(key, SystemLimitKey) else key] = value

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        try:
            return int(self._values.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class FakeFeatureToggles:
    """Feature Toggle-lar — defolt hamısı aktiv."""

    def __init__(self, disabled: set[str] | None = None) -> None:
        self.disabled = disabled or set()

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        return module_key not in self.disabled

    def disable(self, module_key: str) -> None:
        self.disabled.add(module_key)


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def notify(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    def categories(self) -> list[str]:
        return [str(m["category"]) for m in self.messages]


class RecordingEventBus:
    """`EventBus`-un sınaq əvəzedicisi — D2 reqressiyası üçün.

    Real `EventBus` (`shared/event_bus.py`) abunəçi qeydiyyatı, prioritet
    sırası və MRO üzrə dispatch daşıyır — bunların heç biri `leave_verification.
    py::_publish_events`-in ÖZ məntiqinə aid deyil (o, sadəcə `publish()`-i
    çağırır və istisnanı udur). Ona görə tam `EventBus` qurmaq testi predmetdən
    uzaqlaşdırardı; bu sahtə yalnız "NƏ yayıldı" və "yayım neçə dəfə çağırıldı"
    sualına cavab verir.
    """

    def __init__(self) -> None:
        self.published: list[Any] = []
        #: `publish()`-in UĞURSUZLUĞUNU simulyasiya edir (defolt: uğurlu).
        #: `leave_verification._publish_events` bunu udmalıdır — Saga artıq
        #: `COMPLETED`-dir, yayım nasazlığı əməliyyatı geri qaytarmamalıdır.
        self.failure: Exception | None = None

    async def publish(self, event: Any) -> None:
        if self.failure is not None:
            raise self.failure
        self.published.append(event)

    def names(self) -> list[str]:
        return [str(getattr(e, "event_name", type(e).__name__)) for e in self.published]


class RecordingFineReviewBatches:
    """`FineReviewBatchRepository`-in sınaq əvəzedicisi — SEC-8 reqressiyası.

    `MonthlyFineReviewUseCase.__init__`-də `review_batches` MƏCBURİDİR
    (`fine_review.py`-dəki başlığa bax: opsional `None` "partiya sətri
    yazılmadan nəşr" halını sükutla yaradardı). Bu sahtə `RecordingEventBus`
    ilə EYNİ naxışdır: yalnız NƏ saxlanıldığını yazır və `save()`-in
    UĞURSUZLUĞUNU simulyasiya edə bilir (`_record()`-un audit sətrindən
    ƏVVƏL yazdığı üçün — istisna `publish_batch()`-i bütövlükdə kəsməlidir).
    """

    def __init__(self) -> None:
        self.saved: list[Any] = []
        self.failure: Exception | None = None

    def save(self, batch: Any) -> None:
        if self.failure is not None:
            raise self.failure
        self.saved.append(batch)


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        #: Audit yazısının UĞURSUZLUĞUNU simulyasiya edir (defolt: uğurlu).
        #:
        #: NİYƏ LAZIMDIR — Saga zəncirinin SONUNCU addımı `write_audit`-dır.
        #: Yalnız daha erkən addımın çökməsi test edilsəydi, kompensasiya
        #: "cərimə artıq YARADILDIQDAN SONRA" heç vaxt işə düşməzdi və məhz
        #: həmin yolda gizlənən qüsur (kompensasiyanın `reverse()` çağırıb
        #: `DomainRuleError` alması) testlərdən yaşıl keçərdi.
        #:
        #: `AuditTrail.record()`-un istisna udmaması layihə qaydasıdır
        #: (CLAUDE.md §5) — yəni bu, süni deyil, real ssenaridir.
        self.failure: Exception | None = None

    def record(self, **kwargs: Any) -> None:
        if self.failure is not None:
            raise self.failure
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(e["action"]) for e in self.entries]


class RecordingSecurityEvents:
    """`SecurityEventRepository`-in sınaq əvəzedicisi (SEC-7).

    Real port FAIL-SOFT-dur (`ports.py::SecurityEventRepository` başlığı) —
    yəni istehsalatda bu yazı çökəndə əməliyyat GERİ QAYTARILMIR. Sahtə
    ONA GÖRƏ `RecordingAudit`-dən FƏRQLİ olaraq `failure` sahəsi DAŞIMIR:
    fail-soft davranışı ölçmək lazım olsa, `ports.py`-nin öz şərhindəki
    `FailSoftSecurityEventRecorder`-in ÖZÜ test olunmalıdır, bu xam sahtə
    yox (istehsalatda da xam implementasiya BİRBAŞA use case-ə verilmir).
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)

    def event_types(self) -> list[str]:
        return [str(e["event_type"]) for e in self.entries]


class InMemoryPinThrottle:
    """`PinThrottleRepository`-nin sınaq əvəzedicisi (SEC-01/SEC-05, dövrə 3-4).

    `InMemoryLeaveRequests.get_for_update`-lə EYNİ fəlsəfə (yaddaşda həqiqi
    kilid MƏNASIZDIR, YALNIZ çağırış qeydi) — `PinThrottleRepository` isə
    `RowLockingLeaveRequests`-dən FƏRQLİ olaraq `@runtime_checkable` DEYİL
    (sadə Protocol, opsional qabiliyyət yoxdur), ona görə burada `isinstance`
    tələsi YARANMIR — sahtə YALNIZ strukturca uyğun olmalıdır.

    PƏNCƏRƏ/KİLİD ARİFMETİKASI BURADA YAZILMIR — `TerminalPinThrottle.
    advance_after_failure()` ÇAĞIRILIR
    ──────────────────────────────────────────────────────────────────────
    Real yol DB trigger-idir (TIME-1: server-vaxtına bağlı hesablama
    client-dən asılı ola bilməz) — AMMA `advance_after_failure()` (dövrə 4)
    həmin triggerin İCRA OLUNAN SPESİFİKASİYASIDIR, yan-təsirsiz domen
    metodudur (`pin_throttle.py`-nin öz başlığı). Sahtə TƏK yerdən oxuyur:
    riyaziyyatı TƏKRAR YAZMIR, `TerminalPinThrottle`-un özünə həvalə edir —
    pəncərə-bitmə sərhədi (mənim ARCHITECT-ə göndərdiyim siyahının 1-2-ci
    bəndi) buna görə İNDİ BURADA da (Python səviyyəsində) düzgün modellənir;
    SQL trigger-in ÖZÜNÜN eyni nəticəni verdiyi isə `database/tests/`-in
    ayrıca işidir (`infra`).
    """

    def __init__(self, *, clock: FakeClock, limits: FakeSystemLimits | None = None) -> None:
        self.rows: dict[tuple[TenantId, str], TerminalPinThrottle] = {}
        self.locked_reads: list[tuple[TenantId, str]] = []
        self._clock = clock
        self._limits = limits or FakeSystemLimits()

    def get_for_update(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash
    ) -> TerminalPinThrottle | None:
        self.locked_reads.append((tenant_id, machine_key.digest))
        return self.rows.get((tenant_id, machine_key.digest))

    def record_failure(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash, *, store_id: StoreId
    ) -> TerminalPinThrottle:
        key = (tenant_id, machine_key.digest)
        existing = self.rows.get(key)
        now = self._clock.now()
        max_attempts = self._limits.get_int(tenant_id, "KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS", 20)
        lockout_minutes = self._limits.get_int(tenant_id, "KIOSK_STORE_PIN_LOCKOUT_MINUTES", 15)
        base = existing or TerminalPinThrottle(
            tenant_id=tenant_id,
            machine_key=machine_key,
            store_id=store_id,
            failed_count=0,
            window_started_at=None,
            locked_until=None,
            updated_at=now,
        )
        row = base.advance_after_failure(
            now=now, max_attempts=max_attempts, lockout_minutes=lockout_minutes
        )
        if row.store_id != store_id:  # `advance_after_failure` `store_id`-ə TOXUNMUR
            row = replace(row, store_id=store_id)
        self.rows[key] = row
        return row

    def update_last_seen_store(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash, *, store_id: StoreId
    ) -> None:
        key = (tenant_id, machine_key.digest)
        existing = self.rows[key]
        self.rows[key] = replace(existing, store_id=store_id)


class InMemoryLeaveRequests:
    def __init__(self) -> None:
        self.items: dict[LeaveRequestId, LeaveRequest] = {}
        self.save_failure: Exception | None = None
        #: `get_for_update()` neçə dəfə çağırılıb — yazma axınının kilidli
        #: oxudan keçdiyini test AÇIQ şəkildə yoxlaya bilsin deyə.
        self.locked_reads: list[LeaveRequestId] = []

    def get(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        return self.items.get(request_id)

    def get_for_update(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        """`RowLockingLeaveRequests` qabiliyyəti — yaddaşda kilid MƏNASIZDIR.

        Sahtə repo tək saplı testdə işləyir, ona görə burada həqiqi kilid yox,
        yalnız ÇAĞIRIŞ QEYDİ var: test "yazma axını kilidli oxu istədimi"
        sualına cavab ala bilir. Həqiqi `FOR UPDATE` davranışı
        `database/tests/test_guards.sql` və inteqrasiya testlərinin işidir.
        """
        self.locked_reads.append(request_id)
        return self.items.get(request_id)

    def find_open_for_employee(self, employee_id: EmployeeId) -> LeaveRequest | None:
        for request in self.items.values():
            if request.employee_id == employee_id and request.status.is_open:
                return request
        return None

    def find_open_for_employee_locked(self, employee_id: EmployeeId) -> LeaveRequest | None:
        """`RowLockingLeaveRequests` — STEP 2 (`claim_return`) üçün kilidli-oxu qabiliyyəti.

        `get_for_update`-lə EYNİ fəlsəfə (yaddaşda həqiqi kilid yoxdur, YALNIZ
        çağırış qeydi) — sadəcə axtarış açarı `request_id` deyil, `employee_id`.
        """
        for request in self.items.values():
            if request.employee_id == employee_id and request.status.is_open:
                self.locked_reads.append(request.id)
                return request
        return None

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[LeaveRequest]:
        return [
            r
            for r in self.items.values()
            if r.store_id in store_ids and r.status.value == "PENDING_RETURN_VERIFICATION"
        ]

    def list_due_for_timeout(
        self, tenant_id: TenantId, *, now: datetime, timeout_minutes: int
    ) -> list[LeaveRequest]:
        return [
            r
            for r in self.items.values()
            if r.tenant_id == tenant_id and r.status.value == "PENDING_RETURN_VERIFICATION"
        ]

    def list_pending_dual_control(self, tenant_id: TenantId) -> list[LeaveRequest]:
        """İkinci təsdiq gözləyən vaxt düzəlişləri (M-5).

        Real repo "SON override sətri `PENDING_DUAL_CONTROL`-dur" şərtini
        SQL-də qurur; yaddaşda isə entity-nin özündə bir override obyekti var,
        ona görə eyni sual birbaşa `is_pending_approval`-dan oxunur.
        """
        return [
            request
            for request in self.items.values()
            if request.tenant_id == tenant_id
            and request.override is not None
            and request.override.is_pending_approval
        ]

    def monthly_used_minutes(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        """Aylıq icazə cəmi — YALNIZ təsdiqlənmiş sorğular (bölmə 3 limiti).

        Dəyər `penalty.total_minutes`-dən oxunur: `leave_requests.total_minutes`
        SÜTUNU məhz təsdiq anında bu hesablamadan yazılır (bax `verify()`).
        Təsdiqlənib, lakin penalty-si olmayan sətir mümkün deyil, yenə də
        `or 0` qoyulub ki, fake real repo-dan DAHA SƏRT olmasın.
        """
        return sum(
            (request.penalty.total_minutes if request.penalty is not None else 0)
            for request in self.items.values()
            if request.employee_id == employee_id
            and request.status is LeaveStatus.VERIFIED
            and request.requested_time.year == year
            and request.requested_time.month == month
        )

    def save(self, request: LeaveRequest) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.items[request.id] = request


#: `uq_fines_one_live_auto_delay_per_leave` (miqrasiya 015) indeksinin əhatə
#: etdiyi DİRİ statuslar. `REVERSED` QƏSDƏN yoxdur — ölü sətir indeks yerini
#: tutsaydı, kompensasiyadan sonra təkrar təsdiq əbədi bloklanardı.
LIVE_AUTO_DELAY_STATUSES = frozenset(
    {FineStatus.PENDING_REVIEW, FineStatus.PUBLISHED, FineStatus.REDUCED}
)


class DuplicateLiveFineError(Exception):
    """Sahtə repo-da DB unikal indeksinin qarşılığı.

    Real `PostgresFineRepository` bu halda `psycopg.errors.UniqueViolation`
    alır. Sahtə repo həmin qaydanı təkrarlayır ki, "ikinci cərimə yaranmır"
    iddiası DB olmadan da yoxlana bilsin — əks halda unit dəsti indeksin
    olmadığı bir dünyada yaşayardı və qüsuru görməzdi.
    """


class InMemoryFines:
    def __init__(self) -> None:
        self.items: dict[FineId, Fine] = {}
        self.save_failure: Exception | None = None

    def get(self, fine_id: FineId) -> Fine | None:
        return self.items.get(fine_id)

    def list_for_employee_month(
        self, employee_id: EmployeeId, *, year: int, month: int
    ) -> list[Fine]:
        return [
            f
            for f in self.items.values()
            if f.employee_id == employee_id
            and f.issued_at.year == year
            and f.issued_at.month == month
        ]

    def list_exportable(self, tenant_id: TenantId, *, now: datetime) -> list[Fine]:
        return [f for f in self.items.values() if f.is_exportable(now=now)]

    def save(self, fine: Fine) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self._require_single_live_auto_delay(fine)
        self.items[fine.id] = fine

    def _require_single_live_auto_delay(self, fine: Fine) -> None:
        """Bir icazə sorğusuna yalnız BİR diri `AUTO_DELAY` cəriməsi."""
        if fine.source is not FineSource.AUTO_DELAY or fine.leave_request_id is None:
            return
        if fine.status not in LIVE_AUTO_DELAY_STATUSES:
            return
        for existing in self.items.values():
            if (
                existing.id != fine.id
                and existing.source is FineSource.AUTO_DELAY
                and existing.leave_request_id == fine.leave_request_id
                and existing.status in LIVE_AUTO_DELAY_STATUSES
            ):
                raise DuplicateLiveFineError(
                    f"İcazə sorğusuna ({fine.leave_request_id}) artıq diri "
                    f"AUTO_DELAY cəriməsi bağlıdır"
                )


class InMemoryAuthSessions:
    """`AuthSessionRepository`-in sınaq əvəzedicisi (SEC-011 / SEC-5).

    `get_by_token_hash` AÇIQ tokenlə DEYİL, onun heşi ilə axtarır — port
    sərhədi elə buna görə qurulub (bax `ports.py::AuthSessionRepository`);
    sahtə heç vaxt açıq tokeni SAXLAMIR, çünki ona referans belə almır.
    """

    def __init__(self) -> None:
        self.items: dict[SessionId, AuthSession] = {}
        #: HƏR `save()` çağırışını sayır — `items`-in UZUNLUĞUNDAN fərqli
        #: olaraq eyni sessiyanın TƏKRAR yazılıb-yazılmadığını (məs.
        #: `touch()`-un CAMERA_DASHBOARD-da YAZI GÖNDƏRMƏMƏSİ, PERF-1/2/3)
        #: göstərir — upsert eyni `id`-yə düşdüyü üçün `len(items)` bunu
        #: gizlədərdi.
        self.saves: list[SessionId] = []

    def save(self, session: AuthSession) -> None:
        self.items[session.id] = session
        self.saves.append(session.id)

    def get(self, session_id: SessionId) -> AuthSession | None:
        return self.items.get(session_id)

    def get_by_token_hash(self, tenant_id: TenantId, token_hash: str) -> AuthSession | None:
        for session in self.items.values():
            if session.tenant_id == tenant_id and session.token_hash == token_hash:
                return session
        return None

    def list_recent_for_user(
        self, tenant_id: TenantId, user_id: EmployeeId, *, limit: int = 10
    ) -> list[AuthSession]:
        matches = [
            s for s in self.items.values() if s.tenant_id == tenant_id and s.user_id == user_id
        ]
        matches.sort(key=lambda s: s.issued_at, reverse=True)
        return matches[:limit]


class InMemoryAttendance:
    def __init__(self) -> None:
        self.items: dict[AttendanceRecordId, AttendanceRecord] = {}
        #: `get_for_day_for_update()` çağırışlarının izi (bax
        #: `InMemoryLeaveRequests.get_for_update` izahı).
        self.locked_reads: list[tuple[EmployeeId, date]] = []

    def get(self, record_id: AttendanceRecordId) -> AttendanceRecord | None:
        return self.items.get(record_id)

    def get_for_day(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord | None:
        for record in self.items.values():
            if record.employee_id == employee_id and record.work_date == work_date:
                return record
        return None

    def get_for_day_for_update(
        self, employee_id: EmployeeId, work_date: date
    ) -> AttendanceRecord | None:
        """`RowLockingAttendance` qabiliyyəti — yalnız çağırış qeydi."""
        self.locked_reads.append((employee_id, work_date))
        return self.get_for_day(employee_id, work_date)

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[AttendanceRecord]:
        return [
            r
            for r in self.items.values()
            if r.store_id in store_ids and r.status is CheckInStatus.PENDING_VERIFICATION
        ]

    def list_expected_on(self, tenant_id: TenantId, work_date: date) -> list[AttendanceRecord]:
        return [
            r for r in self.items.values() if r.tenant_id == tenant_id and r.work_date == work_date
        ]

    def save(self, record: AttendanceRecord) -> None:
        self.items[record.id] = record


class InMemoryEmployees:
    def __init__(self, employees: list[Employee] | None = None) -> None:
        self.items: dict[EmployeeId, Employee] = {e.id: e for e in employees or []}
        #: `{employee_id: {"password_hash"/"pin_hash"/"pepper_version": ...}}`
        #: — heşlər entity-də DEYİL, ayrı saxlanılır (istehsalat modeli ilə eyni).
        self.credentials: dict[EmployeeId, dict[str, Any]] = {}
        #: `create()`-ə ötürülən XAM sirrlər — `{id: (şifrə, PIN)}`.
        self.created_secrets: dict[EmployeeId, tuple[str | None, str | None]] = {}

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.items.get(employee_id)

    def get_by_username(self, tenant_id: TenantId, username: Any) -> Employee | None:
        for employee in self.items.values():
            if employee.username == username and employee.tenant_id == tenant_id:
                return employee
        return None

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Employee]:
        return [
            e
            for e in self.items.values()
            if e.tenant_id == tenant_id and e.store_id == store_id and e.has_pin
        ]

    def save(self, employee: Employee) -> None:
        self.items[employee.id] = employee

    def create(
        self,
        employee: Employee,
        *,
        raw_password: str | None = None,
        raw_pin: str | None = None,
    ) -> None:
        """YENİ sətir — sirri ilə birlikdə (`EmployeeWriter`).

        `save()`-dən AYRIDIR, çünki istehsalatda da ayrıdır: `save()` `UPDATE`
        edir və olmayan sətri YARATMIR. Sahtənin hər ikisini eyni cür
        işləməsi məhz həmin fərqi gizlədirdi — «Yeni İşçi» axını testdə
        keçir, canlı bazada isə heç nə yazmırdı.
        """
        self.items[employee.id] = employee
        self.created_secrets[employee.id] = (raw_password, raw_pin)

    def update_credentials(
        self,
        employee_id: EmployeeId,
        *,
        pin_hash: str | None = None,
        password_hash: str | None = None,
        pepper_version: int | None = None,
    ) -> None:
        """Sirr heşlərini AYRICA saxlayır — `PostgresEmployeeRepository` kimi.

        `None` verilən sahə TOXUNULMUR (`COALESCE` davranışının sahtəsi): əks
        halda "PIN yazdım, şifrəni sıfırladım" səhvi testdə görünməz qalardı.
        Saxlanan heş testlərdə FAKTİKİ olaraq `HashingService.verify_*` ilə
        yoxlanılır — "çağırıldımı" deyil, "uyğun gəlirmi" sualı vacibdir.
        """
        current = self.credentials.get(employee_id, {})
        if pin_hash is not None:
            current["pin_hash"] = pin_hash
        if password_hash is not None:
            current["password_hash"] = password_hash
        if pepper_version is not None:
            current["pepper_version"] = pepper_version
        self.credentials[employee_id] = current

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        from datetime import UTC

        now = datetime.now(tz=UTC)
        return sum(
            1
            for e in self.items.values()
            if e.tenant_id == tenant_id and e.is_active and e.has_permission(flag_code, now=now)
        )

    def count_active_ranked_at_or_above(self, tenant_id: TenantId, priority: RolePriority) -> int:
        """SETUP-3 sayğacı — `<=`, çünki KİÇİK rəqəm daha YÜKSƏK pillədir."""
        return sum(
            1
            for e in self.items.values()
            if e.tenant_id == tenant_id
            and e.is_active
            and e.position.is_active
            and e.position.priority <= priority
        )


class FakeLeaveTypes:
    def __init__(
        self,
        durations: dict[LeaveTypeId, int] | None = None,
        break_kinds: dict[LeaveTypeId, BreakKind] | None = None,
    ) -> None:
        self.durations = durations or {}
        #: Nahar/Çay nişanı (nahar.md). DEFOLT BOŞDUR — nişansız növ sayğaca
        #: düşmür, yəni mövcud testlərin davranışı DƏYİŞMİR.
        self.break_kinds = break_kinds or {}

    def get_default_duration(self, leave_type_id: LeaveTypeId) -> int | None:
        return self.durations.get(leave_type_id)

    def break_kind_of(self, leave_type_id: LeaveTypeId) -> BreakKind | None:
        return self.break_kinds.get(leave_type_id)


class InMemoryBreakUsage:
    """`daily_break_usage` sahtəsi — atomikliyi Python lüğəti təmin edir.

    Real repo UPSERT ilə işləyir (bax `break_usage_repository.py` başlığı);
    burada eyni MÜQAVİLƏ saxlanılır: `record_use` YENİ dəyəri qaytarır və
    sətir yoxdursa 1-dən başlayır.
    """

    def __init__(self) -> None:
        self.counts: dict[tuple[EmployeeId, date, BreakKind], int] = {}
        self.last_used: dict[tuple[EmployeeId, date, BreakKind], datetime] = {}

    def record_use(
        self,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        *,
        kind: BreakKind,
        on_date: date,
        at: datetime,
    ) -> int:
        del tenant_id  # RLS sahtədə yoxdur; imza real portla eyni qalır
        key = (employee_id, on_date, kind)
        self.counts[key] = self.counts.get(key, 0) + 1
        self.last_used[key] = at
        return self.counts[key]

    def count_for_day(self, employee_id: EmployeeId, *, kind: BreakKind, on_date: date) -> int:
        return self.counts.get((employee_id, on_date, kind), 0)

    def usage_for_day(self, employee_id: EmployeeId, *, on_date: date) -> dict[BreakKind, int]:
        return {kind: self.counts.get((employee_id, on_date, kind), 0) for kind in BreakKind}

    def usage_rows_for_day(
        self, tenant_id: TenantId, *, on_date: date
    ) -> list[tuple[EmployeeId, BreakKind, int]]:
        del tenant_id
        return [
            (employee_id, kind, count)
            for (employee_id, day, kind), count in self.counts.items()
            if day == on_date and count > 0
        ]


class FakeShifts:
    def __init__(
        self,
        *,
        off_days: set[tuple[EmployeeId, date]] | None = None,
        starts: dict[tuple[EmployeeId, date], datetime] | None = None,
    ) -> None:
        self.off_days = off_days or set()
        self.starts = starts or {}

    def is_off_day(self, employee_id: EmployeeId, work_date: date) -> bool:
        return (employee_id, work_date) in self.off_days

    def scheduled_start(self, employee_id: EmployeeId, work_date: date) -> datetime | None:
        return self.starts.get((employee_id, work_date))


class FakeCameraAssignments:
    """FAIL-SAFE: defolt BOŞ — operator heç nə görmür."""

    def __init__(self, mapping: dict[EmployeeId, list[StoreId]] | None = None) -> None:
        self.mapping = mapping or {}

    def stores_for_operator(self, operator_id: EmployeeId) -> list[StoreId]:
        return self.mapping.get(operator_id, [])

    def assign(self, operator_id: EmployeeId, store_id: StoreId) -> None:
        self.mapping.setdefault(operator_id, []).append(store_id)


__all__ = [
    "LIVE_AUTO_DELAY_STATUSES",
    "DuplicateDedupeKeyError",
    "DuplicateLiveFineError",
    "FaceArchiveConstraintError",
    "FakeCamera",
    "FakeCameraAssignments",
    "FakeClock",
    "FakeExceptionSources",
    "FakeFaceMatcher",
    "FakeFaceStoreScope",
    "FakeFeatureToggles",
    "FakeLeaveTypes",
    "FakeNtp",
    "FakeShifts",
    "FakeSystemLimits",
    "InMemoryAttendance",
    "InMemoryAuthSessions",
    "InMemoryBreakUsage",
    "InMemoryEmployees",
    "InMemoryExceptions",
    "InMemoryFaceExemptions",
    "InMemoryFaceProfiles",
    "InMemoryFaceVerificationLog",
    "InMemoryFines",
    "InMemoryLeaveRequests",
    "RecordingAudit",
    "RecordingEventBus",
    "RecordingFineReviewBatches",
    "RecordingNotifier",
    "RecordingSecurityEvents",
]


# --------------------------------------------------------------------------- #
# Faza 5/6 qatları — növbə, tabel, etiraz, dəstək
# --------------------------------------------------------------------------- #


class InMemoryShiftMatrix(FakeShifts):
    """`ShiftRepository`-nin YAZMA tərəfi də daxil olmaqla tam sahtəsi.

    `FakeShifts`-dən miras alır ki, mövcud testlər (`is_off_day`,
    `scheduled_start`) toxunulmaz qalsın — yeni metodlar yalnız əlavədir.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.assignments: dict[tuple[EmployeeId, date], Any] = {}

    def get_assignment(self, employee_id: EmployeeId, work_date: date) -> Any:
        return self.assignments.get((employee_id, work_date))

    def list_range(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
        employee_ids: list[EmployeeId] | None = None,
    ) -> list[Any]:
        rows = [
            item
            for (employee_id, day), item in self.assignments.items()
            if start <= day <= end and (employee_ids is None or employee_id in employee_ids)
        ]
        return sorted(rows, key=lambda item: item.shift_date)

    def save_assignment(self, assignment: Any) -> None:
        self.assignments[(assignment.employee_id, assignment.shift_date)] = assignment
        # `is_off_day()` mövcud testlərlə eyni mənbədən oxunmalıdır.
        key = (assignment.employee_id, assignment.shift_date)
        if assignment.is_off_day:
            self.off_days.add(key)
        else:
            self.off_days.discard(key)

    def clear_assignment(self, employee_id: EmployeeId, work_date: date) -> None:
        self.assignments.pop((employee_id, work_date), None)
        self.off_days.discard((employee_id, work_date))


class InMemorySwaps:
    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}

    def get(self, request_id: Any) -> Any:
        return self.items.get(request_id)

    def list_pending(self, tenant_id: TenantId, *, store_id: StoreId | None = None) -> list[Any]:
        return [item for item in self.items.values() if item.status.value == "PENDING_APPROVAL"]

    def list_for_employee(self, employee_id: EmployeeId, *, limit: int = 50) -> list[Any]:
        return [item for item in self.items.values() if item.employee_id == employee_id][:limit]

    def find_open_for_date(self, employee_id: EmployeeId, target_date: date) -> Any:
        for item in self.items.values():
            if (
                item.employee_id == employee_id
                and item.target_date == target_date
                and item.status.value == "PENDING_APPROVAL"
            ):
                return item
        return None

    def save(self, request: Any) -> None:
        self.items[request.id] = request


class InMemorySheets:
    def __init__(self) -> None:
        self.items: dict[tuple[StoreId, date], Any] = {}

    def get_for_day(self, store_id: StoreId, sheet_date: date) -> Any:
        return self.items.get((store_id, sheet_date))

    def list_unconfirmed(self, tenant_id: TenantId, *, up_to: date) -> list[Any]:
        return [
            sheet
            for (_, day), sheet in self.items.items()
            if day <= up_to and not sheet.is_confirmed
        ]

    def save(self, sheet: Any) -> None:
        self.items[(sheet.store_id, sheet.sheet_date)] = sheet


class FakeAttendanceFacts:
    def __init__(self, facts: list[Any] | None = None) -> None:
        self.facts = facts or []

    def facts_for(self, store_id: StoreId, work_date: date) -> list[Any]:
        return list(self.facts)


class InMemoryAppeals:
    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}

    def get(self, appeal_id: Any) -> Any:
        return self.items.get(appeal_id)

    def get_for_fine(self, fine_id: Any) -> Any:
        return next((item for item in self.items.values() if item.fine_id == fine_id), None)

    def list_pending(self, tenant_id: TenantId) -> list[Any]:
        return [item for item in self.items.values() if item.status.value == "PENDING"]

    def list_undecided(self, tenant_id: TenantId) -> list[Any]:
        """`PENDING` + `EXPIRED` (M-6) — real repo ilə eyni süzgəc.

        Şərt `is_decided` üzərindən yazılıb, status siyahısı üzərindən YOX:
        enum-a yeni "qərarsız" vəziyyət əlavə olunsa, sahtə repo real repo-dan
        sükutla fərqlənməsin.
        """
        return [item for item in self.items.values() if not item.status.is_decided]

    def list_for_employee(self, employee_id: EmployeeId, *, limit: int = 50) -> list[Any]:
        return [item for item in self.items.values() if item.employee_id == employee_id][:limit]

    def save(self, appeal: Any) -> None:
        self.items[appeal.id] = appeal


class DuplicateDedupeKeyError(Exception):
    """Sahtə repo-da `uq_exceptions_dedupe` indeksinin qarşılığı.

    Real `PostgresExceptionRepository` bu halda `UniqueViolation` alır. Sahtə
    repo qaydanı təkrarlayır ki, "təkrar tapıntı ikinci sətir yaratmır"
    iddiası DB olmadan da yoxlana bilsin — əks halda unit dəsti indeksin
    olmadığı bir dünyada yaşayardı (`DuplicateLiveFineError` ilə eyni qərar).
    """


class InMemoryExceptions:
    """`ExceptionRepository` sahtəsi — Vahid İstisna Jurnalı (#9).

    `delete()` QƏSDƏN YOXDUR: DB-də `REVOKE DELETE` var və sahtə repo real
    məhdudiyyətdən daha sərbəst olmamalıdır.
    """

    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}
        self.save_failure: Exception | None = None

    def get(self, exception_id: Any) -> Any:
        return self.items.get(exception_id)

    def find_by_dedupe(self, tenant_id: TenantId, *, source: str, dedupe_key: str) -> Any:
        for record in self.items.values():
            if (
                record.tenant_id == tenant_id
                and record.source == source
                and record.dedupe_key == dedupe_key
            ):
                return record
        return None

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_ids: list[StoreId] | None = None,
        limit: int = 200,
    ) -> list[Any]:
        rows = [
            record
            for record in self.items.values()
            if record.tenant_id == tenant_id
            and record.status.value == "OPEN"
            and (store_ids is None or record.store_id in store_ids)
        ]
        rows.sort(key=lambda record: record.created_at, reverse=True)
        return rows[:limit]

    def save(self, record: Any) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self._require_unique_dedupe(record)
        self.items[record.id] = record

    def _require_unique_dedupe(self, record: Any) -> None:
        if record.dedupe_key is None:
            return
        existing = self.find_by_dedupe(
            record.tenant_id, source=record.source, dedupe_key=record.dedupe_key
        )
        if existing is not None and existing.id != record.id:
            raise DuplicateDedupeKeyError(
                f"'{record.source}' mənbəyində '{record.dedupe_key}' açarı artıq var"
            )


class FakeExceptionSources:
    """`ExceptionSourceCatalog` sahtəsi — `exception_sources` kataloqu."""

    def __init__(self, sources: list[Any] | None = None) -> None:
        self.sources: dict[str, Any] = {source.code: source for source in sources or []}

    def get(self, tenant_id: TenantId, code: str) -> Any:
        return self.sources.get(code.strip().upper())

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        return [source for source in self.sources.values() if include_inactive or source.is_active]


class InMemoryPOSThresholds:
    """`POSThresholdRepository` sahtəsi (#7 — sənədləşdirmə/siyasət qeydi).

    Açar `employee_id`-dir: `pos_permission_thresholds`-da işçi başına BİR
    diri sətir var (`UNIQUE (tenant_id, employee_id)`, migrations/018).
    `delete()` QƏSDƏN YOXDUR — real repo-da `REVOKE DELETE` var
    (bax `InMemoryExceptions` ilə eyni qərar).
    """

    def __init__(self) -> None:
        self.items: dict[Any, Any] = {}
        self.save_failure: Exception | None = None

    def get_for_employee(self, tenant_id: TenantId, employee_id: EmployeeId) -> Any:
        record = self.items.get(employee_id)
        if record is None or record.tenant_id != tenant_id:
            return None
        return record

    def save(self, record: Any) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.items[record.employee_id] = record


# --------------------------------------------------------------------------- #
# Face Control — üz təsdiqi (facecontrol.md Faza 2)
#
# ÜÇ QAYDA BU SAHTƏLƏRDƏ DƏ SAXLANILIR (əks halda vahid testlər sxem
# məhdudiyyətlərinin OLMADIĞI bir dünyada yaşayardı — `DuplicateLiveFineError`
# ilə eyni qərar):
#   1. `PURGED` arxiv sətri vektor SAXLAYA BİLMƏZ (`chk_face_history_purge`);
#   2. üz sayğacı PIN sayğacına TOXUNMUR (ayrı sahələr, ayrı metodlar);
#   3. cross-check YALNIZ eyni mağazanın qeydiyyatlı işçilərini görür.
# --------------------------------------------------------------------------- #


class FaceArchiveConstraintError(Exception):
    """Sahtə repo-da `chk_face_history_purge` məhdudiyyətinin qarşılığı.

    Real bazada "silindi" deyib vektoru saxlamaq MÜMKÜN DEYİL. Sahtə repo
    həmin qaydanı təkrarlayır ki, bənd 8-in silmə iddiası DB olmadan da
    yoxlana bilsin.
    """


class FakeFaceMatcher:
    """`FaceMatcher` sahtəsi — HƏQİQİ Evklid məsafəsi ilə.

    MƏSAFƏ UYDURULMUR, HESABLANIR (`math.dist`): testlər vektorları
    `(0.0,)`/`(0.55,)` kimi bir ölçülü seçir və məsafə birbaşa oxunur —
    yəni "0.55 aşağı-etibar zolağındadır" iddiası sahtənin qaytardığı
    ədədə deyil, `FaceToleranceBand`-ın FAKTİKİ hesablamasına baxır.

    `samples` sırayla qaytarılır; siyahı bitəndə SONUNCU təkrarlanır — belə
    halda "birinci kadr keçmədi, ikinci keçdi" ssenarisi qurmaq mümkündür.
    """

    def __init__(
        self,
        samples: list[Any] | None = None,
        *,
        clock: FakeClock | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.samples = samples or []
        self._index = 0
        #: Doğrulamanın "uzun sürməsini" simulyasiya edir (bənd 18 həddi).
        #: Vaxt `Clock` portundan oxunduğu üçün sahtə saatı irəli sürmək
        #: real ölçmə gözləməkdən həm sürətli, həm determinstikdir.
        self._clock = clock
        self._delay_seconds = delay_seconds
        self.extract_calls: list[Any] = []
        self.distance_calls: list[tuple[Any, Any]] = []

    def extract(self, frame: Any, *, gesture: Any = None) -> Any:
        self.extract_calls.append(gesture)
        if self._clock is not None and self._delay_seconds:
            self._clock.advance(seconds=self._delay_seconds)
        if not self.samples:
            raise AssertionError("FakeFaceMatcher üçün nümunə təyin edilməyib")
        index = min(self._index, len(self.samples) - 1)
        self._index += 1
        return self.samples[index]

    def distance(self, reference: Any, candidate: Any) -> float:
        self.distance_calls.append((reference, candidate))
        return math.dist(reference.values, candidate.values)


class FakeCamera:
    """`CameraCapture` sahtəsi — nasazlıq AYRICA bayraqla ifadə olunur.

    `available=False` ilə "boş kadr siyahısı" HALLARI QƏSDƏN AYRIDIR: birincisi
    avadanlıq nasazlığıdır (bənd 5 — eskalasiya), ikincisi isə işçinin hərəkəti
    vaxtında etməməsidir (`NO_FACE_DETECTED`, sayğacsız).
    """

    def __init__(
        self,
        *,
        available: bool = True,
        frames: list[Any] | None = None,
        clock: FakeClock | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.available = available
        self.frames = frames
        self._clock = clock
        self._delay_seconds = delay_seconds
        self.captures: list[tuple[int, Any]] = []

    def is_available(self) -> bool:
        return self.available

    def capture(self, *, count: int = 1, gesture: Any = None) -> list[Any]:
        from src.domain.value_objects.face_recognition import FaceFrame

        self.captures.append((count, gesture))
        if self._clock is not None and self._delay_seconds:
            self._clock.advance(seconds=self._delay_seconds)
        if self.frames is not None:
            return list(self.frames[:count]) if count > 1 else list(self.frames[:1])
        return [FaceFrame(payload=b"kadr", width=640, height=480) for _ in range(count)]


class InMemoryFaceProfiles:
    """`FaceEmbeddingRepository` sahtəsi — `employees` üz sahələri + arxiv.

    ŞİFRƏLƏMƏ BURADA YOXDUR VƏ BU DOĞRUDUR: real repo-da şifrələmə saxlama
    detalıdır (`face_repository.py`), use case isə açıq vektorla işləyir.
    Sahtəyə şifrələmə əlavə etmək testləri açar provayderindən asılı edərdi.
    """

    def __init__(self, profiles: list[Any] | None = None) -> None:
        self.items: dict[EmployeeId, Any] = {p.employee_id: p for p in profiles or []}
        #: Arxiv sətirləri: `(employee_id, status, embedding, reason)`.
        self.archive_rows: list[tuple[EmployeeId, str, Any, str | None]] = []

    def get_profile(self, employee_id: EmployeeId) -> Any:
        return self.items.get(employee_id)

    def save_enrollment(self, employee_id: EmployeeId, *, embedding: Any, enrolled_at: Any) -> None:
        from dataclasses import replace

        profile = self.items[employee_id]
        self.items[employee_id] = replace(profile, embedding=embedding, enrolled_at=enrolled_at)

    def save_security(
        self, employee_id: EmployeeId, *, mismatch_attempts: int, locked_until: Any
    ) -> None:
        from dataclasses import replace

        profile = self.items[employee_id]
        self.items[employee_id] = replace(
            profile, mismatch_attempts=mismatch_attempts, locked_until=locked_until
        )

    def archive(
        self,
        employee_id: EmployeeId,
        *,
        archived_by: EmployeeId | None,
        reason: str | None,
        archived_at: Any,
    ) -> bool:
        profile = self.items.get(employee_id)
        if profile is None or profile.embedding is None:
            return False
        self.archive_rows.append((employee_id, "REPLACED", profile.embedding, reason))
        return True

    def purge(
        self,
        employee_id: EmployeeId,
        *,
        purged_by: EmployeeId | None,
        reason: str | None,
        purged_at: Any,
    ) -> bool:
        """Vektoru HƏM cari sətirdən, HƏM arxivdən silir (bənd 8).

        Arxivin təmizlənməsi real repo-da ayrıca `UPDATE`-dir; burada da
        AYRICA addım kimi saxlanılır, çünki məhz onun unudulması bənd 8-i
        sükutla pozan səhvdir.
        """
        from dataclasses import replace

        profile = self.items.get(employee_id)
        had_vector = profile is not None and profile.embedding is not None
        cleared = [row for row in self.archive_rows if row[0] == employee_id and row[2] is not None]
        if had_vector:
            self.archive_rows.append((employee_id, "PURGED", None, reason))
            self.items[employee_id] = replace(profile, embedding=None, enrolled_at=None)
        self.archive_rows = [
            (row[0], "PURGED", None, row[3]) if row[0] == employee_id else row
            for row in self.archive_rows
        ]
        self._assert_purge_invariant()
        return had_vector or bool(cleared)

    def list_store_profiles(
        self, tenant_id: TenantId, store_id: StoreId, *, exclude: EmployeeId | None = None
    ) -> list[Any]:
        return [
            profile
            for profile in self.items.values()
            if profile.tenant_id == tenant_id
            and profile.store_id == store_id
            and profile.embedding is not None
            and profile.employee_id != exclude
        ]

    def list_stale_enrollments(
        self, tenant_id: TenantId, *, enrolled_before: datetime
    ) -> list[Any]:
        return sorted(
            (
                profile
                for profile in self.items.values()
                if profile.tenant_id == tenant_id
                and profile.enrolled_at is not None
                and profile.enrolled_at < enrolled_before
            ),
            key=lambda profile: profile.enrolled_at,
        )

    def _assert_purge_invariant(self) -> None:
        for _employee_id, status, embedding, _reason in self.archive_rows:
            if status == "PURGED" and embedding is not None:
                raise FaceArchiveConstraintError(
                    "`PURGED` arxiv sətri vektor saxlaya bilməz (chk_face_history_purge)"
                )


class InMemoryFaceVerificationLog:
    """`FaceVerificationLogRepository` sahtəsi.

    `update()` QƏSDƏN YOXDUR: real cədvəldə tətbiq rolundan `UPDATE` geri
    alınıb (jurnal sətri FAKTdır) — sahtə repo real məhdudiyyətdən daha
    sərbəst olmamalıdır.
    """

    def __init__(self) -> None:
        self.entries: list[Any] = []

    def record(self, entry: Any) -> None:
        self.entries.append(entry)

    def purge_older_than(self, tenant_id: TenantId, *, cutoff: datetime) -> int:
        kept = [
            entry
            for entry in self.entries
            if not (entry.tenant_id == tenant_id and entry.occurred_at < cutoff)
        ]
        removed = len(self.entries) - len(kept)
        self.entries = kept
        return removed

    def list_mismatches_since(self, tenant_id: TenantId, *, since: datetime) -> list[Any]:
        return [
            entry
            for entry in self.entries
            if entry.tenant_id == tenant_id
            and entry.result.value == "MISMATCH"
            and entry.occurred_at >= since
        ]

    def results(self) -> list[str]:
        """Yazılmış nəticələrin sırası — testlərin oxu köməkçisi."""
        return [str(entry.result.value) for entry in self.entries]


class InMemoryFaceExemptions:
    """`FaceExemptionRepository` sahtəsi.

    `delete()` YOXDUR (real cədvəldə `REVOKE DELETE`). `active_for` HƏM
    statusa, HƏM `expires_at`-a baxır — gecəlik iş işləməsə belə istisna öz
    tarixində bitir.
    """

    def __init__(self, exemptions: list[Any] | None = None) -> None:
        self.items: dict[Any, Any] = {e.exemption_id: e for e in exemptions or []}

    def get(self, exemption_id: Any) -> Any:
        return self.items.get(exemption_id)

    def active_for(self, employee_id: EmployeeId, *, now: datetime) -> Any:
        for exemption in self.items.values():
            if exemption.employee_id == employee_id and exemption.is_active_at(now):
                return exemption
        return None

    def list_due_for_expiry(self, tenant_id: TenantId, *, now: datetime) -> list[Any]:
        return [
            exemption
            for exemption in self.items.values()
            if exemption.tenant_id == tenant_id and exemption.is_due_for_expiry(now)
        ]

    def list_active(self, tenant_id: TenantId, *, now: datetime) -> list[Any]:
        return [
            exemption
            for exemption in self.items.values()
            if exemption.tenant_id == tenant_id and exemption.is_active_at(now)
        ]

    def save(self, exemption: Any) -> None:
        self.items[exemption.exemption_id] = exemption


class FakeFaceStoreScope:
    """`FaceStoreScopeRepository` sahtəsi — DEFOLT BOŞ = qlobal davranış (bənd 15)."""

    def __init__(self, store_ids: set[StoreId] | None = None) -> None:
        self.store_ids = store_ids or set()
        self.changes: list[tuple[StoreId, bool]] = []

    def active_scope(self, tenant_id: TenantId) -> Any:
        from src.domain.value_objects.face_recognition import FaceStoreScope

        return FaceStoreScope(store_ids=frozenset(self.store_ids))

    def set_active(
        self, tenant_id: TenantId, store_id: StoreId, *, active: bool, changed_by: EmployeeId
    ) -> None:
        self.changes.append((store_id, active))
        if active:
            self.store_ids.add(store_id)
        else:
            self.store_ids.discard(store_id)


class FakeFineTypes:
    def __init__(self, entries: dict[Any, Any] | None = None) -> None:
        self.entries = entries or {}

    def get(self, fine_type_id: Any) -> Any:
        return self.entries.get(fine_type_id)

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        return [entry for entry in self.entries.values() if include_inactive or entry.is_active]

    def save(self, tenant_id: TenantId, entry: Any, *, changed_by: EmployeeId) -> None:
        self.entries[entry.fine_type_id] = entry

    def deactivate(self, tenant_id: TenantId, fine_type_id: Any, *, changed_by: EmployeeId) -> None:
        self.entries.pop(fine_type_id, None)
