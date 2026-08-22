"""QA-FULL FAZA 6 — Sürətli təkrar-klik (yarış şəraiti) stress sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ 20+ ARDICIL KLİK, 2 YOX
──────────────────────────────────────────────────────────────────────────────
Mövcud e2e fayllarında (`test_fine_entry_screen_e2e.py`,
`test_fine_appeal_inbox_screen_e2e.py`, `test_shift_swap_screen_e2e.py`)
ikiqat-klik artıq sınanıb — bu fayl onları TƏKRARLAMIR, ölçünü 20+ ardıcıl
klikə QƏDƏR aparır ki, döngədə yığılan vəziyyət (say, siyahı, `monotonic`
pəncərəsi) uzun sıra üzərində sınana bilsin. Bu kontrollerlərin HAMISI
sinxrondur (fon sapı YOXDUR — `fine_entry` istisna, o da yalnız sübut
yükləməsi üçün `InlineExecutor` işlədir), yəni Qt hadisə dövrəsi hər kliki
TAM İCRA EDƏNƏ qədər növbətini gözlədir. Ona görə burada ölçülən HƏQİQİ
ip-üstü yarış deyil (tək istifadəçinin proqramatik dövrəsi paralellik
yaratmır) — ölçülən budur: BİR istifadəçinin sürətli-təkrar kliki server
tərəfi domen qoruyucusuna (və ya `monotonic` pəncərəsinə) DÜZGÜN uyğunlaşırmı,
20-ci klikdə də 2-ci klikdəki qədər sabit qalırmı.

──────────────────────────────────────────────────────────────────────────────
NƏTİCƏ (əvvəlcədən xülasə, aşağıda hər test öz sübutunu verir)
──────────────────────────────────────────────────────────────────────────────
* `fine_entry` — pəncərə daxilində 20 klik EYNİ `idempotency_key`-i saxlayır;
  DB-nin unikal indeksi (miqrasiya 074) real dublikatın qarşısını alır,
  bu test yalnız APLİKASİYA sürətli-yolunu (CLAUDE.md §5) ölçür.
* `open_shift` — 20 klikdən YALNIZ biri uğurla tutur, qalan 19-u domen
  xətası ilə RƏDD edilir, ÇÖKMƏ yoxdur.
* `fine_appeals` / `shift_swaps` — real domen keçidi (`_require_decidable`
  bənzəri) 20 klikdən YALNIZ birini yazır, qalan 19-u modalla bildirir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
FINE_TYPE_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
POSTING_ID = uuid.uuid4()
APPEAL_ID = uuid.uuid4()
FINE_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()

RAPID_CLICKS = 20


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


# --------------------------------------------------------------------------- #
# 1. `fine_entry` — 20 ardıcıl klik, pəncərə daxilində eyni açar
# --------------------------------------------------------------------------- #


class _FeRow(dict):
    pass


class _FeConnection:
    def __init__(self, stores: dict[str, str], employees: dict[str, tuple[str, str]]) -> None:
        self._stores = stores
        self._employees = employees
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _FeConnection:
        self._last_sql = sql
        return self

    def fetchall(self) -> list[_FeRow]:
        if "FROM stores" in self._last_sql:
            return [_FeRow(id=sid, name=name) for sid, name in self._stores.items()]
        if "FROM employees" in self._last_sql:
            return [
                _FeRow(id=eid, first_name=first, last_name=last)
                for eid, (first, last) in self._employees.items()
            ]
        return []  # pragma: no cover - naməlum sorğu


class _FeCameraAssignments:
    """`_refresh()` `screen_data.py::_fines` çağırır — o, bu repo-nu gözləyir.

    Boş siyahı qaytarır: operatorun izlədiyi kamera-mağaza əlaqəsi bu testin
    mövzusu deyil, sadəcə "Cərimələr" ekranının sükutla boş qalması kifayətdir.
    """

    def stores_for_operator(self, _operator_id: Any) -> list[Any]:
        return []


class _FeUow:
    def __init__(self, stores: dict[str, str], employees: dict[str, tuple[str, str]]) -> None:
        self.connection = _FeConnection(stores, employees)

    @property
    def fines(self) -> Any:
        return self

    def mark_evidence_pending(self, _fine_id: Any) -> None:
        return None

    def repository(self, name: str) -> Any:
        if name == "camera_assignments":
            return _FeCameraAssignments()
        raise NotImplementedError(name)  # pragma: no cover - testdə lazım deyil


class _ManualFines:
    def __init__(self, *, fine_types: list[Any], allowed_stores: list[Any]) -> None:
        self._fine_types = fine_types
        self._allowed_stores = allowed_stores
        self.issued: list[dict[str, Any]] = []

    def selectable_fine_types(self, _tenant_id: Any) -> list[Any]:
        return list(self._fine_types)

    def allowed_stores(self, _operator: Any) -> list[Any]:
        return list(self._allowed_stores)

    def issue(self, **kwargs: Any) -> Any:
        self.issued.append(kwargs)
        return type("_Fine", (), {"id": kwargs.get("fine_id")})()


class _FeSession:
    def __init__(
        self,
        manual_fines: _ManualFines,
        stores: dict[str, str],
        employees: dict[str, tuple[str, str]],
    ) -> None:
        self.tenant_id = TENANT
        self.manual_fines = manual_fines
        self.uow = _FeUow(stores, employees)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _FeContext:
    def __init__(self) -> None:
        self._stores = {str(STORE_ID): "Mərkəz"}
        self._employees = {str(EMPLOYEE_ID): ("Aygün", "Məmmədova")}
        self.manual_fines = _ManualFines(fine_types=[_fine_type()], allowed_stores=[STORE_ID])
        self.tenant_id = TENANT
        self.evidence = _FeEvidenceQueue()
        self.upload_runs = 0
        self.sessions: list[_FeSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _FeSession(self.manual_fines, self._stores, self._employees)
        self.sessions.append(created)
        yield created

    def evidence_queue(self) -> _FeEvidenceQueue:
        return self.evidence

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _FeEvidenceQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self._counter = 0

    def enqueue(self, **kwargs: Any) -> str:
        self._counter += 1
        self.enqueued.append(kwargs)
        return f"queue-entry-{self._counter}"


def _fine_type() -> Any:
    from decimal import Decimal

    from src.domain.value_objects.catalogs import FineType
    from src.domain.value_objects.money import Money

    return FineType(
        name="Gecikmə",
        tenant_id=TENANT,
        fine_type_id=FINE_TYPE_ID,
        standard_amount=Money(Decimal("25")),
    )


class _Actor:
    id = ACTOR_ID


def _build_fine_entry(theme: Any, qtbot: Any, context: Any) -> tuple[Any, Any]:
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.fine_entry import FineEntryController
    from src.presentation.screens.group_b import FineEntryScreen

    controller = FineEntryController(context, _Actor(), executor=InlineExecutor())
    fine_types, stores, employees = controller.options()
    screen = FineEntryScreen(theme, fine_types=fine_types, stores=stores, employees=employees)
    qtbot.addWidget(screen)
    controller.attach(screen)
    return screen, controller


@requires_qt
def test_twenty_rapid_clicks_on_fine_entry_within_the_dedupe_window_reuse_a_single_key(
    qtbot, theme, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """20 ardıcıl klik, `monotonic()` sabit — hamısı EYNİ `idempotency_key`.

    APLİKASİYA qatı hər klikdə YENİ `manual_fines.issue()` çağırışı göndərir
    (bax fayl başlığı) — real toqquşmanın qarşısını `uq_fines_manual_camera_
    idempotency_key` (miqrasiya 074) alır. Burada ölçülən: 20-ci klikdə də
    açar 1-ci klikdəkindən FƏRQLƏNMİR, yəni pəncərə məntiqi uzun sıra üzərində
    deqradasiya OLMUR (məs. `_recent_idempotency`-nin hər yeniləməsi vaxtı
    irəli sürükləyib pəncərədən erkən çıxarmır).
    """
    from src.presentation.controllers import fine_entry as fine_entry_module

    clock = {"t": 0.0}
    monkeypatch.setattr(fine_entry_module, "monotonic", lambda: clock["t"])

    context = _FeContext()
    screen, _controller = _build_fine_entry(theme, qtbot, context)
    screen._type.set_text("Gecikmə")
    screen._store.set_text("Mərkəz")
    screen._employee.set_text("Aygün Məmmədova")
    photo = tmp_path / "subut.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")
    screen._photo.set_file(str(photo))

    for i in range(RAPID_CLICKS):
        clock["t"] = i * 0.1  # 20 klik, cəmi 1.9 saniyə — pəncərədən (10s) çox uzaqda deyil
        _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert len(context.manual_fines.issued) == RAPID_CLICKS
    keys = {issued["idempotency_key"] for issued in context.manual_fines.issued}
    assert len(keys) == 1, "20 klik ərzində pəncərə YALNIZ bir açar saxlamalı idi"
    # HƏR uğurlu `_issue()`-dan sonra `_refresh()` AYRI (oxuyan, commit ETMƏYƏN)
    # sessiya açır (bax `fine_entry.py::_refresh`) — ona görə `context.sessions`
    # yazı VƏ oxu sessiyalarının qarışığıdır, `all()` YOX, YAZI sayı yoxlanır.
    committed = sum(1 for s in context.sessions if s.committed)
    assert committed == RAPID_CLICKS, "hər 20 kliyin YAZI sessiyası commit olmalı idi"


@requires_qt
def test_rapid_clicks_straddling_the_dedupe_window_boundary_rotate_keys_correctly(
    qtbot, theme, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """10 klik pəncərə İÇİNDƏ, sonra pəncərə bitir, YENİDƏN 10 klik.

    İki qrup arasında YENİ açar yaranmalıdır (bax `fine_entry.py::
    _idempotency_key_for_submission` başlığı) — əks halda tamamilə ayrı iki
    cərimə partiyası eyni DB unikal indeksinə toqquşardı.
    """
    from src.application.use_cases.fine_management import DUPLICATE_SUBMISSION_WINDOW_SECONDS
    from src.presentation.controllers import fine_entry as fine_entry_module

    clock = {"t": 0.0}
    monkeypatch.setattr(fine_entry_module, "monotonic", lambda: clock["t"])

    context = _FeContext()
    screen, _controller = _build_fine_entry(theme, qtbot, context)
    screen._type.set_text("Gecikmə")
    screen._store.set_text("Mərkəz")
    screen._employee.set_text("Aygün Məmmədova")
    photo = tmp_path / "subut.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")
    screen._photo.set_file(str(photo))

    for i in range(10):
        clock["t"] = i * 0.1
        _click(screen, "Cəriməni Qeyd Et")

    clock["t"] = DUPLICATE_SUBMISSION_WINDOW_SECONDS + 1.0
    for _i in range(10):
        clock["t"] += 0.1
        _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    keys = [issued["idempotency_key"] for issued in context.manual_fines.issued]
    first_group = set(keys[:10])
    second_group = set(keys[10:])
    assert len(first_group) == 1
    assert len(second_group) == 1
    assert first_group != second_group, "pəncərə bitəndən sonra YENİ açar yaranmalı idi"


# --------------------------------------------------------------------------- #
# 2. `open_shift` — 20 ardıcıl "Bu Növbəni Götür", YALNIZ biri uğurlu
# --------------------------------------------------------------------------- #


class _RealisticOpenShifts:
    """`SELECT ... FOR UPDATE`-in real effektini TƏQLİD edir: birinci qazanır.

    Mövcud `test_open_shift_screen_e2e.py::_OpenShifts` HƏR çağırışı sükutla
    qəbul edir — ikiqat klik test ssenarisi üçün YARARSIZDIR, çünki real
    repo tutulmuş elana İKİNCİ `claim()` üçün `OpenShiftAlreadyClaimedError`
    atır. Bu sahtə həmin sərhədi TƏQLİD edir ki, 20 klikin YALNIZ biri
    uğurlu olsun — qalanı domen xətası ilə rədd edilsin.
    """

    def __init__(self) -> None:
        self.employee_rows: list[Any] = []
        self.claims: list[dict[str, Any]] = []
        self._claimed: set[Any] = set()

    def list_for_employee(self, *, tenant_id: Any, employee: Any) -> list[Any]:
        return list(self.employee_rows)

    def claim(self, *, tenant_id: Any, employee: Any, posting_id: Any) -> None:
        if posting_id in self._claimed:
            raise KompasOSError("already claimed", user_message="Bu növbəni artıq başqası götürüb.")
        self._claimed.add(posting_id)
        self.claims.append({"posting_id": posting_id})


class _OsWorkModeRepo:
    """`_to_employee_row` → `_work_mode_name` → `uow.repository("work_modes")`.

    `None` qaytarır — `_work_mode_name` bunu artıq idarə edir (`f"#{id[:8]}"`
    yazır), yəni kataloqdan silinmiş/naməlum rejim halını TƏBİİ sınayır.
    """

    def get(self, _work_mode_id: Any) -> Any:
        return None


class _OsUow:
    def repository(self, name: str) -> Any:
        if name == "work_modes":
            return _OsWorkModeRepo()
        raise NotImplementedError(name)  # pragma: no cover - testdə lazım deyil


class _OsSession:
    def __init__(self, open_shifts: _RealisticOpenShifts) -> None:
        self.tenant_id = TENANT
        self.open_shifts = open_shifts
        self.uow = _OsUow()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _OsContext:
    def __init__(self, open_shifts: _RealisticOpenShifts) -> None:
        self._open_shifts = open_shifts
        self.sessions: list[_OsSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _OsSession(self._open_shifts)
        self.sessions.append(created)
        yield created


def _open_shift_view() -> Any:
    from src.application.use_cases.open_shift_market import OpenShiftView
    from src.domain.value_objects.identifiers import OpenShiftPostingId, StoreId, WorkModeId

    return OpenShiftView(
        posting_id=OpenShiftPostingId(POSTING_ID),
        store_id=StoreId(STORE_ID),
        shift_date=__import__("datetime").date(2026, 8, 25),
        work_mode_id=WorkModeId(uuid.uuid4()),
        status="OPEN",
        posted_by=None,
        claimed_by=None,
        created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    )


@requires_qt
def test_twenty_rapid_claims_on_the_same_open_shift_posting_only_one_succeeds(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Kiosk PC PAYLAŞILAN cihazdır (bax `open_shift.py` başlığı) — sürətli
    təkrar-klik ÇÖKMƏMƏLİDİR, HƏR KLİKDƏN sonra "yenidən oxu" işə düşməlidir."""
    from src.presentation.controllers.open_shift import EmployeeOpenShiftController
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    open_shifts = _RealisticOpenShifts()
    open_shifts.employee_rows = [_open_shift_view()]
    context = _OsContext(open_shifts)
    screen = EmployeeHomeScreen(
        theme, full_name="Aygün Məmmədova", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    screen.show()
    EmployeeOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    for _ in range(RAPID_CLICKS):
        _click(screen, "Bu Növbəni Götür")  # ÇÖKMƏMƏLİDİR

    assert len(open_shifts.claims) == 1, "20 kliklə YALNIZ bir tutma yazılmalı idi"
    assert screen._open_shift_hint.text() == "Bu növbəni artıq başqası götürüb."
    assert screen._open_shift_hint.isVisible()


# --------------------------------------------------------------------------- #
# 3. `fine_appeals` — 20 ardıcıl "Qəbul Et", real domen keçidi
# --------------------------------------------------------------------------- #


class _FaEmployees:
    def __init__(self, by_id: dict[Any, Any]) -> None:
        self._by_id = by_id

    def get(self, employee_id: Any) -> Any:
        return self._by_id.get(employee_id)


class _FaConnection:
    def __init__(self) -> None:
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _FaConnection:
        self._last_sql = sql
        return self

    def fetchone(self) -> Any:
        if "fine_types" in self._last_sql:
            return {"name": "Kassa Kəsiri"}
        if "FROM fines" in self._last_sql:
            return {"amount": "25.00"}
        return None  # pragma: no cover


class _FaUow:
    def __init__(self, employees: _FaEmployees, connection: _FaConnection) -> None:
        self.employees = employees
        self.connection = connection


class _FaLimits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default


class _FineAppeals:
    """Real `FineAppeal.approve/reject` üzərindən — 2-ci qərar domendə RƏDD edilir."""

    def __init__(self, appeals: list[Any]) -> None:
        self._by_id = {a.id: a for a in appeals}
        self.approvals: list[dict[str, Any]] = []

    def inbox(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        """`controller.refresh()` HƏR uğurlu qərardan sonra bunu çağırır."""
        return [a for a in self._by_id.values() if not a.status.is_decided]

    def approve(
        self, *, tenant_id: Any, actor: Any, appeal_id: Any, note: str, new_amount: Any = None
    ) -> Any:
        appeal = self._by_id[appeal_id]
        appeal.approve(
            decided_by=actor.id,
            decided_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
            note=note,
            new_amount=new_amount,
        )
        self.approvals.append({"appeal_id": appeal_id, "note": note})
        return appeal


class _FaSession:
    def __init__(self, appeals: _FineAppeals) -> None:
        self.tenant_id = TENANT
        self.fine_appeals = appeals
        self.limits = _FaLimits()
        self.uow = _FaUow(
            _FaEmployees({EMPLOYEE_ID: type("E", (), {"full_name": "Aygün"})()}), _FaConnection()
        )
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _FaContext:
    def __init__(self, appeals: _FineAppeals) -> None:
        self._appeals = appeals
        self.sessions: list[_FaSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _FaSession(self._appeals)
        self.sessions.append(created)
        yield created


def _appeal() -> Any:
    from src.domain.entities.appeal import FineAppeal

    return FineAppeal(
        appeal_id=APPEAL_ID,  # type: ignore[arg-type]
        tenant_id=TENANT,  # type: ignore[arg-type]
        fine_id=FINE_ID,  # type: ignore[arg-type]
        employee_id=EMPLOYEE_ID,  # type: ignore[arg-type]
        reason="Kamerada mən görünmürəm.",
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        emit_created_event=False,
    )


def _mute_modal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []

    def _fake_exec(self: Any) -> int:
        shown.append(self.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    return shown


@requires_qt
def test_twenty_rapid_approve_clicks_on_the_same_fine_appeal_only_decide_once(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.fine_appeals import FineAppealInboxController
    from src.presentation.screens.group_f import FineAppealInboxScreen

    _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _FaContext(appeals)
    screen = FineAppealInboxScreen(theme)
    qtbot.addWidget(screen)
    controller = FineAppealInboxController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(screen)
    controller.refresh(screen)

    from PySide6.QtWidgets import QPlainTextEdit

    box = screen.findChildren(QPlainTextEdit)[0]
    box.setPlainText("Sübut kifayət etmir, ləğv edilir.")

    for _ in range(RAPID_CLICKS):
        # Kart yalnız İLK klikdən sonra `refresh()` ilə sıradan çıxır, lakin
        # düymə istinadı KÖHNƏLMİŞ widget-ə göstərməyə davam edə bilər —
        # `_click` hər dəfə YENİDƏN axtarır, "Qəbul Et" tapılmasa `StopIteration`
        # ÇIXARDI (bax aşağı) — bu da ÖZÜ real bir tapıntıdır (bax test sonu).
        try:
            _click(screen, "Qəbul Et")
        except StopIteration:
            break  # kart artıq siyahıdan çıxıb, düymə YOXDUR — normal haldır

    assert len(appeals.approvals) == 1, "20 klikdən YALNIZ biri yazılmalı idi"
    # `context.sessions[0]` ilkin `controller.refresh(screen)` çağırışının OXU
    # sessiyasıdır (commit ETMİR) — YAZI sessiyasını sayına görə tapırıq.
    committed = sum(1 for s in context.sessions if s.committed)
    assert committed == 1, "YALNIZ BİR yazı sessiyası commit olmalı idi"


# --------------------------------------------------------------------------- #
# 4. `shift_swaps` — 20 ardıcıl "Təsdiqlə", eyni sorğu iki dəfə qərara bağlanmır
# --------------------------------------------------------------------------- #


class _Swaps:
    def __init__(self) -> None:
        self.decided: set[str] = set()
        self.approvals: list[dict[str, Any]] = []

    def approve(self, *, tenant_id: Any, approver: Any, request_id: Any) -> None:
        if str(request_id) in self.decided:
            raise KompasOSError("already decided", user_message="Bu sorğu artıq emal edilib.")
        self.decided.add(str(request_id))
        self.approvals.append({"request_id": request_id})


class _SsSession:
    def __init__(self, swaps: _Swaps) -> None:
        self.tenant_id = TENANT
        self.shift_swaps = swaps
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _SsContext:
    def __init__(self, swaps: _Swaps) -> None:
        self._swaps = swaps
        self.sessions: list[_SsSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _SsSession(self._swaps)
        self.sessions.append(created)
        yield created


class _SsBinder:
    """`ScreenDataBinder` sahtəsi — `refresh()`-in çağırıldığını qeyd edir."""

    populated: list[str] = []  # noqa: RUF012 - siniflər arası paylaşılan test vəziyyəti
    remaining: list[dict[str, str]] = []  # noqa: RUF012

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, screen: Any) -> None:
        _SsBinder.populated.append(key)
        screen.set_counts({"pending": len(_SsBinder.remaining)})
        screen.set_requests(list(_SsBinder.remaining))


@requires_qt
def test_twenty_rapid_approve_clicks_on_the_same_shift_swap_only_decide_once(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers import screen_data as screen_data_module
    from src.presentation.controllers.shift_swaps import ShiftSwapController
    from src.presentation.screens.group_c import ShiftSwapScreen

    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _SsBinder)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
    _SsBinder.populated = []
    _SsBinder.remaining = []

    swaps = _Swaps()
    context = _SsContext(swaps)
    screen = ShiftSwapScreen(theme)
    qtbot.addWidget(screen)
    screen.show()
    ShiftSwapController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_requests(
        [
            {
                "id": str(REQUEST_ID),
                "from_name": "Aygün Məmmədova",
                "to_name": "25.08.2026",
                "shift": "25.08.2026",
                "store": "Mərkəz",
                "status": "Gözləyir",
                "note": "Ailə tədbiri",
            }
        ]
    )

    from PySide6.QtCore import Qt

    card = next(c for c in screen._rows if c.key == str(REQUEST_ID))
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

    for _ in range(RAPID_CLICKS):
        _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR — `_current` refresh-dən sonra da qalır

    assert len(swaps.approvals) == 1, "20 klikdən YALNIZ biri qərara bağlanmalı idi"
    assert context.sessions[0].committed is True
    assert all(not s.committed for s in context.sessions[1:]), (
        "1-dən sonrakı BÜTÜN cəhdlər domen xətası ilə rədd olunub, commit olmamalı idi"
    )
