"""«Məşğulam» vəziyyəti bloklamadan ƏVVƏL çəkilir — UX-1.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
Kontroller bloklayan işdən əvvəl `set_busy(True)` çağırırdı — yəni düymə
söndürülür və mətni «Yoxlanılır…» olur. Qt isə bu dəyişikliyi yalnız hadisə
dövrəsinə qayıdanda çəkir; bloklayan sorğu məhz həmin qayıdışdan ƏVVƏL
başlayırdı. Nəticədə istifadəçi düyməyə basır və ekranda saniyələrlə HEÇ NƏ
dəyişmir — bildirilən «button late reply» şikayətinin görünən hissəsi budur.

Test SIRA-nı yoxlayır: `flush_ui` bloklayan çağırışdan ƏVVƏL, `set_busy(True)`
-dən SONRA gəlməlidir. Sıra pozulsa qüsur geri qayıdar, halbuki bütün
çağırışlar hələ də mövcud olardı — ona görə ölçülən şey MÖVCUDLUQ deyil,
ARDICILLIQDIR.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


class _Screen:
    def __init__(self, trace: list[str]) -> None:
        self._trace = trace
        self.errors: list[str] = []

    def set_busy(self, busy: bool) -> None:
        self._trace.append(f"busy={busy}")

    def set_status(self, message: str) -> None:
        self._trace.append("status")

    def set_error(self, message: str) -> None:
        self.errors.append(message)


def test_the_connection_screen_repaints_before_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bağlantı sınağı 10 saniyəyə qədər bloklayır — vəziyyət əvvəl görünməlidir."""
    from src.presentation.controllers import connection_settings as module

    trace: list[str] = []
    screen = _Screen(trace)
    controller = module.ConnectionSettingsController.__new__(module.ConnectionSettingsController)

    monkeypatch.setattr(module, "flush_ui", lambda: trace.append("flush"))
    monkeypatch.setattr(
        module.ConnectionSettingsController,
        "_probe",
        lambda *_a, **_k: (trace.append("probe"), False)[1],
    )

    controller._on_submit(screen, _PAYLOAD)  # type: ignore[arg-type]

    assert trace.index("flush") < trace.index("probe")
    assert trace.index("busy=True") < trace.index("flush")


def test_the_login_path_repaints_before_authenticating(monkeypatch: pytest.MonkeyPatch) -> None:
    """Giriş yolu ən uzun bloklayandır (~1.7 s) — ona görə ən çox görünəndir."""
    from src.presentation import app as module

    trace: list[str] = []

    class _Login:
        def set_busy(self, busy: bool) -> None:
            trace.append(f"busy={busy}")

        def set_error(self, message: str) -> None:
            trace.append("error")

    class _Auth:
        def authenticate(self, username: object, password: str) -> Any:
            trace.append("authenticate")
            return type("Outcome", (), {"succeeded": False, "message": "x"})()

    monkeypatch.setattr(module, "flush_ui", lambda: trace.append("flush"))

    application = module.KompasApplication.__new__(module.KompasApplication)
    application._login = _Login()  # type: ignore[assignment]
    application._auth = _Auth()  # type: ignore[assignment]

    application._authenticate("m.bayramov", "Uzun-Sifre-123")

    assert trace.index("busy=True") < trace.index("flush") < trace.index("authenticate")


def test_flush_ui_is_a_no_op_without_a_qt_application(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qt-siz vahid testdə kontroller çağırıla bilməlidir.

    İstisna atsaydı, bütün kontroller testləri `QApplication` qurmağa məcbur
    olardı — halbuki onların yoxladığı şey Qt-dən asılı DEYİL.
    """
    from src.presentation.controllers import ui_feedback

    monkeypatch.setattr(
        "PySide6.QtWidgets.QApplication.instance", staticmethod(lambda: None), raising=False
    )

    ui_feedback.flush_ui()  # istisna atmamalıdır


_PAYLOAD: dict[str, Any] = {
    "host": "db.example.com",
    "port": "5432",
    "database": "postgres",
    "username": "app",
    "password": "p@ss",
    "sslmode": "require",
}
