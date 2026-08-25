-- ===========================================================================
-- 105 — KIOSK İLK-İSTİFADƏ BƏLƏDÇİSİ (v2backlog.md Faza 10)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 10 — yeni işçi ilk dəfə Kiosk-da PIN-ekranını
--         görəndə 3-4 addımlı, keçilə-bilən bələdçi.
--
-- NİYƏ YENİ CƏDVƏL DEYİL, SÜTUN
-- ---------------------------------------------------------------------------
-- «Bələdçini gördüm» faktı İSTİFADƏÇİNİN TƏRCHİDİR («keç» də qərardır) və
-- mövcud `user_preferences` cədvəli məhz tərcihlərin yeridir (tema/dil —
-- bölmə 9). Ayrı `kiosk_onboarding` cədvəli EYNİ sualın ikinci cavab yeri
-- olardı: iki yerdə saxlanılan bayraqdan hansı doğrudur?
--
-- NİYƏ DEFOLT FALSE VƏ NİYƏ NOT NULL
-- ---------------------------------------------------------------------------
-- Mövcud işçinin sətri yoxdursa, o bələdçini HƏLƏ GÖRMƏYİB deməkdir — yəni
-- bayraq onsuz da `FALSE` mənasındadır (`preferences.py::kiosk_onboarding_
-- done` boş sətri elə oxuyur). `NOT NULL` isə «bilmirəm» vəziyyətini qadağan
-- edir: ya görüb, ya görməyib.
--
-- RETROAKTİVLIK: miqrasiyadan SONRA ilk girişdə bütün mövcud işçilər
-- bələdçini BİR DƏFƏ görəcək. Bu, arzuolunanz deyil — yenilənmə ilə gələn
-- yeni ekranlar üçün bir dəfəlik tanışlıq faydalıdır; amma istənilsə Root
-- sütunu əl ilə TRUE edib söndürə bilər (adi UPDATE).
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS kiosk_onboarding_done BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN user_preferences.kiosk_onboarding_done IS
    'Faza 10 (v2backlog.md): Kiosk ilk-istifadə bələdçisinin bu istifadəçi '
    'üçün göstərilib-göstərilməməsi. «Keç» də QƏRDDİR — bayraq onsuz da '
    'qoyulur, çünki məqsəd məcburiyyət deyil, tanışlıqdır. Sətir yoxdursa '
    '«görməyib» sayılır (repo fail-safe oxuyur).';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE user_preferences DROP COLUMN IF EXISTS kiosk_onboarding_done;
-- COMMIT;
-- ===========================================================================
