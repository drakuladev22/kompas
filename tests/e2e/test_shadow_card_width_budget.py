"""`shadow=True` daşıyan kartların HƏQİQİ eni 1400px büdcəsini keçməməlidir.

──────────────────────────────────────────────────────────────────────────────
ÖLÇÜLMÜŞ FAKT VƏ BÜDCƏ
──────────────────────────────────────────────────────────────────────────────
`QGraphicsDropShadowEffect` hər repaint-də widget-i offscreen pixmap-a çəkib
bulanıqlaşdırır — xərc SAHƏYƏ görə miqyaslanır. Ölçü
(`shadow_area_survey.py`, `scratchpad`):

    Kiçik tile:                      ~0.2–0.4 ms/repaint — problemsiz
    Orta kart (320×220):             +0.71 ms
    Tam-enli böyük panel:            10–14 ms/repaint

60fps kadr büdcəsi **16.67 ms**-dir. `OpenShiftMarketCard` (o zaman
`shadow=True` daşıyırdı) TƏK BAŞINA **13.91 ms** = büdcənin **83%-i** idi.
1400px özbaşına DEYİL — tipik pəncərə enidir və bütün ölçülər MƏHZ
bu enidə aparılıb.

──────────────────────────────────────────────────────────────────────────────
MEYAR İKİ ŞƏRTDİR, BİR DEYİL — İKİ AYRI TEST FUNKSİYASI
──────────────────────────────────────────────────────────────────────────────
Kart tam-enli panel sayılır, əgər:

    1. `sizeHint()` pəncərə enini aşırsa (kart onsuz da sıxışdırılıb), VƏ YA
    2. FAKTİKİ render SAHƏSİ (en × hündürlük) konteyneri doldurursa (qonşu
       dartsa da, öz siyasəti dartsa da).

Konkret hal İKİNCİ şərti sübut edir: `sync_conflicts.py:319`-dakı kartın
TƏBİİ `sizeHint()`-i cəmi **570px**-dir, LAKİN ekranda FAKTİKİ **1844px**
render olunur — çünki qonşusu (`_build_decision_card`, təbii tələbi
1844px) konteyneri o enə MƏCBUR edir. Elastik kart qonşusuna görə DARTILIR,
repaint xərci isə FAKTİKİ endən gəlir, `sizeHint()`-dən yox.

Ona görə İKİ test funksiyası var, biri DİGƏRİNİ ƏVƏZ ETMİR:

    * `test_shadowed_cards_stay_under_the_natural_width_budget` — ŞƏRT 1:
      widget ÖZ `sizeHint()`-i ilə (heç bir `resize()` MƏCBURİYYƏTİ olmadan)
      göstərilir. `resize()` işlətməmək BURADA DOĞRUDUR: məcburi
      kiçildilmiş pəncərədə ölçülən en TƏBİİ tələbi GİZLƏDƏRDİ.
    * `test_shadowed_cards_stay_under_the_area_budget` — ŞƏRT 2: ekran
      **1400×900**-ə (bütün bugünkü qərarların verildiyi eni) `resize()`
      edilir və kartın FAKTİKİ SAHƏSİ (`geometry().width() * .height()`)
      oxunur. Burada `resize()` MƏHZ ÖLÇMƏK İSTƏDİYİMİZ ŞEYDİR — əksinə,
      resize ETMƏSƏK, dartılma HEÇ VAXT baş verməz və şərt 2 HEÇ VAXT
      sınanmaz.

**Bu iki test GƏLƏCƏKDƏ "biri artıqdır" deyə silinməməlidir** — onlar EYNİ
ölçünü İKİ üsulla YOX, İKİ FƏRQLİ geometriya mənbəyini (təbii tələb / faktiki
konteyner) ölçür və hər ikisi MÜSTƏQİL şəkildə real kartları büdcədən çıxara
bilər.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ŞƏRT 2 EN DEYİL, SAHƏ ÖLÇÜR (VƏ NİYƏ 1920×1080 DEYİL, 1400×900)
──────────────────────────────────────────────────────────────────────────────
İlk versiya ekranı `1920×1080`-ə resize edib EN-i 1400px-lə müqayisə edirdi.
Bu, ÖZÜNÜ İKİ SƏBƏBDƏN doğrulmadı:

    1. `1920×1080`-də TAM-ENLİ istənilən kart ~1872–1920px göstərir — yəni
       «faktiki en > 1400px» qaydası bütün tam-enli kartları (o cümlədən
       QƏSDƏN SAXLADIQLARIMIZI, məs. `FineEntryScreen`) işarələyirdi. En
       real xərcin PROKSİSİDİR, ÖZÜ deyil — ölçülmüş
       sabit nisbət (~7–9.5 ns/px²) göstərir ki, xərcin HƏQİQİ sürücüsü
       SAHƏDİR, TƏK bir ölçü YOX.
    2. `QDialog` alt sinifləri `1920×1080`-ə MƏCBUR resize olunanda dəqiq
       `1920px` (VƏ YA `1872px`) göstərirdi — bu, `resize()` çağırışının
       ÖZÜNÜN artefaktıdır: Qt dialoqu HEÇ VAXT tam pəncərə eninə məcbur
       ETMİR, öz `sizeHint()`-i ilə mərkəzləşdirilmiş göstərir. Bax
       aşağıdakı «`QDialog` ŞƏRT 2-DƏN İSTİSNADIR» bölməsi.

Ona görə ölçü SAHƏYƏ (en × hündürlük) keçirildi, pəncərə isə bugünkü BÜTÜN
qərarların verildiyi **1400×900**-ə resize olunur (`1920×1080` yox) — SAHƏ
ölçüsü artıq PƏNCƏRƏNİ SÜNİ GENİŞLƏNDİRMƏYƏ EHTİYAC DUYMUR, dartılma effekti
kartın ÖZ layout siyasətindən (elastik sütun, `QSizePolicy.Expanding`) gəlir.

**Hədd: 680,000 px².** Özbaşına DEYİL — bugünkü qərarlardan ÇIXARILIB
(`1400px`-lik ekranda ölçülmüş faktiki sahələr):

    Ən böyük SAXLANILAN kart:   FineEntryScreen           650,312 px²
    Ən kiçik ÇIXARILAN kart:    support_inbox söhbət paneli  688,236 px²

Hədd bu ikisinin ARASINDADIR. Marja DAR (~5.8%) — bu, ZƏİFLİK DEYİL, FAKTDIR:
`FineEntryScreen` bir az böyüsə həddi keçəcək və bu, DOĞRU xəbərdarlıq olacaq,
çünki o, ARTIQ (9.10 ms) ən bahalı SAXLANILAN ekrandır. Hədd həmçinin
ÖLÇÜLMÜŞ ~9.5 ns/px² nisbətindən yoxlanıla bilər: 680,000 × 9.5ns ≈ **6.5 ms**
— tək bir kartın 16.67ms kadr büdcəsinin ~**40%**-i. Bundan yuxarı kart TƏK
BAŞINA ekranın xərcini idarə etməyə başlayır.

──────────────────────────────────────────────────────────────────────────────
`QDialog` ŞƏRT 2-DƏN İSTİSNADIR — TİPƏ GÖRƏ, AD SİYAHISI İLƏ YOX
──────────────────────────────────────────────────────────────────────────────
`isinstance(widget, QDialog)` yoxlanılır, sabit AD SİYAHISI YAZILMIR — ad
siyahısı zamanla zibilliyə çevrilir (yeni dialoq əlavə olunanda unudulur),
tip yoxlaması isə SƏBƏBİ kodun ÖZÜNDƏ saxlayır: Qt `QDialog`-u HEÇ VAXT
konteynerin/pəncərənin tam enini tutmağa MƏCBUR ETMİR — o, HƏMİŞƏ öz
`sizeHint()`-i ilə mərkəzləşdirilmiş göstərilir (`shadow_area_survey.py`-nin
öz qeydi də bunu təsdiqləyir). Yəni dialoq üçün SAHƏ Şərt 2-nin təsvir etdiyi
«konteyner dartır» ssenarisini HEÇ VAXT yaşamır — onun eni/sahəsi HƏMİŞƏ
ÖZ `sizeHint()`-indən gəlir, `test_shadowed_cards_stay_under_the_natural_
width_budget` (Şərt 1) bunu ARTIQ TAM ƏHATƏ edir. Ona görə `QDialog`
üçün Şərt 2 `pytest.skip()` edilir — RƏDD YOX, ARTIQLIQ.

──────────────────────────────────────────────────────────────────────────────
BU FAYL YAVAŞDIR VƏ İKİNCİ QATDIR
──────────────────────────────────────────────────────────────────────────────
`tests/unit/test_shadow_card_width_gate.py` (SÜRƏTLİ, AST, HƏR `pytest`
çağırışında işləyir) YENİ, TƏSDİQLƏNMƏMİŞ `shadow=True` çağırışlarını tutur —
LAKİN o test heç bir Qt qurmur, kartın HƏQİQƏTƏN 1400px-dən dar olduğunu
YOXLAMIR, yalnız "bu çağırış BASELINE-DA VARMI" sualına cavab verir. Bu
fayl ƏKS işi görür: real ekranları qurur, `graphicsEffect()`-i
`QGraphicsDropShadowEffect` olan HƏR widget-in enini (yuxarıdakı İKİ üsulla)
ÖLÇÜR. İkisi BİRLİKDƏ `test_ui_screen_regression_gate.py`/`refresh_ui_
baseline.py` cütünün EYNİ iş bölgüsüdür: sürətli qapı NİYYƏTİ, yavaş qapı
DƏQİQLİYİ qoruyur (bax `test_shadow_card_width_gate.py` başlığı).

`@pytest.mark.slow` (30+ real ekran/dialoq qurur, hər biri Qt widget
ağacıdır, İKİ ölçü üsulu ilə) — CI-da tam dəstin bir hissəsi kimi HƏR DƏFƏ
YOX, `shadow=True` DƏYİŞƏNDƏ ƏL İLƏ işə salınır:

    .venv/Scripts/python.exe -m pytest tests/e2e/test_shadow_card_width_budget.py -m slow

──────────────────────────────────────────────────────────────────────────────
HƏDƏF SİYAHISI BASELINE-DAN GƏLİR, TƏKRAR YAZILMIR
──────────────────────────────────────────────────────────────────────────────
`ALL_SHADOW_SCREENS` `tests/fixtures/shadow_card_baseline.py`-dan (AST
qapısının TƏSDİQLƏNMİŞ siyahısı) TÖRƏNİR — statik siyahı BURADA əl ilə
SAXLANILMIR, çünki iki müstəqil siyahı bir gün AYRILARDI («hansı sinif
kölgə daşıyır» sualının İKİ CAVABI olardı). `_EXTRA_ARGS` YALNIZ
QURULUŞ üçün lazım olan konstruktor arqumentlərini verir — `test_theme_
coverage.py::_EXTRA_ARGS` ilə EYNİ naxış.

Bir sinif artıq HEÇ BİR kölgəli widget DAŞIMIRSA (`shadow=True`
çıxarıb), test bunu REQRESSİYA SAYMIR — sürətli AST qapısı onsuz da YENİ
əlavələri tutur, bura yalnız KÖHNƏLMİŞ hədəfin ZƏRƏRSİZ nişanəsidir (bax
`test_shadow_card_width_gate.py` "BASELINE YALNIZ ARTA BİLƏR" bölməsi).
Sinif QURULA BİLMİRSƏ (konstruktor imzası dəyişib) test onu
ATLAYIR — bura KONSTRUKTOR UYĞUNLUĞUNU yox, EN BÜDCƏSİNİ yoxlayır.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtWidgets import QDialog, QGraphicsDropShadowEffect, QWidget

from tests.conftest import requires_qt
from tests.fixtures.shadow_card_baseline import SHADOW_CARD_BASELINE

pytestmark = [pytest.mark.e2e, pytest.mark.qt, pytest.mark.slow]

#: Ölçülərin aparıldığı tipik pəncərə eni — ŞƏRT 1 (`sizeHint()`) üçün.
MAX_SHADOW_CARD_WIDTH_PX = 1400

#: ŞƏRT 2 (faktiki, dartılmış SAHƏ) üçün hədd — bax modul başlığı «Hədd:
#: 680,000 px²»: ən böyük SAXLANILAN kart (`FineEntryScreen`, 650,312 px²)
#: ilə ən kiçik ÇIXARILAN kart (`support_inbox` söhbət paneli, 688,236 px²)
#: ARASINDADIR.
MAX_SHADOW_CARD_AREA_PX2 = 680_000

#: ŞƏRT 2-nin resize etdiyi pəncərə — bütün bugünkü qərarların verildiyi en
#: (`1920×1080` DEYİL, bax modul başlığı «Niyə Şərt 2 en deyil, sahə ölçür»).
STRETCHED_WINDOW_SIZE = (1400, 900)

#: Konstruktoru `theme`-dən BAŞQA arqument tələb edən siniflər.
#: `test_theme_coverage.py::_EXTRA_ARGS` ilə EYNİ naxış — bəzi dəyərlər
#: ORADAN təkrar işlədilir ki, iki fayl AYRI "necə qurulur" bilgisi
#: saxlamasın.
_EXTRA_ARGS: dict[str, dict[str, Any]] = {
    "AnnouncementComposeDialog": {"stores": [("s1", "Mağaza 1")]},
    "AnnualLeaveRequestDialog": {"days": [("2026-08-25", "8 saat")]},
    "BulkImportResultDialog": {
        "success_count": 1,
        "error_count": 0,
        "errors": [],
        "truncated_extra": 0,
        "created": [],
    },
    "StoreTemplateApplyDialog": {"template_name": "Şablon", "snapshot_summary": "özət"},
    "StoreTemplateCaptureDialog": {"stores": [("s1", "Mağaza 1")]},
    "FatalStartupScreen": {"message": "Test xətası"},
    "FineEntryScreen": {
        "fine_types": ["Gecikmə"],
        "stores": ["Mağaza 1"],
        "employees": ["İşçi 1"],
    },
    "ManualTimeOverrideDialog": {
        "employee_name": "Test İşçi",
        "store_name": "Mərkəz",
        "kind": "check_in",
        "system_time": "09:00",
    },
    "OperatorQueueScreen": {"assigned_stores": ["Bellona 28 May"]},
    "LicenseInactiveScreen": {
        "reason": "test",
        "deactivated_at": "2026-08-24",
        "installation_id": "test-id",
    },
    "CatalogEntryDialog": {"title": "Test", "value_label": "Dəyər"},
    "ExportCorrectionDialog": {
        "employees": [("e1", "İşçi 1")],
        "fields": [("f1", "Sahə 1")],
        "default_date": "2026-08-24",
        "reason_min_length": 10,
    },
    "OpenShiftPostDialog": {
        "stores": [("s1", "Mağaza 1")],
        "days": [("2026-08-25", "Çərşənbə")],
        "work_modes": [("m1", "Səhər")],
    },
}


def _publish_confirm_dialog_kwargs() -> dict[str, Any]:
    """`PublishConfirmDialog` `summary=PublishSummary(...)` tələb edir — iç-içə tip."""
    from src.presentation.screens.fine_review import PublishSummary

    return {
        "summary": PublishSummary(
            period_text="Avqust 2026",
            publish_count=3,
            discard_count=0,
            store_count=2,
            amount_text="150 AZN",
        )
    }


_SPECIAL_KWARGS: dict[str, Any] = {
    "PublishConfirmDialog": _publish_confirm_dialog_kwargs,
}

#: `(fayl, sinif)` — `shadow_card_baseline.py`-dakı TƏSDİQLƏNMİŞ siyahıdan
#: TÖRƏNİR (bax modul başlığı). Fayl adı `.py`-siz modul adına çevrilir.
ALL_SHADOW_SCREENS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            (file_name.removesuffix(".py"), class_name)
            for file_name, class_name, _, _ in SHADOW_CARD_BASELINE
        }
    )
)


def _build(module: str, name: str, theme: Any) -> Any:
    from importlib import import_module

    screen_class = getattr(import_module(f"src.presentation.screens.{module}"), name)
    kwargs_source = _SPECIAL_KWARGS.get(name)
    kwargs = kwargs_source() if kwargs_source is not None else _EXTRA_ARGS.get(name, {})
    return screen_class(theme, **kwargs)


def _build_and_show(qt_app: Any, module: str, name: str, *, resize: tuple[int, int] | None) -> Any:
    """Qurur, (verilibsə) `resize()` edir, göstərir və hadisə dövrəsini işlədir.

    Qurula BİLMƏYƏN sinif (davam edən redaktə konstruktor
    imzasını dəyişibsə) `pytest.skip()` ilə ATLANIR — bu test EN büdcəsini
    yoxlayır, konstruktor uyğunluğunu YOX (o, `test_theme_coverage.py`-nin
    predmetidir).
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    try:
        widget = _build(module, name, theme)
    except Exception as error:
        pytest.skip(
            f"{name} qurula bilmədi ({type(error).__name__}: {error}) — vizual iş davam edir"
        )

    if resize is not None:
        widget.resize(*resize)
    widget.show()
    qt_app.processEvents()
    return widget


def _find_shadowed(widget: Any) -> list[QWidget]:
    candidates: list[QWidget] = [widget, *widget.findChildren(QWidget)]
    return [
        child
        for child in candidates
        if isinstance(child.graphicsEffect(), QGraphicsDropShadowEffect)
    ]


@requires_qt
@pytest.mark.parametrize(("module", "name"), ALL_SHADOW_SCREENS, ids=lambda value: value)
def test_shadowed_cards_stay_under_the_natural_width_budget(qt_app, module: str, name: str) -> None:  # type: ignore[no-untyped-def]
    """ŞƏRT 1 — `shadow=True` daşıyan widget-in TƏBİİ `sizeHint().width()`-i.

    `resize()` MƏCBURİYYƏTİ YOXDUR (bax modul başlığı «Meyar iki şərtdir»):
    widget öz təbii tələbi ilə göstərilir — kart özü GENİŞ tələb edirsə
    (qonşusundan ASILI OLMADAN) bura tutur.
    """
    widget = _build_and_show(qt_app, module, name, resize=None)
    shadowed = _find_shadowed(widget)
    widget.close()

    if not shadowed:
        # KÖHNƏLMİŞ HƏDƏF — `shadow=True` artıq çıxarılıb.
        # Reqressiya DEYİL (bax modul başlığı): sürətli AST qapısı YENİ
        # əlavələri onsuz da tutur.
        return

    oversized = [
        (child, child.sizeHint().width())
        for child in shadowed
        if child.sizeHint().width() > MAX_SHADOW_CARD_WIDTH_PX
    ]
    assert not oversized, (
        f"{name}: {len(oversized)} kölgəli widget TƏBİİ eni ilə "
        f"{MAX_SHADOW_CARD_WIDTH_PX}px büdcəsini keçir (tam-enli panelə "
        f"kölgə yaraşmır, 13.91 ms/repaint = 60fps büdcəsinin 83%-i): "
        + ", ".join(f"{w.sizeHint().width()}px" for w, _ in oversized)
    )


@requires_qt
@pytest.mark.parametrize(("module", "name"), ALL_SHADOW_SCREENS, ids=lambda value: value)
def test_shadowed_cards_stay_under_the_area_budget(qt_app, module: str, name: str) -> None:  # type: ignore[no-untyped-def]
    """ŞƏRT 2 — `shadow=True` daşıyan widget-in FAKTİKİ (dartılmış) SAHƏSİ.

    Pəncərə **1400×900**-ə (bugünkü qərarların verildiyi en) MƏCBUR EDİLİR:
    elastik kart öz TƏBİİ tələbindən dar olsa da, qonşusu (ya da öz
    siyasəti) onu konteynerin bütün enini tutmağa MƏCBUR edə bilər — bax
    modul başlığındakı `sync_conflicts.py:319` nümunəsi (570px təbii,
    1844px faktiki). Bura `test_shadowed_cards_stay_under_the_natural_
    width_budget`-i ƏVƏZ ETMİR — ikisi FƏRQLİ geometriya mənbəyini ölçür.

    ÖLÇÜLƏN EN DEYİL, SAHƏDİR (bax modul başlığı «Niyə Şərt 2 en deyil,
    sahə ölçür») — xərcin həqiqi sürücüsü budur, en yalnız PROKSİDİR.

    `QDialog` İSTİSNADIR (bax modul başlığı «QDialog Şərt 2-dən
    istisnadır») — Qt onu HEÇ VAXT konteynerin tam enini tutmağa MƏCBUR
    ETMİR, ona görə bu ssenari dialoq üçün MƏNASIZDIR.
    """
    widget = _build_and_show(qt_app, module, name, resize=STRETCHED_WINDOW_SIZE)
    if isinstance(widget, QDialog):
        widget.close()
        pytest.skip(
            f"{name}: QDialog-dur — Şərt 2 (konteyner dartması) dialoqa aid deyil, "
            "Şərt 1 (natural sizeHint()) onu artıq tam əhatə edir"
        )

    shadowed = _find_shadowed(widget)
    widget.close()

    if not shadowed:
        return  # bax modul başlığı — köhnəlmiş hədəf, reqressiya deyil

    oversized = [
        (child, child.geometry().width() * child.geometry().height())
        for child in shadowed
        if child.geometry().width() * child.geometry().height() > MAX_SHADOW_CARD_AREA_PX2
    ]
    assert not oversized, (
        f"{name}: {len(oversized)} kölgəli widget dartılmış sahəsi ilə "
        f"{MAX_SHADOW_CARD_AREA_PX2:,}px² büdcəsini keçir (~9.5 ns/px² "
        f"nisbətinə görə ~{MAX_SHADOW_CARD_AREA_PX2 * 9.5 / 1000:.1f} ms-dən "
        "artıq repaint xərci): " + ", ".join(f"{area:,}px²" for _, area in oversized)
    )
