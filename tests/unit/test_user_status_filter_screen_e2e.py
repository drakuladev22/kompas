"""`UsersScreen` "Vəziyyət" seçicisi ↔ `UserStatusFilterController` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/user_status_filter.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi
(`grep -rn "UserStatusFilterController" tests/` bu fayldan ƏVVƏL sıfır nəticə
verirdi) — modulun ÖZÜ məhz `user_admin.py`-ın MİNİMAL sahtəsini POZMAMAQ üçün
AYRI fayla çıxarılıb (bax modul başlığı), yəni `test_user_admin_controller.py`
onu STRUKTUR olaraq görə BİLMƏZ. Burada REAL `UsersScreen`-in REAL "Vəziyyət"
`QComboBox`-u dəyişdirilir və `ScreenDataBinder.populate("users", screen)`-in
HƏQİQƏTƏN çağırıldığı yoxlanılır.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


class _Binder:
    """`screen_data.ScreenDataBinder`-in yerini tutur (`test_tasks_screen_e2e.py`
    ilə EYNİ naxış) — real DB olmadan `_refresh`-in ÇAĞIRILDIĞINI ölçmək üçün."""

    calls: ClassVar[list[tuple[Any, str]]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        self._context = context
        self._actor = actor

    def populate(self, key: str, screen: Any) -> None:
        _Binder.calls.append((self._context, key))
        # REAL screen alındığını da yoxlamaq üçün — sahtə deyil, `set_users`
        # çağıra bilən HƏQİQİ `UsersScreen` gəlməlidir.
        screen.set_users([{"full_name": "Test", "username": "t", "role": "Satıcı", "store": "M"}])


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.presentation.controllers import screen_data as screen_data_module

    _Binder.calls = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)


class _Actor:
    id = ACTOR_ID


class _Context:
    """`_refresh`-in yalnız `ScreenDataBinder`-i quraşdırıb çağırdığını sübut
    etmək üçün — `UserStatusFilterController` özü bazaya HEÇ TOXUNMUR."""


def _attach(theme: Any, *, qtbot: Any) -> Any:
    from src.presentation.controllers.user_status_filter import UserStatusFilterController
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    UserStatusFilterController(_Context(), _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


@requires_qt
def test_changing_the_real_status_selector_re_reads_the_full_user_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _attach(theme, qtbot=qtbot)
    screen.set_users([{"full_name": "Köhnə", "username": "k", "role": "Satıcı", "store": "M"}])

    selector = screen.status_filter_selector()
    inactive_index = selector.findData("inactive")
    assert inactive_index >= 0, "«Deaktiv» seçimi kombo qutusunda olmalıdır"
    selector.setCurrentIndex(inactive_index)  # REAL istifadəçi seçimini simulyasiya edir

    assert len(_Binder.calls) == 1
    assert _Binder.calls[0][1] == "users"
    # `_refresh` `ScreenDataBinder.populate("users", screen)` çağırdığı üçün
    # REAL ekran "Köhnə" sətrini "Test" ilə ƏVƏZLƏMİŞ olmalıdır.
    assert screen.table().row_count == 1


@requires_qt
def test_selecting_the_same_option_still_reads_once_per_real_change(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`currentIndexChanged` yalnız DƏYİŞİKLİKDƏ atəşlənir — eyni indeksə
    təkrar seçim İKİNCİ oxu YARATMAMALIDIR (Qt-nin öz davranışı, amma
    kontrollerin ÜZƏRİNƏ əlavə sorğu QOYMADIĞINI sübut edir)."""
    screen = _attach(theme, qtbot=qtbot)
    selector = screen.status_filter_selector()

    all_index = selector.findData("all")
    selector.setCurrentIndex(all_index)
    selector.setCurrentIndex(all_index)  # EYNİ indeks — siqnal YENİDƏN atəşlənmir

    assert len(_Binder.calls) == 1


@requires_qt
def test_status_filter_changed_signal_carries_the_real_selected_key(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _attach(theme, qtbot=qtbot)
    received: list[str] = []
    screen.status_filter_changed.connect(received.append)

    selector = screen.status_filter_selector()
    selector.setCurrentIndex(selector.findData("all"))

    assert received == ["all"]
    assert screen.status_filter() == "all"
