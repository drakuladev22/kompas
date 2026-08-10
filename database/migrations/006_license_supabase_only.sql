-- ===========================================================================
-- MIGRATION 006 — LİSENZİYA: AYRICA SERVER YOX, YALNIZ SUPABASE + RLS
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : Lisenziya arxitekturasının dəqiqləşdirilməsi (bölmə 8) — ayrıca
--         VPS/domen/hostinq VƏ HTTP API İSTİFADƏ OLUNMUR. İki tərəf var:
--
--           MÜŞTƏRİ (.exe)     `anon` açar → `license_tenants`-dəki YALNIZ
--                              ÖZ sətrini OXUYUR. Yazma hüququ yoxdur.
--           DEVELOPER PANELİ   `service_role` açar → yalnız hazırlayıcının
--                              öz kompüterində, `--developer-mode` ilə.
--                              İnternetə host OLUNMUR.
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `expires_at` — `next_payment_date` OLDUĞU HALDA
-- ---------------------------------------------------------------------------
-- `next_payment_date` bir ÖDƏNİŞ TARİXİDİR (DATE) və "ödəniş gözlənilir"
-- xatırlatmalarını idarə edir. Avtomatik dayanma isə DƏQİQ AN tələb edir:
-- gün ortasında uzadılan lisenziya "sabahdan" deyil, DƏRHAL işləməlidir.
-- `TIMESTAMPTZ` seçilib ki, saat qurşağı fərqi (Asia/Baku ↔ UTC) müştərini
-- bir gün erkən bağlamasın.
--
-- İkisi bir-birini əvəz etmir, LAKİN uzatma əməliyyatı hər ikisini birlikdə
-- yeniləyir (`DeveloperTenantDirectory.extend_one_month`) — beləliklə ödəniş
-- xatırlatma view-u ilə bloklama məntiqi heç vaxt bir-birinə zidd olmur.
--
-- ---------------------------------------------------------------------------
-- NİYƏ RLS SİYASƏTİ `current_tenant_id()` VƏ JWT CLAIM-İN HƏR İKİSİNİ QƏBUL EDİR
-- ---------------------------------------------------------------------------
-- Layihə bazaya psycopg ilə birbaşa qoşulur və tenant konteksti hər
-- tranzaksiyada `SET LOCAL app.tenant_id` ilə verilir (SEC-008). Supabase
-- PostgREST üzərindən gələn sorğularda isə kontekst JWT claim-dədir. Siyasət
-- hər ikisini qəbul edir ki, gələcəkdə giriş yolu dəyişəndə sükutla
-- "heç nə görünmür" vəziyyəti yaranmasın — fail-closed davranış qorunur,
-- çünki hər iki mənbə boşdursa nəticə NULL olur və sətir GÖRÜNMÜR.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. `license_tenants.expires_at` — avtomatik dayanmanın yeganə mənbəyi
-- ---------------------------------------------------------------------------
ALTER TABLE license_tenants
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

COMMENT ON COLUMN license_tenants.expires_at IS
    'Lisenziyanın bitmə anı. Klient bunu YERLİ olaraq indiki vaxtla müqayisə '
    'edir → LICENSE_INACTIVE. Server tərəfdə cron/Edge Function TƏLƏB OLUNMUR.';

-- Mövcud qeydlər üçün ilkin dəyər: ödəniş tarixinin sonu (gün bitənə qədər
-- işləsin — bir neçə saat "artıq" vermək müştərini vaxtından əvvəl
-- bağlamaqdan qat-qat ucuzdur).
UPDATE license_tenants
   SET expires_at = (next_payment_date + INTERVAL '1 day')::TIMESTAMPTZ
 WHERE expires_at IS NULL AND next_payment_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tenants_expires_at
    ON license_tenants (expires_at)
 WHERE status <> 'DEAKTIV';

-- ---------------------------------------------------------------------------
-- 2. `license_audit_log` — uzatma/status əməliyyatlarının izi
-- ---------------------------------------------------------------------------
-- Bu, `audit_logs`-dan AYRIDIR: `audit_logs` tenant-a aiddir və RLS ilə
-- tenant-ın özünə görünür. Lisenziya əməliyyatları isə HAZIRLAYICININ
-- əməliyyatlarıdır — müştəri onları görməməlidir (kimin nə vaxt uzadıldığı
-- kommersiya məlumatıdır).
CREATE TABLE IF NOT EXISTS license_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    action          TEXT NOT NULL,
    old_expires_at  TIMESTAMPTZ,
    new_expires_at  TIMESTAMPTZ,
    note            TEXT,
    performed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE license_audit_log IS
    'Developer Panelindəki lisenziya əməliyyatlarının izi (bölmə 8). İcraçı '
    'HƏMİŞƏ hazırlayıcının özüdür — ayrıca "kim" sütunu ona görə yoxdur. '
    'Müştəri tərəfdən GÖRÜNMÜR: yalnız service_role oxuya bilir.';

CREATE INDEX IF NOT EXISTS idx_license_audit_tenant
    ON license_audit_log (tenant_id, performed_at DESC);

-- ---------------------------------------------------------------------------
-- 3. RLS — müştəri YALNIZ öz sətrini görür
-- ---------------------------------------------------------------------------
-- `current_tenant_id()` `app.tenant_id`-ni oxuyur (schema.sql §27). Burada
-- əlavə olaraq PostgREST/JWT yolu da nəzərə alınır.
CREATE OR REPLACE FUNCTION license_scope_tenant_id() RETURNS UUID AS $$
DECLARE
    v_claim TEXT;
BEGIN
    IF current_tenant_id() IS NOT NULL THEN
        RETURN current_tenant_id();
    END IF;
    -- PostgREST claim-ləri JSON kimi ötürülür; sahə yoxdursa NULL qayıdır.
    v_claim := current_setting('request.jwt.claims', TRUE);
    IF v_claim IS NULL OR v_claim = '' THEN
        RETURN NULL;
    END IF;
    RETURN (v_claim::JSONB ->> 'tenant_id')::UUID;
EXCEPTION WHEN OTHERS THEN
    -- Yararsız claim → NULL → heç bir sətir görünmür (fail-closed).
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION license_scope_tenant_id() IS
    'Lisenziya RLS-i üçün tenant konteksti: əvvəlcə app.tenant_id (psycopg), '
    'sonra JWT claim (PostgREST). Hər ikisi boşdursa NULL — fail-closed.';

ALTER TABLE license_tenants ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_reads_own_license ON license_tenants;
CREATE POLICY tenant_reads_own_license ON license_tenants
    FOR SELECT
    USING (tenant_id = license_scope_tenant_id());

-- YAZMA SİYASƏTİ QƏSDƏN YARADILMIR.
-- RLS-də siyasəti olmayan əməliyyat = QADAĞAN. Yəni `INSERT`/`UPDATE`/
-- `DELETE` üçün heç bir policy olmaması müştərinin lisenziya sətrini
-- dəyişməsini bloklayan İKİNCİ qatdır (birincisi §28-dəki REVOKE).
-- `service_role` isə RLS-dən azaddır — Developer Paneli buna görə işləyir.

-- Telemetriya: tenant yalnız ÖZ sətirlərini yaza bilir, oxuya bilmir.
ALTER TABLE tenant_check_ins ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_writes_own_check_in ON tenant_check_ins;
CREATE POLICY tenant_writes_own_check_in ON tenant_check_ins
    FOR INSERT
    WITH CHECK (tenant_id = license_scope_tenant_id());

-- Crash hesabatları: yalnız YAZMA. Oxuma siyasəti yoxdur, çünki bir tenant
-- başqasının stack-trace-lərini görməməlidir (bölmə 8 — anonimlik).
ALTER TABLE crash_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS anyone_writes_crash_report ON crash_reports;
CREATE POLICY anyone_writes_crash_report ON crash_reports
    FOR INSERT
    WITH CHECK (TRUE);

-- Lisenziya audit izi: müştəriyə tamamilə bağlıdır (heç bir policy yoxdur →
-- RLS aktivdirsə heç nə görünmür).
ALTER TABLE license_audit_log ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 4. Səlahiyyətlər — tətbiq rolu üçün minimum
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        RAISE NOTICE 'Rol "%" yoxdur — GRANT/REVOKE atlandı.', v_role;
        RETURN;
    END IF;

    -- Lisenziya sətri: YALNIZ OXUMA (schema.sql §28-dəki REVOKE ilə eyni
    -- qərar, burada təkrar təsdiqlənir — miqrasiya sırasından asılı olmasın).
    EXECUTE format('GRANT SELECT ON license_tenants TO %I', v_role);
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON license_tenants FROM %I', v_role);

    -- Telemetriya və crash: YALNIZ YAZMA.
    EXECUTE format('GRANT INSERT ON tenant_check_ins TO %I', v_role);
    EXECUTE format('REVOKE SELECT, UPDATE, DELETE ON tenant_check_ins FROM %I', v_role);
    EXECUTE format('GRANT INSERT ON crash_reports TO %I', v_role);
    EXECUTE format('REVOKE SELECT, UPDATE, DELETE ON crash_reports FROM %I', v_role);

    -- Lisenziya audit izi: müştəri tərəfə HEÇ BİR hüquq verilmir.
    EXECUTE format(
        'REVOKE SELECT, INSERT, UPDATE, DELETE ON license_audit_log FROM %I', v_role
    );

    RAISE NOTICE 'Lisenziya səlahiyyətləri tətbiq olundu: %', v_role;
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: RLS siyasəti silinsə tətbiq rolu BÜTÜN tenant-ların lisenziya
-- sətrini oxuya bilər. `expires_at` silinsə avtomatik dayanma tamamilə
-- söndürülür — hər tenant müddətsiz işləyər.
--
-- BEGIN;
--   DROP POLICY IF EXISTS anyone_writes_crash_report ON crash_reports;
--   ALTER TABLE crash_reports DISABLE ROW LEVEL SECURITY;
--   DROP POLICY IF EXISTS tenant_writes_own_check_in ON tenant_check_ins;
--   ALTER TABLE tenant_check_ins DISABLE ROW LEVEL SECURITY;
--   DROP POLICY IF EXISTS tenant_reads_own_license ON license_tenants;
--   ALTER TABLE license_tenants DISABLE ROW LEVEL SECURITY;
--   ALTER TABLE license_audit_log DISABLE ROW LEVEL SECURITY;
--   DROP FUNCTION IF EXISTS license_scope_tenant_id();
--   DROP INDEX IF EXISTS idx_license_audit_tenant;
--   DROP TABLE IF EXISTS license_audit_log;
--   DROP INDEX IF EXISTS idx_tenants_expires_at;
--   ALTER TABLE license_tenants DROP COLUMN IF EXISTS expires_at;
-- COMMIT;
