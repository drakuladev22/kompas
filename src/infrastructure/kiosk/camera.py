"""Kiosk veb-kamerası — `CameraCapture` portunun tətbiqi (`facecontrol.md` Faza 3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ OpenCV (`opencv-python-headless`), NİYƏ Qt Multimedia DEYİL
──────────────────────────────────────────────────────────────────────────────
PySide6 layihədə onsuz da var və `QCamera`/`QImageCapture` ilə kadr almaq
MÜMKÜNDÜR. Rədd edilməsinin üç səbəbi var:

  1. Qt-nin çəkiliş API-si HADİSƏ-ƏSASLIDIR (`imageCaptured` siqnalı) və
     işləyən bir Qt hadisə dövrəsi tələb edir. `CameraCapture.capture()` isə
     SİNXRON müqavilədir — Qt ilə onu ödəmək üçün iç-içə hadisə dövrəsi
     lazım gələrdi; bu, GUI-də donma və təkrar-giriş qüsurlarının klassik
     mənbəyidir.
  2. Bu, İNFRASTRUKTUR qatıdır. Qt-ni bura gətirmək kamera sürücüsünü
     təqdimat çərçivəsinə bağlayardı — halbuki üz qeydiyyatı gələcəkdə
     GUI-siz (skript/servis) da çağırıla bilər.
  3. `cv2.VideoCapture` Windows-da DirectShow/MSMF backend-lərini birbaşa
     işlədir və bloklayan `read()` verir — port müqaviləsinin tam qarşılığı.

NİYƏ `opencv-python-headless`, NİYƏ ADİ `opencv-python`
──────────────────────────────────────────────────────────────────────────────
Adi `opencv-python` ÖZ Qt kitabxanalarını daşıyır (cv2-nin `imshow` pəncərəsi
üçün). Eyni prosesdə PySide6 ilə yanaşı olduqda idxal anında
`QT_QPA_PLATFORM_PLUGIN_PATH` cv2-nin plugin qovluğuna yönəldilir və PySide6
"could not load the Qt platform plugin windows" ilə çökür — PyInstaller
paketində bu, ən çətin diaqnoz edilən nasazlıqlardandır. `headless` variantı
məhz həmin GUI backend-lərini daşımır; bizə lazım olan yalnız `VideoCapture`
-dir və o, hər ikisində eynidir.

──────────────────────────────────────────────────────────────────────────────
BƏND 5 — NASAZLIQ SÜKUTLA "YALNIZ PIN"Ə ÇEVRİLMİR
──────────────────────────────────────────────────────────────────────────────
Bu modulda "kamera yoxdursa üz təsdiqini keç" YOLU YOXDUR. İki ayrı siqnal
var və hər ikisi çağırana AÇIQ şəkildə çatır:

  * `is_available() -> False` — cihaz açıla bilmir. Use case bunu MÖVCUD
    eskalasiya kanalına (`VERIFICATION_TIMEOUT`) yönləndirir və System Health
    Monitor-a yazır.
  * `CameraUnavailableError` — cihaz açılmışdı, lakin çəkiliş ortasında
    itdi (kabel çıxdı, sürücü çökdü). İSTİSNA ATILIR, boş siyahı QAYTARILMIR:
    boş siyahı `NO_FACE_DETECTED` kimi oxunardı, yəni avadanlıq nasazlığı
    "işıq zəifdir" kimi görünər və heç vaxt eskalasiya olunmazdı.

──────────────────────────────────────────────────────────────────────────────
HƏRƏKƏT PƏNCƏRƏSİ — NİYƏ "ƏN ÇOX DƏYİŞƏN KADR"
──────────────────────────────────────────────────────────────────────────────
Doğrulamada port TƏK kadr istəyir, canlılıq hərəkəti isə (göz qırpma ~0.3 s)
təsadüfi bir anda baş verir. Göstəriş görünən kimi bir kadr çəksəydik,
vicdanlı işçinin qırpması demək olar heç vaxt tutulmazdı və liveness yoxlaması
faktiki olaraq "hamını rədd edən" qorumaya çevrilərdi.

Ona görə hərəkət tələb olunanda adapter qısa bir pəncərədə bir NEÇƏ kadr
oxuyur və pəncərənin BİRİNCİ (neytral) kadrından ƏN ÇOX FƏRQLƏNƏNİ qaytarır.
Bu, sadə piksel statistikasıdır (landmark/kitabxana lazım deyil) və birbaşa
anti-fraud işi görür: kameraya tutulmuş TƏRPƏNMƏYƏN fotoşəkil bütün pəncərədə
eyni qalır, yəni qaytarılan kadr neytral olur və mühərrikin hərəkət yoxlaması
onu rədd edir.

──────────────────────────────────────────────────────────────────────────────
KADR MÜQAVİLƏSİ
──────────────────────────────────────────────────────────────────────────────
`FaceFrame.payload` sıxılmamış, sətir-ardıcıl RGB888-dir. OpenCV BGR qaytarır,
ona görə kanal sırası ÇEVRİLİR — çevirməsək məsafələr sistematik olaraq
pozulardı və qüsur "dəqiqlik nədənsə aşağıdır" formasında gizlənərdi.
Müqavilənin oxuyan tərəfi `infrastructure/security/face_matcher.py`-dədir.

──────────────────────────────────────────────────────────────────────────────
BU MODULDAKI ƏDƏDLƏR NİYƏ ROOT PARAMETRİ DEYİL
──────────────────────────────────────────────────────────────────────────────
İstiləşmə kadrlarının sayı, kadrlar arası fasilə və hərəkət pəncərəsinin
uzunluğu AVADANLIQ parametrləridir: heç biri "kimin keçdiyi" qərarını
dəyişmir — nə həddi, nə vektoru, nə keyfiyyət tərifini. Üstəlik bənd 18 onları
ROOT ekranına çıxarmağı BİRBAŞA arzuolunmaz edir: orada görünsəydilər,
"doğrulama yavaşdır" şikayətinin ən asan həlli məhz onları kiçiltmək olardı —
yəni performans monitorinqi təhlükəsizlik güzəştinə çevrilərdi, halbuki bənd 18
bunu açıq qadağan edir.

Konstruktor parametrləri kimi AÇIQ saxlanılır ki, fərqli kamera modeli üçün
quraşdırma zamanı (kodda, nəzarətli şəkildə) dəyişdirilə bilsinlər.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.face_recognition import FaceFrame
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.face_recognition import (
        FaceEmbedding,
        FaceSample,
        LivenessGesture,
    )

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

# İdxal `face_matcher.py`-dəki ilə EYNİ naxışdadır: modul səviyyəsində, lakin
# uğursuzluq `import`-un özünü çökdürmür — `is_available()` `False` qaytarır və
# axın eskalasiyaya düşür (bənd 5), sükutla PIN-only rejimi YARANMIR.
try:
    # `cv2` ÖZ tip-stub-larını daşıyır (`cv2/__init__.pyi`), ona görə burada
    # `type: ignore` YOXDUR — `face_recognition`-dan fərqli olaraq (o, stub-suz
    # gəlir və orada susdurma məcburidir).
    import cv2
    import numpy as np

    _IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # pragma: no cover — quraşdırılmış mühitdə işə düşmür
    _IMPORT_ERROR = exc


class CameraUnavailableError(KompasOSError):
    """Kiosk kamerası açıla bilmir və ya çəkiliş ortasında itdi."""

    user_message = "Kiosk kamerası əlçatmazdır. Bağlantını yoxlayın."


#: Cihaz açıldıqdan sonra ATILAN kadr sayı. Veb-kameraların avtomatik
#: ekspozisiya/balans alqoritmi ilk kadrlarda hələ oturmayıb — həmin kadrlar
#: qaranlıq/yaşıl çıxır və keyfiyyət ölçüsünü (bənd 1) haqsız yerə aşağı
#: salardı. Avadanlıq sabitidir (bax modul başlığı).
DEFAULT_WARMUP_FRAMES: Final[int] = 5

#: Qeydiyyat kadrları arasındakı fasilə (saniyə). SIFIR OLA BİLMƏZ: ardıcıl
#: oxunan kadrlar praktiki olaraq EYNİ olardı və bənd 11-in çox-kadr ortası
#: heç bir təsadüfi xətanı azaltmazdı — "beş kadr" adı daşıyan, faktiki olaraq
#: tək kadrlıq qeydiyyat alınardı.
DEFAULT_FRAME_INTERVAL_SECONDS: Final[float] = 0.25

#: Canlılıq hərəkəti üçün müşahidə pəncərəsi (saniyə) və orada oxunan kadr
#: sayı. Pəncərə insanın göstərişi oxuyub hərəkəti etməsinə kifayət etməlidir.
DEFAULT_GESTURE_WINDOW_SECONDS: Final[float] = 1.5
DEFAULT_GESTURE_FRAMES: Final[int] = 12


class OpenCvCameraCapture:
    """USB/inteqrasiya olunmuş veb-kameradan kadr çəkir — DİSKƏ YAZMIR.

    ──────────────────────────────────────────────────────────────────────────
    CİHAZ NİYƏ AÇIQ SAXLANILIR
    ──────────────────────────────────────────────────────────────────────────
    `cv2.VideoCapture` açılışı Windows-da 0.3–1.0 saniyə çəkir. Hər çağırışda
    açıb-bağlasaydıq, `is_available()` + `capture()` cütü hər doğrulamaya iki
    belə gecikmə əlavə edərdi və bənd 18-in xəbərdarlıq həddi (defolt 5 s)
    təkcə cihaz açılışından dolardı.

    Kiosk PC-də kamera BU tətbiqə həsr olunub, yəni tutulu saxlamaq başqa
    proqramı əngəlləmir. Cihaz itdikdə (kabel çıxdı) tutacaq buraxılır və
    növbəti `is_available()` yenidən açmağa çalışır — yəni "açıq saxlama"
    nasazlığı gizlətmir.
    """

    def __init__(
        self,
        *,
        device_index: int = 0,
        frame_width: int = 640,
        frame_height: int = 480,
        warmup_frames: int = DEFAULT_WARMUP_FRAMES,
        frame_interval_seconds: float = DEFAULT_FRAME_INTERVAL_SECONDS,
        gesture_window_seconds: float = DEFAULT_GESTURE_WINDOW_SECONDS,
        gesture_frames: int = DEFAULT_GESTURE_FRAMES,
    ) -> None:
        """Adapteri qurur — CİHAZA TOXUNMUR.

        Konstruktor cihazı AÇMIR: `composition.py` obyekt qrafını örtük
        açılışında qurur və orada bir saniyəlik kamera açılışı bütün tətbiqin
        başlanğıcını gecikdirərdi. Açılış ilk `is_available()` çağırışındadır.
        """
        self._device_index = device_index
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._warmup_frames = warmup_frames
        self._frame_interval = frame_interval_seconds
        self._gesture_window = gesture_window_seconds
        self._gesture_frames = max(2, gesture_frames)
        self._device: Any = None

    # ------------------------------- port səthi ------------------------------ #

    def is_available(self) -> bool:
        """Kamera fiziki olaraq bağlıdır və açıla bilirmi.

        İSTİSNA ATMIR — sual məhz "işləyirmi?" olduğu üçün cavab `bool`-dur.
        `False` çağıran tərəfdə eskalasiyaya çevrilir (bənd 5), yəni səssiz
        keçid yaranmır.
        """
        if _IMPORT_ERROR is not None:
            _error_log.error(
                "FACE_CAMERA_LIBRARY_MISSING",
                extra={"error": str(_IMPORT_ERROR)},
            )
            return False
        try:
            return self._ensure_device() is not None
        except Exception as exc:
            # Sürücü səviyyəsindəki gözlənilməz xəta da "əlçatmaz"dır — lakin
            # səbəbi jurnalda qalmalıdır, əks halda System Health Monitor-un
            # xəbərdarlığı araşdırıla bilməzdi.
            _error_log.exception("FACE_CAMERA_PROBE_FAILED", extra={"error": str(exc)})
            self._release()
            return False

    def capture(self, *, count: int = 1, gesture: LivenessGesture | None = None) -> list[FaceFrame]:
        """Kadr(lar) çəkir — YALNIZ YADDAŞDA, heç bir fayl yaranmır.

        `gesture` verilibsə hərəkət pəncərəsi rejimi işləyir (modul başlığı):
        bir neçə kadr oxunur və neytral kadrdan ƏN ÇOX FƏRQLƏNƏNİ qaytarılır.
        `gesture is None` (qeydiyyat) halında isə `count` sayda kadr FASİLƏ ilə
        oxunur — bənd 11-in ortalaması yalnız fərqli kadrlarda mənalıdır.
        """
        device = self._ensure_device()
        if device is None:
            raise CameraUnavailableError(
                "Kiosk kamerası açıla bilmədi",
                context={"device_index": self._device_index},
            )
        if gesture is not None:
            return [self._capture_gesture_frame()]
        frames: list[FaceFrame] = []
        for index in range(max(1, count)):
            # FASİLƏ BİRİNCİ KADRDAN ƏVVƏL VERİLMİR: cihaz onsuz da
            # istiləşdirilib və əlavə gözləmə hər qeydiyyata mənasız gecikmə
            # əlavə edərdi.
            if index:
                time.sleep(self._frame_interval)
            frames.append(self._read_frame())
        return frames

    def close(self) -> None:
        """Cihaz tutacağını buraxır — tətbiq bağlananda çağırılır.

        İDEMPOTENTDİR: iki dəfə çağırmaq xəta vermir, çünki bağlanma yolu
        (pəncərə bağlanması, çökmə emalı) bir neçə yerdən keçə bilər.
        """
        self._release()

    # ------------------------------- daxili ---------------------------------- #

    def _ensure_device(self) -> Any:
        """Cihazı (lazımdırsa) açır və istiləşdirir. Açıla bilmirsə `None`."""
        if _IMPORT_ERROR is not None:
            return None
        if self._device is not None:
            return self._device
        # `CAP_DSHOW` QƏSDƏN SEÇİLİB: Windows-da defolt MSMF backend-i bəzi
        # UVC kameralarda ilk `read()`-də 3–5 saniyə gözlədir və ya boş kadr
        # verir. DirectShow həmin kameralarda dərhal işləyir və hər iki backend
        # eyni RGB məlumatı qaytarır.
        device = cv2.VideoCapture(self._device_index, cv2.CAP_DSHOW)
        if not device.isOpened():
            device.release()
            _log.warning("FACE_CAMERA_NOT_OPENED", extra={"device_index": self._device_index})
            return None
        device.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_width)
        device.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_height)
        self._device = device
        self._warm_up()
        return self._device

    def _warm_up(self) -> None:
        """İlk kadrları atır (avtomatik ekspozisiya oturana qədər).

        Uğursuz oxu BURADA istisna ATMIR: istiləşmə "ən yaxşı cəhd"dir və
        cihaz həqiqətən ölübsə bunu növbəti FAKTİKİ oxu (`_read_frame`)
        aydın istisna ilə bildirəcək. İstiləşmədə istisna atsaydıq,
        `is_available()` `bool` müqaviləsini poza bilərdi.
        """
        for _ in range(max(0, self._warmup_frames)):
            self._device.read()

    def _read_frame(self) -> FaceFrame:
        """Bir kadr oxuyur və RGB888 `FaceFrame`-ə çevirir."""
        if self._device is None:
            raise CameraUnavailableError(
                "Kamera tutacağı bağlıdır",
                context={"device_index": self._device_index},
            )
        ok, frame = self._device.read()
        if not ok or frame is None:
            # AVADANLIQ NASAZLIĞI — boş siyahı DEYİL, istisna (bax modul
            # başlığı, bənd 5). Tutacaq buraxılır ki, növbəti `is_available()`
            # cihazı yenidən yoxlasın və vəziyyət "yapışıb qalmasın".
            self._release()
            raise CameraUnavailableError(
                "Kameradan kadr oxunmadı — cihaz çəkiliş zamanı itdi",
                context={"device_index": self._device_index},
            )
        return _to_face_frame(frame)

    def _capture_gesture_frame(self) -> FaceFrame:
        """Hərəkət pəncərəsində ƏN ÇOX DƏYİŞƏN kadrı qaytarır (modul başlığı)."""
        interval = self._gesture_window / self._gesture_frames
        baseline_bgr: Any = None
        best_frame: FaceFrame | None = None
        best_score = -1.0
        for index in range(self._gesture_frames):
            if index:
                time.sleep(interval)
            ok, frame = self._device.read()
            if not ok or frame is None:
                self._release()
                raise CameraUnavailableError(
                    "Hərəkət pəncərəsində kadr oxunmadı — cihaz itdi",
                    context={"device_index": self._device_index},
                )
            if baseline_bgr is None:
                baseline_bgr = frame.astype(np.float32)
                best_frame = _to_face_frame(frame)
                best_score = 0.0
                continue
            score = float(np.abs(frame.astype(np.float32) - baseline_bgr).mean())
            if score > best_score:
                best_score = score
                best_frame = _to_face_frame(frame)
        if best_frame is None:  # pragma: no cover — dövr ən azı bir kadr verir
            raise CameraUnavailableError(
                "Hərəkət pəncərəsi boş qaldı",
                context={"device_index": self._device_index},
            )
        # BAL JURNALA YAZILIR, KADR YOX: "hərəkət nə qədər güclü idi" sualı
        # sonradan (şəkil hücumu araşdırmasında) lazım olur, kadrın özü isə
        # heç vaxt yazılmır (migrations/047-nin birinci qaydası).
        _log.info("FACE_GESTURE_WINDOW", extra={"motion_score": round(best_score, 3)})
        return best_frame

    def _release(self) -> None:
        device, self._device = self._device, None
        if device is not None:
            try:
                device.release()
            except Exception:  # pragma: no cover — sürücü buraxılışı nadir hallarda çökür
                _error_log.exception("FACE_CAMERA_RELEASE_FAILED")


def _to_face_frame(frame: Any) -> FaceFrame:
    """OpenCV BGR massivini RGB888 `FaceFrame`-ə çevirir.

    `np.ascontiguousarray` MƏCBURİDİR: `[:, :, ::-1]` dilimi TƏRS addımlı
    (negative stride) baxış verir və `tobytes()` onu C-sırasında düzləşdirsə
    də, aralıq nüsxə olmadan bəzi numpy versiyalarında əməliyyat baha başa
    gəlir. Açıq nüsxə həm sürəti, həm də bayt sırasını proqnozlaşdırılan edir.
    """
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    return FaceFrame(payload=rgb.tobytes(), width=width, height=height)


class UnavailableFaceEngine:
    """Mühərrik/kamera qurula bilmədikdə işə düşən FAIL-SAFE adapter.

    ──────────────────────────────────────────────────────────────────────────
    BU, PLACEHOLDER DEYİL — BƏND 5-İN TƏTBİQİDİR
    ──────────────────────────────────────────────────────────────────────────
    `face_recognition` və ya `cv2` yüklənə bilmirsə iki pis variant var:
    (a) tətbiqi ümumiyyətlə açmamaq — mağaza işləməz olur, halbuki üz təsdiqi
    sistemin YALNIZ BİR qatıdır; (b) üz təsdiqini sükutla keçmək — bənd 5-in
    məhz qadağan etdiyi «yalnız PIN» rejimi.

    Doğru cavab üçüncüsüdür: kamera ƏLÇATMAZ elan olunur və mövcud eskalasiya
    kanalı işə düşür — hər giriş/qayıdış HR_Admin/CEO-nun manual təsdiqinə
    gedir. Yəni sistem işləyir, lakin ÜZ QAPISININ YERİNƏ İNSAN QAPISI qoyulur.

    HƏR İKİ PORTU ÖDƏYİR (`CameraCapture` + `FaceMatcher`) ki, `composition.py`
    tək obyektlə hər iki asılılığı bağlaya bilsin. `capture`/`extract`/
    `distance` metodları praktiki olaraq ƏLÇATMAZDIR (hər iki axın əvvəlcə
    `is_available()` soruşur), lakin yenə də İSTİSNA ATIRLAR: səssiz boş
    nəticə qaytarsaydılar, gələcəkdə yaranan bir sıra səhvi üz təsdiqini
    sükutla söndürərdi.
    """

    def __init__(self, *, reason: str) -> None:
        self._reason = reason

    def is_available(self) -> bool:
        """HƏMİŞƏ `False` — çağıran tərəf eskalasiya edir (bənd 5)."""
        return False

    def capture(self, *, count: int = 1, gesture: LivenessGesture | None = None) -> list[FaceFrame]:
        raise CameraUnavailableError(
            "Üz təsdiqi mühərriki əlçatmazdır",
            context={"reason": self._reason, "count": count},
        )

    def extract(self, frame: FaceFrame, *, gesture: LivenessGesture | None = None) -> FaceSample:
        raise CameraUnavailableError(
            "Üz təsdiqi mühərriki əlçatmazdır",
            context={"reason": self._reason, "frame_bytes": len(frame.payload)},
        )

    def distance(self, reference: FaceEmbedding, candidate: FaceEmbedding) -> float:
        raise CameraUnavailableError(
            "Üz təsdiqi mühərriki əlçatmazdır",
            context={
                "reason": self._reason,
                "reference_dimension": reference.dimension,
                "candidate_dimension": candidate.dimension,
            },
        )


def camera_available() -> bool:
    """`cv2` idxal oluna bildimi (`composition.py` bunu soruşur)."""
    return _IMPORT_ERROR is None


__all__ = [
    "DEFAULT_FRAME_INTERVAL_SECONDS",
    "DEFAULT_GESTURE_FRAMES",
    "DEFAULT_GESTURE_WINDOW_SECONDS",
    "DEFAULT_WARMUP_FRAMES",
    "CameraUnavailableError",
    "OpenCvCameraCapture",
    "UnavailableFaceEngine",
    "camera_available",
]
