"""`AnnouncementsScreen` ↔ `AnnouncementsAdminController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_announcements.py` YALNIZ domen/use-case qatını ölçür (heç bir Qt widget
qurmur). Kontroller özü heç bir yerdə REAL `AnnouncementsScreen` qurub ona
bağlanmır, real "Yeni Elan" düyməsini klikləmir. Bu boşluq CLAUDE.md-nin
təsvir etdiyi tələdir: «düymə bağlanmışdı, test onu ADLA xatırlayırdı, lakin
heç vaxt ÇAĞIRMIRDI». Burada ekran FAKTİKİ qurulur, kontroller ONA bağlanır
və hər ssenari HƏQİQİ widget qarşılıqlı təsiri (düymə kliki, mətn yazma,
checkbox işarələmə) ilə işə salınır.

`AnnouncementComposeDialog.exec()` MODAL-dır və çağırılsa test sapını
əbədi bloklardı (istifadəçi girişi gözləyir). Ona görə `exec()` bu faylda
`_patched_exec` ilə əvəz olunur: əvəzləyici DİALOQUN REAL sahələrini doldurur
və REAL "Yayımla" düyməsini basır — yəni bloklanan YALNIZ hadisə dövrəsinin
gözləməsidir, sahə doldurma və düymə kliki tam realdır.
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
STORE_A = str(uuid.uuid4())
STORE_B = str(uuid.uuid4())


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


# --------------------------------------------------------------------------- #
# Sahtələr — `tests/fixtures/fakes.py` DƏYİŞDİRİLMİR (CLAUDE.md tapşırığı)
# --------------------------------------------------------------------------- #


class _Row(dict):
    """`session.uow.connection.execute(...).fetchall()`-un `row["ad"]` API-si."""


class _Connection:
    def __init__(self, stores: list[tuple[str, str]]) -> None:
        self._stores = stores

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [_Row(id=sid, name=name) for sid, name in self._stores]


class _Uow:
    def __init__(self, stores: list[tuple[str, str]]) -> None:
        self.connection = _Connection(stores)


class _Announcements:
    """`AnnouncementUseCase`-in yerini tutur — YALNIZ kontrollerin gözlədiyi imza."""

    def __init__(self) -> None:
        self.broadcasts: list[Any] = []
        self.withdrawals: list[Any] = []
        self.rows: list[Any] = []
        self.broadcast_error: KompasOSError | None = None
        self.withdraw_error: KompasOSError | None = None

    def list_recent(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        return list(self.rows)

    def broadcast(self, *, tenant_id: Any, actor: Any, draft: Any) -> None:
        if self.broadcast_error is not None:
            raise self.broadcast_error
        self.broadcasts.append(draft)

    def withdraw(self, *, tenant_id: Any, actor: Any, announcement_id: Any) -> None:
        if self.withdraw_error is not None:
            raise self.withdraw_error
        self.withdrawals.append(announcement_id)


class _Session:
    def __init__(self, announcements: _Announcements, stores: list[tuple[str, str]]) -> None:
        self.tenant_id = TENANT
        self.announcements = announcements
        self.uow = _Uow(stores)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    """`ApplicationContext`-in yerini tutur — hər çağırış YENİ sessiya açır (CLAUDE.md §6)."""

    def __init__(self, announcements: _Announcements, stores: list[tuple[str, str]]) -> None:
        self._announcements = announcements
        self._stores = stores
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._announcements, self._stores)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _view(*, announcement_id: str, title: str, message: str, scope: str, is_active: bool) -> Any:
    from datetime import UTC, datetime

    from src.application.use_cases.announcements import AnnouncementView

    return AnnouncementView(
        announcement_id=announcement_id,
        title_az=title,
        message=message,
        scope=scope,
        store_ids=(),
        created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        is_active=is_active,
    )


def _patched_exec(
    monkeypatch: pytest.MonkeyPatch,
    *,
    title: str,
    message: str,
    scope: str = "ALL",
    checked_stores: tuple[str, ...] = (),
) -> None:
    """`AnnouncementComposeDialog.exec()`-i REAL sahə doldurma + REAL klik ilə əvəz edir."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidget, QPushButton

    from src.presentation.screens.announcements import AnnouncementComposeDialog

    def fake_exec(self: AnnouncementComposeDialog) -> int:
        self._title.set_text(title)
        self._message.setPlainText(message)
        if scope == "STORE_LIST":
            self._scope_store_list.setChecked(True)
            store_list = self.findChild(QListWidget)
            assert store_list is not None
            for i in range(store_list.count()):
                item = store_list.item(i)
                if str(item.data(Qt.ItemDataRole.UserRole)) in checked_stores:
                    item.setCheckState(Qt.CheckState.Checked)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yayımla")
        submit.click()
        return 0

    monkeypatch.setattr(AnnouncementComposeDialog, "exec", fake_exec)


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


# --------------------------------------------------------------------------- #
# 1. Yeni elan — real dialoq, real klik → broadcast + commit + yenidən oxuma
# --------------------------------------------------------------------------- #


@requires_qt
def test_publishing_via_the_real_dialog_broadcasts_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.announcements import AnnouncementsAdminController
    from src.presentation.screens.announcements import AnnouncementsScreen

    announcements = _Announcements()
    context = _Context(announcements, [(STORE_A, "Mərkəz")])
    screen = AnnouncementsScreen(theme)
    qtbot.addWidget(screen)
    AnnouncementsAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _patched_exec(monkeypatch, title="Anbar təftişi", message="Sabah 10:00-da anbar bağlıdır.")
    announcements.rows = [
        _view(
            announcement_id=uuid.uuid4(),
            title="Anbar təftişi",
            message="Sabah 10:00-da anbar bağlıdır.",
            scope="ALL",
            is_active=True,
        )
    ]

    _click(screen, "Yeni Elan")

    assert len(announcements.broadcasts) == 1, "Yayımla basılsa da broadcast() çağırılmayıb"
    draft = announcements.broadcasts[0]
    assert draft.title_az == "Anbar təftişi"
    assert draft.message == "Sabah 10:00-da anbar bağlıdır."
    assert draft.store_ids == frozenset()
    assert any(s.committed for s in context.sessions), (
        "commit() çağırılmayıb — dəyişiklik yazılmayacaqdı"
    )
    # `refresh()` YENİDƏN oxuyub — cədvəldə YENİ sətir REAL widget kimi görünür.
    assert screen._summary.text().startswith("1 elan")


@requires_qt
def test_store_list_scope_sends_only_the_checked_store(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.announcements import AnnouncementsAdminController
    from src.presentation.screens.announcements import AnnouncementsScreen

    announcements = _Announcements()
    context = _Context(announcements, [(STORE_A, "Mərkəz"), (STORE_B, "28 May")])
    screen = AnnouncementsScreen(theme)
    qtbot.addWidget(screen)
    AnnouncementsAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _patched_exec(
        monkeypatch,
        title="Yalnız Mərkəz",
        message="Bu elan yalnız bir mağazaya aiddir.",
        scope="STORE_LIST",
        checked_stores=(STORE_A,),
    )

    _click(screen, "Yeni Elan")

    assert len(announcements.broadcasts) == 1
    draft = announcements.broadcasts[0]
    assert {str(sid) for sid in draft.store_ids} == {STORE_A}, (
        "Yalnız işarələnmiş mağaza getməli idi"
    )


# --------------------------------------------------------------------------- #
# 2. Dialoqun ÖZ validasiyası — boş sahə, boş mağaza seçimi (yazı yoluna girmir)
# --------------------------------------------------------------------------- #


@requires_qt
def test_empty_title_is_rejected_by_the_real_widget_before_any_write(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.announcements import AnnouncementComposeDialog

    dialog = AnnouncementComposeDialog(theme, stores=[])
    qtbot.addWidget(dialog)
    emitted: list[Any] = []
    dialog.submitted.connect(lambda *a: emitted.append(a))

    dialog._message.setPlainText("Mətn var, başlıq yoxdur.")
    _click(dialog, "Yayımla")

    assert emitted == [], "Boş başlıqla siqnal yayılmamalı idi"
    assert dialog._title.has_error


@requires_qt
def test_whitespace_only_title_is_rejected(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Yalnız boşluqdan ibarət başlıq da boş sayılmalıdır — `strip()` boşaldır."""
    from src.presentation.screens.announcements import AnnouncementComposeDialog

    dialog = AnnouncementComposeDialog(theme, stores=[])
    qtbot.addWidget(dialog)
    emitted: list[Any] = []
    dialog.submitted.connect(lambda *a: emitted.append(a))

    dialog._title.set_text("     ")
    dialog._message.setPlainText("Mətn.")
    _click(dialog, "Yayımla")

    assert emitted == []
    assert dialog._title.has_error


@requires_qt
def test_empty_message_is_rejected(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.announcements import AnnouncementComposeDialog

    dialog = AnnouncementComposeDialog(theme, stores=[])
    qtbot.addWidget(dialog)
    dialog.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    emitted: list[Any] = []
    dialog.submitted.connect(lambda *a: emitted.append(a))

    dialog._title.set_text("Başlıq")
    _click(dialog, "Yayımla")

    assert emitted == []
    assert dialog._error.isVisible()
    assert "mətni məcburidir" in dialog._error.text()


@requires_qt
def test_store_list_scope_without_any_checked_store_is_rejected(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.announcements import AnnouncementComposeDialog

    dialog = AnnouncementComposeDialog(theme, stores=[(STORE_A, "Mərkəz")])
    qtbot.addWidget(dialog)
    dialog.show()
    emitted: list[Any] = []
    dialog.submitted.connect(lambda *a: emitted.append(a))

    dialog._title.set_text("Başlıq")
    dialog._message.setPlainText("Mətn.")
    dialog._scope_store_list.setChecked(True)
    # Heç bir checkbox işarələnməyib.
    _click(dialog, "Yayımla")

    assert emitted == []
    assert dialog._error.isVisible()
    assert "mağaza seçin" in dialog._error.text()


# --------------------------------------------------------------------------- #
# 3. Səhv/qəribə giriş — 10 000+ simvol, emoji, SQL-bənzər mətn ÇÖKMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_extreme_and_hostile_text_passes_through_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """UI qatı mətni MƏZMUNCA yoxlamır (domen edir) — burada ölçülən ÇÖKMƏMƏKDİR."""
    from src.presentation.controllers.announcements import AnnouncementsAdminController
    from src.presentation.screens.announcements import AnnouncementsScreen

    announcements = _Announcements()
    context = _Context(announcements, [])
    screen = AnnouncementsScreen(theme)
    qtbot.addWidget(screen)
    AnnouncementsAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    hostile_title = "'; DROP TABLE announcements; -- 🔥" * 5
    hostile_message = "😀" * 500 + "A" * 10_000
    _patched_exec(monkeypatch, title=hostile_title, message=hostile_message)

    _click(screen, "Yeni Elan")  # ÇÖKMƏMƏLİDİR

    assert len(announcements.broadcasts) == 1
    draft = announcements.broadcasts[0]
    assert draft.title_az == hostile_title.strip()
    assert draft.message == hostile_message.strip()


# --------------------------------------------------------------------------- #
# 4. Use case istisnası — istifadəçi AÇIQ mesaj görür, sükutla udulmur
# --------------------------------------------------------------------------- #


@requires_qt
def test_broadcast_failure_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Səlahiyyət rədd edilməsi (`AuthorizationError`) burdan da keçir."""
    from src.presentation.controllers.announcements import AnnouncementsAdminController
    from src.presentation.screens.announcements import AnnouncementsScreen

    announcements = _Announcements()
    announcements.broadcast_error = KompasOSError(
        "no permission", user_message="Bu əməliyyat üçün icazəniz yoxdur."
    )
    context = _Context(announcements, [])
    screen = AnnouncementsScreen(theme)
    qtbot.addWidget(screen)
    AnnouncementsAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _patched_exec(monkeypatch, title="Başlıq", message="Mətn")
    _click(screen, "Yeni Elan")

    assert not any(s.committed for s in context.sessions), (
        "İstisna atılıbsa commit() ÇAĞIRILMAMALI idi"
    )
    # `show_error` `ContentSwitcher`-i xəta vəziyyətinə keçirir.
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 5. Geri çəkmə — real cədvəl sətri, real "Geri Çək" kliki
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_withdraw_on_a_real_row_calls_withdraw_and_refreshes(qtbot, qt_app, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.announcements import AnnouncementsAdminController
    from src.presentation.screens.announcements import AnnouncementsScreen

    announcement_id = uuid.uuid4()
    announcements = _Announcements()
    announcements.rows = [
        _view(
            announcement_id=announcement_id,
            title="Aktiv elan",
            message="mətn",
            scope="ALL",
            is_active=True,
        )
    ]
    context = _Context(announcements, [])
    screen = AnnouncementsScreen(theme)
    qtbot.addWidget(screen)
    AnnouncementsAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    # İkinci `refresh()` geri çəkilmiş vəziyyəti göstərsin deyə sətri dəyişirik.
    def _withdraw_then_deactivate(*, tenant_id: Any, actor: Any, announcement_id: Any) -> None:
        announcements.withdrawals.append(announcement_id)
        announcements.rows = [
            _view(
                announcement_id=announcement_id,
                title="Aktiv elan",
                message="mətn",
                scope="ALL",
                is_active=False,
            )
        ]

    announcements.withdraw = _withdraw_then_deactivate  # type: ignore[method-assign]

    _click(screen, "Geri Çək")

    assert [str(x) for x in announcements.withdrawals] == [str(announcement_id)]
    assert any(s.committed for s in context.sessions)
    # `clear_layout()` köhnə cədvəli `deleteLater()` ilə silir. Adi
    # `processEvents()` təxirə salınmış silinməni EMAL ETMİR (`test_background_
    # task.py::test_a_late_result_never_touches_a_destroyed_owner` ilə eyni
    # qərar) — `sendPostedEvents` AÇIQ çağırılmalıdır.
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QPushButton

    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()
    # Yenidən oxumadan sonra "Geri Çək" düyməsi ARTIQ yoxdur (yalnız aktiv sətirdə çıxır).
    assert "Geri Çək" not in [b.text() for b in screen.findChildren(QPushButton)]


@requires_qt
def test_withdraw_failure_shows_an_error_and_refreshes_instead_of_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Elan bu arada başqası tərəfindən geri çəkilibsə də — AÇIQ cavab, çökmə yox.

    ──────────────────────────────────────────────────────────────────────────
    HAZIRDA QIRMIZI — BUQ (bax `SendMessage` ilə `ui`-a göndərilən tapıntı)
    ──────────────────────────────────────────────────────────────────────────
    `_on_withdraw`-un `except KompasOSError` qolu `show_error(...)` çağırır,
    LAKİN elə həmin sətirdən sonra `self.refresh(screen)` da çağırır. `refresh()`
    `list_recent()` uğurla qayıdanda `set_announcements()` → `show_content()`
    işə düşür və bu, `ContentSwitcher`-i DƏRHAL (heç bir render arası olmadan)
    "content" vəziyyətinə qaytarır — göstərilən xəta HEÇ VAXT ekranda
    görünmür. Şərhdəki vəd («admin AÇIQ cavab alır») kodun etdiyinin ƏKSİdir.
    """
    from src.presentation.controllers.announcements import AnnouncementsAdminController
    from src.presentation.screens.announcements import AnnouncementsScreen

    announcement_id = uuid.uuid4()
    announcements = _Announcements()
    announcements.rows = [
        _view(
            announcement_id=announcement_id,
            title="Aktiv elan",
            message="mətn",
            scope="ALL",
            is_active=True,
        )
    ]
    announcements.withdraw_error = KompasOSError(
        "already withdrawn", user_message="Bu elan artıq geri çəkilib."
    )
    context = _Context(announcements, [])
    screen = AnnouncementsScreen(theme)
    qtbot.addWidget(screen)
    AnnouncementsAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Geri Çək")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_malformed_announcement_id_from_a_stale_row_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Siqnal köhnəlmiş sətirdən naməlum sətirdən gələ bilər — `_on_withdraw` UUID yoxlayır."""
    from src.presentation.controllers.announcements import AnnouncementsAdminController
    from src.presentation.screens.announcements import AnnouncementsScreen

    announcements = _Announcements()
    context = _Context(announcements, [])
    screen = AnnouncementsScreen(theme)
    qtbot.addWidget(screen)
    AnnouncementsAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.withdraw_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert announcements.withdrawals == []
    assert screen.switcher().current_state() == "error"
