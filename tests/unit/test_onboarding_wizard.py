"""ONBOARD-FINAL sihirbazının zəmanətləri (Faza 1 + Faza 2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR — HANSI QÜSUR SÜKUTLA QAYIDA BİLƏR
──────────────────────────────────────────────────────────────────────────────
Sihirbazın verdiyi zəmanətlərin hamısı «kodu oxu, gör ki, belədir» tipindədir
və məhz ona görə kövrəkdir. Hər biri BİR sətir dəyişikliklə sükutla itə bilər:

* DSN qurucusu parolu URL-kodlamağı dayandırsa, `@` işarəsi olan parol DSN-i
  BAŞQA hosta yönləndirər və xəta «parol səhvdir» yox, «host tapılmadı» olar;
* maskalama düşsə, parol miqrasiya çıxışı ilə ekrana (və skrinşota) düşər;
* dublikat qapısı bir budağı buraxsa, YETİM kirayəçi yaranar — o, heç bir
  ekranda görünmür və yalnız ödəniş hesabatında üzə çıxır;
* «səhv paroldan sonra YALNIZ parol soruşulur» davranışı itsə, sihirbaz öz
  məqsədinə (sürtünməni azaltmaq) zidd işləyər.

Testlər ŞƏBƏKƏYƏ ÇIXMIR: `probe` əvəzlənir. Yoxlanan şey bağlantı deyil,
sihirbazın MƏNTİQİDİR.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from scripts import onboard_new_tenant as onboard
from scripts import onboard_wizard as wizard

# --------------------------------------------------------------------------- #
# DSN qurulması — regionsuz BİRBAŞA format
# --------------------------------------------------------------------------- #


def test_direct_dsn_needs_only_ref_and_password() -> None:
    """Host TAMAMİLƏ ref-dən qurulur — REGİON tələb olunmur (🔴 düzəlişi)."""
    dsn = wizard.build_direct_dsn("abcdefghijklmnopqrst", "sade")

    assert dsn == (
        "postgresql://postgres:sade@db.abcdefghijklmnopqrst.supabase.co:5432/postgres"
        "?sslmode=require"
    )
    assert "pooler" not in dsn
    assert "aws-0" not in dsn


def test_direct_dsn_url_encodes_password() -> None:
    """Parolda `@`/`/`/`#` normaldır; kodlanmasa DSN BAŞQA hosta işarə edərdi."""
    dsn = wizard.build_direct_dsn("abcdefghijklmnopqrst", "p@ss/w#rd?1")

    assert "p%40ss%2Fw%23rd%3F1" in dsn
    # Host hissəsi POZULMAMALIDIR — qüsurun ölçülən nəticəsi məhz bu idi.
    assert "@db.abcdefghijklmnopqrst.supabase.co:5432" in dsn


def test_dsn_survives_round_trip_through_connection_settings() -> None:
    """`--dev` yolu DSN-i `ConnectionSettings`-ə çevirir — parol İKİQAT kodlanmır."""
    from src.infrastructure.config.connection_file import ConnectionSettings

    settings = ConnectionSettings.from_dsn(wizard.build_direct_dsn("a" * 20, "p@ss/w#rd?1"))

    assert settings.password == "p@ss/w#rd?1"
    assert settings.host == f"db.{'a' * 20}.supabase.co"


@pytest.mark.parametrize(
    "pasted",
    [
        "abcdefghijklmnopqrst",
        "  ABCDEFGHIJKLMNOPQRST  ",
        "https://abcdefghijklmnopqrst.supabase.co",
        "db.abcdefghijklmnopqrst.supabase.co",
        "https://supabase.com/dashboard/project/abcdefghijklmnopqrst",
        "https://supabase.com/dashboard/project/abcdefghijklmnopqrst/settings/database",
    ],
)
def test_project_ref_accepts_every_shape_the_operator_can_paste(pasted: str) -> None:
    """«Yalnız ortadakı hissəni yaz» göstərişi sihirbazın məqsədinə ziddir."""
    assert wizard.normalise_project_ref(pasted) == "abcdefghijklmnopqrst"


# --------------------------------------------------------------------------- #
# Xəta təsnifatı — insan-oxunaqlı, stack-trace YOX
# --------------------------------------------------------------------------- #


class _FakeError(Exception):
    """`psycopg` xətasının imzasını təqlid edir (`sqlstate` atributu)."""

    def __init__(self, message: str, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("message", "sqlstate", "expected_kind"),
    [
        ("password authentication failed for user", "28P01", wizard.PROBE_CREDENTIAL),
        ('could not translate host name "db.x.supabase.co"', None, "host"),
        ("connection timeout expired", None, "timeout"),
        ("Network is unreachable", None, "network"),
        ("something else entirely", None, "other"),
    ],
)
def test_failures_are_classified_not_just_printed(
    message: str, sqlstate: str | None, expected_kind: str
) -> None:
    """`kind` sihirbazın HANSI sualı təkrarlayacağını həll edir — bax `_ask_project`."""
    failure = wizard._humanise(_FakeError(message, sqlstate))

    assert failure.kind == expected_kind
    assert "Traceback" not in failure.message
    assert failure.message.startswith("❌")


def test_wrong_password_does_not_re_ask_the_project_ref() -> None:
    """ÖLÇÜLMÜŞ SÜRTÜNMƏ: ref DÜZGÜNDÜR (server ona görə cavab verdi) — təkrarlanmır."""
    asked: list[str] = []
    passwords = iter(["sehv-parol", "duzgun-parol"])

    def fake_ask(label: str, **kwargs: Any) -> str:
        asked.append(label)
        if kwargs.get("secret"):
            return next(passwords)
        return "abcdefghijklmnopqrst"

    def fake_probe(dsn: str) -> wizard.ProbeFailure | None:
        if "sehv-parol" in dsn:
            return wizard._humanise(_FakeError("password authentication failed", "28P01"))
        return None

    original_ask, original_probe = wizard.ask, wizard.probe
    wizard.ask, wizard.probe = fake_ask, fake_probe
    try:
        result = wizard._ask_project(ref_label="Ref", credential_label="Parol")
    finally:
        wizard.ask, wizard.probe = original_ask, original_probe

    assert result.password == "duzgun-parol"
    assert asked.count("Ref") == 1, "ref YALNIZ BİR DƏFƏ soruşulmalıdır"
    assert asked.count("Parol") == 2


def test_host_failure_does_re_ask_the_project_ref() -> None:
    """Ünvan xətasında ref YENİDƏN soruşulur — parol xətasından FƏRQLİ davranış."""
    asked: list[str] = []
    refs = iter(["a" * 20, "b" * 20])

    def fake_ask(label: str, **kwargs: Any) -> str:
        asked.append(label)
        return "parol" if kwargs.get("secret") else next(refs)

    def fake_probe(dsn: str) -> wizard.ProbeFailure | None:
        if "a" * 20 in dsn:
            return wizard._humanise(_FakeError("could not translate host name"))
        return None

    original_ask, original_probe = wizard.ask, wizard.probe
    wizard.ask, wizard.probe = fake_ask, fake_probe
    try:
        result = wizard._ask_project(ref_label="Ref", credential_label="Parol")
    finally:
        wizard.ask, wizard.probe = original_ask, original_probe

    assert result.project_ref == "b" * 20
    assert asked.count("Ref") == 2


# --------------------------------------------------------------------------- #
# Vendor yaddaşı — şifrəli, plaintext SIZMIR
# --------------------------------------------------------------------------- #


def test_vendor_memory_round_trips_without_storing_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.onboard_config` parolu ŞİFRƏLİ saxlayır — fayla baxan onu OXUYA BİLMİR."""
    memory = tmp_path / ".onboard_config"
    monkeypatch.setattr(wizard, "VENDOR_MEMORY_FILE", memory)
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", "ZmFrZS1rZXktZm9yLXRlc3RzLTMyLWJ5dGVzLXh4eHg=")

    assert wizard.load_vendor() is None

    wizard.save_vendor(wizard.VendorCredentials("b" * 20, "gizli-parol"))
    raw = memory.read_text(encoding="utf-8")

    assert "gizli-parol" not in raw
    restored = wizard.load_vendor()
    assert restored is not None
    assert restored.password == "gizli-parol"


def test_corrupted_vendor_memory_is_treated_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Açılmayan yaddaş DAYANDIRMIR — sual yenidən verilir (bax `load_vendor`)."""
    memory = tmp_path / ".onboard_config"
    memory.write_text("korlanmis-token\n", encoding="utf-8")
    monkeypatch.setattr(wizard, "VENDOR_MEMORY_FILE", memory)

    assert wizard.load_vendor() is None


# --------------------------------------------------------------------------- #
# Faza 2 — parol maskalanması
# --------------------------------------------------------------------------- #


def test_dsn_password_is_masked_but_username_is_kept() -> None:
    """Diaqnostikanın yarısı «hansı rol ilə qoşulur» sualıdır — ad QALIR."""
    masked = onboard._redact_dsn(
        "qosuldu: postgresql://kompasos_app:sirr123@db.aaaa.supabase.co:5432/postgres"
    )

    assert "sirr123" not in masked
    assert "kompasos_app:***@" in masked


def test_redaction_does_not_mangle_ordinary_lines() -> None:
    """Naxış DAR saxlanılır — normal sətirlərdəki iki nöqtə korlanmır."""
    line = "[3/6] Kirayəçi sətri: OK — 12:30"

    assert onboard._redact_dsn(line) == line


# --------------------------------------------------------------------------- #
# Faza 2 — açıq sirr qorumasi
# --------------------------------------------------------------------------- #


def _secret_args(out: Path) -> argparse.Namespace:
    return argparse.Namespace(
        out=str(out),
        dev=False,
        company="Sirr Testi",
        tenant_dsn="postgresql://postgres:t%40jenPW@db.aaaa.supabase.co:5432/postgres",
        vendor_dsn="postgresql://vendoruser:vendPW123@db.bbbb.supabase.co:5432/postgres",
    )


def test_clean_config_passes_the_secret_scan(tmp_path: Path) -> None:
    (tmp_path / "connection.template.json").write_text(
        json.dumps({"host": "db.aaaa.supabase.co", "password_encrypted": ""}), encoding="utf-8"
    )

    onboard._assert_no_plaintext_secrets(_secret_args(tmp_path))


@pytest.mark.parametrize("leaked", ["t@jenPW", "vendPW123"])
def test_plaintext_password_in_any_written_file_stops_the_install(
    tmp_path: Path, leaked: str
) -> None:
    """İDDİA ZƏMANƏTƏ çevrilir: fayllar GERİ OXUNUR, parol axtarılır."""
    (tmp_path / "connection.template.json").write_text(
        json.dumps({"password": leaked}), encoding="utf-8"
    )

    with pytest.raises(onboard.OnboardingError, match="AÇIQ PAROL"):
        onboard._assert_no_plaintext_secrets(_secret_args(tmp_path))


def test_license_key_is_deliberately_not_scanned(tmp_path: Path) -> None:
    """`OXU-MƏNİ.txt` açarı BİLƏRƏKDƏN daşıyır — faylın mövcudluq səbəbi budur."""
    (tmp_path / "OXU-MƏNİ.txt").write_text("license_key : b8G0Kdij-abc\n", encoding="utf-8")

    onboard._assert_no_plaintext_secrets(_secret_args(tmp_path))


# --------------------------------------------------------------------------- #
# Faza 2 — idempotentlik (dublikat qapısı)
# --------------------------------------------------------------------------- #


def _duplicate_args(**overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "company": "Yataş",
        "supabase_ref": "a" * 20,
        "tenant_id": "",
        "license_key": "",
        "allow_duplicate": False,
        "tenant_dsn": "tenant",
        "vendor_dsn": "vendor",
        "dry_run": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


_EXISTING = [
    onboard.ExistingTenant(
        tenant_id="11111111-1111-1111-1111-111111111111",
        company_name="Yataş",
        license_key="KOHNE-ACAR",
        status="AKTIV",
        supabase_ref="a" * 20,
    )
]


@pytest.fixture
def _found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboard, "_detect_existing_tenant", lambda args: list(_EXISTING))


def test_every_decision_has_an_exit_code() -> None:
    """Naməlum qərar `dict.get`-də `None` verər — yəni sükutla YAZIYA keçərdi."""
    decisions = {
        onboard._DUPLICATE_CONTINUE,
        onboard._DUPLICATE_NEW,
        onboard._DUPLICATE_ABORT,
        onboard._DUPLICATE_BLOCKED,
        onboard._DUPLICATE_CANCELLED,
    }

    assert decisions == set(onboard._DUPLICATE_EXITS)


@pytest.mark.usefixtures("_found")
def test_duplicate_blocks_when_no_one_can_be_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI/boru mühitində sükutla YENİ kirayəçi yaratmaq ƏN PİS seçimdir."""
    monkeypatch.setattr(wizard, "is_interactive", lambda: False)
    args = _duplicate_args()

    assert onboard._apply_duplicate_policy(args) == onboard.DUPLICATE_EXIT_CODE
    assert args.tenant_id == ""


@pytest.mark.usefixtures("_found")
def test_allow_duplicate_flag_opens_the_gate_without_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wizard, "is_interactive", lambda: False)
    args = _duplicate_args(allow_duplicate=True)

    assert onboard._apply_duplicate_policy(args) is None
    assert args.tenant_id == "", "YENİ kirayəçi — köhnə kimlik GÖTÜRÜLMÜR"


@pytest.mark.usefixtures("_found")
def test_continue_reuses_the_existing_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Davam» qərarı MÖVCUD D4 bərpa mexanizminə çevrilir — ikinci rejim YOX."""
    monkeypatch.setattr(wizard, "is_interactive", lambda: True)
    monkeypatch.setattr(wizard, "choose", lambda *_: onboard._DUPLICATE_CONTINUE)
    args = _duplicate_args()

    assert onboard._apply_duplicate_policy(args) is None
    assert args.tenant_id == "11111111-1111-1111-1111-111111111111"
    assert args.license_key == "KOHNE-ACAR"


@pytest.mark.usefixtures("_found")
def test_abort_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wizard, "is_interactive", lambda: True)
    monkeypatch.setattr(wizard, "choose", lambda *_: onboard._DUPLICATE_ABORT)
    args = _duplicate_args()

    assert onboard._apply_duplicate_policy(args) == 0
    assert args.tenant_id == ""


def test_explicit_resume_never_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--tenant-id` verilibsə qərar ARTIQ verilib — dublikat GÖZLƏNİLƏNDİR."""

    def _explode(args: argparse.Namespace) -> list[onboard.ExistingTenant]:
        raise AssertionError("dublikat yoxlaması bu yolda işləməməlidir")

    monkeypatch.setattr(onboard, "_detect_existing_tenant", _explode)

    assert onboard._apply_duplicate_policy(_duplicate_args(tenant_id="x", license_key="y")) is None


# --------------------------------------------------------------------------- #
# Faza 2 — atomiklik əvəzi: yarımçıq hal hesabatı
# --------------------------------------------------------------------------- #


def test_partial_report_marks_each_step_with_one_of_three_states() -> None:
    """Operator altı yerin hansının toxunulduğunu TƏXMİN ETMƏMƏLİDİR."""
    report = onboard._partial_state_report(
        2, argparse.Namespace(out="./onboarding/test"), uuid.UUID(int=7)
    )

    assert "[OK      ] 1." in report
    assert "[OK      ] 2." in report
    assert "[UĞURSUZ ] 3." in report
    assert "[EDİLMƏDİ] 4." in report
    assert "GERİ QAYTARILMADI" in report
    # Uğursuz və edilməmiş addımların HƏR BİRİ üçün yoxlama üsulu yazılır.
    assert report.count("yoxlama:") == onboard.TOTAL_STEPS - 2


def test_partial_report_covers_every_step() -> None:
    """Addım adları `_run_steps`-dəkilərlə eyni sayda olmalıdır."""
    assert len(onboard._STEP_TITLES) == onboard.TOTAL_STEPS
    assert len(onboard._STEP_CHECKS) == onboard.TOTAL_STEPS


# --------------------------------------------------------------------------- #
# Faza 2 — lisenziya açarı
# --------------------------------------------------------------------------- #


def test_license_key_is_cryptographically_random() -> None:
    """`secrets` modulu — `random` DEYİL (proqnozlaşdırıla bilən olardı)."""
    import inspect

    source = inspect.getsource(onboard)

    assert "secrets.token_urlsafe(LICENSE_KEY_BYTES)" in source
    assert "import secrets" in source
    assert onboard.LICENSE_KEY_BYTES >= 32


# --------------------------------------------------------------------------- #
# Faza 4 — `--verify <ad>`
# --------------------------------------------------------------------------- #


def _archive_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, with_password: bool
) -> str:
    """`configs/` arxivini QURUR və slug qaytarır — blok ƏSL yazıcı ilə hazırlanır.

    `connection` bloku əl ilə yığılmır: `save_settings()` çağırılır və nəticə
    geri oxunur. Əl ilə yığsaydıq, format dəyişən gün test YAŞIL qalar, real
    arxiv isə oxunmaz olardı — yəni test qorumaq üçün var olduğu şeyi
    qorumazdı.
    """
    from scripts import switch

    from src.infrastructure.config.connection_file import ConnectionSettings, save_settings

    monkeypatch.setenv("KOMPASOS_FERNET_KEY", "ZmFrZS1rZXktZm9yLXRlc3RzLTMyLWJ5dGVzLXh4eHg=")
    monkeypatch.setattr(switch, "CONFIGS_DIR", tmp_path)

    scratch = tmp_path / "connection.json"
    save_settings(
        ConnectionSettings(
            host="db.cccccccccccccccccccc.supabase.co",
            port=5432,
            database="postgres",
            username="postgres",
            password="gizli@parol" if with_password else "",
        ),
        scratch,
    )
    payload = json.loads(scratch.read_text(encoding="utf-8"))
    scratch.unlink()

    switch.archive_config(
        company="Test Şirkət",
        installation={"tenant_id": "33333333-3333-3333-3333-333333333333", "is_licensed": True},
        connection=payload,
    )
    return "test-sirket"


def _verify_args(name: str) -> argparse.Namespace:
    return argparse.Namespace(verify=name, tenant_dsn="", vendor_dsn="", dev=False)


def test_verify_by_name_builds_both_dsns_from_local_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dəstək zəngində operatorun əlində olan YEGANƏ şey müştərinin ADIdır."""
    slug = _archive_fixture(tmp_path, monkeypatch, with_password=True)
    monkeypatch.setattr(
        wizard, "load_vendor", lambda: wizard.VendorCredentials("b" * 20, "vendorPW")
    )
    args = _verify_args(slug)

    resolved = onboard._resolve_verify_by_name(args)

    assert str(resolved) == "33333333-3333-3333-3333-333333333333"
    # Parol arxivdən DEŞİFRƏLƏNİB — müvəqqəti fayl YARANMADAN.
    assert "gizli%40parol" in args.tenant_dsn
    assert "db.bbbbbbbbbbbbbbbbbbbb.supabase.co" in args.vendor_dsn


def test_verify_by_name_marks_dev_only_for_the_active_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--dev` halqası aktiv OLMAYAN kirayəçidə yalançı-qırmızı verərdi."""
    from scripts import switch

    slug = _archive_fixture(tmp_path, monkeypatch, with_password=True)
    monkeypatch.setattr(
        wizard, "load_vendor", lambda: wizard.VendorCredentials("b" * 20, "vendorPW")
    )

    inactive = _verify_args(slug)
    onboard._resolve_verify_by_name(inactive)
    assert inactive.dev is False

    (tmp_path / switch.ACTIVE_MARKER).write_text(f"{slug}\n", encoding="utf-8")
    active = _verify_args(slug)
    onboard._resolve_verify_by_name(active)
    assert active.dev is True


def test_verify_by_name_refuses_an_archive_without_a_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bayraqsız onboarding parolu QƏSDƏN yazmır — səbəb GİZLƏDİLMİR."""
    slug = _archive_fixture(tmp_path, monkeypatch, with_password=False)

    assert onboard._resolve_verify_by_name(_verify_args(slug)) == 2


def test_verify_by_name_lists_available_names_when_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Səhv ad operatoru `configs/` qovluğunu əl ilə açmağa MƏCBUR ETMİR."""
    _archive_fixture(tmp_path, monkeypatch, with_password=True)

    assert onboard._resolve_verify_by_name(_verify_args("belə-bir-ad-yoxdur")) == 2


def test_verify_by_uuid_keeps_the_old_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Köhnə forma POZULMUR: verilən DSN-lər olduğu kimi `_verify`-a çatır."""
    seen: dict[str, str] = {}

    def _fake_verify(args: argparse.Namespace, tenant_id: uuid.UUID) -> int:
        seen["tenant_id"] = str(tenant_id)
        seen["tenant_dsn"] = args.tenant_dsn
        return 0

    monkeypatch.setattr(onboard, "_verify", _fake_verify)
    args = argparse.Namespace(
        verify="33333333-3333-3333-3333-333333333333",
        tenant_dsn="ELDEN-VERILEN",
        vendor_dsn="ELDEN-VERILEN-2",
        dev=False,
    )

    assert onboard._verify_mode(args) == 0
    assert seen == {
        "tenant_id": "33333333-3333-3333-3333-333333333333",
        "tenant_dsn": "ELDEN-VERILEN",
    }


def test_settings_from_payload_needs_no_temporary_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Arxivin bloku BİRBAŞA oxunur — şifrələnmiş parol ÜÇÜNCÜ nüsxəyə çıxmır."""
    from src.infrastructure.config import connection_file

    monkeypatch.setenv("KOMPASOS_FERNET_KEY", "ZmFrZS1rZXktZm9yLXRlc3RzLTMyLWJ5dGVzLXh4eHg=")
    encrypted = connection_file._encrypt("acar-parol")

    settings = connection_file.settings_from_payload(
        {
            "host": "h",
            "port": 5432,
            "database": "postgres",
            "username": "postgres",
            "password_encrypted": encrypted,
        }
    )

    assert settings.password == "acar-parol"


@pytest.mark.usefixtures("_found")
def test_dry_run_warns_about_duplicates_but_never_blocks_or_asks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--dry-run` heç nə yazmır, ona görə YETİM KİRAYƏÇİ riski YOXDUR.

    Qapı `--dry-run`-dan ƏVVƏL işlədiyi üçün əvvəl İKİ zərər verirdi:
    qeyri-interaktiv mühitdə addım siyahısı ÜMUMİYYƏTLƏ çap olunmurdu
    (exit 3), interaktivdə isə sadəcə «nə olacaq?» sualına baxmaq istəyən
    operator qərar verməyə məcbur edilirdi. Xəbərdarlıq QALIR — o, məhz
    əvvəlcədən-görmə rejimində ən faydalıdır.
    """

    def _never(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("`--dry-run` qərar SORUŞMAMALIDIR")

    monkeypatch.setattr(wizard, "is_interactive", lambda: True)
    monkeypatch.setattr(wizard, "choose", _never)
    args = _duplicate_args(dry_run=True)

    assert onboard._apply_duplicate_policy(args) is None
    output = capsys.readouterr().out
    assert "ARTIQ mövcuddur" in output
    assert "qərar SORUŞULMUR" in output
    assert args.tenant_id == "", "dry-run kimliyi DƏYİŞMƏMƏLİDİR"


@pytest.mark.usefixtures("_found")
def test_dry_run_is_not_blocked_without_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI-da `--dry-run` addım siyahısını GÖSTƏRMƏLİDİR, exit 3 ilə dayanmamalı."""
    monkeypatch.setattr(wizard, "is_interactive", lambda: False)

    assert onboard._apply_duplicate_policy(_duplicate_args(dry_run=True)) is None


def test_a_password_equal_to_the_username_is_not_a_false_alarm(tmp_path: Path) -> None:
    """Sihirbaz DSN-i HƏMİŞƏ `postgres` adı ilə qurur — parolu «postgres» olan
    test layihəsi xam `in` yoxlaması ilə YALANÇI-POZİTİV verərdi.

    Qiymət yüksəkdir: dayanma 6-cı addımda, kirayəçi sətri ARTIQ COMMIT
    olunduqdan SONRA baş verir.
    """
    args = argparse.Namespace(
        out=str(tmp_path),
        dev=False,
        company="Yalanci Pozitiv",
        tenant_dsn="postgresql://postgres:postgres@db.aaaa.supabase.co:5432/postgres",
        vendor_dsn="postgresql://postgres:postgres@db.bbbb.supabase.co:5432/postgres",
    )
    (tmp_path / "connection.template.json").write_text(
        json.dumps(
            {
                "version": 1,
                "host": "db.aaaa.supabase.co",
                "database": "postgres",
                "username": "postgres",
                "password_encrypted": "",
            }
        ),
        encoding="utf-8",
    )

    onboard._assert_no_plaintext_secrets(args)


def test_a_leaked_password_is_still_caught_even_when_it_equals_the_username(
    tmp_path: Path,
) -> None:
    """İstisna siyahısı zəmanəti ZƏİFLƏTMİR — parol sahəsi HƏLƏ DƏ yoxlanılır."""
    args = argparse.Namespace(
        out=str(tmp_path),
        dev=False,
        company="Sizma",
        tenant_dsn="postgresql://postgres:postgres@db.aaaa.supabase.co:5432/postgres",
        vendor_dsn="postgresql://v:vendPW123@db.bbbb.supabase.co:5432/postgres",
    )
    # Şifrələmə sükutla düşüb plaintext yazsa — MƏHZ tutulmalı olan haldır.
    (tmp_path / "connection.template.json").write_text(
        json.dumps({"username": "postgres", "password_encrypted": "postgres"}), encoding="utf-8"
    )

    with pytest.raises(onboard.OnboardingError, match="AÇIQ PAROL"):
        onboard._assert_no_plaintext_secrets(args)


def test_a_secret_nested_inside_the_archive_bundle_is_found(tmp_path: Path) -> None:
    """Bundle `connection` blokunu İÇ-İÇƏ saxlayır — düz gəzinti onu GÖRMƏZDİ."""
    args = argparse.Namespace(
        out=str(tmp_path),
        dev=False,
        company="Icice",
        tenant_dsn="postgresql://postgres:derin%40sirr@db.aaaa.supabase.co:5432/postgres",
        vendor_dsn="postgresql://v:vendPW123@db.bbbb.supabase.co:5432/postgres",
    )
    (tmp_path / "bundle.json").write_text(
        json.dumps({"connection": {"password_encrypted": "derin@sirr"}}), encoding="utf-8"
    )

    with pytest.raises(onboard.OnboardingError, match="AÇIQ PAROL"):
        onboard._assert_no_plaintext_secrets(args)


def test_the_wizard_refuses_to_start_without_a_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Terminal yoxdursa sual SORUŞULMUR — səbəb ƏVVƏLCƏDƏN deyilir.

    ──────────────────────────────────────────────────────────────────────────
    ÖLÇÜLMÜŞ İKİ PİS HAL — BU YOXLAMA HANSINI QAPADIR
    ──────────────────────────────────────────────────────────────────────────
    Boru ilə çağırışda (`echo … | script`) `input()` sətirləri OXUYUR, lakin
    Windows-da `getpass.getpass` stdin-i deyil KONSOLU oxuyur — proses parol
    sualında SƏSSİZCƏ ASILIR (2 dəqiqəlik timeout ilə müşahidə edildi).
    Axın tamamilə bağlıdırsa isə `EOFError` «DAYANDIRILDI» mesajına çevrilir
    və operatoru «kim imtina etdi?» sualına göndərir.

    Hər ikisinin əvəzinə indi AYDIN səbəb + bayraqlı yol göstərilir.
    """

    def _never() -> object:
        raise AssertionError("terminal olmadan sihirbaz BAŞLAMAMALIDIR")

    monkeypatch.setattr(wizard, "is_interactive", lambda: False)
    monkeypatch.setattr(wizard, "run_wizard", _never)

    assert onboard.main([]) == 2
    error = capsys.readouterr().err
    assert "interaktiv terminal" in error
    assert "--tenant-dsn" in error, "çıxış yolu GÖSTƏRİLMƏLİDİR"


def test_verify_by_name_works_through_main_without_any_dsn_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TİKİŞ TESTİ: `main()` → `_verify_mode` → `_resolve_verify_by_name` → `_verify`.

    Ayrı-ayrı funksiyaların işləməsi zəncirin işləməsini ZƏMANƏT ETMİR: bu
    yolun bütün mənası `--tenant-dsn`/`--vendor-dsn` bayraqlarını TƏLƏB
    ETMƏMƏKDİR, halbuki `_reject_invalid_arguments` onları MƏCBURİ sayır.
    Zəncir yalnız ona görə işləyir ki, `_verify_mode` həmin yoxlamadan ƏVVƏL
    bitir — sıra dəyişsə funksiyaların hər biri ayrılıqda YAŞIL qalar, əmr
    isə «--tenant-dsn verilməyib» ilə dayanardı.
    """
    slug = _archive_fixture(tmp_path, monkeypatch, with_password=True)
    monkeypatch.setattr(
        wizard, "load_vendor", lambda: wizard.VendorCredentials("b" * 20, "vendorPW")
    )

    seen: dict[str, str] = {}

    def _fake_verify(args: argparse.Namespace, tenant_id: uuid.UUID) -> int:
        seen["tenant_id"] = str(tenant_id)
        seen["tenant_dsn"] = args.tenant_dsn
        seen["vendor_dsn"] = args.vendor_dsn
        return 0

    monkeypatch.setattr(onboard, "_verify", _fake_verify)

    assert onboard.main(["--verify", slug]) == 0
    assert seen["tenant_id"] == "33333333-3333-3333-3333-333333333333"
    assert "gizli%40parol" in seen["tenant_dsn"]
    assert "db.bbbbbbbbbbbbbbbbbbbb.supabase.co" in seen["vendor_dsn"]


def test_verify_accepts_the_company_name_not_only_the_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operatorun əlində ŞİRKƏT ADI olur, slug yox — `switch.py` ilə eyni qayda."""
    _archive_fixture(tmp_path, monkeypatch, with_password=True)
    monkeypatch.setattr(
        wizard, "load_vendor", lambda: wizard.VendorCredentials("b" * 20, "vendorPW")
    )
    monkeypatch.setattr(onboard, "_verify", lambda args, tenant_id: 0)

    assert onboard.main(["--verify", "Test Şirkət"]) == 0
