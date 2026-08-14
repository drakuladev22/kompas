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

EYNİ QAYDA SELF-SERVICE EKRANLARINA DA AİDDİR (`profile`, `help`,
`sales_points`): istifadəçinin ÖZ məlumatını görməsi səlahiyyət tələb etmir —
qapı orada deyil, "başqasının məlumatı" yolunun mövcud OLMAMASINDADIR. Belə
ekrana idarəetmə flag-i qoymaq (məs. `can_manage_sales_points`) işçini öz
balansından kəsir, halbuki bölmə 3 həmin flag-i menecer əməliyyatı kimi
tərif edir.

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
        key="annual_leave",
        title_az="Məzuniyyət Sorğuları",
        # #28 (kompas1.md Faza 4) — İLLİK məzuniyyətin təsdiq növbəsi.
        #
        # NİYƏ «Növbə Dəyişmə»DƏN DƏRHAL SONRA: hər ikisi eyni formada
        # işləyən TƏSDİQ NÖVBƏSİDİR (`PENDING_APPROVAL → APPROVED/REJECTED`,
        # məcburi rədd səbəbi) və HR onları eyni ritmdə gəzir. Ayrı-ayrı
        # yerlərdə dursaydılar, "təsdiq gözləyən nə var?" sualının cavabı
        # menyunun iki ucunda qalardı.
        #
        # NİYƏ «İcazə Növləri» (184) İLƏ QARIŞDIRILMIR: o, STEP1/STEP2
        # GÜNDAXİLİ icazənin kataloqudur (DƏQİQƏ), bu isə İLLİK haqqdır (GÜN).
        # Adların oxşarlığı mexanizmlərin eyniliyi demək deyil — üç ayrı
        # mexanizmin izahı `screens/annual_leave.py` başlığındadır.
        #
        # FEATURE TOGGLE YOXDUR: illik məzuniyyət qanuni haqqdır və "modul"
        # kimi söndürülə bilməz (`announcements` ilə eyni qərar — tək flag-lə
        # qapılı funksiya).
        required_flag="can_manage_leave_balances",
        order=52,
        icon="calendar",
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
        key="store_audit",
        title_az="Mağaza Auditi",
        # #26 (kompas1.md Faza 3) — checklist tələb edən şablon ailəsi.
        # `can_conduct_store_audit` DEFOLT yalnız Root/CEO/Admin/HR_Admin-dədir
        # (migrations/038): strukturlaşdırılmış yoxlama düzəliş tapşırığı
        # yaradır və bal Dashboard-a düşür, yəni "hər kəs" səlahiyyəti deyil.
        #
        # «Tapşırıqlar»dan (80) DƏRHAL SONRA durur, təsadüfən yox: uğursuz
        # bloklayıcı bənd məhz həmin ekranda görünən tapşırığı yaradır — iki
        # maddəni bir-birindən ayırmaq səbəb-nəticə zəncirini gizlədərdi.
        required_flag="can_conduct_store_audit",
        order=82,
        icon="checklist",
    ),
    MenuEntry(
        key="incident_report",
        title_az="İnsident Bildirişi",
        # #27 (kompas1.md Faza 3) — checklist tələb ETMƏYƏN şablon ailəsi.
        #
        # BU MADDƏ QƏSDƏN "ADMIN-TIER" DEYİL. `can_report_incident`
        # migrations/038-də BÜTÜN 7 rola verilib ("Tələ 3": hər kəs insident
        # bildirə bilməlidir, YALNIZ həlli məhduddur) və menyu həmin qərarı
        # OLDUĞU KİMİ güzgüləyir: flag-i olan `Satıcı` da bu maddəni görür.
        # Flag-i universal edib menyunu admin-tier saxlasaydıq, 038-in Tələ 3
        # qərarı sükutla ölü qalardı — verilmiş, lakin heç bir yolla
        # işlədilə bilməyən səlahiyyət.
        #
        # AÇIQ SİYAHI YENƏ DƏ MƏHDUDDUR: `list_open` `can_conduct_store_audit`
        # tələb edir, ona görə `Satıcı` yalnız FORMANI görür, başqalarının
        # insidentlərini yox (`controllers/field_reports.py` başlığı).
        required_flag="can_report_incident",
        order=84,
        # `"fine"` ADI tarixidir, QLİFİ isə nida işarəli XƏBƏRDARLIQ ÜÇBUCAĞIDIR
        # (bax `widgets/icons.py`) — insident üçün düzgün formadır. Yeni ikon
        # əlavə etmək dizayn dəstini eyni formanın ikinci nüsxəsi ilə şişirdərdi.
        icon="fine",
    ),
    MenuEntry(
        key="sales_points",
        title_az="Satış Xalları",
        # FLAG-SİZ — `profile`/`dashboard`/`help` ilə eyni səbəbdən.
        #
        # Ekran (`group_f.SalesPointsScreen` + `screen_data._sales_points`)
        # YALNIZ aktorun ÖZ balansını, öz tarixçəsini və hamıya açıq mükafat
        # kataloqunu göstərir: `SalesPointsUseCase.balance_for` səlahiyyət
        # yoxlamır və "başqasının balansı" yolu ÜMUMİYYƏTLƏ yoxdur.
        #
        # `can_manage_sales_points` isə bölmə 3-də MENECER səlahiyyətidir —
        # "xalları əl ilə düzəltmək, mükafat mübadiləsini təsdiqləmək". Onu
        # bu maddəyə qapı qoymaq işçinin ÖZ balansını görməsini menecer
        # səlahiyyətinə bağlayırdı: adi `Satıcı`-da heç bir flag yoxdur
        # (schema.sql §23), yəni bölmə 6-nın "öz cari xal balansı" tələbi
        # sükutla işləmirdi. Menecer tərəfi (korreksiya/təsdiq) hələ ayrıca
        # ekran deyil; flag «Şübhəli Satışlar» maddəsində qapı olaraq qalır.
        required_flag=None,
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
        key="announcements",
        title_az="Elanlar",
        # #19 (kompasos11.md Faza 8) — mövcud dəstək çatından (`support`)
        # FƏRQLİ, bir-tərəfli broadcast. Feature Toggle YOXDUR (bax
        # `migrations/029` başlığı: tək-flag-lə qapılı kommunikasiya funksiyası).
        required_flag="can_broadcast_announcements",
        order=106,
        icon="bell",
    ),
    MenuEntry(
        key="performance_reviews",
        title_az="Performans Qiymətləndirmələri",
        # #20 (kompasos11.md Faza 8) — nəticə işçinin ÖZ Profil ekranında
        # (`profile`, flag-siz) da görünür; bu maddə yalnız YAZI yoludur.
        required_flag="can_conduct_performance_review",
        order=108,
        icon="checklist",
    ),
    MenuEntry(
        key="users",
        title_az="İstifadəçilər",
        required_flag="can_manage_employees",
        order=110,
        icon="users",
    ),
    MenuEntry(
        key="bulk_operations",
        title_az="Toplu Əməliyyatlar",
        # #29 (kompas1.md Faza 5) — CSV işçi idxalı + mağaza şablonu.
        #
        # NİYƏ «İstifadəçilər»dən (110) DƏRHAL SONRA: hər ikisi işə-qəbul
        # axınının hissəsidir — HR yeni filial açanda ƏVVƏLCƏ şablon tətbiq
        # edir (bax `screens/bulk_operations.py`), SONRA həmin filialın
        # onlarla işçisini CSV ilə yükləyir. `users` fərdi işçi əlavəsidir,
        # bu isə onun TOPLU forması — ayrı-ayrı yerlərdə dursaydılar, "yeni
        # filial necə qurulur?" sualının cavabı menyunun iki ucuna bölünərdi.
        #
        # NİYƏ İKİ AYRI MADDƏ YOX: CSV idxalı VƏ mağaza şablonu EYNİ TƏK
        # flag-ə bağlıdır (`can_perform_bulk_operations`, backend-də də TƏK
        # modul faylı — `bulk_operations.py` başlığı). `field_reports`-dan
        # FƏRQLİ olaraq burada iki AYRI şablon KATEQORİYASI yoxdur ki, iki
        # açar tələb olunsun — bax `screens/bulk_operations.py` başlığı.
        #
        # FEATURE TOGGLE YOXDUR: yüksək-təsirli, YALNIZ Root/CEO/Admin
        # defoltlu əməliyyatdır (hardlock səviyyəsi), "modul" kimi
        # söndürülə bilməz — `announcements`/`annual_leave` ilə eyni qərar.
        required_flag="can_perform_bulk_operations",
        order=112,
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
        key="exceptions",
        title_az="İstisnalar",
        # #9 (kompasos11.md Faza 5) — Vahid İstisna Motorunun jurnalı.
        # "Nəzərdən Keçirildi" / "Rədd Et" qərarları da eyni flag arxasındadır
        # (bax `exception_engine.py::_require_view` başlığı: "OXU VƏ QƏRAR
        # EYNİ FLAG-DƏDİR").
        required_flag="can_view_exceptions",
        order=162,
        icon="shield",
    ),
    MenuEntry(
        key="attrition_risk",
        title_az="İşdən Çıxma Riski",
        # #21 (kompasos11.md Faza 9) — bal HƏSSAS HR proqnozudur (bax
        # `attrition_risk.py` use case başlığı). "GÖRMƏK = SƏLAHİYYƏTİN
        # OLMASI" burada xüsusilə vacibdir: defolt heç bir operativ rola
        # verilmir, yalnız HR_Admin/CEO/Root (migrations/021 flag təsviri).
        required_flag="can_view_attrition_risk",
        order=163,
        icon="activity",
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
