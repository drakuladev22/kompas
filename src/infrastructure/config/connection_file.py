"""Bağlantı konfiqurasiyası: `%PROGRAMDATA%\\KompasOS\\connection.json` (DB-4 Faza 2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ FAYL — NİYƏ SİHİRBAZIN SAHƏSİ DEYİL
──────────────────────────────────────────────────────────────────────────────
İlk Quraşdırma Sihirbazı Root hesabını BAZAYA yazır. Yəni sihirbaz işə düşmək
üçün DSN-i ARTIQ bilməlidir — DSN-i onun içində soruşmaq onu özündən əvvəl
işləməyə məcbur edərdi (toyuq-yumurta).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `%PROGRAMDATA%` — NİYƏ `%LOCALAPPDATA%` VƏ YA `.exe`-NİN YANI DEYİL
──────────────────────────────────────────────────────────────────────────────
* `%LOCALAPPDATA%` HƏR İSTİFADƏÇİDƏ AYRIDIR. Mağaza PC-si paylaşılan cihazdır
  və kiosk nəzarətçisi başqa hesabla işləyə bilər — ikinci istifadəçi «baza
  konfiqurasiya edilməyib» görərdi, halbuki konfiqurasiya var.
* `.exe`-nin yanı (`Program Files`) standart istifadəçi üçün YAZILA BİLMİR;
  parol dəyişmək hər dəfə administrator tələb edərdi.
* `%PROGRAMDATA%` isə oxumaq üçün hamıya açıq, yazmaq üçün admin — paylaşılan
  konfiqurasiya üçün düz balans. Layihə onu artıq işlədir
  (`infrastructure/backup/service.py`).

──────────────────────────────────────────────────────────────────────────────
PAROL FAYLDA AÇIQ SAXLANILMIR
──────────────────────────────────────────────────────────────────────────────
Yalnız parol sahəsi şifrələnir (mövcud AES-256-GCM modulu ilə), qalan sahələr
— host, port, baza adı, istifadəçi — AÇIQ qalır. Səbəb praktikidir: quraşdırıcı
faylı gözlə yoxlaya bilməlidir («hansı serverə baxır?»), parol isə orada
görünməməlidir. Hər şeyi şifrələsəydik, diaqnostika üçün faylı deşifrələmək
lazım gələrdi və o vərdiş parolu da ekrana çıxarardı.

Açar DPAPI-nin MAŞIN əhatəsindədir (`machine_scope=True`) — istifadəçi
əhatəsində ikinci hesab faylı aça bilməzdi (bax `security/encryption.py`).

──────────────────────────────────────────────────────────────────────────────
MÜHİT DƏYİŞƏNİ HƏMİŞƏ ÜSTÜNDÜR
──────────────────────────────────────────────────────────────────────────────
`DATABASE_URL` təyin edilibsə fayl OXUNMUR. İnkişaf mühiti, CI və konteyner
quraşdırmaları məhz həmin dəyişənlə işləyir; fayl onları üstələsəydi, testlər
maşındakı təsadüfi konfiqurasiyadan asılı olardı.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import quote, unquote, urlparse

from src.infrastructure.security.encryption import EncryptionService
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

_log = get_logger(__name__)

#: Faylın adı və yolu üçün mühit dəyişəni (test/xüsusi quraşdırma üçün).
CONNECTION_FILE_ENV: Final[str] = "KOMPASOS_CONNECTION_FILE"
CONNECTION_FILENAME: Final[str] = "connection.json"
APP_DIR_NAME: Final[str] = "KompasOS"

#: Fayl formatının versiyası — gələcək dəyişiklikdə köhnə faylı tanımaq üçün.
FORMAT_VERSION: Final[int] = 1


class ConnectionFileError(KompasOSError):
    """Konfiqurasiya faylı oxuna/yazıla bilmədi."""

    user_message = "Baza bağlantısı konfiqurasiyası oxuna bilmədi."


@dataclass(frozen=True)
class ConnectionSettings:
    """`connection.json`-un məzmunu — parol AÇIQ formada burada saxlanılır.

    Bu dataclass YALNIZ yaddaşdadır: diskə yazılarkən parol şifrələnir,
    oxunarkən deşifrələnir. Yəni açıq parol heç vaxt faylda olmur.
    """

    host: str
    port: int
    database: str
    username: str
    password: str
    sslmode: str = "require"

    def dsn(self) -> str:
        """psycopg-nin gözlədiyi DSN.

        İstifadəçi adı və parol URL-kodlanır: Supabase istifadəçi adları
        `postgres.abcdef` formasındadır və parollarda `@`, `/`, `#` kimi
        simvollar normaldır — kodlanmasa DSN səssizcə YANLIŞ hosta işarə edərdi.
        """
        user = quote(self.username, safe="")
        secret = quote(self.password, safe="")
        return (
            f"postgresql://{user}:{secret}@{self.host}:{self.port}/"
            f"{self.database}?sslmode={self.sslmode}"
        )

    @classmethod
    def from_dsn(cls, dsn: str) -> ConnectionSettings:
        """Mövcud DSN-dən sahələri çıxarır — ekranın «mövcud dəyəri göstər» yolu.

        `unquote` MƏCBURİDİR: `urlparse` istifadəçi adı və parolu KODLANMIŞ
        formada qaytarır. Açmasaydıq, ekran parolu `p%40ss` kimi göstərər,
        istifadəçi onu düzgün sanıb «Yadda saxla» basar və dəyər İKİQAT
        kodlanardı — nəticədə bağlantı «parol səhvdir» ilə dayanardı, səbəbi
        isə heç bir ekranda görünməzdi.
        """
        parsed = urlparse(dsn)
        return cls(
            host=parsed.hostname or "",
            port=parsed.port or 5432,
            database=(parsed.path or "/").lstrip("/") or "postgres",
            username=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
        )


def connection_file_path() -> Path:
    """Konfiqurasiya faylının yolu (mühit dəyişəni ilə əvəzlənə bilər)."""
    override = os.environ.get(CONNECTION_FILE_ENV, "").strip()
    if override:
        return Path(override)
    base = os.environ.get("PROGRAMDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME / CONNECTION_FILENAME


def load_settings(path: Path | None = None) -> ConnectionSettings | None:
    """Faylı oxuyur və parolu deşifrələyir; fayl yoxdursa `None`.

    `None` XƏTA DEYİL: konfiqurasiya edilməmiş quraşdırma gözlənilən haldır və
    çağıran tərəf onu Bağlantı Ayarları ekranına yönləndirir (DB-4 Faza 4).

    Raises:
        ConnectionFileError: fayl VAR, lakin oxuna bilmir (korlanıb, parol
            deşifrələnmir). Bu, sükutla «konfiqurasiya yoxdur» kimi
            oxunmamalıdır — səbəb istifadəçiyə deyilməlidir.
    """
    target = path or connection_file_path()
    if not target.is_file():
        return None

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectionFileError(
            "Bağlantı konfiqurasiyası oxuna bilmədi",
            user_message=(
                f"«{target}» faylı oxunmadı və ya korlanıb. Bağlantı ayarlarını yenidən daxil edin."
            ),
            context={"path": str(target), "error": str(exc)},
        ) from exc

    secret = str(payload.get("password_encrypted", ""))
    try:
        password = _decrypt(secret) if secret else ""
    except Exception as exc:
        raise ConnectionFileError(
            "Bağlantı parolu deşifrələnmədi",
            user_message=(
                "Saxlanmış parol açıla bilmədi — açar bu kompüterdə dəyişib. "
                "Parolu yenidən daxil edin."
            ),
            context={"path": str(target), "error": str(exc)},
        ) from exc

    return ConnectionSettings(
        host=str(payload.get("host", "")),
        port=int(payload.get("port", 5432)),
        database=str(payload.get("database", "postgres")),
        username=str(payload.get("username", "")),
        password=password,
        sslmode=str(payload.get("sslmode", "require")),
    )


def save_settings(settings: ConnectionSettings, path: Path | None = None) -> Path:
    """Konfiqurasiyanı ATOMİK yazır; parol şifrələnir.

    Atomiklik səbəbi `installation.json` ilə eynidir: yazı ortasında kəsilən
    proses yarımçıq JSON qoyar və növbəti açılış onu «korlanmış» sayardı.
    """
    target = path or connection_file_path()
    payload = {
        "version": FORMAT_VERSION,
        "host": settings.host,
        "port": settings.port,
        "database": settings.database,
        "username": settings.username,
        # AÇAR ADI QƏSDƏN `password_encrypted`: faylı açan adam dəyərin
        # şifrələnmiş olduğunu ADDAN görməlidir, məzmuna baxmadan.
        "password_encrypted": _encrypt(settings.password) if settings.password else "",
        "sslmode": settings.sslmode,
    }

    temporary = target.with_suffix(f"{target.suffix}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    except OSError as exc:
        raise ConnectionFileError(
            "Bağlantı konfiqurasiyası yazıla bilmədi",
            user_message=(
                f"«{target}» yazıla bilmədi. Qovluğa yazma icazəsi lazımdır — "
                "proqramı administrator kimi işə salın."
            ),
            context={"path": str(target), "error": str(exc)},
        ) from exc

    _log.info("CONNECTION_FILE_SAVED", extra={"path": str(target), "host": settings.host})
    return target


# --------------------------------------------------------------------------- #
# Şifrələmə — mövcud modul üzərindən, YENİSİ YAZILMIR
# --------------------------------------------------------------------------- #


#: Şifrələmə konteksti (AAD): token başqa sahəyə köçürülüb istifadə edilə
#: bilməsin deyə. `erp_server:<id>` naxışı ilə eynidir.
_CONTEXT: Final[str] = "connection_file:password"


def _cipher() -> EncryptionService:
    """MAŞIN əhatəli DPAPI zənciri ilə qurulmuş şifrələmə servisi.

    Zəncir MÜHİT açarını da saxlayır (`EnvironmentKeyProvider`): inkişaf
    maşınında və CI-da DPAPI yoxdur, `KOMPASOS_FERNET_KEY` isə var — həmin
    yollarda modul yenə işləyir.

    Paylaşılan fayl istifadəçi-əhatəli açarla şifrələnsəydi, eyni kompüterin
    ikinci hesabı onu AÇA BİLMƏZDİ (bax modul başlığı).
    """
    from src.infrastructure.security.encryption import (  # noqa: PLC0415
        ChainedKeyProvider,
        EncryptionService,
        EnvironmentKeyProvider,
        WindowsDpapiKeyProvider,
    )

    return EncryptionService(
        ChainedKeyProvider([EnvironmentKeyProvider(), WindowsDpapiKeyProvider(machine_scope=True)])
    )


def _encrypt(value: str) -> str:
    return _cipher().encrypt(value, context=_CONTEXT)


def _decrypt(value: str) -> str:
    return _cipher().decrypt(value, context=_CONTEXT)


__all__ = [
    "CONNECTION_FILENAME",
    "CONNECTION_FILE_ENV",
    "FORMAT_VERSION",
    "ConnectionFileError",
    "ConnectionSettings",
    "connection_file_path",
    "load_settings",
    "save_settings",
]
