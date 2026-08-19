-- ===========================================================================
-- 075 — TERMİNAL SƏVİYYƏLİ PIN THROTTLE (SEC-01/SEC-05)
-- ===========================================================================
-- Tarix : 2026-08-19 (dövrə 3-də AÇAR DƏYİŞİKLİYİ ilə YENİDƏN YAZILIB —
--         aşağıdakı "AÇAR NİYƏ store_id DEYİL" bölməsinə bax)
-- Səbəb : SEC-01 audit tapıntısı (dövrə 1) — `employees.pin_locked_until`
--         YALNIZ `AuthenticationUseCase.register_failure()` tərəfindən
--         yazılır və bu metod istehsalatda HEÇ YERDƏN ÇAĞIRILMIR (yalnız
--         testlərdən) — yəni PIN lockout SİYASƏTİ mövcuddur, amma PRAKTİKİ
--         HEÇ VAXT İŞƏ DÜŞMÜR. Struktur səbəb daha DƏRİNDİR: kiosk PIN girişi
--         ANONİMDİR (bölmə 2 — PIN işçi identifikatoru DEYİL,
--         `PinHandshakeUseCase.authenticate()` mağazadakı BÜTÜN namizədləri
--         yoxlayır), yəni yanlış PIN-də "hansı işçi cəhd etdi?" sualının
--         domen səviyyəsində CAVABI YOXDUR — işçi-başına lockout PRİNSİPCƏ
--         əlçatmazdır, sadəcə "unudulmuş kod" deyil.
--
--         Həll TERMİNAL (bu FİZİKİ maşın) səviyyəlidir: "bu terminalda son
--         pəncərədə çox sayda yanlış PIN cəhdi oldu" — kimin cəhd etdiyini
--         BİLMƏDƏN, YENƏ DƏ brute-force sürətini kəsir.
--
-- ---------------------------------------------------------------------------
-- AÇAR NİYƏ `store_id` DEYİL, `machine_key` (SEC-05, dövrə 3 çarpaz-sual)
-- ---------------------------------------------------------------------------
-- İLK versiya `(tenant_id, store_id)` açarı işlədirdi. `security` bunu kod
-- YAZILMAMIŞDAN ƏVVƏL sındırdı: `store_id` YALNIZ `KOMPASOS_STORE_ID` mühit
-- dəyişənindən gəlir (`app.py::_build_kiosk_controller`), istehsalat
-- paketlənməsində `.env` QADAĞANDIR (`main.py::_check_dotenv`) — yəni dəyər
-- `HKCU\Environment`-dədir. Bu, İSTİFADƏÇİ-səviyyəli reyestr budağıdır:
-- paylaşılan kassa PC-sinin ADİ (admin OLMAYAN) Windows sessiyası ONU
-- DƏYİŞDİRƏ BİLƏR. Hücumçu hədə yaxınlaşanda `KOMPASOS_STORE_ID`-i dəyişib
-- TƏZƏ, sıfır-sayğaclı sətir ALARDI — throttle HEÇ VAXT işə düşməzdi.
--
-- Əvəzinə `machine_key` — Windows `MachineGuid`-in (`HKEY_LOCAL_MACHINE\
-- SOFTWARE\Microsoft\Cryptography`, `device_identity.py:36,94`) SHA-256
-- HEŞİ. Bu, ADMİN HÜQUQU OLMADAN dəyişdirilə BİLMƏZ — real maneədir. Xam
-- GUID YOX, HEŞ saxlanılır: cədvəl aparat inventarına çevrilməməlidir
-- (layihə onsuz da hash+pepper vərdişindədir).
--
-- RƏDD EDİLƏN ALTERNATİVLƏR:
--   * `device_id` (`device.json`) — fayl silinsə `register_self()`
--     fingerprint-ə görə axtarmadan YENİ UUID yaradır (`device_registry.
--     py:198`; CLAUDE.md §8: "silinsə cihaz YENİ qeydiyyat yaradır") —
--     yəni faylı silmək sayğacı SIFIRLAYARDI, `MachineGuid`-dən fərqli
--     olaraq bu, ADİ istifadəçi ƏMƏLİYYATIDIR (fayl silmək admin tələb
--     etmir).
--   * Tam `collect_fingerprint()` — WMI probe-u ehtiva edir, HƏR PIN
--     cəhdi üçün baha (`HARDWARE_PROBE_TIMEOUT_SECONDS = 8`-ə qədər);
--     `_read_machine_guid()` isə registry-dən, subprocess-siz, ~0.5 ms.
--
-- `store_id` sütunu SAXLANILIR, LAKİN AÇARIN HİSSƏSİ DEYİL — bax aşağı,
-- "KLON AŞKARLAMASI".
--
-- ---------------------------------------------------------------------------
-- `store_id` NİYƏ HƏLƏ DƏ SÜTUNDUR — KLON AŞKARLAMASI (team-lead əlavəsi)
-- ---------------------------------------------------------------------------
-- Sysprep EDİLMƏMİŞ klon disk imicində N maşın EYNİ `MachineGuid`-i daşıya
-- bilər (Windows quruluşunda yaranır, disk surətinə köçürülür) — bu,
-- `machine_key`-in ÖZÜNÜN zəiflik NÖQTƏSİDİR (bax `docs/build_and_release.
-- md`-ə əlavə olunan quraşdırma xəbərdarlığı). Nəticə: N mağaza EYNİ
-- throttle sətrini paylaşar. Kilid MÜDDƏTLİ olduğu üçün (15 dəq) bu
-- BLOKLAYICI DEYİL, amma GÖRÜNMƏLİDİR. `store_id` HƏR `record_failure()`
-- çağırışında YENİLƏNİR (son görülən mağaza); `PinHandshakeUseCase` sətirdə
-- SAXLANMIŞ `store_id`-i CARİ `store_id` ilə müqayisə edib fərq görsə
-- `SUSPECTED_CLONED_MACHINE_GUID` audit hadisəsi yazır (bloklamır, YALNIZ
-- iz buraxır) — bax `authentication.py`, "KLON AŞKARLAMASI" bölməsi.
-- **Bu sütun AÇAR DEYİL və filtr üçün DEYİL** — YALNIZ eyni maşın
-- açarının müxtəlif mağazalarda görünməsini AŞKARLAMAQ üçündür.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `security_events`-DƏN HESABLANMIR — DEDİKATƏ CƏDVƏL (dövrə 1/2 razılaşması)
-- ---------------------------------------------------------------------------
-- `security_events`-in İSTEHSALAT yazıcısı `FailSoftSecurityEventRecorder`-dir
-- (`shared/security_events.py`) — yazı uğursuz olanda İSTİSNA UDULUR, yalnız
-- `security.log`-a düşür. Əgər throttle QƏRARI bu cədvəldən SAYILAN sətirlərə
-- əsaslansa, YAZI uğursuzluğu pəncərəsində baş verən HƏQİQİ brute-force
-- cəhdləri SAYILMAZ — audit üçün qəbul edilən "fail-soft" güzəşt burada
-- TƏHLÜKƏSİZLİK QAPISININ ÖZÜNÜ zəiflədərdi. Dedikatə cədvəl ÖZ
-- uğursuzluğunu UDMUR və atomik `INSERT ... ON CONFLICT DO UPDATE ...
-- RETURNING`-lə işləyir. `PinHandshakeUseCase` PARALEL olaraq
-- `PIN_TERMINAL_LOCKED` audit hadisəsini `security_events`-ə YAZIR, LAKİN
-- throttle QƏRARI ONDAN GƏLMİR (domen tərəfinin qərarı).
--
-- ---------------------------------------------------------------------------
-- PƏNCƏRƏ MODELİ — SABİT PƏNCƏRƏ, UĞURLU GİRİŞDƏ SIFIRLAMA YOXDUR
-- ---------------------------------------------------------------------------
-- ARCHITECT-in qərarı (`security`-nin arqumenti ilə): əgər İSTƏNİLƏN işçinin
-- uğurlu girişi sayğacı sıfırlasaydı, hücumçu N-1 cəhd edib növbəti QANUNİ
-- girişi gözləməklə sayğacı PULSUZ təmizləyərdi ("səs-küydə gizlənmə") —
-- 30 nəfərlik mağazada bu, hər neçə dəqiqədən bir baş verə bilər. Ona görə
-- BU PROTOKOLDA (`PinThrottleRepository`, `ports.py`) "reset"/"uğurdan sonra
-- sıfırla" metodu QƏSDƏN YOXDUR — YALNIZ `record_failure()` yazır. Sıfırlama
-- İSTİFADƏÇİ-səviyyəli `PinSecurityState`-də (`employees.pin_locked_until`)
-- mənalıdır (orada HƏMİN ŞƏXS öz kimliyini sübut edir), BURADA YOX (kim
-- uğurla girsə də, DİGƏR işçilərin PIN-inə qarşı davam edən sınaq HƏLƏ
-- mümkündür).
--
-- SÜRÜŞKƏN PƏNCƏRƏ (hər cəhd üçün ayrıca sətir/timestamp saxlayan) QƏSDƏN
-- SEÇİLMƏDİ: DƏQİQLİK qazandırardı (dəqiq "son N dəqiqədə neçə cəhd"), amma
-- HƏR PIN cəhdi üçün YENİ sətir yazmaq/saxlamaq/təmizləmək tələb edərdi —
-- SABİT pəncərə (bir sətir, `window_started_at` + `failed_count`) eyni
-- QORUMA effektini VERİR (bir dəfə pəncərə açılır, ya bloklanır, ya təbii
-- bitir) qat-qat AZ mürəkkəbliklə.
--
-- ---------------------------------------------------------------------------
-- VAXT SERVER TƏRƏFİNDƏN MƏCBUR EDİLİR (TIME-1, CLAUDE.md §5)
-- ---------------------------------------------------------------------------
-- `enforce_store_pin_throttle_lockout()` `updated_at`-ı ŞƏRTSİZ, `window_
-- started_at`/`failed_count`/`locked_until`-i isə `system_limits`-dən
-- OXUYARAQ ÖZÜ HESABLAYIR — repository-nin bu sütunlara göndərdiyi HƏR HANSI
-- dəyər (Python-da hesablanmış tarix daxil) sükutla ƏVƏZ OLUNUR. Bu, mağaza
-- PC-sinin saatını geri çəkib throttle-dan qaçmağı bağlayır: qorumanın bütün
-- MƏNASI budur. Naxış `set_fine_appeal_window()` (schema.sql) ilə EYNİDİR:
-- sadəcə `DEFAULT now()` YOX, çünki sütun adı `INSERT`/`UPDATE`-də AÇIQ
-- çəkilə bilər (miqrasiya 062-nin dərsi).
--
-- **BUDAQLANMA SİQNALI:** `record_failure()` HƏMİŞƏ `failed_count`-u
-- `SET failed_count = store_pin_throttle.failed_count + 1` ilə AÇIQ
-- ARTIRIR (bax repository SQL-i, aşağı) — bu, `NEW.failed_count IS DISTINCT
-- FROM OLD.failed_count`-u HƏMİŞƏ TRUE edir. `update_last_seen_store()` isə
-- `failed_count`-a HEÇ TOXUNMUR (`SET` siyahısında yoxdur) — Postgres NEW-i
-- "yalnız SET-də olan sütunlar dəyişir" qaydası ilə qurduğu üçün bu halda
-- `NEW.failed_count = OLD.failed_count` olur. Trigger MƏHZ bu bərabərliyi
-- "bu, sayğac YAZISI DEYİL, YALNIZ store_id yeniləməsidir" siqnalı kimi
-- oxuyur (`enforce_server_published_at()`-in NULL→NOT-NULL keçid-siqnalı
-- ilə EYNİ üslub — dəyər DƏYİŞİKLİYİNİN ÖZÜ niyyəti daşıyır).
--
-- ---------------------------------------------------------------------------
-- KİLİDLİ OXU — REPOZİTORİYANIN ÖZ MƏSULİYYƏTİDİR (bu miqrasiyada YOXDUR)
-- ---------------------------------------------------------------------------
-- Sayğac ARTIRMA yarışa açıqdır: iki paralel PIN cəhdi eyni anda "hələ
-- bloklanmayıb" görüb ikisi də keçə bilər. Kilid `SELECT ... FOR UPDATE`
-- ilə TƏTBİQ QATINDA (`repositories.py`, `PinThrottleRepository.
-- get_for_update`) verilir — `get_for_update` bu protokolun MƏCBURİ
-- üzvüdür (DOM-un `ports.py` şərhi: `RowLockingLeaveRequests`-in isinstance-
-- optional naxışından FƏRQLİ, çünki burada İKİNCİ, DB-səviyyəli qoruma qatı
-- (unikal indeks) YOXDUR). PK `(tenant_id, machine_key)` artıq sətri
-- unikal identifikasiya etdiyi üçün bu miqrasiyada ƏLAVƏ indeksə ehtiyac
-- yoxdur.
--
-- ---------------------------------------------------------------------------
-- FAIL-CLOSED (ARCHITECT-in qərarı)
-- ---------------------------------------------------------------------------
-- Throttle SPESİFİK olaraq OXUNA BİLMİRSƏ (cədvəl yoxdur, icazə xətası,
-- kilid timeout-u) PIN cəhdi RƏDD EDİLMƏLİDİR (tətbiq qatının qərarıdır,
-- bu miqrasiyanın ÖZÜNDƏ məcburiyyət YOXDUR — burada YALNIZ qeyd olunur ki,
-- oxuyan `PinHandshakeUseCase` bu sxemi FAIL-CLOSED fərziyyəsi ilə çağırır).
-- Səbəb: sükutla söndürülmüş qoruma məhz SEC-01-in ÖZÜDÜR — aylarla
-- görünməz qalır.
--
-- ---------------------------------------------------------------------------
-- DEFOLT DƏYƏRLƏR — ƏSASLANDIRMA (`infra` təklifi, ARCHITECT-in son qərarı)
-- ---------------------------------------------------------------------------
-- `KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS = 20`, `KIOSK_STORE_PIN_LOCKOUT_
-- MINUTES = 15`. İlkin təklif 15/15 idi (30 nəfərlik mağazanın 15 dəqiqəlik
-- REAL typo-küyündən — təcrübədə 0-3 aralığında — qat-qat yuxarı), AMMA
-- uğurlu girişdə SIFIRLAMA OLMADIĞI üçün (yuxarı bax) sayğac PƏNCƏRƏ
-- ƏRZİNDƏ TAM AQREQATDIR — növbə-dəyişimi partlayışını (30 nəfər 10
-- dəqiqədə PIN yazır) udmalıdır, ona görə hədd 20-yə YUXARI SÜRÜŞDÜRÜLDÜ.
-- 20 UĞURSUZ CƏHD yenə də real typo-küyündən qat-qat yuxarıdadır (qanuni
-- bloklama ehtimalı praktiki sıfıra yaxın qalır); eyni zamanda 4-rəqəmli
-- PIN fəzasında (10 000 variant, ən çoxu 30 həqiqi kod = ~333 gözlənilən
-- cəhd) hücumçunu ~1.3 cəhd/dəqiqə sürətinə MƏHDUDLAŞDIRIR — tam fəzanı
-- taramaq SAATLARLA fasiləsiz FİZİKİ giriş tələb edir. Min/max sərhədləri
-- (5-50 / 1-60) DƏYİŞMİR — hər iki ifrata (0 = işləməyən qoruma, 999 =
-- əbədi lockout) qapalı qalır.
--
-- ---------------------------------------------------------------------------
-- §7 — YENİ OBYEKTDİR, `schema.sql`-DƏ MÖVCUD TƏRİFİ YENİDƏN YAZMIR
-- ---------------------------------------------------------------------------
-- Cədvəl/trigger/funksiya TAMAMİLƏ YENİDİR — `test_schema_migration_parity.
-- py`-a əlavə lazım deyil.
--
-- ---------------------------------------------------------------------------
-- CANLI BAZADA TƏTBİQ EDİLMƏYİB (dövrə 3 qeydi)
-- ---------------------------------------------------------------------------
-- Bu fayl (əvvəlki versiyası ilə birlikdə) HEÇ VAXT canlı bazaya COMMIT
-- olunmayıb — yalnız ƏVVƏLKİ versiya (fərqli açarla) `DATABASE_ADMIN_URL`
-- ilə ROLLBACK edilən tranzaksiyada sınanmışdı (o sınaq ARTIQ etibarsızdır,
-- çünki açar dəyişib). Bu versiya YALNIZ statik nəzərdən keçirilib —
-- `ARCHITECT`-in AÇIQ İCAZƏSİ olmadan növbəti canlı DDL/yazı aparılmayıb.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. CƏDVƏL
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_pin_throttle (
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    -- SHA-256 hex-digest (`MachineIdentityHash.digest`) — HƏMİŞƏ kiçik hərflə.
    machine_key       TEXT NOT NULL CHECK (machine_key ~ '^[0-9a-f]{64}$'),
    -- AÇARIN HİSSƏSİ DEYİL — bax modul başlığı, "KLON AŞKARLAMASI".
    store_id          UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    failed_count      INTEGER NOT NULL DEFAULT 0,
    window_started_at TIMESTAMPTZ,
    locked_until      TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, machine_key)
);

COMMENT ON TABLE store_pin_throttle IS
    'SEC-01/SEC-05: TERMİNAL (maşın) səviyyəli PIN throttle — PIN anonim '
    'olduğu üçün işçi-başına lockout mümkün deyil, açar isə `store_id` YOX '
    '(admin-siz dəyişdirilə bilər), `machine_key`-dir (migrations/075). '
    'Sətir "ilk uğursuz cəhd"də UPSERT ilə yaranır, əvvəlcədən doldurulmur.';

COMMENT ON COLUMN store_pin_throttle.machine_key IS
    'Windows `MachineGuid`-in SHA-256 heşi (`MachineIdentityHash`, '
    '`device_identity.py`) — ADMİN HÜQUQU olmadan dəyişdirilə BİLMƏZ. '
    '`store_id` (mühit dəyişəni, admin-siz dəyişdirilə bilər) SEC-05 '
    'audit tapıntısına görə RƏDD EDİLDİ.';

COMMENT ON COLUMN store_pin_throttle.store_id IS
    'SON GÖRÜLƏN mağaza — AÇARIN HİSSƏSİ DEYİL VƏ FİLTR ÜÇÜN DEYİL. YALNIZ '
    'klon-aşkarlaması üçün: sysprep edilməmiş klon disk imicində N maşın '
    'eyni `machine_key`-i daşıya bilər (`docs/build_and_release.md`-ə bax) '
    '— bu sütunun dəyişməsi `PinHandshakeUseCase`-ə `SUSPECTED_CLONED_'
    'MACHINE_GUID` siqnalı verir (bloklamır, yalnız iz buraxır).';

COMMENT ON COLUMN store_pin_throttle.failed_count IS
    'Cari (SABİT) pəncərədəki ardıcıl uğursuz PIN cəhdi sayı. Uğurlu girişdə '
    'SIFIRLANMIR (qəsdən — bax modul başlığı, "PƏNCƏRƏ MODELİ") — YALNIZ '
    'pəncərə vaxtı ötəndə təbii sıfırlanır.';

COMMENT ON COLUMN store_pin_throttle.window_started_at IS
    'Sayğacın YIĞILMAĞA başladığı AN — SERVER vaxtı, trigger tərəfindən '
    'məcbur edilir (TIME-1). `KIOSK_STORE_PIN_LOCKOUT_MINUTES` qədər vaxt '
    'ötübsə sayğac YENİDƏN başlayır. Domen qatına ÇATMIR (`TerminalPinThrottle` '
    'bu sahəni daşımır) — YALNIZ DB-daxili hesablama üçündür.';

COMMENT ON COLUMN store_pin_throttle.locked_until IS
    'Bu andan ƏVVƏL yeni PIN cəhdi RƏDD edilməlidir. `NULL` = bloklanmayıb. '
    'Dəyər trigger tərəfindən `now() + KIOSK_STORE_PIN_LOCKOUT_MINUTES` kimi '
    'HESABLANIR — repository-nin göndərdiyi HƏR HANSI dəyər nəzərə alınmır.';

COMMENT ON COLUMN store_pin_throttle.updated_at IS
    'TIME-1: hər yazıda server vaxtına ŞƏRTSİZ məcbur edilir (diaqnostika — '
    '"bu sətir SON DƏFƏ NƏ VAXT toxunulub").';

-- ---------------------------------------------------------------------------
-- 2. RLS — LAYİHƏNİN ÖZ NAXIŞI (`tenant_branding`, migrations/064 ilə EYNİ)
-- ---------------------------------------------------------------------------
ALTER TABLE store_pin_throttle ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON store_pin_throttle;
CREATE POLICY tenant_isolation ON store_pin_throttle
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 3. TIME-1 + THROTTLE MƏNTİQİ — VAHİD TRIGGER FUNKSİYASI
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_store_pin_throttle_lockout()
RETURNS TRIGGER AS $$
DECLARE
    v_max_attempts    INTEGER;
    v_lockout_minutes INTEGER;
BEGIN
    -- TIME-1: sütun ŞƏRTSİZ server vaxtına məcbur edilir (bax modul başlığı,
    -- `enforce_server_created_at()` ilə eyni fəlsəfə).
    NEW.updated_at := now();

    -- `TG_OP = 'INSERT'` AYRICA, BİRİNCİ yoxlanılır: `OLD` INSERT trigger-ində
    -- TƏYİN OLUNMAYIB (bağlanmamış sətirdir, sadəcə `NULL` skalyar DEYİL) —
    -- İKİ AYRI budaq, birinci `OLD`-a HEÇ TOXUNMUR.
    IF TG_OP = 'INSERT' THEN
        NEW.window_started_at := now();
        NEW.failed_count := 1;
        NEW.locked_until := NULL;
        RETURN NEW;
    END IF;

    -- BUDAQLANMA SİQNALI (bax modul başlığı): bu, `update_last_seen_store()`
    -- çağırışıdır (YALNIZ `store_id` dəyişir, sayğac/kilid TOXUNULMUR).
    IF NEW.failed_count = OLD.failed_count THEN
        RETURN NEW;
    END IF;

    -- Bu nöqtədən sonra `record_failure()`-dir — `OLD` TƏHLÜKƏSİZ istinad
    -- edilə bilər.
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

    -- PƏNCƏRƏ BİTİBMİ — DÜZƏLİŞ (team-lead-in tapdığı dizayn qüsuru,
    -- dövrə 3 çarpaz-sual): SƏHV versiya YALNIZ `window_started_at +
    -- lockout_minutes`-i yoxlayırdı. Bu, `locked_until`-dan SİSTEMATİK
    -- FƏRQLİDİR: `locked_until` HƏDD AŞILAN ANDA (`now() + lockout`)
    -- hesablanır, `window_started_at` isə pəncərənin BİRİNCİ uğursuz
    -- cəhdinin anıdır — ARADA vaxt keçə bilər (məs. sayğac 10-cu dəqiqədə
    -- həddə çatır, kilid 25-ci dəqiqəyə qədər davam edir), yəni
    -- `locked_until` HƏMİŞƏ `window_started_at + lockout`-dan SONRA və ya
    -- ONA BƏRABƏRDİR. Köhnə şərt kilid HƏLƏ QÜVVƏDƏYKƏN (15-ci dəqiqədə)
    -- pəncərəni "bitmiş" sayıb sayğacı VAXTINDAN ƏVVƏL sıfırlayırdı —
    -- terminalı FAKTİKİ kilid müddətindən TEZ açırdı.
    --
    -- DOĞRU QAYDA: `locked_until` DOLUDURSA (kilid BAŞ VERİB), YEGANƏ
    -- etibarlı mənbə ODUR. `locked_until` HƏLƏ NULL-dırsa (bu pəncərədə
    -- HƏLƏ hədd aşılmayıb), pəncərənin ÖZÜ `window_started_at + lockout`
    -- ilə bitir.
    --
    -- SƏRHƏD (`now() = locked_until`): domendəki `TerminalPinThrottle.
    -- is_locked()` `now < locked_until` (SƏRT) işlədir — yəni `now =
    -- locked_until` ANINDA artıq "bloklanmayıb". Bura görə `<=` (bərabərlik
    -- DAXİL) işlədilir ki, EYNİ ANDA iki qərar TOQQUŞMASIN: `is_locked()`
    -- `False` deyirsə, trigger DƏ pəncərəni "bitib" saymalıdır — əks halda
    -- domen "açıqdır" deyər, DB isə köhnə sayğacı SAXLAYIB YENİ cəhdi
    -- artırar, nəticədə sayğac HƏDDİ DƏRHAL YENİDƏN AŞAR (əbədi-kilid
    -- riski, `qa`-nın tapdığı sərhəd ssenarisi).
    --
    -- QƏSDƏN İKİQAT QAYDA (CLAUDE.md §5): bu SƏRT sərhəd EYNİ ZAMANDA
    -- `TerminalPinThrottle.advance_after_failure()`-də (Python, dövrə 4,
    -- `value_objects/pin_throttle.py`) TƏKRARLANIR — o, `InMemoryPinThrottle`
    -- sınaq sahtəsinin icra etdiyi spesifikasiyadır. BİRİNİ dəyişən DİGƏRİNİ
    -- DƏ dəyişməlidir, əks halda SQL və Python fərqli anda fərqli qərar verər.
    IF OLD.window_started_at IS NULL
       OR (OLD.locked_until IS NOT NULL AND OLD.locked_until <= now())
       OR (OLD.locked_until IS NULL
           AND OLD.window_started_at + make_interval(mins => v_lockout_minutes) <= now()) THEN
        NEW.window_started_at := now();
        NEW.failed_count := 1;
        NEW.locked_until := NULL;
        RETURN NEW;
    END IF;

    -- ARTIQ KİLİDLİDİR (`locked_until` doludur VƏ hələ keçməyib — yuxarıdakı
    -- pəncərə-bitmə şərti bunu artıq İSTİSNA edib) — DÜZƏLİŞ (team-lead-in
    -- tapdığı İKİNCİ qüsur): SƏHV versiya bu halda da sayğacı artırır VƏ
    -- `locked_until`-u HƏR YENİ cəhddə YENİDƏN hesablayırdı — nəticə, davam
    -- edən hücumçu kilidi SONSUZA qədər UZADA bilirdi (hər cəhd növbəti
    -- `lockout_minutes`-i sıfırdan başladırdı). DOĞRU DAVRANIŞ: kilid MÜDDƏTİ
    -- artıq TƏYİN OLUNUB — sayğac DONUR, `locked_until` UZANMIR. Yeni cəhd
    -- YALNIZ `updated_at`-ı görür (yuxarıda artıq tətbiq olunub).
    IF OLD.locked_until IS NOT NULL AND OLD.locked_until > now() THEN
        NEW.window_started_at := OLD.window_started_at;
        NEW.failed_count := OLD.failed_count;
        NEW.locked_until := OLD.locked_until;
        RETURN NEW;
    END IF;

    -- EYNİ pəncərədə DAVAM, HƏLƏ KİLİDLİ DEYİL — sayğac OLD-dan artırılır
    -- (client-in göndərdiyi dəyər YOX), həddə YENİ çatanda kilid TƏYİN olunur.
    NEW.window_started_at := OLD.window_started_at;
    NEW.failed_count := OLD.failed_count + 1;
    IF NEW.failed_count >= v_max_attempts THEN
        NEW.locked_until := now() + make_interval(mins => v_lockout_minutes);
    ELSE
        NEW.locked_until := OLD.locked_until;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_store_pin_throttle_lockout() IS
    'SEC-01/TIME-1: PIN throttle sayğacını VƏ vaxt sahələrini SERVER '
    'tərəfindən hesablayır — client dəyəri (saat manipulyasiyası daxil) '
    'nəzərə alınmır (migrations/075). `update_last_seen_store()` (yalnız '
    'store_id yeniləməsi) BUDAN İSTİSNADIR — bax funksiya gövdəsindəki '
    '"BUDAQLANMA SİQNALI" şərhi.';

DROP TRIGGER IF EXISTS trg_store_pin_throttle_lockout ON store_pin_throttle;
CREATE TRIGGER trg_store_pin_throttle_lockout
    BEFORE INSERT OR UPDATE ON store_pin_throttle
    FOR EACH ROW EXECUTE FUNCTION enforce_store_pin_throttle_lockout();

-- ---------------------------------------------------------------------------
-- 4. `system_limits` DEFOLT DƏYƏRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS', '20', 'INTEGER', '5', '50',
     'Terminal PIN throttle: pəncərədə icazə verilən ardıcıl uğursuz cəhd '
     'sayı — bundan sonra terminal müvəqqəti bloklanır (SEC-01/SEC-05)'),
    ('KIOSK_STORE_PIN_LOCKOUT_MINUTES', '15', 'INTEGER', '1', '60',
     'Terminal PIN throttle: HƏM sayğacın yığıldığı pəncərə, HƏM DƏ kilidin '
     'müddəti (dəqiqə) — iki ayrı dəyər QƏSDƏN yoxdur (bax modul başlığı, '
     'SEC-01/SEC-05)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. `system_limits` DEFOLT DƏYƏRLƏRİ — YENİ KİRAYƏÇİLƏR (062/072 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_pin_throttle_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS', '20', 'INTEGER', '5', '50',
         'Terminal PIN throttle: pəncərədə icazə verilən ardıcıl uğursuz cəhd '
         'sayı (SEC-01/SEC-05)'),
        (NEW.tenant_id, 'KIOSK_STORE_PIN_LOCKOUT_MINUTES', '15', 'INTEGER', '1', '60',
         'Terminal PIN throttle: pəncərə + kilid müddəti, dəqiqə (SEC-01/SEC-05)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_pin_throttle_limits_for_new_tenant() IS
    'Yeni kirayəçiyə SEC-01/SEC-05 PIN throttle parametrlərini əlavə edir '
    '(migrations/075). `seed_tenant_defaults()` toxunulmadan qalır (062/072 '
    'presedenti).';

DROP TRIGGER IF EXISTS trg_seed_pin_throttle_limits ON license_tenants;
CREATE TRIGGER trg_seed_pin_throttle_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_pin_throttle_limits_for_new_tenant();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_pin_throttle_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_pin_throttle_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS', 'KIOSK_STORE_PIN_LOCKOUT_MINUTES');
--   DROP TRIGGER IF EXISTS trg_store_pin_throttle_lockout ON store_pin_throttle;
--   DROP FUNCTION IF EXISTS enforce_store_pin_throttle_lockout();
--   DROP TABLE IF EXISTS store_pin_throttle;
-- COMMIT;
