-- ===========================================================================
-- VENDOR-002 — RLS SİYASƏTLƏRİ (DB-3 FAZA 2)
-- ===========================================================================
-- Tarix : 2026-08-16
--
-- ---------------------------------------------------------------------------
-- QƏRAR: VENDOR BAZASI PARALEL İŞLƏYİR, MÜŞTƏRİ ORA YAZMIR
-- ---------------------------------------------------------------------------
-- Müştərinin lisenziya axını OLDUĞU KİMİ qalır: o, öz Supabase layihəsindəki
-- `license_tenants` sətrini oxuyur və `tenant_check_ins`-ə yazır
-- (`infrastructure/licensing/gateway.py`). Bu baza isə TƏCHİZATÇININ öz
-- konsoludur.
--
-- Nəticə siyasətləri SADƏLƏŞDİRİR və SƏRTLƏŞDİRİR: müştəri tərəfi üçün HEÇ
-- BİR yazma yolu açılmır. `crash_reports`/`support_tickets` cədvəllərinə də
-- müştəri BİRBAŞA yazmır — məlumat vendor tərəfindəki toplama prosesi ilə
-- gəlir. Yəni "tenant yalnız öz sətrini INSERT edə bilər" tipli siyasətə
-- ehtiyac YOXDUR; belə siyasət olsaydı, anon açarla gələn hər kəs cədvələ
-- sətir yaza bilərdi və spam/şişirtmə yolu açıq qalardı.
--
-- ---------------------------------------------------------------------------
-- NİYƏ ROL ƏSASLI, NİYƏ GUC ƏSASLI DEYİL
-- ---------------------------------------------------------------------------
-- Siyasəti `current_setting('vendor.account_id')` kimi sessiya dəyişəninə
-- bağlamaq CAZİBƏDAR görünür, lakin TƏHLÜKƏSİZLİK DEYİL: həmin dəyişəni
-- istənilən sessiya özü `SET` edə bilər. Yeganə etibarlı sərhəd BAZA ROLUDUR.
--
-- ---------------------------------------------------------------------------
-- `FORCE ROW LEVEL SECURITY` NİYƏ MƏCBURİDİR
-- ---------------------------------------------------------------------------
-- Adi `ENABLE` cədvəlin SAHİBİNƏ tətbiq olunmur — sahib bütün siyasətləri yan
-- keçir. Miqrasiyaları tətbiq edən rol isə məhz sahibdir. `FORCE` olmasaydı,
-- konsol həmin rolla qoşulduqda RLS-in olub-olmaması heç nəyi dəyişməzdi və
-- siyasətlər "yazılıb, amma qüvvədə deyil" vəziyyətində qalardı.
--
-- ---------------------------------------------------------------------------
-- `BYPASSRLS` — SİYASƏTLƏRİN ÜSTÜNDƏ DAYANAN YEGANƏ ŞEY
-- ---------------------------------------------------------------------------
-- Postgres-də `BYPASSRLS` atributu olan rol (və superuser) BÜTÜN siyasətləri
-- yan keçir — `FORCE ROW LEVEL SECURITY` DA ONU SAXLAMIR. Supabase-də bu
-- atribut İKİ rolda var: `postgres` və `service_role` (bu instansiyada
-- yoxlanılıb).
--
-- Praktiki nəticə DB-3-ün əsas prinsipinə birbaşa toxunur: konsol
-- `service_role` açarı ilə qoşulursa, buradakı siyasətlərin HEÇ BİRİ qüvvədə
-- deyil və yeganə qoruma "açarı müştəriyə vermə" olur — yəni təhlükəsizlik
-- yenidən KLİENTƏ qayıdır.
--
-- Ona görə konsolun bağlantısı `kompasos_vendor` ÜZVÜ olan, `BYPASSRLS`
-- OLMAYAN ayrıca login rolu ilə qurulmalıdır. `service_role` yalnız
-- miqrasiya tətbiqi üçün qalır.
--
-- ---------------------------------------------------------------------------
-- İKİ QAT: İMTİYAZ + SİYASƏT
-- ---------------------------------------------------------------------------
-- 1. İMTİYAZ (`GRANT`/`REVOKE`) — icazəsiz rol sorğunu ÜMUMİYYƏTLƏ icra edə
--    bilmir («permission denied»).
-- 2. SİYASƏT (RLS) — imtiyaz səhvən verilsə belə, sətir görünmür (boş nəticə).
--
-- Tələb sənədi «boş nəticə» deyir; imtiyaz rədd etməsi ondan DAHA GÜCLÜDÜR
-- (məlumatın mövcudluğu belə bilinmir). Hər ikisini saxlayırıq, çünki biri
-- gələcəkdə səhvən zəiflədilə bilər.
-- ===========================================================================

BEGIN;

SET search_path TO vendor, public;

-- ---------------------------------------------------------------------------
-- 1. VENDOR ROLU
-- ---------------------------------------------------------------------------
-- `NOLOGIN`: bu rol birbaşa qoşulmaq üçün deyil, İCAZƏ DAŞIYICISIDIR. Konsolun
-- öz login rolu ona üzv edilir (`GRANT kompasos_vendor TO <login_rolu>`).
-- Beləliklə şifrə bu fayla düşmür və rol dəyişikliyi siyasətlərə toxunmur.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kompasos_vendor') THEN
        CREATE ROLE kompasos_vendor NOLOGIN;
        RAISE NOTICE '`kompasos_vendor` rolu yaradıldı.';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. İMTİYAZLAR — HƏR ŞEY BAĞLI, SONRA NÖQTƏLİ AÇILIŞ
-- ---------------------------------------------------------------------------
REVOKE ALL ON SCHEMA vendor FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA vendor FROM PUBLIC;

-- Supabase-in standart rolları (`anon`, `authenticated`) mövcuddursa onlardan
-- da açıq şəkildə alınır. `PUBLIC`-dən alınma onsuz da kifayət edir, lakin
-- gələcəkdə kimsə həmin rollara birbaşa `GRANT` versə, bu sətirlər niyyəti
-- sənədləşdirmiş olur.
DO $$
DECLARE
    v_role TEXT;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA vendor FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA vendor FROM %I', v_role);
        END IF;
    END LOOP;
END
$$;

GRANT USAGE ON SCHEMA vendor TO kompasos_vendor;

-- Oxu + yazı: reyestr, hesablar, müraciətlər, çökmələr.
GRANT SELECT, INSERT, UPDATE ON vendor.tenants,
                                vendor.vendor_accounts,
                                vendor.support_tickets,
                                vendor.crash_reports
    TO kompasos_vendor;

-- Ödəniş və audit: `UPDATE`/`DELETE` YOXDUR — hər ikisi jurnaldır.
-- Ödənişin düzəlişi tərs sətirlə edilir (bax vendor/001).
GRANT SELECT, INSERT ON vendor.tenant_payments, vendor.vendor_audit_logs
    TO kompasos_vendor;

-- ---------------------------------------------------------------------------
-- 3. RLS — HƏR CƏDVƏLDƏ, `FORCE` İLƏ
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_table TEXT;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'vendor_accounts', 'tenants', 'tenant_payments',
        'crash_reports', 'support_tickets', 'vendor_audit_logs'
    ] LOOP
        EXECUTE format('ALTER TABLE vendor.%I ENABLE ROW LEVEL SECURITY', v_table);
        EXECUTE format('ALTER TABLE vendor.%I FORCE ROW LEVEL SECURITY', v_table);
        EXECUTE format('DROP POLICY IF EXISTS vendor_only ON vendor.%I', v_table);
        -- `TO kompasos_vendor`: siyasət YALNIZ həmin rol üçün mövcuddur.
        -- Digər hər rol üçün heç bir siyasət yoxdur, RLS isə "siyasət yoxdursa
        -- sətir yoxdur" deməkdir — yəni boş nəticə.
        EXECUTE format(
            'CREATE POLICY vendor_only ON vendor.%I FOR ALL TO kompasos_vendor '
            'USING (TRUE) WITH CHECK (TRUE)', v_table);
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. AUDİT VƏ ÖDƏNİŞ JURNALI DƏYİŞDİRİLƏ BİLMƏZ
-- ---------------------------------------------------------------------------
-- İmtiyaz qatı `UPDATE`/`DELETE` vermir, lakin sahib rolu (miqrasiyanı tətbiq
-- edən) onları hələ də edə bilər. Trigger həmin son yolu da bağlayır —
-- müştəri bazasındakı `enforce_append_only()` ilə eyni qərar.
CREATE OR REPLACE FUNCTION vendor.enforce_vendor_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'APPEND-ONLY POZUNTUSU: "%" cədvəlində % əməliyyatı qadağandır — '
        'lisenziya/ödəniş izi dəyişdirilə bilməz (DB-3).',
        TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_vendor_audit_append_only ON vendor.vendor_audit_logs;
CREATE TRIGGER trg_vendor_audit_append_only
    BEFORE UPDATE OR DELETE ON vendor.vendor_audit_logs
    FOR EACH ROW EXECUTE FUNCTION vendor.enforce_vendor_append_only();

DROP TRIGGER IF EXISTS trg_vendor_payments_append_only ON vendor.tenant_payments;
CREATE TRIGGER trg_vendor_payments_append_only
    BEFORE UPDATE OR DELETE ON vendor.tenant_payments
    FOR EACH ROW EXECUTE FUNCTION vendor.enforce_vendor_append_only();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Siyasətlərin götürülməsi bazanı AÇIQ qoyur — yalnız miqrasiyanın özündə
-- qüsur aşkarlandıqda mənalıdır.
--
-- BEGIN;
--   SET search_path TO vendor, public;
--   DROP TRIGGER IF EXISTS trg_vendor_payments_append_only ON vendor.tenant_payments;
--   DROP TRIGGER IF EXISTS trg_vendor_audit_append_only ON vendor.vendor_audit_logs;
--   DROP FUNCTION IF EXISTS vendor.enforce_vendor_append_only();
--   -- RLS söndürülməsi: hər cədvəl üçün `ALTER TABLE … DISABLE ROW LEVEL SECURITY`.
-- COMMIT;
