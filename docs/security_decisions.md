# KompasOS — TƏHLÜKƏSİZLİK QƏRARLARI (ADR)

Bu sənəd Faza 1-də qəbul edilmiş təhlükəsizlik qərarlarını, onların
əsaslandırmasını və spesifikasiyadan (kompasos.md) sapma hallarını qeyd edir.

Hər qərar bir kod (`SEC-00X`) daşıyır və koda/sxemə şərh kimi istinad edilir.

---

## SEC-001 — `can_approve_dual_control_override` ziddiyyətinin həlli

**Vəziyyət:** Qəbul edildi (spesifikasiyanın hərfi mətnindən şüurlu sapma)

**Problem.** Bölmə 3 dörd flag-i eyni cümlədə hardlock siyahısına salır və
deyir ki, onlar *"yalnız `Kamera_Nəzarətçisi` rolunda və ya … «kamera-tipli»
custom rollarda mövcud ola bilər"*. Eyni bölmədəki DUAL-CONTROL QAYDASI isə
30+ dəqiqəlik override-ın **HR_Admin/CEO-nun** ikinci təsdiqinə getdiyini
deyir. Hərfi tətbiqdə təsdiq flag-i heç kimdə olmazdı → dual-control əbədi
gözləmə vəziyyətinə düşərdi.

**Qərar.** İki ayrı bayraq:

| Flag | `is_anti_fraud` | `is_camera_only` | Kim daşıya bilər |
|---|---|---|---|
| `can_verify_returns` | ✔ | ✔ | yalnız kamera-tipli rollar |
| `can_override_return_time` | ✔ | ✔ | yalnız kamera-tipli rollar |
| `can_issue_fines` | ✔ | ✔ | yalnız kamera-tipli rollar |
| `can_approve_dual_control_override` | ✔ | ✘ | HR_Admin/CEO — kamera rolları **YOX** |

`is_anti_fraud` → heç vaxt `Mağaza_Meneceri`/`Satıcı`-ya verilmir (spesifikasiyanın
əsl niyyəti). `is_camera_only` → əməliyyat aparan üç flag üçün əlavə məhdudiyyət.
Üstəlik kamera-tipli rol təsdiq flag-ini daşıya **bilmir** — əks halda operator
öz override-ını özü təsdiqləyərdi.

**Tətbiq:** `schema.sql` §6, §18 (`enforce_anti_fraud_segregation`),
`database/tests/test_guards.sql` TEST 1/2/8.

---

## SEC-002 — Fernet əvəzinə AES-256-GCM

**Vəziyyət:** Qəbul edildi

**Problem.** Spesifikasiya "Fernet AES-256" deyir. Fernet faktiki olaraq
32 baytlıq açarı ikiyə bölür: 16 bayt HMAC-SHA256, 16 bayt **AES-128**-CBC.
Yəni hərfi mənada AES-256 deyil. Müqavilə/audit sənədində "AES-256" yazılıbsa,
bu uyğunsuzluqdur.

**Qərar.** Əsas şifrə **AES-256-GCM** (AEAD):

- 256-bit açar tam şəkildə AES-256 üçün istifadə olunur;
- bütövlük şifrənin özündə (GCM teqi) — ayrıca HMAC lazım deyil;
- **AAD (associated data) dəstəyi** — şifrəli dəyər öz kontekstinə bağlanır
  (`erp_server:<id>`, `totp:<employee_id>`), beləliklə bir sətrin şifrəli
  dəyərini başqa sətrə köçürmə (cut-and-paste) hücumu bağlanır;
- token formatı `v1.<key_id>.<base64url(nonce||ct||tag)>` — `key_id` rotasiya
  zamanı doğru açarı **sınaqsız** seçməyə imkan verir;
- **köhnə Fernet token-ləri oxunmağa davam edir**, `rotate_token()` onları
  AES-256-GCM-ə köçürür.

**Tətbiq:** `src/infrastructure/security/encryption.py`.

---

## SEC-003 — Saga reconciliation siyasətinin açıq reyestri

**Vəziyyət:** Qəbul edildi

**Problem.** Spesifikasiya hər uğursuzluqda `PENDING_RECONCILIATION` tələb
edir. Bütün sagalara tətbiq edilsə, adi şəbəkə kəsintiləri də növbəni doldurar
→ **alert fatigue** → real problemlər gözdən qaçar.

**Qərar.** Siyasət saga-ya görə `src/shared/saga_policies.py`-də AÇIQ təyin
olunur:

- **`ON_ANY_FAILURE`** (spesifikasiya-hərfi) — pul, davamiyyət, icazə/rol,
  audit izi, DB miqrasiyası, payroll export. 12 saga.
- **`ON_COMPENSATION_FAILURE`** — bildiriş, telemetriya, crash upload, profil
  şəkli, changelog push. 5 saga.
- **Reyestrdə olmayan hər saga → `ON_ANY_FAILURE`** (fail-safe default).

**Tətbiq:** `saga_policies.py`, `SagaOrchestrator(policy_resolver=...)`,
`main.build_container`.

---

## SEC-004 — TOTP replay qorunması və AAD bağlantısı

**Vəziyyət:** ⛔ **LƏĞV EDİLDİ — SEC-016 ilə əvəz olundu (2026-08-09)**

> Bu qərar artıq qüvvədə deyil. Müştəri qərarı ilə 2FA/TOTP tamamilə
> çıxarıldı; `totp.py`, DB sütunları və `pyotp` asılılığı silindi.
> Aşağıdakı mətn tarixi arayış üçün saxlanılır — **tətbiq etməyin**.

**Problem.** Spesifikasiya 2FA tələb edir, lakin TOTP-un iki praktik zəifliyini
göstərmir: (a) kod 30 saniyə etibarlıdır — çiynin üstündən baxan şəxs həmin
pəncərədə eyni kodla girə bilər; (b) şifrəli sirr başqa istifadəçinin sətrinə
köçürülə bilər.

**Qərar.**
- Hər uğurlu təsdiqdə **time-step counter** `employees.totp_last_used_counter`-də
  saxlanılır; eyni və ya daha köhnə counter rədd edilir (`REPLAY_DETECTED`).
- Sirr AES-256-GCM ilə, AAD = `totp:<employee_id>` şifrələnir.
- Drift pəncərəsi ±1 addım (±30 s) — mağaza PC saatları dəqiq deyil, lakin
  daha geniş pəncərə brute-force səthini artırır.
- **10 birdəfəlik ehtiyat kodu** (Argon2id ilə hash-lənmiş) — telefonu itən
  admin üçün; bu, bölmə 2-dəki "Emergency Access Recovery" prosedurunun işə
  düşmə ehtimalını azaldır.

**Tətbiq:** ~~`src/infrastructure/security/totp.py`~~ (silinib, bax SEC-016).

---

## SEC-005 — 4-rəqəmli PIN üçün MƏCBURİ pepper

**Vəziyyət:** Qəbul edildi — **istehsalat üçün ən vacib qərar**

**Problem.** 4-rəqəmli PIN-in cəmi **10 000** mümkün dəyəri var. Argon2id nə
qədər güclü olsa da, baza sızarsa hücumçu offline rejimdə işçi başına 10 000
variant sınamalıdır — 100 ms/hash-da bu ~17 dəqiqədir. **Argon2 tək başına
kifayət deyil.**

**Qərar.** PIN əvvəlcə
`HMAC-SHA256(pepper, "pin:" + employee_id + ":" + pin)` ilə emal olunur,
sonra Argon2id-yə verilir. Pepper (`KOMPASOS_HASH_PEPPER`) **bazada YOX**,
yalnız mühit dəyişənində / DPAPI-də saxlanılır.

Nəticə:
- DB sızsa (pepper sızmadan) → PIN-lər praktiki olaraq bərpa oluna bilməz;
- `employee_id` HMAC-a daxil olduğu üçün eyni PIN fərqli işçilərdə fərqli
  daycest verir → "kimlərdə eyni PIN var" analizi mümkün deyil.

Pepper olmadan sistem işləyir (deqradasiya), lakin `security.log`-a KRİTİK
yazı düşür və `python -m src.main --strict` istehsalat mühitində **uğursuz olur**.

**Əlavə:** zəif PIN-lər (`0000`, `1234`, `2580`, …) qəbul edilmir.

**Tətbiq:** `src/infrastructure/security/hashing.py`.

---

## SEC-006 — Hierarchy Guard: CEO ↔ CEO bloklanır, yalnız Root istisnadır

**Vəziyyət:** Qəbul edildi

**Problem.** Bölmə 3: *"Eyni pillədəki … istifadəçilərin icazələrinə HEÇ VAXT
müdaxilə edə bilməz."* Qayda hərfi tətbiq edilsə, tenant-ın ilk Root-u heç kimə
icazə verə bilməzdi (hər kəs ondan aşağı olmalıdır, amma digər `Root` deyil) →
sistem kilidlənərdi.

**Qərar.** Yalnız `ROOT` **rol kodu** bərabər-pillə qaydasından azaddır.
`CEO` digər `CEO`-ya və `Root`-a müdaxilə edə **bilmir**.

**Tətbiq:** `schema.sql` §18 `enforce_hierarchy_guard`, TEST 13.

**SEC-019 SONRASI DƏQİQLƏŞDİRMƏ (vacib).** Bu qərar yazılanda `Root` və `CEO`
hər ikisi priority 0-da idi, yəni «CEO `Root`-a toxuna bilmir» nəticəsi MƏHZ
bərabər-pillə şərtindən çıxırdı. SEC-019 həmin modeli düzəltdi (`Root` = 0,
`CEO` = 1), ona görə indi CEO → Root qadağası iyerarxiyanın TƏBİİ nəticəsidir.
SEC-006 isə hələ də zəruridir və mənası DARALDI: o, artıq yalnız GERÇƏK
bərabər-pillə hallarını (CEO ↔ CEO, Admin ↔ Admin, Root ↔ Root) tənzimləyir və
`Root` üçün istisna verir.

---

## SEC-019 — `Root` və `CEO` AYRI iyerarxiya pillələrindədir

**Vəziyyət:** Qəbul edildi

**Problem.** `RolePriority` `Root` və `CEO`-nu `EXECUTIVE = 0` altında
birləşdirirdi. Nəticədə iyerarxiya modelin ÖZÜNDƏ səhv idi: `CEO` tenant
sahibi ilə bərabər sayılırdı. «CEO Root-un icazələrinə toxuna bilmir» qaydası
iyerarxiyadan gəlmirdi — o, iki ƏLAVƏ qapının yan təsiri idi
(`hardlock_level = 1` və bərabər-pillə şərti). Bir flag `ROOT_ONLY`-dən
`ROOT_CEO`-ya keçsəydi, CEO onu `Root` rolundan çıxara bilərdi.

Səhvin ikinci, daha az görünən nəticəsi kimlik yolunda idi: bölmə 2 sirr
sıfırlamasına «daha yüksək VƏ YA BƏRABƏR» pilləyə icazə verir, yəni `0 > 0`
yanlış olduğu üçün `CEO` `Root` hesabına müvəqqəti şifrə təyin edə bilirdi —
bu, bütün `ROOT_ONLY` hardlock-larının dolayı yan keçilməsi idi.

Üçüncü nəticə funksional idi: `_assert_may_assign_position` aktorun rolunun
hədəf roldan CİDDİ ŞƏKİLDƏ yuxarıda olmasını tələb edir, yəni `Root` YENİ
`CEO` hesabı yarada bilmirdi.

**Qərar.** Nərdivan beş pilləlidir: `Root`=0 (TƏK BAŞINA), `CEO`=1, `Admin`=2,
`HR_Admin`/`Mağaza_Meneceri`/`Kamera_Nəzarətçisi`=3, `Satıcı`=4.
`RolePriority`-yə `ROOT` üzvü əlavə olundu; `EXECUTIVE` MƏNASINI saxladı
(«şirkət rəhbərliyi» = CEO) və dəyəri 1-ə sürüşdü.

`_PRIORITY_TO_ROLE[RolePriority.ROOT]` QƏSDƏN `SystemRole.CEO`-dur: prioritet
0-lı CUSTOM rol `Root` semantikası ALMAMALIDIR, əks halda «özümə 0-lı rol
yaradıb Root-a toxunum» yolu açılardı və domen DB trigger-lərindən (Root
istisnası rol KODU ilə verilir) fərqli qərar verərdi.

**Hardlock DƏYİŞMİR.** `ROOT_CEO` (=2) hələ də «Root VƏ CEO» deməkdir —
hardlock «flag kimə VERİLƏ bilər» sualına cavabdır, «kim kimə TOXUNA bilər»
sualına yox. İki qat qəsdən müstəqildir.

**Tətbiq:** `src/domain/value_objects/authorization.py`,
`src/domain/entities/position.py`, `database/schema.sql` §5/§18/§21,
`database/migrations/048_root_ceo_priority_split.sql`,
`tests/unit/test_role_priority_split.py`.

### DAVRANIŞ DƏYİŞİKLİYİ — «Root indi `CEO`-nu idarə edə bilir»

Bu, ayrıca bir qərar DEYİL, prioritet ayrılığının məntiqi nəticəsidir; lakin
istifadəçinin GÖRDÜYÜ davranış dəyişdiyi üçün buraxılış qeydi kimi ayrıca
yazılır — əks halda dəstək «əvvəl olmurdu, indi olur» sualına cavabsız qalar.

**NİYƏ əvvəl bağlı idi.** Strict Hierarchy Guard-ın əsası
`RolePriority.outranks()`-dir və o, BƏRABƏR pillə üçün `False` qaytarır
(«yalnız CİDDİ ŞƏKİLDƏ aşağı pilləyə toxunmaq olar»). Köhnə modeldə `Root` və
`CEO` hər ikisi `EXECUTIVE = 0` idi, yəni `Root.outranks(CEO)` → `0 > 0` →
`False`. Nəticədə **tenant sahibi öz şirkətinin CEO hesabına toxuna bilmirdi**
— bu, qorunma deyil, modelin səhvindən doğan sükutlu blok idi.

**İndi nə açıqdır.** `Root` = 0, `CEO` = 1 olduğu üçün `Root.outranks(CEO)` →
`True` və aşağıdakı mövcud əməliyyatlar `Root` → `CEO` istiqamətində işləyir.
Heç bir qapı SİLİNMƏDİ; eyni `outranks()` çağırışı indi düzgün cavab verir:

| Əməliyyat | Yer | Əvvəl | İndi |
|---|---|---|---|
| `CEO` hesabı YARATMAQ (rolu təyin etmək) | `user_management._assert_may_assign_position` | bloklu | açıq |
| `CEO` profilini redaktə / deaktiv etmək | `user_management.update_employee` / `deactivate_employee` | bloklu | açıq |
| `CEO`-nun şifrə / PIN sıfırlaması | `user_management.reset_password` / `reset_pin` | bloklu | açıq |
| `CEO`-ya kamera mağazaları təyin etmək | `user_management.assign_camera_stores` | bloklu | açıq |
| `CEO`-nun icazə flag-lərini dəyişmək | `permission_guards._assert_strict_hierarchy` | bloklu | açıq |
| `CEO` üçün performans qiymətləndirməsi (yazı + oxu) | `performance_reviews._require_hierarchy` | bloklu | açıq |
| `CEO` üçün POS həddi təyin etmək | `pos_threshold._require_hierarchy` | bloklu | açıq |
| `CEO` ROLUNU (position) redaktə etmək | `position.assert_may_be_edited_by` | bloklu | açıq |
| Toplu əməliyyatda `CEO` sətri | `bulk_operations` (eyni guard) | bloklu | açıq |

**Bu, səlahiyyət ARTIRMASI DEYİL.** Üç səbəbdən:

1. `Root` tenant-ın SAHİBİDİR — `can_manage_permissions`,
   `can_manage_system_limits`, lisenziya və Permission Registry onsuz da
   yalnız ondadır (`HardlockLevel.ROOT_ONLY`). `CEO` hesabına toxuna bilməmək
   ona heç bir qorunma vermirdi: `Root` istənilən halda `CEO`-nun rolundakı
   flag dəstini Registry-dən dəyişə bilirdi.
2. Əks istiqamət EYNİ dəyişikliklə DARALDI — `CEO` artıq `Root`-un nə
   icazələrinə, nə profilinə, nə də sirrinə toxuna bilir
   (`authentication._assert_may_reset`: köhnə modeldə `0 > 0` yanlış olduğu
   üçün `CEO` `Root`-a müvəqqəti şifrə təyin edə bilirdi — bu, bütün
   `ROOT_ONLY` hardlock-larının dolayı yan keçilməsi idi). Yəni xalis nəticə
   səlahiyyətin ARTMASI yox, DÜZGÜN İSTİQAMƏTƏ yönəlməsidir.
3. Anti-fraud hardlock-ları toxunulmaz qalır: `Root` bu qapı ilə də
   `can_verify_returns` / `can_issue_fines` / `can_override_return_time` /
   `can_approve_dual_control_override` flag-lərini `Mağaza_Meneceri` və
   `Satıcı`-ya VERƏ BİLMİR (`ANTI_FRAUD_FORBIDDEN_ROLES` + DB-dəki
   `enforce_anti_fraud_segregation()`).

**Əməliyyat qeydi.** Hər sadalanan əməliyyat mövcud audit yolundan keçir
(`AuditTrail.record()` istisna udmur), yəni `Root` → `CEO` müdaxiləsi
jurnalda görünür və sonradan sübut edilə bilər.

### DAVRANIŞ DƏYİŞİKLİYİ — `db_switch` / `plugin_management` rol qapıları «yalnız Root»

`DatabaseSwitchUseCase._require_permission` və
`PluginManagementUseCase._require` rol şərti `Root VƏ CEO` idi, halbuki hər
iki əməliyyatın flag-i (`can_switch_db`, `can_manage_plugins`)
`permission_flags`-də `hardlock_level = 1` = `ROOT_ONLY` daşıyır. `CEO` həmin
flag-i nə rol dəsti, nə fərdi override ilə ala bilmir — yəni rol şərtindəki
`CEO` budağına HEÇ VAXT çatılmırdı (ölü kod). İki qat fərqli qərar yazırdı;
CLAUDE.md §5 qaydanın hər iki yerdə EYNİ olmasını tələb edir, ona görə rol
qapısı `SystemRole.ROOT`-a daraldıldı.

**Heç bir imkan itmir**, çünki bağlayıcı qat flag qatıdır və o dəyişmədi.
`kompasos.md` bölmə 1/2-dəki «Root/CEO» mətni spesifikasiyanın ÜMUMİ
ifadəsidir; icazə kataloqu (`schema.sql` §22) onun DƏQİQLƏŞDİRİLMİŞ
variantıdır və bağlayıcıdır. Hardlock səviyyəsi gələcəkdə Registry-dən 2-yə
(`ROOT_CEO`) qaldırılarsa, rol qapısı da AÇIQ şəkildə genişləndirilməlidir.

**Tətbiq (davranış qeydləri):** `src/application/use_cases/db_switch.py`,
`src/application/use_cases/plugin_management.py`,
`database/migrations/049_position_priority_range_narrowing.sql`,
`tests/unit/test_role_priority_split.py`, `tests/unit/test_remaining_gaps.py`.

---

## SEC-007 — `audit_logs` DB səviyyəsində append-only

**Vəziyyət:** Qəbul edildi

**Problem.** Bölmə 4: *"orijinal qeyd heç vaxt silinmir"*. `REVOKE UPDATE,
DELETE` kifayət deyil — cədvəl sahibi (owner) və superuser onu yan keçir.

**Qərar.** `BEFORE UPDATE OR DELETE` trigger-i istisna atır — **hər kəsə**
tətbiq olunur. `security_events` üçün yalnız UPDATE bloklanır (tenant
silinərkən CASCADE DELETE işləməlidir).

**Əlavə nəticə:** `audit_logs.tenant_id` artıq **foreign key deyil** —
`ON DELETE SET NULL` audit sətrinə UPDATE deməkdir və trigger ilə ziddiyyət
təşkil edərdi. Audit qeydləri tenant silinsə belə yaşamalıdır — bu, düzgün
audit dizaynıdır.

**Tətbiq:** `schema.sql` §16, §26, TEST 14.

---

## SEC-008 — RLS fail-closed

**Vəziyyət:** Qəbul edildi

**Problem.** Faza 1-in ilk variantında siyasət `app.tenant_id` təyin
edilməyibsə **hər şeyi buraxırdı**. Bu o deməkdir ki, repozitoriya qatında
bir yerdə `SET LOCAL` unudulsa, sistem sükutla bütün tenant-ların
məlumatını qaytarardı — çox-tenant sızması.

**Qərar.**
- Siyasət **fail-closed**: kontekst yoxdursa heç bir sətir görünmür.
- `current_tenant_id()` yararsız UUID mətnində istisna atmır, `NULL` qaytarır
  (yenə fail-closed).
- `tenant_id` sütunu olmayan alt-cədvəllər (`user_permission_overrides`,
  `position_permissions`, `camera_operator_store_assignment`, …) valideyn
  sətir üzərindən `EXISTS` predikatı ilə qorunur.
- **Faza 3 müqaviləsi:** hər tranzaksiyada `SET LOCAL app.tenant_id = …`.
  `SET LOCAL` seçilib ki, connection pool-da dəyər növbəti istifadəçiyə
  sızmasın (adi `SET` sessiya boyu qalır — pool ilə təhlükəlidir).

**Tətbiq:** `schema.sql` §27, TEST 15.

---

## SEC-009 — Ayrıca tətbiq DB rolu (`kompasos_app`)

**Vəziyyət:** Qəbul edildi

**Problem.** Tətbiq owner/superuser ilə qoşulsa, RLS-i və append-only
GRANT-larını avtomatik yan keçir — yuxarıdakı bütün qorumalar mənasızlaşır.

**Qərar.** `kompasos_app` rolu: `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`,
DDL hüququ yoxdur, RLS-ə **tabedir**. `audit_logs`/`security_events` üzərində
`UPDATE`/`DELETE` yoxdur, `license_tenants` üzərində `UPDATE`/`DELETE` yoxdur
(lisenziya statusu yalnız Developer Panelindən dəyişir — bölmə 8).

Supabase kimi platformalarda `CREATE ROLE` mümkün olmaya bilər — blok
xəbərdarlıqla atlanır və eyni GRANT-lar əl ilə tətbiq edilməlidir.

**Tətbiq:** `schema.sql` §28.

---

## SEC-010 — `pg_cron` yoxdursa sükut yox, görünən xəbərdarlıq

**Vəziyyət:** Qəbul edildi

**Problem.** `pg_cron` aktiv deyilsə timeout eskalasiyası, "İcazəsiz Qayıb"
təyinetməsi və 6 aylıq xal sıfırlanması **sükutla** işləməzdi — spesifikasiyanın
bir neçə əsas biznes qaydası görünmədən sönərdi.

**Qərar.**
- `scheduled_job_runs` cədvəli — hər icranın qeydi (vaxt, nəticə, xəta).
- `run_all_scheduled_jobs()` — xarici scheduler üçün **tək giriş nöqtəsi**.
- `v_scheduled_job_health` — `is_stale` sütunu; System Health Monitor (bölmə 6)
  bunu göstərir.
- `pg_cron` tapılmadıqda `RAISE WARNING` + `scheduled_job_runs`-a uğursuz
  bootstrap qeydi.

**Tətbiq:** `schema.sql` §29, `docs/scheduler_setup.md`, TEST 17.

---

## SEC-011 — Sessiya idarəetməsi

**Vəziyyət:** Qəbul edildi

**Problem.** Bölmə 2: *"Kamera_Nəzarətçisi … növbə boyu sessiya açıq qalır."*
Müddət və ləğv mexanizmi göstərilmir — gecə növbəsinə qalan açıq sessiya
ertəsi gün başqasının əlinə keçə bilər.

**Qərar.** `auth_sessions` cədvəli:
- token-in **özü saxlanılmır**, yalnız SHA-256 daycesti (DB sızsa mövcud
  sessiyalar oğurlana bilməz);
- `expires_at` (hərəkətsizlik) + `absolute_expiry` (mütləq limit), CHECK ilə
  `expires_at <= absolute_expiry`;
- kontekst: `ADMIN_PANEL` (30 dəq. hərəkətsizlik / 8 saat mütləq),
  `CAMERA_DASHBOARD` (12 saat mütləq — bir növbə, hərəkətsizlik yoxlaması yox,
  çünki operator ekrana baxır, klikləmir), `KIOSK` (sessiya yoxdur — hər
  əməliyyat üçün PIN);
- `revoked_at`/`revoked_by` — admin uzaqdan ləğv edə bilir.

**Tətbiq:** `schema.sql` §17b, TEST 16.

---

## SEC-012 — İmzasız istehsalat buraxılışı qadağandır

**Vəziyyət:** Qəbul edildi

**Problem.** İlk variantda sertifikat yoxdursa CI yalnız xəbərdarlıq verib
**imzasız `.exe` buraxırdı**. Nəticə: Windows SmartScreen xəbərdarlığı →
müştəri "virus?" zəngi; daha pisi — auto-update kanalı imza yoxlamasına
arxalandığı üçün imzasız buraxılış onu sındırır.

**Qərar.** `production-release` job-u sertifikat olmadan **uğursuz olur**.
Təcili hal üçün açıq nəzarətli istisna: `workflow_dispatch` →
`allow_unsigned = true` (jurnalda görünən, qəsdən verilən qərar).

**Tətbiq:** `.github/workflows/ci.yml`.

---

## SEC-013 — Log-da PII/sirr maskalanması

**Vəziyyət:** Qəbul edildi

PIN, şifrə, token, TOTP sirri, Fernet açarı və oxşar açar adları
`logger.REDACTED_KEYS` siyahısına görə **rekursiv** maskalanır. `KeyMaterial`
sinfinin `__repr__`-i də maskalanıb ki, açar traceback-ə və ya pytest
diff-inə düşməsin.

**Tətbiq:** `src/shared/logger.py`, `encryption.py`.

---

## SEC-014 — Timing/enumeration qorunması

**Vəziyyət:** Qəbul edildi

`HashingService._verify` hesab mövcud olmasa belə **dummy hash** yoxlayır —
cavab vaxtı "bu e-poçt sistemdə var/yoxdur" məlumatını sızdırmır. TOTP kod
müqayisəsi `secrets.compare_digest` ilə sabit vaxtlıdır.

---

## SEC-015 — `RESTRICT` əvəzinə `NO ACTION DEFERRABLE` (real bazada aşkarlandı)

**Vəziyyət:** Qəbul edildi — **canlı Supabase bazasında test zamanı tapıldı**

**Problem.** `user_permission_overrides.granted_by` və `fines.employee_id`
`ON DELETE RESTRICT` idi. Bu, tenant silinməsini **tamamilə bloklayırdı**:

1. `RESTRICT` **dərhal** yoxlanılır — referens edən sətir EYNİ əməliyyatda
   silinsə belə xəta verir.
2. `NO ACTION`-a keçirdikdən sonra da davam etdi: yoxlama **statement** sonunda
   işləyir, lakin cascade sırası zəmanətli deyil. A işçisi B-yə override
   veribsə, A silinərkən B-nin sətri hələ mövcud ola bilər.

**Qərar.** `ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED` — yoxlama
**COMMIT** anına keçir, o vaxta bütün cascade silinmələri bitib.

**Qoruma İTMİR:** əgər tranzaksiya sonunda hələ də orfan sətir varsa
(məs. icazə vermiş işçini TƏK-TƏK silmək cəhdi), COMMIT uğursuz olur.

**Necə aşkarlandı.** `database/tests/test_guards.sql` 17/17 testi keçirdi,
lakin son **təmizləmə** addımı (`DELETE FROM license_tenants`) uğursuz oldu.
Statik nəzərdən keçirmə bunu tutmazdı — yalnız real icra göstərdi.

**Tətbiq:** `schema.sql` §7, §11; mövcud bazalar üçün idempotent ALTER bloku.

---

## SEC-016 — Admin girişi: username + şifrə; 2FA ÇIXARILDI

**Vəziyyət:** Qəbul edildi (müştəri qərarı, 2026-08-09) — **SEC-004-ü ləğv edir**

**Kontekst.** Spesifikasiya bölmə 2 (sətir 43, 44, 223, 290, 307) admin-tier
giriş üçün "e-poçt + güclü şifrə + məcburi TOTP 2FA" tələb edirdi. Müştəri
bunu sadələşdirmək qərarına gəldi. Spesifikasiyanın həmin bəndləri bu qərarla
**əvəz olunmuş sayılır** — mətn qəsdən redaktə edilmir ki, dəyişikliyin nə
olduğu görünsün.

**Qərar.**

| Sahə | Əvvəl | İndi |
|---|---|---|
| Giriş identifikatoru | `employees.email` (CITEXT, unikal) | `employees.username` (CITEXT, tenant-daxili unikal) |
| İkinci faktor | Məcburi TOTP + 10 ehtiyat kodu | **Yoxdur** |
| Giriş axını | 2 addım (şifrə → kod) | **1 addım** |
| E-poçt | Autentifikasiya identifikatoru | `notification_email` — yalnız bildiriş, nullable |
| Bərpa kimlik təsdiqi | Fərdi hesab e-poçtu | `license_tenants.company_contact_email` / `_phone` |

**Təhlükəsizliyə təsiri açıq etiraf olunur.** TOTP oğurlanmış şifrəyə qarşı
ikinci maneə idi; o maneə artıq yoxdur. Qalan tədbirlər: Argon2id +
`employee_id`-yə bağlı pepper (SEC-005), admin-tərəfindən sıfırlama +
`must_change_password`, `security_events` qeydiyyatı, sessiya limitləri
(SEC-011), enumeration qorunması (SEC-014). Kompensasiya tam deyil — bu,
qəbul edilmiş biznes riskidir.

**Niyə `email` sütunu silinmədi, ADI DƏYİŞDİRİLDİ.** Tələb həm "email
identifikator kimi çıxarılsın", həm "yeni nullable `notification_email`
əlavə edilsin" deyirdi. İki ayrı sütun saxlanılsaydı mövcud ünvanlar itər və
eyni məlumat üçün iki mənbə qalardı. Ad dəyişikliyi hər iki tələbi ödəyir.

**Niyə `license_tenants`-a yeni `company_contact_*` cütü ƏLAVƏ edilmədi.**
Mövcud `contact_email`/`contact_phone` artıq dəqiq bu rolu oynayırdı.
Yanına eyni məzmunlu ikinci cüt qoymaq Emergency Access Recovery-nin SƏHV
sütunu yoxlaması riskini yaradardı — bu isə birbaşa təhlükəsizlik qüsurudur.
Ona görə sütunlar tələb olunan adlara **yenidən adlandırıldı**.

**Emergency Access Recovery gücləndirildi.** Əvvəl yalnız iki şərt vardı
(aktiv admin qalmaması + istinad nömrəsi). İndi üçüncü və ƏSAS şərt əlavə
olundu: müraciət edən `TenantContact.matches()` ilə şirkət əlaqəsinə qarşı
təsdiqlənməlidir. Bu olmasaydı prosedur istənilən şəxsə Root hesabı verən
arxa qapı olardı.

**Username formatı ASCII-dir** (`^[a-z0-9][a-z0-9._-]{2,31}$`). Mağaza
PC-lərində klaviatura düzümü Azərbaycan, rus və ya ingilis ola bilər —
"şəbnəm" adlı hesab ingilis düzümündə yazıla bilməzdi. Ad-soyad sahələrində
Azərbaycan hərfləri sərbəstdir; məhdudiyyət yalnız giriş identifikatorunadır.

**Tətbiq:** `database/migrations/001_username_auth.sql`,
`domain/value_objects/credentials.py` (`Username`),
`application/use_cases/authentication.py` (`AdminLoginUseCase.login`,
`TenantContact`), `infrastructure/persistence/{mappers,repositories}.py`.

---

## SEC-017 — Drive razılığı: loopback + PKCE; `oob` axını istifadə edilmir

**Vəziyyət:** Qəbul edildi (2026-08-10) — miqrasiya 002-nin davamı

**Kontekst.** Cərimə sübut şəkilləri müştərinin ÖZ Google Drive hesabında
saxlanılır (bax `migrations/002` başlığı). Hesabı qoşmaq üçün OAuth razılığı
lazımdır və masaüstü tətbiqində bunun iki tarixi yolu var idi:

1. `urn:ietf:wg:oauth:2.0:oob` — kod ekranda göstərilir, istifadəçi yapışdırır;
2. loopback yönləndirmə — brauzer kodu `http://127.0.0.1:<port>`-a göndərir.

**Qərar: loopback + PKCE.** Google `oob` axınını 2022-də qapadıb; yeni
klientlərdə o, ümumiyyətlə işləmir, ona görə seçim əslində texniki
məcburiyyətdir. Google Cloud Console-da klient tipi **"Desktop app"**
olmalıdır.

| Element | Seçim | Səbəb |
|---|---|---|
| Port | `0` (OS seçir) | Sabit port onu tutan başqa proqram tərəfindən bloklanardı |
| PKCE | S256, hər axında yeni `code_verifier` | Masaüstündə `client_secret` sirr DEYİL (.exe-ni açan görür) — real müdafiə budur |
| `state` | 32 baytlıq təsadüfi, uyğunsuzluqda rədd | CSRF: cavab BAŞQA axına aid ola bilər |
| Scope | yalnız `drive.file` + `userinfo.email` | Bütöv `drive` istifadəçinin BÜTÜN sənədlərini açardı və Google yoxlaması tələb edərdi |
| `access_type` | `offline` + `prompt=consent` | `refresh_token` yalnız belə gəlir; ikincisi olmasa TƏKRAR qoşulma sükutla sınardı |
| Gözləmə | `poll()` (≤50 ms), Qt taymeri | Bloklayan gözləmə interfeysi dondurardı; ayrıca sap əlavə sinxronizasiya tələb edərdi |
| Vaxt həddi | 300 san, sonra port bağlanır | Açıq qalan lokal dinləyici müddətsiz yaşamamalıdır |

**Token saxlanması.** `refresh_token` ekrandan KEÇMİR: kontrollerin
yaddaşında bir an qalır və `DriveConnectionRepository.connect()`-ə verilir;
orada AES-256-GCM ilə, AAD konteksti `drive_connection:<id>` olmaqla
şifrələnir (SEC-002 modeli). Şifrəli sətir başqa bağlantıya köçürülsə
deşifrə OLUNMUR. Jurnalda yalnız hesabın e-poçtu qalır; HTTP xəta cavabının
gövdəsi HEÇ VAXT loglanmır (SEC-013).

**Səlahiyyət.** `can_manage_drive_connection` (hardlock 0, defolt yalnız
ROOT/CEO). Yoxlama İKİ yerdədir: menyu maddəsi (görünmür) və
`DriveConnectionController._on_connect` (ekran birbaşa açılsa da port
açılmır) — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" tək qapı ola bilməz.

**Tətbiq:** `infrastructure/storage/oauth_flow.py`,
`presentation/controllers/drive_connection.py`,
`presentation/screens/group_d.py` (`DriveConnectionScreen`),
`tests/unit/test_drive_oauth_flow.py` (real loopback serveri ilə).

---

## SEC-018 — İcazəli fayl formatı: sahib-tipinə görə ayrılır, `system_limits`-də DEYİL

**Vəziyyət:** Qəbul edildi (2026-08-13) — Faza 7 sənəd modulunun davamı

**Kontekst.** Faza 7-də sübut yükləmə növbəsi ümumiləşdirildi: eyni SQLite
spool həm cərimə sübutunu (`owner_type = FINE`), həm də işçi sənədini
(`EMPLOYEE_DOCUMENT`) daşıyır. Format siyahısı isə tək qalmışdı
(`ALLOWED_EXTENSIONS` = JPG/PNG/WEBP), yəni müqavilə — praktikada PDF —
ümumiyyətlə yüklənə bilmirdi: modul əsas istifadə halında işləmirdi.

**Qərar 1 — siyahı GENİŞLƏNDİRİLMİR, AYRILIR.** Vahid siyahıya `.pdf`
əlavə etmək cərimə tərəfini də açardı. Cərimə sübutu kameradan gələn
fotodur; ora PDF qəbul etməyin əməliyyat səbəbi yoxdur, hücum səthini isə
genişləndirər (PDF konteyner formatıdır: JavaScript, qoşma fayl, xarici
istinad daşıya bilər və şəkil kimi renderlənmədiyi üçün onu gözlə YOXLAYAN
operator da olmur). Siyahı sahib tipinə görə seçilir; naməlum sahib tipi ən
DAR dəstə düşür (fail-closed), yəni gələcəkdə əlavə edilən sahib növü
sükutla PDF-i açmır.

| Sahib tipi | İcazəli uzantılar | Məzmun yoxlaması |
|---|---|---|
| `FINE` | `.jpg`, `.jpeg`, `.png`, `.webp` | JPEG/PNG/RIFF-WEBP imzası (dəyişməyib) |
| `EMPLOYEE_DOCUMENT` | yuxarıdakılar + `.pdf` | şəkil imzası, PDF üçün `%PDF-` |
| naməlum | yalnız şəkil | şəkil imzası |

**Qərar 2 — PDF-də uzantı–məzmun uyğunluğu MƏCBURİDİR.** Şəkil yolunda
`.jpg` adlı PNG buraxılır (`_looks_like_image` başlığı), çünki baytlar
`_downscale`-dən keçib yenidən JPEG kimi yazılır — Drive-a gedən fayl hər
halda şəkildir. PDF isə kiçildilmir (imzalı sənədi çevirmək onu
DƏYİŞDİRMƏK olardı), yəni bayt olduğu kimi saxlanır; ona görə `.pdf` adının
arxasında `%PDF-` imzası TƏLƏB OLUNUR. `.pdf` adlı `MZ` (Windows icra
faylı) rədd edilir.

**Qərar 3 — siyahı `system_limits`-ə ÇIXARILMIR (CLAUDE.md §5).**
`MAX_UPLOAD_SIZE_BYTES` konfiqurasiyadır, çünki o, MİQDARDIR: Root onu
dəyişəndə qorumanın növü yox, yalnız həddi sürüşür, səhv dəyər (0/mənfi)
isə fallback-a qayıdır — yəni konfiqurasiya qorumanı SÖNDÜRƏ BİLMİR.
Uzantı siyahısı isə hücum səthinin ÖZÜDÜR: cədvələ bir sətir (`.svg`,
`.html`, `.exe`) əlavə etmək icra oluna bilən məzmuna yol açardı və həmin
format üçün imza yoxlaması olmadığından ƏN GÜCLÜ qat — məzmun yoxlaması —
sükutla keçilərdi. GUI-dan verilən bir sətir bütün faylı yoxlanmadan
buraxa bilirsə, o, limit deyil, struktur zəmanətdir. Yeni format həmişə
KOD dəyişikliyidir: yeni imza + yeni test.

**İki qat, tək qayda.** Yoxlama `validate_evidence_payload()`-dadır və İKİ
yerdən çağırılır: `EvidenceUploadQueue.enqueue()` (fayl DİSKƏ yazılmazdan
əvvəl) və `GoogleDriveStorageProvider.upload()` (yükləmə anında). Sahib
tipi hər ikisinə ötürülür — biri ötürməsəydi, qanuni sənəd PDF-i növbədə
`REJECTED` olardı. Sərhəd `UploadOwnerType.value` (mətn) səviyyəsindədir:
enum `upload_queue.py`-dadır və o, `google_drive.py`-ı idxal edir, tərs
idxal dairə yaradardı. Sürüşməni
`test_owner_type_keys_match_the_queue_enum` bağlayır.

**Tətbiq:** `infrastructure/storage/google_drive.py`
(`allowed_extensions_for`, `is_pdf_upload`, `validate_evidence_payload`),
`infrastructure/storage/upload_queue.py` (`enqueue`,
`EvidenceUploadWorker.run_once`), `presentation/screens/group_c.py`
(`EmployeeDocumentDialog._pick_file` süzgəci),
`tests/unit/test_security_hardening.py`, `tests/unit/test_drive_storage.py`.

---

## SEC-020 — Üz-təsdiqi istisnasının kompensasiyası şərti KİLİDLƏ qorunur

**Vəziyyət:** Qəbul edildi (2026-08-15) — anti-fraud auditi tapıntısı

**Kontekst — nə boşluq idi.** `facecontrol.md` bənd 14 üz təsdiqindən
PIN-only istisnasını (tibbi/fiziki səbəb) YALNIZ bir şərtlə verir:

> «MƏCBURİ KOMPENSASİYA EDİCİ NƏZARƏT: İstisnalı işçinin HƏR giriş/qayıdış
> təsdiqi avtomatik olaraq mövcud DUAL-CONTROL axınına düşür — "bir az
> diqqətli ol" kimi qeyri-müəyyən tövsiyə DEYİL, MƏCBURİ ikinci-təsdiq.»

Yəni istisnanın YEGANƏ əvəzləyicisi `DUAL_CONTROL` modulunun axınıdır.
Lakin həmin modul `feature_toggles`-də adi sətir idi (`is_structural = FALSE`,
`schema.sql` §24 seed-i), yəni Root onu **yazılı təsdiq olmadan, bir kliklə**
söndürə bilirdi. Kod tərəfində isə:

* `leave_verification.apply_override` toggle-a BAXIRDI;
* `face_control` istisna yolu (`_dual_control_required`) toggle-a **heç vaxt
  baxmırdı**.

Nəticə tərif olunmamış davranış idi və hər iki ehtimal pis idi:

1. qapı yenə `DUAL_CONTROL_REQUIRED` qaytarır → təsdiqi verəcək axın
   söndürülüb, deməli istisnalı işçi **heç vaxt günə başlaya bilmir** və heç
   bir mesaj səbəbi izah etmir;
2. kompensasiya sükutla itir → istisnalı işçinin PIN-i ilə **istənilən şəxs**
   təkbaşına təsdiq alır — bənd 14-ün bağlamaq istədiyi məhz həmin aldatma
   yolu bir toggle ilə yenidən açılır.

Üstəlik bu, CLAUDE.md §5-in prinsipini pozurdu: **struktur zəmanət sadə
toggle ilə söndürülə bilməz.**

**Qərar — ŞƏRTİ KİLİD (dar yol), `is_structural` DEYİL.** İnvariant belə
ifadə olunur: «(kirayəçidə aktiv üz-təsdiqi istisnası var) VƏ (`DUAL_CONTROL`
sönükdür)» cütü heç vaxt mövcud olmamalıdır. Kilid İKİ tərəflidir, çünki
invarianta iki tərəfdən yaxınlaşmaq olar:

| Yol | Qapı |
|---|---|
| modulu söndür (istisna var) | `RootControlUseCase._require_no_dependent_guarantee` → `CompensatingControlLockedError` |
| istisna ver/uzat (modul sönük) | `FaceControlExemptionUseCase._require_compensating_control` → `FaceControlError` |
| birbaşa SQL (ekranı yan keç) | `enforce_face_exemption_compensation()` + `enforce_exemption_requires_compensation()` (migrations/051) |
| artıq mövcud vəziyyət (köhnə konfiqurasiya) | `FaceVerificationUseCase._exempt_employee_gate` → fail-closed, manual təsdiqə |

Yalnız birinci qapını yazsaydıq, sıranı dəyişdirmək («əvvəlcə modulu söndür,
sonra istisna ver») qorumanı tamamilə keçərdi.

**Niyə `is_structural = TRUE` KİFAYƏT ETMİRDİ.** İkinci variant modulu
struktur-kritik elan etmək idi (mövcud `MIN_CONFIRMATION_LENGTH` axını —
yazılı təsdiq). Rədd edildi, üç səbəbdən:

* o, söndürməni **dayandırmır**, yalnız 6 simvolluq mətn tələb edir. Təsdiq
  yazan Root istisnalı işçini yenə kompensasiyasız qoyardı — sənədləşmə
  əlavə olunar, zəmanət isə bərpa olunmazdı. Bənd 14 «MƏCBURİ» deyir,
  «söndürüləndə qeyd et» yox;
* zəmanət **ŞƏRTLİDİR**: aktiv istisnası olmayan kirayəçidə `DUAL_CONTROL`
  həqiqətən adi bir qatdır (manual vaxt düzəlişi həddi). Statik bayraq şərti
  qaydanı ifadə edə bilmir və onu bütün kirayəçilərə yayardı;
* `is_structural` hazırda `CAMERA_VERIFICATION`-ın mənasını daşıyır («axının
  struktur əsası»); şərti qaydalarla doldurmaq həmin bayrağın mənasını
  seyrəldər və növbəti oxucu üçün «struktur» sözünü ölçüsüz edərdi.

**Kilid əbədi deyil.** Root əvvəlcə istisnaları «Üz Təsdiqi İstisnaları»
ekranından ləğv edir, sonra modulu söndürür — açar Root-un öz əlindədir.
`revoke` / `expire_due` yolları QƏSDƏN toxunulmazdır: onlar boşluğu BAĞLAYIR
və bloklansaydılar ölü-kilid yaranardı.

**Runtime davranışı (fail-closed, lakin çıxışı olan).** Ekranı yan keçən yolla
yaranmış vəziyyətdə `_exempt_employee_gate` `DUAL_CONTROL_REQUIRED` ƏVƏZİNƏ
`MANUAL_APPROVAL_REQUIRED` qaytarır. Səbəb: manual təsdiq kanalı
(`VERIFICATION_TIMEOUT`, bənd 5) `DUAL_CONTROL` toggle-ından **asılı deyil**,
yəni işçi bağlı qapı qarşısında qalmır — təsdiqi HR_Admin/CEO verir. Vəziyyət
sükutla yaşamır: ayrıca audit əməliyyatı
(`FACE_EXEMPT_COMPENSATION_UNAVAILABLE`), `security.log`-da
`FACE_EXEMPTION_COMPENSATION_MISSING` və kritik bildiriş yazılır. İşçinin
gördüyü mesaj səbəbi VƏ növbəti addımı deyir; «Sistem xətası» yazılmır.

**Tətbiq:** `domain/policies.py` (`FACE_EXEMPTION_COMPENSATING_MODULE`),
`application/use_cases/root_control.py`
(`CompensatingControlLockedError`, `_require_no_dependent_guarantee`),
`application/use_cases/face_control.py` (`_exempt_employee_gate`,
`_compensation_unavailable`, `_require_compensating_control`),
`presentation/composition.py` (bağlantı),
`database/migrations/051_face_exemption_compensation_lock.sql`,
`database/tests/test_guards.sql` (TEST 33/34),
`tests/unit/test_face_control.py`, `tests/unit/test_phase5_use_cases.py`.

---

## SEC-021 — Tenant kimliyi: boş mühit dəyişəni ilk quraşdırmadır, xəta deyil

**Vəziyyət:** Qəbul edildi (2026-08-16) — ilk açılış axınının qüsuru

**Kontekst — nə baş verirdi.** `build_context()` `KOMPASOS_TENANT_ID` boş
olduqda `StartupError` atırdı və istifadəçi «Quraşdırma tamamlanmayıb» fatal
ekranını görürdü. Halbuki sıfırdan quraşdırmada həmin dəyişən TƏRİFƏ GÖRƏ
boşdur (`.env.example`-də boş göndərilir) və onu dolduracaq yeganə ekran —
İlk Quraşdırma Sihirbazı — məhz həmin xəta ucbatından heç vaxt açılmırdı.
Sihirbazın kodu (`screens/group_a_entry.FirstRunWizard`,
`use_cases/first_run_setup`) tam yazılmışdı; ora aparan yol yox idi.

**Qərar.** Kimlik `shared/installation.py`-da ÜÇ mənbədən həll olunur:
mühit dəyişəni → yerli fayl (`%LOCALAPPDATA%\KompasOS\datainstallation.json`) → yeni UUID. «Root hesabı varmı?» sualı isə BAZAYA
verilir (`FirstRunSetupUseCase.is_required`). Bloklayıcı xəta yalnız üç halda
qalır: baza əlçatan deyil, sxem ümumiyyətlə tətbiq olunmayıb
(`SQLSTATE 42P01`), lisenziya deaktivdir (`LICENSE_INACTIVE`).

**Lisenziya qapısı NİYƏ YAN KEÇİLMİR.** Bütün cədvəllərin `tenant_id`-si
`license_tenants(tenant_id)`-ə xarici açarla bağlıdır, yəni sihirbazın işləməsi
üçün həmin sətir lazımdır. Sətri sihirbaz YALNIZ identifikator BU MAŞINDA
yaranıbsa qurur (`ApplicationContext.self_hosted`). Mühitdən gələn — yəni
təchizatçının verdiyi — identifikator üçün sətir qurulmur: qursaydıq,
istənilən UUID-ni mühitə yazıb «AKTIV» tenant yaratmaq mümkün olardı.

Özünə-host edilən sətir `license_key_hash = SELF_HOSTED_NO_LICENSE_KEY` nişanı
ilə yaradılır (uydurma hash YOX) və statusu `AKTIV`-dir: ödəniş münasibəti
olmayan quraşdırmada `ODENIS_GOZLENILIR` olmayan borcu göstərərdi. Mövcud sətrə
TOXUNULMUR (`ON CONFLICT DO NOTHING`) — `DO UPDATE` deaktiv tenant-ı sihirbazı
açmaqla dirildərdi.

**Kimliyin sabitliyi məlumat bütövlüyü məsələsidir.** Yeni identifikator diskə
yazıla bilmirsə başlanğıc DAYANIR: davam etsəydik hər açılışda yeni tenant
yaranar və dünənki məlumat görünməz qalardı. Mühitdən gələn dəyər üçün isə yazı
yalnız qeyddir — uğursuzluğu xəbərdarlıqdır.

**Tətbiq:** `shared/installation.py`, `presentation/composition.py`
(`build_context`, `ApplicationContext.self_hosted`, `complete_setup`),
`presentation/app.py` (`StartupRoute`, `_startup_route`),
`application/use_cases/first_run_setup.py` (`TenantProvisioning`, `_provision`),
`infrastructure/persistence/config_repositories.py`
(`PostgresTenantProvisioning`), `tests/unit/test_installation_identity.py`,
`tests/unit/test_first_run_provisioning.py`, `tests/unit/test_startup_route.py`.

---

## Açıq qalan (Faza 3-də bağlanır)

| # | Məsələ | Faza |
|---|---|---|
| 1 | `SET LOCAL app.tenant_id` repozitoriya qatında tətbiq edilməlidir (SEC-008 müqaviləsi) | 3 |
| 2 | `kompasos_app` rolu üçün LOGIN + şifrə deployment skriptində təyin edilməlidir | 3 |
| 3 | Sessiya müddətləri `system_limits`-dən oxunmalıdır (hazırda sənəddə tövsiyə) | 2 |
| 4 | Köhnə Fernet token-lərinin toplu miqrasiyası (`needs_rotation` + `rotate_token`) | 3 |
| 5 | Plugin sandbox-un OS-səviyyəli izolyasiyası (ayrı proses + məhdud hüquq) | 2 |
| 6 | Hüquqi məsləhət: kamera izləmə + cərimə sistemi üçün (bölmə 6 UYĞUNLUQ QEYDİ) | müştəri |
