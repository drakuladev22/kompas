"""Aparat izinin MƏNBƏLƏRİ — `device_identity` (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bu modulun qüsuru SÜKUTLUDUR və məhz buna görə təhlükəlidir: aparat
göstəriciləri oxunmasa proqram normal açılır, sadəcə fingerprint zəif dəyərə
(maşın adı + profil yolu) düşür. Zəif fingerprint isə `device.json`-un başqa
maşına KÖÇÜRÜLMƏSİNİ aşkarlaya bilmir — yəni lisenziya sayğacının yeganə
aparat lövbəri itir və heç bir ekranda xəbərdarlıq görünmür.

Faktiki hadisə: Windows 11 24H2-dən sonra Microsoft `wmic.exe`-ni sistemdən
çıxardı. Modul YALNIZ ona bağlı idi, ona görə hər üç sorğu `FileNotFoundError`
verirdi və NƏTİCƏ hər açılışda zəif fingerprint olurdu. Bu dəst həmin
reqressiyanı bir daha buraxmır:

    1. Sorğu əmri `wmic`-ə İSTİNAD ETMİR;
    2. Machine GUID registry-dən oxunur — subprocess-siz, yəni əmr yoxa
       çıxsa da fingerprint zəif YOLA DÜŞMÜR;
    3. Aparat sorğusu açılış yolunda YALNIZ BİR DƏFƏ çağırılır;
    4. OEM boşluq mətnləri («To be filled by O.E.M.») hash-a düşmür;
    5. Heç nə oxunmayanda zəiflik SÜKUTLA yox, jurnalla qeyd olunur.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Any, Final

import pytest

from src.infrastructure.config import device_identity as di

#: Sorğunun real çıxışı — `KEY=VALUE` sətirləri.
_PROBE_OUTPUT: Final[str] = (
    "BASEBOARD=M80-F6005500009\nDISK=0025_38D4_3140_191E.\nUUID=DE59A1A8-1F4C-0000-0000-000000000000\n"
)


class _FakeCompleted:
    """`subprocess.run` nəticəsinin minimal əvəzi."""

    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Platformanı Windows kimi göstərir — dəst hər OS-də eyni işləsin."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")


def _stub_probe(monkeypatch: pytest.MonkeyPatch, stdout: str) -> list[tuple[str, ...]]:
    """`subprocess.run`-u əvəzləyir və çağırılan əmrləri toplayır."""
    calls: list[tuple[str, ...]] = []

    def fake_run(command: Any, **kwargs: Any) -> _FakeCompleted:
        calls.append(tuple(command))
        return _FakeCompleted(stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


# ─────────────────────────────────────────────────────────────────────────────
# 1. Reqressiya qapısı: `wmic` bir daha yeganə mənbə olmur
# ─────────────────────────────────────────────────────────────────────────────


def test_hardware_probe_does_not_depend_on_wmic() -> None:
    """Əmr `wmic`-ə istinad etmir — o, Windows 11-dən çıxarılıb."""
    joined = " ".join(di.HARDWARE_PROBE_COMMAND).lower()
    assert "wmic" not in joined


# ─────────────────────────────────────────────────────────────────────────────
# 2. Registry mənbəyi subprocess-dən ASILI DEYİL
# ─────────────────────────────────────────────────────────────────────────────


def test_machine_guid_survives_a_missing_probe_executable(
    windows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sorğu icra faylı yoxdursa belə machine GUID hissəsi qalır."""

    def exploding_run(command: Any, **kwargs: Any) -> _FakeCompleted:
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(subprocess, "run", exploding_run)
    monkeypatch.setattr(di, "_read_machine_guid", lambda: "92F16A56-E005-4324-B961-3CCFEC5BE4B7")

    parts = di._hardware_parts()

    assert [source for source, _ in parts] == ["machine_guid"]


@pytest.mark.skipif(platform.system() != "Windows", reason="registry yalnız Windows-dadır")
def test_machine_guid_is_readable_on_this_windows_installation() -> None:
    """Seam saxta deyil: real registry dəyəri oxunur."""
    assert di._read_machine_guid().strip() != ""


# ─────────────────────────────────────────────────────────────────────────────
# 3. Açılış yolunda sorğu BİR dəfə gedir
# ─────────────────────────────────────────────────────────────────────────────


def test_probe_runs_exactly_once(windows: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Üç göstərici üçün üç proses açılmır — açılış yolu buna dözmür."""
    calls = _stub_probe(monkeypatch, _PROBE_OUTPUT)
    monkeypatch.setattr(di, "_read_machine_guid", lambda: "")

    di._hardware_parts()

    assert len(calls) == 1


def test_probe_output_yields_all_three_hardware_sources(
    windows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anakart, disk və SMBIOS UUID ayrı-ayrı hissələr kimi qayıdır."""
    _stub_probe(monkeypatch, _PROBE_OUTPUT)
    monkeypatch.setattr(di, "_read_machine_guid", lambda: "")

    parts = dict(di._hardware_parts())

    assert parts["baseboard"] == "M80-F6005500009"
    assert parts["diskdrive"] == "0025_38D4_3140_191E."
    assert parts["csproduct"] == "DE59A1A8-1F4C-0000-0000-000000000000"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Boşluq mətnləri hash-a düşmür
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "placeholder",
    [
        "To be filled by O.E.M.",
        "Default string",
        "None",
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_oem_placeholders_are_not_treated_as_hardware(
    windows: None, monkeypatch: pytest.MonkeyPatch, placeholder: str
) -> None:
    """OEM boşluq mətni maşınları BİR-BİRİNƏ yaxınlaşdırardı."""
    _stub_probe(monkeypatch, f"BASEBOARD={placeholder}\nDISK=\nUUID=\n")
    monkeypatch.setattr(di, "_read_machine_guid", lambda: "")

    assert di._hardware_parts() == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. Heç nə oxunmayanda zəiflik SÜKUTLA keçmir
# ─────────────────────────────────────────────────────────────────────────────


def test_weak_fingerprint_is_logged_when_nothing_is_readable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Zəif yola düşmək qərar deyil, HADİSƏDİR — jurnalda izi qalır."""
    monkeypatch.setattr(di, "_hardware_parts", list)

    with caplog.at_level(logging.WARNING):
        fingerprint = di.collect_fingerprint()

    assert fingerprint.value
    assert "DEVICE_FINGERPRINT_WEAK" in caplog.text


def test_non_windows_platform_never_spawns_a_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux/macOS-da (CI, developer maşını) proses açılmır."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    calls = _stub_probe(monkeypatch, _PROBE_OUTPUT)

    assert di._hardware_parts() == []
    assert calls == []
