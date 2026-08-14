"""Planlaşdırılmış İcra Xülasəsi (#30, kompas1.md Faza 6).

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR — VƏ NİYƏ MƏHZ BU
──────────────────────────────────────────────────────────────────────────────
`executive_digest.py`-ın modul başlığındakı BEŞ qərarın hər biri sükutla
pozula bilər — bu fayl məhz onları qapıya çevirir:

  1. BOŞ DÖVR → xülasə HƏMİŞƏ göndərilir (sükutla atlanmır).
  2. Alıcı rolu boş/aktiv işçisiz → ÇÖKMƏ yox, BROADCAST ehtiyatı.
  3. TƏKRAR GÖNDƏRMƏ — `last_sent_at` DAILY/WEEKLY üçün AYRI qapıdır.
  4. İnfrastruktur XƏTASI (`configs` repo çökür) → İSTİSNA SƏRBƏST YUXARI
     ÇIXIR (JobRunner-in FAILED yazması ÜÇÜN ŞƏRTDİR).
  5. 1C SƏRHƏDİ — statik `ast` qapısı (`multi_store_benchmark`/`attrition_risk`
     ilə EYNİ naxış).

Sahtələr BURADA, YERLİ (`test_field_reports.py` ilə eyni əsaslandırma: bu
fayl paralel fazaların sahtə dəstindən asılı olmamalıdır).
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases.executive_digest import (
    CONFIGURE_DIGEST_FLAG,
    DIGEST_NOTIFICATION_CATEGORY,
    ExecutiveDigestPermissionError,
    ExecutiveDigestUseCase,
)
from src.application.use_cases.multi_store_benchmark import BenchmarkMetric
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.executive_digest import (
    DigestFrequency,
    ExecutiveDigestConfig,
    InvalidDigestConfigError,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ExecutiveDigestConfigId,
    PositionId,
    StoreId,
    TenantId,
)

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
STORE: Final = StoreId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 13, 3, 0, tzinfo=UTC)  # Bakı: 07:00 (UTC+4)
DIGEST_FLAG = PermissionFlag(code=CONFIGURE_DIGEST_FLAG, category="HR")

_USE_CASE_PATH: Final = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "application"
    / "use_cases"
    / "executive_digest.py"
)
_REPO_PATH: Final = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "infrastructure"
    / "persistence"
    / "executive_digest_repository.py"
)


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


@dataclass
class FakeClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


class FakeLimits:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        try:
            return int(self._values.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(e["action"]) for e in self.entries]


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


class BrokenAudit:
    """Çağırılsa istisna atır — testlərdə audit ÜMUMİYYƏTLƏ gözlənilmir."""

    def record(self, **kwargs: object) -> None:  # pragma: no cover - çağırılmamalıdır
        raise AssertionError("run() audit yazmamalıdır (bax modul başlığı)")


class FakeExceptions:
    """`ExceptionRepository` — YALNIZ `list_open` lazımdır."""

    def __init__(self, open_count: int = 0) -> None:
        self.open_count = open_count

    def list_open(
        self, tenant_id: TenantId, *, store_ids: list[StoreId] | None = None, limit: int = 200
    ) -> list[object]:
        return [object()] * self.open_count


class FakeFacts:
    """`DigestFactProvider` — gecikən check-in sayı."""

    def __init__(self, late_count: int = 0) -> None:
        self.late_count = late_count
        self.calls: list[tuple[date, date]] = []

    def late_check_in_count(self, tenant_id: TenantId, *, start: date, end: date) -> int:
        self.calls.append((start, end))
        return self.late_count


class FakeBenchmark:
    """`MultiStoreMetricProvider` — filial-başına dəyərlər sabitlənir."""

    def __init__(self, values: dict[BenchmarkMetric, dict[StoreId, float]] | None = None) -> None:
        self._values = values or {}

    def active_stores(self, tenant_id: TenantId) -> dict[StoreId, str]:
        return {STORE: "Mərkəz"}

    def metric_values(
        self, tenant_id: TenantId, metric: BenchmarkMetric, *, start: date, end: date
    ) -> dict[StoreId, float]:
        return dict(self._values.get(metric, {}))


class FailingConfigs:
    """`ExecutiveDigestConfigRepository` — `list_for_tenant` İSTİSNA atır."""

    def list_for_tenant(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[ExecutiveDigestConfig]:
        raise ConnectionError("baza əlçatmazdır")


class FakeConfigs:
    """`ExecutiveDigestConfigRepository` — yaddaşda sətirlər + rol → işçi."""

    def __init__(self) -> None:
        self.rows: dict[ExecutiveDigestConfigId, ExecutiveDigestConfig] = {}
        #: rol_kodu → işçilər (real `employees JOIN positions` sorğusunun güzgüsü).
        self.role_members: dict[str, list[EmployeeId]] = {}
        self.marked_sent: list[tuple[ExecutiveDigestConfigId, datetime]] = []

    def get(self, config_id: ExecutiveDigestConfigId) -> ExecutiveDigestConfig | None:
        return self.rows.get(config_id)

    def list_for_tenant(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[ExecutiveDigestConfig]:
        return [
            row
            for row in self.rows.values()
            if row.tenant_id == tenant_id and (include_inactive or row.is_active)
        ]

    def save(self, entry: ExecutiveDigestConfig) -> ExecutiveDigestConfig:
        config_id = entry.config_id or ExecutiveDigestConfigId(uuid.uuid4())
        saved = ExecutiveDigestConfig(
            config_id=config_id,
            tenant_id=entry.tenant_id,
            recipient_role=entry.recipient_role,
            frequency=entry.frequency,
            metrics_included=entry.metrics_included,
            last_sent_at=self.rows.get(config_id).last_sent_at if config_id in self.rows else None,
            created_by=entry.created_by,
        )
        self.rows[config_id] = saved
        return saved

    def deactivate(
        self, tenant_id: TenantId, config_id: ExecutiveDigestConfigId, *, changed_by: EmployeeId
    ) -> None:
        existing = self.rows[config_id]
        self.rows[config_id] = ExecutiveDigestConfig(
            config_id=existing.config_id,
            tenant_id=existing.tenant_id,
            recipient_role=existing.recipient_role,
            frequency=existing.frequency,
            metrics_included=existing.metrics_included,
            last_sent_at=existing.last_sent_at,
            is_active=False,
            deactivated_at=NOW,
            created_by=existing.created_by,
        )

    def mark_sent(
        self, tenant_id: TenantId, config_id: ExecutiveDigestConfigId, *, sent_at: datetime
    ) -> None:
        self.marked_sent.append((config_id, sent_at))
        existing = self.rows[config_id]
        self.rows[config_id] = ExecutiveDigestConfig(
            config_id=existing.config_id,
            tenant_id=existing.tenant_id,
            recipient_role=existing.recipient_role,
            frequency=existing.frequency,
            metrics_included=existing.metrics_included,
            last_sent_at=sent_at,
            created_by=existing.created_by,
        )

    def list_route_recipients(self, tenant_id: TenantId, *, role_code: str) -> list[EmployeeId]:
        return list(self.role_members.get(role_code.strip().upper(), []))

    def add(self, config: ExecutiveDigestConfig) -> ExecutiveDigestConfigId:
        config_id = config.config_id or ExecutiveDigestConfigId(uuid.uuid4())
        row = ExecutiveDigestConfig(
            config_id=config_id,
            tenant_id=config.tenant_id,
            recipient_role=config.recipient_role,
            frequency=config.frequency,
            metrics_included=config.metrics_included,
            last_sent_at=config.last_sent_at,
            is_active=config.is_active,
            deactivated_at=config.deactivated_at,
            created_by=config.created_by,
        )
        self.rows[config_id] = row
        return config_id


@dataclass
class Harness:
    use_case: ExecutiveDigestUseCase
    configs: FakeConfigs
    facts: FakeFacts
    benchmark: FakeBenchmark
    exceptions: FakeExceptions
    audit: RecordingAudit
    notifier: RecordingNotifier
    clock: FakeClock
    limits: FakeLimits


def build(
    *,
    limits: dict[str, str] | None = None,
    benchmark_values: dict[BenchmarkMetric, dict[StoreId, float]] | None = None,
    late_count: int = 0,
    open_exceptions: int = 0,
    configs: FakeConfigs | None = None,
    audit: RecordingAudit | None = None,
) -> Harness:
    clock = FakeClock()
    fake_configs = configs or FakeConfigs()
    fake_facts = FakeFacts(late_count)
    fake_benchmark = FakeBenchmark(benchmark_values)
    fake_exceptions = FakeExceptions(open_exceptions)
    fake_audit = audit if audit is not None else RecordingAudit()
    fake_notifier = RecordingNotifier()
    fake_limits = FakeLimits(limits)
    use_case = ExecutiveDigestUseCase(
        configs=fake_configs,
        facts=fake_facts,
        benchmark=fake_benchmark,
        exceptions=fake_exceptions,
        limits=fake_limits,
        audit=fake_audit,
        clock=clock,
        notifier=fake_notifier,
    )
    return Harness(
        use_case=use_case,
        configs=fake_configs,
        facts=fake_facts,
        benchmark=fake_benchmark,
        exceptions=fake_exceptions,
        audit=fake_audit,
        notifier=fake_notifier,
        clock=clock,
        limits=fake_limits,
    )


def make_actor(*, flags: list[PermissionFlag] | None = None) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.ROOT.value,
        name_az="Root",
        priority=SystemRole.ROOT.default_priority,
        is_system=True,
    )
    for flag in flags if flags is not None else [DIGEST_FLAG]:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="R",
        last_name="Root",
        store_id=None,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def make_config(
    *,
    role: str = "CEO",
    frequency: DigestFrequency = DigestFrequency.DAILY,
    metrics: tuple[str, ...] = ("FINE_COUNT", "OPEN_EXCEPTION_COUNT"),
    last_sent_at: datetime | None = None,
) -> ExecutiveDigestConfig:
    return ExecutiveDigestConfig(
        config_id=None,
        tenant_id=TENANT,
        recipient_role=role,
        frequency=frequency,
        metrics_included=metrics,
        last_sent_at=last_sent_at,
    )


# --------------------------------------------------------------------------- #
# 1. BOŞ DÖVR — HƏMİŞƏ GÖNDƏRİLİR
# --------------------------------------------------------------------------- #


def test_run_sends_the_digest_even_when_every_metric_is_zero() -> None:
    """Sükutla atlanmır: sıfır göstərici DƏ ritmik xülasənin bir hissəsidir."""
    h = build(benchmark_values={}, late_count=0, open_exceptions=0)
    h.configs.add(make_config())
    employee = EmployeeId(uuid.uuid4())
    h.configs.role_members["CEO"] = [employee]

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.evaluated == 1
    assert report.sent == 1
    assert len(h.notifier.messages) == 1
    body = str(h.notifier.messages[0]["body_az"])
    assert "Cərimə sayı: 0" in body
    assert "Açıq istisna sayı: 0" in body


# --------------------------------------------------------------------------- #
# 2. ALICI ROLU BOŞ/AKTİV İŞÇİSİZ — ÇÖKMƏ YOX, BROADCAST
# --------------------------------------------------------------------------- #


def test_run_falls_back_to_broadcast_when_the_role_has_no_active_employee() -> None:
    h = build()
    h.configs.add(make_config(role="GHOST_ROLE"))
    # `role_members` QƏSDƏN doldurulmayıb — real "rol var, aktiv işçi yoxdur".

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.sent == 1
    assert len(h.notifier.messages) == 1
    message = h.notifier.messages[0]
    assert message["recipient_id"] is None
    assert message["category"] == DIGEST_NOTIFICATION_CATEGORY
    assert message["is_critical"] is True


def test_run_sends_one_message_per_resolved_recipient() -> None:
    h = build()
    h.configs.add(make_config(role="HR_ADMIN"))
    first, second = EmployeeId(uuid.uuid4()), EmployeeId(uuid.uuid4())
    h.configs.role_members["HR_ADMIN"] = [first, second]

    h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    recipients = {m["recipient_id"] for m in h.notifier.messages}
    assert recipients == {first, second}
    assert all(m["is_critical"] is True for m in h.notifier.messages)


# --------------------------------------------------------------------------- #
# 3. TƏKRAR GÖNDƏRMƏ — `last_sent_at` QAPISI
# --------------------------------------------------------------------------- #


def test_daily_digest_is_not_resent_the_same_local_day() -> None:
    h = build()
    config_id = h.configs.add(make_config(last_sent_at=NOW - timedelta(hours=2)))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.sent == 0
    assert h.notifier.messages == []
    assert h.configs.marked_sent == []
    assert config_id in h.configs.rows


def test_daily_digest_resends_on_the_next_local_day() -> None:
    h = build()
    yesterday_send = NOW - timedelta(days=1)
    h.configs.add(make_config(last_sent_at=yesterday_send))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.sent == 1
    assert len(h.configs.marked_sent) == 1


def test_weekly_digest_only_fires_on_the_configured_weekday() -> None:
    """2026-08-13 (isoweekday=4) defolt həftəlik göndəriş günü (1=Bazar ertəsi) DEYİL."""
    h = build()
    h.configs.add(make_config(frequency=DigestFrequency.WEEKLY))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.sent == 0
    assert h.notifier.messages == []


def test_weekly_digest_fires_on_the_configured_weekday_and_then_waits_a_full_week() -> None:
    monday = datetime(2026, 8, 17, 3, 0, tzinfo=UTC)  # Bazar ertəsi
    h = build()
    h.configs.add(make_config(frequency=DigestFrequency.WEEKLY))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    first = h.use_case.run(tenant_id=TENANT, now=monday, scheduled_for=monday)
    assert first.sent == 1

    # EYNİ gün TƏKRAR çağırılsa (at-least-once) — YENİDƏN göndərilmir.
    again = h.use_case.run(tenant_id=TENANT, now=monday, scheduled_for=monday)
    assert again.sent == 0

    # Növbəti Bazar ertəsi (7 gün sonra) — YENİDƏN DUE-dur.
    next_monday = monday + timedelta(days=7)
    later = h.use_case.run(tenant_id=TENANT, now=next_monday, scheduled_for=next_monday)
    assert later.sent == 1


def test_monthly_frequency_rows_are_never_processed_by_the_scheduler() -> None:
    """DB `MONTHLY`-ə icazə verir, LAKİN planlayıcı onu HEÇ VAXT emal etmir."""
    h = build()
    h.configs.add(make_config(frequency=DigestFrequency.MONTHLY))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.evaluated == 1
    assert report.sent == 0


# --------------------------------------------------------------------------- #
# 4. İNFRASTRUKTUR XƏTASI — SƏRBƏST YUXARI ÇIXIR (JobRunner FAILED yazsın)
# --------------------------------------------------------------------------- #


def test_run_lets_repository_failures_propagate_for_job_runner() -> None:
    """`run()` istisnanı UDMUR — `JobRunner._run_one` onu FAILED yazsın deyə."""
    h = build(configs=FailingConfigs())  # type: ignore[arg-type]

    with pytest.raises(ConnectionError):
        h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)


def test_run_never_writes_an_audit_entry() -> None:
    """`notify_overdue_audits` ilə EYNİ qərar: aqreqat audit sətri planlayıcının
    ÖZÜNDƏDİR (`SCHEDULED_JOBS_EXECUTED`) — hər göndəriş üçün AYRI sətir yoxdur."""
    h = build(audit=BrokenAudit())  # type: ignore[arg-type]
    h.configs.add(make_config())
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.sent == 1


# --------------------------------------------------------------------------- #
# 5. METRİK HESABLAMASI — MÖVCUD MƏNBƏLƏR ÇAĞIRILIR
# --------------------------------------------------------------------------- #


def test_fine_count_and_overtime_are_summed_network_wide() -> None:
    store_b = StoreId(uuid.uuid4())
    h = build(
        benchmark_values={
            BenchmarkMetric.FINE_COUNT: {STORE: 3.0, store_b: 2.0},
            BenchmarkMetric.OVERTIME_HOURS: {STORE: 4.5, store_b: 1.5},
        }
    )
    h.configs.add(make_config(metrics=("FINE_COUNT", "OVERTIME_HOURS")))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    body = str(h.notifier.messages[0]["body_az"])
    assert "Cərimə sayı: 5" in body
    assert "Overtime saatı: 6.0 saat" in body


def test_turnover_risk_is_averaged_network_wide() -> None:
    store_b = StoreId(uuid.uuid4())
    h = build(benchmark_values={BenchmarkMetric.TURNOVER_RISK: {STORE: 40.0, store_b: 60.0}})
    h.configs.add(make_config(metrics=("TURNOVER_RISK",)))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert "50.0 bal" in str(h.notifier.messages[0]["body_az"])


def test_late_check_in_count_is_queried_for_the_daily_window() -> None:
    h = build(late_count=7)
    h.configs.add(make_config(metrics=("LATE_CHECK_IN_COUNT",)))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert "Gecikən check-in sayı: 7" in str(h.notifier.messages[0]["body_az"])
    assert h.facts.calls == [(NOW.date() - timedelta(days=1), NOW.date())]


def test_a_metric_removed_from_the_catalog_is_silently_dropped_not_the_whole_row() -> None:
    """Kataloqdan çıxmış açar sətri POZMUR — YALNIZ həmin sətir atlanır."""
    h = build(
        limits={"EXECUTIVE_DIGEST_METRIC_CATALOG": "FINE_COUNT"},
        benchmark_values={BenchmarkMetric.FINE_COUNT: {STORE: 2.0}},
    )
    h.configs.add(make_config(metrics=("FINE_COUNT", "OPEN_EXCEPTION_COUNT")))
    h.configs.role_members["CEO"] = [EmployeeId(uuid.uuid4())]

    report = h.use_case.run(tenant_id=TENANT, now=NOW, scheduled_for=NOW)

    assert report.sent == 1
    body = str(h.notifier.messages[0]["body_az"])
    assert "Cərimə sayı: 2" in body
    assert "istisna" not in body.lower()


# --------------------------------------------------------------------------- #
# 6. ROOT YAZI YOLU — SƏLAHİYYƏT VƏ KATALOQ YOXLAMASI
# --------------------------------------------------------------------------- #


def test_configure_requires_the_permission_flag() -> None:
    h = build()
    stranger = make_actor(flags=[])

    with pytest.raises(ExecutiveDigestPermissionError):
        h.use_case.configure(
            TENANT, stranger, recipient_role="CEO", metrics=["FINE_COUNT"], frequency="DAILY"
        )


def test_configure_rejects_a_metric_outside_the_catalog() -> None:
    h = build(limits={"EXECUTIVE_DIGEST_METRIC_CATALOG": "FINE_COUNT"})
    actor = make_actor()

    with pytest.raises(InvalidDigestConfigError):
        h.use_case.configure(
            TENANT,
            actor,
            recipient_role="CEO",
            metrics=["FINE_COUNT", "TURNOVER_RISK"],
            frequency="DAILY",
        )


def test_configure_rejects_monthly_frequency_even_though_the_db_allows_it() -> None:
    h = build()
    actor = make_actor()

    with pytest.raises(InvalidDigestConfigError):
        h.use_case.configure(
            TENANT, actor, recipient_role="CEO", metrics=["FINE_COUNT"], frequency="MONTHLY"
        )


def test_configure_falls_back_to_the_root_default_frequency_when_none_is_given() -> None:
    h = build(limits={"EXECUTIVE_DIGEST_DEFAULT_FREQUENCY": "WEEKLY"})
    actor = make_actor()

    saved = h.use_case.configure(TENANT, actor, recipient_role="CEO", metrics=["FINE_COUNT"])

    assert saved.frequency is DigestFrequency.WEEKLY
    assert h.audit.actions() == ["EXECUTIVE_DIGEST_CONFIGURED"]


def test_configure_upserts_and_deactivate_soft_deletes() -> None:
    h = build()
    actor = make_actor()

    saved = h.use_case.configure(
        TENANT, actor, recipient_role="ceo", metrics=["fine_count"], frequency="daily"
    )
    assert saved.recipient_role == "CEO"
    assert saved.metrics_included == ("FINE_COUNT",)

    h.use_case.deactivate(TENANT, actor, saved.config_id)

    remaining = h.use_case.list_for_management(TENANT, actor)
    assert len(remaining) == 1
    assert not remaining[0].is_active
    assert "EXECUTIVE_DIGEST_DEACTIVATED" in h.audit.actions()


# --------------------------------------------------------------------------- #
# 7. DOMEN VALİDASİYASI — DB CHECK-in tətbiq-qatı güzgüsü
# --------------------------------------------------------------------------- #


def test_config_rejects_an_empty_metric_list() -> None:
    with pytest.raises(InvalidDigestConfigError):
        make_config(metrics=())


def test_config_rejects_a_too_short_role_code() -> None:
    with pytest.raises(InvalidDigestConfigError):
        make_config(role="X")


# --------------------------------------------------------------------------- #
# 8. 1C SƏRHƏDİ — statik `ast` qapısı (`test_benchmark_widgets.py` naxışı)
# --------------------------------------------------------------------------- #

_FORBIDDEN_1C_TOKENS: Final[tuple[str, ...]] = (
    "SalesDataConnector",
    "OneCSaleRecord",
    "ErpServer",
    "SyncCursor",
    "erp_servers",
    "sales_transactions",
)


@pytest.mark.parametrize("path", [_USE_CASE_PATH, _REPO_PATH], ids=lambda p: p.name)
def test_the_module_never_imports_anything_from_the_1c_layer(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    leaking = sorted(name for name in imported if "erp" in name or "sales" in name)
    assert not leaking, f"#30 1C qatına bağlandı: {leaking}"


@pytest.mark.parametrize("path", [_USE_CASE_PATH, _REPO_PATH], ids=lambda p: p.name)
def test_the_module_body_has_no_1c_identifiers(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)

    hits = sorted(token for token in _FORBIDDEN_1C_TOKENS if token in names)
    assert not hits, f"#30 kodunda 1C izi: {hits}"
