"""İcra rejimi: mənbədən işə salınıb, yoxsa paketlənmiş `.exe` içindəyik.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL
──────────────────────────────────────────────────────────────────────────────
`getattr(sys, "frozen", False)` bir sətirdir, lakin ONDAN ÇIXAN QƏRAR bir
sətir deyil: paketlənmiş rejimdə həm fayl yolları, həm də alt-proses çağırışı
FƏRQLİ qurulmalıdır. Həmin qərar üç yerdə lazımdır (`main`, kiosk nəzarətçisi,
plugin sandbox-u) və hər yerdə təkrar yazılsaydı, biri düzəldiləndə digərləri
səssizcə köhnə davranışda qalardı — audit zamanı məhz bu baş vermişdi.

Modul QƏSDƏN asılılıqsızdır (yalnız `sys`/`pathlib`): `shared` qatı domenin
altındadır və heç bir infrastruktur paketi idxal etmir.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: `--onefile` rejimində PyInstaller arxivi açdığı müvəqqəti qovluq.
_MEIPASS_ATTRIBUTE = "_MEIPASS"


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


__all__ = ["bundle_root", "deployment_root", "is_frozen", "relaunch_command"]
