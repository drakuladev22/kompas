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

## Hələ ölçülməmiş / gələcək addımlar

| Mövzu | Ölçülmüş dəyər | Qeyd |
|---|---|---|
| `Database()` hovuz açılışı | ~1450 ms | Açılışda bir dəfə, splash ekranı arxasında. |
| `_build_session()` (use case qrafı) | ~45 ms | Hər sessiyada. Şəbəkə yanında kiçikdir, lakin sıfır deyil. |
| Ekranların canlı məlumatı | ölçülüb | 41 ekran, 0.7–5.9 s, hamısı ~%100 baza gözləməsi (yuxarıdakı cədvəl). |
| `dashboard` ekranının sorğu sayı | ~28 sorğu / 1 sessiya | Tək sessiyada çox sorğu — birləşdirmək (JOIN / tək sorğu) növbəti addımdır. |
| Sorğuların fon sapına köçürülməsi | — | Doğru ümumi həll budur; `BackgroundTask` infrastrukturu artıq mövcuddur. |
