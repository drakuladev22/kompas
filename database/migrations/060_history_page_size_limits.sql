-- ===========================================================================
-- 060 — İŞÇİ TARİXÇƏSİNİN SƏHİFƏ ÖLÇÜLƏRİ ROOT-A KEÇİR (DB-2 FAZA 4)
-- ===========================================================================
-- Tarix : 2026-08-16
-- Səbəb : DB-2 hardcode auditi iki sabit tapdı və hər ikisi eyni, xüsusilə
--         gizli formada idi — dəyər repozitoriya metodunun DEFOLT ARQUMENTİ
--         kimi yazılmışdı:
--
--             list_for_employee(self, employee_id, *, limit: int = 50)
--
--         Çağıran tərəf (`shift_scheduling.my_requests`,
--         `fine_management.my_appeals`) limiti ÖTÜRMÜRDÜ, yəni 50 həddi
--         faktiki qüvvədə idi. Nə Root panelində görünürdü, nə də başqa
--         yerdən dəyişdirilə bilirdi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ BU, SADƏ "SƏHİFƏ ÖLÇÜSÜ" MƏSƏLƏSİNDƏN BÖYÜKDÜR
-- ---------------------------------------------------------------------------
-- Hər iki siyahı İŞÇİNİN ÖZ tarixçəsidir: növbə dəyişmə sorğuları və cərimə
-- etirazları. 50-dən çox sətri olan işçi qalanını HEÇ BİR yolla görə bilmirdi
-- və ekranda "daha çox var" işarəsi də yox idi — yəni məlumat sükutla kəsilir,
-- istifadəçi isə tarixçəsinin tam olduğunu sanırdı. Cərimə etirazı isə pul
-- mübahisəsinin sənədidir.
--
-- ---------------------------------------------------------------------------
-- DƏYƏR DƏYİŞMİR
-- ---------------------------------------------------------------------------
-- Defolt hər ikisində 50 qalır — köçürmə davranışı dəyişdirmir, yalnız dəyəri
-- Root-un əli çatan və audit-lənən yerə gətirir (CLAUDE.md §5). Aşağı hüdud
-- 1-dir: 0 yazılsa siyahı HƏMİŞƏ boş qayıdardı və istifadəçi "məlumat yoxdur"
-- ilə "limit sıfırdır" arasındakı fərqi görə bilməzdi (034 ilə eyni qərar).
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('SHIFT_SWAP_HISTORY_PAGE_SIZE', '50', 'INTEGER', '1', '1000',
     'İşçinin növbə-dəyişmə tarixçəsinin bir oxunuşda gətirdiyi sətir sayı'),
    ('FINE_APPEAL_HISTORY_PAGE_SIZE', '50', 'INTEGER', '1', '1000',
     'İşçinin cərimə-etirazı tarixçəsinin bir oxunuşda gətirdiyi sətir sayı')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR — 034 İLƏ EYNİ TRIGGER NAXIŞI
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` TOXUNULMUR: o, bazis sxemin funksiyasıdır və hər
-- miqrasiyanın öz açarlarını ora əlavə etməsi faylı zaman keçdikcə bütün
-- miqrasiyaların yığınına çevirərdi. Ayrı trigger hər miqrasiyanı öz
-- açarlarının sahibi saxlayır.
CREATE OR REPLACE FUNCTION seed_history_page_size_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'SHIFT_SWAP_HISTORY_PAGE_SIZE', '50', 'INTEGER', '1', '1000',
         'İşçinin növbə-dəyişmə tarixçəsinin bir oxunuşda gətirdiyi sətir sayı'),
        (NEW.tenant_id, 'FINE_APPEAL_HISTORY_PAGE_SIZE', '50', 'INTEGER', '1', '1000',
         'İşçinin cərimə-etirazı tarixçəsinin bir oxunuşda gətirdiyi sətir sayı')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_history_page_size_limits_for_new_tenant() IS
    'Yeni kirayəçiyə işçi-tarixçəsi səhifə ölçülərini əlavə edir '
    '(migrations/060). Dəyərlər köçürmədən əvvəlki sabitlə eynidir (50).';

DROP TRIGGER IF EXISTS trg_seed_history_page_size_limits ON license_tenants;
CREATE TRIGGER trg_seed_history_page_size_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_history_page_size_limits_for_new_tenant();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Açarların silinməsi kodu `DEFAULT_LIMITS` fallback-ına qaytarır (davranış
-- dəyişmir, yalnız Root nəzarəti itir). Root-un DƏYİŞDİRDİYİ dəyər isə itər —
-- ona görə yalnız miqrasiyanın özündə qüsur aşkarlandıqda mənalıdır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_history_page_size_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_history_page_size_limits_for_new_tenant();
--   DELETE FROM system_limits
--    WHERE limit_key IN ('SHIFT_SWAP_HISTORY_PAGE_SIZE', 'FINE_APPEAL_HISTORY_PAGE_SIZE');
-- COMMIT;
