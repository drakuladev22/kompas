-- ===========================================================================
-- 056 — `can_resolve_sync_conflicts` (SEC-018): KONFLİKT HƏLLİ ARTIQ YAZI
--       ƏMƏLİYYATIDIR VƏ BAXIŞ FLAG-İ İLƏ AÇILA BİLMƏZ
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : `SyncConflictUseCase.resolve()` indiyə qədər YALNIZ `sync_conflicts`
--         sətrini bağlayırdı — hədəf cədvələ (`fines`, `leave_requests`,
--         `attendance_records`) heç nə yazılmırdı. Yəni `KEPT_LOCAL` seçimi
--         qeyd sənədi idi, məlumat düzəlişi deyil: konflikt anında hədəfdə
--         UZAQ versiya durur (`offline/sync.py::_apply` divergensiyada
--         `_upsert()`-i ÇAĞIRMADAN `return "CONFLICT"` edir), ona görə
--         "mağazadakı versiyanı saxladım" yazan HR-ın qərarından sonra da
--         cədvəldə bulud versiyası qalırdı.
--
--         Həmin boşluq bağlandı: `KEPT_LOCAL` artıq hədəf sətri FAKTİKİ
--         yeniləyir. Bununla birlikdə İCAZƏ QAPISI dözülməz hala düşdü —
--         qapı `can_view_employee_reports` idi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ KÖHNƏ QAPI TƏHLÜKƏLİDİR (konkret hücum yolu)
-- ---------------------------------------------------------------------------
-- `schema.sql` §23 `can_view_employee_reports` flag-ini `MAGAZA_MENECERI`
-- rolununa DEFOLT VERİR. Yəni düzəlişdən sonra hər mağaza meneceri öz
-- filialının cərimə sətrini "konflikt həlli" düyməsi ilə offline payload-una
-- əvəz edə bilərdi: cəriməni YARADAN kamera təsdiqi, DUAL-CONTROL ikinci
-- imzası və aylıq `PENDING_REVIEW → PUBLISHED` icmalı — hamısı yan keçilərdi.
-- Bu, CLAUDE.md §5-dəki vəzifə ayrılığının birbaşa pozulmasıdır.
--
-- ---------------------------------------------------------------------------
-- YENİ GUARD YAZILMIR — TRIGGER MƏLUMATLA İŞLƏYİR
-- ---------------------------------------------------------------------------
-- `enforce_anti_fraud_segregation()` (schema.sql §18) `permission_flags`
-- sətrindəki `is_anti_fraud` / `is_camera_only` / `excludes_camera_role`
-- sütunlarını OXUYARAQ işləyir və HƏM `position_permissions`, HƏM
-- `user_permission_overrides` üzərində trigger-dir. Domendə eyni qayda
-- `PermissionFlag.assert_grantable_to()`-dadır (`ANTI_FRAUD_FORBIDDEN_ROLES`,
-- `src/domain/value_objects/authorization.py`). Ona görə struktur zəmanət
-- İKİ yerdə mövcuddur və bu miqrasiya yalnız kataloqa YENİ SƏTİR əlavə edir —
-- `038` ilə eyni naxış.
--
-- ---------------------------------------------------------------------------
-- `is_anti_fraud = TRUE` — NİYƏ
-- ---------------------------------------------------------------------------
-- Bu, flag-i `MAGAZA_MENECERI` və `SATICI` üçün STRUKTUR olaraq əlçatmaz edir:
-- nə rol-defoltu, nə də fərdi override (`user_permission_overrides`) onu verə
-- bilmir, çünki hər iki cədvəldə eyni trigger dayanır. "Sadəcə defolt
-- verməmək" KİFAYƏT ETMİRDİ — Root/CEO fərdi override ilə səhvən (və ya
-- təzyiq altında) verə bilərdi, halbuki bu, anti-fraud qatının ÖZÜDÜR.
--
-- ---------------------------------------------------------------------------
-- `excludes_camera_role = TRUE` — NİYƏ (`can_publish_fines` presedenti)
-- ---------------------------------------------------------------------------
-- Kamera Nəzarətçisi `can_issue_fines` daşıyır, yəni cəriməni O YARADIR.
-- Konflikt həllində `KEPT_LOCAL` seçmək isə "mağaza PC-sindəki (yəni çox vaxt
-- OPERATORUN ÖZ yazdığı) versiya qalsın" deməkdir — cəriməni yaradanın öz
-- versiyasını təkbaşına qüvvəyə mindirməsi. Bu, `can_publish_fines` üçün artıq
-- verilmiş qərarın eynidir (schema.sql §23: "cərimə YARADAN ilə cərimə TƏSDİQ
-- EDƏN eyni şəxs ola bilməz") və orada da məhz `excludes_camera_role` ilə
-- həll olunub.
--
-- `is_camera_only` isə TƏBİİ olaraq `FALSE`-dur və olmalıdır: `TRUE` olsaydı
-- (a) domen səviyyəsində `PermissionFlag.__post_init__` `is_camera_only` +
-- `excludes_camera_role` kombinasiyasını `ValueError` ilə rədd edərdi, (b)
-- `schema.sql` §23-dəki Root bloku `AND NOT pf.is_camera_only` şərti ilə
-- işlədiyi üçün Root flag-i ÖZÜ ala bilməzdi.
--
-- ---------------------------------------------------------------------------
-- `hardlock_level = 0` (NONE) — NİYƏ DAHA YÜKSƏYİ YOX
-- ---------------------------------------------------------------------------
-- Spesifikasiya bölmə 5 həlli AÇIQ şəkildə `HR_Admin`-ə verir ("`CONFLICT`
-- statusu ilə HR_Admin-ə MANUAL HƏLL üçün göndərilir"). `HR_ADMIN` isə
-- `OPERATIONAL` (priority 3) pilləsindədir və `HardlockLevel.allows()`-a görə:
--     səviyyə 1 (ROOT_ONLY)  → yalnız Root      → HR_Admin kənarda
--     səviyyə 2 (ROOT_CEO)   → Root/CEO         → HR_Admin kənarda
--     səviyyə 3 (DELEGABLE)  → priority <= 2    → HR_Admin kənarda
-- Yəni SIFIRDAN FƏRQLİ hər səviyyə spesifikasiyanın təyin etdiyi sahibi
-- strukturca kənarlaşdırardı. Məhdudiyyəti anti-fraud ölçüsü daşıyır
-- (yuxarı), hardlock ölçüsü YOX — ikisi `authorization.py`-də QƏSDƏN
-- müstəqildir.
--
-- ---------------------------------------------------------------------------
-- DUAL-CONTROL ƏLAVƏ EDİLMİR — `is_audit_critical` NİYƏ QAPI DEYİL
-- ---------------------------------------------------------------------------
-- `ConflictItem.is_audit_critical` mövcuddur, lakin AYIRD EDİCİ deyil:
-- `OfflineSyncService._apply()` konflikt sətrini YALNIZ
-- `write.is_audit_critical` olduqda yaradır, yəni cədvəldəki praktiki olaraq
-- BÜTÜN açıq konfliktlər audit-kritikdir. Onları dual-control arxasına almaq
-- "bütün konflikt həllini iki nəfərlik et" demək olardı — bu isə
-- spesifikasiyada OLMAYAN yeni iş qaydasıdır (bölmə 5 tək HR_Admin deyir).
-- Qoruma əvəzinə mövcud üç qatdan gəlir: anti-fraud flag ayrılığı, MƏCBURİ
-- səbəb qeydi (`MIN_NOTE_LENGTH`) və tam audit izi (`SYNC_CONFLICT_RESOLVED`,
-- `applied_version` + `target_rows_written` sahələri ilə).
--
-- ---------------------------------------------------------------------------
-- KATEQORİYA — NİYƏ 'ERP_INFRA', 'HR' DEYİL
-- ---------------------------------------------------------------------------
-- Konflikt HR iş-prosesi nəticəsində YARANMIR — o, offline bufer/sinxronizasiya
-- infrastrukturunun məhsuludur və menyuda da məhz `can_view_system_health`
-- (Sistem Sağlamlığı, ERP_INFRA) ilə `can_view_audit_logs` arasında dayanır
-- (`shell/menu.py`, order 152). Admin icazə matrisində onu həmin qonşuluqda
-- axtaracaq.
--
-- ---------------------------------------------------------------------------
-- RETROAKTİV ƏHATƏ
-- ---------------------------------------------------------------------------
-- `038` ilə eyni: `schema.sql` §22/§23 yalnız İLK quraşdırmada, bu flag hələ
-- mövcud olmadan işləyir. Ona görə həm kataloq sətri, həm rol təyinatları
-- BURADA açıq yazılır və `WHERE p.code IN (...)` şərti TENANT FİLTRSİZDİR —
-- həm sistem şablonunu, həm artıq mövcud kirayəçiləri əhatə edir.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. KATALOQ SƏTRİ (mövcud flag-lərdən HEÇ BİRİ TOXUNULMUR)
-- ---------------------------------------------------------------------------
-- `ON CONFLICT (code) DO NOTHING`: təkrar icrada Root-un redaktə etdiyi
-- `name_az`/`description_az` üzərindən YAZILMIR (017/018/021/038 ilə eyni).
-- ---------------------------------------------------------------------------
-- `excludes_camera_role` SÜTUN SİYAHISINDADIR — VƏ BU, DÜZƏLİŞDİR
-- ---------------------------------------------------------------------------
-- ƏVVƏL sütun INSERT-də YOX idi, dəyər isə ardınca gələn `UPDATE ... SET
-- excludes_camera_role = TRUE` ilə verilirdi (§23-dəki `can_publish_fines`
-- naxışı). Həmin naxış `schema.sql`-də İŞLƏYİR, çünki orada seed miqrasiya
-- 013-dən ƏVVƏL icra olunur. BURADA isə 013-ün `trg_flag_attributes_immutable`
-- trigger-i ARTIQ mövcuddur və o, `excludes_camera_role`-un dəyişməsini
-- QADAĞAN edir (bölmə 3: atributlar konfiqurasiya deyil, struktur zəmanətdir).
--
-- Nəticə: miqrasiya HƏR TƏMİZ QURAŞDIRMADA eyni yerdə çökürdü —
--     «DƏYİŞMƏZ ATRİBUT: "can_resolve_sync_conflicts" ...»
-- və fayl `BEGIN/COMMIT` içində olduğu üçün BÜTÜN 056 geri qayıdırdı. DB-1
-- FAZA 4 (sıfırdan tətbiq testi) bunu aşkarladı; canlı bazada da flag YOX idi,
-- yəni miqrasiya HEÇ VAXT uğurla tətbiq olunmamışdı.
--
-- Düzəliş: dəyər sətrin YARANDIĞI anda verilir — trigger yalnız `UPDATE`-ə
-- baxır, `INSERT`-ə yox. `ON CONFLICT (code) DO NOTHING`: təkrar icrada
-- Root-un redaktə etdiyi `name_az`/`description_az` üzərindən YAZILMIR
-- (017/018/021/038 ilə eyni).
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only, excludes_camera_role)
VALUES
    ('can_resolve_sync_conflicts', 'ERP_INFRA',
        'Sinxronizasiya konfliktini həll et',
        'Offline rejimdə yaranan konfliktin manual həlli (bölmə 5). '
        '«Mağazadakı versiya saxlanıldı» seçimi hədəf sətri (cərimə/icazə/'
        'davamiyyət) FAKTİKİ olaraq yerli versiya ilə əvəz edir — ona görə '
        'bu, BAXIŞ deyil, YAZI səlahiyyətidir. Anti-fraud: Mağaza Meneceri '
        'və Satıcı bu flag-i nə rol, nə də fərdi override ilə ala bilməz.',
        0, TRUE, FALSE, TRUE)
ON CONFLICT (code) DO NOTHING;

-- Sətir ƏVVƏLDƏN mövcud olub və atributları səhvdirsə, onu `UPDATE` ilə
-- düzəltmək MÜMKÜN DEYİL (elə həmin trigger). Sükutla davam etmək isə flag-i
-- "anti-fraud" sanılan, əslində isə kamera roluna açıq vəziyyətdə qoyardı —
-- ona görə açıq şəkildə dayanırıq və nə edilməli olduğunu yazırıq.
DO $$
DECLARE
    v_wrong BOOLEAN;
BEGIN
    SELECT NOT (is_anti_fraud AND excludes_camera_role AND hardlock_level = 0)
      INTO v_wrong
      FROM permission_flags
     WHERE code = 'can_resolve_sync_conflicts';

    IF v_wrong THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: "can_resolve_sync_conflicts" flag-i mövcuddur, '
            'lakin təhlükəsizlik atributları gözlənilənlə uyğun deyil '
            '(is_anti_fraud=TRUE, excludes_camera_role=TRUE, hardlock_level=0). '
            'Atributlar trigger ilə qıfıllıdır — sətri yalnız Root nəzarətində, '
            'əl ilə düzəltmək olar.';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. DEFOLT SAHİBLİK — ROOT, CEO, ADMIN, HR_ADMIN
-- ---------------------------------------------------------------------------
-- ROOT/CEO: "Root hər şeyi görür" invariantı (§23). Flag `is_camera_only`
--     DEYİL və `hardlock_level <> 1` — yəni §23-ün hər iki şərtinə uyğundur,
--     sadəcə o blok bu sətir yaranmazdan əvvəl icra olunub.
-- HR_ADMIN: spesifikasiya bölmə 5-in AÇIQ təyinatı.
-- ADMIN: HR_Admin-dən BİR PİLLƏ YUXARI operativ rəhbərdir və artıq
--     `can_view_system_health` daşıyır — konflikt xəbərdarlığı məhz orada
--     görünür (`screen_data._health_alerts`). Xəbərdarlığı görüb ekranı aça
--     bilməyən rol problemi yalnız AŞAĞI pilləyə ötürə bilərdi; bu, iyerarxiyanı
--     tərsinə çevirərdi.
-- `granted_by` QƏSDƏN NULL: `enforce_grantor_owns_flag()`-ın "sistem seed-i"
--     istisnası (schema.sql §18) məhz bu haldır.
--
-- MAGAZA_MENECERI / SATICI / KAMERA_NEZARETCISI BURADA YOXDUR və olmayacaq:
-- ilk ikisini `is_anti_fraud`, üçüncünü `excludes_camera_role` trigger
-- səviyyəsində bloklayır. Yəni bu siyahıya səhvən əlavə edilsələr belə,
-- `INSERT` istisna ilə dayanardı — siyahının qısalığı təsadüf deyil, ikinci
-- qatla üst-üstə düşür.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_resolve_sync_conflicts', TRUE
FROM positions p
WHERE p.code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN')
ON CONFLICT DO NOTHING;

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: geri qaytarma konflikt həlli ekranını BÜTÜN rollar üçün bağlayır
-- (`SyncConflictUseCase._require` bu flag-i tələb edir) — konflikt sətirləri
-- isə yığılmağa davam edir. Yəni DOWN yalnız `use_cases/sync_conflicts.py`-dəki
-- `RESOLVE_CONFLICT_FLAG` sabiti də geri qaytarılırsa mənalıdır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DELETE FROM user_permission_overrides WHERE flag_code = 'can_resolve_sync_conflicts';
--   DELETE FROM position_permissions      WHERE flag_code = 'can_resolve_sync_conflicts';
--   DELETE FROM permission_flags          WHERE code      = 'can_resolve_sync_conflicts';
-- COMMIT;
