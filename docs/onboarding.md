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
2. `Project Settings → Database` bölməsindən **connection pooling** DSN-ini
   götürün (`aws-0-…pooler.supabase.com:5432`).
3. Tətbiq üçün ayrıca rol lazımdır: **`kompasos_app`**. `postgres`
   superuser-i konfiqurasiya faylına YAZILMIR — `connection.json` müştərinin
   maşınında qalır və oradan oxunan superuser bütün RLS qatını mənasız edərdi.
4. Miqrasiyaları tətbiq etmək üçün isə YÜKSƏK səlahiyyətli DSN lazımdır
   (`postgres` və ya migration rolu) — o, YALNIZ skriptin işlədiyi müddətdə,
   `--tenant-dsn` arqumentində yaşayır.

Vendor (mərkəzi lisenziya) bazası BİR DƏFƏ qurulur və bütün müştərilər üçün
eynidir — `--vendor-dsn` həmişə həmin bazanı göstərir.

---

## 2. Skript necə işlədilir

### 2.1 Öz maşınınızda sınamaq üçün — `--dev`

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
.venv/Scripts/python.exe main.py
```

**əlavə addım olmadan** açılır — heç bir fayl köçürmək lazım deyil.

### 2.2 Real müştəri üçün — bayraqsız (defolt)

Eyni əmr, `--dev` OLMADAN. Fayllar yalnız `--out` qovluğuna düşür; oradan
müştərinin maşınına ƏL İLƏ (AnyDesk) köçürülür. Bu, FƏRQLİ fiziki maşındır —
avtomatlaşdırıla bilməz və bu, qüsur deyil.

### 2.3 Əvvəlcədən görmək — `--dry-run`

Heç nə yazmadan addımların siyahısını (və `--dev` ilə birlikdə HANSI yollara
yazılacağını) çap edir.

### 2.4 Mövcud müştərini yoxlamaq — `--verify`

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

## 6. Problem çıxarsa

### «DAYANDI» mesajı gəldi

Skript addımı yarımçıq QOYMUR: uğursuz addımdan sonrakılar İCRA OLUNMUR və
səbəb açıq yazılır. Addım 4-dən (vendor sətri COMMIT olunur) SONRA baş verən
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
* `scripts/create_root_account.py` — təchizatçının `Root` hesabı (SEC-030)
* `docs/build_and_release.md` — `.exe` və Setup quraşdırıcısı (SETUP-1)
* `database/migrations/061` — miqrasiya reyestri (əl ilə SQL işlətmək qadağan)
