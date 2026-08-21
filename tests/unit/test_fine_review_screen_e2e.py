"""`MonthlyFineReviewScreen` ↔ `controllers/fine_review.py` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/fine_review.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi. Real
filial qrupu, real "Hamısı: Sil"/sətir "Sil" düymələri və real TƏK "Bütün
Filiallara Göndər" düyməsi ilə tam nəşr axını sınanır.

──────────────────────────────────────────────────────────────────────────────
DÜZƏLİŞ (komanda lideri + `domain` yoxlaması) — AŞAĞIDAKI SƏTİR REAL BOŞLUQ
DEYİL, TƏK-QATLI SINAQ MƏHDUDİYYƏTİDİR
──────────────────────────────────────────────────────────────────────────────
İlkin versiyada `test_an_actor_who_issued_the_fine_can_also_publish_it`
"yaradan şəxs öz cəriməsini dərc edə bilir" kimi YANLIŞ nəticə yazırdı.
`MonthlyFineReviewUseCase.publish_batch()` (`fine_review.py:172-`) HƏQİQƏTƏN
`fine.issued_by == actor.id` yoxlaması APARMIR (`_assert_may_publish` YALNIZ
`PUBLISH_FINES_FLAG`-i yoxlayır) — LAKİN bu, qapının OLMADIĞI demək DEYİL:
qapı BİR QAT AŞAĞIDADIR, VƏZİFƏ TƏYİNATI ANINDA:

    * `can_issue_fines` — `schema.sql:2470`: `is_anti_fraud=TRUE,
      is_camera_only=TRUE` — YALNIZ kamera-tipli mövqeyə verilə bilər.
    * `can_publish_fines` — `migrations/003:255`: `excludes_camera_role=TRUE`
      — kamera-tipli mövqeyə HEÇ VAXT verilə BİLMƏZ (nə defolt, nə fərdi
      override).
    * `positions.is_camera_type` mövqenin SABİT atributudur — bir işçi eyni
      anda hər iki tərəfdə OLA BİLMƏZ.
    * Qayda İKİ yerdə tətbiq olunur: DB `enforce_anti_fraud_segregation()`
      trigger-i (`migrations/003:188-242` + `schema.sql` §18) VƏ domendə
      `PermissionFlag.assert_grantable_to` (`authorization.py:253-259`) —
      hər icazə dəyişikliyi `permission_guards.py:267-278`-dən keçir.
    * Qərar sənədlidir: SEC-001 və `migrations/003:177-180` şərhi — "Hər
      ikisi eyni şəxsdə olsa, dual-control fəlsəfəsi mənasını itirər".

Bu faylın FAKE `_Context`-i (aşağıda) YALNIZ kontroller+use case qatını
əvəz edir — DB trigger-ini VƏ `PermissionFlag.assert_grantable_to`-nu
TƏMSİL ETMİR. Fake-də `issued_by=ACTOR_ID` yazmaq mümkündür, çünki fake
`positions`/`permission_guards` heç vaxt işə düşmür; REAL sistemdə isə
belə bir aktoru (eyni anda `can_issue_fines` VƏ `can_publish_fines`
daşıyan) YARATMAQ MÜMKÜN DEYİL. Test buna görə YENİDƏN ADLANDIRILIB:
o, "kontroller/use case qatında runtime `issued_by` yoxlaması yoxdur"
FAKTINI ölçür — "self-publish mümkündür" İDDİASINI YOX (bax aşağıdakı
test və onun şərhi).

DƏRS (bütün qalan fazalara aiddir): fake-qurulmuş test bir QATIN
yoxluğunu sübut edə bilər, lakin "istismar mümkündür" nəticəsi vermək
üçün ALT qatları (DB trigger-i, domen guard-ı, flag qrammatikası) da
FAKTİKİ oxumaq lazımdır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
FINE_ID = uuid.uuid4()


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


class _Amount:
    def __init__(self, amount: Decimal) -> None:
        self.amount = amount


class _FakeFine:
    """`Fine`-in yerini tutur — kontroller yalnız bu atributları oxuyur."""

    def __init__(
        self,
        *,
        fine_id: Any = FINE_ID,
        employee_id: Any = EMPLOYEE_ID,
        store_id: Any = STORE_ID,
        issued_by: Any = None,
        amount: Decimal = Decimal("25"),
        fine_type_id: Any = None,
        source: str = "MANUAL_CAMERA",
        photo_evidence_url: str | None = "queue-entry-1",
    ) -> None:
        self.id = fine_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.issued_by = issued_by
        self.amount = _Amount(amount)
        self.fine_type_id = fine_type_id
        self.issued_at = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
        self.photo_evidence_url = photo_evidence_url

        class _Source:
            value = source

        self.source = _Source()


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    def __init__(self, stores: dict[str, str], employees: dict[str, tuple[str, str]]) -> None:
        self._stores = stores
        self._employees = employees
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _Connection:
        self._last_sql = sql
        return self

    def fetchall(self) -> list[_Row]:
        if "FROM stores" in self._last_sql:
            return [_Row(id=sid, name=name) for sid, name in self._stores.items()]
        if "FROM employees" in self._last_sql:
            return [
                _Row(id=eid, first_name=first, last_name=last)
                for eid, (first, last) in self._employees.items()
            ]
        if "FROM fine_types" in self._last_sql:
            return []
        return []  # pragma: no cover


class _FinesRepo:
    def __init__(self, periods: list[str], fines_by_period: dict[str, list[_FakeFine]]) -> None:
        self._periods = periods
        self._fines_by_period = fines_by_period
        self.saved: list[Any] = []

    def pending_review_periods(self, _tenant_id: Any) -> list[str]:
        return list(self._periods)

    def list_pending_review(self, _tenant_id: Any, *, year: int, month: int) -> list[_FakeFine]:
        key = f"{year:04d}-{month:02d}"
        return list(self._fines_by_period.get(key, []))

    def save(self, fine: Any) -> None:
        self.saved.append(fine)


class _Uow:
    def __init__(
        self,
        stores: dict[str, str],
        employees: dict[str, tuple[str, str]],
        fines_repo: _FinesRepo,
    ) -> None:
        self.connection = _Connection(stores, employees)
        self.fines = fines_repo


class _FineReview:
    def __init__(self) -> None:
        self.publish_calls: list[dict[str, Any]] = []
        self.publish_error: KompasOSError | None = None
        self.result_published: list[Any] = []
        self.result_discarded: list[Any] = []

    def publish_batch(self, **kwargs: Any) -> Any:
        if self.publish_error is not None:
            raise self.publish_error
        self.publish_calls.append(kwargs)
        return type(
            "_Result", (), {"published": self.result_published, "discarded": self.result_discarded}
        )()


class _Session:
    def __init__(
        self,
        stores: dict[str, str],
        employees: dict[str, tuple[str, str]],
        fines_repo: _FinesRepo,
        fine_review: _FineReview,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(stores, employees, fines_repo)
        self.fine_review = fine_review
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(
        self,
        *,
        periods: list[str] | None = None,
        fines_by_period: dict[str, list[_FakeFine]] | None = None,
        stores: dict[str, str] | None = None,
        employees: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        self._stores = stores if stores is not None else {str(STORE_ID): "Mərkəz"}
        self._employees = (
            employees if employees is not None else {str(EMPLOYEE_ID): ("Aygün", "Məmmədova")}
        )
        self.fines_repo = _FinesRepo(
            periods if periods is not None else ["2026-08"],
            fines_by_period if fines_by_period is not None else {"2026-08": [_FakeFine()]},
        )
        self.fine_review = _FineReview()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._stores, self._employees, self.fines_repo, self.fine_review)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _build(
    theme: Any,
    qtbot: Any,
    context: Any,
    *,
    monkeypatch: pytest.MonkeyPatch | None = None,
    confirm: bool = True,
) -> Any:
    from src.presentation.controllers.fine_review import MonthlyFineReviewController
    from src.presentation.screens.fine_review import MonthlyFineReviewScreen

    if monkeypatch is not None:
        monkeypatch.setattr(
            MonthlyFineReviewController, "_confirm", lambda self, screen, summary: confirm
        )

    screen = MonthlyFineReviewScreen(theme)
    qtbot.addWidget(screen)
    MonthlyFineReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


# --------------------------------------------------------------------------- #
# 1. Real doldurma — filial qrupu, xülasə
# --------------------------------------------------------------------------- #


@requires_qt
def test_attach_populates_the_real_group_and_publish_button(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch)

    assert screen.groups_layout().count() == 1
    assert screen.publish_button().isEnabled()


@requires_qt
def test_no_pending_periods_shows_the_real_empty_state(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context(periods=[], fines_by_period={})
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch)

    assert screen.switcher().current_state() == "empty"
    assert not screen.publish_button().isEnabled()


# --------------------------------------------------------------------------- #
# 2. Real "Bütün Filiallara Göndər" — uğur, boş dəst, köhnəlmiş siyahı
# --------------------------------------------------------------------------- #


@requires_qt
def test_publishing_via_the_real_button_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    context.fine_review.result_published = [FINE_ID]
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch, confirm=True)

    _click(screen, "Bütün Filiallara Göndər")

    assert len(context.fine_review.publish_calls) == 1
    assert any(s.committed for s in context.sessions)
    assert screen._notice.isVisible() or screen._notice.text()


@requires_qt
def test_declining_the_confirm_modal_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch, confirm=False)

    _click(screen, "Bütün Filiallara Göndər")

    assert context.fine_review.publish_calls == []
    assert not any(s.committed for s in context.sessions)


@requires_qt
def test_a_stale_list_at_publish_time_writes_nothing_and_shows_a_real_message(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Yazı ANINDA siyahı YENİDƏN oxunur və dəst dəyişibsə HEÇ NƏ yazılmır (modul başlığı)."""
    from src.presentation.controllers.fine_review import LIST_CHANGED

    context = _Context()
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch, confirm=True)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    # Nəşrdən DƏRHAL ƏVVƏL başqa admin YENİ cərimə yazıb — siyahı artıq FƏRQLİDİR.
    context.fines_repo._fines_by_period["2026-08"] = [_FakeFine(), _FakeFine(fine_id=uuid.uuid4())]

    _click(screen, "Bütün Filiallara Göndər")

    assert context.fine_review.publish_calls == []
    assert screen._error.text() == LIST_CHANGED
    assert screen._error.isVisible()


@requires_qt
def test_publish_failure_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Səlahiyyət rəddi (`FineReviewError`) — real klik AÇIQ mesaj göstərir."""
    context = _Context()
    context.fine_review.publish_error = KompasOSError(
        "no permission", user_message="Cərimə dərc etmək səlahiyyətiniz yoxdur."
    )
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch, confirm=True)

    _click(screen, "Bütün Filiallara Göndər")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen._error.text() == "Cərimə dərc etmək səlahiyyətiniz yoxdur."


@requires_qt
def test_the_controller_layer_has_no_runtime_issued_by_check_the_guard_is_one_layer_down(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`publish_batch()` `fine.issued_by == actor.id` YOXLAMIR — LAKİN bu, REAL boşluq DEYİL.

    Bu test YALNIZ kontroller+use case qatında (`_assert_may_publish`)
    `issued_by` müqayisəsinin OLMADIĞINI ölçür — real sistemdə belə aktoru
    (eyni anda `can_issue_fines` VƏ `can_publish_fines` daşıyan) YARATMAQ
    mümkün deyil, çünki qapı BİR QAT AŞAĞIDADIR: `can_issue_fines`
    (`schema.sql:2470`: `is_camera_only=TRUE`) YALNIZ kamera-tipli mövqeyə,
    `can_publish_fines` (`migrations/003:255`: `excludes_camera_role=TRUE`)
    isə kamera-tipli mövqeyə HEÇ VAXT verilə bilməz — DB trigger-i
    (`enforce_anti_fraud_segregation()`, `migrations/003:188-242`) VƏ domen
    guard-ı (`PermissionFlag.assert_grantable_to`, `authorization.py:253-259`)
    bunu İKİ yerdə tətbiq edir (bax modul başlığı). Bu faylın FAKE `_Context`-i
    həmin alt qatları TƏMSİL ETMİR, ona görə `issued_by=ACTOR_ID` yazmaq
    fake-də mümkündür — REAL sistemdə DEYİL. Test adı "self-publish mümkündür"
    İDDİASI SƏSLƏNDİRMİR — məhz bu səbəbdən.
    """
    context = _Context(fines_by_period={"2026-08": [_FakeFine(issued_by=ACTOR_ID)]})
    context.fine_review.result_published = [FINE_ID]
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch, confirm=True)

    _click(screen, "Bütün Filiallara Göndər")

    assert len(context.fine_review.publish_calls) == 1, (
        "Kontroller/use case qatı issued_by-ı yoxlamadan çağırışı ötürdü — "
        "qapı buradan aşağıdadır (bax modul başlığı), REAL istismar DEYİL"
    )
    assert any(s.committed for s in context.sessions)


# --------------------------------------------------------------------------- #
# 3. Real sətir/qrup qərarı — "Sil" səbəbi, qısa səbəb, malformed kod
# --------------------------------------------------------------------------- #


@requires_qt
def test_discarding_a_row_via_the_real_button_prompts_for_a_reason(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("kamera nasazlığı", True))
    )
    context = _Context()
    context.fine_review.result_discarded = [FINE_ID]
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch, confirm=True)

    _click(screen, "Sil")
    assert screen.decisions()[0]["decision"] == "DISCARD"
    assert screen.decisions()[0]["reason"] == "kamera nasazlığı"

    _click(screen, "Bütün Filiallara Göndər")

    call = context.fine_review.publish_calls[0]
    assert call["decisions"][0].reason == "kamera nasazlığı"


@requires_qt
def test_a_discard_reason_shorter_than_the_domain_minimum_is_rejected_by_the_real_prompt(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.fine_review import SHORT_REASON

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("qısa", True))
    )
    context = _Context()
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch)

    _click(screen, "Sil")

    assert screen.decisions()[0]["decision"] == "KEEP", "Qısa səbəb qərarı DƏYİŞMƏMƏLİDİR"
    assert screen._error.text() == SHORT_REASON


@requires_qt
def test_group_discard_applies_the_same_reason_to_every_row_in_the_store(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("səhv dövr seçilib", True))
    )
    second_id = uuid.uuid4()
    context = _Context(fines_by_period={"2026-08": [_FakeFine(), _FakeFine(fine_id=second_id)]})
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch)

    _click(screen, "Hamısı: Sil")

    decisions = {row["fine_id"]: row for row in screen.decisions()}
    assert decisions[str(FINE_ID)]["decision"] == "DISCARD"
    assert decisions[str(second_id)]["decision"] == "DISCARD"
    assert decisions[str(FINE_ID)]["reason"] == "səhv dövr seçilib"
    assert decisions[str(second_id)]["reason"] == "səhv dövr seçilib"


@requires_qt
def test_a_malformed_decision_code_from_a_stale_signal_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.fine_review import UNKNOWN_DECISION

    context = _Context()
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch)

    screen.decision_requested.emit(str(FINE_ID), "GARBAGE_CODE")  # ÇÖKMƏMƏLİDİR

    assert screen._error.text() == UNKNOWN_DECISION
    assert screen.decisions()[0]["decision"] == "KEEP"


@requires_qt
def test_hostile_and_extreme_reason_text_passes_through_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    hostile = "'; DROP TABLE fines; -- 🔥" + "A" * 10_000
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (hostile, True))
    )
    context = _Context()
    context.fine_review.result_discarded = [FINE_ID]
    screen = _build(theme, qtbot, context, monkeypatch=monkeypatch, confirm=True)

    _click(screen, "Sil")  # ÇÖKMƏMƏLİDİR
    _click(screen, "Bütün Filiallara Göndər")

    call = context.fine_review.publish_calls[0]
    assert call["decisions"][0].reason == " ".join(hostile.split())
