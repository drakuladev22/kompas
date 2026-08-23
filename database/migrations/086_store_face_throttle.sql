-- ===========================================================================
-- 086 — `store_face_throttle`: 1:N ÜZLƏ girişin AYRI terminal sayğacı (AF-2)
-- ===========================================================================
-- ---------------------------------------------------------------------------
-- NİYƏ AYRI CƏDVƏL — SƏNƏDLİ QƏRAR NİYƏ GERİ ALINDI
-- ---------------------------------------------------------------------------
-- `identify_for_login()` (1:N üz girişi) rəddləri indiyə qədər
-- `store_pin_throttle`-a, yəni PIN girişi ilə ORTAQ sayğaca yazılırdı. Həmin
-- qərar sənədli idi (`face_control.py`): «iki müstəqil sayğac hücumçuya
-- büdcəni İKİ QAT edərdi, halbuki qorunan şey EYNİ terminaldır».
--
-- Lakin o mühakimə «eyni terminalda EYNİ ADAM cəhd edir» fərziyyəsinə
-- əsaslanır. 1:N üz girişində belə fərziyyə YOXDUR: kameranın qarşısına keçən
-- İSTƏNİLƏN adam — mağazanın işçisi olmayan kənar şəxs daxil — sayğacı artırır
-- və heç bir kimlik təqdim etmir. Nəticədə kameraya bir neçə dəfə baxmaqla
-- BÜTÜN mağazanın PIN girişi dayandırıla bilirdi: qoruma XİDMƏTDƏN İMTİNA
-- vasitəsinə çevrilirdi (AF-2 auditinin tapıntısı).
--
-- SİYASƏT QƏRARI: DoS vektoru aradan qaldırılır, terminalın ümumi cəhd
-- büdcəsinin iki qat olması isə QƏBUL EDİLİR. Kompensasiya Root-un əlindədir —
-- hər iki kanal EYNİ `KIOSK_STORE_PIN_*` açarlarını oxuyur (aşağı bax), yəni
-- həddi endirmək İKİSİNƏ DƏ eyni anda tətbiq olunur.
--
-- ---------------------------------------------------------------------------
-- YENİ ROOT AÇARI YARADILMIR — VƏ BU, QƏNAƏT DEYİL, QƏRARDIR
-- ---------------------------------------------------------------------------
-- Üz kanalı `KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS` və
-- `KIOSK_STORE_PIN_LOCKOUT_MINUTES` dəyərlərini PAYLAŞIR. Ayrı açar olsaydı,
-- «bu terminalın ümumi cəhd büdcəsi nə qədərdir?» sualının cavabı İKİ sətrin
-- cəmindən çıxarılmalı olardı və Root birini dəyişib digərini unudardı.
-- Bu miqrasiya `system_limits`-ə HEÇ NƏ əlavə etmir (075 onları artıq seed
-- edib) — yəni yeni seed trigger-i də YOXDUR.
--
-- ---------------------------------------------------------------------------
-- TRIGGER `075`-İN EYNİSİDİR — TƏKRAR QƏSDƏNDİR
-- ---------------------------------------------------------------------------
-- Sabit-pəncərə hesablaması, TIME-1 məcburiyyəti və «pəncərə bitibmi»
-- düzəlişi (bax 075-in həmin bölməsi) SÖZBƏSÖZ təkrarlanır, çünki qayda
-- EYNİDİR — fərq yalnız hansı KANALIN sayılmasındadır. Ortaq funksiya
-- yazmaq cədvəl adını parametrləşdirmək (dinamik SQL) tələb edərdi və
-- `enforce_*` funksiyalarının hamısı layihədə statik yazılıb.
--
-- «BUDAQLANMA SİQNALI» (`NEW.failed_count = OLD.failed_count`) blokunun
-- ANALOQU BURADA DA SAXLANILIR, LAKİN üz repozitoriyasında
-- `update_last_seen_store()` YOXDUR (klon aşkarlaması PIN yolunda qalır —
-- səbəb `face_throttle_repository.py` başlığındadır). Blok gələcək çağırış
-- üçün deyil, İKİ trigger-in bir-birindən SÜKUTLA ayrılmaması üçündür:
-- birində olub digərində olmayan qol, sonrakı oxucu üçün «hansı doğrudur?»
-- sualı yaradardı.
--
-- ---------------------------------------------------------------------------
-- §7 — YENİ OBYEKTDİR, `schema.sql`-DƏ MÖVCUD TƏRİFİ YENİDƏN YAZMIR
-- ---------------------------------------------------------------------------
-- Cədvəl, funksiya və trigger TAMAMİLƏ YENİDİR (`store_pin_throttle` kimi
-- `schema.sql`-də ÜMUMİYYƏTLƏ yoxdur) — paritet siyahısına əlavə lazım deyil.
--
-- İDEMPOTENT: `CREATE TABLE IF NOT EXISTS` + `CREATE OR REPLACE FUNCTION` +
-- `DROP TRIGGER IF EXISTS`. DOWN bloku sonda şərh içindədir.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. CƏDVƏL
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_face_throttle (
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    -- SHA-256 hex-digest (`MachineIdentityHash.digest`) — HƏMİŞƏ kiçik hərflə.
    machine_key       TEXT NOT NULL CHECK (machine_key ~ '^[0-9a-f]{64}$'),
    -- AÇARIN HİSSƏSİ DEYİL (075 ilə eyni qərar) — SON GÖRÜLƏN mağaza.
    store_id          UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    failed_count      INTEGER NOT NULL DEFAULT 0,
    window_started_at TIMESTAMPTZ,
    locked_until      TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, machine_key)
);

COMMENT ON TABLE store_face_throttle IS
    'AF-2: 1:N ÜZLƏ girişin TERMİNAL sayğacı — `store_pin_throttle`-dan AYRI. '
    'Ortaq sayğac zamanı kameraya baxan kənar şəxs bütün mağazanın PIN '
    'girişini dayandıra bilirdi (xidmətdən imtina). Hədd hər iki kanal üçün '
    'EYNİ `KIOSK_STORE_PIN_*` açarlarındandır (migrations/086).';

COMMENT ON COLUMN store_face_throttle.machine_key IS
    'Windows `MachineGuid`-in SHA-256 heşi (`MachineIdentityHash`) — admin '
    'hüququ olmadan dəyişdirilə BİLMƏZ. `store_id` açar kimi SEC-05-ə görə '
    'RƏDD EDİLİB (bax migrations/075).';

COMMENT ON COLUMN store_face_throttle.store_id IS
    'SON GÖRÜLƏN mağaza — AÇARIN HİSSƏSİ DEYİL. Üz yolunda klon-aşkarlaması '
    'APARILMIR (o, PIN yolunda qalır), sütun diaqnostika üçün saxlanılır: '
    '«bu terminal hansı mağazada idi?».';

COMMENT ON COLUMN store_face_throttle.failed_count IS
    'Cari (SABİT) pəncərədəki uğursuz 1:N ÜZ cəhdlərinin sayı. Uğurlu girişdə '
    'SIFIRLANMIR (075 ilə eyni qərar: sıfırlama olsaydı hücumçu N-1 cəhddən '
    'sonra qanuni girişi gözləyib sayğacı pulsuz təmizləyərdi).';

COMMENT ON COLUMN store_face_throttle.window_started_at IS
    'Sayğacın YIĞILMAĞA başladığı AN — SERVER vaxtı, trigger məcbur edir '
    '(TIME-1). Domen qatına ÇATMIR.';

COMMENT ON COLUMN store_face_throttle.locked_until IS
    'Bu andan ƏVVƏL yeni ÜZ cəhdi RƏDD edilməlidir. `NULL` = bloklanmayıb. '
    'PIN girişi BU sütundan ASILI DEYİL — AF-2-nin bütün mahiyyəti budur.';

COMMENT ON COLUMN store_face_throttle.updated_at IS
    'TIME-1: hər yazıda server vaxtına ŞƏRTSİZ məcbur edilir (diaqnostika).';

-- ---------------------------------------------------------------------------
-- 2. RLS — 075/064 NAXIŞI
-- ---------------------------------------------------------------------------
ALTER TABLE store_face_throttle ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON store_face_throttle;
CREATE POLICY tenant_isolation ON store_face_throttle
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 3. TIME-1 + THROTTLE MƏNTİQİ (075-in EYNİSİ, bax başlıq)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_store_face_throttle_lockout()
RETURNS TRIGGER AS $$
DECLARE
    v_max_attempts    INTEGER;
    v_lockout_minutes INTEGER;
BEGIN
    NEW.updated_at := now();

    IF TG_OP = 'INSERT' THEN
        NEW.window_started_at := now();
        NEW.failed_count := 1;
        NEW.locked_until := NULL;
        RETURN NEW;
    END IF;

    -- BUDAQLANMA SİQNALI (bax başlıq): sayğaca toxunmayan yazı sayğacı
    -- irəli aparmır. Üz repozitoriyasında belə çağırış HAZIRDA YOXDUR —
    -- qol İKİ trigger-in eyni qalması üçün saxlanılır.
    IF NEW.failed_count = OLD.failed_count THEN
        RETURN NEW;
    END IF;

    -- HƏDD PIN KANALI İLƏ ORTAQDIR (bax başlıq) — yeni açar oxunmur.
    SELECT COALESCE(
             (SELECT limit_value::INTEGER FROM system_limits
               WHERE tenant_id = NEW.tenant_id
                 AND limit_key = 'KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS'),
             20
           ) INTO v_max_attempts;
    SELECT COALESCE(
             (SELECT limit_value::INTEGER FROM system_limits
               WHERE tenant_id = NEW.tenant_id
                 AND limit_key = 'KIOSK_STORE_PIN_LOCKOUT_MINUTES'),
             15
           ) INTO v_lockout_minutes;

    -- PƏNCƏRƏ BİTİBMİ — 075-dəki DÜZƏLDİLMİŞ qayda: `locked_until` doludursa
    -- YEGANƏ etibarlı mənbə ODUR (kilid həddin AŞILDIĞI anda hesablanır və
    -- `window_started_at + lockout`-dan SONRA bitir); `NULL` isə pəncərənin
    -- öz sərhədi ilə yoxlanılır.
    IF (OLD.locked_until IS NOT NULL AND now() >= OLD.locked_until)
       OR (OLD.locked_until IS NULL
           AND OLD.window_started_at IS NOT NULL
           AND now() >= OLD.window_started_at + make_interval(mins => v_lockout_minutes))
    THEN
        NEW.window_started_at := now();
        NEW.failed_count := 1;
        NEW.locked_until := NULL;
        RETURN NEW;
    END IF;

    NEW.window_started_at := COALESCE(OLD.window_started_at, now());
    NEW.failed_count := OLD.failed_count + 1;
    IF NEW.failed_count >= v_max_attempts THEN
        NEW.locked_until := now() + make_interval(mins => v_lockout_minutes);
    ELSE
        NEW.locked_until := OLD.locked_until;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_store_face_throttle_lockout() IS
    'AF-2/TIME-1: 1:N üz throttle sayğacını VƏ vaxt sahələrini SERVER '
    'tərəfindən hesablayır (migrations/086). Məntiq '
    '`enforce_store_pin_throttle_lockout()` ilə EYNİDİR — fərq yalnız '
    'sayılan KANALDADIR; hədd açarları PAYLAŞILIR.';

DROP TRIGGER IF EXISTS trg_store_face_throttle_lockout ON store_face_throttle;
CREATE TRIGGER trg_store_face_throttle_lockout
    BEFORE INSERT OR UPDATE ON store_face_throttle
    FOR EACH ROW EXECUTE FUNCTION enforce_store_face_throttle_lockout();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Geri qaytarma DATA İTKİSİ DEYİL: cədvəl YALNIZ efemer sayğac saxlayır —
-- silinsə terminal «hələ uğursuz üz cəhdi olmayıb» vəziyyətinə düşür.
-- LAKİN DAVRANIŞ GERİ QAYIDIR: `face_throttle` portu bağlı qalarsa tətbiq
-- mövcud olmayan cədvələ yazmağa çalışar — ona görə ƏVVƏLCƏ kompozisiya
-- kökündə port söndürülməli, SONRA cədvəl silinməlidir.
--
-- BEGIN;
--   DROP TRIGGER IF EXISTS trg_store_face_throttle_lockout ON store_face_throttle;
--   DROP FUNCTION IF EXISTS enforce_store_face_throttle_lockout();
--   DROP TABLE IF EXISTS store_face_throttle;
-- COMMIT;
-- ===========================================================================
