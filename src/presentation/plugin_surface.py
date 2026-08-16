"""Plugin-lərin İNTERFEYS SƏTHİ — səhifə və widget qeydiyyatı (audit G-3).

──────────────────────────────────────────────────────────────────────────────
BU MODUL NİYƏ VAR
──────────────────────────────────────────────────────────────────────────────
Plugin API iki qabiliyyəti ELAN edirdi — `PluginCapability.REGISTER_PAGE` və
`RENDER_WIDGET` — lakin onların İSTEHLAKÇISI yox idi: `shell/menu.py`-dakı
`DEFAULT_ENTRIES` və `use_cases/dashboard_layout.WIDGET_CATALOG` sabit
`tuple`-dur. Yəni imzalanmış, təsdiqlənmiş plugin belə nə menyu maddəsi, nə də
panel bölməsi əlavə edə bilmirdi. Qabiliyyət sənəddə vardı, icrada yox.

Bu modul həmin boşluğu bağlayır və PySide6-dan ASILI DEYİL (`navigation.py`
ilə eyni qərar): burada yalnız filtrləmə və adlandırma məntiqi var, ona görə
qaydalar GUI olmadan test oluna bilir.

──────────────────────────────────────────────────────────────────────────────
BEŞ QAPI — HƏR BİRİ AYRICA POZULA BİLƏR
──────────────────────────────────────────────────────────────────────────────
1. **İMZA + TƏSDİQ** — yalnız `status = APPROVED` VƏ `signature_verified`
   olan plugin səth verir. `PENDING_APPROVAL` plugin quraşdırılıb, lakin Root
   hələ razılıq verməyib; onun menyuda görünməsi təsdiq addımını mənasız
   edərdi. Etibar reyestri boşdursa (`KOMPASOS_PLUGIN_TRUSTED_PUBLISHERS`
   təyin edilməyib) plugin onsuz da heç vaxt quraşdırıla bilmir — fail-closed
   qayda BU MODULDA DA POZULMUR, çünki burada yalnız ARTIQ imza yoxlamasından
   keçmiş sətirlər emal olunur.

2. **QABİLİYYƏT** — səhifə üçün `REGISTER_PAGE`, widget üçün `RENDER_WIDGET`
   manifestdə OLMALIDIR. Manifest imzanın içindədir (bax `plugins/
   signature.py: canonical_payload`), yəni quraşdırmadan sonra əlavə edilə
   bilməz.

3. **İCAZƏ FLAG-İ MƏCBURİDİR** — `manifest.required_flags` BOŞDURSA səth
   RƏDD EDİLİR. "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (bölmə 3) plugin səhifəsinə də
   aiddir; flagsız maddə HƏR istifadəçiyə render olunardı və plugin beləliklə
   səlahiyyət sistemini yan keçən bir pəncərə açardı. Flag-lərin HAMISI tələb
   olunur (`MenuEntry.required_flags`), biri deyil.

4. **AD TOQQUŞMASINDA PLUGIN UDUZUR** — açar məcburi `plugin:<id>` ad
   məkanındadır, yəni `live_queue` və ya `fines` açarını ƏLƏ KEÇİRMƏK mümkün
   deyil. Buna baxmayaraq qeydiyyat da müdafiə edir: mövcud açar varsa plugin
   maddəsi ATILIR (bax `register_plugin_pages`). İki qat lazımdır, çünki
   birinci qat ad sxemindən, ikincisi isə reyestrin faktiki vəziyyətindən
   asılıdır.

5. **İZOLYASİYA** — hər plugin AYRICA `try/except` içində emal olunur.
   Yararsız manifest, naməlum capability, hətta gözlənilməz istisna yalnız
   HƏMİN plugin-i səthdən kənarda saxlayır; qalan plugin-lər və əsas UI
   toxunulmaz qalır. Alternativ (istisnanı yuxarı buraxmaq) bir korlanmış
   sətrin bütün naviqasiyanı çökdürməsi demək olardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR PLUGIN ÜÇÜN BİR SƏHİFƏ, MANİFESTDƏ SƏHİFƏ SİYAHISI YOX
──────────────────────────────────────────────────────────────────────────────
`PluginManifest` İMZALANIR: `to_dict()` çıxışı kanonik yükün bir hissəsidir.
Ona yeni sahə (`pages: [...]`) əlavə etmək MÖVCUD imzaların hamısını
etibarsız edərdi — quraşdırılmış hər plugin bir buraxılışda "imza uyğun
gəlmir" ilə bloklanardı. Ona görə səhifə manifestin MÖVCUD sahələrindən
qurulur: açar `plugin:<plugin_id>`, başlıq `manifest.name`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.application.use_cases.dashboard_layout import DashboardWidget
from src.infrastructure.plugins.contracts import PluginCapability, PluginStatus
from src.presentation.navigation import MenuEntry
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.application.use_cases.plugin_management import PluginRegistry
    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.plugins.contracts import PluginManifest
    from src.presentation.navigation import NavigationRegistry

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Plugin açarlarının MƏCBURİ ad məkanı — heç bir əsas ekran açarı `plugin:`
#: ilə başlamır (bax `shell/menu.py: DEFAULT_ENTRIES`), yəni toqquşma sxem
#: səviyyəsində mümkün deyil.
PLUGIN_KEY_PREFIX: Final = "plugin:"

#: Plugin maddələrinin menyu sırası. Əsas maddələrin ən böyüyü 210-dur
#: (`profile`), ona görə 900-dən başlayan diapazon plugin-in HEÇ BİR əsas
#: maddəni yuxarı-aşağı sürüşdürə bilməməsini təmin edir.
PLUGIN_MENU_ORDER_BASE: Final = 900

#: Plugin maddəsinin ikonu — dizayn dəstində MÖVCUD olan `grid` (Plugin-lər
#: ekranı ilə eynidir, yeni ikon əlavə edilmir).
PLUGIN_ICON: Final = "grid"


def plugin_page_key(plugin_id: str) -> str:
    """Plugin səhifəsinin ekran açarı — MAKET və CANLI yol EYNİ funksiyanı çağırır.

    Ad məkanı bir yerdə qurulur, çünki iki yerdə qurulsaydı maket `"plugin_x"`,
    canlı yol isə `"plugin:x"` işlədə bilərdi və uyğunsuzluq yalnız
    istehsalatda üzə çıxardı (CLAUDE.md bölmə 6, `menu.py` başlığındakı tarixi
    qüsur).
    """
    return f"{PLUGIN_KEY_PREFIX}{plugin_id}"


def plugin_widget_key(plugin_id: str) -> str:
    """Plugin widget-inin dashboard kataloq açarı."""
    return f"{PLUGIN_KEY_PREFIX}{plugin_id}:widget"


@dataclass(frozen=True)
class ApprovedPlugin:
    """Səth qura biləcək plugin sətri — `plugins` cədvəlinin oxu forması.

    `InstalledPlugin`-dən FƏRQİ manifestin ÖZÜNÜN daşınmasıdır: qabiliyyət və
    tələb olunan flag-lər yalnız orada yaşayır və ikisi də səth qərarının
    girişidir.
    """

    plugin_id: str
    name: str
    publisher: str
    status: PluginStatus
    signature_verified: bool
    manifest: PluginManifest


@dataclass(frozen=True)
class PluginPage:
    """Plugin-in menyuya əlavə etdiyi bir səhifə."""

    plugin_id: str
    plugin_name: str
    publisher: str
    key: str
    title_az: str
    required_flags: frozenset[str]
    capabilities: frozenset[str]

    def to_menu_entry(self, *, order: int) -> MenuEntry:
        """`NavigationRegistry`-nin gözlədiyi maddə.

        `required_flag` MƏCBURİ olaraq doldurulur (siyahının ilk elementi) —
        `required_flags` isə qalanlarını daşıyır və reyestr onların HAMISINI
        yoxlayır. İkiyə bölünmə mövcud sahənin (`required_flag`) semantikasını
        POZMAMAQ üçündür: bütün mövcud maddələr və testlər ona bağlıdır.
        """
        ordered = sorted(self.required_flags)
        return MenuEntry(
            key=self.key,
            title_az=self.title_az,
            required_flag=ordered[0],
            required_flags=frozenset(ordered[1:]),
            order=order,
            icon=PLUGIN_ICON,
        )


@dataclass(frozen=True)
class PluginSurface:
    """Bütün təsdiqlənmiş plugin-lərin birgə səthi."""

    pages: tuple[PluginPage, ...] = ()
    widgets: tuple[DashboardWidget, ...] = ()

    def page_for(self, key: str) -> PluginPage | None:
        return next((page for page in self.pages if page.key == key), None)


def collect_surface(records: Iterable[ApprovedPlugin]) -> PluginSurface:
    """Səthi qurur — beş qapının hamısı burada tətbiq olunur (bax modul başlığı).

    Sıra DETERMİNSTİKDİR (naşir, ad, id): eyni quraşdırma hər açılışda eyni
    menyunu verməlidir, əks halda "maddə yerini dəyişdi" şikayəti izahsız
    qalardı.
    """
    pages: list[PluginPage] = []
    widgets: list[DashboardWidget] = []

    for record in sorted(records, key=lambda item: (item.publisher, item.name, item.plugin_id)):
        try:
            _collect_one(record, pages=pages, widgets=widgets)
        except Exception:
            # İZOLYASİYA (qapı 5): bir sətrin nasazlığı qalan plugin-ləri və
            # əsas UI-ni çökdürməməlidir.
            _log.exception(
                "PLUGIN_SURFACE_SKIPPED",
                extra={"plugin_id": record.plugin_id, "plugin": record.name},
            )

    return PluginSurface(pages=tuple(pages), widgets=tuple(widgets))


def _collect_one(
    record: ApprovedPlugin,
    *,
    pages: list[PluginPage],
    widgets: list[DashboardWidget],
) -> None:
    """Bir plugin-in səthi — qapıların hər biri AYRICA jurnal sətri yazır."""
    if record.status is not PluginStatus.APPROVED or not record.signature_verified:
        _security_log.info(
            "PLUGIN_SURFACE_DENIED_STATUS",
            extra={
                "plugin": record.name,
                "status": record.status.value,
                "signature_verified": record.signature_verified,
            },
        )
        return

    manifest = record.manifest
    flags = frozenset(flag.strip() for flag in manifest.required_flags if flag.strip())
    capabilities = frozenset(capability.value for capability in manifest.capabilities)

    wants_page = PluginCapability.REGISTER_PAGE in manifest.capabilities
    wants_widget = PluginCapability.RENDER_WIDGET in manifest.capabilities
    if not (wants_page or wants_widget):
        return

    if not flags:
        # QAPI 3 — flagsız səth "GÖRMƏK = SƏLAHİYYƏTİN OLMASI"-nı pozardı.
        _security_log.warning(
            "PLUGIN_SURFACE_DENIED_NO_FLAG",
            extra={"plugin": record.name, "publisher": record.publisher},
        )
        return

    if wants_page:
        pages.append(
            PluginPage(
                plugin_id=record.plugin_id,
                plugin_name=record.name,
                publisher=record.publisher,
                key=plugin_page_key(record.plugin_id),
                title_az=record.name,
                required_flags=flags,
                capabilities=capabilities,
            )
        )

    if wants_widget:
        widgets.append(
            DashboardWidget(
                key=plugin_widget_key(record.plugin_id),
                title_az=record.name,
                description_az=(
                    manifest.description_az.strip()
                    or f"«{record.publisher}» plugin-inin panel bölməsi."
                ),
                # WIDGET DƏ FLAG TƏLƏB EDİR: `DashboardWidget` yalnız BİR
                # flag daşıyır, ona görə əlifba üzrə ilki seçilir. Səhifə
                # tərəfi ilə fərq QƏSDƏNDİR — panel bölməsi ayrıca bir
                # pəncərə açmır, mövcud paneldə bir kartdır; buna baxmayaraq
                # flagsız QALMIR.
                required_flag=sorted(flags)[0],
            )
        )


def register_plugin_pages(registry: NavigationRegistry, pages: Iterable[PluginPage]) -> int:
    """Səhifələri mövcud reyestrə ƏLAVƏ edir — heç nə əvəz etmir.

    Returns:
        Faktiki qeydiyyatdan keçən maddə sayı.

    AD TOQQUŞMASINDA PLUGIN UDUZUR (qapı 4): reyestrdə həmin açar varsa maddə
    ATILIR və `PLUGIN_MENU_KEY_TAKEN` yazılır. `NavigationRegistry.register`
    təkrar açarda istisna atır — onu burada TUTURUQ, çünki plugin nasazlığı
    örtüyün qurulmasını dayandırmamalıdır (qapı 5).
    """
    registered = 0
    for offset, page in enumerate(pages):
        if registry.get(page.key) is not None:
            _security_log.warning(
                "PLUGIN_MENU_KEY_TAKEN",
                extra={"key": page.key, "plugin": page.plugin_name},
            )
            continue
        try:
            registry.register(page.to_menu_entry(order=PLUGIN_MENU_ORDER_BASE + offset))
        except Exception:
            _log.exception(
                "PLUGIN_MENU_REGISTRATION_FAILED",
                extra={"key": page.key, "plugin": page.plugin_name},
            )
            continue
        registered += 1
    return registered


class PluginRegistrySurface:
    """`plugins` cədvəlindən səth quran adapter (`PluginWidgetProvider`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TƏTBİQ QATINDA DEYİL
    ──────────────────────────────────────────────────────────────────────────
    `DashboardLayoutUseCase` yalnız bir PROTOKOL (`PluginWidgetProvider`)
    tanıyır; onun konkret tətbiqi menyu qaydaları ilə eyni yerdə — burada —
    yaşayır, çünki səhifə və widget qərarları EYNİ beş qapıdan keçir. İki
    yerə bölünsəydi, biri yenilənəndə digəri sükutla köhnəlirdi.

    Sessiya SAXLAMIR: repo obyektini alır və hər çağırışda ondan oxuyur
    (repo onsuz da açıq tranzaksiyaya bağlıdır — `composition.py` naxışı).
    """

    def __init__(self, registry: PluginRegistry, tenant_id: TenantId) -> None:
        self._registry = registry
        self._tenant_id = tenant_id

    def surface(self) -> PluginSurface:
        """Təsdiqlənmiş plugin-lərin səthi; oxuna bilmirsə BOŞ.

        Oxu uğursuzluğu BOŞ SƏTHƏ çevrilir, istisnaya YOX: plugin cədvəlinin
        əlçatmazlığı naviqasiyanı və İdarə Panelini dayandırmamalıdır —
        fail-closed istiqamət onsuz da qorunur (səth olmayanda plugin heç nə
        əlavə etmir).
        """
        try:
            rows = self._registry.list_all(self._tenant_id)
        except Exception:
            _log.exception("PLUGIN_SURFACE_SOURCE_UNAVAILABLE")
            return PluginSurface()

        records = [
            ApprovedPlugin(
                plugin_id=row.plugin_id,
                name=row.name,
                publisher=row.publisher,
                status=row.status,
                signature_verified=row.signature_verified,
                manifest=row.manifest,
            )
            for row in rows
            if row.manifest is not None
        ]
        return collect_surface(records)

    def dashboard_widgets(self) -> tuple[DashboardWidget, ...]:
        """`PluginWidgetProvider` protokolu."""
        return self.surface().widgets


__all__ = [
    "PLUGIN_ICON",
    "PLUGIN_KEY_PREFIX",
    "PLUGIN_MENU_ORDER_BASE",
    "ApprovedPlugin",
    "PluginPage",
    "PluginRegistrySurface",
    "PluginSurface",
    "collect_surface",
    "plugin_page_key",
    "plugin_widget_key",
    "register_plugin_pages",
]
