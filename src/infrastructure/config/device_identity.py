r"""Cihaz kimliyi: `%PROGRAMDATA%\KompasOS\device.json` + aparat izi (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `connection.json`-DAN AYRI FAYL
──────────────────────────────────────────────────────────────────────────────
İki fayl fərqli ÖMÜR daşıyır. Bağlantı ayarları quraşdırıcı tərəfindən
dəyişdirilir (server köçdü, parol dəyişdi) və həmin əməliyyat cihazın
kimliyini İTİRMƏMƏLİDİR — vahid faylda parolu düzəltmək üçün faylı silmək
cihazın təsdiqini də silərdi və mağaza yenidən qeydiyyat gözləyərdi.

Yer eynidir (`%PROGRAMDATA%`) və səbəb DB-4-də verilmiş qərarın eynidir:
paylaşılan mağaza PC-sində ikinci Windows hesabı `%LOCALAPPDATA%`-dakı faylı
GÖRMƏZDİ və özünü yeni cihaz sanardı — yəni hər hesab bir lisenziya yeri
yeyərdi.

──────────────────────────────────────────────────────────────────────────────
FAYLDA SİRR YOXDUR — ONA GÖRƏ ŞİFRƏLƏNMİR
──────────────────────────────────────────────────────────────────────────────
`connection.json` parolu şifrələyir, çünki orada sirr var. Burada isə yalnız
`device_id` UUID-i var və o, TƏK BAŞINA heç nə açmır: cihaz təsdiqlənməyibsə
UUID işə yaramır, təsdiqlənibsə isə UUID-i oğurlamaq fingerprint uyğunsuzluğu
yaradır və audit-ə düşür. Şifrələmək təhlükəsizlik vermədən quraşdırıcının
diaqnostika imkanını (faylı gözlə yoxlamaq) əlindən alardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `wmic` DEYİL — VƏ NİYƏ İKİ AYRI MƏNBƏ
──────────────────────────────────────────────────────────────────────────────
Modul əvvəllər üç `wmic` sorğusuna bağlı idi. Microsoft `wmic.exe`-ni Windows
11 24H2-dən sonra sistemdən ÇIXARDI: əmr tapılmır, hər üç sorğu dərhal
`FileNotFoundError` verir və nəticə HƏR açılışda zəif fingerprint olurdu.
Qüsur sükutlu idi — proqram normal açılır, sadəcə `device.json`-un başqa
maşına köçürülməsini aşkarlayan yeganə lövbər itirdi.

İndi iki mənbə var və onlar QƏSDƏN fərqli xarakterlidir:

    1. `machine_guid` — REGISTRY-dən (`winreg`), subprocess-siz, ~0.5 ms və
       nasazlığı praktiki olaraq mümkün deyil. Bu, izin lövbəridir: sorğu
       icra faylı yoxa çıxsa da fingerprint zəif yola DÜŞMÜR.
    2. anakart/disk/SMBIOS seriyaları — TƏK PowerShell `Get-CimInstance`
       çağırışı ilə. CIM `wmic`-dən fərqli olaraq çıxarılmayıb və hər
       dəstəklənən Windows-da var.

Üç ayrı proses əvəzinə BİR proses açılır: açılış yolundayıq, hər proses soyuq
başlanğıcda saniyələr yeyir. Hissələrin ardıcıllığı da SABİTdir (registry →
anakart → disk → SMBIOS), çünki hash sıradan asılıdır.

──────────────────────────────────────────────────────────────────────────────
NASAZLIQ DAYANDIRICI DEYİL
──────────────────────────────────────────────────────────────────────────────
Anakart/disk seriyası bəzi maşınlarda (virtual maşın, bəzi OEM lövhələr) boş
qayıdır. Belə halda tətbiqin açılmaması ƏN PİS nəticədir: fingerprint kimlik
DEYİL, yalnız dəyişiklik detektorudur (`domain/value_objects/devices.py`).
Ona görə oxuna bilən NƏ VARSA ondan hash qurulur; heç nə oxunmasa maşın adı
və istifadəçi profili yolu işlədilir — zəif, lakin sıfırdan yaxşı, və zəiflik
audit-ə yazılır.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Final

from src.domain.value_objects.devices import DeviceFingerprint
from src.domain.value_objects.identifiers import DeviceId
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

_log = get_logger(__name__)

#: Test və xüsusi quraşdırma üçün yolu əvəzləyən mühit dəyişəni.
DEVICE_FILE_ENV: Final[str] = "KOMPASOS_DEVICE_FILE"
DEVICE_FILENAME: Final[str] = "device.json"
APP_DIR_NAME: Final[str] = "KompasOS"

#: Aparat sorğusunun taymautu. Sabit ədəddir və ROOT PARAMETRİ DEYİL: bu,
#: tətbiqin AÇILIŞ yolundadır — Root dəyəri oxumaq üçün baza lazımdır, baza
#: isə hələ açılmayıb. Dövri asılılıq yaranardı.
#:
#: 8 saniyə üç `wmic` sorğusunun köhnə 3×5 = 15 saniyəlik ən pis halından
#: AZDIR, lakin soyuq PowerShell başlanğıcına (antivirus yoxlaması ilə
#: birlikdə köhnə mağaza PC-sində bir neçə saniyə) dözür. Taymaut baş versə
#: `machine_guid` onsuz da toplanıb — fingerprint zəif yola düşmür.
HARDWARE_PROBE_TIMEOUT_SECONDS: Final[float] = 8.0

#: Windows kriptoqrafiya bölməsindəki quraşdırma GUID-i. Aparat SERİYASI
#: deyil, lakin köçürmə detektoru üçün ondan güclüdür: fayl başqa maşına
#: köçürüləndə mütləq dəyişir, disk təmir olunanda isə dəyişmir.
_MACHINE_GUID_KEY: Final[str] = r"SOFTWARE\Microsoft\Cryptography"
_MACHINE_GUID_VALUE: Final[str] = "MachineGuid"

#: PowerShell skripti. İstifadəçi mətni QƏBUL ETMİR — tam sabitdir və
#: `shell=False` ilə massiv kimi ötürülür, yəni inyeksiya səthi yoxdur.
#: Disk `DeviceID`-yə görə çeşidlənir: sıralama olmasaydı iki diskli maşında
#: sadalanma sırası boot-dan boot-a dəyişib saxta uyğunsuzluq yaradardı.
_PROBE_SCRIPT: Final[str] = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$b=(Get-CimInstance Win32_BaseBoard|Select-Object -First 1).SerialNumber;"
    "$d=(Get-CimInstance Win32_DiskDrive|Sort-Object DeviceID|Select-Object -First 1)"
    ".SerialNumber;"
    "$u=(Get-CimInstance Win32_ComputerSystemProduct|Select-Object -First 1).UUID;"
    'Write-Output "BASEBOARD=$b";Write-Output "DISK=$d";Write-Output "UUID=$u"'
)

#: Aparat sorğusunun tam əmri.
HARDWARE_PROBE_COMMAND: Final[tuple[str, ...]] = (
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    _PROBE_SCRIPT,
)

#: Çıxış açarı → fingerprint hissəsinin adı. Sıra hash-ə düşən sıradır.
_PROBE_LABELS: Final[tuple[tuple[str, str], ...]] = (
    ("BASEBOARD", "baseboard"),
    ("DISK", "diskdrive"),
    ("UUID", "csproduct"),
)

#: OEM-in doldurmadığı sahələr. Bunları hash-a qatmaq maşınları bir-birindən
#: UZAQLAŞDIRMAZDI, əksinə YAXINLAŞDIRARDI — eyni «Default string» minlərlə
#: lövhədə var.
_PLACEHOLDER_VALUES: Final[frozenset[str]] = frozenset(
    {
        "to be filled by o.e.m.",
        "default string",
        "none",
        "system serial number",
        "0",
        "00000000-0000-0000-0000-000000000000",
    }
)


class DeviceIdentityError(KompasOSError):
    """Cihaz kimliyi faylı oxunmadı və ya yazılmadı."""

    user_message = "Cihaz konfiqurasiyası oxunmadı. Administratorunuzla əlaqə saxlayın."


def device_file_path() -> Path:
    """Kimlik faylının yolu (mühit dəyişəni ilə əvəzlənə bilər)."""
    override = os.environ.get(DEVICE_FILE_ENV, "").strip()
    if override:
        return Path(override)
    base = os.environ.get("PROGRAMDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME / DEVICE_FILENAME


def load_device_id(path: Path | None = None) -> DeviceId | None:
    """Saxlanmış `device_id`; fayl yoxdursa `None` (ilk açılış).

    `None` XƏTA DEYİL — ilk açılış gözlənilən haldır. Lakin fayl VAR və
    oxunmursa istisna atılır: onu sükutla «ilk açılış» saymaq cihazın
    təsdiqini itirər və yeni qeydiyyat yaradaraq lisenziya yeri yeyərdi.
    """
    target = path or device_file_path()
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        raw = str(payload["device_id"])
        return DeviceId(uuid.UUID(raw))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise DeviceIdentityError(
            "Cihaz kimliyi faylı oxunmadı",
            user_message=(
                f"«{target}» faylı korlanıb. Onu silsəniz cihaz yenidən "
                "təsdiq gözləyəcək — administratorunuzla əlaqə saxlayın."
            ),
            context={"path": str(target), "error": str(exc)},
        ) from exc


def save_device_id(device_id: DeviceId, path: Path | None = None) -> Path:
    """Kimliyi diskə yazır və yolunu qaytarır."""
    target = path or device_file_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"device_id": str(device_id)}, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise DeviceIdentityError(
            "Cihaz kimliyi yazılmadı",
            user_message=(f"«{target}» yazıla bilmədi. Proqramı administrator hüququ ilə açın."),
            context={"path": str(target), "error": str(exc)},
        ) from exc
    _log.info("DEVICE_IDENTITY_SAVED", extra={"path": str(target)})
    return target


def collect_fingerprint() -> DeviceFingerprint:
    """Aparat izini oxuyur; nasazlıqda zəif, lakin işlək dəyər qaytarır."""
    parts = [value for _, value in _hardware_parts()]
    if parts:
        return DeviceFingerprint.from_parts(*parts)

    # Heç bir aparat göstəricisi oxunmadı — bax modul başlığı.
    _log.warning(
        "DEVICE_FINGERPRINT_WEAK",
        extra={
            "reason": "aparat göstəriciləri oxunmadı",
            "impact": "cihaz köçürülməsi aşkarlanmaya bilər",
        },
    )
    return DeviceFingerprint.from_parts(platform.node() or "UNKNOWN", str(Path.home()))


def _hardware_parts() -> list[tuple[str, str]]:
    """Oxuna bilən aparat göstəriciləri — `(mənbə, dəyər)` cütləri."""
    if platform.system() != "Windows":
        # Registry də, CIM də yalnız Windows-dadır. Linux/macOS-da (CI,
        # developer maşını) boş qayıdırıq və çağıran tərəf zəif fingerprint-ə
        # düşür — bu, test mühitində gözlənilən davranışdır, qüsur deyil.
        return []

    found: list[tuple[str, str]] = []
    guid = _read_machine_guid()
    if guid:
        found.append(("machine_guid", guid))
    found.extend(_parse_probe_output(_probe_hardware()))
    return found


def _read_machine_guid() -> str:
    """Windows quraşdırma GUID-i; oxunmasa boş sətir.

    Qapı İCRA üçündür: CI pytest-i Ubuntu-da da işlədir və orada `winreg`
    modulu ÜMUMİYYƏTLƏ yoxdur — idxal `ImportError` verərdi.

    `platform.system()` əvəzinə `sys.platform` seçilib, çünki mypy məhz bu
    formanı STATİK platforma qapısı sayır və budağı səssizcə kəsir (pyproject
    mypy-ı `platform = "win32"`-ə bağlayır). Beləcə tək yoxlanış həm icraya,
    həm də tip yoxlayıcısına xidmət edir.
    """
    if sys.platform != "win32":
        return ""
    import winreg  # noqa: PLC0415 — Windows-a xas modul, yuxarıda idxal oluna bilməz

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_GUID_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _MACHINE_GUID_VALUE)
    except OSError as exc:
        _log.debug("MACHINE_GUID_UNREADABLE", extra={"error": str(exc)})
        return ""
    return str(value).strip()


def _probe_hardware() -> str:
    """Aparat sorğusunun xam çıxışı; nasazlıqda boş sətir.

    Hər nasazlıq udulur və YALNIZ debug jurnalına düşür: sorğu qadağan
    edilmiş PowerShell siyasəti olan maşınlarda işləməyə bilər. Bunu
    xəbərdarlıq kimi yazsaydıq, hər açılışda görünərdi və həqiqi problemləri
    gizlədərdi — həqiqi siqnal `DEVICE_FINGERPRINT_WEAK`-dir və o, YALNIZ
    heç bir mənbə qalmayanda yazılır.
    """
    try:
        result = subprocess.run(  # noqa: S603 — əmr SABİT massivdir, `shell=False`
            HARDWARE_PROBE_COMMAND,
            capture_output=True,
            text=True,
            timeout=HARDWARE_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log.debug("HARDWARE_PROBE_FAILED", extra={"error": str(exc)})
        return ""
    if result.returncode != 0:
        _log.debug("HARDWARE_PROBE_FAILED", extra={"returncode": result.returncode})
        return ""
    return str(result.stdout)


def _parse_probe_output(stdout: str) -> list[tuple[str, str]]:
    """`KEY=VALUE` sətirlərini `(mənbə, dəyər)` cütlərinə çevirir.

    Sıra ÇIXIŞDAN yox, `_PROBE_LABELS`-dən götürülür: PowerShell sətirlərin
    ardıcıllığını dəyişsə hash da dəyişərdi və eyni maşın özünü «dəyişmiş»
    kimi göstərərdi.
    """
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, raw = line.partition("=")
        if not separator:
            continue
        values[key.strip().upper()] = raw.strip()

    found: list[tuple[str, str]] = []
    for key, source in _PROBE_LABELS:
        value = values.get(key, "")
        if value and value.lower() not in _PLACEHOLDER_VALUES:
            found.append((source, value))
    return found


__all__ = [
    "APP_DIR_NAME",
    "DEVICE_FILENAME",
    "DEVICE_FILE_ENV",
    "HARDWARE_PROBE_COMMAND",
    "HARDWARE_PROBE_TIMEOUT_SECONDS",
    "DeviceIdentityError",
    "collect_fingerprint",
    "device_file_path",
    "load_device_id",
    "save_device_id",
]
