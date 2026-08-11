-- ===========================================================================
-- 013 — ANTI-FRAUD ZƏMANƏTLƏRİNİN BƏRKİDİLMƏSİ (bölmə 3, sətir 76, 79)
-- ===========================================================================
-- Tam audit dörd deşik aşkarladı. Hər biri DOMENDƏ bağlanıb, bu miqrasiya
-- DB tərəfini (ikinci müdafiə qatını) eyni səviyyəyə gətirir — layihə qaydası
-- budur: hər struktur zəmanət İKİ yerdə yaşayır (CLAUDE.md §5).
--
-- 1. Anti-fraud yoxlaması rol KODU ilə işləyirdi (`MAGAZA_MENECERI`,
--    `SATICI`), domen isə PRİORİTETLƏ. Nəticədə `SATICI_2` adlı custom rol
--    (prioritet 3) domendə bloklanır, DB-də isə BLOKLANMIRDI.
-- 2. `is_camera_type` ilə `priority` arasında əlaqə yox idi: DB-də
--    `is_camera_type=TRUE, priority=3` rol yaradıb ona `can_issue_fines`
--    vermək mümkün idi — yəni Satıcı pilləsində cərimə yazma hüququ.
-- 3. `permission_flags` üzərində `UPDATE` geri alınmamışdı. Tək bir
--    `UPDATE ... SET is_anti_fraud = FALSE` həm trigger-i, həm domen
--    yoxlamasını sükutla söndürürdü — "HARDCODED" zəmanət DATA-dan asılı idi.
-- 4. `system_limits` seed-i `SystemLimitKey`-in 12 açarından yalnız 9-unu
--    yazırdı; BR-001/BR-002 açarları metadatasız görünürdü.
--
-- İdempotentdir. DOWN bloku sonda şərh içindədir.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. ANTI-FRAUD YOXLAMASI PRİORİTETƏ DƏ BAXIR
-- ---------------------------------------------------------------------------
-- Domen `Position.effective_system_role` ilə işləyir: prioritet 3 → SELLER,
-- prioritet 2 → HR_ADMIN və s. (bax `position.py`). Trigger indi eyni məntiqi
-- tətbiq edir: sistem kodları ƏLAVƏ OLARAQ saxlanılır (açıq və oxunaqlıdır),
-- lakin prioritet 3 olan HƏR rol — custom da daxil — qadağan sayılır.
--
-- `Mağaza_Meneceri` prioritet 2-dədir, ona görə onu YALNIZ kod ilə tutmaq
-- mümkündür; prioritet 2 tamamilə qadağan edilə bilməz, çünki `HR_Admin` və
-- `Kamera_Nəzarətçisi` də həmin pillədədir.

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
-- (Bu miqrasiyada sətir UNUDULMUŞDU — CI-da 010 məhz buna görə çökürdü.)
SET search_path TO kompasos, public;

CREATE OR REPLACE FUNCTION enforce_anti_fraud_segregation()
RETURNS TRIGGER AS $$
DECLARE
    v_is_anti_fraud   BOOLEAN;
    v_is_camera_only  BOOLEAN;
    v_excl_camera     BOOLEAN;
    v_position_code   TEXT;
    v_priority        SMALLINT;
    v_is_camera_type  BOOLEAN;
BEGIN
    SELECT is_anti_fraud, is_camera_only, excludes_camera_role
      INTO v_is_anti_fraud, v_is_camera_only, v_excl_camera
      FROM permission_flags
     WHERE code = NEW.flag_code;

    IF NOT COALESCE(v_is_anti_fraud, FALSE)
       AND NOT COALESCE(v_is_camera_only, FALSE)
       AND NOT COALESCE(v_excl_camera, FALSE) THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'position_permissions' THEN
        SELECT code, priority, is_camera_type
          INTO v_position_code, v_priority, v_is_camera_type
          FROM positions WHERE id = NEW.position_id;
    ELSE
        SELECT p.code, p.priority, p.is_camera_type
          INTO v_position_code, v_priority, v_is_camera_type
          FROM employees e JOIN positions p ON p.id = e.position_id
         WHERE e.id = NEW.user_id;
    END IF;

    -- (a) Sistem rolları — adbaad qadağa (dəyişmir).
    -- (b) Prioritet 3 (ən aşağı pillə) — HƏR rol, custom da daxil.
    --     Domen `_PRIORITY_TO_ROLE[3] = SELLER` ilə eyni nəticəni verir.
    IF v_position_code IN ('MAGAZA_MENECERI', 'SATICI')
       OR COALESCE(v_priority, 0) >= 3 THEN
        RAISE EXCEPTION
            'ANTI-FRAUD POZUNTUSU: "%" flag-i "%" rolundakı istifadəçiyə verilə bilməz '
            '(bölmə 3, vəzifə ayrılığı hardlock-u; prioritet=%)',
            NEW.flag_code, COALESCE(v_position_code, '?'), COALESCE(v_priority, -1);
    END IF;

    IF COALESCE(v_excl_camera, FALSE) AND COALESCE(v_is_camera_type, FALSE) THEN
        RAISE EXCEPTION
            'VƏZİFƏ AYRILIĞI: "%" flag-i kamera-tipli rola verilə bilməz '
            '(cəriməni yaradan onu təsdiq edə bilməz)', NEW.flag_code;
    END IF;

    IF COALESCE(v_is_camera_only, FALSE) AND NOT COALESCE(v_is_camera_type, FALSE) THEN
        RAISE EXCEPTION
            'ANTI-FRAUD POZUNTUSU: "%" flag-i yalnız kamera-tipli rollarda ola bilər',
            NEW.flag_code;
    END IF;

    -- SEC-001: kamera-tipli rol dual-control TƏSDİQİNİ daşıya bilməz.
    IF NEW.flag_code = 'can_approve_dual_control_override'
       AND COALESCE(v_is_camera_type, FALSE) THEN
        RAISE EXCEPTION
            'SEC-001: dual-control təsdiqi kamera-tipli rola verilə bilməz';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_anti_fraud_segregation() IS
    'Anti-fraud vəzifə ayrılığı (bölmə 3). 013: rol koduna ƏLAVƏ olaraq '
    'prioritet 3 də qadağandır — custom "satıcı-pilləli" rol domendə '
    'bloklanırdı, DB-də isə keçirdi.';

-- ---------------------------------------------------------------------------
-- 2. KAMERA-TİPLİ ROL SATICI PİLLƏSİNDƏ OLA BİLMƏZ
-- ---------------------------------------------------------------------------
-- `position_management.py` bunu tətbiq qatında yoxlayır
-- (`MAX_CAMERA_ROLE_PRIORITY = OPERATIONAL`), lakin birbaşa `INSERT` yolu
-- açıq idi. Bu, "satıcıya cərimə yazma hüququ verməyin dolayı yolu"dur:
-- `is_camera_type=TRUE` rol `is_camera_only` yoxlamasından keçir.

ALTER TABLE positions DROP CONSTRAINT IF EXISTS chk_camera_role_priority;
ALTER TABLE positions ADD CONSTRAINT chk_camera_role_priority
    CHECK (NOT is_camera_type OR priority <= 2);

COMMENT ON CONSTRAINT chk_camera_role_priority ON positions IS
    'Kamera-tipli rol ən aşağı pillədə (prioritet 3) ola bilməz — əks halda '
    'Satıcı səviyyəsində cərimə yazma hüququ yaranardı (bölmə 3).';

-- ---------------------------------------------------------------------------
-- 3. FLAG ATRİBUTLARI DƏYİŞMƏZDİR
-- ---------------------------------------------------------------------------
-- `is_anti_fraud`/`is_camera_only`/`excludes_camera_role`/`hardlock_level`
-- bütün yuxarıdakı yoxlamaların GİRİŞİDİR. Onlar dəyişdirilə bilirsə,
-- zəmanət "hardcoded" deyil, sadəcə konfiqurasiyadır.
--
-- Yeni flag YARADILA bilər (Permission Registry, bölmə 3) — qadağa yalnız
-- MÖVCUD sistem flag-lərinin təhlükəsizlik atributlarının dəyişdirilməsinədir.

CREATE OR REPLACE FUNCTION enforce_flag_attributes_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_anti_fraud       IS DISTINCT FROM OLD.is_anti_fraud
    OR NEW.is_camera_only      IS DISTINCT FROM OLD.is_camera_only
    OR NEW.excludes_camera_role IS DISTINCT FROM OLD.excludes_camera_role
    OR NEW.hardlock_level      IS DISTINCT FROM OLD.hardlock_level THEN
        RAISE EXCEPTION
            'DƏYİŞMƏZ ATRİBUT: "%" flag-inin təhlükəsizlik atributları '
            'dəyişdirilə bilməz (bölmə 3 — struktur zəmanət, konfiqurasiya deyil). '
            'Fərqli davranış lazımdırsa YENİ flag yaradın.', OLD.code;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_flag_attributes_immutable ON permission_flags;
CREATE TRIGGER trg_flag_attributes_immutable
    BEFORE UPDATE ON permission_flags
    FOR EACH ROW EXECUTE FUNCTION enforce_flag_attributes_immutable();

COMMENT ON FUNCTION enforce_flag_attributes_immutable() IS
    'Anti-fraud/hardlock atributlarını UPDATE-dən qoruyur. Ad/təsvir '
    'dəyişdirilə bilər — yalnız təhlükəsizlik semantikası qıfıllıdır.';

-- ---------------------------------------------------------------------------
-- 4. `system_limits` SEED-İ TAMAMLANIR (BR-001, BR-002)
-- ---------------------------------------------------------------------------
-- `SystemLimitKey` 12 açar elan edir, seed isə 9-unu yazırdı. Çatışmayan üçü
-- kodda `DEFAULT_LIMITS` ilə tamamlanır (ona görə funksional qüsur YOX idi),
-- lakin ROOT panelində `value_type`/`min`/`max`/izah metadatası olmadan
-- görünürdü — yəni sürüşdürücü əvəzinə boş sətir sahəsi.

INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('LEAVE_ALLOWANCE_SOURCE', 'LEAVE_TYPE', 'TEXT', NULL, NULL,
     'İcazə güzəştinin mənbəyi (BR-001): LEAVE_TYPE / FIXED / NONE'),
    ('LEAVE_ALLOWANCE_FIXED_MINUTES', '0', 'INTEGER', '0', '1440',
     'Sabit güzəşt müddəti — yalnız mənbə FIXED olduqda tətbiq olunur'),
    ('DELAY_FINE_RATE_PER_MINUTE', '0.00', 'DECIMAL', '0', '100',
     'Gecikmə dəqiqəsinin AZN dəyəri (BR-002). Defolt 0 — təyin edilməmiş '
     'dərəcə ilə avtomatik pul kəsmək hüquqi riskdir.')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- Yeni tenant-lar üçün seed funksiyası da yenilənməlidir — o, `schema.sql`
-- §24-dədir və `013` ondan SONRA tətbiq olunduğu üçün burada təkrarlanır.
-- Funksiyanın özünü dəyişdirmirik (schema.sql tək mənbədir); əvəzinə yeni
-- tenant yarandıqda bu üç sətri əlavə edən ayrıca trigger qoyulur.

CREATE OR REPLACE FUNCTION seed_br_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'LEAVE_ALLOWANCE_SOURCE', 'LEAVE_TYPE', 'TEXT', NULL, NULL,
         'İcazə güzəştinin mənbəyi (BR-001): LEAVE_TYPE / FIXED / NONE'),
        (NEW.tenant_id, 'LEAVE_ALLOWANCE_FIXED_MINUTES', '0', 'INTEGER', '0', '1440',
         'Sabit güzəşt müddəti — yalnız mənbə FIXED olduqda tətbiq olunur'),
        (NEW.tenant_id, 'DELAY_FINE_RATE_PER_MINUTE', '0.00', 'DECIMAL', '0', '100',
         'Gecikmə dəqiqəsinin AZN dəyəri (BR-002). Defolt 0.')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_seed_br_limits ON license_tenants;
CREATE TRIGGER trg_seed_br_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_br_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma)
-- ---------------------------------------------------------------------------
--   DROP TRIGGER IF EXISTS trg_seed_br_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_br_limits_for_new_tenant();
--   DROP TRIGGER IF EXISTS trg_flag_attributes_immutable ON permission_flags;
--   DROP FUNCTION IF EXISTS enforce_flag_attributes_immutable();
--   ALTER TABLE positions DROP CONSTRAINT IF EXISTS chk_camera_role_priority;
--   -- `enforce_anti_fraud_segregation()` üçün `schema.sql` §18-dəki
--   -- orijinal tərifi yenidən tətbiq edin (prioritet şərti olmadan).
--   DELETE FROM system_limits WHERE limit_key IN (
--       'LEAVE_ALLOWANCE_SOURCE', 'LEAVE_ALLOWANCE_FIXED_MINUTES',
--       'DELAY_FINE_RATE_PER_MINUTE');
