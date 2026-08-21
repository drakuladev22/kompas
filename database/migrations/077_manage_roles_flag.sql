-- ===========================================================================
-- 077 — `can_manage_roles` FLAG-I (QA-FULL, FAZA 3 TAPINTISI)
-- ===========================================================================
-- Tarix : 2026-08-21
-- Səbəb : `security`-nin tapıntısı — `user_management.py:80`
--         `MANAGE_ROLES_FLAG = "can_manage_roles"`, `:291` rol dəyişikliyində
--         `self._require(actor, MANAGE_ROLES_FLAG)` çağırır, amma bu kod
--         `permission_flags`-də HEÇ VAXT olmayıb (0 istinad). `position_
--         permissions.flag_code` VƏ `user_permission_overrides.flag_code`
--         hər ikisi `REFERENCES permission_flags(code)` — yəni flag HEÇ KİMƏ
--         verilə bilmir və rol dəyişikliyi HƏR aktor üçün, Root DAXİL,
--         `AuthorizationError` ilə bitir.
--
--         `git log -S"MANAGE_ROLES_FLAG"` göstərir ki, flag `73fcff1`
--         commitində `can_manage_positions`/`can_control_user_permissions`/
--         `can_manage_system_limits` İLƏ EYNİ VAXTDA yazılıb — o üçü
--         `schema.sql` §22-yə düşüb, bu UNUDULUB. Qüsur unutqanlıqdır,
--         qəsdli deviasiya deyil.
--
-- ---------------------------------------------------------------------------
-- NİYƏ KATEQORİYA `ICAZE`, `HR` YOX
-- ---------------------------------------------------------------------------
-- `ICAZE` kateqoriyası "kim kimə hansı gücü verə bilər" oxudur:
-- `can_manage_permissions`=1 (yeni flag yarat), `can_manage_positions`=2
-- (yeni rol tərtib et), `can_control_user_permissions`=3 (fərdi grant/deny).
-- Rol TƏYİNATI (mövcud işçiyə mövcud rolu vermək) da EYNİ oxdadır — "hansı
-- gücün kimdə olacağını" dəyişir, `HR`-in PIN/şifrə/növbə əməliyyatlarından
-- keyfiyyətcə fərqlidir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `hardlock_level=3` — `can_control_user_permissions` İLƏ EYNİ
-- ---------------------------------------------------------------------------
-- Rol təyinatı `can_control_user_permissions`-un ƏN YAXIN analoqudur: hər
-- ikisi Strict Hierarchy Guard-a (aktor yalnız ÖZÜNDƏN aşağı pilləyə toxuna
-- bilər) VƏ Self-Escalation Guard-a tabedir, ikisi də CEO/Admin səviyyəsində
-- HƏVALƏ edilə bilən əməliyyatdır (`can_manage_positions`-un 2-ci səviyyəsi
-- YENİ rol YARADIR — daha nadir, daha ağır əməliyyat; rol TƏYİNATI isə
-- gündəlik HR işidir, ona görə 1 və ya 2 YOX, 3).
--
-- ---------------------------------------------------------------------------
-- NİYƏ `is_anti_fraud=FALSE`
-- ---------------------------------------------------------------------------
-- Rol dəyişikliyi ÖZÜ anti-fraud flag VERMİR: hədəf rolun flag dəsti onun
-- YARADILIŞ anında `PermissionFlag.assert_grantable_to()` ilə artıq
-- vetting-dən keçib (Mağaza_Meneceri/Satıcı-ya anti-fraud flag bağlana
-- bilməz — bax `authorization.py`, `ANTI_FRAUD_FORBIDDEN_ROLES`). Üstəlik
-- `Employee.change_position()` (`user_management.py:293-300`) yeni rolda
-- QADAĞAN olan fərdi override-ları SİLİR — yəni rol dəyişikliyi anti-fraud
-- ayrılığını POZA BİLMİR, əksinə onu TƏMİZLƏYİR.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `schema.sql` §22-yə YAZILMIR — QƏSDLİDİR
-- ---------------------------------------------------------------------------
-- CLAUDE.md §7-nin "hər iki yer" qaydası BURADA TƏTBİQ OLUNMUR: bu, mövcud
-- QAYDANIN (trigger/indeks/constraint) dəyişməsi deyil, TAMAM YENİ kataloq
-- sətridir. Presedent — `021` (+6), `038` (+6), `047` (+1), `056` (+1),
-- `063` (+1), `068` (+3), `072` (+1): heç biri §22-yə toxunmayıb. Səbəb
-- `072`-nin şərhində yazılıb: `schema.sql`-in ADMIN/CEO/ROOT seed bloku
-- (§23) BÜTÜN miqrasiyalardan ƏVVƏL, HƏMİN FAYLIN İÇİNDƏ icra olunur — əgər
-- bu flag §22-yə yazılsaydı belə, §23-ün "Root: bütün flag-lər" wildcard-ı
-- ONU DA tutardı və Root-a MİQRASİYA 077-dən ƏVVƏL, keçmiş buraxılışlarda
-- verilmiş olardı — reyestrsiz, izsiz. CLAUDE.md §8-in "55 flag = 36
-- schema.sql + 19 miqrasiya" hesabı bu presedenti təsdiqləyir.
--
-- ---------------------------------------------------------------------------
-- DEFOLT SAHİBLİK — İSTİFADƏÇİ QƏRARI: YALNIZ `ROOT` VƏ `CEO`
-- ---------------------------------------------------------------------------
-- `security`-nin təklifi `ROOT, CEO, ADMIN` idi; istifadəçi ADMIN-i ÇIXARDI.
-- Rol təyinatı ən yuxarı İKİ pillədə saxlanılır: `Admin` və `HR_Admin`
-- `can_manage_employees` ilə ad/PIN/şifrə/mağaza redaktə edə bilir, amma
-- işçinin ROLUNU dəyişə BİLMİR — bu, qəsdli sıxlaşdırmadır (bir Admin öz
-- səviyyəsindəki başqa Admin-i "Satıcı"ya endirə, yaxud özünü CEO-ya
-- yüksəldə bilməməlidir; hər iki risk yalnız ROOT/CEO-da qapanır).
--
-- `positions.tenant_id IS NULL` süzgəci İŞLƏNMİR (CLAUDE.md §8, `069`-un
-- dərsi) — MÖVCUD kirayəçilərin `ROOT`/`CEO` vəzifələri DƏ flag-i ALMALIDIR,
-- əks halda `069`-un tapdığı eyni sinif qüsur təkrarlanar: TƏK sorğu ilə həm
-- sistem şablonu (gələcək kirayəçilər `seed_tenant_defaults()` ilə ondan
-- kopyalayır), həm də artıq mövcud kirayəçilərin ROOT/CEO sətirləri əhatə
-- olunur.
--
-- `ROOT`/`CEO` AÇIQ yazılır (WHERE p.code IN (...)) — kod-səviyyəli bypass
-- YOXDUR: `Employee.has_permission()` sırf `position.has_flag()`-a əsaslanır
-- (`entities/employee.py:269-278`), `schema.sql`-in §23 "Root: bütün
-- flag-lər" wildcard-ı isə YALNIZ ƏVVƏLCƏDƏN mövcud olan (§22-nin ilk 36
-- sətri) flag-ləri tutur — bu miqrasiyadan sonra yaranan flag həmin
-- wildcard-ın İCRA ANINDAN kənarda qalır, ona görə Root-a da AÇIQ verilir.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING` hər iki INSERT-də. Sətir artıq mövcuddursa və
-- atributları gözlənilənlə uyğun deyilsə `DO $$ ... RAISE EXCEPTION` ilə
-- DAYANIR — `056`/`063`/`068`/`072` ilə EYNİ qərar: sükutla davam etmək
-- flag-i ZƏİF vəziyyətdə qoyardı. Sonunda şərhli DOWN bloku var.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. KATALOQ SƏTRİ
-- ---------------------------------------------------------------------------
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only)
VALUES
    ('can_manage_roles', 'ICAZE', 'İşçiyə rol təyin et',
     'Mövcud işçiyə mövcud rolu TƏYİN etmək — `can_manage_positions`-dan '
     'FƏRQİ: yeni rol YARATMAQ DEYİL, mövcud rolu mövcud işçiyə bağlamaqdır. '
     'Strict Hierarchy + Self-Escalation Guard-a tabedir.',
     3, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- Sətir əvvəldən mövcuddursa və atributları gözlənilənlə uyğun deyilsə
-- `UPDATE` mümkün deyil (`trg_flag_attributes_immutable`, migrasiya 013) —
-- `056`/`063`/`068`/`072` ilə EYNİ qərar: sükutla davam etmək flag-i ZƏİF
-- vəziyyətdə qoyardı.
DO $$
DECLARE
    v_wrong TEXT;
BEGIN
    SELECT string_agg(code, ', ')
      INTO v_wrong
      FROM permission_flags
     WHERE code = 'can_manage_roles'
       AND (category <> 'ICAZE' OR hardlock_level <> 3
            OR is_anti_fraud <> FALSE OR is_camera_only <> FALSE);

    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: can_manage_roles ARTIQ mövcuddur, lakin '
            'atributları gözlənilənlə uyğun deyil: %', v_wrong;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. DEFOLT SAHİBLİK — YALNIZ `ROOT` VƏ `CEO` (istifadəçi qərarı)
-- ---------------------------------------------------------------------------
-- `positions.tenant_id IS NULL` süzgəci İŞLƏNMİR — `069`/`047` naxışı: TƏK
-- sorğu ilə HƏM sistem şablonu, HƏM DƏ artıq mövcud kirayəçilərin ROOT/CEO
-- sətirləri əhatə olunur (bax fayl başlığı). `granted_by` QƏSDƏN NULL
-- (sütun defoltu) — sistem seed-i `enforce_grantor_owns_flag()` istisnasıdır
-- (schema.sql §18, `063`/`068`/`072` ilə eyni qərar).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_roles', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   -- DİQQƏT: bu, Root-un ƏL İLƏ başqa rollara (məs. Admin) verdiyi əlavə
--   -- sətirləri DƏ silər (eyni fərq `069`/`072`-nin DOWN-unda
--   -- sənədləşdirilib) — YALNIZ bu miqrasiyanın verdiyi ROOT/CEO sətirlərini
--   -- geri almaq üçün şərt daraldılmalıdır.
--   DELETE FROM position_permissions
--    WHERE flag_code = 'can_manage_roles'
--      AND position_id IN (SELECT id FROM positions WHERE code IN ('ROOT', 'CEO'));
--   DELETE FROM permission_flags WHERE code = 'can_manage_roles';
-- COMMIT;
