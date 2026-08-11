-- ===========================================================================
-- KompasOS — DB-SƏVİYYƏLİ TƏHLÜKƏSİZLİK ZƏMANƏTLƏRİNİN TESTİ
-- ===========================================================================
-- Bu testlər bölmə 3-dəki "HARDCODED CORE SAFETY RULES" qaydalarının DB
-- qatında da işlədiyini təsdiqləyir (defense-in-depth). CI-da `db-schema`
-- job-u tərəfindən icra olunur.
--
-- İCRA:  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/tests/test_guards.sql
--
-- Hər test öz SAVEPOINT-i daxilində işləyir və geri qaytarılır — baza
-- çirklənmir.
-- ===========================================================================

\set ON_ERROR_STOP on
SET search_path TO kompasos, public;

DO $$
DECLARE
    v_tenant     UUID;
    v_store      UUID;
    v_pos_root   UUID;
    v_pos_ceo    UUID;
    v_pos_admin  UUID;
    v_pos_hr     UUID;
    v_pos_store  UUID;
    v_pos_camera UUID;
    v_pos_seller UUID;
    v_root       UUID;
    v_admin      UUID;
    v_manager    UUID;
    v_seller     UUID;
    v_failed     BOOLEAN;
    v_passed     INTEGER := 0;
BEGIN
    -- ---------------------------------------------------------------- setup
    INSERT INTO license_tenants (tenant_name, license_key_hash, status, company_contact_email)
    VALUES ('GUARD-TEST', 'test', 'AKTIV', 'guard@test.local')
    RETURNING tenant_id INTO v_tenant;

    PERFORM seed_tenant_defaults(v_tenant);

    INSERT INTO stores (tenant_id, code, name, brand)
    VALUES (v_tenant, 'T-001', 'Test Mağaza', 'Yataş')
    RETURNING id INTO v_store;

    SELECT id INTO v_pos_root   FROM positions WHERE tenant_id = v_tenant AND code = 'ROOT';
    SELECT id INTO v_pos_ceo    FROM positions WHERE tenant_id = v_tenant AND code = 'CEO';
    SELECT id INTO v_pos_admin  FROM positions WHERE tenant_id = v_tenant AND code = 'ADMIN';
    SELECT id INTO v_pos_hr     FROM positions WHERE tenant_id = v_tenant AND code = 'HR_ADMIN';
    SELECT id INTO v_pos_store  FROM positions WHERE tenant_id = v_tenant AND code = 'MAGAZA_MENECERI';
    SELECT id INTO v_pos_camera FROM positions WHERE tenant_id = v_tenant AND code = 'KAMERA_NEZARETCISI';
    SELECT id INTO v_pos_seller FROM positions WHERE tenant_id = v_tenant AND code = 'SATICI';

    INSERT INTO employees (tenant_id, store_id, position_id, first_name, last_name,
                           username, password_hash)
    VALUES (v_tenant, v_store, v_pos_root, 'Test', 'Root', 'guard.root', 'argon2-hash')
    RETURNING id INTO v_root;

    INSERT INTO employees (tenant_id, store_id, position_id, first_name, last_name,
                           username, password_hash)
    VALUES (v_tenant, v_store, v_pos_admin, 'Test', 'Admin', 'guard.admin', 'argon2-hash')
    RETURNING id INTO v_admin;

    INSERT INTO employees (tenant_id, store_id, position_id, first_name, last_name,
                           username, password_hash)
    VALUES (v_tenant, v_store, v_pos_store, 'Test', 'Manager', 'guard.manager', 'argon2-hash')
    RETURNING id INTO v_manager;

    INSERT INTO employees (tenant_id, store_id, position_id, first_name, last_name, pin_hash)
    VALUES (v_tenant, v_store, v_pos_seller, 'Test', 'Satici', 'argon2-pin-hash')
    RETURNING id INTO v_seller;

    -- =====================================================================
    -- TEST 1: ANTI-FRAUD — `can_issue_fines` Mağaza_Meneceri-yə VERİLƏ BİLMƏZ
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO position_permissions (position_id, flag_code, granted)
        VALUES (v_pos_store, 'can_issue_fines', TRUE);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 1 UĞURSUZ: can_issue_fines Mağaza_Meneceri-yə verildi!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 1 ✓ anti-fraud: can_issue_fines → Mağaza_Meneceri bloklandı';

    -- =====================================================================
    -- TEST 2: ANTI-FRAUD — fərdi override yolu ilə də verilə bilməz
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_manager, 'can_override_return_time', 'GRANT', v_root);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 2 UĞURSUZ: anti-fraud flag override yolu ilə verildi!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 2 ✓ anti-fraud: fərdi override yolu da bağlıdır';

    -- =====================================================================
    -- TEST 3: HARDLOCK səviyyə 1 — `can_manage_permissions` CEO-ya belə YOX
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO position_permissions (position_id, flag_code, granted)
        VALUES (v_pos_ceo, 'can_manage_permissions', TRUE);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 3 UĞURSUZ: can_manage_permissions CEO-ya verildi!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 3 ✓ hardlock L1: can_manage_permissions yalnız Root-dadır';

    -- =====================================================================
    -- TEST 4: HARDLOCK səviyyə 2 — `can_manage_positions` HR_Admin-ə YOX
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO position_permissions (position_id, flag_code, granted)
        VALUES (v_pos_hr, 'can_manage_positions', TRUE);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 4 UĞURSUZ: can_manage_positions HR_Admin-ə verildi!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 4 ✓ hardlock L2: can_manage_positions yalnız Root/CEO';

    -- =====================================================================
    -- TEST 5: SELF-ESCALATION GUARD — özünə icazə əlavə etmək olmaz
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_admin, 'can_export_reports', 'GRANT', v_admin);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 5 UĞURSUZ: istifadəçi özünə icazə əlavə etdi!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 5 ✓ self-escalation guard işləyir';

    -- =====================================================================
    -- TEST 6: HIERARCHY GUARD — Admin (priority 1) Root-a (0) toxuna bilməz
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_root, 'can_export_reports', 'DENY', v_admin);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 6 UĞURSUZ: Admin Root-un icazəsinə toxundu!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 6 ✓ strict hierarchy guard işləyir';

    -- =====================================================================
    -- TEST 7: MÜSBƏT HAL — Admin Satıcı-ya (priority 3) icazə verə bilər
    -- =====================================================================
    INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
    VALUES (v_seller, 'can_view_employee_reports', 'GRANT', v_admin);
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 7 ✓ Admin → aşağı iyerarxiyalı istifadəçiyə icazə verə bilir';

    -- =====================================================================
    -- TEST 8: VƏZİFƏ AYRILIĞI — kamera rolu dual-control təsdiqi daşıya bilməz
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO position_permissions (position_id, flag_code, granted)
        VALUES (v_pos_camera, 'can_approve_dual_control_override', TRUE);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 8 UĞURSUZ: Kamera Operatoru öz override-ını təsdiqləyə bilər!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 8 ✓ vəzifə ayrılığı: kamera rolu dual-control təsdiqini daşımır';

    -- =====================================================================
    -- TEST 9: PENALTY LOGIC — Delay mənfi ola bilməz
    -- =====================================================================
    DECLARE
        v_delay INTEGER;
        v_total INTEGER;
    BEGIN
        -- Erkən qayıdış: 60 dəq. icazə, 30 dəq. sonra qayıdıb → Delay = 0
        SELECT delay_minutes, total_minutes INTO v_delay, v_total
        FROM calculate_leave_penalty(
            now() - INTERVAL '30 minutes', now(), 60
        );
        IF v_delay <> 0 THEN
            RAISE EXCEPTION 'TEST 9 UĞURSUZ: erkən qayıdışda Delay = % (0 olmalıdır)', v_delay;
        END IF;

        -- Gecikmə: 60 dəq. icazə, 90 dəq. sonra → Delay = 30, Total = 60 + 60 = 120
        SELECT delay_minutes, total_minutes INTO v_delay, v_total
        FROM calculate_leave_penalty(
            now() - INTERVAL '90 minutes', now(), 60
        );
        IF v_delay <> 30 OR v_total <> 120 THEN
            RAISE EXCEPTION 'TEST 9 UĞURSUZ: Delay=%, Total=% (30 və 120 gözlənilirdi)',
                v_delay, v_total;
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 9 ✓ PENALTY LOGIC: max(0, delay) və Total = Req + 2×Delay';

    -- =====================================================================
    -- TEST 10: CƏRİMƏ — MANUAL_CAMERA foto sübutu olmadan qəbul edilmir
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO fines (tenant_id, employee_id, store_id, source, amount)
        VALUES (v_tenant, v_seller, v_store, 'MANUAL_CAMERA', 10.00);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 10 UĞURSUZ: foto sübutsuz manual cərimə yaradıldı!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 10 ✓ manual cərimə üçün foto sübutu məcburidir';

    -- =====================================================================
    -- TEST 11: OVERRIDE — operator öz override-ını özü təsdiqləyə bilməz
    -- =====================================================================
    DECLARE
        v_attendance UUID;
    BEGIN
        INSERT INTO attendance_records (tenant_id, employee_id, store_id, work_date)
        VALUES (v_tenant, v_seller, v_store, CURRENT_DATE)
        RETURNING id INTO v_attendance;

        v_failed := FALSE;
        BEGIN
            INSERT INTO manual_time_overrides (
                tenant_id, attendance_record_id, operator_id, employee_id,
                system_time, overridden_time, delta_minutes, reason, approved_by
            ) VALUES (
                v_tenant, v_attendance, v_root, v_seller,
                now(), now() - INTERVAL '40 minutes', 40,
                'Test səbəbi, on simvoldan uzun', v_root
            );
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION 'TEST 11 UĞURSUZ: operator öz override-ını özü təsdiqlədi!';
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 11 ✓ self-approval bloklandı';

    -- =====================================================================
    -- TEST 12: ETİRAZ PƏNCƏRƏSİ trigger-i 72 saatı avtomatik təyin edir
    -- =====================================================================
    DECLARE
        v_fine_type UUID;
        v_fine_id   UUID;
        v_closes    TIMESTAMPTZ;
    BEGIN
        INSERT INTO fine_types (tenant_id, name_az, standard_amount)
        VALUES (v_tenant, 'Test Cərimə Növü', 15.00)
        RETURNING id INTO v_fine_type;

        INSERT INTO fines (tenant_id, employee_id, store_id, source, fine_type_id,
                           amount, issued_by, photo_evidence_url)
        VALUES (v_tenant, v_seller, v_store, 'MANUAL_CAMERA', v_fine_type,
                15.00, v_root, 'https://storage.test/evidence.jpg')
        RETURNING id, appeal_window_closes_at INTO v_fine_id, v_closes;

        -- (a) YARADILAN anda sayğac HƏLƏ BAŞLAMIR.
        --
        -- Bu şərt miqrasiya 016-da DƏYİŞDİRİLDİ. Əvvəl trigger pəncərəni
        -- INSERT anında doldururdu; nəticədə icmalda bir həftə gözləyən
        -- cərimənin 72 saatı işçi onu GÖRMƏMİŞ bitirdi. Qayda isə müddətin
        -- NƏŞRDƏN sayılmasını tələb edir, ona görə nəşr olunmamış sətirdə
        -- sütun NULL qalır (fail-safe: `v_exportable_fines` onu buraxmır).
        IF v_closes IS NOT NULL THEN
            RAISE EXCEPTION
                'TEST 12 UĞURSUZ: nəşr olunmamış cərimədə etiraz pəncərəsi '
                'açıldı (%) — sayğac yaradılışdan sayılır!', v_closes;
        END IF;

        -- (b) NƏŞRDƏN sonra pəncərə `system_limits`-dəki 72 saatdan qurulur.
        UPDATE fines
           SET status       = 'PUBLISHED',
               published_at = now(),
               reviewed_by  = v_root
         WHERE id = v_fine_id;

        SELECT appeal_window_closes_at INTO v_closes FROM fines WHERE id = v_fine_id;

        IF v_closes IS NULL
           OR v_closes < now() + INTERVAL '71 hours'
           OR v_closes > now() + INTERVAL '73 hours' THEN
            RAISE EXCEPTION
                'TEST 12 UĞURSUZ: nəşrdən sonra etiraz pəncərəsi 72 saata '
                'təyin olunmadı (%)', v_closes;
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 12 ✓ etiraz pəncərəsi nəşrdən sayılır (yaradılışda NULL, nəşrdə 72 saat)';

    -- =====================================================================
    -- TEST 13: CEO ↔ CEO — bərabər pillə müdaxiləsi bloklanır (SEC-006)
    -- =====================================================================
    DECLARE
        v_ceo_a UUID;
        v_ceo_b UUID;
    BEGIN
        INSERT INTO employees (tenant_id, store_id, position_id, first_name, last_name,
                               username, password_hash)
        VALUES (v_tenant, v_store, v_pos_ceo, 'Test', 'CeoA', 'guard.ceoa', 'h')
        RETURNING id INTO v_ceo_a;

        INSERT INTO employees (tenant_id, store_id, position_id, first_name, last_name,
                               username, password_hash)
        VALUES (v_tenant, v_store, v_pos_ceo, 'Test', 'CeoB', 'guard.ceob', 'h')
        RETURNING id INTO v_ceo_b;

        v_failed := FALSE;
        BEGIN
            INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
            VALUES (v_ceo_b, 'can_export_reports', 'DENY', v_ceo_a);
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION 'TEST 13 UĞURSUZ: CEO digər CEO-nun icazəsinə toxundu!';
        END IF;

        -- Root isə istisnadır (əks halda sistem kilidlənərdi)
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_ceo_b, 'can_view_audit_logs', 'DENY', v_root);
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 13 ✓ CEO↔CEO bloklanır, Root istisnası işləyir';

    -- =====================================================================
    -- TEST 14: AUDIT LOG DƏYİŞMƏZLİYİ (SEC-007) — UPDATE/DELETE qadağandır
    -- =====================================================================
    DECLARE
        v_audit_id BIGINT;
    BEGIN
        INSERT INTO audit_logs (tenant_id, action, entity_type, reason)
        VALUES (v_tenant, 'GUARD_TEST', 'test', 'dəyişməzlik yoxlaması')
        RETURNING id INTO v_audit_id;

        v_failed := FALSE;
        BEGIN
            UPDATE audit_logs SET reason = 'dəyişdirildi' WHERE id = v_audit_id;
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION 'TEST 14 UĞURSUZ: audit log sətri redaktə edildi!';
        END IF;

        v_failed := FALSE;
        BEGIN
            DELETE FROM audit_logs WHERE id = v_audit_id;
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION 'TEST 14 UĞURSUZ: audit log sətri silindi!';
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 14 ✓ audit_logs append-only (UPDATE və DELETE bloklandı)';

    -- =====================================================================
    -- TEST 15: RLS FAIL-CLOSED (SEC-008) — kontekst yoxdursa sətir görünmür
    -- =====================================================================
    DECLARE
        v_visible INTEGER;
    BEGIN
        -- Cədvəl sahibi RLS-dən azaddır, ona görə siyasət predikatını
        -- BİRBAŞA yoxlayırıq: kontekst təyin edilməyibsə current_tenant_id()
        -- NULL qaytarmalı və `tenant_id = NULL` heç bir sətrə uyğun gəlməməlidir.
        PERFORM set_config('app.tenant_id', '', TRUE);
        IF current_tenant_id() IS NOT NULL THEN
            RAISE EXCEPTION 'TEST 15 UĞURSUZ: boş kontekstdə current_tenant_id() NULL deyil';
        END IF;

        SELECT count(*) INTO v_visible
        FROM employees WHERE tenant_id = current_tenant_id();
        IF v_visible <> 0 THEN
            RAISE EXCEPTION
                'TEST 15 UĞURSUZ: kontekstsiz halda % sətir görünür (0 olmalıdır)', v_visible;
        END IF;

        -- Kontekst təyin ediləndə isə öz tenant-ının sətirləri görünməlidir
        PERFORM set_config('app.tenant_id', v_tenant::TEXT, TRUE);
        SELECT count(*) INTO v_visible
        FROM employees WHERE tenant_id = current_tenant_id();
        IF v_visible = 0 THEN
            RAISE EXCEPTION 'TEST 15 UĞURSUZ: düzgün kontekstdə heç bir sətir görünmür';
        END IF;

        -- Yararsız UUID mətni istisna atmamalı, NULL qaytarmalıdır (fail-closed)
        PERFORM set_config('app.tenant_id', 'not-a-uuid', TRUE);
        IF current_tenant_id() IS NOT NULL THEN
            RAISE EXCEPTION 'TEST 15 UĞURSUZ: yararsız UUID NULL qaytarmadı';
        END IF;
        PERFORM set_config('app.tenant_id', '', TRUE);
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 15 ✓ RLS predikatı fail-closed işləyir';

    -- =====================================================================
    -- TEST 16: SESSİYA — expires_at mütləq bitmə vaxtını keçə bilməz
    -- =====================================================================
    v_failed := FALSE;
    BEGIN
        INSERT INTO auth_sessions (tenant_id, user_id, token_hash, context,
                                   expires_at, absolute_expiry)
        VALUES (v_tenant, v_root, 'hash-1', 'ADMIN_PANEL',
                now() + INTERVAL '20 hours', now() + INTERVAL '8 hours');
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 16 UĞURSUZ: sessiya mütləq limitdən uzun yaradıldı!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 16 ✓ sessiya mütləq bitmə limiti tətbiq olunur';

    -- =====================================================================
    -- TEST 17: SCHEDULER SAĞLAMLIĞI — run_all_scheduled_jobs() işləyir
    -- =====================================================================
    DECLARE
        v_jobs INTEGER;
    BEGIN
        SELECT count(*) INTO v_jobs FROM run_all_scheduled_jobs();
        IF v_jobs < 8 THEN
            RAISE EXCEPTION
                'TEST 17 UĞURSUZ: run_all_scheduled_jobs() yalnız % job qaytardı', v_jobs;
        END IF;
        IF EXISTS (
            SELECT 1 FROM scheduled_job_runs
            WHERE succeeded = FALSE AND job_name <> '__scheduler_bootstrap__'
        ) THEN
            RAISE EXCEPTION 'TEST 17 UĞURSUZ: ən azı bir planlaşdırılmış job xəta verdi';
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 17 ✓ xarici scheduler girişi (run_all_scheduled_jobs) işləyir';

    -- =====================================================================
    -- TEST 18: SELF-ESCALATION 2 — özündə OLMAYAN flag başqasına verilə bilməz
    -- =====================================================================
    -- `can_manage_leave_types` seed-ə görə HR_Admin-dədir, Admin-də YOXDUR.
    -- Hardlock səviyyəsi 0, anti-fraud deyil — yəni bu sətri bloklaya bilən
    -- YEGANƏ qayda `enforce_grantor_owns_flag()`-dır (migration 014).
    v_failed := FALSE;
    BEGIN
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_seller, 'can_manage_leave_types', 'GRANT', v_admin);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION
            'TEST 18 UĞURSUZ: Admin özündə olmayan flag-i başqasına verdi!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 18 ✓ self-escalation: özündə olmayan flag verilə bilmir';

    -- =====================================================================
    -- TEST 19: MÜSBƏT HAL — flag override ilə aktora verilirsə, o da verə bilir
    -- =====================================================================
    -- Sahiblik İKİ qatın birləşməsidir (rol-defolt + fərdi override), ona görə
    -- override yolu ilə alınmış flag də "sahiblik" sayılmalıdır — domen
    -- `Employee.has_permission()` də məhz belə hesablayır.
    INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
    VALUES (v_admin, 'can_manage_leave_types', 'GRANT', v_root);

    INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
    VALUES (v_seller, 'can_manage_leave_types', 'GRANT', v_admin);
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 19 ✓ override ilə alınmış flag ötürülə bilir';

    -- =====================================================================
    -- TEST 20: SELF-ESCALATION 1 — özünə `DENY` də qadağandır
    -- =====================================================================
    -- Köhnə trigger yalnız `effect = 'GRANT'` halını tuturdu; domen
    -- (`_assert_not_self`) isə hər iki effekti bloklayır (migration 014).
    v_failed := FALSE;
    BEGIN
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_admin, 'can_export_reports', 'DENY', v_admin);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 20 UĞURSUZ: istifadəçi özünə DENY sətri yazdı!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 20 ✓ özünə toxunma effektdən asılı olmayaraq bloklanır';

    -- =====================================================================
    -- TEST 21: `DENY` override rol-defoltu ÜSTƏLƏYİR (sahiblik itir)
    -- =====================================================================
    -- Admin rol-defoltu ilə `can_export_reports` daşıyır. Root ona DENY
    -- yazdıqdan sonra Admin həmin flag-i ARTIQ ötürə bilməməlidir —
    -- `Employee.has_permission()` ilə eyni prioritet sırası.
    INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
    VALUES (v_admin, 'can_export_reports', 'DENY', v_root);

    v_failed := FALSE;
    BEGIN
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_seller, 'can_export_reports', 'GRANT', v_admin);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION
            'TEST 21 UĞURSUZ: DENY edilmiş flag hələ də ötürülə bilir!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 21 ✓ DENY override sahibliyi ləğv edir';

    -- =====================================================================
    -- TEST 22: VAXTI KEÇMİŞ override sahiblik saymır
    -- =====================================================================
    DECLARE
        v_expired_flag TEXT := 'can_manage_fine_types';  -- Admin-də YOXDUR
    BEGIN
        INSERT INTO user_permission_overrides
            (user_id, flag_code, effect, granted_by, expires_at)
        VALUES (v_admin, v_expired_flag, 'GRANT', v_root, now() - INTERVAL '1 hour');

        v_failed := FALSE;
        BEGIN
            INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
            VALUES (v_seller, v_expired_flag, 'GRANT', v_admin);
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION
                'TEST 22 UĞURSUZ: vaxtı keçmiş override sahiblik kimi sayıldı!';
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 22 ✓ vaxtı keçmiş override sahiblik vermir';

    -- =====================================================================
    -- TEST 23: ROL YOLU da bağlıdır, SEED yolu isə AÇIQ qalır
    -- =====================================================================
    -- (a) `granted_by` göstərilibsə sahiblik yoxlanılır — əks halda qadağa bir
    --     addımla yan keçilərdi ("flag-i rola qoyum, sonra rolu hədəfə verim").
    -- (b) `granted_by IS NULL` (sistem seed-i) İSTİSNADIR — §23/§24 seed-i və
    --     ilk Root bootstrap-ı məhz bu yolla yazılır; istisna olmasaydı bu
    --     faylın yuxarısındakı `seed_tenant_defaults()` çağırışı belə çökərdi.
    v_failed := FALSE;
    BEGIN
        INSERT INTO position_permissions (position_id, flag_code, granted, granted_by)
        VALUES (v_pos_seller, 'can_manage_backups', TRUE, v_admin);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION
            'TEST 23 UĞURSUZ: Admin özündə olmayan flag-i ROLA verdi!';
    END IF;

    INSERT INTO position_permissions (position_id, flag_code, granted)
    VALUES (v_pos_seller, 'can_manage_backups', TRUE);
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 23 ✓ rol yolu bağlıdır, seed yolu (granted_by IS NULL) açıqdır';

    -- =====================================================================
    -- TEST 24: DƏYİŞMƏYƏN sətrin təkrar yazılışı bloklanmır
    -- =====================================================================
    -- `EmployeeRepository._sync_overrides()` işçinin HƏR yazılışında bütün
    -- override sətirlərini yenidən UPSERT edir. Sahiblik yoxlaması ÜÇÜNCÜ
    -- şəxsin (verənin) sonrakı vəziyyətindən asılı olduğu üçün istisna
    -- olmasaydı, verənin flag-i geri alındıqdan sonra HƏMİN İŞÇİNİN ADINI
    -- REDAKTƏ ETMƏK belə mümkün olmazdı. Aşağıdakı UPSERT `_sync_overrides()`
    -- sorğusunun hərfi surətidir.
    DECLARE
        v_kept_flag TEXT := 'can_view_employee_reports';  -- TEST 7-də verilib
    BEGIN
        -- Verənin (Admin) sahibliyi ləğv olunur
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_admin, v_kept_flag, 'DENY', v_root);

        -- Eyni sətrin təkrar yazılışı — YENİ səlahiyyət qərarı deyil
        INSERT INTO user_permission_overrides
            (user_id, flag_code, effect, granted_by, expires_at)
        VALUES (v_seller, v_kept_flag, 'GRANT', v_admin, NULL)
        ON CONFLICT (user_id, flag_code) DO UPDATE SET
            effect     = EXCLUDED.effect,
            granted_by = EXCLUDED.granted_by,
            expires_at = EXCLUDED.expires_at;

        -- Mənfi nəzarət: YENİ flag isə hələ də bloklanır
        v_failed := FALSE;
        BEGIN
            INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
            VALUES (v_seller, 'can_manage_work_modes', 'GRANT', v_admin);
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION
                'TEST 24 UĞURSUZ: idempotentlik istisnası YENİ grant-ı da buraxdı!';
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 24 ✓ eyni sətrin təkrar yazılışı keçir, yeni grant keçmir';

    -- =====================================================================
    -- TEST 25: YARIŞ QAPAĞI — bir icazəyə İKİ diri AUTO_DELAY cəriməsi OLMAZ
    -- =====================================================================
    -- Miqrasiya 015. Tətbiq qatında sətir kilidi var, lakin kilid yalnız BİR
    -- tranzaksiya daxilində işləyir; iki paralel proses (və ya ekranı yan
    -- keçən skript) üçün yeganə etibarlı qapaq DB indeksidir.
    DECLARE
        v_leave  UUID;
        v_fine_1 UUID;
    BEGIN
        INSERT INTO leave_requests
            (tenant_id, employee_id, store_id, requested_time, actual_return_time,
             verified_at, verified_by, status, requested_minutes, delay_minutes,
             total_minutes)
        VALUES (v_tenant, v_seller, v_store, now() - INTERVAL '2 hours',
                now() - INTERVAL '1 hour', now() - INTERVAL '1 hour', v_root,
                'VERIFIED', 60, 30, 120)
        RETURNING id INTO v_leave;

        INSERT INTO fines
            (tenant_id, employee_id, store_id, source, leave_request_id, amount, status)
        VALUES (v_tenant, v_seller, v_store, 'AUTO_DELAY', v_leave, 15.00, 'PENDING_REVIEW')
        RETURNING id INTO v_fine_1;

        v_failed := FALSE;
        BEGIN
            INSERT INTO fines
                (tenant_id, employee_id, store_id, source, leave_request_id, amount, status)
            VALUES (v_tenant, v_seller, v_store, 'AUTO_DELAY', v_leave, 15.00,
                    'PENDING_REVIEW');
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION
                'TEST 25 UĞURSUZ: eyni icazə sorğusuna İKİNCİ diri AUTO_DELAY '
                'cəriməsi yarandı — ikiqat pul kəsintisi mümkündür!';
        END IF;

        -- =================================================================
        -- TEST 26: KOMPENSASİYADAN SONRA TƏKRAR TƏSDİQ BLOKLANMIR
        -- =================================================================
        -- ⚠️ İndeksin ən incə şərti. Saga kompensasiyası cəriməni `REVERSED`
        -- edir (məbləğ 0.00, qeyd silinmir). İndeks ölü sətri də saysaydı,
        -- işçinin həmin STEP 3-ü təkrar təsdiqlətməsi ƏBƏDİ bloklanardı.
        --
        -- Aşağıdakı UPDATE `Fine.discard_in_review()`-un hərfi qarşılığıdır:
        -- `published_at` NULL QALIR, çünki cərimə heç vaxt işçiyə görünməyib
        -- (bu, `chk_fine_published`-in 015-dəki istisnasını da yoxlayır).
        UPDATE fines
           SET status          = 'REVERSED',
               amount          = 0.00,
               reversed_by     = v_root,
               reversed_at     = now(),
               reversal_reason = 'Saga kompensasiyası — icazə təsdiqi geri qaytarıldı'
         WHERE id = v_fine_1;

        BEGIN
            INSERT INTO fines
                (tenant_id, employee_id, store_id, source, leave_request_id, amount, status)
            VALUES (v_tenant, v_seller, v_store, 'AUTO_DELAY', v_leave, 15.00,
                    'PENDING_REVIEW');
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION
                'TEST 26 UĞURSUZ: REVERSED sətir indeks yerini tutur — təkrar '
                'təsdiq əbədi bloklanıb! (%)', SQLERRM;
        END;
    END;
    v_passed := v_passed + 2;
    RAISE NOTICE 'TEST 25 ✓ ikinci diri AUTO_DELAY cəriməsi bloklandı';
    RAISE NOTICE 'TEST 26 ✓ REVERSED sətir təkrar təsdiqi bloklamır';

    -- =====================================================================
    -- TEST 27: BİR İŞÇİYƏ EYNİ ANDA İKİ AÇIQ İCAZƏ OLMAZ
    -- =====================================================================
    -- `uq_leave_one_open_per_employee`. STEP 1-in cüt kliki use case-də
    -- `find_open_for_employee()` ilə yoxlanılır, lakin yoxlama ilə INSERT
    -- arasında pəncərə var — yarışı məhz bu indeks udur. Repository həmin
    -- rəddi `OperationNotPermittedError`-a çevirir (xam `UniqueViolation`
    -- istifadəçiyə çatmır).
    BEGIN
        INSERT INTO leave_requests
            (tenant_id, employee_id, store_id, requested_time, status, requested_minutes)
        VALUES (v_tenant, v_manager, v_store, now(), 'OUTSIDE', 60);

        v_failed := FALSE;
        BEGIN
            INSERT INTO leave_requests
                (tenant_id, employee_id, store_id, requested_time, status, requested_minutes)
            VALUES (v_tenant, v_manager, v_store, now(), 'OUTSIDE', 60);
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION
                'TEST 27 UĞURSUZ: işçiyə eyni anda İKİNCİ açıq icazə yaradıldı!';
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 27 ✓ ikinci açıq icazə sorğusu bloklandı';

    -- =====================================================================
    -- TEST 28: TIMEOUT_ESCALATED də AÇIQ sayılır (domen paritetı)
    -- =====================================================================
    -- Miqrasiya 016. `LeaveStatus.is_open` üç statusu əhatə edir; indeks isə
    -- yalnız ikisini tuturdu, yəni "45 dəqiqə gözlə, sonra istədiyin qədər
    -- icazə aç" yolu DB səviyyəsində açıq qalırdı.
    BEGIN
        -- TEST 27-nin açıq sorğusu eskalasiyaya keçir (STEP 2 timeout-u).
        UPDATE leave_requests
           SET status = 'TIMEOUT_ESCALATED', escalated_at = now()
         WHERE employee_id = v_manager AND status = 'OUTSIDE';

        v_failed := FALSE;
        BEGIN
            INSERT INTO leave_requests
                (tenant_id, employee_id, store_id, requested_time, status, requested_minutes)
            VALUES (v_tenant, v_manager, v_store, now(), 'OUTSIDE', 60);
        EXCEPTION WHEN OTHERS THEN
            v_failed := TRUE;
        END;
        IF NOT v_failed THEN
            RAISE EXCEPTION
                'TEST 28 UĞURSUZ: TIMEOUT_ESCALATED icazənin üstündən ikinci '
                'açıq icazə yaradıldı — timeout icazə limitini yan keçir!';
        END IF;

        -- Mənfi nəzarət: sorğu HƏQİQƏTƏN bağlandıqda yeni icazə mümkündür,
        -- əks halda indeks işçini əbədi bloklayardı.
        UPDATE leave_requests
           SET status = 'CANCELLED'
         WHERE employee_id = v_manager AND status = 'TIMEOUT_ESCALATED';

        INSERT INTO leave_requests
            (tenant_id, employee_id, store_id, requested_time, status, requested_minutes)
        VALUES (v_tenant, v_manager, v_store, now(), 'OUTSIDE', 60);
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 28 ✓ TIMEOUT_ESCALATED açıq sayılır, CANCELLED isə yox';

    -- =====================================================================
    -- TEST 29: ETİRAZ PƏNCƏRƏSİ NƏŞRDƏN BAŞLAYIR
    -- =====================================================================
    -- Miqrasiya 016. Köhnə trigger sütunu INSERT anında `now() + 72h` ilə
    -- doldururdu; cərimə icmalda bir həftə qalsaydı işçi onu GÖRDÜYÜ gün
    -- etiraz müddəti bitmiş olardı (bölmə 4 — "ƏN VACİB DETAL").
    DECLARE
        v_leave_2  UUID;
        v_fine_2   UUID;
        v_window   TIMESTAMPTZ;
        v_pub_at   TIMESTAMPTZ := now();
    BEGIN
        INSERT INTO leave_requests
            (tenant_id, employee_id, store_id, requested_time, actual_return_time,
             verified_at, verified_by, status, requested_minutes, delay_minutes,
             total_minutes)
        VALUES (v_tenant, v_admin, v_store, now() - INTERVAL '11 days',
                now() - INTERVAL '11 days', now() - INTERVAL '11 days', v_root,
                'VERIFIED', 60, 30, 120)
        RETURNING id INTO v_leave_2;

        -- (a) İcmalda gözləyən cərimə: sayğac HƏLƏ BAŞLAMIR.
        INSERT INTO fines
            (tenant_id, employee_id, store_id, source, leave_request_id, amount,
             status, fine_date)
        VALUES (v_tenant, v_admin, v_store, 'AUTO_DELAY', v_leave_2, 15.00,
                'PENDING_REVIEW', (now() - INTERVAL '10 days')::DATE)
        RETURNING id INTO v_fine_2;

        SELECT appeal_window_closes_at INTO v_window FROM fines WHERE id = v_fine_2;
        IF v_window IS NOT NULL THEN
            RAISE EXCEPTION
                'TEST 29 UĞURSUZ: nəşr olunmamış cərimədə etiraz pəncərəsi '
                'açıldı (%) — sayğac yaradılışdan sayılır!', v_window;
        END IF;

        -- (b) Nəşrdən sonra pəncərə MƏHZ `published_at`-dan hesablanır.
        UPDATE fines
           SET status       = 'PUBLISHED',
               published_at = v_pub_at,
               reviewed_by  = v_root
         WHERE id = v_fine_2;

        SELECT appeal_window_closes_at INTO v_window FROM fines WHERE id = v_fine_2;
        IF v_window IS NULL THEN
            RAISE EXCEPTION
                'TEST 29 UĞURSUZ: nəşrdən sonra etiraz pəncərəsi açılmadı!';
        END IF;
        IF v_window <> v_pub_at + INTERVAL '72 hours' THEN
            RAISE EXCEPTION
                'TEST 29 UĞURSUZ: pəncərə nəşrdən yox, başqa andan sayılıb (% <> %)',
                v_window, v_pub_at + INTERVAL '72 hours';
        END IF;

        -- =================================================================
        -- TEST 30: `PENDING_REVIEW` cərimə EXPORT-a DÜŞMÜR
        -- =================================================================
        -- Bölmə 6 (hüquqi risk): işçi cəriməni nə görüb, nə də etiraz hüququ
        -- alıb. `v_exportable_fines` bu şərti onsuz da tətbiq edirdi;
        -- repository sorğusu isə yalnız `status <> 'REVERSED'` yoxlayırdı —
        -- test hər iki qatın EYNİ cavabı verdiyini təsbit edir.
        UPDATE fines
           SET status                  = 'PENDING_REVIEW',
               published_at            = NULL,
               appeal_window_closes_at = NULL
         WHERE id = v_fine_2;

        IF EXISTS (SELECT 1 FROM v_exportable_fines WHERE id = v_fine_2) THEN
            RAISE EXCEPTION
                'TEST 30 UĞURSUZ: PENDING_REVIEW cərimə export siyahısına düşdü!';
        END IF;

        -- Nəşr olunmuş, lakin pəncərəsi HƏLƏ AÇIQ cərimə də düşmür.
        UPDATE fines
           SET status = 'PUBLISHED', published_at = now(), reviewed_by = v_root
         WHERE id = v_fine_2;
        IF EXISTS (SELECT 1 FROM v_exportable_fines WHERE id = v_fine_2) THEN
            RAISE EXCEPTION
                'TEST 30 UĞURSUZ: pəncərəsi açıq cərimə export-a düşdü!';
        END IF;

        -- Pəncərə bağlandıqdan sonra DÜŞÜR (mənfi nəzarət: filtr həddindən
        -- artıq sərt deyil).
        UPDATE fines
           SET appeal_window_closes_at = now() - INTERVAL '1 second'
         WHERE id = v_fine_2;
        IF NOT EXISTS (SELECT 1 FROM v_exportable_fines WHERE id = v_fine_2) THEN
            RAISE EXCEPTION
                'TEST 30 UĞURSUZ: pəncərəsi bağlanmış cərimə export-dan çıxdı!';
        END IF;
    END;
    v_passed := v_passed + 2;
    RAISE NOTICE 'TEST 29 ✓ etiraz pəncərəsi nəşrdən (published_at) başlayır';
    RAISE NOTICE 'TEST 30 ✓ PENDING_REVIEW export-a düşmür, PUBLISHED+bağlı pəncərə düşür';

    RAISE NOTICE '';
    RAISE NOTICE '===========================================';
    RAISE NOTICE 'BÜTÜN GUARD TESTLƏRİ UĞURLU: %/30', v_passed;
    RAISE NOTICE '===========================================';

    -- Test məlumatlarının təmizlənməsi
    -- (audit_logs sətirləri QƏSDƏN qalır — append-only, FK yoxdur)
    --
    -- `fines` və `leave_requests` AÇIQ SİLİNİR, tenant kaskadına buraxılmır:
    -- `fines.leave_request_id` üzərindəki FK `NO ACTION`-dır (DEFERRABLE
    -- DEYİL), yəni tək bir `DELETE license_tenants` iki kaskadın hansının
    -- əvvəl işləməsindən asılı olardı. Açıq sıra bu sualı tamamilə aradan
    -- qaldırır — test təmizliyi DB daxili sıraya güvənməməlidir.
    DELETE FROM fines WHERE tenant_id = v_tenant;
    DELETE FROM leave_requests WHERE tenant_id = v_tenant;
    DELETE FROM license_tenants WHERE tenant_id = v_tenant;
END
$$;
