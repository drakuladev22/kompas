# ÜÇÜNCÜ TƏRƏF ŞRİFT LİSENZİYALARI

**Son yenilənmə:** 2026-08-24

---

## Bu sənəd NİYƏ VAR

`assets/fonts/`-dakı `.ttf` faylları `KompasOS.spec` vasitəsilə birbaşa
`.exe`-yə paketlənir (bax `src/KompasOS.spec`, "İNTER ŞRİFTİ" və "İKON
ŞRİFTLƏRİNİN LİSENZİYA MƏTNLƏRİ" bölmələri). Onların HEÇ BİRİ Windows-da
qurulu deyil və heç biri bizim yazdığımız kod deyil — hərəsinin öz
lisenziyası var, ikisi isə (**SIL OFL** və **CC BY**) BAĞLAYICI öhdəlik
qoyur:

* **SIL Open Font License (OFL) 1.1** — lisenziya mətninin nüsxəsi şriftlə
  BİRLİKDƏ paylanmasını TƏLƏB edir. Mətn olmadan paylanma lisenziyanı
  pozur.
* **Creative Commons Attribution 4.0 (CC BY 4.0)** — mətnin özü şərt
  qoymur, lakin ATRİBUTSİYA (mənbə göstərilməsi) tələb edir; lisenziya
  mətninin bundle edilməsi bu tələbi ən aydın şəkildə yerinə yetirir.
* **Apache License 2.0** — lisenziya nüsxəsinin paylanan işlə birlikdə
  verilməsini tələb edir (§4.a).
* **MIT** — lisenziya bildirişinin qalması kifayətdir; nüsxə bura da
  daxildir, çünki qalan fontlarla EYNİ mexanizmdən keçir.

Tam lisenziya mətnləri BURADA TƏKRARLANMIR — hər biri `assets/fonts/`
altında ayrıca fayldadır. Səbəb: iki nüsxə bir gün ayrılar və hansının
DOĞRU olduğu bilinməz (eyni prinsip `docs/security_decisions.md`-in
"hər qayda İKİ yerdə" xəbərdarlığı ilə eynidir — burada isə TƏK yerdə
saxlamaqla önlənir).

---

## Cədvəl

| `.ttf` faylı | Ailə | Lisenziya | Lisenziya faylı | Mənbə versiyası |
|---|---|---|---|---|
| `Inter-Regular.ttf`, `Inter-Medium.ttf`, `Inter-SemiBold.ttf`, `Inter-Bold.ttf` | Inter | SIL OFL 1.1 | `assets/fonts/LICENSE-Inter.txt` | rsms/inter, Copyright (c) 2016 The Inter Project Authors |
| `fontawesome5-{solid,regular,brands}-webfont-5.15.4.ttf` | Font Awesome (v5) | SIL OFL 1.1 (ŞRİFT) | `assets/fonts/LICENSE-FontAwesome.txt` | FortAwesome/Font-Awesome, tag `5.15.4` |
| `fontawesome6-{solid,regular,brands}-webfont-6.7.2.ttf` | Font Awesome (v6) | SIL OFL 1.1 (ŞRİFT) | `assets/fonts/LICENSE-FontAwesome.txt` | FortAwesome/Font-Awesome, tag `6.7.2` |
| `elusiveicons-webfont-2.0.ttf` | Elusive Icons | SIL OFL 1.1 | `assets/fonts/LICENSE-ElusiveIcons.txt` | reduxframework/Elusive-Icons, versiya `2.0.0` |
| `materialdesignicons5-webfont-5.9.55.ttf` | Material Design Icons (v5) | Apache License 2.0 (ŞRİFT) | `assets/fonts/LICENSE-MaterialDesignIcons.txt` | Templarian/MaterialDesign-Webfont, tag `v5.9.55` |
| `materialdesignicons6-webfont-6.9.96.ttf` | Material Design Icons (v6) | Apache License 2.0 (ŞRİFT) | `assets/fonts/LICENSE-MaterialDesignIcons.txt` | Templarian/MaterialDesign-Webfont, tag `v6.9.96` |
| `remixicon-2.5.0.ttf` | Remix Icon | Apache License 2.0 | `assets/fonts/LICENSE-RemixIcon.txt` | Remix-Design/RemixIcon, **tag `v2.5.0`** (bax aşağıdakı xəbərdarlıq) |
| `phosphor-1.3.0.ttf` | Phosphor Icons | MIT | `assets/fonts/LICENSE-Phosphor.txt` | phosphor-icons/web, Copyright (c) 2020 Phosphor Icons |
| `codicon-0.0.36.ttf` | Codicon | CC BY 4.0 | `assets/fonts/LICENSE-Codicon.txt` | microsoft/vscode-codicons, tag `0.0.36` |

Son 8 sətir `qtawesome` paketinin (1.4.2) daşıdığı ikon şriftləridir —
`.spec`-dəki `_ICON_FONT_DATAS`/`_ICON_LICENSE_DATAS` bölmələrinə bax.

---

## Font Awesome — İKİ AYRI LİSENZİYA, QARIŞDIRMA

Font Awesome-un SVG/JS ikon faylları **CC BY 4.0**, ŞRİFT faylları isə
**SIL OFL 1.1** altındadır. Biz `qtawesome` vasitəsilə YALNIZ şrift
faylını daşıyırıq (SVG/JS heç vaxt paketə düşmür), ona görə cədvəldə
YALNIZ OFL yazılıb. Bu, ilk baxışda "Font Awesome = CC BY 4.0" deyə
səhv ümumiləşdirilə bilər — səhv olardı, çünki OFL-in tələbi (mətnin
BİRLİKDƏ paylanması) CC BY-dən fərqlidir və daşınmayan fayl növünə aid
lisenziyanı yazmaq öhdəliyi SƏHV qiymətləndirər.

## Remix Icon — VERSİYA-XƏBƏRDARLIĞI (ən vacib sətir)

Remix-Design/RemixIcon repozitoriyasının HEAD-i **bundle olunan
`remixicon-2.5.0.ttf`-dan SONRA** öz lisenziyasını dəyişib — indi
"Remix Icon License v1.0" adlı fərqli, xüsusi mətn işlədir (npm
registry-də isə köhnə paketlərdə hələ `Apache-2.0` görünür, uyğunsuzluq
elə buradan gəlir). `LICENSE-RemixIcon.txt`-dəki mətn HEAD-dən YOX, məhz
**`v2.5.0` git etiketindən** çəkilib — bizim daşıdığımız versiyaya aid
olan DOĞRU mətn budur.

**`qtawesome` versiyası YENİLƏNƏNDƏ və bundle olunan `remixicon-*.ttf`
versiyası dəyişəndə bu lisenziya YENİDƏN yoxlanmalıdır** — yeni versiya
yeni lisenziya altında ola bilər, köhnə mətni saxlamaq səhv atributsiya
deməkdir. Eyni ehtiyat qalan yeddi fayl üçün də keçərlidir (versiya
dəyişəndə lisenziya növü DƏYİŞMƏYƏ bilər deyə fərz edilməməlidir), lakin
Remix Icon-un tarixçəsi bunun nəzəri deyil, REAL risk olduğunu göstərir.

---

## Yeni şrift/ikon ailəsi əlavə edərkən

1. Bundle olunan DƏQİQ versiyanı tap (`.ttf` fayl adındakı versiya
   nömrəsi, `KompasOS.spec`-dəki `collect_data_files(...)` çıxışı).
2. Rəsmi mənbədən (upstream repo) HƏMİN versiyaya uyğun git etiketindən
   lisenziya mətnini çıxar — HEAD-dən YOX (Remix Icon dərsi).
3. `assets/fonts/LICENSE-<Ailə>.txt` yarat, başında hansı `.ttf`
   fayl(lar)ına aid olduğunu və mənbə URL-ini yaz.
4. `KompasOS.spec`-in müvafiq `_..._DATAS` siyahısına əlavə et (boş/
   yox fayl aşkarlansa `SystemExit` atan qoruyucu naxışı təkrarla).
5. Bu cədvələ sətir əlavə et.
