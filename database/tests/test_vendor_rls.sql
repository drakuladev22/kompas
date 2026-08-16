-- ===========================================================================
-- VENDOR BAZASI — RLS TƏHLÜKƏSİZLİK TESTLƏRİ (DB-3 FAZA 5)
-- ===========================================================================
-- Bu dörd test DB-3-ün əsas prinsipini yoxlayır: qoruma UI-da deyil,
-- SERVERDƏDİR. Vendor konsolunun kodu hər müştəriyə göndərilən eyni `.exe`-nin
-- içindədir — yəni sorğunun ÖZÜ qaçılmazdır; qorunma sorğunun CAVABINDADIR.
--
-- İCRA:
--   psql "$KOMPASOS_VENDOR_DSN" -v ON_ERROR_STOP=1 -f database/tests/test_vendor_rls.sql
--
-- Hər test SAVEPOINT daxilində işləyir və sonda hər şey geri qaytarılır.
--
-- ---------------------------------------------------------------------------
-- «BOŞ NƏTİCƏ» VƏ «İMTİYAZ RƏDDİ» — İKİSİ DƏ KEÇƏRLİ NƏTİCƏDİR
-- ---------------------------------------------------------------------------
-- Tələb sənədi «RLS bloklamalıdır → boş nəticə» deyir. Faktiki quruluşda
-- icazəsiz rol sxemə ÜMUMİYYƏTLƏ çıxa bilmir, yəni «permission denied» alır.
-- Bu, boş nəticədən DAHA GÜCLÜDÜR (cədvəlin mövcudluğu belə bilinmir), ona
-- görə testlər hər iki nəticəni uğur sayır və HANSININ baş verdiyini yazır.
-- Uğursuzluq YALNIZ məlumatın GÖRÜNMƏSİDİR.
-- ===========================================================================

\set ON_ERROR_STOP on
SET search_path TO vendor, public;

BEGIN;

DO $$
DECLARE
    v_tenant_a  UUID := gen_random_uuid();
    v_tenant_b  UUID := gen_random_uuid();
    v_account   UUID;
    v_visible   BIGINT;
    v_denied    BOOLEAN;
    v_status    TEXT;
    v_passed    INTEGER := 0;
BEGIN
    -- ------------------------------------------------------------- hazırlıq
    -- Test rolu: konsolun bağlantı rolunun modelidir — `kompasos_vendor`
    -- ÜZVÜ, `BYPASSRLS` YOX (`service_role` ilə fərqi məhz budur).
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vendor_rls_test_console') THEN
        CREATE ROLE vendor_rls_test_console NOLOGIN;
    END IF;
    EXECUTE 'GRANT kompasos_vendor TO vendor_rls_test_console';
    EXECUTE format('GRANT vendor_rls_test_console TO %I', current_user);

    -- Nümunə məlumat konsol rolu ilə yazılır: cədvəl sahibi `BYPASSRLS`
    -- daşıya bilər və o halda yazı siyasətləri sınamazdı.
    SET LOCAL ROLE vendor_rls_test_console;
    INSERT INTO vendor.tenants (tenant_id, company_name, license_key, status)
    VALUES (v_tenant_a, 'A MMC', 'KEY-A', 'AKTIV'),
           (v_tenant_b, 'B MMC', 'KEY-B', 'DEAKTIV');
    INSERT INTO vendor.support_tickets (tenant_id, message)
    VALUES (v_tenant_a, 'A-nın müraciəti'), (v_tenant_b, 'B-nin müraciəti');
    INSERT INTO vendor.vendor_accounts (email, password_hash)
    VALUES ('rls-test@kompas.az', 'argon2-placeholder')
    RETURNING id INTO v_account;
    RESET ROLE;

    -- =====================================================================
    -- TEST 1 — adi tenant istifadəçisi `tenants` cədvəlini sorğu edir
    -- =====================================================================
    -- Müştəri `.exe`-si Supabase-ə `anon` açarı ilə qoşulur; giriş etmiş
    -- istifadəçi isə `authenticated` olur. Hər ikisi yoxlanılır, çünki
    -- «tenant istifadəçisi» praktikada bu iki roldan biridir.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        v_denied := FALSE;
        BEGIN
            SET LOCAL ROLE anon;
            SELECT count(*) INTO v_visible FROM vendor.tenants;
        EXCEPTION WHEN insufficient_privilege THEN
            v_denied := TRUE;
            v_visible := 0;
        END;
        RESET ROLE;

        IF v_visible > 0 THEN
            RAISE EXCEPTION
                'TEST 1 UĞURSUZ: `anon` rolu `vendor.tenants`-də % sətir GÖRDÜ — '
                'lisenziya/ödəniş məlumatı sızır.', v_visible;
        END IF;
        v_passed := v_passed + 1;
        RAISE NOTICE 'TEST 1 ✓ `anon` → %', CASE WHEN v_denied THEN 'imtiyaz rəddi' ELSE 'boş nəticə' END;
    ELSE
        RAISE NOTICE 'TEST 1 — `anon` rolu bu instansiyada yoxdur, atlandı';
    END IF;

    -- =====================================================================
    -- TEST 2 — Tenant A, Tenant B-nin `support_tickets` sətrini oxumağa çalışır
    -- =====================================================================
    -- QƏRAR (DB-3 FAZA 2): müştəri vendor bazasına NƏ YAZIR, NƏ OXUYUR. Yəni
    -- «A B-ni görməsin» tələbi burada daha güclü formada ödənilir: A ÜMUMİYYƏTLƏ
    -- heç bir sətir görmür — nə özününkünü, nə başqasınınkını.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        v_denied := FALSE;
        BEGIN
            SET LOCAL ROLE authenticated;
            -- Tenant kontekstini "A" kimi elan etmək cəhdi: RLS bu dəyişənə
            -- GÜVƏNMİR (rol əsaslıdır), ona görə cəhd nəticəni dəyişmir.
            PERFORM set_config('request.jwt.claim.tenant_id', v_tenant_a::TEXT, TRUE);
            SELECT count(*) INTO v_visible FROM vendor.support_tickets;
        EXCEPTION WHEN insufficient_privilege THEN
            v_denied := TRUE;
            v_visible := 0;
        END;
        RESET ROLE;

        IF v_visible > 0 THEN
            RAISE EXCEPTION
                'TEST 2 UĞURSUZ: tenant rolu `support_tickets`-də % sətir gördü.', v_visible;
        END IF;
        v_passed := v_passed + 1;
        RAISE NOTICE 'TEST 2 ✓ tenant → %', CASE WHEN v_denied THEN 'imtiyaz rəddi' ELSE 'boş nəticə' END;
    ELSE
        RAISE NOTICE 'TEST 2 — `authenticated` rolu yoxdur, atlandı';
    END IF;

    -- =====================================================================
    -- TEST 3 — autentifikasiyasız (PUBLIC) sorğu rədd edilir
    -- =====================================================================
    -- `SET ROLE PUBLIC` MÜMKÜN DEYİL: `PUBLIC` real rol deyil, «hamı» mənasını
    -- verən psevdo-qrupdur. Ona görə eyni vəziyyət DAHA SƏRT formada
    -- modelləşdirilir: heç bir üzvlüyü və heç bir açıq imtiyazı OLMAYAN yad
    -- rol. Belə sessiya yalnız `PUBLIC`-ə verilmiş imtiyazları daşıyır —
    -- yəni testin hədəfi elə odur.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vendor_rls_test_stranger') THEN
        CREATE ROLE vendor_rls_test_stranger NOLOGIN;
    END IF;
    EXECUTE format('GRANT vendor_rls_test_stranger TO %I', current_user);

    v_denied := FALSE;
    BEGIN
        SET LOCAL ROLE vendor_rls_test_stranger;
        SELECT count(*) INTO v_visible FROM vendor.vendor_accounts;
    EXCEPTION WHEN insufficient_privilege THEN
        v_denied := TRUE;
        v_visible := 0;
    END;
    RESET ROLE;

    IF v_visible > 0 THEN
        RAISE EXCEPTION
            'TEST 3 UĞURSUZ: autentifikasiyasız sorğu `vendor_accounts`-da % sətir '
            'gördü — şifrə heşləri və TOTP sirləri açıqdır.', v_visible;
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 3 ✓ PUBLIC → %', CASE WHEN v_denied THEN 'imtiyaz rəddi' ELSE 'boş nəticə' END;

    -- =====================================================================
    -- TEST 4 — vendor hesabı BÜTÜN tenant-ları görür (MÜSBƏT nəzarət)
    -- =====================================================================
    -- Bu test olmadan yuxarıdakı üçü mənasızdır: hər şeyi bloklayan səhv
    -- siyasət də onları keçərdi. Burada isə konsolun İŞLƏDİYİ təsdiqlənir.
    SET LOCAL ROLE vendor_rls_test_console;
    SELECT count(*) INTO v_visible FROM vendor.tenants;
    IF v_visible < 2 THEN
        RAISE EXCEPTION
            'TEST 4 UĞURSUZ: vendor rolu yalnız % sətir gördü — siyasət konsolu da '
            'bloklayır, yəni panel işləməz.', v_visible;
    END IF;

    SELECT count(*) INTO v_visible FROM vendor.support_tickets;
    IF v_visible < 2 THEN
        RAISE EXCEPTION 'TEST 4 UĞURSUZ: vendor rolu müraciətlərin hamısını görmür (%).', v_visible;
    END IF;
    RESET ROLE;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 4 ✓ vendor rolu bütün tenant-ları və müraciətləri görür';

    -- =====================================================================
    -- TEST 5 — RPC yalnız ÖZ statusunu verir (sadalama qapısı)
    -- =====================================================================
    -- FAZA 3-ün zəmanəti: `tenant_id` + `license_key` CÜTÜ uyğun gəlməsə
    -- cavab `UNKNOWN`-dır. «Tenant yoxdur» ilə «açar səhvdir» AYRILMIR.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        SET LOCAL ROLE anon;
        SELECT status INTO v_status FROM vendor.check_license_status(v_tenant_a, 'KEY-A');
        IF v_status IS DISTINCT FROM 'AKTIV' THEN
            RAISE EXCEPTION 'TEST 5 UĞURSUZ: düzgün cüt öz statusunu qaytarmadı (%).', v_status;
        END IF;

        SELECT status INTO v_status FROM vendor.check_license_status(v_tenant_b, 'KEY-A');
        IF v_status IS DISTINCT FROM 'UNKNOWN' THEN
            RAISE EXCEPTION
                'TEST 5 UĞURSUZ: səhv açarla BAŞQA tenant-ın statusu açıldı (%) — '
                'sadalama mümkündür.', v_status;
        END IF;
        RESET ROLE;
        v_passed := v_passed + 1;
        RAISE NOTICE 'TEST 5 ✓ RPC yalnız uyğun cütə cavab verir, əks halda UNKNOWN';
    END IF;

    RAISE NOTICE '';
    RAISE NOTICE '===========================================';
    RAISE NOTICE 'VENDOR RLS TESTLƏRİ UĞURLU: %', v_passed;
    RAISE NOTICE '===========================================';
END
$$;

-- Test məlumatı SAXLANILMIR: bütün blok bir tranzaksiyadadır.
ROLLBACK;
