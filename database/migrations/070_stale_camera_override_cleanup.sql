-- ===========================================================================
-- 070 — KEÇMİŞ VƏZİFƏ-DƏYİŞİKLİYİNDƏ TƏMİZLƏNMƏMİŞ ANTİ-FRAUD OVERRIDE-LARI
-- ===========================================================================
-- Tarix : 2026-08-19
-- Səbəb : SEC-1 audit tapıntısı (debate dövrə 1) — `Employee.change_position()`
--         (`src/domain/entities/employee.py:258`) `assert_grantable_to()`-a
--         `is_camera_type_role` parametrini ÖTÜRMÜRDÜ (defolt `False`). CUSTOM
--         kamera-tipli rola (`Position.is_camera_type=TRUE`, `Position.
--         effective_system_role` isə prioritetə görə YALNIZ ən yaxın SİSTEM
--         roluna, məs. `HR_ADMIN`, düşür) keçən işçidə əvvəlki fərdi
--         override QORUNURDU, çünki `camera_capable = is_camera_type_role or
--         role.is_camera_type` `False or False = False` hesablanırdı — halbuki
--         işçinin YENİ VƏZİFƏSİ FAKTİKİ kamera-tipli idi.
--
--         Kod düzəlişi (`is_camera_type_role=position.is_camera_type`) ARTIQ
--         tətbiq olunub. BU miqrasiya onun CÜTÜdür: düzəliş YALNIZ GƏLƏCƏK
--         vəzifə dəyişikliklərini qoruyur, keçmişdə YAZILMIŞ sətirlərə TƏSİR
--         ETMİR — CLAUDE.md §7-nin "SÜTUN yox, QAYDA dəyişirsə" prinsipinin
--         analoqudur, sadəcə sütun/trigger yerinə SƏTİR səviyyəsindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ DB TRİGGERİ BUNU ARTIQ TUTMUR (VƏ TUTA DA BİLMƏZDİ)
-- ---------------------------------------------------------------------------
-- `enforce_anti_fraud_segregation()` (schema.sql §18) `user_permission_
-- overrides` budağında `positions.is_camera_type`-i BİRBAŞA oxuyur — domendəki
-- prioritet→rol dolayı yolu ORADA YOXDUR, DB qapısı bu mənada onsuz da
-- DÜZGÜNDÜR. LAKİN trigger `BEFORE INSERT OR UPDATE`-dir: sətir bir dəfə
-- (köhnə, düzgün vəziyyətdə) YAZILIB sonra HEÇ TOXUNULMADAN qalıbsa, heç bir
-- trigger onu geriyə-doğru yenidən yoxlamır — `positions` cədvəlində də
-- `is_camera_type`-i geriyə-doğru YAYAN trigger YOXDUR (yalnız `trg_positions_
-- updated`, `updated_at` üçün). Deməli bu, sxem/trigger qüsuru DEYİL,
-- YALNIZ mövcud sətirlərin təmizlənməsi məsələsidir — `schema.sql` bu
-- miqrasiya ilə DƏYİŞMİR.
--
-- ---------------------------------------------------------------------------
-- HANSI İKİ FLAG ƏHATƏ OLUNUR — VƏ NİYƏ MƏHZ BUNLAR
-- ---------------------------------------------------------------------------
-- `assert_grantable_to()`-da `camera_capable`-dan asılı olan YALNIZ ÜÇ şərt
-- var (authorization.py:253-273):
--
--   1. `excludes_camera_role AND camera_capable`            → RƏDD edilməli
--   2. `is_camera_only AND NOT camera_capable`               → RƏDD edilməli
--   3. `code == DUAL_CONTROL_APPROVAL_FLAG AND camera_capable` → RƏDD edilməli
--
-- Bu bug `camera_capable`-i SƏHVƏN `False` hesablayır (əvəzinə `True` olmalı
-- idi) — yəni YALNIZ 1 və 3-cü şərtlər SİLİNMƏLİ override-u YAZDIRMIŞ (aşağı
-- salınmamış) ola bilər. 2-ci şərt ƏKS İSTİQAMƏTDƏDİR: `not camera_capable`
-- bu bug ilə DAHA ASAN `True` olur, yəni override YERSİZ YERƏ SİLİNƏ bilərdi
-- (funksionallıq itkisi), amma TƏHLÜKƏLİ sətir SAXLANMAZ — bu istiqamətdə
-- "stale təhlükəli override" yaranmır.
--
--   * Şərt 3-ə uyğun flag: `can_approve_dual_control_override`
--     (`DUAL_CONTROL_APPROVAL_FLAG`, authorization.py:291) — SEC-1-in ƏSAS
--     tapıntısı.
--   * Şərt 1-ə uyğun flag: `excludes_camera_role=TRUE` YALNIZ
--     `can_publish_fines`-dədir (schema.sql:2462, `UPDATE permission_flags
--     SET excludes_camera_role = TRUE WHERE code = 'can_publish_fines'` —
--     kataloqda BAŞQA heç bir sətir bu bayrağı daşımır, yoxlanılıb). Eyni
--     səbəbdən AŞKAR EDİLMƏLİDİR: kamera-tipli rol onsuz da `can_issue_fines`
--     (is_camera_only=TRUE, "cərimə YARADAN") daşıya bilər — əgər üstəlik
--     `can_publish_fines`-i (cərimə TƏSDİQ EDƏN) də saxlasaydı, YARADAN və
--     TƏSDİQ EDƏN eyni şəxs olardı, yəni məhz `excludes_camera_role`-un
--     qorumaq istədiyi vəzifə ayrılığı pozulardı.
--
--   * Şərt 2-yə (yəni `is_camera_only=TRUE`) uyğun flag-lər — `can_verify_
--     returns`, `can_override_return_time`, `can_issue_fines` — BU MİQRASİYAYA
--     DAXİL EDİLMİR: yuxarıda izah edildiyi kimi bu bug onları həddindən
--     artıq SİLİRDİ, yox saxlamırdı; yəni "geri qaytarılacaq təhlükəli sətir"
--     bu üç flag üçün MÖVCUD DEYİL.
--
-- `position_permissions` (rol-səviyyəli DEFOLT-lar) BU MİQRASİYAYA daxil
-- edilmir: `Position.is_camera_type` YALNIZ `create_role`-da təyin olunur
-- (`position_management.py`) və heç bir "rolu redaktə et" yolu onu sonradan
-- DƏYİŞMİR (yoxlanılıb — `position_management.py`-da `is_camera_type`-i
-- dəyişən metod yoxdur), üstəlik `Position.grant()` (position.py:104-106)
-- `is_camera_type_role=self.is_camera_type`-i onsuz da DÜZGÜN ötürür. Yəni
-- bu bug-un rol-defolt tərəfində ekvivalenti YOXDUR.
--
-- ---------------------------------------------------------------------------
-- NİYƏ SİLİRİK (DENY YAZMIRIQ)
-- ---------------------------------------------------------------------------
-- `EmployeeRepository._sync_overrides()` (`repositories.py:531-540`) tətbiqin
-- ÖZÜ override-u götürəndə `DELETE FROM user_permission_overrides` işlədir —
-- yəni "override YOXDUR" vəziyyəti bu cədvəldə sətrin ÖZÜNÜN olmaması ilə
-- ifadə olunur, ayrıca `DENY` sətri ilə YOX. Bu miqrasiya EYNİ mexanizmi
-- işlədir: nəticə `change_position()` düzgün işləsəydi VERƏCƏYİ nəticə ilə
-- HƏRFƏN eynidir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `audit_logs`-A YAZILMIR
-- ---------------------------------------------------------------------------
-- `audit_logs.actor_id` `NOT NULL REFERENCES employees(id)`-dir (bax
-- `scripts/create_root_account.py` başlığı) — bir SQL miqrasiyasının
-- attribute edə biləcəyi "aktor işçi" YOXDUR və uydurma/sistem ID icad etmək
-- audit jurnalının həqiqiliyini poza bilər. Bunun əvəzinə reyestr
-- (`kompasos.schema_migrations`, miqrasiya 061) BU faylın nə vaxt, kim
-- tərəfindən tətbiq olunduğunu qeyd edir — "kim, nə vaxt" sualının cavabı
-- ORADADIR.
--
-- ---------------------------------------------------------------------------
-- OPERATOR TƏSİRİ NECƏ GÖRÜR — VƏ MƏLUM MƏHDUDİYYƏT
-- ---------------------------------------------------------------------------
-- Aşağıdakı `DO $$ ... RAISE NOTICE ... $$` bloku HƏR silinən sətir üçün
-- ayrıca xəbərdarlıq, sonda isə CƏMİ sayı yazır. YAZILDIĞI ANDA (bu
-- miqrasiya) `scripts/apply_migrations.py`-ın psycopg bağlantısında
-- `add_notice_handler` QURULMAMIŞDI — yəni `NOTICE`-lər icraçı vasitəsilə
-- operatorun konsoluna ÇATMIRDI (psycopg3 defolt olaraq handler-siz
-- `NOTICE`-i sükutla atır, empirik yoxlanıldı). BU BOŞLUQ EYNİ DƏYİŞİKLİK
-- DƏSTİNDƏ (INFRA-5, `apply_migrations.py::_print_notice`) BAĞLANIB — icraçı
-- İNDİ `conn.add_notice_handler(_print_notice)` qurur, yəni bu miqrasiyanın
-- `NOTICE`-ləri normal tətbiqdə operatora ARTIQ ÇATIR. Aşağıdakı sorğu
-- YENƏ DƏ faydalıdır — NOTICE yalnız GÖRÜNÜRLÜKDÜR, bu SORĞU isə DB-nin ÖZ
-- vəziyyətini birbaşa yoxlayır — operator tətbiqdən ƏVVƏL və SONRA əl ilə
-- (ayrıca, bu faylın İÇİNDƏ DEYİL) işlədə bilər:
--
--     SELECT count(*) FROM kompasos.user_permission_overrides upo
--       JOIN kompasos.employees e ON e.id = upo.user_id
--       JOIN kompasos.positions p ON p.id = e.position_id
--      WHERE upo.effect = 'GRANT'
--        AND upo.flag_code IN ('can_approve_dual_control_override', 'can_publish_fines')
--        AND p.is_camera_type = TRUE;
--
-- Tətbiqdən SONRA bu sorğu 0 qaytarmalıdır.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- Sadə `DELETE ... WHERE ...`dir: ikinci icrada şərtə uyğun sətir artıq
-- qalmadığından heç nə silinmir (0 sətir) — əlavə `IF EXISTS`/`ON CONFLICT`
-- lazım deyil, DELETE öz təbiətinə görə idempotentdir.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

DO $$
DECLARE
    v_row   RECORD;
    v_count INTEGER := 0;
BEGIN
    FOR v_row IN
        DELETE FROM user_permission_overrides upo
        USING employees e, positions p
        WHERE upo.user_id = e.id
          AND e.position_id = p.id
          AND upo.effect = 'GRANT'
          AND upo.flag_code IN ('can_approve_dual_control_override', 'can_publish_fines')
          AND p.is_camera_type = TRUE
        RETURNING upo.flag_code, e.tenant_id, e.id AS employee_id, p.code AS position_code
    LOOP
        v_count := v_count + 1;
        RAISE NOTICE
            'MİQRASİYA 070: təmizləndi — kirayəçi=%, işçi=%, vəzifə=%, flag=%',
            v_row.tenant_id, v_row.employee_id, v_row.position_code, v_row.flag_code;
    END LOOP;

    RAISE NOTICE 'MİQRASİYA 070: CƏMİ % sətir təmizləndi (SEC-1 stale override).', v_count;
END
$$;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Silinən sətirlər bu fayldan bərpa OLUNA BİLMƏZ: DELETE hansı konkret
-- `granted_by`/`created_at`/`expires_at`/`reason` dəyərləri ilə yazıldığını
-- SAXLAMIR (məqsəd elə budur — TƏHLÜKƏLİ sətirdir). Əgər silinmə YANLIŞ
-- olduğu (yəni işçinin vəzifəsi əslində kamera-tipli DEYİLDİ) ortaya
-- çıxarsa, bərpa yalnız İCAZƏ VERƏN ŞƏXSİN yeni, TARİXLİ qərarı ilə —
-- normal tətbiq axını (`PermissionHierarchyGuardUseCase`) üzərindən —
-- edilməlidir, köhnə sətrin eyni ilə geri yazılması ilə YOX, çünki bu,
-- `granted_by`-ın YENİDƏN öz flag-inə sahib olduğunu yoxlamadan keçərdi.
--
-- BEGIN;
-- -- Qəsdən boş — bax yuxarı izah.
-- COMMIT;
