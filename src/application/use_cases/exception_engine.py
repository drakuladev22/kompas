"""VAHİD İSTİSNA MOTORU (#9, kompasos11.md Faza 3) — qayda-qeydiyyatlı dizayn.

Motor üç işi görür və BAŞQA HEÇ NƏ etmir:

    1. Reyestrdəki qaydaları işlədir (`run`);
    2. Tapıntıları `exceptions` jurnalına yazır — təkrar qapağı, ROOT-dan
       gələn ciddiyyət defoltu, audit və bildirişlə birlikdə;
    3. Jurnalı oxuyur və statusu bağlayır (`list_open`, `mark_reviewed`,
       `dismiss`) — Faza 5-in "İstisnalar" ekranı bunları çağırır.

Aşkarlamanın MƏNTİQİ burada YOXDUR. #8-in davranış-anomaliyası hesablaması
Faza 5-də ayrıca qayda kimi yazılır və `registry.register(...)` ilə qoşulur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ RULE-REGISTRY — MOTORDA `if source == ...` ZƏNCİRİ NİYƏ RƏDD EDİLDİ
──────────────────────────────────────────────────────────────────────────────
Bu partiyada mənbə BİRDİR (kompasos11.md struktur qərarı B: #7 avtomatik
aşkarlama etmir, #25 çıxarılıb). Bir mənbə üçün ən qısa yol motorun içində
`if source == "BEHAVIOR_ANOMALY": ...` yazmaq olardı. Rədd edildi, çünki:

  * **Motor audit-kritik koddur.** `exceptions` sətri SİLİNMİR (`REVOKE
    DELETE`, migrations/018) — motorun yazdığı hər şey daimi sübutdur. `if`
    zəncirində hər YENİ mənbə bu faylı dəyişdirməyi tələb edərdi, yəni artıq
    işləyən bütün mənbələr yenidən risk altına düşərdi. Reyestrdə yeni mənbə
    motora TOXUNMUR: bir `register()` çağırışıdır.
  * **Qismən uğur mümkün olur.** Zəncirdə bir `elif`-in istisnası bütün icranı
    aparardı; reyestrdə hər qayda ayrı vahiddir (bax `run()` daxilindəki
    təcridetmə izahı).
  * **DB də eyni qərarı verib.** `exceptions.source` sərt `CHECK`/`ENUM` deyil,
    `exception_sources` kataloquna `FOREIGN KEY`-dir. Kod tərəfində `if`
    zənciri saxlamaq iki qatı bir-birindən ayırardı: DB-yə yeni mənbə əlavə
    etmək mümkün olar, motor isə onu görməzdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA YOXDUR
──────────────────────────────────────────────────────────────────────────────
`morning_check_in.py` başlığındakı meyar tətbiq olunur: Saga YALNIZ bir
əməliyyat BİR NEÇƏ AQREQATA toxunduqda lazımdır (`LeaveVerificationUseCase.
verify_return` — status + cərimə + audit). Burada isə:

  * `run()` yalnız `exceptions` aqreqatını yaradır — başqa aqreqatın vəziyyəti
    DƏYİŞMİR (baz xətti, davamiyyət, cərimə OXUNUR, yazılmır);
  * `mark_reviewed()` / `dismiss()` tək sətrə toxunur.

Uğursuzluqda kompensasiya lazım deyil, çünki geri qaytarılası ikinci yazı
yoxdur: tranzaksiya rollback-i tam bərpadır. Hər əməliyyatı Saga-ya salmaq
reconciliation növbəsini mənasız yükləyərdi (SEC-003).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA `FeatureModule` AÇARI YOXDUR
──────────────────────────────────────────────────────────────────────────────
Aç/bağla qapısı ARTIQ mövcuddur və daha dəqiqdir: `exception_sources.
is_active`. O, mənbə-səviyyəlidir (bir qaydanı söndürmək digərlərini
söndürmür), Root tərəfindən idarə olunur və retroaktiv DEYİL — söndürmə
yalnız YENİ istisnanın yaranmasını bloklayır, mövcud sətirlər axınını
tamamlayır (migrations/018, `is_active` şərhi). Ona görə yoxlama YARADAN
metoddadır (`run`), emal edən metodlarda (`mark_reviewed`, `dismiss`) YOX —
söndürülmüş mənbənin açıq istisnaları da nəzərdən keçirilə bilməlidir, əks
halda onlar əbədi `OPEN` qalardı.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from src.domain.entities.exception_record import ExceptionRecord
from src.domain.exception_rules import ExceptionRuleRegistry
from src.domain.interfaces.ports import (
    AuditTrail,
    Clock,
    ExceptionRepository,
    ExceptionRule,
    ExceptionSourceCatalog,
    Notifier,
    SystemLimits,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.exception_signals import (
    ExceptionFinding,
    ExceptionSeverity,
    ExceptionSource,
    ExceptionStatus,
    RuleEvaluationContext,
)
from src.domain.value_objects.identifiers import (
    ExceptionId,
    StoreId,
    TenantId,
    new_exception_id,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Faza 2-də kataloqa əlavə edilmiş flag (migrations/021).
VIEW_EXCEPTIONS_FLAG = "can_view_exceptions"


class ExceptionEngineError(KompasOSError):
    """İstisna Motorunun əməliyyatı aparıla bilmədi."""

    user_message = "Əməliyyat mövcud vəziyyətdə mümkün deyil."


class ExceptionPermissionError(ExceptionEngineError):
    """İstisnalara baxmaq/qərar vermək üçün səlahiyyət yoxdur."""

    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


# --------------------------------------------------------------------------- #
# İcra hesabatı və ekran oxu-modeli
#
# Bunlar TƏTBİQ QATININ strukturlarıdır və qəsdən `ports.py`-da DEYİL: onları
# domenə qoymaq domen → tətbiq asılılığı yaradardı (`ReportFactProvider` ilə
# eyni qayda, CLAUDE.md bölmə 3).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RuleOutcome:
    """Bir qaydanın bir icradakı nəticəsi."""

    source_code: str
    rule_name_az: str
    created: int = 0
    #: `dedupe_key` ilə artıq mövcud olduğu üçün yazılmayanlar.
    skipped_duplicate: int = 0
    #: Mənbə kataloqda söndürülüb (`is_active = FALSE`).
    skipped_inactive: bool = False
    #: Tavan (`EXCEPTION_MAX_FINDINGS_PER_RULE`) səbəbindən atılanlar.
    dropped_over_limit: int = 0
    #: Qayda istisna atdı və ya mənbəsi kataloqda yoxdur — icra DAVAM ETDİ.
    error_az: str | None = None

    @property
    def failed(self) -> bool:
        return self.error_az is not None


@dataclass(frozen=True)
class EngineRunReport:
    """Motorun bir icrasının yekunu — planlaşdırılmış işin log sətri."""

    tenant_id: TenantId
    started_at: datetime
    outcomes: tuple[RuleOutcome, ...] = ()

    @property
    def created_total(self) -> int:
        return sum(outcome.created for outcome in self.outcomes)

    @property
    def duplicate_total(self) -> int:
        return sum(outcome.skipped_duplicate for outcome in self.outcomes)

    @property
    def failed_rules(self) -> tuple[str, ...]:
        return tuple(o.source_code for o in self.outcomes if o.failed)

    @property
    def evaluated_rules(self) -> int:
        return len(self.outcomes)


@dataclass(frozen=True)
class ExceptionView:
    """ "İstisnalar" ekranının bir sətri (Faza 5 GUI-si bunu göstərir).

    Mənbənin ADI burada var, çünki ekran badge göstərir və mətn BAZADAN
    gəlməlidir — ekran öz ad məkanını qursaydı, kataloqdakı redaktə
    görünməzdi (`menu.py` başlığındakı qüsur növü).
    """

    exception_id: ExceptionId
    source_code: str
    source_name_az: str
    employee_id: str
    store_id: str
    detail: str
    severity: str
    status: str
    created_at: datetime
    context: dict[str, object] = field(default_factory=dict)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None


class ExceptionEngineUseCase:
    """Qaydaları işlədən, jurnalı yazan və oxuyan vahid motor."""

    def __init__(
        self,
        *,
        exceptions: ExceptionRepository,
        sources: ExceptionSourceCatalog,
        registry: ExceptionRuleRegistry,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._exceptions = exceptions
        self._sources = sources
        self._registry = registry
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------ genişlənmə -------------------------------- #

    def register_rule(self, rule: ExceptionRule) -> str:
        """Qaydanı motora bağlayır — GENİŞLƏNMƏ NÖQTƏSİ.

        Faza 5 (və gələcək hər mənbə) yalnız bunu çağırır; motorun kodu
        toxunulmaz qalır. İkiqat qeydiyyat `DuplicateExceptionRuleError`
        atır (bax `ExceptionRuleRegistry.register`).
        """
        return self._registry.register(rule)

    @property
    def registered_sources(self) -> tuple[str, ...]:
        """Qeydiyyatdan keçmiş mənbə kodları — icra sırası ilə."""
        return self._registry.source_codes()

    # -------------------------------- icra ----------------------------------- #

    def run(self, *, tenant_id: TenantId, now: datetime | None = None) -> EngineRunReport:
        """Bütün qeydiyyatlı qaydaları işlədib tapıntıları jurnala yazır.

        Planlaşdırılmış iş (gecəlik) və ROOT panelindəki "indi işlət" düyməsi
        eyni metodu çağırır — iki ayrı yol iki ayrı davranış riski yaradardı.

        SƏLAHİYYƏT QEYDİ: burada `_require_view` YOXDUR və bu qəsdəndir. `run`
        istifadəçi əməliyyatı deyil, planlaşdırılmış sistem işidir; aktoru
        yoxdur (`audit.actor_id = None`). Onu bir flag-ə bağlamaq gecə
        işləyən cron-a süni "istifadəçi" uydurmağı tələb edərdi.
        """
        started_at = now or self._clock.now()
        # Limitlər BİR DƏFƏ oxunur: uzun icra ərzində Root dəyəri dəyişsə,
        # eyni gecənin tapıntıları müxtəlif həddlərlə hesablanardı.
        snapshot = self._limits.all_for(tenant_id)
        context = RuleEvaluationContext(tenant_id=tenant_id, as_of=started_at, limits=snapshot)
        max_per_rule = self._limit_int(snapshot, SystemLimitKey.EXCEPTION_MAX_FINDINGS_PER_RULE)
        notify_floor = ExceptionSeverity.parse(
            snapshot.get(SystemLimitKey.EXCEPTION_NOTIFY_MIN_SEVERITY.value),
            fallback=ExceptionSeverity.parse(
                DEFAULT_LIMITS[SystemLimitKey.EXCEPTION_NOTIFY_MIN_SEVERITY],
                fallback=ExceptionSeverity.HIGH,
            ),
        )

        outcomes: list[RuleOutcome] = []
        for rule in self._registry.rules():
            outcomes.append(
                self._run_one(
                    rule,
                    context=context,
                    max_per_rule=max_per_rule,
                    notify_floor=notify_floor,
                )
            )

        report = EngineRunReport(
            tenant_id=tenant_id, started_at=started_at, outcomes=tuple(outcomes)
        )
        _log.info(
            "EXCEPTION_ENGINE_RUN",
            extra={
                "tenant_id": str(tenant_id),
                "qayda_sayi": report.evaluated_rules,
                "yaradilan": report.created_total,
                "tekrar": report.duplicate_total,
                "ugursuz": list(report.failed_rules),
            },
        )
        return report

    def _run_one(
        self,
        rule: ExceptionRule,
        *,
        context: RuleEvaluationContext,
        max_per_rule: int,
        notify_floor: ExceptionSeverity,
    ) -> RuleOutcome:
        """Tək qaydanı işlədir — istisnası ÖZÜNDƏ QALIR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BİR QAYDANIN ÇÖKMƏSİ İCRANI DAYANDIRMIR
        ──────────────────────────────────────────────────────────────────────
        Motor gecəlik planlaşdırılmış işdir. Qüsurlu qayda bütün icranı
        aparsaydı, HƏMİN GECƏ heç bir mənbədən heç bir tapıntı yaranmazdı —
        yəni yeni qoşulan tək bir qayda BÜTÜN aşkarlama qatını sükutla
        söndürərdi. Ona görə hər qayda təcrid edilir: xəta hesabata düşür,
        log-a yazılır, digər qaydalar işləməyə davam edir.

        TƏCRİD YALNIZ `evaluate()`-i əhatə EDİR. Repo yazısı və audit
        çağırışı BLOKUN XARİCİNDƏDİR və istisnaları YUXARI ÇIXIR:
          * audit yazısı istisna udmur (CLAUDE.md §5) — udulsaydı, "məcburi"
            olan bir şey sükutla buraxılmış olardı;
          * yazı uğursuzluğu qayda qüsuru deyil, infrastruktur nasazlığıdır və
            tranzaksiyanın tam geri qaytarılmasını tələb edir.
        """
        source_code = rule.source_code.strip().upper()
        rule_name = rule.name_az

        source = self._sources.get(context.tenant_id, source_code)
        if source is None:
            # FAIL-CLOSED: kataloqda olmayan mənbə üçün sətir yazılsaydı,
            # `FOREIGN KEY` onsuz da rədd edərdi — lakin o zaman BÜTÜN
            # tranzaksiya çökərdi. Burada dayanmaq digər qaydaları qoruyur.
            _log.error(
                "EXCEPTION_RULE_SOURCE_MISSING",
                extra={"source_code": source_code, "rule": rule_name},
            )
            return RuleOutcome(
                source_code=source_code,
                rule_name_az=rule_name,
                error_az=f"'{source_code}' mənbəyi kataloqda yoxdur",
            )

        if not source.is_active:
            return RuleOutcome(
                source_code=source_code, rule_name_az=rule_name, skipped_inactive=True
            )

        try:
            findings = list(rule.evaluate(context))
        # GENİŞ `except` QƏSDƏNDİR: qaydanın hansı istisnanı atacağını motor
        # bilə bilməz (o, tamamilə kənar koddur) və məhz onu təcrid etmək bu
        # blokun məqsədidir — bax metodun docstring-i.
        except Exception as exc:
            _log.error(
                "EXCEPTION_RULE_FAILED",
                extra={
                    "source_code": source_code,
                    "rule": rule_name,
                    "error": str(exc),
                },
            )
            return RuleOutcome(
                source_code=source_code,
                rule_name_az=rule_name,
                error_az=f"Qayda icra edilə bilmədi: {exc}",
            )

        dropped = max(0, len(findings) - max_per_rule)
        if dropped:
            _log.warning(
                "EXCEPTION_RULE_OVER_LIMIT",
                extra={
                    "source_code": source_code,
                    "tapinti": len(findings),
                    "hedd": max_per_rule,
                },
            )
        created = 0
        duplicates = 0
        for finding in findings[:max_per_rule]:
            if self._persist(finding, source=source, context=context, notify_floor=notify_floor):
                created += 1
            else:
                duplicates += 1

        return RuleOutcome(
            source_code=source_code,
            rule_name_az=rule_name,
            created=created,
            skipped_duplicate=duplicates,
            dropped_over_limit=dropped,
        )

    def _persist(
        self,
        finding: ExceptionFinding,
        *,
        source: ExceptionSource,
        context: RuleEvaluationContext,
        notify_floor: ExceptionSeverity,
    ) -> bool:
        """Tapıntını jurnala yazır. Təkrardırsa `False` qaytarır."""
        if finding.dedupe_key is not None:
            existing = self._exceptions.find_by_dedupe(
                context.tenant_id, source=source.code, dedupe_key=finding.dedupe_key
            )
            if existing is not None:
                return False

        # Ciddiyyət qaydadan gəlmirsə mənbənin ROOT-dan idarə olunan defoltu
        # tətbiq olunur — kodda sabit ciddiyyət YOXDUR (migrations/018).
        severity = finding.severity or source.default_severity
        record = ExceptionRecord.from_finding(
            finding,
            exception_id=new_exception_id(),
            tenant_id=context.tenant_id,
            source=source.code,
            severity=severity,
            created_at=context.as_of,
        )
        self._exceptions.save(record)
        self._audit.record(
            tenant_id=context.tenant_id,
            # Aktor YOXDUR: istisnanı insan deyil, qayda yaradır.
            actor_id=None,
            action="EXCEPTION_RAISED",
            entity_type="exceptions",
            entity_id=record.id,
            after_state={
                "source": record.source,
                "employee_id": str(record.employee_id),
                "store_id": str(record.store_id),
                "severity": record.severity.value,
                "dedupe_key": record.dedupe_key,
            },
            reason=record.detail,
        )
        if severity.at_least(notify_floor):
            self._notifier.notify(
                tenant_id=context.tenant_id,
                recipient_id=None,  # HR_Admin + mağaza rəhbərliyi
                category="EXCEPTION_RAISED",
                title_az=f"Yeni istisna: {source.name_az}",
                body_az=(
                    f"{record.detail} Ciddiyyət: {severity.value}. "
                    f"«İstisnalar» ekranında nəzərdən keçirin."
                ),
                is_critical=severity is ExceptionSeverity.CRITICAL,
            )
        self._drain(record)
        return True

    # -------------------------------- oxuma ---------------------------------- #

    def list_open(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_ids: Sequence[StoreId] | None = None,
        limit: int | None = None,
    ) -> list[ExceptionView]:
        """Açıq istisnalar — "İstisnalar" ekranının məlumat mənbəyi.

        `store_ids` görünmə scopinqi üçündür: BOŞ siyahı "heç bir mağazaya
        çıxışı yoxdur" deməkdir və heç nə qaytarır (fail-safe, `pending_queue`
        ilə eyni qərar); `None` isə süzgəcsiz baxışdır.
        """
        self._require_view(tenant_id, actor, operation="LIST")
        page = limit if limit is not None else self._page_size(tenant_id)
        scope = list(store_ids) if store_ids is not None else None
        if scope is not None and not scope:
            return []

        records = self._exceptions.list_open(tenant_id, store_ids=scope, limit=page)
        catalog = {
            entry.code: entry
            # Söndürülmüş mənbə də lazımdır: onun KÖHNƏ istisnaları hələ də
            # açıq ola bilər və badge-i "naməlum" göstərmək olmaz.
            for entry in self._sources.list_all(tenant_id, include_inactive=True)
        }
        return [self._to_view(record, catalog) for record in records]

    def get_view(
        self, *, tenant_id: TenantId, actor: Employee, exception_id: ExceptionId
    ) -> ExceptionView:
        """Tək istisnanın detal görünüşü (ekranın yan paneli)."""
        self._require_view(tenant_id, actor, operation="GET")
        record = self._require_record(tenant_id, exception_id)
        catalog = {
            entry.code: entry for entry in self._sources.list_all(tenant_id, include_inactive=True)
        }
        return self._to_view(record, catalog)

    # ------------------------------ status keçidi ----------------------------- #

    def mark_reviewed(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        exception_id: ExceptionId,
        note: str | None = None,
    ) -> ExceptionRecord:
        """`[Nəzərdən Keçirildi]` — OPEN → REVIEWED."""
        return self._decide(
            tenant_id=tenant_id,
            actor=actor,
            exception_id=exception_id,
            note=note,
            target=ExceptionStatus.REVIEWED,
        )

    def dismiss(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        exception_id: ExceptionId,
        note: str,
    ) -> ExceptionRecord:
        """`[Rədd Et]` — OPEN → DISMISSED. İzah MƏCBURİDİR."""
        return self._decide(
            tenant_id=tenant_id,
            actor=actor,
            exception_id=exception_id,
            note=note,
            target=ExceptionStatus.DISMISSED,
        )

    def _decide(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        exception_id: ExceptionId,
        note: str | None,
        target: ExceptionStatus,
    ) -> ExceptionRecord:
        self._require_view(tenant_id, actor, operation=target.value)
        record = self._require_record(tenant_id, exception_id)
        decided_at = self._clock.now()
        # TƏK ACAR oxunur (`all_for` DEYİL): qərar bir sətrə aiddir və bütün
        # limit cədvəlini çəkmək lazımsız yükdür. `run()` isə əksinə — o, N
        # qaydanı bir SNAPSHOT ilə işlədir (bax `run` şərhi).
        min_note = self._limits.get_int(
            tenant_id,
            SystemLimitKey.EXCEPTION_REVIEW_NOTE_MIN_LENGTH.value,
            int(DEFAULT_LIMITS[SystemLimitKey.EXCEPTION_REVIEW_NOTE_MIN_LENGTH]),
        )

        before_status = record.status.value
        if target is ExceptionStatus.DISMISSED:
            record.dismiss(
                reviewed_by=actor.id,
                reviewed_at=decided_at,
                note=note or "",
                min_note_length=min_note,
            )
        else:
            record.mark_reviewed(
                reviewed_by=actor.id,
                reviewed_at=decided_at,
                note=note,
                min_note_length=min_note,
            )

        self._exceptions.save(record)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action=f"EXCEPTION_{target.value}",
            entity_type="exceptions",
            entity_id=record.id,
            before_state={"status": before_status},
            after_state={
                "status": record.status.value,
                "reviewed_at": decided_at.isoformat(),
                "source": record.source,
            },
            reason=record.review_note,
        )
        self._drain(record)
        return record

    # ------------------------------- köməkçi ---------------------------------- #

    def _require_view(self, tenant_id: TenantId, actor: Employee, *, operation: str) -> None:
        """`can_view_exceptions` qapısı — sükutla "heç nə etmə" DEYİL.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ OXU VƏ QƏRAR EYNİ FLAG-DƏDİR
        ──────────────────────────────────────────────────────────────────────
        `[Nəzərdən Keçirildi]` / `[Rədd Et]` düymələri məhz bu flag-lə açılan
        ekranın üzərindədir (kompasos11.md Faza 5). İkinci flag icad etmək
        icazə kataloqunu KODDAN genişləndirmək olardı — halbuki bu layihədə
        kataloq DATA-YA ƏSASLANIR (`permission_flags` cədvəli, migrations/021)
        və kodda hardcode flag siyahısı YOXDUR. Kodda mövcud olmayan bir flag
        yoxlansaydı, `has_permission()` HƏMİŞƏ `False` qaytarar və ekran
        heç kimə işləməzdi.

        İstisna bağlamaq iyerarxiya guard-ı tələb ETMİR: qərar işçinin
        səlahiyyətinə deyil, bir SİQNALA aiddir və heç bir icazə vermir/
        alır — Strict Hierarchy Guard isə məhz səlahiyyət ötürülməsi üçündür.
        """
        if actor.tenant_id != tenant_id:
            # Üçüncü izolyasiya qatı (RLS və repo `tenant_id` şərtindən sonra):
            # başqa kirayəçinin aktoru heç bir halda bu jurnala toxunmamalıdır.
            raise ExceptionPermissionError(
                "Aktor bu kirayəçiyə aid deyil",
                context={"actor_id": str(actor.id), "tenant_id": str(tenant_id)},
            )
        if not actor.has_permission(VIEW_EXCEPTIONS_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "EXCEPTION_PERMISSION_DENIED",
                extra={
                    "actor_id": str(actor.id),
                    "flag": VIEW_EXCEPTIONS_FLAG,
                    "operation": operation,
                },
            )
            raise ExceptionPermissionError(
                f"«{VIEW_EXCEPTIONS_FLAG}» səlahiyyəti yoxdur",
                context={"flag": VIEW_EXCEPTIONS_FLAG, "operation": operation},
            )

    def _require_record(self, tenant_id: TenantId, exception_id: ExceptionId) -> ExceptionRecord:
        record = self._exceptions.get(exception_id)
        if record is None or record.tenant_id != tenant_id:
            # Tapılmayan və "başqa kirayəçinin" halı EYNİ mesajı verir: fərqli
            # mətn "bu ID mövcuddur, sadəcə sizin deyil" məlumatını sızdırardı.
            raise ExceptionEngineError(
                "İstisna tapılmadı",
                user_message="Bu istisna mövcud deyil.",
                context={"exception_id": str(exception_id)},
            )
        return record

    def _page_size(self, tenant_id: TenantId) -> int:
        return self._limits.get_int(
            tenant_id,
            SystemLimitKey.EXCEPTION_PAGE_SIZE.value,
            int(DEFAULT_LIMITS[SystemLimitKey.EXCEPTION_PAGE_SIZE]),
        )

    @staticmethod
    def _limit_int(snapshot: dict[str, str], key: SystemLimitKey) -> int:
        """`system_limits` nüsxəsindən tam ədəd — yararsız dəyər defolta düşür."""
        fallback = int(DEFAULT_LIMITS[key])
        raw = snapshot.get(key.value)
        if raw is None:
            return fallback
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _to_view(record: ExceptionRecord, catalog: dict[str, ExceptionSource]) -> ExceptionView:
        source = catalog.get(record.source)
        return ExceptionView(
            exception_id=record.id,
            source_code=record.source,
            # Kataloq sətri tapılmasa kodun ÖZÜ göstərilir: boş badge ekranda
            # "mənbəsiz istisna" təəssüratı yaradardı.
            source_name_az=source.name_az if source is not None else record.source,
            employee_id=str(record.employee_id),
            store_id=str(record.store_id),
            detail=record.detail,
            severity=record.severity.value,
            status=record.status.value,
            created_at=record.created_at,
            context=dict(record.context),
            reviewed_by=str(record.reviewed_by) if record.reviewed_by is not None else None,
            reviewed_at=record.reviewed_at,
            review_note=record.review_note,
        )

    @staticmethod
    def _drain(record: ExceptionRecord) -> None:
        """Aqreqatın topladığı hadisələri YAZIDAN SONRA boşaldır.

        Hadisə avtobusu bu use case-ə injeksiya edilmir: motor çox-aqreqatlı
        saga deyil və hadisələr yalnız audit/telemetriya üçündür
        (`task_workflow._drain` ilə eyni qərar). Boşaltmaq isə vacibdir —
        eyni aqreqat obyekti təkrar işlədilsə, hadisələr yığılıb ikinci dəfə
        yayımlanardı.
        """
        record.collect_events()


__all__ = [
    "VIEW_EXCEPTIONS_FLAG",
    "EngineRunReport",
    "ExceptionEngineError",
    "ExceptionEngineUseCase",
    "ExceptionPermissionError",
    "ExceptionView",
    "RuleOutcome",
]
