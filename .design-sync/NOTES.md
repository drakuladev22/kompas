# design-sync qeydləri — KompasOS

## Bu repo standart konverterdən KƏNARDA sinxronlaşır

`design-sync` skilli JS/TS dizayn sistemləri üçündür: `dist/`-i esbuild ilə
bir `_ds_bundle.js`-ə yığır və Claude Design brauzerdə həmin React
komponentlərini render edir.

KompasOS isə **Python/PySide6 masaüstü tətbiqidir** — dizayn sistemi Qt
Style Sheet-dir (`src/presentation/theme/`), komponentlər isə Qt widget-ləri
(`src/presentation/widgets/`). Onları React paketinə çevirmək mümkün deyil və
skillin öz prinsipini pozardı ("ship what the customer already built — never a
reimplementation").

Ona görə **əhatə qəsdən məhdudlaşdırılıb**:

| Yüklənir | Yüklənmir |
|---|---|
| `tokens/` — rəng, tipoqrafiya, ölçü | `_ds_bundle.js` (komponent yoxdur) |
| `guidelines/` — ikonlar, brend qaydaları | `components/` (render oluna bilməz) |
| `styles.css`, `README.md` | `_vendor/`, `fonts/` (sistem şrifti) |

**Nəticə:** Claude Design öz ümumi komponentləri ilə qurmağa davam edir, lakin
KompasOS palitrası, tipoqrafiyası və ikonları ilə. Yeni maketlər (Qrup H, I…)
brendə uyğun çıxır və PySide6-da tətbiqi birbaşa olur.

**Faza 4-dən sonra əlavə olunan ekranlar** maket sənədində YOXDUR — onlar
mövcud token və widget-lərdən qurulub, ona görə bundle dəyişmir:

| Ekran | Modul | Qeyd |
|---|---|---|
| ROOT Control Center | `screens/group_d.py` | 3 bölmə: limitlər, modul açarları, icazə registri |
| Drive Bağlantısı | `screens/group_d.py` | OAuth razılığı; `image` ikonu |
| Qrup H / I ekranları | `screens/group_h.py`, `group_i.py` | Kataloqlar, hesabat, plugin, dashboard qurucusu |

Yeni ikon lazım olsa `widgets/icons.py`-a əlavə edin və bundle-ı yenidən
qurun — `guidelines/icons.md` avtomatik yenilənir.

## Bundle necə qurulur

```
python scripts/build_design_bundle.py
```

`tokens.py`, `metrics.py` və `icons.py`-ı oxuyub `ds-bundle/` qovluğunu
yaradır. Skript **YEGANƏ mənbədir** — `ds-bundle/` əl ilə redaktə edilmir və
git-ə salınmır (bax `.gitignore`).

## Vacib detallar

- **`_ds_sync.json` YOXDUR.** Skillin sidecar resepti JS paket formasını
  gözləyir (`bundleSha12`, `renderHashes` və s.) — burada onların qarşılığı
  yoxdur. Skill bu halı açıq şəkildə icazəli sayır: anchor olmadan növbəti
  sinxron hər şeyi yenidən yükləyir, bu isə düzgün davranışdır.
- **İkonlar `guidelines/`-dədir, `components/`-də deyil.** Onlar React
  komponenti deyil; `components/` qovluğuna qoysaydıq, dizayn agenti
  `window.<globalName>.*`-dan render etməyə çalışıb boş nəticə alardı.
  `guidelines/icons.md` içindəki SVG-lər birbaşa kopyalana bilir.
- **İki tema bir faylda deyil.** `tokens/colors-light.css` `:root`-a,
  `tokens/colors-dark.css` isə `[data-theme="dark"]`-a yazır — hər ikisi
  `styles.css`-dən `@import` olunur (skillin invariantı: dizaynlara YALNIZ
  `styles.css`-in tranzitiv `@import` bağlaması çatır).
- **Rənglər WCAG AA qapısından keçib** — `scripts/check_contrast.py` 50 cütü
  yoxlayır. Tokenləri dəyişdirən hər kəs həmin skripti işlətməlidir.
  DİQQƏT: 50 rəqəmi `--include-high-contrast` İLƏ alınır; bayraqsız 48 çıxır.

## Növbəti sinxron üçün risklər

- **`conventions.md` avtomatik yenilənMİR.** `icons.py`-a yeni ikon əlavə
  edildikdə oradakı SAY (`NN xətt-ikon`) və `Dəst:` siyahısı köhnəlir, lakin
  nə qurma, nə də test bunu tutur — dizayn agenti isə həmin siyahını
  həqiqət kimi oxuyur. Sinxrondan əvvəl HƏMİŞƏ yoxlayın:
  `guidelines/icons.md`-dəki `### \`ad\`` başlıqlarını `conventions.md`-in
  `Dəst:` bloku ilə tutuşdurun. 2026-08-09 sinxronunda məhz bu fərq tapıldı
  (41 sənədləşmiş / 44 qurulmuş — `arrow_up`, `arrow_down`, `help`).
- **Yüklənəcək fayl dəsti sabitdir** (7 fayl + `_ds_needs_recompile`).
  Uzaqdakı siyahı bununla üst-üstə düşürsə silinəcək fayl yoxdur —
  `finalize_plan`-da `deletes: []` düzgündür.
