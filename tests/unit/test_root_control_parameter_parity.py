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

DÖRDÜNCÜ HALQA (kompas1.md Faza 9): sətrin `description_az` sütunu. Üç halqa
da bütöv ola bilər, HALBUKİ Root ekranda `EXPORT_STORE_ANOMALY_MIN_EMPLOYEES`
kimi texniki kod görər — yəni parametr texniki olaraq idarə olunan, praktiki
olaraq isə oxunmayan qalar (bölmə 4: interfeys dili Azərbaycancadır).

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

#: `description_az` axtarışının pəncərəsi — bir `VALUES` sətri bundan uzun deyil.
_DESCRIPTION_SEARCH_CHARS: Final[int] = 400

#: "İnsan üçün yazılmış mətn" sayılan minimum uzunluq (bax `_seeded_description_of`).
_MIN_DESCRIPTION_CHARS: Final[int] = 8


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


def _seeded_description_of(key_value: str, blob: str) -> str | None:
    """Açarın seed sətrindəki Azərbaycanca izahı (tapılmasa `None`).

    SQL-i AST ilə deyil, MƏTN kimi oxuyuruq: alternativ tam SQL parseri
    əlavə etmək olardı, halbuki burada sual sadədir — "bu açarın yazıldığı
    `VALUES` sətrində insan üçün yazılmış bir mətn varmı". Axtarış açarın
    sətrindən sonrakı hissə ilə məhdudlaşır və növbəti sətrin `(`-i görünəndə
    dayanır, ona görə qonşu açarın izahını səhvən bu açara YAZMIR.

    "İnsan mətni" meyarı: ən azı 8 simvol VƏ bir boşluq. Bu, `'INTEGER'`,
    `'DAILY'`, `'100'` kimi texniki dəyərləri kənarda saxlayır — onların heç
    birində boşluq yoxdur.
    """
    for match in re.finditer(rf"'{re.escape(key_value)}'", blob):
        window = blob[match.end() : match.end() + _DESCRIPTION_SEARCH_CHARS]
        segment = window.split("\n\n", maxsplit=1)[0]
        next_tuple = re.search(r"\)\s*,?\s*\n\s*\(", segment)
        if next_tuple:
            segment = segment[: next_tuple.start()]
        for candidate in re.findall(r"'([^']*)'", segment):
            if len(candidate) >= _MIN_DESCRIPTION_CHARS and " " in candidate:
                return candidate
    return None


def test_every_seeded_limit_carries_an_azerbaijani_description() -> None:
    """İzahsız sətir ROOT ekranında TEXNİKİ KOD kimi görünür.

    ──────────────────────────────────────────────────────────────────────────
    BU QAPI NİYƏ ƏLAVƏ OLUNDU
    ──────────────────────────────────────────────────────────────────────────
    kompas1.md Faza 9 auditində məlum oldu ki, `controllers/root_control.py`
    etiketi 17 sətirlik ƏL İLƏ yazılmış `LIMIT_LABELS` cədvəlindən oxuyur və
    baza sətrinin `description_az` sütununu SÜKUTLA atır. Nəticədə 166
    açarın 149-u ekranda ingiliscə kod adı ilə görünürdü.

    Kontroller düzəldildi (etiket əvvəlcə bazadan oxunur), lakin düzəliş
    yalnız SƏTİRDƏ izah VARSA işləyir. Ona görə izahın mövcudluğu artıq
    qapıdır: yeni açar izahsız seed edilsə, bu test qırılır — reqressiya
    ekranda görünməzdən əvvəl.
    """
    blob = _seed_sources()
    missing = sorted(
        key.value for key in SystemLimitKey if _seeded_description_of(key.value, blob) is None
    )
    assert not missing, (
        "Seed sətrində Azərbaycanca `description_az` olmayan açar(lar): "
        f"{missing} — ROOT ekranında texniki kod kimi görünəcəklər."
    )


def test_the_root_screen_reads_its_labels_from_the_limit_row() -> None:
    """Kontroller `LimitView`-un üç sütununu ekrana ÖTÜRMƏLİDİR.

    Mənbə mətnini oxuyuruq, çünki alternativ — sahta sessiya ilə tam
    kontrolleri qurmaq — yalnız sahtənin doldurulmasını yoxlayardı. Sual isə
    quruluşa aiddir: `_fill` sətri `limit_row(view.key, view.value)`-a geri
    qayıtsa, izah və diapazon YENİDƏN atılar və qüsur səssizcə qayıdar.
    """
    source = (_REPO_ROOT / "src" / "presentation" / "controllers" / "root_control.py").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "description_az=view.description_az",
        "min_value=view.min_value",
        "max_value=view.max_value",
        "is_stored=view.is_stored",
    ):
        assert fragment in source, (
            f"`_fill` artıq `{fragment}` ötürmür — ROOT ekranı limitin "
            "bazadakı izahını/diapazonunu itirir."
        )


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


def test_the_hr_operations_expansion_added_its_root_parameters() -> None:
    """kompas1.md-nin (#26–#30 + export) parametrləri yerindədir.

    Yuxarıdakı test ilə eyni əsaslandırma: SAY deyil, PREFİKS yoxlanılır.
    Burada əlavə bir səbəb də var — bu genişlənmə İKİ fərqli qatda parametr
    yaradıb (hesablama və export təcrübəsi) və birinin unudulması digərini
    yaşıl saxlayardı.
    """
    present = {key.value for key in SystemLimitKey}
    for prefix, feature in (
        ("FIELD_REPORT_", "#26+#27 Sahə hesabatı (audit + insident)"),
        ("ANNUAL_LEAVE_", "#28 İllik məzuniyyət balansı"),
        ("BULK_IMPORT_", "#29 Toplu əməliyyatlar"),
        ("EXECUTIVE_DIGEST_", "#30 Planlaşdırılmış icra xülasəsi"),
        ("REPORT_RANGE_", "Faza 7 tarix-aralığı export"),
        ("EXPORT_", "Faza 8 pre-export doğrulama və düzəliş"),
    ):
        assert any(key.startswith(prefix) for key in present), (
            f"{feature} üçün heç bir `{prefix}*` ROOT parametri yoxdur — "
            "funksiya tam hardcode qalıb."
        )


def test_the_v2_backlog_expansion_added_its_root_parameters() -> None:
    """`v2backlog.md`-nin «ROOT PARAMETRİ» işarəli hər dəyəri açar aldı (Faza 15).

    BURADA PREFİKS DEYİL, DƏQİQ AD YOXLANILIR — yuxarıdakı iki testdən fərqli
    olaraq. Səbəb sənədin özündədir: `v2backlog.md` hər funksiyanın yanında
    parametri ADI İLƏ deyil, TƏRİFİ ilə yazır («keçmiş işçi data-saxlama
    müddəti», «korrelyasiya-həddi»). Prefiks yoxlaması belə tərifi tutmazdı:
    `BEHAVIOR_` prefiksi Faza 7-dən ƏVVƏL də mövcud idi (davranış anomaliyası),
    yəni cüt-korrelyasiya heç yazılmasaydı da test YAŞIL qalardı. Dəqiq ad isə
    məhz həmin sükutlu boşluğu bağlayır.

    Siyahı BAĞLIDIR: yeni parametr bura YALNIZ `v2backlog.md`-nin bir bəndinə
    cavab verdikdə əlavə olunur — əks halda test «bu genişlənmə tam köçürüldü»
    sualından «neçə açar var» sualına sürüşərdi.
    """
    present = {key.value for key in SystemLimitKey}
    for feature, keys in (
        ("Faza 3.2 — keçmiş işçi data-saxlama müddəti", ("FORMER_EMPLOYEE_DATA_RETENTION_MONTHS",)),
        ("Faza 3.5 — tövsiyə (referral) bonus-balı", ("EMPLOYEE_REFERRAL_BONUS_POINTS",)),
        (
            "Faza 4.2 — öz-düzəliş sorğusunun pəncərəsi və tavanı",
            ("SELF_CORRECTION_REQUEST_WINDOW_DAYS", "SELF_CORRECTION_REQUEST_MAX_COUNT"),
        ),
        (
            "Faza 5.1 — uzatılmış offline rejimin həddi",
            (
                "OFFLINE_BACKLOG_MAX_HOURS",
                "OFFLINE_BACKLOG_MAX_ENTRIES",
                "OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS",
            ),
        ),
        (
            "Faza 5.2 — kiosk/POS aparat-nasazlığı həddi",
            (
                "HEALTH_MEMORY_WARNING_PERCENT",
                "HEALTH_MEMORY_CRITICAL_PERCENT",
                "HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS",
            ),
        ),
        (
            "Faza 5.3 — şift-handoff qeydi",
            ("SHIFT_HANDOFF_NOTE_MAX_CHARS", "SHIFT_HANDOFF_VISIBILITY_HOURS"),
        ),
        (
            "Faza 5.4 — break-glass fövqəladə giriş",
            (
                "BREAK_GLASS_MAX_DURATION_MINUTES",
                "BREAK_GLASS_APPROVAL_WINDOW_MINUTES",
                "BREAK_GLASS_MAX_GRANTS_PER_MONTH",
            ),
        ),
        ("Faza 6.5 — iş-yükü ədalətliliyi həddi", ("WORKLOAD_FAIRNESS_MAX_GAP",)),
        (
            "Faza 7 — davranış-cütü korrelyasiya həddi",
            (
                "BEHAVIOR_PAIR_CORRELATION_THRESHOLD",
                "BEHAVIOR_PAIR_MIN_SHARED_DAYS",
                "BEHAVIOR_PAIR_SYNC_MINUTES",
            ),
        ),
        ("Faza 8.1 — interfeys dili", ("UI_LANGUAGE",)),
        (
            "Faza 12.1 — dəstək-chat sui-istifadə qorunması",
            ("SUPPORT_CHAT_MAX_MESSAGES_PER_MINUTE", "SUPPORT_CHAT_LOCKOUT_MINUTES"),
        ),
    ):
        missing = sorted(key for key in keys if key not in present)
        assert not missing, (
            f"{feature}: `SystemLimitKey`-də olmayan açar(lar) {missing} — "
            "`v2backlog.md` həmin dəyəri «ROOT PARAMETRİ» kimi işarələyib, "
            "yəni o, kodda hardcode qala BİLMƏZ."
        )
