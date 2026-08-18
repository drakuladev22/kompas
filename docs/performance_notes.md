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

## Hələ ölçülməmiş / gələcək addımlar

| Mövzu | Ölçülmüş dəyər | Qeyd |
|---|---|---|
| `Database()` hovuz açılışı | ~1450 ms | Açılışda bir dəfə, splash ekranı arxasında. |
| `_build_session()` (use case qrafı) | ~45 ms | Hər sessiyada. Şəbəkə yanında kiçikdir, lakin sıfır deyil. |
| Ekranların canlı məlumatı | ölçülməyib | `screen_data.py` bir ekran üçün neçə sessiya açır — növbəti araşdırma mövzusu. |
| Sorğuların fon sapına köçürülməsi | — | Doğru ümumi həll budur; `BackgroundTask` infrastrukturu artıq mövcuddur. |
