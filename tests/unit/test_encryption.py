"""Fernet şifrələmə və açar idarəetməsi testləri (spesifikasiya bölmə 2)."""

from __future__ import annotations

import pytest

from src.infrastructure.security.encryption import (
    ChainedKeyProvider,
    EncryptionService,
    EnvironmentKeyProvider,
    KeyMaterial,
    WindowsDpapiKeyProvider,
    generate_key,
)
from src.shared.exceptions import DecryptionError, EncryptionKeyError

pytestmark = pytest.mark.unit


def test_generate_key_is_valid() -> None:
    key = generate_key()
    assert len(key) == 44
    EncryptionService(_StaticProvider(KeyMaterial(primary=key))).encrypt("x")


class _StaticProvider:
    name = "static"

    def __init__(self, material: KeyMaterial | None) -> None:
        self._material = material

    def load(self) -> KeyMaterial | None:
        return self._material


def test_encrypt_decrypt_roundtrip(encryption_service: EncryptionService) -> None:
    plaintext = "1C-Server-Parolu-Şifrə-ƏÖÜĞIİ"
    token = encryption_service.encrypt(plaintext)

    assert token != plaintext
    assert encryption_service.decrypt(token) == plaintext


def test_ciphertext_is_not_deterministic(encryption_service: EncryptionService) -> None:
    """Eyni mətn iki dəfə şifrələnəndə fərqli token verməlidir (IV təsadüfidir)."""
    assert encryption_service.encrypt("eyni") != encryption_service.encrypt("eyni")


def test_encrypt_json_roundtrip(encryption_service: EncryptionService) -> None:
    config = {"host": "10.0.0.5", "port": 1541, "user": "erp_sync"}
    token = encryption_service.encrypt_json(config)

    assert encryption_service.decrypt_json(token) == config


def test_missing_key_raises() -> None:
    service = EncryptionService(_StaticProvider(None))

    with pytest.raises(EncryptionKeyError):
        service.encrypt("x")
    assert service.is_configured is False


def test_invalid_key_format_raises() -> None:
    service = EncryptionService(_StaticProvider(KeyMaterial(primary="çox-qısa-açar")))

    with pytest.raises(EncryptionKeyError):
        service.encrypt("x")


def test_wrong_key_cannot_decrypt() -> None:
    writer = EncryptionService(_StaticProvider(KeyMaterial(primary=generate_key())))
    reader = EncryptionService(_StaticProvider(KeyMaterial(primary=generate_key())))
    token = writer.encrypt("gizli")

    with pytest.raises(DecryptionError):
        reader.decrypt(token)


def test_key_rotation_reads_old_tokens() -> None:
    old_key, new_key = generate_key(), generate_key()

    old_service = EncryptionService(_StaticProvider(KeyMaterial(primary=old_key)))
    token = old_service.encrypt("köhnə-məlumat")

    rotated = EncryptionService(_StaticProvider(KeyMaterial(primary=new_key, previous=(old_key,))))

    # Köhnə token hələ də oxunur...
    assert rotated.decrypt(token) == "köhnə-məlumat"

    # ...və cari açara keçirilə bilir.
    new_token = rotated.rotate_token(token)
    only_new = EncryptionService(_StaticProvider(KeyMaterial(primary=new_key)))
    assert only_new.decrypt(new_token) == "köhnə-məlumat"


def test_environment_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    primary, previous = generate_key(), generate_key()
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", primary)
    monkeypatch.setenv("KOMPASOS_FERNET_KEY_PREVIOUS", f"{previous}, ")

    material = EnvironmentKeyProvider().load()

    assert material is not None
    assert material.primary == primary
    assert material.previous == (previous,)
    assert material.source == "environment"


def test_environment_provider_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOMPASOS_FERNET_KEY", raising=False)
    assert EnvironmentKeyProvider().load() is None


def test_chained_provider_prefers_first() -> None:
    first, second = generate_key(), generate_key()
    chain = ChainedKeyProvider(
        [
            _StaticProvider(None),
            _StaticProvider(KeyMaterial(primary=first)),
            _StaticProvider(KeyMaterial(primary=second)),
        ]
    )

    material = chain.load()
    assert material is not None
    assert material.primary == first


def test_chained_provider_requires_members() -> None:
    with pytest.raises(ValueError, match="Ən azı bir"):
        ChainedKeyProvider([])


def test_key_material_repr_is_masked() -> None:
    material = KeyMaterial(primary=generate_key(), previous=(generate_key(),))
    text = repr(material)

    assert "REDACTED" in text
    assert material.primary not in text


def test_is_token_detection(encryption_service: EncryptionService) -> None:
    token = encryption_service.encrypt("x")
    assert EncryptionService.is_token(token) is True
    assert EncryptionService.is_token("adi-mətn") is False
    assert EncryptionService.is_token("") is False


def test_key_source_reported(encryption_service: EncryptionService) -> None:
    assert encryption_service.key_source == "environment"


def test_reload_picks_up_new_key(monkeypatch: pytest.MonkeyPatch) -> None:
    first = generate_key()
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", first)
    monkeypatch.delenv("KOMPASOS_FERNET_KEY_PREVIOUS", raising=False)
    service = EncryptionService()
    token = service.encrypt("məlumat")

    second = generate_key()
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", second)
    monkeypatch.setenv("KOMPASOS_FERNET_KEY_PREVIOUS", first)
    service.reload()

    assert service.decrypt(token) == "məlumat"


def test_dpapi_provider_inactive_off_windows() -> None:
    """Windows-dan kənarda provayder passiv qalmalıdır (CI Linux runner)."""
    provider = WindowsDpapiKeyProvider()
    if not provider.is_supported:
        assert provider.load() is None
        with pytest.raises(EncryptionKeyError):
            provider.store(KeyMaterial(primary=generate_key()))


# --------------------------------------------------------------------------- #
# AES-256-GCM-ə xas davranış (SEC-002)
# --------------------------------------------------------------------------- #


def test_token_has_versioned_format(encryption_service: EncryptionService) -> None:
    token = encryption_service.encrypt("dəyər")
    version, key_id, payload = token.split(".", 2)

    assert version == "v1"
    assert len(key_id) == 8
    assert payload


def test_key_id_is_stable_and_not_the_key(fernet_key: str) -> None:
    service = EncryptionService(_StaticProvider(KeyMaterial(primary=fernet_key)))
    key_id = service.primary_key_id

    assert key_id is not None
    assert key_id not in fernet_key
    assert fernet_key not in (service.encrypt("x"))


def test_aad_context_binding_is_enforced(encryption_service: EncryptionService) -> None:
    """Şifrəli dəyəri başqa sətrə köçürmək (cut-and-paste) mümkün olmamalıdır."""
    token = encryption_service.encrypt("server-parolu", context="erp_server:1")

    assert encryption_service.decrypt(token, context="erp_server:1") == "server-parolu"

    with pytest.raises(DecryptionError):
        encryption_service.decrypt(token, context="erp_server:2")

    with pytest.raises(DecryptionError):
        encryption_service.decrypt(token)  # kontekstsiz də açılmamalıdır


def test_context_free_token_needs_no_context(
    encryption_service: EncryptionService,
) -> None:
    token = encryption_service.encrypt("sadə")
    assert encryption_service.decrypt(token) == "sadə"


def test_encrypt_json_with_context(encryption_service: EncryptionService) -> None:
    config = {"host": "10.0.0.5", "port": 1541}
    token = encryption_service.encrypt_json(config, context="erp_server:7")

    assert encryption_service.decrypt_json(token, context="erp_server:7") == config
    with pytest.raises(DecryptionError):
        encryption_service.decrypt_json(token, context="erp_server:8")


def test_unknown_key_id_gives_actionable_error() -> None:
    writer = EncryptionService(_StaticProvider(KeyMaterial(primary=generate_key())))
    reader = EncryptionService(_StaticProvider(KeyMaterial(primary=generate_key())))
    token = writer.encrypt("gizli")

    with pytest.raises(DecryptionError) as exc_info:
        reader.decrypt(token)

    assert "KOMPASOS_FERNET_KEY_PREVIOUS" in str(exc_info.value)


def test_legacy_fernet_token_still_readable(fernet_key: str) -> None:
    """Köhnə quraşdırmalardakı Fernet token-ləri oxunmağa davam etməlidir."""
    from cryptography.fernet import Fernet

    # QEYD: bytes literalı yalnız ASCII saxlaya bilər — .encode() istifadə olunur.
    legacy_token = Fernet(fernet_key.encode("ascii")).encrypt("köhnə-sirr".encode()).decode()
    service = EncryptionService(_StaticProvider(KeyMaterial(primary=fernet_key)))

    assert service.decrypt(legacy_token) == "köhnə-sirr"
    assert service.needs_rotation(legacy_token) is True


def test_legacy_token_migrates_to_aesgcm(fernet_key: str) -> None:
    from cryptography.fernet import Fernet

    legacy_token = Fernet(fernet_key.encode("ascii")).encrypt(b"miqrasiya").decode()
    service = EncryptionService(_StaticProvider(KeyMaterial(primary=fernet_key)))

    migrated = service.rotate_token(legacy_token)

    assert migrated.startswith("v1.")
    assert service.decrypt(migrated) == "miqrasiya"
    assert service.needs_rotation(migrated) is False


def test_needs_rotation_detects_old_key() -> None:
    old_key, new_key = generate_key(), generate_key()
    old_service = EncryptionService(_StaticProvider(KeyMaterial(primary=old_key)))
    token = old_service.encrypt("məlumat")

    rotated = EncryptionService(_StaticProvider(KeyMaterial(primary=new_key, previous=(old_key,))))

    assert rotated.needs_rotation(token) is True
    assert rotated.needs_rotation(rotated.rotate_token(token)) is False


def test_tampered_ciphertext_is_rejected(encryption_service: EncryptionService) -> None:
    """GCM autentifikasiya teqi dəyişdirilmiş məlumatı tutmalıdır."""
    token = encryption_service.encrypt("toxunulmaz")
    version, key_id, payload = token.split(".", 2)
    flipped = "A" if payload[10] != "A" else "B"
    tampered = f"{version}.{key_id}.{payload[:10]}{flipped}{payload[11:]}"

    with pytest.raises(DecryptionError):
        encryption_service.decrypt(tampered)


def test_malformed_token_is_rejected(encryption_service: EncryptionService) -> None:
    with pytest.raises(DecryptionError):
        encryption_service.decrypt("v1.qırıq")


def test_is_token_recognises_both_formats(
    encryption_service: EncryptionService, fernet_key: str
) -> None:
    from cryptography.fernet import Fernet

    assert EncryptionService.is_token(encryption_service.encrypt("x")) is True
    assert (
        EncryptionService.is_token(Fernet(fernet_key.encode("ascii")).encrypt(b"x").decode())
        is True
    )
    assert EncryptionService.is_token("v1.short") is False
