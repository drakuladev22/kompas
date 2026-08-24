# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# KompasOS — PyInstaller spesifikasiyası
# =============================================================================
# BU FAYL QURMANIN TƏK HƏQİQƏT MƏNBƏYİDİR.
#
# `.github/workflows/ci.yml`-dəki HƏR İKİ qurma job-u (staging-build və
# production-release) məhz bu spec-i çağırır:
#
#     pyinstaller --noconfirm --clean src/KompasOS.spec
#
# NİYƏ BAYRAQLI ƏMRDƏN İMTİNA EDİLDİ
# -----------------------------------------------------------------------------
# Əvvəl CI `.exe`-ni bayraqlarla qururdu (`--onefile --windowed --name ...`),
# bu fayl isə yalnız "lokal diaqnostika" idi. Nəticə: buradakı `excludes` və
# `upx_exclude` kimi qərarlar İMZALANMIŞ artefakta HEÇ VAXT düşmürdü, amma
# fayla baxan adam düşdüyünü zənn edirdi. İki paralel təsvirin sinxron
# qalmasını yalnız intizam təmin edirdi — və belə paritet həmişə səssizcə
# pozulur, çünki pozuntu nə testdə, nə lint-də görünür; yalnız müştəri
# maşınında üzə çıxır. Bir təsvir + iki istehlakçı bu sinifdən olan bütün
# qüsurları struktur olaraq mümkünsüz edir.
#
# SEMANTİK PARİTET (köhnə əmr → bu fayl), sətir-bə-sətir:
#   --onefile   → EXE(...) çağırışına `a.binaries` və `a.datas` DAXİLDİR və
#                 COLLECT bloku YOXDUR; yəni tək fayllıq paket.
#   --windowed  → `console=False`
#   --name      → `name='KompasOS'` (çıxış yolu `dist/KompasOS.exe` DƏYİŞMİR —
#                 SEC-012 imzalama addımı məhz bu yolu gözləyir).
#   --icon      → `icon=...assets/kompasos.ico`
#   --add-data  → `datas=[(...kompasos.ico, 'assets')]`
# Yeganə QƏSDLİ fərq `upx=False`-dur (səbəbi aşağıda, EXE blokunda).
#
# `hiddenimports` NƏ ÜÇÜNDÜR
# -----------------------------------------------------------------------------
# Layihədə gec idxallar funksiya daxilində `from ... import ...` şəklindədir
# (`# noqa: PLC0415`). PyInstaller-in statik analizi bu formanı GÖRÜR — yalnız
# `importlib.import_module(dəyişən)` kimi həqiqi dinamik idxal görünməz olardı,
# belə istifadə isə `src/`-də yoxdur. `psycopg`, `PySide6`, `cryptography`,
# `PIL`, `argon2` üçün standart hook-lar kifayət edir (yoxlanılıb).
#
# Siyahı Face Control (`facecontrol.md` Faza 3) ilə DOLDU və səbəb yuxarıdakı
# qaydanın İSTİSNASIDIR — bax `_FACE_HIDDEN_IMPORTS` blokunun şərhi.
# =============================================================================
# =============================================================================
# CREDENTIALS PAKETƏ DAXİL EDİLMİR (DB-4 Faza 2 qərarı)
# =============================================================================
# `datas` siyahısında NƏ `.env`, NƏ `connection.json`, NƏ də hər hansı DSN var
# — və bu, unudulmuş addım deyil, QƏRARDIR:
#
#   * Tenant bazasının DSN-i HƏR MÜŞTƏRİDƏ FƏRQLİDİR. Onu paketə salsaydıq,
#     hər müştəri üçün ayrıca `.exe` qurmaq lazım gələrdi və bir müştərinin
#     paketi digərinin bazasına açar daşıyardı.
#   * Vendor bazasının DSN-i müştəri paketinə ÜMUMİYYƏTLƏ düşmür: qərar (DB-3)
#     budur ki, müştəri o bazaya nə yazır, nə oxuyur.
#   * `service_role` açarı heç bir halda paketə daxil edilmir.
#
# Konfiqurasiya paketin KƏNARINDA yaşayır:
#     %PROGRAMDATA%\KompasOS\connection.json   (parol AES-256-GCM ilə şifrəli)
# Oxuma sırası: `DATABASE_URL` → həmin fayl → «Bağlantı Ayarları» ekranı.
#
# `tests/unit/test_packaging_credentials.py` bu faylın credentials daşımadığını
# maşınla yoxlayır — şərh bir gün köhnələ bilər, test yox.
# =============================================================================
# =============================================================================
# SXEM PAKETƏ DAXİLDİR — CREDENTIALS İSƏ YOX (RECOVERY-1 Faza 3)
# =============================================================================
# `database/schema.sql` və `database/migrations/NNN_*.sql` ARTIQ paketə düşür.
# Bu, yuxarıdakı qərarla ziddiyyət DEYİL və fərqi bir cümlə ilə ifadə etmək
# olar: sxem NƏ QURULACAĞINI, credentials isə HARADA QURULACAĞINI deyir.
# Birincisi bütün müştərilərdə eynidir və sirr saxlamır (CREATE TABLE,
# trigger, seed defoltları); ikincisi hər müştəridə fərqlidir və sirrdir.
#
# Səbəb: «Bazanı Avtomatik Qur» düyməsi boş Supabase layihəsini bir kliklə
# qurur. Proqram nə quracağını ÖZÜ İLƏ DAŞIMALIDIR — xarici qovluğa
# arxalansaydıq, funksiya məhz ona ehtiyac duyulan maşında (yalnız Setup
# göndərilmiş müştəridə) işləməzdi.
#
# `migrations/vendor/` alt dəsti QƏSDƏN GİRMİR: o, təchizatçının mərkəzi
# bazası üçündür və müştəri bazasında yad cədvəllər yaradardı. Glob (`[0-9]
# [0-9][0-9]_*.sql`) yalnız kök səviyyəni götürür.
# =============================================================================
import os

from PyInstaller.utils.hooks import collect_data_files  # noqa: F821 — spec mühitində mövcuddur

# =============================================================================
# FACE CONTROL — üz təsdiqi (`facecontrol.md` Faza 3)
# =============================================================================
# NİYƏ `hiddenimports` LAZIMDIR (statik analiz KİFAYƏT ETMİR)
# -----------------------------------------------------------------------------
# `face_recognition` və `cv2` layihədə `try/except ImportError` blokunun
# İÇİNDƏ idxal olunur (bax `infrastructure/security/face_matcher.py` və
# `infrastructure/kiosk/camera.py` — nasazlıq `import`-un özünü çökdürməməlidir,
# çünki bənd 5 sükutla PIN-only rejimini qadağan edir və əvəzində eskalasiya
# tələb edir). PyInstaller belə idxalı GÖRÜR, lakin:
#   * `face_recognition` `dlib`-i C-genişlənməsi kimi çağırır — `dlib` heç bir
#     `import` sətrində birbaşa görünmür;
#   * `face_recognition_models` yalnız `pkg_resources` üzərindən (mətn açarı
#     ilə) yüklənir — statik analiz onu heç vaxt tapa bilməz;
#   * `pkg_resources`-un özü setuptools-un içindədir və heç bir modulumuz onu
#     birbaşa idxal etmir.
# Bunlar olmadan paketlənmiş `.exe` işə düşür, üz təsdiqi isə HƏMİŞƏ
# "mühərrik əlçatmazdır" deyir — yəni hər giriş manual təsdiqə düşər.
_FACE_HIDDEN_IMPORTS = [
    'dlib',
    'face_recognition',
    'face_recognition_models',
    'pkg_resources',
]

# =============================================================================
# NATIVE PƏNCƏRƏ ÖRTÜYÜ (Aero Snap + Windows 11 Snap Layouts)
# =============================================================================
# `presentation/shell/native_chrome.py` bu modulların HAMISINI `try/except
# ImportError` blokunun İÇİNDƏ, funksiya daxilində idxal edir (Linux/macOS-da
# modul idxalı çökməsin deyə). Yuxarıdakı ümumi qayda belə formanı "PyInstaller
# görür" deyir və bu, DOĞRUDUR — lakin nəticə burada təhlükəlidir:
#
#   * `qframelesswindow` idxal anında PLATFORMAYA GÖRƏ alt-modul seçir
#     (`windows/`, `linux/`, `mac/`). Statik analiz üç budağı da görür, lakin
#     `win32print`/`winreg` kimi yalnız bir budaqda işlənən modullar asanlıqla
#     kənarda qalır.
#   * `pywin32` paketi `win32api`/`win32gui`-ni C-genişlənməsi kimi verir və
#     onların yükləyicisi (`pywintypes`) heç bir `import` sətrində görünmür.
#
# Çatışmayan modul `.exe`-ni ÇÖKDÜRMÜR — `except ImportError` işə düşür və
# pəncərə sükutla saf-Qt yoluna keçir. Yəni qüsurun simptomu yalnız "snap
# işləmir"dir: qurma yaşıl, test yaşıl, müştəri isə pəncərəni ekran kənarına
# sürüşdürəndə heç nə baş vermir. Məhz buna görə siyahı AÇIQ yazılır.
# =============================================================================
# İŞLƏDİLMƏYƏN Qt MODULLARI — AÇILMA VAXTI VƏ PAKET ÖLÇÜSÜ ÜÇÜN
# =============================================================================
# Kod bazasında YALNIZ dörd PySide6 modulu idxal olunur (ölçülüb):
#
#     QtWidgets (72 idxal) · QtCore (53) · QtGui (44) · QtSvg (1)
#
# PyInstaller-in PySide6 hook-u isə tapdığı bütün Qt kitabxanalarını yığır və
# ən ağırı `QtWebEngine`-dir — tək başına ~100 MB, üstəlik yanında ayrıca
# `QtWebEngineProcess.exe` və resurs faylları gəlir. Onlar paketdə qaldıqca
# iki qiymət ödənilir: disk/şəbəkə həcmi və açılışda faylların oxunması.
#
# SİYAHI QƏSDƏN MÜHAFİZƏKARDIR. `QtNetwork`, `QtOpenGL`, `QtOpenGLWidgets` və
# `QtDBus` BURADA YOXDUR: onları heç bir modulumuz İDXAL ETMİR, lakin
# `QtWidgets`/platform plagini onlara dolayı söykənə bilər və çatışmayan DLL
# özünü yalnız müştəri maşınında, pəncərə ümumiyyətlə açılmayanda göstərərdi —
# bir neçə meqabayta görə belə risk götürülmür.
_UNUSED_QT_MODULES = [
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtWebChannel',
    'PySide6.QtWebSockets',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtSpatialAudio',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuick3D',
    'PySide6.QtQuickControls2',
    'PySide6.QtQuickWidgets',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic',
    'PySide6.Qt3DAnimation',
    'PySide6.Qt3DExtras',
    'PySide6.QtBluetooth',
    'PySide6.QtNfc',
    'PySide6.QtPositioning',
    'PySide6.QtLocation',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSerialBus',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech',
    'PySide6.QtHelp',
    'PySide6.QtDesigner',
    'PySide6.QtUiTools',
    'PySide6.QtTest',
    'PySide6.QtSql',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtNetworkAuth',
]

# Sxem + miqrasiyalar — «Bazanı Avtomatik Qur» üçün (bax fayl başlığı,
# «SXEM PAKETƏ DAXİLDİR» bölməsi). Glob yalnız KÖK səviyyədəki `NNN_*.sql`
# fayllarını götürür, `migrations/vendor/` alt dəsti DÜŞMÜR.
_DATABASE_DIR = os.path.join(SPECPATH, '..', 'database')  # noqa: F821
_DATABASE_DATAS = [
    (os.path.join(_DATABASE_DIR, 'schema.sql'), 'database'),
    (os.path.join(_DATABASE_DIR, 'migrations', '[0-9][0-9][0-9]_*.sql'), 'database/migrations'),
]

_WINDOW_CHROME_HIDDEN_IMPORTS = [
    'qframelesswindow',
    'qframelesswindow.windows',
    'qframelesswindow.windows.c_structures',
    'qframelesswindow.windows.window_effect',
    'qframelesswindow.utils',
    'qframelesswindow.utils.win32_utils',
    'win32api',
    'win32con',
    'win32gui',
    'win32print',   # `getDpiForWindow` ehtiyat yolu (köhnə Windows)
    'pywintypes',   # `win32*` genişlənmələrinin yükləyicisi
]

# MODEL FAYLLARI `datas`-A ƏLAVƏ OLUNMALIDIR — BUNSUZ `.exe` İŞLƏMİR
# -----------------------------------------------------------------------------
# Dlib-in dörd `.dat` modeli (68/5-nöqtə landmark, ResNet encoder, CNN
# detektor; ~132 MB) `face_recognition_models` paketinin İÇİNDƏDİR və
# PyInstaller onları avtomatik götürmür: onlar `.py` deyil, məlumat faylıdır və
# heç bir `import` sətri onlara istinad etmir. `pkg_resources.resource_filename`
# isə paketin qovluq strukturunu gözləyir, ona görə hədəf yolu (`face_
# recognition_models/models`) DƏYİŞDİRİLMƏMƏLİDİR.
_FACE_MODEL_DATAS = collect_data_files(
    'face_recognition_models', includes=['models/*.dat']
)
if not _FACE_MODEL_DATAS:
    # SÜKUTLA BOŞ QALMIR: boş siyahı ilə qurma UĞURLA bitər, `.exe` isə
    # müştəri maşınında "Please install face_recognition_models" deyib
    # çökərdi — yəni qüsur qurma maşınında deyil, mağazada üzə çıxardı.
    raise SystemExit(
        'Face Control model faylları tapılmadı. `pip install -r requirements.txt` '
        'ilə `face_recognition_models` paketini quraşdırın (bax requirements.txt, '
        'Face Control bölməsi).'
    )

# İKON ŞRİFTLƏRİ `datas`-A ƏLAVƏ OLUNMALIDIR — BUNSUZ `.exe`-DƏ İKON YOXDUR
# -----------------------------------------------------------------------------
# `qtawesome` ikonları `.ttf` şrift + `.json` charmap cütləri kimi paketin
# İÇİNDƏ daşıyır (Font Awesome, Material Design, Codicon və s.) və onlara heç
# bir `import` sətri istinad etmir — `_FACE_MODEL_DATAS`-la EYNİ tələnin
# forması. FƏRQ (`face_recognition_models`-dən): PyInstaller-in ÖZÜ
# `hook-qtawesome.py` daşıyır və o da məhz `collect_data_files('qtawesome')`
# çağırır, yəni bu blok TEXNİKİ cəhətdən artıqdır — daxili hook onsuz da
# eyni faylları toplayacaq (`Analysis.hookspath=[]` daxili hook axtarışını
# SÖNDÜRMÜR, yalnız ƏLAVƏ yol qoşur). Bu sətirlər QƏSDƏN buraxılıb: layihənin
# konvensiyası "sükutla boş qalmır"dır (bax aşağı) və daxili hook-un gələcək
# PyInstaller versiyasında dəyişməsi/silinməsi halında ERKƏN, AYDIN xəta
# vermək üçün ikiqat müdafiə dəyərlidir. Duplikat `datas` yazıları
# PyInstaller-in `TOC.append()`-i tərəfindən hədəf ada görə sükutla
# sıxışdırılır (mənbə kodunda yoxlanıb, `PyInstaller.building.datastruct`) —
# ikiqat siyahı xəbərdarlıq yaratmır.
_ICON_FONT_DATAS = collect_data_files('qtawesome')
if not _ICON_FONT_DATAS:
    # SÜKUTLA BOŞ QALMIR — səbəb `_FACE_MODEL_DATAS` ilə eynidir: boş siyahı
    # qurmanı UĞURLA bitirər, `.exe` isə mağazada ikonsuz/xətalı çıxardı.
    raise SystemExit(
        'qtawesome ikon şrift faylları tapılmadı. `pip install -r requirements.txt` '
        'ilə `qtawesome` paketini quraşdırın (bax requirements.txt, İkon Dəsti bölməsi).'
    )

a = Analysis(
    [os.path.join(SPECPATH, 'main.py')],  # noqa: F821 — SPECPATH-ı PyInstaller inject edir
    pathex=[],
    binaries=[],
    # Pəncərə/Taskbar ikonu paketin İÇİNƏ salınır. `--icon` yalnız `.exe`
    # faylının özünü bəzəyir; işləyən pəncərənin ikonu `setWindowIcon` ilə
    # runtime-da oxunur (bax `presentation/app.py::_apply_window_icon`).
    # CI əmrindəki `--add-data "assets/kompasos.ico;assets"` ilə eynidir.
    datas=[
        (os.path.join(SPECPATH, '..', 'assets', 'kompasos.ico'), 'assets'),  # noqa: F821
        # LOQO PNG-LƏRİ PAKETƏ DAXİLDİR (logo.md)
        # ---------------------------------------------------------------------
        # `.ico` yalnız `.exe` faylının və Taskbar-ın ikonudur. Başlıq zolağı və
        # splash isə PNG oxuyur (`widgets/brand_assets.py`) — onlar paketə
        # düşməsəydi, mənbədən işləyən tətbiq düzgün, PAKETLƏNMİŞ tətbiq isə
        # loqosuz (fallback çəkilən kvadratla) çıxardı və fərq yalnız müştəri
        # maşınında görünərdi.
        (os.path.join(SPECPATH, '..', 'assets', 'logo', '*.png'), 'assets/logo'),  # noqa: F821
        # INTER ŞRİFTİ PAKETƏ DAXİLDİR (`appl.md` FAZA 1)
        # ---------------------------------------------------------------------
        # Şrift Windows-da QURAŞDIRILMIŞ DEYİL — fayl paketə düşməsə,
        # `theme/fonts.py` onu tapmaz və interfeys ehtiyat şriftlə (Segoe UI)
        # çıxardı. Yəni mənbədən işləyən tətbiq bir cür, müştəri maşınındakı
        # `.exe` başqa cür görünərdi — loqo PNG-ləri ilə EYNİ tələ.
        #
        # `LICENSE-Inter.txt` də daxildir: SIL Open Font License lisenziya
        # nüsxəsinin şriftlə BİRLİKDƏ paylanmasını TƏLƏB edir.
        (os.path.join(SPECPATH, '..', 'assets', 'fonts', '*.ttf'), 'assets/fonts'),  # noqa: F821
        (os.path.join(SPECPATH, '..', 'assets', 'fonts', 'LICENSE-Inter.txt'), 'assets/fonts'),  # noqa: F821
        *_FACE_MODEL_DATAS,
        *_ICON_FONT_DATAS,
        *_DATABASE_DATAS,
    ],
    hiddenimports=[*_FACE_HIDDEN_IMPORTS, *_WINDOW_CHROME_HIDDEN_IMPORTS],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # TEST ÇƏRÇİVƏSİ İMZALANMIŞ `.exe`-YƏ DÜŞMƏMƏLİDİR
    # -------------------------------------------------------------------------
    # Bu gün `src/` altında heç bir modul `pytest`-i idxal etmir, ona görə bu
    # siyahı praktikada BOŞ nəticə verir — köhnə bayraqlı əmrlə qurulan paketə
    # nisbətən çıxışı DƏYİŞMİR (keçid təhlükəsizdir).
    # O, REQRESSİYA BARYERİDİR: istehsalat modulunda təsadüfən qalan bir
    # `import pytest` (məs. `pytest.approx` və ya köçürülmüş fixture köməkçisi)
    # bütün test ağacını buraxılış paketinə dartardı. Belə sürüşmə nə testdə,
    # nə də lint-də görünür — yalnız paketin ölçüsündə və hücum səthində.
    excludes=['pytest', '_pytest', 'tests', *_UNUSED_QT_MODULES],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

# =============================================================================
# `--onedir` — NİYƏ `--onefile` DEYİL
# =============================================================================
# `--onefile` paketi hər AÇILIŞDA özünü `%TEMP%`-ə açır: 230 MB-lıq arxiv
# müştəri maşınında 5-15 saniyə çəkirdi və istifadəçi bu müddətdə heç nə
# görmür — proqram «açılmır» kimi qavranılır. Üstəlik həmin fayllar hər dəfə
# antivirus tərəfindən yenidən yoxlanılır.
#
# `--onedir`-də açılma YOXDUR: `.exe` yanındakı DLL-ləri birbaşa yükləyir.
# Ödənilən qiymət odur ki, quraşdırma qovluğunda 100+ fayl görünür — lakin
# onlar `C:\Program Files\KompasOS\` altındadır və istifadəçi ora baxmır
# (masaüstündə YALNIZ qısayol var).
#
# `exclude_binaries=True` + `COLLECT` məhz bu deməkdir: `EXE` yalnız
# başladıcıdır, kitabxanalar isə yanındakı qovluqdadır.
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KompasOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX QƏSDƏN SÖNDÜRÜLÜB — QURMA MAŞINDAN ASILI OLMAMALIDIR
    # -------------------------------------------------------------------------
    # `upx=True` (PyInstaller-in defoltu) yalnız UPX ikili faylı PATH-dədirsə
    # işə düşür. GitHub Windows runner-ində UPX YOXDUR, hazırlayıcı maşınında
    # isə ola bilər — yəni eyni commit-dən qurulan iki `.exe` MÜXTƏLİF çıxardı.
    # Bu, spec-i tək mənbəyə çevirməyin bütün mənasını puç edir: reproduksiya
    # edilə bilməyən qurma ilə "CI-da işləmir, məndə işləyir" sinfindən olan
    # qüsuru araşdırmaq mümkün deyil.
    # İkinci və daha ağır səbəb: UPX Qt6/libpq/OpenSSL DLL-lərini sıxdıqda
    # `qwindows.dll` plugin-i yüklənməyə bilir (pəncərə ümumiyyətlə açılmır),
    # üstəlik sıxılmış icra faylı Authenticode/antivirus evristikasında
    # yalançı-müsbət mənbəyidir — imzalanmış buraxılış üçün (SEC-012) bu,
    # qazanılan bir neçə meqabaytdan qat-qat bahalı riskdir.
    upx=False,
    # `upx=False` olduqda bu siyahı praktikada işə düşmür; qəsdən SAXLANILIR ki,
    # kimsə gələcəkdə sıxılmanı yenidən açsa, ən riskli fayllar onsuz da kənarda
    # qalsın (söndürməni geri qaytarmaq bir sətirdir, bu siyahını yenidən
    # kəşf etmək isə bir çökmə araşdırması).
    upx_exclude=[
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
        'Qt6Svg.dll',
        'Qt6Network.dll',
        'qwindows.dll',
        'shiboken6.abi3.dll',
        'libpq.dll',        # psycopg[binary] — bağlantı qatının özəyi
        'libssl-3-x64.dll',
        'libcrypto-3-x64.dll',
        'python3.dll',
        'python311.dll',    # CI-dakı Python versiyası ilə eynidir
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'msvcp140.dll',
    ],
    runtime_tmpdir=None,
    # `--windowed` ekvivalenti. Çökmə diaqnostikası üçün MÜVƏQQƏTİ olaraq
    # `True` edilə bilər: `--windowed` rejimdə çökmə səssiz olur, konsolda isə
    # traceback görünür.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # İkon CI əmrindəki `--icon assets/kompasos.ico` ilə eynidir. Əvvəl burada
    # YOX idi: spec ilə qurulan `.exe` PyInstaller-in defolt ikonu ilə çıxırdı
    # və buraxılış paketindən görünüşcə fərqlənirdi.
    icon=os.path.join(SPECPATH, '..', 'assets', 'kompasos.ico'),  # noqa: F821
)

# `COLLECT` `--onedir` çıxışını yığır: `dist/KompasOS/` qovluğu.
#
# ADI `KompasOS`-dur və bu, Inno Setup skriptinin gözlədiyi yoldur
# (`installer/KompasOS.iss` → `Source: "..\dist\KompasOS\*"`). Adı dəyişdirsək
# quraşdırıcı sükutla BOŞ paket yığar: `.iss` faylı olmayan qovluğu yalnız
# `Flags: recursesubdirs` ilə axtarır və tapmadıqda xəta VERMİR.
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='KompasOS',
)
