-- ===========================================================================
-- 108 — KAMPANİYA GÜNLƏRİNİN ÇƏKİSİ (v2backlog.md Faza 6.4-ün tamamlanması)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 6.4: "istəyə-bağlı «kampaniya tarixi» qeydi
--         (Root/CEO daxil edir), bu tarixlərdə ... tarixi-nümunə-təklifinə
--         ƏLAVƏ ÇƏKİ".
--
-- Faza 6 kampaniya dövrlərini (`campaign_periods`, migrations/089) və panel
-- widget-ini yazdı, lakin «əlavə çəki» hissəsi TƏKLİFƏ toxunmurdu: kampaniya
-- günü `staffing_pattern_suggestions`-da adi günlə BƏRABƏR sayılırdı. Bu
-- miqrasiya həmin çəkinin YERİNİ (sütun) və GÜCÜNÜ (Root parametri) yaradır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ AYRI SÜTUN, MÖVCUD ORTANIN ÜSTÜNDƏN YAZMAQ YOX
-- ---------------------------------------------------------------------------
-- `avg_historical_headcount` sütununun MƏNASI sənədləşdirilib (migrations/019
-- `COMMENT`): "həmin həftə günündə FAKTİKİ işləmiş işçilərin ortası". Çəkili
-- ortanı ora yazsaydıq, həmin cümlə yalan olardı və Root ekranda gördüyü
-- rəqəmi heç bir davamiyyət hesabatı ilə üzləşdirə bilməzdi — «4.2 nəfər»
-- yazır, hesabat isə 3.6 deyir, fərqin səbəbi isə heç yerdə görünmür.
--
-- İki sütun eyni anda iki sualı cavablandırır: "adətən neçə nəfər?" və
-- "kampaniyaya hazırlaşanda neçə nəfər?". Bu, QIRMIZI XƏTTİN də tələbidir:
-- mövcud işləyən funksiya DƏYİŞMİR, üstünə əlavə olunur.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `NULL` İCAZƏLİDİR
-- ---------------------------------------------------------------------------
-- `NULL` = "pəncərədə heç bir kampaniya günü olmayıb" — yəni çəkiləcək bir şey
-- yoxdur. `0` yazsaydıq, ekran onu "kampaniyada 0 işçi lazımdır" kimi göstərə
-- bilərdi; `avg_historical_headcount`-un nüsxəsini yazsaydıq isə, Root eyni
-- iki rəqəmi görüb "çəki işləmir" nəticəsinə gələrdi. `NULL` üçüncü, DÜZGÜN
-- mesajdır: sual bu pəncərə üçün MƏNASIZDIR.
--
-- ---------------------------------------------------------------------------
-- ÇARPANIN HÜDUDLARI (`STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER`)
-- ---------------------------------------------------------------------------
--   * Aşağı 1.0 — NEYTRAL ELEMENT, yəni "çəki söndürülüb". Ondan aşağısı
--     kampaniya gününü adi gündən AZ sayardı və parametrin mənasını tərsinə
--     çevirərdi.
--   * Yuxarı 5.0 — beş qat çəkidə TƏK bir kampaniya günü bütün 8 həftəlik
--     pəncərəni əvəz edər; "tarixi nümunə" adı o zaman yalan olardı.
-- Dəyərlər `APP_LIMIT_BOUNDS` (`src/application/root_limits.py`) ilə HƏRFƏN
-- eynidir — parite `tests/unit/test_application_root_limits.py`-dadır.
--
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7: sütun
-- qatlanır, qayda qatlanmır — burada YALNIZ sütun və seed var).
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `staffing_pattern_suggestions.campaign_adjusted_headcount`
-- ---------------------------------------------------------------------------
ALTER TABLE staffing_pattern_suggestions
    ADD COLUMN IF NOT EXISTS campaign_adjusted_headcount NUMERIC(5, 2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_staffing_campaign_adjusted_nonneg'
    ) THEN
        ALTER TABLE staffing_pattern_suggestions
            ADD CONSTRAINT chk_staffing_campaign_adjusted_nonneg
            CHECK (campaign_adjusted_headcount IS NULL
                OR campaign_adjusted_headcount >= 0);
    END IF;
END $$;

COMMENT ON COLUMN staffing_pattern_suggestions.campaign_adjusted_headcount IS
    'Faza 6.4 (v2backlog.md): kampaniya günləri `STAFFING_CAMPAIGN_WEIGHT_'
    'MULTIPLIER` çarpanı ilə ağırlaşdırılmış orta. `NULL` = pəncərədə '
    'kampaniya günü OLMAYIB (sıfır DEYİL — sual mənasızdır). '
    '`avg_historical_headcount` TOXUNULMUR: onun mənası «faktiki orta»dır və '
    'çəkili rəqəmi ora yazmaq həmin tərifi pozardı (migrations/108).';

-- ---------------------------------------------------------------------------
-- 2. MÖVCUD KİRAYƏÇİLƏR — `STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER`
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER', '1.5', 'DECIMAL', '1.0', '5.0',
     'Kampaniya günlərinin növbə təklifindəki çəkisi. 1.5 = kampaniya günü '
     'adi gündən yarım qat çox sayılır; 1.0 çəkini tamamilə söndürür. '
     'Kampaniya tarixləri «Kampaniya Dövrləri» bölməsindən daxil edilir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 3. YENİ KİRAYƏÇİLƏR (062/072/082/084/095 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_campaign_weight_limit_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER', '1.5', 'DECIMAL', '1.0', '5.0',
         'Kampaniya günlərinin növbə təklifindəki çəkisi. 1.5 = kampaniya günü '
         'adi gündən yarım qat çox sayılır; 1.0 çəkini tamamilə söndürür. '
         'Kampaniya tarixləri «Kampaniya Dövrləri» bölməsindən daxil edilir')
     ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_campaign_weight_limit_for_new_tenant() IS
    'Yeni kirayəçi yaradılanda kampaniya çəkisi parametrini seedləyir '
    '(v2backlog.md Faza 6.4, migrations/108) — 095-in eyni naxışı.';

DROP TRIGGER IF EXISTS trg_seed_campaign_weight_limit ON license_tenants;
CREATE TRIGGER trg_seed_campaign_weight_limit
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_campaign_weight_limit_for_new_tenant();

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Sütun silinsə çəkili ortalar İTİR — lakin onlar TAM TÖRƏMƏdir və növbəti
-- `recalculate_for_store()` çağırışı hamısını yenidən yazır (migrations/019
-- başlığındakı eyni əsaslandırma). Root-un dəyişdiyi ÇARPAN isə geri
-- QAYITMAZ (084/095 ilə eyni xəbərdarlıq).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_campaign_weight_limit ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_campaign_weight_limit_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key = 'STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER';
--   ALTER TABLE staffing_pattern_suggestions
--       DROP CONSTRAINT IF EXISTS chk_staffing_campaign_adjusted_nonneg;
--   ALTER TABLE staffing_pattern_suggestions
--       DROP COLUMN IF EXISTS campaign_adjusted_headcount;
-- COMMIT;
-- ===========================================================================
