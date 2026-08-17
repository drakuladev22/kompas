"""Maketdəki nümunə məzmun — YALNIZ önizləmə üçün — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
BU MODUL İSTEHSALAT AXININDA İŞLƏMİR
──────────────────────────────────────────────────────────────────────────────
Faza 4 təqdimat qatıdır: ekranlar qurulur, lakin onları dolduran repository
sorğuları Faza 5-də qoşulur. O vaxta qədər ekranların həqiqətən maketdəki
kimi göründüyünü YOXLAMAQ üçün bir məzmun mənbəyi lazımdır.

Buradakı dəyərlər birbaşa maketlərdən (Qrup A–G) götürülüb — uydurulmuş
"Lorem ipsum" deyil, dizaynda razılaşdırılmış faktiki mətnlərdir. Beləliklə
`--gui --preview` ilə açılan pəncərə maketlə sətir-sətir müqayisə edilə bilir.

Modul YALNIZ `--preview` bayrağı ilə idxal olunur (bax `app.py`); istehsalat
işə düşməsində ona toxunulmur. Faza 5-də hər `set_*` çağırışı use-case
nəticəsi ilə əvəz olunur və bu fayl silinir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Final, NamedTuple

from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, BreakAllowance, BreakKind, SystemLimitKey
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionFlag,
    RolePriority,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginStatus,
)
from src.presentation.plugin_surface import ApprovedPlugin

#: Maketdəki tarix — ekranlardakı "12 Avqust 2026" ilə uyğun olsun deyə sabitdir.
PREVIEW_NOW: Final = datetime(2026, 8, 12, 9, 42, tzinfo=UTC)

#: Sol paneldə görünən bütün maddələr üçün lazım olan flag-lər.
#: (`menu.py`-dakı `required_flag` dəyərləri ilə eyni olmalıdır.)
_ADMIN_FLAGS: Final = (
    "can_verify_returns",
    "can_fill_daily_attendance",
    "can_manage_shifts",
    "can_approve_shift_swap",
    "can_approve_leave_appeal",
    "can_assign_tasks",
    "can_manage_sales_points",
    "can_manage_employees",
    "can_manage_permissions",
    # Sxemdəki `ADMIN` rolu bu üçünə də sahibdir (bax `schema.sql` —
    # "Admin: operativ idarəetmə + həvalə edilmiş icazə kontrolu"), lakin
    # önizləmə siyahısına düşməmişdi: nəticədə İcazə Matrisi, İdarə Paneli
    # Qurucusu və Hesabatlar ekranları önizləmədə ÜMUMİYYƏTLƏ render
    # olunmurdu — halbuki real Admin onları görür.
    "can_control_user_permissions",
    "can_view_dashboard_builder",
    "can_export_reports",
    "can_manage_erp_servers",
    "can_manage_backups",
    "can_view_system_health",
    "can_view_audit_logs",
    "can_manage_system_limits",
    # Root-səviyyəli bölmələr. Bunlar real `ADMIN` rolunda YOXDUR (bölmə 3
    # hardlock qaydası) — burada yalnız ONA GÖRƏ verilir ki, önizləmə
    # pəncərəsi bütün ekranları göstərə bilsin və hər biri maketlə
    # tutuşdurula bilsin. Fikstür istehsalat axınında işləmir (modul başlığı).
    "can_manage_work_modes",
    "can_manage_fine_types",
    "can_manage_leave_types",
    "can_switch_db",
    "can_manage_plugins",
    # #9-un GUI tərəfi (kompasos11.md Faza 5) — "İstisnalar" ekranı
    # önizləmədə görünsün deyə. Real `ADMIN` rolunda bu flag DATADAN gəlir
    # (migrations/021, kateqoriya "HR"), burada isə yalnız ekranın maketlə
    # tutuşdurulması üçün verilir (bax funksiya docstring-i).
    "can_view_exceptions",
    # #26+#27-nin GUI tərəfi (kompas1.md Faza 3). `can_report_incident` real
    # sistemdə BÜTÜN rollardadır (migrations/038, "Tələ 3"),
    # `can_conduct_store_audit` isə YALNIZ Root/CEO/Admin/HR_Admin-də —
    # önizləmə Admin-i hər ikisini daşıyır ki, hər iki forma maketlə
    # tutuşdurula bilsin.
    "can_conduct_store_audit",
    "can_report_incident",
    # Aylıq Cərimə İcmalı (miqrasiya 003). `can_issue_fines`-dən FƏRQLİ
    # olaraq bu flag REAL `ADMIN` rolunda DA var (003: ROOT/CEO/ADMIN/
    # HR_ADMIN) — yəni önizləmə burada həqiqəti güzgüləyir, güzəşt etmir.
    # Onun kamera roluna verilə bilməməsi (`excludes_camera_role`) isə
    # `build_camera_operator` tərəfində qorunur: orada flag YOXDUR.
    "can_publish_fines",
)


def build_admin() -> Employee:
    """Bütün bölmələri görən nümunə Admin.

    `can_issue_fines` QƏSDƏN verilmir: o, anti-fraud flag-idir və yalnız
    kamera-tipli rollara verilə bilər (SEC-001). Admin-ə zorla vermək domen
    qaydasını pozardı — nəticədə "Cərimələr" maddəsi bu istifadəçidə
    görünmür və bu, DÜZGÜN davranışdır.
    """
    tenant_id = TenantId(uuid.uuid4())
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="ADMIN",
        name_az="Admin",
        priority=RolePriority.ADMIN,
        tenant_id=tenant_id,
        is_system=True,
    )
    for code in _ADMIN_FLAGS:
        position.grant(PermissionFlag(code=code, category="preview"))

    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name="Rəşad",
        last_name="Məmmədov",
        store_id=StoreId(uuid.uuid4()),
        username=Username("r.mammadov"),
        has_password=True,
        hire_date=date(2024, 3, 1),
    )


def build_camera_operator() -> Employee:
    """Kamera Nəzarətçisi — yalnız növbə və cərimə bölmələrini görür.

    "Görmək = Səlahiyyətin Olması" prinsipini önizləmədə göstərmək üçün
    faydalıdır: eyni pəncərə bu istifadəçi ilə açılanda sol panel qısalır.
    """
    tenant_id = TenantId(uuid.uuid4())
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="KAMERA_NEZARETCISI",
        name_az="Kamera Nəzarətçisi",
        priority=RolePriority.OPERATIONAL,
        tenant_id=tenant_id,
        is_system=True,
        is_camera_type=True,
    )
    position.grant(
        PermissionFlag(
            code="can_verify_returns",
            category="preview",
            hardlock=HardlockLevel.NONE,
            is_anti_fraud=True,
            is_camera_only=True,
        )
    )
    position.grant(
        PermissionFlag(
            code="can_issue_fines",
            category="preview",
            is_anti_fraud=True,
            is_camera_only=True,
        )
    )

    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name="Elvin",
        last_name="Həsənov",
        username=Username("e.hasanov"),
        has_password=True,
    )
    for _ in range(2):
        employee.assign_store(StoreId(uuid.uuid4()))
    return employee


# --------------------------------------------------------------------------- #
# Ekran məzmunu (maketdən)
# --------------------------------------------------------------------------- #


class DashboardSummary(NamedTuple):
    """İdarə Paneli rəqəm kartlarının dəyərləri."""

    in_store: int
    planned: int
    pending: int
    longest_wait: str
    fines_total: str
    fines_delta: str
    open_tasks: int
    overdue_tasks: int
    #: Şəbəkənin ölçüsü — CANLI yolda `employees`/`stores` sayğacıdır.
    employees: int
    stores: int


DASHBOARD: Final = DashboardSummary(
    in_store=148,
    planned=156,
    pending=6,
    longest_wait="4 dəq",
    fines_total="3 415 ₼",
    fines_delta="keçən aya nisbətən +12%",
    open_tasks=37,
    overdue_tasks=9,
    employees=235,
    stores=21,
)

FINES_BY_BRANCH: Final = [
    ("28 May", 720.0, "720 ₼"),
    ("Xətai", 540.0, "540 ₼"),
    ("Gənclik", 880.0, "880 ₼"),
    ("Nərimanov", 400.0, "400 ₼"),
    ("Sumqayıt", 620.0, "620 ₼"),
    ("Gəncə", 255.0, "255 ₼"),
]

LEADERS: Final = [("A. Quliyeva", "1 240"), ("K. Vəliyev", "1 105"), ("N. Səfərova", "980")]

SERVER_HEALTH: Final = [
    ("1C — Bakı", "42 ms", "success"),
    ("1C — Gəncə", "318 ms", "warning"),
    ("Baza", "11 ms", "success"),
]

#: Nahar/Çay gündəlik həddini aşanlar (nahar.md GUI, bənd 2).
#:
#: MƏTN `BreakAllowance.warning_az()`-DAN QURULUR, əl ilə yazılmır — canlı
#: yolda HR məhz bu ifadəni görür və maket ondan fərqlənsəydi, dizayn
#: baxışında qüsur görünməz qalardı (bax modul başlığındakı ad-məkanı qaydası).
BREAK_OVERUSE: Final = [
    (
        "K. Vəliyev",
        BreakAllowance(
            kind=BreakKind.TEA, duration_minutes=15, daily_count=2, used_count=3
        ).warning_az(),
    ),
    (
        "N. Səfərova",
        BreakAllowance(
            kind=BreakKind.LUNCH, duration_minutes=60, daily_count=1, used_count=2
        ).warning_az(),
    ),
]

# --------------------------------------------------------------------------- #
# #24 Çox-Mağaza Benchmark Dashboard (kompasos11.md Faza 9A)
# --------------------------------------------------------------------------- #
# Açarlar `screen_data.py::_populate_benchmark_sections`-in FAKTİKİ ötürdüyü
# formadadır (CLAUDE.md bölmə 6 — maket və canlı yol EYNİ açarlı olmalıdır).
# Mağaza ID-ləri UUID DEYİL — önizləmə rejimində drill-down siqnalı heç
# qoşulmur (`app.py::_attach_dashboard_benchmark` `self._preview`-də erkən
# çıxır), ona görə oxunaqlı sabit sətir kifayətdir.
BENCHMARK_METRIC_OPTIONS: Final = [
    ("FINE_COUNT", "Cərimə sayı"),
    ("ATTENDANCE_RATE", "Davamiyyət faizi"),
    ("POINTS_BALANCE", "Xal balansı"),
    ("OVERTIME_HOURS", "Overtime saatı"),
    ("TURNOVER_RISK", "Turnover riski"),
]

#: (mağaza-id, mağaza-adı, dəyər-mətni, trend-oxu, trend-mətni) — ARTIQ sıralanmış.
BENCHMARK_RANKING: Final = [
    ("store-28-may", "28 May", "2", "↓", "azalıb"),
    ("store-sumqayit", "Sumqayıt", "4", "→", "dəyişməyib"),
    ("store-gence", "Gəncə", "7", "↑", "artıb"),
]


class BenchmarkStoreVsNetwork(NamedTuple):
    """`set_store_vs_network` sahələri — açıq NamedTuple, `**dict` DEYİL

    (bax `preview_screens.py::_dashboard` şərhi: açıq yazılış səhv-adlı
    açarı tip yoxlayıcısında tutur)."""

    metric_label: str
    store_label: str
    store_value: float
    store_display: str
    network_label: str
    network_value: float
    network_display: str


BENCHMARK_STORE_VS_NETWORK: Final = BenchmarkStoreVsNetwork(
    metric_label="Cərimə sayı",
    store_label="28 May",
    store_value=2.0,
    store_display="2",
    network_label="Şəbəkə ortalaması",
    network_value=4.3,
    network_display="4.3",
)

#: (dövr etiketi, dəyər, göstəriləcək mətn) — 6 aylıq nümunə (ROOT parametri
#: `BENCHMARK_TREND_MONTHS`-un DEFOLTU, hardcode DEYİL).
BENCHMARK_TREND: Final = [
    ("2026-03", 6.0, "6"),
    ("2026-04", 5.0, "5"),
    ("2026-05", 4.0, "4"),
    ("2026-06", 5.0, "5"),
    ("2026-07", 3.0, "3"),
    ("2026-08", 2.0, "2"),
]


class BenchmarkOutliers(NamedTuple):
    summary_text: str
    rows: list[tuple[str, str]]


BENCHMARK_OUTLIERS: Final = BenchmarkOutliers(
    summary_text="Diqqət: 1 filial cərimə sayı göstəricisində ortalamadan 2.0×σ kənardır.",
    rows=[("Gəncə", "2.4σ yuxarı")],
)


class QueuePreview(NamedTuple):
    """Canlı növbə sətri (maket 06)."""

    request_id: str
    employee_name: str
    store_name: str
    position_name: str
    kind: str
    timestamp_text: str
    waiting_text: str
    is_late: bool = False
    #: Üz təsdiqi AŞAĞI-ETİBAR zolağında keçdi (facecontrol.md bənd 12).
    #: Sətir bloklanmır — operator sadəcə iVMS yoxlamasında daha diqqətli
    #: olmalıdır. Defolt `False`: mövcud maket sətirləri dəyişmir.
    is_low_confidence: bool = False


QUEUE: Final = [
    QueuePreview(
        request_id="q1",
        employee_name="Aysel Quliyeva",
        store_name="Bellona 28 May",
        position_name="Satış",
        kind="Giriş Təsdiqi",
        timestamp_text="09:42",
        waiting_text="1 dəq gözləyir",
    ),
    QueuePreview(
        request_id="q2",
        employee_name="Murad Əliyev",
        store_name="Yataş Xətai",
        position_name="Anbar",
        kind="Qayıdış Təsdiqi",
        timestamp_text="11:58",
        waiting_text="3 dəq gözləyir",
        # Bənd 12 — maketdə ƏN AZI BİR aşağı-etibarlı sətir olmalıdır, əks
        # halda nişanın necə göründüyü heç vaxt gözlə yoxlanmazdı.
        is_low_confidence=True,
    ),
    QueuePreview(
        request_id="q3",
        employee_name="Nigar Səfərova",
        store_name="Bellona 28 May",
        position_name="Kassa",
        kind="Giriş Təsdiqi",
        timestamp_text="09:51",
        waiting_text="Plandan 21 dəq gec",
        is_late=True,
    ),
    QueuePreview(
        request_id="q4",
        employee_name="Rəvan İsmayılov",
        store_name="Yataş Xətai",
        position_name="Satış",
        kind="Giriş Təsdiqi",
        timestamp_text="09:55",
        waiting_text="indi əlavə olundu",
    ),
]

USERS: Final = [
    {
        "full_name": "Elvin Həsənov",
        "username": "e.hasanov",
        "role": "Kamera Nəzarətçisi",
        "store": "2 mağaza təyin edilib",
        "status": "Aktiv",
    },
    {
        "full_name": "Aysel Quliyeva",
        "username": "a.quliyeva",
        "role": "Satış Məsləhətçisi",
        "store": "Bellona 28 May",
        "status": "Aktiv",
    },
    {
        "full_name": "Nigar Səfərova",
        "username": "n.saferova",
        "role": "Kassir",
        "store": "Bellona 28 May",
        "status": "Aktiv",
    },
    {
        "full_name": "Murad Əliyev",
        "username": "m.aliyev",
        "role": "Anbardar",
        "store": "Yataş Xətai",
        "status": "Məzuniyyətdə",
    },
    {
        "full_name": "Kamran Vəliyev",
        "username": "k.valiyev",
        "role": "Mağaza Rəhbəri",
        "store": "İstikbal Gənclik",
        "status": "Aktiv",
    },
    {
        "full_name": "Günel Rəhimova",
        "username": "g.rahimova",
        "role": "HR_Admin",
        "store": "Baş ofis",
        "status": "Bloklanıb",
    },
]

ROLES: Final = [
    ("hr_admin", "HR_Admin", 6),
    ("store_manager", "Mağaza Rəhbəri", 21),
    ("camera", "Kamera Nəzarətçisi", 8),
    ("seller", "Satış Məsləhətçisi", 164),
    ("warehouse", "Anbardar", 32),
    ("accountant", "Mühasib", 4),
]

#: Matris sətri: (flag, etiket, aktiv, hardlock, AKTORDA VAR).
#:
#: BEŞİNCİ SAHƏ MAKETDƏ DƏ REALDIR — CLAUDE.md §6: "maket və canlı yol EYNİ
#: açarları işlətməlidir". Sahə canlı yolda `PermissionMatrixController`
#: tərəfindən aktorun effektiv flag dəstindən doldurulur; burada isə maketin
#: fərz etdiyi aktor (`HR_Admin`) üçün əl ilə yazılıb. `False` olan iki sətir
#: qəsdəndir: onlarsız maket "aktorda olmayan icazə" vəziyyətini HEÇ VAXT
#: göstərməzdi və həmin görüntü qüsuru yalnız istehsalatda üzə çıxardı.
PERMISSION_GROUPS: Final = [
    (
        "Davamiyyət və İcazə",
        [
            ("can_view_leave", "İcazə sorğusuna baxmaq", True, False, True),
            ("can_approve_leave", "İcazə təsdiqləmək", True, False, True),
            ("can_delete_attendance", "Giriş/çıxış qeydini silmək", False, True, True),
            ("can_fill_daily_attendance", "Tabeli təsdiqləmək", True, False, True),
            # Anti-fraud flag-i: maketdəki HR_Admin aktorunda YOXDUR.
            ("can_override_return_time", "Vaxtı manual dəyişmək", False, False, False),
            ("can_approve_dual_control_override", "Cüt nəzarət təsdiqi", False, True, True),
        ],
    ),
    (
        "Cərimə və Etiraz",
        [
            # Kamera-xüsusi flag: HR_Admin onu daşımır, deməli paylaya da bilməz.
            ("can_issue_fines", "Cərimə yaratmaq", False, False, False),
            ("can_view_appeals", "Etirazlara baxmaq", True, False, True),
            ("can_approve_leave_appeal", "Etirazı qəbul/rədd etmək", True, False, True),
            ("can_manage_fine_types", "Cərimə tariflərini dəyişmək", False, False, True),
            ("can_delete_fines", "Cəriməni silmək", False, True, True),
            ("can_export_reports", "Cərimə hesabatı ixracı", True, False, True),
        ],
    ),
    (
        "Sistem",
        [
            ("can_manage_erp_servers", "ERP server idarəetməsi", False, True, True),
            ("can_manage_backups", "Ehtiyat nüsxə / Bərpa", False, True, True),
            ("can_view_audit_logs", "Audit jurnalına baxmaq", True, False, True),
        ],
    ),
]

FINES: Final = [
    {
        "employee": "Nigar Səfərova",
        "type": "Gecikmə",
        "date": "12.08",
        "amount": "25 ₼",
        "status": "Etiraz edilib",
    },
    {
        "employee": "Murad Əliyev",
        "type": "Forma qaydası",
        "date": "09.08",
        "amount": "15 ₼",
        "status": "Təsdiqlənib",
    },
    {
        "employee": "Aysel Quliyeva",
        "type": "İcazəsiz çıxış",
        "date": "07.08",
        "amount": "40 ₼",
        "status": "Təsdiqlənib",
    },
    {
        "employee": "Rəvan İsmayılov",
        "type": "Gecikmə",
        "date": "05.08",
        "amount": "25 ₼",
        "status": "Ləğv edilib",
    },
    {
        "employee": "Kamran Vəliyev",
        "type": "Kassa uyğunsuzluğu",
        "date": "03.08",
        "amount": "50 ₼",
        "status": "Təsdiqlənib",
    },
]

# --------------------------------------------------------------------------- #
# Aylıq Cərimə İcmalı (miqrasiya 003) — nəşr gözləyən cərimələr
# --------------------------------------------------------------------------- #
#
# NİYƏ `FINES`-DƏN AYRI: yuxarıdakı siyahı kamera operatorunun ÖZ qeydləridir
# və statusu göstərir; bu isə `can_publish_fines` sahibinin qərar verdiyi
# dəstdir — orada YALNIZ `PENDING_REVIEW` sətirlər olur, yəni "status" sütunu
# mənasızdır. İki maketi birləşdirmək iki ayrı ekranı bir-birinə bənzədərdi.
#
# TİPLƏR EKRANIN `NamedTuple`-larına ÇEVRİLİR (`preview_screens._fine_review`)
# — burada sadə dəyərlər saxlanılır ki, bu modul PySide6 idxal etməsin
# (`BENCHMARK_RANKING` ilə eyni qərar).

#: Dövr seçicisinin maket dəyərləri — canlı yolda `pending_review_periods`
#: eyni `key`/`label` cütlərini verir (`controllers/fine_review.py::
#: _period_options`).
FINE_REVIEW_PERIODS: Final = [
    {"key": "2026-07", "label": "İyul 2026"},
    {"key": "2026-08", "label": "Avqust 2026"},
]

#: Defolt seçim MAKETDƏ də ƏN KÖHNƏ dövrdür (canlı yolda `_choose_period`).
FINE_REVIEW_SELECTED_PERIOD: Final = "2026-07"

#: `(fine_id, işçi, növ, məbləğ, tarix, qeydə alan, sübut şəkli varmı)`.
#: Sıra `FineReviewRow` sahələri ilə eynidir.
#: `(açar, filial, say mətni, cəm mətni, sətirlər)` — `FineReviewGroup` sırası.
FINE_REVIEW_GROUPS: Final = (
    (
        "st-28may",
        "Bellona 28 May",
        "3 cərimə",
        "90 ₼",
        (
            (
                "fr-1",
                "Nigar Səfərova",
                "Formaya uyğun geyinməmək",
                "25 ₼",
                "03.07.2026",
                "Elvin Həsənov",
                True,
            ),
            (
                "fr-2",
                "Murad Əliyev",
                "İcazəsiz çıxış",
                "40 ₼",
                "09.07.2026",
                "Elvin Həsənov",
                True,
            ),
            # AVTOMATİK cərimənin operatoru YOXDUR və sübut şəkli də olmur —
            # maket hər iki halı göstərir ki, nişanların fərqi görünsün.
            (
                "fr-3",
                "Rəvan İsmayılov",
                "Gecikmə (avtomatik)",
                "25 ₼",
                "14.07.2026",
                "Sistem (avtomatik)",
                False,
            ),
        ),
    ),
    (
        "st-xetai",
        "İstikbal Xətai",
        "2 cərimə",
        "65 ₼",
        (
            (
                "fr-4",
                "Aysel Quliyeva",
                "Kassa qaydalarına əməl etməmək",
                "50 ₼",
                "07.07.2026",
                "Günel Rəhimova",
                True,
            ),
            (
                "fr-5",
                "Kamran Vəliyev",
                "Gecikmə (avtomatik)",
                "15 ₼",
                "21.07.2026",
                "Sistem (avtomatik)",
                False,
            ),
        ),
    ),
)

#: Xülasə sətri — canlı yolda `_build_groups` eyni formatı qurur.
FINE_REVIEW_SUMMARY: Final = "5 cərimə · 2 filial · 155 ₼ nəşr gözləyir"

#: Maketdə BİR sətir "Sil" qərarı ilə göstərilir: qərar nişanının iki tonu
#: (neytral/təhlükə) və "geri qaytar" düyməsi dizayn baxışında görünsün deyə.
FINE_REVIEW_DISCARDED: Final = ("fr-3", "Kamera nasazlığı — sətir səhv yazılıb")

ROSTER_ROWS: Final = [
    {
        "employee": "Aysel Quliyeva",
        "plan": "09:00",
        "check_in": "08:54",
        "status": "Təsdiqli — Mağazada",
        "note": "—",
    },
    {
        "employee": "Nigar Səfərova",
        "plan": "09:00",
        "check_in": "09:51",
        "status": "51 dəq gecikib",
        "note": "Yol qəzası — sənəd gözlənilir",
    },
    {
        "employee": "Rəvan İsmayılov",
        "plan": "13:00",
        "check_in": "12:55",
        "status": "İcazədə — 11:15-dən",
        "note": "Bank işi, 1 saat",
    },
    {
        "employee": "Kamran Vəliyev",
        "plan": "09:00",
        "check_in": "08:47",
        "status": "Təsdiqli — Mağazada",
        "note": "—",
    },
    {
        "employee": "Leyla Hüseynova",
        "plan": "Planda yox",
        "check_in": "09:12",
        "status": "Plandan kənar giriş",
        "note": "Növbə dəyişməsi?",
    },
    {
        "employee": "Murad Əliyev",
        "plan": "09:00",
        "check_in": "—",
        "status": "Gəlməyib",
        "note": "Məzuniyyət sənədi yoxdur",
    },
]

SWAP_REQUESTS: Final = [
    {
        "id": "s1",
        "from_name": "Aysel Quliyeva",
        "to_name": "Leyla Hüseynova",
        "shift": "14 Avq · Səhər 09:00–18:00",
        "store": "Bellona 28 May",
        "note": "2 saat əvvəl göndərilib",
        "status": "Gözləyir",
    },
    {
        "id": "s2",
        "from_name": "Rəvan İsmayılov",
        "to_name": "Kamran Vəliyev",
        "shift": "16 Avq · Axşam 13:00–22:00",
        "store": "Yataş Xətai",
        "note": "Dünən göndərilib",
        "status": "Gözləyir",
    },
    {
        "id": "s3",
        "from_name": "Nigar Səfərova",
        "to_name": "Aysel Quliyeva",
        "shift": "18 Avq · Səhər 09:00–18:00",
        "store": "Bellona 28 May",
        "note": "Qəbul edilsə həmin gün 2 nəfər eyni növbədə olacaq",
        "status": "Gözləyir",
    },
]

#: `type` və `latency_meaning` açarları CANLI yolla (bax
#: `controllers/erp_servers.py::_server_view`) EYNİ olmalıdır — mətnlər
#: domendəki `ConnectorType.label_az` / `.latency_meaning_az` dəyərləridir.
#: Maket öz ad məkanını qursaydı (məs. `"HTTP"` ↔ `"HTTP/OData"`), nişanın
#: tonu maketdə düzgün, istehsalatda isə neytral görünərdi — layihədə məhz
#: bu qüsur olub (bax `shell/menu.py` başlığı).
ERP_SERVERS: Final = [
    {
        "name": "1C-BAKI-01",
        "type": "HTTP/OData",
        "address": "10.20.1.14:1541",
        "stores": "9 mağaza",
        "latency": "42 ms",
        "latency_meaning": "Şəbəkə cavab müddəti",
        "status": "Aktiv",
    },
    {
        "name": "1C-BAKI-02",
        "type": "HTTP/OData",
        "address": "10.20.1.15:1541",
        "stores": "6 mağaza",
        "latency": "57 ms",
        "latency_meaning": "Şəbəkə cavab müddəti",
        "status": "Aktiv",
    },
    {
        "name": "1C-GENCE-01",
        "type": "COM",
        "address": "1C-GENCE-SRV",
        "stores": "4 mağaza",
        "latency": "318 ms",
        "latency_meaning": "COM obyektinin qurulma müddəti",
        "status": "Gecikmə yüksəkdir",
    },
    {
        "name": "1C-SUMQAYIT-01",
        "type": "Fayl",
        "address": "\\\\anbar\\1c_exchange",
        "stores": "2 mağaza",
        "latency": "—",
        "latency_meaning": "Qovluğun oxunma müddəti",
        "status": "Bağlantı yoxdur",
    },
]

BACKUPS: Final = [
    {
        "date": "12.08.2026 02:00",
        "size": "1.8 GB",
        "kind": "Avtomatik",
        "status": "Uğurlu",
        "ok": "1",
    },
    {
        "date": "11.08.2026 02:00",
        "size": "1.8 GB",
        "kind": "Avtomatik",
        "status": "Uğurlu",
        "ok": "1",
    },
    {
        "date": "10.08.2026 16:24",
        "size": "1.7 GB",
        "kind": "Manual — R.M.",
        "status": "Uğurlu",
        "ok": "1",
    },
    {
        "date": "10.08.2026 02:00",
        "size": "—",
        "kind": "Avtomatik",
        "status": "Uğursuz — disk dolu",
        "ok": "0",
    },
    {
        "date": "09.08.2026 02:00",
        "size": "1.7 GB",
        "kind": "Avtomatik",
        "status": "Uğurlu",
        "ok": "1",
    },
]

AUDIT_ENTRIES: Final = [
    {
        "time": "12.08 09:58",
        "user": "Elvin Həsənov",
        "action": "Giriş təsdiqləndi",
        "module": "Davamiyyət",
        "detail": "Aysel Quliyeva · 09:42",
    },
    {
        "time": "12.08 09:47",
        "user": "Elvin Həsənov",
        "action": "Vaxt manual dəyişdirildi",
        "module": "Davamiyyət",
        "detail": "09:42 → 09:05 · Cüt Nəzarət",
    },
    {
        "time": "12.08 09:31",
        "user": "Günel Rəhimova",
        "action": "Cərimə yaradıldı",
        "module": "Cərimələr",
        "detail": "Nigar Səfərova · 25 ₼",
    },
    {
        "time": "12.08 08:12",
        "user": "Rəşad Məmmədov",
        "action": "Rol icazəsi dəyişdirildi",
        "module": "İcazələr",
        "detail": "HR_Admin · +3 icazə",
    },
    {
        "time": "11.08 23:14",
        "user": "ROOT",
        "action": "Modul deaktiv edildi",
        "module": "ROOT",
        "detail": "Satış xalları · müvəqqəti",
    },
    {
        "time": "11.08 18:02",
        "user": "Kamran Vəliyev",
        "action": "Tabel təsdiqləndi",
        "module": "Tabel",
        "detail": "İstikbal Gənclik · 11.08",
    },
    {
        "time": "11.08 14:39",
        "user": "Günel Rəhimova",
        "action": "Etiraz qəbul edildi",
        "module": "Cərimələr",
        "detail": "Rəvan İsmayılov · 25 ₼ ləğv",
    },
    {
        "time": "11.08 10:05",
        "user": "Rəşad Məmmədov",
        "action": "PIN sıfırlandı",
        "module": "İstifadəçilər",
        "detail": "Murad Əliyev",
    },
]

NOTIFICATIONS: Final = [
    {
        "id": "n1",
        "kind": "error",
        "category": "system",
        "title": "1C-SUMQAYIT-01 bağlantısı kəsildi",
        "body": "2 mağaza sinxronizasiya olunmur.",
        "time": "05:41",
        "unread": "1",
    },
    {
        "id": "n2",
        "kind": "warning",
        "category": "approval",
        "title": "4 sorğu təsdiq gözləyir",
        "body": "Ən uzunu 4 dəqiqədir növbədədir.",
        "time": "09:58",
        "unread": "1",
    },
    {
        "id": "n3",
        "kind": "info",
        "category": "approval",
        "title": "Yeni cərimə etirazı — Aysel Quliyeva",
        "body": "İcazəsiz çıxış · 40 ₼ · sənəd əlavə edilib.",
        "time": "Dünən 16:12",
        "unread": "1",
    },
    {
        "id": "n4",
        "kind": "success",
        "category": "approval",
        "title": "Tabel təsdiqləndi — İstikbal Gənclik",
        "body": "Kamran Vəliyev 11 Avqust tabelini bağladı.",
        "time": "11.08 18:02",
    },
    {
        "id": "n5",
        "kind": "system",
        "category": "system",
        "title": "Gecə ehtiyat nüsxəsi uğurla tamamlandı",
        "body": "1.8 GB · 12.08.2026 02:00",
        "time": "02:04",
    },
]

TENANTS: Final = [
    {
        "id": "mq-0041",
        "name": "Mebel Qrup MMC",
        "version": "2.4.0",
        "users": "235",
        "last_seen": "2 dəq əvvəl",
        "status": "Aktiv",
        "license_until": "12.03.2027",
    },
    {
        "id": "ed-0055",
        "name": "Ev Dekor ASC",
        "version": "2.3.2",
        "users": "88",
        "last_seen": "17 dəq əvvəl",
        "status": "Aktiv",
        "license_until": "04.01.2027",
    },
    {
        "id": "nm-0102",
        "name": "Nur Mebel",
        "version": "2.4.0",
        "users": "41",
        "last_seen": "3 saat əvvəl",
        "status": "Sınaq — 12 gün",
        "license_until": "24.08.2026",
    },
    {
        "id": "bo-0117",
        "name": "Bakı Ofis Mebel",
        "version": "2.2.7",
        "users": "19",
        "last_seen": "6 gün əvvəl",
        "status": "Deaktiv",
        "license_until": "—",
    },
    {
        "id": "rm-0088",
        "name": "Region Mebel LTD",
        "version": "2.4.0",
        "users": "126",
        "last_seen": "1 saat əvvəl",
        "status": "Aktiv",
        "license_until": "30.11.2026",
    },
]

UNASSIGNED_SALES: Final = [
    {
        "receipt": "4471",
        "date": "12.08 14:22",
        "amount": "1 240 ₼",
        "suggestion": "A. Quliyeva",
        "confidence": "62",
    },
    {
        "receipt": "4468",
        "date": "12.08 12:05",
        "amount": "680 ₼",
        "suggestion": "",
        "confidence": "18",
    },
    {
        "receipt": "4455",
        "date": "11.08 18:41",
        "amount": "2 150 ₼",
        "suggestion": "K. Vəliyev",
        "confidence": "71",
    },
    {
        "receipt": "4441",
        "date": "11.08 11:17",
        "amount": "395 ₼",
        "suggestion": "N. Səfərova",
        "confidence": "54",
    },
    {
        "receipt": "4433",
        "date": "10.08 16:58",
        "amount": "355 ₼",
        "suggestion": "",
        "confidence": "9",
    },
]

EMPLOYEE_NAMES: Final = [
    "A. Quliyeva",
    "K. Vəliyev",
    "N. Səfərova",
    "M. Əliyev",
    "R. İsmayılov",
]

#: #20 (kompasos11.md Faza 8) — Performans Qiymətləndirməsi formasının işçi
#: dropdown-u `(id, tam_ad)` cütü gözləyir (`PerformanceReviewScreen.
#: set_employees`), `EMPLOYEE_NAMES`-in sadə mətn siyahısı bunun üçün
#: kifayət etmir.
EMPLOYEE_ID_NAMES: Final = [
    ("00000000-0000-0000-0000-0000000000a1", "Aysel Quliyeva"),
    ("00000000-0000-0000-0000-0000000000a2", "Kamran Vəliyev"),
    ("00000000-0000-0000-0000-0000000000a3", "Nərmin Səfərova"),
]

STORES: Final = [
    "Bellona 28 May",
    "Yataş Xətai",
    "İstikbal Gənclik",
    "Enza Home Gəncə",
]

FINE_TYPES: Final = [
    "Gecikmə",
    "Forma qaydası",
    "İcazəsiz çıxış",
    "Kassa uyğunsuzluğu",
]

#: Faza 7 — Növbə Matrisindəki İŞ REJİMİ seçicisinin maket məzmunu:
#: `(work_mode_id, etiket)`. Canlı yol eyni formanı `work_modes` kataloqundan
#: qurur (`controllers/shift_matrix.py::refresh`). Siyahıda GECƏ NÖVBƏSİ
#: qəsdən var: maket onu göstərmirsə, `is_overnight` yolunun ekranda necə
#: göründüyü heç vaxt gözlə yoxlanmazdı.
WORK_MODE_CHOICES: Final[list[tuple[str, str]]] = [
    ("00000000-0000-0000-0000-0000000000b1", "Səhər · 09:00–18:00"),
    ("00000000-0000-0000-0000-0000000000b2", "Axşam · 13:00–22:00"),
    ("00000000-0000-0000-0000-0000000000b3", "Gecə · 22:00–06:00"),
    ("00000000-0000-0000-0000-0000000000b4", "Növbəli 2/2 · Sərbəst növbə"),
]

#: Seçicinin yanındakı nişan — gündəlik norma `bitmə − başlanğıc` fərqindən
#: çıxır (`domain/work_norm.daily_norm_hours`). 09:00–18:00 = 9 saat, hüquqi
#: gündəlik norma isə 8-dir: maket məhz SIXILMA halını göstərir ki, mətnin
#: özü də (artıq hissə aşım jurnalında) gözlə yoxlana bilsin.
WORK_MODE_NORM_LABEL: Final[str] = (
    "İş Rejimi: 09:00–18:00 · norma 8.00 saat/gün (plan 9 saat, artıq hissə aşım jurnalında)"
)

#: #13 — Növbə Matrisindəki tarixi nümunə kartının maket məzmunu:
#: (ISO həftə günü, orta işçi sayı). Həftə günlərinin ADI burada YOXDUR —
#: onu `weekday_name_az()` verir, yəni maket və canlı yol eyni mənbədən
#: adlanır (CLAUDE.md §6). Rəqəmlər həftə sonuna doğru artır, çünki mağaza
#: trafiki real olaraq belədir və maket inandırıcı görünməlidir.
STAFFING_PATTERN: Final[list[tuple[int, float]]] = [
    (1, 2.1),
    (2, 2.0),
    (3, 2.4),
    (4, 2.6),
    (5, 3.1),
    (6, 3.8),
    (7, 3.5),
]

# --------------------------------------------------------------------------- #
# Face Control (facecontrol.md Faza 4)
#
# AÇARLAR CANLI YOLLA EYNİDİR və bu, təsadüf deyil: hər sözlük
# `controllers/face_control.py` (qeydiyyat/istisna), `controllers/kiosk.py::
# face_result_row` (overlay) və `controllers/root_control.py` (mağaza əhatəsi)
# funksiyalarının qaytardığı forma ilə eynidir. Maket öz ad məkanını qursaydı,
# uyğunsuzluq yalnız istehsalatda — kioskda duran işçinin qarşısında — üzə
# çıxardı (`shell/menu.py` başlığındakı tarixi qüsur).
# --------------------------------------------------------------------------- #

#: Qeydiyyat ekranının işçi siyahısı. ÜÇ VƏZİYYƏTİN HƏR BİRİ VAR — maket
#: yalnız `NEW` göstərsəydi, «Köhnəlib» nişanı və yenidən-qeydiyyat rejimi
#: heç vaxt gözlə yoxlanmazdı (bax `WORK_MODE_CHOICES`-dakı eyni qərar).
FACE_ENROLLMENT_EMPLOYEES: Final[list[dict[str, str]]] = [
    {
        "id": "00000000-0000-0000-0000-0000000000f1",
        "name": "Aysel Quliyeva",
        "store": "Bellona 28 May",
        "state": "NEW",
        "enrolled_at": "",
    },
    {
        "id": "00000000-0000-0000-0000-0000000000f2",
        "name": "Murad Əliyev",
        "store": "Yataş Xətai",
        "state": "ENROLLED",
        "enrolled_at": "14.02.2026 10:20",
    },
    {
        "id": "00000000-0000-0000-0000-0000000000f3",
        "name": "Nigar Səfərova",
        "store": "Bellona 28 May",
        "state": "STALE",
        "enrolled_at": "03.03.2025 09:05",
    },
]

#: Kadr sayı ROOT parametrindəndir — maket də onu `DEFAULT_LIMITS`-dən oxuyur
#: ki, ekranda sabit ədəd yazılmasın (CLAUDE.md §5).
FACE_ENROLLMENT_CAMERA: Final[dict[str, str]] = {
    "available": "1",
    "message": "Kamera hazırdır. İşçi kameraya baxsın və [Çək] düyməsini basın.",
    "frame_count": str(DEFAULT_LIMITS[SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT]),
}

#: Son cəhdin nəticəsi — maketdə QİSMƏN uğurlu hal seçilib (5 kadrdan 4-ü),
#: çünki «hamısı keçdi» halı kadr-kadr cədvəlini boş göstərərdi.
FACE_ENROLLMENT_RESULT: Final[dict[str, str]] = {
    "accepted": "1",
    "message": "Üz qeydiyyatı tamamlandı — 4/5 kadrın ortası istinad kimi saxlanıldı.",
    "frames_total": "5",
    "frames_accepted": "4",
    "archived": "0",
}

#: Kadr-kadr nəticə: rədd səbəbi KONKRETDİR (bənd 1) — «uğursuz» yazmaq
#: operatoru işıq, bucaq və kamera arasında təsadüfi axtarışa məcbur edərdi.
FACE_ENROLLMENT_FRAMES: Final[list[dict[str, str]]] = [
    {"index": "1", "accepted": "1", "quality": "0.82", "reason": "—"},
    {"index": "2", "accepted": "0", "quality": "0.31", "reason": "Kadr çox qaranlıqdır"},
    {"index": "3", "accepted": "1", "quality": "0.77", "reason": "—"},
    {"index": "4", "accepted": "1", "quality": "0.69", "reason": "—"},
    {"index": "5", "accepted": "1", "quality": "0.74", "reason": "—"},
]

#: İstisna ekranının işçi seçimi.
FACE_EXEMPTION_EMPLOYEES: Final[list[dict[str, str]]] = [
    {"id": "00000000-0000-0000-0000-0000000000f1", "name": "Aysel Quliyeva"},
    {"id": "00000000-0000-0000-0000-0000000000f2", "name": "Murad Əliyev"},
    {"id": "00000000-0000-0000-0000-0000000000f3", "name": "Nigar Səfərova"},
]

#: Tavan ROOT parametrindən, minimum uzunluq isə SXEM `CHECK`-indən gəlir —
#: ikisi fərqli mənbələrdir və maket də onları qarışdırmır.
FACE_EXEMPTION_LIMITS: Final[dict[str, str]] = {
    "max_days": str(DEFAULT_LIMITS[SystemLimitKey.FACE_EXEMPTION_MAX_DAYS]),
    "min_reason_length": "10",
}

FACE_EXEMPTIONS: Final[list[dict[str, str]]] = [
    {
        "id": "00000000-0000-0000-0000-0000000000e1",
        "employee": "Nigar Səfərova",
        "reason": "Üz cərrahiyyəsindən sonra sağalma dövrü — həkim arayışı var",
        "expires_at": "10.10.2026 09:00",
        "days_remaining": "56 gün",
        "granted_by": "Root İstifadəçi",
    },
]

#: Kiosk overlay-inin maket nəticələri — `outcome` açarı `FaceGateOutcome`
#: dəyəridir (ekran öz ad məkanını qurmur). Üç ƏSAS hal saxlanılır, çünki
#: bənd 3 məhz onların FƏRQLİ mətnlə göstərilməsini tələb edir.
FACE_VERIFICATION_RESULTS: Final[list[dict[str, str]]] = [
    {
        "outcome": "ALLOWED",
        "message": "Üz təsdiqləndi.",
        "gesture": "Gözlərinizi qırpın",
        "confidence": "88%",
        "retry": "0",
    },
    {
        "outcome": "RETRY",
        "message": "Üz aşkarlanmadı. İşığa tərəf dönüb yenidən cəhd edin.",
        "gesture": "Başınızı yavaşca sağa çevirin",
        "confidence": "",
        "retry": "1",
    },
    {
        "outcome": "BLOCKED",
        "message": "Üz uyğun gəlmədi. Əməliyyat dayandırıldı.",
        "gesture": "Gülümsəyin",
        "confidence": "41%",
        "retry": "0",
    },
]

#: Overlay maketinin GÖSTƏRDİYİ sətir — dizayn yoxlaması üçün ən çox məlumat
#: daşıyan hal (`RETRY`: göstəriş + mesaj + yenidən-cəhd düyməsi birlikdə).
FACE_VERIFICATION_RESULT: Final[dict[str, str]] = FACE_VERIFICATION_RESULTS[1]

#: ROOT panelindəki «Face Control mağazaları» sahəsi (bənd 15).
#: `active` sətirlərdən HEÇ BİRİ seçilməsəydi maketdə «boş = qlobal» halı
#: görünərdi, hamısı seçilsəydi isə pilot rejimi görünməzdi — ona görə
#: qarışıqdır.
FACE_STORE_SCOPE: Final[list[dict[str, str]]] = [
    {"id": "00000000-0000-0000-0000-0000000000a1", "name": "Bellona 28 May", "active": "1"},
    {"id": "00000000-0000-0000-0000-0000000000a2", "name": "Yataş Xətai", "active": "0"},
    {"id": "00000000-0000-0000-0000-0000000000a3", "name": "İstikbal Gənclik", "active": "0"},
    {"id": "00000000-0000-0000-0000-0000000000a4", "name": "Enza Home Gəncə", "active": "0"},
]

#: ROOT panelindəki hədd xülasəsi — TƏRS CÜT XƏBƏRDARLIĞI (bax
#: `FaceToleranceBand.resolve`). Maket DÜZGÜN cütü göstərir (`inverted="0"`),
#: çünki xəbərdarlığın YOX olduğu hal da yoxlanılmalıdır.
FACE_TOLERANCE: Final[dict[str, str]] = {
    "match": str(DEFAULT_LIMITS[SystemLimitKey.FACE_MATCH_TOLERANCE]),
    "low_confidence": str(DEFAULT_LIMITS[SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE]),
    "inverted": "0",
    "band_enabled": "1",
}

#: Profil ekranındakı «Üz qeydiyyatı» kartı (bənd 13) — maketdə KÖHNƏLMİŞ
#: qeydiyyat seçilib, çünki xəbərdarlığın ÖZÜ yoxlanılmalı olan hissədir.
FACE_PROFILE_ENROLLMENT: Final[dict[str, str]] = {
    "state": "STALE",
    "enrolled_at": "03.03.2025 09:05",
    "reminder_months": str(DEFAULT_LIMITS[SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS]),
}


__all__ = [
    "AUDIT_ENTRIES",
    "BACKUPS",
    "DASHBOARD",
    "EMPLOYEE_NAMES",
    "ERP_SERVERS",
    "FINES",
    "FINES_BY_BRANCH",
    "FINE_TYPES",
    "LEADERS",
    "NOTIFICATIONS",
    "PERMISSION_GROUPS",
    "PREVIEW_NOW",
    "QUEUE",
    "ROLES",
    "ROSTER_ROWS",
    "SERVER_HEALTH",
    "STAFFING_PATTERN",
    "STORES",
    "SWAP_REQUESTS",
    "TENANTS",
    "UNASSIGNED_SALES",
    "USERS",
    "WORK_MODE_CHOICES",
    "WORK_MODE_NORM_LABEL",
    "DashboardSummary",
    "QueuePreview",
    "build_admin",
    "build_camera_operator",
]


# --------------------------------------------------------------------------- #
# Qrup H — kataloqlar və hesabatlar
# --------------------------------------------------------------------------- #
# `CatalogScreen.set_entries` formatı: `key`, `cells` (`|` ilə ayrılmış),
# `is_active` (`"1"`/`"0"`). Hər kataloqda ən azı bir DEAKTIV sətir var —
# soft delete-in ekranda necə göründüyü də yoxlanılsın deyə (bölmə 4).

WORK_MODES: Final = [
    {"key": "wm-1", "cells": "Səhər növbəsi|09:00 – 18:00", "is_active": "1"},
    {"key": "wm-2", "cells": "Axşam növbəsi|13:00 – 22:00", "is_active": "1"},
    {"key": "wm-3", "cells": "Növbəli 2/2|08:00 – 20:00", "is_active": "1"},
    {"key": "wm-4", "cells": "Qısaldılmış gün|09:00 – 14:00", "is_active": "0"},
]

FINE_TYPE_ROWS: Final = [
    {"key": "ft-1", "cells": "Formaya uyğun geyinməmək|25 ₼", "is_active": "1"},
    {"key": "ft-2", "cells": "Kassa qaydalarına əməl etməmək|50 ₼", "is_active": "1"},
    {"key": "ft-3", "cells": "İcazəsiz çıxış|40 ₼", "is_active": "1"},
    {"key": "ft-4", "cells": "Telefonla danışmaq|15 ₼", "is_active": "0"},
]

LEAVE_TYPE_ROWS: Final = [
    {"key": "lt-1", "cells": "Nahar fasiləsi|60 dəq", "is_active": "1"},
    {"key": "lt-2", "cells": "Siqaret fasiləsi|10 dəq", "is_active": "1"},
    {"key": "lt-3", "cells": "Şəxsi iş|45 dəq", "is_active": "1"},
    {"key": "lt-4", "cells": "Bank işi|90 dəq", "is_active": "0"},
]

# --------------------------------------------------------------------------- #
# Qrup I — infrastruktur, plugin, panel qurucusu
# --------------------------------------------------------------------------- #

DB_SWITCH_WARNINGS: Final = [
    "Sinxronlaşmamış 12 offline yazı var — keçiddən əvvəl göndərilməlidir.",
    "Sumqayıt serveri 3 saatdır cavab vermir.",
]

DB_SWITCH_HISTORY: Final = [
    {
        "date": "02.06.2026 02:00",
        "direction": "Cloud → Özəl server",
        "checksum": "a3f9c1…d84b",
        "result": "Geri qaytarıldı",
    },
    {
        "date": "14.03.2026 03:00",
        "direction": "Özəl server → Cloud",
        "checksum": "7e21b8…04ca",
        "result": "Uğurlu",
    },
]

PLUGINS: Final = [
    {
        "id": "pl-1",
        "name": "Anbar Hesabatı",
        "version": "1.2.0",
        "publisher": "Kompas Studio",
        "enabled": "1",
        "signature": "valid",
    },
    {
        "id": "pl-2",
        "name": "SMS Bildiriş Körpüsü",
        "version": "0.9.4",
        "publisher": "Kompas Studio",
        "enabled": "0",
        "signature": "valid",
    },
    {
        "id": "pl-3",
        "name": "Köhnə 1C Adapteri",
        "version": "0.3.1",
        "publisher": "Naməlum",
        "enabled": "0",
        "signature": "unsigned",
    },
]

#: Maketdə interfeys səthi verən plugin-lər (audit G-3).
#:
#: ÜÇ SƏTİR ÜÇ AYRI HALI GÖSTƏRİR və bu, qəsdəndir — maket yalnız "yaxşı
#: hal"ı göstərsəydi, təhlükəsizlik qapıları dizayn nəzərdən keçirilərkən
#: görünməz qalardı:
#:   * `pl-1` — TƏSDİQLƏNMİŞ, imzalı, flag-li → menyuda GÖRÜNÜR;
#:   * `pl-2` — SÖNDÜRÜLMÜŞ (`DISABLED`) → səth VERMİR;
#:   * `pl-3` — imzasız VƏ flagsız → səth VERMİR.
#: Açarlar canlı yolla eyni funksiyadan qurulur (`plugin_surface.
#: plugin_page_key`), yəni maket öz ad məkanını YARATMIR.
PLUGIN_SURFACE: Final = (
    ApprovedPlugin(
        plugin_id="pl-1",
        name="Anbar Hesabatı",
        publisher="Kompas Studio",
        status=PluginStatus.APPROVED,
        signature_verified=True,
        manifest=PluginManifest(
            name="Anbar Hesabatı",
            version="1.2.0",
            publisher="Kompas Studio",
            capabilities=frozenset(
                {PluginCapability.REGISTER_PAGE, PluginCapability.RENDER_WIDGET}
            ),
            entry_point="anbar_hesabati.py",
            description_az="Anbar qalığının filial üzrə xülasəsi.",
            # FLAG MAKET ADMİNİNDƏ MÖVCUD OLMALIDIR (`_ADMIN_FLAGS`) — əks
            # halda maddə maketdə də doğru şəkildə GİZLƏNƏR və dizayn
            # baxışında "plugin səhifəsi işləmir" kimi oxunardı. Hesabat
            # plugin-i üçün `can_export_reports` həm də semantik olaraq
            # doğrudur (`menu.py`-dakı «Hesabatlar» maddəsinin flag-i).
            required_flags=frozenset({"can_export_reports"}),
        ),
    ),
    ApprovedPlugin(
        plugin_id="pl-2",
        name="SMS Bildiriş Körpüsü",
        publisher="Kompas Studio",
        status=PluginStatus.DISABLED,
        signature_verified=True,
        manifest=PluginManifest(
            name="SMS Bildiriş Körpüsü",
            version="0.9.4",
            publisher="Kompas Studio",
            capabilities=frozenset({PluginCapability.REGISTER_PAGE}),
            entry_point="sms_bridge.py",
            required_flags=frozenset({"can_broadcast_announcements"}),
        ),
    ),
    ApprovedPlugin(
        plugin_id="pl-3",
        name="Köhnə 1C Adapteri",
        publisher="Naməlum",
        status=PluginStatus.APPROVED,
        signature_verified=False,
        manifest=PluginManifest(
            name="Köhnə 1C Adapteri",
            version="0.3.1",
            publisher="Naməlum",
            capabilities=frozenset({PluginCapability.REGISTER_PAGE}),
            entry_point="legacy_1c.py",
        ),
    ),
)

DASHBOARD_WIDGETS: Final = {
    "attendance": ("Davamiyyət xülasəsi", "Bu gün mağazada olan işçilərin sayı"),
    "fines": ("Cərimələr — filial üzrə", "Ayın cərimələri sütun qrafiki"),
    "leave_gauge": ("İcazə istifadəsi", "Aylıq limitə nisbətdə istifadə"),
    "points": ("Xal liderləri", "Ən çox satış xalı toplayan işçilər"),
    "health": ("Server sağlamlığı", "1C serverlərinin gecikməsi"),
    "tasks": ("Açıq tapşırıqlar", "Gecikən və gözləyən tapşırıqlar"),
}

DASHBOARD_ORDER: Final = ["attendance", "fines", "leave_gauge", "points", "health", "tasks"]
#: `tasks` QƏSDƏN gizlidir — gizli widget-in ekranda necə göründüyü yoxlanılsın.
DASHBOARD_VISIBLE: Final = {"attendance", "fines", "leave_gauge", "points", "health"}

#: Şəbəkə sütun sayı (audit G-5). Canlı yolda `DASHBOARD_GRID_COLUMNS` ROOT
#: parametrindən gəlir; maket onun DEFOLTUNU təkrarlayır ki, iki yol eyni
#: görünüşü versin.
DASHBOARD_GRID_COLUMNS: Final = 2

#: `açar → (sətir, sütun, en)`. Maket QƏSDƏN QARIŞIQ bir şəbəkə göstərir:
#: tam-enli sətir (`attendance`), yan-yana iki kart (`fines` + `leave_gauge`)
#: və BOŞ XANALI sətir (`health` tək qalır) — sonuncu, deşiyin çökmə
#: yaratmadığını maketdə də görünən hala çevirir.
DASHBOARD_PLACEMENTS: Final = {
    "attendance": (0, 0, 2),
    "fines": (1, 0, 1),
    "leave_gauge": (1, 1, 1),
    "points": (2, 0, 1),
    "health": (3, 0, 1),
    "tasks": (4, 0, 2),
}

# --------------------------------------------------------------------------- #
# İstisnalar (#9, kompasos11.md Faza 5)
# --------------------------------------------------------------------------- #
# Açarlar `ExceptionsController._to_row`-un qaytardığı sözlüklə EYNİDİR —
# ikisi fərqli ad məkanı işlətsəydi, uyğunsuzluq yalnız istehsalatda üzə
# çıxardı (CLAUDE.md bölmə 6, `menu.py` başlığındakı tarixi qüsur).

EXCEPTIONS: Final = [
    {
        "id": "exc-1",
        "source": "BEHAVIOR_ANOMALY",
        "source_name": "Davranış Anomaliyası",
        "employee": "Kamran Vəliyev",
        "store": "İstikbal Gənclik",
        "detail": "Son 30 günün orta check-in vaxtından 42 dəqiqə sapma.",
        "severity": "HIGH",
        "severity_text": "Yüksək",
        "date": "12.08.2026 09:15",
    },
    {
        "id": "exc-2",
        "source": "BEHAVIOR_ANOMALY",
        "source_name": "Davranış Anomaliyası",
        "employee": "Nərmin Əliyeva",
        "store": "Bellona 28 May",
        "detail": "Son 30 günün orta check-in vaxtından 18 dəqiqə sapma.",
        "severity": "MEDIUM",
        "severity_text": "Orta",
        "date": "11.08.2026 08:52",
    },
]

# --------------------------------------------------------------------------- #
# #19 Elan (Broadcast) — kompasos11.md Faza 8
# --------------------------------------------------------------------------- #
# Açarlar `AnnouncementsAdminController._to_admin_row`-un qaytardığı sözlüklə
# EYNİDİR (CLAUDE.md bölmə 6).

ANNOUNCEMENTS: Final = [
    {
        "id": "ann-1",
        "title": "Bayram iş qrafiki",
        "scope_text": "Bütün mağazalar",
        "date": "12.08.2026 09:00",
        "is_active": "1",
    },
    {
        "id": "ann-2",
        "title": "Yataş Xətai — inventarizasiya",
        "scope_text": "Seçilmiş mağazalar",
        "date": "05.08.2026 14:30",
        "is_active": "1",
    },
    {
        "id": "ann-3",
        "title": "Yay saatları (KEÇMİŞ)",
        "scope_text": "Bütün mağazalar",
        "date": "01.06.2026 08:00",
        "is_active": "0",
    },
]

# --------------------------------------------------------------------------- #
# #20 Performans Qiymətləndirməsi — kompasos11.md Faza 8
# --------------------------------------------------------------------------- #
# `PERFORMANCE_REVIEW_KPI_CATALOG` (`policies.py` defoltu) ilə EYNİ dörd kod —
# maket real KPI kataloqu ilə uyğun görünsün deyə (CLAUDE.md bölmə 6).

PERFORMANCE_REVIEW_KPIS: Final = [
    ("KEYFIYYET", "İş Keyfiyyəti"),
    ("MEHSULDARLIQ", "Məhsuldarlıq"),
    ("KOMANDA_ISI", "Komanda İşi"),
    ("MUSTERI_XIDMETI", "Müştəri Xidməti"),
]

PERFORMANCE_REVIEW_HISTORY: Final = [
    {
        "period": "2026-Q2",
        "overall_score": "82.50",
        "reviewer": "Rəşad Məmmədov",
        "ratings_text": "KEYFIYYET: 4, MEHSULDARLIQ: 4, KOMANDA_ISI: 5, MUSTERI_XIDMETI: 4",
        "notes": "Komanda işində nümunəvi, satış hədəflərini davamlı yerinə yetirir.",
    },
    {
        "period": "2026-Q1",
        "overall_score": "70.00",
        "reviewer": "Rəşad Məmmədov",
        "ratings_text": "KEYFIYYET: 3, MEHSULDARLIQ: 4, KOMANDA_ISI: 4, MUSTERI_XIDMETI: 3",
        "notes": "Müştəri xidmətində irəliləyiş lazımdır.",
    },
]

# --------------------------------------------------------------------------- #
# #21 İşdən Çıxma Riski — kompasos11.md Faza 9
# --------------------------------------------------------------------------- #
# Açarlar `controllers/attrition_risk.py::_to_row`-un qaytardığı sözlüklə
# EYNİDİR (CLAUDE.md bölmə 6 — maket və canlı yol EYNİ açarları işlədir).

ATTRITION_RISK_SCORES: Final = [
    {
        "employee": "Nərmin Əliyeva",
        "store": "Bellona 28 May",
        "score": "78",
        "band_text": "Yüksək risk",
        "is_high_risk": "1",
        "factors_text": (
            "Son 3 ayın yarımlarında cərimə sayı 1 → 4 (artım: 3). • "
            "Son 3 ayda 2 icazəsiz davamiyyət pozuntusu qeydə alınıb. • "
            "Cari ay icazə istifadəsi aylıq limitin 85%-i."
        ),
    },
    {
        "employee": "Kamran Hüseynov",
        "store": "Yataş Xətai",
        "score": "42",
        "band_text": "Normal",
        "is_high_risk": "0",
        "factors_text": (
            "Staj 1.2 ay — 3 aylıq yeni-işçi həddindən azdır (onboarding riski). • "
            "Cari ay icazə istifadəsi aylıq limitin 30%-i."
        ),
    },
    {
        "employee": "Aygün Rzayeva",
        "store": "Bellona 28 May",
        "score": "12",
        "band_text": "Normal",
        "is_high_risk": "0",
        "factors_text": "Son 3 ayın yarımlarında cərimə sayı 2 → 2 (artım: 0).",
    },
]

# --------------------------------------------------------------------------- #
# #26 Mağaza Auditi + #27 İnsident Bildirişi — kompas1.md Faza 3
# --------------------------------------------------------------------------- #
# Açarlar `controllers/field_reports.py`-dakı `_template_row` / `_category_row`
# / `_report_row` funksiyalarının qaytardığı sözlüklərlə HƏRFİ-HƏRFİNƏ eynidir
# (CLAUDE.md §6 — maket və canlı yol EYNİ açarları işlədir). Uyğunluğu
# `tests/unit/test_field_report_screen.py` qoruyur.
#
# Şablon kodları və mətnlər `migrations/037`-nin seed sətirlərindəndir —
# önizləmə uydurma ad məkanı qurmur.

FIELD_REPORT_AUDIT_TEMPLATES: Final = [
    {
        "code": "STORE_AUDIT",
        "name": "Mağaza ziyarəti / audit",
        "description": (
            "Strukturlaşdırılmış checklist üzrə mağaza yoxlaması. Uğursuz "
            "bloklayıcı bənd Tapşırıq Mühərrikində düzəliş tapşırığı yaradır."
        ),
        "requires_checklist": "1",
    }
]

FIELD_REPORT_INCIDENT_TEMPLATES: Final = [
    {
        "code": "INCIDENT",
        "name": "İnsident bildirişi",
        "description": (
            "Baş vermiş hadisənin (oğurluq, qəza, avadanlıq nasazlığı, şikayət) "
            "bildirilməsi. Checklist tələb etmir, foto istəyə bağlıdır."
        ),
        "requires_checklist": "0",
    }
]

#: Audit kateqoriyaları MARŞRUTLANMIR — nəticə rola deyil, Tapşırıq
#: Mühərrikinə gedir (migrations/037 `route_to_role` sütun şərhi).
FIELD_REPORT_AUDIT_CATEGORIES: Final = [
    {
        "code": "TEMIZLIK",
        "template": "STORE_AUDIT",
        "name": "Təmizlik və gigiyena",
        "route_text": "marşrutlanmır",
    },
    {
        "code": "AVADANLIQ",
        "template": "STORE_AUDIT",
        "name": "Avadanlıq və təhlükəsizlik",
        "route_text": "marşrutlanmır",
    },
]

FIELD_REPORT_INCIDENT_CATEGORIES: Final = [
    {
        "code": "OGURLUQ",
        "template": "INCIDENT",
        "name": "Oğurluq şübhəsi",
        "route_text": "TEHLUKESIZLIK",
    },
    {
        "code": "SIKAYET",
        "template": "INCIDENT",
        "name": "Müştəri şikayəti",
        "route_text": "HR_ADMIN",
    },
]

#: (mağaza id, ad) — `set_stores()` `open_shift.OpenShiftPostDialog` ilə eyni
#: cüt formasını gözləyir. ID-lər maketdə sabitdir; canlı yolda UUID gəlir.
FIELD_REPORT_STORES: Final = [
    ("11111111-1111-4111-8111-111111111111", "Bellona 28 May"),
    ("22222222-2222-4222-8222-222222222222", "Yataş Xətai"),
]

FIELD_REPORT_OPEN_AUDITS: Final = [
    {
        "id": "fr-audit-1",
        "type_name": "Mağaza ziyarəti / audit",
        "category_name": "Təmizlik və gigiyena",
        "store": "Bellona 28 May",
        "detail": "Anbar arxasında qablaşdırma tullantısı yığılıb, çıxış yolu daralıb.",
        "status": "SUBMITTED",
        "status_text": "Təqdim edildi",
        "score_text": "67%",
        "date": "12.08.2026 09:20",
    },
    {
        "id": "fr-audit-2",
        "type_name": "Mağaza ziyarəti / audit",
        "category_name": "Avadanlıq və təhlükəsizlik",
        "store": "Yataş Xətai",
        "detail": "Kassa yanındakı işıqlandırma bir həftədir işləmir.",
        "status": "IN_PROGRESS",
        "status_text": "İcradadır",
        # Heç bir bənd cavablanmayıbsa «0%» YAZILMIR (bax `audit_score`).
        "score_text": "—",
        "date": "11.08.2026 16:05",
    },
]

FIELD_REPORT_OPEN_INCIDENTS: Final = [
    {
        "id": "fr-inc-1",
        "type_name": "İnsident bildirişi",
        "category_name": "Oğurluq şübhəsi",
        "store": "Bellona 28 May",
        "detail": "Nümayiş masasından bir ədəd aksesuar itkin düşüb.",
        "status": "SUBMITTED",
        "status_text": "Təqdim edildi",
        "score_text": "—",
        "date": "12.08.2026 08:41",
    }
]

#: ROOT parametrləri DƏYƏRİ İLƏ TƏKRARLANMIR — maket də `DEFAULT_LIMITS`-dən
#: oxuyur, əks halda limit dəyişəndə önizləmə köhnə ədədi göstərərdi.
FIELD_REPORT_MAX_PHOTOS: Final = int(DEFAULT_LIMITS[SystemLimitKey.FIELD_REPORT_MAX_PHOTOS])
FIELD_REPORT_MIN_DETAIL: Final = int(DEFAULT_LIMITS[SystemLimitKey.FIELD_REPORT_MIN_DETAIL_LENGTH])

# --------------------------------------------------------------------------- #
# #28 İllik Məzuniyyət Balansı — kompas1.md Faza 4
# --------------------------------------------------------------------------- #
# Açarlar `controllers/annual_leave.py`-dakı `_to_balance_row` / `_to_inbox_row`
# funksiyalarının qaytardığı sözlüklərlə HƏRFİ-HƏRFİNƏ eynidir (CLAUDE.md §6).
# Uyğunluğu `tests/unit/test_annual_leave_screen.py` qoruyur.
#
# BU, GÜNDAXİLİ İCAZƏ MAKETİ DEYİL: yuxarıdakı `LEAVE_*` dəstləri STEP1/STEP2
# axınına (DƏQİQƏ) aiddir, bu isə İLLİK haqqdır (GÜN) — üç ayrı mexanizmin
# izahı `screens/annual_leave.py` başlığındadır.

#: `total` ROOT DEFOLTUNDAN oxunur, ƏL İLƏ yazılmır — baza haqq dəyişəndə maket
#: köhnə ədədi göstərməsin (`FIELD_REPORT_*` ilə eyni qərar). "14/21 gün qalıb"
#: cümləsini EKRAN qurur, maket yalnız rəqəmləri verir.
#:
#: NİYƏ MAKETDƏ KÖÇÜRMƏ SIFIRDIR: köçürmə İSTİSNA haldır (yalnız keçən ildən
#: gün qalan işçidə olur), maket isə ƏN ADİ vəziyyəti göstərməlidir — və
#: `policies.py`-dakı `ANNUAL_LEAVE_ACCRUAL_PERIOD` şərhi məhz bu kartı
#: "14/21" kimi təsvir edir. Köçürmə sətri yenə də GÖRÜNÜR (solğun tonda son
#: tarixlə), yəni "istifadə et ya itir" qaydası maketdən də oxunur;
#: xəbərdarlıq/xəta tonları `tests/unit/test_annual_leave_screen.py`-də
#: yoxlanılır.
_ANNUAL_LEAVE_BASE: Final = DEFAULT_LIMITS[SystemLimitKey.ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS]

ANNUAL_LEAVE_BALANCE: Final = {
    "year": "2026",
    "available": "14",
    "total": str(int(float(_ANNUAL_LEAVE_BASE))),
    "used": "7",
    "carried_over": "0",
    # Son tarix ROOT açarlarından (`..._DEADLINE_MONTH`/`..._DAY`) qurulur:
    # maketdə "31.03" yazsaydıq və Root onu dəyişsəydi, önizləmə yalan
    # danışardı.
    "carryover_deadline": (
        f"{int(DEFAULT_LIMITS[SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY]):02d}."
        f"{int(DEFAULT_LIMITS[SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH]):02d}.2027"
    ),
    "carryover_expired": "0",
}

ANNUAL_LEAVE_PENDING: Final = [
    {
        "id": "al-1",
        "employee": "Aysel Quliyeva",
        "range_text": "14.09.2026 – 25.09.2026",
        "days_text": "12 təqvim günü",
        "submitted": "12.08.2026 09:30",
    },
    {
        "id": "al-2",
        "employee": "Kamran Hüseynov",
        "range_text": "28.12.2026 – 05.01.2027",
        # İL SƏRHƏDİNİ KƏSƏN sorğu maketdə QƏSDƏN var: `_charge_year`
        # bütünlüklə BAŞLANĞIC ilinə yazır və HR bu halı ekranda görməlidir.
        "days_text": "9 təqvim günü",
        "submitted": "11.08.2026 17:12",
    },
]

# --------------------------------------------------------------------------- #
# #29 Toplu Əməliyyatlar — kompas1.md Faza 5
# --------------------------------------------------------------------------- #
# Açarlar `controllers/bulk_operations.py::_preview_payload`/`_to_template_
# rows`-un qaytardığı sözlüklərlə EYNİDİR (CLAUDE.md bölmə 6).

#: `BulkOperationsScreen.set_preview(**...)` — `errors` xaric qalan sahələr
#: TİPLİDİR (str yox), çünki setter imzası `int` gözləyir (bax `bulk_
#: operations.py` ekran modulu). Boş fayl/başlıq-yalnız halı BURADA GÖSTƏRİLMİR
#: — o, `total_rows=0` ilə AYRI budaqdır və maketin məqsədi ADİ (qismən
#: uğurlu) nəticəni nümayiş etdirməkdir.
BULK_IMPORT_PREVIEW_TOTAL_ROWS: Final = 4
BULK_IMPORT_PREVIEW_VALID_COUNT: Final = 2
BULK_IMPORT_PREVIEW_ERROR_COUNT: Final = 2
BULK_IMPORT_PREVIEW_TRUNCATED_EXTRA: Final = 0
BULK_IMPORT_PREVIEW_ERRORS: Final = [
    {"row": "2", "message": "Rol tapılmadı və ya deaktivdir: KASSIR2"},
    {"row": "4", "message": "Bu istifadəçi adı artıq mövcuddur: e.mammadov"},
]

STORE_TEMPLATES: Final = [
    {
        "id": "st-1",
        "name": "Standart Supermarket",
        "source_store": "Bellona 28 May",
        "setting_count": "2",
        "captured_at": "2026-07-01",
        "status": "Aktiv",
    },
    {
        "id": "st-2",
        "name": "Kiçik Format (köhnə)",
        "source_store": "Bellona 6 Mikrorayon",
        "setting_count": "2",
        "captured_at": "2026-05-14",
        "status": "Deaktiv",
    },
]

# --------------------------------------------------------------------------- #
# Export təcrübəsi (pre-export doğrulama, müqayisə, düzəliş) — kompas1.md Faza 8
# --------------------------------------------------------------------------- #
# Açarlar `controllers/report_export.py`-dakı `_role_rows` / `_finding_rows` /
# `_comparison_rows` / `_correction_rows` funksiyalarının qaytardığı
# sözlüklərlə HƏRFƏN EYNİDİR (CLAUDE.md bölmə 6). Maketin öz ad məkanını
# qurması layihədə artıq bir dəfə qüsura çevrilib (bax `menu.py` başlığı) —
# burada həmin səhv təkrarlanmır.

#: `set_role_options()` — siyahı CANLI yolda `positions` kataloqundan gəlir;
#: maketdə isə real quraşdırmanın tipik rolları göstərilir. «Bütün rollar»
#: sətri BURADA YOXDUR: onu ekranın özü əlavə edir (bax `_build_role_filter`).
EXPORT_ROLE_OPTIONS: Final = [
    {"code": "KAMERA_NEZARETCISI", "name": "Kamera Nəzarətçisi"},
    {"code": "MAGAZA_MENECERI", "name": "Mağaza Meneceri"},
    {"code": "SATICI", "name": "Satıcı"},
]

#: `set_validation_findings()` — DÖRD qaydanın hər biri maketdə TƏMSİL OLUNUR
#: ki, dizayn nəzərdən keçirilərkən heç bir hal görünməmiş qalmasın
#: (`domain/export_validation.py::ExportValidationCode`).
EXPORT_VALIDATION_FINDINGS: Final = [
    {
        "rule": "Aralıqdan çox iş günü",
        "subject": "Kamran Vəliyev",
        "detail": (
            "34 iş günü qeydə alınıb, aralıq isə cəmi 31 təqvim günüdür — "
            "davamiyyət qeydlərində təkrar sətir ola bilər."
        ),
    },
    {
        "rule": "Deaktiv işçi tabeldə",
        "subject": "Elvin Məmmədov",
        "detail": (
            "İşçi DEAKTİVDİR, lakin tabeldə hərəkət var: 6 iş günü, "
            "1 icazəsiz qayıb. Deaktivləşdirmə tarixini yoxlayın."
        ),
    },
    {
        "rule": "0 gün / 0 qayıb ziddiyyəti",
        "subject": "Nigar Əliyeva",
        "detail": (
            "22 gün planlaşdırılıb, lakin nə bir iş günü, nə də icazəsiz qayıb "
            "qeydə alınıb — kamera təsdiqi və ya məzuniyyət qeydi çatışmır."
        ),
    },
    {
        "rule": "Mağazada anomal qayıb",
        "subject": "İstikbal Gənclik",
        "detail": (
            "İcazəsiz qayıb nisbəti 18.4% — ROOT həddi 15.0%. 17 qayıb / 92 norma gün, 5 işçi."
        ),
    },
]

#: `set_period_comparison()` — «əhəmiyyətli fərq» nişanı ROOT həddindən
#: (`EXPORT_PERIOD_DELTA_SIGNIFICANT`, defolt 3) asılıdır; maketdə həm aşan,
#: həm aşmayan sətir var ki, hər iki nişan tonu görünsün.
EXPORT_PERIOD_COMPARISON: Final = [
    {
        "metric": "İcazəsiz qayıb",
        "current": "17",
        "previous": "14",
        "delta": "+3",
        "significant": "1",
    },
    {
        "metric": "Faktiki işlənilən gün",
        "current": "612",
        "previous": "610",
        "delta": "+2",
        "significant": "",
    },
    {
        "metric": "Norma iş günləri",
        "current": "648",
        "previous": "648",
        "delta": "0",
        "significant": "",
    },
    {
        "metric": "Off-day sayı",
        "current": "184",
        "previous": "180",
        "delta": "+4",
        "significant": "1",
    },
]

#: `set_period_comparison(caption=...)` — hansı dövrlə müqayisə edildiyi AÇIQ
#: yazılır ("keçən ay" fərziyyəsi səhv olardı, bax `export_preflight.py`).
EXPORT_COMPARISON_CAPTION: Final = "Müqayisə dövrü: 01.07.2026 – 31.07.2026 (eyni uzunluqda)."

#: `set_corrections()` — hər sətrin SƏBƏBİ var və olmalıdır (məcburi sahə).
EXPORT_CORRECTIONS: Final = [
    {
        "employee": "Kamran Vəliyev",
        "date": "2026-08-04",
        "change": "Faktiki işlənilən gün: 34 → 31",
        "reason": "Kassa sistemində təkrar giriş qeydi aşkarlandı, HR aktı 2026/114.",
    },
    {
        "employee": "Nigar Əliyeva",
        "date": "2026-08-11",
        "change": "Xəstəlik vərəqəsi kadrlar şöbəsinə gec təqdim olunub.",
        "reason": "Vərəqə 11.08 tarixli, sistemə 13.08-də daxil edilib.",
    },
]

#: `set_lock_summary(already_exported=..., overlap_notice=...)` — üst-üstə
#: düşən aralıq (Faza 7). Cümlə CANLI yolda `BonusPenaltySelection.
#: overlap_notice_az()`-dan gəlir; maket onun EYNİ formasını daşıyır ki,
#: dizayn baxışında sətir uzunluğu real halla üst-üstə düşsün.
EXPORT_ALREADY_EXPORTED_COUNT: Final = 2
EXPORT_OVERLAP_NOTICE: Final = (
    "2 cərimə bu aralığa düşür, lakin artıq əvvəlki dövr(lər)də tutulub "
    "(2026-07) — təkrar tutulmur."
)

# --------------------------------------------------------------------------- #
# G-1 Sinxronizasiya konfliktləri — bölmə 5 (offline rejim)
# --------------------------------------------------------------------------- #
# Açarlar `controllers/sync_conflicts.py`-dakı `_to_list_row` / `_to_field_rows`
# sözlükləri ilə EYNİDİR (CLAUDE.md bölmə 6 — maket və canlı yol EYNİ açarları
# işlədir). Sahə ADLARI qəsdən baza sütunlarıdır: canlı yolda da `JSONB`
# açarları göstərilir və maket onları tərcümə etsəydi, dizayn baxışı real
# ekrandan fərqli genişlik verərdi.
#
# SIRA USE CASE-DƏN GƏLİR: `SyncConflictUseCase.inbox` audit-kritik sətirləri
# əvvələ çıxarır, ona görə maketdə də `fines` (audit-kritik) birincidir.

SYNC_CONFLICTS: Final = [
    {
        "id": "sc-1",
        "table_label": "Cərimələr",
        "record_label": "Qeyd: 4f2a9c11",
        "detected": "12.08.2026 08:14",
        "diff_count": "2 sahə fərqlidir",
        "audit_critical": "1",
    },
    {
        "id": "sc-2",
        "table_label": "Davamiyyət qeydləri",
        "record_label": "Qeyd: 91b0de77",
        "detected": "12.08.2026 09:02",
        "diff_count": "1 sahə fərqlidir",
        # `attendance_records` bölmə 5-in audit-kritik siyahısında YOXDUR —
        # maket hər iki halı göstərir ki, nişanın fərqi görünsün.
        "audit_critical": "0",
    },
]

#: `set_comparison(detail, fields)` — seçilmiş konfliktin sahə-sahə müqayisəsi.
#: Fərqli sahələr ƏVVƏLDƏ (kontroller onları belə sıralayır).
SYNC_CONFLICT_FIELDS: Final = [
    {
        "field": "amount",
        "local": "45.00",
        "remote": "30.00",
        "differs": "1",
    },
    {
        "field": "status",
        "local": "PENDING_REVIEW",
        "remote": "PUBLISHED",
        "differs": "1",
    },
    {
        "field": "employee_id",
        "local": "7c1d0e44",
        "remote": "7c1d0e44",
        "differs": "0",
    },
    {
        "field": "issued_at",
        "local": "2026-08-11 18:40",
        "remote": "2026-08-11 18:40",
        "differs": "0",
    },
]

#: «Sistem Sağlamlığı» kartındakı keçidin sayğacı — `SYNC_CONFLICTS` ilə
#: eyni ədəd olmalıdır, əks halda maket özü ilə ziddiyyət təşkil edərdi.
SYNC_CONFLICT_OPEN_COUNT: Final = len(SYNC_CONFLICTS)
