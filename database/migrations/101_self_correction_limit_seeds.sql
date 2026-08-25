-- ===========================================================================
-- 101 — ÖZ-DÜZƏLİŞ SORĞUSU TAVANLARININ SEED-İ (MÖVCUD + YENİ KİRAYƏÇİ)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Səbəb : İki açar `SystemLimitKey` + `DEFAULT_LIMITS`-ə əlavə olundu
--         (`v2backlog.md` Faza 4.2, migrations/097 ilə EYNİ buraxılış),
--         lakin SQL seed-i YAZILMADI — `test_root_control_parameter_parity.py`
--         qapısı hər ikisini tutdu (seed yoxdur; `description_az` yoxdur):
--
--             * `SELF_CORRECTION_REQUEST_WINDOW_DAYS`,
--             * `SELF_CORRECTION_REQUEST_MAX_COUNT`.
--
--         Seed olmadan parametr ROOT ekranında GÖRÜNÜR, lakin dəyəri
--         `system_limits` sətri olmadığı üçün KODDA oturan fallback-dan
--         gəlir. Root dəyəri dəyişib yadda saxlasa,
--         `UPDATE ... WHERE limit_key = ...` heç bir sətrə dəyməz: ekran
--         dəyişikliyi qəbul etmiş kimi görünər, davranış isə əvvəlki qalar.
--         Bu, 082/084-ün başlıqlarında təsvir olunan EYNİ qüsurdur —
--         üç halqadan (enum → `DEFAULT_LIMITS` → SQL seed) sonuncusunun
--         qırıq qalması.
--
-- ---------------------------------------------------------------------------
-- NİYƏ 097-YƏ YOX, YENİ MİQRASİYA
-- ---------------------------------------------------------------------------
-- 097 artıq REYESTRDƏDİR (migrations/061): fayl adı + SHA-256 yazılıb və
-- canlı bazalara tətbiq olunub. Onu redaktə etmək reyestrin SHA-sını pozar
-- və icraçı növbəti dövrədə miqrasiyanı «dəyişdirilib» elan edərdi. Ona
-- görə unudulmuş seed HƏMİŞƏ yeni faylda gəlir — 084 məhz bu səbəblə
-- yaradılmışdı və eyni yolu təkrarlayır.
--
-- ---------------------------------------------------------------------------
-- DEFOLT DƏYƏRLƏR UYDURULMUR — `DEFAULT_LIMITS`-DƏN GÖTÜRÜLÜB
-- ---------------------------------------------------------------------------
-- `policies.py`: 30 / 3. Seed başqa dəyər yazsaydı, EYNİ parametrin iki
-- fərqli defoltu olardı: yeni quraşdırmada SQL sətri, fallback yolunda isə
-- kod dəyəri — və fərq yalnız baza əlçatmaz olanda üzə çıxardı.
--
-- ---------------------------------------------------------------------------
-- HÜDUDLAR (`min_value`/`max_value`) — HƏR BİRİ AYRICA ƏSASLANDIRILIR
-- ---------------------------------------------------------------------------
-- Bu ikisi `INFRA_LIMIT_BOUNDS`-da YOXDUR (tətbiq qatı `_limit_int(...)`
-- ilə oxuyur), yəni SQL hüdudları ilə kod arasında paritet tələbi yoxdur.
-- Hüdudlar yenə də YAZILIR, çünki `system_limits.set_value()` sərbəst mətn
-- qəbul edir və ROOT ekranı diapazonu məhz bu sütunlardan göstərir:
--
--   * `SELF_CORRECTION_REQUEST_WINDOW_DAYS` 1..90 — kod `now() - timedelta(
--     days=window)` pəncərəsi ilə sayır: `0` pəncərəni SIFIRA endirər və
--     sayağ heç bir sorğu pəncərəyə düşməzdi, yəni tavan öz-özünü ləğv
--     edərdi (sui-istifadə qoruması susardı). 90-dan yuxarı «son N gün» isə
--     rübük/mövsümi işçi dövriyyəsindən uzun olduğu üçün sayılan sorğuların
--     əksəriyyəti artıq aktual olmayan hadisələrə aid olardı.
--   * `SELF_CORRECTION_REQUEST_MAX_COUNT` 1..20 — `0` BÜTÜN öz-düzəliş
--     sorğularını bloklayardı; onu söndürmək istəyən Root üçün ayrıca modul
--     açarı var (`FeatureModule`), sıfır isə gizli ikinci söndürmə yolu
--     yaradardı. 20-dən yuxarı isə tavan real funksiyasını itirir —
--     eyni bəhanəni həftədə iyirmidən artıq dəfə sınamaq normal işçi
--     davranışı deyil.
--
-- ---------------------------------------------------------------------------
-- `value_type` NİYƏ 'INTEGER'
-- ---------------------------------------------------------------------------
-- Biri GÜN sayıdır, digəri SAY; kod hər ikisini `_limit_int(...)` ilə oxuyur.
-- 084-ün şərhindəki eyni qayda: yazılan tip oxunan tiplə üst-üstə düşməlidir.
--
-- ---------------------------------------------------------------------------
-- İKİ BLOK (MÖVCUD + YENİ KİRAYƏÇİ) — 062/072/082/084 NAXIŞI
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` TOXUNULMUR: hər miqrasiyanın öz açarını ora
-- yazması həmin faylı bütün miqrasiyaların yığınına çevirərdi. Sətir formatı
-- iki blokda HƏRFƏN eynidir — format ayrılsaydı paritet qapıları açarı
-- «trigger-də yoxdur» deyə oxuyardı.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('SELF_CORRECTION_REQUEST_WINDOW_DAYS', '30', 'INTEGER', '1', '90',
     'İşçinin öz-düzəliş sorğusunda sui-istifadə tavanının sayım pəncərəsi '
     '(gün): bu müddət ərzində göndərilmiş sorğular sayılır. Tavanın ÖZÜ '
     'ayrıca açardır — bu, yalnız «nə vaxt» sualına cavab verir'),
    ('SELF_CORRECTION_REQUEST_MAX_COUNT', '3', 'INTEGER', '1', '20',
     'Sayım pəncərəsi ərzində bir işçinin göndərə biləcəyi ən çox öz-düzəliş '
     'sorğusu. Hədd aşılanda yeni sorğu RƏDD olunur və işçiyə səbəb '
     'göstərilir — HR-a bildiriş gedən mövcud axın dəyişmir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR (062/072/082/084 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_self_correction_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('SELF_CORRECTION_REQUEST_WINDOW_DAYS', '30', 'INTEGER', '1', '90',
         'İşçinin öz-düzəliş sorğusunda sui-istifadə tavanının sayım pəncərəsi '
         '(gün): bu müddət ərzində göndərilən sorğular sayılır. Tavanın ÖZÜ '
         'ayrıca açardır — bu, yalnız «nə vaxt» sualına cavab verir'),
        ('SELF_CORRECTION_REQUEST_MAX_COUNT', '3', 'INTEGER', '1', '20',
         'Sayım pəncərəsi ərzində bir işçinin göndərə biləcəyi ən çox öz-düzəliş '
         'sorğusu. Hədd aşılanda yeni sorğu RƏDD olunur və işçiyə səbəb '
         'göstərilir — HR-a bildiriş gedən mövcud axın dəyişmir')
      ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_self_correction_limits_for_new_tenant() IS
    'Yeni kirayəçiyə öz-düzəliş sorğusunun sui-istifadə tavan cütünü '
    '(v2backlog.md Faza 4.2) əlavə edir (migrations/101). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_self_correction_limits ON license_tenants;
CREATE TRIGGER trg_seed_self_correction_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_self_correction_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Root dəyərlərdən hər hansını əl ilə dəyişmişsə DOWN onu da silir — sətir
-- yenidən yaransa dəyər defolta qayıdar, yəni siyasət seçimi İTƏR. Ona görə
-- DOWN yalnız miqrasiyanın SƏHVƏN tətbiqi halı üçündür:
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_self_correction_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_self_correction_limits_for_new_tenant();
--   DELETE FROM system_limits
--    WHERE limit_key IN ('SELF_CORRECTION_REQUEST_WINDOW_DAYS',
--                        'SELF_CORRECTION_REQUEST_MAX_COUNT');
-- COMMIT;
-- ===========================================================================
