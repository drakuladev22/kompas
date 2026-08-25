-- ===========================================================================
-- 088 — HR LIFECYCLE v2: MÖVSÜMİ DEAKTİVASİYA, RETENSİYA, KÖÇÜRMƏ, TÖVSİYƏ,
--        PAYLAŞILAN CHECKLIST ŞABLONU (`v2backlog.md` Faza 3.1/3.2/3.3/3.5,
--        Faza 3.4 + 4.1 üçün ORTAQ infrastruktur)
-- ===========================================================================
-- Tarix : 2026-08-24
-- Mənbə : `v2backlog.md` FAZA 1 — komanda rəhbərinin təsdiqlədiyi sxem
--         siyahısı (schema-migration-engineer analizi, 8+1 yeni cədvəl).
--
-- ---------------------------------------------------------------------------
-- NİYƏ BEŞ FUNKSİYA BİR MİQRASİYADA
-- ---------------------------------------------------------------------------
-- Hamısı EYNİ Faza 1 sxem-konsolidasiya tələbindən gəlir (`v2backlog.md`:
-- "Aşağıdakı fazalarda təsvir olunan BÜTÜN yeni cədvəlləri BİR miqrasiya-
-- dəstində yarat") və heç biri digərinin davranışına toxunmur — reyestrdə
-- (migrations/061) bir sətir olması "hansı buraxılışda HR v2 nə gəldi"
-- sualını bir SHA ilə cavablandırır (084-ün EYNİ əsaslandırması).
--
-- ---------------------------------------------------------------------------
-- NİYƏ `checklist_item_templates` AYRI CƏDVƏLDİR, `field_report_checklist_
-- items`-in GENİŞLƏNMƏSİ DEYİL
-- ---------------------------------------------------------------------------
-- Faza 3.4 (Struktur Offboarding Checklist) İŞÇİ-mərkəzlidir. `field_reports`
-- isə MAĞAZA-mərkəzlidir (`store_id NOT NULL` — fiziki audit vizitidir,
-- migrations/037). `store_id`-ni NULL edib offboarding-i ora sığdırmaq
-- mövcud, işlək cədvəlin invariantını ("hər sətir bir mağaza auditidir")
-- pozardı — `v2backlog.md`-nin özü "BƏNZƏR struktur" deyir, "EYNİ cədvəl"
-- demir. Qırmızı xətt ("kəsişmə tapsan, mövcudu genişləndir") bura aid
-- DEYİL, çünki iki domenin kəsişməsi YOXDUR — yalnız SƏTHİ formaları
-- oxşardır.
--
-- Faza 4.1 (Gündəlik Açılış/Bağlanış Checklist) isə HƏQİQƏTƏN `field_
-- reports`-a bağlanacaq (yeni `field_report_types` sətri, bax gələcək
-- miqrasiya) — LAKİN mövcud `field_report_checklist_items` bəndləri
-- ŞABLONDAN YOX, TƏQDİM ANINDA sərbəst mətn kimi alır (`ChecklistItemDraft`,
-- `use_cases/field_reports.py:192`). "Root-idarəli" tələbi BƏNDLƏRİN
-- MƏTNİNƏ aiddir (kassa/təhlükəsizlik/təmizlik kimi SABİT siyahı), təkcə
-- kateqoriyalara yox — mövcud mexanizmdə bunun üçün yer yoxdur.
--
-- Qərar (istifadəçi təsdiqi ilə): PAYLAŞILAN, kiçik bir şablon cədvəli.
-- `owner_type` iki domeni ayırır (`FIELD_REPORT` / `OFFBOARDING`),
-- `owner_key` domeninin daxilində hansı kataloqa aid olduğunu göstərir
-- (uyğun olaraq `field_report_types.code`, ya da sabit `'OFFBOARDING'`
-- sentinel-i). Bir cədvəl "Root checklist mətnini idarə edir" konseptini
-- İKİ yerdə TƏKRARLAMAQDAN qortarır — instansiya sətirləri
-- (`field_report_checklist_items`, `employee_offboarding_checklist_items`)
-- doğurdan da AYRI qalır, çünki onların hər biri öz valideynindən
-- (`field_reports` / `employee_offboarding_checklists`) composite FK
-- daşıyır və bu, iki fərqli domendir.
--
-- FK QOYULA BİLMİR (`owner_key` → `field_report_types.code`): `owner_type =
-- 'OFFBOARDING'` olanda `owner_key` heç bir `field_report_types` sətrinə
-- işarə etmir (sabit sentinel-dir). Şərti FK PostgreSQL-də mövcud deyil —
-- `field_report_categories.route_to_role`-dakı EYNİ əsaslandırma
-- (migrations/037): mövcudluğu tətbiq qatı yoxlayır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `employee_transfer_requests` AYRI CƏDVƏLDİR, `shift_swap_requests`-in
-- GENİŞLƏNMƏSİ DEYİL
-- ---------------------------------------------------------------------------
-- `shift_swap_requests` BİR GÜNLÜK rejim dəyişikliyidir (`target_date`,
-- `requested_mode_id`), Store Manager yalnız TÖVSİYƏ yazır, təsdiq etmir.
-- Faza 3.3 isə `employees.store_id`-nin DAİMİ dəyişikliyidir, HR_Admin
-- TƏSDİQ edir (Store Manager deyil) və effektiv tarixi var. İkisini
-- birləşdirmək iki fərqli biznes qərarını (günlük əməliyyat ↔ struktur
-- dəyişiklik) EYNİ sətirdə qarışdırardı — "günlük rejim" sütunları
-- (`requested_mode_id`) transfer sorğusunda mənasız qalardı və əksinə.
-- Struktur ("mövcud Shift Swap təsdiq-pattern-i ilə") ŞÜURLU şəkildə
-- TƏKRARLANIR (status enum-u, `decided_*` üçlüyü), cədvəl özü YOX.
--
-- ---------------------------------------------------------------------------
-- `employees`-Ə ÜÇ YENİ SÜTUN — NİYƏ CƏDVƏL DEYİL
-- ---------------------------------------------------------------------------
-- Faza 3.1 (mövsümi deaktivasiya) və 3.5 (tövsiyə) TƏK DƏYƏRDİR — işçi
-- yaradılarkən doldurulan sahə, əlaqəli WORKFLOW yoxdur (cron mövcud
-- pattern-lə oxuyur, bonus mövcud `points_ledger`-ə yazır). Yeni cədvəl
-- bir-sütunluq məlumat üçün lazımsız JOIN əlavə edərdi.
--
-- Faza 3.2 (data-saxlama müddəti) ROOT PARAMETRİ-dir (`system_limits`,
-- sxem dəyişikliyi TƏLƏB ETMİR — domen qatının işidir) VƏ retensiya
-- prosesinin İDEMPOTENTLİK markeridir: PII ANONİMLƏŞDİRMƏ İŞÇİ SƏTRİNDƏ
-- baş verir (ad/telefon/s. nullanır), `fines`/`attendance_records`
-- sətirlərinə TOXUNULMUR — FK-lar saxlanılır, aqreqat statistika (say,
-- məbləğ, tarix) qorunur. `audit_logs` İSTİSNADIR (hüquqi tələb ola bilər,
-- v2backlog.md-nin özü qeyd edir) — bu miqrasiya ona TOXUNMUR.
--
-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
-- Dörd yeni cədvəlin HAMISI standart `tenant_isolation` siyasətini alır
-- (037/086 naxışı). Vendor-tərəfi istisna BURADA YOXDUR.
--
-- ---------------------------------------------------------------------------
-- TIME-1
-- ---------------------------------------------------------------------------
-- `employee_transfer_requests.created_at` və `employee_offboarding_
-- checklists.created_at` mövcud `enforce_server_created_at()` funksiyasına
-- (migrations/062) BAĞLANIR — 063/064 EYNİ funksiyanı öz yeni cədvəllərinə
-- necə bağladısa, elə: HR qərarının vaxtı sonrakı mübahisədə (transfer nə
-- vaxt tələb olundu? offboarding nə vaxt başladı?) sübutdur, client saatına
-- etibar edilmir. `checklist_item_templates` VƏ `employee_offboarding_
-- checklist_items`-ə BAĞLANMIR — birincisi Root-authored KATALOQDUR (insan
-- fırıldağı riski yoxdur, `field_report_types` ilə eyni səbəb), ikincisi
-- valideynin sətri ilə EYNİ anda yaranır və valideynin möhürü kifayətdir
-- (`field_report_checklist_items` da BU trigger-i daşımır).
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7) —
-- yalnız YENİ obyektlərdir, mövcud trigger/indeks/constraint YENİDƏN
-- YAZILMIR.
-- ===========================================================================

DO $$
BEGIN
    IF to_regtype('employee_transfer_status') IS NULL THEN
        CREATE TYPE employee_transfer_status AS ENUM ('PENDING_APPROVAL', 'APPROVED', 'REJECTED');
    END IF;
END
$$;

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `employees` — ÜÇ ƏLAVƏ SÜTUN
-- ---------------------------------------------------------------------------
ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS scheduled_deactivation_date DATE,
    ADD COLUMN IF NOT EXISTS data_anonymized_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS referred_by_employee_id UUID REFERENCES employees(id) ON DELETE SET NULL;

COMMENT ON COLUMN employees.scheduled_deactivation_date IS
    'Faza 3.1 (v2backlog.md): mövsümi/müvəqqəti işçi üçün istəyə-bağlı '
    'planlaşdırılmış deaktivasiya tarixi. NULL = müddətsiz. Gecəlik cron '
    '(mövcud `scheduled_job_runs` naxışı) bu tarixi keçmiş AKTİV işçiləri '
    'tapıb deaktiv edir və HR-ə bildiriş göndərir — sxem YALNIZ niyyəti '
    'saxlayır, icra tətbiq qatındadır (migrations/088).';

COMMENT ON COLUMN employees.data_anonymized_at IS
    'Faza 3.2 (v2backlog.md): retensiya müddəti (ROOT PARAMETRİ, '
    '`system_limits`) keçmiş DEAKTİV işçinin PII sahələri (ad, telefon və s.) '
    'anonimləşdirildiyi AN. NULL = hələ anonimləşdirilməyib. Marker BU '
    'sətirdədir, `fines`/`attendance_records`-da DEYİL: FK-lar saxlanılır, '
    'aqreqat statistika (say, məbləğ, tarix) qorunur, YALNIZ şəxsi '
    'identifikasiya itir. `audit_logs` bu prosesdən İSTİSNADIR (hüquqi tələb '
    'ola bilər) — bu sütun ora TOXUNMUR (migrations/088).';

COMMENT ON COLUMN employees.referred_by_employee_id IS
    'Faza 3.5 (v2backlog.md): işçi yaradılarkən "kim tövsiyə etdi" sahəsi. '
    'ON DELETE SET NULL — tövsiyə edən sonradan deaktiv/silinsə (praktikada '
    'soft delete) belə, tövsiyə edilən işçinin sətri YETİM QALMAMALIDIR. '
    'Bonus-xal mövcud `points_ledger`-ə YENİ mənbə kimi yazılır (ROOT '
    'PARAMETRİ məbləğ, `system_limits`) — sxem dəyişikliyi bunun üçün lazım '
    'deyil (migrations/088).';

-- ---------------------------------------------------------------------------
-- 2. `employee_transfer_requests` — Faza 3.3
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee_transfer_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- CASCADE: sorğu işçi haqqındadır, müstəqil mənası yoxdur (`shift_swap_
    -- requests` ilə eyni əsaslandırma).
    employee_id       UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    -- NO ACTION: mağaza soft-delete edilir (`stores.is_active`), keçmiş
    -- transfer sorğusu "haradan hara" sualının cavabını itirməməlidir
    -- (`field_reports.store_id` ilə eyni əsaslandırma).
    from_store_id     UUID NOT NULL REFERENCES stores(id) ON DELETE NO ACTION,
    to_store_id       UUID NOT NULL REFERENCES stores(id) ON DELETE NO ACTION,
    CONSTRAINT chk_transfer_different_store CHECK (from_store_id <> to_store_id),

    -- NULL = təsdiqlə DƏRHAL effektiv. Dolu dəyər = HR planlaşdırılmış
    -- keçid tarixi seçib (məs. ay sonu), amma TƏSDİQ indi verilir.
    effective_date    DATE,

    reason            TEXT NOT NULL CHECK (char_length(trim(reason)) >= 5),
    status            employee_transfer_status NOT NULL DEFAULT 'PENDING_APPROVAL',

    -- NO ACTION: "kim sorğu verdi?" sualı sorğudan uzun yaşayır
    -- (`announcements.created_by` ilə eyni əsaslandırma).
    requested_by      UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    -- `shift_swap_requests`-dən FƏRQLİ: Store Manager tövsiyə yazmır, YALNIZ
    -- HR_Admin qərar verir — ona görə `manager_note`/`manager_id` cütü YOXDUR.
    decided_by        UUID REFERENCES employees(id),
    decision_reason   TEXT,
    decided_at        TIMESTAMPTZ,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status       sync_status NOT NULL DEFAULT 'SYNCED',

    CONSTRAINT chk_transfer_decision
        CHECK ((status = 'PENDING_APPROVAL' AND decided_by IS NULL)
            OR (status <> 'PENDING_APPROVAL' AND decided_by IS NOT NULL))
);

COMMENT ON TABLE employee_transfer_requests IS
    'Faza 3.3 (v2backlog.md): filiallar-arası DAİMİ köçürmə sorğusu — '
    'təsdiqdən sonra `employees.store_id` yenilənir (tətbiq qatı), bu '
    'sətir isə tarixçə olaraq QALIR. `shift_swap_requests` ilə QARIŞDIRILMIR: '
    'o, BİR GÜNLÜK rejim dəyişikliyidir, bu isə struktur dəyişiklikdir '
    '(migrations/088).';

COMMENT ON COLUMN employee_transfer_requests.effective_date IS
    'NULL = təsdiqlə DƏRHAL effektiv olur. Dolu dəyər = HR planlaşdırılmış '
    'keçid tarixini əvvəlcədən qeyd edir, icra isə həmin tarixdə (mövcud '
    'cron-pattern) baş verir.';

ALTER TABLE employee_transfer_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON employee_transfer_requests;
CREATE POLICY tenant_isolation ON employee_transfer_requests
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

CREATE INDEX IF NOT EXISTS idx_transfer_pending
    ON employee_transfer_requests (tenant_id, status)
    WHERE status = 'PENDING_APPROVAL';

DROP TRIGGER IF EXISTS trg_server_created_at_transfer_requests ON employee_transfer_requests;
CREATE TRIGGER trg_server_created_at_transfer_requests
    BEFORE INSERT ON employee_transfer_requests
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

-- ---------------------------------------------------------------------------
-- 3. `checklist_item_templates` — Faza 3.4 + 4.1 ORTAQ (bax fayl başlığı)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS checklist_item_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    owner_type      TEXT NOT NULL CHECK (owner_type IN ('FIELD_REPORT', 'OFFBOARDING')),
    -- FK QOYULA BİLMİR (bax fayl başlığı) — `FIELD_REPORT` üçün `field_report_
    -- types.code`, `OFFBOARDING` üçün sabit `'OFFBOARDING'` sentinel-i.
    owner_key       TEXT NOT NULL CHECK (char_length(trim(owner_key)) >= 2),

    position_no     SMALLINT NOT NULL CHECK (position_no >= 1),
    item_text       TEXT NOT NULL CHECK (char_length(trim(item_text)) >= 3),
    is_blocking     BOOLEAN NOT NULL DEFAULT FALSE,
    photo_required  BOOLEAN NOT NULL DEFAULT FALSE,

    -- Soft delete: köhnəlmiş bənd söndürülür, SİLİNMİR — keçmiş instansiya
    -- sətirləri (`field_report_checklist_items`/`employee_offboarding_
    -- checklist_items`) hansı şablondan doğduğunu göstərə bilməlidir
    -- (`catalogs.py` qaydası).
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at  TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, owner_type, owner_key, position_no)
);

COMMENT ON TABLE checklist_item_templates IS
    'Faza 3.4 + 4.1 ORTAQ (v2backlog.md): Root-un ƏVVƏLCƏDƏN təyin etdiyi '
    'checklist bənd mətnləri. `owner_type`/`owner_key` HANSI domenin '
    'kataloquna aid olduğunu göstərir (`FIELD_REPORT` → `field_report_types.'
    'code`, `OFFBOARDING` → sabit sentinel). İnstansiya sətirləri '
    '(faktiki doldurulan checklist-lər) BURADAN OXUYUR, amma bu cədvələ '
    'FK ilə BAĞLANMIR — instansiya öz valideynindən (report/offboarding) '
    'asılıdır, şablon isə YALNIZ mətnin mənbəyidir (migrations/088).';

COMMENT ON COLUMN checklist_item_templates.owner_key IS
    'FK QOYULA BİLMİR: `owner_type` dəyərinə görə fərqli kataloqa işarə edir '
    '(şərti FK PostgreSQL-də yoxdur) — `field_report_categories.route_to_'
    'role`-dakı EYNİ məhdudiyyət (migrations/037). Mövcudluğu tətbiq qatı '
    'yoxlayır.';

ALTER TABLE checklist_item_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON checklist_item_templates;
CREATE POLICY tenant_isolation ON checklist_item_templates
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP TRIGGER IF EXISTS trg_checklist_item_templates_updated ON checklist_item_templates;
CREATE TRIGGER trg_checklist_item_templates_updated
    BEFORE UPDATE ON checklist_item_templates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 4. `employee_offboarding_checklists` — Faza 3.4
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee_offboarding_checklists (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    -- NO ACTION: offboarding qeydi hüquqi/HR sübutdur (avadanlıq-qaytarma,
    -- son-hesablaşma) və işçi sətri ilə birlikdə sükutla yox olmamalıdır
    -- (`field_reports.reported_by` ilə eyni əsaslandırma). İşçilər
    -- praktikada soft delete edilir, ona görə bu qayda normal axını bloklamır.
    employee_id     UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    status          TEXT NOT NULL DEFAULT 'IN_PROGRESS'
                        CHECK (status IN ('IN_PROGRESS', 'COMPLETED')),

    initiated_by    UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,
    completed_by    UUID REFERENCES employees(id) ON DELETE SET NULL,
    completed_at    TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status     sync_status NOT NULL DEFAULT 'SYNCED',

    UNIQUE (tenant_id, id),

    CONSTRAINT chk_offboarding_completion
        CHECK (status <> 'COMPLETED'
            OR (completed_at IS NOT NULL AND completed_by IS NOT NULL))
);

COMMENT ON TABLE employee_offboarding_checklists IS
    'Faza 3.4 (v2backlog.md): struktur offboarding checklist-i — mövcud '
    '"deaktiv et" əməliyyatına ƏLAVƏ, `field_reports`-un GENİŞLƏNMƏSİ DEYİL '
    '(bax fayl başlığı: o, MAĞAZA-mərkəzlidir, bu İŞÇİ-mərkəzlidir). Bəndlər '
    '`checklist_item_templates`-dən (`owner_type = OFFBOARDING`) köçürülür '
    '(migrations/088).';

-- İKİ ARDICIL offboarding cəhdinin EYNİ ANDA "IN_PROGRESS" olmasının qarşısı
-- — ikinci HR admin eyni işçi üçün TƏKRAR checklist açmasın (qismən indeks,
-- YALNIZ aktiv sətirlər üçün unikal).
CREATE UNIQUE INDEX IF NOT EXISTS uq_offboarding_active_per_employee
    ON employee_offboarding_checklists (tenant_id, employee_id)
    WHERE status = 'IN_PROGRESS';

ALTER TABLE employee_offboarding_checklists ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON employee_offboarding_checklists;
CREATE POLICY tenant_isolation ON employee_offboarding_checklists
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP TRIGGER IF EXISTS trg_offboarding_checklists_updated ON employee_offboarding_checklists;
CREATE TRIGGER trg_offboarding_checklists_updated
    BEFORE UPDATE ON employee_offboarding_checklists
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_server_created_at_offboarding ON employee_offboarding_checklists;
CREATE TRIGGER trg_server_created_at_offboarding
    BEFORE INSERT ON employee_offboarding_checklists
    FOR EACH ROW EXECUTE FUNCTION enforce_server_created_at();

-- ---------------------------------------------------------------------------
-- 5. `employee_offboarding_checklist_items` — Faza 3.4
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee_offboarding_checklist_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    checklist_id    UUID NOT NULL,

    position_no     SMALLINT NOT NULL CHECK (position_no >= 1),
    category        TEXT NOT NULL CHECK (category IN ('EQUIPMENT', 'SETTLEMENT', 'EXIT_INTERVIEW')),
    item_text       TEXT NOT NULL CHECK (char_length(trim(item_text)) >= 3),

    -- ÜÇ VƏZİYYƏT: TRUE = tamamlandı, FALSE = tamamlanmadı, NULL = hələ
    -- yoxlanılmadı (`field_report_checklist_items.passed` ilə EYNİ naxış).
    passed          BOOLEAN,
    notes           TEXT,

    is_blocking     BOOLEAN NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (checklist_id, position_no),

    -- BİRLƏŞMİŞ FK (`field_report_checklist_items` ilə EYNİ naxış,
    -- migrations/037): bəndin `tenant_id`-si valideynin `employee_
    -- offboarding_checklists.tenant_id`-si ilə EYNİ olmalıdır.
    FOREIGN KEY (tenant_id, checklist_id)
        REFERENCES employee_offboarding_checklists (tenant_id, id) ON DELETE CASCADE
);

COMMENT ON TABLE employee_offboarding_checklist_items IS
    'Faza 3.4 (v2backlog.md): offboarding checklist bəndinin İNSTANSİYASI — '
    'mətn `checklist_item_templates`-dən köçürülür (yaradılış anında), '
    'sonrakı redaktə şablonu GERİYƏ TƏSİR ETMİR (`field_report_checklist_'
    'items` ilə eyni prinsip: keçmiş sətir "o an nə yazılmışdı"-nın '
    'sübutudur) (migrations/088).';

ALTER TABLE employee_offboarding_checklist_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON employee_offboarding_checklist_items;
CREATE POLICY tenant_isolation ON employee_offboarding_checklist_items
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP TRIGGER IF EXISTS trg_offboarding_items_updated ON employee_offboarding_checklist_items;
CREATE TRIGGER trg_offboarding_items_updated
    BEFORE UPDATE ON employee_offboarding_checklist_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- SIRA VACİBDİR: uşaq cədvəllər valideyndən ƏVVƏL silinməlidir (FK).
-- `employees`-in üç sütunu SİLİNSƏ mövcud sətirlərdəki dəyər İTİR (referral/
-- planlaşdırılmış deaktivasiya tarixi bərpa oluna bilməz) — YALNIZ miqrasiya
-- SƏHVƏN tətbiq olunub və HEÇ bir sətir doldurulmayıbsa işlədin.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_offboarding_items_updated ON employee_offboarding_checklist_items;
--   DROP TABLE IF EXISTS employee_offboarding_checklist_items;
--
--   DROP TRIGGER IF EXISTS trg_server_created_at_offboarding ON employee_offboarding_checklists;
--   DROP TRIGGER IF EXISTS trg_offboarding_checklists_updated ON employee_offboarding_checklists;
--   DROP INDEX IF EXISTS uq_offboarding_active_per_employee;
--   DROP TABLE IF EXISTS employee_offboarding_checklists;
--
--   DROP TRIGGER IF EXISTS trg_checklist_item_templates_updated ON checklist_item_templates;
--   DROP TABLE IF EXISTS checklist_item_templates;
--
--   DROP TRIGGER IF EXISTS trg_server_created_at_transfer_requests ON employee_transfer_requests;
--   DROP INDEX IF EXISTS idx_transfer_pending;
--   DROP TABLE IF EXISTS employee_transfer_requests;
--
--   ALTER TABLE employees
--     DROP COLUMN IF EXISTS scheduled_deactivation_date,
--     DROP COLUMN IF EXISTS data_anonymized_at,
--     DROP COLUMN IF EXISTS referred_by_employee_id;
-- COMMIT;
--
-- DROP TYPE IF EXISTS employee_transfer_status;   -- yalnız cədvəl artıq YOXDURSA
-- ===========================================================================
