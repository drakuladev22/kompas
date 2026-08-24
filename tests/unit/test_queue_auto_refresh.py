"""DEEP-GAP OP-5 — təsdiq növbəsi HƏQİQƏTƏN canlıdır.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
Ekranın alt-başlığı «Canlı · 2 san əvvəl yeniləndi» yazırdı, halbuki heç bir
taymer yox idi: siyahı YALNIZ operator özü təsdiq/rədd edəndə yenilənirdi.
Mətn sonradan dürüstləşdirildi, LAKİN dürüst mətn boşluğu ÖRTDÜ, aradan
qaldırmadı — operator ekrana baxıb «yeni sorğu yoxdur» qərarı verirdi,
növbədə isə dəqiqələrlə gözləyən sorğu ola bilərdi.

Testlər İKİ müqaviləni kilidləyir:

1. dövrə siyahını fonda YENİDƏN OXUYUR;
2. toplu seçim (DEEP-GAP OP-7) varkən dövrə SAKİT KEÇİR — əks halda taymer
   operatorun işarələdiyi sətirləri o səbəb yazarkən silərdi.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


class _FakeBinder:
    def __init__(self) -> None:
        self.populated: list[str] = []
        self.failure: Exception | None = None

    def populate(self, key: str, screen: Any) -> None:
        if self.failure is not None:
            raise self.failure
        self.populated.append(key)


def _entry(kind: str = "Giriş Təsdiqi") -> Any:
    from src.presentation.screens.group_b import QueueEntry

    return QueueEntry(
        request_id=str(uuid.uuid4()),
        employee_name="Aygün Məmmədova",
        store_name="Mərkəz",
        position_name="Satıcı",
        kind=kind,
        timestamp_text="08:05",
        waiting_text="10 dəq",
    )


def _application(qt_app: Any) -> Any:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    return KompasApplication(qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None)


def _screen(qt_app: Any) -> Any:
    from src.presentation.screens.group_b import OperatorQueueScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    screen = OperatorQueueScreen(theme, assigned_stores=["Mərkəz"])
    screen.set_entries([_entry()])
    return screen


def _stop_timers(owner: Any) -> None:
    """Testdən SONRA taymer DAYANDIRILIR — sızma başqa testi qırır.

    Taymerin intervalı 30 saniyədir və tam dəst ~38 dəqiqə işləyir: widget
    canlı qalsa, tıqqıltı SONRAKI testin ortasında baş verir və (uğursuz
    yolda) jurnala sətir yazır. `test_logger.py` isə jurnalda MƏHZ BİR sətir
    gözləyir — yəni sızma orada qırmızı verir və səbəbi bu faylda olur.
    Qt widget-i `deleteLater()` ilə silinsə də taymer hadisə dövrəsi işləyənə
    qədər yaşayır, ona görə AÇIQ `stop()` çağırılır.
    """
    from PySide6.QtCore import QTimer

    for timer in owner.findChildren(QTimer):
        timer.stop()


def _tick(screen: Any) -> None:
    from PySide6.QtCore import QTimer

    timer = screen.findChild(QTimer)
    assert timer is not None, "avtomatik yenilənmə taymeri qurulmadı"
    timer.timeout.emit()


@requires_qt
def test_the_queue_is_refreshed_in_the_background(qt_app) -> None:  # type: ignore[no-untyped-def]
    application = _application(qt_app)
    binder = _FakeBinder()
    application._binder = binder
    screen = _screen(qt_app)

    application._start_queue_auto_refresh(screen)
    _tick(screen)

    assert binder.populated == ["live_queue"]
    _stop_timers(screen)


@requires_qt
def test_an_active_bulk_selection_postpones_the_refresh(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Operator sətirləri seçib səbəb yazarkən siyahı SİLİNMƏMƏLİDİR.

    `set_entries()` sətirləri sıfırdan qurur — seçim itərdi və operator
    işini yenidən başlamalı olardı.
    """
    from PySide6.QtWidgets import QCheckBox

    application = _application(qt_app)
    binder = _FakeBinder()
    application._binder = binder
    screen = _screen(qt_app)
    application._start_queue_auto_refresh(screen)

    screen.findChildren(QCheckBox)[0].setChecked(True)
    _tick(screen)

    assert binder.populated == [], "seçim varkən siyahı yenidən oxunmamalıdır"

    screen.clear_selection()
    _tick(screen)

    assert binder.populated == ["live_queue"], "seçim bitəndə dövrə davam etməlidir"
    _stop_timers(screen)


@requires_qt
def test_a_failing_refresh_keeps_the_timer_alive(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ötəri şəbəkə xətası dövrəni dayandırmır və ekranda modal açmır."""
    application = _application(qt_app)
    binder = _FakeBinder()
    binder.failure = RuntimeError("connection lost")
    application._binder = binder
    screen = _screen(qt_app)
    application._start_queue_auto_refresh(screen)

    _tick(screen)  # ÇÖKMƏMƏLİDİR

    binder.failure = None
    _tick(screen)

    assert binder.populated == ["live_queue"]
    _stop_timers(screen)
