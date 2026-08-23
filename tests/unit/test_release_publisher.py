"""Buraxılışın yayımlanması — `ReleasePublisher` (Developer Paneli, service_role).

Ən vacib test `test_yukleme_ugursuz_olarsa_kataloqa_setir_dusmur`-dur: kataloqda
sətir olub bucket-də fayl OLMAMASI ən pis yarımçıq haldır — bütün tenant-lar
mövcud olmayan paketi endirməyə çalışar. Sıra (əvvəlcə fayl, sonra sətir) məhz
bunun üçündür və test onu qoruyur.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from src.developer_panel.console import publish_confirmation_text
from src.domain.value_objects.updates import (
    DEFAULT_PACKAGE_FILENAME,
    ReleaseChannel,
    ReleaseInfo,
    UpdateAction,
    Version,
    decide,
    storage_path_for,
)
from src.infrastructure.updates.publisher import (
    PublishError,
    ReleasePublisher,
    VersionAlreadyPublishedError,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

PAYLOAD = b"MZ-fake-installer-bytes"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
BASE_URL = "https://project.supabase.co"


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


class FakeDatabase:
    """`system_scope()` — `developer_directory.py` ilə eyni səth."""

    def __init__(self, *, existing: list[str] | None = None) -> None:
        self.existing = existing or []
        self.inserted: list[tuple[Any, ...]] = []
        self.committed = 0
        self.fail_on_insert = False
        #: SAAS-2 — hər `system_scope()` bəyanı (cədvəl siyahısı, cross_tenant).
        self.scopes: list[tuple[Any, bool]] = []

    def system_scope(self, *, tables: Any = None, cross_tenant: bool = False) -> _Conn:
        """SAAS-2: çağıran indi HANSI cədvələ toxunduğunu BƏYAN edir.

        Sahtə bəyanı yoxlamır (real `Database` onu ağ siyahı ilə üzləşdirir) —
        burada yalnız İMZA uyğunluğu lazımdır, əks halda yeni açar-arqumentlə
        gələn çağırış `TypeError` verərdi və test məhsulun qüsurunu deyil,
        sahtənin köhnəliyini göstərərdi.
        """
        self.scopes.append((tables, cross_tenant))
        return _Conn(self)


class _Conn:
    def __init__(self, database: FakeDatabase) -> None:
        self._db = database

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self._db)

    def commit(self) -> None:
        self._db.committed += 1


class _Cursor:
    def __init__(self, database: FakeDatabase) -> None:
        self._db = database
        self._row: tuple[Any, ...] | None = None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if "SELECT 1 FROM app_versions" in sql:
            self._row = (1,) if params[0] in self._db.existing else None
        elif "INSERT INTO app_versions" in sql:
            if self._db.fail_on_insert:
                msg = "unique_violation"
                raise RuntimeError(msg)
            self._db.inserted.append(params)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[dict[str, Any]]:
        return []


class FakeVerifier:
    """`AuthenticodeVerifier` əvəzi — imzalı/imzasız halları modelləşdirir."""

    def __init__(self, *, subject: str = "O=Kompas MMC", error: str = "") -> None:
        self._subject = subject
        self._error = error

    def verify(self, path: Path) -> str:
        if self._error:
            from src.domain.value_objects.updates import SignatureRejectedError

            raise SignatureRejectedError(self._error)
        return self._subject


class UploadRecorder:
    """`httpx.MockTransport` handler-i — sorğuları yazır, cavabı idarə edir."""

    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()  # gövdəni oxu ki, `request.content` əlçatan olsun
        self.requests.append(request)
        return httpx.Response(self.status, json={"Key": "app-updates/x"})


@pytest.fixture
def package(tmp_path: Path) -> Path:
    target = tmp_path / "KompasOS-Setup.exe"
    target.write_bytes(PAYLOAD)
    return target


def make_publisher(
    *,
    database: FakeDatabase | None = None,
    recorder: UploadRecorder | None = None,
    verifier: Any = None,
    base_url: str = BASE_URL,
    key: str = "service-role-key",
) -> tuple[ReleasePublisher, FakeDatabase, UploadRecorder]:
    db = database or FakeDatabase()
    rec = recorder or UploadRecorder()
    publisher = ReleasePublisher(
        db,  # type: ignore[arg-type]
        base_url=base_url,
        service_role_key=key,
        bucket="app-updates",
        client=httpx.Client(transport=httpx.MockTransport(rec)),
        verifier=verifier if verifier is not None else FakeVerifier(),
    )
    return publisher, db, rec


# --------------------------------------------------------------------------- #
# inspect()
# --------------------------------------------------------------------------- #


class TestInspect:
    def test_hash_ve_olcu_hesablanir(self, package: Path) -> None:
        publisher, _, _ = make_publisher()

        facts = publisher.inspect(package)

        assert facts.sha256 == DIGEST
        assert facts.size_bytes == len(PAYLOAD)

    def test_imzali_paketde_nasir_qaytarilir(self, package: Path) -> None:
        publisher, _, _ = make_publisher()

        facts = publisher.inspect(package)

        assert facts.is_signed is True
        assert facts.publisher_subject == "O=Kompas MMC"

    def test_imzasiz_paket_bloklamir_amma_isarelenir(self, package: Path) -> None:
        """İmzasız paket yayımlana bilər — lakin bunu BİLƏRƏK etmək lazımdır."""
        publisher, _, _ = make_publisher(verifier=FakeVerifier(error="imza yoxdur"))

        facts = publisher.inspect(package)

        assert facts.is_signed is False
        assert "imza yoxdur" in facts.signature_error

    def test_olmayan_fayl_xeta_verir(self, tmp_path: Path) -> None:
        publisher, _, _ = make_publisher()

        with pytest.raises(PublishError):
            publisher.inspect(tmp_path / "yoxdur.exe")

    def test_bos_fayl_qebul_edilmir(self, tmp_path: Path) -> None:
        empty = tmp_path / "bos.exe"
        empty.touch()
        publisher, _, _ = make_publisher()

        with pytest.raises(PublishError):
            publisher.inspect(empty)


# --------------------------------------------------------------------------- #
# publish()
# --------------------------------------------------------------------------- #


class TestPublish:
    def test_fayl_yuklenir_ve_kataloqa_setir_dusur(self, package: Path) -> None:
        publisher, db, recorder = make_publisher()

        result = publisher.publish(package, "1.4.0", release_notes="Test buraxılışı")

        assert len(recorder.requests) == 1
        assert recorder.requests[0].content == PAYLOAD
        assert len(db.inserted) == 1
        assert result.sha256 == DIGEST

    def test_storage_yolu_versiya_qovlugundadir(self, package: Path) -> None:
        publisher, _, recorder = make_publisher()

        result = publisher.publish(package, "1.4.0")

        assert result.storage_path == f"1.4.0/{DEFAULT_PACKAGE_FILENAME}"
        assert str(recorder.requests[0].url).endswith(
            f"/storage/v1/object/app-updates/1.4.0/{DEFAULT_PACKAGE_FILENAME}"
        )

    def test_service_role_acari_gonderilir(self, package: Path) -> None:
        publisher, _, recorder = make_publisher()

        publisher.publish(package, "1.4.0")

        headers = recorder.requests[0].headers
        assert headers["apikey"] == "service-role-key"
        assert headers["authorization"] == "Bearer service-role-key"

    def test_mecburi_bayragi_kataloqa_yazilir(self, package: Path) -> None:
        publisher, db, _ = make_publisher()

        publisher.publish(package, "1.4.0", is_mandatory=True)

        assert True in db.inserted[0]

    def test_movcud_versiya_tekrar_yayimlanmir(self, package: Path) -> None:
        """Köhnə buraxılışlar geri qaytarma üçün saxlanılır — üzərinə yazılmır."""
        publisher, _, recorder = make_publisher(database=FakeDatabase(existing=["1.4.0"]))

        with pytest.raises(VersionAlreadyPublishedError):
            publisher.publish(package, "1.4.0")

        assert recorder.requests == []

    def test_yararsiz_versiya_formati_redd_edilir(self, package: Path) -> None:
        publisher, _, recorder = make_publisher()

        with pytest.raises(PublishError):
            publisher.publish(package, "son-versiya")

        assert recorder.requests == []

    def test_konfiqurasiya_yoxdursa_yukleme_baslamir(self, package: Path) -> None:
        publisher, _, recorder = make_publisher(base_url="")

        with pytest.raises(PublishError):
            publisher.publish(package, "1.4.0")

        assert recorder.requests == []

    def test_yukleme_ugursuz_olarsa_kataloqa_setir_dusmur(self, package: Path) -> None:
        """SIRA QORUYUCUSU: sətir olub fayl olmaması ən pis yarımçıq haldır."""
        publisher, db, _ = make_publisher(recorder=UploadRecorder(status=403))

        with pytest.raises(PublishError):
            publisher.publish(package, "1.4.0")

        assert db.inserted == []

    def test_kataloqa_yazma_ugursuz_olarsa_xeta_atilir(self, package: Path) -> None:
        database = FakeDatabase()
        database.fail_on_insert = True
        publisher, _, recorder = make_publisher(database=database)

        with pytest.raises(PublishError):
            publisher.publish(package, "1.4.0")

        # Fayl yükləndi (zərərsiz — görünməz buraxılış), sətir isə yazılmadı.
        assert len(recorder.requests) == 1

    def test_inspect_neticesi_tekrar_hesablanmir(self, package: Path) -> None:
        """Onlarla meqabaytlıq faylı ikinci dəfə oxumaq lazım deyil."""
        publisher, _, _ = make_publisher()
        facts = publisher.inspect(package)
        package.write_bytes(b"DEYISDIRILMIS")  # inspect-dən sonra dəyişdi

        result = publisher.publish(package, "1.4.0", inspection=facts)

        assert result.sha256 == DIGEST


# --------------------------------------------------------------------------- #
# Kataloq lüğəti və qərar məntiqi
# --------------------------------------------------------------------------- #


class TestCatalogVocabulary:
    def test_yeni_sutun_adlari_oxunur(self) -> None:
        release = ReleaseInfo.from_row(
            {
                "version_number": "1.4.0",
                "channel": "STABLE",
                "storage_path": f"1.4.0/{DEFAULT_PACKAGE_FILENAME}",
                "sha256_hash": DIGEST,
                "is_mandatory": True,
                "release_notes": "Yamaq",
            }
        )

        assert release.version == Version(1, 4, 0)
        assert release.is_mandatory is True
        assert release.release_notes == "Yamaq"

    def test_kohne_sutun_adlari_da_qebul_edilir(self) -> None:
        """Miqrasiya 009 tətbiq olunmayıbsa klient SÜKUTLA dayanmamalıdır."""
        release = ReleaseInfo.from_row({"version": "1.4.0", "storage_path": "a", "sha256": DIGEST})

        assert release.version == Version(1, 4, 0)
        assert release.sha256 == DIGEST

    def test_storage_yolu_tek_yerden_hesablanir(self) -> None:
        assert storage_path_for(Version(1, 4, 0)) == f"1.4.0/{DEFAULT_PACKAGE_FILENAME}"

    def test_is_mandatory_qerari_mecburi_edir(self) -> None:
        release = ReleaseInfo(
            version=Version(1, 4, 0),
            channel=ReleaseChannel.STABLE,
            storage_path="1.4.0/x.exe",
            sha256=DIGEST,
            is_mandatory=True,
        )

        decision = decide(current=Version(1, 3, 0), latest=release)

        assert decision.action is UpdateAction.MANDATORY

    def test_is_mandatory_kohne_versiyani_geri_qaytarmir(self) -> None:
        """Məcburilik downgrade qoruyucusunu ƏVƏZ ETMİR."""
        release = ReleaseInfo(
            version=Version(1, 2, 0),
            channel=ReleaseChannel.STABLE,
            storage_path="1.2.0/x.exe",
            sha256=DIGEST,
            is_mandatory=True,
        )

        decision = decide(current=Version(1, 3, 0), latest=release)

        assert decision.action is UpdateAction.REFUSED_DOWNGRADE


# --------------------------------------------------------------------------- #
# Miqrasiya 009-dan əvvəlki sxemlə uyğunluq
# --------------------------------------------------------------------------- #


class _LegacyUow:
    """Miqrasiyası gecikmiş tenant: `app_versions` yoxdur, `app_releases` var."""

    def __init__(self, rows: list[dict[str, Any]], *, legacy_also_missing: bool) -> None:
        self._rows = rows
        self._legacy_missing = legacy_also_missing
        self._result: list[dict[str, Any]] = []

    def __enter__(self) -> _LegacyUow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    @property
    def connection(self) -> _LegacyUow:
        return self

    def cursor(self) -> _LegacyUow:
        return self

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if "FROM app_versions" in sql:
            msg = 'relation "app_versions" does not exist'
            raise RuntimeError(msg)
        if self._legacy_missing:
            msg = "bağlantı yoxdur"
            raise RuntimeError(msg)
        self._result = self._rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._result


class _LegacyDatabase:
    def __init__(self, rows: list[dict[str, Any]], *, legacy_also_missing: bool = False) -> None:
        self._rows = rows
        self._legacy_missing = legacy_also_missing

    def unit_of_work(self, tenant_id: Any, **kwargs: Any) -> _LegacyUow:
        return _LegacyUow(self._rows, legacy_also_missing=self._legacy_missing)


class TestLegacySchemaFallback:
    def test_kohne_cedvel_oxunur_ve_yenilenme_dayanmir(self) -> None:
        """Miqrasiya gecikibsə təhlükəsizlik yaması yenə də çatmalıdır."""
        from src.infrastructure.updates.catalog import SupabaseReleaseCatalog

        database = _LegacyDatabase(
            [
                {
                    "version": "1.4.0",
                    "channel": "STABLE",
                    "storage_path": f"1.4.0/{DEFAULT_PACKAGE_FILENAME}",
                    "sha256": DIGEST,
                    "published_at": None,
                }
            ]
        )
        catalog = SupabaseReleaseCatalog(database)  # type: ignore[arg-type]

        latest = catalog.latest(object())  # type: ignore[arg-type]

        assert latest is not None
        assert latest.version == Version(1, 4, 0)

    def test_her_iki_cedvel_oxunmursa_xeta_gizledilmir(self) -> None:
        """Bu, artıq həqiqi nasazlıqdır — "buraxılış yoxdur" kimi udulmamalıdır."""
        from src.domain.value_objects.updates import UpdateUnavailableError
        from src.infrastructure.updates.catalog import SupabaseReleaseCatalog

        catalog = SupabaseReleaseCatalog(
            _LegacyDatabase([], legacy_also_missing=True)  # type: ignore[arg-type]
        )

        with pytest.raises(UpdateUnavailableError):
            catalog.latest(object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Təsdiq mətni
# --------------------------------------------------------------------------- #


class TestConfirmationText:
    def test_imzasiz_paket_ucun_xeberdarliq_var(self, package: Path) -> None:
        publisher, _, _ = make_publisher(verifier=FakeVerifier(error="imza yoxdur"))
        facts = publisher.inspect(package)

        text = publish_confirmation_text("1.4.0", facts, is_mandatory=False)

        assert "RƏDD EDƏCƏK" in text

    def test_mecburi_bayragi_metnde_gorunur(self, package: Path) -> None:
        publisher, _, _ = make_publisher()
        facts = publisher.inspect(package)

        text = publish_confirmation_text("1.4.0", facts, is_mandatory=True)

        assert "Məcburi: BƏLİ" in text
        assert "1.4.0" in text
