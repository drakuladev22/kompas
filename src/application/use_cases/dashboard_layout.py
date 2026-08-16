"""Panel Qurucusu — konfiqurasiya edilə bilən widget şəbəkəsi (bölmə 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR WIDGET BİR İCAZƏYƏ BAĞLIDIR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3-ün əsas prinsipi: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI". İdarə Paneli bunun ən
asan pozulan yeridir — orada məlumat XÜLASƏ şəklindədir və "onsuz da ümumi
rəqəmdir" deyə süzgəci atlamaq cazibədardır. Halbuki "bu ay 12 cərimə" rəqəmi
cərimə görməyə icazəsi olmayan işçi üçün elə həmin məlumatdır.

Ona görə kataloqun ÖZÜ süzülür: istifadəçi görmədiyi widget-i qurucuda da
görmür və onu düzülüşünə əlavə edə bilmir.

──────────────────────────────────────────────────────────────────────────────
SAXLANMAMIŞ DÜZÜLÜŞ (`None`) İLƏ BOŞ DÜZÜLÜŞ (`[]`) FƏRQLİDİR
──────────────────────────────────────────────────────────────────────────────
`None` → istifadəçi heç vaxt qurmayıb, DEFOLT göstərilir.
`[]`   → istifadəçi hər şeyi qəsdən gizlədib.

Fərq olmasaydı, "hamısını gizlət" əməliyyatı defolta qayıtma kimi görünərdi və
istifadəçi öz seçimini tətbiq edə bilməzdi (bax migration 011).

──────────────────────────────────────────────────────────────────────────────
REAL-TIME BURADA DEYİL
──────────────────────────────────────────────────────────────────────────────
Bu modul DÜZÜLÜŞÜ idarə edir, MƏLUMATI yox. Canlı yeniləmə
`infrastructure/realtime/` qatındadır — beləliklə düzülüş məntiqi WebSocket
olmadan test oluna bilir.

──────────────────────────────────────────────────────────────────────────────
ŞƏBƏKƏ (GRID) — NİYƏ KODLANMIŞ SƏTİR, NİYƏ JSON OBYEKTİ DEYİL (audit G-5)
──────────────────────────────────────────────────────────────────────────────
Bölmə 6 şəbəkə yerləşdirməsi (sətir/sütun + en) tələb edir; əvvəl yalnız
GÖRÜNÜRLÜK və XƏTTİ SIRA var idi. Yerləşdirmə `user_preferences.
dashboard_layout` JSONB sütununda saxlanılır və orada ARTIQ minlərlə köhnə
sətir var: `["stat_tiles", "fines_chart", ...]`.

Seçim iki forma arasında idi:

  A) Obyekt massivi — `[{"key": "stat_tiles", "row": 0, ...}]`. Təmiz
     modelləşdirmədir, LAKİN `DashboardLayoutStore` portunun tipini
     (`list[str]`) dəyişdirir: `PostgresUserPreferences._as_key_list` köhnə
     sətri `str(dict)` kimi oxuyardı və düzülüş bir buraxılışda "sınmış"
     görünərdi. Port dəyişikliyi həm də repo-nu, kompozisiya kökünü və
     testlərdəki sahtələri toxundurardı.

  B) KODLANMIŞ SƏTİR — `"stat_tiles@0,0,2"`. Element yenə `str`-dir, yəni
     port, repo, sxem CHECK-i (`jsonb_typeof = 'array'`) və sahtələr
     TOXUNULMAZ qalır. Formatsız köhnə element isə qanuni girişdir və
     TƏK SÜTUNLU şəbəkə kimi oxunur — yəni köhnə konfiqurasiya EYNİ
     görünüşü verir və heç bir miqrasiya `UPDATE`-i lazım deyil.

(B) seçildi. Naxış layihədə yenilik deyil: `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_
DAYS` ("30,14,7") və `PERFORMANCE_REVIEW_KPI_CATALOG` ("KOD:Ad;KOD:Ad") eyni
səbəbdən — bir-birinə aid hissələr BİRGƏ saxlanılır — kodlanmış sətirdir.

AYIRICI `@` SEÇİLDİ, `:` YOX: plugin-lərin verdiyi widget açarları
`plugin:<id>:<açar>` formasındadır (bax `presentation/plugin_surface.py`) və
`:` ilə ayırsaydıq açarın öz içindəki iki nöqtə formatı pozardı.

──────────────────────────────────────────────────────────────────────────────
GERİYƏ UYĞUNLUQ QAYDASI (bir cümlə ilə)
──────────────────────────────────────────────────────────────────────────────
Yerləşdirməsi OLMAYAN element → `row` = massivdəki mövqe, `column` = 0,
`span` = bütün sütunlar. Yəni xətti siyahı TAM-EN kartların şaquli yığınına
çevrilir və bu, dəyişiklikdən əvvəlki görünüşün eynisidir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import Clock
    from src.domain.value_objects.identifiers import EmployeeId

_log = get_logger(__name__)

#: Düzülüşü DƏYİŞMƏK üçün tələb olunan flag (bölmə 3, Task & Dashboard).
EDIT_WIDGETS_FLAG = "can_edit_dashboard_widgets"

#: Açar ilə yerləşdirməni ayıran işarə (bax modul başlığı — `:` NİYƏ YOX).
PLACEMENT_SEPARATOR: Final = "@"

#: Sütun sayının SƏRT hüdudları — migrations/058-dəki `min_value`/`max_value`
#: ilə EYNİ. İki mənbənin ayrılması ROOT ekranında "qəbul edilən", kodda isə
#: kəsilən dəyər demək olardı (`INFRA_LIMIT_BOUNDS` ilə eyni əsaslandırma).
MIN_GRID_COLUMNS: Final = 1
MAX_GRID_COLUMNS: Final = 4

#: Kodlanmış sonluqdakı hissə sayı — `sətir,sütun,en`.
_PLACEMENT_PARTS: Final = 3

#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits.DASHBOARD_GRID_COLUMNS`
#: (seed: migrations/058). Yalnız `limits` portu verilməyəndə (test, offline)
#: və ya oxu uğursuz olanda işə düşür.
FALLBACK_GRID_COLUMNS: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.DASHBOARD_GRID_COLUMNS])


class DashboardPermissionError(KompasOSError):
    """Panel düzülüşünü dəyişmək səlahiyyəti yoxdur."""

    user_message = "Panel düzülüşünü dəyişmək səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class DashboardWidget:
    """Bir panel bölməsinin tərifi."""

    key: str
    title_az: str
    description_az: str
    #: Görünmək üçün lazım olan icazə. `None` → hamı görür.
    required_flag: str | None = None
    #: Bağlı olduğu Feature Toggle modulu (`None` → toggle-dan asılı deyil).
    feature_module: str | None = None

    def is_visible_to(self, actor: Employee, *, now: datetime) -> bool:
        if self.required_flag is None:
            return True
        return actor.has_permission(self.required_flag, now=now)


#: Bölmə 6-dakı sadalama: "charts, leave gauges, points".
WIDGET_CATALOG: Final[tuple[DashboardWidget, ...]] = (
    DashboardWidget(
        key="stat_tiles",
        title_az="Rəqəm kartları",
        description_az="Mağazada olanlar, təsdiq gözləyənlər, cərimələr, tapşırıqlar.",
    ),
    DashboardWidget(
        key="fines_chart",
        title_az="Filial üzrə cərimə qrafiki",
        description_az="Bu ayın cərimələri filiallara görə.",
        required_flag="can_view_employee_reports",
        feature_module="fines",
    ),
    DashboardWidget(
        key="leave_gauge",
        title_az="İcazə limiti ölçəni",
        description_az="Aylıq icazə limitinin nə qədəri istifadə olunub.",
        feature_module="leave",
    ),
    DashboardWidget(
        key="points_leaderboard",
        title_az="Satış xalları lövhəsi",
        description_az="Cari 6 aylıq dövr üzrə liderlər.",
        feature_module="sales",
    ),
    DashboardWidget(
        key="server_health",
        title_az="Server sağlamlığı",
        description_az="1C serverlərinin sinxronizasiya vəziyyəti.",
        required_flag="can_view_system_health",
        feature_module="diagnostics",
    ),
    DashboardWidget(
        key="open_tasks",
        title_az="Açıq tapşırıqlar",
        description_az="Sizə təyin olunmuş və təsdiq gözləyən tapşırıqlar.",
        feature_module="tasks",
    ),
    # --- #24 Çox-Mağaza Benchmark Dashboard (kompasos11.md Faza 9A) --------- #
    #
    # DÖRDÜ DƏ `can_export_reports` İLƏ QAPILANIR — `menu.py`-dakı
    # "Hesabatlar" maddəsinin eyni flag-i (schema.sql §23 rol-defolt
    # cədvəlində DƏQİQ Root/CEO/Admin/HR_Admin dördlüyünə verilib,
    # Mağaza_Meneceri-də YOXDUR). Yeni flag YARADILMADI (bax `application.
    # use_cases.multi_store_benchmark` modul başlığı) — kataloqun ÖZÜ
    # süzülür ("GÖRMƏK = SƏLAHİYYƏTİN OLMASI", modul başlığı), yəni
    # Mağaza_Meneceri bu dörd widget-i Panel Qurucusunda GÖRMÜR və
    # düzülüşünə ƏLAVƏ EDƏ BİLMİR.
    DashboardWidget(
        key="ranking_table",
        title_az="Çox-Mağaza Reytinq Cədvəli",
        description_az=(
            "Bütün filialları seçilmiş göstəriciyə (cərimə/davamiyyət/xal/"
            "overtime/turnover) görə ən yaxşıdan ən pisə sıralayır."
        ),
        required_flag="can_export_reports",
    ),
    DashboardWidget(
        key="store_vs_network",
        title_az="Mağaza — Şəbəkə Ortalaması",
        description_az="Tək mağazanın göstəricisini şəbəkə ortalaması ilə yan-yana müqayisə edir.",
        required_flag="can_export_reports",
    ),
    DashboardWidget(
        key="metric_trend",
        title_az="Zaman-üzrə Trend",
        description_az="Seçilmiş göstəricinin son aylar üzrə dəyişimi, filial üzrə süzülə bilər.",
        required_flag="can_export_reports",
    ),
    DashboardWidget(
        key="benchmark_outliers",
        title_az="Kritik-Kənar (Outlier) Kartı",
        description_az=(
            "Şəbəkə ortalamasından statistik əhəmiyyətli dərəcədə kənar mağazaları tapır."
        ),
        required_flag="can_export_reports",
    ),
)

#: Defolt düzülüş — istifadəçi heç nə qurmayıbsa göstərilən sıra.
DEFAULT_LAYOUT: Final[tuple[str, ...]] = tuple(widget.key for widget in WIDGET_CATALOG)


def build_widget_catalog(extra: Sequence[DashboardWidget] = ()) -> tuple[DashboardWidget, ...]:
    """Əsas kataloq + plugin-lərin verdiyi widget-lər (audit G-3).

    ──────────────────────────────────────────────────────────────────────────
    AD TOQQUŞMASINDA PLUGIN UDUZUR
    ──────────────────────────────────────────────────────────────────────────
    Plugin `"stat_tiles"` açarı ilə widget elan edərsə, o, SÜKUTLA ATILIR və
    əsas kataloq sətri qalır. Əks qayda (plugin üstələyir) zərərli plugin-ə
    real bölməni öz saxtası ilə əvəz etmək imkanı verərdi — istifadəçi eyni
    başlığı görər, məzmun isə plugin-dən gələrdi.

    Plugin-lərin öz aralarındakı toqquşmada da BİRİNCİ qalır: sıra
    determinstikdir (`plugin_surface` naşir+ad üzrə sıralayır), yəni nəticə
    hər açılışda eynidir.
    """
    catalog: list[DashboardWidget] = list(WIDGET_CATALOG)
    seen = {widget.key for widget in catalog}
    for widget in extra:
        if widget.key in seen:
            _log.warning(
                "DASHBOARD_WIDGET_KEY_COLLISION",
                extra={"key": widget.key, "resolution": "əsas kataloq saxlanıldı"},
            )
            continue
        seen.add(widget.key)
        catalog.append(widget)
    return tuple(catalog)


class PluginWidgetProvider(Protocol):
    """Təsdiqlənmiş plugin-lərin dashboard widget-lərini verən mənbə.

    Protokol TƏTBİQ QATINDA təyin olunur, çünki nəticə tətbiq qatının
    strukturudur (`DashboardWidget`) — bax CLAUDE.md §3 "Port yalnız domen
    tipləri qaytarırsa `ports.py`-a gedir".
    """

    def dashboard_widgets(self) -> tuple[DashboardWidget, ...]: ...


@dataclass(frozen=True)
class WidgetPlacement:
    """Bir widget-in şəbəkədəki yeri (audit G-5).

    Attributes:
        key: Widget açarı.
        row: Sətir indeksi (0-dan).
        column: Sütun indeksi (0-dan).
        span: Neçə sütun tutur (ən azı 1).
    """

    key: str
    row: int
    column: int
    span: int

    def encode(self) -> str:
        """Saxlanma forması — `"acar@setir,sutun,en"` (bax modul başlığı)."""
        return f"{self.key}{PLACEMENT_SEPARATOR}{self.row},{self.column},{self.span}"

    def cells(self) -> tuple[tuple[int, int], ...]:
        """Tutduğu xanalar — toqquşma yoxlaması üçün."""
        return tuple((self.row, self.column + offset) for offset in range(self.span))


def split_entry(raw: str) -> tuple[str, tuple[int, int, int] | None]:
    """Saxlanmış elementi `(açar, yerləşdirmə | None)` cütünə ayırır.

    `None` YERLƏŞDİRMƏ NORMAL HALDIR — köhnə xətti sətir məhz belə görünür
    (bax modul başlığı, "GERİYƏ UYĞUNLUQ QAYDASI"). Yararsız rəqəm də `None`
    kimi oxunur: səhv format düzülüşü sındırmamalıdır, ən pisi widget öz
    xəttinə qayıdır.
    """
    key, separator, suffix = raw.partition(PLACEMENT_SEPARATOR)
    key = key.strip()
    if not separator:
        return key, None
    parts = suffix.split(",")
    if len(parts) != _PLACEMENT_PARTS:
        return key, None
    try:
        row, column, span = (int(part.strip()) for part in parts)
    except ValueError:
        _log.warning("DASHBOARD_PLACEMENT_UNREADABLE", extra={"entry": raw[:60]})
        return key, None
    return key, (row, column, span)


def normalize_placements(
    entries: Iterable[tuple[str, tuple[int, int, int] | None]],
    *,
    columns: int,
) -> tuple[WidgetPlacement, ...]:
    """Xam yerləşdirmələri ÜST-ÜSTƏ DÜŞMƏYƏN şəbəkəyə çevirir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ NORMALLAŞDIRMA MƏCBURİDİR
    ──────────────────────────────────────────────────────────────────────────
    Saxlanmış dəyər üç yolla "yanlış" ola bilər və heç biri istifadəçinin
    günahı deyil: (1) Root sütun sayını 3-dən 2-yə endirib — üçüncü sütundakı
    kartın yeri artıq yoxdur; (2) iki widget eyni xanaya düşüb (paralel
    sessiya, əl ilə redaktə); (3) fayl köhnə formatdadır. Hər üç halda ekran
    ÇÖKMƏMƏLİ, kart isə YOX OLMAMALIDIR — ona görə burada yer TAPILIR,
    istisna atılmır.

    BOŞ XANA QANUNİDİR: istifadəçi bir sətirdə tək kart saxlaya bilər və
    `QGridLayout` deşiyi sakitcə keçir. Yalnız ÖRTÜŞMƏ düzəldilir.
    """
    columns = max(MIN_GRID_COLUMNS, min(MAX_GRID_COLUMNS, columns))
    occupied: set[tuple[int, int]] = set()
    placed: list[WidgetPlacement] = []

    for index, (key, raw) in enumerate(entries):
        if raw is None:
            # Köhnə xətti element — TAM ENLİ sətir (bax modul başlığı).
            row, column, span = index, 0, columns
        else:
            row, column, span = raw
        column = max(0, min(columns - 1, column))
        span = max(1, min(columns - column, span))
        row = max(0, row)

        candidate = WidgetPlacement(key=key, row=row, column=column, span=span)
        if occupied.intersection(candidate.cells()):
            candidate = _first_free_slot(key, span=span, columns=columns, occupied=occupied)
        occupied.update(candidate.cells())
        placed.append(candidate)

    return tuple(sorted(placed, key=lambda item: (item.row, item.column)))


def _first_free_slot(
    key: str, *, span: int, columns: int, occupied: set[tuple[int, int]]
) -> WidgetPlacement:
    """Örtüşən kart üçün ilk boş xananı tapır (yuxarıdan aşağı, soldan sağa).

    Dövr HƏMİŞƏ bitir: hər sətirdə ən çox `columns` xana var və sətir sayı
    sərhədsizdir — yəni ən pis halda kart yeni sətrə düşür.
    """
    row = 0
    while True:
        for column in range(columns - span + 1):
            candidate = WidgetPlacement(key=key, row=row, column=column, span=span)
            if not occupied.intersection(candidate.cells()):
                return candidate
        row += 1


def collapse_to_single_column(
    placements: Sequence[WidgetPlacement],
) -> tuple[WidgetPlacement, ...]:
    """Dar pəncərə üçün şəbəkəni TƏK SÜTUNA yığır (`LayoutMode.COMPACT`).

    Oxunuş sırası SAXLANILIR: kartlar (sətir, sütun) üzrə sıralanır, yəni
    istifadəçinin geniş ekranda gördüyü "soldan sağa, yuxarıdan aşağı" ardıcıllığı
    dar ekranda şaquli sıraya çevrilir. Sıra dəyişsəydi, eyni panel iki ölçüdə
    iki fərqli hekayə danışardı.

    Funksiya SAFDIR və `widgets/responsive.py`-dəki mövcud mexanizmi ƏVƏZ
    ETMİR: rejimi yenə pəncərə ölçür və örtük paylayır (`Screen.
    apply_layout_mode`), bu funksiya isə yalnız həmin qərarın şəbəkəyə
    tətbiqidir.
    """
    ordered = sorted(placements, key=lambda item: (item.row, item.column))
    return tuple(
        WidgetPlacement(key=item.key, row=index, column=0, span=1)
        for index, item in enumerate(ordered)
    )


class DashboardLayoutStore(Protocol):
    """İstifadəçi üzrə düzülüşün saxlanması (`user_preferences.dashboard_layout`)."""

    def load(self, employee_id: EmployeeId) -> list[str] | None:
        """`None` → heç vaxt saxlanmayıb (defolt tətbiq olunur)."""
        ...

    def save(self, employee_id: EmployeeId, layout: list[str]) -> None: ...


class FeatureGate(Protocol):
    """`FeatureToggles`-ın yalnız lazım olan hissəsi."""

    def is_enabled(self, tenant_id: object, module_key: str) -> bool: ...


class LimitReader(Protocol):
    """`SystemLimits`-in yalnız lazım olan hissəsi (`FeatureGate` ilə eyni naxış).

    Tam portu tələb etmirik: bu use case `set_value`/`describe` çağırmır və
    onları tələb etmək sahtələri lazımsız böyüdərdi.
    """

    def get_int(self, tenant_id: object, key: str, default: int) -> int: ...


@dataclass(frozen=True)
class DashboardView:
    """Ekranın göstərdiyi hazır düzülüş."""

    available: tuple[DashboardWidget, ...]
    order: tuple[str, ...]
    visible: frozenset[str]
    is_default: bool
    #: Şəbəkə yerləşdirməsi (audit G-5). DEFOLT BOŞDUR VƏ BU, QƏSDƏNDİR:
    #: sahə mövcud çağırış nöqtələrinin heç birini dəyişmir — `order`/`visible`
    #: əvvəlki mənasını (SIRA və GÖRÜNÜRLÜK) tam saxlayır.
    placements: tuple[WidgetPlacement, ...] = ()
    #: Şəbəkənin sütun sayı (ROOT: `DASHBOARD_GRID_COLUMNS`).
    columns: int = FALLBACK_GRID_COLUMNS

    def ordered_visible(self) -> list[str]:
        return [key for key in self.order if key in self.visible]

    def catalog_map(self) -> dict[str, tuple[str, str]]:
        """Qurucu ekranının gözlədiyi `açar → (başlıq, izah)` xəritəsi."""
        return {w.key: (w.title_az, w.description_az) for w in self.available}

    def placement_map(self) -> dict[str, tuple[int, int, int]]:
        """Qurucu ekranının gözlədiyi `açar → (sətir, sütun, en)` xəritəsi."""
        return {item.key: (item.row, item.column, item.span) for item in self.placements}

    def encoded_layout(self) -> list[str]:
        """GÖRÜNƏN widget-lərin saxlanma forması — `save()`-a birbaşa verilə bilər."""
        return [item.encode() for item in self.placements if item.key in self.visible]


class DashboardLayoutUseCase:
    """Düzülüşü yükləyir, süzür və saxlayır."""

    def __init__(
        self,
        *,
        store: DashboardLayoutStore,
        clock: Clock,
        toggles: FeatureGate | None = None,
        limits: LimitReader | None = None,
        plugin_widgets: PluginWidgetProvider | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._toggles = toggles
        # `limits` YOXDURSA fallback sütun sayı işləyir — `toggles` ilə eyni
        # fail-safe istiqamət: konfiqurasiya mənbəyinin olmaması paneli
        # boşaltmamalıdır (bax `_module_enabled`).
        self._limits = limits
        self._plugin_widgets = plugin_widgets

    def view_for(self, *, actor: Employee, tenant_id: object) -> DashboardView:
        """İstifadəçinin görə biləcəyi widget-lər + onun düzülüşü."""
        now = self._clock.now()
        columns = self._grid_columns(tenant_id)
        # `DASHBOARD_BUILDER` söndürülübsə heç bir widget təklif edilmir —
        # ekran onsuz da naviqasiyadan kəsilir (bölmə 3), lakin birbaşa
        # çağırış yolu da eyni nəticəni verməlidir.
        if not self._builder_enabled(tenant_id):
            return DashboardView(
                available=(),
                order=(),
                visible=frozenset(),
                is_default=True,
                columns=columns,
            )

        available = tuple(
            widget
            for widget in self._catalog()
            if widget.is_visible_to(actor, now=now) and self._module_enabled(widget, tenant_id)
        )
        allowed = {widget.key for widget in available}

        stored = self._store.load(actor.id)
        is_default = stored is None
        raw_entries = list(DEFAULT_LAYOUT) if stored is None else list(stored)
        parsed = [split_entry(entry) for entry in raw_entries]

        # Kataloqda olmayan açar SÜZÜLÜR: modul söndürüldükdə və ya icazə
        # geri alındıqda köhnə düzülüş həmin bölməni yenidən açmamalıdır.
        parsed = [item for item in parsed if item[0] in allowed]
        known = {key for key, _ in parsed}
        # Kataloqa YENİ əlavə olunmuş widget sona düşür — yerləşdirməsi hələ
        # yoxdur, yəni tam enli sətir alır (bax `normalize_placements`).
        parsed += [(widget.key, None) for widget in available if widget.key not in known]

        order = [key for key, _ in parsed]
        # GÖRÜNÜRLÜK SAXLANMIŞ DƏSTDƏN GƏLİR: `None` (heç vaxt qurmayıb) →
        # hamısı görünür; boş massiv → heç biri (migration 011-in qərarı).
        stored_keys = {split_entry(entry)[0] for entry in stored} if stored is not None else None
        visible = allowed if stored_keys is None else {key for key in order if key in stored_keys}

        return DashboardView(
            available=available,
            order=tuple(order),
            visible=frozenset(visible),
            is_default=is_default,
            placements=normalize_placements(parsed, columns=columns),
            columns=columns,
        )

    def save(self, *, actor: Employee, tenant_id: object, layout: list[str]) -> DashboardView:
        """Yeni düzülüşü saxlayır — icazəsiz açarlar ATILIR.

        Süzgəc burada da tətbiq olunur, ekranda da: ekran yan keçilə bilər
        (skript, gələcək API), bu qat isə son qapıdır.

        `layout` elementləri HƏM sadə açar (`"stat_tiles"`), HƏM DƏ kodlanmış
        yerləşdirmə (`"stat_tiles@0,0,2"`) ola bilər — ekranın köhnə çağırışı
        DƏYİŞMƏDƏN işləməyə davam edir (bax modul başlığı).
        """
        self._require_edit_permission(actor)
        view = self.view_for(actor=actor, tenant_id=tenant_id)
        allowed = {widget.key for widget in view.available}

        cleaned: list[tuple[str, tuple[int, int, int] | None]] = []
        seen: set[str] = set()
        dropped: list[str] = []
        for entry in layout:
            key, placement = split_entry(entry)
            if key not in allowed:
                dropped.append(key)
                continue
            if key in seen:
                continue
            seen.add(key)
            cleaned.append((key, placement))

        if dropped:
            _log.warning(
                "DASHBOARD_LAYOUT_KEYS_DROPPED",
                extra={"employee_id": str(actor.id), "dropped": dropped},
            )

        placements = normalize_placements(cleaned, columns=view.columns)
        keys = [key for key, _ in cleaned]

        # ──────────────────────────────────────────────────────────────────
        # SAXLANMA FORMASI GİRİŞƏ GÖRƏ SEÇİLİR
        # ──────────────────────────────────────────────────────────────────
        # Çağırışda HEÇ BİR yerləşdirmə yoxdursa (köhnə ekran, skript, tək
        # sütunlu şəbəkə) sətir ƏVVƏLKİ KİMİ sadə açar massivi olaraq yazılır.
        # Bu, sırf geriyə uyğunluq üçündür: mövcud çağırışın bazadakı izi
        # DƏYİŞMİR, yəni köhnə oxucular (miqrasiya skriptləri, əl ilə SQL
        # sorğuları) sınmır.
        #
        # Ən azı bir yerləşdirmə gəlibsə, HAMISI kodlanmış yazılır —
        # normallaşdırılmış yer geri yazılmasaydı, Root sütun sayını
        # dəyişdikdən sonra istifadəçi ekranda bir düzülüş görər, bazada isə
        # başqası qalardı.
        has_grid = any(placement is not None for _, placement in cleaned)
        self._store.save(
            actor.id,
            [item.encode() for item in placements] if has_grid else keys,
        )
        return DashboardView(
            available=view.available,
            order=tuple(keys + [k for k in view.order if k not in seen]),
            visible=frozenset(keys),
            is_default=False,
            placements=placements,
            columns=view.columns,
        )

    def reset(self, *, actor: Employee, tenant_id: object) -> DashboardView:
        """Defolt düzülüşə qaytarır.

        Saxlanan sətir SİLİNMİR, defolt sıra YAZILIR: silmə "heç vaxt
        qurmayıb" vəziyyətini bərpa edərdi, halbuki istifadəçi qəsdən
        defolta qayıdıb — bu, onun seçimidir.
        """
        self._require_edit_permission(actor)
        view = self.view_for(actor=actor, tenant_id=tenant_id)
        default = [widget.key for widget in view.available]
        # DEFOLT = XƏTTİ = TƏK SÜTUN. Sadə açar (yerləşdirməsiz) yazılır,
        # kodlanmış sətir YOX: "defolta qayıt" istifadəçinin qurduğu şəbəkəni
        # silmək deməkdir və nəticə paketdən çıxan görünüşün eynisi olmalıdır.
        self._store.save(actor.id, default)
        return DashboardView(
            available=view.available,
            order=tuple(default),
            visible=frozenset(default),
            is_default=True,
            placements=normalize_placements([(key, None) for key in default], columns=view.columns),
            columns=view.columns,
        )

    def _require_edit_permission(self, actor: Employee) -> None:
        """`can_edit_dashboard_widgets` — bölmə 3 kataloqundakı redaktə qapısı.

        BAXIŞ (`view_for`) bu flag-i TƏLƏB ETMİR: hər istifadəçi öz
        panelini görməlidir. Yalnız DÜZÜLÜŞÜ DƏYİŞMƏK məhduddur — əks
        halda flag-siz istifadəçi boş ekran görərdi və bunun səbəbi ona
        izahsız qalardı.
        """
        if not actor.has_permission(EDIT_WIDGETS_FLAG, now=self._clock.now()):
            _log.warning(
                "DASHBOARD_EDIT_DENIED",
                extra={"employee_id": str(actor.id), "flag": EDIT_WIDGETS_FLAG},
            )
            raise DashboardPermissionError(
                f"«{EDIT_WIDGETS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )

    def _builder_enabled(self, tenant_id: object) -> bool:
        """`DASHBOARD_BUILDER` Feature Toggle-ı (bölmə 3, 6).

        Toggle mənbəyi qoşulmayıbsa AÇIQ sayılır — widget-lərdəki eyni
        fail-safe istiqaməti (bax `_module_enabled`).
        """
        if self._toggles is None:
            return True
        return self._toggles.is_enabled(tenant_id, FeatureModule.DASHBOARD_BUILDER.value)

    def _module_enabled(self, widget: DashboardWidget, tenant_id: object) -> bool:
        """Feature Toggle yoxlaması — port verilməyibsə HAMISI açıq sayılır.

        Fail-safe istiqaməti: toggle mənbəyinin olmaması bütün paneli
        boşaltmamalıdır.
        """
        if widget.feature_module is None or self._toggles is None:
            return True
        return self._toggles.is_enabled(tenant_id, widget.feature_module)

    def _catalog(self) -> tuple[DashboardWidget, ...]:
        """Əsas kataloq + plugin widget-ləri (audit G-3).

        PLUGIN İSTİSNASI PANELİ ÇÖKDÜRMÜR: mənbə oxuna bilmirsə yalnız əsas
        kataloq qaytarılır. Alternativ (istisnanı yuxarı buraxmaq) bir
        plugin-in nasazlığını bütün İdarə Panelinin nasazlığına çevirərdi.
        """
        if self._plugin_widgets is None:
            return WIDGET_CATALOG
        try:
            extra = self._plugin_widgets.dashboard_widgets()
        except Exception:
            _log.exception("PLUGIN_WIDGETS_UNAVAILABLE")
            return WIDGET_CATALOG
        return build_widget_catalog(extra)

    def _grid_columns(self, tenant_id: object) -> int:
        """`DASHBOARD_GRID_COLUMNS` — ROOT-dan, oxuna bilmirsə fallback.

        Oxu uğursuzluğu paneli DAYANDIRMIR: verilməli cavab "panel açılsınmı"
        deyil, "neçə sütunla" idi (`InfrastructureLimits._raw` ilə eyni
        əsaslandırma). Dəyər hüduda SIXILIR — Root 9 yazsa, 1280px pəncərədə
        kartlar oxunmaz olardı.
        """
        if self._limits is None:
            return FALLBACK_GRID_COLUMNS
        try:
            raw = self._limits.get_int(
                tenant_id, SystemLimitKey.DASHBOARD_GRID_COLUMNS.value, FALLBACK_GRID_COLUMNS
            )
        except Exception:
            _log.exception("DASHBOARD_GRID_COLUMNS_READ_FAILED")
            return FALLBACK_GRID_COLUMNS
        return max(MIN_GRID_COLUMNS, min(MAX_GRID_COLUMNS, int(raw)))


__all__ = [
    "DEFAULT_LAYOUT",
    "EDIT_WIDGETS_FLAG",
    "FALLBACK_GRID_COLUMNS",
    "MAX_GRID_COLUMNS",
    "MIN_GRID_COLUMNS",
    "PLACEMENT_SEPARATOR",
    "WIDGET_CATALOG",
    "DashboardLayoutStore",
    "DashboardLayoutUseCase",
    "DashboardPermissionError",
    "DashboardView",
    "DashboardWidget",
    "FeatureGate",
    "LimitReader",
    "PluginWidgetProvider",
    "WidgetPlacement",
    "build_widget_catalog",
    "collapse_to_single_column",
    "normalize_placements",
    "split_entry",
]
