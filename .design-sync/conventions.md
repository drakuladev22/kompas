# KompasOS — dizayn qaydaları

**Bu, komponent kitabxanası DEYİL, token kitabxanasıdır.** KompasOS native
Windows masaüstü tətbiqidir (Python/PySide6); render oluna bilən React
komponenti yoxdur. Öz komponentlərinizlə qurun, lakin **hər rəngi, ölçünü və
şrifti aşağıdakı tokenlərdən götürün** — hardcode edilmiş hex dəyəri brend
uyğunluğunu pozur və WCAG qapısından keçməmiş rəng gətirir.

## Platforma konteksti (maketin görünüşünü müəyyən edir)

Bu, brauzer və ya mobil tətbiq deyil. Ekranlar **1280×800 minimum**, sabit sol
naviqasiya (hamburger menyu YOX), yuxarıda kompakt header, geniş kontent
sahəsi. Mobil breakpoint yoxdur. **Bütün mətn Azərbaycan dilində** — İngiliscə
placeholder qalmamalıdır.

## Quraşdırma

Kök elementə `data-theme` verin, `styles.css`-i idxal edin:

```html
<link rel="stylesheet" href="./styles.css">
<body data-theme="light">   <!-- və ya "dark" -->
```

`data-theme` verilməsə sistem seçimi (`prefers-color-scheme`) tətbiq olunur.
`styles.css` bütün token fayllarını `@import` edir — ayrıca fayl bağlamayın.

## İdiom: `var(--token)`, utility class YOX

Bu sistemdə Tailwind-tipli sinif adları yoxdur. Stil birbaşa CSS custom
property ilə verilir:

```css
.card {
  background: var(--color-card-bg);
  border: var(--border-width) solid var(--color-card-border);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  color: var(--color-text-primary);
}
```

## Rəng ailələri

| Ailə | Tokenlər | İstifadə |
|---|---|---|
| Səth | `--color-content-bg`, `--color-card-bg`, `--color-card-border`, `--color-divider` | Səhifə fonu, kart, ayırıcı |
| Örtük | `--color-titlebar-bg/-text/-control`, `--color-header-bg/-border`, `--color-sidebar-bg/-border` | Pəncərə başlığı, header, sol panel |
| Naviqasiya | `--color-nav-item-text`, `--color-nav-item-icon`, `--color-nav-active-bg`, `--color-nav-active-text` | Menyu sətri və aktiv vəziyyət |
| Mətn | `--color-text-primary`, `--color-text-secondary`, `--color-text-muted`, `--color-text-disabled` | Başlıq → gövdə → köməkçi |
| Hərəkət | `--color-action-bg`, `--color-action-text`, `--color-action-hover`, `--color-action-pressed` | Əsas düymə |
| Vurğu | `--color-accent`, `--color-accent-hover`, `--color-accent-pressed`, `--color-accent-subtle`, `--color-focus-ring` | Fokus halqası, seçim |
| Brend | `--color-brand-navy`, `--color-brand-amber` | Loqo, dekorativ |
| Semantik | `--color-success`, `--color-warning`, `--color-danger`, `--color-info` | Status mətni/ikonu |
| Nişan fonu | `--color-success-bg`, `--color-warning-bg`, `--color-danger-bg`, `--color-info-bg`, `--color-neutral-bg` | Status həbi (chip) |
| Qrafik | `--color-chart-bar` | Sütun qrafiki (vurğulanan sütun `--color-brand-amber`) |

**İKİ QAYDA:**

1. **`--color-action-bg` ≠ `--color-brand-amber`.** Əsas düymə işıqlı rejimdə
   NAVY, tünddə AMBER-dir — token bunu özü həll edir. Düyməyə birbaşa amber
   verməyin: işıqlı fonda amber 2.03:1 verir və düymənin harası bitdiyi
   görünmür.
2. **Status nişanı = yumşaq fon + semantik mətn.** `--color-success-bg` fonuna
   `--color-success` mətni. Rəngləri qarışdırmayın — cütlər WCAG AA üçün
   kalibrlənib.

## Şkala

`--font-family`, `--font-size-xs|sm|md|lg|xl` (11/13/15/19/26px),
`--font-weight-normal|medium|bold`, `--space-xs|sm|md|lg|xl` (4/8/16/24/32px),
`--radius-sm|md|lg` (4/8/12px), `--border-width`, `--focus-ring-width`,
`--touch-target-min` (44px).

## Örtük ölçüləri

Maketdəki konkret ölçülər `--layout-*` kimi verilib:
`--layout-titlebar-height` (38px), `--layout-sidebar-width` (226px),
`--layout-header-height` (62px), `--layout-nav-item-height` (40px),
`--layout-content-padding-h/-v` (26/22px), `--layout-card-spacing` (18px).
Örtük qurarkən bunları işlədin — maketlə birebir uyğun gəlir.

## İkonlar

44 xətt-ikon `guidelines/icons.md`-dədir — SVG mənbəyi kopyalana bilir.
Hamısı `viewBox="0 0 16 16"`, `fill="none"`, `stroke="currentColor"`, yəni
rəngi valideynin `color`-undan alır:

```html
<span style="color: var(--color-nav-item-icon)">
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"
       stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M2 2.5h5v5H2zM9 2.5h5v3H9zM9 7.5h5v6H9zM2 9.5h5v4H2z"/>
  </svg>
</span>
```

Dəst: `dashboard` `queue` `roster` `fine` `users` `user` `settings` `calendar`
`shield` `star` `tag` `chat` `server` `server_off` `database` `activity`
`wifi_off` `power` `plus` `check` `check_circle` `close` `refresh` `search`
`arrow_up` `arrow_down` `edit` `download` `send` `login` `logout` `slash`
`clock` `bell` `help` `lock` `file` `folder` `image` `moon` `sun` `grid`
`list` `checklist`.

`arrow_up`/`arrow_down` sıralama düymələri üçündür: interfeys şrifti `↑`/`↓`
Unicode işarələrini daşımır, ona görə mətn yox, İKON işlədin.

## Nümunə

```html
<article style="
  background: var(--color-card-bg);
  border: var(--border-width) solid var(--color-card-border);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  display: flex; align-items: center; gap: var(--space-md);">

  <div>
    <div style="color: var(--color-text-muted); font-size: var(--font-size-sm)">
      Təsdiq gözləyir
    </div>
    <div style="color: var(--color-text-primary); font-size: var(--font-size-xl);
                font-weight: var(--font-weight-medium)">6</div>
  </div>

  <span style="margin-left:auto; background: var(--color-warning-bg);
               color: var(--color-warning); border-radius: var(--radius-md);
               padding: var(--space-xs) var(--space-sm);
               font-size: var(--font-size-sm)">ən uzunu 4 dəq</span>
</article>
```

## Həqiqətin mənbəyi

Ad uydurmayın — stil verməzdən əvvəl `styles.css` və onun idxal etdiyi
`tokens/colors-light.css`, `tokens/colors-dark.css`, `tokens/scale.css`,
`tokens/layout.css` fayllarını oxuyun. Orada olmayan token yoxdur.
