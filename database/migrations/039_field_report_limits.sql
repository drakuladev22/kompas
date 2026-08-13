-- ===========================================================================
-- 039 — SAHƏ HESABATLARININ (#26+#27) ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `kompas1.md` Faza 3 — mağaza auditi (#26) və insident bildirişi
--         (#27) BACKEND-i beş konfiqurasiya dəyəri işlədir. `SystemLimitKey`
--         + `DEFAULT_LIMITS` artıq elan edilib (`src/domain/policies.py`);
--         bu miqrasiya həmin açarları `system_limits`-ə yazır ki, ROOT İdarə
--         Mərkəzi ekranında GÖRÜNSÜNLƏR.
--
--         Seed edilməyən açar "konfiqurasiya edilə bilən" görünər, faktiki
--         olaraq isə kodda oturan fallback işləyərdi — `tests/unit/
--         test_root_control_parameter_parity.py` bu boşluğu QAPIYA çevirib
--         (`migrations/036` ilə eyni əsaslandırma).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
-- MÖVCUD CƏDVƏLLƏRƏ TOXUNULMUR: nə sütun dəyişir, nə ad, nə tip.
--
-- ---------------------------------------------------------------------------
-- BU MİQRASİYA NİYƏ CƏDVƏL YARATMIR
-- ---------------------------------------------------------------------------
-- `field_report_types`, `field_report_categories`, `field_reports` və
-- `field_report_checklist_items` ARTIQ `migrations/037`-də qurulub; icazə
-- flag-ləri (`can_conduct_store_audit`, `can_report_incident`) isə `038`-də.
-- `037` başlığı ROOT parametrlərini QƏSDƏN kənarda saxlayıb: "həddlər
-- müvafiq fazaların root-control miqrasiyasında seed edilir. Buradakı
-- ədədlər yalnız ABSURD dəyəri kəsən DÖŞƏMƏDİR, siyasət deyil."
-- Bu fayl həmin vədin yerinə yetirilməsidir.
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ---------------------------------------------------------------------------
--   * AUDIT_INTERVAL_DAYS 1–365 — ALT HÜDUD 0 OLA BİLMƏZ: sıfır interval
--     "hər filial HƏMİŞƏ gecikib" deməkdir və gecəlik iş hər gün 21 filial
--     üçün xəbərdarlıq göndərərdi, yəni bildiriş kanalı təkbaşına dolardı.
--     Üst hüdud bir ildir — daha seyrək "audit siyasəti" praktikada
--     xatırlatmanın ümumiyyətlə söndürülməsidir və bunun düzgün yolu
--     Feature Toggle-dır, hədd deyil.
--   * MAX_PHOTOS 1–50 — ALT HÜDUD 1-dir, 0 DEYİL: sıfır tavan foto-sübutu
--     TAM bloklardı və `photo_required = TRUE` bəndlər ümumiyyətlə
--     cavablana bilməzdi (`FieldReportChecklistItem._apply_answer`), yəni
--     bir konfiqurasiya səhvi bütün auditi dayandırardı. Üst hüdud 50:
--     hər şəkil Drive-da bir fayldır və 5 MB-a qədərdir — 50 şəkil bir
--     hesabat üçün onsuz da 250 MB deməkdir.
--   * MIN_DETAIL_LENGTH 5–500 — ALT HÜDUD SXEMİN `CHECK`-i ilə EYNİDİR
--     (`char_length(trim(detail)) >= 5`, migrations/037): daha aşağı dəyər
--     seçilsəydi, ROOT ekranı qəbul edər, DB isə sətri rədd edərdi və
--     istifadəçi anlaşılmaz sürücü xətası görərdi. Üst hüdud 500 — daha
--     uzun MƏCBURİ mətn sahə işçisini forma doldurmaqdan çəkindirir və
--     nəticədə hesabat ümumiyyətlə yazılmır.
--   * TASK_DEADLINE_DAYS 1–30 — ALT HÜDUD 1-dir, 0 DEYİL: sıfır möhlət
--     tapşırığı YARANAN ANDA gecikmiş edərdi və eskalasiya dövrəsi dərhal
--     işə düşərdi (`TaskWorkflowUseCase.escalate_timeouts`). Üst hüdud bir
--     aydır — bloklayıcı bəndin (yanğın çıxışı, kassa intizamı) düzəlişi
--     növbəti audit dövründən sonraya qala bilməz.
--   * TASK_ASSIGNEE_ROLE — `TEXT`, hüdudsuz. Rol kodu ƏDƏD DEYİL və
--     `positions.code` üçün mərkəzi siyahı YOXDUR (kirayəçi öz rolunu
--     yarada bilər, `schema.sql` §5) — `min/max` mətn üçün mənasızdır.
--     NAMƏLUM DƏYƏR SİSTEMİ ÇÖKDÜRMÜR: `list_route_recipients` boş siyahı
--     qaytarır və tapşırıq hesabatı yazan şəxsə qalır (bax
--     `FieldReportUseCase._corrective_assignee`).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (`036` ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('FIELD_REPORT_AUDIT_INTERVAL_DAYS', '30', 'INTEGER', '1', '365',
     'Mağaza auditinin tezliyi (gün). Bu ədəd auditi BLOKLAMIR — yalnız '
     '`FIELD_REPORT_AUDIT_REMINDER` gecəlik işinin "hansı filial gözdən '
     'qaçıb?" sualına cavabıdır'),
    ('FIELD_REPORT_MAX_PHOTOS', '10', 'INTEGER', '1', '50',
     'Bir sahə hesabatına əlavə edilə bilən maksimum foto sayı. Hər şəkil '
     'Google Drive-da bir fayldır — tavansız massiv səhvən dövrəyə düşmüş '
     'yükləmə ilə kvotanı tək hesabatla yandırardı'),
    ('FIELD_REPORT_MIN_DETAIL_LENGTH', '10', 'INTEGER', '5', '500',
     'Hesabat təsvirinin və bağlanma qeydinin minimum uzunluğu (simvol). '
     'Alt hüdud sxemin CHECK-i ilə eynidir (migrations/037) — daha aşağı '
     'dəyər ekranda qəbul edilib DB-də rədd edilərdi'),
    ('FIELD_REPORT_TASK_DEADLINE_DAYS', '3', 'INTEGER', '1', '30',
     'Uğursuz BLOKLAYICI checklist bəndindən doğan düzəliş tapşırığının '
     'möhləti (gün). Mövcud Tapşırıq Mühərrikində yaranır (Struktur Qərar B)'),
    ('FIELD_REPORT_TASK_ASSIGNEE_ROLE', 'MAGAZA_MENECERI', 'TEXT', NULL, NULL,
     'Düzəliş tapşırığının təyin edildiyi rol (`positions.code`). Boş və ya '
     'naməlum dəyər sistemi çökdürmür — tapşırıq hesabatı yazan şəxsə qalır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022/023/036-dakı naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_field_report_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'FIELD_REPORT_AUDIT_INTERVAL_DAYS', '30', 'INTEGER', '1', '365',
         'Mağaza auditinin tezliyi (gün) — xatırlatma intervalı'),
        (NEW.tenant_id, 'FIELD_REPORT_MAX_PHOTOS', '10', 'INTEGER', '1', '50',
         'Bir sahə hesabatına maksimum foto sayı'),
        (NEW.tenant_id, 'FIELD_REPORT_MIN_DETAIL_LENGTH', '10', 'INTEGER', '5', '500',
         'Hesabat təsvirinin/bağlanma qeydinin minimum uzunluğu (simvol)'),
        (NEW.tenant_id, 'FIELD_REPORT_TASK_DEADLINE_DAYS', '3', 'INTEGER', '1', '30',
         'Düzəliş tapşırığının möhləti (gün)'),
        (NEW.tenant_id, 'FIELD_REPORT_TASK_ASSIGNEE_ROLE', 'MAGAZA_MENECERI', 'TEXT',
         NULL, NULL, 'Düzəliş tapşırığının təyin edildiyi rol (`positions.code`)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_field_report_limits_for_new_tenant() IS
    'Yeni kirayəçiyə sahə hesabatlarının beş ROOT parametrini əlavə edir '
    '(migrations/039). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_field_report_limits ON license_tenants;
CREATE TRIGGER trg_seed_field_report_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_field_report_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlər silinsə, sahə hesabatları İŞLƏMƏYƏ DAVAM EDİR — kod
-- `DEFAULT_LIMITS` fallback-ına düşür (30 gün / 10 şəkil / 10 simvol /
-- 3 gün / MAGAZA_MENECERI). İtən yeganə şey Root-un GUI-dan dəyişdirmə
-- imkanıdır. `migrations/037`-dəki cədvəllərə TOXUNULMUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_field_report_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_field_report_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'FIELD_REPORT_AUDIT_INTERVAL_DAYS', 'FIELD_REPORT_MAX_PHOTOS',
--       'FIELD_REPORT_MIN_DETAIL_LENGTH', 'FIELD_REPORT_TASK_DEADLINE_DAYS',
--       'FIELD_REPORT_TASK_ASSIGNEE_ROLE');
-- COMMIT;
