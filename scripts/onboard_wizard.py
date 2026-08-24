r"""Sual-cavablı tenant sihirbazı — `onboard_new_tenant.py`-in ARQUMENTSİZ yolu.

──────────────────────────────────────────────────────────────────────────────
BU SKRİPT `.exe`-YƏ PAKETLƏNMİR
──────────────────────────────────────────────────────────────────────────────
`src/KompasOS.spec` yalnız `src/` altını yığır. Qayda `onboard_new_tenant.py`,
`switch.py` və `dev_panel.py` ilə EYNİDİR, səbəb də eyni: bu modul VENDOR
bazasının DSN-ini yaddaşda saxlayır — müştəri paketində belə bir faylın olması
lisenziya qapısının açarını müştərinin maşınına köçürmək olardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI MODUL — `onboard_new_tenant.py`-a NİYƏ YAZILMADI
──────────────────────────────────────────────────────────────────────────────
`onboard_new_tenant.py` BİR işi görür: altı addımı SIRA ilə icra edir və hər
biri əvvəlkinin nəticəsindən asılıdır. Sihirbaz isə TAMAMİLƏ başqa bir işdir —
o, həmin addımların GİRİŞLƏRİNİ toplayır və heç bir baza əməliyyatı ETMİR
(yeganə istisna: bağlantı sınağı, `probe`).

İkisi bir faylda olsaydı, «arqumentləri yoxla» məntiqi ilə «sualı təkrar
soruş» məntiqi bir-birinə qarışardı: birincisi UĞURSUZLUQDA DAYANIR (CLI-nin
müqaviləsi), ikincisi isə uğursuzluqda TƏKRAR SORUŞUR (sihirbazın müqaviləsi).
Eyni funksiyada iki ziddiyyətli davranış saxlamaq həmin funksiyanı hər ikisi
üçün səhv edərdi.

Ona görə sərhəd DARDIR: bu modul `WizardAnswers` qaytarır, çağıran tərəf onu
`argparse.Namespace`-ə köçürür və MÖVCUD axın heç nə bilmədən davam edir.

──────────────────────────────────────────────────────────────────────────────
🔴 DSN «POOLER» DEYİL, «BİRBAŞA» FORMATLA QURULUR — REAL XƏTANIN NƏTİCƏSİ
──────────────────────────────────────────────────────────────────────────────
Əvvəl operator DSN-i ƏL İLƏ yazırdı və Supabase-in göstərdiyi ilk sətir pooler
formatıdır:

    postgresql://postgres.<ref>:<parol>@aws-0-<REGION>.pooler.supabase.com:5432/postgres

Bu formatda `<REGION>` VAR və o, Project Ref-dən ÇIXARILA BİLMİR — yəni sihirbaz
istifadəçidən regionu da soruşmalı olardı. Soruşulmayanda (və ya səhv
təxmin ediləndə) nəticə «host tapılmadı» xətasıdır, səbəbi isə heç bir ekranda
yazılmır. Məhz bu qarşılaşılıb.

Burada BİRBAŞA (direct) format qurulur:

    postgresql://postgres:<parol>@db.<ref>.supabase.co:5432/postgres

Host TAMAMİLƏ Project Ref-dən alınır, REGİON LAZIM DEYİL — yəni sihirbazın
soruşduğu iki dəyər (ref + parol) kifayətdir. Bu seçim ƏMƏLİYYAT xarakterlidir
və tətbiqin gündəlik bağlantısına aid DEYİL: burada icra olunan iş
miqrasiya/seed-dir — bir dəfəlik, tək bağlantılı, uzun sürən. Pooler məhz
əks profil (çoxlu qısa bağlantı) üçündür.

QEYD (bilərəkdən qəbul edilən məhdudiyyət): `db.<ref>.supabase.co` bəzi yeni
Supabase layihələrində YALNIZ IPv6 ünvanı elan edir. IPv4-ə bağlı şəbəkədə
bağlantı «şəbəkə əlçatmazdır» ilə dayanır — `_humanise` MƏHZ bu halı ayrıca
tanıyır və operatoru pooler DSN-ini `--tenant-dsn` bayrağı ilə əl ilə verməyə
yönləndirir. Köhnə bayraqlı yol qəsdən SİLİNMƏYİB: o, bu halın yeganə
çıxışıdır.

──────────────────────────────────────────────────────────────────────────────
VENDOR DSN-i BİR DƏFƏ SORUŞULUR — `.onboard_config`
──────────────────────────────────────────────────────────────────────────────
Vendor (mərkəzi lisenziya) bazası HƏR quraşdırmada EYNİDİR — onu hər dəfə
soruşmaq beş sualın ikisini mənasız təkrara çevirərdi və təkrar yazılan parol
səhv yazılma riskidir. Dəyər `.onboard_config` faylında ŞİFRƏLİ saxlanılır.

Şifrələmə YENİDƏN YAZILMIR — `connection_file.py`-ın işlətdiyi EYNİ zəncir
(`EnvironmentKeyProvider` → `WindowsDpapiKeyProvider(machine_scope=True)`)
çağırılır. İkinci bir şifrələmə yolu yazsaydıq, açar rotasiyası (bax
`docs/key_rotation.md`) bir nüsxəni yeniləyər, digərini sükutla köhnə açarla
qoyardı.

Fayl `.gitignore`-dadır: içindəki parol VENDOR bazasınındır, yəni bütün
müştərilərin abunə sətirlərinə yazma icazəsidir.
"""

from __future__ import annotations

import getpass
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import quote

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
# Skript repozitoriya kökündən KƏNARDAN da çağırıla bilər (`python scripts/…`),
# ona görə kök `sys.path`-a AÇIQ əlavə olunur — `switch.py:78` ilə eyni sətir,
# eyni səbəb.
sys.path.insert(0, str(_REPO_ROOT))

#: Vendor bağlantısının şifrəli yaddaşı. Layihə kökündədir (bax modul başlığı).
VENDOR_MEMORY_FILE: Final[Path] = _REPO_ROOT / ".onboard_config"

#: Şifrələmə konteksti (AAD) — `connection_file._CONTEXT` ilə eyni niyyət:
#: token başqa sahəyə köçürülüb istifadə edilə bilməsin.
_MEMORY_CONTEXT: Final[str] = "onboard_config:vendor"

#: Yaddaş formatının versiyası — gələcək dəyişiklikdə köhnə faylı tanımaq üçün.
_MEMORY_VERSION: Final[int] = 1

#: Bağlantı sınağının vaxt həddi. Sihirbaz İNTERAKTİVDİR — operator ekran
#: qarşısında GÖZLƏYİR, ona görə hədd quraşdırma addımlarındakı 30 saniyədən
#: QISADIR: 10 saniyə cavab verməyən host praktikada onsuz da səhv yazılmış
#: host-dur və operatoru 30 saniyə gözlətmək düzəlişi gecikdirməkdən başqa heç
#: nə vermir. Yazı addımları (`_apply_migrations`, `_create_tenant_row`) öz 30
#: saniyəlik həddini SAXLAYIR — orada gözləyən adam yoxdur.
CONNECT_TIMEOUT_SECONDS: Final[int] = 10

#: Supabase Project Ref — 20 simvollu kiçik latın hərfləri (rəsmi format).
#: Diapazon GENİŞ saxlanılır (16–32), çünki uzunluq Supabase-in öz qərarıdır
#: və dəyişsə, DAR yoxlama işlək ref-i rədd edərdi.
_PROJECT_REF_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]{16,32}$")

#: Yapışdırılmış TAM ünvandan ref-i çıxarır: operator Supabase panelindən
#: `https://abcdefghijklmnopqrst.supabase.co` və ya `db.<ref>.supabase.co`
#: kopyalayır — ikisi də QƏBUL EDİLİR, çünki «yalnız ortadakı hissəni yaz»
#: göstərişi sihirbazın öz məqsədinə (texniki termin TƏLƏB ETMƏ) ziddir.
#: … və panelin ÖZ ünvanı (`…/dashboard/project/<ref>`). Bu, praktikada ƏN ÇOX
#: yapışdırılan sətirdir: operator ref-i axtararkən onsuz da həmin səhifədədir
#: və brauzerin ünvan sətri əlinin altındadır.
_PROJECT_REF_IN_URL: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?:https?://)?(?:db\.)?([a-z0-9]{16,32})\.supabase\.(?:co|com)", re.IGNORECASE),
    re.compile(r"/project/([a-z0-9]{16,32})", re.IGNORECASE),
)

#: E-poçt yoxlaması. `license_tenants.company_contact_email` sütununun DB
#: CHECK-i (migrations/059) ilə EYNİ NİYYƏTDƏDİR, lakin onun nüsxəsi DEYİL:
#: burada məqsəd səhv yazılışı EKRANDA tutmaqdır, zəmanət isə DB-dədir.
_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Vendor layihəsinin ref-i tenant kimi verilsə DAYANDIRAN mesaj. Yoxlama
#: `onboard_new_tenant._reject_invalid_arguments`-də DƏ var (bayraqlı yol üçün)
#: — bura ONA ƏLAVƏDİR: sihirbazda səhv DƏRHAL, sual soruşulan anda tutulur,
#: yəni operator qalan sualları boş yerə cavablamır.
_SAME_PROJECT_MESSAGE: Final[str] = (
    "❌ Bu, VENDOR layihəsinin özüdür. Hər müştəri AYRI Supabase layihəsidir — "
    "müştərinin öz layihəsinin Project Ref-ini yazın."
)


class WizardCancelledError(RuntimeError):
    """Operator sihirbazı yarımçıq bağladı (Ctrl+C və ya axın bitdi).

    Adi `KeyboardInterrupt`-dan AYRILDI: çağıran tərəf «istifadəçi imtina etdi»
    (proses kodu 130, heç nə yazılmayıb) ilə «gözlənilməz çökmə» arasındakı
    fərqi görməlidir — birincisi normal, ikincisi hesabat tələb edən haldır.
    """


@dataclass(frozen=True)
class VendorCredentials:
    """Vendor (mərkəzi lisenziya) bazasının açarı — `.onboard_config`-dədir."""

    project_ref: str
    password: str

    @property
    def dsn(self) -> str:
        return build_direct_dsn(self.project_ref, self.password)


@dataclass(frozen=True)
class WizardAnswers:
    """Sihirbazın YEKUN nəticəsi — baza əməliyyatı BURADA yoxdur.

    Attributes:
        company: Şirkət/test adı; `--company`-nin qarşılığı.
        contact_email: `license_tenants.company_contact_email` (NOT NULL).
        tenant_dsn: Müştəri bazasının BİRBAŞA DSN-i.
        vendor_dsn: Mərkəzi lisenziya bazasının BİRBAŞA DSN-i.
        supabase_ref: Müştəri layihəsinin ref-i (vendor sətrinə yazılır).
        anon_key: Müştəri layihəsinin `anon` açarı; boş ola bilər.
    """

    company: str
    contact_email: str
    tenant_dsn: str
    vendor_dsn: str
    supabase_ref: str
    anon_key: str


# --------------------------------------------------------------------------- #
# DSN qurulması
# --------------------------------------------------------------------------- #


def build_direct_dsn(project_ref: str, password: str) -> str:
    """`postgresql://postgres:<parol>@db.<ref>.supabase.co:5432/postgres`.

    Parol URL-KODLANIR (`quote(..., safe="")`). Bu, kosmetika deyil: Supabase
    generasiya etdiyi parollarda `@`, `/`, `#`, `?` normaldır və kodlanmasa
    `@` DSN-i host hissəsindən ERKƏN kəsər — nəticədə bağlantı BAŞQA (çox vaxt
    mövcud olmayan) hosta gedər və xəta «parol səhvdir» deyil, «host tapılmadı»
    olar. Eyni qərar `connection_file.ConnectionSettings.dsn()`-dədir.

    `sslmode=require` AÇIQ yazılır: `psycopg`-nin defoltu `prefer`-dir, yəni
    server TLS-i rədd etsə bağlantı ŞİFRƏSİZ davam edər. Supabase-də bu hal
    baş vermir, lakin defolta güvənmək «şifrələnib» sualının cavabını
    kitabxananın versiyasına bağlamaq olardı.
    """
    return (
        f"postgresql://postgres:{quote(password, safe='')}"
        f"@db.{project_ref}.supabase.co:5432/postgres?sslmode=require"
    )


def normalise_project_ref(raw: str) -> str:
    """Yapışdırılmış ünvandan ref-i çıxarır; ref verilibsə olduğu kimi qaytarır.

    Bax `_PROJECT_REF_IN_URL` şərhinə: sihirbazın qəti şərti texniki termin
    TƏLƏB ETMƏMƏKDİR, ona görə «panelin ünvan sətrini yapışdır» da işləməlidir.
    """
    text = raw.strip()
    for pattern in _PROJECT_REF_IN_URL:
        match = pattern.search(text)
        if match is not None:
            return match.group(1).lower()
    return text.lower()


# --------------------------------------------------------------------------- #
# Bağlantı sınağı — YEGANƏ baza toxunuşu
# --------------------------------------------------------------------------- #


#: Uğursuzluğun NÖVLƏRİ. Mətn deyil, AÇAR kimi işlənir: sihirbaz onlara görə
#: HANSI sualı təkrar soruşacağına qərar verir (bax `_ask_project`).
#:
#: Adlarda «password»/«secret» sözü YOXDUR: `ruff`-un S105/S106 qaydaları
#: belə adlı sabiti/arqumenti «kodda bərkidilmiş parol» sayır. Burada isə
#: nə sabitin dəyəri, nə də arqument PAROLDUR — biri XƏTANIN NÖVÜ, digəri
#: SUALIN MƏTNİDİR.
PROBE_CREDENTIAL: Final[str] = "credential"
PROBE_HOST: Final[str] = "host"
PROBE_TIMEOUT: Final[str] = "timeout"
PROBE_NETWORK: Final[str] = "network"
PROBE_OTHER: Final[str] = "other"


@dataclass(frozen=True)
class ProbeFailure:
    """Bağlantı sınağının uğursuzluğu — NÖVÜ və İNSAN-OXUNAQLI mətni.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TƏK MƏTN DEYİL — `kind` NƏYİ HƏLL EDİR
    ──────────────────────────────────────────────────────────────────────────
    ÖLÇÜLMÜŞ SÜRTÜNMƏ: əvvəlki forma yalnız mətn qaytarırdı, ona görə hər
    uğursuzluqda dövrə BAŞA — Project Ref sualına — qayıdırdı. Səhv PAROL
    yazan operator ref-i də yenidən yazmalı olurdu, halbuki ref DÜZGÜNDÜR
    (server məhz ona görə cavab verdi: `28P01` serverə ÇATMIŞ bağlantının
    kodudur). Bu, sihirbazın öz məqsədinə — sürtünməni azaltmağa — zidd idi.

    `kind` həmin qərarı mümkün edir: parol səhvdirsə YALNIZ parol, ünvan
    səhvdirsə ref soruşulur.
    """

    kind: str
    message: str


def probe(dsn: str) -> ProbeFailure | None:
    """Bağlantını sınayır. Uğur — `None`; əks halda `ProbeFailure`.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SUALDAN DƏRHAL SONRA, MİQRASİYADAN ƏVVƏL
    ──────────────────────────────────────────────────────────────────────────
    Səhv parol sınaq olmadan yalnız 1-ci addımda (miqrasiya icraçısı) üzə
    çıxardı — o isə ALT PROSESDİR və xətası `stderr`-də stack-trace kimi
    görünür. Operator həmin mətndən «parolu səhv yazmışam» nəticəsini çıxara
    bilməzdi və sihirbazı BAŞDAN başlamalı olardı (artıq cavablanmış sualları
    təkrar yazaraq). Sınaq həmin dövrəni sualın YANINDA bağlayır.
    """
    import psycopg

    try:
        with (
            psycopg.connect(dsn, connect_timeout=CONNECT_TIMEOUT_SECONDS) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
    except psycopg.OperationalError as exc:
        return _humanise(exc)
    except psycopg.Error as exc:
        # `OperationalError`-dan KƏNAR hal (məs. icazə xətası): səbəb
        # təsnif edilə bilmir, lakin STACK-TRACE yenə də göstərilmir —
        # yalnız BİRİNCİ sətir, çünki `psycopg` çox vaxt bura serverin tam
        # `CONTEXT:`/`DETAIL:` blokunu qoyur və o, ekranı doldurur.
        return ProbeFailure(
            PROBE_OTHER, f"❌ Baza gözlənilməz cavab verdi: {str(exc).splitlines()[0]}"
        )
    return None


def _humanise(exc: Exception) -> ProbeFailure:
    """`psycopg` xətasını istifadəçi mesajına çevirir (stack-trace YOX).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ MƏTNƏ BAXILIR, `sqlstate`-ə DEYİL (YALNIZ BİR HALDA `sqlstate` VAR)
    ──────────────────────────────────────────────────────────────────────────
    Aşağıdakı halların YALNIZ biri — səhv parol (`28P01`) — serverə ÇATIR, yəni
    `sqlstate` daşıyır. Qalanları (DNS, timeout, şəbəkə) bağlantı QURULMAZDAN
    ƏVVƏL baş verir: server heç bir kod göndərmir, əlimizdə YALNIZ libpq-nun
    mətni olur. Ona görə birinci yoxlama `sqlstate`, qalanları mətn üzrədir —
    ardıcıllıq da məhz budur: dəqiq siqnal əvvəl, təxmini sonra.
    """
    sqlstate = getattr(exc, "sqlstate", None)
    text = str(exc).lower()

    if sqlstate == "28P01" or "password authentication failed" in text:
        return ProbeFailure(
            PROBE_CREDENTIAL,
            "❌ Verilənlər bazasına qoşula bilmədim — parol səhv ola bilər.\n"
            "   (Supabase panelində: Project Settings → Database → Database password)",
        )

    if any(
        marker in text
        for marker in (
            "could not translate host name",
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "no such host",
        )
    ):
        return ProbeFailure(
            PROBE_HOST,
            "❌ Bu ünvanda Supabase layihəsi tapılmadı. Project Ref-i yoxlayıb "
            "yenidən yazın.\n"
            "   (Supabase panelində: Project Settings → General → Reference ID)",
        )

    if "timeout" in text or "timed out" in text:
        # NÖV `timeout`-dur, `host` DEYİL: ünvan səhv OLMAYA da bilər —
        # internet kəsilib. Ref-i yenidən soruşmaq operatoru düzgün yazdığı
        # dəyəri şübhə altına almağa məcbur edərdi, ona görə `_ask_project`
        # bu halda da REF-Ə qayıdır, lakin mesaj şəbəkəni göstərir.
        return ProbeFailure(
            PROBE_TIMEOUT,
            f"❌ Bağlantı {CONNECT_TIMEOUT_SECONDS} saniyədən çox çəkdi. "
            "İnternetinizi yoxlayıb yenidən cəhd edin.",
        )

    if "network is unreachable" in text or "connection refused" in text:
        # BİLƏRƏKDƏN AYRICA HAL — bax modul başlığındakı IPv6 qeydi. Bu mesaj
        # operatoru «ref səhvdir» axtarışına yönəltməməlidir: ünvan DOĞRUDUR,
        # sadəcə bu şəbəkədən çatmır.
        return ProbeFailure(
            PROBE_NETWORK,
            "❌ Ünvana çatmaq mümkün olmadı (şəbəkə əlçatmazdır).\n"
            "   Səbəb çox vaxt budur: `db.<ref>.supabase.co` yalnız IPv6 elan "
            "edir, şəbəkəniz isə IPv4-dür.\n"
            "   Çıxış: Supabase panelindən «Connection pooling» DSN-ini "
            "kopyalayıb skripti bayraqla işə salın:\n"
            "   scripts/onboard_new_tenant.py --company … --tenant-dsn «…» --vendor-dsn «…»",
        )

    return ProbeFailure(PROBE_OTHER, f"❌ Bağlantı alınmadı: {str(exc).splitlines()[0]}")


# --------------------------------------------------------------------------- #
# Sual-cavab
# --------------------------------------------------------------------------- #


def _say(text: str) -> None:
    """Ekrana yazır. `print` ƏVƏZİNƏ — səbəb `onboard_new_tenant.py` ilə eynidir.

    Modul öz çıxışını `sys.stdout`-a AÇIQ yazır ki, `_ensure_utf8_stdio()`-nun
    yenidən konfiqurasiya etdiyi axınla eyni obyekt işlənsin.
    """
    sys.stdout.write(text)
    sys.stdout.flush()


def ask(
    label: str,
    *,
    secret: bool = False,
    optional: bool = False,
    validate: Callable[[str], str] | None = None,
) -> str:
    """Bir sual — cavab QƏBUL EDİLƏNƏ QƏDƏR təkrarlanır.

    Args:
        label: Ekranda görünən sual.
        secret: `True` — yazılan görünmür (parol).
        optional: `True` — boş ENTER qəbul edilir və boş sətir qaytarılır.
        validate: Cavabı yoxlayır; BOŞ sətir — qəbul, əks halda səbəb mətni.

    Raises:
        WizardCancelledError: Ctrl+C və ya giriş axını bağlandı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ DÖVRƏ, NİYƏ «SƏHVDİRSƏ DAYAN»
    ──────────────────────────────────────────────────────────────────────────
    Skript altı addımdan ƏVVƏL, yəni HEÇ NƏ YAZILMAMIŞ vəziyyətdə soruşur —
    burada dayanmağın heç bir qoruyucu faydası yoxdur, əvəzində artıq
    cavablanmış sualları itirir. Yazı başladıqdan SONRA vəziyyət tərsinə
    çevrilir və orada dayanma qaydası (`OnboardingError`) qüvvədədir.
    """
    reader = getpass.getpass if secret else _readline
    suffix = " (istəyə bağlı, ENTER — keç)" if optional else ""
    while True:
        try:
            answer = reader(f"  {label}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise WizardCancelledError("sihirbaz yarımçıq bağlandı") from exc

        if not answer:
            if optional:
                return ""
            _say("     ❌ Bu sahə boş qala bilməz.\n")
            continue

        reason = validate(answer) if validate is not None else ""
        if reason:
            _say(f"     {reason}\n")
            continue
        return answer


def choose(question: str, options: list[tuple[str, str]]) -> str:
    """Nömrələnmiş seçim soruşur və seçilmiş AÇARI qaytarır.

    Args:
        question: Ekranda görünən sual.
        options: `(açar, izah)` cütləri — sıra EKRANDAKI sıradır.

    Raises:
        WizardCancelledError: Ctrl+C və ya giriş axını bağlandı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ NÖMRƏ, NİYƏ «bəli/xeyr» DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Bu köməkçinin YEGANƏ istifadəçisi «bu şirkət ARTIQ mövcuddur» sualıdır
    (`onboard_new_tenant._resolve_duplicate`) və orada üç MƏNALI cavab var:
    mövcudu davam etdir / ayrıca yeni kirayəçi yarat / dayan. İki-cavablı
    sual bu üçlüyü gizlədərdi: «xeyr» həm «dayan», həm «yenisini yarat» kimi
    oxuna bilər və səhv oxunuşun qiyməti YETİM KİRAYƏÇİdir — yəni vendor
    bazasında ödənişi izlənməyən, heç bir maşında işlədilməyən sətir.

    Defolt YOXDUR: boş ENTER sual TƏKRARLANIR. Belə bir sualda defolt
    qoymaq, ekranı oxumadan ENTER basan operatoru sükutla bir seçimə
    bağlamaq olardı.
    """
    _say(f"\n  {question}\n")
    for index, (_, description) in enumerate(options, start=1):
        _say(f"    {index}) {description}\n")
    while True:
        try:
            raw = _readline(f"  Seçim (1–{len(options)}): ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise WizardCancelledError("sihirbaz yarımçıq bağlandı") from exc
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        _say(f"     ❌ 1 ilə {len(options)} arasında bir rəqəm yazın.\n")


def is_interactive() -> bool:
    """Sual soruşmaq MÜMKÜNDÜRMÜ — yəni `stdin` real terminaldır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ LAZIMDIR — SUAL SORUŞA BİLMƏYƏN YERDƏ SORUŞMAQ ASILMADIR
    ──────────────────────────────────────────────────────────────────────────
    Bayraqlı yol CI-dan, `.bat` faylından və ya boru ilə çağırıla bilər.
    Orada `input()` DƏRHAL `EOFError` verir (ya da Windows-da `getpass`
    KONSOLU gözləyib ASILIR) — yəni «istifadəçidən soruş» həlli həmin
    mühitdə həll deyil, nasazlıqdır. `onboard_new_tenant._resolve_duplicate`
    bu funksiyaya baxıb qərar verir: interaktivdirsə SORUŞUR, deyilsə
    AYDIN göstərişlə DAYANIR (sükutla davam etmək YETİM KİRAYƏÇİ yaradardı).
    """
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


def _readline(prompt: str) -> str:
    """`input()`-un örtüyü — `getpass.getpass` ilə EYNİ imzada olsun deyə.

    `ask` oxuyucunu bir dəyişəndə saxlayır; imzalar fərqli olsaydı hər
    çağırışda `if secret:` budağı təkrarlanardı.
    """
    _say(prompt)
    return input()


def _validate_project_ref(value: str) -> str:
    if _PROJECT_REF_PATTERN.match(normalise_project_ref(value)):
        return ""
    return (
        "❌ Bu, Project Ref-ə oxşamır (20 simvollu kiçik hərf/rəqəm gözlənilir).\n"
        "     Supabase panelinin ünvanını olduğu kimi də yapışdıra bilərsiniz."
    )


def _validate_email(value: str) -> str:
    if _EMAIL_PATTERN.match(value):
        return ""
    return "❌ E-poçt ünvanı düzgün görünmür (nümunə: it@embawood.az)."


# --------------------------------------------------------------------------- #
# Vendor yaddaşı — `.onboard_config`
# --------------------------------------------------------------------------- #


def _cipher() -> object:
    """`connection_file._cipher()` ilə EYNİ zəncir — nüsxə DEYİL, eyni qurğu.

    İki fərqli zəncir olsaydı, `docs/key_rotation.md`-dəki rotasiya birini
    yeniləyər, digərini köhnə açarla qoyardı və `.onboard_config` sükutla
    oxunmaz olardı — nəticə isə «vendor DSN-i yenidən soruşulur» kimi görünər,
    səbəbi isə heç yerdə yazılmazdı.
    """
    from src.infrastructure.security.encryption import (
        ChainedKeyProvider,
        EncryptionService,
        EnvironmentKeyProvider,
        WindowsDpapiKeyProvider,
    )

    return EncryptionService(
        ChainedKeyProvider([EnvironmentKeyProvider(), WindowsDpapiKeyProvider(machine_scope=True)])
    )


def load_vendor() -> VendorCredentials | None:
    """Yadda saxlanmış vendor açarı; yoxdursa/açılmırsa `None`.

    ──────────────────────────────────────────────────────────────────────────
    DEŞİFRƏ XƏTASI «YOXDUR» SAYILIR — VƏ BU, QƏSDLİDİR
    ──────────────────────────────────────────────────────────────────────────
    Fayl var, lakin açılmırsa (açar rotasiya olunub, fayl başqa maşından
    köçürülüb, DPAPI profili dəyişib) bu, DÜZƏLƏ BİLƏN vəziyyətdir: sihirbaz
    sualı yenidən verir və cavabı YENİ açarla üzərinə yazır. Burada
    dayansaydıq, operator əl ilə fayl silməli olardı — halbuki sihirbazın bütün
    məqsədi məhz belə əl işlərini aradan qaldırmaqdır.

    Səbəb yenə də EKRANDA deyilir (`_say`), sükutla udulmur: «niyə yenidən
    soruşur?» sualının cavabı görünən yerdə qalmalıdır.
    """
    if not VENDOR_MEMORY_FILE.is_file():
        return None
    try:
        payload = _cipher().decrypt_json(  # type: ignore[attr-defined]
            VENDOR_MEMORY_FILE.read_text(encoding="utf-8").strip(),
            context=_MEMORY_CONTEXT,
        )
    except Exception as exc:
        _say(f"  ⚠ Vendor yaddaşı açılmadı ({type(exc).__name__}) — yenidən soruşulur.\n")
        return None

    ref = str(payload.get("project_ref", ""))
    password = str(payload.get("password", ""))
    if not ref or not password:
        return None
    return VendorCredentials(project_ref=ref, password=password)


def save_vendor(credentials: VendorCredentials) -> None:
    """Vendor açarını `.onboard_config`-ə ŞİFRƏLİ yazır.

    `ensure_machine_key()` yazıdan ƏVVƏL çağırılır — `connection_file.
    save_settings()`-dəki eyni sətir, eyni səbəb (SETUP-2): təmiz maşında DPAPI
    açarı hələ yaranmayıb və onsuz şifrələmə `EncryptionKeyError` ilə dayanardı.
    """
    from src.infrastructure.security.encryption import ensure_machine_key

    ensure_machine_key()
    token = _cipher().encrypt_json(  # type: ignore[attr-defined]
        {
            "version": _MEMORY_VERSION,
            "project_ref": credentials.project_ref,
            "password": credentials.password,
        },
        context=_MEMORY_CONTEXT,
    )
    VENDOR_MEMORY_FILE.write_text(f"{token}\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Sihirbazın axını
# --------------------------------------------------------------------------- #


def _ask_project(
    *,
    ref_label: str,
    credential_label: str,
    reject: Callable[[str], str] | None = None,
) -> VendorCredentials:
    """Bir Supabase layihəsinin (ref + parol) SINANMIŞ açarını toplayır.

    Args:
        ref_label: Project Ref sualının mətni.
        credential_label: Parol sualının mətni. Adında «password» YOXDUR, çünki
            `ruff`-un S106 qaydası belə adlı arqumentin dəyərini «kodda
            bərkidilmiş parol» sayır — bura isə PAROL yox, SUALIN MƏTNİ gəlir.
        reject: Ref-i ƏLAVƏ şərtlə rədd edir (məs. «bu, vendor-un özüdür»);
            BOŞ sətir — qəbul.

    ──────────────────────────────────────────────────────────────────────────
    İKİ DÖVRƏ, ÇÜNKİ İKİ FƏRQLİ SƏHV VAR
    ──────────────────────────────────────────────────────────────────────────
    XARİCİ dövrə ref-i, DAXİLİ dövrə parolu təkrar soruşur. Tək dövrə ilə
    yazılsaydı (əvvəlki forma) səhv parol yazan operator ref-i də yenidən
    yazmalı olurdu — halbuki ref DÜZGÜN idi və bunu server ÖZÜ təsdiqləmişdi
    (`28P01` yalnız ünvana ÇATMIŞ bağlantıda gəlir). Sihirbazın bütün mənası
    məhz bu cür təkrarları aradan qaldırmaqdır.

    Qalan uğursuzluq növləri (`host`, `timeout`, `network`, `other`) XARİCİ
    dövrəyə qayıdır: onların heç biri parolun səhv olduğunu SÜBUT ETMİR, ona
    görə operatora hər iki dəyəri yenidən nəzərdən keçirmək imkanı verilir.

    Vendor və tenant üçün EYNİ funksiya işlənir: fərq yalnız sualın mətnində
    və `reject` şərtindədir. İki nüsxə saxlasaydıq, yuxarıdakı dövrə qaydası
    birində düzələr, digərində köhnə qalardı.
    """
    while True:
        ref = normalise_project_ref(ask(ref_label, validate=_validate_project_ref))
        reason = reject(ref) if reject is not None else ""
        if reason:
            _say(f"     {reason}\n")
            continue

        retry_ref = False
        while not retry_ref:
            credentials = VendorCredentials(
                project_ref=ref, password=ask(credential_label, secret=True)
            )
            _say("  ⏳ Bağlantı test edilir … ")
            failure = probe(credentials.dsn)
            if failure is None:
                _say("✓\n")
                return credentials
            _say("\n")
            _say(f"  {failure.message}\n\n")
            retry_ref = failure.kind != PROBE_CREDENTIAL


def _resolve_vendor() -> VendorCredentials:
    """Vendor açarı: yaddaşdan, yoxdursa BİR DƏFƏ soruşulur və yadda saxlanılır.

    Yaddaşdakı açar da SINANIR. Sınaq olmasaydı, vendor parolu dəyişən gün
    HƏR quraşdırma 2-ci addımda (vendor miqrasiyaları) dayanardı və sihirbaz
    heç vaxt «yenidən soruş» vəziyyətinə keçməzdi — operatorun yeganə çıxışı
    faylı əl ilə silmək olardı.
    """
    stored = load_vendor()
    if stored is not None:
        _say("  Vendor bağlantısı yaddaşdan oxundu.\n")
        _say("  ⏳ Vendor bağlantısı test edilir … ")
        failure = probe(stored.dsn)
        if failure is None:
            _say("✓\n\n")
            return stored
        _say("\n")
        _say(f"  {failure.message}\n")
        _say("  Vendor məlumatları yenidən soruşulur.\n\n")

    _say("  [Vendor bağlantısı YALNIZ İLK DƏFƏ soruşulur — sonra yaddaşdan oxunur]\n")
    credentials = _ask_project(
        ref_label="Vendor (mərkəzi) Supabase Project Ref",
        credential_label="Vendor DB Parolu",
    )
    save_vendor(credentials)
    _say(f"  ✓ Vendor bağlantısı yadda saxlanıldı ({VENDOR_MEMORY_FILE.name})\n\n")
    return credentials


def _resolve_tenant(vendor: VendorCredentials) -> tuple[str, str]:
    """Müştəri layihəsi: `(project_ref, dsn)` — bağlantı SINANMIŞ vəziyyətdə.

    Vendor ref-i ilə üst-üstə düşmə BURADA tutulur (bax `_SAME_PROJECT_MESSAGE`):
    `onboard_new_tenant._reject_invalid_arguments` eyni şeyi yoxlayır, lakin o,
    bütün suallardan SONRA işə düşür və operatoru sıfırdan başlamağa məcbur
    edərdi.
    """
    tenant = _ask_project(
        ref_label="Tenant Supabase Project Ref",
        credential_label="Tenant DB Parolu",
        reject=lambda ref: _SAME_PROJECT_MESSAGE if ref == vendor.project_ref else "",
    )
    return tenant.project_ref, tenant.dsn


def run_wizard() -> WizardAnswers:
    """Bütün sualları soruşur və `WizardAnswers` qaytarır. Baza YAZISI YOXDUR.

    Raises:
        WizardCancelledError: operator Ctrl+C basdı.

    ──────────────────────────────────────────────────────────────────────────
    SUALLARIN SIRASI TƏSADÜFİ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl UCUZ və şəbəkəsiz suallar (ad, e-poçt), sonra ŞƏBƏKƏLİ olanlar
    (vendor, tenant). Tərsinə olsaydı, adı səhv yazan operator iki bağlantı
    sınağını gözlədikdən SONRA səhvi görərdi.

    `anon` açarı SONUNCUDUR və İSTƏYƏ BAĞLIDIR — bax `WizardAnswers.anon_key`
    və `onboard_new_tenant._write_config`: tətbiq onu YALNIZ mühit dəyişənindən
    (`KOMPASOS_SUPABASE_ANON_KEY`) oxuyur, yəni sihirbazın onu tələb etməsi
    quraşdırmanı bloklamaq üçün əsas ola bilməz.
    """
    _say("\nKompasOS Tenant Qurulumu\n")
    _say("─────────────────────────\n")

    company = ask("Şirkət/Test adı")
    # E-poçt SPESİFİKASİYADAKI beş sualdan KƏNARDIR və bilərəkdən əlavə
    # edilib: `license_tenants.company_contact_email` `NOT NULL`-dur
    # (migrations/059) və Emergency Access Recovery-də kimlik təsdiqinin
    # YEGANƏ mənbəyidir. Uydurma dəyər yazmaq həmin bərpa yolunu sükutla
    # ölü edərdi (bax `_create_tenant_row` başlığı) — ona görə soruşulur.
    contact_email = ask("Əlaqə e-poçtu", validate=_validate_email)
    _say("\n")

    vendor = _resolve_vendor()
    tenant_ref, tenant_dsn = _resolve_tenant(vendor)
    anon_key = ask("Tenant Anon Açarı", optional=True)
    _say("\n")

    return WizardAnswers(
        company=company,
        contact_email=contact_email,
        tenant_dsn=tenant_dsn,
        vendor_dsn=vendor.dsn,
        supabase_ref=tenant_ref,
        anon_key=anon_key,
    )


__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "PROBE_CREDENTIAL",
    "VENDOR_MEMORY_FILE",
    "ProbeFailure",
    "VendorCredentials",
    "WizardAnswers",
    "WizardCancelledError",
    "ask",
    "build_direct_dsn",
    "choose",
    "is_interactive",
    "load_vendor",
    "normalise_project_ref",
    "probe",
    "run_wizard",
    "save_vendor",
]
