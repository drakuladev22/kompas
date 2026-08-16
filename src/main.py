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
from src.shared.runtime import deployment_root, is_frozen, relaunch_command
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
    from src.infrastructure.persistence.connection_types import TenantDatabase
    from src.infrastructure.updates.publisher import ReleasePublisher

PRODUCTION_ENVS = frozenset({"PRODUCTION", "STAGING"})

#: Çıxış kodları — HƏR KODUN TƏK MƏNASI OLMALIDIR (bax `docs/cli_reference.md` §3).
#: `0` uğur, `1` ümumi uğursuzluq — bunlar DƏYİŞMİR (geriyə uyğunluq).
#: `2` yalnız işə düşmə/baza xətasıdır; təsdiq-tələbi `4`-ə köçürülüb
#: (`developer_panel.console.EXIT_CONFIRMATION_REQUIRED`) — əvvəl ikisi eyni
#: kodu qaytarırdı və skript «`--yes` əlavə et» ilə «baza yoxdur» hallarını
#: ayırd edə bilmirdi.
EXIT_STARTUP_ERROR = 2
#: Kiosk nəzarətçisi yenidən-başlatma həddinə çatdı (`_run_watchdog`).
EXIT_WATCHDOG_RESTART_LIMIT = 3


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
    """Miqrasiya faylları mövcuddurmu (schema.sql tək başına kifayət etmir).

    Paketlənmiş `.exe`-də yoxluq NASAZLIQ DEYİL — səbəb `_check_schema_file`
    docstring-indədir.
    """
    folder = deployment_root() / "database" / "migrations"
    files = sorted(folder.glob("*.sql")) if folder.exists() else []
    if not files and is_frozen():
        return CheckResult(
            "migrations",
            True,
            "INFO",
            f"Miqrasiya qovluğu paketin yanında yoxdur ({folder}) — "
            "bu, yerləşdirmə artefaktıdır, klient tətbiqi onu oxumur",
        )
    return CheckResult(
        "migrations",
        bool(files),
        "INFO" if files else "WARNING",
        f"{len(files)} miqrasiya faylı: {', '.join(f.name for f in files) or 'yoxdur'}",
    )


def _check_schema_file() -> CheckResult:
    """Bazis sxem faylı əlçatandırmı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SƏRTLİK REJİMDƏN ASILIDIR
    ──────────────────────────────────────────────────────────────────────────
    Mənbədən işə salındıqda faylın olmaması repozitoriyanın natamam olması
    deməkdir — `ERROR`. Paketlənmiş `.exe`-də isə fayl QƏSDƏN yoxdur: sxem
    Supabase-i quran şəxs tərəfindən BİR DƏFƏ tətbiq olunur, klient tətbiqi
    onu işləmə zamanı oxumur (`src/`-də `schema.sql`-a heç bir müraciət yoxdur
    — yalnız şərhlərdə istinad edilir). Müştəri maşınında olmayan faylı "xəta"
    saymaq özünü-yoxlamanı yanlış qırmızıya boyayardı.
    """
    schema = deployment_root() / "database" / "schema.sql"
    exists = schema.exists()
    if not exists and is_frozen():
        return CheckResult(
            "schema_file",
            True,
            "INFO",
            f"Sxem faylı paketin yanında yoxdur ({schema}) — "
            "bazanı quran tərəf tətbiq edir, klient onu oxumur",
        )
    return CheckResult("schema_file", exists, "INFO" if exists else "ERROR", str(schema))


def _check_dotenv(*, is_production: bool) -> CheckResult | None:
    """İstehsalatda `.env` faylı olmamalıdır — sirlər DPAPI/Secrets-dən gəlir.

    Paketlənmiş rejimdə fayl `.exe`-nin YANINDA axtarılır: `.env` heç vaxt
    paketə salınmır (bölmə 2), ona görə arxivin içinə baxmaq mənasızdır.
    """
    dotenv = deployment_root() / ".env"
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

    from src.infrastructure.persistence.connection_types import (  # noqa: PLC0415
        TenantDatabase,
    )

    # `TenantDatabase` — HALBUKİ BU, HAZIRLAYICI PANELİDİR
    # -------------------------------------------------------------------------
    # Panel lisenziya reyestrini oxuyur, lakin həmin cədvəllər (`license_tenants`,
    # `tenant_check_ins`, `license_audit_log`) BU GÜN tenant sxemindədir —
    # `service_role` + RLS qərarının nəticəsidir (CLAUDE.md §9, Master Panel).
    # Yəni DSN mənbəyi `DATABASE_URL`-dir və tip də məhz onu deməlidir.
    #
    # DB-3-ün qurduğu AYRICA vendor bazası (`migrations/vendor/`) hələ bu
    # panelin mənbəyi DEYİL. Köçürmə olduqda dəyişməli olan yer BURADIR və
    # `VendorDatabase.from_env()` onu tələb edəcək — o vaxta qədər tipin açıq
    # yazılması köçürmənin hansı sətirdən başlayacağını göstərir.
    database = TenantDatabase()
    directory = DeveloperTenantDirectory(database)
    publisher = _build_release_publisher(database)

    if args.gui:
        from src.developer_panel.ui import launch  # noqa: PLC0415

        return launch(directory, publisher)

    # DİAQNOSTİKA BAYRAQLARI DA ÖTÜRÜLÜR — əvvəl ötürülmürdü və nəticə SÜKUTLA
    # yanlış idi: `--developer-mode --crashes` çökmə panelini yox, adi müştəri
    # cədvəlini göstərirdi. Xəta mesajı yox idi, yəni istifadəçi səhv məlumata
    # baxdığını bilmirdi. `run_console` onları ilk gündən qəbul edir və
    # `_render_view` məhz onlara görə budaqlanır — boşluq yalnız bu çağırışda idi.
    code, output = run_console(
        directory,
        search=args.search,
        show_crashes=args.crashes,
        show_tickets=args.tickets,
        extend=args.extend,
        force_version=args.force_version,
        confirmed=args.yes,
        publisher=publisher,
        publish_package=args.publish,
        publish_version=args.publish_version,
        publish_notes=args.publish_notes,
        publish_mandatory=args.publish_mandatory,
        database=database,
        recover_access=args.recover_access,
        recovery_reference=args.recovery_reference,
        recovery_contact=args.recovery_contact,
    )
    sys.stdout.write(output + "\n")
    return code


def _run_gui(args: argparse.Namespace) -> int:
    """Əsas interfeysi açır (Faza 4/5).

    İdxal funksiya daxilindədir: `--check` yolunda PySide6 yüklənməməlidir —
    CI-ın başsız (headless) mühitində Qt-ni idxal etmək lazımsız asılılıq və
    əlavə saniyələr deməkdir.

    ──────────────────────────────────────────────────────────────────────────
    KONTEKST NİYƏ "OLA BİLƏR / OLMAYA BİLƏR"
    ──────────────────────────────────────────────────────────────────────────
    İki rejim var və hər ikisi legitimdir:

        `--preview`  → baza LAZIM DEYİL. Dizayn yoxlaması, maket müqayisəsi,
                       CI-dakı Qt testləri bu yolla işləyir.
        adi rejim    → baza MƏCBURİDİR. Qurulmazsa fatal başlanğıc ekranı
                       göstərilir (bölmə 8) — səssiz boş pəncərə YOX.
    """
    from src.presentation.app import run  # noqa: PLC0415
    from src.presentation.composition import StartupError, build_context  # noqa: PLC0415
    from src.presentation.theme.tokens import ThemeMode  # noqa: PLC0415

    context = None
    startup_error = ""
    startup_failure_kind = None
    if not args.preview:
        try:
            context = build_context()
        except StartupError as exc:
            # Proses BURADA dayanmır: istifadəçi izahlı ekran görməlidir,
            # konsola yazılmış bir sətir deyil (mağaza PC-sində konsol yoxdur).
            startup_error = exc.user_message
            # NÖV DƏ ÖTÜRÜLÜR (DB-4 Faza 4): ekran «yenidən cəhd et» ilə
            # «bağlantı ayarları» arasında məhz ona görə seçim edir. Yalnız
            # mətn ötürsəydik, şəbəkə nasazlığı da, konfiqurasiya boşluğu da
            # eyni çıxılmaz ekranı verərdi.
            startup_failure_kind = exc.kind
            get_logger(__name__, channel=LogChannel.ERROR).critical(
                "GUI_STARTUP_ERROR", extra=exc.to_dict()
            )

    return run(
        preview=args.preview,
        kiosk=args.kiosk,
        theme=ThemeMode(args.theme),
        context=context,
        startup_error=startup_error,
        startup_failure_kind=startup_failure_kind,
        # ÖNİZLƏMƏ REJİMİNDƏ `None`: orada baza ümumiyyətlə tələb olunmur,
        # yəni «yenidən cəhd et» düyməsi mənasız olardı.
        rebuild_context=None if args.preview else build_context,
    )


def _run_scheduled_jobs() -> int:
    """Planlaşdırılmış işləri BAŞSIZ icra edir (Faza 11, `--run-scheduled-jobs`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA GİRİŞ NÖQTƏSİ — GUI TAYMERİ KİFAYƏT ETMİR
    ──────────────────────────────────────────────────────────────────────────
    GUI dövrəsi YALNIZ yüngül işləri icra edir (`include_heavy=False`), çünki
    `pg_dump` interfeysi dəqiqələrlə dondurardı. Yəni gecəlik ehtiyat nüsxə
    HEÇ VAXT GUI-dən işləyə bilməz. Bu yol onu işlədir və işləyir ki, mağaza
    PC-si gecə açıq olmasa belə (Windows Task Scheduler oyandırma və ya səhər
    ilk açılış), iş gecikmiş icra (catch-up) ilə tutulsun.

    ──────────────────────────────────────────────────────────────────────────
    ÇOX-KİRAYƏÇİLİK: BU YOL BİR KİRAYƏÇİ ÜÇÜNDÜR (SEC-008)
    ──────────────────────────────────────────────────────────────────────────
    `run_due(tenant_id=...)` tək kirayəçi qəbul edir və burada kirayəçi
    `KOMPASOS_TENANT_ID`-dən gəlir (`build_context()`), yəni HƏMİŞƏ məhz bu
    quraşdırmanın sahibi.

    `DeveloperTenantDirectory` bütün müştərilərin siyahısını verə bilər, lakin
    ONDAN İSTİFADƏ EDİLMİR və səbəb `_build_release_publisher`-dəki ilə
    eynidir: o siyahı LİSENZİYA bazasındadır və `KOMPASOS_DEVELOPER_MODE` +
    `service_role` açarı tələb edir — müştəri maşınında həmin dəyişənlər
    ümumiyyətlə yoxdur. Üstəlik `system_limits` RLS ilə kirayəçiyə bağlıdır
    (SEC-008): hazırlayıcının maşınından "bütün kirayəçilər üçün" dövrə
    işlətmək bir müştərinin `SCHEDULER_NIGHTLY_HOUR` dəyərini digərinin gecə
    işinə tətbiq etmək olardı. Hər quraşdırma ÖZ işlərini icra edir; bu, həm
    icarə modelinə (hər terminal öz `instance_id`-si ilə), həm də RLS-ə
    uyğun yeganə variantdır.

    Çıxış kodu:
        0 — bütün işlər uğurlu (və ya vaxtı çatan iş yox idi);
        1 — ən azı bir iş çökdü (`FAILED`) — nasazlıq Task Scheduler-də
            görünməlidir, əks halda gecə işlərinin dayandığı aşkarlanmazdı;
        2 — quraşdırma/baza xətası (`main`-dəki ümumi `KompasOSError` qolu).
    """
    from src.presentation.composition import build_context  # noqa: PLC0415

    log = get_logger(__name__)
    # KİMLİK BURADA YARADILMIR (`allow_generate=False`): bu yol Task Scheduler
    # altında, çox vaxt BAŞQA istifadəçi hesabı ilə işləyir və onun
    # `%LOCALAPPDATA%`-sı fərqlidir. Orada avtomatik yaradılan kimlik "ikinci,
    # boş tenant" demək olardı — gecəlik işlər səssizcə heç nə etməzdi və
    # nasazlıq yalnız aylar sonra, ehtiyat nüsxə axtarılanda üzə çıxardı.
    # GUI yolu isə tam əksinədir: orada kimliyin yaradılması ilk quraşdırmanın
    # ÖZÜDÜR (`build_context()` defoltu, SEC-021).
    context = build_context(allow_generate=False)
    report = context.run_scheduled_jobs(include_heavy=True)

    lines = [
        f"Planlaşdırılmış işlər: {report.executed} icra, {report.succeeded} uğurlu.",
        *(
            f"  • {outcome.job_key}: {outcome.state.value}"
            f"{' — ' + outcome.detail if outcome.detail else ''}"
            f"{' — ' + outcome.error_az if outcome.error_az else ''}"
            for outcome in report.outcomes
        ),
    ]
    if report.failed_jobs:
        lines.append(f"UĞURSUZ: {', '.join(report.failed_jobs)}")
    # STDOUT XÜLASƏSİ **VƏ** STRUKTUR LOG: birincisi əməliyyatçının Task
    # Scheduler tarixçəsində gördüyüdür, ikincisi isə mərkəzi jurnala düşür.
    # Yalnız log yazsaydıq, əmri əl ilə işə salan admin ekranda heç nə görməz
    # və "işlədimi?" sualı cavabsız qalardı.
    sys.stdout.write("\n".join(lines) + "\n")
    log.info(
        "SCHEDULED_JOBS_CLI_FINISHED",
        extra={
            "icra_edilen": report.executed,
            "ugurlu": report.succeeded,
            "ugursuz": list(report.failed_jobs),
        },
    )
    return 1 if report.failed_jobs else 0


def _run_watchdog(args: argparse.Namespace) -> int:
    """Kiosk nəzarətçisini işə salır (bölmə 5).

    Bu proses interfeysi AÇMIR — o, `--gui --kiosk` ilə alt-proses yaradır və
    çökmə halında onu yenidən başladır. Ayrı proses olması qəsdəndir: eyni
    prosesdə "özünü yenidən başlatmaq" mümkün deyil, çünki çökən proses artıq
    kod icra etmir.
    """
    from src.infrastructure.kiosk.watchdog import KioskWatchdog  # noqa: PLC0415

    # Əmr prefiksi rejimdən asılıdır — səbəb `shared/runtime.py`-dadır:
    # paketlənmiş `.exe`-yə `-m src.main` ötürmək `argparse` xətası verir.
    command = [*relaunch_command(), "--gui"]
    if args.kiosk:
        command.append("--kiosk")
    if args.theme != "system":
        command.extend(["--theme", args.theme])

    # `limits=` QƏSDƏN ÖTÜRÜLMÜR (Faza 10.2 auditinin nəticəsi): nəzarətçi
    # məhz tətbiq — və çox vaxt onunla birlikdə baza bağlantısı — çökəndə
    # işləməlidir. Limit oxusu üçün `Database` qursaydıq, bazanın əlçatmazlığı
    # yenidən-başlatma məntiqinin ÖZÜNÜ dayandırardı, yəni qoruma məhz lazım
    # olduğu anda yox olardı. Cədvəl `system_limits`-dədir və `KioskWatchdog`
    # onu pəncərə VERİLDİKDƏ oxuyur — burada fallback şüurlu seçimdir.
    outcome = KioskWatchdog(command=command).run()
    get_logger(__name__).info(
        "KIOSK_WATCHDOG_FINISHED",
        extra={
            "reason": outcome.stopped_because,
            "restarts": outcome.restart_count,
            "last_exit_code": outcome.last_exit_code,
        },
    )
    # Yenidən başlatma fırtınası — çıxış kodu qeyri-sıfır olmalıdır ki,
    # Windows Task Scheduler / servis meneceri bunu nasazlıq kimi görsün.
    return EXIT_WATCHDOG_RESTART_LIMIT if outcome.hit_restart_limit else 0


def _build_release_publisher(database: TenantDatabase) -> ReleasePublisher | None:
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

    # `limits=` QƏSDƏN ÖTÜRÜLMÜR (SEC-008): bu, Developer Panelinin ÇOX-KİRAYƏÇİ
    # yoludur — hazırlayıcı bütün tenant-lar üçün yayım edir və "hansı tenant-ın
    # `system_limits` sətri oxunsun?" sualının doğru cavabı YOXDUR. `system_limits`
    # RLS ilə tenant-a bağlıdır; ixtiyari bir tenant seçmək bir müştərinin
    # parametrini bütün şəbəkəyə tətbiq etmək olardı. Ona görə yayım tərəfi
    # `UPDATE_MAX_PACKAGE_BYTES`-in fallback dəyəri ilə işləyir.
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
        "--watchdog",
        action="store_true",
        help=(
            "kiosk nəzarətçisi: tətbiq çökərsə avtomatik yenidən başladır "
            "(mağaza PC-lərində bu rejimlə işə salınır, bölmə 5)"
        ),
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="ekranları maketdəki nümunə məzmunla doldur (dizayn yoxlaması)",
    )
    # ---------------------------------------------------------------------
    # PLANLAŞDIRILMIŞ İŞLƏR (Faza 11). Bu rejim interfeys AÇMIR: Windows Task
    # Scheduler onu gecə çağırır (bax `docs/scheduler_setup.md`, Variant C).
    # AĞIR işlər (`pg_dump`) YALNIZ burada icra olunur — GUI taymeri onları
    # atlayır, çünki interfeys axınında dəqiqələrlə donma yaradardılar.
    # ---------------------------------------------------------------------
    parser.add_argument(
        "--run-scheduled-jobs",
        action="store_true",
        help=(
            "planlaşdırılmış fon işlərini bir dəfə icra et və çıx "
            "(başsız; ağır işlər daxil — gecəlik ehtiyat nüsxə)"
        ),
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
        "--crashes",
        action="store_true",
        help="Developer Paneli: anonim çökmə hesabatları, tezliyə görə qruplaşdırılmış",
    )
    parser.add_argument(
        "--tickets",
        action="store_true",
        help="Developer Paneli: dəstək müraciətləri inbox-u (SLA vəziyyəti ilə)",
    )
    parser.add_argument(
        "--extend", default="", metavar="TENANT_ID", help="Developer Paneli: 1 ay uzat"
    )
    parser.add_argument(
        "--force-version",
        default="",
        metavar="TENANT_ID=X.Y.Z",
        help="Developer Paneli: tenant üçün məcburi versiya (boş dəyər ləğv edir)",
    )
    # Təcili giriş bərpası (bölmə 2) — QƏSDƏN yalnız konsolda, GUI düyməsi
    # deyil: prosedur tenant-ın `employees` cədvəlinə yazır və gündəlik
    # istifadə üçün nəzərdə tutulmayıb (bax `console._recover_access`).
    parser.add_argument(
        "--recover-access",
        default="",
        metavar="TENANT_ID=username",
        help="Developer Paneli: təcili giriş bərpası (bütün admin hesabları itibsə)",
    )
    parser.add_argument(
        "--recovery-reference",
        default="",
        metavar="İSTİNAD",
        help="`--recover-access` üçün MƏCBURİ kimlik təsdiqi izi (ticket/qeyd nömrəsi)",
    )
    parser.add_argument(
        "--recovery-contact",
        default="",
        metavar="ƏLAQƏ",
        help="`--recover-access` üçün MƏCBURİ təsdiqlənmiş şirkət e-poçtu/telefonu",
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
        # Planlayıcı GUI qollarından ƏVVƏL yoxlanılır: paketlənmiş rejimdə
        # arqumentsiz işə düşmə DEFOLTU GUI-dir (aşağıdakı `is_frozen()`
        # şərti) və yoxlama sonra gəlsəydi, Task Scheduler-in çağırdığı
        # `KompasOS.exe --run-scheduled-jobs` mağaza PC-sində PƏNCƏRƏ AÇARDI.
        if args.run_scheduled_jobs:
            return _run_scheduled_jobs()
        # Nəzarətçi GUI-dən ƏVVƏL yoxlanılır: `--watchdog --kiosk` çağırışında
        # bu proses interfeysi ÖZÜ açmamalıdır, alt-prosesi idarə etməlidir.
        if args.watchdog:
            return _run_watchdog(args)
        # ------------------------------------------------------------------
        # NİYƏ PAKETLƏNMİŞ REJİMDƏ DEFOLT GUI-DİR
        # ------------------------------------------------------------------
        # `.exe` iki dəfə kliklənəndə arqument ÖTÜRÜLMÜR. Defolt yol
        # özünü-yoxlama olduğu üçün paket istifadəçidə belə davranırdı:
        # pəncərə açılmır, `--windowed` rejimində konsol da yoxdur, proses
        # 1 kodu ilə səssizcə çıxır — yəni tətbiq "işə düşmür" görünür.
        # Yoxlanılıb: `dist/KompasOS.exe` → `SELF_CHECK_FAILED`, çıxış kodu 1,
        # heç bir pəncərə yoxdur.
        #
        # Mənbədən icra üçün defolt DƏYİŞMİR (`python -m src.main` →
        # yoxlama): CI məhz bu davranışa arxalanır və modul başlığında
        # sənədləşdirilib. `--check`/`--strict` isə paketdə də açıq şəkildə
        # yoxlama yolunu seçir — diaqnostika üçün lazımdır.
        # ------------------------------------------------------------------
        if args.gui or (is_frozen() and not (args.check or args.strict)):
            return _run_gui(args)
        bus = get_event_bus()
        _register_audit_listener(bus)
        container = build_container(event_bus=bus)
        return summarize(run_self_check(container, strict=args.strict))
    except KompasOSError as exc:
        get_logger(__name__, channel=LogChannel.ERROR).critical(
            "STARTUP_FAILED", extra=exc.to_dict()
        )
        # `2` = İŞƏ DÜŞMƏ/BAZA XƏTASI — YALNIZ bu məna. Təsdiq-tələbi əvvəllər
        # eyni kodu qaytarırdı və skript ikisini ayırd edə bilmirdi; o məna indi
        # `console.EXIT_CONFIRMATION_REQUIRED`-a (4) köçürülüb. Bax
        # `docs/cli_reference.md` §3 və `console.py`-dakı çıxış kodu bloku.
        return EXIT_STARTUP_ERROR


if __name__ == "__main__":
    sys.exit(main())
