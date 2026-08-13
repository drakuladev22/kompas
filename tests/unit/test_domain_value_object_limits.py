"""Domen value object sabitlərinin ROOT-a köçürülməsinin qapısı (Faza 10.2).

──────────────────────────────────────────────────────────────────────────────
BU FAYL NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
`src/domain/value_objects/` altında 22 ədəd sabit kimi yaşayırdı. Köçürmə
DAVRANIŞ dəyişikliyi DEYİL, idarəolunma dəyişikliyidir — ona görə burada iki
fərqli sual ayrı-ayrı yoxlanılır:

  1. **Defolt köhnə hardcode ilə eynidirmi?** (`_HISTORICAL` cədvəli). Bu sual
     "yaxşılaşdırılmış defolt" adlı sükutlu reqressiyanı bağlayır: 86400 ≠
     43200, 720 ≠ 480. Cədvəl ƏL İLƏ yazılıb və `DEFAULT_LIMITS`-dən
     TÖRƏMİR — əks halda test öz yoxladığı dəyəri özündən oxuyardı.
  2. **Root dəyəri dəyişdikdə kod onu görürmü?** Domen sinifləri limit portu
     TANIMIR (CLAUDE.md §3), dəyəri PARAMETR kimi qəbul edir. Ona görə burada
     istehlakçı naxışı təkrarlanır: `FakeSystemLimits` → `_limit_int` → domen
     funksiyası. Parametr ötürülməsi qırılsa, test dərhal qırmızı olur.

──────────────────────────────────────────────────────────────────────────────
ÜÇÜNCÜ SUAL: ŞƏRH DOĞRU DANIŞIRMI
──────────────────────────────────────────────────────────────────────────────
Köçürmədən əvvəl `gamification.py` şərhi `POINTS_PER_CURRENCY_UNIT` adlı bir
ROOT limitinə istinad edirdi — belə açar HEÇ VAXT mövcud olmayıb. Yəni sənəd
"idarə olunur" deyirdi, kod isə ədədi özündə saxlayırdı və heç bir qapı bu
fərqi tutmurdu. `test_no_comment_references_a_nonexistent_limit_key` məhz bu
QÜSUR SİNFİNİ bağlayır: domen faylındakı hər `system_limits.X` /
`SystemLimitKey.X` istinadı real açar olmalıdır.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from src.domain.entities.sales_points import PointsEntry
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects import catalogs, erp, gamification, infrastructure, licensing, storage
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PointsEntryId,
    StoreId,
    TenantId,
    new_tenant_id,
)
from src.domain.value_objects.infrastructure import DatabaseTarget, MaintenanceWindow, MigrationPlan
from tests.fixtures.fakes import FakeSystemLimits

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_MIGRATION: Final[Path] = (
    _REPO_ROOT / "database" / "migrations" / "033_domain_value_object_limits.sql"
)
_VALUE_OBJECTS_DIR: Final[Path] = _REPO_ROOT / "src" / "domain" / "value_objects"

TENANT: Final[TenantId] = new_tenant_id()
NOW: Final[datetime] = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)

#: Köçürmədən ƏVVƏL koda yazılmış ədədlər — ƏL İLƏ, mənbədən asılı olmadan.
#: Dəyər burada dəyişdirilirsə, bu, davranış dəyişikliyidir və AYRICA qərar
#: tələb edir (köçürmənin özü onu dəyişdirə bilməz).
_HISTORICAL: Final[dict[SystemLimitKey, str]] = {
    SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT: "100",
    SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS: "72",
    SystemLimitKey.SALES_POINTS_RESET_NOTICE_DAYS: "14",
    SystemLimitKey.LICENSE_CHECK_IN_INTERVAL_SECONDS: "86400",
    SystemLimitKey.LICENSE_RETRY_INTERVAL_SECONDS: "3600",
    SystemLimitKey.LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS: "900",
    SystemLimitKey.LICENSE_MIN_OFFLINE_GRACE_DAYS: "7",
    SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS: "14",
    SystemLimitKey.LICENSE_DEFAULT_OFFLINE_GRACE_DAYS: "14",
    SystemLimitKey.LICENSE_EXTENSION_DAYS: "30",
    SystemLimitKey.LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS: "300",
    SystemLimitKey.LICENSE_EXPIRY_WARNING_DAYS: "7",
    SystemLimitKey.UPDATE_CHECK_INTERVAL_SECONDS: "86400",
    SystemLimitKey.UPDATE_RETRY_INTERVAL_SECONDS: "7200",
    SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES: "536870912",
    SystemLimitKey.ERP_SYNC_PAGE_SIZE: "500",
    SystemLimitKey.ERP_NAME_MATCH_THRESHOLD: "0.87",
    SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES: "720",
    SystemLimitKey.DB_MIGRATION_DRAIN_TIMEOUT_SECONDS: "300",
    SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES: "120",
    SystemLimitKey.EVIDENCE_THUMBNAIL_MAX_EDGE_PX: "320",
    SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX: "1600",
}

#: Domen sabiti → gözlənilən dəyər. Sabitin ADI DƏYİŞMƏYİB (infrastruktur qatı
#: onları idxal edir), yalnız MƏNBƏYİ dəyişib — indi `DEFAULT_LIMITS`-dən gəlir.
_CONSTANTS: Final[tuple[tuple[str, object, object], ...]] = (
    (
        "licensing.DEFAULT_CHECK_IN_INTERVAL_SECONDS",
        licensing.DEFAULT_CHECK_IN_INTERVAL_SECONDS,
        86_400.0,
    ),
    ("licensing.RETRY_INTERVAL_SECONDS", licensing.RETRY_INTERVAL_SECONDS, 3_600.0),
    (
        "licensing.BLOCKED_RECHECK_INTERVAL_SECONDS",
        licensing.BLOCKED_RECHECK_INTERVAL_SECONDS,
        900.0,
    ),
    ("licensing.MIN_OFFLINE_GRACE_DAYS", licensing.MIN_OFFLINE_GRACE_DAYS, 7),
    ("licensing.MAX_OFFLINE_GRACE_DAYS", licensing.MAX_OFFLINE_GRACE_DAYS, 14),
    ("licensing.DEFAULT_OFFLINE_GRACE_DAYS", licensing.DEFAULT_OFFLINE_GRACE_DAYS, 14),
    ("licensing.EXTENSION_DAYS", licensing.EXTENSION_DAYS, 30),
    (
        "licensing.CLOCK_ROLLBACK_TOLERANCE_SECONDS",
        licensing.CLOCK_ROLLBACK_TOLERANCE_SECONDS,
        300.0,
    ),
    ("licensing.EXPIRY_WARNING_DAYS", licensing.EXPIRY_WARNING_DAYS, 7),
    ("erp.DEFAULT_PAGE_SIZE", erp.DEFAULT_PAGE_SIZE, 500),
    ("erp.NAME_MATCH_THRESHOLD", erp.NAME_MATCH_THRESHOLD, 0.87),
    ("catalogs.MAX_LEAVE_DURATION_MINUTES", catalogs.MAX_LEAVE_DURATION_MINUTES, 720),
    ("storage.THUMBNAIL_MAX_EDGE", storage.THUMBNAIL_MAX_EDGE, 320),
    ("storage.FULL_MAX_EDGE", storage.FULL_MAX_EDGE, 1_600),
    (
        "infrastructure.DEFAULT_DRAIN_TIMEOUT_SECONDS",
        infrastructure.DEFAULT_DRAIN_TIMEOUT_SECONDS,
        300,
    ),
    ("infrastructure.MAX_WINDOW_MINUTES", infrastructure.MAX_WINDOW_MINUTES, 120),
    (
        "gamification.POINTS_DISPUTE_WINDOW_HOURS",
        gamification.POINTS_DISPUTE_WINDOW_HOURS,
        72,
    ),
    (
        "gamification.DEFAULT_CURRENCY_PER_POINT",
        gamification.DEFAULT_CURRENCY_PER_POINT,
        Decimal("100"),
    ),
    (
        "gamification.DEFAULT_RESET_NOTICE_DAYS",
        gamification.DEFAULT_RESET_NOTICE_DAYS,
        14,
    ),
)


def _limit_int(limits: FakeSystemLimits, key: SystemLimitKey) -> int:
    """İstehlakçı naxışı (`application/use_cases/*._limit_int` ilə eyni)."""
    return limits.get_int(TENANT, key.value, int(DEFAULT_LIMITS[key]))


def _executable_sql() -> str:
    """Miqrasiyanın YALNIZ icra olunan hissəsi (DOWN bloku şərhdədir)."""
    lines = _MIGRATION.read_text(encoding="utf-8").splitlines()
    body = "\n".join(line for line in lines if not line.lstrip().startswith("--"))
    return re.sub(r"\s+", " ", body)


def _seeded_rows(*, for_new_tenant: bool) -> dict[str, tuple[str, str, str, str]]:
    """Miqrasiyadakı sətirlər: açar → (dəyər, tip, min, maks)."""
    prefix = r"\(NEW\.tenant_id, " if for_new_tenant else r"\("
    pattern = re.compile(
        prefix + r"'([A-Z_]+)', '([^']*)', '([A-Z]+)', '([^']*)', '([^']*)',",
    )
    return {
        match.group(1): (match.group(2), match.group(3), match.group(4), match.group(5))
        for match in pattern.finditer(_executable_sql())
    }


# --------------------------------------------------------------------------- #
# 1. Defolt köhnə hardcode ilə eynidir
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("key", "expected"), sorted(_HISTORICAL.items(), key=lambda kv: kv[0].value)
)
def test_default_matches_the_value_that_was_hardcoded(key: SystemLimitKey, expected: str) -> None:
    """Köçürmə idarəolunmanı dəyişir, DAVRANIŞI yox."""
    assert DEFAULT_LIMITS[key] == expected, (
        f"{key.value} defoltu köçürmə zamanı dəyişib — bu, sükutlu davranış "
        "dəyişikliyidir və ayrıca qərar tələb edir."
    )


@pytest.mark.parametrize(
    ("name", "actual", "expected"), _CONSTANTS, ids=[row[0] for row in _CONSTANTS]
)
def test_domain_constant_keeps_its_pre_migration_value(
    name: str, actual: object, expected: object
) -> None:
    """Value object sabitləri artıq `DEFAULT_LIMITS`-dən gəlir, dəyəri isə eynidir."""
    assert actual == expected, f"{name} köçürmədən sonra dəyişib"


def test_value_object_modules_no_longer_carry_the_numbers_themselves() -> None:
    """Sabitlər ədədi ÖZLƏRİNDƏ saxlamır — `DEFAULT_LIMITS`-dən oxuyur.

    Mənbə mətnini oxuyuruq, çünki dəyər bərabərliyi tək başına kifayət deyil:
    faylda yenidən `= 72` yazılsaydı, dəyər yenə düz olardı, lakin Root
    dəyişikliyi heç vaxt görünməzdi (köçürmədən əvvəlki vəziyyətin özü).
    """
    expectations = {
        "gamification.py": (
            "SALES_POINTS_CURRENCY_PER_POINT",
            "SALES_POINTS_DISPUTE_WINDOW_HOURS",
            "SALES_POINTS_RESET_NOTICE_DAYS",
        ),
        "licensing.py": ("LICENSE_CHECK_IN_INTERVAL_SECONDS", "LICENSE_EXTENSION_DAYS"),
        "updates.py": ("UPDATE_CHECK_INTERVAL_SECONDS", "UPDATE_MAX_PACKAGE_BYTES"),
        "erp.py": ("ERP_SYNC_PAGE_SIZE", "ERP_NAME_MATCH_THRESHOLD"),
        "catalogs.py": ("LEAVE_TYPE_MAX_DURATION_MINUTES",),
        "storage.py": ("EVIDENCE_THUMBNAIL_MAX_EDGE_PX", "EVIDENCE_FULL_MAX_EDGE_PX"),
        "infrastructure.py": (
            "DB_MIGRATION_DRAIN_TIMEOUT_SECONDS",
            "DB_MIGRATION_MAX_WINDOW_MINUTES",
        ),
    }
    for filename, keys in expectations.items():
        source = (_VALUE_OBJECTS_DIR / filename).read_text(encoding="utf-8")
        for key in keys:
            assert f"DEFAULT_LIMITS[SystemLimitKey.{key}]" in source, (
                f"{filename}: `{key}` dəyəri `DEFAULT_LIMITS`-dən oxunmur — "
                "sabit yenidən hardcode olub."
            )


def test_policies_stays_a_leaf_module() -> None:
    """`policies.py` runtime-da `value_objects`-dən HEÇ NƏ idxal etməməlidir.

    Bu, üslub qaydası deyil, DAİRƏVİ İDXAL qapısıdır: value object-lər indi
    `DEFAULT_LIMITS`-i oxuyur, yəni əks istiqamətli modul-səviyyəli idxal
    `import src.domain.policies` sətrini `ImportError` ilə çökdürər (paket
    `__init__` yarımçıq `policies`-dən defolt istəyər). Səhv yalnız idxal
    SIRASINDAN asılı olaraq üzə çıxdığı üçün əl ilə tapılması çətindir.
    """
    import ast

    tree = ast.parse((_REPO_ROOT / "src" / "domain" / "policies.py").read_text(encoding="utf-8"))
    runtime_imports = [
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src.domain")
    ]
    assert not runtime_imports, (
        "`policies.py` modul səviyyəsində domen modulu idxal edir "
        f"({runtime_imports}) — dairəvi idxal riski. `TYPE_CHECKING` və ya "
        "funksiya-daxili idxal işlədin (bax modulun başlığı)."
    )


def test_no_comment_references_a_nonexistent_limit_key() -> None:
    """Şərhdə adı çəkilən hər ROOT açarı HƏQİQƏTƏN mövcud olmalıdır.

    Köçürmədən əvvəlki qüsur məhz bu idi: `gamification.py` mövcud olmayan
    `POINTS_PER_CURRENCY_UNIT` açarına istinad edirdi və "idarə olunur"
    iddiası sənəddə qalıb kodda gerçəkləşmirdi.
    """
    known = {key.value for key in SystemLimitKey}
    # Sondakı lookahead prefiks-qeydini (`SystemLimitKey.LICENSE_*`) kənarda
    # saxlayır: o, bir açarın adı deyil, bir AİLƏNİN adıdır.
    referenced = re.compile(r"(?:system_limits|SystemLimitKey)\.([A-Z][A-Z0-9_]{3,})(?![A-Z0-9_*])")
    unknown: list[str] = []
    for path in sorted(_VALUE_OBJECTS_DIR.glob("*.py")):
        for match in referenced.finditer(path.read_text(encoding="utf-8")):
            if match.group(1) not in known:
                unknown.append(f"{path.name}: {match.group(1)}")
    assert not unknown, f"Mövcud olmayan limit açarına istinad edən şərh(lər): {unknown}"


# --------------------------------------------------------------------------- #
# 2. SQL seed — parametr ROOT ekranında GÖRÜNÜR
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(_HISTORICAL, key=lambda k: k.value))
def test_migration_seeds_the_key_with_the_same_default(key: SystemLimitKey) -> None:
    """Seed edilməyən açar mövcud kirayəçidə GUI-dan dəyişdirilə bilmir."""
    rows = _seeded_rows(for_new_tenant=False)
    assert key.value in rows, f"{key.value} migrations/033-də seed edilmir"
    value, _value_type, minimum, maximum = rows[key.value]
    assert value == DEFAULT_LIMITS[key], (
        f"{key.value}: SQL seed dəyəri `DEFAULT_LIMITS` ilə fərqlənir — "
        "eyni parametr iki fərqli defoltla yaşayardı."
    )
    assert minimum and maximum, f"{key.value} üçün `min_value`/`max_value` boşdur"


@pytest.mark.parametrize("key", sorted(_HISTORICAL, key=lambda k: k.value))
def test_new_tenant_trigger_seeds_the_same_row(key: SystemLimitKey) -> None:
    """Yeni kirayəçi köhnə kirayəçi ilə EYNİ parametr dəstini almalıdır."""
    existing = _seeded_rows(for_new_tenant=False)
    fresh = _seeded_rows(for_new_tenant=True)
    assert key.value in fresh, f"{key.value} yeni kirayəçi trigger-ində yoxdur"
    assert fresh[key.value] == existing[key.value], (
        f"{key.value}: trigger ilə INSERT sətri fərqlənir — parametr köhnə "
        "kirayəçidə görünüb yenidə itərdi."
    )


def test_clock_rollback_tolerance_has_a_hard_ceiling() -> None:
    """Saat manipulyasiyası qoruması Root-dan FAKTİKİ söndürülə bilməməlidir.

    Tolerantlıq nə qədər böyükdürsə, saatı geri çəkməklə bitmiş lisenziyanı
    süründürmək o qədər asandır. Ona görə tavan 15 dəqiqədə kilidlidir.
    """
    _value, _type, minimum, maximum = _seeded_rows(for_new_tenant=False)[
        SystemLimitKey.LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS.value
    ]
    assert int(maximum) <= 900, "Tolerantlıq tavanı böyüdülüb — qoruma zəifləyir"
    assert int(minimum) >= 30, "Çox kiçik tolerantlıq NTP düzəlişini manipulyasiya sayardı"


def test_offline_grace_band_cannot_be_widened_past_the_db_check() -> None:
    """`license_tenants.offline_grace_days` CHECK-i 7–14-dür; limit onu keçməməlidir."""
    rows = _seeded_rows(for_new_tenant=False)
    for key in (
        SystemLimitKey.LICENSE_MIN_OFFLINE_GRACE_DAYS,
        SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS,
        SystemLimitKey.LICENSE_DEFAULT_OFFLINE_GRACE_DAYS,
    ):
        assert int(rows[key.value][3]) <= 14, (
            f"{key.value} tavanı DB CHECK-indən böyükdür — parametr işləyən "
            "kimi görünüb yazma anında rədd edilərdi."
        )


def test_name_match_threshold_floor_protects_point_attribution() -> None:
    """0.70-dən aşağı hədd satış xalını SƏHV işçiyə yazardı."""
    minimum = _seeded_rows(for_new_tenant=False)[SystemLimitKey.ERP_NAME_MATCH_THRESHOLD.value][2]
    assert float(minimum) >= 0.70


# --------------------------------------------------------------------------- #
# 3. Root dəyəri dəyişdikdə kod yeni dəyəri oxuyur
# --------------------------------------------------------------------------- #


def test_points_conversion_follows_the_root_currency_rate() -> None:
    """Bal kursu ROOT-dan gəlir — köçürmənin əsas səbəbi məhz bu idi."""
    limits = FakeSystemLimits()
    default_rate = Decimal(
        limits.get_str(
            TENANT,
            SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT.value,
            DEFAULT_LIMITS[SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT],
        )
    )
    assert gamification.points_for_amount(Decimal("250"), currency_per_point=default_rate) == 2

    # Root kampaniya üçün kursu iki dəfə "ucuzlaşdırır": eyni satış İKİ qat xal.
    limits.set(SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT, "50")
    campaign_rate = Decimal(
        limits.get_str(
            TENANT,
            SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT.value,
            DEFAULT_LIMITS[SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT],
        )
    )
    assert gamification.points_for_amount(Decimal("250"), currency_per_point=campaign_rate) == 5


def _points_entry(*, dispute_window_hours: int) -> PointsEntry:
    return PointsEntry(
        entry_id=PointsEntryId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=StoreId(uuid.uuid4()),
        points=3,
        awarded_at=NOW,
        dispute_window_hours=dispute_window_hours,
    )


def test_points_dispute_window_follows_the_root_value() -> None:
    """Xal etiraz pəncərəsi öz açarına tabedir (cərimə açarına DEYİL)."""
    limits = FakeSystemLimits()
    entry = _points_entry(
        dispute_window_hours=_limit_int(limits, SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS)
    )
    assert entry.dispute_window_closes_at == NOW + timedelta(hours=72)

    limits.set(SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS, "120")
    widened = _points_entry(
        dispute_window_hours=_limit_int(limits, SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS)
    )
    assert widened.dispute_window_closes_at == NOW + timedelta(hours=120)


def test_points_dispute_window_is_independent_of_the_fine_window() -> None:
    """Cərimə pəncərəsinin dəyişməsi xal pəncərəsini SÜKUTLA dəyişməməlidir.

    Bu, köçürmənin qərarıdır: eyni DEFOLT, AYRI açar (səbəb `policies.py`
    şərhindədir — sayğaclar fərqli andan başlayır).
    """
    limits = FakeSystemLimits()
    limits.set(SystemLimitKey.FINE_APPEAL_WINDOW_HOURS, "240")
    assert _limit_int(limits, SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS) == 72
    assert (
        DEFAULT_LIMITS[SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS]
        == DEFAULT_LIMITS[SystemLimitKey.FINE_APPEAL_WINDOW_HOURS]
    ), "İki pəncərənin DEFOLTU bölmə 6-ya görə eyni olmalıdır (açarlar ayrı)"


def test_reset_notice_days_follows_the_root_value() -> None:
    """Sıfırlanma TARİXİ sabitdir, xəbərdarlığın qabaqcadanlığı isə parametrdir."""
    limits = FakeSystemLimits()
    period = gamification.PointsPeriod.containing(NOW.date())
    assert period.notice_on(
        notice_days=_limit_int(limits, SystemLimitKey.SALES_POINTS_RESET_NOTICE_DAYS)
    ) == period.end - timedelta(days=14)

    limits.set(SystemLimitKey.SALES_POINTS_RESET_NOTICE_DAYS, "30")
    assert period.notice_on(
        notice_days=_limit_int(limits, SystemLimitKey.SALES_POINTS_RESET_NOTICE_DAYS)
    ) == period.end - timedelta(days=30)
    # Sıfırlanma günü DƏYİŞMƏDİ — yalnız bildiriş tezləşdi.
    assert period.reset_on == period.end


def test_migration_plan_timeouts_follow_the_root_values() -> None:
    """Baza keçidinin iki taymautu da parametrdir."""
    limits = FakeSystemLimits()
    plan = MigrationPlan(
        source=DatabaseTarget.CLOUD,
        destination=DatabaseTarget.PRIVATE_SERVER,
        window_minutes=_limit_int(limits, SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES),
        drain_timeout_seconds=_limit_int(limits, SystemLimitKey.DB_MIGRATION_DRAIN_TIMEOUT_SECONDS),
    )
    assert (plan.window_minutes, plan.drain_timeout_seconds) == (120, 300)

    limits.set(SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES, "45")
    limits.set(SystemLimitKey.DB_MIGRATION_DRAIN_TIMEOUT_SECONDS, "600")
    tightened = MigrationPlan(
        source=DatabaseTarget.CLOUD,
        destination=DatabaseTarget.PRIVATE_SERVER,
        window_minutes=_limit_int(limits, SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES),
        drain_timeout_seconds=_limit_int(limits, SystemLimitKey.DB_MIGRATION_DRAIN_TIMEOUT_SECONDS),
    )
    assert (tightened.window_minutes, tightened.drain_timeout_seconds) == (45, 600)


def test_maintenance_window_accepts_a_shorter_root_value() -> None:
    """Root pəncərəni QISALDA bilər — 24 saat işləyən mağaza üçün vacibdir."""
    limits = FakeSystemLimits({SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES.value: "30"})
    window = MaintenanceWindow(
        opened_at=NOW,
        max_minutes=_limit_int(limits, SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES),
    )
    assert window.deadline == NOW + timedelta(minutes=30)
    assert window.is_expired(now=NOW + timedelta(minutes=31))


# --------------------------------------------------------------------------- #
# 6. Value object-lərin ÖZÜ parametr qəbul edir (Faza 10.2, üçüncü dalğa)
# --------------------------------------------------------------------------- #
#
# İKİNCİ DALĞANIN AÇIQ QALAN HALQASI: açar `DEFAULT_LIMITS`-də var idi və
# yuxarıdakı testlər defoltun doğruluğunu sübut edirdi — LAKİN `evaluate()`,
# `payment_warning()`, `extend_by_month()` və `LeaveType.__post_init__` modul
# sabitini BİRBAŞA oxuyurdu. Yəni Root dəyəri dəyişsə də HEÇ NƏ baş vermirdi.
#
# İcazə növünün tavanı üçün bu, xüsusilə çətin hal idi: yoxlama SƏRT tavan
# kimi işləyir, ona görə tətbiq qatında ikinci qapı əlavə etmək Root-un tavanı
# QALDIRMASINI bloklamağa davam edərdi (yalançı "işləyir" görüntüsü). Həll:
# VO-nun ÖZÜ parametr qəbul edir, oxunu isə çağıran tərəf edir.


def _license_limits(limits: FakeSystemLimits) -> licensing.LicenseLimits:
    """İstehlakçı naxışı — infrastruktur klientinin etdiyinin eynisi."""
    return licensing.LicenseLimits(
        min_offline_grace_days=_limit_int(limits, SystemLimitKey.LICENSE_MIN_OFFLINE_GRACE_DAYS),
        max_offline_grace_days=_limit_int(limits, SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS),
        default_offline_grace_days=_limit_int(
            limits, SystemLimitKey.LICENSE_DEFAULT_OFFLINE_GRACE_DAYS
        ),
        expiry_warning_days=_limit_int(limits, SystemLimitKey.LICENSE_EXPIRY_WARNING_DAYS),
        extension_days=_limit_int(limits, SystemLimitKey.LICENSE_EXTENSION_DAYS),
    )


def _snapshot(
    *, checked_at: datetime, expires_at: datetime | None = None
) -> licensing.LicenseSnapshot:
    return licensing.LicenseSnapshot(
        status=licensing.LicenseStatus.AKTIV,
        checked_at=checked_at,
        expires_at=expires_at,
        vendor_contact="destek@kompas.az",
    )


def test_license_limits_defaults_equal_the_module_fallbacks() -> None:
    """Parametr obyektinin defoltu köhnə sabitlərlə EYNİDİR — davranış dəyişmir."""
    window = licensing.LicenseLimits.defaults()

    assert window.min_offline_grace_days == licensing.MIN_OFFLINE_GRACE_DAYS
    assert window.max_offline_grace_days == licensing.MAX_OFFLINE_GRACE_DAYS
    assert window.default_offline_grace_days == licensing.DEFAULT_OFFLINE_GRACE_DAYS
    assert window.expiry_warning_days == licensing.EXPIRY_WARNING_DAYS
    assert window.extension_days == licensing.EXTENSION_DAYS


def test_offline_grace_evaluation_follows_the_root_band() -> None:
    """Root bandı daraldıqda qrace ERKƏN bitir — `evaluate()` yeni dəyəri oxuyur."""
    checked = NOW - timedelta(days=10)
    snapshot = _snapshot(checked_at=checked)

    # Defolt band (7–14): 10 günlük fasilə hələ qrace daxilindədir.
    relaxed = licensing.evaluate(snapshot, now=NOW)
    assert not relaxed.has(licensing.RestrictionKind.LICENSE_UNVERIFIED)

    # Root tavanı 7 günə endirir — eyni fasilə artıq xəbərdarlıq doğurur.
    narrow = FakeSystemLimits({SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS.value: "7"})
    strict = licensing.evaluate(snapshot, now=NOW, limits=_license_limits(narrow))
    assert strict.has(licensing.RestrictionKind.LICENSE_UNVERIFIED)


def test_never_checked_in_grace_follows_the_root_default() -> None:
    """Heç vaxt oxunuş olmayıbsa qrace `DEFAULT_OFFLINE_GRACE_DAYS`-dən gəlir."""
    first_run = NOW - timedelta(days=9)

    assert licensing.evaluate(None, now=NOW, first_run_at=first_run).offline_grace_days_left == 5

    narrowed = FakeSystemLimits(
        {
            SystemLimitKey.LICENSE_DEFAULT_OFFLINE_GRACE_DAYS.value: "8",
            SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS.value: "8",
        }
    )
    state = licensing.evaluate(
        None, now=NOW, first_run_at=first_run, limits=_license_limits(narrowed)
    )
    assert state.offline_grace_days_left == 0
    assert state.has(licensing.RestrictionKind.LICENSE_UNVERIFIED)


def test_payment_warning_window_follows_the_root_value() -> None:
    """Defolt 7 gün susur; Root 30 gün seçəndə eyni lisenziya XƏBƏRDARLIQ verir."""
    snapshot = _snapshot(checked_at=NOW, expires_at=NOW + timedelta(days=20))

    assert licensing.payment_warning(snapshot, now=NOW) == ""

    wide = FakeSystemLimits({SystemLimitKey.LICENSE_EXPIRY_WARNING_DAYS.value: "30"})
    message = licensing.payment_warning(snapshot, now=NOW, limits=_license_limits(wide))
    assert "20 gün" in message


def test_extension_days_follow_the_root_value() -> None:
    """«[1 Ay Uzat]» addımı Root-dandır — defolt 30 gün DƏYİŞMİR."""
    assert licensing.extend_by_month(None, now=NOW) == NOW + timedelta(days=30)

    quarterly = FakeSystemLimits({SystemLimitKey.LICENSE_EXTENSION_DAYS.value: "90"})
    extended = licensing.extend_by_month(None, now=NOW, limits=_license_limits(quarterly))
    assert extended == NOW + timedelta(days=90)


def test_license_limits_normalize_an_unusable_root_value() -> None:
    """Tərs/sıfır band bütün quraşdırmalara banner asardı — normallaşdırılır."""
    broken = licensing.LicenseLimits(
        min_offline_grace_days=0,
        max_offline_grace_days=-5,
        default_offline_grace_days=99,
        expiry_warning_days=-3,
        extension_days=0,
    )

    assert broken.min_offline_grace_days == 1
    assert broken.max_offline_grace_days == 1
    assert broken.default_offline_grace_days == 1
    assert broken.expiry_warning_days == 0
    assert broken.extension_days == 1


def test_leave_type_ceiling_defaults_to_the_module_fallback() -> None:
    """Tavan verilmədikdə davranış köçürmədən ƏVVƏLKİ ilə eynidir."""
    catalogs.LeaveType(
        name="Uzun növbə",
        tenant_id=TENANT,
        default_duration_minutes=catalogs.MAX_LEAVE_DURATION_MINUTES,
    )
    with pytest.raises(catalogs.InvalidCatalogEntryError):
        catalogs.LeaveType(
            name="Həddi aşan",
            tenant_id=TENANT,
            default_duration_minutes=catalogs.MAX_LEAVE_DURATION_MINUTES + 1,
        )


def test_leave_type_ceiling_can_be_raised_by_root() -> None:
    """ƏSAS QAPI: Root tavanı QALDIRA bilir — VO parametri onu qəbul edir."""
    limits = FakeSystemLimits({SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES.value: "1440"})
    ceiling = _limit_int(limits, SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES)

    entry = catalogs.LeaveType(
        name="24 saatlıq növbə",
        tenant_id=TENANT,
        default_duration_minutes=1000,
        max_duration_minutes=ceiling,
    )
    assert entry.default_duration_minutes == 1000


def test_leave_type_ceiling_can_be_lowered_by_root() -> None:
    """Root tavanı ENDİRƏ də bilir — eyni dəyər artıq rədd olunur."""
    limits = FakeSystemLimits({SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES.value: "60"})
    ceiling = _limit_int(limits, SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES)

    with pytest.raises(catalogs.InvalidCatalogEntryError, match="60"):
        catalogs.LeaveType(
            name="Nahar",
            tenant_id=TENANT,
            default_duration_minutes=90,
            max_duration_minutes=ceiling,
        )


def test_leave_type_ceiling_is_not_a_field() -> None:
    """Tavan `InitVar`-dır: bərabərlik və audit `after_state` ondan asılı DEYİL.

    Sahə olsaydı, Root tavanı dəyişdikdən sonra EYNİ kataloq sətri "fərqli"
    görünərdi və hər müqayisə/serializasiya səhv nəticə verərdi.
    """
    relaxed = catalogs.LeaveType(
        name="Nahar", tenant_id=TENANT, default_duration_minutes=45, max_duration_minutes=1440
    )
    strict = catalogs.LeaveType(
        name="Nahar", tenant_id=TENANT, default_duration_minutes=45, max_duration_minutes=120
    )

    assert relaxed == strict
    assert "max_duration_minutes" not in {field.name for field in fields(relaxed)}
    assert "max_duration_minutes" not in repr(relaxed)


def test_leave_type_ignores_an_unusable_ceiling() -> None:
    """`0` tavan BÜTÜN icazə növlərini rədd edərdi — fallback qoruyur."""
    entry = catalogs.LeaveType(
        name="Nahar", tenant_id=TENANT, default_duration_minutes=45, max_duration_minutes=0
    )
    assert entry.default_duration_minutes == 45
