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

**Vəziyyət:** Qəbul edildi — **TƏTBİQ OLUNUB** (bax aşağıda "FAKTİKİ VƏZİYYƏT
(dövrə 1 audit)" — client-tərəfli uzaqdan-ləğv gecikməsi ilə, CRITICAL deyil)

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

**FAKTİKİ VƏZİYYƏT (dövrə 2/3 audit, SEC-5, 2026-08-19) — TARİXİ QEYD, BU
BOŞLUQ AŞAĞIDAKI "dövrə 1 audit" BƏNDİNDƏ BAĞLANIB, sətir SİLİNMİR ki, tapılma
→ düzəliş zənciri görünsün:** `schema.sql` §17b
`auth_sessions` cədvəlini tam təyin edir, LAKİN heç bir tətbiq qatı ona
YAZMIR — giriş axını (`application/use_cases/authentication.py`) token
yaratmır, `token_hash` yazmır, `expires_at`/`absolute_expiry` yoxlamır.
`presentation/controllers/profile.py:341-420` cədvəldən OXUYUR, amma yazan
tərəf olmadığı üçün istifadəçiyə HƏMİŞƏ boş sessiya siyahısı göstərilir.
Nəticə: yuxarıdakı bütün müddət/ləğv zəmanətləri sənədləşdirilib, LAKİN
işləmir — panel/kamera dashboard sessiyası heç vaxt vaxt bitimi ilə bağlanmır.
Düzəliş SEC-5 iş müqaviləsi ilə (`domain`+`infra`+`ui`) davam edir; bu bənd
kodu yazan agentlər tərəfindən "Tətbiq" sətri ilə YENİLƏNMƏLİDİR.

**FAKTİKİ VƏZİYYƏT (dövrə 1 audit, security, 2026-08-19):** Yuxarıdakı boşluq
BAĞLANDI — `SessionManagementUseCase` (`authentication.py`) indi `issue`/
`validate`/`touch`/`revoke` yazır, `PostgresAuthSessionRepository` DB-yə
bağlanıb, `SessionGuard` (`presentation/controllers/session_guard.py`) client
tərəfini idarə edir. **Qalan, ŞÜURLU məhdudiyyət:** uzaqdan ləğv (`revoke`,
`can_revoke_sessions`) DƏRHAL deyil — subyekt tərəf yalnız növbəti dırnaqlanmış
fəaliyyət callback-ində (`SessionGuard._maybe_touch`, throttle = MAX(60 san.,
hərəkətsizlik pəncərəsinin 1/6-sı; defolt 30 dəq. üçün ~5 dəq.) `validate()`
çağırır və ləğvi öyrənir. Yəni admin sessiyanı uzaqdan bağlasa, subyekt sonrakı
1-5 dəqiqə ərzində panelə davam edə bilər. Bu, PERF-1/2/3 fəlsəfəsi ilə uyğun,
şüurlu trade-off-dur (hər siçan hərəkətində DB gediş-gəlişi UI-1-in düzəltdiyi
donmanı YENİDƏN yaradardı) — CRITICAL deyil, lakin Root panelində "dərhal
bağlanır" gözləntisi YARADILMAMALIDIR; "növbəti fəaliyyətdə bağlanır" düzgün
ifadədir.

**Tətbiq:** `schema.sql` §17b, `src/application/use_cases/authentication.py`
(`SessionManagementUseCase`), `src/infrastructure/persistence/auth_session_repository.py`,
`src/presentation/controllers/session_guard.py`, `src/presentation/app.py`
(`_touch_session`), `migrations/072` (`can_revoke_sessions` + Root limitləri).

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
cavab vaxtı "bu e-poçt sistemdə var/yoxdur" məlumatını sızdırmır.

**SƏNƏD DÜZƏLİŞİ (dövrə 3 audit, 2026-08-19):** Bu bənd əvvəllər "TOTP kod
müqayisəsi `secrets.compare_digest` ilə sabit vaxtlıdır" da deyirdi — həmin
sətir artıq SƏHVDİR: TOTP/2FA SEC-016 ilə TAMAMILƏ ÇIXARILIB (bax SEC-004
LƏĞV qeydi), `totp.py` faylı repoda YOXDUR. Sətir silindi ki, mövcud olmayan
bir qoruma "aktivdir" kimi görünməsin. Qalan iddia (şifrə üçün dummy-hash
sabit vaxt) `hashing.py:486-493`-də TƏSDİQLƏNDİ.

**Tətbiq:** `src/infrastructure/security/hashing.py` (`verify_password`, `_verify`).

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

**DÜZƏLİŞ (dövrə 3 dərin audit, 2026-08-19) — TARİXİ QEYD, BU İKİ BOŞLUQ
DÖVRƏ 1 AUDİTİNDƏ (aşağıya bax) BAĞLANIB, sətir SİLİNMİR ki, tapılma →
düzəliş zənciri görünsün.** O anda yuxarıdakı DÖRD kompensasiya tədbirindən
YALNIZ İKİSİ kodda REAL idi: Argon2id+pepper (SEC-005) və enumeration
qorunması (SEC-014). Qalan İKİSİ (`security_events` qeydiyyatı, sessiya
limitləri) HAZIR DEYİLDİ.

**FAKTİKİ VƏZİYYƏT (dövrə 1 audit, security, 2026-08-19) — QALAN İKİSİ DƏ
İNDİ BAĞLIDIR:**
- `security_events` qeydiyyatı — `FailSoftSecurityEventRecorder.record()`
  (`src/shared/security_events.py`) 11 çağırış nöqtəsində işləyir
  (`authentication.py` ×7 — login uğuru/uğursuzluğu, PIN uğursuzluğu,
  lockout, sessiya issue/revoke/expiry; `dual_control_guard.py` ×2;
  `face_control.py` ×1; `permission_guards.py` ×1). Cədvəl artıq DOLUR.
- sessiya limitləri (SEC-011) — TƏTBİQ OLUNUB (yuxarıda SEC-011 bəndinin
  "dövrə 1 audit" qeydinə bax; qalan yeganə məhdudiyyət uzaqdan-ləğvin
  1-5 dəq. gecikməsidir, CRITICAL deyil).

Yəni 2FA-nın çıxarılmasını əsaslandıran "qalan tədbirlər" siyahısının
DÖRDÜ DƏ indi kodda REAL-dır — dövrə 3-ün qaldırdığı "qərarın əsası
yenidən qiymətləndirilməlidir" narahatlığı bu baxımdan aradan qalxıb.

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

## SEC-022 — Vendor Konsolu tenant-ın OPERATİV datasını GÖRMÜR

**Qərar:** Vendor Konsolu (Developer Paneli) hər kirayəçi üçün YALNIZ
aqreqasiya edilmiş metadata göstərir: şirkət adı, `tenant_id`, Supabase
referansı, ödəniş statusu, aktiv istifadəçi/mağaza/server/cihaz SAYI, açıq
konflikt sayı, son sinxronizasiya anı. İşçi adı, e-poçtu, cərimə sətri,
davamiyyət qeydi — HEÇ BİRİ oxunmur.

**Səbəb:** Vendor bir təchizatçıdır, müştərinin HR şöbəsi deyil. Operativ
dataya çıxış texniki olaraq asandır (bağlantı onsuz da var), lakin o çıxış
bir dəfə açılsa, «dəstək üçün baxdım» ilə «rəqibin məlumatını oxudum»
arasındakı sərhəd yalnız etibar üzərində qalardı. Sərhəd KODDA olmalıdır.

Qapı `DeveloperTenantDirectory.tenant_telemetry()`-nin sorğusundadır: hər
sütun `COUNT(*)` və ya `MAX(timestamp)`-dır. Bir dənə `full_name` sütunu bu
funksiyanı müqavilə pozuntusuna çevirir (bax `docs/contract_notes.md`).

**«Tenant-a qoşul və dəstək göstər» funksiyası İNDİ TİKİLMİR.**

TENANT-1 Faza 3 bu qeydi açıq şəkildə tələb edir. Belə bir funksiya gələcəkdə
lazım olarsa, o, AYRI mexanizm olmalıdır və üç şərti EYNİ ANDA ödəməlidir:

1. **Müştərinin razılığı** — sessiya müştəri tərəfindən AÇIQ başladılır
   (məs. birdəfəlik kod), vendor onu təkbaşına aça bilmir;
2. **Vaxt məhdudiyyəti** — sessiya avtomatik bağlanır, «həmişəlik açıq»
   vəziyyət yoxdur;
3. **Tam audit** — sessiya ərzində oxunan HƏR sətir müştərinin öz
   `audit_logs` cədvəlinə yazılır, yəni müştəri sonradan nəyə baxıldığını
   özü görə bilir.

Bu üç şərtdən biri olmadan funksiya SEC-022-nin özünü ləğv edərdi.

**Tətbiq:** `infrastructure/licensing/developer_directory.py`
(`TenantTelemetry`, `tenant_telemetry`), `tests/unit/test_tenant_isolation.py`.

---

## SEC-023 — Lisenziya sətrini YARATMAQ icazəlidir, DƏYİŞMƏK deyil

**Qərar:** Tətbiq rolu (`kompasos_app`) `license_tenants`-a `INSERT` edə
bilir, lakin YALNIZ iki şərtlə: sətir ONUN öz `tenant_id`-si üçündür və
`license_key_hash` məhz `SELF_HOSTED_NO_LICENSE_KEY` nişanıdır. `UPDATE` və
`DELETE` üçün nə qrant, nə də RLS siyasəti var.

**Səbəb:** Qorunmalı olan zəmanət «müştəri lisenziya sətrini yarada
bilməsin» deyil — «MÖVCUD sətri dəyişə bilməsin»dir. Real yan keçmə
ssenariləri bunlardır: dayandırılmış tenant-ı `AKTIV`-ə qaytarmaq
(`UPDATE`), `expires_at`-i irəli çəkmək (`UPDATE`), bloklanmış sətri silib
yenisini yazmaq (`DELETE`). Üçü də qadağan qalır. Sətrin İLK yaradılması isə
bunların heç biri deyil: o an tenant hələ mövcud deyil, yəni yan keçiləcək
qərar da yoxdur.

İkinci şərt (`license_key_hash` nişanı) daha incə bir şeyi qoruyur: müştəri
vendor tərəfindən verilmiş kimi GÖRÜNƏN sətir uydura bilmir. Nişan
`config_repositories.SELF_HOSTED_LICENSE_MARKER` ilə eyni sətirdir və ikisi
birlikdə dəyişməlidir.

**Qüsur necə tapıldı:** Paketlənmiş `.exe`-də İlk Quraşdırma Sihirbazı son
addımda `InsufficientPrivilege: permission denied for table license_tenants`
ilə dayanırdı — yəni proqram quraşdırıla BİLMİRDİ. Səbəb `CLAUDE.md` §7-dəki
naxışın təkrarı idi: eyni qayda iki yerdə, iki fərqli cavabla.
`schema.sql` §28 yalnız `UPDATE, DELETE` geri alır, miqrasiya 006 isə
`INSERT`-i də geri alırdı. Nəticədə qapı quraşdırma YOLUNDAN asılı idi —
`schema.sql` ilə təmiz baza işləyir, tam miqrasiya zənciri tətbiq olunmuş
baza isə İŞLƏMİRDİ.

Fərq həm də zamanın nəticəsidir: 006 yazılanda yalnız SaaS modeli vardı və
sətri VENDOR yaradırdı. Özünə-host edilən quraşdırmada (`.exe` + müştərinin
öz Supabase layihəsi) belə bir vendor YOXDUR.

**Tətbiq:** `database/migrations/065_self_hosted_tenant_bootstrap.sql`
(qrant + `tenant_bootstraps_own_license` siyasəti),
`infrastructure/persistence/config_repositories.py`
(`SELF_HOSTED_LICENSE_MARKER`, `PostgresTenantProvisioning`),
`tests/unit/test_license_bootstrap_privilege.py`.

---

## SEC-024 — `Root` təchizatçının, `CEO` müştərinin ƏN ÜST pilləsidir

**Qərar:** İlk Quraşdırma Sihirbazı müştəriyə `CEO` hesabı yaradır, `Root`
DEYİL. `Root` pilləsi yalnız təchizatçının öz alətləri ilə (birbaşa baza,
`scripts/`) qurulur və müştəri quraşdırmasından ona yol yoxdur. CEO-nun nə
edib-edə bilməyəcəyi isə Root panelindən idarə olunur.

**Səbəb:** Əvvəl sihirbaz `Root` yaradırdı və nəticə iyerarxiyanın öz mənasını
pozurdu: müştərinin ən üst hesabı təchizatçının pilləsində olurdu, yəni
lisenziya, vendor telemetriyası və `ROOT_ONLY` hardlock-u ilə qorunan hər şey
onun əlinin altında qalırdı. Üstəlik «CEO Root-un icazə matrisini dəyişə
bilir» qüsuru məhz buradan gəlirdi — ikisi EYNİ pillədə idi və
`Position.outranks()` bərabər pillələr arasında fərq görmür.

İndi `RolePriority.ROOT = 0` `EXECUTIVE = 1`-dən CİDDİ ŞƏKİLDƏ yuxarıdır və
qayda iyerarxiyanın TƏBİİ NƏTİCƏSİDİR, əlavə qapının yan təsiri deyil.

**Tətbiq:** `application/use_cases/first_run_setup.py` (`SystemRole.CEO`),
`domain/entities/position.py` (`may_be_edited_by`),
`application/use_cases/position_management.py`,
`scripts/create_root_account.py` (təchizatçının hesabını yaradan YEGANƏ yol),
`tests/unit/test_root_ceo_separation.py`,
`tests/unit/test_employee_creation_path.py`.

**SONRAKI DÜZƏLİŞ (SETUP-3).** Qərarın bir nəticəsi ilk buraxılışda
gözdən qaçmışdı: `first_run_setup.is_required()` «tenant sahibsizdirmi?»
sualını `can_manage_license` flag-ini daşıyan hesabların sayı ilə
cavablandırırdı. Həmin flag səviyyə-1 hardlock-dur, yəni YALNIZ `Root`-a
verilir — sihirbaz isə artıq `CEO` yaradırdı. Nəticədə sayğac quraşdırma
uğurla bitdikdən SONRA da sıfır qalırdı: proqram hər açılışda sihirbazı
yenidən göstərirdi və istifadəçi öz hesabına heç vaxt çata bilmirdi.

Sayğac indi İYERARXİYA PİLLƏSİ ilə işləyir
(`EmployeeRepository.count_active_ranked_at_or_above`, `RolePriority.EXECUTIVE`
və ondan yuxarı). Pillə sualın təbii ölçüsüdür və Root-un flag
konfiqurasiyasından asılı deyil — custom rol da düzgün sayılır.
Qapı: `tests/unit/test_setup_completion_gate.py`.

---

## SEC-025 — Tenant-ın YEGANƏ admini öz üzünü qeydiyyata sala bilər

**Qərar:** `FaceEnrollmentUseCase.enroll_first_account()` aktorun ÖZ üzünü
qeydiyyata salmasına icazə verir — LAKİN yalnız `can_manage_employees` daşıyan
aktiv hesabların sayı **1-dən çox olmadıqda**. Adi `enroll()` yolu
dəyişməyib: orada `assert_may_enroll` özünə-qeydiyyatı qadağan etməyə davam
edir. Audit yazısı da ayrıdır — `FACE_ENROLLED_BOOTSTRAP`.

**Səbəb:** `facecontrol.md` bənd 1 üz qeydiyyatını NƏZARƏTLİ proses sayır:
nəzarətsiz qeydiyyatda işçi istənilən üzü öz hesabına bağlaya bilər. Lakin
İlk Quraşdırma Sihirbazında bu qayda ÖDƏNİLƏ BİLMƏZ — tenant-da yeganə hesab
elə CEO-nun özüdür, yəni nəzarət edəcək ikinci admin fiziki olaraq yoxdur.
Qaydanı olduğu kimi saxlasaydıq, CEO-nun üzü heç vaxt qeydiyyata düşməzdi:
qayda öz məqsədini deyil, yalnız formasını qorumuş olardı.

İstisnanın şərti ADA GÖRƏ deyil, FAKTA GÖRƏDİR. «Bu, ilk hesabdırmı?» sualı
bayraq tələb edərdi və bayraq təmizlənməsə istisna sonsuza qədər açıq
qalardı. «Nəzarət mümkündürmü?» sualı isə sayğacla ölçülür — ikinci admin
yarandığı an yol ÖZ-ÖZÜNƏ bağlanır.

Sayğac qoşulmayıbsa yol FAIL-CLOSED bağlanır: fail-open olsaydı,
`composition.py`-da bir sətrin unudulması istisnanı hər hesaba açardı və bunu
heç bir xəta göstərməzdi.

**Tətbiq:** `application/use_cases/face_control.py` (`AdminCounter`,
`enroll_first_account`), `presentation/controllers/face_setup.py`,
`presentation/screens/face_control.py` (`FaceSetupRequiredScreen`),
`presentation/composition.py` (`admins=repo("employees")`),
`tests/unit/test_face_setup_flow.py`.

---

## SEC-026 — Panel girişində üz ŞİFRƏNİ əvəz edir; `NOT_APPLICABLE` giriş VERMİR

**Qərar:** `AdminLoginScreen`-dəki «Üzlə daxil ol» düyməsi istifadəçi adı +
1:1 üz doğrulaması ilə işləyir (1:N tanıma DEYİL). Giriş YALNIZ `ALLOWED` və
`ALLOWED_LOW_CONFIDENCE` nəticələrində verilir; `NOT_APPLICABLE` daxil olmaqla
qalan hər şey istifadəçini şifrə sahəsinə qaytarır. `assert_admin_login_
allowed()` və `must_change_password` qapıları təkrarlanır, audit isə
`ADMIN_LOGIN` + `method="FACE"` kimi yazılır.

**Səbəb (iki ayrı qərar):**

1. **Niyə 1:1, kioskdakı kimi 1:N deyil.** Kiosk PC-si bir mağazaya bağlıdır
   (`KOMPASOS_STORE_ID`) və `identify_for_login` axtarışı həmin mağaza ilə
   məhdudlaşdırır — çünki namizəd sayı artdıqca «ən yaxın qonşu» təsadüfən
   yaxın düşə bilər. Panel maşınının mağazası yoxdur, yəni eyni yol bütün
   şəbəkə üzrə gedərdi. Panel girişi isə cərimə kəsmək, icazə təsdiqləmək və
   səlahiyyət dəyişmək deməkdir: ən riskli tanıma üsulunu ən səlahiyyətli
   qapıya qoymaq olmazdı.

2. **Niyə `NOT_APPLICABLE` giriş vermir.** Kioskda üz qapısı PIN-dən SONRA
   işləyir, yəni İKİNCİ amildir — modul söndürüldükdə və ya mağaza pilot
   əhatəsindən kənarda olduqda axının «yalnız PIN» rejiminə düşməsi doğrudur,
   birinci amil onsuz da yoxlanılıb. Panel girişində isə üz TƏK amildir. Eyni
   yumşalmanı təkrarlasaydıq, modulu bağlı kirayəçidə istifadəçi adını yazıb
   düyməni basmaq panelə girmək üçün kifayət edərdi — şifrə sükutla ləğv
   olardı.

Düymənin görünmə şərti də kioskdan fərqlidir: burada kamera cihazı AÇILMIR,
yalnız modul açarı və `cv2` kitabxanası soruşulur. Kiosk `is_available()`
çağırır və o, cihazı faktiki olaraq tutur; panel maşınında eyni çağırış hər
idarəçinin veb-kamerasını proqram açıq olduğu müddətcə tutulu saxlayardı —
halbuki düymə burada alternativdir və şifrə sahəsi elə yanındadır.

**Tətbiq:** `presentation/controllers/face_login.py` (`GRANTING_OUTCOMES`),
`presentation/screens/group_a_entry.py` (`face_login_requested`),
`presentation/app.py` (`_on_face_login_requested`),
`tests/unit/test_face_login_screen.py`.

---

## SEC-027 — Smart App Control: imzanın MÖVCUDLUĞU kifayət etmir

**Vəziyyət:** Qəbul edildi — **developer maşınında ölçülüb**

**Problem.** SEC-012 «imzasız istehsalat buraxılışı qadağandır» deyir və CI
həmin qapını saxlayır. Bu, ZƏRURİ, lakin KİFAYƏT DEYİL. Windows 11-in Smart
App Control (SAC) mexanizmi Authenticode imzasının mövcudluğuna deyil,
imzalayanın REPUTASİYASINA baxır.

Ölçmə (18.08.2026, Windows 11 Pro 26200):

```
HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy
  VerifiedAndReputablePolicyState = 1        ← məcburi rejim

CodeIntegrity/Operational
  3118  Smart App Control Block Details
  3077  ...attempted to load ...\dist\KompasOS.exe

Get-AuthenticodeSignature dist\KompasOS.exe → NotSigned
```

`.exe` ümumiyyətlə YÜKLƏNMİR (exit 126) — nə `Start-Process`-dan, nə
Explorer-dən. Bu, antivirus və ya icazə problemi deyil: Code Integrity
qatıdır və istifadəçiyə «davam et» seçimi TƏKLİF ETMİR.

**Niyə bu, developer maşınının yox, MÜŞTƏRİNİN problemidir.** SAC Windows
11-in TƏMİZ quraşdırmalarında defolt açıqdır və mağaza PC-ləri məhz belə
gəlir. İmzalanmış, lakin reputasiyası hələ toplanmamış `.exe` müştərilərin
bir hissəsində sadəcə açılmayacaq — heç bir izah, heç bir jurnal olmadan.
Şikayət «proqram işləmir» kimi gələcək və səbəbi uzaqdan görünməyəcək.

**Qərar.** Paylanan `.exe` üçün **EV (Extended Validation) sertifikatı**
tələb olunur. Adi OV sertifikatı SEC-012 qapısını keçir, lakin SAC üçün
kifayət etmir: reputasiya buraxılış sayı və yayılma ilə TOPLANIR, yəni ilk
müştərilər blok altında qalır — məhz pilot quraşdırmalar.

| Alternativ | Niyə rədd edildi |
|---|---|
| Özü-imzalı sertifikat | SAC etibar zəncirinə baxır; özü-imzalı kök müştəri maşınında yoxdur |
| «Müştəri SAC-ı söndürsün» | Söndürmə BİR YÖNLÜDÜR — geri qaytarmaq üçün Windows-un təmiz quraşdırılması lazımdır. Quraşdırma təlimatında belə addım tələb etmək olmaz |
| Defender istisnası (`Add-MpPreference`) | SAC ayrı qatdır və Defender istisnalarına tabe deyil |
| İmzasız paylamaq | SEC-012 |

**Lokal build imzasızdır və bu QƏSDƏNDİR.** Sertifikat yalnız CI-nin
`production` mühitindədir (`CODE_SIGNING_CERT_BASE64`); developer maşınında
imzalama sirri SAXLANMIR — saxlansaydı, sirrin surəti hər developer PC-sinə
düşərdi. Deməli `dist\KompasOS.exe`-ni SAC açıq maşında lokal işə salmaq
MÜMKÜN DEYİL və bu, qüsur DEYİL. Lokal yoxlama mənbədən aparılır:
`scripts/dev_panel.py` və ya `python -m src.main`.

**Satınalmadan əvvəl təsdiqlənməli.** EV sertifikatının SAC-da DƏRHAL etibar
verməsi vendorun öz sənədində yazılı olmalıdır — bu qərar ölçülmüş faktdan
(yuxarıdakı bloklama) və sertifikat siniflərinin bəyan edilmiş davranışından
çıxarılıb, vendor sınağından YOX.

**Tətbiq:** `.github/workflows/ci.yml` (`production-release`), SEC-012.

---

## SEC-028 — Daxili müraciət hazırlayıcının Telegram-ına DÜŞMÜR

**Qərar:** Dəstək chat-i iki kanala bölünür (`support_tickets.channel`) və
Telegram-a YALNIZ `TECHNICAL` kanalı çıxır.

**Səbəb — bu, funksional seçim deyil, MƏLUMAT SIZMASININ qapadılmasıdır.**
Əvvəlki quruluşda dəstək chat-inin tək ünvanı vardı: hazırlayıcı. Nəticədə
«məzuniyyətim təsdiqlənmir», «cəriməmi haqsız yazıblar» kimi mesajlar —
şirkətin DAXİLİ kadr yazışması — kənar tərəfin qutusuna düşürdü. Telegram
əlavə olunsaydı, həmin mətn üstəlik kənar şəxsin TELEFONUNDA olardı.

**Qayda İKİ yerdədir** (CLAUDE.md §5):

| Yer | Nə edir |
|---|---|
| `SupportChannel.notifies_telegram` | Tərif — yalnız `TECHNICAL` `True` qaytarır |
| `_SupportBase._should_notify` | Tətbiq — şlüzə çağırış bu qapıdan keçir |

Üçüncü qat kimi `SupportInboxUseCase.deliver_telegram_reply` GƏLƏN cavabı da
yoxlayır: daxili kanalın söhbətinə Telegram-dan yazılan cavab RƏDD edilir,
çünki belə bir istinad yalnız səhv və ya uydurma ola bilər.

**Kanal AVTOMATİK təyin edilmir.** Açar sözlə təsnifat («cərimə» → daxili)
rədd edildi: səhv təsnifat mesajı yanlış auditoriyaya çatdırardı və işçi
bunu görməzdi. Seçim işçinin bir klikidir (`value_objects/support.py`).

**Tətbiq:** `migrations/068`, `src/domain/value_objects/support.py`,
`src/application/use_cases/support_chat.py`.

---

## SEC-029 — Telegram bot token bazadadır, `.env`-də DEYİL; ekrana AÇILMIR

**Qərar:** `telegram_config.bot_token_encrypted` — `EncryptionService`
(AES-256-GCM) ilə, AAD kimi `telegram_config:{tenant_id}` konteksti ilə.
Ekran yalnız MASKANI görür (`mask_token`, son 4 simvol).

**Niyə `.env` deyil.** Token-i dəyişmək müştəri ofisindəki istifadəçinin
işidir; o isə `Program Files` altındakı mətn faylını redaktə edə bilmir
(SETUP-1) və etməli də deyil. Bazadakı dəyər üstəlik AUDİT-lənir — fayl iz
qoymur. CHAT-1 bunu açıq tələb edir.

**Niyə AAD konteksti.** Kontekstsiz şifrələmə bir kirayəçinin token sətrinin
digərinin sətrinə köçürülməsini SÜKUTLA qəbul edərdi (baza faylına birbaşa
çıxışı olan hücumçu üçün mümkün əməliyyat). Kontekstlə deşifrə mərhələsində
uğursuz olur.

**Niyə ekrana qaytarılmır.** Root paneli demo, ekran-paylaşımı və uzaqdan
dəstək zamanı açıq olur. Token yalnız YAZILIR («Botu Dəyiş») və yalnız şlüz
tərəfindən oxunur; audit sətrində də yalnız maska saxlanılır — audit jurnalı
ixrac edilə bilir və sirri ora yazmaq onu şifrəli sütundan çıxarardı.

**Səlahiyyət qapısı İKİ yerdədir:** `permission_flags.hardlock_level = 1`
(DB, migrations/068) və `TelegramConfigUseCase.may_manage` (rol yoxlaması) —
`schema.sql` ilə təmiz quraşdırmada miqrasiya zənciri fərqli ola bilər.

**Köhnə token silinmir, ARXİVLƏNİR** (`telegram_config_history`): «hansı bot
nə vaxt işləyirdi?» sualı bot dəyişdikdən sonra cavabsız qalmamalıdır.

**Tətbiq:** `migrations/068`, `src/application/use_cases/telegram_config.py`,
`src/infrastructure/persistence/telegram_repositories.py`.

---

## SEC-030 — Təchizatçının `Root` hesabı YALNIZ əmr sətri aləti ilə yaradılır

**Qərar:** `Root` hesabı `scripts/create_root_account.py` ilə yaradılır. Skript
`.exe`-yə PAKETLƏNMİR, şifrəni əmr sətri arqumenti kimi QƏBUL ETMİR (gizli
soruşulur) və mövcud aktiv `Root` varsa `--force` olmadan DAYANIR.

**Səbəb:** SEC-024 `Root` ilə `CEO`-nu ayırdı, lakin `Root`-u YARADAN yol heç
vaxt yazılmamışdı. `first_run_setup.py` şərhi «təchizatçı öz hesabını
`scripts/onboard_new_tenant.py` ilə açır» deyirdi — həmin skript isə kimlik,
sxem və seed qurur, İŞÇİ YARATMIR. Strict Hierarchy Guard-a görə `CEO` özündən
yuxarı hesab yarada bilmədiyindən panelin içindən də yol yox idi. Nəticədə
ROOT İdarə Mərkəzi, «Texniki Dəstək» kanalı, Telegram ayarları, bərpa konsolu
və plugin idarəsi ƏLÇATMAZ qalırdı.

Sihirbaza addım əlavə etmək RƏDD EDİLDİ: sihirbaz müştərinin əlindədir və orada
`Root` yaratmaq SEC-024-ün ayırdığı iki pilləni yenidən birləşdirərdi.

**Yazma yolu tətbiqin ÖZ yolu ilə eynidir:** skript RLS altında (`kompasos_app`
rolu ilə) yazır və owner DSN-i qəsdən kənarlaşdırır — əks halda RLS siyasətinin
həmin sətri qəbul edib-etmədiyi heç vaxt sınanmazdı və qüsur yalnız müştəri
maşınında üzə çıxardı. Kirayəçi kimliyi `resolve_installation_identity()`-dən
gəlir, `license_tenants` cədvəlindən DEYİL: həmin cədvəl RLS altında tətbiq
roluna görünmür və inkişaf maşınındakı `DATABASE_ADMIN_URL` bu fərqi gizlədirdi.

**Tətbiq:** `scripts/create_root_account.py`, `tests/unit/test_packaging_credentials.py`.

---

## SEC-031 — Tema keçidi giriş-ÖNCƏSİ ekranlara da çatmalıdır (THEME-1)

**Qərar:** `FramelessWindow.apply_theme()` cari məzmun widget-inə `apply_theme`
ötürür. Müqavilə İSTƏYƏ BAĞLIDIR: metod varsa çağırılır.

**Səbəb:** Tema keçidi əvvəl yalnız pəncərə örtüyünə və `AdminShell`-ə çatırdı.
Sihirbaz, giriş, bağlantı və fatal ekran isə örtükdən KƏNARDA yaşayır və
rənglərinin bir hissəsini `setStyleSheet` ilə qurulma anında hesablayır.
Nəticədə QSS-dən gələn fon yeni temaya keçir, sətir-içi mətn rəngi köhnəsində
qalırdı — istifadəçinin bildirdiyi «boxlar ağarır və fontlar görsənmir».

Rəngləri tamamilə QSS-ə köçürmək rədd edildi: sihirbazın sol paneli və xəta
zolağı yalnız orada işlənən token cütlərindən qurulub və hər biri üçün qlobal
selektor yaratmaq QSS-i ekranın daxili quruluşuna bağlayardı.

**Tətbiq:** `presentation/shell/window.py`, `presentation/screens/group_a_entry.py`,
`presentation/shell/admin_shell.py`, `tests/unit/test_theme_switch_prelogin.py`.

---

## SEC-032 — Bərpa Konsolu bypass-ı: deşifrə orakulu riski (dövrə 1 audit, RECOVERY-1/"SEC-2")

**Vəziyyət:** Qəbul edildi — düzəliş `ui` tərəfindən icra olunur (Qayda A + Qayda B)

**Problem.** `recovery_console.may_open()` `Ctrl+Shift+K` qapısını `configured=True`
maşında `actor=None` ikən DƏ açır — YALNIZ `DATABASE_UNREACHABLE`/
`CREDENTIALS_MISSING` hallarında (toyuq-yumurta arqumenti: baza əlçatmazdırsa
səlahiyyət ümumiyyətlə yoxlana bilmir). Bu qapının ARXASINDAKI əməliyyatlar
İSƏ əvvəllər YALNIZ autentifikasiyalı `Root` üçün nəzərdə tutulmuşdu və audit
zamanı YENİDƏN gözdən keçirilmədi.

`RecoveryConsoleController._settings_from()` ekranın boş `password` sahəsini
"dəyişmə" kimi oxuyub `connection_file.load_settings()`-in DEŞİFRƏ ETDİYİ
(DPAPI maşın açarı ilə şifrələnmiş) **istehsalat DB parolunu** geri qaytarır —
`host`/`port`/`username` isə İSTİFADƏÇİNİN yazdığı sərbəst dəyərdir. Nəticə:
`_on_test`/`_on_check`/`_on_provision` (hətta `_on_save`) bu parolu
`ConnectionSettings.dsn()` üzərindən İXTİYARİ hosta göndərir. **Deşifrə
orakulu:** DB kabelini çıxarmaq/kimlikləri korlamaq kifayətdir ki, fiziki
girişi olan hər kəs autentifikasiyasız şəkildə konsolu açsın, `host` sahəsinə
öz serverini yazsın, parolu boş buraxsın və "Bağlantını Yoxla" ilə istehsalat
DB parolunu açıq mətnlə öz serverinə göndərsin.

**Qərar — İKİ QAYDA birlikdə (biri təkbaşına kifayət etmir):**

* **Qayda A** — saxlanmış parol YALNIZ `host`/`port`/`username` DƏYİŞMƏYİBSƏ
  bərpa edilir; dəyişibsə boş sahə "sil" deyil, "parolu AÇIQ yaz" tələbinə
  çevrilir.
* **Qayda B** — Qayda A TƏK BAŞINA YETƏRLİ DEYİL: `installer/KompasOS.iss:127`
  `%PROGRAMDATA%\KompasOS`-a `Permissions: users-modify` verir (QƏSDƏN —
  paylaşılan kassa PC-sində kassir B-nin proqramı kassir A-nın yazdığı
  `connection.json`-u yeniləyə bilməsi üçün, bax faylın öz şərhi). Yəni adi
  istifadəçi hüquqlu hücumçu `connection.json`-un `host` sahəsini əl ilə (GUI-
  dan kənar) redaktə edib öz serverinə yönəldə, `password_encrypted`-ə
  TOXUNMADAN — konsol açılanda Qayda A-nın müqayisəsi "eyni hədəf" görər və
  keçər. Ona görə: **konsol `actor=None` bypass-ı ilə açılıbsa, saxlanmış
  parol HEÇ VAXT deşifrə edilmir** — nə test/check/provision, nə də save
  üçün (gecikdirilmiş sızmanın qarşısı: host dəyişib parolu saxlayan bir
  `save` növbəti açılışda tətbiqi hücumçunun serverinə bağlayardı).
  Autentifikasiyalı `Root` üçün "boş = dəyişmə" erqonomikası TOXUNULMADAN
  qalır — Qayda B YALNIZ `actor is None` yolunu əhatə edir.

**AÇIQ SUAL (bu dövrədə HƏLL EDİLMİR, bax `docs/open_questions.md` OQ-003):**
`ConnectionSettings.dsn()` defolt `sslmode=require` işlədir — bu, nəqliyyatı
şifrələyir, LAKİN server sertifikatını DOĞRULAMIR (`verify-full` DEYİL).
Yəni Qayda A/B-dən ASILI OLMAYARAQ, `_on_test` kimi əməliyyatlar TLS-in
özü ilə "bu, HƏQİQƏTƏN bizim serverimizdir" iddiasını yoxlamır — TLS yalnız
dinləyicini pasiv dinləməkdən qoruyur, saxta serverdən YOX. `verify-full`-a
keçid (kök sertifikat idarəsi, quraşdırma mürəkkəbliyi) ayrıca qərar tələb
edir.

**Tətbiq:** `src/presentation/controllers/recovery_console.py`
(`_settings_from`, `_on_test`/`_on_check`/`_on_provision`/`_on_save`),
`installer/KompasOS.iss:127` (ACL-in ÖZÜ QALIR — layihənin şüurlu qərarıdır,
yalnız üzərinə Qayda A/B əlavə olunur).

---

## SEC-033 — Kiosk PIN throttle-u `store_id`-ə YOX, `machine_guid` hash-inə bağlanır (dövrə 3 audit, SEC-01/SEC-05)

**Vəziyyət:** Qəbul edildi — kod YAZILIR (dövrə 3, `domain`+`infra`)

**Problem — SEC-01: PIN lockout mövcud deyildi.** `PinHandshakeUseCase.
register_failure()` heç bir kontroller tərəfindən çağırılmırdı (yalnız
testlərdən) — PIN brute-force MƏHDUDLAŞDIRILMIRDI. Struktur səbəb: PIN
mağaza-daxili bütün namizədlər üzərində sınanır (bölmə 2-nin "PIN özü
identifikator deyil" qərarı), yəni yanlış cəhddə HANSI İŞÇİNİN bloklanacağı
sualının cavabı YOXDUR — işçi-səviyyəli lockout bura tətbiq oluna BİLMƏZ.
Həll TERMİNAL/MAĞAZA-səviyyəli throttle olmalı idi.

**[SEC-05] — `store_id` açar KİMİ RƏDD EDİLDİ.** İlk dizayn `store_pin_
throttle` cədvəlinin PK-sini `(tenant_id, store_id)` təklif edirdi. Audit
zamanı üzə çıxdı ki, kiosk-un `store_id`-si YALNIZ `KOMPASOS_STORE_ID`
mühit dəyişənindən gəlir (`.env.example`, `presentation/app.py::
_build_kiosk_controller`) və HEÇ BİR DB-bağlı yoxlamadan (device_registry,
aparat izi) keçmir. İstehsalatda `.env` faylı OLMAMALIDIR (`main.py::
_check_dotenv` bunu yoxlayır) — yəni dəyər İSTİFADƏÇİ-SƏVİYYƏLİ Windows
mühit dəyişəni (`HKCU\Environment`) kimi saxlanılmalıdır, bu isə ADMİN
HÜQUQU TƏLƏB ETMİR. Nəticə: fiziki/yerli girişi olan hücumçu `KOMPASOS_
STORE_ID`-i istənilən UUID-ə dəyişib tətbiqi YENİDƏN başlada bilər (reboot
LAZIM DEYİL) və throttle cədvəlində HƏR DƏFƏ sıfır-sayğaclı YENİ sətir alar
— `store_id`-ə bağlı throttle PRAKTİKİ SIFIR qoruma verirdi.

**Niyə `device_id` DƏ rədd edildi.** Alternativ namizəd `device.json`-dakı
`device_id` UUID-i idi (DEVICE-1). CLAUDE.md §8-in özü təsdiqləyir: "silinsə
cihaz YENİ qeydiyyat yaradır" — yəni `device_registry.register_self()`
`device_id is None` olanda (fayl silinəndə) FİNGERPRINT-ə görə mövcud sətri
AXTARMADAN birbaşa YENİ təsadüfi `device_id` yaradır
(`device_registry.py:198`). `device_id` `store_id` qədər asan olmasa da,
EYNİ sinif zəiflik daşıyır: bir faylın silinməsi qədər ucuz sıfırlama.

**Qərar — `machine_guid` (SHA-256 hash-i) açar, `store_id` YALNIZ
məlumat sütunu.**

* `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography\MachineGuid`
  (`device_identity.py`) — registry-dən, subprocess-siz, ~0.5 ms (hər PIN
  cəhdində oxumaq UCUZDUR) və **`HKLM`-dədir** — dəyişmək üçün Windows
  ADMİN hüququ tələb olunur, sadə istifadəçi sessiyasından mümkün deyil.
  Ucuzluq və müqavimət eyni anda təmin olunur.
* TAM `collect_fingerprint()` (anakart/disk/SMBIOS seriyaları,
  `HARDWARE_PROBE_TIMEOUT_SECONDS=8.0`) İŞLƏDİLMİR — hər PIN cəhdi üçün
  8 saniyəyə qədər gecikmə YARARSIZ olardı; `machine_guid` TƏK BAŞINA
  "izin lövbəri" kimi kifayət edir (bax `device_identity.py`-nin öz
  başlığı: bu, kimlik deyil, dəyişiklik detektorudur).
* Dəyər XAM saxlanmır, SHA-256 HASH-İ saxlanılır — cədvəl aparat
  inventarına çevrilməsin.
* `store_id` PK-DAN ÇIXARILDI, sütun kimi QALIR (yalnız diaqnostika/audit
  üçün) — SEC-05-in özünü təkrarlamamaq üçün açarın hissəsi OLA BİLMƏZ.

**QƏBUL EDİLƏN RESİDUAL RİSK — klonlanmış disk/VM imici toqquşması.**
`MachineGuid` Windows QURULUŞU zamanı yaranır və DİSK KLONLAMASINDA
(Clonezilla/FOG/VM template, `sysprep /generalize` İCRA EDİLMƏYİBSƏ)
SÜRƏTLƏ eyni qalır — bir neçə fiziki/virtual maşın EYNİ dəyəri daşıya
bilər. `store_id` açardan çıxarıldığı üçün belə bir toqquşmada BİRDƏN ÇOX
mağaza EYNİ throttle sətrini PAYLAŞAR:

* **Öz-özünə DoS:** klonlanmış mağazalarda EYNİ ANDA baş verən tamamilə
  qanuni, ünsiyyətsiz PIN səhvləri BİRLƏŞİB həddi hücumçusuz keçə bilər.
* **Gücləndirilmiş hücum:** bir mağazada bilərəkdən brute-force digər
  bütün klonlanmış mağazaları da kilidləyər — tək-nöqtəli fiziki giriş
  çox-nöqtəli kəsintiyə çevrilir.
* **MƏHDUDLAŞDIRICI AMİL (nəticəni yumşaldır):** kilid MÜDDƏTLİDİR
  (`locked_until = now + KIOSK_STORE_PIN_LOCKOUT_MINUTES`, defolt 15 dəq) və
  öz-özünə sağalır — ən pis nəticə "N mağaza 15 dəqiqə PIN girişindən
  məhrum qalır", DAİMİ kəsinti DEYİL. Orijinal vəziyyətdə (SEC-01-dən
  ƏVVƏL) qoruma AYLARLA yox idi; bu residual isə FƏRQLİ və MƏHDUD bir
  nasazlıq rejimidir, "daha pis" deyil.

**Yumşaltma (bloklayıcı deyil, iki qatlı):**
1. **Sənəd/operativ tədbir** — çox-mağazalı müştəri eyni Windows imicini
   klonlayırsa `sysprep /generalize /oobe` (və ya ekvivalent) MƏCBURİDİR;
   bu, quraşdırma sənədinə (`docs/build_and_release.md`, `infra`) əlavə
   olunur.
2. **Aşkarlama** — `store_pin_throttle` repozitoriyası cari sətirdəki
   SAXLANMIŞ `store_id`-i qaytarır, use case (DOMEN QATI, repo YOX — DB
   yazısı domen hadisəsi deyil) onu İNDİKİ `store_id` ilə müqayisə edir;
   fərqlidirsə `security_events`-ə `SUSPECTED_CLONED_MACHINE_GUID` yazılır
   və sətir yenilənir. Məqsəd: toqquşma SÜKUTLA baş verməsin — SEC-01-in
   ÖZÜNÜN dərsi ("sükutla söndürülmüş qoruma aylarla görünmür") burada
   TƏKRARLANMASIN.

**NİYƏ `store_id` GERİ AÇARA QAYTARILMADI:** bu, SEC-05-i BİRBAŞA yenidən
açardı — hücumçu yenidən `store_id`-i dəyişməklə qaça bilərdi. İki risk
arasında (trivial sıfırlama vs. məhdud-müddətli klon-toqquşması) `machine_
guid`-in tərəfi seçildi.

**Tətbiq:** `src/infrastructure/config/device_identity.py`
(`compute_machine_guid_hash` və ya ekvivalent), yeni `store_pin_throttle`
cədvəli (`database/migrations/`, `infra`), `PinHandshakeUseCase`
(`domain`), `docs/build_and_release.md` (`infra`, sysprep tələbi).

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
| 7 | EV kod imzalama sertifikatının alınması — onsuz `production-release` SEC-012 qapısında dayanır (SEC-027) | müştəri |
