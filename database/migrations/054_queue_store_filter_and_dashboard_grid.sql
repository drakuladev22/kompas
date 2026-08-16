-- ===========================================================================
-- 054 — KAMERA NÖVBƏSİNİN MAĞAZA SÜZGƏCİ + PANEL ŞƏBƏKƏSİ (audit G-5, G-6)
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : Auditin iki boşluğu spesifikasiyada təsvir olunub, kodda isə sabit
--         ədədə çevrilə bilərdi:
--
--         G-6 — Kamera Operatorunun mağaza süzgəci. Bölmə 4 açıq deyir:
--               "3-dən çox mağazası varsa mağaza seçimi olsun". Ədəd özü
--               müəssisədən asılıdır və `system_limits`-ə aiddir.
--
--         G-5 — Panel Qurucusunda ŞƏBƏKƏ (sətir/sütun/en) yerləşdirməsi.
--               Şəbəkənin SÜTUN SAYI ekran ölçüsündən asılı görünüş
--               dəyəridir; sabit ədəd bir müştəridə boş sahə, digərində
--               kəsilmiş başlıq verərdi.
--
--         `SystemLimitKey` + `DEFAULT_LIMITS` artıq elan edilib
--         (`src/domain/policies.py`); bu miqrasiya həmin iki açarı
--         `system_limits`-ə yazır ki, ROOT İdarə Mərkəzində GÖRÜNSÜN və
--         dəyişdirilə bilsin. Seed edilməyən açar "konfiqurasiya edilə bilən"
--         görünər, faktiki olaraq isə kodda oturan fallback işləyərdi
--         (`tests/unit/test_root_control_parameter_parity.py` bunu QAPIYA
--         çevirib — migrations/039–044 ilə eyni əsaslandırma).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- HEÇ BİR CƏDVƏL DƏYİŞMİR — BU MİQRASİYA SIRF `system_limits` SEED-İDİR
-- ---------------------------------------------------------------------------
--   * `camera_assignments` TOXUNULMUR. Süzgəc SƏLAHİYYƏT QAPISI DEYİL:
--     operator onsuz da yalnız ÖZÜNƏ təyin edilmiş mağazaları görür
--     (`CameraAssignmentRepository.stores_for_operator`) və «Hamısı» seçimi
--     də məhz həmin dəsti əhatə edir. Yeni sütun/cədvəl lazım olsaydı, bu,
--     süzgəcin görünüşdən artıq bir şey etdiyini bildirərdi — etmir.
--
--   * `user_preferences.dashboard_layout` (migrations/011) SÜTUN OLARAQ
--     DƏYİŞMİR və `chk_dashboard_layout_is_array` CHECK-i də qalır. Şəbəkə
--     yerləşdirməsi HƏMİN massivin İÇİNDƏ, elementin ÖZÜNDƏ kodlanır
--     (`stat_tiles@0,0,2` — bax `application/use_cases/dashboard_layout.py`
--     başlığındakı "NİYƏ KODLANMIŞ SƏTİR" bölməsi). Nəticədə:
--       – köhnə sətirlər (`["stat_tiles", ...]`) OLDUĞU KİMİ oxunur və tək
--         sütunlu şəbəkəyə çevrilir — heç bir məlumat itmir;
--       – miqrasiya `UPDATE` etmir, yəni geri qayıtmaq da sərbəstdir.
--     JSONB obyekt massivi (`[{"key": ..., "row": ...}]`) alternativi RƏDD
--     EDİLDİ: o, `DashboardLayoutStore` portunun (`list[str]`) tipini
--     dəyişdirərdi və köhnə sətir yeni oxucuda `str(dict)` kimi görünərdi.
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ---------------------------------------------------------------------------
-- CAMERA_QUEUE_STORE_FILTER_THRESHOLD (INTEGER, defolt 3)
--   * min = 1 — 0 yazılsa süzgəc TƏK mağazalı operatorda da görünərdi və bir
--     sətirlik siyahını süzmək təklif edilərdi (mənasız element). 1 isə
--     "iki və daha çox mağazada göstər" deməkdir — anlamlı ən aşağı hədd.
--   * max = 100 — bir operatorun praktik mağaza tavanı. Daha böyük dəyər
--     süzgəci bütün şəbəkədə sükutla söndürərdi; söndürmək istəyən Root
--     məhz böyük ədəd yazır və bu, AÇIQ seçimdir.
--
-- DASHBOARD_GRID_COLUMNS (INTEGER, defolt 2)
--   * min = 1 — bir sütun ŞƏBƏKƏNİN SÖNDÜRÜLMÜŞ formasıdır (köhnə xətti
--     davranışın eynisi) və qanuni seçimdir. 0 isə heç bir widget-in yerini
--     təyin edə bilməzdi.
--   * max = 4 — 1280px minimum pəncərədə (bax `widgets/metrics.py:
--     LAYOUT_BREAKPOINT_WIDE`) dörd sütun kartı ~300px-ə endirir; beşinci
--     sütunda başlıqlar kəsilir. Dar pəncərə onsuz da tək sütuna yığılır,
--     yəni tavan yalnız GENİŞ rejimə aiddir.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR.
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('CAMERA_QUEUE_STORE_FILTER_THRESHOLD', '3', 'INTEGER', '1', '100',
     'Kamera Operatorunun canlı növbəsində mağaza süzgəcinin görünməsi üçün '
     'lazım olan mağaza sayı. Operatorun təyinatı bu ədəddən ÇOXDURSA süzgəc '
     'göstərilir; az və ya bərabər olduqda siyahı onsuz da qısadır və əlavə '
     'seçici yalnız ekranı doldurardı. SÜZGƏC SƏLAHİYYƏT GENİŞLƏNDİRMİR — '
     'operator hər halda yalnız özünə təyin edilmiş mağazaların sorğularını '
     'görür və «Hamısı» seçimi də məhz həmin dəsti əhatə edir'),
    ('DASHBOARD_GRID_COLUMNS', '2', 'INTEGER', '1', '4',
     'İdarə Panelindəki widget şəbəkəsinin sütun sayı. Hər widget üçün '
     'sətir/sütun və en (span) Panel Qurucusundan seçilir; en bu ədədi keçə '
     'bilmir. 1 yazılsa şəbəkə köhnə XƏTTİ düzülüşün eynisinə çevrilir. Dar '
     'pəncərədə (1280px-dən az) şəbəkə bu dəyərdən ASILI OLMAYARAQ tək sütuna '
     'yığılır — yəni böyük ədəd dar ekranda düzülüşü sındırmır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039–044-dəki naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_ui_surface_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'CAMERA_QUEUE_STORE_FILTER_THRESHOLD', '3', 'INTEGER', '1', '100',
         'Növbədə mağaza süzgəcinin görünməsi üçün lazım olan mağaza sayı'),
        (NEW.tenant_id, 'DASHBOARD_GRID_COLUMNS', '2', 'INTEGER', '1', '4',
         'İdarə Paneli widget şəbəkəsinin sütun sayı')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_ui_surface_limits_for_new_tenant() IS
    'Yeni kirayəçiyə növbə süzgəci və panel şəbəkəsi parametrlərini əlavə edir '
    '(migrations/054). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_ui_surface_limits ON license_tenants;
CREATE TRIGGER trg_seed_ui_surface_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_ui_surface_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- 3. SÜTUN ŞƏRHİNİN GENİŞLƏNMƏSİ — `user_preferences.dashboard_layout`
-- ---------------------------------------------------------------------------
-- Sütunun ÖZÜ, tipi və CHECK-i DƏYİŞMİR (migrations/011 qüvvədədir); yalnız
-- İSTİFADƏSİ konkretləşir ki, bazaya baxan adam iki formatı görüb "hansı
-- düzgündür?" sualı ilə qalmasın.
COMMENT ON COLUMN user_preferences.dashboard_layout IS
    'İstifadəçinin İdarə Paneli düzülüşü — JSONB SƏTİR MASSİVİ. İki format '
    'eyni sütunda yaşayır və hər ikisi qanunidir: (1) XƏTTİ — sadə widget '
    'açarı ("stat_tiles"), sıra massivin öz sırasıdır; (2) ŞƏBƏKƏ — '
    '"acar@setir,sutun,en" (məs. "stat_tiles@0,0,2"). Oxucu formatsız '
    'elementi tək sütunlu şəbəkə kimi oxuyur (sətir = massivdəki mövqe, '
    'sütun = 0, en = tam genişlik), ona görə köhnə sətirlər üçün UPDATE '
    'LAZIM DEYİL və geri qayıtmaq da sərbəstdir. NULL = "istifadəçi heç vaxt '
    'qurmayıb" (defolt tətbiq olunur), boş massiv = "hər şeyi qəsdən '
    'gizlətdim" — bu fərq migrations/011-in əsas qərarıdır və qalır.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlər silinsə, hər iki ekran İŞLƏMƏYƏ DAVAM EDİR — kod
-- `DEFAULT_LIMITS` fallback-larına düşür (3 / 2). İtən yeganə şey Root-un
-- GUI-dan dəyərləri dəyişdirmə imkanıdır.
--
-- `user_preferences` sətirlərinə TOXUNULMUR: orada istifadəçilərin qəsdən
-- qurduğu düzülüş var və şəbəkə formatı köhnə oxucuda da sıradan çıxmır —
-- açar hissəsi `@`-dan əvvəl olduğu üçün ən pis halda gözardı edilər.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_ui_surface_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_ui_surface_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'CAMERA_QUEUE_STORE_FILTER_THRESHOLD',
--       'DASHBOARD_GRID_COLUMNS');
-- COMMIT;
