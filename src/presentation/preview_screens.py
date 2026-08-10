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
    screen.set_fines_by_branch(list(data.FINES_BY_BRANCH), period="Avqust 2026")
    screen.set_leave_usage(128, 200)
    screen.set_leaders(list(data.LEADERS))
    screen.set_server_health(list(data.SERVER_HEALTH))


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
    screen.set_matrix(days, rows)
    screen.set_summary(
        [
            ("Planlaşdırılmış saat", "1 176"),
            ("Açıq növbə", "4"),
            ("Məzuniyyətdə", "1"),
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
            },
            {
                "id": "t5",
                "title": "Qiymət etiketlərinin yenilənməsi",
                "assignee": "K. Vəliyev",
                "due": "Dünən",
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
                "date": "12.08",
                "reason": "Divan satışı — Enza kolleksiyası",
                "status": "Təsdiqli",
                "points": "+45",
            },
            {
                "date": "11.08",
                "reason": "Tapşırıq: səhər açılış yoxlaması",
                "status": "Təsdiqli",
                "points": "+20",
            },
            {
                "date": "10.08",
                "reason": "Yataq dəsti satışı — çek 4471",
                "status": "Gözləyir",
                "points": "+60",
            },
            {
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
            {"name": "Əlavə istirahət günü", "cost": "2000"},
            {"name": "100 ₼ hədiyyə kartı", "cost": "1200"},
            {"name": "Mağaza endirim kuponu", "cost": "600"},
        ],
        balance=1240,
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
        ]
    )


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
            ("Fərdi override", "2"),
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


def _support(widget: group_e.SupportChatWidget) -> None:
    widget.add_separator("Bu gün 09:12")
    widget.add_message("Salam Rəşad. Sumqayıt serveri ilə bağlı sorğunuzu aldıq.")
    widget.add_message("Bağlantı 4 saatdır kəsilib, mağazalar sinxron olmur.", outgoing=True)
    widget.add_message("Yoxlayırıq. Diaqnostika ekranından son log-u göndərə bilərsinizmi?")
    widget.set_unread(True)


def _notifications(widget: group_g.NotificationPanel) -> None:
    widget.set_notifications(list(data.NOTIFICATIONS))


def _reports(screen: Any) -> None:
    screen.set_period("Avqust 2026")
    # Etiraz pəncərəsi hələ açıq olan cərimələr — bölmə 6 LOCK mexanizmi.
    screen.set_lock_summary(4)


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


def _dashboard_builder(screen: Any) -> None:
    screen.set_widgets(
        dict(data.DASHBOARD_WIDGETS),
        order=list(data.DASHBOARD_ORDER),
        visible=set(data.DASHBOARD_VISIBLE),
    )


#: Ekran açarı → doldurucu.
#:
#: Dəyərlərin tipi `Callable[[Any], None]`-dur, çünki hər doldurucu FƏRQLİ
#: konkret ekran tipi gözləyir. Uyğunluq `populate()`-un çağırış yerində
#: təmin olunur: açar həmin ekranı quran fabrikanın açarı ilə eynidir.
_POPULATORS: dict[str, Callable[[Any], None]] = {
    "dashboard": _dashboard,
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
