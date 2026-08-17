r"""`assets/logo/*.png` → `assets/kompasos.ico` (logo.md ADDIM 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SKRİPT — NİYƏ `.ico` REPOZİTORİYAYA ƏL İLƏ ATILMIR
──────────────────────────────────────────────────────────────────────────────
`.ico` TÖRƏMƏ fayldır: mənbəyi `assets/logo/`-dakı PNG-lərdir. Əl ilə qurulub
repozitoriyaya atılsaydı, PNG dəyişəndə `.ico` sükutla köhnələrdi və fərq
YALNIZ Taskbar-da görünərdi — yəni ən gec fərq olunan yerdə. Skript qurma
qaydasını (hansı ölçü hansı mənbədən) KODDA saxlayır.

──────────────────────────────────────────────────────────────────────────────
256×256 MƏNBƏSİ GƏLDİ — «İTMİŞ PİLLƏ» REQRESSİYASI BAĞLANDI
──────────────────────────────────────────────────────────────────────────────
Əvvəl bu fayl belə yazırdı: *«256×256 QURULMUR. Onu 64-dən böyütmək bulanıq
nəticə verərdi, ona görə həmin pillə `.ico`-da YOXDUR»*. Həmin qərar əldəki ən
böyük rastrın 64×64 olması ilə məhdudlaşırdı — səbəb dizayn deyil, MƏNBƏ
çatışmazlığı idi.

İndi `assets/logo/256.png` var və məhdudiyyət aradan qalxdı. Windows-un «Böyük
ikonlar» görünüşü artıq 64-ü miqyaslamır, natiw 256 pilləsini oxuyur.

──────────────────────────────────────────────────────────────────────────────
BÜTÜN PİLLƏLƏR 256-DAN QURULUR — NİYƏ QARIŞIQ MƏNBƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
«Hər pillə üçün ona ən yaxın mənbə» qaydası cazibədar görünür, lakin iki
problem yaradırdı:

  1. `16.png`/`32.png` FAKTİKİ olaraq 32 və 64 piksellik rastrlardır (adlar
     nöqtə ölçüsünü daşıyır) və `32.png` ilə `64.png` PİKSEL-EYNİDİR — yəni
     «yaxın mənbə» əslində eyni şəkilin kiçik nüsxəsidir, ayrıca hazırlanmış
     kiçik-ölçü variantı DEYİL. Ondan qazanc yoxdur.
  2. Qarışıq mənbə `.ico`-nun pillələrini bir-birindən bir qədər FƏRQLİ edərdi
     (fərqli kiçiltmə tarixçəsi, fərqli kənar yumşaqlığı) və nəticə yalnız
     ikonu iki ölçüdə yan-yana görəndə üzə çıxardı.

Ona görə mənbə TƏKDİR: ən böyük master. LANCZOS kiçiltməsi 256-dan hər pilləyə
düzgün nəticə verir və bütün pillələr eyni emal zəncirindən keçir.

`64.png` SİLİNMİR: o, `.ico`-nun mənbəyi olmasa da, tətbiq daxilindəki rozet
kimi işlənməyə davam edir (`brand_assets.APP_MARK`).

──────────────────────────────────────────────────────────────────────────────
`256 negative.png` MƏNBƏ DEYİL — REFERANSDIR
──────────────────────────────────────────────────────────────────────────────
`design_reference/256 negative.png` EYNİ işarənin daha böyük nüsxəsi DEYİL:
onun konteyneri kvadratdır (squircle deyil) və fonu daha tünddür — yəni ayrı
BİR VARİANTDIR. `.ico` tək kompozisiya daşıyır və orada markanın əsas forması
olmalıdır. Variant `design_reference/`-də qalır və `assets/logo/`-ya
KÖÇÜRÜLMÜR (`test_the_reference_variants_are_not_shipped` bunu qoruyur).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LOGO_DIR = _REPO_ROOT / "assets" / "logo"
_TARGET = _REPO_ROOT / "assets" / "kompasos.ico"

#: `.ico`-ya düşən pillələr. 256 ARTIQ VAR — bax modul başlığı.
#:
#: Siyahı Windows-un istifadə etdiyi standart ölçülərdir: 16 (siyahı/başlıq),
#: 24 (bəzi dialoqlar), 32 (masaüstü), 48 (orta ikonlar), 64 (yüksək DPI
#: masaüstü), 256 (böyük ikonlar + Alt-Tab).
ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 256)

#: TƏK mənbə — ən böyük master. Bütün pillələr bundan kiçildilir.
SOURCE_NAME = "256.png"

#: Mənbənin gözlənilən ölçüsü. Yoxlama QƏSDƏNDİR: dizayn faylı bir gün başqa
#: ölçüdə ixrac edilsə, `.ico` sükutla daha kiçik masterdən qurulardı və
#: 256 pilləsi yenidən böyütmə ilə alınardı — yəni reqressiya geri qayıdardı.
SOURCE_SIZE = 256


def build(*, target: Path | None = None) -> Path:
    """`.ico` faylını qurur və yolunu qaytarır."""
    # İdxal funksiya daxilindədir: `--help` və idxal yolu Pillow olmadan da açılmalıdır.
    from PIL import Image

    source = _LOGO_DIR / SOURCE_NAME
    if not source.is_file():
        raise SystemExit(f"Mənbə tapılmadı: {source}")

    master = Image.open(source).convert("RGBA")
    if master.size != (SOURCE_SIZE, SOURCE_SIZE):
        raise SystemExit(
            f"{SOURCE_NAME} {SOURCE_SIZE}×{SOURCE_SIZE} gözlənilirdi, faktiki {master.size}"
        )

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
    sys.stdout.write(f"Mənbə: {SOURCE_NAME} ({SOURCE_SIZE}×{SOURCE_SIZE}) — tək master.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI giriş nöqtəsi
    raise SystemExit(main())
