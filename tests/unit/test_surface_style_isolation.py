"""Widget üslub cədvəlinin uşaqlara SIZMAMASI — qapı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
Qt-də widget səviyyəsində qoyulan üslub cədvəli BÜTÜN alt ağaca tətbiq olunur.
Seçicisiz bir elan (`background-color: X;`) həmin widget-in hər uşağına düşür
və tətbiq səviyyəsindəki qaydaları üstələyir.

Layihədə bunun ölçülmüş nəticəsi belə olub: `EmployeeHomeScreen` özünə
`--color-content-bg` verirdi, kioskun ƏSAS düyməsi isə (`variant=action`,
Navy fon + AĞ mətn) həmin açıq rəngi götürürdü. Yəni «İcazə İstəyirəm»
yazısı ağ fonda ağ mətn kimi çıxırdı — kontrast **1.05:1**, praktik olaraq
görünmürdü. Mağaza işçisinin gün ərzində basdığı əsas düymə budur.

Kontrast skripti bunu tuta bilməzdi: o, TOKEN cütlərini ölçür, token cütü isə
tamamilə düzgündür. Səhv palitrada deyil, Qt-nin kaskadındadır — ona görə
qapı da başqa qatdadır.

İki yoxlama var: statik (naxış bir daha yazılmasın) və faktiki render
(düzəlişin işlədiyi sübut olunsun).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import requires_qt

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRESENTATION = _REPO_ROOT / "src" / "presentation"

#: Seçicisiz `background-color` elanı olan `setStyleSheet` çağırışı.
#: Seçicili forma (`#Ad { … }`, `QLabel { … }`) uşaqlara sızmır və icazəlidir.
_LEAKY = re.compile(r"setStyleSheet\(\s*f?\"(?![^\"]*\{\s*background)[^\"]*background-color:")

#: İstisnalar — sızma BURADA zərərsizdir və səbəbi yazılıb.
_ALLOWED: dict[str, str] = {
    # Yarpaq element: uşağı yoxdur, ona görə sızacaq yer də yoxdur.
    "primitives.py": "StatusDot/Avatar — uşaqsız çəkmə elementləri",
    "charts.py": "qrafik xanaları — uşaqsız",
    "toggle.py": "açar düyməsi — uşaqsız",
}


def test_no_screen_leaks_its_background_into_children() -> None:
    """`screens/` altında seçicisiz fon elanı qalmamalıdır."""
    leaks: list[str] = []
    for path in sorted((_PRESENTATION / "screens").rglob("*.py")):
        if "__pycache__" in str(path) or path.name in _ALLOWED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _LEAKY.search(line):
                leaks.append(f"{path.name}:{number}")

    assert leaks == [], (
        "Seçicisiz `background-color` uşaqlara sızır — `theme.manager."
        f"set_surface_color(widget, rəng)` işlədin: {leaks}"
    )


@requires_qt
@pytest.mark.parametrize("mode_name", ["LIGHT", "DARK"])
def test_kiosk_primary_button_keeps_its_own_colour(qt_app, mode_name: str) -> None:  # type: ignore[no-untyped-def]
    """Kioskun əsas düyməsi valideynin fonunu GÖTÜRMƏMƏLİDİR.

    Piksel ölçülür, QSS mətni yox: qüsur məhz QSS "düzgün görünən" halda baş
    verirdi — qayda şablonda vardı, Qt isə onu tətbiq etmirdi.
    """
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode, theme_tokens
    from src.presentation.widgets.worker_status import WorkerStatus

    mode = ThemeMode.LIGHT if mode_name == "LIGHT" else ThemeMode.DARK
    theme = ThemeManager(preference=mode)
    theme.apply(qt_app)

    screen = EmployeeHomeScreen(
        theme, full_name="Rəşad Məmmədov", position_name="Satıcı", store_name="Bellona"
    )
    screen.set_status(WorkerStatus.VERIFIED)
    screen.resize(1280, 860)
    screen.show()
    qt_app.processEvents()

    button = screen._action
    assert button.isEnabled(), "test yanlış vəziyyəti ölçür — düymə sönülüdür"
    rendered = button.grab().toImage().pixelColor(button.width() // 2, 6).name()
    expected = theme_tokens(mode)["--color-action-bg"].lower()
    screen.close()

    assert rendered == expected, (
        f"əsas düymə {rendered} rəngindədir, gözlənilən {expected} — valideynin "
        "üslub cədvəli uşağa sızır"
    )
