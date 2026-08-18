-- ===========================================================================
-- 068 — İKİ-KANALLI DƏSTƏK + TELEGRAM KONFİQURASİYASI (CHAT-1)
-- ===========================================================================
-- Tarix : 2026-08-18
-- Səbəb : Dəstək chat-i TƏK ünvanlı idi — hər mesaj hazırlayıcıya gedirdi.
--         Halbuki işçinin iki tamamilə fərqli sualı olur:
--
--             «növbəm səhv yazılıb»      → ŞİRKƏTİN öz CEO/HR-ının işidir;
--             «proqram açılmır»          → HAZIRLAYICININ işidir.
--
--         Birincini hazırlayıcıya göndərmək iki zərər verir: şirkətin daxili
--         məsələsi kənar tərəfə düşür (məxfilik), və hazırlayıcının növbəsi
--         onun həll edə BİLMƏYƏCƏYİ mesajlarla dolur.
--
-- ---------------------------------------------------------------------------
-- KANAL SÜTUNUNUN DEFOLTU `TECHNICAL`-DIR — NİYƏ
-- ---------------------------------------------------------------------------
-- Mövcud sətirlərin HAMISI hazırlayıcıya yazılmış mesajlardır (başqa yol yox
-- idi). `INTERNAL` defolt seçsəydik, köhnə ticket-lər bir gecədə şirkətin
-- daxili növbəsinə köçər və hazırlayıcı onları GÖRMƏZ olardı — yəni cavabsız
-- qalan mesajlar sükutla itərdi.
--
-- ---------------------------------------------------------------------------
-- TELEGRAM: TOKEN ŞİFRƏLİ, CHAT ID AÇIQ
-- ---------------------------------------------------------------------------
-- Bot token-i botun ÖZÜNÜ idarə etmək hüququdur — oğurlanarsa yad adam
-- şirkətin adından mesaj göndərə bilər. Ona görə o, `connection.json`-dakı
-- parol ilə eyni mexanizmlə (AES-256-GCM + DPAPI) şifrələnir və sütun adı
-- bunu AÇIQ deyir. `chat_id` isə sirr deyil: o, yalnız «hansı söhbətə» sualının
-- cavabıdır və tokensiz heç nə açmır.
--
-- ---------------------------------------------------------------------------
-- `#msg_XXXX` — NİYƏ AYRICA QISA İSTİNAD, UUID DEYİL
-- ---------------------------------------------------------------------------
-- Telegram-da cavab (`reply`) mesajın MƏTNİNDƏKİ istinada görə tapılır.
-- 36 simvolluq UUID mesajın yarısını tutar və insan gözü ilə oxunmur.
-- `telegram_ref` isə qısa, artan və kirayəçi daxilində unikaldır.
--
-- `telegram_message_id` isə Telegram-ın ÖZ nömrəsidir: reply gələndə bot
-- əvvəlcə ona baxır (dəqiq uyğunluq), mətn istinadı isə ehtiyat yoldur —
-- istifadəçi köhnə mesajı əl ilə kopyalayıb yaza bilər.
-- ===========================================================================

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 0. STATUS DƏYƏRİ — TRANZAKSİYADAN KƏNARDA
-- ---------------------------------------------------------------------------
-- `ALTER TYPE ... ADD VALUE` əlavə edilmiş dəyəri EYNİ tranzaksiyada işlətməyə
-- imkan vermir. Aşağıdakı `BEGIN;` blokunda `'RESOLVED'` sətir kimi yazılmır
-- (defolt `'OPEN'` qalır), lakin qayda gələcək redaktədə asanlıqla pozula
-- bilər — ona görə əmr blokdan KƏNARDA saxlanılır və icraçı `autocommit=True`
-- ilə işlədiyi üçün öz tranzaksiyasında tətbiq olunur
-- (`scripts/apply_migrations.py`).
--
-- «Həll olundu» statusu niyə lazımdır: `CLOSED` işi DƏRHAL arxivə atır və
-- işçinin «problem davam edir» demək imkanını kəsir. `RESOLVED` isə etiraz
-- pəncərəsi saxlayır — bu müddət Root parametridir (aşağıda).
ALTER TYPE ticket_status ADD VALUE IF NOT EXISTS 'RESOLVED';

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. KANAL TİPİ VƏ SÜTUNU
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regtype('support_channel') IS NULL THEN
        CREATE TYPE support_channel AS ENUM ('INTERNAL', 'TECHNICAL');
    END IF;
END
$$;

ALTER TABLE support_tickets
    ADD COLUMN IF NOT EXISTS channel support_channel NOT NULL DEFAULT 'TECHNICAL';

COMMENT ON COLUMN support_tickets.channel IS
    'INTERNAL = şirkətin öz CEO/Admin/HR-ına; TECHNICAL = hazırlayıcıya '
    '(+ Telegram). Defolt TECHNICAL — köhnə sətirlər məhz o kanaldandır '
    '(migrations/068).';

-- Növbə ekranı «kanal + status» üzrə süzür; indeks olmadan hər açılışda tam
-- skan gedərdi.
CREATE INDEX IF NOT EXISTS idx_support_tickets_channel
    ON support_tickets (tenant_id, channel, status, updated_at DESC);

-- ---------------------------------------------------------------------------
-- 1b. TƏCİLİLİK — «YALNIZ TƏCİLİ» Telegram rejiminin YEGANƏ girişi
-- ---------------------------------------------------------------------------
-- Faza 7 Root-a üç rejim verir: HAMISI / YALNIZ TƏCİLİ / DEAKTİV. Orta rejimin
-- işləməsi üçün «təcili»nin MAŞINLA oxunan tərifi lazımdır.
--
-- AÇAR SÖZ ANALİZİ RƏDD EDİLDİ: «yanır», «təcili», «kritik» kimi siyahı
-- Azərbaycan dilində şəkilçi ilə dəyişir («təcilidir», «təcilidi») və
-- siyahıdan kənar ifadə sükutla ADİ sayılardı — yəni işçi «MAĞAZA BAĞLIDIR»
-- yazsa da bildiriş getməzdi. Sükutla itən təcili mesaj bu rejimi
-- faydasızdan da pis edir.
--
-- Ona görə təcililik İŞÇİNİN AÇIQ seçimidir: widget-də bir işarə qutusu.
-- Sui-istifadə riski (hamı hər şeyi təcili işarələyər) qəbul edilir —
-- alternativi mesajın ümumiyyətlə çatmamasıdır.
--
-- SÖNMÜR: bir dəfə təcili olan müraciət sonrakı adi mesajla adiləşmir.
-- Səbəb — Telegram bildirişi ARTIQ getdiyi üçün geri qaytarılmır, sətrin isə
-- «təcili idi» faktını itirməsi hesabatı yalan edərdi.
ALTER TABLE support_tickets
    ADD COLUMN IF NOT EXISTS is_urgent BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN support_tickets.is_urgent IS
    'İşçinin AÇIQ təcili işarəsi. «YALNIZ TƏCİLİ» Telegram rejimi məhz buna '
    'baxır; proqramdakı bölməyə müraciət HƏR halda düşür (migrations/068).';

-- ---------------------------------------------------------------------------
-- 2. TELEGRAM İSTİNADLARI (mesaj səviyyəsində)
-- ---------------------------------------------------------------------------
ALTER TABLE support_messages
    ADD COLUMN IF NOT EXISTS telegram_ref TEXT,
    ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT,
    ADD COLUMN IF NOT EXISTS telegram_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS from_telegram BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS attachment_ref TEXT,
    ADD COLUMN IF NOT EXISTS attachment_name TEXT;

-- ŞƏKİL BAZADA SAXLANMIR — istinad saxlanılır. Səbəb `migrations/002`-dəki
-- qərarın eynisidir: sübut şəkilləri Google Drive-dadır və Postgres `bytea`
-- sütunu ehtiyat nüsxənin ölçüsünü nəzarətsiz artırardı.
--
-- `attachment_ref` `StorageReference` mətnidir (provider + bağlantı + fayl
-- ID-si bir sətirdə) — `employee_documents.file_ref` ilə EYNİ format, ona
-- görə yeni oxucu yazılmır.
--
-- `attachment_name` AYRICA saxlanılır: istinad texniki açardır və ekranda
-- göstərilə bilməz; işçi isə «hansı faylı göndərdim?» sualının cavabını
-- görməlidir.
COMMENT ON COLUMN support_messages.attachment_ref IS
    'Drive istinadı (`StorageReference` mətni) — şəkil yükləndikdən sonra '
    'fon işçisi yazır (migrations/068).';
COMMENT ON COLUMN support_messages.attachment_name IS
    'İstifadəçinin gördüyü fayl adı — istinad texniki açardır (migrations/068).';

COMMENT ON COLUMN support_messages.from_telegram IS
    'Cavab Telegram-dan REPLY ilə gəldi. `is_from_developer` ilə qarışdırma: '
    'o, MƏNBƏ tərəfi (cavablayan), bu isə GİRİŞ YOLUdur — ekran işçiyə '
    'cavabın haradan yazıldığını göstərir (migrations/068).';

COMMENT ON COLUMN support_messages.telegram_ref IS
    'Telegram mesajındakı `#msg_XXXX` istinadı — reply yönləndirməsi üçün '
    '(migrations/068).';
COMMENT ON COLUMN support_messages.telegram_message_id IS
    'Telegram-ın öz mesaj nömrəsi; reply-də ƏSAS uyğunlaşdırma açarıdır.';
COMMENT ON COLUMN support_messages.telegram_sent_at IS
    'Telegram-a göndərilmə anı. NULL = göndərilməyib (ekranda sinxronluq '
    'göstəricisi məhz buna baxır).';

CREATE UNIQUE INDEX IF NOT EXISTS idx_support_messages_telegram_ref
    ON support_messages (telegram_ref)
    WHERE telegram_ref IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_support_messages_telegram_id
    ON support_messages (telegram_message_id)
    WHERE telegram_message_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2b. CAVABLAYAN TƏRƏFİN OXUNMA VƏZİYYƏTİ
-- ---------------------------------------------------------------------------
-- 012 miqrasiyası YALNIZ `customer_last_read_at` əlavə etmişdi, çünki o vaxt
-- proqramın içində cavablayan tərəf YOX idi (hazırlayıcı ayrı paneldə
-- oxuyurdu). CHAT-1 iki gələnlər qutusunu proqramın İÇİNƏ gətirir və
-- naviqasiyadakı sayğac (Faza 6) ikinci oxunma nöqtəsi tələb edir.
--
-- Bir sütunu iki tərəf üçün paylaşmaq mümkün deyildi: CEO söhbəti açanda
-- işçinin öz nişanı da sıfırlanardı və işçi gələn cavabı GÖRMƏMİŞ oxunmuş
-- sayılardı.
ALTER TABLE support_tickets
    ADD COLUMN IF NOT EXISTS staff_last_read_at TIMESTAMPTZ;

COMMENT ON COLUMN support_tickets.staff_last_read_at IS
    'Cavablayan tərəfin (CEO/HR/Root) söhbəti son oxuduğu an — «yalnız '
    'oxunmamışlar» süzgəci buna baxır (migrations/068).';

-- ---------------------------------------------------------------------------
-- 2c. STATUS TAYMERLƏRİ
-- ---------------------------------------------------------------------------
-- İki avtomatik keçid VAXT tələb edir və hər ikisinin başlanğıc anı AYRI
-- saxlanılır:
--
--   `resolved_at`  — «Həll olundu» anı. N gündən sonra avtomatik `CLOSED`.
--   `waiting_since`— «Gözləmədə» anı. M gündən sonra işçiyə xatırlatma.
--
-- `updated_at` KİFAYƏT ETMİRDİ: o, hər mesajda dəyişir, yəni statusun NƏ
-- VAXT qoyulduğunu deyil, sonuncu toxunuşu göstərir. Bir sətir yazılan
-- söhbət taymeri sonsuz uzadardı.
--
-- `reminded_at` təkrar xatırlatmanı bağlayır: onsuz hər planlayıcı dövrü
-- eyni işçiyə eyni bildirişi göndərərdi.
ALTER TABLE support_tickets
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS waiting_since TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reminded_at TIMESTAMPTZ;

COMMENT ON COLUMN support_tickets.resolved_at IS
    '«Həll olundu» anı — avtomatik bağlanma taymerinin başlanğıcı '
    '(SUPPORT_AUTO_CLOSE_DAYS, migrations/068).';
COMMENT ON COLUMN support_tickets.waiting_since IS
    '«Gözləmədə» anı — işçiyə xatırlatma taymerinin başlanğıcı '
    '(SUPPORT_WAITING_REMINDER_DAYS, migrations/068).';
COMMENT ON COLUMN support_tickets.reminded_at IS
    'Son xatırlatmanın anı — eyni bildirişin hər dövrdə təkrarlanmasını '
    'bağlayır (migrations/068).';

-- Planlayıcı YALNIZ iki statusu süzür; indeks olmadan hər dövr tam skan olardı.
CREATE INDEX IF NOT EXISTS idx_support_tickets_status_timers
    ON support_tickets (tenant_id, status, resolved_at, waiting_since);

-- ---------------------------------------------------------------------------
-- 3. TELEGRAM KONFİQURASİYASI (kirayəçi başına BİR sətir)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_config (
    tenant_id           UUID PRIMARY KEY
                        REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    bot_token_encrypted TEXT NOT NULL,
    chat_id             TEXT NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by          UUID REFERENCES employees(id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE telegram_config IS
    'Telegram bot konfiqurasiyası — kirayəçi başına bir sətir. Token '
    'AES-256-GCM ilə şifrələnir (CHAT-1, migrations/068).';

DROP TRIGGER IF EXISTS trg_telegram_config_updated ON telegram_config;
CREATE TRIGGER trg_telegram_config_updated BEFORE UPDATE ON telegram_config
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE telegram_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS telegram_config_tenant_isolation ON telegram_config;
CREATE POLICY telegram_config_tenant_isolation ON telegram_config
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- Köhnə token-lər ARXİVLƏNİR, üstündən yazılmır: «Botu Dəyiş» əməliyyatından
-- sonra «hansı bot nə vaxt işləyirdi?» sualı cavabsız qalmamalıdır.
CREATE TABLE IF NOT EXISTS telegram_config_history (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL
                        REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    bot_token_encrypted TEXT NOT NULL,
    chat_id             TEXT NOT NULL,
    replaced_by         UUID REFERENCES employees(id),
    replaced_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE telegram_config_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS telegram_config_history_tenant_isolation ON telegram_config_history;
CREATE POLICY telegram_config_history_tenant_isolation ON telegram_config_history
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 4. İCAZƏ FLAG-LƏRİ
-- ---------------------------------------------------------------------------
-- Atributlar sətrin YARANDIĞI anda verilir: `trg_flag_attributes_immutable`
-- (013) sonrakı `UPDATE`-i bloklayır (056/063-ün öyrəndiyi dərs).
--
-- `can_view_internal_requests` — hardlock 0 (NONE): bu, ƏMƏLİYYAT növbəsidir,
--   struktur zəmanət deyil. Şirkət kimin cavab verdiyini özü seçir; məsələn
--   böyük şəbəkədə HR köməkçisinə də verilə bilər.
--
-- `can_view_technical_support` — hardlock 3 (DELEGABLE): defolt YALNIZ Root-da
--   olur, lakin Root onu açıq şəkildə həvalə edə bilməlidir (məsələn şirkətin
--   öz IT adamına). `ROOT_ONLY` seçsəydik həmin həvalə İMKANSIZ olardı və
--   tələb pozulardı.
--
-- `can_manage_telegram_config` — hardlock 1 (ROOT_ONLY): burada söhbət
--   BOT TOKEN-indən gedir. Token şirkətin adından mesaj göndərmək hüququdur;
--   onu CEO-ya belə vermək «kim göndərdi?» sualını cavabsız qoyardı.
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only, excludes_camera_role)
VALUES
    ('can_view_internal_requests', 'DESTEK',
        'Daxili müraciətlərə bax',
        'İşçilərin ŞİRKƏTƏ yazdığı müraciətlər (növbə, cərimə, kadr, '
        'məzuniyyət). Texniki dəstək növbəsi AYRIDIR və bu flag onu açmır.',
        0, FALSE, FALSE, FALSE),
    ('can_view_technical_support', 'DESTEK',
        'Texniki dəstək növbəsinə bax',
        'İşçilərin HAZIRLAYICIYA yazdığı texniki mesajlar. Defolt yalnız '
        'Root-dadır; Root onu açıq şəkildə həvalə edə bilər.',
        3, FALSE, FALSE, FALSE),
    ('can_manage_telegram_config', 'DESTEK',
        'Telegram ayarlarını idarə et',
        'Bot token-i, chat ID və aktivlik. Token şirkətin adından mesaj '
        'göndərmək hüququdur — ona görə YALNIZ Root (hardlock 1).',
        1, FALSE, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

-- Sətir əvvəldən mövcuddursa və atributları səhvdirsə `UPDATE` mümkün deyil
-- (elə həmin trigger). Sükutla davam etmək flag-i gözləniləndən ZƏİF
-- vəziyyətdə qoyardı — 056/063 ilə eyni qərar.
DO $$
DECLARE
    v_wrong TEXT;
BEGIN
    SELECT string_agg(code, ', ')
      INTO v_wrong
      FROM permission_flags
     WHERE (code = 'can_view_internal_requests' AND hardlock_level <> 0)
        OR (code = 'can_view_technical_support' AND hardlock_level <> 3)
        OR (code = 'can_manage_telegram_config' AND hardlock_level <> 1);

    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: bu flag-lər mövcuddur, lakin hardlock '
            'səviyyələri gözlənilənlə uyğun deyil: %', v_wrong;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 5. DEFOLT SAHİBLİK
-- ---------------------------------------------------------------------------
-- `granted_by` QƏSDƏN NULL (sütun defoltu) — sistem seed-i
-- `enforce_grantor_owns_flag()` istisnasıdır (schema.sql §18).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
  FROM positions p
 CROSS JOIN (VALUES
        ('can_view_internal_requests')
     ) AS f(flag_code)
 WHERE p.code IN ('ROOT', 'CEO', 'ADMIN', 'HR_ADMIN')
   AND p.tenant_id IS NULL
ON CONFLICT (position_id, flag_code) DO NOTHING;

INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
  FROM positions p
 CROSS JOIN (VALUES
        ('can_view_technical_support'),
        ('can_manage_telegram_config')
     ) AS f(flag_code)
 WHERE p.code = 'ROOT'
   AND p.tenant_id IS NULL
ON CONFLICT (position_id, flag_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. `#msg_XXXX` ARDICILLIĞI
-- ---------------------------------------------------------------------------
-- Nömrə DB ardıcıllığından gəlir, tətbiqdəki sayğacdan YOX: eyni kirayəçidə
-- iki nüsxə (kassa PC-si və menecerin noutbuku) eyni anda mesaj göndərə
-- bilər və yerli sayğaclar toqquşardı. Toqquşma isə burada adi qüsur deyil —
-- Telegram-dan gələn cavab SƏHV işçiyə çatardı.
--
-- MİNİMUM 1000-DƏN BAŞLAYIR: dörd rəqəmli istinad (`#msg_1000`) sabit
-- uzunluqdadır və gözlə oxunanda kəsilmədiyi dərhal görünür.
CREATE SEQUENCE IF NOT EXISTS support_message_ref_seq
    AS BIGINT START WITH 1000 INCREMENT BY 1 MINVALUE 1000 NO CYCLE;

COMMENT ON SEQUENCE support_message_ref_seq IS
    'Telegram `#msg_XXXX` istinadının mənbəyi (migrations/068).';

-- ---------------------------------------------------------------------------
-- 7. ROOT PARAMETRİ — TELEGRAM BİLDİRİŞ REJİMİ (063 NAXIŞI)
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` NULL-dur: dəyər mətndir, ədədi diapazon anlamı
-- yoxdur. İcazəli üç dəyərin siyahısı `TelegramNotifyMode`-dadır və
-- `RootControlUseCase.set_limit` onu yoxlayır — DB `CHECK`-i bura qoyulsaydı,
-- yeni rejim əlavə etmək miqrasiya tələb edərdi.
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('TELEGRAM_NOTIFY_MODE', 'HAMISI', 'TEXT', NULL, NULL,
     'Telegram bildiriş rejimi: HAMISI / YALNIZ TƏCİLİ / DEAKTİV '
     '(proqramdakı bölməyə müraciət hər halda düşür)'),
    ('TELEGRAM_REQUEST_TIMEOUT_SECONDS', '15', 'INTEGER', '5', '120',
     'Telegram sorğusunun gözləmə həddi (saniyə)'),
    ('TELEGRAM_POLL_INTERVAL_SECONDS', '20', 'INTEGER', '5', '3600',
     'Telegram cavablarının nə qədərdən bir yoxlanması (saniyə)'),
    ('SUPPORT_AUTO_CLOSE_DAYS', '3', 'INTEGER', '1', '90',
     '«Həll olundu» müraciət neçə gündən sonra avtomatik bağlansın'),
    ('SUPPORT_WAITING_REMINDER_DAYS', '2', 'INTEGER', '1', '90',
     '«Gözləmədə» müraciətdə işçiyə neçə gündən sonra xatırlatma getsin')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

CREATE OR REPLACE FUNCTION seed_telegram_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'TELEGRAM_NOTIFY_MODE', 'HAMISI', 'TEXT', NULL, NULL,
         'Telegram bildiriş rejimi: HAMISI / YALNIZ TƏCİLİ / DEAKTİV '
         '(proqramdakı bölməyə müraciət hər halda düşür)'),
        (NEW.tenant_id, 'TELEGRAM_REQUEST_TIMEOUT_SECONDS', '15', 'INTEGER', '5', '120',
         'Telegram sorğusunun gözləmə həddi (saniyə)'),
        (NEW.tenant_id, 'TELEGRAM_POLL_INTERVAL_SECONDS', '20', 'INTEGER', '5', '3600',
         'Telegram cavablarının nə qədərdən bir yoxlanması (saniyə)'),
        (NEW.tenant_id, 'SUPPORT_AUTO_CLOSE_DAYS', '3', 'INTEGER', '1', '90',
         '«Həll olundu» müraciət neçə gündən sonra avtomatik bağlansın'),
        (NEW.tenant_id, 'SUPPORT_WAITING_REMINDER_DAYS', '2', 'INTEGER', '1', '90',
         '«Gözləmədə» müraciətdə işçiyə neçə gündən sonra xatırlatma getsin')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_telegram_limits_for_new_tenant() IS
    'Yeni kirayəçiyə Telegram bildiriş rejimini əlavə edir (migrations/068).';

DROP TRIGGER IF EXISTS trg_seed_telegram_limits ON license_tenants;
CREATE TRIGGER trg_seed_telegram_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_telegram_limits_for_new_tenant();

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Kanal sütununu silmək BÜTÜN mövcud ticket-lərin ünvanını itirir: geri
-- qayıtdıqdan sonra daxili müraciətlər yenidən hazırlayıcıya görünər.
-- Telegram cədvəlini silmək isə token-i (şifrəli olsa da) və tarixçəni silir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TABLE IF EXISTS telegram_config_history;
--   DROP TABLE IF EXISTS telegram_config;
--   ALTER TABLE support_messages
--       DROP COLUMN IF EXISTS telegram_ref,
--       DROP COLUMN IF EXISTS telegram_message_id,
--       DROP COLUMN IF EXISTS telegram_sent_at,
--       DROP COLUMN IF EXISTS from_telegram,
--       DROP COLUMN IF EXISTS attachment_ref,
--       DROP COLUMN IF EXISTS attachment_name;
--   ALTER TABLE support_tickets
--       DROP COLUMN IF EXISTS channel,
--       DROP COLUMN IF EXISTS is_urgent,
--       DROP COLUMN IF EXISTS staff_last_read_at,
--       DROP COLUMN IF EXISTS resolved_at,
--       DROP COLUMN IF EXISTS waiting_since,
--       DROP COLUMN IF EXISTS reminded_at;
--   -- `ticket_status`-dan 'RESOLVED' dəyəri SİLİNMİR: PostgreSQL enum
--   -- dəyərinin silinməsini dəstəkləmir və sətirlər hələ ona istinad edir.
--   DROP TYPE IF EXISTS support_channel;
--   DROP SEQUENCE IF EXISTS support_message_ref_seq;
--   DROP TRIGGER IF EXISTS trg_seed_telegram_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_telegram_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'TELEGRAM_NOTIFY_MODE', 'TELEGRAM_REQUEST_TIMEOUT_SECONDS',
--       'TELEGRAM_POLL_INTERVAL_SECONDS', 'SUPPORT_AUTO_CLOSE_DAYS',
--       'SUPPORT_WAITING_REMINDER_DAYS');
--   DELETE FROM permission_flags WHERE code IN (
--       'can_view_internal_requests', 'can_view_technical_support',
--       'can_manage_telegram_config');
-- COMMIT;
