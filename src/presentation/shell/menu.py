"""Standart naviqasiya maddələri — Faza 4.2.

Burada tətbiqin BÜTÜN menyu maddələri bir yerdə qeydiyyatdan keçir: açar,
Azərbaycanca ad, tələb olunan icazə flag-i, bağlı olduğu Feature Toggle və
ikon.

──────────────────────────────────────────────────────────────────────────────
FLAG ADLARI HARDAN GƏLİR
──────────────────────────────────────────────────────────────────────────────
Hər `required_flag` `database/schema.sql`-dakı icazə reyestrində MÖVCUD
olmalıdır — orada olmayan ad heç kimdə aktiv olmayacağı üçün maddə HƏMİŞƏ
gizli qalar və səbəbi görünməz olardı (menyu boş, xəta yox). `test_menu.py`
bu uyğunluğu yoxlayır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ "DASHBOARD" VƏ "AYARLAR" FLAG-SİZDİR
──────────────────────────────────────────────────────────────────────────────
`required_flag=None` — hər autentifikasiya olunmuş istifadəçi görür. Bu, iki
maddə üçün QƏSDƏNDİR: naviqasiyada heç nə görünməyən istifadəçi tətbiqi
"sınmış" hesab edərdi. Dashboard hər kəsə öz səlahiyyəti çərçivəsində boş və
ya məhdud görünə bilər, Ayarlar isə yalnız şəxsi tənzimləmələrdir (tema,
bildiriş) — orada başqasının məlumatı yoxdur.

Diqqət: menyunun görünməsi ƏMƏLİYYAT İCAZƏSİ DEYİL. Ekranı açan hər əməliyyat
öz yoxlamasını ayrıca aparır (bax `navigation.NavigationRegistry.is_visible`
şərhi).
"""

from __future__ import annotations

from typing import Final

from src.presentation.navigation import MenuEntry, NavigationRegistry

#: Feature Toggle açarları (ROOT Control Center-dən idarə olunur).
MODULE_ATTENDANCE: Final = "attendance"
MODULE_LEAVE: Final = "leave"
MODULE_FINES: Final = "fines"
MODULE_SCHEDULING: Final = "scheduling"
MODULE_TASKS: Final = "tasks"
MODULE_SALES: Final = "sales"
MODULE_ERP: Final = "erp"
MODULE_BACKUP: Final = "backup"
MODULE_DIAGNOSTICS: Final = "diagnostics"
MODULE_AUDIT: Final = "audit"


#: Maddələr — `order` maketdəki sol panel sırasını təkrarlayır.
DEFAULT_ENTRIES: Final[tuple[MenuEntry, ...]] = (
    MenuEntry(
        key="dashboard",
        title_az="Dashboard",
        required_flag=None,
        order=10,
        icon="dashboard",
    ),
    MenuEntry(
        key="live_queue",
        title_az="Canlı Növbə",
        required_flag="can_verify_returns",
        feature_module=MODULE_LEAVE,
        order=20,
        icon="queue",
    ),
    MenuEntry(
        key="daily_roster",
        title_az="Gündəlik Tabel",
        required_flag="can_fill_daily_attendance",
        feature_module=MODULE_ATTENDANCE,
        order=30,
        icon="roster",
    ),
    MenuEntry(
        key="shift_planning",
        title_az="Növbə Planlama",
        required_flag="can_manage_shifts",
        feature_module=MODULE_SCHEDULING,
        order=40,
        icon="calendar",
    ),
    MenuEntry(
        key="shift_swaps",
        title_az="Növbə Dəyişmə",
        required_flag="can_approve_shift_swap",
        feature_module=MODULE_SCHEDULING,
        order=50,
        icon="refresh",
    ),
    MenuEntry(
        key="fines",
        title_az="Cərimələr",
        required_flag="can_issue_fines",
        feature_module=MODULE_FINES,
        order=60,
        icon="fine",
    ),
    MenuEntry(
        key="fine_appeals",
        title_az="Cərimə Etirazları",
        required_flag="can_approve_leave_appeal",
        feature_module=MODULE_FINES,
        order=70,
        icon="shield",
    ),
    MenuEntry(
        key="tasks",
        title_az="Tapşırıqlar",
        required_flag="can_assign_tasks",
        feature_module=MODULE_TASKS,
        order=80,
        icon="checklist",
    ),
    MenuEntry(
        key="sales_points",
        title_az="Satış Xalları",
        required_flag="can_manage_sales_points",
        feature_module=MODULE_SALES,
        order=90,
        icon="star",
    ),
    MenuEntry(
        key="unassigned_sales",
        title_az="Şübhəli Satışlar",
        required_flag="can_manage_sales_points",
        feature_module=MODULE_SALES,
        order=100,
        icon="tag",
    ),
    MenuEntry(
        key="users",
        title_az="İstifadəçilər",
        required_flag="can_manage_employees",
        order=110,
        icon="users",
    ),
    MenuEntry(
        key="permissions",
        title_az="İcazə Matrisi",
        required_flag="can_manage_permissions",
        order=120,
        icon="lock",
    ),
    MenuEntry(
        key="erp_servers",
        title_az="ERP / 1C Serverləri",
        required_flag="can_manage_erp_servers",
        feature_module=MODULE_ERP,
        order=130,
        icon="server",
    ),
    MenuEntry(
        key="backups",
        title_az="Backup və Bərpa",
        required_flag="can_manage_backups",
        feature_module=MODULE_BACKUP,
        order=140,
        icon="database",
    ),
    MenuEntry(
        key="health",
        title_az="Sistem Sağlamlığı",
        required_flag="can_view_system_health",
        feature_module=MODULE_DIAGNOSTICS,
        order=150,
        icon="activity",
    ),
    MenuEntry(
        key="audit",
        title_az="Audit Jurnalı",
        required_flag="can_view_audit_logs",
        feature_module=MODULE_AUDIT,
        order=160,
        icon="file",
    ),
    MenuEntry(
        key="root_control",
        title_az="ROOT Mərkəzi",
        required_flag="can_manage_system_limits",
        order=170,
        icon="shield",
    ),
    MenuEntry(
        key="settings",
        title_az="Ayarlar",
        required_flag=None,
        order=200,
        icon="settings",
    ),
    MenuEntry(
        key="profile",
        title_az="Profil",
        required_flag=None,
        order=210,
        icon="user",
    ),
)


def build_default_registry() -> NavigationRegistry:
    """Standart maddələrlə doldurulmuş yeni reyestr qaytarır.

    Hər çağırışda TƏZƏ obyekt yaradılır — qlobal reyestr paylaşılsaydı, bir
    testin qeydiyyatı digərinə sızardı və `register()` təkrar açar xətası
    atardı.
    """
    registry = NavigationRegistry()
    registry.register_all(list(DEFAULT_ENTRIES))
    return registry


__all__ = [
    "DEFAULT_ENTRIES",
    "MODULE_ATTENDANCE",
    "MODULE_AUDIT",
    "MODULE_BACKUP",
    "MODULE_DIAGNOSTICS",
    "MODULE_ERP",
    "MODULE_FINES",
    "MODULE_LEAVE",
    "MODULE_SALES",
    "MODULE_SCHEDULING",
    "MODULE_TASKS",
    "build_default_registry",
]
