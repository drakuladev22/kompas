"""`FineAppealInboxScreen` ↔ `controllers/fine_appeals.py` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, dördüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`test_fine_appeals_controller.py` `_Screen` adlı sahtə obyektlə işləyir —
REAL `FineAppealInboxScreen`, REAL "Qəbul Et"/"Rədd Et" düymələri, REAL
səbəb qutusu (`QPlainTextEdit`) heç vaxt qurulmur. Burada hər üçü FAKTİKİ
qurulur və REAL klik göndərilir.

`session.fine_appeals` sahtəsi domendəki HƏQİQİ `FineAppeal.approve/reject`
metodunu çağırır (sətir aşağıda, `_FineAppeals`) — sadə siyahı manipulyasiyası
DEYİL. Səbəb: "eyni qərar iki dəfə yazılmır" yalnız real domen keçidi
(`_require_decidable`) ilə düzgün ölçülür; sahtə siyahıdan silmə bunu
gizlədərdi (bax `test_fine_review_screen_e2e.py` başlığındakı eyni dərs).

──────────────────────────────────────────────────────────────────────────────
DÜZƏLDİLMİŞ QÜSUR — `refresh()`-dəki OXU XƏTASI QOLU (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
İlk versiyada `ScreenDataBinder.populate()` HƏR istisnanı özü udurdu
(`except Exception:`) və heç vaxt yenidən atmırdı, yəni
`FineAppealInboxController.refresh()`-dəki `except KompasOSError` qolu
İSTEHSALATDA ÇATILMAZ idi — "Yenidən Cəhd Et" düyməli xəta vəziyyəti heç vaxt
görünmürdü, əvəzinə səssiz bölmə banneri göstərilirdi. `fix-face-appeals`
`populate()`-ə `reraise: bool = False` parametri əlavə etdi
(`screen_data.py:210-227`) və `refresh()` indi `populate(..., reraise=True)`
çağırır (`fine_appeals.py:196-201`) — `KompasOSError` artıq YENİDƏN ATILIR,
qol İSTEHSALATDA İŞLƏYİR. `test_a_real_read_failure_reaches_the_documented_
retry_button` bunu real `ScreenDataBinder` ilə (heç bir monkeypatch olmadan)
sübut edir — TƏRSİNƏ nəticə: əvvəl "heç vaxt çatmır" idi, indi "çatır və
retry işləyir".
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.entities.appeal import MIN_DECISION_NOTE_LENGTH, FineAppeal
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
FINE_ID = uuid.uuid4()
APPEAL_ID = uuid.uuid4()

CREATED_AT = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

#: `MIN_DECISION_NOTE_LENGTH`-dən uzun, real HR qərarına bənzər mətn.
LONG_NOTE = "Sübut kifayət etmir, kamerada görünmür, cərimə ləğv edilir."


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


def _reason_box(screen: Any) -> Any:
    """Kartın səbəb qutusu — hər testdə TƏK etiraz olduğu üçün ilki kifayətdir."""
    from PySide6.QtWidgets import QPlainTextEdit

    return screen.findChildren(QPlainTextEdit)[0]


def _appeal(
    *,
    appeal_id: Any = APPEAL_ID,
    employee_id: Any = EMPLOYEE_ID,
    fine_id: Any = FINE_ID,
    reason: str = "Kamerada mən görünmürəm, sifariş başqasına aiddir.",
    created_at: datetime = CREATED_AT,
) -> FineAppeal:
    return FineAppeal(
        appeal_id=appeal_id,  # type: ignore[arg-type]
        tenant_id=TENANT,  # type: ignore[arg-type]
        fine_id=fine_id,  # type: ignore[arg-type]
        employee_id=employee_id,  # type: ignore[arg-type]
        reason=reason,
        created_at=created_at,
        emit_created_event=False,
    )


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Employee:
    def __init__(self, full_name: str) -> None:
        self.full_name = full_name


class _Employees:
    def __init__(self, by_id: dict[Any, _Employee]) -> None:
        self._by_id = by_id

    def get(self, employee_id: Any) -> _Employee | None:
        return self._by_id.get(employee_id)


class _Row(dict):
    pass


class _Connection:
    """`_fine_type_name` VƏ `_fine_amount` sorğuları — SQL mətninə görə ayrılır."""

    def __init__(self, *, type_name: str = "Kassa Kəsiri", amount: str = "25.00") -> None:
        self._type_name = type_name
        self._amount = amount
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _Connection:
        self._last_sql = sql
        return self

    def fetchone(self) -> _Row | None:
        if "fine_types" in self._last_sql:
            return _Row(name=self._type_name)
        if "FROM fines" in self._last_sql:
            return _Row(amount=self._amount)
        return None  # pragma: no cover


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default


class _Uow:
    def __init__(self, employees: _Employees, connection: _Connection) -> None:
        self.employees = employees
        self.connection = connection


class _FineAppeals:
    """`session.fine_appeals` — REAL `FineAppeal.approve/reject` ÜZƏRİNDƏN işləyir.

    `read_failure`/`write_failure` real `KompasOSError`-dır — kontroller onu
    məhz bu tiplə tutur.
    """

    def __init__(
        self,
        appeals: list[FineAppeal],
        *,
        read_failure: KompasOSError | None = None,
        write_failure: KompasOSError | None = None,
    ) -> None:
        self._by_id = {a.id: a for a in appeals}
        self.read_failure = read_failure
        self.write_failure = write_failure
        self.approvals: list[dict[str, Any]] = []
        self.rejections: list[dict[str, Any]] = []

    def inbox(self, *, tenant_id: Any, actor: Any) -> list[FineAppeal]:
        if self.read_failure is not None:
            raise self.read_failure
        return [a for a in self._by_id.values() if not a.status.is_decided]

    def approve(
        self, *, tenant_id: Any, actor: Any, appeal_id: Any, note: str, new_amount: Any = None
    ) -> Any:
        if self.write_failure is not None:
            raise self.write_failure
        if appeal_id not in self._by_id:
            raise KompasOSError("appeal not found", user_message="Bu etiraz artıq siyahıda deyil.")
        appeal = self._by_id[appeal_id]
        appeal.approve(decided_by=actor.id, decided_at=DECIDED_AT, note=note, new_amount=new_amount)
        self.approvals.append({"appeal_id": appeal_id, "note": note, "new_amount": new_amount})
        return appeal

    def reject(self, *, tenant_id: Any, actor: Any, appeal_id: Any, note: str) -> Any:
        if self.write_failure is not None:
            raise self.write_failure
        if appeal_id not in self._by_id:
            raise KompasOSError("appeal not found", user_message="Bu etiraz artıq siyahıda deyil.")
        appeal = self._by_id[appeal_id]
        appeal.reject(decided_by=actor.id, decided_at=DECIDED_AT, note=note)
        self.rejections.append({"appeal_id": appeal_id, "note": note})
        return appeal


class _Session:
    def __init__(
        self, *, appeals: _FineAppeals, employees: _Employees, connection: _Connection
    ) -> None:
        self.tenant_id = TENANT
        self.fine_appeals = appeals
        self.limits = _Limits()
        self.uow = _Uow(employees, connection)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    """Hər `with` YENİ sessiya açır — bölmə 6: «kontroller sessiyanı SAXLAMIR»."""

    def __init__(
        self,
        *,
        appeals: _FineAppeals,
        employees: _Employees | None = None,
        connection: _Connection | None = None,
    ) -> None:
        self._appeals = appeals
        self._employees = employees or _Employees({EMPLOYEE_ID: _Employee("Aygün Məmmədova")})
        self._connection = connection or _Connection()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            appeals=self._appeals, employees=self._employees, connection=self._connection
        )
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _build(theme: Any, qtbot: Any, context: Any) -> tuple[Any, Any]:
    from src.presentation.controllers.fine_appeals import FineAppealInboxController
    from src.presentation.screens.group_f import FineAppealInboxScreen

    screen = FineAppealInboxScreen(theme)
    qtbot.addWidget(screen)
    controller = FineAppealInboxController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(screen)
    return screen, controller


def _mute_modal(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """`_inform()` bloklayan `QMessageBox.exec()`-i kəsir — başlıq/mətni tutur."""
    from PySide6.QtWidgets import QMessageBox

    shown: list[tuple[str, str]] = []

    def _fake_exec(self: Any) -> int:
        shown.append((self.windowTitle(), self.text()))
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    return shown


# --------------------------------------------------------------------------- #
# 1. Real doldurma — kart, düymələr, səbəb qutusu
# --------------------------------------------------------------------------- #


@requires_qt
def test_refresh_populates_a_real_card_with_working_buttons(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    context = _Context(appeals=_FineAppeals([_appeal()]))
    screen, controller = _build(theme, qtbot, context)

    controller.refresh(screen)

    from PySide6.QtWidgets import QPlainTextEdit, QPushButton

    labels = {b.text() for b in screen.findChildren(QPushButton)}
    assert {"Qəbul Et", "Rədd Et"} <= labels
    assert len(screen.findChildren(QPlainTextEdit)) == 1


# --------------------------------------------------------------------------- #
# 2. Real Qəbul Et / Rədd Et
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_real_accept_button_writes_normalises_and_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText("   Sübut   kifayət    etmir   ")
    _click(screen, "Qəbul Et")

    assert len(appeals.approvals) == 1
    assert appeals.approvals[0]["appeal_id"] == APPEAL_ID
    assert appeals.approvals[0]["note"] == "Sübut kifayət etmir"
    assert "new_amount" not in appeals.approvals[0] or appeals.approvals[0]["new_amount"] is None
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_clicking_the_real_reject_button_writes_and_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(LONG_NOTE)
    _click(screen, "Rədd Et")

    assert len(appeals.rejections) == 1
    assert appeals.rejections[0]["appeal_id"] == APPEAL_ID
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_accepted_appeal_disappears_from_the_real_list_after_refresh(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Qərar verilmiş kart siyahıdan ÇIXIR — `inbox` yalnız PENDING qaytarır."""
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(LONG_NOTE)
    _click(screen, "Qəbul Et")

    # `clear_layout()` köhnə kartı `deleteLater()` ilə işarələyir — HƏQİQİ
    # silinmə `DeferredDelete` hadisəsi işlənəndə baş verir. Sadə
    # `processEvents()` bunu YETƏRLİ ETMİR (yoxlanıldı) — `sendPostedEvents`
    # ilə həmin hadisə növü açıq işlədilməlidir, əks halda köhnə düymə
    # `findChildren`-də görünməyə davam edir.
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QPushButton

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert not any(b.text() == "Qəbul Et" for b in screen.findChildren(QPushButton))
    assert screen.switcher().current_state() == "empty"


# --------------------------------------------------------------------------- #
# 3. Səbəbin doğrulanması — real klik, real qutu
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_note", ["", "   \n\t  "], ids=["boş", "yalnız-boşluq"])
@requires_qt
def test_short_note_shows_a_real_modal_and_keeps_the_card_recoverable(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, bad_note: str
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.fine_appeals import SHORT_NOTE_MESSAGE

    shown = _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)
    sessions_before = len(context.sessions)  # `refresh()` özü BİR sessiya açır

    _reason_box(screen).setPlainText(bad_note)
    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR

    assert appeals.approvals == []
    assert len(context.sessions) == sessions_before  # qərar sessiyası ÜMUMİYYƏTLƏ açılmayıb
    assert shown[-1][1] == SHORT_NOTE_MESSAGE

    # Kart HƏLƏ DƏ canlıdır (yenidən qurulmayıb) — eyni qutuya uzun mətn
    # yazıb yenidən klikləmək İŞLƏMƏLİDİR.
    _reason_box(screen).setPlainText(LONG_NOTE)
    _click(screen, "Qəbul Et")

    assert len(appeals.approvals) == 1


@requires_qt
def test_the_boundary_length_note_is_accepted(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Tam `MIN_DECISION_NOTE_LENGTH` uzunluq KEÇİR — sərhəd domenlə eynidir."""
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText("x" * MIN_DECISION_NOTE_LENGTH)
    _click(screen, "Qəbul Et")

    assert len(appeals.approvals) == 1


@requires_qt
def test_hostile_and_extreme_note_text_is_normalised_without_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    hostile = "'; DROP TABLE fine_appeals; -- 🔥" + "A" * 10_000
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(hostile)
    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR

    assert len(appeals.approvals) == 1
    assert appeals.approvals[0]["note"] == " ".join(hostile.split())


# --------------------------------------------------------------------------- #
# 4. Yararsız/köhnəlmiş identifikator — real siqnal
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_id",
    ["", "not-a-uuid", "11111111-1111-1111-1111", "  "],
    ids=["boş", "mətn", "yarımçıq", "boşluq"],
)
@requires_qt
def test_a_malformed_appeal_id_from_a_stale_signal_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, bad_id: str
) -> None:  # type: ignore[no-untyped-def]
    """QA-13 naxışı: real ekran, real siqnal — köhnəlmiş kart YANLIŞ id yayır."""
    from src.presentation.controllers.fine_appeals import UNKNOWN_APPEAL_MESSAGE

    shown = _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)
    sessions_before = len(context.sessions)  # `refresh()` özü BİR sessiya açır

    screen.accepted.emit(bad_id, LONG_NOTE)  # ÇÖKMƏMƏLİDİR

    assert len(context.sessions) == sessions_before
    assert appeals.approvals == []
    assert shown[-1][1] == UNKNOWN_APPEAL_MESSAGE


# --------------------------------------------------------------------------- #
# 5. İkiqat qərar — real domen keçidi
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_second_decision_on_an_already_decided_appeal_is_refused_not_double_written(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Real klik qərarı yazır; TƏKRAR siqnal (köhnəlmiş kart/ikinci admin) REDDEDİLİR.

    Qoruma kontrollerdə YOX — real `FineAppeal._require_decidable()`-dədir
    (`appeal.py:239-252`). Kontroller yalnız domendən gələn `KompasOSError`-u
    modalla göstərir və YAZMIR — bax modul başlığı.
    """
    shown = _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(LONG_NOTE)
    _click(screen, "Qəbul Et")
    assert len(appeals.approvals) == 1

    # Kart artıq siyahıdan çıxıb, amma `appeal_id` HƏLƏ DƏ etibarlı UUID-dir —
    # köhnəlmiş klik/ikinci admin bu id ilə TƏKRAR siqnal göndərə bilər.
    screen.accepted.emit(str(APPEAL_ID), LONG_NOTE)

    assert len(appeals.approvals) == 1, "İkinci yazı BAŞ VERMƏMƏLİDİR"
    assert shown[-1][1] == "Bu etiraz artıq emal edilib."


# --------------------------------------------------------------------------- #
# 6. Yazı xətası — kart itmir, banner refresh ilə üstündən yazılmır
# --------------------------------------------------------------------------- #


@requires_qt
def test_write_failure_shows_a_real_modal_and_keeps_the_pending_card(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    shown = _mute_modal(monkeypatch)
    failure = KompasOSError(
        "icazə yoxdur", user_message="Cərimə etirazına qərar vermə icazəniz yoxdur."
    )
    appeals = _FineAppeals([_appeal()], write_failure=failure)
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(LONG_NOTE)
    _click(screen, "Qəbul Et")

    assert appeals.approvals == []
    assert not any(s.committed for s in context.sessions)
    assert shown[-1][1] == failure.user_message

    # Kart YENİDƏN QURULMAYIB (`refresh()` uğursuz yazıdan sonra çağırılmır) —
    # düymələr hələ də canlıdır və istifadəçi mətnini itirmədən yenidən sınaya bilər.
    from PySide6.QtWidgets import QPushButton

    assert any(b.text() == "Qəbul Et" for b in screen.findChildren(QPushButton))


# --------------------------------------------------------------------------- #
# 7. DÜZƏLDİLMİŞ QÜSUR — real oxu xətası indi sənədləşdirilmiş retry-a çatır
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_real_read_failure_reaches_the_documented_retry_button_and_it_works(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`refresh()`-in `except KompasOSError` qolu artıq REAL `ScreenDataBinder`-lə ÇATILANDIR.

    QA-FULL Faza 3 tapıntısı: `ScreenDataBinder.populate()` əvvəl HƏR
    istisnanı udurdu (`except Exception:`) və heç vaxt yenidən atmırdı,
    yəni bu qol İSTEHSALATDA HEÇ VAXT işə düşmürdü. `populate(...,
    reraise=True)` (`screen_data.py:210-227`) bunu düzəltdi. Bu test
    əvvəlkinin TƏRSİNƏ nəticəsini sübut edir: "error" vəziyyətinə HƏQİQƏTƏN
    keçilir, REAL "Yenidən Cəhd Et" düyməsi görünür və basılanda siyahı
    HƏQİQƏTƏN bərpa olunur (baza yenidən əlçatan olduqda).
    """
    from PySide6.QtWidgets import QPushButton

    failure = KompasOSError("baza əlçatmazdır", user_message="Baza əlçatmazdır.")
    appeals = _FineAppeals([_appeal()], read_failure=failure)
    context = _Context(appeals=appeals)
    screen, controller = _build(theme, qtbot, context)

    controller.refresh(screen)  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"
    assert any(b.text() == "Yenidən Cəhd Et" for b in screen.findChildren(QPushButton))

    # Baza YENİDƏN əlçatan olur — real "Yenidən Cəhd Et" düyməsi basılanda
    # `on_retry` (`self.refresh`) HƏQİQƏTƏN çağırılmalı və siyahı bərpa
    # olunmalıdır.
    appeals.read_failure = None
    _click(screen, "Yenidən Cəhd Et")

    assert screen.switcher().current_state() == "content"
    assert any(b.text() == "Qəbul Et" for b in screen.findChildren(QPushButton))
