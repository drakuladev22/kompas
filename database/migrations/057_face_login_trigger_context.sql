-- ===========================================================================
-- 057 — ÜZ TƏSDİQİ ARTIQ GİRİŞİN ÖZÜNDƏ DƏ İŞLƏYİR (`trigger_context = LOGIN`)
-- ===========================================================================
-- Tarix : 2026-08-16
-- Səbəb : Üz qapısı indiyə qədər YALNIZ günün axınına (STEP_A / STEP_1 /
--         STEP_2) qoyulmuşdu — yəni PIN daxil edilir, İşçi Ana Ekranı AÇILIR,
--         üz isə sonrakı ƏMƏLİYYATDA yoxlanılırdı.
--
--         Bu, anti-fraud zəncirində real bir boşluq idi: PIN-i başqasına verən
--         işçinin adından ekran AÇILIR, həmin adam öz açıq tapşırıqlarını,
--         xal balansını və cərimə tarixçəsini GÖRÜRDÜ. Üz qapısı yalnız
--         «İşə Başladım» basıldıqda işə düşürdü — halbuki məlumat artıq
--         ekrandaydı. Kiosk mağaza zalındadır və PIN dörd rəqəmdir.
--
--         İndi qapı girişin ÖZÜNDƏDİR: PIN uğurlu olduqdan sonra üz təsdiqi
--         keçmirsə, ekran ümumiyyətlə açılmır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ YENİ DƏYƏR, NİYƏ MÖVCUD `STEP_A` TƏKRAR İŞLƏDİLMİR
-- ---------------------------------------------------------------------------
-- `STEP_A` səhər girişinin (işə başlama) qeydidir və hesabatlarda «bu gün neçə
-- nəfər işə başladı» sualına cavab verir. Girişi də ora yazsaydıq, iki fərqli
-- hadisə bir sətir tipinə yığılardı: işçi gün ərzində kiosku beş dəfə açırsa,
-- `STEP_A` sayı beş olardı və davamiyyət hesabatı yalan danışardı.
--
-- Ayrıca dəyər həm də araşdırma üçün lazımdır: «kimin adından kim giriş
-- etməyə çalışıb» sualının cavabı məhz bu sətirlərdədir.
--
-- ---------------------------------------------------------------------------
-- MÖVCUD SƏTİRLƏRƏ TƏSİRİ YOXDUR
-- ---------------------------------------------------------------------------
-- `CHECK` siyahısı YALNIZ GENİŞLƏNİR. Köhnə üç dəyər olduğu kimi qalır, yəni
-- heç bir mövcud sətir yararsız olmur və geri qaytarma da (aşağıdakı DOWN)
-- yalnız yeni dəyər işlədilməyibsə mümkündür — ona görə DOWN blokunda əvvəlcə
-- həmin sətirlərin sayı yoxlanılır.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

ALTER TABLE face_verification_log
    DROP CONSTRAINT IF EXISTS face_verification_log_trigger_context_check;

ALTER TABLE face_verification_log
    ADD CONSTRAINT face_verification_log_trigger_context_check
    CHECK (trigger_context IN ('STEP_A', 'STEP_1', 'STEP_2', 'LOGIN'));

COMMENT ON COLUMN face_verification_log.trigger_context IS
    'Üz təsdiqinin tətbiq nöqtəsi: LOGIN (kiosk girişi — PIN-dən dərhal '
    'sonra, ekran açılmazdan ƏVVƏL), STEP_A (səhər işə başlama), STEP_1 '
    '(icazə sorğusu), STEP_2 (qayıdış təsdiqi).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Geri qaytarma YALNIZ `LOGIN` sətri yoxdursa təhlükəsizdir: sətir varsa,
-- `CHECK` daralması cədvəli yararsız vəziyyətə salar (mövcud sətir yeni
-- şərtə uyğun gəlmir) və `ALTER TABLE` xəta verər. Ona görə əvvəlcə silinir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DELETE FROM face_verification_log WHERE trigger_context = 'LOGIN';
--   ALTER TABLE face_verification_log
--       DROP CONSTRAINT IF EXISTS face_verification_log_trigger_context_check;
--   ALTER TABLE face_verification_log
--       ADD CONSTRAINT face_verification_log_trigger_context_check
--       CHECK (trigger_context IN ('STEP_A', 'STEP_1', 'STEP_2'));
-- COMMIT;
