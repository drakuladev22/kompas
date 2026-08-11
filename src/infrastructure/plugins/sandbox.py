"""Plugin sandbox — ayrı prosesdə icra (spesifikasiya bölmə 1) — Faza 2.7.

QAYDA: "Plugin-lər ayrıca prosesdə icra olunur, birbaşa DB credentials-a
çıxışı olmur, yalnız whitelisted API səthi üzərindən işləyir."

TƏTBİQ:
    * `subprocess` + **təmizlənmiş mühit** — bütün `KOMPASOS_*`, `SUPABASE_*`,
      `DATABASE_URL` və oxşar dəyişənlər SİLİNİR. Plugin prosesi sirrləri
      ümumiyyətlə GÖRMÜR.
    * Ünsiyyət yalnız **stdin/stdout JSON** ilə — paylaşılan yaddaş yoxdur.
    * **Timeout** — cavab verməyən plugin öldürülür (kiosk donmasın).
    * **Çıxış həcmi limiti** — nəhəng cavabla host-un yaddaşını doldurmaq
      mümkün deyil.
    * Hər çağırış **capability whitelist**-inə qarşı yoxlanılır.
    * Alt-proses HƏMİŞƏ əsl Python interpretatoru ilə açılır (`shared/
      runtime.py: plugin_interpreter`) — paketlənmiş `.exe` ilə YOX, çünki
      `.exe` interpretator deyil və `-I -S` izolyasiyasını daşıya bilməz.

QEYD (dürüstlük): bu, OS-səviyyəli TAM izolyasiya (seccomp/AppContainer/
job object) DEYİL. Proses hələ də istifadəçinin fayl sistemini oxuya bilər.
Tam izolyasiya Windows Job Object + AppContainer tələb edir və Faza 5-də
`docs/security_decisions.md`-də ayrıca qərar kimi qeyd olunub. Hazırkı qat
əsas riski — **sirrlərin və DB bağlantısının sızmasını** — bağlayır.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginError,
    PluginManifest,
    PluginPermissionError,
    PluginRequest,
    PluginResponse,
    PluginTimeoutError,
)
from src.shared.logger import LogChannel, get_logger
from src.shared.runtime import PLUGIN_PYTHON_ENV, plugin_interpreter

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MB

#: Plugin prosesinə ÖTÜRÜLMƏYƏN mühit dəyişəni prefiksləri.
SECRET_ENV_PREFIXES = (
    "KOMPASOS_",
    "SUPABASE_",
    "DATABASE_",
    "PG",
    "AWS_",
    "AZURE_",
    "GITHUB_",
)

#: Plugin prosesinə ÖTÜRÜLƏN minimal dəyişənlər (Python işə düşsün deyə).
ALLOWED_ENV_KEYS = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "PYTHONIOENCODING")


def build_sandbox_env() -> dict[str, str]:
    """Plugin prosesi üçün təmizlənmiş mühit qurur.

    Whitelist yanaşması (blacklist DEYİL): yalnız açıq şəkildə icazə verilmiş
    açarlar ötürülür. Yeni sirr dəyişəni əlavə edildikdə onu bura salmağı
    "unutmaq" mümkün deyil — defolt olaraq ötürülmür.
    """
    env = {
        key: os.environ[key]
        for key in ALLOWED_ENV_KEYS
        if key in os.environ and not key.startswith(SECRET_ENV_PREFIXES)
    }
    env["PYTHONIOENCODING"] = "utf-8"
    # Plugin host-un modullarını idxal edə bilməsin.
    env["PYTHONNOUSERSITE"] = "1"
    return env


@dataclass
class SandboxPolicy:
    """Sandbox məhdudiyyətləri."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_output_bytes: int = MAX_OUTPUT_BYTES
    allowed_capabilities: frozenset[PluginCapability] = field(default_factory=frozenset)

    def assert_allowed(self, capability: PluginCapability) -> None:
        if capability not in self.allowed_capabilities:
            _security_log.critical(
                "PLUGIN_CAPABILITY_DENIED",
                extra={
                    "requested": capability.value,
                    "allowed": sorted(c.value for c in self.allowed_capabilities),
                },
            )
            raise PluginPermissionError(
                f"Plugin '{capability.value}' capability-sinə malik deyil",
                context={"capability": capability.value},
            )


class PluginSandbox:
    """Plugin-i izolyasiya olunmuş prosesdə icra edir."""

    def __init__(
        self,
        *,
        manifest: PluginManifest,
        plugin_path: Path,
        policy: SandboxPolicy | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.manifest = manifest
        self.plugin_path = plugin_path
        self.policy = policy or SandboxPolicy(allowed_capabilities=frozenset(manifest.capabilities))
        # `sys.executable` BURADA ÇAĞIRILMIR: paketlənmiş rejimdə o,
        # `KompasOS.exe`-dir və interpretator deyil (bax `_command`).
        # Açıq verilmiş `python_executable` yenə də hər şeydən üstündür —
        # testlər və xüsusi quraşdırmalar bu yolla interpretator seçir.
        self._python: str | None = python_executable or plugin_interpreter()

    def _command(self) -> list[str]:
        """Alt-prosesin argv-si.

        `-I` (isolated) və `-S` (site yox) bayraqları sandbox-un ƏSAS
        zəmanətini daşıyır: plugin host-un `PYTHONPATH`-ını, user-site
        paketlərini və `src.*` modullarını GÖRMÜR. Ona görə əmrin ilk elementi
        həqiqi Python interpretatoru OLMALIDIR.

        İnterpretator tapılmadıqda burada AÇIQ istisna atılır — sükutla
        `sys.executable`-a qayıtmaq paketdə tətbiqin ikinci nüsxəsini işə
        salardı və nasazlıq "plugin xəta ilə bitdi (kod 2)" kimi görünərdi
        (bax `shared/runtime.py: plugin_interpreter`).
        """
        if self._python is None:
            _security_log.warning(
                "PLUGIN_INTERPRETER_MISSING",
                extra={"plugin": self.manifest.name, "env_key": PLUGIN_PYTHON_ENV},
            )
            raise PluginError(
                "Plugin icra edilə bilmədi: Python interpretatoru tapılmadı. "
                f"Paketlənmiş quraşdırmada onu `{PLUGIN_PYTHON_ENV}` mühit "
                "dəyişəni ilə göstərin.",
                context={"plugin": self.manifest.name, "env_key": PLUGIN_PYTHON_ENV},
            )
        return [self._python, "-I", "-S", str(self.plugin_path)]

    def invoke(self, request: PluginRequest) -> PluginResponse:
        """Plugin-ə bir çağırış göndərir və cavabı qaytarır.

        Plugin prosesi HƏR çağırışda yenidən başladılır — vəziyyət saxlamır,
        beləliklə bir çağırışdakı korlanma digərinə keçmir.
        """
        self.policy.assert_allowed(request.capability)

        # Əmr payload-dan ƏVVƏL qurulur: interpretator yoxdursa plugin heç
        # vaxt icra olunmayacaq və JSON hazırlamağın mənası yoxdur.
        command = self._command()

        payload = json.dumps(
            {
                "capability": request.capability.value,
                "payload": request.payload,
                "plugin": self.manifest.name,
                "version": self.manifest.version,
            },
            ensure_ascii=False,
        )

        try:
            completed = subprocess.run(  # noqa: S603 - yol və mühit nəzarətdədir
                command,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.policy.timeout_seconds,
                env=build_sandbox_env(),
                cwd=str(self.plugin_path.parent),
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _security_log.warning(
                "PLUGIN_TIMEOUT",
                extra={
                    "plugin": self.manifest.name,
                    "timeout_seconds": self.policy.timeout_seconds,
                },
            )
            raise PluginTimeoutError(
                f"'{self.manifest.name}' {self.policy.timeout_seconds} saniyə "
                f"ərzində cavab vermədi və dayandırıldı",
                context={"plugin": self.manifest.name},
            ) from exc

        if completed.returncode != 0:
            _log.warning(
                "PLUGIN_NONZERO_EXIT",
                extra={
                    "plugin": self.manifest.name,
                    "exit_code": completed.returncode,
                    "stderr": (completed.stderr or "")[:500],
                },
            )
            return PluginResponse(
                ok=False,
                error=f"Plugin xəta ilə bitdi (kod {completed.returncode})",
            )

        raw = completed.stdout or ""
        if len(raw.encode("utf-8")) > self.policy.max_output_bytes:
            _security_log.warning(
                "PLUGIN_OUTPUT_TOO_LARGE",
                extra={
                    "plugin": self.manifest.name,
                    "limit_bytes": self.policy.max_output_bytes,
                },
            )
            raise PluginError(
                f"Plugin çıxışı {self.policy.max_output_bytes} bayt limitini aşdı",
                context={"plugin": self.manifest.name},
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return PluginResponse(ok=False, error="Plugin cavabı düzgün JSON deyil")

        if not isinstance(data, dict):
            return PluginResponse(ok=False, error="Plugin cavabı obyekt olmalıdır")

        return PluginResponse(ok=True, data=data)

    def __repr__(self) -> str:
        return (
            f"PluginSandbox(plugin={self.manifest.name}@{self.manifest.version}, "
            f"capabilities={sorted(c.value for c in self.policy.allowed_capabilities)})"
        )


__all__ = [
    "ALLOWED_ENV_KEYS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_OUTPUT_BYTES",
    "SECRET_ENV_PREFIXES",
    "PluginSandbox",
    "SandboxPolicy",
    "build_sandbox_env",
]
