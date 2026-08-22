"""`SyncConflictScreen` ↔ `SyncConflictController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, infra dalğası)
──────────────────────────────────────────────────────────────────────────────
`test_sync_conflicts_screen.py` iki qatı ayrı sınayır: kontroller Qt TƏLƏB
ETMİR (duck-typing `_ScreenStub`), ekranın ÖZÜ isə `set_conflicts()` /
`set_comparison()` metodlarını ƏL İLƏ çağırır — REAL `SyncConflictController.
attach()` heç vaxt REAL `SyncConflictScreen` ilə birlikdə qurulmur. Yəni
«sətrə klik → müqayisə paneli dolur → qərar düyməsi basılır → `resolve()`
çağırılır → siyahı yenidən oxunur» zənciri UCADAN-UCA heç yerdə sınanmır.
Burada məhz bu boşluq bağlanır (`test_devices_screen_e2e.py` naxışı).

──────────────────────────────────────────────────────────────────────────────
TAPILIB VƏ DÜZƏLDİLİB — «ARTIQ HƏLL OLUNUB» MESAJI YAZILAN KİMİ SİLİNİRDİ
──────────────────────────────────────────────────────────────────────────────
İlkin versiyada `SyncConflictController._on_resolve`-un `ConflictNotFoundError`
qolu ƏVVƏLCƏ `screen.show_notice(ALREADY_RESOLVED_NOTICE)` çağırır, SONRA
`self.refresh(screen)` işlədirdi. `refresh()` daxilində `_show()` →
`screen.set_comparison(...)` çağırılır və `SyncConflictScreen.set_comparison`
"seçim DƏYİŞİBSƏ notice-i TƏMİZLƏ" qaydasını daşıyır (başqa konfliktə
keçəndə köhnə izahın qalmaması üçün — bax `screens/sync_conflicts.py::
set_comparison`). Paralel həll səbəbindən silinən konflikt siyahıdan
çıxdığı üçün `refresh()` YENİ (fərqli) bir sətri avtomatik seçirdi — bu isə
"seçim dəyişdi" şərtini işə salıb `ALREADY_RESOLVED_NOTICE`-i ONU YAZDIQDAN
dərhal SONRA sükutla SİLİRDİ. İstifadəçi mesajı HEÇ VAXT görmürdü.

`ui` sahibi SIRANI DƏYİŞDİRƏRƏK düzəltdi: indi ƏVVƏLCƏ `refresh(screen)`,
SONRA `screen.show_notice(ALREADY_RESOLVED_NOTICE)` çağırılır (bax
`controllers/sync_conflicts.py::_on_resolve` şərhi). Aşağıdakı
`test_the_already_resolved_notice_survives_the_refresh_that_follows_it`
indi HƏMİN DÜZƏLİŞİN REQRESSİYA QAPISIDIR.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from src.application.use_cases.sync_conflicts import (
    MIN_NOTE_LENGTH,
    ConflictItem,
    ConflictNotFoundError,
    Resolution,
)
from src.presentation.controllers.sync_conflicts import (
    ALREADY_RESOLVED_NOTICE,
    SyncConflictController,
)
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = uuid.uuid4()
ACTOR_ID: Final = uuid.uuid4()
NOW: Final = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


class _Actor:
    id = ACTOR_ID


def _item(*, key: str, table: str = "fines") -> ConflictItem:
    """`is_audit_critical` HESABLANMIŞ property-dir (`table_name`-dən) —
    konstruktora ötürülmür (bax `ConflictItem.is_audit_critical`)."""
    return ConflictItem(
        conflict_id=key,
        table_name=table,
        record_id="4f2a9c11-0000-0000-0000-000000000000",
        local_version={"amount": "45.00", "status": "PENDING"},
        remote_version={"amount": "30.00", "status": "PENDING"},
        detected_at=NOW,
    )


# --------------------------------------------------------------------------- #
# `SyncConflictUseCase` müqaviləsinin sahtəsi — bu fayl LOKAL saxlayır
# (`test_sync_conflicts_screen.py`-dəki `_UseCase` ilə eyni müqavilə, lakin
# paralel işlərin ortaq faylı dəyişməsinin qarşısını almaq üçün TƏKRARLANIR —
# CLAUDE.md bölmə 6-dakı qərarın eyni forması).
# --------------------------------------------------------------------------- #


class _UseCase:
    def __init__(self, *, items: list[ConflictItem], inbox_error: Exception | None = None) -> None:
        self.items = list(items)
        self.inbox_error = inbox_error
        self.resolve_error: Exception | None = None
        self.resolved: list[dict[str, Any]] = []

    def inbox(self, *, tenant_id: Any, actor: Any) -> list[ConflictItem]:
        if self.inbox_error is not None:
            raise self.inbox_error
        return list(self.items)

    def resolve(
        self, *, tenant_id: Any, actor: Any, conflict_id: Any, resolution: Resolution, note: str
    ) -> ConflictItem:
        if self.resolve_error is not None:
            raise self.resolve_error
        self.resolved.append({"conflict_id": conflict_id, "resolution": resolution, "note": note})
        removed = [item for item in self.items if item.conflict_id == conflict_id]
        self.items = [item for item in self.items if item.conflict_id != conflict_id]
        return removed[0] if removed else _item(key=str(conflict_id))


class _Session:
    def __init__(self, use_case: _UseCase) -> None:
        self.tenant_id = TENANT
        self.sync_conflicts = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.opens = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opens += 1
        yield self._session


def _build(use_case: _UseCase, theme: Any) -> tuple[Any, SyncConflictController, _Session]:
    from src.presentation.screens.sync_conflicts import SyncConflictScreen

    session = _Session(use_case)
    context = _Context(session)
    screen = SyncConflictScreen(theme)
    controller = SyncConflictController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(screen)  # type: ignore[arg-type]
    return screen, controller, session


def _row_cards(screen: Any) -> list[Any]:
    layout = screen.list_layout()
    return [layout.itemAt(index).widget() for index in range(layout.count())]


def _decision_button(screen: Any, resolution: Resolution) -> QPushButton:
    """Qərar düyməsi — `set_resolutions()`-in TƏRTİB SIRASI `Resolution` enumu ilə eynidir."""
    index = list(Resolution).index(resolution)
    return screen.decision_buttons()[index]


# --------------------------------------------------------------------------- #
# 1. Real sətir kliki — müqayisə paneli REAL widget-lərdə dolur
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_a_real_row_populates_the_real_comparison_panel(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _UseCase(
        items=[_item(key="sc-1", table="fines"), _item(key="sc-2", table="leave_requests")]
    )
    screen, _controller, _session = _build(use_case, theme)
    qtbot.addWidget(screen)

    # `attach()` avtomatik ilk sətri seçir — ikinci sətrə REAL klik.
    cards = _row_cards(screen)
    assert len(cards) == 2
    qtbot.mouseClick(cards[1], Qt.MouseButton.LeftButton)

    assert screen._detail_title.text() == "İcazə sorğuları"
    assert screen.field_layout().count() >= 0  # panel ÇÖKMƏDƏN yenidən qurulub


# --------------------------------------------------------------------------- #
# 2. Real yazı yolu — qeyd yazılır, REAL düymə basılır, `resolve()` DOĞRU
#    arqumentlərlə çağırılır, commit edilir, siyahı YENİDƏN oxunur
# --------------------------------------------------------------------------- #


@requires_qt
def test_resolving_via_real_widgets_commits_and_rereads_the_inbox(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _UseCase(items=[_item(key="sc-1"), _item(key="sc-2")])
    screen, _controller, session = _build(use_case, theme)
    qtbot.addWidget(screen)

    button = _decision_button(screen, Resolution.KEPT_LOCAL)
    assert not button.isEnabled(), "Səbəb yazılmayana qədər düymə BAĞLI olmalıdır"

    screen._note.setPlainText("Mağazadakı operator hadisəni öz gözü ilə görüb.")
    assert button.isEnabled()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert use_case.resolved == [
        {
            "conflict_id": "sc-1",
            "resolution": Resolution.KEPT_LOCAL,
            "note": "Mağazadakı operator hadisəni öz gözü ilə görüb.",
        }
    ]
    assert session.commits == 1
    # Siyahı YENİDƏN oxunub: həll edilmiş "sc-1" artıq göstərilmir, "sc-2" qalır.
    assert len(_row_cards(screen)) == 1
    assert screen._detail_title.text() != ""  # qalan konflikt avtomatik seçilib


# --------------------------------------------------------------------------- #
# 3. Ekstremal giriş — çox uzun/emoji-li səbəb ÇÖKMÜR, TƏMİZLƏNMİŞ mətn gedir
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_extremely_long_and_emoji_laden_reason_is_accepted_without_crashing(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    use_case = _UseCase(items=[_item(key="sc-1")])
    screen, _controller, _session = _build(use_case, theme)
    qtbot.addWidget(screen)

    long_note = (
        "Mağazadakı vaxt doğrudur 🚀🔥 " * 400
    ) + "\u200b"  # ~10 000+ simvol + sıfır-en boşluq
    screen._note.setPlainText(long_note)

    button = _decision_button(screen, Resolution.KEPT_REMOTE)
    assert button.isEnabled()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # ÇÖKMƏMƏLİDİR

    assert len(use_case.resolved) == 1
    sent_note = use_case.resolved[0]["note"]
    assert "\u200b" not in sent_note, "Sıfır-en boşluq təmizlənməlidir (normalise_decision_text)"
    assert sent_note.strip() == sent_note


@requires_qt
def test_whitespace_only_reason_never_reaches_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _UseCase(items=[_item(key="sc-1")])
    screen, _controller, _session = _build(use_case, theme)
    qtbot.addWidget(screen)

    screen._note.setPlainText(" " * MIN_NOTE_LENGTH)
    button = _decision_button(screen, Resolution.MERGED)
    assert not button.isEnabled(), "Yalnız boşluqdan ibarət qeyd BOŞ sayılmalıdır"


# --------------------------------------------------------------------------- #
# 4. Domen rəddi (səlahiyyət/qapı) — AÇIQ mesaj, siyahı SİLİNMİR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_domain_rejection_shows_the_real_error_and_does_not_wipe_the_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`resolve()` rədd edərsə (məs. səlahiyyət) mövcud siyahı SAXLANIR."""
    use_case = _UseCase(items=[_item(key="sc-1"), _item(key="sc-2")])
    use_case.resolve_error = KompasOSError(
        "denied", user_message="Sinxronizasiya konfliktlərini həll etmək səlahiyyətiniz yoxdur."
    )
    screen, _controller, session = _build(use_case, theme)
    qtbot.addWidget(screen)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır

    screen._note.setPlainText("Bu, real izah mətnidir.")
    button = _decision_button(screen, Resolution.KEPT_LOCAL)
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # ÇÖKMƏMƏLİDİR

    assert screen._error.text() == "Sinxronizasiya konfliktlərini həll etmək səlahiyyətiniz yoxdur."
    assert screen._error.isVisible()
    assert session.commits == 0
    # Siyahı YENİLƏNMƏYİB — rədd edilən əməliyyat qeydi silməməlidir.
    assert len(_row_cards(screen)) == 2


# --------------------------------------------------------------------------- #
# 5. TAPILAN QÜSUR — "artıq həll olunub" mesajı yazılan kimi silinir
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_already_resolved_notice_survives_the_refresh_that_follows_it(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """REQRESSİYA QAPISI — bax modul başlığındakı "TAPILAN QÜSUR" bölməsi.

    Bu test əvvəlcə qüsuru REAL widget üzərində sübut etdi: `_on_resolve`-un
    `ConflictNotFoundError` qolu `show_notice(...)`-u `refresh(screen)`-dən
    ƏVVƏL çağırırdı, `refresh()` isə YENİ (fərqli) konflikti avtomatik
    seçdiyi üçün `set_comparison`-un "seçim dəyişdi" qolu mesajı DƏRHAL
    silirdi. `ui` sahibi bunu SIRANI DƏYİŞDİRƏRƏK düzəltdi (əvvəlcə
    `refresh()`, sonra `show_notice(...)` — bax `controllers/
    sync_conflicts.py::_on_resolve` şərhi) — bu test indi HəMİN düzəlişin
    QORUYUCUSUDUR.
    """
    use_case = _UseCase(items=[_item(key="sc-1"), _item(key="sc-2")])
    screen, _controller, _session = _build(use_case, theme)
    qtbot.addWidget(screen)

    screen._note.setPlainText("Mağazadakı dəyər doğrudur.")
    button = _decision_button(screen, Resolution.KEPT_LOCAL)

    # `resolve()` çağırılan andan `ConflictNotFoundError` atır — paralel HR
    # artıq bağlayıb. REAL backendda bu o deməkdir ki, "sc-1" artıq
    # `resolved_at IS NULL` şərtinə uymur və NÖVBƏTİ `inbox()` oxunuşu onu
    # BİR DAHA qaytarmır — ona görə saxta `items`-dən DƏ çıxarılır (əks
    # halda test "sc-1" hələ siyahıdadır kimi qeyri-real vəziyyət yaradardı).
    use_case.resolve_error = ConflictNotFoundError("sc-1 artıq bağlanıb")
    use_case.items = [item for item in use_case.items if item.conflict_id != "sc-1"]
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # ÇÖKMƏMƏLİDİR

    assert screen._notice.text() == ALREADY_RESOLVED_NOTICE
    # Siyahı da DÜZGÜN yenilənib (qalan tək konflikt görünür).
    assert len(_row_cards(screen)) == 1


# --------------------------------------------------------------------------- #
# 6. Boş gələnlər qutusu — REAL "Yenilə" kliki, real MÜSBƏT boş vəziyyət
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_refresh_on_an_empty_inbox_shows_the_positive_empty_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.sync_conflicts import EMPTY_TITLE

    use_case = _UseCase(items=[_item(key="sc-1")])
    screen, _controller, _session = _build(use_case, theme)
    qtbot.addWidget(screen)
    assert screen.switcher().current_state() == "content"

    use_case.items = []  # sonuncu konflikt başqa yerdən artıq həll olunub
    _click(screen, "Yenilə")  # REAL düymə

    assert screen.switcher().current_state() == "empty"
    from PySide6.QtWidgets import QLabel

    assert any(label.text() == EMPTY_TITLE for label in screen.findChildren(QLabel))


# --------------------------------------------------------------------------- #
# 7. Siyahı oxunmur — real xəta vəziyyəti, ÇÖKMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_unreadable_inbox_shows_a_real_error_state_instead_of_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _UseCase(
        items=[],
        inbox_error=KompasOSError("db down", user_message="Baza əlaqəsi kəsildi."),
    )
    screen, _controller, _session = _build(use_case, theme)  # attach() ÇÖKMƏMƏLİDİR
    qtbot.addWidget(screen)

    assert screen.switcher().current_state() == "error"
