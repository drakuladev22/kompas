"""Üz qeydiyyatı UI sapını BLOKLAMIR (SETUP-1 Faza 3).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Üz qeydiyyatı üç ağır addımdan ibarətdir: kamera kadrı çəkir, `dlib` hər kadr
üçün 128-ölçülü kodlaşdırma hesablayır, sonra baza yazısı gedir. Ölçmə deyil,
tərif: bu, saniyələrlə çəkən CPU işidir.

GUI sapında icra olunsaydı, Windows pəncərəni «Cavab vermir» kimi işarələyər,
operator isə proqramı bağlamağa çalışardı — məhz üz məlumatı yazılarkən.

Ölçülən şey İŞİN NƏTİCƏSİ deyil (onu `test_face_control.py` ölçür), məhz
İCRA YERİdir: iş GUI sapından KƏNARDA getməlidir və nəticə siqnalla geri
qayıtmalıdır.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


class _Screen:
    """`FaceEnrollmentScreen` əvəzinə minimal qəbuledici."""

    def __init__(self) -> None:
        self.results: list[dict[str, str]] = []
        self.frames: list[list[dict[str, str]]] = []
        self.busy: list[bool] = []

    def set_result(self, row: dict[str, str]) -> None:
        self.results.append(row)

    def set_frames(self, rows: list[dict[str, str]]) -> None:
        self.frames.append(rows)

    def set_busy(self, busy: bool) -> None:  # pragma: no cover - hamısı istifadə olunmur
        self.busy.append(busy)


def _drain(qt_app: Any, delivered: list[Any], *, seconds: float = 5.0) -> None:
    """Nəticə gələnə qədər hadisə dövrəsini işlədir.

    Fon işi TƏRİFƏ GÖRƏ dərhal bitmir və nəticə Qt siqnalı ilə əsas sapa
    POSTLANIR — hadisə dövrəsi işləmədən o siqnal heç vaxt çatmazdı. Sabit
    `sleep` əvəzinə şərtə görə gözləmək testi maşın sürətindən asılı etmir.
    """
    deadline = time.monotonic() + seconds
    while not delivered and time.monotonic() < deadline:
        qt_app.processEvents()


@requires_qt
def test_the_enrollment_work_leaves_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`dlib` kodlaşdırması GUI sapında qalsaydı pəncərə donardı."""
    from PySide6.QtCore import QThread

    from src.presentation.controllers.face_control import run_enrollment_job

    gui_thread = QThread.currentThread()
    seen: dict[str, Any] = {}

    def job() -> object:
        seen["thread"] = QThread.currentThread()
        return "hazırdır"

    delivered: list[object] = []
    task = run_enrollment_job(qt_app, job, on_success=delivered.append, on_failure=delivered.append)
    _drain(qt_app, delivered)

    assert task is not None
    assert seen["thread"] is not gui_thread, "üz emalı GUI sapında icra olundu"
    assert delivered == ["hazırdır"]


@requires_qt
def test_a_failure_is_delivered_not_swallowed(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Fon sapındakı istisna İTMƏMƏLİDİR — operator səbəbi görməlidir."""
    from src.presentation.controllers.face_control import run_enrollment_job

    def job() -> object:
        raise RuntimeError("kamera açılmadı")

    failures: list[object] = []
    task = run_enrollment_job(qt_app, job, on_success=lambda _: None, on_failure=failures.append)
    _drain(qt_app, failures)

    assert task is not None
    assert failures and "kamera açılmadı" in str(failures[0])
