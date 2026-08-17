"""Başlıq zolağındakı canlı saat (TIME-1 Faza 2.3).

Qapının səbəbi: saat qüsurları GÖZLƏ görünür, testlə yox. Yanlış mənbədən
oxusa ekranda yenə də düzgün görünən bir rəqəm olacaq — sadəcə o rəqəm
Windows saatı olacaq. Ona görə burada mənbənin KİM olduğu ölçülür, formatın
gözəlliyi yox.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from src.domain.value_objects.time_integrity import TimeIntegrityStatus, TimeTrustLevel
from src.presentation.widgets.live_clock import APPROXIMATE_MARK, LiveClock
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

#: UTC 09:00 → Bakı 13:00 (UTC+4, yay saatı yoxdur — `clock.py::BAKU_UTC_OFFSET`).
MOMENT: Final = datetime(2026, 8, 17, 9, 0, 0, tzinfo=UTC)


class _StubClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


def _status(level: TimeTrustLevel) -> TimeIntegrityStatus:
    return TimeIntegrityStatus(level=level, anchor_age_seconds=1.0, local_clock_offset_seconds=0.0)


@requires_qt
def test_the_widget_is_silent_until_a_source_is_attached(qtbot: object) -> None:
    """Mənbəsiz saat BOŞDUR və taymeri işləmir.

    Maket/önizməmə yolu saatsız qurulur; hər saniyə tıqqıldayan taymer orada
    yalnız səs-küy yaradardı. Boş qalması həm də doğrudur: yanlış saat
    göstərməkdənsə heç nə göstərmək yaxşıdır.
    """
    clock = LiveClock()
    assert clock.text == ""
    assert not clock.is_running


@requires_qt
def test_the_time_comes_from_the_clock_port_in_baku_time(qtbot: object) -> None:
    """UTC saxlanılır, Bakı vaxtı GÖSTƏRİLİR (`clock.py` qaydası)."""
    widget = LiveClock()
    widget.set_source(_StubClock(MOMENT))

    assert widget.text == "13:00:00"
    assert widget.is_running
    widget.stop()


@requires_qt
def test_the_display_follows_the_port_not_the_system_clock(qtbot: object) -> None:
    """Port dəyəri dəyişəndə mətn dəyişir — mənbə HƏQİQƏTƏN portdur."""
    source = _StubClock(MOMENT)
    widget = LiveClock()
    widget.set_source(source)

    source.moment = MOMENT + timedelta(hours=1, seconds=5)
    widget.refresh()

    assert widget.text == "14:00:05"
    widget.stop()


@requires_qt
def test_an_approximate_time_is_marked(qtbot: object) -> None:
    """Təxmini vaxt işarə ilə göstərilir — istifadəçi fərqi bilməlidir."""
    widget = LiveClock()
    widget.set_source(_StubClock(MOMENT), status=lambda: _status(TimeTrustLevel.UNTRUSTED))

    assert widget.text.startswith(APPROXIMATE_MARK)
    widget.stop()


@requires_qt
def test_a_verified_time_carries_no_mark(qtbot: object) -> None:
    widget = LiveClock()
    widget.set_source(_StubClock(MOMENT), status=lambda: _status(TimeTrustLevel.SERVER_VERIFIED))

    assert not widget.text.startswith(APPROXIMATE_MARK)
    assert widget.text == "13:00:00"
    widget.stop()


@requires_qt
def test_a_broken_source_clears_the_text_instead_of_freezing_it(qtbot: object) -> None:
    """Donmuş rəqəm işləyən saat kimi oxunur — bu, yanlış məlumatdır."""

    class _BrokenClock:
        def now(self) -> datetime:
            raise RuntimeError("vaxt mənbəyi çökdü")

    widget = LiveClock()
    widget.set_source(_StubClock(MOMENT))
    assert widget.text == "13:00:00"

    widget.set_source(_BrokenClock())  # type: ignore[arg-type]

    assert widget.text == ""
    widget.stop()


@requires_qt
def test_a_broken_status_provider_does_not_break_the_clock(qtbot: object) -> None:
    """Səviyyə oxuna bilmirsə saat YENƏ DƏ göstərilir — işarəsiz."""

    def _explode() -> TimeIntegrityStatus:
        raise RuntimeError("status oxunmadı")

    widget = LiveClock()
    widget.set_source(_StubClock(MOMENT), status=_explode)

    assert widget.text == "13:00:00"
    widget.stop()
