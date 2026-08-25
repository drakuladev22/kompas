"""Siqnal bağlantısı QAPISI — redizayn zamanı bağlantının itməsinin qarşısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
Ekran redizayn ediləndə widget-lər YENİDƏN YARADILIR. Vizual görünüşü köçürmək
asandır və gözlə yoxlanır; `.connect()` sətrini köçürmək isə görünmür — yeni
düymə maketdəki kimi görünür, basılır, HEÇ NƏ olmur və heç bir xəta çıxmır.
Layihədə məhz bu baş verib: 171 ekran siqnalından 32-si heç yerdə consume
olunmurdu, üstəlik bir neçə süzgəc yalnız çipin rəngini dəyişib siyahıya
toxunmurdu.

Belə qüsuru gözlə tutmaq mümkün deyil, çünki səhv EKRANDA GÖRÜNMÜR. Ona görə
o, qapıya çevrilib: hər ekran siqnalı İKİ suala cavab verməlidir.

    1. YAYILIRMI? Siqnal öz ekran faylında `emit` olunur, ya da bir widget
       siqnalına relay edilir. Cavab yoxdursa, düymə siqnala bağlanmayıb —
       redizayn zamanı `.connect()` sətrinin unudulmasının dəqiq izi budur.
    2. DİNLƏNİLİRMİ? Siqnalın öz faylından KƏNARDA bir consume-edəni var.
       Yoxdursa, o, aşağıdakı iki siyahıdan birində AÇIQ şəkildə qeyd
       olunmalıdır — sükutla ölü qalması qadağandır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİ AYRI SİYAHI
──────────────────────────────────────────────────────────────────────────────
"Consume edilmir" iki tamamilə fərqli vəziyyəti gizlədir və onları bir yerdə
saxlamaq ikisini də görünməz edərdi:

  * `LOCAL_ONLY` — ekran işi ÖZÜ görür, siqnal yalnız məlumatdır (məs. süzgəc
    keşlənmiş sətirləri özü yenidən süzür). Bu, DÜZGÜN vəziyyətdir.
  * `PENDING_CONSUMER` — düymə həqiqətən ölüdür və səbəbi yazılıb (backend
    yoxdur, hədəf ekran naviqasiyaya bağlanmayıb və s.). Bu, İŞ MADDƏSİDİR.

Yeni siqnal əlavə edən adam onu ya bağlamalı, ya da səbəbi ilə birlikdə
`PENDING_CONSUMER`-ə yazmalıdır. Siyahılar boşalmalıdır, uzanmamalı.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
_SCREENS = _SRC / "presentation" / "screens"

#: Ekran işi ÖZÜ görür — siqnal xarici müşahidəçi üçündür, ölü DEYİL.
LOCAL_ONLY: Final[dict[str, str]] = {
    "group_b.OperatorQueueScreen.filter_changed": (
        "`set_filter` keşlənmiş sətirləri özü yenidən süzür"
    ),
    "group_b.OperatorQueueScreen.store_filter_changed": (
        "`set_store_filter` keşlənmiş sətirləri özü yenidən süzür (audit G-6)"
    ),
    "group_b.PhotoDropZone.file_selected": (
        "fayl yolu `photo_path` açarı ilə göndərmə yükündə gedir (`controllers/fine_entry.py`)"
    ),
    "group_c.UsersScreen.search_changed": "`_on_search` cədvəli özü süzür",
    "group_c.ShiftSwapScreen.selected": (
        "seçim `_current`-ə yazılır və `approved`/`rejected` onu işlədir"
    ),
    # `group_c.ShiftPlanningScreen.template_selected` BURADAN ÇIXARILDI:
    # siqnalın ÖZÜ silindi (QA-FULL Faza 3). Bu sətrin əsaslandırması —
    # «şablon ekranda tətbiq olunur» — YANLIŞ idi: heç bir yerdə tətbiq
    # olunmurdu, dörd düymə klikdə heç nə etmirdi. Bu qapının məhz belə
    # yanlış əsaslandırmalarla yan keçilə biləcəyinin sənədləşdirilmiş nümunəsi.
    "group_e.SupportChatWidget.closed": "`close_panel` paneli özü gizlədir",
    "group_f.TaskCard.approved": "`TasksScreen` onu öz siqnalına relay edir",
    "group_f.TaskCard.rejected": "`TasksScreen` onu öz siqnalına relay edir",
    # Faza 4.2 — «Geri Çək» üçü də EYNİ relay ilə işləyir: `card.withdrawn` →
    # `TasksScreen.withdraw_requested` → `controllers/kiosk_self_service.py`
    # (`withdraw_self_correction`-a yazır). Relay EYNI faylda olduğu üçün
    # xarici-istehlakçı axtarışı onu görmür — `approved`/`rejected` ilə EYNİ
    # vəziyyət, yalnız fərq odur ki, `withdrawn` adı TƏKRİSİZDİR və ona görə
    # ada-görə qarışıqlıq yolundan keçmir.
    "group_f.TaskCard.withdrawn": "`TasksScreen` onu öz siqnalına relay edir",
    "group_i.WidgetRow.moved": "`DashboardBuilderScreen` eyni faylda dinləyir",
    "group_i.WidgetRow.placement_changed": (
        "`DashboardBuilderScreen` eyni faylda dinləyir (audit G-5)"
    ),
    "group_g.NotificationPanel.filter_changed": ("`set_filter` siyahını özü yenidən qurur"),
    "face_control.FaceEnrollmentScreen.subject_changed": "seçim ekranın öz vəziyyətidir",
    "face_control.FaceVerificationOverlay.dismissed": "örtük özünü bağlayır",
    "group_a_entry.FirstRunWizard.cancelled": "sihirbaz addımı özü geri qaytarır",
    "group_f.FineAppealScreen.appeal_started": (
        "`start_appeal` formanı ÖZÜ açır və cərimə açarını saxlayır — siqnal "
        "yalnız müşahidəçi üçündür"
    ),
    "group_h.HelpCenterScreen.topic_selected": (
        "`_on_topic` həmin karta özü sürüşdürür — çip indeksdir, süzgəc deyil"
    ),
}

#: HƏQİQƏTƏN ölü — səbəb yazılıb. Bu siyahı QISALMALIDIR.
#:
#: Aşağıdakı beşi sinif-agah yoxlama (bax `_consumers`) əlavə olunanda üzə
#: çıxdı: hər biri ADI başqa ekranda bağlanmış siqnaldır, ona görə köhnə,
#: ada-görə yoxlama onları «bağlanıb» sayırdı. Heç biri sadə naqil işi DEYİL —
#: hər biri arxasında OLMAYAN bir axın tələb edir, ona görə uydurma bağlantı
#: yazmaqdansa iş maddəsi kimi GÖRÜNƏN saxlanılır.
PENDING_CONSUMER: Final[dict[str, str]] = {
    "group_c.ShiftPlanningScreen.publish_requested": (
        "«Planı Yayımla» düyməsi SİLİNDİ (bax `NEVER_RAISED`) — nə yayan, nə "
        "dinləyən ucu var; siqnal ekranın gələcək müqaviləsi kimi saxlanılır"
    ),
}


#: Elan olunub, lakin onu YAYACAQ element ekranda YOXDUR.
#:
#: `PENDING_CONSUMER`-dən fərqi: orada bağlantının DİNLƏYƏN ucu yoxdur, burada
#: isə YAYAN ucu. İkisi ayrı saxlanılır, çünki düzəlişləri də ayrıdır — biri
#: kontroller tələb edir, digəri ekranda bir idarəedici.
NEVER_RAISED: Final[dict[str, str]] = {
    "group_c.ShiftPlanningScreen.publish_requested": (
        "«Planı Yayımla» düyməsi SİLİNDİ: `ShiftPlanningUseCase`-də nəşr "
        "anlayışı yoxdur, matris `apply_assignment` ilə dərhal yazılır. Düymə "
        "yalnız işləmirdi DEYİL, yanlış model öyrədirdi (menecer «hələ "
        "yayımlanmayıb» sanıb sınaq dəyişikliyi edə bilərdi). Siqnal ekranın "
        "müqaviləsi kimi saxlanılır — həqiqi nəşr axını əlavə olunanda "
        "düymə geri qayıdacaq"
    ),
}


@cache
def _declared() -> dict[str, Path]:
    """`ekran_faylı.Sinif.siqnal` → fayl yolu.

    KEŞLƏNİR — `_is_consumed` onu HƏR siqnal üçün (`_ambiguous_names` vasitəsilə)
    çağırır. Keşsiz variantda ~157 siqnal × ~20 ekran faylı = 3000-dən çox AST
    parse-ı olurdu və qapı tək başına ~45 saniyə çəkirdi; tam dəst yükü altında
    isə `--timeout=60`-ı aşıb bütün icranı ASIRDI. Qaytarılan sözlük yalnız
    OXUNUR (heç bir çağıran onu dəyişmir), ona görə paylaşılan nüsxə təhlükəsizdir.
    """
    found: dict[str, Path] = {}
    for path in sorted(_SCREENS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    continue
                target = stmt.targets[0]
                call = stmt.value
                if (
                    isinstance(target, ast.Name)
                    and isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == "Signal"
                ):
                    found[f"{path.stem}.{node.name}.{target.id}"] = path
    return found


def _consumers() -> dict[str, set[Path]]:
    """`.<ad>.connect(` çağırışının olduğu fayllar — siqnal adına görə.

    Açar TAM YOLDUR, fayl adı deyil: kontroller çox vaxt ekranla EYNİ adı
    daşıyır (`screens/fine_review.py` ↔ `controllers/fine_review.py`). Ada görə
    müqayisə etsəydik, kontrollerin bağlantısı «ekranın öz faylı» sayılıb
    atılardı və işləyən 22 siqnal səhvən "ölü" kimi bayraqlanardı.
    """
    sites: dict[str, set[Path]] = {}
    pattern = re.compile(r"\.(\w+)\.connect\(")
    for path in _SRC.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            sites.setdefault(match.group(1), set()).add(path)
    return sites


@cache
def _function_scopes(path: Path) -> tuple[str, ...]:
    """Faylın hər funksiyasının mənbə mətni — bir dəfə hesablanır.

    `ast.get_source_segment` hər çağırışda faylı yenidən sətirlərə bölür; 400+
    fayl × 150+ siqnal üçün bu, qapını dəqiqələrlə uzadırdı. Sətir aralığı ilə
    kəsmək eyni nəticəni verir və bir dəfə keşlənir.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - `src/` həmişə parse olunur
        return (source,)
    scopes = [
        "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    # Modul səviyyəsindəki bağlantılar üçün faylın ÖZÜ də əhatə sayılır.
    scopes.append(source)
    return tuple(scopes)


def _connect_scopes(path: Path, signal: str) -> list[str]:
    """`.<signal>.connect(` çağırışını ƏHATƏ EDƏN funksiyaların mənbə mətni.

    Fayl bütövlükdə yoxlansaydı nəticə YANILDICI olardı: `app.py` onlarla ekran
    sinfinin adını çəkir, ona görə «fayl bu sinfi çəkir» şərti orada HƏMİŞƏ
    doğrudur. Nümunə: `closed` siqnalı həm `SupportChatWidget`-də, həm
    `RecoveryConsoleScreen`-də var; `app.py` yalnız ikincisini bağlayır, lakin
    birincinin adını da başqa yerdə çəkir — fayl səviyyəsində yoxlama ikisini
    də «bağlanıb» sayardı.

    Funksiya səviyyəsi layihənin FAKTİKİ quruluşuna uyğundur: `app.py`-də
    `_attach_*` metodu `isinstance` yoxlamasında sinfi çəkir, kontrollerdə isə
    `attach(self, screen: XScreen)` imzası. Hər ikisi funksiyanın İÇİNDƏDİR.

    Faylın ÖZÜ də siyahıdadır (modul səviyyəli bağlantılar üçün), lakin O,
    yalnız funksiya tapılmayanda fərq yaradır — `app.py` kimi fayllarda
    funksiya əhatəsi həmişə daha dardır.
    """
    needle = f".{signal}.connect("
    scopes = _function_scopes(path)
    inside_functions = [scope for scope in scopes[:-1] if needle in scope]
    if inside_functions:
        return inside_functions
    whole_file = scopes[-1]
    return [whole_file] if needle in whole_file else []


def _is_consumed(
    qualified: str,
    own_file: Path,
    consumers: dict[str, set[Path]],
    *,
    when_unprovable: bool,
) -> bool:
    """Siqnalın HƏQİQİ dinləyicisi varmı — AD TOQQUŞMASINI nəzərə alaraq.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SADƏCƏ AD KİFAYƏT ETMİR
    ──────────────────────────────────────────────────────────────────────────
    Qt-də `screen.approved.connect(...)` sətrindən `screen`-in TİPİNİ statik
    çıxarmaq mümkün deyil, ona görə qapı əvvəlcə yalnız ADA baxırdı. Nəticədə
    eyni adlı siqnal bir ekranda bağlananda DİGƏRLƏRİ də «bağlanıb» sayılırdı.
    Bu kor nöqtə real qüsur gizlədib: `ShiftSwapScreen.approved`/`.rejected` və
    `DailyRosterScreen.approve_requested` heç yerə bağlı deyildi, halbuki eyni
    adlar `TasksScreen`/`annual_leave` tərəfində bağlı olduğu üçün qapı
    susurdu — düymələr isə istehsalatda sadəcə heç nə etmirdi.

    Ona görə ad toqquşan siqnallar üçün ƏLAVƏ şərt qoyulur: consume-edən fayl
    ekranın SİNİF ADINI da çəkməlidir. Kontroller onu onsuz da çəkir (`app.py`
    `isinstance` yoxlaması, `TYPE_CHECKING` idxalı), ona görə bu şərt işləyən
    bağlantıları pozmur — yalnız «başqa ekranın eyni adlı siqnalı» səhv
    müsbətini kəsir.
    """
    name = qualified.rsplit(".", 1)[1]
    outside = consumers.get(name, set()) - {own_file}
    if not outside:
        return False
    if name not in _ambiguous_names():
        return True
    if not _is_screen_class(qualified, own_file):
        # DAXİLİ WIDGET (`QueueRow`, `TopicChip`, dialoq, `QWidget` əsaslı
        # kiosk ekranı): onu kontroller yox, VALİDEYN emal edir — çox vaxt elə
        # öz faylında, `self.X`-ə relay edərək. Burada sahiblik STATİK olaraq
        # SÜBUT EDİLƏ BİLMİR, ona görə cavabı çağıran tərəf seçir:
        #
        #   * «sənədləşdirilməyib?» yoxlaması `True` verir — sübutsuz halda
        #     əlavə sənəd tələb etmək səs-küy yaradardı;
        #   * «siyahı köhnəlib?» yoxlaması `False` verir — sübutsuz halda
        #     «artıq bağlanıb» demək YANLIŞ «düzəldildi» siqnalı olardı.
        return when_unprovable

    screen_class = qualified.split(".")[1]
    module_stem = qualified.split(".", maxsplit=1)[0]
    for path in outside:
        # KONTROLLER EKRANLA EYNİ ADI DAŞIYIR (`screens/recovery_console.py` ↔
        # `controllers/recovery_console.py`). Belə kontroller `screen: Any`
        # yazsa da sahiblik şübhəsizdir — ad uyğunluğu sinif adından güclüdür.
        if path.stem == module_stem:
            return True
        if any(screen_class in scope for scope in _connect_scopes(path, name)):
            return True
    return False


@cache
def _is_screen_class(qualified: str, own_file: Path) -> bool:
    """Siqnalı təyin edən sinif `Screen` törəməsidirmi.

    Ayrım vacibdir: `Screen` törəməsini KONTROLLER bağlayır (ona görə sinif
    adını tələb etmək olar), daxili widget-i isə valideyn ekranın ÖZÜ — və o,
    çox vaxt sinif adını çəkmir, sadəcə `row.x.connect(self.x)` yazır.
    """
    class_name = qualified.split(".")[1]
    tree = ast.parse(own_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return any("Screen" in ast.dump(base) for base in node.bases)
    return False


@cache
def _ambiguous_names() -> frozenset[str]:
    """Birdən çox ekran sinfində eyni adla təyin olunan siqnallar (keşlənir)."""
    names = [key.rsplit(".", 1)[1] for key in _declared()]
    counts = Counter(names)
    return frozenset(name for name, total in counts.items() if total > 1)


def _raised(path: Path) -> set[str]:
    """Fayl daxilində `emit` olunan və ya relay edilən siqnal adları."""
    text = path.read_text(encoding="utf-8")
    # `\.emit` — mötərizəsiz də tutulur: `QTimer.singleShot(ms, self.finished.emit)`
    # siqnalı ÇAĞIRIŞ kimi deyil, ARQUMENT kimi ötürür və mötərizə tələb edən
    # naxış onu "heç vaxt yayılmır" sayardı.
    emitted = set(re.findall(r"self\.(\w+)\.emit\b", text))
    relayed = set(re.findall(r"\.connect\(\s*self\.(\w+)\s*\)", text))
    return emitted | relayed


def test_every_screen_signal_is_actually_raised() -> None:
    """Hər siqnal öz ekranında yayılır — düymə ona BAĞLIDIR.

    Bu qapı redizayn qüsurunu tutur: widget yenidən yaradılıb, lakin
    `.connect()` köçürülməyibsə, siqnal heç vaxt yayılmır.
    """
    silent: list[str] = []
    by_file: dict[Path, set[str]] = {}
    for qualified, path in _declared().items():
        if path not in by_file:
            by_file[path] = _raised(path)
        if qualified.rsplit(".", 1)[1] in by_file[path] or qualified in NEVER_RAISED:
            continue
        silent.append(qualified)

    assert silent == [], (
        "Bu siqnallar heç yerdə yayılmır — onları yayacaq widget bağlantısı "
        f"yoxdur (redizayn zamanı itmiş `.connect()` ola bilər): {sorted(silent)}"
    )


def test_every_screen_signal_is_consumed_or_declared_local() -> None:
    """Dinləyicisi olmayan hər siqnal AÇIQ şəkildə qeyd olunmalıdır."""
    consumers = _consumers()
    undocumented: list[str] = []

    for qualified, path in _declared().items():
        if _is_consumed(qualified, path, consumers, when_unprovable=True):
            continue
        if qualified in LOCAL_ONLY or qualified in PENDING_CONSUMER:
            continue
        undocumented.append(qualified)

    assert undocumented == [], (
        "Bu siqnalları heç kim dinləmir və səbəbi yazılmayıb. Ya kontrollerə "
        "bağlayın, ya da `LOCAL_ONLY`/`PENDING_CONSUMER`-ə səbəbi ilə əlavə "
        f"edin: {sorted(undocumented)}"
    )


def test_the_registries_do_not_list_signals_that_are_already_connected() -> None:
    """Bağlanan siqnal siyahıda QALMAMALIDIR — siyahı köhnəlməməlidir.

    Əks halda siyahı zamanla "bir dəfə ölü olmuş" adların arxivinə çevrilər və
    növbəti oxucu ona baxıb "bu düymə işləmir" qənaətinə gələrdi.
    """
    consumers = _consumers()
    declared = _declared()
    stale: list[str] = []

    # AD TOQQUŞMASI ARTIQ İSTİSNA DEYİL. Əvvəl eyni adlı siqnallar bu
    # yoxlamadan TAMAMİLƏ atlanırdı: `screen.x.connect(...)` sətrindən
    # `screen`-in tipini çıxarmaq mümkün olmadığı üçün köhnəlmə sübut edilə
    # bilmirdi. Nəticədə siyahı «bir dəfə ölü olmuş» adların arxivinə
    # çevrilirdi — məhz `FineAppealInboxScreen.accepted` belə saxlanmışdı və
    # onun səbəbi («sətir vəziyyəti ekranda yenilənir») FAKTİKİ olaraq YANLIŞ
    # idi: ekran heç nə etmirdi. `_is_consumed` sinif adını da tələb etdiyi
    # üçün indi ad toqquşan hallarda da qərar verilə bilir.
    for qualified in list(LOCAL_ONLY) + list(PENDING_CONSUMER):
        path = declared.get(qualified)
        if path is None:
            stale.append(f"{qualified} (belə siqnal artıq yoxdur)")
            continue
        if _is_consumed(qualified, path, consumers, when_unprovable=False):
            stale.append(f"{qualified} (artıq bağlanıb)")

    assert stale == [], f"Siyahılar köhnəlib: {sorted(stale)}"


def test_pending_entries_carry_a_reason() -> None:
    """Səbəbsiz «sonra bağlayarıq» qeydi qadağandır."""
    short = [key for key, reason in PENDING_CONSUMER.items() if len(reason) < 20]
    assert short == [], f"Səbəb çox qısadır: {short}"
