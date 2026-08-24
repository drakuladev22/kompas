"""ƏVVƏL/SONRA skrinşotlarını çəkir — `finalui.md` Faza 6, bənd 1.

    QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
        -m tests.tools.capture_screenshots --output-dir ui_before_after/after \
        --label "cari(HEAD)"

Hər qeydiyyatlı ekranı (`AdminShell._factories`) HƏM `light`, HƏM `dark`
temada, `--preview` rejiminin FAKTİKİ giriş nöqtəsi ilə (`KompasApplication`
+ `preview_data.build_admin()` + `preview_screens.populate()`) açır,
1920×1080-ə `resize()` edib TAM PƏNCƏRƏNİ (`window.grab()` — header + sidebar
daxil) PNG kimi saxlayır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ƏL YAZILMIŞ EKRAN SİYAHISI YOX, REAL `--preview` GİRİŞ NÖQTƏSİ
──────────────────────────────────────────────────────────────────────────────
Hər ekranın konstruktor arqumentlərini (fabrika, `app.py::_register_screens`)
əl ilə təkrarlamaq 44 sinifin HƏR BİRİ üçün ayrıca uyğunlaşma tələb edərdi və
kod dəyişəndə DAİM köhnəlirdi. `KompasApplication(preview=True)` MƏHZ bunu
edir — bu, `main.py --preview`-in işlətdiyi EYNİ koddur, əl ilə yenidən
yığılmış YOX.

──────────────────────────────────────────────────────────────────────────────
ƏDALƏTLİ MÜQAYİSƏ ÜÇÜN: BAZA ÇƏKİLƏRKƏN `preview_data.py`-nı ƏVƏZ EDİN
──────────────────────────────────────────────────────────────────────────────
`preview_data.py`-nın `_ADMIN_FLAGS` siyahısı bəzi ekranları önizləmə
Admin-indən GİZLƏDİR (`NAVIGATION_DENIED`). Bu siyahı iki ölçmə arasında
DƏYİŞƏ bilər (yeni flag əlavə olunub) — o zaman «ƏVVƏL» dəstində daha AZ
ekran görünər, LAKİN bu, VİZUAL fərq DEYİL, sadəcə fikstürün köhnəlməsidir.
Ədalətli müqayisə üçün: baza kodunu daşıyan `git worktree`-də YALNIZ
`src/presentation/preview_data.py`-nı CARİ nüsxə ilə ƏVƏZ EDİN (`cp`), qalan
kodu TOXUNMADAN saxlayın, sonra bu skripti O WORKTREE-yə qarşı işlədin
(`--repo-root <worktree-yolu>`). `preview_data.py` maket FİKSTÜRÜDÜR, MƏHSUL
DAVRANIŞI DEYİL — onu sabitləşdirmək müqayisəni SAXTALAŞDIRMIR, ƏDALƏTLİ edir.
Nə əvəz etdiyinizi hesabatda AÇIQ yazın.

Nümunə (bax `docs/performance_notes.md`-dəki eyni metodologiya, kölgə ölçüsü
sessiyası):

    git worktree add --detach /tmp/baseline-wt ui-overhaul-baseline
    cp src/presentation/preview_data.py /tmp/baseline-wt/src/presentation/preview_data.py
    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m tests.tools.capture_screenshots \
        --repo-root /tmp/baseline-wt --output-dir ui_before_after/before --label "baza+cari fikstür"
    git worktree remove --force /tmp/baseline-wt

──────────────────────────────────────────────────────────────────────────────
`fines` NİYƏ HƏMİŞƏ ATLANIR
──────────────────────────────────────────────────────────────────────────────
`can_issue_fines` anti-fraud flag-idir və YALNIZ kamera-tipli rollara verilə
bilər (SEC-001) — `preview_data.build_admin()` ona QƏSDƏN sahib DEYİL. Bu,
skriptin QÜSURU deyil, domen qaydasının FAKTİKİ İŞLƏDİYİNİN sübutudur. Ona
görə `fines` "ALINMADI" siyahısında YOX, AYRICA "QƏSDƏN KƏNARDA" sətrində
göstərilir.

──────────────────────────────────────────────────────────────────────────────
WINDOWS `:` TƏLƏSİ — BOOLEAN-I MÜTLƏQ YOXLAYIN
──────────────────────────────────────────────────────────────────────────────
Plugin açarları `"plugin:pl-1"` kimi `:` daşıyır. NTFS-də fayl adında `:`
alternate-data-stream kimi oxunur — `QPixmap.save("...plugin:pl-1_light.png")`
SƏSSİZ `True` QAYTARIR, LAKİN heç bir görünən PNG YARANMIR (əvəzinə
"plugin" adlı faylın arxasında gizli axın yaranır). Bu, real ölçmə
sessiyasında TAPILIB: ilk qaçış "62 uğurlu" dedi, diskdə 61 fayl var idi.
İKİ qoruyucu VAR və İKİSİ DƏ SAXLANMALIDIR: (1) `key.replace(":", "-")` fayl
adında, (2) `pixmap.save()`-in qaytardığı BOOLEAN-ın yoxlanması — birincini
unutsan ikincisi tutur, ikincisini unutsan səhv sükutla keçər.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

#: `can_issue_fines` SEC-001 ilə YALNIZ kamera roluna verilir — önizləmə
#: Admin-i buna QƏSDƏN sahib deyil. Aşağıda AYRICA siyahılanır ki, real
#: nasazlıqla QARIŞDIRILMASIN.
_DELIBERATELY_EXCLUDED_KEYS: frozenset[str] = frozenset({"fines"})


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Kodun idxal olunacağı kök qovluq (worktree ola bilər). Defolt: bu repo.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="PNG-lərin yazılacağı qovluq (məs. ui_before_after/before və ya .../after).",
    )
    parser.add_argument(
        "--label",
        default="?",
        help="Konsol çıxışında görünən, hansı kod bazasından çəkildiyini xatırladan etiket.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1920,
        help="Pəncərə eni (hündürlük həmişə 1080). Defolt 1920 — son ölçülərlə eyni şərt.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915
    """Skriptin gövdəsi — `PLR0915` SUSDURULUB.

    Səbəb `_register_screens`/`_build_session`-dəki İSTİSNA ilə EYNİDİR
    (bax onların başlığı): bu, mürəkkəb MƏNTİQ deyil, düz gedən qurma +
    dövrə + hesabat ardıcıllığıdır. `_capture_theme`-i AYRI, modul-səviyyəli
    funksiya kimi çıxara bilmədik — o, `--repo-root`-dan asılı `sys.path`
    daxil edildikdən SONRA idxal olunan `KompasApplication`/`preview_data`/
    `ThemeMode` adlarına EHTİYAC duyur; modul səviyyəsində idxal etsəydik,
    `--repo-root` BAŞQA worktree göstərəndə YENƏ CARİ repo-nun kodu
    yüklənərdi — `--repo-root`-un BÜTÜN mənası itərdi (bax modul başlığı,
    "ƏDALƏTLİ MÜQAYİSƏ" bölməsi).
    """
    args = _parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    sys.path.insert(0, str(args.repo_root.resolve()))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    # `existing`-in tipi `QCoreApplication | None`-dur — `KompasApplication`
    # isə DƏQİQ `QApplication` gözləyir (`app.py::run`-dakı EYNİ naxış).
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])

    from src.presentation import preview_data
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    def _capture_theme(
        *, mode_name: str, mode: ThemeMode
    ) -> tuple[list[str], list[str], list[str]]:
        """Bir temanı bütünlüklə çəkir — `(alındı, qəsdən-kənarda, alınmadı)`.

        `main()`-in İÇİNDƏ QURULUB (bax funksiya başlığı) — `app`,
        `KompasApplication`, `preview_data`, `output_dir` bağlamadan gəlir.
        """
        application = KompasApplication(app, preview=True, theme_preference=mode, context=None)
        application.show_admin(preview_data.build_admin(), now=preview_data.PREVIEW_NOW)
        window = application._window
        shell = application._shell
        assert shell is not None, "show_admin() örtüyü qurmalıdır"
        window.resize(args.width, 1080)
        window.show()
        app.processEvents()

        succeeded: list[str] = []
        excluded: list[str] = []
        failed: list[str] = []

        for key in sorted(shell._factories.keys()):
            # Windows `:` tələsi — modul başlığındakı izaha bax.
            safe_key = key.replace(":", "-")
            label = f"{safe_key}_{mode_name}"
            if key in _DELIBERATELY_EXCLUDED_KEYS:
                excluded.append(f"{label} (SEC-001, can_issue_fines Admin-ə verilmir)")
                continue
            try:
                ok = shell.show_screen(key)
                if not ok:
                    failed.append(f"{label}: show_screen() False qaytardı (icazə/görünməzlik)")
                    continue
                app.processEvents()
                pixmap = window.grab()
                if pixmap.isNull():
                    failed.append(f"{label}: grab() boş pixmap qaytardı")
                    continue
                saved = pixmap.save(str(output_dir / f"{label}.png"), "PNG")
                if not saved:
                    failed.append(f"{label}: pixmap.save() False qaytardı")
                    continue
                succeeded.append(label)
            except Exception as exc:
                failed.append(f"{label}: {type(exc).__name__}: {exc}")

        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        return succeeded, excluded, failed

    succeeded: list[str] = []
    excluded: list[str] = []
    failed: list[str] = []
    for mode_name, mode in (("light", ThemeMode.LIGHT), ("dark", ThemeMode.DARK)):
        theme_succeeded, theme_excluded, theme_failed = _capture_theme(
            mode_name=mode_name, mode=mode
        )
        succeeded += theme_succeeded
        excluded += theme_excluded
        failed += theme_failed

    print(f"BUILD={args.label}")
    print(f"ÇIXIŞ={output_dir}")
    print(f"ALINDI={len(succeeded)}: {succeeded}")
    print(f"QƏSDƏN KƏNARDA={len(excluded)}: {excluded}")
    print(f"ALINMADI={len(failed)}")
    for line in failed:
        print(f"  - {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
