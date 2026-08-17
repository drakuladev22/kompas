"""Üz qeydiyyatının QEYDİYYAT AXINI — SEC-025 və ilk-giriş qapısı.

──────────────────────────────────────────────────────────────────────────────
TƏLƏB VƏ STRUKTUR MANEƏ
──────────────────────────────────────────────────────────────────────────────
Tələb: «qeydiyyat zamanı face control təşkil edilsin — həm CEO, həm işçilər».

Maneə: `facecontrol.md` bənd 1 üz qeydiyyatını NƏZARƏTLİ proses sayır və
`assert_may_enroll` aktorun subyektin ÖZÜ olmasını qadağan edir. Səbəb
praktikdir: nəzarətsiz qeydiyyatda işçi İSTƏNİLƏN üzü öz hesabına bağlaya
bilər, sonra həmin adam onun adına giriş edər.

Ona görə axın İKİYƏ ayrıldı:

    İŞÇİ  → hesab CEO tərəfindən açılır, üz qeydiyyatı İLK GİRİŞDƏ olur və
            yanındakı admin öz hesabı ilə TƏSDİQLƏYİR (qadağa toxunulmur).
    CEO   → sihirbazın sonunda ÖZÜ qeydiyyatdan keçir (SEC-025), çünki o an
            tenant-da ondan başqa admin YOXDUR — nəzarət mümkün deyil.

İSTİSNANIN ŞƏRTİ ADA GÖRƏ DEYİL, FAKTA GÖRƏDİR: `can_manage_employees`
daşıyan aktiv hesabların sayı 1-dən çox olan kimi bootstrap yolu BAĞLANIR.
Bu fayl həmin avtomatik bağlanmanı qapıya salır — «ilk hesab» şərtini adla
yoxlayan hər gələcək sadələşdirmə burada düşəcək.

Saxtalar `test_face_control.py`-dan İDXAL olunur, nüsxə çıxarılmır: kadr sayı
və keyfiyyət həddi kimi qaydalar iki yerdə təqlid olunsaydı, biri dəyişəndə
digəri sükutla köhnələrdi.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases.face_control import (
    ENROLLMENT_FLAG,
    FaceControlPermissionError,
    FaceEnrollmentUseCase,
)
from src.domain.value_objects.face_recognition import (
    FaceControlError,
    FaceProfile,
    FaceSample,
)
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from tests.fixtures.fakes import (
    FakeCamera,
    FakeClock,
    FakeFaceMatcher,
    FakeSystemLimits,
    InMemoryFaceProfiles,
    RecordingAudit,
)
from tests.unit.test_face_control import (
    NOW,
    REFERENCE,
    TENANT,
    _employee,
    _profile,
)

pytestmark = pytest.mark.unit

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_APP: Final[Path] = _REPO / "src" / "presentation" / "app.py"
_GATE: Final[Path] = _REPO / "src" / "presentation" / "controllers" / "face_setup.py"


class FakeAdminCounter:
    """`AdminCounter` saxtası — YALNIZ bir metod (dar protokolun mənası)."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.asked: list[str] = []

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        self.asked.append(flag_code)
        return self.count


def _bootstrap(
    *, admin_count: int | None, profile: FaceProfile
) -> tuple[FaceEnrollmentUseCase, InMemoryFaceProfiles, RecordingAudit]:
    """Bootstrap yolu üçün use case qurur.

    `admin_count=None` — sayğac ÜMUMİYYƏTLƏ qoşulmur (kompozisiya səhvinin
    modeli).
    """
    clock = FakeClock(NOW)
    repository = InMemoryFaceProfiles([profile])
    audit = RecordingAudit()
    use_case = FaceEnrollmentUseCase(
        profiles=repository,
        camera=FakeCamera(available=True),
        matcher=FakeFaceMatcher([FaceSample(embedding=REFERENCE, quality=0.9)] * 8, clock=clock),
        limits=FakeSystemLimits(None),
        audit=audit,
        clock=clock,
        admins=None if admin_count is None else FakeAdminCounter(admin_count),
    )
    return use_case, repository, audit


# --------------------------------------------------------------------------- #
# SEC-025 — tenant-ın yeganə admini öz üzünü qeydiyyata salır
# --------------------------------------------------------------------------- #


def test_the_only_admin_may_enroll_their_own_face() -> None:
    """Nəzarət fiziki olaraq mümkün deyil — qeydiyyat KEÇİR."""
    ceo = _employee(flags=(ENROLLMENT_FLAG,), code="CEO")
    use_case, repository, audit = _bootstrap(admin_count=1, profile=_profile(ceo, embedding=None))

    use_case.enroll_first_account(tenant_id=TENANT, actor=ceo, subject_id=ceo.id)

    stored = repository.get_profile(ceo.id)
    assert stored is not None
    assert stored.is_enrolled

    # AUDİT AYRICA HƏRƏKƏTDİR: jurnala baxan adam bu qeydiyyatın nəzarətsiz
    # aparıldığını GÖRMƏLİDİR — adi `FACE_ENROLLED` yazısı bunu gizlədərdi.
    assert "FACE_ENROLLED_BOOTSTRAP" in audit.actions()
    assert "FACE_ENROLLED" not in audit.actions()


def test_a_second_admin_closes_the_bootstrap_path() -> None:
    """İkinci admin yarandığı an istisna ÖZ-ÖZÜNƏ bağlanır.

    Şərt «bu, ilk hesabdırmı?» deyil, «nəzarət mümkündürmü?» sualıdır — ona
    görə heç bir bayraq təmizlənmir və heç nə vaxta bağlanmır: sayğacın özü
    cavab verir.
    """
    ceo = _employee(flags=(ENROLLMENT_FLAG,), code="CEO")
    use_case, repository, _audit = _bootstrap(admin_count=2, profile=_profile(ceo, embedding=None))

    with pytest.raises(FaceControlPermissionError, match="başqa admin"):
        use_case.enroll_first_account(tenant_id=TENANT, actor=ceo, subject_id=ceo.id)

    stored = repository.get_profile(ceo.id)
    assert stored is not None
    assert not stored.is_enrolled


def test_bootstrap_asks_the_counter_about_the_enrollment_flag() -> None:
    """Sayğac «admin» sözünü DEYİL, konkret flag-i sayır.

    Başqa flag (məs. `can_view_reports`) sayılsaydı, hesabatçısı olan tenant-da
    yol vaxtından əvvəl bağlanardı — yəni CEO üzünü heç vaxt qeyd edə bilməzdi.
    """
    ceo = _employee(flags=(ENROLLMENT_FLAG,), code="CEO")
    counter = FakeAdminCounter(1)
    clock = FakeClock(NOW)
    use_case = FaceEnrollmentUseCase(
        profiles=InMemoryFaceProfiles([_profile(ceo, embedding=None)]),
        camera=FakeCamera(available=True),
        matcher=FakeFaceMatcher([FaceSample(embedding=REFERENCE, quality=0.9)] * 8, clock=clock),
        limits=FakeSystemLimits(None),
        audit=RecordingAudit(),
        clock=clock,
        admins=counter,
    )

    use_case.enroll_first_account(tenant_id=TENANT, actor=ceo, subject_id=ceo.id)

    assert counter.asked == [ENROLLMENT_FLAG]


def test_bootstrap_is_only_for_the_actors_own_face() -> None:
    """Başqasının üzü bu yoldan KEÇMİR — nəzarət qapısı öz işini görməlidir."""
    ceo = _employee(flags=(ENROLLMENT_FLAG,), code="CEO")
    use_case, _repo, _audit = _bootstrap(admin_count=1, profile=_profile(ceo, embedding=None))

    with pytest.raises(FaceControlPermissionError, match="yalnız aktorun"):
        use_case.enroll_first_account(
            tenant_id=TENANT, actor=ceo, subject_id=EmployeeId(uuid.uuid4())
        )


def test_bootstrap_still_requires_the_enrollment_flag() -> None:
    """Səlahiyyət yoxlaması istisnadan AZAD DEYİL.

    İstisna yalnız «aktor = subyekt» qadağasına aiddir; flag tələbi qalır,
    əks halda hər işçi ilk hesab olduğunu iddia edib keçərdi.
    """
    seller = _employee(code="SATICI")
    use_case, _repo, _audit = _bootstrap(admin_count=1, profile=_profile(seller, embedding=None))

    with pytest.raises(FaceControlPermissionError, match=ENROLLMENT_FLAG):
        use_case.enroll_first_account(tenant_id=TENANT, actor=seller, subject_id=seller.id)


def test_bootstrap_fails_closed_without_the_counter() -> None:
    """Sayğac qoşulmayıbsa yol AÇIQ QALMIR.

    Fail-open olsaydı, `composition.py`-da bir sətrin unudulması istisnanı HƏR
    hesaba açardı — yəni nəzarət qaydası sükutla ləğv olardı və bunu heç bir
    xəta göstərməzdi.
    """
    ceo = _employee(flags=(ENROLLMENT_FLAG,), code="CEO")
    use_case, _repo, _audit = _bootstrap(admin_count=None, profile=_profile(ceo, embedding=None))

    with pytest.raises(FaceControlPermissionError, match="sayğac"):
        use_case.enroll_first_account(tenant_id=TENANT, actor=ceo, subject_id=ceo.id)


def test_bootstrap_does_not_overwrite_an_existing_enrollment() -> None:
    """Mövcud qeydiyyat sükutla ÜSTÜNDƏN YAZILMIR — adi yolla eyni qayda."""
    ceo = _employee(flags=(ENROLLMENT_FLAG,), code="CEO")
    use_case, _repo, _audit = _bootstrap(admin_count=1, profile=_profile(ceo))

    with pytest.raises(FaceControlError, match="artıq"):
        use_case.enroll_first_account(tenant_id=TENANT, actor=ceo, subject_id=ceo.id)


def test_the_supervised_ban_is_untouched() -> None:
    """Adi `enroll()` yolu DƏYİŞMƏYİB — istisna YALNIZ bootstrap metodundadır.

    Bu bənd olmasaydı, sabah kimsə eyni güzəşti `enroll()`-a da köçürə bilər və
    qadağa yalnız adı ilə qalardı.
    """
    ceo = _employee(flags=(ENROLLMENT_FLAG,), code="CEO")
    use_case, _repo, _audit = _bootstrap(admin_count=1, profile=_profile(ceo, embedding=None))

    with pytest.raises(FaceControlPermissionError, match="özü apara bilməz"):
        use_case.enroll(tenant_id=TENANT, actor=ceo, subject_id=ceo.id)


# --------------------------------------------------------------------------- #
# İlk-giriş qapısı — HƏR İKİ giriş yolunda
# --------------------------------------------------------------------------- #


def test_both_login_doors_run_the_same_gate() -> None:
    """Panel girişi VƏ kiosk PIN-i eyni funksiyadan keçir.

    Yalnız birində qoysaydıq, digər qapı sükutla açıq qalardı: mağaza işçisi
    kioskdan girib üz qeydiyyatını heç vaxt keçməzdi — və bu, yalnız
    istehsalatda üzə çıxardı.
    """
    source = _APP.read_text(encoding="utf-8")

    # tərif + iki çağırış
    assert source.count("_show_face_setup_if_required(") >= 3
    assert "host=kiosk.set_content" in source, (
        "kioskda ekran ƏSAS pəncərəyə qoyulur — kiosk örtüyünün altında görünməzdi"
    )


def test_the_gate_lets_the_user_through_when_the_check_itself_fails() -> None:
    """Yoxlama çökərsə işçi GİRİŞDƏ İLİŞMİR.

    Üz qatı iş dayandıran nasazlığa çevrilməməlidir: baza cavab vermirsə işçi
    növbəyə çıxa bilməzdi. Ona görə `is_enrollment_required` uğursuzluqda
    `False` qaytarır və qapı da eyni istiqaməti seçir.
    """
    gate = _GATE.read_text(encoding="utf-8")
    body = gate[gate.index("def is_enrollment_required") :]
    body = body[: body.index("\nclass ")]

    assert "except Exception:" in body
    assert body.rstrip().count("return False") >= 2


def test_the_ceo_path_runs_after_the_wizard_not_at_login() -> None:
    """CEO qeydiyyatı sihirbazın SONUNDADIR.

    İlk girişə qoysaydıq, CEO həm nəzarətçisiz qalar, həm də tələb `EXEMPT_ROLES`
    ilə ziddiyyət yaradardı.
    """
    source = _APP.read_text(encoding="utf-8")
    setup = source[source.index("def _on_setup_completed") :]
    setup = setup[: setup.index("def _start_ceo_face_setup")]

    assert "_start_ceo_face_setup(payload)" in setup


def test_the_module_toggle_switches_the_requirement_off() -> None:
    """Üz qatı ROOT panelindən söndürülə bilər — tələb də onunla sönür.

    İstifadəçi «permission flaglarda facecontrol bağla-aç olmalıdır» dedi.
    Bunun üçün YENİ flag yaradılmır: `CAMERA_VERIFICATION` modul açarı artıq
    mövcuddur və STRUKTUR-KRİTİKdir (söndürmək yazılı təsdiq tələb edir).
    İkinci açar iki həqiqət mənbəyi demək olardı — biri açıq, digəri bağlı
    qalanda hansının üstün olduğu heç yerdə yazılmazdı.
    """
    from src.domain.policies import FeatureModule
    from src.presentation.app import FACE_MODULE_KEY
    from src.presentation.controllers.face_setup import FACE_MODULE

    assert FACE_MODULE == FACE_MODULE_KEY == FeatureModule.CAMERA_VERIFICATION.value
    assert FeatureModule.CAMERA_VERIFICATION.is_structural, (
        "üz qatı sadə toggle ilə söndürülür — yazılı təsdiq tələbi itib"
    )

    gate = _GATE.read_text(encoding="utf-8")
    assert re.search(r"is_enabled\(session\.tenant_id,\s*FACE_MODULE\)", gate), (
        "tələb modul açarını oxumur — söndürmək heç nəyi dəyişməzdi"
    )


def test_root_and_ceo_are_exempt_from_the_first_login_gate() -> None:
    """Sihirbazdan keçən pillə ilk girişdə TƏKRAR sorulmur.

    `EXEMPT_ROLES` bu iki pilləni kənarda saxlayır; siyahı genişlənsəydi
    (məs. mağaza meneceri əlavə olunsaydı) tələb sükutla boşalardı.
    """
    from src.domain.value_objects.authorization import SystemRole
    from src.presentation.controllers.face_setup import EXEMPT_ROLES

    assert frozenset({SystemRole.ROOT, SystemRole.CEO}) == EXEMPT_ROLES
