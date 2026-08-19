"""SEC-011 sessiya müddəti — CLIENT tərəfi (SEC-5 iş müqaviləsi).

──────────────────────────────────────────────────────────────────────────────
BU FAYL NƏ ETMİR — GÖRÜNMƏYƏN SƏRHƏD
──────────────────────────────────────────────────────────────────────────────
`docs/security_decisions.md` SEC-011 iki yarımçıq addımdan ibarətdir:
server-tərəfli sessiya (`auth_sessions`-a `issue`/`touch`/`revoke`/`validate`,
domen portu) VƏ client-tərəfli MƏCBURİ ÇIXIŞ (bu fayl). Bu modul YALNIZ
ikincisini edir — token yaratmır, bazaya yazmır, `auth_sessions` haqqında
HEÇ NƏ bilmir. Server portu (`domain` SEC-5 payı) hazır olanda `SessionGuard`
konstruktorundakı `touch` callback-i o porta bağlanacaq (bax `app.py::
_start_session_guard`); bu sinifin ÖZÜ dəyişməyəcək, çünki artıq bunu
GÖZLƏYƏN formada yazılıb.

Bunun BİLƏRƏKDƏN belə bölünməsinin səbəbi: hərəkətsizlik/mütləq-müddət
məcburi çıxışı server dəstəyi OLMADAN da işə düşə bilər (yerli taymer, yerli
qərar) və bu, HƏTTA bugünkü formada belə real təhlükəsizlik faydasıdır —
hazırda tətbiqdə HEÇ bir sessiya müddəti yoxdur. Server-tərəfli izləmə
(başqa cihazdan ləğv, DB sızıntısında oğurlanma qorunması) əlavə qatdır,
bu qatın YOXLUĞU aşağıdakı yerli qapını FAYDASIZ etmir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `QObject` + `eventFilter`, NİYƏ HƏR EKRANDA AYRI SİQNAL BAĞLAMASI DEYİL
──────────────────────────────────────────────────────────────────────────────
Fəaliyyət YALNIZ `AdminShell`-in konkret bir vidjetində yox, PƏNCƏRƏNİN HƏR
YERİNDƏ (dialoqlar daxil) baş verə bilər. Hər ekrana ayrıca "mən aktivəm"
siqnalı bağlasaydıq, YENİ ekran əlavə edən növbəti developer bunu unuda
bilərdi və həmin ekranda "işləyən" istifadəçi sükutla çıxarılardı — bu, ən
pis nasazlıq növüdür (sükutlu, nadir, reproduksiya çətin). `QApplication`-a
bir dəfə `installEventFilter` etmək bu riski KÖKÜNDƏN kəsir: yeni ekran heç
nə etmədən avtomatik əhatə olunur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `touch()` DIRNAQLANIR (THROTTLE) — PERF-1/2/3 DƏRSİ
──────────────────────────────────────────────────────────────────────────────
`QApplication`-a bağlı filtr HƏR siçan hərəkətini görür — aktiv fəaliyyət
zamanı saniyədə onlarla hadisə deməkdir. Hər hadisədə DB-yə gediş-gəliş
(composition.py PERF-3 ölçüsü: ~206 ms uzaq bazada) bütün panelı donduraraq
UI-1-in düzəltdiyi qüsuru YENİDƏN yaradardı — sadəcə fərqli səbəbdən. Ona
görə `touch()` YALNIZ soyuma pəncərəsi bitdikdən sonra YENİDƏN çağırıla
bilir (bax `_TOUCH_THROTTLE_DIVISOR`), yerli hərəkətsizlik taymeri isə HƏR
hadisədə sıfırlanır — bu, PULSUZ yerli əməliyyatdır, DB-yə getmir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `time.monotonic()` YOX, İKİNCİ `QTimer`
──────────────────────────────────────────────────────────────────────────────
Bütün vaxt idarəçiliyi Qt-nin öz taymer sisteminin İÇİNDƏ qalır — kodun
qalan hissəsi (`_upload_timer`, `_scheduler_timer`) da eyni naxışı işlədir.
İkinci saat mənbəyi (`time` modulu) əlavə etmək eyni işi iki fərqli üsulla
görməyin YARADACAĞI qarışıqlığa dəyməzdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEvent, QObject, QTimer, Signal

from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

_log = get_logger(__name__)

#: Fəaliyyət sayılan hadisə növləri. Siçan HƏRƏKƏTİ də daxildir — Windows
#: kilid ekranı və brauzerlərin idle-taymeri eyni konvensiyanı işlədir;
#: yalnız klik/klaviatura sayılsaydı, siçanı "tutub" ekrana baxan (məs.
#: sənəd oxuyan) istifadəçi haqsız yerə çıxarılardı.
_ACTIVITY_EVENT_TYPES: Final[frozenset[QEvent.Type]] = frozenset(
    {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseMove,
        QEvent.Type.KeyPress,
        QEvent.Type.Wheel,
    }
)

#: `touch()` dırnaqlama aralığı hərəkətsizlik pəncərəsinin bu PAYIDIR (1/6) —
#: sabit saniyə DEYİL, çünki Root pəncərəni dəyişəndə (`SystemLimits`) aralıq
#: da MÜTƏNASİB sürüşməlidir: qısa pəncərədə sabit 5 dəqiqəlik dırnaqlama
#: pəncərədən özü uzun ola bilərdi və server sessiyası HEÇ VAXT uzadılmazdı.
_TOUCH_THROTTLE_DIVISOR: Final = 6
#: Alt hədd — pəncərə çox qısa olsa belə saniyədə dəfələrlə DB-yə getmənin
#: qarşısını alır (riyazi zərurət, Root parametri deyil — CLAUDE.md §5
#: "ÜÇÜNCÜ hal" naxışı).
_TOUCH_THROTTLE_MIN_SECONDS: Final = 60


class SessionGuard(QObject):
    """Hərəkətsizlik + mütləq müddət qapısı — YALNIZ CLIENT tərəfi.

    Signals:
        expired: Sessiya bağlanmalıdır — arqument İSTİFADƏÇİYƏ göstərilə
            bilən Azərbaycan mətnidir (səbəb).

    Args:
        inactivity_minutes: Hərəkətsizlik həddi. `None` — YOXLANILMIR
            (CAMERA_DASHBOARD: "operator ekrana baxır, klikləmir").
        absolute_hours: Mütləq həd — HƏR kontekstdə var, fəaliyyətdən asılı
            olmayaraq bu vaxt keçəndə sessiya bağlanır.
        touch: Server-tərəfli sessiyani uzadan çağırış (SEC-5 domen portu).
            `None` — hələ BAĞLANMAYIB (bax modul başlığı); yerli qapı bundan
            asılı olmadan İŞLƏYİR.
        touch_throttle_seconds: `None` ötürülsə `inactivity_minutes`-dən
            törədilir (bax modul qeydi); `inactivity_minutes is None`-da
            işlədilmir, çünki touch-a ehtiyac yoxdur.
    """

    expired = Signal(str)

    def __init__(
        self,
        *,
        inactivity_minutes: int | None,
        absolute_hours: int,
        touch: Callable[[], None] | None = None,
        touch_throttle_seconds: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._touch = touch

        self._absolute_timer = QTimer(self)
        self._absolute_timer.setSingleShot(True)
        self._absolute_timer.setInterval(max(1, absolute_hours) * 3_600_000)
        self._absolute_timer.timeout.connect(
            lambda: self._expire("Sessiyanızın mütləq müddəti bitdi (SEC-011).")
        )

        self._inactivity_timer: QTimer | None = None
        self._touch_cooldown: QTimer | None = None
        self._touch_ready = True
        if inactivity_minutes is not None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(max(1, inactivity_minutes) * 60_000)
            timer.timeout.connect(
                lambda: self._expire("Hərəkətsizlik səbəbindən sessiyanız bağlandı (SEC-011).")
            )
            self._inactivity_timer = timer

            throttle = touch_throttle_seconds or max(
                _TOUCH_THROTTLE_MIN_SECONDS, (inactivity_minutes * 60) // _TOUCH_THROTTLE_DIVISOR
            )
            cooldown = QTimer(self)
            cooldown.setSingleShot(True)
            cooldown.setInterval(throttle * 1000)
            cooldown.timeout.connect(self._end_touch_cooldown)
            self._touch_cooldown = cooldown

    # ------------------------------- həyat dövrü ------------------------------ #

    def start(self) -> None:
        """Sayğacları işə salır — `KompasApplication.show_admin()` çağırır."""
        self._absolute_timer.start()
        if self._inactivity_timer is not None:
            self._inactivity_timer.start()

    def stop(self) -> None:
        """Bütün taymerləri dayandırır — logout/expiry-dən SONRA çağırılır.

        Obyektin ÖZÜ silinmir (`deleteLater` çağırılmır): çağıran hələ də
        `expired` siqnalını emal edir və Qt siqnal növbəsindəki gec gələn
        hadisə silinmiş obyektə TOXUNMAMALIDIR (`background_task.py`-dakı
        eyni əsaslandırma).
        """
        self._absolute_timer.stop()
        if self._inactivity_timer is not None:
            self._inactivity_timer.stop()
        if self._touch_cooldown is not None:
            self._touch_cooldown.stop()
        self._touch_ready = True

    # -------------------------------- fəaliyyət -------------------------------- #

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """`QApplication.installEventFilter(self)` ilə çağırılır.

        Hadisə HEÇ VAXT udulmur (`False` qaytarılır) — bu, MÜŞAHİDƏÇİDİR,
        maneə deyil. `True` qaytarsaydıq, hər klik/klaviatura hadisəsi
        widget-ə çatmadan BURADA dayanardı və bütün panel klikə cavab
        verməzdi.
        """
        if event.type() in _ACTIVITY_EVENT_TYPES:
            self.notify_activity()
        return False

    def notify_activity(self) -> None:
        """İstifadəçi fəaliyyəti — testlərdə DƏ birbaşa çağırıla bilər.

        Ayrıca metod olması TESTLƏNƏ BİLƏNLİK üçündür: sınaq real `QEvent`
        yaratmadan (Qt-nin daxili API-si) birbaşa fəaliyyəti simulyasiya edə
        bilir (`background_task.py`-dakı `InlineExecutor` ilə eyni məqsəd).
        """
        if self._inactivity_timer is not None:
            # `.start()` YENİDƏN başladır — mövcud sayğacı sıfırlayır. Bu,
            # PULSUZ yerli əməliyyatdır, DB-yə GETMİR.
            self._inactivity_timer.start()
        self._maybe_touch()

    def _maybe_touch(self) -> None:
        if self._touch is None or self._touch_cooldown is None or not self._touch_ready:
            return
        self._touch_ready = False
        self._touch_cooldown.start()
        try:
            self._touch()
        except Exception:
            # `touch()` YALNIZ SERVER sessiyasını uzadır — uğursuzluğu yerli
            # qapını POZMAMALIDIR: istifadəçi hələ də vaxtında çıxarılacaq,
            # sadəcə server tərəfi bir az geri qala bilər. Səbəb loga düşür.
            _log.exception("SESSION_TOUCH_FAILED")

    def _end_touch_cooldown(self) -> None:
        self._touch_ready = True

    def _expire(self, reason: str) -> None:
        _log.info("SESSION_GUARD_EXPIRED", extra={"reason": reason})
        self.expired.emit(reason)


__all__ = ["SessionGuard"]
