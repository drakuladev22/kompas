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
    # AF-3 (fail-closed): `_SETTINGS` istifadəçi adı OWNER rolundadır
    # (`postgres.abcdefgh`) və `build_dsn_from_env` onu artıq İSTEHSALATDA
    # RƏDD EDİR. Bu testin predmeti isə ROL deyil, MƏNBƏDİR — «dəyişən boşdur,
    # fayl oxunur». Ona görə mühit açıq şəkildə DEV elan olunur; owner rolunun
    # istehsalatda dayandırılması AYRICA testdə ölçülür.
    monkeypatch.setenv("KOMPASOS_ENV", "DEV")

    assert build_dsn_from_env() == _SETTINGS.dsn()


def test_neither_source_produces_an_actionable_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mesaj İCRA EDİLƏ BİLƏN addım göstərməlidir, mühit dəyişəni deyil.

    «`DATABASE_URL` təyin edin» göstərişi mağaza işçisi üçün mənasızdır — o,
    nə mühit dəyişəninin nə olduğunu bilir, nə də onu təyin edə bilər.

    ƏVVƏL BURADA «Bağlantı Ayarları» EKRANI ADLANIRDI. Həmin ekran fatal
    başlanğıc yolundan ARTIQ AÇILMIR (`presentation/app.py` — «Yenidən Cəhd
    Et» yalnız yeni cəhddir, forma mağaza işçisinin qarşısına çıxmır), yəni
    köhnə mətn istifadəçini ÇATA BİLMƏDİYİ bir yerə göndərirdi: testin
    tələbi («icra edilə bilən») formal olaraq ödənsə də, əməli olaraq
    POZULURDU. İndi mətn dəstəyə yönəldir — mağaza işçisinin HƏQİQƏTƏN
    edə biləcəyi yeganə addım budur. Texnikin yolu isə `Ctrl+Shift+K`
    Bərpa Konsoludur və o, qəsdən burada adlanmır (gizli qalır).
    """
    from src.infrastructure.persistence.connection import ConfigurationError, build_dsn_from_env

    monkeypatch.setenv(CONNECTION_FILE_ENV, str(tmp_path / "yoxdur.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError) as error:
        build_dsn_from_env()
    message = error.value.user_message
    assert "texniki dəstək" in message
    assert "DATABASE_URL" not in message
    # ÇATILA BİLMƏYƏN ekranın adı mesajda OLMAMALIDIR (bax docstring).
    assert "Bağlantı Ayarları" not in message


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


# --------------------------------------------------------------------------- #
# Setup ilə quraşdırma: axtarış SIRASI (SETUP-1 Faza 1)
#
# OXU `.exe`-nin yanından BAŞLAYIR, YAZI isə həmişə `ProgramData`-ya gedir.
# Asimmetriya qəsdəndir və hər iki tərəfin öz səbəbi var:
#
#   * OXU — dəstək axını konfiqurasiyanı AnyDesk ilə `.exe` qovluğuna
#     köçürür. `--onedir` paketində orada onsuz da 100+ fayl var, yəni
#     config gözə dəymir və köçürmə ən qısa yoldur.
#   * YAZI — `C:\Program Files\` standart istifadəçi üçün YAZILA BİLMİR
#     (UAC). Konfiqurasiya ekranı ora yazmağa çalışsaydı, icazə xətası ilə
#     dayanardı.
# --------------------------------------------------------------------------- #


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Üç axtarış yerini müvəqqəti qovluqlara bağlayır."""
    from src.infrastructure.config import connection_file as module

    program_data = tmp_path / "ProgramData"
    app_data = tmp_path / "AppData"
    beside_exe = tmp_path / "portativ"
    for folder in (program_data, app_data, beside_exe):
        folder.mkdir()

    monkeypatch.delenv(CONNECTION_FILE_ENV, raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(program_data))
    monkeypatch.setenv("APPDATA", str(app_data))
    monkeypatch.setattr(module, "deployment_root", lambda: beside_exe)
    return {
        "program_data": program_data / "KompasOS" / "connection.json",
        "app_data": app_data / "KompasOS" / "connection.json",
        "beside_exe": beside_exe / "connection.json",
    }


def test_the_search_order_starts_beside_the_executable(_clean_env: dict[str, Path]) -> None:
    """Sıra təsadüfi deyil: dəstək axını faylı `.exe` qovluğuna qoyur."""
    from src.infrastructure.config.connection_file import connection_search_paths

    assert connection_search_paths() == [
        _clean_env["beside_exe"],
        _clean_env["program_data"],
        _clean_env["app_data"],
    ]


def test_the_environment_override_replaces_the_whole_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Açıq göstərilən yol axtarışı BİTİRİR — testlər və xüsusi quraşdırma."""
    from src.infrastructure.config.connection_file import connection_search_paths

    monkeypatch.setenv(CONNECTION_FILE_ENV, str(tmp_path / "xüsusi.json"))

    assert connection_search_paths() == [tmp_path / "xüsusi.json"]


def test_a_file_beside_the_exe_is_still_found(_clean_env: dict[str, Path]) -> None:
    """Portativ quraşdırma POZULMUR — köhnə davranış saxlanılır."""
    target = _clean_env["beside_exe"]
    save_settings(_SETTINGS, target)

    loaded = load_settings()

    assert loaded is not None
    assert loaded.host == _SETTINGS.host


def test_the_copy_beside_the_exe_wins_when_two_exist(_clean_env: dict[str, Path]) -> None:
    """İki nüsxə varsa qərar BİRMƏNALI olmalıdır.

    Qalib `.exe`-nin yanındakıdır, çünki dəstək məhz oranı əl ilə düzəldir:
    əks halda texnik faylı köçürər, proqram isə köhnə `ProgramData` nüsxəsini
    oxumağa davam edər və «düzəltdim, dəyişmədi» vəziyyəti yaranardı.

    Qarşı risk (köhnə fayl `.exe` yanında qalıb yenisini kölgələyir) EKRANDA
    görünür: Bağlantı Ayarları diaqnostikası FAKTİKİ işlədilən yolu yazır.
    """
    save_settings(_SETTINGS, _clean_env["beside_exe"])
    save_settings(
        ConnectionSettings(
            host="program-data.example",
            port=5432,
            database="postgres",
            username="postgres",
            password="x",
        ),
        _clean_env["program_data"],
    )

    loaded = load_settings()

    assert loaded is not None
    assert loaded.host == _SETTINGS.host


def test_the_user_level_copy_is_used_when_program_data_has_none(
    _clean_env: dict[str, Path],
) -> None:
    """ProgramData əlçatmaz olan maşında (siyasət/UAC) proqram dayanmır."""
    save_settings(_SETTINGS, _clean_env["app_data"])

    loaded = load_settings()

    assert loaded is not None
    assert loaded.host == _SETTINGS.host


def test_writing_always_targets_program_data(_clean_env: dict[str, Path]) -> None:
    """Oxu `.exe` yanından gəlsə belə YAZI paylaşılan yerə gedir.

    Əks halda konfiqurasiya ekranı `Program Files`-a yazmağa çalışar və
    standart istifadəçidə icazə xətası ilə dayanardı — SETUP-1-in həll etdiyi
    problemin məhz özü.
    """
    save_settings(_SETTINGS, _clean_env["beside_exe"])

    written = save_settings(_SETTINGS)

    assert written == _clean_env["program_data"]
    assert written.is_file()


def test_nothing_anywhere_is_still_not_an_error(_clean_env: dict[str, Path]) -> None:
    """Konfiqurasiya edilməmiş quraşdırma gözlənilən haldır (bax `load_settings`)."""
    assert load_settings() is None
