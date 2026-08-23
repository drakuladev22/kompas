"""`tenant_id` arqument BORCUNUN sayğacı və siyahısı (SAAS-1) — dövrə 4.

──────────────────────────────────────────────────────────────────────────────
BORC NƏDİR
──────────────────────────────────────────────────────────────────────────────
`_BaseRepository` törəmələrinin bir hissəsi `tenant_id: TenantId` arqumentini
QƏBUL EDİR (port imzası belə tələb edir), lakin sorğuda bağlantının ÖZ
kontekstini (`self._tenant`) YOX, məhz həmin arqumenti işlədir. RLS
(`USING (tenant_id = current_tenant_id())`) sızmanın qarşısını onsuz da alır —
yəni bu, TƏHLÜKƏSİZLİK DEŞİYİ DEYİL. İtən şey diaqnostikadır: səhv `tenant_id`
ötürən çağırış BOŞ nəticə alır və operator «məlumat yoxdur» zənn edir, halbuki
arxada proqram xətası var (`_BaseRepository._require_matching_tenant` şərhi).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAYĞAC — «HAMISINI İNDİ KÖÇÜR» ƏVƏZİNƏ
──────────────────────────────────────────────────────────────────────────────
Borc 26 fayla yayılıb və hər metodun sorğu quruluşu fərqlidir; hamısını bir
dövrədə köçürmək izlənilməz bir dəyişiklik olardı (ARCHITECT-in dövrə 2
qərarı). Bunun əvəzinə borc ÖLÇÜLÜR və TAVANLA qıfıllanır:

    * `TENANT_ARGUMENT_DEBT_CEILING` cari rəqəmdir,
    * rəqəm YALNIZ AŞAĞI düşə bilər — yeni metod bu borcu ARTIRA BİLMƏZ,
    * artırmaq istəyən adam tavanı da qaldırmalı olur, yəni qərar GÖRÜNÜR.

Naxış `scripts/check_symmetry.py`-nin tavanı ilə eynidir: ölçülən kəmiyyət
sıfır olmayanda da idarə oluna bilər, şərt onun səssizcə böyüməməsidir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SKRİPT YOX, MODUL
──────────────────────────────────────────────────────────────────────────────
Funksiya kimi çağırılan bir qapı həm testdən (`tests/unit/`), həm Developer
Panelindən, həm də adi Python konsolundan işlədilə bilir. Ayrıca skript
olsaydı, nəticəni proqramla oxumaq üçün onu subprocess kimi işə salmaq
lazım gələrdi.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Kod BU sinifdən törəyən sinifləri repository sayır.
_BASE_CLASS: Final[str] = "_BaseRepository"

#: Metodu «borcdan kənar» sayan `self.` ATRİBUTLARI. İkisindən BİRİ kifayətdir:
#: metod ya açıq yoxlamadan (`_require_matching_tenant`) keçir, ya da sorğuda
#: birbaşa `self._tenant` işlədir — hər iki halda sorğunun mənbəyi BAĞLANTININ
#: kontekstidir.
#:
#: Yoxlama ATRİBUT ADINA görədir, mətn axtarışına görə YOX: `"_tenant"` sadə
#: alt-sətir kimi axtarılsaydı `self._tenant_id` (tamam BAŞQA sahə) və hətta
#: `_tenant_clause` da «təhlükəsiz» sayılardı — yəni sayğac borcu OLDUĞUNDAN
#: AZ göstərərdi. Az göstərən sayğac heç olmayandan pisdir: tavan yalançı
#: təhlükəsizlik hissi verərdi.
_SAFE_ATTRIBUTES: Final[frozenset[str]] = frozenset({"_require_matching_tenant", "_tenant"})

#: Cari borc — ölçüldü (dövrə 4, birinci partiyadan SONRA: 136 → 123).
#:
#: BU RƏQƏM YALNIZ AŞAĞI DÜŞÜR. Qaldırmaq lazım gələrsə səbəb commit mesajında
#: yazılmalıdır — «yeni repo metodu əlavə etdim» səbəb DEYİL: yeni metod
#: `_require_matching_tenant()` çağırmalıdır (bax həmin metodun şərhi).
TENANT_ARGUMENT_DEBT_CEILING: Final[int] = 123


@dataclass(frozen=True)
class TenantArgumentSite:
    """Borclu bir metod: fayl, sətir, `Sinif.metod`."""

    path: Path
    line: int
    qualified_name: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}:{self.qualified_name}"


def infrastructure_root() -> Path:
    """`src/infrastructure` qovluğu — bu faylın yerindən həll olunur.

    Yol SABİT YAZILMIR: paket kökü işə salınma qovluğundan asılı olmamalıdır
    (eyni qərar `shared/data_paths.py`-dədir).
    """
    return Path(__file__).resolve().parent.parent


def scan_tenant_argument_debt(root: Path | None = None) -> list[TenantArgumentSite]:
    """`tenant_id` arqumentini işlədən, kontekstə keçməyən metodları qaytarır.

    Sıralama sabitdir (fayl → sətir): iki icranın nəticəsini müqayisə etmək
    (məs. «hansı 13 metod köçürüldü») fərqi oxumaqla mümkün olsun deyə.

    Mənbə faylı OLMAYAN mühitdə (paketlənmiş `.exe`) boş siyahı qayıdır — bu,
    qapının «keçdi» demək olduğu YEGANƏ haldır və qəsdlidir: borcu ölçmək
    inkişaf vaxtının işidir, işləyən tətbiqin yox.
    """
    base = root or infrastructure_root()
    if not base.is_dir():
        return []

    repository_classes = _repository_class_names(base)
    sites: list[TenantArgumentSite] = []
    for path in sorted(base.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name not in repository_classes:
                continue
            sites.extend(_debt_in_class(node, path))
    return sites


def format_debt_report(sites: list[TenantArgumentSite] | None = None) -> str:
    """İnsan üçün hesabat: say, tavan və fayl-üzrə bölgü.

    Hesabatın ÖZÜ məhsuldur: borcu azaltmağı planlaşdıran adam hansı faylın ən
    çox borc daşıdığını bir baxışda görməlidir.
    """
    found = scan_tenant_argument_debt() if sites is None else sites
    by_file: dict[str, int] = {}
    for site in found:
        by_file[site.path.name] = by_file.get(site.path.name, 0) + 1
    lines = [
        f"`tenant_id` arqument borcu: {len(found)} metod, {len(by_file)} fayl "
        f"(tavan: {TENANT_ARGUMENT_DEBT_CEILING})",
    ]
    lines += [
        f"  {name}: {count}"
        for name, count in sorted(by_file.items(), key=lambda item: (-item[1], item[0]))
    ]
    return "\n".join(lines)


def _repository_class_names(base: Path) -> frozenset[str]:
    """`_BaseRepository`-dən (dolayısı ilə də) törəyən bütün sinif adları.

    Törəmə ZƏNCİRİ nəzərə alınır: bir sinif başqa repo sinfindən miras alsa da
    borc daşıyır. Ad-əsaslı həll idxal qrafını qurmaqdan sadədir və bu
    layihədə repository sinif adları qlobal unikaldır.
    """
    bases_by_class: dict[str, set[str]] = {}
    for path in sorted(base.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = {
                item.id if isinstance(item, ast.Name) else getattr(item, "attr", "")
                for item in node.bases
            }
            bases_by_class.setdefault(node.name, set()).update(names)

    def derives(name: str, seen: frozenset[str]) -> bool:
        if name in seen:
            return False
        parents = bases_by_class.get(name, set())
        if _BASE_CLASS in parents:
            return True
        return any(derives(parent, seen | {name}) for parent in parents)

    return frozenset(name for name in bases_by_class if derives(name, frozenset()))


def _debt_in_class(node: ast.ClassDef, path: Path) -> list[TenantArgumentSite]:
    sites: list[TenantArgumentSite] = []
    for item in node.body:
        if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        arguments = [arg.arg for arg in (*item.args.args, *item.args.kwonlyargs)]
        if "tenant_id" not in arguments:
            continue
        if _uses_connection_context(item):
            continue
        sites.append(
            TenantArgumentSite(
                path=path, line=item.lineno, qualified_name=f"{node.name}.{item.name}"
            )
        )
    return sites


def _uses_connection_context(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Metod `self._tenant` və ya `self._require_matching_tenant` işlədirmi."""
    return any(
        isinstance(child, ast.Attribute)
        and child.attr in _SAFE_ATTRIBUTES
        and isinstance(child.value, ast.Name)
        and child.value.id == "self"
        for child in ast.walk(node)
    )


def _parse(path: Path) -> ast.Module | None:
    """Faylı AST-ə çevirir; oxuna/parse edilə bilmirsə `None`.

    Xəta UDULUR və bu, qəsdlidir: sayğac diaqnostika alətidir, bir sınıq faylın
    onu çökdürməsi ölçünün ÜMUMİYYƏTLƏ alınmaması demək olardı. Sınıq fayl
    onsuz da `ruff`/`mypy` qapılarında görünür.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


__all__ = [
    "TENANT_ARGUMENT_DEBT_CEILING",
    "TenantArgumentSite",
    "format_debt_report",
    "infrastructure_root",
    "scan_tenant_argument_debt",
]
