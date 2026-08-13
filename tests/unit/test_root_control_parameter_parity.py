"""ROOT İdarə Mərkəzinin PARİTET qapısı (kompasos11.md Faza 10).

──────────────────────────────────────────────────────────────────────────────
BU FAYL NİYƏ VAR — BİRDƏFƏLİK AUDİT NİYƏ KİFAYƏT ETMİR
──────────────────────────────────────────────────────────────────────────────
Faza 10 bütün konfiqurasiya dəyərlərinin ROOT İdarə Mərkəzinə köçürülməsini
tələb edir. Həmin köçürmə əl ilə bir dəfə yoxlanıla bilər — amma yoxlama
NƏTİCƏSİ növbəti `SystemLimitKey` əlavəsində sükutla köhnəlir. Bir açar
enum-a yazılıb `DEFAULT_LIMITS`-ə yazılmasa, ROOT ekranı onu göstərəndə
`KeyError` ilə çökər; miqrasiyaya yazılmasa isə MÖVCUD kirayəçilərdə
`system_limits` sətri heç vaxt yaranmaz və Root dəyəri GUI-dan dəyişə
bilməz (yalnız kodda oturan fallback işləyər — yəni parametr adı ilə
"idarə olunan", faktiki olaraq isə hardcode qalar).

Ona görə audit bir HESABAT deyil, bir QAPI kimi yazılıb.

──────────────────────────────────────────────────────────────────────────────
ÜÇ SUAL NİYƏ MƏHZ BUNLARDIR
──────────────────────────────────────────────────────────────────────────────
Bir parametrin "Root-dan idarə olunması" üç halqadan ibarətdir və hər üçü
ayrı-ayrılıqda qırıla bilər:

  1. `SystemLimitKey` — açar var. (Olmasa kod onu oxuya bilməz.)
  2. `DEFAULT_LIMITS` — defolt var. (Olmasa `RootControlUseCase.list_limits`
     `DEFAULT_LIMITS[key]` sətrində çökür.)
  3. SQL seed — `schema.sql` və ya bir miqrasiya onu MÖVCUD kirayəçiyə
     əlavə edir. (Olmasa GUI-dan dəyişiklik saxlanmır.)

──────────────────────────────────────────────────────────────────────────────
NİYƏ `list_limits` DAVRANIŞI DA YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`RootControlUseCase.list_limits` hazırda `for key in SystemLimitKey` üzərində
dövr edir — yəni yeni açar ekranda AVTOMATİK görünür. Bu, xoşbəxt təsadüf
deyil, qərardır; kimsə onu əl ilə qurulmuş siyahıya çevirsə, yeni parametrlər
sükutla görünməz olardı. Aşağıdakı test məhz həmin qərarı bağlayır.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DATABASE_DIR: Final[Path] = _REPO_ROOT / "database"
_COMPOSITION: Final[Path] = _REPO_ROOT / "src" / "presentation" / "composition.py"


def _seed_sources() -> str:
    """`schema.sql` + BÜTÜN miqrasiyalar, tək mətn kimi.

    SXEM TƏK BAŞINA KİFAYƏT ETMİR: CLAUDE.md §7-yə görə `schema.sql` miqrasiya
    sətirlərini EHTİVA ETMİR — quraşdırma hər ikisini ardıcıl tətbiq edir.
    Yalnız birinə baxmaq sonrakı fazaların açarlarını yalançı-mənfi ilə rədd
    edərdi (bax `test_notifications.py`-dakı eyni genişlənmə).
    """
    paths = [_DATABASE_DIR / "schema.sql", *sorted((_DATABASE_DIR / "migrations").glob("*.sql"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths if path.exists())


def test_every_system_limit_key_has_a_default() -> None:
    """Defoltsuz açar ROOT ekranını `KeyError` ilə çökdürür."""
    missing = sorted(key.value for key in SystemLimitKey if key not in DEFAULT_LIMITS)
    assert not missing, f"`DEFAULT_LIMITS`-də defoltu olmayan açar(lar): {missing}"


def test_every_system_limit_key_is_seeded_by_sql() -> None:
    """Seed edilməyən açar mövcud kirayəçidə GUI-dan dəyişdirilə bilməz.

    Yəni parametr "Root-dan idarə olunur" görünər, faktiki olaraq isə kodda
    oturan fallback işləyər — Faza 10-un bağlamaq istədiyi qüsurun məhz özü.
    """
    blob = _seed_sources()
    missing = sorted(
        key.value for key in SystemLimitKey if not re.search(rf"'{re.escape(key.value)}'", blob)
    )
    assert not missing, f"Heç bir SQL faylında seed edilməyən açar(lar): {missing}"


def test_root_control_lists_every_key_without_a_curated_allowlist() -> None:
    """`list_limits` enum üzərində dövr etməlidir, əl ilə yazılmış siyahı üzərində YOX.

    Mənbə mətnini oxuyuruq, çünki alternativ — sahta repo ilə tam use case
    qurmaq — bu qərarı DEYİL, sahtənin doldurulmasını yoxlayardı: siyahı əl ilə
    yazılsaydı və sahtə də həmin siyahını qaytarsaydı, test yaşıl qalardı.
    """
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "application"
        / "use_cases"
        / "root_control.py"
    ).read_text(encoding="utf-8")

    assert "for key in SystemLimitKey" in source, (
        "`RootControlUseCase.list_limits` artıq bütün `SystemLimitKey` üzərində "
        "dövr etmir — yeni ROOT parametrləri ekranda sükutla görünməz qalacaq."
    )


def _classes_accepting_a_limits_port() -> set[str]:
    """`__init__`-də `limits` arqumenti qəbul edən BÜTÜN siniflər (`src/` üzrə)."""
    found: set[str] = set()
    for path in (_REPO_ROOT / "src").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:  # pragma: no cover — sintaksis qapısı `ruff`-dadır
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    args = {a.arg for a in item.args.args} | {a.arg for a in item.args.kwonlyargs}
                    if "limits" in args:
                        found.add(node.name)
    return found


def test_every_limit_aware_class_actually_receives_the_port() -> None:
    """Kompozisiya kökü portu ötürməsə, parametr ROOT-da GÖRÜNÜR, amma TƏSİRSİZDİR.

    ──────────────────────────────────────────────────────────────────────────
    BU QAPI NİYƏ AYRICA LAZIMDIR
    ──────────────────────────────────────────────────────────────────────────
    Yuxarıdakı üç test halqanın ilk üç bəndini qoruyur: açar var, defolt var,
    seed var. Onların üçü də yaşıl ola bilər, HALBUKİ istehlakçı sinif
    `limits=None` ilə qurulub və hər çağırışda modul fallback-ını oxuyur.
    Nəticə istifadəçi üçün ən pis formadır: Root dəyəri dəyişir, ekran
    dəyişikliyi təsdiqləyir, audit sətri yazılır — və sistem köhnə dəyərlə
    işləməyə davam edir. Səssiz uğursuzluq.

    Faza 10.2-də bu, faktiki olaraq BAŞ VERDİ: 51 infrastruktur açarı elan
    olundu, 20 sinif `limits` parametri qəbul etdi, lakin `composition.py`
    heç birinə port ötürmürdü.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AST, NİYƏ MƏTN AXTARIŞI YOX
    ──────────────────────────────────────────────────────────────────────────
    `"limits=" in source` yoxlaması sinfə YAXIN, amma BAŞQA çağırışa aid olan
    arqumenti də sayardı. AST hər çağırışın öz açar sözlərinə baxır.

    MÖVQELİ ARQUMENT QƏSDƏN TUTULMUR: `limits` hər yerdə açar sözü ilə
    ötürülməlidir (`_LazyBufferDrain` məhz bu səbəbdən düzəldilib) — mövqeli
    ötürmə oxunuşu çətinləşdirir və bu qapını kor edir.
    """
    tree = ast.parse(_COMPOSITION.read_text(encoding="utf-8"))
    built: set[str] = set()
    given: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            built.add(node.func.id)
            if any(keyword.arg == "limits" for keyword in node.keywords if keyword.arg):
                given.add(node.func.id)

    limit_aware = _classes_accepting_a_limits_port() & built
    # BOŞ YERƏ YAŞIL OLMAĞA QARŞI: parametrin adı dəyişsə (`limits` → başqa),
    # kəsişmə boşalar və yuxarıdakı iddia HEÇ NƏ yoxlamadan keçərdi. Aşağıdakı
    # sətir qapının özünün sınmadığını təsdiqləyir.
    assert len(limit_aware) >= 20, (
        "`limits` portunu qəbul edən və `composition.py`-da qurulan sinif sayı "
        f"gözlənilməz dərəcədə azdır ({len(limit_aware)}) — parametrin adı "
        "dəyişib və bu qapı kor qalıb ola bilər."
    )

    unwired = sorted(limit_aware - given)
    assert not unwired, (
        "Bu siniflər `limits` portunu QƏBUL EDİR, lakin `composition.py` onu "
        f"ÖTÜRMÜR — ROOT dəyişikliyi onlara çatmayacaq: {unwired}"
    )


def test_the_expansion_added_its_root_parameters() -> None:
    """kompasos11.md-nin 12 funksiyası üçün əlavə olunan açarlar yerindədir.

    NİYƏ SAYI DEYİL, PREFİKSLƏRİ YOXLAYIRIQ: dəqiq say hər yeni parametrdə
    testi qırardı və adam onu artırmaqla "düzəldərdi" — yəni qapı öz mənasını
    itirərdi. Prefiks yoxlaması isə BÜTÖV bir funksiyanın parametrsiz
    qaldığını tutur, ki bu, həqiqətən qüsurdur.
    """
    present = {key.value for key in SystemLimitKey}
    for prefix, feature in (
        ("EXCEPTION_", "#9 İstisna motoru"),
        ("POS_", "#7 POS səlahiyyət siyasəti"),
        ("BEHAVIOR_", "#8 Davranış anomaliyası"),
        ("LABOR_", "#14 Əmək qanunu xəbərdarlığı"),
        ("STAFFING_", "#13 Tarixi nümunə təklifi"),
        ("OVERTIME_", "#15 Overtime izləmə"),
        ("OPEN_SHIFT_", "#16 Açıq növbə bazarı"),
        ("EMPLOYEE_DOCUMENT_", "#17 Sənəd idarəetməsi"),
        ("ANNOUNCEMENT_", "#19 Broadcast elanlar"),
        ("PERFORMANCE_", "#20 Performans qiymətləndirməsi"),
        ("ATTRITION_", "#21 Turnover riski"),
        ("BENCHMARK_", "#24 Benchmark paneli"),
    ):
        assert any(key.startswith(prefix) for key in present), (
            f"{feature} üçün heç bir `{prefix}*` ROOT parametri yoxdur — "
            "funksiya tam hardcode qalıb."
        )
