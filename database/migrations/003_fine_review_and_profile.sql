-- ===========================================================================
-- MIGRATION 003 — AYLIQ CƏRİMƏ İCMALI + İŞÇİ DETAL PANELİ
-- ===========================================================================
-- Tarix : 2026-08-09
-- İki qərar dəyişikliyi:
--   (A) Cərimə yaradıldığı an İŞÇİYƏ GÖRÜNMÜR. `PENDING_REVIEW` → icmal →
--       tək "Bütün Filiallara Göndər" düyməsi → `PUBLISHED`.
--   (B) Universal "İşçi Detal Paneli" üçün `date_of_birth` + icazə
--       qaydasının dəqiqləşdirilməsi.
--
-- İdempotentdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- ƏN VACİB HİSSƏ: 72 SAAT ARTIQ `created_at`-DAN HESABLANMIR
-- ---------------------------------------------------------------------------
-- Cərimə həftələrlə `PENDING_REVIEW`-də qala bilər. Sayğac yaradılışdan
-- başlasaydı, işçi cəriməni GÖRMƏMİŞ onun etiraz hüququ bitmiş olardı.
-- Ona görə `appeal_window_closes_at` artıq NULLABLE-dır və YALNIZ publish
-- anında `published_at + FINE_APPEAL_WINDOW_HOURS` kimi doldurulur.
--
-- `NOT NULL`-un götürülməsi qorunmanı ZƏİFLƏTMİR: `chk_fine_published`
-- məhdudiyyəti PUBLISHED sətrin HƏM `published_at`, HƏM
-- `appeal_window_closes_at` sahəsinin dolu olmasını tələb edir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. fine_status enum-unun yenidən qurulması
-- ---------------------------------------------------------------------------
-- `ACTIVE` çıxarılır, çünki yeni modeldə onun mənası `PUBLISHED` ilə
-- ÜST-ÜSTƏ DÜŞÜR. İki sinonim status saxlamaq sorğularda "hansını
-- yoxlamalıyam?" sualı yaradar və gec-tez biri unudulardı.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
         WHERE t.typname = 'fine_status' AND e.enumlabel = 'PENDING_REVIEW'
    ) THEN
        CREATE TYPE fine_status_new AS ENUM
            ('PENDING_REVIEW', 'PUBLISHED', 'REVERSED', 'REDUCED');

        -- Sütunun tipindən asılı olan HƏR ŞEY əvvəlcə götürülməlidir:
        -- view, `status` sabitini saxlayan partial indeks və CHECK.
        -- Əks halda PostgreSQL "operator does not exist:
        -- fine_status_new = fine_status" ilə imtina edir.
        DROP VIEW IF EXISTS v_exportable_fines;
        DROP INDEX IF EXISTS idx_fines_export_ready;
        ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_reversal;

        ALTER TABLE fines ALTER COLUMN status DROP DEFAULT;
        ALTER TABLE fines
            ALTER COLUMN status TYPE fine_status_new
            USING (CASE status::TEXT
                       WHEN 'ACTIVE' THEN 'PUBLISHED'
                       ELSE status::TEXT
                   END)::fine_status_new;

        DROP TYPE fine_status;
        ALTER TYPE fine_status_new RENAME TO fine_status;

        -- YENİ DEFOLT: cərimə artıq görünən vəziyyətdə doğulmur.
        ALTER TABLE fines ALTER COLUMN status SET DEFAULT 'PENDING_REVIEW';
        RAISE NOTICE 'fine_status yenidən quruldu; ACTIVE → PUBLISHED';
    END IF;
END
$$;

-- Götürülmüş məhdudiyyət bərpa olunur (indeks `published_at` sütunundan
-- asılıdır, ona görə aşağıda — sütun əlavə edildikdən sonra).
ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_reversal;
ALTER TABLE fines ADD CONSTRAINT chk_fine_reversal
    CHECK (status <> 'REVERSED' OR (reversed_by IS NOT NULL AND reversal_reason IS NOT NULL));

-- ---------------------------------------------------------------------------
-- 2. fines — icmal/nəşr sahələri
-- ---------------------------------------------------------------------------
ALTER TABLE fines
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES employees(id),
    ADD COLUMN IF NOT EXISTS review_decision_reason TEXT,
    ADD COLUMN IF NOT EXISTS review_batch_id UUID;

ALTER TABLE fines ALTER COLUMN appeal_window_closes_at DROP NOT NULL;

-- Köçürülən sətirlər (köhnə `ACTIVE`) artıq işçiyə görünürdü — onlar üçün
-- nəşr anı yaradılış anıdır, əks halda etiraz pəncərəsi "hesablanmamış"
-- görünərdi.
UPDATE fines
   SET published_at = COALESCE(published_at, created_at)
 WHERE status IN ('PUBLISHED', 'REVERSED', 'REDUCED')
   AND published_at IS NULL;

COMMENT ON COLUMN fines.published_at IS
    '"[Bütün Filiallara Göndər]" basıldığı an. 72-saatlıq etiraz pəncərəsi '
    'BUNDAN hesablanır, `created_at`-dan DEYİL — əks halda işçi cəriməni '
    'görmədən etiraz hüququnu itirə bilərdi.';

ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_published;
ALTER TABLE fines ADD CONSTRAINT chk_fine_published
    CHECK (status = 'PENDING_REVIEW'
        OR (published_at IS NOT NULL AND appeal_window_closes_at IS NOT NULL));

-- İcmal ekranının əsas sorğusu: "bu ayın nəşr gözləyən cərimələri".
CREATE INDEX IF NOT EXISTS idx_fines_pending_review
    ON fines (tenant_id, fine_date) WHERE status = 'PENDING_REVIEW';

-- Export indeksi yeni status və yeni vaxt sütunu ilə bərpa olunur.
CREATE INDEX IF NOT EXISTS idx_fines_export_ready
    ON fines (tenant_id, published_at)
    WHERE status IN ('PUBLISHED', 'REDUCED') AND exported_period IS NULL;

-- ---------------------------------------------------------------------------
-- 2b. LOCK MEXANİZMİ — ÜÇ ŞƏRT (bölmə 6, genişləndirilib)
-- ---------------------------------------------------------------------------
--   (a) status PUBLISHED olmalıdır — `PENDING_REVIEW` HEÇ VAXT export-a
--       düşmür: işçi onu nə görüb, nə də etiraz hüququ alıb;
--   (b) `published_at + FINE_APPEAL_WINDOW_HOURS` keçmiş olmalıdır
--       (`created_at`-dan DEYİL);
--   (c) artıq export olunmamış olmalıdır.
--
-- `REVERSED`/`REDUCED` sətirlər (a) şərtinə görə onsuz da kənarda qalır.
--
-- Pəncərə saatı `system_limits`-dən oxunur: Root onu 24–336 arasında
-- dəyişə bilər və view sabit 72 ilə işləsəydi, dəyişiklik səssizcə
-- nəzərə alınmazdı.
CREATE OR REPLACE VIEW v_exportable_fines AS
SELECT f.*
FROM fines f
-- `REDUCED` DAXİLDİR: qismən qəbul olunmuş etirazdan sonra işçi
-- azaldılmış məbləği yenə ödəyir (bax `Fine.is_exportable`).
WHERE f.status IN ('PUBLISHED', 'REDUCED')
  AND f.published_at IS NOT NULL
  AND f.published_at + make_interval(hours => (
          SELECT COALESCE(MAX(sl.limit_value::INTEGER), 72)
            FROM system_limits sl
           WHERE sl.tenant_id = f.tenant_id
             AND sl.limit_key = 'FINE_APPEAL_WINDOW_HOURS'
      )) <= now()
  AND f.exported_period IS NULL;

COMMENT ON VIEW v_exportable_fines IS
    'Premiya&Cərimə export-una (FAYL 2) düşə bilən cərimələr. Ayın 1-də '
    'nəşr olunan cərimə həmin ayın export-una DÜŞMÜR (72 saat keçməyib) — '
    'bu, gözlənilən davranışdır, xəta deyil.';

-- ---------------------------------------------------------------------------
-- 3. monthly_fine_review_batches — push əməliyyatının auditi
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monthly_fine_review_batches (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    reviewed_by            UUID NOT NULL REFERENCES employees(id),
    review_month           TEXT NOT NULL,      -- 'YYYY-MM'
    pushed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_kept_count       INTEGER NOT NULL DEFAULT 0 CHECK (total_kept_count >= 0),
    total_reversed_count   INTEGER NOT NULL DEFAULT 0 CHECK (total_reversed_count >= 0),
    CONSTRAINT chk_batch_month CHECK (review_month ~ '^\d{4}-(0[1-9]|1[0-2])$')
);

CREATE INDEX IF NOT EXISTS idx_review_batches_tenant
    ON monthly_fine_review_batches (tenant_id, review_month DESC);

COMMENT ON TABLE monthly_fine_review_batches IS
    'Kütləvi nəşrin audit izi: kim, nə vaxt, neçə cərimə göndərdi. '
    'Kütləvi "geri al" YOXDUR — ləğv fərdi-fərdi `REVERSED` ilə aparılır.';

-- ---------------------------------------------------------------------------
-- 4. YENİ HARDLOCK MEXANİZMİ: `excludes_camera_role`
-- ---------------------------------------------------------------------------
-- Mövcud `is_anti_fraud` YALNIZ Mağaza_Meneceri və Satıcını bloklayır;
-- `is_camera_only` isə flag-i kamera roluna MƏHDUDLAŞDIRIR. Bizə lazım olan
-- üçüncü haldır: "anti-fraud + kamera roluna DA verilməz".
--
-- Niyə vacibdir: `can_publish_fines` cəriməni TƏSDİQ edir, `can_issue_fines`
-- isə onu YARADIR. Hər ikisi eyni şəxsdə olsa, dual-control fəlsəfəsi
-- mənasını itirər. "Defolt verilmir" kifayət deyildi — fərdi override ilə
-- səhvən verilə bilərdi.
ALTER TABLE permission_flags
    ADD COLUMN IF NOT EXISTS excludes_camera_role BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN permission_flags.excludes_camera_role IS
    '`is_camera_only`-nin ƏKSİ: flag kamera-tipli rollara HEÇ VAXT verilmir. '
    'Yalnız `is_anti_fraud` ilə birlikdə mənalıdır.';

CREATE OR REPLACE FUNCTION enforce_anti_fraud_segregation() RETURNS TRIGGER AS $$
DECLARE
    v_is_anti_fraud  BOOLEAN;
    v_is_camera_only BOOLEAN;
    v_excl_camera    BOOLEAN;
    v_position_code  TEXT;
    v_is_camera_type BOOLEAN;
BEGIN
    SELECT is_anti_fraud, is_camera_only, excludes_camera_role
      INTO v_is_anti_fraud, v_is_camera_only, v_excl_camera
      FROM permission_flags WHERE code = NEW.flag_code;

    IF NOT COALESCE(v_is_anti_fraud, FALSE) THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'position_permissions' THEN
        IF NOT NEW.granted THEN
            RETURN NEW;
        END IF;
        SELECT code, is_camera_type INTO v_position_code, v_is_camera_type
        FROM positions WHERE id = NEW.position_id;
    ELSE  -- user_permission_overrides
        IF NEW.effect <> 'GRANT' THEN
            RETURN NEW;
        END IF;
        SELECT p.code, p.is_camera_type INTO v_position_code, v_is_camera_type
        FROM employees e JOIN positions p ON p.id = e.position_id
        WHERE e.id = NEW.user_id;
    END IF;

    IF v_position_code IN ('MAGAZA_MENECERI', 'SATICI') THEN
        RAISE EXCEPTION
            'ANTI-FRAUD POZUNTUSU: "%" flag-i "%" rolundakı istifadəçiyə verilə bilməz '
            '(bölmə 3, vəzifə ayrılığı hardlock-u)', NEW.flag_code, v_position_code;
    END IF;

    IF COALESCE(v_excl_camera, FALSE)
       AND (v_position_code = 'KAMERA_NEZARETCISI' OR COALESCE(v_is_camera_type, FALSE)) THEN
        RAISE EXCEPTION
            'VƏZİFƏ AYRILIĞI POZUNTUSU: "%" flag-i kamera-tipli rola verilə bilməz — '
            'cərimə YARADAN ilə cərimə TƏSDİQ EDƏN eyni şəxs ola bilməz (bölmə 3)',
            NEW.flag_code;
    END IF;

    IF COALESCE(v_is_camera_only, FALSE) AND NOT COALESCE(v_is_camera_type, FALSE) THEN
        RAISE EXCEPTION
            'KAMERA-XÜSUSİ FLAG POZUNTUSU: "%" flag-i yalnız kamera-tipli rollara '
            'verilə bilər, "%" isə kamera-tipli deyil (bölmə 3)',
            NEW.flag_code, v_position_code;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- 5. can_publish_fines
-- ---------------------------------------------------------------------------
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only, excludes_camera_role)
VALUES
    ('can_publish_fines', 'KAMERA_CERIME', 'Cərimələri filiallara göndər',
     'Aylıq Cərimə İcmalından təsdiqlənmiş cərimələri işçilərə açır',
     0, TRUE, FALSE, TRUE)
ON CONFLICT (code) DO UPDATE
   SET is_anti_fraud = TRUE, excludes_camera_role = TRUE;

INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_publish_fines', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. employees.date_of_birth (İşçi Detal Paneli)
-- ---------------------------------------------------------------------------
ALTER TABLE employees ADD COLUMN IF NOT EXISTS date_of_birth DATE;

COMMENT ON COLUMN employees.date_of_birth IS
    'HƏSSAS SAHƏ: yalnız `can_view_employee_reports` sahibi (öz profilindən '
    'başqa) görə bilər. Yoxlama TƏKCƏ UI-da deyil, sorğu qatında da '
    'aparılmalıdır — `EmployeeProfileAccessUseCase`.';

-- `can_view_employee_reports` defolt sahibləri (dəqiqləşdirmə).
-- Mağaza_Meneceri artıq sahibdir; onun ƏHATƏ DAİRƏSİ (yalnız öz mağazası)
-- tətbiq qatında tətbiq olunur — DB flag-i "sahibdir/deyil" ikili
-- məlumatından başqa scope saxlamır.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_view_employee_reports', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN', 'MAGAZA_MENECERI')
ON CONFLICT DO NOTHING;

-- Kamera_Nəzarətçisi və Satıcı DEFOLT SAHİB DEYİL: səhvən verilmişsə geri alınır.
DELETE FROM position_permissions pp
 USING positions p
 WHERE pp.position_id = p.id
   AND pp.flag_code = 'can_view_employee_reports'
   AND p.code IN ('KAMERA_NEZARETCISI', 'SATICI');

-- ---------------------------------------------------------------------------
-- 7. RLS + GRANT (yeni cədvəl)
-- ---------------------------------------------------------------------------
ALTER TABLE monthly_fine_review_batches ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON monthly_fine_review_batches;
CREATE POLICY tenant_isolation ON monthly_fine_review_batches
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kompasos_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON monthly_fine_review_batches '
                'TO kompasos_app';
    END IF;
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN — sənədləşdirilir, icra edilmir
-- ===========================================================================
-- DİQQƏT: `PENDING_REVIEW` sətirlərinin `ACTIVE`-ə çevrilməsi onları
-- DƏRHAL bütün işçilərə göstərər — yəni geri qaytarma nəşr qərarını
-- avtomatik "hamısını göndər"ə çevirir. Bu, qəsdən avtomatlaşdırılmır.
--
-- BEGIN;
--   DROP TABLE IF EXISTS monthly_fine_review_batches;
--   ALTER TABLE employees DROP COLUMN IF EXISTS date_of_birth;
--   DELETE FROM position_permissions WHERE flag_code = 'can_publish_fines';
--   DELETE FROM permission_flags WHERE code = 'can_publish_fines';
--   ALTER TABLE permission_flags DROP COLUMN IF EXISTS excludes_camera_role;
--   ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_published;
--   ALTER TABLE fines
--       DROP COLUMN IF EXISTS published_at,
--       DROP COLUMN IF EXISTS reviewed_by,
--       DROP COLUMN IF EXISTS review_decision_reason,
--       DROP COLUMN IF EXISTS review_batch_id;
--   -- fine_status geri qaytarılması ƏL İLƏ nəzərdən keçirilməlidir (yuxarı).
-- COMMIT;
