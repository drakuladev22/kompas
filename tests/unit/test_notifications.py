"""E-poçt fallback və anonim crash reporting — Faza 3.12 testləri.

İki müstəqil risk yoxlanılır:

    1. BİLDİRİŞ İTMƏMƏLİDİR — SMTP bir saat işləmirsə kritik bildiriş
       növbədə qalıb təkrarlanmalıdır (bölmə 7-nin bütün məqsədi).
    2. PII SIZMAMALIDIR — crash hesabatı stack-trace daşıyır və orada
       istifadəçi adı, e-poçt, UUID, PIN ola bilər (bölmə 8: "heç bir PII").
"""

from __future__ import annotations

import smtplib
import uuid
from typing import Any

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.domain.value_objects.notifications import (
    ALWAYS_CRITICAL_CATEGORIES,
    NotificationCategory,
    email_body,
    email_subject,
    is_critical_category,
)
from src.infrastructure.notifications.crash_reporter import (
    MAX_TRACE_CHARS,
    CrashReporter,
    fingerprint_of,
    format_trace,
    scrub,
)
from src.infrastructure.notifications.email import (
    DEFAULT_SMTP_PORT,
    IMPLICIT_TLS_PORT,
    EmailConfig,
    EmailError,
    EmailNotConfiguredError,
    OutgoingEmail,
    SmtpEmailSender,
)
from src.infrastructure.notifications.notifier import (
    BACKOFF_MINUTES,
    MAX_ATTEMPTS,
    EmailFallbackDispatcher,
    PostgresNotifier,
)

TENANT = TenantId(uuid.UUID("11111111-1111-1111-1111-111111111111"))
EMPLOYEE = EmployeeId(uuid.uuid4())
CONFIG = EmailConfig(host="smtp.example.az", port=587, username="bot", password="s3cret")


# --------------------------------------------------------------------------- #
# Saxta SMTP və saxta baza
# --------------------------------------------------------------------------- #


class FakeSmtp:
    """`smtplib.SMTP` əvəzi — bütün addımları qeyd edir."""

    def __init__(self, *, fail_on: str = "", error: Exception | None = None) -> None:
        self.steps: list[str] = []
        self.messages: list[Any] = []
        self._fail_on = fail_on
        self._error = error or smtplib.SMTPException("saxta nasazlıq")

    def _step(self, name: str) -> None:
        self.steps.append(name)
        if name == self._fail_on:
            raise self._error

    def ehlo(self) -> None:
        self._step("ehlo")

    def starttls(self, *, context: object = None) -> None:
        self._step("starttls")

    def login(self, username: str, password: str) -> None:
        self._step("login")

    def send_message(self, message: Any, *, to_addrs: list[str]) -> None:
        self._step("send")
        self.messages.append((message, to_addrs))

    def quit(self) -> None:
        self.steps.append("quit")


class FakeCursor:
    def __init__(self, database: FakeDatabase) -> None:
        self._db = database
        self._result: list[dict[str, Any]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._db.queries.append((" ".join(sql.split()), params))
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("INSERT INTO NOTIFICATIONS"):
            self._db.notification_seq += 1
            identifier = f"n-{self._db.notification_seq}"
            self._db.rows[identifier] = {
                "id": identifier,
                "category": params[2],
                "title_az": params[3],
                "body_az": params[4],
                "is_critical": params[5],
                "email_sent": False,
                "email_attempts": 0,
            }
            self._result = [{"id": identifier}]
        elif "FROM LICENSE_TENANTS" in normalized:
            self._result = [
                {
                    "company_contact_email": self._db.contact_email,
                    "tenant_name": self._db.tenant_name,
                }
            ]
        elif normalized.startswith("SELECT ID, CATEGORY"):
            self._result = [
                dict(row)
                for row in self._db.rows.values()
                if row["is_critical"]
                and not row["email_sent"]
                and row["email_attempts"] < MAX_ATTEMPTS
            ]
        elif "SET EMAIL_SENT = TRUE" in normalized:
            self._db.rows[params[0]]["email_sent"] = True
        elif "SET EMAIL_ATTEMPTS = EMAIL_ATTEMPTS + 1" in normalized:
            identifier = params[-1]
            self._db.rows[identifier]["email_attempts"] += 1
            self._db.errors.append(str(params[0]))
        else:
            self._result = []

    def fetchone(self) -> dict[str, Any] | None:
        return self._result[0] if self._result else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._result


class FakeUnitOfWork:
    def __init__(self, database: FakeDatabase) -> None:
        self._db = database
        self.committed = False

    def __enter__(self) -> FakeUnitOfWork:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    @property
    def connection(self) -> FakeUnitOfWork:
        return self

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._db)

    def commit(self) -> None:
        self.committed = True


class FakeDatabase:
    """DB-siz `Database` əvəzi — bildiriş axını sorğu səviyyəsində yoxlanılır."""

    def __init__(self, *, contact_email: str = "admin@kompas.az") -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.errors: list[str] = []
        self.notification_seq = 0
        self.contact_email = contact_email
        self.tenant_name = "Kompas Retail"

    def unit_of_work(self, tenant_id: TenantId, **kwargs: Any) -> FakeUnitOfWork:
        return FakeUnitOfWork(self)


def make_notifier(
    *, sender: SmtpEmailSender | None = None, contact_email: str = "admin@kompas.az"
) -> tuple[PostgresNotifier, FakeDatabase]:
    database = FakeDatabase(contact_email=contact_email)
    return PostgresNotifier(database, sender), database  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Domen: kritiklik qaydası
# --------------------------------------------------------------------------- #


class TestCriticality:
    def test_bolme_7_de_sadalanan_kateqoriyalar_kritikdir(self) -> None:
        for category in ALWAYS_CRITICAL_CATEGORIES:
            assert is_critical_category(category)

    def test_melumatlandirici_kateqoriya_kritik_deyil(self) -> None:
        assert not is_critical_category(NotificationCategory.FINE_ISSUED.value)

    def test_reconciliation_hec_vaxt_sukutla_qeyd_olunmur(self) -> None:
        """Bölmə 1/7: sistemin ən ciddi məlumat-bütövlüyü vəziyyəti."""
        assert is_critical_category("SAGA_PENDING_RECONCILIATION")

    def test_namelum_kateqoriya_kritik_sayilmir(self) -> None:
        assert not is_critical_category("BIZIM_OLMAYAN_KATEQORIYA")

    def test_mövzu_suzgeclene_bilen_prefiks_dasiyir(self) -> None:  # noqa: PLC2401
        subject = email_subject("DUAL_CONTROL_PENDING", "Override təsdiqi gözlənilir")

        assert subject.startswith("[KompasOS]")
        assert "İkili nəzarət" in subject

    def test_namelum_kateqoriya_da_movzu_yaradir(self) -> None:
        assert email_subject("XYZ", "Başlıq").startswith("[KompasOS] XYZ")

    def test_metn_sirket_adini_daxil_edir(self) -> None:
        body = email_body("Başlıq", "Mətn", tenant_name="Kompas Retail")

        assert "Kompas Retail" in body
        assert "Mətn" in body


# --------------------------------------------------------------------------- #
# SMTP
# --------------------------------------------------------------------------- #


class TestSmtpSender:
    def test_starttls_tetbiq_olunur(self) -> None:
        fake = FakeSmtp()
        sender = SmtpEmailSender(CONFIG, transport=lambda _config: fake)

        sender.send(OutgoingEmail(to=("a@b.az",), subject="Test", body="Mətn"))

        assert fake.steps == ["ehlo", "starttls", "ehlo", "login", "send", "quit"]

    def test_465_portunda_starttls_cagirilmir(self) -> None:
        """Implicit TLS-də kanal onsuz da şifrəlidir."""
        fake = FakeSmtp()
        config = EmailConfig(host="smtp.example.az", port=IMPLICIT_TLS_PORT, username="bot")
        sender = SmtpEmailSender(config, transport=lambda _config: fake)

        sender.send(OutgoingEmail(to=("a@b.az",), subject="Test", body="Mətn"))

        assert "starttls" not in fake.steps
        assert "send" in fake.steps

    def test_starttls_ugursuz_olarsa_gonderilmir(self) -> None:
        """PII-ni şifrələnməmiş kanalda göndərməkdənsə göndərməmək."""
        fake = FakeSmtp(fail_on="starttls", error=smtplib.SMTPNotSupportedError("yoxdur"))
        sender = SmtpEmailSender(CONFIG, transport=lambda _config: fake)

        with pytest.raises(EmailNotConfiguredError):
            sender.send(OutgoingEmail(to=("a@b.az",), subject="Test", body="Mətn"))

        assert "send" not in fake.steps

    def test_muveqqeti_nasazliq_adi_xeta_verir(self) -> None:
        """Təkrar cəhdə DƏYƏR — `EmailError`, `EmailNotConfiguredError` yox."""
        fake = FakeSmtp(fail_on="send")
        sender = SmtpEmailSender(CONFIG, transport=lambda _config: fake)

        with pytest.raises(EmailError) as info:
            sender.send(OutgoingEmail(to=("a@b.az",), subject="Test", body="Mətn"))

        assert not isinstance(info.value, EmailNotConfiguredError)

    def test_autentifikasiya_xetasi_tekrar_cehde_deymez_sayilir(self) -> None:
        fake = FakeSmtp(fail_on="login", error=smtplib.SMTPAuthenticationError(535, b"nope"))
        sender = SmtpEmailSender(CONFIG, transport=lambda _config: fake)

        with pytest.raises(EmailNotConfiguredError):
            sender.send(OutgoingEmail(to=("a@b.az",), subject="Test", body="Mətn"))

    def test_quit_xetasi_gonderisi_legv_etmir(self) -> None:
        """Server bağlantını kəssə də mesaj artıq qəbul edilib."""

        class QuitFails(FakeSmtp):
            def quit(self) -> None:
                raise smtplib.SMTPServerDisconnected("bağlantı kəsildi")

        fake = QuitFails()
        sender = SmtpEmailSender(CONFIG, transport=lambda _config: fake)

        sender.send(OutgoingEmail(to=("a@b.az",), subject="Test", body="Mətn"))

        assert "send" in fake.steps

    def test_konfiqurasiya_yoxdursa_ayrica_xeta_atilir(self) -> None:
        with pytest.raises(EmailNotConfiguredError):
            SmtpEmailSender(None).send(OutgoingEmail(to=("a@b.az",), subject="Test", body="Mətn"))

    def test_konfiqurasiya_sifreni_gostermir(self) -> None:
        assert "s3cret" not in repr(CONFIG)

    def test_env_den_qurulus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KOMPASOS_SMTP_HOST", "smtp.test.az")
        monkeypatch.setenv("KOMPASOS_SMTP_PORT", "yararsız")

        config = EmailConfig.from_env()

        assert config is not None
        assert config.port == DEFAULT_SMTP_PORT  # yararsız dəyər defolta düşür

    def test_host_yoxdursa_konfiqurasiya_yoxdur(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KOMPASOS_SMTP_HOST", raising=False)

        assert EmailConfig.from_env() is None

    def test_alicisiz_mesaj_yaradila_bilmir(self) -> None:
        with pytest.raises(ValueError, match="alıcı"):
            OutgoingEmail(to=(), subject="Test", body="Mətn")


# --------------------------------------------------------------------------- #
# Bildiriş axını
# --------------------------------------------------------------------------- #


class TestNotifier:
    def test_adi_bildiris_epocht_gondermir(self) -> None:
        fake = FakeSmtp()
        notifier, database = make_notifier(
            sender=SmtpEmailSender(CONFIG, transport=lambda _config: fake)
        )

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=EMPLOYEE,
            category=NotificationCategory.FINE_ISSUED.value,
            title_az="Cərimə",
            body_az="Mətn",
        )

        assert fake.messages == []
        assert database.rows["n-1"]["is_critical"] is False

    def test_kritik_bildiris_epocht_gonderir(self) -> None:
        fake = FakeSmtp()
        notifier, database = make_notifier(
            sender=SmtpEmailSender(CONFIG, transport=lambda _config: fake)
        )

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category=NotificationCategory.DUAL_CONTROL_PENDING.value,
            title_az="Təsdiq gözlənilir",
            body_az="Override 30 dəqiqədir gözləyir.",
        )

        assert len(fake.messages) == 1
        assert database.rows["n-1"]["email_sent"] is True

    def test_kritiklik_yalniz_yukselir(self) -> None:
        """`is_critical=False` verilsə də siyahıdakı kateqoriya kritik qalır."""
        fake = FakeSmtp()
        notifier, database = make_notifier(
            sender=SmtpEmailSender(CONFIG, transport=lambda _config: fake)
        )

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category="SAGA_PENDING_RECONCILIATION",
            title_az="Uzlaşdırma",
            body_az="Saga yarımçıq qaldı.",
            is_critical=False,
        )

        assert database.rows["n-1"]["is_critical"] is True
        assert len(fake.messages) == 1

    def test_cagiran_istediyini_kritik_ede_biler(self) -> None:
        fake = FakeSmtp()
        notifier, database = make_notifier(
            sender=SmtpEmailSender(CONFIG, transport=lambda _config: fake)
        )

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category=NotificationCategory.ERP_SYNC_FAILED.value,
            title_az="Sync",
            body_az="Server cavab vermir.",
            is_critical=True,
        )

        assert database.rows["n-1"]["is_critical"] is True

    def test_smtp_nasazligi_bildirisi_itirmir(self) -> None:
        """Ən vacib test: e-poçt getməsə də in-app sətir yerindədir."""
        fake = FakeSmtp(fail_on="send")
        notifier, database = make_notifier(
            sender=SmtpEmailSender(CONFIG, transport=lambda _config: fake)
        )

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category="TIMEOUT_ESCALATION",
            title_az="Gecikmə",
            body_az="45 dəqiqə keçdi.",
        )

        row = database.rows["n-1"]
        assert row["email_sent"] is False
        assert row["email_attempts"] == 1  # növbədə qalır

    def test_sirket_epochtu_yoxdursa_tekrar_cehd_edilmir(self) -> None:
        fake = FakeSmtp()
        notifier, database = make_notifier(
            sender=SmtpEmailSender(CONFIG, transport=lambda _config: fake), contact_email=""
        )

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category="TIMEOUT_ESCALATION",
            title_az="Gecikmə",
            body_az="Mətn",
        )

        assert fake.messages == []
        # `email_next_attempt_at` NULL yazılır → növbədən çıxır.
        assert database.queries[-1][1][1] is None

    def test_smtp_qurulmayibsa_tekrar_cehd_edilmir(self) -> None:
        notifier, database = make_notifier(sender=None)

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category="LICENSE_INACTIVE",
            title_az="Lisenziya",
            body_az="Deaktivdir.",
        )

        assert database.rows["n-1"]["email_attempts"] == 1
        assert database.queries[-1][1][1] is None

    def test_epocht_metninde_bildiris_movzusu_var(self) -> None:
        fake = FakeSmtp()
        notifier, _ = make_notifier(sender=SmtpEmailSender(CONFIG, transport=lambda _config: fake))

        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category="PAYMENT_REMINDER",
            title_az="Ödəniş",
            body_az="3 gün qalır.",
        )

        message, recipients = fake.messages[0]
        assert recipients == ["admin@kompas.az"]
        assert "Ödəniş" in message["Subject"]


class TestDispatcher:
    def test_novbedeki_bildiris_tekrar_gonderilir(self) -> None:
        """SMTP bərpa olunduqda gözləyən bildiriş çatdırılır."""
        failing = FakeSmtp(fail_on="send")
        sender = SmtpEmailSender(CONFIG, transport=lambda _config: failing)
        notifier, database = make_notifier(sender=sender)
        notifier.notify(
            tenant_id=TENANT,
            recipient_id=None,
            category="TIMEOUT_ESCALATION",
            title_az="Gecikmə",
            body_az="Mətn",
        )
        assert database.rows["n-1"]["email_sent"] is False

        working = FakeSmtp()
        dispatcher = EmailFallbackDispatcher(
            database,  # type: ignore[arg-type]
            PostgresNotifier(
                database,  # type: ignore[arg-type]
                SmtpEmailSender(CONFIG, transport=lambda _config: working),
            ),
            tenants=[TENANT],
        )

        sent = dispatcher.dispatch_once(TENANT)

        assert sent == 1
        assert database.rows["n-1"]["email_sent"] is True

    def test_cehd_limiti_novbeni_tixamir(self) -> None:
        database = FakeDatabase()
        database.rows["n-9"] = {
            "id": "n-9",
            "category": "TIMEOUT_ESCALATION",
            "title_az": "Gecikmə",
            "body_az": "Mətn",
            "is_critical": True,
            "email_sent": False,
            "email_attempts": MAX_ATTEMPTS,
        }
        dispatcher = EmailFallbackDispatcher(
            database,  # type: ignore[arg-type]
            PostgresNotifier(database, None),  # type: ignore[arg-type]
            tenants=[TENANT],
        )

        assert dispatcher.dispatch_once(TENANT) == 0

    def test_adi_bildirisler_novbede_gorunmur(self) -> None:
        database = FakeDatabase()
        database.rows["n-8"] = {
            "id": "n-8",
            "category": "FINE_ISSUED",
            "title_az": "Cərimə",
            "body_az": "Mətn",
            "is_critical": False,
            "email_sent": False,
            "email_attempts": 0,
        }
        dispatcher = EmailFallbackDispatcher(
            database,  # type: ignore[arg-type]
            PostgresNotifier(database, None),  # type: ignore[arg-type]
            tenants=[TENANT],
        )

        assert dispatcher.dispatch_once(TENANT) == 0

    def test_gozleme_muddeti_artir(self) -> None:
        assert BACKOFF_MINUTES[0] < BACKOFF_MINUTES[-1]
        assert len(BACKOFF_MINUTES) == MAX_ATTEMPTS


# --------------------------------------------------------------------------- #
# Crash reporting — PII qorunması
# --------------------------------------------------------------------------- #


class TestScrubbing:
    def test_windows_istifadeci_adi_gizlenir(self) -> None:
        cleaned = scrub(r'File "C:\Users\Elvin\Desktop\KompasOS\src\main.py", line 42')

        assert "Elvin" not in cleaned
        assert "KompasOS" in cleaned  # yol strukturu oxunaqlı qalır

    def test_linux_ev_qovlugu_gizlenir(self) -> None:
        assert "elvin" not in scrub("/home/elvin/app/main.py")

    def test_epocht_unvani_gizlenir(self) -> None:
        assert "aliyev@kompas.az" not in scrub("ValueError: aliyev@kompas.az tapılmadı")

    def test_uuid_gizlenir(self) -> None:
        cleaned = scrub("employee_id=11111111-1111-1111-1111-111111111111")

        assert "11111111-1111" not in cleaned

    def test_uzun_reqem_ardicilligi_gizlenir(self) -> None:
        """PIN, telefon, tabel nömrəsi."""
        assert "5512" not in scrub("PIN yoxlanışı uğursuz: 5512")

    def test_qisa_reqemler_qalir(self) -> None:
        """Sətir nömrələri oxunaqlı qalmalıdır."""
        assert "42" in scrub("line 42, in verify")


class TestCrashReporter:
    def _boom(self) -> None:
        message = "Employee aliyev@kompas.az (11111111-1111-1111-1111-111111111111) yoxdur"
        raise ValueError(message)

    def _capture(self) -> tuple[type[BaseException], BaseException, Any]:
        try:
            self._boom()
        except ValueError as exc:
            return type(exc), exc, exc.__traceback__
        msg = "istisna atılmadı"
        raise AssertionError(msg)

    def test_hesabatda_pii_yoxdur(self) -> None:
        sink = _RecordingSink()
        reporter = CrashReporter(sink, tenant_id=TENANT, app_version="1.0.0")

        reporter.report(*self._capture())

        trace = sink.reports[0].stack_trace
        assert "aliyev@kompas.az" not in trace
        assert "11111111-1111" not in trace
        # Sadəcə "yoxdur" kifayət etmir: yer tutucu OLMASI təmizləmənin
        # HƏQİQƏTƏN işə düşdüyünü göstərir (mətn ümumiyyətlə boş deyil).
        assert "<gizlədilib>" in trace
        assert "ValueError" in trace

    def test_hesabatda_tenant_id_yoxdur(self) -> None:
        sink = _RecordingSink()
        reporter = CrashReporter(sink, tenant_id=TENANT, app_version="1.0.0")

        reporter.report(*self._capture())

        assert str(TENANT) not in sink.reports[0].anonymous_tenant_ref

    def test_eyni_bug_eyni_barmaq_izi_verir(self) -> None:
        """Mesaj dəyişsə də qruplaşdırma pozulmamalıdır."""
        first = fingerprint_of(*_fingerprint_inputs("Employee 42 not found"))
        second = fingerprint_of(*_fingerprint_inputs("Employee 43 not found"))

        assert first == second

    def test_ferqli_istisna_tipi_ferqli_barmaq_izi_verir(self) -> None:
        value_error = fingerprint_of(*_fingerprint_inputs("x", error=ValueError))
        key_error = fingerprint_of(*_fingerprint_inputs("x", error=KeyError))

        assert value_error != key_error

    def test_surat_limiti_crash_dovrunu_dayandirir(self) -> None:
        sink = _RecordingSink()
        reporter = CrashReporter(sink, tenant_id=TENANT, app_version="1.0.0", max_per_fingerprint=2)

        for _ in range(10):
            reporter.report(*self._capture())

        assert len(sink.reports) == 2

    def test_sink_nasazligi_udulur(self) -> None:
        """Crash hook-undan atılan istisna çökmə mesajını uda bilərdi."""

        class Broken:
            def report_crash(self, report: object) -> None:
                msg = "şəbəkə yoxdur"
                raise RuntimeError(msg)

        reporter = CrashReporter(Broken(), tenant_id=TENANT, app_version="1.0.0")

        assert reporter.report(*self._capture()) is False

    def test_sondurulmus_hesabatci_gondermir(self) -> None:
        sink = _RecordingSink()
        reporter = CrashReporter(sink, tenant_id=TENANT, app_version="1.0.0", enabled=False)

        assert reporter.report(*self._capture()) is False
        assert sink.reports == []

    def test_tutulmus_istisna_da_gonderile_bilir(self) -> None:
        sink = _RecordingSink()
        reporter = CrashReporter(sink, tenant_id=TENANT, app_version="1.0.0")

        try:
            self._boom()
        except ValueError as exc:
            assert reporter.report_exception(exc) is True

        assert sink.reports[0].exception_type == "ValueError"

    def test_cox_uzun_trace_kesilir(self) -> None:
        long_error = RuntimeError("x" * (MAX_TRACE_CHARS * 2))

        trace = format_trace(RuntimeError, long_error, None)

        assert len(trace) <= MAX_TRACE_CHARS + 200
        assert "kəsildi" in trace

    def test_hook_callable_qaytarilir(self) -> None:
        sink = _RecordingSink()
        reporter = CrashReporter(sink, tenant_id=TENANT, app_version="1.0.0")

        reporter.as_hook()(*self._capture())

        assert len(sink.reports) == 1


class _RecordingSink:
    def __init__(self) -> None:
        self.reports: list[Any] = []

    def report_crash(self, report: Any) -> None:
        self.reports.append(report)


def _fingerprint_inputs(
    message: str, *, error: type[BaseException] = ValueError
) -> tuple[type[BaseException], Any]:
    """Eyni sətirdən atılan istisna — yalnız mətn dəyişir."""
    try:
        raise error(message)
    except BaseException as exc:
        return type(exc), exc.__traceback__
