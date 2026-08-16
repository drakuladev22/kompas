# Komanda Sətri (CLI) Arayışı

`python -m src.main` (mənbədən) / `KompasOS.exe` (paketlənmiş) **23 bayraq**
qəbul edir. Bunların bir hissəsi zərərsiz diaqnostikadır, bir hissəsi isə
müştəri bazasına yazır — o cümlədən **`--recover-access`**, yəni sənədsiz
qalması qəbuledilməz olan bir inzibati giriş yolu.

Bu sənəd həmin boşluğu bağlayır. Mənbə: `src/main.py` (`main()`, sətir 573–770)
və `src/developer_panel/console.py`.

> **Niyə ayrıca sənəd:** bayraqların `--help` mətni bir sətirdir və «nə edir»
> sualına cavab verir. Sistem administratorunun sualı isə başqadır: *kim işlədə
> bilər, nəyi dəyişir, iz qalırmı, geri qaytarmaq mümkündürmü.* Bu suallara
> `--help` cavab verə bilməz — cavab kodun içindədir və buraya çıxarılıb.

---

## 1. Tam siyahı

Sütunların mənası: **Dəyişdirir?** = müştəri bazasına yazır (⚠️) yoxsa yalnız
oxuyur (✓). **Audit izi** = əməliyyatdan sonra hansı jurnalda sətir qalır.

### 1.1. İşə düşmə rejimləri

| Bayraq | Arqument | Nə edir | Kim işlədə bilər | Dəyişdirir? | Audit izi |
|---|---|---|---|---|---|
| `--check` | — | Yalnız özünü-yoxlama işlədir (Saga reyestri, Event Bus, şifrələmə round-trip, pepper, sxem faylı, miqrasiyalar, `.env`). Mənbədən icrada **defolt yol** budur | Hər kəs (baza tələb olunmur) | ✓ yalnız oxu | `SELF_CHECK_ITEM` / `SELF_CHECK_PASSED` (log faylı) |
| `--strict` | — | Eyni yoxlama, lakin **xəbərdarlıqlar da xəta sayılır**. İstehsalat buraxılışı üçün: `KOMPASOS_FERNET_KEY`/`KOMPASOS_HASH_PEPPER` yoxdursa çıxış kodu 1 olur | Hər kəs | ✓ | eyni |
| `--gui` | — | Əsas interfeysi açır. `--developer-mode` ilə birlikdə verildikdə Developer Panelinin **pəncərə** variantını açır (ayrıca bayraq yaradılmayıb) | Hər kəs — daxildə istifadəçi girişi tələb olunur | ⚠️ istifadəçinin öz əməliyyatları qədər | tətbiqin normal auditi |
| `--kiosk` | — | Tam ekran PIN klaviaturası rejimi (mağaza terminalı) | Hər kəs | ⚠️ eyni | eyni |
| `--watchdog` | — | Nəzarətçi prosesi: interfeysi ÖZÜ açmır, `--gui --kiosk` ilə alt-proses yaradır və çökmə halında yenidən başladır. Ayrı proses olması məcburidir — çökən proses artıq kod icra etmir | Mağaza PC-sinin işə düşmə skripti | ✓ (özü) | `KIOSK_WATCHDOG_FINISHED` |
| `--preview` | — | Ekranları maketdəki nümunə məzmunla doldurur. **Baza LAZIM DEYİL** — dizayn yoxlaması və CI-dakı Qt testləri bu yolla işləyir | Dizayner / CI | ✓ heç nəyə toxunmur | yoxdur |
| `--run-scheduled-jobs` | — | Planlaşdırılmış fon işlərini **bir dəfə icra edir və çıxır**. Başsız; **AĞIR işlər daxil** (`pg_dump` gecəlik ehtiyat nüsxəsi) — GUI taymeri onları atlayır, çünki interfeysi dəqiqələrlə dondurardılar | Windows Task Scheduler (bax `docs/scheduler_setup.md`, Variant C) | ⚠️ **BƏLİ** — nüsxə yazır, yenidən hesablayır, bildiriş göndərir | hər işin `scheduled_job_runs` sətri + `SCHEDULED_JOBS_CLI_FINISHED` |
| `--theme` | `light`\|`dark`\|`system` | İşə düşmə teması (defolt `system`). `--watchdog` onu alt-prosesə ötürür | Hər kəs | ✓ | yoxdur |
| `--log-dir` | `YOL` | Log qovluğu. Verilməzsə `configure_logging` öz defoltunu seçir | Hər kəs | ✓ | yoxdur |

### 1.2. Developer Paneli — yalnız oxuyanlar

**Hamısı `--developer-mode` tələb edir** (bax §2). Bunlar müştəri bazasına
YAZMIR, lisenziya bazasından oxuyur.

| Bayraq | Arqument | Nə edir | Kim işlədə bilər | Dəyişdirir? | Audit izi |
|---|---|---|---|---|---|
| `--developer-mode` | — | Developer Panelini açır. **Bayraq TƏK BAŞINA kifayət etmir** — §2-yə bax | Hazırlayıcı (öz mühitində) | ✓ | `PUBLISHER_NOT_CONFIGURED` (yalnız konfiqurasiya jurnalı) |
| `--search` | `MƏTN` | Müştəri cədvəlini ad/e-poçt üzrə süzür | eyni | ✓ | yoxdur |
| `--crashes` | — | Anonim çökmə hesabatları, tezliyə görə qruplaşdırılmış | eyni | ✓ | yoxdur |
| `--tickets` | — | Dəstək müraciətləri inbox-u (SLA vəziyyəti ilə) | eyni | ✓ | yoxdur |

### 1.3. Developer Paneli — DƏYİŞDİRİCİLƏR (`--yes` tələb edir)

Dördünün də davranışı eynidir: **`--yes` olmadan heç nə dəyişmir** — nə
ediləcəyi mətnlə göstərilir və proses **çıxış kodu 4** ilə dayanır. Bu, GUI-dəki
təsdiq modalının konsol qarşılığıdır.

> **Dəyişiklik:** bu kod əvvəl `2` idi və işə düşmə xətası ilə eyni mənanı
> daşıyırdı. Skript ikisini ayırd edə bilmirdi, halbuki reaksiya tam əksdir:
> təsdiq-tələbində əmr `--yes` ilə TƏKRAR edilməlidir, işə düşmə xətasında isə
> təkrar cəhd yalnız eyni nasazlığı təkrarlayar. `2` indi **yalnız** işə düşmə
> xətasıdır (bax §3 «Çıxış kodları»).

| Bayraq | Arqument | Nə edir | Kim işlədə bilər | Dəyişdirir? | Audit izi |
|---|---|---|---|---|---|
| `--extend` | `TENANT_ID` | Lisenziyanı 1 ay uzadır (müddət `LICENSE_EXTENSION_DAYS`-dən). Deaktiv müştərini **yenidən aktivləşdirir** (`deactivation_reason`/`deactivated_at` təmizlənir) | Hazırlayıcı | ⚠️ lisenziya bazası | `license_audit_log` → `EXTEND_ONE_MONTH` + `LICENSE_EXTENDED` |
| `--force-version` | `TENANT_ID=X.Y.Z` | Müştəriyə məcburi versiya təyin edir. **Boş dəyər** (`TENANT_ID=`) məcburiyyəti ləğv edir | Hazırlayıcı | ⚠️ lisenziya bazası | `license_audit_log` → `SET_FORCED_VERSION` / `CLEAR_FORCED_VERSION` |
| `--publish` | `FAYL` | Quraşdırıcını Storage-a yükləyir və buraxılış kataloquna yazır. `--yes`-siz yalnız faylın faktlarını göstərir (ölçü, SHA-256, Authenticode imzası) | Hazırlayıcı | ⚠️ Storage + kataloq | buraxılış sətri (`app_versions`) |
| `--recover-access` | `TENANT_ID=username` | **Təcili giriş bərpası** — ayrıca bölmə: §4 | Hazırlayıcı | ⚠️ **MÜŞTƏRİNİN `employees` cədvəli** | `audit_logs` → `EMERGENCY_ACCESS_RECOVERY` + kritik bildiriş |

### 1.4. Modifikatorlar

| Bayraq | Arqument | Nə edir |
|---|---|---|
| `--yes` | — | Dəyişdirən əmrlər üçün təsdiq. **Tək universal təsdiq bayrağıdır** — dördü də onu oxuyur |
| `--publish-version` | `X.Y.Z` | `--publish` üçün versiya nömrəsi. Boşdursa yayım rədd edilir (çıxış 1) |
| `--publish-notes` | `MƏTN` | Buraxılış qeydləri (məcburi deyil) |
| `--publish-mandatory` | — | Buraxılışı **məcburi yeniləmə** kimi işarələyir |
| `--recovery-reference` | `İSTİNAD` | `--recover-access` üçün **MƏCBURİ** kimlik təsdiqi izi (ticket/qeyd nömrəsi) |
| `--recovery-contact` | `ƏLAQƏ` | `--recover-access` üçün **MƏCBURİ** təsdiqlənmiş şirkət e-poçtu/telefonu |

---

## 2. Developer Paneli necə qorunur

`--developer-mode` bayrağı **tək başına heç nə açmır**. `developer_mode_enabled()`
İKİ mühit dəyişəni tələb edir və hər ikisi olmalıdır:

| Dəyişən | Qəbul edilən dəyər |
|---|---|
| `KOMPASOS_DEVELOPER_MODE` | `1`, `true` və ya `yes` (böyük/kiçik hərf fərqi yoxdur) |
| `KOMPASOS_SUPABASE_SERVICE_ROLE_KEY` | boş olmayan hər hansı dəyər |

Yoxlama **bazadan ƏVVƏL** işləyir və bu, qəsdlidir: əks halda müştəri PC-sində
bayraq yazan istifadəçi «`DATABASE_URL` yoxdur» kimi yanıldıcı xəta alar və əsl
səbəbi (rejim ümumiyyətlə açıq deyil) görməzdi. Müştəri quraşdırmasında həmin
dəyişənlər ümumiyyətlə mövcud olmur, yəni bayraq **təsadüfən işə düşə bilməz**.

**Diqqət — burada istifadəçi girişi (login) YOXDUR.** Developer Paneli rol
modelinə tabe deyil; onun yeganə qapısı `service_role` açarına sahib olmaqdır.
Bu, `docs/security_decisions.md`-də sənədləşdirilmiş qərardır (Master Panel
`mTLS` əvəzinə `service_role` + RLS). Praktik nəticə: **`service_role` açarını
oxuya bilən hər kəs bütün müştəri siyahısını görə bilər** — açarın saxlanması
sistemin ən həssas nöqtəsidir.

### `--publish` üçün əlavə şərt

`_build_release_publisher` yayım qatını yalnız `KOMPASOS_SUPABASE_URL` doludursa
qurur; boşdursa `--publish` çıxış kodu 1 və aydın mesajla dayanır. Naşir
yoxlayıcısı (`KOMPASOS_UPDATE_PUBLISHER`) da burada qurulur ki, panel yayımdan
ƏVVƏL Authenticode imzasını yoxlaya bilsin — boş buraxılsa yoxlayıcı istənilən
etibarlı imzanı qəbul edərdi.

---

## 3. Qolların sırası və çıxış kodları

`main()` qolları **məhz bu sırada** yoxlayır və sıra əhəmiyyətlidir:

```
1. --developer-mode      → Developer Paneli (konsol və ya --gui ilə pəncərə)
2. --run-scheduled-jobs  → başsız iş icrası
3. --watchdog            → nəzarətçi prosesi
4. --gui  VƏ YA  paketlənmiş rejimdə arqumentsiz işə düşmə
5. (qalan hər şey)       → özünü-yoxlama
```

* **`--run-scheduled-jobs` GUI qollarından ƏVVƏLDİR**, çünki paketlənmiş
  rejimdə arqumentsiz defolt GUI-dir; sonra gəlsəydi, Task Scheduler-in çağırdığı
  `KompasOS.exe --run-scheduled-jobs` mağaza PC-sində **pəncərə açardı**.
* **`--watchdog` GUI-dən ƏVVƏLDİR**, çünki `--watchdog --kiosk` çağırışında bu
  proses interfeysi özü açmamalıdır, alt-prosesi idarə etməlidir.
* **Paketlənmiş rejimdə (`.exe`) arqumentsiz defolt GUI-dir**, mənbədən icrada
  isə özünü-yoxlama. Səbəb: `.exe` iki dəfə kliklənəndə arqument ötürülmür və
  köhnə davranışda pəncərə açılmır, `--windowed` rejimində konsol da yoxdur,
  proses 1 kodu ilə səssizcə çıxırdı — yəni tətbiq «işə düşmür» görünürdü.
  Mənbədən defolt DƏYİŞMİR, çünki CI məhz ona arxalanır.

### Çıxış kodları

**Hər kodun TƏK mənası var.** Sabitlər koddadır və ad ilə istinad edilir:
`main.EXIT_STARTUP_ERROR`, `main.EXIT_WATCHDOG_RESTART_LIMIT`,
`developer_panel.console.EXIT_OK / EXIT_FAILED / EXIT_CONFIRMATION_REQUIRED`.

| Kod | Mənası | Harada | Skript nə etməlidir |
|---|---|---|---|
| `0` | Uğur | hər yerdə | davam |
| `1` | Yoxlama uğursuz / əməliyyat rədd edildi (müştəri tapılmadı, versiya verilməyib, fayl yoxlanmadı) | `summarize()`, konsol qolları | girişi düzəlt |
| `1` | Ən azı bir planlaşdırılmış iş çökdü (`FAILED`) | `--run-scheduled-jobs` | jurnalı yoxla |
| `2` | **Yalnız** quraşdırma/baza xətası (`KompasOSError` → `STARTUP_FAILED`) | `main()` ümumi qolu | **təkrar cəhd ETMƏ** — mühiti düzəlt |
| `3` | Kiosk nəzarətçisi yenidən-başlatma həddinə çatdı | `--watchdog` | operatoru xəbərdar et |
| `4` | **Təsdiq gözlənilir** — `--yes` əlavə edin. Heç nə dəyişməyib | dəyişdirici konsol əmrləri | eyni əmri `--yes` ilə TƏKRAR et |

`0` və `1` **dəyişməyib** (geriyə uyğunluq). `2`-ni «xəta» kimi oxuyan mövcud
skript indi də xətanı görür — sadəcə təsdiq-tələbi artıq ona qarışmır.
Tərsini seçsəydik (təsdiq `2`-də qalsın, işə düşmə xətası köçsün), köhnə skript
üçün baza nasazlığı gözlənilməyən bir kod verərdi.

---

## 4. `--recover-access` — Fövqəladə Giriş Bərpası

```bash
KompasOS.exe --developer-mode \
  --recover-access <TENANT_UUID>=<username> \
  --recovery-reference "TICKET-4417 / 2026-08-14 telefon təsdiqi" \
  --recovery-contact "info@musteri-sirket.az" \
  --yes
```

### 4.1. Dəqiq nə edir

Kod: `developer_panel/console.py::_recover_access` →
`application/use_cases/authentication.py::EmergencyAccessRecoveryUseCase.recover`.

Uğurlu icrada **üç şey** baş verir:

1. Hədəf hesabın `must_change_password` **`True`** və `is_active` **`True`**
   olur (`employees.save()` ilə yazılır).
2. Müvəqqəti şifrə generasiya olunur (`HashingService.generate_temporary_password()`,
   uzunluq siyasəti hədəf kirayəçinin `PASSWORD_MIN_LENGTH` parametrindən) və
   **açıq mətn kimi konsola çap olunur**.
3. Audit sətri + kritik bildiriş yazılır (§4.4).

### 4.2. Hansı şəraitdə lazımdır

Yalnız bir ssenaridə: **kirayəçinin BÜTÜN aktiv admin-tier hesabları itirilib**
(işdən çıxma, şifrə itkisi, hesabın səhvən deaktiv edilməsi). Bu, `SEC-016`-nın
birbaşa nəticəsidir — e-poçt token axını çıxarıldığı üçün «şifrəmi unutdum»
linki YOXDUR; sistemə qayıtmağın başqa yolu qalmır.

Prosedur **GUI düyməsi DEYİL və bu qəsdəndir**: o, kirayəçinin `employees`
cədvəlinə yazır, halbuki hazırlayıcı tərəf üçün qayda «heç bir halda işçi
PII-sinə uzaqdan çıxış YOXDUR»-dur. Düymə şəklində həmişə göz önündə duran bir
yol bu sərhədi gündəlik hala gətirərdi; dörd məcburi arqument + `--yes` isə
şüurlu qərar tələb edir.

### 4.3. Hansı yoxlamaları YAN KEÇİR, hansılarını KEÇMİR

**YAN KEÇİR** (dizayn üzrə — prosedurun bütün mənası budur):

| Nə | İzah |
|---|---|
| İstifadəçi girişi (login) | Aktor tenant istifadəçisi deyil; `audit_logs.actor_id` **`NULL`** yazılır |
| İcazə flag-ləri | `can_reset_password` və digər RBAC yoxlamaları ümumiyyətlə işləmir |
| **Strict Hierarchy Guard** | `CredentialResetUseCase`-dəki `actor.priority > subject.priority` müqayisəsi burada YOXDUR — aktor anlayışı yoxdur |
| Öz-özünə sıfırlama qadağası | Eyni səbəbdən tətbiq olunmur |
| Hesabın deaktiv olması | `is_active` **məcburi `True`-ya qaytarılır** — bu, funksiyanın özüdür |

**KEÇMİR** (dörd qapı, hamısı `EmergencyAccessRecoveryUseCase.recover`-dədir):

| # | Qapı | Pozulanda |
|---|---|---|
| 1 | `active_admin_count == 0` — kirayəçidə **aktiv admin-tier hesab QALMAMALIDIR** | `AuthenticationError`; say `directory.active_admin_count()` ilə birbaşa bazadan alınır, arqumentdən yox |
| 2 | `verified_contact` **`license_tenants.company_contact_email/phone`** ilə üst-üstə düşməlidir (SEC-016) — fərdi işçi e-poçtu ilə DEYİL | `EMERGENCY_RECOVERY_CONTACT_MISMATCH` **CRITICAL** təhlükəsizlik jurnalı + rədd |
| 3 | `--recovery-reference` boş olmamalı və `MIN_RECOVERY_REFERENCE_LENGTH`-dən qısa olmamalıdır | `AuthenticationError` |
| 4 | Hədəf hesabın effektiv rolu **`ROOT` və ya `CEO`** olmalıdır | `AuthenticationError` — adi işçi hesabı bu yolla bərpa edilə bilməz |

İkinci qapı **prosedurun əsas qapısıdır**: uyğunsuzluq halında bərpa istənilən
şəxsə admin hesabı verən arxa qapıya çevrilərdi.

### 4.4. Audit izi — kim görür

| Jurnal | Məzmun | Kim görür |
|---|---|---|
| **Kirayəçinin `audit_logs` cədvəli** | `action = EMERGENCY_ACCESS_RECOVERY`, `actor_id = NULL`, `after_state` = `{developer_reference, verified_via: "COMPANY_CONTACT"}`, `reason` | Kirayəçinin özü — `can_view_audit_logs` daşıyan hər kəs |
| **Bildiriş** (`is_critical = True`) | «Təcili giriş bərpası icra edildi. İstinad: …» | `can_view_audit_logs` daşıyanlar (`TENANT_NOTIFICATION_AUDIENCE`) |
| **Təhlükəsizlik log kanalı** | `EMERGENCY_ACCESS_RECOVERY` **CRITICAL** — `tenant_id`, `target_id`, `developer_reference` | Log fayllarına çıxışı olan |

Yəni **əməliyyat müştəridən gizli qalmır**. Bir incəlik var və bilinməlidir:
bildirişi görmək üçün `can_view_audit_logs` lazımdır, prosedurun ön şərti isə
aktiv adminin qalmamasıdır — deməli bildiriş praktikada **bərpa edilmiş hesab
ilk dəfə girəndən sonra** oxunur. Audit sətri isə həmin anda artıq bazadadır.

### 4.5. Risk qiymətləndirməsi — qəbul edilmiş risk, yoxsa qüsur?

Sual: *fiziki server girişi olan hər kəs bunu işlədə bilər — bu, qəbul edilmiş
risk modelidir, yoxsa qüsur?*

**Cavab: mexanizmin ÖZÜ qəbul edilmiş riskdir; bir icra qüsuru isə ayrıca
mövcuddur.**

**Niyə qəbul edilmiş risk:** əmr müştərinin `DATABASE_URL`-ı ilə deyil,
`KOMPASOS_SUPABASE_SERVICE_ROLE_KEY` ilə işləyir. Həmin açar onsuz da RLS-i tam
yan keçir — onu oxuya bilən şəxs `--recover-access`-siz də istənilən sətri SQL
ilə dəyişə bilər. Yəni bayraq **yeni** səlahiyyət vermir, mövcud səlahiyyəti
**audit-lənən, dörd qapıdan keçən və müştəriyə bildirilən** bir kanala
yönləndirir. Alternativlə (adminin birbaşa SQL yazması) müqayisədə bu, ciddi
təkmilləşdirmədir: birbaşa `UPDATE employees` heç bir bildiriş göndərmir və
`audit_logs`-da iz qoymur. `docs/security_decisions.md`-dəki
`service_role` + RLS qərarı bu risk modelini artıq sənədləşdirib.

Əlavə olaraq mexanizm **fövqəladə hal üçün lazımdır**: alternativi olan tək
model «e-poçt token axını»dır və SEC-016 onu qəsdən çıxarıb.

**✅ DÜZƏLDİLDİ — əvvəl müvəqqəti şifrənin heşi SAXLANILMIRDI.** `recover()`
heşi hesablayır (`hashed = self._hashing.hash_password(temporary)`) və
`TemporaryCredential`-ın tərkibində qaytarırdı, lakin **heç bir çağıran onu
bazaya yazmırdı**: `EmployeeRepository.save()` sənədləşdirilmiş şəkildə sirrlərə
TOXUNMUR («`pin_hash`/`password_hash` burada YAZILMIR — onlar üçün ayrıca
`update_credentials()` var»), `update_credentials()`-in isə istehsalat kodunda
çağıranı yox idi. Nəticə: `--recover-access` hesabı aktivləşdirir, «şifrəni
dəyiş» bayrağını qoyur və ekranda bir şifrə göstərirdi — **həmin şifrə ilə
giriş isə mümkün deyildi**.

İndi `recover()` `update_credentials(target.id, password_hash=…,
pepper_version=…)` çağırır (`update_credentials` `EmployeeRepository`
portuna əlavə edilib). Üç detal:

* **`pepper_version` də yazılır** — yazılmasaydı, yeni heş köhnə pepper
  versiyası ilə yoxlanar və doğru şifrə də rədd edilərdi (SEC-005).
* **Sıra:** heş, audit sətri və bildiriş EYNİ tranzaksiyadadır; şifrə YALNIZ
  `uow.commit()`-dən SONRA çap olunur. Hər hansı addım uğursuz olarsa
  administrator işləməyən bir şifrə GÖRMÜR.
* **Reqressiya testi:** `tests/unit/test_authentication.py::
  test_recovery_saxlanmis_hes_muveqqeti_sifreni_dogrulayir` — «metod çağırıldı»
  deyil, **saxlanmış heşin göstərilən açıq şifrəni doğruladığını** yoxlayır.

---

## 5. Məlum boşluqlar — vəziyyəti

Aşağıdakılar kod oxunuşunda təsdiqlənmişdi. **Hamısı düzəldilib**; siyahı
tarixçə üçün saxlanılır, çünki hər bənd niyə-izahı ilə birlikdə mənalıdır.

1. **✅ DÜZƏLDİLDİ — `--crashes` və `--tickets` konsolda təsirsiz idi.**
   `main._run_developer_panel` `run_console(...)` çağırışına `show_crashes` /
   `show_tickets` arqumentlərini **ötürmürdü**, halbuki `run_console` onları
   qəbul edir və `_render_view` onlara görə budaqlanır. Nəticə sükutla yanlış
   idi: `--developer-mode --crashes` adi müştəri cədvəlini göstərirdi və
   istifadəçi səhv məlumata baxdığını bilmirdi. GUI variantı
   (`--developer-mode --gui`) təsirlənməmişdi.
   Test: `tests/unit/test_developer_panel_diagnostics.py::
   test_crashes_flag_reaches_run_console` (və `…_tickets_…`) — həqiqi `argparse`
   parser-i işlədir, yəni bayraq adının dəyişməsini də tutur.

2. **✅ DÜZƏLDİLDİ — müvəqqəti şifrənin heş-i saxlanılmırdı** (§4.5).
   Eyni naxış `CredentialResetUseCase.reset_password/reset_pin`-də də vardı və
   orada da bağlanıb. **Həmin use case istehsalat yoluna qoşulu deyil** və bu,
   yoxlanılıb: `src/` boyu onu quran heç bir yer yoxdur; GUI-dəki
   `[Şifrəni Yenilə]` düyməsi `UserManagementUseCase.reset_password`-a gedir.
   Ölü kod SAYILMIR — orada şifrəni SİSTEM generasiya edir (toplu sıfırlama
   ssenarisi, `bulk_operations.py` başlığı ona istinad edir), ona görə
   silinmək əvəzinə düzəldilib və sinif başlığına bu qeyd yazılıb.

3. **✅ DÜZƏLDİLDİ — `2` çıxış kodunun iki mənası** (§3). Təsdiq-tələbi `4`-ə
   köçürülüb; `0`/`1` dəyişməyib, `2` yalnız işə düşmə xətasıdır.

4. **✅ DÜZƏLDİLDİ (kod tərəfi) — `CredentialWriter` protokolunun tətbiqi yox idi.**
   Sənədləşdirmə zamanı aşkarlanıb: `composition.py` `credentials=uow.employees`
   ötürür, lakin `PostgresEmployeeRepository`-də `set_password`/`set_pin`/
   `clear_pin_lockout` metodları **ümumiyyətlə yox idi** — yəni GUI-dəki
   `[Şifrəni Yenilə]` istehsalatda `AttributeError` ilə çökürdü. `uow.employees`
   `Any` qaytardığı üçün nə mypy, nə də hər hansı test bunu görürdü. Hər üç
   metod artıq mövcud `update_credentials()` SQL-inə yönləndirilib.

5. **⚠️ AÇIQ QALIR — işçi YARADILMASI yolu (bu sənədin əhatəsindən kənar).**
   `UserManagementUseCase`/`FirstRunSetupUseCase` yeni işçini
   `EmployeeRepository.save()` ilə yazır, lakin `save()` `UPDATE`-dir; sətri
   yaradan `insert()` ayrıca metoddur və bu axınlardan çağırılmır. Bu, sirr
   yazısı deyil, SƏTİR yaradılması problemidir — ayrıca düzəliş tələb edir.

---

## 6. `--help` çıxışı

Aşağıdakı mətn faktiki icranın nəticəsidir:

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 \
  .venv/Scripts/python.exe -m src.main --help
```

```text
usage: kompasos [-h] [--check] [--strict] [--log-dir LOG_DIR] [--kiosk]
                [--watchdog] [--preview] [--run-scheduled-jobs]
                [--theme {light,dark,system}] [--developer-mode] [--gui]
                [--search SEARCH] [--crashes] [--tickets] [--extend TENANT_ID]
                [--force-version TENANT_ID=X.Y.Z]
                [--recover-access TENANT_ID=username]
                [--recovery-reference İSTİNAD] [--recovery-contact ƏLAQƏ]
                [--publish FAYL] [--publish-version X.Y.Z]
                [--publish-notes PUBLISH_NOTES] [--publish-mandatory] [--yes]

KompasOS

options:
  -h, --help            show this help message and exit
  --check               yalnız sağlamlıq yoxlaması işlət (Faza 1 defolt
                        davranışı)
  --strict              xəbərdarlıqları da xəta say (istehsalat buraxılışı
                        üçün)
  --log-dir LOG_DIR     log qovluğu
  --kiosk               kiosk rejimi: tam ekran PIN klaviaturası
  --watchdog            kiosk nəzarətçisi: tətbiq çökərsə avtomatik yenidən
                        başladır (mağaza PC-lərində bu rejimlə işə salınır,
                        bölmə 5)
  --preview             ekranları maketdəki nümunə məzmunla doldur (dizayn
                        yoxlaması)
  --run-scheduled-jobs  planlaşdırılmış fon işlərini bir dəfə icra et və çıx
                        (başsız; ağır işlər daxil — gecəlik ehtiyat nüsxə)
  --theme {light,dark,system}
                        işə düşmə teması
  --developer-mode      Developer Panelini aç (yalnız hazırlayıcının yerli
                        mühiti)
  --gui                 interfeysi aç; `--developer-mode` ilə birlikdə —
                        Developer Paneli pəncərəsi
  --search SEARCH       Developer Paneli: ad/e-poçt üzrə süzgəc
  --crashes             Developer Paneli: anonim çökmə hesabatları, tezliyə
                        görə qruplaşdırılmış
  --tickets             Developer Paneli: dəstək müraciətləri inbox-u (SLA
                        vəziyyəti ilə)
  --extend TENANT_ID    Developer Paneli: 1 ay uzat
  --force-version TENANT_ID=X.Y.Z
                        Developer Paneli: tenant üçün məcburi versiya (boş
                        dəyər ləğv edir)
  --recover-access TENANT_ID=username
                        Developer Paneli: təcili giriş bərpası (bütün admin
                        hesabları itibsə)
  --recovery-reference İSTİNAD
                        `--recover-access` üçün MƏCBURİ kimlik təsdiqi izi
                        (ticket/qeyd nömrəsi)
  --recovery-contact ƏLAQƏ
                        `--recover-access` üçün MƏCBURİ təsdiqlənmiş şirkət
                        e-poçtu/telefonu
  --publish FAYL        Developer Paneli: quraşdırıcını Storage-a yüklə və
                        kataloqa yaz
  --publish-version X.Y.Z
                        yayımlanacaq versiya nömrəsi
  --publish-notes PUBLISH_NOTES
                        buraxılış qeydləri
  --publish-mandatory   buraxılışı məcburi yeniləmə kimi işarələ
  --yes                 dəyişdirən əmrlər üçün təsdiq
```

> Windows konsolunda `PYTHONIOENCODING=utf-8` olmadan Azərbaycan hərfləri
> (`İSTİNAD`, `ƏLAQƏ`) `UnicodeEncodeError` verə bilər.
> `QT_QPA_PLATFORM=offscreen` isə `--help` üçün ciddi tələb deyil — bu yol
> PySide6-nı ümumiyyətlə idxal etmir (`_run_gui` idxalları funksiya
> daxilindədir) — lakin başsız mühitdə zərərsiz ehtiyatdır.

---

## 7. Ən çox işlənən nümunələr

```bash
# İstehsalat buraxılışından əvvəl — bütün xəbərdarlıqlar xəta sayılır
.venv/Scripts/python.exe -m src.main --strict

# Mağaza PC-sinin işə düşmə skripti (çökmədə avtomatik bərpa)
KompasOS.exe --watchdog --kiosk --theme dark

# Windows Task Scheduler — gecə 03:00 (bax docs/scheduler_setup.md)
KompasOS.exe --run-scheduled-jobs

# Dizayn yoxlaması — baza lazım deyil
.venv/Scripts/python.exe -m src.main --gui --preview --theme light

# Müştəri siyahısı (yalnız oxu)
KompasOS.exe --developer-mode --search "Mağaza MMC"

# Lisenziyanı uzat — əvvəlcə TƏSDİQSİZ işlədib nə olacağını görün
KompasOS.exe --developer-mode --extend <TENANT_UUID>          # çıxış kodu 4
KompasOS.exe --developer-mode --extend <TENANT_UUID> --yes    # icra

# Buraxılış yayımı
KompasOS.exe --developer-mode --publish dist/KompasOS-1.4.0.exe \
  --publish-version 1.4.0 --publish-notes "Face Control pilotu" \
  --publish-mandatory --yes
```
