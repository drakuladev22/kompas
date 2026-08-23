"""`EmployeeHomeScreen` ↔ `KioskSelfServiceController` — REAL düymə kliki ilə e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_kiosk_self_service.py` REAL ekranlar qurur (`EmployeeHomeScreen`,
`TasksScreen`, `FineAppealScreen`), LAKİN heç bir testdə REAL «Hamısına bax →»
/ «Mükafat kataloqu →» / «Etiraz Et» düyməsi klikLƏNMİR — hər ssenari
`home.tasks_requested.emit()` kimi SİQNALI BİRBAŞA yayır. Bu, məhz CLAUDE.md-
nin təsvir etdiyi qüsur naxışıdır: «düymə bağlanmışdı, test onu ADLA
xatırlayırdı, lakin heç vaxt ÇAĞIRMIRDI».

Burada üç keçid REAL düymə kliki ilə açılır.

──────────────────────────────────────────────────────────────────────────────
İKİNCİ BÖLMƏ — TAPILMIŞ VƏ ARTIQ DÜZƏLDİLMİŞ QÜSUR (`ui-fixes`)
──────────────────────────────────────────────────────────────────────────────
Real klik `_fine_rows()`/`set_history()` arasında açar uyğunsuzluğunu üzə
çıxartdı: `_fine_rows()` sətri `"fine_id"` açarı ilə qururdu, `FineAppealScreen.
set_history()` isə `"id"` açarını VƏ `"appealable" == "1"` bayrağını
axtarırdı — heç biri uyğun gəlmirdi və kiosk «Cərimələrim» tarixçəsində HEÇ
BİR sətirdə «Etiraz Et» düyməsi görünmürdü. Zəncirvari nəticə: `_open_fines()`
`start_appeal()`-i başqa heç yerdən çağırmadığı üçün etiraz forması real
istifadəçiyə ÜMUMİYYƏTLƏ ƏLÇATAN DEYİLDİ — bu modulun mövcud olma səbəbi olan
köhnə qüsur ("cərimə etirazı interfeysdən ÜMUMİYYƏTLƏ əlçatan deyildi", bax
`kiosk_self_service.py` başlığı) sükutla GERİ QAYITMIŞDI.

`ui-fixes` `_fine_rows()`-a `"id"` və `"appealable"` açarlarını əlavə etdi
(bax həmin faylın şərhi). `test_the_per_fine_appeal_button_must_render_for_
an_open_fine` İNDİ YAŞILDIR — sətir düyməsi real klik + real widget ağacı ilə
təsdiqlənir. `test_clicking_the_general_appeal_card_never_opens_a_submittable_
form` HƏLƏ DƏ YAŞILDIR, LAKİN fərqli səbəbdən: ÜMUMİ «Etiraz Et» kart keçidi
(boş formaya) HƏLƏ DƏ `start_appeal()` çağırmır — bu, DÜZGÜN davranışdır
(forma KONKRET bir cərimə seçilmədən açılmamalıdır), qüsur DEYİL. Real
istifadəçi indi SƏTİR düyməsi ilə formaya çata bilir.
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

NOW = datetime(2026, 8, 22, 9, 30, tzinfo=UTC)
FINE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


class _Task:
    def __init__(self, title: str) -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.deadline = NOW


class _Money:
    def __init__(self, amount: Decimal) -> None:
        self.amount = amount


class _Fine:
    def __init__(self) -> None:
        self.id = FINE_ID
        self.amount = _Money(Decimal("25"))
        self.issued_at = NOW


class _Appeal:
    def __init__(self, *, open_: bool) -> None:
        self.fine_id = FINE_ID

        class _Status:
            is_open = open_

        self.status = _Status()


class _Row(dict):  # type: ignore[type-arg]
    pass


class _Cursor:
    def fetchone(self) -> Any:
        return _Row(name="Gecikmə")


class _Connection:
    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        return _Cursor()


class _TaskRepo:
    def __init__(self, tasks: list[_Task]) -> None:
        self._tasks = tasks

    def list_for_assignee(self, employee_id: Any, *, open_only: bool = True) -> list[_Task]:
        return self._tasks


class _Uow:
    def __init__(self, tasks: list[_Task]) -> None:
        self.connection = _Connection()
        self._tasks = _TaskRepo(tasks)

    def repository(self, name: str) -> Any:
        assert name == "tasks"
        return self._tasks


class _ManualFines:
    def __init__(self, fines: list[_Fine]) -> None:
        self._fines = fines

    def my_fines(self, *, employee: Any, year: int, month: int) -> list[_Fine]:
        return self._fines


class _Appeals:
    def __init__(self, appeals: list[_Appeal]) -> None:
        self._appeals = appeals
        self.submitted: list[dict[str, Any]] = []
        #: UX-4 — qaytarılan etirazlar (`owner_id` onların İD-sidir).
        self.submitted_appeals: list[Any] = []
        self.error: KompasOSError | None = None

    def my_appeals(self, _employee: Any) -> list[_Appeal]:
        return self._appeals

    def submit(self, *, tenant_id: Any, employee: Any, fine_id: Any, reason: str) -> Any:
        if self.error is not None:
            raise self.error
        self.submitted.append({"fine_id": fine_id, "reason": reason})
        # UX-4: sənəd növbəsi sahibin İD-sini tələb edir (`owner_id =
        # fine_appeals.id`) — real `submit()` də `FineAppeal` qaytarır.
        appeal = _SubmittedAppeal()
        self.submitted_appeals.append(appeal)
        return appeal


class _SubmittedAppeal:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


class _Session:
    def __init__(self, *, tasks: list[_Task], fines: list[_Fine], appeals: list[_Appeal]) -> None:
        self.tenant_id = uuid.uuid4()
        self.uow = _Uow(tasks)
        self.manual_fines = _ManualFines(fines)
        self.fine_appeals = _Appeals(appeals)
        self.committed = 0

    def commit(self) -> None:
        self.committed += 1


class _EvidenceQueue:
    """UX-4 — sübut növbəsinin sahtəsi (real növbə lokal SQLite faylı açardı)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def enqueue(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "entry-1"


class _Clock:
    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime(2026, 8, 23, 9, 0, tzinfo=UTC)


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.tenant_id = uuid.uuid4()
        self.clock = _Clock()
        self.queue = _EvidenceQueue()
        # Növbə SESSİYA sahtəsinə də bağlanır ki, test onu `_wire`-in
        # qaytardığı obyektdən oxuya bilsin (imza dəyişmir).
        session.queue = self.queue

    def evidence_queue(self) -> _EvidenceQueue:
        return self.queue

    @contextmanager
    def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
        yield self._session


class _Kiosk:
    def __init__(self) -> None:
        self.shown: list[Any] = []

    def set_content(self, widget: Any) -> None:
        self.shown.append(widget)


class _Actor:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.full_name = "Rəşad Məmmədov"
        #: UX-4 — sənəd növbəsi mağazanı YERLƏŞMƏ açarı kimi işlədir.
        self.store_id = uuid.uuid4()


def _wire(theme: Any, *, tasks: Any = None, fines: Any = None, appeals: Any = None) -> Any:
    from src.presentation.controllers.kiosk_self_service import KioskSelfServiceController
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    session = _Session(
        tasks=tasks if tasks is not None else [],
        fines=fines if fines is not None else [],
        appeals=appeals if appeals is not None else [],
    )
    context = _Context(session)
    kiosk = _Kiosk()
    home = EmployeeHomeScreen(
        theme, full_name="Rəşad Məmmədov", position_name="Satıcı", store_name="Bellona 28 May"
    )
    controller = KioskSelfServiceController(context, _Actor(), kiosk=kiosk, theme=theme)
    controller.attach(home)
    return home, kiosk, session


def _click(widget: Any, text: str) -> Any:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()
    return button


# --------------------------------------------------------------------------- #
# 1. Real düymə kliki — hər üç keçid
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_real_tasks_link_opens_the_employees_own_task_board(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import TasksScreen

    home, kiosk, _session = _wire(theme, tasks=[_Task("Vitrin yenilənməsi")])
    qtbot.addWidget(home)

    _click(home, "Hamısına bax →")  # REAL klik — siqnal EMIT deyil

    assert kiosk.shown, "kioskda heç nə göstərilmədi — düymə ölüdür"
    assert _find(kiosk.shown[-1], TasksScreen) is not None


@requires_qt
def test_clicking_the_real_rewards_link_opens_the_points_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import SalesPointsScreen

    home, kiosk, _session = _wire(theme)
    qtbot.addWidget(home)

    _click(home, "Mükafat kataloqu →")

    assert _find(kiosk.shown[-1], SalesPointsScreen) is not None


@requires_qt
def test_clicking_the_real_appeal_link_opens_the_fine_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, _session = _wire(theme, fines=[_Fine()], appeals=[_Appeal(open_=True)])
    qtbot.addWidget(home)

    _click(home, "Etiraz Et")

    screen = _find(kiosk.shown[-1], FineAppealScreen)
    assert screen is not None
    assert screen.switcher().current_state() == "content"


def _find(widget: Any, kind: type) -> Any:
    return widget.findChild(kind)


# --------------------------------------------------------------------------- #
# 2. TAPINTI — cərimə sətrindəki «Etiraz Et» düyməsi HEÇ VAXT görünmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_per_fine_appeal_button_must_render_for_an_open_fine(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`ui-fixes` düzəldib (bax fayl başlığı) — AÇIQ cəriməyə real sətir düyməsi verilir.

    `_fine_rows()` indi `"id"` VƏ `"appealable"` açarlarını yazır (open
    etirazı olmayan cərimə `"appealable": "1"` alır); `FineAppealScreen.
    set_history()` bunu oxuyub sətir düyməsini çəkir. Bu test məhz həmin
    düymənin real widget ağacında OLDUĞUNU təsdiqləyir.
    """
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, _session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)

    _click(home, "Etiraz Et")
    screen = _find(kiosk.shown[-1], FineAppealScreen)
    assert screen is not None

    # Tarixçə kartının İÇİNDƏKİ düymələr — ekranın ÜST səviyyəli «Etirazı
    # Göndər» düyməsini deyil, MƏHZ sətir düyməsini axtarırıq.
    row_buttons = [
        b
        for b in screen._history_layout.parentWidget().findChildren(QPushButton)
        if b.text() == "Etiraz Et"
    ]
    assert len(row_buttons) == 1, (
        "AÇIQ (etiraz edilə bilən) cərimə sətrində «Etiraz Et» düyməsi olmalıdır — "
        "hazırda `_fine_rows()` `appealable`/`id` açarlarını YAZMADIĞI üçün YOXDUR"
    )


@requires_qt
def test_a_fine_with_an_open_appeal_hides_the_row_button(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Artıq etiraz edilmiş cərimə YENİDƏN etiraz düyməsi göstərməməlidir."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, _session = _wire(theme, fines=[_Fine()], appeals=[_Appeal(open_=True)])
    qtbot.addWidget(home)

    _click(home, "Etiraz Et")
    screen = _find(kiosk.shown[-1], FineAppealScreen)

    row_buttons = [
        b
        for b in screen._history_layout.parentWidget().findChildren(QPushButton)
        if b.text() == "Etiraz Et"
    ]
    assert row_buttons == [], "Açıq etirazı olan cərimə YENİDƏN etiraz edilə bilməməlidir"


@requires_qt
def test_clicking_the_real_row_button_opens_the_form_for_that_specific_fine_and_submits(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """UCDAN-UCA: real sətir kliki → real forma → real "Etirazı Göndər" → real use case.

    Əvvəlki testlər `screen.start_appeal(...)`-i BİRBAŞA çağırırdı (bax §3
    şərhi) — bu, düymə HƏLƏ RENDER OLUNMAYANDA belə pipeline-ı sınamaq
    üçün idi. İndi düymə var, ona görə TAM zəncir birbaşa siçan kliki ilə
    yoxlanılır.
    """
    from PySide6.QtWidgets import QPlainTextEdit, QPushButton

    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    _click(home, "Etiraz Et")
    screen = _find(kiosk.shown[-1], FineAppealScreen)

    row_button = next(
        b
        for b in screen._history_layout.parentWidget().findChildren(QPushButton)
        if b.text() == "Etiraz Et"
    )
    row_button.click()  # REAL sətir kliki — `start_appeal(str(FINE_ID), ...)`-i özü çağırır

    assert screen._current_fine == str(FINE_ID)

    explanation = screen.findChild(QPlainTextEdit)
    explanation.setPlainText("Kamera qeydinə görə vaxt düzgün deyil.")
    _click(screen, "Etirazı Göndər")

    assert len(session.fine_appeals.submitted) == 1
    assert str(session.fine_appeals.submitted[0]["fine_id"]) == str(FINE_ID)
    assert session.committed == 1


@requires_qt
def test_clicking_the_general_appeal_card_never_opens_a_submittable_form(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """ÜMUMİ kart keçidi TƏK BAŞINA forma açmır — bu, DÜZGÜN davranışdır (qüsur deyil).

    `_open_fines()` özü `start_appeal()` çağırmır; forma yalnız KONKRET bir
    sətir düyməsi seçiləndə açılmalıdır (bax yuxarıdakı test, düzəlişdən
    sonra həmin düymə İNDİ real widget ağacında MÖVCUDDUR). Bu test o
    ayrımı qoruyur: siyahı görünüşü ilə forma görünüşü QARIŞDIRILMAMALIDIR.
    """
    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, _session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)

    _click(home, "Etiraz Et")
    kiosk.shown[-1].show()  # ancestor-lar göstərilmədən `isVisible()` HƏMİŞƏ False qaytarır
    screen = _find(kiosk.shown[-1], FineAppealScreen)

    assert screen._form_card.isVisible() is False, (
        "Forma açıq görünürsə, `start_appeal()` artıq HARADANSA çağırılır — bu testi yeniləyin"
    )


# --------------------------------------------------------------------------- #
# 3. Formanın qalan hissəsi — `start_appeal()` ARTIQ ÇAĞIRILIB fərz edilir
# --------------------------------------------------------------------------- #
# Yuxarıdakı iki test göstərdi ki, real istifadəçi bu nöqtəyə HEÇ VAXT
# çatmır (sətir düyməsi yoxdur, forma gizli qalır). Aşağıdakı testlər
# `screen.start_appeal(...)`-i BİLAVASİTƏ çağıraraq — sətir düyməsi düzələn
# KİMİ işə düşəcək REAL ekran + REAL kontroller yolunu qabaqcadan qoruyur.
# `_click(screen, "Etirazı Göndər")` ÖZÜ real klikdir; yalnız formanı AÇAN
# addım (`start_appeal`) sətir düyməsinin əvəzinə birbaşa çağırılır.


@requires_qt
def test_filling_the_real_form_and_clicking_submit_reaches_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPlainTextEdit

    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    _click(home, "Etiraz Et")
    screen = _find(kiosk.shown[-1], FineAppealScreen)
    screen.start_appeal(str(FINE_ID), "Gecikmə — 22.08.2026 · 25 ₼")

    explanation = screen.findChild(QPlainTextEdit)
    assert explanation is not None
    explanation.setPlainText("Saat 09:05-də mağazada idim, kamera qeydi var.")
    _click(screen, "Etirazı Göndər")

    assert len(session.fine_appeals.submitted) == 1
    assert str(session.fine_appeals.submitted[0]["fine_id"]) == str(FINE_ID)
    assert "kamera qeydi var" in session.fine_appeals.submitted[0]["reason"]
    assert session.committed == 1


@requires_qt
def test_hostile_and_extreme_explanation_text_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPlainTextEdit

    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    _click(home, "Etiraz Et")
    screen = _find(kiosk.shown[-1], FineAppealScreen)
    screen.start_appeal(str(FINE_ID), "Gecikmə")

    hostile = ("'; DROP TABLE fine_appeals; -- 🔥" * 50) + "A" * 10_000
    explanation = screen.findChild(QPlainTextEdit)
    explanation.setPlainText(hostile)
    _click(screen, "Etirazı Göndər")  # ÇÖKMƏMƏLİDİR

    assert len(session.fine_appeals.submitted) == 1
    assert hostile.strip() in session.fine_appeals.submitted[0]["reason"]


@requires_qt
def test_an_empty_explanation_is_rejected_by_the_real_form_before_any_write(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    _click(home, "Etiraz Et")
    kiosk.shown[-1].show()  # ancestor-lar göstərilmədən `isVisible()` HƏMİŞƏ False qaytarır
    screen = _find(kiosk.shown[-1], FineAppealScreen)
    screen.start_appeal(str(FINE_ID), "Gecikmə")

    _click(screen, "Etirazı Göndər")  # İzah BOŞDUR

    assert session.fine_appeals.submitted == []
    assert screen._explanation_error.isVisible() is True


# --------------------------------------------------------------------------- #
# 4. Xəta qolu — real klik, use case istisnası sükutla udulmur
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_submission_failure_shows_a_real_error_instead_of_a_silent_drop(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPlainTextEdit

    from src.presentation.screens.group_f import FineAppealScreen

    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    _click(home, "Etiraz Et")
    screen = _find(kiosk.shown[-1], FineAppealScreen)
    screen.start_appeal(str(FINE_ID), "Gecikmə")
    session.fine_appeals.error = KompasOSError(
        "window closed", user_message="Etiraz pəncərəsi bağlanıb — 72 saat keçib."
    )

    explanation = screen.findChild(QPlainTextEdit)
    explanation.setPlainText("Vaxtında etiraz etməyə çalışmışdım.")
    _click(screen, "Etirazı Göndər")  # ÇÖKMƏMƏLİDİR

    assert session.fine_appeals.submitted == []
    assert session.committed == 0
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_an_attached_document_is_uploaded_via_the_real_click(qtbot, theme, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """DEEP-GAP UX-4 — REAL kliklə: sənəd növbəyə düşür, sahibi ETİRAZDIR.

    Köhnə test sənədin GÖNDƏRİLMƏDİYİNİ kilidləyirdi (o vaxt domendə sənəd
    anlayışı yox idi). İndi `fine_appeals.document_ref` (miqrasiya 083),
    `UploadOwnerType.FINE_APPEAL` və geri-çağırış mövcuddur — yəni ölçülən
    şey dəyişdi: vəd ARTIQ yerinə yetirilir.
    """
    from PySide6.QtWidgets import QPlainTextEdit

    from src.infrastructure.storage.upload_queue import UploadOwnerType
    from src.presentation.screens.group_f import FineAppealScreen

    document = tmp_path / "arayis.pdf"
    document.write_bytes(b"%PDF-1.4 saxta sened")
    home, kiosk, session = _wire(theme, fines=[_Fine()], appeals=[])
    qtbot.addWidget(home)
    _click(home, "Etiraz Et")
    screen = _find(kiosk.shown[-1], FineAppealScreen)
    screen.start_appeal(str(FINE_ID), "Gecikmə")

    # `PhotoDropZone` real fayl seçici pəncərəsi olmadan yazıla bilmir —
    # daxili yolu birbaşa qururuq (real `QFileDialog` modaldır).
    screen._document._path = str(document)
    explanation = screen.findChild(QPlainTextEdit)
    explanation.setPlainText("Ətraflı izah buradadır və kifayət qədər uzundur.")
    _click(screen, "Etirazı Göndər")

    assert len(session.fine_appeals.submitted) == 1
    queue = session.queue
    assert len(queue.calls) == 1, "sənəd növbəyə DÜŞMƏDİ"
    assert queue.calls[0]["owner_type"] is UploadOwnerType.FINE_APPEAL
    assert queue.calls[0]["owner_id"] == str(session.fine_appeals.submitted_appeals[-1].id)
    assert screen.switcher().current_state() != "error"
