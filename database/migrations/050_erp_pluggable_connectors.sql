-- ===========================================================================
-- 050 — 1C İNTEQRASİYASI: DƏYİŞDİRİLƏ BİLƏN (PLUGGABLE) BAĞLANTI NÖVLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : 1c.md — hər müştərinin 1C-si FƏRQLİ üsulla inteqrasiya oluna bilər
--         (HTTP/OData, COM, fayl-mübadiləsi). Seçim koda bərk-yazıla bilməz,
--         Root/CEO panelindən edilməlidir.
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- QIRMIZI XƏTT: MÖVCUD SƏTİRLƏR TOXUNULMUR
-- ---------------------------------------------------------------------------
-- `connector_type` sütunu `DEFAULT 'HTTP'` ilə gəlir və mövcud hər sətir
-- həmin dəyəri alır. Bu, təxmin DEYİL: migrations/004-ə qədər `erp_servers`
-- YALNIZ OData konnektoru üçün mövcud idi (`infobase`, `use_https`,
-- `document_mapping_json` sütunlarının hamısı OData ünvanına aiddir). Sütunu
-- `NULL` buraxıb "tip naməlumdur" desəydik, miqrasiya günü bütün mövcud
-- serverlər sinxronizasiya növbəsindən düşərdi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ JSON SÜTUN, NİYƏ HƏR TİP ÜÇÜN AYRI SÜTUNLAR DEYİL
-- ---------------------------------------------------------------------------
-- Üç tipin parametr dəstləri KƏSİŞMİR:
--
--     HTTP           host, port, infobase, use_https      (ARTIQ SÜTUNLARDADIR)
--     COM            server/fayl-yolu, baza adı, sorğu mətninin dili, metadata
--                    adları
--     FILE_EXCHANGE  qovluq, fayl formatı, şablon, kodlaşdırma, ayırıcı,
--                    sütun adları, tarix şablonu
--
-- Ayrı-ayrı sütunlar variantı RƏDD EDİLDİ, çünki:
--
--   (a) hər sütun `NULL` ola bilən olmalıdır (tipin biri üçün məcburi, digəri
--       üçün mənasız) — yəni cədvəl 12+ `NULL` sütun qazanır və `NOT NULL`
--       invariantlarının HEÇ BİRİ ifadə edilə bilmir;
--   (b) dördüncü tip (məs. REST API, SQL view) əlavə edildikdə hər dəfə yeni
--       miqrasiya və yeni `NULL` sütun dəstəsi lazım olardı;
--   (c) həmin sütunların bir qismi SİRR daşıyır (COM parolu) və onları açıq
--       mətndə saxlamaq SEC-013-ün birbaşa pozulmasıdır — hər sirr sütunu
--       ayrıca şifrələnməli olardı.
--
-- Seçilən variant: TƏK bir `connector_config_encrypted` sütunu, içində JSON
-- sənəd, BÜTÖV şəkildə AES-256-GCM ilə şifrələnmiş.
--
-- ---------------------------------------------------------------------------
-- SÜTUN ADI NİYƏ `connector_config` DEYİL, `connector_config_encrypted`
-- ---------------------------------------------------------------------------
-- 1c.md `connector_config` adını təklif edir, lakin həmin sütun `JSONB` deyil,
-- şifrələnmiş MƏTNdir. Adı sadəcə `connector_config` qoysaydıq, növbəti
-- inkişafçı ona `jsonb_set(...)` ilə müdaxilə etməyə çalışar və/və ya açıq
-- JSON yazardı — sirr həmin anda açıq mətnə düşərdi. `_encrypted` şəkilçisi
-- cədvəldəki `password_encrypted` və `config_json_encrypted` sütunları ilə
-- eyni siqnalı verir: "burada oxunan mətn YOXDUR".
--
-- JSONB-nin sorğulana bilməsi qazancı BURADA ONSUZ DA MÜMKÜN DEYİL: şifrəli
-- dəyəri indeksləmək və ya `->>` ilə süzmək olmur. Yəni tip seçimi ilə heç bir
-- funksionallıq itmir.
--
-- ---------------------------------------------------------------------------
-- `host` / `port` / `username` — `NOT NULL` PROBLEMİ NECƏ HƏLL OLUNDU
-- ---------------------------------------------------------------------------
-- Üç sütun da `NOT NULL`-dur və HTTP modelinə görə adlandırılıb. Üç variant
-- nəzərdən keçirildi:
--
--   (1) Sütunları `NULL` edilə bilən etmək — RƏDD: mövcud HTTP sətirlərində
--       ünvanın MƏCBURİ olması qorunmalıdır. `NULL` buraxılsa, ünvansız aktiv
--       HTTP serveri yaradıla bilər və nasazlıq yalnız sinxronizasiya dövründə
--       üzə çıxar.
--   (2) COM/FILE üçün süni mətn ("n/a", "-") yazmaq — RƏDD: həmin dəyər
--       ekranda GÖRÜNƏRDİ və istifadəçi "n/a:0" ünvanını nasazlıq sayardı.
--   (3) SEÇİLDİ — `host` sütunu TİPƏ GÖRƏ oxunan ÜNVAN sahəsinə çevrildi,
--       `port` isə şərti CHECK ilə idarə olunur:
--
--           HTTP           host = şəbəkə ünvanı,          port = 1..65535
--           COM            host = 1C server adı / qovluq, port = 0
--           FILE_EXCHANGE  host = mübadilə qovluğu,       port = 0
--
--       `port = 0` SENTİNELDİR və ekranda göstərilmir (domen qaydası:
--       `ErpServer.display_address`). Sentinelin özü CHECK ilə MƏCBURİ edilir
--       — əks halda tip dəyişdirildikdə köhnə HTTP portu sətirdə qalar və
--       "hansı port işlədilir?" sualı cavabsız qalardı.
--
--       `username` toxunulmadı: o, HTTP-də də boş ola bilir (1C-nin Windows
--       autentifikasiyası) və `NOT NULL` boş sətri ONSUZ DA qəbul edir.
--       Fayl mübadiləsində sadəcə boş qalır.
--
-- NİYƏ ÜNVAN ŞİFRƏLİ KONFİQURASİYADA DEYİL, AÇIQ `host` SÜTUNUNDA:
-- Qovluq yolu və server adı SİRR DEYİL (parol sirrdir) və onlar server
-- siyahısında, sağlamlıq görünüşündə və audit sətrində GÖRÜNMƏLİDİR. Şifrəli
-- sütunda saxlasaydıq, hər siyahı sorğusu deşifrə tələb edərdi — yəni sirr
-- oxumaq ADİ əməliyyata çevrilər və `ERP_CREDENTIALS_ACCESSED` audit siqnalı
-- mənasını itirərdi.
--
-- ---------------------------------------------------------------------------
-- AKTİVLƏŞDİRMƏ QAPISI TİPƏ GÖRƏ DƏYİŞİR
-- ---------------------------------------------------------------------------
-- migrations/004 `chk_erp_active_requires_infobase` qoyub: aktiv server üçün
-- baza adı MƏCBURİDİR. Fayl mübadiləsində isə 1C bazası ilə BİRBAŞA əlaqə
-- yoxdur — orada məcburi olan qovluq yoludur. Köhnə CHECK olduğu kimi
-- qalsaydı, düzgün qurulmuş fayl serveri HEÇ VAXT aktivləşməzdi.
--
-- Yeni CHECK hər iki halı əhatə edir və köhnəsini ƏVƏZ EDİR (silmir —
-- dəyişdirir): HTTP/COM üçün qayda HƏRFƏN eynidir.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. YENİ SÜTUNLAR
-- ---------------------------------------------------------------------------
ALTER TABLE erp_servers
    ADD COLUMN IF NOT EXISTS connector_type TEXT NOT NULL DEFAULT 'HTTP',
    -- NULL = tipə xas əlavə parametr YOXDUR (tipik HTTP sətri). Boş JSON
    -- (`{}`) əvəzinə NULL seçilib: sütunun dolu olması "bu serverin tipə xas
    -- konfiqurasiyası var" deməkdir və diaqnostikada bu fərq görünür.
    ADD COLUMN IF NOT EXISTS connector_config_encrypted TEXT;

-- CHECK ayrıca əlavə olunur ki, sütun artıq mövcud olan bazada da qoyulsun
-- (`ADD COLUMN IF NOT EXISTS` mövcud sütuna CHECK əlavə etmir).
ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_connector_type;
ALTER TABLE erp_servers ADD CONSTRAINT chk_erp_connector_type
    CHECK (connector_type IN ('HTTP', 'COM', 'FILE_EXCHANGE'));

COMMENT ON COLUMN erp_servers.connector_type IS
    '1C ilə əlaqənin ÜSULU (1c.md): HTTP (OData veb-servisi) / COM '
    '(V83.COMConnector, yalnız Windows) / FILE_EXCHANGE (şəbəkə qovluğundakı '
    'CSV/XML ixracı). Defolt HTTP — migrations/050-dən əvvəlki bütün sətirlər '
    'OData ilə qurulub. Domen qarşılığı: `ConnectorType`.';

COMMENT ON COLUMN erp_servers.connector_config_encrypted IS
    'Bağlantı növünə XAS parametrlərin JSON sənədi, BÜTÖV şəkildə AES-256-GCM '
    'ilə şifrələnmiş (AAD = "erp_server:<id>", `password_encrypted` ilə eyni '
    'naxış). Sözlükdə sirr ola bilər (COM parolu, fayl-paylaşımı kimlik '
    'məlumatı), ona görə açıq mətn QADAĞANDIR. NULL = tipə xas parametr yoxdur.';

COMMENT ON COLUMN erp_servers.host IS
    'TİPƏ GÖRƏ oxunan ünvan sahəsi: HTTP-də şəbəkə ünvanı, COM-da 1C server '
    'adı (və ya fayl bazasının qovluğu), FILE_EXCHANGE-də mübadilə qovluğunun '
    'yolu. Sirr DEYİL və ekranda göstərilir — bax migrations/050 başlığı.';

COMMENT ON COLUMN erp_servers.port IS
    'Şəbəkə portu — YALNIZ HTTP tipində mənalıdır (1..65535). COM və '
    'FILE_EXCHANGE sətirlərində sentinel 0 saxlanılır və ekranda göstərilmir '
    '(`ErpServer.display_address`). Qayda `chk_erp_port_matches_connector_type` '
    'ilə MƏCBURİDİR: əks halda tip dəyişdirildikdə köhnə port sətirdə qalardı.';

-- ---------------------------------------------------------------------------
-- 2. PORT CHECK-İ ŞƏRTİLƏŞDİRİLİR
-- ---------------------------------------------------------------------------
-- `schema.sql`-dəki inline CHECK (`port BETWEEN 1 AND 65535`) PostgreSQL
-- tərəfindən `erp_servers_port_check` adlandırılır. Onu SİLMİRİK, ƏVƏZ
-- EDİRİK: HTTP üçün eyni aralıq qüvvədə qalır.
ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS erp_servers_port_check;
ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_port_matches_connector_type;
ALTER TABLE erp_servers ADD CONSTRAINT chk_erp_port_matches_connector_type
    CHECK (
        (connector_type = 'HTTP' AND port BETWEEN 1 AND 65535)
        OR (connector_type <> 'HTTP' AND port = 0)
    );

-- ---------------------------------------------------------------------------
-- 3. AKTİVLƏŞDİRMƏ QAPISI — TİPƏ GÖRƏ
-- ---------------------------------------------------------------------------
-- Köhnə CHECK (migrations/004) yalnız `infobase` tələb edirdi. Yeni qayda:
--     HTTP / COM      → baza adı (infobase) MƏCBURİ  (əvvəlki ilə HƏRFƏN eyni)
--     FILE_EXCHANGE   → mübadilə qovluğu (host) MƏCBURİ
--
-- Qovluğun ÖZÜNÜN mövcudluğunu DB yoxlaya BİLMƏZ (o, şəbəkə resursudur) —
-- bunu konnektorun `test_connection`-u edir və sihirbaz test uğursuz olduqda
-- sətri onsuz da yazmır.
ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_active_requires_infobase;
ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_active_requires_config;
ALTER TABLE erp_servers ADD CONSTRAINT chk_erp_active_requires_config
    CHECK (
        status <> 'ACTIVE'
        OR (connector_type = 'FILE_EXCHANGE' AND length(trim(host)) > 0)
        OR (connector_type <> 'FILE_EXCHANGE' AND length(trim(infobase)) > 0)
    );

-- ---------------------------------------------------------------------------
-- 4. SAĞLAMLIQ GÖRÜNÜŞÜ — `connector_type` VƏ `port` ƏLAVƏ OLUNUR
-- ---------------------------------------------------------------------------
-- Görünüş migrations/004-dəkindən YALNIZ iki sütunla fərqlənir; hesablama
-- məntiqi (STALE/DEGRADED/NEVER_SYNCED) HƏRFƏN saxlanılır.
--
-- NİYƏ TİP GÖRÜNÜŞDƏ LAZIMDIR: sağlamlıq diaqnozu tipə görə dəyişir (fayl
-- serverində "şəbəkə əlaqəsini yoxlayın" məsləhəti YANILDICIDIR — orada
-- baxılası şey ixrac tapşırığı və qovluğun əlçatanlığıdır) və server
-- siyahısındakı tip-nişanı da bu görünüşdən oxunur.
--
-- `sync_delay_seconds` TƏRİFİ DƏYİŞMİR: o, şəbəkə gecikməsi deyil, "son
-- uğurlu sinxronizasiyadan bəri keçən vaxt"dır — bu tərif fayl mübadiləsi
-- üçün də tam mənalıdır (faylın nə vaxt oxunduğu). STALE həddi isə
-- `sync_interval_seconds * 3` olaraq qalır və gecəlik ixracda avtomatik
-- olaraq üç günə çevrilir, çünki həmin sətrin intervalı 86400-dür.
DROP VIEW IF EXISTS v_erp_server_health;
CREATE VIEW v_erp_server_health AS
SELECT
    s.id                AS server_id,
    s.tenant_id,
    s.server_name,
    s.host,
    s.port,
    s.connector_type,
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
    'status, son sync və gecikmə. `connector_type`/`port` migrations/050-də '
    'əlavə olunub — diaqnoz mətni və tip-nişanı onlardan asılıdır. '
    '`can_view_system_health` flag-i ilə görünür.';

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

-- ---------------------------------------------------------------------------
-- 5. ROOT PARAMETRİ — FAYL MÜBADİLƏSİNİN DEFOLT DÖVRÜ
-- ---------------------------------------------------------------------------
-- NİYƏ AYRICA PARAMETR, NİYƏ SADƏCƏ SÜTUN DEFOLTU DEYİL:
-- `erp_servers.sync_interval_seconds DEFAULT 300` bütün tiplər üçün eynidir və
-- fayl mübadiləsi üçün MƏNASIZDIR — 1c.md açıq şəkildə "hər gecə bir dəfə"
-- deyir. Sütunun defoltunu dəyişsəydik, HTTP serverləri də gündə bir dəfəyə
-- düşərdi. Ona görə tipə xas defolt AYRICA parametrdədir və sihirbaz sətri
-- yazarkən onu oxuyur (`ErpConnectionWizardUseCase._with_resolved_interval`).
--
-- `min_value` = 300 (5 dəqiqə): daha tez-tez oxumaq eyni faylı təkrar-təkrar
--   parse etmək deməkdir — fayl mübadiləsinin təbiətinə görə yeni məlumat
--   yalnız ixrac işlədikdə yaranır. Aşağı hüdud eyni zamanda
--   `sync_interval_seconds >= 30` CHECK-indən də yuxarıdır, yəni sətir DB
--   səviyyəsində heç vaxt rədd edilmir.
-- `max_value` = 604800 (bir həftə): bundan seyrək oxu praktikada
--   "sinxronizasiya söndürülüb" deməkdir və onun AÇIQ yolu serveri deaktiv
--   etməkdir (status = INACTIVE) — gizli yolu tavanla bağlayırıq.
--
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (039–049 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS', '86400', 'INTEGER', '300', '604800',
     'Fayl-mübadiləsi tipli 1C serverinin defolt sinxronizasiya dövrü (saniyə). '
     'Defolt 86400 = gündə bir dəfə, çünki fayl mübadiləsi real-vaxt deyil və '
     'yeni məlumat yalnız 1C-dəki gecəlik ixrac işlədikdə yaranır. Bu dəyər '
     'YALNIZ yeni serverin defoltudur — mövcud serverin dövrü sətrin öz '
     'sahəsindədir və sihirbazdan dəyişdirilir. HTTP/COM serverlərinə TƏSİR '
     'ETMİR (onların defoltu 300 saniyədir)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. YENİ KİRAYƏÇİLƏR — EYNİ PARAMETR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039–049-dakı naxış təkrarlanır: AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_erp_connector_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS', '86400', 'INTEGER',
         '300', '604800',
         'Fayl-mübadiləsi tipli 1C serverinin defolt sinxronizasiya dövrü (saniyə). '
         'Defolt 86400 = gündə bir dəfə, çünki fayl mübadiləsi real-vaxt deyil və '
         'yeni məlumat yalnız 1C-dəki gecəlik ixrac işlədikdə yaranır. Bu dəyər '
         'YALNIZ yeni serverin defoltudur — mövcud serverin dövrü sətrin öz '
         'sahəsindədir və sihirbazdan dəyişdirilir. HTTP/COM serverlərinə TƏSİR '
         'ETMİR (onların defoltu 300 saniyədir)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_erp_connector_limits_for_new_tenant() IS
    'Yeni kirayəçiyə fayl-mübadiləsi dövrünün ROOT parametrini əlavə edir '
    '(migrations/050). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_erp_connector_limits ON license_tenants;
CREATE TRIGGER trg_seed_erp_connector_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_erp_connector_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: `connector_config_encrypted` silinsə COM və fayl-mübadiləsi
-- serverlərinin BÜTÜN parametrləri (sorğu mətni, sütun adları, kodlaşdırma)
-- İTƏR və bərpa edilə bilməz — şifrəli sətir başqa yerdə saxlanılmır. Həmin
-- serverlər sihirbazdan yenidən qurulmalı olardı.
--
-- `connector_type` silinməzdən ƏVVƏL COM/FILE sətirləri deaktiv edilməlidir:
-- əks halda köhnə kod onları HTTP kimi oxuyar və hər dövrdə mənasız HTTP
-- sorğusu göndərər (port 0-a).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_erp_connector_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_erp_connector_limits_for_new_tenant();
--   DELETE FROM system_limits
--    WHERE limit_key = 'ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS';
--   UPDATE erp_servers SET status = 'INACTIVE' WHERE connector_type <> 'HTTP';
--   ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_active_requires_config;
--   ALTER TABLE erp_servers ADD CONSTRAINT chk_erp_active_requires_infobase
--       CHECK (status <> 'ACTIVE' OR length(trim(infobase)) > 0);
--   ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_port_matches_connector_type;
--   UPDATE erp_servers SET port = 1541 WHERE port = 0;
--   ALTER TABLE erp_servers ADD CONSTRAINT erp_servers_port_check
--       CHECK (port BETWEEN 1 AND 65535);
--   ALTER TABLE erp_servers DROP CONSTRAINT IF EXISTS chk_erp_connector_type;
--   ALTER TABLE erp_servers
--       DROP COLUMN IF EXISTS connector_type,
--       DROP COLUMN IF EXISTS connector_config_encrypted;
--   -- Görünüş migrations/004-dəki formasına qaytarılmalıdır (orada tam mətn var).
-- COMMIT;
