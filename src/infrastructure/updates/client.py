"""Avtomatik yenilənmə klienti: yoxla → yüklə → doğrula → tətbiq et — Faza 3.13.

Spesifikasiya bölmə 7: *"Təhlükəsizlik yamaqları müştərinin heç bir əl əməyi
olmadan arxa planda tətbiq olunur."*

──────────────────────────────────────────────────────────────────────────────
DÖRD ADDIM, HƏR BİRİ AYRICA DAYANA BİLƏR
──────────────────────────────────────────────────────────────────────────────
    check()    kataloqu oxu → `UpdateDecision`   (şəbəkə lazımdır)
    prepare()  yüklə + SHA-256 + Authenticode    (fail-closed)
    apply()    quraşdırıcını işə sal             (proqram bağlanır)
    rollback() əvvəlki paketi geri qur           (şəbəkə LAZIM DEYİL)

Addımların ayrı olması vacibdir: `prepare()` gecə, `apply()` isə mağaza
bağlananda icra oluna bilər. Yenilənməni iş günü ortasında tətbiq etmək
(proqramın bağlanması + quraşdırma) kassanı bir neçə dəqiqə dayandırardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ "MƏCBURİ" YENİLƏNMƏ DƏ DEFOLT OLARAQ TƏTBİQİ BLOKLAMIR
──────────────────────────────────────────────────────────────────────────────
"Məcburi" burada *"növbəti uyğun anda mütləq tətbiq olunacaq"* deməkdir, *"o
vaxta qədər işləmə"* deyil. Versiya nömrəsinə görə 21 filialı dayandırmaq
lisenziya qatındakı əsas prinsiplə (bax `licensing.py`) ziddiyyət təşkil
edərdi. UI bağlanmayan bir xəbərdarlıq göstərir, tətbiq isə növbəti
başlanğıcda baş verir.

İSTİSNA (`restrict_features_when_mandatory=True`): elə yamaqlar var ki, köhnə
versiyanın İŞLƏMƏSİ özü risqdir (məs. cərimə hesablamasını pozan qüsur — hər
saat yanlış maliyyə qeydi yaranır). Belə hallar üçün məhdudlaşdırma AÇILA
bilir, lakin bu, defolt DEYİL və hər dəfə şüurlu qərar tələb edir. Bayraq
`should_restrict_features` vasitəsilə UI-a verilir — bu modul heç nə bağlamır,
yalnız "bağlanmalıdır" siqnalını verir (qərar UI qatındadır, bax bölmə 3).

──────────────────────────────────────────────────────────────────────────────
GERİ QAYTARMA ŞƏBƏKƏSİZ İŞLƏMƏLİDİR
──────────────────────────────────────────────────────────────────────────────
Geri qaytarma məhz yenilənmə nəyisə SINDIRDIQDA lazım olur — və sındırılan
şey şəbəkə/DB bağlantısının özü ola bilər. Ona görə əvvəlki quraşdırıcı
YERLİ olaraq saxlanılır (`previous/`) və `rollback()` heç bir sorğu etmir.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.updates import (
    ReleaseChannel,
    UpdateAction,
    UpdateDecision,
    UpdateError,
    UpdateUnavailableError,
    Version,
    decide,
)
from src.infrastructure.config.limits import InfrastructureLimits
from src.infrastructure.updates.verification import verify_package
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from src.domain.value_objects.identifiers import TenantId
    from src.domain.value_objects.updates import ReleaseInfo
    from src.infrastructure.updates.catalog import SupabaseReleaseCatalog
    from src.infrastructure.updates.verification import AuthenticodeVerifier

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

STAGING_DIR_NAME: Final[str] = "updates"
PREVIOUS_DIR_NAME: Final[str] = "previous"
#: Səssiz quraşdırma arqumentləri (Inno Setup / NSIS uyğun).
SILENT_ARGS: Final[tuple[str, ...]] = ("/SILENT", "/NORESTART")


@dataclass(frozen=True)
class PreparedUpdate:
    """Doğrulanmış, tətbiqə hazır paket.

    `expected_sha256` KATALOQDAN gəlir və burada SAXLANILIR — `apply()`
    zamanı təkrar yoxlama üçün. Hash-ı o an fayldan yenidən hesablamaq
    yoxlamanı mənasız edərdi: dəyişdirilmiş fayl öz yeni hash-ı ilə
    müqayisə olunub həmişə "uyğun" çıxardı.
    """

    version: Version
    package_path: Path
    publisher_subject: str
    is_mandatory: bool
    expected_sha256: str


class AutoUpdateClient:
    """Arxa fon yoxlaması + hazırlıq + tətbiq + geri qaytarma."""

    def __init__(
        self,
        tenant_id: TenantId,
        catalog: SupabaseReleaseCatalog,
        verifier: AuthenticodeVerifier,
        *,
        current_version: str,
        staging_root: Path,
        channel: ReleaseChannel = ReleaseChannel.STABLE,
        limits: InfrastructureLimits | None = None,
        interval_seconds: float | None = None,
        retry_interval_seconds: float | None = None,
        launcher: Callable[[Sequence[str]], None] | None = None,
        restrict_features_when_mandatory: bool = False,
    ) -> None:
        self._tenant_id = tenant_id
        self._catalog = catalog
        self._verifier = verifier
        self._current = Version.parse(current_version)
        self._staging = staging_root / STAGING_DIR_NAME
        self._previous = staging_root / PREVIOUS_DIR_NAME
        self._channel = channel
        # RİTM BİR DƏFƏ OXUNUR: arxa fon sapının gözləmə cədvəlidir və sap
        # yenidən başlayana qədər onsuz da dəyişə bilməz. Açıq arqument ROOT
        # dəyərindən ÜSTÜNDÜR (`LicenseClient._seconds` ilə eyni qayda),
        # `limits=None` isə `DEFAULT_LIMITS` fallback-ını verir — yəni
        # köçürmə davranışı DƏYİŞMİR.
        window = limits or InfrastructureLimits()
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else window.float_of(SystemLimitKey.UPDATE_CHECK_INTERVAL_SECONDS)
        )
        self._retry_interval = (
            retry_interval_seconds
            if retry_interval_seconds is not None
            else window.float_of(SystemLimitKey.UPDATE_RETRY_INTERVAL_SECONDS)
        )
        self._launcher = launcher
        self._restrict_when_mandatory = restrict_features_when_mandatory

        self._lock = threading.Lock()
        self._prepared: PreparedUpdate | None = None
        self._last_decision: UpdateDecision | None = None
        self._last_error: str = ""

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # -------------------------------- vəziyyət -------------------------------- #

    @property
    def current_version(self) -> Version:
        return self._current

    @property
    def prepared(self) -> PreparedUpdate | None:
        """Tətbiqə hazır paket (varsa) — UI "Yenilə və yenidən başlat" göstərir."""
        with self._lock:
            return self._prepared

    @property
    def should_restrict_features(self) -> bool:
        """UI əsas funksiyaları məhdudlaşdırmalıdırmı (bax modul başlığı).

        Yalnız `restrict_features_when_mandatory=True` olduqda `True` ola bilər
        VƏ yalnız məcburi buraxılış aşkarlandıqda. Yenilənmə tətbiq olunan kimi
        (proqram yeni versiyada açılır) `check()` `UP_TO_DATE` verir və
        məhdudiyyət öz-özünə götürülür — ayrıca "sıfırlama" addımı YOXDUR,
        çünki unudulmuş sıfırlama filialı sonsuza qədər bağlı saxlayardı.
        """
        if not self._restrict_when_mandatory:
            return False
        with self._lock:
            decision = self._last_decision
        return bool(decision and decision.is_mandatory)

    @property
    def status(self) -> dict[str, object]:
        """System Health Monitor sətri (bölmə 6)."""
        with self._lock:
            decision = self._last_decision
            prepared = self._prepared
            error = self._last_error
        return {
            "current_version": str(self._current),
            "channel": self._channel.value,
            "action": decision.action.value if decision else None,
            "available_version": str(decision.release.version)
            if decision and decision.release
            else None,
            "prepared_version": str(prepared.version) if prepared else None,
            "is_mandatory": bool(decision and decision.is_mandatory),
            "restricted": self.should_restrict_features,
            "rollback_available": self.rollback_package() is not None,
            "last_error": error,
        }

    # --------------------------------- yoxla ---------------------------------- #

    def check(self) -> UpdateDecision:
        """Kataloqu oxuyur və qərar verir. Uğursuzluqda `UP_TO_DATE`.

        Şəbəkə/DB xətası "yeni versiya yoxdur" kimi işlənir — çünki nəticə
        eynidir: bu dövrdə heç nə tətbiq edilmir. Xəta ATILMIR, çünki bunu
        çağıran arxa fon sapı və ya UI düyməsidir.
        """
        try:
            latest = self._catalog.latest(self._tenant_id, channel=self._channel)
            forced = self._catalog.forced_version(self._tenant_id)
        except UpdateUnavailableError as exc:
            self._remember_error(str(exc))
            return UpdateDecision(UpdateAction.UP_TO_DATE, reason_az="Kataloq oxuna bilmədi.")

        decision = decide(current=self._current, latest=latest, forced_version=forced)
        with self._lock:
            self._last_decision = decision
            self._last_error = ""

        if decision.action is UpdateAction.REFUSED_DOWNGRADE:
            # Bu, sadə "yeni versiya yoxdur" deyil — kataloqda gözlənilməz
            # vəziyyət var və bu, hücum əlaməti ola bilər.
            _security_log.warning(
                "UPDATE_DOWNGRADE_REFUSED",
                extra={
                    "current": str(self._current),
                    "catalog": str(decision.release.version) if decision.release else None,
                },
            )
        return decision

    # -------------------------------- hazırla --------------------------------- #

    def prepare(self, decision: UpdateDecision) -> PreparedUpdate | None:
        """Paketi yükləyir və DOĞRULAYIR. Uğursuzluqda `None`.

        Doğrulama uğursuz olarsa fayl SİLİNİR — yarımçıq və ya saxta paket
        diskdə qalıb sonra təsadüfən işə salınmamalıdır.
        """
        if not decision.should_download or decision.release is None:
            return None

        release = decision.release
        target = self._staging / _package_name(release)
        try:
            self._staging.mkdir(parents=True, exist_ok=True)
            self._catalog.download(release, target)
            subject = verify_package(
                target, expected_sha256=release.digest, verifier=self._verifier
            )
        except UpdateError as exc:
            target.unlink(missing_ok=True)
            self._remember_error(str(exc))
            return None

        prepared = PreparedUpdate(
            version=release.version,
            package_path=target,
            publisher_subject=subject,
            is_mandatory=decision.is_mandatory,
            expected_sha256=release.digest,
        )
        with self._lock:
            self._prepared = prepared
        _log.info(
            "UPDATE_PREPARED",
            extra={"version": str(release.version), "mandatory": decision.is_mandatory},
        )
        return prepared

    # -------------------------------- tətbiq ---------------------------------- #

    def apply(self, prepared: PreparedUpdate | None = None) -> bool:
        """Quraşdırıcını səssiz rejimdə işə salır.

        TƏKRAR DOĞRULAMA APARILIR: paket hazırlandıqdan sonra tətbiq edilənə
        qədər saatlar keçə bilər və bu müddətdə fayl diskdə dəyişdirilə
        bilərdi (məs. zərərli proses tərəfindən). Yoxlama ucuzdur, buraxmaq
        isə bütün imza zəncirini mənasız edərdi.
        """
        target = prepared or self.prepared
        if target is None:
            return False
        if not target.package_path.exists():
            self._remember_error("Hazırlanmış paket tapılmadı.")
            return False

        try:
            verify_package(
                target.package_path,
                expected_sha256=target.expected_sha256,
                verifier=self._verifier,
            )
        except UpdateError as exc:
            target.package_path.unlink(missing_ok=True)
            self._remember_error(str(exc))
            with self._lock:
                self._prepared = None
            return False

        self._keep_for_rollback(target.package_path)
        command = [str(target.package_path), *SILENT_ARGS]
        try:
            launcher = self._launcher or self._default_launcher
            launcher(command)
        except OSError as exc:
            self._remember_error(f"Quraşdırıcı işə salınmadı: {exc}")
            return False

        _security_log.info(
            "UPDATE_APPLIED",
            extra={
                "from_version": str(self._current),
                "to_version": str(target.version),
                "publisher": target.publisher_subject,
            },
        )
        return True

    def rollback(self) -> bool:
        """Əvvəlki versiyanın quraşdırıcısını yenidən icra edir.

        Şəbəkə/DB TƏLƏB ETMİR (bax modul başlığı). İmza yenə yoxlanılır —
        `previous/` qovluğu istifadəçi profilindədir və dəyişdirilə bilər.
        """
        package = self.rollback_package()
        if package is None:
            return False

        try:
            self._verifier.verify(package)
        except UpdateError as exc:
            self._remember_error(str(exc))
            return False

        try:
            launcher = self._launcher or self._default_launcher
            launcher([str(package), *SILENT_ARGS])
        except OSError as exc:
            self._remember_error(f"Geri qaytarma işə salınmadı: {exc}")
            return False

        _security_log.warning(
            "UPDATE_ROLLED_BACK",
            extra={"package": package.name, "current_version": str(self._current)},
        )
        return True

    def rollback_package(self) -> Path | None:
        """Saxlanmış əvvəlki quraşdırıcı (varsa)."""
        if not self._previous.is_dir():
            return None
        packages = sorted(self._previous.glob("*.exe"))
        return packages[-1] if packages else None

    def _keep_for_rollback(self, package: Path) -> None:
        """Tətbiq edilən paketi geri-qaytarma nöqtəsi kimi saxlayır.

        YALNIZ BİR nüsxə saxlanılır: iki addım geri qayıtmaq praktikada heç
        vaxt lazım olmur, lakin hər versiya üçün onlarla meqabayt saxlamaq
        mağaza PC-sinin diskini doldurar.
        """
        try:
            self._previous.mkdir(parents=True, exist_ok=True)
            for stale in self._previous.glob("*.exe"):
                stale.unlink(missing_ok=True)
            shutil.copy2(package, self._previous / package.name)
        except OSError as exc:
            # Geri qaytarma nöqtəsinin saxlanmaması yenilənməni DAYANDIRMIR —
            # yeni versiya köhnədən yaxşıdır, sadəcə geri yol bir qədər çətindir.
            _log.warning("UPDATE_ROLLBACK_COPY_FAILED", extra={"error": str(exc)})

    def _default_launcher(self, command: Sequence[str]) -> None:
        # `Popen` — gözləmirik: quraşdırıcı bu prosesi bağlayacaq.
        subprocess.Popen(  # noqa: S603 — yol yalnız doğrulanmış paketdən gəlir
            list(command),
            close_fds=True,
        )

    def _remember_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
        _log.warning("UPDATE_STEP_FAILED", extra={"error": message})

    # ---------------------------- arxa fon sapı ------------------------------- #

    def run_once(self) -> PreparedUpdate | None:
        """Bir dövr: yoxla → (lazımdırsa) hazırla. TƏTBİQ ETMİR."""
        decision = self.check()
        if not decision.should_download:
            return None
        return self.prepare(decision)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="auto-update", daemon=True)
        self._thread.start()
        _log.info("UPDATE_CLIENT_STARTED", extra={"interval_seconds": self._interval})

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        _log.info("UPDATE_CLIENT_STOPPED")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                success = self.run_once() is not None or not self._last_error
            except Exception as exc:  # arxa fon sapı heç vaxt ölməməlidir
                success = False
                _log.error("UPDATE_LOOP_CRASHED", extra={"error": str(exc)})
            self._stop_event.wait(self._interval if success else self._retry_interval)


def _package_name(release: ReleaseInfo) -> str:
    return f"KompasOS-{release.version}.exe"


__all__ = [
    "SILENT_ARGS",
    "AutoUpdateClient",
    "PreparedUpdate",
]
