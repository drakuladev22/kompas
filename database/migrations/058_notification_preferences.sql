-- ===========================================================================
-- 058 — BİLDİRİŞ TƏRCİHLƏRİ SAXLANILIR (`user_preferences.notification_prefs`)
-- ===========================================================================
-- Tarix : 2026-08-16
-- Səbəb : «Ayarlar» ekranında üç bildiriş açarı vardı («Təsdiq gözləyən
--         sorğular», «Server xəbərdarlıqları», «Gündəlik xülasə e-poçtu») və
--         onların vəziyyəti `collected()` payload-una da düşürdü — lakin
--         saxlanacaq YER yox idi. Yəni istifadəçi açarı söndürür, «Yadda
--         Saxla» basır, ekranı yenidən açır və açar YENƏ AÇIQ olurdu.
--
--         Bu, sadəcə «işləməyən düymə» deyil: istifadəçi bildirişi
--         söndürdüyünü SANIR və gələn bildirişi nasazlıq kimi qəbul edir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ JSONB, NİYƏ ÜÇ AYRI SÜTUN
-- ---------------------------------------------------------------------------
-- Bildiriş kanallarının siyahısı DƏYİŞKƏNDİR: modul əlavə olunanda yeni açar
-- yaranır (məs. «üz uyğunsuzluğu»). Hər kanal üçün sütun əlavə etmək hər yeni
-- modulda miqrasiya tələb edərdi və `user_preferences` tədricən onlarla
-- boolean sütuna çevrilərdi.
--
-- JSONB burada TƏHLÜKƏSİZDİR, çünki məzmun İSTİFADƏÇİ TƏRCİHİDİR — hesabat,
-- audit və ya pul hesablaması ona istinad etmir. (Layihədə JSONB-dən qaçmaq
-- qaydası məhz həmin kritik yollara aiddir.)
--
-- ---------------------------------------------------------------------------
-- DEFOLT: BOŞ OBYEKT = «HAMISI AÇIQ»
-- ---------------------------------------------------------------------------
-- Sətri olmayan istifadəçi üçün davranış BUGÜNKÜ ilə eynidir: bildiriş gedir.
-- Söndürmə YALNIZ açıq şəkildə yazılmış `false` ilə baş verir — yəni miqrasiya
-- heç kimin bildirişini sükutla kəsmir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS notification_prefs JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN user_preferences.notification_prefs IS
    'Bildiriş kanallarının açıq/bağlı vəziyyəti: {"approvals": true, '
    '"server_alerts": false, …}. Açar YOXDURSA kanal AÇIQ sayılır — yəni boş '
    'obyekt bugünkü davranışdır və heç bir bildiriş sükutla kəsilmir.';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Sütunun silinməsi istifadəçi tərcihlərini itirir; geri qaytarma yalnız
-- miqrasiyanın səhvən tətbiq edildiyi halda mənalıdır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE user_preferences DROP COLUMN IF EXISTS notification_prefs;
-- COMMIT;
