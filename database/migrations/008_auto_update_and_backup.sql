-- ===========================================================================
-- MIGRATION 008 — AVTOMATİK YENİLƏNMƏ KATALOQU VƏ MƏCBURİ VERSİYA
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : Faza 3, bənd 6 (spesifikasiya bölmə 1, 7, 8) — "Auto-Update Client
--         (arxa planda periodik yoxlama, Developer Panel-in «forced update
--         trigger»-ini qəbul edən uc, Authenticode imzasını doğrulayaraq
--         tətbiq edir)".
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ AYRICA UPDATE SERVERİ YOXDUR
-- ---------------------------------------------------------------------------
-- Lisenziya ilə eyni arxitektura qərarı (bax miqrasiya 006): buraxılış
-- kataloqu bu cədvəldir, quraşdırıcı faylın özü isə Supabase Storage-dadır.
-- CDN, update serveri və ya ayrıca domen tələb OLUNMUR — Developer Paneli
-- sadəcə yeni sətir əlavə edir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ HASH BU CƏDVƏLDƏDİR
-- ---------------------------------------------------------------------------
-- `setup.exe.sha256` kimi yan fayl faydasız olardı — faylı əvəz edən onun
-- yanındakı hash faylını da əvəz edər. Buradakı sətir AYRI etibar
-- sərhədindədir: `app_releases`-ə yazma yalnız `service_role` ilə mümkündür,
-- Storage-a yazma isə ayrıca icazədir. Hash TƏK QAT DEYİL — klient əlavə
-- olaraq Authenticode imzasını da yoxlayır (bax `updates/verification.py`).
--
-- ---------------------------------------------------------------------------
-- NİYƏ KATALOQ TENANT-A AİD DEYİL
-- ---------------------------------------------------------------------------
-- Buraxılış hamı üçün eynidir; hər tenant üçün sətir təkrarlamaq həm
-- artıqlıq, həm də səhv mənbəyi olardı (bir tenant-a səhvən köhnə versiya
-- yazıla bilərdi). Tenant-a XAS olan yeganə şey MƏCBURİ versiyadır —
-- o da `license_tenants.forced_update_version` sütununda saxlanılır.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. Buraxılış kataloqu
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_releases (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version           TEXT NOT NULL,
    channel           TEXT NOT NULL DEFAULT 'STABLE'
                          CHECK (channel IN ('STABLE', 'BETA')),
    storage_path      TEXT NOT NULL,           -- Supabase Storage bucket-daxili açar
    sha256            TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes        BIGINT CHECK (size_bytes IS NULL OR size_bytes > 0),
    -- Bu versiyadan KÖHNƏ quraşdırmalar üçün yenilənmə məcburidir
    -- (təhlükəsizlik yaması). NULL = məcburi deyil.
    mandatory_below   TEXT,
    release_notes_az  TEXT NOT NULL DEFAULT '',
    -- NULL = hazırlanır, hələ yayımlanmayıb. Klient yalnız NOT NULL olanları görür.
    published_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (version, channel)
);

COMMENT ON TABLE app_releases IS
    'Buraxılış kataloqu (bölmə 7). Ayrıca update serveri YOXDUR — fayl '
    'Supabase Storage-dadır, sətir isə buradadır. Yazma: yalnız service_role.';
COMMENT ON COLUMN app_releases.mandatory_below IS
    'Bu versiyadan köhnə quraşdırmalar üçün yenilənmə məcburidir. "Məcburi" '
    'tətbiqi BLOKLAMIR — növbəti uyğun anda tətbiq olunur (bölmə 7).';
COMMENT ON COLUMN app_releases.published_at IS
    'NULL olduqda buraxılış klientlərə GÖRÜNMÜR — hazırlıq mərhələsi.';

CREATE INDEX IF NOT EXISTS idx_releases_channel_published
    ON app_releases (channel, published_at DESC)
 WHERE published_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. Tenant üzrə məcburi versiya (Developer Panelindəki "forced update")
-- ---------------------------------------------------------------------------
ALTER TABLE license_tenants
    ADD COLUMN IF NOT EXISTS forced_update_version TEXT;

COMMENT ON COLUMN license_tenants.forced_update_version IS
    'Bu tenant üçün məcburi edilmiş versiya (bölmə 8 — "seçilmiş tenant-a"). '
    'Bütün tenant-lar üçün məcburilik app_releases.mandatory_below ilə verilir.';

-- ---------------------------------------------------------------------------
-- 3. RLS — kataloq hamı üçün OXUNAN, heç kim üçün YAZILAN deyil
-- ---------------------------------------------------------------------------
-- Buraxılış siyahısında məxfi məlumat yoxdur (versiya, hash, fayl adı), lakin
-- YAZMA hüququ kritikdir: kataloqa sətir əlavə edə bilən tərəf bütün
-- quraşdırmalara paket təklif edə bilərdi. Ona görə YALNIZ `SELECT` siyasəti
-- yaradılır — siyasəti olmayan əməliyyat RLS-də QADAĞANDIR.
ALTER TABLE app_releases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS everyone_reads_releases ON app_releases;
CREATE POLICY everyone_reads_releases ON app_releases
    FOR SELECT
    USING (published_at IS NOT NULL);

DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        RAISE NOTICE 'Rol "%" yoxdur — GRANT/REVOKE atlandı.', v_role;
        RETURN;
    END IF;
    EXECUTE format('GRANT SELECT ON app_releases TO %I', v_role);
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON app_releases FROM %I', v_role);
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Ehtiyat nüsxə: yalnız görünüş (cədvəl schema.sql-dədir)
-- ---------------------------------------------------------------------------
-- `backup_records` və `cron_prune_expired_backups()` artıq mövcuddur. Burada
-- yalnız operativ görünüş əlavə olunur: "son nüsxə nə vaxt alınıb və
-- ETİBARLIDIRMI". Bunsuz gecəlik cron-un sükutla dayanması yalnız bərpa
-- lazım olan gün üzə çıxardı — yəni ən pis anda.
DROP VIEW IF EXISTS v_backup_health;
CREATE VIEW v_backup_health WITH (security_invoker = true) AS
SELECT
    b.tenant_id,
    max(b.created_at)                                    AS last_backup_at,
    count(*) FILTER (WHERE b.created_at > now() - INTERVAL '7 days')  AS backups_last_7_days,
    max(b.size_bytes) FILTER (WHERE b.created_at > now() - INTERVAL '2 days')
                                                         AS latest_size_bytes,
    bool_or(b.created_at > now() - INTERVAL '36 hours')   AS is_fresh,
    min(b.retention_until)                               AS earliest_retention_until
  FROM backup_records b
 GROUP BY b.tenant_id;

COMMENT ON VIEW v_backup_health IS
    'System Health Monitor sətri (bölmə 6): son nüsxə təzədirmi. '
    'is_fresh = FALSE → gecəlik cron işləmir.';

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: `app_releases` silinsə avtomatik yenilənmə tamamilə dayanar —
-- təhlükəsizlik yamaqları müştərilərə ÇATMAZ. Bu, sükutla baş verər, çünki
-- klient "kataloq boşdur" halını normal sayır (bax `decide`).
--
-- BEGIN;
--   DROP VIEW IF EXISTS v_backup_health;
--   DROP POLICY IF EXISTS everyone_reads_releases ON app_releases;
--   ALTER TABLE app_releases DISABLE ROW LEVEL SECURITY;
--   DROP INDEX IF EXISTS idx_releases_channel_published;
--   DROP TABLE IF EXISTS app_releases;
--   ALTER TABLE license_tenants DROP COLUMN IF EXISTS forced_update_version;
-- COMMIT;
