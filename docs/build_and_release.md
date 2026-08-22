# Qurma və buraxılış — addım-addım (SETUP-1 Faza 5)

Bu sənəd `Setup.exe` hazırlamağın TAM ardıcıllığıdır. Hər əmr kopyala-yapışdır
üçündür; qovluq həmişə **repozitoriya kökü**dür.

---

## 0. Versiyanı yenilə (buraxılışdan ƏVVƏL)

Versiya **iki** yerdədir və uyğunsuzluq «Proqramlar» siyahısında bir, proqramın
öz haqqında ekranında başqa nömrə göstərər:

| Fayl | Sətir |
|---|---|
| `src/__init__.py` | `__version__ = "0.1.0"` |
| `installer/KompasOS.iss` | `#define MyAppVersion "0.1.0"` |

---

## 1. Qapılar (buraxılış qurmağa BAŞLAMAZDAN əvvəl)

Sınıq kodu paketləmək onu tapmağı ən bahalı ana — müştəri maşınına —
təxirə salır:

```bash
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/
.venv/Scripts/python.exe -m ruff format src/ tests/ scripts/
.venv/Scripts/python.exe -m mypy src
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe scripts/check_contrast.py --include-high-contrast
```

`QT_QPA_PLATFORM=offscreen` opsional deyil — səbəb `CLAUDE.md` §2-dədir.

---

## 2. PyInstaller — `.exe`

```bash
.venv/Scripts/python.exe -m PyInstaller --noconfirm --clean src/KompasOS.spec
```

* Qurma təsviri TƏK yerdədir: `src/KompasOS.spec`. Bayraqları əmr sətrinə
  yazmayın — CI eyni spec-i işlədir və iki mənbə səssizcə ayrılar.
* Nəticə: **`dist\KompasOS\`** qovluğu (`--onedir`) — içində `KompasOS.exe`
  və `_internal\` (Qt, şriftlər, ikon, üz modelləri). Ölçüldü (0.1.0):
  **1044 fayl, 433 MB**, `KompasOS.exe` 15.5 MB.
* `--onedir` QƏSDƏNDİR: `--onefile` hər açılışda arxivi `%TEMP%`-ə açırdı və
  müştəri maşınında 5-15 saniyə çəkirdi. Ölçülmüş isti açılış: **0.7 s**
  (ilk açılış ~5 s — Defender 960 yeni faylı bir dəfəlik yoxlayır).
* **`database/` PAKETƏ DÜŞÜR, `.env` DÜŞMÜR.** Bu sətir əvvəl «`database/`
  qəsdən paketə düşmür» deyirdi — YANLIŞ idi və təhlükəli yanlış idi:
  `provisioning.py` «Bazanı Avtomatik Qur» axınında sxemi və miqrasiyaları
  məhz PAKETİN İÇİNDƏN oxuyur (`_sql_root()` əvvəlcə `bundle_root()`-a baxır),
  yəni onlar olmasaydı təmiz müştəri quraşdırması bazanı QURA BİLMƏZDİ.
  Spec onları `_DATABASE_DATAS` ilə daxil edir (`schema.sql` + kök səviyyəli
  `NNN_*.sql`; `migrations/vendor/` DÜŞMÜR). Ölçülüb: paketdə **83 SQL faylı**
  (`schema.sql` + 82 miqrasiya) — rəqəm miqrasiya əlavə olunduqca ARTIR, ona
  görə burada TARİX ilə saxlanılır: 2026-08-23.
  `.env` isə HƏQİQƏTƏN düşmür — sirr saxlayır.

Yoxlama:

```bash
ls dist/KompasOS/KompasOS.exe
```

---

## 3. Inno Setup — `Setup.exe`

```bash
"$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" installer/KompasOS.iss
```

Sistem üzrə quraşdırılıbsa yol fərqlidir:

```bash
"/c/Program Files (x86)/Inno Setup 6/ISCC.exe" installer/KompasOS.iss
```

Inno Setup yoxdursa:

```bash
winget install --id JRSoftware.InnoSetup --silent \
  --accept-package-agreements --accept-source-agreements
```

* Nəticə: **`dist\KompasOS-Setup-<versiya>.exe`**
* Setup **UNİVERSALDIR** — config faylı ona DAXİL EDİLMİR (Variant B). Hər
  müştəri eyni faylı işlədir, bağlantı ilk açılışda ekrandan daxil edilir.

---

## 4. Kod imzalama (sertifikat hazır olduqda)

**SERTİFİKAT QƏSDƏN ALINMIR — QƏBUL EDİLMİŞ RİSK (SEC-034).** Buraxılış
imzasız paylanır; səbəb və nəticələr `docs/security_decisions.md` SEC-034-dədir.
Aşağıdakı addımlar sertifikat alınan gün üçün SAXLANILIR, hazırda İCRA
EDİLMİR.

**Quraşdırmadan ƏVVƏL hər hədəf maşında bunu işlədin** — imzasız buraxılışın
yeganə praktiki qorunması budur:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_target_machine.ps1
```

Skript Windows versiyasını, arxitekturanı, **Smart App Control vəziyyətini**,
`%PROGRAMDATA%` yazıla bilməsini, disk sahəsini və administrator hüququnu
yoxlayır. `NƏTİCƏ: bu maşında quraşdırmayın` çıxarsa quraşdırmağa BAŞLAMAYIN —
`Setup.exe` özü də imzasız `.exe`-dir və SAC məcburi rejimdə onu da açmır,
yəni səhv yalnız mağazada, müştərinin yanında üzə çıxardı.

Sertifikat mövzusunun texniki hissəsi (nə vaxt alınsa) — SEC-027.
İmzasız `.exe` Windows 11-in Smart App Control-u tərəfindən BLOKLANIR, yəni
bu addım buraxılış üçün opsional deyil.

İmzalanmalı **iki** fayl var — əvvəlcə proqram, SONRA Setup (Setup proqramı
öz içinə alır, ona görə sıra pozulmamalıdır):

```powershell
$signtool = "C:\Program Files (x86)\Windows Kits\10\bin\<versiya>\x64\signtool.exe"

& $signtool sign /f cert.pfx /p <parol> /fd SHA256 `
    /tr http://timestamp.digicert.com /td SHA256 /d "KompasOS" `
    dist\KompasOS\KompasOS.exe

# `.exe` imzalandıqdan SONRA Setup yenidən qurulur:
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\KompasOS.iss

& $signtool sign /f cert.pfx /p <parol> /fd SHA256 `
    /tr http://timestamp.digicert.com /td SHA256 /d "KompasOS Setup" `
    dist\KompasOS-Setup-<versiya>.exe
```

Yoxlama (`Valid` olmalıdır):

```powershell
Get-AuthenticodeSignature dist\KompasOS-Setup-<versiya>.exe | Select-Object Status
```

**Vaxt möhürü (`/tr`) məcburidir**: onsuz sertifikatın müddəti bitəndə ARTIQ
PAYLANMIŞ fayllar da etibarsız sayılır.

CI-dakı `production-release` job-u eyni ardıcıllığı avtomatik icra edir
(`.github/workflows/ci.yml`) və sertifikat yoxdursa QƏSDƏN dayanır (SEC-012).

---

## 5. Yekun fayl haradadır

| Fayl | Yer | Kimə verilir |
|---|---|---|
| `KompasOS-Setup-<versiya>.exe` | `dist\` | **Müştəriyə** |
| `KompasOS\` qovluğu | `dist\` | Yalnız daxili sınaq — müştəriyə TƏK BAŞINA verilmir |

---

## 5b. Developer maşınında ÖLÇÜLƏN dövrə (2026-08-23, versiya 0.1.0)

Aşağıdakılar bu maşında FAKTİKİ icra olunub — «təmiz maşın» siyahısını (§6)
ƏVƏZ ETMİR, lakin paketin özünün sağlam olduğunu buraxılışdan ƏVVƏL təsdiqləyir:

| Addım | Nəticə |
|---|---|
| Silent quraşdırma (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=… /LOG=…`) | kod 0, **19 san**, 1046 fayl / 438 MB |
| Reyestr (`HKLM\…\Uninstall\{AppId}_is1`) | `KompasOS`, `0.1.0`, uninstall sətri düzgün |
| Qısayollar | Start menyu + ictimai masaüstü — hər ikisi yaranır |
| Quraşdırma jurnalı (`/LOG`) | 5397 sətir, «Installation process succeeded», xəta YOX |
| `KompasOS.exe --check` | işləyir; YALNIZ `encryption`/`hash_pepper` uğursuzdur — **gözlənilən**: açar paketə düşmür, maşın açarı İLK YAZIDA yaranır (SETUP-2) |
| `KompasOS.exe --gui --preview` (offscreen, 45 san) | 0 traceback, 0 «Logging error», stderr BOŞ |
| Silent uninstall (`unins000.exe /VERYSILENT`) | kod 0, **1 san**; qovluq, reyestr qeydi və qısayollar SİLİNİR |
| Müştəri məlumatı (`%PROGRAMDATA%\KompasOS`) | `data\` və `logs\` **QALIR** — silinmə onları aparmır |

Bu dövrədə TAPILAN qüsur (düzəldildi): paketlənmiş `.exe`-nin konsol log
kanalı `cp1252` axına yazırdı və HƏR sətir `UnicodeEncodeError` verirdi
(`src/shared/logger.py::_console_stream`). Mənbədən işləyəndə görünmürdü —
orada konsol UTF-8-dir.

---

## 6. Təmiz maşında test siyahısı

Bunlar developer maşınında YOXLANA BİLMƏZ (orada proqram repozitoriya
qovluğundan işə düşür və hüquqlar fərqlidir):

- [ ] **Quraşdırma** — Setup açılır, `C:\Program Files\KompasOS\` yaranır,
      masaüstündə YALNIZ qısayol görünür (config/`.exe` gözə dəymir).
- [ ] **ProgramData** — `C:\ProgramData\KompasOS\` yaranıb; `logs\` və `data\`
      alt qovluqları var və **standart istifadəçi** ora yaza bilir.
- [ ] **Config-siz ilk açılış** — proqram ÇÖKMÜR, «KompasOS işə düşə bilmədi»
      ekranı açılır (mesaj + «Yenidən Cəhd Et» + dəstək ünvanı). Müştəri
      ekranı QƏSDƏN kasıbdır — RECOVERY-1 Faza 2. Konfiqurasiyanı texnik
      `Ctrl+Shift+K` → Bərpa Konsolu ilə yazır; diaqnostika yolları da
      oradadır.
- [ ] **Config yazılması** — ekrandan yadda saxlayın; fayl
      `C:\ProgramData\KompasOS\connection.json`-da yaranmalıdır (`.exe`-nin
      yanında YOX). Yanında `kompasos.key` də yaranır — şifrələmə açarı ilk
      yazıda avtomatik qurulur (SETUP-2, `docs/key_rotation.md`).
- [ ] **Əl ilə köçürmə (dəstək axını)** — hazır `connection.json`-u
      `C:\Program Files\KompasOS\` qovluğuna (`.exe`-nin yanına) qoyun;
      OXU sırasında o, BİRİNCİDİR və dərhal qüvvəyə minir. `ProgramData`
      nüsxəsi də oxunur, lakin `.exe` yanındakı onu üstələyir — hansının
      işlədiyi Bağlantı Ayarları ekranının diaqnostika sətrində yazılır.
- [ ] **Loglar** — `C:\ProgramData\KompasOS\logs\app.log` yazılır
      (`Program Files`-da log qovluğu YARANMAMALIDIR).
- [ ] **İkinci Windows hesabı** — başqa hesabla girin: proqram EYNİ
      konfiqurasiyanı görür və parol xətası vermir (DPAPI blobu maşın
      əhatəsindədir).
- [ ] **Uninstall** — «Proqramlar» siyahısında görünür; silinmə zamanı
      «Məlumatı da siləkmi?» sualı verilir. **Xeyr** deyildikdə
      `C:\ProgramData\KompasOS\` QALIR.
- [ ] **Smart App Control** — imzasız buraxılışda proqram ÜMUMİYYƏTLƏ
      açılmaya bilər (SEC-027). Bu, quraşdırma qüsuru DEYİL.
- [ ] **Sihirbaz BİR DƏFƏ çıxır** — quraşdırmanı tamamlayın, proqramı bağlayıb
      yenidən açın: bu dəfə GİRİŞ ekranı gəlməlidir. Sihirbaz təkrar çıxırsa,
      bu, SETUP-3 reqressiyasıdır (bax `docs/security_decisions.md`, SEC-024
      altındakı «SONRAKI DÜZƏLİŞ» bəndi).

---

## 6.1. Quraşdırmadan SONRA — təchizatçının `Root` hesabı

Setup `Root` hesabı YARATMIR və yaratmamalıdır (SEC-030). Sihirbaz müştərinin
`CEO` hesabını açır; təchizatçının öz hesabı AYRI addımdır və onsuz ROOT İdarə
Mərkəzi, «Texniki Dəstək» kanalı, Telegram ayarları və bərpa konsolu əlçatmaz
qalır.

Müştərinin sihirbazı tamamlandıqdan SONRA, repozitoriya olan maşında:

```bash
# Nə ediləcəyini göstərir, heç nə yazmır:
.venv/Scripts/python.exe scripts/create_root_account.py --dry-run

# Yaradır — şifrə GİZLİ soruşulur (əmr sətrində YAZILMIR):
.venv/Scripts/python.exe scripts/create_root_account.py     --username developer --first-name Texniki --last-name Dəstək
```

* Skript **birbaşa terminalda** işlədilməlidir (PowerShell / cmd) — boru və ya
  avtomatlaşdırılmış mühitdə şifrə soruşula bilmir və skript bunu AÇIQ deyir.
* Kirayəçi kimliyi tətbiqin öz mənbəyindən (`installation.json`) gəlir; bazada
  birdən çox kirayəçi varsa `--tenant-id` MƏCBURİ olur.
* Aktiv `Root` artıq varsa skript DAYANIR (`--force` ilə keçilə bilər).

---

## 6.2. ÇOX-MAĞAZALI MÜŞTƏRİ — HƏR KİOSK PC-Sİ ÜÇÜN `sysprep` MƏCBURİDİR

**Qısası:** eyni Windows imicini bir neçə mağaza PC-sinə klonlayırsınızsa,
HƏR birində quraşdırmadan ƏVVƏL `sysprep /generalize /oobe /shutdown`
işlədin. Bu, Windows-un ÖZ standart tövsiyəsidir, amma KompasOS-da
buraxılması SƏSSİZ bir təhlükəsizlik boşluğuna gətirir:

* Terminal PIN qorunması (SEC-01/SEC-05) hər kiosk PC-nin Windows quraşdırma
  identifikatorına (`MachineGuid`) bağlıdır — bu, mağaza kodundan (`.env`)
  FƏRQLİ olaraq admin hüququ olmadan dəyişdirilə bilmədiyi üçün seçilib.
* `sysprep` KEÇİLMƏDƏN klonlanmış diskdə HƏR maşın EYNİ `MachineGuid`-i
  daşıyır — Windows onu quraşdırma zamanı YENİDƏN yaratmır.
* Nəticə: bütün klon mağazalar EYNİ PIN qoruma sayğacını PAYLAŞIR. Bir
  mağazada baş verən uğursuz PIN cəhdləri BAŞQA mağazanın terminalını
  bloklaya bilər — sistemin ÖZÜ bunu aşkarlayıb qeyd edir (audit jurnalında
  «şübhəli klonlanmış maşın» siqnalı görünür), lakin qarşısını ALMIR.

`sysprep`-dən sonra HƏR PC öz unikal `MachineGuid`-ini alır və bu problem
kökündən aradan qalxır. Bircə PC-lik quraşdırmada (klon YOXDURSA) bu addıma
ehtiyac yoxdur.

---

## 7. Tez-tez qarşılaşılan səhvlər

| Əlamət | Səbəb |
|---|---|
| `.exe` işə düşmür, exit 126, heç bir pəncərə yoxdur | Smart App Control imzasız faylı bloklayır (SEC-027) |
| «Baza bağlantısı konfiqurasiya edilməyib» | `connection.json` yoxdur — normal ilk açılışdır, ekrandan daxil edin |
| Config yazılmır, «icazə lazımdır» | Fayl `Program Files`-a yazılmağa çalışılır — Setup ilə quraşdırmada bu baş verməməlidir; `KOMPASOS_CONNECTION_FILE` təyin edilibmi? |
| İkinci hesabda «parol açıla bilmədi» | DPAPI blobu köhnə quraşdırmadan `%LOCALAPPDATA%`-da qalıb; parolu bir dəfə yenidən daxil edin |
| Log qovluğu boşdur | `KOMPASOS_LOG_DIR` başqa yerə yönləndirilib |
