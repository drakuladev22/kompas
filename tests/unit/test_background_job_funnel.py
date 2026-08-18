"""Ortaq fon-iş funnel-i — `run_job` (SETUP-1 Faza 3).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Üç ağır ekran (`backup_admin`, `report_export`, `bulk_operations`) eyni işi
görür: uzun əməliyyatı fon sapına buraxmaq, nəticəni GUI sapına qaytarmaq və
işçiyə istinad saxlamaq. Hər biri öz nüsxəsini yazsaydı, biri istinadı
saxlamağı unudar və nəticə SÜKUTLA itərdi — Python obyekti nəticə gəlməmiş
toplayanda `BackgroundTask` heç bir siqnal yaymır.

Ona görə funnel BİR yerdədir və burada ölçülür:

    1. iş GUI sapından KƏNARDA icra olunur;
    2. uğur/uğursuzluq HƏR İKİSİ çatdırılır (istisna udulmur);
    3. qaytarılan işçi çağırana verilir ki, o, istinadı saxlaya bilsin.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _drain(qt_app: Any, delivered: list[Any], *, seconds: float = 5.0) -> None:
    """Nəticə gələnə qədər hadisə dövrəsini işlədir.

    Nəticə Qt siqnalı ilə əsas sapa POSTLANIR — hadisə dövrəsi işləmədən o
    siqnal heç vaxt çatmazdı. Şərtə görə gözləmək testi maşın sürətindən
    asılı etmir (sabit `sleep` qeyri-sabit test yaradardı).
    """
    deadline = time.monotonic() + seconds
    while not delivered and time.monotonic() < deadline:
        qt_app.processEvents()


@requires_qt
def test_the_job_runs_outside_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Fon işi GUI sapında qalsaydı pəncərə «Cavab vermir» olardı."""
    from PySide6.QtCore import QThread

    from src.presentation.background_task import run_job

    gui_thread = QThread.currentThread()
    seen: dict[str, Any] = {}
    delivered: list[Any] = []

    def job() -> object:
        seen["thread"] = QThread.currentThread()
        return "bitdi"

    task = run_job(job, on_success=delivered.append, on_failure=delivered.append)
    _drain(qt_app, delivered)

    assert task is not None, "işçi qaytarılmır — çağıran istinadı saxlaya bilməz"
    assert seen["thread"] is not gui_thread
    assert delivered == ["bitdi"]


@requires_qt
def test_a_failure_reaches_the_caller(qt_app) -> None:  # type: ignore[no-untyped-def]
    """İstisna udulsaydı, istifadəçi «heç nə olmadı» görərdi."""
    from src.presentation.background_task import run_job

    def job() -> object:
        raise RuntimeError("pg_dump tapılmadı")

    failures: list[Any] = []
    # İSTİNAD SAXLANILIR — və bu, testin öz iddiasının sübutudur: istinadsız
    # buraxılışda Python işçini nəticə gəlməmiş toplayır və HEÇ BİR siqnal
    # yayılmır (funksiya məhz buna görə işçini qaytarır).
    task = run_job(job, on_success=lambda _: None, on_failure=failures.append)
    _drain(qt_app, failures)

    assert task is not None
    assert failures and "pg_dump tapılmadı" in str(failures[0])


def test_an_inline_executor_delivers_synchronously() -> None:
    """Testlər hadisə dövrəsi olmadan da nəticə ala bilməlidir.

    `InlineExecutor` sap testi ilə MƏNTİQ testini ayırır: kontroller
    testləri nəticəni dərhal alır, sap davranışı isə yuxarıdakı iki testdə
    ölçülür.
    """
    from src.presentation.background_task import InlineExecutor, run_job

    delivered: list[Any] = []
    run_job(
        lambda: "dərhal",
        on_success=delivered.append,
        on_failure=delivered.append,
        executor=InlineExecutor(),
    )

    assert delivered == ["dərhal"]
