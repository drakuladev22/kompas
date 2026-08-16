# assets/

Bu qovluqda hazırda **TƏK BİR fayl** var: `kompasos.ico`. Aşağıdakı cədvəl nəyin
mövcud, nəyin isə YOX olduğunu açıq göstərir — çünki bu faylın əvvəlki
variantı mövcud olmayan bir aktivə (`kompasos-splash.png`) sanki mövcuddur kimi
istinad edirdi.

| Fayl | Vəziyyət | Kim istifadə edir |
|---|---|---|
| `kompasos.ico` | ✅ MÖVCUD (placeholder) | `src/KompasOS.spec` — `.exe` ikonu + `datas`; runtime-da `presentation/app.py::_apply_window_icon` |
| `kompasos-splash.png` | ❌ YOXDUR və **hazırda LAZIM DEYİL** | Heç kim — splash ekranı vektor `CompassLogo` widget-i ilə çəkilir (`presentation/widgets/logo.py`) |
| `kompasos-light.ico` / `kompasos-dark.ico` | ❌ YOXDUR | Heç kim — yalnız real loqo gətiriləndə və tema-kontrastı itirilsə lazım olacaq |

---

## `kompasos.ico` — HƏLƏ DƏ PLACEHOLDER

Bu fayl **avtomatik yaradılmış placeholder-dır** (Deep Navy fon + Amber "K",
bax dizayn sistemi, bölmə 9). Format düzgündür və build-i qırmır:

| Xüsusiyyət | Dəyər |
|---|---|
| Format | ICO, PNG-sıxılmış |
| Ölçülər | 16×16, 32×32, 48×48, 256×256 |
| Rənglər | `#0B1D3A` (Deep Navy) / `#F5A623` (Amber) |

**NƏ VAXT ƏVƏZ EDİLMƏLİDİR (DÜZƏLİŞ):** əvvəllər burada «**Faza 4-dən əvvəl**
müştərinin real loqosu ilə əvəz edilməlidir» yazılırdı. Faza 4 çoxdan bağlanıb,
placeholder isə hələ də yerindədir — yəni bu tarix keçmiş və yanıldıcı bir
vədə çevrilmişdi. Faktiki asılılıq fazaya deyil, **müştəriyə** bağlıdır:
placeholder heç bir texniki qapını bloklamır (build keçir, ikon görünür), lakin
**ilk müştəri təhvilindən (imzalanmış `production` buraxılışından) əvvəl** real
loqo ilə əvəzlənməlidir — əks halda müştəri öz brendi əvəzinə bizim müvəqqəti
"K" işarəmizi görəcək.

Spesifikasiya bölmə 9 real loqodan bunları tələb edir:

- eyni loqo splash screen-də, pəncərə başlığında, Taskbar/Alt-Tab-da və `.exe`
  faylının özündə istifadə olunur;
- dörd ölçü (16/32/48/256) bulanıqlaşma olmadan hazırlanır;
- dark/light temada kontrast itməməsi üçün lazım gələrsə **iki variant**
  (`kompasos-light.ico`, `kompasos-dark.ico`) hazırlanır.

### Əvəzləmə

Yeni `.ico` faylını eyni adla bu qovluğa qoyun — `src/KompasOS.spec` (və onu
çağıran `ci.yml` addımı) həm `.exe` ikonu, həm də paket daxilindəki nüsxə üçün
avtomatik onu götürür. Kodda dəyişiklik lazım deyil.

### Splash şəkli haqqında (DÜZƏLİŞ)

Əvvəlki mətn «Splash screen üçün əlavə olaraq yüksək keyfiyyətli PNG (minimum
512×512, şəffaf fon) da lazımdır: `assets/kompasos-splash.png`» deyirdi və bu,
mövcud olmayan bir faylı sanki tələb kimi göstərirdi. Faktiki vəziyyət: splash
ekranı **rastr şəkil YÜKLƏMİR** — `CompassLogo` widget-i loqonu `QPainter` ilə
vektor kimi çəkir (`src/presentation/widgets/logo.py`), ona görə istənilən
DPI-da bulanıqlaşmır və heç bir PNG-yə ehtiyac duymur. Belə bir PNG YALNIZ
o zaman lazım olacaq ki, müştərinin real loqosu vektor kimi yenidən çəkilə
bilməsin; həmin halda fayl bura əlavə edilir və `logo.py` şəkil-yükləyən
variantla əvəzlənir.

### Yenidən yaratmaq (placeholder)

`scripts/generate_placeholder_icon.ps1` faylına baxın.
