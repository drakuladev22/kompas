-- ===========================================================================
-- 103 — İKİ-NƏFƏRLİK FIRILDAQÇILIQ AŞKARLAMASI (v2backlog.md Faza 7)
--       MƏNBƏ + LİMİT
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 7 — iki işçinin davranış-nümunələri arasında
--         Root-un korrelyasiya-həddini aşan uyğunluq.
--
-- ---------------------------------------------------------------------------
-- 1. `BEHAVIOR_PAIR` İSTİSNA MƏNBƏYİ
-- ---------------------------------------------------------------------------
-- Qayda (`PairBehaviorCorrelationRule`) tapıntını `exceptions.source` ilə
-- yazır, sütun isə `exception_sources`-a FOREIGN KEY-dir — kataloqda sətir
-- yoxdursa motor yazını SÜKUTLA atır və qayda TƏSİRSİZ qalır (migrations/087
-- başlığındakı «seed olmadan qayda təsirsizdir» dərsi; 102 eyni qaydanın
-- ikinci tətbiqidir).
--
-- CİDDİYYƏT = HIGH və bu, SPESİFİKASİYA TƏLƏBİDİR: «HR_Admin-ə bildiriş».
-- Motor bildirişi yalnız `severity >= EXCEPTION_NOTIFY_MIN_SEVERITY`
-- (defolt HIGH) olan istisnalara göndərir — ciddiyyət MEDIUM seed olunsaydı,
-- tapıntı jurnalda görünərdi, amma spesifikasiyanın açıq sözü olan bildiriş
-- SÜKUTLA işləməzdi. Yalan-pozitiv riski (eyni avtobusda gedən həmkarlar)
-- isə həddin özü ilə idarə olunur (aşağıdakı açarlar), ciddiyyəti
-- alçaqaltmaqla deyil.
--
-- ---------------------------------------------------------------------------
-- 2. ÜÇ ROOT AÇARI
-- ---------------------------------------------------------------------------
-- * BEHAVIOR_PAIR_CORRELATION_THRESHOLD (spesifikasiyanın **ROOT PARAMETRİ**):
--   ortaq iş günlərinin neçə faizində girişlər SYNC_MINUTES içində üst-üstə
--   düşürsə, cüt tapıntı olur. Defolt 90% — «həmişə» sözünün ölçüsü: 10
--   ortaq günün 9-u. Daha alçaq hədd adi həmkarları da araşdırmaya göndərərdi.
--   Aralıq 50..100: 50 — «yarısı sinxrondur» artıq normal iş ritmidir;
--   100 — praktiki olaraq yalnız mükəmməl sinxron cütlər.
-- * BEHAVIOR_PAIR_MIN_SHARED_DAYS: minimum nümunə sayı (defolt 10). Az
--   ortaq gündən «cütlük» elan etmək yanlış ittihamdır — BehaviorAnomalyRule-
--   un min-sample qaydasının analoqu (migrations/018 şərhi). Aralıq 3..60.
-- * BEHAVIOR_PAIR_SYNC_MINUTES: «birlikdə giriş» pəncərəsi (defolt 5 dəq).
--   İki insanın lift/kassa növbəsində 5 dəqiqliklə üst-üstə düşməsi
--   təsadüfüdür; 30 dəqiqəlik pəncərə isə artıq «eyni növbə»ni deyil,
--   «eyni yarım-saat»ı ölçərdi. Aralıq 1..120.
--
-- Seed 095/100/102-un İKİ BLOKLU naxışı (mövcud kirayəçilər + yeni kirayəçi
-- trigger-i). Dəyərlər `DEFAULT_LIMITS` ilə HƏRFƏN eynidir.
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. İSTİSNA MƏNBƏYİ
-- ---------------------------------------------------------------------------
INSERT INTO exception_sources (code, tenant_id, name_az, description_az, default_severity)
VALUES ('BEHAVIOR_PAIR', NULL, 'Davranış-cüt korrelyasiyası',
    'İki işçinin davranış-nümunələri Root-un korrelyasiya-həddini aşır '
    '(v2backlog.md Faza 7): son N gündə ortaq iş günlərinin böyük payında '
    'girişlərini bir-neçə dəqiqədən qısaca üst-üstə salırlar («həmişə eyni '
    'növbədə», «qayıbın örtülməsi»). Qayda AVTOMATİK HEÇ NƏ ETMİR: eyni '
    'avtobusda gedən iki həmkar da bu həddi keçə bilər — qərar HR '
    'araşdırmasıdır.',
    'HIGH')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT AÇARLARI — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('BEHAVIOR_PAIR_CORRELATION_THRESHOLD', '90', 'INTEGER', '50', '100',
     'Ortaq iş günlərinin bu faizində iki işçinin girişləri sinxron pəncərədə '
     'üst-üstə düşərsə, «davranış-cüt» istisnası yazılır (korrelyasiya-həddi, '
     'v2backlog.md Faza 7)'),
    ('BEHAVIOR_PAIR_MIN_SHARED_DAYS', '10', 'INTEGER', '3', '60',
     'Davranış-cüt tapıntısı üçün iki işçinin EYNİ mağazada işlədiyi minimum '
     'gün sayı — az nümunədən «cütlük» çıxarılmır'),
    ('BEHAVIOR_PAIR_SYNC_MINUTES', '5', 'INTEGER', '1', '120',
     'İki giriş anının arasındaki maksimum fərq ki, onlar «birlikdə giriş» '
     'sayılsın')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 3. ROOT AÇARLARI — YENİ KİRAYƏÇİLƏR (095/100/102 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_behavior_pair_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('BEHAVIOR_PAIR_CORRELATION_THRESHOLD', '90', 'INTEGER', '50', '100',
         'Ortaq iş günlərinin bu faizində iki işçinin girişləri sinxron pəncərədə '
         'üst-üstə düşərsə, «davranış-cüt» istisnası yazılır (korrelyasiya-həddi, '
         'v2backlog.md Faza 7)'),
        ('BEHAVIOR_PAIR_MIN_SHARED_DAYS', '10', 'INTEGER', '3', '60',
         'Davranış-cüt tapıntısı üçün iki işçinin EYNİ mağazada işlədiyi minimum '
         'gün sayı — az nümunədən «cütlük» çıxarılmır'),
        ('BEHAVIOR_PAIR_SYNC_MINUTES', '5', 'INTEGER', '1', '120',
         'İki giriş anının arasındaki maksimum fərq ki, onlar «birlikdə giriş» '
         'sayılsın')
     ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_behavior_pair_limits_for_new_tenant() IS
    'Yeni kirayəçi yaradılanda davranış-cüt (v2backlog.md Faza 7) ROOT '
    'parametrlərini seedləyir (migrations/103) — 102-nin eyni naxışı.';

DROP TRIGGER IF EXISTS trg_seed_behavior_pair_limits ON license_tenants;
CREATE TRIGGER trg_seed_behavior_pair_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_behavior_pair_limits_for_new_tenant();

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_behavior_pair_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_behavior_pair_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'BEHAVIOR_PAIR_CORRELATION_THRESHOLD',
--       'BEHAVIOR_PAIR_MIN_SHARED_DAYS',
--       'BEHAVIOR_PAIR_SYNC_MINUTES');
--   DELETE FROM exception_sources WHERE code = 'BEHAVIOR_PAIR';
-- COMMIT;
-- ===========================================================================
