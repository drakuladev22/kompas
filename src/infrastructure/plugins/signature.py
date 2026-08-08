"""Plugin rəqəmsal imzasının yoxlanması (spesifikasiya bölmə 1) — Faza 2.7.

ALQORİTM: **Ed25519** — RSA-dan seçilmə səbəbləri:
    * imza cəmi 64 bayt (RSA-2048-də 256 bayt);
    * yoxlama qat-qat sürətlidir (tətbiq açılışını ləngitmir);
    * yanlış parametr seçmək mümkün deyil (RSA-da açar ölçüsü/padding
      seçimi səhv edilə bilər).

ETİBAR MODELİ: yalnız `TrustStore`-dakı açıq açarlar etibarlıdır. Açıq açar
tətbiqlə birlikdə paylanır (`.exe` Authenticode ilə imzalandığı üçün onu
dəyişdirmək öz-özlüyündə aşkarlana bilir).

İMZALANAN NƏDİR: plugin faylının SHA-256 daycesti + manifestin kanonik
JSON-u. Beləliklə nə kod, nə də elan edilmiş capability-lər imzadan sonra
dəyişdirilə bilməz — capability-ni dəyişmək imzanı pozur.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from src.infrastructure.plugins.contracts import PluginManifest, PluginSignatureError
from src.shared.logger import LogChannel, get_logger

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


def canonical_payload(*, file_digest: str, manifest: PluginManifest) -> bytes:
    """İmzalanan baytları determinstik şəkildə qurur.

    `sort_keys=True` + `separators` — eyni məzmun HƏMİŞƏ eyni baytları verir,
    əks halda lüğət sırası dəyişəndə imza yanlış olardı.
    """
    document = {
        "file_sha256": file_digest,
        "manifest": manifest.to_dict(),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def file_sha256(path: Path) -> str:
    """Plugin faylının SHA-256 daycesti (böyük fayllar üçün hissə-hissə)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class TrustedPublisher:
    """Etibarlı naşir və onun Ed25519 açıq açarı."""

    name: str
    public_key_hex: str

    def public_key(self) -> Ed25519PublicKey:
        try:
            return Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key_hex))
        except (ValueError, TypeError) as exc:
            raise PluginSignatureError(
                f"'{self.name}' naşirinin açıq açarı yararsızdır",
                context={"publisher": self.name},
            ) from exc


class TrustStore:
    """Etibarlı naşirlərin reyestri.

    FAIL-CLOSED: boş truststore-da HEÇ BİR plugin yüklənmir. Bu, qəsdəndir —
    "hələ konfiqurasiya etməmişik" vəziyyəti sükutla "hər şeyə icazə var"a
    çevrilməməlidir.
    """

    def __init__(self, publishers: list[TrustedPublisher] | None = None) -> None:
        self._publishers: dict[str, TrustedPublisher] = {p.name: p for p in publishers or []}

    def add(self, publisher: TrustedPublisher) -> None:
        self._publishers[publisher.name] = publisher

    def get(self, name: str) -> TrustedPublisher | None:
        return self._publishers.get(name)

    @property
    def is_empty(self) -> bool:
        return not self._publishers

    @property
    def publisher_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._publishers))


class PluginSignatureVerifier:
    """Plugin imzasını yoxlayır — yüklənmədən ƏVVƏL."""

    def __init__(self, trust_store: TrustStore) -> None:
        self._trust_store = trust_store

    def verify(
        self,
        *,
        plugin_path: Path,
        manifest: PluginManifest,
        signature_hex: str,
    ) -> str:
        """İmzanı yoxlayır.

        Returns:
            Faylın SHA-256 daycesti (DB-də `plugins.signature` yanında saxlanılır).

        Raises:
            PluginSignatureError: imza yoxdursa, naşir naməlumdursa və ya
                imza uyğun gəlmirsə.
        """
        if self._trust_store.is_empty:
            self._deny(manifest, reason="EMPTY_TRUST_STORE")
            raise PluginSignatureError(
                "Etibarlı naşir siyahısı boşdur — heç bir plugin yüklənə bilməz (fail-closed)",
                context={"plugin": manifest.name},
            )

        publisher = self._trust_store.get(manifest.publisher)
        if publisher is None:
            self._deny(manifest, reason="UNKNOWN_PUBLISHER")
            raise PluginSignatureError(
                f"'{manifest.publisher}' etibarlı naşirlər siyahısında deyil",
                context={
                    "plugin": manifest.name,
                    "publisher": manifest.publisher,
                    "trusted": self._trust_store.publisher_names,
                },
            )

        if not plugin_path.exists():
            raise PluginSignatureError(
                f"Plugin faylı tapılmadı: {plugin_path}",
                context={"path": str(plugin_path)},
            )

        digest = file_sha256(plugin_path)
        payload = canonical_payload(file_digest=digest, manifest=manifest)

        try:
            signature = bytes.fromhex(signature_hex)
        except ValueError as exc:
            self._deny(manifest, reason="MALFORMED_SIGNATURE")
            raise PluginSignatureError(
                "İmza formatı yararsızdır (hex gözlənilir)",
                context={"plugin": manifest.name},
            ) from exc

        try:
            publisher.public_key().verify(signature, payload)
        except InvalidSignature as exc:
            self._deny(manifest, reason="SIGNATURE_MISMATCH")
            raise PluginSignatureError(
                f"'{manifest.name}' plugin-inin imzası uyğun gəlmir — fayl və ya "
                f"manifest imzalandıqdan sonra dəyişdirilib",
                context={"plugin": manifest.name, "publisher": manifest.publisher},
            ) from exc

        _security_log.info(
            "PLUGIN_SIGNATURE_VERIFIED",
            extra={
                "plugin": manifest.name,
                "version": manifest.version,
                "publisher": manifest.publisher,
                "file_sha256": digest,
                "capabilities": sorted(c.value for c in manifest.capabilities),
            },
        )
        return digest

    @staticmethod
    def _deny(manifest: PluginManifest, *, reason: str) -> None:
        _security_log.critical(
            "PLUGIN_SIGNATURE_REJECTED",
            extra={
                "plugin": manifest.name,
                "publisher": manifest.publisher,
                "denial_reason": reason,
            },
        )


def sign_plugin(
    *,
    plugin_path: Path,
    manifest: PluginManifest,
    private_key: Ed25519PrivateKey,
) -> str:
    """Plugin-i imzalayır — YALNIZ hazırlayıcı tərəfin build alətində istifadə olunur.

    Bu funksiya istehsalat tətbiqində HEÇ VAXT çağırılmır; burada saxlanılır ki,
    imzalama və yoxlama məntiqi bir yerdə, sinxron qalsın.
    """
    payload = canonical_payload(file_digest=file_sha256(plugin_path), manifest=manifest)
    return private_key.sign(payload).hex()


__all__ = [
    "PluginSignatureVerifier",
    "TrustStore",
    "TrustedPublisher",
    "canonical_payload",
    "file_sha256",
    "sign_plugin",
]
