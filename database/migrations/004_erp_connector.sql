-- ===========================================================================
-- MIGRATION 004 — 1C KONNEKTORU: OData PARAMETRLƏRİ VƏ SİNXRONİZASİYA KURSORU
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : Faza 3, bənd 2 (spesifikasiya bölmə 6, 7) — "1C Dynamic Connector
--         Manager supporting N parallel servers ... with composite-ID matching
--         + low-confidence review queue".
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `erp_servers`-ə YENİ SÜTUNLAR LAZIMDIR
-- ---------------------------------------------------------------------------
-- `schema.sql` serverin ŞƏBƏKƏ ünvanını saxlayır (host, port, istifadəçi,
-- şifrə), lakin 1C OData ünvanı bununla tamamlanmır:
--
--     http://<host>:<port>/<INFOBASE>/odata/standard.odata/<SƏNƏD>
--                          ^^^^^^^^^^                      ^^^^^^^
--
-- `INFOBASE` (publikasiya adı) olmadan sorğu ünvanı qurula bilmir, `SƏNƏD`
-- adı isə 1C KONFİQURASİYASINDAN asılıdır (Bellona/İstikbal/Yataş/Enza üçün
-- ayrı-ayrı bazalar ola bilər). Hər ikisini koda bərk-yazmaq müştərini yeni
-- baza əlavə edərkən HAZIRLAYICIYA müraciət etməyə məcbur edərdi — bu, bölmə
-- 7-nin özünə-xidmət prinsipinin birbaşa pozulmasıdır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ KURSOR SÜTUNLARI (`sync_cursor_at` + `sync_cursor_document_ids`)
-- ---------------------------------------------------------------------------
-- Sinxronizasiya "harada qaldım" sualına cavab verməlidir. Yalnız vaxt
-- damğası saxlansaydı iki səhvdən biri qaçılmaz olardı:
--
--     `>` ilə davam  → son sənədlə EYNİ saniyədəki digər çeklər ATLANIR
--     `>=` ilə davam → sərhəd sənədləri hər dövrdə TƏKRAR emal olunur
--
-- Ona görə sorğu `>=` ilə gedir, sərhəd saniyəsindəki sənəd ID-ləri isə
-- massivdə saxlanılıb süzülür. Atlanan satış işçinin premiyasından itərdi —
-- təkrar oxuma isə yalnız ucuz şəbəkə trafikidir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. erp_servers — OData ünvanı və sənəd adlandırması
-- ---------------------------------------------------------------------------
ALTER TABLE erp_servers
    ADD COLUMN IF NOT EXISTS infobase TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS use_https BOOLEAN NOT NULL DEFAULT FALSE,
    -- NULL = defolt adlandırma (bax `one_c_connector.OneCDocumentMapping`).
    -- Yalnız qeyri-standart konfiqurasiyalar üçün doldurulur.
    ADD COLUMN IF NOT EXISTS document_mapping_json JSONB;

COMMENT ON COLUMN erp_servers.infobase IS
    '1C publikasiya (infobase) adı — OData ünvanının tərkib hissəsi. '
    'Bağlantı Sihirbazındakı [Bağlantını Test Et] bunu doğrulayır.';

-- Serveri AKTİV etmək üçün infobase MƏCBURİDİR. Boş infobase ilə aktiv
-- server "işləyir" görünüb hər dövrdə sükutla xəta verərdi.
ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_active_requires_infobase;
ALTER TABLE erp_servers ADD CONSTRAINT chk_erp_active_requires_infobase
    CHECK (status <> 'ACTIVE' OR length(trim(infobase)) > 0);

-- ---------------------------------------------------------------------------
-- 2. erp_servers — sinxronizasiya kursoru və sağlamlıq sayğacları
-- ---------------------------------------------------------------------------
ALTER TABLE erp_servers
    ADD COLUMN IF NOT EXISTS sync_cursor_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sync_cursor_document_ids TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS last_sync_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0
        CHECK (consecutive_failures >= 0);

COMMENT ON COLUMN erp_servers.sync_cursor_document_ids IS
    'Sərhəd saniyəsində artıq emal olunmuş sənəd ID-ləri. `>=` filtrinin '
    'qaçılmaz təkrarını süzür — bax migration başlığı.';

-- ---------------------------------------------------------------------------
-- 3. sales_transactions — nəzərdən keçirmə növbəsi üçün əlavələr
-- ---------------------------------------------------------------------------
-- `confidence` sütunu artıq var. Çatışmayan: fallback-ın NİYƏ belə qərar
-- verdiyi. Bu izah olmadan HR_Admin "Şübhəli Uyğunlaşma" növbəsində sətri
-- görür, amma nəyə görə şübhəli olduğunu bilmir və hər dəfə 1C-yə baxmalı
-- olur (bölmə 7: dəstək yükünü azaltma prinsipi).
ALTER TABLE sales_transactions
    ADD COLUMN IF NOT EXISTS match_reason TEXT,
    -- 1C-dəki satıcı adı — uyğunlaşma insan tərəfindən yoxlanarkən lazımdır.
    ADD COLUMN IF NOT EXISTS one_c_seller_name TEXT;

-- ---------------------------------------------------------------------------
-- 4. Sağlamlıq görünüşü — System Health Monitor (bölmə 6, hər server AYRI sətir)
-- ---------------------------------------------------------------------------
-- Hesablama SQL-də saxlanılır ki, GUI (Faza 5) və gələcək telemetriya eyni
-- tərifi paylaşsın — iki yerdə təkrarlansaydı biri gec-tez sürüşərdi.
DROP VIEW IF EXISTS v_erp_server_health;
CREATE VIEW v_erp_server_health AS
SELECT
    s.id                AS server_id,
    s.tenant_id,
    s.server_name,
    s.host,
    s.status,
    s.last_successful_sync,
    s.last_error,
    s.last_error_at,
    s.consecutive_failures,
    s.sync_interval_seconds,
    EXTRACT(EPOCH FROM (now() - s.last_successful_sync))::BIGINT AS sync_delay_seconds,
    CASE
        WHEN s.status = 'INACTIVE' THEN 'INACTIVE'
        WHEN s.last_successful_sync IS NULL THEN 'NEVER_SYNCED'
        -- Gecikmə intervalın 3 mislindən çoxdursa problem VAR: bir dövrün
        -- ötürülməsi normal ola bilər (şəbəkə), üç dövr isə yox.
        WHEN now() - s.last_successful_sync
             > (s.sync_interval_seconds * 3) * INTERVAL '1 second' THEN 'STALE'
        WHEN s.consecutive_failures > 0 THEN 'DEGRADED'
        ELSE 'HEALTHY'
    END AS health,
    (SELECT count(*) FROM store_server_mapping m WHERE m.server_id = s.id) AS mapped_stores
FROM erp_servers s;

COMMENT ON VIEW v_erp_server_health IS
    'System Health Monitor sətirləri (bölmə 6): hər 1C serveri üçün ayrıca '
    'status, son sync və gecikmə. `can_view_system_health` flag-i ilə görünür.';

-- ---------------------------------------------------------------------------
-- 5. İndekslər
-- ---------------------------------------------------------------------------
-- Sync planlayıcısı "növbəti hansı server?" sualını hər dövrdə verir.
CREATE INDEX IF NOT EXISTS idx_erp_servers_syncable
    ON erp_servers (tenant_id, status) WHERE status <> 'INACTIVE';

-- Mağaza kodu → mağaza həlli hər sənəd üçün aparılır.
CREATE INDEX IF NOT EXISTS idx_store_server_mapping_code
    ON store_server_mapping (server_id, one_c_store_code);

-- ---------------------------------------------------------------------------
-- 6. RLS — yeni görünüş sahibin hüquqları ilə işləməməlidir
-- ---------------------------------------------------------------------------
-- `security_invoker` olmadan view SAHİBİN hüquqları ilə oxunur və RLS-i yan
-- keçərdi: bir tenant-ın admini başqa tenant-ın serverlərini görərdi.
ALTER VIEW v_erp_server_health SET (security_invoker = true);

DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format('GRANT SELECT ON v_erp_server_health TO %I', v_role);
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
    END IF;
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: `sync_cursor_at`/`sync_cursor_document_ids` silinsə növbəti
-- sinxronizasiya SIFIRDAN başlayar. Sənədlər `UNIQUE (server_id,
-- one_c_document_id)` ilə təkrarlanmaz, yəni məlumat pozulmaz — lakin ilk
-- dövr bütün 1C tarixçəsini oxuyacağı üçün uzun sürər.
--
-- BEGIN;
--   DROP VIEW IF EXISTS v_erp_server_health;
--   DROP INDEX IF EXISTS idx_store_server_mapping_code;
--   DROP INDEX IF EXISTS idx_erp_servers_syncable;
--   ALTER TABLE sales_transactions
--       DROP COLUMN IF EXISTS match_reason,
--       DROP COLUMN IF EXISTS one_c_seller_name;
--   ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_active_requires_infobase;
--   ALTER TABLE erp_servers
--       DROP COLUMN IF EXISTS infobase,
--       DROP COLUMN IF EXISTS use_https,
--       DROP COLUMN IF EXISTS document_mapping_json,
--       DROP COLUMN IF EXISTS sync_cursor_at,
--       DROP COLUMN IF EXISTS sync_cursor_document_ids,
--       DROP COLUMN IF EXISTS last_sync_started_at,
--       DROP COLUMN IF EXISTS consecutive_failures;
-- COMMIT;
