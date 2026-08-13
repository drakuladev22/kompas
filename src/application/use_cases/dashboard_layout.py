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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from src.domain.policies import FeatureModule
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import Clock
    from src.domain.value_objects.identifiers import EmployeeId

_log = get_logger(__name__)

#: Düzülüşü DƏYİŞMƏK üçün tələb olunan flag (bölmə 3, Task & Dashboard).
EDIT_WIDGETS_FLAG = "can_edit_dashboard_widgets"


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


class DashboardLayoutStore(Protocol):
    """İstifadəçi üzrə düzülüşün saxlanması (`user_preferences.dashboard_layout`)."""

    def load(self, employee_id: EmployeeId) -> list[str] | None:
        """`None` → heç vaxt saxlanmayıb (defolt tətbiq olunur)."""
        ...

    def save(self, employee_id: EmployeeId, layout: list[str]) -> None: ...


class FeatureGate(Protocol):
    """`FeatureToggles`-ın yalnız lazım olan hissəsi."""

    def is_enabled(self, tenant_id: object, module_key: str) -> bool: ...


@dataclass(frozen=True)
class DashboardView:
    """Ekranın göstərdiyi hazır düzülüş."""

    available: tuple[DashboardWidget, ...]
    order: tuple[str, ...]
    visible: frozenset[str]
    is_default: bool

    def ordered_visible(self) -> list[str]:
        return [key for key in self.order if key in self.visible]

    def catalog_map(self) -> dict[str, tuple[str, str]]:
        """Qurucu ekranının gözlədiyi `açar → (başlıq, izah)` xəritəsi."""
        return {w.key: (w.title_az, w.description_az) for w in self.available}


class DashboardLayoutUseCase:
    """Düzülüşü yükləyir, süzür və saxlayır."""

    def __init__(
        self,
        *,
        store: DashboardLayoutStore,
        clock: Clock,
        toggles: FeatureGate | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._toggles = toggles

    def view_for(self, *, actor: Employee, tenant_id: object) -> DashboardView:
        """İstifadəçinin görə biləcəyi widget-lər + onun düzülüşü."""
        now = self._clock.now()
        # `DASHBOARD_BUILDER` söndürülübsə heç bir widget təklif edilmir —
        # ekran onsuz da naviqasiyadan kəsilir (bölmə 3), lakin birbaşa
        # çağırış yolu da eyni nəticəni verməlidir.
        if not self._builder_enabled(tenant_id):
            return DashboardView(available=(), order=(), visible=frozenset(), is_default=True)

        available = tuple(
            widget
            for widget in WIDGET_CATALOG
            if widget.is_visible_to(actor, now=now) and self._module_enabled(widget, tenant_id)
        )
        allowed = {widget.key for widget in available}

        stored = self._store.load(actor.id)
        is_default = stored is None
        order = list(DEFAULT_LAYOUT) if stored is None else list(stored)

        # Kataloqda olmayan açar SÜZÜLÜR: modul söndürüldükdə və ya icazə
        # geri alındıqda köhnə düzülüş həmin bölməni yenidən açmamalıdır.
        order = [key for key in order if key in allowed]
        order += [widget.key for widget in available if widget.key not in order]

        visible = allowed if stored is None else {key for key in stored if key in allowed}

        return DashboardView(
            available=available,
            order=tuple(order),
            visible=frozenset(visible),
            is_default=is_default,
        )

    def save(self, *, actor: Employee, tenant_id: object, layout: list[str]) -> DashboardView:
        """Yeni düzülüşü saxlayır — icazəsiz açarlar ATILIR.

        Süzgəc burada da tətbiq olunur, ekranda da: ekran yan keçilə bilər
        (skript, gələcək API), bu qat isə son qapıdır.
        """
        self._require_edit_permission(actor)
        view = self.view_for(actor=actor, tenant_id=tenant_id)
        allowed = {widget.key for widget in view.available}

        cleaned: list[str] = []
        for key in layout:
            if key in allowed and key not in cleaned:
                cleaned.append(key)

        dropped = [key for key in layout if key not in allowed]
        if dropped:
            _log.warning(
                "DASHBOARD_LAYOUT_KEYS_DROPPED",
                extra={"employee_id": str(actor.id), "dropped": dropped},
            )

        self._store.save(actor.id, cleaned)
        return DashboardView(
            available=view.available,
            order=tuple(cleaned + [k for k in view.order if k not in cleaned]),
            visible=frozenset(cleaned),
            is_default=False,
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
        self._store.save(actor.id, default)
        return DashboardView(
            available=view.available,
            order=tuple(default),
            visible=frozenset(default),
            is_default=True,
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


__all__ = [
    "DEFAULT_LAYOUT",
    "EDIT_WIDGETS_FLAG",
    "WIDGET_CATALOG",
    "DashboardLayoutStore",
    "DashboardLayoutUseCase",
    "DashboardPermissionError",
    "DashboardView",
    "DashboardWidget",
    "FeatureGate",
]
