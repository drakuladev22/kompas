"""Əl ilə işə salınan test alətləri — `pytest` tərəfindən TOPLANMIR.

`tests/unit`/`tests/e2e`-dən fərqli olaraq bu paketdəki fayllar TEST DEYİL,
CLI skriptlərdir (`python -m tests.tools.<ad>`). Toplanmama SƏBƏBİ fayl
ADIDIR — heç biri `test_*.py`/`*_test.py` naxışına uymur (`pyproject.toml`
`[tool.pytest.ini_options]`), `testpaths = ["tests"]` bu qovluğu da EHTİVA
EDİR, sadəcə pytest onun içindən yalnız naxışa uyan faylları seçir.
"""

from __future__ import annotations
