"""Üz-tanıma mühərriki — `FaceMatcher` portunun Dlib tətbiqi (`facecontrol.md` Faza 3).

──────────────────────────────────────────────────────────────────────────────
KİTABXANA QƏRARI BURADA MÜZAKİRƏ EDİLMİR
──────────────────────────────────────────────────────────────────────────────
`face_recognition` (Dlib əsaslı) `facecontrol.md`-nin "KİTABXANA QƏRARI"
bölməsində QƏTİ seçilib: Boost lisenziyası kommersiya satışına icazə verir
(InsightFace ayrıca lisenziya tələb edir), CPU-da işləyir (mağaza PC-lərində
GPU yoxdur) və PyInstaller paketini TensorFlow kimi ağırlaşdırmır. Bu fayl
həmin qərarın TƏTBİQİDİR, təkrar seçim yeri deyil.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İDXAL MODUL SƏVİYYƏSİNDƏDİR, LAKİN NASAZLIQ SÜKUTLA UDULMUR
──────────────────────────────────────────────────────────────────────────────
Bu, İNFRASTRUKTUR qatıdır — burada `face_recognition` idxalı qat qaydasını
pozmur (domen yalnız `FaceMatcher` protokolunu görür). Lakin idxal MODUL
səviyyəsində uğursuz olarsa `import`-un özü çökərdi və `composition.py`
tətbiqi ümumiyyətlə aça bilməzdi. Ona görə idxal `try/except` ilə tutulur və
səbəb SAXLANILIR: `DlibFaceMatcher` qurula bilər, lakin İLK çağırışda aydın
Azərbaycanca xəta ilə dayanır.

BURADA "kitabxana yoxdursa üz təsdiqini keç" YOLU QƏSDƏN YOXDUR — bənd 5-in
mənası budur: nasazlıq PIN-only rejiminə çevrilməməlidir. Mühərrik
qurulmadıqda `composition.py` `UnavailableFaceEngine`-i (bax
`infrastructure/kiosk/camera.py`) qoşur və axın MÖVCUD eskalasiya kanalına
düşür — yəni nəticə "keçir" deyil, "insan təsdiqi tələb olunur"dur.

──────────────────────────────────────────────────────────────────────────────
KADR MÜQAVİLƏSİ — RGB888, SIXILMAMIŞ
──────────────────────────────────────────────────────────────────────────────
`FaceFrame.payload` SIXILMAMIŞ, sətir-ardıcıl RGB888 baytlarıdır
(`len(payload) == width * height * 3`). JPEG/PNG variantı RƏDD EDİLDİ: kodlaşma
hər kadrda əlavə sıxma/açma dövrü, artefakt və — ən əsası — DİSKƏ YAZILA
BİLƏN bir fayl formatı yaradardı. `migrations/047`-nin birinci qaydası kadrın
yalnız yaddaşda yaşamasını tələb edir; xam bayt massivi bu qaydanı struktur
olaraq dəstəkləyir, çünki onu "sadəcə saxlamaq" mənasız bir fayl verir.

Müqavilənin İKİ tərəfi var: `infrastructure/kiosk/camera.py` onu YAZIR, bu
modul OXUYUR. Uyğunsuzluq SÜKUTLA keçmir — `FaceFrameFormatError` atılır,
çünki yanlış formatlanmış bayt yığını təsadüfən "üz tapılmadı" nəticəsi verər
və qüsur aylarla NO_FACE_DETECTED statistikasının içində gizlənərdi.

──────────────────────────────────────────────────────────────────────────────
BƏND 10 — ALIGNMENT MƏCBURİDİR VƏ YAN KEÇİLƏ BİLMİR
──────────────────────────────────────────────────────────────────────────────
Vektor HEÇ VAXT xam kadrdan hesablanmır: əvvəlcə `face_landmarks()` ilə göz
mərkəzləri tapılır, kadr göz xəttini üfüqi edəcək bucaqla döndərilir, sonra
`face_encodings()` DÖNDƏRİLMİŞ kadrda çağırılır. Bu, `extract()`-in İÇİNDƏDİR
(ayrıca metod deyil) — bax `ports.py::FaceMatcher` şərhi: ayrıca metod olsaydı,
onu çağırmağı unudan axın sükutla daha aşağı dəqiqliklə işləyərdi.

DÖNDƏRİLMİŞ KADRDA ÜZ TAPILMASA XAM VEKTORA QAYIDILMIR. Cazibədar görünürdü
("heç olmasa nəsə qaytaraq"), lakin nəticə ən pis formada olardı: istinad
vektorları düzləndirilmiş, yoxlama vektorlarının bir hissəsi isə xam olardı —
yəni məsafələr müqayisə edilə bilməyən iki fəzadan gələrdi və Root-un
tənzimlədiyi hədd mənasını itirərdi. Belə halda `NO_FACE_DETECTED` qaytarılır
(təhlükəsiz istiqamət: yenidən cəhd, sayğacsız).

──────────────────────────────────────────────────────────────────────────────
İLKİN DƏYƏRLƏR — PİLOTDA TƏNZİMLƏNMƏLİDİR
──────────────────────────────────────────────────────────────────────────────
Bu fayldakı ədədi sabitlərin HAMISI İLKİN dəyərdir və pilot mağazada real
işıq/kamera şəraitində ölçülüb dəqiqləşdirilməlidir. Onlar `system_limits`-ə
QOYULMAYIB və səbəbi aşağıda hər blokun yanında ayrıca yazılıb — qısası:
onlar ÖLÇÜNÜN TƏRİFİDİR, QƏBUL HƏDDİ deyil. Qəbul həddi
(`FACE_ENROLLMENT_MIN_QUALITY`, `FACE_MATCH_TOLERANCE`,
`FACE_LOW_CONFIDENCE_TOLERANCE`) Root-dadır.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.face_recognition import (
    FaceControlError,
    FaceEmbedding,
    FaceSample,
    LivenessGesture,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.domain.value_objects.face_recognition import FaceFrame

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

# --------------------------------------------------------------------------- #
# Kitabxana idxalı
#
# `numpy`/`PIL` MƏCBURİ deyil, `face_recognition` ilə BİRLİKDƏ gəlir: birincisi
# onun öz asılılığıdır, ikincisi (Pillow) isə layihədə onsuz da var (sübut
# şəkillərinin sıxılması). Ona görə üçü BİR blokda tutulur — biri olmadan bu
# modulun heç bir hissəsi işləyə bilməz və "yarım işləyən" mühərrik ən pis
# vəziyyətdir.
#
# `type: ignore[import-untyped]` NİYƏ: `face_recognition` və `dlib` üçün tip
# stub-ı YOXDUR (typeshed-də də yoxdur). `pyproject.toml`-a `ignore_missing_
# imports` yazmaq variantı RƏDD EDİLDİ — o, açarı BÜTÜN modullar üçün açardı
# və gələcəkdə stub-sız gələn hər hansı paket sükutla `Any` sızdırardı.
# Susdurma burada, TƏK sətirdədir; sızma isə `_encode`/`_locate` örtükləri ilə
# dayandırılır: modulun ictimai səthində `Any` YOXDUR.
# --------------------------------------------------------------------------- #
try:
    import face_recognition  # type: ignore[import-untyped]
    import numpy as np
    from PIL import Image

    _IMPORT_ERROR: BaseException | None = None
except (ImportError, SystemExit) as exc:  # pragma: no cover — quraşdırılmış mühitdə işə düşmür
    # `SystemExit` NİYƏ TUTULUR — BU, TƏSADÜFİ GENİŞLƏNDİRMƏ DEYİL
    # ─────────────────────────────────────────────────────────────────────────
    # `face_recognition/api.py` model paketini tapa bilmədikdə `ImportError`
    # ATMIR — ekrana mesaj yazıb `quit()` ÇAĞIRIR, yəni `SystemExit` qaldırır
    # (`BaseException`, `Exception` DEYİL). Yalnız `ImportError` tutsaydıq,
    # model paketi olmayan bir quraşdırmada tətbiq İDXAL ANINDA, heç bir
    # jurnal sətri olmadan, "proqram açılmır" formasında ölərdi — halbuki üz
    # təsdiqi sistemin YALNIZ BİR qatıdır və bənd 5 belə halda eskalasiya
    # tələb edir, dayanma yox.
    #
    # Bu vəziyyət real ssenaridir: `setuptools<81` pini (bax requirements.txt)
    # məhz həmin `quit()` yolunu bağlamaq üçündür və pinin bir gün "təmizlik"
    # adı ilə silinməsi mümkündür.
    _IMPORT_ERROR = exc


class FaceEngineUnavailableError(KompasOSError):
    """Üz-tanıma kitabxanası yüklənə bilmədi.

    İSTİSNA ATILIR, `False`/`None` QAYTARILMIR: sükutla "üz təsdiqi yoxdur"
    demək bənd 5-in qadağan etdiyi məhz həmin keçiddir. Çağıran tərəf
    (`composition.py`) bu vəziyyəti `UnavailableFaceEngine` ilə MÖVCUD
    eskalasiya kanalına çevirir.
    """

    user_message = (
        "Üz tanıma mühərriki yüklənə bilmədi. Təsdiq HR_Admin və ya CEO "
        "tərəfindən manual verilməlidir."
    )


class FaceFrameFormatError(FaceControlError):
    """Kadrın bayt uzunluğu elan edilmiş ölçü ilə uyğun gəlmir.

    PROQRAMLAŞDIRMA XƏTASIDIR, gündəlik hal deyil: kamera adapteri ilə bu modul
    arasındakı müqavilə pozulub. Ona görə `NO_FACE_DETECTED` kimi udulmur —
    udulsaydı, nasaz adapter aylarla "üz görünmür" statistikası yaradardı.
    """

    user_message = "Kameradan gələn kadr oxuna bilmədi. Kamera sürücüsünü yoxlayın."


#: RGB888 — piksel başına üç kanal. `FaceFrame` müqaviləsinin sabiti
#: (`payload` uzunluğu = `width * height * FRAME_CHANNELS`), konfiqurasiya
#: DEYİL: dəyişdirilməsi formatın özünü dəyişər.
FRAME_CHANNELS: Final[int] = 3

#: Dlib-in 128 ölçülü üz vektoru. Burada YOXLAMA üçün saxlanılır, tələb kimi
#: yox: `FaceEmbedding` qəsdən sabit ölçü tələb etmir (bax onun şərhi), lakin
#: gözlənilməz ölçü jurnala yazılır ki, model faylının dəyişməsi görünsün.
EXPECTED_DIMENSION: Final[int] = 128

# --------------------------------------------------------------------------- #
# KEYFİYYƏT ÖLÇÜSÜNÜN TƏRİFİ (bənd 1 — `FACE_ENROLLMENT_MIN_QUALITY`)
#
# Bal DÖRD amilin HƏNDƏSİ ORTASIDIR (0–1). Amillərin hər biri kadrın üz
# SAHƏSİNDƏ (bütün kadrda yox — divar/fon balı süni şəkildə yaxşılaşdırardı)
# ölçülür:
#
#   1. KƏSKİNLİK — Laplas operatorunun dispersiyası. Klassik bulanıqlıq
#      ölçüsüdür (Pech-Pacheco et al., 2000): fokusdan çıxmış və ya hərəkətdən
#      sürüşmüş kadrda yüksək tezliklər itir və dispersiya düşür.
#   2. İŞIQLANDIRMA — orta parlaqlığın orta-boz səviyyədən uzaqlığı. Həm
#      qaranlıq, həm həddən artıq işıqlı kadr eyni dərəcədə cəzalandırılır.
#   3. KƏSİLMƏ — 0/255-ə "yapışmış" piksellərin payı. Kontr-işıqda (pəncərə
#      arxada) üz qaralır, fon isə ağ kəsilir — orta parlaqlıq NORMAL görünə
#      bilər, halbuki üzün detalı tamamilə itib. Bu amil məhz həmin hiyləni
#      tutur.
#   4. KONTRAST — standart kənarlaşma. Dumanlı/tüstülü/aşağı-kontrastlı kadrda
#      landmark-lar sürüşür.
#
# NİYƏ HƏNDƏSİ ORTA, ARİFMETİK YOX: arifmetik ortada üç yaxşı amil bir fəlakətli
# amili gizlədə bilər (tam qaranlıq, lakin "kəskin" kadr 0.75 alardı). Həndəsi
# ortada bir amilin sıfıra yaxınlaşması bütün balı sıfıra çəkir — keyfiyyət
# ölçüsündən gözlənilən davranış məhz budur.
#
# AŞAĞIDAKI ÜÇ SABİT ÖLÇÜNÜN MİQYASIDIR, QƏBUL HƏDDİ DEYİL — ona görə
# `system_limits`-də DEYİL. Onları Root-a versəydik, `FACE_ENROLLMENT_MIN_
# QUALITY = 0.50` sətrinin MƏNASI hər dəyişiklikdə sürüşərdi: Root ekranda
# "0.50" görər, faktiki tələb isə tamam başqa olardı. Qəbul həddi ROOT-dadır,
# ölçünün tərifi isə kodda versiyalanır.
#
# ⚠️ HƏR ÜÇÜ İLKİN DƏYƏRDİR — pilot mağazanın kamerası və işığı ilə ölçülüb
# dəqiqləşdirilməlidir.
# --------------------------------------------------------------------------- #

#: Laplas dispersiyasının "kifayət qədər kəskin" istinadı. 100.0 bulanıqlıq
#: aşkarlamasında geniş istifadə olunan klassik kəsim nöqtəsidir.
QUALITY_SHARPNESS_REFERENCE: Final[float] = 100.0

#: Yaxşı işıqlandırılmış üz kəsiyinin tipik standart kənarlaşması (0–255).
QUALITY_CONTRAST_REFERENCE: Final[float] = 40.0

#: Kəsilmiş piksellərin dözülən payı — bundan yuxarısı balı sıfırlayır.
QUALITY_CLIPPING_TOLERANCE: Final[float] = 0.10

#: "Kəsilmiş" sayılan sərhədlər (8-bitlik kanalda praktiki doyma zonası).
_CLIP_LOW: Final[int] = 2
_CLIP_HIGH: Final[int] = 253

# --------------------------------------------------------------------------- #
# CANLILIQ HƏRƏKƏTLƏRİNİN ÖLÇÜSÜ (bənd 6)
#
# ⚠️ AÇIQ MƏHDUDİYYƏT — GİZLƏDİLMİR
# ───────────────────────────────────────────────────────────────────────────
# `CameraCapture.capture()` müqaviləsi doğrulamada TƏK kadr qaytarır (bax
# `ports.py`), yəni hərəkət BİR kadrdan qiymətləndirilir. Bu, tam anti-spoofing
# DEYİL: hərəkəti "edən" bir fotoşəkil (məsələn gülümsəyən çap) TƏLƏB OLUNAN
# hərəkət təsadüfən ona uyğun gələrsə keçə bilər. Qoruma iki yerdən gəlir:
#   * hərəkət SERVERDƏ, `secrets.choice` ilə seçilir (bax `face_control.py`)
#     — hansı hərəkətin istənəcəyi əvvəlcədən bilinmir;
#   * kamera adapteri hərəkət pəncərəsində ƏN ÇOX DƏYİŞƏN kadrı qaytarır (bax
#     `camera.py`), yəni tərpənməyən şəkil neytral kadr verir və aşağıdakı
#     yoxlamalardan keçmir.
# Bunun növbəti səviyyəsi (zaman seriyası üzrə EAR ardıcıllığı və ya toxuma
# əsaslı PAD modeli) port müqaviləsinin dəyişməsini tələb edir və QƏSDƏN bu
# fazadan kənarda saxlanılıb — sənədləşdirilmiş boşluqdur, sükutla buraxılmış
# deyil.
#
# NİYƏ NİSBƏTLƏR, MÜTLƏQ PİKSEL DEYİL: bütün ölçülər ya öz sərhəd
# qutusuna, ya da gözlərarası məsafəyə bölünür — əks halda kameraya
# yaxınlaşmaq/uzaqlaşmaq hərəkəti "aşkarlayardı".
#
# ⚠️ ÜÇ HƏDD DƏ İLKİN DƏYƏRDİR, pilotda tənzimlənməlidir.
# --------------------------------------------------------------------------- #

#: Gözün hündürlük/en nisbəti — bundan aşağısı "göz qapalı" sayılır.
#: Ədəbiyyatdakı "eye aspect ratio" kəsimi (~0.20) ilə eyni səviyyədədir.
BLINK_ASPECT_THRESHOLD: Final[float] = 0.20

#: Ağız eninin gözlərarası məsafəyə nisbəti — neytral üzdə ~1.0–1.2.
SMILE_WIDTH_RATIO_THRESHOLD: Final[float] = 1.40

#: Burun ucunun çənə konturunun sol/sağ kənarlarına olan məsafələrinin
#: nisbəti. Üz kameraya düz baxanda ~1.0; baş çevriləndə kəskin artır.
HEAD_TURN_RATIO_THRESHOLD: Final[float] = 1.60

#: Bu bucaqdan (dərəcə) kiçik əyrilik üçün kadr DÖNDƏRİLMİR. Səbəb keyfiyyət
#: qorumasıdır: hər döndərmə interpolyasiya deməkdir və interpolyasiya
#: kəskinliyi (yuxarıdakı 1-ci amil) azaldır. Yarım dərəcədən kiçik əyrilik
#: landmark ölçmə səs-küyü səviyyəsindədir — onu "düzəltmək" ölçünü
#: yaxşılaşdırmır, yalnız kadrı yumşaldardı.
MIN_ALIGNMENT_DEGREES: Final[float] = 0.5


def engine_available() -> bool:
    """Kitabxana idxal oluna bildimi (`composition.py` bunu soruşur)."""
    return _IMPORT_ERROR is None


def _require_engine() -> None:
    """İdxal uğursuz olubsa AYDIN Azərbaycanca xəta ilə dayanır."""
    if _IMPORT_ERROR is not None:
        raise FaceEngineUnavailableError(
            "`face_recognition` (Dlib) kitabxanası yüklənə bilmədi",
            context={"error": str(_IMPORT_ERROR)},
        )


class DlibFaceMatcher:
    """`FaceMatcher` portunun Dlib tətbiqi — ON-DEVICE, şəbəkəsiz.

    ──────────────────────────────────────────────────────────────────────────
    HEÇ BİR KADR/VEKTOR ŞƏBƏKƏYƏ ÇIXMIR
    ──────────────────────────────────────────────────────────────────────────
    Bu sinifdə nə HTTP klienti, nə fayl yazısı var — emal tamamilə prosesin
    yaddaşındadır (`migrations/047`-nin üçüncü qaydası). Jurnala yalnız
    NƏTİCƏ və BAL düşür; kadr və vektor `__repr__`-ləri onsuz da maskalanıb
    (bax `value_objects/face_recognition.py`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `hog`, `cnn` YOX
    ──────────────────────────────────────────────────────────────────────────
    Dlib-in CNN detektoru daha dəqiqdir, lakin CPU-da bir kadr üçün saniyələr
    tələb edir. Kiosk PC-lərində GPU YOXDUR (kitabxana qərarının 2-ci səbəbi)
    və bənd 18 doğrulama vaxtını izləyir — CNN ilə hər doğrulama xəbərdarlıq
    hədddini keçərdi. `hog` detektoru düz baxan, işıqlandırılmış üz üçün (kiosk
    ssenarisi məhz budur) kifayətdir. Seçim konstruktorda AÇIQ saxlanılır ki,
    güclü avadanlığı olan quraşdırma onu dəyişə bilsin.
    """

    def __init__(self, *, detector_model: str = "hog", jitters: int = 1) -> None:
        """Mühərriki qurur — MODEL YÜKÜ ARTIQ ÖDƏNİLİB (bax aşağı).

        DİQQƏT, ASAN YANILAN NÖQTƏ: `face_recognition/api.py` model fayllarını
        MODUL SƏVİYYƏSİNDƏ yükləyir (`dlib.shape_predictor(...)` və
        `dlib.face_recognition_model_v1(...)` idxal anında çağırılır). Yəni
        qiymət (bu maşında ölçülmüş ~1.0 saniyə + ~150 MB) BU FAYLIN idxalında
        ödənilir, konstruktorda yox — konstruktoru "tənbəl" etməyin heç bir
        faydası olmazdı.

        Ona görə TƏNBƏLLİK BİR PİLLƏ YUXARIDADIR: `composition.py` modulu
        funksiya daxilində idxal edir və `_LazyFaceEngine` proxy-si onu yalnız
        FAKTİKİ üz əməliyyatında çağırır. Face Control əhatəsindən kənar
        mağazalar (bənd 15) beləliklə heç nə ödəmir.

        İdxal uğursuzluğu isə DƏRHAL yoxlanılır — o, gecikdirilə bilməz:
        `composition.py` mühərrikin qurula bilib-bilmədiyini bilməlidir ki,
        eskalasiya yolunu (bənd 5) seçsin.
        """
        _require_engine()
        self._detector_model = detector_model
        self._jitters = jitters

    # ------------------------------- port səthi ------------------------------ #

    def extract(self, frame: FaceFrame, *, gesture: LivenessGesture | None = None) -> FaceSample:
        """Kadr → (alignment) → vektor + keyfiyyət balı + canlılıq nəticəsi.

        SIRA TƏHLÜKƏSİZLİK QƏRARIDIR və yuxarıdan aşağı oxunur:
        aşkarla → landmark → DÜZLƏNDİR → yenidən aşkarla → vektor →
        keyfiyyət → canlılıq. Vektor DÜZLƏNDİRİLMİŞ kadrdan çıxarılır (bənd 10),
        canlılıq isə düzləndirilmiş landmark-lardan ölçülür ki, baş əyriliyi
        "göz qapalı" kimi oxunmasın.
        """
        _require_engine()
        image = _decode_frame(frame)

        found = _largest_face(image, model=self._detector_model)
        if found is None:
            return FaceSample(embedding=None, quality=0.0, liveness_confirmed=False)

        # BƏND 10 — ALIGNMENT. Bu iki sətir yan keçilə bilməz: aşağıdakı
        # `face_encodings` yalnız `aligned` üzərində çağırılır.
        aligned = _align_by_eyes(image, found[1])
        aligned_face = _largest_face(aligned, model=self._detector_model)
        if aligned_face is None:
            # Düzləndirilmiş kadrda üz itdi (çox nadir: kəskin əyrilik + kadr
            # kənarı). Xam vektora QAYITMIRIQ — səbəb modul başlığındadır.
            _log.info("FACE_ALIGNED_FRAME_LOST", extra={"detector": self._detector_model})
            return FaceSample(embedding=None, quality=0.0, liveness_confirmed=False)

        detector_box, aligned_marks = aligned_face
        encodings = face_recognition.face_encodings(
            aligned, known_face_locations=[detector_box], num_jitters=self._jitters
        )
        if not encodings:
            _log.info("FACE_ENCODING_EMPTY", extra={"detector": self._detector_model})
            return FaceSample(embedding=None, quality=0.0, liveness_confirmed=False)

        values = tuple(float(item) for item in encodings[0])
        if len(values) != EXPECTED_DIMENSION:
            # Model faylı dəyişibsə bu, SÜKUTLA keçməməlidir: saxlanılmış
            # istinad vektorları köhnə ölçüdədir və `FaceEmbedding.average`
            # onları qarışdıra bilməz.
            _security_log.warning("FACE_EMBEDDING_DIMENSION", extra={"dimension": len(values)})

        # KEYFİYYƏT DETEKTOR QUTUSUNDA DEYİL, LANDMARK QUTUSUNDA ölçülür:
        # detektorun qutusu saç/fon zolağını da əhatə edir və qaranlıq fon
        # işıqlı üzün balını süni şəkildə aşağı salardı.
        quality = _quality_score(aligned, _bounding_box(aligned_marks))
        liveness = True if gesture is None else _gesture_confirmed(gesture, aligned_marks)
        return FaceSample(
            embedding=FaceEmbedding(values=values),
            quality=quality,
            liveness_confirmed=liveness,
        )

    def distance(self, reference: FaceEmbedding, candidate: FaceEmbedding) -> float:
        """İki vektor arasındakı Evklid məsafəsi — kitabxananın öz vahidi.

        `face_recognition.face_distance` çağırılır, əl ilə `math.dist`
        hesablanmır: kitabxana gələcəkdə metrikanı dəyişsə (məs. normallaşdırma
        əlavə etsə), Root-un tənzimlədiyi hədd ilə faktiki müqayisə arasında
        fərq yaranardı. Vahid bir mənbədən gəlməlidir.
        """
        _require_engine()
        if reference.dimension != candidate.dimension:
            raise FaceControlError(
                "Fərqli ölçülü vektorlar müqayisə edilə bilməz",
                user_message="Üz məlumatı uyğunsuzdur. Yenidən qeydiyyat tələb olunur.",
                context={"reference": reference.dimension, "candidate": candidate.dimension},
            )
        result = face_recognition.face_distance(
            [np.array(reference.values, dtype=np.float64)],
            np.array(candidate.values, dtype=np.float64),
        )
        return float(result[0])


# --------------------------------------------------------------------------- #
# Kadrın oxunması
# --------------------------------------------------------------------------- #


def _decode_frame(frame: FaceFrame) -> Any:
    """`FaceFrame` → `numpy` RGB massivi (H, W, 3), `uint8`.

    Ölçü uyğunsuzluğu istisna ilə bitir (bax `FaceFrameFormatError`): səssiz
    "üz tapılmadı" cavabı nasaz adapteri illərlə gizlədə bilərdi.
    """
    expected = frame.width * frame.height * FRAME_CHANNELS
    if frame.width <= 0 or frame.height <= 0 or len(frame.payload) != expected:
        raise FaceFrameFormatError(
            "Kadrın bayt uzunluğu elan edilmiş ölçüyə uyğun gəlmir",
            context={
                "width": frame.width,
                "height": frame.height,
                "expected_bytes": expected,
                "actual_bytes": len(frame.payload),
            },
        )
    buffer = np.frombuffer(frame.payload, dtype=np.uint8)
    # `reshape` NÜSXƏ ÇIXARMIR, lakin `frombuffer` YALNIZ-OXU massiv verir və
    # Dlib bəzi yollarda yazıla bilən bufer gözləyir; `copy()` bu uyğunsuzluğu
    # bir yerdə bağlayır (alternativ — hər çağırışda `np.array(..., copy=True)`
    # — eyni işi daha gec və daha gizli edərdi).
    return buffer.reshape(frame.height, frame.width, FRAME_CHANNELS).copy()


# --------------------------------------------------------------------------- #
# Landmark + alignment (bənd 10)
# --------------------------------------------------------------------------- #


def _largest_face(
    image: Any, *, model: str
) -> tuple[tuple[int, int, int, int], dict[str, list[tuple[int, int]]]] | None:
    """Kadrdakı ƏN BÖYÜK üzün detektor qutusu + 68-nöqtə landmark-ları.

    Üz (və ya landmark) yoxdursa `None` — istisna ATILMIR, çünki bu, gündəlik
    haldır və `NO_FACE_DETECTED` axınına çevrilir (bənd 3).

    NİYƏ ƏN BÖYÜK: kioskda duran şəxs kameraya ƏN YAXINDIR, arxa fondakı
    keçən adamlar isə kiçik görünür. "Birinci tapılanı götür" variantı
    detektorun daxili sırasından asılı olardı — yəni arxadan keçən bir nəfər
    təsadüfən doğrulamanın SUBYEKTİNƏ çevrilə bilərdi.
    """
    locations = face_recognition.face_locations(image, model=model)
    if not locations:
        return None
    largest = max(locations, key=_box_area)
    box = (int(largest[0]), int(largest[1]), int(largest[2]), int(largest[3]))
    marks = face_recognition.face_landmarks(image, face_locations=[box])
    if not marks:
        return None
    return box, {
        str(name): [(int(x), int(y)) for x, y in points] for name, points in marks[0].items()
    }


def _box_area(box: tuple[int, int, int, int]) -> int:
    """`face_recognition` qutusu `(top, right, bottom, left)` sırasındadır."""
    top, right, bottom, left = box
    return max(0, bottom - top) * max(0, right - left)


def _align_by_eyes(image: Any, marks: dict[str, list[tuple[int, int]]]) -> Any:
    """Göz xəttini üfüqi edən döndərmə — BƏND 10-un tətbiqi.

    Döndərmə MƏRKƏZİ gözlərin orta nöqtəsidir, kadrın mərkəzi deyil: kadrın
    mərkəzi ətrafında döndərmək üzü kadr kənarına sürüşdürər və kənara çıxan
    hissə itərdi.

    `expand=False` QƏSDƏNDİR: kadrın ölçüsü sabit qalır, yəni sonrakı
    `face_locations` çağırışı eyni koordinat sistemində işləyir. Genişlənmə
    ilə qara haşiyə yaranar və o haşiyə keyfiyyət ölçüsünün "kəsilmə" amilini
    süni şəkildə pisləşdirərdi.
    """
    left_eye = _centroid(marks.get("left_eye", ()))
    right_eye = _centroid(marks.get("right_eye", ()))
    if left_eye is None or right_eye is None:
        # 68-nöqtə modeli həmişə hər iki gözü verir; bura yalnız kitabxananın
        # "small" modelinə keçiddə düşə bilər. Döndərmədən keçirik — bu, xəta
        # deyil, lakin jurnalda görünməlidir.
        _log.info("FACE_ALIGNMENT_SKIPPED_NO_EYES")
        return image
    angle = _roll_degrees(left_eye, right_eye)
    if abs(angle) < MIN_ALIGNMENT_DEGREES:
        return image
    center = ((left_eye[0] + right_eye[0]) / 2.0, (left_eye[1] + right_eye[1]) / 2.0)
    rotated = Image.fromarray(image).rotate(angle, resample=Image.Resampling.BICUBIC, center=center)
    # `np.asarray` YOX, `np.array`: birincisi Pillow buferinə YALNIZ-OXU
    # baxış qaytarır və Dlib bəzi yollarda yazıla bilən massiv gözləyir.
    return np.array(rotated, dtype=np.uint8)


def _roll_degrees(left_eye: tuple[float, float], right_eye: tuple[float, float]) -> float:
    """Göz xəttinin üfüqdən sapması (dərəcə).

    İŞARƏ SINAQDAN KEÇİB: `Image.rotate(+angle, center=...)` məhz bu bucağı
    SIFIRA endirir (bax `tests/unit/test_face_infrastructure.py` — sintetik iki
    nöqtə ilə ölçülür). Əks işarə bucağı İKİQAT artırardı və alignment
    dəqiqliyi ARTIRMAQ əvəzinə azaldardı — üstəlik nəticə yenə "işləyən" bir
    sistem olardı, yəni qüsur yalnız uzun müddətli dəqiqlik itkisi kimi
    görünərdi. Ona görə işarə testlə bağlanıb.
    """
    return math.degrees(
        math.atan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]),
    )


def _centroid(points: Sequence[tuple[int, int]]) -> tuple[float, float] | None:
    if not points:
        return None
    return (
        sum(float(x) for x, _ in points) / len(points),
        sum(float(y) for _, y in points) / len(points),
    )


def _bounding_box(marks: dict[str, list[tuple[int, int]]]) -> tuple[int, int, int, int]:
    """Landmark-lardan `(top, right, bottom, left)` qutusu.

    Detektorun qaytardığı qutu YENİDƏN İSTİFADƏ EDİLMİR, çünki landmark
    dəsti üzün FAKTİKİ sərhədini daha dar verir — keyfiyyət ölçüsü (aşağıda)
    fon piksellərindən nə qədər az təsirlənsə, bir o qədər dürüstdür.
    """
    xs = [x for points in marks.values() for x, _ in points]
    ys = [y for points in marks.values() for _, y in points]
    return (min(ys), max(xs), max(ys), min(xs))


# --------------------------------------------------------------------------- #
# Keyfiyyət ölçüsü
# --------------------------------------------------------------------------- #


def _quality_score(image: Any, box: tuple[int, int, int, int]) -> float:
    """Üz kəsiyinin 0–1 keyfiyyət balı (tərif modul başlığındadır)."""
    top, right, bottom, left = box
    height, width = image.shape[0], image.shape[1]
    crop = image[max(0, top) : min(height, bottom), max(0, left) : min(width, right)]
    if crop.size == 0:
        return 0.0
    # BT.601 çəkiləri ilə boz səviyyə: sadə orta (R+G+B)/3 insan gözünün
    # yaşıla həssaslığını nəzərə almır və eyni işıqda fərqli dəri tonlarını
    # fərqli "parlaq" göstərərdi.
    gray = (
        0.299 * crop[:, :, 0].astype(np.float64)
        + 0.587 * crop[:, :, 1].astype(np.float64)
        + 0.114 * crop[:, :, 2].astype(np.float64)
    )
    factors = (
        _sharpness_factor(gray),
        _brightness_factor(gray),
        _clipping_factor(gray),
        _contrast_factor(gray),
    )
    # Həndəsi orta — bir amilin sıfıra yaxınlaşması balı sıfıra çəkir.
    product = 1.0
    for factor in factors:
        product *= max(0.0, min(1.0, factor))
    return round(float(product ** (1.0 / len(factors))), 4)


def _sharpness_factor(gray: Any) -> float:
    """Laplas dispersiyasının istinada nisbəti (1.0-da doyur)."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:  # noqa: PLR2004 — 3x3 nüvənin ölçüsü
        return 0.0
    # 3x3 Laplas nüvəsi ƏL İLƏ tətbiq olunur: `scipy`/`cv2` asılılığı yalnız
    # bir konvolyusiya üçün əlavə edilməzdi (paket ölçüsü + PyInstaller yükü),
    # numpy dilimləməsi isə eyni nəticəni bir neçə sətirdə verir.
    centre = gray[1:-1, 1:-1]
    laplacian = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4.0 * centre
    return float(laplacian.var()) / QUALITY_SHARPNESS_REFERENCE


def _brightness_factor(gray: Any) -> float:
    """Orta parlaqlığın orta-boz səviyyəyə yaxınlığı (1.0 = ideal)."""
    mean = float(gray.mean()) / 255.0
    return 1.0 - abs(mean - 0.5) / 0.5


def _clipping_factor(gray: Any) -> float:
    """0/255-ə yapışmış piksellərin payına görə cəza."""
    clipped = float(((gray <= _CLIP_LOW) | (gray >= _CLIP_HIGH)).mean())
    return 1.0 - clipped / QUALITY_CLIPPING_TOLERANCE


def _contrast_factor(gray: Any) -> float:
    """Standart kənarlaşmanın istinada nisbəti (1.0-da doyur)."""
    return float(gray.std()) / QUALITY_CONTRAST_REFERENCE


# --------------------------------------------------------------------------- #
# Canlılıq hərəkətləri (bənd 6)
# --------------------------------------------------------------------------- #


def _gesture_confirmed(gesture: LivenessGesture, marks: dict[str, list[tuple[int, int]]]) -> bool:
    """Tələb olunan hərəkət kadrda görünürmü.

    NAMƏLUM HƏRƏKƏT `False` QAYTARIR (fail-closed): `LivenessGesture`-a yeni
    dəyər əlavə edilib burada ölçüsü yazılmasa, qoruma SÜKUTLA "hər şey
    keçir"ə çevrilməməlidir. `gesture_pool` fəlsəfəsi ilə eynidir — liveness
    qoruması təsadüfən sönə bilməz.

    NİYƏ SÖZLÜK, NİYƏ `if/elif` ZƏNCİRİ: zəncirin sonundakı "naməlum dəyər"
    budağını mypy ƏLÇATMAZ sayır (enum tam əhatə olunub) və `warn_unreachable`
    onu xəta kimi göstərir. Susdurma yazsaydıq, qoruma bir gün HƏQİQƏTƏN
    əlçatmaz olduqda da susqun qalardı. Sözlük axtarışı isə `None` nəticəsini
    normal, yoxlanıla bilən hal edir.
    """
    check = _GESTURE_CHECKS.get(gesture)
    if check is None:
        _security_log.warning("FACE_GESTURE_UNSUPPORTED", extra={"gesture": gesture.value})
        return False
    return check(marks)


def _blink_detected(marks: dict[str, list[tuple[int, int]]]) -> bool:
    """Ən azı bir gözün hündürlük/en nisbəti həddin altındadırmı.

    NİYƏ SƏRHƏD QUTUSU, NİYƏ KLASSİK ALTI-NÖQTƏLİ DÜSTUR: klassik EAR düsturu
    landmark-ların SIRASINDAN asılıdır (p1..p6), sıra isə kitabxananın
    sənədləşdirilməmiş detalıdır — versiya dəyişikliyi düsturu sükutla
    yanlış nöqtələrə tətbiq edərdi və qapalı göz "açıq" oxunardı. Sərhəd
    qutusunun nisbəti eyni fiziki kəmiyyəti (gözün açıqlığı) ölçür, lakin
    sıradan TAM ASILI DEYİL.

    "Ən azı bir göz" — hər iki gözün eyni anda tutulması tələbi zəif kamerada
    vicdanlı işçini cəzalandırardı (bax `face_control.py`-dəki liveness
    şərhi: qoruma öz istifadəçisini cəzalandırmamalıdır).
    """
    for key in ("left_eye", "right_eye"):
        ratio = _aspect_ratio(marks.get(key, ()))
        if ratio is not None and ratio < BLINK_ASPECT_THRESHOLD:
            return True
    return False


def _smile_detected(marks: dict[str, list[tuple[int, int]]]) -> bool:
    """Ağız eni gözlərarası məsafəyə nisbətən genişlənibmi.

    NİYƏ GÖZLƏRARASI MƏSAFƏYƏ BÖLÜNÜR: gözlərarası məsafə üzün ən sabit
    antropometrik ölçüsüdür və mimika ilə dəyişmir — yəni məxrəc sabit,
    surət isə hərəkətdən asılıdır. Piksel ölçüsü ilə müqayisə etsəydik,
    kameraya bir addım yaxınlaşmaq "gülümsəmə" kimi oxunardı.
    """
    lips = [*marks.get("top_lip", ()), *marks.get("bottom_lip", ())]
    left_eye = _centroid(marks.get("left_eye", ()))
    right_eye = _centroid(marks.get("right_eye", ()))
    if not lips or left_eye is None or right_eye is None:
        return False
    interocular = math.dist(left_eye, right_eye)
    if interocular <= 0:
        return False
    mouth_width = float(max(x for x, _ in lips) - min(x for x, _ in lips))
    return bool(mouth_width / interocular >= SMILE_WIDTH_RATIO_THRESHOLD)


def _head_turn_detected(marks: dict[str, list[tuple[int, int]]]) -> bool:
    """Burun ucu çənə konturunun mərkəzindən kifayət qədər sürüşübmü.

    NİYƏ ÇƏNƏ KONTURU: baş çevriləndə burun ucu bir tərəfə yaxınlaşır, digər
    tərəfdən uzaqlaşır — iki məsafənin NİSBƏTİ isə üzün ölçüsündən və kameraya
    məsafədən asılı deyil. Mütləq piksel sürüşməsi ilə ölçsəydik, kameraya
    yaxın duran adam "başını çevirmiş" görünərdi.
    """
    chin = marks.get("chin", ())
    nose = _centroid(marks.get("nose_tip", ()))
    if not chin or nose is None:
        return False
    left_edge = min(float(x) for x, _ in chin)
    right_edge = max(float(x) for x, _ in chin)
    to_left = nose[0] - left_edge
    to_right = right_edge - nose[0]
    if to_left <= 0 or to_right <= 0:
        # Burun konturdan kənardadır — bu, artıq güclü çevrilmədir.
        return True
    ratio = max(to_left / to_right, to_right / to_left)
    return ratio >= HEAD_TURN_RATIO_THRESHOLD


#: Landmark sözlüyünün tipi — üç ölçmə funksiyasının hamısı onu alır.
_Marks = dict[str, list[tuple[int, int]]]

#: Hərəkət → ölçmə funksiyası. `_gesture_confirmed` bunu SÖZLÜK kimi oxuyur
#: ki, "naməlum hərəkət" halı əlçatan və testlənə bilən qalsın (bax orada).
_GESTURE_CHECKS: Final[dict[LivenessGesture, Callable[[_Marks], bool]]] = {
    LivenessGesture.BLINK: _blink_detected,
    LivenessGesture.SMILE: _smile_detected,
    LivenessGesture.HEAD_TURN: _head_turn_detected,
}


def _aspect_ratio(points: Sequence[tuple[int, int]]) -> float | None:
    """Nöqtə dəstinin sərhəd qutusunun hündürlük/en nisbəti."""
    if not points:
        return None
    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]
    width = max(xs) - min(xs)
    if width <= 0:
        return None
    return (max(ys) - min(ys)) / width


__all__ = [
    "BLINK_ASPECT_THRESHOLD",
    "EXPECTED_DIMENSION",
    "FRAME_CHANNELS",
    "HEAD_TURN_RATIO_THRESHOLD",
    "MIN_ALIGNMENT_DEGREES",
    "QUALITY_CLIPPING_TOLERANCE",
    "QUALITY_CONTRAST_REFERENCE",
    "QUALITY_SHARPNESS_REFERENCE",
    "SMILE_WIDTH_RATIO_THRESHOLD",
    "DlibFaceMatcher",
    "FaceEngineUnavailableError",
    "FaceFrameFormatError",
    "engine_available",
]
