"""Kiosk kontrollerinin QURULA BİLMƏMƏSİ — SƏBƏB istifadəçiyə görünür (INF2-04/ui).

──────────────────────────────────────────────────────────────────────────────
HANSI QÜSURU TUTUR
──────────────────────────────────────────────────────────────────────────────
Dövrə 2 audit tapıntısı (`infra`): `_build_kiosk_controller` `KOMPASOS_STORE_ID`
boş/yanlış olduqda `None` qaytarırdı və yeganə iz `_log.error`-a düşürdü.
Kiosk PC-si mağazada durur — orada heç kim `app.log`-u oxumur. Nəticə: PIN
klaviaturası açılır, hər cəhd sükutla uğursuz olur, işçi/texnik səbəbi
BİLMİR.

Bu fayl İKİ QATI ölçür:

    1. `_build_kiosk_controller` — səbəb mühit dəyişəninin ADINI daşıyırmı?
    2. `KompasApplication.start_kiosk()` — mesaj PIN cəhdini GÖZLƏMƏDƏN,
       ekran AÇILAN KİMİ görünürmü?
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

_ENV_KEY = "KOMPASOS_STORE_ID"


# --------------------------------------------------------------------------- #
# 1 — `_build_kiosk_controller` səbəbi adlandırır
# --------------------------------------------------------------------------- #


def test_a_missing_store_id_names_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boş `KOMPASOS_STORE_ID` — səbəb AÇIQ mətndə, açarın ADI ilə."""
    from src.presentation.app import _build_kiosk_controller

    monkeypatch.delenv(_ENV_KEY, raising=False)

    controller, reason = _build_kiosk_controller(None)  # type: ignore[arg-type]

    assert controller is None
    assert _ENV_KEY in reason


def test_an_invalid_store_id_also_names_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dəyər VAR, lakin UUID DEYİL — bu da eyni açarın adı ilə izah olunur.

    İKİ FƏRQLİ uğursuzluq (boş / yanlış format) eyni açara aiddir — texnik
    HANSI vəziyyətdə olduğunu bilməsə belə, DÜZƏLDƏCƏYİ dəyişənin adını
    dərhal görür.
    """
    from src.presentation.app import _build_kiosk_controller

    monkeypatch.setenv(_ENV_KEY, "bu-uuid-deyil")

    controller, reason = _build_kiosk_controller(None)  # type: ignore[arg-type]

    assert controller is None
    assert _ENV_KEY in reason


def _stub_machine_identity(monkeypatch: pytest.MonkeyPatch, digest: str | None) -> None:
    """`read_machine_guid_hash()`-i sabitləyir — real registry oxunuşu QEYRİ-SABİTDİR.

    `_build_kiosk_controller` bunu LOKAL idxal edir (`device_identity`
    modulunun ÖZÜNDƏN, çağırış anında) — ona görə mənbə modulun atributunu
    dəyişmək kifayətdir (`_stub_stored_settings`-dəki EYNİ naxış,
    `test_recovery_console.py`-də).
    """
    from src.infrastructure.config import device_identity

    monkeypatch.setattr(device_identity, "read_machine_guid_hash", lambda: digest)


def test_a_valid_store_id_builds_the_controller_with_no_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal hal — kontroller qurulur, səbəb sətri BOŞDUR (uğur işarəsi)."""
    from src.presentation.app import _build_kiosk_controller

    monkeypatch.setenv(_ENV_KEY, str(uuid.uuid4()))
    _stub_machine_identity(monkeypatch, "a" * 64)

    controller, reason = _build_kiosk_controller(None)  # type: ignore[arg-type]

    assert controller is not None
    assert reason == ""


def test_a_valid_machine_identity_reaches_the_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`read_machine_guid_hash()`-in dəyəri kontrollerə HƏQİQƏTƏN çatır."""
    from src.presentation.app import _build_kiosk_controller

    monkeypatch.setenv(_ENV_KEY, str(uuid.uuid4()))
    _stub_machine_identity(monkeypatch, "b" * 64)

    controller, _reason = _build_kiosk_controller(None)  # type: ignore[arg-type]

    assert controller is not None
    assert controller._machine_key.digest == "b" * 64  # type: ignore[attr-defined]


def test_an_unavailable_machine_identity_blocks_pin_entry_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-01/SEC-05 (dövrə 3) — maşın kimliyi oxunmazsa PIN girişi AÇILMIR.

    `read_machine_guid_hash()` `None` qaytarır (Windows deyil/registry
    əlçatmaz) — FAIL-CLOSED: kontroller QURULMUR, səbəb `KOMPASOS_STORE_ID`
    naxışının EYNİSİ ilə istifadəçiyə görünür. Throttle olmadan PIN girişini
    açmaq brute-force qorumasını SÜKUTLA söndürmək demək olardı — SEC-01-in
    ÖZÜ (qoruma var, heç vaxt işə düşmür, aylarla görünmür).
    """
    from src.presentation.app import _build_kiosk_controller

    monkeypatch.setenv(_ENV_KEY, str(uuid.uuid4()))
    _stub_machine_identity(monkeypatch, None)

    controller, reason = _build_kiosk_controller(None)  # type: ignore[arg-type]

    assert controller is None
    assert "terminal kimliyi" in reason.lower()


# --------------------------------------------------------------------------- #
# 2 — `start_kiosk()` mesajı DƏRHAL göstərir, PIN cəhdini gözləmir
# --------------------------------------------------------------------------- #


@requires_qt
def test_start_kiosk_shows_the_setup_error_before_any_pin_attempt(qt_app) -> None:  # type: ignore[no-untyped-def]
    """PIN klaviaturası AÇILAN KİMİ konkret səbəb görünür — köhnə davranış SÜKUTLU idi.

    Köhnə axında bu mesaj YALNIZ işçi PIN daxil edib «submit» etdikdən SONRA
    (`on_pin`) görünürdü — ekran açılanda HEÇ NƏ yox idi. İndi çağıran heç
    bir düyməyə toxunmadan (`start_kiosk()` qayıdan kimi) mesajı görməlidir.
    """
    from src.presentation.app import KompasApplication
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None
    )
    reason = (
        f"Terminal konfiqurasiya edilməyib — `{_ENV_KEY}` mühit dəyişəni "
        "təyin edilməyib. Administratorla əlaqə saxlayın."
    )
    application.set_kiosk_setup_error(reason)

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    assert pin_pad._message.text() == reason  # type: ignore[attr-defined]


@requires_qt
def test_start_kiosk_falls_back_to_a_generic_message_without_a_stored_reason(
    qt_app,
) -> None:  # type: ignore[no-untyped-def]
    """`set_kiosk_setup_error` ÇAĞIRILMASA belə, ekran susmur — sadəcə generic mesajdır.

    Bu, PRAKTİKİ olaraq baş verməməlidir (`run()` HƏMİŞƏ ikisindən birini
    çağırır), lakin `set_kiosk_controller`/`set_kiosk_setup_error` ayrı-ayrı
    çağırıla bilən İCTİMAİ metodlardır — FAIL-CLOSED ehtiyat mesaj itkisinin
    qarşısını alır.
    """
    from src.presentation.app import KompasApplication
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None
    )

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    assert pin_pad._message.text().strip() != ""  # type: ignore[attr-defined]
    assert "administratorla" in pin_pad._message.text().lower()  # type: ignore[attr-defined]


@requires_qt
def test_start_kiosk_shows_nothing_when_the_controller_is_configured(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Kontroller QURULUBSA mesaj sətri BOŞ qalır — yalançı həyəcan YOX."""
    from src.domain.value_objects.identifiers import StoreId
    from src.domain.value_objects.machine_identity import MachineIdentityHash
    from src.presentation.app import KompasApplication
    from src.presentation.controllers.kiosk import KioskController
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None
    )
    application.set_kiosk_controller(
        KioskController(  # type: ignore[arg-type]
            None,
            store_id=StoreId(uuid.uuid4()),
            machine_key=MachineIdentityHash(digest="a" * 64),
        )
    )

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    assert pin_pad._message.text().strip() == ""  # type: ignore[attr-defined]
