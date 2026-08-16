"""ERP / 1C Server panelinin YAZI yolu — `ErpConnectionWizardUseCase` (bölmə 7).

──────────────────────────────────────────────────────────────────────────────
KREDENSİAL EKRANA DA, JURNALA DA DÜŞMÜR (SEC-013)
──────────────────────────────────────────────────────────────────────────────
Şifrə YALNIZ iki yerdə yaşayır: sihirbazdakı `QLineEdit` (maskalanmış) və
`ErpServerDraft` (işlək yaddaş). Kontroller onu heç bir jurnala, heç bir
`extra=` sözlüyünə və heç bir ekran mətninə ötürmür. Audit görünüşü domendə
həll olunub — `ErpServerDraft.auditable()` şifrəni QƏSDƏN kənarda saxlayır və
use case məhz onu yazır. Ona görə burada "audit üçün sahə yığmaq" kimi bir
addım YOXDUR: onu əlavə etsəydik, SEC-013-ün tək qapısını yan keçmiş olardıq.

Redaktə zamanı şifrə ekrana GERİ QAYTARILMIR — o, `erp_servers` cədvəlində
AES-256-GCM ilə şifrələnib və `ErpServer` oxu-modeli onu ümumiyyətlə daşımır.
İstifadəçi onu yenidən yazır; bu, əlavə yük deyil, qorumanın nəticəsidir.

──────────────────────────────────────────────────────────────────────────────
REDAKTƏDƏ KONFİQURASİYA OXUNUR, SİRR İSƏ SÜZÜLÜR (1c.md GUI fazası)
──────────────────────────────────────────────────────────────────────────────
Üç konnektorlu dünyada sihirbaz boş açıla BİLMƏZ: fayl serverinin sütun adları
və ya COM-un sorğu parametrləri formada görünmürsə, redaktə həmin dəyərləri
səssizcə defolta qaytarardı — yəni işləyən bir konfiqurasiya bir "Yadda Saxla"
kliki ilə dağılardı.

Ona görə `_existing_payload()` saxlanmış konfiqurasiyanı oxuyur, lakin ekrana
YALNIZ `ConnectorConfig.public_values()` ötürülür: sirr daşıyan açarlar
(`password`, `token`, …) süzülür və şifrənin özü heç bir sözlüyə düşmür.
Oxunuş `security.log`-a `ERP_CREDENTIALS_ACCESSED` sətri yazır — bu, itki
deyil, qazancdır: konfiqurasiyanın nə vaxt və kim tərəfindən açıldığı görünür.

──────────────────────────────────────────────────────────────────────────────
YADDA SAXLAMA TESTDƏN KEÇİR — KONTROLLER TESTİ YAN KEÇMİR
──────────────────────────────────────────────────────────────────────────────
`save_new()` / `save_existing()` `_require_successful_test()` çağırır, yəni
uğursuz test halında sətir YAZILMIR (spesifikasiya: "yeni ayar yalnız test
uğurlu olduqdan sonra aktivləşir"). Kontroller ayrıca "test etdim, indi
saxlayıram" məntiqi qurmur — həmin qapı use case-in içindədir və orada
qalmalıdır.

──────────────────────────────────────────────────────────────────────────────
BAĞLANTI TESTİ ARTIQ FONDA İCRA OLUNUR (`background_task.py`)
──────────────────────────────────────────────────────────────────────────────
ƏVVƏL: test sinxron çağırılırdı, çünki layihədə GUI fon-işçi naxışı yox idi.
Cavab verməyən 1C serverində bütün örtük taymaut bitənə qədər donurdu, spinner
fırlanmırdı (taymer bloklanmış hadisə dövründə işə düşmür) və istifadəçi
pəncərəni bağlaya bilmirdi. Donmanın HƏDDİ var idi
(`system_limits.ERP_REQUEST_TIMEOUT_SECONDS`), lakin hədd donmanı qanuniləşdirmir.

İNDİ: test `BackgroundTask` ilə Qt sap hovuzunda icra olunur, nəticə isə
siqnalla ƏSAS SAPA qayıdır — yəni pəncərə test müddətində CAVAB VERİR.
Üç incəlik burada, çağırış yerində qeyd olunur (naxışın izahı modulun
öz başlığındadır):

    1. SESSİYA SAP SƏRHƏDİNİ KEÇMİR. `_run_test()` FON SAPINDA icra olunur və
       `context.session(...)`-u ORADA açır. Əsas sapda qurulmuş sessiya işə
       ötürülsəydi, eyni `psycopg` bağlantısı iki sapdan işlədilərdi — bu,
       bağlantı protokolunu qarışdırır. `test_connection` heç nə YAZMIR, ona
       görə commit çağırılmır: sessiya bağlananda tranzaksiya geri qaytarılır.

    2. LƏĞV = NƏTİCƏNİ RƏDD ETMƏK. Sihirbaz bağlananda `cancel()` çağırılır;
       gec gələn cavab artıq bağlanmış pəncərəyə YAZILMIR. Sap zorla
       öldürülmür — soketin/COM çağırışının ortasında sapı kəsmək təhlükəlidir.

    3. İKİQAT İŞƏ SALMA QAPISI İKİ QATLIDIR: düymə `set_busy(True)` ilə
       deaktiv olur (görünən qat) və `BackgroundTask.is_running` ikinci
       buraxılışı rədd edir (klaviatura qısayolu düymənin deaktivliyini yan
       keçə bilər).

Gözləmə KURSORU testdə artıq QOYULMUR (yalnız yadda saxlamada qalır): qum
saatı "sistem məşğuldur, toxunma" deməkdir, halbuki indi məhz əksi doğrudur —
istifadəçi sahələri dəyişə və pəncərəni bağlaya bilər.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.background_task import TaskExecutor
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_d import ErpServersScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `v_erp_server_health.health` → ekranın tanıdığı status mətni.
#: Açarlar `ErpServersScreen._STATUS_TONES`-dandır; naməlum dəyər neytral
#: nişan alır və gizlədilmir.
_STATUS_TEXT: dict[str, str] = {
    "HEALTHY": "Aktiv",
    "DEGRADED": "Gecikmə yüksəkdir",
    "STALE": "Gecikmə yüksəkdir",
    "NEVER_SYNCED": "Bağlantı yoxdur",
    "INACTIVE": "Deaktiv",
}


class ErpServersController:
    """1C server panelini `ErpConnectionWizardUseCase`-ə bağlayır."""

    def __init__(
        self,
        context: ApplicationContext,
        actor: Employee,
        *,
        executor: TaskExecutor | None = None,
    ) -> None:
        """Kontrolleri qurur.

        Args:
            context: Canlı obyekt qrafı — hər əməliyyat üçün yeni sessiya
                açılır (sessiya SAXLANILMIR, CLAUDE.md bölmə 6).
            actor: Paneli açan istifadəçi.
            executor: Bağlantı testinin icraçısı. `None` = Qt sap hovuzu.
                Testlərdə `InlineExecutor` verilir ki, bütün axın (sihirbaz →
                kontroller → nəticə) heç bir vaxt gözləməsi olmadan, yəni
                qeyri-sabitliyə yer qoymadan yoxlansın.
        """
        self._context = context
        self._actor = actor
        self._executor = executor
        #: server adı → siyahı sətri (ekran yalnız ADI yayır).
        #:
        #: ID-nin ÖZÜ deyil, BÜTÖV sətir saxlanılır: redaktə sihirbazı serverin
        #: növünü, ünvanını, bazasını və dövrünü də formaya yükləməlidir və
        #: onlar onsuz da siyahı sorğusunda gəlir — ikinci sorğu eyni anın
        #: ikinci şəklini verərdi.
        self._servers: dict[str, Any] = {}

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: ErpServersScreen) -> None:
        screen.create_requested.connect(lambda: self._open_wizard(screen, server_name=None))
        screen.server_selected.connect(lambda name: self._open_wizard(screen, server_name=name))
        screen.test_all_requested.connect(lambda: self._on_test_all(screen))
        self.refresh(screen)

    def refresh(self, screen: ErpServersScreen) -> None:
        """Server siyahısını, xəritələməni və son sinxronizasiyanı oxuyur.

        ──────────────────────────────────────────────────────────────────────
        SİYAHI BİRBAŞA OXUNUR, SƏLAHİYYƏT İSƏ USE CASE-DƏN GƏLİR
        ──────────────────────────────────────────────────────────────────────
        `ErpConnectionWizardUseCase`-də "serverləri sadala" metodu YOXDUR və
        onu əlavə etmək use case-i göstəriş vasitəsinə çevirərdi (eyni əsas
        `screen_data._fines`-də izah olunub). Lakin ekran icazəsiz AÇILMAMALIDIR,
        ona görə `mappings_for()` ƏVVƏL çağırılır: o, `can_manage_erp_servers`
        qapısından keçir və icazə yoxdursa istisna atır — yəni siyahı sorğusu
        ümumiyyətlə icra olunmur.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                mapping = session.erp_connections.mappings_for(actor=self._actor, now=_now())
                servers = _server_rows(session)
        except KompasOSError as error:
            screen.show_error(title="Panel açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ERP_SERVERS_LOAD_FAILED")
            screen.show_error(
                title="Panel açıla bilmədi",
                message="Server siyahısı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        self._servers = {str(row["server_name"]): row for row in servers}

        # Açarlar ekranın FAKTİKİ oxuduqlarıdır: `name`, `type`, `address`,
        # `stores`, `latency`, `latency_meaning`, `status` — maket yolundakı
        # `preview_data.ERP_SERVERS` ilə EYNİ dəst (CLAUDE.md bölmə 6).
        screen.set_servers([_server_view(row) for row in servers], mapped_stores=len(mapping))
        screen.set_mapping(
            [(link.store_name, link.server_name) for link in mapping],
            note=_mapping_note(len(mapping), len(servers)),
        )
        screen.set_last_sync(
            [
                (
                    str(row["server_name"]),
                    _sync_text(row),
                    "success" if row["last_successful_sync"] is not None else "danger",
                )
                for row in servers
            ]
        )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_test_all(self, screen: ErpServersScreen) -> None:
        """«Hamısını Yoxla» — sağlamlıq görünüşünü YENİDƏN oxuyur.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ HƏR SERVERƏ AYRICA TEST GÖNDƏRİLMİR
        ──────────────────────────────────────────────────────────────────────
        `ErpConnectionWizardUseCase.test_connection()` YALNIZ `ErpServerDraft`
        qəbul edir, yəni ŞİFRƏ tələb edir — saxlanmış server üçün isə şifrə
        şifrələnmiş formadadır və oxu-modelində (`ErpServer`) YOXDUR (SEC-013).
        Saxlanmış serveri test edən bir metod use case-də MÖVCUD DEYİL; onu
        burada, konnektor fabrikini birbaşa çağıraraq qurmaq səlahiyyət
        yoxlamasını və audit yazısını yan keçmək olardı.

        `v_erp_server_health` isə sinxronizasiya worker-inin REAL nəticələrini
        saxlayır — yəni bu düymənin verə biləcəyi ən dürüst cavab həmin
        nəticələri yenidən oxumaqdır.
        """
        self.refresh(screen)

    def _open_wizard(self, screen: ErpServersScreen, *, server_name: str | None) -> None:
        """Yeni server / mövcud serverin redaktəsi — eyni sihirbaz.

        Redaktədə şifrə sahəsi BOŞ açılır (bax modul başlığı) və istifadəçi
        onu yenidən yazır; `save_existing()` onsuz da testdən keçirir. Növ,
        ünvan, baza, dövr və növə xas parametrlər isə FORMAYA YÜKLƏNİR —
        səbəbi modul başlığındadır.
        """
        from src.presentation.screens.group_d import ServerConnectionWizard  # noqa: PLC0415

        row = self._servers.get(server_name or "")
        if server_name is not None and row is None:
            screen.show_error(
                title="Server tapılmadı",
                message="Bu server artıq dəyişdirilib. Siyahı yenilənir.",
            )
            self.refresh(screen)
            return

        server_id = row["id"] if row is not None else None
        wizard = ServerConnectionWizard(screen.theme, parent=screen)
        self._bind_wizard(screen, wizard, server_id=server_id)
        if row is not None:
            wizard.load(self._existing_payload(row))
        wizard.exec()

    def _bind_wizard(self, screen: ErpServersScreen, wizard: Any, *, server_id: Any) -> Any:
        """Sihirbazın siqnallarını kontrollerə bağlayır — `exec()`-dən AYRI.

        Ayrılıq qəsdlidir: `exec()` modal hadisə dövrü açır və onu avtomatik
        bağlayan heç nə yoxdur, ona görə layihədə heç bir test onu çağırmır
        (bax `tests/unit/test_erp_connection_wizard.py` başlığı). Bağlama
        ayrıca metod olduqda test REAL zənciri — düymə kliki → siqnal →
        kontroller → fon işçisi → ekran — yoxlaya bilir; əks halda yalnız
        kontrollerin daxili metodları ayrı-ayrılıqda çağırılardı və məhz
        BAĞLANTININ özündəki qüsur (yanlış siqnal, unudulmuş `cancel`)
        görünməz qalardı.
        """
        tester = self._build_tester(wizard)
        wizard.test_requested.connect(lambda payload: self._on_test(wizard, tester, payload))
        wizard.saved.connect(lambda payload: self._on_save(screen, payload, server_id=server_id))
        return tester

    def _build_tester(self, wizard: Any) -> Any:
        """Bağlantı testinin fon işçisi — ÖMRÜ SİHİRBAZA BAĞLIDIR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ İŞÇİYƏ İSTİNAD SAXLANILMIR
        ──────────────────────────────────────────────────────────────────────
        İşçi sihirbazın Qt UŞAĞIDIR (`parent=wizard`), yəni sihirbaz məhv
        olanda o da məhv olur və gec gələn nəticə silinmiş widget-ə TOXUNA
        BİLMİR (Qt alıcısı ölmüş bağlantıları qoparır və ona postlanmış
        hadisələri növbədən çıxarır). Kontrollerin özü də `lambda`-ların
        bağlamasında yaşayır — eyni məntiq (CLAUDE.md bölmə 6).

        `finished` isə AYRI bir hal üçündür: `QDialog` bağlananda dərhal MƏHV
        OLMUR (valideyni ekrandır), ona görə ləğv AÇIQ çağırılır — əks halda
        gec gələn cavab bağlanmış, lakin hələ canlı olan formanı doldurardı.
        """
        from src.presentation.background_task import BackgroundTask  # noqa: PLC0415

        tester = BackgroundTask(parent=wizard, executor=self._executor, name="ERP_TEST")
        tester.succeeded.connect(lambda result: self._show_test_result(wizard, result))
        tester.failed.connect(lambda error: self._show_test_error(wizard, error))
        wizard.finished.connect(lambda _code: tester.cancel())
        return tester

    def _existing_payload(self, row: Any) -> dict[str, Any]:
        """Saxlanmış serverin sihirbaz görünüşü — ŞİFRƏSİZ.

        Konfiqurasiya oxuna bilməsə (şifrələmə açarı dəyişib, sətir zədəlidir)
        forma YENƏ AÇILIR — sadəcə növə xas sahələr boş qalır. İstisnanı
        yuxarı buraxsaydıq, bir zədəli sətir bütün redaktə axınını bağlayardı,
        halbuki istifadəçinin məhz həmin sətri düzəltməyə ehtiyacı var.
        """
        return {
            "name": str(row["server_name"]),
            "connector_type": str(row["connector_type"] or ""),
            "host": str(row["host"] or ""),
            "database": str(row["infobase"] or ""),
            "username": str(row["username"] or ""),
            "sync_interval": str(int(row["sync_interval_seconds"] or 0)),
            "config": self._public_config(row["id"]),
        }

    def _public_config(self, server_id: Any) -> dict[str, Any]:
        """`connector_config`-in sirrsiz görünüşü (bax modul başlığı)."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                config = session.erp_server_configs.credentials_for(server_id).connector_config
                return dict(config.public_values())
        except Exception:
            _error_log.exception("ERP_CONFIG_READ_FAILED")
            return {}

    def _on_test(self, wizard: Any, tester: Any, payload: Any) -> None:
        """«Bağlantını Yoxla» — iş FONA buraxılır, ekran cavab verməkdə qalır.

        Forma natamamdırsa fon işi ÜMUMİYYƏTLƏ buraxılmır: səbəb dərhal
        bəllidir və sap açmaq mənasız gecikmə olardı.

        İkinci klik (və ya klaviatura qısayolu) `is_running` ilə rədd edilir —
        deaktiv düymə yalnız GÖRÜNƏN qatdır.
        """
        draft = _draft_from(payload)
        if draft is None:
            wizard.set_test_result(ok=False, message=_missing_fields_message(payload))
            return
        if tester.is_running:
            return

        wizard.set_busy(True)
        tester.run(lambda: self._run_test(draft))

    def _run_test(self, draft: Any) -> Any:
        """FON SAPINDA icra olunur — ÖZ sessiyasını açır (bax modul başlığı).

        Burada HEÇ BİR Qt widget-inə toxunulmur: widget-lər sap-təhlükəsiz
        deyil və nəticə onsuz da siqnalla əsas sapa qayıdır. Metod yalnız
        domen nəticəsini (`ConnectionTestResult` — dəyişməz dataclass)
        qaytarır, yəni saplar arasında keçən obyekt paylaşılan vəziyyət
        DAŞIMIR.
        """
        with self._context.session(user_id=self._actor.id) as session:
            return session.erp_connections.test_connection(
                actor=self._actor, draft=draft, now=_now()
            )

    def _show_test_result(self, wizard: Any, result: Any) -> None:
        """Uğurlu/uğursuz nəticə — ƏSAS SAPDA, olduğu kimi.

        ──────────────────────────────────────────────────────────────────────
        NƏTİCƏ OLDUĞU KİMİ GÖSTƏRİLİR — ÜMUMİLƏŞDİRİLMİR
        ──────────────────────────────────────────────────────────────────────
        `ConnectionTestResult.message` konnektorun QURDUĞU konkret səbəbdir:
        hansı qovluq tapılmadı, hansı sütun(lar) yoxdur, hansı kodlaşdırma
        oxunmadı, COM üçün baza adı (Ref) boşdur… Onu "bağlantı alınmadı" kimi
        bir cümləyə yığmaq 1c.md-nin generic-mesaj yasağını pozardı.

        `detail` DƏ ötürülür (əvvəl yalnız `app.log`-a gedirdi): fayl
        mübadiləsində o, faylda TAPILAN sütunların siyahısıdır, naməlum COM
        xətasında isə xam `HRESULT` — yəni nasazlığı axtaranın yeganə ipucu.
        """
        wizard.set_test_result(ok=result.ok, message=result.message, detail=result.detail)

    def _show_test_error(self, wizard: Any, error: BaseException) -> None:
        """Fon işində qalan istisna — SÜKUTLA UDULMUR.

        Domen istisnası öz hazır mətnini daşıyır və istifadəçi onu görməlidir
        (məs. səlahiyyət qapısı, lisenziya). Gözlənilməz istisnada isə mətn
        BİZİM qurduğumuz deyil və DSN/şifrə daşıya bilər — ona görə ekrana
        ümumi cümlə, `error.log`-a isə tam iz yazılır. `detail` YENƏ verilmir:
        həmin sahə ekranda göstərilir və sızma yolu olardı.
        """
        if isinstance(error, KompasOSError):
            wizard.set_test_result(ok=False, message=error.user_message)
            return
        _error_log.error("ERP_TEST_FAILED", exc_info=error)
        wizard.set_test_result(ok=False, message="Bağlantı yoxlanıla bilmədi. Yenidən cəhd edin.")

    def _on_save(self, screen: ErpServersScreen, payload: Any, *, server_id: Any) -> None:
        draft = _draft_from(payload)
        if draft is None:
            screen.show_error(
                title="Forma tamamlanmayıb",
                message=_missing_fields_message(payload),
            )
            return

        with _busy_cursor():
            try:
                with self._context.session(user_id=self._actor.id) as session:
                    self._persist(session, draft, server_id=server_id)
                    session.commit()
            except KompasOSError as error:
                # UĞURSUZ TEST DƏ BURAYA DÜŞÜR (`ConnectionNotVerifiedError`):
                # sətir YAZILMIR və istifadəçi səbəbi görür.
                screen.show_error(title="Server saxlanmadı", message=error.user_message)
                return
            except Exception:
                _error_log.exception("ERP_SERVER_SAVE_FAILED")
                screen.show_error(
                    title="Server saxlanmadı",
                    message="Konfiqurasiya yazılmadı. Yenidən cəhd edin.",
                )
                return

        self.refresh(screen)

    def _persist(self, session: Session, draft: Any, *, server_id: Any) -> None:
        if server_id is None:
            session.erp_connections.save_new(actor=self._actor, draft=draft, now=_now())
            return
        session.erp_connections.save_existing(
            actor=self._actor, server_id=server_id, draft=draft, now=_now()
        )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _now() -> Any:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC)


class _busy_cursor:  # noqa: N801 — kontekst meneceri, sinif deyil
    """Yadda saxlama üçün gözləmə kursoru — YALNIZ orada qalıb.

    Bağlantı testində ARTIQ İŞLƏDİLMİR: test fon işçisinə keçib və qum saatı
    "sistem məşğuldur, toxunma" mesajı verərdi, halbuki pəncərə həmin anda
    tam cavab verir. Yadda saxlama isə qısa, tranzaksiyalı və YARIMÇIQ
    kəsilməməli bir əməliyyatdır — orada gözləmə kursoru dürüst siqnaldır.

    Kursor `finally`-də HƏR HALDA geri qaytarılır — əks halda bir istisna
    bütün örtüyü qum saatı ilə qoyardı.
    """

    def __enter__(self) -> None:
        from PySide6.QtCore import Qt  # noqa: PLC0415
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *_exc: object) -> None:
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        QApplication.restoreOverrideCursor()


def _draft_from(payload: Any) -> Any:
    """Sihirbaz formasını `ErpServerDraft`-a çevirir — məcburi sahə boşdursa `None`.

    Çevirmə BURADA edilir, ekranda YOX: ekran domen tiplərini tanımır (bax
    `controllers/__init__.py`). Şifrə boş ola bilər — bəzi 1C quraşdırmaları
    Windows autentifikasiyası ilə işləyir və testin nəticəsi onsuz da bunu
    göstərəcək; onu burada rədd etsəydik, işləyən konfiqurasiyanı bloklamış
    olardıq.

    ──────────────────────────────────────────────────────────────────────────
    MƏCBURİ SAHƏLƏR NÖVDƏN ASILIDIR
    ──────────────────────────────────────────────────────────────────────────
    Fayl mübadiləsində 1C bazası ilə BİRBAŞA əlaqə yoxdur — orada baza adı
    (infobase) mənasızdır (`ConnectorType.requires_infobase`). COM-da isə o,
    yalnız klient-server rejimində məcburidir: fayl bazasında bağlantı sətri
    `File="…"` formasındadır və `Ref=` ümumiyyətlə yazılmır (bax
    `ComConnectionSettings.from_config`). Vahid "hər üç sahə doludursa"
    qaydası bu iki qanuni quraşdırmanı bloklayardı.
    """
    from src.domain.value_objects.erp import (  # noqa: PLC0415
        ConnectorConfig,
        ConnectorType,
        ErpServerDraft,
    )

    if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
        return None

    connector_type = ConnectorType.parse(str(payload.get("connector_type", "")))
    name = str(payload.get("name", "")).strip()
    raw_address = str(payload.get("host", "")).strip()
    infobase = str(payload.get("database", "")).strip()
    config = ConnectorConfig.from_dict(payload.get("config") or {})
    if not name or not raw_address:
        return None
    if _needs_infobase(connector_type, config) and not infobase:
        return None

    host, port = _host_and_port(connector_type, raw_address)
    return ErpServerDraft(
        server_name=name,
        host=host,
        port=port,
        username=str(payload.get("username", "")).strip(),
        password=str(payload.get("password", "")),
        infobase=infobase,
        connector_type=connector_type,
        connector_config=config,
        sync_interval_seconds=_interval_from(payload),
    )


def _needs_infobase(connector_type: Any, config: Any) -> bool:
    """Bu növ/konfiqurasiya üçün baza adı məcburidirmi (bax `_draft_from`)."""
    return bool(connector_type.requires_infobase) and not config.flag("file_mode")


def _host_and_port(connector_type: Any, raw_address: str) -> tuple[str, int]:
    """Ünvan sətrini `(host, port)`-a ayırır — YALNIZ HTTP üçün parse edilir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `_split_host_port` QEYRİ-HTTP YOLDA ÇAĞIRILMIR
    ──────────────────────────────────────────────────────────────────────────
    Həmin funksiya sətri SON iki nöqtədən bölür (`rpartition(":")`). COM-da
    ünvan `C:\\Bazalar\\Ticaret` ola bilər, fayl mübadiləsində isə
    `D:\\1c_exchange` — hər ikisində `:` sürücü hərfinin ayırıcısıdır, port
    deyil. Parse edilsəydi host `"C"`-yə çevrilər, qalan yol isə port kimi
    oxunmağa çalışılardı; nəticədə tam düzgün doldurulmuş forma yanlış yolla
    yadda saxlanardı və nasazlıq yalnız ilk sinxronizasiyada görünərdi.

    Port qeyri-HTTP növlərdə onsuz da mənasızdır — `ErpServerDraft` onu
    sentinel `0`-a normallaşdırır (`ConnectorType.uses_port`).
    """
    if not connector_type.uses_port:
        return (raw_address, 0)
    # Eyni «host:port» parsingi ilk quraşdırma sihirbazında da işlədilir;
    # ikinci nüsxə yazsaydıq, biri düzəldiləndə digəri arxada qalardı.
    from src.presentation.composition import _split_host_port  # noqa: PLC0415

    host, port = _split_host_port(raw_address)
    return (host, port)


def _interval_from(payload: Any) -> int | None:
    """Sihirbazdakı dövr — boş/sıfır dəyər `None` (növün defoltu tətbiq olunur)."""
    raw = str(payload.get("sync_interval", "")).strip()
    if not raw.isdigit():
        return None
    seconds = int(raw)
    return seconds or None


def _missing_fields_message(payload: Any) -> str:
    """Hansı sahələrin məcburi olduğunu NÖVƏ görə sadalayır.

    Sabit "Server adı, ünvan və baza adı doldurulmalıdır" cümləsi fayl
    serverində YANLIŞ olardı: orada baza adı sahəsi ümumiyyətlə yoxdur və
    istifadəçi mövcud olmayan bir sahəni axtarardı. Ünvan sahəsinin adı da
    növdən-növə dəyişir (`ConnectorType.address_label_az`), ona görə mesaj
    formada GÖRÜNƏN etiketi işlədir.
    """
    from src.domain.value_objects.erp import ConnectorConfig, ConnectorType  # noqa: PLC0415

    if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
        return "Bağlantı sahələri doldurulmalıdır."
    connector_type = ConnectorType.parse(str(payload.get("connector_type", "")))
    config = ConnectorConfig.from_dict(payload.get("config") or {})
    fields = ["Server adı", f"«{connector_type.address_label_az}»"]
    if _needs_infobase(connector_type, config):
        fields.append("baza adı")
    return f"{', '.join(fields[:-1])} və {fields[-1]} doldurulmalıdır."


def _server_view(row: Any) -> dict[str, str]:
    """Siyahı sətrinin EKRAN görünüşü — ŞİFRƏ YOXDUR (SEC-013).

    Ünvan `display_address_for` ilə qurulur, `f"{host}:{port}"` ilə YOX: fayl
    serverində port sentinel `0`-dır və sətir «\\\\anbar\\1c_exchange:0» kimi
    görünərdi (bax `ErpServer.display_address` docstring-i).
    """
    from src.domain.value_objects.erp import ConnectorType, display_address_for  # noqa: PLC0415

    connector_type = ConnectorType.parse(str(row["connector_type"] or ""))
    return {
        "name": str(row["server_name"]),
        "type": connector_type.label_az,
        "address": display_address_for(
            connector_type, str(row["host"] or ""), int(row["port"] or 0)
        ),
        "stores": f"{int(row['mapped_stores'] or 0)} mağaza",
        "latency": _latency_text(row),
        # Rəqəmin MƏNASI növdən-növə dəyişir — izahsız göstərmək yanıldıcıdır.
        "latency_meaning": connector_type.latency_meaning_az,
        "status": _status_text(row),
    }


def _server_rows(session: Session) -> list[Any]:
    """Server siyahısı — konfiqurasiya + sağlamlıq BİR sorğuda.

    `erp_servers` ilə `v_erp_server_health` birləşdirilir, çünki ekranın bir
    sətrində hər ikisindən sahə var (ünvan konfiqurasiyadan, gecikmə və
    sağlamlıq görünüşdən). İki ayrı sorğu eyni anın iki fərqli şəklini verə
    bilərdi. `password_encrypted` və `connector_config_encrypted` sütunları
    SEÇİLMİR (SEC-013) — konfiqurasiya yalnız redaktə anında, `_public_config`
    ilə və `security.log`-a düşən açıq bir çağırışla oxunur.
    """
    return session.uow.connection.execute(
        """
        SELECT s.id, s.server_name, s.host, s.port, s.status, s.last_successful_sync,
               s.connector_type, s.infobase, s.username, s.sync_interval_seconds,
               h.health, h.sync_delay_seconds, h.mapped_stores
          FROM erp_servers s
          JOIN v_erp_server_health h ON h.server_id = s.id
         WHERE s.tenant_id = %s
         ORDER BY s.server_name
        """,
        (session.tenant_id,),
    ).fetchall()


def _status_text(row: Any) -> str:
    """Cədvəldəki status nişanı — `v_erp_server_health.health` əsasında."""
    health = str(row["health"])
    return _STATUS_TEXT.get(health, health)


def _latency_text(row: Any) -> str:
    """Sinxron gecikməsi — deaktiv serverdə gecikmənin mənası yoxdur."""
    if str(row["health"]) == "INACTIVE":
        return "—"
    from src.presentation.controllers.screen_data import _sync_delay_text  # noqa: PLC0415

    return _sync_delay_text(row["sync_delay_seconds"])


def _sync_text(row: Any) -> str:
    moment = row["last_successful_sync"]
    return f"{moment:%H:%M}" if moment is not None else "heç vaxt"


def _mapping_note(mapped: int, servers: int) -> str:
    """Xəritələmə kartının altındakı izah.

    Xəritə BOŞDURSA bu, ən vacib xəbərdarlıqdır: gələn hər 1C sənədi
    `UNASSIGNED` olur və «Şübhəli Satışlar» növbəsinə düşür (bax
    `ErpConnectionWizardUseCase.mappings_for` docstring-i).
    """
    if servers == 0:
        return "Hələ heç bir 1C serveri əlavə edilməyib."
    if mapped == 0:
        return (
            "Heç bir mağaza serverə bağlanmayıb — gələn bütün satışlar "
            "«Şübhəli Satışlar» növbəsinə düşəcək."
        )
    return f"{mapped} mağaza xəritələnib."


__all__ = ["ErpServersController"]
