"""Quraşdırma kimliyi — `tenant_id` mühitdən, yerli fayldan və ya YENİ yaradılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`build_context()` əvvəllər `KOMPASOS_TENANT_ID` boş olduqda FATAL xəta atırdı və
istifadəçi «Quraşdırma tamamlanmayıb» dalan ekranını görürdü. Halbuki sıfırdan
quraşdırmada həmin dəyişən TƏRİFƏ GÖRƏ boşdur — onu doldurmalı olan sihirbaz
isə məhz həmin xəta ucbatından heç vaxt açılmırdı. Yəni "ilk açılış" halı
"nasazlıq" kimi işlənirdi.

Boş baza FƏLAKƏT DEYİL, GÖZLƏNİLƏN vəziyyətdir. Bloklayıcı xəta yalnız iki
halda qalır: baza ÜMUMİYYƏTLƏ əlçatan deyil, və lisenziya deaktivdir.

──────────────────────────────────────────────────────────────────────────────
ÜÇ MƏNBƏ, DƏYİŞMƏZ SIRA
──────────────────────────────────────────────────────────────────────────────
1. **Mühit dəyişəni** — lisenziyalı quraşdırma. Təchizatçının verdiyi
   identifikator hər şeydən üstündür, çünki `license_tenants` sətri məhz
   ona bağlıdır.
2. **Yerli fayl** — əvvəlki açılışda yaradılmış identifikator. Onsuz hər
   açılış YENİ tenant yaradardı və dünənki məlumat "başqasının"a çevrilərdi.
3. **Yeni UUID** — bu maşında ilk açılış. Yaradılır, DƏRHAL yazılır və
   sihirbaza ötürülür.

──────────────────────────────────────────────────────────────────────────────
YAZI UĞURSUZ OLARSA NƏ OLUR — İKİ FƏRQLİ CAVAB
──────────────────────────────────────────────────────────────────────────────
YENİ identifikator yazıla bilmirsə əməliyyat DAYANIR: davam etsəydik, növbəti
açılışda yenə yeni UUID yaranardı və istifadəçinin bu gün yazdığı hər şey
görünməz "keçmiş tenant"da qalardı. Sükutla məlumat itirmək yerinə açıq xəta
vermək yeganə düzgün davranışdır.

MÜHİTDƏN gələn identifikator üçün isə yazı yalnız QEYDDİR (hansı lisenziya
qoşulub) — diskə yazıla bilməməsi işə mane olmur, çünki dəyər onsuz da hər
açılışda mühitdən gəlir. Ona görə orada yalnız xəbərdarlıq yazılır.

──────────────────────────────────────────────────────────────────────────────
LİSENZİYA SONRADAN QOŞULANDA
──────────────────────────────────────────────────────────────────────────────
Əvvəl yerli identifikatorla işləyən quraşdırmaya sonradan
`KOMPASOS_TENANT_ID` verilirsə, mühit dəyəri QALİB GƏLİR, lakin köhnə
identifikator faylda SAXLANILIR və çağıran tərəfə qaytarılır. Səbəb:
köhnə identifikatorla yazılmış sətirlər avtomatik KÖÇMÜR — onları köçürmək
bütün cədvəllərdə `tenant_id` dəyişdirmək deməkdir və bu, sükutla ediləcək
əməliyyat deyil. Fərq görünən yerdə (jurnal + xəbərdarlıq) qalır ki, məlumatın
"itdiyi" heç kimə sürpriz olmasın.

Modul QƏSDƏN yalnız standart kitabxanaya söykənir — `shared` ən aşağı qatdır
(bax `data_paths.py` başlığı).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from src.shared.data_paths import resolve_data_file
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

_log = get_logger(__name__)

#: Faylın adı və onu əvəz edən mühit dəyişəni (paketlənmiş quraşdırmalar üçün).
INSTALLATION_FILE: Final[str] = "installation.json"
INSTALLATION_PATH_ENV: Final[str] = "KOMPASOS_INSTALLATION_PATH"
TENANT_ID_ENV: Final[str] = "KOMPASOS_TENANT_ID"


class IdentitySource(str, Enum):
    """Identifikatorun HARADAN gəldiyi — jurnal və sihirbaz qərarı üçün."""

    ENVIRONMENT = "ENVIRONMENT"
    LOCAL = "LOCAL"
    GENERATED = "GENERATED"


class InstallationIdentityError(KompasOSError):
    """Kimlik oxuna/yazıla bilmədi — davam etmək məlumat itkisi riskidir."""


@dataclass(frozen=True)
class InstallationIdentity:
    """Bu quraşdırmanın kimliyi.

    Attributes:
        tenant_id: İşlənəcək identifikator.
        source: Mənbə (bax `IdentitySource`).
        superseded_local_id: Mühit dəyəri yerli dəyəri əvəz etdisə, KÖHNƏ
            identifikator. `None` — belə bir hal yoxdur.
    """

    tenant_id: uuid.UUID
    source: IdentitySource
    superseded_local_id: uuid.UUID | None = None

    @property
    def is_licensed(self) -> bool:
        """Identifikator təchizatçıdan gəlirmi (lisenziya qeydi mövcuddur)."""
        return self.source is IdentitySource.ENVIRONMENT


def installation_file() -> Path:
    """Kimlik faylının yolu — CWD-dən ASILI DEYİL (bax `data_paths.py`)."""
    return resolve_data_file(INSTALLATION_PATH_ENV, INSTALLATION_FILE)


def resolve_installation_identity(
    *,
    env_key: str = TENANT_ID_ENV,
    path: Path | None = None,
    allow_generate: bool = True,
) -> InstallationIdentity:
    """Mühit → yerli fayl → yeni UUID sırası ilə kimliyi həll edir.

    Args:
        allow_generate: `False` → kimlik tapılmasa YENİSİ YARADILMIR, açıq
            xəta atılır. BAŞSIZ yollar (planlaşdırılmış işlər) bunu işlədir:
            həmin proses Task Scheduler altında BAŞQA istifadəçi hesabı ilə
            işləyə bilər və onun `%LOCALAPPDATA%`-sı fərqlidir — orada
            avtomatik yaradılan kimlik "ikinci, boş tenant" demək olardı və
            gecəlik işlər səssizcə heç nə etməzdi.

    Raises:
        InstallationIdentityError: Mühitdəki dəyər UUID deyil, YENİ
            identifikator diskə yazıla bilmədi, və ya `allow_generate=False`
            ikən heç bir kimlik tapılmadı.
    """
    store = path if path is not None else installation_file()
    stored = _read(store)

    raw_env = os.environ.get(env_key, "").strip()
    if raw_env:
        licensed = _parse(raw_env, source="mühit dəyişəni")
        previous = stored.get("tenant_id")
        superseded = previous if previous is not None and previous != licensed else None
        _remember(
            store,
            tenant_id=licensed,
            generated=stored.get("generated_tenant_id") or superseded,
            fatal=False,
        )
        if superseded is not None:
            _log.warning(
                "INSTALLATION_ID_SUPERSEDED_BY_LICENSE",
                extra={"previous": str(superseded), "current": str(licensed)},
            )
        return InstallationIdentity(
            tenant_id=licensed,
            source=IdentitySource.ENVIRONMENT,
            superseded_local_id=superseded,
        )

    local = stored.get("tenant_id")
    if local is not None:
        return InstallationIdentity(tenant_id=local, source=IdentitySource.LOCAL)

    if not allow_generate:
        raise InstallationIdentityError(
            "Quraşdırma kimliyi tapılmadı və yaradılması icazəli deyil",
            user_message=(
                "Quraşdırma kimliyi tapılmadı. Başsız icra üçün "
                f"`{env_key}` mühit dəyişəni təyin edilməlidir "
                "(bax `docs/scheduler_setup.md`)."
            ),
            context={"env_key": env_key, "path": str(store)},
        )

    created = uuid.uuid4()
    _remember(store, tenant_id=created, generated=created, fatal=True)
    _log.info("INSTALLATION_ID_GENERATED", extra={"tenant_id": str(created), "path": str(store)})
    return InstallationIdentity(tenant_id=created, source=IdentitySource.GENERATED)


# --------------------------------------------------------------------------- #
# Fayl əməliyyatları
# --------------------------------------------------------------------------- #


def _read(path: Path) -> dict[str, uuid.UUID | None]:
    """Faylı oxuyur; yoxdursa/korlanıbsa BOŞ nəticə.

    KORLANMIŞ FAYL XƏTA ATMIR: JSON qırılıbsa (disk dolub, proses yarıda
    öldürülüb) ən pis nəticə yeni identifikatorun yaranmasıdır — halbuki
    istisna atsaydıq tətbiq ÜMUMİYYƏTLƏ açılmazdı və istifadəçinin əlində
    heç bir düzəltmə yolu qalmazdı. Hər iki hal jurnala düşür.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _log.warning("INSTALLATION_FILE_UNREADABLE", extra={"path": str(path), "error": str(exc)})
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _log.warning("INSTALLATION_FILE_CORRUPT", extra={"path": str(path)})
        return {}
    if not isinstance(payload, dict):
        _log.warning("INSTALLATION_FILE_CORRUPT", extra={"path": str(path)})
        return {}

    return {
        "tenant_id": _maybe_uuid(payload.get("tenant_id")),
        "generated_tenant_id": _maybe_uuid(payload.get("generated_tenant_id")),
    }


def _remember(
    path: Path,
    *,
    tenant_id: uuid.UUID,
    generated: uuid.UUID | None,
    fatal: bool,
) -> None:
    """Kimliyi ATOMİK yazır (müvəqqəti fayl + `os.replace`).

    Birbaşa yazsaydıq, yazı ortasında kəsilən proses YARIMÇIQ JSON qoyardı və
    növbəti açılış onu "korlanmış" sayıb YENİ identifikator yaradardı — yəni
    məhz qorunmaq istədiyimiz hal baş verərdi.
    """
    payload: dict[str, str] = {"tenant_id": str(tenant_id)}
    if generated is not None:
        payload["generated_tenant_id"] = str(generated)

    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        if not fatal:
            _log.warning(
                "INSTALLATION_FILE_NOT_WRITTEN", extra={"path": str(path), "error": str(exc)}
            )
            return
        raise InstallationIdentityError(
            "Quraşdırma kimliyi yazıla bilmədi",
            user_message=(
                "Quraşdırma kimliyi yadda saxlanıla bilmədi: "
                f"«{path}». Qovluğa yazma icazəsini yoxlayın — kimlik "
                "saxlanılmasa hər açılışda yeni quraşdırma yaranar."
            ),
            context={"path": str(path), "error": str(exc)},
        ) from exc


def _parse(raw: str, *, source: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise InstallationIdentityError(
            f"Tenant identifikatoru düzgün UUID deyil ({source})",
            user_message=(
                "Quraşdırma faylındakı tenant identifikatoru yararsızdır. "
                "Dəyəri düzəldin və ya boş buraxın — boş dəyər ilk quraşdırma "
                "sihirbazını açır."
            ),
            context={"value": raw},
        ) from exc


def _maybe_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None


__all__ = [
    "INSTALLATION_FILE",
    "INSTALLATION_PATH_ENV",
    "TENANT_ID_ENV",
    "IdentitySource",
    "InstallationIdentity",
    "InstallationIdentityError",
    "installation_file",
    "resolve_installation_identity",
]
