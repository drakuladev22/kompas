"""Buraxılış kataloqu və paket yükləməsi (Supabase) — Faza 3.13.

Lisenziya ilə eyni arxitektura: ayrıca update serveri, CDN və ya domen YOXDUR.

    `app_versions`               buraxılış siyahısı (versiya, hash, yol)
    `app-updates` bucket-i       quraşdırıcı faylın özü (PRIVATE)
    `license_tenants.forced_...` seçilmiş tenant üçün məcburi versiya

──────────────────────────────────────────────────────────────────────────────
NİYƏ HASH KATALOQDA SAXLANILIR, FAYLIN YANINDA DEYİL
──────────────────────────────────────────────────────────────────────────────
`setup.exe.sha256` kimi yan fayl faydasız olardı: faylı əvəz edən hücumçu
onun yanındakı hash faylını da əvəz edər. Kataloqdakı sətir isə AYRI bir
etibar sərhədindədir (`app_versions`-ə yazma yalnız `service_role` ilə
mümkündür). Hash tək başına kifayət etmir — Authenticode ikinci qatdır
(bax `verification.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ ENDİRMƏ DEFOLT OLARAQ İMZALI URL İLƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Bucket private-dir, yəni endirmə `apikey` başlığı tələb edir. İmzalı URL
(`/object/sign/...`) BİR ƏLAVƏ sorğu deməkdir və eyni `anon` açarı ilə alınır
— yəni ƏLAVƏ TƏHLÜKƏSİZLİK VERMİR, sadəcə linkin müvəqqəti olmasını təmin
edir. Faydalı olduğu yeganə hal: endirməni tətbiqdən KƏNAR bir alətə
(brauzer, `curl`, korporativ proxy) ötürmək lazım gələndə. Ona görə
`use_signed_url=True` seçim kimi saxlanılır, defolt isə birbaşa
autentifikasiyalı `GET`-dir — bir sorğu az, bir nasazlıq nöqtəsi az.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YÜKLƏMƏ AXINLA (STREAM) GEDİR
──────────────────────────────────────────────────────────────────────────────
Quraşdırıcı onlarla meqabaytdır. Bütövlükdə yaddaşa oxumaq mağaza PC-sində
(çox vaxt 4 GB RAM) digər işləri sıxışdırardı. Üstəlik axın ölçü limitini
yükləmə ZAMANI tətbiq etməyə imkan verir — gözlənilməz nəhəng cavab diski
doldurmadan kəsilir.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Final

import httpx

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.updates import (
    MAX_PACKAGE_BYTES,
    ReleaseChannel,
    ReleaseInfo,
    UpdateUnavailableError,
    Version,
)
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_float,
    fallback_int,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)

SUPABASE_URL_ENV: Final[str] = "KOMPASOS_SUPABASE_URL"
SUPABASE_ANON_KEY_ENV: Final[str] = "KOMPASOS_SUPABASE_ANON_KEY"
UPDATE_BUCKET_ENV: Final[str] = "KOMPASOS_UPDATE_BUCKET"
DEFAULT_BUCKET: Final[str] = "app-updates"

#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`UPDATE_DOWNLOAD_TIMEOUT_SECONDS`, seed: migrations/032). Mağazanın
#: kanalı zəifdirsə 5 dəqiqə paketi endirməyə çatmır və yenilənmə sonsuz
#: təkrar cəhd dövrünə düşərdi.
FALLBACK_DOWNLOAD_TIMEOUT_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.UPDATE_DOWNLOAD_TIMEOUT_SECONDS
)
DOWNLOAD_CHUNK: Final[int] = 256 * 1024
#: İmzalı linkin ömrü — yükləmə üçün kifayət, paylaşmaq üçün qısa.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`UPDATE_SIGNED_URL_TTL_SECONDS`, seed: migrations/032).
FALLBACK_SIGNED_URL_TTL_SECONDS: Final[int] = fallback_int(
    SystemLimitKey.UPDATE_SIGNED_URL_TTL_SECONDS
)

#: Kataloq sorğusunun oxuduğu sətir tavanı — FALLBACK; HƏQİQİ MƏNBƏ
#: `system_limits` (`UPDATE_CATALOG_FETCH_LIMIT`). Sorğu son N sətri gətirir
#: və İLK OXUNA BİLƏNİ seçir (bax `latest` docstring-i); N nə qədər böyükdürsə
#: yararsız sətirlərə qarşı dözüm bir o qədər artır, sorğu isə ağırlaşır.
FALLBACK_CATALOG_FETCH_LIMIT: Final[int] = fallback_int(SystemLimitKey.UPDATE_CATALOG_FETCH_LIMIT)

_LATEST_SQL: Final[str] = """
    SELECT version_number, channel, storage_path, sha256_hash, size_bytes,
           is_mandatory, mandatory_below, release_notes, release_date, published_at
      FROM app_versions
     WHERE channel = %s AND published_at IS NOT NULL
     ORDER BY published_at DESC
     LIMIT %s
"""

#: Miqrasiya 009-dan ƏVVƏLKİ sxem. Klient `.exe` ilə baza miqrasiyası ayrı-ayrı
#: yayılır — biri digərindən qabaq gedə bilər. Bu ehtiyat sorğu olmasaydı,
#: miqrasiyası gecikmiş tenant-da yenilənmə SÜKUTLA dayanardı: kataloq oxunmaz,
#: klient isə bunu normal "yeni versiya yoxdur" halı kimi qəbul edərdi (bax
#: `client.check`). Yəni təhlükəsizlik yaması çatmazdı və heç kim bilməzdi.
_LATEST_SQL_LEGACY: Final[str] = """
    SELECT version, channel, storage_path, sha256, size_bytes,
           mandatory_below, release_notes_az, published_at
      FROM app_releases
     WHERE channel = %s AND published_at IS NOT NULL
     ORDER BY published_at DESC
     LIMIT %s
"""


class SupabaseReleaseCatalog:
    """`app_versions` cədvəlini oxuyur və paketi Storage-dan yükləyir."""

    def __init__(
        self,
        database: Database,
        *,
        base_url: str = "",
        anon_key: str = "",
        bucket: str = "",
        client: httpx.Client | None = None,
        use_signed_url: bool = False,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._database = database
        self._base_url = (base_url or os.environ.get(SUPABASE_URL_ENV, "")).rstrip("/")
        self._anon_key = anon_key or os.environ.get(SUPABASE_ANON_KEY_ENV, "")
        self._bucket = bucket or os.environ.get(UPDATE_BUCKET_ENV, "") or DEFAULT_BUCKET
        self._http = client
        self._use_signed_url = use_signed_url
        self._limits = limits or InfrastructureLimits()

    def _max_package_bytes(self) -> int:
        """Yüklənəcək paketin yuxarı həddi — mənbə `system_limits`.

        `MAX_PACKAGE_BYTES` modul sabiti YALNIZ fallback-dır (limit portu
        ötürülməyən çağırış yolları üçün). Sıfır/mənfi dəyər həddi SÖNDÜRMÜR,
        fallback-a qaytarır: səhv konfiqurasiya diski dolduran yükləməyə
        icazə verməməlidir (`google_drive._max_upload_bytes` ilə eyni qayda).
        """
        limit = self._limits.int_of(SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES)
        return limit if limit > 0 else MAX_PACKAGE_BYTES

    # -------------------------------- kataloq -------------------------------- #

    def latest(
        self, tenant_id: TenantId, *, channel: ReleaseChannel = ReleaseChannel.STABLE
    ) -> ReleaseInfo | None:
        """Kanalın ən yeni ETİBARLI buraxılışı.

        Sorğu son 20 sətri gətirir və İLK OXUNA BİLƏNİ seçir: bir yararsız
        sətir (məs. səhv yazılmış hash) bütün yenilənmə kanalını
        dayandırmamalıdır — bu, kataloqa yazan tərəfin bir düzəliş səhvinin
        21 filialı köhnə versiyada saxlaması demək olardı.
        """
        try:
            # `LIMIT` PARAMETRLƏŞDİRİLİB (`%s`), sətir birləşdirmə YOXDUR —
            # CLAUDE.md §4 SQL qaydası. Dəyər onsuz da klamp edilmiş tam ədəddir.
            fetch_limit = self._limits.int_of(SystemLimitKey.UPDATE_CATALOG_FETCH_LIMIT)
            rows = self._fetch(tenant_id, _LATEST_SQL, (channel.value, fetch_limit))
        except UpdateUnavailableError:
            rows = self._fetch_legacy(tenant_id, channel)

        for row in rows:
            try:
                return ReleaseInfo.from_row(row)
            except (ValueError, TypeError) as exc:
                _log.warning(
                    "UPDATE_RELEASE_ROW_INVALID",
                    extra={"version": str(row.get("version")), "error": str(exc)},
                )
        return None

    def forced_version(self, tenant_id: TenantId) -> Version | None:
        """Bu tenant üçün Developer Panelindən təyin edilmiş məcburi versiya."""
        rows = self._fetch(
            tenant_id,
            "SELECT forced_update_version FROM license_tenants WHERE tenant_id = %s",
            (tenant_id,),
        )
        if not rows:
            return None
        return Version.try_parse(str(rows[0].get("forced_update_version") or ""))

    def _fetch_legacy(self, tenant_id: TenantId, channel: ReleaseChannel) -> list[dict[str, Any]]:
        """Miqrasiya 009-dan əvvəlki `app_releases` cədvəli (bax `_LATEST_SQL_LEGACY`).

        Hər iki cədvəl yoxdursa xəta YUXARI ötürülür — bu, artıq həqiqi
        nasazlıqdır (bağlantı yoxdur, icazə yoxdur) və gizlədilməməlidir.
        """
        fetch_limit = self._limits.int_of(SystemLimitKey.UPDATE_CATALOG_FETCH_LIMIT)
        rows = self._fetch(tenant_id, _LATEST_SQL_LEGACY, (channel.value, fetch_limit))
        _log.warning(
            "UPDATE_CATALOG_LEGACY_SCHEMA",
            extra={
                "detail": "`app_versions` oxunmadı, `app_releases` istifadə olundu",
                "action": "miqrasiya 009 tətbiq edilməlidir",
            },
        )
        return rows

    def _fetch(
        self, tenant_id: TenantId, sql: str, params: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        try:
            with self._database.unit_of_work(tenant_id) as uow, uow.connection.cursor() as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            raise UpdateUnavailableError(
                "Buraxılış kataloqu oxuna bilmədi", context={"error": str(exc)}
            ) from exc

    # -------------------------------- yükləmə -------------------------------- #

    @property
    def is_download_configured(self) -> bool:
        return bool(self._base_url)

    def download(self, release: ReleaseInfo, destination: Path) -> Path:
        """Paketi Storage-dan `destination`-a yükləyir (axınla).

        Doğrulama BURADA APARILMIR — `verification.verify_package()` ayrıca
        çağırılır. Səbəb: yükləmə və doğrulama fərqli nasazlıq siniflərdir və
        onları ayırmaq "şəbəkə kəsildi" ilə "imza saxtadır" hallarını
        qarışdırmamağa imkan verir (birincisi təkrar cəhd, ikincisi
        TƏHLÜKƏSİZLİK hadisəsidir).
        """
        if not self._base_url:
            raise UpdateUnavailableError(
                "Supabase ünvanı təyin edilməyib", context={"env": SUPABASE_URL_ENV}
            )

        headers = self._auth_headers()
        destination.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        # Taymaut ENDİRMƏ ANINDA oxunur — klient hər endirmədə qurulur.
        client = self._http or httpx.Client(
            timeout=self._limits.float_of(SystemLimitKey.UPDATE_DOWNLOAD_TIMEOUT_SECONDS)
        )
        try:
            url = (
                self._signed_url(release.storage_path, client)
                if self._use_signed_url
                else f"{self._base_url}/storage/v1/object/{self._bucket}/{release.storage_path}"
            )
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code >= httpx.codes.BAD_REQUEST:
                    raise UpdateUnavailableError(
                        f"Paket yüklənmədi (HTTP {response.status_code})",
                        context={"status_code": response.status_code, "path": release.storage_path},
                    )
                # Hədd DÖVRƏDƏN ƏVVƏL bir dəfə oxunur: hər 64 KB blokda
                # `system_limits`-ə sorğu getsəydi, 500 MB-lıq paket minlərlə
                # əlavə sorğu demək olardı. Root dəyəri yükləmənin ORTASINDA
                # dəyişsə, cari yükləmə köhnə həddi ilə bitir — növbəti dəfə
                # yenisi tətbiq olunur.
                max_bytes = self._max_package_bytes()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes(DOWNLOAD_CHUNK):
                        written += len(chunk)
                        if written > max_bytes:
                            # Limit yükləmə ZAMANI tətbiq olunur — disk dolmur.
                            handle.close()
                            destination.unlink(missing_ok=True)
                            raise UpdateUnavailableError(
                                "Paket gözlənilən ölçüdən böyükdür",
                                context={"limit_bytes": max_bytes},
                            )
                        handle.write(chunk)
        except UpdateUnavailableError:
            raise
        except httpx.HTTPError as exc:
            destination.unlink(missing_ok=True)
            raise UpdateUnavailableError(
                "Paket yüklənərkən şəbəkə xətası", context={"error": str(exc)}
            ) from exc
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise UpdateUnavailableError(
                "Paket diskə yazıla bilmədi", context={"error": str(exc)}
            ) from exc
        finally:
            if self._http is None:
                client.close()

        _log.info(
            "UPDATE_PACKAGE_DOWNLOADED",
            extra={"version": str(release.version), "bytes": written},
        )
        return destination

    def _auth_headers(self) -> dict[str, str]:
        """Private bucket üçün `anon` açarı — açarsız endirmə 400 verir."""
        if not self._anon_key:
            return {}
        return {"apikey": self._anon_key, "Authorization": f"Bearer {self._anon_key}"}

    def _signed_url(self, storage_path: str, client: httpx.Client) -> str:
        """Müvəqqəti imzalı endirmə linki (`use_signed_url=True` halında)."""
        endpoint = f"{self._base_url}/storage/v1/object/sign/{self._bucket}/{storage_path}"
        try:
            response = client.post(
                endpoint,
                headers=self._auth_headers(),
                json={
                    "expiresIn": self._limits.int_of(SystemLimitKey.UPDATE_SIGNED_URL_TTL_SECONDS)
                },
            )
            response.raise_for_status()
            signed = str(response.json().get("signedURL") or "")
        except (httpx.HTTPError, ValueError) as exc:
            raise UpdateUnavailableError(
                "İmzalı endirmə linki alınmadı", context={"error": str(exc)}
            ) from exc

        if not signed:
            raise UpdateUnavailableError(
                "İmzalı endirmə linki boş qayıtdı", context={"path": storage_path}
            )
        # Cavabdakı yol `/object/sign/...` kimi nisbi gəlir.
        return f"{self._base_url}/storage/v1{signed}" if signed.startswith("/") else signed


__all__ = [
    "DEFAULT_BUCKET",
    "FALLBACK_SIGNED_URL_TTL_SECONDS",
    "SUPABASE_ANON_KEY_ENV",
    "SUPABASE_URL_ENV",
    "UPDATE_BUCKET_ENV",
    "SupabaseReleaseCatalog",
]
