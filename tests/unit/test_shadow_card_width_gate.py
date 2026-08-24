"""`shadow=True` YENİ tam-enli kartda görünə bilməz — SÜRƏTLİ AST qapısı.

──────────────────────────────────────────────────────────────────────────────
ÖLÇÜLMÜŞ FAKT — NİYƏ BU QAYDA VAR
──────────────────────────────────────────────────────────────────────────────
`QGraphicsDropShadowEffect` hər repaint-də widget-i offscreen pixmap-a çəkib
bulanıqlaşdırır — xərc SAHƏYƏ görə miqyaslanır. Ölçü
(`shadow_area_survey.py`, `scratchpad`):

    Kiçik tile (dashboard kartı):    ~0.2–0.4 ms/repaint  — problemsiz
    Orta kart (320×220):             +0.71 ms
    Tam-enli böyük panel:            10–14 ms/repaint

60fps kadr büdcəsi 16.67 ms-dir — tam-enli kölgəli panel TƏK BAŞINA bunun
60–83%-ni yeyir (`OpenShiftMarketCard` 13.91 ms = 83%). Qərar: **təbii eni
(`sizeHint().width()`) 1400px-dən böyük kart `shadow=True` ala bilməz.**
1400px özbaşına DEYİL — tipik pəncərə enidir və bütün
ölçüsü MƏHZ bu enidə (`resize(1400, 900)`) aparılıb; başqa en seçilsəydi
ölçülərin ÖZÜ etibarsız olardı.

──────────────────────────────────────────────────────────────────────────────
BU TEST NƏYİ ÖLÇÜR, NƏYİ ÖLÇMÜR — İKİ QATLI QAPI
──────────────────────────────────────────────────────────────────────────────
Bu fayl SÜRƏTLİDİR (Qt QURMUR, AST ilə işləyir) və YALNIZ NİYYƏTİ qoruyur:
`tests/fixtures/shadow_card_baseline.py`-da TƏSDİQLƏNMİŞ olmayan HƏR YENİ
`shadow=True` çağırışını tutur. Həqiqi ÖLÇÜNÜ (kartın ÖZÜ HƏQİQƏTƏN
1400px-dən darmı) `tests/e2e/test_shadow_card_width_budget.py` aparır (YAVAŞ,
real Qt qurur) — baseline-a giriş YALNIZ o test yaşıl olandan SONRA əlavə
edilməlidir (bax `refresh_shadow_card_baseline.py` iş axını).

Yəni bu qapı `test_ui_screen_regression_gate.py`/`test_screen_data_binding.
py::DELEGATED_BINDERS` naxışının EYNİSİDİR: sürətli AST testi ƏSAS qapıdır
(hər `pytest` çağırışında işləyir), yavaş runtime testi isə DƏQİQLİYİ verir
(yalnız `shadow=True` DƏYİŞƏNDƏ lazımdır). Bu fayl `test_screen_data_
thread_boundary.py`-nin "hər çağırışda Qt qurma" fəlsəfəsini TƏKRARLAYIR.

──────────────────────────────────────────────────────────────────────────────
BASELINE YALNIZ ARTA BİLƏR, HEÇ VAXT AVTOMATİK KİÇİLMİR
──────────────────────────────────────────────────────────────────────────────
Test YALNIZ CARİ koddakı `shadow=True`-nun baseline-da OLMAMASINI tutur
(YENİ, TƏSDİQLƏNMƏMİŞ əlavə). Baseline-da olub kodda ARTIQ olmayan giriş
(kart silinib, ya da `shadow=True` çıxarılıb) SÜKUTLA nəzərdən qaçır — bu,
QƏSDƏNDİR: vizual iş kartları TEZ-TEZ silir/köçürür və hər belə hərəkəti
"reqressiya" saymaq bu testin ƏSL məqsədini (yeni ÖLÇÜLMƏMİŞ risk) əlaqəsiz
səs-küylə batırardı. `DECLARED_BUT_NOT_IMPORTED`-un ƏKS istiqamətdəki
qoruması (`test_dependency_manifest.py::test_declared_but_not_imported_
entries_go_stale_once_imported`) BURAYA TƏTBİQ OLUNMUR, çünki oradakı risk
("paket sonsuza qədər əsaslandırılmış qalır") fərqlidir — burada köhnəlmiş
giriş HEÇ NƏYİ GİZLƏTMİR, sadəcə artıq keçərsiz olan icazədir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.shadow_card_baseline import SHADOW_CARD_BASELINE
from tests.fixtures.shadow_card_scanner import scan_shadow_card_sites

pytestmark = pytest.mark.unit

SCREENS_DIR = Path(__file__).resolve().parents[2] / "src/presentation/screens"

_REFRESH_INSTRUCTIONS = (
    "Bu, YENİ `shadow=True` çağırışıdırsa: ƏVVƏLCƏ "
    "`pytest tests/e2e/test_shadow_card_width_budget.py -m slow` işə salın "
    "(kartın sizeHint().width()-i 1400px-dən DARdırmı, real Qt ilə ölçür). "
    "YAŞILDIRSA: `.venv/Scripts/python.exe -m tests.tools."
    "refresh_shadow_card_baseline` ilə baseline-ı yeniləyin. QIRMIZIDIRSA: "
    "`shadow=True`-nu silin — kölgə tam-enli panelə YARAŞMIR."
)


def test_new_shadow_true_call_sites_must_be_approved_in_the_baseline() -> None:
    """Baseline-da OLMAYAN `shadow=True` çağırışı UĞURSUZLUQ deməkdir.

    `assert SHADOW_CARD_BASELINE`/`assert current` sıfır-element halını
    tutur — baseline BOŞ gəlibsə (fayl korlanıb) ya da `SCREENS_DIR`
    yanlışdırsa, test "0 yoxladım, hamısı keçdi" deyə YAŞIL QALMAMALIDIR.
    """
    assert SHADOW_CARD_BASELINE, (
        "Baseline BOŞDUR — `tests/fixtures/shadow_card_baseline.py` boş "
        "gəlibsə qapı heç nəyi qorumur."
    )

    current = scan_shadow_card_sites(SCREENS_DIR)
    assert current, f"HEÇ BİR `shadow=True` tapılmadı ({SCREENS_DIR}) — yol dəyişibmi?"

    unapproved: list[str] = []
    for key, site in current.items():
        if key in SHADOW_CARD_BASELINE:
            continue
        file_name, class_name, func_name, occurrence = key
        unapproved.append(
            f"{file_name}::{class_name}.{func_name}[{occurrence}] (sətir {site.lineno}) "
            f"— YENİ `shadow=True`, baseline-da TƏSDİQLƏNMƏYİB"
        )

    assert not unapproved, (
        "Tam-enli panelə (>1400px) kölgə YARAŞMIR (13.91 ms/repaint = 60fps "
        "büdcəsinin 83%-i) — hər yeni `shadow=True` runtime ölçüsü ilə "
        "TƏSDİQLƏNMƏLİDİR.\n"
        f"{_REFRESH_INSTRUCTIONS}\n  " + "\n  ".join(unapproved)
    )
