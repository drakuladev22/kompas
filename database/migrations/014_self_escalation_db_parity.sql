-- ===========================================================================
-- MIGRATION 014 — SELF-ESCALATION GUARD: DB TƏRƏFİ DOMENƏ UYĞUNLAŞDIRILIR
-- ===========================================================================
-- Tarix : 2026-08-10
-- Səbəb : Anti-fraud auditi CLAUDE.md §5-dəki «hər struktur qayda İKİ yerdə
--         yaşayır — domendə VƏ DB trigger-ində» prinsipinin iki pozuntusunu
--         tapdı. Hər ikisində DOMEN DOĞRUDUR, DB isə GERİDƏ QALIB. Ona görə
--         bu miqrasiya YALNIZ DB tərəfini domenə çəkir: mövcud heç bir
--         yoxlama silinmir, zəiflədilmir və ya sadələşdirilmir — üstünə
--         əlavə olunur (defense-in-depth).
--
-- ---------------------------------------------------------------------------
-- TAPINTI 1 (YÜKSƏK) — «aktor özündə olmayan flag-i verə bilməz» DB-də YOX İDİ
-- ---------------------------------------------------------------------------
-- Domen: `permission_guards.py::_assert_actor_owns_flag` (fərdi override) və
-- `position_management.py::_apply_flags` (rol-defolt) — hər ikisi aktorda
-- AKTİV OLMAYAN flag-in başqasına verilməsini bloklayır.
--
-- `schema.sql` §18-dəki dörd trigger isə bunu heç yerdə yoxlamırdı:
--   * `enforce_anti_fraud_segregation` → flag ilə HƏDƏF rolunun uyğunluğu;
--   * `enforce_permission_hardlock`    → flag ilə HƏDƏF pilləsinin uyğunluğu;
--   * `enforce_self_escalation_guard`  → yalnız `granted_by = user_id`;
--   * `enforce_hierarchy_guard`        → yalnız pillə fərqi.
-- Yəni ekranı yan keçən skript üçün belə yol açıq idi: `Admin` özündə OLMAYAN
-- `can_manage_leave_types` flag-ini bir Satıcıya verir, sonra həmin hesabla
-- daxil olur. Bu, məhz Self-Escalation Guard-ın qarşısını almalı olduğu
-- ssenaridir — sadəcə bir addım dolayı yolla.
--
-- ---------------------------------------------------------------------------
-- TAPINTI 2 (ORTA) — özünə toxunma yalnız GRANT halında bloklanırdı
-- ---------------------------------------------------------------------------
-- Domen `_assert_not_self` EFFEKTDƏN ASILI OLMAYARAQ bloklayır: istifadəçi öz
-- icazə sətrinə ümumiyyətlə toxuna bilməz. DB isə `AND NEW.effect = 'GRANT'`
-- şərti ilə yalnız yarısını tuturdu.
--
-- NİYƏ ÖZÜNƏ `DENY` DƏ QADAĞANDIR (görünüşdə "zərərsiz" olsa da):
--   (a) `user_permission_overrides` üzərində `UNIQUE (user_id, flag_code)`
--       var. Aktor özünə `DENY` sətri yazıb SONRA onu `UPDATE ... SET
--       effect = 'GRANT'` etməyə çalışsa, `UPDATE` trigger-i onu tutur —
--       lakin sətri əvvəlcədən "tutmaq" (əldə saxlamaq) imkanı özü artıq
--       audit izini çaşdırır: sətrin `granted_by`-ı aktorun özüdür.
--   (b) Öz səlahiyyətini könüllü AZALTMAQ da səlahiyyət dəyişikliyidir və
--       bölmə 3-ə görə audit + iyerarxiya yoxlamasından keçməlidir; sükutla
--       icazə verilsə, "kim mənim flag-imi söndürdü" sualı cavabsız qalır.
--   (c) Ən əsası: qayda İKİ yerdə EYNİ olmalıdır. Domen bloklayır, DB isə
--       buraxırsa, iki qat arasında davranış fərqi yaranır və audit hansının
--       həqiqət olduğunu deyə bilmir.
--
-- İdempotentdir (CREATE OR REPLACE + DROP TRIGGER IF EXISTS). Təkrar icra
-- təhlükəsizdir. DOWN bloku faylın sonunda şərh içindədir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 0. MÖVCUD MƏLUMATIN YOXLANIŞI (yalnız oxuyur, heç nə silmir)
-- ---------------------------------------------------------------------------
-- Tapıntı 2 mövcud sətirləri də təsir altına ala bilər: `EmployeeRepository`
-- işçini yazarkən onun BÜTÜN override sətirlərini UPSERT edir. Əgər bazada
-- köhnə `granted_by = user_id` sətri varsa (yalnız `DENY` ola bilər — `GRANT`
-- onsuz da bloklanırdı), həmin işçinin növbəti yazılışı yeni trigger-ə
-- ilişərdi. Sətri SİLMİRİK (QIRMIZI XƏTT: icazə tarixçəsi sübutdur) —
-- əvəzinə operator XƏBƏRDARLIQ görür və sətri əl ilə başqa `granted_by` ilə
-- düzəltməli olur.
DO $$
DECLARE
    v_self_rows INTEGER;
BEGIN
    SELECT count(*) INTO v_self_rows
      FROM user_permission_overrides
     WHERE granted_by = user_id;

    IF v_self_rows > 0 THEN
        RAISE WARNING
            'MİQRASİYA 014: % sətirdə granted_by = user_id (özünə verilmiş '
            'override). Sətirlər SİLİNMƏDİ, lakin həmin işçinin növbəti '
            'yazılışı yeni trigger-ə ilişəcək — `granted_by` sütununu həqiqi '
            'səlahiyyət verənlə əvəzləyin.', v_self_rows;
    ELSE
        RAISE NOTICE
            'MİQRASİYA 014: granted_by = user_id olan sətir tapılmadı '
            '(gözlənilən hal — köhnə trigger GRANT-ı onsuz da bloklayırdı).';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 1. TAPINTI 2: SELF-ESCALATION GUARD EFFEKTDƏN ASILI OLMUR
-- ---------------------------------------------------------------------------
-- Dəyişən YALNIZ `AND NEW.effect = 'GRANT'` şərtinin GÖTÜRÜLMƏSİDİR — yəni
-- qayda GENİŞLƏNİR, daralmır. `GRANT` halı əvvəlki kimi bloklanmağa davam
-- edir, üstəlik `DENY` halı da tutulur (domen `_assert_not_self` ilə eyni).
CREATE OR REPLACE FUNCTION enforce_self_escalation_guard() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.granted_by = NEW.user_id THEN
        RAISE EXCEPTION
            'SELF-ESCALATION GUARD: istifadəçi öz icazə sətrinə toxuna bilməz '
            '(effekt: % — GRANT və DENY üçün eyni qayda, bölmə 3)', NEW.effect;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_self_escalation_guard() IS
    'Self-Escalation Guard, 1-ci hissə (bölmə 3): aktor öz icazə sətrinə '
    'toxuna bilməz. 014: əvvəl yalnız GRANT bloklanırdı, domen isə '
    '(`_assert_not_self`) hər iki effekti bloklayır — iki qat uyğunlaşdırıldı.';

-- Trigger tərifi dəyişmir, lakin miqrasiya idempotent və tam-quraşdırma
-- şəraitindən asılı olmasın deyə yenidən yazılır.
DROP TRIGGER IF EXISTS trg_self_escalation ON user_permission_overrides;
CREATE TRIGGER trg_self_escalation
    BEFORE INSERT OR UPDATE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_self_escalation_guard();

-- ---------------------------------------------------------------------------
-- 2. TAPINTI 1: SƏLAHİYYƏT VERƏN HƏMİN FLAG-Ə SAHİB OLMALIDIR
-- ---------------------------------------------------------------------------
-- Domen semantikası EYNİLƏ təkrarlanır (öz variantı icad EDİLMİR):
--
--   1. Yalnız VERMƏ yoxlanılır. `DENY` (override) və `granted = FALSE`
--      (rol-defolt) — yəni icazənin GERİ ALINMASI — səlahiyyət artırması
--      deyil, ona görə aktorda həmin flag-in olması TƏLƏB EDİLMİR
--      (`_assert_actor_owns_flag`-ın ilk şərti ilə eyni).
--
--   2. `Root` istisnadır. `Position.effective_system_role` yalnız kodu
--      `ROOT` olan rolu `SystemRole.ROOT` sayır (prioritet 0-lı custom rol
--      `CEO` kimi qiymətləndirilir) — ona görə burada da MƏHZ kod yoxlanılır,
--      prioritet yox. Root icazə kataloqunun sahibidir: seed-ə görə onda
--      kamera-əməliyyat flag-ləri YOXDUR, lakin onları paylaya bilməlidir,
--      əks halda kamera rolunu heç kim konfiqurasiya edə bilməzdi.
--
--   3. «Aktorda aktivdir» = `Employee.has_permission()`: ƏVVƏLCƏ fərdi
--      override (vaxtı keçməmişsə; `DENY` rol-defoltu ÜSTƏLƏYİR), sonra
--      rol-defolt, tapılmasa `FALSE`. Ardıcıllıq qəsdən eynidir — fərqli
--      hesablama iki qatı sükutla ayırardı.
--
-- NİYƏ `v_effective_permissions` GÖRÜNÜŞÜ İSTİFADƏ EDİLMİR: o, `WHERE
-- e.is_active` filtri daşıyır və deaktiv aktoru "flag-i yoxdur" kimi
-- göstərərdi. Domendə isə `has_permission` aktivlikdən asılı deyil (giriş
-- ayrıca `assert_admin_login_allowed` ilə bloklanır). Görünüş semantikası
-- burada domendən FƏRQLİ olardı — məhz qaçdığımız vəziyyət.
CREATE OR REPLACE FUNCTION enforce_grantor_owns_flag() RETURNS TRIGGER AS $$
DECLARE
    v_actor        UUID;
    v_actor_code   TEXT;
    v_actor_effect permission_effect;
    v_role_granted BOOLEAN;
    v_owns         BOOLEAN;
BEGIN
    -- (1) Yalnız VERMƏ halı — geri alma yoxlanılmır.
    IF TG_TABLE_NAME = 'position_permissions' THEN
        IF NOT NEW.granted THEN
            RETURN NEW;
        END IF;
    ELSE  -- user_permission_overrides
        IF NEW.effect <> 'GRANT' THEN
            RETURN NEW;
        END IF;
    END IF;

    -- (1a) İDEMPOTENT TƏKRAR YAZILIŞ — YENİ səlahiyyət qərarı deyil.
    --      `EmployeeRepository._sync_overrides()` işçinin HƏR yazılışında bütün
    --      override sətirlərini yenidən UPSERT edir (`ON CONFLICT DO UPDATE`),
    --      `PositionRepository._sync_flags()` isə rolun bütün flag-lərini. Yəni
    --      bu trigger köhnə, ARTIQ TƏSDİQLƏNMİŞ sətirlər üçün də işə düşür və
    --      onun nəticəsi ÜÇÜNCÜ şəxsin (səlahiyyət verənin) sonrakı vəziyyətindən
    --      asılıdır. İstisna olmasaydı belə hal yaranardı: Admin qanuni şəkildə
    --      flag verir → sonra Admin-in həmin flag-i geri alınır → artıq
    --      SATICI-nın adını redaktə etmək belə mümkün olmur, çünki dəyişməyən
    --      override sətri trigger-ə ilişir.
    --
    --      Domen də məhz belə davranır: `apply_override()` YALNIZ yeni qərarı
    --      yoxlayır, mövcud sətrin təkrar yazılışını yox. Sətir hərfi-hərfinə
    --      eyni qaldıqda əlavə hüquq yaranmır — istisna boşluq açmır.
    --
    --      `ON CONFLICT DO UPDATE`-də BEFORE INSERT trigger-i KONFLİKT AŞKAR
    --      EDİLMƏZDƏN ƏVVƏL işə düşür, ona görə yoxlama `TG_OP`-a görə deyil,
    --      cədvəldə eyni sətrin MÖVCUDLUĞUNA görə aparılır.
    IF TG_TABLE_NAME = 'position_permissions' THEN
        IF EXISTS (
            SELECT 1 FROM position_permissions pp
             WHERE pp.position_id = NEW.position_id
               AND pp.flag_code   = NEW.flag_code
               AND pp.granted     = NEW.granted
               AND pp.granted_by IS NOT DISTINCT FROM NEW.granted_by
        ) THEN
            RETURN NEW;
        END IF;
    ELSIF EXISTS (
        SELECT 1 FROM user_permission_overrides upo
         WHERE upo.user_id    = NEW.user_id
           AND upo.flag_code  = NEW.flag_code
           AND upo.effect     = NEW.effect
           AND upo.granted_by IS NOT DISTINCT FROM NEW.granted_by
           AND upo.expires_at IS NOT DISTINCT FROM NEW.expires_at
    ) THEN
        RETURN NEW;
    END IF;

    v_actor := NEW.granted_by;

    -- (2) SEED / BOOTSTRAP İSTİSNASI — MƏCBURİDİR.
    --     `schema.sql` §23 (rol → flag defolt təyinatı), §24
    --     (`seed_tenant_defaults`) və §25 (DEV tenant) `position_permissions`
    --     sətirlərini `granted_by` OLMADAN yazır: o anda hələ heç bir işçi
    --     mövcud deyil, yəni "verən" də yoxdur. Bu istisna olmasaydı tenant
    --     ümumiyyətlə qurula bilməzdi (ilk Root da daxil olmaqla — onun rolu
    --     seed-dən flag alır). `user_permission_overrides` tərəfində sütun
    --     `NOT NULL`-dur, ona görə istisna yalnız rol cədvəlinə aiddir.
    IF v_actor IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT p.code INTO v_actor_code
      FROM employees e
      JOIN positions p ON p.id = e.position_id
     WHERE e.id = v_actor;

    -- (3) Aktor işçi cədvəlində tapılmadı. `position_permissions.granted_by`
    --     sütununda FK YOXDUR (silinmiş işçinin ID-si qala bilər), həmçinin
    --     RLS aktorun sətrini gizlədə bilər. `enforce_hierarchy_guard` eyni
    --     vəziyyətdə `RETURN NEW` edir — davranışı ondan fərqləndirmək iki
    --     trigger-in eyni yazıya fərqli qərar verməsi demək olardı.
    IF v_actor_code IS NULL THEN
        RETURN NEW;
    END IF;

    -- (4) Root istisnası (yuxarıdakı 2-ci bənd).
    IF v_actor_code = 'ROOT' THEN
        RETURN NEW;
    END IF;

    -- (5) Effektiv sahiblik: fərdi override → rol-defolt → FALSE.
    SELECT upo.effect INTO v_actor_effect
      FROM user_permission_overrides upo
     WHERE upo.user_id = v_actor
       AND upo.flag_code = NEW.flag_code
       AND (upo.expires_at IS NULL OR upo.expires_at > now());

    IF v_actor_effect IS NOT NULL THEN
        v_owns := (v_actor_effect = 'GRANT');
    ELSE
        SELECT COALESCE(pp.granted, FALSE) INTO v_role_granted
          FROM employees e
          LEFT JOIN position_permissions pp
                 ON pp.position_id = e.position_id
                AND pp.flag_code = NEW.flag_code
         WHERE e.id = v_actor;
        v_owns := COALESCE(v_role_granted, FALSE);
    END IF;

    IF NOT v_owns THEN
        RAISE EXCEPTION
            'SELF-ESCALATION GUARD: "%" flag-i səlahiyyəti verən istifadəçidə '
            '(%) aktiv deyil — özündə olmayan icazə başqasına və ya rola '
            'verilə bilməz (bölmə 3)', NEW.flag_code, v_actor;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_grantor_owns_flag() IS
    'Self-Escalation Guard, 2-ci hissə (bölmə 3): aktor YALNIZ özündə AKTİV '
    'olan flag-i verə bilər. Domen qarşılıqları: '
    '`permission_guards._assert_actor_owns_flag` (fərdi override) və '
    '`position_management._apply_flags` (rol-defolt). Dörd istisna: geri alma '
    '(DENY / granted=FALSE), `granted_by IS NULL` (sistem seed-i), `ROOT` və '
    'dəyişməyən sətrin təkrar yazılışı (repozitoriya hər save-də UPSERT edir).';

-- Hər İKİ yazı yolu bağlanır: fərdi override də, rol-defolt da.
-- Rol tərəfi vacibdir, çünki əks halda qadağa bir addımla yan keçilərdi:
-- "özümdə olmayan flag-i custom rola qoyum, sonra o rolu hədəfə təyin edim".
DROP TRIGGER IF EXISTS trg_grantor_owns_flag_override ON user_permission_overrides;
CREATE TRIGGER trg_grantor_owns_flag_override
    BEFORE INSERT OR UPDATE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_grantor_owns_flag();

DROP TRIGGER IF EXISTS trg_grantor_owns_flag_position ON position_permissions;
CREATE TRIGGER trg_grantor_owns_flag_position
    BEFORE INSERT OR UPDATE ON position_permissions
    FOR EACH ROW EXECUTE FUNCTION enforce_grantor_owns_flag();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma)
-- ---------------------------------------------------------------------------
-- DİQQƏT: geri qaytarma İKİ təhlükəsizlik qatını açır — yalnız miqrasiyanın
-- özü nasazlıq yaradarsa istifadə edin.
--
--   BEGIN;
--   SET search_path TO kompasos, public;
--
--   DROP TRIGGER IF EXISTS trg_grantor_owns_flag_position ON position_permissions;
--   DROP TRIGGER IF EXISTS trg_grantor_owns_flag_override ON user_permission_overrides;
--   DROP FUNCTION IF EXISTS enforce_grantor_owns_flag();
--
--   -- Self-Escalation Guard-ın 014-dən əvvəlki (dar) variantı:
--   CREATE OR REPLACE FUNCTION enforce_self_escalation_guard() RETURNS TRIGGER AS $f$
--   BEGIN
--       IF NEW.granted_by = NEW.user_id AND NEW.effect = 'GRANT' THEN
--           RAISE EXCEPTION
--               'SELF-ESCALATION GUARD: istifadəçi öz hesabına icazə əlavə edə bilməz '
--               '(bölmə 3)';
--       END IF;
--       RETURN NEW;
--   END;
--   $f$ LANGUAGE plpgsql;
--
--   COMMIT;
