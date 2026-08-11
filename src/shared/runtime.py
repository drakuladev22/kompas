"""İcra rejimi: mənbədən işə salınıb, yoxsa paketlənmiş `.exe` içindəyik.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL
──────────────────────────────────────────────────────────────────────────────
`getattr(sys, "frozen", False)` bir sətirdir, lakin ONDAN ÇIXAN QƏRAR bir
sətir deyil: paketlənmiş rejimdə həm fayl yolları, həm də alt-proses çağırışı
FƏRQLİ qurulmalıdır. Həmin qərar üç yerdə lazımdır (`main`, kiosk nəzarətçisi,
plugin sandbox-u) və hər yerdə təkrar yazılsaydı, biri düzəldiləndə digərləri
səssizcə köhnə davranışda qalardı — audit zamanı məhz bu baş vermişdi.

Modul QƏSDƏN asılılıqsızdır (yalnız standart kitabxana: `sys`/`os`/`shutil`/
`pathlib`): `shared` qatı domenin altındadır və heç bir infrastruktur paketi
idxal etmir.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Final

#: `--onefile` rejimində PyInstaller arxivi açdığı müvəqqəti qovluq.
_MEIPASS_ATTRIBUTE = "_MEIPASS"

#: Paketlənmiş quraşdırmada plugin interpretatorunun AÇIQ göstərilməsi üçün.
#: Boş buraxıla bilər — bax `plugin_interpreter()` və `.env.example`.
PLUGIN_PYTHON_ENV: Final[str] = "KOMPASOS_PLUGIN_PYTHON"


def is_frozen() -> bool:
    """PyInstaller ilə paketlənmiş `.exe` içində icra olunuruqmu."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path | None:
    """Paketin İÇİNDƏKİ resurslar üçün kök (`sys._MEIPASS`), yoxdursa `None`.

    `--add-data` ilə paketə salınmış fayl BURADA axtarılır. Hazırda tətbiq
    işləmə zamanı heç bir fayl resursuna müraciət etmir (ikonlar SVG mətni
    kimi koda hopdurulub — bax `presentation/widgets/icons.py`, üslub isə
    `theme/qss.py`-da şablondan qurulur), ona görə funksiya yalnız gələcək
    resurslar üçün TƏK doğru giriş nöqtəsi olaraq saxlanılır.
    """
    meipass = getattr(sys, _MEIPASS_ATTRIBUTE, None)
    return Path(str(meipass)) if meipass else None


def deployment_root() -> Path:
    """Paketin YANINDAKI yerləşdirmə fayllarının kökü.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `Path(__file__).parents[N]` PAKETLƏNMİŞ REJİMDƏ YARAMIR
    ──────────────────────────────────────────────────────────────────────────
    `--onefile` rejimində giriş skripti arxivin KÖKÜNƏ açılır — yəni `main.py`
    artıq `src/` qovluğunun altında DEYİL. Nəticədə mənbədə düzgün işləyən
    `Path(__file__).resolve().parents[1]` bir pillə ARTIQ yuxarı qalxır və
    istifadəçinin müvəqqəti qovluğunu göstərir. Auditdə `schema_file`
    yoxlaması məhz buna görə `%TEMP%\\database\\schema.sql` yolunu çap edirdi
    — mövcud olmayan, heç vaxt mövcud olmayacaq yol.

    Paketlənmiş rejimdə düzgün kök `.exe`-nin YANIdır: `database/` və `.env`
    YERLƏŞDİRMƏ artefaktlarıdır və qəsdən paketə salınmır (sirr `.exe`-yə
    hopdurulmur — bölmə 2), ona görə onları arxivin içində axtarmaq mənasızdır.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # `src/shared/runtime.py` → `src/shared` → `src` → repozitoriya kökü
    return Path(__file__).resolve().parents[2]


def relaunch_command() -> list[str]:
    """Tətbiqin ÖZÜNÜ yenidən işə salan əmrin prefiksi.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `[sys.executable, "-m", "src.main"]` PAKETDƏ SINIQDIR
    ──────────────────────────────────────────────────────────────────────────
    Paketlənmiş `.exe` Python interpretatoru DEYİL — `-m src.main` ona
    interpretator bayrağı kimi yox, ADİ ARQUMENT kimi çatır. Yoxlanılıb:

        KompasOS.exe -m src.main --gui --kiosk
        → kompasos: error: unrecognized arguments: -m src.main   (çıxış kodu 2)

    Kiosk nəzarətçisi bunu "çökmə" kimi görür və yenidən başladır; hər cəhd
    eyni xəta ilə bitdiyi üçün proses dərhal "restart fırtınası" limitinə
    dəyir və kiosk rejimi paketdə heç vaxt açılmır.
    """
    return [sys.executable] if is_frozen() else [sys.executable, "-m", "src.main"]


def plugin_interpreter() -> str | None:
    """Plugin alt-prosesi üçün ƏSL Python interpretatoru; tapılmasa `None`.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `sys.executable` PAKETDƏ YARAMIR
    ──────────────────────────────────────────────────────────────────────────
    Sandbox `[sys.executable, "-I", "-S", plugin.py]` çağırırdı. Paketlənmiş
    rejimdə `sys.executable` = `KompasOS.exe`, yəni interpretator DEYİL:
    `-I -S plugin.py` ona interpretator bayrağı kimi yox, ADİ ARQUMENT kimi
    çatır və `argparse` "unrecognized arguments" deyib 2 kodu ilə çıxır.
    Arqumentlər təsadüfən tanınsaydı nəticə daha pis olardı — istifadəçinin
    ekranında tətbiqin İKİNCİ nüsxəsi açılardı. Hər iki halda sandbox bunu
    "plugin xəta ilə bitdi (kod 2)" kimi göstərir, yəni ƏSL SƏBƏB gizli qalır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `relaunch_command()` BURADA İŞLƏMİR
    ──────────────────────────────────────────────────────────────────────────
    O köməkçi TƏTBİQİ yenidən işə salır — kiosk nəzarətçisinin istədiyi məhz
    budur. Sandbox-a isə tətbiq yox, TƏMİZ interpretator lazımdır: `-I -S`
    bayraqları "host-un mühiti, `PYTHONPATH`-ı və modulları görünməsin"
    deməkdir və `plugins/sandbox.py` bunu açıq zəmanət kimi elan edir
    (`test_plugin_cannot_import_host_modules`). Plugin-i `.exe`-nin öz
    proses obrazında (frozen arxivlə birlikdə) icra etsəydik, həmin zəmanət
    YALNIZ PAKETDƏ və SÜKUTLA itərdi: plugin `src.*` modullarını idxal edə
    bilərdi. Ona görə paketdə həqiqi interpretator AXTARILIR, tapılmazsa
    `None` qaytarılır və sandbox aydın səbəblə imtina edir — yanlış proses
    işə salmaqdansa icra etməmək təhlükəsizdir.
    """
    # 1. Quraşdırıcının açıq qərarı hər şeydən üstündür (hər iki rejimdə).
    override = os.environ.get(PLUGIN_PYTHON_ENV, "").strip()
    if override:
        return override
    # 2. Mənbədən icrada davranış DƏYİŞMİR — bu, elə cari interpretatordur.
    if not is_frozen():
        return sys.executable
    # 3. Paketin YANINA qoyulmuş interpretator (`deployment_root()` ilə eyni
    #    məntiq: `.exe`-nin qonşuluğu yerləşdirmə artefaktlarının yeridir).
    names = ("python.exe",) if sys.platform == "win32" else ("python3", "python")
    root = deployment_root()
    for directory in (root / "python", root):
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    # 4. Sistemdə quraşdırılmış Python.
    for name in names:
        found = shutil.which(name)
        # `WindowsApps` altındakı `python.exe` interpretator DEYİL, Microsoft
        # Store yönləndiricisidir: alt-proses kimi çağırıldıqda heç nə icra
        # etmir və 9009 kodu ilə çıxır — yəni "tapıldı" saymaq nasazlığı
        # anlaşılmaz "plugin xəta ilə bitdi (kod 9009)" mesajına çevirərdi.
        if found and "WindowsApps" not in found:
            return found
    return None


__all__ = [
    "PLUGIN_PYTHON_ENV",
    "bundle_root",
    "deployment_root",
    "is_frozen",
    "plugin_interpreter",
    "relaunch_command",
]
