"""Buraxılışın yayımlanması — Developer Panelinin `service_role` tərəfi.

Tələb: *"«Yeni Versiya Yüklə» — … «[Yüklə və Yayımla]» düyməsi — bu, faylı
Storage-a yükləyir VƏ `app_versions` cədvəlinə sətir əlavə edir (iki əməliyyat,
tək düymə)."*

──────────────────────────────────────────────────────────────────────────────
BU FAYL MÜŞTƏRİYƏ GÖNDƏRİLƏN `.exe`-DƏ İŞLƏMİR
──────────────────────────────────────────────────────────────────────────────
`catalog.py` müştəri PC-sindədir və yalnız OXUYUR. Buradakı kod isə kataloqa
YAZAN tərəfdir — `service_role` açarı tələb edir və yalnız hazırlayıcının öz
kompüterində, `--developer-mode` ilə işə düşür (eyni model: bax
`licensing/developer_directory.py`).

──────────────────────────────────────────────────────────────────────────────
SIRA: ƏVVƏLCƏ FAYL, SONRA SƏTİR — QƏTİYYƏN ƏKSİ DEYİL
──────────────────────────────────────────────────────────────────────────────
İki əməliyyat bir tranzaksiya DEYİL (biri Storage-da, biri Postgres-də), ona
görə yarımçıq qalma ehtimalı var. İki yarımçıq halın nəticələri kəskin fərqlidir:

    sətir var, fayl yox  → BÜTÜN tenant-lar yeni versiya görür, endirməyə
                           çalışır və uğursuz olur. Hər saat, hər filialda.
    fayl var, sətir yox  → heç kim heç nə görmür. Bucket-də bir artıq fayl
                           qalır, o qədər.

İkincisi açıq-aşkar ucuzdur, ona görə yükləmə HƏMİŞƏ birinci gedir. Sətir
əlavə olunana qədər buraxılış "yayımlanmamış" sayılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İMZA YAYIMDAN ƏVVƏL YOXLANILIR (LAKİN BLOKLAMIR)
──────────────────────────────────────────────────────────────────────────────
Klient fail-closed-dur: imzasız paketi RƏDD edir (bax `verification.py`). Yəni
imzasız buraxılış yayımlansa, nəticə sükutla "heç kim yenilənmir" olardı və
səbəb yalnız log-larda görünərdi. `inspect()` bunu YAYIMDAN ƏVVƏL üzə çıxarır
— hazırlayıcı hələ öz kompüterində ikən. Bloklamır, çünki imzasız daxili sınaq
buraxılışı (BETA kanalı, imzalanmamış staging build — bax bölmə 1 CI/CD)
qanuni haldır; qərar açıq şəkildə hazırlayıcıya verilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import httpx

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.updates import (
    DEFAULT_PACKAGE_FILENAME,
    MAX_PACKAGE_BYTES,
    ReleaseChannel,
    UpdateError,
    Version,
    storage_path_for,
)
from src.infrastructure.config.limits import InfrastructureLimits, fallback_float
from src.infrastructure.updates.catalog import (
    DEFAULT_BUCKET,
    SUPABASE_URL_ENV,
    UPDATE_BUCKET_ENV,
)
from src.infrastructure.updates.verification import file_sha256
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.infrastructure.persistence.connection import Database
    from src.infrastructure.updates.verification import AuthenticodeVerifier

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: `service_role` açarı — `licensing/developer_directory.py` ilə EYNİ dəyişən.
#: İki ayrı ad olsaydı, biri təyin edilib digəri unudulanda panel yarımçıq
#: işləyərdi: tenant siyahısı açılar, yayım isə anlaşılmaz xəta verərdi.
SERVICE_ROLE_ENV: Final[str] = "KOMPASOS_SUPABASE_SERVICE_ROLE_KEY"

#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`UPDATE_UPLOAD_TIMEOUT_SECONDS`, seed: migrations/032). Quraşdırıcı fayl
#: 100 MB-dan böyük ola bilər və hazırlayıcının kanalı simmetrik deyil —
#: sabit 10 dəqiqə yükləməni sonuna yaxın kəsə bilər.
FALLBACK_UPLOAD_TIMEOUT_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.UPDATE_UPLOAD_TIMEOUT_SECONDS
)
#: Quraşdırıcının MIME tipi — Supabase Storage `Content-Type`-ı saxlayır.
PACKAGE_CONTENT_TYPE: Final[str] = "application/octet-stream"

_INSERT_SQL: Final[str] = """
    INSERT INTO app_versions
        (version_number, channel, storage_path, sha256_hash, size_bytes,
         is_mandatory, release_notes, release_date, published_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_EXISTS_SQL: Final[str] = """
    SELECT 1 FROM app_versions WHERE version_number = %s AND channel = %s
"""


class PublishError(UpdateError):
    """Yayım tamamlanmadı."""

    user_message = "Yeni versiya yayımlanmadı."


class VersionAlreadyPublishedError(PublishError):
    """Bu versiya kataloqda artıq var."""

    user_message = (
        "Bu versiya nömrəsi artıq yayımlanıb. Köhnə buraxılışlar geri qaytarma "
        "üçün saxlanılır — nömrəni artırın (məs. 1.4.1)."
    )


@dataclass(frozen=True)
class PackageInspection:
    """Yayımdan ƏVVƏL hesablanan faktlar — təsdiq modalında göstərilir."""

    path: Path
    sha256: str
    size_bytes: int
    #: Authenticode doğrulandımı. `False` → klientlər paketi RƏDD EDƏCƏK.
    is_signed: bool
    publisher_subject: str = ""
    signature_error: str = ""

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 1)


@dataclass(frozen=True)
class PublishResult:
    """Yayımın nəticəsi — paneldə "yayımlandı" mesajının mənbəyi."""

    version: Version
    channel: ReleaseChannel
    storage_path: str
    sha256: str
    size_bytes: int
    is_mandatory: bool
    published_at: datetime


class ReleasePublisher:
    """Quraşdırıcını `app-updates` bucket-inə yükləyir və kataloqa yazır."""

    def __init__(
        self,
        database: Database,
        *,
        base_url: str = "",
        service_role_key: str = "",
        bucket: str = "",
        client: httpx.Client | None = None,
        verifier: AuthenticodeVerifier | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._database = database
        self._base_url = (base_url or os.environ.get(SUPABASE_URL_ENV, "")).rstrip("/")
        self._key = service_role_key or os.environ.get(SERVICE_ROLE_ENV, "")
        self._bucket = bucket or os.environ.get(UPDATE_BUCKET_ENV, "") or DEFAULT_BUCKET
        self._http = client
        self._verifier = verifier
        self._limits = limits or InfrastructureLimits()

    def _max_package_bytes(self) -> int:
        """Yayımlana bilən paketin yuxarı həddi — mənbə `system_limits`.

        `SupabaseReleaseCatalog._max_package_bytes()` ilə EYNİ açarı oxuyur:
        yayımçı və yükləyici eyni həddi görməlidir, əks halda yayımlanan
        paket müştəridə yüklənə bilməzdi.
        """
        limit = self._limits.int_of(SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES)
        return limit if limit > 0 else MAX_PACKAGE_BYTES

    # ------------------------------- yoxlama ---------------------------------- #

    def inspect(self, package: Path) -> PackageInspection:
        """Faylı oxuyur: ölçü, SHA-256 və (mümkünsə) Authenticode imzası.

        Yayımdan əvvəl çağırılır ki, təsdiq modalı real dəyərləri göstərsin —
        "nəyi yayımlayıram?" sualının cavabı klik anında görünsün.
        """
        if not package.is_file():
            raise PublishError(
                f"Fayl tapılmadı: {package}",
                user_message="Seçilmiş fayl tapılmadı.",
                context={"path": str(package)},
            )

        size = package.stat().st_size
        if size <= 0:
            raise PublishError(
                "Fayl boşdur", user_message="Seçilmiş fayl boşdur.", context={"path": str(package)}
            )
        max_bytes = self._max_package_bytes()
        if size > max_bytes:
            raise PublishError(
                f"Fayl limitdən böyükdür: {size} > {max_bytes}",
                user_message=(
                    f"Fayl çox böyükdür ({round(size / (1024 * 1024))} MB). "
                    f"Limit: {max_bytes // (1024 * 1024)} MB."
                ),
                context={"size_bytes": size},
            )

        digest = file_sha256(package)
        subject, error = self._signature_of(package)
        return PackageInspection(
            path=package,
            sha256=digest,
            size_bytes=size,
            is_signed=not error,
            publisher_subject=subject,
            signature_error=error,
        )

    def _signature_of(self, package: Path) -> tuple[str, str]:
        """`(naşir, xəta)` — yoxlayıcı verilməyibsə hər ikisi boş sətir."""
        if self._verifier is None:
            return "", "Authenticode yoxlayıcısı konfiqurasiya edilməyib."
        try:
            return self._verifier.verify(package), ""
        except UpdateError as exc:
            return "", exc.message

    # -------------------------------- yayım ----------------------------------- #

    def publish(
        self,
        package: Path,
        version: str,
        *,
        release_notes: str = "",
        is_mandatory: bool = False,
        channel: ReleaseChannel = ReleaseChannel.STABLE,
        inspection: PackageInspection | None = None,
        now: datetime | None = None,
    ) -> PublishResult:
        """Faylı yükləyir, sonra kataloqa sətir əlavə edir.

        Args:
            package: Yerli `KompasOS-Setup.exe`.
            version: `1.4.0` formatında versiya nömrəsi.
            release_notes: Buraxılış qeydləri (istifadəçiyə göstərilir).
            is_mandatory: "Məcburi Yeniləmədir" checkbox-u.
            channel: `STABLE` müştərilər, `BETA` daxili sınaq.
            inspection: `inspect()` nəticəsi — verilməsə yenidən hesablanır.
                Panel onu təsdiq modalı üçün onsuz da hesablayır; təkrar
                hesablamaq onlarla meqabaytlıq faylı ikinci dəfə oxumaq olardı.

        Raises:
            VersionAlreadyPublishedError: Bu versiya kataloqda var.
            PublishError: Yükləmə və ya yazma alınmadı.
        """
        parsed = Version.try_parse(version)
        if parsed is None:
            raise PublishError(
                f"Versiya formatı tanınmadı: {version!r}",
                user_message="Versiya «1.4.0» formatında olmalıdır.",
                context={"value": version},
            )
        if not self._base_url or not self._key:
            raise PublishError(
                "Supabase ünvanı və ya service_role açarı təyin edilməyib",
                user_message=(
                    "Yayım üçün `KOMPASOS_SUPABASE_URL` və "
                    "`KOMPASOS_SUPABASE_SERVICE_ROLE_KEY` təyin edilməlidir."
                ),
                context={"required_env": [SUPABASE_URL_ENV, SERVICE_ROLE_ENV]},
            )

        if self._version_exists(str(parsed), channel):
            raise VersionAlreadyPublishedError(
                f"Versiya artıq kataloqdadır: {parsed} ({channel.value})",
                context={"version": str(parsed), "channel": channel.value},
            )

        facts = inspection or self.inspect(package)
        storage_path = storage_path_for(parsed, filename=DEFAULT_PACKAGE_FILENAME)
        moment = now or datetime.now(UTC)

        # 1) FAYL — sıra qəsdəndir (bax modul başlığı).
        self._upload(package, storage_path, size_bytes=facts.size_bytes)

        # 2) SƏTİR — bundan sonra buraxılış klientlərə GÖRÜNÜR.
        try:
            with self._database.system_scope() as conn, conn.cursor() as cur:
                cur.execute(
                    _INSERT_SQL,
                    (
                        str(parsed),
                        channel.value,
                        storage_path,
                        facts.sha256,
                        facts.size_bytes,
                        is_mandatory,
                        release_notes.strip(),
                        moment.date(),
                        moment,
                    ),
                )
                conn.commit()
        except Exception as exc:
            # Fayl bucket-də qalır — zərərsizdir (görünməz buraxılış) və
            # növbəti cəhddə `x-upsert` ilə üzərinə yazılır.
            raise PublishError(
                "Kataloqa yazıla bilmədi", context={"error": str(exc), "version": str(parsed)}
            ) from exc

        _audit_log.warning(
            "RELEASE_PUBLISHED",
            extra={
                "version": str(parsed),
                "channel": channel.value,
                "storage_path": storage_path,
                "sha256": facts.sha256,
                "size_bytes": facts.size_bytes,
                "is_mandatory": is_mandatory,
                "signed": facts.is_signed,
                "publisher": facts.publisher_subject or None,
            },
        )
        return PublishResult(
            version=parsed,
            channel=channel,
            storage_path=storage_path,
            sha256=facts.sha256,
            size_bytes=facts.size_bytes,
            is_mandatory=is_mandatory,
            published_at=moment,
        )

    # ------------------------------- köməkçilər ------------------------------- #

    def _version_exists(self, version: str, channel: ReleaseChannel) -> bool:
        try:
            with self._database.system_scope() as conn, conn.cursor() as cur:
                cur.execute(_EXISTS_SQL, (version, channel.value))
                return cur.fetchone() is not None
        except Exception as exc:
            raise PublishError("Kataloq oxuna bilmədi", context={"error": str(exc)}) from exc

    def _upload(self, package: Path, storage_path: str, *, size_bytes: int) -> None:
        """Faylı bucket-ə yükləyir (axınla — fayl yaddaşa tam oxunmur)."""
        url = f"{self._base_url}/storage/v1/object/{self._bucket}/{storage_path}"
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": PACKAGE_CONTENT_TYPE,
            "Content-Length": str(size_bytes),
            # Eyni yola təkrar yazmağa icazə: yarımçıq qalmış əvvəlki cəhdin
            # (fayl yükləndi, sətir yazılmadı) təkrarı bloklanmamalıdır.
            # Kataloqdakı sətir onsuz da unikaldır — həqiqi qoruma odur.
            "x-upsert": "true",
        }
        # Taymaut YÜKLƏMƏ ANINDA oxunur: klient hər yayımda yenidən qurulur,
        # yəni Root-un dəyişikliyi növbəti yayımda dərhal qüvvədədir.
        client = self._http or httpx.Client(
            timeout=self._limits.float_of(SystemLimitKey.UPDATE_UPLOAD_TIMEOUT_SECONDS)
        )
        try:
            with package.open("rb") as handle:
                response = client.post(url, headers=headers, content=handle)
            if response.status_code >= httpx.codes.BAD_REQUEST:
                raise PublishError(
                    f"Yükləmə alınmadı (HTTP {response.status_code})",
                    user_message="Fayl Supabase Storage-a yüklənmədi.",
                    context={"status_code": response.status_code, "path": storage_path},
                )
        except PublishError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise PublishError(
                "Yükləmə zamanı xəta", context={"error": str(exc), "path": storage_path}
            ) from exc
        finally:
            if self._http is None:
                client.close()

        _log.info(
            "RELEASE_PACKAGE_UPLOADED",
            extra={"path": storage_path, "bytes": size_bytes, "bucket": self._bucket},
        )

    def list_published(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Son buraxılışlar — panelin "Yayımlanmış versiyalar" siyahısı."""
        try:
            with self._database.system_scope() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT version_number, channel, release_date, is_mandatory,
                           size_bytes, published_at
                      FROM app_versions
                     ORDER BY published_at DESC NULLS LAST, created_at DESC
                     LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            raise PublishError("Kataloq oxuna bilmədi", context={"error": str(exc)}) from exc


__all__ = [
    "PACKAGE_CONTENT_TYPE",
    "SERVICE_ROLE_ENV",
    "PackageInspection",
    "PublishError",
    "PublishResult",
    "ReleasePublisher",
    "VersionAlreadyPublishedError",
]
