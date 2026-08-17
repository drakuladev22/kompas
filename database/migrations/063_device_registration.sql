-- ===========================================================================
-- 063 — CİHAZ QEYDİYYATI VƏ FİLİAL TANIMA (DEVICE-1)
-- ===========================================================================
-- Tarix : 2026-08-17
-- Səbəb : Tətbiq indiyə qədər «bu PC hansı filialdadır?» sualına cavab verə
--         bilmirdi. Kamera operatorunun əhatəsi, gündəlik tabel və cərimə
--         yazısı filiala bağlıdır — filial isə istifadəçinin öz profilindən
--         gəlirdi. Yəni bir mağazanın kompüterindən başqa mağazanın adından
--         yazmaq üçün sadəcə həmin mağazanın hesabı ilə girmək kifayət idi.
--
-- ---------------------------------------------------------------------------
-- IP ÜNVANI İSTİFADƏ EDİLMİR — QƏTİ QƏRAR
-- ---------------------------------------------------------------------------
-- Filialı IP ilə tanımaq ilk baxışda pulsuzdur, lakin üç yerdə sınır:
-- dinamik IP dəyişir, bir neçə filial eyni NAT/public IP arxasında ola bilər,
-- VPN/provayder dəyişəndə bağlantı itir. Hər üç halda nəticə EYNİDİR —
-- cərimə/tabel SƏHV filiala yazılır — və qüsur sükutludur, çünki sistem
-- özünü tam işlək hesab edir. Ona görə cihaz ÖZÜNÜ tanıdır və filialı ADMİN
-- təyin edir.
--
-- ---------------------------------------------------------------------------
-- `hardware_fingerprint` KİMLİK DEYİL
-- ---------------------------------------------------------------------------
-- Kimlik `device_id` UUID-idir (`%PROGRAMDATA%`-dakı konfiqurasiyada).
-- Fingerprint ona ƏLAVƏ ölçüdür və UNIQUE DEYİL: disk dəyişdirmək legitim
-- təmirdir, ona görə uyğunsuzluq bloklamır — hadisə audit-ə yazılır və admin
-- qərar verir. `UNIQUE` qoysaydıq, klonlanmış virtual maşınlar (test mühiti)
-- ikinci qeydiyyatı ümumiyyətlə apara bilməzdi.
--
-- XAM seriya nömrələri SAXLANILMIR — yalnız SHA-256 hash-inin ilk 32 simvolu.
-- Xam dəyər saxlansaydı, baza sızması müştərinin bütün avadanlıq inventarını
-- verərdi; bizə lazım olan isə «dəyişdimi» sualıdır, «nədir» sualı deyil.
--
-- ---------------------------------------------------------------------------
-- `short_code` NİYƏ AYRICA SÜTUNDUR
-- ---------------------------------------------------------------------------
-- UUID-nin ilk 6 simvolunu kəsmək olardı, lakin onda kod UUID-nin FUNKSİYASI
-- olardı: kodu bilən adam `device_id`-nin bir hissəsini də bilərdi. Üstəlik
-- UUID hex-dir və `0`/`O`, `1`/`I` qarışıqlığından qaça bilməzdi — halbuki bu
-- kod TELEFONLA söylənilir. Ayrıca sütun məhdudlaşdırılmış əlifba ilə yaranır
-- (`domain/value_objects/devices.py::SHORT_CODE_ALPHABET`).
--
-- ---------------------------------------------------------------------------
-- `store_id` NULL OLA BİLƏR — LAKİN YALNIZ TƏSDİQDƏN ƏVVƏL
-- ---------------------------------------------------------------------------
-- `chk_device_active_has_store` bunu STRUKTUR olaraq qıfıllayır: filialsız
-- `ACTIVE` sətir yaransaydı, DEVICE-1-in həll etdiyi problem geri qayıdardı —
-- üstəlik bu dəfə cihaz «təsdiqlənmiş» görünərdi, yəni daha da gizli olardı.
-- Eyni invariant domendə də var (`entities/registered_device.py::__post_init__`)
-- — `CLAUDE.md` §5-in «hər qayda İKİ yerdə» prinsipi.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. CƏDVƏL
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS registered_devices (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- Aparat izinin hash-i (SHA-256-nın ilk 32 simvolu). UNIQUE DEYİL — bax
    -- fayl başlığı.
    hardware_fingerprint TEXT NOT NULL,
    -- Telefonla söylənilən qeydiyyat kodu. Kirayəçi daxilində unikaldır:
    -- qlobal unikallıq lazım deyil, çünki admin onsuz da öz kirayəçisinin
    -- siyahısına baxır və qlobal UNIQUE fərqli müştərilər arasında (ayrı
    -- Supabase layihələri!) mənasız olardı.
    short_code           TEXT NOT NULL,
    -- Maşının şəbəkə adı — TƏKLİF, kimlik deyil; admin onu dəyişə bilər.
    machine_name         TEXT NOT NULL DEFAULT '',
    -- Admin-in verdiyi ad, məs. «Yataş Babək — Kassa 1».
    device_name          TEXT NOT NULL DEFAULT '',

    store_id             UUID REFERENCES stores(id) ON DELETE RESTRICT,
    device_type          TEXT NOT NULL DEFAULT 'ADMIN_PC'
                             CHECK (device_type IN ('KIOSK', 'ADMIN_PC', 'CAMERA_OPERATOR')),
    status               TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
                             CHECK (status IN ('PENDING_APPROVAL', 'ACTIVE', 'BLOCKED')),
    block_reason         TEXT NOT NULL DEFAULT '',

    registered_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by          UUID REFERENCES employees(id) ON DELETE SET NULL,
    approved_at          TIMESTAMPTZ,
    last_seen_at         TIMESTAMPTZ,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, short_code),
    -- Aktiv cihaz filialsız ola bilməz — bax fayl başlığı.
    CONSTRAINT chk_device_active_has_store
        CHECK (status <> 'ACTIVE' OR store_id IS NOT NULL)
);

COMMENT ON TABLE registered_devices IS
    'Qeydiyyatdan keçmiş PC-lər (migrations/063, DEVICE-1). Filial tanıma IP '
    'ilə DEYİL, bu cədvəllə edilir — səbəb fayl başlığındadır.';

COMMENT ON COLUMN registered_devices.hardware_fingerprint IS
    'Anakart/disk seriyası + Windows machine GUID-in SHA-256 hash-i (32 simvol). '
    'Kimlik DEYİL, dəyişiklik detektorudur: uyğunsuzluq bloklamır, audit-ə düşür.';

COMMENT ON COLUMN registered_devices.short_code IS
    'Telefonla söylənilən qeydiyyat kodu. Qarışan simvollar (0/O, 1/I/L) '
    'əlifbadan çıxarılıb — bax domain/value_objects/devices.py.';

COMMENT ON COLUMN registered_devices.last_seen_at IS
    'Cihazın son dəfə özünü göstərdiyi an. Passivlik həddi (Root parametri) '
    'bundan ölçülür; heç vaxt görünməyibsə registered_at işlədilir.';

-- `updated_at` avtomatik yenilənməsi — sxemdəki mövcud funksiya.
DROP TRIGGER IF EXISTS trg_registered_devices_updated ON registered_devices;
CREATE TRIGGER trg_registered_devices_updated BEFORE UPDATE ON registered_devices
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- TIME-1 (migrations/062): `created_at` server vaxtına məcbur edilir. Yeni
-- cədvəl elə DOĞULARKƏN həmin qapının arxasına qoyulur — sonradan əlavə
-- etmək «hansı cədvəllər qorunur?» sualını yenidən açardı.
DROP TRIGGER IF EXISTS trg_server_created_at_devices ON registered_devices;
CREATE TRIGGER trg_server_created_at_devices
    BEFORE INSERT ON registered_devices
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

-- Admin ekranının ƏSAS sorğusu: «bu kirayəçidə təsdiq gözləyənlər».
CREATE INDEX IF NOT EXISTS idx_devices_pending
    ON registered_devices (tenant_id, registered_at DESC)
    WHERE status = 'PENDING_APPROVAL';

-- Lisenziya sayğacı və filial üzrə axtarış.
CREATE INDEX IF NOT EXISTS idx_devices_active
    ON registered_devices (tenant_id, store_id)
    WHERE status = 'ACTIVE';

-- ---------------------------------------------------------------------------
-- 2. RLS — LAYİHƏNİN ÖZ NAXIŞI
-- ---------------------------------------------------------------------------
-- Siyasət `current_setting('app.tenant_id', true)::uuid` DEYİL,
-- `current_tenant_id()` işlədir və bu, fərq DAVRANIŞ fərqidir: GUC təyin
-- edilməyibsə xam çevirmə `invalid_text_representation` ilə ÇÖKÜR, helper isə
-- `NULL` qaytarır — yəni sorğu boş nəticə verir (fail-closed), xəta yox.
-- Kontekstsiz yol (miqrasiya skripti, `system_scope()`) məhz belə olmalıdır.
--
-- `WITH CHECK` də MƏCBURİDİR: `USING` yalnız OXUNU məhdudlaşdırır. Onsuz
-- başqa kirayəçinin `tenant_id`-si ilə sətir YAZMAQ mümkün olardı.
--
-- Ad `tenant_isolation`-dır — `schema.sql` §-dəki DO dövrəsi və migrations/002
-- eyni adı işlədir; fərqli ad qoysaydıq, gələcək toplu `DROP POLICY IF EXISTS
-- tenant_isolation` təmizliyi bu cədvəli ATLAYARDI.
ALTER TABLE registered_devices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON registered_devices;
CREATE POLICY tenant_isolation ON registered_devices
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 3. İCAZƏ FLAG-İ — `can_manage_devices`
-- ---------------------------------------------------------------------------
-- Dəyərlər sətrin YARANDIĞI anda verilir: `trg_flag_attributes_immutable`
-- (013) yalnız `UPDATE`-ə baxır və sonradan `UPDATE ... SET` yazmaq miqrasiyanı
-- çökdürərdi (056-nın öyrəndiyi dərs).
--
-- `is_anti_fraud = FALSE` — NİYƏ: cihaz təsdiqi cərimə/icazə axınına toxunmur,
-- yəni vəzifə ayrılığı ölçüsündə deyil. Mağaza Meneceri öz filialının yeni
-- kassasını təsdiqləyə bilməlidir; əks halda hər PC dəyişikliyi mərkəzi ofisə
-- zəng tələb edərdi və qayda praktikada «hamıya Root parolu ver» ilə
-- nəticələnərdi.
--
-- `hardlock_level = 3` (DELEGABLE) — NİYƏ: cihaz təsdiqi operativ işdir, lakin
-- LİSENZİYA sayğacına təsir edir (aktiv cihaz sayı = ödəniş əsası). Ona görə
-- flag defolt olaraq Root/CEO/Admin-dədir və AŞAĞI pilləyə yalnız AÇIQ
-- həvalə ilə verilir — «hər satıcı öz noutbukunu qeyd etsin» vəziyyəti
-- təsadüfən yaranmasın.
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only, excludes_camera_role)
VALUES
    ('can_manage_devices', 'ERP_INFRA',
        'Cihazları idarə et',
        'Qeydiyyat gözləyən PC-ləri təsdiqləmək, filiala təyin etmək, '
        'bloklamaq və filialını dəyişmək (DEVICE-1). Təsdiqlənmiş cihaz '
        'lisenziya sayğacına düşdüyü üçün bu, sadə konfiqurasiya deyil — '
        'ona görə həvalə edilə bilən (səviyyə 3) hardlock daşıyır.',
        3, FALSE, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- Sətir əvvəldən mövcud olub və atributları səhvdirsə `UPDATE` mümkün deyil
-- (elə həmin trigger). Sükutla davam etmək flag-i gözləniləndən ZƏİF
-- vəziyyətdə qoyardı — 056 ilə eyni qərar.
DO $$
DECLARE
    v_wrong BOOLEAN;
BEGIN
    SELECT NOT (hardlock_level = 3 AND NOT is_anti_fraud AND NOT is_camera_only)
      INTO v_wrong
      FROM permission_flags
     WHERE code = 'can_manage_devices';

    IF v_wrong THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: "can_manage_devices" flag-i mövcuddur, lakin '
            'atributları gözlənilənlə uyğun deyil (hardlock_level=3, '
            'is_anti_fraud=FALSE, is_camera_only=FALSE).';
    END IF;
END
$$;

-- ROOT/CEO/ADMIN defolt sahiblik. `granted_by` QƏSDƏN NULL (sütun defoltu) —
-- sistem seed-i `enforce_grantor_owns_flag()` istisnasıdır (schema.sql §18).
--
-- SÜTUN VƏ FİLTR 056 İLƏ HƏRFƏN EYNİDİR: `position_permissions` `granted`
-- BOOLEAN saxlayır (`effect` sütunu `user_permission_overrides`-dadır, bu
-- cədvəldə YOXDUR), rol isə `positions.code` ilə seçilir. İkisini qarışdırmaq
-- miqrasiyanı TƏMİZ quraşdırmada çökdürərdi — 056-nın öz tarixçəsində məhz
-- belə bir uyğunsuzluq aylarla gizli qalmışdı.
--
-- HR_ADMIN BURADA YOXDUR: cihaz idarəsi insan resursu işi deyil, infrastruktur
-- işidir və HR_Admin-in gündəlik ekranlarında yeri olmazdı. Lazım olarsa
-- Root fərdi override ilə verə bilər — flag `is_anti_fraud` DEYİL, yəni
-- struktur maneə yoxdur.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_devices', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO', 'ADMIN')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('MAX_REGISTERED_DEVICES', '25', 'INTEGER', '1', '10000',
     'Eyni vaxtda aktiv ola bilən maksimum cihaz sayı (lisenziya həddi)'),
    ('DEVICE_APPROVAL_REQUIRED', '1', 'INTEGER', '0', '1',
     'Yeni cihaz admin təsdiqi gözləsinmi (1) yoxsa avtomatik aktiv olsun (0)'),
    ('DEVICE_INACTIVITY_DAYS', '90', 'INTEGER', '1', '3650',
     'Bu qədər gün görünməyən cihaz avtomatik bloklanır və sayğacdan çıxır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR (032/060/062 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_device_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('MAX_REGISTERED_DEVICES', '25', 'INTEGER', '1', '10000',
         'Eyni vaxtda aktiv ola bilən maksimum cihaz sayı (lisenziya həddi)'),
        ('DEVICE_APPROVAL_REQUIRED', '1', 'INTEGER', '0', '1',
         'Yeni cihaz admin təsdiqi gözləsinmi (1) yoxsa avtomatik aktiv olsun (0)'),
        ('DEVICE_INACTIVITY_DAYS', '90', 'INTEGER', '1', '3650',
         'Bu qədər gün görünməyən cihaz avtomatik bloklanır və sayğacdan çıxır')
      ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_device_limits_for_new_tenant() IS
    'Yeni kirayəçiyə cihaz qeydiyyatı parametrlərini əlavə edir (migrations/063).';

DROP TRIGGER IF EXISTS trg_seed_device_limits ON license_tenants;
CREATE TRIGGER trg_seed_device_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_device_limits_for_new_tenant();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Cədvəlin silinməsi BÜTÜN cihaz təsdiqlərini itirər — hər mağaza yenidən
-- qeydiyyatdan keçməli olar. Yalnız miqrasiyanın özündə qüsur aşkarlandıqda
-- mənalıdır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_device_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_device_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'MAX_REGISTERED_DEVICES', 'DEVICE_APPROVAL_REQUIRED', 'DEVICE_INACTIVITY_DAYS');
--   DELETE FROM position_permissions WHERE flag_code = 'can_manage_devices';
--   DELETE FROM permission_flags WHERE code = 'can_manage_devices';
--   DROP TABLE IF EXISTS registered_devices;
-- COMMIT;
