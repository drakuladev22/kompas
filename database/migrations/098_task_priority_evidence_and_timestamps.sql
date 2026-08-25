-- ===========================================================================
-- 098 — `tasks`-A DÖRD ÇATIŞMAYAN SÜTUN: `priority`, `requires_evidence`,
--        `submitted_at`, `cancelled_at`
-- ===========================================================================
-- Tarix : 2026-08-25
-- Səbəb : `qa`-nın `test_entity_persistence_parity.py` qapısı (`hire_date`
--         tapıntısından sonra genişləndirilmiş sorğu) `entities/task.py`-da
--         DÖRD sahənin `tasks` cədvəlində qarşılığı olmadığını göstərdi.
--         Bunlar `PostgresTaskRepository._hydrate()`-də HƏR DƏFƏ sabit
--         dəyərə (`priority=NORMAL`, `requires_evidence=True`,
--         `submitted_at=None`, `cancelled_at=None`) sıfırlanırdı.
--
--         `requires_evidence` üçün bu, NƏZƏRİ DEYİL — TƏSDİQLƏNMİŞ AKTİV
--         QÜSURDUR: `TaskWorkflowUseCase.request_self_correction()` (Faza
--         4.2, v2backlog.md) `requires_evidence=FALSE` ilə tapşırıq yaradır
--         (izahat kifayətdir, foto istəyə-bağlıdır), lakin `submit_
--         evidence()` əvvəlcə DB-dən YENİDƏN oxuyur — `_hydrate()`-in
--         sabit `True`-su işçini fotosuz YENİDƏN cəhddə SƏHVƏN bloklayır.
--         Digər üç sahə üçün oxşar arqument: heç biri "qəsdən keçicidir"
--         deyə sənədləşdirilməyib, EYNİ formadakı `escalated_at` isə
--         ARTIQ davamlıdır.
--
-- ---------------------------------------------------------------------------
-- `priority` — NİYƏ TEXT+CHECK (`employee_transfer_status`-un ENUM-u DEYİL)
-- ---------------------------------------------------------------------------
-- `tasks.status`-un (`field_reports.status` ilə EYNİ) TEXT+CHECK naxışı
-- təkrarlanır: `TaskPriority` yalnız üç dəyərlidir, LAKİN `task_status` ENUM
-- DEYİL (schema.sql-də TEXT+CHECK) — eyni cədvəldə iki fərqli üslub
-- QARIŞDIRMAMAQ üçün `priority` DƏ TEXT+CHECK seçilir.
--
-- ---------------------------------------------------------------------------
-- `requires_evidence` DEFOLTU NİYƏ `TRUE` (`FALSE` DEYİL)
-- ---------------------------------------------------------------------------
-- Mövcud sətirlərdə dəyər YOXDUR — köhnə davranış (sübut MƏCBURİDİR,
-- `Task.__init__`-in öz defoltu `requires_evidence: bool = True`) QORUNMALI-
-- DIR. `FALSE` defolt seçilsəydi, BÜTÜN köhnə tapşırıqlar SÜKUTLA
-- "sübut istəyə-bağlıdır" statusuna keçərdi — bu, `submit_evidence()`-in
-- indiyədək TƏTBİQ ETDİYİ məcburiyyəti geriyə-təsirli LƏĞV edərdi.
--
-- ---------------------------------------------------------------------------
-- SXEM/MİQRASİYA PARİTETİ (§7) — DƏYİŞİKLİK LAZIM DEYİL
-- ---------------------------------------------------------------------------
-- Bunlar TAMAM YENİ sütunlardır, mövcud trigger/indeks/constraint YENİDƏN
-- yazılmır — `schema.sql` YENİLƏNMİR.
--
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'NORMAL'
        CHECK (priority IN ('LOW', 'NORMAL', 'HIGH')),
    ADD COLUMN IF NOT EXISTS requires_evidence BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

COMMENT ON COLUMN tasks.priority IS
    '`entities/task.py::TaskPriority` — YARADILIŞDA seçilir (`group_f.py` '
    'UI), heç bir ekran hazırda sıralamır/filtrləmir, LAKİN bu, TƏSADÜFDƏNDİR '
    'DİZAYN QƏRARI DEYİL — sütun olmadan dəyər hər oxunuşda `NORMAL`-a '
    'sıfırlanırdı (migrations/098).';

COMMENT ON COLUMN tasks.requires_evidence IS
    'YARADILIŞDA təyin olunur (`Task.__init__` defoltu `TRUE`). `FALSE` = '
    'Faza 4.2 öz-düzəliş sorğusu (`request_self_correction`) — izahat '
    'kifayətdir, foto istəyə-bağlıdır. Sütun olmadan `submit_evidence()`-in '
    'DB-dən yenidən oxuduğu tapşırıq HƏMİŞƏ `TRUE` görürdü və fotosuz '
    'YENİDƏN cəhdi SƏHVƏN bloklayırdı (migrations/098, AKTİV qüsur idi).';

COMMENT ON COLUMN tasks.submitted_at IS
    '`Task.submit_evidence()`-in möhürlədiyi an — sübutun NƏ VAXT '
    'yükləndiyinin tarixçəsi. Sütun olmadan hər oxunuşda `NULL`-a '
    'sıfırlanırdı (migrations/098).';

COMMENT ON COLUMN tasks.cancelled_at IS
    '`Task.cancel()`-in möhürlədiyi an — ləğvin tarixçəsi. Sütun olmadan '
    'hər oxunuşda `NULL`-a sıfırlanırdı (migrations/098).';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Sütunlar silinsə `requires_evidence`/`priority`/`submitted_at`/
-- `cancelled_at` YENİDƏN hər oxunuşda sabit dəyərə sıfırlanar — Faza 4.2
-- öz-düzəliş axını YENİDƏN "fotosuz resubmit sərhəddi" qüsuruna qayıdar.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE tasks
--     DROP COLUMN IF EXISTS priority,
--     DROP COLUMN IF EXISTS requires_evidence,
--     DROP COLUMN IF EXISTS submitted_at,
--     DROP COLUMN IF EXISTS cancelled_at;
-- COMMIT;
-- ===========================================================================
