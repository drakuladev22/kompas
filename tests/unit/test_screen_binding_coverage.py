"""Ekran açarlarının canlı bağlama ƏHATƏSİ — reqressiya qapısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VAR
──────────────────────────────────────────────────────────────────────────────
`app.py` 29 ekran açarını qeydiyyatdan keçirir, `ScreenDataBinder._binders()`
isə onların yalnız bir hissəsini tanıyır. Qalan açarlar üçün `populate()`
sadəcə geri qayıdırdı — nə istisna, nə jurnal sətri. Nəticə: canlı bağlaması
olmayan ekran YALNIZ istifadəçi boş pəncərə görəndə üzə çıxırdı və bu, tipik
olaraq istehsalatda baş verirdi.

İki qapı qoyulur:

1. `populate()` bağlama tapmayanda `SCREEN_BINDER_MISSING` XƏBƏRDARLIĞI verir
   (davranış eynidir: istisna atılmır, örtük çökmür).
2. Əhatə olunmayan açarlar AÇIQ SİYAHIDIR. Yeni ekran əlavə edən adam ya onu
   bağlamalı, ya da siyahıya yazmalıdır — hər iki halda qərar GÖRÜNÜR olur.

Test Qt TƏLƏB ETMİR: `app.py` idxal olunmur, `ast` ilə oxunur.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Final

import pytest

from src.presentation.controllers.screen_data import ScreenDataBinder

pytestmark = pytest.mark.unit

_SRC: Final = Path(__file__).resolve().parents[2] / "src/presentation"
APP_PY: Final = _SRC / "app.py"

#: Öz kontrolleri olan ekranlar (`app.py:_register_screens` içindəki
#: `isinstance` budaqları). Bunlar `_binders()`-də YOXDUR və olmamalıdır:
#: hər ikisi HƏM oxuyur, HƏM yazır, yəni siyahı hər əməliyyatdan sonra
#: yenidən oxunmalıdır (CLAUDE.md bölmə 6 — "Ekranın YAZI yolu").
CONTROLLER_BOUND: Final[dict[str, str]] = {
    "fines": "_attach_fine_entry",
    "live_queue": "_attach_camera_queue",
    "root_control": "_attach_root_control",
    "drive_connection": "_attach_drive_connection",
    # Üç kataloq EYNİ ekran sinfindən (`group_h.CatalogScreen`) qurulur və
    # EYNİ kontrollerə bağlanır — fərq yalnız açardır (bax
    # `controllers/catalog_admin.py` başlığı).
    "work_modes": "_attach_catalog_admin",
    "fine_types": "_attach_catalog_admin",
    "leave_types": "_attach_catalog_admin",
    # FAZA 5/6 yazı yolları.
    "permissions": "_attach_permission_matrix",
    "unassigned_sales": "_attach_sales_review",
    "plugins": "_attach_plugin_admin",
    "dashboard_builder": "_attach_dashboard_builder",
    "exceptions": "_attach_exceptions",
    "profile": "_attach_profile",
    "erp_servers": "_attach_erp_servers",
    "backups": "_attach_backups",
    "infrastructure": "_attach_infrastructure",
    # #19/#20 Ünsiyyət və Performans (kompasos11.md Faza 8) — hər ikisi HƏM
    # oxuyur, HƏM yazır (bax `controllers/announcements.py` və
    # `controllers/performance_review.py` başlıqları).
    "announcements": "_attach_announcements",
    "performance_reviews": "_attach_performance_review",
    # #21 İşdən Çıxma Riski (kompasos11.md Faza 9) — İSTİSNA: bu ekran YALNIZ
    # oxuyur, lakin `_binders()`-ə DEYİL, ÖZ kontrolleri var — çünki baxış
    # `AttritionRiskUseCase.list_for_tenant`-də AUDİT-lənir və icazə yoxlaması
    # use case-in ÖZÜNDƏDİR (bax `controllers/attrition_risk.py` başlığı).
    "attrition_risk": "_attach_attrition_risk",
    # #28 İllik Məzuniyyət Balansı (kompas1.md Faza 4) — təsdiq növbəsi HƏM
    # oxuyur, HƏM yazır (təsdiqlə / rədd et) və hər qərardan sonra siyahı
    # yenidən oxunur, çünki qərar verilmiş sorğu `list_pending`-dən çıxır
    # (bax `controllers/annual_leave.py` başlığı).
    "annual_leave": "_attach_annual_leave",
    # #26+#27 Sahə hesabatları (kompas1.md Faza 3) — İKİ açar, BİR ekran sinfi
    # və BİR `_attach_*` metodu (üç kataloq ekranı ilə eyni naxış): forma HƏM
    # oxuyur (açıq hesabatlar, kataloq, ROOT limitləri), HƏM yazır (təqdim et /
    # icraya götür / bağla) və hər yazıdan sonra siyahını yenidən oxuyur.
    "store_audit": "_attach_field_reports",
    "incident_report": "_attach_field_reports",
    # #29 Toplu Əməliyyatlar (kompas1.md Faza 5) — CSV idxalı + mağaza şablonu
    # HƏR İKİSİ HƏM oxuyur, HƏM yazır (bax `controllers/bulk_operations.py`
    # başlığı) — `announcements`/`annual_leave` ilə eyni qərar.
    "bulk_operations": "_attach_bulk_operations",
    # Face Control (facecontrol.md Faza 4) — İKİ ekran, İKİ AYRI SƏLAHİYYƏT.
    # Hər ikisi HƏM oxuyur, HƏM yazır: qeydiyyatdan sonra işçinin vəziyyəti
    # `NEW`-dən `ENROLLED`-a keçir, istisna verildikdən sonra aktiv siyahıya
    # düşür — yəni siyahı hər yazıdan sonra yenidən oxunmalıdır (bax
    # `controllers/face_control.py` başlığı).
    "face_enrollment": "_attach_face_enrollment",
    "face_exemptions": "_attach_face_exemptions",
    # G-1 Sinxronizasiya konfliktləri (bölmə 5) — HƏM oxuyur (`inbox`), HƏM
    # yazır (`resolve`). Həll edilmiş konflikt `list_open`-dan çıxır, ona görə
    # siyahı hər qərardan sonra yenidən oxunmalıdır; üstəlik eyni konflikti
    # paralel işləyən ikinci HR bağlamış ola bilər (bax
    # `controllers/sync_conflicts.py` başlığı).
    "sync_conflicts": "_attach_sync_conflicts",
    # DEVICE-1 Cihazlar — HƏM oxuyur (siyahı + təsdiq növbəsi + lisenziya
    # sayğacı), HƏM yazır (təsdiqlə / blokla / bərpa et / filialı köçür).
    # Siyahı hər yazıdan sonra YENİDƏN oxunmalıdır və səbəb yalnız sətrin
    # yerini dəyişməsi deyil: təsdiq lisenziya sayğacını BİR artırır və
    # sayğac yenilənməsəydi, admin ardıcıl iki cihaz təsdiqləyəndə ikincidə
    # gözlənilməz «limit doldu» xətası görərdi (bax `controllers/devices.py`).
    "devices": "_attach_devices",
    # CHAT-1 dəstək gələnlər qutuları — İKİ AÇAR, BİR EKRAN SİNFİ və BİR
    # `_attach_*` metodu (üç kataloq ekranı ilə eyni naxış). Fərq ekranın öz
    # `channel` sahəsindədir, açarda deyil — kontroller onu oradan oxuyur.
    # Hər ikisi HƏM oxuyur (söhbət siyahısı), HƏM yazır (cavab, bağla/aç) və
    # hər yazıdan sonra siyahı yenidən oxunur: cavab verilmiş söhbət
    # «Cavablanmamış» süzgəcindən çıxır.
    "internal_requests": "_attach_support_inbox",
    "technical_support": "_attach_support_inbox",
    # Aylıq Cərimə İcmalı (miqrasiya 003) — HƏM oxuyur (dövrlər + nəşr
    # gözləyən sətirlər), HƏM yazır (`publish_batch`). Nəşr olunmuş cərimə
    # `PENDING_REVIEW`-dan çıxır, yəni siyahı hər göndərmədən sonra yenidən
    # oxunmalıdır (bax `controllers/fine_review.py` başlığı).
    "fine_review": "_attach_fine_review",
}

#: Həm `_binders()`-də, HƏM DƏ `_attach_*` ilə bağlanan açarlar.
#:
#: «Yardım Mərkəzi» belədir: mövzu siyahısı YALNIZ oxudur (`_help` onu
#: modul açarlarına görə süzür), «Dəstəyə yaz» düyməsi isə mövcud üzən
#: dəstək panelini açır — yəni ekranın yazı yolu ÖZ kontrollerini tələb
#: etmir, sadəcə bir siqnal bağlanır.
#: «Sistem Sağlamlığı» də belədir: bütün göstəricilər `_health` binder-indən
#: gəlir, `[Yenidən Yoxla]` düyməsi isə həmin binder-i təkrar çağırır — ayrıca
#: kontroller bir sətirlik yenidən-oxuma üçün lazımsız qat olardı.
#: «İstifadəçi İdarəetməsi» də belədir (kompasos11.md Faza 4, #7): cədvəl
#: `_users` binder-indən oxunur, "···" menyusunun YALNIZ "POS Səlahiyyəti"
#: bəndi isə `UsersPOSThresholdController`-ə bağlanır — qalan üç maddə
#: (`reset_pin`, `reset_password`, `change_role`, `deactivate`) bu Faza-nın
#: əhatəsindən kənardır və əvvəlki kimi kontrollersiz qalır.
#: «Növbə Planlama» da belədir (kompasos11.md Faza 6, #16): aylıq matris
#: `_shift_planning` binder-indən oxunur və O DƏYİŞMİR, ekrana ƏLAVƏ edilmiş
#: "Açıq Növbə Bazarı" kartı isə həm oxuyur, həm yazır (elan et / ləğv et) və
#: hər yazıdan sonra siyahını yenidən oxuyur — ona görə ÖZ kontrolleri var
#: (bax `controllers/open_shift.py` başlığı).
#: «İdarə Paneli» də belədir (#24, kompasos11.md Faza 9A): beş köhnə bölmə
#: `_dashboard` binder-indən DƏYİŞMƏDƏN oxunur, Çox-Mağaza Benchmark
#: dörd bölməsi isə ƏLAVƏ olaraq dropdown/drill-down SİQNALLARINI qoşur
#: (yazı YOXDUR, YALNIZ metrik dəyişəndə YENİDƏN oxu və naviqasiya) — ona
#: görə ÖZ kontrolleri yox, YALNIZ bir `_attach_*` siqnal bağlaması var
#: (bax `app.py::_attach_dashboard_benchmark` başlığı).
#: «Aylıq Hesabatlar» da belədir (kompas1.md Faza 8): dövr etiketi və LOCK
#: xülasəsi (72 saatlıq etiraz pəncərəsi) `_reports` binder-indən DƏYİŞMƏDƏN
#: oxunur, ekrana ƏLAVƏ edilmiş pre-export doğrulama bölməsi isə həm oxuyur,
#: həm yazır (manual düzəliş) və hər yazıdan sonra siyahını yenidən oxuyur —
#: ona görə ÖZ kontrolleri var (bax `controllers/report_export.py` başlığı).
HYBRID_BOUND: Final[dict[str, str]] = {
    # Tapşırıqlar: ilkin doldurma `screen_data`-dan, təsdiq/rədd isə öz
    # kontrollerindən — hər qərardan sonra lövhə yenidən oxunur.
    "tasks": "_attach_task_review",
    # Satış Xalları: balans/tarixçə `screen_data`-dan, mükafat sorğusu və
    # etiraz isə öz kontrollerindən — hər yazıdan sonra üçü də yenilənir.
    "sales_points": "_attach_sales_points",
    # Audit: ilkin doldurma `screen_data`-dan, süzgəc/səhifələmə isə öz
    # kontrollerindən gəlir — ekran yalnız oxuyur, lakin TƏKRAR oxuyur.
    "audit": "_attach_audit_log",
    "help": "_attach_help_center",
    "health": "_attach_health",
    "users": "_attach_users_pos_threshold",
    "shift_planning": "_attach_open_shift_market",
    "dashboard": "_attach_dashboard_benchmark",
    "reports": "_attach_report_export",
    # Aşağıdakı ÜÇÜ dövrə-4 auditində əlavə olundu. Hər üçü `_binders()`-də
    # ARTIQ VAR idi (yəni ekran DOLURDU), lakin `_attach_*` bağlaması YOX idi
    # — düymələr siqnal yayırdı, dinləyən yox idi:
    #
    #   * `fine_appeals` — «Qəbul Et»/«Rədd Et»: işçinin REAL PUL kəsintisinə
    #     qarşı etirazı heç vaxt qərar almırdı və 72 saat sonra «HR cavab
    #     vermədi» statusuna düşürdü;
    #   * `daily_roster` — «Tabeli Təsdiqlə»: imzasız tabel norma üstü saatları
    #     `overtime_log`-a yazdırmır;
    #   * `shift_swaps` — «Təsdiqlə»/«Rədd Et»: sorğu `PENDING` qalır, matris
    #     köhnə qalır və işçi razılaşdığı gün üçün planlaşdırılmış görünür.
    "fine_appeals": "_attach_fine_appeals",
    "daily_roster": "_attach_daily_roster",
    "shift_swaps": "_attach_shift_swaps",
}

#: Kontrolleri olmayan, lakin örtüyə birbaşa bağlanan ekran: Ayarlar temanı
#: seçir və seçim `user_preferences`-ə yazılır (bölmə 9).
THEME_BOUND: Final[dict[str, str]] = {"settings": "_attach_settings"}

#: `_attach_*` bağlamalarının axtarıldığı funksiyalar.
#:
#: Bağlama cədvəli `_register_screens`-dən `_attach_write_controller`-ə
#: köçürüldü (12-dən çox ekran `elif` zəncirini oxunmaz edirdi), lakin
#: QAPININ MƏNASI dəyişmir: ekran qurulan yolda hər kontroller-bağlı açarın
#: `_attach_*` metodu görünməlidir. İkisini birlikdə skan edirik ki, gələcəkdə
#: bağlama yenidən `_register_screens`-ə qayıtsa da test işləsin.
ATTACH_SCAN_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"_register_screens", "_attach_write_controller"}
)

#: HƏLƏ CANLI BAĞLANMAMIŞ açarlar.
#:
#: SİYAHI ARTIQ BOŞDUR — `app.py`-dakı 29 ekran açarının HAMISI ya
#: `_binders()`-dədir, ya da öz `_attach_*` kontrollerinə bağlanıb. Boş
#: frozenset SİLİNMİR: o, qapının ÖZÜDÜR. Yeni ekran əlavə edən adam ya onu
#: bağlamalı, ya da bura yazıb səbəbini izah etməlidir — hər iki halda qərar
#: kod-review-də GÖRÜNÜR olur. Siyahını silsək, növbəti bağlanmamış ekran
#: yenidən sükutla keçərdi (məhz bu testin yarandığı hal).
#:
#: 29-cu ekran (`exceptions`, #9 — kompasos11.md Faza 5) `CONTROLLER_BOUND`-a
#: əlavə olunub, buraya YOX — `PluginScreen`/`DashboardBuilderScreen` ilə eyni
#: səbəbdən öz kontrolleri var (bax `controllers/exceptions.py` başlığı).
PENDING_LIVE_BINDING: Final[frozenset[str]] = frozenset()


def _app_tree() -> ast.Module:
    return ast.parse(APP_PY.read_text(encoding="utf-8"))


def _register_screens() -> ast.FunctionDef:
    for node in ast.walk(_app_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == "_register_screens":
            return node
    pytest.fail("`app.py`-da `_register_screens` tapılmadı")


def _factory_keys() -> set[str]:
    """`app.py`-dakı `factories` sözlüyünün açarları."""
    for node in ast.walk(_register_screens()):
        if not isinstance(node, ast.AnnAssign):
            continue
        target = node.target
        if isinstance(target, ast.Name) and target.id == "factories":
            assert isinstance(node.value, ast.Dict)
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    pytest.fail("`factories` sözlüyü tapılmadı")


def _binder_keys() -> set[str]:
    """`ScreenDataBinder._binders()` açarları — baza/Qt olmadan."""
    binder = ScreenDataBinder(None, None)  # type: ignore[arg-type]
    return set(binder._binders())


def test_every_screen_key_is_either_bound_or_explicitly_pending() -> None:
    """Əhatə olunmayan açarlar dəsti SƏNƏDLƏŞDİRİLMİŞ siyahı ilə eyni olmalıdır.

    Yeni ekran əlavə olunanda bu test qırılır — bu, məqsəddir: qərar ("indi
    bağlayıram" / "Faza 6-ya qalır") kod-review-də görünsün.
    """
    covered = _binder_keys() | set(CONTROLLER_BOUND) | set(HYBRID_BOUND) | set(THEME_BOUND)
    unbound = _factory_keys() - covered

    assert unbound == set(PENDING_LIVE_BINDING), (
        "Canlı bağlaması olmayan ekran açarları dəyişib — "
        f"əlavə: {sorted(unbound - PENDING_LIVE_BINDING)}, "
        f"artıq bağlanıb: {sorted(PENDING_LIVE_BINDING - unbound)}"
    )


def test_documented_keys_still_exist_in_app() -> None:
    """Siyahılar `app.py`-dan silinmiş açarı daşımamalıdır (ölü sənəd)."""
    keys = _factory_keys()
    documented = (
        set(PENDING_LIVE_BINDING) | set(CONTROLLER_BOUND) | set(HYBRID_BOUND) | set(THEME_BOUND)
    )
    stale = documented - keys
    assert not stale, f"Bu açarlar artıq `factories`-də yoxdur: {sorted(stale)}"


def _attached_methods() -> set[str]:
    """Ekran qurma yolundakı bütün `self._attach_*` istinadları.

    `Call` DEYİL, `Attribute` axtarılır: bağlama cədvəlində metod ÇAĞIRILMIR,
    istinad kimi saxlanılır (`(ScreenType, self._attach_x)`) və sonra
    dövrədə çağırılır. Çağırışa görə axtarsaydıq cədvəldəki hər sətir
    "bağlanmayıb" görünərdi.
    """
    wanted = ATTACH_SCAN_FUNCTIONS
    found: set[str] = set()
    for node in ast.walk(_app_tree()):
        if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
            continue
        found |= {
            value.attr
            for value in ast.walk(node)
            if isinstance(value, ast.Attribute) and value.attr.startswith("_attach_")
        }
    # Dispetçerin ÖZÜ bağlama deyil — `_register_screens` onu çağırır.
    return found - wanted


def test_controller_bound_screens_are_still_attached_in_app() -> None:
    """Hər kontroller-bağlı açarın `_attach_*` metodu ekran yolunda qalmalıdır.

    Biri silinsə, ekran sükutla "yalnız oxu"ya düşərdi və düymələr heç bir
    şeyə bağlanmazdı — istifadəçi basar, heç nə baş verməz.
    """
    called = _attached_methods()
    expected = (
        set(CONTROLLER_BOUND.values()) | set(HYBRID_BOUND.values()) | set(THEME_BOUND.values())
    )
    assert called == expected, (
        f"Ekran qurma yolundakı kontroller bağlamaları dəyişib: {sorted(called)}"
    )


# --------------------------------------------------------------------------- #
# `populate()` artıq SƏSSİZ keçmir
# --------------------------------------------------------------------------- #


class _LogRecorder:
    """`_error_log` əvəzi — kanal konfiqurasiyasına toxunmadan çağırışı tutur."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, Any]]] = []

    def warning(self, message: str, *, extra: dict[str, Any] | None = None) -> None:
        self.warnings.append((message, extra or {}))


def test_missing_binder_logs_a_warning_and_does_not_raise(monkeypatch: Any) -> None:
    """Davranış eynidir (istisna yox), lakin artıq İZ QALIR."""
    from src.presentation.controllers import screen_data

    recorder = _LogRecorder()
    monkeypatch.setattr(screen_data, "_error_log", recorder)

    binder = screen_data.ScreenDataBinder(None, None)  # type: ignore[arg-type]
    # `screen` heç vaxt toxunulmur — bağlama tapılmadıqda funksiya geri qayıdır.
    # Açar `PENDING_LIVE_BINDING`-dən götürülüb: bağlanmış ekran (məs.
    # `dashboard`) burada sessiya açmağa cəhd edərdi.
    binder.populate("plugins", None)  # type: ignore[arg-type]

    assert recorder.warnings == [
        (
            "SCREEN_BINDER_MISSING",
            {
                "screen": "plugins",
                "impact": "ekran boş qalır — canlı bağlama hələ yazılmayıb",
            },
        )
    ]


def test_every_pending_screen_leaves_a_trace(monkeypatch: Any) -> None:
    """Sənədləşdirilmiş boşluqların HAMISI jurnalda görünür."""
    from src.presentation.controllers import screen_data

    recorder = _LogRecorder()
    monkeypatch.setattr(screen_data, "_error_log", recorder)

    binder = screen_data.ScreenDataBinder(None, None)  # type: ignore[arg-type]
    for key in sorted(PENDING_LIVE_BINDING):
        binder.populate(key, None)  # type: ignore[arg-type]

    logged = {extra["screen"] for _, extra in recorder.warnings}
    assert logged == set(PENDING_LIVE_BINDING)
