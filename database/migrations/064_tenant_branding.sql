-- ===========================================================================
-- 064 — TENANT BRENDİNQİ (TENANT-1 FAZA 2)
-- ===========================================================================
-- Tarix : 2026-08-17
-- Səbəb : Hər müştəri (Yataş Group, Embawood, ...) proqramda ÖZ şirkət
--         kimliyini görmək istəyir. İndiyə qədər başlıq zolağında, splash
--         ekranında və export fayllarının başlığında yalnız «KompasOS»
--         yazılırdı.
--
-- ---------------------------------------------------------------------------
-- NİYƏ AYRICA CƏDVƏL, NİYƏ `system_limits` DEYİL
-- ---------------------------------------------------------------------------
-- `system_limits` SKALYAR mətn saxlayır və ROOT ekranı onu «açar → dəyər»
-- cədvəli kimi göstərir. Loqo isə İKİLİ məlumatdır: ora yazılsaydı, Root
-- paneli sürüşdürücünün yanında minlərlə simvolluq base64 sətri göstərərdi
-- və ekran praktiki olaraq oxunmaz olardı. Üstəlik şirkət adı «limit»
-- deyil — açar siyahısında onun yeri yoxdur.
--
-- Bir sətir = bir kirayəçi (`tenant_id` PRIMARY KEY). Tarixçə saxlanılmır:
-- brendinq audit obyekti deyil, konfiqurasiyadır — kim dəyişdi sualı
-- `audit_logs`-da onsuz da cavablanır.
--
-- ---------------------------------------------------------------------------
-- LOQO BAZADA SAXLANILIR — DRIVE-DA DEYİL
-- ---------------------------------------------------------------------------
-- Cərimə sübut şəkilləri Google Drive-dadır (migrations/002), lakin loqo
-- ORADA OLA BİLMƏZ: Drive bağlantısı İSTƏYƏ BAĞLIDIR (`.env.example`:
-- «boşdursa şəkillər lokal növbədə gözləyir») və brendinq tətbiqin AÇILIŞ
-- ekranında lazımdır. Drive-a bağlasaydıq, Drive qoşulmamış quraşdırmada
-- splash ekranı boş qalardı və səbəbi tapmaq üçün Drive jurnalına baxmaq
-- lazım gələrdi.
--
-- Ölçü həddi CHECK ilə qoyulur (256 KB): loqo bir ikondur, şəkil qalereyası
-- deyil. Hədd olmasaydı, kimsə 20 MB-lıq PNG yükləyər və hər açılışda həmin
-- həcm şəbəkədən keçərdi.
--
-- ---------------------------------------------------------------------------
-- BRENDİNQ YALNIZ VİZUAL QATDIR — QƏTİ SƏRHƏD
-- ---------------------------------------------------------------------------
-- Bu cədvəldə funksionallığa, təhlükəsizlik qaydalarına və ya RBAC-a təsir
-- edən HEÇ BİR sütun YOXDUR və olmayacaq. Səbəb `CLAUDE.md` §5-dədir:
-- «müştəri istədi» hər struktur zəmanətin yan keçilməsi üçün bəhanəyə
-- çevrilərdi. Yeni sütun əlavə edən adam əvvəlcə bu suala cavab verməlidir:
-- «bu dəyər dəyişəndə hansısa qadağa zəifləyirmi?» Cavab «bəli»dirsə, yeri
-- burası DEYİL.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

CREATE TABLE IF NOT EXISTS tenant_branding (
    tenant_id     UUID PRIMARY KEY REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- Başlıq zolağında «KompasOS — <ad>» kimi görünür. BOŞ ola bilər: o
    -- halda yalnız «KompasOS» qalır (defolt davranış dəyişmir).
    company_name  TEXT NOT NULL DEFAULT ''
                      CHECK (char_length(company_name) <= 80),

    -- İstəyə bağlı PNG. `NULL` = defolt KompasOS loqosu.
    logo_png      BYTEA
                      CHECK (logo_png IS NULL OR octet_length(logo_png) <= 262144),

    -- İstəyə bağlı vurğu rəngi (`#RRGGBB`). `NULL` = defolt Amber.
    --
    -- KONTRAST XƏBƏRDARLIĞI: bu dəyər `scripts/check_contrast.py` qapısından
    -- KEÇMİR — qapı `tokens.py`-dakı SABİT palitranı ölçür, müştərinin işə
    -- düşmə anında verdiyi rəngi yox. Ona görə tətbiq qatı onu istifadə
    -- etməzdən əvvəl özü yoxlayır (`value_objects/branding.py`).
    accent_color  TEXT
                      CHECK (accent_color IS NULL OR accent_color ~ '^#[0-9A-Fa-f]{6}$'),

    updated_by    UUID REFERENCES employees(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE tenant_branding IS
    'Kirayəçinin vizual kimliyi (migrations/064, TENANT-1 Faza 2). YALNIZ '
    'görünüş: funksionallıq, təhlükəsizlik qaydaları və RBAC buradan '
    'DƏYİŞMİR — bax fayl başlığındakı qəti sərhəd.';

COMMENT ON COLUMN tenant_branding.logo_png IS
    'İstəyə bağlı PNG (≤256 KB). NULL = defolt KompasOS loqosu. Drive-da '
    'DEYİL, çünki Drive bağlantısı istəyə bağlıdır və loqo açılış ekranında '
    'lazımdır.';

COMMENT ON COLUMN tenant_branding.accent_color IS
    'İstəyə bağlı `#RRGGBB`. NULL = defolt Amber. Kontrast qapısından keçmir '
    '— yoxlama tətbiq qatındadır (value_objects/branding.py).';

DROP TRIGGER IF EXISTS trg_tenant_branding_updated ON tenant_branding;
CREATE TRIGGER trg_tenant_branding_updated BEFORE UPDATE ON tenant_branding
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- TIME-1 (migrations/062): `created_at` server vaxtına məcbur edilir.
DROP TRIGGER IF EXISTS trg_server_created_at_branding ON tenant_branding;
CREATE TRIGGER trg_server_created_at_branding
    BEFORE INSERT ON tenant_branding
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

-- Ayrı Supabase layihələri onsuz da FİZİKİ izolyasiya verir (TENANT-1 qəti
-- qərarı), lakin RLS İKİNCİ qat kimi qalır: `CLAUDE.md` §6 hər repozitoriyada
-- açıq `tenant_id` şərtini də tələb edir və üç qatın hamısı eyni anda sıradan
-- çıxmayana qədər sızma olmur.
-- ---------------------------------------------------------------------------
-- RLS — LAYİHƏNİN ÖZ NAXIŞI
-- ---------------------------------------------------------------------------
-- Siyasət `current_setting('app.tenant_id', true)::uuid` DEYİL,
-- `current_tenant_id()` işlədir və bu, fərq DAVRANIŞ fərqidir: GUC təyin
-- edilməyibsə xam çevirmə `invalid_text_representation` ilə ÇÖKÜR, helper isə
-- `NULL` qaytarır — yəni sorğu boş nəticə verir (fail-closed), xəta yox.
-- Kontekstsiz yol (miqrasiya skripti, `system_scope()`) məhz belə olmalıdır.
--
-- `WITH CHECK` də MƏCBURİDİR: `USING` yalnız OXUNU məhdudlaşdırır. Onsuz
-- başqa kirayəçinin `tenant_id`-si ilə sətir YAZMAQ mümkün olardı.
--
-- Ad `tenant_isolation`-dır — `schema.sql` §-dəki DO dövrəsi və migrations/002
-- eyni adı işlədir; fərqli ad qoysaydıq, gələcək toplu `DROP POLICY IF EXISTS
-- tenant_isolation` təmizliyi bu cədvəli ATLAYARDI.
ALTER TABLE tenant_branding ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenant_branding;
CREATE POLICY tenant_isolation ON tenant_branding
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- MÖVCUD KİRAYƏÇİLƏR ÜÇÜN BOŞ SƏTİR
-- ---------------------------------------------------------------------------
-- Sətir ƏVVƏLCƏDƏN yaradılır ki, oxu yolunda «sətir yoxdur» halı olmasın:
-- əks halda hər ekran `None` yoxlaması yazmalı olardı və biri unudulanda
-- başlıq zolağı boş qalardı. Boş sətir DEFOLT davranışı verir.
INSERT INTO tenant_branding (tenant_id)
SELECT tenant_id FROM license_tenants
ON CONFLICT (tenant_id) DO NOTHING;

CREATE OR REPLACE FUNCTION seed_branding_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO tenant_branding (tenant_id)
    VALUES (NEW.tenant_id)
    ON CONFLICT (tenant_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_branding_for_new_tenant() IS
    'Yeni kirayəçiyə boş brendinq sətri yaradır (migrations/064).';

DROP TRIGGER IF EXISTS trg_seed_tenant_branding ON license_tenants;
CREATE TRIGGER trg_seed_tenant_branding
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_branding_for_new_tenant();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Cədvəlin silinməsi müştərinin yüklədiyi loqonu İTİRƏR. Davranış defolta
-- qayıdar (tətbiq işləməyə davam edər), lakin fayl geri qaytarıla bilməz.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_tenant_branding ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_branding_for_new_tenant();
--   DROP TABLE IF EXISTS tenant_branding;
-- COMMIT;
