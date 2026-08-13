-- ===========================================================================
-- 036 — TƏTBİQ-SƏVİYYƏLİ PLANLAYICI: İCARƏ CƏDVƏLİ + ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : KompasOS-un dövri işlərinin (davranış baz xətti, sənəd bitmə
--         xəbərdarlığı, turnover balı, kadr nümunəsi, gecə ehtiyat nüsxəsi,
--         köhnəlmiş cərimə təmizliyi, ödəniş xatırlatmaları) HAMISININ metodu
--         yazılıb, lakin onları çağıran mexanizm yox idi. Bu miqrasiya həmin
--         mexanizmin SAXLAMA qatını qurur.
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
-- MÖVCUD CƏDVƏLLƏRƏ TOXUNULMUR: nə sütun dəyişir, nə ad, nə tip.
--
-- ---------------------------------------------------------------------------
-- NİYƏ AD `scheduled_job_runs` DEYİL — MÖVCUD CƏDVƏLLƏ TOQQUŞMA
-- ---------------------------------------------------------------------------
-- `schema.sql` §29-da ARTIQ `scheduled_job_runs` adlı cədvəl var və o, TAM
-- BAŞQA şeydir: DB-nin ÖZ cron funksiyalarının (`run_all_scheduled_jobs()`)
-- jurnalıdır — `job_name` sütunu var, `tenant_id` YOXDUR, icarə anlayışı
-- YOXDUR. `database/tests/test_guards.sql` TEST 17 və `v_scheduled_job_health`
-- görünüşü məhz həmin cədvəli oxuyur.
--
-- Eyni adı təkrar işlətsəydik, `CREATE TABLE IF NOT EXISTS` SÜKUTLA heç nə
-- etməzdi (cədvəl onsuz da var) və tətbiq "sütun yoxdur" xətası ilə yalnız
-- İSTEHSALATDA çökərdi. Ona görə yeni cədvəl `app_` prefiksi ilə ayrılır:
--   * `scheduled_job_runs`      → DB-nin öz SQL işləri (pg_cron / xarici cron)
--   * `app_scheduled_job_runs`  → TƏTBİQİN Python işləri (bu miqrasiya)
--
-- ---------------------------------------------------------------------------
-- `UNIQUE (tenant_id, job_key, scheduled_for)` — MÜDAFİƏNİN BÜTÜN ƏSASI
-- ---------------------------------------------------------------------------
-- Sistem 21 mağazada, hər mağazada bir neçə terminalda işləyir və planlayıcı
-- HƏR terminalda var. Onların hamısı eyni gecə işini görməyə çalışır.
--
-- Tətbiq qatında "əvvəlcə oxu, sonra yaz" yoxlaması BU ŞƏRAİTDƏ UDUZUR: iki
-- terminal eyni anda "qeyd yoxdur" görür və hər ikisi işi icra edir — baz
-- xətti iki dəfə hesablanır, HR eyni sənəd üçün iki e-poçt alır. Ona görə
-- qərarı DB verir:
--
--     INSERT ... ON CONFLICT (tenant_id, job_key, scheduled_for) DO NOTHING
--
-- İki paralel `INSERT`-dən yalnız biri 1 sətir yazır; ikincisi 0 sətir alır və
-- işi ATLAYIR. Unikal indeks olmasaydı, hər ikisi yazardı və `ON CONFLICT`
-- heç vaxt işə düşməzdi — yəni bu məhdudiyyət "əlavə qoruma" deyil,
-- mexanizmin ÖZÜDÜR (#16 açıq növbə bazarındakı `uq_open_shift_one_open_per_
-- slot` ilə eyni rol).
--
-- ---------------------------------------------------------------------------
-- ÇÖKMÜŞ İNSTANSİYA — İŞ NİYƏ ƏBƏDİ "RUNNING" QALMIR
-- ---------------------------------------------------------------------------
-- İcarəni götürən terminal cərəyan kəsilməsindən çöksə, sətir `RUNNING`
-- qalır. Onu təmizləyən "canlılıq siqnalı" YOXDUR və qəsdən yoxdur: heartbeat
-- fon axını tələb edir, fon axını isə çökmüş prosesdə onsuz da işləmir.
--
-- Əvəzinə icarənin SON İSTİFADƏ TARİXİ var (`leased_until`). Vaxtı keçmiş
-- icarəni istənilən instansiya şərti `UPDATE` ilə geri götürür:
--
--     WHERE ... AND (status = 'FAILED'
--                 OR (status = 'RUNNING' AND leased_until <= now_param))
--
-- SƏRHƏD `<=`-dir: `leased_until` anında icarə ARTIQ bitmiş sayılır. `<`
-- yazılsaydı, sərhəd anında iki instansiya eyni işi "diri icarə" ilə görərdi.
-- Eyni operator kod tərəfindədir (`ScheduledJobRun.is_lease_expired`).
--
-- Beləliklə çökmə ən pis halda BİR icarə müddəti (defolt 30 dəq.) gecikməyə
-- çevrilir — əbədi dayanmaya yox.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. app_scheduled_job_runs — İCRA QEYDİ VƏ İCARƏ
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_scheduled_job_runs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,
    -- CASCADE: kirayəçi silinirsə onun fon işlərinin izinin müstəqil mənası
    -- qalmır (qeyd heç bir pul/qərar sübutu daşımır — bax `GRANT` bölməsi).

    -- Açar BÖYÜK hərflərlə saxlanılır ki, reyestrdəki ad, DB sətri və log
    -- açarı EYNİ olsun. Kod tərəfi `normalize_job_key()` ilə eyni qaydanı
    -- tətbiq edir (`exception_sources.code` ilə eyni naxış).
    job_key        TEXT NOT NULL
                       CHECK (job_key = upper(job_key)
                              AND char_length(trim(job_key)) >= 3),

    -- İcranın AİD OLDUĞU an (03:00 slotu), FAKTİKİ başlanğıc DEYİL. İkisinin
    -- ayrılması gecikmiş icranı (catch-up) görünən edir: kompüter 09:12-də
    -- açılıbsa `scheduled_for = 03:00`, `started_at = 09:12` olur və "gecə
    -- işi niyə səhər 9-da işlədi?" sualı cavablana bilir.
    scheduled_for  TIMESTAMPTZ NOT NULL,

    status         TEXT NOT NULL DEFAULT 'RUNNING'
                       CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),

    -- İcarə sahibi: hansı terminal/proses. `NOT NULL`, çünki sətir YALNIZ
    -- icarə anında yaranır — sahibsiz qeyd mümkün deyil.
    leased_by      TEXT NOT NULL CHECK (char_length(trim(leased_by)) > 0),
    leased_until   TIMESTAMPTZ NOT NULL,

    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ,

    -- Cəhd sayı 1-dən başlayır: sətir ilk icarə ilə yaranır. Tavan
    -- (`SCHEDULER_MAX_ATTEMPTS`) bu sütuna görə tətbiq olunur — tavansız
    -- planlayıcı tətbiqi ÖLDÜRƏN işi sonsuz təkrarlayardı.
    attempts       INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),

    last_error     TEXT,
    -- İşin qaytardığı qısa xülasə ("235 işçi yeniləndi"). Sağlamlıq ekranında
    -- "işlədi, amma nə etdi?" sualının cavabıdır; bu sütun olmasaydı uğurlu
    -- icra ilə "heç nə tapmayan" icra bir-birindən seçilməzdi.
    result_detail  TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- MÜDAFİƏNİN ƏSASI — bax fayl başlığı.
    UNIQUE (tenant_id, job_key, scheduled_for),

    -- Yarımçıq vəziyyət mümkün deyil: işləyən sətrin bitmə anı OLMAMALIDIR,
    -- bitmiş sətrin isə OLMALIDIR. Çökmüş instansiyanın işi geri götürüləndə
    -- `finished_at` məhz buna görə `NULL`-a qaytarılır.
    CONSTRAINT chk_job_run_finished
        CHECK ((status = 'RUNNING' AND finished_at IS NULL)
            OR (status <> 'RUNNING' AND finished_at IS NOT NULL)),
    -- Uğursuzluq SƏBƏBSİZ yazıla bilməz: "FAILED, səbəb naməlum" sətri
    -- diaqnostikanı tam dayandırar və növbəti gecə eyni qüsur təkrarlanardı.
    CONSTRAINT chk_job_run_error
        CHECK (status <> 'FAILED' OR (last_error IS NOT NULL
                                      AND char_length(trim(last_error)) > 0))
);

DROP TRIGGER IF EXISTS trg_app_job_runs_updated ON app_scheduled_job_runs;
CREATE TRIGGER trg_app_job_runs_updated BEFORE UPDATE ON app_scheduled_job_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- "Hansı iş asılı qalıb?" — sağlamlıq sorğusu. QİSMƏN indeksdir, çünki sual
-- yalnız `RUNNING` sətirlərə aiddir; tamamlanmış minlərlə sətri indeksləmək
-- yazı yükünü artırar, oxu faydası verməzdi.
CREATE INDEX IF NOT EXISTS idx_app_job_runs_stale
    ON app_scheduled_job_runs (tenant_id, leased_until)
    WHERE status = 'RUNNING';

-- ---------------------------------------------------------------------------
-- 2. STATUS KEÇİD TRIGGER-İ — İDEMPOTENTLİYİN DB QATI
-- ---------------------------------------------------------------------------
-- Tətbiq qatı `WHERE status = 'FAILED' OR (status = 'RUNNING' AND ...)` şərti
-- işlədir. Layihə qaydası isə budur: struktur zəmanət İKİ yerdə yaşayır
-- (CLAUDE.md §5) — şərt kodda unudula bilər, skript və ya ikinci tətbiq
-- nüsxəsi onu yan keçə bilər (`migrations/015` başlığı).
--
-- Trigger BİR şeyi qoruyur: TAMAMLANMIŞ slot bir daha açıla bilməz. Yəni gecə
-- işi bir dəfə uğurla bitibsə, heç bir `UPDATE` onu yenidən `RUNNING` edə
-- bilməz və eyni gün ikinci dəfə icra oluna bilməz.
CREATE OR REPLACE FUNCTION enforce_app_job_run_transition() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'SUCCEEDED' AND NEW.status <> 'SUCCEEDED' THEN
        RAISE EXCEPTION
            'PLANLAYICI POZUNTUSU: tamamlanmış icra yenidən açıla bilməz '
            '(iş %, slot %) — idempotentlik zəmanəti',
            OLD.job_key, OLD.scheduled_for;
    END IF;
    -- Slotun kimliyi DONDURULUR: `job_key`/`scheduled_for` dəyişsəydi, sətir
    -- BAŞQA slotun qeydinə çevrilər və unikal açar öz mənasını itirərdi.
    IF NEW.job_key IS DISTINCT FROM OLD.job_key
       OR NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for THEN
        RAISE EXCEPTION
            'PLANLAYICI POZUNTUSU: icra qeydinin kimliyi (iş açarı / slot) '
            'dəyişdirilə bilməz (iş %)', OLD.job_key;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_app_job_run_transition() IS
    'Planlayıcının idempotentlik zəmanətinin DB qatı: tamamlanmış slot yenidən '
    'açıla bilməz, qeydin kimliyi dondurulur (bax `migrations/015` başlığı — '
    'struktur zəmanət iki yerdə yaşayır).';

DROP TRIGGER IF EXISTS trg_app_job_run_transition ON app_scheduled_job_runs;
CREATE TRIGGER trg_app_job_run_transition
    BEFORE UPDATE ON app_scheduled_job_runs
    FOR EACH ROW EXECUTE FUNCTION enforce_app_job_run_transition();

COMMENT ON TABLE app_scheduled_job_runs IS
    'TƏTBİQİN (Python) planlanmış işlərinin icra qeydi və İCARƏSİ. `schema.sql` '
    '§29-dakı `scheduled_job_runs` ilə QARIŞDIRILMAMALIDIR — o, DB-nin öz SQL '
    'cron işlərinin jurnalıdır (tenant-sız, icarəsiz). Burada hər sətir bir '
    'kirayəçinin bir işinin bir slotudur və `UNIQUE (tenant_id, job_key, '
    'scheduled_for)` çox-terminallı quraşdırmada təkrar icranı bloklayır.';
COMMENT ON COLUMN app_scheduled_job_runs.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN app_scheduled_job_runs.tenant_id IS
    'Kirayəçi izolyasiyası — RLS açarı və unikal icarə açarının birinci hissəsi.';
COMMENT ON COLUMN app_scheduled_job_runs.job_key IS
    'İşin kanonik açarı (BÖYÜK hərflərlə, ən azı 3 simvol). Kod tərəfi '
    '`domain.value_objects.job_runs.normalize_job_key()` ilə eyni qaydanı tətbiq '
    'edir — açar reyestrdə, DB-də və log-da EYNİ yazılmalıdır.';
COMMENT ON COLUMN app_scheduled_job_runs.scheduled_for IS
    'İcranın AİD OLDUĞU an (məs. yerli 03:00), faktiki başlanğıc DEYİL. '
    'Gecikmiş icra (catch-up) yalnız `started_at` ilə fərqindən görünür.';
COMMENT ON COLUMN app_scheduled_job_runs.status IS
    'RUNNING → SUCCEEDED / FAILED. SUCCEEDED TERMİNALDIR (trigger bloklayır) — '
    'idempotentlik zəmanətinin özü budur. FAILED təkrar cəhd üçün açıq qalır.';
COMMENT ON COLUMN app_scheduled_job_runs.leased_by IS
    'İcarə sahibi: hansı terminal/proses işi götürüb. Nəticə yazılarkən şərt '
    'kimi işlədilir — icarəsi bitmiş instansiya yeni sahibin nəticəsini '
    'ÜSTÜNDƏN yaza bilməz.';
COMMENT ON COLUMN app_scheduled_job_runs.leased_until IS
    'İcarənin son istifadə tarixi. Bu andan (DAXİL OLMAQLA) sonra icarə bitmiş '
    'sayılır və işi başqa instansiya götürə bilər — cərəyan kəsilməsindən '
    'çökmüş terminalın işi əbədi "RUNNING" qalmasın deyə. Dəyər '
    'ROOT-dan idarə olunur (`SCHEDULER_LEASE_MINUTES`).';
COMMENT ON COLUMN app_scheduled_job_runs.started_at IS
    'Faktiki başlanğıc anı (tz-aware). Geri götürmədə YENİLƏNİR — sətir hər '
    'zaman SONUNCU icarənin başlanğıcını göstərir.';
COMMENT ON COLUMN app_scheduled_job_runs.finished_at IS
    'Bitmə anı. `RUNNING` sətirdə MÜTLƏQ NULL-dur (`chk_job_run_finished`), '
    'geri götürmədə yenidən NULL edilir.';
COMMENT ON COLUMN app_scheduled_job_runs.attempts IS
    'Bu slot üçün ümumi cəhd sayı (1-dən başlayır). `SCHEDULER_MAX_ATTEMPTS` '
    'tavanı buna görə tətbiq olunur: tətbiqi öldürən iş sonsuz təkrarlanmasın.';
COMMENT ON COLUMN app_scheduled_job_runs.last_error IS
    'Sonuncu uğursuzluğun səbəbi (kəsilmiş, ~2000 simvol). Uğurlu icrada '
    'NULL-a qaytarılır — sətir SONUNCU vəziyyəti göstərir, tarixçəni '
    '`attempts` saxlayır.';
COMMENT ON COLUMN app_scheduled_job_runs.result_detail IS
    'İşin qaytardığı qısa xülasə ("235 işçi yeniləndi"). Uğurlu icra ilə '
    '"heç nə tapmayan" icranı bir-birindən seçmək üçün.';
COMMENT ON COLUMN app_scheduled_job_runs.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN app_scheduled_job_runs.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

COMMENT ON INDEX idx_app_job_runs_stale IS
    'Sağlamlıq sorğusu: icarəsi keçmiş, hələ RUNNING qalan işlər (çökmüş '
    'instansiyanın izi). Qismən indeks — sual tamamlanmış sətirlərə aid deyil.';

-- ---------------------------------------------------------------------------
-- 3. RLS — fail-closed (SEC-008)
-- ---------------------------------------------------------------------------
ALTER TABLE app_scheduled_job_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON app_scheduled_job_runs;
CREATE POLICY tenant_isolation ON app_scheduled_job_runs
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 4. GRANT — tətbiq rolu
-- ---------------------------------------------------------------------------
-- `DELETE` QƏSDƏN VERİLMİR. Səbəb icarədədir: silmə hüququ olan tərəf
-- tamamlanmış slotun sətrini SİLİB yenisini yarada və "eyni gün ikinci dəfə
-- icra olunmur" qaydasını yan keçə bilərdi — trigger yalnız `UPDATE` yolunu
-- bağlayır (#16-dakı `open_shift_postings` ilə eyni əsaslandırma).
--
-- AÇIQ `REVOKE` MƏCBURİDİR: `schema.sql` §28-dəki `ALTER DEFAULT PRIVILEGES`
-- yeni cədvəllərə `DELETE`-i AVTOMATİK verir; dar `GRANT` tək başına
-- məhdudiyyət yaratmır (ətraflı izah `migrations/018`-dədir).
--
-- HƏCM QEYDİ: sətir sayı işlərin sayı × gün sayıdır (bir neçə min/il) —
-- təmizləmə tələb etmir. Lazım olarsa sahib (owner) rolu ilə edilir.
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON app_scheduled_job_runs TO %I', v_role
        );
        EXECUTE format('REVOKE DELETE ON app_scheduled_job_runs FROM %I', v_role);
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 5. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `SystemLimitKey` + `DEFAULT_LIMITS` artıq elan edilib (src/domain/policies.py);
-- bu blok həmin açarları `system_limits`-ə yazır ki, ROOT İdarə Mərkəzi
-- ekranında GÖRÜNSÜNLƏR. Seed edilməyən açar "konfiqurasiya edilə bilən"
-- görünər, faktiki olaraq isə kodda oturan fallback işləyərdi
-- (`tests/unit/test_root_control_parameter_parity.py` bu boşluğu qapıya
-- çevirib).
--
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI:
--   * POLL 1–1440 — 1 dəqiqədən tez yoxlama fon dövrəsini mənasız yükə
--     çevirər; 1440 = bir sutka (daha seyrək yoxlama gecə işini bir gün
--     gecikdirərdi).
--   * NIGHTLY_HOUR 0–23 — sutkanın tərifi.
--   * LEASE 5–720 — ALT HÜDUD KRİTİKDİR: icarə ən uzun işin icra
--     müddətindən qısa seçilsə, hələ işləyən instansiyanın icarəsi bitər və
--     ikinci terminal EYNİ işi paralel başladar. Yəni parametr yanlış
--     seçiləndə qoruma özü yarış yaradır. Üst hüdud 12 saatdır: daha uzun
--     icarə çökmüş terminalın işini növbəti gecəyə qədər bloklayardı.
--   * MAX_ATTEMPTS 1–10 — 1 = "təkrar cəhd yoxdur" (qanuni seçim); 10-dan
--     çoxu yalnız log doldurur, çünki 3-dən sonra problem struktur olur.
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('SCHEDULER_POLL_INTERVAL_MINUTES', '15', 'INTEGER', '1', '1440',
     'Planlayıcının "vaxtı çatan iş varmı?" yoxlama aralığı (dəqiqə). '
     'Kiçik dəyər gecikmiş gecə işini tez tutur, böyük dəyər fon yükünü azaldır'),
    ('SCHEDULER_NIGHTLY_HOUR', '3', 'INTEGER', '0', '23',
     'Gecə işlərinin MAĞAZA YERLİ saatı (0–23). Mağazalar bağlı, 1C '
     'sinxronizasiyası bitmiş olmalıdır'),
    ('SCHEDULER_LEASE_MINUTES', '30', 'INTEGER', '5', '720',
     'İcarənin ömrü (dəqiqə). ƏN UZUN işin icra müddətindən BÖYÜK olmalıdır — '
     'əks halda hələ işləyən terminalın icarəsi bitər və ikinci terminal eyni '
     'işi paralel başladar'),
    ('SCHEDULER_MAX_ATTEMPTS', '3', 'INTEGER', '1', '10',
     'Uğursuz (və ya icraçısı çökmüş) işin ümumi cəhd tavanı. Tavan tətbiqi '
     'öldürən işin sonsuz təkrarlanmasının qarşısını alır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022/023-dəki naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_scheduler_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'SCHEDULER_POLL_INTERVAL_MINUTES', '15', 'INTEGER', '1', '1440',
         'Planlayıcının yoxlama aralığı (dəqiqə)'),
        (NEW.tenant_id, 'SCHEDULER_NIGHTLY_HOUR', '3', 'INTEGER', '0', '23',
         'Gecə işlərinin mağaza yerli saatı (0–23)'),
        (NEW.tenant_id, 'SCHEDULER_LEASE_MINUTES', '30', 'INTEGER', '5', '720',
         'İcarənin ömrü (dəqiqə) — ən uzun işin icra müddətindən böyük olmalıdır'),
        (NEW.tenant_id, 'SCHEDULER_MAX_ATTEMPTS', '3', 'INTEGER', '1', '10',
         'Uğursuz işin ümumi cəhd tavanı')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_scheduler_limits_for_new_tenant() IS
    'Yeni kirayəçiyə planlayıcının dörd ROOT parametrini əlavə edir '
    '(migrations/036). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_scheduler_limits ON license_tenants;
CREATE TRIGGER trg_seed_scheduler_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_scheduler_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: `app_scheduled_job_runs` silinsə, planlayıcı hər terminalda hər
-- işi TƏKRAR-TƏKRAR icra edəcək (icarə yeri qalmır) — yəni cədvəlin silinməsi
-- yalnız planlayıcı giriş nöqtələri də söndürüldükdə təhlükəsizdir.
-- `schema.sql` §29-dakı `scheduled_job_runs` cədvəlinə TOXUNULMUR: o, ayrı
-- mexanizmdir və bu DOWN bloku ona aid deyil.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_scheduler_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_scheduler_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'SCHEDULER_POLL_INTERVAL_MINUTES', 'SCHEDULER_NIGHTLY_HOUR',
--       'SCHEDULER_LEASE_MINUTES', 'SCHEDULER_MAX_ATTEMPTS');
--   DROP TRIGGER IF EXISTS trg_app_job_run_transition ON app_scheduled_job_runs;
--   DROP FUNCTION IF EXISTS enforce_app_job_run_transition();
--   DROP TABLE IF EXISTS app_scheduled_job_runs;
-- COMMIT;
