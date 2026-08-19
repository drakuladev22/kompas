r"""Təchizatçının `Root` hesabını yaradır — VENDOR ALƏTİ (SEC-024).

──────────────────────────────────────────────────────────────────────────────
BOŞLUQ NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`first_run_setup.complete()` şərhi belə deyirdi: «Təchizatçı öz hesabını
`scripts/onboard_new_tenant.py` ilə açır». Həmin skript isə kimlik, vendor
sətri, sxem, seed və konfiqurasiya qurur — İŞÇİ YARATMIR. Yəni vəd yerinə
yetirilmirdi və zəncir hər halqasında bağlı idi:

    * sihirbaz `CEO` yaradır (müştərinin ən üst hesabı) — qəsdən;
    * Strict Hierarchy Guard-a görə `CEO` özündən YUXARI hesab yarada bilmir,
      yəni `Root`-u sonradan panelin içindən açmaq da mümkün deyil;
    * `ROOT` vəzifəsi `seed_tenant_defaults()` ilə yaranır və BOŞ qalır.

Nəticədə `Root`-a bağlı hər şey əlçatmaz idi: ROOT İdarə Mərkəzi (limit və
Feature Toggle-lar), «Texniki Dəstək» kanalı (CHAT-1), Telegram ayarları,
bərpa konsolu, plugin idarəsi və baza keçidi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `.exe`-YƏ PAKETLƏNMİR
──────────────────────────────────────────────────────────────────────────────
`src/KompasOS.spec` yalnız `src/` altını yığır. Səbəb `onboard_new_tenant.py`
ilə eynidir: müştəri maşınında `Root` yaratmaq imkanı bütün rol iyerarxiyasını
mənasız edərdi — istənilən adam özünə ən yüksək səlahiyyəti verə bilərdi.
`tests/unit/test_packaging_credentials.py` bunu maşınla qoruyur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA SKRİPT — «SİHİRBAZA ADDIM ƏLAVƏ ETMƏK» NİYƏ RƏDD EDİLDİ
──────────────────────────────────────────────────────────────────────────────
Sihirbaz MÜŞTƏRİNİN əlindədir. Ona «Root hesabı yarat» addımı əlavə etmək
SEC-024-ün ayırdığı iki pilləni yenidən birləşdirərdi: müştəri quraşdırmanın
ilk dəqiqəsində təchizatçı səlahiyyətlərini alardı və auditdə «kim etdi»
sualı bir daha ayrıla bilməzdi. Ona görə yol əmr sətrindədir — həmin maşına
təchizatçı özü çıxır.

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ
──────────────────────────────────────────────────────────────────────────────
    # Nə ediləcəyini göstərir, HEÇ NƏ yazmır:
    .venv/Scripts/python.exe scripts/create_root_account.py --dry-run

    # Yaradır (şifrə GİZLİ soruşulur — əmr sətrində YAZILMIR):
    .venv/Scripts/python.exe scripts/create_root_account.py \
        --username developer --first-name Texniki --last-name Dəstək

DSN mənbəyi tətbiqin özü ilə eynidir (`build_dsn_from_env()`): `DATABASE_URL`,
o boşdursa paketlənmiş quraşdırmanın `connection.json` faylı. Yəni skript həm
inkişaf maşınında, həm də müştəri kompüterində eyni bazanı görür.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

#: Şifrənin minimum uzunluğu — YALNIZ ehtiyat hədd.
#:
#: Həqiqi mənbə `system_limits`-dəki `PASSWORD_MIN_LENGTH`-dir və onu
#: `HashingService` `create()` daxilində tətbiq edir. Burada saxlanan dəyər
#: sadəcə istifadəçiyə İKİ dəfə şifrə yazdırıb sonra rədd cavabı verməmək
#: üçündür — yəni erqonomika, siyasət deyil.
FALLBACK_MIN_PASSWORD: Final[int] = 8


def _load_dotenv() -> None:
    """`.env`-i mühitə yükləyir — `apply_migrations.py` ilə EYNİ oxuyucu.

    `python-dotenv` işlədilmir: skript inkişaf mühitindən kənarda da işlədilir
    və orada əlavə asılılıq olmaya bilər. `setdefault` — artıq təyin edilmiş
    mühit dəyişəni FAYLDAN üstündür (bax `build_dsn_from_env()` sırası).
    """
    path = _REPO_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _ensure_utf8_stdio() -> None:
    """Windows-un defolt konsol kodlaşdırmasını (cp1252) DÜZƏLDİR.

    `scripts/apply_migrations.py::_ensure_utf8_stdio`-nun HƏRFİ nüsxəsi.
    Bu skript SEC-024 bootstrap addımıdır — ən həssas skriptlərdən biri — və
    sətir 266-dakı "OK — `Root` hesabı yaradıldı" təsdiqi məhz hesab BAZAYA
    YAZILDIQDAN (COMMIT-dən) SONRA çap olunur. `PYTHONIOENCODING`
    təyin edilməyəndə həmin çap `UnicodeEncodeError` ilə çökür — yəni Root
    hesabı FAKTİKİ yaradılır, operator isə traceback görüb əks nəticə zənn
    edə, əməliyyatı TƏKRARLAMAĞA cəhd edə bilər (nəticədə `--force` tələb
    olunan ikinci Root axtarışı).
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            with suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


def _prompt_password(minimum: int) -> str:
    """Şifrəni GİZLİ soruşur — əmr sətri arqumenti kimi QƏBUL EDİLMİR.

    Arqument olsaydı, şifrə həm qabıq tarixçəsinə, həm də proses siyahısına
    düşərdi; hər ikisi eyni kompüterdəki digər istifadəçiyə görünür. Təkrar
    soruşmaq isə yazı səhvini yaratma anında tutur — əks halda təchizatçı öz
    hesabından kilidlənərdi və onu açacaq ikinci `Root` mövcud olmazdı.
    """
    # KONSOL YOXLAMASI — SÜKUTLU ASILMANI QARŞILAYIR.
    # Windows-da `getpass` `msvcrt` ilə BİRBAŞA konsoldan oxuyur; boru
    # (`echo ... | python ...`) və ya konsolsuz mühitdə çağırış cavab
    # gözləyərək SONSUZA QƏDƏR dayanır — nə xəta, nə mesaj. Sınaq zamanı
    # məhz belə oldu, ona görə şərt açıq yazılır.
    if not sys.stdin.isatty():
        raise SystemExit(
            "Bu alət ŞİFRƏNİ konsoldan soruşur — onu birbaşa terminalda işlədin "
            "(PowerShell / cmd), boru və ya avtomatlaşdırılmış mühitdə yox."
        )

    first = getpass.getpass("Root şifrəsi: ")
    if len(first) < minimum:
        raise SystemExit(f"Şifrə minimum {minimum} simvol olmalıdır")
    if first != getpass.getpass("Təkrarı    : "):
        raise SystemExit("Şifrələr uyğun gəlmir")
    return first


def _resolve_tenant(explicit: str | None) -> uuid.UUID:
    """Kirayəçini TƏTBİQİN ÖZ mənbəyindən həll edir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `license_tenants`-DƏN OXUNMUR
    ──────────────────────────────────────────────────────────────────────────
    İlk yazılışda skript kirayəçini `license_tenants` cədvəlindən seçirdi və
    inkişaf maşınında işləyirdi — çünki `.env`-də `DATABASE_ADMIN_URL` var və
    `Database` onu görüb `system_scope()`-u OWNER bağlantısı ilə açır. Müştəri
    kompüterində belə bir DSN YOXDUR: `kompasos_app` rolu RLS altında həmin
    cədvəli ÜMUMİYYƏTLƏ görmür və skript «kirayəçi sətri yoxdur» deyərdi —
    halbuki sətir var. Yəni sınaq mühiti həqiqəti gizlədirdi.

    `resolve_installation_identity()` isə tətbiqin `build_context()`-də
    işlətdiyi EYNİ mənbədir (mühit → `installation.json`), ona görə skript
    proqramın hansı kirayəçini açdığına ZƏMANƏTLƏ uyğun gəlir.

    `allow_generate=False` MƏCBURİDİR: yeni UUID yaratmaq «boş, uydurma
    tenant-da Root hesabı» demək olardı və hesab heç bir bazada görünməzdi.
    """
    if explicit:
        return uuid.UUID(explicit)

    from src.shared.installation import (
        InstallationIdentityError,
        resolve_installation_identity,
    )

    try:
        return resolve_installation_identity(allow_generate=False).tenant_id
    except InstallationIdentityError as exc:
        raise SystemExit(
            f"Kirayəçi kimliyi tapılmadı: {exc.message}\n"
            "Ya `--tenant-id` verin, ya da əvvəlcə proqramı bir dəfə açıb "
            "ilk quraşdırma sihirbazını tamamlayın."
        ) from exc


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Təchizatçının `Root` hesabını yaradır")
    parser.add_argument("--username", default="developer", help="Giriş identifikatoru")
    parser.add_argument("--first-name", default="Texniki", help="Ad")
    parser.add_argument("--last-name", default="Dəstək", help="Soyad")
    parser.add_argument("--tenant-id", default=None, help="Kirayəçi (birdən çox olduqda məcburi)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Aktiv `Root` olsa belə YENİSİNİ yarat (defolt: dayanır)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Heç nə yazmadan göstər")
    args = parser.parse_args(argv)

    _load_dotenv()

    from src.domain.entities.employee import Employee
    from src.domain.value_objects.authorization import RolePriority, SystemRole
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import TenantId, new_employee_id
    from src.infrastructure.persistence.connection import Database, build_dsn_from_env

    tenant = _resolve_tenant(args.tenant_id)
    tenant_id = TenantId(tenant)

    # OWNER DSN QƏSDƏN KƏNARLAŞDIRILIR: hesab yazısı RLS ALTINDA getməlidir —
    # tətbiqin özü də məhz bu yolu işlədir. Owner ilə yazsaydıq, RLS
    # siyasətinin bu sətri qəbul edib-etmədiyi HEÇ VAXT sınanmazdı və qüsur
    # yalnız müştəri maşınında üzə çıxardı. `Database` `admin_dsn=None`
    # verildikdə də mühitə baxır, ona görə açar burada silinir.
    os.environ.pop("DATABASE_ADMIN_URL", None)
    database = Database(build_dsn_from_env())
    try:
        with database.unit_of_work(tenant_id) as uow:
            position = uow.positions.get_by_code(tenant_id, SystemRole.ROOT.value)
            if position is None:
                raise SystemExit(
                    "`ROOT` vəzifəsi tapılmadı — baza seed-i tətbiq olunmayıb "
                    "(`scripts/apply_migrations.py`)."
                )
            username = Username.parse(args.username)
            # Sayğac PİLLƏ ilədir, vəzifə ADI ilə deyil: təchizatçı custom rol
            # da yarada bilər və onun prioriteti `ROOT` olsaydı, ad üzrə axtarış
            # onu görməzdi (bax `count_active_ranked_at_or_above`, SETUP-3).
            existing = uow.employees.count_active_ranked_at_or_above(tenant_id, RolePriority.ROOT)
            taken = uow.employees.get_by_username(tenant_id, username)

            print(f"Kirayəçi    : {tenant}")
            print(f"ROOT vəzifə : {position.id}  (prioritet {int(position.priority)})")
            print(f"Mövcud Root : {existing}")
            print(f"Yaradılacaq : {username} ({args.first_name} {args.last_name})")

            if taken is not None:
                raise SystemExit(
                    f"\n`{username}` istifadəçi adı ARTIQ MÖVCUDDUR "
                    f"({taken.position.code}). Başqa `--username` seçin."
                )
            if existing and not args.force:
                raise SystemExit(
                    "\nAktiv `Root` hesabı ARTIQ VAR. Yenisini yaratmaq üçün `--force` verin — "
                    "təsadüfən ikinci ən yüksək hesab açmaq audit izini qarışdırır."
                )
            if args.dry_run:
                print("\n--dry-run: heç nə yazılmadı.")
                return 0

            password = _prompt_password(FALLBACK_MIN_PASSWORD)

            employee_id = new_employee_id()
            employee = Employee(
                employee_id=employee_id,
                tenant_id=tenant_id,
                position=position,
                first_name=args.first_name,
                last_name=args.last_name,
                # Filiala BAĞLANMIR: təchizatçı bütün şəbəkəyə baxır və bir
                # mağazaya bağlansaydı hesabatlar sükutla daralardı (`CEO` ilə
                # eyni qərar — bax `first_run_setup.complete`).
                store_id=None,
                username=username,
                has_password=True,
                # Şifrəni təchizatçı ÖZÜ təyin edir, ona görə məcburi dəyişmə
                # yoxdur — sihirbazın `CEO` hesabında da eyni istisna var.
                must_change_password=False,
            )
            # `save()` DEYİL: o `UPDATE`-dir və olmayan sətri yaratmır
            # (bax `repositories.create()` docstring-i).
            uow.employees.create(employee, raw_password=password)

            # Audit sətri hesabın ÖZÜ tərəfindən yazılır: `audit_logs.actor_id`
            # `employees`-ə xarici açardır, yəni aktor mövcud olmalıdır — və bu
            # anda mövcud olan yeganə uyğun sətir elə yeni yaradılandır.
            uow.audit.record(
                tenant_id=tenant_id,
                actor_id=employee_id,
                action="ROOT_ACCOUNT_PROVISIONED",
                entity_type="employees",
                entity_id=employee_id,
                after_state={
                    "username": args.username,
                    "position_code": SystemRole.ROOT.value,
                    "source": "scripts/create_root_account.py",
                },
                reason="Təchizatçı hesabı əmr sətri aləti ilə yaradıldı (SEC-024)",
            )
            uow.commit()
    finally:
        database.close()

    print(f"\nOK — `Root` hesabı yaradıldı: {args.username}")
    print("Proqramın giriş ekranında həmin istifadəçi adı və şifrə ilə daxil olun.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
