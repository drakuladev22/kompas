-- ===========================================================================
-- 080 — T6 (DEEP-GAP dövrə 4): `positions.is_store_tier` + ANTİ-FRAUD BUDAĞI
-- ===========================================================================
-- Tarix : 2026-08-22
-- Səbəb : `security`-nin DEEP-GAP tapıntısı, komanda rəhbərinin TƏSDİQ etdiyi
--         "İ8" siyahısında (T6). `Position.is_store_tier` domen sahəsi
--         (`entities/position.py`), `PermissionFlag.assert_grantable_to`-nun
--         `is_store_tier_role` parametri VƏ hər ikisinin çağırış yerləri
--         ARTIQ mövcuddur (`domain` yarısı bitib) — DB tərəfi bu miqrasiyaya
--         qədər YOX idi.
--
-- ---------------------------------------------------------------------------
-- BOŞLUQ NİYƏ REAL İDİ
-- ---------------------------------------------------------------------------
-- `enforce_anti_fraud_segregation()` (a)/(b) budağı YALNIZ hərfi `positions.
-- code IN ('MAGAZA_MENECERI', 'SATICI')` VƏ ya `priority >= 4` yoxlayır.
-- Custom rol prioritetinə görə `effective_system_role`-da ən yaxın SİSTEM
-- roluna (məs. prioritet 3 → `HR_ADMIN`) düşür — yəni CEO "Filial
-- Məsulu" adlı, priority=3, kodu `MAGAZA_MENECERI` OLMAYAN custom rol
-- yaratsa, bu DB qapısı onu keçirir və `can_approve_dual_control_override`
-- kimi anti-fraud flag-i həmin rola verilə bilirdi — Mağaza Meneceri öz
-- filialının kamera operatorunun manual vaxt düzəlişini ÖZÜ təsdiq edə
-- bilərdi (bölmə 3, vəzifə ayrılığı). Domen tərəfi (`Position.grant()` →
-- `assert_grantable_to(is_store_tier_role=...)`) bunu ARTIQ tuturdu — yəni
-- qayda YALNIZ BİR yerdə idi (CLAUDE.md §5 pozuntusu, `is_camera_type`-ın
-- simmetrik BOŞLUĞU).
--
-- ---------------------------------------------------------------------------
-- NİYƏ `048`-in ÖZÜ DƏYİŞMİR, YENİ MİQRASİYA YARADILIR
-- ---------------------------------------------------------------------------
-- `048_root_ceo_priority_split.sql` ARTIQ TƏTBİQ OLUNMUŞ miqrasiyadır —
-- onun məzmununu redaktə etmək checksum-u (`schema_migrations`, migrations/
-- 061) dəyişdirər və icraçı XƏBƏRDARLIQ verər ("tətbiq olunmuş faylın
-- SONRADAN redaktəsi"). Bunun əvəzinə 013 → 048 EYNİ naxışı təkrarlanır:
-- YENİ `CREATE OR REPLACE FUNCTION` miqrasiyası əvvəlkini ÜSTƏLƏYİR.
-- `test_schema_migration_parity.py::_pairs()` "sonuncu miqrasiya" məntiqini
-- SIRALI fayl adına görə qurur — bu fayl (080) indi `enforce_anti_fraud_
-- segregation`-ın "qüvvədə olan" mənbəyidir, `schema.sql`-in nüsxəsi ONUNLA
-- müqayisə olunur.
--
-- ---------------------------------------------------------------------------
-- BACKFILL NİYƏ LAZIMDIR
-- ---------------------------------------------------------------------------
-- `is_camera_type`-ın `KAMERA_NEZARETCISI`-də etdiyi ilə EYNİ naxış: yeni
-- sütun `DEFAULT FALSE` ilə yaranır, built-in `MAGAZA_MENECERI` sətri isə
-- (şablon VƏ artıq mövcud olan HƏR tenant-ın öz nüsxəsi) `TRUE` olmalıdır —
-- kod-əsaslı yoxlama onu onsuz da tanısa da, sütun "mağaza-pilləli" faktının
-- TƏK MƏNBƏYİ olmalıdır (növbəti oxucu üçün ziddiyyətli iki mənbə YARATMAMAQ
-- üçün).
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE positions ADD COLUMN IF NOT EXISTS is_store_tier BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN positions.is_store_tier IS
    'T6 (migrations/080): "mağaza-pilləli" (Mağaza Meneceri EKVİVALENTİ) '
    'custom rol işarəsi — `is_camera_type`-ın EYNİ naxışı. '
    '`enforce_anti_fraud_segregation()`-un (c) budağı VƏ domendəki '
    '`PermissionFlag.assert_grantable_to(is_store_tier_role=...)` bu sütunu '
    'oxuyur/güzgüləyir.';

-- Şablon (`tenant_id IS NULL`) VƏ artıq mövcud HƏR tenant-ın öz nüsxəsi —
-- kod sabitdir, tenant_id süzgəci İŞLƏDİLMİR (CLAUDE.md §8-in 069 qeydi ilə
-- EYNİ qayda: flag/atribut əlavə edən miqrasiya `tenant_id IS NULL` filtri
-- İŞLƏTMƏMƏLİDİR ki, mövcud kirayəçilər kənarda qalmasın).
UPDATE positions SET is_store_tier = TRUE
 WHERE code = 'MAGAZA_MENECERI' AND NOT is_store_tier;

-- ---------------------------------------------------------------------------
-- `enforce_anti_fraud_segregation()` — 048-in gövdəsi + `v_is_store_tier` (c)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_anti_fraud_segregation()
RETURNS TRIGGER AS $$
DECLARE
    v_is_anti_fraud   BOOLEAN;
    v_is_camera_only  BOOLEAN;
    v_excl_camera     BOOLEAN;
    v_position_code   TEXT;
    v_priority        SMALLINT;
    v_is_camera_type  BOOLEAN;
    v_is_store_tier   BOOLEAN;
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
        SELECT code, priority, is_camera_type, is_store_tier
          INTO v_position_code, v_priority, v_is_camera_type, v_is_store_tier
          FROM positions WHERE id = NEW.position_id;
    ELSE
        SELECT p.code, p.priority, p.is_camera_type, p.is_store_tier
          INTO v_position_code, v_priority, v_is_camera_type, v_is_store_tier
          FROM employees e JOIN positions p ON p.id = e.position_id
         WHERE e.id = NEW.user_id;
    END IF;

    -- (a) Sistem rolları — adbaad qadağa (dəyişmir).
    -- (b) Prioritet 4 (ən aşağı pillə, `RolePriority.STAFF`) — HƏR rol,
    --     custom da daxil. Domen `_PRIORITY_TO_ROLE[STAFF] = SELLER` ilə
    --     eyni nəticəni verir. 048-ə qədər burada 3 yazılırdı.
    -- (c) T6: `is_store_tier` — custom rol AÇIQ ŞƏKİLDƏ "mağaza-pilləli"
    --     işarələnibsə, kodundan/prioritetindən ASILI OLMAYARAQ (a)/(b) ilə
    --     EYNİ qadağaya tabedir (bax `positions.is_store_tier` sütun şərhi,
    --     §3; domen qarşılığı `PermissionFlag.assert_grantable_to`-dakı
    --     `is_store_tier_role`).
    IF v_position_code IN ('MAGAZA_MENECERI', 'SATICI')
       OR COALESCE(v_priority, 0) >= 4
       OR COALESCE(v_is_store_tier, FALSE) THEN
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

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Sütunun silinməsi trigger-i DƏ qırar (`is_store_tier`-ə istinad edir) —
-- əvvəlcə funksiyanı 048-in gövdəsinə (sütunsuz) qaytarmaq, SONRA sütunu
-- silmək lazımdır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   -- 048-in DOWN-dan ƏVVƏLKİ (`v_is_store_tier`-siz) gövdəsi bura YAPIŞDIRILMALIDIR.
--   ALTER TABLE positions DROP COLUMN IF EXISTS is_store_tier;
-- COMMIT;
-- ===========================================================================
