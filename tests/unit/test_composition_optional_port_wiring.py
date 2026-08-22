"""Kompozisiya kökündə OPSİONAL portların bağlanması — «yaşıl test, ölü funksiya» qapısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR (DEEP-GAP Faza 4, `team-lead`-in tapıntısı)
──────────────────────────────────────────────────────────────────────────────
Bugünkü dövrədə bir neçə use case-ə YENİ opsional port əlavə olundu
(`MonthlyFineReviewUseCase.employees`/`.evidence_sync`,
`DailyAttendanceSheetUseCase.limits`, `UserManagementUseCase.fine_exposure`,
`FaceVerificationUseCase.pin_throttle`). Hər birinin `None` fallback-ı VAR —
qayda POZULMUR (istehsalat qırılmır), LAKİN `composition.py` portu ötürmürsə
YAZILMIŞ QORUMA SÜKUTLA SÖNÜKDÜR. Testlər bunu tutmur, çünki test öz sahtə
`UseCase(..., employees=fake_repo)`-ni QURUR — port bağlıdır, test yaşıldır.
İSTEHSALATDA isə `composition.py` onu ötürmür, funksiya ÖLÜDÜR.

Bu, `app.py:3982`-dəki EYNİ qüsur sinfidir («kiosk kartları heç vaxt
doldurulmur» — `set_tasks`/`set_points`/`set_fines` yalnız `show_preview_
home()`-da idi, canlı yol onları çağırmırdı) — fərq təkbaşına GÖRÜNMƏ yerinin
UI yox, KOMPOZİSİYA olmasıdır. Hər ikisində «kod yazılıb, test yaşıldır,
istehsalat yolu ona çatmır» eyni naxışdır.

Naxış `test_signal_wiring_gate.py`-dəkinin EYNİSİDİR (AST + iki siyahı):

    1. BAĞLIDIRMI? `composition.py`-da klassın çağırışında portun adı açar
       söz kimi görünür VƏ dəyəri hərfi `None` DEYİL.
    2. YOXDURSA, AÇIQ sənədləşdirilməlidir — `UNWIRED_PORTS`-də səbəbi ilə.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SADƏCƏ "None deyilsə YEKUN" DEYİL — `EXPLICIT_NONE` AYRICA TUTULUR
──────────────────────────────────────────────────────────────────────────────
`security_events=None,` yazmaqla qapını "susdurmaq" mümkün olardı (açar var,
qapı "bağlanıb" deyərdi). Ona görə hərfi `None` sabiti YAZILSA da "bağlanıb"
SAYILMIR — açarın YOXLUĞU ilə AÇIQ `None`-u eyni non-halda saxlayırıq.

──────────────────────────────────────────────────────────────────────────────
`UNWIRED_PORTS`-DƏKİ HƏR SƏTIR NİYƏ VAR (bu gün tapılan VƏ pre-existing)
──────────────────────────────────────────────────────────────────────────────
`fine_exposure`, İKİ `security_events` boşluğu (`DualControlDeadlockGuard
UseCase`, `PermissionHierarchyGuardUseCase`) VƏ `evidence_sync` bura
ƏVVƏLCƏ, BİRİ-BİRİ ARDINCA yazılmışdı — hamısı sonradan BAĞLANDI (`infra2`-
nin iki adapteri, `team-lead`-in göstərişi ilə `FailSoftSecurityEventRecorder
(repo("security_events"))` naxışı, `composition.py:3135`-dəki EYNİ SEC-7
qərarı) və SİYAHIDAN ÇIXARILDI — məhz `test_the_deferred_registry_does_not_
list_ports_that_are_already_wired` bunu ƏMƏLİ olaraq TUTDU. `evidence_sync`
bağlandıqdan sonra `fine_review.py::_to_row`-un `has_evidence` sahəsi də
DOMAIN2-nin resepti ilə düzəldildi (bax həmin faylın DEEP-GAP T3 şərhi).
`JobRunner.registry` İSƏ HƏQİQİ boşluq DEYİL: sinif `registry or
ScheduledJobRegistry()` ilə ÖZÜ fallback qurur və işlər `.register()` ilə
qurulduqdan SONRA əlavə olunur (bax `job_runner.py`-nin öz istifadə
nümunəsi) — bura QƏSDƏN "təhlükəsiz" kimi yazılıb, "boşluq" kimi yox.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
_USE_CASES = _SRC / "application" / "use_cases"
_COMPOSITION = _SRC / "presentation" / "composition.py"

#: `(sinif, port)` → SƏBƏB. Bura yazılan hər sətir "bağlı deyil, LAKİN
#: bilərəkdən" deməkdir — sükutla unudulmuş DEYİL. Siyahı QISALMALIDIR.
UNWIRED_PORTS: Final[dict[tuple[str, str], str]] = {
    ("JobRunner", "registry"): (
        "HƏQİQİ BOŞLUQ DEYİL — `JobRunner.__init__` `registry or "
        "ScheduledJobRegistry()` ilə ÖZÜ fallback qurur (bax `job_runner.py` "
        "sinif başlığındakı istifadə nümunəsi); işlər sonradan `.register()` "
        "ilə əlavə olunur, konstruktora ötürülmür. `_build_job_runner()` "
        "məhz bu naxışı işlədir."
    ),
}


def _optional_ports() -> dict[str, dict[str, Path]]:
    """`sinif adı` → `{port adı: fayl}` — `__init__`-in `X | None = None` kwonly arqumentləri.

    YALNIZ `src/application/use_cases/*.py`-dəki siniflər — kompozisiya kökü
    başqa qatların portlarını fərqli mexanizmlə bağlayır (`repo()` ilə
    RAST-GƏLMƏ birbaşa `PostgresXRepository`, `domain`/`infrastructure`
    özləri, bu qapının mövzusu deyil).
    """
    ports: dict[str, dict[str, Path]] = {}
    for path in sorted(_USE_CASES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not (isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__"):
                    continue
                for arg, default in zip(stmt.args.kwonlyargs, stmt.args.kw_defaults, strict=True):
                    if (
                        default is not None
                        and isinstance(default, ast.Constant)
                        and default.value is None
                    ):
                        ports.setdefault(node.name, {})[arg.arg] = path
    return ports


def _composition_calls() -> dict[str, list[ast.Call]]:
    """`composition.py`-da hansı sinif hansı sətirdə çağırılır — AD ÜZRƏ.

    `ast.Name` funksiyalı çağırışlar kifayətdir: `composition.py` bütün
    use case-ləri BARE idxal edir (`from ... import X`), heş bir sinif
    modul-prefiksli çağırılmır.
    """
    tree = ast.parse(_COMPOSITION.read_text(encoding="utf-8"))
    calls: dict[str, list[ast.Call]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.setdefault(node.func.id, []).append(node)
    return calls


def _is_wired(call: ast.Call, port: str) -> bool:
    """Açar sözlə ötürülübmü VƏ dəyəri hərfi `None` DEYİLMİ."""
    for kw in call.keywords:
        if kw.arg != port:
            continue
        return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return False


def _unwired_pairs() -> list[tuple[str, str]]:
    """`composition.py`-da HEÇ olmasa bir çağırışda bağlanmayan `(sinif, port)` cütləri.

    Sinif `composition.py`-da ÜMUMİYYƏTLƏ çağırılmırsa keçilir — bu qapının
    mövzusu YALNIZ "çağırılıb, LAKİN portu unudulub" haldır (team-lead-in
    tapşırığı `composition.py`-a scoped-dir).
    """
    calls_by_class = _composition_calls()
    unwired: list[tuple[str, str]] = []
    for class_name, port_map in _optional_ports().items():
        class_calls = calls_by_class.get(class_name)
        if not class_calls:
            continue
        for port in port_map:
            if not all(_is_wired(call, port) for call in class_calls):
                unwired.append((class_name, port))
    return unwired


def test_every_optional_use_case_port_is_wired_in_composition_or_documented() -> None:
    """Bağlanmayan hər opsional port `UNWIRED_PORTS`-də səbəbi ilə olmalıdır."""
    undocumented = [pair for pair in _unwired_pairs() if pair not in UNWIRED_PORTS]
    assert undocumented == [], (
        "Bu use case portları `composition.py`-da bağlanmır və səbəbi "
        "yazılmayıb — ya bağlayın, ya `UNWIRED_PORTS`-ə səbəbi ilə əlavə edin "
        f"(bax bu faylın başlığı): {sorted(undocumented)}"
    )


def test_the_deferred_registry_does_not_list_ports_that_are_already_wired() -> None:
    """Bağlanan port siyahıda QALMAMALIDIR — köhnəlmiş qeyd gizlədici olar."""
    unwired = set(_unwired_pairs())
    stale = [pair for pair in UNWIRED_PORTS if pair not in unwired]
    assert stale == [], f"`UNWIRED_PORTS` köhnəlib — bu portlar ARTIQ bağlanıb: {sorted(stale)}"


def test_deferred_entries_carry_a_substantive_reason() -> None:
    """Səbəbsiz «sonra bağlayarıq» qeydi qadağandır (`test_signal_wiring_gate` ilə eyni qayda)."""
    short = [key for key, reason in UNWIRED_PORTS.items() if len(reason) < 40]
    assert short == [], f"Səbəb çox qısadır: {short}"
