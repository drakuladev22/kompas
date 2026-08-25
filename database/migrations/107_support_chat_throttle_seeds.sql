-- ===========================================================================
-- 107 — DƏSTƏK-CHAT SÜRƏT SAYĞACI SEED (v2backlog.md Faza 12.1)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : migrations/090-nın ÖZ TƏLƏBİ («Domen `SystemLimitKey` əlavə
--         edəndən SONRA SQL seed-i 084-ün naxışı ilə AYRI miqrasiyada
--         gəlməlidir»). Domen açarları İNDİ mövcuddur (`policies.py`) —
--         seed onların vaxtıdır.
--
-- DƏYƏRLƏR `DEFAULT_LIMITS` ilə HƏRFƏN eynidir və 090 trigger-inin
-- COALESCE fallback-ları ilə üst-üstə düşür: fallback yalnız sətir
-- seed edilməmiş quraşdırmada işləyir, normal yolda HƏQİQİ MƏNBƏ bu
-- sütunlardır.
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('SUPPORT_CHAT_MAX_MESSAGES_PER_MINUTE', '20', 'INTEGER', '3', '200',
     'Bir işçinin dəqiqədə göndərə biləcəyi maksimum dəstək mesajı '
     '(v2backlog.md Faza 12.1). Aşılırsa qiflənir.'),
    ('SUPPORT_CHAT_LOCKOUT_MINUTES', '5', 'INTEGER', '1', '60',
     'Mesaj həddi aşan işçinin dəstək-chatı neçə dəqiqə qiflənir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR (095/100/102 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_support_chat_throttle_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('SUPPORT_CHAT_MAX_MESSAGES_PER_MINUTE', '20', 'INTEGER', '3', '200',
         'Bir işçinin dəqiqədə göndərə biləcəyi maksimum dəstək mesajı '
         '(v2backlog.md Faza 12.1). Aşılırsa qiflənir.'),
        ('SUPPORT_CHAT_LOCKOUT_MINUTES', '5', 'INTEGER', '1', '60',
         'Mesaj həddi aşan işçinin dəstək-chatı neçə dəqiqə qiflənir')
     ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_support_chat_throttle_limits_for_new_tenant() IS
    'Yeni kirayəçiyə dəstək-chat sürət sayğacı açarlarını seedləyir '
    '(migrations/107; 090 trigger-inin COALESCE fallback-ları ilə eyni).';

DROP TRIGGER IF EXISTS trg_seed_support_chat_throttle_limits ON license_tenants;
CREATE TRIGGER trg_seed_support_chat_throttle_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_support_chat_throttle_limits_for_new_tenant();

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_support_chat_throttle_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_support_chat_throttle_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'SUPPORT_CHAT_MAX_MESSAGES_PER_MINUTE',
--       'SUPPORT_CHAT_LOCKOUT_MINUTES');
-- COMMIT;
-- ===========================================================================
