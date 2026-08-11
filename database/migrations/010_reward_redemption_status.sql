-- ===========================================================================
-- MIGRATION 010 — MÜKAFAT MÜBADİLƏSİNƏ STATUS VƏ QƏRAR SAHƏLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : `reward_redemptions` yalnız `approved_by` / `approved_at` sütunları
--         ilə qurulmuşdu. Bu, YALNIZ təsdiqi modelləşdirir — "rədd edildi" ilə
--         "hələ baxılmayıb" halları AYIRD EDİLƏ BİLMİRDİ (hər ikisində
--         `approved_at IS NULL`). Nəticədə işçi öz sorğusunun taleyini görə
--         bilmirdi və rədd səbəbi heç yerdə saxlanmırdı.
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `status` SÜTUNU, NİYƏ `rejected_at` DEYİL
-- ---------------------------------------------------------------------------
-- İkinci bir tarix sütunu (`rejected_at`) əlavə etmək eyni problemi böyüdərdi:
-- `approved_at` və `rejected_at` hər ikisi dolu olduqda vəziyyət qeyri-müəyyən
-- qalardı və hansının "doğru" olduğunu sorğu yazan hər kəs özü qərara
-- almalı olardı. Tək `status` sütunu bunu struktur olaraq mümkünsüz edir.
--
-- ---------------------------------------------------------------------------
-- `FULFILLED` NİYƏ AYRICA STATUSDUR
-- ---------------------------------------------------------------------------
-- Təsdiq ≠ təhvil. Mükafat təsdiqləndikdən sonra fiziki olaraq işçiyə
-- verilməlidir; bu iki an arasında günlər ola bilər. Ayrı status olmasaydı,
-- "təsdiqlədim, amma hələ vermədim" halı heç yerdə görünməzdi və işçi
-- mükafatını gözləyərkən sistemdə "tamamlanmış" kimi qalardı.
--
-- ---------------------------------------------------------------------------
-- MÖVCUD SƏTİRLƏR NECƏ KÖÇÜRÜLÜR
-- ---------------------------------------------------------------------------
-- `approved_at IS NOT NULL` → `APPROVED`, əks halda `REQUESTED`. `REJECTED`
-- sətri yaradıla BİLMƏZ, çünki köhnə sxemdə rədd heç vaxt yazılmayıb —
-- olmayan məlumatı təxmin etmək əvəzinə boş buraxılır.
-- ===========================================================================

BEGIN;

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
-- (Bu miqrasiyada sətir UNUDULMUŞDU — CI-da 010 məhz buna görə çökürdü.)
SET search_path TO kompasos, public;


-- ---------------------------------------------------------------------------
-- 1. Enum
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'redemption_status') THEN
        CREATE TYPE redemption_status AS ENUM (
            'REQUESTED', 'APPROVED', 'REJECTED', 'FULFILLED'
        );
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Sütunlar
-- ---------------------------------------------------------------------------
ALTER TABLE reward_redemptions
    ADD COLUMN IF NOT EXISTS status         redemption_status NOT NULL DEFAULT 'REQUESTED',
    ADD COLUMN IF NOT EXISTS decision_note  TEXT,
    ADD COLUMN IF NOT EXISTS fulfilled_at   TIMESTAMPTZ,
    -- Mükafatın MÜBADİLƏ ANINDAKI adı: kataloq sonradan dəyişsə də, işçidən
    -- nə üçün xal tutulduğu sənəddə OLDUĞU KİMİ qalmalıdır.
    ADD COLUMN IF NOT EXISTS reward_name_snapshot TEXT;

-- ---------------------------------------------------------------------------
-- 3. Mövcud sətirlərin köçürülməsi
-- ---------------------------------------------------------------------------
UPDATE reward_redemptions
   SET status = 'APPROVED'
 WHERE approved_at IS NOT NULL
   AND status = 'REQUESTED';

UPDATE reward_redemptions r
   SET reward_name_snapshot = w.name_az
  FROM rewards w
 WHERE w.id = r.reward_id
   AND r.reward_name_snapshot IS NULL;

-- ---------------------------------------------------------------------------
-- 4. Uyğunluq məhdudiyyətləri
-- ---------------------------------------------------------------------------
-- Rədd səbəbsiz ola bilməz — işçi niyə rədd edildiyini bilməlidir
-- (tapşırıq rəddindəki `chk_task_reject` ilə eyni prinsip).
ALTER TABLE reward_redemptions
    DROP CONSTRAINT IF EXISTS chk_redemption_reject;
ALTER TABLE reward_redemptions
    ADD CONSTRAINT chk_redemption_reject
        CHECK (status <> 'REJECTED' OR char_length(trim(coalesce(decision_note, ''))) >= 10);

-- Təsdiqlənməmiş mübadilə təhvil verilə bilməz.
ALTER TABLE reward_redemptions
    DROP CONSTRAINT IF EXISTS chk_redemption_fulfilled;
ALTER TABLE reward_redemptions
    ADD CONSTRAINT chk_redemption_fulfilled
        CHECK (status <> 'FULFILLED' OR fulfilled_at IS NOT NULL);

-- ---------------------------------------------------------------------------
-- 5. İndeks — təsdiq gözləyən sorğular inbox-u
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_redemptions_pending
    ON reward_redemptions (tenant_id, created_at DESC)
    WHERE status = 'REQUESTED';

-- Bloklanmış ("held") xalların hesablanması üçün: işçi üzrə aktiv sorğular.
CREATE INDEX IF NOT EXISTS idx_redemptions_holding
    ON reward_redemptions (employee_id)
    WHERE status IN ('REQUESTED', 'APPROVED', 'FULFILLED');

COMMENT ON COLUMN reward_redemptions.status IS
    'Mübadilənin vəziyyəti (bölmə 6). REQUESTED/APPROVED/FULFILLED xalları '
    'BLOKLAYIR — işçi eyni xalı iki mükafata xərcləyə bilməz. REJECTED xalı '
    'geri açır.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — avtomatik geri qaytarma YOXDUR)
-- ===========================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS idx_redemptions_holding;
-- DROP INDEX IF EXISTS idx_redemptions_pending;
-- ALTER TABLE reward_redemptions DROP CONSTRAINT IF EXISTS chk_redemption_fulfilled;
-- ALTER TABLE reward_redemptions DROP CONSTRAINT IF EXISTS chk_redemption_reject;
-- ALTER TABLE reward_redemptions
--     DROP COLUMN IF EXISTS reward_name_snapshot,
--     DROP COLUMN IF EXISTS fulfilled_at,
--     DROP COLUMN IF EXISTS decision_note,
--     DROP COLUMN IF EXISTS status;
-- DROP TYPE IF EXISTS redemption_status;
-- COMMIT;
