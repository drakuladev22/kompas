"""`Root` / `CEO` prioritet ayrılığı — domen ↔ DB pariteti (CLAUDE.md §5).

──────────────────────────────────────────────────────────────────────────────
BU MODUL HANSI KONSEPTUAL SƏHVİ TUTUR
──────────────────────────────────────────────────────────────────────────────
`RolePriority` uzun müddət `EXECUTIVE = 0` altında `Root` və `CEO`-nu BİRLƏŞDİR-
MİŞDİ. Nəticə ədəd səhvi deyildi — modelin ÖZÜ səhv idi:

    * `CEO` `Root` ilə BƏRABƏR pillədə sayılırdı;
    * "CEO Root-un icazələrinə toxuna bilmir" qaydası İYERARXİYADAN GƏLMİRDİ,
      yalnız iki əlavə qapının yan təsiri idi — `hardlock_level = 1` və
      bərabər-pillə şərti (`0 <= 0`);
    * yəni bir flag `ROOT_ONLY`-dən `ROOT_CEO`-ya keçsəydi, CEO həmin flag-i
      `Root` rolundan çıxara bilərdi və heç bir qat bunu tutmazdı.

Düzgün model: Root=0, CEO=1, Admin=2, operativ=3, Satıcı=4.

Aşağıdakı testlər HƏR İKİ yarını yoxlayır — domendəki `RolePriority` VƏ
DB-dəki ədədləri (seed, hardlock həddi, anti-fraud həddi, CHECK). Birinin
sükutla geri qayıtması ikincisi ilə uyğunsuzluq yaradar və məhz belə
uyğunsuzluqlar yalnız insidentdə üzə çıxır.

Naxış `test_db_guard_parity.py`-dandır: SQL mətn kimi oxunur, icra edilmir
(icra CI-dakı `db-schema` job-undadır).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases.position_management import MAX_CAMERA_ROLE_PRIORITY
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    HardlockLevel,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import PositionId

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"
MIGRATION_013: Final = "013_antifraud_hardening.sql"
MIGRATION_048: Final = "048_root_ceo_priority_split.sql"
MIGRATION_049: Final = "049_position_priority_range_narrowing.sql"

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")

#: `schema.sql` §21 seed bloku — `INSERT ... VALUES ... ON CONFLICT` arası.
_SEED_BLOCK_RE: Final = re.compile(
    r"INSERT\s+INTO\s+positions\s*\(\s*tenant_id.*?VALUES(?P<rows>.*?)ON\s+CONFLICT",
    re.DOTALL | re.IGNORECASE,
)

#: Blok daxilindəki bir sətir: (NULL, 'KOD', 'Ad', PRİORİTET, ...)
_SEED_ROW_RE: Final = re.compile(
    r"\(\s*NULL\s*,\s*'(?P<code>[A-Z_]+)'\s*,\s*'[^']*'\s*,\s*(?P<priority>\d+)\s*,"
)

#: Spesifikasiya bölmə 3-ün ədədi modeli — testin YEGANƏ həqiqət mənbəyi.
EXPECTED_MODEL: Final[dict[SystemRole, int]] = {
    SystemRole.ROOT: 0,
    SystemRole.CEO: 1,
    SystemRole.ADMIN: 2,
    SystemRole.HR_ADMIN: 3,
    SystemRole.STORE_MANAGER: 3,
    SystemRole.CAMERA_OPERATOR: 3,
    SystemRole.SELLER: 4,
}


def _executable_sql(path: Path) -> str:
    """Şərhsiz SQL — DOWN bloku şərh içindədir və sayılmamalıdır."""
    return _LINE_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))


def _migration_048() -> Path:
    return MIGRATIONS_DIR / MIGRATION_048


def _migration_049() -> Path:
    return MIGRATIONS_DIR / MIGRATION_049


def _migration_013() -> Path:
    return MIGRATIONS_DIR / MIGRATION_013


def _seeded_priorities() -> dict[str, int]:
    """`schema.sql` §21 seed blokundan (kod → prioritet) xəritəsi."""
    block = _SEED_BLOCK_RE.search(_executable_sql(SCHEMA_FILE))
    assert block is not None, "`schema.sql`-də §21 rol seed bloku tapılmadı"
    return {
        match.group("code"): int(match.group("priority"))
        for match in _SEED_ROW_RE.finditer(block.group("rows"))
    }


def _shift_statement() -> str:
    """048-dəki prioritet sürüşdürən `UPDATE` ifadəsi (nöqtəli vergülə qədər)."""
    sql = _executable_sql(_migration_048())
    start = sql.find("UPDATE positions p")
    assert start >= 0, "048-də prioritet sürüşdürən UPDATE tapılmadı"
    end = sql.find(";", start)
    return sql[start : end + 1]


# --------------------------------------------------------------------------- #
# 1. DOMEN YARISI
# --------------------------------------------------------------------------- #


def test_domain_model_matches_the_specification_numbers() -> None:
    """`RolePriority` ədədləri bölmə 3-dəki nərdivanla eynidir."""
    actual = {role: int(role.default_priority) for role in SystemRole}
    assert actual == EXPECTED_MODEL


def test_root_occupies_its_rung_alone() -> None:
    """Pillə 0-da `Root`-dan başqa HEÇ BİR sistem rolu yoxdur.

    Bu, konseptual səhvin birbaşa reqressiya qapısıdır: `CEO`-nun yenidən
    0-a qaytarılması məhz burada tutulur.
    """
    on_root_rung = [role for role in SystemRole if role.default_priority is RolePriority.ROOT]
    assert on_root_rung == [SystemRole.ROOT]


def test_ceo_sits_exactly_one_rung_below_root() -> None:
    ceo = SystemRole.CEO.default_priority
    root = SystemRole.ROOT.default_priority
    assert int(ceo) - int(root) == 1
    assert root.outranks(ceo) is True
    assert ceo.outranks(root) is False


def test_priority_zero_custom_role_never_gains_root_semantics() -> None:
    """`_PRIORITY_TO_ROLE[ROOT]` QƏSDƏN `SystemRole.CEO`-dur.

    `RolePriority`-yə `ROOT` üzvü əlavə edildikdən sonra ən aşkar (və ən
    təhlükəli) addım xəritəni `SystemRole.ROOT`-a bağlamaqdır. O halda
    prioritet 0-lı CUSTOM rol həqiqi `Root` rolunun flag dəstini redaktə edə
    və `ROOT_ONLY` flag-lərinə toxuna bilərdi; üstəlik DB trigger-ləri Root
    istisnasını rol KODU ilə verdiyi üçün iki qat FƏRQLİ qərar verərdi.
    """
    shadow = Position(
        position_id=PositionId(uuid.uuid4()),
        code="KÖLGƏ_ROOT",
        name_az="Kölgə Root",
        priority=RolePriority.ROOT,
        is_system=False,
    )

    assert shadow.effective_system_role is SystemRole.CEO
    # `Root` semantikası YALNIZ kod vasitəsilə əldə olunur.
    assert shadow.system_role is None


def test_hardlock_delegable_still_covers_exactly_root_ceo_admin() -> None:
    """`DELEGABLE` həddi SİMVOLLADIR — sürüşmə onun əhatəsini dəyişməməlidir.

    Əgər müqayisə ədədə (`<= 1`) bağlansaydı, prioritet ayrılığından sonra
    `Admin` (2) sükutla kənarda qalardı və `can_control_user_permissions`
    ona verilə bilməzdi — spesifikasiya isə Admin-i AÇIQ daxil edir.
    """
    allowed = {role for role in SystemRole if HardlockLevel.DELEGABLE.allows(role)}
    assert allowed == {SystemRole.ROOT, SystemRole.CEO, SystemRole.ADMIN}


def test_root_ceo_hardlock_semantics_survive_the_split() -> None:
    """`ROOT_CEO` (=2) hələ də «Root VƏ CEO» deməkdir.

    Hardlock "flag kimə VERİLƏ bilər" sualına cavabdır; prioritet ayrılığı
    isə "kim kimə TOXUNA bilər" sualına aiddir. İki qat QƏSDƏN müstəqildir,
    ona görə ayrılıq `ROOT_CEO`-nun əhatəsini dəyişməməlidir.
    """
    allowed = {role for role in SystemRole if HardlockLevel.ROOT_CEO.allows(role)}
    assert allowed == {SystemRole.ROOT, SystemRole.CEO}

    root_only = {role for role in SystemRole if HardlockLevel.ROOT_ONLY.allows(role)}
    assert root_only == {SystemRole.ROOT}


def test_camera_role_ceiling_is_the_operational_rung() -> None:
    """`MAX_CAMERA_ROLE_PRIORITY` sürüşmə ilə birlikdə 2-dən 3-ə keçir.

    Semantika DƏYİŞMİR — hədd yenə "operativ pillə"dir; dəyişən yalnız
    həmin pillənin ədədidir. DB tərəfindəki `chk_camera_role_priority`
    aşağıda ayrıca yoxlanılır.
    """
    assert MAX_CAMERA_ROLE_PRIORITY is RolePriority.OPERATIONAL
    assert int(MAX_CAMERA_ROLE_PRIORITY) == 3
    assert int(RolePriority.STAFF) > int(MAX_CAMERA_ROLE_PRIORITY)


# --------------------------------------------------------------------------- #
# 2. SEED YARISI (`schema.sql` §21) — TƏZƏ QURAŞDIRMA
# --------------------------------------------------------------------------- #


def test_schema_seed_priorities_match_the_domain() -> None:
    """Təzə quraşdırılan baza domenlə EYNİ nərdivanı yazmalıdır.

    Fərq olsaydı, `mappers.position_from_row` bazadan oxuduğu ədədi başqa
    pilləyə çevirərdi — yəni ekran bir şey göstərər, guard başqa qərar verərdi.
    """
    seeded = _seeded_priorities()

    for role, expected in EXPECTED_MODEL.items():
        assert seeded.get(role.value) == expected, (
            f"`schema.sql` §21 seed-ində '{role.value}' prioriteti "
            f"{seeded.get(role.value)}-dir, domendə isə {expected}"
        )


def test_schema_seed_does_not_put_two_roles_on_the_root_rung() -> None:
    """Seed-də 0 prioriteti YALNIZ `ROOT` sətrindədir."""
    zero_rows = [code for code, priority in _seeded_priorities().items() if priority == 0]
    assert zero_rows == ["ROOT"], (
        f"Prioritet 0-da birdən çox rol var: {zero_rows} — `Root` TƏK BAŞINA "
        f"ən üst pillədə olmalıdır (bölmə 3)"
    )


# --------------------------------------------------------------------------- #
# 3. MİQRASİYA YARISI (048) — MÖVCUD QURAŞDIRMALAR
# --------------------------------------------------------------------------- #


def test_migration_048_exists_and_carries_the_search_path_preamble() -> None:
    """Qapı testi: fayl yoxdursa aşağıdakılar yanlış olaraq "keçərdi"."""
    path = _migration_048()
    assert path.exists(), f"Miqrasiya tapılmadı: {path}"
    assert "SET search_path TO kompasos, public;" in path.read_text(encoding="utf-8")


def test_migration_048_shifts_every_role_except_root() -> None:
    """Sürüşdürmə PİLLƏYƏ görədir — custom rollar da daxil.

    Yalnız sistem rollarını yeniləsəydik, köhnə prioritet 1-li custom
    «Bölgə Rəhbəri» yerində qalar və `Admin` 2-yə qalxdıqdan sonra birdən-birə
    `CEO` pilləsinə YÜKSƏLƏRDİ — yəni miqrasiya sükutla səlahiyyət artırardı.
    """
    statement = _shift_statement()

    assert "SET priority = p.priority + 1" in statement, "Prioritet sürüşdürməsi yoxdur"
    assert "p.code <> 'ROOT'" in statement, (
        "Sürüşdürmə `ROOT` sətrini istisna etmir — `Root` 1-ə düşərdi"
    )
    # Rol kodlarına görə AĞ SİYAHI yoxdur: custom rollar da əhatə olunmalıdır.
    # (`'CEO'` istisnadır — o, idempotentlik markeridir, filtr deyil.)
    for system_code in ("HR_ADMIN", "MAGAZA_MENECERI", "KAMERA_NEZARETCISI", "SATICI", "ADMIN"):
        assert f"'{system_code}'" not in statement, (
            f"Sürüşdürmə '{system_code}' kodunu adbaad sayır — custom rollar "
            f"sürüşmədən kənarda qalardı"
        )


def test_migration_048_covers_template_rows_and_tenant_copies() -> None:
    """`tenant_id IS NULL` şablonu DA, kirayəçi nüsxələri DƏ köçürülməlidir.

    `seed_tenant_defaults()` şablondan kopyalayır; şablon yerində qalsaydı,
    miqrasiyadan SONRA yaradılan hər yeni kirayəçi köhnə (səhv) modellə
    doğulardı.
    """
    statement = _shift_statement()

    assert "IS NOT DISTINCT FROM" in statement, (
        "Əhatə müqayisəsi `IS NOT DISTINCT FROM` deyil — `tenant_id IS NULL` "
        "şablon sətirləri `=` müqayisəsində NULL verər və köçürülməzdi"
    )
    # Statement bütün `positions` sətirlərini əhatə edir: `tenant_id = ...`
    # formalı dar filtr YOXDUR.
    assert not re.search(r"p\.tenant_id\s*=\s*", statement, re.IGNORECASE)


def test_migration_048_is_idempotent_by_an_explicit_marker() -> None:
    """Təkrar icra prioritetləri İKİNCİ dəfə sürüşdürməməlidir.

    Marker: köhnə modeldə `CEO` sətri 0-dadır. Şərt olmasaydı, miqrasiyanın
    təkrar icrası `CEO`-nu 2-yə, `Satıcı`-nı 5-ə atardı — yəni düzəliş öz
    nəticəsini pozardı.
    """
    sql = _executable_sql(_migration_048())

    assert "ceo.code = 'CEO'" in sql and "ceo.priority = 0" in sql, (
        "İdempotentlik markeri yoxdur — təkrar icra prioritetləri yenidən sürüşdürər"
    )


def test_migration_048_is_reversible() -> None:
    """DOWN bloku `+1`-in tam əksini (`-1`) eyni şərtlə saxlamalıdır."""
    raw = _migration_048().read_text(encoding="utf-8")
    down_start = raw.find("DOWN (geri qaytarma)")
    assert down_start > 0, "DOWN bloku yoxdur (CLAUDE.md §7)"

    down = raw[down_start:]
    assert "priority = p.priority - 1" in down, "Geri qaytarma sürüşdürməsi yoxdur"
    assert "ceo.priority = 1" in down, (
        "DOWN blokunun markeri tərsinə çevrilməyib — geri qaytarma idempotent olmazdı"
    )


def test_migration_048_reopens_the_camera_check_before_shifting() -> None:
    """`chk_camera_role_priority` (`<= 2`) sürüşməni BLOKLAYARDI.

    Kamera rolu 2-dən 3-ə qalxır; CHECK açılmasaydı `UPDATE` çökərdi. Sıra
    vacibdir: əvvəl DROP, sonra UPDATE, sonra YENİ həddlə ADD.
    """
    sql = _executable_sql(_migration_048())

    drop_at = sql.find("DROP CONSTRAINT IF EXISTS chk_camera_role_priority")
    update_at = sql.find("SET priority = p.priority + 1")
    add_at = sql.find("ADD CONSTRAINT chk_camera_role_priority")

    assert -1 < drop_at < update_at < add_at, (
        "CHECK məhdudiyyəti sürüşmədən əvvəl açılıb sonra bağlanmır"
    )
    assert f"priority <= {int(MAX_CAMERA_ROLE_PRIORITY)}" in sql, (
        "Yeni CHECK həddi `MAX_CAMERA_ROLE_PRIORITY` ilə uyğun deyil"
    )


# --------------------------------------------------------------------------- #
# 4. ƏDƏDƏ BAĞLI DB QAYDALARI — DOMEN SİMVOLU İLƏ UYĞUNLUQ
# --------------------------------------------------------------------------- #


def test_db_hardlock_level_three_threshold_matches_the_admin_rung() -> None:
    """Səviyyə 3 (`DELEGABLE`) həddi DB-də ƏDƏDDİR və `Admin` pilləsidir.

    Domen `role.default_priority <= RolePriority.ADMIN` yazır (sürüşməni özü
    udur), DB isə ədəd yazmalıdır. Hədd 1-də qalsaydı, `Admin` (2)
    `can_control_user_permissions`-i DB səviyyəsində ALA BİLMƏZDİ.
    """
    sql = _executable_sql(_migration_048())
    expected = int(RolePriority.ADMIN)

    assert f"v_level = 3 AND COALESCE(v_priority, 9) > {expected}" in sql, (
        f"Səviyyə-3 həddi `> {expected}` deyil — domen ilə DB fərqli qərar verər"
    )


def test_db_anti_fraud_threshold_matches_the_staff_rung() -> None:
    """Anti-fraud "ən aşağı pillə" həddi `Satıcı` pilləsidir (4).

    Bu, miqrasiyanın ƏN KRİTİK sətridir. Hədd 3-də qalsaydı,
    `Kamera_Nəzarətçisi` (3) "ən aşağı pillə" sayılar və `can_verify_returns`
    / `can_issue_fines` flag-lərini DB səviyyəsində itirərdi — bütün kamera
    təsdiq axını dayanardı. Qadağa nə genişlənir, nə daralır: hədəf yenə
    `Satıcı` pilləsidir.
    """
    sql = _executable_sql(_migration_048())
    expected = int(RolePriority.STAFF)

    assert f"COALESCE(v_priority, 0) >= {expected}" in sql, (
        f"Anti-fraud həddi `>= {expected}` deyil — ya kamera rolu flag-lərini "
        f"itirir, ya da Satıcı pilləsi qadağadan çıxır"
    )


def test_schema_and_migration_agree_on_the_hardlock_threshold() -> None:
    """`schema.sql` (təzə quraşdırma) və 048 (mövcud baza) EYNİ ədədi yazmalıdır.

    CLAUDE.md §7: `schema.sql` təkbaşına tam quraşdırmadır. İki tərif
    ayrılsaydı, təzə baza ilə yenilənmiş baza FƏRQLİ hardlock qaydası ilə
    işləyərdi.
    """
    threshold = f"v_level = 3 AND COALESCE(v_priority, 9) > {int(RolePriority.ADMIN)}"
    assert threshold in _executable_sql(SCHEMA_FILE)
    assert threshold in _executable_sql(_migration_048())


# --------------------------------------------------------------------------- #
# 5. `positions.priority` DİAPAZONU (049) — DOMEN ↔ CHECK PARİTETİ
# --------------------------------------------------------------------------- #
#
# BU BÖLMƏNİN ƏHATƏSİ VƏ ƏHATƏSİZLİYİ (gələcək oxucu üçün AÇIQ qeyd)
# ───────────────────────────────────────────────────────────────────────────
# Aşağıdakılar SQL-i MƏTN kimi oxuyur, İCRA ETMİR. Yəni onlar "ədədlər domen
# simvolları ilə uyğundurmu" sualına cavab verir, "miqrasiya real bazada
# işləyirmi" sualına YOX. YALNIZ real Postgres ilə yoxlana biləcək ssenarilər:
#
#   * `pg_get_constraintdef()` mətninin faktiki formatı (Postgres `BETWEEN`-i
#     `((priority >= 0) AND (priority <= 4))` kimi normallaşdırır) — 049-un
#     köhnə CHECK-i TAPA bilməsi məhz buna baxır;
#   * `RAISE WARNING` sətirlərinin həqiqətən çıxması və miqrasiyanın onlara
#     baxmayaraq DAVAM etməsi;
#   * `UPDATE positions SET priority = 4` -in `chk_camera_role_priority` ilə
#     ziddiyyət yaratmaması;
#   * miqrasiyaların ARDICIL icrası (schema → 013 → … → 048 → 049) və
#     idempotentlik (hər faylın İKİ dəfə icrası).
#
# Bu ssenariler CI-dakı `db-schema` job-undadır. Bu maşında `psql`/`docker`
# yoxdur, ona görə statik yoxlama TAM ƏVƏZ DEYİL — o, yalnız "ədəd sürüşməsi"
# sinfindəki qüsurları tutur (təcrübədə ən tez-tez baş verən sinif budur).

#: `schema.sql` §5 sütun tərifindəki diapazon.
_SCHEMA_RANGE_RE: Final = re.compile(
    r"priority\s+SMALLINT\s+NOT\s+NULL\s+CHECK\s*\(\s*priority\s+BETWEEN\s+(\d+)\s+AND\s+(\d+)\s*\)",
    re.IGNORECASE,
)

#: 049-dakı yeni məhdudiyyət.
_MIGRATION_RANGE_RE: Final = re.compile(
    r"ADD\s+CONSTRAINT\s+chk_positions_priority_range\s+CHECK\s*"
    r"\(\s*priority\s+BETWEEN\s+(\d+)\s+AND\s+(\d+)\s*\)",
    re.IGNORECASE,
)

#: 049-dakı endirmə: `UPDATE positions SET priority = N WHERE priority > M`.
_DOWNSHIFT_RE: Final = re.compile(
    r"UPDATE\s+positions\s+SET\s+priority\s*=\s*(?P<target>\d+)\s+"
    r"WHERE\s+priority\s*>\s*(?P<threshold>\d+)",
    re.IGNORECASE,
)


def _domain_range() -> tuple[int, int]:
    values = [int(member) for member in RolePriority]
    return min(values), max(values)


def test_schema_priority_check_matches_the_role_priority_members() -> None:
    """CHECK həddi `RolePriority` üzvlərindən AVTOMATİK çıxarılır.

    Sabit ədəd YAZILMIR: gələcəkdə `Satıcı`-dan aşağı altıncı pillə əlavə
    olunarsa, bu test dərhal xəbər verər — çünki domendəki maksimum dəyişər,
    `schema.sql`-dəki CHECK isə yerində qalar. Məhz həmin növ sükutlu ayrılıq
    049-dan əvvəl mövcud idi (domen 0..4, DB 0..9).
    """
    match = _SCHEMA_RANGE_RE.search(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert match is not None, "`schema.sql` §5-də `positions.priority` CHECK-i tapılmadı"

    low, high = int(match.group(1)), int(match.group(2))
    assert (low, high) == _domain_range(), (
        f"`schema.sql` CHECK-i {low}..{high}, `RolePriority` isə {_domain_range()} "
        f"aralığındadır — bazada qanuni, tətbiqdə oxunmaz sətir yarana bilər"
    )


def test_priority_ladder_has_no_gaps() -> None:
    """Nərdivan FASİLƏSİZDİR — CHECK diapazonu ilə üzv sayı üst-üstə düşür.

    Fasilə olsaydı (məs. 0,1,2,4), diapazon yoxlaması hələ də keçər, lakin
    DB aradakı boş ədədi (3) qəbul edər və domen onu oxuya bilməzdi.
    """
    low, high = _domain_range()
    assert len(RolePriority) == high - low + 1
    assert sorted(int(member) for member in RolePriority) == list(range(low, high + 1))


def test_migration_049_exists_with_the_required_preamble_and_down_block() -> None:
    """Qapı testi — fayl yoxdursa aşağıdakılar yanlış olaraq "keçərdi"."""
    path = _migration_049()
    assert path.exists(), f"Miqrasiya tapılmadı: {path}"

    raw = path.read_text(encoding="utf-8")
    assert "SET search_path TO kompasos, public;" in raw, "`search_path` preambulası yoxdur"
    assert "DOWN (geri qaytarma)" in raw, "DOWN bloku yoxdur (CLAUDE.md §7)"
    assert "COMMENT ON CONSTRAINT chk_positions_priority_range" in raw, "COMMENT yoxdur"
    assert "COMMENT ON COLUMN positions.priority" in raw, "Sütun COMMENT-i yenilənməyib"


def test_migration_049_narrows_to_exactly_the_domain_range() -> None:
    """049-dakı yeni CHECK `schema.sql`-dəki ilə EYNİ diapazondadır.

    CLAUDE.md §7: `schema.sql` təkbaşına tam quraşdırmadır, miqrasiya isə
    MÖVCUD bazanı ora gətirir. İkisi ayrılsaydı, təzə baza ilə yenilənmiş baza
    fərqli qaydaya tabe olardı.
    """
    match = _MIGRATION_RANGE_RE.search(_executable_sql(_migration_049()))
    assert match is not None, "049-da `chk_positions_priority_range` tapılmadı"

    assert (int(match.group(1)), int(match.group(2))) == _domain_range()


def test_migration_049_downshift_never_raises_authority() -> None:
    """Endirmə İSTİQAMƏTİ aşağıdır — `priority`-də KİÇİK rəqəm YÜKSƏK səlahiyyətdir.

    Ən təhlükəli səhv variant: diapazondan kənar sətri "ən yaxın icazəli üst
    pilləyə" (məs. 0 və ya 2) gətirmək. O halda miqrasiya sükutla SƏLAHİYYƏT
    ARTIRARDI — birbaşa SQL ilə yazılmış 7-lik bir rol birdən-birə `Admin`,
    hətta `Root` pilləsinə qalxardı.

    Ona görə hədəf dəyər domendəki MAKSİMUM (ən az səlahiyyətli) pillə
    olmalıdır və o, endirmə həddi ilə eyni ədəd olmalıdır.
    """
    match = _DOWNSHIFT_RE.search(_executable_sql(_migration_049()))
    assert match is not None, "049-da endirmə `UPDATE`-i tapılmadı"

    target = int(match.group("target"))
    threshold = int(match.group("threshold"))
    _, lowest_rung = _domain_range()

    assert target == lowest_rung == int(RolePriority.STAFF), (
        f"Endirmə hədəfi {target}-dir, ən aşağı pillə isə {lowest_rung} — "
        f"miqrasiya səlahiyyət artırır"
    )
    assert threshold == target, (
        "Şərt ilə hədəf fərqlidir: yalnız diapazondan kənar sətirlər toxunulmalıdır"
    )
    # Toxunulan HƏR sətir üçün yeni dəyər köhnəsindən KİÇİK ola bilməz:
    # şərt `> target` olduğuna görə köhnə dəyər həmişə `target`-dən böyükdür.
    assert threshold >= int(RolePriority.STAFF)


def test_migration_049_does_not_block_the_installation() -> None:
    """Diapazondan kənar sətir `RAISE WARNING` verir, `RAISE EXCEPTION` YOX.

    Belə sətir tətbiqdə ONSUZ DA işləmirdi (`RolePriority(...)` → ValueError),
    ona görə miqrasiyanı çökdürmək problemi həll etmir — onu bütün
    quraşdırmanı bloklayan daha böyük problemə çevirir.
    """
    sql = _executable_sql(_migration_049())

    assert "RAISE EXCEPTION" not in sql, (
        "049 istisna atır — diapazondan kənar sətir quraşdırmanı bloklamamalıdır"
    )
    assert "RAISE WARNING" in sql, "Endirmə sükutla baş verir — operator xəbər tutmalıdır"
    assert "DELETE" not in sql.upper(), "049 sətir silir — heç bir rol itməməlidir"


def test_migration_049_leaves_the_camera_constraint_untouched() -> None:
    """`chk_camera_role_priority` DA `priority`-dən danışır — o, AYRI qaydadır.

    049 köhnə diapazon CHECK-ini ADI ilə yox, TƏRİFİ ilə tapır; süzgəc
    `is_camera_type`-i istisna etməsəydi, miqrasiya kamera qaydasını (SEC-001
    ailəsi) sükutla SİLƏRDİ.
    """
    sql = _executable_sql(_migration_049())

    assert "NOT LIKE '%is_camera_type%'" in sql, (
        "049 kamera CHECK-ini istisna etmir — anti-fraud qaydası silinə bilər"
    )
    assert "DROP CONSTRAINT IF EXISTS chk_camera_role_priority" not in sql


# --------------------------------------------------------------------------- #
# 6. MİQRASİYA ZƏNCİRİNİN ARDICIL OXUNUŞU
# --------------------------------------------------------------------------- #


def test_migration_chain_is_consistent_from_schema_through_049() -> None:
    """schema → 013 → 048 → 049 ardıcıllığı ziddiyyət YARATMIR.

    Hər faylın ədədi ayrıca doğru ola bilər, LAKİN ardıcıl tətbiq olunanda
    ziddiyyət yarada bilər. Zəncirin dörd düyünü:

        1. `schema.sql` §21 seed  → təzə bazanın BAŞLANĞIC prioritetləri;
        2. `013`  → anti-fraud "ən aşağı pillə" həddi (KÖHNƏ model: 3);
        3. `048`  → bütün qeyri-`ROOT` sətirlərə `+1` və həddlərin yenilənməsi;
        4. `049`  → diapazonun 0..4-ə daraldılması.

    Kritik nöqtə: 049 mütləq 048-DƏN SONRA gəlməlidir. Əks halda köhnə modeldə
    4-də olan custom rol 048-in sürüşməsində 5-ə keçər və YENİ CHECK-ə ilişib
    048-i çökdürərdi.
    """
    assert int(MIGRATION_049[:3]) > int(MIGRATION_048[:3]) > int(MIGRATION_013[:3])

    _, ceiling = _domain_range()

    # (1) Seed maksimumu yeni CHECK-in tavanını AŞMIR.
    assert max(_seeded_priorities().values()) == ceiling

    # (2) 013-ün KÖHNƏ anti-fraud həddi + 048-in sürüşməsi = yeni `Satıcı` pilləsi.
    legacy = re.search(r"COALESCE\(v_priority, 0\) >= (\d+)", _executable_sql(_migration_013()))
    assert legacy is not None, "013-də anti-fraud həddi tapılmadı"
    assert int(legacy.group(1)) + 1 == int(RolePriority.STAFF), (
        "013-ün həddi 048-in sürüşməsi ilə `Satıcı` pilləsinə düşmür — "
        "ya kamera rolu flag-lərini itirir, ya Satıcı qadağadan çıxır"
    )

    # (3) 048-in sürüşmədən SONRAKI maksimumu 049-un tavanına BƏRABƏRDİR,
    #     yəni daraltma sürüşməni geri sındırmır.
    assert "SET priority = p.priority + 1" in _shift_statement()
    assert int(RolePriority.STAFF) == ceiling

    # (4) 013-ün kamera həddi `Satıcı - 1` düsturu ilə hesablanır; domen
    #     qarşılığı SİMVOLDUR və sürüşmədən sonra da eyni münasibətdə qalır.
    assert int(MAX_CAMERA_ROLE_PRIORITY) == int(RolePriority.STAFF) - 1
    assert "v_seller_priority - 1" in _executable_sql(_migration_013())


def test_migration_048_precheck_stays_inside_the_new_range() -> None:
    """048-in `priority >= 9` qapısı 049-dan sonra əlçatmaz olur — və bu, DOĞRUDUR.

    048 sürüşmədən əvvəl 9-luq sətir axtarır (çünki `+1` köhnə 0..9 CHECK-ini
    aşardı). 049 diapazonu 0..4-ə daraltdıqdan sonra belə sətir MÖVCUD ola
    bilmir. Qapı silinmir: 048 mövcud bazalara TARİXİ sıra ilə (049-dan əvvəl)
    tətbiq olunur və o an hədd hələ 0..9-dur.

    Test bunu sabitləşdirir ki, kimsə "artıq lazım deyil" deyib 048-i sonradan
    redaktə etməsin — həmin redaktə hələ 048-ə çatmamış bazaları qırardı.
    """
    sql = _executable_sql(_migration_048())
    assert "p.priority >= 9" in sql
    assert "MIGRATION 048 DAYANDIRILDI" in sql
