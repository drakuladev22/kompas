"""AES-256-GCM şifrələmə və master açar idarəetməsi (spesifikasiya bölmə 2).

QAYDA (spesifikasiyadan):
    "Fernet master key heç vaxt DB-də və ya config faylında plaintext
    saxlanılmır. Açar env variable və ya OS-səviyyəli credential store
    (Windows DPAPI) vasitəsilə təchiz olunur, key-rotation prosedur
    sənədləşdirilir."

TƏHLÜKƏSİZLİK QƏRARI (SEC-002, bax `docs/security_decisions.md`):
    Spesifikasiya "Fernet AES-256" tələb edir. Fernet faktiki olaraq
    AES-128-CBC + HMAC-SHA256 istifadə edir (256-bit açar materialını ikiyə
    bölür) — yəni hərfi mənada AES-256 DEYİL. Audit/müqavilə uyğunluğu üçün
    əsas şifrə **AES-256-GCM**-ə keçirildi:

        * 256-bit açar tam şəkildə AES-256 üçün istifadə olunur;
        * GCM autentifikasiyalı şifrələmədir (AEAD) — bütövlük şifrənin
          özündə təmin olunur, ayrıca HMAC lazım deyil;
        * `associated_data` (AAD) dəstəyi ilə şifrələnmiş dəyəri öz
          KONTEKSTİNƏ bağlamaq mümkündür — məs. 1C server şifrəsi konkret
          `server_id`-yə bağlanır, beləliklə bir sətrin şifrəli dəyərini
          başqa sətrə köçürmək (cut-and-paste hücumu) mümkün olmur.

    Köhnə Fernet token-ləri **oxunmağa davam edir** (geriyə uyğunluq), lakin
    yeni yazılar həmişə AES-256-GCM ilə gedir. `rotate_token()` köhnə
    Fernet token-ini yeni sxemə köçürür.

TOKEN FORMATI:
    v1.<key_id>.<base64url(nonce(12) || ciphertext || tag(16))>

    `key_id` — açarın SHA-256 daycestinin ilk 8 hex simvolu. Rotasiya zamanı
    hansı açarla açılacağını **sınaqsız** müəyyən etməyə imkan verir və
    açarın özü haqqında heç bir məlumat sızdırmır.

NONCE: hər şifrələmədə 96-bit kriptoqrafik təsadüfi nonce (`os.urandom`).
    GCM-də nonce təkrarı fəlakətlidir; təsadüfi 96-bit nonce ilə eyni açar
    altında ~2^32 mesaja qədər təhlükəsizdir — bu sistemin həcmindən qat-qat
    yüksəkdir. Rotasiya siyasəti (ildə 1 dəfə) əlavə ehtiyat qatıdır.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.shared.data_paths import shared_root
from src.shared.exceptions import DecryptionError, EncryptionKeyError
from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

ENV_PRIMARY_KEY: Final[str] = "KOMPASOS_FERNET_KEY"
ENV_PREVIOUS_KEYS: Final[str] = "KOMPASOS_FERNET_KEY_PREVIOUS"
DPAPI_BLOB_ENV: Final[str] = "KOMPASOS_DPAPI_KEY_PATH"
DEFAULT_DPAPI_FILENAME: Final[str] = "kompasos.key"

TOKEN_VERSION: Final[str] = "v1"  # noqa: S105 - versiya markeri, şifrə deyil
NONCE_SIZE: Final[int] = 12  # 96 bit — GCM üçün tövsiyə olunan ölçü
KEY_SIZE: Final[int] = 32  # 256 bit — AES-256
KEY_ID_LENGTH: Final[int] = 8

#: Token `v1.<key_id>.<payload>` — nöqtə ilə ayrılmış 3 hissə.
TOKEN_PART_COUNT: Final[int] = 3
#: Fernet token-inin minimum uzunluğu (versiya + timestamp + IV + HMAC).
MIN_FERNET_TOKEN_LENGTH: Final[int] = 40
#: Fernet token-inin ilk baytı — format markeri.
FERNET_VERSION_BYTE: Final[int] = 0x80


def generate_key() -> str:
    """Yeni 256-bit açar yaradır (base64url, 44 simvol).

    Format Fernet ilə eynidir ki, mövcud quraşdırmalardakı açarlar dəyişmədən
    AES-256-GCM üçün də istifadə oluna bilsin.

    İstifadə::

        python -c "from src.infrastructure.security.encryption \
import generate_key; print(generate_key())"
    """
    return base64.urlsafe_b64encode(os.urandom(KEY_SIZE)).decode("ascii")


def _key_id(raw_key: bytes) -> str:
    """Açarın açıq identifikatoru — açarın özündən heç nə sızdırmır."""
    return hashlib.sha256(b"kompasos-key-id\x00" + raw_key).hexdigest()[:KEY_ID_LENGTH]


def _b64decode_key(key: str) -> bytes:
    raw = base64.urlsafe_b64decode(key.strip().encode("ascii"))
    if len(raw) != KEY_SIZE:
        raise ValueError(f"Açar {KEY_SIZE} bayt olmalıdır, alındı: {len(raw)} bayt")
    return raw


# --------------------------------------------------------------------------- #
# Açar provayderləri
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class KeyMaterial:
    """Cari + köhnə açarlar (rotasiya üçün).

    `__repr__` qəsdən maskalanıb ki, açar heç bir log/traceback/pytest
    diff-inə düşməsin.
    """

    primary: str
    previous: tuple[str, ...] = ()
    source: str = "unknown"

    def as_list(self) -> list[str]:
        return [self.primary, *self.previous]

    def __repr__(self) -> str:  # pragma: no cover - sadə maskalama
        return (
            f"KeyMaterial(primary=***REDACTED***, "
            f"previous_count={len(self.previous)}, source={self.source!r})"
        )

    __str__ = __repr__


@runtime_checkable
class KeyProvider(Protocol):
    """Master açarı təchiz edən port."""

    name: str

    def load(self) -> KeyMaterial | None:
        """Açarı qaytarır, tapılmadıqda `None`."""
        ...


class EnvironmentKeyProvider:
    """Mühit dəyişənlərindən açar oxuyur (CI/CD və server mühiti üçün)."""

    name = "environment"

    def __init__(
        self,
        *,
        primary_var: str = ENV_PRIMARY_KEY,
        previous_var: str = ENV_PREVIOUS_KEYS,
    ) -> None:
        self._primary_var = primary_var
        self._previous_var = previous_var

    def load(self) -> KeyMaterial | None:
        primary = os.environ.get(self._primary_var, "").strip()
        if not primary:
            return None

        raw_previous = os.environ.get(self._previous_var, "").strip()
        previous = tuple(item.strip() for item in raw_previous.split(",") if item.strip())
        return KeyMaterial(primary=primary, previous=previous, source=self.name)


class WindowsDpapiKeyProvider:
    """Windows DPAPI ilə qorunan lokal açar blobu.

    DPAPI açarı cari Windows istifadəçi hesabına bağlayır — blob faylı
    oğurlansa belə başqa maşında/istifadəçidə açılmır. Mağaza kiosk PC-ləri
    üçün nəzərdə tutulan yoldur.

    Windows-dan kənar platformalarda `load()` sadəcə `None` qaytarır
    (CI-da Linux runner-lərdə bu provayder passiv qalır).
    """

    name = "windows_dpapi"

    def __init__(self, blob_path: Path | None = None, *, machine_scope: bool = False) -> None:
        """
        Args:
            machine_scope: `True` → blob MAŞINA bağlanır (`CRYPTPROTECT_
                LOCAL_MACHINE`), yəni həmin kompüterin HƏR istifadəçisi onu
                aça bilir.

                NİYƏ LAZIMDIR: mağaza PC-si PAYLAŞILAN cihazdır və kiosk
                nəzarətçisi başqa hesabla işləyə bilər. İstifadəçi-əhatəli
                blob o halda ikinci hesabda AÇILMIR — proqram «açar yoxdur»
                deyib bağlantı konfiqurasiyasını itirmiş kimi davranardı.

                NİYƏ DEFOLT DEYİL: maşın əhatəsi qorumanı ZƏİFLƏDİR — həmin
                kompüterdə kod icra edə bilən hər kəs blobu aça bilir.
                Fərdi istifadəçi məlumatı (şifrələmə açarı) üçün istifadəçi
                əhatəsi doğru qərardır; yalnız PAYLAŞILAN konfiqurasiya
                (bağlantı parolu) maşın əhatəsinə keçir.
        """
        self._machine_scope = machine_scope
        self._blob_path = blob_path or self._default_path(machine_scope)

    @staticmethod
    def _default_path(machine_scope: bool = False) -> Path:
        """Blob faylının yeri — açarın ƏHATƏSİ ilə uyğun olmalıdır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ MAŞIN ƏHATƏSİ `%PROGRAMDATA%`-ya KEÇDİ
        ──────────────────────────────────────────────────────────────────────
        `connection.json` MAŞIN əhatəli açarla şifrələnir, çünki paylaşılan
        mağaza PC-sində ikinci Windows hesabı da onu AÇA BİLMƏLİDİR. Lakin
        blob FAYLI istifadəçinin `%LOCALAPPDATA%`-sında qalırdı — yəni ikinci
        hesab paylaşılan konfiqurasiyanı oxuyur, açarı isə TAPMIRDI və
        «Saxlanmış parol açıla bilmədi — açar bu kompüterdə dəyişib» xətası
        alırdı. DPAPI-nin əhatəsi düz idi, faylın yeri səhv.

        İstifadəçi əhatəli açar (defolt) `%LOCALAPPDATA%`-da QALIR: onu
        paylaşılan qovluğa qoymaq başqa hesabın faylı görməsinə səbəb olardı
        — halbuki həmin açarın bütün mənası əksidir.

        KÖHNƏ BLOB KÖÇÜRÜLMÜR, TANINIR: mövcud quraşdırmada fayl hələ köhnə
        yerdədir və onunla şifrələnmiş HƏR ŞEY (bağlantı parolu, ERP
        tokenləri) ona bağlıdır. Köçürmə yarımçıq qalsaydı, açar itər və
        məlumat bərpa edilməz olardı — `data_paths` modulundakı eyni qərar.
        """
        override = os.environ.get(DPAPI_BLOB_ENV)
        if override:
            return Path(override)
        user_scoped = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
            / "KompasOS"
            / DEFAULT_DPAPI_FILENAME
        )
        if not machine_scope:
            return user_scoped
        if user_scoped.is_file():
            return user_scoped
        return shared_root() / DEFAULT_DPAPI_FILENAME

    @property
    def blob_path(self) -> Path:
        return self._blob_path

    @property
    def _flags(self) -> int:
        """`CRYPTPROTECT_UI_FORBIDDEN` (+ istəyə görə `LOCAL_MACHINE`).

        Deşifrələmədə də EYNİ bayraq verilir: `CryptUnprotectData` maşın
        blobunu bayraqsız da açır, lakin ikisini fərqli yazsaq oxucu hansı
        əhatənin qüvvədə olduğunu koddan çıxara bilməzdi.
        """
        return 0x1 | (0x4 if self._machine_scope else 0)

    @property
    def is_supported(self) -> bool:
        return sys.platform == "win32"

    # ------------------------------ DPAPI ---------------------------------- #

    @staticmethod
    def _dpapi_call(  # pragma: no cover - OS API
        data: bytes, *, protect: bool, flags: int = 0x1
    ) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):  # noqa: N801 - Win32 adı
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        buffer_in = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buffer_in, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()

        function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1 — kiosk rejimində heç bir dialoq açılmasın.
        # CRYPTPROTECT_LOCAL_MACHINE = 0x4 — blob maşına bağlanır (bax `__init__`).
        if protect:
            ok = function(
                ctypes.byref(blob_in),
                "KompasOS",
                None,
                None,
                None,
                flags,
                ctypes.byref(blob_out),
            )
        else:
            ok = function(
                ctypes.byref(blob_in),
                None,
                None,
                None,
                None,
                flags,
                ctypes.byref(blob_out),
            )

        if not ok:
            raise EncryptionKeyError(
                f"DPAPI əməliyyatı uğursuz oldu (protect={protect}), "
                f"Win32 xəta kodu: {ctypes.GetLastError()}"
            )

        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

    # ------------------------------ API ------------------------------------ #

    def load(self) -> KeyMaterial | None:
        if not self.is_supported or not self._blob_path.exists():
            return None
        try:
            protected = self._blob_path.read_bytes()
            plaintext = self._dpapi_call(protected, protect=False, flags=self._flags)
            payload: dict[str, Any] = json.loads(plaintext.decode("utf-8"))
        except EncryptionKeyError:
            raise
        except Exception as exc:
            raise EncryptionKeyError(
                f"DPAPI açar blobu oxuna bilmədi: {self._blob_path}",
                context={"path": str(self._blob_path)},
            ) from exc

        primary = str(payload.get("primary", "")).strip()
        if not primary:
            return None
        previous = tuple(str(item) for item in payload.get("previous", []) if item)
        return KeyMaterial(primary=primary, previous=previous, source=self.name)

    def store(self, material: KeyMaterial) -> Path:
        """Açarı DPAPI ilə şifrələyib diskə yazır (ilk quraşdırma/rotasiya).

        Fayl heç vaxt plaintext saxlamır — yalnız DPAPI blobu.
        """
        if not self.is_supported:
            raise EncryptionKeyError(
                "DPAPI yalnız Windows platformasında dəstəklənir",
                context={"platform": sys.platform},
            )
        payload = json.dumps(
            {"primary": material.primary, "previous": list(material.previous)}
        ).encode("utf-8")
        protected = self._dpapi_call(payload, protect=True, flags=self._flags)

        self._blob_path.parent.mkdir(parents=True, exist_ok=True)
        self._blob_path.write_bytes(protected)
        # Faylı yalnız cari istifadəçiyə oxunan et (Windows-da DPAPI onsuz da
        # qoruyur, lakin defense-in-depth). Windows-da chmod məhdud işlədiyi
        # üçün uğursuzluq gözləniləndir və əməliyyatı dayandırmamalıdır.
        with contextlib.suppress(OSError):
            self._blob_path.chmod(0o600)

        _security_log.info(
            "DPAPI_KEY_STORED",
            extra={
                "path": str(self._blob_path),
                "previous_count": len(material.previous),
            },
        )
        return self._blob_path


def ensure_machine_key(provider: WindowsDpapiKeyProvider | None = None) -> bool:
    """Maşın-əhatəli DPAPI açarı YOXDURSA yaradır. Nəticə: yaradıldımı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ LAZIMDIR — SETUP-2
    ──────────────────────────────────────────────────────────────────────────
    Təmiz quraşdırmada NƏ `KOMPASOS_FERNET_KEY` var (paketə `.env` düşmür),
    NƏ də DPAPI blobu (onu heç kim yaratmırdı). Nəticədə «Bağlantı Ayarları»
    ekranından yadda saxlamaq `EncryptionKeyError` ilə dayanırdı — yəni
    müştəri maşınında proqram HEÇ VAXT konfiqurasiya edilə bilmirdi.

    `docs/key_rotation.md` blobu ƏL İLƏ yaratmağı təsvir edirdi (Python
    snippet). Paketlənmiş `.exe`-də isə Python konsolu yoxdur — sənəddəki
    yol quraşdırıcı üçün icra edilə bilməz.

    ──────────────────────────────────────────────────────────────────────────
    YALNIZ YAZI YOLUNDA ÇAĞIRILIR, OXUDA YOX
    ──────────────────────────────────────────────────────────────────────────
    Oxuma zamanı açar yaratmaq ƏN TƏHLÜKƏLİ variantdır: blob itibsə (disk
    dəyişdi, profil köçürüldü) yeni açar köhnə şifrəli dəyəri OXUNMAZ edər,
    lakin xəta VERMƏZDİ — istifadəçi «parol səhvdir» əvəzinə səssiz uğursuzluq
    görərdi. Ona görə oxu yolu olduğu kimi qalır: açar tapılmasa
    `load()` `None` qaytarır və ekran «parolu yenidən daxil edin» deyir.

    ──────────────────────────────────────────────────────────────────────────
    MÜHİT AÇARI ÜSTÜNDÜR
    ──────────────────────────────────────────────────────────────────────────
    `KOMPASOS_FERNET_KEY` təyin edilibsə blob YARADILMIR: inkişaf maşınında
    və CI-da açar mənbəyi ODUR, ikinci mənbə yaratmaq «hansı açarla
    şifrələnib?» sualını doğurardı.
    """
    if EnvironmentKeyProvider().load() is not None:
        return False
    target = provider or WindowsDpapiKeyProvider(machine_scope=True)
    if not target.is_supported or target.load() is not None:
        return False
    target.store(KeyMaterial(primary=generate_key(), source="dpapi-provisioned"))
    _log.warning(
        "ENCRYPTION_KEY_PROVISIONED",
        extra={"path": str(target.blob_path), "scope": "machine"},
    )
    return True


class ChainedKeyProvider:
    """Provayderləri sıra ilə yoxlayır, ilk uğurlu nəticəni qaytarır."""

    name = "chained"

    def __init__(self, providers: list[KeyProvider]) -> None:
        if not providers:
            raise ValueError("Ən azı bir KeyProvider verilməlidir")
        self._providers = providers

    def load(self) -> KeyMaterial | None:
        for provider in self._providers:
            material = provider.load()
            if material is not None:
                _log.debug("KEY_PROVIDER_HIT", extra={"provider": provider.name})
                return material
        return None


def default_key_provider() -> ChainedKeyProvider:
    """Standart zəncir: env → Windows DPAPI."""
    return ChainedKeyProvider([EnvironmentKeyProvider(), WindowsDpapiKeyProvider()])


# --------------------------------------------------------------------------- #
# Şifrələmə servisi
# --------------------------------------------------------------------------- #


class EncryptionService:
    """DB-də saxlanılan həssas dəyərləri (1C server şifrələri, TOTP sirləri)
    AES-256-GCM ilə şifrələyən/açan servis.

    Nümunə::

        service = EncryptionService()
        token = service.encrypt("1c-server-parolu", context=f"erp_server:{server_id}")
        plain = service.decrypt(token, context=f"erp_server:{server_id}")

    `context` (AAD) verilibsə, açarkən EYNİ kontekst verilməlidir — əks halda
    `DecryptionError`. Bu, şifrəli dəyəri başqa sətrə köçürmə hücumunu bağlayır.
    """

    def __init__(self, key_provider: KeyProvider | None = None) -> None:
        self._key_provider = key_provider or default_key_provider()
        self._ciphers: dict[str, AESGCM] = {}
        self._legacy_fernets: list[Fernet] = []
        self._primary_key_id: str | None = None
        self._material: KeyMaterial | None = None
        self._lock = threading.Lock()

    # ----------------------------- açar ------------------------------------ #

    def _is_loaded(self) -> bool:
        """Açarlar yüklənibmi. Metod kimi ayrılıb ki, double-checked locking
        naxışında tip-daraltma (narrowing) ikinci yoxlamanı "əlçatmaz" saymasın."""
        return self._primary_key_id is not None

    def _ensure_loaded(self) -> None:
        if self._is_loaded():
            return
        with self._lock:
            # Başqa thread bu arada yükləmiş ola bilər.
            if self._is_loaded():
                return

            material = self._key_provider.load()
            if material is None:
                raise EncryptionKeyError(
                    f"Master şifrələmə açarı tapılmadı. `{ENV_PRIMARY_KEY}` mühit "
                    f"dəyişənini təyin edin və ya Windows DPAPI blobunu quraşdırın.",
                    context={"provider": getattr(self._key_provider, "name", "?")},
                )

            ciphers: dict[str, AESGCM] = {}
            legacy: list[Fernet] = []
            primary_id: str | None = None

            for index, key in enumerate(material.as_list()):
                try:
                    raw = _b64decode_key(key)
                except Exception as exc:
                    raise EncryptionKeyError(
                        "Master açar yararsız formatdadır (32 baytlıq base64url gözlənilir)",
                        context={"source": material.source, "key_index": index},
                    ) from exc

                identifier = _key_id(raw)
                ciphers[identifier] = AESGCM(raw)
                # Eyni açar köhnə Fernet token-lərini oxumaq üçün də saxlanılır.
                legacy.append(Fernet(key.strip().encode("ascii")))
                if index == 0:
                    primary_id = identifier

            self._ciphers = ciphers
            self._legacy_fernets = legacy
            self._primary_key_id = primary_id
            self._material = material

            _security_log.info(
                "ENCRYPTION_KEY_LOADED",
                extra={
                    "source": material.source,
                    "algorithm": "AES-256-GCM",
                    "primary_key_id": primary_id,
                    "rotation_keys": len(material.previous),
                },
            )

    @property
    def is_configured(self) -> bool:
        """Açar mövcuddursa `True` — startup health-check üçün."""
        try:
            self._ensure_loaded()
        except EncryptionKeyError:
            return False
        return True

    @property
    def key_source(self) -> str | None:
        """Açarın hansı provayderdən gəldiyi (açarın özü YOX)."""
        self._ensure_loaded()
        return self._material.source if self._material else None

    @property
    def primary_key_id(self) -> str | None:
        """Cari açarın açıq identifikatoru — audit/diaqnostika üçün."""
        self._ensure_loaded()
        return self._primary_key_id

    def reload(self) -> None:
        """Açarı yenidən yükləyir (rotasiyadan sonra restart-sız tətbiq üçün)."""
        with self._lock:
            self._ciphers = {}
            self._legacy_fernets = []
            self._primary_key_id = None
            self._material = None
        self._ensure_loaded()

    # --------------------------- şifrələmə --------------------------------- #

    @staticmethod
    def _aad(key_id: str, context: str | None) -> bytes:
        """Header-i (və istəyə görə kontekst) AAD kimi bağlayır."""
        base = f"{TOKEN_VERSION}.{key_id}".encode()
        if context:
            return base + b"|" + context.encode("utf-8")
        return base

    def _seal(self, data: bytes, context: str | None) -> tuple[str, bytes]:
        """AES-256-GCM-lə bağlayır — MƏTN və BAYT şifrələməsinin ORTAQ NÜVƏSİ.

        `encrypt()` və `encrypt_bytes()` İKİSİ DƏ buradan keçir: açar seçimi,
        nonce yaradılması və AAD bağlanması TƏK yerdə qalır. Yalnız ZƏRFİN
        formatı fərqlənir (mətn üçün base64 sətir, bayt üçün xam bayt) —
        aşağıdakı iki metodda. Əks halda kripto nüvəsi iki yerdə təkrarlanardı
        və birinin düzəlişi (məs. AAD sxemi dəyişəndə) digərində unudulardı.

        Returns:
            `(key_id, nonce + sealed)` — zərfə salmaq çağıranın işidir.
        """
        self._ensure_loaded()
        assert self._primary_key_id is not None
        key_id = self._primary_key_id
        nonce = os.urandom(NONCE_SIZE)
        cipher = self._ciphers[key_id]
        sealed = cipher.encrypt(nonce, data, self._aad(key_id, context))
        return key_id, nonce + sealed

    def _open(self, key_id: str, nonce_and_sealed: bytes, context: str | None) -> bytes:
        """AES-256-GCM-i açır — MƏTN və BAYT deşifrəsinin ORTAQ NÜVƏSİ (bax `_seal`)."""
        self._ensure_loaded()
        cipher = self._ciphers.get(key_id)
        if cipher is None:
            _security_log.error("DECRYPTION_UNKNOWN_KEY_ID", extra={"key_id": key_id})
            raise DecryptionError(
                f"Bu məlumat naməlum açarla ('{key_id}') şifrələnib. "
                f"Köhnə açarı KOMPASOS_FERNET_KEY_PREVIOUS-a əlavə edin.",
                context={"key_id": key_id},
            )

        nonce, sealed = nonce_and_sealed[:NONCE_SIZE], nonce_and_sealed[NONCE_SIZE:]
        try:
            return cipher.decrypt(nonce, sealed, self._aad(key_id, context))
        except InvalidTag as exc:
            _security_log.warning(
                "DECRYPTION_FAILED",
                extra={"reason": "invalid_tag_or_context", "key_id": key_id},
            )
            raise DecryptionError(
                "Şifrələnmiş dəyər açıla bilmədi — məlumat dəyişdirilib və ya "
                "yanlış kontekst verilib"
            ) from exc
        except Exception as exc:
            raise DecryptionError("Şifrələnmiş dəyər açıla bilmədi") from exc

    def encrypt(self, plaintext: str | bytes, *, context: str | None = None) -> str:
        """Mətni AES-256-GCM ilə şifrələyir və versiyalı token qaytarır.

        Args:
            plaintext: Şifrələnəcək dəyər.
            context: İstəyə bağlı AAD — dəyəri öz sətrinə/obyektinə bağlayır
                (məs. ``f"erp_server:{server_id}"``). Açarkən eyni dəyər
                verilməlidir.
        """
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        key_id, body = self._seal(data, context)
        payload = base64.urlsafe_b64encode(body).decode("ascii")
        return f"{TOKEN_VERSION}.{key_id}.{payload}"

    def decrypt(self, token: str | bytes, *, context: str | None = None) -> str:
        """Token-i açır — həm AES-256-GCM, həm də köhnə Fernet formatını dəstəkləyir."""
        self._ensure_loaded()
        text = token.decode("ascii") if isinstance(token, bytes) else token

        if text.startswith(f"{TOKEN_VERSION}."):
            return self._decrypt_aesgcm(text, context)
        return self._decrypt_legacy_fernet(text)

    def _decrypt_aesgcm(self, token: str, context: str | None) -> str:
        try:
            _, key_id, payload = token.split(".", 2)
        except ValueError as exc:
            raise DecryptionError("Şifrələnmiş dəyərin formatı yararsızdır") from exc

        try:
            raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        except Exception as exc:
            raise DecryptionError("Şifrələnmiş dəyər açıla bilmədi") from exc

        # `_open()` `.decode("utf-8")` ETMİR (bayt API-si ilə ORTAQ olduğu üçün) —
        # mətn sərhədi MƏHZ BURADADIR, ən xarici mətn səthində.
        return self._open(key_id, raw, context).decode("utf-8")

    def _decrypt_legacy_fernet(self, token: str) -> str:
        """Köhnə (AES-256-GCM-ə keçiddən əvvəlki) Fernet token-lərini oxuyur."""
        for fernet in self._legacy_fernets:
            try:
                value = fernet.decrypt(token.encode("ascii")).decode("utf-8")
            except InvalidToken:
                continue
            _log.info("LEGACY_FERNET_TOKEN_READ", extra={"action": "rotasiya tövsiyə olunur"})
            return value

        _security_log.warning("DECRYPTION_FAILED", extra={"reason": "invalid_token"})
        raise DecryptionError(
            "Şifrələnmiş dəyər açıla bilmədi — açar uyğun gəlmir və ya məlumat korlanıb"
        )

    # ------------------------------ bayt API --------------------------------- #
    #
    # NİYƏ AYRICA API LAZIM OLDU (SEC-4, dövrə 2 audit tapıntısı):
    # yuxarıdakı `encrypt()`/`decrypt()` MƏTN üçündür — `decrypt()` `_open()`-un
    # nəticəsini `.decode("utf-8")` edir. Binar bayt axını (sübut şəkli, PDF)
    # demək olar HEÇ VAXT keçərli UTF-8 olmur → şəkil üçün `decrypt()`
    # `UnicodeDecodeError` ilə ÇÖKƏRDİ. Üstəlik `encrypt()` nəticəni base64
    # sətrə çevirir — bu, ~33% şişmədir (3 bayt → 4 simvol). `upload_queue.py`
    # modulunun ÖZÜ məhz bu səbəbdən sübut şəkillərini SQLite/JSON sütununa
    # YOX, ayrıca fayla yazmağı seçib (bax orada modul başlığı) — eyni
    # məntiqlə, o faylı şifrələyəndə DƏ base64 əlavə etmək məqsədsizdir.
    #
    # NİYƏ BASE64 YOXDUR: `encrypt_bytes()` xam bayt qaytarır — çağıran onu
    # BİRBAŞA diskə yaza bilər. Zərf `TOKEN_VERSION.key_id.` ASCII başlığı +
    # xam `nonce || şifrmətn || tag`-dır (mətn tokeninin eyni sxemi, YALNIZ
    # son hissə base64-lənmir).
    #
    # NİYƏ MƏTN API-Sİ ÜSTÜNDƏ QURULUB (`_seal`/`_open`): kripto nüvəsi
    # (açar seçimi, nonce, AAD bağlanması) TƏK yerdədir — iki ayrı şifrələmə
    # yolu olsaydı, AAD sxemi dəyişəndə (məs. INFRA-2 tapıntısındakı AAD
    # mənbəyi uyğunsuzluğu kimi) yalnız biri düzəlib digəri unudula bilərdi.
    #
    # YADDAŞ SƏRHƏDİ (gələcək üçün sənədləşdirilir): `AESGCM` AXIN (streaming)
    # rejimi TƏKLİF ETMİR — bütün `data` YADDAŞDA bütöv şifrələnir/açılır.
    # 10 MB şəkil üçün zirvə yaddaş sərfi ~3× (orijinal + şifrəli surət +
    # köçürmə buferi) qədər ola bilər. Bu, mövcud sübut şəkli həddi ilə
    # (`MAX_UPLOAD_BYTES`/`system_limits`, bir neçə MB) TƏHLÜKƏSİZDİR, lakin
    # bu API-ni video və ya böyük arxiv üçün İSTİFADƏ ETMƏYİN — yüzlərlə
    # meqabaytlıq fayl üçün axın-əsaslı şifrələmə (məs. bloklara bölünmüş
    # AES-GCM) tələb olunur, bu sinif onu təmin ETMİR.

    def encrypt_bytes(self, data: bytes, *, context: str | None = None) -> bytes:
        """Xam bayt axınını (şəkil, sənəd) AES-256-GCM ilə şifrələyir.

        `encrypt()`-dən fərqli olaraq NƏTİCƏ BASE64-LƏNMİR — çağıran onu
        birbaşa fayla/BLOB sütununa yaza bilər. `context` mətn API-si ilə
        EYNİ semantikadadır: verilibsə, `decrypt_bytes()`-ə EYNİ dəyər
        ötürülməlidir, əks halda `DecryptionError`.
        """
        key_id, body = self._seal(data, context)
        return f"{TOKEN_VERSION}.{key_id}.".encode("ascii") + body

    def decrypt_bytes(self, blob: bytes, *, context: str | None = None) -> bytes:
        """`encrypt_bytes()` nəticəsini açır — nəticə XAM BAYTDIR, mətn DEYİL."""
        self._ensure_loaded()
        try:
            prefix, key_id_bytes, body = blob.split(b".", 2)
        except ValueError as exc:
            raise DecryptionError("Şifrələnmiş dəyərin formatı yararsızdır") from exc
        if prefix != TOKEN_VERSION.encode("ascii"):
            raise DecryptionError("Şifrələnmiş dəyərin formatı yararsızdır")
        return self._open(key_id_bytes.decode("ascii"), body, context)

    # ------------------------------ JSON ----------------------------------- #

    def encrypt_json(self, payload: dict[str, Any], *, context: str | None = None) -> str:
        """Lüğəti JSON-a çevirib şifrələyir (məs. bütöv server konfiqurasiyası)."""
        return self.encrypt(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), context=context
        )

    def decrypt_json(self, token: str, *, context: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.decrypt(token, context=context))
        return result

    # ---------------------------- rotasiya ---------------------------------- #

    def rotate_token(self, token: str, *, context: str | None = None) -> str:
        """Token-i CARİ açar və CARİ sxem (AES-256-GCM) ilə yenidən şifrələyir.

        Köhnə Fernet token-lərini də AES-256-GCM-ə köçürür — miqrasiya üçün
        ayrıca kod lazım deyil.
        """
        plaintext = self.decrypt(token, context=context)
        return self.encrypt(plaintext, context=context)

    def needs_rotation(self, token: str) -> bool:
        """Token köhnə açarla və ya köhnə sxemlə şifrələnibsə `True`.

        Toplu miqrasiya skripti bu metodla lazımsız yazmalardan qaçır.
        """
        self._ensure_loaded()
        if not token.startswith(f"{TOKEN_VERSION}."):
            return True  # köhnə Fernet formatı
        parts = token.split(".", 2)
        return len(parts) != TOKEN_PART_COUNT or parts[1] != self._primary_key_id

    # ----------------------------- köməkçi ---------------------------------- #

    @staticmethod
    def is_token(value: str) -> bool:
        """Dəyərin şifrələnmiş token olub-olmadığını yoxlayır (migrasiya üçün)."""
        if not isinstance(value, str) or not value:
            return False
        if value.startswith(f"{TOKEN_VERSION}."):
            parts = value.split(".", 2)
            return (
                len(parts) == TOKEN_PART_COUNT and len(parts[1]) == KEY_ID_LENGTH and bool(parts[2])
            )
        # Köhnə Fernet token-i: base64, ilk bayt versiya markeridir
        if len(value) < MIN_FERNET_TOKEN_LENGTH:
            return False
        try:
            decoded = base64.urlsafe_b64decode(value.encode("ascii"))
        except Exception:
            return False
        return len(decoded) > 0 and decoded[0] == FERNET_VERSION_BYTE
