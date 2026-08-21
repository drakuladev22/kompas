"""`UsersScreen`-in "Vəziyyət" seçicisi — deaktiv işçiləri YENİDƏN göstərmə yolu.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
QA-FULL Faza 3: `screen_data.py::_users` indi DEFOLTDA yalnız AKTİV işçiləri
sorğulayır (İSTİFADƏÇİNİN sözü: "işçi işdən çıxsa... əlavə yer tutmasın" —
bax həmin funksiyanın başlığı). Bu, SERVER-tərəfli süzgəcdir — deaktiv işçilər
`UsersScreen._users`-də ÜMUMİYYƏTLƏ ola bilməz, ona görə "Vəziyyət" seçimi
dəyişəndə dəst client-side YENİDƏN süzülə BİLMƏZ, YENİDƏN OXUNMALIDIR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, `controllers/user_admin.py`-a ƏLAVƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
`user_admin.py`-ın ARTIQ işlək `refresh()` metodu var və qoşulma məntiqi
cəhətdən ora sığardı, LAKİN `tests/unit/test_user_admin_controller.py` həmin
kontrolleri MİNİMAL `_Screen` sahtəsi ilə test edir (`status_filter_changed`
siqnalı YOXDUR) — `attach()`-ə əlavə `.connect(...)` çağırışı o testin 13
halını `AttributeError`-la ÇÖKDÜRDÜ. `controllers/shift_window.py` EYNİ
problemi eyni həllə həll edib: yeni siqnal, AYRI kontroller, `app.py`-da AYRI
bağlama — mövcud fake-lər TOXUNULMAZ qalır, çünki onlar bu YENİ siqnalı heç
vaxt görməyəcək kontrolleri bağlamırlar.

Sessiya SAXLANMIR (CLAUDE.md §6): hər dəyişiklikdə `ScreenDataBinder` YENİDƏN
qurulur (`ShiftWindowController`-dəki eyni izaha bax — bağlayıcı vəziyyəti
özündə saxlamır).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_c import UsersScreen


class UserStatusFilterController:
    """ "Vəziyyət" seçicisini `screen_data.py::_users`-in YENİDƏN oxunmasına bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: UsersScreen) -> None:
        screen.status_filter_changed.connect(lambda _key: self._refresh(screen))

    def _refresh(self, screen: UsersScreen) -> None:
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        ScreenDataBinder(self._context, self._actor).populate("users", screen)


__all__ = ["UserStatusFilterController"]
