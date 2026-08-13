-- ===========================================================================
-- 031 — #24 ÇOX-MAĞAZA BENCHMARK DASHBOARD-UN ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : Faza 9A (kompasos11.md) Dashboard Builder-ə dörd yeni widget tipi
--         (`ranking_table`, `store_vs_network`, `metric_trend`, `benchmark_
--         outliers`) əlavə edir. İKİ ədəd (trend ay sayı + outlier σ həddi)
--         MƏRKƏZİ TƏLƏBƏ görə (kompasos11.md #24: "6 ay/2σ hardcode
--         edilməməlidir") koda yazıla bilməz. `SystemLimitKey` + `DEFAULT_
--         LIMITS` (src/domain/policies.py) artıq açarları elan edir — bu
--         miqrasiya onları `system_limits`-ə SEED edir ki, ROOT İdarə
--         Mərkəzi ekranında GÖRÜNSÜNLƏR (migrations/022–030 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun, indeks və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir. Benchmark widget-ləri
-- YENİ CƏDVƏL TƏLƏB ETMİR — mövcud `fines`/`daily_attendance_sheet_lines`/
-- `points_ledger`/`overtime_log`/`attrition_risk_scores` cədvəllərini OXUYUR
-- (bax `infrastructure/persistence/benchmark_repository.py` başlığı).
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- İKİ AÇAR — NİYƏ FƏRQLİ TİPLƏR
-- ---------------------------------------------------------------------------
-- `BENCHMARK_TREND_MONTHS` (1–24) SƏLİS ƏDƏDDİR — "6.5 ay" mənasızdır.
-- Yuxarı hədd `ATTRITION_WINDOW_MONTHS`/`STAFFING_PATTERN_BASED_ON_WEEKS`
-- ilə EYNİ məntiqlə seçilib: iki ildən uzun pəncərə artıq "tendensiya" DEYİL,
-- tarixi arxivdir.
--
-- `BENCHMARK_OUTLIER_SIGMA_MULTIPLIER` (0.5–5.0) `BEHAVIOR_ANOMALY_SIGMA_
-- MULTIPLIER`-in (migrations/024) EYNİ hüdudlarını təkrarlayır — statistik
-- əsaslandırma (normal paylanmanın σ-qaydası) domendən asılı deyil, yalnız
-- TƏTBİQ OLUNAN OBYEKT fərqlidir (mağaza aqreqatı, işçi baz xətti YOX).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–030 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('BENCHMARK_TREND_MONTHS', '6', 'INTEGER', '1', '24',
     '#24 — Zaman-üzrə Trend widget-inin geriyə baxdığı ay sayı'),
    ('BENCHMARK_OUTLIER_SIGMA_MULTIPLIER', '2.0', 'DECIMAL', '0.5', '5.0',
     '#24 — Kritik-Kənar kartının şəbəkə ortalamasından kənarlaşma həddi (σ)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–030 naxışı təkrarlanır: yeni kirayəçi yarananda
-- bu iki sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_multi_store_benchmark_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'BENCHMARK_TREND_MONTHS', '6', 'INTEGER', '1', '24',
         '#24 — Zaman-üzrə Trend widget-inin geriyə baxdığı ay sayı'),
        (NEW.tenant_id, 'BENCHMARK_OUTLIER_SIGMA_MULTIPLIER', '2.0', 'DECIMAL', '0.5', '5.0',
         '#24 — Kritik-Kənar kartının şəbəkə ortalamasından kənarlaşma həddi (σ)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_multi_store_benchmark_limits_for_new_tenant() IS
    'Yeni kirayəçiyə #24-ün iki ROOT parametrini əlavə edir (migrations/031). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_multi_store_benchmark_limits ON license_tenants;
CREATE TRIGGER trg_seed_multi_store_benchmark_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_multi_store_benchmark_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir; #24
-- işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə (src/domain/
-- policies.py) — yəni Root onları artıq dəyişdirə bilmir. Benchmark
-- nəticələrinə TƏSİRİ YOXDUR (heç bir hesablanmış sətir SAXLANMIR — bu
-- widget-lər canlı sorğu ilə işləyir, tarixçə cədvəli yoxdur).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_multi_store_benchmark_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_multi_store_benchmark_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'BENCHMARK_TREND_MONTHS', 'BENCHMARK_OUTLIER_SIGMA_MULTIPLIER'
--   );
-- COMMIT;
