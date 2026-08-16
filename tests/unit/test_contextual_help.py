"""Kontekstual «?» kömək düyməsi (audit G-4).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
`widgets/help_hint.HelpButton` `buttons.icon_button()` fabrikasını İŞLƏTMİR
— fabrika hazır nüsxə qaytarır və alt sinif üçün yararsızdır. Konfiqurasiya
isə hərfən eyni olmalıdır (`variant=icon`, `HEADER_ICON_BUTTON` ölçüsü, ikon
ölçüsü, göstərici kursor). İki nüsxə sükutla ayrıla bilər: kimsə fabrikadakı
ölçünü dəyişəndə «?» düyməsi bir buraxılışda başqa ölçüdə qalar və heç bir
test bunu tutmazdı. Birinci qrup test məhz həmin PARİTETİ qapılayır.

İkinci qrup əlçatanlığı qapılayır: düymə YALNIZ-İKONDUR, yəni `text()` boşdur
və Qt-nin `accessibleName() → text()` zənciri tooltip-ə BAXMIR. Ad açıq
verilmirsə ekran oxuyucusu elementi sadəcə "düymə" kimi elan edir — kömək
düyməsi isə klaviatura istifadəçisi üçün ən çox lazım olan düymədir.

Üçüncü qrup MƏTNİN MENYU İLƏ SİNXRONLUĞUNU qapılayır və burada ən çox dəyər
var: `UsersScreen.ACTIONS`-a yeni bənd əlavə edən adam köməyi yeniləməyi
unudarsa, istifadəçi menyuda izah olunmayan bir əməliyyat görür — özü də
sırada GERİ QAYTARILA BİLMƏYƏN «Deaktiv Et» ilə yan-yana. Bu, sənəd
köhnəlməsi deyil, real səhv-klik riskidir.

Dördüncü qrup bir REQRESSİYA qapısıdır: `UsersScreen.__init__` bir dəfə
yarımçıq redaktə ilə iki yerə bölünmüşdü — `help_button()` metodu
konstruktorun ORTASINA düşmüş, cədvəli quran blok isə `return`-dan sonra
qalıb heç vaxt icra olunmamışdı. Ekranın həm alət panelini, HƏM cədvəli
qurduğunu yoxlamaq bu formanı bir daha buraxmır.

Sahtə lazım deyil — bunlar saf widget testləridir.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import requires_qt


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _labels(widget: Any) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in widget.findChildren(QLabel)]


def _button(theme: Any) -> Any:
    from src.presentation.widgets.help_hint import HelpButton

    return HelpButton(
        theme,
        title="ERP Serverləri",
        intro="Bu ekranda 1C serverləri sadalanır.",
        steps=("Serveri seçin.", "«Bağlantını Test Et» düyməsini basın."),
    )


# ---------------------------------------------------------------------------
# 1. `icon_button()` fabrikası ilə paritet
# ---------------------------------------------------------------------------


@requires_qt
def test_help_button_configuration_matches_the_icon_button_factory(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets.buttons import icon_button

    reference = icon_button("help", theme.color("--color-text-muted"))
    button = _button(theme)
    qtbot.addWidget(reference)
    qtbot.addWidget(button)

    assert button.property("variant") == reference.property("variant")
    assert button.size() == reference.size()
    assert button.iconSize() == reference.iconSize()
    assert button.cursor().shape() == reference.cursor().shape()


@requires_qt
def test_help_button_uses_the_header_icon_metric(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets import metrics

    button = _button(theme)
    qtbot.addWidget(button)

    assert button.width() == metrics.HEADER_ICON_BUTTON
    assert button.height() == metrics.HEADER_ICON_BUTTON


# ---------------------------------------------------------------------------
# 2. Əlçatanlıq — ikon-düymənin adı AÇIQ verilməlidir
# ---------------------------------------------------------------------------


@requires_qt
def test_accessible_name_is_explicit_because_the_button_has_no_text(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    button = _button(theme)
    qtbot.addWidget(button)

    # `text()` boşdursa Qt-nin ad zənciri tooltip-ə BAXMIR — ad ayrıca
    # verilməsəydi, ekran oxuyucusu düyməni "düymə" kimi elan edərdi.
    assert button.text() == ""
    assert button.accessibleName() == "Kömək — ERP Serverləri"
    assert button.accessibleDescription() == "Bu ekranda 1C serverləri sadalanır."


@requires_qt
def test_tooltip_is_identical_on_every_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets.help_hint import HELP_TOOLTIP

    button = _button(theme)
    qtbot.addWidget(button)

    # İkonun mənası bir dəfə öyrənilir; tooltip ekrandan-ekrana dəyişsəydi
    # istifadəçi hər dəfə yenidən oxumalı olardı.
    assert button.toolTip() == HELP_TOOLTIP


@requires_qt
def test_button_is_reachable_with_the_keyboard(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    button = _button(theme)
    qtbot.addWidget(button)

    # Siçansız istifadəçi köməyə eyni yolla çatmalıdır.
    assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus


# ---------------------------------------------------------------------------
# 3. Modal — davranış və məzmun
# ---------------------------------------------------------------------------


@requires_qt
def test_open_help_returns_without_blocking_and_shows_a_modal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    button = _button(theme)
    qtbot.addWidget(button)

    # `exec()` öz hadisə dövrəsini işə salıb bu sətri sonsuza qədər
    # bloklayardı — çağırışın QAYITMASI elə `show()` işlədildiyinin sübutudur.
    dialog = button.open_help()
    qtbot.addWidget(dialog)

    assert dialog.isModal() is True
    assert dialog.isVisible() is True


@requires_qt
def test_dialog_is_parented_to_the_window_not_to_the_button(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    host = QWidget()
    QVBoxLayout(host)
    button = _button(theme)
    host.layout().addWidget(button)
    qtbot.addWidget(host)

    dialog = button.open_help()
    qtbot.addWidget(dialog)

    # Modal ekranın MƏRKƏZİNDƏ açılmalıdır, düymənin üstündə yox; ekran
    # dəyişəndə isə onunla birlikdə ölməlidir.
    assert dialog.parent() is button.window()


@requires_qt
def test_dialog_lists_every_step_with_its_order_number(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    button = _button(theme)
    qtbot.addWidget(button)
    dialog = button.open_help()
    qtbot.addWidget(dialog)

    labels = _labels(dialog)
    assert "ERP Serverləri" in labels
    assert "Bu ekranda 1C serverləri sadalanır." in labels
    assert "Serveri seçin." in labels
    assert "«Bağlantını Test Et» düyməsini basın." in labels
    assert {"1", "2"}.issubset(set(labels))


@requires_qt
def test_dialog_text_stays_selectable_for_support_requests(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    button = _button(theme)
    qtbot.addWidget(button)
    dialog = button.open_help()
    qtbot.addWidget(dialog)

    selectable = [
        label
        for label in dialog.findChildren(QLabel)
        if label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    ]
    # İstifadəçi addımı dəstək müraciətinə köçürə bilməlidir — mətni
    # kilidləmək onu yenidən yazmağa məcbur edərdi.
    assert [label.text() for label in selectable] != []


@requires_qt
def test_close_button_accepts_the_dialog(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.widgets.help_hint import HELP_CLOSE_TEXT

    button = _button(theme)
    qtbot.addWidget(button)
    dialog = button.open_help()
    qtbot.addWidget(dialog)

    close = next(b for b in dialog.findChildren(QPushButton) if b.text() == HELP_CLOSE_TEXT)
    close.click()

    assert dialog.isVisible() is False


# ---------------------------------------------------------------------------
# 4. Mətn ↔ menyu sinxronluğu və `UsersScreen` reqressiyası
# ---------------------------------------------------------------------------


def test_users_help_explains_every_row_action() -> None:
    from src.presentation.screens.group_c import USERS_HELP_STEPS, UsersScreen

    joined = " ".join(USERS_HELP_STEPS)
    missing = [label for _key, label in UsersScreen.ACTIONS if label not in joined]

    assert missing == [], f"Kömək mətnində izah olunmayan menyu maddəsi: {missing}"
    assert len(USERS_HELP_STEPS) == len(UsersScreen.ACTIONS)


def test_users_help_warns_that_deactivation_cannot_be_undone() -> None:
    from src.presentation.screens.group_c import USERS_HELP_INTRO, USERS_HELP_STEPS

    # Geri dönməzlik xəbərdarlığı HƏM girişdə, HƏM də bəndin özündə olmalıdır:
    # istifadəçi modalı yuxarıdan oxumaya bilər.
    assert "geri qaytarıla bilmir" in USERS_HELP_INTRO.lower()
    assert any("GERİ" in step and "QAYTARILA BİLMİR" in step for step in USERS_HELP_STEPS)


@requires_qt
def test_users_screen_builds_both_the_toolbar_and_the_table(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import UsersScreen
    from src.presentation.widgets.help_hint import HelpButton

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)

    # Konstruktor bir dəfə ikiyə bölünmüşdü: kömək düyməsi qurulur, cədvəl
    # isə QURULMURDU. İkisi bir yerdə yoxlanır ki, həmin forma qayıtmasın.
    assert isinstance(screen.help_button(), HelpButton)
    assert screen.help_button() in screen.findChildren(HelpButton)

    screen.set_users([{"full_name": "Rəşad Məmmədov", "username": "rmammadov"}])
    assert screen.table().row_count == 1
    assert screen.switcher().current_state() == "content"


@requires_qt
def test_users_screen_help_carries_the_screen_name(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import USERS_HELP_TITLE, UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)

    assert screen.help_button().accessibleName() == f"Kömək — {USERS_HELP_TITLE}"


# ---------------------------------------------------------------------------
# 5. «?» düyməsinin qalan ekranlara yayılması (audit G-4, ikinci dalğa)
# ---------------------------------------------------------------------------
#
# `UsersScreen` naxışı səkkiz ekrana köçürüldü. Hər ekran üçün üç ayrı test
# yazmaq 24 funksiya demək olardı və biri əlavə ediləndə digərinin unudulması
# qaçılmaz idi — ona görə siyahı BİR yerdədir və testlər onun üzərində
# parametrləşdirilir: yeni ekran qoşan adam yalnız bir sətir yazır, üç qapı
# isə avtomatik işə düşür.
#
# ÜÇÜNCÜ QAPI (`_exercise`) ən vacibidir: `UsersScreen`-də bir dəfə baş vermiş
# qüsur — `help_button()` metodunun konstruktorun ORTASINA düşməsi və qalan
# hissənin `return`-dan sonra qalıb heç vaxt icra olunmaması — səssizdir.
# Ekran qurulur, düymə görünür, yalnız cədvəl/kart boş qalır. Ona görə hər
# ekranda konstruktorun SONUNDA qurulan strukturlara toxunan bir əməliyyat
# icra olunur.


def _exercise_erp(screen) -> None:  # type: ignore[no-untyped-def]
    """`_table`, `_mapping_rows`, `_sync_rows`, `_server_names` — hamısı sonda."""
    screen.set_servers(
        [
            {
                "name": "1C-BAKI",
                "type": "HTTP/OData",
                "address": "https://1c.local",
                "stores": "3",
                "latency": "45 ms",
                "latency_meaning": "şəbəkə cavab müddəti",
                "status": "Aktiv",
            }
        ],
        mapped_stores=3,
    )
    screen.set_mapping([("Mağaza №1", "1C-BAKI")], note="1 mağaza xəritələnib")
    screen.set_last_sync([("1C-BAKI", "10:24", "success")])
    assert screen.switcher().current_state() == "content"


def _exercise_drive(screen) -> None:  # type: ignore[no-untyped-def]
    """`_history_rows` və gözləmə kartı konstruktorun son bloklarındadır."""
    screen.set_active(
        account="sübutlar@kompas.az",
        status_text="Aktiv",
        tone="success",
        quota_text="12 GB / 15 GB",
    )
    screen.set_history([("sübutlar@kompas.az", "Aktiv", "01.08.2026")])
    screen.show_pending("https://accounts.google.com/o/oauth2/auth")
    screen.clear_pending()
    assert screen.switcher().current_state() == "content"


def _exercise_root(screen) -> None:  # type: ignore[no-untyped-def]
    """`_build_registry()` konstruktorun SON çağırışıdır — `set_registry` onu tələb edir."""
    screen.set_limits([("LEAVE_REQUEST_SLA_HOURS", "İcazə SLA", 24, 1, 96, "saat")])
    screen.set_break_limits([("LUNCH_BREAK_MINUTES", "Nahar", 30, 5, 120, "dəq")])
    screen.set_modules([("FINE_MODULE", "Cərimə modulu", True, False)])
    screen.set_face_scope([{"id": "store-1", "name": "Mağaza №1", "active": "1"}])
    screen.set_registry([("can_issue_fines", False)])
    collected = screen.collected()
    assert collected["limits"]["LEAVE_REQUEST_SLA_HOURS"] == 24
    assert collected["modules"]["FINE_MODULE"] is True


def _exercise_matrix(screen) -> None:  # type: ignore[no-untyped-def]
    """Kömək düyməsi matris panelindədir — panel bütöv qurulmalıdır."""
    screen.set_roles([("SATICI", "Satıcı", 12)])
    screen.select_role("SATICI")
    screen.set_matrix(
        "Satıcı",
        [("Cərimə", [("can_issue_fines", "Cərimə ver", True, False, True)])],
    )
    assert screen.collected() == {"can_issue_fines": True}
    assert screen.switcher().current_state() == "content"


def _exercise_infrastructure(screen) -> None:  # type: ignore[no-untyped-def]
    """`_history_layout` və `set_active_target()` konstruktorun sonundadır."""
    screen.set_warnings([])
    screen.reset_phases()
    screen.set_history(
        [
            {
                "date": "01.08.2026",
                "direction": "Cloud → Şəxsi Server",
                "checksum": "a1b2c3",
                "status": "Tamamlandı",
                "tone": "success",
            }
        ]
    )
    assert screen.switcher().current_state() == "content"


def _exercise_builder(screen) -> None:  # type: ignore[no-untyped-def]
    """`_render()` önizləmə kartına və icmal sətrinə toxunur — ikisi də sonda qurulur."""
    screen.set_widgets(
        {
            "stat_tiles": ("Rəqəm kartları", "Gündəlik göstəricilər"),
            "fines_chart": ("Cərimə qrafiki", "Aylıq cərimə dinamikası"),
        },
        order=["stat_tiles", "fines_chart"],
        visible={"stat_tiles"},
        columns=2,
    )
    layout = screen.current_layout()
    assert len(layout) == 1
    assert layout[0].startswith("stat_tiles")
    assert screen.switcher().current_state() == "content"


def _exercise_fine_review(screen) -> None:  # type: ignore[no-untyped-def]
    """`_build_footer()` (nəşr düyməsi) konstruktorun sonuncu blokudur."""
    from src.presentation.screens.fine_review import FineReviewGroup, FineReviewRow

    screen.set_decision_options(
        [{"code": "KEEP", "label": "Saxla"}, {"code": "DISCARD", "label": "Sil"}]
    )
    screen.set_periods([{"key": "2026-08", "label": "Avqust 2026"}])
    screen.set_groups(
        [
            FineReviewGroup(
                key="store-1",
                store="Mağaza №1",
                count_text="1 cərimə",
                total_text="20.00 AZN",
                rows=(
                    FineReviewRow(
                        fine_id="fine-1",
                        employee="Rəşad Məmmədov",
                        fine_type="Gecikmə",
                        amount_text="20.00 AZN",
                        date_text="01.08.2026",
                        operator="Kamera operatoru",
                        has_evidence=True,
                    ),
                ),
            )
        ],
        summary_text="1 cərimə nəşr gözləyir",
    )
    assert screen.selected_period() == "2026-08"
    assert screen.publish_button().isEnabled() is True


def _exercise_sync_conflicts(screen) -> None:  # type: ignore[no-untyped-def]
    """Qərar kartı (`_note`, `_note_hint`, düymələr) konstruktorun sonundadır."""
    screen.set_note_min_length(10)
    screen.set_resolutions([{"code": "LOCAL", "label": "Mağaza versiyası", "hint": ""}])
    screen.set_conflicts(
        [
            {
                "id": "conflict-1",
                "table_label": "Davamiyyət qeydi",
                "record_label": "attendance_records:42",
                "detected": "01.08.2026 10:24",
                "diff_count": "2 sahə fərqlidir",
                "audit_critical": "1",
            }
        ]
    )
    screen.set_comparison(
        {"id": "conflict-1", "table_label": "Davamiyyət qeydi", "audit_critical": "1"},
        [{"field": "status", "local": "RETURNED", "remote": "ON_LEAVE", "differs": "1"}],
    )
    # Səbəb yazılmayıb — düymələr basıla bilməz (ekranın öz sərhəd qaydası).
    assert screen.decision_buttons() != []
    assert all(not button.isEnabled() for button in screen.decision_buttons())


#: (modul, ekran sinfi, başlıq sabiti, giriş sabiti, addım sabiti, bütövlük yoxlaması).
_HELP_SCREENS = [
    (
        "src.presentation.screens.group_d",
        "ErpServersScreen",
        "ERP_HELP_TITLE",
        "ERP_HELP_INTRO",
        "ERP_HELP_STEPS",
        _exercise_erp,
    ),
    (
        "src.presentation.screens.group_d",
        "DriveConnectionScreen",
        "DRIVE_HELP_TITLE",
        "DRIVE_HELP_INTRO",
        "DRIVE_HELP_STEPS",
        _exercise_drive,
    ),
    (
        "src.presentation.screens.group_d",
        "RootControlScreen",
        "ROOT_HELP_TITLE",
        "ROOT_HELP_INTRO",
        "ROOT_HELP_STEPS",
        _exercise_root,
    ),
    (
        "src.presentation.screens.group_c",
        "PermissionMatrixScreen",
        "MATRIX_HELP_TITLE",
        "MATRIX_HELP_INTRO",
        "MATRIX_HELP_STEPS",
        _exercise_matrix,
    ),
    (
        "src.presentation.screens.group_i",
        "InfrastructureScreen",
        "INFRASTRUCTURE_HELP_TITLE",
        "INFRASTRUCTURE_HELP_INTRO",
        "INFRASTRUCTURE_HELP_STEPS",
        _exercise_infrastructure,
    ),
    (
        "src.presentation.screens.group_i",
        "DashboardBuilderScreen",
        "BUILDER_HELP_TITLE",
        "BUILDER_HELP_INTRO",
        "BUILDER_HELP_STEPS",
        _exercise_builder,
    ),
    (
        "src.presentation.screens.fine_review",
        "MonthlyFineReviewScreen",
        "FINE_REVIEW_HELP_TITLE",
        "FINE_REVIEW_HELP_INTRO",
        "FINE_REVIEW_HELP_STEPS",
        _exercise_fine_review,
    ),
    (
        "src.presentation.screens.sync_conflicts",
        "SyncConflictScreen",
        "SYNC_CONFLICT_HELP_TITLE",
        "SYNC_CONFLICT_HELP_INTRO",
        "SYNC_CONFLICT_HELP_STEPS",
        _exercise_sync_conflicts,
    ),
]

_SCREEN_IDS = [case[1] for case in _HELP_SCREENS]

#: Addımın SADƏCƏ düymə adı olmadığını göstərən nəticə ifadələri.
#:
#: Kömək mətninin ən asan sürüşmə yolu odur ki, kimsə addımları «düyməni
#: basın» siyahısına çevirsin — belə mətn heç nə öyrətmir. Hər ekranın kömək
#: dəsti ən azı bir NƏTİCƏ cümləsi daşımalıdır: nə dəyişir, nə dəyişmir,
#: nəyin geri dönüşü yoxdur.
_CONSEQUENCE_MARKERS = (
    "geri qaytaril",
    "silinmir",
    "dəyişmir",
    "təsir etmir",
    "itir",
    "yoxdur",
)


def _fold(text: str) -> str:
    """Böyük «İ» hərfini müqayisə üçün normallaşdırır.

    Python-da `"İ".lower()` İKİ simvol qaytarır: `i` + birləşən nöqtə (U+0307).
    Yəni «SİLİNMİR».lower() sətir kimi «silinmir»-dən FƏRQLİDİR və sadə
    `in` yoxlaması Azərbaycan mətnində səssizcə uğursuz olardı. Birləşən
    nöqtəni atmaq hər iki formanı eyni edir.
    """
    return text.lower().replace(chr(0x0307), "")


def _load(module: str, name: str):  # type: ignore[no-untyped-def]
    import importlib

    return getattr(importlib.import_module(module), name)


@requires_qt
@pytest.mark.parametrize(
    ("module", "screen_name", "title_name", "_intro_name", "_steps_name", "_exercise"),
    _HELP_SCREENS,
    ids=_SCREEN_IDS,
)
def test_screen_exposes_a_help_button_carrying_its_name(  # type: ignore[no-untyped-def]
    qtbot,
    theme,
    module,
    screen_name,
    title_name,
    _intro_name,
    _steps_name,
    _exercise,
) -> None:
    from src.presentation.widgets.help_hint import HelpButton

    screen = _load(module, screen_name)(theme)
    qtbot.addWidget(screen)
    title = _load(module, title_name)

    button = screen.help_button()
    assert isinstance(button, HelpButton)
    # Düymə ekranın ÖVLADI olmalıdır: yalnız istinad saxlanılsaydı, widget
    # heç bir layout-a düşmədən görünməz qalardı və test yenə keçərdi.
    assert button in screen.findChildren(HelpButton)
    # `text()` boşdur (yalnız-ikon), ona görə ekranın adını AÇIQ ad daşıyır.
    assert button.accessibleName() == f"Kömək — {title}"


@pytest.mark.parametrize(
    ("module", "_screen_name", "title_name", "intro_name", "steps_name", "_exercise"),
    _HELP_SCREENS,
    ids=_SCREEN_IDS,
)
def test_help_text_explains_consequences_not_button_names(  # type: ignore[no-untyped-def]
    module,
    _screen_name,
    title_name,
    intro_name,
    steps_name,
    _exercise,
) -> None:
    title = _load(module, title_name)
    intro = _load(module, intro_name)
    steps = _load(module, steps_name)

    assert title.strip() == title
    assert len(intro) >= 80, "Giriş cümləsi ekranın nə etdiyini izah etməlidir"
    assert isinstance(steps, tuple)
    # 3-dən az addım ekranı izah etmir, 6-dan çoxu isə modalı sürüşdürülən
    # sənədə çevirir — kömək o zaman oxunmur.
    assert 3 <= len(steps) <= 6
    for step in steps:
        assert step.endswith("."), f"Addım cümlə kimi bitməlidir: {step!r}"
        assert len(step.split()) >= 12, f"Addım yalnız düymə adını sadalayır: {step!r}"

    joined = _fold(" ".join(steps))
    assert any(_fold(marker) in joined for marker in _CONSEQUENCE_MARKERS), (
        f"{title} köməyi heç bir nəticə/geri-dönməzlik ifadəsi daşımır"
    )


def test_help_titles_are_unique_across_screens() -> None:
    from src.presentation.screens.group_c import USERS_HELP_TITLE

    titles = [USERS_HELP_TITLE] + [
        _load(module, title_name) for module, _s, title_name, _i, _st, _e in _HELP_SCREENS
    ]
    # Ekran oxuyucusu düyməni yalnız adı ilə elan edir; iki ekranın eyni adı
    # olsaydı, istifadəçi hansı köməyi açdığını səslə ayırd edə bilməzdi.
    assert len(set(titles)) == len(titles)


@requires_qt
@pytest.mark.parametrize(
    ("module", "screen_name", "_title_name", "_intro_name", "_steps_name", "exercise"),
    _HELP_SCREENS,
    ids=_SCREEN_IDS,
)
def test_constructor_stays_whole_after_the_help_button_was_added(  # type: ignore[no-untyped-def]
    qtbot,
    theme,
    module,
    screen_name,
    _title_name,
    _intro_name,
    _steps_name,
    exercise,
) -> None:
    from src.presentation.widgets.help_hint import HelpButton

    screen = _load(module, screen_name)(theme)
    qtbot.addWidget(screen)

    # Kömək düyməsi VAR, lakin konstruktorun qalan hissəsi də icra olunub:
    # `UsersScreen`-də bir dəfə məhz bu ikisi ayrılmışdı (bax modul başlığı).
    assert isinstance(screen.help_button(), HelpButton)
    exercise(screen)
