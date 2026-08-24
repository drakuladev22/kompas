"""`tests/fixtures/shadow_card_baseline.py`-i CARİ koddan YENİDƏN YAZIR.

    .venv/Scripts/python.exe -m tests.tools.refresh_shadow_card_baseline

──────────────────────────────────────────────────────────────────────────────
NİYƏ ƏL İLƏ, NİYƏ TEST ÖZÜ ÇAĞIRMIR
──────────────────────────────────────────────────────────────────────────────
`refresh_ui_baseline.py` ilə EYNİ əsaslandırma: `test_shadow_card_width_gate.py`
bu skripti ÇAĞIRMIR. Yeni `shadow=True` çağırışını buraya AVTOMATİK əlavə
etsəydi, hər YENİ tam-enli kart səssizcə "təsdiqlənmiş" sayılardı — qapının
BÜTÜN mənası itərdi. Yeniləmə bir insanın QƏRARI olmalıdır: «bu kartın təbii
eni 1400px-dən AZDIR, `shadow=True` TƏHLÜKƏSİZDİR» — VƏ bu qərar
`tests/e2e/test_shadow_card_width_budget.py`-nin (YAVAŞ, real Qt ölçüsü)
YAŞIL nəticəsinə əsaslanmalıdır, sadəcə bu skripti işlətməklə YOX.

──────────────────────────────────────────────────────────────────────────────
İŞ AXINI — YENİ `shadow=True` ƏLAVƏ EDƏNDƏ
──────────────────────────────────────────────────────────────────────────────
    1. `pytest tests/e2e/test_shadow_card_width_budget.py -m slow` işə salın
       (real Qt qurur, kartın `sizeHint().width()`-ini ölçür).
    2. YAŞILDIRSA (yeni kart 1400px-dən DARdır) — bu skripti işlədin.
    3. QIRMIZIDIRSA — kart 1400px-i keçir, `shadow=True`-nu SİLİN (kölgə
       tam-enli panelə YARAŞMIR, bax `test_shadow_card_width_gate.py`
       başlığı) VƏ YA kartı bölün ki, hər hissə 1400px-dən dar olsun.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.shadow_card_scanner import ShadowCardKey, ShadowCardSite, scan_shadow_card_sites

SCREENS_DIR = Path(__file__).resolve().parents[2] / "src/presentation/screens"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "fixtures/shadow_card_baseline.py"

_HEADER = '''"""`shadow=True` reqressiya qapısının BASELINE-ı — BU FAYL AVTOMATİK YARADILIB.

Əl İLƏ REDAKTƏ ETMƏYİN. Yeniləmək üçün (YALNIZ runtime ölçüsü YAŞIL olandan
SONRA — bax `refresh_shadow_card_baseline.py` başlığı):

    .venv/Scripts/python.exe -m tests.tools.refresh_shadow_card_baseline

Nə üçün bu fayl var: `tests/unit/test_shadow_card_width_gate.py` başlığına
baxın.

──────────────────────────────────────────────────────────────────────────────
BU SAY (ÇAĞIRIŞ YERİ) `tests/e2e/test_shadow_card_width_budget.py`-nin ÖLÇDÜYÜ
SAYDAN (RENDER OLUNAN KART) FƏRQLİDİR — UYĞUNSUZLUQ DEYİL
──────────────────────────────────────────────────────────────────────────────
Bu baseline ÇAĞIRIŞ YERİNƏ görə sayır (bir `shadow=True` sətri = bir giriş).
`group_h.py`-də `_REPORT_CARDS` adlı İKİ elementli dövrə İÇİNDƏ TƏK bir
`shadow=True` çağırışı var — o, İKİ real widget yaradır. Yəni runtime testi
(HƏR RENDER OLUNAN widget-i sayır) bu baseline-dan BİR ARTIQ nəticə görəcək.
Fərq gələcəkdə "bir giriş çatmır" deyə axtarışa səbəb OLMAMALIDIR — bu,
skanın SƏHVİ deyil, İKİ ölçünün TƏBİƏTİDİR (çağırış yeri / real widget sayı).
"""

from __future__ import annotations

from tests.fixtures.shadow_card_scanner import ShadowCardKey

'''


def _format_baseline(data: dict[ShadowCardKey, ShadowCardSite]) -> str:
    lines = [_HEADER, "SHADOW_CARD_BASELINE: frozenset[ShadowCardKey] = frozenset("]
    lines.append("    {")
    for key in sorted(data):
        file_name, class_name, func_name, occurrence = key
        lines.append(f"        ({file_name!r}, {class_name!r}, {func_name!r}, {occurrence}),")
    lines.append("    }")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    data = scan_shadow_card_sites(SCREENS_DIR)
    if not data:
        raise SystemExit(
            f"HEÇ BİR `shadow=True` tapılmadı ({SCREENS_DIR}) — yol yanlışdır, dayandırıldı."
        )
    OUTPUT_PATH.write_text(_format_baseline(data), encoding="utf-8")
    _ruff_format(OUTPUT_PATH)
    print(f"Baseline yeniləndi: {len(data)} `shadow=True` yeri → {OUTPUT_PATH}")


def _ruff_format(path: Path) -> None:
    """`refresh_ui_baseline.py::_ruff_format` ilə EYNİ səbəb (bax onun başlığı)."""
    import subprocess
    import sys

    for args in (["ruff", "check", "--fix", str(path)], ["ruff", "format", str(path)]):
        subprocess.run([sys.executable, "-m", *args], check=False)  # noqa: S603


if __name__ == "__main__":
    main()
