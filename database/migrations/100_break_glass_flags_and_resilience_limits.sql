-- ===========================================================================
-- 100 — BREAK-GLASS İCAZƏ FLAG-LƏRİ (Faza 5.4) + FAZA 5 ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 2 (flag-lər) + MƏRKƏZİ TƏLƏB #1 (Root
--         parametrləri) — hər ikisi Faza 5-in tələb etdiyi hissə.
--
-- ---------------------------------------------------------------------------
-- `can_manage_break_glass` — NİYƏ `hardlock_level=1` (YALNIZ ROOT)
-- ---------------------------------------------------------------------------
-- Bu flag ehtiyat-admin REYESTRİNİ (`break_glass_trustees`, migrations/099)
-- idarə edir, yəni «böhran anında kim Root ola bilər» sualının cavabını
-- yazır. CEO-ya verilsəydi, CEO özünü reyestrə salıb ikinci-etibarlı şəxsi
-- də özü seçə bilərdi — o an break-glass artıq «ikinci şəxs tələb edən
-- mexanizm» olmaqdan çıxıb CEO-nun daimi Root açarına çevrilərdi.
-- `can_switch_db`/`can_manage_plugins`/`can_manage_webhooks` ilə eyni səviyyə
-- və eyni kateqoriya (`ERP_INFRA`) — üçü də «sistemin özünə» toxunur.
--
-- ---------------------------------------------------------------------------
-- `can_approve_break_glass` — NİYƏ `hardlock_level=2` (ROOT VƏ CEO)
-- ---------------------------------------------------------------------------
-- Bu, İKİNCİ-ETİBARLI-ŞƏXS qapısıdır. `can_manage_break_glass`-dan FƏRQLİ
-- olaraq CEO-da OLMALIDIR: mexanizmin bütün mövcudluq səbəbi Root-un
-- ƏLÇATMAZ olmasıdır — təsdiqi yalnız Root verə bilsəydi, funksiya məhz
-- lazım olduğu anda işləməzdi.
--
-- `hardlock_level=2` isə onu Admin/HR_Admin səviyyəsinə ENDİRİLMƏKDƏN
-- qoruyur: Root/CEO onu həvalə EDƏ BİLMƏZ (səviyyə 3 olsaydı edə bilərdi).
-- Bundan əlavə TƏTBİQ QATI (`BreakGlassUseCase.approve`) təsdiqləyicinin
-- ya `can_approve_break_glass` daşıyıcısı, ya da AKTİV ehtiyat-admin
-- olmasını tələb edir — yəni iki ehtiyat-admin bir-birini təsdiqləyə bilər
-- (Root DA, CEO DA əlçatmaz olduğu ssenari), lakin heç kim ÖZÜNÜ təsdiqləyə
-- bilməz (DB-də `chk_break_glass_not_self`, tətbiqdə `approve`).
--
-- `is_anti_fraud=FALSE`: anti-fraud vəzifə ayrılığı (§5) cərimə/qayıdış
-- axınına aiddir; break-glass onlardan tamamilə ayrı bir infrastruktur
-- qapısıdır və `Mağaza_Meneceri`/`Satıcı`-ya verilməsi hardlock=2 ilə
-- ONSUZ DA mümkün deyil.
--
-- ---------------------------------------------------------------------------
-- ROOT PARAMETRLƏRİ — 11 AÇAR (MƏRKƏZİ TƏLƏB #1)
-- ---------------------------------------------------------------------------
-- Dəyərlər `DEFAULT_LIMITS` (`src/domain/policies.py`) ilə HƏRFƏN eynidir —
-- 095-in xəbərdarlığı: seed başqa dəyər yazsaydı, EYNİ quraşdırma
-- miqrasiyanın tətbiq olunub-olunmamasından asılı olaraq FƏRQLİ davranardı.
--
-- Aralıqların (`min_value`/`max_value`) əsaslandırması:
--   * `OFFLINE_BACKLOG_MAX_HOURS` 1..720 — aşağı hədd 1 saat (daha az
--     dəyər hər qısa şəbəkə kəsintisini nasazlıq elan edərdi), yuxarı hədd
--     30 gün (`LICENSE_MAX_OFFLINE_GRACE_DAYS`-in iki qatı: lisenziya
--     möhlətindən UZUN offline artıq ayrıca problemdir).
--   * `OFFLINE_BACKLOG_MAX_ENTRIES` 10..100000 — yuxarı hədd SQLite
--     buferinin praktik həcmidir, aşağı hədd isə sıfır OLMAMALIDIR: 0
--     hər ilk yazıda xəbərdarlıq deməkdir.
--   * `OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS` 1..168 — `DRIVE_QUOTA_
--     WARNING_COOLDOWN_DAYS` naxışı, saat vahidində.
--   * `HEALTH_MEMORY_*_PERCENT` 50..99.9 — disk hədlərinin (migrations/032)
--     EYNİ aralığı; 100 QƏSDƏN İCAZƏLİ DEYİL, çünki 100%-də xəbərdarlıq
--     artıq gecdir.
--   * `HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS` 1..168.
--   * `SHIFT_HANDOFF_NOTE_MAX_CHARS` 50..5000 — 50-dən aşağı bir cümlə də
--     yazmağa imkan verməzdi.
--   * `SHIFT_HANDOFF_VISIBILITY_HOURS` 1..72.
--   * `BREAK_GLASS_MAX_DURATION_MINUTES` 15..1440 — 15 dəq. real bir
--     əməliyyat üçün minimumdur; 1440 (24 saat) mütləq tavandır, çünki
--     bundan uzun «müvəqqəti» səlahiyyət artıq daimi səlahiyyətdir.
--   * `BREAK_GLASS_APPROVAL_WINDOW_MINUTES` 5..240.
--   * `BREAK_GLASS_MAX_GRANTS_PER_MONTH` 1..10 — SIFIR QƏSDƏN İCAZƏLİ
--     DEYİL: 0 mexanizmi tamamilə söndürərdi və Root bunu edə bilsəydi,
--     «Root əlçatmaz olanda işləyən yol» sükutla yox edilə bilərdi.
--     Söndürmə yolu var, lakin BAŞQADIR: reyestri boş saxlamaq.
--
-- 095-in İKİ BLOKLU naxışı (mövcud kirayəçilər + yeni kirayəçi trigger-i)
-- təkrarlanır. İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. KATALOQ SƏTİRLƏRİ
-- ---------------------------------------------------------------------------
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only)
VALUES
    ('can_manage_break_glass', 'ERP_INFRA', 'Fövqəladə giriş reyestrini idarə et',
     'Ehtiyat-adminlər reyestrini (`break_glass_trustees`, migrations/099) '
     'təyin/ləğv etmək və aktiv fövqəladə səlahiyyəti dayandırmaq. YALNIZ '
     'Root: bu flag «böhran anında kim Root ola bilər» sualının cavabını '
     'yazır.',
     1, FALSE, FALSE),
    ('can_approve_break_glass', 'ERP_INFRA', 'Fövqəladə girişi təsdiqlə',
     'Ehtiyat-adminin fövqəladə səlahiyyət sorğusunu ikinci-etibarlı şəxs '
     'kimi təsdiqləmək. Root VƏ CEO (hardlock=2): mexanizmin səbəbi Root-un '
     'əlçatmazlığıdır, ona görə təsdiq YALNIZ Root-da qala bilməz. Özünü '
     'təsdiq DB-də və tətbiqdə qadağandır.',
     2, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

DO $$
DECLARE
    v_wrong TEXT;
BEGIN
    SELECT string_agg(code, ', ')
      INTO v_wrong
      FROM permission_flags
     WHERE code IN ('can_manage_break_glass', 'can_approve_break_glass')
       AND ((code = 'can_manage_break_glass'
             AND (category <> 'ERP_INFRA' OR hardlock_level <> 1
                  OR is_anti_fraud <> FALSE OR is_camera_only <> FALSE))
         OR (code = 'can_approve_break_glass'
             AND (category <> 'ERP_INFRA' OR hardlock_level <> 2
                  OR is_anti_fraud <> FALSE OR is_camera_only <> FALSE)));

    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: bu flag(lər) ARTIQ mövcuddur, lakin '
            'atributları gözlənilənlə uyğun deyil: %', v_wrong;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. DEFOLT SAHİBLİK
-- ---------------------------------------------------------------------------
-- `can_manage_break_glass` — YALNIZ ROOT (hardlock=1 DB səviyyəsində məcbur
-- edir; `positions.tenant_id` süzgəci QOYULMUR — CLAUDE.md §8, 069 dərsi:
-- mövcud kirayəçilərin öz `ROOT` sətirləri də flag-i almalıdır).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_break_glass', TRUE
  FROM positions p
 WHERE p.code = 'ROOT'
ON CONFLICT DO NOTHING;

-- `can_approve_break_glass` — ROOT və CEO (bax fayl başlığı).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_approve_break_glass', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('OFFLINE_BACKLOG_MAX_HOURS', '24', 'INTEGER', '1', '720',
     'Offline buferdəki ən köhnə yazı bu qədər saatdan artıq gözləyirsə, '
     'HR-ə «uzun-müddətli offline» xəbərdarlığı gedir. Giriş (PIN/Face) '
     'DAYANMIR — bu, yalnız xəbərdarlıqdır'),
    ('OFFLINE_BACKLOG_MAX_ENTRIES', '500', 'INTEGER', '10', '100000',
     'Offline buferdə gözləyən yazı sayı bu həddi aşarsa HR-ə xəbərdarlıq '
     'gedir. Yaş həddindən MÜSTƏQİLDİR: az sətirlə uzun offline ilə qısa '
     'müddətdə çox sətir fərqli nasazlıqlardır'),
    ('OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS', '12', 'INTEGER', '1', '168',
     'Eyni mağaza üçün offline xəbərdarlığının təkrar göndərilməsi arasında '
     'minimum müddət — hər saat təkrarlanan bildiriş oxunmağı dayandırır'),
    ('HEALTH_MEMORY_WARNING_PERCENT', '85.0', 'DECIMAL', '50.0', '99.9',
     'Yaddaş (RAM) istifadəsinin XƏBƏRDARLIQ həddi (faiz). Disk həddi ilə '
     'eyni məntiq: 4 GB-lıq kioskda və 32 GB-lıq serverdə eyni faiz tamam '
     'fərqli qalıq deməkdir'),
    ('HEALTH_MEMORY_CRITICAL_PERCENT', '95.0', 'DECIMAL', '50.0', '99.9',
     'Yaddaş (RAM) istifadəsinin KRİTİK həddi (faiz)'),
    ('HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS', '12', 'INTEGER', '1', '168',
     'Aparat-nasazlığı bildirişinin (disk/RAM) eyni mağaza üçün təkrar '
     'göndərilməsi arasında minimum müddət'),
    ('SHIFT_HANDOFF_NOTE_MAX_CHARS', '1000', 'INTEGER', '50', '5000',
     'Şift-handoff qeydinin maksimum uzunluğu (simvol). Kiosk ekranının '
     'ölçüsü quraşdırmadan-quraşdırmaya dəyişir'),
    ('SHIFT_HANDOFF_VISIBILITY_HOURS', '12', 'INTEGER', '1', '72',
     'Handoff qeydi növbəti işçiyə neçə saat ərzində göstərilir. Bundan '
     'sonra qeyd köhnədir və göstərilmir (sətir SİLİNMİR)'),
    ('BREAK_GLASS_MAX_DURATION_MINUTES', '120', 'INTEGER', '15', '1440',
     'Fövqəladə (break-glass) səlahiyyətin maksimum yaşama müddəti '
     '(dəqiqə). 24 saatdan uzun «müvəqqəti» səlahiyyət artıq daimidir'),
    ('BREAK_GLASS_APPROVAL_WINDOW_MINUTES', '30', 'INTEGER', '5', '240',
     'İkinci-etibarlı şəxsin təsdiq verməsi üçün pəncərə (dəqiqə). '
     'Keçərsə sorğu ölür — unudulmuş sorğunun gecə təsdiqlənməsi '
     'təhlükəlidir'),
    ('BREAK_GLASS_MAX_GRANTS_PER_MONTH', '2', 'INTEGER', '1', '10',
     'Bir təqvim ayında verilə bilən fövqəladə səlahiyyət sayı. SIFIR '
     'icazəli deyil: mexanizmi söndürmək yolu reyestri boş saxlamaqdır, '
     'həddi sıfırlamaq deyil')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 4. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR (095 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_resilience_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('OFFLINE_BACKLOG_MAX_HOURS', '24', 'INTEGER', '1', '720',
         'Offline buferdəki ən köhnə yazı bu qədər saatdan artıq gözləyirsə, '
         'HR-ə «uzun-müddətli offline» xəbərdarlığı gedir. Giriş (PIN/Face) '
         'DAYANMIR — bu, yalnız xəbərdarlıqdır'),
        ('OFFLINE_BACKLOG_MAX_ENTRIES', '500', 'INTEGER', '10', '100000',
         'Offline buferdə gözləyən yazı sayı bu həddi aşarsa HR-ə xəbərdarlıq '
         'gedir. Yaş həddindən MÜSTƏQİLDİR: az sətirlə uzun offline ilə qısa '
         'müddətdə çox sətir fərqli nasazlıqlardır'),
        ('OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS', '12', 'INTEGER', '1', '168',
         'Eyni mağaza üçün offline xəbərdarlığının təkrar göndərilməsi arasında '
         'minimum müddət — hər saat təkrarlanan bildiriş oxunmağı dayandırır'),
        ('HEALTH_MEMORY_WARNING_PERCENT', '85.0', 'DECIMAL', '50.0', '99.9',
         'Yaddaş (RAM) istifadəsinin XƏBƏRDARLIQ həddi (faiz). Disk həddi ilə '
         'eyni məntiq: 4 GB-lıq kioskda və 32 GB-lıq serverdə eyni faiz tamam '
         'fərqli qalıq deməkdir'),
        ('HEALTH_MEMORY_CRITICAL_PERCENT', '95.0', 'DECIMAL', '50.0', '99.9',
         'Yaddaş (RAM) istifadəsinin KRİTİK həddi (faiz)'),
        ('HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS', '12', 'INTEGER', '1', '168',
         'Aparat-nasazlığı bildirişinin (disk/RAM) eyni mağaza üçün təkrar '
         'göndərilməsi arasında minimum müddət'),
        ('SHIFT_HANDOFF_NOTE_MAX_CHARS', '1000', 'INTEGER', '50', '5000',
         'Şift-handoff qeydinin maksimum uzunluğu (simvol). Kiosk ekranının '
         'ölçüsü quraşdırmadan-quraşdırmaya dəyişir'),
        ('SHIFT_HANDOFF_VISIBILITY_HOURS', '12', 'INTEGER', '1', '72',
         'Handoff qeydi növbəti işçiyə neçə saat ərzində göstərilir. Bundan '
         'sonra qeyd köhnədir və göstərilmir (sətir SİLİNMİR)'),
        ('BREAK_GLASS_MAX_DURATION_MINUTES', '120', 'INTEGER', '15', '1440',
         'Fövqəladə (break-glass) səlahiyyətin maksimum yaşama müddəti '
         '(dəqiqə). 24 saatdan uzun «müvəqqəti» səlahiyyət artıq daimidir'),
        ('BREAK_GLASS_APPROVAL_WINDOW_MINUTES', '30', 'INTEGER', '5', '240',
         'İkinci-etibarlı şəxsin təsdiq verməsi üçün pəncərə (dəqiqə). '
         'Keçərsə sorğu ölür — unudulmuş sorğunun gecə təsdiqlənməsi '
         'təhlükəlidir'),
        ('BREAK_GLASS_MAX_GRANTS_PER_MONTH', '2', 'INTEGER', '1', '10',
         'Bir təqvim ayında verilə bilən fövqəladə səlahiyyət sayı. SIFIR '
         'icazəli deyil: mexanizmi söndürmək yolu reyestri boş saxlamaqdır, '
         'həddi sıfırlamaq deyil')
     ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_resilience_limits_for_new_tenant() IS
    'Yeni kirayəçi yaradılanda sistem davamlılığı (v2backlog.md Faza 5) ROOT '
    'parametrlərini seedləyir (migrations/100) — 095-in eyni naxışı.';

DROP TRIGGER IF EXISTS trg_seed_resilience_limits ON license_tenants;
CREATE TRIGGER trg_seed_resilience_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_resilience_limits_for_new_tenant();

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_resilience_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_resilience_limits_for_new_tenant();
--   DELETE FROM system_limits
--    WHERE limit_key IN ('OFFLINE_BACKLOG_MAX_HOURS', 'OFFLINE_BACKLOG_MAX_ENTRIES',
--                        'OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS',
--                        'HEALTH_MEMORY_WARNING_PERCENT', 'HEALTH_MEMORY_CRITICAL_PERCENT',
--                        'HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS',
--                        'SHIFT_HANDOFF_NOTE_MAX_CHARS', 'SHIFT_HANDOFF_VISIBILITY_HOURS',
--                        'BREAK_GLASS_MAX_DURATION_MINUTES',
--                        'BREAK_GLASS_APPROVAL_WINDOW_MINUTES',
--                        'BREAK_GLASS_MAX_GRANTS_PER_MONTH');
--   -- DİQQƏT: Root-un əl ilə verdiyi əlavə sətirləri də silər (093 xəbərdarlığı).
--   DELETE FROM position_permissions
--    WHERE flag_code IN ('can_manage_break_glass', 'can_approve_break_glass');
--   DELETE FROM permission_flags
--    WHERE code IN ('can_manage_break_glass', 'can_approve_break_glass');
-- COMMIT;
-- ===========================================================================
