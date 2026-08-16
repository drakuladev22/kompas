"""Quraşdırma kimliyi — boş mühit dəyişəni XƏTA DEYİL, ilk açılışdır.

Qüsurun forması bu testlərin nə ölçdüyünü izah edir: `KOMPASOS_TENANT_ID` boş
olduqda tətbiq «Quraşdırma tamamlanmayıb» dalanına düşürdü və İlk Quraşdırma
Sihirbazı — onu doldurmalı olan yeganə ekran — heç vaxt açılmırdı.

ƏN VACİB TEST `test_second_launch_reuses_the_generated_identity`-dir: kimlik
sabit qalmasa, hər açılış yeni tenant yaradar və dünənki məlumat görünməz
"keçmiş quraşdırma"da qalardı — yəni düzəliş ilkin qüsurdan da pis olardı.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from src.shared.installation import (
    IdentitySource,
    InstallationIdentityError,
    resolve_installation_identity,
)

pytestmark = pytest.mark.unit

_ENV = "KOMPASOS_TENANT_ID"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mühitdəki real dəyər testə sızmamalıdır."""
    monkeypatch.delenv(_ENV, raising=False)


def _store(tmp_path: Path) -> Path:
    return tmp_path / "installation.json"


# --------------------------------------------------------------------------- #
# Boş mühit — ilk açılış
# --------------------------------------------------------------------------- #


def test_empty_environment_generates_an_identity(tmp_path: Path) -> None:
    """Dəyişən boşdursa kimlik YARADILIR — istisna atılmır."""
    identity = resolve_installation_identity(env_key=_ENV, path=_store(tmp_path))

    assert identity.source is IdentitySource.GENERATED
    assert not identity.is_licensed
    assert _store(tmp_path).is_file()


def test_second_launch_reuses_the_generated_identity(tmp_path: Path) -> None:
    """İkinci açılış EYNİ identifikatoru oxuyur — yenisini YARATMIR."""
    first = resolve_installation_identity(env_key=_ENV, path=_store(tmp_path))
    second = resolve_installation_identity(env_key=_ENV, path=_store(tmp_path))

    assert second.tenant_id == first.tenant_id
    assert second.source is IdentitySource.LOCAL


def test_generated_identity_is_written_atomically(tmp_path: Path) -> None:
    """Yazıdan sonra müvəqqəti fayl QALMIR."""
    resolve_installation_identity(env_key=_ENV, path=_store(tmp_path))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith("installation")]
    assert leftovers == ["installation.json"], "yarımçıq `.tmp` faylı qalıb"


def test_unwritable_store_stops_startup(tmp_path: Path) -> None:
    """Kimlik yazıla bilmirsə DAYANIRIQ — səssiz davam məlumat itkisidir.

    Davam etsəydik, hər açılışda yeni identifikator yaranar və istifadəçinin
    bugünkü işi sabah "başqa tenant"ın malı olardı.
    """
    blocker = tmp_path / "blocked"
    blocker.write_text("fayl, qovluq deyil", encoding="utf-8")

    with pytest.raises(InstallationIdentityError):
        resolve_installation_identity(env_key=_ENV, path=blocker / "installation.json")


# --------------------------------------------------------------------------- #
# Mühit dəyişəni — lisenziyalı quraşdırma
# --------------------------------------------------------------------------- #


def test_environment_value_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    licensed = uuid.uuid4()
    monkeypatch.setenv(_ENV, str(licensed))

    identity = resolve_installation_identity(env_key=_ENV, path=_store(tmp_path))

    assert identity.tenant_id == licensed
    assert identity.source is IdentitySource.ENVIRONMENT
    assert identity.is_licensed


def test_license_supersedes_a_local_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonradan qoşulan lisenziya qalib gəlir, KÖHNƏ kimlik isə itmir.

    Köhnə identifikatorla yazılmış sətirlər avtomatik KÖÇMÜR (bu, bütün
    cədvəllərdə `tenant_id` dəyişdirmək olardı) — ona görə fərq görünən yerdə
    qalmalıdır, sükutla udulmamalıdır.
    """
    local = resolve_installation_identity(env_key=_ENV, path=_store(tmp_path)).tenant_id
    licensed = uuid.uuid4()
    monkeypatch.setenv(_ENV, str(licensed))

    identity = resolve_installation_identity(env_key=_ENV, path=_store(tmp_path))

    assert identity.tenant_id == licensed
    assert identity.superseded_local_id == local
    stored = json.loads(_store(tmp_path).read_text(encoding="utf-8"))
    assert stored["generated_tenant_id"] == str(local)


def test_headless_path_refuses_to_invent_an_identity(tmp_path: Path) -> None:
    """Planlaşdırılmış işlər kimlik YARATMIR — açıq xəta verir.

    Həmin proses Task Scheduler altında başqa istifadəçi hesabı ilə işləyir və
    onun `%LOCALAPPDATA%`-sı fərqlidir. Kimlik orada yaradılsaydı, gecəlik
    işlər boş bir tenant üzərində "uğurla" işləyər və heç nə etməzdi.
    """
    with pytest.raises(InstallationIdentityError):
        resolve_installation_identity(env_key=_ENV, path=_store(tmp_path), allow_generate=False)

    assert not _store(tmp_path).exists()


def test_invalid_environment_value_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Açıq şəkildə YANLIŞ dəyər boş dəyərlə eyni sayılmır.

    Boş = "hələ quraşdırılmayıb"; yararsız = "kimsə səhv yazıb". İkincisini
    sükutla yeni kimliyə çevirsəydik, bir hərf səhvi bütün mövcud məlumatı
    görünməz edərdi.
    """
    monkeypatch.setenv(_ENV, "bu-uuid-deyil")

    with pytest.raises(InstallationIdentityError):
        resolve_installation_identity(env_key=_ENV)


# --------------------------------------------------------------------------- #
# Korlanmış fayl
# --------------------------------------------------------------------------- #


def test_corrupt_file_does_not_block_startup(tmp_path: Path) -> None:
    """Yarımçıq JSON tətbiqi açılmaz etmir — yeni kimlik yaradılır.

    İstisna atsaydıq, istifadəçinin əlində heç bir düzəltmə yolu qalmazdı:
    ekran açılmır, fayl isə `%LOCALAPPDATA%` altındadır.
    """
    store = _store(tmp_path)
    store.write_text('{"tenant_id": "yarım', encoding="utf-8")

    identity = resolve_installation_identity(env_key=_ENV, path=store)

    assert identity.source is IdentitySource.GENERATED
    assert json.loads(store.read_text(encoding="utf-8"))["tenant_id"] == str(identity.tenant_id)


def test_unreadable_uuid_in_file_is_replaced(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_text(json.dumps({"tenant_id": "12345"}), encoding="utf-8")

    identity = resolve_installation_identity(env_key=_ENV, path=store)

    assert identity.source is IdentitySource.GENERATED


# --------------------------------------------------------------------------- #
# `build_context` — ƏSAS REQRESSİYA
# --------------------------------------------------------------------------- #


class _Database:
    """`TenantDatabase`-in yalnız `open()`-i işlənir — bağlantı qurulmur."""

    def open(self) -> None:
        return None


def test_build_context_no_longer_fails_without_a_tenant_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`KOMPASOS_TENANT_ID` boş olsa da kontekst QURULUR.

    Bu, istifadəçinin bildirdiyi qüsurun ÖZÜDÜR: əvvəl burada `StartupError`
    atılırdı, `main.py` onu «Quraşdırma tamamlanmayıb» fatal ekranına
    çevirirdi və sihirbaz heç vaxt açılmırdı.

    `self_hosted` bayrağı da yoxlanılır: identifikator bu maşında yarandığı
    üçün sihirbaz `license_tenants` sətrini özü qurmalıdır.
    """
    from src.infrastructure.persistence import connection_types
    from src.presentation.composition import build_context

    monkeypatch.setenv("KOMPASOS_INSTALLATION_PATH", str(_store(tmp_path)))
    # SEAM `connection_types`-dədir, `connection` DEYİL: `build_context`
    # bağlantını `TenantDatabase` kimi qurur (DB-4 Faza 1 tip ayırıcısı).
    monkeypatch.setattr(connection_types, "TenantDatabase", _Database)

    context = build_context()

    assert context.self_hosted is True
    assert _store(tmp_path).is_file()


def test_build_context_marks_a_licensed_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mühitdən gələn identifikator = lisenziyalı quraşdırma."""
    from src.infrastructure.persistence import connection_types
    from src.presentation.composition import build_context

    licensed = uuid.uuid4()
    monkeypatch.setenv(_ENV, str(licensed))
    monkeypatch.setenv("KOMPASOS_INSTALLATION_PATH", str(_store(tmp_path)))
    # SEAM `connection_types`-dədir, `connection` DEYİL: `build_context`
    # bağlantını `TenantDatabase` kimi qurur (DB-4 Faza 1 tip ayırıcısı).
    monkeypatch.setattr(connection_types, "TenantDatabase", _Database)

    context = build_context()

    assert context.self_hosted is False
    assert str(context.tenant_id) == str(licensed)
