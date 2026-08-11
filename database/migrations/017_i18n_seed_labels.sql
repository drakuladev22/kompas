-- ===========================================================================
-- 017 — SEED ETİKETLƏRİNİN AZƏRBAYCANLAŞDIRILMASI (FAZA 8, lokalizasiya)
-- ===========================================================================
-- Bölmə 9 yeganə interfeys dilini Azərbaycan dili kimi təyin edir. Faza 8-də
-- tətbiq qatındakı bütün İngiliscə sızmalar bağlandı, LAKİN bir yol açıq
-- qalmışdı: bu etiketlərin bir hissəsi KODDA deyil, BAZADA yaşayır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ BU KOD DÜZƏLİŞİ İLƏ BAĞLANMIR
-- ---------------------------------------------------------------------------
-- `presentation/controllers/permission_matrix.py` icazə adlarını UYDURMUR —
-- şüurlu qərarla bazadan oxuyur:
--
--     SELECT code, COALESCE(name_az, code) AS name_az FROM permission_flags
--
-- Səbəb həmin faylın başlığında yazılıb: tərcüməni ekranda təkrarlamaq
-- kataloqla ekran arasında İKİNCİ ad məkanı yaradardı və Root yeni flag
-- əlavə edəndə ekran onu kodu ilə göstərərdi. Yəni mətnin TƏK MƏNBƏYİ
-- bazadır — deməli düzəliş də bazada olmalıdır.
--
-- Eyni şey `system_limits.description_az` və `feature_toggles.description_az`
-- üçün də keçərlidir: `application/use_cases/root_control.py` onları
-- `LimitView.description_az` / `ModuleView.description_az` sahələrində
-- OLDUĞU KİMİ oxu-modelinə ötürür.
--
-- ---------------------------------------------------------------------------
-- MAKET ↔ CANLI CÜTLÜYÜ (CLAUDE.md bölmə 6)
-- ---------------------------------------------------------------------------
-- Maket yolu (`preview_data.PERMISSION_GROUPS`) Faza 8-də artıq tərcümə
-- edildi. Baza yenilənməsəydi, EYNİ ekran maketdə «Cüt nəzarət təsdiqi»,
-- istehsalatda isə «Dual-control təsdiqi» göstərərdi — məhz `menu.py`
-- başlığında təsvir olunan, yalnız istehsalatda üzə çıxan qüsur növü.
--
-- ---------------------------------------------------------------------------
-- NƏ DƏYİŞMİR
-- ---------------------------------------------------------------------------
-- `code` / `flag_code` (`can_view_dashboard_builder`), `limit_key`
-- (`DUAL_CONTROL_THRESHOLD_MINUTES`), `module_key` (`DASHBOARD_BUILDER`),
-- `category`, cədvəl və sütun adları — hamısı İDENTİFİKATORDUR. Onlar
-- `FeatureModule` / `SystemLimitKey` enum dəyərləri və `menu.py` bağlantıları
-- ilə hərfi uyğunluqdadır; tərcümə edilsəydi tətbiq bazadakı sətri TAPA
-- BİLMƏZDİ. Bu miqrasiya YALNIZ insan-oxunaqlı sütunlara toxunur:
-- `positions.description`, `permission_flags.name_az/description_az`,
-- `system_limits.description_az`, `feature_toggles.description_az`.
--
-- İDEMPOTENTLİK: hər `UPDATE` KÖHNƏ dəyəri `WHERE` şərtində hədəfləyir.
-- Təkrar icrada heç bir sətir uyğun gəlmir (0 sətir yenilənir), artıq əl ilə
-- redaktə edilmiş etiket isə ÜSTÜNDƏN YAZILMIR — müştərinin öz mətni
-- miqrasiya tərəfindən geri qaytarılmamalıdır.
--
-- TENANT ƏHATƏSİ: `system_limits` və `feature_toggles` sətirləri hər tenant
-- üçün ayrıca mövcuddur (`seed_tenant_defaults`). `WHERE`-də tenant filtri
-- QƏSDƏN YOXDUR — köhnə mətn hansı tenant-dadırsa hamısı düzəlir.
--
-- DOWN bloku sonda şərh içindədir.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. positions.description — Kamera Nəzarətçisi
-- ---------------------------------------------------------------------------
-- «override» burada MANUAL VAXT DÜZƏLİŞİ mənasındadır (icazə istisnası YOX).
-- Faza 8 terminologiya cədvəli bu iki mənanı ayırır, çünki eyni İngiliscə söz
-- domendə İKİ fərqli anlayışdır: `ManualOverride` ↔ `PermissionOverride`.
-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
-- (Bu miqrasiyada sətir UNUDULMUŞDU — CI-da 010 məhz buna görə çökürdü.)
SET search_path TO kompasos, public;

UPDATE positions
   SET description = 'iVMS-də görüntünü yoxlayıb təsdiq/vaxt düzəlişi/cərimə verir'
 WHERE description = 'iVMS-də görüntünü yoxlayıb təsdiq/override/cərimə verir';


-- ---------------------------------------------------------------------------
-- 2. permission_flags — İcazə Matrisi ekranının GÖRÜNƏN mətni
-- ---------------------------------------------------------------------------
UPDATE permission_flags
   SET description_az = 'Manual vaxt düzəlişi'
 WHERE code = 'can_override_return_time'
   AND description_az = 'Manual Time Override';

UPDATE permission_flags
   SET name_az        = 'Cüt nəzarət təsdiqi',
       description_az = '30+ dəqiqəlik vaxt düzəlişinə ikinci təsdiq (HR_Admin/CEO)'
 WHERE code = 'can_approve_dual_control_override'
   AND name_az = 'Dual-control təsdiqi';

UPDATE permission_flags
   SET name_az        = 'Panel Qurucusuna bax',
       description_az = 'Panel Qurucusu ekranı'
 WHERE code = 'can_view_dashboard_builder'
   AND name_az = 'Dashboard Builder-ə bax';

UPDATE permission_flags
   SET description_az = 'İdarə Paneli widget konfiqurasiyası'
 WHERE code = 'can_edit_dashboard_widgets'
   AND description_az = 'Dashboard widget konfiqurasiyası';

UPDATE permission_flags
   SET name_az        = 'Lisenziya vəziyyətinə bax',
       description_az = 'Lokal lisenziya vəziyyəti + aktivasiya açarı (aktiv/deaktiv etmə YOX)'
 WHERE code = 'can_manage_license'
   AND name_az = 'Lisenziya statusuna bax';

UPDATE permission_flags
   SET name_az = 'Ehtiyat nüsxə/bərpa'
 WHERE code = 'can_manage_backups'
   AND name_az = 'Backup/bərpa';

UPDATE permission_flags
   SET description_az = 'ROOT İdarə Mərkəzi — YALNIZ Root'
 WHERE code = 'can_manage_system_limits'
   AND description_az = 'ROOT Control Center — YALNIZ Root';


-- ---------------------------------------------------------------------------
-- 3. system_limits.description_az — ROOT panelinin oxu-modeli
-- ---------------------------------------------------------------------------
-- Mətn `presentation/controllers/root_control.py`-dakı `LIMIT_LABELS`
-- etiketi ilə EYNİ kökdədir («Cüt nəzarət həddi»); ekran hazırda öz
-- sözlüyünü göstərir, lakin iki mənbənin fərqli danışması gələcək qüsurdur.
UPDATE system_limits
   SET description_az = 'Cüt nəzarət həddi (dəqiqə)'
 WHERE limit_key = 'DUAL_CONTROL_THRESHOLD_MINUTES'
   AND description_az = 'Dual-Control həddi (dəqiqə)';


-- ---------------------------------------------------------------------------
-- 4. feature_toggles.description_az — modul açarlarının izahı
-- ---------------------------------------------------------------------------
-- Hər iki mətn `root_control.py`-dakı `MODULE_LABELS` dəyərləri ilə HƏRFİ
-- olaraq eynidir — Root paneldə modulun adı hansı yoldan gəlirsə gəlsin
-- istifadəçi EYNİ sözü görür.
UPDATE feature_toggles
   SET description_az = 'Cüt-nəzarətli əlavə təsdiq qatı'
 WHERE module_key = 'DUAL_CONTROL'
   AND description_az = 'Dual-Control əlavə təsdiq qatı';

UPDATE feature_toggles
   SET description_az = 'Panel qurucusu'
 WHERE module_key = 'DASHBOARD_BUILDER'
   AND description_az = 'Custom Dashboard Builder';


-- ---------------------------------------------------------------------------
-- 5. YENİ TENANT-LAR — `seed_tenant_defaults()` NİYƏ BURADA TƏKRARLANMIR
-- ---------------------------------------------------------------------------
-- Funksiyanın gövdəsi `schema.sql` §24-dədir və HƏMİN FAYLDA yeni mətnlə
-- yeniləndi (CLAUDE.md bölmə 7: `schema.sql` tək başına tam quraşdırmadır).
-- Funksiyanı burada `CREATE OR REPLACE` etmək onun tərifini İKİ fayla
-- yayardı və növbəti dəyişiklikdə hansının yeni olduğu bilinməzdi.
--
-- Mövcud quraşdırmalarda funksiya artıq köhnə mətnlə yaradılmış ola bilər.
-- Bu, ZƏRƏRSİZDİR: yuxarıdakı `UPDATE`-lər köhnə mətni hədəflədiyi üçün
-- 017 təkrar icra edildikdə (və ya deployment ardıcıllığı `schema.sql`-i
-- sonra tətbiq etdikdə) nəticə eynidir. Sxem faylı ilə miqrasiyanın mətn
-- paritetini `tests/unit/test_i18n_no_english_leaks.py` statik yoxlayır.


-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma)
-- ---------------------------------------------------------------------------
-- Yalnız etiket mətnini geri qaytarır — heç bir struktur dəyişiklik olmayıb,
-- ona görə məlumat itkisi riski YOXDUR.
--
--   UPDATE positions
--      SET description = 'iVMS-də görüntünü yoxlayıb təsdiq/override/cərimə verir'
--    WHERE description = 'iVMS-də görüntünü yoxlayıb təsdiq/vaxt düzəlişi/cərimə verir';
--
--   UPDATE permission_flags SET description_az = 'Manual Time Override'
--    WHERE code = 'can_override_return_time' AND description_az = 'Manual vaxt düzəlişi';
--
--   UPDATE permission_flags
--      SET name_az = 'Dual-control təsdiqi',
--          description_az = '30+ dəqiqəlik override-a ikinci təsdiq (HR_Admin/CEO)'
--    WHERE code = 'can_approve_dual_control_override' AND name_az = 'Cüt nəzarət təsdiqi';
--
--   UPDATE permission_flags
--      SET name_az = 'Dashboard Builder-ə bax', description_az = 'Dashboard Builder ekranı'
--    WHERE code = 'can_view_dashboard_builder' AND name_az = 'Panel Qurucusuna bax';
--
--   UPDATE permission_flags SET description_az = 'Dashboard widget konfiqurasiyası'
--    WHERE code = 'can_edit_dashboard_widgets'
--      AND description_az = 'İdarə Paneli widget konfiqurasiyası';
--
--   UPDATE permission_flags
--      SET name_az = 'Lisenziya statusuna bax',
--          description_az = 'Lokal lisenziya statusu + aktivasiya açarı (aktiv/deaktiv etmə YOX)'
--    WHERE code = 'can_manage_license' AND name_az = 'Lisenziya vəziyyətinə bax';
--
--   UPDATE permission_flags SET name_az = 'Backup/bərpa'
--    WHERE code = 'can_manage_backups' AND name_az = 'Ehtiyat nüsxə/bərpa';
--
--   UPDATE permission_flags SET description_az = 'ROOT Control Center — YALNIZ Root'
--    WHERE code = 'can_manage_system_limits'
--      AND description_az = 'ROOT İdarə Mərkəzi — YALNIZ Root';
--
--   UPDATE system_limits SET description_az = 'Dual-Control həddi (dəqiqə)'
--    WHERE limit_key = 'DUAL_CONTROL_THRESHOLD_MINUTES'
--      AND description_az = 'Cüt nəzarət həddi (dəqiqə)';
--
--   UPDATE feature_toggles SET description_az = 'Dual-Control əlavə təsdiq qatı'
--    WHERE module_key = 'DUAL_CONTROL' AND description_az = 'Cüt-nəzarətli əlavə təsdiq qatı';
--
--   UPDATE feature_toggles SET description_az = 'Custom Dashboard Builder'
--    WHERE module_key = 'DASHBOARD_BUILDER' AND description_az = 'Panel qurucusu';
--
--   -- `schema.sql` §21/§22/§24 seed mətnləri də köhnə variantına qaytarılmalıdır,
--   -- əks halda növbəti təmiz quraşdırma yenidən yeni mətni gətirər.
