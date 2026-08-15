-- ===========================================================================
-- MIGRATION 046 — ROL-FLAG YOLUNDA STRICT HIERARCHY + MÜTLƏQ ROOT_ONLY GUARD
-- ===========================================================================
-- Tarix : 2026-08-14
-- Səbəb : Anti-fraud auditi CLAUDE.md §5-dəki «hər struktur qayda İKİ yerdə
--         yaşayır» prinsipinin növbəti pozuntusunu tapdı. Bu dəfə qayda NƏ
--         domendə, NƏ də DB-də tam deyildi:
--
--           * `position_management.set_role_flags()` aktorun pilləsini hədəf
--             rolun pilləsi ilə HEÇ VAXT müqayisə etmirdi;
--           * `Position.revoke()` sadəcə `discard()` idi — geri alma yolu
--             TAMAMİLƏ qorumasız qalırdı;
--           * `schema.sql` §18-dəki `enforce_hierarchy_guard()` YALNIZ
--             `user_permission_overrides` cədvəlinə bağlıdır;
--             `position_permissions` üzərində yalnız anti-fraud, hardlock və
--             sahiblik trigger-ləri var — iyerarxiya yoxlaması YOXDUR.
--
--         Nəticə: `can_manage_positions` sahibi (defolt Root VƏ CEO) öz
--         pilləsindən YUXARI rolun flag dəstini redaktə edə bilirdi.
--         Praktikada CEO `Root` rolundan `can_manage_permissions` /
--         `can_manage_system_limits` flag-lərini ÇIXARA bilərdi və Root öz
--         sistemindən kilidlənərdi — geri qaytarmaq üçün lazım olan flag isə
--         məhz çıxarılan flag idi.
--
--         Domen yarısı bu miqrasiya ilə eyni dəyişiklikdə bağlanır
--         (`Position.assert_may_be_edited_by`,
--          `Position.assert_root_only_flag_allowed`, `Position.revoke`).
--         Bu fayl həmin qaydanın DB yarısıdır — ekranı yan keçən birbaşa SQL
--         də ona tabe olmalıdır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `DELETE` DƏ TUTULUR (ən vacib detal)
-- ---------------------------------------------------------------------------
-- `PostgresPositionRepository._sync_flags()` geri almanı UPDATE ilə DEYİL,
-- `DELETE FROM position_permissions WHERE ... flag_code <> ALL(...)` ilə edir.
-- Yalnız `BEFORE INSERT OR UPDATE` trigger-i qursaydıq, qorunan tərəf VERMƏK
-- olardı, hücum isə ALMAQ yolundan keçərdi — yəni miqrasiya heç nə
-- bağlamazdı. Ona görə trigger ÜÇ əməliyyatı da əhatə edir.
--
-- `DELETE` sətrində "kim silir" sütunu yoxdur: `granted_by` sətri VERƏNİ
-- göstərir, silən isə cari sessiyadır. Ona görə aktor `app.user_id`-dən
-- oxunur — həmin dəyəri `UnitOfWork._apply_tenant_context()` `SET LOCAL` ilə
-- qoyur və `_sync_flags()` INSERT-də də ondan istifadə edir.
--
-- ---------------------------------------------------------------------------
-- SEED YOLU AÇIQ QALIR (fail-open DEYİL, kontekst yoxluğu)
-- ---------------------------------------------------------------------------
-- §23 (rol → flag defolt təyinatı), §24 (`seed_tenant_defaults`) və §25 (DEV
-- tenant) `position_permissions` sətirlərini aktor OLMADAN yazır — o anda hələ
-- heç bir işçi mövcud deyil. Aktor tapılmadıqda trigger `enforce_grantor_owns_flag()`
-- və `enforce_hierarchy_guard()` ilə EYNİ qərarı verir: sətri buraxır. İki
-- trigger eyni yazıya fərqli qərar verməməlidir, əks halda quraşdırma
-- ardıcıllığı hansı trigger-in əvvəl işə düşməsindən asılı olardı.
--
-- ---------------------------------------------------------------------------
-- ROOT_ONLY YOXLAMASI NİYƏ AYRICA DURUR
-- ---------------------------------------------------------------------------
-- `enforce_permission_hardlock()` artıq mövcuddur, lakin o, YALNIZ HƏDƏF
-- rolunun kodunu yoxlayır ("bu flag `ROOT` rolundadırmı") və yalnız
-- `granted = TRUE` halında. Bura isə AKTORU da yoxlayır ("bu flag-ə toxunan
-- `ROOT`-durmu") və geri alma yolunu da əhatə edir. İkisi bir-birini əvəz
-- etmir: biri flag-in HARADA olduğunu, digəri KİMİN ona toxunduğunu qoruyur.
--
-- Sərt LİTERAL flag siyahısı (`can_manage_permissions`, `can_manage_system_limits`,
-- …) QƏSDƏN yazılmır: həmin flag-lər onsuz da `permission_flags.hardlock_level = 1`
-- ilə elan olunub. Siyahı ÜÇÜNCÜ mənbə yaradardı və Root Permission
-- Registry-dən yeni `ROOT_ONLY` flag əlavə etdikdə arxada qalardı. Domen tərəfi
-- də eyni qərarı verir: `flag.hardlock is HardlockLevel.ROOT_ONLY`.
--
-- İdempotentdir (CREATE OR REPLACE + DROP TRIGGER IF EXISTS). Təkrar icra
-- təhlükəsizdir. DOWN bloku faylın sonunda şərh içindədir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. TRIGGER FUNKSİYASI
-- ---------------------------------------------------------------------------
-- Üslub `enforce_hierarchy_guard()` (schema.sql §18) ilə eynidir: prioritetlər
-- `positions` cədvəlindən oxunur, `ROOT` istisnası koda görə verilir və
-- müqayisə `<=` ilə aparılır (bərabər pillə DƏ bloklanır — SEC-006).
CREATE OR REPLACE FUNCTION enforce_position_flag_hierarchy() RETURNS TRIGGER AS $$
DECLARE
    v_result           position_permissions%ROWTYPE;
    v_position_id      UUID;
    v_flag_code        TEXT;
    v_actor            UUID;
    v_actor_code       TEXT;
    v_actor_priority   SMALLINT;
    v_target_code      TEXT;
    v_target_priority  SMALLINT;
    v_hardlock         SMALLINT;
BEGIN
    -- BEFORE trigger-i sətri qaytarmalıdır; `DELETE` üçün bu, `OLD`-dur.
    IF TG_OP = 'DELETE' THEN
        v_result      := OLD;
        v_position_id := OLD.position_id;
        v_flag_code   := OLD.flag_code;
        -- Silmədə aktor yalnız sessiya kontekstindən bilinir (fayl başlığına bax).
        -- Pozulmuş GUC dəyəri `current_tenant_id()` (§27) ilə EYNİ cür udulur:
        -- kontekst oxuna bilmirsə "aktor naməlumdur" halına düşürük, çünki
        -- `::uuid` çevirmə xətası bütün texniki silmə əməliyyatlarını
        -- (miqrasiya 003-dəki təmizləmə kimi) anlaşılmaz şəkildə çökdürərdi.
        BEGIN
            v_actor := NULLIF(current_setting('app.user_id', TRUE), '')::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
            v_actor := NULL;
        END;
    ELSE
        v_result      := NEW;
        v_position_id := NEW.position_id;
        v_flag_code   := NEW.flag_code;
        -- INSERT/UPDATE-də `granted_by` avtoritetdir: digər üç trigger də
        -- (anti-fraud, hardlock, sahiblik) qərarını məhz ona görə verir.
        v_actor       := NEW.granted_by;
    END IF;

    -- Sistem seed-i / kontekstsiz texniki yazı — fayl başlığındakı izaha bax.
    IF v_actor IS NULL THEN
        RETURN v_result;
    END IF;

    SELECT p.code, p.priority INTO v_actor_code, v_actor_priority
      FROM employees e
      JOIN positions p ON p.id = e.position_id
     WHERE e.id = v_actor;

    -- Aktor tapılmadı: `position_permissions.granted_by`-da FK yoxdur, həmçinin
    -- RLS aktorun sətrini gizlədə bilər. `enforce_hierarchy_guard` eyni halda
    -- sətri buraxır — iki trigger eyni yazıya fərqli qərar verməməlidir.
    IF v_actor_code IS NULL THEN
        RETURN v_result;
    END IF;

    SELECT p.code, p.priority INTO v_target_code, v_target_priority
      FROM positions p
     WHERE p.id = v_position_id;

    IF v_target_priority IS NULL THEN
        RETURN v_result;
    END IF;

    SELECT hardlock_level INTO v_hardlock
      FROM permission_flags
     WHERE code = v_flag_code;

    -- (b) MÜTLƏQ ROOT_ONLY — iyerarxiya müqayisəsindən AYRI və ona BAXMAYARAQ.
    --     `ROOT` üçün SEC-006 istisnası BURADA tətbiq olunmur: bu, pillə
    --     müqayisəsi deyil, mütləq sahiblik qaydasıdır.
    IF COALESCE(v_hardlock, 0) = 1 THEN
        IF v_actor_code <> 'ROOT' THEN
            RAISE EXCEPTION
                'HARDLOCK POZUNTUSU (səviyyə 1): "%" flag-inə YALNIZ Root toxuna '
                'bilər — verilməsi də, geri alınması da (bölmə 3). Aktor rolu: %',
                v_flag_code, v_actor_code;
        END IF;
        IF v_target_code <> 'ROOT' THEN
            RAISE EXCEPTION
                'HARDLOCK POZUNTUSU (səviyyə 1): "%" flag-i yalnız Root rolunda '
                'ola bilər — "%" roluna əlavə edilə və oradan götürülə bilməz '
                '(bölmə 3)', v_flag_code, v_target_code;
        END IF;
    END IF;

    -- (a) STRICT HIERARCHY GUARD.
    -- QƏRAR SEC-006: YALNIZ `Root` bərabər-pillə qaydasından azaddır — bölmə 3
    -- eyni pilləyə müdaxiləni qadağan edir (CEO ↔ CEO, Admin ↔ Admin).
    -- Root istisnası zəruridir: əks halda Root ÖZ rolunun flag dəstini redaktə
    -- edə bilməzdi (`v_target_priority <= v_actor_priority` özünə də düşür).
    --
    -- SEC-019 QEYDİ (miqrasiya 048): bu fayl yazılanda `CEO` də priority
    -- 0-da idi, yəni «CEO Root roluna toxuna bilmir» nəticəsi bərabər-pillə
    -- şərtindən çıxırdı. 048 modeli düzəltdi (`Root`=0, `CEO`=1) və AŞAĞIDAKI
    -- SQL DƏYİŞMƏDİ: müqayisə NİSBİDİR, `ROOT` istisnası isə rol KODU ilə
    -- verilir — hər ikisi sürüşmədən asılı deyil. `0 <= 1` şərti indi
    -- iyerarxiyanın təbii nəticəsi kimi işə düşür.
    IF v_actor_code = 'ROOT' THEN
        RETURN v_result;
    END IF;

    IF v_target_priority <= v_actor_priority THEN
        RAISE EXCEPTION
            'STRICT HIERARCHY GUARD: yalnız öz iyerarxiya pilləsindən CİDDİ '
            'ŞƏKİLDƏ aşağı rolun icazələrinə toxunmaq olar (aktor priority=%, '
            'hədəf rol=%, hədəf priority=%) (bölmə 3)',
            v_actor_priority, v_target_code, v_target_priority;
    END IF;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_position_flag_hierarchy() IS
    'Strict Hierarchy Guard + mütləq ROOT_ONLY qoruması (bölmə 3), rol → flag '
    'yolu üçün. Domen qarşılıqları: `Position.assert_may_be_edited_by`, '
    '`Position.assert_root_only_flag_allowed` və `Position.revoke`; use case '
    'tərəfi `position_management.set_role_flags`/`_apply_flags`. INSERT/UPDATE '
    'ilə yanaşı DELETE-i də tutur, çünki `_sync_flags()` geri almanı DELETE ilə '
    'edir. Aktor tapılmadıqda (seed / kontekstsiz yazı) sətir buraxılır — '
    '`enforce_hierarchy_guard` və `enforce_grantor_owns_flag` ilə eyni qərar.';

-- ---------------------------------------------------------------------------
-- 2. TRIGGER BAĞLANTISI
-- ---------------------------------------------------------------------------
-- `BEFORE`, çünki qərar sətir yazılmazdan ƏVVƏL verilməlidir; `AFTER` variantı
-- eyni tranzaksiyada rollback etsə də, aralıq vəziyyəti digər trigger-lərə
-- göstərərdi.
DROP TRIGGER IF EXISTS trg_position_flag_hierarchy ON position_permissions;
CREATE TRIGGER trg_position_flag_hierarchy
    BEFORE INSERT OR UPDATE OR DELETE ON position_permissions
    FOR EACH ROW EXECUTE FUNCTION enforce_position_flag_hierarchy();

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — YALNIZ MƏLUMAT İTKİSİ RİSKİ OLMADAN
-- ===========================================================================
-- DİQQƏT: aşağıdakı blok struktur təhlükəsizlik zəmanətini SÖNDÜRÜR
-- (CLAUDE.md §5) və yalnız miqrasiyanın özündə sintaksis qüsuru aşkarlandıqda
-- istifadə edilməlidir. Heç bir sətir silinmir — yalnız qapı açılır.
--
-- BEGIN;
-- SET search_path TO kompasos, public;
-- DROP TRIGGER IF EXISTS trg_position_flag_hierarchy ON position_permissions;
-- DROP FUNCTION IF EXISTS enforce_position_flag_hierarchy();
-- COMMIT;
-- ===========================================================================
