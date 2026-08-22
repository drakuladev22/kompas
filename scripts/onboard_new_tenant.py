r"""Yeni müştəri quraşdırması — bir əmrlə (TENANT-1 Faza 4).

──────────────────────────────────────────────────────────────────────────────
BU SKRİPT `.exe`-YƏ PAKETLƏNMİR
──────────────────────────────────────────────────────────────────────────────
`src/KompasOS.spec` yalnız `src/` altını yığır; `scripts/` ora düşmür. Bu,
təsadüf deyil: skript VENDOR bazasına YAZIR (`tenants` sətri yaradır) və
müştəri maşınında belə bir imkanın olması lisenziya qapısını mənasız edərdi —
istənilən adam özünə «AKTİV» sətir yaza bilərdi.

`tests/unit/test_packaging_credentials.py` `.spec`-in `scripts/`-i daxil
etmədiyini maşınla qoruyur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SKRİPT — ƏL İLƏ ETMƏK NƏYİ POZURDU
──────────────────────────────────────────────────────────────────────────────
Yeni müştəri qurmaq beş addımdır və hər biri digərinin nəticəsindən asılıdır:
kimlik → vendor qeydi → sxem → seed → konfiqurasiya. Əl ilə görüləndə üçüncü
addımın buraxılması DB-5-in tapdığı vəziyyəti yaradır (32 cədvəl yox, tətbiq
onlara yazmağa çalışır) və qüsur aylarla görünmür.

Skript SIRA-nı kodda saxlayır: hər addım əvvəlkinin uğurunu yoxlayır və
uğursuzluqda DAYANIR. Yarımçıq quraşdırma «işləyir kimi görünən, əslində
pozuq» vəziyyətdən yaxşıdır.

──────────────────────────────────────────────────────────────────────────────
İKİ BAZA, İKİ DSN — QARIŞDIRMAQ MÜMKÜN DEYİL
──────────────────────────────────────────────────────────────────────────────
`--tenant-dsn` müştərinin ÖZ Supabase layihəsi, `--vendor-dsn` isə mərkəzi
lisenziya bazasıdır (DB-3/DB-4). İkisi AYRI arqumentdir və biri digərinin
defoltu DEYİL: eyni dəyəri təsadüfən iki yerə vermək bütün müştəriləri bir
bazaya yığmaq — yəni TENANT-1-in qəti qərarını pozmaq — olardı. Skript
bərabərliyi AÇIQ yoxlayır və dayanır.

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ
──────────────────────────────────────────────────────────────────────────────
    .venv/Scripts/python.exe scripts/onboard_new_tenant.py \
        --company "Embawood" \
        --tenant-dsn "postgresql://kompasos_app....@aws-0-eu.pooler.supabase.com:5432/postgres" \
        --vendor-dsn "postgresql://vendor....@aws-0-eu.pooler.supabase.com:5432/postgres" \
        --supabase-ref "abcdefghijklmnop" \
        --contact-email "it@embawood.az" \
        --out ./embawood

    # Nə ediləcəyini görmək (heç nə yazılmır):
    ... --dry-run

    # ÖZ maşınında sınamaq üçün — konfiqurasiya işlək yerlərə DƏ yazılır:
    ... --dev

──────────────────────────────────────────────────────────────────────────────
İKİ REJİM: `--dev` VƏ BAYRAQSIZ (PROD) — KONFİQURASİYA HARAYA DÜŞÜR
──────────────────────────────────────────────────────────────────────────────
Skript HƏR İKİ rejimdə `--out` qovluğuna arxiv nüsxəsini yazır. Fərq
ƏLAVƏDƏDİR:

* **Bayraqsız (defolt, real müştəri):** yalnız arxiv. Fayllar oradan
  müştərinin maşınına ƏL İLƏ (AnyDesk) köçürülür — bu, FƏRQLİ fiziki maşın
  olduğu üçün avtomatlaşdırıla BİLMƏZ və parol da orada, «Bağlantı Ayarları»
  ekranında daxil edilir (şifrələmə MAŞINA bağlıdır, bax `_write_config`).
* **`--dev` (təchizatçının öz maşını):** arxivə ƏLAVƏ olaraq konfiqurasiya
  tətbiqin FAKTİKİ oxuduğu yerlərə də yazılır və parol YERİNDƏ şifrələnir —
  yəni skript bitən kimi `python main.py` heç bir əlavə addım olmadan açılır
  (bax `_deploy_dev_config`).

Hər iki rejim SONDA öz-özünü yoxlayır (addım 6, `_self_check`): yazılan
konfiqurasiya GERİ OXUNUR və bazaya test-bağlantısı qurulur — «yazıldı»
ilə «işləyir» eyni şey deyil.

──────────────────────────────────────────────────────────────────────────────
YARIMÇIQ ÇÖKMƏDƏN SONRA DAVAM ETMƏ (D4) — `--tenant-id` / `--license-key`
──────────────────────────────────────────────────────────────────────────────
Beş addım BİR-BİRİNDƏN asılıdır (yuxarı bax), amma 1-4-ün HƏR BİRİ artıq
idempotentdir: 1/2 miqrasiya icraçısının ÖZÜ (reyestrə görə), 3/4 isə
`ON CONFLICT (tenant_id) DO NOTHING` ilə. Yeganə çatışmayan hissə — `tenant_id`
və `license_key` HƏR ÇAĞIRIŞDA TƏSADÜFİ yaranırdı, ona görə təkrar işə salmaq
DAVAM ETMİRDİ, YENİ (üçüncü, dördüncü, …) yetim kirayəçi yaradırdı.

`--tenant-id`/`--license-key` verilsə, `uuid4()`/`token_urlsafe()` ƏVƏZİNƏ
ONLAR işlənir — beləcə eyni kimliklə təkrar çağırış yuxarıdakı idempotentlik
sayəsində TƏBİİ ŞƏKİLDƏ "davam edir" (artıq tamamlanmış addımlar sükutla
keçilir, yarımçıq qalan YERİNDƏN başlayır).

──────────────────────────────────────────────────────────────────────────────
`--verify <tenant_id>` — NƏ EDİR, NƏ ETMİR
──────────────────────────────────────────────────────────────────────────────
Bu rejim ƏVVƏL RƏDD EDİLMİŞDİ və rədd səbəbi HƏLƏ DƏ QÜVVƏDƏDİR: vendor
bazası tək başına HEÇ BİR tenant DSN-i saxlamır (DB-3), yəni "bütün
müştəriləri skan et" MÜMKÜN DEYİL və belə bir söz verən rejim yalançı
tamlıq hissi yaradardı.

Buradakı `--verify` həmin şeyi ETMİR: o, skan DEYİL, TƏK bir müştərinin
YOXLANIŞIDIR və operatorun ƏLİNDƏ olan İKİ DSN-i (`--tenant-dsn`,
`--vendor-dsn`) YENİDƏN tələb edir. Fərqi `--tenant-id` ilə təkrar
çağırışdan isə budur: təkrar çağırış YAZIR (idempotent olsa da), `--verify`
isə HEÇ NƏ YAZMIR — yəni "canlı müştəridə vəziyyət necədir?" sualına
quraşdırmaya TOXUNMADAN cavab verir. Dəstək zəngi zamanı lazım olan məhz
budur: yazma icazəsi olmayan halda da işləyir və nəticəsi bir checklist-dir.

Yoxlanan beş halqa (`_verify`): miqrasiya reyestri (061) → əsas cədvəllər →
seed məlumatı (`system_limits`/`feature_toggles`/rol şablonları) → vendor
sətri → yerli konfiqurasiya faylı. Hər biri AYRI sətir kimi çap olunur:
"hamısı OK" ilə "biri çatmır" arasındakı fərq gözlə görünməlidir.

Addım 4-dən (vendor sətri, `license_key` artıq ORADA plaintext saxlanılır —
bax `_create_vendor_row` başlığı) SONRAKI hər `DAYANDI` TAM `license_key`-i
və hazır `--tenant-id`/`--license-key` sətrini çap edir (bax `_resume_hint`) —
operator vendor bazasını əl ilə SQL-lə sorğulamaq məcburiyyətində qalmır.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
# `--dev` və öz-özünü yoxlama `src.`-dən konfiqurasiya YOLLARINI oxuyur (yolu
# burada TƏKRAR hesablamamaq üçün — bax `_deploy_dev_config`). Skript
# repozitoriya kökündən KƏNARDAN da çağırıla bilər (`python scripts/…`), ona
# görə kök `sys.path`-a AÇIQ əlavə olunur — `apply_migrations.py:55` ilə eyni
# sətir, eyni səbəb.
sys.path.insert(0, str(_REPO_ROOT))
_APPLY_MIGRATIONS: Final[Path] = _REPO_ROOT / "scripts" / "apply_migrations.py"

#: Lisenziya açarının uzunluğu (bayt). `secrets.token_urlsafe(32)` ~43 simvol
#: verir — brute-force üçün praktiki olaraq əlçatmazdır və eyni zamanda
#: e-poçtla göndərilə biləcək qədər qısadır.
LICENSE_KEY_BYTES: Final[int] = 32

#: Vendor sətrinin başlanğıc statusu. `ODENIS_GOZLENILIR` — `AKTIV` DEYİL:
#: quraşdırma ilə ödəniş fərqli hadisələrdir və skriptin özünə ödəniş təsdiqi
#: səlahiyyəti vermək lisenziya qapısını yan keçmək olardı.
INITIAL_STATUS: Final[str] = "ODENIS_GOZLENILIR"

#: D4: bu addımdan (vendor sətri COMMIT olunur) sonrakı `DAYANDI` bərpa
#: göstərişi çap edir — bax `_resume_hint`.
VENDOR_ROW_STEP: Final[int] = 4

#: Addımların ÜMUMİ sayı — `[n/TOTAL]` sətrində görünür. Öz-özünü yoxlama
#: (addım 6) AYRICA addımdır, `_write_config`-in içində GİZLƏNMİR: operator
#: «yazıldı» ilə «yazılan geri OXUNDU və bağlantı QURULDU» arasındakı fərqi
#: ekranda GÖRMƏLİDİR — birincinin uğuru ikincisini ZƏMANƏT ETMİR (məs. fayl
#: yazılır, lakin şifrələmə açarı olmadığı üçün geri oxuna bilmir).
TOTAL_STEPS: Final[int] = 6


class OnboardingError(RuntimeError):
    """Addımlardan biri uğursuz oldu — sonrakılar İCRA OLUNMUR."""


def _ensure_utf8_stdio() -> None:
    """Windows-un defolt konsol kodlaşdırmasını (cp1252) DÜZƏLDİR.

    `scripts/apply_migrations.py::_ensure_utf8_stdio`-nun HƏRFİ nüsxəsi —
    səbəb eynidir: bu skript Azərbaycan hərfli (`ə`, `ı`, `İ`) mesajları
    ÖZÜ yazır (məs. sətir "Yeni kirayəçi", "BİTDİ"), `PYTHONIOENCODING`
    təyin edilməyəndə (adi Windows terminalı) həmin yazılar
    `UnicodeEncodeError` ilə çökür. Bu, MÜŞTƏRİ QURAŞDIRMASI skriptidir —
    çökmə beş addımlı onboarding-i yarımçıq (bax `_apply_migrations`-dan
    sonrakı addımlar) buraxa bilər, halbuki əsl səbəb konsol, DB deyil.

    `_apply_migrations`-ın açdığı ALT PROSESƏ ötürülən
    `PYTHONIOENCODING=utf-8` (aşağıda) AYRICA saxlanılır: subprocess ayrı
    prosesdir və mühit dəyişəni ora bu yolla çatır — bu funksiya YALNIZ
    CARİ prosesin (yəni bu skriptin ÖZÜNÜN) axınlarını qoruyur.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            with suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


def _reject_invalid_arguments(args: argparse.Namespace) -> int | None:
    """YAZI axınının giriş şərtləri. Qaytarır: proses kodu, ya da `None` (təmiz).

    `main()`-dən AYRILDI, çünki `--verify` gələndən sonra o funksiya həm
    yoxlama, həm yazı axınını daşıyırdı və hər iki axının şərtləri bir-birinə
    qarışmışdı. Burada YALNIZ yazı axını danışılır — `--verify` bu funksiyaya
    ÇATMIR (`main()` onu daha əvvəl bitirir).
    """
    if not args.company:
        sys.stderr.write("XƏTA: `--company` MƏCBURİDİR (yalnız `--verify` onsuz işləyir).\n")
        return 2

    if args.tenant_dsn == args.vendor_dsn:
        sys.stderr.write(
            "XƏTA: `--tenant-dsn` ilə `--vendor-dsn` eynidir. Hər müştəri AYRI "
            "Supabase layihəsidir (TENANT-1 qəti qərarı) — vendor bazası isə "
            "mərkəzi və paylaşılandır.\n"
        )
        return 2

    # INF-02 (dövrə 1 audit): `--tenant-id`/`--license-key` CÜT tələb olunur.
    # ──────────────────────────────────────────────────────────────────────
    # Əvvəl ikisi MÜSTƏQİL həll olunurdu ("license_key-in mənbəyi tenant_id-dən
    # asılı deyil" fərziyyəsi) — operator addım 4-dən (vendor sətri artıq
    # COMMIT olunub) sonra YALNIZ `--tenant-id`-i köçürüb `--license-key`-i
    # unutsa, bu sətir SƏSSİZCƏ YENİ təsadüfi açar yaradırdı. Addım 3/4-ün
    # `ON CONFLICT (tenant_id) DO NOTHING`-i DB-də köhnə (düzgün) açarı
    # SAXLAYIR, lakin addım 5 (`_write_config`) hər halda bu YENİ, HEÇ YERDƏ
    # saxlanmayan açarı müştəri faylına yazırdı — nəticə paket nə vendor, nə
    # tenant bazası ilə uyğun gəlməyən açar daşıyırdı. Hazırda bunu HEÇ BİR
    # yoxlama tutmur, çünki `license_key_hash`-i doğrulayan yol hələ yoxdur
    # (bax `_create_tenant_row` başlığı) — səhv YALNIZ gələcək bir doğrulama
    # əlavə olunanda üzə çıxardı. İkisi YALNIZ CÜT mənalıdır: BƏRPA rejimi
    # KEÇMİŞ bir çağırışın İKİ dəyərini BİRLİKDƏ təkrarlamaqdır, YARISINI YOX.
    if bool(args.tenant_id) != bool(args.license_key):
        sys.stderr.write(
            "XƏTA: `--tenant-id` və `--license-key` YALNIZ BİRLİKDƏ verilə bilər "
            "(D4 bərpa rejimi). Yalnız birini vermək DB-də SAXLANAN açarla "
            "UYĞUNSUZ, YENİ təsadüfi açar yaradardı və müştəri konfiqurasiyası "
            "SINARDI. `DAYANDI` mesajındakı `_resume_hint` sətrini TAM (hər "
            "iki bayrağı) kopyalayın, ya da heç birini verməyib TAMAMİLƏ YENİ "
            "kirayəçi yaradın.\n"
        )
        return 2
    return None


def _verify_mode(args: argparse.Namespace) -> int | None:
    """`--verify` verilibsə yoxlamanı icra edir; verilməyibsə `None` qaytarır."""
    if not args.verify:
        return None
    try:
        verify_id = uuid.UUID(args.verify)
    except ValueError:
        sys.stderr.write(f"XƏTA: `--verify` keçərli UUID deyil: {args.verify!r}\n")
        return 2
    return _verify(args, verify_id)


def _resolve_identity(args: argparse.Namespace) -> tuple[uuid.UUID, bool] | None:
    """`(tenant_id, davam-edilirmi)` — səhv UUID-də `None` (səbəb çap olunub).

    Bax fayl başlığındakı "D4": `--tenant-id` verilibsə YENİSİ yaranmır, yəni
    təkrar çağırış yarımçıq quraşdırmanı DAVAM ETDİRİR.
    """
    if not args.tenant_id:
        return uuid.uuid4(), False
    try:
        return uuid.UUID(args.tenant_id), True
    except ValueError:
        sys.stderr.write(f"XƏTA: `--tenant-id` keçərli UUID deyil: {args.tenant_id!r}\n")
        return None


def _run_steps(args: argparse.Namespace, tenant_id: uuid.UUID, license_key: str) -> int:
    """Altı addımı SIRA ilə icra edir. Qaytarır: 0 (hamısı OK) və ya 1.

    Addım 4 (vendor sətri) bitəndən SONRA baş verən uğursuzluqda `DAYANDI`
    mesajına bərpa göstərişi əlavə olunur — bax `_resume_hint` və fayl
    başlığındakı "D4" bölməsi.
    """
    last_ok = 0
    try:
        _step(1, "Tenant bazasına miqrasiyalar", lambda: _apply_migrations(args.tenant_dsn))
        last_ok = 1
        _step(
            2,
            "Vendor bazasına miqrasiyalar",
            lambda: _apply_migrations(args.vendor_dsn, vendor=True),
        )
        last_ok = 2
        _step(
            3,
            "Kirayəçi sətri (tenant bazası)",
            lambda: _create_tenant_row(args, tenant_id, license_key),
        )
        last_ok = 3
        _step(
            4,
            "Abunə sətri (vendor bazası)",
            lambda: _create_vendor_row(args, tenant_id, license_key),
        )
        last_ok = 4
        _step(5, "Konfiqurasiya faylları", lambda: _write_config(args, tenant_id, license_key))
        last_ok = 5
        _step(6, "Öz-özünü yoxlama", lambda: _self_check(args, tenant_id))
    except OnboardingError as exc:
        sys.stderr.write(f"\nDAYANDI: {exc}\n")
        if last_ok >= VENDOR_ROW_STEP:
            sys.stderr.write(_resume_hint(tenant_id, license_key))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    args = _parse_args(argv)

    # `--verify` YAZI axınından TAMAMİLƏ ayrıdır: nə şirkət adı, nə əlaqə
    # ünvanı, nə də bərpa bayraqları ona aiddir — ona görə budaq BURADA,
    # bütün yazı-yönümlü yoxlamalardan ƏVVƏL bitir.
    verified = _verify_mode(args)
    if verified is not None:
        return verified

    invalid = _reject_invalid_arguments(args)
    if invalid is not None:
        return invalid

    identity = _resolve_identity(args)
    if identity is None:
        return 2
    tenant_id, resumed = identity
    # `_reject_invalid_arguments`-dakı cüt-yoxlama sayəsində burada YA hər
    # ikisi doludur (bərpa), YA da hər ikisi boşdur (yeni) — `or` budağı artıq
    # yalnız SƏNƏDLƏŞDİRMƏ xarakterlidir, sükutla qarışıq hal yarada BİLMƏZ.
    license_key = args.license_key or secrets.token_urlsafe(LICENSE_KEY_BYTES)

    sys.stdout.write(f"{'Davam edilən' if resumed else 'Yeni'} kirayəçi: {args.company}\n")
    sys.stdout.write(f"  tenant_id   : {tenant_id}\n")
    sys.stdout.write(f"  license_key : {license_key[:8]}… ({len(license_key)} simvol)\n")
    sys.stdout.write(f"  supabase_ref: {args.supabase_ref or '(verilməyib)'}\n\n")

    if args.dry_run:
        sys.stdout.write("--dry-run: heç nə yazılmadı.\n")
        _describe_steps(args)
        return 0

    failed = _run_steps(args, tenant_id, license_key)
    if failed:
        return failed

    # Yekun mətn REJİMƏ görə fərqlidir: dev-də köçürüləcək heç nə YOXDUR
    # (addım 5 onsuz da yerinə yazdı), prod-da isə əsas iş MƏHZ köçürməkdir.
    sys.stdout.write("\nBİTDİ. ")
    if args.dev:
        sys.stdout.write("Konfiqurasiya bu maşında hazırdır:\n")
        sys.stdout.write("  1. `python main.py` — əlavə addım LAZIM DEYİL.\n")
        sys.stdout.write(f"  2. Arxiv nüsxəsi «{args.out}» qovluğundadır.\n")
    else:
        sys.stdout.write("Növbəti addımlar:\n")
        sys.stdout.write(f"  1. «{args.out}» qovluğundakı faylları müştəri maşınına köçürün.\n")
        sys.stdout.write("  2. Tətbiqi açın — İlk Quraşdırma Sihirbazı Root hesabını yaradacaq.\n")
    sys.stdout.write("  3. Ödəniş alındıqdan sonra Vendor Konsolundan statusu AKTIV edin.\n")
    return 0


# --------------------------------------------------------------------------- #
# Addımlar
# --------------------------------------------------------------------------- #


def _step(number: int, title: str, action: object) -> None:
    sys.stdout.write(f"[{number}/{TOTAL_STEPS}] {title} …\n")
    action()  # type: ignore[operator]
    sys.stdout.write(f"[{number}/{TOTAL_STEPS}] {title} — OK\n")


def _resume_hint(tenant_id: uuid.UUID, license_key: str) -> str:
    """D4: addım 4-dən sonrakı çökmədə bərpa üçün TAM açar + hazır bayraqlar.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TAM `license_key` (8 simvol YOX)
    ──────────────────────────────────────────────────────────────────────────
    Addım 4 artıq COMMIT olub — `license_key` VENDOR bazasında plaintext
    saxlanılır (bax `_create_vendor_row` başlığı), yəni açarın özü artıq
    "sızıb" sayılan yerdədir; onu BURADA gizlətmək əlavə təhlükəsizlik
    vermir, əksinə operatoru vendor bazasını əl ilə SQL-lə sorğulamağa
    məcbur edərdi.

    ──────────────────────────────────────────────────────────────────────────
    RİSK — BU SƏTİR YENİDƏN YAZILMAMALI, KOPYALANMALIDIR
    ──────────────────────────────────────────────────────────────────────────
    Aşağıdakı sətir KOPYALANMAQ üçündür, ƏL İLƏ transkript üçün YOX: açar
    43 simvoldur və bir hərfin səhv yazılması `--license-key`-i DƏYİŞDİRMİR
    (`_create_tenant_row`-dakı `ON CONFLICT (tenant_id) DO NOTHING` artıq
    yazılmış `license_key_hash`-i SAXLAYIR), lakin `_write_config` sonrakı
    fayllara MƏHZ səhv yazılan (yeni) açarı yazar — nəticədə müştəri
    faylındakı açar vendor/tenant bazasındakı HEÇ BİRİ ilə uyğun gəlməz və
    bu uyğunsuzluq YALNIZ müştəri lisenziyanı yoxlatmaq istəyəndə üzə çıxar.
    """
    command = f"  --tenant-id {tenant_id} --license-key {license_key}\n"
    return (
        "\nBƏRPA: addım 4 (vendor sətri) ARTIQ YAZILIB — yenidən başlamaq "
        "TƏKRAR abunə sətri yaratmasın deyə eyni kimliklə davam edin.\n"
        f"  tenant_id   : {tenant_id}\n"
        f"  license_key : {license_key}\n"
        "Orijinal əmrə bu İKİ bayrağı ƏLAVƏ EDİB (KOPYALAYARAQ, əl ilə "
        "yenidən yazmadan) təkrar işə salın:\n" + command
    )


def _apply_migrations(dsn: str, *, vendor: bool = False) -> None:
    """Miqrasiya icraçısını çağırır — SIFIRDAN yazılmır.

    İkinci bir tətbiq məntiqi yazmaq `schema_migrations` reyestrini iki
    fərqli yazıcıya bölərdi (migrations/061) və hansının yazdığı sual altında
    qalardı. Ona görə mövcud icraçı ALT PROSES kimi çağırılır və DSN mühit
    dəyişəni ilə ötürülür.

    `PYTHONIOENCODING=utf-8` mühitə AÇIQ yazılır: alt proses AYRI Python
    prosesidir və `_ensure_utf8_stdio()` yalnız CARİ prosesi qoruyur — mühit
    dəyişəni olmasa `apply_migrations.py` öz konsol kodlaşdırmasını yenə
    özü təyin edəcək (o da indi `_ensure_utf8_stdio()` ilə qorunur, bax
    `scripts/apply_migrations.py`), lakin bura AÇIQ yazmaq iki müstəqil
    qoruma qatını EYNİ NİYYƏTLƏ üst-üstə salır — biri pozulsa digəri qalır.
    """
    command = [sys.executable, str(_APPLY_MIGRATIONS)]
    if vendor:
        command.append("--vendor")
    result = subprocess.run(  # noqa: S603 — əmr SABİT massivdir, `shell=False`
        command,
        env={"DATABASE_ADMIN_URL": dsn, "PYTHONIOENCODING": "utf-8", "PATH": _path_env()},
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    sys.stdout.write(_indent(result.stdout))
    if result.returncode != 0:
        raise OnboardingError(f"miqrasiya icraçısı {result.returncode} qaytardı:\n{result.stderr}")


def _create_tenant_row(args: argparse.Namespace, tenant_id: uuid.UUID, license_key: str) -> None:
    """`license_tenants` sətri + `seed_tenant_defaults()` — MÜŞTƏRİNİN bazasında.

    ──────────────────────────────────────────────────────────────────────────
    AÇAR PLAINTEXT SAXLANILMIR — `license_key_hash` ARGON2 GÖZLƏYİR
    ──────────────────────────────────────────────────────────────────────────
    Tenant bazasındakı sütunun adı `license_key`-dir DEYİL,
    `license_key_hash`-dir (schema.sql: «Argon2 hash, plaintext DEYİL»).
    Səbəb: müştəri bazası müştərinin əlindədir və oradan oxunan plaintext açar
    lisenziyanın özünü kopyalamağa imkan verərdi. PLAİNTEXT nüsxə YALNIZ
    VENDOR bazasındadır — orada o, buraxan tərəfin öz qeydidir.

    Hash `argon2.PasswordHasher()` ilə — BİBƏRSİZ (pepper YOX) — qurulur və
    bu, şüurlu seçimdir: `security/hashing.py::PasswordService` `KOMPASOS_HASH_
    PEPPER` tələb edir, həmin bibər isə MÜŞTƏRİNİN maşınına aiddir və bizim
    quraşdırma maşınımızda YOXDUR. Bibərli hash yazsaydıq, o, heç bir maşında
    yoxlana bilməzdi.

    QEYD (mövcud vəziyyət): kod bazasında `license_key_hash`-i YOXLAYAN yol
    hazırda YOXDUR — sütun yalnız yazılır (`PostgresTenantProvisioning` özünə-
    host halında ora `SELF_HOSTED_NO_LICENSE_KEY` nişanı qoyur). Yoxlama
    əlavə ediləndə o, məhz bu formatı — bibərsiz Argon2-ni — gözləməlidir.

    ──────────────────────────────────────────────────────────────────────────
    `company_contact_email` MƏCBURİDİR (migrations/059)
    ──────────────────────────────────────────────────────────────────────────
    Sütun `NOT NULL`-dur və CHECK ilə formatı yoxlanılır. O, Emergency Access
    Recovery-də kimlik təsdiqinin YEGANƏ mənbəyidir — ona görə skript
    `--contact-email` verilməyibsə DAYANIR, uydurma dəyər yazmır.

    `seed_tenant_defaults()` sətirdən SONRA çağırılır: `system_limits`,
    `feature_toggles` və rol şablonları oradan gəlir, əks halda ROOT paneli
    boş qalardı.
    """
    if not args.contact_email:
        raise OnboardingError(
            "`--contact-email` MƏCBURİDİR: `license_tenants.company_contact_email` "
            "`NOT NULL`-dur (migrations/059) və Emergency Access Recovery-də "
            "kimlik təsdiqinin yeganə mənbəyidir."
        )

    import psycopg
    from argon2 import PasswordHasher

    with psycopg.connect(args.tenant_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO kompasos, public")
        cur.execute(
            """
            INSERT INTO license_tenants
                (tenant_id, tenant_name, license_key_hash, status, company_contact_email)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING
            """,
            (
                str(tenant_id),
                args.company,
                PasswordHasher().hash(license_key),
                INITIAL_STATUS,
                args.contact_email,
            ),
        )
        cur.execute("SELECT seed_tenant_defaults(%s)", (str(tenant_id),))
        conn.commit()


def _create_vendor_row(args: argparse.Namespace, tenant_id: uuid.UUID, license_key: str) -> None:
    """`tenants` sətri — MƏRKƏZİ vendor bazasında (DB-3)."""
    import psycopg

    with psycopg.connect(args.vendor_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants
                (tenant_id, company_name, license_key, status, supabase_ref, contact_email)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING
            """,
            (
                str(tenant_id),
                args.company,
                license_key,
                INITIAL_STATUS,
                args.supabase_ref or None,
                args.contact_email or None,
            ),
        )
        conn.commit()


def _write_config(args: argparse.Namespace, tenant_id: uuid.UUID, license_key: str) -> None:
    r"""Müştəri maşınına köçürüləcək faylları hazırlayır.

    PAROL YAZILMIR. `connection.json`-dakı parol DPAPI ilə MAŞIN əhatəsində
    şifrələnir (DB-4 Faza 2) — yəni bizim maşında şifrələnən dəyər müştərinin
    maşınında AÇILA BİLMƏZ. Ona görə skript `connection.template.json`
    hazırlayır və parol quraşdırıcı tərəfindən «Bağlantı Ayarları» ekranından
    daxil edilir; həmin ekran onu YERİNDƏ şifrələyir.

    `installation.json` isə tam hazırdır: onun içində sirr yoxdur (SEC-021).
    """
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "installation.json").write_text(
        json.dumps(
            {"tenant_id": str(tenant_id), "is_licensed": True},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    host, port, database, username = _parse_dsn(args.tenant_dsn)
    (out / "connection.template.json").write_text(
        json.dumps(
            {
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "password_encrypted": "",
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    (out / "OXU-MƏNİ.txt").write_text(
        "KompasOS — quraşdırma təlimatı\n"
        "==============================\n\n"
        f"Müştəri     : {args.company}\n"
        f"tenant_id   : {tenant_id}\n"
        f"license_key : {license_key}\n\n"
        "1. `installation.json` faylını `%PROGRAMDATA%\\KompasOS\\` qovluğuna\n"
        "   köçürün.\n"
        "2. `connection.template.json` faylını eyni qovluğa `connection.json`\n"
        "   adı ilə köçürün.\n"
        "3. Tətbiqi açın. «Bağlantı Ayarları» ekranı parolu soruşacaq — parol\n"
        "   MƏHZ ORADA daxil edilməlidir, çünki o, bu kompüterə bağlı şəkildə\n"
        "   şifrələnir (başqa maşında şifrələnən dəyər burada açılmır).\n"
        "4. Bağlantı uğurlu olduqdan sonra İlk Quraşdırma Sihirbazı Root\n"
        "   hesabını yaradacaq.\n\n"
        "QEYD: lisenziya statusu `ODENIS_GOZLENILIR`-dir. Ödəniş alındıqdan\n"
        "sonra Vendor Konsolundan `AKTIV` edilməlidir.\n",
        encoding="utf-8",
    )
    sys.stdout.write(_indent(f"{out}/installation.json\n{out}/connection.template.json\n"))

    if args.dev:
        _deploy_dev_config(args, tenant_id)


def _deploy_dev_config(args: argparse.Namespace, tenant_id: uuid.UUID) -> None:
    r"""`--dev`: konfiqurasiyanı BU maşının FAKTİKİ oxu yerlərinə yazır.

    ──────────────────────────────────────────────────────────────────────────
    HANSI PROBLEMİ HƏLL EDİR
    ──────────────────────────────────────────────────────────────────────────
    Arxiv qovluğu (`--out`) MÜŞTƏRİ üçündür — `python main.py` ora HEÇ VAXT
    baxmır. Bayraqsız çağırışdan sonra öz maşınında proqramı açan operator
    «işə düşə bilmədi» ekranı görür və səbəbi axtarır: fayllar YARANIB, sadəcə
    tətbiqin AXTARDIĞI yerdə deyil. `--dev` həmin əl-ilə-köçürmə addımını
    aradan qaldırır.

    ──────────────────────────────────────────────────────────────────────────
    HARA YAZILIR — YER KODDAN OXUNUR, BURADA TƏKRARLANMIR
    ──────────────────────────────────────────────────────────────────────────
    İki fayl, iki AYRI mənbə (ikisi də `src/`-dədir və bu skript onları
    ÇAĞIRIR, yolu ÖZÜ hesablamır — əks halda yol qaydası iki yerdə yaşayardı
    və biri dəyişəndə digəri sükutla köhnələrdi):

        * `installation.json` → `src.shared.installation.installation_file()`
          (`%PROGRAMDATA%\KompasOS\`, `KOMPASOS_INSTALLATION_PATH` ilə əvəzlənir);
        * `connection.json`   → `connection_file.save_settings()` (YAZI həmişə
          `%PROGRAMDATA%\KompasOS\`-a gedir; OXU `.exe` yanından başlayır, lakin
          dev rejimində orada — repozitoriya kökündə — belə bir fayl yoxdur).

    ──────────────────────────────────────────────────────────────────────────
    PAROL BURADA ŞİFRƏLƏNİR — `connection.template.json`-DAN FƏRQİ MƏHZ BUDUR
    ──────────────────────────────────────────────────────────────────────────
    Şablon faylı parolu BOŞ saxlayır, çünki DPAPI ilə MAŞIN əhatəsində
    şifrələnən dəyər BAŞQA maşında açıla bilmir (bax `_write_config`). `--dev`
    halında isə hədəf maşın BU maşındır — yəni məhdudiyyət ARADAN QALXIR və
    parol `--tenant-dsn`-dən götürülüb yerində şifrələnə bilər. Nəticə: skript
    bitən kimi `python main.py` heç bir əlavə addım olmadan açılır.
    """
    from src.infrastructure.config.connection_file import (
        ConnectionSettings,
        save_settings,
    )
    from src.shared.installation import installation_file

    identity_path = installation_file()
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(
        json.dumps({"tenant_id": str(tenant_id), "is_licensed": True}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    try:
        connection_path = save_settings(ConnectionSettings.from_dsn(args.tenant_dsn))
    except Exception as exc:
        # `save_settings` şifrələmə açarı olmayan mühitdə (`KOMPASOS_FERNET_KEY`
        # yoxdur VƏ DPAPI əlçatmazdır) qalxır. Bu, YARIMÇIQ vəziyyətdir:
        # `installation.json` artıq yazılıb, `connection.json` yox — ona görə
        # sükutla keçilmir, addım DAYANIR (fayl başlığı, "atomik davranış").
        raise OnboardingError(
            f"`--dev`: `connection.json` yazıla bilmədi — {exc}. "
            f"`{identity_path}` YAZILIB, bağlantı faylı YOX: ya "
            "`KOMPASOS_FERNET_KEY` təyin edin, ya da faylı «Bağlantı Ayarları» "
            "ekranından qurun."
        ) from exc

    sys.stdout.write(_indent(f"{identity_path}\n{connection_path}\n"))


def _self_check(args: argparse.Namespace, tenant_id: uuid.UUID) -> None:
    r"""Yazılanı GERİ OXUYUR və bazaya test-bağlantısı qurur (hər iki rejimdə).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA ADDIM — «YAZILDI» «İŞLƏYİR» DEMƏK DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Beş addımın hamısı uğurla bitə, konfiqurasiya isə yenə də açıla bilməz:
    parol şifrələnib, lakin açar bu maşında yoxdursa deşifrələmə qalxır; JSON
    yazılıb, lakin sahə adı köhnədirsə oxucu `None` qaytarır. Bunların hamısı
    ilk `python main.py` çağırışında «işə düşə bilmədi» ekranı kimi görünür —
    yəni səhv SKRİPTİN sonunda deyil, SAATLAR sonra, başqa kontekstdə üzə
    çıxır. Ona görə skript öz nəticəsini ÖZÜ oxuyur: deşifrələmə həqiqətən
    işləyirmi, `tenant_id` yazdığımız dəyərdirmi, DSN canlı bazaya çatırmı.

    ──────────────────────────────────────────────────────────────────────────
    İKİ REJİM, İKİ MƏNBƏ — LAKİN EYNİ SUAL
    ──────────────────────────────────────────────────────────────────────────
    `--dev`: FAKTİKİ yerlərdəki fayllar oxunur (`load_settings()` parolu
    deşifrələyir) — yəni yoxlanan şey tətbiqin AÇACAĞI faylın ÖZÜdür.

    Bayraqsız (prod): həmin fayllar bu maşında YOXDUR və olmamalıdır da —
    arxivdəki `installation.json` oxunur, parol isə şablonda BOŞDUR (səbəb
    `_write_config`-dədir), ona görə bağlantı `--tenant-dsn` ilə yoxlanılır.
    Bu, «müştəri maşınında da işləyəcək» ZƏMANƏTİ DEYİL (orada parol əl ilə
    daxil ediləcək) — burada yoxlanan DSN-in ÖZÜNÜN doğruluğudur: səhv host
    və ya səhv istifadəçi adı ilə yaradılmış paket müştəriyə getməsin.
    """
    import psycopg

    if args.dev:
        from src.infrastructure.config.connection_file import load_settings
        from src.shared.installation import installation_file

        identity_path = installation_file()
        settings = load_settings()
        if settings is None:
            raise OnboardingError(
                f"`connection.json` geri oxuna bilmədi (axtarılan yer: {identity_path.parent}). "
                "Fayl yazıldı, lakin oxucu onu tanımadı — konfiqurasiya İŞLƏMİR."
            )
        dsn = settings.dsn()
    else:
        identity_path = Path(args.out) / "installation.json"
        dsn = args.tenant_dsn

    try:
        stored = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OnboardingError(f"`{identity_path}` oxuna bilmədi: {exc}") from exc

    if stored.get("tenant_id") != str(tenant_id):
        raise OnboardingError(
            f"`{identity_path}` içindəki tenant_id ({stored.get('tenant_id')}) bu "
            f"quraşdırmanınkı ({tenant_id}) DEYİL — köhnə fayl üzərinə yazılmayıb."
        )

    try:
        with psycopg.connect(dsn, connect_timeout=30) as conn, conn.cursor() as cur:
            cur.execute("SET search_path TO kompasos, public")
            # Sadəcə «bağlantı qurulur» kifayət deyil: addım 3 həmin sətri
            # YAZIB, yəni onu geri oxumaq bütün zənciri (DSN → RLS → seed)
            # bir sorğuda təsdiqləyir.
            cur.execute(
                "SELECT tenant_name FROM license_tenants WHERE tenant_id = %s", (str(tenant_id),)
            )
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise OnboardingError(f"konfiqurasiyadakı DSN ilə bazaya qoşulmaq alınmadı: {exc}") from exc

    if row is None:
        raise OnboardingError(
            f"bazada `license_tenants` sətri TAPILMADI (tenant_id={tenant_id}) — "
            "addım 3 uğurlu görünsə də sətir yerində deyil."
        )
    sys.stdout.write(_indent(f"kirayəçi «{row[0]}» oxundu, konfiqurasiya işləkdir\n"))


#: `--verify`-in "əsas cədvəllər" halqası. TAM SİYAHI DEYİL və olmamalıdır:
#: sxemdə 100-dən çox cədvəl var, hamısını burada saxlamaq siyahını sxemin
#: İKİNCİ, əl ilə yenilənən nüsxəsinə çevirərdi (DB-1-in dərsi). Bunlar
#: SEÇİLMİŞ göstəricilərdir — hər biri AYRI miqrasiya dalğasından gəlir, yəni
#: biri yoxdursa zəncirin harada kəsildiyi dərhal görünür.
_CORE_TABLES: Final[tuple[str, ...]] = (
    "license_tenants",  # 001 — kimlik
    "positions",  # 001 — rol iyerarxiyası
    "employees",  # 001 — işçi
    "fines",  # 002 — cərimə axını
    "system_limits",  # 022 — Root parametrləri
    "feature_toggles",  # 022 — modul açarları
    "audit_logs",  # 001 — audit
    "schema_migrations",  # 061 — reyestrin ÖZÜ
)

#: Seed halqasının minimum gözləntisi. Dəqiq say YOX (o, hər miqrasiya ilə
#: dəyişir və testi hər dəfə yeniləmək lazım gələrdi) — sıfırdan böyük olması
#: yoxlanılır: `seed_tenant_defaults()` çağırılmayıbsa HƏR ÜÇÜ sıfırdır.
_SEEDED_TABLES: Final[tuple[str, ...]] = ("system_limits", "feature_toggles", "positions")


def _verify(args: argparse.Namespace, tenant_id: uuid.UUID) -> int:
    """Mövcud kirayəçini YOXLAYIR — heç nə yazmır. Qaytarır: proses kodu.

    Beş halqanın hər biri AYRI sətir kimi çap olunur (`OK` / `ÇATMIR`), sonda
    yekun verilir. Bir halqanın uğursuzluğu qalanlarını DAYANDIRMIR: dəstək
    zəngində "hansı biri sınıb" sualının cavabı TAM mənzərə tələb edir —
    birinci xətada dayanmaq operatoru ikinci dəfə çağırmağa məcbur edərdi.
    """
    import psycopg

    failures: list[str] = []

    def _line(ok: bool, title: str, detail: str) -> None:
        sys.stdout.write(f"  [{'OK    ' if ok else 'ÇATMIR'}] {title}: {detail}\n")
        if not ok:
            failures.append(title)

    sys.stdout.write(f"Kirayəçi yoxlaması: {tenant_id}\n")

    try:
        with psycopg.connect(args.tenant_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
            cur.execute("SET search_path TO kompasos, public")

            # 1. MİQRASİYA REYESTRİ (061) — DB-5-in tapdığı qüsurun qapısı:
            # tətbiq olunmayan miqrasiya "cədvəl yoxdur" kimi AYLARLA gizlənir.
            expected = {
                path.name
                for path in sorted(
                    (_REPO_ROOT / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql")
                )
            }
            cur.execute("SELECT to_regclass('kompasos.schema_migrations')")
            row = cur.fetchone()
            if row is None or row[0] is None:
                _line(False, "Miqrasiya reyestri", "cədvəl YOXDUR (061 tətbiq olunmayıb)")
            else:
                cur.execute("SELECT filename FROM schema_migrations")
                applied = {name for (name,) in cur.fetchall()}
                missing = sorted(expected - applied)
                _line(
                    not missing,
                    "Miqrasiya reyestri",
                    f"{len(applied)}/{len(expected)} tətbiq olunub"
                    + (f", çatmayan: {', '.join(missing[:5])}" if missing else ""),
                )

            # 2. ƏSAS CƏDVƏLLƏR — `to_regclass` NULL qaytarırsa cədvəl yoxdur.
            absent = []
            for table in _CORE_TABLES:
                cur.execute("SELECT to_regclass(%s)", (f"kompasos.{table}",))
                found = cur.fetchone()
                if found is None or found[0] is None:
                    absent.append(table)
            _line(
                not absent,
                "Əsas cədvəllər",
                f"{len(_CORE_TABLES) - len(absent)}/{len(_CORE_TABLES)} mövcuddur"
                + (f", yoxdur: {', '.join(absent)}" if absent else ""),
            )

            # 3. SEED — `seed_tenant_defaults()` çağırılıbmı. Sətirlər HƏMİŞƏ
            # kirayəçiyə görə süzülür: qlobal şablon sətirləri (`tenant_id IS
            # NULL`, məs. rol şablonları) SAYILSAYDI, seed edilməmiş kirayəçi
            # də "dolu" görünərdi.
            counts: dict[str, int] = {}
            for table in _SEEDED_TABLES:
                cur.execute(
                    f"SELECT count(*) FROM {table} WHERE tenant_id = %s",  # noqa: S608 — ad SABİT siyahıdandır
                    (str(tenant_id),),
                )
                counted = cur.fetchone()
                counts[table] = int(counted[0]) if counted else 0
            empty = sorted(name for name, value in counts.items() if value == 0)
            _line(
                not empty,
                "Seed məlumatı",
                ", ".join(f"{name}={value}" for name, value in counts.items())
                + (f" — BOŞ: {', '.join(empty)}" if empty else ""),
            )

            # 4. KİRAYƏÇİ SƏTRİ — addım 3-ün nəticəsi.
            cur.execute(
                "SELECT tenant_name, status FROM license_tenants WHERE tenant_id = %s",
                (str(tenant_id),),
            )
            tenant_row = cur.fetchone()
            _line(
                tenant_row is not None,
                "Kirayəçi sətri",
                f"«{tenant_row[0]}», status {tenant_row[1]}" if tenant_row else "TAPILMADI",
            )
    except psycopg.Error as exc:
        _line(False, "Tenant bazası", f"qoşulmaq alınmadı — {exc}")

    # 5. VENDOR SƏTRİ — AYRI bazadır, ona görə AYRI bağlantı: birincinin
    # uğursuzluğu ikincinin yoxlanmasını əngəlləməməlidir (ikisi müstəqil
    # şəkildə sına bilər və hansının sındığı MƏHZ bu ayrılıqla görünür).
    try:
        with psycopg.connect(args.vendor_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT company_name, status FROM tenants WHERE tenant_id = %s", (str(tenant_id),)
            )
            vendor_row = cur.fetchone()
            _line(
                vendor_row is not None,
                "Vendor sətri",
                f"«{vendor_row[0]}», status {vendor_row[1]}" if vendor_row else "TAPILMADI",
            )
    except psycopg.Error as exc:
        _line(False, "Vendor bazası", f"qoşulmaq alınmadı — {exc}")

    # 6. YERLİ KONFİQURASİYA — YALNIZ `--dev` maşınında mənalıdır. Bayraqsız
    # halda bu maşında fayl OLMAMALIDIR, ona görə yoxluğu XƏTA sayılmır.
    _verify_local_config(tenant_id, dev=args.dev, failures=failures)

    if failures:
        sys.stdout.write(f"\nNƏTİCƏ: {len(failures)} halqa ÇATMIR — {', '.join(failures)}\n")
        return 1
    sys.stdout.write("\nNƏTİCƏ: bütün halqalar yerindədir.\n")
    return 0


def _verify_local_config(tenant_id: uuid.UUID, *, dev: bool, failures: list[str]) -> None:
    """`--verify`-in altıncı sətri: bu maşındakı konfiqurasiya faylı.

    `--dev` VERİLMƏYİBSƏ bu halqa ÜMUMİYYƏTLƏ yoxlanmır — fayl mövcud olsa
    DA. Səbəb ölçülmüş haldır: təchizatçının maşınında ÖZ inkişaf
    kirayəçisinin `installation.json`-u onsuz da durur, yəni MÜŞTƏRİ
    kirayəçisini yoxlayan hər prod çağırışı «fayl BAŞQA kirayəçinindir» deyə
    YALANÇI-QIRMIZI verərdi. Operator qırmızı sətri saymağı öyrənən kimi
    yoxlamanın MƏNASI ölür — ona görə sətir «aid deyil» kimi çap olunur və
    `failures`-a DÜŞMÜR.
    """
    from src.infrastructure.config.connection_file import load_settings
    from src.shared.installation import installation_file

    if not dev:
        sys.stdout.write("  [—     ] Yerli konfiqurasiya: aid deyil (`--dev` verilməyib)\n")
        return

    path = installation_file()
    if not path.exists():
        sys.stdout.write(f"  [ÇATMIR] Yerli konfiqurasiya: {path} YOXDUR\n")
        failures.append("Yerli konfiqurasiya")
        return

    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stdout.write(f"  [ÇATMIR] Yerli konfiqurasiya: {path} oxunmur — {exc}\n")
        failures.append("Yerli konfiqurasiya")
        return

    if stored.get("tenant_id") != str(tenant_id):
        sys.stdout.write(
            f"  [ÇATMIR] Yerli konfiqurasiya: fayl BAŞQA kirayəçinindir "
            f"({stored.get('tenant_id')})\n"
        )
        failures.append("Yerli konfiqurasiya")
        return

    settings = load_settings()
    if settings is None:
        sys.stdout.write("  [ÇATMIR] Yerli konfiqurasiya: `connection.json` oxunmur\n")
        failures.append("Yerli konfiqurasiya")
        return

    sys.stdout.write(f"  [OK    ] Yerli konfiqurasiya: {settings.host}/{settings.database}\n")


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Yeni KompasOS müştərisi qurur (TENANT-1 Faza 4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # `--verify` rejimində şirkət adı LAZIM DEYİL (heç nə yazılmır, ad isə
    # yalnız YAZI addımlarında işlənir) — ona görə `required=True` DEYİL və
    # məcburiliyi `main()` rejimə görə yoxlayır.
    parser.add_argument("--company", default="", help="şirkət adı, məs. «Embawood»")
    parser.add_argument("--tenant-dsn", required=True, help="MÜŞTƏRİNİN öz Supabase DSN-i")
    parser.add_argument("--vendor-dsn", required=True, help="MƏRKƏZİ vendor bazasının DSN-i")
    parser.add_argument("--supabase-ref", default="", help="müştəri layihəsinin ref-i")
    # MƏCBURİDİR (bax `_create_tenant_row`), lakin `required=True` DEYİL:
    # `--dry-run` yolunun onsuz da işləməsi lazımdır ki, quraşdırıcı
    # addımları əvvəlcədən görə bilsin.
    parser.add_argument(
        "--contact-email", default="", help="şirkət əlaqə ünvanı (yazma üçün MƏCBURİ)"
    )
    parser.add_argument("--out", default="./onboarding", help="konfiqurasiya qovluğu")
    parser.add_argument("--dry-run", action="store_true", help="heç nə yazma, addımları göstər")
    # `--dev`: bax `_deploy_dev_config`. Defolt YOXDUR (prod) — bayraq
    # BU maşına yazır, yəni səhvən müştəri quraşdırmasında verilsə
    # təchizatçının öz `%PROGRAMDATA%`-sını müştərinin bazasına bağlayardı.
    parser.add_argument(
        "--dev",
        action="store_true",
        help="konfiqurasiyanı BU maşının işlək yerlərinə də yaz (öz inkişaf mühiti)",
    )
    parser.add_argument(
        "--verify",
        default="",
        metavar="TENANT_ID",
        help="mövcud kirayəçini YOXLA (heç nə yazılmır) — bax `_verify`",
    )
    # D4: yarımçıq çökmədən sonra DAVAM ETMƏ — bax fayl başlığı. Verilməzsə
    # köhnə davranış (təsadüfi `uuid4()`/`token_urlsafe()`) DƏYİŞMİR.
    parser.add_argument(
        "--tenant-id",
        default="",
        help="əvvəlki (yarımçıq) çağırışın tenant_id-si — verilsə YENİSİ yaranmır",
    )
    parser.add_argument(
        "--license-key",
        default="",
        help="əvvəlki çağırışın DAYANDI mesajında çap olunan tam açar — verilsə YENİSİ yaranmır",
    )
    return parser.parse_args(argv)


def _describe_steps(args: argparse.Namespace) -> None:
    sys.stdout.write("Addımlar:\n")
    sys.stdout.write("  1. Tenant bazasına BÜTÜN miqrasiyalar (apply_migrations.py)\n")
    sys.stdout.write("  2. Vendor bazasına vendor miqrasiyaları (--vendor)\n")
    sys.stdout.write("  3. `license_tenants` sətri → seed trigger-ləri işə düşür\n")
    sys.stdout.write("  4. Vendor `tenants` sətri (status: ODENIS_GOZLENILIR)\n")
    sys.stdout.write(f"  5. Konfiqurasiya faylları → {args.out}\n")
    if args.dev:
        from src.infrastructure.config.connection_file import (
            connection_file_path,
        )
        from src.shared.installation import installation_file

        sys.stdout.write(f"     + `--dev`: {installation_file()}\n")
        sys.stdout.write(f"     + `--dev`: {connection_file_path()} (parol şifrələnmiş)\n")
    sys.stdout.write("  6. Öz-özünü yoxlama: konfiqurasiya geri oxunur, bazaya qoşulur\n")


def _parse_dsn(dsn: str) -> tuple[str, int, str, str]:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(dsn)
    return (
        parsed.hostname or "",
        parsed.port or 5432,
        (parsed.path or "/").lstrip("/") or "postgres",
        unquote(parsed.username or ""),
    )


def _path_env() -> str:
    """Alt prosesə ötürülən `PATH`.

    Mühit TAMAMİLƏ əvəzlənir (DSN sızmasın deyə), lakin `PATH` olmadan
    Windows-da `python.exe` öz DLL-lərini tapa bilmir.
    """
    import os

    return os.environ.get("PATH", "")


def _indent(text: str) -> str:
    return "".join(f"      {line}\n" for line in text.splitlines() if line.strip())


if __name__ == "__main__":  # pragma: no cover — CLI giriş nöqtəsi
    raise SystemExit(main())
