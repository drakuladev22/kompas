"""KompasOS — kompozisiya kökü (composition root) və giriş nöqtəsi.

FAZA 1 ƏHATƏSİ: burada YALNIZ infrastruktur qurulur (loglama, DI qeydiyyatı,
şifrələmə/hash-ləmə/2FA servisləri, Event Bus, Saga orkestratoru + siyasət
reyestri). GUI qatı Faza 4-də (`src/presentation`) əlavə olunur.

İcra::

    python -m src.main            # təhlükəsizlik və sağlamlıq yoxlaması
    python -m src.main --check    # eyni, açıq şəkildə
    python -m src.main --strict   # xəbərdarlıqları da xəta sayır (istehsalat)
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src import __version__
from src.infrastructure.security.encryption import EncryptionService
from src.infrastructure.security.hashing import HashingService
from src.shared.di_container import DIContainer, Lifetime, get_container
from src.shared.event_bus import DomainEvent, EventBus, get_event_bus
from src.shared.exceptions import EncryptionKeyError, KompasOSError
from src.shared.logger import (
    LogChannel,
    configure_logging,
    get_logger,
    install_global_exception_hook,
)
from src.shared.saga_orchestrator import (
    InMemorySagaStateRepository,
    SagaOrchestrator,
    SagaStateRepository,
)
from src.shared.saga_policies import assert_registry_is_consistent, policy_for

if TYPE_CHECKING:
    # Bu iki modul yalnız `--developer-mode` yolunda lazımdır və orada
    # funksiya daxilində idxal olunur (bax `_run_developer_panel`). Burada
    # yalnız tip yoxlaması üçün görünürlər — icra zamanı yüklənmirlər.
    from src.infrastructure.persistence.connection import Database
    from src.infrastructure.updates.publisher import ReleasePublisher

PRODUCTION_ENVS = frozenset({"PRODUCTION", "STAGING"})


def build_container(*, event_bus: EventBus | None = None) -> DIContainer:
    """Tətbiqin DI qrafını qurur.

    Faza 2/3-də bu funksiya genişlənəcək: domen repo-ları, 1C konnektorları,
    lisenziya klienti və s. burada qeydiyyatdan keçəcək. Qatların bir-birinə
    birbaşa import etməməsi məhz bu nöqtədə təmin olunur.
    """
    container = get_container()
    bus = event_bus or get_event_bus()

    container.register_instance(EventBus, bus, override=True)
    container.register_singleton(EncryptionService, override=True)
    container.register_singleton(HashingService, override=True)
    container.register_factory(
        SagaStateRepository,  # type: ignore[type-abstract]
        InMemorySagaStateRepository,
        lifetime=Lifetime.SINGLETON,
        override=True,
    )
    container.register_factory(
        SagaOrchestrator,
        lambda c: SagaOrchestrator(
            event_bus=c.resolve(EventBus),
            state_repository=c.resolve(SagaStateRepository),
            # Siyasət reyestri burada qoşulur — orkestrator onu birbaşa
            # idxal etmir (dövri asılılıqdan qaçmaq üçün, bax saga_policies).
            policy_resolver=policy_for,
        ),
        lifetime=Lifetime.SINGLETON,
        override=True,
    )
    return container


def _register_audit_listener(bus: EventBus) -> None:
    """Bütün domen hadisələrini `audit.log`-a yazan universal dinləyici.

    `DomainEvent` bazis tipinə abunə olduğu üçün HƏR hadisəni tutur — modullar
    ayrı-ayrılıqda audit yazmağı unuda bilməz.
    """
    audit = get_logger("kompasos.audit.listener", channel=LogChannel.AUDIT)

    def on_any_event(event: DomainEvent) -> None:
        audit.info(event.event_name, extra=event.to_dict())

    bus.subscribe(DomainEvent, on_any_event, priority=1000)


# --------------------------------------------------------------------------- #
# Sağlamlıq / təhlükəsizlik yoxlaması
# --------------------------------------------------------------------------- #


@dataclass
class CheckResult:
    """Bir yoxlamanın nəticəsi."""

    name: str
    ok: bool
    severity: str  # "ERROR" | "WARNING" | "INFO"
    message: str


def _check_saga_registry() -> CheckResult:
    """Saga siyasət reyestrinin daxili tutarlılığı (SEC-003)."""
    try:
        assert_registry_is_consistent()
    except ValueError as exc:
        return CheckResult("saga_policy_registry", False, "ERROR", str(exc))
    return CheckResult("saga_policy_registry", True, "INFO", "Reyestr tutarlıdır")


def _check_event_bus(container: DIContainer) -> CheckResult:
    bus = container.resolve(EventBus)
    get_logger(__name__).info("CHECK_EVENT_BUS", extra=bus.stats)
    return CheckResult(
        "event_bus",
        True,
        "INFO",
        f"{bus.stats['subscription_count']} abunəlik aktivdir",
    )


def _check_pending_reconciliation(container: DIContainer) -> CheckResult:
    """İnsan müdaxiləsi gözləyən saga varmı (bölmə 1)."""
    pending = container.resolve(SagaOrchestrator).pending_reconciliation()
    return CheckResult(
        "saga_pending_reconciliation",
        not pending,
        "ERROR" if pending else "INFO",
        f"{len(pending)} saga insan müdaxiləsi gözləyir" if pending else "Gözləyən saga yoxdur",
    )


def _check_encryption(container: DIContainer) -> CheckResult:
    """Açar mövcuddur, round-trip işləyir və AAD bağlantısı tətbiq olunur (SEC-002)."""
    encryption = container.resolve(EncryptionService)
    context = "self-check"
    try:
        probe = encryption.encrypt("self-check-value", context=context)
        round_trip_ok = encryption.decrypt(probe, context=context) == "self-check-value"
    except EncryptionKeyError as exc:
        return CheckResult("encryption", False, "ERROR", exc.message)

    # Yanlış kontekstlə açılmamalıdır — cut-and-paste qoruması işləyirmi?
    aad_enforced = False
    try:
        encryption.decrypt(probe, context="wrong-context")
    except Exception:
        aad_enforced = True

    if round_trip_ok and aad_enforced:
        return CheckResult(
            "encryption",
            True,
            "INFO",
            f"AES-256-GCM işlək (mənbə: {encryption.key_source}, "
            f"açar: {encryption.primary_key_id})",
        )
    return CheckResult(
        "encryption",
        False,
        "ERROR",
        f"Şifrələmə yoxlaması uğursuz (round_trip={round_trip_ok}, aad={aad_enforced})",
    )


def _check_pepper(container: DIContainer, *, is_production: bool) -> CheckResult:
    """4-rəqəmli PIN-lər üçün pepper (SEC-005) — istehsalatda MƏCBURİ."""
    if container.resolve(HashingService).has_pepper:
        return CheckResult("hash_pepper", True, "INFO", "Pepper konfiqurasiya edilib")
    return CheckResult(
        "hash_pepper",
        not is_production,
        "ERROR" if is_production else "WARNING",
        "KOMPASOS_HASH_PEPPER təyin edilməyib — 4-rəqəmli PIN-lər DB sızması "
        "halında brute-force ilə bərpa oluna bilər",
    )


def _check_migrations() -> CheckResult:
    """Miqrasiya faylları mövcuddurmu (schema.sql tək başına kifayət etmir)."""
    folder = Path(__file__).resolve().parents[1] / "database" / "migrations"
    files = sorted(folder.glob("*.sql")) if folder.exists() else []
    return CheckResult(
        "migrations",
        bool(files),
        "INFO" if files else "WARNING",
        f"{len(files)} miqrasiya faylı: {', '.join(f.name for f in files) or 'yoxdur'}",
    )


def _check_schema_file() -> CheckResult:
    schema = Path(__file__).resolve().parents[1] / "database" / "schema.sql"
    return CheckResult(
        "schema_file",
        schema.exists(),
        "INFO" if schema.exists() else "ERROR",
        str(schema),
    )


def _check_dotenv(*, is_production: bool) -> CheckResult | None:
    """İstehsalatda `.env` faylı olmamalıdır — sirlər DPAPI/Secrets-dən gəlir."""
    dotenv = Path(__file__).resolve().parents[1] / ".env"
    if not (dotenv.exists() and is_production):
        return None
    return CheckResult(
        "dotenv_in_production",
        False,
        "WARNING",
        ".env faylı istehsalat mühitində mövcuddur — sirlər DPAPI/Secrets "
        "vasitəsilə təchiz olunmalıdır",
    )


def run_self_check(container: DIContainer, *, strict: bool = False) -> list[CheckResult]:
    """Faza 1 təhlükəsizlik və sağlamlıq yoxlaması.

    Args:
        strict: `True` olduqda xəbərdarlıqlar da xəta sayılır (istehsalat buraxılışı).
    """
    log = get_logger(__name__)
    security_log = get_logger(__name__, channel=LogChannel.SECURITY)
    env = os.environ.get("KOMPASOS_ENV", "PRODUCTION").upper()
    is_production = env in PRODUCTION_ENVS

    candidates: list[CheckResult | None] = [
        _check_saga_registry(),
        _check_event_bus(container),
        _check_pending_reconciliation(container),
        _check_encryption(container),
        _check_pepper(container, is_production=is_production),
        _check_schema_file(),
        _check_migrations(),
        _check_dotenv(is_production=is_production),
    ]
    results: list[CheckResult] = [item for item in candidates if item is not None]

    # ------------------------------ nəticə ---------------------------------- #
    for result in results:
        # `message` LogRecord-un qorunan adıdır — `detail` istifadə olunur.
        # (Logger indi belə halları özü də təhlükəsiz adlandırır, bax
        # RESERVED_KEY_PREFIX — lakin mənbədə düzgün ad daha oxunaqlıdır.)
        payload = {"check": result.name, "detail": result.message}
        if result.severity == "ERROR" and not result.ok:
            security_log.error("SELF_CHECK_FAILED_ITEM", extra=payload)
        elif result.severity == "WARNING" and not result.ok:
            security_log.warning("SELF_CHECK_WARNING", extra=payload)
        else:
            log.info("SELF_CHECK_ITEM", extra=payload)

    if strict:
        for result in results:
            if not result.ok:
                result.severity = "ERROR"

    return results


def summarize(results: list[CheckResult]) -> int:
    """Yoxlama nəticələrini yekunlaşdırır və çıxış kodunu qaytarır."""
    log = get_logger(__name__)
    errors = [r for r in results if not r.ok and r.severity == "ERROR"]
    warnings = [r for r in results if not r.ok and r.severity == "WARNING"]

    if errors:
        log.error(
            "SELF_CHECK_FAILED",
            extra={
                "errors": len(errors),
                "warnings": len(warnings),
                "failed_checks": [r.name for r in errors],
            },
        )
        return 1

    log.info(
        "SELF_CHECK_PASSED",
        extra={
            "version": __version__,
            "phase": 1,
            "warnings": len(warnings),
            "warning_checks": [r.name for r in warnings],
            "note": "GUI qatı Faza 4-də əlavə olunur",
        },
    )
    return 0


def _run_developer_panel(args: argparse.Namespace) -> int:
    """Developer Panelini açır (konsol və ya pəncərə).

    İdxallar QƏSDƏN funksiya daxilindədir: `src.developer_panel` müştəriyə
    göndərilən paketə daxil EDİLMİR, ona görə modul səviyyəsində idxal
    edilsəydi adi işə düşmə də ondan asılı olardı.
    """
    from src.developer_panel.console import run_console  # noqa: PLC0415
    from src.infrastructure.licensing.developer_directory import (  # noqa: PLC0415
        DEVELOPER_MODE_ENV,
        SERVICE_ROLE_ENV,
        DeveloperModeRequiredError,
        DeveloperTenantDirectory,
        developer_mode_enabled,
    )

    # Konfiqurasiya yoxlaması BAZADAN ƏVVƏL: əks halda müştəri PC-sində
    # bayraq yazan istifadəçi "DATABASE_URL yoxdur" kimi yanıldıcı xəta
    # alardı və əsl səbəbi (rejim ümumiyyətlə açıq deyil) görməzdi.
    if not developer_mode_enabled():
        raise DeveloperModeRequiredError(
            f"`{DEVELOPER_MODE_ENV}` və `{SERVICE_ROLE_ENV}` təyin edilməyib",
            context={"required_env": [DEVELOPER_MODE_ENV, SERVICE_ROLE_ENV]},
        )

    from src.infrastructure.persistence.connection import Database  # noqa: PLC0415

    database = Database()
    directory = DeveloperTenantDirectory(database)
    publisher = _build_release_publisher(database)

    if args.gui:
        from src.developer_panel.ui import launch  # noqa: PLC0415

        return launch(directory, publisher)

    code, output = run_console(
        directory,
        search=args.search,
        extend=args.extend,
        force_version=args.force_version,
        confirmed=args.yes,
        publisher=publisher,
        publish_package=args.publish,
        publish_version=args.publish_version,
        publish_notes=args.publish_notes,
        publish_mandatory=args.publish_mandatory,
    )
    sys.stdout.write(output + "\n")
    return code


def _run_gui(args: argparse.Namespace) -> int:
    """Əsas interfeysi açır (Faza 4).

    İdxal funksiya daxilindədir: `--check` yolunda PySide6 yüklənməməlidir —
    CI-ın başsız (headless) mühitində Qt-ni idxal etmək lazımsız asılılıq və
    əlavə saniyələr deməkdir.
    """
    from src.presentation.app import run  # noqa: PLC0415
    from src.presentation.theme.tokens import ThemeMode  # noqa: PLC0415

    return run(
        preview=args.preview,
        kiosk=args.kiosk,
        theme=ThemeMode(args.theme),
    )


def _build_release_publisher(database: Database) -> ReleasePublisher | None:
    """Yayım qatı — Supabase ünvanı yoxdursa `None` (bölmə yalnız o zaman gizlənir).

    Naşir yoxlayıcısı BURADA qurulur ki, panel yayımdan ƏVVƏL imzanı yoxlaya
    bilsin. `KOMPASOS_UPDATE_PUBLISHER` boşdursa yoxlayıcı istənilən etibarlı
    imzanı qəbul edərdi — bu, klient tərəfdəki qayda ilə eynidir və orada da
    həmin dəyişənin doldurulması tələb olunur (bax `.env.example`).
    """
    from src.infrastructure.updates.catalog import SUPABASE_URL_ENV  # noqa: PLC0415
    from src.infrastructure.updates.publisher import ReleasePublisher  # noqa: PLC0415
    from src.infrastructure.updates.verification import AuthenticodeVerifier  # noqa: PLC0415

    if not os.environ.get(SUPABASE_URL_ENV, "").strip():
        get_logger(__name__).info(
            "PUBLISHER_NOT_CONFIGURED", extra={"missing_env": SUPABASE_URL_ENV}
        )
        return None

    return ReleasePublisher(
        database,
        verifier=AuthenticodeVerifier(
            expected_subject=os.environ.get("KOMPASOS_UPDATE_PUBLISHER", "")
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Giriş nöqtəsi."""
    parser = argparse.ArgumentParser(prog="kompasos", description="KompasOS")
    parser.add_argument(
        "--check",
        action="store_true",
        help="yalnız sağlamlıq yoxlaması işlət (Faza 1 defolt davranışı)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="xəbərdarlıqları da xəta say (istehsalat buraxılışı üçün)",
    )
    parser.add_argument("--log-dir", type=Path, default=None, help="log qovluğu")
    # ---------------------------------------------------------------------
    # GUI (Faza 4). `--gui` TƏK BAŞINA əsas interfeysi açır; `--developer-mode`
    # ilə birlikdə verildikdə Developer Panelinin pəncərə variantını açır
    # (bax `_run_developer_panel`) — ona görə ayrıca bayraq YARADILMIR.
    #
    # Bu yol sağlamlıq yoxlamasını ATLAYIR, çünki interfeys bazasız da
    # açılmalıdır: quraşdırma sehrbazı məhz baza konfiqurasiya edilməmiş
    # kompüterdə işə düşür.
    # ---------------------------------------------------------------------
    parser.add_argument(
        "--kiosk",
        action="store_true",
        help="kiosk rejimi: tam ekran PIN klaviaturası",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="ekranları maketdəki nümunə məzmunla doldur (dizayn yoxlaması)",
    )
    parser.add_argument(
        "--theme",
        choices=("light", "dark", "system"),
        default="system",
        help="işə düşmə teması",
    )
    # ---------------------------------------------------------------------
    # DEVELOPER PANELİ (bölmə 8) — YALNIZ hazırlayıcının öz kompüterində.
    # Bayraq TƏK BAŞINA kifayət etmir: `KOMPASOS_DEVELOPER_MODE` və
    # `KOMPASOS_SUPABASE_SERVICE_ROLE_KEY` təyin olunmayıbsa rejim açılmır
    # (bax `developer_mode_enabled`). Müştəri quraşdırmasında həmin dəyişənlər
    # ümumiyyətlə mövcud olmur, yəni bayraq təsadüfən işə düşə bilməz.
    # ---------------------------------------------------------------------
    parser.add_argument(
        "--developer-mode",
        action="store_true",
        help="Developer Panelini aç (yalnız hazırlayıcının yerli mühiti)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="interfeysi aç; `--developer-mode` ilə birlikdə — Developer Paneli pəncərəsi",
    )
    parser.add_argument("--search", default="", help="Developer Paneli: ad/e-poçt üzrə süzgəc")
    parser.add_argument(
        "--extend", default="", metavar="TENANT_ID", help="Developer Paneli: 1 ay uzat"
    )
    parser.add_argument(
        "--force-version",
        default="",
        metavar="TENANT_ID=X.Y.Z",
        help="Developer Paneli: tenant üçün məcburi versiya (boş dəyər ləğv edir)",
    )
    parser.add_argument(
        "--publish",
        default="",
        metavar="FAYL",
        help="Developer Paneli: quraşdırıcını Storage-a yüklə və kataloqa yaz",
    )
    parser.add_argument(
        "--publish-version", default="", metavar="X.Y.Z", help="yayımlanacaq versiya nömrəsi"
    )
    parser.add_argument("--publish-notes", default="", help="buraxılış qeydləri")
    parser.add_argument(
        "--publish-mandatory",
        action="store_true",
        help="buraxılışı məcburi yeniləmə kimi işarələ",
    )
    parser.add_argument("--yes", action="store_true", help="dəyişdirən əmrlər üçün təsdiq")
    args = parser.parse_args(argv)

    # `force=True` VACİBDİR: modul səviyyəsindəki `get_logger(...)` çağırışları
    # import zamanı lazy konfiqurasiyanı işə salır (app_version="0.0.0").
    # Kompozisiya kökü olaraq son sözü main deyir — əks halda bütün log
    # sətirləri yanlış versiya ilə yazılır.
    log_dir = configure_logging(
        log_dir=args.log_dir,
        level=os.environ.get("KOMPASOS_LOG_LEVEL", "INFO"),
        app_version=__version__,
        force=True,
    )
    install_global_exception_hook()

    log = get_logger(__name__)
    log.info(
        "KOMPASOS_STARTING",
        extra={
            "version": __version__,
            "env": os.environ.get("KOMPASOS_ENV", "PRODUCTION"),
            "log_dir": str(log_dir),
        },
    )

    try:
        if args.developer_mode:
            return _run_developer_panel(args)
        if args.gui:
            return _run_gui(args)
        bus = get_event_bus()
        _register_audit_listener(bus)
        container = build_container(event_bus=bus)
        return summarize(run_self_check(container, strict=args.strict))
    except KompasOSError as exc:
        get_logger(__name__, channel=LogChannel.ERROR).critical(
            "STARTUP_FAILED", extra=exc.to_dict()
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
