# Yeni müştəri quraşdırması (onboarding)

Bu sənəd `scripts/onboard_new_tenant.py` skriptinin NECƏ işlədildiyini yazır.
Skriptin NİYƏ belə qurulduğu — hansı qərarın hansı auditdən gəldiyi — faylın
öz başlığındadır və burada TƏKRARLANMIR: iki yerdə saxlanan izah bir gün
ayrılar və hansının doğru olduğu bilinməz.

**Skript `.exe`-yə paketlənmir.** `src/KompasOS.spec` yalnız `src/` altını
yığır; `scripts/` ora düşmür. Səbəb: skript VENDOR bazasına yazır (`tenants`
sətri) və müştəri maşınında belə bir imkan lisenziya qapısını mənasız edərdi.

---

## 1. Supabase-də yeni layihə

Hər müştəri AYRI Supabase layihəsidir (TENANT-1 qərarı) — ortaq baza YOXDUR.

1. Supabase konsolunda yeni layihə açın, region kimi müştəriyə ən yaxın
   AB regionunu seçin.
2. **Sihirbaz (defolt) üçün yalnız İKİ dəyər lazımdır:**
   * **Project Ref** — `Project Settings → General → Reference ID`
     (20 simvollu). Panelin ünvan sətrini olduğu kimi də yapışdıra
     bilərsiniz: `https://supabase.com/dashboard/project/<ref>` və
     `https://<ref>.supabase.co` formaları da tanınır.
   * **DB parolu** — `Project Settings → Database → Database password`.

   DSN-i skript ÖZÜ qurur. Regionu soruşmur, çünki BİRBAŞA formatı işlədir:
   `postgresql://postgres:<parol>@db.<ref>.supabase.co:5432/postgres`. Host
   tamamilə ref-dən alınır — bu, **əvvəl real qarşılaşılmış xətanın
   düzəlişidir**: pooler formatı (`aws-0-<REGION>.pooler.supabase.com`)
   REGİON tələb edir və region Project Ref-dən ÇIXARILA BİLMİR.
3. **Bayraqlı yol üçün** (aşağı, §2.1) `Project Settings → Database`
   bölməsindən **connection pooling** DSN-ini götürün
   (`aws-0-…pooler.supabase.com:5432`).
4. Tətbiq üçün ayrıca rol lazımdır: **`kompasos_app`**. `postgres`
   superuser-i konfiqurasiya faylına YAZILMIR — `connection.json` müştərinin
   maşınında qalır və oradan oxunan superuser bütün RLS qatını mənasız edərdi.
5. Miqrasiyaları tətbiq etmək üçün isə YÜKSƏK səlahiyyətli DSN lazımdır
   (`postgres` və ya migration rolu) — o, YALNIZ skriptin işlədiyi müddətdə,
   `--tenant-dsn` arqumentində yaşayır.

Vendor (mərkəzi lisenziya) bazası BİR DƏFƏ qurulur və bütün müştərilər üçün
eynidir — `--vendor-dsn` həmişə həmin bazanı göstərir.

---

## 2. Skript necə işlədilir

### 2.0 DEFOLT YOL — sual-cavablı sihirbaz (arqumentsiz)

```bash
.venv/Scripts/python.exe scripts/onboard_new_tenant.py
```

Başqa heç nə. Ekran:

```
KompasOS Tenant Qurulumu
─────────────────────────
  Şirkət/Test adı: Embawood
  Əlaqə e-poçtu: it@embawood.az

  [Vendor bağlantısı YALNIZ İLK DƏFƏ soruşulur — sonra yaddaşdan oxunur]
  Vendor (mərkəzi) Supabase Project Ref: ····
  Vendor DB Parolu:
  ⏳ Bağlantı test edilir … ✓
  ✓ Vendor bağlantısı yadda saxlanıldı (.onboard_config)

  Tenant Supabase Project Ref: ····
  Tenant DB Parolu:
  ⏳ Bağlantı test edilir … ✓
  Tenant Anon Açarı (istəyə bağlı, ENTER — keç):

[1/6] Tenant bazasına miqrasiyalar … OK
…
BİTDİ. Konfiqurasiya bu maşında hazırdır:
  1. `python -m src.main` — əlavə addım LAZIM DEYİL.
  2. Arxiv nüsxəsi «onboarding/embawood» qovluğundadır.
     Başqa kirayəçiyə keçmək: `python scripts/switch.py`
```

Bilməli olduğunuz dörd şey:

* **`--dev` avtomatik qalxır.** Sihirbaz «bitən kimi açılır» sözü verir, bu
  isə konfiqurasiyanın tətbiqin FAKTİKİ oxu yerlərinə yazılması deməkdir.
* **Vendor bağlantısı BİR DƏFƏ soruşulur.** Dəyər `.onboard_config`
  faylında ŞİFRƏLİ saxlanılır (`connection.json`-un işlətdiyi EYNİ açar
  zənciri). Fayl `.gitignore`-dadır: içindəki parol BÜTÜN müştərilərin
  abunə sətirlərinə yazma icazəsidir. Vendor parolu dəyişsə, sınaq uğursuz
  olur və sihirbaz onu YENİDƏN soruşub üzərinə yazır — faylı əl ilə silmək
  lazım deyil.
* **Bağlantı sualın YANINDA sınanır.** Səhv parol 1-ci addımda (miqrasiya
  alt prosesi) stack-trace kimi görünərdi; indi dərhal, insan-oxunaqlı
  mesajla tutulur və **yalnız səhv olan sual** təkrarlanır: parol
  səhvdirsə ref YENİDƏN SORUŞULMUR.
* **`anon` açarı istəyə bağlıdır.** O, `connection.json`-a yazılmır — tətbiq
  onu YALNIZ `KOMPASOS_SUPABASE_ANON_KEY` mühit dəyişənindən oxuyur və
  `.env` faylını qəsdən oxumur. Verilsə, `OXU-MƏNİ.txt`-ə və
  `configs/<slug>.config` arxivinə qeyd kimi düşür.

**Eyni şirkət təkrar daxil edilsə** skript vendor bazasında ad VƏ Supabase
ref üzrə axtarır, tapsa DAYANIR və soruşur:

```
  ⚠ Bu müştəri vendor bazasında ARTIQ mövcuddur:
      «Embawood» — 3f2b1c44-…, AKTIV, abcdefghijklmnopqrst

  Nə edilsin?
    1) Mövcud kirayəçini DAVAM etdir (heç nə silinmir, təkrar yazılmır)
    2) AYRICA yeni kirayəçi yarat (eyni adlı FƏRQLİ şirkət/filial)
    3) Dayan, heç nə etmə
```

«Davam» seçimi mövcud `tenant_id`/`license_key`-i bərpa edir — yəni
quraşdırma idempotent şəkildə tamamlanır. Terminal OLMAYAN mühitdə (CI,
boru) sual verilə bilmədiyi üçün skript **proses kodu 3** ilə dayanır:
sükutla YENİ kirayəçi yaratmaq YETİM sətir yaradardı və o, yalnız ödəniş
hesabatında üzə çıxardı. Həqiqətən ayrı kirayəçi lazımdırsa
`--allow-duplicate` verin.

### 2.1 Bayraqlı yol — `--dev` (geridə-uyumlu)

Sihirbaz bir halda İŞLƏMİR: `db.<ref>.supabase.co` bəzi yeni Supabase
layihələrində YALNIZ IPv6 ünvanı elan edir və IPv4-ə bağlı şəbəkədən ora
çatmaq mümkün olmur. Sihirbaz bunu tanıyır və məhz bu yola yönləndirir —
aşağıdakı forma həmin halın YEGANƏ çıxışıdır və ona görə SİLİNMƏYİB.

```bash
.venv/Scripts/python.exe scripts/onboard_new_tenant.py \
    --company "Embawood" \
    --tenant-dsn "postgresql://kompasos_app:PAROL@aws-0-eu.pooler.supabase.com:5432/postgres" \
    --vendor-dsn "postgresql://vendor:PAROL@aws-0-eu.pooler.supabase.com:5432/postgres" \
    --supabase-ref "abcdefghijklmnop" \
    --contact-email "it@embawood.az" \
    --out ./output/embawood \
    --dev
```

`--dev` konfiqurasiyanı arxivə YAZMAQLA YANAŞI bu maşının FAKTİKİ oxu
yerlərinə də yazır və parolu YERİNDƏ şifrələyir. Skript bitən kimi:

```bash
.venv/Scripts/python.exe -m src.main
```

**əlavə addım olmadan** açılır — heç bir fayl köçürmək lazım deyil.

> Giriş nöqtəsi `main.py` DEYİL: repozitoriya kökündə belə bir fayl yoxdur,
> tətbiq `src/main.py`-dır və PAKET kimi işə düşür (`python src/main.py`
> nisbi idxalları qırır).

### 2.2 Real müştəri üçün — `--dev` OLMADAN

Eyni bayraqlı əmr, `--dev` OLMADAN. Fayllar yalnız `--out` qovluğuna düşür; oradan
müştərinin maşınına ƏL İLƏ (AnyDesk) köçürülür. Bu, FƏRQLİ fiziki maşındır —
avtomatlaşdırıla bilməz və bu, qüsur deyil.

### 2.3 Əvvəlcədən görmək — `--dry-run`

Heç nə yazmadan addımların siyahısını (və `--dev` ilə birlikdə HANSI yollara
yazılacağını) çap edir.

### 2.4 Mövcud müştərini yoxlamaq — `--verify`

İki forma var. **Ada görə** (bu maşında quraşdırılmış kirayəçilər üçün):

```bash
.venv/Scripts/python.exe scripts/onboard_new_tenant.py --verify embawood
```

DSN soruşulmur, çünki onlar ONSUZ DA bu maşındadır: tenant bağlantısı
`configs/<slug>.config` arxivindən (parol yerində deşifrələnir, müvəqqəti
fayl YARANMIR), vendor bağlantısı isə `.onboard_config` yaddaşından gəlir.
Ad `switch.py`-dakı ilə EYNİ qayda ilə həll olunur; səhv yazılsa mövcud
adların siyahısı göstərilir. `--dev` halqası avtomatik təyin olunur: yalnız
yoxlanan kirayəçi HAZIRDA AKTİVdirsə yerli konfiqurasiya da yoxlanılır.

Bayraqsız («real müştəri») onboarding arxivə PAROL yazmır (səbəb §4-dədir) —
belə arxiv üçün ad forması işləmir və skript bunu açıq deyir.

**UUID-ə görə** (kirayəçi bu maşında quraşdırılmayıbsa — YEGANƏ işləyən yol):

```bash
.venv/Scripts/python.exe scripts/onboard_new_tenant.py \
    --tenant-dsn "postgresql://…" \
    --vendor-dsn "postgresql://…" \
    --verify "3f2b1c44-…"
```

**Heç nə yazmır** — yalnız oxuyur. Çıxış bir checklist-dir:

```
Kirayəçi yoxlaması: 3f2b1c44-…
  [OK    ] Miqrasiya reyestri: 82/82 tətbiq olunub
  [OK    ] Əsas cədvəllər: 8/8 mövcuddur
  [ÇATMIR] Seed məlumatı: system_limits=0, feature_toggles=0, positions=0 — BOŞ: …
  [OK    ] Kirayəçi sətri: «Embawood», status ODENIS_GOZLENILIR
  [OK    ] Vendor sətri: «Embawood», status ODENIS_GOZLENILIR
  [—     ] Yerli konfiqurasiya: aid deyil (`--dev` verilməyib)

NƏTİCƏ: 1 halqa ÇATMIR — Seed məlumatı
```

Bir halqanın sınması qalanlarını DAYANDIRMIR: dəstək zəngində lazım olan
«hansı biri sınıb» sualının cavabıdır, ona görə mənzərə TAM verilir. Proses
kodu: 0 (hamısı yerində) / 1 (ən azı biri çatmır) / 2 (arqument səhvi).

`--company` bu rejimdə LAZIM DEYİL. Yerli konfiqurasiya halqası isə YALNIZ
`--dev` ilə birlikdə yoxlanılır — əks halda təchizatçının öz maşınındakı
inkişaf faylı hər müştəri yoxlamasında yalançı-qırmızı verərdi.

**Bu, «bütün müştəriləri skan et» DEYİL və ola bilməz:** vendor bazası heç bir
tenant DSN-i saxlamır (DB-3 qərarı), yəni yoxlanacaq müştərinin DSN-i
operatorun əlindən gəlir.

---

## 3. Skript nə edir — altı addım

| # | Addım | Harada |
|---|---|---|
| 1 | Bütün miqrasiyalar | müştəri bazası |
| 2 | Vendor miqrasiyaları (`--vendor`) | vendor bazası |
| 3 | `license_tenants` sətri + `seed_tenant_defaults()` | müştəri bazası |
| 4 | `tenants` sətri (status `ODENIS_GOZLENILIR`) | vendor bazası |
| 5 | Konfiqurasiya faylları (+ `--dev` ilə işlək yerlərə) | disk |
| 6 | **Öz-özünü yoxlama** — konfiqurasiya geri oxunur, bazaya qoşulur | hər ikisi |

Addım 6 ayrıca dayanır, çünki «yazıldı» «işləyir» demək deyil: parol
şifrələnib, lakin açar bu maşında yoxdursa deşifrələmə qalxır, JSON yazılıb,
lakin başqa quraşdırmanın `tenant_id`-si qalıbsa proqram KÖHNƏ kirayəçi ilə
açılar. Addım 6 bunların hər ikisini skriptin ÖZ çıxışında tutur.

---

## 4. Konfiqurasiya haraya düşür

| Fayl | `--dev` ilə | Bayraqsız |
|---|---|---|
| `installation.json` | `%PROGRAMDATA%\KompasOS\` (`KOMPASOS_INSTALLATION_PATH` ilə əvəzlənir) | `--out` qovluğu |
| `connection.json` | `%PROGRAMDATA%\KompasOS\`, parol ŞİFRƏLİ | — |
| `connection.template.json` | `--out` (arxiv) | `--out`, parol BOŞ |
| `OXU-MƏNİ.txt` | `--out` (arxiv) | `--out` |

Bayraqsız rejimdə parol boş qalır, çünki şifrələmə MAŞINA bağlıdır (DPAPI,
maşın əhatəsi): bizim maşında şifrələnən dəyər müştərinin maşınında AÇILA
BİLMƏZ. Parol orada, «Bağlantı Ayarları» ekranında daxil edilir və elə orada
şifrələnir.

Tətbiq `connection.json`-u ÜÇ yerdə axtarır (`connection_file.py`):
`.exe`-nin yanı → `%PROGRAMDATA%\KompasOS\` → `%APPDATA%\KompasOS\`. İlk
tapılan qalib gəlir; FAKTİKİ işlədilən yol «Bağlantı Ayarları» ekranının
diaqnostika sətrində görünür.

---

## 5. Müştəriyə nə çatdırılır

`--out` qovluğundakı üç fayl:

1. `installation.json` → `%PROGRAMDATA%\KompasOS\`
2. `connection.template.json` → eyni qovluğa, **`connection.json` adı ilə**
3. `OXU-MƏNİ.txt` — müştəri üçün addım-addım təlimat (`tenant_id` və
   `license_key` daxil)

Sonra tətbiq açılır, «Bağlantı Ayarları» ekranı parolu soruşur, bağlantı
qurulan kimi İlk Quraşdırma Sihirbazı Root hesabını yaradır.

**Lisenziya statusu `ODENIS_GOZLENILIR`-dir.** Ödəniş alındıqdan sonra Vendor
Konsolundan `AKTIV` edilməlidir — skriptin özünə bu səlahiyyət qəsdən
verilmir (quraşdırma ilə ödəniş fərqli hadisələrdir).

---

## 5A. Kirayəçilər arasında keçid — `switch.py`

Təchizatçının maşınında eyni anda YALNIZ BİR kirayəçi aktiv ola bilər:
`installation.json` və `connection.json` sabit yerlərdədir. `switch.py` həmin
məhdudiyyəti idarə edir — hər kirayəçinin konfiqurasiyası `configs/` altında
arxivlənir və bir əmrlə yerinə qoyulur.

```bash
.venv/Scripts/python.exe scripts/switch.py            # siyahı + hazırkı vəziyyət
.venv/Scripts/python.exe scripts/switch.py vendor     # config-i götür (Vendor Konsolu üçün)
.venv/Scripts/python.exe scripts/switch.py embawood   # həmin kirayəçi kimi test
```

* Arxiv onboarding zamanı AVTOMATİK yaranır (`configs/<slug>.config`) — əlavə
  bir addım atmaq lazım deyil.
* Keçid HEÇ VAXT üstünə yazmır: aktiv konfiqurasiya əvvəlcə öz adı ilə geri
  arxivlənir, sonra yenisi qoyulur. Sıra qəsdən belədir — nüsxə yazılmamış
  silmə, prosesin ortada kəsilməsi halında konfiqurasiyanı tamamilə itirərdi
  (parol BU MAŞINA bağlı şifrələnib və başqa nüsxədən bərpa oluna bilmir).
* `configs/.aktiv` iz-faylı yalnız AKTİV kirayəçinin ADINI saxlayır. Adı
  aktiv fayllar daşımır (`installation.json`-da yalnız `tenant_id` var), ona
  görə iz olmasa hər keçid `namelum-<vaxt>` adlı arxiv yaradardı.
* `configs/` `.gitignore`-dadır: bundle-lar müştərinin host adını, istifadəçi
  adını və şifrələnmiş parolunu daşıyır.

---

## 6. Problem çıxarsa

### ❌ «Verilənlər bazasına qoşula bilmədim — parol səhv ola bilər»

Sihirbaz bunu sualın YANINDA deyir və **yalnız parolu** yenidən soruşur —
Project Ref-i təkrar yazmaq lazım deyil, çünki server məhz ona görə cavab
verdi (`28P01` yalnız ünvana ÇATMIŞ bağlantıda gəlir). Parolun yeri:
`Project Settings → Database → Database password`.

### ❌ «Bu ünvanda Supabase layihəsi tapılmadı»

Project Ref səhvdir. Panelin ünvan sətrini olduğu kimi yapışdıra bilərsiniz —
skript ref-i özü çıxarır. Yeri: `Project Settings → General → Reference ID`.

### ❌ «Ünvana çatmaq mümkün olmadı (şəbəkə əlçatmazdır)»

Ünvan DOĞRUDUR — bu şəbəkədən çatmır. Səbəb praktikada budur:
`db.<ref>.supabase.co` yalnız IPv6 elan edir, şəbəkəniz isə IPv4-dür.
Çıxış: Supabase panelindən **Connection pooling** DSN-ini kopyalayıb bayraqlı
yolu işlədin (§2.1) — sihirbaz bu mesajda həmin əmri özü çap edir.

### ❌ «Bağlantı 10 saniyədən çox çəkdi»

İnternet bağlantısı. Hədd sihirbazda qəsdən qısadır (quraşdırma addımlarında
30 saniyədir): burada ekran qarşısında GÖZLƏYƏN adam var.

### ⚠ «Bu müştəri vendor bazasında ARTIQ mövcuddur»

§2.0-dakı üç seçim. Qısası: eyni müştərinin təkrar quraşdırmasıdırsa
«Davam», eyni adlı FƏRQLİ şirkət/filialdırsa «Yeni».

### ❌ «AÇIQ PAROL AŞKARLANDI»

Addım 6 yazılan HƏR faylı geri oxuyur və içində baza parolunu axtarır. Bu
mesaj o deməkdir ki, şifrələmə işləməyib və parol açıq qalıb — quraşdırma
TAMAMLANMIŞ sayılmır. Fayl SİLİNMİR (səbəb sizə lazımdır); əvvəlcə
`KOMPASOS_FERNET_KEY`/DPAPI vəziyyətini yoxlayın.

### «DAYANDI» mesajı gəldi

Skript addımı yarımçıq QOYMUR: uğursuz addımdan sonrakılar İCRA OLUNMUR və
səbəb açıq yazılır. Mesajla birlikdə **vəziyyət cədvəli** çap olunur — hər
altı addım `OK` / `UĞURSUZ` / `EDİLMƏDİ` kimi göstərilir və edilməmiş
addımların yanında ƏL İLƏ yoxlama üsulu yazılır. Skript HEÇ NƏ GERİ
QAYTARMIR və bu, qəsdlidir: addımlar iki AYRI PostgreSQL serverinə və fayl
sisteminə toxunur, tətbiq olunmuş miqrasiyanı geri qaytarmaq isə işlək ola
biləcək bazanı boşaltmaq olardı. Addım 1-4 onsuz da idempotentdir.

DSN parolları çıxışda maskalanır (`postgres:***@`) — miqrasiya alt prosesinin
çıxışı da daxil olmaqla, çünki ekran dəstək üçün skrinşot edilə bilər. Addım 4-dən (vendor sətri COMMIT olunur) SONRA baş verən
hər dayanma bərpa göstərişi də çap edir:

```bash
... --tenant-id "<UUID>" --license-key "<TAM AÇAR>"
```

Bu iki bayraq YALNIZ BİRLİKDƏ verilir. Yalnız birini vermək DB-də saxlanan
açarla uyğunsuz, YENİ təsadüfi açar yaradar və müştəri konfiqurasiyası sınar
— skript bunu açıq xəta ilə rədd edir. Eyni kimliklə təkrar çağırış
idempotentdir: tamamlanmış addımlar sükutla keçilir, yarımçıq qalan yerindən
başlayır.

### `--dev`-dən sonra proqram yenə «işə düşə bilmədi» deyir

Addım 6 keçibsə konfiqurasiya OXUNUR və baza ƏLÇATANDIR — problem
konfiqurasiyada deyil. Əvvəlcə `%PROGRAMDATA%\KompasOS\` qovluğunda İKİNCİ
bir `connection.json` nüsxəsinin (məs. repozitoriya kökündə, `.exe` yanı
yolunda) olub-olmadığını yoxlayın: axtarış sırasında birinci tapılan qalib
gəlir və köhnə nüsxə yenisini kölgələyə bilər.

### `connection.json` yazıla bilmədi

`--dev` şifrələmə açarı tələb edir: bu maşında DPAPI, CI-da isə
`KOMPASOS_FERNET_KEY`. Heç biri yoxdursa addım 5 dayanır və
`installation.json` artıq yazılmış olur — açarı təyin edib skripti eyni
`--tenant-id`/`--license-key` ilə təkrar işə salın.

### Yanlış tenant ilə açılır

Addım 6 `installation.json`-dakı `tenant_id`-ni bu quraşdırmanınkı ilə
tutuşdurur və fərq varsa DAYANIR (fayl SİLİNMİR — səbəb operatora lazımdır).
Bu mesajı görsəniz, köhnə quraşdırmanın faylı yerində qalıb: onu silib
skripti təkrar işə salın.

---

## 7. Əlaqəli sənədlər

* `scripts/onboard_new_tenant.py` — qərarların izahı (fayl başlığı)
* `scripts/onboard_wizard.py` — sihirbazın qərarları: niyə BİRBAŞA DSN, niyə
  ayrı modul, `.onboard_config` şifrələməsi
* `scripts/switch.py` — niyə «config» İKİ fayldır, niyə «nüsxə + sil»
* `tests/unit/test_onboarding_wizard.py` — sihirbazın zəmanətlərini maşınla
  qoruyan testlər (DSN kodlaması, maskalama, dublikat qapısı, açıq sirr
  yoxlaması)
* `scripts/create_root_account.py` — təchizatçının `Root` hesabı (SEC-030)
* `docs/build_and_release.md` — `.exe` və Setup quraşdırıcısı (SETUP-1)
* `database/migrations/061` — miqrasiya reyestri (əl ilə SQL işlətmək qadağan)
