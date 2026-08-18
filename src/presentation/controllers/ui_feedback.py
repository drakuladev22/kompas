"""Bloklayan əməliyyatdan ƏVVƏL ekranı çəkdirən köməkçi — UX-1.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ — «DÜYMƏ GEC CAVAB VERİR»
──────────────────────────────────────────────────────────────────────────────
Kontrollerlər bloklayan işdən əvvəl düzgün şeyi edirdi: `set_busy(True)`
düyməni söndürür və mətnini «Yoxlanılır…»-a çevirirdi. Lakin Qt həmin
dəyişikliyi DƏRHAL çəkmir — o, yalnız növbəti çəkiliş hadisəsində görünür,
çəkiliş hadisəsi isə idarə hadisə dövrəsinə QAYITDIQDA emal olunur. Bloklayan
sorğu məhz həmin qayıdışdan ƏVVƏL başlayırdı.

Nəticə istifadəçinin gördüyü şey idi: düyməyə basılır, ekranda HEÇ NƏ dəyişmir,
bir-iki saniyə sonra birdən nəticə çıxır. Yəni proqram «cavab vermir» kimi
görünürdü — halbuki işləyirdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İŞÇİ SAP DEYİL
──────────────────────────────────────────────────────────────────────────────
Düzgün ümumi həll işi arxa sapa köçürməkdir, lakin bu, hər kontroller üçün
siqnal körpüsü, ləğvetmə və «ekran artıq ölüb» hallarının emalını tələb edir.
Bir dəfəlik, ön-planda, istifadəçinin GÖZLƏDİYİ əməliyyat üçün bu, artıq
mürəkkəblikdir (eyni mühakimə `connection_settings.py`-da da yazılıb — bu
funksiya oradan çıxarılıb, çünki qayda artıq İKİ yerdə lazım idi).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `ExcludeUserInputEvents` YOX
──────────────────────────────────────────────────────────────────────────────
`processEvents()` istifadəçi girişini də emal edir, yəni nəzəri olaraq
istifadəçi bloklama başlamazdan əvvəl ikinci dəfə klikləyə bilər. Praktikada
bu mümkün deyil: çağıran HƏMİŞƏ əvvəlcə `set_busy(True)` edir və düymə artıq
SÖNDÜRÜLMÜŞ olur. Girişi süzgəcdən keçirmək isə pəncərənin bağlanması kimi
hadisələri də kəsərdi.
"""

from __future__ import annotations


def flush_ui() -> None:
    """Gözləyən çəkilişləri DƏRHAL icra edir.

    `QApplication` yoxdursa (kontroller vahid testdə Qt-siz qurula bilər)
    heç nə etmir — kontrollerin məntiqi hadisə dövrəsindən ASILI OLMAMALIDIR.
    """
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    app = QApplication.instance()
    if app is not None:
        app.processEvents()


__all__ = ["flush_ui"]
