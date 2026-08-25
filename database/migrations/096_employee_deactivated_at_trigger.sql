-- ===========================================================================
-- 096 — `employees.deactivated_at` SERVER-TƏRƏFİ MÖHÜRLƏNMƏSİ (TIME-1)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Səbəb : `v2backlog.md` Faza 3.1/3.2 oxucularını yazarkən (`user_management.
--         py:325-340`) tapıldı — `employees.deactivated_at` sütunu (bazis
--         sxemdə mövcuddur) HEÇ BİR YERDƏ yazılmır. Yoxladım:
--         `PostgresEmployeeRepository.save()`-in `UPDATE` siyahısında YOXDUR,
--         `insert()`-də də YOXDUR, `Employee` domen entity-sinin özündə BELƏ
--         `deactivated_at` sahəsi YOXDUR (yalnız `is_active` var).
--
--         Nəticə: Faza 3.2-nin `list_pending_anonymization(deactivated_
--         before=...)` oxucusu DÜZGÜN yazılsa BELƏ, filtri `employees.
--         deactivated_at < deactivated_before`-dur — sütun ƏBƏDİ NULL
--         qalarsa nəticə ƏBƏDİ BOŞ qalır. Komanda rəhbərinin "ölü yol"
--         xəbərdarlığı BU SƏBƏBDƏN BİR PİLLƏ DƏRİNDİR: təkcə oxucu YOX,
--         onun oxuduğu SÜTUN da heç vaxt dolmur.
--
-- ---------------------------------------------------------------------------
-- NİYƏ TƏTBİQ QATINDA YOX, DB TRIGGER-İNDƏ (TIME-1)
-- ---------------------------------------------------------------------------
-- `deactivated_at` retensiya/anonimləşdirmə QƏRARININ vaxt lövbəridir —
-- CLAUDE.md §5 TIME-1: "created_at/published_at kimi hüquqi əhəmiyyətli
-- vaxt möhürləri client-dən qəbul edilmir". Əgər tətbiq qatı `now()`-u
-- Python tərəfdə hesablayıb `save()`-ə ötürsəydi, iki yol (`deactivate_
-- employee` insan-başlanğıclı, `deactivate_scheduled_employees` cron-
-- başlanğıclı) EYNİ məntiqi TƏKRARLAMALI olardı və biri unudulsaydı
-- (`fines.published_at`-ın bir vaxtlar yaşadığı EYNİ qüsur sinfi) retensiya
-- hesablaması sükutla YANLIŞ olardı. Trigger TƏK yerdə, `is_active`
-- keçidinin ÖZÜNDƏN asılı işləyir — hər iki çağırış yolu AVTOMATİK əhatə
-- olunur, `PostgresEmployeeRepository.save()`-in `UPDATE` siyahısına
-- `deactivated_at`-ı ƏLAVƏ ETMƏYƏ EHTİYAC YOXDUR (aşağı bax).
--
-- ---------------------------------------------------------------------------
-- NİYƏ İKİ İSTİQAMƏTLİ (RESET DƏ VAR)
-- ---------------------------------------------------------------------------
-- `Employee.activate()` (HR-4, "qayıdan işçinin simmetriyası") deaktiv
-- işçini YENİDƏN aktivləşdirir. `deactivated_at` SIFIRLANMASA, sonrakı
-- deaktivasiyada (`is_active` YENİDƏN `FALSE` olanda) köhnə tarix QALARDI
-- və retensiya müddəti YANLIŞ ("köhnə deaktivasiyadan") hesablanardı.
-- Trigger `TRUE → FALSE` keçidində möhürləyir, `FALSE → TRUE`-da NULL-a
-- qaytarır — `Employee.activate()`-in domen səviyyəli simmetriyasının DB
-- güzgüsü.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `PostgresEmployeeRepository.save()`-Ə TOXUNMAQ LAZIM DEYİL
-- ---------------------------------------------------------------------------
-- `BEFORE UPDATE` trigger-i `NEW`/`OLD` sətirlərini SET siyahısından ASILI
-- OLMADAN görür (Postgres UPDATE semantikası: göstərilməyən sütunlar əvvəlki
-- dəyərini SAXLAYIR, trigger isə YENƏ DƏ hər iki tərəfi müqayisə edə bilir).
-- `save()`-in mövcud `SET is_active = %s` sətri KİFAYƏT edir — trigger
-- `OLD.is_active`/`NEW.is_active` fərqini avtomatik tutur.
--
-- ---------------------------------------------------------------------------
-- RLS/SXEM DƏYİŞİKLİYİ YOXDUR — sütun ARTIQ MÖVCUDDUR (bazis sxem), yalnız
-- YENİ trigger əlavə olunur. `schema.sql` YENİLƏNMİR: bu, MÖVCUD sxemdə
-- artıq tərif edilmiş bir sütunun DAVRANIŞINI YENİ təyin edir, "qayda
-- qatlanmır" (CLAUDE.md §7) prinsipinə görə YENİ trigger schema.sql-ə
-- KÖÇÜRÜLMƏLİDİR — sxemdə HƏLƏ bu trigger YOXDUR (heç vaxt olmayıb), ona
-- görə bu, "mövcud qaydanın YENİDƏN yazılması" DEYİL, TAMAM YENİ obyektdir
-- (test_schema_migration_parity.py-in `MISSING_FROM_SCHEMA` bölməsinə
-- əlavə lazımdır — `qa`-ya ötürüləcək).
--
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

CREATE OR REPLACE FUNCTION enforce_server_employee_deactivated_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT NEW.is_active AND OLD.is_active THEN
        NEW.deactivated_at := now();
    ELSIF NEW.is_active AND NOT OLD.is_active THEN
        NEW.deactivated_at := NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_server_employee_deactivated_at() IS
    'TIME-1: `employees.deactivated_at`-ı `is_active` keçidinə görə SERVER '
    'vaxtı ilə möhürləyir/sıfırlayır (migrations/096). Retensiya/anonim-'
    'ləşdirmə hesablamasının (v2backlog.md Faza 3.2) lövbəridir — client '
    'dəyəri qəbul edilmir.';

DROP TRIGGER IF EXISTS trg_server_employee_deactivated_at ON employees;
CREATE TRIGGER trg_server_employee_deactivated_at
    BEFORE UPDATE ON employees
    FOR EACH ROW
    WHEN (NEW.is_active IS DISTINCT FROM OLD.is_active)
    EXECUTE FUNCTION enforce_server_employee_deactivated_at();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Trigger silinsə `deactivated_at` YENİDƏN heç vaxt yazılmayan sütuna
-- qayıdır — Faza 3.2 retensiya hesablaması YENİDƏN "ölü yol" olar (data
-- itkisi DEYİL, mövcud möhürlər QALIR, YENİ möhür isə yaranmaz).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_server_employee_deactivated_at ON employees;
--   DROP FUNCTION IF EXISTS enforce_server_employee_deactivated_at();
-- COMMIT;
-- ===========================================================================
