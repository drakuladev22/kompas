"""GUI fon-işçi naxışı — `presentation/background_task.py`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BURADA HEÇ BİR `sleep` YOXDUR
──────────────────────────────────────────────────────────────────────────────
Sap testinin klassik qüsuru «nəticə gəlsin deyə 0.2 saniyə gözlə» sətridir: o,
yüklü maşında təsadüfi qırılır və qeyri-sabit test heç bir testdən pisdir.
Burada iki üsul işlədilir:

    * `_ManualExecutor` — işi SAXLAYIR və testin özü onu istədiyi ANDA icra
      edir. Beləliklə «birinci cavab ikincidən GEC gəldi» ssenarisi vaxtdan
      asılı olmadan, tam determinstik qurulur;
    * `qtbot.waitSignal` — yalnız FAKTİKİ sap yolunu yoxlayan tək testdə,
      açıq taymautla (hadisə dövrü siqnal gələn kimi qayıdır, gözləmir).

`QT_QPA_PLATFORM=offscreen` altında hər ikisi asmadan işləyir: sinxron
rejimdə ümumiyyətlə sap yaranmır, hovuz testində isə iş bir sətirlikdir.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


class _ManualExecutor:
    """İşi SAXLAYAN icraçı — icra anını test özü seçir.

    `runs_inline` `True`-dur, çünki iş çağıran (test) sapında icra olunur və
    nəticə DİREKT bağlantı ilə çatır — yəni hadisə dövrü tələb olunmur.
    """

    def __init__(self) -> None:
        self.jobs: list[Any] = []

    @property
    def runs_inline(self) -> bool:
        return True

    def submit(self, job: Any) -> None:
        self.jobs.append(job)

    def deliver(self, index: int = 0) -> None:
        """Növbədəki işlərdən BİRİNİ icra edir (sıra testin öz seçimidir)."""
        self.jobs.pop(index)()


def _task(executor: Any = None, parent: Any = None) -> Any:
    from src.presentation.background_task import BackgroundTask

    return BackgroundTask(parent=parent, executor=executor, name="TEST")


# --------------------------------------------------------------------------- #
# Nəticə və səhv yolu
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_result_returns_through_a_signal(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Uğurlu iş `succeeded` ilə qayıdır, `finished` isə SONRA yayılır."""
    from src.presentation.background_task import InlineExecutor

    task = _task(InlineExecutor())
    events: list[str] = []
    results: list[Any] = []
    task.started.connect(lambda: events.append("started"))
    task.succeeded.connect(lambda value: (events.append("succeeded"), results.append(value)))
    task.finished.connect(lambda: events.append("finished"))

    task.run(lambda: {"ok": True})

    assert results == [{"ok": True}]
    assert events == ["started", "succeeded", "finished"]
    assert task.is_running is False


@requires_qt
def test_an_exception_inside_the_job_is_never_swallowed(qt_app) -> None:  # type: ignore[no-untyped-def]
    """İşçidəki istisna `failed` ilə OLDUĞU KİMİ qayıdır (sükut YOXDUR)."""
    from src.presentation.background_task import InlineExecutor

    task = _task(InlineExecutor())
    failures: list[BaseException] = []
    successes: list[Any] = []
    task.failed.connect(failures.append)
    task.succeeded.connect(successes.append)

    def _explode() -> Any:
        raise RuntimeError("1C serveri cavab vermir")

    task.run(_explode)

    assert successes == []
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert str(failures[0]) == "1C serveri cavab vermir"


@requires_qt
def test_the_busy_flag_is_set_before_the_job_runs(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`started` işdən ƏVVƏL yayılır — busy vəziyyəti nəticədən sonra qurulmaz."""
    executor = _ManualExecutor()
    task = _task(executor)
    seen: list[bool] = []
    task.started.connect(lambda: seen.append(task.is_running))

    task.run(lambda: "nəticə")

    assert seen == [True]
    assert task.is_running is True
    assert len(executor.jobs) == 1


# --------------------------------------------------------------------------- #
# Köhnəlmiş nəticə və ləğv
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_stale_result_is_dropped(qt_app) -> None:  # type: ignore[no-untyped-def]
    """İki ardıcıl buraxılış: BİRİNCİNİN gec gələn cavabı tətbiq OLUNMUR."""
    executor = _ManualExecutor()
    task = _task(executor)
    results: list[Any] = []
    finished: list[int] = []
    task.succeeded.connect(results.append)
    task.finished.connect(lambda: finished.append(1))

    task.run(lambda: "birinci")
    task.run(lambda: "ikinci")
    assert len(executor.jobs) == 2

    # Birinci iş İKİNCİDƏN SONRA bitir — cavabı köhnəlib.
    executor.deliver(0)
    assert results == []
    assert finished == []
    assert task.is_running is True

    executor.deliver(0)
    assert results == ["ikinci"]
    assert finished == [1]
    assert task.is_running is False


@requires_qt
def test_cancel_rejects_the_pending_result_without_killing_the_job(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ləğv icranı DAYANDIRMIR — nəticəni rədd edir (sap zorla öldürülmür)."""
    executor = _ManualExecutor()
    task = _task(executor)
    results: list[Any] = []
    failures: list[Any] = []
    finished: list[int] = []
    task.succeeded.connect(results.append)
    task.failed.connect(failures.append)
    task.finished.connect(lambda: finished.append(1))

    executed: list[str] = []
    task.run(lambda: executed.append("qaçdı") or "nəticə")
    task.cancel()

    assert task.is_running is False
    executor.deliver()

    # İş İCRA OLUNDU (sap kəsilmədi), lakin nəticə heç bir siqnala çevrilmədi.
    assert executed == ["qaçdı"]
    assert (results, failures, finished) == ([], [], [])


@requires_qt
def test_cancel_without_a_pending_job_is_harmless(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Boş ləğv (pəncərə heç bir test başlatmadan bağlanır) heç nə etmir."""
    task = _task(_ManualExecutor())
    task.cancel()
    assert task.is_running is False
    assert task.generation == 0


# --------------------------------------------------------------------------- #
# Widget ölümü
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_late_result_never_touches_a_destroyed_owner(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Valideyn məhv olub — gec gələn nəticə ÇÖKMƏ yaratmır.

    Widget FAKTİKİ olaraq məhv edilir, sadəcə gizlədilmir — yəni bu test
    Qt-nin "alıcı öləndə bağlantı qopur" zəmanətini yoxlayır, bizim əlavə bir
    yoxlamamızı yox.

    `deleteLater()`-dən sonra `sendPostedEvents(..., DeferredDelete)` AÇIQ
    çağırılır: adi `processEvents()` təxirə salınmış silinməni EMAL ETMİR
    (Qt onu yalnız hadisə dövrünün öz səviyyəsində icra edir), yəni onunla
    widget canlı qalar və test heç nə yoxlamamış olardı.
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QWidget

    owner = QWidget()
    executor = _ManualExecutor()
    task = _task(executor, parent=owner)
    results: list[Any] = []
    task.succeeded.connect(results.append)

    task.run(lambda: "gec gələn cavab")
    owner.deleteLater()
    qt_app.sendPostedEvents(owner, QEvent.Type.DeferredDelete)

    executor.deliver()  # çökməməlidir
    assert results == []


# --------------------------------------------------------------------------- #
# FAKTİKİ sap yolu — `QThreadPool`
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_pool_executor_runs_off_the_gui_thread_and_returns_to_it(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """İş BAŞQA sapda icra olunur, nəticə isə ƏSAS sapda çatdırılır.

    Bu, naxışın bütün mövcudluq səbəbidir: uzun əməliyyat hadisə dövründən
    kənarda qaçmalı, ekran yeniləməsi isə GUI sapında baş verməlidir (Qt
    widget-ləri sap-təhlükəsiz deyil).
    """
    from src.presentation.background_task import QtPoolExecutor

    task = _task(QtPoolExecutor())
    gui_thread = threading.get_ident()
    delivered: list[int] = []
    task.succeeded.connect(lambda _value: delivered.append(threading.get_ident()))

    with qtbot.waitSignal(task.succeeded, timeout=5000) as blocker:
        task.run(threading.get_ident)

    assert blocker.args[0] != gui_thread  # iş fon sapında qaçdı
    assert delivered == [gui_thread]  # nəticə əsas sapda tətbiq olundu
    assert task.is_running is False
