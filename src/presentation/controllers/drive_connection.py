"""Drive razılıq ekranının kontrolleri — `can_manage_drive_connection`.

──────────────────────────────────────────────────────────────────────────────
SƏLAHİYYƏT QAPISI BURADADIR, EKRANDA DEYİL
──────────────────────────────────────────────────────────────────────────────
Menyu maddəsi `can_manage_drive_connection` tələb edir və icazəsiz istifadəçi
bölməni GÖRMÜR (bölmə 3). Lakin görünmə yeganə qapı ola bilməz: ekran birbaşa
açılsa (`show_screen` çağırışı, gələcək dərin keçid) yenə də qoşulma
başlamamalıdır. Ona görə hər əməliyyatın əvvəlində flag yoxlanılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ TAYMER, SAP DEYİL
──────────────────────────────────────────────────────────────────────────────
`DriveOAuthFlow.poll()` bloklamır (bax həmin modulun başlığı) — ona görə
gözləmə adi `QTimer` ilə aparılır və bütün iş Qt hadisə dövrəsində qalır.
Ayrıca sap qursaydıq, brauzerdən qayıdan kod GUI sapına köçürülməli olardı.

──────────────────────────────────────────────────────────────────────────────
TOKEN EKRANDAN KEÇMİR
──────────────────────────────────────────────────────────────────────────────
`refresh_token` yalnız bu kontrollerin yaddaşında bir an mövcud olur və
dərhal `DriveConnectionRepository.connect()`-ə verilir; orada AES-256-GCM ilə
şifrələnib yazılır (SEC-002 modeli). Ekran onu HEÇ VAXT görmür, jurnalda isə
yalnız hesabın e-poçtu qalır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.storage import StorageError
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_d import DriveConnectionScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

MANAGE_DRIVE_FLAG = "can_manage_drive_connection"

#: Razılıq nəticəsinin yoxlanma tezliyi. 200 ms insan üçün ani görünür və
#: hər tıqqıltıda ən çoxu 50 ms soket gözləməsi olur (bax `oauth_flow`).
POLL_INTERVAL_MS = 200

#: Status → (mətn, nişan tonu). Açarlar `DriveConnectionStatus` dəyərləridir.
STATUS_TEXT: dict[str, tuple[str, str]] = {
    "ACTIVE": ("Aktiv", "success"),
    "QUOTA_EXCEEDED": ("Yer qalmayıb", "warning"),
    "ARCHIVED": ("Arxivlənib", "neutral"),
    "REVOKED": ("İcazə ləğv edilib", "danger"),
}


class DriveConnectionController:
    """Razılıq axınını başladır, gözləyir və bağlantını yazır."""

    def __init__(
        self, context: ApplicationContext, actor: Employee, *, executor: Any = None
    ) -> None:
        self._context = context
        self._actor = actor
        self._flow: Any = None
        self._timer: QTimer | None = None
        self._elapsed_ms = 0
        #: Fon icraçısı — istehsalatda Qt hovuzu, testlərdə `InlineExecutor`.
        self._executor = executor
        #: Kod-mübadiləsi işinə istinad: nəticə gəlməmiş toplanarsa siqnal itərdi.
        self._exchange_task: Any = None

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: DriveConnectionScreen) -> None:
        screen.connect_requested.connect(lambda: self._on_connect(screen))
        screen.cancel_requested.connect(lambda: self._on_cancel(screen))
        self.refresh(screen)

    def refresh(self, screen: DriveConnectionScreen) -> None:
        """Aktiv hesabı və tarixçəni bazadan oxuyur."""
        try:
            connections = self._repository().list_all()
        except Exception:
            _error_log.exception("DRIVE_CONNECTIONS_LOAD_FAILED")
            screen.show_error(
                title="Bağlantılar oxunmadı",
                message="Drive bağlantı siyahısı alınmadı. Yenidən cəhd edin.",
            )
            return

        # CARİ HESAB = ARXİVLƏNMƏMİŞ SƏTİR, YALNIZ `ACTIVE` DEYİL.
        #
        # Əvvəl yalnız `status == "ACTIVE"` axtarılırdı və bunun iki nəticəsi
        # vardı: kvotası dolmuş (`QUOTA_EXCEEDED`) və ya razılığı geri alınmış
        # (`REVOKED`) hesab ekranda «Qoşulmayıb» kimi görünürdü. Yəni ekran
        # SƏBƏBİ gizlədirdi: administrator «hesab qoşulmayıb» oxuyub yenidən
        # qoşmağa çalışırdı, halbuki problem başqa idi. İndi sətir tapılır və
        # `STATUS_TEXT` onun HƏQİQİ vəziyyətini yazır.
        #
        # Sıra `connected_at DESC`-dir və tenant başına eyni anda yalnız BİR
        # arxivlənməmiş sətir olur (`connect()` köhnəni arxivləyir), ona görə
        # `next(...)` birmənalıdır.
        active = next(
            (item for item in connections if item.status.value != "ARCHIVED"),
            None,
        )
        if active is None:
            screen.set_active(
                account=None,
                status_text="Qoşulmayıb",
                tone="neutral",
                quota_text=(
                    "Hesab qoşulana qədər cərimə şəkilləri bu kompüterdə növbədə "
                    "gözləyir — cərimələr normal yaradılır."
                ),
            )
        else:
            text, tone = STATUS_TEXT.get(active.status.value, (active.status.value, "neutral"))
            screen.set_active(
                account=active.google_account_email,
                status_text=text,
                tone=tone,
                quota_text=_quota_text(active),
            )

        screen.set_history(
            [
                (
                    item.google_account_email,
                    STATUS_TEXT.get(item.status.value, (item.status.value, ""))[0],
                    _date_text(item),
                )
                for item in connections
            ]
        )

    # ------------------------------- razılıq --------------------------------- #

    def _on_connect(self, screen: DriveConnectionScreen) -> None:
        # MESAJ ROL DEYİL, FLAG ADI DEYİR — NİYƏ:
        #
        # Əvvəlki mətn «yalnız Root və CEO idarə edə bilər» idi, halbuki
        # `_permitted()` YALNIZ `can_manage_drive_connection` flag-ini yoxlayır
        # və həmin flag `schema.sql` §22-də `hardlock_level = 0`-dır, yəni Root
        # onu İSTƏNİLƏN rola verə bilər (bax `HardlockLevel.NONE`).
        #
        # Yəni mesaj faktdan DAR idi: flag-i almış HR_Admin əməliyyatı uğurla
        # icra edə bilirdi, lakin icazəsi olmayan bir istifadəçi «bu, Root/CEO
        # işidir» oxuyub səhv adama — CEO-ya — müraciət edirdi. Rol qapısı
        # ƏLAVƏ ETMƏK variantı rədd edildi: o, flag-i qanuni şəkildə almış
        # rolların REAL imkanını bağlayardı (`can_manage_drive_connection`
        # qəsdən delegasiya edilə biləndir — bax `migrations/002` başlığı).
        # ÖLÜ-SON DÜZƏLİŞİ (QA-FULL FAZA 3): bu ekranın altı `show_error()`
        # çağırışı `ContentSwitcher`-i TAM xəta vəziyyətinə keçirirdi — status
        # kartı, «Google Hesabı Qoş» düyməsi və tarixçə GÖRÜNMƏZ olurdu.
        # `AdminShell` ekranı BİR DƏFƏ qurub saxlayır (`REFRESH_ON_REVISIT`
        # yalnız `dashboard`), yəni bölmədən çıxıb qayıtmaq da düzəltmirdi —
        # sessiya sonuna qədər ölü qalırdı. Bu altı hal isə TRANZİTDİR (bir
        # kliklik/bir taymaut nəticəsidir, bölmənin ÖZÜNÜN oxunmaması DEYİL),
        # ona görə `screen.set_connect_message(...)` işlədilir: mətn status
        # kartının İÇİNDƏ qalır, `ContentSwitcher` toxunulmur (bax ekranın
        # `set_connect_message` şərhi). Boş Google konfiqurasiyası İLK
        # QURAŞDIRMADA REAL haldır — bu ölü-son adi istifadəçidə baş verirdi.
        #
        # Köhnə mesaj HƏR CƏHDDƏ təmizlənir: əks halda əvvəlki xəbərdarlıq
        # yeni cəhdin nəticəsini maskalayardı.
        screen.set_connect_message("")
        if not self._permitted():
            screen.set_connect_message(
                "Səlahiyyət yoxdur: Drive bağlantısını idarə etmək üçün «Drive "
                "bağlantısını idarə et» icazəsi lazımdır. Administratorunuzla "
                "əlaqə saxlayın.",
                error=True,
            )
            return
        if self._flow is not None:
            return

        oauth = self._oauth_client()
        if oauth is None:
            screen.set_connect_message(
                "Google konfiqurasiyası yoxdur: KOMPASOS_GOOGLE_CLIENT_ID və "
                "KOMPASOS_GOOGLE_CLIENT_SECRET təyin edilməyib. Quraşdırma "
                "sənədinə baxın.",
                error=True,
            )
            return

        from src.infrastructure.storage.oauth_flow import DriveOAuthFlow  # noqa: PLC0415

        flow = DriveOAuthFlow(oauth)
        try:
            request = flow.start()
        except Exception:
            flow.close()
            _error_log.exception("DRIVE_OAUTH_START_FAILED")
            screen.set_connect_message(
                "Razılıq başlamadı: Lokal port açıla bilmədi. Antivirus/firewall "
                "ayarlarını yoxlayın.",
                error=True,
            )
            return

        self._flow = flow
        self._elapsed_ms = 0
        # Brauzer açılmasa da ünvan ekranda qalır (bax ekran docstring-i).
        flow.open_browser(request)
        screen.show_pending(request.url)

        timer = QTimer(screen)
        timer.setInterval(POLL_INTERVAL_MS)
        timer.timeout.connect(lambda: self._poll(screen))
        timer.start()
        self._timer = timer

    def _poll(self, screen: DriveConnectionScreen) -> None:
        if self._flow is None:
            self._stop_timer()
            return

        self._elapsed_ms += POLL_INTERVAL_MS
        if self._elapsed_ms > self._flow_timeout_seconds() * 1000:
            self._finish(screen)
            screen.set_connect_message(
                "Razılıq vaxtı bitdi: Google səhifəsində icazə verilmədi. Yenidən cəhd edin.",
                error=True,
            )
            return

        try:
            code = self._flow.poll()
        except StorageError as error:
            self._finish(screen)
            screen.set_connect_message(f"Razılıq alınmadı: {error.user_message}", error=True)
            return
        except Exception:
            self._finish(screen)
            _error_log.exception("DRIVE_OAUTH_POLL_FAILED")
            screen.set_connect_message(
                "Razılıq alınmadı: Gözlənilməz xəta baş verdi. Yenidən cəhd edin.",
                error=True,
            )
            return

        if code is None:
            return
        # Kod gəldi — TAYMER burada dayandırılır: `_complete()` indi FONDA
        # işləyəcək (bax onun başlığı) və taymer kəsilməsə, növbəti 200 ms-lik
        # tıqqıltı artıq bağlanmış lokal serverdə ikinci `poll()` çağırardı.
        self._stop_timer()
        self._complete(screen, code)

    def _complete(self, screen: DriveConnectionScreen, code: str) -> None:
        """Kodu token-ə dəyişir — İŞ FON SAPINDADIR (UI-5).

        ──────────────────────────────────────────────────────────────────
        ƏVVƏL SİNXRON İDİ — DÖVRƏ 5 AUDİTİNİN TAPINTISI
        ──────────────────────────────────────────────────────────────────
        `flow.exchange()` Google token endpoint-inə birbaşa `httpx` ilə POST
        göndərir (`infrastructure/storage/oauth_flow.py`), taymautu isə 30
        saniyədir. Sinxron çağırıldıqda bu, `QTimer.timeout` slotunun içində
        icra olunduğu üçün bütün GUI sapını — və beləliklə bütöv pəncərəni —
        həmin müddət ərzində dondururdu. Düzəliş `erp_servers.py` bağlantı
        testi ilə EYNİ naxışdır (`background_task.run_job`).
        """
        from src.presentation.background_task import run_job  # noqa: PLC0415

        flow = self._flow
        assert flow is not None

        def job() -> object:
            # FON SAPINDA icra olunur: `flow.exchange()` şəbəkə çağırışıdır,
            # `_repository()` isə `self._context.database` hovuzundan TƏZƏ
            # bağlantı götürür (`unit_of_work`) — pool sap-təhlükəsizdir.
            credentials = flow.exchange(code)
            connection = self._repository().connect(
                google_account_email=credentials.account_email or "(naməlum hesab)",
                refresh_token=credentials.refresh_token,
                encryption=self._encryption(),
                connected_by=self._actor.id,
            )
            return (credentials, connection)

        self._exchange_task = run_job(
            job,
            on_success=lambda result: self._on_exchange_succeeded(screen, result),
            on_failure=lambda error: self._on_exchange_failed(screen, error),
            owner=screen,
            name="DRIVE_OAUTH_EXCHANGE",
            executor=self._executor,
        )

    def _on_exchange_succeeded(self, screen: DriveConnectionScreen, result: object) -> None:
        """Nəticə ƏSAS SAPDA qəbul edilir — burada Qt widget-ə TOXUNULA bilər."""
        credentials: Any
        connection: Any
        credentials, connection = result  # type: ignore[misc]
        _audit_log.warning(
            "DRIVE_CONNECTION_ESTABLISHED",
            extra={"actor_id": str(self._actor.id), "account": credentials.account_email},
        )
        # DB AUDİTİ: fayl jurnalı rotasiya ilə (10 fayl × 10 MB) itir, halbuki
        # «hansı Google hesabı nə vaxt, kim tərəfindən qoşuldu» sualı sonradan
        # — mübahisə və ya təhlükəsizlik araşdırması zamanı — verilir. Root
        # panelinin «Audit» ekranı yalnız `audit_logs`-u oxuyur.
        recorded = self._record_audit(
            action="DRIVE_CONNECTION_ESTABLISHED",
            connection_id=connection.id,
            account=connection.google_account_email,
            status=connection.status.value,
        )
        if not recorded:
            # Bağlantı ARTIQ yazılıb və öz tranzaksiyasında commit olunub —
            # onu geri qaytarmaq istifadəçini yenidən Google razılığına
            # göndərmək demək olardı, halbuki nasazlıq audit sətrindədir.
            # Buna baxmayaraq sükut QADAĞANDIR (CLAUDE.md bölmə 5): istifadəçi
            # izin natamam olduğunu GÖRMƏLİDİR ki, administratora deyə bilsin.
            screen.show_error(
                title="Audit izi yazılmadı",
                message=(
                    "Hesab qoşuldu, lakin əməliyyat audit jurnalına düşmədi. "
                    "Administratora bildirin."
                ),
            )
        self._finish(screen)
        # Yeni hesab = yeni provider. Keşlənmiş fabrik köhnə bağlantını
        # saxlayır, ona görə atılır; növbəti dövrə onu ROOT limiti ilə
        # yenidən qurur (bax `ApplicationContext.drive_providers`).
        self._context.invalidate_drive_providers()
        self.refresh(screen)
        # Gözləyən şəkillər dərhal yüklənməyə başlasın — administrator
        # bağlantının işlədiyini elə burada görməlidir.
        self._context.run_evidence_uploads()

    def _on_exchange_failed(self, screen: DriveConnectionScreen, error: BaseException) -> None:
        """Fon işində qalan istisna — SÜKUTLA UDULMUR."""
        self._finish(screen)
        if isinstance(error, KompasOSError):
            screen.show_error(title="Hesab qoşulmadı", message=error.user_message)
            return
        _error_log.error("DRIVE_CONNECT_FAILED", exc_info=error)
        screen.show_error(
            title="Hesab qoşulmadı",
            message="Bağlantı yazıla bilmədi. Yenidən cəhd edin.",
        )

    def _on_cancel(self, screen: DriveConnectionScreen) -> None:
        self._finish(screen)

    def _finish(self, screen: DriveConnectionScreen) -> None:
        self._stop_timer()
        if self._exchange_task is not None:
            # Ləğv = nəticəni rədd etmək (bax `background_task.py`): gözlənən
            # kod-mübadiləsi bağlanmış ekrana/dialoqa geri yazılmasın.
            self._exchange_task.cancel()
            self._exchange_task = None
        if self._flow is not None:
            self._flow.close()
            self._flow = None
        screen.clear_pending()

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    # ------------------------------ köməkçilər ------------------------------- #

    def _permitted(self) -> bool:
        """VAXT `self._context.clock`-DAN GƏLİR, `datetime.now(UTC)`-DAN YOX
        (DEEP-GAP FAZA 4, T5) — `root_control.py::_permitted` ilə EYNİ
        düzəliş, eyni səbəb: bu, yeganə qapıdır (use case yoxdur, kontroller
        birbaşa repository-yə yazır) və OS saatı TIME-1-in server-lövbərli
        vədini pozurdu."""
        return bool(self._actor.has_permission(MANAGE_DRIVE_FLAG, now=self._context.clock.now()))

    def _record_audit(
        self,
        *,
        action: str,
        connection_id: Any,
        account: str,
        status: str,
    ) -> bool:
        """`audit_logs`-a bir sətir yazır. Qaytarır: yazıldımı.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA, QISA SESSİYA
        ──────────────────────────────────────────────────────────────────────
        Bağlantı sətrini `DriveConnectionRepository` YAZIR və o, `Database`-ə
        birbaşa bağlıdır (öz `unit_of_work`-u ilə commit edir) — yəni audit-i
        həmin yazı ilə eyni tranzaksiyaya salmaq mümkün deyil. Kontroller isə
        sessiya SAXLAMIR (bax modul başlığı və CLAUDE.md bölmə 6), ona görə
        audit dərhal ardınca öz qısa sessiyasında yazılır və commit edilir.

        İstisna BURADA udulur, LAKİN sükutla deyil: nəticə çağırana `False`
        kimi qayıdır və o, istifadəçiyə açıq mesaj göstərir. İstisnanı yuxarı
        ötürsəydik, uğurla qurulmuş bağlantı "qoşulmadı" kimi görünərdi və
        administrator eyni hesabı təkrar-təkrar qoşmağa çalışardı.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.uow.audit.record(
                    tenant_id=self._context.tenant_id,
                    actor_id=self._actor.id,
                    action=action,
                    entity_type="drive_connections",
                    entity_id=connection_id,
                    after_state={
                        # Token DEYİL, yalnız hesabın e-poçtu (SEC-017):
                        # `refresh_token` bu kontrollerin yaddaşından kənara
                        # heç bir formada çıxmır.
                        "account": account,
                        "status": status,
                    },
                )
                session.commit()
        except Exception:
            _error_log.exception("DRIVE_AUDIT_WRITE_FAILED", extra={"account": account})
            return False
        return True

    def _flow_timeout_seconds(self) -> float:
        """Razılıq axınının ömrü — CANLI ROOT dəyəri, fallback modul sabiti.

        ƏVVƏL SABİT OXUNURDU: `oauth_flow.FLOW_TIMEOUT_SECONDS` idxal edilirdi
        və o, `DEFAULT_LIMITS`-dən doğulan FALLBACK-dır — yəni Root
        `DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS`-i uzatsa da, razılıq pəncərəsi
        köhnə müddətdə bağlanırdı (Google hesabına 2FA ilə girən admin üçün
        məhz bu müddət azlıq edir). Sabitin ADI DƏYİŞMİR — o, hələ də
        fallback mənbəyidir (bax `oauth_flow` başlığı).

        Oxu HƏR tıqqıltıda deyil, hər dəfə çağırılanda edilir; axın onsuz da
        200 ms-lik taymerlədir və dəyər dəyişsə növbəti tıqqıltı onu görür.
        """
        from src.infrastructure.storage.oauth_flow import (  # noqa: PLC0415
            FLOW_TIMEOUT_SECONDS,
        )

        try:
            return float(
                self._context.infrastructure_limits().float_of(
                    SystemLimitKey.DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS
                )
            )
        except Exception:
            _error_log.warning("DRIVE_OAUTH_TIMEOUT_FALLBACK")
            return float(FLOW_TIMEOUT_SECONDS)

    def _repository(self) -> Any:
        from src.infrastructure.storage.connections import (  # noqa: PLC0415
            DriveConnectionRepository,
        )

        return DriveConnectionRepository(self._context.database, self._context.tenant_id)

    @staticmethod
    def _encryption() -> Any:
        from src.infrastructure.security.encryption import EncryptionService  # noqa: PLC0415

        return EncryptionService()

    @staticmethod
    def _oauth_client() -> Any:
        import os  # noqa: PLC0415

        from src.infrastructure.storage.drive_api import OAuthClient  # noqa: PLC0415

        client_id = os.environ.get("KOMPASOS_GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("KOMPASOS_GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None
        return OAuthClient(client_id=client_id, client_secret=client_secret)


# --------------------------------------------------------------------------- #
# Mətnlər
# --------------------------------------------------------------------------- #


def _quota_text(connection: Any) -> str:
    """Kvota sətri — ölçülməyibsə bunu AÇIQ deyir.

    "0 GB istifadə olunub" yazmaq ölçülməmiş kvotanı boş kvota kimi
    göstərərdi; administrator isə yerin bitməkdə olduğunu vaxtında görməlidir.
    """
    used = connection.quota_used_bytes
    total = connection.quota_total_bytes
    if used is None:
        return "Kvota hələ ölçülməyib"
    if total is None:
        return f"{_gigabytes(used)} istifadə olunub (limit göstərilməyib)"
    percent = (used / total * 100) if total else 0
    return f"{_gigabytes(used)} / {_gigabytes(total)} istifadə olunub ({percent:.0f}%)"


def _gigabytes(value: int) -> str:
    return f"{value / (1024**3):.2f} GB"


def _date_text(connection: Any) -> str:
    moment = connection.archived_at or connection.connected_at
    return moment.astimezone().strftime("%d.%m.%Y %H:%M") if moment else "—"


__all__ = ["MANAGE_DRIVE_FLAG", "STATUS_TEXT", "DriveConnectionController"]
