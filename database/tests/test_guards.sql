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
    v_ceo        UUID;
    v_admin      UUID;
    v_manager    UUID;
    v_seller     UUID;
    v_failed     BOOLEAN;
    v_message    TEXT;
    v_passed     INTEGER := 0;

    -- TEST 35-39 (SEC-01/SEC-05, terminal PIN throttle trigger) üçün:
    v_tenant2        UUID;
    v_store2         UUID;
    v_machine_a      TEXT := 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    v_machine_b      TEXT := 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
    v_machine_c      TEXT := 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
    v_failed_count   INTEGER;
    v_locked_until   TIMESTAMPTZ;
    v_window_started TIMESTAMPTZ;
    v_now            TIMESTAMPTZ := now();
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

    -- `CEO` istifadəçisi TEST 31/32 üçündür: Root/CEO prioritet ayrılığından
    -- sonra CEO → Root qadağası İYERARXİYADAN gəlir və bu, DB tərəfində də
    -- yoxlanılmalıdır (CLAUDE.md §5 — qayda İKİ yerdədir).
    INSERT INTO employees (tenant_id, store_id, position_id, first_name, last_name,
                           username, password_hash)
    VALUES (v_tenant, v_store, v_pos_ceo, 'Test', 'Ceo', 'guard.ceo', 'argon2-hash')
    RETURNING id INTO v_ceo;

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
    -- TEST 6: HIERARCHY GUARD — Admin (priority 2) Root-a (0) toxuna bilməz
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
    -- TEST 7: MÜSBƏT HAL — Admin Satıcı-ya (priority 4) icazə verə bilər
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
    --
    -- T2 (DEEP-GAP dövrə auditi): nümunə flag `can_manage_backups`-dan
    -- `can_manage_fine_types`-a DƏYİŞDİRİLİB — `can_manage_backups`-ın
    -- hardlock-u `ROOT_CEO`-ya (2) qaldırılıb (migrations/078), ona görə
    -- (a)-dakı INSERT artıq `enforce_grantor_owns_flag()`-dan ƏVVƏL
    -- `enforce_permission_hardlock()`-a ilişərdi (v_pos_seller nə ROOT, nə
    -- CEO-dur) — DOĞRU sədddən YANLIŞ SƏBƏBLƏ keçərdi. Daha PİSİ: (b)-dəki
    -- "seed yolu AÇIQDIR" iddiası `enforce_permission_hardlock()` `granted_
    -- by`-a heç baxmadığı üçün TAMAMİLƏ PARÇALANARDI. `can_manage_fine_types`
    -- hardlock=0-dır (schema.sql:2756) və Admin-in defolt flag dəstində
    -- YOXDUR (§23) — TEST-in orijinal fərziyyəsini saxlayır: yeganə maneə
    -- `enforce_grantor_owns_flag()` olsun.
    v_failed := FALSE;
    BEGIN
        INSERT INTO position_permissions (position_id, flag_code, granted, granted_by)
        VALUES (v_pos_seller, 'can_manage_fine_types', TRUE, v_admin);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION
            'TEST 23 UĞURSUZ: Admin özündə olmayan flag-i ROLA verdi!';
    END IF;

    INSERT INTO position_permissions (position_id, flag_code, granted)
    VALUES (v_pos_seller, 'can_manage_fine_types', TRUE);
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

    -- =====================================================================
    -- TEST 31: PRİORİTET MODELİ — `Root` TƏK BAŞINA 0-dadır (miqrasiya 048)
    -- =====================================================================
    -- Domen qarşılığı `RolePriority` + `SystemRole.default_priority`.
    -- Seed ilə domen ayrılsaydı, `mappers.position_from_row` bazadakı ədədi
    -- BAŞQA pilləyə çevirərdi: ekran bir şey göstərər, guard başqa qərar
    -- verərdi. Ona görə ədədlər burada ADBAAD təsbit olunur.
    IF (SELECT priority FROM positions WHERE id = v_pos_root)   <> 0
       OR (SELECT priority FROM positions WHERE id = v_pos_ceo)    <> 1
       OR (SELECT priority FROM positions WHERE id = v_pos_admin)  <> 2
       OR (SELECT priority FROM positions WHERE id = v_pos_hr)     <> 3
       OR (SELECT priority FROM positions WHERE id = v_pos_store)  <> 3
       OR (SELECT priority FROM positions WHERE id = v_pos_camera) <> 3
       OR (SELECT priority FROM positions WHERE id = v_pos_seller) <> 4 THEN
        RAISE EXCEPTION
            'TEST 31 UĞURSUZ: rol prioritetləri Root=0/CEO=1/Admin=2/'
            'operativ=3/Satıcı=4 modelinə uyğun deyil (bölmə 3, SEC-019)';
    END IF;

    IF (SELECT COUNT(*) FROM positions
         WHERE tenant_id = v_tenant AND priority = 0) <> 1 THEN
        RAISE EXCEPTION
            'TEST 31 UĞURSUZ: prioritet 0 pilləsində birdən çox rol var — '
            '`Root` TƏK BAŞINA ən üst pillədə olmalıdır';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 31 ✓ Root=0 (tək), CEO=1, Admin=2, operativ=3, Satıcı=4';

    -- =====================================================================
    -- TEST 32: CEO `Root` istifadəçisinin icazəsinə TOXUNA BİLMİR
    -- =====================================================================
    -- Bu, TEST 6-nın (Admin → Root) DAHA DAR variantıdır və prioritet
    -- ayrılığının əsas nəticəsidir. Köhnə modeldə (Root=CEO=0) qadağa
    -- BƏRABƏR-pillə şərtindən çıxırdı; indi `0 < 1`, yəni qadağa
    -- iyerarxiyanın ÖZÜNDƏNDİR. Mesaj yoxlaması vacibdir: yazı başqa
    -- trigger-in (hardlock/sahiblik) səbəbindən rədd edilsəydi, test
    -- yanlış olaraq "keçmiş" sayılardı.
    --
    -- `DENY` seçilir ki, `enforce_grantor_owns_flag` erkən çıxsın —
    -- TEST 6 ilə eyni naxış.
    v_failed := FALSE;
    v_message := '';
    BEGIN
        INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
        VALUES (v_root, 'can_export_reports', 'DENY', v_ceo);
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
        v_message := SQLERRM;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 32 UĞURSUZ: CEO Root-un icazəsinə toxundu!';
    END IF;
    IF v_message NOT LIKE '%STRICT HIERARCHY GUARD%' THEN
        RAISE EXCEPTION
            'TEST 32 UĞURSUZ: yazı bloklandı, lakin iyerarxiyaya GÖRƏ YOX (%)', v_message;
    END IF;

    -- MÜSBƏT HAL: eyni CEO ondan CİDDİ ŞƏKİLDƏ aşağı olan Admin-ə toxuna bilir
    -- (guard-ın "hər şeyi bloklamadığının" sübutu).
    INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
    VALUES (v_admin, 'can_view_employee_reports', 'DENY', v_ceo);

    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 32 ✓ CEO → Root bloklandı, CEO → Admin işləyir';

    -- =====================================================================
    -- TEST 33: AKTİV ÜZ-İSTİSNASI VARKƏN `DUAL_CONTROL` SÖNDÜRÜLƏ BİLMƏZ
    -- =====================================================================
    -- SEC-020 / miqrasiya 051. `facecontrol.md` bənd 14 PIN-only istisnasının
    -- YEGANƏ əvəzləyicisi kimi dual-control axınını göstərir. Həmin modul adi
    -- toggle olsaydı, bir `UPDATE` istisnalı işçini kompensasiyasız qoyardı.
    --
    -- Domen qarşılığı `RootControlUseCase._require_no_dependent_guarantee`;
    -- bu blok qaydanın DB yarısını yoxlayır (ekranı yan keçən skript).
    INSERT INTO face_control_exemptions
           (tenant_id, employee_id, granted_by, reason, expires_at)
    VALUES (v_tenant, v_seller, v_root,
            'Tibbi arayış — üz nahiyəsində sarğı var', now() + INTERVAL '30 days');

    v_failed := FALSE;
    v_message := '';
    BEGIN
        UPDATE feature_toggles SET is_enabled = FALSE
         WHERE tenant_id = v_tenant AND module_key = 'DUAL_CONTROL';
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
        v_message := SQLERRM;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION
            'TEST 33 UĞURSUZ: aktiv üz-istisnası varkən DUAL_CONTROL söndürüldü!';
    END IF;
    IF v_message NOT LIKE '%KOMPENSASİYA KİLİDİ%' THEN
        RAISE EXCEPTION
            'TEST 33 UĞURSUZ: yazı bloklandı, lakin kompensasiya kilidinə GÖRƏ YOX (%)',
            v_message;
    END IF;

    -- MÜSBƏT HAL: BAŞQA modul sərbəst söndürülür (kilid ümumi deyil, dardır).
    UPDATE feature_toggles SET is_enabled = FALSE
     WHERE tenant_id = v_tenant AND module_key = 'SHIFT_SWAP';

    -- KİLİD ƏBƏDİ DEYİL: istisna ləğv olunandan sonra söndürmə İŞLƏYİR.
    -- Bu yoxlama olmasa, guard "hər şeyi bloklayan" versiyaya sürüşə bilər və
    -- Root öz sistemindən kilidlənərdi.
    UPDATE face_control_exemptions
       SET status = 'REVOKED', revoked_by = v_root, revoked_at = now(),
           revoke_reason = 'Guard testi — kilidin açıla bildiyi yoxlanılır'
     WHERE tenant_id = v_tenant AND employee_id = v_seller;

    UPDATE feature_toggles SET is_enabled = FALSE
     WHERE tenant_id = v_tenant AND module_key = 'DUAL_CONTROL';

    IF (SELECT is_enabled FROM feature_toggles
         WHERE tenant_id = v_tenant AND module_key = 'DUAL_CONTROL') THEN
        RAISE EXCEPTION
            'TEST 33 UĞURSUZ: istisna ləğv edildikdən sonra da söndürmə keçmədi — '
            'kilid əbədi olub';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 33 ✓ aktiv istisna DUAL_CONTROL-u kilidləyir, ləğvdən sonra açılır';

    -- =====================================================================
    -- TEST 34: `DUAL_CONTROL` SÖNÜKDÜRSƏ YENİ AKTİV İSTİSNA YAZILA BİLMƏZ
    -- =====================================================================
    -- İnvariantın SİMMETRİK yarısı. TEST 33-dən sonra modul söndürülü
    -- vəziyyətdədir — yəni bu blok məhz «sıranı dəyişdirmək» hücumunu yoxlayır:
    -- əvvəlcə modulu söndür, sonra istisna ver.
    v_failed := FALSE;
    v_message := '';
    BEGIN
        INSERT INTO face_control_exemptions
               (tenant_id, employee_id, granted_by, reason, expires_at)
        VALUES (v_tenant, v_manager, v_root,
                'Tibbi arayış — üz nahiyəsində sarğı var', now() + INTERVAL '10 days');
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
        v_message := SQLERRM;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION
            'TEST 34 UĞURSUZ: kompensasiya söndürülü ikən yeni aktiv istisna yazıldı!';
    END IF;
    IF v_message NOT LIKE '%KOMPENSASİYA KİLİDİ%' THEN
        RAISE EXCEPTION
            'TEST 34 UĞURSUZ: yazı bloklandı, lakin kompensasiya kilidinə GÖRƏ YOX (%)',
            v_message;
    END IF;

    -- YOL AÇIQ QALIR: modul yenidən aktivləşdirildikdə istisna normal verilir.
    -- Bu yoxlama olmadan guard "istisna mexanizmini tamamilə söndürən" bir
    -- versiyaya sürüşə bilərdi və tibbi/fiziki səbəbli işçi heç vaxt istisna
    -- ala bilməzdi — qoruma öz məqsədini əvəz edərdi.
    UPDATE feature_toggles SET is_enabled = TRUE
     WHERE tenant_id = v_tenant AND module_key = 'DUAL_CONTROL';

    INSERT INTO face_control_exemptions
           (tenant_id, employee_id, granted_by, reason, expires_at)
    VALUES (v_tenant, v_manager, v_root,
            'Tibbi arayış — üz nahiyəsində sarğı var', now() + INTERVAL '10 days');

    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 34 ✓ sönük kompensasiya yeni istisnanı bloklayır, açıq modul buraxır';

    -- =========================================================================
    -- TEST 35-39: TERMİNAL PIN THROTTLE TRIGGER-İ (SEC-01/SEC-05, migrations/075)
    -- =========================================================================
    -- `enforce_store_pin_throttle_lockout()` pəncərə/kilid ARİFMETİKASINI DB
    -- TRİGGER-İNDƏ aparır (TIME-1) — Python tərəfindəki testlər (`tests/unit/
    -- test_authentication.py`) sahtə repo ilə işlədiyi üçün bu riyaziyyatı
    -- HEÇ VAXT ÖRTMÜR. Bu testlər `qa`-nın tapdığı boşluğu bağlayır (dövrə 3).
    --
    -- Mövcud `v_tenant`/`v_store` YENİDƏN İSTİFADƏ OLUNUR (TEST 35-38) —
    -- `store_pin_throttle` yuxarıdakı 34 testin TOXUNMADIĞI TAMAMİLƏ AYRI
    -- cədvəldir, çarpaz çirklənmə riski yoxdur. YALNIZ TEST 39 (çox-kirayəçi
    -- təcridi) üçün AYRICA `v_tenant2`/`v_store2` yaradılır.
    --
    -- "VAXT KEÇMƏSİ" SİMULYASİYASI: `KIOSK_STORE_PIN_LOCKOUT_MINUTES` defolt
    -- 15-dir və `make_interval(mins => ...)` YALNIZ TAM ədəd qəbul edir —
    -- real vaxt gözləmək (60+ saniyə) testi yavaş/kövrək edərdi. Əvəzinə
    -- `ALTER TABLE ... DISABLE/ENABLE TRIGGER` ilə sətri BİRBAŞA (trigger-i
    -- keçərək) keçmişə aid dəyərlərlə saxtalaşdırırıq.
    --
    -- DƏQİQ SƏRHƏD (`now() = locked_until`, TEST 37): Postgres-də `now()`
    -- TRANZAKSİYA DAXİLİNDƏ SABİTDİR (`clock_timestamp()`-dən FƏRQLİ) —
    -- `locked_until`-u BİRBAŞA `now()`-a bərabər təyin etsək, trigger-in
    -- İÇİNDƏKİ `now()` çağırışı da EYNİ dəyəri görür — real vaxt gözləməyə
    -- ehtiyac yoxdur.

    -- TEST tenant-ın PIN həddini 3-ə ENDİRİRİK (defolt 20-dir) ki, TEST 35
    -- 20 dəfə INSERT/UPDATE etmədən DETERMİNİST işləsin — riyaziyyat hər iki
    -- ədədlə EYNİDİR, sınanan MƏNTİQ (hədd-1/hədd/hədd+1) ədəddən asılı deyil.
    UPDATE system_limits SET limit_value = '3'
     WHERE tenant_id = v_tenant AND limit_key = 'KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS';

    -- =====================================================================
    -- TEST 35: HƏDD-1 → kilidlənmir; HƏDD → kilidlənir; HƏDD+1 → DONUR
    -- =====================================================================
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_a, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1,
        store_id     = EXCLUDED.store_id
    RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
    IF v_failed_count <> 1 OR v_locked_until IS NOT NULL THEN
        RAISE EXCEPTION 'TEST 35a UĞURSUZ: cəhd 1-də failed_count=% locked_until=%',
            v_failed_count, v_locked_until;
    END IF;

    -- Cəhd 2 (HƏDD-1, hədd=3)
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_a, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1,
        store_id     = EXCLUDED.store_id
    RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
    IF v_failed_count <> 2 OR v_locked_until IS NOT NULL THEN
        RAISE EXCEPTION 'TEST 35b UĞURSUZ (hədd-1): failed_count=% locked_until=% (kilidlənmiş olmamalı idi)',
            v_failed_count, v_locked_until;
    END IF;

    -- Cəhd 3 (HƏDD, hədd=3) — İNDİ kilidlənməlidir
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_a, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1,
        store_id     = EXCLUDED.store_id
    RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
    IF v_failed_count <> 3 OR v_locked_until IS NULL THEN
        RAISE EXCEPTION 'TEST 35c UĞURSUZ (hədd): failed_count=% locked_until=% (kilidlənməli idi)',
            v_failed_count, v_locked_until;
    END IF;

    -- Cəhd 4 (HƏDD+1, ARTIQ kilidli) — sayğac DONMALI, locked_until UZANMAMALI.
    -- `pg_sleep()` LAZIM DEYİL: `now()` bu TRANZAKSİYA daxilində SABİTDİR —
    -- `locked_until` bir addım əvvəl elə HƏMİN `now()` + interval kimi
    -- hesablanıb, ona görə `locked_until > now()` HƏR HALDA TRİVİAL doğrudur.
    DECLARE
        v_locked_until_before TIMESTAMPTZ := v_locked_until;
    BEGIN
        INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
        VALUES (v_tenant, v_machine_a, v_store, 1)
        ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
            failed_count = store_pin_throttle.failed_count + 1,
            store_id     = EXCLUDED.store_id
        RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
        IF v_failed_count <> 3 THEN
            RAISE EXCEPTION 'TEST 35d UĞURSUZ (hədd+1): sayğac DONMADI, failed_count=% (3 olmalı idi)',
                v_failed_count;
        END IF;
        IF v_locked_until <> v_locked_until_before THEN
            RAISE EXCEPTION 'TEST 35d UĞURSUZ (hədd+1): locked_until UZANDI (əvvəl=%, indi=%)',
                v_locked_until_before, v_locked_until;
        END IF;
    END;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 35 ✓ hədd-1 kilidsiz, hədd kilidli, hədd+1 donmuş (sayğac=3, kilid sabit)';

    -- =====================================================================
    -- TEST 36: PƏNCƏRƏNİN BİTMƏSİ İLƏ SIFIRLANMA (`locked_until` keçib)
    -- =====================================================================
    ALTER TABLE store_pin_throttle DISABLE TRIGGER trg_store_pin_throttle_lockout;
    UPDATE store_pin_throttle
       SET window_started_at = v_now - INTERVAL '20 minutes',
           locked_until      = v_now - INTERVAL '1 second'
     WHERE tenant_id = v_tenant AND machine_key = v_machine_a;
    ALTER TABLE store_pin_throttle ENABLE TRIGGER trg_store_pin_throttle_lockout;

    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_a, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1,
        store_id     = EXCLUDED.store_id
    RETURNING failed_count, locked_until, window_started_at
      INTO v_failed_count, v_locked_until, v_window_started;
    IF v_failed_count <> 1 OR v_locked_until IS NOT NULL THEN
        RAISE EXCEPTION
            'TEST 36 UĞURSUZ: pəncərə bitdikdən sonra sıfırlanmadı (failed_count=%, locked_until=%)',
            v_failed_count, v_locked_until;
    END IF;
    IF v_window_started < v_now THEN
        RAISE EXCEPTION 'TEST 36 UĞURSUZ: window_started_at server vaxtına YENİLƏNMƏDİ (%)',
            v_window_started;
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 36 ✓ pəncərə (locked_until keçib) bitəndə sayğac 1-ə sıfırlanır';

    -- =====================================================================
    -- TEST 37: DƏQİQ SƏRHƏD — `now() = locked_until` ARTIQ "bloklanmayıb"
    --   sayılmalıdır (domendəki `is_locked()`-in `now < locked_until` SƏRT
    --   şərti ilə TUTARLI, bax miqrasiyanın "SƏRHƏD" şərhi)
    -- =====================================================================
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_b, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1, store_id = EXCLUDED.store_id;
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_b, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1, store_id = EXCLUDED.store_id;
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_b, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1, store_id = EXCLUDED.store_id
    RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
    IF v_locked_until IS NULL THEN
        RAISE EXCEPTION 'TEST 37 SETUP UĞURSUZ: v_machine_b kilidlənmədi (failed_count=%)', v_failed_count;
    END IF;

    -- `locked_until`-u DƏQİQ `now()`-a (tranzaksiyanın SABİT `now()`-u) təyin
    -- edirik — trigger-in İÇİNDƏKİ `now()` DƏ EYNİ dəyəri görəcək.
    ALTER TABLE store_pin_throttle DISABLE TRIGGER trg_store_pin_throttle_lockout;
    UPDATE store_pin_throttle
       SET locked_until = now(), window_started_at = now() - INTERVAL '2 minutes'
     WHERE tenant_id = v_tenant AND machine_key = v_machine_b;
    ALTER TABLE store_pin_throttle ENABLE TRIGGER trg_store_pin_throttle_lockout;

    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_b, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1, store_id = EXCLUDED.store_id
    RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
    IF v_failed_count <> 1 OR v_locked_until IS NOT NULL THEN
        RAISE EXCEPTION
            'TEST 37 UĞURSUZ: now()=locked_until anında "hələ kilidlidir" sayıldı (failed_count=%, locked_until=%) — domendəki is_locked() (now < locked_until, SƏRT) ilə TUTARSIZ olardı',
            v_failed_count, v_locked_until;
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 37 ✓ now() = locked_until anında DB DƏ "bloklanmayıb" qərarına gəlir (domenlə tutarlı sərhəd)';

    -- =====================================================================
    -- TEST 38: `update_last_seen_store`-un EKVİVALENTİ SAYĞACA TOXUNMUR
    -- =====================================================================
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_c, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1, store_id = EXCLUDED.store_id;
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant, v_machine_c, v_store, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1, store_id = EXCLUDED.store_id
    RETURNING failed_count INTO v_failed_count;
    IF v_failed_count <> 2 THEN
        RAISE EXCEPTION 'TEST 38 SETUP UĞURSUZ: failed_count=% (2 olmalı idi)', v_failed_count;
    END IF;

    -- `update_last_seen_store()`-un EKVİVALENTİ: `failed_count` SET
    -- siyahısında HEÇ YOXDUR — bax `pin_throttle_repository.py`.
    UPDATE store_pin_throttle
       SET store_id = v_store
     WHERE tenant_id = v_tenant AND machine_key = v_machine_c
     RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
    IF v_failed_count <> 2 OR v_locked_until IS NOT NULL THEN
        RAISE EXCEPTION
            'TEST 38 UĞURSUZ: store_id-yeniləməsi sayğaca TOXUNDU (failed_count=%, locked_until=%)',
            v_failed_count, v_locked_until;
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 38 ✓ store_id-yalnız yeniləmə sayğacı/kiliddən TOXUNULMAZ saxlayır';

    -- =====================================================================
    -- TEST 39: ÇOX-KİRAYƏÇİ TƏCRİDİ — EYNİ machine_key, FƏRQLİ tenant_id
    -- =====================================================================
    INSERT INTO license_tenants (tenant_name, license_key_hash, status, company_contact_email)
    VALUES ('GUARD-TEST-THROTTLE-2', 'test', 'AKTIV', 'guard-throttle2@test.local')
    RETURNING tenant_id INTO v_tenant2;
    PERFORM seed_tenant_defaults(v_tenant2);
    INSERT INTO stores (tenant_id, code, name, brand)
    VALUES (v_tenant2, 'T-902', 'Throttle Mağaza 2', 'Yataş')
    RETURNING id INTO v_store2;

    -- v_machine_a artıq v_tenant-da KİLİDLİDİR (TEST 35-in nəticəsi). Eyni
    -- açarla v_tenant2-də YENİ, AÇIQ sətir gözlənilir.
    INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
    VALUES (v_tenant2, v_machine_a, v_store2, 1)
    ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
        failed_count = store_pin_throttle.failed_count + 1, store_id = EXCLUDED.store_id
    RETURNING failed_count, locked_until INTO v_failed_count, v_locked_until;
    IF v_failed_count <> 1 OR v_locked_until IS NOT NULL THEN
        RAISE EXCEPTION
            'TEST 39 UĞURSUZ: v_tenant-in kilidi v_tenant2-yə SIZDI (failed_count=%, locked_until=%)',
            v_failed_count, v_locked_until;
    END IF;
    -- Əks istiqamət: v_tenant-dakı sətir HƏLƏ DƏ kilidli qalmalıdır.
    SELECT failed_count, locked_until INTO v_failed_count, v_locked_until
      FROM store_pin_throttle
     WHERE tenant_id = v_tenant AND machine_key = v_machine_a;
    IF v_failed_count <> 3 OR v_locked_until IS NULL THEN
        RAISE EXCEPTION
            'TEST 39 UĞURSUZ: v_tenant-in sətri v_tenant2 yazısından SONRA dəyişdi (failed_count=%, locked_until=%)',
            v_failed_count, v_locked_until;
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 39 ✓ eyni machine_key, fərqli tenant_id → tam təcrid olunmuş sətirlər';

    -- =====================================================================
    -- TEST 40-41: DB-6 (migrations/076) — `ROOT_ONLY` FLAG-İN DELETE İLƏ
    --   GERİ ALINMASI YALNIZ ROOT TƏRƏFİNDƏN EDİLƏ BİLƏR
    -- =====================================================================
    -- `seed_tenant_defaults()` ARTIQ `v_pos_root`-a `can_manage_permissions`-i
    -- (hardlock=1) `granted_by = NULL` ilə vermişdi (§23 seed-in kopyası) —
    -- YENİ sətir INSERT etməyə EHTİYAC YOXDUR, mövcud sətri işlədirik.

    -- TEST 40: `position_permissions` — CEO (Root DEYİL) silə BİLMƏZ.
    PERFORM set_config('app.user_id', v_ceo::TEXT, TRUE);
    v_failed := FALSE;
    BEGIN
        DELETE FROM position_permissions
         WHERE position_id = v_pos_root AND flag_code = 'can_manage_permissions';
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 40a UĞURSUZ: CEO ROOT-un can_manage_permissions sətrini SİLDİ!';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM position_permissions
         WHERE position_id = v_pos_root AND flag_code = 'can_manage_permissions'
    ) THEN
        RAISE EXCEPTION 'TEST 40a UĞURSUZ: istisnaya baxmayaraq sətir artıq yoxdur!';
    END IF;

    -- Root ÖZÜ silə bilməlidir (blok "heç kim silə bilməz" demir, "yalnız
    -- Root silə bilər" deyir).
    PERFORM set_config('app.user_id', v_root::TEXT, TRUE);
    BEGIN
        DELETE FROM position_permissions
         WHERE position_id = v_pos_root AND flag_code = 'can_manage_permissions';
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'TEST 40b UĞURSUZ: Root ÖZÜ belə sətri silə bilmədi (%)', SQLERRM;
    END;
    IF EXISTS (
        SELECT 1 FROM position_permissions
         WHERE position_id = v_pos_root AND flag_code = 'can_manage_permissions'
    ) THEN
        RAISE EXCEPTION 'TEST 40b UĞURSUZ: Root sildi, amma sətir HƏLƏ mövcuddur!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 40 ✓ position_permissions: ROOT_ONLY flag-in DELETE-i yalnız Root-a icazəlidir';

    -- TEST 41: `user_permission_overrides` — EYNİ qapı fərdi override yolunda.
    INSERT INTO user_permission_overrides (user_id, flag_code, effect, granted_by)
    VALUES (v_root, 'can_manage_system_limits', 'GRANT', v_root);

    PERFORM set_config('app.user_id', v_ceo::TEXT, TRUE);
    v_failed := FALSE;
    BEGIN
        DELETE FROM user_permission_overrides
         WHERE user_id = v_root AND flag_code = 'can_manage_system_limits';
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 41a UĞURSUZ: CEO Root-un fərdi ROOT_ONLY override-ını SİLDİ!';
    END IF;

    PERFORM set_config('app.user_id', v_root::TEXT, TRUE);
    BEGIN
        DELETE FROM user_permission_overrides
         WHERE user_id = v_root AND flag_code = 'can_manage_system_limits';
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'TEST 41b UĞURSUZ: Root ÖZÜ belə override-ı silə bilmədi (%)', SQLERRM;
    END;
    IF EXISTS (
        SELECT 1 FROM user_permission_overrides
         WHERE user_id = v_root AND flag_code = 'can_manage_system_limits'
    ) THEN
        RAISE EXCEPTION 'TEST 41b UĞURSUZ: Root sildi, amma sətir HƏLƏ mövcuddur!';
    END IF;
    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 41 ✓ user_permission_overrides: EYNİ qapı fərdi override yolunda da işləyir';

    -- =====================================================================
    -- TEST 42: İ6/İ7 (DEEP-GAP dövrə auditi) — ROL SƏLAHİYYƏTLƏRİNİN
    --   İCTİMAİ VƏZİYYƏTİ. `has_*_privilege()` YALNIZ kataloqu sorğulayır —
    --   DATA TOXUNULMUR, SET ROLE lazım deyil.
    -- =====================================================================
    -- `kompasos_app` mövcud olmaya bilər (Supabase-idarəli platforma, §28
    -- şərhi) — o halda `schema.sql`-in özü GRANT/REVOKE-u ATLAYIR, bu test
    -- də EYNİ şərtlə keçir (aşağıdakı hər iki test buna görə IF-lə əhatə
    -- olunub, sadəcə v_passed artırılmır).
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kompasos_app') THEN
        -- İ6: `permission_flags` — İNSERT açıq qalır (Root `create()` yolu,
        -- `config_repositories.py::PostgresPermissionFlagRepository.create`),
        -- UPDATE/DELETE bağlıdır (Python-da HEÇ BİR `UPDATE permission_flags`
        -- çağırışı yoxdur — yoxlanılıb).
        IF NOT has_table_privilege('kompasos_app', 'permission_flags', 'INSERT') THEN
            RAISE EXCEPTION
                'TEST 42a UĞURSUZ: kompasos_app permission_flags-a İNSERT edə bilmir '
                '— Root-un create() yolu qırılıb';
        END IF;
        IF has_table_privilege('kompasos_app', 'permission_flags', 'UPDATE') THEN
            RAISE EXCEPTION
                'TEST 42b UĞURSUZ: kompasos_app permission_flags-ı HƏLƏ DƏ UPDATE edə bilir (İ6)';
        END IF;
        IF has_table_privilege('kompasos_app', 'permission_flags', 'DELETE') THEN
            RAISE EXCEPTION
                'TEST 42c UĞURSUZ: kompasos_app permission_flags-ı HƏLƏ DƏ DELETE edə bilir';
        END IF;

        -- İ7: `scheduled_job_runs` — Python tətbiqinin heç bir qanuni yolu
        -- yoxdur (əvəzinə `app_scheduled_job_runs`, migrations/036), yeganə
        -- yazan `run_scheduled_job()` indi `run_all_scheduled_jobs()`-un
        -- `SECURITY DEFINER` kontekstində işləyir.
        IF has_table_privilege('kompasos_app', 'scheduled_job_runs', 'SELECT')
        OR has_table_privilege('kompasos_app', 'scheduled_job_runs', 'INSERT')
        OR has_table_privilege('kompasos_app', 'scheduled_job_runs', 'UPDATE')
        OR has_table_privilege('kompasos_app', 'scheduled_job_runs', 'DELETE') THEN
            RAISE EXCEPTION
                'TEST 42d UĞURSUZ: kompasos_app scheduled_job_runs cədvəlinə birbaşa girişi var (İ7)';
        END IF;
        IF NOT has_function_privilege('kompasos_app', 'run_all_scheduled_jobs()', 'EXECUTE') THEN
            RAISE EXCEPTION
                'TEST 42e UĞURSUZ: xarici scheduler girişi (run_all_scheduled_jobs) bağlanıb '
                '— docs/scheduler_setup.md Variant B qırılar';
        END IF;
        IF has_function_privilege('kompasos_app', 'run_scheduled_job(text, text)', 'EXECUTE') THEN
            RAISE EXCEPTION
                'TEST 42f UĞURSUZ: kompasos_app ixtiyari SQL icra edən run_scheduled_job-u '
                'birbaşa çağıra bilir';
        END IF;
        -- `schema_migrations` (migrations/061) — reyestr tətbiq rolunun heç
        -- görmədiyi bir faktdır (bax faylın öz başlığı).
        IF has_table_privilege('kompasos_app', 'schema_migrations', 'SELECT')
        OR has_table_privilege('kompasos_app', 'schema_migrations', 'INSERT') THEN
            RAISE EXCEPTION
                'TEST 42g UĞURSUZ: kompasos_app schema_migrations reyestrinə görünürlüyə malikdir';
        END IF;

        v_passed := v_passed + 1;
        RAISE NOTICE 'TEST 42 ✓ İ6/İ7 rol səlahiyyətləri gözlənilən vəziyyətdədir';
    ELSE
        RAISE NOTICE 'TEST 42 ATLANDI: kompasos_app rolu mövcud deyil (Supabase-idarəli platforma)';
    END IF;

    -- =====================================================================
    -- TEST 43: İ5 (DEEP-GAP dövrə auditi) — mövqe ŞABLONU (`positions.
    --   tenant_id IS NULL`) kirayəçi sessiyasından UPDATE/DELETE edilə
    --   bilmir, `enforce_position_template_protection()` İKİNCİ QATI
    -- =====================================================================
    -- Owner bağlantısı RLS-dən azaddır (§27 başlığı), ona görə RLS SİYASƏTİ
    -- (`tenant_isolation_write`) BURADA TƏSDİQLƏNMİR — TEST 42-dəki
    -- `has_table_privilege` da yalnız cədvəl-səviyyəli GRANT-ı görür, RLS
    -- predikatını yox. Trigger isə HƏR KƏSƏ (owner DAXİL) tətbiq olunur,
    -- ona görə owner bağlantısında da doğrulana bilir (`enforce_append_
    -- only()`-un başlığındakı EYNİ arqument).
    PERFORM set_config('app.tenant_id', v_tenant::TEXT, TRUE);

    v_failed := FALSE;
    BEGIN
        UPDATE positions SET name_az = name_az WHERE tenant_id IS NULL AND code = 'ROOT';
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 43a UĞURSUZ: kirayəçi kontekstində şablon UPDATE edildi!';
    END IF;

    v_failed := FALSE;
    BEGIN
        DELETE FROM positions WHERE tenant_id IS NULL AND code = 'ROOT';
    EXCEPTION WHEN OTHERS THEN
        v_failed := TRUE;
    END;
    IF NOT v_failed THEN
        RAISE EXCEPTION 'TEST 43b UĞURSUZ: kirayəçi kontekstində şablon DELETE edildi!';
    END IF;

    -- Sessiya kontekstsiz (miqrasiya/owner) icra HƏLƏ DƏ mümkün olmalıdır —
    -- əks halda gələcək bir miqrasiyanın şablonu ÖZÜ dəyişdirməsi (yeni ad,
    -- s.) trigger-ə ilişərdi. Real dəyişiklik BURAXILMIR: özümüzün atdığı
    -- marker istisnası bu sub-tranzaksiyanı geri qaytarır.
    PERFORM set_config('app.tenant_id', '', TRUE);
    BEGIN
        UPDATE positions SET name_az = name_az WHERE tenant_id IS NULL AND code = 'ROOT';
        RAISE EXCEPTION 'İ5_TEST_ROLLBACK_MARKER';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM <> 'İ5_TEST_ROLLBACK_MARKER' THEN
            RAISE EXCEPTION
                'TEST 43c UĞURSUZ: kontekstsiz UPDATE trigger tərəfindən bloklandı (%)', SQLERRM;
        END IF;
    END;

    v_passed := v_passed + 1;
    RAISE NOTICE 'TEST 43 ✓ mövqe şablonu kirayəçi sessiyasından qorunur, kontekstsiz icra açıqdır';

    -- Sessiya kontekstini TƏMİZLƏYİRİK: aşağıdakı `DELETE FROM license_tenants`
    -- `positions`/`position_permissions`-ı KASKAD silir — `app.user_id` CEO-da
    -- qalsaydı, ROOT-un digər (hələ silinməmiş) ROOT_ONLY sətirləri üzərində
    -- BU TRIGGER kaskadı bloklayardı. Boş dəyər → "kontekstsiz" → buraxılır
    -- (bax miqrasiyanın "aktor tapılmadıqda" şərhi).
    PERFORM set_config('app.user_id', '', TRUE);

    RAISE NOTICE '';
    RAISE NOTICE '===========================================';
    RAISE NOTICE 'BÜTÜN GUARD TESTLƏRİ UĞURLU: %/43', v_passed;
    RAISE NOTICE '===========================================';

    -- Test məlumatlarının təmizlənməsi
    -- (audit_logs sətirləri QƏSDƏN qalır — append-only, FK yoxdur)
    --
    -- `fines` və `leave_requests` AÇIQ SİLİNİR, tenant kaskadına buraxılmır:
    -- `fines.leave_request_id` üzərindəki FK `NO ACTION`-dır (DEFERRABLE
    -- DEYİL), yəni tək bir `DELETE license_tenants` iki kaskadın hansının
    -- əvvəl işləməsindən asılı olardı. Açıq sıra bu sualı tamamilə aradan
    -- qaldırır — test təmizliyi DB daxili sıraya güvənməməlidir.
    --
    -- `face_control_exemptions` DƏ AÇIQ SİLİNİR (TEST 33/34): `granted_by`
    -- üzərindəki FK `ON DELETE NO ACTION`-dır və DEFERRABLE DEYİL (miqrasiya
    -- 047), yəni tenant kaskadı `employees` sətrini əvvəl silsəydi silmə
    -- FK pozuntusu ilə çökərdi. Açıq sıra bu sualı aradan qaldırır.
    DELETE FROM fines WHERE tenant_id = v_tenant;
    DELETE FROM leave_requests WHERE tenant_id = v_tenant;
    DELETE FROM face_control_exemptions WHERE tenant_id = v_tenant;
    -- TEST 35-39 (`store_pin_throttle`): FK-si `ON DELETE CASCADE`-dir, yəni
    -- aşağıdakı `license_tenants` silinməsi bunu ÖZÜ təmizləyərdi — açıq
    -- silmək YALNIZ oxunaqlılıq üçündür, faylın qalan hissəsinin "AÇIQ SIRA"
    -- konvensiyasına uyğun.
    DELETE FROM store_pin_throttle WHERE tenant_id IN (v_tenant, v_tenant2);
    DELETE FROM license_tenants WHERE tenant_id = v_tenant2;
    DELETE FROM license_tenants WHERE tenant_id = v_tenant;
END
$$;
