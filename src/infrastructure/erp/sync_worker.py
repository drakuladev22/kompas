"""Server-üzrə izolyasiya olunmuş sinxronizasiya worker-ləri — Faza 3.10.

Spesifikasiya bölmə 7: *"`sync_worker` bütün aktiv serverlər üzrə **paralel**
işləyir; bir serverin bağlantı problemi digər serverlərin sinxronizasiyasını
dayandırmır (izolyasiya olunmuş worker-lər)."*

──────────────────────────────────────────────────────────────────────────────
İZOLYASİYA NƏ DEMƏKDİR — VƏ NƏ DEMƏK DEYİL
──────────────────────────────────────────────────────────────────────────────
İzolyasiya BURADA "bir serverin xətası digərinin nəticəsinə TƏSİR ETMİR"
deməkdir. Bunun üçün hər server öz `try` sərhədində işləyir və xəta HEÇ VAXT
yuxarı qalxmır — `SyncReport` içində qeyd olunur. `parallel_sync()` bir
istisna atsaydı, siyahının qalan hissəsi həmin dövrdə heç oxunmazdı.

İzolyasiya AYRI PROSES demək DEYİL. Ayrı proses yalnız çökmə (segfault) və
ya qeyri-məhdud yaddaş istehlakı riski olduqda dəyər verir; burada iş HTTP
sorğusu + SQL yazmadır, hər ikisi I/O-bağlıdır. Thread-lər eyni izolyasiyanı
proses başlatma xərci və IPC mürəkkəbliyi olmadan verir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ XAL HESABLANMIR
──────────────────────────────────────────────────────────────────────────────
Bu qat satışı YAZIR, xal VERMİR. `points_ledger`, 6 aylıq sıfırlama və
mükafat mübadiləsi Faza 6-nın işidir (spesifikasiya bölmə 10, Faza 6, bənd
1). Xalı burada hesablasaydıq, xal qaydası dəyişəndə (məs. əmsal) həm bu
modul, həm Faza 6 modulu dəyişməli olardı.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.erp import (
    DEFAULT_PAGE_SIZE,
    ErpError,
    MatchConfidence,
)
from src.infrastructure.config.limits import InfrastructureLimits, fallback_int
from src.infrastructure.erp.matching import SalesMatcher
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from decimal import Decimal

    from src.domain.interfaces.ports import ErpConnectorFactory, ErpServerRegistry
    from src.domain.value_objects.erp import ErpServer, MatchResult
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        SalesTransactionId,
        StoreId,
        TenantId,
    )
    from src.infrastructure.erp.matching import MatchDirectory
    from src.infrastructure.erp.sales import SalesTransactionRepository

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: HƏR İKİSİ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`ERP_SYNC_MAX_PARALLEL_SERVERS`, `ERP_SYNC_MAX_PAGES_PER_RUN`;
#: seed: migrations/032). Bu ədədlər yalnız ROOT portu əlçatmaz olduqda işə düşür.
#:
#: Eyni anda neçə server sinxronlaşdırılır. Mağaza PC-si zəif ola bilər və
#: hər worker bir HTTP bağlantısı + bir DB bağlantısı tutur; DB pool-unun
#: maksimumu 8-dir (`DB_POOL_MAX_SIZE`), ona görə hədd ondan aşağıdır — sync
#: bütün pool-u tutub istifadəçi əməliyyatlarını gözlətməsin. İKİSİ DƏ İNDİ
#: ROOT-dan idarə olunur: hovuzu böyüdən müəssisə paralelliyi də artıra bilməli,
#: zəif kioskda isə hər ikisini azalda bilməlidir.
FALLBACK_MAX_PARALLEL_SERVERS: Final[int] = fallback_int(
    SystemLimitKey.ERP_SYNC_MAX_PARALLEL_SERVERS
)

#: Bir dövrdə bir serverdən neçə səhifə oxunur. İlk sinxronizasiyada 1C-də
#: illərlə sənəd ola bilər; hamısını bir dövrdə çəkmək dövrü saatlarla
#: uzadardı. Qalan sənədlər növbəti dövrdə davam edir (kursor saxlanılır).
FALLBACK_MAX_PAGES_PER_RUN: Final[int] = fallback_int(SystemLimitKey.ERP_SYNC_MAX_PAGES_PER_RUN)

#: Sinxronizasiyaya VERİLMƏYƏN bağlantı sayı (SAAS-7, bax `_max_parallel_value`).
#:
#: Root parametri DEYİL, «bir istifadəçi + bir fon oxuması» tərifidir: dəyəri
#: Root-a versəydik, onu sıfıra endirmək paralelliyin hovuzu TAM tutmasına
#: icazə verərdi — yəni klampın bütün mənası itərdi. Hovuzun ÖZÜ isə Root
#: açarıdır (`DB_POOL_MAX_SIZE`) — tənzimləmə oradan aparılır.
_POOL_HEADROOM_CONNECTIONS: Final[int] = 2


@dataclass
class SyncReport:
    """Bir serverin bir dövrünün nəticəsi."""

    server_id: str
    server_name: str
    ok: bool = True
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    exact_matches: int = 0
    low_confidence: int = 0
    unassigned: int = 0
    pages: int = 0
    #: Bu dövrdə YENİ sətirlərdən verilən xal sayı (bölmə 6).
    points_awarded: int = 0
    error: str | None = None

    @property
    def needs_review(self) -> int:
        """ "Şübhəli Uyğunlaşma" növbəsinə düşən sətir sayı (bölmə 6)."""
        return self.low_confidence + self.unassigned


@dataclass
class SyncCycleReport:
    """Bütün serverlərin bir dövrü."""

    started_at: datetime
    finished_at: datetime
    servers: list[SyncReport] = field(default_factory=list)

    @property
    def failed(self) -> list[SyncReport]:
        return [report for report in self.servers if not report.ok]

    @property
    def total_inserted(self) -> int:
        return sum(report.inserted for report in self.servers)

    @property
    def all_ok(self) -> bool:
        return not self.failed


@runtime_checkable
class PointsAwarder(Protocol):
    """Satışdan xal yazan tərəf — `SalesPointsUseCase` bunu ödəyir.

    Protokol olaraq təyin edilir ki, `infrastructure` qatı `application`
    qatının konkret sinfinə bağlanmasın: sync worker yalnız "xal yaz"
    əməliyyatını tanıyır, xal qaydasını bilmir.
    """

    def award_for_sale(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        transaction_id: SalesTransactionId,
        gross_amount: Decimal,
        confidence: MatchConfidence,
    ) -> object | None: ...


class SalesSyncService:
    """BİR serveri sinxronlaşdırır. Xəta atır — izolyasiya `ErpSyncManager`-dədir."""

    def __init__(
        self,
        *,
        servers: ErpServerRegistry,
        connectors: ErpConnectorFactory,
        sales: SalesTransactionRepository,
        directory: MatchDirectory,
        tenant_id: TenantId | None = None,
        points: PointsAwarder | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            max_pages: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.
        """
        self._servers = servers
        self._tenant_id = tenant_id
        self._connectors = connectors
        self._sales = sales
        self._limits = limits or InfrastructureLimits()
        self._matcher = SalesMatcher(directory, limits=self._limits)
        # `None` → xal modulu qoşulmayıb (məs. Feature Toggle söndürülüb).
        # Sinxronizasiya bundan ASILI DEYİL: satış sətirləri yenə yazılır,
        # sadəcə xal verilmir. Əks halda xal modulunun söndürülməsi bütün
        # 1C sinxronizasiyasını dayandırardı.
        self._points = points
        self._page_size = page_size
        self._explicit_max_pages = max_pages

    def _max_pages_value(self) -> int:
        """Dövr başına səhifə tavanı — DÖVRÜN BAŞINDA oxunur.

        İlk sinxronizasiyada admin tavanı müvəqqəti qaldırıb geridə qalmış
        arxivi tez çəkmək istəyə bilər; yenidən başlatma tələb etmək bu
        əməliyyatı lazımsız yerə çətinləşdirərdi.
        """
        if self._explicit_max_pages is not None:
            return self._explicit_max_pages
        return self._limits.int_of(SystemLimitKey.ERP_SYNC_MAX_PAGES_PER_RUN)

    def _award_points(self, written: Sequence[tuple[SalesTransactionId, MatchResult]]) -> int:
        """Yeni yazılmış sətirlərə xal verir (bölmə 6).

        Xəta UDULUR və loglanır: xal qazandırma satışın yazılmasından SONRA
        gəlir və onu geri qaytarmamalıdır — satış faktı 1C-dən gəlir və
        həqiqətdir, xal isə törəmə hesablamadır. Uğursuzluq halında sətir
        yenə növbədə görünür və əl ilə düzəldilə bilər.
        """
        if self._points is None or self._tenant_id is None:
            return 0

        awarded = 0
        for transaction_id, result in written:
            if result.employee_id is None or result.store_id is None:
                continue
            try:
                entry = self._points.award_for_sale(
                    tenant_id=self._tenant_id,
                    employee_id=result.employee_id,
                    store_id=result.store_id,
                    transaction_id=transaction_id,
                    gross_amount=result.record.gross_amount,
                    confidence=result.confidence,
                )
            except Exception:
                _log.exception(
                    "POINTS_AWARD_FAILED",
                    extra={"transaction_id": str(transaction_id)},
                )
                continue
            if entry is not None:
                awarded += 1
        return awarded

    def sync(self, server: ErpServer, *, now: datetime | None = None) -> SyncReport:
        moment = now or datetime.now(UTC)
        report = SyncReport(server_id=str(server.id), server_name=server.server_name)
        server_id = server.id

        self._servers.mark_sync_started(server_id, now=moment)
        cursor = server.cursor

        connector = self._connectors.for_server(server_id)
        try:
            for _ in range(self._max_pages_value()):
                batch = connector.fetch_sales(cursor, page_size=self._page_size)
                if not batch:
                    break

                report.pages += 1
                report.fetched += len(batch)
                results = [self._matcher.match(record, server_id) for record in batch]
                _tally(report, results)

                written = self._sales.insert_batch_returning(server_id, results)
                report.inserted += len(written)
                report.duplicates += len(results) - len(written)
                report.points_awarded += self._award_points(written)

                cursor = cursor.advanced(batch)
                # Kursor HƏR səhifədən sonra yazılır: dövr ortasında çökmə
                # baş verərsə növbəti dövr oxunmuş səhifələri təkrarlamır.
                self._servers.record_success(server_id, cursor, now=moment)

                if len(batch) < self._page_size:
                    break
        finally:
            connector.close()

        if report.pages == 0:
            # Yeni sənəd yoxdur — bu da UĞURLU dövrdür. `record_success`
            # çağırılır ki, `last_successful_sync` təzələnsin, əks halda
            # sakit bir gündən sonra Health Monitor serveri `STALE` sayardı.
            self._servers.record_success(server_id, cursor, now=moment)

        _log.info(
            "ERP_SERVER_SYNCED",
            extra={
                "server_id": report.server_id,
                "server_name": report.server_name,
                "fetched": report.fetched,
                "inserted": report.inserted,
                "duplicates": report.duplicates,
                "needs_review": report.needs_review,
            },
        )
        if report.needs_review:
            # Bölmə 6: şübhəli uyğunlaşma insana göndərilir — sükutla
            # qalsaydı işçinin xalı səhv qalardı və heç kim bilməzdi.
            _audit_log.info(
                "ERP_SALES_NEED_REVIEW",
                extra={
                    "server_id": report.server_id,
                    "low_confidence": report.low_confidence,
                    "unassigned": report.unassigned,
                },
            )
        return report


class ErpSyncManager:
    """Bütün sinxronlaşdırıla bilən serverləri PARALEL və İZOLYASİYA ilə işlədir.

    ──────────────────────────────────────────────────────────────────────────
    HƏR SERVERİN ÖZ RİTMİ VAR (1c.md — fayl mübadiləsi)
    ──────────────────────────────────────────────────────────────────────────
    Dövr çağırıldıqda BÜTÜN serverlər sinxronlaşdırılsaydı, gecəlik fayl
    ixracı ilə işləyən server də hər 5 dəqiqədə oxunardı: eyni fayl gün
    ərzində onlarla dəfə açılar, hər dəfə bütün sətirlər parse olunar və
    hamısı dublikat kimi atılardı — xalis itki.

    Ona görə `run_cycle` hər serverin `sync_interval_seconds` sütununa baxır
    və VAXTI ÇATMAYAN serveri həmin dövrdə buraxır. Sütunun defoltu tipə
    görədir (HTTP/COM 300 san., fayl 86400 san. —
    `ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS`).

    `force=True` bu qapını AÇIQ şəkildə yan keçir: «indi sinxronlaşdır»
    düyməsi istifadəçinin şüurlu tələbidir və gözləmə müddəti onu
    saxlamamalıdır.
    """

    def __init__(
        self,
        *,
        servers: ErpServerRegistry,
        service_factory: Callable[[], SalesSyncService],
        max_parallel: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            max_parallel: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback.
        """
        self._servers = servers
        self._service_factory = service_factory
        self._explicit_max_parallel = max_parallel
        self._limits = limits or InfrastructureLimits()

    def _max_parallel_value(self) -> int:
        """Paralel worker sayı — HƏR DÖVRDƏ oxunur (dövrlər arası dəyişə bilər).

        ──────────────────────────────────────────────────────────────────────
        HOVUZA GÖRƏ KLAMP (SAAS-7)
        ──────────────────────────────────────────────────────────────────────
        `ERP_SYNC_MAX_PARALLEL_SERVERS` və `DB_POOL_MAX_SIZE` İKİ AYRI Root
        açarıdır və bir-birindən xəbərsiz idi. Hər sync worker-i bir DB
        bağlantısı tutur; paralellik hovuzdan böyük seçilsə (məs. paralellik 8,
        hovuz 4) sinxronizasiya bütün bağlantıları yeyir və İSTİFADƏÇİ
        əməliyyatları `psycopg_pool` taymautuna düşür — yəni fon işi ön planı
        dayandırır. Qüsur yalnız 1C serverlərinin sayı artanda üzə çıxır.

        TAVAN `pool_max - 2`-dir: iki bağlantı QƏSDƏN kənarda saxlanılır —
        biri istifadəçinin cari əməliyyatı, biri isə fon oxumaları
        (bildiriş dispetçeri, server vaxtı) üçün. `max(1, ...)` isə ən dar
        hovuzda belə sinxronizasiyanın TAM dayanmamasını təmin edir: bir
        worker həmişə qalır.

        AÇIQ DƏYƏR DƏ KLAMP EDİLİR: `_explicit_max_parallel` testdən/xüsusi
        quraşdırmadan gəlir, lakin hovuz məhdudiyyəti fiziki həqiqətdir —
        onu «açıq üstünlük» ilə yan keçmək eyni taymautu yaradardı.

        Hovuz dəyəri ROOT açarından oxunur (canlı `ConnectionPool`-dan yox):
        bu sinifin `Database`-ə istinadı YOXDUR və onu əlavə etmək ERP
        modulunu bağlantı qatına bağlayardı. Eyni açar `apply_root_pool_limits`
        ilə canlı hovuza tətbiq olunur, yəni mənbə birdir.
        """
        requested = (
            self._explicit_max_parallel
            if self._explicit_max_parallel is not None
            else self._limits.int_of(SystemLimitKey.ERP_SYNC_MAX_PARALLEL_SERVERS)
        )
        pool_max = self._limits.int_of(SystemLimitKey.DB_POOL_MAX_SIZE)
        ceiling = max(1, pool_max - _POOL_HEADROOM_CONNECTIONS)
        if requested <= ceiling:
            return requested
        _log.warning(
            "ERP_SYNC_PARALLELISM_CLAMPED",
            extra={
                "requested": requested,
                "applied": ceiling,
                "pool_max": pool_max,
                "reason": "paralellik hovuzdan böyükdür — istifadəçi əməliyyatları gözləyərdi",
            },
        )
        return ceiling

    def run_cycle(self, *, now: datetime | None = None, force: bool = False) -> SyncCycleReport:
        """Bir sinxronizasiya dövrü.

        Args:
            force: `True` — dövr intervalı NƏZƏRƏ ALINMIR («indi
                sinxronlaşdır» düyməsi).
        """
        started = now or datetime.now(UTC)
        candidates = self._servers.syncable()
        targets = candidates if force else [s for s in candidates if _is_due(s, started)]
        if not targets:
            # Fərq LOGLANIR: "server yoxdur" ilə "hamısının vaxtı çatmayıb"
            # tamamilə fərqli vəziyyətlərdir və ikincisi NORMALDIR — onu
            # "server yoxdur" kimi göstərmək diaqnostikanı yanıldardı.
            _log.info(
                "ERP_SYNC_NO_SERVERS",
                extra={"candidates": len(candidates), "waiting_for_interval": len(candidates)},
            )
            return SyncCycleReport(started_at=started, finished_at=started)

        workers = min(self._max_parallel_value(), len(targets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="erp-sync") as pool:
            reports = list(pool.map(lambda server: self._sync_isolated(server, started), targets))

        cycle = SyncCycleReport(
            started_at=started,
            finished_at=datetime.now(UTC),
            servers=reports,
        )
        _log.info(
            "ERP_SYNC_CYCLE_FINISHED",
            extra={
                "servers": len(reports),
                "failed": len(cycle.failed),
                "inserted": cycle.total_inserted,
                "duration_seconds": (cycle.finished_at - cycle.started_at).total_seconds(),
            },
        )
        return cycle

    def _sync_isolated(self, server: ErpServer, moment: datetime) -> SyncReport:
        """Bir serverin xətası BURADA bitir — dövrün qalanı davam edir."""
        try:
            service = self._service_factory()
            return service.sync(server, now=moment)
        except ErpError as exc:
            return self._record_failure(server, exc, technical=str(exc))
        except Exception as exc:
            # Gözlənilməz xəta (DB, kodlaşdırma, ...) da bir serveri
            # digərlərindən ayırmalıdır — buraxılsaydı `pool.map` bütün
            # dövrü qırardı.
            return self._record_failure(server, exc, technical=repr(exc))

    def _record_failure(self, server: ErpServer, exc: Exception, *, technical: str) -> SyncReport:
        message = getattr(exc, "user_message", None) or "1C sinxronizasiyası uğursuz oldu."
        try:
            self._servers.record_failure(server.id, technical)
        except Exception:  # pragma: no cover - DB də əlçatmazdır
            _log.exception("ERP_FAILURE_NOT_RECORDED", extra={"server_id": str(server.id)})
        _log.error(
            "ERP_SERVER_SYNC_FAILED",
            extra={
                "server_id": str(server.id),
                "server_name": server.server_name,
                "host": server.host,
                "error": technical[:300],
            },
        )
        return SyncReport(
            server_id=str(server.id),
            server_name=server.server_name,
            ok=False,
            error=message,
        )


def _is_due(server: ErpServer, moment: datetime) -> bool:
    """Serverin növbəti sinxronizasiya vaxtı çatıbmı.

    HEÇ VAXT SİNXRONLAŞMAYAN server HƏMİŞƏ növbədədir: yeni əlavə edilmiş
    konfiqurasiya dərhal işə düşməlidir, əks halda admin serveri qeyd edib
    "niyə heç nə gəlmir?" sualı ilə bir gün gözləyərdi.

    Müqayisə `>=` ilə gedir ki, dəqiq intervalda çağırılan planlayıcı (məs.
    hər 300 saniyədə bir, interval da 300) sonsuz "bir saniyə qaldı" halına
    düşməsin.
    """
    if server.last_successful_sync is None:
        return True
    elapsed = (moment - server.last_successful_sync).total_seconds()
    return elapsed >= server.sync_interval_seconds


def _tally(report: SyncReport, results: Sequence[MatchResult]) -> None:
    for result in results:
        if result.confidence is MatchConfidence.EXACT_MATCH:
            report.exact_matches += 1
        elif result.confidence is MatchConfidence.LOW_CONFIDENCE_MATCH:
            report.low_confidence += 1
        elif result.confidence is MatchConfidence.UNASSIGNED:
            report.unassigned += 1


__all__ = [
    "FALLBACK_MAX_PARALLEL_SERVERS",
    "ErpSyncManager",
    "SalesSyncService",
    "SyncCycleReport",
    "SyncReport",
]
