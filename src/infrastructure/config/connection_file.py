"""Bağlantı konfiqurasiyası: `%PROGRAMDATA%\\KompasOS\\connection.json` (DB-4 Faza 2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ FAYL — NİYƏ SİHİRBAZIN SAHƏSİ DEYİL
──────────────────────────────────────────────────────────────────────────────
İlk Quraşdırma Sihirbazı `CEO` hesabını BAZAYA yazır. Yəni sihirbaz işə düşmək
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
OXU ÜÇ YERƏ BAXIR, YAZI İSƏ BİR YERƏ (SETUP-1)
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı qərar YAZI üçün qüvvədə qalır və dəyişmir. OXU isə `.exe`-nin
yanından BAŞLAYIR:

    1. `.exe`-nin yanı             — DƏSTƏK axınının yeri (AnyDesk ilə
       köçürülən fayl); `--onedir` paketində orada 100+ fayl var;
    2. `%PROGRAMDATA%\\KompasOS\\`  — konfiqurasiya ekranının YAZDIĞI yer;
    3. `%APPDATA%\\KompasOS\\`      — qrup siyasəti ProgramData-ya yazmağı
       bağlayan maşınlarda istifadəçi səviyyəli ehtiyat.

Asimmetriya (oxu üç yerdən, yazı bir yerə) qəsdəndir: `Program Files`-a geri
yazmaq standart istifadəçidə icazə xətası verərdi və SETUP-1-in həll etdiyi
problem məhz budur.

Sıra `connection_search_paths()`-dədir; ilk MÖVCUD fayl qalib gəlir və
FAKTİKİ işlədilən yol Bağlantı Ayarları ekranının diaqnostika sətrində
yazılır — iki nüsxə qalsa hansının qüvvədə olduğu gözlə görünür.

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
from typing import Any, Final
from urllib.parse import quote, unquote, urlparse

from src.infrastructure.security.encryption import EncryptionService
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger
from src.shared.runtime import deployment_root

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
    """Faylın YAZILDIĞI yol (mühit dəyişəni ilə əvəzlənə bilər).

    Oxumaqdan FƏRQLİDİR və qəsdən: oxu üç yerə baxır
    (`connection_search_paths`), yazı isə HƏMİŞƏ buraya — paylaşılan,
    yazıla bilən qovluğa — gedir. Yazı da «tapıldığı yerə» getsəydi,
    `.exe`-nin yanından oxunan fayl `Program Files`-a geri yazılmağa
    çalışardı və standart istifadəçidə icazə xətası verərdi.
    """
    override = os.environ.get(CONNECTION_FILE_ENV, "").strip()
    if override:
        return Path(override)
    base = os.environ.get("PROGRAMDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME / CONNECTION_FILENAME


def connection_search_paths() -> list[Path]:
    """Faylın axtarıldığı yerlər — ARDICILLIQLA, ilk tapılan qalib gəlir.

    ──────────────────────────────────────────────────────────────────────────
    SIRA TƏSADÜFİ DEYİL
    ──────────────────────────────────────────────────────────────────────────
        1. `.exe`-nin yanı            — DƏSTƏK AXINININ yeri. Texnik
           konfiqurasiyanı AnyDesk ilə həmin qovluğa köçürür; `--onedir`
           paketində orada onsuz da 100+ fayl var, yəni config gözə dəymir.
           Birinci olmasaydı, köçürülən fayl köhnə `ProgramData` nüsxəsi
           tərəfindən kölgələnər və «düzəltdim, dəyişmədi» vəziyyəti yaranardı.
        2. `%PROGRAMDATA%\\KompasOS\\` — konfiqurasiya EKRANININ yazdığı yer:
           bütün Windows hesabları eyni faylı görür və qovluq yazıla biləndir.
        3. `%APPDATA%\\KompasOS\\`     — istifadəçi səviyyəsində ehtiyat:
           qrup siyasəti ProgramData-ya yazmağı bağlayan maşınlarda proqram
           dayanmır, sadəcə konfiqurasiya həmin istifadəçiyə aid olur.

    Sıranın qarşı riski (köhnə fayl `.exe` yanında qalıb yenisini kölgələyir)
    EKRANDA görünür: Bağlantı Ayarları diaqnostikası FAKTİKİ işlədilən yolu
    yazır (`controllers/connection_settings.diagnostic_paths`).

    Mühit dəyişəni verilibsə axtarış ÜMUMİYYƏTLƏ aparılmır — açıq göstərilən
    yol mübahisəsizdir və testlər/konteyner quraşdırmaları ona arxalanır.
    """
    override = os.environ.get(CONNECTION_FILE_ENV, "").strip()
    if override:
        return [Path(override)]

    candidates = [deployment_root() / CONNECTION_FILENAME, connection_file_path()]
    app_data = os.environ.get("APPDATA", "").strip()
    if app_data:
        candidates.append(Path(app_data) / APP_DIR_NAME / CONNECTION_FILENAME)

    # Təkrarlar atılır, SIRA saxlanılır: `%PROGRAMDATA%` və `%APPDATA%` eyni
    # qovluğa baxan maşınlarda (nadir, lakin mümkün) eyni yol iki dəfə
    # yoxlanardı və diaqnostika mesajı oxunmaz olardı.
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def find_connection_file() -> Path | None:
    """Mövcud olan İLK konfiqurasiya faylı; heç biri yoxdursa `None`."""
    for candidate in connection_search_paths():
        if candidate.is_file():
            return candidate
    return None


def load_settings(path: Path | None = None) -> ConnectionSettings | None:
    """Faylı oxuyur və parolu deşifrələyir; fayl yoxdursa `None`.

    `None` XƏTA DEYİL: konfiqurasiya edilməmiş quraşdırma gözlənilən haldır və
    çağıran tərəf onu Bağlantı Ayarları ekranına yönləndirir (DB-4 Faza 4).

    Raises:
        ConnectionFileError: fayl VAR, lakin oxuna bilmir (korlanıb, parol
            deşifrələnmir). Bu, sükutla «konfiqurasiya yoxdur» kimi
            oxunmamalıdır — səbəb istifadəçiyə deyilməlidir.
    """
    target = path or find_connection_file()
    if target is None or not target.is_file():
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

    return settings_from_payload(payload, source=str(target))


def settings_from_payload(payload: dict[str, Any], *, source: str = "") -> ConnectionSettings:
    """`connection.json` MƏZMUNUNDAN ayarları qurur — fayl OXUMADAN.

    Args:
        payload: Faylın (və ya ona bərabər blokun) məzmunu.
        source: Diaqnostika üçün mənbənin adı — xəta mesajında görünür.

    Raises:
        ConnectionFileError: parol deşifrələnmir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA FUNKSİYA — `load_settings`-DƏN ÇIXARILDI
    ──────────────────────────────────────────────────────────────────────────
    Eyni məzmun artıq İKİ yerdə yaşayır: diskdəki `connection.json` və
    `configs/<slug>.config` arxivinin `connection` BLOKU (`scripts/switch.py`).
    İkincisini oxumaq istəyən tərəfin (`onboard_new_tenant --verify <ad>`)
    yeganə alternativi bloku MÜVƏQQƏTİ FAYLA yazıb `load_settings`-ə vermək
    olardı — yəni ŞİFRƏLƏNMİŞ parolu diskdə üçüncü bir nüsxəyə çıxarmaq və
    onu silməyi unutmaq riskini yaratmaq.

    Deşifrələmə məntiqini ORADA təkrar yazmaq isə daha pisdir: `_CONTEXT`
    (AAD) və açar zənciri dəyişən gün nüsxə sükutla köhnə qalar və xəta
    «parol səhvdir» kimi görünərdi.

    Ona görə oxu İKİYƏ bölündü: HARADAN gəldiyi (`load_settings`) və NƏ
    olduğu (bu funksiya). Davranış DƏYİŞMƏYİB — `load_settings` indi bunu
    çağırır.
    """
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
            context={"path": source, "error": str(exc)},
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
    # AÇAR İLK YAZIDA YARADILIR (SETUP-2). Bu sətir olmasaydı, təmiz
    # quraşdırmada ekran «Yadda saxla» düyməsində `EncryptionKeyError` ilə
    # dayanardı — bax `encryption.ensure_machine_key` başlığı.
    _ensure_key()

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


def _ensure_key() -> None:
    """Maşın-əhatəli DPAPI açarını (yoxdursa) yaradır — YALNIZ yazı yolunda."""
    from src.infrastructure.security.encryption import (  # noqa: PLC0415
        ensure_machine_key,
    )

    ensure_machine_key()


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
    "connection_search_paths",
    "find_connection_file",
    "load_settings",
    "save_settings",
    "settings_from_payload",
]
