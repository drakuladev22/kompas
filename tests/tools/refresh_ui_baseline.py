"""`tests/fixtures/ui_screen_baseline.py`-i CARİ koddan YENİDƏN YAZIR.

    .venv/Scripts/python.exe -m tests.tools.refresh_ui_baseline

──────────────────────────────────────────────────────────────────────────────
NİYƏ ƏL İLƏ, NİYƏ TEST ÖZÜ ÇAĞIRMIR
──────────────────────────────────────────────────────────────────────────────
`test_ui_screen_regression_gate.py` bu skripti ÇAĞIRMIR və baseline-ı
avtomatik yeniləmir — əgər çağırsaydı, hər İTKİ («funksionallıq silindi»)
növbəti test işə düşəndə səssizcə YENİ NORMA sayılardı və qapı öz mənasını
itirərdi. Baseline-ın dəyişməsi HƏMİŞƏ bir insanın QƏRARI olmalıdır:
«bəli, bu Signal/setter/bağlantı QƏSDƏN silindi» ya da «xeyr, geri qaytar».

──────────────────────────────────────────────────────────────────────────────
NƏ YAZILIR, NƏ YAZILMIR
──────────────────────────────────────────────────────────────────────────────
Bu skript YALNIZ `UI_SCREEN_BASELINE` sözlüyünü yenidən yaradır. `KNOWN_DEAD_
ELEMENTS` (`ui_screen_known_dead_elements.py`) AYRICA fayldadır və bu skript
ONA TOXUNMUR — ölü element siyahısı `ui-inventory`-nin ƏL İLƏ yoxladığı
(oxuma/mənimsəmə təhlili, bax `refine.py`) NƏTİCƏDİR, AST-in TƏKRAR
İSTEHSAL EDƏ BİLƏCƏYİ bir şey deyil.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.fixtures.ui_screen_scanner import ScreenClassSignature, ScreenKey, scan_screen_classes

SCREENS_DIR = Path(__file__).resolve().parents[2] / "src/presentation/screens"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "fixtures/ui_screen_baseline.py"

_HEADER = '''"""FINAL-UI reqressiya qapısının BASELINE-ı — BU FAYL AVTOMATİK YARADILIB.

Əl İLƏ REDAKTƏ ETMƏYİN. Yeniləmək üçün:

    .venv/Scripts/python.exe -m tests.tools.refresh_ui_baseline

Nə üçün bu fayl var və nəyi qoruyur: `tests/unit/test_ui_screen_regression_
gate.py` başlığına baxın. Məlum ölü elementlər (bu baseline-ın SİLİNMƏSİNƏ
səbəb OLMAYAN, artıq mövcud boşluqlar) `ui_screen_known_dead_elements.py`-
dədir.
"""

from __future__ import annotations

from tests.fixtures.ui_screen_scanner import ScreenClassSignature, ScreenKey
'''


def _format_signature(signature: ScreenClassSignature) -> str:
    signals = ", ".join(repr(name) for name in signature["signals"])
    if signals:
        signals += ","
    setters = ", ".join(repr(name) for name in signature["setters"])
    if setters:
        setters += ","
    return (
        "ScreenClassSignature(\n"
        f"        signals=({signals}),\n"
        f"        setters=({setters}),\n"
        f"        connect_count={signature['connect_count']},\n"
        "    )"
    )


def _format_baseline(data: dict[ScreenKey, ScreenClassSignature]) -> str:
    lines = [_HEADER, "UI_SCREEN_BASELINE: dict[ScreenKey, ScreenClassSignature] = {"]
    for key in sorted(data):
        file_name, class_name = key
        body = _format_signature(data[key])
        lines.append(f"    ({file_name!r}, {class_name!r}): {body},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _ruff_format(path: Path) -> None:
    """Yazılan faylı DƏRHAL `ruff`-la formatlaşdırır.

    Bu skript `Path.write_text` ilə yazır — `Write`/`Edit` alətindən KEÇMİR,
    ona görə `.claude/hooks/ruff_fix.py` (`PostToolUse` hook-u) İŞLƏMİR. Eyni
    addımı burada TƏKRARLAMASAQ, hər `refresh` sonra əl ilə `ruff format` +
    `ruff check --fix` çağırmaq LAZIM gələrdi və unudulanda `ruff` qapısı
    (§2) qırmızı qalardı.
    """
    for args in (["ruff", "check", "--fix", str(path)], ["ruff", "format", str(path)]):
        # S603 — arqumentlər SABİT siyahıdandır (`sys.executable` + hərfi
        # "-m"/"ruff"/"check"/"--fix"/"format" sətirləri), YALNIZ `path`
        # dəyişir — o da bu skriptin ÖZ çıxış yoludur (`OUTPUT_PATH`),
        # xarici/istifadəçi girişi DEYİL.
        subprocess.run([sys.executable, "-m", *args], check=False)  # noqa: S603


def main() -> None:
    data = scan_screen_classes(SCREENS_DIR)
    if not data:
        raise SystemExit(f"HEÇ BİR sinif tapılmadı ({SCREENS_DIR}) — yol yanlışdır, dayandırıldı.")
    OUTPUT_PATH.write_text(_format_baseline(data), encoding="utf-8")
    _ruff_format(OUTPUT_PATH)
    total_signals = sum(len(sig["signals"]) for sig in data.values())
    total_setters = sum(len(sig["setters"]) for sig in data.values())
    total_connects = sum(sig["connect_count"] for sig in data.values())
    print(
        f"Baseline yeniləndi: {len(data)} sinif, {total_signals} siqnal, "
        f"{total_setters} setter, {total_connects} .connect() → {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
