-- ===========================================================================
-- 099 — ŞİFT-HANDOFF QEYDİ (Faza 5.3) + BREAK-GLASS FÖVQƏLADƏ GİRİŞ (Faza 5.4)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 5.
--
-- ---------------------------------------------------------------------------
-- NİYƏ 089-DA DEYİL, AYRICA
-- ---------------------------------------------------------------------------
-- 089 Faza 5-in YEGANƏ "kiçik" sxem ehtiyacını (bir sütun: `stores.
-- technical_contact_employee_id`) qarşıladı. Bu iki funksiyanın hər ikisi
-- isə DAVRANIŞ SAXLAYAN cədvəl tələb edir və biri (break-glass) sistemin ən
-- həssas yoludur — 089-un "kiçik əlavələr" dəstinə qarışdırılsaydı, geri
-- qaytarma (DOWN) həmin kataloq sütunlarını da götürərdi. Reyestrdə ayrı SHA
-- olması bu sətri müstəqil geri qaytarıla bilən edir.
--
-- ---------------------------------------------------------------------------
-- `shift_handoff_notes` — NİYƏ MÜSTƏQİL CƏDVƏL, `attendance_records` SÜTUNU DEYİL
-- ---------------------------------------------------------------------------
-- Handoff qeydi İŞÇİYƏ deyil, MAĞAZANIN NÖVBƏ SIRASINA aiddir: onu yazan
-- işçi ilə oxuyan işçi FƏRQLİ adamlardır və oxuyanın həmin gün ümumiyyətlə
-- davamiyyət sətri olmaya bilər (növbəti gün səhər açan işçi). Sütun kimi
-- `attendance_records`-a qoyulsaydı, oxuma sorğusu "başqasının davamiyyət
-- sətrini oxu" formasını alardı — RLS və məxfilik baxımından yanlış istiqamət
-- (davamiyyət sətrində gecikmə/rədd səbəbi kimi ŞƏXSİ sahələr var).
--
-- `visible_until` SÜTUNU QƏSDƏN YOXDUR: görünmə pəncərəsi Root parametridir
-- (`SHIFT_HANDOFF_VISIBILITY_HOURS`) və OXUMA anında hesablanır. Sütun kimi
-- yazılsaydı, Root pəncərəni dəyişəndə ARTIQ yazılmış sətirlər köhnə dəyərlə
-- qalardı — `system_limits`-in bütün mənası itərdi.
--
-- TIME-1 TƏTBİQ OLUNUR (`created_at` trigger-i): qeydi İŞÇİ yazır və "mən bu
-- qeydi növbə bitəndə yazmışdım" iddiası mübahisə predmetidir (kassa
-- vəziyyəti barədə qeyd puldan danışır).
--
-- ---------------------------------------------------------------------------
-- `break_glass_trustees` VƏ `break_glass_grants` — NİYƏ İKİ CƏDVƏL
-- ---------------------------------------------------------------------------
-- Biri REYESTRDİR (kim ehtiyat-admin ola bilər — Root ƏVVƏLCƏDƏN təyin edir,
-- böhran anında DEYİL), digəri HADİSƏ jurnalıdır (konkret istifadə). Bir
-- cədvəldə birləşdirilsəydi, "təyinat" ilə "istifadə" eyni sətirdə qarışardı
-- və ən vacib sual — «bu şəxs böhrandan ƏVVƏL təyin edilmişdi, yoxsa böhran
-- anında özünü təyin etdi?» — cavabsız qalardı. Break-glass-ın BÜTÜN
-- təhlükəsizliyi məhz bu ayrımdadır.
--
-- `granted_role` SÜTUNU YOXDUR: verilən səlahiyyət HƏMİŞƏ eynidir (müvəqqəti
-- Root-səviyyəli giriş) və onu dəyişən bir yol açmaq break-glass-ı ixtiyari
-- səlahiyyət artırma alətinə çevirərdi.
--
-- `vendor_synced_at` — spesifikasiyanın "hər istifadə mərkəzi vendor bazasına
-- da yazılsın" tələbinin İZİDİR. NULL = hələ göndərilməyib (offline ola
-- bilər); göndərmə uğursuz olsa da YERLİ sətir QALIR — mərkəzi baza əlçatmaz
-- olduğu üçün fövqəladə girişi bloklamaq, məhz fövqəladə halda sistemi
-- işləməz edərdi.
--
-- ---------------------------------------------------------------------------
-- RLS: hər üçü standart `tenant_isolation`.
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7).
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `shift_handoff_notes` — Faza 5.3
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shift_handoff_notes (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- NO ACTION: mağaza soft-delete edilir; "hansı mağazanın təhvili" sualı
    -- qeyddən uzun yaşayır (`employee_transfer_requests.from_store_id` ilə
    -- eyni əsaslandırma).
    store_id           UUID NOT NULL REFERENCES stores(id) ON DELETE NO ACTION,

    -- NO ACTION: "kim təhvil verdi?" sualı işçinin deaktivasiyasından sonra
    -- da cavablanmalıdır (`announcements.created_by` naxışı).
    author_employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    -- Uzunluq həddi TƏTBİQ QATINDADIR (`SHIFT_HANDOFF_NOTE_MAX_CHARS`, Root
    -- parametri). Burada YALNIZ boş-deyil yoxlanılır: DB tərəfdə sabit tavan
    -- qoyulsaydı, Root həddi böyüdəndə yazı DB xətası ilə düşərdi.
    note               TEXT NOT NULL CHECK (char_length(trim(note)) >= 1),

    -- Növbənin İŞ GÜNÜ — oxuma sorğusu "bu mağazanın son qeydi" deyil,
    -- "görünmə pəncərəsi içindəki son qeyd" axtarır, lakin gündəlik hesabat
    -- üçün tarixə görə süzgəc lazımdır.
    work_date          DATE NOT NULL,

    -- Qeydi növbəti işçi GÖRDÜ və qəbul etdi. NULL = hələ oxunmayıb.
    -- Sətir SİLİNMİR: təhvil-qəbulun kim tərəfindən qəbul edildiyi faktdır.
    acknowledged_by    UUID REFERENCES employees(id) ON DELETE SET NULL,
    acknowledged_at    TIMESTAMPTZ,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status        sync_status NOT NULL DEFAULT 'SYNCED',

    CONSTRAINT chk_handoff_ack
        CHECK ((acknowledged_by IS NULL AND acknowledged_at IS NULL)
            OR (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL))
);

COMMENT ON TABLE shift_handoff_notes IS
    'Faza 5.3 (v2backlog.md): növbəni təhvil verən işçinin növbəti işçiyə '
    'qoyduğu qeyd (açıq tapşırıqlar, kassa vəziyyəti). Görünmə pəncərəsi '
    'SÜTUN DEYİL — Root parametri (SHIFT_HANDOFF_VISIBILITY_HOURS) oxuma '
    'anında tətbiq olunur (migrations/099).';

COMMENT ON COLUMN shift_handoff_notes.acknowledged_by IS
    'Qeydi görüb qəbul edən növbəti işçi. NULL = hələ oxunmayıb. Sətir heç '
    'vaxt silinmir — kimin təhvil aldığı təhvil-qəbulun özü qədər faktdır.';

ALTER TABLE shift_handoff_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON shift_handoff_notes;
CREATE POLICY tenant_isolation ON shift_handoff_notes
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- Oxuma sorğusunun DƏQİQ forması: bir mağazanın, hələ qəbul edilməmiş,
-- ən yeni qeydləri. Qismən indeks — qəbul edilmiş sətirlər (zamanla
-- əksəriyyət) indeksdə yer tutmur.
CREATE INDEX IF NOT EXISTS idx_handoff_unacknowledged
    ON shift_handoff_notes (tenant_id, store_id, created_at DESC)
    WHERE acknowledged_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_handoff_store_date
    ON shift_handoff_notes (tenant_id, store_id, work_date DESC);

DROP TRIGGER IF EXISTS trg_server_created_at_handoff_notes ON shift_handoff_notes;
CREATE TRIGGER trg_server_created_at_handoff_notes
    BEFORE INSERT ON shift_handoff_notes
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

-- ---------------------------------------------------------------------------
-- 2. `break_glass_trustees` — Faza 5.4 REYESTRİ
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS break_glass_trustees (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- CASCADE: işçi tamamilə silinsə (praktikada soft delete) reyestrdə
    -- yetim sətir qalmamalıdır — bu reyestr GƏLƏCƏK səlahiyyət verir, keçmiş
    -- faktı saxlamır (`break_glass_grants` isə saxlayır, ora NO ACTION-dır).
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    -- Kim təyin etdi (yalnız Root). NO ACTION: təyinatın mənbəyi faktdır.
    designated_by  UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,
    designated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Ləğv SİLMƏ ilə DEYİL, bayraqla olur: "bu şəxs nə vaxtsa ehtiyat-admin
    -- idi" sualı auditdə soruşulur (`catalogs.py` soft-delete əsaslandırması).
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    revoked_by     UUID REFERENCES employees(id) ON DELETE SET NULL,
    revoked_at     TIMESTAMPTZ,

    CONSTRAINT chk_trustee_revocation
        CHECK ((is_active AND revoked_at IS NULL)
            OR (NOT is_active AND revoked_at IS NOT NULL))
);

-- BİR işçi BİR dəfə aktiv reyestrdə ola bilər. Qismən unikal indeks: ləğv
-- edilmiş köhnə sətirlər yenidən təyinata mane olmur.
CREATE UNIQUE INDEX IF NOT EXISTS uq_break_glass_trustee_active
    ON break_glass_trustees (tenant_id, employee_id)
    WHERE is_active;

COMMENT ON TABLE break_glass_trustees IS
    'Faza 5.4 (v2backlog.md): Root ƏVVƏLCƏDƏN təyin etdiyi ehtiyat-adminlər '
    'reyestri. Böhran anında bu siyahıya əlavə etmək MÜMKÜN DEYİL (tətbiq '
    'qatı can_manage_break_glass tələb edir, o isə YALNIZ Root-dadır) — '
    'break-glass-ın bütün təhlükəsizliyi «əvvəlcədən təyin» şərtindədir '
    '(migrations/099).';

ALTER TABLE break_glass_trustees ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON break_glass_trustees;
CREATE POLICY tenant_isolation ON break_glass_trustees
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 3. `break_glass_grants` — Faza 5.4 HADİSƏ JURNALI
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS break_glass_grants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- NO ACTION hər üçündə: bu, AUDİT sətridir — iştirakçıların işçi qeydi
    -- silinsə belə "kim istədi, kim təsdiqlədi" cavabsız qalmamalıdır.
    requested_by        UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,
    approved_by         UUID REFERENCES employees(id) ON DELETE NO ACTION,

    reason              TEXT NOT NULL CHECK (char_length(trim(reason)) >= 10),

    status              TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
        CHECK (status IN ('PENDING_APPROVAL', 'ACTIVE', 'EXPIRED',
                          'REJECTED', 'REVOKED')),

    requested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Təsdiq pəncərəsinin sonu (`BREAK_GLASS_APPROVAL_WINDOW_MINUTES`).
    -- Bu, `visible_until`-dən FƏRQLİ olaraq SÜTUNDUR: sorğu verildiyi anda
    -- iştirakçılara SÖYLƏNİLƏN vaxtdır ("30 dəqiqən var"), sonradan Root
    -- həddi dəyişsə də həmin vədin dəyişməsi YANLIŞ olardı.
    approval_expires_at TIMESTAMPTZ NOT NULL,
    approved_at         TIMESTAMPTZ,
    -- Səlahiyyətin bitmə anı — təsdiq anında hesablanır
    -- (`BREAK_GLASS_MAX_DURATION_MINUTES`). Eyni əsaslandırma.
    expires_at          TIMESTAMPTZ,
    revoked_at          TIMESTAMPTZ,
    revoked_by          UUID REFERENCES employees(id) ON DELETE NO ACTION,

    -- Mərkəzi vendor bazasına yazılma izi (bax fayl başlığı).
    vendor_synced_at    TIMESTAMPTZ,

    CONSTRAINT chk_break_glass_approval
        CHECK ((status = 'PENDING_APPROVAL'
                AND approved_by IS NULL AND approved_at IS NULL AND expires_at IS NULL)
            OR (status = 'REJECTED'
                AND approved_by IS NOT NULL AND expires_at IS NULL)
            OR (status IN ('ACTIVE', 'EXPIRED', 'REVOKED')
                AND approved_by IS NOT NULL AND approved_at IS NOT NULL
                AND expires_at IS NOT NULL)),

    -- ÖZÜNÜ-TƏSDİQ DB SƏVİYYƏSİNDƏ QADAĞANDIR. Qayda tətbiq qatında da var
    -- (`BreakGlassUseCase.approve`) — CLAUDE.md §5 «hər qayda İKİ yerdə»
    -- prinsipi: ekranı yan keçən skript də ona tabe olmalıdır.
    CONSTRAINT chk_break_glass_not_self
        CHECK (approved_by IS NULL OR approved_by <> requested_by)
);

COMMENT ON TABLE break_glass_grants IS
    'Faza 5.4 (v2backlog.md): fövqəladə Root-səviyyəli müvəqqəti səlahiyyətin '
    'HƏR istifadəsi. Sətir heç vaxt silinmir və heç vaxt yenidən istifadə '
    'edilmir — bitmiş səlahiyyət üçün YENİ sorğu tələb olunur (migrations/099).';

COMMENT ON COLUMN break_glass_grants.vendor_synced_at IS
    'Mərkəzi vendor bazasına yazılma anı. NULL = hələ göndərilməyib (offline '
    'ola bilər). Göndərmənin uğursuzluğu fövqəladə girişi BLOKLAMIR — məhz '
    'fövqəladə halda mərkəzi bazanın əlçatmazlığı sistemi işləməz edərdi.';

ALTER TABLE break_glass_grants ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON break_glass_grants;
CREATE POLICY tenant_isolation ON break_glass_grants
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- Aktiv səlahiyyətin yoxlanışı hər səlahiyyət sorğusunda baş verə bilər —
-- qismən indeks onu bir sətirlik axtarışa endirir.
CREATE INDEX IF NOT EXISTS idx_break_glass_active
    ON break_glass_grants (tenant_id, requested_by, expires_at DESC)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_break_glass_pending
    ON break_glass_grants (tenant_id, approval_expires_at)
    WHERE status = 'PENDING_APPROVAL';

-- Aylıq tavan sorğusu (`BREAK_GLASS_MAX_GRANTS_PER_MONTH`) tarixə görə sayır.
CREATE INDEX IF NOT EXISTS idx_break_glass_requested_at
    ON break_glass_grants (tenant_id, requested_at DESC);

-- Vendor sinxronizasiyası gözləyən sətirlər (gecəlik iş yenidən cəhd edir).
CREATE INDEX IF NOT EXISTS idx_break_glass_vendor_pending
    ON break_glass_grants (tenant_id, requested_at)
    WHERE vendor_synced_at IS NULL;

DROP TRIGGER IF EXISTS trg_server_created_at_break_glass ON break_glass_grants;
CREATE TRIGGER trg_server_created_at_break_glass
    BEFORE INSERT ON break_glass_grants
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

COMMIT;

-- ===========================================================================
-- QEYD — `enforce_server_created_at()` `requested_at` SÜTUNUNU GÖRMÜR
-- ---------------------------------------------------------------------------
-- Trigger funksiyası (migrations/062) `NEW.created_at`-a yazır. `break_glass_
-- grants`-də sütunun adı `requested_at`-dır və trigger onu TOXUNMUR — sətir
-- `DEFAULT now()` ilə server vaxtı alır. Bu, TIME-1-in «sütun adı INSERT-də
-- açıq çəkiləndə default yan keçilir» xəbərdarlığına DÜŞÜR, ona görə tətbiq
-- qatı (`BreakGlassUseCase`) `requested_at`-ı İNSERT-də HEÇ VAXT açıq
-- yazmır — dəyər həmişə serverdən gəlir. Trigger `created_at` üçün
-- qalır ki, gələcəkdə həmin adlı sütun əlavə olunsa qapı hazır olsun.
-- ===========================================================================

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- DİQQƏT: `break_glass_grants` AUDİT sətirləridir — silinməsi «kim fövqəladə
-- səlahiyyət aldı» sualını əbədi cavabsız qoyur. Yalnız səhv tətbiq edilmiş
-- miqrasiyanı geri almaq üçün.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TABLE IF EXISTS break_glass_grants;
--   DROP TABLE IF EXISTS break_glass_trustees;
--   DROP TABLE IF EXISTS shift_handoff_notes;
-- COMMIT;
-- ===========================================================================
