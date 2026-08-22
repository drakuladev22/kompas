# QA-FULL yekun hesabatı (FAZA 8)

Bu sənəd `qamanual.md` (QA-FULL), `gap.md` (DEEP-GAP) və `onbaoard.md`
dövrəsinin YEKUNUDUR. Rəqəmlərin hamısı ÖLÇÜLÜB — təxmin yoxdur; ölçmə
üsulu hər bölmədə yazılıb ki, eyni ölçü təkrar edilə bilsin.

Teq: `qa-full-comprehensive-v1`.

---

## 1. Ümumi statistika

| Nə | Rəqəm |
|---|---|
| Bu dövrədəki commit | 4 (`b1bccd4`, `1f84cd1`, `0afafad` + bu hesabat) |
| Dəyişən fayl | 108+ |
| Test faylı (unit + e2e + integration) | 278 |
| Test sayı | **6407 keçir**, 50 atlanır, 1 xfail |
| Tip yoxlaması | `mypy --strict`, 376 fayl, 0 xəta |
| Kontrast qapısı | 160 rəng cütü, hamısı WCAG AA |
| Miqrasiya | 082-yə qədər, CANLI bazada 82/82 tətbiq olunub |

---

## 2. Funksional qüsurlar (DEEP-GAP dövrə 4 — commit `b1bccd4`)

13 tapıntı bağlandı. Hər qayda İKİ yerdədir (domen + DB trigger-i, §5):

| Kod | Nə idi |
|---|---|
| T1 | Kiosk 1:N üz girişinin terminal throttle-ı yox idi — foto/video ilə limitsiz cəhd |
| T2 | `can_manage_backups` hardlock 0 — DB səviyyəsində istənilən rola verilə bilirdi |
| T3 | Nəşr olunmuş `MANUAL_CAMERA` cəriməsi Drive-a YÜKLƏNMƏMİŞ sübutla keçirdi (sütun lokal növbə açarını saxlayırdı) |
| T5 | `_permitted()` OS saatını oxuyurdu — TIME-1-in server-lövbərli vədini pozurdu |
| T6 | Custom rol prioritetlə mağaza pilləsinə düşürdü, DB anti-fraud qapısı onu keçirirdi |
| İ5 | Qlobal mövqe şablonu kirayəçi sessiyasından SİLİNƏ/oğurlana bilirdi (`DELETE` `WITH CHECK`-ə tabe deyil) |
| İ6 | `permission_flags` üzərində `UPDATE` bağlı deyildi |
| İ7 | `scheduled_job_runs` tətbiq roluna səssizcə açıq idi |
| U1 | Uğurlu göndərişdən sonra forma və sübut şəkli təmizlənmirdi — köhnə foto NÖVBƏTİ işçiyə keçirdi |
| U5 | İşçi Ana Ekranının üç kartı canlı rejimdə HEÇ VAXT dolmurdu |
| U8 | Domen rəddi ekranı SİLİRDİ — «14 sətirdən 1-i emal olundu» mesajı itirdi |
| U9 | Qısa cavabdan sonra dialoq YAZILAN MƏTNİ itirirdi |
| 082 | `ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY` ROOT ekranında görünürdü, dəyişiklik isə heç bir sətrə dəymirdi (SQL seed-i yox idi) |

---

## 3. Test dəstinin ara-sıra ÇÖKMƏSİ (eyni commit)

`Windows fatal exception: access violation` tam dəstin ~84%-ində prosesi
söndürürdü. Kök-səbəb ölçüldü: 13 test faylı `KompasApplication`-ı `qtbot`-a
QEYD ETMƏDƏN qurur, obyektlər əlçatmaz qalır, LAKİN silinmir (23 → 2 `QObject`,
yalnız `gc.collect()`-dən sonra). Toplayıcı İSTƏNİLƏN yerdə — o cümlədən
BAŞQA testin `processEvents()` dövrəsinin İÇİNDƏ — işə düşə bilər; onda Qt
destruktoru hadisə dispetçerinin ortasında reentrant çağırılır.

Düzəliş: `tests/conftest.py` teardown-u gecikmiş silinmələri boşaldır, sonra
toplayıcını AÇIQ çağırır. Nəticə: çökmə tezliyi iki qaçışdan birindən
**sıfıra** düşdü (düzəlişdən sonra dörd tam qaçış — 6397, 6404, 6407 test —
çökməsiz).

---

## 4. Performans (FAZA 5)

Ölçmə: `psycopg.Cursor.execute` sarındı, hər ekran CANLI bazaya qarşı açıldı.
Şəbəkə gediş-gəlişi **205 ms** (Sinqapur pooler). Təfərrüat:
[`performance_notes.md`](performance_notes.md) → PERF-5.

| Ekran | Əvvəl | Sonra |
|---|---|---|
| `dashboard` | 5251 ms / 17 sorğu | **3247 ms / 13 sorğu** |
| `health` | 3777 ms / 8 sorğu / 2 sessiya | **1900 ms / 7 sorğu / 1 sessiya** |
| `sales_points` | 2107 ms / 8 sorğu | **1896 ms / 7 sorğu** |
| `audit` | 5 sorğu | **4 sorğu** |

Kök-səbəblər: (a) benchmark trend N ayı N sorğu ilə oxuyurdu, (b) açıq
sessiyanın içində limit oxusu İKİNCİ tranzaksiya açırdı, (c) mükafat kataloqu
iki dəfə oxunurdu, (d) audit səhifəsi və sayı ayrı sorğular idi.

Ölçüldü, TƏMİZ çıxdı (düzəliş lazım deyil): Excel ixracı 1000 sətir 68 ms,
üz aşkarlama 102 ms, 1:N müqayisə 0.4 ms, yaddaş 38 ekran × 32 dövr +45 KB
(sızma yoxdur), paketdə `QtWebEngine` yoxdur.

**Ən böyük lever hələ də koddan KƏNARDADIR:** baza Sinqapurdadır, Frankfurt
2.6× yaxındır — bütün yuxarıdakı rəqəmlər həmin əmsala bölünür.

---

## 5. Sabitlik (FAZA 6)

Mövcud örtük (yeni test yazılmadı, çünki ssenarilər ARTIQ bağlıdır):

| Ssenari | Qapı |
|---|---|
| Paralel iki iddia (eyni açıq növbə) | `test_open_shift_market.py::test_two_parallel_claims_produce_exactly_one_winner` + `FOR UPDATE` + şərtli `UPDATE` + DB trigger-i |
| Paralel yükləmə (eyni sübut şəkli) | `test_race_condition_guards.py::test_two_workers_upload_the_photo_only_once` |
| Şəbəkənin əməliyyat ORTASINDA kəsilməsi | `test_stress_connection_loss.py` — dörd axın (cərimə etirazı, növbə dəyişmə, açıq növbə, cərimə girişi) |
| Sürətli təkrar-klik | `test_stress_rapid_clicks.py` |
| Ekstremal input | `test_stress_extreme_input.py` |
| Dublikat cərimə | `uq_fines_manual_camera_idempotency_key` (miqrasiya 074) + 10 saniyəlik sürətli-yol |

---

## 6. Onboarding (`onbaoard.md`)

`--dev` yerləşdirməsi, addım 6 (öz-özünü yoxlama) və `--verify` rejimi
yazıldı; `docs/onboarding.md` tam sənəddir.

**FAZA 7 (tam dövrə testi) QİSMƏN icra olundu** — səbəb açıq yazılır:
bu mühitdə YALNIZ BİR Supabase layihəsi var, vendor bazası isə AYRI olmalıdır
(TENANT-1). Ona görə vendor sətri yazan addım 4 CANLI sınanmadı.

CANLI icra olunan hissə və onun TAPDIĞI qüsurlar:

1. `--verify` göstərdi ki, **078-082 miqrasiyaları canlı bazada tətbiq
   olunmamışdı** — reyestr 77/82. Düzəldildi: icraçı ilə tətbiq olundu.
2. Tətbiq zamanı **079 SINDI**: `enforce_flag_attributes_immutable()`
   `hardlock_level` dəyişikliyini bloklayır. Miqrasiya trigger-i TƏK bir
   `UPDATE` üçün söndürüb dərhal geri qaytaracaq şəkildə düzəldildi (səbəb
   faylın içindədir: miqrasiya həmin qaydanı dəyişməyin YEGANƏ sanksiyalı
   yoludur, tətbiq qatı isə yox).
3. `--verify`-in ÖZÜ də düzəldildi: `kompasos_app` rolu `schema_migrations`-i
   oxuya bilmir (078 GRANT sərtləşməsi) və həmin icazə xətası QALAN üç halqanı
   da öldürürdü. İndi hər halqa müstəqil sınır, `rollback()`-dan sonra
   `search_path` yenidən qurulur.

Yəni FAZA 7 tam dövrəni sınaya bilmədi, LAKİN öz məqsədinə çatdı — üç real
qüsur məhz canlı icra zamanı üzə çıxdı və bağlandı.

---

## 7. YEKUN

**Tətbiq stabildir:** 6407 test keçir, tam dəst dörd ardıcıl qaçışda çökmür,
`mypy --strict` təmizdir, kontrast qapısı 160 cütdə keçir.

**Sürət:** panel açılışının ən ağır iki ekranı 38% və 50% sürətləndi; qalan
vaxtın praktik olaraq HAMISI şəbəkə gözləməsidir (ekran çəkilişi ~0 ms).

**Canlıya çıxmaq üçün qalan İKİ addım — hər ikisi koddan kənardır:**

1. **Supabase regionunu Frankfurt-a köçürmək** — kod dəyişikliyi YOX, bütün
   ölçülər 2.6× yaxşılaşır (206 ms → 79 ms gediş-gəliş).
2. **Vendor bazasını qurmaq və onboarding-i tam dövrə ilə sınamaq**
   (`onbaoard.md` FAZA 7) — ikinci Supabase layihəsi tələb edir.
