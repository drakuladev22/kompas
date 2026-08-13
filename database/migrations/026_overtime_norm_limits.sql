-- ===========================================================================
-- 026 — #15 NORMA ÜSTÜ İŞ SAATLARININ ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-12
-- Səbəb : Faza 6 (kompasos11.md) `OvertimeTrackingUseCase`-i qurur. Üç
--         parametr var — gündəlik norma, həftəlik norma və bildiriş həddi —
--         və MƏRKƏZİ TƏLƏBƏ görə (hər şey ROOT-dan idarə olunur) heç biri
--         koda hardcode edilə bilməz. `SystemLimitKey` + `DEFAULT_LIMITS`
--         (src/domain/policies.py) onları artıq elan edir; bu miqrasiya
--         həmin açarları `system_limits`-ə SEED edir ki, ROOT İdarə Mərkəzi
--         ekranında GÖRÜNSÜNLƏR (miqrasiya 022/023/024 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir.
-- `overtime_log` cədvəlinin ÖZÜ artıq migrations/019-dadır (sətir 123–207)
-- və ona TOXUNULMUR.
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ SEED LAZIMDIR — `DEFAULT_LIMITS` NİYƏ KİFAYƏT ETMİR
-- ---------------------------------------------------------------------------
-- Kod tərəfi `SystemLimits.get_str(tenant, key, default)` işlədir, yəni sətir
-- olmasa da hesablama DOĞRU dəyərlə işləyir — funksional qüsur YOXDUR. Lakin
-- ROOT paneli `describe()` ilə `system_limits` cədvəlini oxuyur: seed
-- edilməmiş açar orada ÜMUMİYYƏTLƏ görünmür və Root onu dəyişə bilmir. Yəni
-- parametr "konfiqurasiya edilə bilən" olmaqdan çıxıb sükutla sabitə
-- çevrilərdi (miqrasiya 022/023/024 eyni boşluğu bağlamışdı).
--
-- ---------------------------------------------------------------------------
-- DEFOLTLAR VƏ `min_value` / `max_value` HÜDUDLARI NİYƏ BELƏDİR
-- ---------------------------------------------------------------------------
--   * OVERTIME_DAILY_NORM_HOURS (defolt 8.00, 1–24): Azərbaycan Əmək
--     Məcəlləsinin normal gündəlik iş vaxtı 8 saatdır. Aşağı hədd 1-dir
--     (0 "hər dəqiqə norma üstüdür" demək olardı və jurnalı mənasız edərdi),
--     yuxarı hədd 24 — sutkadan uzun gün fiziki olaraq mümkün deyil.
--   * OVERTIME_WEEKLY_NORM_HOURS (defolt 40.00, 1–168): həftəlik normal iş
--     vaxtı 40 saatdır. 168 = 7 × 24, yəni təqvim həftəsinin tam uzunluğu.
--     QEYD: həftəlik normanın gündəlikdən kiçik olması MƏNTİQLİ haldır
--     (məs. 8 saat / 24 saat həftə = qismən ştat), ona görə DB-də çarpaz
--     `CHECK` QOYULMUR — belə bir məhdudiyyət qanuni konfiqurasiyanı
--     bloklayardı.
--   * OVERTIME_NOTIFY_THRESHOLD_HOURS (defolt 1.00, 0–24): 0 QANUNİDİR və
--     "hər aşımı bildir" deməkdir; 24 isə praktik olaraq bildirişi söndürür.
--     Hədd YALNIZ bildirişə təsir edir — jurnala aşımın HAMISI yazılır, yəni
--     həddi qaldırmaq məlumat itkisi YARATMIR.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022/023/024 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('OVERTIME_DAILY_NORM_HOURS', '8.00', 'DECIMAL', '1', '24',
     '#15 — Gündəlik norma iş saatı; bundan çoxu `overtime_log`-a norma üstü '
     'kimi yazılır'),
    ('OVERTIME_WEEKLY_NORM_HOURS', '40.00', 'DECIMAL', '1', '168',
     '#15 — Həftəlik (Bazar ertəsi–Bazar) norma iş saatı; gündəlik norma '
     'aşılmasa belə həftəlik aşım qeydə alınır'),
    ('OVERTIME_NOTIFY_THRESHOLD_HOURS', '1.00', 'DECIMAL', '0', '24',
     '#15 — Bu hədddən (daxil olmaqla) böyük aşım HR_Admin-ə bildiriş '
     'doğurur; jurnala isə aşımın hamısı yazılır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022/023/024-dəki naxış təkrarlanır: yeni kirayəçi
-- yarananda bu üç sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_overtime_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'OVERTIME_DAILY_NORM_HOURS', '8.00', 'DECIMAL', '1', '24',
         '#15 — Gündəlik norma iş saatı; bundan çoxu `overtime_log`-a norma '
         'üstü kimi yazılır'),
        (NEW.tenant_id, 'OVERTIME_WEEKLY_NORM_HOURS', '40.00', 'DECIMAL', '1', '168',
         '#15 — Həftəlik (Bazar ertəsi–Bazar) norma iş saatı'),
        (NEW.tenant_id, 'OVERTIME_NOTIFY_THRESHOLD_HOURS', '1.00', 'DECIMAL', '0', '24',
         '#15 — Bu hədddən böyük aşım HR_Admin-ə bildiriş doğurur')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_overtime_limits_for_new_tenant() IS
    'Yeni kirayəçiyə norma üstü iş saatlarının üç ROOT parametrini əlavə edir '
    '(migrations/026). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_overtime_limits ON license_tenants;
CREATE TRIGGER trg_seed_overtime_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_overtime_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir;
-- hesablama işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə (gündə
-- 8, həftədə 40 saat) — yəni Root onları artıq dəyişdirə bilmir.
-- `overtime_log` cədvəli və içindəki sətirlər BU BLOKDAN TƏSİRLƏNMİR; onların
-- geri qaytarılması migrations/019-un DOWN blokundadır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_overtime_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_overtime_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'OVERTIME_DAILY_NORM_HOURS', 'OVERTIME_WEEKLY_NORM_HOURS',
--       'OVERTIME_NOTIFY_THRESHOLD_HOURS'
--   );
-- COMMIT;
