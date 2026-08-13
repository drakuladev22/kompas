-- ===========================================================================
-- 030 — #21 İŞDƏN ÇIXMA RİSKİ BALININ ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : Faza 9 (kompasos11.md) `AttritionRiskUseCase`-i qurur. Yeddi
--         ədəd (dörd siqnal çəkisi + pəncərə ay sayı + yeni-işçi həddi +
--         yüksək-risk həddi) MƏRKƏZİ TƏLƏBƏ görə (hər siqnalın çəkisi
--         `system_limits`-də, kod-hardcode DEYİL) koda yazıla bilməz.
--         `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py) artıq
--         açarları elan edir — bu miqrasiya onları `system_limits`-ə SEED
--         edir ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜNLƏR
--         (migrations/022–029 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun, indeks və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir. `attrition_risk_scores`
-- cədvəli ARTIQ migrations/020-dədir — ora TOXUNULMUR (o cümlədən
-- `factors_json <> '{}'` CHECK-i).
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- YEDDİ AÇAR — NİYƏ HAMISI `INTEGER`
-- ---------------------------------------------------------------------------
-- Dörd çəki (`ATTRITION_FINE_TREND_WEIGHT`, `ATTRITION_ATTENDANCE_VIOLATION_
-- WEIGHT`, `ATTRITION_NEW_HIRE_RISK_POINTS`, `ATTRITION_LEAVE_USAGE_WEIGHT`)
-- SƏLİS ƏDƏDDİR — kəsr bal (məs. "4.5") HR üçün heç bir əlavə dəqiqlik
-- vermir, əksinə ekranda "niyə 4.5?" sualı yaradardı. `min_value = 0`:
-- Root bir siqnalı SÖNDÜRMƏK istəsə (`LaborLimits` fəlsəfəsi — "sıfır = qayda
-- susur"), ayrıca Feature Toggle yaratmadan çəkini 0 qoyur. `max_value = 100`:
-- tək bir siqnalın YEKUN balı tək başına 100-ü keçməsin deyə (praktik tavan,
-- sxem sərhədi deyil — `score` sütununun CHECK-i onsuz da 0–100-dür).
--
-- `ATTRITION_WINDOW_MONTHS` (1–24) və `ATTRITION_NEW_HIRE_THRESHOLD_MONTHS`
-- (0–24): iki ildən uzun pəncərə/staj həddi artıq "cari tendensiya" DEYİL,
-- tarixi arxivdir və FINE_TREND siqnalının mənasını itirər (köhnə, artıq
-- əhəmiyyətsiz cərimələr "artım" kimi görünə bilər).
--
-- `ATTRITION_HIGH_RISK_THRESHOLD` (0–100): bal sütununun ÖZÜ ilə eyni
-- miqyasda, sxem sərhədini TƏKRARLAYIR — Root-un "bu hədddən yuxarı diqqət
-- tələb edir" qərarı üçün əlavə tavan mənasızdır.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–029 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('ATTRITION_FINE_TREND_WEIGHT', '5', 'INTEGER', '0', '100',
     '#21 — son pəncərənin sonuncu yarımında ƏLAVƏ hər cərimə üçün bal '
     '(artım, mütləq say yox)'),
    ('ATTRITION_ATTENDANCE_VIOLATION_WEIGHT', '8', 'INTEGER', '0', '100',
     '#21 — eyni pəncərədə hər icazəsiz davamiyyət pozuntusuna bal'),
    ('ATTRITION_NEW_HIRE_RISK_POINTS', '15', 'INTEGER', '0', '100',
     '#21 — staj yeni-işçi həddindən az olduqda verilən sabit bal'),
    ('ATTRITION_NEW_HIRE_THRESHOLD_MONTHS', '3', 'INTEGER', '0', '24',
     '#21 — bu neçə aydan az staj "yeni işçi" sayılır'),
    ('ATTRITION_LEAVE_USAGE_WEIGHT', '20', 'INTEGER', '0', '100',
     '#21 — aylıq icazə limitinin TAM (100%) istifadəsinə qarşılıq maksimum bal'),
    ('ATTRITION_WINDOW_MONTHS', '3', 'INTEGER', '1', '24',
     '#21 — cərimə artımı/davamiyyət pozuntusu siqnallarının baxdığı ay sayı'),
    ('ATTRITION_HIGH_RISK_THRESHOLD', '70', 'INTEGER', '0', '100',
     '#21 — bu bal həddindən (daxil) yuxarı "yüksək risk" sayılır və Store '
     'Manager → HR_Admin bildiriş zəncirini işə salır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–029-dakı naxış təkrarlanır: yeni kirayəçi
-- yarananda bu yeddi sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_attrition_risk_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'ATTRITION_FINE_TREND_WEIGHT', '5', 'INTEGER', '0', '100',
         '#21 — son pəncərənin sonuncu yarımında ƏLAVƏ hər cərimə üçün bal '
         '(artım, mütləq say yox)'),
        (NEW.tenant_id, 'ATTRITION_ATTENDANCE_VIOLATION_WEIGHT', '8', 'INTEGER', '0', '100',
         '#21 — eyni pəncərədə hər icazəsiz davamiyyət pozuntusuna bal'),
        (NEW.tenant_id, 'ATTRITION_NEW_HIRE_RISK_POINTS', '15', 'INTEGER', '0', '100',
         '#21 — staj yeni-işçi həddindən az olduqda verilən sabit bal'),
        (NEW.tenant_id, 'ATTRITION_NEW_HIRE_THRESHOLD_MONTHS', '3', 'INTEGER', '0', '24',
         '#21 — bu neçə aydan az staj "yeni işçi" sayılır'),
        (NEW.tenant_id, 'ATTRITION_LEAVE_USAGE_WEIGHT', '20', 'INTEGER', '0', '100',
         '#21 — aylıq icazə limitinin TAM (100%) istifadəsinə qarşılıq maksimum bal'),
        (NEW.tenant_id, 'ATTRITION_WINDOW_MONTHS', '3', 'INTEGER', '1', '24',
         '#21 — cərimə artımı/davamiyyət pozuntusu siqnallarının baxdığı ay sayı'),
        (NEW.tenant_id, 'ATTRITION_HIGH_RISK_THRESHOLD', '70', 'INTEGER', '0', '100',
         '#21 — bu bal həddindən (daxil) yuxarı "yüksək risk" sayılır və Store '
         'Manager → HR_Admin bildiriş zəncirini işə salır')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_attrition_risk_limits_for_new_tenant() IS
    'Yeni kirayəçiyə #21-in yeddi ROOT parametrini əlavə edir (migrations/030). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_attrition_risk_limits ON license_tenants;
CREATE TRIGGER trg_seed_attrition_risk_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_attrition_risk_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir; #21
-- işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə (src/domain/
-- policies.py) — yəni Root onları artıq dəyişdirə bilmir. Mövcud
-- `attrition_risk_scores` sətirlərinə TƏSİRİ YOXDUR (tarixçə qalır).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_attrition_risk_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_attrition_risk_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'ATTRITION_FINE_TREND_WEIGHT', 'ATTRITION_ATTENDANCE_VIOLATION_WEIGHT',
--       'ATTRITION_NEW_HIRE_RISK_POINTS', 'ATTRITION_NEW_HIRE_THRESHOLD_MONTHS',
--       'ATTRITION_LEAVE_USAGE_WEIGHT', 'ATTRITION_WINDOW_MONTHS',
--       'ATTRITION_HIGH_RISK_THRESHOLD'
--   );
-- COMMIT;
