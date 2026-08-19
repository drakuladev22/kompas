-- ===========================================================================
-- 076 — DB-6: `ROOT_ONLY` FLAG-İN DELETE İLƏ GERİ ALINMASI QAPISI
-- ===========================================================================
-- Tarix : 2026-08-19
-- Səbəb : `security`-nin dövrə 4 tapıntısı — `PostgresPositionRepository.
--         _sync_flags()` (`repositories.py:237-256`) və `PostgresEmployeeRepository.
--         _sync_overrides()` (eyni fayl:595-600) geri alınan flag sətirlərini
--         `DELETE FROM position_permissions ...` / `DELETE FROM
--         user_permission_overrides ...` ilə silir. `schema.sql` §18-dəki ÜÇ
--         qoruyucu trigger (`enforce_anti_fraud_segregation`,
--         `enforce_permission_hardlock`, `enforce_grantor_owns_flag`) HAMISI
--         `BEFORE INSERT OR UPDATE`-dir — DELETE-i HEÇ BİRİ görmür.
--
-- ---------------------------------------------------------------------------
-- NİYƏ MƏHZ `ROOT_ONLY` (hardlock=1) — QALAN SƏVİYYƏLƏR YOX
-- ---------------------------------------------------------------------------
-- Domendə `Position.assert_root_only_flag_allowed()` (`domain/entities/
-- position.py:232`) MƏHZ bu flag sinfi üçün AYRICA, iyerarxiyadan asılı
-- olmayan mütləq qapı daşıyır — səbəb "ROOT_ONLY flag Root-dan itsə, onu geri
-- qaytara biləcək HEÇ KİM qalmır" (yalnız Root ONU verə bilər, başqa heç kim).
-- Səviyyə 2/3 flag-lər üçün belə mütləq risk yoxdur: onları CEO/Admin də
-- idarə edə bilir, itki geri dönməzlik yaratmır.
--
-- ---------------------------------------------------------------------------
-- CARİ RİSK SƏVİYYƏSİ — AKTİV EKSPLOİT DEYİL, DEFENSE-IN-DEPTH
-- ---------------------------------------------------------------------------
-- `positions.save()`-i çağıran YEGANƏ yol `application/use_cases/
-- position_management.py`-dır (`create_role`, `set_role_flags`) və hər ikisi
-- `save()`-dən ƏVVƏL `Position.assert_may_be_edited_by()` çağırır — bu, ROOT-
-- un öz rolunu YALNIZ ROOT-un redaktə edə bilməsini artıq təmin edir (SEC-006:
-- bərabər-pillə istisnası YALNIZ Root üçündür). Yəni HAZIRKI tək çağırış
-- yolunda ROOT-un öz `ROOT_ONLY` flag-ini QEYRİ-ROOT bir aktorun silməsi
-- REACHABLE DEYİL. Bu miqrasiya CLAUDE.md §5-in "hər qayda İKİ yerdə —
-- ekranı yan keçən skript də tabe olmalıdır" tələbini ödəyir: gələcək kod
-- yolu (yeni skript, bug, birbaşa `UPDATE`/`DELETE`) `Position.revoke()`-u
-- yan keçib birbaşa flag dəstini dəyişsə, DB YENƏ DƏ tutur.
--
-- ---------------------------------------------------------------------------
-- NİYƏ HƏDƏF SƏTRİN "ROOT-A MƏXSUSLUĞU" AYRICA YOXLANMIR
-- ---------------------------------------------------------------------------
-- `enforce_permission_hardlock()` artıq GRANT (INSERT/UPDATE) zamanı
-- `hardlock_level = 1` flag-in YALNIZ `positions.code = 'ROOT'` sətrinə
-- yazılmasına icazə verir — yəni `position_permissions`/`user_permission_
-- overrides`-da `ROOT_ONLY` flag daşıyan HƏR sətir artıq İNVARİANT olaraq
-- Root-un öz sətridir. Bu trigger YALNIZ "kim SİLİR" sualını yoxlayır (aktor
-- Root olmalıdır) — "kimdən silinir" sualı yuxarıdakı invariantla ARTIQ
-- bağlıdır, ikinci yoxlama TƏKRAR olardı.
--
-- ---------------------------------------------------------------------------
-- AKTOR HARADAN OXUNUR — SÜTUNDAN YOX, SESSİYA KONTEKSTİNDƏN
-- ---------------------------------------------------------------------------
-- `enforce_grantor_owns_flag()` aktoru `NEW.granted_by` SÜTUNUNDAN oxuyur —
-- DELETE-də bu mümkün deyil, `OLD` sətrində "kim silir" sualının cavabı YOX
-- (yalnız "kim vermişdi" var, o da bu sualı cavablamır). Ona görə `_sync_
-- flags()`/`_sync_overrides()`-un ÖZÜNÜN artıq oxuduğu `app.user_id`
-- (`UnitOfWork._apply_tenant_context`, `SET LOCAL`) mənbəyi işlədilir —
-- `repositories.py:245`-dəki EYNİ naxış (`NULLIF(current_setting(...), '')`).
--
-- ---------------------------------------------------------------------------
-- AKTOR TAPILMADIQDA `RETURN OLD` — QALAN ÜÇ QAPI İLƏ EYNİ QƏRAR
-- ---------------------------------------------------------------------------
-- Sessiya kontekstsizdirsə (miqrasiya/DOWN-rollback, planlayıcı, seed) və ya
-- aktorun işçi sətri tapılmırsa, `enforce_grantor_owns_flag()`/`enforce_
-- hierarchy_guard()` HƏR İKİSİ `RETURN NEW` edərək buraxır — iki trigger
-- eyni yazıya FƏRQLİ qərar verməməlidir. Bu trigger DƏ eyni qayda ilə
-- `RETURN OLD` edir (blok etmir): əks halda `permission_flags`/`positions`-
-- dan gələn `ON DELETE CASCADE` (məs. bir DOWN blokunun `DELETE FROM
-- permission_flags`-i) sessiya kontekstsiz mühitdə sükutla ÇÖKƏRDİ.
--
-- ---------------------------------------------------------------------------
-- §7 — MÖVCUD `schema.sql` NÜSXƏSİNİ YENİDƏN YAZMIR, YENİ OBYEKTDİR
-- ---------------------------------------------------------------------------
-- Funksiya/trigger `schema.sql`-də ƏVVƏL MÖVCUD DEYİLDİ — `test_schema_
-- migration_parity.py`-a əlavə lazım deyil (adı hər ikisində EYNİ mətnlə
-- görünəcək, test bunu avtomatik tutur). Buna baxmayaraq, funksiya ƏLAVƏ
-- OLARAQ `schema.sql` §18-ə DƏ (digər üç bacı-qapının yanına) yazılır: bu,
-- §18-in ÖZÜ "HARDCODED TƏHLÜKƏSİZLİK ZƏMANƏTLƏRİ" toplusu olduğu üçün
-- oxunaqlılıq qərarıdır — dörd qapının hamısı BİR yerdə görünməlidir ki,
-- növbəti oxucu üçüncüsünü tapıb dördüncünü qaçırmasın.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

CREATE OR REPLACE FUNCTION enforce_root_only_flag_revoke() RETURNS TRIGGER AS $$
DECLARE
    v_level      SMALLINT;
    v_actor_code TEXT;
BEGIN
    SELECT hardlock_level INTO v_level FROM permission_flags WHERE code = OLD.flag_code;
    -- Flag artıq kataloqdan silinibsə (`ON DELETE CASCADE`) `v_level` NULL
    -- olur — `COALESCE(..., 0)` bunu "adi flag" kimi oxuyur, bloklamır.
    IF COALESCE(v_level, 0) <> 1 THEN
        RETURN OLD;
    END IF;

    SELECT p.code INTO v_actor_code
      FROM employees e
      JOIN positions p ON p.id = e.position_id
     WHERE e.id = NULLIF(current_setting('app.user_id', TRUE), '')::uuid;

    -- Sessiya kontekstsiz (seed/planlayıcı/DOWN-rollback) — digər üç
    -- qoruyucu ilə EYNİ qərar (bax modul başlığı).
    IF v_actor_code IS NULL THEN
        RETURN OLD;
    END IF;

    IF v_actor_code <> 'ROOT' THEN
        RAISE EXCEPTION
            'HARDLOCK (səviyyə 1): ROOT_ONLY flag-in "%" geri alınması '
            'yalnız Root tərəfindən edilə bilər (bölmə 3)', OLD.flag_code;
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_root_only_flag_revoke() IS
    'DB-6 (migrations/076): `enforce_permission_hardlock()`-un DELETE tərəfi. '
    'GRANT (INSERT/UPDATE) YOLUNU səviyyə-1 flag üçün artıq `enforce_permission_'
    'hardlock()` `positions.code = ''ROOT''` sətrinə MƏHDUDLAŞDIRIR — bu funksiya '
    'REVOKE (DELETE) yolunu bağlayır: `_sync_flags()`/`_sync_overrides()` geri '
    'alınan flag-ləri DELETE ilə silir, mövcud İKİ trigger isə (`enforce_'
    'permission_hardlock`, `enforce_grantor_owns_flag`) BEFORE INSERT OR UPDATE '
    'olduğu üçün DELETE-i görmür.';

DROP TRIGGER IF EXISTS trg_root_only_revoke_position ON position_permissions;
CREATE TRIGGER trg_root_only_revoke_position
    BEFORE DELETE ON position_permissions
    FOR EACH ROW EXECUTE FUNCTION enforce_root_only_flag_revoke();

DROP TRIGGER IF EXISTS trg_root_only_revoke_override ON user_permission_overrides;
CREATE TRIGGER trg_root_only_revoke_override
    BEFORE DELETE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_root_only_flag_revoke();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_root_only_revoke_override ON user_permission_overrides;
--   DROP TRIGGER IF EXISTS trg_root_only_revoke_position ON position_permissions;
--   DROP FUNCTION IF EXISTS enforce_root_only_flag_revoke();
-- COMMIT;
