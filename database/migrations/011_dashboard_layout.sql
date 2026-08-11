-- ===========================================================================
-- MIGRATION 011 — İSTİFADƏÇİ ÜZRƏ DASHBOARD DÜZÜLÜŞÜ
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : Bölmə 6 "DASHBOARD BUILDER: Configurable widget grid" tələb edir.
--         `user_preferences` yalnız tema və dil saxlayırdı — hansı bölmələrin
--         görünəcəyi və hansı sıra ilə düzüləcəyi heç yerdə saxlanmırdı, yəni
--         istifadəçinin qurduğu düzülüş tətbiq bağlananda İTİRDİ.
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `JSONB` MASSİV, NİYƏ AYRI CƏDVƏL DEYİL
-- ---------------------------------------------------------------------------
-- Düzülüş SIRALI siyahıdır və həmişə TAM oxunur/tam yazılır — heç vaxt "üçüncü
-- widget-i tapıb yenilə" sorğusu olmur. Ayrı cədvəldə hər dəyişiklik `DELETE` +
-- `INSERT` dəsti tələb edərdi və sıra sütununun boşluqları ("1, 2, 5") ayrıca
-- problemə çevrilərdi. Massiv sıranı öz strukturunda saxlayır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ YALNIZ GÖRÜNƏNLƏR SAXLANILIR
-- ---------------------------------------------------------------------------
-- Massivdə olan = görünür, olmayan = gizlidir. "Gizli" siyahısını da
-- saxlasaydıq, yeni widget əlavə edildikdə o, heç bir siyahıda olmazdı və
-- "görünsün, ya yox?" sualı cavabsız qalardı. İndiki modeldə cavab sadədir:
-- yeni widget siyahıda yoxdur → gizlidir → istifadəçi özü açır.
--
-- BOŞ massiv (`'[]'`) ilə `NULL` FƏRQLİDİR:
--   NULL → istifadəçi heç vaxt düzülüş qurmayıb, DEFOLT göstərilir;
--   []   → istifadəçi hər şeyi qəsdən gizlədib, boş dashboard göstərilir.
-- Bu fərq olmasaydı, "hamısını gizlət" əməliyyatı defolta qayıtma kimi
-- görünərdi və istifadəçi seçimini geri ala bilməzdi.
-- ===========================================================================

BEGIN;

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
-- (Bu miqrasiyada sətir UNUDULMUŞDU — CI-da 010 məhz buna görə çökürdü.)
SET search_path TO kompasos, public;


ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS dashboard_layout JSONB,
    ADD COLUMN IF NOT EXISTS dashboard_updated_at TIMESTAMPTZ;

-- Massiv olmayan dəyər (obyekt, mətn) oxuma tərəfini çökdürərdi.
ALTER TABLE user_preferences
    DROP CONSTRAINT IF EXISTS chk_dashboard_layout_is_array;
ALTER TABLE user_preferences
    ADD CONSTRAINT chk_dashboard_layout_is_array
        CHECK (dashboard_layout IS NULL OR jsonb_typeof(dashboard_layout) = 'array');

COMMENT ON COLUMN user_preferences.dashboard_layout IS
    'Görünən dashboard bölmələri, SIRA ilə (bölmə 6). NULL = defolt düzülüş, '
    '[] = istifadəçi hər şeyi gizlədib.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün)
-- ===========================================================================
-- BEGIN;
-- ALTER TABLE user_preferences DROP CONSTRAINT IF EXISTS chk_dashboard_layout_is_array;
-- ALTER TABLE user_preferences
--     DROP COLUMN IF EXISTS dashboard_updated_at,
--     DROP COLUMN IF EXISTS dashboard_layout;
-- COMMIT;
