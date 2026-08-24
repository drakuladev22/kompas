r"""«Vendor Konsolu» ↔ «konkret kirayəçi» vəziyyətləri arasında TƏK komandalı keçid.

──────────────────────────────────────────────────────────────────────────────
BU SKRİPT `.exe`-YƏ PAKETLƏNMİR
──────────────────────────────────────────────────────────────────────────────
`src/KompasOS.spec` yalnız `src/` altını yığır; `scripts/` ora düşmür —
`onboard_new_tenant.py` və `dev_panel.py` ilə EYNİ qayda, EYNİ səbəb. Bu alət
TƏCHİZATÇININ öz maşınında test vəziyyətini dəyişir; müştəri paketində belə bir
imkanın olması işlək quraşdırmanı bir əmrlə «konfiqurasiya edilməyib»
vəziyyətinə salmaq demək olardı.

──────────────────────────────────────────────────────────────────────────────
«CONFIG» TƏK FAYL DEYİL — İKİ FAYLDIR (ARAŞDIRMANIN NƏTİCƏSİ)
──────────────────────────────────────────────────────────────────────────────
Tapşırıq mətni «layihə kökündəki `kompasos.config`»-dən danışır. BELƏ BİR FAYL
KOD BAZASINDA YOXDUR — tətbiqin hansı kirayəçi kimi qalxdığını İKİ ayrı fayl
təyin edir və onlar İKİ AYRI yerdə yaşayır:

    * `installation.json` — `tenant_id`, yəni KİM olduğumuz.
      Yol: `src.shared.installation.installation_file()` →
      `KOMPASOS_INSTALLATION_PATH` → `./data/` → `%LOCALAPPDATA%\KompasOS\data\`
      → `%PROGRAMDATA%\KompasOS\data\`. İlk MÖVCUD fayl qalib gəlir.

    * `connection.json` — DSN + şifrələnmiş parol, yəni HARAYA qoşulduğumuz.
      Yol: `connection_file.find_connection_file()` → `.exe`-nin yanı (mənbədən
      icrada bu, REPOZİTORİYA KÖKÜdür) → `%PROGRAMDATA%\KompasOS\` →
      `%APPDATA%\KompasOS\`. İlk MÖVCUD fayl qalib gəlir.

Tətbiqin «config yoxdur» qərarı MƏHZ ikincisinə baxır (`presentation/app.py`:
`find_connection_file() is not None`), lakin birincisi qalsaydı, vendor
vəziyyətinə keçən maşın yenə də köhnə kirayəçinin kimliyini daşıyardı — ona
görə hər ikisi BİRLİKDƏ arxivlənir və BİRLİKDƏ qaytarılır.

──────────────────────────────────────────────────────────────────────────────
YOLLAR BURADA TƏKRAR HESABLANMIR
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı iki funksiya ÇAĞIRILIR, axtarış sırası bu faylda TƏKRARLANMIR.
Təkrar yazsaydıq, sıra dəyişən gün bu alət sükutla KÖHNƏ yerə baxardı və nəticə
«keçid etdim, amma proqram dəyişmədi» olardı — səbəbi isə heç bir ekranda
görünməzdi. Eyni prinsip `onboard_new_tenant._deploy_dev_config` başlığındadır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ «NÜSXƏ + SİL», NİYƏ «KÖÇÜR»
──────────────────────────────────────────────────────────────────────────────
Arxiv (`configs/<ad>.config`) aktiv fayllar silinməzdən ƏVVƏL yazılır və
aktivləşdirmədən SONRA da yerində qalır. Yəni hər an ƏN AZI bir nüsxə var:
köçürmə (`move`) yarıda kəsilsəydi (proses öldürülür, disk dolur) konfiqurasiya
nə arxivdə, nə də aktiv yerdə olardı — halbuki `connection.json` içindəki parol
BU MAŞINA bağlı şəkildə şifrələnib və başqa nüsxədən bərpa oluna bilməz.

──────────────────────────────────────────────────────────────────────────────
`configs/.aktiv` İZ-FAYLI — NİYƏ LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
Aktiv `installation.json` içində `tenant_id` var, ŞİRKƏT ADI YOXDUR. Ad olmasa
vendor vəziyyətinə keçəndə arxivin hansı adla yazılacağı bilinməzdi və hər
keçid yeni `namelum-…` faylı yaradardı. İz-fayl YALNIZ adı saxlayır —
konfiqurasiya məlumatı DAŞIMIR, yəni itsə də heç nə itmir (ad `tenant_id`-yə
görə arxivdən tapılır, tapılmasa vaxt möhürlü ad verilir).

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ
──────────────────────────────────────────────────────────────────────────────
    .venv/Scripts/python.exe scripts/switch.py          # siyahı + hazırkı vəziyyət
    .venv/Scripts/python.exe scripts/switch.py vendor   # config-i götür (Vendor Konsolu)
    .venv/Scripts/python.exe scripts/switch.py yatas    # həmin kirayəçi kimi test
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
# Skript repozitoriya kökündən KƏNARDAN da çağırıla bilər (`python scripts/…`),
# ona görə kök `sys.path`-a AÇIQ əlavə olunur — `apply_migrations.py:55` ilə
# eyni sətir, eyni səbəb.
sys.path.insert(0, str(_REPO_ROOT))

# Konsol kodlaşdırması ÜÇÜNCÜ dəfə yazılmır, İDXAL edilir: `dev_panel.py`
# `_load_dotenv`-i məhz bu cür götürür və səbəb eynidir — iki nüsxə olsaydı
# biri düzələndə digəri sükutla geridə qalardı.
from scripts.apply_migrations import _ensure_utf8_stdio  # noqa: E402

#: Arxiv qovluğu. Layihə kökündədir və `.gitignore`-dadır: bundle-lar müştərinin
#: host/istifadəçi adını və BU MAŞINA bağlı şifrələnmiş parolunu daşıyır —
#: repozitoriyada yeri yoxdur.
CONFIGS_DIR: Final[Path] = _REPO_ROOT / "configs"

#: Bundle faylının uzantısı (tapşırıq mətnindəki ad saxlanılır).
BUNDLE_SUFFIX: Final[str] = ".config"

#: Aktiv kirayəçinin ADINI saxlayan iz-fayl (bax modul başlığı).
ACTIVE_MARKER: Final[str] = ".aktiv"

#: Bundle formatının versiyası — gələcək dəyişiklikdə köhnə faylı tanımaq üçün
#: (`connection_file.FORMAT_VERSION` ilə eyni niyyət).
BUNDLE_VERSION: Final[int] = 1

#: «Config-siz» vəziyyətin adı. Kirayəçi adı kimi işlədilə bilməz — `slugify`
#: onu qaytarsa, `switch.py vendor` iki mənalı olardı.
VENDOR_KEYWORD: Final[str] = "vendor"

#: Şirkət adını fayl adına çevirərkən Azərbaycan hərflərinin qarşılığı.
#: `unicodedata.normalize` BURADA İŞLƏMİR: `ə` və `ı` latın hərflərinin
#: diakritik variantı DEYİL, ayrıca kod nöqtəsidir — NFKD onları olduğu kimi
#: saxlayır və slug `yata`, `hsn` kimi hərfi düşmüş adlara çevrilərdi.
_TRANSLITERATION: Final[dict[str, str]] = {
    "ə": "e",
    "ı": "i",
    "İ": "i",
    "ö": "o",
    "ü": "u",
    "ç": "c",
    "ş": "s",
    "ğ": "g",
}


class SwitchError(RuntimeError):
    """Keçid təhlükəsiz şəkildə tamamlana bilmədi — aktiv fayllar SİLİNMİR."""


class ActiveState(NamedTuple):
    """Bu maşındakı FAKTİKİ vəziyyət — hər sahə tətbiqin öz həlledicisindən.

    Attributes:
        slug: `configs/.aktiv` iz-faylındakı ad; `None` — iz yoxdur.
        connection: Tapılan `connection.json`; `None` — heç bir yerdə yoxdur.
        installation: Tapılan `installation.json`; `None` — yoxdur.
    """

    slug: str | None
    connection: Path | None
    installation: Path | None

    @property
    def is_vendor(self) -> bool:
        """Vəziyyət «config yoxdur»dursa — TƏTBİQİN öz qərarı ilə.

        ──────────────────────────────────────────────────────────────────────
        MƏNBƏ İZ-FAYL DEYİL, `find_connection_file()`-DIR
        ──────────────────────────────────────────────────────────────────────
        `presentation/app.py` «konfiqurasiya edilibmi» sualına MƏHZ
        `find_connection_file() is not None` ilə cavab verir. Bu xassə həmin
        qərarı TƏKRARLAYIR, ondan KƏNARA çıxmır: `configs/.aktiv` iz-faylı
        yalnız ADI xatırlayır və vəziyyəti TƏYİN ETMİR. İz-fayla baxsaydıq,
        onun itməsi (əl ilə silinib, `configs/` təzələnib) işlək quraşdırmanı
        «naməlum» elan edərdi — halbuki tətbiq həmin anda normal qalxır.

        `installation.json` da vəziyyəti TƏYİN ETMİR: onsuz tətbiq özünə YENİ
        kimlik yaradır (`resolve_installation_identity`-nin üçüncü mənbəyi),
        yəni onun mövcudluğu «bağlantı var» demək deyil. Lakin qalması
        mənasızdır (bax `has_files` və `_print_state`).
        """
        return self.connection is None

    @property
    def has_files(self) -> bool:
        """Arxivlənəsi (və silinəsi) fayl VARMI — `is_vendor`-dan FƏRQLİ sual.

        `is_vendor` «tətbiq nə görür» sualıdır, bu isə «bu alətin işi qalıbmı».
        İkisi AYRILDI, çünki `connection.json` yoxdur, `installation.json` isə
        var olan YARIMÇIQ hal mümkündür: vəziyyət vendor-dur, lakin köhnə
        kirayəçinin kimliyi hələ diskdədir və `switch.py vendor` onu
        arxivləyib təmizləməlidir.
        """
        return self.connection is not None or self.installation is not None


# --------------------------------------------------------------------------- #
# Ad çevirməsi
# --------------------------------------------------------------------------- #


def slugify(name: str) -> str:
    """Şirkət adını fayl adına çevirir: «Yataş Azərbaycan» → `yatas-azerbaycan`.

    Fayl adında YALNIZ ASCII saxlanılır. Səbəb praktikidir: bundle adı əmr
    sətrində yazılır (`switch.py yatas`), Windows terminalında isə `ə`/`ş`
    yazmaq klaviatura düzümündən asılıdır — adın özü keçidin qarşısını
    almamalıdır.
    """
    converted = name
    for source, target in _TRANSLITERATION.items():
        converted = converted.replace(source, target).replace(source.upper(), target)
    return re.sub(r"[^a-z0-9]+", "-", converted.lower()).strip("-")


# --------------------------------------------------------------------------- #
# Arxiv (bundle) əməliyyatları
# --------------------------------------------------------------------------- #


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """JSON-u ATOMİK yazır (müvəqqəti fayl + `os.replace`).

    Naxış `shared/installation._remember`-dən götürülüb və səbəb eynidir: yazı
    ortasında kəsilən proses YARIMÇIQ JSON qoyar, növbəti oxu isə onu
    «korlanmış» sayardı — burada həmin fayl konfiqurasiyanın YEGANƏ nüsxəsi ola
    bilər.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    """JSON obyekti oxuyur; oxunmursa aydın səbəblə DAYANIR."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SwitchError(f"«{path}» oxuna bilmədi: {exc}") from exc
    if not isinstance(payload, dict):
        raise SwitchError(f"«{path}» JSON obyekti deyil — fayl korlanıb.")
    return payload


def _bundle_paths() -> list[Path]:
    """`configs/` altındakı bundle-lar, ada görə sıralı."""
    if not CONFIGS_DIR.is_dir():
        return []
    return sorted(CONFIGS_DIR.glob(f"*{BUNDLE_SUFFIX}"))


def _bundle_path(slug: str) -> Path:
    return CONFIGS_DIR / f"{slug}{BUNDLE_SUFFIX}"


def _target_bundle(slug: str, tenant_id: str) -> Path:
    """Yazılacaq bundle faylı — MÖVCUD, BAŞQA kirayəçinin faylı ƏZİLMİR.

    Eyni `tenant_id` üçün fayl üzərinə yazılır (arxiv təzələnir: canlı vəziyyət
    arxivdəkindən yenidir). Ad ÜST-ÜSTƏ düşür, lakin `tenant_id` FƏRQLİDİRSƏ
    (iki müştərinin adı eyni slug verib) yeni fayl `-2`, `-3` … şəkilçisi ilə
    yaradılır: adın toqquşması BAŞQA bir müştərinin konfiqurasiyasını silmək
    üçün əsas ola bilməz.
    """
    candidate = _bundle_path(slug)
    index = 1
    while candidate.exists():
        stored = _read_json(candidate)
        if str(stored.get("tenant_id", "")) == tenant_id:
            return candidate
        index += 1
        candidate = _bundle_path(f"{slug}-{index}")
    return candidate


def bundle_names() -> list[str]:
    """Arxivlənmiş kirayəçilərin adları (slug), ada görə sıralı.

    `_bundle_paths()`-ın PUBLİK üzü. Kənar çağıran (`onboard_new_tenant
    --verify <ad>`) «hansı adlar var» sualına cavab verməlidir — ad səhv
    yazılanda mövcud siyahını göstərmək operatoru `configs/` qovluğunu əl ilə
    açmaqdan xilas edir.
    """
    return [path.stem for path in _bundle_paths()]


def load_bundle(name: str) -> dict[str, Any]:
    """Ada (və ya slug-a) görə arxivi oxuyur; tapılmasa `SwitchError`.

    Ad həlli `cmd_activate` ilə EYNİ qaydadadır və qəsdən: əvvəlcə verilən
    sətir OLDUĞU KİMİ fayl adı kimi sınanır, sonra `slugify` tətbiq olunur.
    İki fərqli həll qaydası olsaydı, `switch.py yatas` işləyər, `--verify
    yatas` işləməzdi — və fərqin səbəbi heç yerdə yazılmazdı.
    """
    slug = name if _bundle_path(name).is_file() else slugify(name)
    bundle = _bundle_path(slug)
    if not bundle.is_file():
        available = ", ".join(bundle_names()) or "(arxiv boşdur)"
        raise SwitchError(f"«{name}» üçün arxiv tapılmadı. Mövcud adlar: {available}")
    stored = _read_json(bundle)
    stored.setdefault("slug", slug)
    return stored


def archive_config(
    *,
    company: str,
    installation: dict[str, Any],
    connection: dict[str, Any] | None,
    supabase: dict[str, Any] | None = None,
) -> Path:
    """Konfiqurasiyanı `configs/<slug>.config`-ə arxivləyir və yolu qaytarır.

    `onboard_new_tenant.py` bunu HƏR quraşdırmadan sonra çağırır — həmin
    skriptin mövcud yazı davranışı (arxiv qovluğu + `--dev` yerləri) DƏYİŞMİR,
    bu, ONA ƏLAVƏDİR.

    `connection` `None` ola bilər, ya da parolu boş ola bilər: bayraqsız («real
    müştəri») rejimində parol QƏSDƏN yazılmır, çünki DPAPI ilə şifrələnən dəyər
    başqa maşında açılmır (`onboard_new_tenant._write_config`). Belə bundle yenə
    arxivlənir — host/port/baza/istifadəçi adı ONDA var və aktivləşdirən tərəf
    parolun çatmadığını EKRANDA görür.

    ──────────────────────────────────────────────────────────────────────────
    `supabase` BLOKU — ARXİVDƏ VAR, AKTİVLƏŞDİRMƏDƏ İŞLƏNMİR
    ──────────────────────────────────────────────────────────────────────────
    Blok kirayəçinin `anon` açarını və layihə ünvanını daşıyır (ONBOARD-FINAL
    sihirbazı toplayır). O, `activate()` tərəfindən HEÇ BİR fayla YAZILMIR və
    bu, unudulmuş hissə deyil: tətbiq həmin dəyərləri YALNIZ mühit
    dəyişənindən oxuyur (`KOMPASOS_SUPABASE_ANON_KEY`), yəni onları
    `connection.json`-a köçürmək heç bir davranışı dəyişməzdi. Blokun rolu
    QEYD saxlamaqdır: «bu kirayəçinin açarı hansı idi» sualının cavabı Supabase
    panelindən kənarda başqa yerdə qalmır.

    Sirr kateqoriyası: `anon` açarı brauzerə göndərilmək üçündür və RLS ilə
    məhdudlaşır — `service_role` bura HEÇ VAXT düşmür.
    """
    tenant_id = str(installation.get("tenant_id", ""))
    slug = slugify(company) or f"tenant-{tenant_id[:8]}".strip("-") or "tenant"
    if slug == VENDOR_KEYWORD:
        # «Vendor» adlı kirayəçi `switch.py vendor` əmrini iki mənalı edərdi.
        slug = f"{slug}-tenant"
    target = _target_bundle(slug, tenant_id)
    _write_json(
        target,
        {
            "format_version": BUNDLE_VERSION,
            "slug": target.stem,
            "company": company,
            "tenant_id": tenant_id,
            "archived_at": datetime.now(UTC).isoformat(),
            "installation": installation,
            "connection": _keep_previous_connection(target, tenant_id, connection),
            "supabase": _keep_previous_supabase(target, tenant_id, supabase),
        },
    )
    return target


def _keep_previous_supabase(
    target: Path, tenant_id: str, supabase: dict[str, Any] | None
) -> dict[str, Any] | None:
    """`supabase` YOXDURSA köhnə bundle-dakı bloku SAXLAYIR.

    `_keep_previous_connection` ilə EYNİ qayda və eyni səbəb, lakin fərqli
    itki: `switch.py`-ın öz arxivləmə yolu (`_archive_active`) bu bloku
    ÜMUMİYYƏTLƏ bilmir — o, yalnız diskdəki iki JSON faylını oxuyur, `anon`
    açarı isə orada YOXDUR (bax `archive_config` başlığı). Qoruma olmasaydı,
    sihirbazla qurulmuş kirayəçiyə BİR DƏFƏ `switch.py` ilə keçmək açarı
    arxivdən həmişəlik silərdi.
    """
    if supabase is not None or not target.is_file():
        return supabase
    stored = _read_json(target)
    if str(stored.get("tenant_id", "")) != tenant_id:
        return supabase
    previous = stored.get("supabase")
    return previous if isinstance(previous, dict) else None


def _keep_previous_connection(
    target: Path, tenant_id: str, connection: dict[str, Any] | None
) -> dict[str, Any] | None:
    """`connection` YOXDURSA köhnə bundle-dakı bloku SAXLAYIR.

    ──────────────────────────────────────────────────────────────────────────
    ÖLÇÜLMÜŞ İTKİ — BU QORUMA OLMADAN NƏ OLURDU
    ──────────────────────────────────────────────────────────────────────────
    YARIMÇIQ hal (bax `ActiveState.has_files`) arxivlənəndə `connection.json`
    diskdə YOXDUR, yəni bura `None` gəlir. Şərtsiz yazsaydıq, EYNİ `tenant_id`
    üçün mövcud bundle-ın işlək bağlantısı — şifrələnmiş parolu daxil olmaqla —
    `null` ilə ƏVƏZLƏNƏRDİ. Parol BU MAŞINA bağlı şifrələnib və başqa
    nüsxədən bərpa oluna bilmir: itki geri dönməzdir.

    Qoruma DAR saxlanılır: blok YALNIZ TAMAMİLƏ YOXDURSA köhnəsi qalır. Blok
    VARSA (məsələn bayraqsız onboarding-in parolsuz şablonu) yenisi keçərlidir
    — orada operator bilərəkdən yeni konfiqurasiya yazır və sahə-sahə
    «birləşdirmə» host dəyişəndə köhnə parolu YENİ serverə yapışdırardı.
    """
    if connection is not None or not target.is_file():
        return connection
    stored = _read_json(target)
    if str(stored.get("tenant_id", "")) != tenant_id:
        return connection
    previous = stored.get("connection")
    return previous if isinstance(previous, dict) else None


# --------------------------------------------------------------------------- #
# Aktiv vəziyyət — yollar TƏTBİQİN ÖZ HƏLLEDİCİLƏRİNDƏN gəlir
# --------------------------------------------------------------------------- #


def _active_connection() -> Path | None:
    from src.infrastructure.config.connection_file import find_connection_file

    return find_connection_file()


def _connection_write_path() -> Path:
    from src.infrastructure.config.connection_file import connection_file_path

    return connection_file_path()


def _active_installation() -> Path | None:
    from src.shared.installation import installation_file

    path = installation_file()
    return path if path.is_file() else None


def _installation_write_path() -> Path:
    """`installation.json`-un yazılacağı yol.

    `installation_file()` MÖVCUD fayl tapmırsa defolt yolu qaytarır — yəni aktiv
    fayl silindikdən SONRA bu çağırış məhz «yeni fayl hara düşməlidir» sualına
    cavab verir.
    """
    from src.shared.installation import installation_file

    return installation_file()


def _read_state() -> ActiveState:
    marker = CONFIGS_DIR / ACTIVE_MARKER
    slug = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    return ActiveState(
        slug=slug or None,
        connection=_active_connection(),
        installation=_active_installation(),
    )


def _set_marker(slug: str | None) -> None:
    marker = CONFIGS_DIR / ACTIVE_MARKER
    if slug is None:
        marker.unlink(missing_ok=True)
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{slug}\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Keçid addımları
# --------------------------------------------------------------------------- #


def _fallback_slug(tenant_id: str) -> str:
    """İz-fayl yoxdur — aktiv konfiqurasiya HANSI adla arxivlənsin.

    Əvvəlcə arxivdə EYNİ `tenant_id` axtarılır: vendor vəziyyətində açılan
    tətbiq özünə YENİ `installation.json` yarada bilər
    (`resolve_installation_identity`-nin üçüncü mənbəyi) və həmin fayl adsız
    qalır. Tapılsa köhnə ad işlədilir, arxiv sadəcə təzələnir; tapılmasa vaxt
    möhürlü ad verilir. SİLMƏK seçim DEYİL — bu fayl istifadəçinin əl ilə
    qurduğu konfiqurasiya da ola bilər.
    """
    for path in _bundle_paths():
        stored = _read_json(path)
        if tenant_id and str(stored.get("tenant_id", "")) == tenant_id:
            return path.stem
    return f"namelum-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


def _archive_active(state: ActiveState) -> Path | None:
    """Aktiv konfiqurasiyanı arxivləyir və aktiv yerlərdən SİLİR.

    Qaytarır: yazılan bundle (arxivlənəsi fayl yoxdursa `None`). Silmə YALNIZ
    arxiv faylı diskə düşdükdən SONRA baş verir — sıra tərsinə olsaydı, yazı
    uğursuzluğu konfiqurasiyanı tamamilə itirərdi.

    Şərt `is_vendor` DEYİL, `has_files`-dir: `connection.json` yoxdur,
    `installation.json` isə var olan YARIMÇIQ halda vəziyyət «vendor» görünür,
    lakin təmizlənəsi (və əvvəlcə ARXİVLƏNƏSİ) fayl hələ qalır.
    """
    if not state.has_files:
        return None

    installation = _read_json(state.installation) if state.installation else {}
    connection = _read_json(state.connection) if state.connection else None
    tenant_id = str(installation.get("tenant_id", ""))
    slug = state.slug or _fallback_slug(tenant_id)

    # Şirkət adı aktiv fayllarda YOXDUR (bax modul başlığı) — mövcud bundle-dan
    # götürülür ki, təzələmə adı «yatas»a endirməsin.
    previous = _bundle_path(slug)
    company = str(_read_json(previous).get("company", "")) if previous.is_file() else slug
    bundle = archive_config(
        company=company or slug, installation=installation, connection=connection
    )

    for path in (state.connection, state.installation):
        if path is not None:
            path.unlink(missing_ok=True)
    _set_marker(None)
    return bundle


def _warn_shadow_copies() -> None:
    """Silmədən SONRA hələ də tapılan nüsxələri BİLDİRİR — özbaşına silmir.

    Hər iki faylın axtarış sırası ÇOX yerlidir (bax modul başlığı). Aktiv nüsxə
    silinəndə sıradakı NÖVBƏTİ fayl «aktiv»ə çevrilə bilər — məsələn həm
    repozitoriya kökündə, həm `%PROGRAMDATA%`-da `connection.json` varsa. Həmin
    ikinci fayl BİZİM arxivlədiyimiz DEYİL, yəni onu silmək arxivdə qarşılığı
    olmayan konfiqurasiyanı yox etmək olardı. Ona görə alət yalnız YERİNİ
    göstərir — qərarı operator verir.
    """
    remaining = (
        ("connection.json", _active_connection()),
        ("installation.json", _active_installation()),
    )
    for label, path in remaining:
        if path is None:
            continue
        sys.stdout.write(
            f"  XƏBƏRDARLIQ: axtarış sırasında BAŞQA «{label}» nüsxəsi qaldı — {path}\n"
            "               Bu fayl arxivlənmədi (məzmunu bizə məlum deyil); "
            "vendor vəziyyəti üçün onu ƏL İLƏ götürün.\n"
        )


def _database_url_note() -> None:
    """`DATABASE_URL` `connection.json`-u ÜSTƏLƏYİR — bu, sükutla qalmamalıdır.

    `build_dsn_from_env` əvvəlcə `DATABASE_URL`-ə baxır, yalnız o boşdursa fayla
    keçir. `python -m src.main` `.env` faylını OXUMUR, yəni adi işə salma bu
    aləti üstələmir; LAKİN `.env` yükləyən yollar (`scripts/dev_panel.py`) və
    mühitə əl ilə yazılmış dəyər üstələyir. Fərqi bilmədən «keçid işləmədi»
    qənaətinə gəlmək çox asandır — ona görə fakt EKRANDA deyilir.
    """
    if os.environ.get("DATABASE_URL", "").strip():
        sys.stdout.write(
            "  QEYD: mühitdə `DATABASE_URL` var — bu proses üçün o, "
            "`connection.json`-u ÜSTƏLƏYİR.\n"
        )
        return
    dotenv = _REPO_ROOT / ".env"
    if not dotenv.is_file():
        return
    for line in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL=") and stripped.partition("=")[2].strip():
            sys.stdout.write(
                "  QEYD: `.env`-də `DATABASE_URL` doludur. `python -m src.main` onu OXUMUR\n"
                "        (yəni keçid qüvvədədir), lakin `.env` yükləyən alətlərdə "
                "(`scripts/dev_panel.py`)\n        həmin dəyər `connection.json`-u üstələyir.\n"
            )
            return


# --------------------------------------------------------------------------- #
# Əmrlər
# --------------------------------------------------------------------------- #


def _describe(state: ActiveState) -> str:
    """Vəziyyətin BİR SƏTİRLİK adı — ÜÇ hal, mənbə HƏMİŞƏ `connection.json`.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ İZ-FAYL BURADA BİRİNCİ SORUŞULMUR
    ──────────────────────────────────────────────────────────────────────────
    Vəziyyəti tətbiqin ÖZ qərarı təyin edir (`find_connection_file()`, bax
    `ActiveState.is_vendor`). Əvvəl bu funksiya iz-fayldan başlayırdı və
    nəticədə `connection.json` olmayan maşın «naməlum (iz-fayl yoxdur)»
    görünürdü — halbuki tətbiq üçün həmin vəziyyət DƏQİQ məlumdur: config
    yoxdur, yəni vendor. İz-fayl VƏZİYYƏTİ deyil, yalnız ADI bilir.

        1. `connection.json` YOXDUR      → «vendor (config yoxdur)».
           İz-fayla ÜMUMİYYƏTLƏ baxılmır: adın olub-olmaması tətbiqin
           bağlantısız qalmasını dəyişmir.
        2. VAR + iz-fayl var             → kirayəçinin adı.
        3. VAR + iz-fayl YOX             → «kirayəçi (adı bilinmir)». Bağlantı
           işlək ola-ola adı bilmirik (iz-fayl silinib, ya da config əl ilə
           qoyulub); ad arxivləmə anında `tenant_id`-yə görə axtarılır
           (`_fallback_slug`) — burada isə HƏLƏ tapılmadığı üçün açıq deyilir.
    """
    if state.is_vendor:
        return f"{VENDOR_KEYWORD} (config yoxdur)"
    if state.slug:
        return state.slug
    return "kirayəçi (adı bilinmir)"


def _print_state(state: ActiveState) -> None:
    """Vəziyyət + hər iki faylın FAKTİKİ yolu, sonra YARIMÇIQ hal xəbərdarlığı.

    Yollar həmişə çap olunur, çünki «vendor»un səbəbi ORADA görünür: fayl hansı
    qovluqda tapıldı (və ya heç tapılmadı) sualına cavab vermədən istifadəçi
    «keçid işləmədi» ilə «konfiqurasiya başqa yerdədir»i ayıra bilmir.
    """
    sys.stdout.write(f"Hazırda: {_describe(state)}\n")
    sys.stdout.write(f"  connection.json  : {state.connection or 'YOXDUR'}\n")
    sys.stdout.write(f"  installation.json: {state.installation or 'YOXDUR'}\n")
    if state.is_vendor and state.installation is not None:
        # YARIMÇIQ HAL — «vendor» sətrini ziddiyyətli göstərməmək üçün AÇIQ
        # yazılır: bağlantı yoxdur (yəni vəziyyət vendor-dur), lakin köhnə
        # kirayəçinin KİMLİYİ hələ diskdədir. Tətbiq onu oxuyub həmin
        # `tenant_id` ilə qalxmağa çalışacaq, ona görə hal təmiz vendor DEYİL.
        sys.stdout.write(
            "  QEYD: bağlantı yoxdur, LAKİN köhnə kirayəçinin kimliyi qalıb — "
            "yarımçıq haldır.\n"
            f"        `.venv/Scripts/python.exe scripts/switch.py {VENDOR_KEYWORD}` "
            "onu arxivləyib təmizləyir.\n"
        )


def _print_list(state: ActiveState) -> None:
    bundles = _bundle_paths()
    sys.stdout.write(f"Arxivlənmiş kirayəçilər ({CONFIGS_DIR}):\n")
    if not bundles:
        sys.stdout.write(
            "  (boş — `scripts/onboard_new_tenant.py` hər quraşdırmadan sonra yazır)\n"
        )
    for path in bundles:
        stored = _read_json(path)
        mark = "→" if path.stem == state.slug else " "
        company = str(stored.get("company", "")) or "(ad yoxdur)"
        tenant = str(stored.get("tenant_id", ""))[:8] or "????????"
        connection = stored.get("connection")
        secret = (
            ""
            if isinstance(connection, dict) and connection.get("password_encrypted")
            else "  [parolsuz]"
        )
        sys.stdout.write(f"  {mark} {path.stem:<22} {company:<22} tenant {tenant}…{secret}\n")
    sys.stdout.write("\n")
    _print_state(state)
    sys.stdout.write(
        "\nKeçid:\n"
        f"  .venv/Scripts/python.exe scripts/switch.py {VENDOR_KEYWORD}\n"
        "  .venv/Scripts/python.exe scripts/switch.py <ad>\n"
    )


def _finish(state: ActiveState) -> None:
    """Keçidin YEKUN sətri — vəziyyət YENİDƏN oxunur, güman edilmir.

    «Etdim» ilə «oldu» eyni şey deyil (`onboard_new_tenant._self_check` ilə eyni
    prinsip): kölgədə qalmış ikinci nüsxə keçidi sükutla ləğv edə bilər, ona görə
    ekrana yazılan vəziyyət faylların FAKTİKİ vəziyyətindən gəlir.
    """
    sys.stdout.write(
        f"\n✅ İndi: {_describe(state)}. "
        "Tətbiqi işə salın: `.venv/Scripts/python.exe -m src.main --gui`\n"
    )


def cmd_vendor() -> int:
    """`switch.py vendor` — aktiv config arxivlənir, maşın «config-siz» qalır."""
    state = _read_state()
    # Şərt `is_vendor` DEYİL: bağlantı onsuz da yoxdursa, lakin köhnə
    # `installation.json` qalıbsa görüləsi iş VAR (arxivlə + təmizlə).
    if not state.has_files:
        sys.stdout.write("Artıq vendor vəziyyətindədir — heç nə dəyişmədi.\n")
        _finish(state)
        return 0

    bundle = _archive_active(state)
    if bundle is not None:
        sys.stdout.write(f"Arxivləndi: {bundle}\n")
    _warn_shadow_copies()
    _database_url_note()
    _finish(_read_state())
    return 0


def cmd_activate(name: str) -> int:
    """`switch.py <ad>` — arxivdəki konfiqurasiya aktiv yerlərə qaytarılır."""
    slug = name if _bundle_path(name).is_file() else slugify(name)
    bundle = _bundle_path(slug)
    if not bundle.is_file():
        sys.stderr.write(f"XƏTA: «{name}» üçün arxiv tapılmadı ({bundle}).\n\n")
        _print_list(_read_state())
        return 1

    stored = _read_json(bundle)
    installation = stored.get("installation")
    if not isinstance(installation, dict) or not installation.get("tenant_id"):
        raise SwitchError(
            f"«{bundle}» içində `installation` bloku yoxdur və ya `tenant_id` boşdur — "
            "arxiv korlanıb və ya köhnə formatdadır."
        )
    connection = stored.get("connection")

    # ƏVVƏLCƏ ARXİVLƏ, SONRA YAZ: kökdəki (və ya `%PROGRAMDATA%`-dakı) mövcud
    # konfiqurasiya üzərinə birbaşa yazsaydıq, adı bilinməyən aktiv kirayəçi
    # sükutla İTƏRDİ — tapşırığın qırmızı xətti məhz budur.
    state = _read_state()
    if state.slug == slug and state.has_files:
        sys.stdout.write(f"«{slug}» onsuz da aktivdir — arxiv təzələnir.\n")
    previous = _archive_active(state)
    if previous is not None and previous != bundle:
        sys.stdout.write(f"Əvvəlki konfiqurasiya arxivləndi: {previous}\n")

    identity_path = _installation_write_path()
    _write_json(identity_path, installation)
    sys.stdout.write(f"Aktiv edildi: {identity_path}\n")

    if isinstance(connection, dict):
        connection_path = _connection_write_path()
        _write_json(connection_path, connection)
        sys.stdout.write(f"Aktiv edildi: {connection_path}\n")
        if not connection.get("password_encrypted"):
            sys.stdout.write(
                "  XƏBƏRDARLIQ: arxivdə PAROL yoxdur (bayraqsız onboarding belə yazır) — "
                "«Bağlantı Ayarları» ekranından daxil edin.\n"
            )
    else:
        sys.stdout.write(
            "  XƏBƏRDARLIQ: arxivdə `connection` bloku yoxdur — baza bağlantısı qurulmayacaq.\n"
        )

    _set_marker(slug)
    _database_url_note()
    _finish(_read_state())
    return 0


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Vendor Konsolu ↔ kirayəçi test vəziyyəti arasında keçid",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="",
        metavar="AD",
        help=f"«{VENDOR_KEYWORD}» və ya arxivlənmiş kirayəçinin adı; boş = siyahı",
    )
    args = parser.parse_args(argv)

    target = str(args.target).strip()
    try:
        if not target:
            _print_list(_read_state())
            return 0
        if target.lower() == VENDOR_KEYWORD:
            return cmd_vendor()
        return cmd_activate(target)
    except SwitchError as exc:
        sys.stderr.write(f"DAYANDI: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover — CLI giriş nöqtəsi
    raise SystemExit(main())
