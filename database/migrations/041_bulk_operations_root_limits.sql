-- ===========================================================================
-- 041 — TOPLU ƏMƏLİYYATLARIN (#29) ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `kompas1.md` Faza 5 — CSV işçi idxalı + mağaza şablonu BACKEND-i
--         iki konfiqurasiya dəyəri işlədir. `SystemLimitKey` + `DEFAULT_
--         LIMITS` artıq elan edilib (`src/domain/policies.py`); bu miqrasiya
--         həmin açarları `system_limits`-ə yazır ki, ROOT İdarə Mərkəzi
--         ekranında GÖRÜNSÜNLƏR.
--
--         Seed edilməyən açar "konfiqurasiya edilə bilən" görünər, faktiki
--         olaraq isə kodda oturan fallback işləyərdi — `tests/unit/
--         test_root_control_parameter_parity.py` bu boşluğu QAPIYA çevirib
--         (`migrations/039`/`040` ilə eyni əsaslandırma).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
-- MÖVCUD CƏDVƏLLƏRƏ TOXUNULMUR: nə sütun dəyişir, nə ad, nə tip. Bu miqrasiya
-- SIRF YALNIZ `system_limits` seed-idir — `bulk_import_log`/`store_templates`
-- cədvəlləri ARTIQ `migrations/037`-də, icazə flag-i (`can_perform_bulk_
-- operations`) isə `038`-də qurulub.
--
-- ---------------------------------------------------------------------------
-- ÜÇÜNCÜ AÇAR (MAKSIMUM FAYL ÖLÇÜSÜ) NİYƏ BURADA YOXDUR
-- ---------------------------------------------------------------------------
-- `src/application/use_cases/bulk_operations.py` başlığı və `src/domain/
-- policies.py`-dəki `BULK_IMPORT_MAX_ROWS` şərhi bunu açıq izah edir: CSV
-- fayl ölçüsü ARTIQ MÖVCUD `MAX_UPLOAD_SIZE_BYTES` açarının (defolt 5 MB,
-- seed: `schema.sql` §24) altındadır — 300 sətirlik mətn faylı bir neçə on
-- KB-dır, sübut ŞƏKİLLƏRİ üçün nəzərdə tutulmuş bu döşəmədən min qat
-- kiçikdir. İkinci, TƏKRAR açar yaratmaq eyni sualın ("faylım nə qədər ola
-- bilər?") iki fərqli cavabını yaradıb Root-u çaşdırardı.
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ---------------------------------------------------------------------------
--   * BULK_IMPORT_MAX_ROWS 10–5000 — ALT HÜDUD 10-dur, 1 DEYİL: toplu
--     idxalın BÜTÜN MƏQSƏDİ çoxlu sətri BİR DƏFƏYƏ emal etməkdir; 1-9 sətir
--     ÜÇÜN HR fərdi "İşçi Əlavə Et" formasını işlədə bilər — tavanı bu
--     qədər aşağı salmaq funksiyanı faktiki söndürmək olardı (düzgün yolu
--     Feature Toggle-dır, hədd deyil). Üst hüdud 5000 — `bulk_import_log`-da
--     `REVOKE DELETE` var (audit qeydidir): səhvən yüklənmiş nəhəng fayl
--     LƏĞV EDİLƏ BİLMƏZ, yalnız GÖZLƏNİLƏ bilər; tavan bu riski YÜKLƏMƏ
--     ANINDA kəsir. 5000 sətir 21 filiallı şəbəkənin illik BÜTÜN kadr
--     dövriyyəsini (işə qəbul + çıxış) belə əhatə edən, praktik cəhətdən
--     absurd üst sərhəddir.
--   * BULK_IMPORT_PREVIEW_ERROR_LIMIT 5–500 — ALT HÜDUD 5-dir: bundan az
--     sətir HR-ə "ilk N səhv"in NÜMUNƏ olduğunu görməyə imkan verməzdi (məs.
--     1 sətir "ayırıcı səhvdir" ilə "tək bir işçinin poçtu səhvdir" arasında
--     fərqi göstərməz). Üst hüdud 500 — ekranın rahat vərəqlənə bilən sətir
--     sayı; bundan çoxu ekranı SÜRÜŞDÜRMƏYƏ deyil, DONDURMAĞA xidmət edərdi.
--     Aqreqat say (`error_count`) BU HÜDUDDAN ASILI DEYİL — həmişə TAM
--     göstərilir (bax `bulk_operations.py::BulkImportPreview`).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (`039`/`040` ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('BULK_IMPORT_MAX_ROWS', '300', 'INTEGER', '10', '5000',
     'CSV toplu işçi idxalında qəbul edilən maksimum sətir sayı. Fayl bu '
     'tavanı aşarsa TAM RƏDD EDİLİR (sükutla kəsilmir) — HR faylı bölüb '
     'yenidən yükləməlidir. `bulk_import_log`-da DELETE olmadığı üçün '
     'səhvən yüklənmiş nəhəng fayl silinə bilməz, yalnız qarşısı alına bilər'),
    ('BULK_IMPORT_PREVIEW_ERROR_LIMIT', '50', 'INTEGER', '5', '500',
     'Önizləmə ekranında sətir-sətir göstərilən xəta sayının tavanı. '
     'Aqreqat say (`bulk_import_log.error_count`) bu tavandan ASILI DEYİL — '
     'həmişə TAM yazılır, yalnız ətraflı siyahı kəsilir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039/040-dakı naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_bulk_operations_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'BULK_IMPORT_MAX_ROWS', '300', 'INTEGER', '10', '5000',
         'CSV toplu işçi idxalının maksimum sətir sayı'),
        (NEW.tenant_id, 'BULK_IMPORT_PREVIEW_ERROR_LIMIT', '50', 'INTEGER', '5', '500',
         'Önizləmədə göstərilən xəta sətri sayının tavanı')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_bulk_operations_limits_for_new_tenant() IS
    'Yeni kirayəçiyə toplu əməliyyatların iki ROOT parametrini əlavə edir '
    '(migrations/041). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_bulk_operations_limits ON license_tenants;
CREATE TRIGGER trg_seed_bulk_operations_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_bulk_operations_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlər silinsə, toplu əməliyyatlar İŞLƏMƏYƏ DAVAM EDİR — kod
-- `DEFAULT_LIMITS` fallback-ına düşür (300 sətir / 50 xəta sətri). İtən
-- yeganə şey Root-un GUI-dan dəyişdirmə imkanıdır. `migrations/037`-dəki
-- `bulk_import_log`/`store_templates` cədvəllərinə VƏ `038`-dəki
-- `can_perform_bulk_operations` flag-inə TOXUNULMUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_bulk_operations_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_bulk_operations_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'BULK_IMPORT_MAX_ROWS', 'BULK_IMPORT_PREVIEW_ERROR_LIMIT');
-- COMMIT;
