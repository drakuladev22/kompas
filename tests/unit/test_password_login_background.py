"""Şifrə ilə giriş FON SAPINDA icra olunur (PERF-6, `app.py::_authenticate`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
`_authenticate()` ƏVVƏL `AuthController.authenticate()`-i GUI sapında sinxron
çağırırdı — ölçülən 1894 ms donma (bax `app.py::_authenticate` başlığı).
Düzəliş `run_job(..., executor=self._executor)` ilə işi fon sapına köçürdü;
`test_login_and_startup_recovery.py` və `test_busy_feedback.py`-dəki testlər
bunu `InlineExecutor` ilə yoxlayır (sinxron, hadisə dövrəsi olmadan), lakin
`InlineExecutor` işi ÇAĞIRAN sapda dərhal icra etdiyi üçün həmin testlər
`_authenticate`-in ÖZÜNÜN fon sapına köçüb-köçmədiyini SÜBUT ETMİR — sadəcə
mövcud əvvəlki davranışı (sinxron çağırış) da eyni cür keçərdi.

Bu fayl `test_face_login_background.py`-dəki EYNİ üsulu işlədir: DEFOLT
icraçı (`QtPoolExecutor`, real `QThreadPool`) ilə `_authenticate()`
çağırılır, `authenticate()` isə `threading.Event` ilə BLOKLANIR. Əgər kimsə
gələcəkdə `executor=self._executor` sətrini silib çağırışı yenidən sinxron
etsə, bu test ƏBƏDİ QALAR (5 saniyə taymautla uğursuz olar) — çünki
`_authenticate("...", "...")` çağırışının ÖZÜ `block.wait()`-də dayanardı.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _drain_until(qt_app: Any, predicate: Any, *, seconds: float = 5.0) -> None:
    """`predicate()` `True` olana qədər hadisə dövrəsini işlədir.

    Bax `test_face_login_background.py::_drain_until` — eyni əsaslandırma:
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


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_password_login_does_not_block_the_gui_thread(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`_authenticate()` NƏTİCƏ GƏLMƏMİŞ qayıtmalıdır (iş fon sapındadır).

    Sinxron versiyada bu metod `authenticate()` bitənə qədər QAYITMIRDI —
    çağırışın ÖZÜ 5 saniyəlik `block.wait()`-i gözlərdi və test taymautla
    uğursuz olardı. Fon sapına köçürüldükdən sonra çağırış DƏRHAL qayıdır,
    `_login_task.is_running` isə iş bitənə qədər `True` qalır.
    """

    class _Outcome:
        succeeded = False
        message = "test"

    application = _application(qt_app)
    application._login = _Login()  # type: ignore[assignment]

    block = threading.Event()

    class _Auth:
        def authenticate(self, username: object, password: str) -> Any:
            block.wait(timeout=5.0)
            return _Outcome()

    application._auth = _Auth()  # type: ignore[assignment]

    started_at = time.monotonic()
    application._authenticate("m.bayramov", "Uzun-Sifre-123")
    elapsed = time.monotonic() - started_at

    # ÇAĞIRIŞ ÖZÜ dərhal qayıtdı — sinxron olsaydı bura `block.set()`
    # çağırılana qədər (5 saniyə) çatmazdı.
    assert elapsed < 1.0, "`_authenticate` GUI sapını blokladı — PERF-6 geri qayıtdı"
    assert application._login_task is not None
    assert application._login_task.is_running
    assert application._login.busy_history == [True]

    block.set()
    _drain_until(qt_app, lambda: not application._login_task.is_running)
