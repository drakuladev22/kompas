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
FINGERPRINT WMI İLƏ OXUNUR VƏ NASAZLIQ DAYANDIRICI DEYİL
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

#: WMI sorğularının taymautu. Sabit ədəddir və ROOT PARAMETRİ DEYİL: bu,
#: tətbiqin AÇILIŞ yolundadır — Root dəyəri oxumaq üçün baza lazımdır, baza
#: isə hələ açılmayıb. Dövri asılılıq yaranardı.
WMI_TIMEOUT_SECONDS: Final[float] = 5.0

#: Aparat göstəricilərini verən əmrlər. Siyahı SABİTdir və istifadəçi mətni
#: QƏBUL ETMİR — `subprocess` çağırışı `shell=False` ilə, arqumentlər isə
#: massiv kimi ötürülür, yəni inyeksiya səthi yoxdur.
_WMI_QUERIES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("baseboard", ("wmic", "baseboard", "get", "serialnumber")),
    ("diskdrive", ("wmic", "diskdrive", "get", "serialnumber")),
    ("csproduct", ("wmic", "csproduct", "get", "uuid")),
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
        # WMI yalnız Windows-dadır. Linux/macOS-da (CI, developer maşını)
        # boş qayıdırıq və çağıran tərəf zəif fingerprint-ə düşür — bu, test
        # mühitində gözlənilən davranışdır, qüsur deyil.
        return []

    found: list[tuple[str, str]] = []
    for source, command in _WMI_QUERIES:
        value = _run_wmi(command)
        if value:
            found.append((source, value))
    return found


def _run_wmi(command: tuple[str, ...]) -> str:
    """Bir WMI sorğusu; nasazlıqda boş sətir.

    Hər nasazlıq udulur və YALNIZ debug jurnalına düşür: `wmic` Windows 11-də
    köhnəlmiş sayılır və bəzi quraşdırmalarda ümumiyyətlə yoxdur. Bunu
    xəbərdarlıq kimi yazsaydıq, hər açılışda üç xəbərdarlıq görünərdi və
    həqiqi problemləri gizlədərdi.
    """
    try:
        result = subprocess.run(  # noqa: S603 — əmr SABİT massivdir, `shell=False`
            command,
            capture_output=True,
            text=True,
            timeout=WMI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log.debug("WMI_QUERY_FAILED", extra={"command": command[1], "error": str(exc)})
        return ""

    if result.returncode != 0:
        return ""
    # Birinci sətir sütun başlığıdır (`SerialNumber`), qalanı dəyərlərdir.
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    values = [line for line in lines[1:] if line.lower() not in {"", "to be filled by o.e.m."}]
    return values[0] if values else ""


__all__ = [
    "APP_DIR_NAME",
    "DEVICE_FILENAME",
    "DEVICE_FILE_ENV",
    "WMI_TIMEOUT_SECONDS",
    "DeviceIdentityError",
    "collect_fingerprint",
    "device_file_path",
    "load_device_id",
    "save_device_id",
]
