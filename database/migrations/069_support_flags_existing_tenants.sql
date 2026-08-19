-- ===========================================================================
-- 069 — DƏSTƏK FLAG-LƏRİ MÖVCUD KİRAYƏÇİLƏRƏ DƏ VERİLİR
-- ===========================================================================
-- Tarix : 2026-08-18
-- Səbəb : Miqrasiya 068 qrantı YALNIZ sistem şablonuna yazdı.
--
--         068-in `position_permissions` INSERT-lərində `AND p.tenant_id IS
--         NULL` süzgəci var. O süzgəc flag əlavə edən BÜTÜN digər
--         miqrasiyaların naxışından fərqlidir və onlar bunu açıq
--         əsaslandırıb — məsələn 047:
--
--             «`WHERE p.code IN ('ROOT','CEO')` TENANT FİLTRSİZDİR … həm
--              sistem şablonu, həm də ARTIQ mövcud kirayəçilərin rol
--              sətirləri əhatə olunur»
--
--         Səbəb `seed_tenant_defaults()`-un işləmə anındadır: o, kirayəçi
--         YARADILARKƏN sistem rollarını və onların HƏMİN ANDAKI icazə
--         sətirlərini KOPYALAYIR. Sonradan şablona əlavə olunan flag mövcud
--         kopyaya avtomatik DÜŞMÜR — yəni tenant filtri qoyulan miqrasiya
--         yalnız GƏLƏCƏK kirayəçilərə təsir edir.
--
-- ---------------------------------------------------------------------------
-- NƏTİCƏ CANLI BAZADA ÖLÇÜLDÜ
-- ---------------------------------------------------------------------------
-- 068-dən ƏVVƏL yaradılmış kirayəçidə:
--
--     ROOT nüsxəsi : 48 flag, dəstək flag-i 0/3
--     ROOT şablonu : 51 flag, dəstək flag-i 3/3
--
-- Yəni həmin kirayəçidə `Root` «Daxili Müraciətlər» və «Texniki Dəstək»
-- maddələrini menyuda GÖRMÜR (menyu `required_flag` ilə süzülür) və Telegram
-- konfiqurasiyası əlçatmaz qalır — CHAT-1/SEC-029 funksiyaları sükutla
-- işləmir. Səhv «flag yoxdur» kimi deyil, «maddə yoxdur» kimi görünür, ona
-- görə səbəbi tapmaq çətindir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ 068 REDAKTƏ EDİLMİR
-- ---------------------------------------------------------------------------
-- `scripts/apply_migrations.py` hər faylın SHA-256-sını `schema_migrations`
-- reyestrinə yazır və tətbiq olunmuş faylı sonradan dəyişmək reyestrlə
-- uyğunsuzluq yaradır (miqrasiya 061). Tətbiq olunmuş miqrasiya
-- DƏYİŞDİRİLMİR — düzəliş HƏMİŞƏ növbəti fayl ilə gəlir.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING` — flag-i artıq daşıyan sətir toxunulmur, yəni
-- Root-un ƏL İLƏ ləğv etdiyi (`granted = FALSE`) qərar da geri qaytarılmır.
-- ===========================================================================

-- Sxem yolu MİQRASİYADA təyin olunur (bütün digər fayllarla eyni): trigger
-- funksiyaları (`enforce_anti_fraud_segregation`) cədvəllərə KVALİFİKASİYASIZ
-- müraciət edir və `search_path` olmadan «relation does not exist» ilə çökür.
SET search_path TO kompasos, public;

BEGIN;

-- «Daxili Müraciət» görüntüsü — CHAT-1: müştəri tərəfinin idarəçiləri.
-- Rol siyahısı 068 ilə HƏRFƏN eynidir, yeganə fərq tenant süzgəcinin
-- OLMAMASIDIR.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_view_internal_requests', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN')
ON CONFLICT DO NOTHING;

-- «Texniki Dəstək» və Telegram konfiqurasiyası — YALNIZ `Root` (SEC-028/029):
-- texniki kanal təchizatçıya gedir, müştərinin ən üst hesabına yox.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
  FROM positions p
 CROSS JOIN (VALUES
        ('can_view_technical_support'),
        ('can_manage_telegram_config')
     ) AS f(flag_code)
 WHERE p.code = 'ROOT'
ON CONFLICT DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- BEGIN;
-- -- DİQQƏT: bu geri qaytarma 068-in verdiyi ŞABLON sətirlərini də silər,
-- -- çünki iki miqrasiyanın yazdığı sətirlər fərqlənmir. Yalnız 069-u geri
-- -- almaq lazımdırsa şərt `positions.tenant_id IS NOT NULL` ilə daraldılmalıdır.
-- DELETE FROM position_permissions
--  WHERE flag_code IN (
--            'can_view_internal_requests',
--            'can_view_technical_support',
--            'can_manage_telegram_config'
--        )
--    AND position_id IN (SELECT id FROM positions WHERE tenant_id IS NOT NULL);
-- COMMIT;
