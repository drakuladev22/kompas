"""Avtomatik yenilənmə və gecəlik ehtiyat nüsxə — Faza 3.13 testləri.

İki fərqli risk profili yoxlanılır:

    YENİLƏNMƏ  fail-CLOSED — şübhə varsa TƏTBİQ ETMƏ. Doğrulanmamış `.exe`
               hər kassa PC-sində ixtiyari kod deməkdir.
    NÜSXƏ      "yazıldı ≠ yedəkləndi" — yoxlanmamış fayl nüsxə deyil, ümiddir.
"""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from src.domain.value_objects.identifiers import TenantId
from src.domain.value_objects.updates import (
    ChecksumMismatchError,
    InvalidVersionError,
    ReleaseChannel,
    ReleaseInfo,
    SignatureRejectedError,
    UpdateAction,
    UpdateDecision,
    UpdateUnavailableError,
    Version,
    decide,
)
from src.infrastructure.backup.service import (
    MIN_RETENTION_DAYS,
    RESTORE_CONFIRMATION,
    BackupError,
    BackupRecord,
    BackupToolMissingError,
    BackupVerificationError,
    NightlyBackupService,
)
from src.infrastructure.updates.client import SILENT_ARGS, AutoUpdateClient
from src.infrastructure.updates.verification import (
    AuthenticodeVerifier,
    file_sha256,
    verify_checksum,
    verify_package,
)

if TYPE_CHECKING:
    from pathlib import Path

TENANT = TenantId(uuid.UUID("11111111-1111-1111-1111-111111111111"))
NOW = datetime(2026, 8, 9, 2, 0, tzinfo=UTC)
DIGEST_ZERO = "0" * 64


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def make_release(version: str = "1.2.0", **kwargs: Any) -> ReleaseInfo:
    defaults: dict[str, Any] = {
        "channel": ReleaseChannel.STABLE,
        "storage_path": f"stable/KompasOS-{version}.exe",
        "sha256": hashlib.sha256(version.encode()).hexdigest(),
        "size_bytes": 1024,
        "published_at": NOW,
    }
    defaults.update(kwargs)
    return ReleaseInfo(version=Version.parse(version), **defaults)


def ok_process(stdout: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr="")


def signed_runner(status: str = "Valid", subject: str = "CN=Kompas, O=Kompas MMC") -> Any:
    payload = f'{{"status":"{status}","subject":"{subject}","thumbprint":"AB12"}}'
    return lambda _cmd, _env: ok_process(payload)


class FakeCatalog:
    """Bazasız buraxılış kataloqu."""

    def __init__(
        self,
        release: ReleaseInfo | None = None,
        *,
        forced: Version | None = None,
        error: Exception | None = None,
        payload: bytes = b"MZ-setup-payload",
    ) -> None:
        self._release = release
        self._forced = forced
        self._error = error
        self.payload = payload
        self.downloads: list[str] = []

    def latest(self, tenant_id: TenantId, *, channel: ReleaseChannel) -> ReleaseInfo | None:
        if self._error is not None:
            raise self._error
        return self._release

    def forced_version(self, tenant_id: TenantId) -> Version | None:
        return self._forced

    def download(self, release: ReleaseInfo, destination: Path) -> Path:
        self.downloads.append(release.storage_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.payload)
        return destination


def make_client(
    tmp_path: Path,
    *,
    catalog: FakeCatalog,
    current: str = "1.0.0",
    runner: Any = None,
    launches: list[list[str]] | None = None,
) -> AutoUpdateClient:
    verifier = AuthenticodeVerifier(runner=runner or signed_runner())
    return AutoUpdateClient(
        TENANT,
        catalog,  # type: ignore[arg-type]
        verifier,
        current_version=current,
        staging_root=tmp_path,
        launcher=(lambda command: launches.append(list(command))) if launches is not None else None,
    )


# --------------------------------------------------------------------------- #
# Versiya və qərar
# --------------------------------------------------------------------------- #


class TestVersion:
    def test_normal_versiya_oxunur(self) -> None:
        assert Version.parse("1.2.3") == Version(1, 2, 3)

    def test_v_prefiksi_qebul_edilir(self) -> None:
        assert Version.parse("v2.0.1") == Version(2, 0, 1)

    def test_suffiks_saxlanilir(self) -> None:
        assert Version.parse("1.0.0-rc2").suffix == "rc2"

    def test_yararsiz_versiya_redd_edilir(self) -> None:
        with pytest.raises(InvalidVersionError):
            Version.parse("son buraxılış")

    def test_muqayise_reqemlere_gore_gedir(self) -> None:
        assert Version.parse("1.10.0") > Version.parse("1.9.9")

    def test_try_parse_yararsizda_none_verir(self) -> None:
        assert Version.try_parse("") is None

    def test_metn_formati_geri_qaytarilir(self) -> None:
        assert str(Version.parse("1.0.0-rc1")) == "1.0.0-rc1"


class TestDecide:
    def test_eyni_versiya_yenilenme_teleb_etmir(self) -> None:
        decision = decide(current=Version(1, 2, 0), latest=make_release("1.2.0"))

        assert decision.action is UpdateAction.UP_TO_DATE
        assert not decision.should_download

    def test_bos_kataloq_yenilenme_teleb_etmir(self) -> None:
        assert decide(current=Version(1, 0, 0), latest=None).action is UpdateAction.UP_TO_DATE

    def test_yeni_versiya_isteye_bagli_olur(self) -> None:
        decision = decide(current=Version(1, 0, 0), latest=make_release("1.1.0"))

        assert decision.action is UpdateAction.OPTIONAL
        assert decision.should_download
        assert not decision.is_mandatory

    def test_tehlukesizlik_yamasi_mecburi_olur(self) -> None:
        release = make_release("1.5.0", mandatory_below=Version(1, 4, 0))

        decision = decide(current=Version(1, 3, 0), latest=release)

        assert decision.is_mandatory

    def test_yamadan_yeni_qurasdirma_ucun_mecburi_deyil(self) -> None:
        release = make_release("1.5.0", mandatory_below=Version(1, 4, 0))

        decision = decide(current=Version(1, 4, 2), latest=release)

        assert decision.action is UpdateAction.OPTIONAL

    def test_developer_paneli_mecburi_ede_bilir(self) -> None:
        """Bölmə 8: "seçilmiş tenant-a" məcburi yenilənmə."""
        decision = decide(
            current=Version(1, 0, 0),
            latest=make_release("1.1.0"),
            forced_version=Version(1, 1, 0),
        )

        assert decision.is_mandatory

    def test_endirme_redd_edilir(self) -> None:
        """Kataloqa yazma imkanı ələ keçirən hücumçu köhnə, zəiflikli
        versiyanı "yeni buraxılış" kimi göstərə bilməməlidir."""
        decision = decide(current=Version(2, 0, 0), latest=make_release("1.0.0"))

        assert decision.action is UpdateAction.REFUSED_DOWNGRADE
        assert not decision.should_download


class TestReleaseInfo:
    def test_yararsiz_hash_qebul_edilmir(self) -> None:
        with pytest.raises(ValueError, match="sha256"):
            ReleaseInfo(
                version=Version(1, 0, 0),
                channel=ReleaseChannel.STABLE,
                storage_path="a.exe",
                sha256="qisa",
            )

    def test_bos_yol_qebul_edilmir(self) -> None:
        with pytest.raises(ValueError, match="storage_path"):
            ReleaseInfo(
                version=Version(1, 0, 0),
                channel=ReleaseChannel.STABLE,
                storage_path="  ",
                sha256=DIGEST_ZERO,
            )

    def test_setirden_qurulus(self) -> None:
        release = ReleaseInfo.from_row(
            {
                "version": "3.1.4",
                "channel": "beta",
                "storage_path": "beta/setup.exe",
                "sha256": DIGEST_ZERO,
                "size_bytes": 2048,
                "mandatory_below": "3.0.0",
            }
        )

        assert release.channel is ReleaseChannel.BETA
        assert release.mandatory_below == Version(3, 0, 0)

    def test_namelum_kanal_stable_e_dusur(self) -> None:
        release = ReleaseInfo.from_row(
            {"version": "1.0.0", "channel": "nightly", "storage_path": "a", "sha256": DIGEST_ZERO}
        )

        assert release.channel is ReleaseChannel.STABLE


# --------------------------------------------------------------------------- #
# Doğrulama
# --------------------------------------------------------------------------- #


class TestVerification:
    def test_dogru_hash_kecir(self, tmp_path: Path) -> None:
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")

        verify_checksum(package, file_sha256(package))

    def test_yanlis_hash_redd_edilir(self, tmp_path: Path) -> None:
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")

        with pytest.raises(ChecksumMismatchError):
            verify_checksum(package, DIGEST_ZERO)

    def test_etibarli_imza_qebul_edilir(self, tmp_path: Path) -> None:
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")
        verifier = AuthenticodeVerifier(runner=signed_runner())

        assert "Kompas" in verifier.verify(package)

    def test_imzasiz_fayl_redd_edilir(self, tmp_path: Path) -> None:
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")
        verifier = AuthenticodeVerifier(runner=signed_runner(status="NotSigned"))

        with pytest.raises(SignatureRejectedError):
            verifier.verify(package)

    def test_yad_nasir_redd_edilir(self, tmp_path: Path) -> None:
        """Etibarlı, LAKİN başqasının sertifikatı ilə imzalanmış fayl."""
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")
        verifier = AuthenticodeVerifier(
            expected_subject="O=Kompas MMC",
            runner=signed_runner(subject="CN=Basqa Sirket, O=Basqa MMC"),
        )

        with pytest.raises(SignatureRejectedError):
            verifier.verify(package)

    def test_yoxlayici_cavab_vermirse_redd_edilir(self, tmp_path: Path) -> None:
        """FAIL-CLOSED: yoxlaya bilmirsənsə, tətbiq etmə."""
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")

        def timeout(_cmd: Any, _env: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=60)

        with pytest.raises(SignatureRejectedError):
            AuthenticodeVerifier(runner=timeout).verify(package)

    def test_yoxlayici_yararsiz_cavab_verirse_redd_edilir(self, tmp_path: Path) -> None:
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")
        verifier = AuthenticodeVerifier(runner=lambda _c, _e: ok_process("<html>xəta</html>"))

        with pytest.raises(SignatureRejectedError):
            verifier.verify(package)

    def test_yoxlayici_xeta_kodu_qaytararsa_redd_edilir(self, tmp_path: Path) -> None:
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")
        verifier = AuthenticodeVerifier(runner=lambda _c, _e: ok_process("", code=1))

        with pytest.raises(SignatureRejectedError):
            verifier.verify(package)

    def test_hash_imzadan_evvel_yoxlanilir(self, tmp_path: Path) -> None:
        """Zədələnmiş baytlar imza yoxlayıcısına ötürülməməlidir."""
        package = tmp_path / "setup.exe"
        package.write_bytes(b"paket")
        called: list[str] = []

        def spy(_cmd: Any, _env: Any) -> Any:
            called.append("imza")
            return ok_process('{"status":"Valid","subject":"x","thumbprint":"y"}')

        with pytest.raises(ChecksumMismatchError):
            verify_package(
                package, expected_sha256=DIGEST_ZERO, verifier=AuthenticodeVerifier(runner=spy)
            )

        assert called == []


# --------------------------------------------------------------------------- #
# Yenilənmə klienti
# --------------------------------------------------------------------------- #


class TestAutoUpdateClient:
    def test_yeni_versiya_hazirlanir(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        client = make_client(tmp_path, catalog=catalog)

        prepared = client.run_once()

        assert prepared is not None
        assert prepared.version == Version(1, 1, 0)
        assert prepared.package_path.exists()

    def test_hash_uygun_gelmirse_paket_silinir(self, tmp_path: Path) -> None:
        """Saxta paket diskdə qalıb sonra təsadüfən işə salınmamalıdır."""
        catalog = FakeCatalog(make_release("1.1.0"))  # hash payload ilə uyğun DEYİL
        client = make_client(tmp_path, catalog=catalog)

        assert client.run_once() is None
        assert list((tmp_path / "updates").glob("*.exe")) == []

    def test_imza_redd_edilirse_paket_silinir(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        client = make_client(tmp_path, catalog=catalog, runner=signed_runner(status="HashMismatch"))

        assert client.run_once() is None
        assert list((tmp_path / "updates").glob("*.exe")) == []

    def test_kataloq_elcatmazdirsa_tetbiq_pozulmur(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(error=UpdateUnavailableError("şəbəkə yoxdur"))
        client = make_client(tmp_path, catalog=catalog)

        decision = client.check()

        assert decision.action is UpdateAction.UP_TO_DATE
        assert client.status["last_error"]

    def test_tetbiq_qurasdiricini_isledir(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        launches: list[list[str]] = []
        client = make_client(tmp_path, catalog=catalog, launches=launches)
        prepared = client.run_once()

        assert client.apply(prepared) is True
        assert launches[0][1:] == list(SILENT_ARGS)

    def test_tetbiqden_evvel_paket_yeniden_dogrulanir(self, tmp_path: Path) -> None:
        """Hazırlıqdan sonra fayl diskdə dəyişdirilə bilər."""
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        launches: list[list[str]] = []
        client = make_client(tmp_path, catalog=catalog, launches=launches)
        prepared = client.run_once()
        assert prepared is not None

        prepared.package_path.write_bytes(b"MALICIOUS-CODE")

        assert client.apply(prepared) is False
        assert launches == []
        assert not prepared.package_path.exists()

    def test_tetbiqden_sonra_geri_qaytarma_noqtesi_saxlanilir(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        client = make_client(tmp_path, catalog=catalog, launches=[])
        client.apply(client.run_once())

        assert client.rollback_package() is not None

    def test_geri_qaytarma_sebekesiz_isleyir(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        launches: list[list[str]] = []
        client = make_client(tmp_path, catalog=catalog, launches=launches)
        client.apply(client.run_once())
        launches.clear()

        assert client.rollback() is True
        assert launches[0][1:] == list(SILENT_ARGS)

    def test_geri_qaytarma_noqtesi_yoxdursa_false(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, catalog=FakeCatalog(), launches=[])

        assert client.rollback() is False

    def test_geri_qaytarilan_paketin_imzasi_da_yoxlanilir(self, tmp_path: Path) -> None:
        """`previous/` istifadəçi profilindədir — dəyişdirilə bilər."""
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        launches: list[list[str]] = []
        verifier_states = ["Valid", "NotSigned"]
        client = AutoUpdateClient(
            TENANT,
            catalog,  # type: ignore[arg-type]
            AuthenticodeVerifier(
                runner=lambda _c, _e: ok_process(
                    f'{{"status":"{verifier_states.pop(0) if verifier_states else "NotSigned"}",'
                    '"subject":"CN=Kompas","thumbprint":"AB"}'
                )
            ),
            current_version="1.0.0",
            staging_root=tmp_path,
            launcher=launches.append,
        )
        prepared = client.prepare(UpdateDecision(UpdateAction.OPTIONAL, release=catalog._release))
        assert prepared is not None
        client._keep_for_rollback(prepared.package_path)

        assert client.rollback() is False

    def test_endirme_teklifi_tetbiq_edilmir(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(make_release("0.9.0"))
        client = make_client(tmp_path, catalog=catalog, current="1.0.0")

        assert client.run_once() is None
        assert catalog.downloads == []

    def test_saglamliq_setri_veziyyeti_ozetleyir(self, tmp_path: Path) -> None:
        catalog = FakeCatalog(make_release("1.1.0"))
        catalog._release = _with_digest(catalog, "1.1.0")
        client = make_client(tmp_path, catalog=catalog)
        client.run_once()

        status = client.status

        assert status["current_version"] == "1.0.0"
        assert status["available_version"] == "1.1.0"
        assert status["prepared_version"] == "1.1.0"


def _with_digest(catalog: FakeCatalog, version: str) -> ReleaseInfo:
    """Kataloq sətrini faktiki payload-ın hash-ı ilə uzlaşdırır."""
    return make_release(version, sha256=hashlib.sha256(catalog.payload).hexdigest())


# --------------------------------------------------------------------------- #
# Gecəlik ehtiyat nüsxə
# --------------------------------------------------------------------------- #


class FakeBackupDatabase:
    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []
        self.expired: list[dict[str, Any]] = []

    def unit_of_work(self, tenant_id: TenantId, **kwargs: Any) -> Any:
        return _BackupUow(self)


class _BackupUow:
    def __init__(self, database: FakeBackupDatabase) -> None:
        self._db = database

    def __enter__(self) -> _BackupUow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    @property
    def connection(self) -> _BackupUow:
        return self

    def cursor(self) -> _BackupCursor:
        return _BackupCursor(self._db)

    def commit(self) -> None:
        return None


class _BackupCursor:
    def __init__(self, database: FakeBackupDatabase) -> None:
        self._db = database
        self._result: list[dict[str, Any]] = []

    def __enter__(self) -> _BackupCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if "INSERT INTO backup_records" in sql:
            self._db.rows.append(params)
        elif "SELECT storage_ref" in sql:
            self._result = self._db.expired

    def fetchall(self) -> list[dict[str, Any]]:
        return self._result


def make_backup_service(
    tmp_path: Path,
    *,
    database: FakeBackupDatabase | None = None,
    runner: Any = None,
    tool: str | None = "pg_dump.exe",
    retention_days: int = MIN_RETENTION_DAYS,
) -> tuple[NightlyBackupService, FakeBackupDatabase]:
    db = database or FakeBackupDatabase()
    service = NightlyBackupService(
        db,  # type: ignore[arg-type]
        dsn="postgresql://user:gizli@localhost:5432/kompasos",
        backup_dir=tmp_path / "backups",
        retention_days=retention_days,
        runner=runner or _writing_runner(),
        clock=lambda: NOW,
        tool_locator=lambda _name: tool,
    )
    return service, db


def _writing_runner(content: bytes = b"PGDMP-fake-dump") -> Any:
    """`pg_dump` əvəzi — `--file` arqumentindəki yola yazır."""

    def run(command: Any, environment: Any) -> subprocess.CompletedProcess[str]:
        target = command[command.index("--file") + 1]
        from pathlib import Path as _Path

        _Path(target).write_bytes(content)
        return ok_process()

    return run


class TestNightlyBackup:
    def test_nusxe_yaradilir_ve_qeyd_olunur(self, tmp_path: Path) -> None:
        service, database = make_backup_service(tmp_path)

        record = service.create(TENANT)

        assert record.path.exists()
        assert record.size_bytes > 0
        assert len(database.rows) == 1

    def test_checksum_faktiki_fayldan_hesablanir(self, tmp_path: Path) -> None:
        service, _ = make_backup_service(tmp_path)

        record = service.create(TENANT)

        assert record.checksum == file_sha256(record.path)

    def test_saxlama_muddeti_30_gunden_asagi_dusmur(self, tmp_path: Path) -> None:
        """Spesifikasiya "minimum 30 gün" deyir — konfiqurasiya səhvi bunu
        sükutla poza bilməməlidir."""
        service, _ = make_backup_service(tmp_path, retention_days=3)

        assert service.retention_days == MIN_RETENTION_DAYS
        assert service.create(TENANT).retention_until == (NOW + timedelta(days=30)).date()

    def test_bos_fayl_etibarsiz_sayilir(self, tmp_path: Path) -> None:
        """ "Yazıldı ≠ yedəkləndi" — boş fayl nüsxə deyil."""
        service, _ = make_backup_service(tmp_path, runner=_writing_runner(b""))

        with pytest.raises(BackupVerificationError):
            service.create(TENANT)

    def test_ugursuz_dump_fayl_qoymur(self, tmp_path: Path) -> None:
        service, _ = make_backup_service(tmp_path, runner=lambda _c, _e: ok_process("", code=1))

        with pytest.raises(BackupError):
            service.create(TENANT)
        assert not list((tmp_path / "backups").glob("*.dump"))

    def test_alet_yoxdursa_aydin_xeta_verilir(self, tmp_path: Path) -> None:
        """Sükutla "sadə SQL ixracı"na keçilmir."""
        service, _ = make_backup_service(tmp_path, tool=None)

        with pytest.raises(BackupToolMissingError):
            service.create(TENANT)

    def test_sifre_emr_setrinde_getmir(self, tmp_path: Path) -> None:
        captured: dict[str, Any] = {}

        def spy(command: Any, environment: Any) -> subprocess.CompletedProcess[str]:
            captured["command"] = list(command)
            captured["env"] = dict(environment)
            from pathlib import Path as _Path

            _Path(command[command.index("--file") + 1]).write_bytes(b"PGDMP")
            return ok_process()

        service, _ = make_backup_service(tmp_path, runner=spy)
        service.create(TENANT)

        assert "gizli" not in " ".join(captured["command"])
        assert captured["env"]["PGPASSWORD"] == "gizli"

    def test_muddeti_bitmis_fayllar_silinir(self, tmp_path: Path) -> None:
        service, database = make_backup_service(tmp_path)
        stale = tmp_path / "backups" / "kohne.dump"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"stale")
        database.expired = [{"storage_ref": str(stale)}]

        assert service.prune(TENANT) == 1
        assert not stale.exists()

    def test_qeyd_yazila_bilmese_de_fayl_qalir(self, tmp_path: Path) -> None:
        """Fayl ƏSL nüsxədir — qeyd sonradan bərpa oluna bilər."""

        class BrokenDatabase(FakeBackupDatabase):
            def unit_of_work(self, tenant_id: TenantId, **kwargs: Any) -> Any:
                msg = "DB yoxdur"
                raise RuntimeError(msg)

        service, _ = make_backup_service(tmp_path, database=BrokenDatabase())

        record = service.create(TENANT)

        assert record.path.exists()


class TestRestore:
    def _record(self, tmp_path: Path, content: bytes = b"PGDMP") -> BackupRecord:
        path = tmp_path / "nusxe.dump"
        path.write_bytes(content)
        return BackupRecord(
            tenant_id=str(TENANT),
            backup_type="NIGHTLY_AUTO",
            storage_ref=str(path),
            size_bytes=len(content),
            checksum=hashlib.sha256(content).hexdigest(),
            retention_until=(NOW + timedelta(days=30)).date(),
            created_at=NOW,
        )

    def test_tesdiq_ifadesi_olmadan_berpa_edilmir(self, tmp_path: Path) -> None:
        service, _ = make_backup_service(tmp_path)
        record = self._record(tmp_path)

        with pytest.raises(BackupError, match="təsdiqlənmədi"):
            service.restore(record, target_dsn="postgresql://x/y", confirmation="hə")

    def test_zedelenmis_nusxeden_berpa_edilmir(self, tmp_path: Path) -> None:
        """Bölmə 1: məcburi pre-flight checksum yoxlaması."""
        service, _ = make_backup_service(tmp_path)
        record = self._record(tmp_path)
        record.path.write_bytes(b"TAMPERED")

        with pytest.raises(BackupVerificationError):
            service.restore(
                record, target_dsn="postgresql://x/y", confirmation=RESTORE_CONFIRMATION
            )

    def test_dogru_tesdiq_ve_checksum_ile_berpa_islenir(self, tmp_path: Path) -> None:
        captured: dict[str, Any] = {}

        def spy(command: Any, environment: Any) -> subprocess.CompletedProcess[str]:
            captured["command"] = list(command)
            captured["env"] = dict(environment)
            return ok_process()

        service, _ = make_backup_service(tmp_path, runner=spy, tool="pg_restore.exe")
        record = self._record(tmp_path)

        service.restore(
            record, target_dsn="postgresql://u:p@h/db", confirmation=RESTORE_CONFIRMATION
        )

        assert "--clean" in captured["command"]
        assert "p" not in captured["command"][captured["command"].index("--dbname") + 1].split(":")

    def test_olmayan_fayldan_berpa_edilmir(self, tmp_path: Path) -> None:
        service, _ = make_backup_service(tmp_path, tool="pg_restore.exe")
        record = self._record(tmp_path)
        record.path.unlink()

        with pytest.raises(BackupError, match="tapılmadı"):
            service.restore(
                record, target_dsn="postgresql://x/y", confirmation=RESTORE_CONFIRMATION
            )
