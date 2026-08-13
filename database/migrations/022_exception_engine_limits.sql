-- ===========================================================================
-- 022 — VAHİD İSTİSNA MOTORUNUN ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-11
-- Səbəb : Faza 3 (kompasos11.md) `ExceptionEngineUseCase`-i qurur. Motorun
--         DÖRD davranış parametri var və MƏRKƏZİ TƏLƏBƏ görə (hər şey
--         ROOT-dan idarə olunur) heç biri koda hardcode edilə bilməz.
--         `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py) onları
--         artıq elan edir — bu miqrasiya həmin açarları `system_limits`-ə
--         SEED edir ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜNLƏR.
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
-- Kod tərəfi `SystemLimits.get_int(tenant, key, default)` işlədir, yəni sətir
-- olmasa da motor DOĞRU dəyərlə işləyir — funksional qüsur YOXDUR. Lakin ROOT
-- paneli `describe()` ilə `system_limits` cədvəlini oxuyur: seed edilməmiş
-- açar orada ÜMUMİYYƏTLƏ görünmür və Root onu dəyişə bilmir. Yəni parametr
-- "konfiqurasiya edilə bilən" olmaqdan çıxıb sükutla sabitə çevrilərdi —
-- miqrasiya 013 eyni boşluğu BR-001/BR-002 açarları üçün bağlamışdı.
--
-- ---------------------------------------------------------------------------
-- `min_value` / `max_value` NİYƏ BU HÜDUDLARDADIR
-- ---------------------------------------------------------------------------
--   * EXCEPTION_PAGE_SIZE (10–1000): 10-dan aşağı səhifə ekranı istifadəsiz
--     edir; 1000-dən yuxarı isə 21 filialın açıq növbəsini bir sorğuda
--     çəkərək örtüyü dondurar.
--   * EXCEPTION_MAX_FINDINGS_PER_RULE (1–5000): TAVAN, hədəf deyil. Qüsurlu
--     qayda minlərlə sətir yarada bilər və `exceptions`-da `REVOKE DELETE`
--     olduğu üçün onları təmizləmək MÜMKÜN DEYİL (migrations/018). Aşağı
--     hüdud 1-dir — 0 aşkarlamanı tamamilə söndürərdi və bunun düzgün yolu
--     `exception_sources.is_active = FALSE`-dır.
--   * EXCEPTION_NOTIFY_MIN_SEVERITY: mətn açarıdır, `min/max` mənasızdır
--     (NULL). Naməlum dəyər kodda sükutla defolta düşür — Root-un yazı səhvi
--     gecəlik aşkarlamanı çökdürməməlidir.
--   * EXCEPTION_REVIEW_NOTE_MIN_LENGTH (0–500): 0 = izah məcburi deyil.
--     Defolt 10 `fine_appeals`-dakı qərar izahı ilə eynidir — eyni suala
--     ("niyə belə qərar verdin?") iki fərqli standart qoymaq çaşdırıcı olardı.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('EXCEPTION_PAGE_SIZE', '200', 'INTEGER', '10', '1000',
     '«İstisnalar» ekranının bir dəfəyə oxuduğu sətir sayı'),
    ('EXCEPTION_MAX_FINDINGS_PER_RULE', '500', 'INTEGER', '1', '5000',
     'Bir qaydanın bir icrada yarada biləcəyi maksimum istisna sayı '
     '(qüsurlu qaydaya qarşı tavan — istisna sətirləri SİLİNMİR)'),
    ('EXCEPTION_NOTIFY_MIN_SEVERITY', 'HIGH', 'TEXT', NULL, NULL,
     'Bu ciddiyyətdən (daxil olmaqla) yuxarı istisna dərhal bildiriş doğurur: '
     'LOW / MEDIUM / HIGH / CRITICAL'),
    ('EXCEPTION_REVIEW_NOTE_MIN_LENGTH', '10', 'INTEGER', '0', '500',
     'İstisna qərarı (xüsusilə «Rədd Et») üçün minimum izah uzunluğu')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013-dəki `trg_seed_br_limits` naxışı təkrarlanır: yeni
-- kirayəçi yarananda bu dörd sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_exception_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'EXCEPTION_PAGE_SIZE', '200', 'INTEGER', '10', '1000',
         '«İstisnalar» ekranının bir dəfəyə oxuduğu sətir sayı'),
        (NEW.tenant_id, 'EXCEPTION_MAX_FINDINGS_PER_RULE', '500', 'INTEGER', '1', '5000',
         'Bir qaydanın bir icrada yarada biləcəyi maksimum istisna sayı'),
        (NEW.tenant_id, 'EXCEPTION_NOTIFY_MIN_SEVERITY', 'HIGH', 'TEXT', NULL, NULL,
         'Bu ciddiyyətdən yuxarı istisna dərhal bildiriş doğurur'),
        (NEW.tenant_id, 'EXCEPTION_REVIEW_NOTE_MIN_LENGTH', '10', 'INTEGER', '0', '500',
         'İstisna qərarı üçün minimum izah uzunluğu')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_exception_limits_for_new_tenant() IS
    'Yeni kirayəçiyə Vahid İstisna Motorunun dörd ROOT parametrini əlavə edir '
    '(migrations/022). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_exception_limits ON license_tenants;
CREATE TRIGGER trg_seed_exception_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_exception_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir; motor
-- işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə — yəni Root onları
-- artıq dəyişdirə bilmir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_exception_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_exception_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'EXCEPTION_PAGE_SIZE', 'EXCEPTION_MAX_FINDINGS_PER_RULE',
--       'EXCEPTION_NOTIFY_MIN_SEVERITY', 'EXCEPTION_REVIEW_NOTE_MIN_LENGTH'
--   );
-- COMMIT;
