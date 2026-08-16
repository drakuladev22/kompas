# Google Drive İnteqrasiyası

Cərimə sübut şəkilləri, işçi sənəd skanları və sahə hesabatı fotoları
**müştərinin ÖZ Google Drive hesabında** saxlanılır. Bu, spesifikasiyadan
sənədləşdirilmiş deviasiyadır (`CLAUDE.md` §9) və alt-sistem
`src/infrastructure/storage/` altında **8 moduldan** ibarətdir — indiyədək
yalnız `migrations/002` başlığında bir cümlə ilə xatırlanırdı.

| Modul | Məsuliyyəti |
|---|---|
| `oauth_flow.py` | Razılıq axını — loopback + PKCE (SEC-017) |
| `drive_api.py` | Drive REST klienti — token yeniləmə, təkrar cəhd, xəta xəritəsi |
| `connections.py` | `drive_connections` sətri, status keçidləri, provider fabriki |
| `google_drive.py` | Yükləmə/oxuma, formatın validasiyası, kiçildilmə |
| `folder_resolver.py` | `KompasOS/{Mağaza}/{İl-Ay}/` iyerarxiyası + DB keşi |
| `upload_queue.py` | SQLite növbəsi + disk spool-u, backoff, claim |
| `quota_monitor.py` | Kvota yoxlaması, 90% xəbərdarlığı, `QUOTA_EXCEEDED` |
| `image_cache.py` | Yerli şəkil keşi (TTL + disk tavanı) |

---

## 1. Niyə Drive, niyə Supabase Storage yox

`migrations/002` və `.env.example` eyni əsaslandırmanı verir və o, **iki
hissəlidir**:

**Kvota iqtisadiyyatı.** Sübut şəkilləri megabaytlarla yer tutur və Supabase-in
pulsuz/aşağı planlarında saxlama kvotası tez dolur. Kvota bir dəfə dolduqda
təsir bütün şəbəkəyə yayılardı: 21 filialın hamısında yeni cərimə sübutsuz
qalardı, halbuki spesifikasiya manual cəriməni sübutsuz QADAĞAN edir. Müştərinin
öz Drive hesabı isə **onun öz kvotasıdır** — dolduğunda yalnız o kirayəçi
təsirlənir və həlli də onun əlindədir (yeni hesab qoşmaq).

**Data mülkiyyəti.** `drive_connections` cədvəlinin şərhi bunu açıq yazır:
hesab *«tenant-ın öz Google Drive hesabıdır, developer-in paylaşılan Drive-ı
DEYİL»*. Yəni cərimə arxivi müştəriyə aiddir — o, KompasOS-suz da Drive-da
qovluğa baxıb şəkilləri görə bilər. Bu, mübahisə halında əhəmiyyətlidir:
sübutun saxlandığı yer proqram təminatçısının infrastrukturu deyil.

> **Diqqət — DİGƏR şəkil növləri TOXUNULMUR.** Profil şəkli və tapşırıq sübutu
> öz əvvəlki yollarında qalır; köçürmə YALNIZ cərimə sübutuna aiddir və sonradan
> işçi sənədləri (#17) ilə sahə hesabatı fotolarına (#26+#27) genişləndirilib.

`fines.photo_evidence_url` sütunu da **silinmir**: köçürülməzdən əvvəl
yaradılmış cərimələrin sübutu hələ Supabase Storage-dadır və o sütun silinsəydi
həmin şəkillər həmişəlik itərdi — cərimə etirazının yeganə sübutu odur.

---

## 2. Razılıq axını (OAuth)

### 2.1. Kim qoşur

| Şərt | Dəyər |
|---|---|
| İcazə flag-i | **`can_manage_drive_connection`** (`migrations/002` §5) |
| Defolt sahibi | yalnız `ROOT` və `CEO` mövqeləri |
| `hardlock_level` | `0`, anti-fraud DEYİL, kamera-only DEYİL |
| Ekran | Sol menyu → **Drive Bağlantısı** (`menu.py`, `order=165`) |

Səlahiyyət qapısı **ekranda deyil, kontrollerdədir**: menyu maddəsi flag-siz
istifadəçiyə görünmür, lakin görünməmək tək qapı ola bilməz — ekran birbaşa
açılsa da hər əməliyyatın əvvəlində flag yenidən yoxlanılır
(`presentation/controllers/drive_connection.py`).

### 2.2. Axının forması — SEC-017

**Loopback + PKCE.** Google `urn:ietf:wg:oauth:2.0:oob` axınını («kodu ekranda
göstər, istifadəçi yapışdırsın») **2022-də qapadıb** — yeni klientlərdə
ümumiyyətlə işləmir. Quraşdırılmış tətbiqlər üçün yeganə dəstəklənən yol
`http://127.0.0.1:<port>` üzərinə yönləndirmədir: brauzer razılıqdan sonra kodu
birbaşa müvəqqəti lokal serverə göndərir.

| Detal | Seçim | Niyə |
|---|---|---|
| Port | **0** — OS boş port seçir | Sabit port seçilsəydi, həmin portu tutan başqa proqram bağlantını tamamilə bloklayardı |
| Google Cloud Console klient tipi | **Desktop app** | Bu tip bütün loopback portlarına icazə verir; konkret port qeydiyyatdan keçirilmir |
| PKCE | `code_verifier` yalnız cari prosesin yaddaşında, hər axında yeni | Masaüstündə `client_secret` **əslində sirr deyil** — `.exe`-ni açan onu görür (Google özü sənədləşdirir). Müdafiə PKCE-dədir: loopback portunu dinləyən yerli zərərli proses kodu tutsa belə onu token-ə dəyişə bilmir |
| `state` | təsadüfi dəyər, geri qayıtmalıdır | CSRF — cavab BAŞQA axına aiddirsə rədd edilir |
| `access_type=offline` + `prompt=consent` | **məcburi** | `refresh_token` lazımdır (şəkillər aylarla, istifadəçi olmadan yüklənir). Google onu yalnız `offline` ilə verir və eyni hesab üçün təkrar razılıqda ümumiyyətlə göndərmir — `prompt=consent` olmasa hesabı ikinci dəfə qoşmaq «refresh_token gəlmədi» xətası ilə bitərdi |
| Gözləmə | `poll()`, bloklayan `wait()` deyil | Razılıq brauzerdə dəqiqələrlə çəkə bilər; bloklayan gözləmə GUI sapını dondurardı. Kontroller `QTimer` ilə hər 200 ms yoxlayır və bütün iş Qt hadisə dövrəsində qalır |
| Taymaut | `DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS` (defolt 300 s) | Açıq qalan lokal port müddətsiz dinləməməlidir |

### 2.3. İstənilən icazələr (scope)

```
https://www.googleapis.com/auth/drive.file
https://www.googleapis.com/auth/userinfo.email
```

**`drive.file` — tətbiqin ÖZ yaratdığı fayllar.** Bütöv `drive` scope-u
istifadəçinin BÜTÜN sənədlərinə giriş istəyərdi, Google-un əlavə yoxlama
prosesindən keçmək tələb edərdi və müştəriyə izah edilə bilməyən bir səlahiyyət
olardı. `userinfo.email` yalnız qoşulan hesabın ünvanını ekranda göstərmək
üçündür.

### 2.4. Token harada saxlanılır

Yalnız **`refresh_token`** saxlanılır — `drive_connections.oauth_refresh_token`
sütununda, **AES-256-GCM** ilə şifrəli (AAD = `drive_connection:<id>`). Access
token heç vaxt DB-yə düşmür: o, prosesin yaddaşındadır və müddəti bitəndə
yenidən alınır.

Token **ekrandan keçmir**: `refresh_token` bir an kontrollerin yaddaşında olur
və dərhal `DriveConnectionRepository.connect()`-ə verilir; şifrələmə orada baş
verir. Jurnalda yalnız hesabın e-poçtu qalır. Sütun şərhi səbəbi yazır:
*«plaintext saxlamaq bütün cərimə arxivinə çıxış vermək demək olardı»*.

### 2.5. Tenant başına yalnız BİR aktiv bağlantı

```sql
CREATE UNIQUE INDEX uq_drive_one_active_per_tenant
    ON drive_connections (tenant_id) WHERE status = 'ACTIVE';
```

Partial unique index seçilib, `CHECK` yox: `CHECK` sətirlərarası şərti ifadə edə
bilmir, trigger isə iki paralel tranzaksiyada sıza bilər. Yeni hesab qoşulduqda
köhnəsi **eyni tranzaksiyada** `ARCHIVED` olur.

---

## 3. Yükləmə növbəsi

### 3.1. Niyə ayrıca növbə — `OfflineBuffer` niyə kifayət etmir

`OfflineBuffer` **DB sətirlərinin** outbox-udur: payload JSON-dur və şifrələnib
SQLite sütununda saxlanılır. Şəkil isə megabaytlarla ikili məlumatdır — onu
base64-ləyib SQLite sütununa yazmaq faylı **~33% şişirdərdi** və hər oxunuşda
bütün sətri yaddaşa gətirərdi.

Ona görə **eyni naxış, fərqli saxlama**: SQLite indeks + eksponensial backoff +
status, lakin baytlar diskdə ayrıca **spool** faylında. Backoff cədvəli də
qəsdən eynidir (`OFFLINE_RETRY_BACKOFF_SECONDS` = `30,120,600`) — iki fərqli
gözləmə davranışı olsaydı, nasazlıq zamanı sistemin nə vaxt təkrar cəhd edəcəyini
proqnozlaşdırmaq çətinləşərdi.

### 3.2. Fayllar harada yaşayır

| Nə | Yol | Mühit dəyişəni |
|---|---|---|
| SQLite indeksi | `%LOCALAPPDATA%\KompasOS\data\evidence_uploads.db` | `KOMPASOS_EVIDENCE_QUEUE_PATH` |
| Şəkil baytları (spool) | indeks faylının **yanındakı** `evidence_spool/` qovluğu | — (indeks yolundan törəyir) |
| Şəkil keşi (oxuma) | `%APPDATA%\KompasOS\image_cache\` | `KOMPASOS_IMAGE_CACHE_DIR` |

Linux/macOS-da: `~/.local/share/KompasOS/data/…` (XDG). Yol **CWD-yə nisbi
DEYİL**, çünki paketlənmiş `.exe` ixtiyari qovluqdan işə düşür və cari qovluq
yazıla bilməyəndə **ilk sübut şəkli itərdi**.

> ⚠️ **Yolu dəyişəndə ikisi birlikdə köçürülməlidir** — indeks faylı və onun
> yanındakı `evidence_spool/`. Köhnə quraşdırmada `./data/evidence_uploads.db`
> mövcuddursa o işlədilir (`src/shared/data_paths.py`), yəni yüklənməmiş
> şəkillər növbədə qalır.

### 3.3. Nə vaxt növbəyə düşür

Sıra **qəsdən** belədir (`controllers/fine_entry.py`):

```
1. EvidenceUploadQueue.enqueue()   → fayl LOKAL diskə yazılır, açar qaytarılır
2. ManualFineUseCase.issue(...)    → cərimə bazaya yazılır, açar `evidence_reference`
3. context.run_evidence_uploads()  → növbə dərhal bir dəfə boşaldılmağa çalışılır
```

Tərsi olsaydı — əvvəlcə cərimə, sonra spool — aradakı çökmə **«sübutu olmayan
cərimə»** yaradardı və bu, bərpa oluna bilməyən pozuntudur. Bu sıra ilə ən pis
hal «sahibsiz spool faylı»dır: yer tutur, heç kimə zərər vermir.

Növbə həm də **fon dövrəsi** ilə boşaldılır: `presentation/app.py` hər
`EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS` (defolt **120 s**) bir dəfə çağırır. Bu
dövrə cərimə anındakı birdəfəlik cəhdi əvəz etmir — **şəbəkə qayıdanda qalanları
götürür**.

### 3.4. Statuslar və təkrar cəhd

| Status | Mənası | Növbəyə qayıdır? |
|---|---|---|
| `PENDING` | Yüklənməyi gözləyir | — |
| `PROCESSING` | Bir işçi «claim» edib, hazırda yükləyir | köhnəlmə müddətindən sonra |
| `UPLOADED` | Drive-dadır; spool faylı **silinir** | xeyr |
| `FAILED` → `PENDING` | Müvəqqəti nasazlıq (şəbəkə, kvota, 5xx) | **bəli**, backoff ilə |
| `REJECTED` | Fayl **yararsızdır** (ölçü/uzantı/imza) | **xeyr** |

**İki fərqli uğursuzluq — bu, alt-sistemin əsas qərarıdır.** «Gözlə və təkrar
cəhd et» qaydası YALNIZ müvəqqəti nasazlığa aiddir. Faylın ÖZÜ yararsızdırsa
(5 MB-dan böyük, `.exe` uzantılı, məzmunu şəkil olmayan) heç bir gözləmə
nəticəni dəyişmir — belə element əvvəllər `FAILED`-ə düşüb hər 10 dəqiqədən bir
eyni cavabla rədd edilirdi: sonsuz dövrə, dolan disk, faydasız jurnal.

Ona görə iki qat var:

1. `enqueue()` faylı **diskə yazmazdan ƏVVƏL** `validate_evidence_payload()`
   çağırır — yararsız fayl növbəyə ümumiyyətlə düşmür və operator səbəbi
   **dərhal ekranda** görür.
2. Artıq növbədə olan element (köhnə versiyadan qalmış, ya da Root həddi
   sonradan aşağı salıb) yükləmə anında `REJECTED`-ə keçir və `PENDING`
   seçimindən çıxır.

`REJECTED` elementin **spool faylı silinmir** — bayt Drive-da deyil, silinsə
şəkil birdəfəlik itərdi. Rədd səbəbi konfiqurasiya da ola bilər (Root həddi
1 MB-a salıb); hədd geri qaldırıldıqda admin faylı `requeue_rejected()` ilə
yenidən növbəyə sala bilər.

**Uğursuzluq həddi:** müvəqqəti nasazlıq üçün **cəhd tavanı YOXDUR.**
`mark_failed` cəhd sayğacını artırır və backoff cədvəlindən gecikmə seçir
(`schedule[min(attempts-1, len(schedule)-1)]`) — cədvəl bitəndən sonra sonuncu
addım (**10 dəqiqə**) sonsuz təkrarlanır. Bu, şüurlu seçimdir: şəkil sübutdur və
«N cəhddən sonra imtina» onu itirmək demək olardı. Sonsuz dövrə riski isə
`REJECTED` qatı ilə bağlanıb — həqiqətən düzəlməyəcək fayl heç vaxt bu yola
düşmür.

### 3.5. İki işçi, bir şəkil — claim mexanizmi

Növbə əvvəllər sadəcə OXUYURDU. İki işçi (kiosk prosesi + admin paneli, və ya
proqramın iki nüsxəsi) eyni anda işə düşəndə hər ikisi eyni sətri görür və eyni
şəkli Drive-a **iki dəfə** yükləyirdi: yetim fayl, boşuna sərf olunan kvota və
`fines` sətrində hansı `file_id`-nin qaldığı təsadüfə bağlı.

`claim_pending()` artıq `BEGIN IMMEDIATE` daxilində sətri `PROCESSING`-ə keçirir
və `PROCESSING` `PENDING` seçimindən çıxır — ikinci işçi elementi ümumiyyətlə
görmür. Çökmə halında element **əbədi ilişmir**: claim anında `next_attempt_at`
köhnəlmə anına təyin olunur (`UPLOAD_CLAIM_STALE_AFTER_SECONDS`, defolt
**600 s**) və həmin an keçəndən sonra element yenidən claim edilə bilir. Dəyər
backoff cədvəlinin ən uzun addımı (10 dəq.) ilə uzlaşdırılıb: daha qısası hələ
yüklənməkdə olan böyük faylı ikinci işçiyə verərdi.

---

## 4. Drive konfiqurasiya EDİLMƏYİBSƏ nə olur

**Cərimə normal yaradılır. Şəkil lokal növbədə gözləyir. Bağlantı qurulan kimi
avtomatik yüklənir.**

Bu, kodla təsdiqlənir — üç müstəqil nöqtədə:

**1. `.env.example`** açıq yazır ki, `KOMPASOS_GOOGLE_CLIENT_ID` /
`KOMPASOS_GOOGLE_CLIENT_SECRET` **boş buraxıla bilər**.

**2. `composition.drive_providers()` `None` qaytarır** və docstring bunu xəta
saymır:

```python
client_id = os.environ.get("KOMPASOS_GOOGLE_CLIENT_ID", "").strip()
client_secret = os.environ.get("KOMPASOS_GOOGLE_CLIENT_SECRET", "").strip()
if not client_id or not client_secret:
    return None
```

`run_evidence_uploads()` fabriki `None` görəndə sadəcə `0` qaytarır — istisna
atmır, jurnal doldurmur. Yəni fon dövrəsi hər 120 saniyədə zərərsiz boş dönür.

**3. DB məhdudiyyəti buna uyğun genişləndirilib** (`migrations/002` §4):

```sql
CHECK (source <> 'MANUAL_CAMERA'
    OR (fine_type_id IS NOT NULL AND issued_by IS NOT NULL
        AND (photo_evidence_url IS NOT NULL
             OR evidence_drive_file_id IS NOT NULL
             OR evidence_upload_status = 'PENDING')));
```

Yəni **«yüklənməni gözləyən» vəziyyət də qanuni sübut mənbəyidir**. Şəkil
Drive-a asinxron yükləndiyi üçün cərimə yaradılan anda hələ
`evidence_drive_file_id` YOXDUR — məhdudiyyət «hər hansı sübut mənbəyi
göstərilib» formasındadır.

Eyni davranış **bağlantı var, lakin kvota dolub** halında da işləyir: yükləmə
uğursuz olur, cərimə yaradılması bloklanmır, element növbədə qalır və admin yeni
Drive hesabı qoşandan sonra avtomatik yüklənir.

---

## 5. Token bitəndə / razılıq geri alınanda

### 5.1. Normal token yenilənməsi

Access token prosesin yaddaşındadır və `expires_in` müddətinin
`DRIVE_TOKEN_REFRESH_MARGIN_SECONDS` (defolt **60 s**) qədər ƏVVƏLİNDƏ
etibarsız sayılır — sorğu göndərilən an tokenin bitməsi «tam sərhəddə» səhvini
bağlayır. `refresh_token` DB-dən oxunur, deşifrə edilir və Google token
endpoint-inə göndərilir.

### 5.2. `401 Unauthorized`

`DriveApiClient._request` **bir dəfə** keşlənmiş tokeni atır və dövrəni təkrar
edir (`DRIVE_MAX_RETRIES`, defolt 3). Bu, tokenin vaxtından əvvəl etibarsız
olduğu halı örtür — məsələn istifadəçi razılığı ləğv edib yenidən verib.

### 5.3. Razılıq həqiqətən geri alınıbsa

`refresh_token` ölür və token endpoint-i **HTTP 400 + `{"error":
"invalid_grant"}`** qaytarır. Nəticə:

1. `DRIVE_TOKEN_REFRESH_FAILED` **təhlükəsizlik jurnalına** yazılır — **cavabın
   mətni jurnala DÜŞMÜR**, çünki içində sirr ola bilər; yalnız status kodu qalır.
2. `DriveConsentRevokedError` atılır (adi `DriveApiError`-un alt-sinfi), mesaj:
   *«Google Drive icazəsi ləğv edilib — Ayarlar → Drive Bağlantısı bölməsindən
   hesabı yenidən qoşun.»* **Ayrı istisna olması vacibdir:** adi API xətasına
   qarşı düzgün reaksiya gözləyib təkrar cəhd etməkdir, razılıq ləğvi isə heç
   vaxt öz-özünə keçmir.
3. Yükləmə `mark_failed` yolundan keçir → element `PENDING` qalır, backoff ilə
   təkrar cəhd edilir. **Şəkil itmir.**
4. Gündəlik `DRIVE_QUOTA_CHECK` işi bunu görür və bağlantını **`REVOKED`**
   işarələyir (`DriveConnectionRepository.mark_revoked()`), `last_error`-a
   səbəb yazılır və Root/CEO **kritik bildiriş** alır. Keçid idempotentdir —
   xəbərdarlıq hər gecə təkrarlanmır.

**Bərpa yolu:** admin **Drive Bağlantısı** ekranından hesabı yenidən qoşur. Yeni
sətir `ACTIVE`, köhnəsi `ARCHIVED` olur; növbədə gözləyən bütün şəkillər növbəti
dövrədə yeni hesaba yüklənir.

> **Tarixçə — bağlanmış uyğunsuzluq.** GUI kontrollerinin `STATUS_TEXT`
> cədvəlində `"REVOKED": ("İcazə ləğv edilib", "danger")` sətri ilk gündən
> vardı, lakin `drive_connection_status` **enum-unda belə dəyər YOX İDİ** və heç
> bir kod sətri o statusa keçirmirdi. Yəni razılıq geri alınanda bağlantı
> ekranda hələ də **«Aktiv»** görünürdü. **Miqrasiya 057** enum dəyərini əlavə
> etdi; `DriveQuotaMonitor` `invalid_grant`-ı tanıyıb vəziyyəti dəyişir; ekran
> isə artıq yalnız `ACTIVE` deyil, **arxivlənməmiş** sətri göstərir — yəni
> `QUOTA_EXCEEDED` və `REVOKED` də öz həqiqi adı ilə görünür (əvvəl ikisi də
> «Qoşulmayıb» kimi görünürdü və səbəb gizli qalırdı).

### 5.4. Köhnə hesabdakı şəkillər

**Oxunmağa davam edir.** `fines.evidence_drive_connection_id` sütunu şəklin
HANSI hesabda olduğunu saxlayır və yeni hesab qoşulduqda **köhnə sətirlərin bu
sahəsi dəyişmir**. `ARCHIVED` bağlantı yeni yazı qəbul etmir, lakin oxuma
provider-i onun üçün də qurulur.

`ON DELETE SET NULL` seçilib, `RESTRICT` yox (SEC-015): dərhal yoxlanan
məhdudiyyət tenant silinməsini bloklayardı. Bağlantı silinsə sütun `NULL` olur,
`photo_evidence_url` və audit izi qalır.

---

## 6. Fayl adlandırma və qovluq strukturu

### 6.1. İyerarxiya

```
KompasOS/                       ← DRIVE_ROOT_FOLDER_NAME, hesabın kökündə
└── {Mağaza adı}/               ← sanitize_folder_name(), Azərbaycan hərfləri SAXLANILIR
    └── {YYYY-MM}/              ← year_month(), DB CHECK ilə eyni format
        └── 20260814-143207_kassa-sahesi.jpg
```

**Aylıq rotasiya «əməliyyat» deyil, ad sxeminin nəticəsidir.** Qovluq yolunda
`{İl-Ay}` olduğu üçün ay dəyişəndə axtarış açarı da dəyişir: keşdə tapılmır,
yeni qovluq **lazy** yaradılır, əvvəlki ayın qovluğuna daha heç nə yazılmır.
Ayrıca cron, «arxivlə» düyməsi və ya vəziyyət sahəsi **lazım deyil** — ayın 1-də
cron işləməsə belə sistem düzgün davranır, halbuki vəziyyət saxlayan həll cron
uğursuz olanda sükutla səhv qovluğa yazardı.

Mağaza adında Azərbaycan hərfləri **saxlanılır** — bu, insanın Drive-da baxdığı
addır və «Yataş Babək» «Yatas Babek»-ə çevrilməməlidir. Yalnız Drive axtarış
sorğusunu poza bilən simvollar (`\ / ' " \n \r \t`) təmizlənir, ad 100 simvola
kəsilir, boş qalarsa `"Adsız Mağaza"` olur.

### 6.2. Qovluq keşi

`drive_folder_cache` cədvəli `(drive_connection_id, store_id, year_month) →
drive_folder_id` saxlayır. **Keş DB-dədir, yaddaşda deyil**: eyni kirayəçinin bir
neçə mağaza PC-si var və yaddaş keşi hər PC-də ayrıca olardı — hər biri Drive-da
eyni qovluğu axtarardı. DB keşi ilə Drive API-yə sorğu mağaza/ay başına **bir
dəfə** gedir; Drive API kvotası istifadəçi başına ~100 sorğu/100 saniyədir.

Unikal açar `drive_connection_id`-ni **də** əhatə edir: hesab dəyişəndə eyni
mağaza/ay üçün yeni hesabda yeni qovluq lazımdır, köhnə keş sətri isə köhnə
hesabın qovluğunu göstərməyə davam edir.

### 6.3. Fayl adı

```
{YYYYMMDD-HHMMSS}_{orijinal adın ilk 60 simvolu}{.jpg | .pdf}
```

Drive eyniadlı fayllara icazə verir (ID-lər fərqlidir), lakin insan qovluğa
baxanda `photo.jpg` adlı 40 fayl faydasızdır — ona görə vaxt möhürü prefiksdir.

**Uzantı:** şəkillər üçün **həmişə `.jpg`**, çünki kiçildilmə hər şeyi JPEG-ə
çevirir və adın məzmuna uyğun olması Drive-da faylı açanın işini asanlaşdırır.
PDF kiçildilmədiyi üçün onun uzantısı **saxlanılır** — `.jpg` adlı PDF-i nə
Drive-ın önizləməsi, nə də admin aça bilməzdi.

### 6.4. Nə qəbul edilir

| Sahib tipi | İcazəli uzantılar |
|---|---|
| `FINE` (cərimə sübutu) | `.jpg`, `.jpeg`, `.png`, `.webp` |
| `EMPLOYEE_DOCUMENT` (sənəd skanı) | yuxarıdakılar **+ `.pdf`** |
| `FIELD_REPORT` (sahə hesabatı fotosu) | `.jpg`, `.jpeg`, `.png`, `.webp` |
| naməlum tip | **ən dar dəst** — yalnız şəkil (fail-closed) |

**Uzantı siyahısı `system_limits`-də DEYİL və bu, SEC-018 qərarıdır.**
`MAX_UPLOAD_SIZE_BYTES` konfiqurasiyadır, çünki o, **miqdardır**: Root onu
dəyişəndə qorumanın NÖVÜ dəyişmir, yalnız hədd sürüşür — və səhv dəyər (0/mənfi)
fallback-a qayıdır, yəni konfiqurasiya qorumanı söndürə bilmir. Uzantı siyahısı
isə **hücum səthinin özüdür**: cədvələ bir sətir (`.svg`, `.html`, `.exe`) əlavə
etmək icra oluna bilən məzmuna yol açardı və — daha pisi — həmin format üçün
imza yoxlaması olmadığından aşağıdakı məzmun qatı sükutla keçilərdi.

**İmza (magic bytes) yoxlaması ikinci qatdır:** uzantı fayl adının bir hissəsidir,
yəni onu yazan tərəf seçir (`zerarli.exe` → `sekil.jpg`). Ona görə baytların
başlanğıcı da yoxlanılır — `\xff\xd8\xff` (JPEG), `\x89PNG\r\n\x1a\n` (PNG),
`RIFF….WEBP`, `%PDF-`. Bu qat **Pillow-dan asılı deyil** (Pillow istəyə bağlı
asılıqdır və olmadıqda baytlar toxunulmadan buraxılır).

### 6.5. Kiçildilmə

| Parametr | Defolt | Nə edir |
|---|---|---|
| `EVIDENCE_FULL_MAX_EDGE_PX` | 1600 | Drive-a yüklənən şəklin maksimum kənarı |
| `EVIDENCE_THUMBNAIL_MAX_EDGE_PX` | 320 | Siyahı görünüşündəki kiçik şəkil |
| `EVIDENCE_JPEG_QUALITY` | 85 | JPEG keyfiyyəti |

Kiçildilmə **optimallaşdırmadır**: Pillow yoxdursa orijinal baytlar olduğu kimi
qaytarılır və məntiqin düzgünlüyü ondan asılı deyil. Yeni yüklənən şəkil dərhal
`ImageCache`-ə qoyulur ki, operator cəriməni yaratdıqdan sonra siyahıda onu
görmək üçün Drive-a getməsin. **PDF keşlənmir** — keş şəkil keşidir və oradan
gələn bayt kiçildilməyə verilir, PDF orada istisna atardı.

---

## 7. Kvota nəzarəti

`DriveQuotaMonitor` (`storage/quota_monitor.py`) aktiv bağlantının kvotasını
yoxlayır və `drive_connections` sətrindəki `quota_used_bytes` /
`quota_total_bytes` / `quota_checked_at` sahələrini yeniləyir.

| Hədd | Parametr | Davranış |
|---|---|---|
| **90%** | `DRIVE_QUOTA_WARNING_RATIO` (0.90) | Root/CEO-ya bildiriş — mövcud `Notifier` kanalı ilə |
| **100%** | — | Status avtomatik `ACTIVE` → **`QUOTA_EXCEEDED`** (`update_quota(..., mark_exceeded=True)`) |
| Təkrar susma | `DRIVE_QUOTA_WARNING_COOLDOWN_DAYS` (7) | `quota_warning_sent_at` ilə: eyni hədd üçün bir dəfə göndərilir; kvota aşağı düşüb yenidən qalxarsa yenidən göndərilir |

Ayrıca bildiriş kanalı qurulmayıb və bu, qəsdlidir: `Notifier` portu onsuz da
in-app + kritik hallarda e-poçt fallback-ini idarə edir; ayrıca kanal olsaydı
admin bildirişləri iki fərqli yerdə axtarmalı olardı. Təkrar-xəbərdarlıq
qorunması da vacibdir — gündəlik yoxlama sadə «90%-i keçib?» şərti ilə hər gün
eyni bildirişi göndərərdi və admin onları oxumağı dayandırardı (alarm yorğunluğu).

**İş qrafiki:** monitor gündəlik **`DRIVE_QUOTA_CHECK`** planlaşdırılmış işi ilə
çağırılır (`composition._register_scheduled_jobs`, `JobCadence.DAILY`,
`JobWeight.LIGHT`) — yəni GUI taymeri də, `--run-scheduled-jobs` də onu işlədir.
Ritm `DAILY`-dir, çünki təkrar-susma müddəti GÜN vahidlidir; `HOURLY` seçsəydik,
kvota 90%-i keçən gün 24 Drive API sorğusu edilər, xəbərdarlıq isə yenə günə bir
dəfə gedərdi. Google açarları təyin edilməyibsə iş **sakit dayanır** (`SUCCEEDED`,
izahı «Drive konfiqurasiya edilməyib») — bax `docs/scheduler_setup.md`.

> **Tarixçə — bağlanmış boşluq.** Sinif yazılıb, test edilib və
> `storage/__init__.py`-dan ixrac olunmuşdu, lakin `check()`-in istehsalat
> kodunda **heç bir çağıranı yox idi**: planlaşdırılmış işlər siyahısında kvota
> işi YOX İDİ. Praktik nəticə: 90% xəbərdarlığı və avtomatik `QUOTA_EXCEEDED`
> keçidi BAŞ VERMİRDİ və kvota dolduqda ilk siqnal yükləmənin
> `DriveQuotaExceededError` ilə uğursuz olması olurdu. Söhbət cərimə SÜBUT
> şəkillərindən gedir — mübahisə halında cərimənin yeganə əsaslandırmasından —
> ona görə xəbərdarlıqsız itmə qəbuledilməz idi.

---

## 8. Nasazlıq axtarışı

### 8.1. «Şəkillər Drive-a getmir, amma cərimələr yaranır»

**Simptom:** cərimələr normal, `evidence_upload_status = 'PENDING'` qalır,
`evidence_spool/` qovluğu böyüyür, jurnalda `EVIDENCE_UPLOAD_RETRY` yoxdur.

**Ən ehtimallı səbəb:** `KOMPASOS_GOOGLE_CLIENT_ID` və ya
`KOMPASOS_GOOGLE_CLIENT_SECRET` boşdur → `drive_providers()` `None` qaytarır və
növbə heç cəhd də etmir. **Yoxlayın:** `.env` faylında hər ikisi doludurmu.

**İkinci ehtimal:** aktiv `drive_connections` sətri yoxdur
(`NoActiveDriveConnectionError`) — hesab heç vaxt qoşulmayıb. **Yoxlayın:**
Drive Bağlantısı ekranı boşdurmu.

### 8.2. «Bir şəkil dönə-dönə uğursuz olur»

**Simptom:** jurnalda eyni `entry_id` üçün `EVIDENCE_UPLOAD_RETRY` təkrarlanır,
`attempts` sayğacı artır.

**Ayırd etmə:** `last_error` sahəsinə baxın.

| `last_error` | Nə deməkdir |
|---|---|
| `HTTP 429` / `5xx` | Drive API səs-küyü — özü keçəcək, müdaxilə lazım deyil |
| `Access token alınmadı (HTTP 4xx)` | Razılıq geri alınıb → hesabı yenidən qoşun (§5.3) |
| `Drive kvotası: …` | Hesab dolub → yeni hesab qoşun (köhnəsi `ARCHIVED` olub oxunacaq) |
| ölçü/uzantı/imza mətni | Element `REJECTED` olmalıdır; hələ də təkrarlanırsa köhnə buraxılışdan qalmış sətirdir |

### 8.3. «Element `PROCESSING`-də ilişib»

**Simptom:** SQLite-da `status = 'PROCESSING'`, `uploaded_at` boş, heç nə baş
vermir.

**Səbəb:** işçi proses claim-dən sonra çökdü. **Həll: heç nə** — köhnəlmə
müddəti (`UPLOAD_CLAIM_STALE_AFTER_SECONDS`, defolt 600 s) bitəndən sonra element
avtomatik yenidən claim edilir. Əl müdaxiləsi tələb olunmur; 10 dəqiqədən sonra
da dəyişmirsə fon dövrəsi ümumiyyətlə işləmir (§8.1-ə qayıdın).

### 8.4. «Razılıq axını brauzerdə açılır, amma tamamlanmır»

| Simptom | Ehtimallı səbəb |
|---|---|
| Google `redirect_uri_mismatch` deyir | Google Cloud Console-da klient tipi **Desktop app** deyil. Loopback portu hər dəfə dəyişir və yalnız bu tip bütün loopback portlarına icazə verir |
| Brauzer «Hesab qoşuldu» göstərir, ekranda dəyişiklik yoxdur | Kontroller `poll()`-u dayandırıb — 5 dəqiqəlik taymaut (`DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS`) keçib. 2FA/hesab seçimi uzun çəkirsə həmin parametri Root panelindən artırın |
| «refresh_token gəlmədi» | Hesab əvvəllər qoşulub və Google təkrar razılıqda token göndərmir. Axın onsuz da `prompt=consent` göndərir; problem davam edərsə Google hesabının «Üçüncü tərəf tətbiqləri» bölməsindən KompasOS-un icazəsini ləğv edib yenidən qoşun |
| Menyuda «Drive Bağlantısı» görünmür | İstifadəçidə `can_manage_drive_connection` flag-i yoxdur (defolt yalnız ROOT/CEO) |

### 8.5. «Köhnə cərimələrin şəkilləri açılmır»

Yeni Drive hesabı qoşulub, lakin köhnə sətirlərin
`evidence_drive_connection_id`-si **köhnə** bağlantını göstərir. Bu, düzgün
davranışdır (§5.4). Şəkil açılmırsa:

* Köhnə sətir `ARCHIVED` deyil, **silinib** — onda `evidence_drive_connection_id`
  `NULL`-dır və oxuma mümkün deyil. `photo_evidence_url` doludursa şəkil hələ də
  Supabase Storage-dadır (köçürmədən əvvəlki dövr).
* Köhnə hesabın razılığı Google tərəfindən ləğv edilib — həmin hesabı yenidən
  qoşmaq lazımdır; `ARCHIVED` sətir OXUMA üçün öz `refresh_token`-indən istifadə
  edir.

---

## 9. Əlaqəli sənədlər

| Mövzu | Sənəd |
|---|---|
| Drive-a aid 17 ROOT parametri (defolt, aralıq, təsir) | [`root_parameters.md`](root_parameters.md) §6 |
| Təhlükəsizlik qərarları (SEC-015, SEC-017, SEC-018) | [`security_decisions.md`](security_decisions.md) |
| Sxem və miqrasiya | `database/migrations/002_drive_evidence_storage.sql` |
| Mühit dəyişənləri | `.env.example` — «Cərimə sübut şəkilləri» bölməsi |
