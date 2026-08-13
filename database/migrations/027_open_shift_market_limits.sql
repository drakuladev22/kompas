-- ===========================================================================
-- 027 — #16 AÇIQ NÖVBƏ BAZARININ ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-12
-- Səbəb : Faza 6 (kompasos11.md) `OpenShiftMarketUseCase`-i qurur. Bazarın
--         iki ədədi var — elanın nə qədər irəli verilə biləcəyi və bir
--         işçinin ayda neçə elan tuta biləcəyi. MƏRKƏZİ TƏLƏBƏ görə
--         (hər şey ROOT-dan idarə olunur) heç biri koda hardcode edilə
--         bilməz. `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py)
--         onları artıq elan edir — bu miqrasiya həmin açarları
--         `system_limits`-ə SEED edir ki, ROOT İdarə Mərkəzi ekranında
--         GÖRÜNSÜNLƏR (migrations/022–026 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun, indeks və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir.
-- `open_shift_postings` cədvəlinin ÖZÜ artıq migrations/019-dadır — ora
-- toxunulmur (o cümlədən "ilk basan qazanır" trigger-i və üç unikal indeksi).
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ SEED LAZIMDIR — `DEFAULT_LIMITS` NİYƏ KİFAYƏT ETMİR
-- ---------------------------------------------------------------------------
-- Kod tərəfi `SystemLimits.get_int(tenant, key, default)` işlədir, yəni sətir
-- olmasa da bazar DOĞRU dəyərlərlə işləyir — funksional qüsur YOXDUR. Lakin
-- ROOT paneli `describe()` ilə `system_limits` cədvəlini oxuyur: seed
-- edilməmiş açar orada ÜMUMİYYƏTLƏ görünmür və Root onu dəyişə bilmir. Yəni
-- parametr "konfiqurasiya edilə bilən" olmaqdan çıxıb sükutla sabitə
-- çevrilərdi (migrations/022–026 eyni boşluğu bağlamışdı).
--
-- ---------------------------------------------------------------------------
-- NİYƏ FEATURE TOGGLE SƏTRİ ƏLAVƏ EDİLMİR
-- ---------------------------------------------------------------------------
-- Açıq bazar YENİ modul açarı YARATMIR — mövcud `SHIFT_SWAP` açarını
-- işlədir (bax `application/use_cases/open_shift_market.py` başlığı):
-- hər ikisi işçi-tərəfi növbə self-service-idir və layihə həmin açarı artıq
-- "Növbə planlaması və dəyişmə" ÇƏTİRİ kimi işlədir
-- (`controllers/screen_data.HELP_TOPIC_MODULES`). Ayrıca açar əlavə etsəydik,
-- Root iki düymə görərdi və birini söndürüb digərinin açıq qaldığını gec
-- fərq edərdi.
--
-- ---------------------------------------------------------------------------
-- `min_value` / `max_value` NİYƏ BU HÜDUDLARDADIR
-- ---------------------------------------------------------------------------
--   * OPEN_SHIFT_MAX_LEAD_DAYS (1–90): 0 QƏSDƏN İSTİSNA EDİLİB — sıfır gün
--     "yalnız bu gün üçün elan" deməkdir və axşam növbəsini səhər elan etmək
--     imkanını da kəsərdi. Yuxarı hüdud 90-dır: Növbə Dəyişmə sorğusunun
--     pəncərəsi ilə eyni tavan (`shift_scheduling.MAX_SWAP_LEAD_DAYS`) —
--     ondan uzağı planlaşdırma işidir, bazar işi deyil.
--   * OPEN_SHIFT_MAX_CLAIMS_PER_MONTH (1–31): 0 istisna edilib, çünki sıfır
--     tavan bazarı tamamilə söndürərdi və bunun ÜÇÜN Feature Toggle var —
--     limit ilə modul söndürmək gizli, izahsız davranış olardı. Tavan 31-dir:
--     bir işçi eyni günə yalnız BİR elan tuta bilir (migrations/019
--     `uq_open_shift_one_claim_per_employee_day`), yəni ayda mümkün maksimum
--     ayın gün sayıdır.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–026 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('OPEN_SHIFT_MAX_LEAD_DAYS', '30', 'INTEGER', '1', '90',
     '#16 — Açıq növbə elanı ən çox neçə gün irəli üçün verilə bilər'),
    ('OPEN_SHIFT_MAX_CLAIMS_PER_MONTH', '8', 'INTEGER', '1', '31',
     '#16 — Bir işçinin bir təqvim ayında götürə biləcəyi açıq növbə sayı')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–026-dakı naxış təkrarlanır: yeni kirayəçi
-- yarananda bu iki sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_open_shift_market_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'OPEN_SHIFT_MAX_LEAD_DAYS', '30', 'INTEGER', '1', '90',
         '#16 — Açıq növbə elanı ən çox neçə gün irəli üçün verilə bilər'),
        (NEW.tenant_id, 'OPEN_SHIFT_MAX_CLAIMS_PER_MONTH', '8', 'INTEGER', '1', '31',
         '#16 — Bir işçinin bir təqvim ayında götürə biləcəyi açıq növbə sayı')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_open_shift_market_limits_for_new_tenant() IS
    'Yeni kirayəçiyə Açıq Növbə Bazarının iki ROOT parametrini əlavə edir '
    '(migrations/027). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_open_shift_market_limits ON license_tenants;
CREATE TRIGGER trg_seed_open_shift_market_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_open_shift_market_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir; bazar
-- işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə — yəni Root
-- onları artıq dəyişdirə bilmir. Mövcud elanlara TƏSİRİ YOXDUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_open_shift_market_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_open_shift_market_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'OPEN_SHIFT_MAX_LEAD_DAYS', 'OPEN_SHIFT_MAX_CLAIMS_PER_MONTH'
--   );
-- COMMIT;
