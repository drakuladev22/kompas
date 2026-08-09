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
