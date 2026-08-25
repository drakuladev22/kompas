-- ===========================================================================
-- 095 — İKİ YENİ ROOT PARAMETRİNİN SEED-İ (`v2backlog.md` HR Lifecycle v2)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Səbəb : `domain` `SystemLimitKey.FORMER_EMPLOYEE_DATA_RETENTION_MONTHS`
--         (Faza 3.2) və `SystemLimitKey.EMPLOYEE_REFERRAL_BONUS_POINTS`
--         (Faza 3.5) açarlarını `policies.py`/`DEFAULT_LIMITS`-ə əlavə etdi,
--         LAKİN SQL seed-i YAZILMADI — `084`-ün TAM EYNİ qüsuru
--         (`test_root_control_parameter_parity.py`, iki test bir anda
--         qırdı: `test_every_system_limit_key_is_seeded_by_sql` VƏ
--         `test_every_seeded_limit_carries_an_azerbaijani_description`).
--
--         Seed olmadan parametr ROOT ekranında GÖRÜNÜR (`list_limits` enum
--         üzərində dövr edir), lakin dəyəri `system_limits` sətri olmadığı
--         üçün `DEFAULT_LIMITS`-dən (koddan) gəlir — Root dəyəri dəyişib
--         yadda saxlasa, `UPDATE ... WHERE limit_key = ...` heç bir sətrə
--         dəyməz: ekran dəyişikliyi qəbul etmiş kimi görünər, davranış isə
--         əvvəlki qalar (084-ün, 082-nin EYNİ təsviri).
--
-- ---------------------------------------------------------------------------
-- NİYƏ İKİSİ BİR MİQRASİYADA
-- ---------------------------------------------------------------------------
-- Hər ikisi EYNİ qüsurun (seed unudulması) VƏ EYNİ mənbənin (`v2backlog.md`
-- Faza 3, HR Lifecycle v2) nəticəsidir, heç biri digərinin davranışına
-- toxunmur — `084`-ün eyni əsaslandırması: reyestrdə bir sətir "hansı
-- buraxılışda hansı parametrlər gəldi" sualını bir SHA ilə cavablandırır.
--
-- ---------------------------------------------------------------------------
-- DEFOLT DƏYƏRLƏR UYDURULMUR — `DEFAULT_LIMITS`-DƏN GÖTÜRÜLÜB
-- ---------------------------------------------------------------------------
-- `policies.py`: 24 / 50 (`FORMER_EMPLOYEE_DATA_RETENTION_MONTHS` /
-- `EMPLOYEE_REFERRAL_BONUS_POINTS`). Seed başqa dəyər yazsaydı, EYNİ
-- parametrin iki fərqli defoltu olardı (084-ün eyni xəbərdarlığı).
--
-- ---------------------------------------------------------------------------
-- HÜDUDLAR — HƏR BİRİ AYRICA ƏSASLANDIRILIR
-- ---------------------------------------------------------------------------
--   * `FORMER_EMPLOYEE_DATA_RETENTION_MONTHS` 1..120 — `0` PII-ni işçi
--     deaktiv olduğu GÜN silərdi, hüquqi mübahisə (əmək kodeksi iddia
--     müddəti) üçün sənədi HƏLƏ LAZIM OLA BİLƏN anda itirərdi (bax
--     `employees.data_anonymized_at` şərhi, migrations/088). 120 aydan
--     (10 il) yuxarı isə retensiya siyasətinin ÖZÜNÜ mənasız uzadar —
--     "unudulma hüququ" gözlənilən son həddir.
--   * `EMPLOYEE_REFERRAL_BONUS_POINTS` 0..1000 — `0` QƏSDƏN İCAZƏLİDİR:
--     `policies.py`-in öz şərhi deyir "0 = bonus SÖNDÜRÜLÜB" (BR-002-nin
--     "gecikmə→AZN dərəcəsi defolt 0.00" ilə EYNİ söndürmə-ilə-sıfır
--     naxışı). 1000-dən yuxarı isə tövsiyə bonusunu adi satış xalı
--     miqyasından (`ATTRITION_NEW_HIRE_RISK_POINTS` 0..100 presedenti)
--     ölçüsüz böyüdərdi.
--
-- ---------------------------------------------------------------------------
-- `value_type` NİYƏ 'INTEGER'
-- ---------------------------------------------------------------------------
-- Hər ikisi TAM ƏDƏDDİR (ay sayı, xal sayı) və kod onları `_limit_int(...)`
-- ilə oxuyur (084/082-nin eyni qaydası: yazılan tip oxunan tiplə üst-üstə
-- düşməlidir).
--
-- ---------------------------------------------------------------------------
-- İKİ BLOK (MÖVCUD + YENİ KİRAYƏÇİ) — 062/072/082/084-ÜN NAXIŞI
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` TOXUNULMUR — sətir formatı iki blokda HƏRFƏN
-- eynidir.
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
    ('FORMER_EMPLOYEE_DATA_RETENTION_MONTHS', '24', 'INTEGER', '1', '120',
     'Deaktiv işçinin şəxsi sahələri (ad, telefon və s.) neçə ay sonra '
     'anonimləşdirilsin. Audit jurnalı bu həddən istisnadır — hüquqi tələb '
     'ola bilər, buradan idarə olunmur'),
    ('EMPLOYEE_REFERRAL_BONUS_POINTS', '50', 'INTEGER', '0', '1000',
     'Yeni işçini tövsiyə edən işçiyə yazılan bonus-xal sayı. Sıfır bonusu '
     'söndürür — tövsiyə sahəsi yenə doldurulur, sadəcə xal verilmir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR (062/072/082/084 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_hr_lifecycle_v2_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('FORMER_EMPLOYEE_DATA_RETENTION_MONTHS', '24', 'INTEGER', '1', '120',
         'Deaktiv işçinin şəxsi sahələri (ad, telefon və s.) neçə ay sonra '
         'anonimləşdirilsin. Audit jurnalı bu həddən istisnadır — hüquqi tələb '
         'ola bilər, buradan idarə olunmur'),
        ('EMPLOYEE_REFERRAL_BONUS_POINTS', '50', 'INTEGER', '0', '1000',
         'Yeni işçini tövsiyə edən işçiyə yazılan bonus-xal sayı. Sıfır bonusu '
         'söndürür — tövsiyə sahəsi yenə doldurulur, sadəcə xal verilmir')
     ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_hr_lifecycle_v2_limits_for_new_tenant() IS
    'Yeni kirayəçi yaradılanda HR Lifecycle v2 (v2backlog.md Faza 3.2/3.5) '
    'ROOT parametrlərini seedləyir (migrations/095) — 062/072/082/084-ün '
    'eyni naxışı.';

DROP TRIGGER IF EXISTS trg_seed_hr_lifecycle_v2_limits ON license_tenants;
CREATE TRIGGER trg_seed_hr_lifecycle_v2_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_hr_lifecycle_v2_limits_for_new_tenant();

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Silinsə Root-un YADDA SAXLADIĞI xüsusi dəyərlər İTİR, `DEFAULT_LIMITS`
-- fallback-ına qayıdılır (084 ilə eyni xəbərdarlıq).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_hr_lifecycle_v2_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_hr_lifecycle_v2_limits_for_new_tenant();
--   DELETE FROM system_limits
--    WHERE limit_key IN ('FORMER_EMPLOYEE_DATA_RETENTION_MONTHS', 'EMPLOYEE_REFERRAL_BONUS_POINTS');
-- COMMIT;
-- ===========================================================================
