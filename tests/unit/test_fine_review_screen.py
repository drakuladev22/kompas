"""Aylıq Cərimə İcmalı ekranı, kontrolleri və kompozisiya bağlantısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
`MonthlyFineReviewUseCase.publish_batch` `FineStatus.PUBLISHED`-ə YEGANƏ
yoldur, lakin nə ekranı, nə kontrolleri vardı, nə də `composition.py`-dakı
`Session`-a qoşulmuşdu — yəni onu çağıracaq BİR YOL DA yox idi. Nəticə
zəncirvari idi: cərimə `PENDING_REVIEW` doğulur → nəşr olunmur → işçi onu
görmür → etiraz pəncərəsi açılmır → export şərti heç vaxt ödənmir, yəni HEÇ
BİR cərimə maaşdan kəsilmir.

Fayl həmin zəncirin hər halqasını qapıya çevirir:

    * menyu maddəsi FAKTİKİ flag-ə bağlıdır (`can_publish_fines`) və kamera
      rolundan struktur olaraq kəsilib;
    * use case `Session`-da MÖVCUDDUR (kompozisiya reqressiyası);
    * nəşr `publish_batch`-i TƏK dəfə, DOĞRU arqumentlərlə çağırır;
    * təsdiq modalı ləğv edilərsə HEÇ NƏ yazılmır;
    * yazma və commit BİR sessiyadadır (qismən nəşr mümkün deyil);
    * nəşrdən sonra siyahı yenidən oxunur;
    * uçdan-uca: `PENDING_REVIEW` cərimə nəşrdən sonra `PUBLISHED` olur və
      `visible_to_employee` onu qaytarır.

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py`-ın YALNIZ mövcud
`FakeClock`/`FakeSystemLimits`/`RecordingAudit`/`RecordingNotifier` sinifləri
işlədilir (paralel işlər ortaq faylı dəyişə bilər).

Kontroller testləri PySide6 idxalını TƏLƏB EDİR (`controllers/fine_review.py`
ekranın `NamedTuple`-larını modul səviyyəsində idxal edir —
`controllers/field_reports.py` ilə eyni naxış); pəncərə qurmaq isə yalnız
`@requires_qt` testlərində baş verir.
"""

from __future__ import annotations

import ast
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from src.application.use_cases.fine_review import (
    MIN_DISCARD_REASON_LENGTH,
    PUBLISH_FINES_FLAG,
    FineReviewError,
    MonthlyFineReviewUseCase,
    ReviewDecision,
)
from src.domain.entities.employee import Employee
from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FineId,
    FineTypeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.presentation import preview_data
from src.presentation.composition import Session
from src.presentation.controllers.fine_review import (
    EMPTY_BATCH,
    LIST_CHANGED,
    LIST_READ_FAILED,
    PUBLISH_FAILED,
    MonthlyFineReviewController,
    decision_options,
)
from src.presentation.screens.fine_review import (
    FineReviewGroup,
    FineReviewRow,
    PublishSummary,
)
from src.presentation.shell.menu import DEFAULT_ENTRIES, MODULE_FINES, build_default_registry
from tests.conftest import requires_qt
from tests.fixtures.fakes import (
    FakeClock,
    FakeSystemLimits,
    RecordingAudit,
    RecordingFineReviewBatches,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
STORE_A: Final = StoreId(uuid.uuid4())
STORE_B: Final = StoreId(uuid.uuid4())
WORKER: Final = EmployeeId(uuid.uuid4())
OPERATOR: Final = EmployeeId(uuid.uuid4())
FINE_TYPE: Final = FineTypeId(uuid.uuid4())

#: Cərimələr İYUL ayındadır, nəşr isə avqustun əvvəlində — icmalın real ritmi.
ISSUED: Final = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)
PUBLISHED_AT: Final = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
PERIOD: Final = "2026-07"

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
COMPOSITION: Final = PROJECT_ROOT / "src/presentation/composition.py"
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"


# --------------------------------------------------------------------------- #
# Aktorlar və cərimələr
# --------------------------------------------------------------------------- #


def _employee(*flags: str, is_camera_type: bool = False) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="ADMIN",
        name_az="Admin",
        priority=RolePriority.ADMIN,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=is_camera_type,
    )
    for flag in flags:
        position.grant(PermissionFlag(code=flag, category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Rəşad",
        last_name="Məmmədov",
        username=Username("r.mammadov"),
        has_password=True,
    )


def _publisher() -> Employee:
    return _employee(PUBLISH_FINES_FLAG)


def _seller() -> Employee:
    """Heç bir flag daşımayan `Satıcı` — maddəni GÖRMƏMƏLİDİR."""
    return _employee()


def _fine(*, store_id: StoreId = STORE_A, amount: str = "25.00") -> Fine:
    fine = Fine(
        fine_id=FineId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=store_id,
        source=FineSource.MANUAL_CAMERA,
        amount=Money.parse(amount),
        issued_at=ISSUED,
        fine_type_id=FINE_TYPE,
        issued_by=OPERATOR,
        photo_evidence_url="queue-entry-1",
    )
    # Repository-dən BƏRPA olunmuş aqreqat hadisə yaymır (CLAUDE.md §3).
    fine.discard_events()
    return fine


# --------------------------------------------------------------------------- #
# Sahtələr — baza və Qt olmadan
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Connection:
    """`_display_names`-in üç ad sorğusunun sahtəsi."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> _Result:
        self.queries.append(sql)
        wanted = {str(value) for value in params[1]}
        if "FROM employees" in sql:
            rows = [
                {"id": str(WORKER), "first_name": "Nigar", "last_name": "Səfərova"},
                {"id": str(OPERATOR), "first_name": "Elvin", "last_name": "Həsənov"},
            ]
        elif "FROM stores" in sql:
            rows = [
                {"id": str(STORE_A), "name": "Bellona 28 May"},
                {"id": str(STORE_B), "name": "İstikbal Xətai"},
            ]
        else:
            rows = [{"id": str(FINE_TYPE), "name_az": "Formaya uyğun geyinməmək"}]
        return _Result([row for row in rows if row["id"] in wanted])


class _FinesRepo:
    """`PostgresFineRepository`-nin icmal metodlarının müqavilə təkrarı."""

    def __init__(self, fines: list[Fine], journal: list[str]) -> None:
        self.fines = list(fines)
        self.saved: list[Fine] = []
        self.list_calls = 0
        self._journal = journal

    def pending_review_periods(self, tenant_id: Any) -> list[str]:
        return sorted(
            {
                f"{fine.issued_at.year:04d}-{fine.issued_at.month:02d}"
                for fine in self.fines
                if fine.status is FineStatus.PENDING_REVIEW
            }
        )

    def list_pending_review(self, tenant_id: Any, *, year: int, month: int) -> list[Fine]:
        self.list_calls += 1
        return [
            fine
            for fine in self.fines
            if fine.status is FineStatus.PENDING_REVIEW
            and fine.issued_at.year == year
            and fine.issued_at.month == month
        ]

    def save(self, fine: Fine) -> None:
        self.saved.append(fine)
        self._journal.append(f"SAVE:{fine.id}")


class _Uow:
    def __init__(self, fines: _FinesRepo, connection: _Connection) -> None:
        self.fines = fines
        self.connection = connection


class _SpyReview:
    """Həqiqi use case-in üzərində nazik casus — arqumentləri qeyd edir."""

    def __init__(self, inner: MonthlyFineReviewUseCase, error: Exception | None = None) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def publish_batch(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self._inner.publish_batch(**kwargs)


class _Session:
    def __init__(self, uow: _Uow, review: _SpyReview, journal: list[str]) -> None:
        self.tenant_id = TENANT
        self.uow = uow
        self.fine_review = review
        self.commits = 0
        self._journal = journal

    def commit(self) -> None:
        self.commits += 1
        self._journal.append("COMMIT")


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.tenant_id = TENANT
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


class _ScreenStub:
    """Ekranın setter API-sinin sahtəsi — Qt olmadan."""

    theme: Any = None

    def __init__(self) -> None:
        self.option_sets: list[list[dict[str, str]]] = []
        self.period_sets: list[tuple[list[dict[str, str]], str]] = []
        self.group_sets: list[list[FineReviewGroup]] = []
        self.summaries: list[str] = []
        self.notices: list[str] = []
        self.errors: list[str] = []
        self.decisions: dict[str, tuple[str, str]] = {}

    def set_decision_options(self, options: list[dict[str, str]]) -> None:
        self.option_sets.append(options)

    def set_periods(self, periods: list[dict[str, str]], *, selected: str = "") -> None:
        self.period_sets.append((periods, selected))

    def set_groups(self, groups: list[FineReviewGroup], *, summary_text: str = "") -> None:
        self.group_sets.append(list(groups))
        self.summaries.append(summary_text)

    def set_decision(self, fine_id: str, *, decision: str, reason: str = "") -> None:
        self.decisions[fine_id] = (decision, reason)

    def show_notice(self, message: str) -> None:
        self.notices.append(message)

    def show_form_error(self, message: str) -> None:
        self.errors.append(message)


class _Controller(MonthlyFineReviewController):
    """Modal `exec()` hadisə dövrəsini bloklayır — testdə cavab əvəzlənir."""

    def __init__(self, context: Any, actor: Employee, *, confirm: bool = True) -> None:
        super().__init__(context, actor)
        self.answer = confirm
        self.summaries: list[PublishSummary] = []
        self.reason = "Kamera nasazlığı — sətir səhv yazılıb"

    def _confirm(self, screen: Any, summary: PublishSummary) -> bool:
        self.summaries.append(summary)
        return self.answer

    def _ask_reason(self, screen: Any) -> str | None:
        return self.reason


def _build(
    fines: list[Fine],
    *,
    confirm: bool = True,
    publish_error: Exception | None = None,
) -> tuple[_Controller, _ScreenStub, _Session, _Context, _FinesRepo, _SpyReview]:
    journal: list[str] = []
    repo = _FinesRepo(fines, journal)
    use_case = MonthlyFineReviewUseCase(
        clock=FakeClock(PUBLISHED_AT),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        notifier=RecordingNotifier(),  # type: ignore[arg-type]
        limits=FakeSystemLimits(),  # type: ignore[arg-type]
        review_batches=RecordingFineReviewBatches(),  # type: ignore[arg-type]
    )
    review = _SpyReview(use_case, publish_error)
    session = _Session(_Uow(repo, _Connection()), review, journal)
    context = _Context(session)
    controller = _Controller(context, _publisher(), confirm=confirm)
    return controller, _ScreenStub(), session, context, repo, review


def _payload(rows: list[FineReviewRow], **overrides: tuple[str, str]) -> list[dict[str, str]]:
    """Ekranın yaydığı yük: hər sətir üçün qərar + səbəb."""
    default = ReviewDecision.KEEP.value
    return [
        {
            "fine_id": row.fine_id,
            "decision": overrides.get(row.fine_id, (default, ""))[0],
            "reason": overrides.get(row.fine_id, (default, ""))[1],
        }
        for row in rows
    ]


def _rows(screen: _ScreenStub) -> list[FineReviewRow]:
    return [row for group in screen.group_sets[-1] for row in group.rows]


# --------------------------------------------------------------------------- #
# 1. Menyu: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (CLAUDE.md §3, §5)
# --------------------------------------------------------------------------- #


def test_menu_entry_is_gated_by_the_use_case_flag() -> None:
    """Maddə use case-in FAKTİKİ flag-inə bağlıdır, təxmin edilmiş ada yox."""
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "fine_review")
    assert entry.required_flag == PUBLISH_FINES_FLAG
    # Cərimə modulu söndürüləndə göndəriləcək bir şey də qalmır.
    assert entry.feature_module == MODULE_FINES


def test_employee_without_the_flag_does_not_see_the_entry() -> None:
    """Flag-siz istifadəçidə maddə RENDER OLUNMUR (boz deyil, YOX)."""
    registry = build_default_registry()
    now = PUBLISHED_AT
    assert registry.is_visible("fine_review", _seller(), now=now) is False
    assert registry.is_visible("fine_review", _publisher(), now=now) is True


def test_the_entry_sits_between_fine_entry_and_appeals() -> None:
    """Cərimənin ömür dövrü naviqasiyada ardıcıl görünür: yaz → göndər → etiraz."""
    orders = {entry.key: entry.order for entry in DEFAULT_ENTRIES}
    assert orders["fines"] < orders["fine_review"] < orders["fine_appeals"]


def test_publish_flag_is_structurally_denied_to_camera_roles() -> None:
    """Anti-fraud (CLAUDE.md §5): cəriməni YARADAN onu TƏSDİQ EDƏ BİLMƏZ.

    Qayda İKİ yerdədir — domendə (`PermissionFlag.assert_grantable_to`) və DB
    trigger-ində. Menyu maddəsi məhz bu flag-ə bağlandığı üçün kamera-tipli
    rol ekranı heç bir yolla görə bilmir.
    """
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    assert f"excludes_camera_role = TRUE WHERE code = '{PUBLISH_FINES_FLAG}'" in schema

    flag = PermissionFlag(
        code=PUBLISH_FINES_FLAG,
        category="KAMERA_CERIME",
        is_anti_fraud=True,
        excludes_camera_role=True,
    )
    with pytest.raises(AuthorizationError, match="kamera-tipli"):
        flag.assert_grantable_to(SystemRole.ADMIN, is_camera_type_role=True)


# --------------------------------------------------------------------------- #
# 2. Kompozisiya reqressiyası — boşluğun KÖKÜ məhz bu idi
# --------------------------------------------------------------------------- #


def test_session_exposes_the_monthly_fine_review_use_case() -> None:
    """`Session`-da sahə YOXDURSA, use case-i çağıracaq bir yol da yoxdur."""
    field = Session.__dataclass_fields__.get("fine_review")
    assert field is not None, "`Session.fine_review` silinib — zəncir yenidən qırılardı"
    assert field.type == "MonthlyFineReviewUseCase"


def test_build_session_actually_constructs_the_use_case() -> None:
    """Sahə elan etmək kifayət deyil — `_build_session` onu QURMALIDIR."""
    tree = ast.parse(COMPOSITION.read_text(encoding="utf-8"))
    keywords: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_session":
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "Session"
                ):
                    keywords = {kw.arg for kw in call.keywords if kw.arg is not None}
    assert "fine_review" in keywords


# --------------------------------------------------------------------------- #
# 3. Oxu yolu
# --------------------------------------------------------------------------- #


def test_refresh_groups_fines_by_branch_with_subtotals() -> None:
    controller, screen, _session, _context, _repo, _review = _build(
        [_fine(store_id=STORE_A), _fine(store_id=STORE_A, amount="40.00"), _fine(store_id=STORE_B)]
    )

    controller.refresh(screen)  # type: ignore[arg-type]

    groups = screen.group_sets[-1]
    assert [group.store for group in groups] == ["Bellona 28 May", "İstikbal Xətai"]
    assert groups[0].count_text == "2 cərimə"
    assert groups[0].total_text == "65 ₼"
    assert screen.summaries[-1] == "3 cərimə · 2 filial · 90 ₼ nəşr gözləyir"


def test_oldest_pending_period_is_selected_by_default() -> None:
    """Gecikmiş nəşr işçinin etiraz pəncərəsini də gecikdirir — ən köhnə ay birinci."""
    late = _fine()
    later = _fine()
    later.issued_at = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    controller, screen, _session, _context, _repo, _review = _build([late, later])

    controller.refresh(screen)  # type: ignore[arg-type]

    periods, selected = screen.period_sets[-1]
    assert [period["key"] for period in periods] == ["2026-07", "2026-08"]
    assert selected == PERIOD
    assert [period["label"] for period in periods] == ["İyul 2026", "Avqust 2026"]
    # Yalnız seçilmiş dövrün sətirləri göstərilir.
    assert len(_rows(screen)) == 1


def test_empty_period_is_a_positive_empty_state_not_an_error() -> None:
    """Nəşr gözləyən cərimə olmaması NORMAL haldır — qırmızı ekran YOX."""
    controller, screen, _session, _context, _repo, _review = _build([])

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.group_sets[-1] == []
    assert screen.errors == []
    assert screen.period_sets[-1][0] == []


def test_unreadable_list_does_not_crash_the_screen() -> None:
    class _Broken(_FinesRepo):
        def pending_review_periods(self, tenant_id: Any) -> list[str]:
            raise RuntimeError("baza əlçatmazdır")

    journal: list[str] = []
    repo = _Broken([], journal)
    session = _Session(
        _Uow(repo, _Connection()),
        _SpyReview(
            MonthlyFineReviewUseCase(
                clock=FakeClock(PUBLISHED_AT),  # type: ignore[arg-type]
                audit=RecordingAudit(),  # type: ignore[arg-type]
                notifier=RecordingNotifier(),  # type: ignore[arg-type]
                limits=FakeSystemLimits(),  # type: ignore[arg-type]
                review_batches=RecordingFineReviewBatches(),  # type: ignore[arg-type]
            )
        ),
        journal,
    )
    controller = _Controller(_Context(session), _publisher())
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.group_sets[-1] == []
    assert screen.errors[-1] == LIST_READ_FAILED


def test_automatic_fine_shows_its_source_and_missing_evidence() -> None:
    """Kataloq növü olmayan cərimə "—" yazılmır: mənbəsi göstərilir."""
    from src.domain.value_objects.identifiers import LeaveRequestId

    auto = Fine(
        fine_id=FineId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=WORKER,
        store_id=STORE_A,
        source=FineSource.AUTO_DELAY,
        amount=Money.parse("15.00"),
        issued_at=ISSUED,
        leave_request_id=LeaveRequestId(uuid.uuid4()),
    )
    auto.discard_events()
    controller, screen, _session, _context, _repo, _review = _build([auto])

    controller.refresh(screen)  # type: ignore[arg-type]

    row = _rows(screen)[0]
    assert row.fine_type == "Gecikmə (avtomatik)"
    assert row.operator == "Sistem (avtomatik)"
    assert row.has_evidence is False


# --------------------------------------------------------------------------- #
# 4. Təsdiq modalı — nəşr geri qaytarıla bilmir
# --------------------------------------------------------------------------- #


def test_publish_asks_for_confirmation_with_the_real_numbers() -> None:
    controller, screen, _session, _context, _repo, _review = _build(
        [_fine(store_id=STORE_A), _fine(store_id=STORE_B, amount="40.00")]
    )
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_publish(screen, _payload(_rows(screen)))  # type: ignore[arg-type]

    summary = controller.summaries[-1]
    assert summary == PublishSummary(
        period_text="İyul 2026",
        publish_count=2,
        discard_count=0,
        store_count=2,
        amount_text="65 ₼",
    )


def test_cancelled_confirmation_publishes_nothing() -> None:
    """Ləğv → nə use case çağırılır, nə sətir yazılır, nə commit olunur."""
    controller, screen, session, context, repo, review = _build([_fine(), _fine()], confirm=False)
    controller.refresh(screen)  # type: ignore[arg-type]
    opened_before = context.opened

    controller._on_publish(screen, _payload(_rows(screen)))  # type: ignore[arg-type]

    assert review.calls == []
    assert repo.saved == []
    assert session.commits == 0
    # Sessiya belə açılmır: təsdiq verilməyibsə bazaya toxunmuruq.
    assert context.opened == opened_before
    assert all(fine.status is FineStatus.PENDING_REVIEW for fine in repo.fines)


# --------------------------------------------------------------------------- #
# 5. Yazı yolu — TƏK tranzaksiya
# --------------------------------------------------------------------------- #


def test_publish_calls_publish_batch_once_with_the_exact_arguments() -> None:
    controller, screen, session, _context, repo, review = _build([_fine(), _fine()])
    controller.refresh(screen)  # type: ignore[arg-type]
    rows = _rows(screen)

    controller._on_publish(screen, _payload(rows))  # type: ignore[arg-type]

    assert len(review.calls) == 1, "Dəst TƏK çağırışdadır — filial-filial göndərmə YOXDUR"
    call = review.calls[0]
    assert call["tenant_id"] == TENANT
    assert call["review_month"] == PERIOD
    assert set(call["fines"]) == {fine.id for fine in repo.fines}
    assert [decision.fine_id for decision in call["decisions"]] == [
        FineId(uuid.UUID(row.fine_id)) for row in rows
    ]
    assert all(decision.decision is ReviewDecision.KEEP for decision in call["decisions"]), (
        "Qərar verilməmiş sətir DEFOLT olaraq 'Saxla'dır"
    )
    assert session.commits == 1, "commit UNUDULSA bütün nəşr rollback olardı"


def test_every_write_lands_before_the_single_commit() -> None:
    """Qismən nəşr MÜMKÜN DEYİL: bütün `save()`-lar TƏK commit-dən əvvəldədir.

    Jurnal sırası nəşrin atomluğunun birbaşa sübutudur — sətirlər arasında
    ikinci bir commit olsaydı, bəzi işçilər cəriməni digərlərindən əvvəl
    görərdi (use case başlığı: "bir anda görünür" TEXNİKİ tələbdir).
    """
    fines = [_fine(), _fine(store_id=STORE_B)]
    controller, screen, session, _context, repo, _review = _build(fines)
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_publish(screen, _payload(_rows(screen)))  # type: ignore[arg-type]

    journal = session._journal
    assert journal.count("COMMIT") == 1
    assert journal[-1] == "COMMIT"
    assert len([entry for entry in journal if entry.startswith("SAVE:")]) == len(fines)
    assert len(repo.saved) == len(fines)


def test_publish_rereads_the_list_and_published_fines_disappear() -> None:
    controller, screen, _session, _context, repo, _review = _build([_fine(), _fine()])
    controller.refresh(screen)  # type: ignore[arg-type]
    assert len(_rows(screen)) == 2

    controller._on_publish(screen, _payload(_rows(screen)))  # type: ignore[arg-type]

    assert repo.list_calls >= 3, "Nəşr üçün bir oxu + nəşrdən sonra yenidən oxu"
    assert screen.group_sets[-1] == [], "Nəşr olunan cərimə icmaldan ÇIXIR"
    assert screen.notices[-1] == "2 cərimə bütün filiallara göndərildi."


def test_discarded_fines_are_reported_separately() -> None:
    controller, screen, _session, _context, repo, _review = _build([_fine(), _fine()])
    controller.refresh(screen)  # type: ignore[arg-type]
    rows = _rows(screen)
    reason = "Kamera nasazlığı — sətir səhv yazılıb"

    controller._on_publish(  # type: ignore[arg-type]
        screen,
        _payload(rows, **{rows[0].fine_id: (ReviewDecision.DISCARD.value, reason)}),
    )

    statuses = {fine.status for fine in repo.fines}
    assert statuses == {FineStatus.PUBLISHED, FineStatus.REVERSED}
    assert screen.notices[-1] == "1 cərimə bütün filiallara göndərildi, 1 cərimə silindi."


def test_permission_error_does_not_crash_and_publishes_nothing() -> None:
    """Flag-siz aktor ekranı açsa (deep link), səbəb AÇIQ yazılır."""
    denied = FineReviewError(
        "flag yoxdur", user_message="Cərimələri göndərmək səlahiyyətiniz yoxdur."
    )
    controller, screen, session, _context, repo, _review = _build([_fine()], publish_error=denied)
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_publish(screen, _payload(_rows(screen)))  # type: ignore[arg-type]

    assert screen.errors[-1] == "Cərimələri göndərmək səlahiyyətiniz yoxdur."
    assert session.commits == 0
    assert repo.saved == []
    assert all(fine.status is FineStatus.PENDING_REVIEW for fine in repo.fines)


def test_unexpected_failure_says_that_nothing_was_published() -> None:
    """Qismən uğur illüziyası YARADILMIR — "HEÇ BİRİ" sözü mesajdadır."""
    controller, screen, session, _context, repo, _review = _build(
        [_fine()], publish_error=RuntimeError("bağlantı qırıldı")
    )
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_publish(screen, _payload(_rows(screen)))  # type: ignore[arg-type]

    assert screen.errors[-1] == PUBLISH_FAILED
    assert "HEÇ BİRİ" in PUBLISH_FAILED
    assert session.commits == 0
    assert repo.saved == []


def test_a_fine_added_after_the_screen_loaded_aborts_the_whole_batch() -> None:
    """Görünməmiş cərimə SÜKUTLA nəşr olunmur.

    `publish_batch` `fines` sözlüyündəki BÜTÜN gözləyən sətirləri açır
    (qərarsız sətir "Saxla" sayılır), yəni yeni yazılmış cərimə istifadəçinin
    baxmadığı halda işçiyə görünərdi. Ona görə dəst uyğun gəlmirsə heç nə
    yazılmır.
    """
    controller, screen, session, _context, repo, review = _build([_fine()])
    controller.refresh(screen)  # type: ignore[arg-type]
    payload = _payload(_rows(screen))
    repo.fines.append(_fine(store_id=STORE_B))  # kamera operatoru yeni cərimə yazdı

    controller._on_publish(screen, payload)  # type: ignore[arg-type]

    assert review.calls == []
    assert session.commits == 0
    assert repo.saved == []
    assert screen.errors[-1] == LIST_CHANGED
    assert len(_rows(screen)) == 2, "Siyahı yenidən oxundu — istifadəçi təzə dəsti görür"


def test_empty_payload_never_reaches_the_use_case() -> None:
    controller, screen, session, _context, _repo, review = _build([])
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_publish(screen, [])  # type: ignore[arg-type]

    assert review.calls == []
    assert controller.summaries == [], "Boş dəst üçün təsdiq modalı AÇILMIR"
    assert screen.errors[-1] == EMPTY_BATCH
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# 6. Sətir və qrup qərarları
# --------------------------------------------------------------------------- #


def test_decision_options_come_from_the_enum_not_from_the_screen() -> None:
    options = decision_options()
    assert [option["code"] for option in options] == [item.value for item in ReviewDecision]
    assert options[0]["code"] == ReviewDecision.KEEP.value, "Birinci variant DEFOLTDUR"
    assert [option["label"] for option in options] == ["Saxla", "Sil"]


def test_discard_decision_asks_for_a_reason_before_touching_the_screen() -> None:
    controller, screen, _session, _context, _repo, _review = _build([_fine()])
    controller.refresh(screen)  # type: ignore[arg-type]
    fine_id = _rows(screen)[0].fine_id

    controller._on_decision(screen, fine_id, ReviewDecision.DISCARD.value)  # type: ignore[arg-type]

    assert screen.decisions[fine_id] == (ReviewDecision.DISCARD.value, controller.reason)
    assert len(controller.reason) >= MIN_DISCARD_REASON_LENGTH


def test_cancelled_reason_leaves_the_row_untouched() -> None:
    controller, screen, _session, _context, _repo, _review = _build([_fine()])
    controller.refresh(screen)  # type: ignore[arg-type]
    controller.reason = ""  # `_ask_reason` "imtina" cavabını təqlid edir
    controller._ask_reason = lambda screen: None  # type: ignore[assignment, method-assign]
    fine_id = _rows(screen)[0].fine_id

    controller._on_decision(screen, fine_id, ReviewDecision.DISCARD.value)  # type: ignore[arg-type]

    assert screen.decisions == {}


def test_unknown_decision_code_never_reaches_the_screen() -> None:
    controller, screen, _session, _context, _repo, _review = _build([_fine()])
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_decision(screen, _rows(screen)[0].fine_id, "HAMISI")  # type: ignore[arg-type]

    assert screen.decisions == {}
    assert screen.errors[-1] == "Qərar variantı tanınmadı."


def test_group_decision_applies_only_to_that_branch() -> None:
    """Toplu sürətləndirici: 21 filial × onlarla sətir əl ilə keçilməzdir."""
    controller, screen, _session, _context, _repo, _review = _build(
        [_fine(store_id=STORE_A), _fine(store_id=STORE_A), _fine(store_id=STORE_B)]
    )
    controller.refresh(screen)  # type: ignore[arg-type]
    groups = {group.store: group for group in screen.group_sets[-1]}
    target = groups["Bellona 28 May"]

    controller._on_group_decision(  # type: ignore[arg-type]
        screen, target.key, ReviewDecision.DISCARD.value
    )

    assert set(screen.decisions) == {row.fine_id for row in target.rows}
    assert all(
        value == (ReviewDecision.DISCARD.value, controller.reason)
        for value in screen.decisions.values()
    )


# --------------------------------------------------------------------------- #
# 7. UÇDAN-UCA — sınıq zəncirin bağlandığının sübutu
# --------------------------------------------------------------------------- #


def test_pending_fine_becomes_visible_to_the_employee_after_publish() -> None:
    """`PENDING_REVIEW` → nəşr → `PUBLISHED` → işçi onu GÖRÜR.

    Zəncirin bütün halqaları: cərimə görünməz doğulur, ekran onu icmalda
    göstərir, TƏK düymə use case-i çağırır, sətir yazılır, `visible_to_
    employee` artıq onu qaytarır və etiraz pəncərəsi AÇILIR (`appeal_window_
    closes_at` yalnız nəşrdə dolur — onsuz export şərti heç vaxt ödənmirdi).
    """
    fine = _fine()
    assert fine.is_visible_to_employee is False
    assert fine.appeal_window_closes_at is None

    controller, screen, _session, _context, repo, _review = _build([fine])
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_publish(screen, _payload(_rows(screen)))  # type: ignore[arg-type]

    assert fine.status is FineStatus.PUBLISHED
    assert fine.is_visible_to_employee is True
    assert fine.published_at == PUBLISHED_AT
    assert fine.appeal_window_closes_at is not None
    assert MonthlyFineReviewUseCase.visible_to_employee([fine]) == [fine]
    assert repo.saved == [fine], "Status yaddaşda qalsaydı, sətir köhnə statusda olardı"


# --------------------------------------------------------------------------- #
# 8. Maket ↔ canlı yol paritetı (CLAUDE.md §6)
# --------------------------------------------------------------------------- #


def test_preview_groups_have_the_same_shape_as_the_live_ones() -> None:
    """Maket `FineReviewGroup`/`FineReviewRow` sahələrini bir-bir doldurur."""
    for key, store, count_text, total_text, rows in preview_data.FINE_REVIEW_GROUPS:
        group = FineReviewGroup(
            key=key,
            store=store,
            count_text=count_text,
            total_text=total_text,
            rows=tuple(FineReviewRow(*row) for row in rows),
        )
        assert group.rows
        assert all(len(row) == len(FineReviewRow._fields) for row in rows)


def test_live_path_produces_the_same_named_tuples() -> None:
    controller, screen, _session, _context, _repo, _review = _build([_fine()])

    controller.refresh(screen)  # type: ignore[arg-type]

    group = screen.group_sets[-1][0]
    assert isinstance(group, FineReviewGroup)
    assert isinstance(group.rows[0], FineReviewRow)


def test_preview_period_keys_match_the_live_format() -> None:
    """Maketdəki `YYYY-MM` açarları canlı yolun dövr formatı ilə eynidir."""
    assert preview_data.FINE_REVIEW_PERIODS[0]["key"] == preview_data.FINE_REVIEW_SELECTED_PERIOD
    for period in preview_data.FINE_REVIEW_PERIODS:
        year, month = period["key"].split("-")
        assert len(year) == 4
        assert 1 <= int(month) <= 12


# --------------------------------------------------------------------------- #
# 9. Ekranın ÖZÜ — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _screen(theme: Any) -> Any:
    from src.presentation.screens.fine_review import MonthlyFineReviewScreen

    screen = MonthlyFineReviewScreen(theme)
    screen.set_decision_options(decision_options())
    return screen


def _preview_groups() -> list[FineReviewGroup]:
    return [
        FineReviewGroup(
            key=key,
            store=store,
            count_text=count_text,
            total_text=total_text,
            rows=tuple(FineReviewRow(*row) for row in rows),
        )
        for key, store, count_text, total_text, rows in preview_data.FINE_REVIEW_GROUPS
    ]


def _labels(widget: Any) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in widget.findChildren(QLabel)]


@requires_qt
def test_empty_state_is_positive_not_an_empty_table(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.fine_review import EMPTY_TITLE

    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_groups([])

    assert screen.switcher().current_state() == "empty"
    assert EMPTY_TITLE in _labels(screen.switcher())
    assert screen.publish_button().isEnabled() is False


@requires_qt
def test_groups_start_collapsed_so_21_branches_stay_readable(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_groups(_preview_groups(), summary_text=preview_data.FINE_REVIEW_SUMMARY)

    layout = screen.groups_layout()
    assert layout.count() == len(preview_data.FINE_REVIEW_GROUPS)
    from src.presentation.widgets.data_table import DataTable

    tables = screen.findChildren(DataTable)
    assert tables and all(not table.isVisible() for table in tables)
    # Alt-cəmlər açmadan görünür — icmalın ilk sualı budur.
    assert "3 cərimə · 90 ₼" in _labels(layout.itemAt(0).widget())


@requires_qt
def test_single_publish_button_emits_every_row_with_the_default_decision(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _screen(theme)
    qtbot.addWidget(screen)
    screen.set_groups(_preview_groups())

    emitted: list[list[dict[str, str]]] = []
    screen.publish_requested.connect(emitted.append)
    screen.publish_button().click()

    assert len(emitted) == 1
    payload = emitted[0]
    assert [row["fine_id"] for row in payload] == [
        row.fine_id for group in _preview_groups() for row in group.rows
    ]
    assert {row["decision"] for row in payload} == {ReviewDecision.KEEP.value}


@requires_qt
def test_discard_decision_is_visible_in_the_row(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _screen(theme)
    qtbot.addWidget(screen)
    screen.set_groups(_preview_groups())
    fine_id, reason = preview_data.FINE_REVIEW_DISCARDED

    screen.set_decision(fine_id, decision=ReviewDecision.DISCARD.value, reason=reason)

    chip = screen._decision_chips[fine_id]
    assert chip.text() == "Sil"
    assert chip.property("chip") == "danger"
    assert chip.toolTip() == reason
    # Geri qayıtma yolu YALNIZ dəyişdirilmiş sətirdə qurulur/görünür.
    # `isHidden()` işlədilir, `isVisibleTo()` YOX: qruplar yığılmış başlayır,
    # yəni valideyn cədvəl gizlidir və "görünən" heç bir sətir olmazdı.
    assert screen._revert_buttons[fine_id].isHidden() is False
    others = [key for key in screen._revert_buttons if key != fine_id]
    assert all(screen._revert_buttons[key].isHidden() for key in others)
    payload = {row["fine_id"]: row for row in screen.decisions()}
    assert payload[fine_id]["reason"] == reason


@requires_qt
def test_preview_path_uses_the_same_setters_as_the_live_one(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Maket yolu (`preview_screens.populate`) canlı yolla EYNİ imzadadır.

    Qapı CLAUDE.md §6-nın birbaşa tələbidir: maket öz ad məkanını qursaydı,
    uyğunsuzluq yalnız istehsalatda üzə çıxardı.
    """
    from src.presentation import preview_screens

    screen = _screen(theme)
    qtbot.addWidget(screen)

    preview_screens.populate("fine_review", screen)

    assert screen.groups_layout().count() == len(preview_data.FINE_REVIEW_GROUPS)
    assert screen.selected_period() == preview_data.FINE_REVIEW_SELECTED_PERIOD
    assert screen.publish_button().isEnabled() is True
    discarded_id, reason = preview_data.FINE_REVIEW_DISCARDED
    payload = {row["fine_id"]: row for row in screen.decisions()}
    assert payload[discarded_id] == {
        "fine_id": discarded_id,
        "decision": ReviewDecision.DISCARD.value,
        "reason": reason,
    }


@requires_qt
def test_period_change_emits_the_period_key_only_on_user_action(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Proqramla doldurma siqnal YAYMIR — əks halda sonsuz yenidən oxu olardı."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    emitted: list[str] = []
    screen.period_selected.connect(emitted.append)
    screen.set_periods(
        [dict(period) for period in preview_data.FINE_REVIEW_PERIODS],
        selected="2026-08",
    )
    assert emitted == []
    assert screen.selected_period() == "2026-08"

    screen._period.setCurrentIndex(0)
    assert emitted == ["2026-07"]


@requires_qt
def test_confirm_dialog_shows_the_numbers_and_defaults_to_cancel(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Təsdiq modalı MƏCBURİDİR və Enter təsadüfən nəşr etməməlidir."""
    from src.presentation.screens.fine_review import (
        IRREVERSIBLE_NOTE,
        PublishConfirmDialog,
    )

    dialog = PublishConfirmDialog(
        theme,
        summary=PublishSummary(
            period_text="İyul 2026",
            publish_count=42,
            discard_count=3,
            store_count=21,
            amount_text="1 240 ₼",
        ),
    )
    qtbot.addWidget(dialog)

    text = " ".join(_labels(dialog))
    assert "42" in text and "21" in text and "1 240 ₼" in text
    assert "3 cərimə silinəcək" in text, "Silinən sətirlərin sayı da göstərilir"
    assert IRREVERSIBLE_NOTE in _labels(dialog)
    assert dialog.confirm_button().isDefault() is False

    confirmed: list[bool] = []
    dialog.confirmed.connect(lambda: confirmed.append(True))
    dialog.confirm_button().click()
    assert confirmed == [True]
