r"""Paketlənmiş şriftlərin qeydiyyatı — Inter (`appl.md` FAZA 1, qayda 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ ŞRİFT PAKETLƏNİR — «SİYAHIYA YAZMAQ» KİFAYƏT ETMİRDİ
──────────────────────────────────────────────────────────────────────────────
`tokens.TYPOGRAPHY["--font-family"]` əvvəl `Segoe UI, Inter, …` idi, yəni Inter
YALNIZ ehtiyat kimi dayanırdı və faktiki olaraq HEÇ VAXT işlədilmirdi: Windows-da
Inter QURAŞDIRILMIŞ DEYİL (ölçüldü — `QFontDatabase.families()` onu qaytarmır),
Segoe UI isə həmişə var. Sırayı çevirmək tək başına vəziyyəti DAHA PİS edərdi:
şrift quraşdırılmış maşında interfeys bir cür, quraşdırılmamışda başqa cür
görünərdi — yəni eyni buraxılış iki fərqli məhsul kimi çıxardı.

Ona görə fayl tətbiqlə BİRLİKDƏ gəlir və işə düşəndə `QFontDatabase`-ə
qeydiyyatdan keçir. Nəticə: Inter HƏR maşında var, sistem quraşdırmasından
ASILI DEYİL.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SF Pro DEYİL — LİSENZİYA
──────────────────────────────────────────────────────────────────────────────
Apple-in öz şrifti (`SF Pro`) yalnız Apple platformalarında işlədilə bilər;
Windows tətbiqinə paketlənməsi lisenziya pozuntusudur. Inter isə SIL Open Font
License 1.1 altındadır — paketləmə, dəyişdirmə və satış AÇIQ şəkildə icazəlidir
(`assets/fonts/LICENSE-Inter.txt`, mətn dəyişmədən saxlanılır, çünki OFL
lisenziya nüsxəsinin şriftlə birlikdə paylanmasını TƏLƏB edir).

──────────────────────────────────────────────────────────────────────────────
NİYƏ DÖRD STATİK FAYL, VARIABLE ŞRİFT DEYİL
──────────────────────────────────────────────────────────────────────────────
Inter-in `InterVariable.ttf` variantı tək fayldır, lakin Qt-nin dəyişkən-şrift
(variable font) ox dəstəyi versiyadan-versiyaya fərqlidir və `font-weight: 600`
sorğusu bəzi qurğularda ən yaxın STATİK üzə yuvarlaqlaşır. Dizayn sistemi məhz
çəki ilə iyerarxiya qurur (`--font-weight-normal/medium/bold` = 400/600/700),
yəni səhv yuvarlaqlaşma başlıqla gövdəni eyniləşdirərdi. Dörd statik fayl bu
sualı tamamilə aradan qaldırır: hər çəki ayrıca üzdür.

`Medium` (500) da daxildir, çünki `appl.md` gövdə mətni üçün 400–500 aralığını
göstərir — token əlavə olunanda faylın SONRADAN axtarılması lazım gəlməsin.

──────────────────────────────────────────────────────────────────────────────
XƏTA TƏTBİQİ DAYANDIRMIR
──────────────────────────────────────────────────────────────────────────────
Şrift yüklənməsə (fayl paketə düşməyib, disk oxunmur) tətbiq İŞLƏMƏYƏ DAVAM
EDİR və QSS-dəki ehtiyat sırası (`Segoe UI, Arial, sans-serif`) qüvvəyə minir.
Bu, `brand_assets.logo_path` və `app._apply_window_icon` ilə EYNİ qərardır:
görünüş detalı proqramı açılmaqdan saxlamamalıdır. Uğursuzluq JURNALA düşür —
səbəb ekranda görünməsə də, dəstək zəngində oxunmalıdır.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtGui import QFontDatabase

from src.shared.logger import get_logger
from src.shared.runtime import bundle_root, deployment_root

_log = get_logger(__name__)

#: Şrift fayllarının qovluğu — paketə `KompasOS.spec` ilə daxil edilir.
FONT_DIR: Final = "assets/fonts"

#: Qeydiyyatdan keçirilən üzlər. Sıra əhəmiyyətsizdir — `QFontDatabase` ailəni
#: özü qurur; siyahı DAR saxlanılır, çünki hər fayl ~410 KB-dır və istifadə
#: olunmayan çəki quraşdırıcını böyüdür.
FONT_FILES: Final[tuple[str, ...]] = (
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
)

#: `tokens.TYPOGRAPHY["--font-family"]`-dəki BİRİNCİ ad ilə eyni olmalıdır.
#: Fərqlənsələr şrift yüklənər, lakin QSS onu heç vaxt soruşmazdı.
FONT_FAMILY: Final = "Inter"

#: Təkrar qeydiyyatın qarşısını alır: `QFontDatabase.addApplicationFont` eyni
#: faylı ikinci dəfə YENİ id ilə yükləyir (yaddaşda ikinci nüsxə). Modul
#: səviyyəsində bayraq kifayətdir — qeydiyyat prosesə aiddir, pəncərəyə yox.
_registered: list[str] = []


def register_bundled_fonts() -> list[str]:
    """Paketlənmiş şriftləri yükləyir və tanınan AİLƏ adlarını qaytarır.

    İdempotentdir: ikinci çağırış diskə toxunmur, ilk nəticəni qaytarır.
    Boş siyahı «heç biri yüklənmədi» deməkdir və çağıran tərəf üçün
    DAYANDIRICI DEYİL (bax modul başlığı).
    """
    if _registered:
        return list(_registered)

    families: list[str] = []
    for name in FONT_FILES:
        path = _font_path(name)
        if path is None:
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            # `-1` = fayl var, LAKİN oxunmadı (korlanıb və ya format yanlışdır).
            # Bu, «tapılmadı»dan FƏRQLİ hadisədir və ayrıca jurnal açarı alır.
            _log.warning("FONT_LOAD_FAILED", extra={"path": path})
            continue
        families.extend(QFontDatabase.applicationFontFamilies(font_id))

    unique = list(dict.fromkeys(families))
    _registered.extend(unique)
    if unique:
        _log.info("FONTS_REGISTERED", extra={"families": unique, "count": len(unique)})
    else:
        _log.warning("FONTS_MISSING", extra={"directory": FONT_DIR})
    return list(unique)


def _font_path(name: str) -> str | None:
    """Faylın FAKTİKİ yolu — paketin içi, sonra paketin yanı.

    Sıra `brand_assets.logo_path` ilə EYNİDİR və qəsdən: iki resurs növü üçün
    iki fərqli axtarış sırası olsaydı, biri paketlənmiş buraxılışda işləyər,
    digəri yalnız mənbədən işləyəndə tapılardı.
    """
    for root in (bundle_root(), deployment_root()):
        if root is None:
            continue
        candidate = root / FONT_DIR / name
        if candidate.is_file():
            return str(candidate)
    return None


__all__ = ["FONT_DIR", "FONT_FAMILY", "FONT_FILES", "register_bundled_fonts"]
