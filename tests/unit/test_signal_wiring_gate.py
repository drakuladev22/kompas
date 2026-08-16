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
    "group_c.DailyRosterScreen.draft_saved": "qaralama ekranın öz vəziyyətindədir",
    "group_c.ShiftPlanningScreen.template_selected": "şablon ekranda tətbiq olunur",
    "group_e.SupportChatWidget.closed": "`close_panel` paneli özü gizlədir",
    "group_f.FineAppealInboxScreen.accepted": "sətir vəziyyəti ekranda yenilənir",
    "group_f.FineAppealInboxScreen.rejected": "sətir vəziyyəti ekranda yenilənir",
    "group_f.TaskCard.approved": "`TasksScreen` onu öz siqnalına relay edir",
    "group_f.TaskCard.rejected": "`TasksScreen` onu öz siqnalına relay edir",
    "group_i.WidgetRow.moved": "`DashboardBuilderScreen` eyni faylda dinləyir",
    "group_i.WidgetRow.placement_changed": (
        "`DashboardBuilderScreen` eyni faylda dinləyir (audit G-5)"
    ),
    "group_g.NotificationPanel.filter_changed": ("`set_filter` siyahını özü yenidən qurur"),
    "face_control.FaceEnrollmentScreen.subject_changed": "seçim ekranın öz vəziyyətidir",
    "face_control.FaceVerificationOverlay.dismissed": "örtük özünü bağlayır",
    "group_a_entry.FirstRunWizard.cancelled": "sihirbaz addımı özü geri qaytarır",
    "group_d.SettingsScreen.notification_changed": (
        "açar vəziyyəti `collected()` ilə «Yadda Saxla» payload-una düşür və "
        "`SettingsController` onu yazır — canlı siqnal yalnız məlumatdır"
    ),
    "group_f.FineAppealScreen.appeal_started": (
        "`start_appeal` formanı ÖZÜ açır və cərimə açarını saxlayır — siqnal "
        "yalnız müşahidəçi üçündür"
    ),
    "group_h.HelpCenterScreen.topic_selected": (
        "`_on_topic` həmin karta özü sürüşdürür — çip indeksdir, süzgəc deyil"
    ),
}

#: HƏQİQƏTƏN ölü — səbəb yazılıb. Bu siyahı QISALMALIDIR.
PENDING_CONSUMER: Final[dict[str, str]] = {}


#: Elan olunub, lakin onu YAYACAQ element ekranda YOXDUR.
#:
#: `PENDING_CONSUMER`-dən fərqi: orada bağlantının DİNLƏYƏN ucu yoxdur, burada
#: isə YAYAN ucu. İkisi ayrı saxlanılır, çünki düzəlişləri də ayrıdır — biri
#: kontroller tələb edir, digəri ekranda bir idarəedici.
NEVER_RAISED: Final[dict[str, str]] = {}


def _declared() -> dict[str, Path]:
    """`ekran_faylı.Sinif.siqnal` → fayl yolu."""
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
        name = qualified.rsplit(".", 1)[1]
        outside = consumers.get(name, set()) - {path}
        if outside:
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

    # AD TOQQUŞMASI: `_consumers` siqnalı ADINA görə tapır, çünki Qt-də
    # `screen.x.connect(...)` sətrindən `screen`-in TİPİNİ statik çıxarmaq
    # mümkün deyil. Eyni ad iki ekranda varsa (məs. `appeal_requested` həm
    # `EmployeeHomeScreen`-də, həm `SalesPointsScreen`-də), birinin bağlanması
    # digərini də "bağlanıb" göstərərdi. Belə hallarda köhnəlmə SÜBUT
    # EDİLƏ BİLMİR, ona görə iddia edilmir — səhv müsbət «düzəldildi» siqnalı
    # vermək, siyahını bir az uzun saxlamaqdan daha zərərlidir.
    ambiguous = {
        key.rsplit(".", 1)[1]
        for key in declared
        if sum(1 for other in declared if other.rsplit(".", 1)[1] == key.rsplit(".", 1)[1]) > 1
    }

    for qualified in list(LOCAL_ONLY) + list(PENDING_CONSUMER):
        if qualified.rsplit(".", 1)[1] in ambiguous:
            continue
        path = declared.get(qualified)
        if path is None:
            stale.append(f"{qualified} (belə siqnal artıq yoxdur)")
            continue
        name = qualified.rsplit(".", 1)[1]
        if consumers.get(name, set()) - {path}:
            stale.append(f"{qualified} (artıq bağlanıb)")

    assert stale == [], f"Siyahılar köhnəlib: {sorted(stale)}"


def test_pending_entries_carry_a_reason() -> None:
    """Səbəbsiz «sonra bağlayarıq» qeydi qadağandır."""
    short = [key for key, reason in PENDING_CONSUMER.items() if len(reason) < 20]
    assert short == [], f"Səbəb çox qısadır: {short}"
