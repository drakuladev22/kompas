-- ===========================================================================
-- 059 — `license_tenants.company_contact_email` HƏR İKİ YOLDA `NOT NULL`
-- ===========================================================================
-- Tarix : 2026-08-16
-- Səbəb : DB-1 konsolidasiya auditi tək REAL tip/məhdudiyyət toqquşmasını
--         tapdı — sütunun nullability-si bazanın NECƏ qurulduğundan asılıdır:
--
--           * `schema.sql` ilə TƏMİZ quraşdırma → `TEXT NOT NULL` (sətir 200)
--           * 001-lə YÜKSƏLDİLMİŞ baza        → `ADD COLUMN ... TEXT` (nullable)
--
--         001 sütunu `IF NOT EXISTS` ilə əlavə edir; sütun artıq varsa
--         toxunmur, ona görə fərq sükutla yaşayır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ BU SÜTUN ÜÇÜN FƏRQ TƏHLÜKƏLİDİR
-- ---------------------------------------------------------------------------
-- `company_contact_email` ŞİRKƏT-səviyyəli əlaqədir və Emergency Access
-- Recovery-də kimlik təsdiqinin YEGANƏ mənbəyidir (bölmə 2, 8). Boş qalması o
-- deməkdir ki, Root hesabı bloklandıqda sistemə qayıtmağın heç bir yolu yoxdur
-- — və bunu istifadəçi məhz ən pis anda öyrənir. Yəni burada nullability
-- "üslub məsələsi" deyil, bərpa yolunun mövcudluğudur.
--
-- ---------------------------------------------------------------------------
-- NİYƏ BOŞ SƏTİRLƏR AVTOMATIK DOLDURULMUR
-- ---------------------------------------------------------------------------
-- `noreply@local` kimi yer-tutucu yazsaydıq, sütun formal olaraq dolar, bərpa
-- isə MÜMKÜNSÜZ qalardı — yəni qüsur gizlədilər, düzəldilməzdi. Ona görə
-- miqrasiya boş sətir aşkarlayanda AÇIQ XƏTA verir və hansı tenant-ın
-- doldurulmalı olduğunu yazır. Bu, layihənin "audit yazısı istisna udmur"
-- prinsipinin eyni məntiqidir: məcburi olan bir şeyin sükutla buraxılması onu
-- məcburi olmaqdan çıxarır.
--
-- İDEMPOTENT: sütun onsuz da `NOT NULL`-dursa heç nə edilmir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

DO $$
DECLARE
    v_nullable BOOLEAN;
    v_empty    BIGINT;
    v_ids      TEXT;
BEGIN
    SELECT is_nullable = 'YES' INTO v_nullable
      FROM information_schema.columns
     WHERE table_schema = 'kompasos'
       AND table_name   = 'license_tenants'
       AND column_name  = 'company_contact_email';

    IF v_nullable IS NULL THEN
        RAISE EXCEPTION
            'license_tenants.company_contact_email sütunu tapılmadı — '
            'əvvəlcə schema.sql və 001 tətbiq edilməlidir';
    END IF;

    IF NOT v_nullable THEN
        RAISE NOTICE 'company_contact_email onsuz da NOT NULL — dəyişiklik yoxdur.';
        RETURN;
    END IF;

    SELECT count(*), string_agg(tenant_id::TEXT, ', ')
      INTO v_empty, v_ids
      FROM license_tenants
     WHERE company_contact_email IS NULL OR btrim(company_contact_email) = '';

    IF v_empty > 0 THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: % tenant sətrində şirkət əlaqə e-poçtu boşdur '
            '(%). Bu sütun Emergency Access Recovery-nin yeganə kimlik mənbəyidir '
            '— yer-tutucu dəyər yazmaq bərpanı MÜMKÜNSÜZ qoyar. Həqiqi ünvanları '
            'doldurun və miqrasiyanı yenidən işlədin.',
            v_empty, v_ids;
    END IF;

    ALTER TABLE license_tenants
        ALTER COLUMN company_contact_email SET NOT NULL;

    RAISE NOTICE 'company_contact_email NOT NULL edildi.';
END
$$;

COMMENT ON COLUMN license_tenants.company_contact_email IS
    'Şirkət-səviyyəli əlaqə — fərdi hesabdan TAM AYRI. Emergency Access '
    'Recovery-də kimlik təsdiqinin yeganə mənbəyi (bölmə 2, 8). NOT NULL: '
    'miqrasiya 059-a qədər nullability quraşdırma yolundan asılı idi '
    '(schema.sql → NOT NULL, 001 → nullable).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Məhdudiyyətin götürülməsi bərpa kanalını yenidən boş qalmağa açır — yalnız
-- 059-un ÖZÜNDƏ qüsur aşkarlandıqda mənalıdır. Sətirlər dəyişmir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE license_tenants ALTER COLUMN company_contact_email DROP NOT NULL;
-- COMMIT;
