-- ===========================================================================
-- MIGRATION 048 — `Root` VƏ `CEO` PRİORİTETLƏRİNİN AYRILMASI (KONSEPTUAL)
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : İyerarxiya modelində konseptual səhv aşkarlandı — `ROOT` və `CEO`
--         hər ikisi `priority = 0` idi, yəni sistem `CEO`-nu `Root` ilə
--         BƏRABƏR pillədə sayırdı.
--
--         Bu, sadəcə "ədəd səhvi" deyil. "CEO Root-un icazələrinə toxuna
--         bilmir" qaydası həmin modeldə İYERARXİYANIN NƏTİCƏSİ DEYİLDİ — o,
--         yalnız iki ƏLAVƏ qapının yan təsiri kimi işləyirdi:
--             (1) `hardlock_level = 1` (YALNIZ Root) — flag-lərin dörddə
--                 birinə aiddir, qalanlarına yox;
--             (2) bərabər-pillə şərti (`<=`) — `0 <= 0`.
--         Birinci qapı bir flag üçün 2-yə (`ROOT_CEO`) dəyişsəydi, CEO həmin
--         flag-i `Root` rolundan çıxara bilərdi və heç bir yoxlama tutmazdı.
--
--         Düzgün model (bölmə 3, yenilənmiş):
--             Root  = 0   (TƏK BAŞINA ən üst pillə)
--             CEO   = 1   (Root-dan DƏRHAL aşağı)
--             Admin = 2
--             HR_Admin / Mağaza_Meneceri / Kamera_Nəzarətçisi = 3
--             Satıcı = 4
--
--         Domen yarısı eyni dəyişiklikdə bağlanır (`RolePriority.ROOT`,
--         `_DEFAULT_PRIORITIES`, `_PRIORITY_TO_ROLE`). Bu fayl həmin qaydanın
--         DB yarısıdır — ekranı yan keçən birbaşa SQL də ona tabe olmalıdır
--         (CLAUDE.md §5: hər struktur qayda İKİ yerdə yaşayır).
--
-- ---------------------------------------------------------------------------
-- 1. CUSTOM ROLLAR NİYƏ "0-DAN BÖYÜK HAMISINA +1" DEYİL, "ROOT-DAN BAŞQA
--    HAMISINA +1" QAYDASI İLƏ KÖÇÜRÜLÜR
-- ---------------------------------------------------------------------------
-- Kirayəçilərin yaratdığı custom rollar da nərdivanın pillələrindədir; onlar
-- yerində qalsaydı iyerarxiya QARIŞARDI. Nümunə: köhnə modeldə prioritet 1-li
-- custom «Bölgə Rəhbəri» `Admin` pilləsində idi. Sistem rolları sürüşüb
-- `Admin`-i 2-yə qaldırdıqda həmin custom rol 1-də qalsaydı, o, birdən-birə
-- `CEO` pilləsinə YÜKSƏLƏRDİ — yəni miqrasiya sükutla səlahiyyət artırardı.
--
-- Ona görə sürüşdürmə PİLLƏYƏ görə aparılır, rol adına görə yox:
--
--     köhnə 0 (Root/CEO/«rəhbərlik» custom) → yeni 1,  MİNUS `ROOT` rolu
--     köhnə 1 → 2,   köhnə 2 → 3,   köhnə 3 → 4
--
-- Yeganə istisna `code = 'ROOT'`-dur: o, 0-da QALIR, çünki yeni modeldə 0
-- məhz ona məxsusdur. Bütün digər sətirlərə (sistem və custom, şablon və
-- kirayəçi nüsxəsi) `+1` tətbiq olunur.
--
-- Prioritet 0-lı custom rol yeni modeldə 1-ə düşür və bu, DOĞRUDUR: domen
-- onu onsuz da `Root` yox, `CEO` semantikası ilə qiymətləndirirdi
-- (`_PRIORITY_TO_ROLE[ROOT] = SystemRole.CEO`), yəni köçürmə həmin rolun
-- FAKTİKİ səlahiyyətini dəyişmir, sadəcə etiketi həqiqətə uyğunlaşdırır.
--
-- GERİ QAYTARILA BİLƏNDİR: `+1` əməliyyatı `code <> 'ROOT'` şərti ilə
-- birlikdə tam tərsinə çevrilir (`-1`, eyni şərtlə). Heç bir sətir silinmir,
-- heç bir dəyər itmir. DOWN bloku faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- 2. İDEMPOTENTLİK — HANSI SİQNALA GÖRƏ
-- ---------------------------------------------------------------------------
-- Təkrar icra prioritetləri İKİNCİ DƏFƏ sürüşdürərdi, yəni miqrasiya öz
-- düzəltdiyini pozardı. Marker seçimi: KÖHNƏ modeldə `CEO` sətri 0-dadır,
-- YENİ modeldə 1-dədir. Yəni «`code = 'CEO'` AND `priority = 0`» şərti
-- "bu əhatə hələ köçürülməyib" sualının dəqiq cavabıdır.
--
-- Qərar HƏR KİRAYƏÇİ ÜÇÜN AYRICA verilir (`tenant_id IS NOT DISTINCT FROM`,
-- yəni `tenant_id IS NULL` şablon sətirləri də öz əhatəsidir). Səbəb: köhnə
-- ehtiyat nüsxədən BƏRPA edilmiş tək bir kirayəçi qalan hamısını yenidən
-- sürüşdürməyə məcbur etməməlidir. Qlobal marker seçsəydik, belə bərpadan
-- sonra artıq düzgün olan kirayəçilər ikinci dəfə sürüşərdi.
--
-- `seed_tenant_defaults()` şablondan kopyaladığı üçün şablon (`tenant_id IS
-- NULL`) VƏ hər kirayəçi nüsxəsi eyni statementdə əhatə olunur.
--
-- ---------------------------------------------------------------------------
-- 3. ƏDƏDƏ BAĞLI DİGƏR QAYDALAR DA BURADA YENİLƏNİR
-- ---------------------------------------------------------------------------
-- Domen tərəfi müqayisələri SİMVOLLA aparır (`RolePriority.ADMIN`,
-- `RolePriority.OPERATIONAL`), ona görə sürüşməni avtomatik udur. DB tərəfi
-- isə ƏDƏD yazır — həmin üç yer əl ilə uyğunlaşdırılmalıdır, əks halda iki
-- qat FƏRQLİ qərar verər:
--
--   (a) `enforce_permission_hardlock()` — səviyyə 3 (`DELEGABLE`) həddi
--       `priority <= 1` idi (Root/CEO/Admin). Admin 2-yə keçdiyi üçün hədd
--       `<= 2` olmalıdır; əks halda `can_control_user_permissions` /
--       `can_perform_bulk_operations` kimi flag-lər `Admin`-ə VERİLƏ
--       BİLMƏZDİ — spesifikasiya isə Admin-i AÇIQ daxil edir.
--   (b) `enforce_anti_fraud_segregation()` — "ən aşağı pillə" həddi
--       `priority >= 3` idi (`Satıcı`). Satıcı 4-ə keçdi; hədd 3-də
--       qalsaydı, OPERATİV pilləli (`Kamera_Nəzarətçisi` daxil!) hər rol
--       anti-fraud flag-lərindən məhrum olardı — yəni kamera axını
--       tamamilə dayanardı.
--   (c) `chk_camera_role_priority` — `priority <= 2` idi; kamera rolları
--       3-ə keçdiyi üçün CHECK həm sürüşdürməni BLOKLAYARDI, həm də
--       sonradan kamera rolu yaratmağı. Hədd `<= 3` olur
--       (`MAX_CAMERA_ROLE_PRIORITY = RolePriority.OPERATIONAL`).
--
-- Miqrasiya 046-nın trigger-i (`enforce_position_flag_hierarchy`) YENİDƏN
-- YAZILMIR: o, prioritetləri MÜQAYİSƏ edir (`v_target_priority <=
-- v_actor_priority`) və `ROOT` istisnasını rol KODU ilə verir — hər ikisi
-- sürüşmədən asılı deyil. Yalnız həmin fayldakı şərh mətni («CEO də priority
-- 0-dadır») köhnəlib; şərh tarixi sənəd olduğu üçün orada saxlanılır və
-- həqiqi vəziyyət burada qeyd olunur.
--
-- ---------------------------------------------------------------------------
-- 4. RLS / KONTEKST
-- ---------------------------------------------------------------------------
-- `positions` cədvəlində RLS siyasəti yoxdur (rol kataloqu kirayəçi-üstü
-- şablon sətirlərini də saxlayır), ona görə miqrasiya `SET LOCAL` tenant
-- konteksti TƏLƏB ETMİR. `position_permissions` sətirlərinə toxunulmur —
-- yəni 046-dakı `trg_position_flag_hierarchy` trigger-i işə düşmür.
--
-- İdempotentdir. Təkrar icra təhlükəsizdir. DOWN bloku faylın sonundadır.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. CHECK MƏHDUDİYYƏTİNİ ƏVVƏLCƏ AÇIRIQ
-- ---------------------------------------------------------------------------
-- `chk_camera_role_priority` (miqrasiya 013) `priority <= 2` tələb edir.
-- Kamera rolunu 2-dən 3-ə qaldıran UPDATE məhz bu CHECK-ə ilişərdi, yəni
-- sıralama vacibdir: əvvəl aç, sonra sürüşdür, sonra YENİ həddlə bağla.
ALTER TABLE positions DROP CONSTRAINT IF EXISTS chk_camera_role_priority;

-- ---------------------------------------------------------------------------
-- 2. TƏHLÜKƏSİZLİK YOXLAMASI — SÜRÜŞMƏ CHECK-İN ÜST SƏRHƏDİNİ AŞMAMALIDIR
-- ---------------------------------------------------------------------------
-- `priority` sütunu `BETWEEN 0 AND 9` ilə məhduddur. Domen modeli yalnız 0..3
-- (köhnə) dəyərlərini tanıyır — `RolePriority(row["priority"])` daha böyüyünü
-- onsuz da oxuya bilmir. Buna baxmayaraq birbaşa SQL ilə yazılmış 9-luq bir
-- sətir sürüşmədə 10 olardı və miqrasiya anlaşılmaz CHECK xətası ilə çökərdi.
-- Ona görə səbəb ƏVVƏLCƏDƏN, AYDIN mətnlə bildirilir.
DO $$
DECLARE
    v_bad INTEGER;
BEGIN
    -- Yoxlama MƏHZ sürüşəcək sətirlərə aiddir (eyni `EXISTS` markeri).
    -- Əks halda ARTIQ köçürülmüş bir kirayəçidəki əl ilə yazılmış 9-luq sətir
    -- təkrar icranı əsassız yerə dayandırardı — halbuki ona toxunulmayacaq.
    SELECT COUNT(*) INTO v_bad
      FROM positions p
     WHERE p.code <> 'ROOT'
       AND p.priority >= 9
       AND EXISTS (
            SELECT 1
              FROM positions ceo
             WHERE ceo.code = 'CEO'
               AND ceo.tenant_id IS NOT DISTINCT FROM p.tenant_id
               AND ceo.priority = 0
       );

    IF v_bad > 0 THEN
        RAISE EXCEPTION
            'MIGRATION 048 DAYANDIRILDI: % sətrin prioriteti 9-dur və +1 '
            'sürüşməsi `priority BETWEEN 0 AND 9` CHECK-ini aşardı. Həmin '
            'sətirlər domen modelinin (RolePriority 0..4) kənarındadır və '
            'əl ilə düzəldilməlidir.', v_bad;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. PRİORİTETLƏRİN SÜRÜŞDÜRÜLMƏSİ (şablon + kirayəçi nüsxələri + custom)
-- ---------------------------------------------------------------------------
-- `code <> 'ROOT'` — yeganə istisna. `EXISTS(...)` isə idempotentlik
-- markeridir (fayl başlığı, bölmə 2): yalnız `CEO`-su hələ 0-da olan əhatələr
-- sürüşür.
UPDATE positions p
   SET priority = p.priority + 1
 WHERE p.code <> 'ROOT'
   AND EXISTS (
        SELECT 1
          FROM positions ceo
         WHERE ceo.code = 'CEO'
           AND ceo.tenant_id IS NOT DISTINCT FROM p.tenant_id
           AND ceo.priority = 0
   );

-- `ROOT` sətri 0-da olmalıdır. Köhnə modeldə də 0 idi, yəni bu UPDATE adətən
-- sıfır sətir toxunur — lakin əl ilə dəyişdirilmiş quraşdırma üçün qapı
-- bağlanır (fail-loud əvəzinə fail-safe: dəyər BƏRPA edilir).
UPDATE positions SET priority = 0 WHERE code = 'ROOT' AND priority <> 0;

-- Köçürülməmiş əhatə qaldısa (məs. `CEO` sətri əl ilə silinmiş kirayəçi)
-- operator bunu GÖRMƏLİDİR — sükutla yarımçıq iyerarxiya ən pis nəticədir.
DO $$
DECLARE
    v_orphan INTEGER;
BEGIN
    -- `COUNT(DISTINCT tenant_id)` NULL-u SAYMAZDI, yəni ŞABLON əhatəsi
    -- (`tenant_id IS NULL`) diaqnostikadan sükutla düşərdi. Alt-sorğudakı
    -- `SELECT DISTINCT` isə NULL-u ayrıca dəyər kimi qaytarır.
    SELECT COUNT(*) INTO v_orphan
      FROM (
        SELECT DISTINCT p.tenant_id
          FROM positions p
         WHERE NOT EXISTS (
                SELECT 1 FROM positions ceo
                 WHERE ceo.code = 'CEO'
                   AND ceo.tenant_id IS NOT DISTINCT FROM p.tenant_id)
      ) AS orphan_scopes;

    IF v_orphan > 0 THEN
        RAISE WARNING
            'MIGRATION 048: % kirayəçi əhatəsində `CEO` rolu tapılmadı — '
            'prioritetləri sürüşdürmək üçün marker yoxdur, həmin əhatələr '
            'ƏL İLƏ yoxlanılmalıdır (gözlənilən model: Root=0, CEO=1, '
            'Admin=2, operativ=3, Satıcı=4).', v_orphan;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. CHECK-İ YENİ HƏDDLƏ BƏRPA EDİRİK
-- ---------------------------------------------------------------------------
-- `MAX_CAMERA_ROLE_PRIORITY = RolePriority.OPERATIONAL` = 3 (yeni model).
ALTER TABLE positions ADD CONSTRAINT chk_camera_role_priority
    CHECK (NOT is_camera_type OR priority <= 3);

COMMENT ON CONSTRAINT chk_camera_role_priority ON positions IS
    'Kamera-tipli rol ən aşağı pillədə (prioritet 4 = Satıcı) ola bilməz — '
    'əks halda Satıcı səviyyəsində cərimə yazma hüququ yaranardı (bölmə 3). '
    '048: hədd 2-dən 3-ə qalxdı, çünki Root/CEO ayrılığı operativ pilləni '
    '2-dən 3-ə sürüşdürdü. Tətbiq qatındakı qarşılığı '
    '`position_management.MAX_CAMERA_ROLE_PRIORITY`.';

COMMENT ON COLUMN positions.priority IS
    'Strict Hierarchy Guard-ın əsası: can_control_user_permissions sahibi '
    'yalnız ÖZ priority dəyərindən CİDDİ ŞƏKİLDƏ BÖYÜK (daha aşağı '
    'səlahiyyətli) istifadəçilərə toxuna bilər (bölmə 3). Model (048): '
    'Root=0 (TƏK BAŞINA), CEO=1, Admin=2, HR_Admin/Mağaza_Meneceri/'
    'Kamera_Nəzarətçisi=3, Satıcı=4. Domen qarşılığı `RolePriority`.';

-- ---------------------------------------------------------------------------
-- 5. HARDLOCK SƏVİYYƏ 3 HƏDDİ: `priority <= 1` → `priority <= 2`
-- ---------------------------------------------------------------------------
-- Gövdə `schema.sql` §18-dəki ilə EYNİDİR — yalnız (c) bloku dəyişir.
-- Funksiya bütövlükdə təkrarlanır, çünki PostgreSQL-də funksiyanın bir
-- sətrini "yamamaq" mümkün deyil.
CREATE OR REPLACE FUNCTION enforce_permission_hardlock() RETURNS TRIGGER AS $$
DECLARE
    v_level SMALLINT;
    v_priority SMALLINT;
    v_position_code TEXT;
BEGIN
    SELECT hardlock_level INTO v_level FROM permission_flags WHERE code = NEW.flag_code;
    IF COALESCE(v_level, 0) = 0 THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'position_permissions' THEN
        IF NOT NEW.granted THEN
            RETURN NEW;
        END IF;
        SELECT code, priority INTO v_position_code, v_priority
        FROM positions WHERE id = NEW.position_id;
    ELSE
        IF NEW.effect <> 'GRANT' THEN
            RETURN NEW;
        END IF;
        SELECT p.code, p.priority INTO v_position_code, v_priority
        FROM employees e JOIN positions p ON p.id = e.position_id
        WHERE e.id = NEW.user_id;
    END IF;

    -- Səviyyə 1: YALNIZ Root (CEO-ya belə verilmir)
    IF v_level = 1 AND v_position_code <> 'ROOT' THEN
        RAISE EXCEPTION
            'HARDLOCK POZUNTUSU: "%" flag-i YALNIZ Root roluna məxsusdur (bölmə 3, '
            'dörd-səviyyəli hardlock iyerarxiyası, səviyyə 1)', NEW.flag_code;
    END IF;

    -- Səviyyə 2: Root VƏ CEO. Prioritet ayrılığından SONRA da qayda EYNİDİR:
    -- hardlock "flag kimə VERİLƏ BİLƏR" sualına cavabdır, "kim kimə toxuna
    -- bilər" sualına yox — ikincisi Strict Hierarchy Guard-ındır.
    IF v_level = 2 AND v_position_code NOT IN ('ROOT', 'CEO') THEN
        RAISE EXCEPTION
            'HARDLOCK POZUNTUSU: "%" flag-i yalnız Root/CEO rollarına verilə bilər '
            '(bölmə 3, səviyyə 2)', NEW.flag_code;
    END IF;

    -- Səviyyə 3: Admin-ə həvalə edilə bilər, amma operativ rollardan aşağı YOX.
    -- 048: hədd 1-dən 2-yə qalxdı — yeni modeldə Root=0, CEO=1, Admin=2.
    -- Domen qarşılığı `HardlockLevel.allows()` və orada müqayisə SİMVOLLADIR
    -- (`role.default_priority <= RolePriority.ADMIN`), yəni sürüşməni özü udur.
    IF v_level = 3 AND COALESCE(v_priority, 9) > 2 THEN
        RAISE EXCEPTION
            'HARDLOCK POZUNTUSU: "%" flag-i yalnız priority <= 2 olan rollara '
            '(Root/CEO/Admin) verilə bilər (bölmə 3, səviyyə 3)', NEW.flag_code;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_permission_hardlock() IS
    'Dörd-səviyyəli hardlock (bölmə 3), DB yarısı. Domen qarşılığı '
    '`HardlockLevel.allows()`. 048: səviyyə-3 həddi `priority <= 1`-dən '
    '`<= 2`-yə keçdi, çünki Root/CEO ayrılığı `Admin`-i 1-dən 2-yə sürüşdürdü.';

-- ---------------------------------------------------------------------------
-- 6. ANTI-FRAUD "ƏN AŞAĞI PİLLƏ" HƏDDİ: `priority >= 3` → `priority >= 4`
-- ---------------------------------------------------------------------------
-- Gövdə miqrasiya 013-dəki ilə EYNİDİR — yalnız (b) bəndindəki ədəd dəyişir.
-- Bu, miqrasiyanın ƏN KRİTİK hissəsidir: hədd 3-də qalsaydı, yeni modeldə
-- `Kamera_Nəzarətçisi` (3) "ən aşağı pillə" sayılar və `can_verify_returns` /
-- `can_issue_fines` flag-lərini DB səviyyəsində İTİRƏRDİ — yəni bütün kamera
-- təsdiq axını dayanardı. Anti-fraud qadağası GENİŞLƏMİR də, DARALMIR da:
-- hədəf yenə `Satıcı` pilləsidir, sadəcə onun ədədi 3-dən 4-ə keçib.
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
    -- (b) Prioritet 4 (ən aşağı pillə, `RolePriority.STAFF`) — HƏR rol,
    --     custom da daxil. Domen `_PRIORITY_TO_ROLE[STAFF] = SELLER` ilə
    --     eyni nəticəni verir. 048-ə qədər burada 3 yazılırdı.
    IF v_position_code IN ('MAGAZA_MENECERI', 'SATICI')
       OR COALESCE(v_priority, 0) >= 4 THEN
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
    'Anti-fraud vəzifə ayrılığı (bölmə 3). 013: rol koduna ƏLAVƏ olaraq ən '
    'aşağı pillə də qadağandır — custom "satıcı-pilləli" rol domendə '
    'bloklanırdı, DB-də isə keçirdi. 048: həmin pillənin ədədi 3-dən 4-ə '
    'keçdi, çünki Root/CEO ayrılığı bütün pillələri bir vahid sürüşdürdü.';

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — TAM TƏRSİNƏ ÇEVRİLƏ BİLƏN
-- ===========================================================================
-- DİQQƏT: aşağıdakı blok iyerarxiyanı KONSEPTUAL SƏHVİ OLAN modelə qaytarır
-- (`Root` və `CEO` yenidən BƏRABƏR pillədə olur) və yalnız miqrasiyanın
-- özündə qüsur aşkarlandıqda istifadə edilməlidir. Heç bir sətir silinmir.
--
-- Sıralama UP-ın tam əksidir: əvvəl CHECK açılır, sonra `-1`, sonra CHECK
-- köhnə həddlə bağlanır, ən sonda funksiyalar köhnə ədədlərlə bərpa olunur.
-- İdempotentlik markeri də tərsinədir: yalnız `CEO`-su 1-də olan əhatələr.
--
-- BEGIN;
-- SET search_path TO kompasos, public;
--
-- ALTER TABLE positions DROP CONSTRAINT IF EXISTS chk_camera_role_priority;
--
-- UPDATE positions p
--    SET priority = p.priority - 1
--  WHERE p.code <> 'ROOT'
--    AND EXISTS (
--         SELECT 1 FROM positions ceo
--          WHERE ceo.code = 'CEO'
--            AND ceo.tenant_id IS NOT DISTINCT FROM p.tenant_id
--            AND ceo.priority = 1);
--
-- ALTER TABLE positions ADD CONSTRAINT chk_camera_role_priority
--     CHECK (NOT is_camera_type OR priority <= 2);
--
-- -- `enforce_permission_hardlock()` üçün `schema.sql` §18-dəki gövdəni
-- -- `v_priority > 1` ilə yenidən tətbiq edin.
-- -- `enforce_anti_fraud_segregation()` üçün miqrasiya 013-dəki gövdəni
-- -- `v_priority >= 3` ilə yenidən tətbiq edin.
-- COMMIT;
-- ===========================================================================
