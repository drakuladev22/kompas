"""Ay oxları matris pəncərəsini FAKTİKİ olaraq sürüşdürür.

Bu qapının səbəbi nasazlığın FORMASIDIR: oxlar ekranda vardı, siqnal yayılırdı,
heç bir xəta çıxmırdı — sadəcə heç nə dəyişmirdi. Belə nasazlıq nə jurnala,
nə də istisna izinə düşür; yalnız davranış testi onu tutur.

Ölçdüyümüz şey ADDIMIN ÖZÜDÜR: sürüşmə pəncərənin uzunluğu qədər olmalıdır.
Sabit ədəd yazılsaydı, Root pəncərəni qısaldanda iki klik arasında görünməyən
günlər qalardı — bu isə "işləyir" görünən, amma məlumat gizlədən haldır.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers.shift_window import ShiftWindowController
from src.shared.exceptions import KompasOSError


class _Signal:
    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, value: int) -> None:
        for slot in list(self._slots):
            slot(value)


class _Screen:
    """`ShiftPlanningScreen`-in yalnız işlənən hissəsi."""

    def __init__(self) -> None:
        self.month_changed = _Signal()
        self.errors: list[tuple[str, str]] = []

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _Actor:
    """Kontroller aktordan yalnız `id`-ni işlədir (sessiya açarı)."""

    id = "11111111-1111-1111-1111-111111111111"


class _Context:
    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield object()


class _Binder:
    """Sahtə `ScreenDataBinder` — çağırışları qeyd edir."""

    #: Sinif səviyyəsində, çünki kontroller HƏR klikdə yenisini qurur.
    offsets: ClassVar[list[int]] = []
    populated: ClassVar[list[str]] = []
    window: int = 14
    populate_error: KompasOSError | None = None
    window_error: KompasOSError | None = None

    def __init__(self, context: Any, actor: Any) -> None:
        self._context = context

    def shift_window_days(self, session: Any) -> int:
        if _Binder.window_error is not None:
            raise _Binder.window_error
        return _Binder.window

    def set_shift_offset(self, day_offset: int) -> None:
        _Binder.offsets.append(day_offset)

    def populate(self, key: str, screen: Any) -> None:
        if _Binder.populate_error is not None:
            raise _Binder.populate_error
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _binder(monkeypatch: pytest.MonkeyPatch) -> None:
    _Binder.offsets = []
    _Binder.populated = []
    _Binder.window = 14
    _Binder.populate_error = None
    _Binder.window_error = None
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)


def _attached() -> tuple[ShiftWindowController, _Screen]:
    screen = _Screen()
    controller = ShiftWindowController(_Context(), _Actor())  # type: ignore[arg-type]
    controller.attach(screen)  # type: ignore[arg-type]
    return controller, screen


def test_forward_arrow_shifts_the_window_by_its_own_length() -> None:
    _controller, screen = _attached()
    screen.month_changed.emit(1)
    assert _Binder.offsets == [14]
    assert _Binder.populated == ["shift_planning"]


def test_offset_accumulates_across_clicks() -> None:
    """İki dəfə irəli, bir dəfə geri — sürüşmə TOPLANIR, sıfırlanmır."""
    _controller, screen = _attached()
    screen.month_changed.emit(1)
    screen.month_changed.emit(1)
    screen.month_changed.emit(-1)
    assert _Binder.offsets == [14, 28, 14]


def test_zero_window_does_nothing() -> None:
    """Pəncərə 0-dırsa matris yenilənmir — sıfır addım oxu mənasız edərdi."""
    _Binder.window = 0
    _controller, screen = _attached()
    screen.month_changed.emit(1)
    assert _Binder.offsets == []
    assert _Binder.populated == []


def test_unreadable_window_length_does_not_move_the_matrix() -> None:
    _Binder.window_error = KompasOSError("pəncərə oxunmadı")
    _controller, screen = _attached()
    screen.month_changed.emit(1)
    assert _Binder.offsets == []
    assert screen.errors == []


def test_failed_reload_is_reported_to_the_user() -> None:
    """Yükləmə uğursuzdursa istifadəçi XƏBƏR TUTUR — ox sükutla ölmür."""
    _Binder.populate_error = KompasOSError("matris oxunmadı")
    _controller, screen = _attached()
    screen.month_changed.emit(1)
    assert len(screen.errors) == 1
    assert screen.errors[0][0] == "Növbə matrisi oxuna bilmədi"
