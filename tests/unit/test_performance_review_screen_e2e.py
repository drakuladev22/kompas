"""`PerformanceReviewScreen` ↔ `PerformanceReviewController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/performance_review.py` `tests/` daxilində HEÇ YERDƏ adı
çəkilmirdi. Ekran HƏM oxuyur (işçi dropdown-u, KPI kataloqu), HƏM yazır
("Yadda Saxla") — burada real dropdown seçimi, real KPI combo-ları və real
"Yadda Saxla" kliki ilə tam axın sınanır.

REYTİNQ SƏRHƏDLƏRİ (0, mənfi, 6, 999): `_build_kpi_row` KPI balını YALNIZ
1–5 seçimli `QComboBox`-la təqdim edir (`_SCORE_CHOICES`, modul başlığı:
"ROOT parametri deyil, ölçü vahididir") — istifadəçi UI-dan naməlum bal
SEÇƏ BİLMİR. Bu, quruluş etibarilə qoruma deməkdir; aşağıda REAL widget
introspeksiyası ilə yoxlanılır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
EMPLOYEE_A = str(uuid.uuid4())
EMPLOYEE_B = str(uuid.uuid4())


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


def _kpi() -> Any:
    from src.application.use_cases.performance_reviews import KpiDefinition

    return KpiDefinition(code="SALES", label_az="Satış nəticələri")


def _history_view(*, employee_id: str, period: str = "2026-Q2") -> Any:
    from datetime import UTC, datetime

    from src.application.use_cases.performance_reviews import PerformanceReviewView

    return PerformanceReviewView(
        review_id=uuid.uuid4(),
        employee_id=employee_id,
        reviewer_id=ACTOR_ID,
        period=period,
        ratings={"SALES": 4},
        overall_score=4,
        notes="Yaxşı rüb",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    def __init__(self, employees: list[tuple[str, str, str]]) -> None:
        self._employees = employees

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [
            _Row(id=eid, first_name=first, last_name=last) for eid, first, last in self._employees
        ]


class _Uow:
    def __init__(self, employees: list[tuple[str, str, str]]) -> None:
        self.connection = _Connection(employees)


class _PerformanceReviews:
    def __init__(self) -> None:
        self.kpi_error: KompasOSError | None = None
        self.submissions: list[dict[str, Any]] = []
        self.submit_error: KompasOSError | None = None
        self.history: dict[str, list[Any]] = {}

    def kpi_catalog(self, _tenant_id: Any) -> list[Any]:
        if self.kpi_error is not None:
            raise self.kpi_error
        return [_kpi()]

    def default_period(self, _tenant_id: Any) -> str:
        return "2026-Q3"

    def list_for_employee(self, *, tenant_id: Any, actor: Any, employee_id: Any) -> list[Any]:
        return list(self.history.get(str(employee_id), []))

    def submit_review(self, **kwargs: Any) -> None:
        if self.submit_error is not None:
            raise self.submit_error
        self.submissions.append(kwargs)


class _Priority:
    value = 2


class _Session:
    def __init__(
        self, performance_reviews: _PerformanceReviews, employees: list[tuple[str, str, str]]
    ) -> None:
        self.tenant_id = TENANT
        self.performance_reviews = performance_reviews
        self.uow = _Uow(employees)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(
        self,
        performance_reviews: _PerformanceReviews,
        employees: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self._performance_reviews = performance_reviews
        self._employees = employees or []
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._performance_reviews, self._employees)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID
    priority = _Priority()


# --------------------------------------------------------------------------- #
# 1. Real doldurma — dropdown, KPI kataloqu, dövr
# --------------------------------------------------------------------------- #


@requires_qt
def test_attach_fills_the_real_employee_and_kpi_dropdowns(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QComboBox

    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    reviews.history[EMPLOYEE_A] = [_history_view(employee_id=EMPLOYEE_A)]
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)

    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    combo = screen._employee.input_widget()
    assert isinstance(combo, QComboBox)
    assert combo.count() == 1
    assert combo.itemText(0) == "Aygün Məmmədova"
    assert screen._period.text() == "2026-Q3"
    # İlk işçi AVTOMATİK seçilir (`set_employees` başlığı) — tarixçə DƏRHAL gəlir.
    assert "Yaxşı rüb" in _all_labels(screen)


@requires_qt
def test_the_kpi_score_combo_only_offers_one_through_five(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UI STRUKTURCA 0/mənfi/6/999 seçilməsinin QARŞISINI ALIR (yoxlama, bug DEYİL)."""
    from PySide6.QtWidgets import QComboBox

    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    kpi_combo = screen._kpi_inputs["SALES"]
    assert isinstance(kpi_combo, QComboBox)
    values = [kpi_combo.itemData(i) for i in range(kpi_combo.count())]
    assert values == [1, 2, 3, 4, 5]


@requires_qt
def test_switching_the_real_dropdown_reloads_history_for_the_new_employee(
    qtbot, qt_app, theme
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QComboBox

    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    reviews.history[EMPLOYEE_A] = [_history_view(employee_id=EMPLOYEE_A, period="A-dövrü")]
    reviews.history[EMPLOYEE_B] = [_history_view(employee_id=EMPLOYEE_B, period="B-dövrü")]
    context = _Context(
        reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova"), (EMPLOYEE_B, "Kamran", "Əliyev")]
    )
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    combo = screen._employee.input_widget()
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(1)  # REAL dropdown seçimi — `currentIndexChanged` özü yayır

    # `set_history()` köhnə sətirləri `clear_layout()`/`deleteLater()` ilə
    # silir — faktiki silinmə YALNIZ təxirə salınmış hadisə emal ediləndə
    # baş verir (`test_announcements_screen_e2e.py`-dəki eyni tələ).
    from PySide6.QtCore import QEvent

    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()

    assert any("B-dövrü" in text for text in _all_labels(screen))
    assert not any("A-dövrü" in text for text in _all_labels(screen))


# --------------------------------------------------------------------------- #
# 2. Real "Yadda Saxla" — uğur, boş sahələr, ekstremal mətn
# --------------------------------------------------------------------------- #


@requires_qt
def test_submitting_via_the_real_button_commits_and_reloads_history(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen._notes.setPlainText("Çox məhsuldar rüb oldu.")
    _click(screen, "Yadda Saxla")

    assert len(reviews.submissions) == 1
    submission = reviews.submissions[0]
    assert str(submission["employee_id"]) == EMPLOYEE_A
    assert submission["period"] == "2026-Q3"
    assert submission["ratings"] == {"SALES": 3}  # combo defolt ortadadır (3)
    assert submission["notes"] == "Çox məhsuldar rüb oldu."
    assert any(s.committed for s in context.sessions)
    assert screen._error.isVisible() is False


@requires_qt
def test_submitting_with_no_employees_shows_the_real_validation_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Dropdown boşdursa `currentData()` `None`-dır — REAL klik yazı yoluna girmir."""
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    context = _Context(reviews, [])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Yadda Saxla")

    assert reviews.submissions == []
    assert screen._error.text() == "İşçi seçin."
    assert screen._error.isVisible()


@requires_qt
def test_submitting_with_an_empty_period_shows_a_real_field_error(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen._period.set_text("")
    _click(screen, "Yadda Saxla")

    assert reviews.submissions == []
    assert screen._period.has_error


@requires_qt
def test_hostile_and_extreme_notes_pass_through_without_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    hostile = "'; DROP TABLE performance_reviews; -- 🔥" + "A" * 10_000
    screen._notes.setPlainText(hostile)
    _click(screen, "Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert len(reviews.submissions) == 1
    assert reviews.submissions[0]["notes"] == hostile.strip()


# --------------------------------------------------------------------------- #
# 3. Use-case istisnası, malformed ID, oxu xətası — çökmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_hierarchy_rejection_shows_the_domain_message_and_does_not_commit(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`submit_review`-in Strict Hierarchy Guard-ı — real klik AÇIQ mesaj göstərir."""
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    reviews.submit_error = KompasOSError(
        "hierarchy", user_message="Bu işçini qiymətləndirmək səlahiyyətiniz yoxdur."
    )
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen._error.text() == "Bu işçini qiymətləndirmək səlahiyyətiniz yoxdur."
    assert screen._error.isVisible()


@requires_qt
def test_a_malformed_employee_id_in_the_submit_payload_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    context = _Context(reviews, [])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.submit_requested.emit(
        {"employee_id": "not-a-uuid", "period": "2026-Q3", "ratings": {}, "notes": ""}
    )  # ÇÖKMƏMƏLİDİR

    assert reviews.submissions == []
    assert screen._error.text() == "İşçi identifikatoru düzgün deyil."


@requires_qt
def test_kpi_catalog_read_failure_shows_an_error_instead_of_a_blank_form(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    reviews.kpi_error = KompasOSError("db down", user_message="Baza əlaqəsi kəsildi.")
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)

    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_malformed_employee_id_selected_in_the_dropdown_clears_history_not_crashes(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`employee_selected` düzgün UUID DAŞIYIR (kombonun `userData`-sı) — buna baxmayaraq
    `_on_employee_selected`-in `ValueError` qoruyucusu birbaşa siqnal emiti ilə də sınanır."""
    from src.presentation.controllers.performance_review import PerformanceReviewController
    from src.presentation.screens.performance_review import PerformanceReviewScreen

    reviews = _PerformanceReviews()
    context = _Context(reviews, [(EMPLOYEE_A, "Aygün", "Məmmədova")])
    screen = PerformanceReviewScreen(theme)
    qtbot.addWidget(screen)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    PerformanceReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.employee_selected.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert screen._history_empty.isVisible()


def _all_labels(screen: Any) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in screen.findChildren(QLabel)]
