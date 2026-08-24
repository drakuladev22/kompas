# Performans qeydləri — «proqram gec işləyir» şikayətinin araşdırılması

Bu sənəd kod deyil: **ölçülmüş rəqəmləri**, onlardan çıxan qərarları və
**rədd edilən alternativləri** saxlayır. Səbəb sadədir — performans
düzəlişləri sonradan «lazımsız mürəkkəblik» kimi görünür və geri qaytarılır;
rəqəm olmadan həmin müzakirə yenidən sıfırdan başlayır.

Ölçmə mühiti: Windows 11, Supabase Session Pooler, `.env`-siz (paketlənmiş
`.exe` ilə eyni şərtlər). **Bir şəbəkə gediş-gəlişi ≈ 206 ms.**

---

## Tapıntı: yavaşlığın səbəbi alqoritm deyil, GEDİŞ-GƏLİŞ SAYIDIR

Heç bir sorğu ağır deyil. Ağır olan onların SAYIDIR: bazaya hər müraciət
təxminən beşdə bir saniyə əlavə edir və istifadəçinin bir düymə basılışı
arxasında altı-on bir müraciət dururdu.

```
tək SELECT 1 (xalis gediş-gəliş)                    206 ms
```

---

## PERF-1 — sessiyanın öz yükü

### Nə tapıldı

`PostgresUnitOfWork.__enter__` üç artıq gediş-gəliş ödəyirdi:

| Addım | Ölçülmüş | İzah |
|---|---|---|
| `conn.execute("BEGIN")` | **412 ms** | Hovuz `autocommit=False`-dur, yəni psycopg tranzaksiyanı ONSUZ DA açır. Bizim `BEGIN` onun içində icra olunurdu: PostgreSQL `there is already a transaction in progress` xəbərdarlığı qaytarırdı (canlı bazada təsdiqlənib) və iki gediş-gəliş yeyirdi. |
| `set_config` × 2 | 412 ms | Hər GUC (`app.tenant_id`, `app.user_id`) üçün ayrıca sorğu. `set_config()` adi funksiyadır — bir `SELECT`-də ikisi də çağırıla bilər. |
| `commit()` sonrası `BEGIN` | 412 ms | `COMMIT` → açıq `BEGIN` → kontekst. `COMMIT AND CHAIN` bunu bir gediş-gəlişdə edir. |

### Nəticə (ölçülmüş)

| Ssenari | Əvvəl | Sonra |
|---|---|---|
| Boş sessiya (aç/bağla) | 1051 ms | **628 ms** |
| Sessiya + bir sorğu | 1261 ms | **829 ms** |
| Yazı formalı sessiya (sorğu + commit + çıxış) | ~2270 ms | **1283 ms** |

### Dəyişməyən şey

`SET LOCAL` semantikası (SEC-008) **toxunulmadı**. Kontekst `commit()`-dən
sonra hər dəfə YENİDƏN tətbiq olunur, çünki `AND CHAIN` yalnız tranzaksiya
xarakteristikalarını daşıyır, `SET LOCAL` dəyərlərini yox.

### Rədd edilən alternativlər

**1. `conn.pipeline()` ilə kontekst + ilk sorğunu birləşdirmək.** Ölçüldü:
841 → 631 ms, yəni daha 210 ms. RƏDD EDİLDİ: pipeline rejimində xəta artıq
`execute()` anında deyil, sinxronizasiya nöqtəsində qalxır. Repozitoriyaların
bir qismi `psycopg.errors`-u məhz `execute()` ətrafında tutur (məs. unikal
pozuntu emalı) — qazanc bütün yazma yollarının yenidən yoxlanılmasını tələb
edərdi. Ayrıca addım kimi qiymətləndirilməlidir.

**2. GUC-ları SESSİYA səviyyəsində qoyub hovuza qaytarılanda sıfırlamaq.**
Bu, `commit()` sonrası kontekst tətbiqini TAMAMİLƏ aradan qaldırardı.
RƏDD EDİLDİ: SEC-008 `SET LOCAL`-ı (adi `SET` yox) struktur zəmanət kimi
sənədləşdirib — izolyasiyanı bazanın özü tətbiq edir, bizim `reset`
çağırışımız yox. Sürət üçün təhlükəsizlik zəmanətini geri addımlamaq
CLAUDE.md §5-in birbaşa pozulmasıdır.

**3. Bağlantı proxy-si ilə kontekstin TƏNBƏL tətbiqi.** `commit()`-dən sonra
tranzaksiya açılmazdı; kontekst növbəti sorğuda tətbiq olunardı və dərhal
çıxılan sessiyalar iki gediş-gəlişə qənaət edərdi. RƏDD EDİLDİ (hələlik):
repozitoriyalar bağlantını BİRBAŞA saxlayır və use case-lər onları commit
boyu əldə tutur — yəni proxy 40-dan çox repozitoriyanın hər sorğusunun
üstündən keçməlidir. Buraxılışdan əvvəl belə bir dəyişikliyin riski
qazancından böyükdür.

---

## PERF-2 — bir giriş cəhdi ÜÇ tranzaksiya açırdı

`app._SessionScopedLogin` başlığı belə vəd edirdi: «Üçü BİR sinifdədir, çünki
hər üçü eyni sətri oxuyur; ayrı-ayrı olsaydılar bir giriş cəhdi üç ardıcıl
tranzaksiya açardı». Vəd yerinə yetirilmirdi — üç metodun hər biri öz
sessiyasını açırdı.

Sərhəd `AuthController.authenticate()`-ə qoyuldu (`AttemptScope`), çünki
«cəhd nə vaxt başlayıb nə vaxt bitir» sualının cavabını yalnız kontroller
bilir.

| Ssenari | Əvvəl | Sonra |
|---|---|---|
| Giriş cəhdi (uçtan-uca, real obyekt qrafı) | 2272 ms | **1704 ms** |

Ölçmə MÖVCUD OLMAYAN istifadəçi adı ilə aparılıb: axın eynidir (sabit-vaxt
qoruması), lakin real hesabın uğursuz-cəhd sayğacına toxunmur. Mövcud hesabda
qazanc daha böyükdür, çünki orada üçüncü oxu (`credentials_for`) da baş verir.

**PERF-1 + PERF-2 birlikdə:** giriş ≈ 3.4 saniyədən **1.7 saniyəyə** düşür.

---

## UX-1 — düymə «gec cavab verir», halbuki iş dərhal başlayır

Kontrollerlər bloklayan işdən əvvəl `set_busy(True)` çağırırdı, lakin Qt həmin
dəyişikliyi yalnız hadisə dövrəsinə qayıdanda çəkir — bloklayan sorğu isə
qayıdışdan ƏVVƏL başlayırdı. İstifadəçi düyməyə basır və ekranda saniyələrlə
HEÇ NƏ dəyişmirdi.

Həll: `presentation/controllers/ui_feedback.flush_ui()` — `set_busy(True)`-dan
sonra, bloklamadan əvvəl çağırılır. Qayda `connection_settings.py`-da artıq
vardı; indi ortaq modula çıxarılıb (CLAUDE.md §5: eyni qaydanın iki nüsxəsi
sürüşür).

Tətbiq olunan yerlər: giriş (şifrə və üz), cihaz qeydiyyatı, üz qeydiyyatı,
bağlantı ayarları. `recovery_console` və `erp_servers` bunu TƏLƏB ETMİR —
onlar artıq `BackgroundTask` ilə fon sapında işləyir.

---

## PERF-3 — panelin açılışı 13 tranzaksiya idi

### Nə tapıldı

`show_admin()` girişdən sonra bir sıra kiçik oxu edir. Hər biri ÖZ sessiyasını
açırdı; çağırış zənciri ilə birlikdə ölçüldü:

| Oxu | Haradan |
|---|---|
| saxlanmış tema | `app.py:_apply_stored_theme` |
| sistem limitləri (×2) | `infrastructure/config/limits.py:_decimal` |
| planlayıcı intervalı | `job_runner.poll_interval` |
| plugin siyahısı | `app.py:_collect_plugin_pages` |
| aktiv modullar | `app.py:_enabled_modules` |
| cərimə növləri | `controllers/fine_entry.options` |
| işçi adları | `controllers/sales_review.employee_names` |
| dəstək nişanı | `controllers/support_chat.refresh_badge` |
| bildirişlər | `controllers/notifications._load` |
| kontekst altyazıları | `app.py:_refresh_context_subtitles` |
| dəstək sayğacları | `app.py:_refresh_support_badges` |
| ilk ekran | `controllers/screen_data.populate` |

### Həll

`ApplicationContext.read_batch()` — açılış oxularını BİR tranzaksiyada
birləşdirən sərhəd. Sərhəd `show_admin`-dədir, çünki «açılış nə vaxt başlayıb
nə vaxt bitir» sualının cavabını yalnız o bilir.

**Toplu SAPA GÖRƏ ayrıdır (`threading.local`).** `BackgroundTask` bəzi
ekranlarda fon sapında sorğu edir; qlobal toplu həmin sapın əsas sapın psycopg
bağlantısına eyni anda yazmasına səbəb olardı — psycopg bağlantısı
sap-təhlükəsiz DEYİL və nəticə sükutlu pozulma olardı.

**`user_id=None` oxusu da topluya düşür.** Təhlükəsizdir: `app.user_id` heç bir
RLS OXU siyasətində işlənmir — onu yalnız `position_permissions` üzərindəki
`DELETE` trigger-i oxuyur (miqrasiya 046).

| Ölçü | Əvvəl | Sonra |
|---|---|---|
| `show_admin` tranzaksiya sayı | 13 | **4** |
| `show_admin` müddəti | 18.0 s | **13.1 s** |

### Uzun tranzaksiya qadağasını (CLAUDE.md §6) pozmur

Qadağa PANELİN ÖMRÜ boyu açıq qalan sessiyaya aiddir. Bu toplu açılış
burstudur — saniyələrlə ölçülür və `with` bloku bitən kimi bağlanır.
Kontrollerlərin əməliyyat-başına-sessiya qaydası dəyişmir.

---

## Panellərin canlı ölçüsü (Root hesabı, 41 ekran)

Hər ekran `AdminShell.show_screen()` ilə FAKTİKİ qurulub və canlı sorğularını
edib. Nəticə: **41/41 ekran işləyir, çökmə yoxdur.**

| Ekran | Müddət | Sessiya |
|---|---|---|
| dashboard | 5.9 s | 1 |
| technical_support | 5.4 s | 4 |
| face_enrollment | 4.4 s | 1 |
| internal_requests | 4.4 s | 3 |
| permissions | 4.1 s | 2 |
| … qalan 36 ekran | 0.7–3.5 s | 1–3 |

**Hər ekranın vaxtının 99–100 %-i baza gözləməsidir** — çəkiliş (rendering)
praktik olaraq sıfırdır. Yəni ekranları «yüngülləşdirmək» heç nə verməz;
yeganə lever sorğu sayı və gediş-gəliş müddətidir.

`show_admin` ayrıca profilləndi: **59 sorğu**, ekran modullarının idxalı isə
cəmi **15 ms**. Yəni yavaşlıq Python-da deyil, şəbəkədədir.

---

## ƏN BÖYÜK LEVER: baza Sinqapurdadır, istifadəçi Bakıda

Cari DSN: `aws-0-ap-southeast-1.pooler.supabase.com` — **Sinqapur**.

TCP əl sıxma ölçüldü (sorğu yox, xalis məsafə; 5 cəhdin ortası):

| Region | Orta | Minimum |
|---|---|---|
| **ap-southeast-1 (Sinqapur) — cari** | **216 ms** | 206 ms |
| eu-central-1 (Frankfurt) | **83 ms** | 70 ms |
| eu-west-3 (Paris) | 91 ms | 78 ms |
| eu-west-2 (London) | 99 ms | 84 ms |
| eu-west-1 (İrlandiya) | 113 ms | 106 ms |
| us-east-1 (Virciniya) | 166 ms | 153 ms |

Frankfurt **2.6× yaxındır**. Bütün ölçülən vaxtlar birbaşa bu əmsala bölünür:

| Əməliyyat | Sinqapur (cari) | Frankfurt (təxmin) |
|---|---|---|
| Panelin açılışı | 13.1 s | ~5 s |
| Giriş | 1.7 s | ~0.7 s |
| Orta ekran | 0.9–5.9 s | 0.35–2.3 s |

**Bu, KOD DƏYİŞİKLİYİ TƏLƏB ETMİR** — Supabase layihəsinin regionunu dəyişmək
(və ya yeni layihəyə köçürmək) kifayətdir. Heç bir kod optimallaşdırması bu
qazancın yaxınına gəlmir: 59 sorğunun hər biri 206 ms əvəzinə 70 ms çəkəcək.

---

## LAYOUT-1 — üç panel BOŞ render olunurdu (performans deyil, DAVRANIŞ)

Panel auditində tapıldı və ölçmə ilə təsdiqləndi. `Screen.__init__` `self`
üzərində `QVBoxLayout` qurur; üç ekran bunun üstünə İKİNCİ layout yazırdı:

    QLayout: Attempting to add QLayout "" to DeviceAdminScreen "ScreenSurface",
    which already has a layout

Qt ikinci layout-u QURMUR. Ekran istisnasız qurulur, `show_screen()` `True`
qaytarır, sorğuları da işləyir — LAKİN bütün məzmun valideynsiz qalır və
istifadəçi BOŞ ekran görür.

| Ekran | Menyu maddəsi |
|---|---|
| `DeviceAdminScreen` | Cihazlar |
| `SupportInboxScreen` | Daxili Müraciətlər |
| `SupportInboxScreen` | Texniki Dəstək |

Yəni Root-un ən çox ehtiyac duyduğu üç panel boş idi. Ölçmə: 41 ekran
Qt xəbərdarlıq tutucusu ilə qurulub — əvvəl 3 pozuq, düzəlişdən sonra **0**.

Qapı: `tests/unit/test_screen_layout_ownership.py` (AST — bazasız işləyir).

---

## PERF-5 — İdarə Paneli 17 sorğu, Sağlamlıq ekranı İKİ sessiya idi

Ölçmə üsulu: `psycopg.Cursor.execute` sarındı, hər ekran `ScreenDataBinder.
populate()` ilə CANLI bazaya qarşı açıldı (boş kirayəçi, Sinqapur pooler,
gediş-gəliş ~206 ms). Ölçülən şey ekranın çəkilişi deyil — göndərilən sorğu
və açılan tranzaksiya sayıdır.

### Nə tapıldı

| Qüsur | Ölçülmüş |
|---|---|
| `MultiStoreBenchmarkUseCase.trend()` N ayı N AYRI sorğu ilə oxuyurdu | 6 aya 5 əlavə sorğu |
| `ranking()` cari və əvvəlki ayı iki sorğu ilə oxuyurdu | +1 sorğu |
| Açıq sessiyanın İÇİNDƏ limit oxusu (`NtpVerifier` → `NTP_*`) İKİNCİ tranzaksiya açırdı | +1 sessiya (~0.63 s) |

Üçüncüsü ən gizlisi idi: `read_batch()` (PERF-3) iş vahidini limit
körpüləri ilə paylaşırdı, LAKİN yalnız AÇILIŞ topluları üçün. Ekranın öz
sessiyası paylaşmırdı — yəni eyni sapda, eyni kirayəçidə AÇIQ tranzaksiya
dururkən limit oxusu yenisini açırdı.

### Həll

* `BatchedMetricProvider` (OPSİYONAL port, `multi_store_benchmark.py`) —
  `metric_values_by_period()` N aralığı BİR sorğuda oxuyur. Postgres tərəfi
  MÖVCUD metrik SQL-ini `UNION ALL` ilə N dəfə sarıyır: aylıq sorğu dəsti
  İKİNCİ nüsxədə YAZILMIR (`AVG`/`HAVING` semantikası hərfən qorunur).
* Provayder metodu dəstəkləmirsə (yaddaş-daxili sahtələr) köhnə dövrə
  işləyir — nəticə eynidir, yalnız sorğu sayı fərqlidir.
* `ApplicationContext.session()` açıq iş vahidini limit körpüləri ilə
  PAYLAŞIR (`_read_batch.uow`), sessiya bitəndə bərpa edir.

### Nəticə (canlı ölçü, əvvəl → sonra)

| Ekran | Əvvəl | Sonra |
|---|---|---|
| `dashboard` | 5251 ms / 17 sorğu | **3247 ms / 13 sorğu** |
| `health` | 3777 ms / 8 sorğu / 2 sessiya | **1900 ms / 7 sorğu / 1 sessiya** |
| `sales_points` | 2107 ms / 8 sorğu | **1896 ms / 7 sorğu** |
| `audit` | 5 sorğu (səhifə + say AYRI) | **4 sorğu** — `count(*) OVER ()` |

İki əlavə təkrar da bağlandı:

* `_sales_points` mükafat kataloqunu İKİ dəfə oxuyurdu — biri ekranın
  siyahısı, digəri «növbəti mükafat» düsturu (`_next_reward_gap`). İndi bir
  dəfə oxunur və hər ikisinə verilir.
* `AuditQueryUseCase.search` səhifəni və ümumi sayı AYRI sorğularla alırdı;
  `PostgresAuditReader.query_page` pəncərə funksiyası ilə ikisini birləşdirir.
  BOŞ səhifədə (süzgəc heç nə tapmayıb VƏ YA `offset` dəstdən kənardadır)
  `count()` yenə çağırılır — pəncərə dəyəri sətir olmadıqda MÖVCUD DEYİL.

Qapı: `tests/unit/test_benchmark_batched_reads.py` (sayğac testi, bazasız).

### Şübhələnilən, LAKİN ölçüdə TƏMİZ çıxan dörd yer

Bunlar «yavaş ola bilər» siyahısındaydı; ölçü göstərdi ki, düzəliş TƏLƏB
ETMİRLƏR. Rəqəmlər burada saxlanılır ki, eyni şübhə ikinci dəfə araşdırılmasın.

| Nə ölçüldü | Nəticə |
|---|---|
| Excel ixracı (`ExcelReportWriter.write_table`) | 1000 sətir **68 ms**, 5000 sətir 273 ms, 20 000 sətir 1174 ms — xətti. İxrac onsuz da `BackgroundTask`-dadır (`report_export.py`), UI sapı bloklanmır |
| Üz aşkarlama (HOG, 640×480 kadr) | **102 ms** |
| 1:N üz müqayisəsi (500 profil) | **0.4 ms** — hədəf 3 saniyə idi; baza tərəfi də tək sorğudur (`list_store_profiles`) |
| Yaddaş sızması: 38 ekran × 32 dövr (1216 quruluş) | 16.58 → **16.62 MB** (+45 KB, +0.3 %), artım FASİLƏSİZ DEYİL — sızma yoxdur |
| Paketdəki istifadəsiz Qt modulları | `dist/`-də `Qt6WebEngine*.dll` YOXDUR — `.spec`-in `_UNUSED_QT_MODULES` siyahısı işləyir |

### Qalan ən yavaş üçlük (ölçülmüş, hələ toxunulmayıb)

| Ekran | Müddət | Sorğu |
|---|---|---|
| `dashboard` | 3247 ms | 13 |
| `sales_points` | 2107 ms | 8 |
| `audit` | 1641 ms | 5 |

---

## PERF-6 — giriş öncəsi/sonrası GUI sapının donması (SPEED-FIX Faza 3)

Tapıntılar `time.perf_counter()` ilə, real Supabase bağlantısı ilə ölçülüb
(sinqapur pooler, gediş-gəliş ~206 ms — yuxarıdakı ölçmə mühiti ilə eyni).

### 1 — `_after_splash()`: İKİ AYRI sessiya, 1724 ms

`app.py::_startup_route()` (864 ms) və `face_login.py::FaceLoginController.
available()` (860 ms, `show_login()` çağırır) hər biri ÖZ sessiyasını açırdı.
`read_batch()` (PERF-3) buraya tətbiq olunmamışdı, çünki iki oxu fərqli
metodlardadır və aralarında marşrut budaqlanması var — BİR yerdə açılıb
BAĞLANMALI sərhəd yox idi.

**Həll:** `_after_splash()` marşrutlaşdırmanı `_route_after_splash()`-a çıxarır
və onu `context.read_batch()` sərhədinə salır; `show_login()`-un içindəki
`_face_login_available()` HƏMİN sərhədin içindən çağırıldığı üçün paylaşılmış
sessiyanı təkrar istifadə edir (`ApplicationContext.session()`-in aktor şərti:
`user_id=None` hər ikisinə uyğun gəlir).

| Ssenari | Əvvəl | Sonra (gözlənilən) |
|---|---|---|
| Splash bitdikdən login ekranına qədər | 1724 ms (2 sessiya) | **~860 ms** (1 sessiya) |

**Canlı ölçü (`perf-startup`, 4 işə salma) BU RƏQƏMİ DÜZƏLDİR:** faktiki
nəticə ~860 ms deyil, **1050–1160 ms** oldu — `read_batch()` yalnız SESSİYA
QURULMASINI (BEGIN/kontekst, ~0.63 s) paylaşır, İKİ sorğunun ŞƏBƏKƏ vaxtı
(hər biri ~206 ms+) QALIR. `MAIN_THREAD_STALL` həddi 1000 ms-dir
(`stall_monitor.py`) — köhnə 1724 ms onu HƏMİŞƏ keçirdi, yeni 1050–1160 ms
İSƏ sərhəddə YELLƏNİR (4 işə salmadan 1-də `stall_ms=1050` loqa düşdü).
Yəni bu addım TƏK BAŞINA kifayət ETMƏDİ — 1a bölməsinə bax.

### 1a — post-splash: qalan 1050–1160 ms-i UI sapından TAM çıxarmaq

`_after_splash()`-ın 1-ci bölmədəki düzəlişi iki oxunu BİR sessiyaya yığdı,
lakin onlar YENƏ splash BİTDİKDƏN SONRA, GUI sapında sinxron işləyirdi.
Splash-ın ARXASINDA isə ARTIQ bir fon mərhələsi var idi
(`_load_context_behind_splash` → `build_context()`, ~2.4–2.7 s, UI donmur) —
məhz bu mərhələnin SONUNA, kontekst hazır olan kimi, iki oxunu da əlavə etmək
mümkün oldu.

**Həll:** `_load_context_behind_splash`-ın fon işi (`task.run(_job)`) indi
`factory()` (`build_context()`, DƏYİŞMƏDƏN) bitdikdən SONRA `_compute_
startup_preload(context)`-u da ÇAĞIRIR — `_resolve_startup_route()`
(`_startup_route()`-un `self`-siz NÜVƏSİ, modul-səviyyəli funksiyaya
çıxarılıb) + `FaceLoginController(context).available()`. Nəticə
`application.set_startup_preload()` YAN TƏSİRİ ilə çatdırılır (`_load_
context_behind_splash`-ın PUBLİK 4-elementli qaytarış imzası DƏYİŞMƏDİ —
mövcud testlər onu birbaşa açır). `_after_splash()` preload varsa
`read_batch()`-i ÜMUMİYYƏTLƏ AÇMIR; `show_login(face_login_available=...)`
YENİ, OPSİYONAL parametr aldı ki, `_route_after_splash` dəyəri BİRBAŞA ötürə
bilsin. Preload BİR DƏFƏLİK istifadə olunub TƏMİZLƏNİR (`self._startup_
preload = None`) — sonrakı `show_login()` çağırışları (logout, sessiya
bitmə) YENƏ CANLI oxuyur, köhnəlmiş dəyər əbədi keşlənmir.

**Uğursuzluq halı:** `_resolve_startup_route`/`FaceLoginController.available()`
HƏR İKİSİ ÖZ istisnalarını ARTIQ daxildə tutur (mövcud davranış) və
təhlükəsiz dəyərə (`LOGIN`, `False`) düşür; `_job()` daxilində ƏLAVƏ
`try/except` DƏ var ki, gözlənilməz bir səhv UĞURLU kontekst qurulmasını
fatal başlanğıc xətasına ÇEVİRMƏSİN — `build_context()`-in ÖZÜ dəyişmədi və
onun uğursuzluğu HƏLƏ DƏ eyni fatal-ekran yolunu işlədir.

| Ölçü | Əvvəl | Sonra (gözlənilən) |
|---|---|---|
| Splash bitdikdən login ekranına qədər (GUI donması) | 1050–1160 ms | **~0 ms** (iki oxu artıq fon mərhələsindədir) |
| Splash arxasındakı fon mərhələsinin müddəti | ~2.4–2.7 s | ~3.5 s (donma DEYİL, splash animasiya edir) |
| ÜMUMİ açılış müddəti | dəyişmir (təxminən) | dəyişmir — 1.1 saniyə DONMA olmaqdan çıxır, cəmə əlavə OLUNMUR |

**Yoxlama (manual skript, `tests/`-ə YAZILMADI):** preload mövcud olanda
`read_batch()`-in ÜMUMİYYƏTLƏ çağırılmadığı, preload-un BİR DƏFƏLİK
işləndiyi, preload yoxdursa köhnə (`read_batch()`) yolun toxunulmaz qaldığı
VƏ `self._preview`-un qısa-dövrə davranışının (preview-də `_face_login_
available()` ÇAĞIRILMIR) qorunduğu — dörd ssenari ilə təsdiqləndi. Ayrıca
`_resolve_startup_route`-un `test_startup_route.py`-dəki DÖRD halın (boş
baza/SETUP_WIZARD, dolu baza/LOGIN, sxem yox/SCHEMA_MISSING, naməlum
xəta/LOGIN) HƏR BİRİNİ `_startup_route()` ilə EYNİ verdiyi təsdiqləndi.

**Canlı ölçü (`perf-startup`, 4 işə salma) BÖLGÜNÜ DÜZƏLDİR:** splash
arxasındakı ÜMUMİ fon işi gözlənilən "~3.5 s" DEYİL, **4235–4636 ms**
(orta ~4360 ms) oldu — yuxarıdakı cədvəldəki "~700–900 ms ARTIQ". Səbəb
TƏXMİN DEYİL, ÖLÇÜLÜB: `_compute_startup_preload()` → `FaceLoginController.
available()` → `camera_available()` `cv2`-ni İLK DƏFƏ idxal edir
(`camera.py:108`, soyuq keşdə 70–624 ms). Bu idxal ƏVVƏL `show_login()`-da,
UI SAPINDA baş verirdi və 1-ci bölmədəki 1724/1050–1160 ms donmanın BİR
HİSSƏSİ idi — indi fon sapına köçüb, LAKİN silinmədi, YERİ dəyişdi.
Riyaziyyat: 2353 ms (`build_context`) + ~1075 ms (iki oxu) + ~600 ms
(soyuq `cv2`) ≈ 4030–4630 ms — müşahidə ilə uyğundur.

**"ÜMUMİ açılış müddəti dəyişmir (təxminən)" sətri DƏQİQLƏŞDİRİLİR:** cəm
HƏQİQƏTƏN dəyişməyib (yalnız BÖLGÜSÜ dəyişib — `cv2` xərci UI donmasından
fon animasiyasına köçüb), lakin rəqəm artıq TƏXMİN deyil, ÖLÇÜLÜB. Bu,
REQRESSİYA DEYİL: istifadəçi bir qədər uzun, LAKİN CANLI (splash animasiya
edir) gözləyir; splash bitəndən sonra giriş ekranı DƏRHAL açılır.

**Gələcək maddə (bu sənəddə qeyd, İNDİ EDİLMİR):** `cv2` idxalı YALNIZ
«Üzlə daxil ol» düyməsinin görünüb-görünməyəcəyini həll edir — onu
splash-dan TAMAMILƏ çıxarıb (yalnız toggle-ı preload-da saxlayıb) giriş
ekranını DƏRHAL göstərmək, prob bitəndə düyməni aktivləşdirmək mümkündür
(~600 ms qazanc). Naxış `face_enrollment.py::FaceEnrollmentController.
_refresh_camera_state`-də ARTIQ var.

### 2 — `AuthController.authenticate()`: 1894 ms sinxron

`app.py::_authenticate()` `self._auth.authenticate(...)`-i birbaşa GUI
sapında çağırırdı. İzolyasiya ölçüsü: Argon2 hesablaması 34 ms (cəminin
~2%-i) — qalan vaxt şəbəkə/sessiya gediş-gəlişidir (PERF-1/2 ARTIQ onu bir
tranzaksiyaya salıb, lakin uzaq baza yenə uzaqdır).

**Həll:** `_on_face_login_requested`/`_on_face_login_succeeded`/`_on_face_
login_failed` üçlüyü ilə EYNİ naxış (yeni naxış icad edilmir):
`run_job(..., executor=self._executor)` çağırışı işi fon sapına verir,
nəticə `_on_password_login_succeeded`/`_on_password_login_failed`
slotlarında ƏSAS SAPDA qəbul edilir (Qt widget-ə YALNIZ orada toxunulur).
`executor=self._executor` ötürülür (`_attempt_startup` ilə eyni naxış) ki,
mövcud Qt-siz testlər `InlineExecutor` ilə sinxron yoxlana bilsin.

| Ssenari | Əvvəl | Sonra (gözlənilən) |
|---|---|---|
| "Daxil Ol" düyməsi → GUI sapının sərbəst qalması | 1894 ms bloklanma | **~0 ms** (iş fon sapında) |

**Test təsiri (qeyd, düzəldilməli deyil — `tests/` bu agentin sahəsi
deyil):** `_authenticate()` artıq DƏRHAL qayıdır, nəticəni gözləmir. Üç
mövcud test bunu sinxron fərz edirdi və `self._executor` təyin etmədən
`object.__new__(KompasApplication)` üzərində çağırırdı —
`test_login_and_startup_recovery.py::test_a_successful_login_reaches_the_
shell_instead_of_raising`, `::test_a_non_employee_result_is_reported_not_
crashed`, `test_busy_feedback.py::test_the_login_path_repaints_before_
authenticating`. Üçü də `_attempt_startup`-ın öz testlərindəki İLƏ EYNİ
bir sətirlə düzəlir: `application._executor = InlineExecutor()` (çağırışdan
ƏVVƏL, bax `test_login_and_startup_recovery.py::_application_with_
recorders`).

### 3 — `show_admin()`: 3.2–13.1 s, İKİ çağırış yerində (`app.py:1079`, `:950`)

**EDİLDİ (PERF-6, Mərhələ 2) — aşağıdakı yolla.**

İlk cəhddə (SPEED-FIX Faza 3) bu tapıntı FON SAPINA köçürülməmişdi: DB
oxuları və Qt widget qurulması `_build_admin_shell`-in HƏR SƏTRİNDƏ
növbələşirdi, sabit "əvvəlcə bütün oxular, sonra bütün widget-lər" sərhədi
YOX idi. Doğru həll kimi `ScreenDataBinder.populate()`-in imzasını
"fetch (fon) + tətbiq (əsas sap)" ayırmaq yazılmışdı — FAZA C/D
(`screen_data.py`, bax `ScreenDataBinder` başlığı) bunu BÜTÜN 14 binder
üçün tamamladıqdan SONRA bu bölmə artıq mümkün oldu.

**Həll:** `app.py::_fetch_admin_shell_preload()` `_build_admin_shell`-in
DB-yə toxunan HƏR addımını (tema, aktiv modullar, plugin səthi + reyestr,
İLK ekranın `ScreenDataBinder.prefetch_first_screen()` fetch-i, kontekst
altyazı sayğacları, dəstək nişanları, sübut/planlayıcı dövrə ritmləri,
sessiya-buraxılışı YAZISI (SEC-5), SEC-011-in üç `SessionGuard` limiti)
`context.read_batch()` daxilində, BİR `run_job()` çağırışı ilə FON SAPINDA
toplayır (`_AdminShellPreload` bağlaması). `show_admin()` bu işi buraxır və
DƏRHAL qayıdır; nəticə `_on_admin_shell_preload_ready`-də ƏSAS SAPDA
`_build_admin_shell(..., preload=...)`-ə keçir — bu metod ARTIQ HEÇ BİR
sətirdə DB-yə getmir, YALNIZ Qt qurur və hazır dəyərləri tətbiq edir.
İLK ekranın tətbiqi (`_register_screens::build()` daxilində) canlı
`ScreenDataBinder.populate()`-i ATLAYIR — ƏVƏZİNƏ fon sapında artıq hazır
olan closure (`_pending_first_screen_apply`) çağırılır.

`background_task.py`-nın «fon işi Qt widget-inə TOXUNMAMALIDIR» qaydası
POZULMUR: `AdminShell` və bütün ekranlar YENƏ DƏ, İSTİSNASIZ, əsas sapda
qurulur — fon sapı YALNIZ məlumat qaytarır.

**Fon işi tam İSTİSNA atsa** (son qoruyucu — normalda hər addım öz
try/except-i ilə qorunur): `_on_admin_shell_preload_failed` `_build_admin_
shell`-i `preload=None` ilə (KÖHNƏ, tək-tək canlı oxu yolu) çağırır və
`_notify_slow_admin_load()` (UI-1) istifadəçini xəbərdar edir — bu, köhnə
`read_batch()` FALLBACK-inin funksional YERİNİ tutur.

`on_ready` (YENİ, opsional parametr) `show_admin()`-in çağıranına (hər iki
giriş yolu, `_on_password_login_succeeded`/`_on_face_login_succeeded`)
"panel HƏQİQƏTƏN hazırdır" hadisəsini verir — `set_busy(True)`/`flush_ui()`
DƏYİŞMƏDƏN qalır (UX-1), `set_busy(False)` isə köhnə sinxron `finally`
ƏVƏZİNƏ bu callback-dən çağırılır (metod artıq DƏRHAL qayıtdığı üçün
`finally` fon işi hələ BAŞLAMAMIŞ işə düşərdi).

**«Klikdən panelə» ÖLÇÜLMƏDİ (canlı giriş tələb edir, bu dövrədə test hesabı
verilmədi) — rəqəm YAZILMIR, TƏXMİN DƏ EDİLMİR.** Zəmanət qapılardan gəlir:
`mypy`/`ruff` təmiz, hədəflənmiş test dəsti yaşıl (aşağıya bax) və kod
səviyyəsində `_build_admin_shell`-in `preload` yolunda HEÇ BİR sətir DB-yə
getmir — yəni GUI sapının DONMA MƏNBƏYİ struktur olaraq aradan qalxıb,
LAKİN bu, `perf-startup`-ın `MAIN_THREAD_STALL` ölçüsü ilə TƏSDİQLƏNMƏYİB.

**Yoxlama:** `mypy src` (380 fayl, strict) təmiz; `ruff check`/`format`
təmiz (`_build_admin_shell`/`_register_screens` ÜÇÜN `PLR0915` susdurulub —
`_build_session`/ekran qurucuları ilə EYNİ əsaslandırma, `_fetch_admin_
shell_preload`-in ÖZÜ isə 9 kiçik `_preload_*` köməkçisinə bölünüb).
Hədəflənmiş dəst yaşıl: `test_login_and_startup_recovery.py`,
`test_face_login_background.py`, `test_password_login_background.py`,
`test_busy_feedback.py`, `test_screen_data_thread_boundary.py`,
`test_screen_data_binding.py`, `test_read_batch_scope.py`,
`test_session_guard_e2e.py`, `test_session_touch_guard.py`,
`test_navigation_shell_ux.py`, `tests/e2e/test_shell_e2e.py` + geniş
`dashboard/admin_shell/shell/login/startup/session/screen_data/navigation`
süzgəci (362 keçdi) — **İKİ test faylı `show_admin`-i sahtələyən
lambda/funksiyanın imzasını `on_ready` qəbul edəcək şəkildə YENİLƏMƏLİDİR**
(`tests/` bu agentin sahəsi deyil, dəqiq dəyişiklik `qa`-ya bildirilib):
`test_login_and_startup_recovery.py:88` və
`test_face_login_background.py::test_successful_face_login_clears_the_
form_and_opens_the_panel`-in `_fake_show_admin` köməkçisi.

### 5 — `internal_requests` (4.4 s / 3 sessiya) və `technical_support` (5.4 s / 4 sessiya)

`app.py::_attach_support_inbox()` `SupportInboxController.attach()`-i
çağırırdı, o da İKİ ardıcıl sessiya açırdı (`_load_options` + `refresh`);
`refresh()`-in `_on_counts_changed` geri çağırışı (`app.py::_refresh_support_
badges`) ÜÇÜNCÜ sessiyanı `refresh()`-in ÖZ sessiyası BAĞLANDIQDAN SONRA
açırdı. `technical_support`-da `_build_telegram_poller()` (bot ayarlarını
oxuyur) DÖRDÜNCÜ sessiyanı, `attach()`-dən DAHA ƏVVƏL açırdı.

**Həll:** `_attach_support_inbox()`-un bədəni `context.read_batch(user_id=
self._current_employee.id)` sərhədinə salındı (1-ci PERF-6 tapıntısı ilə
EYNİ naxış). Bütün dörd oxu EYNİ aktorla işlədiyi üçün (yazı yolu YOXDUR:
`attach()` daxilində heç bir `session.commit()` çağırılmır) paylaşılmış
sessiyanı avtomatik təkrar istifadə edir.

| Ekran | Əvvəl | Sonra (gözlənilən) |
|---|---|---|
| `internal_requests` | 4.4 s / 3 sessiya | **~1 sessiya** |
| `technical_support` | 5.4 s / 4 sessiya | **~1 sessiya** |

### 6 — `permissions` (4.1 s / 2 sessiya)

`controllers/permission_matrix.py::refresh()` rol siyahısını oxuyub
`screen.select_role(active)` çağırırdı → bu, `role_selected` siqnalını
SİNXRON yayırdı → `_on_role_selected` DƏRHAL İKİNCİ sessiya açıb aktiv rolun
flag qruplarını oxuyurdu. İlk açılışda bu, ARTIQ MƏLUM olan (siyahının
BİRİNCİSİ) rolun təkrar sorğusu idi.

**Həll:** `first_open` (`self._active is None`) halında ilk rolun flag
qrupları `list_roles` İLƏ EYNİ sessiyada oxunur; `PermissionMatrixScreen`-ə
YENİ `set_active_role()` setter-i əlavə olundu (`group_c.py`) — `select_role()`-
un SİQNALSIZ forması, YALNIZ vizual vurğunu qurur. `refresh()` bu YENİ
setter-i (varsa) çağırıb matrisi BİRBAŞA `set_matrix()` ilə doldurur —
`_on_role_selected` təkrar sorğu göndərmir. `getattr` naxışı (`_set_busy`,
`face_control.py`, ilə EYNİ) köhnə setter-i daşımayan ekran/test sahtələrini
qoruyur: onlar köhnə (siqnallı, iki sessiyalı) yolda qalır.

SONRAKI `refresh()` çağırışları (yadda saxladıqdan/rol yaratdıqdan sonra) BU
YOLU İŞLƏTMİR: `self._active` ARTIQ dolu olduğu üçün `first_open` `False`-dur
və `select_role()` köhnə (siqnallı) yolla işləyir — flag-lər məhz belə
hallarda dəyişmiş ola bilər və TƏZƏ oxu doğru davranışdır. İstifadəçinin ƏL
İLƏ rol dəyişməsi TOXUNULMADI: düymə kliki `select_role()`-u birbaşa çağırır.

| Ssenari | Əvvəl | Sonra (gözlənilən) |
|---|---|---|
| `permissions` İLK açılış | 4.1 s / 2 sessiya | **~1 sessiya** |
| Rolun ƏL İLƏ dəyişməsi | 1 sessiya (dəyişməz) | 1 sessiya (dəyişməz) |

### 7 — `face_enrollment` (4.4 s, CƏMİ 1 sessiya — DB SƏBƏB DEYİLDİ)

`controllers/face_control.py::FaceEnrollmentController._camera_row()`
`camera.is_available()` — HƏQİQİ KAMERA APARAT PROBU — AÇIQ DB sessiyasının
(`refresh()`-in `with self._context.session(...)` bloku) İÇİNDƏ, GUI sapında
sinxron çağırılırdı. İKİ ayrı zərəri var idi: (a) GUI donurdu, (b)
`employees` sətrini oxuyan tranzaksiya probun BÜTÜN müddəti boyu AÇIQ
qalırdı — CLAUDE.md §6-nın «kontroller uzun-ömürlü tranzaksiya saxlamır»
qaydasının pozulması (HOG üz-aşkarlaması BUNUN SƏBƏBİ DEYİL — o, ayrıca
ölçülüb, 102 ms, problemsizdir).

**Həll:** `refresh()` indi YALNIZ siyahı + kadr sayını sessiya İÇİNDƏ oxuyur
və sessiyanı BAĞLAYIR; kamera probu `_refresh_camera_state()` ilə, sessiyadan
KƏNARDA, `run_job` ilə FON SAPINDA aparılır (`_camera_task`, `_task`-dan AYRI
sahə — qeydiyyat yazısı ilə paralel qaça bilər). Prob bitənə qədər ekran
`"available": "0"`, `"Kamera yoxlanılır…"` göstərir — bu, TƏHLÜKƏSİZ
defoltdur, çünki `[Çək]` düyməsi YALNIZ `available=1`-də aktivləşir.

| Ölçü | Əvvəl | Sonra (gözlənilən) |
|---|---|---|
| DB sessiya sayı | 1 | 1 (dəyişməz) |
| GUI sapının kamera probu boyu bloklanması | ~4.4 s-ə qədər (sürücüdən asılı) | **0 ms** (fon sapında) |
| Açıq tranzaksiyanın kamera probu boyu davam etməsi | BƏLİ (qayda pozğunluğu) | **XEYR** |

**Test təsiri (`tests/`-ə TOXUNMADIM, sizə bildirirəm):** iki test kamera
probunun İNDİ ASİNXRON olduğunu nəzərə almır —
`test_face_control_screen.py::test_an_unavailable_camera_is_explained_not_
hidden` (çağırışa `executor=InlineExecutor()` çatışmır — sibling testlərdəki
İLƏ EYNİ bir sətir) və `test_face_enrollment_screen_e2e.py::test_a_second_
click_while_the_first_capture_is_still_running_is_rejected`
(`_DeferredExecutor` ilə: `[Çək]` düyməsi kamera probu HƏLƏ bitmədiyi üçün
BAŞLANĞICDA deaktivdir — testin klikləri `executor.flush()`-dan ƏVVƏL, düymə
deaktivkən gedir; test kamera-probu jobunu ƏVVƏLCƏ `flush()` etməli, sonra
klikləməlidir).

---

## UI-FINAL — kart kölgəsinin ÖLÇÜLMÜŞ xərci (`QGraphicsDropShadowEffect`)

Vizual redizayn kartlara kölgə əlavə etdi (7 → 45). Kölgə RASTER effektdir:
Qt widget-i offscreen pixmap-a çəkir, bulanıqlaşdırır, sonra kompozisiya edir.
Xərc `show()`-da YOX, HƏR REPAINT-də ödənilir — ona görə adi «testlər keçir»
yoxlaması onu GÖRMÜR.

### Üç ölçü, üç fərqli nəticə — və yalnız sonuncusu doğru sual idi

| Ölçü üsulu | Nəticə | Niyə yanıldıcı idi |
|---|---|---|
| e2e dəsti, yaddaş, qurulma vaxtı | «reqressiya yoxdur» | offscreen fake-populate ekranı FAKTİKİ ÇƏKMİR — yəni kölgənin xərci olan yeri ölçmür |
| sahə (px²) siyahısı | proksi | doğru istiqamət, lakin kartın FAKTİKİ render eni ilə TƏBİİ `sizeHint()`-i fərqlidir |
| real `show()` + `repaint()` dövrəsi | HƏQİQİ | 60fps büdcəsi (16.67 ms/kadr) ilə birbaşa müqayisə olunur |

### Ölçülmüş qanun

* Xərc KART SAYINDAN yox, **KART SAHƏSİNDƏN** asılıdır (~7–9.5 ns/px², sabit).
* Kiçik tile (≤300K px²): ~0.2–0.4 ms — problemsiz.
* Orta kart (320×220): +0.71 ms.
* Tam-enli panel (≥900K px²): **8–14 ms** — tək başına kadr büdcəsinin yarısı və ya çoxu.
* **İSTƏNİLƏN uşaq widget-in yenilənməsi** — hətta məzmun dəyişmədən boş
  `update()` belə — kartın TAM yenidən rasterizəsini tətikləyir. `paintEvent`
  sayğacı ilə təsdiqləndi. Yəni cədvəl sətri yenilənən kölgəli panelin xərci
  BİR DƏFƏ yox, HƏR YENİLƏMƏDƏ ödənilir.

### Blur radiusunu azaltmaq KÖMƏK ETMİR

İki müstəqil kartda ölçüldü (`OpenShiftMarketCard` 1.88M px²,
`RecoveryConsoleScreen` 916K px²): `--shadow-blur` 24 → 8 (radiusun 3× azalması)
cəmi **2–5%** qazandırır, kölgəni SÖNDÜRMƏK isə **6–21×**. Səbəb: xərcin böyük
hissəsi MƏNBƏ widget-in pixmap-a çəkilməsindən gəlir, konvolyusiya radiusundan
yox. **Yəni «kölgəni incəldib saxlayaq» aralıq həlli YOXDUR — qərar ikilikdir.**

### Meyar (kartda `shadow=True` nə vaxt olur)

BEŞ şərtin HAMISI ödənməlidir:

1. dövrədə qurulmayıb (dinamik, naməlum sayda kart);
2. `surface="panel"` deyil;
3. başqa kartın içinə `.add()` ilə qoyulmayıb;
4. `sizeHint().width()` ≤ 1400px;
5. faktiki render eni konteyneri DOLDURMUR.

4 və 5 AYRI şərtdir və biri digərini əvəz etmir. `sync_conflicts.py:319`
naxışı: kartın öz `sizeHint()`-i cəmi 570px, LAKİN qonşusu konteyneri 1844px-ə
məcbur etdiyi üçün faktiki render eni 1844px-dir — xərc TƏBİİ tələbdən yox,
FAKTİKİ endən gəlir. Əks naxış da var: `field_reports.py:271` 1400px-lik
konteynerdə 640px görünürdü, təbii tələbi isə **2897px**-dir — layout onu
sıxışdırmışdı və kart «kiçik» sanılırdı.

**Gözlə qiymətləndirmə İŞLƏMİR.** «640px görünür, deməli kiçikdir» mühakiməsi
bu auditdə DÖRD dəfə yanlış çıxdı. Şübhəli hər kart ölçülməlidir.

Qapı: `tests/unit/test_shadow_card_width_gate.py` (sürətli, AST) və
`tests/e2e/test_shadow_card_width_budget.py` (yavaş, hər iki şərti REAL ölçür).

### Ölçülərin şərti

Bütün rəqəmlər `QT_QPA_PLATFORM=offscreen` altındadır — raster backend, yəni
real Windows-un GPU kompozisiyası ƏKS OLUNMUR. `QGraphicsDropShadowEffect`
onsuz da `QWidget` üzərində Qt-nin CPU bulanıqlaşdırması ilə işlədiyi üçün
ölçü etibarlıdır, lakin MÜTLƏQ millisaniyə real maşında fərqlənə bilər.
Ölçülər 1400px VƏ 1920px pəncərədə aparılıb: 1400→1920 keçidində tam-enli
kartların xərci **~30% artır** — yəni yalnız 1400px-də ölçmək ən yaxşı halı
ölçmək deməkdir.

---

## Hələ ölçülməmiş / gələcək addımlar

| Mövzu | Ölçülmüş dəyər | Qeyd |
|---|---|---|
| `Database()` hovuz açılışı | ~1450 ms | Açılışda bir dəfə, splash ekranı arxasında. |
| `_build_session()` (use case qrafı) | ~45 ms | Hər sessiyada. Şəbəkə yanında kiçikdir, lakin sıfır deyil. |
| Ekranların canlı məlumatı | ölçülüb | 41 ekran, 0.7–5.9 s, hamısı ~%100 baza gözləməsi (yuxarıdakı cədvəl). |
| `dashboard` ekranının sorğu sayı | ~28 sorğu / 1 sessiya | Tək sessiyada çox sorğu — birləşdirmək (JOIN / tək sorğu) növbəti addımdır. |
| Sorğuların fon sapına köçürülməsi | edilib | `_authenticate()` (PERF-6 #2), `_after_splash()` (PERF-6 #1) VƏ `show_admin()` (PERF-6 #3) — ÜÇÜ DƏ köçürülüb. Bu sətir bir müddət «`show_admin()` HƏLƏ QALIR» yazırdı, halbuki yuxarıdakı §3 bölməsi artıq «EDİLDİ» deyirdi: xülasə cədvəli bölmə ilə birlikdə yenilənməmişdi. Sənədin İKİ yerində eyni fakt varsa, ikisi də dəyişməlidir (CLAUDE.md §7-nin «qayda İKİ yerdə» prinsipi sənədə də aiddir). |
