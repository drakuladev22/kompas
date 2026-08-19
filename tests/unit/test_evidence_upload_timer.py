"""Sübut yükləmə növbəsinin dövri boşaldılması — D3-01 (dövrə 3 audit).

──────────────────────────────────────────────────────────────────────────────
HANSI QÜSURU TUTUR
──────────────────────────────────────────────────────────────────────────────
`_drain_upload_queue()` ƏVVƏL GUI sapında SİNXRON `context.run_evidence_
uploads()` çağırırdı — `QTimer` hər 10-120 saniyədən bir (`EVIDENCE_UPLOAD_
POLL_INTERVAL_SECONDS`) növbədəki HƏR şəkli (partiya 20-yə qədər) Google
Drive-a sinxron yükləyirdi. UI-02 (`_touch_session`) DB gediş-gəlişi (~200 ms)
idi; bu isə ŞƏBƏKƏ ŞƏKİL YÜKLƏMƏSİdir (saniyələr) və HƏR admin sessiyasında
davamlı işləyir.

Bu fayl İKİ ŞEYİ ölçür:

    1. yükləmə İŞİ GUI sapından KƏNARDA icra olunur (`test_background_job_
       funnel.py`-dəki EYNİ üsul: işin icra sapını qeyd edib GUI sapı ilə
       müqayisə edir);
    2. əvvəlki dövrə HƏLƏ QAÇIRSA, YENİ dövrə BAŞLADILMIR — eyni anda İKİ
       yükləmə dövrəsi qarşısı alınır (`_touch_task`-dakı EYNİ nəsil-token
       naxışı, `background_task.py::BackgroundTask.run`).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _application(qt_app: Any) -> Any:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    return KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT, context=None)


def _drain_until(qt_app: Any, predicate: Any, *, seconds: float = 5.0) -> None:
    """`predicate()` `True` olana qədər hadisə dövrəsini işlədir.

    Fon işinin nəticəsi Qt siqnalı ilə əsas sapa POSTLANIR — hadisə dövrəsi
    işləmədən o siqnal heç vaxt çatmaz (eyni naxış `test_session_touch_
    guard.py::_drain_until`-dədir).
    """
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()


class _FakeContext:
    """`ApplicationContext`-in minimal təkrarı — YALNIZ `run_evidence_uploads`."""

    def __init__(self, *, uploaded: int = 0, block: threading.Event | None = None) -> None:
        self.calls = 0
        self.threads: list[int] = []
        self._uploaded = uploaded
        self._block = block

    def run_evidence_uploads(self) -> int:
        self.calls += 1
        self.threads.append(threading.get_ident())
        if self._block is not None:
            self._block.wait(timeout=5.0)
        return self._uploaded


@requires_qt
def test_drain_upload_queue_runs_off_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Yükləmə işi GUI sapından KƏNARDA icra olunur — panel DONMUR."""
    application = _application(qt_app)
    context = _FakeContext(uploaded=3)
    application._context = context  # type: ignore[assignment]

    gui_thread = threading.get_ident()
    application._drain_upload_queue()
    _drain_until(qt_app, lambda: not application._upload_task.is_running)

    assert context.calls == 1
    assert context.threads[0] != gui_thread


@requires_qt
def test_drain_upload_queue_logs_the_uploaded_count(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Uğurlu dövrənin nəticəsi (yüklənən say) ƏSAS SAPDA qeydə alınır."""
    from src.presentation import app as app_module

    application = _application(qt_app)
    application._context = _FakeContext(uploaded=5)  # type: ignore[assignment]
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        app_module._log, "info", lambda key, **kw: logged.append((key, kw.get("extra", {})))
    )

    application._drain_upload_queue()
    _drain_until(qt_app, lambda: not application._upload_task.is_running)

    assert ("EVIDENCE_UPLOADED", {"count": 5}) in logged


@requires_qt
def test_drain_upload_queue_does_not_start_a_second_cycle_while_one_is_running(
    qt_app,
) -> None:  # type: ignore[no-untyped-def]
    """Əvvəlki dövrə HƏLƏ QAÇIRSA, taymerin NÖVBƏTİ tetiklənməsi YENİ dövrə açmır.

    `block` birinci dövrəni QƏSDƏN gecikdirir ki, ikinci çağırışın onun
    ÜSTÜNDƏN keçmədiyi (üst-üstə düşmə) sınansın.
    """
    block = threading.Event()
    application = _application(qt_app)
    context = _FakeContext(block=block)
    application._context = context  # type: ignore[assignment]

    application._drain_upload_queue()  # birinci dövrə başlayır, `block`-da gözləyir
    # `BackgroundTask.run()` `is_running`-i SİNXRON olaraq dərhal `True` edir
    # (bax `background_task.py::run`) — hadisə dövrəsi gözləmədən yoxlanıla bilər.
    assert application._upload_task is not None
    assert application._upload_task.is_running

    application._drain_upload_queue()  # İKİNCİ çağırış — YENİ dövrə AÇILMAMALIDIR

    block.set()  # birinci dövrəni buraxır
    _drain_until(qt_app, lambda: not application._upload_task.is_running)

    assert context.calls == 1, "YALNIZ BİR dövrə icra olunmalıdır"


@requires_qt
def test_drain_upload_queue_survives_an_unexpected_task_failure(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`job()`-un ÖZÜ çöksə belə (nəzəri hal), taymer nasazlığı UDULUR — GUI çökmür."""
    from src.presentation import app as app_module

    class _BrokenContext:
        def run_evidence_uploads(self) -> int:
            raise RuntimeError("gözlənilməz nasazlıq")

    application = _application(qt_app)
    application._context = _BrokenContext()  # type: ignore[assignment]
    logged: list[str] = []
    monkeypatch.setattr(app_module._log, "error", lambda key, **_: logged.append(key))

    application._drain_upload_queue()  # istisna ATMAMALIDIR
    _drain_until(qt_app, lambda: bool(logged))

    assert logged == ["EVIDENCE_UPLOAD_TASK_FAILED"]
