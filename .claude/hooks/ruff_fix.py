# -*- coding: utf-8 -*-
"""PostToolUse hook — yazılan Python faylını DƏRHAL `ruff` ilə düzəldir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA SKRIPT, SƏTİR-İÇİ ƏMR YOX
──────────────────────────────────────────────────────────────────────────────
Hook stdin-dən JSON alır və oradan fayl yolunu çıxarmaq lazımdır. Adi resept
`jq`-dur, LAKİN bu maşında `jq` QURAŞDIRILMAYIB (yoxlanılıb: «command not
found»). Sətir-içi `python -c "..."` variantı isə dırnaq və qaçış
qaydalarında sükutla sınır — hook uğursuz olsa heç bir səs çıxmır və
istifadəçi onu «işləyir» sayar.

Yeri `.claude/hooks/`-dədir, `scripts/`-də YOX: `scripts/` keyfiyyət
qapılarının (`ruff check src/ tests/ scripts/`) əhatəsindədir və orada duran
alət öz-özünü yoxlayan dövrə yaradardı. Burası isə xalis alət qovluğudur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SƏSSİZ QAYIDIR
──────────────────────────────────────────────────────────────────────────────
Hook redaktəni BLOKLAMAMALIDIR. `ruff` düzəldə bilməyən xəta tapsa, onu
qapılar onsuz da tutacaq (`ruff check src/ tests/ scripts/`). Hook-un işi
formatı avtomatik saxlamaqdır, nəzarətçi olmaq yox — əks halda hər yarımçıq
redaktə iş axınını dayandırardı.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    response = payload.get("tool_response") or {}
    target = response.get("filePath") or (payload.get("tool_input") or {}).get("file_path")
    if not target:
        return 0

    path = Path(target)
    if path.suffix != ".py" or not path.exists():
        return 0

    # `src/`, `tests/`, `scripts/` — qapıların əhatəsi. Kənardakı fayl
    # (məs. scratchpad skripti) layihənin üslub qaydalarına tabe deyil.
    try:
        relative = path.resolve().relative_to(REPO)
    except ValueError:
        return 0
    if relative.parts[0] not in {"src", "tests", "scripts"}:
        return 0

    if not PYTHON.exists():
        return 0

    for arguments in (["-m", "ruff", "check", "--fix"], ["-m", "ruff", "format"]):
        subprocess.run(  # noqa: S603
            [str(PYTHON), *arguments, str(path)],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
