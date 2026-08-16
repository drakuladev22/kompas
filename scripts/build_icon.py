r"""`assets/logo/*.png` → `assets/kompasos.ico` (logo.md ADDIM 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SKRİPT — NİYƏ `.ico` REPOZİTORİYAYA ƏL İLƏ ATILMIR
──────────────────────────────────────────────────────────────────────────────
`.ico` TÖRƏMƏ fayldır: mənbəyi `assets/logo/`-dakı PNG-lərdir. Əl ilə qurulub
repozitoriyaya atılsaydı, PNG dəyişəndə `.ico` sükutla köhnələrdi və fərq
YALNIZ Taskbar-da görünərdi — yəni ən gec fərq olunan yerdə. Skript qurma
qaydasını (hansı ölçü hansı mənbədən) KODDA saxlayır.

──────────────────────────────────────────────────────────────────────────────
MÖVCUD MƏNBƏLƏR VƏ FAKTİKİ ÖLÇÜLƏR
──────────────────────────────────────────────────────────────────────────────
Fayl adları ilə faktiki piksel ölçüləri UYĞUN GƏLMİR — adlar nöqtə (pt)
ölçüsünü, fayllar isə @2x rasteri daşıyır:

    16.png                  →  32×32
    16_withoutcontainer.png →  32×32   (konteynersiz işarə, title bar üçün)
    32.png                  →  64×64
    64.png                  →  64×64   (32.png ilə PİKSEL-EYNİ)

Yəni əldə YALNIZ İKİ fərqli rastr var: 32 və 64. `.ico`-nun qalan pillələri
(16, 24, 48) 64-dən KİÇİLDİLƏRƏK alınır — kiçiltmə keyfiyyət itirmir.

**256×256 QURULMUR.** Onu 64-dən böyütmək bulanıq nəticə verərdi (logo.md
bunu açıq qadağan edir), ona görə həmin pillə `.ico`-da YOXDUR və Windows-un
«Böyük ikonlar» görünüşü 64-ü miqyaslayacaq. Tam keyfiyyət üçün 256×256
Claude Design-dan AYRICA ixrac edilməlidir.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LOGO_DIR = _REPO_ROOT / "assets" / "logo"
_TARGET = _REPO_ROOT / "assets" / "kompasos.ico"

#: `.ico`-ya düşən pillələr. 256 QƏSDƏN yoxdur — bax modul başlığı.
ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64)

#: Ən böyük mövcud mənbə. Kiçik pillələr bundan KİÇİLDİLİR.
SOURCE_NAME = "64.png"


def build(*, target: Path | None = None) -> Path:
    """`.ico` faylını qurur və yolunu qaytarır."""
    # İdxal funksiya daxilindədir: `--help` və idxal yolu Pillow olmadan da açılmalıdır.
    from PIL import Image

    source = _LOGO_DIR / SOURCE_NAME
    if not source.is_file():
        raise SystemExit(f"Mənbə tapılmadı: {source}")

    master = Image.open(source).convert("RGBA")
    if master.size != (64, 64):
        raise SystemExit(f"{SOURCE_NAME} 64×64 gözlənilirdi, faktiki {master.size}")

    destination = target or _TARGET
    # Pillow `sizes` verildikdə hər pilləni ÖZÜ kiçildir (LANCZOS). Ayrı-ayrı
    # `resize` çağırışları eyni nəticəni verər, lakin `.ico` formatının
    # daxili sırasını əl ilə idarə etmək lazım gələrdi.
    master.save(destination, format="ICO", sizes=[(size, size) for size in ICO_SIZES])
    return destination


def main() -> int:
    destination = build()
    from PIL import Image

    with Image.open(destination) as icon:
        built = sorted(icon.info.get("sizes", []))
    sys.stdout.write(f"{destination.relative_to(_REPO_ROOT)} quruldu: {built}\n")
    sys.stdout.write("QEYD: 256×256 pilləsi YOXDUR — mənbə 64×64-dür (bax modul başlığı).\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI giriş nöqtəsi
    raise SystemExit(main())
