-- ===========================================================================
-- 042 — PLANLAŞDIRILMIŞ İCRA XÜLASƏSİNİN (#30) ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `kompas1.md` Faza 6 — icra xülasəsi BACKEND-i (`src/application/
--         use_cases/executive_digest.py`) üç konfiqurasiya dəyəri işlədir.
--         `SystemLimitKey` + `DEFAULT_LIMITS` artıq elan edilib
--         (`src/domain/policies.py`); bu miqrasiya həmin açarları
--         `system_limits`-ə yazır ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜNLƏR.
--
--         Seed edilməyən açar "konfiqurasiya edilə bilən" görünər, faktiki
--         olaraq isə kodda oturan fallback işləyərdi — `tests/unit/
--         test_root_control_parameter_parity.py` bu boşluğu QAPIYA çevirib
--         (`migrations/039`/`040`/`041` ilə eyni əsaslandırma).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
-- MÖVCUD CƏDVƏLLƏRƏ TOXUNULMUR: bu miqrasiya SIRF YALNIZ `system_limits`
-- seed-idir — `executive_digest_config` cədvəli ARTIQ `migrations/037`-də,
-- icazə flag-i (`can_configure_executive_digest`) isə `038`-də qurulub.
--
-- ---------------------------------------------------------------------------
-- NİYƏ CƏMİ ÜÇ AÇAR — "TEZLİK" VƏ "METRİKLƏR" NİYƏ BURADA SƏTİR-SƏTİR YOXDUR
-- ---------------------------------------------------------------------------
-- `kompas1.md` "tezlik"i və "daxil olan metrikləri" ROOT PARAMETRİ adlandırır,
-- LAKİN FAKTİKİ seçim (hansı ROLA, hansı TEZLİKDƏ, hansı METRİKLƏRLƏ) artıq
-- `executive_digest_config` sətrindədir (`migrations/037`) — Root onu ORADA
-- REDAKTƏ edir (`ExecutiveDigestUseCase.configure`), sistem_limits-də İKİNCİ
-- nüsxəsi YARADILMIR (iki həqiqət mənbəyi qüsuru olardı, ətraflı əsaslandırma
-- `src/domain/value_objects/executive_digest.py` başlığındadır).
--
-- Bu miqrasiyanın üç açarı YALNIZ cədvəldə SÜTUNU OLMAYAN siyasətdir:
--   * `EXECUTIVE_DIGEST_DEFAULT_FREQUENCY` — yeni sətir yaradılanda tezlik
--     AÇIQ verilməzsə tətbiq olunan defolt (BR-001-dəki `LEAVE_ALLOWANCE_
--     SOURCE` ilə EYNİ "defolt mənbə konfiqurasiya edilir" naxışı).
--   * `EXECUTIVE_DIGEST_METRIC_CATALOG` — toggle-lənə bilən metrik açarlarının
--     TAM SİYAHISI (kirayəçiyə TƏK dəyər); `metrics_included` isə HƏR sətrin
--     bu siyahıdan seçdiyi ALT-ÇOXLUQDUR.
--   * `EXECUTIVE_DIGEST_WEEKLY_WEEKDAY` — `JobCadence`-də `WEEKLY` yoxdur
--     (`job_runner.py` başlığı), ona görə HƏFTƏLİK xülasənin HANSI gün
--     göndəriləcəyini planlayıcı BUNDAN oxuyur (bax `executive_digest.py::
--     _due_window`).
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ---------------------------------------------------------------------------
--   * `EXECUTIVE_DIGEST_WEEKLY_WEEKDAY` 1–7 — ISO həftə günü tərifinin ÖZÜ
--     (1=Bazar ertəsi, 7=Bazar); bu, sxem sərhədi DEYİL (sütun yoxdur),
--     LAKİN TƏQVİMİN ÖZÜNÜN sərhədidir — 0 və ya 8 mənasız gündür.
--   * `EXECUTIVE_DIGEST_DEFAULT_FREQUENCY`/`EXECUTIVE_DIGEST_METRIC_CATALOG`
--     üçün `min_value`/`max_value` YOXDUR (`NULL`) — hər ikisi MƏTNDİR,
--     `LEAVE_ALLOWANCE_SOURCE`/`EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` ilə
--     EYNİ qərar (ədədi hüdud mənasızdır).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (`039`/`040`/`041` ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('EXECUTIVE_DIGEST_DEFAULT_FREQUENCY', 'DAILY', 'TEXT', NULL, NULL,
     'Yeni icra xülasəsi konfiqurasiyası tezlik seçilmədən yaradılanda tətbiq '
     'olunan defolt (DAILY/WEEKLY). Mövcud konfiqurasiyaların tezliyinə '
     'TƏSİR ETMİR — o, `executive_digest_config.frequency` sütunundadır'),
    ('EXECUTIVE_DIGEST_METRIC_CATALOG', 'FINE_COUNT,OPEN_EXCEPTION_COUNT,'
     'LATE_CHECK_IN_COUNT,OVERTIME_HOURS,TURNOVER_RISK', 'TEXT', NULL, NULL,
     'Toggle-lənə bilən icra xülasəsi göstəricilərinin vergüllü kataloqu. '
     'Yeni konfiqurasiya YALNIZ bu siyahıdan metrik seçə bilər; kataloqdan '
     'çıxarılan açar MÖVCUD konfiqurasiyanı pozmur, göndərmə anında sükutla ötürülür'),
    ('EXECUTIVE_DIGEST_WEEKLY_WEEKDAY', '1', 'INTEGER', '1', '7',
     'Həftəlik tezlikli icra xülasəsinin göndərildiyi ISO həftə günü '
     '(1=Bazar ertəsi..7=Bazar). Planlayıcıda ayrıca HƏFTƏLİK slot yoxdur '
     '(yalnız DAILY/HOURLY) — bu dəyər gündəlik yoxlama dövrəsinin '
     '"bu gün həftəlik göndəriş günüdürmü?" sualını cavablandırır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039/040/041-dəki naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_executive_digest_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'EXECUTIVE_DIGEST_DEFAULT_FREQUENCY', 'DAILY', 'TEXT', NULL, NULL,
         'Yeni icra xülasəsi konfiqurasiyasının defolt tezliyi'),
        (NEW.tenant_id, 'EXECUTIVE_DIGEST_METRIC_CATALOG',
         'FINE_COUNT,OPEN_EXCEPTION_COUNT,LATE_CHECK_IN_COUNT,OVERTIME_HOURS,TURNOVER_RISK',
         'TEXT', NULL, NULL, 'Toggle-lənə bilən icra xülasəsi göstəricilərinin kataloqu'),
        (NEW.tenant_id, 'EXECUTIVE_DIGEST_WEEKLY_WEEKDAY', '1', 'INTEGER', '1', '7',
         'Həftəlik icra xülasəsinin göndərildiyi ISO həftə günü')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_executive_digest_limits_for_new_tenant() IS
    'Yeni kirayəçiyə icra xülasəsinin üç ROOT parametrini əlavə edir '
    '(migrations/042). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_executive_digest_limits ON license_tenants;
CREATE TRIGGER trg_seed_executive_digest_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_executive_digest_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlər silinsə, icra xülasəsi İŞLƏMƏYƏ DAVAM EDİR — kod
-- `DEFAULT_LIMITS` fallback-ına düşür (DAILY / beş metriklik kataloq /
-- Bazar ertəsi). İtən yeganə şey Root-un GUI-dan dəyişdirmə imkanıdır.
-- `migrations/037`-dəki `executive_digest_config` cədvəlinə VƏ `038`-dəki
-- `can_configure_executive_digest` flag-inə TOXUNULMUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_executive_digest_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_executive_digest_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'EXECUTIVE_DIGEST_DEFAULT_FREQUENCY', 'EXECUTIVE_DIGEST_METRIC_CATALOG',
--       'EXECUTIVE_DIGEST_WEEKLY_WEEKDAY');
-- COMMIT;
