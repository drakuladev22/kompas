"""Ekran mətnləri kataloqdan oxunur — `v2backlog.md` Faza 8.1-in qapısı.

──────────────────────────────────────────────────────────────────────────────
BU QAPI NİYƏ VAR — «STRUKTUR HAZIRDIR» İDDİASI ÖLÇÜLƏ BİLƏN OLMALIDIR
──────────────────────────────────────────────────────────────────────────────
Faza 8.1 tərcümə qatını, kataloqu və ROOT panelindəki «Dil» seçimini gətirdi,
LAKİN ekranlar mətnləri hələ də birbaşa yazırdı və `configure_i18n()` heç
yerdən çağırılmırdı. Nəticə xoşagəlməz bir aldanışdır: fayl siyahısına baxan
adam «i18n var» deyir, halbuki ikinci dil əlavə olunsa EKRANDA HEÇ NƏ
DƏYİŞMƏZDİ — 194 açar heç kimin oxumadığı bir sözlükdə otururdu.

Ona görə «tamamlandı» sözü burada İKİ ölçülə bilən şərtə bağlanıb:

  1. Tətbiq açılışda tərcüməçini QURUR (`configure_i18n`).
  2. Kataloqda dəyəri OLAN mətn ekran kodunda LİTERAL kimi TƏKRARLANMIR —
     `tr("açar")` ilə oxunur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YALNIZ UI ÇAĞIRIŞLARI YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
Eyni sətir kodda İKİ fərqli işdə görünə bilər: düymənin ETİKETİ (tərcümə
olunmalıdır) və məlumat DƏYƏRİ — sözlük açarı, müqayisə operandı, maket
sətri (tərcümə olunmamalıdır, çünki onlar interfeys mətni deyil; tərcümə
onları sükutla sındırardı). Ayırd etmə mümkün olan yeganə yer çağırış
kontekstidir: aşağıdakı ağ siyahı yalnız EKRANA mətn verən funksiyaları
sadalayır.

`preview_*` faylları KƏNARDADIR: onlar maket MƏLUMATIdır (Root panelinin
nümunə sətirləri, saxta işçi adları), interfeys mətni deyil.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from src.presentation.i18n.catalog_az import CATALOG_AZ

_PRESENTATION: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "presentation"

#: Arqumenti EKRANA mətn kimi düşən funksiya/metodlar (bax modul başlığı).
_UI_CALLS: Final[frozenset[str]] = frozenset(
    {
        "action_button",
        "secondary_button",
        "ghost_button",
        "danger_button",
        "field_label",
        "title_label",
        "muted_label",
        "plain_label",
        "section_header",
        "Column",
        "FormField",
        "Chip",
        "setText",
        "setPlaceholderText",
        "setToolTip",
        "setAccessibleName",
        "setAccessibleDescription",
        "setTitle",
        "setWindowTitle",
        "addItem",
        "addTab",
    }
)

#: İki simvoldan qısa dəyərlər (`—`) yoxlanmır: onlar sözdən çox işarədir və
#: `tr("common.none")` yazmaq oxunuşu ağırlaşdırar, tərcüməyə isə heç nə
#: qatmaz — em-tire bütün dillərdə eynidir.
_MIN_LENGTH: Final = 3

_CATALOG_VALUES: Final[frozenset[str]] = frozenset(
    text for text in CATALOG_AZ.values() if len(text) >= _MIN_LENGTH
)


def _screen_files() -> list[Path]:
    return [
        path
        for folder in ("screens", "shell", "widgets")
        for path in sorted((_PRESENTATION / folder).rglob("*.py"))
        if not path.name.startswith("preview_")
    ]


def _hardcoded_ui_texts(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        )
        if name not in _UI_CALLS:
            continue
        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
            if (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and argument.value in _CATALOG_VALUES
            ):
                found.append(f"{path.name}:{argument.lineno} «{argument.value}»")
    return found


def test_screens_read_shared_texts_from_the_catalog() -> None:
    """Kataloqda olan mətn ekranda TƏKRAR YAZILMIR.

    Qapı yalnız KATALOQDA OLAN dəyərləri tutur — yəni yeni ekran öz mətnini
    sərbəst yaza bilər. Qadağan olunan tək şey budur: eyni cümlə həm
    kataloqda, həm ekranda yaşasın, çünki o zaman ikinci dil əlavə olunanda
    biri tərcümə olunar, digəri arxada qalar və interfeys iki dilli görünər.
    """
    offenders = [entry for path in _screen_files() for entry in _hardcoded_ui_texts(path)]
    assert not offenders, (
        "Bu mətnlər kataloqda VAR, lakin ekranda literal kimi yazılıb — "
        f'`tr("açar")` ilə oxuyun: {offenders}'
    )


def test_the_application_configures_the_translator_before_any_window() -> None:
    """`configure_i18n()` açılış yolunda çağırılır.

    Kataloq özü-özünə qurulur (`get_translator()` tənbəl defolt yaradır), yəni
    bu çağırış OLMASA da mətnlər görünərdi — və məhz buna görə qapı lazımdır:
    dil seçimi üçün yeganə giriş nöqtəsi budur, itsə heç bir test qırılmazdı
    və dil dəyişikliyi sükutla təsirsiz qalardı.
    """
    source = (_PRESENTATION / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "src.presentation.i18n"
        and any(alias.name == "configure_i18n" for alias in node.names)
        and node.col_offset == 0  # `TYPE_CHECKING` bloku DEYİL — icra idxalı
        for node in ast.walk(tree)
    )
    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "configure_i18n"
        for node in ast.walk(tree)
    )

    assert imported, "`configure_i18n` icra idxalı yoxdur (yalnız tip idxalı kifayət etmir)"
    assert called, "`configure_i18n()` açılışda çağırılmır — dil seçimi təsirsiz qalardı"


def test_every_catalog_key_is_unique_per_text_or_documented() -> None:
    """Eyni mətnin İKİ açarı olması qəsdli olmalıdır.

    Təkrar dəyər öz-özlüyündə qüsur deyil (məs. «Aktiv» həm istifadəçi, həm
    ERP statusudur və ikinci dildə fərqli sözlər ola bilər). Qapı yalnız SAYI
    sabit saxlayır: yeni təkrar əlavə edən adam onu ŞÜURLU şəkildə etməlidir,
    çünki ekran köçürməsi belə dəyərlərdə açarı KONTEKSTƏ görə seçir.
    """
    seen: dict[str, list[str]] = {}
    for key, text in CATALOG_AZ.items():
        seen.setdefault(text, []).append(key)
    duplicates = {text: keys for text, keys in seen.items() if len(keys) > 1}

    assert duplicates == {
        "İşçi": ["common.employee", "fine.employee"],
        "Tarix": ["common.date", "fine.date"],
        "Mağaza": ["common.store", "fine.store"],
        "Səbəb": ["common.reason", "license.inactive.reason"],
        "İstifadəçi adı": ["common.username", "auth.login.username"],
        "Şifrə": ["common.password", "auth.login.password"],
        "Aktiv": ["common.active", "users.status.active", "erp.status.active"],
        "Sil": ["common.delete", "kiosk.pin.delete"],
        "Gözləyir": ["common.pending", "fine.status.pending"],
        "Məlumat yoxdur": ["common.no_data", "state.empty.title"],
        "Tətbiq Et": ["common.apply", "root.apply"],
        "Təmizlə": ["common.clear", "kiosk.pin.clear"],
        "ROOT İdarə Mərkəzi": ["nav.root_control", "root.title"],
        "Bildirişlər": ["settings.notifications", "notifications.title"],
    }, "Kataloqda gözlənilməyən təkrar dəyər — açar seçimi kontekstə bağlıdır, bax modul başlığı"
