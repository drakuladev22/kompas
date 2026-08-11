"""Yerli SQLite fayllarının kökü — CARİ QOVLUQDAN ASILI OLMAYAN yol.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `./data/...` PAKETLƏNMİŞ REJİMDƏ SINIQDIR
──────────────────────────────────────────────────────────────────────────────
`Path("./data/offline_buffer.db")` cari İŞ QOVLUĞUNA (CWD) görə həll olunur.
Mənbədən icrada CWD repozitoriya kökü olur və yol işləyir — qüsur məhz buna
görə inkişaf mühitində heç vaxt görünmür. Paketlənmiş `.exe`-də isə CWD
ixtiyaridir:

    * Start menyusu qısayolundan açılanda CWD `C:\\Windows\\System32` olur —
      standart istifadəçinin ora yazma hüququ YOXDUR;
    * kiosk nəzarətçisi alt-prosesə `cwd=deployment_root()` verir
      (`kiosk/watchdog.py`), yəni `C:\\Program Files\\KompasOS` — UAC olmadan
      bura da yazıla bilmir.

Nəticə hər iki halda eynidir və İLK YAZI anına qədər gizli qalır:
`sqlite3.OperationalError: unable to open database file` — yəni ilk sübut
şəkli və ya ilk offline yazı. Nasazlığın proqramın işə salınma ÜSULUNDAN asılı
olması onu ən çətin diaqnoz olunan növə çevirirdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `LOCALAPPDATA` (roaming `APPDATA` DEYİL)
──────────────────────────────────────────────────────────────────────────────
Burada saxlanan iki fayl SQLite BAZASIDIR: yanlarında WAL jurnalı, sübut
növbəsinin isə üstəlik `evidence_spool/` qovluğu var (`upload_queue.py`).
Domen mühitində roaming profil `APPDATA`-nı şəbəkə üzərindən sinxronlaşdırır
və baza faylı ilə WAL jurnalını AYRI-AYRI anlarda köçürə bilər — bu, bazanı
korlayır. Ona görə kök MAŞINA bağlı `LOCALAPPDATA`-dır; eyni seçim DPAPI
blobu üçün də edilib (`security/encryption.py`). Windows-dan kənarda XDG
qarşılığı işlədilir — `state_store.py` və `backup/service.py` ilə eyni naxış.

──────────────────────────────────────────────────────────────────────────────
KÖHNƏ QURAŞDIRMA: FAYL KÖÇÜRÜLMÜR, YALNIZ TANINIR
──────────────────────────────────────────────────────────────────────────────
Mövcud quraşdırmada `./data/offline_buffer.db` HƏLƏ GÖNDƏRİLMƏMİŞ yazıları,
`./data/evidence_uploads.db` isə hələ yüklənməmiş şəkillərin indeksini saxlaya
bilər; şəkillərin BAYTLARI həmin faylın yanındakı `evidence_spool/`
qovluğundadır. Avtomatik köçürmə iki faylı və bir qovluğu atomik OLMAYAN
şəkildə daşımaq demək olardı: yarımçıq qalan köçürmə (proses öldürülür, disk
dolur, fayl kilidlidir) indeksi öz spool fayllarından ayırar və cərimə
"sübutsuz" qalardı. Sübut isə real pul kəsintisinin əsasıdır.

Ona görə köçürmə YOXDUR — sadəcə FALLBACK var: köhnə yol MÖVCUDDURSA həmin
fayl işlədilməyə davam edir. Bu qərar idempotentdir (heç nə yazılmır,
silinmir, adı dəyişdirilmir) və köhnə növbəni görünməz etmir. Yeni yerə
keçmək istəyən quraşdırıcı ya faylları özü köçürür, ya da
`KOMPASOS_SQLITE_PATH` / `KOMPASOS_EVIDENCE_QUEUE_PATH` ilə açıq yol göstərir
— hər iki mühit dəyişəni bu modula qədər ÜSTÜNDÜR.

Modul QƏSDƏN yalnız standart kitabxanaya (`os`/`pathlib`) söykənir: `shared`
qatı ən aşağıdadır və heç bir infrastruktur paketi idxal etmir.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

#: Bütün yerli fayllarımızın altında toplandığı qovluq adı.
APP_DIR_NAME: Final[str] = "KompasOS"

#: Köhnə (CWD-yə bağlı) defolt qovluq — YALNIZ geriyə uyğunluq üçün oxunur.
LEGACY_DATA_DIR: Final[str] = "data"


def default_data_dir() -> Path:
    """`%LOCALAPPDATA%\\KompasOS\\data` və ya XDG qarşılığı.

    Qovluq BURADA yaradılmır: hər iki istifadəçi (`OfflineBuffer`,
    `EvidenceUploadQueue`) konstruktorunda `mkdir(parents=True)` çağırır və
    qovluğu iki yerdə yaratmaq "kim sahibdir" sualını bulandırardı.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_DIR_NAME / LEGACY_DATA_DIR


def legacy_data_file(filename: str) -> Path:
    """Köhnə, CWD-yə nisbi yol (`./data/<fayl>`) — yalnız MÖVCUDLUQ yoxlaması üçün."""
    return Path(LEGACY_DATA_DIR) / filename


def resolve_data_file(env_key: str, filename: str) -> Path:
    """Yerli SQLite faylının yolu: mühit dəyişəni → köhnə fayl → yeni defolt.

    Sıra qəsdən belədir:

    1. **Mühit dəyişəni** — quraşdırıcının açıq qərarı hər şeydən üstündür və
       mövcud davranış BİR ZƏRRƏ dəyişmir (dəyər boşdursa təyin olunmamış
       sayılır — `.env` faylında boş sətir adi haldır).
    2. **Köhnə fayl** — `./data/<fayl>` HƏQİQƏTƏN varsa o işlədilir. Yalnız
       "var" halına baxılır: yol mövcud deyilsə heç nə yaradılmır, yəni
       System32-də icra edilən `.exe` bu budağa ümumiyyətlə düşmür.
    3. **Yeni defolt** — istifadəçi məlumat qovluğu (bax modul başlığı).
    """
    override = os.environ.get(env_key, "").strip()
    if override:
        return Path(override)
    legacy = legacy_data_file(filename)
    # `is_file()` icazə xətasında da `False` qaytarır — oxuna bilməyən CWD
    # (məs. şəbəkə diski qopub) burada istisna atmamalıdır, çünki bu, sadəcə
    # "köhnə fayl yoxdur" deməkdir və yeni defolt onsuz da işləkdir.
    if legacy.is_file():
        return legacy
    return default_data_dir() / filename


__all__ = [
    "APP_DIR_NAME",
    "LEGACY_DATA_DIR",
    "default_data_dir",
    "legacy_data_file",
    "resolve_data_file",
]
