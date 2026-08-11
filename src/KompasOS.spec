# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# KompasOS — PyInstaller spesifikasiyası
# =============================================================================
# DİQQƏT: CI BU FAYLI İŞLƏTMİR.
#
# `.github/workflows/ci.yml` (staging-build və production-release) `.exe`-ni
# BAYRAQLARLA qurur:
#
#     pyinstaller --noconfirm --clean --onefile --windowed \
#       --name KompasOS --icon assets/kompasos.ico src/main.py
#
# Fayl repozitoriyada saxlanılır (bax `.gitignore`-dakı `!KompasOS.spec`
# istisnası), çünki lokal təkrar-qurma və diaqnostika üçün rahatdır. Lakin o,
# CI üçün MƏNBƏ DEYİL — buradakı dəyişiklik buraxılışa TƏSİR ETMİR.
#
# NİYƏ TƏK MƏNBƏYƏ KEÇİLMƏDİ
# -----------------------------------------------------------------------------
# CI-ın bayraqlı yolu auditdə lokal olaraq təkrarlanıb və İŞLƏK `.exe` verib
# (Qt `qwindows.dll`, `libpq`, `libssl`, `_argon2_cffi_bindings` — hamısı
# paketə düşür, `warn-*.txt`-də əhəmiyyətli çatışmazlıq yoxdur). İmzalanmış
# istehsalat yolunu (SEC-012) yoxlanılmamış bir qurma yoluna keçirmək audit
# çərçivəsində əsassız risk olardı. Ona görə CI mənbə olaraq qalır, bu fayl
# isə onunla EYNİ nəticəni verəcək şəkildə saxlanılır.
#
# QAYDA: bu iki yer BİRLİKDƏ dəyişdirilir. Burada `--collect-all` və ya
# `hiddenimports` əlavə edilirsə, EYNİ dəyişiklik CI əmrinə də yazılmalıdır,
# əks halda buraxılış paketi lokal paketdən fərqlənər — və fərq yalnız
# müştəri maşınında üzə çıxar.
#
# `hiddenimports` NİYƏ BOŞDUR
# -----------------------------------------------------------------------------
# Layihədə gec idxallar funksiya daxilində `from ... import ...` şəklindədir
# (`# noqa: PLC0415`). PyInstaller-in statik analizi bu formanı GÖRÜR — yalnız
# `importlib.import_module(dəyişən)` kimi həqiqi dinamik idxal görünməz olardı,
# belə istifadə isə `src/`-də yoxdur. `psycopg`, `PySide6`, `cryptography`,
# `PIL`, `argon2` üçün standart hook-lar kifayət edir (yoxlanılıb).
# =============================================================================
import os

a = Analysis(
    [os.path.join(SPECPATH, 'main.py')],  # noqa: F821 — SPECPATH-ı PyInstaller inject edir
    pathex=[],
    binaries=[],
    # Pəncərə/Taskbar ikonu paketin İÇİNƏ salınır. `--icon` yalnız `.exe`
    # faylının özünü bəzəyir; işləyən pəncərənin ikonu `setWindowIcon` ilə
    # runtime-da oxunur (bax `presentation/app.py::_apply_window_icon`).
    # CI əmrindəki `--add-data "assets/kompasos.ico;assets"` ilə eynidir.
    datas=[(os.path.join(SPECPATH, '..', 'assets', 'kompasos.ico'), 'assets')],  # noqa: F821
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # TEST ÇƏRÇİVƏSİ İMZALANMIŞ `.exe`-YƏ DÜŞMƏMƏLİDİR
    # -------------------------------------------------------------------------
    # Bu gün `src/` altında heç bir modul `pytest`-i idxal etmir, ona görə bu
    # siyahı praktikada BOŞ nəticə verir — yəni CI-ın bayraqlı yolu ilə çıxış
    # fərqi YARATMIR (spec ↔ CI paritetini pozmur, bax fayl başlığı).
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
    upx=True,
    # UPX NATİV KİTABXANALARA TOXUNMAMALIDIR
    # -------------------------------------------------------------------------
    # NİYƏ BU SİYAHI LAZIMDIR: `upx=True` yalnız UPX ikili faylı PATH-dədirsə
    # işə düşür. GitHub Windows runner-ində UPX YOXDUR, ona görə CI-ın verdiyi
    # `.exe` SIXILMAMIŞDIR; UPX quraşdırılmış hazırlayıcı maşınında isə eyni
    # spec Qt6/libpq/OpenSSL DLL-lərini sıxardı. Nəticədə bu faylın yeganə
    # məqsədi olan şey — "CI ilə EYNİ nəticə" (fayl başlığı) — pozulur və
    # diaqnostika üçün qurulan paket buraxılış paketindən FƏRQLİ olur.
    # Sıxılmış Qt6 DLL-ləri həm işə düşməmə (plugin `qwindows.dll` yüklənmir),
    # həm də Authenticode/antivirus evristikasında yalançı-müsbət mənbəyidir —
    # yəni fərq ən pis yerdə, müştəri maşınında üzə çıxardı.
    # Tam paritet üçün doğru yol `upx=False`-dur; mövcud sətir qəsdən
    # dəyişdirilmir (audit səlahiyyəti yalnız ƏLAVƏ etməkdir) — bu istisna
    # siyahısı isə ən riskli faylları onsuz da kənarda saxlayır.
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
