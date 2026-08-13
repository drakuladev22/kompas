-- ===========================================================================
-- 023 — #7 POS SƏLAHİYYƏT SİYASƏTİNİN ROOT PARAMETRİ
-- ===========================================================================
-- Tarix : 2026-08-12
-- Səbəb : Faza 4 (kompasos11.md) `POSThresholdUseCase`-i qurur.
--         `pos_permission_thresholds.max_discount_pct` sütununun DB `CHECK`-i
--         (migrations/018) 0–100 sxem sərhədidir və dəyişməzdir — bu miqrasiya
--         onu YUMŞALTMIR. Əvəzinə Root-un bu sərhədin ALTINDA öz biznes
--         siyasətini tətbiq edə biləcəyi ƏLAVƏ tavanı (`POS_MAX_DISCOUNT_
--         PCT_CEILING`) seed edir — `SystemLimitKey`-i artıq elan edir
--         (src/domain/policies.py), bu miqrasiya həmin açarı `system_limits`-ə
--         yazır ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜN.
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir.
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ SEED LAZIMDIR — `DEFAULT_LIMITS` NİYƏ KİFAYƏT ETMİR
-- ---------------------------------------------------------------------------
-- Kod tərəfi `SystemLimits.get_str(tenant, key, default)` işlədir, yəni sətir
-- olmasa da use case DOĞRU dəyərlə (100, yəni sxem sərhədi ilə eyni) işləyir
-- — funksional qüsur YOXDUR. Lakin ROOT paneli `describe()` ilə
-- `system_limits` cədvəlini oxuyur: seed edilməmiş açar orada ÜMUMİYYƏTLƏ
-- görünmür və Root onu dəyişə bilmir. Yəni parametr "konfiqurasiya edilə
-- bilən" olmaqdan çıxıb sükutla sabitə çevrilərdi — miqrasiya 022 eyni
-- boşluğu Vahid İstisna Motorunun dörd açarı üçün bağlamışdı, bu miqrasiya
-- həmin naxışı təkrarlayır.
--
-- ---------------------------------------------------------------------------
-- `min_value` / `max_value` NİYƏ BU HÜDUDLARDADIR
-- ---------------------------------------------------------------------------
-- 0–100: sxem sərhədinin ÖZÜ (migrations/018 `CHECK (max_discount_pct >= 0
-- AND max_discount_pct <= 100)`). Root bu diapazonun İÇİNDƏ istənilən dəyər
-- seçə bilər (məs. 40 — "heç bir işçiyə 40%-dən çox səlahiyyət verilməsin");
-- 100-dən yuxarı dəyər sxem `CHECK`-i ilə ziddiyyət yaradardı, ona görə
-- `max_value` də 100-dür.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('POS_MAX_DISCOUNT_PCT_CEILING', '100', 'INTEGER', '0', '100',
     '#7 — POS Səlahiyyət Siyasətində işçiyə təyin edilə biləcək maksimum '
     'endirim faizinin Root-dan idarə olunan yuxarı tavanı (sxem sərhədi '
     'də 0–100-dür, migrations/018)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022-dəki naxış təkrarlanır: yeni kirayəçi yarananda
-- bu açarı əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_pos_threshold_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'POS_MAX_DISCOUNT_PCT_CEILING', '100', 'INTEGER', '0', '100',
         '#7 — POS Səlahiyyət Siyasətində işçiyə təyin edilə biləcək maksimum '
         'endirim faizinin Root-dan idarə olunan yuxarı tavanı')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_pos_threshold_limits_for_new_tenant() IS
    'Yeni kirayəçiyə #7 POS Səlahiyyət Siyasətinin ROOT parametrini əlavə edir '
    '(migrations/023). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_pos_threshold_limits ON license_tenants;
CREATE TRIGGER trg_seed_pos_threshold_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_pos_threshold_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətrin silinməsi parametri ROOT ekranından yox edir; use case
-- işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyəri (100) ilə — yəni Root
-- onu artıq dəyişdirə bilmir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_pos_threshold_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_pos_threshold_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key = 'POS_MAX_DISCOUNT_PCT_CEILING';
-- COMMIT;
