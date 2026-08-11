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
NİYƏ «İDARƏ PANELİ» VƏ «AYARLAR» FLAG-SİZDİR
──────────────────────────────────────────────────────────────────────────────
`required_flag=None` — hər autentifikasiya olunmuş istifadəçi görür. Bu, iki
maddə üçün QƏSDƏNDİR: naviqasiyada heç nə görünməyən istifadəçi tətbiqi
"sınmış" hesab edərdi. İdarə Paneli hər kəsə öz səlahiyyəti çərçivəsində boş və
ya məhdud görünə bilər, Ayarlar isə yalnız şəxsi tənzimləmələrdir (tema,
bildiriş) — orada başqasının məlumatı yoxdur.

Diqqət: menyunun görünməsi ƏMƏLİYYAT İCAZƏSİ DEYİL. Ekranı açan hər əməliyyat
öz yoxlamasını ayrıca aparır (bax `navigation.NavigationRegistry.is_visible`
şərhi).
"""

from __future__ import annotations

from typing import Final

from src.domain.policies import FeatureModule
from src.presentation.navigation import MenuEntry, NavigationRegistry

# ──────────────────────────────────────────────────────────────────────────────
# FEATURE TOGGLE AÇARLARI HARDAN GƏLİR
# ──────────────────────────────────────────────────────────────────────────────
# Dəyərlər `FeatureModule` enum-undan GÖTÜRÜLÜR, əl ilə YAZILMIR. Əvvəllər
# burada ayrıca ad məkanı vardı (`"fines"`, `"tasks"`, `"sales"`), halbuki
# `feature_toggles` cədvəli və `AdminShell`-ə ötürülən `enabled_modules`
# dəsti `FeatureModule` dəyərlərini (`"FINE_MODULE"`, ...) saxlayır.
#
# Nəticədə `entry.feature_module not in modules` şərti HƏMİŞƏ doğru olurdu:
# Root modulu söndürsə belə menyu maddəsi görünməyə davam edirdi, yəni
# bölmə 3-dəki DYNAMIC UI INTEGRATION qaydası sükutla işləmirdi. İndi tək
# mənbə var; `test_menu_registry.py` uyğunluğu qoruyur.
MODULE_CAMERA: Final = FeatureModule.CAMERA_VERIFICATION.value
MODULE_SHIFT_SWAP: Final = FeatureModule.SHIFT_SWAP.value
MODULE_FINES: Final = FeatureModule.FINE_MODULE.value
MODULE_TASKS: Final = FeatureModule.TASK_ENGINE.value
MODULE_SALES: Final = FeatureModule.SALES_POINTS.value
MODULE_DASHBOARD_BUILDER: Final = FeatureModule.DASHBOARD_BUILDER.value

# NİYƏ BƏZİ MADDƏLƏR TOGGLE-SIZDIR (`feature_module=None`)
# ──────────────────────────────────────────────────────────────────────────────
# Bölmə 3 Feature Toggle-ı **İŞ-PROSESİ modulları** üçün təyin edir (Kamera
# Təsdiqi, Shift Swap, Cərimə Modulu, Dual-Control, ...). ERP paneli, backup,
# sistem sağlamlığı, audit jurnalı və kataloq ekranları iş prosesi DEYİL —
# onlar infrastruktur/konfiqurasiya səthidir və `feature_toggles` cədvəlində
# sətirləri yoxdur. Onlara uydurma açar vermək iki nəticə verərdi: ya maddə
# həmişə gizli qalardı (açar dəstdə yoxdur), ya da Root paneldə mövcud
# olmayan modul görünərdi. Hər ikisi səhvdir — ona görə qapı yalnız
# `required_flag`-dədir.


#: Maddələr — `order` maketdəki sol panel sırasını təkrarlayır.
DEFAULT_ENTRIES: Final[tuple[MenuEntry, ...]] = (
    MenuEntry(
        key="dashboard",
        title_az="İdarə Paneli",
        required_flag=None,
        order=10,
        icon="dashboard",
    ),
    MenuEntry(
        key="live_queue",
        title_az="Canlı Növbə",
        required_flag="can_verify_returns",
        feature_module=MODULE_CAMERA,
        order=20,
        icon="queue",
    ),
    MenuEntry(
        key="daily_roster",
        title_az="Gündəlik Tabel",
        required_flag="can_fill_daily_attendance",
        feature_module=MODULE_CAMERA,
        order=30,
        icon="roster",
    ),
    MenuEntry(
        key="shift_planning",
        title_az="Növbə Planlama",
        required_flag="can_manage_shifts",
        order=40,
        icon="calendar",
    ),
    MenuEntry(
        key="shift_swaps",
        title_az="Növbə Dəyişmə",
        required_flag="can_approve_shift_swap",
        feature_module=MODULE_SHIFT_SWAP,
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
        key="reports",
        title_az="Hesabatlar",
        required_flag="can_export_reports",
        order=105,
        icon="download",
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
        # `can_manage_permissions` DEYİL — o, YALNIZ `Root`-a hardlock-dur
        # (bölmə 3) və yeni FLAG YARATMAQ üçündür, Permission Registry-də
        # yaşayır. Matris ekranı isə mövcud flag-ləri istifadəçilərə paylayır;
        # bölmə 3 açıq deyir ki, `Admin` onu `can_control_user_permissions`
        # çərçivəsində GÖRÜR. Əvvəlki qapı ilə nə `Admin`, nə də `CEO` ekranı
        # heç vaxt görə bilmirdi — səlahiyyətin həvalə edilməsi mümkünsüz idi.
        required_flag="can_control_user_permissions",
        order=120,
        icon="lock",
    ),
    MenuEntry(
        key="erp_servers",
        title_az="ERP / 1C Serverləri",
        required_flag="can_manage_erp_servers",
        order=130,
        icon="server",
    ),
    MenuEntry(
        key="backups",
        title_az="Ehtiyat Nüsxə və Bərpa",
        required_flag="can_manage_backups",
        order=140,
        icon="database",
    ),
    MenuEntry(
        key="health",
        title_az="Sistem Sağlamlığı",
        required_flag="can_view_system_health",
        order=150,
        icon="activity",
    ),
    MenuEntry(
        key="audit",
        title_az="Audit Jurnalı",
        required_flag="can_view_audit_logs",
        order=160,
        icon="file",
    ),
    MenuEntry(
        key="drive_connection",
        title_az="Drive Bağlantısı",
        # Miqrasiya 002: cərimə sübut şəkilləri Supabase Storage-da deyil,
        # müştərinin ÖZ Google Drive hesabındadır — hesabı qoşmaq ayrıca
        # səlahiyyətdir və defolt yalnız ROOT/CEO-dadır.
        required_flag="can_manage_drive_connection",
        order=165,
        icon="image",
    ),
    MenuEntry(
        key="root_control",
        title_az="ROOT İdarə Mərkəzi",
        required_flag="can_manage_system_limits",
        order=170,
        icon="shield",
    ),
    # --- Kataloqlar (bölmə 4) ------------------------------------------------
    # Üçü ardıcıl yerləşir və hamısı 180-lərdədir: onlar konfiqurasiya
    # ekranlarıdır, gündəlik iş axını deyil — sol panelin aşağı hissəsində
    # qruplaşdırılması istifadəçinin gündəlik gözü ilə uyğun gəlir.
    MenuEntry(
        key="work_modes",
        title_az="İş Rejimləri",
        required_flag="can_manage_work_modes",
        order=180,
        icon="clock",
    ),
    MenuEntry(
        key="fine_types",
        title_az="Cərimə Növləri",
        required_flag="can_manage_fine_types",
        feature_module=MODULE_FINES,
        order=182,
        icon="tag",
    ),
    MenuEntry(
        key="leave_types",
        title_az="İcazə Növləri",
        required_flag="can_manage_leave_types",
        feature_module=MODULE_CAMERA,
        order=184,
        icon="checklist",
    ),
    MenuEntry(
        key="infrastructure",
        title_az="İnfrastruktur",
        required_flag="can_switch_db",
        order=172,
        icon="database",
    ),
    MenuEntry(
        key="plugins",
        title_az="Plugin-lər",
        required_flag="can_manage_plugins",
        order=174,
        icon="grid",
    ),
    MenuEntry(
        key="dashboard_builder",
        title_az="Panel Qurucusu",
        # Bölmə 6: "Yalnız bu modula icazəsi olan rollara görünür".
        # Bayraqsız qaldıqda maddə HƏR istifadəçiyə render olunurdu və bu,
        # "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipini birbaşa pozurdu.
        required_flag="can_view_dashboard_builder",
        feature_module=MODULE_DASHBOARD_BUILDER,
        order=176,
        icon="dashboard",
    ),
    MenuEntry(
        key="help",
        title_az="Yardım Mərkəzi",
        required_flag=None,
        order=190,
        icon="help",
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
    "MODULE_CAMERA",
    "MODULE_DASHBOARD_BUILDER",
    "MODULE_FINES",
    "MODULE_SALES",
    "MODULE_SHIFT_SWAP",
    "MODULE_TASKS",
    "build_default_registry",
]
