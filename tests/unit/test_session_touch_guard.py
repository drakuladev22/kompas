"""Sessiya-toxunma zənciri — `KompasApplication` səviyyəsi (SEC-011 / SEC-5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL AYRICADIR
──────────────────────────────────────────────────────────────────────────────
`test_authentication.py` `SessionManagementUseCase`-in ÖZÜNÜ (domen/tətbiq
qatı) ölçür — `touch()` `absolute_expiry`-ni uzatmır, `validate()` müddəti
bitmişi rədd edir və s. BURADA isə fərqli bir sual ölçülür: `app.py`-nin
həmin use case-i DÜZGÜN SIRAYLA çağırıb-çağırmadığı.

`_touch_session()` ƏVVƏLCƏ `validate()`, SONRA `touch()` çağırmalıdır —
yalnız `touch()` çağırsaydı, admin sessiyanı UZAQDAN LƏĞV ETSƏ belə yerli
QTimer bunu HEÇ VAXT öyrənməzdi (bax `app.py::_touch_session` başlığı).
Bu sıra `SessionManagementUseCase`-in öz testlərində ÖLÇÜLƏ BİLMƏZ — hər
ikisi ORADA mövcuddur, sıranı YALNIZ ÇAĞIRAN (`app.py`) təyin edir.

──────────────────────────────────────────────────────────────────────────────
UI-02 (dövrə 1 audit) — DB İŞİ İNDİ `BackgroundTask`-DADIR, TESTLƏR DƏ ONA GÖRƏ
──────────────────────────────────────────────────────────────────────────────
`_touch_session()` daha ARTIQ SİNXRON deyil (GUI sapını donduran DB gediş-
gəlişi `BackgroundTask`-a köçürülüb, bax `app.py::_touch_session` UI-02
bölməsi). Aşağıdakı `_drain_until` `qt_app.processEvents()` işlədərək
`QThreadPool` işçisinin bitib nəticəni `QueuedConnection`-la geri
göndərməsini gözləyir — sabit `sleep` YOX, çünki bu, maşın sürətindən asılı
qeyri-sabit test yaradardı (eyni naxış `test_background_job_funnel.py::
_drain`-dədir).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tests.fixtures.fakes import FakeClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _drain_until(qt_app: Any, predicate: Any, *, seconds: float = 5.0) -> None:
    """`predicate()` `True` olana qədər hadisə dövrəsini işlədir.

    Fon işi bitəndə nəticə Qt siqnalı ilə əsas sapa POSTLANIR — hadisə
    dövrəsi işləmədən o siqnal heç vaxt çatmaz (bax `background_task.py`
    modul başlığı, "SƏSSİZLİ NÖVBƏ" izahı).
    """
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()


def _pump(qt_app: Any, seconds: float) -> None:
    """Sabit müddət ərzində hadisə dövrəsini işlədir — MƏNFİ nəticəni ölçmək üçün.

    `_drain_until`-dan FƏRQİ: «bu BAŞ VERMƏDİ» iddiasını sübut etmək üçün
    şərtsiz gözləmə lazımdır (şərtli gözləmə «hələ baş verməyib» ilə «heç
    vaxt verməyəcək»-i ayırd edə bilməz).
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qt_app.processEvents()


def _application(qt_app: Any) -> Any:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    return KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT, context=None)


class _FakeSessions:
    """`SessionManagementUseCase`-in çağırış SIRASINI qeyd edən sahtəsi."""

    def __init__(self, *, validate_error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.validate_error = validate_error
        self.touched_with: Any = None

    def validate(self, *, tenant_id: Any, token: str) -> Any:
        self.calls.append("validate")
        if self.validate_error is not None:
            raise self.validate_error
        return "VALIDATED_SESSION"

    def touch(self, *, tenant_id: Any, session: Any) -> Any:
        self.calls.append("touch")
        self.touched_with = session
        return session


class _FakeSession:
    def __init__(self, sessions: _FakeSessions) -> None:
        self.tenant_id = "tenant"
        self.sessions = sessions
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakeContext:
    def __init__(self, sessions: _FakeSessions) -> None:
        self._session = _FakeSession(sessions)

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


# --------------------------------------------------------------------------- #
# `_touch_session()` — ƏVVƏLCƏ `validate()`, SONRA `touch()`
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_touch_session_validates_before_touching(qt_app) -> None:  # type: ignore[no-untyped-def]
    """SIRA TƏSDİQLƏNİR: `touch()` YALNIZ `validate()`-in QAYTARDIĞI sessiya ilə çağrılır.

    UI-02: DB işi indi `BackgroundTask`-dadır — `_touch_session()` qayıdanda
    iş hələ ARXA SAPDA gedə bilər, ona görə `_drain_until` işçinin `is_running`
    `False`-a düşməsini (nəticə çatdırılıb) gözləyir.
    """
    application = _application(qt_app)
    sessions = _FakeSessions()
    application._context = _FakeContext(sessions)  # type: ignore[assignment]
    application._session_token = "açıq-token"
    application._current_employee = None

    application._touch_session()
    _drain_until(qt_app, lambda: not application._touch_task.is_running)

    assert sessions.calls == ["validate", "touch"]
    assert sessions.touched_with == "VALIDATED_SESSION"


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_touch_session_never_touches_when_validate_rejects(  # type: ignore[no-untyped-def]
    qt_app, monkeypatch
) -> None:
    """`validate()` `SessionExpiredError` atsa `touch()` HEÇ ÇAĞIRILMIR.

    TIME-1-in yerli qapıdan güclü olmasının SƏBƏBİ məhz budur: admin
    sessiyanı uzaqdan ləğv edibsə, yerli `touch()` onu YENİDƏN CANLANDIRA
    BİLMƏZ, çünki bu sətir ONA çatmır. UI-02: `SessionExpiredError` fon
    sapında atılır, `TaskOutcome.error`-a qoyulur və `_on_touch_failed`
    ƏSAS SAPDA `_on_session_expired`-ə YÖNLƏNDİRİR (bax `app.py`).
    """
    from src.application.use_cases.authentication import SessionExpiredError

    application = _application(qt_app)
    sessions = _FakeSessions(validate_error=SessionExpiredError("bitib"))
    application._context = _FakeContext(sessions)  # type: ignore[assignment]
    application._session_token = "açıq-token"
    application._current_employee = None
    reasons: list[str] = []
    monkeypatch.setattr(application, "_on_session_expired", reasons.append)

    application._touch_session()
    _drain_until(qt_app, lambda: bool(reasons))

    assert sessions.calls == ["validate"]  # `touch` YOXDUR
    assert reasons and "SEC-011" in reasons[0]


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_touch_session_survives_an_ordinary_network_failure(  # type: ignore[no-untyped-def]
    qt_app, monkeypatch
) -> None:
    """Ötəri şəbəkə xətası (`SessionExpiredError` DEYİL) yerli qapını POZMUR.

    UI-02: `_on_touch_failed` `SessionExpiredError` OLMAYAN hər şeyi
    `_log.error(..., exc_info=error)` ilə qeydə alır (əvvəl `_log.exception()`
    idi — bax `app.py`); bu, «iş həqiqətən bitdi» siqnalı kimi işlədilir.
    """
    from src.presentation import app as app_module

    application = _application(qt_app)
    sessions = _FakeSessions(validate_error=RuntimeError("bağlantı qırıldı"))
    application._context = _FakeContext(sessions)  # type: ignore[assignment]
    application._session_token = "açıq-token"
    application._current_employee = None
    expired_called: list[str] = []
    logged: list[str] = []
    monkeypatch.setattr(application, "_on_session_expired", expired_called.append)
    monkeypatch.setattr(app_module._log, "error", lambda key, **_: logged.append(key))

    application._touch_session()  # istisna ATMAMALIDIR
    _drain_until(qt_app, lambda: bool(logged))

    assert logged == ["SESSION_TOUCH_FAILED"]
    assert expired_called == []  # panel MƏCBURİ bağlanmadı


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_stopping_the_guard_drops_a_stale_touch_result(qt_app) -> None:  # type: ignore[no-untyped-def]
    """UI-02 — LOGOUT-dan sonra gecikmiş toxunma nəticəsi SÜKUTLA atılır.

    ──────────────────────────────────────────────────────────────────────
    HANSI QÜSURU TUTUR
    ──────────────────────────────────────────────────────────────────────
    DB işi fon sapına köçəndən sonra istifadəçi TAM DÜZGÜN logout edərkən
    köhnə bir `_touch_session()` hələ QAÇIRSA (nadir, amma mümkün), onun
    GECİKMİŞ nəticəsi `_stop_session_guard`-ın `cancel()` çağırmadığı halda
    `_on_session_expired`-i YENİDƏN tetikləyərdi — istifadəçi ARTIQ giriş
    ekranındadır, üstünə "sessiyanız bitdi" mesajı gələrdi.
    """
    from src.application.use_cases.authentication import SessionExpiredError

    application = _application(qt_app)
    sessions = _FakeSessions(validate_error=SessionExpiredError("bitib"))
    application._context = _FakeContext(sessions)  # type: ignore[assignment]
    application._session_token = "açıq-token"
    application._current_employee = None
    expired_called: list[str] = []
    application._on_session_expired = expired_called.append  # type: ignore[method-assign]

    application._touch_session()
    task = application._touch_task
    assert task is not None
    assert task.is_running  # fon işi HƏLƏ NƏTİCƏ VERMƏYİB

    application._stop_session_guard()  # istifadəçi normal LOGOUT edir

    assert not task.is_running  # `cancel()` DƏRHAL aktivliyi söndürür
    _pump(qt_app, 1.0)  # fon işinin ÖZÜ bitsin, gecikmiş nəticə YENƏ DƏ gəlsin

    assert expired_called == []  # gecikmiş nəticə köhnəlmiş sayılıb, SÜKUTLA atılıb


# --------------------------------------------------------------------------- #
# `_start_session_guard()` — `issue()` uğursuz olsa giriş DAYANMIR
# --------------------------------------------------------------------------- #


class _FailingIssueSessions:
    def issue(self, **kwargs: Any) -> Any:
        raise RuntimeError("baza əlçatmazdır")


class _FailingIssueSession:
    def __init__(self) -> None:
        self.tenant_id = "tenant"
        self.sessions = _FailingIssueSessions()

    def commit(self) -> None:
        pass


class _FailingIssueContext:
    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield _FailingIssueSession()


def _fake_employee() -> Any:
    position = type("_Position", (), {"is_camera_type": False})()
    return type("_Employee", (), {"id": "emp-1", "position": position})()


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_a_failed_session_issue_does_not_block_login(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`issue()` çökəndə giriş YENƏ TAMAMLANIR — server-tərəfli iz YALNIZ ƏLAVƏ qatdır.

    `app.py::_start_session_guard` başlığı: uğursuzluqda `self._session_token`
    `None` qalır və `SessionGuard`-a `touch=None` ötürülür — heç bir istisna
    çağıranı (girişi) YARIMÇIQ QOYMUR.
    """
    application = _application(qt_app)
    application._context = _FailingIssueContext()  # type: ignore[assignment]

    application._start_session_guard(_fake_employee())  # istisna ATMAMALIDIR

    assert application._session_token is None
    assert application._session_id is None
    assert application._session_guard is not None  # yerli qapı YENƏ DƏ qurulub


# --------------------------------------------------------------------------- #
# `ProfileController._on_close_sessions` — CARİ sessiya İSTİSNA edilir
# --------------------------------------------------------------------------- #


class _AuthSessionsRepo:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def list_recent_for_user(self, tenant_id: Any, user_id: Any, *, limit: int = 10) -> list[Any]:
        return list(self._rows)


class _RevokingSessions:
    def __init__(self) -> None:
        self.revoked: list[Any] = []

    def revoke(self, *, tenant_id: Any, actor: Any, target: Any, reason: str) -> None:
        self.revoked.append(target)


class _CloseSessionsUow:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._auth_sessions = _AuthSessionsRepo(rows)

    def repository(self, name: str) -> Any:
        assert name == "auth_sessions"
        return self._auth_sessions


class _CloseSessionsSession:
    def __init__(self, rows: list[SimpleNamespace], sessions: _RevokingSessions) -> None:
        self.tenant_id = "tenant"
        self.uow = _CloseSessionsUow(rows)
        self.sessions = sessions
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _CloseSessionsContext:
    """`ApplicationContext`-in minimal təkrarı — `.clock` da daxil (TIME-1)."""

    def __init__(self, rows: list[SimpleNamespace], sessions: _RevokingSessions) -> None:
        self._session = _CloseSessionsSession(rows, sessions)
        self.clock = FakeClock(NOW)

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


def _session_row(
    *, session_id: str, revoked_at: datetime | None, expires_at: datetime
) -> SimpleNamespace:
    return SimpleNamespace(id=session_id, revoked_at=revoked_at, expires_at=expires_at)


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_close_other_sessions_excludes_the_current_one(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """CARİ sessiya İSTİSNA, YALNIZ digər AKTİV sessiyalar ləğv olunur.

    `ui`-nin əl ilə sınadığı ÜÇ-sessiyalı ssenari (cari / digər aktiv /
    artıq bitmiş) burada avtomatlaşdırılır: YALNIZ ortadakı ləğv olunmalıdır.
    """
    from src.presentation.controllers.profile import ProfileController

    rows = [
        _session_row(
            session_id="CARİ", revoked_at=None, expires_at=NOW + timedelta(hours=8)
        ),  # istisna
        _session_row(
            session_id="DİGƏR-AKTİV", revoked_at=None, expires_at=NOW + timedelta(hours=8)
        ),  # ləğv OLUNMALIDIR
        _session_row(
            session_id="ARTIQ-BİTMİŞ", revoked_at=None, expires_at=NOW - timedelta(minutes=1)
        ),  # artıq ölü — toxunulmur
    ]
    from PySide6.QtWidgets import QMessageBox, QWidget

    sessions = _RevokingSessions()
    context = _CloseSessionsContext(rows, sessions)
    actor = SimpleNamespace(id="emp-1")
    controller = ProfileController(  # type: ignore[arg-type]
        context, actor, current_session_id="CARİ"
    )
    monkeypatch.setattr(controller, "refresh", lambda screen: None)
    # `_inform()` `QMessageBox(screen).exec()` çağırır (bax `profile.py`) —
    # `parent`-in HƏQİQİ `QWidget` olmasını PySide6 tələb edir (duck-type
    # sahtə işləmir), `exec()` isə real modal açıb TIKLANMAYA GÖZLƏYƏRDİ.
    # `qt_app` sayəsində real (boş) widget ucuzdur; `exec` monkeypatch edilir
    # ki, test "OK" düyməsini gözləyərək əbədi asılmasın.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
    screen = QWidget()

    controller._on_close_sessions(screen)  # type: ignore[arg-type]

    assert [row.id for row in sessions.revoked] == ["DİGƏR-AKTİV"]
    assert context._session.commits == 1
