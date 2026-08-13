-- ===========================================================================
-- 024 — #8 İŞÇİ DAVRANIŞ BAZ XƏTTİNİN ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-12
-- Səbəb : Faza 5 (kompasos11.md) `BehaviorBaselineUseCase` və
--         `BehaviorAnomalyRule`-u qurur. Dörd davranış parametri var və
--         MƏRKƏZİ TƏLƏBƏ görə (hər şey ROOT-dan idarə olunur) heç biri koda
--         hardcode edilə bilməz. `SystemLimitKey` + `DEFAULT_LIMITS`
--         (src/domain/policies.py) onları artıq elan edir — bu miqrasiya
--         həmin açarları `system_limits`-ə SEED edir ki, ROOT İdarə Mərkəzi
--         ekranında GÖRÜNSÜNLƏR (miqrasiya 022/023 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir.
-- `employee_behavior_baseline` cədvəlinin ÖZÜ artıq migrations/018-dədir.
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ SEED LAZIMDIR — `DEFAULT_LIMITS` NİYƏ KİFAYƏT ETMİR
-- ---------------------------------------------------------------------------
-- Kod tərəfi `SystemLimits.get_int/get_str(tenant, key, default)` işlədir,
-- yəni sətir olmasa da hesablama/qayda DOĞRU dəyərlə işləyir — funksional
-- qüsur YOXDUR. Lakin ROOT paneli `describe()` ilə `system_limits` cədvəlini
-- oxuyur: seed edilməmiş açar orada ÜMUMİYYƏTLƏ görünmür və Root onu dəyişə
-- bilmir. Yəni parametr "konfiqurasiya edilə bilən" olmaqdan çıxıb sükutla
-- sabitə çevrilərdi (miqrasiya 022/023 eyni boşluğu bağlamışdı).
--
-- ---------------------------------------------------------------------------
-- `min_value` / `max_value` NİYƏ BU HÜDUDLARDADIR
-- ---------------------------------------------------------------------------
--   * BEHAVIOR_BASELINE_WINDOW_DAYS (7–90): 7-dən az pəncərə statistik
--     cəhətdən mənasızdır (bir iş həftəsi belə deyil); 90-dan çox isə köhnə
--     davranışı bugünkü ilə qarışdırar (işçinin son 3 ay ərzində dəyişən
--     adətini "orta"ya endirər).
--   * BEHAVIOR_ANOMALY_THRESHOLD_MINUTES (5–240): 5 dəqiqədən az hədd HƏR
--     GÜN adi trafik dalğalanmasını "anomaliya" elan edərdi; 240 (4 saat)
--     TAVANDIR — ondan yuxarısı artıq "sapma" yox, "başqa növbə" deməkdir.
--   * BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE (1–90): 0 QƏSDƏN İSTİSNA EDİLİB —
--     "sıfır müşahidədən baz xətt" mənasızdır; 1 ən aşağı, pəncərənin
--     maksimum uzunluğu (90) isə təbii yuxarı tavandır.
--   * BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER (0.5–5.0): 0.5-dən aşağı demək olar
--     ki, HƏR sapmanı eskalasiya edərdi (statistik mənasını itirər); 5.0-dan
--     yuxarı isə praktik olaraq HEÇ VAXT işə düşməzdi (normal paylanmada
--     5σ hadisəsi milyonda bir).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022/023 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('BEHAVIOR_BASELINE_WINDOW_DAYS', '30', 'INTEGER', '7', '90',
     '#8 — Davranış baz xəttinin hesablandığı gün sayı (son N gün)'),
    ('BEHAVIOR_ANOMALY_THRESHOLD_MINUTES', '45', 'INTEGER', '5', '240',
     '#8 — Bugünkü check-in baz xəttindən neçə dəqiqə sapanda anomaliya '
     'elan edilsin'),
    ('BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE', '5', 'INTEGER', '1', '90',
     '#8 — Anomaliya elan edilməzdən əvvəl baz xəttin minimum neçə günlük '
     'müşahidəyə əsaslanmalı olduğu (az nümunə = yanlış ittiham riski)'),
    ('BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER', '2.0', 'DECIMAL', '0.5', '5.0',
     '#8 — Sapma işçinin öz standart kənarlaşmasının neçə qatını keçəndə '
     'ciddiyyət bir pillə yuxarı qalxsın (statistik "adi deyil" həddi)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022/023-dəki naxış təkrarlanır: yeni kirayəçi
-- yarananda bu dörd sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_behavior_baseline_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'BEHAVIOR_BASELINE_WINDOW_DAYS', '30', 'INTEGER', '7', '90',
         '#8 — Davranış baz xəttinin hesablandığı gün sayı (son N gün)'),
        (NEW.tenant_id, 'BEHAVIOR_ANOMALY_THRESHOLD_MINUTES', '45', 'INTEGER', '5', '240',
         '#8 — Bugünkü check-in baz xəttindən neçə dəqiqə sapanda anomaliya '
         'elan edilsin'),
        (NEW.tenant_id, 'BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE', '5', 'INTEGER', '1', '90',
         '#8 — Anomaliya elan edilməzdən əvvəl baz xəttin minimum neçə günlük '
         'müşahidəyə əsaslanmalı olduğu'),
        (NEW.tenant_id, 'BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER', '2.0', 'DECIMAL', '0.5', '5.0',
         '#8 — Sapma işçinin öz standart kənarlaşmasının neçə qatını keçəndə '
         'ciddiyyət bir pillə yuxarı qalxsın')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_behavior_baseline_limits_for_new_tenant() IS
    'Yeni kirayəçiyə İşçi Davranış Baz Xəttinin dörd ROOT parametrini əlavə '
    'edir (migrations/024). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_behavior_baseline_limits ON license_tenants;
CREATE TRIGGER trg_seed_behavior_baseline_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_behavior_baseline_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir;
-- hesablama/qayda işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə
-- — yəni Root onları artıq dəyişdirə bilmir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_behavior_baseline_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_behavior_baseline_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'BEHAVIOR_BASELINE_WINDOW_DAYS', 'BEHAVIOR_ANOMALY_THRESHOLD_MINUTES',
--       'BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE', 'BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER'
--   );
-- COMMIT;
