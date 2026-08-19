"""`Screen` törəməsi İKİNCİ layout qurmamalıdır — LAYOUT-1.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`Screen.__init__` `self` üzərində `QVBoxLayout` qurur və məzmun üçün `body()`
təqdim edir. Üç ekran (`DeviceAdminScreen`, `DevicePendingScreen`,
`SupportInboxScreen`) bunun üstünə İKİNCİ `QVBoxLayout(self)` yazırdı.

Qt ikinci layout-u QURMUR — yalnız konsola

    QLayout: Attempting to add QLayout "" to DeviceAdminScreen "ScreenSurface",
    which already has a layout

xəbərdarlığı yazır. Nəticə: ekran İSTİSNASIZ qurulur, `show_screen()` `True`
qaytarır, sorğuları da işləyir — LAKİN həmin layout-a əlavə edilən bütün
vidjetlər valideynsiz qalır və istifadəçi BOŞ ekran görür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AST QAPISI, NİYƏ İŞƏ SALIB YOXLAMA DEYİL
──────────────────────────────────────────────────────────────────────────────
Ekranı işə salıb yoxlamaq CANLI BAZA tələb edir (hər ekran öz sorğusunu edir),
yəni qapı yalnız DB olan mühitdə işləyərdi — məhz orada isə qüsur artıq
istifadəçiyə çatıb. AST yoxlaması bazasızdır, saniyənin altında işləyir və
səbəbi mənbədə göstərir.

Nasazlığın tutulma tarixçəsi bunu tələb edir: üç ekranın üçü də istisna
atmırdı, testlərdən keçirdi və `show_screen()` `True` qaytarırdı — yəni
mövcud qapıların HEÇ BİRİ onu görmürdü.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCREENS_DIR = Path(__file__).resolve().parents[2] / "src" / "presentation" / "screens"

#: `QWidget` üzərində layout quran konstruktorlar — hamısı eyni nəticəni verir.
_LAYOUT_TYPES = frozenset(
    {"QVBoxLayout", "QHBoxLayout", "QGridLayout", "QFormLayout", "QStackedLayout", "QBoxLayout"}
)


def _screen_subclasses(tree: ast.Module) -> list[ast.ClassDef]:
    """`Screen`-dən törəyən siniflər.

    Yalnız BİRBAŞA törəmə axtarılır: ikinci səviyyə törəmələr (məs.
    `DeviceAdminScreen`-dən törəyən bir sinif) onsuz da valideynin
    konstruktorunu çağırır və eyni qadağaya tabedir — lakin belə hal hazırda
    yoxdur və uydurma ümumiləşdirmə qapını oxunmaz edərdi.
    """
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Screen" for base in node.bases)
    ]


def _self_layout_calls(node: ast.ClassDef) -> list[tuple[str, int]]:
    """`QXLayout(self)` çağırışları — yəni `self`-ə layout QURAN sətirlər.

    `QVBoxLayout(card)` və ya arqumentsiz `QHBoxLayout()` TOXUNULMUR: onlar
    başqa vidjetə aiddir və problem yaratmır. Ölçü YALNIZ `self`-dir.
    """
    found: list[tuple[str, int]] = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id not in _LAYOUT_TYPES:
            continue
        if any(isinstance(arg, ast.Name) and arg.id == "self" for arg in call.args):
            found.append((call.func.id, call.lineno))
    return found


def test_no_screen_installs_a_second_layout_on_itself() -> None:
    """QÜSURUN QAPISI: `Screen` törəməsi `self`-ə layout QURMAMALIDIR."""
    offenders: list[str] = []

    for path in sorted(_SCREENS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for klass in _screen_subclasses(tree):
            for layout_type, line in _self_layout_calls(klass):
                offenders.append(f"{path.name}:{line} {klass.name} → {layout_type}(self)")

    assert not offenders, (
        "Bu siniflər `Screen`-in layout-unun üstünə ikincisini qurur — Qt onu "
        "QURMUR və ekran BOŞ görünür. Əvəzinə `self.body()` işlədin:\n  " + "\n  ".join(offenders)
    )


def test_the_gate_actually_detects_the_pattern() -> None:
    """Qapının ÖZÜ işləyirmi — yoxsa sükutla «heç nə tapmadı» deyir?

    Bu, qapı testlərinin klassik nasazlığıdır: axtarış naxışı səhv yazılır,
    nəticə boş çıxır və qapı ƏBƏDİ yaşıl qalır. Ona görə qüsurlu nümunə
    burada QƏSDƏN qurulur və qapının onu tapdığı yoxlanılır.
    """
    sample = ast.parse(
        "class BadScreen(Screen):\n"
        "    def __init__(self):\n"
        "        super().__init__(theme)\n"
        "        layout = QVBoxLayout(self)\n"
        "        other = QHBoxLayout(card)\n"
    )

    classes = _screen_subclasses(sample)

    assert len(classes) == 1
    assert _self_layout_calls(classes[0]) == [("QVBoxLayout", 4)]
