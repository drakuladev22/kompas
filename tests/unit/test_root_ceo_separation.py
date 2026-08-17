"""SEC-024 — `Root` təchizatçının, `CEO` müştərinin pilləsidir.

──────────────────────────────────────────────────────────────────────────────
İKİ QÜSUR, BİR KÖK
──────────────────────────────────────────────────────────────────────────────
İstifadəçi hesabatı iki cümlədən ibarət idi:

    «first run wizardda ancaq ceolar olmalıdır, niyə root permission
     verirsən?»
    «ceo rootun icazə matrisini dəyişə bilir, bu çox məntiqsizdir»

Kök birdir: `Root` pilləsi TƏCHİZATÇININDIR (developer), `CEO` isə
müştərinin ən yüksək hesabıdır. Baza seed-i bunu ARTIQ bilirdi — `CEO`
şablonunda beş açar QƏSDƏN yoxdur (`can_manage_system_limits`,
`can_manage_permissions`, `can_manage_plugins`, `can_switch_db`,
`can_manage_license`). Pozan tərəf sihirbaz idi: müştəriyə `Root` verirdi.

──────────────────────────────────────────────────────────────────────────────
QAPI NƏ ÖLÇÜR
──────────────────────────────────────────────────────────────────────────────
    1. Sihirbaz `CEO` yaradır və `Root` rolunu TƏLƏB ETMİR;
    2. `CEO` icazə matrisində `Root` sətrini GÖRMÜR (yazma onsuz da
       bloklanır — bu, görüntü tərəfidir);
    3. `Root` isə hər şeyi görür (SEC-006 istisnası).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from src.domain.value_objects.authorization import SystemRole

pytestmark = pytest.mark.unit

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_SETUP: Final[Path] = _REPO / "src" / "application" / "use_cases" / "first_run_setup.py"


def test_the_wizard_asks_for_the_executive_role_not_root() -> None:
    """Sihirbaz `_require_position(...)`-a `CEO` verir.

    Yoxlama MƏTN səviyyəsindədir, çünki qüsur məhz bir sabitin seçimində idi
    və davranış testi (saxta repo) həmin sabiti ÖZÜ təqlid edir — yəni
    fake-i də dəyişən adam qapını fərqinə varmadan yan keçə bilərdi.
    """
    source = _SETUP.read_text(encoding="utf-8")
    calls = re.findall(r"_require_position\(\s*tenant_id,\s*SystemRole\.(\w+)\.value", source)
    assert calls, "sihirbaz artıq `_require_position` çağırmır — qapı köhnəlib"
    assert set(calls) == {SystemRole.CEO.name}, (
        f"sihirbaz `{calls}` rolunu tələb edir — müştəri quraşdırması yalnız "
        "`CEO` yaratmalıdır (`Root` təchizatçının pilləsidir)"
    )


def test_the_seed_keeps_the_vendor_flags_away_from_the_executive() -> None:
    """`CEO` şablonu təchizatçı açarlarını DAŞIMAMALIDIR.

    Siyahı `schema.sql`-in seed blokundan oxunur: qayda orada yaşayır, burada
    yalnız QORUNUR. Açarlardan biri `CEO`-ya verilsəydi, sihirbazın rolu
    dəyişdirməsinin mənası qalmazdı — müştəri yenə eyni səlahiyyəti alardı.
    """
    schema = (_REPO / "database" / "schema.sql").read_text(encoding="utf-8")
    vendor_flags = (
        "can_manage_system_limits",
        "can_manage_permissions",
        "can_manage_plugins",
        "can_switch_db",
        "can_manage_license",
    )

    # Seed sətirləri `('CEO', 'can_...', TRUE)` formasındadır.
    granted_to_ceo = set(re.findall(r"'CEO',\s*'(can_\w+)',\s*TRUE", schema))
    leaked = sorted(set(vendor_flags) & granted_to_ceo)
    assert not leaked, f"təchizatçı açarları `CEO` şablonuna sızıb: {leaked}"


def test_the_matrix_hides_roles_the_actor_cannot_touch() -> None:
    """`list_roles` süzgəci `may_be_edited_by`-dan keçir.

    Süzgəc TƏHLÜKƏSİZLİK QAPISI DEYİL — əsl qapı
    `Position.assert_may_be_edited_by()`-dədir. Lakin süzgəc olmasa, ekran
    dəyişdirilə bilməyən sətri redaktə oluna bilən kimi göstərir və
    istifadəçi rədd cavabını yalnız «Yadda Saxla»dan sonra görür.
    """
    source = (_REPO / "src" / "application" / "use_cases" / "position_management.py").read_text(
        encoding="utf-8"
    )
    assert "may_be_edited_by(actor.position)" in source, "rol siyahısı süzgəcsizdir"


def test_the_silent_predicate_and_the_raising_guard_agree() -> None:
    """`may_be_edited_by` ilə `assert_may_be_edited_by` EYNİ cavabı verməlidir.

    İkisi ayrı metoddur (biri jurnal yazır, digəri yox) və məhz buna görə
    sürüşə bilər. Qapı hər kombinasiyanı gəzir.
    """
    import uuid

    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import AuthorizationError
    from src.domain.value_objects.identifiers import PositionId

    def make(role: SystemRole) -> Position:
        return Position(
            position_id=PositionId(uuid.uuid4()),
            code=role.value,
            name_az=role.value.title(),
            priority=role.default_priority,
            is_system=True,
        )

    roles = [make(role) for role in SystemRole]
    for actor in roles:
        for target in roles:
            try:
                target.assert_may_be_edited_by(actor)
            except AuthorizationError:
                allowed = False
            else:
                allowed = True
            assert target.may_be_edited_by(actor) is allowed, (
                f"{actor.code} → {target.code}: səssiz yoxlama qapıdan fərqlənir"
            )

    # Qapının ÖZÜ: ən azı bir qadağan hal olmalıdır, əks halda yuxarıdakı
    # dövrə hər şeyi «icazəli» kimi təsdiqləyər və heç nə ölçməz.
    ceo = make(SystemRole.CEO)
    root = make(SystemRole.ROOT)
    assert not root.may_be_edited_by(ceo), "CEO `Root` rolunu redaktə edə bilir"
    assert not ceo.may_be_edited_by(ceo), "bərabər pillə bloklanmır (SEC-006)"
    assert root.may_be_edited_by(root), "`Root` öz rolunu redaktə edə bilmir"

    # İSTİQAMƏT TƏK TƏRƏFLİ OLMALIDIR: `CEO`-nun nə edib-edə bilməyəcəyini
    # TƏCHİZATÇI təyin edir. Bu bənd olmasaydı, «CEO Root-a toxuna bilmir»
    # iddiası «heç kim heç kimə toxuna bilmir» halında da keçərdi və idarəetmə
    # zənciri tamamilə qopardı.
    assert ceo.may_be_edited_by(root), "`Root` `CEO` rolunu idarə edə bilmir"


def test_the_actor_context_is_required() -> None:
    """Aktor naməlumdursa cavab FAIL-CLOSED olmalıdır."""
    import uuid

    from src.domain.entities.position import Position
    from src.domain.value_objects.identifiers import PositionId

    seller = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.SELLER.value,
        name_az="Satıcı",
        priority=SystemRole.SELLER.default_priority,
        is_system=True,
    )
    assert seller.may_be_edited_by(None) is False
