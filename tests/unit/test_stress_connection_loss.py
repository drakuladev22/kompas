"""QA-FULL FAZA 6 — Şəbəkə kəsilməsi ƏMƏLİYYAT ORTASINDA (real Qt e2e).

──────────────────────────────────────────────────────────────────────────────
DÜZƏLDİLMİŞ QÜSUR — `fine_appeals.py`/`shift_swaps.py`-in YAZI qolu `except
Exception` FALLBACK-INDAN MƏHRUM İDİ
──────────────────────────────────────────────────────────────────────────────
`fine_entry.py::_issue` və `open_shift.py::_on_claim`/`_submit`/`_on_cancel`
HƏR YAZI cəhdini İKİ qatla əhatə edir:

    except KompasOSError as error:
        screen.show_error(...)   # domen xətası — göstəriş mətni HAZIRDIR
        return
    except Exception:
        _error_log.exception(...)
        screen.show_error(..., "Yenidən cəhd edin.")  # istənilən DİGƏR xəta
        return

`fine_appeals.py::_write` və `shift_swaps.py::_write` isə ƏVVƏL YALNIZ
`except KompasOSError` saxlayırdı. `psycopg.OperationalError` (bağlantı
kəsilməsi, DNS uğursuzluğu, pooler taymautu) `KompasOSError` DEYİL — nəticədə
bu ikisinin yazı yolunda şəbəkə əməliyyatın ORTASINDA (`session.commit()`
zamanı) kəsilsə, istisna KONTROLLERDƏ HEÇ YERDƏ TUTULMURDU.

PySide6-nın öz sınağı (aşağıdakı `_probe_pyside_swallows_slot_exceptions`,
bu faylın ANNEKSİ) göstərir ki, Qt siqnal→slot dispetçerində tutulmamış
Python istisnası ÇÖKMƏ yaratmır — `sys.excepthook`-a keçir (`app.py::
install_global_exception_hook` onu `error.log`-a yazır,
`KompasApplication.notify_unhandled_error` istifadəçiyə BİR DƏFƏ ÜMUMİ
"Gözlənilməz xəta" bildirişi göstərir). Yəni ÇÖKMƏ YOXDUR, LAKİN:

    1. `_inform()`-un KONTEKSTUAL, HƏRƏKƏTƏ ÇAĞIRAN modalı (kartı canlı
       saxlayır, yazılmış mətni İTİRMİR) GÖRÜNMÜR — əvəzinə ÜMUMİ, texniki
       "Gözlənilməz xəta" bildirişi (əgər varsa) gəlir;
    2. `notify_unhandled_error` `_crash_notified` gate-i ilə YALNIZ BİR DƏFƏ
       göstərilir (`app.py:453-455`) — SESSİYA ərzində EYNİ növ bağlantı
       kəsilməsi İKİNCİ dəfə baş versə, İSTİFADƏÇİ HEÇ NƏ GÖRMÜR: düymə
       sükutla "heç nə etmir", kart yerində qalır, heç bir izah yoxdur.

Bu, CLAUDE.md-nin "Hesabat yox, düzəliş" / "sükutla udulma çökmədən BETƏR"
prinsipinin BİRƏBİR nümunəsi idi — məhz bu teammate-in təlimatındakı
XƏBƏRDARLIQ.

DÜZƏLİŞ (`ui` sahibi): `fine_appeals.py::_write` və `shift_swaps.py::_write`
`open_shift.py::_on_claim` ilə EYNİ ikinci `except Exception:` qolunu aldı
(`_error_log.exception(...)` + `_inform(screen, failure, "Yenidən cəhd
edin.")`). Aşağıdakı iki test artıq HƏQİQİ (düzəldilmiş) davranışı yoxlayır —
`xfail` markerləri silinib. Sonrakı iki test `open_shift`/`fine_entry`-nin
əvvəldən DÜZGÜN işlədiyini sübut edir (kontrast/reqressiya qoruması).
"""

from __future__ import annotations

import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
FINE_ID = uuid.uuid4()
APPEAL_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
POSTING_ID = uuid.uuid4()
FINE_TYPE_ID = uuid.uuid4()


class _ConnectionDroppedError(Exception):
    """`psycopg.OperationalError`-un yerli təqlidi — bağlantı ORTADA kəsilir."""


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


class _Actor:
    id = ACTOR_ID


# --------------------------------------------------------------------------- #
# 0. ANNEKS — PySide6-nın öz zəmanəti: slot istisnası prosesi ÇÖKDÜRMÜR
# --------------------------------------------------------------------------- #


def test_pyside_swallows_uncaught_slot_exceptions_instead_of_propagating_them(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Yuxarıdakı bütün analiz BUNA əsaslanır — quraşdırılmadan qəbul EDİLMİR.

    `sys.excepthook` `install_global_exception_hook` tərəfindən qurulur;
    bura ÇAĞIRILMASI ÖZÜ sübutdur ki, kontrollerdə tutulmayan istisna ÇÖKMƏ
    DEYİL, LAKİN SÜKUTLA fərqli (ÜMUMİ) kanala keçən bir hadisədir.
    """
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QPushButton

    captured: list[BaseException] = []
    original_hook = sys.excepthook

    def _hook(exc_type: type[BaseException], exc: BaseException, _tb: object) -> None:
        captured.append(exc)

    sys.excepthook = _hook
    try:

        class _Emitter(QObject):
            fired = Signal(str)

        emitter = _Emitter()

        def _bad_slot(_value: str) -> None:
            raise _ConnectionDroppedError("bağlantı kəsildi")

        emitter.fired.connect(_bad_slot)
        button = QPushButton("test")
        button.clicked.connect(lambda: emitter.fired.emit("x"))

        button.click()  # ÇÖKMƏMƏLİDİR — bu, ÖZÜ sınağın nəticəsidir
    finally:
        sys.excepthook = original_hook

    assert len(captured) == 1
    assert isinstance(captured[0], _ConnectionDroppedError)


# --------------------------------------------------------------------------- #
# 1. TAPILAN QÜSUR — `fine_appeals.py::_write` bağlantı xətasını UDMUR
# --------------------------------------------------------------------------- #


class _FaEmployees:
    def get(self, _employee_id: Any) -> Any:
        return type("E", (), {"full_name": "Aygün Məmmədova"})()


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
    def __init__(self) -> None:
        self.employees = _FaEmployees()
        self.connection = _FaConnection()


class _FaLimits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default


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


class _FineAppeals:
    def __init__(self, appeals: list[Any]) -> None:
        self._by_id = {a.id: a for a in appeals}
        self.approvals: list[dict[str, Any]] = []

    def inbox(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        return [a for a in self._by_id.values() if not a.status.is_decided]

    def approve(
        self, *, tenant_id: Any, actor: Any, appeal_id: Any, note: str, new_amount: Any = None
    ) -> Any:
        # Domen mutasiyası (yaddaşda) — DB `commit()` ANCAQ bundan sonra
        # çağırılır, real dünyada isə bağlantı MƏHZ bu anda kəsilir.
        appeal = self._by_id[appeal_id]
        appeal.approve(
            decided_by=actor.id,
            decided_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
            note=note,
            new_amount=new_amount,
        )
        self.approvals.append({"appeal_id": appeal_id, "note": note})
        return appeal


class _FaSessionDroppedOnCommit:
    """`commit()` ANDA bağlantı kəsilir — `action()` ARTIQ icra OLUNUB."""

    def __init__(self, appeals: _FineAppeals) -> None:
        self.tenant_id = TENANT
        self.fine_appeals = appeals
        self.limits = _FaLimits()
        self.uow = _FaUow()
        self.committed = False

    def commit(self) -> None:
        raise _ConnectionDroppedError("connection reset by peer")


class _FaContextDroppedOnCommit:
    def __init__(self, appeals: _FineAppeals) -> None:
        self._appeals = appeals
        self.sessions: list[_FaSessionDroppedOnCommit] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _FaSessionDroppedOnCommit(self._appeals)
        self.sessions.append(created)
        yield created


def _mute_and_capture_modal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []

    def _fake_exec(self: Any) -> int:
        shown.append(self.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    return shown


@requires_qt
# `qt_no_exception_capture` — pytest-qt-nin ÖZ avtomatik istisna-tutma
# mexanizmi bu testin PROVOSATİV etdiyi istisnanı AYRICA da uğursuzluğa
# çevirərdi (eyni nodeid iki dəfə raportlanır) — bu marker YALNIZ pytest-qt-
# nin ƏLAVƏ qatını söndürür, production kodun ÖZÜNÜ YOX (bax fayl başlığındakı
# anneks: PySide6-nın ÖZÜ istisnanı artıq `sys.excepthook`-a keçirir).
@pytest.mark.qt_no_exception_capture
def test_fine_appeal_approval_shows_a_recoverable_modal_when_connection_drops_mid_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.fine_appeals import FineAppealInboxController
    from src.presentation.screens.group_f import FineAppealInboxScreen

    shown = _mute_and_capture_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _FaContextDroppedOnCommit(appeals)
    screen = FineAppealInboxScreen(theme)
    qtbot.addWidget(screen)
    controller = FineAppealInboxController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(screen)
    controller.refresh(screen)

    from PySide6.QtWidgets import QPlainTextEdit

    box = screen.findChildren(QPlainTextEdit)[0]
    box.setPlainText("Sübut kifayət etmir, ləğv edilir.")

    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR (PySide udur — anneks sübutu)

    assert shown, (
        "bağlantı kəsilməsi digər kontrollerlərdəki kimi KONTEKSTUAL modal "
        "göstərməli idi (`_inform`) — göstərilmədi"
    )


class _SsSessionDroppedOnCommit:
    def __init__(self) -> None:
        self.tenant_id = TENANT
        self.rejections: list[dict[str, Any]] = []
        self.shift_swaps = self
        self.committed = False

    def reject(self, *, tenant_id: Any, approver: Any, request_id: Any, reason: str) -> None:
        self.rejections.append({"request_id": request_id, "reason": reason})

    def commit(self) -> None:
        raise _ConnectionDroppedError("connection reset by peer")


class _SsContextDroppedOnCommit:
    def __init__(self) -> None:
        self.sessions: list[_SsSessionDroppedOnCommit] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _SsSessionDroppedOnCommit()
        self.sessions.append(created)
        yield created


@requires_qt
@pytest.mark.qt_no_exception_capture  # bax birinci testin şərhi
def test_shift_swap_approval_shows_a_recoverable_modal_when_connection_drops_mid_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    from src.presentation.controllers import screen_data as screen_data_module
    from src.presentation.controllers.shift_swaps import ShiftSwapController
    from src.presentation.screens.group_c import ShiftSwapScreen

    class _Binder:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def populate(self, _key: str, screen: Any) -> None:
            screen.set_counts({"pending": 0})
            screen.set_requests([])

    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    shown = _mute_and_capture_modal(monkeypatch)

    context = _SsContextDroppedOnCommit()
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
    card = next(c for c in screen._rows if c.key == str(REQUEST_ID))
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

    _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert shown, "bağlantı kəsilməsi kontekstual modal göstərməli idi"


# --------------------------------------------------------------------------- #
# 2. ƏKS SÜBUT — `open_shift.py` / `fine_entry.py` EYNİ hadisəni DÜZGÜN tutur
# --------------------------------------------------------------------------- #


class _RealisticOpenShiftsDroppedOnCommit:
    def list_for_employee(self, *, tenant_id: Any, employee: Any) -> list[Any]:
        return []

    def list_claimed_for_employee(self, *, tenant_id: Any, employee: Any) -> list[Any]:
        """DEEP-GAP OP-4 — «Tutduğunuz növbələr» bölməsinin oxu yolu.

        Sahtə BOŞ siyahı qaytarır: bu faylın testləri TUTMA axınını ölçür,
        geri vermə isə ayrıca sınanır. Metodun MÖVCUD olması vacibdir —
        `refresh()` hər çağırışda hər iki siyahını EYNİ sessiyada oxuyur.
        """
        return []

    def claim(self, *, tenant_id: Any, employee: Any, posting_id: Any) -> None:
        return None


class _OsWorkModeRepo:
    def get(self, _work_mode_id: Any) -> Any:
        return None


class _OsUow:
    def repository(self, name: str) -> Any:
        if name == "work_modes":
            return _OsWorkModeRepo()
        raise NotImplementedError(name)  # pragma: no cover


class _OsSessionDroppedOnCommit:
    def __init__(self, open_shifts: Any) -> None:
        self.tenant_id = TENANT
        self.open_shifts = open_shifts
        self.uow = _OsUow()

    def commit(self) -> None:
        raise _ConnectionDroppedError("connection reset by peer")


class _OsContextDroppedOnCommit:
    def __init__(self) -> None:
        self._open_shifts = _RealisticOpenShiftsDroppedOnCommit()

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield _OsSessionDroppedOnCommit(self._open_shifts)


def _open_shift_view() -> Any:
    from datetime import date

    from src.application.use_cases.open_shift_market import OpenShiftView
    from src.domain.value_objects.identifiers import OpenShiftPostingId, StoreId, WorkModeId

    return OpenShiftView(
        posting_id=OpenShiftPostingId(POSTING_ID),
        store_id=StoreId(STORE_ID),
        shift_date=date(2026, 8, 25),
        work_mode_id=WorkModeId(uuid.uuid4()),
        status="OPEN",
        posted_by=None,
        claimed_by=None,
        created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    )


@requires_qt
def test_open_shift_claim_shows_a_clear_message_when_connection_drops_mid_commit(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """KONTRAST: `open_shift.py::_on_claim`-in `except Exception:` qolu
    EYNİ ssenarini DÜZGÜN idarə edir — bax fayl başlığındakı asimmetriya."""
    from src.presentation.controllers.open_shift import EmployeeOpenShiftController
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    context = _OsContextDroppedOnCommit()
    screen = EmployeeHomeScreen(
        theme, full_name="Aygün Məmmədova", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    screen.show()
    EmployeeOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.open_shift_claim_requested.emit(str(POSTING_ID))  # ÇÖKMƏMƏLİDİR

    assert screen._open_shift_hint.text() == "Növbə götürülmədi. Yenidən cəhd edin."
    assert screen._open_shift_hint.isVisible()


class _FeManualFinesDroppedOnCommit:
    def __init__(self) -> None:
        self.issued: list[dict[str, Any]] = []

    def selectable_fine_types(self, _tenant_id: Any) -> list[Any]:
        return [_fine_type()]

    def allowed_stores(self, _operator: Any) -> list[Any]:
        return [STORE_ID]

    def issue(self, **kwargs: Any) -> Any:
        self.issued.append(kwargs)
        return type("_Fine", (), {"id": kwargs.get("fine_id")})()


class _FeRow(dict):
    pass


class _FeConnection:
    def __init__(self) -> None:
        self._stores = {str(STORE_ID): "Mərkəz"}
        self._employees = {str(EMPLOYEE_ID): ("Aygün", "Məmmədova")}
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
        return []  # pragma: no cover


class _FeUow:
    def __init__(self) -> None:
        self.connection = _FeConnection()

    @property
    def fines(self) -> Any:
        return self

    def mark_evidence_pending(self, _fine_id: Any) -> None:
        return None


class _FeSessionDroppedOnCommit:
    def __init__(self, manual_fines: _FeManualFinesDroppedOnCommit) -> None:
        self.tenant_id = TENANT
        self.manual_fines = manual_fines
        self.uow = _FeUow()

    def commit(self) -> None:
        raise _ConnectionDroppedError("connection reset by peer")


class _FeEvidenceQueue:
    """Sübut ARTIQ diskə yazılıb — bağlantı YALNIZ DB commit-ində kəsilir."""

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self._counter = 0

    def enqueue(self, **kwargs: Any) -> str:
        self._counter += 1
        self.enqueued.append(kwargs)
        return f"queue-entry-{self._counter}"


class _FeContextDroppedOnCommit:
    def __init__(self) -> None:
        self.manual_fines = _FeManualFinesDroppedOnCommit()
        self.tenant_id = TENANT
        self.evidence = _FeEvidenceQueue()
        self.upload_runs = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield _FeSessionDroppedOnCommit(self.manual_fines)

    def evidence_queue(self) -> _FeEvidenceQueue:
        return self.evidence

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


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


@requires_qt
def test_fine_entry_shows_a_clear_message_when_connection_drops_after_evidence_is_already_queued(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """KONTRAST + sıra sübutu: sübut ARTIQ yerli diskə yazılıb (növbədə qalır,
    bax `fine_entry.py` başlığı — "ən pis hal sahibsiz spool faylıdır"), DB
    `commit()`-i isə kəsilir. `except Exception:` qolu bunu DÜZGÜN tutur."""
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.fine_entry import FineEntryController
    from src.presentation.screens.group_b import FineEntryScreen

    context = _FeContextDroppedOnCommit()
    controller = FineEntryController(context, _Actor(), executor=InlineExecutor())
    fine_types, stores, employees = controller.options()
    screen = FineEntryScreen(theme, fine_types=fine_types, stores=stores, employees=employees)
    qtbot.addWidget(screen)
    screen.show()
    controller.attach(screen)

    screen._type.set_text("Gecikmə")
    screen._store.set_text("Mərkəz")
    screen._employee.set_text("Aygün Məmmədova")
    photo = tmp_path / "subut.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")
    screen._photo.set_file(str(photo))

    _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"
    assert len(context.evidence.enqueued) == 1, (
        "sübut DB commit-indən ƏVVƏL yerli diskə yazılıb — sahibsiz qalması "
        "SƏNƏDLƏŞDİRİLMİŞ, qəbul edilmiş nəticədir (bax `fine_entry.py` başlığı)"
    )
