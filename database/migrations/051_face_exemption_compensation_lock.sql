-- ===========================================================================
-- MIGRATION 051 — ÜZ-İSTİSNASININ KOMPENSASİYA EDİCİ NƏZARƏTİ KİLİDLƏNİR
-- ===========================================================================
-- Tarix : 2026-08-15
-- Qərar : SEC-020 (`docs/security_decisions.md`)
-- Səbəb : Anti-fraud auditi `facecontrol.md` bənd 14-ün zəmanətinin YARIM
--         qaldığını tapdı.
--
--         Bənd 14 üz təsdiqindən PIN-only istisnasını YALNIZ bir şərtlə
--         verir:
--
--           «MƏCBURİ KOMPENSASİYA EDİCİ NƏZARƏT: İstisnalı işçinin HƏR
--            giriş/qayıdış təsdiqi avtomatik olaraq mövcud DUAL-CONTROL
--            axınına düşür — MƏCBURİ ikinci-təsdiq.»
--
--         Yəni istisnanın YEGANƏ əvəzləyicisi `DUAL_CONTROL` modulunun
--         axınıdır. Lakin həmin modul `feature_toggles`-də adi sətir idi
--         (`is_structural = FALSE`), yəni bir `UPDATE` ilə söndürülə bilirdi.
--         Nəticə tərif olunmamış vəziyyət idi:
--
--           (a) qapı yenə ikinci təsdiq tələb etsəydi — istisnalı işçi HEÇ
--               VAXT günə başlaya bilməzdi (təsdiqi verəcək axın söndürülüb);
--           (b) kompensasiya sükutla itsəydi — həmin işçinin PIN-i ilə
--               İSTƏNİLƏN şəxs təkbaşına təsdiq alardı, yəni bənd 14-ün
--               bağlamaq istədiyi aldatma yolu bir toggle ilə yenidən açılardı.
--
--         Hər iki nəticə qəbuledilməzdir. Qayda indi ŞƏRTİ KİLİDDİR: aktiv
--         üz-təsdiqi istisnası varkən `DUAL_CONTROL` söndürülə bilməz və
--         `DUAL_CONTROL` sönükdürsə yeni/uzadılan aktiv istisna yaradıla
--         bilməz. Kilid əbədi deyil — Root əvvəlcə istisnaları ləğv edir.
--
-- ---------------------------------------------------------------------------
-- DOMEN YARISI HARADADIR (CLAUDE.md §5 — qayda İKİ yerdədir)
-- ---------------------------------------------------------------------------
--   * `src/domain/policies.py` → `FACE_EXEMPTION_COMPENSATING_MODULE`
--     (bağlantının adlandırılmış TƏK mənbəyi);
--   * `RootControlUseCase._require_no_dependent_guarantee` → modulu istisnaya
--     görə kilidləyir;
--   * `FaceControlExemptionUseCase._require_compensating_control` → istisnanı
--     modula görə kilidləyir (SİMMETRİK yarı: əks halda «əvvəlcə modulu
--     söndür, sonra istisna ver» sırası qapını yan keçərdi);
--   * `FaceVerificationUseCase._exempt_employee_gate` → köhnə/əlüstü
--     yaradılmış vəziyyətdə FAIL-CLOSED davranır (manual təsdiqə yönləndirir).
--
-- Bu fayl həmin qaydanın DB yarısıdır: ekranı YAN KEÇƏN birbaşa SQL də ona
-- tabe olmalıdır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ İKİ TRIGGER, BİRİ YOX
-- ---------------------------------------------------------------------------
-- Qayda bir İNVARİANTDIR: «(aktiv istisna) VƏ (DUAL_CONTROL sönük)» cütü heç
-- vaxt mövcud olmamalıdır. İnvarianta İKİ tərəfdən yaxınlaşmaq olar və hər
-- iki qapı bağlanmalıdır — yalnız `feature_toggles` trigger-i yazsaydıq,
-- sıranı dəyişdirmək (əvvəlcə modulu söndür, sonra istisna yaz) qorumanı
-- tamamilə keçərdi.
--
-- ---------------------------------------------------------------------------
-- `is_structural = TRUE` NİYƏ SEÇİLMƏDİ
-- ---------------------------------------------------------------------------
-- Alternativ variant `feature_toggles.is_structural`-i `TRUE` etmək idi
-- (yazılı təsdiq tələbi). Rədd edildi:
--   * o, söndürməni DAYANDIRMIR, yalnız 6 simvolluq mətn tələb edir — təsdiq
--     yazan Root istisnalı işçini yenə kompensasiyasız qoyardı;
--   * zəmanət ŞƏRTLİDİR (yalnız aktiv istisnası olan kirayəçidə), statik
--     bayraq isə şərti qaydanı ifadə edə bilmir və bütün kirayəçilərə
--     yayılardı;
--   * `is_structural` hazırda `CAMERA_VERIFICATION`-ın mənasını daşıyır
--     («axının struktur əsası»); onu şərti qaydalarla doldurmaq həmin bayrağın
--     mənasını seyrəldərdi.
--
-- ---------------------------------------------------------------------------
-- SƏTİR YOXDURSA MODUL AÇIQ SAYILIR
-- ---------------------------------------------------------------------------
-- `PostgresFeatureToggles.is_enabled` sətir olmayanda `TRUE` qaytarır (yeni
-- modul əlavə ediləndə seed unudula bilər və modul sükutla yox olmamalıdır).
-- Aşağıdakı `enforce_face_exemption_compensation()` EYNİ qərarı verir:
-- yalnız MÖVCUD və `is_enabled = FALSE` olan sətir istisna yazısını bloklayır.
-- Fərqli davransaydıq, seed-i olmayan kirayəçidə kod «modul açıqdır» deyər,
-- trigger isə istisnanı rədd edərdi.
--
-- İdempotentdir (CREATE OR REPLACE + DROP TRIGGER IF EXISTS). Təkrar icra
-- təhlükəsizdir. Heç bir sətir silinmir/dəyişdirilmir. DOWN bloku faylın
-- sonunda şərh içindədir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. `feature_toggles` TƏRƏFİ — modulu istisnaya görə kilidləyir
-- ---------------------------------------------------------------------------
-- `BEFORE INSERT OR UPDATE`: `PostgresFeatureToggles.set_enabled` yazını
-- `INSERT ... ON CONFLICT DO UPDATE` ilə edir, yəni HƏR İKİ yol eyni
-- əməliyyatdan gəlir. Yalnız `UPDATE`-i tutsaydıq, sətri hələ olmayan
-- kirayəçidə ilk yazı `DUAL_CONTROL = FALSE` ilə sərbəst keçərdi.
--
-- `DELETE` QƏSDƏN TUTULMUR: `feature_toggles` sətrinin silinməsi modulu
-- SÖNDÜRMÜR — sətri olmayan modul AÇIQ sayılır (yuxarıdakı izah). Yəni silmə
-- invarianta zidd vəziyyət yarada bilmir və onu bloklamaq yalnız kirayəçi
-- kaskadını (`ON DELETE CASCADE`) çökdürərdi.
CREATE OR REPLACE FUNCTION enforce_face_exemption_compensation() RETURNS TRIGGER AS $$
DECLARE
    v_active INTEGER;
BEGIN
    IF NEW.module_key <> 'DUAL_CONTROL' OR NEW.is_enabled THEN
        RETURN NEW;
    END IF;

    -- HƏM statusa, HƏM `expires_at`-a baxılır — `FaceExemptionRepository.
    -- list_active` ilə EYNİ meyar. Yalnız statusa baxsaydıq, gecəlik iş
    -- işləməyəndə (terminal söndürülüb) faktiki olaraq bitmiş istisna modulu
    -- əbədi kilidləyərdi: qoruma öz sahibini bloklayardı.
    SELECT COUNT(*) INTO v_active
      FROM face_control_exemptions
     WHERE tenant_id = NEW.tenant_id
       AND status = 'ACTIVE'
       AND expires_at > now();

    IF v_active > 0 THEN
        RAISE EXCEPTION
            'KOMPENSASİYA KİLİDİ (SEC-020): "DUAL_CONTROL" modulu % aktiv üz-təsdiqi '
            'istisnasının YEGANƏ kompensasiya edici nəzarətidir (facecontrol.md bənd 14) '
            've söndürülə bilməz. Əvvəlcə həmin istisnaları ləğv edin.', v_active;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_face_exemption_compensation() IS
    'SEC-020 — `DUAL_CONTROL` modulu aktiv `face_control_exemptions` sətri olan '
    'kirayəçidə söndürülə bilməz. Domen qarşılığı: `RootControlUseCase.'
    '_require_no_dependent_guarantee`. Müddəti keçmiş `ACTIVE` sətir SAYILMIR — '
    'meyar `FaceExemptionRepository.list_active` ilə eynidir.';

DROP TRIGGER IF EXISTS trg_dual_control_compensation_lock ON feature_toggles;
CREATE TRIGGER trg_dual_control_compensation_lock
    BEFORE INSERT OR UPDATE ON feature_toggles
    FOR EACH ROW EXECUTE FUNCTION enforce_face_exemption_compensation();

-- ---------------------------------------------------------------------------
-- 2. `face_control_exemptions` TƏRƏFİ — istisnanı modula görə kilidləyir
-- ---------------------------------------------------------------------------
-- YALNIZ `NEW.status = 'ACTIVE'` bloklanır. Bu, ən vacib detaldır: `REVOKED`
-- və `EXPIRED`-ə keçid boşluğu BAĞLAYIR və bloklansaydı ölü-kilid yaranardı —
-- modul sönük, istisna isə ləğv edilə bilməyən vəziyyətdə qalardı. Yəni
-- trigger yalnız boşluğun AÇILMASINI/UZADILMASINI dayandırır, bağlanmasını
-- heç vaxt.
CREATE OR REPLACE FUNCTION enforce_exemption_requires_compensation() RETURNS TRIGGER AS $$
DECLARE
    v_enabled BOOLEAN;
BEGIN
    IF NEW.status <> 'ACTIVE' THEN
        RETURN NEW;
    END IF;

    SELECT is_enabled INTO v_enabled
      FROM feature_toggles
     WHERE tenant_id = NEW.tenant_id
       AND module_key = 'DUAL_CONTROL';

    -- Sətir YOXDURSA modul AÇIQ sayılır (fayl başlığındakı izah) — `FOUND`
    -- yoxlaması `v_enabled IS NULL` ilə eyni nəticəni verir, çünki sütun
    -- `NOT NULL`-dur.
    IF v_enabled IS NOT NULL AND NOT v_enabled THEN
        RAISE EXCEPTION
            'KOMPENSASİYA KİLİDİ (SEC-020): "DUAL_CONTROL" modulu söndürülüb — '
            'Face Control istisnası kompensasiya edici nəzarət olmadan aktiv ola '
            'bilməz (facecontrol.md bənd 14). Əvvəlcə modulu aktivləşdirin.';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_exemption_requires_compensation() IS
    'SEC-020 — aktiv `face_control_exemptions` sətri yalnız `DUAL_CONTROL` modulu '
    'açıq olduqda yazıla bilər. Domen qarşılığı: `FaceControlExemptionUseCase.'
    '_require_compensating_control` (`grant` + `extend`). `REVOKED`/`EXPIRED` '
    'keçidləri TOXUNULMAZDIR — onlar boşluğu bağlayır.';

DROP TRIGGER IF EXISTS trg_exemption_requires_compensation ON face_control_exemptions;
CREATE TRIGGER trg_exemption_requires_compensation
    BEFORE INSERT OR UPDATE ON face_control_exemptions
    FOR EACH ROW EXECUTE FUNCTION enforce_exemption_requires_compensation();

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — YALNIZ MƏLUMAT İTKİSİ RİSKİ OLMADAN
-- ===========================================================================
-- DİQQƏT: aşağıdakı blok struktur təhlükəsizlik zəmanətini SÖNDÜRÜR
-- (CLAUDE.md §5, SEC-020) və yalnız miqrasiyanın özündə sintaksis qüsuru
-- aşkarlandıqda istifadə edilməlidir. Heç bir sətir silinmir — yalnız qapı
-- açılır və üz-təsdiqi istisnası yenidən kompensasiyasız qala bilər.
--
-- BEGIN;
-- SET search_path TO kompasos, public;
-- DROP TRIGGER IF EXISTS trg_dual_control_compensation_lock ON feature_toggles;
-- DROP TRIGGER IF EXISTS trg_exemption_requires_compensation ON face_control_exemptions;
-- DROP FUNCTION IF EXISTS enforce_face_exemption_compensation();
-- DROP FUNCTION IF EXISTS enforce_exemption_requires_compensation();
-- COMMIT;
-- ===========================================================================
