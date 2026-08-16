-- ===========================================================================
-- VENDOR-003 — `check_license_status()` RPC (DB-3 FAZA 3)
-- ===========================================================================
-- Tarix : 2026-08-16
--
-- Müştərinin `.exe`-si öz statusunu soruşa bilməlidir, LAKİN bütün müştəri
-- siyahısını görməməlidir. Cədvələ birbaşa `SELECT` icazəsi bu iki tələbi
-- eyni anda ödəyə bilmir: RLS sətri süzsə belə, cədvəlin mövcudluğu, sütun
-- adları və sətir sayı barədə siqnal qalır.
--
-- Ona görə YEGANƏ giriş nöqtəsi bu funksiyadır: bir sətir, iki sütun, başqa
-- heç nə.
--
-- ---------------------------------------------------------------------------
-- `SECURITY DEFINER` — VƏ ONUN İKİ MƏCBURİ ŞƏRTİ
-- ---------------------------------------------------------------------------
-- Funksiya SAHİBİNİN hüquqları ilə işləyir, yəni çağırana `vendor.tenants`
-- üzərində heç bir imtiyaz lazım deyil. Bu güc iki qayda tələb edir:
--
--   1. `SET search_path` FUNKSİYADA SABİTLƏNİR. Əks halda çağıran öz
--      `search_path`-ını qurub `tenants` adlı saxta cədvəl yerləşdirə və
--      funksiyanı öz məlumatını oxumağa məcbur edə bilər (klassik
--      SECURITY DEFINER zəifliyi).
--   2. `REVOKE ... FROM PUBLIC` — `GRANT EXECUTE` AÇIQ və dar olmalıdır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ HƏM `tenant_id`, HƏM `license_key` TƏLƏB OLUNUR
-- ---------------------------------------------------------------------------
-- Tək `tenant_id` kifayət etsəydi, UUID-ni bilən hər kəs istənilən müştərinin
-- ödəniş vəziyyətini oxuya bilərdi — bu, kommersiya məlumatıdır. Cüt
-- uyğunsuzluğunda funksiya `UNKNOWN` qaytarır: «tenant yoxdur» ilə «açar
-- səhvdir» halları EYNİ cavabı verir, yəni sadalama (enumeration) siqnalı
-- yoxdur.
--
-- ---------------------------------------------------------------------------
-- BU FUNKSİYA HEÇ NƏ YAZMIR
-- ---------------------------------------------------------------------------
-- `last_checkin_at`-ı yeniləmək CAZİBƏDARDIR (panel «son əlaqə» sütununu
-- göstərir), lakin qərar açıqdır: MÜŞTƏRİ VENDOR BAZASINA YAZMIR. Yazsaydı,
-- anon açarı olan hər kəs sətri saatda minlərlə dəfə yeniləyə və panelin
-- göstərdiyi mənzərəni təhrif edə bilərdi. Check-in müştərinin ÖZ bazasındakı
-- `tenant_check_ins` cədvəlində qalır (bax `licensing/gateway.py`).
--
-- PARALEL REJİM: bu RPC hazırda müştəri tərəfindən ÇAĞIRILMIR — mövcud
-- lisenziya axını dəyişmir. Funksiya vendor bazası avtoritet olduqda hazır
-- olsun deyə indi qurulur.
-- ===========================================================================

BEGIN;

SET search_path TO vendor, public;

CREATE OR REPLACE FUNCTION vendor.check_license_status(
    p_tenant_id   UUID,
    p_license_key TEXT
)
RETURNS TABLE (status TEXT, next_payment_date DATE)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vendor, pg_temp
AS $$
BEGIN
    RETURN QUERY
    SELECT t.status, t.next_payment_date
      FROM vendor.tenants t
     WHERE t.tenant_id = p_tenant_id
       AND t.license_key = p_license_key;

    IF NOT FOUND THEN
        -- «Tapılmadı» ilə «açar səhvdir» AYIRD EDİLMİR — bax fayl başlığı.
        RETURN QUERY SELECT 'UNKNOWN'::TEXT, NULL::DATE;
    END IF;
END;
$$;

COMMENT ON FUNCTION vendor.check_license_status(UUID, TEXT) IS
    'Müştərinin öz lisenziya statusu — BİR sətir, İKİ sütun. Cədvələ birbaşa '
    'çıxış tələb etmir (SECURITY DEFINER). Uyğunsuzluqda `UNKNOWN` qaytarır ki, '
    'sadalama siqnalı olmasın. HEÇ NƏ YAZMIR.';

-- ---------------------------------------------------------------------------
-- İCRA İCAZƏSİ — DAR VƏ AÇIQ
-- ---------------------------------------------------------------------------
REVOKE ALL ON FUNCTION vendor.check_license_status(UUID, TEXT) FROM PUBLIC;

DO $$
DECLARE
    v_role TEXT;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated', 'kompasos_vendor'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format(
                'GRANT EXECUTE ON FUNCTION vendor.check_license_status(UUID, TEXT) TO %I',
                v_role);
        END IF;
    END LOOP;
END
$$;

-- `USAGE` sxem üzərində: funksiyanı ADI ilə çağırmaq üçün lazımdır. Cədvəl
-- imtiyazı VERİLMİR — yəni sxem görünür, məzmunu yox.
DO $$
DECLARE
    v_role TEXT;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA vendor TO %I', v_role);
        END IF;
    END LOOP;
END
$$;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- BEGIN;
--   DROP FUNCTION IF EXISTS vendor.check_license_status(UUID, TEXT);
--   -- Sxem `USAGE` icazəsi: REVOKE USAGE ON SCHEMA vendor FROM anon, authenticated;
-- COMMIT;
