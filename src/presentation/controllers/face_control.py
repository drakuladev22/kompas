"""Face Control ekranlarının canlı yolu — `facecontrol.md` Faza 4.

İKİ KONTROLLER, İKİ AYRI SƏLAHİYYƏT:

    `FaceEnrollmentController` → `can_manage_employees` (bənd 1, 2, 11)
    `FaceExemptionController`  → `can_manage_face_exemptions` (bənd 14, hardlock 2)

──────────────────────────────────────────────────────────────────────────────
NİYƏ `screen_data.py`-DA DEYİL, AYRI FAYLDA
──────────────────────────────────────────────────────────────────────────────
`screen_data.py` YALNIZ oxu yolunu bağlayır: sessiya açır, setter çağırır,
bağlayır. Hər iki ekran isə HƏM oxuyur, HƏM YAZIR (qeydiyyat, yenidən-qeydiyyat,
istisna verilməsi/ləğvi) və hər yazıdan sonra siyahını yenidən oxumalıdır —
qeydiyyatdan sonra işçinin vəziyyəti `NEW`-dən `ENROLLED`-a keçir, istisna
verildikdən sonra o, aktiv siyahıya düşür. Bu dövrə `populate()`-ın tək
çağırışından uzun yaşayır (CLAUDE.md §6).

──────────────────────────────────────────────────────────────────────────────
HƏR ƏMƏLİYYAT ÖZ SESSİYASINDA
──────────────────────────────────────────────────────────────────────────────
Kontroller sessiyanı SAXLAMIR. Səbəb burada xüsusilə kəskindir: qeydiyyat
əməliyyatı KAMERADAN kadr çəkir və bu, saniyələr çəkir. Uzun-ömürlü tranzaksiya
həmin müddət boyu `employees` sətrini kilidli saxlayardı və panel açıq qaldıqca
kilid davam edərdi.

──────────────────────────────────────────────────────────────────────────────
KAMERA MÜHƏRRİKİ NİYƏ EKRAN AÇILANDA YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`ApplicationContext.face_engine()` `face_recognition` kitabxanasını TƏNBƏL
yükləyir (~1 s + ~150 MB model) və `composition.py` bunu qəsdən ilk FAKTİKİ üz
əməliyyatına saxlayır. Qeydiyyat ekranı isə məhz həmin əməliyyat üçün açılır:
admin işçini yanına çağırıb ekranı açır. Yükü ORADA ödəmək operatorun `[Çək]`
düyməsini basıb səbəbsiz gözləməsindən yaxşıdır — üstəlik nasazlıq (kamera
qoşulmayıb) DƏRHAL görünür, kadr çəkilişi cəhdindən sonra deyil.

Face Control əhatəsindən kənar mağazalar bu qiyməti ödəmir: ekran menyuda
`can_manage_employees` ilə qapılıdır və heç bir başqa yol onu açmır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.face_recognition import add_months
from src.domain.value_objects.identifiers import EmployeeId, FaceExemptionId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.face_control import (
        FaceEnrollmentScreen,
        FaceExemptionScreen,
    )

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Kamera hazır olduqda göstərilən mətn.
CAMERA_READY = "Kamera hazırdır. İşçi kameraya baxsın və [Çək] düyməsini basın."

#: Kamera əlçatmaz olduqda — SƏSSİZ keçid YOX, AÇIQ səbəb (bənd 5 fəlsəfəsi).
CAMERA_UNAVAILABLE = (
    "Kamera əlçatmazdır. Kabel bağlantısını və cihaz sürücüsünü yoxlayın — "
    "kamera olmadan üz qeydiyyatı aparıla bilməz."
)

#: Ləğv səbəbi soruşulan modalın mətni (bənd 14: ləğv İNSAN qərarıdır).
REVOKE_PROMPT = (
    "İstisna vaxtından əvvəl ləğv olunur. Səbəbi yazın — qeyd audit jurnalına "
    "düşür və işçiyə bildiriş göndərilir:"
)

#: Qeydiyyat siyahısının tavanı — `_eligible_employees` (performance_review.py)
#: ilə eyni ədəd. Bu, SİYASƏT DEYİL, sorğu həddidir: 235 nəfərlik şəbəkədə də
#: dropdown 500 sətirdən uzun olmamalıdır.
EMPLOYEE_ROW_LIMIT = 500


def enrollment_state(enrolled_at: datetime | None, *, now: datetime, reminder_months: int) -> str:
    """İşçinin üz qeydiyyatının vəziyyəti — `NEW` / `ENROLLED` / `STALE`.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `FaceProfile.is_stale` ÇAĞIRILMIR
    ──────────────────────────────────────────────────────────────────────────
    Həmin metod TAM profil obyektini (o cümlədən DEŞİFRƏ EDİLMİŞ vektoru)
    tələb edir. Siyahıda 500 işçi ola bilər — hər biri üçün profil yükləmək
    500 Fernet deşifrəsi demək olardı, yəni biometrik vektorlar yalnız
    «köhnəlibmi?» sualına cavab vermək üçün yaddaşa çıxardı. Burada isə YALNIZ
    `face_enrolled_at` sütunu oxunur.

    Qayda TƏKRARLANMIR, sərhəd EYNİDİR: `add_months` domen funksiyasıdır və
    `FaceProfile.is_stale` də onu işlədir — «ay» anlayışının iki tərifi
    yaranmır (bax `face_recognition.add_months` başlığı).
    """
    if enrolled_at is None:
        return "NEW"
    if reminder_months > 0 and now >= add_months(enrolled_at, reminder_months):
        return "STALE"
    return "ENROLLED"


# --------------------------------------------------------------------------- #
# 1–2. Qeydiyyat / yenidən-qeydiyyat
# --------------------------------------------------------------------------- #


def run_enrollment_job(
    _app: object,
    job: Callable[[], object],
    *,
    on_success: Callable[[Any], None],
    on_failure: Callable[[BaseException], None],
    executor: Any = None,
) -> Any:
    """Ağır üz emalını FON SAPINA buraxır və nəticəni GUI sapına qaytarır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA FUNKSİYA — METOD DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Beləliklə icra yeri KONTROLLERDƏN ASILI OLMADAN ölçülə bilir
    (`test_face_enrollment_threading.py`): test sahtə iş verir və işin HANSI
    sapda getdiyini yoxlayır. Metod olsaydı, test tam kontroller qrafını
    (kontekst, aktor, ekran) qurmalı olardı və ölçdüyü şey — sap — həmin
    quraşdırmanın altında itərdi.

    Qaytarılan `BackgroundTask` çağıranda SAXLANILMALIDIR: nəticə gəlməmiş
    Python onu topladıqda siqnal sükutla itərdi.

    `executor` verilməzsə Qt sap hovuzu işlədilir. Testlər `InlineExecutor`
    ötürür: onlar İCRA YERİNİ deyil, MƏNTİQİ ölçür və hadisə dövrəsi
    gözləməsi qeyri-sabit test yaradardı (bax `background_task` başlığı).
    """
    from src.presentation.background_task import BackgroundTask  # noqa: PLC0415

    task = BackgroundTask(name="FACE_ENROLLMENT", executor=executor)
    task.succeeded.connect(on_success)
    task.failed.connect(on_failure)
    task.run(job)
    return task


class FaceEnrollmentController:
    """«Üz Qeydiyyatı» ekranını `FaceEnrollmentUseCase`-ə bağlayır."""

    def __init__(
        self, context: ApplicationContext, actor: Employee, *, executor: Any = None
    ) -> None:
        self._context = context
        self._actor = actor
        #: Fon icraçısı — istehsalatda Qt hovuzu, testlərdə `InlineExecutor`.
        self._executor = executor
        #: Qaçan işə istinad: nəticə gəlməmiş toplanarsa siqnal itərdi.
        self._task: Any = None

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: FaceEnrollmentScreen) -> None:
        screen.capture_requested.connect(lambda key: self._on_capture(screen, key))
        screen.re_enroll_requested.connect(
            lambda key, reason: self._on_re_enroll(screen, key, reason)
        )
        screen.retake_requested.connect(lambda key: self._on_retake(screen, key))
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: FaceEnrollmentScreen) -> None:
        """İşçi siyahısını, kamera vəziyyətini və kadr sayını yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                screen.set_employees(_enrollment_rows(session, self._actor))
                screen.set_camera(self._camera_row(session))
        except KompasOSError as error:
            screen.show_error(title="Ekran açıla bilmədi", message=error.user_message)
        except Exception:
            _error_log.exception("FACE_ENROLLMENT_LOAD_FAILED")
            screen.show_error(
                title="Ekran açıla bilmədi",
                message="İşçi siyahısı oxuna bilmədi. Yenidən cəhd edin.",
            )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_capture(self, screen: FaceEnrollmentScreen, employee_id: str) -> None:
        """`[Çək]` — İLK qeydiyyat (bənd 1)."""
        subject = _employee_id_or_none(employee_id)
        if subject is None:
            screen.set_result({"accepted": "0", "message": "İşçi identifikatoru düzgün deyil."})
            return

        def run(session: Session) -> Any:
            return session.face_enrollment.enroll(
                tenant_id=session.tenant_id,
                actor=self._actor,
                subject_id=subject,
            )

        self._run(screen, run)

    def _on_re_enroll(self, screen: FaceEnrollmentScreen, employee_id: str, reason: str) -> None:
        """`[Yadda Saxla]` — YENİDƏN qeydiyyat (bənd 2), səbəb MƏCBURİ."""
        subject = _employee_id_or_none(employee_id)
        if subject is None:
            screen.set_result({"accepted": "0", "message": "İşçi identifikatoru düzgün deyil."})
            return

        def run(session: Session) -> Any:
            return session.face_re_enrollment.re_enroll(
                tenant_id=session.tenant_id,
                actor=self._actor,
                subject_id=subject,
                reason=reason,
            )

        self._run(screen, run)

    def _on_retake(self, screen: FaceEnrollmentScreen, employee_id: str) -> None:
        """`[Yenidən Çək]` — SON əməliyyatı təkrarlayır.

        Hansı əməliyyatın təkrarlanacağını EKRANIN REJİMİ həll edir, ayrı
        yaddaş DEYİL: rejim onsuz da seçilmiş işçinin qeydiyyat vəziyyətindən
        doğulur (`FaceEnrollmentScreen._on_subject_changed`). İkinci bir
        «son əməliyyat» dəyişəni saxlasaydıq, o, siyahı yeniləndikdən sonra
        ekranda görünənlə ayrıla bilərdi.
        """
        if screen.mode() == "RE_ENROLL":
            self._on_re_enroll(screen, employee_id, screen.reason_text())
            return
        self._on_capture(screen, employee_id)

    def _run(self, screen: FaceEnrollmentScreen, action: Any) -> None:
        """Ortaq icra qabığı — iş FON SAPINDA, nəticə isə GUI sapında.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ FON SAPI (SETUP-1 Faza 3)
        ──────────────────────────────────────────────────────────────────────
        Bu qabığın içindəki iş üç ağır addımdan ibarətdir: kamera kadr çəkir,
        `dlib` hər kadr üçün 128-ölçülü kodlaşdırma hesablayır, sonra baza
        yazısı gedir — saniyələrlə çəkən CPU işi. GUI sapında icra olunanda
        pəncərə həmin müddət boyu «Cavab vermir» olurdu və operator proqramı
        bağlamağa çalışırdı, məhz üz məlumatı yazılarkən.

        SIRA VACİBDİR: əvvəlcə `refresh()` (siyahı və vəziyyət yenilənir),
        SONRA `set_result()`. Tərsinə etsəydik, `refresh()` seçim siqnalını
        yenidən işə salar və nəticə mesajını silərdi — operator «heç nə
        olmadı» görərdi.

        SESSİYA FON SAPINDA AÇILIR: `BackgroundTask` sənədinin tələbi budur —
        DB bağlantısı sapa bağlıdır və GUI sapında açılan sessiyanı fon
        sapından işlətmək bağlantını korlayardı.
        """

        def job() -> object:
            with self._context.session(user_id=self._actor.id) as session:
                result = action(session)
                if result.accepted:
                    # KADRLAR KEÇMƏYİBSƏ COMMIT EDİLMİR: `capture_and_store`
                    # rədd halında heç nə yazmır, lakin yenidən-qeydiyyatda
                    # arxiv sətri artıq yazılıb — onu commit etmək «dəyişdi»
                    # kimi görünən, faktiki olaraq baş tutmamış əməliyyatın
                    # izini qoyardı (bax `FaceReEnrollmentUseCase.re_enroll`
                    # sonundakı şərh).
                    session.commit()
                return result

        def succeeded(result: Any) -> None:
            self.refresh(screen)
            screen.set_result(_result_row(result))
            screen.set_frames([_frame_row(frame) for frame in result.frames])

        def failed(error: BaseException) -> None:
            if isinstance(error, KompasOSError):
                self._fail(screen, error.user_message)
                return
            _error_log.error("FACE_ENROLLMENT_WRITE_FAILED", exc_info=error)
            self._fail(screen, "Əməliyyat tamamlanmadı. Yenidən cəhd edin.")

        self._task = run_enrollment_job(
            None, job, on_success=succeeded, on_failure=failed, executor=self._executor
        )

    @staticmethod
    def _fail(screen: FaceEnrollmentScreen, message: str) -> None:
        """Uğursuz cəhd — mesaj GÖSTƏRİLİR, KÖHNƏ kadr cədvəli TƏMİZLƏNİR.

        Cədvəli təmizləmək məcburidir: əvvəlki cəhdin «2-ci kadr qaranlıqdır»
        sətri yeni xəta mesajının altında qalsaydı, operator onu bu cəhdin
        səbəbi sayardı — halbuki bu dəfə kadr ümumiyyətlə çəkilməyib
        (səlahiyyət, kamera və ya baza xətası).
        """
        screen.set_result({"accepted": "0", "message": message})
        screen.set_frames([])

    # ------------------------------ köməkçilər ------------------------------- #

    def _camera_row(self, session: Session) -> dict[str, str]:
        """Kameranın vəziyyəti + ROOT-dan gələn kadr sayı.

        NASAZLIQ İSTİSNA ATMIR: `is_available()` `False` qaytaranda ekran
        səbəbi göstərir və düymələr sönür. Bu, «səssiz keçid» DEYİL — bənd 5
        məhz gizli davranış dəyişikliyini qadağan edir, açıq xəbərdarlığı yox.
        """
        camera, _ = self._context.face_engine()
        try:
            available = bool(camera.is_available())
        except Exception:
            _error_log.exception("FACE_CAMERA_PROBE_FAILED")
            available = False
        return {
            "available": "1" if available else "0",
            "message": CAMERA_READY if available else CAMERA_UNAVAILABLE,
            "frame_count": str(_limit_int(session, SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT)),
        }


# --------------------------------------------------------------------------- #
# 14. İstisna idarəetməsi
# --------------------------------------------------------------------------- #


class FaceExemptionController:
    """«Üz Təsdiqi İstisnaları» ekranını `FaceControlExemptionUseCase`-ə bağlayır.

    SƏLAHİYYƏT BURADA YOXLANMIR: `list_active`/`grant`/`revoke` hər biri
    `can_manage_face_exemptions` tələb edir və qapı use case-in ÖZÜNDƏDİR
    (`_require_permission`). Kontroller onu təkrarlasaydı, qayda iki yerdə
    yaşayardı və ekranı yan keçən yol üçün yalnız biri işləyərdi.
    """

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: FaceExemptionScreen) -> None:
        screen.grant_requested.connect(
            lambda key, reason, days: self._on_grant(screen, key, reason, days)
        )
        screen.revoke_requested.connect(lambda key: self._on_revoke(screen, key))
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: FaceExemptionScreen) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                screen.set_limits(_exemption_limits(session))
                screen.set_employees(_employee_options(session))
                views = session.face_exemptions.list_active(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                screen.set_exemptions([_exemption_row(session, view) for view in views])
        except KompasOSError as error:
            # Səlahiyyəti olmayan aktor BOŞ siyahı deyil, SƏBƏB görməlidir:
            # boş cədvəl «istisna yoxdur» kimi oxunardı və bu, təhlükəsizlik
            # baxımından yanlış təəssüratdır.
            screen.show_error(title="İstisnalar oxunmadı", message=error.user_message)
        except Exception:
            _error_log.exception("FACE_EXEMPTIONS_LOAD_FAILED")
            screen.show_error(
                title="İstisnalar oxunmadı",
                message="Siyahı oxuna bilmədi. Yenidən cəhd edin.",
            )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_grant(
        self, screen: FaceExemptionScreen, employee_id: str, reason: str, days: int
    ) -> None:
        subject = _employee_id_or_none(employee_id)
        if subject is None:
            screen.show_error(
                title="İstisna verilmədi", message="İşçi identifikatoru düzgün deyil."
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                # BİTMƏ ANI BURADA HESABLANIR, EKRANDA YOX: ekran yalnız GÜN
                # sayını bilir; `granted_at`-dan sayılan tavan yoxlaması
                # (`_require_within_ceiling`) use case-dədir və o, öz
                # `Clock`-unu işlədir. İki ayrı «indi» yaranmasın deyə burada
                # da eyni an bazadan deyil, tək yerdən götürülür.
                expires_at = _now() + _days(days)
                session.face_exemptions.grant(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=subject,
                    reason=reason,
                    expires_at=expires_at,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="İstisna verilmədi", message=error.user_message)
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("FACE_EXEMPTION_GRANT_FAILED")
            screen.show_error(
                title="İstisna verilmədi",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    def _on_revoke(self, screen: FaceExemptionScreen, exemption_id: str) -> None:
        """`[Ləğv Et]` — səbəb MƏCBURİDİR (bax `FaceExemption.revoked`)."""
        target = _exemption_id_or_none(exemption_id)
        if target is None:
            screen.show_error(title="İstisna ləğv edilmədi", message="Sətir tapılmadı.")
            return

        reason = self._ask_reason(screen)
        if reason is None:
            # BOŞ CAVAB YAZI YOLUNA GETMİR: domen istisnası («Ləğvin səbəbi
            # boş ola bilməz») istifadəçiyə xəta kimi görünərdi, halbuki o,
            # sadəcə modalı bağlayıb.
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.face_exemptions.revoke(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    exemption_id=target,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="İstisna ləğv edilmədi", message=error.user_message)
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("FACE_EXEMPTION_REVOKE_FAILED")
            screen.show_error(
                title="İstisna ləğv edilmədi",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    @staticmethod
    def _ask_reason(screen: FaceExemptionScreen) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen, "Face Control istisnasını ləğv et", REVOKE_PROMPT
        )
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    """Tz-aware indi — ekran qatının yeganə vaxt mənbəyi."""
    return datetime.now(UTC)


def _days(count: int) -> Any:
    from datetime import timedelta  # noqa: PLC0415

    return timedelta(days=max(1, count))


def _limit_int(session: Session, key: SystemLimitKey) -> int:
    value: int = session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
    return value


def _enrollment_rows(session: Session, actor: Employee) -> list[dict[str, str]]:
    """Qeydiyyat siyahısı — AKTORUN ÖZÜ SİYAHIDA YOXDUR.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SÜZGƏC BURADADIR
    ──────────────────────────────────────────────────────────────────────────
    `FaceEnrollmentUseCase.assert_may_enroll` özünə-qeydiyyatı onsuz da rədd
    edir (bənd 1: nəzarətli proses ikinci insanın iştirakını tələb edir).
    Lakin «GÖRMƏK = SƏLAHİYYƏTİN OLMASI» qaydası deyir ki, edilə bilməyən
    əməliyyat interfeysdə GÖRÜNMƏMƏLİDİR — admin öz adını seçib `[Çək]`
    basmalı və yalnız sonra istisna almalı DEYİL.

    Qayda TƏKRARLANMIR: domen qapısı yerində qalır, burada yalnız həmin
    qapının arxasındakı seçim gizlədilir.
    """
    now = _now()
    reminder_months = _limit_int(session, SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS)
    rows = session.uow.connection.execute(
        """
        SELECT e.id, e.first_name, e.last_name, e.face_enrolled_at,
               COALESCE(s.name, '—') AS store_name
          FROM employees e
          LEFT JOIN stores s ON s.id = e.store_id
         WHERE e.tenant_id = %s AND e.is_active AND e.id <> %s
         ORDER BY e.last_name, e.first_name
         LIMIT %s
        """,
        (session.tenant_id, actor.id, EMPLOYEE_ROW_LIMIT),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "name": f"{row['first_name']} {row['last_name']}".strip(),
            "store": str(row["store_name"]),
            "state": enrollment_state(
                row["face_enrolled_at"], now=now, reminder_months=reminder_months
            ),
            "enrolled_at": _moment(row["face_enrolled_at"]),
        }
        for row in rows
    ]


def _employee_options(session: Session) -> list[dict[str, str]]:
    """İstisna verilə bilən işçilər — `id`, `name`.

    AKTOR ÇIXARILMIR (qeydiyyat siyahısından fərqli olaraq): `FaceControl
    ExemptionUseCase.grant` özünə istisna verməyi qadağan ETMİR və burada
    yeni qadağa İCAD ETMİRİK. Root öz hesabına istisna verirsə, bu, audit
    sətrində açıq görünür və hardlock onsuz da yalnız Root/CEO-ya icazə verir.
    """
    rows = session.uow.connection.execute(
        """
        SELECT e.id, e.first_name, e.last_name
          FROM employees e
         WHERE e.tenant_id = %s AND e.is_active
         ORDER BY e.last_name, e.first_name
         LIMIT %s
        """,
        (session.tenant_id, EMPLOYEE_ROW_LIMIT),
    ).fetchall()
    return [
        {"id": str(row["id"]), "name": f"{row['first_name']} {row['last_name']}".strip()}
        for row in rows
    ]


def _exemption_limits(session: Session) -> dict[str, str]:
    """Ekranın gözlədiyi tavan sözlüyü — açarlar maket yolu ilə EYNİDİR."""
    from src.application.use_cases.face_control import (  # noqa: PLC0415
        MIN_EXEMPTION_REASON_LENGTH,
    )

    return {
        "max_days": str(_limit_int(session, SystemLimitKey.FACE_EXEMPTION_MAX_DAYS)),
        # SXEM MƏHDUDİYYƏTİDİR, ROOT PARAMETRİ DEYİL: `face_control_exemptions.
        # reason` sütununda `CHECK (char_length(trim(reason)) >= 10)` var və
        # onu ekrandan aşağı salmaq bazanın rədd edəcəyi dəyəri yazmağa icazə
        # vermək olardı (bax use case-dəki eyni sabitin şərhi).
        "min_reason_length": str(MIN_EXEMPTION_REASON_LENGTH),
    }


def _exemption_row(session: Session, view: Any) -> dict[str, str]:
    """`FaceExemptionView` → ekranın FAKTİKİ gözlədiyi açarlar (CLAUDE.md §6)."""
    exemption = view.exemption
    return {
        "id": str(exemption.exemption_id),
        "employee": _employee_name(session, exemption.employee_id),
        "reason": exemption.reason,
        "expires_at": _moment(exemption.expires_at),
        "days_remaining": f"{view.days_remaining} gün",
        "granted_by": _employee_name(session, exemption.granted_by),
    }


def _employee_name(session: Session, employee_id: EmployeeId) -> str:
    """İşçi adı — tapılmasa identifikator GİZLƏDİLMİR.

    Silinmiş/başqa kirayəçidən qalmış sətir üçün boş ad göstərmək «bu istisna
    kimindir?» sualını cavabsız qoyardı — halbuki istisna məhz həmin suala
    görə auditlənir.
    """
    employee = session.uow.employees.get(employee_id)
    if employee is None:
        return f"(naməlum · {str(employee_id)[:8]})"
    name: str = employee.full_name
    return name


def _result_row(result: Any) -> dict[str, str]:
    """`FaceEnrollmentResult` → ekran sözlüyü (maket yolu ilə EYNİ açarlar)."""
    return {
        "accepted": "1" if result.accepted else "0",
        "message": result.message_az,
        "frames_total": str(len(result.frames)),
        "frames_accepted": str(result.accepted_frame_count),
        "archived": "1" if result.archived_previous else "0",
    }


def _frame_row(frame: Any) -> dict[str, str]:
    """`FaceEnrollmentFrameOutcome` → cədvəl sətri.

    SƏBƏB MÜMKÜN QƏDƏR KONKRETDİR (bənd 1): «uğursuz» əvəzinə «Kadrda üz
    aşkarlanmadı» / «Keyfiyyət balı 0.31 — tələb olunan 0.50». Mətn use
    case-dən gəlir, ekran onu YENİDƏN yazmır.
    """
    return {
        "index": str(frame.index),
        "accepted": "1" if frame.accepted else "0",
        "quality": f"{frame.quality:.2f}",
        "reason": frame.reason_az or "—",
    }


def _moment(value: datetime | None) -> str:
    """Tz-aware an → «12.08.2026 09:42». Boş dəyər boş sətir qaytarır."""
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y %H:%M")


def _employee_id_or_none(raw: str) -> EmployeeId | None:
    try:
        return EmployeeId(uuid.UUID(raw))
    except (AttributeError, TypeError, ValueError):
        return None


def _exemption_id_or_none(raw: str) -> FaceExemptionId | None:
    try:
        return FaceExemptionId(uuid.UUID(raw))
    except (AttributeError, TypeError, ValueError):
        return None


__all__ = [
    "CAMERA_READY",
    "CAMERA_UNAVAILABLE",
    "EMPLOYEE_ROW_LIMIT",
    "REVOKE_PROMPT",
    "FaceEnrollmentController",
    "FaceExemptionController",
    "enrollment_state",
]
