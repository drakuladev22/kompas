-- ===========================================================================
-- 090 — `support_chat_throttle`: DƏSTƏK-ÇATDA SUİ-İSTİFADƏ QORUNMASI (Faza 12.1)
-- ===========================================================================
-- Tarix : 2026-08-24
-- Mənbə : `v2backlog.md` FAZA 1 / FAZA 12.1: "ROOT PARAMETRİ: dəqiqədə
--         maksimum mesaj sayı — bu həddi aşan istifadəçi müvəqqəti
--         məhdudlaşdırılır (mövcud PIN-lockout pattern-inə bənzər)".
--
-- ---------------------------------------------------------------------------
-- NİYƏ AYRI CƏDVƏL, `store_pin_throttle`-un GENİŞLƏNMƏSİ DEYİL
-- ---------------------------------------------------------------------------
-- `store_pin_throttle`/`store_face_throttle` TERMİNAL-mərkəzlidir (açar:
-- `tenant_id, machine_key` — "bu CİHAZ neçə səhv verdi?"). Dəstək-çat
-- sui-istifadəsi isə İSTİFADƏÇİ-mərkəzlidir (açar: `tenant_id, employee_id`
-- — "bu ADAM dəqiqədə neçə mesaj yazır?") və mövzu tamamilə fərqlidir (PIN
-- girişi ↔ dəstək mesajı). İkisini EYNİ cədvəldə saxlamaq açar sxemini
-- (machine_key vs employee_id) şərti sütunlarla çirkləndirərdi.
--
-- ---------------------------------------------------------------------------
-- PƏNCƏRƏ MODELİ — `store_pin_throttle`-DAN NİYƏ FƏRQLİDİR
-- ---------------------------------------------------------------------------
-- PIN throttle-da pəncərə "N səhvdən sonra LOCKOUT_MINUTES qıfılla" modelidir
-- (pəncərənin uzunluğu ÖZÜ lockout müddətidir). Faza 12.1-in tələbi isə
-- HƏRFİ "dəqiqədə maksimum mesaj sayı"dır — pəncərə SABİT 1 DƏQİQƏDİR
-- (tələbin TƏRİFİNİN özüdür, Root parametri DEYİL — `_WEEKLY_DEDUPE_GAP_
-- DAYS` kimi "sözün mənasının özü" sabitlərinin eyni kateqoriyası, CLAUDE.md
-- §5 "ÜÇÜNCÜ hal"). Aşılanda tətbiq olunan QIFIL müddəti isə AYRI Root
-- parametridir (`SUPPORT_CHAT_LOCKOUT_MINUTES`) — sənəddə ADI ÇƏKİLMƏYİB,
-- amma "müvəqqəti məhdudlaşdırılır" ifadəsi müddət olmadan icra edilə
-- bilməz, ona görə əlavə olunur (`security` bunu webhook `secret`-i kimi
-- eyni "əlavə, sənəddə yazılmayan, amma zəruri" kateqoriyasında təsdiqləyib).
--
-- ---------------------------------------------------------------------------
-- `SUPPORT_CHAT_MAX_MESSAGES_PER_MINUTE`/`SUPPORT_CHAT_LOCKOUT_MINUTES` BU
-- MİQRASİYADA SEED EDİLMİR
-- ---------------------------------------------------------------------------
-- `SystemLimitKey`/`DEFAULT_LIMITS` DOMEN qatındadır (`policies.py`,
-- CLAUDE.md §5 cədvəli) — bu, mənim sahəm DEYİL. Trigger aşağıda hər iki
-- açarı `COALESCE(..., <fallback>)` ilə oxuyur ki, domen kodu HƏLƏ yazılmasa
-- belə (sətir `system_limits`-də yoxdursa) funksiya ÇÖKMƏSİN — `store_face_
-- throttle` (migrations/086) EYNİ ehtiyatı göstərir. Domen `SystemLimitKey`
-- əlavə edəndən SONRA SQL seed-i 084-ün naxışı ilə AYRI miqrasiyada gəlməlidir.
--
-- ---------------------------------------------------------------------------
-- RLS: standart `tenant_isolation`. TIME-1: `window_started_at`/`locked_
-- until`/`updated_at` trigger vasitəsilə SERVER vaxtına məcbur edilir (aşağı,
-- `store_face_throttle` ilə EYNİ struktur).
--
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7) —
-- cədvəl TAMAMİLƏ YENİDİR, mövcud tərifi yenidən yazmır.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. CƏDVƏL
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS support_chat_throttle (
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    employee_id       UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    message_count     INTEGER NOT NULL DEFAULT 0,
    window_started_at TIMESTAMPTZ,
    locked_until      TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, employee_id)
);

COMMENT ON TABLE support_chat_throttle IS
    'Faza 12.1 (v2backlog.md): dəstək-çat mesaj sürəti sayğacı. `store_pin_'
    'throttle`-un GENİŞLƏNMƏSİ DEYİL — açar İSTİFADƏÇİ-mərkəzlidir (o, '
    'TERMİNAL-mərkəzlidir), bax fayl başlığı. `PENDING_VERIFICATION` kimi '
    'status YOXDUR: bu, sadəcə sayğacdır, iş axını deyil (migrations/090).';

COMMENT ON COLUMN support_chat_throttle.message_count IS
    'Cari SABİT 1-dəqiqəlik pəncərədəki mesaj sayı. `store_face_throttle` ilə '
    'eyni qərar: uğurlu (bloklanmamış) mesajda da SIFIRLANMIR — pəncərə '
    'YALNIZ vaxt bitəndə sıfırlanır (aşağı trigger).';

COMMENT ON COLUMN support_chat_throttle.window_started_at IS
    'Pəncərənin YIĞILMAĞA başladığı AN — SERVER vaxtı, trigger məcbur edir '
    '(TIME-1). Domen qatına ÇATMIR.';

COMMENT ON COLUMN support_chat_throttle.locked_until IS
    'Bu andan ƏVVƏL yeni dəstək mesajı RƏDD edilməlidir. NULL = '
    'bloklanmayıb.';

COMMENT ON COLUMN support_chat_throttle.updated_at IS
    'TIME-1: hər yazıda server vaxtına ŞƏRTSİZ məcbur edilir (diaqnostika).';

-- ---------------------------------------------------------------------------
-- 2. RLS — 086/075 NAXIŞI
-- ---------------------------------------------------------------------------
ALTER TABLE support_chat_throttle ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON support_chat_throttle;
CREATE POLICY tenant_isolation ON support_chat_throttle
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 3. TIME-1 + THROTTLE MƏNTİQİ
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_support_chat_throttle_lockout()
RETURNS TRIGGER AS $$
DECLARE
    v_max_per_minute  INTEGER;
    v_lockout_minutes INTEGER;
BEGIN
    NEW.updated_at := now();

    IF TG_OP = 'INSERT' THEN
        NEW.window_started_at := now();
        NEW.message_count := 1;
        NEW.locked_until := NULL;
        RETURN NEW;
    END IF;

    -- BUDAQLANMA SİQNALI (`store_face_throttle` ilə eyni naxış): sayğaca
    -- toxunmayan yazı sayğacı irəli aparmır.
    IF NEW.message_count = OLD.message_count THEN
        RETURN NEW;
    END IF;

    -- Açarlar YALNIZ bu cədvəl üçündür — `SUPPORT_CHAT_*` heç bir başqa
    -- kanalla PAYLAŞILMIR (bax fayl başlığı, `store_face_throttle`-dan fərq).
    SELECT COALESCE(
             (SELECT limit_value::INTEGER FROM system_limits
               WHERE tenant_id = NEW.tenant_id
                 AND limit_key = 'SUPPORT_CHAT_MAX_MESSAGES_PER_MINUTE'),
             20
           ) INTO v_max_per_minute;
    SELECT COALESCE(
             (SELECT limit_value::INTEGER FROM system_limits
               WHERE tenant_id = NEW.tenant_id
                 AND limit_key = 'SUPPORT_CHAT_LOCKOUT_MINUTES'),
             5
           ) INTO v_lockout_minutes;

    -- PƏNCƏRƏ BİTİBMİ — SABİT 1 DƏQİQƏ (bax fayl başlığı: bu, tələbin
    -- TƏRİFİDİR, Root parametri DEYİL). `store_pin_throttle`-un "düzəldilmiş
    -- qayda"sı ilə eyni: `locked_until` doludursa YEGANƏ etibarlı mənbə
    -- ODUR.
    IF (OLD.locked_until IS NOT NULL AND now() >= OLD.locked_until)
       OR (OLD.locked_until IS NULL
           AND OLD.window_started_at IS NOT NULL
           AND now() >= OLD.window_started_at + INTERVAL '1 minute')
    THEN
        NEW.window_started_at := now();
        NEW.message_count := 1;
        NEW.locked_until := NULL;
        RETURN NEW;
    END IF;

    NEW.window_started_at := COALESCE(OLD.window_started_at, now());
    NEW.message_count := OLD.message_count + 1;
    IF NEW.message_count >= v_max_per_minute THEN
        NEW.locked_until := now() + make_interval(mins => v_lockout_minutes);
    ELSE
        NEW.locked_until := OLD.locked_until;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_support_chat_throttle_lockout() IS
    'Faza 12.1/TIME-1: dəstək-çat mesaj sayğacını VƏ vaxt sahələrini SERVER '
    'tərəfindən hesablayır (migrations/090). Pəncərə SABİT 1 dəqiqədir '
    '(tələbin tərifi), hədd və qıfıl müddəti `system_limits`-dən oxunur.';

DROP TRIGGER IF EXISTS trg_support_chat_throttle_lockout ON support_chat_throttle;
CREATE TRIGGER trg_support_chat_throttle_lockout
    BEFORE INSERT OR UPDATE ON support_chat_throttle
    FOR EACH ROW EXECUTE FUNCTION enforce_support_chat_throttle_lockout();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Geri qaytarma DATA İTKİSİ DEYİL: cədvəl YALNIZ efemer sayğac saxlayır —
-- silinsə istifadəçi "hələ heç bir sui-istifadə cəhdi olmayıb" vəziyyətinə
-- düşür. LAKİN DAVRANIŞ GERİ QAYIDIR: dəstək-çat port bağlı qalarsa tətbiq
-- mövcud olmayan cədvələ yazmağa çalışar — ƏVVƏLCƏ kompozisiya kökündə port
-- söndürülməli, SONRA cədvəl silinməlidir (`store_face_throttle` ilə eyni
-- xəbərdarlıq).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_support_chat_throttle_lockout ON support_chat_throttle;
--   DROP FUNCTION IF EXISTS enforce_support_chat_throttle_lockout();
--   DROP TABLE IF EXISTS support_chat_throttle;
-- COMMIT;
-- ===========================================================================
