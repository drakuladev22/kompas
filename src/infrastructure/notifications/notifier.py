"""Bildiriş yazıcısı və e-poçt ehtiyat kanalı (bölmə 7) — Faza 3.12.

──────────────────────────────────────────────────────────────────────────────
ƏVVƏLCƏ YAZ, SONRA GÖNDƏR ("outbox" nümunəsi)
──────────────────────────────────────────────────────────────────────────────
`notify()` əvvəlcə `notifications` sətrini COMMIT edir, yalnız sonra e-poçt
göndərməyə çalışır. Sıra tərsinə olsaydı, SMTP serveri yavaş cavab verdikdə
bildirişin ÖZÜ də gecikərdi — halbuki in-app bildiriş e-poçtdan daha vacibdir.

Göndəriş uğursuz olduqda sətir `email_sent = FALSE` qalır və
`EmailFallbackDispatcher` onu arxa fonda təkrarlayır. Beləliklə "SMTP bir saat
işləmədi" halında bildiriş İTMİR — bu, spesifikasiyanın bütün məqsədidir
("gözdən qaçıb təcili müraciətə çevrilməsin").

──────────────────────────────────────────────────────────────────────────────
KRİTİKLİK YALNIZ YÜKSƏLİR
──────────────────────────────────────────────────────────────────────────────
Çağıran `is_critical=False` versə də, kateqoriya bölmə 7-nin siyahısındadırsa
sətir kritik yazılır (bax `domain/value_objects/notifications.py`). Əks
istiqamət (kritikdən adiyə endirmə) MÜMKÜN DEYİL.

──────────────────────────────────────────────────────────────────────────────
CƏHD SAYĞACI GÖNDƏRİŞDƏN ƏVVƏL ARTIRILIR (AT-MOST-ONCE)
──────────────────────────────────────────────────────────────────────────────
`email_attempts` SMTP çağırışından ƏVVƏL, ayrıca COMMIT ilə artırılır. Sıra
tərsinə idi və nəticəsi belə olurdu: göndəriş uğurlu olsa da status yazısı
(baza əlçatmaz, kilid, tranzaksiya xətası) uda bilirdi — sətir ƏBƏDİ `PENDING`
qalır, sayğac artmır, dispetçer isə HƏR dövrədə EYNİ e-poçtu yenidən
göndərirdi. Nəticə: qutuda yüzlərlə eyni mesaj və provayderin göndərəni
bloklaması.

NİYƏ AT-MOST-ONCE (at-least-once DEYİL): itirilən e-poçt burada məlumat itkisi
DEYİL — in-app bildiriş artıq COMMIT olunub və o, ƏSAS kanaldır (modul
başlığının birinci bölməsi). E-poçt YALNIZ dublikat xəbərdarlıqdır. Sonsuz
təkrar isə kanalın ÖZÜNÜ öldürür: bloklanan göndərici ilə heç bir kirayəçiyə
heç bir kritik e-poçt getmir. Yəni seçim "bir e-poçt itə bilər" ilə "bütün
e-poçt kanalı itə bilər" arasındadır.

──────────────────────────────────────────────────────────────────────────────
STATUS YAZISI UĞURSUZ OLARSA DÖVRƏ DAYANIR
──────────────────────────────────────────────────────────────────────────────
Status yazısının uda bilməsi yuxarıdakı sonsuz təkrarın MƏNBƏYİ idi. İndi
`_execute()` nəticəni QAYTARIR və `deliver_email()` uğursuzluqda
`NotificationStatusWriteError` atır: baza yazıla bilmirsə növbəti sətri
göndərmək eyni vəziyyəti təkrarlamaqdan başqa bir şey deyil. Dispetçer həmin
KİRAYƏÇİ üçün dövrəni dayandırır, digər kirayəçilər isə öz dövrəsini davam
etdirir (bax `_run`).

──────────────────────────────────────────────────────────────────────────────
ALICI: ŞİRKƏT ƏLAQƏSİ, FƏRDİ HESAB DEYİL
──────────────────────────────────────────────────────────────────────────────
E-poçt `license_tenants.company_contact_email`-ə gedir. Səbəb bölmə 2/8-də
yazılıb: bu ünvan ŞİRKƏT səviyyəlidir və fərdi hesabdan tam ayrıdır. İşçinin
şəxsi e-poçtuna göndərmək iki problem yaradardı — (a) işçi işdən çıxanda kanal
ölür, (b) cərimə/təsdiq məlumatı fərdi qutuya düşür.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.notifications import (
    email_body,
    email_subject,
    is_critical_category,
)
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_float,
    fallback_int,
    fallback_int_tuple,
)
from src.infrastructure.notifications.email import (
    EmailError,
    EmailNotConfiguredError,
    OutgoingEmail,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.notifications.email import SmtpEmailSender
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)

#: DÖRDÜ DƏ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`NOTIFY_MAX_BATCH_SIZE`, `NOTIFY_MAX_ATTEMPTS`,
#: `NOTIFY_RETRY_BACKOFF_MINUTES`, `NOTIFY_POLL_INTERVAL_SECONDS`;
#: seed: migrations/032). Bunlar SMTP PROVAYDERİNİN qaydalarına uyğunlaşdırılır
#: və provayder müəssisədən müəssisəyə fərqlənir — birində saatda 100 mesaj
#: limiti var, digərində 10 000. Sabit ədəd birinci halda göndərəni bloklayır,
#: ikinci halda isə kanalı lazımsız yavaşladır.
#:
#: Bir dövrdə göndərilən maksimum gözləyən bildiriş. Limit olmasaydı, uzun
#: fasilədən sonra ilk dövr yüzlərlə e-poçt göndərməyə çalışar və SMTP
#: provayderi göndərəni müvəqqəti bloklayardı (rate limit).
FALLBACK_MAX_BATCH: Final[int] = fallback_int(SystemLimitKey.NOTIFY_MAX_BATCH_SIZE)

#: Bu qədər uğursuz cəhddən sonra sətir "göndərilməz" sayılır və növbəni
#: tıxamır. Bildirişin özü DB-də qalır — in-app kanal işləməyə davam edir.
FALLBACK_MAX_ATTEMPTS: Final[int] = fallback_int(SystemLimitKey.NOTIFY_MAX_ATTEMPTS)

#: Cəhdlər arası gözləmə (dəqiqə): 1 → 5 → 15 → 60 → 240.
FALLBACK_BACKOFF_MINUTES: Final[tuple[int, ...]] = fallback_int_tuple(
    SystemLimitKey.NOTIFY_RETRY_BACKOFF_MINUTES
)

FALLBACK_POLL_SECONDS: Final[float] = fallback_float(SystemLimitKey.NOTIFY_POLL_INTERVAL_SECONDS)


class NotificationStatusWriteError(KompasOSError):
    """Bildirişin göndəriş vəziyyəti bazaya yazıla bilmədi.

    NİYƏ AYRICA TİP: bu, "e-poçt getmədi" DEYİL — "e-poçtun nə olduğunu qeyd
    edə bilmədik" deməkdir və nəticəsi tam FƏRQLİDİR. Birincisi backoff ilə
    təkrarlanır; ikincisində təkrar EYNİ e-poçtun yenidən göndərilməsi
    demək olardı (bax modul başlığı). Ona görə çağıran tərəf iki halı
    ayırd edə bilməlidir.
    """

    user_message = "Bildiriş vəziyyəti qeyd edilə bilmədi."


class PostgresNotifier:
    """`Notifier` portunun tətbiqi — in-app sətir + kritik hallarda e-poçt."""

    def __init__(
        self,
        database: Database,
        sender: SmtpEmailSender | None = None,
        *,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._database = database
        self._sender = sender
        self._limits = limits or InfrastructureLimits()

    def notify(
        self,
        *,
        tenant_id: TenantId,
        recipient_id: EmployeeId | None,
        category: str,
        title_az: str,
        body_az: str,
        is_critical: bool = False,
    ) -> None:
        critical = is_critical or is_critical_category(category)
        notification_id = self._insert(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            category=category,
            title_az=title_az,
            body_az=body_az,
            is_critical=critical,
        )

        if not critical:
            return
        # Dərhal cəhd: adminin qutusuna 2 dəqiqə gec düşən "təsdiq gözlənilir"
        # bildirişi çox vaxt artıq gecikmiş olur.
        try:
            self.deliver_email(
                tenant_id=tenant_id,
                notification_id=notification_id,
                category=category,
                title_az=title_az,
                body_az=body_az,
                attempts=0,
            )
        except NotificationStatusWriteError as exc:
            # BURADA UDULUR — və bu, qəsdli İSTİSNADIR: `notify()` iş axınının
            # ORTASINDAN çağırılır (cərimə verildi, icazə təsdiqləndi) və
            # in-app sətir ARTIQ commit olunub. İstisnanı yuxarı buraxmaq
            # e-poçt kanalının nasazlığına görə ƏSAS əməliyyatı geri qaytarardı
            # — halbuki e-poçt yalnız dublikat xəbərdarlıqdır. Dispetçer isə
            # əksinə: o, məhz bu iş üçün işləyir, ona görə orada dövrə DAYANIR.
            _log.error(
                "NOTIFY_EMAIL_SKIPPED",
                extra={
                    "notification_id": notification_id,
                    "error": str(exc),
                    "impact": "in-app bildiriş yerindədir — e-poçt fon dispetçerinə qalır",
                },
            )

    # -------------------------------- yazma ---------------------------------- #

    def _insert(
        self,
        *,
        tenant_id: TenantId,
        recipient_id: EmployeeId | None,
        category: str,
        title_az: str,
        body_az: str,
        is_critical: bool,
    ) -> str:
        with self._database.unit_of_work(tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notifications
                        (tenant_id, recipient_id, category, title_az, body_az, is_critical)
                    VALUES (%s, %s, %s, %s, %s, %s)
                 RETURNING id
                    """,
                    (tenant_id, recipient_id, category, title_az, body_az, is_critical),
                )
                row = cur.fetchone()
            uow.commit()
        return str(row["id"]) if row else ""

    # ------------------------------- göndəriş -------------------------------- #

    def deliver_email(
        self,
        *,
        tenant_id: TenantId,
        notification_id: str,
        category: str,
        title_az: str,
        body_az: str,
        attempts: int,
    ) -> bool:
        """Bir e-poçt cəhdi. XƏTA ATMIR — nəticə DB-də qeyd olunur.

        `EmailFallbackDispatcher` də bunu çağırır: göndəriş məntiqi (alıcının
        həlli, mövzu formatı, uğur/uğursuzluq qeydi) TƏK YERDƏ qalsın deyə
        ictimai metoddur — iki nüsxə bir gün fərqli davranardı.

        Raises:
            NotificationStatusWriteError: YEGANƏ atılan istisna — göndəriş
                DEYİL, STATUS YAZISI uğursuz olduqda (bax modul başlığı).
                SMTP nasazlığı hələ də istisna atmır: o, DB-də qeyd olunur və
                backoff ilə təkrarlanır.
        """
        if not notification_id:
            return False
        # CƏHD REZERVASİYASI — GÖNDƏRİŞDƏN ƏVVƏL, AYRI COMMIT ilə.
        # Bu sətir yazılmayıbsa GÖNDƏRMİRİK: sayğacsız göndəriş növbəti
        # dövrədə eyni e-poçtu yenidən göndərməyə aparır (modul başlığı).
        # Rezervasiya `email_next_attempt_at`-ı da təyin edir ki, proses
        # göndəriş ORTASINDA çöksə belə sətir dərhal DEYİL, backoff-dan sonra
        # yenidən götürülsün.
        self._reserve_attempt(tenant_id, notification_id, attempts)
        if self._sender is None or not self._sender.is_configured:
            self._record_failure(
                tenant_id, notification_id, "SMTP konfiqurasiya edilməyib", attempts, final=True
            )
            return False

        recipient, tenant_name = self._tenant_contact(tenant_id)
        if not recipient:
            # Şirkət əlaqəsi olmadan göndəriləcək yer yoxdur — təkrar cəhd
            # mənasızdır, ona görə dərhal "final" işarələnir.
            self._record_failure(
                tenant_id,
                notification_id,
                "Şirkət əlaqə e-poçtu təyin edilməyib",
                attempts,
                final=True,
            )
            return False

        message = OutgoingEmail(
            to=(recipient,),
            subject=email_subject(category, title_az),
            body=email_body(title_az, body_az, tenant_name=tenant_name),
        )
        try:
            self._sender.send(message)
        except EmailNotConfiguredError as exc:
            self._record_failure(tenant_id, notification_id, str(exc), attempts, final=True)
            return False
        except EmailError as exc:
            self._record_failure(tenant_id, notification_id, str(exc), attempts, final=False)
            return False

        self._record_success(tenant_id, notification_id)
        return True

    def _tenant_contact(self, tenant_id: TenantId) -> tuple[str, str]:
        """`(company_contact_email, tenant_name)`; oxunmazsa boş dəyərlər."""
        try:
            with self._database.unit_of_work(tenant_id) as uow, uow.connection.cursor() as cur:
                cur.execute(
                    "SELECT company_contact_email, tenant_name FROM license_tenants "
                    "WHERE tenant_id = %s",
                    (tenant_id,),
                )
                row = cur.fetchone()
        except Exception as exc:
            _log.warning("NOTIFY_CONTACT_LOOKUP_FAILED", extra={"error": str(exc)})
            return "", ""
        if row is None:
            return "", ""
        return str(row["company_contact_email"] or ""), str(row["tenant_name"] or "")

    def _record_success(self, tenant_id: TenantId, notification_id: str) -> None:
        self._execute(
            tenant_id,
            """
            UPDATE notifications
               SET email_sent = TRUE, email_sent_at = now(),
                   email_error = NULL, email_next_attempt_at = NULL
             WHERE id = %s
            """,
            (notification_id,),
        )

    def _record_failure(
        self,
        tenant_id: TenantId,
        notification_id: str,
        error: str,
        attempts: int,
        *,
        final: bool,
    ) -> None:
        next_attempt = self._next_attempt_minutes(attempts, final=final)
        # `email_attempts` BURADA ARTIRILMIR — `_reserve_attempt()` onu
        # göndərişdən ƏVVƏL artırıb (modul başlığı). İkinci artım eyni cəhdi
        # iki dəfə sayardı və tavan yarı-yolda dolardı.
        self._execute(
            tenant_id,
            """
            UPDATE notifications
               SET email_error = %s,
                   email_next_attempt_at = CASE
                       WHEN %s::INT IS NULL THEN NULL
                       ELSE now() + (%s::INT * INTERVAL '1 minute')
                   END
             WHERE id = %s
            """,
            (error[:500], next_attempt, next_attempt, notification_id),
        )
        _log.warning(
            "NOTIFY_EMAIL_FAILED",
            extra={
                "notification_id": notification_id,
                "attempts": attempts + 1,
                "retry_in_minutes": next_attempt,
                "error": error,
                "impact": "in-app bildiriş yerindədir — yalnız e-poçt kanalı gecikir",
            },
        )

    def _next_attempt_minutes(self, attempts: int, *, final: bool) -> int | None:
        """Növbəti cəhdə qalan dəqiqə; `None` = daha cəhd YOXDUR.

        Cəhd tavanı və gözləmə cədvəli HƏR ÇAĞIRIŞDA oxunur: dispetçer
        günlərlə işləyir və Root ara-sıra SMTP provayderini dəyişir.

        Hesablama AYRI metoddadır, çünki İKİ yerdən çağırılır — rezervasiya
        (göndərişdən əvvəl) və uğursuzluq qeydi (göndərişdən sonra). İki nüsxə
        olsaydı, biri dəyişəndə sətir "gözləyir, amma heç vaxt götürülmür"
        vəziyyətinə düşərdi.
        """
        max_attempts = self._limits.int_of(SystemLimitKey.NOTIFY_MAX_ATTEMPTS)
        schedule = self._limits.int_tuple_of(SystemLimitKey.NOTIFY_RETRY_BACKOFF_MINUTES)
        if final or attempts + 1 >= max_attempts:
            return None
        return _backoff_minutes(attempts, schedule)

    def _reserve_attempt(self, tenant_id: TenantId, notification_id: str, attempts: int) -> None:
        """Cəhdi GÖNDƏRİŞDƏN ƏVVƏL qeyd edir (at-most-once, modul başlığı).

        Raises:
            NotificationStatusWriteError: sayğac artırıla bilmədi — çağıran
                tərəf e-poçtu GÖNDƏRMƏMƏLİDİR.
        """
        next_attempt = self._next_attempt_minutes(attempts, final=False)
        self._execute(
            tenant_id,
            """
            UPDATE notifications
               SET email_attempts = email_attempts + 1,
                   email_next_attempt_at = CASE
                       WHEN %s::INT IS NULL THEN NULL
                       ELSE now() + (%s::INT * INTERVAL '1 minute')
                   END
             WHERE id = %s
            """,
            (next_attempt, next_attempt, notification_id),
        )

    def _execute(self, tenant_id: TenantId, sql: str, params: tuple[Any, ...]) -> None:
        """Status yazısı — uğursuzluq UDULMUR (bax modul başlığı).

        Əvvəl istisna yalnız loglanırdı. Nəticəsi görünməz sonsuz dövrə idi:
        `email_sent`/`email_attempts` yazılmır → sətir `PENDING` qalır →
        növbəti dövrədə EYNİ e-poçt yenidən göndərilir. İndi çağıran tərəf
        vəziyyəti bilir və dövrəni dayandıra bilir.
        """
        try:
            with self._database.unit_of_work(tenant_id) as uow:
                with uow.connection.cursor() as cur:
                    cur.execute(sql, params)
                uow.commit()
        except Exception as exc:
            _log.error("NOTIFY_STATUS_WRITE_FAILED", extra={"error": str(exc)})
            raise NotificationStatusWriteError(
                "Bildirişin göndəriş vəziyyəti yazıla bilmədi",
                context={"error": str(exc)},
            ) from exc


class EmailFallbackDispatcher:
    """Göndərilməmiş kritik bildirişləri arxa fonda təkrarlayır.

    `notifications` cədvəlindəki `idx_notifications_email_pending` indeksi
    məhz bu sorğu üçün mövcuddur (`WHERE is_critical AND NOT email_sent`).
    """

    def __init__(
        self,
        database: Database,
        notifier: PostgresNotifier,
        *,
        tenants: Callable[[], Sequence[TenantId]] | Sequence[TenantId],
        poll_seconds: float | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            poll_seconds: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.
        """
        self._database = database
        self._notifier = notifier
        self._limits = limits or InfrastructureLimits()
        # Hansı tenant-ların növbəsinə baxılacağı — mağaza quraşdırmasında bu,
        # tək elementli siyahıdır; Developer mühitində çoxlu ola bilər.
        self._tenants = tenants
        self._explicit_poll_seconds = poll_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def dispatch_once(self, tenant_id: TenantId, *, now: datetime | None = None) -> int:
        """Bir dövr. Qaytarır: uğurla göndərilən sətir sayı."""
        del now  # vaxt müqayisəsi SQL-də (`now()`) aparılır
        pending = self._pending(tenant_id)
        sent = 0
        for row in pending:
            try:
                ok = self._notifier.deliver_email(
                    tenant_id=tenant_id,
                    notification_id=str(row["id"]),
                    category=str(row["category"]),
                    title_az=str(row["title_az"]),
                    body_az=str(row["body_az"]),
                    attempts=int(row["email_attempts"]),
                )
            except NotificationStatusWriteError as exc:
                # DÖVRƏ DAYANIR, paket ATLANMIR: baza status yazısını qəbul
                # etmirsə növbəti sətri göndərmək eyni vəziyyəti təkrarlamaq,
                # yəni qeydiyyatsız e-poçt axını yaratmaq olardı. Sətirlər
                # növbədə qalır — bildiriş İTMİR, yalnız gecikir.
                _log.error(
                    "NOTIFY_DISPATCH_HALTED",
                    extra={
                        "tenant_id": str(tenant_id),
                        "notification_id": str(row["id"]),
                        "sent_before_halt": sent,
                        "error": str(exc),
                        "impact": "növbə qalır — növbəti dövrədə davam edir",
                    },
                )
                break
            sent += int(ok)
        if pending:
            _log.info(
                "NOTIFY_DISPATCH_CYCLE",
                extra={"pending": len(pending), "sent": sent, "tenant_id": str(tenant_id)},
            )
        return sent

    def _pending(self, tenant_id: TenantId) -> list[dict[str, Any]]:
        try:
            with self._database.unit_of_work(tenant_id) as uow, uow.connection.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, category, title_az, body_az, email_attempts
                      FROM notifications
                     WHERE is_critical
                       AND NOT email_sent
                       AND email_attempts < %s
                       AND (email_next_attempt_at IS NULL OR email_next_attempt_at <= now())
                     ORDER BY created_at
                     LIMIT %s
                    """,
                    (
                        self._limits.int_of(SystemLimitKey.NOTIFY_MAX_ATTEMPTS),
                        self._limits.int_of(SystemLimitKey.NOTIFY_MAX_BATCH_SIZE),
                    ),
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            _log.error("NOTIFY_PENDING_QUERY_FAILED", extra={"error": str(exc)})
            return []

    # ---------------------------- arxa fon sapı ------------------------------ #

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="email-fallback", daemon=True)
        self._thread.start()
        _log.info("EMAIL_DISPATCHER_STARTED", extra={"poll_seconds": self._poll_interval()})

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        _log.info("EMAIL_DISPATCHER_STOPPED")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                tenants = self._tenant_ids()
            except Exception as exc:  # arxa fon sapı heç vaxt ölməməlidir
                # Kirayəçi siyahısının ÖZÜ oxuna bilmədi — bu dövrədə
                # işlənəcək heç nə yoxdur, sap isə yaşamağa davam edir.
                _log.error("EMAIL_DISPATCH_CRASHED", extra={"error": str(exc)})
                tenants = []
            for tenant_id in tenants:
                self._dispatch_isolated(tenant_id)
            # Aralıq HƏR DÖVRDƏ oxunur — Root onu dəyişəndə növbəti gözləmə
            # artıq yeni dəyərlə olur, yenidən başlatma tələb olunmur.
            self._stop_event.wait(self._poll_interval())

    def _dispatch_isolated(self, tenant_id: TenantId) -> None:
        """Bir kirayəçinin xətası BURADA bitir — dövrün qalanı davam edir.

        NİYƏ `try` DÖVRÜN İÇİNDƏDİR: əvvəl blok dövrün XARİCİNDƏ idi, yəni
        BİRİNCİ kirayəçidə qalxan istisna dövrü qırırdı və sonrakı
        kirayəçilərin kritik bildirişləri həmin dövrədə HEÇ işlənmirdi. Bir
        müştərinin baza nasazlığı digərinin "45 dəqiqə gecikmə" e-poçtunu
        susdururdu. Naxış `erp/sync_worker.py::_sync_isolated`-ın eynisidir.
        """
        try:
            self.dispatch_once(tenant_id)
        except Exception as exc:
            _log.error(
                "EMAIL_DISPATCH_TENANT_FAILED",
                extra={
                    "tenant_id": str(tenant_id),
                    "error": str(exc),
                    "impact": "yalnız bu kirayəçi — dövrə digərləri ilə davam edir",
                },
            )

    def _poll_interval(self) -> float:
        if self._explicit_poll_seconds is not None:
            return self._explicit_poll_seconds
        return self._limits.float_of(SystemLimitKey.NOTIFY_POLL_INTERVAL_SECONDS)

    def _tenant_ids(self) -> list[TenantId]:
        source = self._tenants
        return list(source()) if callable(source) else list(source)


def _backoff_minutes(attempts: int, schedule: tuple[int, ...]) -> int:
    """Cəhd sayına görə gözləmə — cədvəl ÇAĞIRANDAN gəlir.

    Cədvəl arqument kimi ötürülür (modul sabiti oxunmur), çünki onu ROOT
    təyin edir və funksiyanın öz `system_limits` girişi olmamalıdır: bu,
    saf hesablamadır və testdə cədvəllə birlikdə yoxlanılır.
    """
    index = min(attempts, len(schedule) - 1)
    return schedule[index]


__all__ = [
    "FALLBACK_BACKOFF_MINUTES",
    "FALLBACK_MAX_ATTEMPTS",
    "FALLBACK_MAX_BATCH",
    "FALLBACK_POLL_SECONDS",
    "EmailFallbackDispatcher",
    "NotificationStatusWriteError",
    "PostgresNotifier",
]
