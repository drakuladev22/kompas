"""`--dev` konfiqurasiya yerləşdirməsi və öz-özünü yoxlama (ONBOARD Faza 3/4).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR — «FAYL YARANDI» QAPI DEYİL
──────────────────────────────────────────────────────────────────────────────
`--dev`-in BÜTÜN mənası budur: skript bitən kimi `python main.py` ƏLAVƏ
ADDIM OLMADAN açılmalıdır. Yəni yoxlanmalı olan şey «iki fayl yarandı» deyil,
«TƏTBİQİN OXUDUĞU yollarda, TƏTBİQİN oxuya bildiyi formatda yarandı».

Ona görə testlər faylın məzmununu ƏL İLƏ oxumur — məhz tətbiqin öz oxucuları
(`connection_file.load_settings`, `installation_file`) çağırılır. Yol qaydası
gələcəkdə dəyişsə (məs. `%PROGRAMDATA%`-dan başqa yerə), bu testlər skriptlə
BİRLİKDƏ sürüşəcək və yalançı-yaşıl qalmayacaq.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "onboard_new_tenant.py"
_spec = importlib.util.spec_from_file_location("onboard_new_tenant", _SCRIPT)
assert _spec is not None and _spec.loader is not None
onboard = importlib.util.module_from_spec(_spec)
sys.modules["onboard_new_tenant"] = onboard
_spec.loader.exec_module(onboard)

#: Sınaq DSN-i — parolda `@` VAR: `ConnectionSettings.from_dsn` onu URL-dən
#: açmalıdır, əks halda `--dev` yolunda parol səhv yazılar və qüsur yalnız
#: canlı bazada üzə çıxardı (`from_dsn` docstring-indəki eyni tələ).
_DSN = "postgresql://kompasos_app:p%40ss@db.example.com:5432/postgres"


def _args(tmp_path: Path, *, dev: bool = True, verify: str = "") -> Namespace:
    return Namespace(
        company="Embawood",
        tenant_dsn=_DSN,
        vendor_dsn="postgresql://vendor:v@vendor.example.com:5432/postgres",
        supabase_ref="",
        contact_email="it@embawood.az",
        out=str(tmp_path / "arxiv"),
        dry_run=False,
        dev=dev,
        verify=verify,
        tenant_id="",
        license_key="",
    )


@pytest.fixture
def _local_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Hər iki konfiqurasiya faylını müvəqqəti qovluğa yönləndirir.

    `%PROGRAMDATA%` ƏVƏZLƏNİR, yoxlanan yol qaydası isə DƏYİŞMİR: skript yolu
    yenə `installation_file()`/`connection_file_path()`-dan alır — test sadəcə
    həmin funksiyaların baxdığı kökü müvəqqəti qovluğa çevirir. Belə olmasa
    test bu maşının FAKTİKİ quraşdırmasını üzərinə yazardı.
    """
    root = tmp_path / "ProgramData"
    monkeypatch.setenv("PROGRAMDATA", str(root))
    monkeypatch.setenv("KOMPASOS_INSTALLATION_PATH", str(root / "KompasOS" / "installation.json"))
    monkeypatch.setenv("KOMPASOS_CONNECTION_FILE", str(root / "KompasOS" / "connection.json"))
    # Şifrələmə açarı: bu maşında DPAPI var, CI-da yoxdur — `EnvironmentKey
    # Provider` zəncirin BİRİNCİ üzvüdür, ona görə açıq açar hər iki mühitdə
    # eyni yolu işlədir və test mühitdən asılı qalmır.
    from src.infrastructure.security.encryption import generate_key

    monkeypatch.setenv("KOMPASOS_FERNET_KEY", generate_key())
    return root


def test_dev_deploy_writes_where_the_application_actually_reads(
    tmp_path: Path, _local_config: Path
) -> None:
    """`--dev`-dən sonra tətbiqin ÖZ oxucuları konfiqurasiyanı tapır."""
    from src.infrastructure.config.connection_file import load_settings
    from src.shared.installation import installation_file

    tenant_id = uuid.uuid4()
    onboard._deploy_dev_config(_args(tmp_path), tenant_id)

    stored = json.loads(installation_file().read_text(encoding="utf-8"))
    assert stored["tenant_id"] == str(tenant_id)
    assert stored["is_licensed"] is True

    settings = load_settings()
    assert settings is not None
    assert settings.host == "db.example.com"
    assert settings.database == "postgres"
    assert settings.username == "kompasos_app"
    # Parol GERİ OXUNUR: fayla şifrəli düşür, oxucu onu açır.
    assert settings.password == "p@ss"


def test_dev_deploy_does_not_leave_the_password_in_plain_text(
    tmp_path: Path, _local_config: Path
) -> None:
    """Fayl açıq parol DAŞIMIR — `--dev` yolu bu zəmanəti yan keçmir."""
    from src.infrastructure.config.connection_file import connection_file_path

    onboard._deploy_dev_config(_args(tmp_path), uuid.uuid4())

    raw = connection_file_path().read_text(encoding="utf-8")
    assert "p@ss" not in raw
    assert json.loads(raw)["password_encrypted"]


def test_self_check_rejects_an_identity_file_from_another_installation(
    tmp_path: Path, _local_config: Path
) -> None:
    """`installation.json` BAŞQA kirayəçininkidirsə addım 6 DAYANIR.

    Bu, dev maşınında REAL haldır: əvvəlki müştərinin faylı yerində qalır və
    yeni quraşdırma onu üzərinə yaza bilməsə (icazə, kilid), proqram KÖHNƏ
    kirayəçi ilə açılardı — yəni «hazırdır» mesajı YANLIŞ olardı.
    """
    from src.shared.installation import installation_file

    onboard._deploy_dev_config(_args(tmp_path), uuid.uuid4())
    # Fayl BAŞQA quraşdırmadan qalıb: DSN-ə heç toxunulmur, uyğunsuzluq
    # bağlantıdan ƏVVƏL tutulmalıdır.
    with pytest.raises(onboard.OnboardingError, match="tenant_id"):
        onboard._self_check(_args(tmp_path), uuid.uuid4())

    assert installation_file().exists()  # fayl SİLİNMİR — səbəb operatora lazımdır


def test_self_check_in_prod_mode_reads_the_archive_not_the_local_machine(
    tmp_path: Path, _local_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bayraqsız rejimdə yoxlanan fayl ARXİVDƏKİDİR, bu maşındakı YOX.

    Prod axınında bu maşında heç bir `installation.json` OLMAMALIDIR — addım 6
    yerli faylı oxusaydı, ya köhnə bir quraşdırmanı «təsdiqləyər», ya da
    ümumiyyətlə tapmayıb yalançı xəta verərdi.
    """
    args = _args(tmp_path, dev=False)
    tenant_id = uuid.uuid4()
    archive = Path(args.out)
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "installation.json").write_text(
        json.dumps({"tenant_id": str(tenant_id), "is_licensed": True}), encoding="utf-8"
    )

    seen: dict[str, Any] = {}

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, sql: str, params: tuple[str, ...] | None = None) -> None:
            if params:
                seen["params"] = params

        def fetchone(self) -> tuple[str]:
            return ("Embawood",)

    class _Connection:
        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def cursor(self) -> _Cursor:
            return _Cursor()

    import psycopg

    def _connect(dsn: str, **_: object) -> _Connection:
        seen["dsn"] = dsn
        return _Connection()

    monkeypatch.setattr(psycopg, "connect", _connect)

    onboard._self_check(args, tenant_id)

    # Prod rejimində bağlantı MƏHZ `--tenant-dsn` ilə qurulur: yerli
    # `connection.json` (parolsuz şablon) bu yoxlamanı APARA BİLMƏZ.
    assert seen["dsn"] == _DSN
    assert seen["params"] == (str(tenant_id),)


# --------------------------------------------------------------------------- #
# `--verify` — YOXLAMA REJİMİ (ONBOARD Faza 5)
# --------------------------------------------------------------------------- #


def test_verify_writes_nothing_and_reports_every_broken_link(
    tmp_path: Path, _local_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Hər halqa AYRI sətir kimi görünür və biri sınsa qalanları DAYANMIR.

    Bu, rejimin bütün mənasıdır: dəstək zəngində «hansı halqa çatmır» sualına
    bir çağırışda cavab verilməlidir. Birinci xətada dayansaydı, operator
    ikinci-üçüncü dəfə çağırmalı olardı.
    """
    import psycopg

    args = _args(tmp_path, dev=False, verify=str(uuid.uuid4()))

    def _refuse(_dsn: str, **_: object) -> None:
        raise psycopg.OperationalError("bağlantı yoxdur")

    # `monkeypatch` YOX, çünki `psycopg.connect` burada QƏSDƏN hər iki bazada
    # sınmalıdır — biri tenant, digəri vendor.
    original = psycopg.connect
    psycopg.connect = _refuse  # type: ignore[assignment]
    try:
        code = onboard._verify(args, uuid.UUID(args.verify))
    finally:
        psycopg.connect = original  # type: ignore[assignment]

    output = capsys.readouterr().out
    assert code == 1
    assert "Tenant bazası" in output
    assert "Vendor bazası" in output
    # Yerli konfiqurasiya halqası prod rejimində YALANÇI-QIRMIZI vermir.
    assert "aid deyil" in output
    # HEÇ NƏ YAZILMIR: arxiv qovluğu belə yaranmır.
    assert not Path(args.out).exists()


def test_verify_flags_a_tenant_whose_seed_never_ran(
    tmp_path: Path, _local_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`seed_tenant_defaults()` çağırılmayıbsa «Seed məlumatı» ÇATMIR olur.

    Bu, DB-5-in tapdığı vəziyyətin kiçik qardaşıdır: cədvəllər var, sətirlər
    yox — tətbiq açılır, ROOT ekranı isə BOŞ gəlir və səbəb heç yerdə
    yazılmır.
    """
    import psycopg

    tenant_id = uuid.uuid4()
    args = _args(tmp_path, dev=False, verify=str(tenant_id))

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def __init__(self) -> None:
            self._last = ""

        def execute(self, sql: str, params: tuple[str, ...] | None = None) -> None:
            self._last = sql

        def fetchone(self) -> tuple[Any, ...] | None:
            if "to_regclass" in self._last:
                return ("kompasos.x",)  # hər cədvəl mövcuddur
            if "count(*)" in self._last:
                return (0,)  # seed HEÇ VAXT işləməyib
            if "license_tenants" in self._last:
                return ("Embawood", "AKTIV")
            return ("Embawood", "AKTIV")

        def fetchall(self) -> list[tuple[str]]:
            # Reyestr TAMDIR: diqqət YALNIZ seed halqasına yönəlsin.
            root = Path(__file__).resolve().parents[2] / "database" / "migrations"
            return [(path.name,) for path in sorted(root.glob("[0-9][0-9][0-9]_*.sql"))]

    class _Connection:
        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def cursor(self) -> _Cursor:
            return _Cursor()

    original = psycopg.connect
    psycopg.connect = lambda _dsn, **_: _Connection()  # type: ignore[assignment,misc]
    try:
        code = onboard._verify(args, tenant_id)
    finally:
        psycopg.connect = original  # type: ignore[assignment]

    output = capsys.readouterr().out
    assert code == 1
    assert "Seed məlumatı" in output
    assert "BOŞ" in output
    # Reyestr və cədvəllər halqaları eyni çağırışda YAŞIL qalır — «hansı biri»
    # sualının cavabı məhz bu fərqdədir.
    assert "[OK    ] Miqrasiya reyestri" in output
    assert "[OK    ] Əsas cədvəllər" in output


def test_verify_rejects_a_malformed_tenant_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """UUID olmayan dəyər bazaya ÇATMADAN rədd edilir."""
    code = onboard.main(
        [
            "--tenant-dsn",
            _DSN,
            "--vendor-dsn",
            "postgresql://v:p@h:5432/postgres",
            "--verify",
            "belə-bir-uuid-yoxdur",
        ]
    )
    assert code == 2
    assert "keçərli UUID deyil" in capsys.readouterr().err
