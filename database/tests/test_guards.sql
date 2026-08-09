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
        v_closes    TIMESTAMPTZ;
    BEGIN
        INSERT INTO fine_types (tenant_id, name_az, standard_amount)
        VALUES (v_tenant, 'Test Cərimə Növü', 15.00)
        RETURNING id INTO v_fine_type;

        INSERT INTO fines (tenant_id, employee_id, store_id, source, fine_type_id,
                           amount, issued_by, photo_evidence_url)
        VALUES (v_tenant, v_seller, v_store, 'MANUAL_CAMERA', v_fine_type,
                15.00, v_root, 'https://storage.test/evidence.jpg')
        RETURNING appeal_window_closes_at INTO v_closes;

        IF v_closes IS NULL
           OR v_closes < now() + INTERVAL '71 hours'
           OR v_closes > now() + INTERVAL '73 hours' THEN
            RAISE EXCEPTION
                'TEST 12 UĞURSUZ: etiraz pəncərəsi 72 saata təyin olunmadı (%)', v_closes;
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 12 ✓ etiraz pəncərəsi system_limits-dən 72 saat kimi təyin olundu';

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

    RAISE NOTICE '';
    RAISE NOTICE '===========================================';
    RAISE NOTICE 'BÜTÜN GUARD TESTLƏRİ UĞURLU: %/17', v_passed;
    RAISE NOTICE '===========================================';

    -- Test məlumatlarının təmizlənməsi
    -- (audit_logs sətirləri QƏSDƏN qalır — append-only, FK yoxdur)
    DELETE FROM license_tenants WHERE tenant_id = v_tenant;
END
$$;
