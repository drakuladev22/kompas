"""Sahə hesabatları (#26 Mağaza Auditi + #27 İnsident) — kompas1.md Faza 3.

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR — VƏ NİYƏ MƏHZ BU
──────────────────────────────────────────────────────────────────────────────
Bu funksiyanın üç struktur qərarı var və hər üçü SÜKUTLA pozula bilər:

  A. VAHİD NÜVƏ — iki şablon bir use case-dən keçir. Pozulma əlaməti: yeni
     şablon əlavə etmək üçün KOD dəyişikliyi lazım olması. Ona görə burada
     kataloqa YALNIZ sətir əlavə edən (`SUPPLY_CHECK`) test var.
  B. MÖVCUD TAPŞIRIQ MÜHƏRRİKİ — uğursuz bloklayıcı bənd yeni sistem yox,
     `TaskWorkflowUseCase`-i çağırmalıdır. Pozulma əlaməti: tapşırığın
     `TASK_ENGINE` toggle-ından və audit izindən yan keçməsi.
  C. `passed` ÜÇ VƏZİYYƏTLİDİR — `None` (yoxlanılmadı) tapşırıq YARATMIR.
     Pozulma əlaməti: `not passed` yazılması (`None` da uğursuz sayılar).

Sahtələr BURADA, YERLİ təyin olunub (`tests/fixtures/fakes.py`-a əlavə
edilmir) — `test_employee_documents.py`/`test_labor_rules.py` ilə eyni
əsaslandırma: bu fayl paralel işləyən başqa fazaların sahtə dəstindən asılı
olmamalıdır.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.application.use_cases.field_reports import (
    CONDUCT_AUDIT_FLAG,
    REPORT_INCIDENT_FLAG,
    ROUTED_NOTIFICATION_CATEGORY,
    FieldReportDraft,
    FieldReportUseCase,
    UnknownFieldReportTemplateError,
)
from src.application.use_cases.multi_store_benchmark import (
    VIEW_BENCHMARK_FLAG,
    BenchmarkMetric,
    MultiStoreBenchmarkUseCase,
)
from src.application.use_cases.task_workflow import TaskWorkflowUseCase
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee
from src.domain.entities.field_report import FieldReport, FieldReportChecklistItem
from src.domain.entities.position import Position
from src.domain.entities.task import Task
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.field_reports import (
    ChecklistItemDraft,
    FieldReportCategory,
    FieldReportStatus,
    FieldReportTemplate,
    StoreAuditGap,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FieldReportId,
    FieldReportItemId,
    PositionId,
    StoreId,
    TaskId,
    TenantId,
)
from src.domain.value_objects.notifications import (
    TENANT_NOTIFICATION_AUDIENCE,
    hidden_tenant_categories,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
OTHER_STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)

AUDIT_FLAG = PermissionFlag(code=CONDUCT_AUDIT_FLAG, category="HR")
INCIDENT_FLAG = PermissionFlag(code=REPORT_INCIDENT_FLAG, category="HR")
ASSIGN_FLAG = PermissionFlag(code="can_assign_tasks", category="TASK_DASHBOARD")
EXPORT_FLAG = PermissionFlag(code=VIEW_BENCHMARK_FLAG, category="TASK_DASHBOARD")

#: Kataloqun `migrations/037` seed-i ilə EYNİ dəyərləri — sahtə uydurma
#: məlumat qurmur, real sətirlərin surətini işlədir.
AUDIT_TEMPLATE = FieldReportTemplate(
    code="STORE_AUDIT",
    name_az="Mağaza ziyarəti / audit",
    requires_checklist=True,
)
INCIDENT_TEMPLATE = FieldReportTemplate(
    code="INCIDENT",
    name_az="İnsident bildirişi",
    requires_checklist=False,
)
AUDIT_CATEGORY = FieldReportCategory(
    code="AUDIT_TEHLUKESIZLIK",
    report_type="STORE_AUDIT",
    name_az="Təhlükəsizlik",
    route_to_role=None,
)
THEFT_CATEGORY = FieldReportCategory(
    code="INCIDENT_OGURLUQ",
    report_type="INCIDENT",
    name_az="Oğurluq",
    route_to_role="ADMIN",
)
COMPLAINT_CATEGORY = FieldReportCategory(
    code="INCIDENT_SIKAYET",
    report_type="INCIDENT",
    name_az="Şikayət",
    route_to_role="HR_ADMIN",
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
    """`SystemLimits` — verilməyən açar üçün çağıranın defoltunu qaytarır."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return int(self._values.get(key, default))

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class FakeCatalog:
    """`FieldReportCatalog` — şablon/kateqoriya sətirləri YADDAŞDA.

    Kataloq `dict` kimi saxlanılır, çünki testin əsas iddialarından biri
    məhz budur: yeni şablon BİR SƏTİRDİR (`add_template`), kod dəyişikliyi
    deyil.
    """

    def __init__(
        self,
        templates: list[FieldReportTemplate] | None = None,
        categories: list[FieldReportCategory] | None = None,
    ) -> None:
        self.templates = {t.code: t for t in (templates or [AUDIT_TEMPLATE, INCIDENT_TEMPLATE])}
        self.categories = {
            c.code: c for c in (categories or [AUDIT_CATEGORY, THEFT_CATEGORY, COMPLAINT_CATEGORY])
        }

    def add_template(
        self, template: FieldReportTemplate, categories: list[FieldReportCategory]
    ) -> None:
        """Yeni şablon = bir `INSERT` (migrations/037-nin kataloq qərarı)."""
        self.templates[template.code] = template
        for category in categories:
            self.categories[category.code] = category

    def get_template(self, tenant_id: TenantId, code: str) -> FieldReportTemplate | None:
        return self.templates.get(code.strip().upper())

    def list_templates(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[FieldReportTemplate]:
        return [t for t in self.templates.values() if include_inactive or t.is_active]

    def get_category(self, tenant_id: TenantId, code: str) -> FieldReportCategory | None:
        return self.categories.get(code.strip().upper())

    def list_categories(
        self,
        tenant_id: TenantId,
        *,
        report_type: str | None = None,
        include_inactive: bool = False,
    ) -> list[FieldReportCategory]:
        return [
            c
            for c in self.categories.values()
            if (include_inactive or c.is_active)
            and (report_type is None or c.report_type == report_type)
        ]


class FakeFieldReports:
    """`FieldReportRepository` — yaddaşdakı hesabatlar + rol → işçi cədvəli."""

    def __init__(self) -> None:
        self.rows: dict[FieldReportId, FieldReport] = {}
        #: `(rol_kodu, store_id | None)` → işçilər. Real sorğunun
        #: (`employees JOIN positions`) davranışını güzgüləyir.
        self.role_members: dict[str, list[tuple[StoreId | None, EmployeeId]]] = {}
        self.gaps: list[StoreAuditGap] = []
        self.saved: list[FieldReportId] = []

    def get(self, report_id: FieldReportId) -> FieldReport | None:
        return self.rows.get(report_id)

    def find_by_item(self, tenant_id: TenantId, item_id: FieldReportItemId) -> FieldReport | None:
        for report in self.rows.values():
            if report.tenant_id != tenant_id:
                continue
            if any(item.id == item_id for item in report.items):
                return report
        return None

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_ids: list[StoreId] | None = None,
        report_type: str | None = None,
        limit: int = 200,
    ) -> list[FieldReport]:
        if store_ids is not None and not store_ids:
            return []
        return [
            r
            for r in self.rows.values()
            if r.tenant_id == tenant_id
            and r.status.is_open
            and (store_ids is None or r.store_id in store_ids)
            and (report_type is None or r.report_type == report_type)
        ][:limit]

    def save(self, report: FieldReport) -> None:
        self.rows[report.id] = report
        self.saved.append(report.id)

    def list_route_recipients(
        self, tenant_id: TenantId, *, role_code: str, store_id: StoreId | None = None
    ) -> list[EmployeeId]:
        members = self.role_members.get(role_code.strip().upper(), [])
        return [
            employee_id
            for member_store, employee_id in members
            if store_id is None or member_store == store_id
        ]

    def stores_missing_audit(
        self, tenant_id: TenantId, *, now: datetime, interval_days: int
    ) -> list[StoreAuditGap]:
        return list(self.gaps)


class FakeTasks:
    """`TaskRepository` — Tapşırıq Mühərrikinin yaddaş tərəfi."""

    def __init__(self) -> None:
        self.rows: dict[TaskId, Task] = {}

    def get(self, task_id: TaskId) -> Task | None:
        return self.rows.get(task_id)

    def list_for_assignee(self, employee_id: EmployeeId, *, open_only: bool = True) -> list[Task]:
        return [t for t in self.rows.values() if t.assignee_id == employee_id]

    def list_awaiting_review(self, tenant_id: TenantId) -> list[Task]:
        return []

    def list_overdue(self, tenant_id: TenantId, *, now: datetime) -> list[Task]:
        return []

    def save(self, task: Task) -> None:
        self.rows[task.id] = task


class FakeToggles:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        return self.enabled


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


class FakeBenchmarkProvider:
    """`MultiStoreMetricProvider` — audit balının Dashboard tərəfi."""

    def __init__(self, values: dict[BenchmarkMetric, dict[StoreId, float]]) -> None:
        self._values = values

    def active_stores(self, tenant_id: TenantId) -> dict[StoreId, str]:
        return {STORE: "Mərkəz", OTHER_STORE: "Filial-2"}

    def metric_values(
        self, tenant_id: TenantId, metric: BenchmarkMetric, *, start: object, end: object
    ) -> dict[StoreId, float]:
        return dict(self._values.get(metric, {}))


@dataclass
class Harness:
    use_case: FieldReportUseCase
    reports: FakeFieldReports
    catalog: FakeCatalog
    tasks: FakeTasks
    audit: RecordingAudit
    notifier: RecordingNotifier
    clock: FakeClock
    toggles: FakeToggles
    limits: FakeLimits
    task_engine: TaskWorkflowUseCase
    created_tasks: list[TaskId] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def make_actor(
    *,
    flags: list[PermissionFlag] | None = None,
    role: SystemRole = SystemRole.HR_ADMIN,
    store_id: StoreId | None = STORE,
) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value.title(),
        priority=role.default_priority,
        is_system=True,
    )
    for flag in flags if flags is not None else [AUDIT_FLAG, INCIDENT_FLAG, ASSIGN_FLAG]:
        position.grant(flag)
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="A",
        last_name="Auditor",
        store_id=store_id,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def build(
    *,
    catalog: FakeCatalog | None = None,
    limits: dict[str, str] | None = None,
    toggles_enabled: bool = True,
) -> Harness:
    clock = FakeClock()
    reports = FakeFieldReports()
    tasks = FakeTasks()
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    toggles = FakeToggles(enabled=toggles_enabled)
    fake_limits = FakeLimits(limits)
    # TƏK NÜSXƏ: use case-in gördüyü kataloq ilə testin redaktə etdiyi kataloq
    # EYNİ obyekt olmalıdır — iki nüsxə qursaydıq, `add_template()` çağırışı
    # use case-ə heç vaxt çatmazdı və "yeni şablon kod dəyişikliyi tələb
    # etmir" testi yalançı-yaşıl olardı.
    active_catalog = catalog or FakeCatalog()
    task_engine = TaskWorkflowUseCase(
        tasks=tasks,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        toggles=toggles,  # type: ignore[arg-type]
    )
    use_case = FieldReportUseCase(
        reports=reports,  # type: ignore[arg-type]
        catalog=active_catalog,  # type: ignore[arg-type]
        tasks=task_engine,
        limits=fake_limits,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
    )
    return Harness(
        use_case=use_case,
        reports=reports,
        catalog=active_catalog,
        tasks=tasks,
        audit=audit,
        notifier=notifier,
        clock=clock,
        toggles=toggles,
        limits=fake_limits,
        task_engine=task_engine,
    )


def audit_draft(*items: ChecklistItemDraft) -> FieldReportDraft:
    return FieldReportDraft(
        report_type="STORE_AUDIT",
        category="AUDIT_TEHLUKESIZLIK",
        store_id=STORE,
        detail="Yanğın çıxışı və kassa intizamı yoxlanıldı.",
        checklist=tuple(items),
    )


def incident_draft(category: str = "INCIDENT_OGURLUQ") -> FieldReportDraft:
    return FieldReportDraft(
        report_type="INCIDENT",
        category=category,
        store_id=STORE,
        detail="Anbarda iki qutu məhsul əskikdir.",
    )


# --------------------------------------------------------------------------- #
# Struktur Qərar B — Tapşırıq Mühərriki və `passed`-in üç vəziyyəti
# --------------------------------------------------------------------------- #


class TestCorrectiveTasks:
    def test_ugursuz_bloklayici_bend_task_yaradir(self) -> None:
        """Mövcud Tapşırıq Mühərriki ÇAĞIRILIR — yeni sistem yaranmır."""
        harness = build()
        actor = make_actor()
        manager = EmployeeId(uuid.uuid4())
        harness.reports.role_members["MAGAZA_MENECERI"] = [(STORE, manager)]

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=actor,
            draft=audit_draft(
                ChecklistItemDraft(
                    item_text="Yanğın çıxışı açıqdır",
                    is_blocking=True,
                    passed=False,
                    note="Qapı qutularla bağlanıb",
                )
            ),
        )

        assert len(submission.corrective_task_ids) == 1
        task = harness.tasks.rows[submission.corrective_task_ids[0]]
        # Tapşırıq MÖVCUD motorun sətridir: `Task` aqreqatı, `TASK_ASSIGNED`
        # audit yazısı və mağaza rəhbərinə təyinat.
        assert task.assignee_id == manager
        assert task.store_id == STORE
        assert "TASK_ASSIGNED" in harness.audit.actions()
        assert "Qapı qutularla bağlanıb" in task.description

    def test_ugursuz_qeyri_bloklayici_bend_task_yaratmir(self) -> None:
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(item_text="Vitrin tozludur", is_blocking=False, passed=False)
            ),
        )

        assert submission.corrective_task_ids == ()
        assert harness.tasks.rows == {}

    def test_cavabsiz_bloklayici_bend_task_yaratmir(self) -> None:
        """`passed IS NULL` = "hələ yoxlanılmayıb" — uğursuzluq DEYİL.

        `migrations/037`-dəki qismən indeksin predikatı (`passed IS FALSE`)
        ilə eyni qərar; `not passed` yazılsaydı bu test qırılardı.
        """
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(
                    item_text="Anbar rəfləri yoxlanılmalıdır", is_blocking=True, passed=None
                )
            ),
        )

        assert submission.corrective_task_ids == ()
        assert submission.report.blocking_failures == ()

    def test_task_engine_sondurulubse_hesabat_da_yazilmir(self) -> None:
        """Tapşırıq istisnası UDULMUR — sükutla itən tapıntı ən pis haldır."""
        harness = build(toggles_enabled=False)

        with pytest.raises(Exception, match="TASK_ENGINE"):
            harness.use_case.submit(
                tenant_id=TENANT,
                actor=make_actor(),
                draft=audit_draft(
                    ChecklistItemDraft(
                        item_text="Yanğın çıxışı açıqdır", is_blocking=True, passed=False
                    )
                ),
            )

    def test_task_mohleti_root_parametrindendir(self) -> None:
        harness = build(limits={SystemLimitKey.FIELD_REPORT_TASK_DEADLINE_DAYS.value: "7"})

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(
                    item_text="Kassa kilidi sınıqdır", is_blocking=True, passed=False
                )
            ),
        )

        task = harness.tasks.rows[submission.corrective_task_ids[0]]
        assert task.deadline == NOW + timedelta(days=7)

    def test_menecer_tapilmayanda_task_hesabati_yazana_qalir(self) -> None:
        """Sahibsiz tapşırıq mümkün deyil — ehtiyat yolu auditorun özüdür."""
        harness = build()
        actor = make_actor()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=actor,
            draft=audit_draft(
                ChecklistItemDraft(
                    item_text="Kassa kilidi sınıqdır", is_blocking=True, passed=False
                )
            ),
        )

        task = harness.tasks.rows[submission.corrective_task_ids[0]]
        assert task.assignee_id == actor.id

    def test_bloklayici_bend_basina_ayri_task(self) -> None:
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(
                    item_text="Yanğın çıxışı açıqdır", is_blocking=True, passed=False
                ),
                ChecklistItemDraft(
                    item_text="Kassa kilidi işləyir", is_blocking=True, passed=False
                ),
                ChecklistItemDraft(item_text="Vitrin təmizdir", is_blocking=True, passed=True),
            ),
        )

        assert len(submission.corrective_task_ids) == 2


# --------------------------------------------------------------------------- #
# Foto-sübut qaydası
# --------------------------------------------------------------------------- #


class TestPhotoEvidence:
    def test_photo_required_bend_fotosuz_tesdiqlene_bilmir(self) -> None:
        harness = build()

        with pytest.raises(DomainRuleError, match=r"[Ff]oto"):
            harness.use_case.submit(
                tenant_id=TENANT,
                actor=make_actor(),
                draft=audit_draft(
                    ChecklistItemDraft(
                        item_text="Soyuducunun temperaturu",
                        photo_required=True,
                        passed=True,
                    )
                ),
            )

    def test_photo_required_bend_fotolu_tesdiqlenir(self) -> None:
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(
                    item_text="Soyuducunun temperaturu",
                    photo_required=True,
                    passed=True,
                    photo_ref="spool:abc",
                )
            ),
        )

        assert submission.report.items[0].passed is True

    def test_photo_required_bend_cavabsiz_qala_biler(self) -> None:
        """Qayda CAVAB anındadır, sətrin YARANMASI anında yox.

        Oflayn terminal checklist-i fotosuz YARADA bilməlidir — məhz bu
        səbəblə `migrations/037` DB `CHECK`-i qoymayıb.
        """
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(item_text="Soyuducunun temperaturu", photo_required=True)
            ),
        )

        assert submission.report.items[0].passed is None

    def test_yuklenmis_foto_hesabata_baglanir(self) -> None:
        harness = build()
        submission = harness.use_case.submit(
            tenant_id=TENANT, actor=make_actor(), draft=incident_draft()
        )

        attached = harness.use_case.attach_uploaded_photo(
            tenant_id=TENANT, owner_id=submission.report.id, photo_ref="drive:conn/file"
        )

        assert attached is True
        assert harness.reports.rows[submission.report.id].photo_refs == ("drive:conn/file",)
        assert "FIELD_REPORT_PHOTO_ATTACHED" in harness.audit.actions()

    def test_yuklenmis_foto_checklist_bendine_baglanir(self) -> None:
        """`owner_id` bənd İD-si olduqda da birmənalı həll olunur (UUID unikal)."""
        harness = build()
        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(
                    item_text="Soyuducunun temperaturu", photo_required=True, photo_ref="spool:abc"
                )
            ),
        )
        item_id = submission.report.items[0].id

        attached = harness.use_case.attach_uploaded_photo(
            tenant_id=TENANT, owner_id=item_id, photo_ref="drive:conn/file"
        )

        assert attached is True
        assert harness.reports.rows[submission.report.id].items[0].photo_ref == "drive:conn/file"

    def test_namelum_sahib_cokdurmur(self) -> None:
        harness = build()

        assert (
            harness.use_case.attach_uploaded_photo(
                tenant_id=TENANT, owner_id=FieldReportId(uuid.uuid4()), photo_ref="drive:x"
            )
            is False
        )

    def test_foto_tavani_root_parametrindendir(self) -> None:
        harness = build(limits={SystemLimitKey.FIELD_REPORT_MAX_PHOTOS.value: "1"})

        with pytest.raises(Exception, match="şəkil"):
            harness.use_case.submit(
                tenant_id=TENANT,
                actor=make_actor(),
                draft=FieldReportDraft(
                    report_type="INCIDENT",
                    category="INCIDENT_OGURLUQ",
                    store_id=STORE,
                    detail="Anbarda iki qutu məhsul əskikdir.",
                    photo_refs=("a", "b"),
                ),
            )


# --------------------------------------------------------------------------- #
# #27 marşrutlaması — kataloqdan, `if` ilə yox
# --------------------------------------------------------------------------- #


class TestRouting:
    def test_kateqoriya_kataloqdaki_rola_marsrutlanir(self) -> None:
        harness = build()
        admin = EmployeeId(uuid.uuid4())
        hr = EmployeeId(uuid.uuid4())
        harness.reports.role_members["ADMIN"] = [(None, admin)]
        harness.reports.role_members["HR_ADMIN"] = [(None, hr)]

        theft = harness.use_case.submit(
            tenant_id=TENANT, actor=make_actor(), draft=incident_draft("INCIDENT_OGURLUQ")
        )
        complaint = harness.use_case.submit(
            tenant_id=TENANT, actor=make_actor(), draft=incident_draft("INCIDENT_SIKAYET")
        )

        assert theft.routed_role == "ADMIN"
        assert complaint.routed_role == "HR_ADMIN"
        routed = [
            m["recipient_id"]
            for m in harness.notifier.messages
            if m["category"] == ROUTED_NOTIFICATION_CATEGORY
        ]
        assert routed == [admin, hr]

    def test_marsrut_deyisdirilende_kod_deyismir(self) -> None:
        """Root `route_to_role`-u dəyişəndə bildiriş YENİ rola gedir.

        `if category == "INCIDENT_OGURLUQ"` yazılsaydı, bu test qırılardı.
        """
        catalog = FakeCatalog(
            categories=[
                AUDIT_CATEGORY,
                FieldReportCategory(
                    code="INCIDENT_OGURLUQ",
                    report_type="INCIDENT",
                    name_az="Oğurluq",
                    route_to_role="HR_ADMIN",  # Root dəyişdi: ADMIN → HR_ADMIN
                ),
            ]
        )
        harness = build(catalog=catalog)
        hr = EmployeeId(uuid.uuid4())
        harness.reports.role_members["HR_ADMIN"] = [(None, hr)]

        submission = harness.use_case.submit(
            tenant_id=TENANT, actor=make_actor(), draft=incident_draft()
        )

        assert submission.routed_role == "HR_ADMIN"
        assert submission.routed_recipients == 1

    def test_marsrutsuz_kateqoriya_broadcast_yoluna_dusur(self) -> None:
        """Audit kateqoriyaları `route_to_role IS NULL`-dur — çökmür."""
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(ChecklistItemDraft(item_text="Vitrin təmizdir", passed=True)),
        )

        assert submission.routed_role is None
        assert submission.routed_recipients == 0
        broadcast = [
            m for m in harness.notifier.messages if m["category"] == ROUTED_NOTIFICATION_CATEGORY
        ]
        assert broadcast and broadcast[0]["recipient_id"] is None

    def test_rolda_isci_yoxdursa_broadcast_yoluna_dusur(self) -> None:
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT, actor=make_actor(), draft=incident_draft()
        )

        assert submission.routed_role == "ADMIN"
        assert submission.routed_recipients == 0

    def test_broadcast_setri_auditoriya_suzgeci_ile_qapilir(self) -> None:
        """Süzgəcsiz sətir FAIL-OPEN olardı — `Satıcı` oğurluğu görərdi."""
        assert ROUTED_NOTIFICATION_CATEGORY in TENANT_NOTIFICATION_AUDIENCE
        assert TENANT_NOTIFICATION_AUDIENCE[ROUTED_NOTIFICATION_CATEGORY] == (CONDUCT_AUDIT_FLAG,)

        hidden_for_seller = hidden_tenant_categories(lambda _flag: False)
        hidden_for_admin = hidden_tenant_categories(lambda flag: flag == CONDUCT_AUDIT_FLAG)

        assert ROUTED_NOTIFICATION_CATEGORY in hidden_for_seller
        assert ROUTED_NOTIFICATION_CATEGORY not in hidden_for_admin

    def test_namelum_kateqoriya_cokdurmur(self) -> None:
        """Aydın domen xətası — `KeyError`/`AttributeError` YOX."""
        harness = build()

        with pytest.raises(UnknownFieldReportTemplateError):
            harness.use_case.submit(
                tenant_id=TENANT, actor=make_actor(), draft=incident_draft("INCIDENT_YOXDUR")
            )

    def test_deaktiv_kateqoriya_yeni_hesabatda_secilmir(self) -> None:
        catalog = FakeCatalog(
            categories=[
                FieldReportCategory(
                    code="INCIDENT_OGURLUQ",
                    report_type="INCIDENT",
                    name_az="Oğurluq",
                    route_to_role="ADMIN",
                    is_active=False,
                )
            ]
        )
        harness = build(catalog=catalog)

        with pytest.raises(UnknownFieldReportTemplateError):
            harness.use_case.submit(tenant_id=TENANT, actor=make_actor(), draft=incident_draft())

    def test_kateqoriya_sablona_uygun_olmalidir(self) -> None:
        """Birləşmiş FK-nın kod tərəfi — DB xətası ekrana çatmır."""
        harness = build()

        with pytest.raises(UnknownFieldReportTemplateError):
            harness.use_case.submit(
                tenant_id=TENANT,
                actor=make_actor(),
                draft=FieldReportDraft(
                    report_type="INCIDENT",
                    category="AUDIT_TEHLUKESIZLIK",
                    store_id=STORE,
                    detail="Kateqoriya səhv şablona bağlanıb.",
                ),
            )


# --------------------------------------------------------------------------- #
# Səlahiyyət — açıq istisna, sükutla "heç nə" YOX
# --------------------------------------------------------------------------- #


class TestAuthorization:
    def test_flagsiz_aktor_audit_hesabati_yarada_bilmir(self) -> None:
        harness = build()
        seller = make_actor(flags=[INCIDENT_FLAG], role=SystemRole.SELLER)

        with pytest.raises(AuthorizationError, match=CONDUCT_AUDIT_FLAG):
            harness.use_case.submit(
                tenant_id=TENANT,
                actor=seller,
                draft=audit_draft(ChecklistItemDraft(item_text="Vitrin təmizdir", passed=True)),
            )
        assert harness.reports.rows == {}

    def test_her_kes_insident_bildire_bilir(self) -> None:
        """038 Tələ 3: bildirmək sərbəstdir, HƏLL etmək məhduddur."""
        harness = build()
        seller = make_actor(flags=[INCIDENT_FLAG], role=SystemRole.SELLER)

        submission = harness.use_case.submit(tenant_id=TENANT, actor=seller, draft=incident_draft())

        assert submission.report.status is FieldReportStatus.SUBMITTED

    def test_insident_bildiren_onu_baglaya_bilmir(self) -> None:
        harness = build()
        seller = make_actor(flags=[INCIDENT_FLAG], role=SystemRole.SELLER)
        submission = harness.use_case.submit(tenant_id=TENANT, actor=seller, draft=incident_draft())

        with pytest.raises(AuthorizationError, match=CONDUCT_AUDIT_FLAG):
            harness.use_case.close(
                tenant_id=TENANT,
                actor=seller,
                report_id=submission.report.id,
                status=FieldReportStatus.DISMISSED,
                note="Yoxlanıldı, əsassızdır.",
            )

    def test_sablon_siyahisi_selahiyyete_gore_suzulur(self) -> None:
        harness = build()
        seller = make_actor(flags=[INCIDENT_FLAG], role=SystemRole.SELLER)

        codes = [t.code for t in harness.use_case.list_templates(tenant_id=TENANT, actor=seller)]

        assert codes == ["INCIDENT"]

    def test_basqa_kirayecinin_aktoru_reddedilir(self) -> None:
        harness = build()
        stranger = make_actor()
        stranger.tenant_id = TenantId(uuid.uuid4())

        with pytest.raises(AuthorizationError):
            harness.use_case.submit(tenant_id=TENANT, actor=stranger, draft=incident_draft())


# --------------------------------------------------------------------------- #
# Struktur Qərar A — yeni şablon KOD dəyişikliyi tələb etmir
# --------------------------------------------------------------------------- #


class TestTemplateExtensibility:
    def test_yeni_sablon_yalniz_kataloq_setri_teleb_edir(self) -> None:
        """`SUPPLY_CHECK` — kodda HEÇ BİR yeri dəyişmədən tam axından keçir.

        Bu test Struktur Qərar A-nın QAPISIDIR: kimsə `if report_type ==
        "STORE_AUDIT"` zənciri yazsa, üçüncü şablon ya rədd edilər, ya da
        checklist/səlahiyyət/tapşırıq qollarından birinə düşməz.
        """
        catalog = FakeCatalog()
        catalog.add_template(
            FieldReportTemplate(
                code="SUPPLY_CHECK",
                name_az="Təchizat yoxlaması",
                requires_checklist=True,
            ),
            [
                FieldReportCategory(
                    code="SUPPLY_ANBAR",
                    report_type="SUPPLY_CHECK",
                    name_az="Anbar",
                    route_to_role=None,
                )
            ],
        )
        harness = build(catalog=catalog)
        manager = EmployeeId(uuid.uuid4())
        harness.reports.role_members["MAGAZA_MENECERI"] = [(STORE, manager)]

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=FieldReportDraft(
                report_type="SUPPLY_CHECK",
                category="SUPPLY_ANBAR",
                store_id=STORE,
                detail="Anbar təchizatı yoxlanıldı.",
                checklist=(
                    ChecklistItemDraft(
                        item_text="Soyuq zəncir pozulmayıb", is_blocking=True, passed=False
                    ),
                ),
            ),
        )

        # 1) checklist tələbi kataloqdan tanınır, 2) səlahiyyət audit
        # flag-idir (`requires_checklist=True`), 3) tapşırıq yaranır.
        assert submission.report.report_type == "SUPPLY_CHECK"
        assert len(submission.corrective_task_ids) == 1
        assert harness.tasks.rows[submission.corrective_task_ids[0]].assignee_id == manager

    def test_checklist_teleb_eden_sablon_bos_forma_ile_teqdim_edilmir(self) -> None:
        harness = build()

        with pytest.raises(Exception, match="checklist"):
            harness.use_case.submit(
                tenant_id=TENANT,
                actor=make_actor(),
                draft=FieldReportDraft(
                    report_type="STORE_AUDIT",
                    category="AUDIT_TEHLUKESIZLIK",
                    store_id=STORE,
                    detail="Checklist doldurulmayıb.",
                ),
            )

    def test_checklist_teleb_etmeyen_sablon_bos_forma_qebul_edir(self) -> None:
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT, actor=make_actor(), draft=incident_draft()
        )

        assert submission.report.items == ()


# --------------------------------------------------------------------------- #
# Struktur Qərar C — audit balı Benchmark metriki kimi oxunur
# --------------------------------------------------------------------------- #


class TestAuditScoreMetric:
    def test_audit_bali_domen_terefinde_faizdir(self) -> None:
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(item_text="Vitrin təmizdir", passed=True),
                ChecklistItemDraft(item_text="Kassa intizamı", passed=True),
                ChecklistItemDraft(item_text="Yanğın çıxışı", passed=False),
                # Cavabsız bənd MƏXRƏCƏ DAXİL DEYİL.
                ChecklistItemDraft(item_text="Anbar rəfləri"),
            ),
        )

        assert submission.report.audit_score == pytest.approx(200.0 / 3)

    def test_cavablanmamis_audit_bali_sifir_deyil_none_dir(self) -> None:
        """ "0% keçdi" ilə "hələ yoxlanılmayıb" fərqli hallardır."""
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(ChecklistItemDraft(item_text="Anbar rəfləri")),
        )

        assert submission.report.audit_score is None

    def test_audit_bali_benchmark_metrikidir_ve_istiqameti_duzgundur(self) -> None:
        """ÇOX yaxşıdır — `lower_is_better=False`.

        Səhv istiqamət ən pis filialı reytinqin başında "ən yaxşı" kimi
        göstərərdi.
        """
        assert BenchmarkMetric.AUDIT_SCORE.lower_is_better is False
        assert BenchmarkMetric.AUDIT_SCORE.unit_suffix == "%"

        provider = FakeBenchmarkProvider(
            {BenchmarkMetric.AUDIT_SCORE: {STORE: 92.0, OTHER_STORE: 61.0}}
        )
        use_case = MultiStoreBenchmarkUseCase(
            provider=provider,  # type: ignore[arg-type]
            limits=FakeLimits(),  # type: ignore[arg-type]
            clock=FakeClock(),  # type: ignore[arg-type]
        )
        actor = make_actor(flags=[EXPORT_FLAG])

        rows = use_case.ranking(
            tenant_id=TENANT, actor=actor, metric=BenchmarkMetric.AUDIT_SCORE, now=NOW
        )

        assert [row.store_id for row in rows] == [STORE, OTHER_STORE]
        assert rows[0].display_value == "92.0%"


# --------------------------------------------------------------------------- #
# Status axını, ROOT parametrləri və gecəlik xatırlatma
# --------------------------------------------------------------------------- #


class TestWorkflowAndReminders:
    def test_status_axini_terminala_qeder(self) -> None:
        harness = build()
        actor = make_actor()
        submission = harness.use_case.submit(tenant_id=TENANT, actor=actor, draft=incident_draft())

        harness.use_case.start_progress(
            tenant_id=TENANT, actor=actor, report_id=submission.report.id
        )
        closed = harness.use_case.close(
            tenant_id=TENANT,
            actor=actor,
            report_id=submission.report.id,
            status=FieldReportStatus.RESOLVED,
            note="Kameralar yoxlanıldı, məhsul tapıldı.",
        )

        assert closed.status is FieldReportStatus.RESOLVED
        assert closed.resolved_by == actor.id
        assert closed.resolved_at == NOW
        assert harness.audit.actions().count("FIELD_REPORT_CLOSED") == 1

    def test_baglanmis_hesabat_yeniden_baglanmir(self) -> None:
        harness = build()
        actor = make_actor()
        submission = harness.use_case.submit(tenant_id=TENANT, actor=actor, draft=incident_draft())
        harness.use_case.close(
            tenant_id=TENANT,
            actor=actor,
            report_id=submission.report.id,
            status=FieldReportStatus.DISMISSED,
            note="Səhv məlumat verilib.",
        )

        with pytest.raises(Exception, match="bağlan"):
            harness.use_case.close(
                tenant_id=TENANT,
                actor=actor,
                report_id=submission.report.id,
                status=FieldReportStatus.RESOLVED,
                note="İkinci qərar yazılmamalıdır.",
            )

    def test_minimum_tesvir_uzunlugu_root_parametrindendir(self) -> None:
        harness = build(limits={SystemLimitKey.FIELD_REPORT_MIN_DETAIL_LENGTH.value: "40"})

        with pytest.raises(DomainRuleError, match="40"):
            harness.use_case.submit(tenant_id=TENANT, actor=make_actor(), draft=incident_draft())

    def test_gecikmis_audit_xatirlatmasi_filial_basina_bir_setirdir(self) -> None:
        harness = build()
        harness.reports.gaps = [
            StoreAuditGap(store_id=STORE, store_name="Mərkəz", last_audit_at=None, days_since=None),
            StoreAuditGap(
                store_id=OTHER_STORE,
                store_name="Filial-2",
                last_audit_at=NOW - timedelta(days=45),
                days_since=45,
            ),
        ]

        result = harness.use_case.notify_overdue_audits(TENANT)

        assert result.checked == 2
        assert result.overdue_count == 2
        bodies = [str(m["body_az"]) for m in harness.notifier.messages]
        assert any("HEÇ VAXT" in body for body in bodies)
        assert any("45 gün əvvəl" in body for body in bodies)

    def test_audit_xatirlatmasi_auditoriya_suzgeci_ile_qapilir(self) -> None:
        harness = build()
        harness.reports.gaps = [
            StoreAuditGap(store_id=STORE, store_name="Mərkəz", last_audit_at=None, days_since=None)
        ]

        harness.use_case.notify_overdue_audits(TENANT)

        category = str(harness.notifier.messages[0]["category"])
        assert category in TENANT_NOTIFICATION_AUDIENCE
        assert TENANT_NOTIFICATION_AUDIENCE[category] == (CONDUCT_AUDIT_FLAG,)

    def test_root_parametrlerinin_hamisinin_defoltu_var(self) -> None:
        """Defoltsuz açar ROOT ekranını `KeyError` ilə çökdürür."""
        for key in (
            SystemLimitKey.FIELD_REPORT_AUDIT_INTERVAL_DAYS,
            SystemLimitKey.FIELD_REPORT_MAX_PHOTOS,
            SystemLimitKey.FIELD_REPORT_MIN_DETAIL_LENGTH,
            SystemLimitKey.FIELD_REPORT_TASK_DEADLINE_DAYS,
            SystemLimitKey.FIELD_REPORT_TASK_ASSIGNEE_ROLE,
        ):
            assert key in DEFAULT_LIMITS

    def test_acig_hesabat_siyahisi_magaza_ehatesi_ile_suzulur(self) -> None:
        harness = build()
        actor = make_actor()
        harness.use_case.submit(tenant_id=TENANT, actor=actor, draft=incident_draft())

        assert harness.use_case.list_open(tenant_id=TENANT, actor=actor, store_ids=[STORE])
        # BOŞ siyahı = "heç bir mağazaya çıxışı yoxdur" (fail-safe).
        assert harness.use_case.list_open(tenant_id=TENANT, actor=actor, store_ids=[]) == []


# --------------------------------------------------------------------------- #
# Aqreqat davranışı
# --------------------------------------------------------------------------- #


class TestAggregate:
    def test_repository_berpasi_hadise_yaymir(self) -> None:
        """Hər oxu "yeni hesabat" bildirişi doğursaydı, marşrut spam olardı."""
        report = FieldReport(
            report_id=FieldReportId(uuid.uuid4()),
            tenant_id=TENANT,
            report_type="INCIDENT",
            category="INCIDENT_OGURLUQ",
            store_id=STORE,
            reported_by=EmployeeId(uuid.uuid4()),
            detail="Bərpa edilmiş sətir.",
            created_at=NOW,
            updated_at=NOW,
            emit_created_event=False,
        )

        assert report.collect_events() == ()

    def test_teqdimat_hadisesi_bloklayici_ugursuzluq_sayini_dasiyir(self) -> None:
        harness = build()
        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(item_text="Yanğın çıxışı", is_blocking=True, passed=False)
            ),
        )

        events = submission.report.collect_events()

        assert len(events) == 1
        assert events[0].blocking_failures == 1  # type: ignore[attr-defined]
        assert events[0].report_type == "STORE_AUDIT"  # type: ignore[attr-defined]

    def test_tekrar_foto_istinadi_sukutla_atilir(self) -> None:
        """Növbə eyni yükləməni iki dəfə təsdiqləyə bilər — istisna atmır."""
        report = _bare_report()

        report.add_photo(photo_ref="drive:a", now=NOW)
        report.add_photo(photo_ref="drive:a", now=NOW)

        assert report.photo_refs == ("drive:a",)

    def test_bend_sirasi_birden_baslayir(self) -> None:
        harness = build()

        submission = harness.use_case.submit(
            tenant_id=TENANT,
            actor=make_actor(),
            draft=audit_draft(
                ChecklistItemDraft(item_text="Birinci bənd"),
                ChecklistItemDraft(item_text="İkinci bənd"),
            ),
        )

        assert [item.position_no for item in submission.report.items] == [1, 2]

    def test_bos_foto_istinadi_reddedilir(self) -> None:
        report = _bare_report()

        with pytest.raises(DomainRuleError):
            report.add_photo(photo_ref="   ", now=NOW)

    def test_bend_cavabi_sonradan_verilende_de_foto_teleb_olunur(self) -> None:
        item = FieldReportChecklistItem(
            item_id=FieldReportItemId(uuid.uuid4()),
            tenant_id=TENANT,
            report_id=FieldReportId(uuid.uuid4()),
            position_no=1,
            item_text="Soyuducunun temperaturu",
            created_at=NOW,
            updated_at=NOW,
            photo_required=True,
        )

        with pytest.raises(DomainRuleError):
            item.answer(passed=False, now=NOW)

        item.answer(passed=False, now=NOW, photo_ref="spool:z")
        assert item.is_blocking_failure is False  # `is_blocking=False`


def _bare_report() -> FieldReport:
    return FieldReport(
        report_id=FieldReportId(uuid.uuid4()),
        tenant_id=TENANT,
        report_type="INCIDENT",
        category="INCIDENT_OGURLUQ",
        store_id=STORE,
        reported_by=EmployeeId(uuid.uuid4()),
        detail="Foto qaydası testi üçün sətir.",
        created_at=NOW,
        updated_at=NOW,
        emit_created_event=False,
    )
