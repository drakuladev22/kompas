"""Developer Panelinin konsol rejimi — Faza 3.11.

GUI (`ui.py`) və konsol EYNİ məlumat qatını (`DeveloperTenantDirectory`) və
EYNİ mətn funksiyalarını (`render_table`, `confirmation_text`) işlədir. Belə
olmasaydı, təsdiq modalındakı mətn ilə konsoldakı mətn bir gün fərqlənərdi
və "uzatdım, amma nə oldu?" sualı yaranardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İNTERAKTİV DEYİL
──────────────────────────────────────────────────────────────────────────────
`input()` gözləyən konsol nə skript, nə də test tərəfindən çağırıla bilməz.
Ona görə əməliyyat arqumentlə verilir və təhlükəli addım (`--extend`) açıq
təsdiq bayrağı (`--yes`) tələb edir — yanlışlıqla icra mümkün deyil.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.application.use_cases.developer_console import CrashDashboard, SupportInbox
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.licensing import BLOCKED_RECHECK_INTERVAL_SECONDS, EXTENSION_DAYS
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.infrastructure.licensing.developer_directory import (
        DeveloperTenantDirectory,
        TenantRow,
    )
    from src.infrastructure.persistence.connection_types import TenantDatabase
    from src.infrastructure.updates.publisher import PackageInspection, ReleasePublisher

# --------------------------------------------------------------------------- #
# ÇIXIŞ KODLARI
# --------------------------------------------------------------------------- #
#
# `2` KODUNUN İKİ MƏNASI VAR İDİ və bu, skriptləşdirməni qeyri-mümkün edirdi:
# həm «`--yes` gözlənilir, heç nə dəyişmədi», həm də `main()`-in ümumi
# `KompasOSError` qolu («işə düşmə/baza xətası») eyni `2`-ni qaytarırdı. Avtomat
# skript üçün bu fərq həlledicidir: birincidə əmri `--yes` ilə TƏKRAR etmək
# düzgün davranışdır, ikincidə isə təkrar cəhd yalnız eyni nasazlığı təkrarlayar.
#
# TƏSDİQ-TƏLƏBİ AYRILDI, `2` YERİNDƏ QALDI — geriyə uyğunluq bu istiqamətdə
# daha təhlükəsizdir: `2`-ni «xəta» kimi oxuyan mövcud skript indi də xətanı
# görür, sadəcə təsdiq-tələbi artıq ona qarışmır. Əks seçim (təsdiqi `2`-də
# saxlayıb işə düşmə xətasını köçürmək) mövcud skriptlərə səssizcə «uğur»
# görüntüsü verə bilərdi.
#
# `3` TUTULUB: kiosk nəzarətçisinin yenidən-başlatma həddi (`main._run_watchdog`).
# Ona görə növbəti sərbəst kod `4`-dür.
EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_CONFIRMATION_REQUIRED: Final[int] = 4

#: Uzatmadan sonra göstərilən "nə vaxt işə düşəcək" cümləsi — GUI və konsol
#: üçün EYNİ mənbə. Rəqəm `BLOCKED_RECHECK_INTERVAL_SECONDS`-dən gəlir ki,
#: mətn ilə klientin faktiki davranışı bir-birindən ayrılmasın.
SYNC_NOTE_AZ: Final[str] = (
    "Dəyişiklik Supabase-də artıq qüvvədədir. Bağlı quraşdırma onu "
    f"{int(BLOCKED_RECHECK_INTERVAL_SECONDS // 60)} dəqiqəyə qədər özü tutur; "
    "işləyən quraşdırmalarda növbəti sutkalıq yoxlamada görünür."
)

#: Konsol çökmə cədvəlinin sətir tavanı — GUI paneli ilə EYNİ ROOT açarından
#: (`DEVELOPER_CRASH_ROW_LIMIT`, seed: migrations/035). FALLBACK-dır və burada
#: qalıcıdır: konsol rejimi də çox-kirayəçilidir (bax `developer_panel/ui.py`
#: sabitinin şərhi — RLS kontekstsiz kirayəçi limiti oxuna bilmir).
FALLBACK_CRASH_ROW_LIMIT: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.DEVELOPER_CRASH_ROW_LIMIT])
FALLBACK_TICKET_ROW_LIMIT: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.DEVELOPER_TICKET_ROW_LIMIT]
)

#: Cədvəl sütunlarının eni — dar terminalda da oxunaqlı qalsın.
_NAME_WIDTH: Final[int] = 28
_BADGE_WIDTH: Final[int] = 18
_SEEN_WIDTH: Final[int] = 17
#: Diaqnostika bölmələrinin sütun enləri.
_CRASH_TYPE_WIDTH: Final[int] = 30
_SUBJECT_WIDTH: Final[int] = 32
_SLA_WIDTH: Final[int] = 15


def render_table(rows: Sequence[TenantRow], *, now: datetime) -> str:
    """Tenant cədvəli: şirkət adı, status-nişanı, qalan gün, son check-in."""
    if not rows:
        return "Heç bir müştəri qeydi tapılmadı."

    header = (
        f"{'ŞİRKƏT':<{_NAME_WIDTH}} {'VƏZİYYƏT':<{_BADGE_WIDTH}} "
        f"{'SON ƏLAQƏ':<{_SEEN_WIDTH}} TENANT ID"
    )
    lines = [header, "-" * (len(header) + 8)]
    for row in rows:
        marker = "!" if row.needs_attention(now) else " "
        lines.append(
            f"{_clip(row.tenant_name, _NAME_WIDTH):<{_NAME_WIDTH}} "
            f"{_clip(row.badge_az(now), _BADGE_WIDTH):<{_BADGE_WIDTH}} "
            f"{_clip(_seen(row.last_check_in_at, now), _SEEN_WIDTH):<{_SEEN_WIDTH}} "
            f"{row.tenant_id}{marker}"
        )
    attention = sum(1 for row in rows if row.needs_attention(now))
    lines.append("")
    lines.append(f"Cəmi: {len(rows)} müştəri, diqqət tələb edən: {attention} (!)")
    return "\n".join(lines)


def render_crash_dashboard(
    dashboard: CrashDashboard, *, limit: int = FALLBACK_CRASH_ROW_LIMIT
) -> str:
    """Çökmə paneli — TEZLİYƏ görə sıralanmış (bölmə 8).

    Konsol variantı GUI ilə EYNİ oxu-modeli (`CrashDashboard`) istifadə edir;
    fərq yalnız çıxış formatındadır. Ayrı hesablama olsaydı, iki panel bir gün
    fərqli prioritet göstərərdi.

    `limit` defoltu da GUI ilə EYNİ mənbədəndir (`DEVELOPER_CRASH_ROW_LIMIT`,
    `DEFAULT_LIMITS` — bax sabitin şərhi): konsolda ayrı bir "12" yazsaydıq,
    biri dəyişəndə digəri sükutla köhnələrdi.
    """
    if not dashboard.groups:
        return "Çökmə hesabatı yoxdur."

    header = f"{'XƏTA NÖVÜ':<{_CRASH_TYPE_WIDTH}} {'TƏKRAR':>7} {'QURAŞDIRMA':>11}  VERSİYA"
    lines = [header, "-" * (len(header) + 4)]
    for group in dashboard.top(limit):
        # "!" — bir neçə quraşdırmada təkrarlanır, yəni kod problemidir.
        marker = "!" if group.is_widespread else " "
        lines.append(
            f"{_clip(group.exception_type, _CRASH_TYPE_WIDTH):<{_CRASH_TYPE_WIDTH}} "
            f"{group.occurrences:>7} {group.affected_installations:>11}  "
            f"{', '.join(group.app_versions)}{marker}"
        )

    shown = min(limit, len(dashboard.groups))
    lines.append("")
    lines.append(
        f"Cəmi {dashboard.total_crashes} çökmə, {len(dashboard.groups)} qrup "
        f"({shown} göstərilir); bir neçə quraşdırmada təkrarlanan: "
        f"{len(dashboard.widespread)} (!)"
    )
    return "\n".join(lines)


def render_support_inbox(inbox: SupportInbox, *, limit: int = FALLBACK_TICKET_ROW_LIMIT) -> str:
    """Dəstək inbox-u — diqqət tələb edənlər ƏVVƏLDƏ (bölmə 8).

    `limit` defoltu GUI paneli ilə EYNİ mənbədəndir
    (`DEVELOPER_TICKET_ROW_LIMIT` — bax yuxarıdakı sabitin şərhi).
    """
    if not inbox.tickets:
        return "Dəstək müraciəti yoxdur."

    header = (
        f"{'MÜŞTƏRİ':<{_NAME_WIDTH}} {'MÖVZU':<{_SUBJECT_WIDTH}} {'İLK CAVAB':<{_SLA_WIDTH}} HƏLL"
    )
    lines = [header, "-" * (len(header) + 4)]
    for view in inbox.tickets[:limit]:
        marker = "!" if view.needs_attention else " "
        lines.append(
            f"{_clip(view.record.tenant_name, _NAME_WIDTH):<{_NAME_WIDTH}} "
            f"{_clip(view.record.subject, _SUBJECT_WIDTH):<{_SUBJECT_WIDTH}} "
            f"{_clip(view.response_sla.label_az, _SLA_WIDTH):<{_SLA_WIDTH}} "
            f"{view.resolution_sla.label_az}{marker}"
        )

    lines.append("")
    lines.append(
        f"Cəmi {len(inbox.tickets)} müraciət, diqqət tələb edən: "
        f"{inbox.attention_count} (!), ilk cavab gözləyən: "
        f"{len(inbox.awaiting_first_reply)}"
    )
    return "\n".join(lines)


def confirmation_text(rows: Sequence[TenantRow]) -> str:
    """Təsdiq modalının mətni — GUI və konsol üçün EYNİ mənbə.

    Bölmə 6 tələbi: *"təsdiq-modalı ilə: «N tenant-ın lisenziyası 30 gün
    uzadılacaq»"*. Bir tenant seçildikdə adı açıq yazılır — "1 tenant"
    ifadəsi hansı müştəri olduğunu gizlədərdi və səhv sətrə basmaq
    mümkün olardı.
    """
    if not rows:
        return "Heç bir müştəri seçilməyib."
    if len(rows) == 1:
        return (
            f"«{rows[0].tenant_name}» müştərisinin lisenziyası "
            f"{EXTENSION_DAYS} gün uzadılacaq. Davam edilsin?"
        )
    return f"{len(rows)} müştərinin lisenziyası {EXTENSION_DAYS} gün uzadılacaq. Davam edilsin?"


def tier_change_confirmation_text(row: TenantRow, target_tier: str) -> str:
    """`[Tier Dəyiş]` təsdiq modalının mətni (Faza 9.2) — GUI/konsol EYNİ.

    NƏ DƏYİŞƏCƏYİNİ AÇIQ yazır: tier dəyişikliyi yalnız sütunu yeniləmir,
    Feature Toggle defolt-dəstini də tətbiq edir. Root sonradan modulları
    öz panelindən dəyişə bilər — mətn bunu da bildirir ki, "tier-i geri
    qaytardım, amma toggle-lar qayitmadı" çaşqınlığı olmasın.
    """
    from src.domain.value_objects.licensing import (  # noqa: PLC0415
        SERVICE_TIER_LABELS,
        SERVICE_TIER_MODULE_DEFAULTS,
    )

    label = SERVICE_TIER_LABELS.get(target_tier, target_tier)
    disabled = sorted(SERVICE_TIER_MODULE_DEFAULTS.get(target_tier, frozenset()))
    lines = [
        f"«{row.tenant_name}» xidmət səviyyəsi → {label}.",
    ]
    if disabled:
        lines.append("Defolt söndürüləcək modullar: " + ", ".join(disabled) + ".")
    else:
        lines.append("Bu tier-də defolt söndürülən modul YOXDUR.")
    lines += [
        "",
        "Qeyd: Root sonrakı toggle dəyişiklikləri bu dəsti əvəz edir.",
        "Davam edilsin?",
    ]
    return "\n".join(lines)


def publish_confirmation_text(
    version: str, inspection: PackageInspection, *, is_mandatory: bool
) -> str:
    """`[Yüklə və Yayımla]` təsdiq modalının mətni — GUI və konsol üçün EYNİ.

    SHA-256 QISALDILMIŞ şəkildə göstərilir (ilk 12 simvol): tam dayceti oxuyub
    tutuşdurmaq heç kimin etmədiyi işdir, qısa prefiks isə "yenidən build etdim,
    fayl dəyişdi" halını gözlə tutmağa kifayət edir.
    """
    lines = [
        f"Versiya {version} yayımlanacaq.",
        "",
        f"Fayl:    {inspection.path.name} ({inspection.size_mb} MB)",
        f"SHA-256: {inspection.sha256[:12]}…",
    ]
    if is_mandatory:
        lines.append("Məcburi: BƏLİ — bu buraxılışdan köhnə bütün quraşdırmalar üçün.")
    if not inspection.is_signed:
        # Bu, sadə xəbərdarlıq deyil: imzasız paketi HƏR klient rədd edir
        # (fail-closed). Yayım texniki olaraq uğurlu olar, nəticə isə sıfır.
        lines += [
            "",
            "⚠ DİQQƏT: Authenticode imzası doğrulanmadı —",
            f"  {inspection.signature_error}",
            "  Klientlər bu paketi RƏDD EDƏCƏK (imzasız yenilənmə tətbiq olunmur).",
        ]
    elif inspection.publisher_subject:
        lines.append(f"Naşir:   {inspection.publisher_subject}")
    lines += ["", "Yayımdan sonra bütün tenant-lar bu versiyanı görəcək. Davam edilsin?"]
    return "\n".join(lines)


def render_audit_trail(entries: Sequence[dict[str, object]]) -> str:
    """Bir tenant üzrə lisenziya əməliyyatları tarixçəsi."""
    if not entries:
        return "Bu müştəri üçün lisenziya əməliyyatı qeydə alınmayıb."
    lines = ["TARİX              ƏMƏLİYYAT              KÖHNƏ → YENİ"]
    for entry in entries:
        performed = entry.get("performed_at")
        stamp = performed.strftime("%d.%m.%Y %H:%M") if isinstance(performed, datetime) else "—"
        old = _short_date(entry.get("old_expires_at"))
        new = _short_date(entry.get("new_expires_at"))
        lines.append(f"{stamp:<18} {entry.get('action', '')!s:<21} {old} → {new}")
    return "\n".join(lines)


def run_console(
    directory: DeveloperTenantDirectory,
    *,
    search: str = "",
    extend: str = "",
    force_version: str = "",
    confirmed: bool = False,
    now: datetime | None = None,
    publisher: ReleasePublisher | None = None,
    publish_package: str = "",
    publish_version: str = "",
    publish_notes: str = "",
    publish_mandatory: bool = False,
    show_crashes: bool = False,
    show_tickets: bool = False,
    database: TenantDatabase | None = None,
    recover_access: str = "",
    recovery_reference: str = "",
    recovery_contact: str = "",
) -> tuple[int, str]:
    """Konsol rejimini icra edir.

    Returns:
        `(çıxış_kodu, mətn)` — çağıran tərəf mətni özü çap edir ki, funksiya
        test edilə bilsin.
    """
    moment = now or datetime.now(UTC)

    if publish_package:
        return _publish(
            publisher,
            publish_package,
            publish_version,
            notes=publish_notes,
            is_mandatory=publish_mandatory,
            confirmed=confirmed,
            now=moment,
        )

    if force_version:
        return _force_version(directory, force_version, confirmed=confirmed, now=moment)

    if recover_access:
        if database is None:  # pragma: no cover - çağıran tərəf həmişə verir
            return 1, "Bərpa üçün baza bağlantısı lazımdır."
        return _recover_access(
            directory,
            database,
            recover_access,
            reference=recovery_reference,
            contact=recovery_contact,
            confirmed=confirmed,
            now=moment,
        )
    return _tenant_view_or_extend(
        directory,
        search=search,
        extend=extend,
        confirmed=confirmed,
        now=moment,
        show_crashes=show_crashes,
        show_tickets=show_tickets,
    )


def _tenant_view_or_extend(
    directory: DeveloperTenantDirectory,
    *,
    search: str,
    extend: str,
    confirmed: bool,
    now: datetime,
    show_crashes: bool,
    show_tickets: bool,
) -> tuple[int, str]:
    """Defolt yol: cədvəl/diaqnostika görünüşü, yaxud `[1 Ay Uzat]`."""
    moment = now

    view = _render_view(
        directory,
        search=search,
        now=moment,
        show_crashes=show_crashes,
        show_tickets=show_tickets,
        skip_default=bool(extend),
    )
    if view is not None:
        return view

    target = directory.get(extend)
    if target is None:
        return 1, f"Müştəri tapılmadı: {extend}"

    if not confirmed:
        # Təsdiq bayrağı olmadan HEÇ NƏ dəyişmir — mətn göstərilir və çıxılır.
        return (
            EXIT_CONFIRMATION_REQUIRED,
            f"{confirmation_text([target])}\n(Təsdiq üçün `--yes` əlavə edin.)",
        )

    result = directory.extend_one_month(extend, now=moment)
    suffix = " Müştəri yenidən aktivləşdirildi." if result.reactivated else ""
    return 0, (
        f"«{result.tenant_name}» uzadıldı: "
        f"{_short_date(result.old_expires_at)} → {_short_date(result.new_expires_at)}.{suffix}\n"
        f"{SYNC_NOTE_AZ}"
    )


def _render_view(
    directory: DeveloperTenantDirectory,
    *,
    search: str,
    now: datetime,
    show_crashes: bool,
    show_tickets: bool,
    skip_default: bool,
) -> tuple[int, str] | None:
    """YALNIZ-OXU görünüşlər — heç nə dəyişdirmir.

    Ayrı funksiya olmasının səbəbi `run_console`-un iki fərqli məsuliyyəti
    qarışdırmamasıdır: burada "nə göstərim?", orada isə "nəyi dəyişim?"
    sualına cavab verilir. `None` qayıdışı "göstəriləsi görünüş yoxdur,
    dəyişdirmə axınına keç" deməkdir.
    """
    if show_crashes:
        return 0, render_crash_dashboard(CrashDashboard.from_records(directory.crash_records()))
    if show_tickets:
        return 0, render_support_inbox(
            SupportInbox.from_records(directory.support_tickets(), now=now)
        )
    if skip_default:
        return None
    return 0, render_table(directory.list_tenants(search=search), now=now)


def _force_version(
    directory: DeveloperTenantDirectory,
    argument: str,
    *,
    confirmed: bool,
    now: datetime,
) -> tuple[int, str]:
    """`--force-version TENANT_ID=1.2.3` (boş versiya məcburiyyəti götürür)."""
    tenant_id, _, version = argument.partition("=")
    tenant_id = tenant_id.strip()
    target = directory.get(tenant_id)
    if target is None:
        return 1, f"Müştəri tapılmadı: {tenant_id}"

    version = version.strip()
    action = f"«{version}» versiyasına məcburi keçid" if version else "məcburiyyətin ləğvi"
    if not confirmed:
        return EXIT_CONFIRMATION_REQUIRED, (
            f"«{target.tenant_name}» üçün {action} tətbiq ediləcək. "
            "(Təsdiq üçün `--yes` əlavə edin.)"
        )

    directory.set_forced_version(tenant_id, version, now=now)
    return 0, f"«{target.tenant_name}»: {action} tətbiq edildi."


def _recovery_problem(
    directory: DeveloperTenantDirectory,
    tenant_id: str,
    username: str,
    reference: str,
    contact: str,
) -> str | None:
    """Bərpanın giriş şərtləri — hamısı MƏCBURİ, `None` = problem yoxdur."""
    if not username:
        return "İstifadəçi adı göstərilməyib: `--recover-access TENANT_ID=username`"
    if directory.get(tenant_id) is None:
        return f"Müştəri tapılmadı: {tenant_id}"
    if not reference.strip():
        return "`--recovery-reference` MƏCBURİDİR (kimlik təsdiqinin izi)."
    if not contact.strip():
        return "`--recovery-contact` MƏCBURİDİR (təsdiqlənmiş şirkət əlaqəsi)."
    return None


def _recover_access(
    directory: DeveloperTenantDirectory,
    database: TenantDatabase,
    argument: str,
    *,
    reference: str,
    contact: str,
    confirmed: bool,
    now: datetime,
) -> tuple[int, str]:
    """`--recover-access TENANT_ID=username` — bölmə 2 son tədbiri.

    QƏSDƏN YALNIZ KONSOLDADIR, GUI düyməsi deyil. Prosedur tenant-ın
    `employees` cədvəlinə yazır, halbuki bölmə 8 hazırlayıcı tərəf üçün
    "heç bir halda işçi PII-sinə uzaqdan çıxış YOXDUR" deyir. Düymə şəklində
    hər zaman göz önündə duran bir yol bu sərhədi gündəlik hala gətirərdi;
    dörd məcburi arqument + `--yes` tələb edən əmr isə şüurlu qərar tələb edir.

    Bütün qapılar `EmergencyAccessRecoveryUseCase`-dədir və burada TƏKRAR
    YAZILMIR — burada yalnız tərkib (composition) var.
    """
    from src.application.use_cases.authentication import (  # noqa: PLC0415
        EmergencyAccessRecoveryUseCase,
        TenantContact,
    )
    from src.domain.value_objects.credentials import Username  # noqa: PLC0415
    from src.domain.value_objects.identifiers import TenantId  # noqa: PLC0415
    from src.infrastructure.config.limits import InfrastructureLimits  # noqa: PLC0415
    from src.infrastructure.notifications.notifier import PostgresNotifier  # noqa: PLC0415
    from src.infrastructure.security.hashing import HashingService  # noqa: PLC0415
    from src.infrastructure.timekeeping.clock import SystemClock  # noqa: PLC0415
    from src.shared.security_events import FailSoftSecurityEventRecorder  # noqa: PLC0415

    tenant_id, _, username = argument.partition("=")
    tenant_id, username = tenant_id.strip(), username.strip()

    problem = _recovery_problem(directory, tenant_id, username, reference, contact)
    if problem is not None:
        return 1, problem

    target_tenant = directory.get(tenant_id)
    assert target_tenant is not None  # `_recovery_problem` yoxlayıb
    remaining = directory.active_admin_count(tenant_id)
    if not confirmed:
        return EXIT_CONFIRMATION_REQUIRED, (
            f"«{target_tenant.tenant_name}» üçün TƏCİLİ GİRİŞ BƏRPASI.\n"
            f"Hədəf hesab: {username} · qalan aktiv admin: {remaining}\n"
            f"İstinad: {reference.strip()}\n"
            "Əməliyyat tam audit-lənir və tenant-a bildiriş göndərilir.\n"
            "(Təsdiq üçün `--yes` əlavə edin.)"
        )

    identifier = TenantId(uuid.UUID(tenant_id))
    with database.unit_of_work(identifier) as uow:
        employee = uow.employees.get_by_username(identifier, Username(username))
        if employee is None:
            return 1, f"Hesab tapılmadı: {username}"

        # ROOT pəncərəsi HƏDƏF kirayəçinin öz sətirlərindən oxunur: bərpa
        # konkret quraşdırmaya aiddir və `identifier` məlumdur, yəni burada
        # (panelin qalan hissəsindən fərqli olaraq) çox-kirayəçi maneəsi
        # YOXDUR. Açıq `uow` işlədilir — ikinci bağlantı lazımsızdır.
        limits = InfrastructureLimits(limits=uow.repository("limits"), tenant_id=identifier)
        use_case = EmergencyAccessRecoveryUseCase(
            employees=uow.employees,
            # Müvəqqəti şifrənin uzunluq siyasəti (`PASSWORD_MIN_LENGTH`)
            # ROOT-dandır — ötürülməsəydi fallback işləyər və kirayəçinin
            # seçdiyi siyasət tətbiq olunmazdı.
            hashing=HashingService(limits=limits),
            clock=SystemClock(),
            audit=uow.audit,
            # Bildiriş cəhd/gözləmə cədvəli də həmin pəncərədən.
            notifier=PostgresNotifier(database, limits=limits),
            # SEC-7 — SARILMIŞ forma MƏCBURİDİR (bax `app.py::
            # _SessionScopedLogin.login` eyni şərhi). Bu əməliyyat artıq
            # SON TƏDBİRDİR (bölmə 2) — `security_events` yazısının
            # uğursuzluğu bərpanın ÖZÜNÜ dayandırmamalıdır, sadəcə
            # `security.log`-a düşməlidir.
            security_events=FailSoftSecurityEventRecorder(uow.repository("security_events")),
        )
        credential = use_case.recover(
            tenant_id=identifier,
            target=employee,
            developer_reference=reference.strip(),
            active_admin_count=remaining,
            tenant_contact=TenantContact(
                email=target_tenant.company_contact_email,
                phone=target_tenant.company_contact_phone or None,
            ),
            verified_contact=contact.strip(),
        )
        uow.commit()

    # SIRA MƏCBURİDİR: şifrə YALNIZ commit-dən SONRA çap olunur. `recover()`
    # heşi, audit sətrini və bildirişi EYNİ tranzaksiyaya yazır (CLAUDE.md §5:
    # audit yazısı istisna udmur) — hər hansı biri uğursuz olarsa `uow` bu
    # bloku rollback ilə tərk edir və bu sətrə heç vaxt çatılmır. Əks sıra
    # (əvvəl göstər, sonra yaz) administratora İŞLƏMƏYƏN bir şifrə verərdi.
    return 0, (
        f"«{target_tenant.tenant_name}» — «{username}» üçün müvəqqəti şifrə:\n"
        f"    {credential.plaintext}\n"
        "İstifadəçi ilk girişdə onu MƏCBURİ dəyişəcək. Şifrəni yalnız "
        "kimliyi təsdiqlənmiş şəxsə, təhlükəsiz kanalla verin."
    )


def _publish(
    publisher: ReleasePublisher | None,
    package: str,
    version: str,
    *,
    notes: str,
    is_mandatory: bool,
    confirmed: bool,
    now: datetime,
) -> tuple[int, str]:
    """`--publish FAYL --publish-version 1.4.0 [--publish-mandatory] --yes`.

    `--yes` olmadan HEÇ NƏ yüklənmir: yalnız faylın faktları (ölçü, SHA-256,
    imza) göstərilir. Bu, GUI-dəki təsdiq modalının konsol qarşılığıdır və
    eyni funksiyadan (`publish_confirmation_text`) qidalanır.
    """
    if publisher is None:
        return 1, (
            "Yayım konfiqurasiya edilməyib: `KOMPASOS_SUPABASE_URL` və "
            "`KOMPASOS_SUPABASE_SERVICE_ROLE_KEY` təyin edin."
        )
    if not version.strip():
        return 1, "Versiya nömrəsi tələb olunur: `--publish-version 1.4.0`."

    try:
        inspection = publisher.inspect(Path(package))
    except KompasOSError as exc:
        return 1, f"Fayl yoxlanmadı: {exc.user_message}"

    if not confirmed:
        return EXIT_CONFIRMATION_REQUIRED, (
            publish_confirmation_text(version, inspection, is_mandatory=is_mandatory)
            + "\n(Təsdiq üçün `--yes` əlavə edin.)"
        )

    try:
        result = publisher.publish(
            Path(package),
            version,
            release_notes=notes,
            is_mandatory=is_mandatory,
            inspection=inspection,
            now=now,
        )
    except KompasOSError as exc:
        return 1, f"Yayım alınmadı: {exc.user_message}"

    return 0, (
        f"Yayımlandı: {result.version} → {result.storage_path} "
        f"({inspection.size_mb} MB, sha256 {result.sha256[:12]}…). "
        "Bütün tenant-lar növbəti yoxlamalarında görəcək."
    )


def _seen(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "heç vaxt"
    days = (now - moment).days
    if days <= 0:
        return "bu gün"
    if days == 1:
        return "dünən"
    return f"{days} gün əvvəl"


def _short_date(value: object) -> str:
    return value.strftime("%d.%m.%Y") if isinstance(value, datetime) else "—"


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


__all__ = [
    "EXIT_CONFIRMATION_REQUIRED",
    "EXIT_FAILED",
    "EXIT_OK",
    "SYNC_NOTE_AZ",
    "confirmation_text",
    "publish_confirmation_text",
    "render_audit_trail",
    "render_crash_dashboard",
    "render_support_inbox",
    "render_table",
    "run_console",
]
