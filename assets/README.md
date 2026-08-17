# assets/

Bu qovluqda `kompasos.ico` və `logo/` altqovluğundakı **səkkiz PNG** var.
Cədvəl nəyin mövcud olduğunu VƏ hər faylı KİMİN oxuduğunu göstərir — çünki bu
faylın əvvəlki iki variantı da məhz burada yanılmışdı: birincisi mövcud
olmayan bir aktivə (`kompasos-splash.png`) sanki mövcuddur kimi istinad edirdi,
ikincisi isə (aşağıdakı düzəlişə bax) real loqo gətirildikdən sonra da onu
«placeholder» adlandırmağa davam edirdi.

| Fayl | Faktiki ölçü | Kim oxuyur |
|---|---|---|
| `kompasos.ico` | 16/24/32/48/64 | `src/KompasOS.spec` — `.exe` ikonu + `datas`; runtime-da `presentation/app.py::_apply_window_icon` |
| `logo/16_withoutcontainer.png` | 32×32 | `widgets/brand_assets.TITLE_MARK` — başlıq zolağındakı işarə (BOYANIR, aşağıya bax) |
| `logo/64.png` | 64×64 | `widgets/brand_assets.APP_MARK` — giriş/sihirbaz ekranlarındakı rozet; **həm də `.ico`-nun MƏNBƏYİ** |
| `logo/loading_screen_light.png` | 1066×388 | `brand_assets.splash_asset(dark=False)` — splash lockup |
| `logo/loading_screen_dark.png` | 1064×388 | `brand_assets.splash_asset(dark=True)` — splash lockup |
| `logo/16.png` | 32×32 | ❕ Runtime kodu OXUMUR — bax «Oxunmayan dörd fayl» |
| `logo/32.png` | 64×64 | ❕ Runtime kodu OXUMUR (`64.png` ilə PİKSEL-EYNİ) |
| `logo/light.png` | 1066×324 | ❕ Runtime kodu OXUMUR — rozetin AÇIQ fonda təqdimat kartı, mətnsiz |
| `logo/dark.png` | 1064×324 | ❕ Runtime kodu OXUMUR — eyni kart TÜND fonda |
| `windows_app.png` | — | ❌ Bu qovluqda OLMAMALIDIR — yalnız `design_reference/`-dəki maketdir; `test_the_reference_mockup_is_not_shipped` yoxluğunu qoruyur |

**Fayl adları piksel ölçüsü DEYİL.** Adlar nöqtə (pt) ölçüsünü, fayllar isə @2x
rasteri daşıyır: `16.png` → 32×32, `32.png` → 64×64. Bu, dizayndan gəldiyi
kimi saxlanılıb — adları «düzəltmək» dizayn ixracı ilə repozitoriya arasında
uyğunsuzluq yaradardı.

---

## `kompasos.ico` — TÖRƏMƏ FAYLDIR, ƏL İLƏ REDAKTƏ EDİLMİR

**(ÇATIŞMAZLIQ DÜZƏLİŞİ:** bu bölmə əvvəllər «`kompasos.ico` — HƏLƏ DƏ
PLACEHOLDER» adlanırdı və faylı avtomatik yaradılmış Deep Navy + Amber "K"
kimi təsvir edirdi. Həmin mətn `3ae2484` commit-indən sonra yanlışdır: real
pərgar loqosu gətirilib, `.ico` ondan qurulur. Sənəd isə commit-lə birlikdə
yenilənmədiyi üçün oxucuya hələ də görülməmiş bir iş vəd edirdi.**)**

Fayl **`scripts/build_icon.py` ilə qurulur** və mənbəyi `logo/64.png`-dir:

```bash
.venv/Scripts/python.exe scripts/build_icon.py
```

Əl ilə qurulub repozitoriyaya atılsaydı, PNG dəyişəndə `.ico` sükutla köhnələr
və fərq YALNIZ Taskbar-da — yəni ən gec fərq olunan yerdə — görünərdi. Qurma
qaydası (hansı pillə hansı mənbədən) buna görə koddadır, sənəddə deyil.
`test_the_icon_is_built_from_the_logo_sources` `.ico`-nu skriptin ölçü siyahısı
ilə tutuşdurur — faylın əl ilə dəyişdirilməsi də belə tutulur.

| Xüsusiyyət | Dəyər |
|---|---|
| Format | ICO, PNG-sıxılmış |
| Pillələr | 16, 24, 32, 48, 64 |
| Mənbə | `logo/64.png` (64×64); kiçik pillələr ondan KİÇİLDİLİR |

### 256×256 pilləsi YOXDUR — bu, qərardır

Köhnə placeholder `.ico`-da 256 vardı; yenisində yoxdur. Səbəb: əldəki ən böyük
rastr 64×64-dür və onu 256-ya BÖYÜTMƏK bulanıq nəticə verərdi. Nəticə: Windows-un
«Böyük ikonlar» görünüşü 64-ü özü miqyaslayır.

Tam keyfiyyət üçün **256×256 dizayndan AYRICA ixrac edilməlidir** — bu, kök
README-dəki «İlk müştəri təhvilindən əvvəl» siyahısının yeganə açıq maddəsidir.
`test_the_missing_large_tier_is_documented` pillənin yoxluğunun sənədləşdiyini
yoxlayır ki, növbəti adam bunu qüsur sanıb böyütmə əlavə etməsin.

**24 və 48 haqqında ayrıca qeyd:** 64-dən yalnız 32 (÷2) və 16 (÷4) TAM
nisbətlə alınır; 24 və 48 tam olmayan nisbətlərdir və bir qədər yumşalır
(LANCZOS bunu yaxşı idarə edir, amma sıfırlamır). 256 ilə birlikdə ixrac
edilsələr, onlardan da faydalanardıq. Bu, DAYANDIRICI deyil.

---

## Başlıq zolağındakı işarə BOYANIR

`16_withoutcontainer.png` TAM SABİT rəngdədir — bütün piksellər `#134E4A`
(tünd teal), yəni AÇIQ fon üçün. Başlıq zolağı isə hər iki temada TÜNDDÜR:
faylı olduğu kimi qoysaydıq, işarə praktiki olaraq görünməzdi.

Ona görə şəkil **alfa maskası** kimi işlədilir — forma fayldan, rəng temadan:
`--color-brand-mark` tokeni (dəyəri `BRAND_TEAL_LIGHT` = `#2DD4BF`, hər iki
palitrada EYNİ, çünki zolaq hər iki temada tünddür). Bu, layihənin mövcud
naxışıdır — pəncərə düymələrinin ikonları da məhz belə boyanır — və dizayndan
İKİNCİ fayl dəsti tələb etmir. Detallar:
`src/presentation/widgets/brand_assets.py` başlığı.

---

## Splash rastr şəkil YÜKLƏYİR (əvvəlki mətnin əksinə)

**(ÇATIŞMAZLIQ DÜZƏLİŞİ:** əvvəlki mətn «splash ekranı rastr şəkil YÜKLƏMİR —
`CompassLogo` widget-i loqonu `QPainter` ilə vektor kimi çəkir» deyirdi. Bu,
o vaxt doğru idi, indi deyil.**)**

Splash `loading_screen_light/dark.png` faylını yükləyir: PNG pərgarı və
"KompasOS" mətnini BİR kompozisiyada daşıyır, onu Qt-də iki elementlə yenidən
qurmaq dizaynın nisbətlərini TƏXMİN ETMƏK olardı. Fayl adı hardcode edilmir —
seçim `brand_assets.splash_asset(dark=...)`-dadır və `ThemeManager`-in HƏLL
OLUNMUŞ rejimindən gəlir.

`CompassLogo` (`src/presentation/widgets/logo.py`) silinməyib: şəkil tapılmasa
işə düşən **fallback**-dır. Paket qüsuru ekranı boş qoymamalıdır.

---

## Oxunmayan dörd fayl niyə saxlanılır

`16.png`, `32.png`, `light.png`, `dark.png` — heç bir runtime kod yolu onları
oxumur, lakin `logo.md` təhvil xəritəsinin bir hissəsidirlər və
`test_every_runtime_logo_file_is_present` mövcudluqlarını qoruyur. Silinsəydilər,
gələcəkdə lazım olduqda dizayndan yenidən istənilməli olardı; qovluqda qalmaları
isə heç nəyə başa gəlmir (`.spec` `logo/*.png` qlobu ilə hamısını paketə salır,
ümumi həcm 90 KB-dan azdır).

---

## ⚠️ `scripts/generate_placeholder_icon.ps1` KÖHNƏLİB

Bu skript hələ də repozitoriyadadır və işlədilsə **real loqonu placeholder "K"
ilə ƏVƏZ EDƏR**. İşlətməyin. Yanlışlıqla işlədilibsə bərpa bir əmrdir:

```bash
.venv/Scripts/python.exe scripts/build_icon.py
```

---

## Loqo dəyişəndə nə edilir

1. Yeni PNG-ləri `assets/logo/`-ya qoyun (adlar dəyişmirsə kodda düzəliş lazım
   deyil — fayl adları `brand_assets.py`-dakı sabitlərdədir).
2. `.venv/Scripts/python.exe scripts/build_icon.py` işlədin.
3. `tests/unit/test_brand_assets.py` işlədin — mövcudluq, `.ico` pillələri,
   boyamanın rəngi faktiki dəyişdiyi və tema keçidində splash faylının
   dəyişdiyi orada ölçülür.

`.spec` və `ci.yml` addımlarına toxunmaq lazım deyil: hər ikisi `kompasos.ico`
və `logo/*.png` qlobunu adla götürür.
