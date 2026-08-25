"""Önizləmə məzmununun ekranlara yerləşdirilməsi — Faza 4.2.

`preview_data.py` MƏLUMATI saxlayır, bu modul isə onu ekranlara YAZIR.
İkisi ayrıdır, çünki:

    * `app.py` yalnız "hansı açar → hansı ekran" bağlantısını qurur; nə ilə
      dolduğunu bilmək məcburiyyətində deyil (istehsalatda o, use-case-lərdən
      gələcək);
    * Faza 5-də hər ikisi birlikdə silinir və `app.py`-a toxunulmur.

`populate()` naməlum açar üçün SƏSSİZ keçir — yeni ekran əlavə edildikdə
önizləmə məzmunu olmaya bilər və bu, xəta deyil.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.staffing_signals import weekday_name_az
from src.presentation import preview_data as data

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

    from src.presentation.screens import (
        group_b,
        group_c,
        group_d,
        group_e,
        group_f,
        group_g,
    )


def _dashboard(screen: group_c.DashboardScreen) -> None:
    # Sahələr AÇIQ yazılır (`**data.DASHBOARD` deyil): belə olduqda lüğətdə
    # bir açar səhv adlandırılsa, tip yoxlayıcısı onu burada tutur.
    summary = data.DASHBOARD
    screen.set_summary(
        in_store=summary.in_store,
        planned=summary.planned,
        pending=summary.pending,
        longest_wait=summary.longest_wait,
        fines_total=summary.fines_total,
        fines_delta=summary.fines_delta,
        open_tasks=summary.open_tasks,
        overdue_tasks=summary.overdue_tasks,
    )
    # Maket və canlı yol EYNİ metodu çağırır (`CLAUDE.md` §6): burada rəqəm
    # nümunə şəbəkənindir, istehsalatda isə `screen_data._dashboard_network`
    # onu bazadan gətirir.
    screen.set_network_size(employees=summary.employees, stores=summary.stores)
    screen.set_fines_by_branch(list(data.FINES_BY_BRANCH), period="Avqust 2026")
    screen.set_leave_usage(128, 200)
    screen.set_leaders(list(data.LEADERS))
    screen.set_server_health(list(data.SERVER_HEALTH))
    # Nahar/Çay həddini aşanlar (nahar.md) — maket mətnləri CANLI yolla eyni
    # mənbədən (`BreakAllowance.warning_az()`) qurulur ki, iki yol fərqli
    # ifadə göstərməsin (bax `preview_data.py` başlığı).
    screen.set_break_overuse(list(data.BREAK_OVERUSE))

    # #24 Çox-Mağaza Benchmark (Faza 9A) — canlı yolla EYNİ açarlar
    # (`screen_data.py::_populate_benchmark_sections`), bax `preview_data.py`
    # başlığı.
    from src.presentation.screens.group_c import RankingEntry  # noqa: PLC0415

    screen.set_ranking_table(
        [
            RankingEntry(
                store_id=store_id,
                store_name=store_name,
                value_display=value_display,
                trend_arrow=trend_arrow,
                trend_label=trend_label,
            )
            for store_id, store_name, value_display, trend_arrow, trend_label in (
                data.BENCHMARK_RANKING
            )
        ],
        metric_options=list(data.BENCHMARK_METRIC_OPTIONS),
        selected_metric="FINE_COUNT",
    )
    versus = data.BENCHMARK_STORE_VS_NETWORK
    screen.set_store_vs_network(
        metric_label=versus.metric_label,
        store_label=versus.store_label,
        store_value=versus.store_value,
        store_display=versus.store_display,
        network_label=versus.network_label,
        network_value=versus.network_value,
        network_display=versus.network_display,
    )
    screen.set_metric_trend(metric_label="Cərimə sayı", points=list(data.BENCHMARK_TREND))
    screen.set_outliers(
        summary_text=data.BENCHMARK_OUTLIERS.summary_text,
        rows=list(data.BENCHMARK_OUTLIERS.rows),
    )

    # v2backlog.md Faza 6 — analitika widget-ləri. Canlı yol flag-QAPILIDIR
    # (`screen_data` fetch-ləri); maketdə isə TAM DƏST göstərilir ki, dizayn
    # bir yerdə yoxlanılsın (MƏRKƏZİ TƏLƏB #2). Açarlar canlı setter
    # imzaları ilə EYNİDİR (CLAUDE.md §6).
    screen.set_cost_center(
        list(data.COST_CENTER_BARS),
        period="Avqust 2026",
        bonus_note=data.COST_CENTER_NOTE,
    )
    screen.set_duplicate_faces(list(data.DUPLICATE_FACES))
    screen.set_operator_performance(list(data.OPERATOR_PERFORMANCE))
    screen.set_campaign_impact(list(data.CAMPAIGN_IMPACT))
    screen.set_workload_fairness(
        list(data.WORKLOAD_FAIRNESS),
        hint="Son 30 gün · median 12 gün · nişan həddi ±4 gün (Root parametri)",
    )


def _live_queue(screen: group_b.OperatorQueueScreen) -> None:
    from src.presentation.screens.group_b import QueueEntry  # noqa: PLC0415

    screen.set_entries(
        [
            QueueEntry(
                request_id=entry.request_id,
                employee_name=entry.employee_name,
                store_name=entry.store_name,
                position_name=entry.position_name,
                kind=entry.kind,
                timestamp_text=entry.timestamp_text,
                waiting_text=entry.waiting_text,
                is_late=entry.is_late,
                # facecontrol.md bənd 12 — nişan CANLI yolda da eyni sahədən
                # gəlir (`screen_data._live_queue`).
                is_low_confidence=entry.is_low_confidence,
            )
            for entry in data.QUEUE
        ]
    )


def _daily_roster(screen: group_c.DailyRosterScreen) -> None:
    screen.set_stats(
        [
            ("Planlaşdırılıb", 9),
            ("Təsdiqli giriş", 7),
            ("Gecikən", 1),
            ("Gəlməyən", 1),
        ]
    )
    screen.set_mismatch(
        "HR planı ilə uyğunsuzluq: Leyla Hüseynova bu gün planda yoxdur, lakin girişi təsdiqlənib."
    )
    screen.set_rows(list(data.ROSTER_ROWS))


def _shift_planning(screen: group_c.ShiftPlanningScreen) -> None:
    weekdays = ("B.e", "Ç.a", "Ç", "C.a", "C", "Ş", "B")
    days = [(day, weekdays[(day - 1) % 7]) for day in range(1, 15)]
    pattern = ["S", "S", "A", "", "S", "M", "S"]
    rows = [
        (name, [pattern[(index + offset) % 7] for index in range(14)])
        for offset, name in enumerate(data.EMPLOYEE_NAMES)
    ]
    screen.set_month("Avqust 2026", stores=list(data.STORES), mode="5/2")
    # Faza 7 — İş Rejimi seçicisi maketdə də DOLU olmalıdır: boş dropdown
    # "funksiya işləmir" kimi oxunardı. Açarlar maket ID-ləridir; canlı yolda
    # eyni setter `work_modes` kataloqunun UUID-lərini alır
    # (`controllers/shift_matrix.py`) — CLAUDE.md §6 "eyni açar" qaydası.
    screen.set_work_modes(list(data.WORK_MODE_CHOICES))
    screen.set_work_mode_norm(data.WORK_MODE_NORM_LABEL)
    screen.set_matrix(days, rows)
    screen.set_summary(
        [
            ("Planlaşdırılmış saat", "1 176"),
            ("Açıq növbə", "4"),
            ("Məzuniyyətdə", "1"),
        ]
    )
    # #13 — maket və canlı yol EYNİ mənbədən ad alır (`weekday_name_az`) və
    # EYNİ setter imzasını işlədir. `preview_screens` öz həftə-günü siyahısını
    # qursaydı, ISO nömrələmə sürüşməsi maketdə görünməz qalar və yalnız
    # istehsalatda üzə çıxardı (CLAUDE.md §6 xəbərdarlığı).
    screen.set_staffing_pattern(
        [
            (weekday_name_az(weekday), f"{average:.1f} nəfər")
            for weekday, average in data.STAFFING_PATTERN
        ],
        store_name=data.STORES[0],
        based_on_weeks=int(DEFAULT_LIMITS[SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS]),
        calculated_label="hesablandı: 11.08.2026",
    )
    # #16 — açarlar canlı yolla EYNİDİR (`id`, `date`, `work_mode`, `store`);
    # bax `controllers/open_shift.py::_to_admin_row`.
    screen.set_open_shift_postings(
        [
            {
                "id": "00000000-0000-0000-0000-000000000016",
                "date": "14.08.2026 · Cüm",
                "work_mode": "Səhər · 09:00–18:00",
                "store": data.STORES[0],
            },
            {
                "id": "00000000-0000-0000-0000-000000000017",
                "date": "16.08.2026 · Baz",
                "work_mode": "Axşam · 13:00–22:00",
                "store": data.STORES[1],
            },
        ]
    )
    # DEEP-GAP OP-4 — «Tutulmuş növbələr» bölməsi maketdə DƏ görünür: bölmə
    # yalnız sətir olduqda çəkilir, yəni nümunə verilməsəydi dizayn nəzərdən
    # keçirilməsində HEÇ VAXT görünməzdi. Açarlar canlı yolla EYNİDİR — dörd
    # ortaq açar + `employee` (bax `_to_claimed_row`).
    screen.set_claimed_open_shifts(
        [
            {
                "id": "00000000-0000-0000-0000-000000000018",
                "date": "18.08.2026 · Çər",
                "work_mode": "Səhər · 09:00–18:00",
                "store": data.STORES[0],
                "employee": "Aygün Məmmədova",
            },
        ]
    )


def _shift_swaps(screen: group_c.ShiftSwapScreen) -> None:
    screen.set_counts({"pending": 4, "approved": 12, "rejected": 3})
    screen.set_requests(list(data.SWAP_REQUESTS))
    screen.set_detail(
        "14 Avqust — Səhər növbəsi",
        [
            ("Sorğunu göndərən", "Aysel Quliyeva"),
            ("Razılıq verib", "Leyla Hüseynova"),
            (
                "Səbəb",
                "Ailə tədbiri səbəbindən həmin gün səhər növbəsində ola bilmirəm.",
            ),
            ("Dəyişikliyin təsiri", "Mağazada işçi sayı dəyişmir"),
        ],
    )


def _fines(screen: group_b.FineEntryScreen) -> None:
    screen.set_price("25 ₼ · avtomatik")
    screen.set_fines(list(data.FINES), period_text="Avqust 2026", total_text="265 ₼")


def _fine_appeals(screen: group_f.FineAppealInboxScreen) -> None:
    screen.set_appeals(
        [
            {
                "id": "a1",
                "employee": "Aysel Quliyeva",
                "fine_type": "İcazəsiz çıxış",
                "amount": "40 ₼",
                "meta": "07 Avqust · Elvin Həsənov yazıb",
                "explanation": ("Mağaza rəhbərinin şifahi icazəsi ilə bank işinə getmişdim."),
                "document": "qeydiyyat.pdf",
            }
        ]
    )


def _tasks(screen: group_f.TasksScreen) -> None:
    screen.set_summary("Bellona 28 May · 12 açıq")
    screen.set_tasks(
        "open",
        [
            {
                "id": "t1",
                "title": "Vitrin yenilənməsi",
                "description": "Yeni kolleksiya üçün vitrin düzülüşü",
                "assignee": "A. Quliyeva",
                "due": "Bu gün",
            },
            {
                "id": "t2",
                "title": "Anbar sayımı",
                "description": "Divan və kreslo bölməsi",
                "assignee": "M. Əliyev",
                "due": "Sabah",
            },
            {
                "id": "t3",
                "title": "Müştəri geri-zəngi",
                "description": "3 gözləyən sifariş üzrə",
                "assignee": "N. Səfərova",
                "due": "14 Avq",
            },
        ],
    )
    screen.set_tasks(
        "review",
        [
            {
                "id": "t4",
                "title": "Kassa zonasının təmizliyi",
                "evidence": "sübut şəkli",
                "assignee": "R. İsmayılov",
                "due": "09:48",
                "reviewable": "1",
            },
            {
                "id": "t5",
                "title": "Qiymət etiketlərinin yenilənməsi",
                "assignee": "K. Vəliyev",
                "due": "Dünən",
                "reviewable": "1",
            },
            # `v2backlog.md` Faza 4.2 — öz-düzəliş sorğusu nümunəsi:
            # `[Təsdiqlə]`/`[Rədd Et]` YOXDUR — açar `controllers/screen_
            # data.py::_tasks_fetch`-lə EYNİDİR (CLAUDE.md §6).
            {
                "id": "t6",
                "title": "Üz tanıma uyğunsuzluğu — öz izahatım",
                "assignee": "Cari istifadəçi",
                "due": "Bugün",
                "reviewable": "0",
            },
        ],
    )
    screen.set_tasks(
        "done",
        [
            {
                "id": "t6",
                "title": "Səhər açılış yoxlaması",
                "status_text": "Təsdiqləndi · +20 xal",
                "due": "09:05",
            },
            {
                "id": "t7",
                "title": "Çatdırılma sənədlərinin təhvili",
                "status_text": "Təsdiqləndi · +15 xal",
                "due": "Dünən",
            },
            {
                "id": "t8",
                "title": "Anbar rəfinin nizamı",
                "status_text": "Rədd edildi — təkrar",
                "due": "10 Avq",
            },
        ],
    )


def _sales_points(screen: group_f.SalesPointsScreen) -> None:
    screen.set_balance(
        1240,
        monthly_delta=180,
        to_next_reward=760,
        next_reward_cost=2000,
        rank_text="21 filial arasında 3-cü",
    )
    screen.set_history(
        [
            {
                "entry_id": "preview-1208",
                "can_appeal": "1",
                "date": "12.08",
                "reason": "Divan satışı — Enza kolleksiyası",
                "status": "Təsdiqli",
                "points": "+45",
            },
            {
                "entry_id": "preview-1108",
                "can_appeal": "1",
                "date": "11.08",
                "reason": "Tapşırıq: səhər açılış yoxlaması",
                "status": "Təsdiqli",
                "points": "+20",
            },
            {
                "entry_id": "preview-1008",
                "can_appeal": "1",
                "date": "10.08",
                "reason": "Yataq dəsti satışı — çek 4471",
                "status": "Gözləyir",
                "points": "+60",
            },
            {
                "entry_id": "preview-0808",
                "can_appeal": "1",
                "date": "08.08",
                "reason": "Satış geri qaytarıldı — çek 4392",
                "status": "Geri alınıb",
                "points": "−30",
            },
            {"date": "05.08", "reason": "Aylıq plan bonusu", "status": "Təsdiqli", "points": "+85"},
        ],
        period="Avqust 2026",
    )
    screen.set_catalog(
        [
            # `id` MAKETDƏ DƏ VAR: canlı yol onu `request_reward` üçün
            # işlədir və iki yol EYNİ AÇARLARI daşımalıdır (CLAUDE.md §6).
            {"id": "preview-reward-1", "name": "Əlavə istirahət günü", "cost": "2000"},
            {"id": "preview-reward-2", "name": "100 ₼ hədiyyə kartı", "cost": "1200"},
            {"id": "preview-reward-3", "name": "Mağaza endirim kuponu", "cost": "600"},
        ],
        balance=1240,
    )
    # MENECER BÖLMƏSİ MAKETDƏ DƏ GÖRÜNÜR: bölmə yalnız sətir olduqda çəkilir,
    # yəni nümunə verilməsəydi dizayn baxışında HEÇ VAXT görünməzdi. Açarlar
    # canlı yolla EYNİDİR (bax `controllers/points_disputes.py::_to_row`).
    # İKİ SƏTİR QƏSDƏN: biri gözləyən, biri VAXTI BİTMİŞ — «vaxt bitdi ≠
    # qərar verildi» (M-6) məhz nişanların yan-yana görünməsi ilə anlaşılır.
    screen.set_disputes(
        [
            {
                "id": "preview-dispute-1",
                "employee": "Aygün Məmmədova",
                "points": "+60 xal",
                "reason": "Çek 4471 mənim satışımdır, kassa səhv işçiyə yazıb.",
                "status": "Gözləyir",
            },
            {
                "id": "preview-dispute-2",
                "employee": "Rəşad Məmmədli",
                "points": "−30 xal",
                "reason": "Geri qaytarma müştəri qərarıdır, satış səhvi deyil.",
                "status": "Vaxtı bitib",
            },
        ]
    )


def _unassigned_sales(screen: group_f.UnassignedSalesScreen) -> None:
    screen.set_sales(list(data.UNASSIGNED_SALES), total_amount="4 820 ₼")


def _users(screen: group_c.UsersScreen) -> None:
    screen.set_users(list(data.USERS))


def _permissions(screen: group_c.PermissionMatrixScreen) -> None:
    screen.set_roles(list(data.ROLES))
    screen.select_role("hr_admin")
    screen.set_matrix("HR_Admin", list(data.PERMISSION_GROUPS))


def _erp_servers(screen: group_d.ErpServersScreen) -> None:
    screen.set_servers(list(data.ERP_SERVERS), mapped_stores=21)
    screen.set_mapping(
        [
            ("Bellona 28 May", "1C-BAKI-01"),
            ("Yataş Xətai", "1C-BAKI-01"),
            ("İstikbal Gənclik", "1C-BAKI-02"),
            ("Enza Home Gəncə", "1C-GENCE-01"),
        ],
        note="Xəritələnməmiş mağaza yoxdur.",
    )
    screen.set_last_sync(
        [
            ("Satış sənədləri", "09:40", "success"),
            ("İşçi kartları", "09:15", "success"),
            ("Sumqayıt qalıqları", "uğursuz", "danger"),
        ]
    )


def _backups(screen: group_d.BackupScreen) -> None:
    screen.set_schedule_label("Avtomatik: hər gecə 02:00")
    screen.set_backups(list(data.BACKUPS))
    screen.set_storage(48.2, 80, count=27)


def _health(screen: group_d.HealthScreen) -> None:
    screen.set_last_check("Son yoxlama 30 saniyə əvvəl")
    screen.set_metrics(
        [
            ("Baza (DB Ping)", "11 ms", "Norma: < 50 ms", "success"),
            ("Disk (server)", "62%", "168 GB boş", "success"),
            ("NTP sapması", "+2.4 san", "Kiosk-01 saatı geridədir", "warning"),
        ]
    )
    screen.set_latencies(
        [
            ("1C-BAKI-01", "42 ms", "success"),
            ("1C-BAKI-02", "57 ms", "success"),
            ("1C-GENCE-01", "318 ms", "warning"),
            ("1C-SUMQAYIT-01", "timeout", "danger"),
        ]
    )
    screen.set_alerts(
        [
            (
                "1C-SUMQAYIT-01 serverinə 4 saatdır bağlantı yoxdur — "
                "2 mağaza sinxronizasiya olunmur.",
                "05:41",
                "danger",
            ),
            (
                "Kiosk-01 terminalının saatı 2.4 saniyə geridədir — "
                "davamiyyət vaxtlarına təsir edə bilər.",
                "09:12",
                "warning",
            ),
            (
                f"{data.SYNC_CONFLICT_OPEN_COUNT} sinxronizasiya konflikti həll "
                "gözləyir — eyni qeyd iki yerdə fərqli dəyişdirilib.",
                "09:41",
                "warning",
            ),
        ]
    )
    # G-1: xəbərdarlığın GEDƏCƏYİ yer. Maketdə keçid HƏMİŞƏ görünür — canlı
    # yolda isə `screen_data._health` flag-i yoxlayıb sayğacı `0` göndərir və
    # widget ÜMUMİYYƏTLƏ qurulmur (bax `HealthScreen.set_conflict_action`).
    screen.set_conflict_action(data.SYNC_CONFLICT_OPEN_COUNT)


def _audit(screen: group_d.AuditScreen) -> None:
    screen.set_total("18 420 yazı · dəyişdirilə bilməz")
    screen.set_entries(list(data.AUDIT_ENTRIES), result_text="142 nəticə")
    screen.set_pagination(1, 18)


def _drive_connection(screen: group_d.DriveConnectionScreen) -> None:
    screen.set_active(
        account="kompas.sube@gmail.com",
        status_text="Aktiv",
        tone="success",
        quota_text="4.20 GB / 15.00 GB istifadə olunub (28%)",
    )
    screen.set_history(
        [
            ("kompas.sube@gmail.com", "Aktiv", "12.08.2026 09:14"),
            ("kompas.kohne@gmail.com", "Arxivlənib", "02.03.2026 11:40"),
        ]
    )


def _root_control(screen: group_d.RootControlScreen) -> None:
    """Maket məzmunu — açarlar İSTEHSALATDAKI ilə eynidir.

    Əvvəl burada ayrı adlar vardı ("fines", "sales"), halbuki canlı panel
    `SystemLimitKey`/`FeatureModule` dəyərlərini işlədir. Fərqli ad məkanı
    maketdə görünməyən uyğunsuzluq yaradırdı — indi hər ikisi eyni mənbədir
    (bax `controllers/root_control.py`).
    """
    from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey  # noqa: PLC0415
    from src.presentation.controllers.root_control import (  # noqa: PLC0415
        BREAK_LIMIT_KEYS,
        MODULE_LABELS,
        limit_row,
    )

    preview_keys = (
        SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT,
        SystemLimitKey.FINE_APPEAL_WINDOW_HOURS,
        SystemLimitKey.LATE_TOLERANCE_MINUTES,
        SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES,
        SystemLimitKey.DUAL_CONTROL_THRESHOLD_MINUTES,
        SystemLimitKey.LEAVE_ALLOWANCE_SOURCE,
    )
    screen.set_limits([limit_row(key.value, DEFAULT_LIMITS[key]) for key in preview_keys])
    # «Fasilə Parametrləri» maketdə də CANLI açarlarla doldurulur (nahar.md):
    # `BREAK_LIMIT_KEYS` kontrollerdən gəlir, yəni maket öz ad məkanını
    # qurmur — modul başlığındakı uyğunsuzluq qüsuru təkrarlanmır.
    screen.set_break_limits([limit_row(key.value, DEFAULT_LIMITS[key]) for key in BREAK_LIMIT_KEYS])
    screen.set_modules(
        [
            (module.value, MODULE_LABELS[module], True, module.is_structural)
            for module in FeatureModule
        ]
    )
    screen.set_registry(
        [
            ("can_override_return_time", True),
            ("can_delete_fines", True),
            ("can_approve_roster", False),
            ("can_manage_erp_servers", False),
        ]
    )
    # facecontrol.md bənd 15 + (7, 12) — açarlar `controllers/root_control.py::
    # face_scope_rows` / `face_tolerance_row` ilə EYNİDİR (CLAUDE.md §6).
    screen.set_face_scope([dict(store) for store in data.FACE_STORE_SCOPE])
    screen.set_face_tolerance(dict(data.FACE_TOLERANCE))
    # TENANT-1 Faza 2. Maket CANLI yolun defoltunu göstərir: rəng sahəsi BOŞ,
    # ad isə nümunə. Boş rəng «defolt Amber» deməkdir və maketdə də məhz o
    # görünməlidir — burada `#F5A623` yazsaydıq, maket «rəng təyin edilib»
    # təəssüratı yaradar və Root paneli açan adam onu silməyə çalışardı.
    screen.set_branding(company_name="Yataş Group", accent_color="")


def _settings(screen: group_d.SettingsScreen) -> None:
    screen.set_security_info(
        password_age="Son dəyişiklik 41 gün əvvəl",  # noqa: S106 - göstərilən mətn
        sessions="2 cihaz — bu PC və Baş ofis PC",
    )


def _profile(screen: group_g.ProfileScreen) -> None:
    screen.set_account(
        username="r.mammadov",
        email="admin@kompas.az",
        phone="+994 50 000 00 00",
        password_note="Şifrə son dəfə 41 gün əvvəl dəyişdirilib.",  # noqa: S106
    )
    screen.set_role_info(
        [
            ("Aktiv icazə", "52 / 58"),
            ("Fərdi istisna", "2"),
            ("Təyin edilmiş mağaza", "Hamısı (21)"),
        ]
    )
    screen.set_sessions(
        [
            ("12.08 08:41", "Bu kompüter", "Aktiv sessiya"),
            ("11.08 09:02", "Baş ofis PC-02", "Bağlanıb"),
            ("08.08 17:55", "Baş ofis PC-02", "Bağlanıb"),
        ]
    )
    # #20 (kompasos11.md Faza 8) — açarlar `controllers/profile.py::
    # _performance_rows` ilə EYNİDİR (CLAUDE.md §6).
    screen.set_performance_history(list(data.PERFORMANCE_REVIEW_HISTORY))
    # facecontrol.md bənd 13 — açarlar `controllers/profile.py::
    # _face_enrollment_row` ilə EYNİDİR.
    screen.set_face_enrollment(dict(data.FACE_PROFILE_ENROLLMENT))


def _support(widget: group_e.SupportChatWidget) -> None:
    widget.add_separator("Bu gün 09:12")
    widget.add_message("Salam Rəşad. Sumqayıt serveri ilə bağlı sorğunuzu aldıq.")
    widget.add_message("Bağlantı 4 saatdır kəsilib, mağazalar sinxron olmur.", outgoing=True)
    widget.add_message("Yoxlayırıq. Diaqnostika ekranından son log-u göndərə bilərsinizmi?")
    widget.set_unread(True)


def _notifications(widget: group_g.NotificationPanel) -> None:
    widget.set_notifications(list(data.NOTIFICATIONS))


def _reports(screen: Any) -> None:
    """Bölmə 6 + kompas1.md Faza 8 — açarlar `controllers/report_export.py`
    (`_role_rows`, `_finding_rows`, `_comparison_rows`, `_correction_rows`) ilə
    HƏRFƏN EYNİDİR (CLAUDE.md §6).

    `set_correction_access(allowed=True)` maketdə QƏSDƏN AÇIQDIR: dizayn
    baxışında bölmə görünməlidir. CANLI yolda o, `can_manage_export_
    corrections` flag-inə bağlıdır (bax `ReportExportController.attach`) —
    yəni maket "hər şey görünür" halını, canlı yol isə səlahiyyəti göstərir.
    """
    screen.set_period("Avqust 2026")
    # Bölmə 6 LOCK mexanizmi — İKİ AYRI səbəb: 4 cərimənin etiraz pəncərəsi
    # hələ açıqdır, 2-si isə ARTIQ əvvəlki dövrdə tutulub (Faza 7, üst-üstə
    # düşən aralıq). Maket hər iki cümləni göstərir ki, dizayn baxışında
    # ikisinin bir yerdə necə oxunduğu görünsün.
    screen.set_lock_summary(
        4,
        already_exported=data.EXPORT_ALREADY_EXPORTED_COUNT,
        overlap_notice=data.EXPORT_OVERLAP_NOTICE,
    )

    # `[Tam Ay]` DEFOLTDUR — canlı yolda `ReportExportController.attach()`
    # EYNİ setter-i eyni arqumentlə çağırır (CLAUDE.md §6).
    screen.set_range_selection(custom=False)
    screen.set_range_message("")
    screen.set_role_options(list(data.EXPORT_ROLE_OPTIONS), selected="")
    screen.set_correction_access(allowed=True)
    screen.set_validation_findings(list(data.EXPORT_VALIDATION_FINDINGS))
    screen.set_period_comparison(
        list(data.EXPORT_PERIOD_COMPARISON), caption=data.EXPORT_COMPARISON_CAPTION
    )
    screen.set_corrections(list(data.EXPORT_CORRECTIONS))


def _work_modes(screen: Any) -> None:
    screen.set_entries(list(data.WORK_MODES))


def _fine_types(screen: Any) -> None:
    screen.set_entries(list(data.FINE_TYPE_ROWS))


def _leave_types(screen: Any) -> None:
    screen.set_entries(list(data.LEAVE_TYPE_ROWS))


def _infrastructure(screen: Any) -> None:
    from src.domain.value_objects.infrastructure import DatabaseTarget  # noqa: PLC0415

    screen.set_active_target(DatabaseTarget.CLOUD)
    screen.set_warnings(list(data.DB_SWITCH_WARNINGS))
    screen.set_history(list(data.DB_SWITCH_HISTORY))


def _plugins(screen: Any) -> None:
    screen.set_plugins(list(data.PLUGINS))


def _exceptions(screen: Any) -> None:
    screen.set_exceptions(list(data.EXCEPTIONS))


def _announcements(screen: Any) -> None:
    """#19 (kompasos11.md Faza 8) — açarlar `controllers/announcements.py::
    _to_admin_row` ilə EYNİDİR (CLAUDE.md §6)."""
    screen.set_announcements(list(data.ANNOUNCEMENTS))


def _performance_reviews(screen: Any) -> None:
    """#20 (kompasos11.md Faza 8) — açarlar `controllers/performance_review.py`
    ilə EYNİDİR (CLAUDE.md §6)."""
    screen.set_employees(list(data.EMPLOYEE_ID_NAMES))
    screen.set_kpi_catalog(list(data.PERFORMANCE_REVIEW_KPIS))
    screen.set_period("2026-Q3")
    screen.set_history(list(data.PERFORMANCE_REVIEW_HISTORY))


def _support_inbox(screen: Any) -> None:
    """CHAT-1 dəstək qutuları — açarlar `controllers/support_inbox.py::_row`
    və `_detail` ilə EYNİDİR (CLAUDE.md §6).

    STATUS DƏYƏRLƏRİ `SupportTicketStatus`-dan GƏLİR, maketdə uydurulmur:
    ekran onları `parse()` ilə oxuyur və yazı səhvi sükutla `OPEN`-a
    düşərdi — yəni maket bütün söhbətləri «Açıq» göstərər, canlı yol isə
    dörd fərqli status göstərərdi (eyni qərar `_fine_review`-də).

    İKİ AÇAR, BİR FUNKSİYA: bölmələr eyni sinifdəndir, fərq yalnız ekranın
    öz `channel` sahəsindədir — maket də həmin sahəyə baxır və Telegram
    göstəricisini yalnız texniki bölmədə çəkir.
    """
    from src.domain.value_objects.support import SupportTicketStatus  # noqa: PLC0415

    rows = [
        {
            "ticket_id": "11111111-1111-1111-1111-111111111111",
            "sender_name": "Murad Bayramov",
            "sender_position": "Mağaza Meneceri",
            "store_name": "Yataş Babək",
            "preview": "Kiosk PC açılmır, PIN ekranı gəlmir.",
            "time": "18:42",
            "unread": True,
            "status": SupportTicketStatus.OPEN.value,
            "is_urgent": True,
        },
        {
            "ticket_id": "22222222-2222-2222-2222-222222222222",
            "sender_name": "Aysel Quliyeva",
            "sender_position": "Satıcı",
            "store_name": "Yataş Mərkəzi",
            "preview": "Ekranın şəklini göndərdim.",
            "time": "16:05",
            "unread": False,
            "status": SupportTicketStatus.WAITING.value,
            "is_urgent": False,
        },
    ]
    screen.set_stores([("s1", "Yataş Babək"), ("s2", "Yataş Mərkəzi")])
    screen.set_positions([("SELLER", "Satıcı"), ("STORE_MANAGER", "Mağaza Meneceri")])
    screen.set_status_counts(
        {
            SupportTicketStatus.OPEN: 1,
            SupportTicketStatus.WAITING: 1,
            SupportTicketStatus.RESOLVED: 0,
            SupportTicketStatus.CLOSED: 7,
        }
    )
    screen.set_threads(rows)
    screen.set_thread(
        {
            "ticket_id": rows[0]["ticket_id"],
            "subject": "Kiosk PC açılmır",
            "sender_name": rows[0]["sender_name"],
            "sender_position": rows[0]["sender_position"],
            "store_name": rows[0]["store_name"],
            "status": SupportTicketStatus.OPEN.value,
            "is_urgent": True,
            "messages": [
                {
                    "body": "Kiosk PC açılmır, PIN ekranı gəlmir.",
                    "outgoing": False,
                    "telegram_sent_at": "18:42",
                    "from_telegram": False,
                    "attachment_ref": "",
                    "attachment_name": "",
                },
                {
                    "body": "Kabeli çıxarıb yenidən taxın, nəticəni yazın.",
                    "outgoing": True,
                    "telegram_sent_at": "18:47",
                    "from_telegram": True,
                    "attachment_ref": "",
                    "attachment_name": "",
                },
            ],
        }
    )


def _annual_leave(screen: Any) -> None:
    """#28 (kompas1.md Faza 4) — açarlar `controllers/annual_leave.py::
    _to_inbox_row` ilə EYNİDİR (CLAUDE.md §6)."""
    screen.set_requests(list(data.ANNUAL_LEAVE_PENDING))


def _transfer_requests(screen: Any) -> None:
    """`v2backlog.md` Faza 3.3 — açarlar `controllers/transfer_requests.py::
    _to_inbox_row` ilə EYNİDİR (CLAUDE.md §6)."""
    screen.set_requests(list(data.TRANSFER_REQUESTS))


def _break_glass(screen: Any) -> None:
    """`v2backlog.md` Faza 5.4 — açarlar `controllers/break_glass.py`
    köməkçiləri ilə EYNİDİR (CLAUDE.md §6).

    MAKET «ROOT GÖRÜNÜŞÜ»DÜR: bütün bölmələr görünür. Görünürlük bayraqları
    canlı yolda use case-in istisnalarından gəlir, maketdə isə TAM DƏST
    göstərilir ki, dörd bölmənin də dizaynı bir yerdə yoxlanılsın."""
    screen.set_my_status(True, dict(data.BREAK_GLASS_MY_STATUS))
    screen.set_request_form_visible(True)
    screen.set_pending_visible(True)
    screen.set_pending([dict(row) for row in data.BREAK_GLASS_PENDING])
    screen.set_active_visible(True)
    screen.set_active([dict(row) for row in data.BREAK_GLASS_ACTIVE])
    screen.set_registry(
        [dict(row) for row in data.BREAK_GLASS_TRUSTEES],
        can_manage=True,
        employees=[("e1", "Səbinə Hüseynova"), ("e2", "Elvin Məmmədov")],
    )


def _checklist_templates(screen: Any) -> None:
    """`v2backlog.md` Faza 3.4 — ekranın DEFOLT sekması (OFFBOARDING) doldurulur.

    FIELD_REPORT sekması maketdə BOŞ-VƏZİYYƏT göstərir (`ChecklistTemplateScreen.
    _set_owner_type`-in özü qurur) — canlı yolda da EYNİ, açar axtarılana qədər
    heç bir sorğu getmir (bax `controllers/checklist_templates.py` başlığı).
    """
    screen.set_entries(list(data.CHECKLIST_TEMPLATES_OFFBOARDING))


def _fine_review(screen: Any) -> None:
    """Aylıq Cərimə İcmalı (miqrasiya 003) — maket və canlı yol EYNİ tiplərlə.

    Sətirlər `FineReviewRow`/`FineReviewGroup` `NamedTuple`-larına çevrilir,
    yəni `controllers/fine_review.py::_group_rows`-un qurduğu ilə EYNİ
    strukturdur — uyğunsuzluğu tip yoxlayıcısı da tutur (CLAUDE.md §6).

    Qərar ETİKETLƏRİ maketdə UYDURULMUR: `decision_options()` canlı yolun
    işlətdiyi EYNİ funksiyadır və `ReviewDecision` üzvlərini gətirir
    (`_sync_conflicts` ilə eyni qərar).
    """
    from src.presentation.controllers.fine_review import (  # noqa: PLC0415
        decision_options,
    )
    from src.presentation.screens.fine_review import (  # noqa: PLC0415
        FineReviewGroup,
        FineReviewRow,
    )

    screen.set_decision_options(decision_options())
    screen.set_periods(
        [dict(period) for period in data.FINE_REVIEW_PERIODS],
        selected=data.FINE_REVIEW_SELECTED_PERIOD,
    )
    screen.set_groups(
        [
            FineReviewGroup(
                key=key,
                store=store,
                count_text=count_text,
                total_text=total_text,
                # Sahələr AÇIQ adlarla verilir (`_dashboard`-dakı
                # `RankingEntry` ilə eyni qərar): sıra dəyişsə tip
                # yoxlayıcısı deyil, insan gözü qərarları qarışdırardı.
                rows=tuple(
                    FineReviewRow(
                        fine_id=fine_id,
                        employee=employee,
                        fine_type=fine_type,
                        amount_text=amount_text,
                        date_text=date_text,
                        operator=operator,
                        has_evidence=has_evidence,
                    )
                    for (
                        fine_id,
                        employee,
                        fine_type,
                        amount_text,
                        date_text,
                        operator,
                        has_evidence,
                    ) in rows
                ),
            )
            for key, store, count_text, total_text, rows in data.FINE_REVIEW_GROUPS
        ],
        summary_text=data.FINE_REVIEW_SUMMARY,
    )
    # Bir sətir "Sil" vəziyyətində göstərilir — bax `FINE_REVIEW_DISCARDED`.
    discarded_id, discard_reason = data.FINE_REVIEW_DISCARDED
    screen.set_decision(
        discarded_id,
        decision=decision_options()[-1]["code"],
        reason=discard_reason,
    )


def _attrition_risk(screen: Any) -> None:
    """#21 (kompasos11.md Faza 9) — açarlar `controllers/attrition_risk.py::
    _to_row` ilə EYNİDİR (CLAUDE.md §6).

    Kampaniya bölməsi də maketdə GÖRÜNÜR (Faza 6.4) — canlı yolda flag-siz
    istifadəçidə HEÇ render olunmur, maket isə Root görünüşünü təkrarlayır."""
    screen.set_scores(list(data.ATTRITION_RISK_SCORES))
    screen.set_campaigns_visible(True)
    screen.set_campaigns([dict(row) for row in data.CAMPAIGN_PERIOD_ROWS])
    screen.set_campaign_message("")


def _sync_conflicts(screen: Any) -> None:
    """G-1 (bölmə 5) — açarlar `controllers/sync_conflicts.py`-dakı
    `_to_list_row` / `_to_detail` / `_to_field_rows` ilə EYNİDİR (CLAUDE.md §6).

    Qərar ETİKETLƏRİ maketdə də UYDURULMUR: `resolution_options()` canlı yolun
    işlətdiyi EYNİ funksiyadır və `Resolution.label_az`-ı gətirir. Maket öz
    mətnini yazsaydı, enum dəyişəndə iki yol sükutla ayrılardı — `menu.py`
    başlığındakı tarixi qüsurun eyni forması.
    """
    from src.application.use_cases.sync_conflicts import (  # noqa: PLC0415
        MIN_NOTE_LENGTH,
    )
    from src.presentation.controllers.sync_conflicts import (  # noqa: PLC0415
        resolution_options,
    )

    screen.set_resolutions(resolution_options())
    screen.set_note_min_length(MIN_NOTE_LENGTH)
    screen.set_conflicts([dict(row) for row in data.SYNC_CONFLICTS])
    screen.set_comparison(
        dict(data.SYNC_CONFLICTS[0]),
        [dict(row) for row in data.SYNC_CONFLICT_FIELDS],
    )


def _field_report(
    screen: Any,
    *,
    templates: list[dict[str, str]],
    categories: list[dict[str, str]],
    reports: list[dict[str, str]],
) -> None:
    """#26+#27 (kompas1.md Faza 3) — açarlar `controllers/field_reports.py`-dakı
    `_template_row` / `_category_row` / `_report_row` ilə EYNİDİR (CLAUDE.md §6).

    İKİ AÇAR, TƏK DOLDURUCU: forma sinfi eynidir, fərq yalnız KATALOQ
    məzmunundadır — maket bunu iki funksiya ilə təkrarlasaydı, sabahkı üçüncü
    şablon üçüncü nüsxə tələb edərdi.
    """
    screen.set_templates(templates)
    screen.set_categories(categories)
    screen.set_stores(list(data.FIELD_REPORT_STORES))
    screen.set_detail_min_length(data.FIELD_REPORT_MIN_DETAIL)
    screen.set_photo_limit(data.FIELD_REPORT_MAX_PHOTOS)
    screen.set_open_reports(reports)


def _store_audit(screen: Any) -> None:
    _field_report(
        screen,
        templates=list(data.FIELD_REPORT_AUDIT_TEMPLATES),
        categories=list(data.FIELD_REPORT_AUDIT_CATEGORIES),
        reports=list(data.FIELD_REPORT_OPEN_AUDITS),
    )


def _incident_report(screen: Any) -> None:
    _field_report(
        screen,
        templates=list(data.FIELD_REPORT_INCIDENT_TEMPLATES),
        categories=list(data.FIELD_REPORT_INCIDENT_CATEGORIES),
        reports=list(data.FIELD_REPORT_OPEN_INCIDENTS),
    )


def _bulk_operations(screen: Any) -> None:
    """#29 (kompas1.md Faza 5) — açarlar `controllers/bulk_operations.py`
    ilə EYNİDİR (CLAUDE.md §6)."""
    screen.set_preview(
        total_rows=data.BULK_IMPORT_PREVIEW_TOTAL_ROWS,
        valid_count=data.BULK_IMPORT_PREVIEW_VALID_COUNT,
        error_count=data.BULK_IMPORT_PREVIEW_ERROR_COUNT,
        errors=list(data.BULK_IMPORT_PREVIEW_ERRORS),
        truncated_extra=data.BULK_IMPORT_PREVIEW_TRUNCATED_EXTRA,
    )
    screen.set_templates(list(data.STORE_TEMPLATES))


def _face_enrollment(screen: Any) -> None:
    """facecontrol.md bənd 1, 2, 11 — açarlar `controllers/face_control.py`-dakı
    `_enrollment_rows` / `_result_row` / `_frame_row` ilə EYNİDİR (CLAUDE.md §6).

    KAMERA MAKETDƏ «HAZIR»DIR: `--preview` rejimi dizayn yoxlaması üçündür və
    orada fiziki kamera olmaya bilər. Nasazlıq halının ÖZÜ kontroller testində
    yoxlanılır (`CAMERA_UNAVAILABLE`), maketdə isə düymələr sönülü qalsaydı
    ekranın əsas axını heç vaxt görünməzdi.
    """
    screen.set_employees([dict(row) for row in data.FACE_ENROLLMENT_EMPLOYEES])
    screen.set_camera(dict(data.FACE_ENROLLMENT_CAMERA))
    screen.set_result(dict(data.FACE_ENROLLMENT_RESULT))
    screen.set_frames([dict(row) for row in data.FACE_ENROLLMENT_FRAMES])


def _face_exemptions(screen: Any) -> None:
    """facecontrol.md bənd 14 — açarlar `controllers/face_control.py::
    `_exemption_row` / `_exemption_limits` ilə EYNİDİR (CLAUDE.md §6)."""
    screen.set_limits(dict(data.FACE_EXEMPTION_LIMITS))
    screen.set_employees([dict(row) for row in data.FACE_EXEMPTION_EMPLOYEES])
    screen.set_exemptions([dict(row) for row in data.FACE_EXEMPTIONS])


def _dashboard_builder(screen: Any) -> None:
    # `placements`/`columns` (audit G-5) CANLI yolla EYNİ arqumentlərdir
    # (`controllers/dashboard_builder.py`) — maket öz ad məkanını qurmur.
    screen.set_widgets(
        dict(data.DASHBOARD_WIDGETS),
        order=list(data.DASHBOARD_ORDER),
        visible=set(data.DASHBOARD_VISIBLE),
        placements=dict(data.DASHBOARD_PLACEMENTS),
        columns=data.DASHBOARD_GRID_COLUMNS,
    )


#: Ekran açarı → doldurucu.
#:
#: Dəyərlərin tipi `Callable[[Any], None]`-dur, çünki hər doldurucu FƏRQLİ
#: konkret ekran tipi gözləyir. Uyğunluq `populate()`-un çağırış yerində
#: təmin olunur: açar həmin ekranı quran fabrikanın açarı ilə eynidir.
_POPULATORS: dict[str, Callable[[Any], None]] = {
    "dashboard": _dashboard,
    "internal_requests": _support_inbox,
    "technical_support": _support_inbox,
    "live_queue": _live_queue,
    "daily_roster": _daily_roster,
    "shift_planning": _shift_planning,
    "shift_swaps": _shift_swaps,
    "fines": _fines,
    "fine_appeals": _fine_appeals,
    "tasks": _tasks,
    "sales_points": _sales_points,
    "unassigned_sales": _unassigned_sales,
    "users": _users,
    "permissions": _permissions,
    "erp_servers": _erp_servers,
    "backups": _backups,
    "health": _health,
    "audit": _audit,
    "drive_connection": _drive_connection,
    "root_control": _root_control,
    "settings": _settings,
    "profile": _profile,
    "support": _support,
    "notifications": _notifications,
    # Qrup H və I ekranları — əvvəllər önizləmə məzmunu YOX idi, ona görə
    # boş render olunur və vizual yoxlamadan kənarda qalırdılar.
    "reports": _reports,
    "work_modes": _work_modes,
    "fine_types": _fine_types,
    "leave_types": _leave_types,
    "infrastructure": _infrastructure,
    "plugins": _plugins,
    "dashboard_builder": _dashboard_builder,
    "exceptions": _exceptions,
    "store_audit": _store_audit,
    "incident_report": _incident_report,
    "announcements": _announcements,
    "performance_reviews": _performance_reviews,
    "attrition_risk": _attrition_risk,
    "sync_conflicts": _sync_conflicts,
    "annual_leave": _annual_leave,
    "transfer_requests": _transfer_requests,
    "break_glass": _break_glass,
    "checklist_templates": _checklist_templates,
    "fine_review": _fine_review,
    "bulk_operations": _bulk_operations,
    # Face Control (facecontrol.md Faza 4) — hər ikisi ÖZ kontrollerinə
    # bağlıdır (həm oxuyur, həm yazır), maket isə eyni setter-ləri çağırır.
    "face_enrollment": _face_enrollment,
    "face_exemptions": _face_exemptions,
}


def populate(key: str, screen: QWidget) -> None:
    """Ekranı maketdəki nümunə məzmunla doldurur.

    Açar tanınmırsa heç nə edilmir — yeni ekranın önizləmə məzmunu olmaya
    bilər və bu, xəta sayılmır.
    """
    populator = _POPULATORS.get(key)
    if populator is not None:
        populator(screen)


def unread_notification_count() -> int:
    """Header-dəki nişan üçün oxunmamış bildiriş sayı."""
    return sum(1 for item in data.NOTIFICATIONS if item.get("unread") == "1")


__all__ = ["populate", "unread_notification_count"]
