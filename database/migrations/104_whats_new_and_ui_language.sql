-- ===========================================================================
-- 104 — LOKALLAŞDIRMA + «NƏ YENİ?» (v2backlog.md Faza 8) — AÇAR + CƏDVƏL + FLAG
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 8 — çox-dil DƏSTƏYİ əsası (yalnız struktur,
--         rus dili TƏRCÜMƏ EDİLMİR) və «Nə Yeni?» versiya-qeydləri ekranı.
--
-- ---------------------------------------------------------------------------
-- 1. UI_LANGUAGE ROOT AÇARI (Faza 8.1)
-- ---------------------------------------------------------------------------
-- Kirayəçinin interfeys dili. DƏYƏR hazırda yalnız "az" ola bilər — amma
-- yoxlama KODDADIR (`AVAILABLE_UI_LANGUAGES`, `RootControlUseCase.
-- set_language`), DB CHECK deyil: yeni dil əlavəsi kataloq faylıdır,
-- miqrasiya deyil. Root seçimi bu açara yazılır və audit-lənir
-- ("SYSTEM_LIMIT_CHANGED").
--
-- ---------------------------------------------------------------------------
-- 2. `whats_new_entries` CƏDVƏLİ (Faza 8.2)
-- ---------------------------------------------------------------------------
-- Kirayəçi-daxili versiya-qeydləri. Vendor-un `app_versions` cədvəlindən
-- FƏRQLIDIR: orada müəllif TƏCHİZATÇIdır, burada isə kirayəçinin Root-u —
-- iki fərqli müəllif iki fərqli cədvəldədir (bax `use_cases/whats_new.py`
-- başlığı).
--
-- SOFT DELETE (`is_active`): köhnə qeyd dəyişiklik tarixçəsinin sübutudur —
-- fiziki silmə `catalogs.py` əsaslandırmasına zidd olardı.
--
-- ---------------------------------------------------------------------------
-- 3. İKİ FLAG (Faza 8.2)
-- ---------------------------------------------------------------------------
-- Spesifikasiyanın İKİ ayrı cümləsi İKİ flag-dır:
--   * `can_view_whats_new` — «CEO/HR_Admin görünüşündə»: OXU auditoriyası.
--     Defolt Root/CEO/HR_Admin üçlüyü (migrations/021-in attrition naxışı),
--     hardlock_level=0 — baxış flag-idir.
--   * `can_publish_whats_new` — «Root panelindən mətn-əlavə edilə bilən»:
--     YAZAN. Defolt yalnız Root/CEO — daxili ünsiyyət rəsmi məlumatdır,
--     HR_Admin-ə nəşr hüququ verilsəydi menyu maddəsi «rəhbər baxışı»ndan
--     «hər kəs yazar»a çevrilərdi.
--
-- Seed 095/100/102-un İKİ BLOKLU naxışı. Dəyərlər `DEFAULT_LIMITS` ilə
-- HƏRFƏN eynidir. İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. UI_LANGUAGE — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, 'UI_LANGUAGE', 'az', 'STRING', NULL, NULL,
       'Kirayəçinin interfeys dili (v2backlog.md Faza 8.1). Yalnız kataloqda '
       'olan dil kodu yazıla bilər.'
  FROM license_tenants t
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. FLAG KATALOQU
-- ---------------------------------------------------------------------------
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only)
VALUES
    ('can_view_whats_new', 'HR', '"Nə Yeni?" jurnalına bax',
     'v2backlog.md Faza 8.2 - kirayəçi-daxili versiya-qeydlərinin siyahısı. '
     'Spesifikasiya: CEO/HR_Admin görünüşündə. Defolt: Root/CEO/HR_Admin.',
     0, FALSE, FALSE),
    ('can_publish_whats_new', 'HR', '"Nə Yeni?" qeydi nəşr et',
     'v2backlog.md Faza 8.2 - Root panelindən versiya-qeydinin '
     'əlavə edilməsi/söndürülməsi. Daxili rəsmi ünsiyyətdir; defolt yalnız '
     'Root/CEO.',
     0, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

DO $$
DECLARE
    v_wrong TEXT;
BEGIN
    SELECT string_agg(code, ', ')
      INTO v_wrong
      FROM permission_flags
     WHERE code IN ('can_view_whats_new', 'can_publish_whats_new')
       AND (category <> 'HR' OR hardlock_level <> 0
            OR is_anti_fraud <> FALSE OR is_camera_only <> FALSE);

    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: bu flag(lər) ARTIQ mövcuddur, lakin '
            'atributları gözlənilənlə uyğun deyil: %', v_wrong;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. DEFOLT SAHİBLİK
-- ---------------------------------------------------------------------------
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
  FROM positions p
  CROSS JOIN (VALUES ('can_view_whats_new'), ('can_publish_whats_new'))
       AS f(flag_code)
 WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_view_whats_new', TRUE
  FROM positions p
 WHERE p.code = 'HR_ADMIN'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. `whats_new_entries` CƏDVƏLİ
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS whats_new_entries (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- Etiket başlıq zolağında görünür — uzunluq EKRANIN ölçüsünün
    -- nəticəsidir, Root parametri DEYİL (`PANEL_LIMIT` pretsedenti).
    version_label TEXT NOT NULL CHECK (char_length(trim(version_label)) BETWEEN 1 AND 40),
    title_az      TEXT NOT NULL CHECK (char_length(trim(title_az)) >= 3),
    body_az       TEXT NOT NULL CHECK (char_length(trim(body_az)) >= 10),

    -- NO ACTION: "kim nəşr etdi?" sualının cavabı qeydin ÖMRÜNDƏN uzun
    -- yaşayır (`announcements.created_by` ilə eyni əsaslandırma).
    created_by    UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    -- Soft delete: köhnə qeyd dəyişiklik tarixçəsinin hissəsidir.
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at TIMESTAMPTZ,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_whats_new_recent
    ON whats_new_entries (tenant_id, created_at DESC);

COMMENT ON TABLE whats_new_entries IS
    'Faza 8.2 (v2backlog.md): kirayəçi-daxili «Nə Yeni?» versiya-qeydləri. '
    'Müəllif kirayəçinin Root-udur; vendor buraxılış qeydləri '
    '`app_versions.release_notes_az`-dadır — iki fərqli müəllif, iki fərqli '
    'cədvəl.';

ALTER TABLE whats_new_entries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON whats_new_entries;
CREATE POLICY tenant_isolation ON whats_new_entries
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP TRIGGER IF EXISTS trg_whats_new_updated ON whats_new_entries;
CREATE TRIGGER trg_whats_new_updated
    BEFORE UPDATE ON whats_new_entries
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

-- ---------------------------------------------------------------------------
-- 5. UI_LANGUAGE — YENİ KİRAYƏÇİLƏR (095/100/102 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_ui_language_limit_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, description_az)
    VALUES (NEW.tenant_id, 'UI_LANGUAGE', 'az', 'STRING',
            'Kirayəçinin interfeys dili (v2backlog.md Faza 8.1). Yalnız '
            'kataloqda olan dil kodu yazıla bilər.')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_ui_language_limit_for_new_tenant() IS
    'Yeni kirayəçiyə interfeys-dili açarını seedləyir (migrations/104).';

DROP TRIGGER IF EXISTS trg_seed_ui_language_limits ON license_tenants;
CREATE TRIGGER trg_seed_ui_language_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_ui_language_limit_for_new_tenant();

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_ui_language_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_ui_language_limit_for_new_tenant();
--   DROP TRIGGER IF EXISTS trg_whats_new_updated ON whats_new_entries;
--   DROP TABLE IF EXISTS whats_new_entries;
--   DELETE FROM system_limits WHERE limit_key = 'UI_LANGUAGE';
--   DELETE FROM position_permissions
--    WHERE flag_code IN ('can_view_whats_new', 'can_publish_whats_new');
--   DELETE FROM permission_flags
--    WHERE code IN ('can_view_whats_new', 'can_publish_whats_new');
-- COMMIT;
-- ===========================================================================
