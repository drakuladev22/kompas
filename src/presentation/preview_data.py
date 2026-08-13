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


DASHBOARD: Final = DashboardSummary(
    in_store=148,
    planned=156,
    pending=6,
    longest_wait="4 dəq",
    fines_total="3 415 ₼",
    fines_delta="keçən aya nisbətən +12%",
    open_tasks=37,
    overdue_tasks=9,
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

PERMISSION_GROUPS: Final = [
    (
        "Davamiyyət və İcazə",
        [
            ("can_view_leave", "İcazə sorğusuna baxmaq", True, False),
            ("can_approve_leave", "İcazə təsdiqləmək", True, False),
            ("can_delete_attendance", "Giriş/çıxış qeydini silmək", False, True),
            ("can_fill_daily_attendance", "Tabeli təsdiqləmək", True, False),
            ("can_override_return_time", "Vaxtı manual dəyişmək", False, False),
            ("can_approve_dual_control_override", "Cüt nəzarət təsdiqi", False, True),
        ],
    ),
    (
        "Cərimə və Etiraz",
        [
            ("can_issue_fines", "Cərimə yaratmaq", False, False),
            ("can_view_appeals", "Etirazlara baxmaq", True, False),
            ("can_approve_leave_appeal", "Etirazı qəbul/rədd etmək", True, False),
            ("can_manage_fine_types", "Cərimə tariflərini dəyişmək", False, False),
            ("can_delete_fines", "Cəriməni silmək", False, True),
            ("can_export_reports", "Cərimə hesabatı ixracı", True, False),
        ],
    ),
    (
        "Sistem",
        [
            ("can_manage_erp_servers", "ERP server idarəetməsi", False, True),
            ("can_manage_backups", "Ehtiyat nüsxə / Bərpa", False, True),
            ("can_view_audit_logs", "Audit jurnalına baxmaq", True, False),
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

ERP_SERVERS: Final = [
    {
        "name": "1C-BAKI-01",
        "address": "10.20.1.14:1541",
        "stores": "9 mağaza",
        "latency": "42 ms",
        "status": "Aktiv",
    },
    {
        "name": "1C-BAKI-02",
        "address": "10.20.1.15:1541",
        "stores": "6 mağaza",
        "latency": "57 ms",
        "status": "Aktiv",
    },
    {
        "name": "1C-GENCE-01",
        "address": "10.40.3.7:1541",
        "stores": "4 mağaza",
        "latency": "318 ms",
        "status": "Gecikmə yüksəkdir",
    },
    {
        "name": "1C-SUMQAYIT-01",
        "address": "10.60.2.5:1541",
        "stores": "2 mağaza",
        "latency": "—",
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
