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
  və `_internal\` (Qt, şriftlər, ikon, üz modelləri; 960+ fayl, ~430 MB).
* `--onedir` QƏSDƏNDİR: `--onefile` hər açılışda arxivi `%TEMP%`-ə açırdı və
  müştəri maşınında 5-15 saniyə çəkirdi. Ölçülmüş isti açılış: **0.7 s**
  (ilk açılış ~5 s — Defender 960 yeni faylı bir dəfəlik yoxlayır).
* `database/` və `.env` QƏSDƏN paketə düşmür: birincisi yerləşdirmə
  artefaktıdır, ikincisi sirr saxlayır.

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

**Hazırda sertifikat YOXDUR** — bax `docs/security_decisions.md` SEC-027.
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

## 6. Təmiz maşında test siyahısı

Bunlar developer maşınında YOXLANA BİLMƏZ (orada proqram repozitoriya
qovluğundan işə düşür və hüquqlar fərqlidir):

- [ ] **Quraşdırma** — Setup açılır, `C:\Program Files\KompasOS\` yaranır,
      masaüstündə YALNIZ qısayol görünür (config/`.exe` gözə dəymir).
- [ ] **ProgramData** — `C:\ProgramData\KompasOS\` yaranıb; `logs\` və `data\`
      alt qovluqları var və **standart istifadəçi** ora yaza bilir.
- [ ] **Config-siz ilk açılış** — proqram ÇÖKMÜR, «Bağlantı Ayarları» ekranı
      açılır. Ekranın altındakı Diaqnostika sətrində üç yol görünür.
- [ ] **Config yazılması** — ekrandan yadda saxlayın; fayl
      `C:\ProgramData\KompasOS\connection.json`-da yaranmalıdır (`.exe`-nin
      yanında YOX).
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

---

## 7. Tez-tez qarşılaşılan səhvlər

| Əlamət | Səbəb |
|---|---|
| `.exe` işə düşmür, exit 126, heç bir pəncərə yoxdur | Smart App Control imzasız faylı bloklayır (SEC-027) |
| «Baza bağlantısı konfiqurasiya edilməyib» | `connection.json` yoxdur — normal ilk açılışdır, ekrandan daxil edin |
| Config yazılmır, «icazə lazımdır» | Fayl `Program Files`-a yazılmağa çalışılır — Setup ilə quraşdırmada bu baş verməməlidir; `KOMPASOS_CONNECTION_FILE` təyin edilibmi? |
| İkinci hesabda «parol açıla bilmədi» | DPAPI blobu köhnə quraşdırmadan `%LOCALAPPDATA%`-da qalıb; parolu bir dəfə yenidən daxil edin |
| Log qovluğu boşdur | `KOMPASOS_LOG_DIR` başqa yerə yönləndirilib |
