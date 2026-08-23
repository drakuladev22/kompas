-- ===========================================================================
-- 084 — DÖRD YENİ ROOT PARAMETRİNİN SEED-İ (MÖVCUD + YENİ KİRAYƏÇİ)
-- ===========================================================================
-- Tarix : 2026-08-23
-- Səbəb : Dörd açar `SystemLimitKey` + `DEFAULT_LIMITS`-ə əlavə olundu, lakin
--         SQL seed-i YAZILMADI — `test_root_control_parameter_parity.py`
--         qapısı hər ikisini tutdu (seed yoxdur; `description_az` yoxdur):
--
--             * `EVIDENCE_UPLOAD_RETENTION_DAYS` (SAAS-6),
--             * `FACE_ENROLLMENT_GRACE_DAYS`     (UX-7),
--             * `FINE_APPEAL_ESCALATION_DAYS`    (HR-1),
--             * `FINE_REVIEW_OVERDUE_DAYS`       (HR-2).
--
--         Seed olmadan parametr ROOT ekranında GÖRÜNÜR (`list_limits` enum
--         üzərində dövr edir), lakin dəyəri `system_limits` sətri olmadığı
--         üçün `DEFAULT_LIMITS`-dən — yəni KODDA oturan fallback-dan — gəlir.
--         Root dəyəri dəyişib yadda saxlasa, `UPDATE ... WHERE limit_key = ...`
--         heç bir sətrə dəyməz: ekran dəyişikliyi qəbul etmiş kimi görünər,
--         davranış isə əvvəlki qalar. Bu, 082-nin başlığında təsvir olunan
--         EYNİ qüsurdur — üç halqadan (enum → `DEFAULT_LIMITS` → SQL seed)
--         sonuncusunun qırıq qalması.
--
-- ---------------------------------------------------------------------------
-- NİYƏ DÖRDÜ BİR MİQRASİYADA
-- ---------------------------------------------------------------------------
-- Dördü də EYNİ qüsurun (seed unudulması) nəticəsidir və heç biri digərinin
-- davranışına toxunmur — yəni ayrı-ayrı fayllara bölmək dörd eyni strukturlu
-- miqrasiya və dörd ayrı trigger yaradardı. Reyestrdə (migrations/061) bir
-- sətir olması izləməni də asanlaşdırır: «hansı buraxılışda hansı parametrlər
-- gəldi» sualı bir SHA ilə cavablanır.
--
-- ---------------------------------------------------------------------------
-- DEFOLT DƏYƏRLƏR UYDURULMUR — `DEFAULT_LIMITS`-DƏN GÖTÜRÜLÜB
-- ---------------------------------------------------------------------------
-- `policies.py`: 30 / 7 / 3 / 30. Seed başqa dəyər yazsaydı, EYNİ parametrin
-- iki fərqli defoltu olardı: yeni quraşdırmada SQL sətri, fallback yolunda isə
-- kod dəyəri — və fərq yalnız baza əlçatmaz olanda üzə çıxardı.
--
-- ---------------------------------------------------------------------------
-- HÜDUDLAR (`min_value`/`max_value`) — HƏR BİRİ AYRICA ƏSASLANDIRILIR
-- ---------------------------------------------------------------------------
-- Bu dördü `INFRA_LIMIT_BOUNDS`-da YOXDUR (infrastruktur onları oxumur —
-- tətbiq qatı `_limit_int(...)` ilə oxuyur), yəni SQL hüdudları ilə kod
-- arasında paritet tələbi yoxdur. Hüdudlar yenə də YAZILIR, çünki `system_
-- limits.set_value()` sərbəst mətn qəbul edir və ROOT ekranı diapazonu məhz
-- bu sütunlardan göstərir:
--
--   * `EVIDENCE_UPLOAD_RETENTION_DAYS` 1..365 — `0` «hər dövrədə hamısını sil»
--     demək olardı və terminaldakı diaqnostika izi tamamilə itərdi (sətir
--     yalnız İŞİNİ BİTİRMİŞ yükləmə üçün yaranır, bax `purge_uploaded`).
--     365-dən yuxarı isə həll edilmək istənən problemi (sonsuz böyüyən lokal
--     SQLite) geri qaytarardı.
--   * `FACE_ENROLLMENT_GRACE_DAYS` 1..90 — `0` işçini işə götürüldüyü GÜN
--     menecerin «İstisnalar» siyahısına salardı, yəni möhlət anlayışı itərdi;
--     90-dan yuxarı möhlət isə qeydiyyat tələbini praktiki olaraq ləğv edir.
--   * `FINE_APPEAL_ESCALATION_DAYS` 1..30 — `0` etirazı yazıldığı gün
--     eskalasiya edərdi (HR-a cavab vermək imkanı qalmır); 30-dan yuxarı dəyər
--     isə cavabsızlığı «problem» saymağı 72 saatlıq etiraz pəncərəsindən
--     (bölmə 4) on dəfə uzun bir müddətə atardı.
--   * `FINE_REVIEW_OVERDUE_DAYS` 7..180 — icmal AYLIQ ritmdədir (CLAUDE.md §9:
--     `PENDING_REVIEW` → aylıq icmal → `PUBLISHED`), ona görə 7 gündən kiçik
--     hədd NORMAL dövrəni «gecikmiş» elan edərdi və siqnal dəyərini itirərdi.
--     180-dən yuxarı isə işçinin etiraz hüququnu yarım ildən artıq gözlədərdi.
--
-- ---------------------------------------------------------------------------
-- `value_type` NİYƏ 'INTEGER'
-- ---------------------------------------------------------------------------
-- Dördü də GÜN sayıdır və kod onları `_limit_int(...)` ilə oxuyur. 082-nin
-- şərhindəki eyni qayda: yazılan tip oxunan tiplə üst-üstə düşməlidir, əks
-- halda ROOT ekranı fərqli redaktor göstərər, oxu yolu isə dəyişməz qalar.
--
-- ---------------------------------------------------------------------------
-- İKİ BLOK (MÖVCUD + YENİ KİRAYƏÇİ) — 062/072/082-NİN NAXIŞI
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` TOXUNULMUR: hər miqrasiyanın öz açarını ora
-- yazması həmin faylı bütün miqrasiyaların yığınına çevirərdi. Sətir formatı
-- iki blokda HƏRFƏN eynidir — 062-nin şərhindəki səbəb: format ayrılsaydı
-- paritet qapıları açarı «trigger-də yoxdur» deyə oxuyardı.
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
    ('EVIDENCE_UPLOAD_RETENTION_DAYS', '30', 'INTEGER', '1', '365',
     'Yüklənməsi tamamlanmış sübut sətri və həll edilmiş sinxronizasiya '
     'münaqişəsi bu terminalda neçə gün saxlanılsın. Sübut şəkli Google '
     'Drive-da QALIR — silinən yalnız yerli iz qeydidir'),
    ('FACE_ENROLLMENT_GRACE_DAYS', '7', 'INTEGER', '1', '90',
     'İşə götürüldükdən sonra üz qeydiyyatı üçün verilən möhlət (gün). '
     'Möhlət bitəndə işçi BLOKLANMIR — sətir yalnız menecerin «İstisnalar» '
     'siyahısında görünür'),
    ('FINE_APPEAL_ESCALATION_DAYS', '3', 'INTEGER', '1', '30',
     'Cavabsız qalan cərimə etirazı neçə gündən sonra İstisna Motoruna '
     'qaldırılsın. İşçinin etiraz vermə pəncərəsi ilə qarışdırılmır — bu, '
     'HR-ın cavab müddətidir'),
    ('FINE_REVIEW_OVERDUE_DAYS', '30', 'INTEGER', '7', '180',
     'Cərimə nəşr gözləmə vəziyyətində («Aylıq Cərimə İcmalı») neçə gün qala '
     'bilər. Hədd aşılanda cərimə gecikmiş sayılır: işçi onu hələ görməyib, '
     'yəni etiraz müddəti də başlamayıb')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR (062/072/082 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_hr_and_retention_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('EVIDENCE_UPLOAD_RETENTION_DAYS', '30', 'INTEGER', '1', '365',
         'Yüklənməsi tamamlanmış sübut sətri və həll edilmiş sinxronizasiya '
         'münaqişəsi bu terminalda neçə gün saxlanılsın. Sübut şəkli Google '
         'Drive-da QALIR — silinən yalnız yerli iz qeydidir'),
        ('FACE_ENROLLMENT_GRACE_DAYS', '7', 'INTEGER', '1', '90',
         'İşə götürüldükdən sonra üz qeydiyyatı üçün verilən möhlət (gün). '
         'Möhlət bitəndə işçi BLOKLANMIR — sətir yalnız menecerin «İstisnalar» '
         'siyahısında görünür'),
        ('FINE_APPEAL_ESCALATION_DAYS', '3', 'INTEGER', '1', '30',
         'Cavabsız qalan cərimə etirazı neçə gündən sonra İstisna Motoruna '
         'qaldırılsın. İşçinin etiraz vermə pəncərəsi ilə qarışdırılmır — bu, '
         'HR-ın cavab müddətidir'),
        ('FINE_REVIEW_OVERDUE_DAYS', '30', 'INTEGER', '7', '180',
         'Cərimə nəşr gözləmə vəziyyətində («Aylıq Cərimə İcmalı») neçə gün qala '
         'bilər. Hədd aşılanda cərimə gecikmiş sayılır: işçi onu hələ görməyib, '
         'yəni etiraz müddəti də başlamayıb')
      ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_hr_and_retention_limits_for_new_tenant() IS
    'Yeni kirayəçiyə saxlama müddəti (SAAS-6), üz qeydiyyatı möhləti (UX-7) və '
    'iki HR gecikmə həddini (HR-1, HR-2) əlavə edir (migrations/084). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_hr_and_retention_limits ON license_tenants;
CREATE TRIGGER trg_seed_hr_and_retention_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_hr_and_retention_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Root dəyərlərdən hər hansını əl ilə dəyişmişsə DOWN onu da silir — sətir
-- yenidən yaransa dəyər defolta qayıdar, yəni siyasət seçimi İTƏR. Ona görə
-- DOWN yalnız miqrasiyanın SƏHVƏN tətbiqi halı üçündür:
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_hr_and_retention_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_hr_and_retention_limits_for_new_tenant();
--   DELETE FROM system_limits
--    WHERE limit_key IN ('EVIDENCE_UPLOAD_RETENTION_DAYS', 'FACE_ENROLLMENT_GRACE_DAYS',
--                        'FINE_APPEAL_ESCALATION_DAYS', 'FINE_REVIEW_OVERDUE_DAYS');
-- COMMIT;
-- ===========================================================================
