"""Face Control İNFRASTRUKTUR adapterlərinin qapıları — `facecontrol.md` Faza 3.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, NİYƏ `test_face_control.py`-A ƏLAVƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
`test_face_control.py` öz başlığında AÇIQ vəd verir: "BAZA VƏ KİTABXANA LAZIM
DEYİL ... `face_recognition` heç yerdə idxal edilmir". Həmin vəd təsadüfi
deyil — anti-fraud MƏNTİQİ ağır bir kitabxananın quraşdırılmasından asılı
olmamalıdır. Bu faylın testləri isə məhz ADAPTERLƏRİ yoxlayır və kitabxananı
tələb edir; onları oraya qatsaydıq, vəd sükutla pozulardı və bir gün
`face_recognition` qurulmamış maşında BÜTÜN Face Control testləri qırılardı.

──────────────────────────────────────────────────────────────────────────────
REAL KAMERA VƏ REAL ÜZ ŞƏKLİ TƏLƏB EDİLMİR
──────────────────────────────────────────────────────────────────────────────
İki texnika işlədilir:

  * SİNTETİK MASSİV — `numpy` ilə qurulmuş kadrlar. Onlarda üz YOXDUR, ona
    görə `NO_FACE_DETECTED` yolu, kadr formatı və keyfiyyət/hərəkət ölçüləri
    birbaşa yoxlanılır.
  * MODUL SƏVİYYƏSİNDƏ ƏVƏZLƏMƏ — `face_recognition`-un üç funksiyası
    (`face_locations`/`face_landmarks`/`face_encodings`) `monkeypatch` ilə
    əvəz olunur. Bu, adapterin ORKESTRASİYASINI yoxlamağa imkan verir:
    alignment FAKTİKİ olaraq tətbiq olunurmu və vektor DÜZLƏNDİRİLMİŞ kadrdan
    çıxarılırmı (bənd 10). Real üz şəkli ilə bunu yoxlamaq MÜMKÜN DEYİL —
    orada yalnız "nəticə gəldi" görünərdi, hansı kadrdan gəldiyi yox.

Kitabxana qurulmayıbsa testlər `skip` olunur (`requires_qt` naxışı ilə eyni
məntiq): quraşdırılmamış asılılıq REQRESSİYA deyil, mühit xüsusiyyətidir.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Final

import pytest

from src.domain.interfaces.ports import CameraCapture, FaceMatcher
from src.domain.value_objects.face_recognition import (
    FaceEmbedding,
    FaceFrame,
    LivenessGesture,
)

# --------------------------------------------------------------------------- #
# Kitabxana mövcudluğu — `conftest.py::requires_qt` naxışının eynisi
# --------------------------------------------------------------------------- #


def _engine_available() -> bool:
    from src.infrastructure.security.face_matcher import engine_available

    return engine_available()


def _camera_library_available() -> bool:
    from src.infrastructure.kiosk.camera import camera_available

    return camera_available()


requires_face_engine = pytest.mark.skipif(
    not _engine_available(),
    reason="`face_recognition` (Dlib) quraşdırılmayıb — bax requirements.txt",
)
requires_camera_library = pytest.mark.skipif(
    not _camera_library_available(),
    reason="`opencv-python-headless` quraşdırılmayıb — bax requirements.txt",
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


def _numpy() -> Any:
    import numpy as np

    return np


def _frame_from_array(array: Any) -> FaceFrame:
    """Sintetik RGB massivini kadr müqaviləsinə uyğun `FaceFrame`-ə çevirir."""
    return FaceFrame(
        payload=array.tobytes(),
        width=int(array.shape[1]),
        height=int(array.shape[0]),
    )


# --------------------------------------------------------------------------- #
# Port müqaviləsi
# --------------------------------------------------------------------------- #


@requires_face_engine
def test_matcher_satisfies_the_face_matcher_port() -> None:
    """Adapter `FaceMatcher` protokolunu ödəyir (structural typing, miras YOX)."""
    from src.infrastructure.security.face_matcher import DlibFaceMatcher

    assert isinstance(DlibFaceMatcher(), FaceMatcher)


@requires_camera_library
def test_camera_satisfies_the_camera_capture_port() -> None:
    """Adapter `CameraCapture` protokolunu ödəyir — CİHAZ AÇILMADAN.

    Konstruktorun cihaza toxunmaması ayrıca vacibdir: `composition.py` obyekt
    qrafını örtük açılışında qurur və orada bir saniyəlik kamera açılışı bütün
    tətbiqin başlanğıcını gecikdirərdi.
    """
    from src.infrastructure.kiosk.camera import OpenCvCameraCapture

    assert isinstance(OpenCvCameraCapture(), CameraCapture)


def test_unavailable_engine_satisfies_both_ports() -> None:
    """Fail-safe adapter HƏR İKİ portu ödəyir — kitabxana olmadan da."""
    from src.infrastructure.kiosk.camera import UnavailableFaceEngine

    engine = UnavailableFaceEngine(reason="test")
    assert isinstance(engine, CameraCapture)
    assert isinstance(engine, FaceMatcher)


# --------------------------------------------------------------------------- #
# BƏND 5 — kamera nasazlığı SƏSSİZ keçid yaratmır
# --------------------------------------------------------------------------- #


def test_camera_failure_never_becomes_a_silent_pin_only_pass() -> None:
    """Nasaz mühərrik `is_available()`-də `False` deyir, kadr QAYTARMIR.

    BU, BƏND 5-İN MƏRKƏZİ QAPISIDIR. Ən təhlükəli səhv `capture()`-un boş
    siyahı (və ya süni "keçdi" nəticəsi) qaytarmasıdır: boş siyahı use case-də
    `NO_FACE_DETECTED` kimi oxunardı, yəni AVADANLIQ nasazlığı "işıq zəifdir"
    kimi görünər və HEÇ VAXT eskalasiya olunmazdı.
    """
    from src.infrastructure.kiosk.camera import CameraUnavailableError, UnavailableFaceEngine

    engine = UnavailableFaceEngine(reason="face_recognition")

    assert engine.is_available() is False
    with pytest.raises(CameraUnavailableError):
        engine.capture(count=1, gesture=LivenessGesture.BLINK)
    with pytest.raises(CameraUnavailableError):
        engine.extract(FaceFrame(payload=b"xxx", width=1, height=1))
    with pytest.raises(CameraUnavailableError):
        engine.distance(FaceEmbedding(values=(0.0,)), FaceEmbedding(values=(1.0,)))


@requires_camera_library
def test_capture_raises_when_the_device_disappears_mid_stream() -> None:
    """Çəkiliş ortasında itən cihaz İSTİSNA verir, boş siyahı YOX (bənd 5)."""
    from src.infrastructure.kiosk.camera import CameraUnavailableError, OpenCvCameraCapture

    class _DeadDevice:
        """Açılan, lakin oxunmayan cihaz — kabel çıxma ssenarisi."""

        def isOpened(self) -> bool:  # noqa: N802 — OpenCV API adı
            return True

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            return False, None

        def release(self) -> None:
            return None

    camera = OpenCvCameraCapture(warmup_frames=0)
    camera._device = _DeadDevice()

    with pytest.raises(CameraUnavailableError):
        camera.capture(count=1)
    # Tutacaq BURAXILIR ki, növbəti `is_available()` vəziyyəti yenidən
    # yoxlasın — nasazlıq "yapışıb qalmamalıdır".
    assert camera._device is None


@requires_camera_library
def test_gesture_window_failure_also_raises() -> None:
    """Hərəkət pəncərəsində itən cihaz da səssiz keçmir."""
    from src.infrastructure.kiosk.camera import CameraUnavailableError, OpenCvCameraCapture

    class _DeadDevice:
        def isOpened(self) -> bool:  # noqa: N802 — OpenCV API adı
            return True

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            return False, None

        def release(self) -> None:
            return None

    camera = OpenCvCameraCapture(warmup_frames=0, gesture_frames=2, gesture_window_seconds=0.01)
    camera._device = _DeadDevice()

    with pytest.raises(CameraUnavailableError):
        camera.capture(count=1, gesture=LivenessGesture.SMILE)


@requires_camera_library
def test_gesture_window_returns_the_most_changed_frame() -> None:
    """Hərəkət pəncərəsi neytral kadrdan ƏN ÇOX FƏRQLƏNƏNİ seçir.

    Bu, sadə piksel statistikasıdır və birbaşa anti-fraud işi görür:
    kameraya tutulmuş TƏRPƏNMƏYƏN fotoşəkil bütün pəncərədə eyni qalır, yəni
    qaytarılan kadr neytral olur və mühərrikin hərəkət yoxlaması onu rədd edir.
    """
    from src.infrastructure.kiosk.camera import OpenCvCameraCapture

    np = _numpy()
    neutral = np.zeros((4, 4, 3), dtype=np.uint8)
    slight = np.full((4, 4, 3), 10, dtype=np.uint8)
    strong = np.full((4, 4, 3), 200, dtype=np.uint8)

    class _ScriptedDevice:
        def __init__(self) -> None:
            self._frames = [neutral, slight, strong, slight]
            self._index = 0

        def isOpened(self) -> bool:  # noqa: N802 — OpenCV API adı
            return True

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            frame = self._frames[min(self._index, len(self._frames) - 1)]
            self._index += 1
            return True, frame

        def release(self) -> None:
            return None

    camera = OpenCvCameraCapture(warmup_frames=0, gesture_frames=4, gesture_window_seconds=0.01)
    camera._device = _ScriptedDevice()

    frames = camera.capture(count=1, gesture=LivenessGesture.HEAD_TURN)

    assert len(frames) == 1
    # BGR → RGB çevrilməsindən sonra da bərabər kanallı kadr eyni qalır, ona
    # görə dəyər birbaşa müqayisə edilə bilər.
    assert frames[0].payload == strong[:, :, ::-1].tobytes()


@requires_camera_library
def test_camera_converts_bgr_to_rgb_in_the_frame_contract() -> None:
    """OpenCV BGR verir, kadr müqaviləsi RGB888 tələb edir.

    Çevirmə unudulsaydı sistem yenə "işləyərdi": üz tapılar, vektor
    hesablanar, sadəcə məsafələr sistematik olaraq pozulardı — yəni qüsur
    "dəqiqlik nədənsə aşağıdır" formasında illərlə gizlənə bilərdi.
    """
    from src.infrastructure.kiosk.camera import OpenCvCameraCapture

    np = _numpy()
    # Tək piksel: BGR (mavi=1, yaşıl=2, qırmızı=3) → RGB (3, 2, 1).
    bgr = np.array([[[1, 2, 3]]], dtype=np.uint8)

    class _SingleFrameDevice:
        def isOpened(self) -> bool:  # noqa: N802 — OpenCV API adı
            return True

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            return True, bgr

        def release(self) -> None:
            return None

    camera = OpenCvCameraCapture(warmup_frames=0)
    camera._device = _SingleFrameDevice()

    frame = camera.capture(count=1)[0]

    assert frame.payload == bytes([3, 2, 1])
    assert (frame.width, frame.height) == (1, 1)


@requires_camera_library
def test_enrollment_capture_returns_the_requested_frame_count() -> None:
    """Qeydiyyat `count` sayda kadr alır — bənd 11-in ortalaması üçün."""
    from src.infrastructure.kiosk.camera import OpenCvCameraCapture

    np = _numpy()

    class _CountingDevice:
        def __init__(self) -> None:
            self.reads = 0

        def isOpened(self) -> bool:  # noqa: N802 — OpenCV API adı
            return True

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            self.reads += 1
            return True, np.full((2, 2, 3), self.reads, dtype=np.uint8)

        def release(self) -> None:
            return None

    camera = OpenCvCameraCapture(warmup_frames=0, frame_interval_seconds=0.0)
    camera._device = _CountingDevice()

    frames = camera.capture(count=5)

    assert len(frames) == 5
    # KADRLAR FƏRQLİDİR: eyni olsaydılar, "beş kadrın ortası" adı daşıyan,
    # faktiki olaraq tək kadrlıq qeydiyyat alınardı.
    assert len({frame.payload for frame in frames}) == 5


# --------------------------------------------------------------------------- #
# Kadr müqaviləsi
# --------------------------------------------------------------------------- #


@requires_face_engine
def test_malformed_frame_is_rejected_loudly() -> None:
    """Bayt uzunluğu ilə ölçü uyğunsuzluğu SÜKUTLA «üz yoxdur» olmur.

    Udulsaydı, nasaz kamera adapteri aylarla NO_FACE_DETECTED statistikası
    yaradar və heç kim səbəbi axtarmazdı.
    """
    from src.infrastructure.security.face_matcher import DlibFaceMatcher, FaceFrameFormatError

    matcher = DlibFaceMatcher()

    with pytest.raises(FaceFrameFormatError):
        matcher.extract(FaceFrame(payload=b"\x00" * 10, width=640, height=480))


@requires_face_engine
def test_frame_without_a_face_returns_no_face_instead_of_raising() -> None:
    """Üzsüz kadr İSTİSNA ATMIR — bu, gündəlik haldır (bənd 3).

    İstisna atsaydıq, adi işıq problemi kioskda xəta ekranı kimi görünərdi.
    """
    from src.infrastructure.security.face_matcher import DlibFaceMatcher

    np = _numpy()
    sample = DlibFaceMatcher().extract(_frame_from_array(np.zeros((64, 64, 3), dtype=np.uint8)))

    assert sample.has_face is False
    assert sample.embedding is None
    # Üz yoxdursa canlılıq da TƏSDİQLƏNMİR — fail-closed istiqamət.
    assert sample.liveness_confirmed is False


@requires_face_engine
def test_distance_rejects_vectors_of_different_dimensions() -> None:
    """Fərqli ölçülü vektorlar müqayisə edilmir (model faylı dəyişibsə)."""
    from src.domain.value_objects.face_recognition import FaceControlError
    from src.infrastructure.security.face_matcher import DlibFaceMatcher

    with pytest.raises(FaceControlError):
        DlibFaceMatcher().distance(
            FaceEmbedding(values=(0.1, 0.2)), FaceEmbedding(values=(0.1, 0.2, 0.3))
        )


@requires_face_engine
def test_distance_uses_the_library_unit_not_a_percentage() -> None:
    """Məsafə KİTABXANANIN vahidindədir (kiçik = daha oxşar), faiz DEYİL.

    Faizə çevirmə YALNIZ təqdimat qatındadır (`FaceToleranceBand.confidence_
    percent`). Burada faiz qaytarsaydıq, Root-un gördüyü hədd ilə faktiki
    müqayisə arasında gizli bir çevirmə sabiti oturardı.
    """
    from src.infrastructure.security.face_matcher import DlibFaceMatcher

    matcher = DlibFaceMatcher()
    identical = matcher.distance(FaceEmbedding(values=(0.5, 0.5)), FaceEmbedding(values=(0.5, 0.5)))
    apart = matcher.distance(FaceEmbedding(values=(0.0, 0.0)), FaceEmbedding(values=(0.3, 0.4)))

    assert identical == pytest.approx(0.0)
    assert apart == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# BƏND 10 — ALIGNMENT
# --------------------------------------------------------------------------- #


@requires_face_engine
def test_rotation_sign_levels_the_eye_line() -> None:
    """`_roll_degrees` + `Image.rotate` cütü göz xəttini SIFIRA endirir.

    İŞARƏ SƏHVİ SÜKUTLA KEÇƏRDİ: əks işarə bucağı iki dəfə artırar, sistem
    isə yenə "işləyən" görünərdi — nəticə yalnız uzun müddətli dəqiqlik
    itkisi kimi hiss olunardı. Ona görə işarə sintetik iki nöqtə ilə ölçülür,
    real üz şəkli olmadan.
    """
    from PIL import Image

    from src.infrastructure.security.face_matcher import _roll_degrees

    np = _numpy()
    canvas = np.zeros((200, 200, 3), dtype=np.uint8)
    left_eye = (60.0, 90.0)
    right_eye = (140.0, 110.0)
    canvas[88:93, 58:63] = 255
    canvas[108:113, 138:143] = 255

    angle = _roll_degrees(left_eye, right_eye)
    assert angle > 0  # sağ göz aşağıdadır

    center = ((left_eye[0] + right_eye[0]) / 2.0, (left_eye[1] + right_eye[1]) / 2.0)
    rotated = np.array(
        Image.fromarray(canvas).rotate(angle, resample=Image.Resampling.BILINEAR, center=center)
    )

    ys, xs = np.where(rotated[:, :, 0] > 128)
    mid = xs.mean()
    left_dot = (xs[xs < mid].mean(), ys[xs < mid].mean())
    right_dot = (xs[xs >= mid].mean(), ys[xs >= mid].mean())
    residual = math.degrees(
        math.atan2(right_dot[1] - left_dot[1], right_dot[0] - left_dot[0]),
    )

    assert abs(residual) < 0.5


@requires_face_engine
@pytest.mark.parametrize("gesture", [None, LivenessGesture.BLINK])
def test_alignment_runs_on_both_enrollment_and_verification(
    monkeypatch: pytest.MonkeyPatch, gesture: LivenessGesture | None
) -> None:
    """Vektor HƏMİŞƏ DÜZLƏNDİRİLMİŞ kadrdan çıxarılır (bənd 10).

    `gesture is None` QEYDİYYAT yoludur (`_evaluate_frames` onu belə çağırır),
    `gesture` verilmiş hal isə DOĞRULAMA yoludur. Bənd 10 alignment-i HƏR
    İKİSİ üçün məcburi edir və bu test məhz həmin "hər ikisi"ni bağlayır.

    ÖLÇÜ: `face_encodings`-ə ötürülən massiv GİRİŞ kadrından FƏRQLİ olmalıdır.
    Yalnız "alignment funksiyası çağırıldı" yoxlaması kifayət etməzdi —
    funksiya çağırılıb, nəticəsi isə atıla bilərdi.
    """
    from src.infrastructure.security import face_matcher as module

    np = _numpy()
    # Üzün yerində sıfır olmayan, təkrarsız naxış: döndərmədən sonra massiv
    # mütləq dəyişməlidir (bircins kadr döndərməni gizlədərdi).
    canvas = np.arange(120 * 120 * 3, dtype=np.uint8).reshape(120, 120, 3)
    # Göz mərkəzləri arasında 20 piksel şaquli fərq → ~14° əyrilik.
    marks = {
        "left_eye": [(40, 50)],
        "right_eye": [(80, 70)],
        "chin": [(30, 100), (90, 100)],
        "nose_tip": [(60, 75)],
        "top_lip": [(50, 85), (70, 85)],
        "bottom_lip": [(50, 90), (70, 90)],
    }
    encoded_arrays: list[Any] = []

    def _locations(img: Any, model: str = "hog") -> list[tuple[int, int, int, int]]:
        return [(20, 100, 100, 20)]

    def _landmarks(img: Any, face_locations: Any = None) -> list[Any]:
        return [marks]

    monkeypatch.setattr(module.face_recognition, "face_locations", _locations)
    monkeypatch.setattr(module.face_recognition, "face_landmarks", _landmarks)

    def _fake_encodings(
        img: Any, known_face_locations: Any = None, num_jitters: int = 1
    ) -> list[Any]:
        encoded_arrays.append(img)
        return [np.zeros(module.EXPECTED_DIMENSION, dtype=np.float64)]

    monkeypatch.setattr(module.face_recognition, "face_encodings", _fake_encodings)

    sample = module.DlibFaceMatcher().extract(_frame_from_array(canvas), gesture=gesture)

    assert sample.has_face
    assert len(encoded_arrays) == 1
    assert not np.array_equal(encoded_arrays[0], canvas), (
        "Vektor XAM kadrdan hesablanıb — bənd 10-un alignment tələbi pozulub"
    )


@requires_face_engine
def test_alignment_failure_does_not_fall_back_to_the_raw_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Düzləndirilmiş kadrda üz itərsə XAM vektora QAYITMIRIQ.

    Qayıtsaydıq, istinad vektorları düzləndirilmiş, yoxlama vektorlarının bir
    hissəsi isə xam olardı — məsafələr müqayisə edilə bilməyən iki fəzadan
    gələr və Root-un tənzimlədiyi hədd mənasını itirərdi.
    """
    from src.infrastructure.security import face_matcher as module

    np = _numpy()
    canvas = np.arange(120 * 120 * 3, dtype=np.uint8).reshape(120, 120, 3)
    marks = {"left_eye": [(40, 50)], "right_eye": [(80, 70)]}
    calls = {"count": 0}

    def _locations(img: Any, model: str = "hog") -> list[tuple[int, int, int, int]]:
        calls["count"] += 1
        # Birinci çağırış (xam kadr) üzü tapır, ikinci (düzləndirilmiş) yox.
        return [(20, 100, 100, 20)] if calls["count"] == 1 else []

    def _landmarks(img: Any, face_locations: Any = None) -> list[Any]:
        return [marks]

    def _forbidden_encodings(*args: Any, **kwargs: Any) -> list[Any]:
        pytest.fail("Xam kadrdan vektor hesablanmamalıdır")

    monkeypatch.setattr(module.face_recognition, "face_locations", _locations)
    monkeypatch.setattr(module.face_recognition, "face_landmarks", _landmarks)
    monkeypatch.setattr(module.face_recognition, "face_encodings", _forbidden_encodings)

    sample = module.DlibFaceMatcher().extract(_frame_from_array(canvas))

    assert sample.has_face is False


@requires_face_engine
def test_tiny_roll_angles_skip_the_rotation() -> None:
    """Yarım dərəcədən kiçik əyrilik üçün kadr DÖNDƏRİLMİR.

    Hər döndərmə interpolyasiya deməkdir və interpolyasiya kəskinliyi —
    yəni keyfiyyət balının birinci amilini — azaldır. Ölçmə səs-küyünü
    "düzəltmək" kadrı yalnız yumşaldardı.
    """
    from src.infrastructure.security.face_matcher import _align_by_eyes

    np = _numpy()
    canvas = np.arange(60 * 60 * 3, dtype=np.uint8).reshape(60, 60, 3)
    level = {"left_eye": [(20, 30)], "right_eye": [(40, 30)]}

    assert _align_by_eyes(canvas, level) is canvas


# --------------------------------------------------------------------------- #
# Keyfiyyət ölçüsü (bənd 1)
# --------------------------------------------------------------------------- #


@requires_face_engine
def test_quality_score_collapses_on_a_black_frame() -> None:
    """Tam qaranlıq kəsik sıfıra yaxın bal alır — HƏNDƏSİ ORTANIN mənası budur.

    Arifmetik orta olsaydı, "kəskin" görünən (lakin tamamilə qara) kadr üç
    yaxşı amilin sayəsində keçə bilərdi.
    """
    from src.infrastructure.security.face_matcher import _quality_score

    np = _numpy()
    black = np.zeros((40, 40, 3), dtype=np.uint8)

    assert _quality_score(black, (0, 40, 40, 0)) == pytest.approx(0.0)


@requires_face_engine
def test_quality_score_prefers_a_sharp_frame_over_a_blurred_one() -> None:
    """Bulanıq kadrın balı kəskin kadrın balından AŞAĞI olmalıdır.

    Ölçünün İSTİQAMƏTİ yoxlanılır, konkret ədəd yox: ədədlərin özü pilot
    mağazada tənzimlənəcək İLKİN dəyərlərdir (bax modul başlığı).
    """
    from PIL import Image

    from src.infrastructure.security.face_matcher import _quality_score

    np = _numpy()
    rng = np.random.default_rng(11)
    # Orta-boz ətrafında səs-küy: parlaqlıq/kəsilmə amilləri hər iki kadrda
    # təxminən eynidir, fərq YALNIZ kəskinlikdədir.
    sharp = np.clip(rng.normal(128, 40, (60, 60, 3)), 0, 255).astype(np.uint8)
    blurred = np.array(
        Image.fromarray(sharp).resize((6, 6)).resize((60, 60), Image.Resampling.BILINEAR)
    )

    box = (0, 60, 60, 0)
    assert _quality_score(blurred, box) < _quality_score(sharp, box)


@requires_face_engine
def test_quality_score_is_inside_the_unit_interval() -> None:
    """Bal həmişə 0–1 aralığındadır — ROOT həddi ilə müqayisə mənalı olsun."""
    from src.infrastructure.security.face_matcher import _quality_score

    np = _numpy()
    rng = np.random.default_rng(3)
    for mean in (0, 64, 128, 200, 255):
        frame = np.clip(rng.normal(mean, 30, (40, 40, 3)), 0, 255).astype(np.uint8)
        score = _quality_score(frame, (0, 40, 40, 0))
        assert 0.0 <= score <= 1.0


# --------------------------------------------------------------------------- #
# Canlılıq hərəkətləri (bənd 6)
# --------------------------------------------------------------------------- #


@requires_face_engine
def test_open_eyes_do_not_pass_the_blink_check() -> None:
    """Açıq göz «qırpma» sayılmır — əks halda hər şəkil keçərdi."""
    from src.infrastructure.security.face_matcher import _gesture_confirmed

    # Hündürlük/en = 8/20 = 0.40 → açıq göz.
    open_eye = {
        "left_eye": [(20, 30), (40, 30), (30, 26), (30, 34)],
        "right_eye": [(60, 30), (80, 30), (70, 26), (70, 34)],
    }
    assert _gesture_confirmed(LivenessGesture.BLINK, open_eye) is False


@requires_face_engine
def test_closed_eye_passes_the_blink_check() -> None:
    """Bir gözün qapalı olması kifayətdir.

    Hər iki gözü tələb etsəydik, zəif kamerada vicdanlı işçi cəzalanardı
    (bax `face_control.py`-dəki liveness şərhi).
    """
    from src.infrastructure.security.face_matcher import _gesture_confirmed

    # Sol göz: hündürlük/en = 2/20 = 0.10 → qapalı.
    marks = {
        "left_eye": [(20, 30), (40, 30), (30, 29), (30, 31)],
        "right_eye": [(60, 30), (80, 30), (70, 26), (70, 34)],
    }
    assert _gesture_confirmed(LivenessGesture.BLINK, marks) is True


@requires_face_engine
def test_smile_is_measured_relative_to_the_interocular_distance() -> None:
    """Ağız eni GÖZLƏRARASI məsafəyə görə ölçülür, piksellə YOX.

    Piksellə ölçsəydik, kameraya bir addım yaxınlaşmaq «gülümsəmə» kimi
    oxunardı — yəni liveness yoxlaması hərəkəti deyil, məsafəni ölçərdi.
    """
    from src.infrastructure.security.face_matcher import _gesture_confirmed

    neutral = {
        "left_eye": [(40, 30)],
        "right_eye": [(80, 30)],
        "top_lip": [(48, 70), (72, 70)],
        "bottom_lip": [(48, 76), (72, 76)],
    }
    smiling = {
        "left_eye": [(40, 30)],
        "right_eye": [(80, 30)],
        "top_lip": [(28, 70), (92, 70)],
        "bottom_lip": [(28, 76), (92, 76)],
    }
    # Eyni üz, kameraya İKİ DƏFƏ yaxın: bütün piksel ölçüləri ikiqat artır,
    # nisbət isə DƏYİŞMİR — nəticə də dəyişməməlidir.
    neutral_closer = {name: [(x * 2, y * 2) for x, y in points] for name, points in neutral.items()}

    assert _gesture_confirmed(LivenessGesture.SMILE, neutral) is False
    assert _gesture_confirmed(LivenessGesture.SMILE, neutral_closer) is False
    assert _gesture_confirmed(LivenessGesture.SMILE, smiling) is True


@requires_face_engine
def test_head_turn_uses_the_nose_to_jaw_ratio() -> None:
    """Düz baxan üz «çevrilmiş» sayılmır, çevrilmiş üz sayılır."""
    from src.infrastructure.security.face_matcher import _gesture_confirmed

    frontal = {"chin": [(20, 90), (100, 90)], "nose_tip": [(60, 70)]}
    turned = {"chin": [(20, 90), (100, 90)], "nose_tip": [(85, 70)]}

    assert _gesture_confirmed(LivenessGesture.HEAD_TURN, frontal) is False
    assert _gesture_confirmed(LivenessGesture.HEAD_TURN, turned) is True


@requires_face_engine
def test_missing_landmarks_fail_closed_for_every_gesture() -> None:
    """Landmark yoxdursa hərəkət TƏSDİQLƏNMİR — fail-closed.

    `True` qaytarsaydıq, landmark aşkarlamasını pozan istənilən hücum
    (məsələn qismən örtülmüş üz) liveness qorumasını tamamilə söndürərdi.
    """
    from src.infrastructure.security.face_matcher import _gesture_confirmed

    for gesture in LivenessGesture:
        assert _gesture_confirmed(gesture, {}) is False


# --------------------------------------------------------------------------- #
# Quraşdırma sənədi — üç qeyri-aşkar detal itməməlidir
# --------------------------------------------------------------------------- #


def test_requirements_document_the_three_installation_pitfalls() -> None:
    """`requirements.txt` üç quraşdırma tələsini SƏNƏDLƏŞDİRİR.

    ÜÇÜ DƏ "təmizlik" adı ilə silinməyə namizəddir: `dlib-bin` "yanlış paket
    adı" kimi, `--no-deps` "lazımsız bayraq" kimi, `setuptools<81` isə
    "köhnəlmiş pin" kimi görünür. Silinsə, üz təsdiqi TƏMİZ maşında sükutla
    qurulmaz — ona görə sənədləşmə qapı ilə qorunur.
    """
    text = (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "dlib-bin" in text
    assert "--no-deps" in text
    assert "setuptools>=80.10,<81.0" in text
    assert "opencv-python-headless" in text


def test_pyinstaller_spec_bundles_the_engine_and_its_models() -> None:
    """`.spec` gizli idxalları VƏ model fayllarını daşıyır.

    Model faylları `datas`-a düşməsə, paketlənmiş `.exe` işə DÜŞƏR, üz təsdiqi
    isə həmişə "mühərrik əlçatmazdır" deyər — yəni qüsur qurma maşınında
    deyil, MAĞAZADA üzə çıxardı.
    """
    text = (_REPO_ROOT / "src" / "KompasOS.spec").read_text(encoding="utf-8")

    for module_name in ("dlib", "face_recognition", "face_recognition_models", "pkg_resources"):
        assert f"'{module_name}'" in text, f"`hiddenimports`-da `{module_name}` yoxdur"
    assert "collect_data_files" in text
    assert "models/*.dat" in text


# --------------------------------------------------------------------------- #
# Kompozisiya — üç use case FAKTİKİ olaraq qoşulub
# --------------------------------------------------------------------------- #


def test_lazy_face_engine_defers_the_library_import() -> None:
    """Proxy YARADILARKƏN mühərrik AÇILMIR — yalnız ilk metod çağırışında.

    Bu, ölçülmüş ~1.0 saniyəlik model yükünün tətbiq AÇILIŞINDAN çıxarılması
    deməkdir. Proxy tənbəl olmasaydı, Face Control əhatəsindən kənar mağazalar
    (bənd 15) da həmin yükü hər gün ödəyərdi.
    """
    from src.presentation.composition import _LazyFaceEngine

    calls = {"count": 0}
    sentinel_camera = object()
    sentinel_matcher = object()

    def _resolve() -> tuple[Any, Any]:
        calls["count"] += 1
        return sentinel_camera, sentinel_matcher

    proxy = _LazyFaceEngine(_resolve)
    assert calls["count"] == 0, "Proxy qurularkən mühərrik açılmamalıdır"

    # Portun səthi ödənilir — proxy hər iki müqaviləni daşıyır.
    assert isinstance(proxy, CameraCapture)
    assert isinstance(proxy, FaceMatcher)


def test_lazy_face_engine_forwards_to_the_resolved_adapters() -> None:
    """Proxy kameranı VƏ mühərriki AYRI-AYRI, düzgün obyektə yönləndirir."""
    from src.presentation.composition import _LazyFaceEngine

    class _Camera:
        def is_available(self) -> bool:
            return True

        def capture(self, *, count: int = 1, gesture: Any = None) -> list[Any]:
            return ["kadr"] * count

    class _Matcher:
        def extract(self, frame: Any, *, gesture: Any = None) -> str:
            return "nümunə"

        def distance(self, reference: Any, candidate: Any) -> float:
            return 0.25

    proxy = _LazyFaceEngine(lambda: (_Camera(), _Matcher()))

    assert proxy.is_available() is True
    assert proxy.capture(count=3) == ["kadr", "kadr", "kadr"]
    assert proxy.extract(object()) == "nümunə"
    assert proxy.distance(object(), object()) == pytest.approx(0.25)


def test_composition_wires_all_three_face_use_cases() -> None:
    """`composition.py` üç use case-i FAKTİKİ olaraq qurur (Faza 3-ün işi).

    MƏNBƏ-OXUYAN QAPI, çünki `Session` qurmaq üçün canlı baza lazımdır. Faza 2
    həmin üç sahəni qəsdən boş buraxmışdı (adapterlər yox idi) — bu test
    onların geri qayıtmasının qarşısını alır: sahə silinsə, üz qapısı sükutla
    heç yerdən çağırılmayan bir koda çevrilərdi.
    """
    text = (_REPO_ROOT / "src" / "presentation" / "composition.py").read_text(encoding="utf-8")

    for field in ("face_enrollment", "face_re_enrollment", "face_verification"):
        assert f"{field}=" in text, f"`Session`-da `{field}` bağlanmayıb"
    # Adapterlər EYNİ proxy nüsxəsindən gəlir — cihaz fizikidir.
    assert text.count("camera=face_engine") == 2
    assert text.count("matcher=face_engine") == 2
