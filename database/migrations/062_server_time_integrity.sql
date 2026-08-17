-- ===========================================================================
-- 062 — SERVER-ƏSASLI VAXT BÜTÖVLÜYÜ (TIME-1)
-- ===========================================================================
-- Tarix : 2026-08-17
-- Səbəb : Bütün davamiyyət məntiqi (gecikmə dəqiqələri → cərimə, 45 dəqiqəlik
--         timeout, 72 saatlıq etiraz pəncərəsi) vaxt-möhürlərinə əsaslanır.
--         Həmin möhürlərin bir qismini TƏTBİQ göndərirdi, yəni mağaza PC-sinin
--         Windows saatı onlara birbaşa təsir edirdi. Saatı 20 dəqiqə geri
--         çəkmək = gecikməni və cəriməni silmək.
--
-- ---------------------------------------------------------------------------
-- `DEFAULT now()` TƏK BAŞINA KİFAYƏT ETMİRDİ — NİYƏ
-- ---------------------------------------------------------------------------
-- Sxemdə 60, miqrasiyalarda 67 sütun ARTIQ `DEFAULT now()` daşıyır. Lakin
-- default YALNIZ sütun `INSERT`-də ADI ÇƏKİLMƏDİKDƏ işləyir. Repozitoriyaların
-- bir qismi (`announcement_repository`, `annual_leave_repository`,
-- `catalog_repositories`, `open_shift_repository`, ...) `created_at`-ı AÇIQ
-- göndərir — yəni server defoltu sükutla yan keçilirdi. Bu, kodu oxuyanda
-- görünmürdü: sütunun tərifi «server vaxtı» vəd edirdi, faktiki dəyər isə
-- client-dən gəlirdi.
--
-- Trigger defoltdan GÜCLÜDÜR: sütunun adı çəkilsə belə dəyəri əvəz edir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ YALNIZ `created_at` — BİZNES VAXTLARI NİYƏ TOXUNULMUR
-- ---------------------------------------------------------------------------
-- İki fərqli sual var və onları qarışdırmaq qüsur olardı:
--
--     created_at, published_at  →  «sistem bunu NƏ VAXT qeydə aldı»
--     requested_at, verified_at →  «hadisə NƏ VAXT baş verdi»
--
-- Birincisi HƏMİŞƏ «indi»dir — client dəyərinin legitim səbəbi YOXDUR, ona
-- görə trigger onu şərtsiz əvəz edir.
--
-- İkincisi normalda da «indi»dir, LAKİN icazəli istisnası var:
-- `can_override_return_time` flag-i məhz vaxtı əl ilə düzəltmək üçündür
-- (kamera nasazlığı, işçi qayıtdı amma operator yox idi). Trigger onları da
-- əvəz etsəydi, həmin — audit-lənən və qəsdən mövcud olan — imkan sükutla
-- ölərdi. Onların qorunması BAŞQA yoldadır: tətbiq artıq `Clock` portundan
-- oxuyur və port indi SERVER LÖVBƏRLİDİR (`timekeeping/server_time.py`),
-- yəni Windows saatını dəyişmək onlara da təsir etmir.
--
-- ---------------------------------------------------------------------------
-- `time_trust_level` — QEYD ÖZ VAXTININ MƏNBƏYİNİ DAŞIYIR
-- ---------------------------------------------------------------------------
-- Oflayn yaranan qeydin vaxtı monotonic saatla uzadılır və dəqiq deyil. Bunu
-- sonradan təxmin etmək mümkün olmazdı, ona görə səviyyə qeydin ÖZÜNDƏ
-- saxlanılır. Mübahisə halında «bu möhür server ilə təsdiqlənib» ilə «bu möhür
-- 6 saat oflayn qalmış PC-nin təxminidir» arasındakı fərq sənədin dəyərini
-- müəyyən edir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- min/max dəyərləri `src/infrastructure/config/limits.py::INFRA_LIMIT_BOUNDS`
-- ilə HƏRFƏN eynidir; `test_infrastructure_root_limits.py` pariteti qapı kimi
-- yoxlayır (iki mənbənin ayrılması ROOT ekranında «qəbul edildi» görünən,
-- kodda isə kəsilən dəyər deməkdir).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('SERVER_TIME_SYNC_INTERVAL_SECONDS', '300', 'INTEGER', '30', '86400',
     'Server vaxtının nə qədər tez-tez soruşulması (saniyə)'),
    ('SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS', '14400', 'INTEGER', '300', '604800',
     'Server ilə əlaqəsiz qalındıqda vaxtın etibarlı sayıldığı maksimum müddət (saniyə)'),
    ('LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS', '60', 'INTEGER', '5', '3600',
     'PC saatının server vaxtından icazə verilən maksimum fərqi (saniyə)'),
    ('LOCAL_CLOCK_MANIPULATION_NOTIFY', '1', 'INTEGER', '0', '1',
     'Saat manipulyasiyası aşkarlananda HR_Admin-ə bildiriş göndərilsinmi (1/0)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR (034/060 NAXIŞI)
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` TOXUNULMUR: hər miqrasiyanın öz açarlarını ora
-- yazması həmin faylı zamanla bütün miqrasiyaların yığınına çevirərdi.
-- Sətir formatı 1-ci bloka HƏRFƏN eynidir (`('AÇAR', 'dəyər', ...)`) —
-- `NEW.tenant_id` tuple-ın İÇİNƏ yazılmır, `SELECT`-ə çıxarılır. Bu, 032-nin
-- naxışıdır və qəsdəndir: `test_migration_seeds_both_existing_and_new_tenants_
-- identically` iki bloku məhz bu formatı sayaraq tutuşdurur. Format ayrılsaydı,
-- qapı «açar trigger-də yoxdur» deyə yanlış siqnal verərdi.
CREATE OR REPLACE FUNCTION seed_server_time_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('SERVER_TIME_SYNC_INTERVAL_SECONDS', '300', 'INTEGER', '30', '86400',
         'Server vaxtının nə qədər tez-tez soruşulması (saniyə)'),
        ('SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS', '14400', 'INTEGER', '300', '604800',
         'Server ilə əlaqəsiz qalındıqda vaxtın etibarlı sayıldığı maksimum müddət (saniyə)'),
        ('LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS', '60', 'INTEGER', '5', '3600',
         'PC saatının server vaxtından icazə verilən maksimum fərqi (saniyə)'),
        ('LOCAL_CLOCK_MANIPULATION_NOTIFY', '1', 'INTEGER', '0', '1',
         'Saat manipulyasiyası aşkarlananda HR_Admin-ə bildiriş göndərilsinmi (1/0)')
      ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_server_time_limits_for_new_tenant() IS
    'Yeni kirayəçiyə server-vaxtı parametrlərini əlavə edir (migrations/062).';

DROP TRIGGER IF EXISTS trg_seed_server_time_limits ON license_tenants;
CREATE TRIGGER trg_seed_server_time_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_server_time_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- 3. `created_at` SERVER VAXTINA MƏCBUR EDİLİR
-- ---------------------------------------------------------------------------
-- Funksiya cədvəl adını TANIMIR: `NEW.created_at` plpgsql-də icra anında həll
-- olunur, yəni eyni funksiya `created_at` sütunu olan HƏR cədvələ bağlana
-- bilər. Alternativ — hər cədvəl üçün ayrı funksiya — dörd eyni gövdə
-- yaradardı və beşincisi əlavə olunanda biri unudulardı.
CREATE OR REPLACE FUNCTION enforce_server_created_at()
RETURNS TRIGGER AS $$
BEGIN
    -- Şərtsiz təyinat: `IS NULL` yoxlaması qoyulsaydı, client sadəcə dəyər
    -- göndərməklə qapını yan keçərdi — halbuki qapının SƏBƏBİ məhz odur.
    NEW.created_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_server_created_at() IS
    'INSERT anında `created_at`-ı Postgres server vaxtı ilə əvəz edir '
    '(migrations/062). `DEFAULT now()`-dan güclüdür: sütunun adı açıq '
    'çəkilsə belə client dəyəri qəbul edilmir.';

DROP TRIGGER IF EXISTS trg_server_created_at_fines ON fines;
CREATE TRIGGER trg_server_created_at_fines
    BEFORE INSERT ON fines
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

DROP TRIGGER IF EXISTS trg_server_created_at_fine_appeals ON fine_appeals;
CREATE TRIGGER trg_server_created_at_fine_appeals
    BEFORE INSERT ON fine_appeals
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

DROP TRIGGER IF EXISTS trg_server_created_at_leave_requests ON leave_requests;
CREATE TRIGGER trg_server_created_at_leave_requests
    BEFORE INSERT ON leave_requests
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

DROP TRIGGER IF EXISTS trg_server_created_at_attendance ON attendance_records;
CREATE TRIGGER trg_server_created_at_attendance
    BEFORE INSERT ON attendance_records
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

-- ---------------------------------------------------------------------------
-- 4. `fines.published_at` — ETİRAZ PƏNCƏRƏSİNİN LÖVBƏRİ
-- ---------------------------------------------------------------------------
-- 72 saatlıq etiraz pəncərəsi `created_at`-dan DEYİL, `published_at`-dan
-- hesablanır (bax `schema.sql` `fines` şərhi). Yəni manipulyasiya üçün ƏSL
-- hədəf odur: nəşr anını irəli çəkmək işçinin etiraz hüququnu qısaldardı.
--
-- Yalnız NULL → NOT NULL keçidində möhürlənir. Hər UPDATE-də təyin etsəydik,
-- geri-qaytarma (`reversed_at`) və ya digər sonrakı redaktə pəncərəni
-- SÜRÜŞDÜRƏRDİ — halbuki nəşr anı bir dəfə baş verir.
CREATE OR REPLACE FUNCTION enforce_server_published_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.published_at IS NOT NULL AND OLD.published_at IS NULL THEN
        NEW.published_at := now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_server_published_at() IS
    'Cərimənin nəşr anını server vaxtı ilə möhürləyir (migrations/062). '
    '72 saatlıq etiraz pəncərəsi bu andan hesablanır.';

DROP TRIGGER IF EXISTS trg_server_published_at_fines ON fines;
CREATE TRIGGER trg_server_published_at_fines
    BEFORE UPDATE ON fines
    FOR EACH ROW EXECUTE FUNCTION enforce_server_published_at();

-- ---------------------------------------------------------------------------
-- 5. `attendance_records.time_trust_level` — VAXTIN MƏNBƏYİ QEYDDƏ QALIR
-- ---------------------------------------------------------------------------
-- Defolt `SERVER_VERIFIED`: mövcud sətirlər onlayn yaranıb (oflayn buferin
-- «təxmini vaxt» işarəsi bu miqrasiya ilə YENİ gəlir), ona görə onları
-- şübhəli kimi göstərmək yanlış olardı.
ALTER TABLE attendance_records
    ADD COLUMN IF NOT EXISTS time_trust_level TEXT NOT NULL DEFAULT 'SERVER_VERIFIED';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_attendance_time_trust_level'
    ) THEN
        ALTER TABLE attendance_records
            ADD CONSTRAINT chk_attendance_time_trust_level
            CHECK (time_trust_level IN ('SERVER_VERIFIED', 'MONOTONIC_ESTIMATE', 'UNTRUSTED'));
    END IF;
END $$;

COMMENT ON COLUMN attendance_records.time_trust_level IS
    'Bu sətrin vaxt-möhürünün mənbəyi (migrations/062, TIME-1). '
    'SERVER_VERIFIED = təzə server lövbəri; MONOTONIC_ESTIMATE = oflayn, '
    'Root həddi daxilində; UNTRUSTED = oflayn müddət həddi aşıb. '
    'Dəyərlər `domain/value_objects/time_integrity.py::TimeTrustLevel` ilə eynidir.';

-- Yalnız şübhəli sətirlər üçün qismən indeks: HR_Admin ekranı məhz onları
-- soruşur və tam indeks cədvəlin 99%-ni əbəs saxlayardı.
CREATE INDEX IF NOT EXISTS idx_attendance_time_trust_suspect
    ON attendance_records (tenant_id, work_date DESC)
    WHERE time_trust_level <> 'SERVER_VERIFIED';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Trigger-lərin silinməsi vaxt-möhürlərini yenidən client-in ixtiyarına
-- verər — yəni miqrasiyanın bağladığı qapını AÇAR. Yalnız miqrasiyanın
-- özündə qüsur aşkarlandıqda mənalıdır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_server_published_at_fines ON fines;
--   DROP TRIGGER IF EXISTS trg_server_created_at_attendance ON attendance_records;
--   DROP TRIGGER IF EXISTS trg_server_created_at_leave_requests ON leave_requests;
--   DROP TRIGGER IF EXISTS trg_server_created_at_fine_appeals ON fine_appeals;
--   DROP TRIGGER IF EXISTS trg_server_created_at_fines ON fines;
--   DROP FUNCTION IF EXISTS enforce_server_published_at();
--   DROP FUNCTION IF EXISTS enforce_server_created_at();
--   DROP INDEX IF EXISTS idx_attendance_time_trust_suspect;
--   ALTER TABLE attendance_records DROP CONSTRAINT IF EXISTS chk_attendance_time_trust_level;
--   ALTER TABLE attendance_records DROP COLUMN IF EXISTS time_trust_level;
--   DROP TRIGGER IF EXISTS trg_seed_server_time_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_server_time_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'SERVER_TIME_SYNC_INTERVAL_SECONDS', 'SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS',
--       'LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS', 'LOCAL_CLOCK_MANIPULATION_NOTIFY');
-- COMMIT;
