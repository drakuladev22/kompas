"""GUI fon-işçi naxışı — uzun əməliyyat Qt hadisə dövrəsini BLOKLAMIR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
Layihədə uzun əməliyyatı hadisə dövrəsindən kənarda icra edən naxış YOX İDİ və
bu boşluq üç yerdə eyni cür üzə çıxırdı:

    * ERP bağlantı testi cavab verməyən 1C serverində bütün örtüyü taymaut
      bitənə qədər dondururdu (`controllers/erp_servers.py` başlığı);
    * plugin səhifəsi `PluginSandbox.invoke`-un 10 saniyəyə qədər bloklaması
      ucbatından plugin kodunu ÜMUMİYYƏTLƏ icra etmirdi (`app.py::
      _plugin_page_factory`), yalnız elan olunmuş metadata göstərirdi;
    * hər gələcək ağır iş (Drive yükləməsi, aylıq hesabat) eyni divara
      dəyəcəkdi.

Naxış BİR DƏFƏ burada qurulur ki, hər istehlakçı öz sap idarəçiliyini
yenidən icad etməsin — ikinci nüsxə bir gün birincidən ayrılardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `QThreadPool` + `QRunnable`, NİYƏ XAM `threading.Thread` YOX
──────────────────────────────────────────────────────────────────────────────
Qt widget-ləri sap-təhlükəsiz DEYİL: `setText()` və ya `setEnabled()` yalnız
GUI sapından çağırıla bilər. Xam `threading.Thread` işlədilsəydi, nəticəni
ekrana yazmaq üçün onsuz da əsas sapa qayıtmaq mexanizmi lazım olardı — yəni
Qt-nin siqnal növbəsini əl ilə təkrar yazmalı olardıq. Qt siqnalı isə fon
sapından yayılanda avtomatik olaraq alıcının sapına POSTLANIR (queued
connection) və slot əsas sapda icra olunur. Beləliklə "nəticə siqnalla qayıdır"
qaydası mexanizmin ÖZÜNDƏN gəlir, bizim intizamımızdan yox.

`QThread`-in özü əvəzinə `QThreadPool` seçilib: hər test üçün yeni sap yaratmaq
(və sonra `quit()`/`wait()` ilə düzgün bağlamaq) klassik «QThread: Destroyed
while thread is still running» çökməsinin mənbəyidir. Hovuz sapları TƏKRAR
işlədir və ömrünü özü idarə edir — bizim bağlamalı heç nəyimiz qalmır.

`QRunnable` `QObject` deyil və siqnal yaya bilmir; ona görə hər buraxılış üçün
kiçik bir `_TaskSignals` daşıyıcısı qurulur (Qt for Python-un öz sənədləşdirdiyi
naxış).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAP ÖLDÜRÜLMÜR — LƏĞV = NƏTİCƏNİ RƏDD ETMƏK
──────────────────────────────────────────────────────────────────────────────
İstifadəçi sihirbazı bağlaya, yaxud testi YENİDƏN işə sala bilər. Qaçan sapı
zorla dayandırmaq üçün Qt-də (və Python-da) təhlükəsiz üsul YOXDUR: sap soketin
ortasında, kilidin altında və ya COM çağırışının içində ola bilər — onu kəsmək
bağlantını və ya prosesi zədələyər.

Ona görə burada ləğv İCRANI dayandırmır, NƏTİCƏNİ rədd edir: hər buraxılışa
artan bir nəsil nömrəsi (`token`) verilir və `_deliver()` yalnız SONUNCU
nəsli qəbul edir. Köhnəlmiş cavab sükutla atılır (yalnız `app.log`-a sətir
düşür). Fon işi öz taymautu ilə onsuz da bitəcək — sadəcə heç kimə təsir
etməyəcək.

Praktiki nəticə: ikinci testin cavabı birincidən TEZ gəlsə belə, ekranda
həmişə İSTİFADƏÇİNİN SONUNCU İSTƏYİNİN cavabı görünür.

──────────────────────────────────────────────────────────────────────────────
WIDGET ÖLÜMÜ — QT-NİN ÖZ ZƏMANƏTİ İŞLƏDİLİR
──────────────────────────────────────────────────────────────────────────────
`BackgroundTask` ekranın/dialoqun UŞAĞI kimi qurulur (`parent=`). Valideyn
məhv olanda Qt uşağı da məhv edir və:

    1. alıcısı məhv olmuş bütün bağlantılar AVTOMATİK qopur — daşıyıcının
       sonrakı `emit`-i heç kimə çatmır;
    2. `QObject` destruktoru həmin obyektə POSTLANMIŞ hadisələri də növbədən
       çıxarır (`removePostedEvents`), yəni artıq yolda olan queued nəticə də
       silinmiş widget-ə TOXUNMUR.

`deleteLater()` semantikası bu qorumanı ZƏİFLƏTMİR, sadəcə gecikdirir: widget
`deleteLater()` ilə DƏRHAL ölmür, hadisə dövrünün növbəti dövriyyəsində ölür.
Aralıqda o, hələ canlıdır və gec gələn nəticə ona ÇATA bilər — məhz buna görə
dialoq bağlananda `cancel()` çağırılır (bax `controllers/erp_servers.py`).
Yəni: `parent` çökməyə qarşı qoruyur, `cancel()` isə köhnə nəticənin bağlanmış
pəncərəni yenidən doldurmasına qarşı.

Daşıyıcı obyekt nəticə çatana qədər `_pending`-də SAXLANILIR: `QRunnable`
hovuz tərəfindən buraxıldıqdan sonra daşıyıcıya yeganə istinad ORADA qalır və
onsuz göndərən obyekt queued hadisə çatmamış zibil kimi toplana bilərdi.

──────────────────────────────────────────────────────────────────────────────
SESSİYA SAP SƏRHƏDİNİ KEÇMİR (CLAUDE.md bölmə 6 — ƏN VACİB İNCƏLİK)
──────────────────────────────────────────────────────────────────────────────
`context.session(...)` bir DB bağlantısı tutur. `psycopg` bağlantısı sap-
təhlükəsiz DEYİL: eyni bağlantını iki sapdan işlətmək protokol axınını
qarışdırır və nasazlıq özünü "gözlənilməz sorğu nəticəsi" kimi göstərir.

Ona görə qayda belədir: **fon işi öz sessiyasını ÖZÜ açır və ÖZÜ commit edir.**
Əsas sapda qurulmuş `Session` obyekti işə ÖTÜRÜLMÜR. Hovuz (`ConnectionPool`)
sap-təhlükəsizdir — hər sap öz bağlantısını götürür, yəni düzgün naxış heç bir
əlavə qiymət tələb etmir:

    def _job() -> Result:
        # BU FUNKSİYA FON SAPINDA İCRA OLUNUR.
        with context.session(user_id=actor.id) as session:
            outcome = session.some_use_case.do_work(...)
            session.commit()      # commit UNUDULARSA rollback olur
            return outcome

Yalnız OXUYAN iş (məs. bağlantı testi — `test_connection` heç nə yazmır)
commit etmir; sessiya bağlananda tranzaksiya geri qaytarılır və bu, düzgün
davranışdır.

Fon işi Qt widget-inə TOXUNMAMALIDIR. O, yalnız məlumat qaytarır; ekranı
`succeeded`/`failed` slotları (əsas sapda) yeniləyir.

──────────────────────────────────────────────────────────────────────────────
TESTLƏNƏ BİLƏNLİK
──────────────────────────────────────────────────────────────────────────────
İcraçı İNYEKSİYA edilir. `InlineExecutor` işi çağıran sapda dərhal icra edir və
nəticəni DİREKT bağlantı ilə çatdırır — yəni hadisə dövrü olmadan da bütün
məntiq (nəsil yoxlaması, istisna yolu, ləğv) yoxlana bilir və test heç vaxt
`sleep` gözləmir. `QT_QPA_PLATFORM=offscreen` altında testlər asmır, çünki
sinxron rejimdə heç bir sap yaranmır.

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ — PLUGIN SƏHİFƏSİ BUNU NECƏ MƏNİMSƏYƏCƏK
──────────────────────────────────────────────────────────────────────────────
`app.py::_plugin_page_factory` ƏVVƏL plugin kodunu icra ETMİRDİ, çünki
`PluginSandbox.invoke` `PLUGIN_SANDBOX_TIMEOUT_SECONDS`-ə qədər bloklayır.
Naxış tətbiq edildi (`controllers/plugin_page.py`) — səhifə əvvəlcə metadata
ilə açılır, məzmun isə arxada gəlir. Aşağıdakı eskiz həmin tətbiqin
sadələşdirilmiş formasıdır:

    from src.presentation.background_task import BackgroundTask

    screen = PluginPageScreen(self._theme, ...)
    # Səhifə DƏRHAL açılır: elan olunmuş metadata + "yüklənir" sətri.
    screen.set_rows([*metadata_rows, ("Məzmun", "Plugin cavabı gözlənilir…")])

    task = BackgroundTask(parent=screen, name="PLUGIN_PAGE")
    task.succeeded.connect(lambda payload: screen.set_rows(_rows(payload)))
    task.failed.connect(
        lambda error: screen.show_error(
            title="Plugin cavab vermədi",
            message="Səhifə məzmunu alınmadı — plugin-i Plugin İdarəetməsindən yoxlayın.",
        )
    )
    task.run(lambda: sandbox.invoke(page.plugin_name, "render"))

Diqqət: `task` üçün AYRICA istinad saxlanmır — o, `screen`-in uşağıdır və
ekranla birlikdə ölür (kontrollerlərin `lambda` bağlaması ilə eyni məntiq).
Səhifə bağlananda `cancel()` çağırmaq kifayətdir ki, gec gələn plugin cavabı
başqa ekrana yazılmasın.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal

from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """Fon işinin nəticəsi — sap sərhədini TƏK bir obyekt kimi keçir.

    Siqnalı üç ayrı arqumentlə elan etmək də mümkün idi, lakin queued
    bağlantıda hər arqument ayrıca marşallanır və "hansı sahə hansıdır"
    sualı çağırış yerində itir. Bir dəyişməz payload isə köhnəlmiş nəticənin
    yoxlanışını (`token`) nəticənin ÖZÜ ilə eyni yerdə saxlayır.

    `error` `None`-dursa iş uğurludur; əks halda `value` mənasızdır.
    """

    token: int
    value: object = None
    error: Exception | None = None


class TaskExecutor(Protocol):
    """İşin HARADA icra olunacağını təyin edən nöqtə (inyeksiya üçün)."""

    @property
    def runs_inline(self) -> bool:
        """`True` — iş çağıran sapda dərhal icra olunur (test rejimi).

        `BackgroundTask` bundan asılı olaraq nəticənin bağlantı tipini seçir:
        sinxron icrada queued bağlantı hadisə dövrü olmadan HEÇ VAXT
        çatmazdı, yəni test sonsuz gözləyərdi.
        """

    def submit(self, job: Callable[[], None]) -> None:
        """İşi icraya verir. `job` istisna ATMIR — o, artıq bükülmüşdür."""


class QtPoolExecutor:
    """Standart icraçı — Qt-nin qlobal sap hovuzu.

    Hovuz qəsdən qlobaldır: GUI-də eyni anda qaçan fon işlərinin sayı təbii
    olaraq azdır (bir bağlantı testi, bir plugin çağırışı) və hər istehlakçı
    üçün ayrıca hovuz saxlamaq sap sayını izahsız artırardı. Ayrı hovuz lazım
    olarsa (məs. ağır hesabat axını GUI işlərini gözlətməsin deyə) o,
    konstruktora ötürülə bilər.
    """

    def __init__(self, pool: QThreadPool | None = None) -> None:
        self._pool = pool

    @property
    def runs_inline(self) -> bool:
        return False

    def submit(self, job: Callable[[], None]) -> None:
        pool = self._pool if self._pool is not None else QThreadPool.globalInstance()
        pool.start(_JobRunnable(job))


class InlineExecutor:
    """Sinxron icraçı — testlər və hadisə dövrü olmayan mühitlər üçün.

    İş ÇAĞIRAN sapda icra olunur, yəni `run()` qayıtdıqda nəticə artıq
    çatdırılmış olur. Bu, "sap testi" ilə "məntiq testi"ni ayırır: nəsil
    yoxlaması, istisna yolu və ləğv heç bir vaxt gözləməsi olmadan yoxlanır
    (qeyri-sabit test heç bir testdən pisdir).
    """

    @property
    def runs_inline(self) -> bool:
        return True

    def submit(self, job: Callable[[], None]) -> None:
        job()


class _JobRunnable(QRunnable):
    """`QThreadPool`-un icra vahidi — sadəcə verilmiş bükücünü çağırır."""

    def __init__(self, job: Callable[[], None]) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:
        try:
            self._job()
        except Exception:
            # Bura NORMALDA düşmür: `_capture()` bütün istisnaları tutub
            # `failed` siqnalına çevirir. Yenə də son qoruyucu qalır — hovuz
            # sapında qaçan istisna Python-da sükutla sapı bitirər və nəticə
            # HEÇ VAXT gəlməzdi, yəni ekran əbədi «Yoxlanılır…» qalardı.
            _error_log.exception("BACKGROUND_TASK_RUNNABLE_FAILED")


class _TaskSignals(QObject):
    """Fon sapından əsas sapa keçidin YEGANƏ körpüsü.

    Ayrıca obyektdir, çünki `QRunnable` `QObject` deyil. Ömrü `BackgroundTask.
    _pending`-də saxlanılır — səbəbi modul başlığındadır.
    """

    done = Signal(object)


class BackgroundTask(QObject):
    """Bir növ uzun əməliyyatı fonda icra edən və nəticəsini siqnalla qaytaran işçi.

    Signals:
        started: İş buraxıldı (busy vəziyyətini qurmaq üçün).
        succeeded: İş uğurla bitdi — payload işin qaytardığı dəyərdir.
        failed: İş istisna ilə bitdi — payload `Exception` obyektidir.
        finished: Uğur/uğursuzluqdan ASILI OLMAYARAQ nəticə çatdırıldı.

    Bir nüsxə BİR NÖV iş üçündür (məs. «bağlantı testi»). Eyni nüsxə ilə
    ardıcıl buraxılışlar mümkündür: yenisi köhnənin nəticəsini avtomatik
    köhnəldir.

    Ləğv edilmiş və ya köhnəlmiş buraxılış üçün HEÇ BİR siqnal yayılmır —
    `finished` də daxil. Səbəb: `finished` adətən busy vəziyyətini SÖNDÜRÜR,
    köhnəlmiş cavab isə HƏLƏ QAÇAN yeni işin spinnerini söndürərdi.
    """

    started = Signal()
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        *,
        parent: QObject | None = None,
        executor: TaskExecutor | None = None,
        name: str = "",
    ) -> None:
        """Fon işçisini qurur.

        Args:
            parent: Ömrü idarə edən Qt valideyni — adətən ekran və ya dialoq.
                Verilməsi TÖVSİYƏ OLUNUR: valideyn öləndə gec gələn nəticə
                avtomatik atılır (bax modul başlığı).
            executor: İcraçı. Defolt `QtPoolExecutor`; testlərdə
                `InlineExecutor`.
            name: Jurnal sətirlərində görünən iş adı (məs. `ERP_TEST`).
                Diaqnostika üçündür — istifadəçiyə göstərilmir.
        """
        super().__init__(parent)
        self._executor: TaskExecutor = executor if executor is not None else QtPoolExecutor()
        self._name = name or "BACKGROUND_TASK"
        #: Sonuncu buraxılışın nömrəsi — hər `run()` onu artırır.
        self._generation = 0
        #: Nəticəsi hələ GÖZLƏNİLƏN buraxılış (`None` = gözlənilən yoxdur).
        self._active: int | None = None
        #: token → daşıyıcı. Daşıyıcı nəticə çatana qədər burada YAŞAYIR.
        self._pending: dict[int, _TaskSignals] = {}

    # ------------------------------- vəziyyət -------------------------------- #

    @property
    def is_running(self) -> bool:
        """Nəticəsi gözlənilən buraxılış varmı.

        Düymənin deaktivliyi ekranın işidir; bu bayraq isə kontrollerə ikiqat
        buraxılışı RƏDD ETMƏK imkanı verir — klaviatura qısayolu düymənin
        deaktivliyini yan keçə bilər.
        """
        return self._active is not None

    @property
    def generation(self) -> int:
        """Sonuncu buraxılışın nömrəsi (diaqnostika və testlər üçün)."""
        return self._generation

    # -------------------------------- icra ----------------------------------- #

    def run(self, job: Callable[[], object]) -> int:
        """İşi buraxır və nəsil nömrəsini qaytarır.

        `job` FON SAPINDA icra olunur, ona görə:

            * Qt widget-inə TOXUNMAMALIDIR (widget-lər sap-təhlükəsiz deyil);
            * öz DB sessiyasını ÖZÜ açmalıdır (bax modul başlığı);
            * qaytardığı dəyər `succeeded` ilə əsas sapa keçir.

        Əvvəlki buraxılış hələ qaçırsa DAYANDIRILMIR — sadəcə nəticəsi
        köhnəlir və atılır.
        """
        self._generation += 1
        token = self._generation
        self._active = token

        signals = _TaskSignals()
        self._pending[token] = signals
        # Bağlantı tipi AÇIQ verilir, avtomatikə buraxılmır: hovuz rejimində
        # nəticə mütləq əsas sapa POSTLANMALIDIR (widget-lər sap-təhlükəsiz
        # deyil), sinxron rejimdə isə hadisə dövrü olmaya bilər və queued
        # nəticə heç vaxt çatmazdı.
        connection = (
            Qt.ConnectionType.DirectConnection
            if self._executor.runs_inline
            else Qt.ConnectionType.QueuedConnection
        )
        signals.done.connect(self._deliver, connection)

        # `started` işin ÖZÜNDƏN ƏVVƏL yayılır: sinxron icraçıda `submit()`
        # nəticəni dərhal çatdırır, yəni sonraya qoysaydıq busy vəziyyəti
        # nəticədən SONRA qurulardı və ekran əbədi «Yoxlanılır…» qalardı.
        self.started.emit()
        _log.debug("BACKGROUND_TASK_STARTED", extra={"task": self._name, "token": token})
        self._executor.submit(_capture(job, signals, token))
        return token

    def cancel(self) -> None:
        """Gözlənilən nəticəni RƏDD edir — icranı dayandırmır (bax modul başlığı).

        Dialoq bağlananda, ekran dəyişəndə və ya yeni sorğudan əvvəl çağırılır.
        Gözlənilən iş yoxdursa heç nə etmir.
        """
        if self._active is None:
            return
        _log.debug("BACKGROUND_TASK_CANCELLED", extra={"task": self._name, "token": self._active})
        self._active = None

    # ------------------------------ çatdırılma -------------------------------- #

    def _deliver(self, outcome: object) -> None:
        """Nəticəni ƏSAS SAPDA qəbul edir və köhnəlmişi süzür."""
        if not isinstance(outcome, TaskOutcome):  # pragma: no cover - tip qoruyucusu
            return
        # Daşıyıcı ARTIQ lazım deyil — köhnəlmiş nəticədə də buraxılır, əks
        # halda hər ləğv edilmiş buraxılış bir obyekt sızdırardı.
        self._pending.pop(outcome.token, None)
        if outcome.token != self._active:
            _log.debug(
                "BACKGROUND_TASK_STALE_RESULT",
                extra={"task": self._name, "token": outcome.token},
            )
            return

        self._active = None
        try:
            if outcome.error is not None:
                self.failed.emit(outcome.error)
            else:
                self.succeeded.emit(outcome.value)
        finally:
            # `finally` MƏCBURİDİR: `succeeded` abunəçisində qalan bir istisna
            # busy vəziyyətini əbədi açıq qoyardı — yəni bir ekran qüsuru
            # düyməni birdəfəlik deaktiv edərdi.
            self.finished.emit()


def _capture(job: Callable[[], object], signals: _TaskSignals, token: int) -> Callable[[], None]:
    """İşi nəticə/xəta daşıyıcısına bükür — FON SAPINDA icra olunacaq hissə.

    İstisna SÜKUTLA UDULMUR: tutulur, `TaskOutcome.error`-a qoyulur və eyni
    kanalla geri qaytarılır. Beləliklə istifadəçi "heç nə baş vermədi"
    vəziyyətində qalmır — səbəbi göstərmək artıq abunəçinin işidir.

    Bura `except Exception` yazılır, `BaseException` YOX: `KeyboardInterrupt`
    və `SystemExit` prosesin dayanma siqnalıdır və onları nəticəyə çevirmək
    bağlanmanı gecikdirərdi.
    """

    def _run() -> None:
        try:
            value = job()
        except Exception as error:
            signals.done.emit(TaskOutcome(token=token, error=error))
            return
        signals.done.emit(TaskOutcome(token=token, value=value))

    return _run


__all__ = [
    "BackgroundTask",
    "InlineExecutor",
    "QtPoolExecutor",
    "TaskExecutor",
    "TaskOutcome",
]
