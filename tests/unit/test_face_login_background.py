"""«Üzlə daxil ol» — kamera + 1:1 doğrulama FON SAPINDA (`app.py::_on_face_login_requested`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
Köhnə kodun ÖZÜ etiraf edirdi ki, kamera çəkilişi + 1:1 doğrulama saniyələr
çəkir və bu müddətdə "ekran donmuş görünürdü" — düzəliş yalnız `flush_ui()`
ilə busy vəziyyətini əvvəlcədən çəkməkdən ibarət idi (UX-1), iş isə yenə GUI
sapında qalırdı. Bu test `_touch_session`-ın `test_session_touch_guard.py`-dəki
sınağı ilə EYNİ üsulu işlədir: `FaceLoginController.authenticate()` fon
sapında (real `QThreadPool`) işə düşür, nəticə isə `QueuedConnection`-la əsas
sapa qayıdır — `_drain_until` `qt_app.processEvents()` ilə onu gözləyir.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _drain_until(qt_app: Any, predicate: Any, *, seconds: float = 5.0) -> None:
    """`predicate()` `True` olana qədər hadisə dövrəsini işlədir.

    Bax `test_session_touch_guard.py::_drain_until` — eyni əsaslandırma:
    fon işinin nəticəsi Qt siqnalı ilə qayıdır, hadisə dövrəsi işləmədən heç
    vaxt çatmaz.
    """
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()


def _application(qt_app: Any) -> Any:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    return KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT, context=None)


class _Login:
    """`AdminLoginScreen`-in kontrollerin toxunduğu hissəsinin əvəzi."""

    def __init__(self) -> None:
        self.busy_history: list[bool] = []
        self.errors: list[str] = []
        self.cleared = 0

    def set_busy(self, busy: bool) -> None:
        self.busy_history.append(busy)

    def set_error(self, message: str) -> None:
        self.errors.append(message)

    def clear(self) -> None:
        self.cleared += 1


def _patch_controller(monkeypatch: pytest.MonkeyPatch, *, outcome: Any) -> None:
    from src.presentation.controllers import face_login as face_login_module

    monkeypatch.setattr(
        face_login_module.FaceLoginController, "authenticate", lambda self, username: outcome
    )


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_face_login_does_not_block_the_gui_thread(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`_on_face_login_requested` NƏTİCƏ GƏLMƏMİŞ qayıtmalıdır (iş fon sapındadır).

    Köhnə (sinxron) versiyada bu metod `authenticate()` bitənə qədər
    QAYITMIRDI — yəni çağırış ÖZÜ bloklayardı. İndi `run_job` dərhal
    (nəticə gözləmədən) qayıtmalıdır, `_face_login_task.is_running` isə
    HƏLƏ `True` olmalıdır.
    """
    from src.presentation.controllers.face_login import FaceLoginOutcome

    application = _application(qt_app)
    application._context = object()  # `None` DEYİL — yoxlama budağını keçir
    application._login = _Login()  # type: ignore[assignment]

    block = __import__("threading").Event()

    def _slow_authenticate(self: Any, username: str) -> FaceLoginOutcome:
        block.wait(timeout=5.0)
        return FaceLoginOutcome(succeeded=False, message="test")

    from src.presentation.controllers import face_login as face_login_module

    monkeypatch.setattr(face_login_module.FaceLoginController, "authenticate", _slow_authenticate)

    application._on_face_login_requested("aysel")

    # ÇAĞIRIŞ ÖZÜ dərhal qayıtdı — iş hələ FON SAPINDA gedir.
    assert application._face_login_task is not None
    assert application._face_login_task.is_running
    assert application._login.busy_history == [True]

    block.set()
    _drain_until(qt_app, lambda: not application._face_login_task.is_running)


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_successful_face_login_clears_the_form_and_opens_the_panel(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_login import FaceLoginOutcome

    application = _application(qt_app)
    application._context = object()
    application._login = _Login()  # type: ignore[assignment]

    employee = object()
    _patch_controller(
        monkeypatch,
        outcome=FaceLoginOutcome(succeeded=True, employee=employee),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(application, "_show_face_setup_if_required", lambda *a, **k: False)
    opened: list[Any] = []

    def _fake_show_admin(emp: Any, *, now: Any, on_ready: Any = None) -> None:
        opened.append(emp)

    monkeypatch.setattr(application, "show_admin", _fake_show_admin)

    application._on_face_login_requested("aysel")
    _drain_until(qt_app, lambda: not application._face_login_task.is_running)
    # `show_admin()` özü də busy pəncərəsi açır (UI-1) — o da hadisə dövrü
    # tələb edir.
    _drain_until(qt_app, lambda: opened != [])

    assert opened == [employee]
    assert application._login.cleared == 1
    assert application._login.errors == []


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_denied_face_login_shows_the_reason_and_clears_busy(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_login import FaceLoginOutcome

    application = _application(qt_app)
    application._context = object()
    application._login = _Login()  # type: ignore[assignment]

    _patch_controller(
        monkeypatch, outcome=FaceLoginOutcome(succeeded=False, message="Üzünüz uyğun gəlmədi.")
    )

    application._on_face_login_requested("aysel")
    _drain_until(qt_app, lambda: not application._face_login_task.is_running)

    assert application._login.errors == ["Üzünüz uyğun gəlmədi."]
    assert application._login.busy_history == [True, False]
    assert application._login.cleared == 0


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_unexpected_task_failure_is_logged_not_swallowed(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`authenticate()` özü istisna ATMIR, lakin son qoruyucu sınanır."""
    from src.presentation import app as app_module

    application = _application(qt_app)
    application._context = object()
    application._login = _Login()  # type: ignore[assignment]

    from src.presentation.controllers import face_login as face_login_module

    def _boom(self: Any, username: str) -> Any:
        raise RuntimeError("kamera əlçatmazdır")

    monkeypatch.setattr(face_login_module.FaceLoginController, "authenticate", _boom)
    logged: list[str] = []
    monkeypatch.setattr(app_module._log, "error", lambda key, **_: logged.append(key))

    application._on_face_login_requested("aysel")
    _drain_until(qt_app, lambda: bool(logged))

    assert logged == ["FACE_LOGIN_TASK_FAILED"]
    assert application._login.errors == ["Üz təsdiqi aparıla bilmədi. Şifrənizlə daxil olun."]
    assert application._login.busy_history == [True, False]


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_the_busy_indicator_stays_on_until_show_admin_calls_on_ready(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`set_busy(False)` ARTIQ `show_admin()`-dan DƏRHAL SONRA gəlmir (PERF-6 Mərhələ 2).

    `show_admin()` fon sapına köçəndən (Mərhələ 2) sonra DƏRHAL qayıdır —
    əvvəlki `try/finally` bunu artıq DÜZGÜN idarə edə bilməz, çünki o, fon
    işi HƏLƏ BAŞLAMAMIŞ işə düşərdi: göstərici dərhal sönər, istifadəçi isə
    hələ gözləyərdi ("panel açılır" əvəzinə donmuş, amma busy-siz pəncərə).
    Ona görə `_on_face_login_succeeded` göstəricini `on_ready` callback-i
    ilə söndürür (bax `app.py::show_admin` başlığı).

    Bu test `show_admin()`-in ARXASINDAKI ağır işi (`_fetch_admin_shell_
    preload`, DB-yə gedir) `threading.Event` ilə bloklayır və sübut edir:
    preload BİTMƏMİŞ göstərici HƏLƏ AKTİV qalır, YALNIZ `on_ready` işə
    düşəndən SONRA sönür. `_build_admin_shell` (real Qt qurulması, DB-siz
    ölçülə bilməz) yüngül sahtə ilə əvəzlənir — ölçülən şey QURULUŞUN ÖZÜ
    yox, SIRADIR.
    """
    from src.presentation import app as app_module
    from src.presentation.controllers.face_login import FaceLoginOutcome

    application = _application(qt_app)
    application._context = object()
    application._login = _Login()  # type: ignore[assignment]

    employee = object()
    _patch_controller(
        monkeypatch,
        outcome=FaceLoginOutcome(succeeded=True, employee=employee),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(application, "_show_face_setup_if_required", lambda *a, **k: False)
    monkeypatch.setattr(application, "_build_admin_shell", lambda *a, **k: None)

    block = threading.Event()
    started = threading.Event()

    def _blocked_preload(context: Any, emp: Any, *, now: Any) -> Any:
        started.set()
        block.wait(timeout=5.0)
        return object()

    monkeypatch.setattr(app_module, "_fetch_admin_shell_preload", _blocked_preload)

    application._on_face_login_requested("aysel")
    _drain_until(qt_app, started.is_set)

    # PRELOAD HƏLƏ BLOKLANIB — göstərici HƏLƏ AKTİV qalmalıdır. Köhnə
    # (sinxron) `finally` bura çatana qədər ARTIQ `False` yazmış olardı.
    assert application._login.busy_history[-1] is True, (
        "`set_busy(False)` `show_admin()`-in fon işi bitmədən çağırılıb — "
        "bu, köhnə sinxron `finally` davranışının geri qayıtması deməkdir"
    )
    assert application._admin_shell_task is not None
    assert application._admin_shell_task.is_running

    block.set()
    _drain_until(qt_app, lambda: not application._admin_shell_task.is_running)

    # [0] True  — `_on_face_login_requested`, giriş cəhdinin ÖZ busy-si (UX-1,
    #             bu dəyişiklikdən ƏVVƏL də var idi, `show_admin`-ə aid deyil)
    # [1] False — üz-doğrulama fon işi (`FaceLoginController.authenticate`) bitdi
    # [2] True  — `_on_face_login_succeeded`, `show_admin` üçün İKİNCİ busy (UI-1)
    # [3] False — `on_ready` callback-i, yəni panel HƏQİQƏTƏN hazırdır
    assert application._login.busy_history == [True, False, True, False]
