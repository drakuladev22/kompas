"""FINAL-UI-dən ƏVVƏL məlum olan ÖLÜ (heç yerə bağlanmayan) UI elementləri.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, NİYƏ ƏL İLƏ YAZILIB (AVTOMATİK YARADILMIR)
──────────────────────────────────────────────────────────────────────────────
`ui-inventory` agenti 147 «xam bağlanmamış» namizədi (statik AST-də heç bir
`.connect()` görünməyən widget) əl ilə süzdü: FormField örtüyü, lüğətə
yazılan lokal dəyişən, lambda bağlaması və göstərmə-üçün `DataTable` kimi
143 YALANÇI-MÜSBƏTİ çıxarandan sonra YALNIZ DÖRDÜ HƏQİQƏTƏN ölü qaldı (bax
`refine.py`/`report.md`, sətir "DEAD BUTTON CANDIDATES"). Bu, AST-in TƏKRAR
İSTEHSAL EDƏ BİLMƏYƏCƏYİ bir NƏTİCƏDİR (oxuma/mənimsəmə təhlili tələb edir),
ona görə `refresh_ui_baseline.py` bu faylı YARATMIR və DƏYİŞMİR.

──────────────────────────────────────────────────────────────────────────────
BU SİYAHININ MƏQSƏDİ — QAPI DEYİL, QEYDDİR
──────────────────────────────────────────────────────────────────────────────
`test_ui_screen_regression_gate.py` bu siyahını MƏCBURİ ETMİR (bu dörd
elementin «ölü qalması» tələb OLUNMUR — vizual iş onları düzəldə, silə və ya
saxlaya bilər, hamısı QƏBUL EDİLƏNDİR). Tək məqsəd: FINAL-UI-dən sonra kimsə
bu dördünü tapıb "biz sındırdıq" desə, buraya baxıb ARTIQ ƏVVƏLDƏN ölü
olduğunu görsün — reqressiya sayılmasın.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class DeadElement(NamedTuple):
    file: str
    screen_class: str
    attribute: str
    reason: str


#: FINAL-UI-dən ƏVVƏLKİ vəziyyət — `ui-inventory`, sətir "DEAD BUTTON
#: CANDIDATES (4)" (`report.md`).
KNOWN_DEAD_ELEMENTS: Final[tuple[DeadElement, ...]] = (
    DeadElement(
        file="group_c.py",
        screen_class="PermissionMatrixScreen",
        attribute="_override_search",
        reason="Heç bir .connect() yoxdur — axtarış sahəsi qurulur, siqnala bağlanmır.",
    ),
    DeadElement(
        file="group_d.py",
        screen_class="BackupScreen",
        attribute="_auto_toggle",
        reason="Heç bir .connect() yoxdur.",
    ),
    DeadElement(
        file="group_d.py",
        screen_class="BackupScreen",
        attribute="_time_combo",
        reason="Heç bir .connect() yoxdur.",
    ),
    DeadElement(
        file="group_d.py",
        screen_class="BackupScreen",
        attribute="_retention",
        reason="Heç bir .connect() yoxdur.",
    ),
)


__all__ = ["KNOWN_DEAD_ELEMENTS", "DeadElement"]
