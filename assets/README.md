# assets/

Bu qovluqda `kompasos.ico` və `logo/` altqovluğundakı **doqquz PNG** var.
Cədvəl nəyin mövcud olduğunu VƏ hər faylı KİMİN oxuduğunu göstərir — çünki bu
faylın əvvəlki iki variantı da məhz burada yanılmışdı: birincisi mövcud
olmayan bir aktivə (`kompasos-splash.png`) sanki mövcuddur kimi istinad edirdi,
ikincisi isə (aşağıdakı düzəlişə bax) real loqo gətirildikdən sonra da onu
«placeholder» adlandırmağa davam edirdi.

| Fayl | Faktiki ölçü | Kim oxuyur |
|---|---|---|
| `kompasos.ico` | 16/24/32/48/64/**256** | `src/KompasOS.spec` — `.exe` ikonu + `datas`; runtime-da `presentation/app.py::_apply_window_icon` |
| `logo/16_withoutcontainer.png` | 32×32 | `widgets/brand_assets.TITLE_MARK` — başlıq zolağındakı işarə (BOYANIR, aşağıya bax) |
| `logo/256.png` | 256×256 | **`.ico`-nun TƏK MASTERİ** — bütün pillələr bundan kiçildilir |
| `logo/64.png` | 64×64 | `widgets/brand_assets.APP_MARK` — giriş/sihirbaz ekranlarındakı rozet |
| `logo/loading_screen_light.png` | 1066×388 | `brand_assets.splash_asset(dark=False)` — splash lockup |
| `logo/loading_screen_dark.png` | 1064×388 | `brand_assets.splash_asset(dark=True)` — splash lockup |
| `logo/16.png` | 32×32 | ❕ Runtime kodu OXUMUR — bax «Oxunmayan dörd fayl» |
| `logo/32.png` | 64×64 | ❕ Runtime kodu OXUMUR (`64.png` ilə PİKSEL-EYNİ) |
| `logo/light.png` | 1066×324 | ❕ Runtime kodu OXUMUR — rozetin AÇIQ fonda təqdimat kartı, mətnsiz |
| `logo/dark.png` | 1064×324 | ❕ Runtime kodu OXUMUR — eyni kart TÜND fonda |
| `windows_app.png` | — | ❌ Bu qovluqda OLMAMALIDIR — `design_reference/`-dəki maketdir |
| `256 negative.png` | 256×256 | ❌ Bu qovluqda OLMAMALIDIR — AYRI VARİANTdır (kvadrat konteyner, daha tünd fon), eyni işarənin böyük nüsxəsi DEYİL. `design_reference/`-də qalır |

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

Fayl **`scripts/build_icon.py` ilə qurulur** və mənbəyi `logo/256.png`-dir:

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
| Pillələr | 16, 24, 32, 48, 64, **256** |
| Mənbə | `logo/256.png` — TƏK master; bütün pillələr ondan KİÇİLDİLİR |

### 256×256 pilləsi ARTIQ VAR — «itmiş pillə» reqressiyası bağlandı

**(ÇATIŞMAZLIQ DÜZƏLİŞİ:** bu bölmə əvvəllər «256×256 pilləsi YOXDUR — bu,
qərardır» adlanırdı və pillənin olmamasını dizayn qərarı kimi izah edirdi.
İzah yarımçıq idi: məhdudiyyət qərar deyil, MƏNBƏ çatışmazlığı idi — əldəki ən
böyük rastr 64×64 olduğu üçün 256 yalnız böyütmə ilə alına bilərdi.
`assets/logo/256.png` gələndən sonra səbəb aradan qalxdı.**)**

Windows-un «Böyük ikonlar» görünüşü və Alt-Tab artıq 64-ü miqyaslamır — natiw
256 pilləsini oxuyur.

**BÜTÜN PİLLƏLƏR ARTIQ 256-DAN QURULUR.** «Hər pillə üçün ona ən yaxın mənbə»
qaydası rədd edildi, çünki `16.png`/`32.png` ayrıca hazırlanmış kiçik-ölçü
variantları DEYİL (`32.png` ilə `64.png` piksel-eynidir) — yəni onlardan qazanc
yox idi, qarışıq mənbə isə pillələri bir-birindən bir qədər fərqli edərdi.
Detallar: `scripts/build_icon.py` başlığı.

`64.png` silinmədi: o, `.ico`-nun mənbəyi olmasa da tətbiq daxilindəki rozetdir
(`brand_assets.APP_MARK`).

`test_the_large_tier_exists_and_is_not_upscaled` iki şeyi birlikdə saxlayır:
pillə var VƏ master həqiqətən 256×256-dır. İkincisi olmasa, dizayn faylı bir gün
kiçik ölçüdə ixrac edilsə `.ico` sükutla böyütmə ilə qurulardı.

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
ümumi həcm 100 KB-dan azdır).

**`256.png` bu siyahıda DEYİL** və bu, fərqi vurğulamaq üçün ayrıca yazılır: o,
runtime kodu tərəfindən oxunmasa da (`brand_assets`-də sabiti yoxdur) BİLAVASİTƏ
işlədilir — `.ico` ondan qurulur. Yəni onu silmək `build_icon.py`-ı dayandırardı,
qalan dördü isə heç nəyi pozmur.

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
