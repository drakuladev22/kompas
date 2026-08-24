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
İSTİFADƏ — DEFOLT REJİM SİHİRBAZDIR (ONBOARD-FINAL)
──────────────────────────────────────────────────────────────────────────────
    .venv/Scripts/python.exe scripts/onboard_new_tenant.py

Arqumentsiz çağırış `scripts/onboard_wizard.py`-i işə salır: şirkət adı,
əlaqə e-poçtu, vendor Project Ref + parol (YALNIZ İLK DƏFƏ), tenant Project
Ref + parol + `anon` açarı soruşulur, DSN-lər ÖZÜ qurulur (BİRBAŞA format —
səbəb sihirbazın başlığındadır) və `--dev` avtomatik qalxır, yəni skript
bitən kimi `python -m src.main` heç bir əlavə addım olmadan açılır.

──────────────────────────────────────────────────────────────────────────────
BAYRAQLI YOL QALIR — SİLİNMƏSİ NƏYİ POZARDI
──────────────────────────────────────────────────────────────────────────────
Aşağıdakı forma GERİDƏ-UYUMLU olaraq saxlanılır və bir halda YEGANƏ çıxışdır:
`db.<ref>.supabase.co` bəzi layihələrdə yalnız IPv6 elan edir və IPv4 şəbəkədə
sihirbazın qurduğu DSN çatmır. Həmin halda operator Supabase-in «Connection
pooling» sətrini `--tenant-dsn` ilə əl ilə verir (sihirbaz bunu xəta mesajında
AÇIQ deyir — bax `onboard_wizard._humanise`).

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
import re
import secrets
import subprocess
import sys
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Final, NamedTuple

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

#: `--out`-un defoltu. SABİT kimi ayrıldı, çünki İKİ yerdə oxunur: `argparse`
#: defoltunda və `_run_wizard_into`-da (operator dəyəri DƏYİŞDİRİBmi sualında).
#: İki nüsxə olsaydı, defolt dəyişən gün sihirbaz operatorun `--out`-unu
#: sükutla əzərdi.
DEFAULT_OUT_DIR: Final[str] = "./onboarding"


#: Dublikat aşkarlananda `--allow-duplicate` verilməyibsə qaytarılan kod.
#: `1` (addım uğursuzluğu) və `2` (istifadə səhvi) DEYİL: bu, nə xəta, nə də
#: səhv əmrdir — skript SORUŞA BİLMƏDİYİ üçün TƏHLÜKƏSİZ tərəfə keçib
#: dayanıb. Örtük skript üç halı bir-birindən ayıra bilməlidir.
DUPLICATE_EXIT_CODE: Final[int] = 3

#: DSN-in parol hissəsini tapan naxış — `_redact_dsn`.
_DSN_PASSWORD: Final[re.Pattern[str]] = re.compile(r"(?<=://)([^:/@\s]+):([^@\s]+)(?=@)")


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

    # ONBOARD-FINAL: `argparse`-dən köçən məcburilik. Şərt REJİMƏ bağlıdır —
    # bura çatan çağırış YA sihirbazdan gəlir (hər iki DSN doludur), YA da
    # bayraqlıdır. Deməli yeganə səhv hal YARIMÇIQ bayraq dəstidir: birini
    # verib digərini unutmaq. Bu, aşağıdakı «ikisi eynidir» yoxlamasından
    # ƏVVƏL tutulmalıdır, əks halda iki BOŞ sətir «eynidir» kimi görünər və
    # operator tamamilə yanlış səbəb oxuyardı.
    if not args.tenant_dsn or not args.vendor_dsn:
        missing = "--tenant-dsn" if not args.tenant_dsn else "--vendor-dsn"
        sys.stderr.write(
            f"XƏTA: `{missing}` verilməyib. İkisi YALNIZ BİRLİKDƏ mənalıdır — "
            "quraşdırma HƏM müştəri, HƏM vendor bazasına yazır (DB-3).\n"
            "Bayraqları tamamlayın, ya da HEÇ BİRİNİ verməyib sihirbazı işə "
            "salın: `python scripts/onboard_new_tenant.py`\n"
        )
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
    """`--verify` verilibsə yoxlamanı icra edir; verilməyibsə `None` qaytarır.

    ──────────────────────────────────────────────────────────────────────────
    İKİ FORMA, BİR YOXLAMA (ONBOARD-FINAL Faza 4)
    ──────────────────────────────────────────────────────────────────────────
    `--verify <UUID>` — KÖHNƏ forma, DƏYİŞMƏYİB: hər iki DSN bayraqla verilir.
    O, YEGANƏ işləyən yoldur, əgər kirayəçi BU maşında quraşdırılmayıbsa
    (başqa təchizatçı maşınından, ya da müştərinin öz maşınında).

    `--verify <ad>` — YENİ forma: DSN-lər soruşulmur, çünki onlar ONSUZ DA
    bu maşındadır — tenant `configs/<slug>.config` arxivində, vendor isə
    `.onboard_config` yaddaşında. Dəstək zəngi zamanı operatorun əlində
    olan YEGANƏ şey müştərinin ADIdır; DSN-i axtarmağa göndərmək yoxlamanı
    məhz ən lazım olan anda işlətməz edərdi.

    Ad forması UUID-i ƏVƏZLƏMİR, ona ƏLAVƏDİR: aşağıdakı budaq əvvəlcə UUID
    sınayır və uğurlu olarsa köhnə yola HEÇ NƏ dəyişmədən keçir.
    """
    if not args.verify:
        return None
    try:
        verify_id = uuid.UUID(args.verify)
    except ValueError:
        resolved = _resolve_verify_by_name(args)
        if isinstance(resolved, int):
            return resolved
        verify_id = resolved
    return _verify(args, verify_id)


def _resolve_verify_by_name(args: argparse.Namespace) -> uuid.UUID | int:
    """`--verify <ad>` — arxivdən kimliyi və hər iki DSN-i qurur.

    Qaytarır: `tenant_id`, ya da proses kodu (səbəb ARTIQ çap olunub).

    ──────────────────────────────────────────────────────────────────────────
    PAROL MÜVƏQQƏTİ FAYLA YAZILMIR
    ──────────────────────────────────────────────────────────────────────────
    Arxivin `connection` bloku `connection.json`-un məzmununun EYNİSİDİR, lakin
    FAYL deyil. `load_settings()` fayl gözlədiyi üçün ilk baxışda «bloku
    müvəqqəti fayla yaz» həlli görünür — o isə ŞİFRƏLƏNMİŞ parolu diskdə
    ÜÇÜNCÜ nüsxəyə çıxarardı və silinməsi `finally` blokunun düzgünlüyündən
    asılı olardı. Ona görə `connection_file.settings_from_payload()` əlavə
    edildi: blok BİRBAŞA, diskə toxunmadan oxunur.

    ──────────────────────────────────────────────────────────────────────────
    `--dev` AVTOMATİK TƏYİN OLUNUR — VƏ BU, MƏNALI FƏRQDİR
    ──────────────────────────────────────────────────────────────────────────
    `_verify_local_config` «yerli konfiqurasiya» halqasını YALNIZ `--dev`-də
    yoxlayır (səbəbi onun başlığındadır: yalançı-qırmızı). Ad forması bu
    sualın cavabını ÖZÜ bilir: yoxlanan kirayəçi HAZIRDA AKTİVdirsə, yerli
    fayllar MƏHZ onundur və halqa mənalıdır; aktiv deyilsə, diskdəki fayllar
    BAŞQA kirayəçinindir və halqa yalançı-qırmızı verərdi.
    """
    from scripts.switch import ACTIVE_MARKER, CONFIGS_DIR, SwitchError, load_bundle

    try:
        bundle = load_bundle(args.verify)
    except SwitchError as exc:
        sys.stderr.write(f"XƏTA: {exc}\n")
        return 2

    installation = bundle.get("installation")
    tenant_id = str(installation.get("tenant_id", "")) if isinstance(installation, dict) else ""
    try:
        verify_id = uuid.UUID(tenant_id)
    except ValueError:
        sys.stderr.write(
            f"XƏTA: «{bundle.get('slug')}» arxivində keçərli `tenant_id` yoxdur "
            "— arxiv korlanıb və ya köhnə formatdadır.\n"
        )
        return 2

    tenant_dsn = _tenant_dsn_from_bundle(bundle)
    if not tenant_dsn:
        return 2
    args.tenant_dsn = tenant_dsn

    from scripts.onboard_wizard import load_vendor

    stored_vendor = load_vendor()
    if stored_vendor is None:
        sys.stderr.write(
            "XƏTA: vendor bağlantısı yaddaşda yoxdur (`.onboard_config`). Sihirbazı "
            "bir dəfə işə salın, ya da `--verify <UUID>` + `--vendor-dsn` işlədin.\n"
        )
        return 2
    args.vendor_dsn = stored_vendor.dsn

    marker = CONFIGS_DIR / ACTIVE_MARKER
    active = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    args.dev = active == str(bundle.get("slug"))

    sys.stdout.write(f"Arxiv: configs/{bundle.get('slug')}.config")
    sys.stdout.write(" (HAZIRDA AKTİV)\n" if args.dev else " (aktiv deyil)\n")
    return verify_id


def _tenant_dsn_from_bundle(bundle: dict[str, object]) -> str:
    """Arxivin `connection` blokundan tenant DSN-i; alınmasa BOŞ sətir.

    Səbəb HƏR halda EKRANDA deyilir — boş qayıdış «naməlum xəta» demək
    deyil, «səbəb artıq çap olundu» deməkdir. `_resolve_verify_by_name`-dən
    AYRILDI, çünki orada beş müstəqil dayanma səbəbi toplanmışdı və hər
    birinin öz mesajı var; bir funksiyada onlar bir-birini gizlədirdi.
    """
    from src.infrastructure.config.connection_file import (
        ConnectionFileError,
        settings_from_payload,
    )

    slug = bundle.get("slug")
    connection = bundle.get("connection")
    if not isinstance(connection, dict):
        sys.stderr.write(
            f"XƏTA: «{slug}» arxivində `connection` bloku yoxdur — tenant bazasına "
            "qoşulmaq mümkün deyil. `--verify <UUID>` formasını işlədib "
            "`--tenant-dsn`/`--vendor-dsn` verin.\n"
        )
        return ""

    try:
        settings = settings_from_payload(connection, source=f"configs/{slug}.config")
    except ConnectionFileError as exc:
        sys.stderr.write(f"XƏTA: arxivdəki parol açıla bilmədi — {exc}\n")
        return ""

    if not settings.password:
        # Bayraqsız («real müştəri») onboarding parolu QƏSDƏN yazmır — bax
        # `_write_config`. Belə arxivlə yoxlama mümkün deyil və bunu SÜKUTLA
        # «bağlantı sınıb» kimi göstərmək səbəbi gizlətmək olardı.
        sys.stderr.write(
            f"XƏTA: «{slug}» arxivində PAROL yoxdur (bayraqsız onboarding belə "
            "yazır). `--verify <UUID>` + `--tenant-dsn` işlədin.\n"
        )
        return ""
    return settings.dsn()


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
        # `_redact_dsn` BURADA da tətbiq olunur, `_apply_migrations`-dakına
        # ƏLAVƏ: istisna mətni alt prosesdən KƏNAR mənbədən də gələ bilər
        # (məs. `psycopg`-nin öz bağlantı xətası, `_create_tenant_row`).
        # Bir qat buraxılsa parol məhz həmin yoldan ekrana düşərdi.
        sys.stderr.write(f"\nDAYANDI: {_redact_dsn(str(exc))}\n")
        sys.stderr.write(_partial_state_report(last_ok, args, tenant_id))
        if last_ok >= VENDOR_ROW_STEP:
            sys.stderr.write(_resume_hint(tenant_id, license_key))
        return 1
    return 0


class ExistingTenant(NamedTuple):
    """Vendor bazasında ARTIQ mövcud olan kirayəçi sətri.

    Attributes:
        tenant_id: Mövcud kimlik — davam edilərsə `--tenant-id` kimi işlənir.
        company_name: Yazıldığı kimi (böyük/kiçik hərf saxlanılır).
        license_key: Plaintext açar — vendor bazasında ONSUZ DA belə saxlanılır
            (`_create_vendor_row` başlığı), yəni burada oxumaq yeni sızma
            yaratmır və `--license-key` bərpasını ƏL İLƏ SQL-siz mümkün edir.
        status: `AKTIV` / `ODENIS_GOZLENILIR` / `DEAKTIV`.
        supabase_ref: Müştəri layihəsinin ref-i; boş ola bilər.
    """

    tenant_id: str
    company_name: str
    license_key: str
    status: str
    supabase_ref: str


def _detect_existing_tenant(args: argparse.Namespace) -> list[ExistingTenant]:
    """Vendor bazasında EYNİ şirkət adı və ya EYNİ Supabase ref-i axtarır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ VENDOR BAZASI — YERLİ `configs/` ARXİVİ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    `configs/<slug>.config` yalnız BU maşında quraşdırılmışları bilir. Eyni
    müştərini ikinci bir təchizatçı maşınından quraşdıran adam yerli arxivdə
    HEÇ NƏ tapmazdı və dublikat sükutla yaranardı. Vendor bazası isə TƏK
    mərkəzdir (DB-3) — sual məhz orada mənalıdır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ İKİ MEYAR — AD **VƏ** `supabase_ref`
    ──────────────────────────────────────────────────────────────────────────
    Ad İNSANIN yazdığıdır: «Yataş» ilə «Yatas MMC» eyni müştəri ola bilər və
    ad meyarı onları TUTMUR. `supabase_ref` isə MAŞININ dəyəridir və bir
    Supabase layihəsi bir kirayəçidir — yəni eyni ref ilə ikinci sətir
    YARATMAQ hər halda səhvdir, adı nə olursa olsun. İki meyar bir-birinin
    kor nöqtəsini örtür.

    ──────────────────────────────────────────────────────────────────────────
    CƏDVƏL YOXDURSA — «DUBLİKAT YOXDUR», XƏTA DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Bu yoxlama addım 2-dən (vendor miqrasiyaları) ƏVVƏL işləyir, yəni TƏMİZ
    vendor bazasında `tenants` cədvəli hələ MÖVCUD OLMAYA bilər. Belə halda
    cavab aydındır: dublikat ola bilməz, çünki heç bir sətir yoxdur.
    """
    import psycopg

    query = """
        SELECT tenant_id, company_name, license_key, status, COALESCE(supabase_ref, '')
        FROM tenants
        WHERE lower(company_name) = lower(%s)
           OR (%s <> '' AND supabase_ref = %s)
        ORDER BY installed_at
    """
    try:
        with psycopg.connect(args.vendor_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
            cur.execute(query, (args.company, args.supabase_ref, args.supabase_ref))
            rows = cur.fetchall()
    except psycopg.errors.UndefinedTable:
        return []
    except psycopg.Error as exc:
        # Yoxlama APARILA BİLMƏDİ — bu, «dublikat yoxdur» DEMƏK DEYİL, ona
        # görə sükutla keçilmir. Lakin DAYANDIRMIR da: vendor bazasına
        # qoşulmaq mümkün deyilsə addım 2 onsuz da dayanacaq və vendor
        # bazasına HEÇ NƏ yazılmayacaq — yəni yetim sətir yarana bilməz.
        sys.stdout.write(
            f"  XƏBƏRDARLIQ: dublikat yoxlaması aparıla bilmədi — "
            f"{_redact_dsn(str(exc).splitlines()[0])}\n"
        )
        return []
    return [ExistingTenant(str(row[0]), row[1], row[2], row[3], row[4]) for row in rows]


def _apply_duplicate_policy(args: argparse.Namespace) -> int | None:
    """İdempotentlik qapısı. Qaytarır: proses kodu, ya da `None` (davam).

    Davam qərarı verilərsə `args.tenant_id`/`args.license_key` DOLDURULUR —
    yəni qərar MÖVCUD D4 bərpa mexanizminə çevrilir və `_resolve_identity`
    ondan sonra heç nə bilmədən işini görür. Yeni bir «davam rejimi» yazmaq
    eyni davranışın İKİNCİ nüsxəsini yaradardı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SORUŞULUR, NİYƏ ÖZBAŞINA QƏRAR VERİLMİR
    ──────────────────────────────────────────────────────────────────────────
    İki qərarın hər ikisi MƏNALIDIR və fərqi YALNIZ operator bilir:
    «Yataş» adını təkrar yazmaq ya EYNİ müştərinin təkrar quraşdırmasıdır
    (davam), ya da eyni adlı İKİNCİ filial/şirkətdir (yeni). Skript birini
    seçsəydi, digər halda ya mövcud müştərinin konfiqurasiyası əzilər, ya da
    ödənişi izlənməyən YETİM sətir yaranardı.
    """
    if args.tenant_id:
        # AÇIQ bərpa (`--tenant-id`): operator qərarı ARTIQ verib, sual
        # təkrarı mənasızdır və bu yolda dublikat GÖZLƏNİLƏNDİR.
        return None

    matches = _detect_existing_tenant(args)
    if not matches:
        return None

    sys.stdout.write("\n  ⚠ Bu müştəri vendor bazasında ARTIQ mövcuddur:\n")
    for row in matches:
        ref = row.supabase_ref or "(ref yoxdur)"
        sys.stdout.write(f"      «{row.company_name}» — {row.tenant_id}, {row.status}, {ref}\n")

    if args.dry_run:
        # `--dry-run` NƏ SORUŞUR, NƏ DAYANIR — yalnız XƏBƏRDARLIQ edir.
        # ──────────────────────────────────────────────────────────────────
        # Bu rejimin müqaviləsi «heç nə yazma, nə olacağını göstər»dir. Qapının
        # məqsədi isə YETİM KİRAYƏÇİ yaranmasının qarşısını almaqdır — dry-run
        # heç nə yazmadığına görə orada yetim sətir MÜMKÜN DEYİL, yəni
        # dayanmağın qoruyucu faydası SIFIRDIR, zərəri isə realdır: operator
        # addım siyahısını görə bilmir (qeyri-interaktiv mühitdə exit 3) və ya
        # sadəcə baxmaq istəyərkən qərar verməyə məcbur edilir.
        #
        # Xəbərdarlıq isə SAXLANILIR: «bu ad artıq mövcuddur» məlumatı məhz
        # əvvəlcədən-görmə rejimində ƏN faydalıdır.
        sys.stdout.write(
            "  --dry-run: qərar SORUŞULMUR. Həqiqi çağırışda seçim təklif "
            "ediləcək (davam / yeni / ləğv).\n\n"
        )
        return None

    decision = _decide_duplicate(args)
    if decision == _DUPLICATE_CONTINUE:
        chosen = matches[0]
        args.tenant_id = chosen.tenant_id
        args.license_key = chosen.license_key
        sys.stdout.write(f"  Mövcud kirayəçi davam etdirilir: {chosen.tenant_id}\n\n")
    return _DUPLICATE_EXITS.get(decision)


#: `_decide_duplicate`-in qaytardığı qərarlar. Sətir sabitləri kimi ayrıldı ki,
#: qərar ilə ONUN NƏTİCƏSİ (proses kodu) bir-birindən ayrı qalsın — əks halda
#: «yeni kirayəçi yarat» qərarı ilə «davam et» qərarı hər ikisi `None`
#: qaytardığı üçün eyni budağa düşər və hansının seçildiyi görünməzdi.
_DUPLICATE_CONTINUE: Final[str] = "davam"
_DUPLICATE_NEW: Final[str] = "yeni"
_DUPLICATE_ABORT: Final[str] = "legv"
_DUPLICATE_BLOCKED: Final[str] = "blok"
_DUPLICATE_CANCELLED: Final[str] = "imtina"

#: Qərar → proses kodu. `None` — davam et (yazı başlayır).
_DUPLICATE_EXITS: Final[dict[str, int | None]] = {
    _DUPLICATE_CONTINUE: None,
    _DUPLICATE_NEW: None,
    _DUPLICATE_ABORT: 0,
    _DUPLICATE_BLOCKED: DUPLICATE_EXIT_CODE,
    _DUPLICATE_CANCELLED: 130,
}


def _decide_duplicate(args: argparse.Namespace) -> str:
    """Dublikat halında NƏ ediləcəyini müəyyən edir — mesajları ÖZÜ çap edir.

    Qərar `_apply_duplicate_policy`-dən AYRILDI, çünki orada iki müstəqil
    məsuliyyət toplanmışdı: «hansı qərar verilir» və «qərar `args`-a necə
    tətbiq olunur». Ayrılıq həm də qərar dəstini SİYAHI kimi görünən edir —
    yeni bir hal əlavə edən `_DUPLICATE_EXITS`-i yeniləməyi UNUTMAZ, çünki
    naməlum açar `dict.get` ilə `None` qaytarardı və bu, testdə dərhal
    görünür.
    """
    from scripts.onboard_wizard import WizardCancelledError, choose, is_interactive

    if not is_interactive():
        # Sual soruşula bilməyən mühitdə (CI, boru, `.bat`) sükutla YENİ
        # kirayəçi yaratmaq ƏN PİS seçimdir: yetim sətir heç bir ekranda
        # görünmür və yalnız ödəniş hesabatında üzə çıxır. `--allow-duplicate`
        # BU budaqda da hörmət olunur — orada niyyət AÇIQ yazılıb.
        if args.allow_duplicate:
            sys.stdout.write("  `--allow-duplicate` verilib — AYRICA yeni kirayəçi yaradılır.\n\n")
            return _DUPLICATE_NEW
        sys.stderr.write(
            "\nDAYANDI: dublikat aşkarlandı, sual soruşula bilmədi (interaktiv "
            "terminal deyil).\n"
            "  • Mövcud kirayəçini DAVAM etdirmək üçün yuxarıdakı sətrin "
            "`--tenant-id` və `--license-key` dəyərlərini verin.\n"
            "  • Həqiqətən AYRI, yeni kirayəçi lazımdırsa `--allow-duplicate` "
            "əlavə edin.\n"
        )
        return _DUPLICATE_BLOCKED

    if args.allow_duplicate:
        sys.stdout.write("  `--allow-duplicate` verilib — AYRICA yeni kirayəçi yaradılır.\n\n")
        return _DUPLICATE_NEW

    try:
        decision = choose(
            "Nə edilsin?",
            [
                (
                    _DUPLICATE_CONTINUE,
                    "Mövcud kirayəçini DAVAM etdir (heç nə silinmir, təkrar yazılmır)",
                ),
                (_DUPLICATE_NEW, "AYRICA yeni kirayəçi yarat (eyni adlı FƏRQLİ şirkət/filial)"),
                (_DUPLICATE_ABORT, "Dayan, heç nə etmə"),
            ],
        )
    except WizardCancelledError:
        sys.stderr.write("\nDAYANDIRILDI: heç nə yazılmadı.\n")
        return _DUPLICATE_CANCELLED

    if decision == _DUPLICATE_ABORT:
        sys.stdout.write("  Dayandırıldı — heç nə yazılmadı.\n")
    elif decision == _DUPLICATE_NEW:
        sys.stdout.write("  AYRICA yeni kirayəçi yaradılır.\n\n")
    return decision


def _wizard_requested(args: argparse.Namespace) -> bool:
    """Sihirbaz işə düşsünmü — MEYAR «HEÇ BİR DSN VERİLMƏYİB»dir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `not argv`, YƏNİ «ÜMUMİYYƏTLƏ ARQUMENT YOXDUR» DEYİL
    ──────────────────────────────────────────────────────────────────────────
    `--dry-run`, `--out`, `--dev` sihirbazla ZİDD DEYİL: onlar quraşdırmanın
    NECƏ aparılacağını deyir, GİRİŞLƏRİ vermir. `not argv` meyarı ilə
    `onboard_new_tenant.py --dry-run` sihirbaza DÜŞMƏZ, əvəzində «--tenant-dsn
    verilməyib» xətası verərdi — halbuki operatorun niyyəti aydındır.

    Meyar MƏHZ DSN-lərdir, çünki sihirbazın YEGANƏ işi onları qurmaqdır.
    Biri verilibsə niyyət bayraqlı yoldur və yarımçıqlığı
    `_reject_invalid_arguments` AÇIQ mesajla deyir — sükutla sihirbaza
    keçmək operatorun ARTIQ yazdığı DSN-i görməzdən gəlmək olardı.
    """
    return not args.tenant_dsn and not args.vendor_dsn


def _run_wizard_into(args: argparse.Namespace) -> int | None:
    """Sihirbazı işə salır və cavabları `args`-a köçürür. Qaytarır: kod, ya `None`.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `Namespace`-Ə KÖÇÜRÜLÜR, AYRICA AXIN YAZILMIR
    ──────────────────────────────────────────────────────────────────────────
    Altı addımın hamısı (`_run_steps` və altındakılar) `args`-dan oxuyur.
    Sihirbaz üçün paralel bir axın yazsaydıq, hər gələcək dəyişiklik İKİ yerdə
    təkrarlanmalı olardı və biri unudulan gün fərq YALNIZ istehsalatda —
    müştəri quraşdırmasında — görünərdi. Sərhəd DARDIR: sihirbaz yalnız
    dəyərləri doldurur, məntiqə TOXUNMUR.

    `--dev` MƏCBURİ olaraq qalxır: sihirbazın verdiyi söz «bitən kimi
    `python -m src.main` açılır»dır, bu isə konfiqurasiyanın tətbiqin FAKTİKİ
    oxu yerlərinə yazılması deməkdir (bax `_deploy_dev_config`). Bayraqsız
    rejim yalnız arxiv qovluğuna yazır — həmin sözü tuta bilməzdi.
    """
    from scripts.onboard_wizard import WizardCancelledError, is_interactive, run_wizard

    if not is_interactive():
        # TERMİNAL YOXDURSA SİHİRBAZ ÜMUMİYYƏTLƏ BAŞLAMIR.
        # ──────────────────────────────────────────────────────────────────
        # Bu yoxlama olmasa nəticə İKİ fərqli, hər ikisi PİS haldır:
        #
        #   * Boru ilə (`echo … | script`) çağırışda `input()` sətirləri
        #     OXUYUR, lakin Windows-da `getpass.getpass` stdin-i DEYİL,
        #     KONSOLU oxuyur — proses parol sualında ASILIR və heç bir mesaj
        #     çıxmır. Bu, ölçülmüş haldır (2 dəqiqəlik timeout ilə müşahidə
        #     edildi).
        #   * Axın tamamilə bağlıdırsa (CI) `input()` `EOFError` atır və
        #     operator «DAYANDIRILDI: heç nə yazılmadı» görür — mesaj DOĞRU,
        #     lakin SƏBƏBİ yanlış göstərir: heç kim imtina etməyib, sadəcə
        #     terminal yoxdur.
        #
        # Ona görə səbəb BURADA, sual soruşulmazdan ƏVVƏL deyilir və çıxış
        # yolu (bayraqlı forma) göstərilir.
        sys.stderr.write(
            "XƏTA: sihirbaz interaktiv terminal tələb edir (bu mühitdə `stdin` "
            "terminal deyil).\n"
            "Boru/CI mühitində bayraqlı formanı işlədin:\n"
            "  scripts/onboard_new_tenant.py --company «…» --tenant-dsn «…» "
            "--vendor-dsn «…» --contact-email «…»\n"
        )
        return 2

    try:
        answers = run_wizard()
    except WizardCancelledError:
        sys.stderr.write("\nDAYANDIRILDI: heç nə yazılmadı.\n")
        # 130 = 128 + SIGINT. Qəsdən 1 DEYİL: CI və ya örtük skript «xəta»
        # ilə «istifadəçi imtina etdi» arasındakı fərqi proses kodundan
        # oxuya bilməlidir.
        return 130

    args.company = answers.company
    args.contact_email = answers.contact_email
    args.tenant_dsn = answers.tenant_dsn
    args.vendor_dsn = answers.vendor_dsn
    args.supabase_ref = answers.supabase_ref
    args.anon_key = answers.anon_key
    args.dev = True

    # Arxiv qovluğu kirayəçiyə görə AYRILIR. Defolt `./onboarding` sabit
    # olsaydı, ikinci müştərinin `OXU-MƏNİ.txt`-i birincinin ÜZƏRİNƏ yazılardı
    # və orada `license_key` var — yəni itən şey bərpa oluna bilməyən dəyərdir.
    # Şərt `== parser defoltu`-dur: operator `--out` verib sihirbaza düşə bilər
    # (bax `_wizard_requested`) və onun seçimi əzilməməlidir.
    from scripts.switch import slugify

    if args.out == DEFAULT_OUT_DIR:
        args.out = str(Path(DEFAULT_OUT_DIR) / (slugify(answers.company) or "tenant"))
    return None


def _prepare_arguments(args: argparse.Namespace) -> int | None:
    """Yazı axınının GİRİŞLƏRİNİ hazırlayır: sihirbaz + yoxlamalar.

    Qaytarır: proses kodu (dayanılmalıdır) və ya `None` (davam).

    İki addım BİR funksiyada birləşdi, çünki onlar EYNİ sualın iki yarısıdır —
    «`args` yazı üçün hazırdırmı?». Ayrı qalsaydılar `main()` yeddi çıxış
    nöqtəsi daşıyardı və hansı yoxlamanın hansı rejimə aid olduğu çağırış
    yerindən görünməzdi; burada isə SIRA aşkardır: əvvəl BOŞLUQLAR doldurulur,
    sonra NƏTİCƏ yoxlanılır.
    """
    if _wizard_requested(args):
        cancelled = _run_wizard_into(args)
        if cancelled is not None:
            return cancelled
    invalid = _reject_invalid_arguments(args)
    if invalid is not None:
        return invalid
    # Dublikat qapısı YOXLAMALARDAN SONRA gəlir və bu, sıra məsələsidir:
    # o, vendor bazasına QOŞULUR, yəni yarımçıq/səhv arqument dəstində
    # şəbəkə gözləməsi yaradardı. Əvvəl ucuz yoxlamalar, sonra bahalı.
    return _apply_duplicate_policy(args)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    args = _parse_args(argv)

    # `--verify` YAZI axınından TAMAMİLƏ ayrıdır: nə şirkət adı, nə əlaqə
    # ünvanı, nə də bərpa bayraqları ona aiddir — ona görə budaq BURADA,
    # bütün yazı-yönümlü yoxlamalardan ƏVVƏL bitir.
    verified = _verify_mode(args)
    if verified is not None:
        return verified

    prepared = _prepare_arguments(args)
    if prepared is not None:
        return prepared

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
        # Giriş nöqtəsi `python main.py` DEYİL: repozitoriya kökündə belə bir
        # fayl YOXDUR, tətbiq `src/main.py`-dır və PAKET kimi işə düşür
        # (`python src/main.py` nisbi idxalları qırır). Əvvəlki mətn səhv idi
        # və operatoru mövcud olmayan faylı axtarmağa göndərirdi.
        sys.stdout.write("  1. `python -m src.main` — əlavə addım LAZIM DEYİL.\n")
        sys.stdout.write(f"  2. Arxiv nüsxəsi «{args.out}» qovluğundadır.\n")
        sys.stdout.write("     Başqa kirayəçiyə keçmək: `python scripts/switch.py`\n")
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


def _redact_dsn(text: str) -> str:
    """Mətndəki hər DSN-in PAROLUNU maskalayır — istifadəçi adı QALIR.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ LAZIMDIR — «PAROL ONSUZ DA ÇAP OLUNMUR» KİFAYƏT DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Bu skript DSN-i heç yerdə BİLƏRƏKDƏN çap etmir, lakin ÜÇ yol onu ekrana
    ÇIXARA bilər və üçü də bizim nəzarətimizdən KƏNARDADIR:

      1. `_apply_migrations` ALT PROSESİN `stdout`/`stderr`-ini olduğu kimi
         yazır — orada `apply_migrations.py`-ın gələcək bir sətri, ya da
         `psycopg`-nin öz mesajı DSN daşıya bilər;
      2. `psycopg` bağlantı xətalarında bəzən tam bağlantı sətrini əks etdirir;
      3. operator ekranı dəstək üçün SKRİNŞOT edir — və məhz o an parol
         başqasının ekranına düşür.

    Maskalama ODUR ki, yuxarıdakı üç yolun HƏR BİRİ bir yerdə — çap
    nöqtəsində — bağlansın. İstifadəçi adı QƏSDƏN qalır: diaqnostikanın
    yarısı «hansı rol ilə qoşulur» sualıdır (`postgres` ilə `kompasos_app`
    fərqi) və onu da gizlətsək, mesaj faydasız olardı.

    Naxış DAR saxlanılır (`://user:parol@`): sərbəst mətndə iki nöqtə ilə
    ayrılmış hər cütü maskalasaydıq, `[3/6] Kirayəçi sətri: OK` kimi normal
    sətirlər də korlanardı.
    """
    return _DSN_PASSWORD.sub(r"\1:***", text)


#: `--verify`-in beş halqası ilə EYNİ NİYYƏT, lakin BAŞQA sual: burada
#: «quraşdırma nə qədər irəlilədi» deyilir. Mətnlər `_run_steps`-dəki addım
#: adları ilə üst-üstə düşür — operator ekranda gördüyü sətri hesabatda EYNİ
#: adla tapmalıdır, əks halda iki siyahını zehnində uyğunlaşdırmalı olur.
_STEP_TITLES: Final[tuple[str, ...]] = (
    "Tenant bazasına miqrasiyalar",
    "Vendor bazasına miqrasiyalar",
    "Kirayəçi sətri (tenant bazası)",
    "Abunə sətri (vendor bazası)",
    "Konfiqurasiya faylları",
    "Öz-özünü yoxlama",
)

#: Hər addımın ƏL İLƏ necə yoxlanacağı. Yarımçıq halda operatorun ilk sualı
#: «indi nə edim» olur — cavab HESABATIN İÇİNDƏ olmalıdır, sənəddə deyil.
_STEP_CHECKS: Final[tuple[str, ...]] = (
    "`scripts/apply_migrations.py --dry-run` — gözləyən miqrasiya qalıbmı",
    "`scripts/apply_migrations.py --vendor --dry-run`",
    "tenant bazası: SELECT * FROM kompasos.license_tenants WHERE tenant_id = …",
    "vendor bazası: SELECT * FROM tenants WHERE tenant_id = …",
    "`--out` qovluğu və `configs/` arxivi yarandımı",
    "`--verify <tenant_id>` ilə beş halqanı yoxlayın",
)


def _partial_state_report(last_ok: int, args: argparse.Namespace, tenant_id: uuid.UUID) -> str:
    """«Yarımçıq qaldı, bunları əl ilə yoxla» siyahısı — ATOMİKLİK ƏVƏZİ.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HESABAT, NİYƏ GERİ-QAYTARMA (ROLLBACK)
    ──────────────────────────────────────────────────────────────────────────
    Altı addım ALTI FƏRQLİ yerə toxunur: iki AYRI baza (tenant, vendor), yerli
    fayl sistemi və `%PROGRAMDATA%`. Bunları əhatə edən BİR tranzaksiya
    mövcud deyil — iki müstəqil PostgreSQL serveri arasında iki-fazalı commit
    qurmaq bu skriptin həll etməyə çalışdığı problemdən qat-qat böyük bir
    problemdir və nasazlıq halında ÖZÜ yarımçıq qala bilər.

    «Hamısını geri qaytar» daha pisdir: addım 1/2 MİQRASİYADIR — tətbiq
    olunmuş sxemi geri qaytarmaq (DOWN blokları) İŞLƏK ola biləcək bir bazanı
    boşaltmaq deməkdir və uğursuzluq başqa müştərinin işini kəsə bilər.

    Ona görə seçim ŞÜURLUDUR: skript geri qaytarmır, LAKİN vəziyyəti GİZLƏTMİR
    də. Hər addım üç haldan birində göstərilir (OK / UĞURSUZ / EDİLMƏDİ) və
    hər birinin yanında ƏL İLƏ yoxlama üsulu yazılır. Sükutla «xəta oldu»
    demək — operatoru altı yerin hansının toxunulduğunu təxmin etməyə məcbur
    etmək olardı.

    Addımların 1-4-ü ONSUZ DA idempotentdir (fayl başlığı, "D4"), yəni doğru
    davranış geri qaytarmaq YOX, EYNİ kimliklə təkrar çağırmaqdır.
    """
    lines = ["\nYARIMÇIQ QALDI — vəziyyət aşağıdakı kimidir:\n"]
    for index, (title, check) in enumerate(zip(_STEP_TITLES, _STEP_CHECKS, strict=True), start=1):
        if index <= last_ok:
            mark = "OK      "
        elif index == last_ok + 1:
            mark = "UĞURSUZ "
        else:
            mark = "EDİLMƏDİ"
        lines.append(f"  [{mark}] {index}. {title}\n")
        if index > last_ok:
            lines.append(f"              yoxlama: {check}\n")
    lines.append(f"\n  tenant_id : {tenant_id}\n")
    lines.append(f"  arxiv     : {args.out}\n")
    lines.append(
        "\nHEÇ NƏ GERİ QAYTARILMADI (bu, qəsdlidir — bax `_partial_state_report`).\n"
        "Addım 1-4 idempotentdir: eyni kimliklə təkrar çağırış tamamlanmış "
        "addımları sükutla keçir və yarımçıq qalandan davam edir.\n"
    )
    return "".join(lines)


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
    # ALT PROSESİN ÇIXIŞI OLDUĞU KİMİ YAZILMIR — bax `_redact_dsn`. DSN ora
    # mühit dəyişəni ilə düşür, yəni məzmununa bu skript nəzarət ETMİR.
    sys.stdout.write(_indent(_redact_dsn(result.stdout)))
    if result.returncode != 0:
        raise OnboardingError(
            f"miqrasiya icraçısı {result.returncode} qaytardı:\n{_redact_dsn(result.stderr)}"
        )


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

    ──────────────────────────────────────────────────────────────────────────
    ÜÇÜNCÜ ÜNVAN — `configs/<slug>.config` ARXİVİ (SWITCH-1)
    ──────────────────────────────────────────────────────────────────────────
    Yuxarıdakı İKİ davranış (arxiv qovluğu, `--dev` yerləri) OLDUĞU KİMİ qalır;
    sonda ÜÇÜNCÜSÜ ƏLAVƏ olunur: eyni konfiqurasiya `configs/<slug>.config`
    faylına da yazılır. Səbəb `scripts/switch.py`-dadır — təchizatçının
    maşınında yalnız BİR kirayəçi eyni anda aktiv ola bilər (fayllar sabit
    yerlərdədir), ona görə ikinci müştəri quraşdıranda birincinin
    konfiqurasiyası ÜZƏRİNƏ yazılırdı və geri qayıtmağın yolu quraşdırmanı
    təkrarlamaq idi. Arxiv həmin itkini aradan qaldırır.

    `--dev` halında bundle-a FAKTİKİ `connection.json` (şifrələnmiş parolla)
    düşür, bayraqsız halda isə şablonun özü — yəni parolsuz. Fərq `switch.py`-da
    EKRANDA deyilir; parolu bura yazmaq mümkün deyil (bax yuxarı).
    """
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    identity = {"tenant_id": str(tenant_id), "is_licensed": True}
    (out / "installation.json").write_text(
        json.dumps(identity, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    host, port, database, username = _parse_dsn(args.tenant_dsn)
    template = {
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password_encrypted": "",
    }
    (out / "connection.template.json").write_text(
        json.dumps(template, indent=2, ensure_ascii=False) + "\n",
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
        "sonra Vendor Konsolundan `AKTIV` edilməlidir.\n" + _anon_key_note(args),
        encoding="utf-8",
    )
    sys.stdout.write(_indent(f"{out}/installation.json\n{out}/connection.template.json\n"))

    deployed = _deploy_dev_config(args, tenant_id) if args.dev else None
    _archive_switch_config(args, identity, deployed=deployed, template=template)


def _anon_key_note(args: argparse.Namespace) -> str:
    """`OXU-MƏNİ.txt`-in `anon` açarı bölməsi — açar verilməyibsə BOŞ sətir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ FAYLA YAZILIR, KONFİQURASİYAYA DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Tətbiq `anon` açarını YALNIZ mühit dəyişənindən oxuyur
    (`KOMPASOS_SUPABASE_ANON_KEY` — `realtime/supabase_transport.py`,
    `updates/catalog.py`) və `.env` faylını QƏSDƏN oxumur (`src/main.py::
    _check_dotenv` istehsalatda `.env`-in MÖVCUDLUĞUNU xəbərdarlıq sayır).
    Yəni açarı `connection.json`-a yazmaq onu heç bir yolla İŞLƏK etməzdi —
    yalnız faylı bir sirr də ağır edərdi.

    Ona görə açar quraşdırıcıya GÖSTƏRİLİR: dəyəri hara qoyacağını bilən
    yeganə tərəf odur. Nüsxə həm də `configs/<slug>.config` arxivindədir
    (`_archive_switch_config`) — orada o, «bu kirayəçinin açarı hansı idi»
    sualının cavabıdır, çünki Supabase paneli açarı yalnız layihə səhifəsində
    saxlayır və dəstək zəngində ora çıxış həmişə olmur.

    Açar SİRR SAYILMIR: `anon` açarı brauzer tərəfinə göndərilmək üçün
    nəzərdə tutulub və RLS ilə məhdudlaşır — `service_role` açarı isə bu
    skriptə HEÇ VAXT verilmir (bax fayl başlığı).
    """
    anon_key = getattr(args, "anon_key", "")
    if not anon_key:
        return ""
    return (
        "\nSupabase `anon` açarı (realtime və auto-update üçün):\n"
        f"  KOMPASOS_SUPABASE_ANON_KEY={anon_key}\n"
        f"  KOMPASOS_SUPABASE_URL=https://{args.supabase_ref}.supabase.co\n"
        "Bu iki sətir MÜHİT DƏYİŞƏNİ kimi təyin edilməlidir — tətbiq `.env`\n"
        "faylını oxumur.\n"
    )


def _archive_switch_config(
    args: argparse.Namespace,
    identity: dict[str, object],
    *,
    deployed: Path | None,
    template: dict[str, object],
) -> None:
    """SWITCH-1: nüsxəni `configs/<slug>.config`-ə də yazır (bax `_write_config`).

    Arxivləmə HEÇ VAXT quraşdırmanı DAYANDIRMIR: bu addıma çatanda kirayəçi
    sətri artıq COMMIT olunub və müştəri paketi hazırdır — RAHATLIQ üçün
    saxlanan nüsxənin alınmaması (qovluq yazıla bilmir, disk dolub, köhnə
    bundle korlanıb) həmin işi «uğursuz» elan etməyi haqq qazandırmır. Səbəb
    görünən yerdə — ekranda — qalır və operator `switch.py` ilə sonra da
    arxivləyə bilər.
    """
    from scripts.switch import SwitchError, archive_config

    try:
        payload = _read_json_file(deployed) if deployed is not None else dict(template)
        archived = archive_config(
            company=args.company,
            installation=dict(identity),
            connection=payload,
            supabase=_supabase_block(args),
        )
    except (OSError, ValueError, SwitchError) as exc:
        sys.stdout.write(_indent(f"XƏBƏRDARLIQ: `configs/` arxivi yazılmadı — {exc}\n"))
        return
    sys.stdout.write(_indent(f"{archived}\n"))


def _supabase_block(args: argparse.Namespace) -> dict[str, object] | None:
    """Arxiv bundle-ının `supabase` bloku — heç nə bilinmirsə `None`.

    `None` qaytarmaq MƏNALIDIR: `switch.archive_config` onu «dəyişmə» kimi
    oxuyur və mövcud bundle-dakı köhnə açarı SAXLAYIR
    (`_keep_previous_supabase`). Boş sözlük qaytarsaydıq, bayraqlı yol ilə
    edilən hər təkrar quraşdırma sihirbazın topladığı açarı sükutla silərdi.
    """
    anon_key = getattr(args, "anon_key", "")
    if not anon_key and not args.supabase_ref:
        return None
    return {
        "project_ref": args.supabase_ref,
        "url": f"https://{args.supabase_ref}.supabase.co" if args.supabase_ref else "",
        "anon_key": anon_key,
    }


def _read_json_file(path: Path) -> dict[str, object]:
    """Yazılmış konfiqurasiyanı GERİ oxuyur — məzmun burada TƏKRAR qurulmur.

    `connection.json`-un sahələri (`version`, `sslmode`, şifrələnmiş parol)
    `connection_file.save_settings()`-in işidir; onları bu skriptdə yenidən
    yığsaydıq, format dəyişən gün arxiv sükutla köhnə formada qalardı.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _deploy_dev_config(args: argparse.Namespace, tenant_id: uuid.UUID) -> Path:
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

    Qaytarır: yazılmış `connection.json`-un yolu. Dəyər SWITCH-1 arxivinə
    lazımdır (`_archive_switch_config`) — həmin fayl parolu ŞİFRƏLƏNMİŞ şəkildə
    daşıyan YEGANƏ nüsxədir və arxiv onu geri OXUYUR, təkrar QURMUR.
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
    return connection_path


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
    _assert_no_plaintext_secrets(args)
    sys.stdout.write(_indent(f"kirayəçi «{row[0]}» oxundu, konfiqurasiya işləkdir\n"))


#: Konfiqurasiya JSON-unda parol OLMAYAN, lakin parolla ÜST-ÜSTƏ DÜŞƏ BİLƏN
#: sahələr. `username` xüsusilə təhlükəlidir: sihirbaz DSN-i HƏMİŞƏ `postgres`
#: istifadəçi adı ilə qurur, yəni parolu «postgres» olan test layihəsi bu
#: yoxlamanı YALANÇI-POZİTİV etdirərdi — və qiymət yüksəkdir: dayanma 6-cı
#: addımda, kirayəçi sətri ARTIQ COMMIT olunduqdan SONRA baş verir.
_NON_SECRET_JSON_KEYS: Final[frozenset[str]] = frozenset(
    {"username", "host", "database", "sslmode", "version", "slug", "company", "tenant_id"}
)


def _leaks_secret(content: str, secrets_to_find: set[str]) -> bool:
    """Faylın məzmununda AÇIQ parol varmı — JSON-da SAHƏYƏ görə, mətndə xam.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ XAM `in` YOXLAMASI KİFAYƏT ETMİR — ÖLÇÜLƏ BİLƏN YALANÇI-POZİTİV
    ──────────────────────────────────────────────────────────────────────────
    `connection.json` içində `"username": "postgres"` sahəsi VAR və sihirbazın
    qurduğu DSN-in istifadəçi adı HƏMİŞƏ `postgres`-dir. Parolu təsadüfən
    «postgres» olan (test layihələrində tamamilə real hal) müştəri üçün xam
    `secret in content` yoxlaması DOĞRU faylı «sızmış» elan edərdi. Eyni tələ
    host və baza adında da var: qısa parol («db», ref-in bir hissəsi) həmin
    sahələrdə rast gələ bilər.

    Yalançı-pozitivin qiyməti burada XÜSUSİLƏ yüksəkdir: yoxlama 6-cı addımda,
    kirayəçi sətri ARTIQ COMMIT olunduqdan SONRA işləyir — yəni səhv həyəcan
    quraşdırmanı «tamamlanmamış» elan edir və operatoru olmayan sızmanı
    axtarmağa göndərir.

    ──────────────────────────────────────────────────────────────────────────
    ZƏMANƏT ZƏİFLƏMİR — `password_encrypted` YOXLAMADAN ÇIXARILMIR
    ──────────────────────────────────────────────────────────────────────────
    İstisna siyahısı (`_NON_SECRET_JSON_KEYS`) YALNIZ parol DAŞIMAYAN sahələri
    əhatə edir. Parolun yazıla biləcəyi hər sahə — `password_encrypted` daxil
    olmaqla — yoxlanır: şifrələmə sükutla düşüb ora plaintext yazsa, o, MƏHZ
    tutulmalı olan haldır və tutulur.

    JSON olmayan fayllarda (`OXU-MƏNİ.txt`) xam yoxlama qalır — orada sahə
    anlayışı yoxdur və hər hansı rastlaşma araşdırılmalıdır.
    """
    try:
        payload = json.loads(content)
    except ValueError:
        return any(secret in content for secret in secrets_to_find)
    return _json_leaks_secret(payload, secrets_to_find)


def _json_leaks_secret(node: object, secrets_to_find: set[str], *, key: str = "") -> bool:
    """JSON ağacını gəzir; `_NON_SECRET_JSON_KEYS` açarlarının DƏYƏRİ atlanır.

    Rekursiya lazımdır, çünki `configs/<slug>.config` bundle-ı `connection` və
    `installation` bloklarını İÇ-İÇƏ saxlayır — düz (bir səviyyəli) gəzinti
    həmin blokların içindəki parolu GÖRMƏZDİ.
    """
    if isinstance(node, dict):
        return any(
            _json_leaks_secret(value, secrets_to_find, key=str(name))
            for name, value in node.items()
        )
    if isinstance(node, list):
        return any(_json_leaks_secret(item, secrets_to_find, key=key) for item in node)
    if isinstance(node, str) and key not in _NON_SECRET_JSON_KEYS:
        return any(secret in node for secret in secrets_to_find)
    return False


def _assert_no_plaintext_secrets(args: argparse.Namespace) -> None:
    """Yazılan HƏR faylı oxuyub AÇIQ parol axtarır — tapılsa DAYANIR.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ YOXLAMA, NİYƏ «ONSUZ DA YAZMIRIQ»
    ──────────────────────────────────────────────────────────────────────────
    «Parol config-ə yazılmır» İDDİADIR və iddia kodun oxusu ilə qorunur —
    yəni növbəti dəyişiklik onu SÜKUTLA poza bilər. Konkret üç yol var:
    `_write_config`-in şablonuna sahə əlavə etmək, `_deploy_dev_config`-in
    şifrələməsinin sükutla düşməsi (`save_settings` gələcəkdə boş açarla
    plaintext yazsa), və `switch.archive_config`-in bundle formatının
    genişlənməsi. Üçü də AYRI fayldadır, yəni bir baxışla qorunmur.

    Bu yoxlama iddianı ZƏMANƏTƏ çevirir: fayllar GERİ OXUNUR və içində
    parolun ÖZÜ axtarılır. `AuditTrail.record()`-un naxışı ilə eynidir —
    məcburi olan bir şeyin sükutla buraxılması onu məcburi olmaqdan çıxarır,
    ona görə uğursuzluq DAYANDIRIR (`OnboardingError`), xəbərdarlıq deyil.

    ──────────────────────────────────────────────────────────────────────────
    NƏ AXTARILIR, NƏ AXTARILMIR
    ──────────────────────────────────────────────────────────────────────────
    Axtarılan: TENANT və VENDOR baza parolları (DSN-dən çıxarılır).
    Axtarılmayan: `license_key`. O, `OXU-MƏNİ.txt`-ə BİLƏRƏKDƏN yazılır —
    quraşdırıcı onu müştəriyə verməlidir və faylın bütün mövcudluq səbəbi
    budur. `service_role` açarı isə bu skriptə HEÇ VAXT verilmir, yəni
    axtarılacaq dəyər də yoxdur.
    """
    from urllib.parse import unquote, urlparse

    from scripts.switch import BUNDLE_SUFFIX, CONFIGS_DIR, slugify

    secrets_to_find = {
        unquote(urlparse(dsn).password or "") for dsn in (args.tenant_dsn, args.vendor_dsn)
    }
    # Boş parol axtarmaq HƏR faylı «sızmış» elan edərdi (`"" in text` həmişə
    # doğrudur) — parolsuz DSN isə real haldır (məs. `.pgpass` ilə).
    secrets_to_find.discard("")
    if not secrets_to_find:
        return

    targets = [path for path in Path(args.out).glob("*") if path.is_file()]
    bundle = CONFIGS_DIR / f"{slugify(args.company)}{BUNDLE_SUFFIX}"
    if bundle.is_file():
        targets.append(bundle)
    if args.dev:
        from src.infrastructure.config.connection_file import connection_file_path
        from src.shared.installation import installation_file

        targets.extend(
            path for path in (connection_file_path(), installation_file()) if path.is_file()
        )

    for path in targets:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Oxuna bilməyən fayl yoxlanmamış sayılır, LAKİN quraşdırmanı
            # dayandırmır: bu addıma çatanda kirayəçi sətri artıq COMMIT
            # olunub və oxu icazəsi problemi sızma DEYİL.
            continue
        if _leaks_secret(content, secrets_to_find):
            raise OnboardingError(
                f"AÇIQ PAROL AŞKARLANDI: «{path}» faylı baza parolunu şifrələnməmiş "
                "saxlayır. Fayl SİLİNMƏDİ (əl ilə yoxlayın), lakin quraşdırma "
                "TAMAMLANMIŞ sayılmır — bax `_assert_no_plaintext_secrets`."
            )


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


def _verify_tenant_links(
    args: argparse.Namespace,
    tenant_id: uuid.UUID,
    *,
    line: Callable[[bool, str, str], None],
) -> None:
    """`--verify`-in TENANT bazasındakı dörd halqası (reyestr, cədvəl, seed, sətir).

    `_verify`-dən AYRILDI: hər halqa öz `try`-ı ilə gəldikdən sonra funksiya
    ifadə həddini keçirdi. Bölgü təbiidir — burada YALNIZ müştəri bazası
    danışılır, vendor bazası və yerli konfiqurasiya AYRI bağlantılardır.
    """
    import psycopg

    def _link(title: str, check: Callable[[], None]) -> None:
        """BİR halqa — ÖZ `try`-ı ilə.

        CANLI AŞKARLANDI: `kompasos_app` rolu `schema_migrations`-i OXUYA
        BİLMİR (migrations/078 GRANT sərtləşməsi — reyestr admin işidir).
        Bütün halqalar TƏK `try` ilə sarılanda həmin icazə xətası QALAN üç
        halqanı da öldürürdü, yəni operator «seed varmı?» sualına cavab
        ALMIRDI. İndi hər halqa müstəqil sınır.
        """
        try:
            check()
        except psycopg.Error as exc:
            line(False, title, f"oxuna bilmədi — {str(exc).splitlines()[0]}")

    try:
        with psycopg.connect(args.tenant_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
            cur.execute("SET search_path TO kompasos, public")

            def _registry() -> None:
                """1. MİQRASİYA REYESTRİ (061) — DB-5-in tapdığı qüsurun qapısı:
                tətbiq olunmayan miqrasiya «cədvəl yoxdur» kimi AYLARLA gizlənir.

                REYESTR ADMİN İŞİDİR: `kompasos_app` rolunun ora OXU icazəsi
                YOXDUR (migrations/078) — o halda bu halqa «oxuna bilmədi»
                deyir və operator admin DSN-i ilə təkrar çağırır."""
                expected = {
                    path.name
                    for path in sorted(
                        (_REPO_ROOT / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql")
                    )
                }
                cur.execute("SELECT to_regclass('kompasos.schema_migrations')")
                row = cur.fetchone()
                if row is None or row[0] is None:
                    line(False, "Miqrasiya reyestri", "cədvəl YOXDUR (061 tətbiq olunmayıb)")
                    return
                cur.execute("SELECT filename FROM schema_migrations")
                applied = {name for (name,) in cur.fetchall()}
                missing = sorted(expected - applied)
                line(
                    not missing,
                    "Miqrasiya reyestri",
                    f"{len(applied)}/{len(expected)} tətbiq olunub"
                    + (f", çatmayan: {', '.join(missing[:5])}" if missing else ""),
                )

            def _tables() -> None:
                """2. ƏSAS CƏDVƏLLƏR — `to_regclass` NULL qaytarırsa cədvəl yoxdur."""
                absent = []
                for table in _CORE_TABLES:
                    cur.execute("SELECT to_regclass(%s)", (f"kompasos.{table}",))
                    found = cur.fetchone()
                    if found is None or found[0] is None:
                        absent.append(table)
                line(
                    not absent,
                    "Əsas cədvəllər",
                    f"{len(_CORE_TABLES) - len(absent)}/{len(_CORE_TABLES)} mövcuddur"
                    + (f", yoxdur: {', '.join(absent)}" if absent else ""),
                )

            def _seed() -> None:
                """3. SEED — `seed_tenant_defaults()` çağırılıbmı.

                Sətirlər HƏMİŞƏ kirayəçiyə görə süzülür: qlobal şablon sətirləri
                (`tenant_id IS NULL`, məs. rol şablonları) SAYILSAYDI, seed
                edilməmiş kirayəçi də «dolu» görünərdi."""
                counts: dict[str, int] = {}
                for table in _SEEDED_TABLES:
                    cur.execute(
                        f"SELECT count(*) FROM {table} WHERE tenant_id = %s",  # noqa: S608 — ad SABİT siyahıdandır
                        (str(tenant_id),),
                    )
                    counted = cur.fetchone()
                    counts[table] = int(counted[0]) if counted else 0
                empty = sorted(name for name, value in counts.items() if value == 0)
                line(
                    not empty,
                    "Seed məlumatı",
                    ", ".join(f"{name}={value}" for name, value in counts.items())
                    + (f" — BOŞ: {', '.join(empty)}" if empty else ""),
                )

            def _tenant_row() -> None:
                """4. KİRAYƏÇİ SƏTRİ — addım 3-ün nəticəsi."""
                cur.execute(
                    "SELECT tenant_name, status FROM license_tenants WHERE tenant_id = %s",
                    (str(tenant_id),),
                )
                row = cur.fetchone()
                line(
                    row is not None,
                    "Kirayəçi sətri",
                    f"«{row[0]}», status {row[1]}" if row else "TAPILMADI",
                )

            for title, check in (
                ("Miqrasiya reyestri", _registry),
                ("Əsas cədvəllər", _tables),
                ("Seed məlumatı", _seed),
                ("Kirayəçi sətri", _tenant_row),
            ):
                _link(title, check)
                # Bir halqa sınsa tranzaksiya ABORTED qalır — növbəti sorğu da
                # sınardı (PostgreSQL qaydası). `rollback()` sessiyanı təmizə
                # çıxarır və qalan halqalar HƏQİQƏTƏN yoxlanır.
                conn.rollback()
                # `SET search_path` TRANZAKSİYAYA bağlıdır: `rollback()` onu da
                # geri alır və növbəti halqa cədvəli «yoxdur» sanardı (canlı
                # ölçüdə məhz belə oldu — `system_limits does not exist`).
                cur.execute("SET search_path TO kompasos, public")
    except psycopg.Error as exc:
        line(False, "Tenant bazası", f"qoşulmaq alınmadı — {exc}")


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

    def _link(title: str, check: Callable[[], None]) -> None:
        """BIR halqa — oz try/except-i ile.

        CANLI ASKARLANDI: `kompasos_app` rolu `schema_migrations`-i OXUYA
        BILMIR (migrations/078 GRANT sertlesmesi — reyestr admin isidir).
        Butun halqalar TEK `try` ile sarilanda hemin icaze xetasi QALAN uc
        halqani da oldururdu, yeni operator "seed varmi?" sualina cavab
        ALMIRDI. Indi her halqa mustegil sinir.
        """
        try:
            check()
        except psycopg.Error as exc:
            _line(False, title, f"oxuna bilmedi — {str(exc).splitlines()[0]}")

    _verify_tenant_links(args, tenant_id, line=_line)

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
    # ONBOARD-FINAL: `required=True` GÖTÜRÜLDÜ. Səbəb defolt rejimin
    # dəyişməsidir — arqumentsiz çağırış artıq «istifadə səhvi» deyil,
    # SİHİRBAZDIR (bax `_wizard_requested`). `argparse` məcburiliyi
    # saxlasaydı, sihirbaz heç vaxt işə düşməzdi: parser ondan ƏVVƏL
    # `SystemExit(2)` ilə dayanardı. Bayraqlı yolun məcburiliyi İTMİR —
    # o, `_reject_invalid_arguments`-ə köçdü, çünki şərt artıq sadə
    # «verilib/verilməyib» deyil, REJİMDƏN asılıdır.
    parser.add_argument(
        "--tenant-dsn", default="", help="MÜŞTƏRİNİN öz Supabase DSN-i (boş = sihirbaz)"
    )
    parser.add_argument(
        "--vendor-dsn", default="", help="MƏRKƏZİ vendor bazasının DSN-i (boş = sihirbaz)"
    )
    parser.add_argument("--supabase-ref", default="", help="müştəri layihəsinin ref-i")
    parser.add_argument(
        "--anon-key", default="", help="müştəri layihəsinin `anon` açarı (istəyə bağlı)"
    )
    # MƏCBURİDİR (bax `_create_tenant_row`), lakin `required=True` DEYİL:
    # `--dry-run` yolunun onsuz da işləməsi lazımdır ki, quraşdırıcı
    # addımları əvvəlcədən görə bilsin.
    parser.add_argument(
        "--contact-email", default="", help="şirkət əlaqə ünvanı (yazma üçün MƏCBURİ)"
    )
    parser.add_argument("--out", default=DEFAULT_OUT_DIR, help="konfiqurasiya qovluğu")
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
        metavar="AD|TENANT_ID",
        help=(
            "mövcud kirayəçini YOXLA (heç nə yazılmır). AD verilsə DSN-lər "
            "`configs/` arxivindən və `.onboard_config`-dən qurulur; UUID verilsə "
            "`--tenant-dsn`/`--vendor-dsn` MƏCBURİDİR — bax `_verify_mode`"
        ),
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
    # ONBOARD-FINAL Faza 2 (idempotentlik): dublikat aşkarlananda skript
    # DAYANIR. Bu bayraq həmin qapını AÇIQ şəkildə yan keçir — «eyni adlı
    # FƏRQLİ şirkət» halı realdır (filiallar), lakin o qərar ADAMINDIR,
    # skriptin defoltu deyil.
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="eyni adlı/ref-li kirayəçi olsa belə AYRICA yenisini yarat",
    )
    return parser.parse_args(argv)


def _describe_steps(args: argparse.Namespace) -> None:
    sys.stdout.write("Addımlar:\n")
    sys.stdout.write("  1. Tenant bazasına BÜTÜN miqrasiyalar (apply_migrations.py)\n")
    sys.stdout.write("  2. Vendor bazasına vendor miqrasiyaları (--vendor)\n")
    sys.stdout.write("  3. `license_tenants` sətri → seed trigger-ləri işə düşür\n")
    sys.stdout.write("  4. Vendor `tenants` sətri (status: ODENIS_GOZLENILIR)\n")
    sys.stdout.write(f"  5. Konfiqurasiya faylları → {args.out}\n")
    from scripts.switch import BUNDLE_SUFFIX, CONFIGS_DIR, slugify

    sys.stdout.write(
        f"     + arxiv (SWITCH-1): {CONFIGS_DIR / (slugify(args.company) + BUNDLE_SUFFIX)}\n"
    )
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
