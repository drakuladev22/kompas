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
    excludes=[],
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
    upx_exclude=[],
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
