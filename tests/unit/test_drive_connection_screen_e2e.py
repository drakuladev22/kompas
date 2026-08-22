"""`DriveConnectionScreen` ↔ `controllers/drive_connection.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, dördüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`test_drive_connections.py` (`tests/integration/`) YALNIZ `DriveConnectionRepository`-ni
sınayır — GUI heç yerdə qurulmur, `DriveConnectionController` heç bir testdə adı
çəkilmir. Burada həm ekran, həm kontroller FAKTİKİ qurulur: «Google Hesabı Qoş»
düyməsi REAL kliklənir, `DriveOAuthFlow` isə `_FakeFlow` ilə əvəz olunur — heç bir
real HTTP/soket açılmır (`start()` real halda lokal port açır, `exchange()` isə
Google-a POST göndərir — hər ikisi sahtədir).

`InlineExecutor` işlədilir ki, `_complete()`-in fon işi (`run_job`) test sapında
SİNXRON icra olunsun (CLAUDE.md bölmə 6 — "qeyri-sabit test heç bir testdən
pisdir").

──────────────────────────────────────────────────────────────────────────────
DÜZƏLDİLMİŞ QÜSUR — TRANZİT XƏTA BÜTÜN EKRANI ÖLDÜRÜRDÜ, GERİ QAYITMA YOLU YOX İDİ
──────────────────────────────────────────────────────────────────────────────
`drive_connection.py`-dəki ALTI yerdə (`_on_connect`-in icazə qapısı, Google
konfiqurasiyası yoxdursa, OAuth başlamırsa, `_poll`-un taymautu və iki istisna
qolu) ƏVVƏL `screen.show_error(...)` çağırılırdı. `Screen.show_error()` isə
`ContentSwitcher`-i xəta vəziyyətinə keçirir — bu, `QStackedWidget.
setCurrentWidget()`-dir və status kartını (Aktiv hesab, «Google Hesabı Qoş»/
«Ləğv Et» düymələri, tarixçə) TAM GİZLƏDİR (`base.py::ContentSwitcher.
set_content/show_content`).

Heç bir çağırış `on_retry=` ötürmürdü, `base.py:442`-dəki qayda isə açıq
deyir: "`on_retry` VERİLMƏYİBSƏ ƏSAS DÜYMƏ ÜMUMİYYƏTLƏ ÇƏKİLMİR" — yəni
«Yenidən Cəhd Et» düyməsi belə göstərilmirdi. Üstəlik `AdminShell._screens`
ekranı BİR DƏFƏ qurub saxlayır (`shell/admin_shell.py::show_screen`) və
`KompasApplication.REFRESH_ON_REVISIT` yalnız `{"dashboard"}`-dır —
administrator bölmədən çıxıb geri qayıtsa belə `refresh()` YENİDƏN
ÇAĞIRILMIRDI. Nəticə: bir dəfə icazəsiz klik, bir dəfə Google
konfiqurasiyasının boş olması və ya bir dəfə razılıq taymautu — sessiyanın
SONUNA qədər bu ekranı istifadəyə yararsız qoyurdu.

DÜZƏLİŞ (`ui` sahibi): bu altı hal artıq `screen.set_connect_message(...)`
işlədir — mətn status kartının İÇİNDƏ qalır, `ContentSwitcher` toxunulmur
(bax `group_d.py::DriveConnectionScreen.set_connect_message`). Aşağıdakı iki
test əvvəl `xfail(strict=True)` idi, indi XPASS olduğu üçün marker silinib.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()


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


def _label_texts(screen: Any) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in screen.findChildren(QLabel)]


# --------------------------------------------------------------------------- #
# Sahtələr — heç bir real HTTP/soket, heç bir real DB
# --------------------------------------------------------------------------- #


def _default_request(url: str | None = None) -> Any:
    from src.infrastructure.storage.oauth_flow import AuthorizationRequest

    return AuthorizationRequest(
        url=url or "https://accounts.google.com/o/oauth2/auth?client_id=test&state=abc",
        redirect_uri="http://127.0.0.1:53219",
        state="abc",
        code_verifier="verifier",
    )


class _FakeFlow:
    """`DriveOAuthFlow`-un yerini tutur — real port/HTTP AÇILMIR.

    Sinif dəyişənləri test-lər arası PAYLAŞILIR (`_FakeSandbox.behavior`
    naxışının eynisi, `test_plugin_page_screen_e2e.py`) — hər test öz
    ssenarisini `monkeypatch`-dən ƏVVƏL, `attach` çağırmazdan ƏVVƏL təyin
    edir. `_reset_fake_flow` avtomatik-fixture-u hər testdən ƏVVƏL sıfırlayır.
    """

    start_result: ClassVar[Any] = None
    poll_results: ClassVar[list[Any]] = [None]
    exchange_result: ClassVar[Any] = None
    instances: ClassVar[list[_FakeFlow]] = []

    def __init__(self, _oauth: Any) -> None:
        self._poll_index = 0
        self.close_called = False
        type(self).instances.append(self)

    def start(self) -> Any:
        if isinstance(type(self).start_result, Exception):
            raise type(self).start_result
        return type(self).start_result

    @staticmethod
    def open_browser(_request: Any) -> bool:
        return True

    def poll(self) -> Any:
        results = type(self).poll_results
        index = min(self._poll_index, len(results) - 1)
        result = results[index]
        self._poll_index += 1
        if isinstance(result, Exception):
            raise result
        return result

    def exchange(self, _code: str) -> Any:
        if isinstance(type(self).exchange_result, Exception):
            raise type(self).exchange_result
        return type(self).exchange_result

    def close(self) -> None:
        self.close_called = True


@pytest.fixture(autouse=True)
def _reset_fake_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.storage import oauth_flow as oauth_flow_module

    monkeypatch.setattr(oauth_flow_module, "DriveOAuthFlow", _FakeFlow)
    _FakeFlow.start_result = _default_request()
    _FakeFlow.poll_results = [None]
    _FakeFlow.exchange_result = None
    _FakeFlow.instances = []


@pytest.fixture(autouse=True)
def _google_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_SECRET", "test-client-secret")


class _Status:
    def __init__(self, value: str) -> None:
        self.value = value


class _ConnectionRecord:
    def __init__(
        self,
        *,
        status: str = "ACTIVE",
        email: str = "finance@acme.com",
        used: int | None = None,
        total: int | None = None,
        connected_at: datetime | None = None,
        archived_at: datetime | None = None,
    ) -> None:
        self.id = uuid.uuid4()
        self.status = _Status(status)
        self.google_account_email = email
        self.quota_used_bytes = used
        self.quota_total_bytes = total
        self.connected_at = connected_at or datetime.now(UTC)
        self.archived_at = archived_at


class _FakeAudit:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        if self.fails:
            raise KompasOSError("audit yazılmadı")
        self.records.append(kwargs)


class _FakeUow:
    def __init__(self, audit: _FakeAudit) -> None:
        self.audit = audit


class _FakeSession:
    def __init__(self, audit: _FakeAudit, commits: list[bool]) -> None:
        self.uow = _FakeUow(audit)
        self._commits = commits

    def commit(self) -> None:
        self._commits.append(True)


class _Limits:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def float_of(self, _key: Any) -> float:
        return self._seconds


class _FakeContext:
    """`ApplicationContext`-in yerini tutur — real DB bağlantısı AÇILMIR."""

    def __init__(self, *, audit_fails: bool = False, timeout_seconds: float = 5.0) -> None:
        self.tenant_id = TENANT
        self.database = object()  # `_repository()` instansiya səviyyəsində əvəzlənir
        self._audit = _FakeAudit(fails=audit_fails)
        self._timeout = timeout_seconds
        self.commits: list[bool] = []
        self.sessions: list[_FakeSession] = []
        self.invalidate_calls = 0
        self.evidence_upload_calls = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        _ = user_id
        created = _FakeSession(self._audit, self.commits)
        self.sessions.append(created)
        yield created

    def infrastructure_limits(self) -> _Limits:
        return _Limits(self._timeout)

    def invalidate_drive_providers(self) -> None:
        self.invalidate_calls += 1

    def run_evidence_uploads(self) -> None:
        self.evidence_upload_calls += 1


class _FakeRepo:
    def __init__(
        self,
        *,
        rows: list[_ConnectionRecord] | None = None,
        list_error: Exception | None = None,
        connect_result: _ConnectionRecord | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self.rows = rows or []
        self._list_error = list_error
        self._connect_result = connect_result or _ConnectionRecord()
        self._connect_error = connect_error
        self.connect_calls: list[dict[str, Any]] = []

    def list_all(self) -> list[_ConnectionRecord]:
        if self._list_error is not None:
            raise self._list_error
        return list(self.rows)

    def connect(self, **kwargs: Any) -> _ConnectionRecord:
        self.connect_calls.append(kwargs)
        if self._connect_error is not None:
            raise self._connect_error
        return self._connect_result


class _Actor:
    def __init__(self, *, permitted: bool = True) -> None:
        self.id = uuid.uuid4()
        self._permitted = permitted

    def has_permission(self, _flag: str, *, now: datetime) -> bool:
        _ = now
        return self._permitted


def _attach(
    screen: Any,
    *,
    context: _FakeContext,
    actor: _Actor,
    repo: _FakeRepo,
) -> Any:
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.drive_connection import DriveConnectionController

    controller = DriveConnectionController(context, actor, executor=InlineExecutor())
    # `_repository()`/`_encryption()` real infrastruktura (DB bağlantısı,
    # `KOMPASOS_FERNET_KEY`) müraciət edir — instansiya səviyyəsində əvəzlənir,
    # çünki hər ikisi kontrollerin İÇİNDƏ, lokal idxaldan sonra qurulur.
    controller._repository = lambda: repo  # type: ignore[method-assign]
    controller._encryption = object  # type: ignore[method-assign]
    controller.attach(screen)
    return controller


# --------------------------------------------------------------------------- #
# 1. Baza doldurma — REAL ekranda REAL mətn
# --------------------------------------------------------------------------- #


@requires_qt
def test_refresh_renders_the_active_connection_and_history(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    row = _ConnectionRecord(
        status="ACTIVE", email="finance@acme.com", used=2 * 1024**3, total=15 * 1024**3
    )
    repo = _FakeRepo(rows=[row])
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)

    _attach(screen, context=_FakeContext(), actor=_Actor(), repo=repo)

    assert screen._account.text() == "finance@acme.com"
    assert screen._status_chip.text() == "Aktiv"
    assert "%" in screen._quota.text()
    assert "finance@acme.com" in _label_texts(screen)


@requires_qt
def test_no_connection_shows_the_neutral_not_connected_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)

    _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo(rows=[]))

    assert screen._account.text() == "Hesab qoşulmayıb"
    assert screen._status_chip.text() == "Qoşulmayıb"
    assert screen._connect.text() == "Google Hesabı Qoş"


@requires_qt
def test_archived_connection_status_is_shown_not_hidden_as_unconnected(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Kvota bitmiş/razılığı ləğv edilmiş hesab «qoşulmayıb» kimi GÖRÜNMƏMƏLİDİR
    (kontroller başlığı: bu, əvvəlki real qüsurun düzəlişidir — REQRESSİYA testi)."""
    from src.presentation.screens.group_d import DriveConnectionScreen

    row = _ConnectionRecord(status="REVOKED", email="old@acme.com")
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)

    _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo(rows=[row]))

    assert screen._account.text() == "old@acme.com"
    assert screen._status_chip.text() == "İcazə ləğv edilib"


# --------------------------------------------------------------------------- #
# 2. Bağlan / Ləğv Et — REAL klik
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_connect_starts_the_flow_and_shows_the_auth_url(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    hostile_url = (
        "https://accounts.google.com/o/oauth2/auth?state="
        + "A" * 5_000
        + "&note='; DROP TABLE drive_connections; --🔥"
    )
    _FakeFlow.start_result = _default_request(hostile_url)
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")  # ÇÖKMƏMƏLİDİR

    # `isVisible()` YAZILMIR: `screen` heç vaxt `.show()` edilmir (headless
    # test), yəni əcdad zənciri "ekranda" sayılmır və `isVisible()` HƏMİŞƏ
    # `False` qaytarardı — vəziyyəti `setVisible()`-in ÖZÜ təyin etdiyi
    # `isHidden()` bayrağı ilə yoxlayırıq.
    assert screen._auth_url.text() == hostile_url
    assert not screen._pending.isHidden()
    assert not screen._connect.isEnabled()
    assert not screen._cancel.isHidden()
    assert controller._timer is not None
    assert controller._timer.isActive()


@requires_qt
def test_clicking_cancel_while_pending_stops_the_timer_and_closes_the_flow(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")
    flow = _FakeFlow.instances[-1]
    _click(screen, "Ləğv Et")

    assert flow.close_called
    assert controller._timer is None
    assert controller._flow is None
    assert screen._pending.isHidden()
    assert screen._connect.isEnabled()


@requires_qt
def test_double_clicking_connect_does_not_start_two_parallel_flows(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sürətli ikiqat klik — `_flow is not None` qapısı ikinci axını rədd edir."""
    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    # `_connect.setEnabled(False)` ilk klikdən sonra iş görür, lakin siqnal
    # birbaşa `connect_requested`-ə bağlıdır — proqramatik ikinci `emit`
    # düymənin deaktivliyini keçib real qısayol/sürətli klik ssenarisini
    # sınayır.
    screen.connect_requested.emit()
    screen.connect_requested.emit()

    assert len(_FakeFlow.instances) == 1


@requires_qt
def test_destroying_the_screen_mid_poll_kills_the_timer_too_no_runtime_error(theme) -> None:  # type: ignore[no-untyped-def]
    """`app.py::_attach_drive_connection` başlığının iddiasını YOXLAYIR:

        "Gözləmə taymeri də `screen`-in övladıdır, ona görə ekran
        bağlananda o da dayanır."

    Bu, layihənin BİLİNƏN tələsidir (`clear_layout()` sonrası `field.text()`
    → `RuntimeError`, Qt slotunda SÜKUTLA udulur). `QTimer(screen)` HƏQİQƏTƏN
    C++ övladıdırsa, `screen`-in məhvi ilə taymer də DƏRHAL məhv olmalıdır —
    bu isə o deməkdir ki, `_poll()` heç vaxt "ölü" ekrana müraciət EDƏ BİLMİR
    (Qt eyni-sap `QTimer.timeout`-u birbaşa çağırır, növbəyə YAZMIR, yəni
    "artıq göndərilmiş, hələ çatmamış" tıqqıltı riski YOXDUR).

    `qtbot.addWidget()` İŞLƏDİLMİR: bu test ekranı ƏLLƏ, DƏRHAL məhv edir —
    pytest-qt-nin öz təmizləməsi artıq-ölü C++ obyektinə toxunmasın.
    """
    import shiboken6

    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    controller = _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    screen.connect_requested.emit()  # taymer başlayır
    timer = controller._timer
    assert timer is not None
    assert shiboken6.isValid(timer)

    shiboken6.delete(screen)  # `set_employee()`-in `deleteLater()`-inin ANİ forması

    assert not shiboken6.isValid(timer)  # C++ övladı valideynlə BİRLİKDƏ öldü


# --------------------------------------------------------------------------- #
# 3. Poll — taymaut, `StorageError`, gözlənilməz istisna
# --------------------------------------------------------------------------- #


@requires_qt
def test_poll_timeout_shows_an_error_and_stops_the_timer(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    context = _FakeContext(timeout_seconds=0.1)  # 100 ms — testi UZATMIR
    _FakeFlow.poll_results = [None]  # heç vaxt kod gəlmir
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=context, actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")
    # Taymer real 200 ms gözləmədən, birbaşa `_poll` çağırılır (CLAUDE.md
    # bölmə 6 — hadisə dövrəsi gözləməsi YAZILMIR). `_elapsed_ms` hər
    # çağırışda `POLL_INTERVAL_MS` (200) artır, hədd isə 100 ms-dir — bir
    # tıqqıltı kifayətdir.
    controller._poll(screen)  # ÇÖKMƏMƏLİDİR

    assert controller._timer is None
    assert controller._flow is None
    assert any("vaxtı bitdi" in text for text in _label_texts(screen))


@requires_qt
def test_poll_storage_error_shows_the_users_message_not_a_traceback(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.domain.value_objects.storage import StorageError
    from src.presentation.screens.group_d import DriveConnectionScreen

    _FakeFlow.poll_results = [
        StorageError("internal detail", user_message="Google hesabına icazə verilmədi.")
    ]
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")
    controller._poll(screen)  # ÇÖKMƏMƏLİDİR

    texts = _label_texts(screen)
    assert any("Google hesabına icazə verilmədi." in text for text in texts)
    assert not any("internal detail" in text for text in texts)


@requires_qt
def test_poll_unexpected_exception_shows_the_generic_message_and_is_logged(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`except Exception` qolu — proqramlaşdırma xətası da UI-ı ÇÖKDÜRMƏMƏLİDİR."""
    from src.presentation.screens.group_d import DriveConnectionScreen

    _FakeFlow.poll_results = [TypeError("gözlənilməz daxili xəta")]
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")
    controller._poll(screen)  # ÇÖKMƏMƏLİDİR

    assert any("Gözlənilməz xəta baş verdi" in text for text in _label_texts(screen))


# --------------------------------------------------------------------------- #
# 4. Uğurlu mübadilə — audit, commit, refresh, "gözləyən şəkillər" tetiklənir
# --------------------------------------------------------------------------- #


@requires_qt
def test_successful_exchange_writes_the_connection_commits_audit_and_refreshes(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.storage.oauth_flow import DriveCredentials
    from src.presentation.screens.group_d import DriveConnectionScreen

    _FakeFlow.poll_results = ["auth-code-123"]
    _FakeFlow.exchange_result = DriveCredentials(
        refresh_token="rt-secret", account_email="new@acme.com"
    )
    new_row = _ConnectionRecord(status="ACTIVE", email="new@acme.com")
    context = _FakeContext()
    # İLK `refresh()` (`attach()` daxilində) BOŞ siyahı görməlidir ki, düymə
    # "Google Hesabı Qoş" mətnini SAXLASIN (`_click` mətnə görə axtarır).
    # Uğurlu mübadilədən sonrakı İKİNCİ `refresh()` isə YENİ sətri görməlidir
    # — ona görə sətir `_attach()`-dan SONRA əlavə olunur.
    repo = _FakeRepo(rows=[], connect_result=new_row)
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=context, actor=_Actor(), repo=repo)
    repo.rows = [new_row]

    _click(screen, "Google Hesabı Qoş")
    controller._poll(screen)  # kod gəlir → `InlineExecutor` mübadiləni SİNXRON bitirir

    # 1) YAZI — token repository-yə getdi, EKRANA DEYİL (SEC-017/modul başlığı).
    assert len(repo.connect_calls) == 1
    assert repo.connect_calls[0]["refresh_token"] == "rt-secret"
    assert not any("rt-secret" in text for text in _label_texts(screen))
    # 2) AUDİT — ayrıca qısa sessiya açıldı və commit edildi.
    assert len(context.commits) == 1
    assert context.sessions[0].uow.audit.records[0]["action"] == "DRIVE_CONNECTION_ESTABLISHED"
    # 3) Provayder keşi etibarsızlaşdı, gözləyən sübutlar dərhal işə salındı.
    assert context.invalidate_calls == 1
    assert context.evidence_upload_calls == 1
    # 4) Ekran yeni vəziyyəti göstərir, pending kart bağlandı.
    assert screen._account.text() == "new@acme.com"
    assert screen._pending.isHidden()


@requires_qt
def test_audit_write_failure_after_a_successful_connect_is_not_swallowed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`_record_audit` istisnası UDULMUR — istifadəçi audit itkisini GÖRMƏLİDİR
    (CLAUDE.md bölmə 5: "Audit yazısı istisna udmur" + modul başlığındakı izah)."""
    from src.infrastructure.storage.oauth_flow import DriveCredentials
    from src.presentation.screens.group_d import DriveConnectionScreen

    _FakeFlow.poll_results = ["auth-code-456"]
    _FakeFlow.exchange_result = DriveCredentials(
        refresh_token="rt-2", account_email="broken-audit@acme.com"
    )
    context = _FakeContext(audit_fails=True)
    repo = _FakeRepo(connect_result=_ConnectionRecord(email="broken-audit@acme.com"))
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=context, actor=_Actor(), repo=repo)

    _click(screen, "Google Hesabı Qoş")
    controller._poll(screen)

    assert len(repo.connect_calls) == 1  # bağlantı YAZILDI
    assert any("Audit izi yazılmadı" in text for text in _label_texts(screen))


@requires_qt
def test_exchange_failure_with_kompasos_error_shows_its_user_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    _FakeFlow.poll_results = ["code"]
    _FakeFlow.exchange_result = KompasOSError(
        "internal", user_message="Google `refresh_token` göndərmədi."
    )
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")
    controller._poll(screen)  # ÇÖKMƏMƏLİDİR

    assert any("Google `refresh_token` göndərmədi." in text for text in _label_texts(screen))


@requires_qt
def test_exchange_failure_with_unexpected_exception_shows_the_generic_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    _FakeFlow.poll_results = ["code"]
    _FakeFlow.exchange_result = RuntimeError("gözlənilməz")
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")
    controller._poll(screen)  # ÇÖKMƏMƏLİDİR

    assert any("Bağlantı yazıla bilmədi" in text for text in _label_texts(screen))


# --------------------------------------------------------------------------- #
# 5. Səlahiyyət qapısı — flag EKRANDA DEYİL, KLİKDƏ yoxlanır (modul başlığı)
# --------------------------------------------------------------------------- #


@requires_qt
def test_connect_button_is_always_rendered_but_permission_is_checked_on_click(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Modulun ÖZ dizaynı: menyu bölməni gizlədir, düymə isə HƏMİŞƏ görünür və
    hər klikdə flag yenidən yoxlanır (`_permitted()`). Bu, `e2e` tapşırığındakı
    "düymə ÜMUMİYYƏTLƏ render olunmur" gözləntisindən FƏRQLİDİR — kod BUNU
    qəsdən belə qurmayıb, çünki bölmə səviyyəli qapı artıq `menu.py`-dadır."""
    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    _attach(screen, context=_FakeContext(), actor=_Actor(permitted=False), repo=_FakeRepo())

    assert not screen._connect.isHidden()

    _click(screen, "Google Hesabı Qoş")

    assert not _FakeFlow.instances  # OAuth axını HEÇ BAŞLAMADI


# --------------------------------------------------------------------------- #
# 6. Google konfiqurasiyası yoxdur — aydın mesaj, çökmə yox
# --------------------------------------------------------------------------- #


@requires_qt
def test_missing_google_config_shows_an_actionable_message(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    monkeypatch.delenv("KOMPASOS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("KOMPASOS_GOOGLE_CLIENT_SECRET", raising=False)
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    _attach(screen, context=_FakeContext(), actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")  # ÇÖKMƏMƏLİDİR

    assert not _FakeFlow.instances
    assert any("KOMPASOS_GOOGLE_CLIENT_ID" in text for text in _label_texts(screen))


# --------------------------------------------------------------------------- #
# 7. Sıfır/xəta yükləmə cavabı — banner ekranı ÖLDÜRMÜR, oxunaqlı qalır
# --------------------------------------------------------------------------- #


@requires_qt
def test_list_all_failure_shows_an_error_instead_of_a_blank_or_crashed_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    repo = _FakeRepo(list_error=RuntimeError("DB bağlantısı kəsildi"))
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    _attach(screen, context=_FakeContext(), actor=_Actor(), repo=repo)  # ÇÖKMƏMƏLİDİR

    assert any("Bağlantılar oxunmadı" in text for text in _label_texts(screen))
    assert not any("DB bağlantısı kəsildi" in text for text in _label_texts(screen))


# --------------------------------------------------------------------------- #
# 8. TAPILAN QÜSUR — tranzit xəta bütün ekranı ölü-son qoyur (bax fayl başlığı)
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_permission_denied_click_does_not_permanently_dead_end_the_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    _attach(screen, context=_FakeContext(), actor=_Actor(permitted=False), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")

    # DÜZƏLDİLDİ (QA-FULL FAZA 3 tapıntısı, `ui` sahibi): icazə qapısı artıq
    # `screen.set_connect_message(...)` işlədir — status kartı, «Google
    # Hesabı Qoş» düyməsi və tarixçə YERİNDƏ qalır, `ContentSwitcher`
    # toxunulmur.
    assert screen.switcher().current_state() == "content"


@requires_qt
def test_a_poll_timeout_does_not_permanently_dead_end_the_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import DriveConnectionScreen

    context = _FakeContext(timeout_seconds=0.1)
    _FakeFlow.poll_results = [None]
    screen = DriveConnectionScreen(theme)
    qtbot.addWidget(screen)
    controller = _attach(screen, context=context, actor=_Actor(), repo=_FakeRepo())

    _click(screen, "Google Hesabı Qoş")
    controller._poll(screen)

    assert screen.switcher().current_state() == "content"


def test_drive_connection_is_not_in_the_revisit_refresh_allowlist() -> None:
    """Sənədləşdirmə testi (`src`-ə TOXUNMUR): yuxarıdakı iki `xfail`-in NİYƏ
    "naviqasiyadan çıxıb-geri qayıt" ilə düzəlmədiyini SÜBUT edir.

    `app.py::KompasApplication._on_screen_revisited` YALNIZ `REFRESH_ON_REVISIT`
    siyahısındakı açarlar üçün `refresh()`-ə bənzər yenidənqurma tetikləyir.
    `"drive_connection"` orada YOXDUR — deməli ekranın konstruktor anında
    qurulmuş TƏK kontrolleri var və `show_error()` bir dəfə çağırılandan
    sonra onu düzəldəcək HEÇ BİR avtomatik yol yoxdur (yalnız yenidən giriş,
    yəni `AdminShell.set_employee()`-in ekranları silib-yenidən qurması).
    """
    from src.presentation.app import KompasApplication

    assert "drive_connection" not in KompasApplication.REFRESH_ON_REVISIT
