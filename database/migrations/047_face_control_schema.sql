-- ===========================================================================
-- 047 — FACE CONTROL (ÜZ TƏSDİQİ): BİOMETRİK SAXLAMA QATI
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : `facecontrol.md` Faza 1. Face Control PIN-i ƏVƏZ ETMİR — onun
--         ÜSTÜNƏ qoyulan anti-aldatma qatıdır: PIN "kim olduğunu BİLİRSƏN"
--         sualına, üz isə "kim OLDUĞUNA" cavab verir. İkisi ayrı-ayrılıqda
--         oğurlana bilər, birlikdə isə praktikada yox.
--
--         Bu miqrasiya YALNIZ ƏLAVƏ EDİR: dörd yeni cədvəl, `employees`-ə
--         dörd yeni sütun, bir icazə flag-i, bir istisna mənbəyi və ON
--         ROOT parametri. Heç bir mövcud cədvəl silinmir, heç bir sütunun
--         tipi dəyişmir, heç nəyin adı dəyişdirilmir.
--
-- İdempotentdir (`IF NOT EXISTS` / `DROP ... IF EXISTS` / `ON CONFLICT`).
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- 1C SƏRHƏDİ
-- ---------------------------------------------------------------------------
-- Buradakı HEÇ BİR cədvəl 1C-yə yeni bağlantı/sync nöqtəsi AÇMIR. Sistemdə
-- 1C-yə toxunan yeganə kanal Satış Xalları axınıdır (`sales_transactions` →
-- `points_ledger`) və ona TOXUNULMUR. Üz müqayisəsi tam LOKALDIR (on-device,
-- `facecontrol.md` bənd 3) — nə 1C-yə, nə buluda heç nə göndərilmir.
--
-- ---------------------------------------------------------------------------
-- BİOMETRİK MƏLUMATIN DÖRD SƏRT QAYDASI (bu sxemin təməli)
-- ---------------------------------------------------------------------------
--   (1) FOTO SAXLANMIR. Bu miqrasiyada kadr/şəkil saxlayan BİR sütun da
--       yoxdur — nə `BYTEA`, nə fayl yolu, nə Drive açarı. Saxlanılan yeganə
--       şey riyazi vektordur və vektordan üz BƏRPA EDİLƏ BİLMİR. Şəkil
--       saxlamaq cazibədar görünürdü ("sonra yenidən hesablayarıq"), lakin
--       o, sistemi biometrik ŞƏKİL bazasına çevirərdi: sızma halında zərər
--       ölçüyəgəlməz olardı, halbuki vektor sızması yalnız bu sistemə
--       xasdır və yenidən qeydiyyatla dəyərsizləşdirilir.
--   (2) VEKTOR AÇIQ MƏTN DEYİL. `face_embedding` tətbiq qatında mövcud
--       şifrələmə modulu ilə (`infrastructure/security/encryption.py`,
--       AES-256-GCM / köhnə Fernet token-ləri ilə uyğun) şifrələnir və
--       bazaya YALNIZ şifrələnmiş token kimi yazılır.
--   (3) DEAKTİVASİYADA SİLİNİR. İşçi deaktiv ediləndə vektor həmin anda
--       silinir (bənd 8) — bu, tətbiq qatının işidir, lakin qayda sütun
--       şərhində YAZILIR ki, sxemi oxuyan adam onu kəşf etməsin.
--   (4) JURNALDA VEKTOR YOXDUR. `face_verification_log` yalnız NƏTİCƏ və
--       BAL saxlayır. Əks halda hər doğrulama cəhdi ikinci bir biometrik
--       nüsxə yaradardı və (3)-dəki silmə mənasız olardı.
--
-- ---------------------------------------------------------------------------
-- `face_embedding` NİYƏ `TEXT`, NİYƏ `BYTEA` DEYİL
-- ---------------------------------------------------------------------------
-- Vektorun ÖZÜ ədədlər massividir — saf `BYTEA` ilk baxışda təbii görünür.
-- Lakin bazaya yazılan şey vektor DEYİL, onun ŞİFRƏLƏNMİŞ TOKENİDİR və
-- `EncryptionService.encrypt()` layihədə `str` qaytarır (base64url ASCII).
-- Üç variant nəzərdən keçirildi:
--
--   (a) `BYTEA` + tətbiq qatında `str` ↔ `bytes` çevirmə — RƏDD EDİLDİ:
--       psycopg `BYTEA`-nı `memoryview` kimi qaytarır, yəni HƏR oxuda əlavə
--       çevirmə və `mypy --strict` altında əlavə tip keçidi lazım olardı.
--       Üstəlik mövcud şifrəli sütunların HAMISI (`erp_connections.
--       password_encrypted`, `store_server_mapping.config_json_encrypted`,
--       `drive_connections.refresh_token_encrypted`) `TEXT`-dir — yeni tip
--       eyni qatda iki fərqli konvensiya yaradardı.
--   (b) `BYTEA` + DB-də şifrələmə (`pgcrypto`) — RƏDD EDİLDİ: açar onda
--       baza serverində olardı, halbuki layihənin təhdid modeli məhz baza
--       nüsxəsinin sızmasını nəzərdə tutur (SEC — açar tətbiq tərəfindədir).
--   (c) SEÇİLDİ: `TEXT`. Şifrələnmiş token onsuz da ASCII-dir, mövcud üç
--       sütunla eyni naxışdır və heç bir çevirmə tələb etmir.
--
-- ---------------------------------------------------------------------------
-- `face_embedding_history` NİYƏ AYRICA CƏDVƏLDİR
-- ---------------------------------------------------------------------------
-- `facecontrol.md` bənd 2 hərfi oxunuşda «`employees.face_embedding_history`»
-- yazır, yəni sütun kimi. Bir sütun isə TARİXÇƏ saxlaya bilməz: ikinci
-- yenidən-qeydiyyatda birinci arxiv üstündən yazılardı və "bu işçinin üzü
-- neçə dəfə dəyişdirilib?" sualı cavabsız qalardı — halbuki məhz bu sual
-- aldatma axtarışının özüdür (tez-tez yenidən qeydiyyat şübhəlidir).
-- `JSONB` massiv variantı da rədd edildi: onda hər arxiv sətrinin kim/nə
-- vaxt/nə üçün sahələri sxemsiz qalar, FK olmaz və silmə (aşağıdakı
-- `PURGED`) sətir-səviyyəli deyil, mətn-redaktəsi əməliyyatına çevrilərdi.
--
-- ARXİVDƏ VEKTORUN SİLİNMƏSİ — ƏN VACİB DETAL:
-- Bənd 8 deaktivasiyada vektorun silinməsini tələb edir. Arxiv cədvəli
-- KÖHNƏ vektorları saxladığı üçün, yalnız `employees.face_embedding`-i
-- təmizləmək qaydanı SÜKUTLA pozardı — biometrik məlumat arxivdə yaşamağa
-- davam edərdi. Ona görə arxiv sətrinin iki statusu var: `REPLACED` (vektor
-- var, yenisi ilə əvəzlənib) və `PURGED` (vektor SİLİNİB, yalnız kim/nə
-- vaxt izi qalıb). `CHECK` bu ikisini bir-birinə bağlayır, yəni "silindi"
-- deyib vektoru saxlamaq mümkün deyil.
--
-- ---------------------------------------------------------------------------
-- MISMATCH SAYĞACI NİYƏ `employees` SÜTUNUDUR (AYRICA CƏDVƏL DEYİL)
-- ---------------------------------------------------------------------------
-- MÖVCUD PIN-lockout strukturuna baxıldı: `schema.sql` §7 sayğacı ayrıca
-- kredensial cədvəlində DEYİL, `employees.pin_failed_attempts` /
-- `employees.pin_locked_until` sütunlarında saxlayır. EYNİ naxış təkrarlanır
-- (`face_mismatch_attempts` / `face_locked_until`), çünki:
--   * hər doğrulamada onsuz da işçi sətri oxunur — ayrıca cədvəl hər
--     kiosk əməliyyatına bir JOIN əlavə edərdi;
--   * lockout MEXANİZMİ (müddət, UI, açma yolu) eynidir və bənd 4 açıq
--     şəkildə "yeni mexanizm yazma, mövcudu ÇAĞIR" deyir.
--
-- SAYĞAC İSƏ TAM AYRIDIR (bənd 3): `NO_FACE_DETECTED` ona DAXİL EDİLMİR —
-- kameranın üzü görməməsi texniki nasazlıqdır, aldatma siqnalı deyil. Onları
-- birləşdirsəydik, işıqsız dəhlizdə duran vicdanlı işçi üç cəhddən sonra
-- kilidlənərdi və sistem "təhlükəsiz" görünüb faktiki olaraq işi dayandırardı.
-- Yalnız `MISMATCH` artırır. İki sayğacın AYRI sütunlarda olması bu qaydanı
-- struktur şəkildə mümkün edir: bir sütunu artıran kod digərinə toxunmur.
--
-- ---------------------------------------------------------------------------
-- MAĞAZA SİYAHISI (bənd 15) NİYƏ AYRICA CƏDVƏL, NİYƏ VERGÜLLÜ `system_limits` DEYİL
-- ---------------------------------------------------------------------------
-- Layihədə vergüllü-siyahı naxışı var (`EXECUTIVE_DIGEST_METRIC_CATALOG`,
-- `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`), lakin onların məzmunu KOD
-- sətirləridir və ya ədədlərdir — heç biri başqa cədvəlin sətrinə istinad
-- etmir. Mağaza siyahısı isə FK-lı varlıqlar toplusudur və layihə bu sualı
-- artıq bir dəfə həll edib: `announcement_targets` (migrations/020) məhz
-- `store_ids UUID[]`/`JSONB` variantını RƏDD edib, çünki
--   * FK olmadan silinmiş və ya BAŞQA kirayəçiyə aid mağaza ID-si sükutla
--     siyahıda qalır;
--   * `system_limits.limit_value` sərbəst mətndir — Root bir simvol səhv
--     yazsa, Face Control həmin mağazada SÜKUTLA sönərdi (fail-open, ən
--     təhlükəli uğursuzluq forması);
--   * "bu mağazada Face Control nə vaxt açıldı?" sualı vergüllü sətirdə
--     cavabsızdır.
-- Ona görə `face_control_store_scope` uşaq cədvəli seçildi — eyni naxış,
-- eyni RLS, real `FOREIGN KEY`.
--
-- QLOBAL TOGGLE TOXUNULMUR: `feature_toggles` cədvəli və onun retroaktivlik
-- qaydası olduğu kimi qalır. Bu cədvəl onun ÜSTÜNDƏ dar süzgəcdir: AKTİV
-- sətir yoxdursa (defolt) davranış BUGÜNKÜ ilə eynidir — qlobal toggle nə
-- deyirsə, o olur.
--
-- ---------------------------------------------------------------------------
-- `FACE_MISMATCH` MÖVCUD İSTİSNA MOTORUNA SEED EDİLİR (bənd 16)
-- ---------------------------------------------------------------------------
-- `exception_sources` (migrations/018) bazadan idarə olunan kataloqdur —
-- yeni mənbə DDL deyil, bir `INSERT`-dir və motorun kodu DƏYİŞMİR.
-- `default_severity = 'CRITICAL'` seçildi: `BEHAVIOR_ANOMALY` (MEDIUM)
-- statistik kənarlaşmadır və izahı ola bilər (avtobus gecikdi), MISMATCH isə
-- "bu PIN-in sahibi ilə kameradakı şəxs eyni adam DEYİL" deməkdir — bu,
-- sistemdəki ƏN GÜCLÜ fırıldaqçılıq siqnalıdır və sıralamada hər şeydən
-- yuxarıda durmalıdır.
--
-- DİQQƏT (bənd 16-nın təhlükəsizlik qeydi): bu seed mövcud "İLK DƏFƏDƏN
-- DƏRHAL bildiriş" mexanizmini ƏVƏZ ETMİR, ona ƏLAVƏ olunur. İstisna
-- siyahısı "sonra baxaram" effekti yaradır; MISMATCH öz təcili kanalını
-- itirməməlidir.
--
-- ---------------------------------------------------------------------------
-- `can_manage_face_exemptions` NİYƏ YENİ FLAG-DİR (bənd 14)
-- ---------------------------------------------------------------------------
-- Mövcud `can_manage_employees` KİFAYƏT ETMİR: onun `hardlock_level = 0`-dır,
-- yəni Root/CEO onu istənilən HR-səviyyəli admin-ə həvalə edə bilər. Face
-- Control istisnası isə PIN-only yoludur — özü bir aldatma-yoluna çevrilə
-- bilər. Ona görə yeni flag `hardlock_level = 2` (`HardlockLevel.ROOT_CEO`)
-- ilə elan olunur: `enforce_permission_hardlock()` (schema.sql §18) və domen
-- tərəfi (`PermissionFlag.assert_grantable_to`) onu AVTOMATİK olaraq yalnız
-- `ROOT`/`CEO` rollarında buraxır — yeni guard yazılmır.
--
-- SƏVİYYƏ 1 (yalnız Root) NİYƏ SEÇİLMƏDİ: bənd 14 açıq şəkildə "YALNIZ
-- Root/CEO" deyir. Səviyyə 1 CEO-nu da kənarda qoyardı və spesifikasiyadan
-- daha sərt olardı — sərtləşdirmə də spesifikasiyadan sapmadır.
--
-- ---------------------------------------------------------------------------
-- İLKİN HƏDD DƏYƏRLƏRİ — PİLOT-ƏSASLI TƏNZİMLƏMƏ
-- ---------------------------------------------------------------------------
-- `FACE_MATCH_TOLERANCE` = 0.60 `face_recognition` (Dlib) kitabxanasının
-- SƏNƏDLƏŞDİRİLMİŞ defoltudur (`compare_faces(..., tolerance=0.6)`). Bu,
-- "doğru" ədəd DEYİL, başlanğıc nöqtəsidir: real dəyər mağaza işığından,
-- kamera keyfiyyətindən və heyətin tərkibindən asılıdır və PİLOT mağazada
-- ölçülərək tənzimlənməlidir. Məhz buna görə hər ikisi `system_limits`-dədir.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `employees` — DÖRD YENİ SÜTUN (mövcud sütunlara TOXUNULMUR)
-- ---------------------------------------------------------------------------
ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS face_embedding         TEXT,
    ADD COLUMN IF NOT EXISTS face_enrolled_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS face_mismatch_attempts SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS face_locked_until      TIMESTAMPTZ;

-- `CHECK` ayrıca əlavə olunur: `ADD COLUMN IF NOT EXISTS` sütun ARTIQ varsa
-- heç nə etmir və məhdudiyyəti də qoymur (migrations/045 ilə eyni naxış).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_employee_face_mismatch_attempts'
           AND connamespace = current_schema()::regnamespace
    ) THEN
        ALTER TABLE employees
            ADD CONSTRAINT chk_employee_face_mismatch_attempts
            CHECK (face_mismatch_attempts >= 0);
    END IF;
END
$$;

-- QEYDİYYAT ANI VEKTORSUZ OLA BİLMƏZ VƏ ƏKSİ: `face_enrolled_at` bənd 13-ün
-- «köhnəlib» hesablamasının YEGANƏ mənbəyidir. Vektor var, tarix yoxdursa,
-- xatırlatma heç vaxt işə düşməz və qeydiyyat sükutla əbədi «təzə» qalar.
-- Tarix var, vektor yoxdursa (deaktivasiyadan sonra yarımçıq təmizləmə),
-- admin panelində «qeydiyyatlı» görünən, faktiki olaraq isə doğrulana
-- bilməyən işçi yaranardı.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_employee_face_enrollment_pair'
           AND connamespace = current_schema()::regnamespace
    ) THEN
        ALTER TABLE employees
            ADD CONSTRAINT chk_employee_face_enrollment_pair
            CHECK ((face_embedding IS NULL) = (face_enrolled_at IS NULL));
    END IF;
END
$$;

COMMENT ON COLUMN employees.face_embedding IS
    'ŞİFRƏLƏNMİŞ üz vektoru (istinad embedding). AÇIQ MƏTN DEYİL — tətbiq '
    'qatı onu `infrastructure/security/encryption.py` ilə (AES-256-GCM, '
    'köhnə Fernet token-ləri ilə uyğun) şifrələyir və bazaya yalnız token '
    'yazılır. FOTO SAXLANMIR: bu sütun kadr deyil, vektordur və vektordan '
    'şəkil bərpa edilə bilmir. DƏYƏR TƏK KADRDAN GƏLMİR — enrollment zamanı '
    'çəkilən BİR NEÇƏ kadrın embedding-lərinin RİYAZİ ORTASIDIR '
    '(facecontrol.md bənd 11): tək kadr təsadüfi işıq/açı xətasını istinad '
    'nöqtəsinə çevirərdi. SİLİNMƏ QAYDASI: işçi deaktiv ediləndə bu sütun '
    'HƏMİN ANDA `NULL` edilir (bənd 8) — qayda tətbiq qatındadır (mövcud '
    '«işçini deaktiv et» use case-i), lakin sxemdən oxunan adam üçün burada '
    'yazılır. Arxiv nüsxəsi `face_embedding_history`-də `PURGED` statusu ilə '
    'eyni anda təmizlənir.';
COMMENT ON COLUMN employees.face_enrolled_at IS
    'Cari istinad vektorunun qeydiyyat anı (tz-aware). Bənd 13-ün «üz-'
    'qeydiyyatı köhnəlib» xəbərdarlığı MƏHZ bu tarixdən hesablanır '
    '(`FACE_REENROLLMENT_REMINDER_MONTHS`). Xəbərdarlıq BLOKLAMIR — insan '
    'üzü zamanla dəyişir (saqqal, eynək, yaş) və bu, admin üçün tövsiyədir.';
COMMENT ON COLUMN employees.face_mismatch_attempts IS
    'Ardıcıl MISMATCH sayğacı — PIN sayğacından (`pin_failed_attempts`) TAM '
    'AYRIDIR (bənd 3). `NO_FACE_DETECTED` bu sayğaca DAXİL EDİLMİR: kameranın '
    'üzü görməməsi texniki nasazlıqdır, aldatma siqnalı deyil. Uğurlu '
    'doğrulamada sıfırlanır. Hədd `FACE_MISMATCH_LOCKOUT_THRESHOLD`-dadır.';
COMMENT ON COLUMN employees.face_locked_until IS
    'Üz-uyğunsuzluğuna görə kilid bitmə anı (tz-aware). Kilidin MÜDDƏTİ yeni '
    'parametr DEYİL — mövcud `PIN_LOCKOUT_MINUTES` işlədilir, çünki bənd 4 '
    'lockout MEXANİZMİNİN təkrar yazılmasını qadağan edir; yalnız SAYĞAC və '
    'HƏDD ayrıdır. `pin_locked_until` ilə eyni anda dolu ola bilər — ikisi '
    'müstəqil qapıdır və hər ikisi keçilməlidir.';

-- Bu indeks İKİ sorğuya xidmət edir və ona görə TƏK indeksdir:
--   (a) MISMATCH cross-check (bənd 3) — «EYNİ mağazanın qeydiyyatlı digər
--       işçiləri» dəsti (`tenant_id`, `store_id` prefiksi);
--   (b) bənd 13 «köhnəlmiş qeydiyyat» taraması (`face_enrolled_at` sıralaması).
-- Qismən şərt vacibdir: qeydiyyatsız işçilər (yeni işə götürülənlər, istisnalı
-- işçilər) indeksin yarısını doldurardı və heç bir sorğuda lazım olmazdı.
CREATE INDEX IF NOT EXISTS idx_employees_face_enrolled
    ON employees (tenant_id, store_id, face_enrolled_at)
    WHERE face_embedding IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. `face_embedding_history` — ARXİV (bənd 2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS face_embedding_history (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,
    -- CASCADE: arxiv işçi sətrinin törəməsidir və ondan uzun yaşamağın mənası
    -- yoxdur — biometrik məlumatın sahibsiz qalması təhlükəsizlik riskidir,
    -- üstünlük deyil. Praktikada işçilər fiziki silinmir (`is_active` soft
    -- delete), ona görə bu yol yalnız kirayəçi tam ləğv olunanda işə düşür.
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    -- Arxivlənən ŞİFRƏLƏNMİŞ vektor. `NULL` OLA BİLƏR və bu, qəsdən belədir:
    -- `PURGED` statusunda vektor silinir, sətir isə "burada bir qeydiyyat var
    -- idi" faktının izi kimi qalır (aşağıdakı CHECK ikisini bağlayır).
    face_embedding TEXT,

    -- Arxivlənən vektorun İLKİN qeydiyyat anı — `employees.face_enrolled_at`
    -- dəyərinin köçürülmüş nüsxəsi. Onsuz "bu vektor nə qədər işlədi?" sualı
    -- cavabsız qalar və tez-tez yenidən-qeydiyyat naxışı görünməzdi.
    enrolled_at    TIMESTAMPTZ NOT NULL,
    -- Arxivə düşmə anı (yenidən-qeydiyyat və ya təmizləmə anı).
    archived_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    status         TEXT NOT NULL DEFAULT 'REPLACED'
                       CHECK (status IN ('REPLACED', 'PURGED')),

    -- SET NULL: arxiv sətri əməliyyatı aparan admin-in profilindən uzun
    -- yaşamalıdır — "kim dəyişdirdi?" sualının mətn izi `audit_logs`-dadır.
    archived_by    UUID REFERENCES employees(id) ON DELETE SET NULL,

    -- NİYƏ SƏBƏB SÜTUNU VAR: yenidən-qeydiyyat nəzarətli əməliyyatdır və
    -- səbəbsizi şübhəlidir (bənd 2). `pos_permission_thresholds.note` ilə eyni
    -- əsaslandırma: səbəbsiz qərar mübahisədə müdafiə olunmur.
    reason         TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- «SİLİNDİ» DEYİB SAXLAMAQ MÜMKÜN DEYİL: bənd 8-in silmə tələbi arxivə də
    -- aiddir, əks halda biometrik məlumat burada yaşamağa davam edərdi.
    CONSTRAINT chk_face_history_purge
        CHECK ((status = 'PURGED') = (face_embedding IS NULL))
);

-- İşçi profilində «üz-qeydiyyatı tarixçəsi» bölməsi — ən yenisi əvvəldə.
CREATE INDEX IF NOT EXISTS idx_face_history_employee
    ON face_embedding_history (employee_id, archived_at DESC);

COMMENT ON TABLE face_embedding_history IS
    'Üz qeydiyyatının ARXİVİ (facecontrol.md bənd 2). Köhnə vektor '
    'yenidən-qeydiyyatda SİLİNMİR, `REPLACED` statusu ilə bura köçürülür — '
    '"bu işçinin üzü neçə dəfə və kim tərəfindən dəyişdirilib?" sualı '
    'aldatma axtarışının özüdür. Spesifikasiya bunu `employees` sütunu kimi '
    'yazır, lakin BİR sütun tarixçə saxlaya bilməz (ikinci dəyişiklik '
    'birincini üstündən yazardı) — ona görə AYRICA cədvəldir. Cədvəldə '
    'kadr/şəkil YOXDUR, yalnız şifrələnmiş vektor.';
COMMENT ON COLUMN face_embedding_history.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN face_embedding_history.tenant_id IS
    'Kirayəçi izolyasiyası — RLS `tenant_isolation` siyasətinin açarı.';
COMMENT ON COLUMN face_embedding_history.employee_id IS
    'Arxivlənən qeydiyyatın sahibi olan işçi.';
COMMENT ON COLUMN face_embedding_history.face_embedding IS
    'Arxivlənən ŞİFRƏLƏNMİŞ vektor (açıq mətn DEYİL, foto DEYİL). `PURGED` '
    'statusunda `NULL`-dur: işçi deaktiv ediləndə (bənd 8) yalnız '
    '`employees.face_embedding` təmizlənsəydi, biometrik məlumat MƏHZ BURADA '
    'sağ qalar və silmə qaydası sükutla pozulardı.';
COMMENT ON COLUMN face_embedding_history.enrolled_at IS
    'Arxivlənən vektorun İLKİN qeydiyyat anı (tz-aware) — `employees.'
    'face_enrolled_at` dəyərinin köçürülmüş nüsxəsi. "Bu vektor nə qədər '
    'istifadədə qaldı?" sualının yeganə cavabı.';
COMMENT ON COLUMN face_embedding_history.archived_at IS
    'Arxivə düşmə anı (tz-aware) — yenidən-qeydiyyat və ya təmizləmə anı.';
COMMENT ON COLUMN face_embedding_history.status IS
    'REPLACED = yeni qeydiyyatla əvəzlənib (vektor saxlanılır); '
    'PURGED = işçi deaktiv edilib və vektor SİLİNİB (yalnız iz qalıb). '
    'Siyahı SƏRTDİR: hər iki dəyər fərqli DAVRANIŞ deməkdir, yeni dəyər kod '
    'dəyişikliyi olmadan mənasızdır (`exceptions.status` ilə eyni qərar).';
COMMENT ON COLUMN face_embedding_history.archived_by IS
    'Yenidən-qeydiyyatı/təmizləməni aparan şəxs. İşçi qeydi silinsə `NULL` '
    'olur, arxiv sətri qalır. Tam mətn izi `audit_logs`-dadır.';
COMMENT ON COLUMN face_embedding_history.reason IS
    'Yenidən-qeydiyyatın səbəbi (məs. «eynək dəyişdi», «tanınma pisləşdi»). '
    'Səbəbsiz təkrar qeydiyyat auditdə müdafiə oluna bilməz.';
COMMENT ON COLUMN face_embedding_history.created_at IS 'Sətrin yaradılma anı (tz-aware).';

-- ---------------------------------------------------------------------------
-- 3. `face_verification_log` — HƏR CƏHDİN JURNALI (bənd 9, 12)
-- ---------------------------------------------------------------------------
-- NİYƏ `result` VƏ `trigger_context` SƏRT `CHECK` SİYAHISIDIR (`exceptions.
-- source`-dan FƏRQLİ OLARAQ): hər iki siyahı DAVRANIŞ açarıdır, etiket deyil.
-- Dördüncü nəticə növü yeni axın (yeni sayğac qaydası, yeni ekran mətni),
-- dördüncü tətbiq nöqtəsi isə yeni use case deməkdir — hər ikisi onsuz da
-- kod dəyişikliyi tələb edir, yəni miqrasiya əlavə yük yaratmır. Genişlənmə
-- nöqtəsi burada YOXDUR; o, `exception_sources` kataloqundadır.
--
-- `trigger_context` DƏYƏRLƏRİ MÖVCUD SÖZLÜKDƏN GÖTÜRÜLÜB: `morning_check_in.
-- py` və `leave_verification.py` `_verified_now(operation=...)` çağırışlarında
-- artıq `STEP_A` / `STEP_1` / `STEP_2` yazır. Yeni ad məkanı qurmaq (`MORNING_
-- CHECK_IN_STEP_A` kimi) `menu.py` başlığındakı qüsurun eynisi olardı: iki
-- siyahı bir müddət üst-üstə düşər, sonra sükutla ayrılardı.
CREATE TABLE IF NOT EXISTS face_verification_log (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 UUID NOT NULL REFERENCES license_tenants(tenant_id)
                                  ON DELETE CASCADE,
    -- CASCADE: jurnal işçi haqqındadır. Praktikada işçi soft delete edilir,
    -- ona görə bu yol yalnız kirayəçi ləğvində işə düşür.
    employee_id               UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    -- SET NULL və AYRICA saxlanılır (`exceptions.store_id` ilə eyni qərar):
    -- işçi sonradan başqa filiala keçsə, tarixi cəhd öz mağazasında qalmalıdır.
    -- MISMATCH cross-check-i mağaza-əhatəlidir (bənd 3) və HR süzgəci də.
    store_id                  UUID REFERENCES stores(id) ON DELETE SET NULL,

    -- Doğrulamanın BAŞ VERDİYİ an (`Clock` portundan, tz-aware).
    occurred_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    result                    TEXT NOT NULL
                                  CHECK (result IN ('SUCCESS', 'NO_FACE_DETECTED', 'MISMATCH')),
    trigger_context           TEXT NOT NULL
                                  CHECK (trigger_context IN ('STEP_A', 'STEP_1', 'STEP_2')),

    -- SET NULL: uyğun gələn işçinin qeydi silinsə də hadisə jurnalda qalmalıdır.
    matched_other_employee_id UUID REFERENCES employees(id) ON DELETE SET NULL,

    lockout_triggered         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Bənd 12 — NƏTİCƏ BİNAR DEYİL: faktiki oxşarlıq FAİZİ (0–100).
    -- `NULL` yalnız `NO_FACE_DETECTED` halında olur (müqayisə ediləcək üz yoxdur).
    confidence_score          NUMERIC(5, 2)
                                  CHECK (confidence_score IS NULL
                                     OR (confidence_score >= 0 AND confidence_score <= 100)),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: "aşağı-etibarlı təsdiq" QƏRARI həmin anda
    -- qüvvədə olan `FACE_LOW_CONFIDENCE_TOLERANCE` dəyərinə görə verilir. Onu
    -- saxlamayıb sonradan baldan yenidən hesablasaydıq, Root həddi dəyişən
    -- kimi KEÇMİŞ qeydlərin nişanı da dəyişərdi — Kamera Operatorunun o gün
    -- GÖRDÜYÜ şey geriyə dönük saxtalaşardı.
    is_low_confidence         BOOLEAN NOT NULL DEFAULT FALSE,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA (bənd 6): hansı liveness hərəkəti TƏLƏB
    -- edildiyi. Randomlaşdırmanın həqiqətən işlədiyi yalnız jurnaldan
    -- yoxlana bilər — bütün sətirlərdə eyni hərəkət görünürsə, təsadüfilik
    -- sınıb və qorumanın özü mənasızlaşıb. Sərt `CHECK` QOYULMUR: aktiv
    -- hərəkətlər siyahısı ROOT parametridir (`FACE_LIVENESS_ACTIONS`) və
    -- `CHECK` onunla ikinci, sürüşən mənbə yaradardı.
    liveness_action           TEXT,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA (bənd 18): doğrulamanın davam etdiyi vaxt.
    -- System Health Monitor-a yalnız XƏBƏRDARLIQ yazmaq kifayət etmir —
    -- "hansı kiosk, hansı saatda yavaşdır?" sualı ölçmə SIRASI tələb edir.
    -- KRİTİK QAYDA: bu sütun diaqnostika üçündür və HEÇ VAXT keyfiyyət
    -- parametrlərini (kadr sayı, alignment, hədd) avtomatik zəiflətmək üçün
    -- istifadə edilmir — həll yolu hardware/optimallaşdırmadır.
    duration_ms               INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),

    -- Sətrin bazaya düşdüyü an. `occurred_at`-dan FƏRQLİ ola bilər: kiosk
    -- oflayn buferdə işləyir (`infrastructure/offline`) və sətir bağlantı
    -- bərpa olunanda yazılır. İki sütunu birləşdirsəydik, oflayn dövrün bütün
    -- cəhdləri sinxronizasiya anına yığılardı.
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- ÜZ TAPILMAYIBSA BAL DA YOXDUR: müqayisə ümumiyyətlə aparılmayıb.
    -- `0.00` yazmaq daha sadə görünürdü, lakin o, "tamamilə fərqli üz"
    -- mənasına gələrdi və hesabatda MISMATCH kimi oxunardı.
    CONSTRAINT chk_face_log_no_face_has_no_score
        CHECK (result <> 'NO_FACE_DETECTED' OR confidence_score IS NULL),
    -- Cross-check nəticəsi YALNIZ uyğunsuzluqda mənalıdır (bənd 3).
    CONSTRAINT chk_face_log_match_only_on_mismatch
        CHECK (matched_other_employee_id IS NULL OR result = 'MISMATCH'),
    -- İşçinin özü ilə "uyğun gəlməsi" MISMATCH ola bilməz — belə sətir
    -- hesabatda anlaşılmaz olardı.
    CONSTRAINT chk_face_log_match_is_another_person
        CHECK (matched_other_employee_id IS NULL
            OR matched_other_employee_id <> employee_id),
    -- "Aşağı-etibarlı təsdiq" YALNIZ təsdiq halında var (bənd 12).
    CONSTRAINT chk_face_log_low_confidence_only_on_success
        CHECK (NOT is_low_confidence OR result = 'SUCCESS'),
    -- Kilid YALNIZ MISMATCH sayğacından doğur (bənd 3/4).
    CONSTRAINT chk_face_log_lockout_only_on_mismatch
        CHECK (NOT lockout_triggered OR result = 'MISMATCH')
);

-- İşçi detal panelində «bu işçinin üz-doğrulamaları» + MISMATCH sayğacının
-- yenidən hesablanması.
CREATE INDEX IF NOT EXISTS idx_face_verification_log_employee
    ON face_verification_log (employee_id, occurred_at DESC);
-- HR/Mağaza Meneceri üçün ƏSAS sorğu: uyğunsuzluqlar, ən yenisi əvvəldə.
-- Qismən indeks: sətirlərin böyük əksəriyyəti `SUCCESS` olacaq və onlar bu
-- sorğuda heç vaxt lazım deyil.
CREATE INDEX IF NOT EXISTS idx_face_verification_log_mismatch
    ON face_verification_log (tenant_id, occurred_at DESC)
    WHERE result = 'MISMATCH';
-- Bənd 17 — gecəlik saxlama-müddəti təmizləməsi kirayəçi + yaş üzrə gedir.
CREATE INDEX IF NOT EXISTS idx_face_verification_log_retention
    ON face_verification_log (tenant_id, occurred_at);

COMMENT ON TABLE face_verification_log IS
    'Hər üz-doğrulama cəhdinin jurnalı (facecontrol.md bənd 9). Cədvəldə '
    'NƏ VEKTOR, NƏ KADR var — yalnız nəticə, bal və kontekst; əks halda hər '
    'cəhd ikinci bir biometrik nüsxə yaradar və deaktivasiyada silmə qaydası '
    '(bənd 8) mənasız olardı. Sətirlər `FACE_VERIFICATION_LOG_RETENTION_'
    'MONTHS` müddətindən sonra gecəlik işlə TAM SİLİNİR (anonimləşdirmə '
    'lazım deyil — silinəcək həssas məzmun onsuz da yoxdur).';
COMMENT ON COLUMN face_verification_log.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN face_verification_log.tenant_id IS
    'Kirayəçi izolyasiyası — RLS `tenant_isolation` siyasətinin açarı.';
COMMENT ON COLUMN face_verification_log.employee_id IS
    'PIN-i daxil edən (yəni doğrulanmaq İDDİASINDA olan) işçi.';
COMMENT ON COLUMN face_verification_log.store_id IS
    'Cəhdin baş verdiyi mağaza. AYRICA saxlanılır, çünki işçi sonradan başqa '
    'filiala keçə bilər — tarixi cəhd isə öz filialında qalmalıdır '
    '(`exceptions.store_id` ilə eyni qərar).';
COMMENT ON COLUMN face_verification_log.occurred_at IS
    'Doğrulamanın BAŞ VERDİYİ an (tz-aware, `Clock` portundan).';
COMMENT ON COLUMN face_verification_log.result IS
    'SUCCESS / NO_FACE_DETECTED / MISMATCH. İki uğursuzluq rejimi QƏSDƏN '
    'ayrılıb (bənd 3): NO_FACE_DETECTED texniki problemdir və heç bir '
    'sayğaca düşmür; MISMATCH isə ən güclü fırıldaqçılıq siqnalıdır və '
    'İLK DƏFƏDƏN dərhal bildiriş doğurur.';
COMMENT ON COLUMN face_verification_log.trigger_context IS
    'Hansı addımda tətbiq olundu: STEP_A (Səhər Check-in), STEP_1 (icazə '
    'sorğusu), STEP_2 (qayıdış). Dəyərlər mövcud `_verified_now(operation=...)` '
    'sözlüyündən götürülüb — ikinci ad məkanı qurulmur.';
COMMENT ON COLUMN face_verification_log.matched_other_employee_id IS
    'MISMATCH halında EYNİ MAĞAZANIN hansı işçisinə uyğun gəldiyi (bənd 3). '
    'Cross-check qəsdən mağaza ilə məhdudlaşır: bütün şəbəkə üzrə axtarış '
    'həm yavaş, həm də yalançı-müsbətə meyllidir. Uyğun tapılmasa `NULL`.';
COMMENT ON COLUMN face_verification_log.lockout_triggered IS
    'Bu cəhd MISMATCH sayğacını həddə çatdırıb kilidi işə saldımı '
    '(`FACE_MISMATCH_LOCKOUT_THRESHOLD`). Kilidin müddəti mövcud PIN '
    'mexanizmindən gəlir (`PIN_LOCKOUT_MINUTES`) — yeni mexanizm yazılmır.';
COMMENT ON COLUMN face_verification_log.confidence_score IS
    'Faktiki oxşarlıq FAİZİ (0–100) — nəticə binar deyil (bənd 12). '
    'NO_FACE_DETECTED halında `NULL` (müqayisə aparılmayıb). VAHİD QEYDİ: '
    'ROOT həddləri (`FACE_MATCH_TOLERANCE`, `FACE_LOW_CONFIDENCE_TOLERANCE`) '
    'kitabxananın öz vahidindədir — MƏSAFƏ (kiçik = oxşar). Faizə çevirmə '
    'yalnız İNSAN üçün, təqdimat qatındadır; qərar məsafə üzərində verilir ki, '
    'Root-un gördüyü ədədlə kitabxananın cavabı arasında gizli çevirmə sabiti '
    'oturmasın.';
COMMENT ON COLUMN face_verification_log.is_low_confidence IS
    '«Aşağı-etibarlı təsdiq» nişanı (bənd 12): əməliyyata icazə verilib, lakin '
    'bal tam-uyğunluq zolağının kənarındadır. Qərar HƏMİN ANDAKI hədd ilə '
    'verilir və saxlanılır — sonradan hesablansaydı, Root həddi dəyişəndə '
    'keçmiş qeydlərin nişanı da geriyə dönük dəyişərdi.';
COMMENT ON COLUMN face_verification_log.liveness_action IS
    'Bu cəhddə TƏLƏB olunan təsadüfi liveness hərəkəti (bənd 6). Sərt CHECK '
    'yoxdur: aktiv siyahı `FACE_LIVENESS_ACTIONS` ROOT parametrindədir. '
    'Sütun randomlaşdırmanın həqiqətən işlədiyini auditdə yoxlamağa imkan verir.';
COMMENT ON COLUMN face_verification_log.duration_ms IS
    'Doğrulamanın davam etdiyi müddət (millisaniyə) — bənd 18 performans '
    'diaqnostikası üçün. `FACE_VERIFICATION_MAX_SECONDS` aşılarsa System '
    'Health Monitor-a xəbərdarlıq yazılır. Bu ölçmə HEÇ VAXT keyfiyyət '
    'parametrlərini zəiflətmək üçün istifadə edilmir — həll hardware/kod '
    'optimallaşdırmasıdır, təhlükəsizlik güzəşti DEYİL.';
COMMENT ON COLUMN face_verification_log.created_at IS
    'Sətrin bazaya düşdüyü an (tz-aware). Oflayn buferdə gözləyən cəhdlərdə '
    '`occurred_at`-dan gec olur — ona görə iki sütun birləşdirilmir.';

-- ---------------------------------------------------------------------------
-- 4. `face_control_exemptions` — PIN-ONLY İSTİSNASI (bənd 14)
-- ---------------------------------------------------------------------------
-- Bu cədvəl bir BOŞLUQ yaradır (üz təsdiqi olmadan giriş), ona görə hər sütunu
-- həmin boşluğu daraltmağa xidmət edir:
--   * `expires_at` MƏCBURİDİR — istisna müvəqqətidir. `NULL` icazə versəydik,
--     "müvəqqəti" istisna sükutla əbədi qalardı və bu, ən çox rast gəlinən
--     təhlükəsizlik aşınması formasıdır.
--   * `reason` BOŞ OLA BİLMƏZ və ən azı 10 simvoldur (`export_manual_
--     corrections.reason` və `EXCEPTION_REVIEW_NOTE_MIN_LENGTH` ilə eyni
--     döşəmə) — «ok», «.» kimi cavablar sənəd sayılmır.
--   * FİZİKİ `DELETE` YOXDUR — ləğv edilmiş və müddəti bitmiş istisna sətir
--     kimi qalır: "həmin gün bu işçi niyə üz təsdiqindən keçmirdi?" sualının
--     yeganə struktur cavabıdır.
CREATE TABLE IF NOT EXISTS face_control_exemptions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    -- NO ACTION (CASCADE/SET NULL DEYİL): istisnanı KİMİN verdiyi sualı
    -- istisnadan uzun yaşayır və cavabsız qala bilməz — `announcements.
    -- created_by` ilə eyni qərar. Root/CEO qeydi fiziki silinməzdən əvvəl
    -- istisnalar arxivlənməlidir.
    granted_by     UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    reason         TEXT NOT NULL CHECK (char_length(trim(reason)) >= 10),

    granted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,

    status         TEXT NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('ACTIVE', 'EXPIRED', 'REVOKED')),

    -- ƏLAVƏ SÜTUNLAR — ƏSASLANDIRMA: `EXPIRED` avtomatik keçiddir (vaxt
    -- gəldi), `REVOKED` isə İNSAN QƏRARIDIR. Qərarın sahibi və səbəbi
    -- yazılmasa, "kim ləğv etdi?" sualı yalnız audit jurnalında qalar və
    -- ekranda göstərilə bilməzdi (`exceptions.reviewed_by` naxışı).
    revoked_by     UUID REFERENCES employees(id) ON DELETE SET NULL,
    revoked_at     TIMESTAMPTZ,
    revoke_reason  TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Sıfır və ya mənfi ömürlü istisna mənasızdır; belə sətir ekranda "aktiv"
    -- görünüb heç vaxt işləməzdi.
    CONSTRAINT chk_face_exemption_window CHECK (expires_at > granted_at),
    -- Ləğv QƏRARDIR: qərar verən və an olmadan status dəyişə bilməz
    -- (`shift_swap_requests.chk_swap_decision` / `exceptions.chk_exception_review`
    -- ilə eyni naxış).
    CONSTRAINT chk_face_exemption_revocation
        CHECK (status <> 'REVOKED'
            OR (revoked_by IS NOT NULL AND revoked_at IS NOT NULL))
);

-- BİR İŞÇİ, BİR AKTİV İSTİSNA: qismən unikal indeks. Tam `UNIQUE (tenant_id,
-- employee_id)` işləməzdi — keçmiş (EXPIRED/REVOKED) sətirlər saxlanılır və
-- ikinci istisnanı bloklayardı. Qismən indeks tam olaraq lazım olan qaydanı
-- ifadə edir: "eyni anda iki aktiv istisna olmasın" — əks halda biri ləğv
-- edilər, digəri sükutla qüvvədə qalardı.
CREATE UNIQUE INDEX IF NOT EXISTS ux_face_exemption_active
    ON face_control_exemptions (tenant_id, employee_id)
    WHERE status = 'ACTIVE';

-- Gecəlik «müddəti bitənləri EXPIRED et» işi üçün.
CREATE INDEX IF NOT EXISTS idx_face_exemption_expiry
    ON face_control_exemptions (tenant_id, expires_at)
    WHERE status = 'ACTIVE';

DROP TRIGGER IF EXISTS trg_face_exemptions_updated ON face_control_exemptions;
CREATE TRIGGER trg_face_exemptions_updated BEFORE UPDATE ON face_control_exemptions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE face_control_exemptions IS
    'Face Control-dan PIN-only istisnası (facecontrol.md bənd 14) — tibbi/'
    'fiziki səbəblə üz təsdiqindən azad edilən işçilər. YALNIZ Root/CEO təyin '
    'edə bilər (`can_manage_face_exemptions`, hardlock səviyyə 2). İstisna '
    'MÜVƏQQƏTİDİR: `expires_at` məcburidir və maksimum ömrü '
    '`FACE_EXEMPTION_MAX_DAYS` ilə məhdudlaşır. Kompensasiya edici nəzarət '
    '(istisnalı işçinin hər təsdiqinin MƏCBURİ dual-control axınına düşməsi) '
    'tətbiq qatındadır — bu cədvəl həmin qaydanın mənbəyidir.';
COMMENT ON COLUMN face_control_exemptions.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN face_control_exemptions.tenant_id IS
    'Kirayəçi izolyasiyası — RLS `tenant_isolation` siyasətinin açarı.';
COMMENT ON COLUMN face_control_exemptions.employee_id IS
    'İstisnadan yararlanan işçi. Eyni anda YALNIZ BİR aktiv sətir ola bilər '
    '(`ux_face_exemption_active`).';
COMMENT ON COLUMN face_control_exemptions.granted_by IS
    'İstisnanı verən Root/CEO. `ON DELETE NO ACTION` — "kim icazə verdi?" '
    'sualı istisnadan uzun yaşayır və yetim qala bilməz.';
COMMENT ON COLUMN face_control_exemptions.reason IS
    'İstisnanın səbəbi (Azərbaycanca, ən azı 10 simvol). Boş/absurd səbəb '
    'qəbul edilmir: istisnanın özü bir aldatma yoluna çevrilə bilər və '
    'sənədləşməmiş boşluq müdafiə oluna bilməz.';
COMMENT ON COLUMN face_control_exemptions.granted_at IS 'Təyinat anı (tz-aware).';
COMMENT ON COLUMN face_control_exemptions.expires_at IS
    'İstisnanın avtomatik bitmə anı (tz-aware). MƏCBURİDİR — `NULL` icazə '
    'verilsəydi «müvəqqəti» istisna sükutla əbədi qalardı. Gecəlik iş bu '
    'tarixi keçmiş sətirləri `EXPIRED`-ə keçirir.';
COMMENT ON COLUMN face_control_exemptions.status IS
    'ACTIVE → EXPIRED (avtomatik, vaxt keçib) / REVOKED (insan qərarı ilə '
    'ləğv). Sətir heç vaxt SİLİNMİR: "həmin gün bu işçi niyə üz təsdiqindən '
    'keçmirdi?" sualının yeganə struktur cavabıdır.';
COMMENT ON COLUMN face_control_exemptions.revoked_by IS
    'İstisnanı vaxtından əvvəl ləğv edən şəxs (yalnız `REVOKED` statusunda).';
COMMENT ON COLUMN face_control_exemptions.revoked_at IS 'Ləğv anı (tz-aware).';
COMMENT ON COLUMN face_control_exemptions.revoke_reason IS
    'Ləğvin əsası — "niyə vaxtından əvvəl bitirildi?".';
COMMENT ON COLUMN face_control_exemptions.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN face_control_exemptions.updated_at IS
    'Sonuncu dəyişiklik anı — `set_updated_at()` trigger-i doldurur.';

-- ---------------------------------------------------------------------------
-- 5. `face_control_store_scope` — MAĞAZA-SƏVİYYƏLİ AKTİVLİK (bənd 15)
-- ---------------------------------------------------------------------------
-- BOŞ = QLOBAL TOGGLE-A TABE (indiki davranış DƏYİŞMİR). Bir və ya bir neçə
-- AKTİV sətir varsa — Face Control YALNIZ həmin mağazalarda tətbiq olunur.
-- Bu, pilot-mərhələli yayımın bütün mənasıdır: bir mağazada sınamaq üçün
-- qlobal modulu söndürüb-yandırmaq lazım deyil.
CREATE TABLE IF NOT EXISTS face_control_store_scope (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,
    -- CASCADE: mağaza qeydi silinərsə əhatə sətrinin mənası qalmır
    -- (`announcement_targets.store_id` ilə eyni qərar). Mağazalar praktikada
    -- soft delete edilir (`stores.is_active`), ona görə bu yol nadirdir.
    store_id       UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,

    -- SET NULL: seçimi edən Root sistemdən çıxsa da əhatə qeydi qalmalıdır.
    added_by       UUID REFERENCES employees(id) ON DELETE SET NULL,

    -- SOFT DELETE — ƏSASLANDIRMA: sətri fiziki silmək "bu mağazada Face
    -- Control 3 ay işlədi, sonra söndürüldü" faktını izsiz yox edərdi. Həmin
    -- fakt isə keçmiş MISMATCH kilidlərinin qanuni olub-olmadığını izah edən
    -- yeganə mənbədir (`catalogs.py` soft delete qaydası).
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at TIMESTAMPTZ,
    deactivated_by UUID REFERENCES employees(id) ON DELETE SET NULL,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Bir mağaza üçün bir sətir; yenidən əlavə etmə UPSERT-dir (sətir
    -- `is_active = TRUE`-ya qaytarılır), ikinci sətir yaratmır.
    UNIQUE (tenant_id, store_id),
    CONSTRAINT chk_face_scope_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_face_store_scope_updated ON face_control_store_scope;
CREATE TRIGGER trg_face_store_scope_updated BEFORE UPDATE ON face_control_store_scope
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE face_control_store_scope IS
    'Face Control-un AKTİV olduğu mağazalar (facecontrol.md bənd 15). '
    'AKTİV sətir YOXDURSA (defolt) modul qlobal Feature Toggle-a tabe olur — '
    'yəni bu cədvəl boş qalarsa indiki davranış heç cür dəyişmir. Qlobal '
    'toggle mexanizminə (`feature_toggles`) TOXUNULMUR; bu, onun üstündə '
    'yalnız DARALDICI süzgəcdir. Vergüllü `system_limits` siyahısı əvəzinə '
    'uşaq cədvəl seçildi (`announcement_targets` naxışı): mətn siyahısında '
    'səhv yazılmış ID Face Control-u həmin mağazada SÜKUTLA söndürərdi.';
COMMENT ON COLUMN face_control_store_scope.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN face_control_store_scope.tenant_id IS
    'Kirayəçi izolyasiyası — RLS `tenant_isolation` siyasətinin açarı.';
COMMENT ON COLUMN face_control_store_scope.store_id IS
    'Face Control-un aktiv olduğu mağaza. Real `FOREIGN KEY` — silinmiş və ya '
    'başqa kirayəçiyə aid ID buraya düşə bilmir.';
COMMENT ON COLUMN face_control_store_scope.added_by IS
    'Mağazanı pilot əhatəsinə salan Root. İşçi qeydi silinsə `NULL` olur.';
COMMENT ON COLUMN face_control_store_scope.is_active IS
    'Soft delete: FALSE = mağaza əhatədən ÇIXARILIB. Sətir SİLİNMİR — keçmiş '
    'kilid/uyğunsuzluq qeydlərinin hansı dövrdə yarandığını izah edir.';
COMMENT ON COLUMN face_control_store_scope.deactivated_at IS
    'Əhatədən çıxarılma anı (tz-aware).';
COMMENT ON COLUMN face_control_store_scope.deactivated_by IS
    'Mağazanı əhatədən çıxaran şəxs.';
COMMENT ON COLUMN face_control_store_scope.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN face_control_store_scope.updated_at IS
    'Sonuncu dəyişiklik anı — trigger doldurur.';

-- ---------------------------------------------------------------------------
-- 6. RLS — YENİ CƏDVƏLLƏR DƏ FAIL-CLOSED (SEC-008)
-- ---------------------------------------------------------------------------
-- `app.tenant_id` təyin edilməyibsə tətbiq rolu HEÇ BİR sətir görmür.
-- Biometrik cədvəllərdə bu, adi izolyasiyadan daha vacibdir: bir kirayəçinin
-- üz vektorlarına başqa kirayəçinin sorğusu heç bir halda çatmamalıdır.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'face_embedding_history', 'face_verification_log',
        'face_control_exemptions', 'face_control_store_scope'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I
                 USING (tenant_id = current_tenant_id())
                 WITH CHECK (tenant_id = current_tenant_id())', t
        );
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 7. GRANT / REVOKE — TƏTBİQ ROLU
-- ---------------------------------------------------------------------------
-- ⚠️ AÇIQ `REVOKE` MƏCBURİDİR: `schema.sql` §28 `ALTER DEFAULT PRIVILEGES ...
-- GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kompasos_app` icra edir,
-- yəni BUNDAN SONRA yaradılan HƏR cədvəl `DELETE`-i AVTOMATİK alır. Dar
-- `GRANT` tək başına heç nə məhdudlaşdırmır (ətraflı izah migrations/018).
--
-- CƏDVƏL-CƏDVƏL QƏRAR:
--   * `face_embedding_history` — `DELETE` YOX. Arxiv sətri "bu işçinin üzü
--     dəyişdirildi" faktının sübutudur. Biometrik məzmunun silinməsi
--     `UPDATE` ilə edilir (`status = 'PURGED'`, vektor `NULL`) — yəni
--     məlumat gedir, İZ qalır. Fiziki `DELETE` hər ikisini aparardı.
--   * `face_verification_log` — `DELETE` VAR, `UPDATE` YOX. Bu, qəsdli
--     asimmetriyadır: jurnal sətri FAKTdır və redaktə edilməməlidir (biri
--     MISMATCH-i sonradan SUCCESS-ə çevirə bilərdi), lakin bənd 17 saxlama
--     müddətindən köhnə sətirlərin TAM SİLİNMƏSİNİ açıq şəkildə tələb edir
--     və həmin gecəlik iş məhz bu rolla işləyir.
--   * `face_control_exemptions` — `DELETE` YOX. EXPIRED/REVOKED sətir
--     keçmişin izahıdır; silinsə, "o gün niyə üz təsdiqi olmadı?" sualı
--     cavabsız qalardı.
--   * `face_control_store_scope` — `DELETE` YOX (soft delete qaydası).
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON face_embedding_history, '
            'face_control_exemptions, face_control_store_scope TO %I', v_role
        );
        EXECUTE format(
            'REVOKE DELETE ON face_embedding_history, face_control_exemptions, '
            'face_control_store_scope FROM %I', v_role
        );
        EXECUTE format(
            'GRANT SELECT, INSERT, DELETE ON face_verification_log TO %I', v_role
        );
        EXECUTE format('REVOKE UPDATE ON face_verification_log FROM %I', v_role);
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 8. İCAZƏ FLAG-İ — `can_manage_face_exemptions` (bənd 14)
-- ---------------------------------------------------------------------------
-- `ON CONFLICT (code) DO NOTHING`: təkrar icrada Root-un redaktə etdiyi
-- `name_az`/`description_az` ÜSTÜNDƏN YAZILMIR (017/018/021 ilə eyni qayda).
--
-- `is_anti_fraud = FALSE`: CLAUDE.md §5-dəki dörd anti-fraud flag-inin
-- siyahısında deyil — həmin siyahı HARDCODED-dir və genişləndirilmir.
-- Qorunma başqa yoldan gəlir: `hardlock_level = 2` onsuz da Mağaza
-- Meneceri/Satıcı da daxil olmaqla Root/CEO-dan başqa HƏR rolu kənarda
-- saxlayır — yəni anti-fraud siyahısına əlavə etmək heç nə dəyişməzdi.
-- `is_camera_only = FALSE` / `excludes_camera_role = FALSE`: SEC-001 yalnız
-- `can_approve_dual_control_override`-a aiddir, bu flag o deyil.
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level, is_anti_fraud, is_camera_only)
VALUES
    ('can_manage_face_exemptions', 'HR',
        'Üz təsdiqi istisnalarını idarə et',
        'facecontrol.md bənd 14 — işçini Face Control-dan azad edən müvəqqəti '
        'PIN-only istisnasını təyin/uzatma/ləğv etmək. YALNIZ Root/CEO '
        '(hardlock səviyyə 2): mövcud `can_manage_employees` KİFAYƏT ETMİR, '
        'çünki onun hardlock səviyyəsi 0-dır və adi HR-səviyyəli admin-ə '
        'həvalə edilə bilər. İstisna üz təsdiqi qatını söndürür, yəni özü bir '
        'aldatma yoluna çevrilə bilər — ona görə səlahiyyət yuxarı qaldırılır.',
        2, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- DEFOLT SAHİBLİK — YALNIZ ROOT VƏ CEO.
-- `granted_by` QƏSDƏN yazılmır (NULL qalır): `enforce_grantor_owns_flag()`
-- (schema.sql §18) və `enforce_position_flag_hierarchy()` (migrations/046)
-- "sistem seed-i" halını məhz aktorun yoxluğu ilə tanıyır — seed anında
-- flag-i "verən" real işçi mövcud deyil.
--
-- `WHERE p.code IN ('ROOT', 'CEO')` TENANT FİLTRSİZDİR (021 ilə eyni
-- əsaslandırma): həm sistem şablonu (`tenant_id IS NULL`), həm də ARTIQ
-- mövcud kirayəçilərin rol sətirləri əhatə olunur.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_face_exemptions', TRUE
FROM positions p
WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

-- HR_Admin, Admin, Mağaza Meneceri, Kamera Nəzarətçisi və Satıcı üçün HEÇ BİR
-- sətir yazılmır — `enforce_permission_hardlock()` onsuz da səviyyə 2-ni
-- bloklayardı, lakin cəhdin özü də edilmir ki, sxem oxunanda qayda aydın olsun.

-- ---------------------------------------------------------------------------
-- 9. İSTİSNA MOTORUNA YENİ MƏNBƏ — `FACE_MISMATCH` (bənd 16)
-- ---------------------------------------------------------------------------
-- Motorun KODU DƏYİŞMİR: `exception_sources` bazadan idarə olunan kataloqdur
-- (migrations/018) və yeni mənbə bir `INSERT`-dir. `tenant_id = NULL` =
-- sistem mənbəyi, bütün kirayəçilər görür (`positions` naxışı).
INSERT INTO exception_sources (code, tenant_id, name_az, description_az, default_severity)
VALUES ('FACE_MISMATCH', NULL, 'Üz uyğunsuzluğu',
        'Kioskda PIN daxil edən şəxsin üzü həmin PIN-in sahibinin qeydiyyatlı '
        'üzü ilə uyğun gəlmədikdə yaranır (facecontrol.md bənd 3). Ciddiyyət '
        'CRITICAL-dır: davranış anomaliyasından fərqli olaraq bu, statistik '
        'kənarlaşma deyil, kimlik uyğunsuzluğudur. İstisna qeydi mövcud '
        'DƏRHAL-BİLDİRİŞ kanalını ƏVƏZ ETMİR, ona ƏLAVƏ olunur.',
        'CRITICAL')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 10. ON ROOT PARAMETRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (039–045 ilə eyni qayda).
--
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ....................................................
-- FACE_ENROLLMENT_MIN_QUALITY (DECIMAL, 0.50)
--   * min = 0.10 — bundan aşağı hədd keyfiyyət yoxlamasını faktiki olaraq
--     söndürərdi (hər kadr keçərdi) və bənd 1-in «[Yenidən Çək]» təklifi heç
--     vaxt görünməzdi.
--   * max = 0.95 — mağaza veb-kamerası ilə 0.95-dən yuxarı bal praktikada
--     alınmır; belə hədd enrollment-i tamamilə mümkünsüz edərdi, yəni yeni
--     işçi sistemə heç cür daxil ola bilməzdi.
-- FACE_ENROLLMENT_FRAME_COUNT (INTEGER, 5)
--   * NİYƏ ROOT PARAMETRİDİR: bənd 11 çox-kadr ortalamasını tələb edir, lakin
--     kadrın SAYINI təyin etmir — o, keyfiyyət ilə vaxt arasındakı mübadilədir
--     və avadanlıqdan asılıdır. Sabit ədəd zəif kamerada azlıq, güclü kamerada
--     isə lazımsız gözləmə yaradardı.
--   * min = 3 — ikidən az kadrın "ortası" tək-kadr xətasını praktikada
--     saxlayır, yəni bənd 11-in bütün mənası itərdi. Üç kadr bir rədd
--     ediləndən sonra da iki keçən kadr saxlayır.
--   * max = 15 — daha çoxu kioskda insanı gözlədir və qeydiyyatı praktikada
--     tərk edilən prosedura çevirir (operator "sonra edərəm" deyir).
--   * KRİTİK QAYDA (bənd 18): bu ədəd performans xəbərdarlığına görə AVTOMATİK
--     azaldılmır — sürət problemi hardware ilə həll olunur, keyfiyyət
--     parametrini endirmək təhlükəsizlik güzəştidir.
-- FACE_MISMATCH_LOCKOUT_THRESHOLD (INTEGER, 3)
--   * min = 1 — bir uyğunsuzluqdan dərhal kilid AÇIQ seçim olmalıdır (ən sərt
--     rejim); 0 isə "hər cəhd kilidlə bitsin" mənasına gələrdi, absurddur.
--   * max = 10 — PIN həddi (5) ilə eyni tərtibdə tavan. Daha böyük dəyər
--     kilidi sükutla söndürərdi, halbuki söndürmənin açıq yolu modulun öz
--     Feature Toggle-ıdır.
-- FACE_MATCH_TOLERANCE / FACE_LOW_CONFIDENCE_TOLERANCE (DECIMAL, 0.60 / 0.50)
--   * min = 0.20 / 0.15 — bundan sərt hədd EYNİ adamı da rədd edir (fərqli
--     işıq/açı) və sistem hər gün yalançı MISMATCH verərdi — yəni ən güclü
--     siqnal etibarını itirərdi.
--   * max = 0.99 / 0.98 — 1.0-a yaxın tolerantlıq praktikada HƏR üzü qəbul
--     edir, yəni qorumanı sükutla söndürərdi.
--   * ƏLAQƏ QAYDASI: aşağı-etibar həddi bənzərlik həddindən BÖYÜK olmamalıdır
--     (əks halda «aşağı-etibarlı» zolaq tərsinə çevrilər). Bu, iki AYRI sətir
--     olduğu üçün `CHECK` ilə ifadə edilə bilmir — yoxlama tətbiq qatındadır
--     (Faza 2) və ROOT ekranı tərs dəyəri qəbul etməməlidir.
-- FACE_REENROLLMENT_REMINDER_MONTHS (INTEGER, 12)
--   * min = 1 — aylıq xatırlatma sərt, lakin qanuni seçimdir.
--   * max = 60 — 5 ildən sonra xatırlatma praktiki olaraq "heç vaxt"dır;
--     söndürmək istəyən Root bu tavana qoyur, bu, AÇIQ seçimdir.
-- FACE_EXEMPTION_MAX_DAYS (INTEGER, 90)
--   * min = 1 — bir günlük istisna qanunidir (bir günlük tibbi hal).
--   * max = 365 — bir ildən uzun istisna artıq «müvəqqəti» deyil; bənd 14-ün
--     bütün mənası istisnanın yenidən əsaslandırılmasını məcbur etməkdir.
-- FACE_VERIFICATION_LOG_RETENTION_MONTHS (INTEGER, 12)
--   * min = 1 — daha qısa saxlama hüquqi baxımdan mümkündür, lakin 0 «dərhal
--     sil» deməkdir və auditi tamamilə yox edərdi.
--   * max = 60 — 5 il. TƏHLÜKƏSİZLİK TƏSDİQİ: 12 aylıq defolt mövcud Davranış
--     Anomaliyası baseline hesablamasını (yalnız son 30 gün) POZMUR — aralıq
--     qat-qat genişdir, konflikt yoxdur.
-- FACE_VERIFICATION_MAX_SECONDS (INTEGER, 5)
--   * min = 1 — 0 saniyə hər doğrulamanı «yavaş» elan edərdi.
--   * max = 60 — bir dəqiqədən uzun gözləmə kioskda onsuz da istifadəyə
--     yararsızdır; tavan yalnız yazı səhvini kəsir.
-- FACE_LIVENESS_ACTIONS (TEXT, vergüllü siyahı)
--   * `min_value`/`max_value` YOXDUR — dəyər ədəd deyil, kataloqdur
--     (`EXECUTIVE_DIGEST_METRIC_CATALOG` ilə eyni naxış). Bir hərəkəti
--     söndürmək onu siyahıdan çıxarmaqdır; siyahının BOŞ qalması isə liveness
--     qorumasını söndürər, ona görə tətbiq qatı boş siyahını rədd edir.
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('FACE_ENROLLMENT_MIN_QUALITY', '0.50', 'DECIMAL', '0.10', '0.95',
     'Üz qeydiyyatında kadrın qəbul edilməsi üçün minimum keyfiyyət balı '
     '(0–1: aydınlıq/işıqlandırma). Kadrlar bu həddi keçmirsə operatora '
     '«Yenidən Çək» təklif olunur. İLKİN DƏYƏRDİR — pilot mağazanın real '
     'işıq şəraitində ölçülüb tənzimlənməlidir'),
    ('FACE_ENROLLMENT_FRAME_COUNT', '5', 'INTEGER', '3', '15',
     'Üz qeydiyyatında çəkilən kadr sayı. Kadrların embedding-lərinin RİYAZİ '
     'ORTASI tək istinad vektoru kimi saxlanılır (bənd 11) — tək kadr '
     'təsadüfi işıq/açı xətasını istinad nöqtəsinə çevirərdi. İLKİN DƏYƏRDİR: '
     'doğru say kameradan asılıdır və pilot mağazada tənzimlənməlidir. Bu '
     'parametr performans xəbərdarlığına görə AVTOMATİK AZALDILMIR — sürət '
     'problemi hardware ilə həll olunur'),
    ('FACE_MISMATCH_LOCKOUT_THRESHOLD', '3', 'INTEGER', '1', '10',
     'Ardıcıl neçə üz-uyğunsuzluğundan sonra hesab kilidlənir. PIN-in öz '
     'həddindən (`PIN_MAX_FAILED_ATTEMPTS` = 5) AYRIDIR və qəsdən daha '
     'aşağıdır: üz uyğunsuzluğu unudulmuş rəqəm deyil, kimlik siqnalıdır. '
     'Kilidin MÜDDƏTİ yeni parametr deyil — mövcud `PIN_LOCKOUT_MINUTES` '
     'işlədilir, çünki mexanizm təkrar yazılmır'),
    ('FACE_LIVENESS_ACTIONS', 'BLINK,HEAD_TURN,SMILE', 'TEXT', NULL, NULL,
     'Hər doğrulamada TƏSADÜFİ seçilən aktiv liveness hərəkətlərinin vergüllü '
     'kataloqu: BLINK (göz qırpma), HEAD_TURN (baş çevirmə), SMILE '
     '(gülümsəmə). Bir hərəkəti söndürmək üçün onu siyahıdan çıxarmaq '
     'kifayətdir; siyahı BOŞ qala bilməz, çünki bu, liveness qorumasını '
     'tamamilə söndürərdi'),
    ('FACE_MATCH_TOLERANCE', '0.60', 'DECIMAL', '0.20', '0.99',
     'Üz bənzərlik həddi — kitabxananın MƏSAFƏ vahidindədir (kiçik = daha '
     'oxşar). Bu qiymətdən BÖYÜK məsafə MISMATCH sayılır. İLKİN DƏYƏR '
     'kitabxananın sənədləşdirilmiş defoltudur (0.6) və pilot mağazada real '
     'şəraitdə tənzimlənməlidir — «düzgün» ədəd empirik qərardır'),
    ('FACE_LOW_CONFIDENCE_TOLERANCE', '0.50', 'DECIMAL', '0.15', '0.98',
     'Tam-etibarlı uyğunluğun sərhədi (məsafə vahidi). Bu qiymətdən kiçik '
     'məsafə tam təsdiqdir; bu qiymətlə `FACE_MATCH_TOLERANCE` arasındakı '
     'zolaq isə «aşağı-etibarlı təsdiq»dir — əməliyyata icazə verilir, lakin '
     'qeyd nişanlanır ki, Kamera Operatoru öz yoxlamasında daha diqqətli '
     'olsun. Dəyər bənzərlik həddindən BÖYÜK ola bilməz'),
    ('FACE_REENROLLMENT_REMINDER_MONTHS', '12', 'INTEGER', '1', '60',
     'Üz qeydiyyatının «köhnəlmiş» sayılması üçün ay sayı. Bu müddət keçəndə '
     'admin panelində tövsiyə xəbərdarlığı görünür (insan üzü zamanla dəyişir: '
     'saqqal, eynək, yaş). MƏCBURİ BLOKLAMA YARATMIR — işçi normal işləməyə '
     'davam edir'),
    ('FACE_EXEMPTION_MAX_DAYS', '90', 'INTEGER', '1', '365',
     'Face Control istisnasının maksimum müddəti (gün). Bu müddət bitdikdə '
     'istisna avtomatik ləğv olunur və yenidən əsaslandırılmalı olur — istisna '
     'sükutla əbədi qalmamalıdır, çünki o, üz təsdiqi qatını söndürür'),
    ('FACE_VERIFICATION_LOG_RETENTION_MONTHS', '12', 'INTEGER', '1', '60',
     'Üz-doğrulama jurnalının saxlanma müddəti (ay). Bundan köhnə sətirlər '
     'gecəlik işlə TAM SİLİNİR (anonimləşdirmə lazım deyil — jurnalda foto və '
     'vektor yoxdur). 12 ay mövcud Davranış Anomaliyası baseline aralığından '
     '(son 30 gün) qat-qat genişdir, konflikt yaratmır'),
    ('FACE_VERIFICATION_MAX_SECONDS', '5', 'INTEGER', '1', '60',
     'Gözlənilən maksimum doğrulama vaxtı (saniyə). Aşılarsa System Health '
     'Monitor-a performans xəbərdarlığı yazılır (kiosk PC-nin gücü kifayət '
     'edirmi?). Bu monitorinq HEÇ VAXT keyfiyyət parametrlərini avtomatik '
     'zəiflətmir — həll yolu hardware/kod optimallaşdırmasıdır')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 11. ON ROOT PARAMETRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039–045-dəki naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_face_control_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'FACE_ENROLLMENT_MIN_QUALITY', '0.50', 'DECIMAL', '0.10', '0.95',
         'Üz qeydiyyatı üçün minimum kadr keyfiyyəti'),
        (NEW.tenant_id, 'FACE_ENROLLMENT_FRAME_COUNT', '5', 'INTEGER', '3', '15',
         'Üz qeydiyyatında çəkilən kadr sayı (orta vektor üçün)'),
        (NEW.tenant_id, 'FACE_MISMATCH_LOCKOUT_THRESHOLD', '3', 'INTEGER', '1', '10',
         'Ardıcıl üz uyğunsuzluğu həddi (PIN həddindən ayrı)'),
        (NEW.tenant_id, 'FACE_LIVENESS_ACTIONS', 'BLINK,HEAD_TURN,SMILE', 'TEXT', NULL, NULL,
         'Aktiv liveness hərəkətlərinin kataloqu'),
        (NEW.tenant_id, 'FACE_MATCH_TOLERANCE', '0.60', 'DECIMAL', '0.20', '0.99',
         'Üz bənzərlik həddi (məsafə vahidi)'),
        (NEW.tenant_id, 'FACE_LOW_CONFIDENCE_TOLERANCE', '0.50', 'DECIMAL', '0.15', '0.98',
         'Tam etibarlı uyğunluğun sərhədi (məsafə vahidi)'),
        (NEW.tenant_id, 'FACE_REENROLLMENT_REMINDER_MONTHS', '12', 'INTEGER', '1', '60',
         'Yenidən qeydiyyat tövsiyəsinin intervalı (ay)'),
        (NEW.tenant_id, 'FACE_EXEMPTION_MAX_DAYS', '90', 'INTEGER', '1', '365',
         'Face Control istisnasının maksimum müddəti (gün)'),
        (NEW.tenant_id, 'FACE_VERIFICATION_LOG_RETENTION_MONTHS', '12', 'INTEGER', '1', '60',
         'Doğrulama jurnalının saxlanma müddəti (ay)'),
        (NEW.tenant_id, 'FACE_VERIFICATION_MAX_SECONDS', '5', 'INTEGER', '1', '60',
         'Gözlənilən maksimum doğrulama vaxtı (saniyə)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_face_control_limits_for_new_tenant() IS
    'Yeni kirayəçiyə Face Control-un on ROOT parametrini əlavə edir '
    '(migrations/047). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_face_control_limits ON license_tenants;
CREATE TRIGGER trg_seed_face_control_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_face_control_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- ⚠️ İTKİ XƏBƏRDARLIĞI — BU GERİ QAYTARMA BƏRPA EDİLƏ BİLMƏYƏN MƏLUMAT SİLİR:
--
--   * `employees.face_embedding` sütununun düşürülməsi BÜTÜN üz qeydiyyatlarını
--     məhv edir. Vektor heç bir yerdən yenidən hesablana bilməz (foto
--     saxlanmır!) — hər işçi FİZİKİ olaraq kioska gəlib yenidən qeydiyyatdan
--     keçməlidir. 235 işçilik şəbəkədə bu, günlərlə iş deməkdir.
--   * `face_verification_log` uyğunsuzluq hadisələrinin YEGANƏ izidir; onunla
--     birlikdə "bu kilid niyə baş verdi?" sualının cavabı da gedir.
--   * `face_control_exemptions` silinsə, keçmiş girişlərin niyə üz təsdiqindən
--     keçmədiyi izah edilə bilməz.
--   * `face_embedding_history` "bu işçinin üzü neçə dəfə dəyişdirildi?"
--     sualının yeganə mənbəyidir — tez-tez yenidən qeydiyyat aldatma
--     əlamətidir və bu iz auditdə lazım ola bilər.
--
-- YALNIZ `system_limits` sətirləri silinsə, sistem İŞLƏMƏYƏ DAVAM EDİR: kod
-- `DEFAULT_LIMITS` fallback-larına düşür (0.50 / 5 / 3 / BLINK,HEAD_TURN,SMILE
-- / 0.60 / 0.50 / 12 / 90 / 12 / 5). İtən yeganə şey Root-un GUI-dan
-- dəyişdirmə imkanıdır.
--
-- `exception_sources` sətri SİLİNMƏMƏLİDİR, əgər ona istinad edən `exceptions`
-- sətirləri varsa: FK `ON DELETE NO ACTION`-dır və silmə xəta verər. Doğru yol
-- `is_active = FALSE` ilə söndürməkdir (018-in soft delete qaydası).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_face_control_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_face_control_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'FACE_ENROLLMENT_MIN_QUALITY', 'FACE_ENROLLMENT_FRAME_COUNT',
--       'FACE_MISMATCH_LOCKOUT_THRESHOLD',
--       'FACE_LIVENESS_ACTIONS', 'FACE_MATCH_TOLERANCE',
--       'FACE_LOW_CONFIDENCE_TOLERANCE', 'FACE_REENROLLMENT_REMINDER_MONTHS',
--       'FACE_EXEMPTION_MAX_DAYS', 'FACE_VERIFICATION_LOG_RETENTION_MONTHS',
--       'FACE_VERIFICATION_MAX_SECONDS');
--   DELETE FROM position_permissions WHERE flag_code = 'can_manage_face_exemptions';
--   DELETE FROM permission_flags     WHERE code      = 'can_manage_face_exemptions';
--   UPDATE exception_sources SET is_active = FALSE, deactivated_at = now()
--    WHERE code = 'FACE_MISMATCH';
--   DROP TABLE IF EXISTS face_control_store_scope;
--   DROP TABLE IF EXISTS face_control_exemptions;
--   DROP TABLE IF EXISTS face_verification_log;
--   DROP TABLE IF EXISTS face_embedding_history;
--   DROP INDEX IF EXISTS idx_employees_face_enrolled;
--   ALTER TABLE employees DROP CONSTRAINT IF EXISTS chk_employee_face_enrollment_pair;
--   ALTER TABLE employees DROP CONSTRAINT IF EXISTS chk_employee_face_mismatch_attempts;
--   ALTER TABLE employees
--       DROP COLUMN IF EXISTS face_locked_until,
--       DROP COLUMN IF EXISTS face_mismatch_attempts,
--       DROP COLUMN IF EXISTS face_enrolled_at,
--       DROP COLUMN IF EXISTS face_embedding;
-- COMMIT;
