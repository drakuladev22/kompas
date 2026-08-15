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
        *_FACE_MODEL_DATAS,
    ],
    hiddenimports=_FACE_HIDDEN_IMPORTS,
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
    excludes=['pytest', '_pytest', 'tests'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
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
