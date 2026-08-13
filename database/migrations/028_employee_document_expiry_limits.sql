-- ===========================================================================
-- 028 — #17 İŞÇİ SƏNƏDLƏRİNİN BİTMƏ XƏBƏRDARLIĞI ROOT PARAMETRİ
-- ===========================================================================
-- Tarix : 2026-08-12
-- Səbəb : Faza 7 (kompasos11.md #17) sənəd/müqavilə idarəetməsi bitmə
--         tarixinə 30/14/7 gün qalanda xəbərdarlıq göndərir. Bu gün ədədləri
--         MƏRKƏZİ TƏLƏBƏ görə (hər şey ROOT-dan idarə olunur) koda hardcode
--         edilə bilməz. `SystemLimitKey.EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`
--         (src/domain/policies.py) açarı artıq elan olunub — bu miqrasiya
--         onu `system_limits`-ə SEED edir ki, ROOT İdarə Mərkəzi ekranında
--         GÖRÜNSÜN (migrations/022–027 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: `employee_documents` cədvəli
-- (migrations/020) və onun indeksləri/trigger-ləri TOXUNULMUR.
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ ÜÇ AYRI AÇAR YOX, BİR SİYAHI-AÇAR ("30,14,7")
-- ---------------------------------------------------------------------------
-- `src/domain/policies.py`-dəki `SystemLimitKey.EMPLOYEE_DOCUMENT_EXPIRY_
-- WARNING_DAYS` şərhinin təkrarı: üç hədd BİRGƏ bir "xatırlatma cədvəli"
-- təşkil edir. Ayrı açarlarda Root onları yanlış sıraya (məs. birinci hədd
-- ikincidən kiçik) yaza bilərdi və bu, sükutla "hansı ədəd hansı pillədir"
-- sualını pozardı. `value_type = 'TEXT'` və `min_value`/`max_value = NULL` —
-- `EXCEPTION_NOTIFY_MIN_SEVERITY` (migrations/022) və `LEAVE_ALLOWANCE_SOURCE`
-- (migrations/013) ilə EYNİ üslub: mətn açarı üçün ədədi hüdud mənasızdır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ FEATURE TOGGLE SƏTRİ ƏLAVƏ EDİLMİR
-- ---------------------------------------------------------------------------
-- #17 yeni modul açarı tələb etmir — sənəd idarəetməsi `can_manage_employee_
-- documents` flag-i ilə artıq qapılıdır (migrations/021) və bloklama
-- xəbərdarlığı Shift Matrix-in mövcud axınının bir hissəsidir (heç bir ayrı
-- "aç/bağla" düyməsi yoxdur, `LABOR_*` #14 limitləri ilə eyni qərar).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–027 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS', '30,14,7', 'TEXT', NULL, NULL,
     '#17 — Sənəd bitmə tarixinə neçə gün qalanda xəbərdarlıq göndərilsin '
     '(vergüllə ayrılmış tam ədədlər, məs. "30,14,7")')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–027-dəki naxış təkrarlanır: yeni kirayəçi
-- yarananda bu sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_employee_document_expiry_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS', '30,14,7', 'TEXT', NULL, NULL,
         '#17 — Sənəd bitmə tarixinə neçə gün qalanda xəbərdarlıq göndərilsin '
         '(vergüllə ayrılmış tam ədədlər, məs. "30,14,7")')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_employee_document_expiry_limits_for_new_tenant() IS
    'Yeni kirayəçiyə #17 sənəd bitmə xəbərdarlığının ROOT parametrini əlavə '
    'edir (migrations/028). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_employee_document_expiry_limits ON license_tenants;
CREATE TRIGGER trg_seed_employee_document_expiry_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_employee_document_expiry_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətrin silinməsi parametri ROOT ekranından yox edir; xəbərdarlıq
-- işləməyə davam edir, lakin `DEFAULT_LIMITS` fallback-ı ("30,14,7") ilə —
-- yəni Root onu artıq dəyişdirə bilmir. Mövcud sənəd qeydlərinə TƏSİRİ YOXDUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_employee_document_expiry_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_employee_document_expiry_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key = 'EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS';
-- COMMIT;
