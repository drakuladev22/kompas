-- ===========================================================================
-- 038 — İCAZƏ KATALOQUNA 6 YENİ FLAG (kompas1.md Faza 2)
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `migrations/037` #26-30 + HR-D-nin SAXLAMA qatını qurdu
--         (`field_reports`, `annual_leave_balances`, `bulk_import_log`,
--         `store_templates`, `executive_digest_config`,
--         `export_manual_corrections`), lakin heç biri `permission_flags`
--         kataloquna toxunmadı — ekranlar hələ yoxdur (Faza 3-8), amma
--         "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipi flag-in kataloqda
--         ƏVVƏLCƏDƏN mövcud olmasını tələb edir.
--
-- ---------------------------------------------------------------------------
-- QIRMIZI XƏTT — YENİ GUARD YAZILMIR
-- ---------------------------------------------------------------------------
-- `enforce_anti_fraud_segregation()`, `enforce_permission_hardlock()`,
-- `enforce_self_escalation_guard()`, `enforce_grantor_owns_flag()` (schema.sql
-- §18) artıq `permission_flags.hardlock_level` / `is_anti_fraud` /
-- `is_camera_only` sütunlarını OXUYARAQ işləyir — yeni sətir əlavə etmək
-- kifayətdir (domen tərəfdə eyni: `PermissionFlag.assert_grantable_to`,
-- `src/domain/value_objects/authorization.py`). Bu miqrasiya YALNIZ `021`-dən
-- FƏRQLİ olaraq İKİ flag-ə SIFIRDAN FƏRQLİ hardlock səviyyəsi verir
-- (aşağıya bax) — bu da MÖVCUD `HardlockLevel.allows()` məntiqinin
-- parametrləşdirilməsidir, yeni kod DEYİL.
--
-- ---------------------------------------------------------------------------
-- TƏLƏ 1 — NİYƏ HEÇ BİR FLAG `hardlock_level = 1` (ROOT_ONLY) ALMIR
-- ---------------------------------------------------------------------------
-- `schema.sql` §23-dəki CEO defolt bloku `AND pf.hardlock_level <> 1` şərti
-- ilə işləyir — səviyyə 1 CEO-nu SÜKUTLA kənarlaşdırır (`can_manage_license`,
-- `can_switch_db`, `can_manage_plugins`, `can_manage_permissions`,
-- `can_manage_system_limits` məhz buna görə YALNIZ Root-dadır). `kompas1.md`
-- Faza 2 cədvəlində "Root/CEO" defoltu olan YEGANƏ flag `can_configure_
-- executive_digest`-dir (#30) və CEO defoltu AÇIQ TƏLƏB OLUNUR — ona görə
-- səviyyə 1 DEYİL, səviyyə 2 (`ROOT_CEO`, `role IN ('ROOT','CEO')`) seçildi:
-- bu, "YALNIZ Root/CEO" tələbini "Root" defoltunu pozmadan STRUKTUR şəkildə
-- (fərdi override ilə belə HR_Admin-ə verilə bilməz) zəmanətləndirir.
--
-- `can_perform_bulk_operations` (#29) "YALNIZ Root/CEO/Admin — yüksək-
-- təsirli əməliyyat" tələb edir. Səviyyə 1 (YALNIZ Root) BURADA DA səhv
-- olardı — Admin-i (və CEO-nu) kənarlaşdırardı. Səviyyə 2 (`ROOT_CEO`) də
-- səhvdir — Admin-i kənarlaşdırardı, spesifikasiya isə Admin-i AÇIQ daxil
-- edir. Ona görə səviyyə 3 (`DELEGABLE`, `priority <= ADMIN`) seçildi:
-- `RolePriority.ADMIN = 1` olduğu üçün YALNIZ Root(0)/CEO(0)/Admin(1) bu
-- şərti ötür, HR_Admin/Mağaza_Meneceri/Kamera_Nəzarətçisi (OPERATIONAL=2) və
-- Satıcı (STAFF=3) STRUKTUR SƏVİYYƏSİNDƏ əbədi kənarda qalır — "YALNIZ"
-- sözü bununla defolt-təyinatdan kənara çıxıb HARDLOCK-a çevrilir (analoji:
-- `can_control_user_permissions` da səviyyə 3-dür, schema.sql §22).
--
-- Qalan dörd flag (`can_conduct_store_audit`, `can_report_incident`,
-- `can_manage_leave_balances`, `can_manage_export_corrections`) HR_Admin
-- (OPERATIONAL, priority=2) və ya BÜTÜN rolları (Satıcı, STAFF=3) defolt
-- sahib kimi tələb edir — səviyyə 2 və ya 3 istənilən halda bu rolları
-- STRUKTUR şəkildə kənarlaşdırardı (`ROOT_CEO`/`DELEGABLE` heç vaxt
-- OPERATIONAL/STAFF-a icazə vermir, `HardlockLevel.allows()`). Ona görə
-- dördü də `hardlock_level = 0` (NONE) — "kimə verilə biləcəyi" sualını
-- TAMAMİLƏ Strict Hierarchy Guard + defolt təyinat həll edir.
--
-- ---------------------------------------------------------------------------
-- TƏLƏ 2 — NİYƏ ALTISI DA `is_camera_only = FALSE`
-- ---------------------------------------------------------------------------
-- `schema.sql` §23-dəki Root defolt bloku `AND NOT pf.is_camera_only` şərti
-- ilə işləyir — `is_camera_only = TRUE` olsaydı Root ÖZÜ bu flag-ləri ala
-- BİLMƏZDİ (kamera-əməliyyat flag-ləri Root-a QƏSDƏN verilmir, vəzifə
-- ayrılığı: Root konfiqurasiya edir, gündəlik kamera əməliyyatı aparmır).
-- Bu altı flag-in heç biri kamera-əməliyyatı DEYİL (mağaza auditi, insident
-- bildirişi, məzuniyyət balansı, toplu əməliyyat, export düzəlişi, icra
-- xülasəsi) — `is_camera_only = FALSE` DÜZGÜNDÜR və eyni zamanda MƏCBURİDİR:
-- `PermissionFlag.__post_init__` `is_camera_only=TRUE`-nu YALNIZ
-- `is_anti_fraud=TRUE` olanda qəbul edir (SEC-001-in dar alt-çoxluğu), altısı
-- da anti-fraud DEYİL (aşağı bax), ona görə əks halda domen səviyyəsində
-- `ValueError` atılardı.
--
-- ---------------------------------------------------------------------------
-- TƏLƏ 3 — `can_report_incident` "BÜTÜN ROLLAR" DEFOLTU
-- ---------------------------------------------------------------------------
-- `kompas1.md` Faza 2: "defolt: bütün rollar — hər kəs insident bildirə
-- bilməlidir, YALNIZ HƏLLİ məhduddur". Bu, kataloqda ADƏTDƏN KƏNARDIR: `021`
-- daxil bütün əvvəlki flag-lər ya Root/CEO-ya, ya da bir-iki əməliyyat
-- roluna verilir. Kamera Nəzarətçisi VƏ Satıcı bu flag-i AÇIQ ALIR (aşağıda
-- "3. DEFOLT SAHİBLİK — BÜTÜN ROLLAR" bölməsi) — bu, SEC-001-i POZMUR:
-- SEC-001 yalnız `can_approve_dual_control_override`-ın (dual-control
-- TƏSDİQİ) kamera roluna verilməsini qadağan edir, insident BİLDİRMƏYƏ heç
-- bir aidiyyəti yoxdur. Əksinə, nəzarətçinin gördüyü şübhəli hadisəni bildirə
-- bilməsi TƏHLÜKƏSİZLİK QAZANCIDIR (görüntüdə anomaliya aşkarlayan
-- nəzarətçinin əlində "bunu bildirim" düyməsi olmaması boşluqdur).
-- HƏLL etmək (status → RESOLVED/DISMISSED, `resolved_by`) isə bu flag-in
-- ÖHDƏSİNDƏ DEYİL — o, ayrıca marşrutlama qaydası ilə (`field_report_
-- categories.route_to_role`, migrations/037) müəyyən rola göndərilir və
-- HƏLLETMƏ üçün Faza 3-də AYRI bir yoxlama (məs. `can_assign_tasks`/mövcud
-- rol-uyğunluğu) tələb olunacaq — bu miqrasiya YALNIZ BİLDİRMƏ hüququnu açır.
--
-- ---------------------------------------------------------------------------
-- KATEQORİYA SEÇİMİ — NİYƏ HAMISI 'HR' (021 ilə eyni qərar)
-- ---------------------------------------------------------------------------
-- Altısı da işçi/mağaza əməliyyatlarının genişlənməsidir (mağaza auditi,
-- insident, məzuniyyət balansı, toplu əməliyyat, export düzəlişi, icra
-- xülasəsi) — mövcud `HR` kateqoriyasında artıq `can_manage_employees`,
-- `can_view_employee_reports` kimi analoji flag-lər var və `021` da eyni altı
-- fərqli funksiyanı `HR`-ə yazıb. Yeni kateqoriya yaratmaq MƏCBURİ DEYİL.
--
-- ---------------------------------------------------------------------------
-- ANTİ-FRAUD YOXLAMASI (hər altı flag üçün)
-- ---------------------------------------------------------------------------
-- 1. Mağaza_Meneceri/Satıcı vəzifə ayrılığı: heç biri CLAUDE.md §5-dəki dörd
--    hardcoded flag-dən (`can_verify_returns`, `can_override_return_time`,
--    `can_issue_fines`, `can_approve_dual_control_override`) DEYİL, ona görə
--    `is_anti_fraud = FALSE` düzgündür.
-- 2. SEC-001: heç biri `can_approve_dual_control_override` DEYİL, kamera-tipli
--    rol bu altısını NƏZƏRİ olaraq ala bilər (məs. Root manual override
--    versə) — bu, `can_export_reports` kimi mövcud qeyri-anti-fraud
--    flag-lərlə EYNİ davranışdır.
-- 3. Self-Escalation Guard (`enforce_self_escalation_guard`,
--    `PermissionHierarchyGuardUseCase._assert_actor_owns_flag`) HEÇ BİR
--    dəyişiklik olmadan tətbiq olunur — aktor bu altı flag-dən istənilən
--    birini YALNIZ ÖZÜNDƏ varsa başqasına verə bilir.
-- 4. Strict Hierarchy Guard eyni cür — bərabər və yuxarı pilləyə toxunmaq
--    bloklanır. `can_perform_bulk_operations`/`can_configure_executive_
--    digest` ƏLAVƏ OLARAQ hardlock ilə (səviyyə 3/2) qorunur — bax Tələ 1.
-- Narahatlıq doğuran tək məqam: `can_conduct_store_audit`-in Mağaza
-- Meneceri-yə DEFOLT VERİLMƏMƏSİ (aşağı bax, bölmə "seçim") ŞÜURLU seçimdir,
-- guard dəyişikliyi DEYİL.
--
-- ---------------------------------------------------------------------------
-- `can_conduct_store_audit` (#26) DEFOLT SEÇİMİ — "seç və əsaslandır"
-- ---------------------------------------------------------------------------
-- `kompas1.md` Faza 2 cədvəlində bu flag üçün konkret rol yazılmayıb.
-- Seçim: Admin + HR_Admin (Root/CEO invariantına əlavə olaraq) — Mağaza
-- Meneceri BİLƏRƏKDƏN kənarda qalır. Səbəb: audit balı Benchmark Dashboard-a
-- (Struktur Qərar C) düşür və uğursuz BLOKLAYICI bənd mağaza rəhbərinə qarşı
-- Tapşırıq Mühərrikində düzəliş-tapşırığı yaradır (Struktur Qərar B) — öz
-- mağazasını özü auditə çəkən menecerin balı sistemli maraq ziddiyyəti
-- daşıyır (eyni məntiq `can_conduct_performance_review`-un öz-özünü
-- qiymətləndirmə qadağasında da var, `chk_review_not_self`, migrations/020).
-- Bu, HARDLOCK DEYİL (səviyyə 0 qalır) — Root/CEO istəsə fərdi override ilə
-- konkret bir menecerə verə bilər (məs. kiçik tək-mağaza kirayəçidə HQ
-- auditoru yoxdursa) — yalnız DEFOLT paylanma bunu açmır.
--
-- ---------------------------------------------------------------------------
-- DEFOLT SAHİBLİK — ROOT VƏ CEO NİYƏ AYRICA YAZILIB
-- ---------------------------------------------------------------------------
-- `schema.sql` §23: "Root: bütün flag-lər, MİNUS kamera-əməliyyat flag-ləri"
-- və "CEO: Root-un hər şeyi, MİNUS səviyyə-1 hardlock" — BİR DƏFƏLİK sorğu
-- (tətbiq olunan andakı CROSS JOIN), sonradan əlavə olunan flag avtomatik
-- ötürülmür. Ona görə bu miqrasiya Root/CEO-ya altısını da AÇIQ verir.
--
-- ---------------------------------------------------------------------------
-- RETROAKTİV ƏHATƏ — NİYƏ `tenant_id IS NULL` ŞƏRTİ YOXDUR
-- ---------------------------------------------------------------------------
-- `021`-lə EYNİ səbəb: `schema.sql` §23 yalnız SİSTEM ŞABLONU üzərində işləyir
-- (ilk quraşdırma), bu miqrasiya isə ARTIQ MÖVCUD tenant-ların da eyni flag-ə
-- malik olmasını təmin etməlidir. `WHERE p.code = '...'` şərti TENANT
-- FİLTRSİZDİR — həm şablon sətrini, həm mövcud tenant-ların sətirlərini əhatə
-- edir.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. YENİ FLAG-LƏR — KATALOQA ƏLAVƏ (mövcud flag-lərdən HEÇ BİRİ TOXUNULMUR)
-- ---------------------------------------------------------------------------
-- `ON CONFLICT (code) DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir)
-- mövcud sətir ÜSTÜNDƏN YAZILMIR — Root artıq `name_az`/`description_az`-ı
-- redaktə etmiş ola bilər (`017`/`018`/`021` ilə eyni qərar).
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level, is_anti_fraud, is_camera_only)
VALUES
    ('can_conduct_store_audit', 'HR',
        'Mağaza auditi apar',
        '#26 — strukturlaşdırılmış checklist üzrə mağaza ziyarəti/auditi '
        '(`field_reports`, `field_report_checklist_items`, migrations/037). '
        'Uğursuz bloklayıcı bənd mövcud Tapşırıq Mühərrikində avtomatik '
        'düzəliş-tapşırığı yaradır (Struktur Qərar B).',
        0, FALSE, FALSE),
    ('can_report_incident', 'HR',
        'İnsident bildir',
        '#27 — oğurluq/qəza/avadanlıq/şikayət kimi hadisələri bildirmək '
        '(`field_reports`, migrations/037). Defolt BÜTÜN rollara verilir: '
        'hər kəs insident bildirə bilməlidir — YALNIZ HƏLLİ (bağlanma qərarı) '
        'məhduddur, bildirmə deyil (kompas1.md Faza 2).',
        0, FALSE, FALSE),
    ('can_manage_leave_balances', 'HR',
        'İllik məzuniyyət balansını idarə et',
        '#28 — işçinin illik məzuniyyət haqqı/istifadəsi (`annual_leave_'
        'balances`) və sorğularının (`annual_leave_requests`) təsdiqi '
        '(migrations/037). Mövcud GÜNDAXİLİ icazə sistemi (`leave_requests`) '
        'ilə QARIŞDIRILMASIN — ayrı flag, ayrı konsept.',
        0, FALSE, FALSE),
    ('can_perform_bulk_operations', 'HR',
        'Toplu əməliyyat apar',
        '#29 — CSV-əsaslı toplu işçi idxalı və mağaza-şablon köçürməsi '
        '(`bulk_import_log`, `store_templates`, migrations/037). Yüksək-'
        'təsirli əməliyyat: DELEGABLE hardlock (səviyyə 3) ilə strukturca '
        'YALNIZ Root/CEO/Admin-ə məhdudlaşdırılıb — HR_Admin/Mağaza Meneceri '
        'fərdi override ilə belə ala bilməz.',
        3, FALSE, FALSE),
    ('can_manage_export_corrections', 'HR',
        'Export düzəlişini idarə et',
        'HR-yaxşılaşdırması D — export-öncəsi konkret gün/işçi sətrinə manual '
        'düzəliş (`export_manual_corrections`, migrations/037). Səbəb-sahəsi '
        'məcburi, tam audit-lənir.',
        0, FALSE, FALSE),
    ('can_configure_executive_digest', 'HR',
        'İcra xülasəsini konfiqurasiya et',
        '#30 — planlaşdırılmış gündəlik/həftəlik icra xülasəsinin tezliyi və '
        'daxil olan metriklərin ayarları (`executive_digest_config`, '
        'migrations/037). ROOT_CEO hardlock (səviyyə 2) ilə strukturca '
        'YALNIZ Root/CEO-ya məhdudlaşdırılıb.',
        2, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. DEFOLT SAHİBLİK — ROOT VƏ CEO (mövcud "hər şeyi görür" invariantı)
-- ---------------------------------------------------------------------------
-- `granted_by` QƏSDƏN yazılmır (NULL qalır) — `enforce_grantor_owns_flag()`-ın
-- "sistem seed-i" istisnası (schema.sql §18) məhz bu haldır: seed anında
-- flag-i "verən" real bir işçi yoxdur. Hardlock trigger-i bu sətirlərə də
-- tətbiq olunur (defense-in-depth) — səviyyə 2/3 olan iki flag Root/CEO-nu
-- QƏBUL EDİR (Tələ 1-in məhz təmin etdiyi şey).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_conduct_store_audit', 'can_report_incident',
        'can_manage_leave_balances', 'can_perform_bulk_operations',
        'can_manage_export_corrections', 'can_configure_executive_digest'
     ]) AS f(flag_code)
WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. DEFOLT SAHİBLİK — BÜTÜN ROLLAR (`can_report_incident`, Tələ 3)
-- ---------------------------------------------------------------------------
-- YEDDİ sistem rolunun HAMISI — Kamera Nəzarətçisi VƏ Satıcı DAXİL. Bu,
-- `021`-in "Kamera Nəzarətçisi/Satıcı heç nə almır" qaydasından bilərəkdən
-- kənara çıxır, çünki `kompas1.md` bu flag üçün AÇIQ "bütün rollar" tələb
-- edir (bax fayl başlığı, Tələ 3). SEC-001-i POZMUR: bax yuxarıdakı izah.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_report_incident', TRUE
FROM positions p
WHERE p.code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN',
                  'MAGAZA_MENECERI', 'KAMERA_NEZARETCISI', 'SATICI')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. DEFOLT SAHİBLİK — ADMIN
-- ---------------------------------------------------------------------------
-- `can_perform_bulk_operations`: spesifikasiyanın "YALNIZ Root/CEO/Admin"
-- tələbinin Admin tərəfi (DELEGABLE hardlock buna görə seçildi, Tələ 1).
-- `can_manage_leave_balances`: "HR_Admin/Admin" defoltunun Admin tərəfi.
-- `can_conduct_store_audit`: yuxarıdakı "seç və əsaslandır" qərarı.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_perform_bulk_operations', 'can_manage_leave_balances',
        'can_conduct_store_audit'
     ]) AS f(flag_code)
WHERE p.code = 'ADMIN'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. DEFOLT SAHİBLİK — HR_ADMIN
-- ---------------------------------------------------------------------------
-- `can_manage_leave_balances`: "HR_Admin/Admin" defoltunun HR_Admin tərəfi.
-- `can_manage_export_corrections`: spesifikasiyada YEGANƏ sahib HR_Admin-dir
-- (Admin BURADA YOXDUR — kompas1.md cədvəli Admin-i sadalamır).
-- `can_conduct_store_audit`: yuxarıdakı "seç və əsaslandır" qərarı.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_manage_leave_balances', 'can_manage_export_corrections',
        'can_conduct_store_audit'
     ]) AS f(flag_code)
WHERE p.code = 'HR_ADMIN'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. Mağaza Meneceri, Kamera Nəzarətçisi, Satıcı
-- ---------------------------------------------------------------------------
-- Bu üç rol üçün BURADA əlavə sətir YAZILMIR — onların yeganə yeni flag-i
-- `can_report_incident`-dir və o, artıq yuxarıdakı bölmə 3-də ("BÜTÜN
-- ROLLAR") verilib. Digər beş flag-dən heç biri bu üç rola defolt VERİLMİR
-- (`can_perform_bulk_operations`/`can_configure_executive_digest` üçün bu,
-- hardlock ilə STRUKTUR ZƏMANƏTDİR də; qalan üçü üçün isə sadəcə defolt
-- paylanma qərarıdır — Root/CEO fərdi override ilə istənilən vaxt aça bilər).

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: `position_permissions` sətirlərinin silinməsi hazırda bu flag-lərə
-- güvənən HEÇ bir ekran YOXDUR (Faza 3-8 hələ qurulmayıb), ona görə geri
-- qaytarma TARİXİ sübut itkisi yaratmır — sadəcə kataloq qeydini silir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DELETE FROM position_permissions WHERE flag_code IN (
--       'can_conduct_store_audit', 'can_report_incident',
--       'can_manage_leave_balances', 'can_perform_bulk_operations',
--       'can_manage_export_corrections', 'can_configure_executive_digest'
--   );
--   DELETE FROM permission_flags WHERE code IN (
--       'can_conduct_store_audit', 'can_report_incident',
--       'can_manage_leave_balances', 'can_perform_bulk_operations',
--       'can_manage_export_corrections', 'can_configure_executive_digest'
--   );
-- COMMIT;
