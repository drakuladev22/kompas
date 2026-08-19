-- ===========================================================================
-- 072 — SEC-5: SESSİYA MÜDDƏTİ PARAMETRLƏRİ + `can_revoke_sessions` FLAG-I
-- ===========================================================================
-- Tarix : 2026-08-19
-- Səbəb : SEC-5 audit tapıntısı (dövrə debatı) — `auth_sessions` (SEC-011)
--         faktiki yazılıb-oxunmağa başladı (`PostgresAuthSessionRepository`,
--         `SessionManagementUseCase`), amma İKİ şey hələ bazada YOX idi:
--
--           1. `schema.sql` §17b-nin vəd etdiyi ÜÇ ROOT parametri
--              (`SystemLimitKey` + `DEFAULT_LIMITS`-də ARTIQ elan olunub,
--              `policies.py:936-949`) — `system_limits`-ə SEED edilməyib,
--              yəni Root İdarə Mərkəzində GÖRÜNMÜRDÜ (migrations/022-nin
--              həll etdiyi eyni boşluq, indi SEC-011 üçün).
--           2. Admin uzaqdan sessiya ləğvi üçün AYRICA icazə flag-i
--              (`can_revoke_sessions`) — SEC-011 "admin uzaqdan ləğv edə
--              bilir" deyir, amma flag mövcud deyildi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ İKİSİ EYNİ FAYLDADIR
-- ---------------------------------------------------------------------------
-- İkisi də EYNİ SEC-5 rollout-unun hissəsidir və EYNİ "mövcud + yeni
-- kirayəçi" naxışını (069/022 presedenti) təkrarlayır — ayrı fayllara
-- bölmək iki demək olar eyni miqrasiyanı ikiqat saxlamaq olardı.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `can_revoke_sessions` AYRI FLAG-DIR, `can_reset_password`-A ƏLAVƏ
-- SƏLAHİYYƏT DEYİL
-- ---------------------------------------------------------------------------
-- `can_reset_pin`/`can_reset_password`-un AYRI saxlanması presedentdir:
-- ikisi də "kimliyi sıfırlama"dır, amma layihə oxşar-lakin-fərqli-riskli
-- əməliyyatları BİRLƏŞDİRMİR. Sessiya ləğvi ilə şifrə sıfırlama arasındakı
-- risk fərqi PIN/şifrə fərqindən DAHA BÖYÜKDÜR: şifrə sıfırlayan hesaba TAM
-- giriş əldə edir (kimlik oğurluğu), sessiya ləğv edən isə YALNIZ məcburi
-- yenidən-girişə səbəb olur. "Şübhəli sessiyanı bağla" səlahiyyəti verəndə
-- işçiyə MƏCBURİ tam şifrə-sıfırlama səlahiyyəti də verilməsi §5-in "ən az
-- imtiyaz" prinsipinin TƏRSİ olardı.
--
-- ---------------------------------------------------------------------------
-- DEFOLT ROL GRANTI — `can_reset_password` İLƏ EYNİ (QƏRAR DƏYİŞDİ, SƏBƏBİ)
-- ---------------------------------------------------------------------------
-- İlk versiyada bu flag heç bir rola avtomatik verilmirdi — o qərar
-- "`can_reset_password`-un da hardcode defolt rolu yoxdur" fərziyyəsinə
-- əsaslanırdı. Yoxlanılanda ÇIXDI Kİ, bu, YANLIŞ idi: `schema.sql`-də
-- `can_reset_password` `ADMIN`-in defolt flag siyahısındadır (bax "Admin:
-- operativ idarəetmə" INSERT bloku, `unnest(ARRAY[... 'can_reset_password'
-- ...])` WHERE p.code = 'ADMIN'). Yanlış fərziyyə düzəldikdən sonra qərar
-- da dəyişdi: `can_revoke_sessions` İNDİ ADMIN-ə DEFOLT VERİLİR.
--
-- SƏBƏB: defolt qrant olmasa, TƏMİZ quraşdırmada HEÇ KİM sessiya ləğv edə
-- bilməz — Root əl ilə flag verənə qədər. `profile.py`-dakı "Digər
-- sessiyaları bağla" düyməsi heç kimə işləməz və SEC-011-in "admin uzaqdan
-- ləğv edə bilir" vədi YENƏ YERİNƏ YETİRİLMƏMİŞ qalar — dövrə debatının
-- kəşf etdiyi "fantom implementasiya" sinfinin (`auth_sessions`,
-- `saga_instances`, `security_events`, `monthly_fine_review_batches`,
-- FOCUS-1) altıncı nümunəsi olardı. `can_revoke_sessions`
-- `can_reset_password`-dan CİDDİ ŞƏKİLDƏ AZ təhlükəlidir (məcburi
-- yenidən-giriş vs hesabın TAM ələ keçirilməsi) — ADMIN-ə güclüsünü verib
-- zəifini verməmək məntiqsiz olardı.
--
-- AYRICA FLAG QƏRARI DƏYİŞMİR: defolt qrant AYRI flag olmaqla ZİDDİYYƏT
-- TƏŞKİL ETMİR — flag ayrı olduğu üçün Root onu ADMIN-dən ALIB başqa rola
-- (məs. HR_Admin) verə, ya da ADMIN-dən GERİ ala bilər. Birləşdirilmiş
-- (`can_reset_password`-un bir hissəsi) olsaydı bu sərbəstlik mümkün
-- olmazdı — bax yuxarıdakı "AYRI FLAG-DIR" bölməsi.
--
-- ---------------------------------------------------------------------------
-- MİN/MAX HÜDUDLARI (SEC-011-in mənasını qorumaq üçün)
-- ---------------------------------------------------------------------------
--   * ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES (5–240, defolt 30): alt hədd
--     0-ı (dərhal bitmə) VƏ 1-2 dəqiqə kimi praktik istifadəsiz dəyərləri
--     kəsir; üst hədd (240 dəq. = 4 saat) hərəkətsizlik pəncərəsini mütləq
--     tavanın (8 saat defolt) yarısında saxlayır — əks halda "hərəkətsizlik"
--     anlayışı mənasını itirər və faktiki YEGANƏ hədd mütləq tavan olardı.
--   * ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS (1–24, defolt 8): 1 saatdan
--     az tez-tez məcburi yenidən-girişlə istifadəsiz olar; 24 saatdan çox
--     isə "mütləq tavan" faktiki tavan olmaqdan çıxar (bir təqvim günündən
--     uzun açıq sessiya SEC-011-in qorumaq istədiyi RİSKİN ÖZÜDÜR).
--   * CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS (4–24, defolt 12): alt
--     hədd yarım-növbədən qısa dəyərləri kəsir (mənasız tez-tez yenidən-PIN);
--     üst hədd 24 saatdır — SEC-5-in kəşf etdiyi ORİJİNAL problem MƏHZ
--     "gecə növbəsinə qalan sessiya ertəsi günə keçir" idi, 24 saatdan çoxu
--     bu riski BİRBAŞA YENİDƏN AÇARDI.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- Bütün bölmələr `ON CONFLICT DO NOTHING` ilə. Sonunda şərhli DOWN bloku var.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1a. SESSİYA MÜDDƏTLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES', '30', 'INTEGER', '5', '240',
     'Admin panelində hərəkətsizlik pəncərəsi (dəqiqə) — bu müddət sonunda '
     'sessiya bağlanır, əməliyyat davam etsə pəncərə uzanır (SEC-011)'),
    ('ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS', '8', 'INTEGER', '1', '24',
     'Admin panel sessiyasının MÜTLƏQ tavanı (saat) — hərəkətsizlik '
     'pəncərəsi uzansa da bu vaxtdan sonra sessiya bağlanır (SEC-011)'),
    ('CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS', '12', 'INTEGER', '4', '24',
     'Kamera Dashboard sessiyasının MÜTLƏQ tavanı (saat, bir növbə) — '
     'hərəkətsizlik yoxlaması yoxdur, YALNIZ bu tavan (SEC-011)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 1b. SESSİYA MÜDDƏTLƏRİ — YENİ KİRAYƏÇİLƏR (022-nin naxışı)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_session_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES', '30', 'INTEGER', '5', '240',
         'Admin panelində hərəkətsizlik pəncərəsi (dəqiqə) (SEC-011)'),
        (NEW.tenant_id, 'ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS', '8', 'INTEGER', '1', '24',
         'Admin panel sessiyasının MÜTLƏQ tavanı (saat) (SEC-011)'),
        (NEW.tenant_id, 'CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS', '12', 'INTEGER', '4', '24',
         'Kamera Dashboard sessiyasının MÜTLƏQ tavanı (saat, bir növbə) (SEC-011)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_session_limits_for_new_tenant() IS
    'Yeni kirayəçiyə SEC-011 sessiya müddəti parametrlərini əlavə edir '
    '(migrations/072). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_session_limits ON license_tenants;
CREATE TRIGGER trg_seed_session_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_session_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- 2. `can_revoke_sessions` FLAG-I (KATALOQ SƏTRİ)
-- ---------------------------------------------------------------------------
-- `permission_flags` TENANT-A GÖRƏ BÖLÜNMÜR (qlobal kataloqdur, `positions`-a
-- istinad YOXDUR) — "mövcud/yeni kirayəçi" ayrımı bura AİD DEYİL, bu sətir
-- YALNIZ BİR DƏFƏ yazılır. Tenant-a görə bölünən hissə (KİM bu flag-ə
-- SAHİBDİR) aşağıda, 3-cü bölmədədir.
--
-- `hardlock_level=0`, `is_anti_fraud=FALSE`, `is_camera_only=FALSE` —
-- `can_reset_password` İLƏ HƏRFƏN EYNİ (bax fayl başlığı, tapşırılan naxış).
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only)
VALUES
    ('can_revoke_sessions', 'HR', 'Sessiyaları uzaqdan ləğv et',
     'Başqa istifadəçinin açıq admin/kamera sessiyasını məcburi bağlamaq '
     '(SEC-011) — şifrəni SIFIRLAMIR, YALNIZ yenidən-girişə məcbur edir',
     0, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- Sətir əvvəldən mövcuddursa və atributları gözlənilənlə uyğun deyilsə
-- `UPDATE` mümkün deyil (`trg_flag_attributes_immutable`, migrasiya 013) —
-- 056/063/068 ilə EYNİ qərar: sükutla davam etmək flag-i ZƏİF vəziyyətdə
-- qoyardı.
DO $$
DECLARE
    v_wrong TEXT;
BEGIN
    SELECT string_agg(code, ', ')
      INTO v_wrong
      FROM permission_flags
     WHERE code = 'can_revoke_sessions' AND hardlock_level <> 0;

    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: can_revoke_sessions ARTIQ mövcuddur, lakin '
            'hardlock səviyyəsi gözlənilənlə (0) uyğun deyil: %', v_wrong;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. DEFOLT SAHİBLİK — YALNIZ `ADMIN`, `can_reset_password` İLƏ EYNİ
-- ---------------------------------------------------------------------------
-- `positions.tenant_id IS NULL` süzgəci İŞLƏNMİR — VƏ bu, TƏK sorğu ilə HƏM
-- sistem şablonunu (gələcək kirayəçilər `seed_tenant_defaults()` vasitəsilə
-- ONDAN kopyalayır), HƏM DƏ artıq mövcud kirayəçilərin `ADMIN` sətirlərini
-- əhatə edir — `069`-un `can_view_internal_requests` naxışı ilə HƏRFƏN
-- eynidir (bax onun şərhi: "TENANT FİLTRSİZDİR ... həm sistem şablonu, həm
-- də artıq mövcud kirayəçilərin rol sətirləri əhatə olunur"). `granted_by`
-- QƏSDƏN NULL (sütun defoltu) — sistem seed-i `enforce_grantor_owns_flag()`
-- istisnasıdır (schema.sql §18, 063/068 ilə eyni qərar).
--
-- `schema.sql`-in ÖZÜNDƏKİ ADMIN defolt siyahısı (§22, "Admin: operativ
-- idarəetmə" bloku) QƏSDƏN DƏYİŞDİRİLMİR — bu, CLAUDE.md §7-nin "qayda
-- dəyişirsə hər iki yer" tələbinin İSTİSNASIDIR, pozuntusu DEYİL:
-- `position_permissions.flag_code` `permission_flags(code)`-ə FK daşıyır
-- (schema.sql:341) və `schema.sql`-in ADMIN bloku HƏMİN FAYLIN İÇİNDƏ,
-- BÜTÜN miqrasiyalardan ƏVVƏL icra olunur. `can_revoke_sessions`
-- `permission_flags`-ə YALNIZ bu miqrasiya (072) ilə düşür — sıra tərs
-- olsaydı (`schema.sql`-in ADMIN bloku bu kodu əvvəlcədən çağırsaydı) təmiz
-- quraşdırma FK POZUNTUSU ilə DAYANARDI. Eyni səbəbdən `can_publish_fines`
-- ADMIN blokunda görünür (o, `permission_flags`-ə HƏMİN FAYLDA, sətir 2420-də,
-- BLOKDAN ƏVVƏL yazılıb), `can_manage_devices`/CHAT-1 üç flag-i İSƏ
-- GÖRÜNMÜR — onlar da MİQRASİYA-daxili (063/068) öz ayrıca qrant sorğusunu
-- yazıb, `schema.sql`-ə TOXUNMAYIB (bax 068 §5 "DEFAULT SAHİBLİK"). Bu
-- miqrasiya HƏMİN presedenti təkrarlayır.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_revoke_sessions', TRUE
  FROM positions p
 WHERE p.code = 'ADMIN'
ON CONFLICT DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_session_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_session_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES',
--       'ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS',
--       'CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS');
--   -- DİQQƏT: bu, Root-un ƏL İLƏ başqa rollara verdiyi əlavə sətirləri DƏ
--   -- silər (eyni fərq `069`-un DOWN-unda sənədləşdirilib) — YALNIZ bu
--   -- miqrasiyanın verdiyi ADMIN sətrini geri almaq üçün şərt daraldılmalıdır.
--   DELETE FROM position_permissions
--    WHERE flag_code = 'can_revoke_sessions'
--      AND position_id IN (SELECT id FROM positions WHERE code = 'ADMIN');
--   DELETE FROM permission_flags WHERE code = 'can_revoke_sessions';
-- COMMIT;
