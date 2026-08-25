-- ===========================================================================
-- 093 — İKİ YENİ İCAZƏ FLAG-I: `can_approve_transfer_request`,
--        `can_manage_webhooks` (v2backlog.md FAZA 1 sxem işinin davamı)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Səbəb : 088 (`employee_transfer_requests`) və 091 (`webhook_endpoints`)
--         cədvəllərini yaradanda müvafiq icazə flag-ləri KATALOQA
--         ƏLAVƏ EDİLMƏMİŞDİ — `sec-v2`-nin tapıntısı (`can_manage_webhooks`
--         üçün), komanda rəhbərinin təsdiqi ilə `can_approve_transfer_
--         request` da eyni boşluqda olduğu üçün BURAYA əlavə olundu.
--
-- ---------------------------------------------------------------------------
-- `can_approve_transfer_request` — NİYƏ `can_approve_shift_swap` NAXIŞI
-- ---------------------------------------------------------------------------
-- Filiallar-arası daimi köçürmə sorğusu (`employee_transfer_requests`,
-- migrations/088) mövcud Shift Swap təsdiq-axınının struktur analoqudur
-- (bax 088 başlığı) — icazə flag-i də EYNİ kateqoriya/hardlock cütünü
-- daşıyır: `category='HR'`, `hardlock_level=0` (adi operativ flag,
-- Strict Hierarchy/Self-Escalation Guard-a tabedir, LAKİN dörd-səviyyəli
-- hardlock iyerarxiyasından KƏNARDADIR — `can_approve_shift_swap`-ın
-- özü ilə EYNİ), `is_anti_fraud=FALSE` (təsdiq əməliyyatı pul kəsintisi
-- YARATMIR, işçinin filial təyinatını dəyişir).
--
-- ---------------------------------------------------------------------------
-- `can_manage_webhooks` — NİYƏ `hardlock_level=1` (ROOT_ONLY)
-- ---------------------------------------------------------------------------
-- Səbəb `sec-v2`-nindir, komanda rəhbəri təsdiqləyib: ERP konnektorları
-- (`can_switch_db`, `can_manage_plugins` — hər ikisi hardlock=1) TANINAN,
-- vendor-nəzarətli endpoint-lərə bağlanır. Webhook isə İXTİYARİ XARİCİ
-- URL-ə (`webhook_endpoints.target_url`, migrations/091) hadisə payload-u
-- göndərir — səlahiyyətli olmayan əlin bir webhook qeydiyyatı YARATMASI
-- bütün tenant-ın hadisə axınını naməlum üçüncü tərəfə sızdıra bilər. Ona
-- görə `category='ERP_INFRA'` (`can_switch_db`/`can_manage_plugins` ilə
-- EYNİ kateqoriya — səbəb EYNİ sinif risk), `hardlock_level=1`.
--
-- ---------------------------------------------------------------------------
-- DEFOLT SAHİBLİK
-- ---------------------------------------------------------------------------
-- `can_approve_transfer_request`: ROOT, CEO, ADMIN, HR_ADMIN —
-- `can_approve_shift_swap`-ın MÖVCUD sahiblik dəstinin EYNİSİ
-- (`schema.sql` §23, ADMIN/HR_ADMIN siyahılarında həmin flag artıq var).
--
-- `can_manage_webhooks`: YALNIZ ROOT — `hardlock_level=1` DB SƏVİYYƏSİNDƏ
-- bunu MƏCBUR EDİR (`enforce_permission_hardlock()`, schema.sql §18):
-- CEO/Admin/HR_Admin-ə bu flag-i vermək cəhdi `RAISE EXCEPTION` ilə
-- BÜTÜN tranzaksiyanı geri qaytarardı — ona görə aşağıda YALNIZ ROOT üçün
-- INSERT yazılıb.
--
-- ---------------------------------------------------------------------------
-- `positions.tenant_id IS NULL` SÜZGƏCİ İŞLƏNMİR (CLAUDE.md §8, `069`/`077`
-- dərsi)
-- ---------------------------------------------------------------------------
-- TƏK sorğu ilə HƏM sistem şablonu (gələcək kirayəçilər `seed_tenant_
-- defaults()` ilə ondan kopyalayır), HƏM DƏ artıq mövcud kirayəçilərin
-- ROOT/CEO/ADMIN/HR_ADMIN sətirləri əhatə olunur — əks halda `069`-un
-- tapdığı EYNİ sinif qüsur təkrarlanardı: mövcud kirayəçilər YENİ flag-i
-- HEÇ VAXT ALMAZDI.
--
-- `schema.sql` §22/§23-Ə YAZILMIR — QƏSDLİDİR (077-nin EYNİ əsaslandırması):
-- §23-ün seed bloku BÜTÜN miqrasiyalardan ƏVVƏL, `schema.sql`-in ÖZÜNÜN
-- İÇİNDƏ icra olunur — bu miqrasiyadan sonra yaranan flag onun wildcard-ının
-- İCRA ANINDAN kənarda qalır, ona görə hər iki flag açıq şəkildə BURADA
-- verilir.
--
-- `granted_by` QƏSDƏN NULL (sütun defoltu) — sistem seed-i `enforce_
-- grantor_owns_flag()` istisnasıdır (schema.sql §18, `063`/`068`/`072`/`077`
-- ilə eyni qərar).
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- `ON CONFLICT (code) DO NOTHING` hər iki INSERT-də. Sətir artıq mövcuddursa
-- və atributları gözlənilənlə uyğun deyilsə (`UPDATE` mümkün deyil —
-- `trg_flag_attributes_immutable`, migrasiya 013) `DO $$ ... RAISE
-- EXCEPTION` ilə DAYANIR — `056`/`063`/`068`/`072`/`077` ilə EYNİ qərar.
-- Sonunda şərhli DOWN bloku var.
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
    ('can_approve_transfer_request', 'HR', 'Filial köçürmə sorğusunu təsdiqlə',
     'Filiallar-arası daimi köçürmə sorğusunu (`employee_transfer_requests`, '
     'migrations/088) təsdiq/rədd etmək — təsdiqdən sonra `employees.'
     'store_id` yenilənir. `can_approve_shift_swap`-ın struktur analoqu.',
     0, FALSE, FALSE),
    ('can_manage_webhooks', 'ERP_INFRA', 'Webhook uc nöqtələrini idarə et',
     'Ümumi genişlənmə səthinin (`webhook_endpoints`, migrations/091) '
     'qeydiyyatı/redaktəsi — ixtiyari xarici URL-ə hadisə göndərmə icazəsi. '
     'YALNIZ Root: `can_switch_db`/`can_manage_plugins` səviyyəli sızma '
     'səthi (sec-v2 qərarı).',
     1, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

DO $$
DECLARE
    v_wrong TEXT;
BEGIN
    SELECT string_agg(code, ', ')
      INTO v_wrong
      FROM permission_flags
     WHERE code IN ('can_approve_transfer_request', 'can_manage_webhooks')
       AND ((code = 'can_approve_transfer_request'
             AND (category <> 'HR' OR hardlock_level <> 0
                  OR is_anti_fraud <> FALSE OR is_camera_only <> FALSE))
         OR (code = 'can_manage_webhooks'
             AND (category <> 'ERP_INFRA' OR hardlock_level <> 1
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
-- `can_approve_transfer_request` — ROOT/CEO/ADMIN/HR_ADMIN (`can_approve_
-- shift_swap`-ın MÖVCUD dəstinin eynisi, bax fayl başlığı).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_approve_transfer_request', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN')
ON CONFLICT DO NOTHING;

-- `can_manage_webhooks` — YALNIZ ROOT (hardlock_level=1 bunu DB
-- səviyyəsində MƏCBUR EDİR, bax fayl başlığı).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_webhooks', TRUE
  FROM positions p
 WHERE p.code = 'ROOT'
ON CONFLICT DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   -- DİQQƏT: bu, Root-un ƏL İLƏ başqa rollara verdiyi əlavə sətirləri DƏ
--   -- silər (eyni fərq `077`-nin DOWN-unda sənədləşdirilib) — YALNIZ bu
--   -- miqrasiyanın verdiyi sətirləri geri almaq üçün şərt daraldılmalıdır.
--   DELETE FROM position_permissions
--    WHERE flag_code = 'can_approve_transfer_request'
--      AND position_id IN (SELECT id FROM positions WHERE code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN'));
--   DELETE FROM position_permissions
--    WHERE flag_code = 'can_manage_webhooks'
--      AND position_id IN (SELECT id FROM positions WHERE code = 'ROOT');
--   DELETE FROM permission_flags WHERE code IN ('can_approve_transfer_request', 'can_manage_webhooks');
-- COMMIT;
-- ===========================================================================
