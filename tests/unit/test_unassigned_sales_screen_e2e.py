"""`UnassignedSalesScreen` ↔ `SalesReviewController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_sales_review_controller.py` sahtə `_Screen`/`_SalesReview` siniflərlə
ölçür — REAL `group_f.UnassignedSalesScreen`-in "Təyin Et" düymələri, REAL
işçi açılan siyahısı (`QComboBox`) və REAL "Seçilmişləri Toplu Təyin Et"
düyməsi heç vaxt qurulmur. Burada onlar əl ilə klikllənir/seçilir.
`ReviewQueueItem` REAL `application` tipidir (`sales_review_queue.py`) —
yalnız `session.sales_review` (use case sərhədi) sahtələnir, eyni sərhəd
`test_pos_threshold_screen_e2e.py`/`test_catalog_screen_e2e.py`-dədir.

──────────────────────────────────────────────────────────────────────────────
"TƏSDİQ" ↔ "KÖÇÜRMƏ" AYRIMI VƏ SÜRƏTLİ İKİQAT KLİK
──────────────────────────────────────────────────────────────────────────────
Kontroller sətri seçilmiş işçi 1C-nin təklifi ilə EYNİDİRSƏ `confirm()`,
FƏRQLİDİRSƏ `reassign()` çağırır (bax `sales_review.py` başlığı). Aşağıda hər
iki qol REAL kliklə sınanır. "Sürətli ikiqat klik" sınağı isə köhnə (artıq
`deleteLater()`-lənmiş, lakin Python tərəfdə hələ canlı) "Təyin Et" düyməsinə
İKİNCİ dəfə basmağı təqlid edir — `_items` xəritəsi hər `refresh()`-də
yeniləndiyi üçün ikinci klik "Siyahı köhnəlib" ilə rədd edilir, TƏKRAR
təyinat YAZILMIR.

──────────────────────────────────────────────────────────────────────────────
DÜZƏLDİLMİŞ QÜSUR — XƏTA BANNERİ SÜKUTLA ÜSTÜNDƏN YAZILIRDI
──────────────────────────────────────────────────────────────────────────────
`controllers/sales_review.py::_apply()` `except KompasOSError`/`except
Exception` qollarının HƏR İKİSİNDƏ ƏVVƏL `screen.show_error(...)`-dan DƏRHAL
SONRA `self.refresh(screen)` çağırılırdı. Uğurlu `refresh()` `show_content()`/
`show_empty()` işə salır və İSTİFADƏÇİNİN indicə gördüyü xəta mesajını EYNİ
funksiya çağırışı içində sükutla əvəz edirdi — istifadəçi "niyə yazılmadı"
sualının cavabını GÖRMÜRDÜ. `catalog_admin.py`-dəki eyni naxış (`_save`/
`_on_toggle`) DÜZGÜN idi: xəta qollarında `refresh()` ÇAĞIRILMIR, yalnız
`return`. Bu, `menu.py` başlığında qeyd olunan "banner `refresh()` ilə
sükutla ÜSTÜNDƏN yazılır" (`announcements.py`) qüsurunun EYNİSİ idi.

DÜZƏLİŞ (`ui` sahibi): iki `refresh()` çağırışı silindi (yalnız `return`
qalır — `catalog_admin.py` naxışı). `test_a_failed_assignment_error_banner_
is_not_silently_overwritten_by_the_trailing_refresh`-in `xfail` markeri
silinib; həmin bugu "gözlənilən" kimi sənədləşdirən İKİ digər test
(`test_an_employee_not_in_the_active_list_is_rejected_with_a_clear_message`,
`test_a_reassign_failure_shows_the_domain_message_and_does_not_commit`) də
DÜZGÜN nəticəyə ("error") yenilənib.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.sales_review_queue import ReviewQueueItem
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.money import Money
from src.presentation.controllers.sales_review import BULK_REASON, SINGLE_REASON
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()

EMPLOYEE_A_ID = uuid.uuid4()
EMPLOYEE_B_ID = uuid.uuid4()
EMPLOYEE_A_NAME = "Aygün Məmmədova"
EMPLOYEE_B_NAME = "Elvin Əliyev"
EMPLOYEE_ROWS = [
    (EMPLOYEE_A_ID, "Aygün", "Məmmədova"),
    (EMPLOYEE_B_ID, "Elvin", "Əliyev"),
]
EMPLOYEE_NAMES = [EMPLOYEE_A_NAME, EMPLOYEE_B_NAME]


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


def _select_employee(screen: Any, receipt: str, name: str) -> None:
    combo = screen._combos[receipt]
    combo.setCurrentText(name)


def _click_assign(screen: Any, receipt: str) -> None:
    """Verilmiş çekin ÖZ sətrindəki "Təyin Et" düyməsini klikləyir.

    Ümumi `_click(screen, "Təyin Et")` YANLIŞ ola bilər: `refresh()` köhnə
    `DataTable` sətirlərini `deleteLater()` ilə silir (dərhal DEYİL, gələcək
    hadisə dövrəsi üçün planlaşdırılır), ona görə eyni mətnli KÖHNƏ düymələr
    `findChildren()`-də bir müddət YENİ ilə YANAŞI qalır və `next(...)` səhv
    (silinmiş sətrə aid) düyməni tuta bilər. Buradakı axtarış combo-nun ÖZ
    valideynindən (`action_cell`) başlayır — hər çağırışda TƏZƏ, `_combos`
    xəritəsindən oxunur, ona görə həmişə CARİ sətrə aiddir.
    """
    from PySide6.QtWidgets import QPushButton

    combo = screen._combos[receipt]
    action_cell = combo.parentWidget()
    button = next(b for b in action_cell.findChildren(QPushButton) if b.text() == "Təyin Et")
    button.click()


def _item(
    *,
    receipt: str = "R-1001",
    suggested_id: Any = None,
    suggested_name: str = "",
    confidence: MatchConfidence = MatchConfidence.EXACT_MATCH,
    amount: Decimal = Decimal("120.00"),
) -> ReviewQueueItem:
    return ReviewQueueItem(
        transaction_id=uuid.uuid4(),
        server_name="Mərkəz-1",
        one_c_seller_id="S-01",
        one_c_seller_name=suggested_name or None,
        one_c_store_code="ST-01",
        one_c_document_id=receipt,
        gross_amount=Money(amount),
        transaction_date=datetime(2026, 8, 20, 14, 30, tzinfo=UTC),
        confidence=confidence,
        match_reason=None,
        suggested_employee_id=suggested_id,
        suggested_employee_name=suggested_name,
        store_id=uuid.uuid4(),
    )


# --------------------------------------------------------------------------- #
# Sahtələr — YALNIZ use case/DB sərhədi. `ReviewQueueItem` REAL tipdir.
# --------------------------------------------------------------------------- #


class _FakeSalesReview:
    """`session.sales_review`-in yerini tutur — REAL imza, "DB" yaddaşda."""

    def __init__(self, items: list[ReviewQueueItem]) -> None:
        self._items: dict[Any, ReviewQueueItem] = {item.transaction_id: item for item in items}
        self.confirms: list[Any] = []
        self.reassigns: list[dict[str, Any]] = []
        self.queue_error: KompasOSError | None = None
        self.reassign_error: KompasOSError | None = None
        self.queue_calls = 0

    def queue(
        self, *, tenant_id: Any, actor: Any, server_id: Any = None, limit: Any = None
    ) -> list[ReviewQueueItem]:
        self.queue_calls += 1
        if self.queue_error is not None:
            raise self.queue_error
        return list(self._items.values())

    def confirm(self, *, tenant_id: Any, actor: Any, transaction_id: Any) -> None:
        self.confirms.append(transaction_id)
        self._items.pop(transaction_id, None)  # real repo: sətir NÖVBƏDƏN çıxır

    def reassign(
        self, *, tenant_id: Any, actor: Any, transaction_id: Any, employee_id: Any, reason: str
    ) -> None:
        if self.reassign_error is not None:
            raise self.reassign_error
        self.reassigns.append(
            {"transaction_id": transaction_id, "employee_id": employee_id, "reason": reason}
        )
        self._items.pop(transaction_id, None)


class _Row(dict):
    pass


class _Connection:
    def __init__(self, employees: list[tuple[Any, str, str]]) -> None:
        self._employees = employees

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [
            _Row(id=eid, first_name=first, last_name=last) for eid, first, last in self._employees
        ]


class _Uow:
    def __init__(self, employees: list[tuple[Any, str, str]]) -> None:
        self.connection = _Connection(employees)


class _Limits:
    def __init__(self, percent: int = 50) -> None:
        self._percent = percent

    def get_int(self, _tenant_id: Any, _key: str, _fallback: int) -> int:
        return self._percent


class _Session:
    def __init__(
        self, sales_review: _FakeSalesReview, employees: list[tuple[Any, str, str]], limits: Any
    ) -> None:
        self.tenant_id = TENANT
        self.sales_review = sales_review
        self.limits = limits
        self.uow = _Uow(employees)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(
        self,
        sales_review: _FakeSalesReview,
        *,
        employees: list[tuple[Any, str, str]] | None = None,
        limits: Any = None,
    ) -> None:
        self._sales_review = sales_review
        self._employees = employees if employees is not None else EMPLOYEE_ROWS
        self._limits = limits or _Limits()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._sales_review, self._employees, self._limits)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _attach(sales_review: _FakeSalesReview, *, qtbot: Any, theme: Any, limits: Any = None):
    from src.presentation.controllers.sales_review import SalesReviewController
    from src.presentation.screens.group_f import UnassignedSalesScreen

    screen = UnassignedSalesScreen(theme, employees=EMPLOYEE_NAMES)
    qtbot.addWidget(screen)
    context = _Context(sales_review, limits=limits)
    SalesReviewController(context, _Actor()).attach(screen)
    return screen, context


# --------------------------------------------------------------------------- #
# 1. Real siyahı — `attach()` REAL `queue()` çağırır
# --------------------------------------------------------------------------- #


def _press_retry(screen: Any) -> None:
    """Xəta banner-indəki «Yenidən Cəhd Et» düyməsini HƏQİQƏTƏN basır.

    Siqnalı birbaşa yaymaq kifayət etməzdi: UI-R4-01-ə görə `on_retry`
    verilməyəndə düymə ÜMUMİYYƏTLƏ çəkilmir (bax `ContentSwitcher.show_error`
    docstring-i). Yəni düymənin MÖVCUDLUĞU testin əsl iddiasıdır — banner
    yenilənməni istifadəçiyə buraxırsa, o yenilənməni başlatmaq YOLU da
    olmalıdır.
    """
    from PySide6.QtWidgets import QPushButton

    state = screen.switcher()._stack.currentWidget()
    button = state.findChild(QPushButton)
    assert button is not None, "Xəta banner-i «Yenidən Cəhd Et» düyməsi olmadan ölü dalandır"
    button.click()


@requires_qt
def test_attach_loads_the_real_queue_and_shows_content(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview(
        [_item(receipt="R-1"), _item(receipt="R-2", amount=Decimal("30.00"))]
    )
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme)

    assert screen.switcher().current_state() == "content"
    assert screen.table().row_count == 2


@requires_qt
def test_an_empty_queue_shows_the_real_empty_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview([])
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme)

    assert screen.switcher().current_state() == "empty"


# --------------------------------------------------------------------------- #
# 2. Real "Təyin Et" — TƏSDİQ ↔ KÖÇÜRMƏ ayrımı
# --------------------------------------------------------------------------- #


@requires_qt
def test_assigning_a_different_employee_than_the_suggestion_reassigns(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview(
        [_item(receipt="R-1", suggested_id=EMPLOYEE_A_ID, suggested_name=EMPLOYEE_A_NAME)]
    )
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    _select_employee(screen, "R-1", EMPLOYEE_B_NAME)
    _click_assign(screen, "R-1")

    assert sales_review.confirms == []
    assert len(sales_review.reassigns) == 1
    assert sales_review.reassigns[0]["employee_id"] == EMPLOYEE_B_ID
    assert sales_review.reassigns[0]["reason"] == SINGLE_REASON
    assert any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "empty"  # sətir növbədən çıxdı


@requires_qt
def test_assigning_the_suggested_employee_confirms_instead_of_reassigning(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview(
        [_item(receipt="R-1", suggested_id=EMPLOYEE_A_ID, suggested_name=EMPLOYEE_A_NAME)]
    )
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    _select_employee(screen, "R-1", EMPLOYEE_A_NAME)
    _click_assign(screen, "R-1")

    assert sales_review.reassigns == []
    assert len(sales_review.confirms) == 1
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_the_placeholder_combo_entry_makes_the_button_do_nothing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Combo "İşçi seç"-də qalıbsa `_on_assign` erkən çıxır — `assigned` HEÇ YAYILMIR."""
    sales_review = _FakeSalesReview([_item(receipt="R-1")])
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    _click_assign(screen, "R-1")  # combo "İşçi seç"-də

    assert sales_review.confirms == []
    assert sales_review.reassigns == []
    assert not any(s.committed for s in context.sessions)


# --------------------------------------------------------------------------- #
# 3. Real "Seçilmişləri Toplu Təyin Et" — bir sessiya, çox təyinat
# --------------------------------------------------------------------------- #


@requires_qt
def test_bulk_assign_resolves_multiple_selected_rows_in_a_single_session(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview(
        [
            _item(receipt="R-1", suggested_id=EMPLOYEE_A_ID, suggested_name=EMPLOYEE_A_NAME),
            _item(receipt="R-2"),
        ]
    )
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    _select_employee(screen, "R-1", EMPLOYEE_B_NAME)  # KÖÇÜRMƏ
    _select_employee(screen, "R-2", EMPLOYEE_A_NAME)  # TƏYİNAT (təklif yoxdur)
    _click(screen, "Seçilmişləri Toplu Təyin Et")

    assert len(sales_review.reassigns) == 2
    assert {r["reason"] for r in sales_review.reassigns} == {BULK_REASON}
    assert screen.switcher().current_state() == "empty"
    # Toplu əməliyyat BİR sessiyadadır (bax modul başlığı): 1 ilkin oxu +
    # 1 toplu yazı + 1 yazıdan sonrakı `refresh()` = 3. Əks halda hər cüt
    # ÖZ sessiyasında yazılsaydı, say 4 olardı.
    assert len(context.sessions) == 3


@requires_qt
def test_bulk_assign_with_nothing_selected_shows_an_error_and_writes_nothing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview([_item(receipt="R-1")])
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme)
    calls_before = sales_review.queue_calls

    _click(screen, "Seçilmişləri Toplu Təyin Et")  # heç bir combo seçilməyib

    assert sales_review.confirms == []
    assert sales_review.reassigns == []
    # ƏVVƏL BURADA `queue_calls > calls_before` YAZILMIŞDI və test qüsuru
    # kilidləyirdi: «Sətir seçilməyib» banner-i göstərildikdən DƏRHAL sonra
    # `refresh()` çağırılır, `set_sales()` → `show_content()` isə switcher-i
    # «content»-ə qaytarıb xəbərdarlığın üstündən yazırdı — operator boş
    # seçimlə düyməni basır və HEÇ NƏ görmürdü.
    assert sales_review.queue_calls == calls_before, "Xəbərdarlıq yenilənmə ilə udulmamalıdır"
    assert screen.switcher().current_state() == "error"

    _press_retry(screen)

    assert sales_review.queue_calls > calls_before
    assert screen.switcher().current_state() == "content"


# --------------------------------------------------------------------------- #
# 4. Hər əməliyyat öz sessiyasında — TƏK təyinatla ziddiyyət təşkil edir
# --------------------------------------------------------------------------- #


@requires_qt
def test_two_separate_single_assignments_each_use_their_own_session(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview([_item(receipt="R-1"), _item(receipt="R-2")])
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    _select_employee(screen, "R-1", EMPLOYEE_A_NAME)
    _click_assign(screen, "R-1")
    _select_employee(screen, "R-2", EMPLOYEE_B_NAME)
    _click_assign(screen, "R-2")

    assert len(sales_review.confirms) + len(sales_review.reassigns) == 2
    # 1 ilkin oxu + (1 yazı + 1 refresh) × 2 = 5 — bax `test_bulk_assign_...`
    # ilə ZİDDİYYƏT: TƏK təyinat hər dəfə TƏZƏ sessiya açır.
    assert len(context.sessions) == 5


# --------------------------------------------------------------------------- #
# 5. Sürətli ikiqat klik — köhnə düymə TƏKRAR yazı YARATMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_rapid_double_click_on_assign_does_not_write_twice(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    sales_review = _FakeSalesReview(
        [_item(receipt="R-1", suggested_id=EMPLOYEE_A_ID, suggested_name=EMPLOYEE_A_NAME)]
    )
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme)
    _select_employee(screen, "R-1", EMPLOYEE_B_NAME)

    stale_button = next(b for b in screen.findChildren(QPushButton) if b.text() == "Təyin Et")
    stale_button.click()  # 1-ci klik: köçürür, cədvəl (boş) YENİDƏN qurulur
    stale_button.click()  # 2-ci klik: EYNİ (artıq silinmiş sətrə aid) Python obyektinə

    assert len(sales_review.reassigns) == 1  # TƏKRAR YAZI YOXDUR
    assert screen.switcher().current_state() == "empty"


# --------------------------------------------------------------------------- #
# 6. Köhnəlmiş/naməlum sətir və işçi — çökmür, açıq mesaj
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_unknown_receipt_from_a_stale_row_shows_an_error_and_refreshes_on_retry(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview([_item(receipt="R-1")])
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    screen.assigned.emit("R-999-STALE", EMPLOYEE_A_NAME)  # ÇÖKMƏMƏLİDİR

    assert sales_review.confirms == []
    assert sales_review.reassigns == []
    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error", (
        "«Siyahı köhnəlib» səbəbi görünməlidir — əvvəl dərhal gələn `refresh()` "
        "onu `set_sales()` → `show_content()` ilə udurdu"
    )

    _press_retry(screen)

    assert screen.switcher().current_state() == "content"  # R-1 hələ növbədədir


@requires_qt
@pytest.mark.parametrize(
    "malicious_receipt",
    [
        "",
        " ",
        "🔥" * 50,
        "'; DROP TABLE sales_transactions; --",
        "R-1" + "9" * 10_000,
    ],
)
def test_extreme_receipt_strings_via_a_direct_signal_do_not_crash(
    qtbot, theme, malicious_receipt: str
) -> None:  # type: ignore[no-untyped-def]
    """Real UI çeki heç vaxt belə yazmaz — bu, artıq navbədən çıxmış/korlanmış
    sətrə aid gecikmiş siqnalı təqlid edir. Heç biri `_items`-də olmadığı üçün
    "Siyahı köhnəlib" qolu işə düşməlidir, çökmə YOX."""
    sales_review = _FakeSalesReview([_item(receipt="R-1")])
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme)

    screen.assigned.emit(malicious_receipt, EMPLOYEE_A_NAME)  # ÇÖKMƏMƏLİDİR

    assert sales_review.confirms == []
    assert sales_review.reassigns == []


@requires_qt
def test_an_employee_not_in_the_active_list_is_rejected_with_a_clear_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Combo-nun ÖZÜ yalnız aktiv siyahıdan icazə versə də, siqnal BİRBAŞA
    yayılsa (köhnəlmiş widget, xarici çağırış) kontroller çökməməlidir."""
    sales_review = _FakeSalesReview([_item(receipt="R-1")])
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    screen.assigned.emit("R-1", "Naməlum Şəxs")  # ÇÖKMƏMƏLİDİR

    assert sales_review.confirms == []
    assert sales_review.reassigns == []
    assert not any(s.committed for s in context.sessions)
    # DÜZƏLDİLDİ (`ui` sahibi): `_apply()`-in xəta qolu artıq `show_error()`-
    # dan sonra `refresh()` ÇAĞIRMIR — banner sükutla əvəzlənmir, istifadəçi
    # səbəbi görür (bax `test_a_failed_assignment_error_banner_is_not_
    # silently_overwritten_by_the_trailing_refresh`).
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 7. Use case istisnası — real klik, açıq mesaj, rollback
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_reassign_failure_shows_the_domain_message_and_does_not_commit(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview([_item(receipt="R-1")])
    sales_review.reassign_error = KompasOSError(
        "balans qeyri-kafi", user_message="Xal balansı köçürülə bilmədi."
    )
    screen, context = _attach(sales_review, qtbot=qtbot, theme=theme)

    _select_employee(screen, "R-1", EMPLOYEE_A_NAME)
    _click_assign(screen, "R-1")  # ÇÖKMƏMƏLİDİR

    assert sales_review.reassigns == []
    assert not any(s.committed for s in context.sessions)
    # DÜZƏLDİLDİ — bax yuxarıdakı şərh.
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_failed_assignment_error_banner_is_not_silently_overwritten_by_the_trailing_refresh(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    sales_review = _FakeSalesReview([_item(receipt="R-1")])
    sales_review.reassign_error = KompasOSError(
        "balans qeyri-kafi", user_message="Xal balansı köçürülə bilmədi."
    )
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme)

    _select_employee(screen, "R-1", EMPLOYEE_A_NAME)
    _click_assign(screen, "R-1")

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 8. Uyğunluq rənginin həddi — CANLI ROOT dəyəri, ekranın öz fallback-ı DEYİL
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_confidence_color_threshold_comes_from_the_live_root_limit(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`UnassignedSalesScreen.FALLBACK_LOW_CONFIDENCE_PERCENT` (50) ilə QƏSDƏN
    FƏRQLİ bir hədd (65) verilir — 60%-lik sətir yalnız CANLI dəyər həqiqətən
    ötürülübsə xəbərdarlıq rənginə düşür."""
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.group_f import UnassignedSalesScreen

    assert UnassignedSalesScreen.FALLBACK_LOW_CONFIDENCE_PERCENT == 50  # nəzarət fərziyyəsi

    sales_review = _FakeSalesReview(
        [
            _item(receipt="R-1", confidence=MatchConfidence.UNASSIGNED),  # 0%
            _item(
                receipt="R-2",
                confidence=MatchConfidence.LOW_CONFIDENCE_MATCH,
                suggested_id=EMPLOYEE_A_ID,
                suggested_name=EMPLOYEE_A_NAME,
            ),  # 60%
        ]
    )
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme, limits=_Limits(percent=65))

    labels = {lbl.text(): lbl for lbl in screen.findChildren(QLabel)}
    assert "color" in labels["0%"].styleSheet()  # hər zaman xəbərdarlıqdadır
    assert "color" in labels["60%"].styleSheet()  # YALNIZ 65 hədd altında xəbərdarlıqdadır


@requires_qt
def test_the_confidence_color_threshold_does_not_warn_above_the_live_limit(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel

    sales_review = _FakeSalesReview(
        [
            _item(
                receipt="R-2",
                confidence=MatchConfidence.LOW_CONFIDENCE_MATCH,
                suggested_id=EMPLOYEE_A_ID,
                suggested_name=EMPLOYEE_A_NAME,
            )
        ]
    )
    screen, _ = _attach(sales_review, qtbot=qtbot, theme=theme, limits=_Limits(percent=40))

    label = next(lbl for lbl in screen.findChildren(QLabel) if lbl.text() == "60%")
    assert label.styleSheet() == ""  # 60 >= 40 həddi — xəbərdarlıq YOXDUR
