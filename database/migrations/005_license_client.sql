-- ===========================================================================
-- MIGRATION 005 — LİSENZİYA KLİENTİ: CHECK-IN TELEMETRİYASI VƏ ÖDƏNİŞ NƏZARƏTİ
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : Faza 3, bənd 4 (spesifikasiya bölmə 8) — "License Client (periodic
--         check-in, grace period logic, three distinct restricted-mode
--         states) AND a minimal License/Telemetry Backend Stub".
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ AYRICA `tenant_check_ins` CƏDVƏLİ
-- ---------------------------------------------------------------------------
-- `license_tenants.last_check_in_at` yalnız SON anı saxlayır. Bölmə 8 isə
-- Developer Panelində "sync sağlamlığı", "aktiv istifadəçi sayı", "server
-- sayı" kimi göstəriciləri TARİXÇƏ ilə tələb edir — tək sütunla "bu tenant
-- iki həftədir yavaş-yavaş sönür" tipli meyl görünməzdi.
--
-- Cədvəl QƏSDƏN yalnız SAYĞAC saxlayır. Bölmə 8: *"heç bir halda işçi
-- PII-sinə uzaqdan çıxış YOXDUR"*. Sərbəst `JSONB` sütunu qoyulsaydı, bir
-- gün ora ad/e-poçt düşməsi yalnız kod-baxışının diqqətindən asılı olardı;
-- ciddi tipli `INTEGER` sütunlar bunu struktur olaraq mümkünsüz edir
-- (klient tərəfdəki `Telemetry` sinfi ilə eyni prinsip).
--
-- ---------------------------------------------------------------------------
-- NİYƏ `v_license_payment_reminders`
-- ---------------------------------------------------------------------------
-- Bölmə 8: *"Növbəti ödəniş tarixinə X gün qaldıqda (məs. 7/3/1 gün)
-- Developer Panelində avtomatik xəbərdarlıq"*. Bu hesablama tək yerdə
-- (SQL-də) saxlanılır ki, Faza 6-dakı UI və e-poçt xatırladıcısı (bənd 5)
-- eyni məntiqi TƏKRAR YAZMASIN — iki nüsxə bir gün fərqli davranardı.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. Check-in telemetriyası (yalnız aqreqasiya — PII YOXDUR)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_check_ins (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    checked_in_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    app_version       TEXT,
    active_users      INTEGER NOT NULL DEFAULT 0 CHECK (active_users >= 0),
    store_count       INTEGER NOT NULL DEFAULT 0 CHECK (store_count >= 0),
    erp_server_count  INTEGER NOT NULL DEFAULT 0 CHECK (erp_server_count >= 0),
    pending_sync_count INTEGER NOT NULL DEFAULT 0 CHECK (pending_sync_count >= 0)
);

COMMENT ON TABLE tenant_check_ins IS
    'Dövri check-in telemetriyası (bölmə 8). YALNIZ sayğaclar — işçi PII-si '
    'heç bir halda uzaqdan çıxarılmır. Sərbəst mətn/JSONB sütunu QƏSDƏN yoxdur.';

CREATE INDEX IF NOT EXISTS idx_check_ins_tenant_time
    ON tenant_check_ins (tenant_id, checked_in_at DESC);

-- ---------------------------------------------------------------------------
-- 2. Ödəniş xatırlatmaları (7/3/1 gün) — tək həqiqət mənbəyi
-- ---------------------------------------------------------------------------
-- `security_invoker`: view sorğunu ÇAĞIRANIN hüquqları ilə icra edir.
-- Bu olmasaydı view sahibinin (owner) hüquqları ilə işləyər və RLS yan
-- keçilərdi — miqrasiya 004-dəki `v_erp_server_health` ilə eyni səbəb.
DROP VIEW IF EXISTS v_license_payment_reminders;
CREATE VIEW v_license_payment_reminders WITH (security_invoker = true) AS
SELECT
    t.tenant_id,
    t.tenant_name,
    t.status,
    t.last_payment_date,
    t.next_payment_date,
    t.grace_period_days,
    t.company_contact_email,
    t.last_check_in_at,
    (t.next_payment_date - CURRENT_DATE)                       AS days_until_due,
    GREATEST(0, CURRENT_DATE - t.next_payment_date)            AS days_overdue,
    -- Güzəşt müddəti bitibmi. DİQQƏT: bu, AVTOMATİK bloklama demək DEYİL —
    -- söndürmə həmişə Developer Panelindəki insan qərarıdır (bölmə 8).
    (t.next_payment_date IS NOT NULL
        AND CURRENT_DATE - t.next_payment_date > t.grace_period_days) AS grace_exhausted,
    CASE
        WHEN t.status = 'DEAKTIV'                              THEN 'DEAKTIV'
        WHEN t.next_payment_date IS NULL                       THEN 'TARIX_YOXDUR'
        WHEN CURRENT_DATE > t.next_payment_date                THEN 'GECIKIB'
        WHEN t.next_payment_date - CURRENT_DATE <= 1           THEN 'SON_GUN'
        WHEN t.next_payment_date - CURRENT_DATE <= 3           THEN 'UC_GUN'
        WHEN t.next_payment_date - CURRENT_DATE <= 7           THEN 'YEDDI_GUN'
        ELSE 'NORMAL'
    END                                                        AS reminder_stage,
    -- "Uzun müddətdir səssizdir" — tətbiq ümumiyyətlə işləyirmi sualı.
    (t.last_check_in_at IS NULL OR t.last_check_in_at < now() - INTERVAL '3 days')
                                                               AS check_in_stale
  FROM license_tenants t
 WHERE t.status <> 'DEAKTIV' OR t.deactivated_at > now() - INTERVAL '90 days';

COMMENT ON VIEW v_license_payment_reminders IS
    'Developer Paneli üçün ödəniş xatırlatma mərhələləri (7/3/1 gün, bölmə 8). '
    'grace_exhausted = TRUE avtomatik bloklama DEYİL — söndürmə insan qərarıdır.';

-- ---------------------------------------------------------------------------
-- 3. Köhnə check-in qeydlərinin təmizlənməsi
-- ---------------------------------------------------------------------------
-- Hər tenant sutkada ~1 sətir yazır; 21 filiallı bir müştəri üçün bu azdır,
-- lakin çox-tenant reyestrində illər ərzində yığılır. 180 gün meyl analizi
-- üçün kifayətdir və `backup_records` təmizləməsi ilə eyni nümunədədir.
CREATE OR REPLACE FUNCTION cron_prune_check_ins() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH pruned AS (
        DELETE FROM tenant_check_ins
        WHERE checked_in_at < now() - INTERVAL '180 days'
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM pruned;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cron_prune_check_ins() IS
    'Telemetriya tarixçəsini 180 günlə məhdudlaşdırır (miqrasiya 005).';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
      BEGIN
        PERFORM cron.schedule(
            'kompasos-checkins', '35 3 * * *', 'SELECT kompasos.cron_prune_check_ins()'
        );
      EXCEPTION WHEN OTHERS THEN
        RAISE WARNING
            'pg_cron mövcuddur, lakin `kompasos-checkins` qeydiyyatı alınmadı (%). '
            'Xarici scheduler istifadə edin — bax docs/scheduler_setup.md', SQLERRM;
      END;
    ELSE
        RAISE WARNING 'pg_cron tapılmadı — cron_prune_check_ins() xarici scheduler ilə çağırılmalıdır.';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. İcazələr
-- ---------------------------------------------------------------------------
-- `tenant_check_ins` LİSENZİYA SERVERİNİN cədvəlidir — tenant tətbiqi onu
-- oxumur, yalnız yazılır. Ona görə tətbiq roluna `SELECT` VERİLMİR.
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format('GRANT INSERT ON tenant_check_ins TO %I', v_role);
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
    END IF;
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: `tenant_check_ins` silinsə telemetriya TARİXÇƏSİ itir. Lisenziya
-- məntiqi bundan asılı DEYİL (klient öz vəziyyətini yerli fayl da saxlayır),
-- yəni müştəri tərəfdə heç nə pozulmur — yalnız Developer Panelindəki meyl
-- qrafikləri boşalır.
--
-- BEGIN;
--   DO $$ BEGIN
--       IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
--           PERFORM cron.unschedule('kompasos-checkins');
--       END IF;
--   END $$;
--   DROP FUNCTION IF EXISTS cron_prune_check_ins();
--   DROP VIEW IF EXISTS v_license_payment_reminders;
--   DROP INDEX IF EXISTS idx_check_ins_tenant_time;
--   DROP TABLE IF EXISTS tenant_check_ins;
-- COMMIT;
