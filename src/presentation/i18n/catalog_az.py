"""Azərbaycan dili kataloqu — Faza 4.2.

`translator.py` bu kataloqu defolt mənbə kimi yükləyir. Açarlar
`bölmə.element.rol` şəklində adlanır ki, eyni sözün fərqli kontekstləri
qarışmasın: "Təsdiqlə" düyməsi növbədə və tapşırıqda eyni mətndir, lakin
gələcəkdə biri dəyişsə digəri toxunulmaz qalmalıdır.

──────────────────────────────────────────────────────────────────────────────
BU FAYL NƏYİ ƏHATƏ EDİR
──────────────────────────────────────────────────────────────────────────────
Burada TƏKRARLANAN interfeys mətnləri var — düymələr, status adları, ümumi
başlıqlar. Bir ekrana MƏXSUS uzun izah cümlələri (məsələn LICENSE_INACTIVE
ekranının izahı) ekranın öz kodunda qalır: onlar bir yerdə işlənir və
kataloqa köçürülsəydi, mətni oxumaq üçün iki fayl arasında gedib-gəlmək
lazım gələrdi.

Mətnlər maketlərdən (Qrup A–G) götürülüb.
"""

from __future__ import annotations

from typing import Final

CATALOG_AZ: Final[dict[str, str]] = {
    # ------------------------------ ümumi ---------------------------------- #
    "common.app_name": "KompasOS",
    "common.save": "Yadda Saxla",
    "common.cancel": "Ləğv Et",
    "common.close": "Bağla",
    "common.back": "Geri",
    "common.next": "Davam Et",
    "common.skip": "Keç",
    "common.finish": "Tamamla",
    "common.approve": "Təsdiqlə",
    "common.reject": "Rədd Et",
    "common.accept": "Qəbul Et",
    "common.retry": "Yenidən Cəhd Et",
    "common.search": "Axtar",
    "common.export_excel": "Excel-ə İxrac Et",
    "common.decline": "İmtina",
    "common.all": "Hamısı",
    "common.loading": "Yüklənir…",
    "common.waiting": "Gözlənilir…",
    "common.none": "—",
    # ------------------------------ giriş ---------------------------------- #
    "auth.login.title": "Hesabınıza Daxil Olun",
    "auth.login.username": "İstifadəçi adı",
    "auth.login.password": "Şifrə",
    "auth.login.submit": "Daxil Ol",
    "auth.login.checking": "Yoxlanılır…",
    "auth.login.forgot": "Şifrənizi unutmusunuz?\nAdmininizlə əlaqə saxlayın.",
    "auth.login.username_required": "İstifadəçi adını daxil edin",
    "auth.login.password_required": "Şifrəni daxil edin",
    # --------------------------- ilk quraşdırma ----------------------------- #
    "setup.title": "Quraşdırma",
    # Açar adı `admin` qalır (tarixi), MƏTNİ isə CEO-dur — sihirbaz məhz o
    # rolu yaradır (SEC-024). Açarı dəyişmək kataloqun bütün istinadlarını
    # sındırardı və heç bir fayda verməzdi: görünən yalnız dəyərdir.
    "setup.step.admin": "Şirkət Rəhbəri (CEO)",
    "setup.step.admin.hint": "E-poçt, istifadəçi adı, şifrə",
    "setup.step.store": "İlk Mağaza",
    "setup.step.store.hint": "Ad, brend, ünvan",
    "setup.step.server": "1C Server",
    "setup.step.server.hint": "İstəyə görə keçilə bilər",
    "setup.progress": "Addım {current} / {total}",
    "setup.password_mismatch": "Şifrələr uyğun gəlmir",
    # ------------------------------- kiosk ---------------------------------- #
    "kiosk.pin.prompt": "PIN kodunuzu daxil edin",
    "kiosk.pin.clear": "Təmizlə",
    "kiosk.pin.delete": "Sil",
    "kiosk.pin.help": "Problem yaşayırsınızsa mağaza rəhbərinizə müraciət edin.",
    "kiosk.pin.wrong": "PIN yanlışdır — {remaining} cəhd qaldı",
    "kiosk.pin.locked": "Terminal {minutes} dəqiqə bloklandı. Mağaza rəhbərinizə müraciət edin.",
    "kiosk.home.greeting": "Salam, {name}",
    "kiosk.home.status": "Cari vəziyyət",
    "kiosk.home.change_photo": "Şəkli Dəyiş",
    "kiosk.home.logout": "Çıxış",
    "kiosk.home.tasks": "Açıq Tapşırıqlarım",
    "kiosk.home.points": "Xal Balansım",
    "kiosk.home.fines": "Cərimələrim",
    # ------------------------- işçi statusları ------------------------------ #
    "status.not_started": "Günə Başlamayıb",
    "status.pending_check_in": "Giriş Təsdiqi Gözləyir",
    "status.verified": "Mağazada",
    "status.outside": "Xaricdə",
    "status.pending_return": "Qayıdış Təsdiqi Gözləyir",
    "status.action.start": "İşə Başladım",
    "status.action.request_leave": "İcazə İstəyirəm",
    "status.action.returned": "Mən Qayıtdım",
    # ---------------------------- naviqasiya -------------------------------- #
    "nav.section": "Naviqasiya",
    "nav.dashboard": "İdarə Paneli",
    "nav.live_queue": "Canlı Növbə",
    "nav.daily_roster": "Gündəlik Tabel",
    "nav.shift_planning": "Növbə Planlama",
    "nav.shift_swaps": "Növbə Dəyişmə",
    "nav.fines": "Cərimələr",
    "nav.fine_appeals": "Cərimə Etirazları",
    "nav.tasks": "Tapşırıqlar",
    "nav.sales_points": "Satış Xalları",
    "nav.unassigned_sales": "Şübhəli Satışlar",
    "nav.users": "İstifadəçilər",
    "nav.permissions": "İcazə Matrisi",
    "nav.erp_servers": "ERP / 1C Serverləri",
    "nav.backups": "Ehtiyat Nüsxə və Bərpa",
    "nav.health": "Sistem Sağlamlığı",
    "nav.audit": "Audit Jurnalı",
    "nav.drive_connection": "Drive Bağlantısı",
    "nav.root_control": "ROOT İdarə Mərkəzi",
    "nav.break_glass": "Fövqəladə Giriş",
    "nav.settings": "Ayarlar",
    "nav.profile": "Profil",
    # ------------------------------ növbə ----------------------------------- #
    "queue.title": "Canlı Təsdiq Növbəsi",
    "queue.check_in": "Giriş Təsdiqi",
    "queue.return": "Qayıdış Təsdiqi",
    "queue.adjust_time": "Vaxtı Düzəlt",
    "queue.ivms_reminder": "Fiziki görüntünü iVMS proqramında yoxlayın",
    "queue.empty.title": "Gözləyən sorğu yoxdur",
    "queue.no_stores.title": "Sizə mağaza təyin edilməyib",
    # --------------------------- vaxt düzəlişi ------------------------------ #
    "override.title": "Vaxtı Manual Düzəlt",
    "override.system_time": "Sistem qeydi",
    "override.corrected_time": "Düzəldilmiş vaxt",
    "override.reason": "Səbəb *",
    "override.reason_required": "Səbəb məcburidir",
    "override.audit_note": "Səbəb audit jurnalına yazılır və silinmir.",
    "override.dual_control": "Cüt Nəzarətli Təsdiq Tələb Olunacaq",
    "override.submit": "Təsdiqə Göndər",
    # ----------------------------- cərimələr -------------------------------- #
    "fine.new": "Yeni Cərimə",
    "fine.type": "Cərimə Növü",
    "fine.store": "Mağaza",
    "fine.employee": "İşçi",
    "fine.date": "Tarix",
    "fine.amount": "Qiymət",
    "fine.photo": "Foto Sübutu *",
    "fine.photo_required": "Foto sübutu məcburidir",
    "fine.submit": "Cəriməni Qeyd Et",
    "fine.status.approved": "Təsdiqlənib",
    "fine.status.appealed": "Etiraz edilib",
    "fine.status.cancelled": "Ləğv edilib",
    "fine.status.pending": "Gözləyir",
    "fine.appeal": "Etiraz Et",
    "fine.appeal.submit": "Etirazı Göndər",
    "fine.appeal.reason": "Etiraz səbəbi",
    "fine.appeal.explanation": "İzah",
    "fine.appeal.explanation_required": "İzah məcburidir",
    "fine.appeal.deadline": "Etiraz müddəti cərimə yazıldıqdan sonra 3 gündür.",
    # ------------------------------ tabel ----------------------------------- #
    "roster.approve": "Tabeli Təsdiqlə",
    "roster.save_draft": "Qaralama Saxla",
    "roster.note_placeholder": "Rəhbər qeydi əlavə et…",
    "roster.planned": "Planlaşdırılıb",
    "roster.verified": "Təsdiqli giriş",
    "roster.late": "Gecikən",
    "roster.absent": "Gəlməyən",
    # ------------------------------ istifadəçi ------------------------------ #
    "users.new": "Yeni İşçi",
    "users.reset_pin": "PIN Sıfırla",
    "users.reset_password": "Şifrəni Yenilə",
    "users.change_role": "Rolu Dəyiş",
    "users.deactivate": "Deaktiv Et",
    "users.status.active": "Aktiv",
    "users.status.on_leave": "Məzuniyyətdə",
    "users.status.blocked": "Bloklanıb",
    # ------------------------------ icazələr -------------------------------- #
    "permissions.roles": "Vəzifələr",
    "permissions.new_role": "+ Yeni Vəzifə",
    "permissions.active_count": "{active} / {total} aktiv",
    "permissions.hardlock_note": "Qıfıllı icazələr hardlock-dur — yalnız ROOT "
    "İdarə Mərkəzindən dəyişdirilir.",
    "permissions.override": "Fərdi İstisna",
    # -------------------------------- ERP ----------------------------------- #
    "erp.new_server": "Yeni Server",
    "erp.test_all": "Hamısını Yoxla",
    "erp.test_connection": "Bağlantını Yoxla",
    "erp.status.active": "Aktiv",
    "erp.status.slow": "Gecikmə yüksəkdir",
    "erp.status.offline": "Bağlantı yoxdur",
    # ------------------------------ backup ---------------------------------- #
    "backup.now": "İndi Ehtiyat Nüsxə Al",
    "backup.restore": "Bu Nöqtəyə Bərpa Et",
    "backup.restore.confirm_title": "Bu nöqtəyə bərpa edilsin?",
    "backup.retention": "Son 30 günün ehtiyat nüsxələri saxlanılır, sonra avtomatik silinir.",
    # ------------------------------- audit ---------------------------------- #
    "audit.immutable": "Audit yazıları dəyişdirilə və silinə bilməz.",
    # ------------------------------ ayarlar --------------------------------- #
    "settings.appearance": "Görünüş",
    "settings.theme.light": "İşıqlı",
    "settings.theme.dark": "Qaranlıq",
    "settings.theme.system": "Sistemə uyğun",
    "settings.language": "İnterfeys dili",
    "settings.notifications": "Bildirişlər",
    "settings.security": "Təhlükəsizlik",
    "settings.change_password": "Şifrəni Dəyiş",
    "settings.close_sessions": "Hamısını Bağla",
    # ------------------------------- ROOT ----------------------------------- #
    "root.title": "ROOT İdarə Mərkəzi",
    "root.mode": "ROOT rejimi",
    "root.apply": "Tətbiq Et",
    "root.limits": "Dinamik limitlər",
    "root.modules": "Modul açarları",
    "root.registry": "İcazə registri",
    # ----------------------------- bildirişlər ------------------------------ #
    "notifications.title": "Bildirişlər",
    "notifications.mark_all_read": "Hamısını oxunmuş et",
    "notifications.see_all": "Bütün bildirişlərə bax",
    "notifications.retention": "30 gün saxlanılır",
    "notifications.unread": "{count} yeni",
    "notifications.empty": "Bildiriş yoxdur.",
    # ------------------------------- profil --------------------------------- #
    "profile.title": "Profilim",
    "profile.personal": "Şəxsi məlumat",
    "profile.sessions": "Son giriş tarixçəsi",
    "profile.role": "Rol və səlahiyyət",
    "profile.locked_note": "İstifadəçi adı və e-poçt yalnız Admin tərəfindən dəyişdirilir.",
    # ------------------------------- dəstək --------------------------------- #
    "support.title": "KompasOS Dəstək",
    "support.online": "Onlayn · adətən 10 dəq içində",
    "support.placeholder": "Mesaj yazın…",
    # ----------------------------- lisenziya -------------------------------- #
    "license.inactive.title": "Lisenziya aktiv deyil",
    "license.inactive.reason": "Səbəb",
    "license.inactive.date": "Deaktiv tarixi",
    "license.inactive.installation": "Quraşdırma nömrəsi",
    "license.inactive.contact": "Bərpa üçün təchizatçı ilə əlaqə saxlayın",
    # ----------------------------- vəziyyətlər ------------------------------ #
    "state.empty.title": "Məlumat yoxdur",
    "state.error.title": "Serverə bağlanmaq mümkün olmadı",
    "state.error.code": "Xəta kodu",
    "state.error.last_success": "Son uğurlu yenilənmə",
    # ƏDƏD QƏSDƏN ÇIXARILIB: mətn əvvəl "30 saniyədən bir" yazırdı, halbuki bu
    # kataloq sətri STATİKDİR (modul səviyyəsində qurulur) və heç bir təkrar-
    # cəhd dövrəsinə bağlı deyil. Yeganə 30 saniyəlik dövrə `REALTIME_POLL_
    # INTERVAL_SECONDS`-dir və o, Root-dan idarə olunur — yəni Root ritmi
    # dəyişən kimi mətn YALAN olardı. Konfiqurasiyaya bağlana bilməyən ədədi
    # mətndə saxlamaq mətnlə davranışı bir-birindən ayırmaq deməkdir.
    "state.error.auto_retry": "Bağlantı bərpa olunan kimi avtomatik yenidən cəhd edilir.",
}

__all__ = ["CATALOG_AZ"]
