"""FINAL-UI vizual redizaynı — «heç nə itmədi» qapısı (baseline reqressiyası).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VAR — ƏL İLƏ MÜQAYİSƏ BAŞ TUTMUR
──────────────────────────────────────────────────────────────────────────────
`finalui.md` bütün ekranların vizual redizaynını tələb edir və hər ekrandan
sonra ƏL İLƏ funksional müqayisə deyir: «əvvəl-sonra bax, heç nə itməsin».
`ui-inventory`nin çıxardığı rəqəmlər bunun NİYƏ praktik olmadığını göstərir —
99 sinif, 424 interaktiv element, 288 `.connect()` çağırışı, 211 `Signal`
elanı, 209 `set_*`/`populate*` setter. Bir neçə ekrandan sonra insan diqqəti
YORULUR, baxış SƏTHİLƏŞİR — və məhz onda bir siqnal, bir setter sükutla
itir, heç bir test qırılmır, heç kim fərq etmir (`docs/risk_register.md`-
dəki eyni nümunə: statik AST-in görə bilmədiyi şey insan gözündən DƏ qaça
bilər, amma bura ƏKSİNƏDİR — insan gözünün qaçırdığını AST tuta bilər).

──────────────────────────────────────────────────────────────────────────────
BU QAPI NƏYİ ÖLÇÜR
──────────────────────────────────────────────────────────────────────────────
`tests/fixtures/ui_screen_baseline.py` VİZUAL İŞDƏN ƏVVƏLKİ vəziyyətin
(`(fayl, sinif)` açarı ilə) DONDURULMUŞ ŞƏKLİDİR: hər sinfin `Signal(...)`
ADLARI, `set_*`/`populate*` setter ADLARI, və `.connect()` çağırışlarının
SAYI. Test bunu CARİ koddan (`tests/fixtures/ui_screen_scanner.py` ilə,
AST-lə) YENİDƏN hesablayır və UĞURSUZ olur, əgər:

    * baseline-dakı bir `Signal` ADI cari kodda YOXDURSA;
    * baseline-dakı bir setter ADI cari kodda YOXDURSA;
    * bir sinifdə `.connect()` sayı baseline-dan AZALIBSA;
    * baseline-dakı bir SİNİF cari koddan ÜMUMİYYƏTLƏ YOXOLUBSA.

ARTMA (yeni Signal, yeni setter, çoxalan `.connect()`) UĞURSUZLUQ DEYİL —
vizual iş yeni element əlavə edə bilər, bu NORMALDIR. Qapının məqsədi
İTKİni tutmaqdır, dondurmaq deyil.

──────────────────────────────────────────────────────────────────────────────
BU QAPI NƏYİ ÖLÇMÜR — ƏHATƏ SƏRHƏDİ
──────────────────────────────────────────────────────────────────────────────
`.connect()` çağırışının SAYI qorunur, DOĞRULUĞU YOX: bu, «hər widget bağlı
olmalıdır» qaydası DEYİL. `ui-inventory` xam statik skanın 147 «bağlanmamış»
namizəddən 143-ünün yalançı-müsbət olduğunu tapdı (FormField örtüyü, lüğətə
yazılan lokal dəyişən, lambda bağlaması, göstərmə-üçün `DataTable`) — bu
qapı O SƏHVİ TƏKRARLAMIR, çünki HƏR bir bağlantının DOĞRU widget-ə/slota
getdiyini yoxlamır, sadəcə RƏQƏMİN AZALMADIĞINI yoxlayır. Eyni səbəbdən
Signal/setter ADLARI da MƏZMUNCA (parametrləri, kimin dinlədiyi) yox, YALNIZ
MÖVCUDLUQ baxımından yoxlanılır — `test_screen_data_binding.py` fərqli bir
qatda (kontroller ↔ ekran sərhədi) bunu artıq edir, bura TƏKRARLAMIR.

──────────────────────────────────────────────────────────────────────────────
BASELINE-I NECƏ YENİLƏMƏLİ
──────────────────────────────────────────────────────────────────────────────
Vizual iş QƏSDƏN bir Signal/setter sildisə (məs. iki köhnə ekran BİRLƏŞDİ),
baseline ƏL İLƏ, AÇIQ bir addımla yenilənir:

    .venv/Scripts/python.exe -m tests.tools.refresh_ui_baseline

Bu skript TEST TƏRƏFİNDƏN ÇAĞIRILMIR (bax onun öz başlığı) — əks halda hər
itki səssizcə YENİ NORMA olardı.

──────────────────────────────────────────────────────────────────────────────
MƏLUM ÖLÜ ELEMENTLƏR — BU TEST TƏRƏFİNDƏN QORUNMUR
──────────────────────────────────────────────────────────────────────────────
`tests/fixtures/ui_screen_known_dead_elements.py`-dəki dörd element
(`PermissionMatrixScreen._override_search`, `BackupScreen._auto_toggle`/
`_time_combo`/`_retention`) FINAL-UI-dən ƏVVƏL DƏ ölü idi — heç bir
`.connect()` çağırmır. Onlar bu baseline-da `connect_count`-a HEÇ VAXT
DAXİL OLMAYIB (say artıq onlarsız), ona görə vizual iş onları SINDIRMIR —
sadəcə QEYD kimi saxlanılır ki, kimsə sonradan "biz sındırdıq" deməsin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.ui_screen_baseline import UI_SCREEN_BASELINE
from tests.fixtures.ui_screen_scanner import scan_screen_classes

pytestmark = pytest.mark.unit

SCREENS_DIR = Path(__file__).resolve().parents[2] / "src/presentation/screens"

_REFRESH_COMMAND = ".venv/Scripts/python.exe -m tests.tools.refresh_ui_baseline"


def test_ui_screens_never_lose_signals_setters_or_connections() -> None:
    """Baseline ilə CARİ kod arasında YALNIZ İTKİ axtarır, artımı SAYMIR.

    `assert UI_SCREEN_BASELINE`/`assert current` — ikisi də sıfır-element
    halını tutur: baseline boşdursa ya da `SCREENS_DIR` yanlış yol göstərib
    heç bir sinif tapılmasa, test "0 yoxladım, hamısı keçdi" deyə YAŞIL
    QALMAMALIDIR (bax modul başlığı — belə testlərin ən çox yayılmış ölüm
    formasıdır).
    """
    assert UI_SCREEN_BASELINE, (
        "Baseline BOŞDUR — `tests/fixtures/ui_screen_baseline.py` boş "
        "gəlibsə qapı heç nəyi qorumur. Yenidən yaradın: " + _REFRESH_COMMAND
    )

    current = scan_screen_classes(SCREENS_DIR)
    assert current, f"HEÇ BİR ekran sinfi tapılmadı ({SCREENS_DIR}) — yol dəyişibmi?"

    failures: list[str] = []
    for (file_name, class_name), before in UI_SCREEN_BASELINE.items():
        label = f"{file_name}::{class_name}"
        now = current.get((file_name, class_name))
        if now is None:
            failures.append(
                f"{label} — sinif ARTIQ TAPILMIR (silinib və ya köçürülüb). "
                f"Qəsdəndirsə baseline-ı yeniləyin: {_REFRESH_COMMAND}"
            )
            continue

        missing_signals = [name for name in before["signals"] if name not in now["signals"]]
        if missing_signals:
            failures.append(f"{label} — Signal itib: {sorted(missing_signals)}")

        missing_setters = [name for name in before["setters"] if name not in now["setters"]]
        if missing_setters:
            failures.append(f"{label} — setter itib: {sorted(missing_setters)}")

        if now["connect_count"] < before["connect_count"]:
            failures.append(
                f"{label} — .connect() sayı azalıb: "
                f"{before['connect_count']} → {now['connect_count']}"
            )

    assert not failures, (
        "FINAL-UI reqressiyası — funksionallıq İTİB (aşağıdakı hər sətir "
        "AYRI itkidir). Dəyişiklik QƏSDƏNDİRSƏ baseline-ı yeniləyin:\n"
        f"    {_REFRESH_COMMAND}\n" + "\n".join(f"  - {line}" for line in failures)
    )
