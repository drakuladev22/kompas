-- ===========================================================================
-- 065 — ÖZÜNƏ-HOST EDİLƏN QURAŞDIRMANIN LİSENZİYA SƏTRİ (SEC-023)
-- ===========================================================================
-- Tarix : 2026-08-17
-- Səbəb : Paketlənmiş `.exe`-də İlk Quraşdırma Sihirbazı SON addımda
--         dayanırdı:
--
--             InsufficientPrivilege: permission denied for table
--             license_tenants
--             (first_run_setup._provision → ensure_self_hosted_tenant)
--
--         Yəni proqram quraşdırıla BİLMİRDİ — istifadəçi «KompasOS işə düşə
--         bilmədi» mesajı ilə qarşılaşırdı.
--
-- ---------------------------------------------------------------------------
-- QÜSUR NƏDƏN İBARƏT İDİ: EYNİ QAYDA İKİ YERDƏ, İKİ FƏRQLİ CAVAB
-- ---------------------------------------------------------------------------
-- `schema.sql` §28 tətbiq rolundan YALNIZ `UPDATE, DELETE` geri alır:
--
--     REVOKE UPDATE, DELETE ON license_tenants FROM kompasos_app
--
-- Miqrasiya 006 isə `INSERT`-i də geri alır:
--
--     REVOKE INSERT, UPDATE, DELETE ON license_tenants FROM kompasos_app
--
-- Nəticə quraşdırma YOLUNDAN asılı olurdu — `CLAUDE.md` §7-dəki
-- `enforce_anti_fraud_segregation()` hekayəsinin eynisi. Yalnız `schema.sql`
-- ilə qurulan təmiz bazada sihirbaz İŞLƏYİRDİ; tam miqrasiya zənciri tətbiq
-- olunmuş bazada isə İŞLƏMİRDİ. Canlı baza ikinci haldadır, ona görə qüsur
-- məhz `.exe` işə salınanda üzə çıxdı.
--
-- Fərq həm də ZAMANIN nəticəsidir: 006 yazılanda yalnız SaaS modeli vardı və
-- lisenziya sətrini VENDOR yaradırdı. Özünə-host edilən quraşdırma (`.exe` +
-- müştərinin öz Supabase layihəsi) sonra gəldi və orada sətri yaradacaq
-- vendor YOXDUR — sihirbaz özü yaratmalıdır.
--
-- ---------------------------------------------------------------------------
-- HANSI CAVAB DOĞRUDUR: `schema.sql`-INKI
-- ---------------------------------------------------------------------------
-- Qorunmalı olan zəmanət «müştəri lisenziya sətrini YARADA bilməsin» deyil —
-- «MÖVCUD sətri DƏYİŞƏ bilməsin»dir. Real hücum ssenariləri bunlardır:
--
--   * dayandırılmış tenant-ı `AKTIV`-ə qaytarmaq  → `UPDATE` (qadağan)
--   * `expires_at`-i irəli çəkmək                 → `UPDATE` (qadağan)
--   * bloklanmış sətri silib yenisini yazmaq      → `DELETE` (qadağan)
--
-- Sətrin İLK dəfə yaradılması bunların heç biri deyil: o an tenant hələ
-- mövcud deyil, yəni yan keçiləcək bir qərar da yoxdur.
--
-- ---------------------------------------------------------------------------
-- İCAZƏ İKİ QATLA MƏHDUDLAŞIR — SADƏCƏ `GRANT INSERT` KİFAYƏT ETMİR
-- ---------------------------------------------------------------------------
-- 006 `license_tenants`-a RLS qoyub və QƏSDƏN yalnız `SELECT` siyasəti
-- yazıb: «siyasəti olmayan əməliyyat = qadağan». Yəni `GRANT INSERT` tək
-- başına heç nəyi dəyişməzdi — sətir RLS-də dayanardı. Ona görə burada HƏM
-- qrant verilir, HƏM də dar bir `INSERT` siyasəti yazılır:
--
--   1. `tenant_id = license_scope_tenant_id()` — yalnız ÖZ sətrini yarada
--      bilir. Bu, `authorization.py`-dəki Self-Escalation Guard-ın DB
--      qarşılığıdır: aktor özündə olmayan bir şeyi verə bilmir.
--
--   2. `license_key_hash = 'SELF_HOSTED_NO_LICENSE_KEY'` — yaradılan sətir
--      MÜTLƏQ özünə-host nişanı daşıyır. Müştəri vendor tərəfindən verilmiş
--      kimi görünən (yəni real Argon2 hash-li) sətir UYDURA BİLMİR. Nişan
--      `config_repositories.SELF_HOSTED_LICENSE_MARKER` ilə eyni sətirdir —
--      ikisi birlikdə dəyişməlidir.
--
-- `UPDATE`/`DELETE` üçün siyasət YENƏ DƏ yazılmır və §28-in REVOKE-u
-- qüvvədədir: iki qat da yerində qalır.
--
-- `service_role` RLS-dən azaddır — Developer Paneli və
-- `scripts/onboard_new_tenant.py` bu dəyişiklikdən təsirlənmir.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Qrant — 006-nın həddindən artıq geri alması düzəldilir
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
        RETURN;
    END IF;

    EXECUTE format('GRANT INSERT ON license_tenants TO %I', v_role);
    -- Təkrar təsdiq: dəyişən YALNIZ `INSERT`-dir.
    EXECUTE format('REVOKE UPDATE, DELETE ON license_tenants FROM %I', v_role);

    RAISE NOTICE 'Özünə-host bootstrap icazəsi verildi: %', v_role;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. RLS siyasəti — «yalnız ÖZ sətrini, yalnız özünə-host nişanı ilə»
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS tenant_bootstraps_own_license ON license_tenants;
CREATE POLICY tenant_bootstraps_own_license ON license_tenants
    FOR INSERT
    WITH CHECK (
        tenant_id = license_scope_tenant_id()
        AND license_key_hash = 'SELF_HOSTED_NO_LICENSE_KEY'
    );

COMMENT ON POLICY tenant_bootstraps_own_license ON license_tenants IS
    'İlk Quraşdırma Sihirbazı ÖZ tenant sətrini yaradır (migrations/065). '
    'Mövcud sətri dəyişmək üçün siyasət yoxdur — UPDATE/DELETE qadağandır.';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- DİQQƏT: bu blok icra edilsə İlk Quraşdırma Sihirbazı yenidən 006-dakı
-- vəziyyətə qayıdır — yəni özünə-host edilən quraşdırma TAMAMLANA BİLMƏZ.
-- Geri qaytarma yalnız sistem SaaS-a keçirilirsə (lisenziya sətrini vendor
-- yaradırsa) mənalıdır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP POLICY IF EXISTS tenant_bootstraps_own_license ON license_tenants;
--   REVOKE INSERT ON license_tenants FROM kompasos_app;
-- COMMIT;
