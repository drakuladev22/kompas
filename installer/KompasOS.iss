; ===========================================================================
; KompasOS — Inno Setup quraşdırıcısı (SETUP-1 Faza 3)
; ===========================================================================
; Qurma:  ISCC.exe installer\KompasOS.iss
; Nəticə: dist\KompasOS-Setup-<versiya>.exe
;
; ÖNCƏ `dist\KompasOS.exe` mövcud olmalıdır (PyInstaller) — bax
; `docs/build_and_release.md`.
;
; ---------------------------------------------------------------------------
; QOVLUQ BÖLGÜSÜ — BU FAYLIN ƏSAS QƏRARI
; ---------------------------------------------------------------------------
;   {autopf}\KompasOS\        proqram faylları   — YALNIZ OXU (Windows qaydası)
;   {commonappdata}\KompasOS\ konfiqurasiya/data — YAZILA BİLƏN, PAYLAŞILAN
;
; İkiyə bölmək məcburidir: standart istifadəçi `Program Files`-a yaza bilmir,
; yəni config, log və offline bufer orada saxlanılsaydı proqram ilk yazıda
; icazə xətası verərdi — və qüsur yalnız MÜŞTƏRİ maşınında görünərdi, çünki
; developer maşınında proqram repozitoriya qovluğundan işə düşür.
;
; ---------------------------------------------------------------------------
; CONFIG FAYLI SETUP-A DAXİL EDİLMİR (Variant B)
; ---------------------------------------------------------------------------
; Setup UNİVERSALDIR — hər müştəri EYNİ faylı işlədir. Konfiqurasiyanı paketə
; salsaydıq, hər müştəri üçün ayrıca Setup qurmaq lazım gələrdi və bir
; müştərinin baza parolu digərinin paketinə düşmək riski yaranardı.
; Bağlantı ilk açılışda «Bağlantı Ayarları» ekranından daxil edilir və proqram
; onu `{commonappdata}\KompasOS\connection.json`-a yazır.
; ===========================================================================

#define MyAppName "KompasOS"
; Versiya `src/__init__.py`-dakı `__version__` ilə EYNİ olmalıdır — uyğunsuzluq
; «Proqramlar» siyahısında bir, proqramın özündə başqa nömrə göstərərdi.
#define MyAppVersion "0.1.0"
; Buraxılışdan ƏVVƏL şirkətin rəsmi adı ilə əvəzlənir; kod imzalama
; sertifikatındakı ad ilə eyni olmalıdır (SEC-027), əks halda müştəri
; «Naşir: KompasOS» ilə «İmzalayan: <şirkət>» arasındakı fərqi görər.
#define MyAppPublisher "KompasOS"
#define MyAppExeName "KompasOS.exe"
#define MyAppIcon "..\assets\kompasos.ico"

[Setup]
; AppId DƏYİŞMƏZ olmalıdır: Windows quraşdırmanı məhz bu GUID ilə tanıyır.
; Dəyişdirilsə, növbəti buraxılış KÖHNƏSİNİ əvəz etmək yerinə YANINDA
; quraşdırılar və «Proqramlar» siyahısında iki KompasOS görünər.
AppId={{7C4B9E42-2F5D-4C31-9A6E-0D8B7F3A15C6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} quraşdırıcısı

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Qovluq seçimi ekranı GÖSTƏRİLİR: mağaza PC-lərində sistem diski kiçik ola
; bilər və quraşdırıcı başqa disk seçmək istəyə bilər.
DisableDirPage=no
DisableProgramGroupPage=yes

; `Program Files`-a yazmaq və `ProgramData`-da icazə təyin etmək üçün
; administrator lazımdır. `lowest` seçilsəydi, quraşdırma istifadəçi
; qovluğuna düşər və ikinci Windows hesabı proqramı ÜMUMİYYƏTLƏ görməzdi.
PrivilegesRequired=admin

OutputDir=..\dist
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 64-bit: `.exe` PyInstaller ilə x64 qurulur, 32-bit Windows-da işləməz.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; MİNİMUM WINDOWS 10 — QURAŞDIRMA ANINDA DAYANDIRILIR, AÇILIŞDA YOX.
;
; PySide6 6.x Windows 10-dan aşağıda işləmir və `qframelesswindow` çərçivəsiz
; pəncərə üçün Windows 10+ API-lərinə (`DwmExtendFrameIntoClientArea`,
; `GetDpiForWindow`) güvənir. `MinVersion` olmadan Setup Windows 8.1-də də
; quraşdırırdı: müştəri 400 MB yükləyir, quraşdırır, sonra proqram açılanda
; anlaşılmaz DLL xətası alırdı. İndi sihirbaz ilk ekranda AYDIN dayanır —
; səhvi tapmağın ən ucuz anı budur.
MinVersion=10.0

[Languages]
; Inno Setup-un rəsmi paylanmasında AZƏRBAYCAN dili YOXDUR — ona görə
; sihirbazın öz mətnləri İngiliscədir (config.md: «mümkünsə; deyilsə İngiliscə
; standart»). BİZİM yazdığımız mətnlər isə Azərbaycancadır: aşağıdakı
; `[CustomMessages]` bölməsi. Qeyri-rəsmi tərcümə faylı əlavə etmək variantı
; rədd edildi — o, Inno versiyası yeniləndikdə səssizcə köhnəlir və sihirbaz
; yarısı tərcümə olunmuş halda çıxır.
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.DesktopIconLabel=Masaüstündə qısayol yarat
english.LaunchAfterInstall={#MyAppName} proqramını indi başlat
english.RemoveDataPrompt=KompasOS silindi.%n%nKonfiqurasiya, loglar və yerli məlumat qovluğu («%1») saxlanılıb.%n%nOnları da silmək istəyirsiniz?%n%nDİQQƏT: göndərilməmiş offline yazılar və yüklənməmiş sübut şəkilləri varsa, onlar da silinəcək.
english.RemoveDataTitle=Məlumatı da silmək?

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIconLabel}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; `--onedir` çıxışının BÜTÜN məzmunu (`dist\KompasOS\` — 960+ fayl).
;
; NİYƏ TƏK `.exe` DEYİL: `--onefile` paketi hər açılışda özünü `%TEMP%`-ə
; açırdı və müştəri maşınında bu, 5-15 saniyə çəkirdi (bax `src/KompasOS.spec`
; başlığı). `--onedir`-də açılma yoxdur — ölçülmüş isti açılış 0.7 saniyədir.
;
; `recursesubdirs createallsubdirs` MƏCBURİDİR: `_internal\` altında Qt
; plaginləri, üz modelləri və şriftlər alt qovluqlardadır. Bayraqlar
; olmasaydı Setup səssizcə yalnız kök faylları yığar, proqram isə müştəri
; maşınında «platform plagini tapılmadı» ilə açılmazdı.
;
; `.env` və `connection.json` QƏSDƏN GÖNDƏRİLMİR: birincisi sirr saxlayır,
; ikincisi hər müştəridə fərqlidir (universal Setup — Variant B).
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; PAYLAŞILAN MƏLUMAT QOVLUĞU — icazə ilə birlikdə.
;
; `{commonappdata}` (= `C:\ProgramData`) altında yaradılan qovluq defolt olaraq
; YALNIZ yaradana tam icazə verir; digər istifadəçilər fayl yarada bilsə də
; BAŞQASININ faylını dəyişə bilmir. Mağaza PC-sində isə kassir A-nın yazdığı
; `connection.json`-u kassir B-nin proqramı YENİLƏYƏ bilməlidir (parol dəyişdi,
; server köçdü). Ona görə `users-modify` açıq verilir.
;
; Bu, qəsdən verilmiş bir güzəştdir: qovluqda sirr AÇIQ saxlanmır — parol
; DPAPI ilə şifrələnir (`config/connection_file.py`), `device.json`-da isə
; ümumiyyətlə sirr yoxdur (DEVICE-1).
Name: "{commonappdata}\{#MyAppName}"; Permissions: users-modify
Name: "{commonappdata}\{#MyAppName}\logs"; Permissions: users-modify
Name: "{commonappdata}\{#MyAppName}\data"; Permissions: users-modify

[Icons]
; Masaüstündə YALNIZ qısayol görünür — `.exe` və config `{app}` ilə
; `{commonappdata}` altındadır və istifadəçinin gözünə dəymir.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; `nowait postinstall skipifsilent` — sihirbazın son səhifəsindəki seçim.
; `runasoriginaluser`: Setup administrator kimi işləyir, proqram isə ADİ
; istifadəçi kimi açılmalıdır. Əks halda ilk sessiya admin hüququ ilə açılar
; və `%LOCALAPPDATA%`-dakı fayllar SƏHV hesabın altında yaranardı.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchAfterInstall}"; \
    Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
{ ---------------------------------------------------------------------------
  SİLİNMƏDƏ MƏLUMAT AVTOMATİK SİLİNMİR — SORUŞULUR
  ---------------------------------------------------------------------------
  `[UninstallDelete]` ilə qovluğu sükutla silmək ƏN PİS variantdır: orada
  göndərilməmiş offline yazılar və yüklənməmiş sübut şəkilləri ola bilər, sübut
  isə real pul kəsintisinin əsasıdır. Versiya yeniləməsi üçün silib-quraşdıran
  quraşdırıcı bir kliklə bütün növbəni itirərdi.

  Səssiz (`/SILENT`) rejimdə sual VERİLMİR və məlumat SAXLANILIR — sual
  verilməyən yerdə susmaq yeganə təhlükəsiz cavabdır.
  --------------------------------------------------------------------------- }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{commonappdata}\{#MyAppName}');
    if not DirExists(DataDir) then
      Exit;
    if UninstallSilent then
      Exit;
    if MsgBox(FmtMessage(CustomMessage('RemoveDataPrompt'), [DataDir]),
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(DataDir, True, True, True);
  end;
end;
