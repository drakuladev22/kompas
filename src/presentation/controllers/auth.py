"""Giriş körpüsü: ekran ↔ use case — Faza 5.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI KONTROLLER QATI
──────────────────────────────────────────────────────────────────────────────
`AdminLoginScreen` yalnız iki şey bilir: nə göstərilir və hansı siqnal yayılır.
`AdminLoginUseCase` isə yalnız domen qaydalarını bilir. Aralarında bir tərcümə
addımı lazımdır, çünki:

    * use case `stored_hash`-ı AYRICA arqument kimi gözləyir (hash domen
      entity-sinə qoyulmur ki, təsadüfən log-a düşməsin) — onu repo-dan
      çıxarmaq kiminsə işi olmalıdır;
    * domen istisnaları (`AuthenticationError`, `AccountLockedError`)
      istifadəçiyə göstərilən mətn DEYİL — onları ekran dilinə çevirmək
      lazımdır;
    * ekran Qt siqnalları ilə işləyir, use case isə saf funksiyadır.

Bu qat həmin tərcüməni edir və BAŞQA HEÇ NƏ etmir — burada iş məntiqi yoxdur.

──────────────────────────────────────────────────────────────────────────────
XƏTA MƏTNİ NİYƏ HƏMİŞƏ EYNİDİR
──────────────────────────────────────────────────────────────────────────────
"İstifadəçi adı yanlışdır" və "şifrə yanlışdır" fərqli mesajlar olsaydı,
hücumçu mövcud hesabları sadalaya bilərdi (user enumeration). Use case özü də
mövcud olmayan hesab üçün Argon2 hesablamasını APARIR (sabit vaxt), ona görə
burada mesajı da eyni saxlamaq həmin qorumanı tamamlayır.

`AccountLockedError` İSTİSNADIR: bloklanma faktını gizlətmək istifadəçiyə
zərər verir — o, nə qədər gözləməli olduğunu bilməlidir.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, Protocol

from src.application.use_cases.authentication import (
    AccountLockedError,
    AuthenticationError,
    LoginStage,
)
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from src.application.use_cases.authentication import AdminLoginUseCase, LoginResult
    from src.domain.entities.employee import Employee
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.persistence.mappers import Credentials

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: İstifadəçiyə göstərilən ÜMUMİ xəta — hansı sahənin səhv olduğu açıqlanmır.
GENERIC_FAILURE_MESSAGE = "İstifadəçi adı və ya şifrə yanlışdır"


class CredentialSource(Protocol):
    """Şifrə hash-ını verən mənbə (`PostgresEmployeeRepository` bunu ödəyir)."""

    def credentials_for(self, employee_id: EmployeeId) -> Credentials | None: ...


class AttemptScope(Protocol):
    """Bir giriş cəhdinin SƏRHƏDİ — üç oxunun BİR tranzaksiyada qalması üçün.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ LAZIM OLDU (PERF-2)
    ──────────────────────────────────────────────────────────────────────────
    Bir giriş cəhdi üç ayrı oxu edir: işçi sətri, şifrə hash-ı, sonra use
    case-in özü. Hər üçü ayrı sessiya açsaydı — və məhz belə idi — uzaq bazada
    hər biri təxminən 0.8 saniyə çəkirdi: istifadəçi «Daxil Ol» düyməsindən
    sonra üç saniyəyə yaxın gözləyirdi. Kod bunu artıq NƏZƏRDƏ TUTMUŞDU (bax
    `app._SessionScopedLogin` başlığı: «ayrı-ayrı olsaydılar bir giriş cəhdi üç
    ardıcıl tranzaksiya açardı»), lakin sərhədi işarələyən bir şey yox idi.

    Sərhəd BURADADIR, körpüdə deyil: yalnız kontroller «cəhd nə vaxt başlayıb
    nə vaxt bitir» sualının cavabını bilir.
    """

    def attempt(self) -> AbstractContextManager[None]: ...


class EmployeeLookup(Protocol):
    """İstifadəçi adına görə işçi tapan mənbə.

    `EmployeeRepository` portunun YALNIZ bu hissəsi lazımdır — tam portu
    tələb etmək kontrolleri testdə qurmağı ağırlaşdırardı.
    """

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None: ...


class AuthOutcome:
    """Girişin nəticəsi — ekranın anladığı formada.

    `LoginResult`-dan fərqi: burada Qt tərəfin lazım olduğu hər şey var və
    domen istisnası YOXDUR — ekran `try/except` yazmır.
    """

    __slots__ = ("employee", "message", "must_change_password", "succeeded")

    def __init__(
        self,
        *,
        succeeded: bool,
        employee: object | None = None,
        message: str = "",
        must_change_password: bool = False,
    ) -> None:
        self.succeeded = succeeded
        self.employee = employee
        self.message = message
        #: `True` → giriş doğrudur, lakin şifrə DƏYİŞDİRİLMƏLİDİR (bölmə 2).
        self.must_change_password = must_change_password


class AuthController:
    """`AdminLoginScreen` üçün giriş körpüsü."""

    def __init__(
        self,
        *,
        login_use_case: AdminLoginUseCase,
        credentials: CredentialSource,
        employees: EmployeeLookup,
        tenant_id: TenantId,
        scope: AttemptScope | None = None,
    ) -> None:
        self._login = login_use_case
        self._credentials = credentials
        self._employees = employees
        self._tenant_id = tenant_id
        #: İSTƏYƏ BAĞLI: verilməzsə hər oxu öz sessiyasını açır — testlərdəki
        #: yaddaş sahtələri üçün doğru davranış budur (bax `AttemptScope`).
        self._scope = scope

    def authenticate(self, username: Username, password: str) -> AuthOutcome:
        """Giriş cəhdi — heç vaxt istisna atmır.

        Ekran nəticəni birbaşa göstərə bilsin deyə hər hal `AuthOutcome`-a
        çevrilir; gözlənilməz istisna da tutulur, çünki giriş ekranında
        çökmək istifadəçini tamamilə bloklayardı.

        Bütün gövdə BİR `attempt()` sərhədindədir (PERF-2): üç oxu eyni
        tranzaksiyanı paylaşır. Sərhəd `finally` ilə deyil, kontekst meneceri
        ilə qurulur — istisna halında da bağlanmalıdır.
        """
        with self._scope.attempt() if self._scope is not None else nullcontext():
            return self._authenticate(username, password)

    def _authenticate(self, username: Username, password: str) -> AuthOutcome:
        stored_hash, pepper_version = self._lookup_secret(username)

        try:
            result: LoginResult = self._login.login(
                tenant_id=self._tenant_id,
                username=username,
                password=password,
                stored_hash=stored_hash,
                pepper_version=pepper_version,
            )
        except AccountLockedError as exc:
            # Bloklanma AÇIQ deyilir — istifadəçi nə qədər gözləyəcəyini
            # bilməlidir (bax modul başlığı).
            return AuthOutcome(succeeded=False, message=exc.user_message)
        except AuthenticationError:
            return AuthOutcome(succeeded=False, message=GENERIC_FAILURE_MESSAGE)
        except Exception:
            _security_log.exception("LOGIN_UNEXPECTED_ERROR")
            return AuthOutcome(
                succeeded=False,
                message="Giriş yoxlanıla bilmədi. Yenidən cəhd edin.",
            )

        return AuthOutcome(
            succeeded=True,
            employee=result.employee,
            must_change_password=result.stage is LoginStage.MUST_CHANGE_PASSWORD,
        )

    def _lookup_secret(self, username: Username) -> tuple[str | None, int]:
        """Şifrə hash-ını tapır.

        Hesab yoxdursa `(None, 1)` qaytarılır — use case həmin halda da
        Argon2 hesablamasını aparır, yəni cavab müddəti hesabın mövcudluğunu
        AÇIQLAMIR.
        """
        employee = self._employees.get_by_username(self._tenant_id, username)
        if employee is None:
            return None, 1

        credentials = self._credentials.credentials_for(employee.id)
        if credentials is None:
            return None, 1
        return credentials.password_hash, credentials.pepper_version


__all__ = [
    "GENERIC_FAILURE_MESSAGE",
    "AttemptScope",
    "AuthController",
    "AuthOutcome",
    "CredentialSource",
    "EmployeeLookup",
]
