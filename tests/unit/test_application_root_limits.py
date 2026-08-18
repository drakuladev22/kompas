"""Tətbiq qatı ROOT parametrlərinin qapısı (Faza 10.2, ikinci dalğa).

──────────────────────────────────────────────────────────────────────────────
BU FAYL NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Faza 10.2-nin ikinci dalğası `src/application/` qatındakı 15 sabiti ROOT İdarə
Mərkəzinə köçürdü və birinci dalğanın açıq buraxdığı üç halqanı (satış xalı
kursu, etiraz pəncərəsi, sıfırlanma bildirişi) bağladı. Dörd ayrı qapı var:

  1. DEFOLT = KÖHNƏ HARDCODE — köçürmə DAVRANIŞ dəyişikliyi deyil. Kimsə
     defoltu "yaxşılaşdırsa", test dərhal qırılır.
  2. ARALIQ PARİTETİ — `APP_LIMIT_BOUNDS` ilə migrations/034-dəki
     `min_value`/`max_value` eyni olmalıdır. Ayrılsalar, ROOT ekranı "qəbul
     edilən" göstərən dəyəri kod sükutla kəsərdi.
  3. CANLI OXU — Root dəyəri dəyişdikdə KOD YENİ DƏYƏRİ OXUMALIDIR. Bu, ən
     vacib qapıdır: parametrin `SystemLimitKey`-də, `DEFAULT_LIMITS`-də və SQL
     seed-ində olması onun İŞLƏDİYİNİ SÜBUT ETMİR — istehlakçı hələ də modul
     sabitini oxuya bilər ("görünür, dəyişdirilir, təsirsiz" qüsuru). Aşağıdakı
     testlər hər bağlanmış istehlakçı üçün davranışın DƏYİŞDİYİNİ yoxlayır.
  4. FAİL-SAFE — yararsız/həddi aşan Root dəyəri ekranı çökdürməməlidir.

`tests/unit/test_root_control_parameter_parity.py` ayrıca hər açarın həm
`DEFAULT_LIMITS`-də, həm də SQL seed-ində olmasını yoxlayır — burada onu
təkrarlamırıq.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from src.application.root_limits import (
    APP_LIMIT_BOUNDS,
    fallback_int,
    fallback_int_tuple,
    limit_decimal,
    limit_int,
    limit_int_tuple,
)
from src.application.use_cases.announcements import AnnouncementUseCase
from src.application.use_cases.audit_query import AuditFilter, AuditQueryUseCase
from src.application.use_cases.backup_access import BackupAccessUseCase
from src.application.use_cases.developer_console import (
    ConsoleThresholds,
    CrashDashboard,
    CrashRecord,
    SlaState,
    SupportInbox,
    TicketRecord,
)
from src.application.use_cases.first_run_setup import FirstRunSetupUseCase
from src.application.use_cases.payment_reminders import (
    REMINDER_OFFSETS,
    PaymentReminderUseCase,
    ReminderMessage,
    TenantBilling,
    build_message,
    reminder_offsets,
)
from src.application.use_cases.sales_points import SalesPointsUseCase
from src.application.use_cases.sales_review_queue import SalesReviewQueueUseCase
from src.application.use_cases.shift_scheduling import ShiftRequestError, ShiftSwapUseCase
from src.application.use_cases.support_chat import SupportChatUseCase
from src.application.use_cases.sync_conflicts import ConflictItem, SyncConflictUseCase
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.entities.sales_points import PointsEntry
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PointsEntryId,
    PositionId,
    SalesTransactionId,
    StoreId,
    TenantId,
)
from tests.fixtures.fakes import (
    FakeClock,
    FakeFeatureToggles,
    FakeSystemLimits,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.UUID("22222222-2222-2222-2222-222222222222"))
STORE: Final = StoreId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

_MIGRATIONS_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "database" / "migrations"

#: Tətbiq qatının limitlərini seed edən BÜTÜN miqrasiyalar.
#:
#: Yeni tətbiq açarı gətirən miqrasiya buraya bir sətir əlavə edir (səbəb
#: `_migration_bounds` docstring-indədir).
_MIGRATIONS: Final[tuple[Path, ...]] = (
    _MIGRATIONS_DIR / "034_application_layer_limits.sql",
    _MIGRATIONS_DIR / "068_support_channels_telegram.sql",
)

#: Açar → Faza 10.2-nin ikinci dalğasından ƏVVƏL kodda oturan HƏRFİ dəyər.
#:
#: Siyahı ƏL İLƏ yazılıb və məhz bu, onun dəyəridir: dəyərləri
#: `DEFAULT_LIMITS`-dən oxusaydıq test öz-özünü təsdiqləyər və heç nə
#: qorumazdı. Buradakı ədədlər auditin göstərdiyi sətirlərdən götürülüb
#: (`developer_console.py:47,49,51,98,200`, `shift_scheduling.py:116`,
#: `payment_reminders.py:43`, `sales_review_queue.py:54`,
#: `audit_query.py:40,41`, `backup_access.py:57`, `announcements.py:193`,
#: `support_chat.py:127`, `sync_conflicts.py:118`, `first_run_setup.py:71`).
_PREVIOUS_HARDCODE: Final[dict[SystemLimitKey, str]] = {
    SystemLimitKey.SUPPORT_FIRST_RESPONSE_SLA_HOURS: "24",
    SystemLimitKey.SUPPORT_RESOLUTION_SLA_HOURS: "72",
    SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO: "0.75",
    SystemLimitKey.CRASH_WIDESPREAD_INSTALLATION_THRESHOLD: "3",
    SystemLimitKey.CRASH_DASHBOARD_TOP_LIMIT: "10",
    SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS: "90",
    SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS: "-7,-3,-1,1,7",
    SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE: "200",
    SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE: "500",
    SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE: "100",
    SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE: "60",
    SystemLimitKey.ANNOUNCEMENT_LIST_PAGE_SIZE: "50",
    SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE: "20",
    SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE: "100",
    SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT: "2",
}


# --------------------------------------------------------------------------- #
# 1. Defolt = köhnə hardcode
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("key", "expected"), sorted(_PREVIOUS_HARDCODE.items(), key=str))
def test_default_equals_the_previous_hardcoded_value(key: SystemLimitKey, expected: str) -> None:
    """Köçürmə DAVRANIŞ dəyişikliyi deyil, idarəolunma dəyişikliyidir."""
    assert DEFAULT_LIMITS[key] == expected, (
        f"«{key.value}» defoltu köçürmədən əvvəlki hardcode ilə eyni deyil — "
        "köçürmə mövcud quraşdırmanın davranışını sükutla dəyişərdi."
    )


# --------------------------------------------------------------------------- #
# 2. Aralıq pariteti (kod ↔ migrations/034)
# --------------------------------------------------------------------------- #


def _migration_bounds() -> dict[str, tuple[str, str]]:
    """`_MIGRATIONS`-dəki `('KEY', 'val', 'TYPE', 'min', 'max', ...)` sətirləri.

    SİYAHI FAYL DEYİL, DƏSTdir. Əvvəl burada tək 034 vardı və qapı «açar
    034-dədir?» soruşurdu — sonrakı miqrasiya ilə gələn hər yeni tətbiq
    açarı qapını POZURDU, halbuki onun qüsuru yox idi. Alternativ (açarı
    geri 034-ə yazmaq) artıq tətbiq olunmuş miqrasiyanı redaktə etmək
    deməkdir və `schema_migrations` checksum-u ilə birbaşa ziddiyyətdədir
    (migrations/061). Eyni düzəliş infrastruktur qapısında artıq tətbiq
    olunub — bax `test_infrastructure_root_limits._MIGRATIONS`.
    """
    pattern = re.compile(
        r"'(?P<key>[A-Z0-9_]+)',\s*'[^']*',\s*'(?:INTEGER|DECIMAL)',\s*"
        r"'(?P<low>-?[0-9.]+)',\s*'(?P<high>-?[0-9.]+)'"
    )
    found: dict[str, tuple[str, str]] = {}
    for path in _MIGRATIONS:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            key = match.group("key")
            bounds = (match.group("low"), match.group("high"))
            # Eyni açarın iki miqrasiyada fərqli hüdudu tətbiq SIRASINDAN
            # asılı davranış yaradardı — hansının qüvvədə olduğu bilinməzdi.
            assert found.get(key, bounds) == bounds, (
                f"«{key}» iki miqrasiyada fərqli hüdudlarla seed edilir"
            )
            found[key] = bounds
    return found


def test_code_bounds_match_the_migration_bounds() -> None:
    """İki mənbənin ayrılması "ekranda qəbul edilir, kodda kəsilir" deməkdir."""
    from_sql = _migration_bounds()
    for key, (low, high) in APP_LIMIT_BOUNDS.items():
        assert key.value in from_sql, f"«{key.value}» heç bir seed miqrasiyasında aralıqsızdır"
        sql_low, sql_high = from_sql[key.value]
        assert Decimal(sql_low) == low, f"«{key.value}» aşağı hüdudu fərqlənir"
        assert Decimal(sql_high) == high, f"«{key.value}» yuxarı hüdudu fərqlənir"


def test_every_new_numeric_key_has_a_bound() -> None:
    """Aralıqsız qalan ədədi açar `0` yazıldıqda ekranı boş göstərərdi."""
    # `LICENSE_PAYMENT_REMINDER_OFFSET_DAYS` MƏTN cədvəlidir və mənfi element
    # daşıyır — onun ədədi aralığı YOXDUR (bax `root_limits` şərhi).
    numeric = set(_PREVIOUS_HARDCODE) - {SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS}
    missing = sorted(key.value for key in numeric if key not in APP_LIMIT_BOUNDS)
    assert not missing, f"Aralığı olmayan yeni açar(lar): {missing}"


# --------------------------------------------------------------------------- #
# 3. Oxuyucunun özü — fallback, canlı oxu, klamp
# --------------------------------------------------------------------------- #


def test_reader_without_a_port_returns_the_default() -> None:
    """Portsuz oxu köçürmədən ƏVVƏLKİ davranışı verir."""
    assert limit_int(None, TENANT, SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE) == 500
    assert limit_int_tuple(None, TENANT, SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS) == (
        -7,
        -3,
        -1,
        1,
        7,
    )


def test_reader_follows_the_root_value() -> None:
    limits = FakeSystemLimits({SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE.value: "250"})
    assert limit_int(limits, TENANT, SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE) == 250


def test_reader_clamps_a_value_outside_the_bounds() -> None:
    """`0` səhifə ölçüsü siyahını HƏMİŞƏ boş göstərərdi — aşağı hüdud qoruyur."""
    limits = FakeSystemLimits({SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE.value: "0"})
    assert limit_int(limits, TENANT, SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE) == 1

    limits.set(SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO, "5.00")
    ratio = limit_decimal(limits, TENANT, SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO)
    assert ratio == Decimal("0.99")


def test_reader_survives_unusable_text() -> None:
    """Root-un yazı səhvi ekranı çökdürmür — defolta qayıdır."""
    limits = FakeSystemLimits({SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE.value: "altmış"})
    assert limit_int(limits, TENANT, SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE) == 60


def test_reader_never_returns_an_empty_schedule() -> None:
    """Boş cədvəl susan planlayıcı deməkdir — defolt işə düşür."""
    limits = FakeSystemLimits({SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS.value: "   "})
    assert limit_int_tuple(
        limits, TENANT, SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS
    ) == fallback_int_tuple(SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS)


def test_reader_keeps_negative_schedule_items() -> None:
    """T-7 mərhələsi mənfidir — hər hansı ədədi klamp onu yox edərdi."""
    limits = FakeSystemLimits(
        {SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS.value: "-30,-1,3"}
    )
    assert limit_int_tuple(limits, TENANT, SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS) == (
        -30,
        -1,
        3,
    )


# --------------------------------------------------------------------------- #
# 4. Developer Paneli — SLA və çökmə hədləri
# --------------------------------------------------------------------------- #


def _ticket(*, hours_ago: int, first_response_hours: int | None = None) -> TicketRecord:
    created = NOW - timedelta(hours=hours_ago)
    return TicketRecord(
        ticket_id=str(uuid.uuid4()),
        tenant_name="Bellona",
        subject="Kassa açılmır",
        status="OPEN",
        created_at=created,
        first_response_at=(
            None
            if first_response_hours is None
            else created + timedelta(hours=first_response_hours)
        ),
    )


def _crash(ref: str) -> CrashRecord:
    return CrashRecord(
        fingerprint="abc",
        exception_type="ValueError",
        app_version="1.0.0",
        anonymous_tenant_ref=ref,
        occurred_at=NOW,
    )


def test_sla_targets_follow_the_root_values() -> None:
    """24 saatlıq hədəf 4 saata endirildikdə eyni müraciət POZULMUŞ olur."""
    ticket = _ticket(hours_ago=6)

    with_default = SupportInbox.from_records([ticket], now=NOW)
    assert with_default.tickets[0].response_sla is SlaState.ON_TRACK

    limits = FakeSystemLimits({SystemLimitKey.SUPPORT_FIRST_RESPONSE_SLA_HOURS.value: "4"})
    tightened = SupportInbox.from_records(
        [ticket], now=NOW, thresholds=ConsoleThresholds.from_limits(limits, TENANT)
    )
    assert tightened.tickets[0].response_sla is SlaState.BREACHED


def test_at_risk_band_follows_the_root_ratio() -> None:
    """Zolaq 0.75 → 0.20 olanda 6 saatlıq müraciət artıq "risk altında"dır."""
    ticket = _ticket(hours_ago=6)
    assert SupportInbox.from_records([ticket], now=NOW).tickets[0].response_sla is SlaState.ON_TRACK

    limits = FakeSystemLimits({SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO.value: "0.20"})
    widened = SupportInbox.from_records(
        [ticket], now=NOW, thresholds=ConsoleThresholds.from_limits(limits, TENANT)
    )
    assert widened.tickets[0].response_sla is SlaState.AT_RISK


def test_widespread_threshold_follows_the_root_value() -> None:
    records = [_crash("a"), _crash("b")]
    assert not CrashDashboard.from_records(records).groups[0].is_widespread

    limits = FakeSystemLimits({SystemLimitKey.CRASH_WIDESPREAD_INSTALLATION_THRESHOLD.value: "2"})
    lowered = CrashDashboard.from_records(
        records, thresholds=ConsoleThresholds.from_limits(limits, TENANT)
    )
    assert lowered.groups[0].is_widespread


def test_dashboard_top_limit_follows_the_root_value() -> None:
    records = [
        CrashRecord(
            fingerprint=f"fp{index}",
            exception_type="ValueError",
            app_version="1.0.0",
            anonymous_tenant_ref=f"t{index}",
            occurred_at=NOW,
        )
        for index in range(12)
    ]
    assert len(CrashDashboard.from_records(records).top()) == 10

    limits = FakeSystemLimits({SystemLimitKey.CRASH_DASHBOARD_TOP_LIMIT.value: "3"})
    trimmed = CrashDashboard.from_records(
        records, thresholds=ConsoleThresholds.from_limits(limits, TENANT)
    )
    assert len(trimmed.top()) == 3
    # AÇIQ ARQUMENT ROOT-u ƏVƏZ EDİR — konsol öz sütun sayını seçə bilməlidir.
    assert len(trimmed.top(7)) == 7


# --------------------------------------------------------------------------- #
# 5. Ödəniş xatırlatmaları
# --------------------------------------------------------------------------- #


class _ReminderLog:
    def __init__(self) -> None:
        self.sent: set[str] = set()

    def was_sent(self, stage_key: str) -> bool:
        return stage_key in self.sent

    def mark_sent(self, stage_key: str, *, sent_at: datetime) -> None:
        self.sent.add(stage_key)


class _ReminderSender:
    def __init__(self) -> None:
        self.messages: list[ReminderMessage] = []

    def send(self, message: ReminderMessage) -> None:
        self.messages.append(message)


def _billing(days_left: int) -> TenantBilling:
    return TenantBilling(
        tenant_id=str(TENANT),
        tenant_name="Bellona",
        contact_email="mehsul@bellona.az",
        expires_on=NOW.date() + timedelta(days=days_left),
    )


def test_reminder_schedule_follows_the_root_value() -> None:
    """T-5 defolt cədvəldə YOXDUR; Root onu əlavə edəndə xatırlatma göndərilir."""
    sender = _ReminderSender()
    default_run = PaymentReminderUseCase(sender=sender, log=_ReminderLog())
    assert default_run.run([_billing(5)], now=NOW).sent_count == 0

    limits = FakeSystemLimits(
        {SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS.value: "-5,-1,2"}
    )
    configured = PaymentReminderUseCase(
        sender=sender, log=_ReminderLog(), offsets=reminder_offsets(limits, TENANT)
    )
    run = configured.run([_billing(5)], now=NOW)
    assert run.sent_count == 1
    assert run.sent[0].offset_days == -5


def test_reminder_module_constant_is_the_documented_fallback() -> None:
    assert REMINDER_OFFSETS == (-7, -3, -1, 1, 7)
    assert build_message(_billing(7), today=NOW.date()) is not None
    assert build_message(_billing(5), today=NOW.date()) is None
    assert build_message(_billing(5), today=NOW.date(), offsets=(-5,)) is not None


# --------------------------------------------------------------------------- #
# 6. Səhifə ölçüləri — hər istehlakçı üçün canlı oxu
# --------------------------------------------------------------------------- #


def _employee(role: SystemRole, *, flags: list[PermissionFlag]) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for flag in flags:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


class _RecordingReader:
    """`AuditLogReader` sahtəsi — YALNIZ verilən `limit`-i qeyd edir."""

    def __init__(self) -> None:
        self.seen: list[int] = []

    def query(self, tenant_id: TenantId, filters: AuditFilter) -> list[Any]:
        self.seen.append(filters.limit)
        return []

    def count(self, tenant_id: TenantId, filters: AuditFilter) -> int:
        return 0

    def distinct_actions(self, tenant_id: TenantId) -> list[str]:
        return []


def test_audit_page_size_follows_the_root_values() -> None:
    reader = _RecordingReader()
    limits = FakeSystemLimits(
        {
            SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE.value: "7",
            SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE.value: "9",
        }
    )
    use_case = AuditQueryUseCase(
        reader=reader,  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    viewer = _employee(
        SystemRole.CEO, flags=[PermissionFlag(code="can_view_audit_logs", category="SISTEM")]
    )

    use_case.search(tenant_id=TENANT, actor=viewer)
    assert reader.seen[-1] == 7, "Defolt səhifə ölçüsü ROOT-dan oxunmur"

    use_case.search(tenant_id=TENANT, actor=viewer, filters=AuditFilter(limit=500))
    assert reader.seen[-1] == 9, "ROOT tavanı tətbiq olunmur"


class _Catalog:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def list_available(self, tenant_id: TenantId, *, limit: int = 60) -> list[Any]:
        self.seen.append(limit)
        return []


def test_backup_history_page_size_follows_the_root_value() -> None:
    catalog = _Catalog()
    limits = FakeSystemLimits({SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE.value: "12"})
    use_case = BackupAccessUseCase(
        catalog=catalog,  # type: ignore[arg-type]
        operations=object(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    admin = _employee(
        SystemRole.ROOT, flags=[PermissionFlag(code="can_manage_backups", category="SISTEM")]
    )
    use_case.restore_points(tenant_id=TENANT, actor=admin)
    assert catalog.seen == [12]


class _Tickets:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def list_threads(self, tenant_id: TenantId, *, limit: int = 20, **_: Any) -> list[Any]:
        self.seen.append(limit)
        return []


def test_support_thread_page_size_follows_the_root_value() -> None:
    tickets = _Tickets()
    limits = FakeSystemLimits({SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE.value: "4"})
    use_case = SupportChatUseCase(
        tickets=tickets,  # type: ignore[arg-type]
        toggles=FakeFeatureToggles(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    actor = _employee(
        SystemRole.CEO, flags=[PermissionFlag(code="can_contact_support", category="SISTEM")]
    )
    use_case.threads(tenant_id=TENANT, actor=actor)
    assert tickets.seen == [4]


class _Conflicts:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def list_open(self, tenant_id: TenantId, *, limit: int = 100) -> list[ConflictItem]:
        self.seen.append(limit)
        return []


def test_sync_conflict_page_size_follows_the_root_value() -> None:
    repository = _Conflicts()
    limits = FakeSystemLimits({SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE.value: "6"})
    use_case = SyncConflictUseCase(
        repository=repository,  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    # SEC-018-dən sonra oxu yolu da AYRICA `can_resolve_sync_conflicts`
    # tələb edir — hesabat flag-i artıq kifayət etmir.
    hr = _employee(
        SystemRole.HR_ADMIN,
        flags=[PermissionFlag(code="can_resolve_sync_conflicts", category="ERP_INFRA")],
    )
    use_case.inbox(tenant_id=TENANT, actor=hr)
    assert repository.seen == [6]


class _Queue:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def list_queue(
        self, tenant_id: TenantId, *, server_id: object | None = None, limit: int = 200
    ) -> list[Any]:
        self.seen.append(limit)
        return []

    def get(self, transaction_id: SalesTransactionId) -> None:
        return None

    def queue_size(self, tenant_id: TenantId) -> int:
        return 0

    def assign(self, transaction_id: SalesTransactionId, **kwargs: Any) -> None: ...

    def confirm(self, transaction_id: SalesTransactionId, **kwargs: Any) -> None: ...


def test_sales_review_queue_page_size_follows_the_root_value() -> None:
    repository = _Queue()
    limits = FakeSystemLimits({SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE.value: "25"})
    use_case = SalesReviewQueueUseCase(
        repository=repository,  # type: ignore[arg-type]
        points=None,
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    actor = _employee(
        SystemRole.CEO,
        flags=[PermissionFlag(code="can_manage_sales_points", category="SATIS_MUKAFAT")],
    )
    use_case.queue(tenant_id=TENANT, actor=actor)
    assert repository.seen == [25]

    # AÇIQ ARQUMENT ROOT-u ƏVƏZ EDİR (ekranın "daha çox göstər" vəziyyəti).
    use_case.queue(tenant_id=TENANT, actor=actor, limit=3)
    assert repository.seen[-1] == 3


# --------------------------------------------------------------------------- #
# 7. İlk quraşdırma sihirbazının admin tövsiyəsi
# --------------------------------------------------------------------------- #


class _Employees:
    def __init__(self, count: int) -> None:
        self._count = count

    def count_active_with_flag(self, tenant_id: TenantId, flag: str) -> int:
        return self._count

    def count_active_ranked_at_or_above(self, tenant_id: TenantId, priority: object) -> int:
        """Sihirbaz artıq PİLLƏ ilə sayır (SETUP-3) — sahtə eyni dəyəri verir."""
        return self._count


def test_recommended_admin_count_follows_the_root_value() -> None:
    """İki admin defoltda kifayətdir; Root üç tələb edəndə xəbərdarlıq qayıdır."""
    limits = FakeSystemLimits()
    use_case = FirstRunSetupUseCase(
        employees=_Employees(2),  # type: ignore[arg-type]
        positions=object(),  # type: ignore[arg-type]
        stores=object(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    assert use_case._warning_for(TENANT) is None

    limits.set(SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT, "3")
    assert use_case._warning_for(TENANT) is not None


# --------------------------------------------------------------------------- #
# 8. Birinci dalğanın açıq buraxdığı halqa — satış xalı parametrləri
# --------------------------------------------------------------------------- #


class _PointsRepo:
    def __init__(self) -> None:
        self.saved: list[Any] = []
        self.entries: list[Any] = []

    def save(self, entry: Any) -> None:
        self.saved.append(entry)

    def list_for_employee(self, employee_id: EmployeeId, *, period: Any) -> list[Any]:
        return [entry for entry in self.entries if entry.employee_id == employee_id]

    def get(self, entry_id: Any) -> None:
        return None


class _Rewards:
    def list_redemptions(self, tenant_id: TenantId, *, pending_only: bool = False) -> list[Any]:
        return []

    def list_rewards(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        return []


def _points_use_case(limits: FakeSystemLimits | None) -> tuple[SalesPointsUseCase, _PointsRepo]:
    repo = _PointsRepo()
    use_case = SalesPointsUseCase(
        points=repo,  # type: ignore[arg-type]
        rewards=_Rewards(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        notifier=RecordingNotifier(),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    return use_case, repo


def test_points_rate_now_actually_reaches_the_award_path() -> None:
    """BİRİNCİ DALĞANIN QÜSURU: açar var idi, use case onu OXUMURDU.

    100 AZN = 1 xal defoltunda 500 AZN-lik satış 5 xal verir. Root kursu 50-yə
    endirəndə eyni satış 10 xal verməlidir — əvvəl 5 qalırdı.
    """
    use_case, _repo = _points_use_case(None)
    entry = use_case.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId("1C-001"),
        gross_amount=Decimal("500.00"),
        confidence=MatchConfidence.EXACT_MATCH,
    )
    assert entry is not None
    assert entry.points == 5

    limits = FakeSystemLimits({SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT.value: "50"})
    configured, _ = _points_use_case(limits)
    faster = configured.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId("1C-002"),
        gross_amount=Decimal("500.00"),
        confidence=MatchConfidence.EXACT_MATCH,
    )
    assert faster is not None
    assert faster.points == 10


def test_points_dispute_window_now_actually_reaches_the_ledger_row() -> None:
    """Etiraz pəncərəsi sətrin ÖZÜNƏ yazılır — sonrakı dəyişiklik retroaktiv deyil."""
    limits = FakeSystemLimits({SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS.value: "12"})
    use_case, _ = _points_use_case(limits)
    entry = use_case.award_for_sale(
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        transaction_id=SalesTransactionId("1C-003"),
        gross_amount=Decimal("300.00"),
        confidence=MatchConfidence.EXACT_MATCH,
    )
    assert entry is not None
    assert entry.dispute_window_hours == 12


def test_points_reset_notice_days_now_actually_reaches_the_scheduler() -> None:
    """Defolt 14 gün; Root 30 gün seçəndə bildiriş DAHA ERKƏN başlayır.

    5 İyun 1 İyul sıfırlanmasına 26 gün qalır — 14 günlük pəncərədə hələ
    bildiriş vaxtı DEYİL, 30 günlükdə isə artıq vaxtıdır.
    """
    early = datetime(2026, 6, 5, 9, 0, tzinfo=UTC)
    limits = FakeSystemLimits()
    employee = EmployeeId(uuid.uuid4())
    repo = _PointsRepo()
    repo.entries = [
        PointsEntry(
            entry_id=PointsEntryId(uuid.uuid4()),
            tenant_id=TENANT,
            employee_id=employee,
            store_id=STORE,
            points=9,
            awarded_at=early,
        )
    ]
    use_case = SalesPointsUseCase(
        points=repo,  # type: ignore[arg-type]
        rewards=_Rewards(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(early),  # type: ignore[arg-type]
        notifier=RecordingNotifier(),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )

    narrow = use_case.send_reset_notices(tenant_id=TENANT, employee_ids=[employee])
    assert narrow.notified_count == 0

    limits.set(SystemLimitKey.SALES_POINTS_RESET_NOTICE_DAYS, "30")
    widened = use_case.send_reset_notices(tenant_id=TENANT, employee_ids=[employee])
    assert widened.notified_count == 1


# --------------------------------------------------------------------------- #
# 9. Növbə dəyişmə pəncərəsi və elan siyahısı
# --------------------------------------------------------------------------- #


def test_shift_swap_lead_window_follows_the_root_value() -> None:
    """Defolt 90 gün; Root 30 gün qoyanda 60 günlük sorğu artıq RƏDD olunur."""
    limits = FakeSystemLimits()
    use_case = ShiftSwapUseCase(
        swaps=object(),  # type: ignore[arg-type]
        planning=object(),  # type: ignore[arg-type]
        toggles=FakeFeatureToggles(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        notifier=RecordingNotifier(),  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    seller = _employee(SystemRole.SELLER, flags=[])

    with pytest.raises(ShiftRequestError, match="90 gün"):
        use_case.submit(
            tenant_id=TENANT,
            employee=seller,
            target_date=NOW.date() + timedelta(days=120),
            reason="Ailə vəziyyəti",
        )

    limits.set(SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS, "30")
    with pytest.raises(ShiftRequestError, match="30 gün"):
        use_case.submit(
            tenant_id=TENANT,
            employee=seller,
            target_date=NOW.date() + timedelta(days=60),
            reason="Ailə vəziyyəti",
        )


class _Announcements:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def list_recent(self, tenant_id: TenantId, *, limit: int = 50) -> list[Any]:
        self.seen.append(limit)
        return []


def test_announcement_list_page_size_follows_the_root_value() -> None:
    repository = _Announcements()
    limits = FakeSystemLimits({SystemLimitKey.ANNOUNCEMENT_LIST_PAGE_SIZE.value: "8"})
    use_case = AnnouncementUseCase(
        announcements=repository,  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    admin = _employee(
        SystemRole.HR_ADMIN,
        flags=[PermissionFlag(code="can_broadcast_announcements", category="ELAN")],
    )
    use_case.list_recent(tenant_id=TENANT, actor=admin)
    assert repository.seen == [8]

    use_case.list_recent(tenant_id=TENANT, actor=admin, limit=2)
    assert repository.seen[-1] == 2


def test_module_constants_are_sourced_from_the_defaults_not_a_second_literal() -> None:
    """Sabit ədəd İKİ yerdə yaşasaydı, biri dəyişəndə digəri sükutla köhnələrdi."""
    from src.application.use_cases.audit_query import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
    from src.application.use_cases.backup_access import DEFAULT_HISTORY_LIMIT
    from src.application.use_cases.shift_scheduling import MAX_SWAP_LEAD_DAYS
    from src.application.use_cases.support_chat import DEFAULT_THREAD_PAGE_SIZE
    from src.application.use_cases.sync_conflicts import DEFAULT_INBOX_PAGE_SIZE

    assert fallback_int(SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE) == MAX_PAGE_SIZE
    assert fallback_int(SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE) == DEFAULT_PAGE_SIZE
    assert fallback_int(SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE) == DEFAULT_HISTORY_LIMIT
    assert fallback_int(SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE) == DEFAULT_THREAD_PAGE_SIZE
    assert fallback_int(SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE) == DEFAULT_INBOX_PAGE_SIZE
    assert fallback_int(SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS) == MAX_SWAP_LEAD_DAYS
