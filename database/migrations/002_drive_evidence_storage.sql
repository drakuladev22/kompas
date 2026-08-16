-- ===========================================================================
-- MIGRATION 002 — CƏRİMƏ SÜBUT ŞƏKİLLƏRİ GOOGLE DRIVE-DA
-- ===========================================================================
-- Tarix   : 2026-08-09
-- Səbəb   : Cərimə sübut şəkilləri Supabase Storage-dan Google Drive-a keçir.
--           DİGƏR şəkil növləri (profil şəkli, tapşırıq sübutu) TOXUNULMUR.
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `photo_evidence_url` SİLİNMİR
-- ---------------------------------------------------------------------------
-- İki səbəb:
--   1. Köçürülməzdən ƏVVƏL yaradılmış cərimələrin sübutu hələ Supabase
--      Storage-dadır. Sütun silinsəydi həmin şəkillər həmişəlik itərdi —
--      cərimə etirazının yeganə sübutu odur.
--   2. `chk_fine_manual_requires_evidence` manual cərimədə sübutun MƏCBURİ
--      olmasını təmin edir. Şəkil Drive-a ASİNXRON yükləndiyi üçün cərimə
--      yaradılan anda hələ `evidence_drive_file_id` YOXDUR — məhdudiyyət
--      "hər hansı sübut mənbəyi göstərilib" formasına genişləndirilir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. ENUM: Drive bağlantısının vəziyyəti
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regtype('drive_connection_status') IS NULL THEN
        CREATE TYPE drive_connection_status AS ENUM (
            'ACTIVE',          -- yeni yükləmələr bura gedir (tenant başına TƏK)
            'ARCHIVED',        -- köhnə hesab: yeni yazı yox, OXUMA davam edir
            'QUOTA_EXCEEDED'   -- dolub — yükləmələr lokal buferdə gözləyir
        );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. drive_connections
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS drive_connections (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    google_account_email  TEXT NOT NULL,
    -- AES-256-GCM (AAD = 'drive_connection:<id>') — plaintext QADAĞANDIR.
    -- Sütun adı tarixi səbəbdən "oauth_refresh_token"-dir; məzmun ŞİFRƏLİDİR.
    oauth_refresh_token   TEXT NOT NULL,
    -- Drive-dakı kök qovluq ("KompasOS") — hər dəfə axtarmamaq üçün keşlənir.
    root_folder_id        TEXT,
    status                drive_connection_status NOT NULL DEFAULT 'ACTIVE',

    -- Kvota: dövri yenilənən keşlənmiş dəyərlər (bax quota_monitor).
    quota_used_bytes      BIGINT,
    quota_total_bytes     BIGINT,
    quota_checked_at      TIMESTAMPTZ,
    quota_warning_sent_at TIMESTAMPTZ,     -- təkrar xəbərdarlıq spam-ının qarşısı

    connected_by          UUID REFERENCES employees(id),
    connected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at           TIMESTAMPTZ,
    last_error            TEXT,
    last_error_at         TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_drive_email
        CHECK (google_account_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    CONSTRAINT chk_drive_quota
        CHECK (quota_used_bytes IS NULL OR quota_used_bytes >= 0),
    CONSTRAINT chk_drive_archived
        CHECK (status <> 'ARCHIVED' OR archived_at IS NOT NULL)
);

-- ƏSAS QAYDA: tenant başına EYNİ ANDA yalnız BİR aktiv bağlantı.
-- Partial unique index seçilib, CHECK yox: CHECK sətirlərarası şərti ifadə
-- edə bilmir, trigger isə yarış şəraitində (iki paralel tranzaksiya) sıza
-- bilər. Unikal indeks bunu DB səviyyəsində atomik təmin edir.
CREATE UNIQUE INDEX IF NOT EXISTS uq_drive_one_active_per_tenant
    ON drive_connections (tenant_id) WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_drive_connections_tenant
    ON drive_connections (tenant_id, status);

DROP TRIGGER IF EXISTS trg_drive_connections_updated ON drive_connections;
CREATE TRIGGER trg_drive_connections_updated BEFORE UPDATE ON drive_connections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE drive_connections IS
    'Tenant-ın öz Google Drive hesabı (developer-in paylaşılan Drive-ı DEYİL) — '
    'data mülkiyyəti və kvota müstəqilliyi üçün. Drive dolduqda admin yeni '
    'hesab qoşur, köhnəsi ARCHIVED olur və oradakı şəkillər OXUNMAĞA davam edir.';

COMMENT ON COLUMN drive_connections.oauth_refresh_token IS
    'AES-256-GCM ilə şifrələnmiş refresh token (AAD = drive_connection:<id>). '
    'Plaintext saxlamaq bütün cərimə arxivinə çıxış vermək demək olardı.';

-- ---------------------------------------------------------------------------
-- 3. drive_folder_cache — mağaza+ay qovluq ID-ləri
-- ---------------------------------------------------------------------------
-- Niyə keş: hər yükləmədə Drive API-yə "bu qovluq varmı?" sorğusu getsəydi,
-- gündə yüzlərlə əlavə sorğu olardı və Drive API kvotası (istifadəçi başına
-- 100 sorğu/100 saniyə) tez tükənərdi.
CREATE TABLE IF NOT EXISTS drive_folder_cache (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    drive_connection_id  UUID NOT NULL REFERENCES drive_connections(id) ON DELETE CASCADE,
    store_id             UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    year_month           TEXT NOT NULL,      -- 'YYYY-MM'
    drive_folder_id      TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_folder_year_month CHECK (year_month ~ '^\d{4}-(0[1-9]|1[0-2])$'),
    -- Açar `drive_connection_id`-ni DƏ əhatə edir: hesab dəyişəndə eyni
    -- mağaza/ay üçün YENİ hesabda yeni qovluq lazımdır, köhnə keş sətri isə
    -- köhnə hesabın qovluğunu göstərməyə davam edir.
    UNIQUE (drive_connection_id, store_id, year_month)
);

CREATE INDEX IF NOT EXISTS idx_drive_folder_cache_lookup
    ON drive_folder_cache (drive_connection_id, store_id, year_month);

COMMENT ON TABLE drive_folder_cache IS
    'AYLIQ ROTASİYA burada TƏBİİ şəkildə baş verir: qovluq adında {İl-Ay} '
    'olduğu üçün ay dəyişəndə axtarış açarı dəyişir, keşdə tapılmır və yeni '
    'qovluq lazy şəkildə yaradılır. Ayrıca "arxivləmə" əməliyyatı LAZIM DEYİL.';

-- ---------------------------------------------------------------------------
-- 4. fines — Drive istinadları
-- ---------------------------------------------------------------------------
ALTER TABLE fines
    ADD COLUMN IF NOT EXISTS evidence_drive_file_id TEXT,
    -- HANSI hesaba yükləndiyi: hesab dəyişdikdə köhnə keçidlər qırılmasın.
    -- ON DELETE RESTRICT DEYİL — SEC-015: dərhal yoxlanan məhdudiyyət tenant
    -- silinməsini bloklayır. Bağlantı silinsə sətir NULL olur, `photo_evidence_url`
    -- və audit izi qalır.
    ADD COLUMN IF NOT EXISTS evidence_drive_connection_id UUID
        REFERENCES drive_connections(id) ON DELETE SET NULL,
    -- Asinxron yükləmənin vəziyyəti (cərimə yaradılışını BLOKLAMIR).
    ADD COLUMN IF NOT EXISTS evidence_upload_status sync_status NOT NULL DEFAULT 'SYNCED';

CREATE INDEX IF NOT EXISTS idx_fines_evidence_pending
    ON fines (created_at) WHERE evidence_upload_status = 'PENDING';

COMMENT ON COLUMN fines.evidence_drive_connection_id IS
    'Şəklin HANSI Drive hesabında olduğu. Yeni hesab qoşulduqda KÖHNƏ '
    'sətirlərin bu sahəsi DƏYİŞMİR — köhnə şəkillər öz hesabından oxunur.';

-- Sübut məcburiyyəti: artıq Supabase URL-i VƏ YA Drive fayl ID-si VƏ YA
-- yüklənməni gözləyən vəziyyət qəbul olunur.
ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_manual_requires_evidence;
ALTER TABLE fines ADD CONSTRAINT chk_fine_manual_requires_evidence
    CHECK (source <> 'MANUAL_CAMERA'
        OR (fine_type_id IS NOT NULL
            AND issued_by IS NOT NULL
            AND (photo_evidence_url IS NOT NULL
                 OR evidence_drive_file_id IS NOT NULL
                 OR evidence_upload_status = 'PENDING')));

-- ---------------------------------------------------------------------------
-- 5. İCAZƏ FLAG-İ: can_manage_drive_connection
-- ---------------------------------------------------------------------------
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level, is_anti_fraud, is_camera_only)
VALUES
    ('can_manage_drive_connection', 'ERP_INFRA', 'Drive bağlantısını idarə et',
     'Cərimə sübut şəkilləri üçün Google Drive hesabı qoşmaq/arxivləşdirmək',
     0, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- Sistem şablonlarına (tenant_id IS NULL) VƏ mövcud tenant kopyalarına ver.
-- `seed_tenant_defaults` yalnız YENİ tenant-lar üçün işləyir, ona görə
-- mövcud tenant-lar burada ayrıca yenilənir.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_drive_connection', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. RLS — yeni cədvəllər də fail-closed olmalıdır (SEC-008)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['drive_connections', 'drive_folder_cache'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I
                 USING (tenant_id = current_tenant_id())
                 WITH CHECK (tenant_id = current_tenant_id())', t
        );
    END LOOP;
END
$$;

-- Tətbiq rolu yeni cədvəlləri görməlidir (schema.sql-dəki GRANT yalnız
-- həmin an mövcud olan cədvəllərə tətbiq olunub).
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON drive_connections, '
            'drive_folder_cache TO %I', v_role
        );
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
    END IF;
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: `drive_connections` silinsə şifrələnmiş refresh token-lər itir və
-- Drive-dakı mövcud şəkillərə proqram vasitəsilə çıxış bərpa oluna bilməz
-- (fayllar Drive-da qalır, lakin hansı qovluqda olduqları keşdən silinir).
--
-- BEGIN;
--   ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_manual_requires_evidence;
--   ALTER TABLE fines ADD CONSTRAINT chk_fine_manual_requires_evidence
--       CHECK (source <> 'MANUAL_CAMERA'
--           OR (fine_type_id IS NOT NULL AND photo_evidence_url IS NOT NULL
--               AND issued_by IS NOT NULL));
--   ALTER TABLE fines
--       DROP COLUMN IF EXISTS evidence_drive_file_id,
--       DROP COLUMN IF EXISTS evidence_drive_connection_id,
--       DROP COLUMN IF EXISTS evidence_upload_status;
--   DELETE FROM position_permissions WHERE flag_code = 'can_manage_drive_connection';
--   DELETE FROM permission_flags WHERE code = 'can_manage_drive_connection';
--   DROP TABLE IF EXISTS drive_folder_cache;
--   DROP TABLE IF EXISTS drive_connections;
--   DROP TYPE IF EXISTS drive_connection_status;
-- COMMIT;
