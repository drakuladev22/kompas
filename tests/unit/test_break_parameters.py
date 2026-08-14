"""Nahar / Çay fasiləsi — ROOT parametrləri və gündəlik sayğac (nahar.md).

──────────────────────────────────────────────────────────────────────────────
BU FAYL DÖRD QATI AYRICA YOXLAYIR
──────────────────────────────────────────────────────────────────────────────
    1. DOMEN   — `BreakKind` / `BreakAllowance` / `ordinal_az` qərarları.
    2. TƏTBİQ  — STEP1 sayğacı artırırmı, hədd aşılanda BLOKLAYIRMI (yox!).
    3. İNFRA   — UPSERT atomikdir, naməlum növ sükutla atılır, HR redaktəsi
                 `break_kind` nişanını POZMUR.
    4. TƏQDİMAT— ROOT ekranında hər açar YALNIZ bir bölmədə, işçi ekranında
                 defolt seçim «Ümumi icazə».

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, `test_use_cases.py`-A ƏLAVƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
`test_use_cases.py` 3-STEP axınının ÖZÜNÜ qoruyur (status keçidləri, Saga,
kompensasiya). Fasilə sayğacı isə həmin axının ÜSTÜNƏ qoyulmuş ayrı qatdır və
nahar.md-nin QIRMIZI XƏTTİ məhz budur: mövcud axın dəyişməməlidir. İki mövzunu
bir fayla yığsaydıq, sabah fasilə testi qırılanda "STEP1 sındı" kimi oxunardı.

──────────────────────────────────────────────────────────────────────────────
ƏN VACİB İDDİA
──────────────────────────────────────────────────────────────────────────────
`test_exceeding_the_daily_count_does_not_block_the_request` — nahar.md
§MƏNTİQ bənd 2 AÇIQ göstərişdir və gələcəkdə kimsə "limit varsa, bloklamaq
lazımdır" düşüncəsi ilə onu sərtləşdirə bilər. Həmin dəyişiklik real mağaza
əməliyyatını qəfil dayandırardı; bu test onun qarşısındakı qapıdır.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from src.application.use_cases.leave_verification import LeaveVerificationUseCase
from src.domain.policies import (
    DEFAULT_LIMITS,
    BreakAllowance,
    BreakKind,
    SystemLimitKey,
    ordinal_az,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    LeaveTypeId,
    StoreId,
    TenantId,
)
from src.infrastructure.persistence.break_usage_repository import (
    PostgresDailyBreakUsageRepository,
)
from src.infrastructure.persistence.config_repositories import PostgresLeaveTypeRepository
from src.shared.saga_orchestrator import SagaOrchestrator
from tests.conftest import requires_qt
from tests.fixtures.fakes import (
    FakeCameraAssignments,
    FakeClock,
    FakeFeatureToggles,
    FakeLeaveTypes,
    FakeNtp,
    FakeSystemLimits,
    InMemoryBreakUsage,
    InMemoryEmployees,
    InMemoryFines,
    InMemoryLeaveRequests,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())
OTHER_WORKER = EmployeeId(uuid.uuid4())

LUNCH_TYPE = LeaveTypeId(uuid.uuid4())
TEA_TYPE = LeaveTypeId(uuid.uuid4())
#: Nişansız növ — HR_Admin-in sərbəst əlavə etdiyi adi icazə ("Bank işi").
PLAIN_TYPE = LeaveTypeId(uuid.uuid4())

NOW: Final = datetime(2026, 8, 14, 11, 0, tzinfo=UTC)

_MIGRATION: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "045_break_parameters_and_daily_usage.sql"
)


# --------------------------------------------------------------------------- #
# 1. DOMEN — `BreakKind`, `BreakAllowance`, `ordinal_az`
# --------------------------------------------------------------------------- #


def test_each_break_kind_points_at_its_own_pair_of_root_keys() -> None:
    """Növ → açar bağlantısı: səhv bağlantı Çay həddini Nahara tətbiq edərdi."""
    assert BreakKind.LUNCH.duration_key is SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES
    assert BreakKind.LUNCH.daily_count_key is SystemLimitKey.LUNCH_BREAK_DAILY_COUNT
    assert BreakKind.TEA.duration_key is SystemLimitKey.TEA_BREAK_DURATION_MINUTES
    assert BreakKind.TEA.daily_count_key is SystemLimitKey.TEA_BREAK_DAILY_COUNT


def test_every_break_key_has_a_default_and_a_screen_label() -> None:
    """Dörd açarın hamısı `DEFAULT_LIMITS`-dədir (ROOT ekranı `KeyError` verməsin)."""
    for kind in BreakKind:
        assert kind.duration_key in DEFAULT_LIMITS
        assert kind.daily_count_key in DEFAULT_LIMITS


def test_the_possessive_label_is_not_built_by_appending_a_suffix() -> None:
    """«Nahar fasiləniz», «Nahar fasiləsiniz» YOX — şəkilçi ƏVƏZLƏNİR.

    Sadəcə `label_az + "niz"` yazmaq qrammatik cəhətdən səhv forma verir və
    işçi ekranında hər gün görünərdi.
    """
    assert BreakKind.LUNCH.possessive_label_az == "Nahar fasiləniz"
    assert BreakKind.TEA.possessive_label_az == "Çay fasiləniz"
    for kind in BreakKind:
        assert "fasiləsiniz" not in kind.possessive_label_az


@pytest.mark.parametrize(
    ("used", "limit", "exceeded"),
    [(0, 2, False), (1, 2, False), (2, 2, False), (3, 2, True)],
)
def test_the_limit_is_exceeded_only_after_it_is_passed(
    used: int, limit: int, exceeded: bool
) -> None:
    """Hədd BƏRABƏRLİKDƏ aşılmır — «2/2» normal, «3/2» xəbərdarlıqdır."""
    allowance = BreakAllowance(
        kind=BreakKind.TEA, duration_minutes=15, daily_count=limit, used_count=used
    )
    assert allowance.is_exceeded is exceeded


def test_zero_daily_count_means_every_use_is_flagged() -> None:
    """`0` = "bu kirayəçidə fasilə nəzərdə tutulmayıb" (migrations/045 `min_value`).

    `MonthlyLeaveUsage` 0-ı LİMİTSİZ kimi oxuyur; burada isə əksinədir və
    fərq qəsdidir — 0 dəqiqəlik icazə büdcəsi mənasızdır, 0 fasilə isə tam
    mənalı konfiqurasiyadır.
    """
    allowance = BreakAllowance(
        kind=BreakKind.LUNCH, duration_minutes=60, daily_count=0, used_count=1
    )
    assert allowance.is_exceeded is True
    assert allowance.remaining_count == 0


def test_remaining_count_never_goes_negative() -> None:
    allowance = BreakAllowance(kind=BreakKind.TEA, duration_minutes=15, daily_count=2, used_count=5)
    assert allowance.remaining_count == 0


def test_the_warning_is_empty_while_the_limit_holds() -> None:
    """Boş sətir istisna ATMIR — ekran `if` ilə soruşur, `try` ilə yox."""
    allowance = BreakAllowance(kind=BreakKind.TEA, duration_minutes=15, daily_count=2, used_count=2)
    assert allowance.warning_az() == ""


def test_the_warning_matches_the_wording_the_specification_asks_for() -> None:
    """nahar.md-nin öz nümunəsi: «3-cü çay fasiləsi (limit: 2)»."""
    allowance = BreakAllowance(kind=BreakKind.TEA, duration_minutes=15, daily_count=2, used_count=3)
    assert allowance.warning_az() == "3-cü çay fasiləsi (limit: 2)"


def test_the_screen_labels_read_as_azerbaijani_sentences() -> None:
    allowance = BreakAllowance(
        kind=BreakKind.LUNCH, duration_minutes=60, daily_count=1, used_count=0
    )
    assert allowance.duration_label_az() == "Nahar fasiləniz: 60 dəqiqə"
    assert allowance.usage_label_az() == "Bu gün: 0/1 nahar fasiləsi istifadə edilib"


def test_a_corrupt_limit_row_falls_back_instead_of_crashing_the_screen() -> None:
    """`system_limits.limit_value` `TEXT`-dir — ora birbaşa SQL ilə "abc" yazıla bilər.

    Belə bir sətrə görə İşçi Ana Ekranının açılmaması qüsurun cəzasını səhv
    adama verərdi.
    """
    allowance = BreakAllowance.from_limits(
        BreakKind.LUNCH,
        {
            SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES.value: "abc",
            SystemLimitKey.LUNCH_BREAK_DAILY_COUNT.value: "",
        },
        used_count=1,
    )
    assert allowance.duration_minutes == int(
        DEFAULT_LIMITS[SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES]
    )
    assert allowance.daily_count == int(DEFAULT_LIMITS[SystemLimitKey.LUNCH_BREAK_DAILY_COUNT])


def test_from_limits_reads_the_root_value_when_it_is_valid() -> None:
    allowance = BreakAllowance.from_limits(
        BreakKind.TEA,
        {
            SystemLimitKey.TEA_BREAK_DURATION_MINUTES.value: "20",
            SystemLimitKey.TEA_BREAK_DAILY_COUNT.value: "4",
        },
        used_count=2,
    )
    assert (allowance.duration_minutes, allowance.daily_count) == (20, 4)


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (1, "1-ci"),
        (2, "2-ci"),
        (3, "3-cü"),
        (4, "4-cü"),
        (5, "5-ci"),
        (6, "6-cı"),
        (7, "7-ci"),
        (8, "8-ci"),
        (9, "9-cu"),
        (10, "10-cu"),
        (11, "11-ci"),
        (20, "20-ci"),
        (23, "23-cü"),
    ],
)
def test_azerbaijani_ordinals_follow_vowel_harmony(number: int, expected: str) -> None:
    """Tək şəkilçi işləmir: "3-cü" (üçüncü) ilə "2-ci" (ikinci) fərqlidir."""
    assert ordinal_az(number) == expected


def test_a_negative_ordinal_returns_the_bare_number_instead_of_raising() -> None:
    """Qrammatika heç bir halda əməliyyatı dayandırmamalıdır."""
    assert ordinal_az(0) == "0"
    assert ordinal_az(-1) == "-1"


# --------------------------------------------------------------------------- #
# 2. TƏTBİQ — STEP1 sayğacı
# --------------------------------------------------------------------------- #


class _Ctx:
    """Fasilə sayğacı üçün minimal `LeaveVerificationUseCase` konteksti.

    `test_use_cases.Ctx`-dən İDXAL EDİLMİR: ora kamera operatoru, cərimə
    repo-su və Saga ssenariləri üçün qurulub və bu faylın sualları həmin
    quruluşa ehtiyac duymur (STEP1 işçini repo-dan OXUMUR).
    """

    def __init__(self, **limit_overrides: str) -> None:
        self.clock = FakeClock(NOW)
        self.leave_requests = InMemoryLeaveRequests()
        self.leave_types = FakeLeaveTypes(
            {LUNCH_TYPE: 60, TEA_TYPE: 15, PLAIN_TYPE: 30},
            {LUNCH_TYPE: BreakKind.LUNCH, TEA_TYPE: BreakKind.TEA},
        )
        self.break_usage = InMemoryBreakUsage()
        self.limits = FakeSystemLimits(limit_overrides or None)
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()

        self.use_case = LeaveVerificationUseCase(
            leave_requests=self.leave_requests,  # type: ignore[arg-type]
            fines=InMemoryFines(),  # type: ignore[arg-type]
            employees=InMemoryEmployees(),  # type: ignore[arg-type]
            leave_types=self.leave_types,  # type: ignore[arg-type]
            camera_assignments=FakeCameraAssignments(),  # type: ignore[arg-type]
            break_usage=self.break_usage,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            ntp=FakeNtp(self.clock),  # type: ignore[arg-type]
            limits=self.limits,  # type: ignore[arg-type]
            toggles=FakeFeatureToggles(),  # type: ignore[arg-type]
            saga=SagaOrchestrator(),
            audit=self.audit,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def step1(self, leave_type_id: LeaveTypeId | None, *, employee_id: EmployeeId = WORKER) -> Any:
        """STEP1 — ardıcıl çağırışlar üçün açıq sorğu təmizlənir.

        "Eyni anda yalnız BİR açıq icazə" qaydası MÖVCUD davranışdır və bu
        faylın mövzusu deyil (onun testi `test_use_cases.py`-dadır). Burada
        sual gündə NEÇƏ DƏFƏ fasilə başladığıdır, ona görə hər çağırışdan
        əvvəl əvvəlki sorğu bağlanmış sayılır.
        """
        self.leave_requests.items.clear()
        return self.use_case.request_leave(
            tenant_id=TENANT,
            employee_id=employee_id,
            store_id=STORE,
            leave_type_id=leave_type_id,
            employee_is_in_store=True,
        )

    def leave_audit(self) -> dict[str, Any]:
        entries = [e for e in self.audit.entries if e["action"] == "LEAVE_REQUESTED"]
        return dict(entries[-1]["after_state"])


def test_step1_increments_the_counter_for_a_marked_break_type() -> None:
    ctx = _Ctx()
    ctx.step1(TEA_TYPE)
    ctx.step1(TEA_TYPE)

    status = ctx.use_case.break_status(tenant_id=TENANT, employee_id=WORKER, on_date=NOW.date())
    assert status[BreakKind.TEA].used_count == 2
    assert status[BreakKind.LUNCH].used_count == 0


def test_a_plain_leave_type_never_touches_the_break_counter() -> None:
    """Nahar/Çay ümumi kataloqdan AYRI qatdır (nahar.md TƏSVİR bölməsi).

    "Bank işi" seçən işçinin sorğusu fasilə sayılsaydı, HR paneli səbəbsiz
    xəbərdarlıq göstərərdi.
    """
    ctx = _Ctx()
    ctx.step1(PLAIN_TYPE)

    status = ctx.use_case.break_status(tenant_id=TENANT, employee_id=WORKER, on_date=NOW.date())
    assert all(allowance.used_count == 0 for allowance in status.values())
    assert "break_kind" not in ctx.leave_audit()


def test_step1_without_a_leave_type_keeps_the_previous_behaviour() -> None:
    """«Ümumi icazə» — işçi ekranının DEFOLT seçimi; bugünkü davranışın eynisi."""
    ctx = _Ctx()
    ctx.step1(None)

    assert ctx.break_usage.counts == {}
    assert "break_kind" not in ctx.leave_audit()


def test_exceeding_the_daily_count_does_not_block_the_request() -> None:
    """nahar.md §MƏNTİQ, bənd 2 — AÇIQ göstəriş: bloklama YOX.

    Bax modul başlığındakı "ƏN VACİB İDDİA" izahı.
    """
    ctx = _Ctx()
    ctx.step1(LUNCH_TYPE)  # limit 1
    request = ctx.step1(LUNCH_TYPE)  # 2-ci — hədd aşılır

    assert request is not None
    assert request.employee_id == WORKER
    # Sorğu HƏQİQƏTƏN yazılıb, yəni əməliyyat sonadək gedib.
    assert ctx.leave_requests.items


def test_exceeding_the_daily_count_notifies_hr_without_blocking() -> None:
    ctx = _Ctx()
    ctx.step1(LUNCH_TYPE)
    assert ctx.notifier.categories() == []

    ctx.step1(LUNCH_TYPE)
    assert "BREAK_DAILY_LIMIT_EXCEEDED" in ctx.notifier.categories()
    body = ctx.notifier.messages[-1]["body_az"]
    assert "2-ci nahar fasiləsi (limit: 1)" in body
    assert "bloklanmadı" in body


def test_the_audit_row_records_the_counter_as_it_was_at_that_moment() -> None:
    """«İşçiyə limit aşıldığı bildirildimi?» sualı sonradan cavablanmalıdır.

    Sayğacın ÖZÜ sabah dəyişir; audit sətri isə dəyişmir.
    """
    ctx = _Ctx()
    ctx.step1(LUNCH_TYPE)
    ctx.step1(LUNCH_TYPE)

    after = ctx.leave_audit()
    assert after["break_kind"] == "LUNCH"
    assert after["break_used_count"] == 2
    assert after["break_daily_count"] == 1
    assert after["break_limit_exceeded"] is True


def test_the_root_limit_takes_effect_without_a_restart() -> None:
    """Hədd `system_limits`-dən HƏR çağırışda oxunur, keşlənmir.

    Kodda sabit qalsaydı, Root dəyəri dəyişəndə panel köhnə həddi göstərməyə
    davam edərdi — parametrin "idarə olunan" görünüb faktiki hardcode qalması.
    """
    ctx = _Ctx()
    ctx.step1(TEA_TYPE)  # defolt limit 2 — aşılma yoxdur
    assert ctx.notifier.categories() == []

    ctx.limits.set(SystemLimitKey.TEA_BREAK_DAILY_COUNT, "0")
    ctx.step1(TEA_TYPE)
    assert "BREAK_DAILY_LIMIT_EXCEEDED" in ctx.notifier.categories()


def test_break_status_always_returns_both_kinds() -> None:
    """İşçi haqqını İSTİFADƏ ETMƏMİŞDƏN ƏVVƏL görməlidir — boş kart olmaz."""
    ctx = _Ctx()
    status = ctx.use_case.break_status(tenant_id=TENANT, employee_id=WORKER, on_date=NOW.date())

    assert set(status) == set(BreakKind)
    assert status[BreakKind.LUNCH].daily_count == 1
    assert status[BreakKind.TEA].daily_count == 2
    assert all(allowance.used_count == 0 for allowance in status.values())


def test_the_hr_overview_lists_only_those_past_the_limit() -> None:
    ctx = _Ctx()
    ctx.step1(TEA_TYPE, employee_id=WORKER)  # 1/2 — normal
    ctx.step1(LUNCH_TYPE, employee_id=OTHER_WORKER)
    ctx.step1(LUNCH_TYPE, employee_id=OTHER_WORKER)  # 2/1 — aşılıb

    overuse = ctx.use_case.break_overuse_for_day(tenant_id=TENANT, on_date=NOW.date())

    assert [usage.employee_id for usage in overuse] == [OTHER_WORKER]
    assert overuse[0].allowance.warning_az() == "2-ci nahar fasiləsi (limit: 1)"


def test_the_hr_overview_re_evaluates_when_root_lowers_the_limit() -> None:
    """Süzgəc SQL-də deyil, domendədir — Root dəyəri dərhal təsir edir."""
    ctx = _Ctx()
    ctx.step1(TEA_TYPE)
    assert ctx.use_case.break_overuse_for_day(tenant_id=TENANT, on_date=NOW.date()) == []

    ctx.limits.set(SystemLimitKey.TEA_BREAK_DAILY_COUNT, "0")
    assert len(ctx.use_case.break_overuse_for_day(tenant_id=TENANT, on_date=NOW.date())) == 1


def test_counters_are_kept_per_employee_and_per_kind() -> None:
    ctx = _Ctx()
    ctx.step1(TEA_TYPE, employee_id=WORKER)
    ctx.step1(LUNCH_TYPE, employee_id=WORKER)
    ctx.step1(TEA_TYPE, employee_id=OTHER_WORKER)

    mine = ctx.use_case.break_status(tenant_id=TENANT, employee_id=WORKER, on_date=NOW.date())
    theirs = ctx.use_case.break_status(
        tenant_id=TENANT, employee_id=OTHER_WORKER, on_date=NOW.date()
    )
    assert (mine[BreakKind.TEA].used_count, mine[BreakKind.LUNCH].used_count) == (1, 1)
    assert (theirs[BreakKind.TEA].used_count, theirs[BreakKind.LUNCH].used_count) == (1, 0)


# --------------------------------------------------------------------------- #
# 3. İNFRASTRUKTUR — repository qərarları (baza LAZIM DEYİL)
# --------------------------------------------------------------------------- #


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows = rows
        self._log = log
        self.rowcount = len(rows)

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._log.append((" ".join(sql.split()), params))

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.rows, self.executed)


class _Context:
    def __init__(self, tenant_id: TenantId) -> None:
        self.tenant_id = tenant_id


def _repo(repo_cls: type, rows: list[dict[str, Any]] | None = None) -> tuple[Any, _FakeConnection]:
    conn = _FakeConnection(rows)
    return repo_cls(conn, _Context(TENANT)), conn


def test_recording_a_use_is_a_single_atomic_upsert() -> None:
    """İki kiosk terminalı eyni saniyədə STEP1 göndərə bilər.

    "Oxu → artır → yaz" ardıcıllığı bir artımı İZSİZ itirərdi; artım bazanın
    öz sətir kilidi altında olmalıdır və yeni dəyər EYNİ gedişdə qayıtmalıdır.
    """
    repo, conn = _repo(PostgresDailyBreakUsageRepository, rows=[{"count_used": 3}])

    result = repo.record_use(TENANT, WORKER, kind=BreakKind.TEA, on_date=NOW.date(), at=NOW)

    assert result == 3
    assert len(conn.executed) == 1, "artım BİR sorğuda olmalıdır (oxu + yaz ayrılmır)"
    sql, _ = conn.executed[0]
    assert "ON CONFLICT (employee_id, usage_date, break_type)" in sql
    assert "count_used = daily_break_usage.count_used + 1" in sql
    assert "RETURNING count_used" in sql


def test_a_missing_counter_row_reads_as_zero_not_as_an_error() -> None:
    repo, _ = _repo(PostgresDailyBreakUsageRepository, rows=[])
    assert repo.count_for_day(WORKER, kind=BreakKind.LUNCH, on_date=NOW.date()) == 0


def test_usage_for_day_fills_both_kinds_even_when_the_table_is_empty() -> None:
    """Ekran «məlumat yoxdur» ilə «hələ istifadə edilməyib» arasında fərq qoymamalıdır."""
    repo, _ = _repo(PostgresDailyBreakUsageRepository, rows=[])
    assert repo.usage_for_day(WORKER, on_date=NOW.date()) == dict.fromkeys(BreakKind, 0)


def test_an_unknown_break_type_is_skipped_instead_of_crashing_the_screen() -> None:
    """Gələcək miqrasiya üçüncü növ əlavə edə bilər — köhnə tətbiq işləməlidir."""
    rows = [
        {"break_type": "TEA", "count_used": 2},
        {"break_type": "SIGARET", "count_used": 9},
    ]
    repo, _ = _repo(PostgresDailyBreakUsageRepository, rows=rows)

    usage = repo.usage_for_day(WORKER, on_date=NOW.date())
    assert usage[BreakKind.TEA] == 2
    assert usage[BreakKind.LUNCH] == 0


def test_the_hr_query_skips_unknown_rows_but_keeps_the_rest() -> None:
    rows = [
        {"employee_id": WORKER, "break_type": "LUNCH", "count_used": 2},
        {"employee_id": OTHER_WORKER, "break_type": "SIGARET", "count_used": 5},
    ]
    repo, _ = _repo(PostgresDailyBreakUsageRepository, rows=rows)

    assert repo.usage_rows_for_day(TENANT, on_date=NOW.date()) == [(WORKER, BreakKind.LUNCH, 2)]


def test_the_hr_query_does_not_apply_the_limit_in_sql() -> None:
    """Hədd ROOT parametridir — SQL-ə yazılsaydı, İKİ mənbə yaranardı."""
    repo, conn = _repo(PostgresDailyBreakUsageRepository, rows=[])
    repo.usage_rows_for_day(TENANT, on_date=NOW.date())

    sql, _ = conn.executed[0]
    assert "count_used > 0" in sql, "yalnız boş sətir süzgəci gözlənilir"
    assert not re.search(r"count_used\s*>\s*[1-9]", sql), "hədd SQL-ə sızıb"


def test_break_kind_is_read_from_the_row_not_from_the_name() -> None:
    repo, _ = _repo(PostgresLeaveTypeRepository, rows=[{"break_kind": "TEA"}])
    assert repo.break_kind_of(TEA_TYPE) is BreakKind.TEA


def test_a_plain_leave_type_reports_no_break_kind() -> None:
    repo, _ = _repo(PostgresLeaveTypeRepository, rows=[{"break_kind": None}])
    assert repo.break_kind_of(PLAIN_TYPE) is None


def test_an_unknown_break_kind_reads_as_a_plain_leave_type() -> None:
    repo, _ = _repo(PostgresLeaveTypeRepository, rows=[{"break_kind": "SIGARET"}])
    assert repo.break_kind_of(PLAIN_TYPE) is None


def test_the_break_lookup_does_not_filter_on_is_active() -> None:
    """Sual "bu sətir hansı fasilədir", "seçilə bilərmi" DEYİL.

    HR növü deaktiv edəndən sonra da köhnə ekrandan gələn sorğu doğru sayğaca
    düşməlidir — əks halda sayğac səssizcə yanlış növə yazılardı.
    """
    repo, conn = _repo(PostgresLeaveTypeRepository, rows=[{"break_kind": "LUNCH"}])
    repo.break_kind_of(LUNCH_TYPE)

    sql, _ = conn.executed[0]
    assert "is_active" not in sql


def test_the_catalog_read_carries_the_break_marker_into_the_domain_object() -> None:
    rows = [
        {
            "id": LUNCH_TYPE,
            "tenant_id": TENANT,
            "name_az": "Nahar Fasiləsi",
            "default_duration_minutes": 60,
            "is_active": True,
            "break_kind": "LUNCH",
            # Sahtə bağlantı HƏR sorğuya eyni sətri qaytarır, `list_all()` isə
            # əvvəlcə ROOT tavanını (`system_limits`) oxuyur — ona görə sətir
            # hər iki sorğunun sütununu daşımalıdır. Tavan bu testin sualı
            # deyil (onun öz testi `test_config_repositories.py`-dadır).
            "limit_value": "720",
        }
    ]
    repo, _ = _repo(PostgresLeaveTypeRepository, rows=rows)
    entries = repo.list_all(TENANT)

    assert entries[0].break_kind is BreakKind.LUNCH


def test_an_hr_catalog_edit_cannot_erase_the_break_marker() -> None:
    """«İki qat, iki sahib»: sətrin MƏZMUNU HR-ın, STRUKTUR ROLU Root-undur.

    `save()` UPSERT-i `break_kind`-ı `EXCLUDED` siyahısına salsaydı, HR
    "Nahar Fasiləsi"nin müddətini dəyişəndə nişan `NULL`-a düşər və sayğac
    həmin andan etibarən sükutla dayanardı.
    """
    from src.domain.value_objects.catalogs import LeaveType

    repo, conn = _repo(PostgresLeaveTypeRepository, rows=[])
    repo.save(
        TENANT,
        LeaveType(
            name="Nahar Fasiləsi",
            tenant_id=TENANT,
            leave_type_id=LUNCH_TYPE,
            default_duration_minutes=45,
        ),
        changed_by=EmployeeId(uuid.uuid4()),
    )

    sql, _ = conn.executed[0]
    update_clause = sql.split("DO UPDATE SET", maxsplit=1)[1]
    assert "break_kind" not in update_clause
    assert "break_kind" not in sql.split("VALUES", maxsplit=1)[0]


# --------------------------------------------------------------------------- #
# 4. SXEM PARİTETİ — qayda İKİ yerdədir (CLAUDE.md §5)
# --------------------------------------------------------------------------- #


def _migration_text() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def test_the_sql_check_lists_exactly_the_domain_break_kinds() -> None:
    """Domen enum-u ilə DB `CHECK`-i ayrılsa, biri digərini rədd edərdi.

    Məsələn domenə üçüncü növ əlavə edilib miqrasiya unudulsaydı, `INSERT`
    `CHECK` pozuntusu ilə çökərdi — üstəlik STEP1-in ORTASINDA.
    """
    sql = _migration_text()
    domain = {kind.value for kind in BreakKind}

    for column in ("break_kind", "break_type"):
        matches = re.findall(rf"{column}\s+IN\s*\(([^)]*)\)", sql)
        assert matches, f"`{column}` üçün CHECK siyahısı tapılmadı"
        for raw in matches:
            assert {value.strip().strip("'") for value in raw.split(",")} == domain


def test_the_migration_creates_the_counter_table_with_a_tenant_scope() -> None:
    """RLS fail-closed (SEC-008) — sayğac da kirayəçiyə bağlıdır."""
    sql = _migration_text()
    assert "CREATE TABLE IF NOT EXISTS daily_break_usage" in sql
    assert "ALTER TABLE daily_break_usage ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY tenant_isolation ON daily_break_usage" in sql


def test_the_counter_table_denies_delete_to_the_application_role() -> None:
    """`ALTER DEFAULT PRIVILEGES` `DELETE`-i AVTOMATİK verir (migrations/018).

    Ona görə dar `GRANT` tək başına heç nə məhdudlaşdırmır — açıq `REVOKE`
    məcburidir, əks halda bir `DELETE` işçiyə göstərilmiş xəbərdarlığın
    əsasını izsiz yox edərdi.
    """
    sql = _migration_text()
    assert "REVOKE DELETE ON daily_break_usage" in sql


def test_only_one_lunch_and_one_tea_row_may_exist_per_tenant() -> None:
    sql = _migration_text()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_leave_types_break_kind" in sql
    assert "WHERE break_kind IS NOT NULL" in sql


def test_the_migration_seeds_every_break_key_for_new_tenants_too() -> None:
    """Mövcud kirayəçilər `INSERT`-lə, yenilər trigger-lə — hər ikisi lazımdır.

    Yalnız birini yazsaydıq, ya köhnə bazada sətir yaranmazdı, ya da yeni
    kirayəçi parametrsiz qalardı.
    """
    sql = _migration_text()
    assert "seed_break_parameters_for_new_tenant" in sql
    assert "trg_seed_break_parameters" in sql
    for kind in BreakKind:
        for key in (kind.duration_key, kind.daily_count_key):
            assert sql.count(f"'{key.value}'") >= 2, (
                f"«{key.value}» ya mövcud, ya da yeni kirayəçilər üçün seed edilməyib"
            )


# --------------------------------------------------------------------------- #
# 5. TƏQDİMAT — ROOT bölməsi və işçi ekranı
# --------------------------------------------------------------------------- #


def test_every_break_key_has_a_screen_label_and_a_range() -> None:
    """Etiketsiz açar ROOT ekranında texniki kod kimi görünərdi (bölmə 9)."""
    from src.presentation.controllers.root_control import BREAK_LIMIT_KEYS, LIMIT_LABELS

    for key in BREAK_LIMIT_KEYS:
        label, minimum, maximum, suffix = LIMIT_LABELS[key]
        assert label and not label.isupper()
        assert minimum <= int(DEFAULT_LIMITS[key]) <= maximum
        assert suffix in {"dəq", "dəfə"}


def test_the_break_section_keeps_the_duration_and_count_pairs_together() -> None:
    """Root onları BİRLİKDƏ dəyişir; əlifba sırası cütü qırardı."""
    from src.presentation.controllers.root_control import BREAK_LIMIT_KEYS

    assert BREAK_LIMIT_KEYS == (
        SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES,
        SystemLimitKey.LUNCH_BREAK_DAILY_COUNT,
        SystemLimitKey.TEA_BREAK_DURATION_MINUTES,
        SystemLimitKey.TEA_BREAK_DAILY_COUNT,
    )


@requires_qt
def test_the_root_screen_edits_each_break_key_in_exactly_one_place(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """İki yerdə redaktə olunan açar üçün qalibi düymələrin sırası həll edərdi."""
    from src.presentation.controllers.root_control import BREAK_LIMIT_KEYS, limit_row
    from src.presentation.screens.group_d import RootControlScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)

    screen.set_limits([limit_row(SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT.value, "240")])
    screen.set_break_limits([limit_row(key.value, DEFAULT_LIMITS[key]) for key in BREAK_LIMIT_KEYS])

    break_keys = {key.value for key in BREAK_LIMIT_KEYS}
    assert set(screen._break_inputs) == break_keys
    assert not (set(screen._limit_inputs) & break_keys)
    # Ümumi «Tətbiq Et» də fasilə sahələrini daşıyır — Root iki düymə basmağa
    # məcbur qalmamalıdır.
    assert break_keys <= set(screen.collected()["limits"])


@requires_qt
def test_the_employee_screen_defaults_to_a_plain_leave(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Defolt Nahar olsaydı, MÖVCUD davranış sükutla dəyişərdi.

    Bank işinə çıxan işçinin sorğusu nahar sayılar, sayğac səhv artar və
    BR-001 güzəşti gözlənilmədən tətbiq olunardı.
    """
    screen = _home_screen(qtbot, qt_app)
    screen.set_break_options(_break_option_rows())

    assert screen.selected_break_leave_type_id() == ""


@requires_qt
def test_the_break_card_stays_hidden_when_no_break_types_exist(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Miqrasiya tətbiq olunmamış bazada ekran BUGÜNKÜ halında qalmalıdır."""
    screen = _home_screen(qtbot, qt_app)
    assert screen._break_card.isHidden()

    screen.set_break_options(_break_option_rows())
    assert not screen._break_card.isHidden()

    screen.set_break_options([])
    assert screen._break_card.isHidden()


@requires_qt
def test_the_selection_survives_a_refresh(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Siyahı hər STEP1-dən sonra yenidən oxunur (sayğac dəyişib).

    Seçim sıfırlansaydı, ardıcıl iki çay fasiləsi üçün işçi seçimi hər dəfə
    təkrarlamalı olardı.
    """
    screen = _home_screen(qtbot, qt_app)
    screen.set_break_options(_break_option_rows())
    screen._break_combo.setCurrentIndex(2)  # 0 = Ümumi icazə, 1 = Nahar, 2 = Çay
    chosen = screen.selected_break_leave_type_id()

    screen.set_break_options(_break_option_rows(tea_used=2))

    assert screen.selected_break_leave_type_id() == chosen
    assert "2/2" in screen._break_detail.text()


@requires_qt
def test_the_warning_chip_appears_only_past_the_limit(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    screen = _home_screen(qtbot, qt_app)
    screen.set_break_options(_break_option_rows())
    screen._break_combo.setCurrentIndex(2)
    assert screen._break_warning.isHidden()

    screen.set_break_options(_break_option_rows(tea_used=3))
    assert not screen._break_warning.isHidden()
    assert screen._break_warning.text() == "3-cü çay fasiləsi (limit: 2)"


@requires_qt
def test_the_hr_card_is_hidden_when_nobody_passed_the_limit(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """«Bu gün heç kim aşmayıb» xəbər deyil — həmişə görünən boş kart
    HR-ı ona baxmamağa öyrədərdi."""
    from src.presentation.screens.group_c import DashboardScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = DashboardScreen(theme)
    qtbot.addWidget(screen)

    assert screen._break_card.isHidden()

    screen.set_break_overuse([("K. Vəliyev", "3-cü çay fasiləsi (limit: 2)")])
    assert not screen._break_card.isHidden()
    assert screen._break_rows.count() == 1

    screen.set_break_overuse([])
    assert screen._break_card.isHidden()
    assert screen._break_rows.count() == 0


# --------------------------------------------------------------------------- #
# 6. KİOSK KONTROLLERİ — seçim siyahısı (Qt TƏLƏB ETMİR)
# --------------------------------------------------------------------------- #


class _StubLeaveTypes:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        del tenant_id, include_inactive
        return self._entries


class _StubUow:
    def __init__(self, entries: list[Any]) -> None:
        self._leave_types = _StubLeaveTypes(entries)

    def repository(self, name: str) -> Any:
        assert name == "leave_types"
        return self._leave_types


class _StubLeaveVerification:
    def __init__(self, status: dict[BreakKind, BreakAllowance]) -> None:
        self._status = status

    def break_status(self, **_: Any) -> dict[BreakKind, BreakAllowance]:
        return self._status


class _StubSession:
    def __init__(self, entries: list[Any], status: dict[BreakKind, BreakAllowance]) -> None:
        self.tenant_id = TENANT
        self.uow = _StubUow(entries)
        self.leave_verification = _StubLeaveVerification(status)

    def commit(self) -> None:  # pragma: no cover — oxu yolu commit etmir
        raise AssertionError("Seçim siyahısı YAZMIR — commit gözlənilmir")


class _StubContext:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: Any, *, error: Exception | None = None) -> None:
        from contextlib import contextmanager

        self.tenant_id = TENANT
        self._session = session
        self._error = error

        @contextmanager
        def _open(*, user_id: Any = None) -> Any:
            del user_id
            if self._error is not None:
                raise self._error
            yield self._session

        self.session = _open


def _leave_type(name: str, type_id: LeaveTypeId, kind: BreakKind | None) -> Any:
    return type(
        "_LeaveType",
        (),
        {"name": name, "leave_type_id": type_id, "break_kind": kind},
    )()


def _kiosk_controller(
    entries: list[Any],
    status: dict[BreakKind, BreakAllowance] | None = None,
    *,
    error: Exception | None = None,
) -> Any:
    from src.presentation.controllers.kiosk import KioskController

    resolved = status or {
        BreakKind.LUNCH: BreakAllowance(
            kind=BreakKind.LUNCH, duration_minutes=60, daily_count=1, used_count=0
        ),
        BreakKind.TEA: BreakAllowance(
            kind=BreakKind.TEA, duration_minutes=15, daily_count=2, used_count=3
        ),
    }
    context = _StubContext(_StubSession(entries, resolved), error=error)
    return KioskController(context, store_id=STORE)  # type: ignore[arg-type]


def test_the_kiosk_offers_the_marked_break_types_in_declaration_order() -> None:
    """Sıra `BreakKind`-dan gəlir: bazanın əlifba sırası «Çay»-ı öndə qoyardı."""
    controller = _kiosk_controller(
        [
            _leave_type("Çay Fasiləsi", TEA_TYPE, BreakKind.TEA),
            _leave_type("Nahar Fasiləsi", LUNCH_TYPE, BreakKind.LUNCH),
        ]
    )

    options = controller.break_options(_stub_employee())

    assert [option["label"] for option in options] == ["Nahar Fasiləsi", "Çay Fasiləsi"]
    assert options[0]["leave_type_id"] == str(LUNCH_TYPE)


def test_the_kiosk_takes_the_label_from_the_catalog_and_the_duration_from_root() -> None:
    """HR sətrin ADINI dəyişə bilər; müddət isə YALNIZ Root parametridir."""
    controller = _kiosk_controller([_leave_type("Nahar (uzun)", LUNCH_TYPE, BreakKind.LUNCH)])

    option = controller.break_options(_stub_employee())[0]

    assert option["label"] == "Nahar (uzun)"
    assert option["detail"].startswith("Nahar fasiləniz: 60 dəqiqə")
    assert "Bu gün: 0/1" in option["detail"]


def test_the_kiosk_passes_the_warning_through_unchanged() -> None:
    """HR paneli ilə işçi ekranı EYNİ ifadəni göstərməlidir."""
    controller = _kiosk_controller([_leave_type("Çay Fasiləsi", TEA_TYPE, BreakKind.TEA)])

    option = controller.break_options(_stub_employee())[0]

    assert option["warning"] == "3-cü çay fasiləsi (limit: 2)"


def test_plain_catalog_entries_never_reach_the_break_selector() -> None:
    controller = _kiosk_controller([_leave_type("Bank işi", PLAIN_TYPE, None)])
    assert controller.break_options(_stub_employee()) == []


def test_a_failure_hides_the_card_instead_of_blocking_the_kiosk() -> None:
    """Kiosk PAYLAŞILAN cihazdır — göstəricinin olmaması düyməni bloklamamalıdır."""
    controller = _kiosk_controller([], error=RuntimeError("baza əlçatmazdır"))
    assert controller.break_options(_stub_employee()) == []


def _stub_employee() -> Any:
    return type("_Employee", (), {"id": WORKER})()


def _home_screen(qtbot: Any, qt_app: Any) -> Any:
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = EmployeeHomeScreen(
        theme,
        full_name="Aysel Quliyeva",
        position_name="Satış Məsləhətçisi",
        store_name="Bellona 28 May",
    )
    qtbot.addWidget(screen)
    return screen


def _break_option_rows(*, tea_used: int = 0) -> list[dict[str, str]]:
    """Kontrollerin qurduğu sətirlərin EYNİSİ (`kiosk._break_option`).

    Mətnlər `BreakAllowance`-dan qurulur, əl ilə yazılmır — testin gözlədiyi
    ifadə ilə istifadəçinin gördüyü ifadə ayrılmasın deyə.
    """
    lunch = BreakAllowance(kind=BreakKind.LUNCH, duration_minutes=60, daily_count=1, used_count=0)
    tea = BreakAllowance(
        kind=BreakKind.TEA, duration_minutes=15, daily_count=2, used_count=tea_used
    )
    return [
        {
            "leave_type_id": str(LUNCH_TYPE),
            "label": "Nahar Fasiləsi",
            "detail": f"{lunch.duration_label_az()} · {lunch.usage_label_az()}",
            "warning": lunch.warning_az(),
        },
        {
            "leave_type_id": str(TEA_TYPE),
            "label": "Çay Fasiləsi",
            "detail": f"{tea.duration_label_az()} · {tea.usage_label_az()}",
            "warning": tea.warning_az(),
        },
    ]
