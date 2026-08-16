"""Bağlantı konfiqurasiya faylı — parol diskdə AÇIQ qalmır (DB-4 Faza 2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL LAZIM OLDU
──────────────────────────────────────────────────────────────────────────────
Paketlənmiş `.exe` DSN-i yalnız `DATABASE_URL` mühit dəyişənindən oxuyurdu,
tətbiq isə `.env` faylını OXUMUR. Nəticədə Start menyusundan açılan `.exe`-də
dəyişən boş olur və bağlantı ÜMUMİYYƏTLƏ qurula bilmirdi — müştəri maşınında
proqram «Baza bağlantısı qurula bilmədi» ilə dayanırdı.

Testlərin əsas hədəfi ORDUR: fayl yolu işləyir, parol diskdə açıq QALMIR və
mühit dəyişəni faylı HƏMİŞƏ üstələyir.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.infrastructure.config.connection_file import (
    CONNECTION_FILE_ENV,
    ConnectionFileError,
    ConnectionSettings,
    connection_file_path,
    load_settings,
    save_settings,
)

pytestmark = pytest.mark.unit

_SETTINGS = ConnectionSettings(
    host="aws-0-eu-central-1.pooler.supabase.com",
    port=5432,
    database="postgres",
    username="postgres.abcdefgh",
    password="p@ss/word#1",
)


@pytest.fixture(autouse=True)
def _isolated_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Şifrələmə açarı testdə mühitdən gəlir — DPAPI (Windows API) çağırılmır.

    `EncryptionService` zənciri `EnvironmentKeyProvider` → DPAPI sırasındadır,
    yəni dəyişən verildikdə OS API-yə heç vaxt çatmır. Bu, testi platformadan
    asılı olmaqdan xilas edir.
    """
    from src.infrastructure.security.encryption import generate_key

    monkeypatch.setenv("KOMPASOS_FERNET_KEY", generate_key())


def test_a_saved_password_is_not_readable_in_the_file(tmp_path: Path) -> None:
    """Faylın XAM mətnində parol keçməməlidir — testin ƏSAS iddiası budur."""
    target = tmp_path / "connection.json"
    save_settings(_SETTINGS, target)

    raw = target.read_text(encoding="utf-8")
    assert _SETTINGS.password not in raw
    # Host/istifadəçi AÇIQ qalır: quraşdırıcı «hansı serverə baxır?» sualını
    # faylı deşifrələmədən cavablaya bilməlidir (bax modul başlığı).
    assert _SETTINGS.host in raw
    assert _SETTINGS.username in raw
    assert json.loads(raw)["password_encrypted"]


def test_a_saved_configuration_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "connection.json"
    save_settings(_SETTINGS, target)

    loaded = load_settings(target)
    assert loaded == _SETTINGS


def test_the_dsn_url_encodes_credentials() -> None:
    """`@`, `/`, `#` olan parol DSN-i SÜKUTLA sındırmamalıdır.

    Kodlanmasaydı, `p@ss/word#1` parolu DSN-i başqa hosta işarə edən sətrə
    çevirərdi — və nəticə «host tapılmadı» kimi görünərdi, parol səhvi kimi
    yox.
    """
    dsn = _SETTINGS.dsn()
    assert "p%40ss%2Fword%231" in dsn
    assert dsn.startswith("postgresql://postgres.abcdefgh:")
    assert "@aws-0-eu-central-1.pooler.supabase.com:5432/postgres" in dsn


def test_a_dsn_can_be_parsed_back_into_settings() -> None:
    """Ekran mövcud dəyəri göstərə bilməlidir."""
    restored = ConnectionSettings.from_dsn(_SETTINGS.dsn())
    assert restored.host == _SETTINGS.host
    assert restored.username == _SETTINGS.username
    assert restored.password == _SETTINGS.password


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    """Konfiqurasiya edilməmiş quraşdırma GÖZLƏNİLƏN haldır."""
    assert load_settings(tmp_path / "yoxdur.json") is None


def test_a_corrupt_file_reports_the_reason(tmp_path: Path) -> None:
    """«Konfiqurasiya yoxdur» ilə «konfiqurasiya sınıqdır» EYNİ sayılmır.

    Sükutla `None` qaytarsaydıq, sınıq fayl «yeni quraşdırma» kimi görünər və
    istifadəçi mövcud ayarlarını itirdiyini bilməzdi.
    """
    target = tmp_path / "connection.json"
    target.write_text('{"host": "x", "port":', encoding="utf-8")

    with pytest.raises(ConnectionFileError):
        load_settings(target)


def test_an_undecryptable_password_reports_the_reason(tmp_path: Path) -> None:
    """Açar dəyişibsə səbəb AÇIQ deyilir — «parol səhvdir» kimi görünməməlidir."""
    target = tmp_path / "connection.json"
    save_settings(_SETTINGS, target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["password_encrypted"] = "v1:korlanmis-token"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConnectionFileError) as error:
        load_settings(target)
    assert "parol" in error.value.user_message.lower()


def test_the_environment_variable_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DATABASE_URL` varsa fayl OXUNMUR — CI/inkişaf mühiti sabit qalmalıdır."""
    from src.infrastructure.persistence.connection import build_dsn_from_env

    target = tmp_path / "connection.json"
    save_settings(_SETTINGS, target)
    monkeypatch.setenv(CONNECTION_FILE_ENV, str(target))
    monkeypatch.setenv("DATABASE_URL", "postgresql://env_user:env@env-host:5432/envdb")

    assert build_dsn_from_env() == "postgresql://env_user:env@env-host:5432/envdb"


def test_the_file_is_used_when_the_environment_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paketlənmiş `.exe`-nin yolu: dəyişən boşdur, fayl var."""
    from src.infrastructure.persistence.connection import build_dsn_from_env

    target = tmp_path / "connection.json"
    save_settings(_SETTINGS, target)
    monkeypatch.setenv(CONNECTION_FILE_ENV, str(target))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert build_dsn_from_env() == _SETTINGS.dsn()


def test_neither_source_produces_an_actionable_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mesaj istifadəçini EKRANA yönləndirməlidir, mühit dəyişəninə yox.

    «`DATABASE_URL` təyin edin» göstərişi mağaza işçisi üçün mənasızdır — o,
    nə mühit dəyişəninin nə olduğunu bilir, nə də onu təyin edə bilər.
    """
    from src.infrastructure.persistence.connection import ConfigurationError, build_dsn_from_env

    monkeypatch.setenv(CONNECTION_FILE_ENV, str(tmp_path / "yoxdur.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError) as error:
        build_dsn_from_env()
    assert "Bağlantı Ayarları" in error.value.user_message


def test_the_default_path_is_machine_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defolt yol `%PROGRAMDATA%`-dədir — hər istifadəçi EYNİ faylı görür.

    `%LOCALAPPDATA%` olsaydı, kiosk nəzarətçisi başqa hesabla işlədiyində
    «konfiqurasiya yoxdur» görərdi (bax modul başlığı).
    """
    monkeypatch.delenv(CONNECTION_FILE_ENV, raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(Path(os.sep) / "ProgramData"))

    path = connection_file_path()
    assert path.parts[-2:] == ("KompasOS", "connection.json")
    assert "ProgramData" in str(path)
