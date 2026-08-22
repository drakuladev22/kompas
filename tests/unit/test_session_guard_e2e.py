"""`SessionGuard` — REAL `QTimer`/`QApplication.eventFilter` e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`test_session_touch_guard.py` `app.py::_touch_session`/`_start_session_guard`-ı
(YƏNİ `KompasApplication`-ın `SessionGuard`-ı NECƏ İŞLƏTDİYİNİ) ölçür.
`SessionGuard` sinfinin ÖZÜ — `eventFilter`, hərəkətsizlik/mütləq taymerlər,
`touch()` dırnaqlaması — `tests/` daxilində HEÇ YERDƏ birbaşa qurulmur
(`grep -rn "SessionGuard(" tests/` bu fayldan ƏVVƏL sıfır nəticə verirdi).

──────────────────────────────────────────────────────────────────────────────
NİYƏ TAYMER İNTERVALLARI QISALDILIR
──────────────────────────────────────────────────────────────────────────────
`__init__` `max(1, minutes) * 60_000` və `max(1, hours) * 3_600_000` işlədir —
minimum REAL interval 1 dəqiqədir. Real 60 saniyə gözləmək test dəstini
ləngidərdi (CLAUDE.md: tam dəst onsuz da ~50 dəqiqədir). Ona görə `start()`
çağrılmazdan ƏVVƏL REAL `QTimer` obyektlərinin `setInterval(...)`-i birbaşa
qısaldılır — taymer HƏLƏ DƏ REAL Qt mexanizmidir (saxta saat DEYİL), yalnız
gözləmə vaxtı sıxılır. `touch_throttle_seconds` isə birbaşa parametrdən
gəldiyi üçün heç bir hiylə lazım deyil.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _guard(
    *,
    inactivity_minutes: int | None = 1,
    absolute_hours: int = 1,
    touch=None,
    touch_throttle_seconds: int | None = None,
):  # type: ignore[no-untyped-def]
    from src.presentation.controllers.session_guard import SessionGuard

    return SessionGuard(
        inactivity_minutes=inactivity_minutes,
        absolute_hours=absolute_hours,
        touch=touch,
        touch_throttle_seconds=touch_throttle_seconds,
    )


# --------------------------------------------------------------------------- #
# 1. `eventFilter` — REAL hadisə növləri fəaliyyət sayılır, digərləri yox
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_real_mouse_move_event_is_observed_as_activity(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent, Qt

    guard = _guard()
    calls: list[str] = []
    guard.notify_activity = lambda: calls.append("activity")  # type: ignore[method-assign]

    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(1, 1),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    consumed = guard.eventFilter(qt_app, event)

    assert calls == ["activity"]
    assert consumed is False, "eventFilter siçanı BLOKLAMAMALIDIR (bax şərh)"


@requires_qt
def test_a_resize_event_is_not_activity(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Yalnız `_ACTIVITY_EVENT_TYPES`-dəki dörd növ sayılır — hər hadisə YOX."""
    from PySide6.QtCore import QEvent

    guard = _guard()
    calls: list[str] = []
    guard.notify_activity = lambda: calls.append("activity")  # type: ignore[method-assign]

    guard.eventFilter(qt_app, QEvent(QEvent.Type.Resize))

    assert calls == []


# --------------------------------------------------------------------------- #
# 2. Hərəkətsizlik taymeri — REAL vaxtında bitir, DOĞRU səbəblə
# --------------------------------------------------------------------------- #


@requires_qt
def test_inactivity_expiry_fires_with_the_inactivity_reason(qtbot) -> None:  # type: ignore[no-untyped-def]
    guard = _guard(inactivity_minutes=1, absolute_hours=1)
    guard._inactivity_timer.setInterval(50)
    guard._absolute_timer.setInterval(5_000)  # mütləq hədd BU testdə tetiklənməməlidir

    with qtbot.waitSignal(guard.expired, timeout=1000) as blocker:
        guard.start()

    assert "Hərəkətsizlik" in blocker.args[0]
    guard.stop()


@requires_qt
def test_activity_resets_the_inactivity_timer_and_postpones_expiry(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Real fəaliyyət taymeri sıfırlayır — «yarıya qədər» gözləyib fəaliyyət
    göstərmək müddəti UZADIR, bitirmır."""
    guard = _guard(inactivity_minutes=1, absolute_hours=1)
    guard._inactivity_timer.setInterval(150)
    guard._absolute_timer.setInterval(10_000)
    fired: list[str] = []
    guard.expired.connect(fired.append)

    guard.start()
    qtbot.wait(90)  # taymerin yarısı qədər gözlə
    guard.notify_activity()  # REAL fəaliyyət — sayğac sıfırlanmalıdır
    qtbot.wait(90)  # ilk taymerdən keçən CƏMİ VAXT artıq 180ms-dir, LAKİN sıfırlanıb

    assert fired == [], "Fəaliyyətdən sonra taymer sıfırlanmalı idi, bitməməli idi"
    guard.stop()


@requires_qt
def test_absolute_expiry_fires_even_with_continuous_activity(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Mütləq hədd FƏALİYYƏTDƏN ASILI DEYİL — kim nə qədər klikləsə də bitir."""
    guard = _guard(inactivity_minutes=1, absolute_hours=1)
    guard._inactivity_timer.setInterval(10_000)  # bu testdə tetiklənməməlidir
    guard._absolute_timer.setInterval(100)

    with qtbot.waitSignal(guard.expired, timeout=1000) as blocker:
        guard.start()
        # Davamlı fəaliyyət mütləq həddi ERTƏLƏMİR.
        guard.notify_activity()
        qtbot.wait(30)
        guard.notify_activity()
        qtbot.wait(30)

    assert "mütləq müddəti" in blocker.args[0]
    guard.stop()


# --------------------------------------------------------------------------- #
# 3. `touch()` dırnaqlaması — server sessiyasını UZADIR, hər hadisədə YOX
# --------------------------------------------------------------------------- #


@requires_qt
def test_touch_fires_once_then_is_throttled_until_the_cooldown_ends(qtbot) -> None:  # type: ignore[no-untyped-def]
    calls: list[int] = []
    guard = _guard(
        inactivity_minutes=1,
        absolute_hours=1,
        touch=lambda: calls.append(1),
        touch_throttle_seconds=1,
    )
    guard.start()

    guard.notify_activity()
    guard.notify_activity()
    guard.notify_activity()

    assert calls == [1], "Dırnaqlama pəncərəsi bitmədən `touch()` TƏKRAR ÇAĞIRILMAMALIDIR"

    qtbot.wait(1100)  # 1 saniyəlik soyuma pəncərəsi bitsin
    guard.notify_activity()

    assert calls == [1, 1]
    guard.stop()


@requires_qt
def test_a_failing_touch_callback_does_not_break_the_local_gate(qtbot) -> None:  # type: ignore[no-untyped-def]
    """`touch()` ATSA belə yerli qapı (hərəkətsizlik taymeri) İŞLƏMƏYƏ davam edir."""

    def _failing_touch() -> None:
        raise RuntimeError("server əlçatmazdır")

    guard = _guard(
        inactivity_minutes=1, absolute_hours=1, touch=_failing_touch, touch_throttle_seconds=1
    )
    guard._inactivity_timer.setInterval(80)
    guard._absolute_timer.setInterval(10_000)

    with qtbot.waitSignal(guard.expired, timeout=1000):
        guard.start()
        guard.notify_activity()  # `touch()` BURADA ATIR — ÇÖKMƏMƏLİDİR

    guard.stop()


# --------------------------------------------------------------------------- #
# 4. `stop()` — bütün taymerlər dayanır, gecikmiş siqnal GƏLMİR
# --------------------------------------------------------------------------- #


@requires_qt
def test_stopping_the_guard_prevents_a_pending_expiry_from_firing(qtbot) -> None:  # type: ignore[no-untyped-def]
    guard = _guard(inactivity_minutes=1, absolute_hours=1)
    guard._inactivity_timer.setInterval(60)
    guard._absolute_timer.setInterval(10_000)
    fired: list[str] = []
    guard.expired.connect(fired.append)

    guard.start()
    guard.stop()  # istifadəçi taymer bitmədən LOGOUT etdi
    qtbot.wait(150)  # köhnə taymer İNDİ bitəcəkdi — amma DAYANDIRILIB

    assert fired == []


# --------------------------------------------------------------------------- #
# 5. `inactivity_minutes=None` — CAMERA_DASHBOARD: yoxlanılmır
# --------------------------------------------------------------------------- #


@requires_qt
def test_none_inactivity_minutes_disables_the_local_inactivity_timer(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Operator ekrana baxır, klikləmir — hərəkətsizlik SAYILMIR (bax sinif başlığı)."""
    guard = _guard(inactivity_minutes=None, absolute_hours=1)
    guard._absolute_timer.setInterval(10_000)
    fired: list[str] = []
    guard.expired.connect(fired.append)

    guard.start()
    assert guard._inactivity_timer is None
    qtbot.wait(100)  # heç bir hərəkətsizlik taymeri işləmir, ÇÖKMƏMƏLİDİR
    guard.notify_activity()  # `touch`-a keçid ÇÖKMƏMƏLİDİR (`_touch_cooldown is None`)

    assert fired == []
    guard.stop()
