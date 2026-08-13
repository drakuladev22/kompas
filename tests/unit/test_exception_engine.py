"""Vahid İstisna Motorunun (#9, Faza 3) qapıları.

BAZA LAZIM DEYİL: bütün portlar sahtə obyektlərlə əvəz olunur.

──────────────────────────────────────────────────────────────────────────────
NƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
1. REYESTR — qeydiyyat, ikiqat qeydiyyat, boş reyestr, kod normallaşdırması.
   Reyestr motorun GENİŞLƏNMƏ NÖQTƏSİDİR: sükutla üstündən yazılan qayda
   aşkarlamanın yarısını görünməz şəkildə söndürərdi.
2. TƏCRİD — bir qaydanın çökməsi digərlərini DAYANDIRMIR. Əks halda yeni
   qoşulan tək bir qüsurlu qayda bütün gecəlik aşkarlamanı söndürərdi.
3. SOFT-CODED — tavan, səhifə ölçüsü, bildiriş həddi və izah uzunluğu
   `system_limits`-dən oxunur; motorda hardcode ədəd YOXDUR.
4. STATUS KEÇİDLƏRİ — OPEN → REVIEWED / DISMISSED terminaldır; təkrar keçid
   bloklanır (əks halda "bir dəfə rədd etdim" qərarı sabah təkzib edilərdi).
5. SƏLAHİYYƏT VƏ İZOLYASİYA — `can_view_exceptions` olmadan nə oxu, nə qərar;
   başqa kirayəçinin sətri görünmür.
6. AUDIT — hər yaradılma və hər qərar `audit_logs`-a düşür.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.exception_engine import (
    VIEW_EXCEPTIONS_FLAG,
    ExceptionEngineError,
    ExceptionEngineUseCase,
    ExceptionPermissionError,
)
from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.exception_record import ExceptionRecord
from src.domain.entities.position import Position
from src.domain.exception_rules import (
    DuplicateExceptionRuleError,
    ExceptionRuleRegistry,
    InvalidRuleSourceError,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import (
    PermissionEffect,
    RolePriority,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.exception_signals import (
    BEHAVIOR_ANOMALY_SOURCE,
    ExceptionFinding,
    ExceptionSeverity,
    ExceptionSource,
    ExceptionStatus,
    RuleEvaluationContext,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ExceptionId,
    StoreId,
    TenantId,
    new_exception_id,
)
from tests.fixtures.fakes import (
    DuplicateDedupeKeyError,
    FakeClock,
    FakeExceptionSources,
    FakeSystemLimits,
    InMemoryExceptions,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
OTHER_TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
WORKER = EmployeeId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


class _StubRule:
    """Motorun test etdiyi YEGANƏ qayda tipi — `ExceptionRule` müqaviləsi.

    Faza 5-in həqiqi qaydası bu imzanı təkrarlayacaq; burada hesablama
    məntiqi QƏSDƏN yoxdur, çünki motor onu tanımır.
    """

    def __init__(
        self,
        *,
        source_code: str = BEHAVIOR_ANOMALY_SOURCE,
        name_az: str = "Sınaq qaydası",
        findings: list[ExceptionFinding] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._source_code = source_code
        self._name_az = name_az
        self._findings = findings or []
        self._error = error
        self.calls: list[RuleEvaluationContext] = []

    @property
    def source_code(self) -> str:
        return self._source_code

    @property
    def name_az(self) -> str:
        return self._name_az

    def evaluate(self, context: RuleEvaluationContext) -> list[ExceptionFinding]:
        self.calls.append(context)
        if self._error is not None:
            raise self._error
        return list(self._findings)


def _finding(
    *,
    detail: str = "Check-in vaxtı baz xəttindən 42 dəqiqə kənarlaşıb",
    dedupe_key: str | None = "BEHAVIOR_ANOMALY:2026-08-12",
    severity: ExceptionSeverity | None = None,
    store_id: StoreId = STORE,
    employee_id: EmployeeId = WORKER,
) -> ExceptionFinding:
    return ExceptionFinding(
        employee_id=employee_id,
        store_id=store_id,
        detail=detail,
        context={"baz_xetti": 510, "faktiki": 552, "kenarlasma": 42},
        severity=severity,
        dedupe_key=dedupe_key,
    )


def _source(
    *,
    code: str = BEHAVIOR_ANOMALY_SOURCE,
    default_severity: ExceptionSeverity = ExceptionSeverity.MEDIUM,
    is_active: bool = True,
) -> ExceptionSource:
    return ExceptionSource(
        code=code,
        name_az="Davranış anomaliyası",
        description_az="İşçinin check-in vaxtı baz xəttindən kənarlaşdıqda yaranır.",
        default_severity=default_severity,
        is_active=is_active,
    )


def _employee(
    *,
    flags: tuple[str, ...] = (VIEW_EXCEPTIONS_FLAG,),
    tenant_id: TenantId = TENANT,
) -> Employee:
    position = Position(
        position_id=uuid.uuid4(),  # type: ignore[arg-type]
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=tenant_id,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name="Ayan",
        last_name="Məmmədova",
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


def _engine(
    *,
    rules: tuple[Any, ...] = (),
    sources: list[ExceptionSource] | None = None,
    limits: dict[str, str] | None = None,
) -> tuple[ExceptionEngineUseCase, InMemoryExceptions, RecordingAudit, RecordingNotifier]:
    repository = InMemoryExceptions()
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    engine = ExceptionEngineUseCase(
        exceptions=repository,
        sources=FakeExceptionSources(sources if sources is not None else [_source()]),
        registry=ExceptionRuleRegistry(rules),
        limits=FakeSystemLimits(limits),
        audit=audit,
        clock=FakeClock(NOW),
        notifier=notifier,
    )
    return engine, repository, audit, notifier


def _stored_record(
    *,
    tenant_id: TenantId = TENANT,
    status: ExceptionStatus = ExceptionStatus.OPEN,
    store_id: StoreId = STORE,
    exception_id: ExceptionId | None = None,
) -> ExceptionRecord:
    reviewer = EmployeeId(uuid.uuid4()) if not status.is_open else None
    return ExceptionRecord(
        exception_id=exception_id or new_exception_id(),
        tenant_id=tenant_id,
        source=BEHAVIOR_ANOMALY_SOURCE,
        employee_id=WORKER,
        store_id=store_id,
        detail="Check-in vaxtı baz xəttindən kənarlaşıb",
        created_at=NOW,
        status=status,
        reviewed_by=reviewer,
        reviewed_at=NOW if reviewer is not None else None,
        dedupe_key=f"K-{uuid.uuid4().hex[:8]}",
        emit_created_event=False,
    )


# --------------------------------------------------------------------------- #
# 1. REYESTR
# --------------------------------------------------------------------------- #


def test_rule_registers_and_keeps_insertion_order() -> None:
    """Qeydiyyat sırası ICRA sırasıdır — təsadüfi sıra audit izini pozardı."""
    registry = ExceptionRuleRegistry()
    registry.register(_StubRule(source_code="BEHAVIOR_ANOMALY"))
    registry.register(_StubRule(source_code="POS_OVERRIDE"))

    assert registry.source_codes() == ("BEHAVIOR_ANOMALY", "POS_OVERRIDE")
    assert len(registry) == 2
    assert "behavior_anomaly" in registry  # kod normallaşdırılır
    assert not registry.is_empty


def test_duplicate_registration_is_loud_not_silent() -> None:
    """İkinci qayda birincisini SÜKUTLA əvəz etsəydi, yarısı yox olardı."""
    registry = ExceptionRuleRegistry((_StubRule(source_code="BEHAVIOR_ANOMALY"),))

    with pytest.raises(DuplicateExceptionRuleError, match="BEHAVIOR_ANOMALY"):
        registry.register(_StubRule(source_code="behavior_anomaly"))

    assert len(registry) == 1


def test_invalid_source_code_fails_at_registration_not_at_write() -> None:
    """Yararsız kod `FOREIGN KEY` pozuntusu kimi gecə yox, indi görünür."""
    with pytest.raises(InvalidRuleSourceError):
        ExceptionRuleRegistry().register(_StubRule(source_code="XY"))


def test_lookup_with_garbage_code_returns_none_instead_of_raising() -> None:
    """Axtarış istisna atsaydı, ekranın süzgəci sətir səhvinə görə çökərdi."""
    registry = ExceptionRuleRegistry((_StubRule(),))

    assert registry.get("  behavior_anomaly ") is not None
    assert registry.get("") is None
    assert 42 not in registry


def test_empty_registry_runs_cleanly() -> None:
    """Boş reyestr NORMAL vəziyyətdir — Faza 5-dən əvvəlki hər buraxılış belədir."""
    engine, repository, audit, notifier = _engine()

    report = engine.run(tenant_id=TENANT)

    assert report.evaluated_rules == 0
    assert report.created_total == 0
    assert report.failed_rules == ()
    assert repository.items == {}
    assert audit.entries == []
    assert notifier.messages == []


# --------------------------------------------------------------------------- #
# 2. İCRA VƏ TƏCRİD
# --------------------------------------------------------------------------- #


def test_run_writes_finding_with_audit_entry() -> None:
    rule = _StubRule(findings=[_finding()])
    engine, repository, audit, _ = _engine(rules=(rule,))

    report = engine.run(tenant_id=TENANT)

    assert report.created_total == 1
    (record,) = repository.items.values()
    assert record.source == BEHAVIOR_ANOMALY_SOURCE
    assert record.status is ExceptionStatus.OPEN
    assert record.created_at == NOW
    assert record.context["kenarlasma"] == 42
    # Audit MƏCBURİDİR: aktor `None`-dur, çünki istisnanı qayda yaradır.
    assert audit.actions() == ["EXCEPTION_RAISED"]
    assert audit.entries[0]["actor_id"] is None
    assert audit.entries[0]["entity_type"] == "exceptions"


def test_rule_receives_clock_time_and_limit_snapshot() -> None:
    """Qayda `datetime.now()` çağırmır və həddini `system_limits`-dən alır."""
    rule = _StubRule()
    engine, *_ = _engine(rules=(rule,), limits={"BEHAVIOR_ANOMALY_SIGMA": "3"})

    engine.run(tenant_id=TENANT)

    (context,) = rule.calls
    assert context.as_of == NOW
    assert context.tenant_id == TENANT
    assert context.limit_int("BEHAVIOR_ANOMALY_SIGMA", 2) == 3
    assert context.limit_int("YOXDUR", 7) == 7


def test_one_failing_rule_does_not_stop_the_others() -> None:
    """Qüsurlu qayda BÜTÜN gecəlik aşkarlamanı söndürə bilməz."""
    broken = _StubRule(source_code="POS_OVERRIDE", error=RuntimeError("bölmə sıfıra"))
    healthy = _StubRule(findings=[_finding()])
    engine, repository, audit, _ = _engine(
        rules=(broken, healthy),
        sources=[_source(), _source(code="POS_OVERRIDE")],
    )

    report = engine.run(tenant_id=TENANT)

    assert report.failed_rules == ("POS_OVERRIDE",)
    assert report.created_total == 1
    assert len(repository.items) == 1
    assert audit.actions() == ["EXCEPTION_RAISED"]


def test_audit_failure_is_not_swallowed() -> None:
    """Audit istisna udmur (CLAUDE.md §5) — qayda təcridi buna şamil DEYİL."""
    engine, _, audit, _ = _engine(rules=(_StubRule(findings=[_finding()]),))
    audit.failure = RuntimeError("audit_logs əlçatmazdır")

    with pytest.raises(RuntimeError, match="audit_logs"):
        engine.run(tenant_id=TENANT)


def test_repository_failure_is_not_swallowed() -> None:
    """Yazı nasazlığı qayda qüsuru deyil — tranzaksiya tam geri qayıtmalıdır."""
    engine, repository, _, _ = _engine(rules=(_StubRule(findings=[_finding()]),))
    repository.save_failure = RuntimeError("bağlantı qırıldı")

    with pytest.raises(RuntimeError, match="bağlantı"):
        engine.run(tenant_id=TENANT)


def test_unknown_source_is_reported_not_written() -> None:
    """Kataloqda olmayan mənbə FAIL-CLOSED: sətir yazılmır, icra davam edir."""
    engine, repository, _, _ = _engine(
        rules=(_StubRule(source_code="NAMELUM", findings=[_finding()]),),
    )

    report = engine.run(tenant_id=TENANT)

    assert report.failed_rules == ("NAMELUM",)
    assert "kataloqda yoxdur" in (report.outcomes[0].error_az or "")
    assert repository.items == {}


def test_deactivated_source_creates_nothing_but_keeps_existing_rows() -> None:
    """Söndürmə RETROAKTİV DEYİL: yeni sətir yaranmır, köhnə sətir qalır."""
    engine, repository, _, _ = _engine(
        rules=(_StubRule(findings=[_finding()]),),
        sources=[_source(is_active=False)],
    )
    existing = _stored_record()
    repository.items[existing.id] = existing

    report = engine.run(tenant_id=TENANT)

    assert report.outcomes[0].skipped_inactive is True
    assert report.created_total == 0
    assert existing.id in repository.items


# --------------------------------------------------------------------------- #
# 3. TƏKRAR QAPAĞI VƏ SOFT-CODED HƏDDLƏR
# --------------------------------------------------------------------------- #


def test_same_finding_is_not_created_twice() -> None:
    """Gecəlik icra eyni tapıntını hər dəfə təzələsəydi, qərar itərdi."""
    rule = _StubRule(findings=[_finding()])
    engine, repository, audit, _ = _engine(rules=(rule,))

    first = engine.run(tenant_id=TENANT)
    second = engine.run(tenant_id=TENANT)

    assert first.created_total == 1
    assert second.created_total == 0
    assert second.duplicate_total == 1
    assert len(repository.items) == 1
    assert audit.actions() == ["EXCEPTION_RAISED"]


def test_dismissed_finding_is_not_reopened_by_the_next_run() -> None:
    """Rədd edilmiş tapıntı sabah yenidən açılmır (statusdan asılı olmayan açar)."""
    rule = _StubRule(findings=[_finding()])
    engine, repository, _, _ = _engine(rules=(rule,))
    engine.run(tenant_id=TENANT)
    (record,) = repository.items.values()
    actor = _employee()
    engine.dismiss(
        tenant_id=TENANT,
        actor=actor,
        exception_id=record.id,
        note="Avtobus gecikməsi sənədlə təsdiqləndi",
    )

    report = engine.run(tenant_id=TENANT)

    assert report.created_total == 0
    assert len(repository.items) == 1
    assert record.status is ExceptionStatus.DISMISSED


def test_findings_without_dedupe_key_hit_the_repository_guard() -> None:
    """Açarsız tapıntı hər icrada yeni sətir yaradır — sənədləşdirilmiş davranış."""
    rule = _StubRule(findings=[_finding(dedupe_key=None)])
    engine, repository, _, _ = _engine(rules=(rule,))

    engine.run(tenant_id=TENANT)
    engine.run(tenant_id=TENANT)

    assert len(repository.items) == 2


def test_duplicate_dedupe_key_is_blocked_by_the_storage_layer_too() -> None:
    """İkinci qat: kod qapağı yan keçilsə belə unikal indeks saxlayır."""
    repository = InMemoryExceptions()
    first = _stored_record()
    first.dedupe_key = "TEKRAR"
    repository.save(first)
    second = _stored_record()
    second.dedupe_key = "TEKRAR"

    with pytest.raises(DuplicateDedupeKeyError):
        repository.save(second)


def test_per_rule_ceiling_comes_from_system_limits() -> None:
    """Tavan ROOT-dandır: `exceptions` sətirləri SİLİNMİR, daşqın bərpasızdır."""
    findings = [_finding(dedupe_key=f"K{i}") for i in range(5)]
    engine, repository, _, _ = _engine(
        rules=(_StubRule(findings=findings),),
        limits={SystemLimitKey.EXCEPTION_MAX_FINDINGS_PER_RULE.value: "2"},
    )

    report = engine.run(tenant_id=TENANT)

    assert report.created_total == 2
    assert report.outcomes[0].dropped_over_limit == 3
    assert len(repository.items) == 2


def test_invalid_limit_value_falls_back_to_default() -> None:
    """Root-un yazı səhvi gecəlik aşkarlamanı çökdürməməlidir."""
    engine, _, _, _ = _engine(
        rules=(_StubRule(findings=[_finding()]),),
        limits={SystemLimitKey.EXCEPTION_MAX_FINDINGS_PER_RULE.value: "çox"},
    )

    report = engine.run(tenant_id=TENANT)

    assert report.created_total == 1
    assert int(DEFAULT_LIMITS[SystemLimitKey.EXCEPTION_MAX_FINDINGS_PER_RULE]) > 1


def test_severity_defaults_to_the_catalog_value_not_to_code() -> None:
    """Ciddiyyət kodda sabit deyil — mənbə kataloqundan gəlir (ROOT-dan idarə)."""
    engine, repository, _, _ = _engine(
        rules=(_StubRule(findings=[_finding(severity=None)]),),
        sources=[_source(default_severity=ExceptionSeverity.CRITICAL)],
    )

    engine.run(tenant_id=TENANT)

    (record,) = repository.items.values()
    assert record.severity is ExceptionSeverity.CRITICAL


def test_rule_severity_overrides_the_catalog_default() -> None:
    engine, repository, _, _ = _engine(
        rules=(_StubRule(findings=[_finding(severity=ExceptionSeverity.LOW)]),),
        sources=[_source(default_severity=ExceptionSeverity.CRITICAL)],
    )

    engine.run(tenant_id=TENANT)

    (record,) = repository.items.values()
    assert record.severity is ExceptionSeverity.LOW


def test_notification_threshold_is_configurable() -> None:
    """Defolt HIGH: MEDIUM-da hər anomaliya bildiriş göndərər və kanal boğulardı."""
    quiet_engine, _, _, quiet_notifier = _engine(
        rules=(_StubRule(findings=[_finding(severity=ExceptionSeverity.MEDIUM)]),)
    )
    loud_engine, _, _, loud_notifier = _engine(
        rules=(_StubRule(findings=[_finding(severity=ExceptionSeverity.MEDIUM)]),),
        limits={SystemLimitKey.EXCEPTION_NOTIFY_MIN_SEVERITY.value: "LOW"},
    )

    quiet_engine.run(tenant_id=TENANT)
    loud_engine.run(tenant_id=TENANT)

    assert quiet_notifier.messages == []
    assert loud_notifier.categories() == ["EXCEPTION_RAISED"]


def test_critical_severity_is_flagged_critical_for_the_email_fallback() -> None:
    engine, _, _, notifier = _engine(
        rules=(_StubRule(findings=[_finding(severity=ExceptionSeverity.CRITICAL)]),)
    )

    engine.run(tenant_id=TENANT)

    assert notifier.messages[0]["is_critical"] is True


def test_severity_ranking_is_not_alphabetical() -> None:
    """`str` müqayisəsi "CRITICAL" < "LOW" verərdi — hədd tərsinə işləyərdi."""
    assert ExceptionSeverity.CRITICAL.at_least(ExceptionSeverity.HIGH)
    assert not ExceptionSeverity.LOW.at_least(ExceptionSeverity.MEDIUM)
    assert ExceptionSeverity.parse("hIgH", fallback=ExceptionSeverity.LOW) is (
        ExceptionSeverity.HIGH
    )
    assert ExceptionSeverity.parse("YOXDUR", fallback=ExceptionSeverity.LOW) is (
        ExceptionSeverity.LOW
    )


# --------------------------------------------------------------------------- #
# 4. OXU — SƏLAHİYYƏT, SCOPE, SƏHİFƏ ÖLÇÜSÜ
# --------------------------------------------------------------------------- #


def test_reading_requires_the_flag_and_raises_instead_of_returning_empty() -> None:
    """Sükutla boş siyahı qaytarmaq istifadəçini "səhv oldu?" sualında qoyardı."""
    engine, repository, _, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record

    with pytest.raises(ExceptionPermissionError, match=VIEW_EXCEPTIONS_FLAG):
        engine.list_open(tenant_id=TENANT, actor=_employee(flags=()))


def test_open_list_carries_the_source_name_from_the_catalog() -> None:
    """Badge mətni BAZADAN gəlir — ekran ikinci ad məkanı qurmur."""
    engine, repository, _, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record

    (view,) = engine.list_open(tenant_id=TENANT, actor=_employee())

    assert view.source_code == BEHAVIOR_ANOMALY_SOURCE
    assert view.source_name_az == "Davranış anomaliyası"
    assert view.status == "OPEN"


def test_closed_rows_do_not_appear_in_the_open_queue() -> None:
    engine, repository, _, _ = _engine()
    for status in (ExceptionStatus.OPEN, ExceptionStatus.REVIEWED, ExceptionStatus.DISMISSED):
        record = _stored_record(status=status)
        repository.items[record.id] = record

    views = engine.list_open(tenant_id=TENANT, actor=_employee())

    assert [view.status for view in views] == ["OPEN"]


def test_store_scope_filters_and_empty_scope_shows_nothing() -> None:
    """FAIL-SAFE: təyinatı olmayan istifadəçi "hər şeyi" DEYİL, heç nə görür."""
    engine, repository, _, _ = _engine()
    mine = _stored_record(store_id=STORE)
    theirs = _stored_record(store_id=OTHER_STORE)
    repository.items.update({mine.id: mine, theirs.id: theirs})
    actor = _employee()

    scoped = engine.list_open(tenant_id=TENANT, actor=actor, store_ids=[STORE])
    empty = engine.list_open(tenant_id=TENANT, actor=actor, store_ids=[])

    assert [view.exception_id for view in scoped] == [mine.id]
    assert empty == []


def test_page_size_comes_from_system_limits() -> None:
    engine, repository, _, _ = _engine(limits={SystemLimitKey.EXCEPTION_PAGE_SIZE.value: "2"})
    for _ in range(4):
        record = _stored_record()
        repository.items[record.id] = record

    assert len(engine.list_open(tenant_id=TENANT, actor=_employee())) == 2


def test_detail_view_requires_the_flag_and_the_tenant() -> None:
    engine, repository, _, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record

    view = engine.get_view(tenant_id=TENANT, actor=_employee(), exception_id=record.id)

    assert view.detail == record.detail
    with pytest.raises(ExceptionPermissionError):
        engine.get_view(tenant_id=TENANT, actor=_employee(flags=()), exception_id=record.id)


# --------------------------------------------------------------------------- #
# 5. TENANT İZOLYASİYASI
# --------------------------------------------------------------------------- #


def test_record_of_another_tenant_is_invisible() -> None:
    """RLS + repo şərtindən sonra ÜÇÜNCÜ qat — sahtə/plugin repo-lara qarşı."""
    engine, repository, _, _ = _engine()
    foreign = _stored_record(tenant_id=OTHER_TENANT)
    repository.items[foreign.id] = foreign

    assert engine.list_open(tenant_id=TENANT, actor=_employee()) == []
    with pytest.raises(ExceptionEngineError, match="tapılmadı"):
        engine.mark_reviewed(tenant_id=TENANT, actor=_employee(), exception_id=foreign.id)


def test_actor_from_another_tenant_is_rejected() -> None:
    engine, repository, _, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record

    with pytest.raises(ExceptionPermissionError, match="kirayəçiyə aid deyil"):
        engine.list_open(tenant_id=TENANT, actor=_employee(tenant_id=OTHER_TENANT))


def test_missing_record_and_foreign_record_share_one_message() -> None:
    """Fərqli mətn "bu ID var, sadəcə sizin deyil" məlumatını sızdırardı."""
    engine, _, _, _ = _engine()

    with pytest.raises(ExceptionEngineError) as missing:
        engine.get_view(tenant_id=TENANT, actor=_employee(), exception_id=new_exception_id())

    assert missing.value.user_message == "Bu istisna mövcud deyil."


# --------------------------------------------------------------------------- #
# 6. STATUS KEÇİDLƏRİ
# --------------------------------------------------------------------------- #


def test_open_to_reviewed_is_audited() -> None:
    engine, repository, audit, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record
    actor = _employee()

    updated = engine.mark_reviewed(
        tenant_id=TENANT,
        actor=actor,
        exception_id=record.id,
        note="İşçi ilə söhbət aparıldı, səbəb aydınlaşdı",
    )

    assert updated.status is ExceptionStatus.REVIEWED
    assert updated.reviewed_by == actor.id
    assert updated.reviewed_at == NOW
    assert audit.actions() == ["EXCEPTION_REVIEWED"]
    assert audit.entries[0]["before_state"] == {"status": "OPEN"}
    assert audit.entries[0]["actor_id"] == actor.id


def test_open_to_dismissed_is_audited() -> None:
    engine, repository, audit, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record

    updated = engine.dismiss(
        tenant_id=TENANT,
        actor=_employee(),
        exception_id=record.id,
        note="Nahar fasiləsi rəhbərliklə razılaşdırılıb",
    )

    assert updated.status is ExceptionStatus.DISMISSED
    assert audit.actions() == ["EXCEPTION_DISMISSED"]


def test_second_transition_is_blocked() -> None:
    """Terminal keçid: bağlanmış istisna yenidən açılmır."""
    engine, repository, _, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record
    actor = _employee()
    engine.mark_reviewed(tenant_id=TENANT, actor=actor, exception_id=record.id)

    with pytest.raises(InvalidStateTransitionError, match="artıq bağlanıb"):
        engine.dismiss(
            tenant_id=TENANT,
            actor=actor,
            exception_id=record.id,
            note="Fikrimi dəyişdim, əslində əsassızdır",
        )


def test_dismiss_requires_a_justification() -> None:
    """Səbəbsiz söndürmə audit baxımından izsiz silmə ilə eynidir."""
    engine, repository, audit, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record

    with pytest.raises(DomainRuleError, match="izah"):
        engine.dismiss(tenant_id=TENANT, actor=_employee(), exception_id=record.id, note="ok")

    assert record.status is ExceptionStatus.OPEN
    assert audit.entries == []


def test_reviewed_accepts_an_empty_note_but_not_a_meaningless_one() -> None:
    engine, repository, _, _ = _engine()
    without_note = _stored_record()
    with_short_note = _stored_record()
    repository.items.update({without_note.id: without_note, with_short_note.id: with_short_note})
    actor = _employee()

    engine.mark_reviewed(tenant_id=TENANT, actor=actor, exception_id=without_note.id)

    assert without_note.status is ExceptionStatus.REVIEWED
    with pytest.raises(DomainRuleError):
        engine.mark_reviewed(
            tenant_id=TENANT, actor=actor, exception_id=with_short_note.id, note="ok"
        )


def test_note_length_threshold_is_configurable() -> None:
    """İzah uzunluğu da ROOT parametridir — motorda sabit ədəd yoxdur."""
    engine, repository, _, _ = _engine(
        limits={SystemLimitKey.EXCEPTION_REVIEW_NOTE_MIN_LENGTH.value: "0"}
    )
    record = _stored_record()
    repository.items[record.id] = record

    engine.dismiss(tenant_id=TENANT, actor=_employee(), exception_id=record.id, note="yox")

    assert record.status is ExceptionStatus.DISMISSED


def test_transition_requires_the_flag() -> None:
    engine, repository, audit, _ = _engine()
    record = _stored_record()
    repository.items[record.id] = record

    with pytest.raises(ExceptionPermissionError):
        engine.mark_reviewed(tenant_id=TENANT, actor=_employee(flags=()), exception_id=record.id)

    assert record.status is ExceptionStatus.OPEN
    assert audit.entries == []


def test_deactivated_source_still_allows_closing_old_findings() -> None:
    """Söndürülmüş mənbənin açıq istisnaları əbədi `OPEN` qalmamalıdır."""
    engine, repository, _, _ = _engine(sources=[_source(is_active=False)])
    record = _stored_record()
    repository.items[record.id] = record

    engine.mark_reviewed(tenant_id=TENANT, actor=_employee(), exception_id=record.id)

    assert record.status is ExceptionStatus.REVIEWED


# --------------------------------------------------------------------------- #
# 7. AQREQAT QAYDALARI
# --------------------------------------------------------------------------- #


def test_new_record_records_event_and_restored_one_does_not() -> None:
    """Repo-dan bərpa hadisə YAYMIR — hər oxu bildiriş doğurardı."""
    created = ExceptionRecord.from_finding(
        _finding(),
        exception_id=new_exception_id(),
        tenant_id=TENANT,
        source=BEHAVIOR_ANOMALY_SOURCE,
        severity=ExceptionSeverity.HIGH,
        created_at=NOW,
    )
    restored = _stored_record()

    assert created.has_pending_events
    assert not restored.has_pending_events
    assert created.collect_events()[0].event_name == "ExceptionRaisedEvent"


def test_engine_drains_events_after_writing() -> None:
    """Aqreqat təkrar işlədilsə hadisələr yığılıb iki dəfə yayılmamalıdır."""
    engine, repository, _, _ = _engine(rules=(_StubRule(findings=[_finding()]),))

    engine.run(tenant_id=TENANT)

    (record,) = repository.items.values()
    assert not record.has_pending_events


def test_decision_records_a_domain_event() -> None:
    record = _stored_record()
    reviewer = EmployeeId(uuid.uuid4())

    record.mark_reviewed(reviewed_by=reviewer, reviewed_at=NOW, note=None)

    (event,) = record.collect_events()
    assert event.event_name == "ExceptionReviewDecidedEvent"
    assert event.actor_id == reviewer


def test_detail_shorter_than_the_db_check_is_rejected() -> None:
    with pytest.raises(DomainRuleError, match="izahı"):
        ExceptionRecord(
            exception_id=new_exception_id(),
            tenant_id=TENANT,
            source=BEHAVIOR_ANOMALY_SOURCE,
            employee_id=WORKER,
            store_id=STORE,
            detail="qısa",
            created_at=NOW,
        )


def test_closed_record_without_a_decider_is_rejected() -> None:
    """`chk_exception_review` güzgüsü — "baxılıb" sözünün sahibi olmalıdır."""
    with pytest.raises(DomainRuleError, match="qərar verəni"):
        ExceptionRecord(
            exception_id=new_exception_id(),
            tenant_id=TENANT,
            source=BEHAVIOR_ANOMALY_SOURCE,
            employee_id=WORKER,
            store_id=STORE,
            detail="Kifayət qədər uzun izah mətni",
            created_at=NOW,
            status=ExceptionStatus.REVIEWED,
        )


def test_naive_datetime_is_rejected_at_the_boundary() -> None:
    with pytest.raises(Exception, match="vaxt zonası"):
        RuleEvaluationContext(tenant_id=TENANT, as_of=datetime(2026, 8, 12, 3, 0))  # noqa: DTZ001


def test_age_hours_uses_the_injected_clock() -> None:
    record = _stored_record()

    assert record.age_hours(now=NOW) == 0.0
    assert record.is_open


# --------------------------------------------------------------------------- #
# 8. GENİŞLƏNMƏ NÖQTƏSİ
# --------------------------------------------------------------------------- #


def test_new_source_needs_no_engine_change() -> None:
    """FAZA 5-İN YOLU: qaydanı qeydiyyatdan keçir — motor toxunulmaz qalır."""
    engine, repository, _, _ = _engine(
        sources=[_source(), _source(code="GELECEK_MENBE", default_severity=ExceptionSeverity.LOW)]
    )

    engine.register_rule(
        _StubRule(
            source_code="GELECEK_MENBE",
            name_az="Gələcək mənbə",
            findings=[_finding(dedupe_key="GELECEK-1")],
        )
    )
    report = engine.run(tenant_id=TENANT)

    assert engine.registered_sources == ("GELECEK_MENBE",)
    assert report.created_total == 1
    (record,) = repository.items.values()
    assert record.source == "GELECEK_MENBE"
    assert record.severity is ExceptionSeverity.LOW


def test_registering_the_same_source_twice_through_the_engine_fails() -> None:
    engine, _, _, _ = _engine(rules=(_StubRule(),))

    with pytest.raises(DuplicateExceptionRuleError):
        engine.register_rule(_StubRule())


def test_registry_is_iterable_and_readable_in_logs() -> None:
    """Diaqnostika: "hansı qaydalar bağlıdır?" sualı bir `repr` ilə cavablanır."""
    rule = _StubRule()
    registry = ExceptionRuleRegistry((rule,))

    assert list(registry) == [rule]
    assert BEHAVIOR_ANOMALY_SOURCE in repr(registry)


def test_record_repr_names_the_source_and_status() -> None:
    record = _stored_record()

    assert BEHAVIOR_ANOMALY_SOURCE in repr(record)
    assert "OPEN" in repr(record)


def test_record_rejects_a_source_code_shorter_than_the_catalog_check() -> None:
    """`exception_sources.code` CHECK-inin güzgüsü — FK səhvindən əvvəl tutulur."""
    with pytest.raises(DomainRuleError, match="Mənbə kodu"):
        ExceptionRecord(
            exception_id=new_exception_id(),
            tenant_id=TENANT,
            source="XY",
            employee_id=WORKER,
            store_id=STORE,
            detail="Kifayət qədər uzun izah mətni",
            created_at=NOW,
        )


def test_context_limit_str_falls_back_on_blank_values() -> None:
    """Boş sətir "dəyər var" sayılmır — Root sahəni təmizləsə defolt işləyir."""
    context = RuleEvaluationContext(
        tenant_id=TENANT, as_of=NOW, limits={"BOS": "   ", "DOLU": " HIGH "}
    )

    assert context.limit_str("BOS", "MEDIUM") == "MEDIUM"
    assert context.limit_str("YOXDUR", "MEDIUM") == "MEDIUM"
    assert context.limit_str("DOLU", "MEDIUM") == "HIGH"


def test_context_limit_int_survives_a_typo_in_root_panel() -> None:
    """Root-un yazı səhvi qaydanı çökdürməməlidir — parametr təsirsiz qalır."""
    context = RuleEvaluationContext(tenant_id=TENANT, as_of=NOW, limits={"SIGMA": "iki"})

    assert context.limit_int("SIGMA", 2) == 2


def test_severity_parse_accepts_none() -> None:
    """Kataloq sütunu boş qayıtsa motor çökmür, defolta düşür."""
    assert ExceptionSeverity.parse(None, fallback=ExceptionSeverity.MEDIUM) is (
        ExceptionSeverity.MEDIUM
    )
