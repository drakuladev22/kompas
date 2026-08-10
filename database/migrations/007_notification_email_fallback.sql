-- ===========================================================================
-- MIGRATION 007 — BİLDİRİŞ E-POÇT EHTİYAT KANALI: TƏKRAR CƏHD MÜHASİBATI
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : Faza 3, bənd 5 (spesifikasiya bölmə 7) — "Kritik bildirişlər ...
--         eyni zamanda qeydiyyatlı admin e-poçtuna da göndərilir".
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ TƏKRAR CƏHD SÜTUNLARI LAZIMDIR
-- ---------------------------------------------------------------------------
-- `schema.sql` yalnız `email_sent` və `email_sent_at` saxlayır — yəni "getdi"
-- və "getmədi". Bu, iki halı AYIRD EDƏ BİLMİR:
--
--     (a) SMTP müvəqqəti işləmir  → təkrar cəhd EDİLMƏLİDİR
--     (b) SMTP ümumiyyətlə qurulmayıb / şirkət e-poçtu boşdur
--         → təkrar cəhd MƏNASIZDIR, sətir növbəni əbədi tıxayardı
--
-- `email_attempts` + `email_next_attempt_at` bu fərqi yaradır: (b) halında
-- `email_next_attempt_at` NULL qalır və sətir bir daha götürülmür.
-- `email_error` isə "niyə getmədi?" sualına cavabı SAXLAYIR — əks halda səbəb
-- yalnız log faylında qalar və müştəri PC-sindən onu almaq lazım gələrdi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ İNDEKS DƏYİŞİR
-- ---------------------------------------------------------------------------
-- Mövcud `idx_notifications_email_pending` bütün göndərilməmiş kritik
-- sətirləri əhatə edir. Cəhd limiti gələndən sonra "tükənmiş" sətirlər də
-- orada qalar və hər dövrdə oxunardı. Yeni indeks `email_attempts` sütununu
-- daxil edir ki, dispatcher sorğusu yalnız CANLI növbəni oxusun.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS email_attempts        SMALLINT    NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS email_error           TEXT,
    ADD COLUMN IF NOT EXISTS email_next_attempt_at TIMESTAMPTZ;

ALTER TABLE notifications
    DROP CONSTRAINT IF EXISTS chk_notifications_email_attempts;
ALTER TABLE notifications
    ADD CONSTRAINT chk_notifications_email_attempts
        CHECK (email_attempts >= 0 AND email_attempts <= 20);

COMMENT ON COLUMN notifications.email_attempts IS
    'Uğursuz e-poçt cəhdlərinin sayı. Limitə çatdıqda sətir növbədən çıxır — '
    'in-app bildiriş isə yerində qalır (bölmə 7).';
COMMENT ON COLUMN notifications.email_next_attempt_at IS
    'Növbəti cəhdin ən erkən vaxtı (eksponensial gözləmə). NULL = daha cəhd '
    'edilmir (ya göndərilib, ya da səbəb təkrarla düzəlməyəndir).';

DROP INDEX IF EXISTS idx_notifications_email_pending;
CREATE INDEX IF NOT EXISTS idx_notifications_email_pending
    ON notifications (email_next_attempt_at NULLS FIRST, created_at)
 WHERE is_critical AND NOT email_sent AND email_attempts < 5;

-- ---------------------------------------------------------------------------
-- Köhnə bildirişlərin təmizlənməsi
-- ---------------------------------------------------------------------------
-- Bildiriş axını gündəlikdir və illər ərzində yığılır. 90 gün seçilib:
-- oxunmuş bildirişin bundan sonra dəyəri yoxdur, KRİTİK olanlar isə audit
-- dəyəri daşıyır və SAXLANILIR (`audit_logs` ilə uyğunluq).
CREATE OR REPLACE FUNCTION cron_prune_notifications() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH pruned AS (
        DELETE FROM notifications
        WHERE created_at < now() - INTERVAL '90 days'
          AND read_at IS NOT NULL
          AND NOT is_critical
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM pruned;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cron_prune_notifications() IS
    'Oxunmuş, qeyri-kritik bildirişləri 90 gündən sonra silir (miqrasiya 007). '
    'Kritik bildirişlər audit dəyəri üçün saxlanılır.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
      BEGIN
        PERFORM cron.schedule(
            'kompasos-notifications', '40 3 * * *', 'SELECT kompasos.cron_prune_notifications()'
        );
      EXCEPTION WHEN OTHERS THEN
        RAISE WARNING
            'pg_cron mövcuddur, lakin `kompasos-notifications` qeydiyyatı alınmadı (%). '
            'Xarici scheduler istifadə edin — bax docs/scheduler_setup.md', SQLERRM;
      END;
    ELSE
        RAISE WARNING
            'pg_cron tapılmadı — cron_prune_notifications() xarici scheduler ilə çağırılmalıdır.';
    END IF;
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: `email_attempts` silinsə dispatcher uğursuz sətirləri SONSUZA QƏDƏR
-- təkrarlayar və SMTP provayderi göndərəni bloklaya bilər.
--
-- BEGIN;
--   DO $$ BEGIN
--       IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
--           PERFORM cron.unschedule('kompasos-notifications');
--       END IF;
--   END $$;
--   DROP FUNCTION IF EXISTS cron_prune_notifications();
--   DROP INDEX IF EXISTS idx_notifications_email_pending;
--   CREATE INDEX idx_notifications_email_pending
--       ON notifications (created_at) WHERE is_critical AND NOT email_sent;
--   ALTER TABLE notifications DROP CONSTRAINT IF EXISTS chk_notifications_email_attempts;
--   ALTER TABLE notifications
--       DROP COLUMN IF EXISTS email_attempts,
--       DROP COLUMN IF EXISTS email_error,
--       DROP COLUMN IF EXISTS email_next_attempt_at;
-- COMMIT;
