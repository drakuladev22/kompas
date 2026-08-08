"""Plugin sandbox və imza testləri (Faza 2.7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.infrastructure.plugins import (
    ALLOWED_ENV_KEYS,
    SECRET_ENV_PREFIXES,
    PluginCapability,
    PluginError,
    PluginManifest,
    PluginPermissionError,
    PluginRequest,
    PluginSandbox,
    PluginSignatureError,
    PluginSignatureVerifier,
    PluginTimeoutError,
    SandboxPolicy,
    TrustedPublisher,
    TrustStore,
    build_sandbox_env,
    file_sha256,
    sign_plugin,
)

pytestmark = pytest.mark.unit


def make_manifest(**overrides: object) -> PluginManifest:
    defaults: dict[str, object] = {
        "name": "test-plugin",
        "version": "1.0.0",
        "publisher": "KompasOS Rəsmi",
        "capabilities": frozenset({PluginCapability.REPORT_TRANSFORM}),
        "entry_point": "main.py",
    }
    defaults.update(overrides)
    return PluginManifest(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def keypair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes_raw().hex()
    return private, public_hex


@pytest.fixture
def plugin_file(tmp_path: Path) -> Path:
    """stdin-dən JSON oxuyub stdout-a JSON yazan minimal plugin."""
    path = tmp_path / "main.py"
    path.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "print(json.dumps({'echo': request['payload'], 'ok': True}))\n",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


def test_manifest_requires_capabilities() -> None:
    with pytest.raises(PluginError, match="capability"):
        make_manifest(capabilities=frozenset())


def test_manifest_requires_name() -> None:
    with pytest.raises(PluginError, match="adı boş"):
        make_manifest(name="  ")


def test_manifest_serialises_deterministically() -> None:
    manifest = make_manifest(
        capabilities=frozenset({PluginCapability.RENDER_WIDGET, PluginCapability.REGISTER_PAGE})
    )
    # Capability-lər sıralanmış olmalıdır ki, imza determinstik olsun
    assert manifest.to_dict()["capabilities"] == ["register_page", "render_widget"]


# --------------------------------------------------------------------------- #
# İmza
# --------------------------------------------------------------------------- #


def test_valid_signature_accepted(
    plugin_file: Path, keypair: tuple[Ed25519PrivateKey, str]
) -> None:
    private, public_hex = keypair
    manifest = make_manifest()
    signature = sign_plugin(plugin_path=plugin_file, manifest=manifest, private_key=private)

    verifier = PluginSignatureVerifier(TrustStore([TrustedPublisher("KompasOS Rəsmi", public_hex)]))
    digest = verifier.verify(plugin_path=plugin_file, manifest=manifest, signature_hex=signature)

    assert digest == file_sha256(plugin_file)


def test_empty_trust_store_is_fail_closed(
    plugin_file: Path, keypair: tuple[Ed25519PrivateKey, str]
) -> None:
    """Konfiqurasiya edilməmiş truststore "hər şeyə icazə"yə çevrilməməlidir."""
    private, _ = keypair
    manifest = make_manifest()
    signature = sign_plugin(plugin_path=plugin_file, manifest=manifest, private_key=private)

    verifier = PluginSignatureVerifier(TrustStore())
    with pytest.raises(PluginSignatureError, match="fail-closed"):
        verifier.verify(plugin_path=plugin_file, manifest=manifest, signature_hex=signature)


def test_unknown_publisher_rejected(
    plugin_file: Path, keypair: tuple[Ed25519PrivateKey, str]
) -> None:
    private, public_hex = keypair
    manifest = make_manifest(publisher="Naməlum Şirkət")
    signature = sign_plugin(plugin_path=plugin_file, manifest=manifest, private_key=private)

    verifier = PluginSignatureVerifier(TrustStore([TrustedPublisher("KompasOS Rəsmi", public_hex)]))
    with pytest.raises(PluginSignatureError, match="etibarlı naşirlər"):
        verifier.verify(plugin_path=plugin_file, manifest=manifest, signature_hex=signature)


def test_tampered_file_breaks_signature(
    plugin_file: Path, keypair: tuple[Ed25519PrivateKey, str]
) -> None:
    """İmzalandıqdan SONRA kod dəyişdirilirsə yüklənmə bloklanmalıdır."""
    private, public_hex = keypair
    manifest = make_manifest()
    signature = sign_plugin(plugin_path=plugin_file, manifest=manifest, private_key=private)

    plugin_file.write_text("print('zərərli kod')\n", encoding="utf-8")

    verifier = PluginSignatureVerifier(TrustStore([TrustedPublisher("KompasOS Rəsmi", public_hex)]))
    with pytest.raises(PluginSignatureError, match="dəyişdirilib"):
        verifier.verify(plugin_path=plugin_file, manifest=manifest, signature_hex=signature)


def test_capability_escalation_breaks_signature(
    plugin_file: Path, keypair: tuple[Ed25519PrivateKey, str]
) -> None:
    """KRİTİK: manifestdə capability artırmaq imzanı pozmalıdır."""
    private, public_hex = keypair
    original = make_manifest(capabilities=frozenset({PluginCapability.REPORT_TRANSFORM}))
    signature = sign_plugin(plugin_path=plugin_file, manifest=original, private_key=private)

    escalated = make_manifest(
        capabilities=frozenset({PluginCapability.REPORT_TRANSFORM, PluginCapability.ERP_TRANSFORM})
    )
    verifier = PluginSignatureVerifier(TrustStore([TrustedPublisher("KompasOS Rəsmi", public_hex)]))

    with pytest.raises(PluginSignatureError, match="uyğun gəlmir"):
        verifier.verify(plugin_path=plugin_file, manifest=escalated, signature_hex=signature)


def test_malformed_signature_rejected(
    plugin_file: Path, keypair: tuple[Ed25519PrivateKey, str]
) -> None:
    _, public_hex = keypair
    verifier = PluginSignatureVerifier(TrustStore([TrustedPublisher("KompasOS Rəsmi", public_hex)]))
    with pytest.raises(PluginSignatureError, match="format"):
        verifier.verify(
            plugin_path=plugin_file,
            manifest=make_manifest(),
            signature_hex="bu-hex-deyil",
        )


def test_missing_file_rejected(tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str]) -> None:
    _, public_hex = keypair
    verifier = PluginSignatureVerifier(TrustStore([TrustedPublisher("KompasOS Rəsmi", public_hex)]))
    with pytest.raises(PluginSignatureError, match="tapılmadı"):
        verifier.verify(
            plugin_path=tmp_path / "yoxdur.py",
            manifest=make_manifest(),
            signature_hex="00" * 64,
        )


def test_invalid_public_key_rejected(plugin_file: Path) -> None:
    verifier = PluginSignatureVerifier(
        TrustStore([TrustedPublisher("KompasOS Rəsmi", "qırıq-açar")])
    )
    with pytest.raises(PluginSignatureError, match="açıq açarı"):
        verifier.verify(
            plugin_path=plugin_file,
            manifest=make_manifest(),
            signature_hex="00" * 64,
        )


# --------------------------------------------------------------------------- #
# Sandbox mühiti
# --------------------------------------------------------------------------- #


def test_secrets_never_reach_plugin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ƏSAS ZƏMANƏT: plugin prosesi sirrləri GÖRMÜR."""
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", "çox-gizli-açar")
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", "çox-gizli-pepper")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "gizli")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")

    env = build_sandbox_env()

    assert "KOMPASOS_FERNET_KEY" not in env
    assert "KOMPASOS_HASH_PEPPER" not in env
    assert "SUPABASE_SERVICE_ROLE_KEY" not in env
    assert "DATABASE_URL" not in env
    for value in env.values():
        assert "çox-gizli" not in value
        assert "postgresql://" not in value


def test_sandbox_env_is_whitelist_based(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yeni naməlum dəyişən DEFOLT olaraq ötürülmür."""
    monkeypatch.setenv("SOME_FUTURE_SECRET", "dəyər")
    env = build_sandbox_env()

    assert "SOME_FUTURE_SECRET" not in env
    assert set(env) <= {*ALLOWED_ENV_KEYS, "PYTHONIOENCODING", "PYTHONNOUSERSITE"}


def test_secret_prefixes_cover_known_families() -> None:
    for prefix in ("KOMPASOS_", "SUPABASE_", "DATABASE_"):
        assert prefix in SECRET_ENV_PREFIXES


# --------------------------------------------------------------------------- #
# Sandbox icrası
# --------------------------------------------------------------------------- #


def test_plugin_executes_and_returns_json(plugin_file: Path) -> None:
    sandbox = PluginSandbox(manifest=make_manifest(), plugin_path=plugin_file)

    response = sandbox.invoke(
        PluginRequest(capability=PluginCapability.REPORT_TRANSFORM, payload={"say": 42})
    )

    assert response.ok is True
    assert response.data is not None
    assert response.data["echo"] == {"say": 42}


def test_capability_not_in_manifest_denied(plugin_file: Path) -> None:
    """Whitelist: manifestdə olmayan capability çağırıla bilməz."""
    sandbox = PluginSandbox(manifest=make_manifest(), plugin_path=plugin_file)

    with pytest.raises(PluginPermissionError, match="capability"):
        sandbox.invoke(PluginRequest(capability=PluginCapability.ERP_TRANSFORM, payload={}))


def test_plugin_timeout_is_killed(tmp_path: Path) -> None:
    """Cavab verməyən plugin kiosk-u dondurmamalıdır."""
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    sandbox = PluginSandbox(
        manifest=make_manifest(),
        plugin_path=slow,
        policy=SandboxPolicy(
            timeout_seconds=1.0,
            allowed_capabilities=frozenset({PluginCapability.REPORT_TRANSFORM}),
        ),
    )

    with pytest.raises(PluginTimeoutError, match="cavab vermədi"):
        sandbox.invoke(PluginRequest(capability=PluginCapability.REPORT_TRANSFORM, payload={}))


def test_plugin_crash_returns_error_not_exception(tmp_path: Path) -> None:
    crashing = tmp_path / "crash.py"
    crashing.write_text("raise SystemExit(3)\n", encoding="utf-8")

    sandbox = PluginSandbox(manifest=make_manifest(), plugin_path=crashing)
    response = sandbox.invoke(
        PluginRequest(capability=PluginCapability.REPORT_TRANSFORM, payload={})
    )

    assert response.ok is False
    assert response.error is not None
    assert "kod 3" in response.error


def test_non_json_output_handled(tmp_path: Path) -> None:
    noisy = tmp_path / "noisy.py"
    noisy.write_text("print('bu JSON deyil')\n", encoding="utf-8")

    sandbox = PluginSandbox(manifest=make_manifest(), plugin_path=noisy)
    response = sandbox.invoke(
        PluginRequest(capability=PluginCapability.REPORT_TRANSFORM, payload={})
    )

    assert response.ok is False
    assert "JSON" in (response.error or "")


def test_oversized_output_rejected(tmp_path: Path) -> None:
    """Nəhəng cavabla host-un yaddaşını doldurmaq mümkün olmamalıdır."""
    flooder = tmp_path / "flood.py"
    flooder.write_text("import json\nprint(json.dumps({'x': 'A' * 200000}))\n", encoding="utf-8")

    sandbox = PluginSandbox(
        manifest=make_manifest(),
        plugin_path=flooder,
        policy=SandboxPolicy(
            timeout_seconds=10.0,
            max_output_bytes=1024,
            allowed_capabilities=frozenset({PluginCapability.REPORT_TRANSFORM}),
        ),
    )

    with pytest.raises(PluginError, match="limitini aşdı"):
        sandbox.invoke(PluginRequest(capability=PluginCapability.REPORT_TRANSFORM, payload={}))


def test_plugin_cannot_import_host_modules(tmp_path: Path) -> None:
    """Plugin host-un `src` paketini idxal edə bilməməlidir."""
    intruder = tmp_path / "intruder.py"
    intruder.write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "try:\n"
        "    from src.infrastructure.security.encryption import EncryptionService\n"
        "    print(json.dumps({'imported': True}))\n"
        "except Exception:\n"
        "    print(json.dumps({'imported': False}))\n",
        encoding="utf-8",
    )

    sandbox = PluginSandbox(manifest=make_manifest(), plugin_path=intruder)
    response = sandbox.invoke(
        PluginRequest(capability=PluginCapability.REPORT_TRANSFORM, payload={})
    )

    assert response.ok is True
    assert response.data is not None
    assert response.data["imported"] is False


def test_sandbox_repr_lists_capabilities(plugin_file: Path) -> None:
    sandbox = PluginSandbox(manifest=make_manifest(), plugin_path=plugin_file)
    assert "report_transform" in repr(sandbox)


def test_canonical_payload_is_stable(plugin_file: Path) -> None:
    """Eyni məzmun HƏMİŞƏ eyni baytları verməlidir (imza determinizmi)."""
    from src.infrastructure.plugins import canonical_payload

    manifest = make_manifest()
    digest = file_sha256(plugin_file)

    first = canonical_payload(file_digest=digest, manifest=manifest)
    second = canonical_payload(file_digest=digest, manifest=make_manifest())

    assert first == second
    assert json.loads(first)["file_sha256"] == digest
