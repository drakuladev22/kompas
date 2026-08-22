"""`ShiftPlanningScreen` ↔ `controllers/{shift_matrix,shift_window}.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_shift_window_controller.py` və `test_shift_matrix_work_mode.py` hər ikisi
kontrolleri SAHTƏ ekranla ölçür (`_Signal`/duck-typing sinif) — real
`ShiftPlanningScreen` heç vaxt qurulmur, real "‹"/"›" oxları, real
"İş Rejimi Şablonları" düymələri heç vaxt klikllənmir. Burada REAL ekran +
REAL kontroller birlikdə qurulur və düymələr FAKTİKİ basılır.

──────────────────────────────────────────────────────────────────────────────
TAPILAN QÜSURLAR (hamısı `src/`-dədir, bu fayl YALNIZ sınayır)
──────────────────────────────────────────────────────────────────────────────
Bu ekranın "YAZI yolu" göründüyündən daha azdır: matris xanaları statik
`QLabel`-dır (klikllənmir), "Planı Yayımla" düyməsi Faza 7-də QƏSDƏN
silinib (`group_c.py` başlığı), yalnız #16 Açıq Növbə Bazarı yazır və o,
`test_open_shift_screen_e2e.py`-də artıq sınanıb. Qalan interaktiv
elementlərin ÜÇÜ ÖLÜ çıxdı:

  1. [DÜZƏLDİLDİ] `template_selected` — dörd şablon düyməsi siqnal yayırdı,
     onu isə heç kim dinləmirdi; footer «boş xanalar avtomatik doldurulur»
     VƏD EDİRDİ. İstifadəçi qərarı ilə düymələr, siqnal və vəd mətni SİLİNDİ
     (ekranın yazı yolu yoxdur — «Planı Yayımla» əvvəlki fazada qəsdən
     çıxarılıb). İndi `test_screen_builds_with_the_toolbar_and_without_the_
     dead_template_buttons` onların qayıtmamasını qoruyur.
  2. `_store_combo` — `set_month(stores=[...])` yalnız AD (mətn) əlavə edir,
     `addItems()` `itemData` YARATMIR (iş rejimi seçicisindəki `addItem(label,
     mode_id)`-dən fərqli olaraq). Seçimin arxasında heç bir ID yoxdur, ona
     görə `view_matrix(store_id=...)`-ə HEÇ VAXT çevrilə bilməz — filtr
     struktur baxımından mümkünsüzdür, təkcə bağlanmayıb.
  3. [DÜZƏLDİLDİ] Canlı yol toolbar etiketini heç vaxt yazmırdı — istehsalatda
     "‹ [BURADA] ›" HƏMİŞƏ boş idi. `screen_data.py` indi `set_window_label()`
     çağırır (dar setter: `set_month()` iş rejimi nişanını əzərdi).
  4. [DÜZƏLDİLDİ] `ScreenDataBinder.populate()` bütün istisnaları ÖZÜ udurdu
     (`report_section_error` ilə) və heç vaxt yenidən atmırdı —
     `shift_window.py`-dəki xüsusi `except KompasOSError` bloku ÖLÜ İDİ.
     İndi `populate(..., reraise=True)` `KompasOSError`-u geri ötürür,
     xüsusi mesaj görünür; gözlənilməz (domen-olmayan) istisna isə köhnə
     davranışı (ümumi banner) saxlayır.

1, 3 və 4 DÜZƏLDİLİB (testləri indi yaşıldır); 2 hələ `xfail(strict=True)` ilə
sənədləşdirilib — mağaza filtri funksiyası AYRICA iş tələb edir (kombonun
`itemData` daşıya bilməsi üçün).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId, WorkModeId
from src.presentation.controllers.shift_matrix import ShiftMatrixWorkModeController
from src.presentation.controllers.shift_window import ShiftWindowController
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: TenantId = TenantId(uuid.uuid4())
ACTOR_ID: EmployeeId = EmployeeId(uuid.uuid4())


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


# --------------------------------------------------------------------------- #
# Sahtələr — `ScreenDataBinder`/`shift_matrix.py`/`shift_window.py`-in
# duck-typing gözlədiyi minimum kontrat.
# --------------------------------------------------------------------------- #


@dataclass
class _Assignment:
    employee_id: Any
    shift_date: date
    is_off_day: bool


@dataclass
class _Employee:
    full_name: str


class _EmployeeRepo:
    def __init__(self, employees: dict[Any, _Employee]) -> None:
        self._employees = employees

    def get(self, employee_id: Any) -> _Employee | None:
        return self._employees.get(employee_id)


class _Connection:
    """`_default_store` sorğusu — aktorun filialı yoxdursa çağırılır."""

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchone(self) -> Any:
        return None  # aktiv mağaza yoxdur → `_default_store` "—" qaytarır.


class _Uow:
    def __init__(self, employees: dict[Any, _Employee]) -> None:
        self.employees = _EmployeeRepo(employees)
        self.connection = _Connection()


class _Limits:
    def __init__(self, *, window_days: int = 14) -> None:
        self.window_days = window_days

    def get_int(self, _tenant_id: Any, _key: str, _fallback: int) -> int:
        return self.window_days

    def get_str(self, _tenant_id: Any, _key: str, fallback: str) -> str:
        return fallback


class _ShiftPlanning:
    """`view_matrix` çağırışlarını qeydə alır — sürüşmə/mağaza sınaqları üçün."""

    def __init__(self, assignments: list[_Assignment] | None = None) -> None:
        self._assignments = assignments or []
        self.calls: list[dict[str, Any]] = []
        self.error: KompasOSError | None = None

    def view_matrix(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        start: date,
        end: date,
        store_id: Any = None,
    ) -> list[_Assignment]:
        self.calls.append({"start": start, "end": end, "store_id": store_id})
        if self.error is not None:
            raise self.error
        return [a for a in self._assignments if start <= a.shift_date < end]


class _WorkModeRepo:
    def __init__(self, modes: list[Any]) -> None:
        self._modes = modes

    def list_for_selection(self, _tenant_id: Any) -> list[Any]:
        return list(self._modes)


@dataclass
class _Session:
    tenant_id: Any
    uow: _Uow
    limits: _Limits
    shift_planning: _ShiftPlanning
    work_modes: _WorkModeRepo = field(default=None)  # type: ignore[assignment]


class _Context:
    """`ApplicationContext.session()` — hər çağırışı sayır (§6: sessiya YENİDƏN açılır)."""

    def __init__(self, session: _Session) -> None:
        self._session = session
        self.session_open_count = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.session_open_count += 1
        yield self._session


def _actor(*, store_id: Any = None) -> Any:
    return type("_Actor", (), {"id": ACTOR_ID, "store_id": store_id})()


def _work_mode(name: str, mode_id: Any) -> Any:
    from src.domain.value_objects.catalogs import WorkMode

    return WorkMode(name=name, tenant_id=TENANT, work_mode_id=mode_id)


def _session(
    *,
    employees: dict[Any, _Employee] | None = None,
    window_days: int = 14,
    assignments: list[_Assignment] | None = None,
    work_modes: list[Any] | None = None,
) -> tuple[_Session, _ShiftPlanning]:
    shift_planning = _ShiftPlanning(assignments)
    session = _Session(
        tenant_id=TENANT,
        uow=_Uow(employees or {}),
        limits=_Limits(window_days=window_days),
        shift_planning=shift_planning,
        work_modes=_WorkModeRepo(work_modes or []),
    )
    return session, shift_planning


# --------------------------------------------------------------------------- #
# 1. Quraşdırma — REAL widget-lər mövcuddurmu
# --------------------------------------------------------------------------- #


@requires_qt
def test_screen_builds_with_the_toolbar_and_without_the_dead_template_buttons(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Ay oxları VAR, şablon düymələri isə ARTIQ YOXDUR (QA-FULL Faza 3).

    Dörd şablon düyməsi (`5/2`, `6/1`, `2/2`, `Fərdi`) `template_selected`
    siqnalını yayırdı, onu isə heç kim dinləmirdi; altındakı mətn «boş xanalar
    avtomatik doldurulur» VƏD EDİRDİ. Bu ekranın YAZI yolu yoxdur («Planı
    Yayımla» əvvəlki fazada qəsdən çıxarılıb), yəni düymələr həmin funksiyanın
    qalığı idi — istifadəçi qərarı ilə silindi.

    TEST ONLARIN QAYITMAMASINI QORUYUR: düymə yenidən əlavə olunarsa, onunla
    birlikdə HƏQİQİ doldurma yolu da yazılmalıdır.
    """
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    button_texts = {b.text() for b in screen.findChildren(QPushButton)}
    assert {"‹", "›"} <= button_texts, "Ay naviqasiyası qalmalıdır"
    assert not ({"5/2", "6/1", "2/2", "Fərdi"} & button_texts), (
        "Ölü şablon düymələri geri qayıdıb — onlarla birlikdə yazı yolu da yazılmalıdır"
    )
    assert not hasattr(ShiftPlanningScreen, "template_selected"), (
        "`template_selected` siqnalı da silinməlidir — dinləyicisi olmayan siqnal ölü bənddir"
    )


# --------------------------------------------------------------------------- #
# 2. Ay oxları — REAL klik, REAL kontroller
# --------------------------------------------------------------------------- #


@requires_qt
def test_forward_arrow_real_click_opens_a_fresh_session_per_operation(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §6: sessiya SAXLANMIR — hər əməliyyat üçün yenisi açılır.

    Bir klik İKİ sessiya açır: `shift_window_days()` oxusu VƏ
    `binder.populate()`-in öz sessiyası. Uzun-ömürlü TƏK sessiya olsaydı,
    panel saatlarla açıq qaldıqda kilid saxlayardı (§6 şərhi).
    """
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    session, _planning = _session()
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")

    assert context.session_open_count == 2


@requires_qt
def test_forward_arrow_real_click_shifts_the_queried_window_by_its_own_length(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    session, planning = _session(window_days=14)
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")
    _click(screen, "›")
    _click(screen, "‹")

    # Sürüşmə TOPLANIR (test_shift_window_controller.py-dəki naxışın eynisi,
    # amma bu dəfə siqnal.emit() ilə yox, REAL düymə klikilə): irəli, irəli,
    # geri → offset ardıcıllığı [14, 28, 14] — üçüncü klik BİRİNCİNİN
    # mövqeyinə qayıdır, sıfırlamır.
    starts = [call["start"] for call in planning.calls]
    assert (starts[1] - starts[0]).days == 14
    assert starts[2] == starts[0]


@requires_qt
def test_rapid_double_click_does_not_crash_and_applies_both_steps(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sürətli ikiqat klik — çökmə yoxdur, hər iki addım tətbiq olunur."""
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    session, planning = _session(window_days=10)
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")
    _click(screen, "›")

    assert len(planning.calls) == 2
    assert (planning.calls[1]["start"] - planning.calls[0]["start"]).days == 10


@requires_qt
def test_matrix_populates_from_the_real_view_matrix_result(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    # BİR "›" klikindən SONRA sorğulanan pəncərə [bugün+7, bugün+14) olur
    # (`ShiftWindowController` `attach()`-də deyil, YALNIZ klikdə sürüşdürür) —
    # təyinat elə bu pəncərənin İÇİNDƏ olmalıdır ki, matrisdə görünsün.
    window_days = 7
    first_day = date.today() + timedelta(days=window_days)  # noqa: DTZ011
    employee_id = uuid.uuid4()
    session, _planning = _session(
        employees={employee_id: _Employee(full_name="Aysel Məmmədova")},
        window_days=window_days,
        assignments=[_Assignment(employee_id=employee_id, shift_date=first_day, is_off_day=False)],
    )
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")

    assert "Aysel Məmmədova" in {name for name, _ in screen._cells}


@requires_qt
def test_unreadable_window_length_self_heals_with_the_fallback_instead_of_erroring(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`test_shift_window_controller.py`-dəki sahtə ssenari REAL koda uyğun DEYİL.

    O testdə sahtə `_Binder.shift_window_days` əl ilə `KompasOSError` atır.
    HƏQİQİ `matrix_window_days()` isə (`screen_data.py:1573-1581`) İSTƏNİLƏN
    istisnanı ÖZÜ tutur və `FALLBACK_MATRIX_WINDOW_DAYS`-ə qayıdır — heç vaxt
    yenidən atmır. Nəticədə `ShiftWindowController._on_month_changed`-dəki
    BİRİNCİ `except KompasOSError` bloku da (limit oxuması üçün) əməli olaraq
    ÇATILMAZDIR: sürüşmə həmişə baş tutur, sadəcə FALLBACK pəncərə ilə.
    """
    from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    session, planning = _session()

    class _BrokenLimits:
        def get_int(self, *_args: Any, **_kwargs: Any) -> int:
            raise KompasOSError("limit oxunmadı")

        def get_str(self, *_args: Any, **_kwargs: Any) -> str:
            return "8"

    session.limits = _BrokenLimits()  # type: ignore[assignment]
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")

    fallback_days = int(DEFAULT_LIMITS[SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS])
    assert len(planning.calls) == 1
    assert planning.calls[0]["start"] == date.today() + timedelta(days=fallback_days)  # noqa: DTZ011


# --------------------------------------------------------------------------- #
# 3. İş Rejimi seçicisi — real dəyişiklik, matrisə TOXUNMUR (docstring zəmanəti)
# --------------------------------------------------------------------------- #


@requires_qt
def test_changing_the_work_mode_selection_updates_the_norm_chip_without_a_matrix_reload(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    morning_id = WorkModeId(uuid.uuid4())
    night_id = WorkModeId(uuid.uuid4())
    session, _planning = _session(
        work_modes=[
            _work_mode("Səhər", morning_id),
            _work_mode("Gecə", night_id),
        ]
    )
    context = _Context(session)
    ShiftMatrixWorkModeController(context, _actor()).attach(screen)
    opened_after_attach = context.session_open_count

    # `setCurrentIndex` REAL istifadəçi seçiminin doğurduğu EYNİ
    # `currentIndexChanged` siqnalını yayır — popup açıb siçanla seçmək
    # offscreen platformada etibarsızdır, amma nəticə eyni koda gedir.
    screen.select_work_mode(str(night_id))

    assert "Gecə" in screen._mode_label.text()
    # Sənəddəki zəmanət: seçici YALNIQ oxuyur, matrisi YENİDƏN doldurmur —
    # deməli seçim heç bir ƏLAVƏ sessiya açmamalıdır.
    assert context.session_open_count == opened_after_attach


@requires_qt
def test_work_mode_catalog_read_failure_does_not_crash_the_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    class _BrokenWorkModes:
        def list_for_selection(self, _tenant_id: Any) -> list[Any]:
            raise KompasOSError("kataloq oxunmadı", user_message="İş rejimləri oxunmadı.")

    session, _planning = _session()
    session.work_modes = _BrokenWorkModes()  # type: ignore[assignment]
    context = _Context(session)

    # NASAZLIQ EKRANI ÇÖKDÜRMÜR (modulun başlığı) — dropdown boş qalır.
    ShiftMatrixWorkModeController(context, _actor()).attach(screen)

    assert screen.selected_work_mode_id() == ""


# --------------------------------------------------------------------------- #
# 4. Ekstremal/malformed data — REAL widget-lərdə çökmə yoxdur
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize(
    "extreme_name",
    [
        pytest.param("", id="empty"),
        pytest.param(" " * 12, id="only-spaces"),
        pytest.param("İ" * 10_000, id="10000-chars"),
        pytest.param("😀🔥💥 Növbə", id="emoji"),
        pytest.param("'; DROP TABLE fines; --", id="sql-like"),
        pytest.param("Ad\nSoyad\tTab", id="control-chars"),
    ],
)
def test_extreme_employee_names_render_without_crashing(qtbot, theme, extreme_name: str) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    # BİR "›" klikindən SONRA sorğulanan pəncərə [bugün+3, bugün+6) olur.
    window_days = 3
    first_day = date.today() + timedelta(days=window_days)  # noqa: DTZ011
    employee_id = uuid.uuid4()
    session, _planning = _session(
        employees={employee_id: _Employee(full_name=extreme_name)},
        window_days=window_days,
        assignments=[_Assignment(employee_id=employee_id, shift_date=first_day, is_off_day=False)],
    )
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")  # çökmə YOXDUR — bu, testin ÖZÜdür.

    assert extreme_name in {name for name, _ in screen._cells}


@requires_qt
def test_thirty_by_thirty_one_matrix_builds_without_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """30 işçi × 31 gün — böyük matris ƏSAS SAPI çökdürmür (donma ölçüsü
    `performance-profiling-engineer`-in işidir, bu test yalnız DOĞRULUĞU
    yoxlayır)."""
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    # BİR "›" klikindən SONRA sorğulanan pəncərə [bugün+31, bugün+62) olur —
    # təyinatlar elə bu ARALIQDA yerləşdirilir.
    window_days = 31
    window_start = date.today() + timedelta(days=window_days)  # noqa: DTZ011
    employees = {uuid.uuid4(): _Employee(full_name=f"İşçi {i:02d}") for i in range(30)}
    assignments = [
        _Assignment(
            employee_id=emp_id,
            shift_date=window_start + timedelta(days=offset % window_days),
            is_off_day=False,
        )
        for offset, emp_id in enumerate(employees)
    ]
    session, _planning = _session(
        employees=employees, window_days=window_days, assignments=assignments
    )
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")

    assert len(screen._cells) == 30 * 31


@requires_qt
def test_mismatched_day_code_row_length_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`set_matrix` sətir uzunluğu sütun sayı ilə UYĞUN GƏLMƏSƏ də çökmür.

    `_render_shift_matrix` HƏMİŞƏ `window_days` uzunluqlu siyahı qurur, amma
    ekranın öz `set_matrix()` API-si ictimaidir — malformed çağırış (məs.
    başqa bir kontrollerdən) qısa/uzun sətirlə gəlsə belə, `enumerate` təbii
    şəkildə qısa olanı KƏSİR, uzun olanı isə şəbəkəyə ƏLAVƏ sütun kimi əlavə
    edir; heç biri istisna atmır.
    """
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    days = [(1, "B.e"), (2, "Ç.a"), (3, "Çər")]
    rows = [("Qısa sətir", ["S"]), ("Uzun sətir", ["S", "A", "", "M", "S"])]

    screen.set_matrix(days, rows)  # çökmə YOXDUR — bu, testin ÖZÜdür.

    assert ("Qısa sətir", 1) in screen._cells
    assert ("Uzun sətir", 5) in screen._cells


# --------------------------------------------------------------------------- #
# 5. TAPILAN QÜSURLAR — hər biri `src/`-dədir, düzəlişi SAHİBİNƏ göndərilib
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.xfail(
    strict=True,
    reason=(
        "group_c.py:2638-2639 — `_store_combo.addItems(stores)` yalnız mağaza "
        "ADI əlavə edir, iş rejimi seçicisindəki `addItem(label, mode_id)`-dən "
        "fərqli olaraq `itemData` (mağaza ID-si) YOXDUR. Seçim heç vaxt "
        "`view_matrix(store_id=...)`-ə çevrilə bilməz — filtr struktur "
        "baxımından mümkünsüzdür, təkcə bağlanmayıb."
    ),
)
def test_store_selector_should_carry_a_store_identifier_but_does_not(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    screen.set_month("Avqust 2026", stores=["Yasamal", "Nərimanov"], mode="5/2")
    screen._store_combo.setCurrentIndex(1)

    assert screen._store_combo.itemData(1) is not None


@requires_qt
def test_live_navigation_updates_the_window_label(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """DÜZƏLDİLDİ (QA-FULL Faza 3): canlı yol `set_window_label()` çağırır.

    Əvvəl `set_month(...)`-u YALNIZ `preview_screens.py` çağırırdı; istehsalatda
    toolbar-dakı «‹ [aralıq] ›» HƏMİŞƏ boş qalırdı. `set_month()` işlədilmir,
    çünki onun `mode` arqumenti iş rejimi nişanını əzərdi (bax
    `group_c.ShiftPlanningScreen.set_window_label`).
    """
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    session, _planning = _session(window_days=14)
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    _click(screen, "›")

    assert screen._month_label.text() != ""


@requires_qt
def test_matrix_reload_failure_shows_the_dedicated_error_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """DÜZƏLDİLDİ (QA-FULL Faza 3): `populate(..., reraise=True)`.

    Əvvəl `ScreenDataBinder.populate()` HƏR istisnanı ÖZÜ udurdu, ona görə
    aşağıdakı `except KompasOSError` bloku (`shift_window.py`) heç vaxt işə
    düşmürdü. İndi `reraise=True` `KompasOSError`-u geri ötürür və çağıran
    tərəf öz xüsusi mesajını göstərə bilir — bax `screen_data.py::populate`
    başlığı və `shift_window.py::_on_month_changed`.
    """
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    session, planning = _session(window_days=14)
    planning.error = KompasOSError("sorğu düşdü", user_message="Növbə matrisi oxuna bilmədi.")
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    shown_errors: list[dict[str, Any]] = []
    screen.show_error = lambda **kwargs: shown_errors.append(kwargs)  # type: ignore[method-assign]

    _click(screen, "›")

    assert shown_errors, "xüsusi `show_error(...)` mesajı çağırılmadı"
    assert shown_errors[0]["title"] == "Növbə matrisi oxuna bilmədi"
    assert shown_errors[0]["message"] == "Növbə matrisi oxuna bilmədi."
    # ÜMUMİ bölmə banneri artıq göstərilmir — `reraise=True` istisnanı
    # `populate()`-in öz `report_section_error` qoluna DÜŞMƏDƏN çıxarır (əks
    # halda istifadəçi EYNİ nasazlıq üçün İKİ ziddiyyətli mesaj görərdi).
    assert screen._section_errors == []


@requires_qt
def test_unexpected_non_kompasos_error_still_falls_back_to_the_generic_section_banner(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`reraise=True` YALNIZ `KompasOSError`-u ötürür (`populate()` başlığı).

    Gözlənilməz (domen-olmayan) istisna köhnə davranışı saxlayır: örtük
    çökmür, ümumi "Ekran məlumatları" banneri görünür — çağıran tərəf onun
    üçün mənalı istifadəçi mesajı YAZA BİLMƏZ, çünki səbəb naməlumdur.
    """
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    session, planning = _session(window_days=14)
    planning.error = RuntimeError("gözlənilməz nasazlıq")  # type: ignore[assignment]
    context = _Context(session)
    ShiftWindowController(context, _actor()).attach(screen)

    shown_errors: list[dict[str, Any]] = []
    screen.show_error = lambda **kwargs: shown_errors.append(kwargs)  # type: ignore[method-assign]

    _click(screen, "›")

    assert shown_errors == []
    assert "Ekran məlumatları" in screen._section_errors
