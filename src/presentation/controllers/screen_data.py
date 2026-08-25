"""Ekranların CANLI məlumatla doldurulması (Faza 5/6).

`preview_screens.populate()` maketdəki nümunə məzmunu yazır; bu modul eyni
işi REAL use case nəticələri ilə görür. İkisi eyni imzaya malikdir
(`populate(key, screen)`), ona görə `app.py` yalnız hansını çağıracağını
seçir — ekran fabrikaları toxunulmaz qalır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR EKRAN AYRI FUNKSİYADIR
──────────────────────────────────────────────────────────────────────────────
Hər ekranın öz setter imzası var (`set_entries`, `set_users`, `set_rows`, ...)
və onları ümumi bir interfeysə salmaq cəhdi hər ekranı süni bir adapterlə
yükləyərdi. Ayrı funksiya = ayrı imza = tip yoxlayıcısı səhvi burada tutur.

──────────────────────────────────────────────────────────────────────────────
XƏTA EKRANI BOŞ QOYUR, ÇÖKDÜRMÜR
──────────────────────────────────────────────────────────────────────────────
`populate()` hər doldurucunu `try/except` içində çağırır. Səbəb: bir ekranın
sorğusundakı problem (məs. `store_id` təyin edilməyib) BÜTÜN örtüyü
çökdürməməlidir — istifadəçi digər bölmələrdə işləməyə davam edə bilməlidir.
Səbəb `error.log`-a düşür və boş ekran özü də siqnaldır.

──────────────────────────────────────────────────────────────────────────────
BOŞ EKRAN ARTIQ «MƏLUMAT YOXDUR» DEMİR
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı fail-soft davranış SAXLANILIR — bir bölmənin sınması örtüyü
çökdürmür. Lakin əvvəl istisna YALNIZ `error.log`-a düşürdü və istifadəçi
üçün «yüklənə bilmədi» ilə «məlumat yoxdur» EYNİ görünürdü: hər ikisi boş
ekran idi. Real qüsur məhz bu boşluqda aylarla yaşadı — sorğu
`fine_types.name` sütununu oxuyurdu (`name_az` olmalı idi), `UndefinedColumn`
udulurdu, «Cərimələr» ekranı isə həmişə boş idi və heç kim şikayət etmədi.

İndi hər tutulmuş istisna jurnala ƏLAVƏ OLARAQ ekranda görünən iz qoyur:
`report_section_error()` ekranın `set_section_error()` metodunu çağırır
(`screens/base.py`) və istifadəçi hansı bölməyə inanmayacağını bilir. Metod
`getattr` ilə axtarılır — onu daşımayan ekran (və ya `None`) sadəcə köhnə
davranışı saxlayır, yəni heç bir mövcud imza pozulmur.

QİSMƏN UĞUR ƏN TƏHLÜKƏLİ HALDIR: İdarə Panelinin yeddi bölməsindən biri
sınarsa qalan altısı DÜZGÜN qalır, sınan isə AÇIQ işarələnir. Sükutla boş
qalan sayğac istifadəçiyə «0 cərimə»ni HƏQİQƏT kimi göstərir və bu, yanlış
qərara aparır.

──────────────────────────────────────────────────────────────────────────────
BAĞLAMASI OLMAYAN AÇAR DA İZ QOYUR
──────────────────────────────────────────────────────────────────────────────
`app.py` `_binders()`-dəkindən ÇOX ekran açarı qeydiyyatdan keçirir. Əvvəl
naməlum açar sükutla keçilirdi — nə istisna, nə jurnal sətri, yəni əskik
bağlama YALNIZ istifadəçi boş ekran görəndə üzə çıxırdı. İndi həmin hal
`SCREEN_BINDER_MISSING` xəbərdarlığı verir; davranış eynidir (ekran boş
qalır, örtük çökmür), lakin qüsur ölçülə bilən hala gəlir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Generic, TypeVar

from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.identifiers import StoreId
from src.presentation.controllers.audit_log import entry_row
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

    from src.application.use_cases.multi_store_benchmark import BenchmarkMetric
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

# --------------------------------------------------------------------------- #
# Bölmə adları — İSTİFADƏÇİ dilində
# --------------------------------------------------------------------------- #
# NİYƏ SABİT, NİYƏ ÇAĞIRIŞ YERİNDƏ SƏTİR DEYİL: eyni ad həm bannerdə, həm
# jurnal sətrində görünür. Dəstək zəngində istifadəçi «Xülasə sayğacları
# yüklənmədi» deyir və admin `error.log`-da MƏHZ həmin adı axtarır — iki yerdə
# iki fərqli ad bu zənciri qırardı. Texniki ad (`_dashboard_summary`) ekrana
# ÇIXMIR: istifadəçi kodun daxili adlarını görməməlidir.

SECTION_SCREEN: Final = "Ekran məlumatları"
SECTION_DASHBOARD_SUMMARY: Final = "Xülasə sayğacları"
SECTION_DASHBOARD_NETWORK: Final = "Şəbəkənin ölçüsü"
SECTION_DASHBOARD_FINES: Final = "Filial üzrə cərimələr"
SECTION_DASHBOARD_LEAVE: Final = "İcazə ölçəni"
SECTION_DASHBOARD_LEADERS: Final = "Xal liderləri"
SECTION_DASHBOARD_HEALTH: Final = "Server sağlamlığı"
SECTION_DASHBOARD_BENCHMARK: Final = "Mağaza reytinqi"
SECTION_DASHBOARD_BREAKS: Final = "Fasilə həddini aşanlar"
SECTION_DAILY_ROSTER: Final = "Gündəlik tabel"
SECTION_HEALTH_OFFLINE: Final = "Offline bufer sayğacı"
SECTION_HEALTH_CONFLICTS: Final = "Sinxronizasiya konflikti sayğacı"
SECTION_HEALTH_ALERTS: Final = "Kritik bildirişlər"
SECTION_QUEUE_FACE_BADGES: Final = "Üz-təsdiq nişanları"


def report_section_error(screen: Any, section_label: str) -> None:
    """Sınmış bölməni EKRANDA görünən edir — jurnal yazısına ƏLAVƏ olaraq.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `getattr`, NİYƏ BİRBAŞA ÇAĞIRIŞ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Doldurucular `screen: Any` alır: maket yolu (`preview_screens`), canlı yol
    və testlərdəki duck-typing saxtaları eyni funksiyalara girir. Birbaşa
    `screen.set_section_error(...)` çağırışı metodu daşımayan hər obyektdə
    `AttributeError` atardı — yəni XƏTANI GÖRÜNƏN ETMƏK CƏHDİ ikinci bir xəta
    yaradardı. `Screen` bazasındakı metod varsa işləyir, yoxdursa davranış
    əvvəlki kimi qalır (yalnız jurnal).

    Bannerin özü də sınarsa (Qt obyekti artıq silinib və s.) istisna BURADA
    dayanır: xəbərdarlıq mexanizmi əsas axını çökdürə bilməz.
    """
    reporter = getattr(screen, "set_section_error", None)
    if reporter is None:
        return
    try:
        reporter(section_label)
    except Exception:
        _error_log.exception("SECTION_ERROR_BANNER_FAILED", extra={"section": section_label})


#: Növbə/təqvim görünüşlərində göstərilən dövr.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits.SHIFT_MATRIX_WINDOW_DAYS`
#: (seed: migrations/035) və hədd hər dəfə ondan oxunur (bax
#: `matrix_window_days()`). 21 filialın planlama ritmi eyni deyil: kimisi
#: həftəlik, kimisi aylıq planlayır. Sabit YALNIZ limit oxuna bilmədikdə işə
#: düşür — onu silmək "limit yoxdursa matris də yoxdur" davranışı yaradardı.
FALLBACK_MATRIX_WINDOW_DAYS = int(DEFAULT_LIMITS[SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS])

#: Çox-Mağaza Reytinq Cədvəlinin DRILL-DOWN hədəfi (#24, Faza 9A) — mövcud
#: "Gündəlik Tabel" ekranının `AdminShell`-dəki açarı (bax `shell/menu.py`).
DAILY_ROSTER_SCREEN_KEY: Final = "daily_roster"

#: «Aşağı-etibarlı üz təsdiqi» nişanının geriyə baxış pəncərəsi (gün).
#:
#: ROOT PARAMETRİ DEYİL VƏ BU, QƏSDLİDİR: pəncərə yalnız SORĞU həddidir —
#: nişan onsuz da yalnız növbədə DAYANAN sətirlərə düşür və növbənin öz ömrü
#: 45 dəqiqəlik timeout ilə məhduddur (`face_control.MISMATCH_LOOKBACK_DAYS`
#: ilə eyni əsaslandırma). Gecə növbəsinin gün sərhədini keçməsi üçün bir gün
#: kifayətdir.
LOW_CONFIDENCE_LOOKBACK_DAYS: Final = 1

#: Növbə dəyişmə statusu → ekran mətni.
_SWAP_STATUS_TEXT: Final[dict[str, str]] = {
    "PENDING_APPROVAL": "Gözləyir",
    "APPROVED": "Təsdiqlənib",
    "REJECTED": "Rədd edilib",
}

#: Növbə matrisinin sütun başlıqları. `strftime("%a")` sistem lokalından
#: asılıdır və Windows-da ingiliscə qaytarır — interfeys dili isə yalnız
#: Azərbaycan dilidir (bölmə 9).
_WEEKDAYS_AZ: Final = ("B.e", "Ç.a", "Çər", "C.a", "Cüm", "Şən", "Baz")

#: Bu qədər dəqiqədən sonra növbə sətri xəbərdarlıq rəngində göstərilir.
#: 45 dəqiqəlik timeout-un (bölmə 4) YARISI seçilib — operator eskalasiya
#: baş verməmişdən əvvəl reaksiya verə bilsin.
#:
#: DİQQƏT: bu, YALNIZ FALLBACK-dır. Həqiqi mənbə
#: `system_limits.VERIFICATION_TIMEOUT_MINUTES`-dir (bölmə 3, Root idarə edir)
#: və hədd hər dəfə ondan hesablanır — bax `late_threshold_minutes()`. Sabit
#: yalnız limit oxuna bilmədikdə işə düşür; onu silmək "limit yoxdursa
#: xəbərdarlıq da yoxdur" davranışı yaradardı.
LATE_QUEUE_MINUTES = 22

#: `v_erp_server_health.health` → dashboard kartındakı ton.
#:
#: `INACTIVE` siyahıda YOXDUR, çünki həmin sətirlər sorğuda süzülür (bax
#: `_dashboard_health`). Naməlum dəyər "warning"a düşür: yeni bir sağlamlıq
#: vəziyyəti əlavə olunarsa onu SÜKUTLA yaşıl göstərmək ən pis hal olardı.
_HEALTH_TONES: Final[dict[str, str]] = {
    "HEALTHY": "success",
    "DEGRADED": "warning",
    "STALE": "warning",
    "NEVER_SYNCED": "danger",
}

#: Yardım mövzusu → onu görünən edən modul açarı (`FeatureModule` dəyəri).
#:
#: `None` = modula bağlı DEYİL. «1C / ERP bağlantısı» belədir: ERP inteqrasiyası
#: Feature Toggle ilə söndürülən bir modul deyil, quraşdırma addımıdır — onun
#: təlimatını gizlətmək serveri qura bilməyən müştərini məhz lazım olan anda
#: köməksiz qoyardı. «Problem yaşayırsınızsa» mövzusu isə `SUPPORT_CHAT`-a
#: bağlıdır, çünki mətnin özü dəstək düyməsini göstərir.
HELP_TOPIC_MODULES: Final[dict[str, str | None]] = {
    "leave": FeatureModule.CAMERA_VERIFICATION.value,
    "fines": FeatureModule.FINE_MODULE.value,
    "shifts": FeatureModule.SHIFT_SWAP.value,
    "erp": None,
    "points": FeatureModule.SALES_POINTS.value,
    "support": FeatureModule.SUPPORT_CHAT.value,
}


@dataclass(frozen=True, slots=True)
class SectionFailure:
    """Bir bölmənin `fetch` mərhələsində uğursuz olduğunu bildirir (PERF-6 Qərar 2).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ VAR — `report_section_error(screen, …)` FETCH-İN DAXİLİNDƏN ÇAĞIRILMIR
    ──────────────────────────────────────────────────────────────────────────
    `fetch` fon sapına köçürüləcək (FAZA D) və Qt-yə TOXUNA BİLMƏZ
    (`background_task.py`-nın qaydası). Əvvəl `_health`in beş köməkçisi
    (`_health_metrics`, `_offline_pending`, `_open_conflicts_or_none`,
    `_health_alerts`, `_critical_notifications`) HƏRƏSİ ÖZ uğursuzluğunda
    BİRBAŞA `report_section_error(screen, label)` çağırırdı. Bu tip onun
    ƏVƏZİNƏ qayıdır: `fetch` `SectionFailure(section=SECTION_X)` qaytarır,
    `apply` (ƏSAS SAPDA) bunu görüb `report_section_error`-u ÖZÜ çağırır.

    ÜÇ YERDƏ İSTİFADƏ ÜÇÜN NƏZƏRDƏ TUTULUB (SƏNƏDLƏŞDİRİLİB, HAMISI EYNİ
    ANDA KÖÇMƏYİB): `_health`in beş köməkçisi (indi), `_live_queue::
    _low_confidence_faces` (hazırda öz sadə `bool` bayrağı ilə işləyir —
    BU FORMAYA MƏCBURİ keçmir, işləyən kod dəyişdirilmədi) və FAZA D-də
    `_fill_section` (dashboard-ın səpələnmiş bölmə banner-lərini EYNİ
    mexanizmə yığmaq üçün).

    `section` `SECTION_*` sabitlərindən biridir — `report_section_error`-un
    GÖZLƏDİYİ eyni etiket (məs. `SECTION_HEALTH_OFFLINE`).
    """

    section: str


_SectionT = TypeVar("_SectionT")


@dataclass(frozen=True, slots=True)
class SectionResult(Generic[_SectionT]):
    """Bir bölmənin `fetch` NƏTİCƏSİ — `data` YA `failure`, HEÇ VAXT İKİSİ BİRLİKDƏ (FAZA D).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ VAR — `_fill_section`-un FETCH/APPLY-A BÖLÜNMƏSİ (Qərar 2, variant b)
    ──────────────────────────────────────────────────────────────────────────
    Köhnə `_fill_section(screen, *, label, event, fill)` `fill: Callable[[],
    None]`-u try/except-ə salırdı və Qt çağırışını (`report_section_error`)
    İÇƏRİDƏ edirdi — `fetch`-in Qt-yə TOXUNMAMASI tələbini pozurdu. `Screen
    DataBinder._fill()` bunun ƏVƏZİNƏ bu tipi qaytarır: `fetch()` sınarsa
    `failure` dolur, uğurlu olsa (`None` daxil — bax aşağı) `data` dolur.
    `ScreenDataBinder._apply_section()` bunu görüb YA `apply(data)`, YA
    `report_section_error(screen, failure.section)` çağırır — ƏSAS SAPDA.

    `data=None, failure=None` DA MÜMKÜNDÜR (məs. `_dashboard_benchmark`-ın
    icazə-əsaslı gizlənməsi): bölmə sadəcə HEÇ NƏ göstərmir — nə xəta, nə
    məzmun, `_fill_section`-un "icazə yoxdursa `set_*` çağırılmır" köhnə
    davranışının DƏQİQ TƏKRARI.

    ÜÇ yerdə istifadə üçün nəzərdə tutulub (bax `SectionFailure` başlığı):
    `_dashboard`-ın SƏKKİZ bölməsi (indi), `_health` (öz `*_failure`
    sahələrini artıq işlədir — BURAYA KEÇMƏDİ, çünki banner sırası ÜÇ AYRI
    sahə ilə DAHA AYDIN ifadə olunur), `_live_queue` (öz sadə bayrağını
    saxlayır, MƏCBURİ deyil).
    """

    data: _SectionT | None = None
    failure: SectionFailure | None = None


@dataclass(frozen=True, slots=True)
class _NoInputs:
    """`inputs` mərhələsinin BOŞ nəticəsi — PERF-6 FAZA B (bax `ScreenDataBinder`).

    `None` ƏVƏZİNƏ İŞLƏDİLİR: `strict` mypy `-> None` elan edən funksiyanın
    nəticəsini dəyişənə mənimsətməyi `func-returns-value` kimi işarələyir (adətən
    unudulmuş `return` əlamətidir) — `_fines_inputs`/`_help_inputs` bu xəbərdarlığı
    real verdi. `_NoInputs()` HƏMİŞƏ eyni, yüngül instansiyadır: "bu binder-in
    inputs-u YOXDUR" faktını tip sistemində AÇIQ saxlayır, mypy-ı çaşdırmadan.
    """


@dataclass(frozen=True, slots=True)
class _LiveQueueData:
    """`_live_queue_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat.

    `entries` `list[Any]`-dir (`QueueEntry`-lərin siyahısı), çünki `QueueEntry`
    sinfi ekran modulundan (`screens/group_b.py`) yalnız `_live_queue_fetch`-in
    DAXİLİNDƏ, tənbəl idxal olunur (bax `ScreenDataBinder`-in mövcud üslubu) —
    modul səviyyəsində idxal etmək bu faylı ekran qatına ƏLAVƏ bağlayardı.
    """

    entries: list[Any]
    low_confidence_failed: bool


@dataclass(frozen=True, slots=True)
class _FinesData:
    """`_fines_fetch`-in nəticəsi (PERF-6 FAZA B) — saf məlumat, Qt OBYEKTİ DEYİL.

    `screen.set_fines(...)`-in üç arqumentini BİR YERDƏ daşıyır ki, `_fines_
    fetch`/`_fines_apply` arasında sap sərhədini keçəndə (FAZA D) heç nə
    unudulmasın — üç ayrı dəyişən ötürülsəydi biri sükutla düşə bilərdi.
    """

    rows: list[dict[str, str]]
    period_text: str
    total_text: str


@dataclass(frozen=True, slots=True)
class _ShiftSwapsData:
    """`_shift_swaps_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    pending_count: int
    rows: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class _ShiftStaffingPatternData:
    """`_shift_staffing_pattern_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    rows: list[tuple[str, str]]
    store_name: str
    based_on_weeks: int
    calculated_label: str


@dataclass(frozen=True, slots=True)
class _ShiftPlanningData:
    """`_render_shift_matrix_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat.

    `staffing` iç-içədir: köhnə kodda `_render_shift_matrix` sonunda
    `_shift_staffing_pattern`-i BİRBAŞA çağırırdı (İKİ ARDICIL bölmə, TƏK
    `fill()` daxilində) — indi eyni ardıcıllıq `fetch`-in ÖZÜNDƏ saxlanılır.
    """

    window_label: str
    days: list[tuple[int, str]]
    rows: list[tuple[str, list[str]]]
    staffing: _ShiftStaffingPatternData


@dataclass(frozen=True, slots=True)
class _TasksData:
    """`_tasks_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    summary: str
    review: list[dict[str, str]]
    open_column: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class _SalesPointsData:
    """`_sales_points_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat.

    `screen.set_balance`/`set_history`/`set_catalog`-un ÜÇ ayrı çağırışını
    BİR yerdə daşıyır — bax `_FinesData`-dakı EYNİ əsaslandırma.
    """

    available: int
    monthly_delta: int
    to_next_reward: int
    next_reward_cost: int
    rank_text: str
    history: list[dict[str, str]]
    history_period: str
    catalog: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class _AuditData:
    """`_audit_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    entries: list[dict[str, str]]
    result_text: str


@dataclass(frozen=True, slots=True)
class _ReportsData:
    """`_reports_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    period_text: str
    deferred_fine_count: int
    already_exported: int
    overlap_notice: str


@dataclass(frozen=True, slots=True)
class _DashboardNetworkData:
    """`_dashboard_network_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat.

    `None` = sətir gəlmədi (`pragma: no cover` — `count(*)` həmişə sətir
    qaytarır, bax fetch-in şərhi) — `apply` bu halda HEÇ NƏ çağırmır.
    """

    employees: int | None
    stores: int | None


@dataclass(frozen=True, slots=True)
class _DashboardSummaryData:
    """`_dashboard_summary_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    in_store: int
    planned: int
    pending: int
    longest_wait: str
    fines_total: str
    fines_delta: str
    open_tasks: int
    overdue_tasks: int


@dataclass(frozen=True, slots=True)
class _DashboardFinesData:
    """`_dashboard_fines_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    rows: list[tuple[str, float, str]]
    period: str


@dataclass(frozen=True, slots=True)
class _DashboardLeaveData:
    """`_dashboard_leave_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    used: float
    budget: float


@dataclass(frozen=True, slots=True)
class _DashboardLeadersData:
    """`_dashboard_leaders_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    leaders: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class _DashboardHealthData:
    """`_dashboard_health_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    rows: list[tuple[str, str, str]]


@dataclass(frozen=True, slots=True)
class _BenchmarkComparison:
    """`screen.set_store_vs_network(...)`-un YEDDİ arqumenti — saf məlumat.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `dict[str, Any]` DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl bura `dict[str, Any]` idi və `apply` onu `screen.set_store_vs_
    network(**data.comparison)` ilə açırdı — layihədə `**` ilə setter çağıran
    YEGANƏ yer idi (qadağan edilib). Səbəb: açar adı sürüşsə heç bir qapı
    tutmur — AST testi `**`-i GÖRMÜR (`keyword.arg` `None` olur), mypy isə
    `dict[str, Any]` açılışını YOXLAMIR. Nəticə udulan `TypeError` + boş
    ekran olardı (`_audit_apply`-ın şərhindəki EYNİ qüsur sinfi). Frozen
    dataclass-a keçəndə HƏR İKİ qapı işə düşür: mypy sahə adlarını, AST
    testi isə açıq `screen.set_store_vs_network(metric_label=..., …)`
    çağırışının setter imzasına uyğunluğunu yoxlayır.
    """

    metric_label: str
    store_label: str
    store_value: float
    store_display: str
    network_label: str
    network_value: float
    network_display: str


@dataclass(frozen=True, slots=True)
class _DashboardBenchmarkData:
    """`_dashboard_benchmark_fetch`-in nəticəsi (PERF-6 FAZA C, ORTA) — saf məlumat.

    Köhnə kodda DÖRD bölmə ARDICIL fetch+apply cütü idi (`_populate_
    benchmark_sections`) — indi hamısı BİR fetch-də toplanır. `comparison`
    `None`-dur, əgər `ranking` BOŞDURSA (bax fetch-in şərhi: defolt müqayisə
    YALNIZ sıralama boş olmayanda hesablanır) — `apply` bu halda `set_store_
    vs_network`-i ÇAĞIRMIR, köhnə davranışla EYNİ.
    """

    ranking: list[Any]
    metric_options: list[tuple[str, str]]
    selected_metric: str
    comparison: _BenchmarkComparison | None
    metric_label: str
    trend_points: list[tuple[str, float, str]]
    outliers_summary: str
    outliers_rows: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class _DashboardData:
    """`_dashboard_fetch`-in nəticəsi (PERF-6 FAZA D) — SƏKKİZ bölmənin HƏR
    BİRİ MÜSTƏQİL `SectionResult`-dur.

    Sahə SIRASI `_dashboard_apply`-ın çağırış sırası ilə EYNİDİR (bax onun
    şərhi) — köhnə `_fill_section` çağırışlarının sırasının DƏQİQ TƏKRARI,
    banner sırasının qorunması buna görədir.
    """

    summary: SectionResult[_DashboardSummaryData]
    network: SectionResult[_DashboardNetworkData]
    fines: SectionResult[_DashboardFinesData]
    leave: SectionResult[_DashboardLeaveData]
    leaders: SectionResult[_DashboardLeadersData]
    health: SectionResult[_DashboardHealthData]
    benchmark: SectionResult[_DashboardBenchmarkData]
    breaks: SectionResult[list[tuple[str, str]]]


@dataclass(frozen=True, slots=True)
class _UsersInputs:
    """`_users_inputs`-in nəticəsi (PERF-6 FAZA C) — ƏSAS SAPDA Qt-dən oxunub.

    `status_filter` `UsersScreen.status_filter()`-in XAM qaytardığı sətirdir —
    SQL-ə birbaşa getmir, `_users_fetch` onu SABİT `WHERE` siyahısından
    (CLAUDE.md §4) birinə uyğunlaşdırır. Bu, `_NoInputs` OLMAYAN İLK binder-dir
    (bax `_users` başlığı) — naxışın ÜÇÜNCÜ mərhələsinin mövcudluq səbəbi.
    """

    status_filter: str


@dataclass(frozen=True, slots=True)
class _UsersData:
    """`_users_fetch`-in nəticəsi (PERF-6 FAZA C) — saf məlumat."""

    permitted_actions: frozenset[str]
    rows: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class _HealthData:
    """`_health_fetch`-in nəticəsi (PERF-6 FAZA C, RİSKLİ) — saf məlumat.

    Uğursuzluq sahələri (`*_failure`) AYRI-AYRI saxlanılır, TƏK siyahıya
    yığılmır — `_health_apply`-ın banner ÇAĞIRIŞLARINI köhnə kodla EYNİ SIRADA
    (müvafiq `screen.set_*`-dən DƏRHAL ƏVVƏL) verə bilməsi üçün (bax `_health`
    başlığı: "banner sırası qorunur").
    """

    last_check_text: str
    conflicts_failure: SectionFailure | None
    metrics: list[tuple[str, str, str, str]]
    offline_failure: SectionFailure | None
    latencies: list[tuple[str, str, str]]
    alerts: list[tuple[str, str, str]]
    notifications_failure: SectionFailure | None
    conflict_action: int


@dataclass(frozen=True, slots=True)
class _DailyRosterData:
    """`_daily_roster_fetch`/`_daily_roster_for_store_fetch`-in nəticəsi
    (PERF-6 FAZA C, RİSKLİ) — saf məlumat.

    `failure` YALNIZ `populate_daily_roster_for_store`-da işlədilir (bax onun
    başlığı) — `_daily_roster` (binder) istisnanı ÖZÜ TUTMUR, `populate()`-un
    ümumi `SECTION_SCREEN` yoluna buraxır, ona görə HƏMİŞƏ `None`-dur.
    `rows`/`mismatch_text` `failure` `None` OLMAYANDA mənasızdır (boş qalır).
    """

    rows: list[dict[str, str]]
    mismatch_text: str | None
    failure: SectionFailure | None = None


class ScreenDataBinder:
    """Ekran açarına görə canlı məlumat yazır.

    ──────────────────────────────────────────────────────────────────────────
    PERF-6 FAZA B — İNPUTS/FETCH/APPLY NAXIŞI (bütün binder-lər buna keçir)
    ──────────────────────────────────────────────────────────────────────────
    Səbəb: `show_admin()`-in açılışı DB gözləməsinə görə 3.2–13.1 saniyə
    bloklayır (`docs/performance_notes.md`, PERF-6 #3), lakin bu metodların
    ÖZÜ Qt widget-ə TOXUNUR (`screen.set_...`) — `background_task.py`-nın
    «fon işi Qt widget-inə toxunmur» qaydası bir binder-i BÜTÖV halda fon
    sapına verməyi qadağan edir. Naxış sərhədi YARADIR:

        inputs(screen) -> Params       # ƏSAS SAP, YALNIZ Qt OXUYUR (yazmır)
        fetch(session, params) -> Data # FON SAPI, YALNIZ DB (Qt-yə TOXUNMUR)
        apply(screen, data) -> None    # ƏSAS SAP, YALNIZ Qt (DB-yə TOXUNMUR)

    ÜÇ MƏRHƏLƏ, İKİ YOX: `_users` (PERF-6 FAZA A tapıntısı) DB sorğusunun
    WHERE şərtini qurmaq üçün `screen.status_filter()` (Qt getter) çağırır —
    bu, İSTİSNA deyil, naxışın ÇATIŞMAYAN hissəsi idi. `inputs` əksər binder-
    lərdə BOŞ (`None`) qayıdır (bax `_fines_inputs`/`_help_inputs`) — bu,
    problemsiz sabitlikdir, hər binder üçün "iki-mərhələlidirmi, üç-
    mərhələlidirmi?" sualının YENİDƏN verilməsinin qarşısını alır.

    HƏLƏLİK ÜÇÜ DƏ EYNİ (ƏSAS) SAPDA, ARDICIL ÇAĞIRILIR — bu FAZA (B/C)
    `populate()`-un çağırış yerini DƏYİŞMİR, YALNIZ hər binder-in DAXİLİNİ
    üç mərhələyə ayırır. Sap sərhədi (FAZA D) YALNIZ `show_admin()`-in
    açdığı İLK ekran üçün, `app.py`-da qurulacaq: `fetch` `run_job`-a
    veriləcək, `apply` isə ƏSAS SAPDA qalacaq. Digər ekranlar (menyudan
    klik) BU FAZANIN ƏHATƏSİNDƏN KƏNARDADIR — onlar artıq sürətlidir
    (bax `docs/performance_notes.md`, "Panellərin canlı ölçüsü": çəkiliş
    praktik olaraq sıfırdır, YALNIZ İLK ekran örtük qurulmasının ARDINCA
    gəldiyi üçün DONMA yaradır).

    BÖLMƏ XƏTALARI MƏLUMATDIR, ÇAĞIRIŞ DEYİL: `report_section_error(screen,
    …)` `fetch`-in DAXİLİNDƏN ÇAĞIRILMIR (`_health`in köməkçiləri və
    `_live_queue::_low_confidence_faces` bunu FAZA C-də DƏYİŞDİRƏCƏK) — `fetch`
    saf məlumat (məs. "hansı bölmə sınıb" siyahısı) qaytarır, `apply` onu
    bannerə çevirir. Zəmanət DƏYİŞMİR (bir bölmənin sınması qalanlarını
    dayandırmır), yalnız MƏSULİYYƏT yeri dəyişir.

    GİZLİ YAZI QALIR, AMMA ADI ÇƏKİLİR: `_daily_roster`, `populate_daily_
    roster_for_store` və `_audit` `session.commit()` çağırır (gündəlik tabel
    "avtomatik status" YARADIR, audit sorğusunun ÖZÜ audit-lənir — §5-in
    qəsdli zəmanəti). Bu üçü OXU-YALNIZ DEYİL: yazı `fetch` mərhələsində
    QALIR (fon sapında yazı problemsizdir — `_run_scheduled_jobs` da belə
    edir), `apply` isə YENƏ YALNIZ Qt olur. CLAUDE.md-nin "yalnız oxuyan
    ekran `screen_data.py`-a bağlanır" cümləsi ilə bu üç binder arasındakı
    uyğunsuzluq QƏSDƏN saxlanılır (CLAUDE.md-yə bu tapşırıqda TOXUNULMUR).
    """

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: Növbə matrisinin başlanğıc sürüşməsi (gün) — `set_shift_offset`.
        self._shift_offset_days = 0

    def populate(self, key: str, screen: QWidget, *, reraise: bool = False) -> None:
        """Ekranı canlı məlumatla doldurur — bağlaması olmayan açar İZ QOYUR.

        ──────────────────────────────────────────────────────────────────────
        `reraise` NİYƏ VAR (QA-FULL Faza 3 tapıntısı)
        ──────────────────────────────────────────────────────────────────────
        `fine_appeals.py::refresh`, `daily_roster.py::refresh` və
        `shift_window.py::_on_month_changed` `populate()`-u öz `try/except
        KompasOSError` ilə əhatə edib "Yenidən Cəhd Et" düyməli tam-ekran
        mesaj vəd edirdi — LAKİN bu metod hər istisnanı ÖZÜ udurdu
        (`report_section_error` ilə) və heç vaxt yenidən atmırdı, yəni həmin
        qollar İSTEHSALATDA ÇATILMAZ idi. `reraise=True` YALNIZ
        `KompasOSError`-u yenidən atır — digər (gözlənilməz) istisnalar KÖHNƏ
        davranışı saxlayır (bölmə banneri, örtük ayaqda qalır): bir ekranın
        gözlənilməz nasazlığı örtüyü çökdürməməlidir, `KompasOSError` isə artıq
        istifadəçi mesajı daşıyan GÖZLƏNİLƏN domən xətasıdır və çağıran tərəf
        onu mənalı şəkildə göstərə bilər.
        """
        binder = self._binders().get(key)
        if binder is None:
            # DAVRANIŞ DƏYİŞMİR: ekran boş qalır, istisna atılmır, örtük
            # çökmür — `app.py` 28 ekran açarını qeydiyyatdan keçirir, onların
            # bir hissəsinin canlı bağlaması hələ yazılmayıb və bu, planlı
            # vəziyyətdir (bax `tests/unit/test_screen_binding_coverage.py`).
            # DƏYİŞƏN YALNIZ GÖRÜNÜRLÜKDÜR: əvvəl bu hal heç bir iz qoymurdu,
            # yəni əskik bağlama yalnız istifadəçi boş ekran görəndə üzə
            # çıxırdı. `warning` seçilib, `exception` yox — burada tutulmuş
            # xəta yoxdur, tamamlanmamış bağlama var; `raise` isə qadağandır,
            # çünki menyuda görünən ekran açılmalıdır (məzmunsuz da olsa).
            _error_log.warning(
                "SCREEN_BINDER_MISSING",
                extra={
                    "screen": key,
                    "impact": "ekran boş qalır — canlı bağlama hələ yazılmayıb",
                },
            )
            return
        # KÖHNƏ XƏBƏRDARLIQ ƏVVƏLCƏ SİLİNİR: panel saatlarla açıq qalır və
        # eyni ekran dəfələrlə doldurula bilər. Keçən dəfə sınmış, indi
        # düzgün yüklənən bölmə üçün banner qalsaydı, o, YALAN danışardı.
        clear = getattr(screen, "clear_section_errors", None)
        if clear is not None:
            clear()

        try:
            with self._context.session(user_id=self._actor.id) as session:
                binder(session, screen)
        except KompasOSError:
            if reraise:
                # Jurnala BURADA YAZILMIR — çağıran tərəf (məs.
                # `FINE_APPEAL_REFRESH_FAILED`) öz hadisə adı ilə eyni
                # istisnanı artıq qeyd edəcək; ikisi eyni sətri iki dəfə
                # yazardı.
                raise
            _error_log.exception("SCREEN_BIND_FAILED", extra={"screen": key})
            report_section_error(screen, SECTION_SCREEN)
        except Exception:
            # Bax modul başlığı: bir ekranın problemi örtüyü çökdürmür.
            # DAVRANIŞ EYNİDİR (istisna udulur), lakin artıq İSTİFADƏÇİ də
            # görür: sorğu düşübsə ekran «məlumat yoxdur» kimi oxunmamalıdır.
            _error_log.exception("SCREEN_BIND_FAILED", extra={"screen": key})
            report_section_error(screen, SECTION_SCREEN)

    def _fill(
        self, *, label: str, event: str, fetch: Callable[[], _SectionT | None]
    ) -> SectionResult[_SectionT]:
        """Bir bölmənin FETCH mərhələsi — sınarsa SAF `SectionFailure` qaytarır.

        ──────────────────────────────────────────────────────────────────────
        FAZA D (PERF-6) — `_fill_section`-un ƏVƏZİ, Qərar 2 (variant b)
        ──────────────────────────────────────────────────────────────────────
        Köhnə `_fill_section` `fill()`-i (fetch+apply BİRLİKDƏ) try/except-ə
        salır və uğursuzluqda BİRBAŞA `report_section_error(screen, label)`
        çağırırdı — Qt çağırışı FETCH-in daxilində idi. Bu metod YALNIZ
        `fetch`-i çağırır, Qt-yə HEÇ TOXUNMUR — nəticəni `SectionResult`
        (bax onun tərifi) kimi qaytarır, banner çağırışını `_apply_section`
        (ƏSAS SAPDA) edir.

        NİYƏ HƏR BÖLMƏ AYRICA TUTULUR (dəyişməyib): `populate()`-dakı tək
        `try` bloku ilə İdarə Panelinin ilk sınan bölməsi QALAN ALTISINI da
        dayandırırdı — sorğular ardıcıl işləyir, ilk istisna funksiyadan
        çıxır. Nəticədə bir sütunun adı səhv olanda istifadəçi yeddi boş
        bölmə görürdü və heç biri səbəb göstərmirdi.
        """
        try:
            return SectionResult(data=fetch())
        except Exception:
            _error_log.exception(event, extra={"section": label})
            return SectionResult(failure=SectionFailure(section=label))

    def _apply_section(
        self,
        screen: Any,
        result: SectionResult[_SectionT],
        apply: Callable[[_SectionT], None],
    ) -> None:
        """Bir bölmənin APPLY mərhələsi — ƏSAS SAPDA, YALNIZ Qt.

        `result.failure` DOLUDURSA banner göstərilir (`_fill`-in sınadığı
        bölmə), `result.data` DOLUDURSA setter çağırılır. İkisi də boşdursa
        (icazə-əsaslı gizlənmə, bax `SectionResult` başlığı) HEÇ NƏ olmur —
        bölmə köhnə davranışdakı kimi sükutla GİZLİ qalır.
        """
        if result.failure is not None:
            report_section_error(screen, result.failure.section)
            return
        if result.data is not None:
            apply(result.data)

    def _binders(self) -> dict[str, Callable[[Session, Any], None]]:
        return {
            "dashboard": self._dashboard,
            "live_queue": self._live_queue,
            "fines": self._fines,
            "shift_planning": self._shift_planning,
            "shift_swaps": self._shift_swaps,
            "daily_roster": self._daily_roster,
            "fine_appeals": self._fine_appeals,
            "tasks": self._tasks,
            "sales_points": self._sales_points,
            "users": self._users,
            "audit": self._audit,
            "reports": self._reports,
            "help": self._help,
            "health": self._health,
        }

    def _first_screen_binders(
        self,
    ) -> dict[str, tuple[Callable[[Session, Any], Any], Callable[[Any, Any], None]]]:
        """`_binders()`-in FETCH/APPLY cütü ilə eyni siyahısı (bax `prefetch_first_screen`).

        `_binders()`-i TƏKRAR yazmır, YALNIZ hər açarın orkestratoru
        (`_dashboard`, `_users`, …) daxilindəki İKİ addımı — `_X_fetch` +
        `_X_apply` — ayrıca ifşa edir. `Any` ilə tipləndirilib, çünki hər
        açarın MƏLUMAT tipi FƏRQLİDİR (`_DashboardData`, `_UsersData`, …) —
        heterogen lüğət YALNIZ `Any` sərhədi ilə mypy strict altında keçir.
        """
        return {
            "dashboard": (self._dashboard_fetch, self._dashboard_apply),
            "live_queue": (self._live_queue_fetch, self._live_queue_apply),
            "fines": (self._fines_fetch, self._fines_apply),
            "shift_planning": (self._shift_planning_fetch, self._shift_planning_apply),
            "shift_swaps": (self._shift_swaps_fetch, self._shift_swaps_apply),
            "daily_roster": (self._daily_roster_fetch, self._daily_roster_apply),
            "fine_appeals": (self._fine_appeals_fetch, self._fine_appeals_apply),
            "tasks": (self._tasks_fetch, self._tasks_apply),
            "sales_points": (self._sales_points_fetch, self._sales_points_apply),
            "users": (self._users_fetch, self._users_apply),
            "audit": (self._audit_fetch, self._audit_apply),
            "reports": (self._reports_fetch, self._reports_apply),
            "help": (self._help_fetch, self._help_apply),
            "health": (self._health_fetch, self._health_apply),
        }

    def prefetch_first_screen(self, key: str) -> Callable[[Any], None] | None:
        """FAZA D (PERF-6, Mərhələ 2) — İLK ekranın FETCH-i FON SAPINDA, ekran QURULMAMIŞ.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ VAR
        ──────────────────────────────────────────────────────────────────────
        `show_admin()` → `_build_admin_shell()` `shell.show_screen(visible[0])`
        çağıranda `populate()` İLK ekranın bütün sorğularını ƏSAS SAPDA,
        sinxron icra edirdi (bax `_dashboard`-ın "FAZA D" qeydi) — bu,
        `show_admin`-in Qt qurulduqdan SONRAKI donmasının ƏSAS mənbəyidir
        (`docs/performance_notes.md`, PERF-6 #3: "3.2–13.1 s"). `app.py`
        bu metodu ekran HƏLƏ QURULMAMIŞ ikən, FON SAPINDA çağırır və
        nəticəni bir APPLY closure-una bükür — closure isə ekran
        (`AdminShell.show_screen` → `app.py::_register_screens::build`)
        qurulandan SONRA, ƏSAS SAPDA çağırılır.

        ──────────────────────────────────────────────────────────────────────
        "USERS" ÜÇÜN XÜSUSİ HAL — WİDGET HƏLƏ YOXDUR
        ──────────────────────────────────────────────────────────────────────
        `_users_inputs` `screen.status_filter()` oxuyur (bax sinif başlığı,
        "ÜÇ MƏRHƏLƏ, İKİ YOX") — İLK açılışda bu HƏMİŞƏ `"active"`-dir
        (`UsersScreen`-in öz defoltu, bax `_users_fetch`-in şərhi). Widget
        hələ qurulmadığı üçün BURADA canlı oxuna bilməz — sabit defolt
        YAZILIR: bu, WİDGET-in ÖZ ilkin vəziyyətini TƏKRARLAYIR, YENİ
        davranış YARATMIR.

        ──────────────────────────────────────────────────────────────────────
        UĞURSUZLUQ = `None` — KÖHNƏ (SİNXRON) YOLA QAYIDIR
        ──────────────────────────────────────────────────────────────────────
        Açar `_binders()`-də yoxdursa (məs. plugin səhifəsi İLK ekrandır) və
        ya fetch istisna atarsa, `None` qaytarılır: çağıran `show_screen()`-i
        öz KÖHNƏ (sinxron `populate()`) yolu ilə açır — istifadəçi HEÇ nə
        itirmir, yalnız BU XÜSUSİ girişdə donma qalır (fail-soft, CLAUDE.md
        bölmə 3 ilə eyni istiqamət).
        """
        entry = self._first_screen_binders().get(key)
        if entry is None:
            return None
        fetch, apply = entry
        inputs: Any = _UsersInputs(status_filter="active") if key == "users" else _NoInputs()
        try:
            with self._context.session(user_id=self._actor.id) as session:
                data = fetch(session, inputs)
        except Exception:
            _error_log.exception("FIRST_SCREEN_PREFETCH_FAILED", extra={"screen": key})
            return None

        def _apply(screen: Any) -> None:
            apply(screen, data)

        return _apply

    def _may_resolve_conflicts(self) -> bool:
        """Aktorun «Sinxronizasiya Konfliktləri» ekranına icazəsi varmı.

        "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (bölmə 3): sağlamlıq kartındakı keçid
        yalnız flag sahibində QURULUR (bax `HealthScreen.set_conflict_action`).
        Flag adı use case-dən GÖTÜRÜLÜR, burada təkrar YAZILMIR — ikisi
        ayrılsaydı, keçid görünər, ekran isə "səlahiyyətiniz yoxdur" deyərdi.
        """
        from src.application.use_cases.sync_conflicts import (  # noqa: PLC0415
            RESOLVE_CONFLICT_FLAG,
        )

        return bool(self._actor.has_permission(RESOLVE_CONFLICT_FLAG, now=datetime.now(UTC)))

    # ------------------------------ Qrup C ----------------------------------- #

    def _dashboard(self, session: Session, screen: Any) -> None:
        """Admin / CEO İdarə Paneli — beş bölmə, hamısı AQREQASİYA.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ USE CASE DEYİL, BİRBAŞA SQL
        ──────────────────────────────────────────────────────────────────────
        Burada heç bir iş qərarı verilmir: nə status keçidi, nə səlahiyyət
        yoxlaması, nə hesablama qaydası var — yalnız SAYĞAC göstərilir. Eyni
        səbəb `_fines`-də də yazılıb: use case-ə "dashboard üçün say" metodu
        əlavə etmək onu göstəriş vasitəsinə çevirərdi.

        Rəqəmlərin MƏNASI isə mövcud qaydalardan gəlir və burada YENİDƏN
        təyin edilmir: `VERIFIED` = mağazadadır (bölmə 4 STEP C),
        `PENDING_VERIFICATION` + `PENDING_RETURN_VERIFICATION` = operatorun
        birləşmiş növbəsi (`_live_queue` ilə eyni iki mənbə), `OPEN` +
        `EVIDENCE_SUBMITTED` = açıq tapşırıq (`_tasks` ilə eyni dəst).

        ──────────────────────────────────────────────────────────────────────
        BÖLMƏLƏR MÜSTƏQİL NƏTİCƏ VERİR
        ──────────────────────────────────────────────────────────────────────
        Hər bölmə `_fill_section` ilə AYRICA qorunur. Əvvəl ilk istisna
        funksiyadan çıxırdı və qalan bölmələr HEÇ VAXT doldurulmurdu — yəni
        bir sorğunun qüsuru bütün paneli səbəbsiz boşaldırdı. İndi sınan bölmə
        bannerdə adı ilə görünür, qalanları isə düzgün rəqəm göstərir.

        ──────────────────────────────────────────────────────────────────────
        FAZA D (PERF-6) — TAM FETCH/APPLY SƏRHƏDİ (`_fill_section` silindi)
        ──────────────────────────────────────────────────────────────────────
        FAZA C bölmələrin HƏR BİRİNİ `_X_fetch`/`_X_apply` cütünə ayırmışdı,
        LAKİN `_dashboard`-ın ÖZÜNDƏ hər bölmə öz `fill()`-i daxilində
        ARDICIL fetch+apply edirdi — `_fill_section` bunu BİR sətirlik
        try/except-lə əhatə edirdi. İndi `_dashboard_fetch()` SƏKKİZ
        bölmənin HAMISINI (`SectionResult`, bax onun tərifi) yığır — DB-yə
        toxunan YEGANƏ mərhələ budur; `_dashboard_apply()` isə eyni sıra ilə
        ya `apply`, ya `report_section_error` çağırır — Qt-yə toxunan
        YEGANƏ mərhələ budur. Bölmə izolyasiyası VƏ banner sırası
        DƏYİŞMƏDİ: hər bölmə `_fill()`-lə AYRICA sınanır (biri sınsa
        qalanları göstərilir), `_dashboard_apply` isə onları FETCH-dəki İLƏ
        EYNİ ardıcıllıqla tətbiq edir.
        """
        inputs = self._dashboard_inputs(screen)
        data = self._dashboard_fetch(session, inputs)
        self._dashboard_apply(screen, data)

    def _dashboard_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _dashboard_fetch(self, session: Session, _inputs: _NoInputs) -> _DashboardData:
        today = datetime.now(UTC).date()
        month_start = today.replace(day=1)
        next_month = _next_month(month_start)
        previous_month = _previous_month(month_start)

        return _DashboardData(
            summary=self._fill(
                label=SECTION_DASHBOARD_SUMMARY,
                event="DASHBOARD_SUMMARY_FAILED",
                fetch=lambda: self._dashboard_summary_fetch(
                    session,
                    today=today,
                    month_start=month_start,
                    next_month=next_month,
                    previous_month=previous_month,
                ),
            ),
            # «Neçə işçi, neçə filial» — AYRICA bölmə, çünki mənbəyi də
            # ayrıdır: xülasə kartları günün/ayın əməliyyat rəqəmləridir,
            # bu isə şirkətin ölçüsü. Ayrı bölmə həm də ayrı sınır: cərimə
            # sorğusu pozulsa, say yenə görünür.
            network=self._fill(
                label=SECTION_DASHBOARD_NETWORK,
                event="DASHBOARD_NETWORK_FAILED",
                fetch=lambda: self._dashboard_network_fetch(session),
            ),
            fines=self._fill(
                label=SECTION_DASHBOARD_FINES,
                event="DASHBOARD_FINES_FAILED",
                fetch=lambda: self._dashboard_fines_fetch(
                    session, month_start=month_start, next_month=next_month
                ),
            ),
            leave=self._fill(
                label=SECTION_DASHBOARD_LEAVE,
                event="DASHBOARD_LEAVE_FAILED",
                fetch=lambda: self._dashboard_leave_fetch(
                    session, month_start=month_start, next_month=next_month
                ),
            ),
            leaders=self._fill(
                label=SECTION_DASHBOARD_LEADERS,
                event="DASHBOARD_LEADERS_FAILED",
                fetch=lambda: self._dashboard_leaders_fetch(session, today=today),
            ),
            health=self._fill(
                label=SECTION_DASHBOARD_HEALTH,
                event="DASHBOARD_HEALTH_FAILED",
                fetch=lambda: self._dashboard_health_fetch(session),
            ),
            benchmark=self._fill(
                label=SECTION_DASHBOARD_BENCHMARK,
                event="DASHBOARD_BENCHMARK_FAILED",
                fetch=lambda: self._dashboard_benchmark_gated_fetch(session),
            ),
            breaks=self._fill(
                label=SECTION_DASHBOARD_BREAKS,
                event="DASHBOARD_BREAK_OVERUSE_FAILED",
                fetch=lambda: self._dashboard_break_overuse_fetch(session, today=today),
            ),
        )

    def _dashboard_apply(self, screen: Any, data: _DashboardData) -> None:
        self._apply_section(
            screen, data.summary, lambda d: self._dashboard_summary_apply(screen, d)
        )
        self._apply_section(
            screen, data.network, lambda d: self._dashboard_network_apply(screen, d)
        )
        self._apply_section(screen, data.fines, lambda d: self._dashboard_fines_apply(screen, d))
        self._apply_section(screen, data.leave, lambda d: self._dashboard_leave_apply(screen, d))
        self._apply_section(
            screen, data.leaders, lambda d: self._dashboard_leaders_apply(screen, d)
        )
        self._apply_section(screen, data.health, lambda d: self._dashboard_health_apply(screen, d))
        self._apply_section(
            screen, data.benchmark, lambda d: self._dashboard_benchmark_apply(screen, d)
        )
        self._apply_section(
            screen, data.breaks, lambda d: self._dashboard_break_overuse_apply(screen, d)
        )

    def _dashboard_network_fetch(self, session: Session) -> _DashboardNetworkData:
        """Aktiv işçi və filial sayı — «yaratdıqca artan» rəqəmlər.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ SAYĞAC, NİYƏ PARAMETR DEYİL
        ──────────────────────────────────────────────────────────────────────
        Əvvəl bu rəqəmlər başlıqda SABİT mətn idi («21 filial», «235 nəfər»)
        və bir mağazalı quraşdırmada da göstərilirdi. Root parametrinə
        çevirmək daha da pis olardı: `stores` cədvəli ilə sinxrondan çıxan
        ikinci həqiqət mənbəyi yaranardı — mağaza əlavə edilir, rəqəm qalır.

        `is_active` SÜZGƏCİ QƏSDLİDİR: deaktiv edilmiş mağaza/işçi sətri
        arxivdə QALIR (soft delete), lakin şəbəkənin CARİ ölçüsü deyil.
        """
        row = session.uow.connection.execute(
            """
            SELECT
                (SELECT count(*) FROM employees
                  WHERE tenant_id = %s AND is_active) AS employee_count,
                (SELECT count(*) FROM stores
                  WHERE tenant_id = %s AND is_active) AS store_count
            """,
            (str(session.tenant_id), str(session.tenant_id)),
        ).fetchone()
        if row is None:  # pragma: no cover - `count(*)` həmişə sətir qaytarır
            return _DashboardNetworkData(employees=None, stores=None)
        return _DashboardNetworkData(
            employees=int(row["employee_count"]), stores=int(row["store_count"])
        )

    def _dashboard_network_apply(self, screen: Any, data: _DashboardNetworkData) -> None:
        if data.employees is None or data.stores is None:  # pragma: no cover - bax fetch
            return
        screen.set_network_size(employees=data.employees, stores=data.stores)

    def _dashboard_summary_fetch(
        self,
        session: Session,
        *,
        today: date,
        month_start: date,
        next_month: date,
        previous_month: date,
    ) -> _DashboardSummaryData:
        """Dörd rəqəm kartı — bir sorğu, səkkiz sayğac.

        Aylıq cərimə cəmi (`_fine_month_totals`) DA burada oxunur — köhnə
        kodda bu, `_dashboard()`-un `fill_summary` closure-ında AYRI idi
        (eyni bölmə üçün, sadəcə iki yerə bölünmüşdü); indi TƏK `fetch`
        funksiyasında birləşir, bölmənin sərhədi DƏYİŞMİR.
        """
        # Aylıq cəm rəqəm KARTININ bir hissəsidir — onunla EYNİ bölmədə
        # qalır ki, sınması yalnız həmin kartı işarələsin.
        fine_totals = _fine_month_totals(
            session,
            month_start=month_start,
            next_month=next_month,
            previous_month=previous_month,
        )
        row = session.uow.connection.execute(
            """
            SELECT
              (SELECT count(*) FROM attendance_records
                WHERE tenant_id = %s AND work_date = %s
                  AND check_in_status = 'VERIFIED')                     AS in_store,
              (SELECT count(*) FROM shift_assignments
                WHERE tenant_id = %s AND shift_date = %s
                  AND NOT is_off_day)                                   AS planned,
              (SELECT count(*) FROM attendance_records
                WHERE tenant_id = %s AND work_date = %s
                  AND check_in_status = 'PENDING_VERIFICATION')         AS pending_entry,
              (SELECT count(*) FROM leave_requests
                WHERE tenant_id = %s
                  AND status = 'PENDING_RETURN_VERIFICATION')           AS pending_return,
              (SELECT min(requested_at) FROM attendance_records
                WHERE tenant_id = %s AND work_date = %s
                  AND check_in_status = 'PENDING_VERIFICATION')         AS oldest_entry,
              (SELECT min(return_claimed_time) FROM leave_requests
                WHERE tenant_id = %s
                  AND status = 'PENDING_RETURN_VERIFICATION')           AS oldest_return,
              (SELECT count(*) FROM tasks
                WHERE tenant_id = %s
                  AND status IN ('OPEN', 'EVIDENCE_SUBMITTED'))         AS open_tasks,
              (SELECT count(*) FROM tasks
                WHERE tenant_id = %s AND deadline < now()
                  AND status IN ('OPEN', 'EVIDENCE_SUBMITTED'))         AS overdue_tasks
            """,
            (
                session.tenant_id,
                today,
                session.tenant_id,
                today,
                session.tenant_id,
                today,
                session.tenant_id,
                session.tenant_id,
                today,
                session.tenant_id,
                session.tenant_id,
                session.tenant_id,
            ),
        ).fetchone()
        counts = row or {}

        # Ən uzun gözləmə İKİ mənbədən ən KÖHNƏSİDİR — növbə birləşmişdir
        # (bölmə 4), ona görə "ən uzunu" da birləşmiş dəstə aid olmalıdır.
        oldest = _earliest(counts.get("oldest_entry"), counts.get("oldest_return"))
        pending = int(counts.get("pending_entry") or 0) + int(counts.get("pending_return") or 0)

        return _DashboardSummaryData(
            in_store=int(counts.get("in_store") or 0),
            planned=int(counts.get("planned") or 0),
            pending=pending,
            longest_wait=f"{_minutes_since(oldest)} dəq" if oldest is not None else "—",
            fines_total=fine_totals[0],
            fines_delta=fine_totals[1],
            open_tasks=int(counts.get("open_tasks") or 0),
            overdue_tasks=int(counts.get("overdue_tasks") or 0),
        )

    def _dashboard_summary_apply(self, screen: Any, data: _DashboardSummaryData) -> None:
        screen.set_summary(
            in_store=data.in_store,
            planned=data.planned,
            pending=data.pending,
            longest_wait=data.longest_wait,
            fines_total=data.fines_total,
            fines_delta=data.fines_delta,
            open_tasks=data.open_tasks,
            overdue_tasks=data.overdue_tasks,
        )

    def _dashboard_fines_fetch(
        self, session: Session, *, month_start: date, next_month: date
    ) -> _DashboardFinesData:
        """Filial üzrə cərimə sütunları — bu ayın BÜTÜN statusları.

        `PENDING_REVIEW` sətirlər DƏ daxildir və bu, qəsdəndir: dashboard
        idarəetmə göstəricisidir, hesabat ixracı deyil. Bölmə 6-nın LOCK
        mexanizmi yalnız EXPORT-a aiddir (`_reports`) — ayın ortasında
        "cərimə yoxdur" göstərmək menecerə yanlış mənzərə verərdi.
        """
        rows = session.uow.connection.execute(
            """
            SELECT COALESCE(s.name, '—') AS store_name,
                   COALESCE(SUM(f.amount), 0) AS total
              FROM fines f
              LEFT JOIN stores s ON s.id = f.store_id
             WHERE f.tenant_id = %s AND f.fine_date >= %s AND f.fine_date < %s
             GROUP BY s.name
             ORDER BY total DESC
             LIMIT 12
            """,
            (session.tenant_id, month_start, next_month),
        ).fetchall()
        return _DashboardFinesData(
            rows=[
                (str(row["store_name"]), float(row["total"] or 0), f"{row['total'] or 0} ₼")
                for row in rows
            ],
            period=_month_text(),
        )

    def _dashboard_fines_apply(self, screen: Any, data: _DashboardFinesData) -> None:
        screen.set_fines_by_branch(data.rows, period=data.period)

    def _dashboard_leave_fetch(
        self, session: Session, *, month_start: date, next_month: date
    ) -> _DashboardLeaveData:
        """İcazə ölçəni — istifadə / tenant büdcəsi.

        Büdcə = `MONTHLY_LEAVE_MINUTES_LIMIT` × aktiv işçi sayı. Limit
        SPESİFİKASİYADA işçi başınadır (bölmə 3) və burada YENİDƏN təyin
        edilmir — sadəcə eyni limit tenant miqyasına vurulur ki, ölçən
        nisbəti göstərə bilsin. Qayda (240 dəq aşıldıqda XƏBƏRDARLIQ, bloklama
        YOX) `MonthlyLeaveUsage`-də qalır; bu ölçən heç nə bloklamır.
        """
        key = SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT
        per_employee = session.limits.get_int(
            session.tenant_id, key.value, int(DEFAULT_LIMITS[key])
        )
        row = session.uow.connection.execute(
            """
            SELECT
              (SELECT COALESCE(SUM(total_minutes), 0) FROM leave_requests
                WHERE tenant_id = %s AND requested_time >= %s
                  AND requested_time < %s)              AS used_minutes,
              (SELECT count(*) FROM employees
                WHERE tenant_id = %s AND is_active)     AS active_employees
            """,
            (session.tenant_id, month_start, next_month, session.tenant_id),
        ).fetchone()
        used = float((row or {}).get("used_minutes") or 0)
        headcount = int((row or {}).get("active_employees") or 0)
        return _DashboardLeaveData(used=used, budget=float(per_employee * headcount))

    def _dashboard_leave_apply(self, screen: Any, data: _DashboardLeaveData) -> None:
        screen.set_leave_usage(data.used, data.budget)

    def _dashboard_leaders_fetch(self, session: Session, *, today: date) -> _DashboardLeadersData:
        """Xal liderləri — CARİ 6 aylıq dövr (`PointsPeriod`, bölmə 6).

        Dövr sərhədi domendən götürülür, "son 30 gün" kimi bir kəsim
        uydurulmur: xallar 1 Yanvar / 1 İyul-da sıfırlanır və liderlik
        lövhəsi sıfırlanmadan SONRA köhnə dövrün adlarını göstərməməlidir.
        """
        from src.domain.value_objects.gamification import PointsPeriod  # noqa: PLC0415

        period = PointsPeriod.containing(today)
        rows = session.uow.connection.execute(
            """
            SELECT e.first_name, e.last_name, SUM(l.delta_points) AS total
              FROM points_ledger l
              JOIN employees e ON e.id = l.employee_id
             WHERE l.tenant_id = %s AND l.period_start = %s AND l.status <> 'REVERSED'
             GROUP BY e.first_name, e.last_name
             HAVING SUM(l.delta_points) > 0
             ORDER BY total DESC
             LIMIT 5
            """,
            (session.tenant_id, period.start),
        ).fetchall()
        return _DashboardLeadersData(
            leaders=[(_full_name(row), _points_text(row["total"])) for row in rows]
        )

    def _dashboard_leaders_apply(self, screen: Any, data: _DashboardLeadersData) -> None:
        screen.set_leaders(data.leaders)

    def _dashboard_health_fetch(self, session: Session) -> _DashboardHealthData:
        """1C serverlərinin vəziyyəti — `v_erp_server_health` görünüşündən.

        `INACTIVE` sətirlər GÖSTƏRİLMİR: `ServerHealth.needs_attention` onları
        qəsdən kənarda saxlayır — deaktivləşdirmə adminin QƏRARIDIR, nasazlıq
        deyil. Onları daimi sarı ilə göstərmək kartı "həmişə xəbərdarlıq"
        halına salar və REAL problem itərdi. Tam siyahı «Sistem Sağlamlığı»
        ekranındadır.
        """
        rows = session.uow.connection.execute(
            """
            SELECT server_name, health, sync_delay_seconds
              FROM v_erp_server_health
             WHERE tenant_id = %s AND health <> 'INACTIVE'
             ORDER BY server_name
             LIMIT 8
            """,
            # `tenant_id` şərti RLS-ə ƏLAVƏ ikinci qatdır (CLAUDE.md bölmə 6):
            # görünüş `security_invoker` ilə işləyir, lakin bir konfiqurasiya
            # səhvi bütün tenant-ların serverlərini bir dashboard-a tökərdi.
            (session.tenant_id,),
        ).fetchall()
        return _DashboardHealthData(
            rows=[
                (
                    str(row["server_name"]),
                    _sync_delay_text(row["sync_delay_seconds"]),
                    _HEALTH_TONES.get(str(row["health"]), "warning"),
                )
                for row in rows
            ]
        )

    def _dashboard_health_apply(self, screen: Any, data: _DashboardHealthData) -> None:
        screen.set_server_health(data.rows)

    def _dashboard_break_overuse_fetch(
        self, session: Session, *, today: date
    ) -> list[tuple[str, str]]:
        """Nahar/Çay gündəlik həddini aşanlar (nahar.md GUI, bənd 2).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BİRBAŞA SQL DEYİL, USE CASE ÜZƏRİNDƏN
        ──────────────────────────────────────────────────────────────────────
        Bu bölmə `_dashboard_summary`/`_dashboard_leave`-dən FƏRQLƏNİR: orada
        yalnız SAYĞAC göstərilir, burada isə QƏRAR var — "hədd aşılıbmı?".
        Həmin qərar ROOT parametrindən (`LUNCH_BREAK_DAILY_COUNT` /
        `TEA_BREAK_DAILY_COUNT`) asılıdır və `BreakAllowance.is_exceeded`-də
        yaşayır. SQL-ə `count_used > <hədd>` yazsaydıq, qayda İKİ yerdə
        olardı və Root dəyəri dəyişəndə panel köhnə həddi göstərməyə davam
        edərdi.

        ──────────────────────────────────────────────────────────────────────
        SƏLAHİYYƏT: `can_view_employee_reports`
        ──────────────────────────────────────────────────────────────────────
        Siyahı AD-BAAD işçi göstərir, yəni aqreqat deyil, fərdi məlumatdır.
        `_dashboard_benchmark`-dakı eyni qısa-dövrə: flag yoxdursa bölmə
        doldurulmur və ekranda GÖRÜNMÜR (bölmə 3: "GÖRMƏK = SƏLAHİYYƏTİN
        OLMASI"). BOŞ siyahı AÇIQ qaytarılır — əvvəlki dolu vəziyyət
        ekranda qalmasın deyə (panel yenidən oxunanda rol dəyişmiş ola
        bilər); `apply` mərhələsi bunu heç bir şərtsiz `set_break_overuse`-a
        ötürür (bax `_dashboard_break_overuse_apply`).
        """
        from src.application.use_cases.employee_profile import (  # noqa: PLC0415
            VIEW_EMPLOYEE_REPORTS_FLAG,
        )

        if not self._actor.has_permission(VIEW_EMPLOYEE_REPORTS_FLAG, now=datetime.now(UTC)):
            return []

        usages = session.leave_verification.break_overuse_for_day(
            tenant_id=session.tenant_id, on_date=today
        )
        if not usages:
            return []

        # ADLAR BİR SORĞUDA: sətir başına `employees.get()` çağırmaq 21
        # filialın həddi aşan işçiləri üçün onlarla gediş-gəliş demək olardı.
        rows = session.uow.connection.execute(
            """
            SELECT id, first_name, last_name
              FROM employees
             WHERE tenant_id = %s AND id = ANY(%s)
            """,
            (session.tenant_id, [usage.employee_id for usage in usages]),
        ).fetchall()
        names = {row["id"]: _full_name(row) for row in rows}

        return [
            (names.get(usage.employee_id, "Naməlum işçi"), usage.allowance.warning_az())
            for usage in usages
        ]

    def _dashboard_break_overuse_apply(self, screen: Any, rows: list[tuple[str, str]]) -> None:
        screen.set_break_overuse(rows)

    def _dashboard_benchmark_gated_fetch(self, session: Session) -> _DashboardBenchmarkData | None:
        """#24 Çox-Mağaza Benchmark — dörd yeni widget, YALNIZ `can_export_reports`.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ MAĞAZA_MENECERI ÜÇÜN "ERKƏN RETURN" KİFAYƏTDİR
        ──────────────────────────────────────────────────────────────────────
        `MultiStoreBenchmarkUseCase`-in ÖZÜ də bu flag-i tələb edir (ikinci
        qat, use case modul başlığı) — burdakı yoxlama əlavə səlahiyyət
        QAYDASI DEYİL, sadəcə lazımsız sorğunun qarşısını alan QISA-DÖVRƏDİR:
        flag yoxdursa `set_*` heç çağırılmır, ekranın dörd bölməsi (bax
        `group_c.DashboardScreen` sinif başlığı) defolt GİZLİ qalır.

        FAZA D (PERF-6) — `None` QAYTARMAQ "İCAZƏ YOXDUR" DEMƏKDİR, "UĞURSUZ
        OLDU" DEYİL: `_dashboard_fetch`-də `self._fill(...)` bunu `SectionResult
        (data=None, failure=None)`-a çevirir (bax onun tərifi) — `_dashboard_
        apply` heç bir banner, heç bir setter çağırmır, bölmə köhnə davranışdakı
        kimi sükutla GİZLİ qalır. Bu metod `_dashboard`-ın SƏKKİZ bölməsindən
        BİRİDİR; `refresh_dashboard_benchmark` (dropdown dəyişəndə, AYRI giriş
        nöqtəsi) EYNİ icazə yoxlamasını ÖZÜ aparır, bura DELEGƏ ETMİR — ikisinin
        sərhədi FƏRQLİDİR (bax onun başlığı).
        """
        from src.application.use_cases.multi_store_benchmark import (  # noqa: PLC0415
            VIEW_BENCHMARK_FLAG,
            BenchmarkMetric,
        )

        now = datetime.now(UTC)
        if not self._actor.has_permission(VIEW_BENCHMARK_FLAG, now=now):
            return None
        # İLK açılışdakı defolt metrik — dropdown dəyişəndə `refresh_dashboard_
        # benchmark` YENİ metriklə TƏKRAR çağırır (bax o metodun başlığı).
        return self._dashboard_benchmark_fetch(session, metric=BenchmarkMetric.FINE_COUNT)

    def refresh_dashboard_benchmark(self, screen: Any, *, metric_key: str) -> None:
        """Reytinq dropdown-u dəyişəndə dörd bölməni YENİ metriklə yeniləyir.

        Kontroller sessiyanı SAXLAMIR (CLAUDE.md bölmə 6) — hər dəyişiklik
        ÖZ sessiyasını açır, `_dashboard`-ın ilkin populate çağırışından
        MÜSTƏQİLDİR.
        """
        from src.application.use_cases.multi_store_benchmark import (  # noqa: PLC0415
            VIEW_BENCHMARK_FLAG,
            BenchmarkMetric,
        )

        now = datetime.now(UTC)
        if not self._actor.has_permission(VIEW_BENCHMARK_FLAG, now=now):
            return
        try:
            metric = BenchmarkMetric(metric_key)
        except ValueError:
            # İSTİFADƏÇİ DÜYMƏNİ BASIB VƏ NƏTİCƏ GÖZLƏYİR: naməlum açar
            # sükutla keçilsəydi, cədvəl KÖHNƏ metrikin rəqəmlərini yeni
            # metrikin adı altında göstərməyə davam edərdi — səssiz boşluqdan
            # da pis hal.
            _error_log.warning("BENCHMARK_UNKNOWN_METRIC", extra={"metric_key": metric_key})
            report_section_error(screen, SECTION_DASHBOARD_BENCHMARK)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                data = self._dashboard_benchmark_fetch(session, metric=metric)
        except Exception:
            _error_log.exception("BENCHMARK_REFRESH_FAILED", extra={"metric_key": metric_key})
            report_section_error(screen, SECTION_DASHBOARD_BENCHMARK)
            return
        self._dashboard_benchmark_apply(screen, data)

    def _dashboard_benchmark_fetch(
        self, session: Session, *, metric: BenchmarkMetric
    ) -> _DashboardBenchmarkData:
        """Dörd bölmənin ORTAQ oxuma məntiqi (`_dashboard_benchmark` +
        `refresh_dashboard_benchmark` EYNİ kodu paylaşır)."""
        from src.application.use_cases.multi_store_benchmark import (  # noqa: PLC0415
            BenchmarkMetric,
            format_metric_value,
        )
        from src.presentation.screens.group_c import RankingEntry  # noqa: PLC0415

        metric_options = [(item.value, item.label_az) for item in BenchmarkMetric]

        rows = session.multi_store_benchmark.ranking(
            tenant_id=session.tenant_id, actor=self._actor, metric=metric
        )
        ranking = [
            RankingEntry(
                store_id=str(row.store_id),
                store_name=row.store_name,
                value_display=row.display_value,
                trend_arrow=row.trend.arrow,
                trend_label=row.trend.label_az,
            )
            for row in rows
        ]

        comparison: _BenchmarkComparison | None = None
        if rows:
            # Defolt müqayisə ƏN YAXŞI sıralanan mağaza üçündür — istifadəçi
            # sətrə klikləyəndə (drill-down) fərqli bir kontekstə keçir,
            # bura toxunmur (bax `AdminShell.screen_for` şərhi).
            store_vs_network = session.multi_store_benchmark.store_vs_network(
                tenant_id=session.tenant_id,
                actor=self._actor,
                metric=metric,
                store_id=rows[0].store_id,
            )
            comparison = _BenchmarkComparison(
                metric_label=metric.label_az,
                store_label=store_vs_network.store_name,
                store_value=store_vs_network.store_value or 0.0,
                store_display=format_metric_value(store_vs_network.store_value, metric),
                network_label="Şəbəkə ortalaması",
                network_value=store_vs_network.network_average or 0.0,
                network_display=format_metric_value(store_vs_network.network_average, metric),
            )

        trend_points = session.multi_store_benchmark.trend(
            tenant_id=session.tenant_id, actor=self._actor, metric=metric
        )

        outliers = session.multi_store_benchmark.outliers(
            tenant_id=session.tenant_id, actor=self._actor, metric=metric
        )

        return _DashboardBenchmarkData(
            ranking=ranking,
            metric_options=metric_options,
            selected_metric=metric.value,
            comparison=comparison,
            metric_label=metric.label_az,
            trend_points=[
                (point.period_label, point.value or 0.0, format_metric_value(point.value, metric))
                for point in trend_points
            ],
            outliers_summary=outliers.summary_text_az,
            outliers_rows=[
                (
                    outlier.store_name,
                    f"{outlier.deviation_sigma:.1f}σ "
                    f"{'yuxarı' if outlier.above_average else 'aşağı'}",
                )
                for outlier in outliers.outliers
            ],
        )

    def _dashboard_benchmark_apply(self, screen: Any, data: _DashboardBenchmarkData) -> None:
        screen.set_ranking_table(
            data.ranking, metric_options=data.metric_options, selected_metric=data.selected_metric
        )
        if data.comparison is not None:
            screen.set_store_vs_network(
                metric_label=data.comparison.metric_label,
                store_label=data.comparison.store_label,
                store_value=data.comparison.store_value,
                store_display=data.comparison.store_display,
                network_label=data.comparison.network_label,
                network_value=data.comparison.network_value,
                network_display=data.comparison.network_display,
            )
        screen.set_metric_trend(metric_label=data.metric_label, points=data.trend_points)
        screen.set_outliers(summary_text=data.outliers_summary, rows=data.outliers_rows)

    def populate_daily_roster_for_store(self, store_id: StoreId, screen: Any) -> None:
        """Reytinq Cədvəlindəki DRILL-DOWN-un yazı yolu (#24, Faza 9A).

        `_daily_roster`-dən FƏRQİ: o, aktorun ÖZ mağazasını göstərir (Store
        Manager-in gündəlik işi). Bura İSƏ Root/CEO/Admin/HR_Admin-in
        REYTİNQDƏ kliklədiyi İSTƏNİLƏN mağazanı açır — `DailyAttendanceSheet
        UseCase.open_sheet` bunu ARTIQ dəstəkləyir (`store_id` sərbəst
        arqumentdir, `_require_store_access` `can_view_employee_reports`
        sahibini istənilən mağazaya buraxır), ona görə YENİ use case metodu
        YOX, sadəcə bu kontroller bir yeni AÇAR yolu əlavə edir.

        ──────────────────────────────────────────────────────────────────────
        FAZA C (PERF-6, RİSKLİ) — GİZLİ YAZI + XÜSUSİ BANNER, EYNİ FORMA
        ──────────────────────────────────────────────────────────────────────
        `_daily_roster`-in başlığındakı EYNİ "gizli yazı" izahı burada da
        keçərlidir: `open_sheet()` gündəlik tabeli YARADIR, yazı `fetch`
        mərhələsində qalır. FƏRQ: bu metodun ÖZÜNÜN try/except-i var (SPESİFİK
        `SECTION_DAILY_ROSTER` banneri) — `_health`-dəki Qərar-2 mexanizmi
        (bax `SectionFailure`) BURADA da işlədilir: `fetch` uğursuzluqda SAF
        `_DailyRosterData(failure=...)` qaytarır, `apply` bunu bannerə çevirir.

        `_context.session(...)` BURADA açılır (`_daily_roster`-dən fərqli
        olaraq bu metod `populate()`-dən keçmir, ÖZ sessiyasını özü qurur) —
        bu, DƏYİŞMİR, çünki `perform_ranking_drill_down` bu metodu birbaşa,
        artıq açılmış sessiyasız çağırır.

        ──────────────────────────────────────────────────────────────────────
        FAZA D (PERF-6, Mərhələ 3) — BÜTÖV FORMA QALIR, İKİ YARISI DA İFŞA OLUNUR
        ──────────────────────────────────────────────────────────────────────
        `app.py::_on_ranking_row_selected` ARTIQ bu bütöv metodu ÇAĞIRMIR —
        `fetch_daily_roster_for_store()`/`apply_daily_roster_for_store()`-u
        AYRI-AYRI, `run_job` sərhədi ilə işlədir (bax onların başlığı). Bu
        metod (bütöv forma) YALNIZ digər, sap sərhədi TƏLƏB ETMƏYƏN çağıran
        yerlər üçün (məs. `_on_screen_revisited`-in ÖZ `populate()` yolu,
        testlər) SAXLANILIR — imza VƏ davranış DƏYİŞMİR.
        """
        self.apply_daily_roster_for_store(screen, self.fetch_daily_roster_for_store(store_id))

    def fetch_daily_roster_for_store(self, store_id: StoreId) -> _DailyRosterData:
        """`populate_daily_roster_for_store`-un FETCH mərhələsi — FON SAPINDA çağırıla bilər.

        PERF-6, Mərhələ 3: `app.py::_on_ranking_row_selected` bunu `run_job`-a
        verir ki, `open_sheet()`-in gizli YAZISI (bax `populate_daily_roster_
        for_store` başlığı) `AdminShell.show_screen()`/`screen_for()`
        (Qt naviqasiya, ƏSAS SAPDA) TAMAMLANDIQDAN SONRA, LAKİN GUI sapını
        BLOKLAMADAN icra olunsun. `screen` arqumenti YOXDUR — `inputs`
        həmişə `_NoInputs()`-dur (bax `_daily_roster_for_store_inputs`),
        widget-dən oxunan HEÇ NƏ yoxdur.
        """
        return self._daily_roster_for_store_fetch(store_id, _NoInputs())

    def apply_daily_roster_for_store(self, screen: Any, data: _DailyRosterData) -> None:
        """`populate_daily_roster_for_store`-un APPLY mərhələsi — ƏSAS SAPDA, YALNIZ Qt."""
        self._daily_roster_for_store_apply(screen, data)

    def _daily_roster_for_store_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _daily_roster_for_store_fetch(
        self, store_id: StoreId, _inputs: _NoInputs
    ) -> _DailyRosterData:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                view = session.daily_attendance.open_sheet(
                    tenant_id=session.tenant_id, actor=self._actor, store_id=store_id
                )
                session.commit()  # gündəlik tabel YARADIR — bax bu metodun başlığı
                rows = [
                    {
                        "employee": _employee_name(session, line.employee_id),
                        "status": line.auto_status.label_az,
                        "note": line.manager_note or "",
                    }
                    for line in view.sheet.lines
                ]
        except Exception:
            # DRILL-DOWN SÜKUTLA GERİ QAYITMIR: istifadəçi reytinqdə bir
            # mağazaya kliklədi və ekran açıldı. Sətirlər yazılmasa, o,
            # ƏVVƏLKİ mağazanın (və ya boş) siyahısını YENİ mağazanın
            # məlumatı kimi oxuyardı — yanlış filial haqqında qərar verərdi.
            _error_log.exception(
                "BENCHMARK_DRILL_DOWN_ROSTER_FAILED", extra={"store_id": str(store_id)}
            )
            return _DailyRosterData(
                rows=[], mismatch_text=None, failure=SectionFailure(section=SECTION_DAILY_ROSTER)
            )

        mismatch_text = (
            f"{view.mismatch_count} sətir HR planı ilə uyğun gəlmir — nəzərdən keçirin."
            if view.mismatch_count
            else None
        )
        return _DailyRosterData(rows=rows, mismatch_text=mismatch_text)

    def _daily_roster_for_store_apply(self, screen: Any, data: _DailyRosterData) -> None:
        if data.failure is not None:
            report_section_error(screen, data.failure.section)
            return
        screen.set_rows(data.rows)
        if data.mismatch_text is not None:
            screen.set_mismatch(data.mismatch_text)

    # ------------------------------ Qrup B ----------------------------------- #

    def _live_queue(self, session: Session, screen: Any) -> None:
        """Kamera Operatorunun BİRLƏŞMİŞ növbəsi (bölmə 4: giriş + qayıdış).

        İki mənbə bir siyahıda göstərilir və tip-badge ilə fərqləndirilir —
        spesifikasiya açıq şəkildə "iki ayrı tab/ekran əvəzinə" deyir.

        FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır. Bu,
        kateqoriya-3 (səpələnmiş `report_section_error`) daşıyan İKİNCİ
        binder-dir (`_health`-in köməkçiləri birincidir) — `_low_confidence_
        faces` artıq `screen`-i ÇAĞIRMIR, uğursuzluğu SAF `bool` kimi
        qaytarır (bax onun tərifi).
        """
        inputs = self._live_queue_inputs(screen)
        data = self._live_queue_fetch(session, inputs)
        self._live_queue_apply(screen, data)

    def _live_queue_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _live_queue_fetch(self, session: Session, _inputs: _NoInputs) -> _LiveQueueData:
        from src.presentation.screens.group_b import QueueEntry  # noqa: PLC0415

        stores = session.uow.repository("camera_assignments").stores_for_operator(self._actor.id)
        if not stores:
            # FAIL-SAFE (bölmə 4): təyinatsız operator HEÇ NƏ görmür.
            return _LiveQueueData(entries=[], low_confidence_failed=False)

        # Xəbərdarlıq həddi CANLI limitdən hesablanır: Root timeout-u 45-dən
        # 20 dəqiqəyə endirsə, sabit 22 ilə operator xəbərdarlığı ESKALASİYADAN
        # SONRA görərdi — yəni siqnal öz mənasını itirərdi (bax
        # `late_threshold_minutes` və `LATE_QUEUE_MINUTES` şərhi).
        late_after = late_threshold_minutes(session)

        # AŞAĞI-ETİBARLI ÜZ TƏSDİQİ (facecontrol.md bənd 12) — nişan üçün
        # lazım olan dəst BİR sorğu ilə oxunur; sətir-sətir sorğu 40 sətirlik
        # növbədə 40 gediş-gəliş demək olardı.
        low_confidence, low_confidence_failed = _low_confidence_faces(session, stores)

        # `(gözləmə dəqiqəsi, sətir)` cütü ilə yığılır: `QueueEntry` gözləməni
        # MƏTN kimi saxlayır ("18 dəq") və mətnə görə sıralamaq "9 dəq"-i
        # "18 dəq"-dən sonra qoyardı.
        pending: list[tuple[int, QueueEntry]] = []

        for record in session.uow.attendance.list_pending_verification(stores):
            waited = _minutes_since(record.requested_at)
            pending.append(
                (
                    waited,
                    QueueEntry(
                        request_id=str(record.id),
                        employee_name=_employee_name(session, record.employee_id),
                        store_name=_store_name(session, record.store_id),
                        position_name=_position_name(session, record.employee_id),
                        kind="Giriş Təsdiqi",
                        timestamp_text=_hhmm(record.requested_at),
                        waiting_text=f"{waited} dəq",
                        is_late=waited >= late_after,
                        is_low_confidence=(str(record.employee_id), "STEP_A") in low_confidence,
                    ),
                )
            )

        for request in session.uow.leave_requests.list_pending_verification(stores):
            waited = _minutes_since(request.return_claimed_time)
            pending.append(
                (
                    waited,
                    QueueEntry(
                        request_id=str(request.id),
                        employee_name=_employee_name(session, request.employee_id),
                        store_name=_store_name(session, request.store_id),
                        position_name=_position_name(session, request.employee_id),
                        kind="Qayıdış Təsdiqi",
                        timestamp_text=_hhmm(request.requested_time),
                        waiting_text=f"{waited} dəq",
                        is_late=waited >= late_after,
                        is_low_confidence=(str(request.employee_id), "STEP_2") in low_confidence,
                    ),
                )
            )

        # Ən çox gözləyən ƏVVƏLDƏ: operator növbəni yuxarıdan aşağı emal edir
        # və 45 dəqiqəlik timeout-a ən yaxın olan birinci görünməlidir.
        pending.sort(key=lambda item: item[0], reverse=True)
        return _LiveQueueData(
            entries=[entry for _, entry in pending],
            low_confidence_failed=low_confidence_failed,
        )

    def _live_queue_apply(self, screen: Any, data: _LiveQueueData) -> None:
        screen.set_entries(data.entries)
        if data.low_confidence_failed:
            report_section_error(screen, SECTION_QUEUE_FACE_BADGES)

    # ------------------------------ Qrup C ----------------------------------- #

    def _shift_planning(self, session: Session, screen: Any) -> None:
        """FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır.

        `fetch`-in atdığı `KompasOSError` BURADA TUTULMUR — `shift_window.py::
        _on_month_changed` `populate(..., reraise=True)` ilə çağırır və onu
        gözləyir (bax `populate()` başlığı, `_fine_appeals` ilə EYNİ qayda).
        """
        inputs = self._shift_planning_inputs(screen)
        data = self._shift_planning_fetch(session, inputs)
        self._shift_planning_apply(screen, data)

    def _shift_planning_inputs(self, screen: Any) -> _NoInputs:
        """Widget-dən oxunan YOXDUR: sürüşmə (`day_offset`) ARTIQ kontroller
        vəziyyətindədir (`self._shift_offset_days`, `set_shift_offset` ilə
        qurulur) — Qt-dən YENİDƏN oxunmur."""
        return _NoInputs()

    def _shift_planning_fetch(self, session: Session, _inputs: _NoInputs) -> _ShiftPlanningData:
        return self._render_shift_matrix_fetch(session, day_offset=self._shift_offset_days)

    def _shift_planning_apply(self, screen: Any, data: _ShiftPlanningData) -> None:
        self._render_shift_matrix_apply(screen, data)

    def shift_window_days(self, session: Session) -> int:
        """Matris pəncərəsinin uzunluğu — kontroller sürüşmə addımını bilməlidir."""
        return matrix_window_days(session)

    def set_shift_offset(self, day_offset: int) -> None:
        """Növbə matrisinin başlanğıcını sürüşdürür (irəli/geri naviqasiya).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ GÜN SÜRÜŞMƏSİ, NİYƏ TƏQVİM AYI
        ──────────────────────────────────────────────────────────────────────
        Ekranda «ay» oxları var, məlumat modeli isə BUGÜNDƏN başlayan
        SÜRÜŞƏN pəncərədir (`matrix_window_days`). Oxları təqvim ayına
        bağlasaydıq, iki fərqli anlayış bir idarəediciyə yığılardı: istifadəçi
        «Avqust» gözləyər, ekran isə 14 günlük pəncərə göstərərdi. Ona görə
        oxlar pəncərəni ÖZ uzunluğu qədər sürüşdürür — göstərilən aralıq
        başlıqda yazılır və vəd ilə nəticə üst-üstə düşür.
        """
        self._shift_offset_days = day_offset

    def _render_shift_matrix_fetch(
        self, session: Session, *, day_offset: int
    ) -> _ShiftPlanningData:
        today = date.today() + timedelta(days=day_offset)  # noqa: DTZ011
        window_days = matrix_window_days(session)
        end = today + timedelta(days=window_days)
        assignments = session.shift_planning.view_matrix(
            tenant_id=session.tenant_id,
            actor=self._actor,
            start=today,
            end=end,
        )
        # `set_matrix(days, rows)` İKİ arqument gözləyir: sütun başlıqları və
        # sətirlər. Əvvəl bura tək `dict` ötürülürdü — `TypeError` `populate()`
        # tərəfindən udulurdu və matris canlı rejimdə HƏMİŞƏ boş qalırdı.
        window = [today + timedelta(days=offset) for offset in range(window_days)]
        days = [(day.day, _WEEKDAYS_AZ[day.weekday()]) for day in window]
        # ETİKET CANLI YOLDA DA YAZILIR (QA-FULL Faza 3 tapıntısı): əvvəl
        # `set_month()`-u YALNIZ maket çağırırdı, istehsalatda isə toolbar-dakı
        # «‹ [aralıq] ›» HƏMİŞƏ BOŞ qalırdı — istifadəçi oxlarla gəzir, amma
        # hansı tarix aralığına baxdığını görmürdü. Dar setter işlədilir, çünki
        # `set_month()` iş rejimi nişanını da yazır və onu `shift_matrix.py`
        # ARTIQ doldurub (bax `set_window_label` başlığı).
        window_label = f"{window[0]:%d.%m.%Y} – {window[-1]:%d.%m.%Y}"

        by_employee: dict[str, dict[date, str]] = {}
        for item in assignments:
            name = _employee_name(session, item.employee_id)
            by_employee.setdefault(name, {})[item.shift_date] = "off" if item.is_off_day else "work"

        rows = [
            (name, [marks.get(day, "") for day in window])
            for name, marks in sorted(by_employee.items())
        ]
        return _ShiftPlanningData(
            window_label=window_label,
            days=days,
            rows=rows,
            staffing=self._shift_staffing_pattern_fetch(session),
        )

    def _render_shift_matrix_apply(self, screen: Any, data: _ShiftPlanningData) -> None:
        screen.set_window_label(data.window_label)
        screen.set_matrix(data.days, data.rows)
        self._shift_staffing_pattern_apply(screen, data.staffing)

    def _shift_staffing_pattern_fetch(self, session: Session) -> _ShiftStaffingPatternData:
        """#13 — Növbə Matrisinin QEYRİ-MƏCBURİ tarixi nümunə kartı.

        MAĞAZA SEÇİMİ: aktorun öz filialı, o yoxdursa (Root/CEO şəbəkə
        səviyyəsindədir) əlifba üzrə İLK aktiv mağaza. Rəqəmlərin hansı
        mağazaya aid olduğu kartın başlığında YAZILIR — əks halda 21 filiallı
        şəbəkədə göstərici mənasız olardı.

        MÜŞAHİDƏSİZ HAL SÜKUTLA KEÇİLMİR: mağaza tapılmasa da kart "tarixçə
        yoxdur" mətni ilə göstərilir (bax `set_staffing_pattern` docstring-i).
        """
        store_id, store_name = _default_store(session, self._actor)
        suggestions = (
            []
            if store_id is None
            else session.staffing_pattern.suggestions_for(session.tenant_id, store_id=store_id)
        )
        based_on_weeks = (
            suggestions[0].based_on_weeks
            if suggestions
            else int(DEFAULT_LIMITS[SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS])
        )
        calculated = (
            f"hesablandı: {suggestions[0].calculated_at.strftime('%d.%m.%Y')}"
            if suggestions
            else "hələ hesablanmayıb"
        )
        return _ShiftStaffingPatternData(
            rows=[
                (suggestion.weekday_label_az, suggestion.headcount_label_az())
                for suggestion in suggestions
            ],
            store_name=store_name,
            based_on_weeks=based_on_weeks,
            calculated_label=calculated,
        )

    def _shift_staffing_pattern_apply(self, screen: Any, data: _ShiftStaffingPatternData) -> None:
        screen.set_staffing_pattern(
            data.rows,
            store_name=data.store_name,
            based_on_weeks=data.based_on_weeks,
            calculated_label=data.calculated_label,
        )

    def _shift_swaps(self, session: Session, screen: Any) -> None:
        """FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır."""
        inputs = self._shift_swaps_inputs(screen)
        data = self._shift_swaps_fetch(session, inputs)
        self._shift_swaps_apply(screen, data)

    def _shift_swaps_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _shift_swaps_fetch(self, session: Session, _inputs: _NoInputs) -> _ShiftSwapsData:
        requests = session.shift_swaps.pending_inbox(tenant_id=session.tenant_id, actor=self._actor)
        # Açarlar ekranın FAKTİKİ gözlədikləridir: `id`, `from_name`, `to_name`,
        # `shift`, `store`, `status`, `note`. Əvvəl `employee`/`date` göndərilirdi
        # və kart `KeyError` ilə çökürdü — `populate()` isə istisnanı udurdu,
        # ona görə Növbə Dəyişmə inbox-u canlı rejimdə HƏMİŞƏ boş idi.
        rows = [
            {
                "id": str(item.id),
                "from_name": _employee_name(session, item.employee_id),
                # Sorğuda hədəf işçi YOXDUR — spesifikasiya (sətir 106)
                # yalnız "istədiyi tarix + səbəb" deyir; qərarı HR verir.
                "to_name": item.target_date.strftime("%d.%m.%Y"),
                "shift": item.target_date.strftime("%d.%m.%Y"),
                "store": _store_name(session, item.store_id) if item.store_id else "—",
                "status": _SWAP_STATUS_TEXT.get(item.status.value, item.status.value),
                "note": item.reason,
            }
            for item in requests
        ]
        return _ShiftSwapsData(pending_count=len(requests), rows=rows)

    def _shift_swaps_apply(self, screen: Any, data: _ShiftSwapsData) -> None:
        screen.set_counts({"pending": data.pending_count})
        screen.set_requests(data.rows)

    def _daily_roster(self, session: Session, screen: Any) -> None:
        """FAZA C (PERF-6, RİSKLİ) — naxış izahı `ScreenDataBinder` başlığındadır.

        ──────────────────────────────────────────────────────────────────────
        BU BİNDER OXU-YALNIZ DEYİL — `fetch` `session.commit()` ÇAĞIRIR
        ──────────────────────────────────────────────────────────────────────
        `open_sheet()` gündəlik tabeli AVTOMATİK statuslarla YARADIR (gizli
        yazı) — `_audit`/`populate_daily_roster_for_store` ilə EYNİ forma:
        CLAUDE.md-nin "yalnız oxuyan ekran `screen_data.py`-a bağlanır"
        cümləsi ilə uyğunsuzluq QƏSDƏN saxlanılır. Yazı `fetch` mərhələsində
        QALIR (fon sapında yazı problemsizdir), `apply` YENƏ YALNIZ Qt olur.

        `fetch`-in atdığı istisna BURADA TUTULMUR — `populate()`-un ÜMUMİ
        `SECTION_SCREEN` yoluna (bax onun başlığı) buraxılır, `_fine_appeals`/
        `_shift_planning`-dən FƏRQLİ olaraq `reraise=True` YOXDUR, çünki bu
        binder-i xüsusi `reraise` ilə çağıran YOXDUR.
        """
        inputs = self._daily_roster_inputs(screen)
        data = self._daily_roster_fetch(session, inputs)
        self._daily_roster_apply(screen, data)

    def _daily_roster_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _daily_roster_fetch(self, session: Session, _inputs: _NoInputs) -> _DailyRosterData:
        store_id = self._actor.store_id
        if store_id is None:
            return _DailyRosterData(rows=[], mismatch_text=None)

        view = session.daily_attendance.open_sheet(
            tenant_id=session.tenant_id, actor=self._actor, store_id=store_id
        )
        session.commit()  # gündəlik tabel YARADIR — bax bu metodun başlığı
        rows = [
            {
                "employee": _employee_name(session, line.employee_id),
                "status": line.auto_status.label_az,
                "note": line.manager_note or "",
            }
            for line in view.sheet.lines
        ]
        mismatch_text = (
            f"{view.mismatch_count} sətir HR planı ilə uyğun gəlmir — nəzərdən keçirin."
            if view.mismatch_count
            else None
        )
        return _DailyRosterData(rows=rows, mismatch_text=mismatch_text)

    def _daily_roster_apply(self, screen: Any, data: _DailyRosterData) -> None:
        screen.set_rows(data.rows)
        if data.mismatch_text is not None:
            screen.set_mismatch(data.mismatch_text)

    def _users(self, session: Session, screen: Any) -> None:
        """ "İstifadəçilər" cədvəli — QA-FULL Faza 3: "···" menyusunun görünürlüyü DƏ BURADA.

        `set_permitted_actions()` TƏK yerdə hesablanır (bax `controllers/
        user_lifecycle.py` başlığı): bu ekranın DÖRD yazan kontrolleri
        (`user_admin.py`, `pos_threshold.py`, `employee_documents.py`,
        `user_lifecycle.py`) `refresh()`-lərinin HAMISI bu funksiyadan
        keçir, ona görə icazə süzgəci hər kontrollerdə AYRI hesablansaydı
        biri digərinin nəticəsini sükutla üstələyərdi.

        ──────────────────────────────────────────────────────────────────────
        `is_active` SÜZGƏCİ — QA-FULL Faza 3, İSTİFADƏÇİNİN sözü ilə
        ──────────────────────────────────────────────────────────────────────
        İstifadəçi: «işçi işdən çıxsa, işçinin üstünə basıb xitam vermək
        lazımdır ki, ƏLAVƏ YER TUTMASIN». Əvvəl sorğuda `is_active` şərti
        YOX İDİ — deaktiv edilmiş işçi siyahıda ƏBƏDİ qalırdı, "Deaktiv Et"
        düyməsi işlədikdən SONRA belə heç nə DƏYİŞMİRDİ. Daha ciddisi:
        `LIMIT 500` süzgəcdən ƏVVƏL YOX (SQL-də `WHERE` HƏMİŞƏ `LIMIT`-dən
        əvvəl tətbiq olunur), amma ÖZÜ `is_active` şərti olmadan bütün
        (aktiv + deaktiv) sətirləri əhatə edirdi — uzun işləyən müştəridə
        işdən çıxmışlar toplanıb aktiv işçiləri 500-lük pəncərədən
        SIXIŞDIRA bilərdi (sükutlu məlumat itkisi: admin işçini "yoxdur"
        sanardı). `screen.status_filter()` DEFOLTDA `"active"`-dir —
        `UsersScreen` başlığındakı izaha bax.

        SOFT-DELETE FİZİKİ SİLMƏ DEYİL (CLAUDE.md §4/§6): deaktiv işçilər
        YOX EDİLMİR, YALNIZ defolt görünüşdən GİZLƏDİLİR — admin "Vəziyyət"
        seçicisi ilə "Deaktiv"/"Hamısı"na keçib onları YENƏ görə bilər.

        `LIMIT 500` ÖZÜ DƏ HƏLƏ QALIR (növbəti addım deyil, bu partiyanın
        əhatəsindən kənardır): 500-dən çox AKTİV işçisi olan müştəridə YENƏ
        DƏ risklidir. `is_active` süzgəci bu riski AZALDIR (deaktivlər artıq
        yer tutmur), amma LƏĞV ETMİR — səhifələmə/`OFFSET` ayrıca iş kimi
        qalır.

        ──────────────────────────────────────────────────────────────────────
        FAZA C (PERF-6) — `INPUTS` MƏRHƏLƏSİNİN İLK HƏQİQİ NÜMUNƏSİ
        ──────────────────────────────────────────────────────────────────────
        `screen.status_filter()` Qt-dən OXUYUR — `_fines`/`_help`-dəki `_NoInputs`
        BURADA İŞLƏMİR. `inputs` (`_users_inputs`) bu dəyəri ƏSAS SAPDA oxuyub
        `_UsersInputs`-a qoyur; `fetch` (`_users_fetch`) onu YALNIZ PARAMETR
        kimi alır, Qt-yə ÜMUMİYYƏTLƏ TOXUNMUR — FAZA D-də `fetch` fon sapına
        keçəndə Qt-dən sinxronlaşdırılmamış oxu (yazmaq qədər təhlükəli) baş
        VERMİR. Xam sətir → SQL şərti çevrilməsi (SABİT siyahıdan, CLAUDE.md
        §4) `fetch`-də QALIR — sorğu qurmaq DB narahatlığıdır, `inputs`-un işi
        deyil.
        """
        inputs = self._users_inputs(screen)
        data = self._users_fetch(session, inputs)
        self._users_apply(screen, data)

    def _users_inputs(self, screen: Any) -> _UsersInputs:
        return _UsersInputs(status_filter=screen.status_filter())

    def _users_fetch(self, session: Session, inputs: _UsersInputs) -> _UsersData:
        if inputs.status_filter == "inactive":
            status_clause = "NOT e.is_active"
        elif inputs.status_filter == "all":
            status_clause = "TRUE"
        else:  # "active" — DEFOLT (bax `_users` başlığı)
            status_clause = "e.is_active"
        rows = session.uow.connection.execute(
            f"""
            SELECT e.first_name, e.last_name, e.username, e.is_active,
                   COALESCE(p.name_az, '—') AS role_name,
                   COALESCE(s.name, '—')    AS store_name
            FROM employees e
            LEFT JOIN positions p ON p.id = e.position_id
            LEFT JOIN stores s    ON s.id = e.store_id
            WHERE e.tenant_id = %s AND {status_clause}
            ORDER BY e.last_name, e.first_name
            LIMIT 500
            """,  # noqa: S608 — şərtlər sabit siyahıdandır, dəyər %s ilə bağlanır
            (session.tenant_id,),
        ).fetchall()
        return _UsersData(
            permitted_actions=_permitted_user_actions(self._actor),
            rows=[
                {
                    # Açarlar ekranın FAKTİKİ gözlədikləridir (`user["full_name"]`,
                    # `user["username"]`) — əvvəl `name` göndərilirdi və sətir
                    # `KeyError` ilə çökürdü, istisna isə udulurdu.
                    "full_name": f"{row['first_name']} {row['last_name']}".strip(),
                    "username": row["username"],
                    "role": row["role_name"],
                    "store": row["store_name"],
                    "status": "Aktiv" if row["is_active"] else "Deaktiv",
                }
                for row in rows
            ],
        )

    def _users_apply(self, screen: Any, data: _UsersData) -> None:
        screen.set_permitted_actions(data.permitted_actions)
        screen.set_users(data.rows)

    def _fines(self, session: Session, screen: Any) -> None:
        """Operatorun izlədiyi filiallarda BU AYIN cərimələri.

        ──────────────────────────────────────────────────────────────────────
        PERF-6 FAZA B — İNPUTS/FETCH/APPLY NÜMUNƏSİ (Şell #1)
        ──────────────────────────────────────────────────────────────────────
        Bu, ÜÇ-MƏRHƏLƏLİ naxışın İKİ nümunəsindən BİRİDİR (`_help` digəridir) —
        naxışın ÖZÜ `_binders()`-in başlığındakı ÜMUMİ izahdadır. `_fines`-in
        `inputs` mərhələsi BOŞDUR (ekrandan oxunan HEÇ NƏ yoxdur) — bu, NAXIŞIN
        NORMAL halıdır (`_users`, PERF-6 FAZA A tapıntısı, boş OLMAYAN nümunədir).

        Siyahı `fines` cədvəlindən BİRBAŞA oxunur, use case-dən yox: burada
        biznes qərarı yoxdur, sadəcə göstəriş var və `ManualFineUseCase`-də
        "mağazaya görə aylıq siyahı" metodu mövcud deyil — onu yalnız bu ekran
        üçün əlavə etmək use case-i hesabat vasitəsinə çevirərdi.
        """
        inputs = self._fines_inputs(screen)
        data = self._fines_fetch(session, inputs)
        self._fines_apply(screen, data)

    def _fines_inputs(self, screen: Any) -> _NoInputs:
        """`inputs` mərhələsi — ƏSAS SAPDA, YALNIZ Qt OXUYUR.

        `_fines` heç bir widget dəyərindən ASILI DEYİL, ona görə `_NoInputs()`
        qaytarır (bax onun tərifi — `None` DEYİL, mypy səbəbi ilə). İmza YENƏ
        DƏ `screen`-i alır ki, ekrandan asılı olan bir binder (`_users` kimi)
        İNPUTS-u BURAYA əlavə edəndə çağırış yeri (`_fines`-in özü) DƏYİŞMƏSİN.
        """
        return _NoInputs()

    def _fines_fetch(self, session: Session, _inputs: _NoInputs) -> _FinesData:
        """`fetch` mərhələsi — FON SAPINA köçürüləcək hissə, Qt-yə TOXUNMUR."""
        stores = session.uow.repository("camera_assignments").stores_for_operator(self._actor.id)
        if not stores:
            return _FinesData(rows=[], period_text=_month_text(), total_text="0 ₼")

        today = datetime.now(UTC).date()
        rows = session.uow.connection.execute(
            """
            SELECT f.amount, f.fine_date, f.status,
                   -- SÜTUN ADI `name_az`-dır, `name` DEYİL (`schema.sql` §
                   -- fine_types). Səhv ad `UndefinedColumn` atırdı, istisna
                   -- isə `populate()`-da udulurdu — nəticədə «Cərimələr»
                   -- ekranı HƏMİŞƏ boş qalırdı və səbəb yalnız `error.log`-da
                   -- görünürdü. Kataloq repo-su (`catalog_repositories.py`)
                   -- və `_fine_type_name` onsuz da `name_az` oxuyur.
                   COALESCE(ft.name_az, '—') AS type_name,
                   e.first_name, e.last_name
              FROM fines f
              LEFT JOIN fine_types ft ON ft.id = f.fine_type_id
              LEFT JOIN employees  e  ON e.id = f.employee_id
             WHERE f.tenant_id = %s AND f.store_id = ANY(%s)
               AND EXTRACT(YEAR  FROM f.fine_date) = %s
               AND EXTRACT(MONTH FROM f.fine_date) = %s
             ORDER BY f.fine_date DESC
             LIMIT 200
            """,
            (session.tenant_id, list(stores), today.year, today.month),
        ).fetchall()

        total = sum(row["amount"] or 0 for row in rows)
        return _FinesData(
            rows=[
                {
                    "employee": _full_name(row),
                    "type": row["type_name"],
                    "date": row["fine_date"].strftime("%d.%m.%Y") if row["fine_date"] else "—",
                    "amount": f"{row['amount']} ₼",
                    "status": _FINE_STATUS_TEXT.get(str(row["status"]), str(row["status"])),
                }
                for row in rows
            ],
            period_text=_month_text(),
            total_text=f"{total} ₼",
        )

    def _fines_apply(self, screen: Any, data: _FinesData) -> None:
        """`apply` mərhələsi — ƏSAS SAPDA, YALNIZ Qt, DB-yə TOXUNMUR."""
        screen.set_fines(data.rows, period_text=data.period_text, total_text=data.total_text)

    # ------------------------------ Qrup F ----------------------------------- #

    def _fine_appeals(self, session: Session, screen: Any) -> None:
        """FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır.

        `fetch`-in atdığı `KompasOSError` BURADA TUTULMUR — `populate()`-un
        `reraise=True` yolu (`fine_appeals.py::refresh`) onu gözləyir (bax
        `populate()` başlığı). Üç-mərhələli çağırış zənciri istisnanı OLDUĞU
        KİMİ yuxarı ötürür, tutmaq DAVRANIŞI dəyişərdi.
        """
        inputs = self._fine_appeals_inputs(screen)
        data = self._fine_appeals_fetch(session, inputs)
        self._fine_appeals_apply(screen, data)

    def _fine_appeals_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _fine_appeals_fetch(self, session: Session, _inputs: _NoInputs) -> list[dict[str, str]]:
        appeals = session.fine_appeals.inbox(tenant_id=session.tenant_id, actor=self._actor)
        now = datetime.now(UTC)
        # SLA həddi ROOT İdarə Mərkəzindən gəlir (bölmə 3) — burada sabit
        # 72 yazmaq Root-un dəyişdirdiyi dəyəri sükutla yan keçərdi.
        key = SystemLimitKey.FINE_APPEAL_WINDOW_HOURS
        sla_hours = session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        # Açarlar `FineAppealInboxScreen`-in FAKTİKİ oxuduqlarıdır: `id`,
        # `employee`, `fine_type`, `amount`, `meta`, `explanation`. Əvvəl
        # `reason`/`age`/`overdue` göndərilirdi — kartlar boş sahələrlə
        # qurulurdu və `[Qəbul Et]` düyməsi BOŞ `id` yayırdı, yəni qərar
        # heç bir etiraza aid olmurdu.
        return [
            {
                "id": str(appeal.id),
                "employee": _employee_name(session, appeal.employee_id),
                "fine_type": _fine_type_name(session, appeal.fine_id),
                "amount": _fine_amount(session, appeal.fine_id),
                "meta": (
                    f"{appeal.age_hours(now=now):.0f} saatdır gözləyir"
                    + (" · SLA aşılıb" if appeal.is_overdue(now=now, sla_hours=sla_hours) else "")
                ),
                "explanation": appeal.reason,
            }
            for appeal in appeals
        ]

    def _fine_appeals_apply(self, screen: Any, rows: list[dict[str, str]]) -> None:
        screen.set_appeals(rows)

    def _tasks(self, session: Session, screen: Any) -> None:
        """FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır."""
        inputs = self._tasks_inputs(screen)
        data = self._tasks_fetch(session, inputs)
        self._tasks_apply(screen, data)

    def _tasks_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _tasks_fetch(self, session: Session, _inputs: _NoInputs) -> _TasksData:
        awaiting = session.uow.repository("tasks").list_awaiting_review(session.tenant_id)
        overdue = session.uow.repository("tasks").list_overdue(
            session.tenant_id, now=datetime.now(UTC)
        )
        return _TasksData(
            summary=f"{len(awaiting)} təsdiq gözləyir · {len(overdue)} gecikib",
            review=[
                {
                    # AÇAR `"id"`-DİR: `TaskCard.__init__` `task.get("id", "")`
                    # oxuyur. Bu sətir ƏVVƏL YOX İDİ (DEEP-GAP tapıntısı, bu
                    # dəyişikliklə tapıldı) — yəni `[Təsdiqlə]`/`[Rədd Et]`
                    # düymələri `TaskReviewController._on_approve/_on_reject`-ə
                    # HƏMİŞƏ boş sətir göndərirdi, `_parse_task_id("")` isə
                    # `ValueError` atıb tutulur və menecer HƏR kliklə "Tapşırıq
                    # identifikatoru düzgün deyil" xətası alırdı — düymələr
                    # görünürdü, LAKİN heç biri işləmirdi (`FineAppealScreen`-
                    # dəki `"fine_id"`/`"id"` qarışıqlığının EYNİSİ, bax
                    # `kiosk_self_service.py::_fine_rows` şərhi).
                    "id": str(task.id),
                    "title": task.title,
                    "assignee": _employee_name(session, task.assignee_id),
                    # `v2backlog.md` Faza 4.2 — öz-düzəliş sorğusunda (`task.
                    # assignee_id == self._actor.id`) `[Təsdiqlə]`/`[Rədd Et]`
                    # ÜMUMİYYƏTLƏ QURULMUR (bax `group_f.py::set_tasks`).
                    # Domendəki HƏQİQİ zəmanət `Task._require_not_self_review`-
                    # dədir — bu, YALNIZ görünüş qatıdır (team-lead göstərişi).
                    "reviewable": "0" if task.assignee_id == self._actor.id else "1",
                }
                for task in awaiting
            ],
            # Sütun açarları `TasksScreen._COLUMNS`-dandır: `open`/`review`/`done`.
            # Əvvəl "overdue" göndərilirdi — belə sütun YOXDUR və `KeyError`
            # udulurdu. Gecikmiş tapşırıq hələ AÇIQ tapşırıqdır; neçəsinin
            # gecikdiyi yuxarıdakı xülasə sətrindədir. Sahə adı `open_column`-
            # dur, `open` DEYİL — Python builtin-i kölgələməmək üçün.
            open_column=[
                {
                    "id": str(task.id),
                    "title": task.title,
                    "assignee": _employee_name(session, task.assignee_id),
                }
                for task in overdue
            ],
        )

    def _tasks_apply(self, screen: Any, data: _TasksData) -> None:
        screen.set_summary(data.summary)
        screen.set_tasks("review", data.review)
        screen.set_tasks("open", data.open_column)

    def _sales_points(self, session: Session, screen: Any) -> None:
        """Satış Xalları — İŞÇİNİN ÖZ balansı, tarixçəsi və kataloqu (bölmə 6).

        ──────────────────────────────────────────────────────────────────────
        SƏLAHİYYƏT DEYİL, SAHİBLİK
        ──────────────────────────────────────────────────────────────────────
        `SalesPointsUseCase.balance_for` səlahiyyət TƏLƏB ETMİR: işçinin öz
        balansına baxması onun hüququdur (bax use case başlığı). Ona görə
        burada `self._actor.id` işlədilir və "başqasının balansı" yolu
        ÜMUMİYYƏTLƏ yoxdur — kimin baxdığı sualı struktur olaraq bağlanıb.

        YAZI yolu (`appeal_requested`, `reward_requested`) burada QOŞULMUR:
        onlar `points_ledger`-ə yazır və hər yazıdan sonra siyahı yenidən
        oxunmalıdır, yəni öz kontrollerini tələb edir (CLAUDE.md bölmə 6).

        FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır. Köhnə
        kodda ÜÇ `screen.set_*` çağırışı fetch-lərin ARASINDA idi (balans →
        tarixçə sorğusu → tarixçə → kataloq); indi HAMISI `_sales_points_
        fetch`-də TOPLANIR, `_sales_points_apply`-da isə ARDICILLIQLA
        çağırılır — nəticə eynidir, çünki heç bir `apply` özündən SONRAKI
        fetch-in NƏTİCƏSİNDƏN asılı deyildi.
        """
        inputs = self._sales_points_inputs(screen)
        data = self._sales_points_fetch(session, inputs)
        self._sales_points_apply(screen, data)

    def _sales_points_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _sales_points_fetch(self, session: Session, _inputs: _NoInputs) -> _SalesPointsData:
        balance = session.sales_points.balance_for(self._actor.id, tenant_id=session.tenant_id)
        available = int(balance.available)
        # Kataloq BİR DƏFƏ oxunur və İKİ yerə gedir: «növbəti mükafat»
        # düsturuna və ekranın kataloq siyahısına (PERF-5 — əvvəl eyni sorğu
        # iki dəfə gedirdi, bax `_next_reward_gap`).
        catalog = list(session.sales_points.list_rewards_for_employee(session.tenant_id))
        to_next_reward, next_reward_cost = _next_reward_gap(
            session, session.tenant_id, available, rewards=[item for _reward_id, item in catalog]
        )
        monthly_delta = _monthly_points_delta(session, self._actor.id)
        rank_text = _points_rank_text(session, self._actor.id, period_start=balance.period.start)

        # Tarixçə `points_ledger`-dən BİRBAŞA oxunur: `PointsEntry` aqreqatı
        # `reason` MƏTNİNİ daşımır (o, yalnız "nə qədər xal qüvvədədir"
        # sualına cavab verir), ekran isə səbəb sütunu göstərir.
        rows = session.uow.connection.execute(
            """
            SELECT l.id, l.created_at, l.delta_points, l.reason, l.status,
                   a.status AS appeal_status
              FROM points_ledger l
              LEFT JOIN points_appeals a ON a.ledger_id = l.id
             WHERE l.tenant_id = %s AND l.employee_id = %s AND l.period_start = %s
             ORDER BY l.created_at DESC
             LIMIT 100
            """,
            (session.tenant_id, self._actor.id, balance.period.start),
        ).fetchall()
        history = [
            {
                "entry_id": str(row["id"]),
                "date": f"{row['created_at']:%d.%m}" if row["created_at"] else "—",
                "reason": str(row["reason"] or "—"),
                "status": _points_status_text(row),
                "points": _points_text(row["delta_points"], reversed_=_is_reversed(row)),
                # ETİRAZ PƏNCƏRƏSİNİ DOMEN HESABLAYIR: ekran 72 saatı TƏKRAR
                # hesablamır (iki mənbə sükutla ayrılardı) — burada yalnız
                # mövcud etirazın OLMAMASI yoxlanılır, qalan şərti
                # `open_dispute` özü tətbiq edir.
                "can_appeal": "0" if row["appeal_status"] else "1",
            }
            for row in rows
        ]

        return _SalesPointsData(
            available=available,
            monthly_delta=monthly_delta,
            to_next_reward=to_next_reward,
            next_reward_cost=next_reward_cost,
            rank_text=rank_text,
            history=history,
            history_period=_month_text(),
            # AÇARLAR MAKET YOLU İLƏ EYNİDİR (`preview_screens._sales_points`):
            # `id` mükafat sorğusunun YEGANƏ etibarlı açarıdır — ad təkrarlana
            # bilər, `request_reward` isə `reward_id` tələb edir.
            catalog=[
                {"id": str(reward_id), "name": item.name, "cost": str(item.cost_points)}
                for reward_id, item in catalog
            ],
        )

    def _sales_points_apply(self, screen: Any, data: _SalesPointsData) -> None:
        screen.set_balance(
            data.available,
            monthly_delta=data.monthly_delta,
            to_next_reward=data.to_next_reward,
            next_reward_cost=data.next_reward_cost,
            rank_text=data.rank_text,
        )
        # `period=` — `SalesPointsScreen.set_history`-nin FAKTİKİ açar adıdır
        # (`_fines`-dəki `period_text=` BAŞQA ekrandır). Səhv ad `TypeError`
        # verərdi və `populate()` onu udardı: tarixçə canlı rejimdə həmişə
        # boş qalardı.
        screen.set_history(data.history, period=data.history_period)
        screen.set_catalog(data.catalog, balance=data.available)

    # ------------------------------ Qrup D/H --------------------------------- #

    def _help(self, session: Session, screen: Any) -> None:
        """Yardım Mərkəzi — mövzular GÖRÜNƏN modullara görə süzülür.

        ──────────────────────────────────────────────────────────────────────
        PERF-6 FAZA B — İNPUTS/FETCH/APPLY NÜMUNƏSİ (Şell #2)
        ──────────────────────────────────────────────────────────────────────
        `_fines`-in şərhindəki İZAHA bax — naxışın ÖZÜ ORADA yazılıb, təkrar
        edilmir. `_help`-in FƏRQİ: köhnə kodda fail-open budağı `except`
        İÇİNDƏN BİRBAŞA `screen.set_visible_topics(None)` çağırırdı — yəni
        Qt çağırışı `fetch`-in daxilində idi. İndi `fetch` `None`-u DATA kimi
        QAYTARIR, `apply` isə onu OLDUĞU KİMİ ötürür — `HelpCenterScreen.
        set_visible_topics(None)`-un ÖZÜ fail-open MƏNASINI daşıyır (bax
        aşağı), ona görə `apply`-da əlavə şərt LAZIM DEYİL.

        ──────────────────────────────────────────────────────────────────────
        AÇARLAR TOGGLE CƏDVƏLİ İLƏ EYNİDİR
        ──────────────────────────────────────────────────────────────────────
        Süzgəc `FeatureModule` dəyərləri üzərində işləyir — `feature_toggles`
        cədvəlinin və `shell/menu.py`-ın işlətdiyi EYNİ açarlar. Burada öz ad
        məkanımızı qursaydıq (məs. `"fines"` ↔ `"FINE_MODULE"`), uyğunsuzluq
        maketdə görünməz qalar və yalnız istehsalatda üzə çıxardı — layihədə
        məhz bu qüsur olub (bax `menu.py` başlığı).

        Toggle mənbəyi oxunmasa BÜTÜN mövzular göstərilir (fail-open): yardım
        mətnini gizlətmək dəstək yükünü artırar, azaltmaz (bax
        `HelpCenterScreen` başlığı) — bu, naviqasiyadakı `_enabled_modules`
        ilə eyni istiqamətdir.
        """
        inputs = self._help_inputs(screen)
        data = self._help_fetch(session, inputs)
        self._help_apply(screen, data)

    def _help_inputs(self, screen: Any) -> _NoInputs:
        """`_fines_inputs` ilə EYNİ səbəb: `_help` widget dəyərindən ASILI DEYİL."""
        return _NoInputs()

    def _help_fetch(self, session: Session, _inputs: _NoInputs) -> frozenset[str] | None:
        """`fetch` — FON SAPINA köçürüləcək hissə. `None` = fail-open (bax başlıq)."""
        try:
            enabled = frozenset(session.toggles.enabled_modules(session.tenant_id))
        except Exception:
            # BANNER QOYULMUR VƏ BU, QƏSDƏNDİR: fail-open istifadəçiyə DAHA AZ
            # deyil, DAHA ÇOX mövzu göstərir — yəni burada nə boş ekran, nə də
            # yalan rəqəm var. «Yüklənə bilmədi» xəbərdarlığı yardım mətnini
            # oxuyan adamı əsassız narahat edərdi; səbəb `error.log`-dadır.
            # Loglamaq Qt ÇAĞIRIŞI DEYİL — fon sapında qalması TƏHLÜKƏSİZDİR.
            _error_log.exception("HELP_TOGGLES_LOAD_FAILED")
            return None

        return frozenset(
            topic
            for topic, module in HELP_TOPIC_MODULES.items()
            if module is None or module in enabled
        )

    def _help_apply(self, screen: Any, visible_topics: frozenset[str] | None) -> None:
        """`apply` — ƏSAS SAPDA, YALNIZ Qt, DB-yə TOXUNMUR."""
        screen.set_visible_topics(visible_topics)

    def _health(self, session: Session, screen: Any) -> None:
        """Sistem Sağlamlığı — YALNIZ FAKTİKİ ölçülən göstəricilər (bölmə 6).

        ──────────────────────────────────────────────────────────────────────
        YENİ İŞ QAYDASI İCAD EDİLMİR
        ──────────────────────────────────────────────────────────────────────
        Bu ekranın öz use case-i YOXDUR və olmamalıdır: burada heç bir qərar
        verilmir, mövcud mənbələr bir yerə yığılır — baza cavab müddəti,
        `NtpVerifier` sürüşməsi, offline bufer sayğacı, `sync_conflicts` və
        `v_erp_server_health`. Hər rəqəmin arxasında REAL ölçmə var.

        ──────────────────────────────────────────────────────────────────────
        ÖLÇÜLƏ BİLMƏYƏN GÖSTƏRİCİ GÖSTƏRİLMİR
        ──────────────────────────────────────────────────────────────────────
        Maketdə «Disk (server)» kartı var, lakin tətbiqdə server diskini
        ölçən mənbə YOXDUR. Onu `0%` və ya "naməlum" ilə göstərmək monitorinq
        ekranının ƏSAS məqsədini pozardı: burada göstərilən hər rəqəm etibarlı
        olmalıdır. NTP sürüşməsi də ölçülməyibsə (`_NullNtp`) kart
        ÜMUMİYYƏTLƏ qurulmur — `0.0 san` "saat dəqiqdir" kimi oxunardı.

        ──────────────────────────────────────────────────────────────────────
        FAZA C (PERF-6) — QƏRAR 2: BEŞ KÖMƏKÇİ ARTIQ `screen` ALMIR
        ──────────────────────────────────────────────────────────────────────
        `_health_metrics`, `_offline_pending`, `_open_conflicts_or_none`,
        `_health_alerts`, `_critical_notifications` əvvəl HƏRƏSİ ÖZ
        uğursuzluğunda birbaşa `report_section_error(screen, …)` çağırırdı —
        Qt çağırışı fetch-in daxilində idi. İndi hər biri uğursuzluğu SAF
        `SectionFailure` (bax onun tərifi) kimi QAYTARIR, `_health_apply`
        isə onları bannerə çevirir. `SectionFailure` `_health`-ə XAS DEYİL —
        FAZA D-də `_fill_section` EYNİ tipi işlədəcək (dashboard-ın
        səpələnmiş bölmə banner-lərini bir mexanizmə yığmaq üçün).

        BANNER SIRASI QORUNUR: köhnə kodda banner çağırışları müvafiq
        `screen.set_*` çağırışından DƏRHAL ƏVVƏL gəlirdi (arqument
        qiymətləndirilməsi setter-dən əvvəl baş verdiyi üçün) — `_health_
        apply` bu sıranı AÇIQ təkrarlayır (aşağı bax), tək fərq banner
        çağırışının artıq FETCH-dən deyil, APPLY-dan getməsidir.
        """
        inputs = self._health_inputs(screen)
        data = self._health_fetch(session, inputs)
        self._health_apply(screen, data)

    def _health_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _health_fetch(self, session: Session, _inputs: _NoInputs) -> _HealthData:
        # Sayğac BİR dəfə oxunur və ÜÇ yerə gedir: rəqəm kartına, xəbərdarlıq
        # mətninə və «… konflikti həll et» keçidinə. Ayrı-ayrı `SELECT
        # count(*)` eyni rəqəmi verərdi, lakin oxunuşlar arasında paralel həll
        # baş versə kart, mətn və keçid bir-birinə ZİDD danışardı. Oxunuş ƏN
        # ƏVVƏLƏ çəkilib ki, hər üç istifadəçi eyni dəyəri alsın.
        #
        # `None` = OXUNA BİLMƏDİ (sıfır DEYİL) — bax `_open_conflicts_or_none`.
        conflicts, conflicts_failure = _open_conflicts_or_none(session)

        metrics, offline_failure = _health_metrics(session, self._context, open_conflicts=conflicts)
        latencies = _health_latencies(session)
        alerts, notifications_failure = _health_alerts(
            session, self._actor, open_conflicts=conflicts or 0
        )

        return _HealthData(
            last_check_text=f"Son yoxlama: {_hhmm(datetime.now(UTC))}",
            conflicts_failure=conflicts_failure,
            metrics=metrics,
            offline_failure=offline_failure,
            latencies=latencies,
            alerts=alerts,
            notifications_failure=notifications_failure,
            # OXUNA BİLMƏYƏN SAYĞAC KEÇİD QURMUR: «0 konflikti həll et» keçidi
            # istifadəçini boş ekrana aparardı və sayğacın etibarlı olduğunu
            # təsdiqləyərdi. Xəbərdarlıq bannerdədir.
            conflict_action=conflicts if conflicts and self._may_resolve_conflicts() else 0,
        )

    def _health_apply(self, screen: Any, data: _HealthData) -> None:
        if data.conflicts_failure is not None:
            report_section_error(screen, data.conflicts_failure.section)
        screen.set_last_check(data.last_check_text)
        if data.offline_failure is not None:
            report_section_error(screen, data.offline_failure.section)
        screen.set_metrics(data.metrics)
        screen.set_latencies(data.latencies)
        if data.notifications_failure is not None:
            report_section_error(screen, data.notifications_failure.section)
        screen.set_alerts(data.alerts)
        screen.set_conflict_action(data.conflict_action)

    def _audit(self, session: Session, screen: Any) -> None:
        """FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır.

        ──────────────────────────────────────────────────────────────────────
        BU BİNDER OXU-YALNIZ DEYİL — `fetch` `session.commit()` ÇAĞIRIR
        ──────────────────────────────────────────────────────────────────────
        Audit sorğusunun ÖZÜ audit-lənir (`audit_query`-nin öz qərarı, §5-in
        qəsdli zəmanətinin nəticəsi: "baxış faktı" da jurnala düşür). Bu, CLAUDE.
        md-nin "yalnız oxuyan ekran `screen_data.py`-a bağlanır" cümləsi ilə
        UYĞUN GƏLMİR — uyğunsuzluq QƏSDƏN saxlanılır (PERF-6 FAZA A/B qərarı).
        Yazı `fetch` mərhələsində QALIR (fon sapında yazı problemsizdir, `app.
        py::_run_scheduled_jobs` da belə edir), `apply` isə YENƏ YALNIZ Qt olur.
        """
        inputs = self._audit_inputs(screen)
        data = self._audit_fetch(session, inputs)
        self._audit_apply(screen, data)

    def _audit_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _audit_fetch(self, session: Session, _inputs: _NoInputs) -> _AuditData:
        page = session.audit_query.search(tenant_id=session.tenant_id, actor=self._actor)
        session.commit()  # baxış faktı da audit-lənir (bax `audit_query`) — YAZI, bax başlıq
        # AÇARLAR `controllers/audit_log.entry_row`-DAN GƏLİR: burada əvvəllər
        # `actor`/`entity`/`reason` yazılırdı, halbuki `AuditScreen.set_entries`
        # `user`/`module`/`detail` oxuyur — nəticədə canlı rejimdə cədvəlin üç
        # sütunu BOŞ qalırdı, maketdə isə dolu görünürdü. Bu, CLAUDE.md bölmə
        # 6-dakı "maket və canlı yol EYNİ AÇARLARI işlətməlidir" qaydasının
        # pozulmasının dəqiq nümunəsidir; ona görə forma indi tək funksiyadadır.
        return _AuditData(
            entries=[entry_row(entry) for entry in page.entries],
            result_text=f"{len(page.entries)} nəticə",
        )

    def _audit_apply(self, screen: Any, data: _AuditData) -> None:
        # `result_text` MƏCBURİ açar-arqumentdir — onsuz `TypeError` atılırdı
        # və audit ekranı canlı rejimdə boş qalırdı (istisna udulurdu).
        screen.set_entries(data.entries, result_text=data.result_text)

    def _reports(self, session: Session, screen: Any) -> None:
        """FAZA C (PERF-6) — naxış izahı `ScreenDataBinder` başlığındadır."""
        inputs = self._reports_inputs(screen)
        data = self._reports_fetch(session, inputs)
        self._reports_apply(screen, data)

    def _reports_inputs(self, screen: Any) -> _NoInputs:
        return _NoInputs()

    def _reports_fetch(self, session: Session, _inputs: _NoInputs) -> _ReportsData:
        today = date.today()  # noqa: DTZ011

        # Bölmə 6 LOCK MEXANİZMİ: pəncərəsi hələ açıq cərimələr bu ayın
        # export-una DÜŞMÜR — ekran bunu AÇIQ göstərməlidir.
        #
        # `list_exportable` DEYİL, `list_in_range` (kompas1.md Faza 8): birinci
        # metod üç LOCK şərtini SQL-də tətbiq edir və artıq tutulmuş cərimələri
        # ÜMUMİYYƏTLƏ qaytarmır — nəticədə `already_exported_count` həmişə sıfır
        # olardı və üst-üstə düşən aralıqda atlanan cərimə ekranda GÖRÜNMƏZDİ
        # (bax `ports.py::RangeScopedFineReader` başlığı). LOCK ZƏİFLƏMİR:
        # qərarı yenə `Fine.is_exportable(now=...)` verir.
        start = today.replace(day=1)
        facts = session.report_facts.sales_facts(session.tenant_id, start=start, end=today)
        fines = session.uow.fines.list_in_range(session.tenant_id, start=start, end=today)
        selection = session.reports.build_bonus_penalty(
            actor=self._actor,
            facts=facts,
            fines=fines,
            now=datetime.now(UTC),
        )
        return _ReportsData(
            period_text=f"{today:%m.%Y}",
            deferred_fine_count=selection.deferred_fine_count,
            already_exported=selection.already_exported_count,
            overlap_notice=selection.overlap_notice_az() or "",
        )

    def _reports_apply(self, screen: Any, data: _ReportsData) -> None:
        screen.set_period(data.period_text)
        screen.set_lock_summary(
            data.deferred_fine_count,
            already_exported=data.already_exported,
            overlap_notice=data.overlap_notice,
        )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def perform_ranking_drill_down(
    store_id_text: str,
    *,
    show_screen: Callable[[str], bool],
    screen_for: Callable[[str], Any | None],
    populate: Callable[[StoreId, Any], None],
) -> bool:
    """Reytinq Cədvəlinin DRILL-DOWN qərarı — SAF funksiya, Qt TƏLƏB ETMİR.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `app.py`-DAN ÇIXARILIB
    ──────────────────────────────────────────────────────────────────────────
    Naviqasiya qərarının ÖZÜ ("hansı açar, hansı sıra ilə") biznes məntiqidir
    və `QApplication` tələb etməməlidir. `app.py`-dakı `_on_ranking_row_
    selected` bu funksiyanı `AdminShell.show_screen`/`screen_for` VƏ
    (Mərhələ 3-dən) `app.py::_start_ranking_drill_down_fetch`-i `populate`
    kimi ötürərək çağırır — YENİ naviqasiya qatı YOXDUR, sadəcə MÖVCUD
    collaborator-lar (bax arqumentlər) bir yerdə çağırılır. `populate`-in
    ÖZÜ İNDİ sinxron DEYİL (bax onun başlığı) — bu funksiya bunu BİLMİR VƏ
    BİLMƏMƏLİDİR: o, YALNIZ `populate(store_id, screen)`-i ÇAĞIRIR, nəyin
    ARXASINDA (sinxron tətbiq, yoxsa fon işinin BAŞLADILMASI) olduğu ilə
    maraqlanmır — sərhəd HƏMİŞƏ ÇAĞIRANDA (bax `Returns` altındakı qeyd).

    Args:
        store_id_text: Klik edilən sətrin mağaza ID-si (mətn, `RankingEntry.
            store_id`).
        show_screen: `AdminShell.show_screen` — mövcud ekrana keçid.
        screen_for: `AdminShell.screen_for` — keçiddən SONRA instansiyanı tapır.
        populate: KLİKLƏNƏN mağaza ilə doldurma çağırışı — `ScreenDataBinder.
            populate_daily_roster_for_store` (sinxron) VƏ YA `app.py::_start_
            ranking_drill_down_fetch` (fon işini BAŞLADIR, tətbiq gec gəlir)
            OLA BİLƏR; bu funksiya İKİSİNİ DƏ EYNİ CÜR çağırır.

    Returns:
        Bütün addımlar uğurlu olduqda `True`. Yararsız ID, gizli ekran və ya
        hələ qurulmamış instansiya SƏSSİZCƏ `False` qaytarır — çağıran tərəf
        bunu jurnala yaza bilər, lakin bu funksiya İSTİSNA ATMIR (klik hadisə
        idarəedicisidir, çökmə istifadəçini bütün paneldən məhrum edərdi).

    ──────────────────────────────────────────────────────────────────────────
    FAZA D (PERF-6, Mərhələ 3) — SƏRHƏD BURADA DEYİL, `populate`-İN İÇİNDƏDİR
    ──────────────────────────────────────────────────────────────────────────
    Bu funksiyanın ÖZÜ nə DB, nə Qt widget-inə TOXUNUR — o, `show_screen`/
    `screen_for` (Qt naviqasiya) ilə `populate` arasında SADƏ körpüdür.
    Fetch/apply sap sərhədi ARTIQ `populate`-in ÖZÜNDƏ (çağıran tərəfin
    verdiyi funksiyada) HƏLL OLUNUB — bura ƏLAVƏ struktur ƏLAVƏ ETMƏK YALNIZ
    eyni şeyi iki yerdə ifadə edərdi.

    SIRA BURADA QORUNUR VƏ BU, KRİTİKDİR: aşağıdakı sətir sırası (əvvəl
    `show_screen`, SONRA `screen_for`, SONRA `populate`) DƏYİŞDİRİLƏ BİLMƏZ
    — `screen_for()` yalnız `show_screen()`-dən SONRA doğru instansiyanı
    qaytarır (əvvəl heç qurulmamış ekranın widget-i YOXDUR). `populate`
    ARTIQ fon işini BAŞLADA BİLdiyi üçün (bax `app.py::_start_ranking_
    drill_down_fetch`) bu sıranın pozulması "yanlış ekrana yazma" yox,
    "HEÇ NƏYƏ yazmama" (`screen_for()` `None` qaytarardı, `if screen is
    None: return False` bunu artıq TUTUR) və ya STALE widget-ə yazma riski
    yaradardı — SIRA saxlanıldığı üçün heç biri BAŞ VERMİR.
    """
    try:
        store_id = StoreId(uuid.UUID(store_id_text))
    except ValueError:
        return False
    if not show_screen(DAILY_ROSTER_SCREEN_KEY):
        return False
    screen = screen_for(DAILY_ROSTER_SCREEN_KEY)
    if screen is None:
        return False
    populate(store_id, screen)
    return True


def late_threshold_minutes(session: Session) -> int:
    """Növbə sətrinin "gecikib" sayıldığı hədd — CANLI limitdən hesablanır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SABİT DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Hədd `VERIFICATION_TIMEOUT_MINUTES`-in YARISIDIR: operator eskalasiya baş
    verməmişdən ƏVVƏL reaksiya verə bilsin. Bu münasibət sabit yazılsaydı
    (22 = 45 / 2), yalnız yazıldığı gün doğru olardı — Root timeout-u 20
    dəqiqəyə endirən kimi eskalasiya 20-də baş verər, xəbərdarlıq isə hələ
    22-də görünərdi, yəni operator siqnalı GECİKMİŞ alardı.

    Eyni naxış `_fine_appeals`-dakı `FINE_APPEAL_WINDOW_HOURS` üçün də
    işlədilir — limit oxunuşunun tək düzgün forması budur.

    Ən azı 1 dəqiqə qaytarılır: Root timeout-u 1 dəqiqəyə salsa, `45 // 2`
    məntiqi 0 verərdi və HƏR sətir doğulan anda "gecikmiş" görünərdi — belə
    bir siyahıda xəbərdarlıq rəngi heç nə demir.
    """
    key = SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES
    try:
        timeout = int(
            session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        )
    except Exception:
        # Limit mənbəyi cavab vermədi — sabit FALLBACK işə düşür. Xəbərdarlığı
        # tamamilə söndürmək (məs. `sys.maxsize`) növbəni "hər şey qaydasında"
        # kimi göstərərdi, halbuki problem yalnız konfiqurasiya oxunuşundadır.
        _error_log.warning(
            "QUEUE_LATE_THRESHOLD_FALLBACK",
            extra={"minutes": LATE_QUEUE_MINUTES, "limit_key": key.value},
        )
        return LATE_QUEUE_MINUTES
    return max(1, timeout // 2)


def matrix_window_days(session: Session) -> int:
    """Növbə matrisinin göstərdiyi gün sayı — CANLI limitdən.

    `late_threshold_minutes` ilə EYNİ naxış (limit oxunuşunun tək düzgün
    forması): dəyər hər doldurmada oxunur, çünki panel saatlarla açıq qala
    bilər və Root pəncərəni bu müddət ərzində dəyişə bilər.

    Ən azı 1 gün qaytarılır: `0` yazılsaydı `range(0)` boş pəncərə verər,
    matris SÜTUNSUZ görünər və istifadəçi "məlumat yoxdur" ilə "pəncərə
    sıfırdır" arasındakı fərqi ekranda GÖRƏ BİLMƏZDİ (DB-dəki `min_value` ROOT
    ekranını qoruyur; bu, birbaşa SQL ilə düşən dəyərə qarşı son xətdir).
    """
    key = SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS
    try:
        days = int(session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key])))
    except Exception:
        _error_log.warning(
            "SHIFT_MATRIX_WINDOW_FALLBACK",
            extra={"days": FALLBACK_MATRIX_WINDOW_DAYS, "limit_key": key.value},
        )
        return FALLBACK_MATRIX_WINDOW_DAYS
    return max(1, days)


def _next_month(month_start: date) -> date:
    """Ayın SONU yarı-açıq aralıq kimi — `< next_month`.

    `<= ayın son günü` yazsaydıq, `TIMESTAMPTZ` sütunlarda həmin günün
    saatları kəsilərdi; `DATE` və `TIMESTAMPTZ` sütunlar eyni sorğuda
    işlədildiyi üçün TƏK forma seçilib.
    """
    return (
        date(month_start.year + 1, 1, 1)
        if month_start.month == 12  # noqa: PLR2004 — dekabr ilin son ayıdır
        else date(month_start.year, month_start.month + 1, 1)
    )


def _previous_month(month_start: date) -> date:
    return (
        date(month_start.year - 1, 12, 1)
        if month_start.month == 1
        else date(month_start.year, month_start.month - 1, 1)
    )


def _earliest(*moments: Any) -> datetime | None:
    """Verilənlərdən ən KÖHNƏSİ — hamısı `None`-dursa `None`."""
    values = [moment for moment in moments if isinstance(moment, datetime)]
    return min(values) if values else None


def _fine_month_totals(
    session: Session, *, month_start: date, next_month: date, previous_month: date
) -> tuple[str, str]:
    """(bu ayın cəmi, keçən aya nisbətən dəyişmə mətni).

    Faiz KEÇƏN AY sıfır olduqda hesablanmır — "+∞%" mənasız göstəricidir və
    ilk ay hər quraşdırmada belədir. Həmin halda müqayisə əvəzinə vəziyyət
    yazılır ("keçən ay cərimə olmayıb").
    """
    row = session.uow.connection.execute(
        """
        SELECT
          (SELECT COALESCE(SUM(amount), 0) FROM fines
            WHERE tenant_id = %s AND fine_date >= %s AND fine_date < %s) AS current_total,
          (SELECT COALESCE(SUM(amount), 0) FROM fines
            WHERE tenant_id = %s AND fine_date >= %s AND fine_date < %s) AS previous_total
        """,
        (
            session.tenant_id,
            month_start,
            next_month,
            session.tenant_id,
            previous_month,
            month_start,
        ),
    ).fetchone()
    current = float((row or {}).get("current_total") or 0)
    previous = float((row or {}).get("previous_total") or 0)

    total_text = f"{current:,.0f} ₼".replace(",", " ")
    if previous <= 0:
        return (total_text, "keçən ay cərimə olmayıb")
    change = (current - previous) / previous * 100
    return (total_text, f"keçən aya nisbətən {change:+.0f}%")


def _sync_delay_text(seconds: Any) -> str:
    """Sinxronizasiya gecikməsi — saniyə/dəqiqə/saat.

    `None` "heç vaxt sinxronlaşmayıb" deməkdir və `0 san` kimi göstərilmir:
    sıfır gecikmə ideal vəziyyətdir, məlumatsızlıq isə problem əlamətidir.
    """
    if seconds is None:
        return "sinxronlaşmayıb"
    value = int(seconds)
    if value < 60:  # noqa: PLR2004 — bir dəqiqə
        return f"{value} san"
    if value < 3600:  # noqa: PLR2004 — bir saat
        return f"{value // 60} dəq"
    return f"{value // 3600} saat"


def _points_text(delta: Any, *, reversed_: bool = False) -> str:
    """Xal sətri — işarə ilə BİRLİKDƏ (rəng tək daşıyıcı deyil).

    Geri alınmış sətir MƏNFİ işarə ilə göstərilir: ledger-də dəyər müsbət
    qalır (`points_ledger` sətri silinmir, yalnız `REVERSED` olur), lakin
    işçinin balansına təsiri çıxılmadır — ekranda müsbət göstərmək "xal
    hələ məndədir" deyə oxunardı.
    """
    value = int(delta or 0)
    sign = "−" if reversed_ else "+"
    return f"{sign}{abs(value)}"


def _is_reversed(row: Any) -> bool:
    return str(row["status"]) == "REVERSED"


def _points_status_text(row: Any) -> str:
    """Ekranın `_HISTORY_TONES` açarları: «Təsdiqli» / «Gözləyir» / «Geri alınıb».

    Sıra vacibdir: geri alınmış sətrin açıq etirazı ola bilməz, lakin
    etirazı GÖZLƏYƏN sətir hələ qüvvədədir — ona görə `REVERSED` əvvəl
    yoxlanılır.
    """
    if _is_reversed(row):
        return "Geri alınıb"
    if str(row["appeal_status"] or "") == "PENDING":
        return "Gözləyir"
    return "Təsdiqli"


def _next_reward_gap(
    session: Session, tenant_id: Any, available: int, *, rewards: list[Any] | None = None
) -> tuple[int, int]:
    """`(to_next_reward, next_reward_cost)` — "Növbəti mükafat" düsturu.

    Balansı hələ ÇATMAYAN ən ucuz mükafat götürülür. Hamısı əlçatandırsa ən
    BAHALI götürülür ki, ölçən 100%-də dolu görünsün — sıfır dəyər ölçəni
    "hədəf yoxdur" halında bölmə xətasına salardı. `_sales_points` VƏ
    `points_balance_summary` bu düsturu PAYLAŞIR (bax aşağıdakı başlıq) —
    balans obyektini hər çağıran ÖZÜ gətirir ki, əlavə `balance_for`
    sorğusu yaranmasın.

    `rewards` ARQUMENTİ NİYƏ VAR (PERF-5, canlı ölçü): `_sales_points` mükafat
    kataloqunu ONSUZ DA oxuyur (ekranın `set_catalog` çağırışı üçün) — bu
    funksiya isə EYNİ `SELECT ... FROM rewards` sorğusunu İKİNCİ dəfə
    göndərirdi. Ölçü: «Satış Xalları» 8 sorğudan biri məhz bu təkrar idi
    (~206 ms). Kataloq verilməyibsə (kiosk kartı — `points_balance_summary`)
    davranış DƏYİŞMİR: funksiya onu özü oxuyur.
    """
    catalog = (
        rewards
        if rewards is not None
        else [
            item for _reward_id, item in session.sales_points.list_rewards_for_employee(tenant_id)
        ]
    )
    out_of_reach = sorted(item.cost_points for item in catalog if item.cost_points > available)
    next_cost = (
        out_of_reach[0] if out_of_reach else max((item.cost_points for item in catalog), default=0)
    )
    return max(0, next_cost - available), next_cost


def points_balance_summary(session: Session, employee_id: Any) -> tuple[int, int, int]:
    """Balans + aylıq dəyişim + növbəti mükafata qalan xal.

    `_sales_points` (Xallarım ekranı) VƏ `KioskSelfServiceController`-in İşçi
    Ana Ekranındakı «Xal Balansım» kartı EYNİ rəqəmi göstərməlidir (bölmə 3,
    6) — ikisi düsturu ayrı-ayrı yazsaydı, biri dəyişəndə digəri arxada
    qalardı və eyni işçi iki fərqli balans görərdi (DEEP-GAP U5-in özü məhz
    bu qüsurun bir forması idi: kart tamamilə doldurulmurdu).
    """
    balance = session.sales_points.balance_for(employee_id, tenant_id=session.tenant_id)
    available = int(balance.available)
    to_next_reward, _next_cost = _next_reward_gap(session, session.tenant_id, available)
    return available, _monthly_points_delta(session, employee_id), to_next_reward


def _monthly_points_delta(session: Session, employee_id: Any) -> int:
    """Bu TƏQVİM ayında qazanılan xal — kartdakı «Bu ay +N xal».

    Dövr (6 aylıq) deyil, AY götürülür: kart aylıq tempi göstərir, balans
    isə onsuz da dövrə görə hesablanır (`balance_for`).
    """
    today = datetime.now(UTC).date()
    month_start = today.replace(day=1)
    row = session.uow.connection.execute(
        """
        SELECT COALESCE(SUM(delta_points), 0) AS total
          FROM points_ledger
         WHERE tenant_id = %s AND employee_id = %s
           AND status <> 'REVERSED'
           AND created_at >= %s AND created_at < %s
        """,
        (session.tenant_id, employee_id, month_start, _next_month(month_start)),
    ).fetchone()
    return int((row or {}).get("total") or 0)


def _points_rank_text(session: Session, employee_id: Any, *, period_start: date) -> str:
    """«N nəfər arasında K-cı» — İŞÇİNİN ÖZ FİLİALI üzrə.

    Filial daxilində müqayisə edilir, tenant miqyasında yox: 21 filialda
    235 nəfər arasında sıra işçi üçün mənasız rəqəmdir və satış həcmi
    filialdan filiala fərqlənir. Sətir `sales_transactions.store_id`
    üzərindən bağlanır, çünki xal həmişə bir satışdan doğur.
    """
    row = session.uow.connection.execute(
        """
        WITH totals AS (
            SELECT e.id, SUM(l.delta_points) AS total
              FROM points_ledger l
              JOIN employees e ON e.id = l.employee_id
             WHERE l.tenant_id = %s AND l.period_start = %s AND l.status <> 'REVERSED'
               AND e.store_id = (SELECT store_id FROM employees WHERE id = %s)
             GROUP BY e.id
        )
        SELECT (SELECT count(*) FROM totals) AS people,
               (SELECT count(*) FROM totals t
                 WHERE t.total > COALESCE((SELECT total FROM totals WHERE id = %s), 0)) AS ahead
        """,
        (session.tenant_id, period_start, employee_id, employee_id),
    ).fetchone()
    people = int((row or {}).get("people") or 0)
    if people == 0:
        return "Reytinq hələ formalaşmayıb"
    return f"{people} nəfər arasında {int((row or {}).get('ahead') or 0) + 1}-ci"


#: Baza cavab müddətinin "norma" həddi (millisaniyə) — kartın tonu bundan
#: asılıdır. Bu, İŞ QAYDASI DEYİL və `system_limits`-ə aid deyil: heç bir
#: əməliyyat bloklanmır, yalnız rəng seçilir. Dəyər maketdəki «Norma: < 50 ms»
#: mətnindən götürülüb ki, ekranın izahı ilə rəngi bir-birini təkzib etməsin.
DB_PING_WARNING_MS: Final = 50
DB_PING_DANGER_MS: Final = 250

#: NTP sürüşməsinin xəbərdarlıq həddi — `system_limits.NTP_MAX_DRIFT_SECONDS`
#: oxuna bilmədikdə işlənən FALLBACK (həqiqi mənbə Root-dadır, bölmə 3).
NTP_DRIFT_FALLBACK_SECONDS: Final = 60


#: Oxuna bilməyən sayğacın DƏYƏRİ — «0» YAZILMIR.
#:
#: Bu, bütün modulun ən bahalı ayrımıdır: `0` istifadəçi üçün «problem yoxdur»
#: deməkdir və yaşıl ton onu TƏSDİQLƏYİR, halbuki əsl vəziyyət «oxuya
#: bilmədim»dir. Tire heç bir şey iddia etmir və kartın izah sətri səbəbi
#: yazır.
UNREADABLE_VALUE: Final = "—"

#: Oxuna bilməyən kartın izah sətri və tonu.
#:
#: TON `warning`-dir, `danger` DEYİL: mənbənin oxunmaması hələ nasazlıq DEMƏK
#: DEYİL (məsələn miqrasiya tətbiq edilməyib), lakin göstəricini yaşıl
#: saxlamaq da yalan olardı. Hər iki ton `tokens.py`-da AA üçün kalibrlənib.
UNREADABLE_CAPTION: Final = "Oxuna bilmədi — səbəb jurnala yazıldı"
UNREADABLE_TONE: Final = "warning"


def _health_metrics(
    session: Session,
    context: Any,
    *,
    open_conflicts: int | None,
) -> tuple[list[tuple[str, str, str, str]], SectionFailure | None]:
    """Rəqəm kartları — `(ad, dəyər, izah, ton)`.

    Siyahı DİNAMİKDİR: ölçülə bilməyən göstərici sadəcə əlavə olunmur (bax
    `_health` docstring-i). Ona görə ekranda 2 kart da görünə bilər, 4 da.

    Args:
        open_conflicts: Konflikt sayğacı — `None` = OXUNA BİLMƏDİ. Parametr
            MƏCBURİDİR (defolt yoxdur) və bu, qəsdəndir: dəyər `_health`-dəki
            TƏK oxunuşdan gəlməlidir, əks halda kart ilə xəbərdarlıq mətni
            fərqli rəqəm göstərə bilər.

    Returns:
        `(kartlar, uğursuzluq)` — PERF-6 Qərar 2: `screen` artıq ALINMIR,
        offline bufer sayğacının uğursuzluğu SAF `SectionFailure` kimi
        qaytarılır (bax `_health` başlığı).
    """
    metrics: list[tuple[str, str, str, str]] = []
    metrics.append(_db_ping_metric(session))

    drift = context.ntp_drift_seconds()
    if drift is not None:
        key = SystemLimitKey.NTP_MAX_DRIFT_SECONDS
        try:
            limit = int(
                session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
            )
        except Exception:
            limit = NTP_DRIFT_FALLBACK_SECONDS
        metrics.append(
            (
                "NTP sapması",
                f"{drift:+.1f} san",
                f"Hədd: ±{limit} san",
                "success" if abs(drift) <= limit else "danger",
            )
        )

    pending, offline_failure = _offline_pending(session, context)
    metrics.append(_counter_card("Sinxronlaşmamış yazı", pending, caption="Offline bufer növbəsi"))
    metrics.append(_counter_card("Sync konflikti", open_conflicts, caption="Həll gözləyən sətir"))
    return metrics, offline_failure


def _counter_card(name: str, value: int | None, *, caption: str) -> tuple[str, str, str, str]:
    """Sayğac kartı — `None` GİZLƏDİLMİR, «—» ilə AÇIQ göstərilir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ KART ARTIQ ATLANMIR
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl oxuna bilməyən göstərici siyahıya ƏLAVƏ OLUNMURDU — «0 yazmaqdansa
    heç nə yazma» qaydası ilə. Nəticə isə eyni sükut idi: kart sadəcə YOX
    olurdu və istifadəçi bunun səbəbini ekranda görə bilmirdi (ekranda dörd
    əvəzinə üç kart olduğunu kim sayır?). İndi kart qalır, dəyəri isə heç nə
    iddia etməyən tiredir.

    «Ölçülə bilməyən göstərici göstərilmir» qaydası POZULMUR: o qayda MƏNBƏSİ
    OLMAYAN göstəriciyə aiddir (server diski, `_NullNtp`) — həmin kartlar
    ümumiyyətlə qurulmur. Bu isə mənbəsi OLAN, lakin bu dəfə oxunmayan
    göstəricidir; ikisi fərqli hallardır.
    """
    if value is None:
        return (name, UNREADABLE_VALUE, UNREADABLE_CAPTION, UNREADABLE_TONE)
    return (name, str(value), caption, "success" if value == 0 else "warning")


def _db_ping_metric(session: Session) -> tuple[str, str, str, str]:
    """Bazanın cavab müddəti — REAL ölçmə (`SELECT 1` gediş-gəlişi).

    Sabit dəyər və ya "OK" yazmaq mənasız olardı: bu kartın yeganə məqsədi
    bağlantının nə qədər ləng olduğunu göstərməkdir. Ölçmə sorğunun ÖZÜNÜ
    əhatə edir (şəbəkə + parse + cavab), yəni istifadəçinin hiss etdiyi
    gecikmə ilə eyni cinsdəndir.
    """
    import time  # noqa: PLC0415

    started = time.monotonic()
    session.uow.connection.execute("SELECT 1").fetchone()
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if elapsed_ms >= DB_PING_DANGER_MS:
        tone = "danger"
    elif elapsed_ms >= DB_PING_WARNING_MS:
        tone = "warning"
    else:
        tone = "success"
    return ("Baza (DB Ping)", f"{elapsed_ms} ms", f"Norma: < {DB_PING_WARNING_MS} ms", tone)


def _offline_pending(session: Session, context: Any) -> tuple[int | None, SectionFailure | None]:
    """Offline buferdəki gözləyən yazı sayı — bufer açıla bilmirsə `None`.

    `0` HEÇ VAXT qaytarılmır: o, "hər şey sinxrondur" demək olardı, halbuki
    əsl vəziyyət "oxuya bilmədim"dir (bax `_LazyBufferDrain`). `None` isə
    kartda «—» kimi göstərilir (bax `_counter_card`) və bölmə bannerdə
    işarələnir — əvvəl kart sadəcə YOX olurdu və istifadəçi fərqi görmürdü.

    PERF-6 Qərar 2: `screen` artıq ALINMIR — uğursuzluq `SectionFailure`
    kimi qaytarılır, banner çağırışını çağıran (`_health_metrics`, sonra
    `_health_apply`) edir.
    """
    try:
        return int(context.offline_drain().pending_count(session.tenant_id)), None
    except Exception:
        _error_log.warning("HEALTH_OFFLINE_BUFFER_UNREADABLE")
        return None, SectionFailure(section=SECTION_HEALTH_OFFLINE)


def _open_conflicts_or_none(session: Session) -> tuple[int | None, SectionFailure | None]:
    """Həll gözləyən sinxronizasiya konfliktləri — oxuna bilməsə `None`.

    Use case-in `open_count()` metodu `can_view_employee_reports` tələb edir;
    burada REPO birbaşa oxunur, çünki ekran onsuz da `can_view_system_health`
    flag-i ilə açılır (bax `menu.py`) və sağlamlıq sayğacı üçün İKİNCİ,
    əlaqəsiz bir flag tələb etmək istifadəçini izahsız boş kartla qoyardı.
    Sayğac heç bir konflikt MƏZMUNUNU açmır — yalnız ədəddir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `0` DEYİL, `None`
    ──────────────────────────────────────────────────────────────────────────
    Sorğu düşəndə funksiya `0` qaytarırdı və kart YAŞIL «0» göstərirdi: yəni
    nasazlıq ekranda «hər şey qaydasındadır» kimi görünürdü. Bu, bütün
    modulun ən bahalı sükutu idi — sinxronizasiya konflikti həll edilmədikcə
    iki yerdə fərqli dəyişdirilmiş qeyd yaşayır və heç kim ona baxmır.

    PERF-6 Qərar 2: `screen` artıq ALINMIR (bax `_offline_pending`-in EYNİ
    izahı).
    """
    try:
        return int(session.uow.repository("sync_conflicts").open_count(session.tenant_id)), None
    except Exception:
        _error_log.exception("HEALTH_CONFLICT_COUNT_FAILED")
        return None, SectionFailure(section=SECTION_HEALTH_CONFLICTS)


def _open_conflicts(session: Session) -> int:
    """`_open_conflicts_or_none`-un GERİYƏ-UYĞUN forması — oxunmasa `0`.

    `_health_alerts` sayğacı ötürülmədikdə özü oxuyur və orada `None` üçün yer
    yoxdur: xəbərdarlıq sətri ya var, ya yox. Sıfır burada "xəbərdarlıq
    əlavə etmə" deməkdir — vəziyyəti İDDİA etmir, çünki həqiqi göstərici
    kartdadır («—») və bölmə bannerdə işarələnib.

    UĞURSUZLUQ BURADA BANNERƏ ÇEVRİLMİR (dəyişməyib): bu yol yalnız `_health_
    alerts` MÜSTƏQİL (pre-supplied conflicts olmadan) çağırılanda işə düşür —
    cari `_health` axınında HEÇ VAXT baş vermir, çünki sayğac ORADA ARTIQ
    oxunub ötürülür (bax `_health_fetch`).
    """
    count, _failure = _open_conflicts_or_none(session)
    return count or 0


def _health_latencies(session: Session) -> list[tuple[str, str, str]]:
    """1C serverlərinin sinxron gecikməsi — `v_erp_server_health` görünüşü.

    `INACTIVE` sətirlər DƏ göstərilir (dashboard-dan fərqli olaraq): bu ekran
    diaqnostika üçündür və "server niyə məlumat göndərmir" sualının cavabı
    çox vaxt məhz "deaktiv edilib"dir.
    """
    rows = session.uow.connection.execute(
        """
        SELECT server_name, health, sync_delay_seconds
          FROM v_erp_server_health
         WHERE tenant_id = %s
         ORDER BY server_name
         LIMIT 20
        """,
        (session.tenant_id,),
    ).fetchall()
    return [
        (
            str(row["server_name"]),
            "deaktiv"
            if str(row["health"]) == "INACTIVE"
            else _sync_delay_text(row["sync_delay_seconds"]),
            _HEALTH_TONES.get(str(row["health"]), "warning"),
        )
        for row in rows
    ]


def _health_alerts(
    session: Session, actor: Any, *, open_conflicts: int | None = None
) -> tuple[list[tuple[str, str, str]], SectionFailure | None]:
    """Aktiv xəbərdarlıqlar — `(mətn, vaxt, ton)`.

    Üç REAL mənbə birləşdirilir: problemli 1C serverləri (diaqnoz mətni
    domendədir — `ServerHealthRow.diagnosis`), oxunmamış KRİTİK bildirişlər
    və açıq sinxronizasiya konfliktləri. Yeni xəbərdarlıq NÖVÜ icad edilmir.

    Args:
        open_conflicts: Sayğac ARTIQ oxunubsa ötürülür — belə halda ikinci
            `SELECT count(*)` edilmir və xəbərdarlıq mətni ilə kartın altındakı
            keçid EYNİ rəqəmi göstərir (bax `ScreenDataBinder._health`).
            `None` → funksiya özü oxuyur (mövcud çağırış yerləri üçün).

    Returns:
        `(xəbərdarlıqlar, uğursuzluq)` — PERF-6 Qərar 2: `screen` artıq
        ALINMIR, kritik bildirişlərin uğursuzluğu SAF `SectionFailure` kimi
        qaytarılır.
    """
    alerts: list[tuple[str, str, str]] = []
    now = datetime.now(UTC)

    rows = session.uow.connection.execute(
        """
        SELECT server_name, health, last_error_at, consecutive_failures, mapped_stores
          FROM v_erp_server_health
         WHERE tenant_id = %s AND health IN ('DEGRADED', 'STALE', 'NEVER_SYNCED')
         ORDER BY server_name
         LIMIT 10
        """,
        (session.tenant_id,),
    ).fetchall()
    for row in rows:
        alerts.append(
            (
                f"{row['server_name']}: {_erp_diagnosis(row)}",
                _hhmm(row["last_error_at"]),
                "danger" if str(row["health"]) == "NEVER_SYNCED" else "warning",
            )
        )

    notifications, notifications_failure = _critical_notifications(session, actor)
    for notification in notifications:
        alerts.append(
            (
                notification.title_az,
                _hhmm(notification.created_at),
                "danger" if notification.is_critical else "warning",
            )
        )

    conflicts = _open_conflicts(session) if open_conflicts is None else open_conflicts
    if conflicts:
        alerts.append(
            (
                f"{conflicts} sinxronizasiya konflikti həll gözləyir — "
                "eyni qeyd iki yerdə fərqli dəyişdirilib.",
                _hhmm(now),
                "warning",
            )
        )
    return alerts, notifications_failure


def _erp_diagnosis(row: Any) -> str:
    """Sətri domendəki diaqnoz mətninə çevirir.

    Mətn BURADA yazılmır — `ServerHealthRow.diagnosis` onu texniki-olmayan
    dildə verir (bölmə 7 tələbi) və eyni mətn «ERP Serverləri» ekranında da
    görünür. İki yerdə iki fərqli izah istifadəçini çaşdırardı.
    """
    from src.infrastructure.erp.health import ServerHealth, ServerHealthRow  # noqa: PLC0415

    return ServerHealthRow(
        server_id="",
        server_name=str(row["server_name"]),
        host="",
        health=ServerHealth(str(row["health"])),
        status="",
        consecutive_failures=int(row["consecutive_failures"] or 0),
        mapped_stores=int(row["mapped_stores"] or 0),
        sync_interval_seconds=300,
    ).diagnosis


def _critical_notifications(
    session: Session, actor: Any
) -> tuple[list[Any], SectionFailure | None]:
    """Oxunmamış KRİTİK bildirişlər — sistem hadisələrinin izi (bölmə 7).

    Auditoriya süzgəci zəng panelindəki ilə EYNİ funksiyadan gəlir: İdarə
    Panelindəki kritik siyahı zəng nişanından geniş olsaydı, istifadəçi
    paneldə tapa bilmədiyi bir sətri burada görərdi.

    PERF-6 Qərar 2: `screen` artıq ALINMIR — uğursuzluq `SectionFailure`
    kimi qaytarılır, banner çağırışını çağıran (`_health_alerts`, sonra
    `_health_apply`) edir.
    """
    from src.presentation.controllers.notifications import (  # noqa: PLC0415
        hidden_categories_for,
    )

    try:
        rows = session.notifications.list_for_recipient(
            actor.id, hidden_categories=hidden_categories_for(actor)
        )
    except Exception:
        # BOŞ SİYAHI «kritik bildiriş yoxdur» kimi oxunur — halbuki oxunmayan
        # mənbədə məhz KRİTİK sətirlər gözləyə bilər. Ekran «Aktiv xəbərdarlıq
        # yoxdur» yazacaq, banner isə bu iddianın natamam olduğunu deyəcək.
        _error_log.exception("HEALTH_NOTIFICATIONS_FAILED")
        return [], SectionFailure(section=SECTION_HEALTH_ALERTS)
    return [row for row in rows if row.is_critical and row.is_unread][:5], None


def _employee_name(session: Session, employee_id: Any) -> str:
    """İşçi adı — tapılmazsa ID-nin qısa forması.

    Boş sətir QAYTARILMIR: ekranda adsız sətir "məlumat itib" kimi görünərdi;
    qısa ID isə heç olmasa hansı qeyd olduğunu tapmağa imkan verir.
    """
    employee = session.uow.employees.get(employee_id)
    if employee is None:
        return f"#{str(employee_id)[:8]}"
    return str(employee.full_name)


def _hhmm(moment: datetime | None) -> str:
    return f"{moment:%H:%M}" if moment is not None else "—"


#: Ay adları — `datetime.strftime("%B")` sistem lokalından asılıdır və Windows
#: maşınında ingiliscə qaytarır; interfeys dili isə YALNIZ Azərbaycancadır.
_MONTHS_AZ: Final = (
    "Yanvar",
    "Fevral",
    "Mart",
    "Aprel",
    "May",
    "İyun",
    "İyul",
    "Avqust",
    "Sentyabr",
    "Oktyabr",
    "Noyabr",
    "Dekabr",
)

#: Cərimə statusu → ekran mətni. Açarlar `FineStatus` dəyərləridir; naməlum
#: status (köhnə sətir) öz kodu ilə göstərilir, gizlədilmir.
_FINE_STATUS_TEXT: Final[dict[str, str]] = {
    "PENDING_REVIEW": "Gözləyir",
    "PUBLISHED": "Təsdiqlənib",
    "REVERSED": "Ləğv edilib",
    "REDUCED": "Azaldılıb",
}


def _month_text() -> str:
    today = datetime.now(UTC).date()
    return f"{_MONTHS_AZ[today.month - 1]} {today.year}"


def _fine_type_name(session: Session, fine_id: Any) -> str:
    """Etiraz kartındakı cərimə növü — tapılmasa "—"."""
    row = session.uow.connection.execute(
        """SELECT COALESCE(ft.name_az, '—') AS name
             FROM fines f LEFT JOIN fine_types ft ON ft.id = f.fine_type_id
            WHERE f.id = %s AND f.tenant_id = %s""",
        (fine_id, session.tenant_id),
    ).fetchone()
    return str(row["name"]) if row else "—"


def _fine_amount(session: Session, fine_id: Any) -> str:
    row = session.uow.connection.execute(
        "SELECT amount FROM fines WHERE id = %s AND tenant_id = %s",
        (fine_id, session.tenant_id),
    ).fetchone()
    return f"{row['amount']} ₼" if row else "—"


def _full_name(row: Any) -> str:
    """`LEFT JOIN` NULL verə bilər — adsız sətir "—" kimi göstərilir."""
    name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
    return name or "—"


def _minutes_since(moment: datetime | None) -> int:
    if moment is None:
        return 0
    return max(0, int((datetime.now(UTC) - moment).total_seconds() // 60))


def _low_confidence_faces(session: Session, stores: list[Any]) -> tuple[set[tuple[str, str]], bool]:
    """AŞAĞI-ETİBARLI üz təsdiqi olan (işçi, addım) cütləri (facecontrol.md bənd 12).

    ──────────────────────────────────────────────────────────────────────────
    PERF-6 FAZA C — QƏRAR 2: BANNER ÇAĞIRIŞI ARTIQ BURADA DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl bu funksiya `screen` alır və uğursuzluqda BİRBAŞA `report_section_
    error(...)` çağırırdı — Qt çağırışı `fetch`-in (`_live_queue_fetch`)
    daxilində olurdu. İndi uğursuzluq İKİNCİ qaytarılan dəyər kimi (`bool`)
    ötürülür, banner çağırışını isə `_live_queue_apply` edir. Zəmanət
    DƏYİŞMİR: uğursuzluqda dəst BOŞ qalır, banner YENƏ görünür — sadəcə
    MƏSULİYYƏT yeri dəyişib.

    Returns:
        `(aşağı-etibarlı cüt dəsti, uğursuz oldumu)`.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ USE CASE DEYİL, BİRBAŞA SQL
    ──────────────────────────────────────────────────────────────────────────
    `_users`/`_fines` ilə eyni əsaslandırma: burada heç bir iş qərarı
    verilmir — nə status keçidi, nə hesablama, nə səlahiyyət yoxlaması var.
    Yalnız bir NİŞAN göstərilir. `FaceVerificationUseCase`-ə «operator növbəsi
    üçün siyahı» metodu əlavə etmək onu hesabat vasitəsinə çevirərdi.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SON SƏTİR (`DISTINCT ON`) VƏ NİYƏ 24 SAAT
    ──────────────────────────────────────────────────────────────────────────
    Bir işçi eyni gün bir neçə dəfə doğrulana bilər (məsələn əvvəlcə üz
    görünmədi, sonra keçdi). Operatorun sualı isə «BU sətri yaradan təsdiq
    zəif idimi?» — yəni SONUNCU nəticə. Bütün gün üzrə `bool_or` işlətsəydik,
    səhər bir dəfə zəif tanınan işçi axşama qədər nişanlı qalardı və nişan
    öz mənasını itirərdi.

    24 saatlıq pəncərə növbənin ÖZ ömründən (45 dəqiqəlik timeout) qat-qat
    genişdir və gecə növbəsinin gün sərhədini keçməsini də əhatə edir. Bu,
    siyasət deyil — SORĞU həddidir, ona görə ROOT parametri deyil.

    ──────────────────────────────────────────────────────────────────────────
    NASAZLIQ NÖVBƏNİ DAYANDIRMIR
    ──────────────────────────────────────────────────────────────────────────
    Boş dəst qayıdırsa nişan görünmür, növbə isə OLDUĞU KİMİ işləyir. Face
    Control quraşdırılmamış (miqrasiya tətbiq edilməmiş) bir bazada bu sorğu
    uğursuz olar və operatorun BÜTÜN növbəsini boş qoymaq — bir nişanın
    ucbatından — yolverilməz olardı.
    """
    if not stores:
        return set(), False
    try:
        rows = session.uow.connection.execute(
            """
            SELECT DISTINCT ON (employee_id, trigger_context)
                   employee_id, trigger_context, is_low_confidence
              FROM face_verification_log
             WHERE tenant_id = %s
               AND store_id = ANY(%s)
               AND occurred_at >= %s
             ORDER BY employee_id, trigger_context, occurred_at DESC
            """,
            (
                session.tenant_id,
                list(stores),
                datetime.now(UTC) - timedelta(days=LOW_CONFIDENCE_LOOKBACK_DAYS),
            ),
        ).fetchall()
    except Exception:
        # NİŞANSIZ NÖVBƏ «hamısı etibarlıdır» kimi oxunur — operator zəif
        # tanınmış təsdiqi fərqləndirə bilmir. Növbənin ÖZÜ işləməyə davam
        # edir (fail-soft), lakin nişanların əskik olduğu AÇIQ deyilir.
        _error_log.exception("FACE_LOW_CONFIDENCE_LOOKUP_FAILED")
        return set(), True
    return {
        (str(row["employee_id"]), str(row["trigger_context"]))
        for row in rows
        if row["is_low_confidence"]
    }, False


def _store_name(session: Session, store_id: Any) -> str:
    """Mağaza adı — çox-mağazalı operator üçün sətir nişanı (bölmə 4)."""
    row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE id = %s", (store_id,)
    ).fetchone()
    return str(row["name"]) if row else "—"


def _default_store(session: Session, actor: Employee) -> tuple[Any, str]:
    """Mağaza-əhatəli göstəricilər üçün "hansı mağaza?" cavabı (#13).

    Aktorun öz filialı ÜSTÜNDÜR. Root/CEO-nun filialı yoxdur (şəbəkə
    səviyyəsindədir) — onlar üçün əlifba üzrə ilk AKTİV mağaza seçilir.
    Boş nəticə "—" adı ilə qaytarılır ki, çağıran tərəf ekranı yenə də
    doldursun: səssiz `return` istifadəçidə "kart sınıb" təəssüratı yaradardı.
    """
    if actor.store_id is not None:
        return actor.store_id, _store_name(session, actor.store_id)

    row = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name LIMIT 1",
        (session.tenant_id,),
    ).fetchone()
    if row is None:
        return None, "—"
    return row["id"], str(row["name"])


def _position_name(session: Session, employee_id: Any) -> str:
    employee = session.uow.employees.get(employee_id)
    return str(employee.position.name_az) if employee is not None else "—"


def _permitted_user_actions(actor: Employee) -> frozenset[str]:
    """`UsersScreen.ACTIONS`-dan aktorun GÖRƏ biləcəyi açarlar (QA-FULL Faza 3).

    "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" — hər açar öz use case-inin `_require(...)`
    çağırdığı flag-lə birbaşa uzlaşır (`user_lifecycle.py`, `pos_threshold.py`,
    `employee_documents.py` başlıqları). `change_role` İKİ flag tələb edir,
    çünki `UserManagementUseCase.update_employee` rol dəyişikliyində HƏR
    İKİSİNİ yoxlayır (`MANAGE_EMPLOYEES_FLAG` + rol dəyişəndə əlavə olaraq
    `MANAGE_ROLES_FLAG`) — bəndi göstərib, klikdən sonra rədd etmək "GÖRMƏK
    = SƏLAHİYYƏT" prinsipini yarı-tətbiq edərdi.
    """
    from src.application.use_cases.employee_documents import (  # noqa: PLC0415
        MANAGE_EMPLOYEE_DOCUMENTS_FLAG,
    )
    from src.application.use_cases.pos_threshold import (  # noqa: PLC0415
        MANAGE_POS_THRESHOLDS_FLAG,
    )
    from src.application.use_cases.user_management import (  # noqa: PLC0415
        MANAGE_EMPLOYEES_FLAG,
        MANAGE_ROLES_FLAG,
        RESET_PASSWORD_FLAG,
        RESET_PIN_FLAG,
    )

    now = datetime.now(UTC)
    can_manage_employees = actor.has_permission(MANAGE_EMPLOYEES_FLAG, now=now)
    permitted: set[str] = set()
    if actor.has_permission(RESET_PIN_FLAG, now=now):
        permitted.add("reset_pin")
    if actor.has_permission(RESET_PASSWORD_FLAG, now=now):
        permitted.add("reset_password")
    if can_manage_employees and actor.has_permission(MANAGE_ROLES_FLAG, now=now):
        permitted.add("change_role")
    if actor.has_permission(MANAGE_POS_THRESHOLDS_FLAG, now=now):
        permitted.add("pos_threshold")
    if actor.has_permission(MANAGE_EMPLOYEE_DOCUMENTS_FLAG, now=now):
        permitted.add("employee_documents")
    if can_manage_employees:
        permitted.add("deactivate")
    return frozenset(permitted)


__all__ = [
    "FALLBACK_MATRIX_WINDOW_DAYS",
    "HELP_TOPIC_MODULES",
    "LATE_QUEUE_MINUTES",
    "ScreenDataBinder",
    "late_threshold_minutes",
    "matrix_window_days",
    "points_balance_summary",
]
