"""Təmiz quraşdırmada şifrələmə açarı — SETUP-2.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
Müştəri maşınında NƏ `KOMPASOS_FERNET_KEY` var (paketə `.env` düşmür), NƏ də
DPAPI blobu — onu heç kim yaratmırdı (`WindowsDpapiKeyProvider.store()` bütün
kod bazasında ÇAĞIRILMAYAN metod idi). Nəticədə «Bağlantı Ayarları» ekranından
«Yadda saxla» düyməsi `EncryptionKeyError` ilə dayanırdı, kontroller isə
YALNIZ `ConnectionFileError`-u tuturdu — istisna Qt siqnal işləyicisindən
çıxıb `stderr`-ə düşürdü və istifadəçi HEÇ NƏ görmürdü.

Yəni quraşdırılmış proqram heç vaxt konfiqurasiya edilə bilmirdi və səbəb
ekranda görünmürdü. Bu fayl hər iki qatı bağlayır.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from src.infrastructure.security.encryption import (
    EncryptionService,
    KeyMaterial,
    WindowsDpapiKeyProvider,
    ensure_machine_key,
    generate_key,
)

pytestmark = pytest.mark.unit


class _FakeDpapi:
    """DPAPI-siz platformalarda da işləyən sadə blob saxlayıcısı.

    `WindowsDpapiKeyProvider`-in FAKTİKİ `CryptProtectData` çağırışını
    əvəzləyir: test qərarı «açar yaradıldımı?» sualıdır, Windows API-nin
    özü deyil (o, `test_encryption.py`-də ayrıca yoxlanılır).
    """

    def __init__(self, path: Path, *, supported: bool = True) -> None:
        self.blob_path = path
        self.is_supported = supported
        self.stored: KeyMaterial | None = None

    def load(self) -> KeyMaterial | None:
        return self.stored

    def store(self, material: KeyMaterial) -> Path:
        self.stored = material
        self.blob_path.parent.mkdir(parents=True, exist_ok=True)
        self.blob_path.write_bytes(b"dpapi-blob")
        return self.blob_path


def test_a_clean_install_gets_a_key_on_the_first_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nə mühit açarı, nə blob — ilk yazı açarı YARATMALIDIR."""
    monkeypatch.delenv("KOMPASOS_FERNET_KEY", raising=False)
    provider = _FakeDpapi(tmp_path / "kompasos.key")

    created = ensure_machine_key(provider)  # type: ignore[arg-type]

    assert created is True
    assert provider.stored is not None
    assert provider.blob_path.exists()


def test_the_key_is_created_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """İdempotent: ikinci çağırış MÖVCUD açarı əvəz etməməlidir.

    Əvəz etsəydi, hər yadda saxlama əvvəlki şifrəli dəyərləri OXUNMAZ edərdi.
    """
    monkeypatch.delenv("KOMPASOS_FERNET_KEY", raising=False)
    provider = _FakeDpapi(tmp_path / "kompasos.key")
    ensure_machine_key(provider)  # type: ignore[arg-type]
    first = provider.stored

    created_again = ensure_machine_key(provider)  # type: ignore[arg-type]

    assert created_again is False
    assert provider.stored is first


def test_the_environment_key_wins_and_no_blob_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """İnkişaf maşınında ikinci açar mənbəyi YARADILMIR.

    Yaradılsaydı, «hansı açarla şifrələnib?» sualı ortaya çıxardı: zəncir
    mühit açarını birinci yoxlayır, blob isə sükutla istifadəsiz qalardı.
    """
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", generate_key())
    provider = _FakeDpapi(tmp_path / "kompasos.key")

    assert ensure_machine_key(provider) is False  # type: ignore[arg-type]
    assert provider.stored is None
    assert not provider.blob_path.exists()


def test_an_unsupported_platform_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux/CI-da DPAPI yoxdur — funksiya sükutla `False` qaytarır.

    İstisna atsaydı, `save_settings()` həmin platformalarda ÜMUMİYYƏTLƏ
    işləməzdi; halbuki orada mühit açarı var.
    """
    monkeypatch.delenv("KOMPASOS_FERNET_KEY", raising=False)
    provider = _FakeDpapi(tmp_path / "kompasos.key", supported=False)

    assert ensure_machine_key(provider) is False  # type: ignore[arg-type]
    assert provider.stored is None


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI yalnız Windows-dadır")
def test_the_real_provider_targets_the_shared_folder() -> None:
    """Blob PAYLAŞILAN qovluqdadır — ikinci Windows hesabı da oxumalıdır.

    İstifadəçi əhatəli yol (`%LOCALAPPDATA%`) seçilsəydi, eyni kompüterin
    ikinci kassiri `connection.json`-u aça bilməzdi.
    """
    provider = WindowsDpapiKeyProvider(machine_scope=True)

    assert provider.blob_path.name == "kompasos.key"
    assert "ProgramData" in str(provider.blob_path)


def test_saving_a_connection_provisions_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UÇTAN-UCA: `save_settings()` açarsız maşında da işləməlidir.

    Bu, qüsurun FAKTİKİ ssenarisidir — ekranın «Yadda saxla» düyməsi məhz
    bu funksiyanı çağırır.
    """
    from src.infrastructure.config import connection_file as module

    monkeypatch.delenv("KOMPASOS_FERNET_KEY", raising=False)
    monkeypatch.delenv(module.CONNECTION_FILE_ENV, raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))

    provider = _FakeDpapi(tmp_path / "KompasOS" / "kompasos.key")
    calls: list[str] = []

    def fake_ensure() -> None:
        calls.append("ensure")
        ensure_machine_key(provider)  # type: ignore[arg-type]

    # Şifrələmə servisi sahtə blobdan qidalanır — belə ki, test həqiqi
    # Windows API-sindən asılı olmasın, lakin ZƏNCİRİN SIRASI qorunsun.
    monkeypatch.setattr(module, "_ensure_key", fake_ensure)
    monkeypatch.setattr(module, "_cipher", lambda: EncryptionService(_StubProvider(provider)))

    settings = module.ConnectionSettings(
        host="db.example.com",
        port=5432,
        database="postgres",
        username="app",
        password="p@ss/word#1",
    )
    target = module.save_settings(settings)

    assert calls == ["ensure"], "Açar YARADILMALI idi"
    restored = module.load_settings(target)
    assert restored is not None
    assert restored.password == settings.password
    assert settings.password not in target.read_text(encoding="utf-8")


class _StubProvider:
    """`_FakeDpapi`-nin saxladığı açarı `EncryptionService`-ə verir."""

    name = "stub"

    def __init__(self, dpapi: _FakeDpapi) -> None:
        self._dpapi = dpapi

    def load(self) -> KeyMaterial | None:
        return self._dpapi.load()


def test_the_screen_shows_every_save_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kontroller DAR tutucu ilə şifrələmə xətasını buraxırdı.

    Qt siqnal işləyicisindən çıxan istisna yalnız `stderr`-ə düşür — yəni
    istifadəçi düyməni basır və HEÇ NƏ baş vermir. Ən pis nasazlıq növüdür:
    səbəb də görünmür, nəticə də.
    """
    from src.presentation.controllers import connection_settings as module
    from src.shared.exceptions import KompasOSError

    class _KeyMissingError(KompasOSError):
        user_message = "Şifrələmə açarı tapılmadı."

    class _Screen:
        def __init__(self) -> None:
            self.errors: list[str] = []
            self.busy: list[bool] = []

        def set_error(self, message: str) -> None:
            self.errors.append(message)

        def set_busy(self, busy: bool) -> None:
            self.busy.append(busy)

        def set_status(self, message: str) -> None:
            return None

    screen = _Screen()
    controller = module.ConnectionSettingsController.__new__(module.ConnectionSettingsController)
    monkeypatch.setattr(module.ConnectionSettingsController, "_probe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        module.ConnectionSettingsController, "_existing_password", lambda _self: "x"
    )
    monkeypatch.setattr(
        "src.infrastructure.config.connection_file.save_settings",
        _raise(_KeyMissingError("açar yoxdur")),
    )

    controller._on_submit(screen, _PAYLOAD)  # type: ignore[arg-type]

    assert screen.errors == ["Şifrələmə açarı tapılmadı."]
    assert screen.busy[-1] is False, "Məşğulluq göstəricisi söndürülməlidir"


_PAYLOAD: dict[str, Any] = {
    "host": "db.example.com",
    "port": "5432",
    "database": "postgres",
    "username": "app",
    "password": "p@ss",
    "sslmode": "require",
}


def _raise(error: Exception) -> Any:
    def _inner(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _inner
