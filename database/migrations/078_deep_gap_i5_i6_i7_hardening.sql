-- ===========================================================================
-- 078 — DEEP-GAP FAZA 4: İ5/İ6/İ7 (mövqe şablonu, permission_flags,
--   scheduled_job_runs) — TƏTBİQ ROLUNUN QALAN YAZI SIZMALARI
-- ===========================================================================
-- Tarix : 2026-08-22
-- Səbəb : `infra`-nın DEEP-GAP dövrə 4 auditi — komanda rəhbərinin TƏSDİQ
--         etdiyi ÜÇ tapıntı, eyni kökdən: `kompasos_app` (bütün kirayəçilərin
--         paylaşdığı TƏK tətbiq rolu) `schema.sql`-in HANSISA hissəsində
--         nəzərdə tutulmayan yazı/oxu icazəsi saxlayırdı. Üçü BİR miqrasiyaya
--         yığılıb, çünki hamısı EYNİ növ düzəlişdir (RLS/GRANT sərtləşməsi)
--         və ayrı-ayrı fayllara bölünsəydi oxucu üçün əlaqə itərdi.
--
-- ---------------------------------------------------------------------------
-- İ5 — `positions` VƏ `position_permissions`: ŞABLON SƏTRİ YAZILA BİLİRDİ
-- ---------------------------------------------------------------------------
-- `schema.sql` §27-dəki TƏK `USING (... OR tenant_id IS NULL) WITH CHECK
-- (tenant_id = current_tenant_id())` siyasəti YAZI qapısı kimi sızırdı:
-- `WITH CHECK` yalnız INSERT/yeni UPDATE sətrini yoxlayır, DELETE-ə HEÇ
-- TƏTBİQ OLUNMUR, UPDATE-in "hansı köhnə sətrə toxunmaq olar" sualını isə
-- YALNIZ `USING` cavablandırır. Nəticədə kirayəçi sessiyası
--     DELETE FROM positions WHERE tenant_id IS NULL
-- ilə qlobal rol şablonunu SİLƏ, ya da
--     UPDATE positions SET tenant_id = current_tenant_id() WHERE tenant_id IS NULL
-- ilə ÖZ TENANT-INA KEÇİRƏ (digər tenant-lardan gizlədə) bilirdi —
-- sonrakı `seed_tenant_defaults()` çağırışı (yeni müştəri quraşdırması)
-- həmin şablonsuz işləyirdi: tenant rolsuz, demək ki girişsiz qalırdı.
-- Eyni boşluq `position_permissions`-ın `WITH CHECK`-ində də var idi
-- (`p.tenant_id IS NULL` yazı predikatında da daşınırdı).
--
-- Həll: OXU (`FOR SELECT`, NULL DAXİL) və YAZI (`FOR ALL`, yalnız öz
-- tenant-ı) ayrı siyasətlərə bölünür — `FOR INSERT, UPDATE, DELETE` kimi
-- siyahı Postgres-də SİNTAKSİS SƏHVİDİR (`FOR` YALNIZ TƏK əmr adı qəbul
-- edir), `FOR ALL` isə PERMISSIVE OR məntiqi ilə SELECT-i geniş, yazını dar
-- saxlayır (bax hər iki `DO $$` blokunun daxili şərhi, aşağıda).
--
-- İKİNCİ QAT: owner bağlantısı (RLS-dən azad) və ya gələcəkdə `FORCE ROW
-- LEVEL SECURITY` qoyulmamış hər hansı yol üçün `enforce_position_template_
-- protection()` trigger-i — HƏR KƏSƏ tətbiq olunur, sessiya kontekstsiz
-- (miqrasiya/owner/seed) icranı isə buraxır (`enforce_root_only_flag_
-- revoke()`-un "sessiya kontekstsiz → bloklamır" naxışı, migrations/076).
--
-- ---------------------------------------------------------------------------
-- İ6 — `permission_flags`: UPDATE bağlı DEYİLDİ
-- ---------------------------------------------------------------------------
-- Köhnə §28/§30 yalnız `REVOKE DELETE` edirdi — `UPDATE permission_flags
-- SET hardlock_level = 0 WHERE code = 'can_manage_permissions'` HƏLƏ DƏ
-- mümkün idi. Dörd təhlükəsizlik atributu artıq `enforce_flag_attributes_
-- immutable()` trigger-i ilə qorunur (migrations/013), amma bu REVOKE
-- İKİNCİ qatdır: `name_az`/`category` kimi immutable OLMAYAN sütunlar da
-- artıq UPDATE-ə bağlı deyil. İNSERT AÇIQ QALIR — Root-un `create()` yolu
-- (`config_repositories.py::PostgresPermissionFlagRepository.create`) buna
-- görə qırılmır; Python-da HEÇ BİR `UPDATE permission_flags` çağırışı
-- yoxdur (yoxlanılıb), ona görə tənzimlənmiş REVOKE heç nəyi qırmır.
--
-- ---------------------------------------------------------------------------
-- İ7 — `scheduled_job_runs`: TƏTBİQ ROLUNA SƏSSİZCƏ AÇIQ QALMIŞDI
-- ---------------------------------------------------------------------------
-- `scheduled_job_runs` (§29) DB-nin ÖZ SQL job-larının qeydidir — Python
-- tətbiqi bu cədvələ HEÇ VAXT toxunmur (əvəzinə `app_scheduled_job_runs`,
-- migrations/036 istifadə edir, bax `scheduled_job_repository.py`).
-- `schema.sql` §28-dəki `ALTER DEFAULT PRIVILEGES` bu cədvələ SESSİZCƏ tam
-- GRANT verirdi, çünki yaradan rol elə DEFAULT PRIVILEGES-i elan edən
-- roldur — açıq `REVOKE` yox idi. Üstəlik `error_message` xam `SQLERRM`
-- saxlayırdı: RLS-siz, tenant_id-siz bu cədvəldə bir tenant-ın job xətası
-- (məs. constraint pozuntusu daxilində görünən başqa kirayəçinin açarı)
-- İSTƏNİLƏN `kompasos_app` sessiyasından oxuna bilirdi.
--
-- Xarici scheduler (`docs/scheduler_setup.md`, Variant B) MƏHZ `kompasos_app`
-- ilə qoşulub `run_all_scheduled_jobs()`-u çağırır — cədvəl səlahiyyətini
-- kor-koranə geri almaq onu qırardı, çünki daxildəki `run_scheduled_job()`
-- (`SECURITY INVOKER`, defolt) çağıran rolun adından yazmağa çalışardı.
-- Ona görə `run_all_scheduled_jobs()` `SECURITY DEFINER`-ə keçirilir —
-- daxili çağırışlar artıq FUNKSİYA SAHİBİNİN adından işləyir, `kompasos_app`
-- isə YALNIZ bu sabit-çağırış zəncirini işə sala bilir (birbaşa `run_
-- scheduled_job(TEXT, TEXT)` EXECUTE-u artıq bağlıdır, §28/§30-dan bəri).
-- `run_scheduled_job` ÖZÜ `SECURITY DEFINER` EDİLMİR: EXECUTE ona birbaşa
-- verilmədiyi üçün bu, `p_sql` inyeksiya səthini genişləndirmir.
--
-- `scheduled_job_runs`-a DELETE-ə qarşı append-only trigger əlavə olunur
-- (`enforce_append_only()`, §26 — audit_logs ilə EYNİ funksiya, YALNIZ
-- DELETE bağlanır, UPDATE YOX: `run_scheduled_job()` hər sətri əvvəl
-- `PENDING` kimi INSERT edir, sonra NƏTİCƏ ilə UPDATE edir).
--
-- `schema_migrations` (migrations/061) da EYNİ boşluğu daşıyırdı — reyestr
-- YENİ miqrasiya ilə YARADILMIR (061-də artıq mövcuddur), ona görə onun
-- REVOKE-u da BURADA (fayl artıq tətbiq olunub, ÜZƏRİNƏ YAZILMIR — §7
-- qaydası: köhnə miqrasiya checksum-u dəyişməməlidir).
--
-- ---------------------------------------------------------------------------
-- §7 — `schema.sql` DƏ EYNİ MƏTNLƏ YENİLƏNİB
-- ---------------------------------------------------------------------------
-- Aşağıdakı `CREATE OR REPLACE FUNCTION`/`CREATE TRIGGER` gövdələri
-- `schema.sql`-dəki YENİ nüsxə ilə EYNİDİR (`test_schema_migration_
-- parity.py::test_shared_objects_are_defined_identically` bunu avtomatik
-- yoxlayır) — təzə quraşdırma və mövcud bazanın YENİLƏNMƏSİ eyni son
-- vəziyyətə gəlir.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- --------------------------------------------------------------------- İ5 --

-- `positions` — OXU (bütün əmrlər üçün NULL DAXİL) və YAZI (yalnız öz
-- tenant-ı) ayrı siyasətlərə bölünür.
DROP POLICY IF EXISTS tenant_isolation ON positions;
DROP POLICY IF EXISTS tenant_isolation_read ON positions;
DROP POLICY IF EXISTS tenant_isolation_write ON positions;
CREATE POLICY tenant_isolation_read ON positions
    FOR SELECT
    USING (tenant_id = current_tenant_id() OR tenant_id IS NULL);
-- `FOR ALL` SELECT-i də əhatə edir, LAKİN yuxarıdakı `tenant_isolation_read`
-- PERMISSIVE siyasəti onunla OR olunur — SELECT üçün nəticə İKİ predikatın
-- GENİŞİ (NULL DAXİL) qalır, INSERT/UPDATE/DELETE üçün isə YALNIZ bu siyasət
-- keçərlidir.
CREATE POLICY tenant_isolation_write ON positions
    FOR ALL
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- `position_permissions` — eyni bölgü, `write_predicate` şablon mövqeyə
-- (`positions.tenant_id IS NULL`) bağlı sətri istisna edir.
DROP POLICY IF EXISTS tenant_isolation ON position_permissions;
DROP POLICY IF EXISTS tenant_isolation_read ON position_permissions;
DROP POLICY IF EXISTS tenant_isolation_write ON position_permissions;
CREATE POLICY tenant_isolation_read ON position_permissions
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM positions p
             WHERE p.id = position_permissions.position_id
               AND (p.tenant_id = current_tenant_id() OR p.tenant_id IS NULL)
        )
    );
CREATE POLICY tenant_isolation_write ON position_permissions
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM positions p
             WHERE p.id = position_permissions.position_id
               AND p.tenant_id = current_tenant_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM positions p
             WHERE p.id = position_permissions.position_id
               AND p.tenant_id = current_tenant_id()
        )
    );

-- İKİNCİ QAT — RLS-dən azad hər yol üçün trigger (bax modul başlığı).
CREATE OR REPLACE FUNCTION enforce_position_template_protection() RETURNS TRIGGER AS $$
BEGIN
    IF current_tenant_id() IS NULL THEN
        RETURN OLD;
    END IF;

    IF OLD.tenant_id IS NULL THEN
        RAISE EXCEPTION
            'İ5 QORUYUCUSU: qlobal şablon mövqe (id=%) kirayəçi sessiyasından '
            'dəyişdirilə/silinə bilməz — bu RLS yazı siyasətinin ARTIQ '
            'bloklaması lazım olan hərəkətin İKİNCİ qatıdır', OLD.id;
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_position_template_protection() IS
    'İ5 (DEEP-GAP dövrə auditi): qlobal mövqe şablonlarını (`tenant_id IS '
    'NULL`) kirayəçi sessiyasından UPDATE/DELETE-dən qoruyan İKİNCİ qat — '
    'birinci qat `tenant_isolation_write` RLS siyasətidir (yuxarıda, §27).';

DROP TRIGGER IF EXISTS trg_position_template_protection ON positions;
CREATE TRIGGER trg_position_template_protection
    BEFORE UPDATE OR DELETE ON positions
    FOR EACH ROW EXECUTE FUNCTION enforce_position_template_protection();

-- --------------------------------------------------------------------- İ6 --

DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format('REVOKE UPDATE ON permission_flags FROM %I', v_role);
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — İ6 REVOKE atlandı.', v_role;
    END IF;
END
$$;

-- --------------------------------------------------------------------- İ7 --

-- YAN TAPINTI (İ7-in özündən AYRI, amma ona bağlıdır): `scheduled_job_runs`
-- VƏ onun `run_scheduled_job`/`run_all_scheduled_jobs` aparatı (SEC-010,
-- §29) HEÇ VAXT bir miqrasiya ilə yaradılmayıb — YALNIZ `schema.sql`-də
-- mövcud idi. Yəni yalnız miqrasiya zənciri ilə qurulan (fresh `schema.sql`
-- OLMADAN yenilənən) HƏR HANSI mövcud quraşdırmada bu cədvəl/funksiyalar
-- ÜMUMİYYƏTLƏ yox idi — xarici scheduler (`docs/scheduler_setup.md`,
-- Variant B) sükutla işləmirdi. Bu, D4-ün TAPDIĞI sinifdən (miqrasiyada
-- yaranıb schema.sql-ə köçürülməyən obyekt) TƏRS HALDIR və AYRICA hesabat
-- tələb edir — komanda rəhbərinə bildirilib. Aşağıdakı `CREATE TABLE IF NOT
-- EXISTS` YALNIZ bu miqrasiyanın öz REVOKE/trigger addımlarının təhlükəsiz
-- işləməsi üçün ÖN ŞƏRTDİR (idempotent, `schema.sql`-dəki tərif ilə eynidir)
-- — `v_scheduled_job_health` görünüşü və pg_cron qeydiyyatı bu miqrasiyanın
-- ƏHATƏSİNDƏN KƏNARDIR (İ7-nin özü ilə əlaqəsi yoxdur).
--
-- EYNİ SƏBƏBLƏ: `enforce_append_only()` (§26) DƏ HEÇ VAXT bir miqrasiya ilə
-- yaradılmayıb — bu trigger-in ÖZÜ ona bağlı olduğu üçün, o da BURADA
-- (idempotent `CREATE OR REPLACE`, eyni tərif) təkrarlanır. Bunun `audit_
-- logs`/`security_events` üzərindəki YAYILMA əhatəsi (o cədvəllərin append-
-- only zəmanəti də eyni səbəbdən miqrasiya zəncirində HEÇ VAXT olmayıb) bu
-- miqrasiyanın ƏHATƏSİNDƏN KƏNARDIR — komanda rəhbərinə AYRICA bildirilib.
CREATE OR REPLACE FUNCTION enforce_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'APPEND-ONLY POZUNTUSU: "%" cədvəlində % əməliyyatı qadağandır — '
        'audit izi dəyişdirilə və ya silinə bilməz (bölmə 4)',
        TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS scheduled_job_runs (
    id            BIGSERIAL PRIMARY KEY,
    job_name      TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    affected_rows INTEGER,
    succeeded     BOOLEAN,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_name_time
    ON scheduled_job_runs (job_name, started_at DESC);

-- `error_message` — xam `SQLERRM` əvəzinə `SQLSTATE + job adı`. Tam mətn
-- HƏLƏ DƏ `RAISE WARNING` ilə server loquna düşür (dəyişməyib) — DBA
-- diaqnostikası itmir, yalnız RLS-siz/tenant_id-siz CƏDVƏLDƏ geniş görünmə
-- bağlanır.
CREATE OR REPLACE FUNCTION run_scheduled_job(p_job_name TEXT, p_sql TEXT)
RETURNS INTEGER AS $$
DECLARE
    v_id      BIGINT;
    v_result  INTEGER;
BEGIN
    INSERT INTO scheduled_job_runs (job_name) VALUES (p_job_name) RETURNING id INTO v_id;
    BEGIN
        EXECUTE 'SELECT ' || p_sql INTO v_result;
        UPDATE scheduled_job_runs
        SET finished_at = now(), affected_rows = v_result, succeeded = TRUE
        WHERE id = v_id;
        RETURN v_result;
    EXCEPTION WHEN OTHERS THEN
        UPDATE scheduled_job_runs
        SET finished_at = now(), succeeded = FALSE,
            error_message = 'SQLSTATE ' || SQLSTATE || ' (' || p_job_name || ')'
        WHERE id = v_id;
        RAISE WARNING 'Planlaşdırılmış job uğursuz oldu (%): %', p_job_name, SQLERRM;
        RETURN -1;
    END;
END;
$$ LANGUAGE plpgsql;

-- `SECURITY DEFINER` — aşağıdakı §28/§30 REVOKE-dən sonra `kompasos_app`-ın
-- `scheduled_job_runs` üzərində birbaşa cədvəl səlahiyyəti QALMIR. Xarici
-- scheduler isə MƏHZ `kompasos_app` ilə qoşulub bu funksiyanı çağırır
-- (`docs/scheduler_setup.md`, Variant B) — `SECURITY DEFINER` olmasaydı,
-- daxildəki `run_scheduled_job()` çağırışı (SECURITY INVOKER) çağıran rolun
-- adından yazmağa cəhd edərdi və sükutla uğursuz olardı. `SET search_path`
-- axtarış yolu manipulyasiyasının qarşısını alır (standart bərkitmə).
CREATE OR REPLACE FUNCTION run_all_scheduled_jobs() RETURNS TABLE (
    job_name TEXT, affected_rows INTEGER
) SECURITY DEFINER SET search_path = kompasos, pg_temp AS $$
BEGIN
    RETURN QUERY
    SELECT 'escalate_verification_timeouts'::TEXT,
           run_scheduled_job('escalate_verification_timeouts',
                             'kompasos.cron_escalate_verification_timeouts()');
    RETURN QUERY
    SELECT 'escalate_task_deadlines'::TEXT,
           run_scheduled_job('escalate_task_deadlines',
                             'kompasos.cron_escalate_task_deadlines()');
    RETURN QUERY
    SELECT 'close_expired_appeals'::TEXT,
           run_scheduled_job('close_expired_appeals',
                             'kompasos.cron_close_expired_appeals()');
    RETURN QUERY
    SELECT 'detect_unauthorized_absences'::TEXT,
           run_scheduled_job('detect_unauthorized_absences',
                             'kompasos.cron_detect_unauthorized_absences()');
    RETURN QUERY
    SELECT 'reset_sales_points'::TEXT,
           run_scheduled_job('reset_sales_points', 'kompasos.cron_reset_sales_points()');
    RETURN QUERY
    SELECT 'notify_points_reset_upcoming'::TEXT,
           run_scheduled_job('notify_points_reset_upcoming',
                             'kompasos.cron_notify_points_reset_upcoming()');
    RETURN QUERY
    SELECT 'update_license_payment_status'::TEXT,
           run_scheduled_job('update_license_payment_status',
                             'kompasos.cron_update_license_payment_status()');
    RETURN QUERY
    SELECT 'prune_expired_backups'::TEXT,
           run_scheduled_job('prune_expired_backups',
                             'kompasos.cron_prune_expired_backups()');
    RETURN QUERY
    SELECT 'prune_expired_sessions'::TEXT,
           run_scheduled_job('prune_expired_sessions',
                             'kompasos.cron_prune_expired_sessions()');
END;
$$ LANGUAGE plpgsql;

-- DELETE-ə qarşı append-only (§26-dakı `enforce_append_only()` — audit_logs
-- ilə EYNİ funksiya, YALNIZ DELETE bağlanır).
DROP TRIGGER IF EXISTS trg_scheduled_job_runs_append_only ON scheduled_job_runs;
CREATE TRIGGER trg_scheduled_job_runs_append_only
    BEFORE DELETE ON scheduled_job_runs
    FOR EACH ROW EXECUTE FUNCTION enforce_append_only();

DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'REVOKE SELECT, INSERT, UPDATE, DELETE ON scheduled_job_runs FROM %I', v_role
        );
        -- `run_scheduled_job(TEXT, TEXT)` ixtiyari SQL icra edir — birbaşa
        -- EXECUTE artıq §28/§30-da bağlanıb, burada TƏKRAR (yeni GRANT-ların
        -- onu geri açmaması üçün defense-in-depth, digər REVOKE-lərlə EYNİ
        -- naxış).
        EXECUTE format(
            'REVOKE EXECUTE ON FUNCTION run_scheduled_job(TEXT, TEXT) FROM %I', v_role
        );
        -- `schema_migrations` (migrations/061) — reyestr tətbiq rolunun heç
        -- görmədiyi bir faktdır (bax həmin faylın başlığı). 061 ARTIQ tətbiq
        -- olunmuş miqrasiyadır — checksum-u dəyişməmək üçün REVOKE ORAYA
        -- YOX, BURAYA yazılır.
        EXECUTE format(
            'REVOKE SELECT, INSERT, UPDATE, DELETE ON schema_migrations FROM %I', v_role
        );
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — İ7 REVOKE-ləri atlandı.', v_role;
    END IF;
END
$$;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--
--   -- İ7: GRANT-ları qaytar (əvvəlki, tənzimlənməmiş vəziyyət)
--   DO $$
--   DECLARE
--       v_role TEXT := 'kompasos_app';
--   BEGIN
--       IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
--           EXECUTE format(
--               'GRANT SELECT, INSERT, UPDATE, DELETE ON scheduled_job_runs TO %I', v_role
--           );
--           EXECUTE format(
--               'GRANT SELECT, INSERT, UPDATE, DELETE ON schema_migrations TO %I', v_role
--           );
--       END IF;
--   END
--   $$;
--   DROP TRIGGER IF EXISTS trg_scheduled_job_runs_append_only ON scheduled_job_runs;
--
--   -- İ6: UPDATE-i qaytar
--   DO $$
--   DECLARE
--       v_role TEXT := 'kompasos_app';
--   BEGIN
--       IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
--           EXECUTE format('GRANT UPDATE ON permission_flags TO %I', v_role);
--       END IF;
--   END
--   $$;
--
--   -- İ5: köhnə tək-siyasət modelinə qayıt
--   DROP TRIGGER IF EXISTS trg_position_template_protection ON positions;
--   DROP FUNCTION IF EXISTS enforce_position_template_protection();
--   DROP POLICY IF EXISTS tenant_isolation_read ON positions;
--   DROP POLICY IF EXISTS tenant_isolation_write ON positions;
--   CREATE POLICY tenant_isolation ON positions
--       USING (tenant_id = current_tenant_id() OR tenant_id IS NULL)
--       WITH CHECK (tenant_id = current_tenant_id());
--   DROP POLICY IF EXISTS tenant_isolation_read ON position_permissions;
--   DROP POLICY IF EXISTS tenant_isolation_write ON position_permissions;
--   CREATE POLICY tenant_isolation ON position_permissions
--       USING (
--           EXISTS (SELECT 1 FROM positions p WHERE p.id = position_permissions.position_id
--                     AND (p.tenant_id = current_tenant_id() OR p.tenant_id IS NULL))
--       )
--       WITH CHECK (
--           EXISTS (SELECT 1 FROM positions p WHERE p.id = position_permissions.position_id
--                     AND (p.tenant_id = current_tenant_id() OR p.tenant_id IS NULL))
--       );
-- COMMIT;
-- ===========================================================================
