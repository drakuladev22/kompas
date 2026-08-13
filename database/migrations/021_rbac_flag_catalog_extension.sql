-- ===========================================================================
-- 021 — İCAZƏ KATALOQUNA 6 YENİ FLAG (FAZA 2, kompasos11.md)
-- ===========================================================================
-- Tarix : 2026-08-11
-- Səbəb : Faza 1 (miqrasiya 018–020) altı yeni funksiyanın SAXLAMA qatını
--         qurdu (#7, #9, #17, #19, #20, #21), lakin heç biri `permission_flags`
--         kataloquna toxunmadı — ekranlar hələ yoxdur (Faza 4–9A), amma
--         "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipi flag-in kataloqda ƏVVƏLCƏDƏN
--         mövcud olmasını tələb edir, əks halda ekran gələndə flag-i haradan
--         götürəcəyi məlum olmayacaqdı.
--
-- ---------------------------------------------------------------------------
-- QIRMIZI XƏTT — YENİ GUARD YAZILMIR
-- ---------------------------------------------------------------------------
-- Bu miqrasiya heç bir trigger/funksiya YARATMIR və ya DƏYİŞDİRMİR.
-- `enforce_anti_fraud_segregation()`, `enforce_permission_hardlock()`,
-- `enforce_self_escalation_guard()`, `enforce_grantor_owns_flag()` (schema.sql
-- §18) artıq `permission_flags.hardlock_level` / `is_anti_fraud` /
-- `is_camera_only` / `excludes_camera_role` sütunlarını OXUYARAQ işləyir —
-- yəni YENİ sətir əlavə etmək kifayətdir, bu dörd funksiya onu AVTOMATİK
-- əhatə edir (domen tərəfində eyni şey: `PermissionFlag.assert_grantable_to`,
-- bax `src/domain/value_objects/authorization.py`). Altısı da:
--   * `is_anti_fraud = FALSE`      — heç biri CLAUDE.md §5-dəki dörd anti-fraud
--     flag-inin (`can_verify_returns`, `can_override_return_time`,
--     `can_issue_fines`, `can_approve_dual_control_override`) siyahısında
--     DEYİL, ona görə `Mağaza_Meneceri`/`Satıcı` qadağası bunlara TƏTBİQ
--     OLUNMUR — `can_conduct_performance_review`-un Mağaza Menecerinə defolt
--     verilməsi MƏHZ buna görə mümkündür (kompasos11.md #20).
--   * `is_camera_only = FALSE`     — kamera-tipli rol bunları defolt ALMIR
--     (aşağıdakı seed-də Kamera_Nəzarətçisi-yə heç bir sətir yazılmır), lakin
--     SEC-001-in ÖZÜ yalnız `can_approve_dual_control_override`-a aiddir —
--     bu altısından heç biri o flag DEYİL.
--   * `hardlock_level = 0`         — Strict Hierarchy Guard/Self-Escalation
--     Guard normal "rol-defolt + fərdi override" axını ilə işləyir; xüsusi
--     hardlock səviyyəsi tələb olunmur, çünki heç biri Root-un inhisarında
--     olan konfiqurasiya səlahiyyəti (icazə/limit idarəetməsi) deyil.
--
-- ---------------------------------------------------------------------------
-- KATEQORİYA SEÇİMİ — NİYƏ HAMISI 'HR'
-- ---------------------------------------------------------------------------
-- Altısı da işçi/kadr idarəetməsinin genişlənməsidir (POS səlahiyyət qeydi,
-- istisna nəzarəti, elan, performans, turnover riski, sənədlər) — mövcud
-- `HR` kateqoriyasında artıq `can_manage_employees`, `can_view_employee_reports`
-- kimi analoji flag-lər var. Yeni kateqoriya yaratmaq MƏCBURİ DEYİL
-- (kompasos11.md Faza 2) və `KAMERA_CERIME` kimi digər kateqoriyalar semantik
-- uyğun gəlmir (o, kamera-əməliyyat/cərimə anti-fraud qatıdır, bunlar isə deyil).
--
-- ---------------------------------------------------------------------------
-- DEFOLT SAHİBLİK — ROOT/CEO NİYƏ AYRICA YAZILIB (spesifikasiya cədvəlində YOX)
-- ---------------------------------------------------------------------------
-- `schema.sql` §23-dəki qayda: "Root: bütün flag-lər, MİNUS kamera-əməliyyat
-- flag-ləri" və "CEO: Root-un hər şeyi, MİNUS səviyyə-1 hardlock". Bu, BİR
-- DƏFƏLİK sorğu idi (schema.sql tətbiq olunan andakı `permission_flags`
-- üzərində CROSS JOIN) — sonradan əlavə olunan flag avtomatik ötürülmür.
-- Ona görə bu miqrasiya Root/CEO-ya altısını da AÇIQ verir ki, mövcud
-- invariant ("Root/CEO hər şeyi görür, əməliyyat rolları isə yalnız öz
-- iş sahəsini") qırılmasın. kompasos11.md-dəki "Defolt sahib" sütunu bunu
-- TƏKRAR sadalamır, çünki Root/CEO-nun "hər şeyə sahib olması" onsuz da
-- strukturun bir hissəsidir (schema.sql §23 şərhi).
--
-- ---------------------------------------------------------------------------
-- RETROAKTİV ƏHATƏ — NİYƏ `tenant_id IS NULL` ŞƏRTİ YOXDUR
-- ---------------------------------------------------------------------------
-- `schema.sql` §23 yalnız SİSTEM ŞABLONU (`positions.tenant_id IS NULL`)
-- üzərində işləyir, çünki o, İLK quraşdırmadır və `seed_tenant_defaults()`
-- şablonu hər YENİ tenant üçün kopyalayır. Bu miqrasiya isə ARTIQ MÖVCUD
-- tenant-ların da eyni flag-ə malik olmasını təmin etməlidir (əks halda DEV
-- tenant-ın Root-u bu altı flag-i GÖRMƏZDİ). Ona görə aşağıdakı sorğularda
-- `WHERE p.code = '...'` şərti TENANT FİLTRSİZDİR — bu, HƏM şablon sətrini
-- (gələcək tenant-lar üçün), HƏM DƏ mövcud tenant-ların sətirlərini eyni anda
-- əhatə edir (`018`/`020`-dəki cədvəl-yaratma miqrasiyalarından fərqli olaraq,
-- burada YENİ sətir deyil, MÖVCUD kataloqa YENİ sətir əlavə olunur).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. YENİ FLAG-LƏR — KATALOQA ƏLAVƏ (mövcud 36 flag TOXUNULMUR)
-- ---------------------------------------------------------------------------
-- `ON CONFLICT (code) DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir)
-- mövcud sətir ÜSTÜNDƏN YAZILMIR. `schema.sql` §22-dəki bulk seed
-- `DO UPDATE` işlədir, çünki o, TƏK BAŞINA quraşdırmada HƏR icrada eyni 36
-- sətri "təzələyir" (Root hələ heç nəyi redaktə etməyib). Bu miqrasiya isə
-- ARTIQ İŞLƏYƏN sistemə tətbiq olunur — Root bu flag-lərin `name_az`/
-- `description_az`-ını sonradan redaktə etmiş ola bilər (permission_matrix.py
-- bu sütunları oxu-modelinə ötürür, bax migrations/017 başlığı) və miqrasiya
-- onu geri qaytarmamalıdır (`017`/`018`-dəki eyni qərar).
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level, is_anti_fraud, is_camera_only)
VALUES
    ('can_manage_pos_thresholds', 'HR',
        'POS səlahiyyət həddini idarə et',
        '#7 — işçi üçün endirim/ləğv/geri-qaytarma səlahiyyət qeydini təyin '
        'etmək. YALNIZ sənədləşdirmə: 1C-yə bağlantı yoxdur, avtomatik yoxlama '
        'aparılmır (kompasos11.md struktur qərarı A).',
        0, FALSE, FALSE),
    ('can_view_exceptions', 'HR',
        'İstisnalara bax',
        '#9 — "İstisnalar" ekranı: Davranış Anomaliyası və gələcək mənbələrdən '
        'gələn tapıntılara baxış (Vahid İstisna Motoru, Faza 3/5).',
        0, FALSE, FALSE),
    ('can_broadcast_announcements', 'HR',
        'Elan yayımla',
        '#19 — bütün mağazalara və ya seçilmiş mağaza siyahısına (STORE_LIST) '
        'elan göndərmək.',
        0, FALSE, FALSE),
    ('can_conduct_performance_review', 'HR',
        'Performans qiymətləndirməsi apar',
        '#20 — işçi üçün dövri performans qiymətləndirməsi yaratmaq/yeniləmək. '
        'Öz-özünü qiymətləndirmə DB səviyyəsində bloklanır '
        '(`chk_review_not_self`, migrations/020); yuxarı pilləni qiymətləndirmə '
        'isə Strict Hierarchy Guard vasitəsilə Faza 8 use case-ində bloklanacaq.',
        0, FALSE, FALSE),
    ('can_view_attrition_risk', 'HR',
        'İşdən çıxma riskinə bax',
        '#21 — işçi üzrə hesablanmış işdən çıxma riski balına və izahedici '
        'amillərinə (`factors_json`) baxış. Həssas HR datası — defolt heç bir '
        'operativ rola verilmir, yalnız HR_Admin/CEO.',
        0, FALSE, FALSE),
    ('can_manage_employee_documents', 'HR',
        'İşçi sənədlərini idarə et',
        '#17 — işçi sənəd/müqavilə qeydlərini yaratmaq, bitmə tarixini izləmək. '
        'Fayl özü mövcud Google Drive kanalındadır (migrations/002).',
        0, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. DEFOLT SAHİBLİK — ROOT VƏ CEO (mövcud "hər şeyi görür" invariantı)
-- ---------------------------------------------------------------------------
-- `granted_by` QƏSDƏN yazılmır (NULL qalır) — `enforce_grantor_owns_flag()`-ın
-- "sistem seed-i" istisnası (schema.sql §18, "istisna 2") məhz bu haldır:
-- seed anında flag-i "verən" real bir işçi yoxdur.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_manage_pos_thresholds', 'can_view_exceptions',
        'can_broadcast_announcements', 'can_conduct_performance_review',
        'can_view_attrition_risk', 'can_manage_employee_documents'
     ]) AS f(flag_code)
WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. DEFOLT SAHİBLİK — ƏMƏLİYYAT ROLLARI (kompasos11.md Faza 2 cədvəli)
-- ---------------------------------------------------------------------------
-- `can_view_exceptions` və `can_manage_employee_documents` BURADA YOXDUR —
-- kompasos11.md defolt sahib sütununda "—" işarələnib, yəni heç bir operativ
-- rol defolt ALMIR. Root/CEO Permission Matrisindən İSTƏNİLƏN operativ rola
-- əl ilə həvalə edə bilər (hardlock_level = 0, DELEGABLE-dən də azaddır).

-- Admin: "HR/Admin" defolt sahibliyinin Admin tərəfi (yalnız #7).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_pos_thresholds', TRUE
FROM positions p
WHERE p.code = 'ADMIN'
ON CONFLICT DO NOTHING;

-- HR_Admin: dörd flag-də "HR_Admin" sahib kimi sadalanıb (#7, #19, #20, #21).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_manage_pos_thresholds', 'can_broadcast_announcements',
        'can_conduct_performance_review', 'can_view_attrition_risk'
     ]) AS f(flag_code)
WHERE p.code = 'HR_ADMIN'
ON CONFLICT DO NOTHING;

-- Mağaza Meneceri: YALNIZ #20 (öz tabeliyindəkini qiymətləndirir — Strict
-- Hierarchy Guard yuxarı pilləni, `chk_review_not_self` isə özünü qiymət-
-- ləndirməni bloklayır, bax yuxarı §18 şərhi).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_conduct_performance_review', TRUE
FROM positions p
WHERE p.code = 'MAGAZA_MENECERI'
ON CONFLICT DO NOTHING;

-- Kamera Nəzarətçisi VƏ Satıcı: heç bir sətir yazılmır (spesifikasiyada
-- ikisi də sahib kimi sadalanmayıb — mövcud "Kamera Nəzarətçisi YALNIZ
-- kamera-əməliyyat flag-ləri alır" / "Satıcı heç bir idarəetmə flag-i
-- daşımır" qaydası pozulmur, bax schema.sql §23).

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: `position_permissions` sətirlərinin silinməsi hazırda bu flag-lərə
-- güvənən HEÇ bir ekran YOXDUR (Faza 4–9A hələ qurulmayıb), ona görə geri
-- qaytarma TARİXİ sübut itkisi yaratmır — sadəcə kataloq qeydini silir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DELETE FROM position_permissions WHERE flag_code IN (
--       'can_manage_pos_thresholds', 'can_view_exceptions',
--       'can_broadcast_announcements', 'can_conduct_performance_review',
--       'can_view_attrition_risk', 'can_manage_employee_documents'
--   );
--   DELETE FROM permission_flags WHERE code IN (
--       'can_manage_pos_thresholds', 'can_view_exceptions',
--       'can_broadcast_announcements', 'can_conduct_performance_review',
--       'can_view_attrition_risk', 'can_manage_employee_documents'
--   );
-- COMMIT;
