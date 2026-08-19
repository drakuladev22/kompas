r"""Gizli bərpa konsolunun MƏNTİQ qatı — `Ctrl+Shift+K` (RECOVERY-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ GİZLİ
──────────────────────────────────────────────────────────────────────────────
Müştərinin gördüyü ekran QƏSDƏN kasıbdır: mesaj + «Yenidən Cəhd Et» + dəstək
ünvanı. Orada «Bağlantı Ayarları» düyməsi OLSAYDI, mağaza işçisi problemi özü
«düzəltməyə» çalışar və işlək konfiqurasiyanı poza bilərdi — sonra isə həm
nasazlıq, həm də onun səbəbi dəyişmiş olardı.

Konsol isə TEXNİKİN alətidir və qısayolla açılır. Gizlilik təhlükəsizlik
DEYİL (qısayol sənədləşdirilib) — o, sadəcə səhv adamın oraya təsadüfən
düşməsinin qarşısını alır. Həqiqi qapı aşağıdakı `may_open`-dadır.

──────────────────────────────────────────────────────────────────────────────
XƏTA MESAJI KONKRET OLMALIDIR
──────────────────────────────────────────────────────────────────────────────
«Bağlantı xətası» quraşdırıcıya heç nə vermir: DNS səhvi host sahəsini,
`28P01` isə açarı düzəltməyi tələb edir. Ayırıcı SQLSTATE-dir və o,
lokalizasiyadan asılı deyil (`composition.classify_connection_failure`-dakı
eyni qərar). Tanımadığımız halda server MƏTNİ olduğu kimi göstərilir —
«naməlum xəta» yazmaq texniki gözlə oxunan yeganə məlumatı gizlədərdi.
"""

from __future__ import annotations

import os
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Final

from src import __version__
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.domain.entities.employee import Employee
    from src.presentation.composition import StartupFailureKind

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Konsolu açan səlahiyyət — `use_cases/db_switch.SWITCH_DB_FLAG` ilə EYNİ.
#: İkinci sabit yaratmaq iki qaydanın bir gün ayrılması deməkdir.
SWITCH_DB_FLAG: Final[str] = "can_switch_db"

#: Fon işinin nəticəsi `(mətn, təsdiq lazımdır?)` cütü ola bilər.
_RESULT_PAIR: Final[int] = 2

#: Uzun siyahılarda ekranda göstərilən element sayı — mesaj bir neçə
#: sətirdən uzun olsa, texnik ƏSAS məlumatı (say) itirər.
_PREVIEW_LIMIT: Final[int] = 10

#: SEC-2 genişlənməsi (dövrə 1 audit, `RecoveryConsoleController` başlığına
#: bax) — avtentifikasiyasız (bypass) rejimdə saxlanmış parol HEÇ VAXT
#: şəbəkəyə göndərilmir/yaddaşa yazılmır; bu mətnlər həmin qərarın
#: istifadəçiyə görünən tərəfidir.
_UNAUTHENTICATED_NETWORK_BLOCKED: Final[str] = (
    "Bu rejimdə saxlanmış parol istifadə olunmur — parolu əl ilə daxil edin."
)
_UNAUTHENTICATED_SAVE_BLOCKED: Final[str] = (
    "Bu rejimdə boş parolla yadda saxlamaq olmaz — parolu əl ilə daxil edin."
)
#: Dövrə 2 audit (team-lead tapıntısı) — `refresh()`-in KÖHNƏ statusu
#: ("Parol boş qalarsa dəyişmir") avtentifikasiyasız rejimdə YALANDIR: bu
#: rejimdə boş parol "dəyişmə" YOX, "yoxdur" deməkdir və əməliyyat
#: BLOKLANACAQ. Texnik nasazlıq təzyiqi altında köhnə mesaja güvənib boş
#: sahə ilə düymələri basardı və niyə işləmədiyini anlamazdı.
_UNAUTHENTICATED_REFRESH_STATUS: Final[str] = (
    "Mövcud ayarlar göstərilir. Bu rejimdə saxlanmış parol İSTİFADƏ OLUNMUR "
    "— parolu MÜTLƏQ əl ilə yazın."
)

#: SQLSTATE → istifadəçi mətni. Siyahı DAR saxlanılır: yalnız quraşdırıcının
#: FƏRQLİ addım atacağı hallar. Qalanı orijinal mətnlə göstərilir.
_SQLSTATE_MESSAGES: Final[dict[str, str]] = {
    "28P01": "Açar/parol rədd edildi (28P01) — istifadəçi adı və ya parol yanlışdır.",
    "28000": "Açar rədd edildi (28000) — istifadəçi bu bazaya qoşula bilmir.",
    "3D000": "Belə baza yoxdur (3D000) — «Baza adı» sahəsini yoxlayın.",
    "42P01": "Cədvəl yoxdur (42P01) — sxem qurulmayıb. «Bazanı Avtomatik Qur» işlədin.",
    "42501": "İcazə çatmır (42501) — bu istifadəçinin cədvəl yaratmaq hüququ yoxdur.",
    "53300": "Bağlantı limiti dolub (53300) — Supabase layihəsində aktiv sessiyalar çoxdur.",
}

#: Mətndə axtarılan naxışlar — SQLSTATE OLMAYAN nasazlıqlar üçün.
#: Şəbəkə səviyyəsindəki xətalar (DNS, taymaut) `sqlstate` DAŞIMIR, çünki
#: server cavabı ümumiyyətlə alınmır.
_TEXT_MESSAGES: Final[tuple[tuple[str, str], ...]] = (
    (
        "could not translate host name",
        "Host adı tapılmadı (DNS) — «Server ünvanı» sahəsindəki ad səhv yazılıb "
        "və ya internet yoxdur.",
    ),
    (
        "timeout expired",
        "Bağlantı taymauta düşdü — server cavab vermir, port bağlı ola bilər.",
    ),
    (
        "connection refused",
        "Bağlantı rədd edildi — həmin port dinlənilmir (port nömrəsini yoxlayın).",
    ),
    (
        "certificate verify failed",
        "SSL sertifikatı doğrulanmadı — `sslmode` dəyəri və şəbəkə proksisini yoxlayın.",
    ),
)


def describe_failure(error: BaseException) -> str:
    """Bağlantı/sorğu nasazlığını KONKRET cümləyə çevirir.

    Sıra vacibdir: əvvəlcə SQLSTATE (serverdən gələn, lokalizasiyadan asılı
    olmayan kod), sonra mətn naxışları (şəbəkə səviyyəsi, SQLSTATE yoxdur),
    ən sonda orijinal mətn.
    """
    sqlstate = str(getattr(error, "sqlstate", "") or "")
    known = _SQLSTATE_MESSAGES.get(sqlstate)
    if known:
        return known

    text = str(error)
    lowered = text.lower()
    for needle, message in _TEXT_MESSAGES:
        if needle in lowered:
            return message

    # ORİJİNAL MƏTN GİZLƏDİLMİR — bax modul başlığı.
    return f"Bağlantı alınmadı: {text}" if text else "Bağlantı alınmadı (səbəb bilinmir)."


#: Bypass İCAZƏ VERİLƏN YEGANƏ İKİ NÖV (SEC-2 audit qərarı, aşağıda izah).
#: Set DAR saxlanılır — yeni növ bura yalnız EYNİ toyuq-yumurta arqumenti
#: yenidən yoxlanandan sonra əlavə olunmalıdır.
_BYPASS_KINDS: Final[frozenset[str]] = frozenset({"DATABASE_UNREACHABLE", "CREDENTIALS_MISSING"})


def may_open(
    *,
    actor: Employee | None,
    configured: bool,
    startup_failure_kind: StartupFailureKind | None = None,
) -> bool:
    """Konsolu açmaq icazəsi.

    ──────────────────────────────────────────────────────────────────────────
    ÜÇ VƏZİYYƏT, ÜÇ QAYDA
    ──────────────────────────────────────────────────────────────────────────
    * **Konfiqurasiya edilməmiş maşın** — hesab hələ YOXDUR, yəni səlahiyyət
      soruşmaq üçün baza lazımdır, baza isə məhz bu konsolla qurulacaq
      (toyuq-yumurta). Qapını bağlamaq konsolu faydasız edərdi.
    * **Konfiqurasiya edilmiş, LAKİN TƏTBİQ QALXA BİLMƏYƏN maşın** — eyni
      toyuq-yumurta, sadəcə gec mərhələdə: `can_switch_db` flag-i BAZADADIR,
      baza özü isə əlçatmaz OLA BİLƏR — amma YALNIZ İKİ NÖVDƏ (aşağı bax).
    * **Konfiqurasiya edilmiş və işlək maşın** — `can_switch_db` daşıyan
      `Root`. Şərt `use_cases/db_switch._require_permission` ilə EYNİDİR və
      qəsdən: konsol həmin əməliyyatların qısa yoludur, ona görə ikinci, daha
      zəif qayda icad edilməməlidir. `CEO` buraya çata BİLMİR — flag onsuz da
      `HardlockLevel.ROOT_ONLY` daşıyır.

    ──────────────────────────────────────────────────────────────────────────
    İKİNCİ HAL NİYƏ ƏLAVƏ OLUNDU — ZİDDİYYƏT AUDİTDƏ TAPILDI
    ──────────────────────────────────────────────────────────────────────────
    `screens/group_a_entry.FatalStartupScreen` başlığı konsolu texnikin yeganə
    yolu kimi elan edir: «Eyni imkan TEXNİKDƏDİR: `Ctrl+Shift+K` → Bərpa
    Konsolu». Halbuki həmin ekran məhz baza açılmayanda görünür və o anda
    `actor` HƏMİŞƏ `None`-dur (giriş mümkün deyil) — yəni sənədləşdirilmiş
    çıxış yolu FAKTİKİ olaraq bağlı idi.

    ──────────────────────────────────────────────────────────────────────────
    SEC-2 — BAYRAQ (`database_reachable: bool`) KİFAYƏT ETMİRDİ
    ──────────────────────────────────────────────────────────────────────────
    Birinci düzəliş (`database_reachable`) çılpaq `bool` idi: `self._context
    is not None` demək YALNIZ «tətbiq hazırda İŞLƏK obyekt qrafına sahibdir»
    demək idi, «BAŞLANĞIC NİYƏ UĞURSUZ OLDU» sualına cavab vermirdi.
    `StartupFailureKind` (`composition.py`) dörd fərqli səbəbi ayırır və
    `_load_context_behind_splash` onu ARTIQ hesablayır (bax `app.py`) — burada
    yalnız İSTİFADƏ olunur:

        * `DATABASE_UNREACHABLE` — server/şəbəkə əlçatmazdır, konfiqurasiya
          DÜZGÜNDÜR. Toyuq-yumurta arqumenti BURADA həqiqətən keçərlidir.
        * `CREDENTIALS_MISSING` — heç bir mənbədə bağlantı məlumatı yoxdur.
          İlk quraşdırma anıdır, `configured=False` ilə EYNİ məntiqdir.
        * `CREDENTIALS_INVALID` — BAĞLI. Baza özü İŞLƏKDİR (server cavab
          verir), sadəcə saxlanmış parol/açar səhvdir — səlahiyyət
          YOXLANILA BİLƏRDİ, sadəcə YOXLANILMADI. Toyuq-yumurta arqumenti
          burada YALANDIR.
        * `IDENTITY_UNAVAILABLE` — BAĞLI, eyni səbəblə (baza qatı ilə əlaqəsi
          yoxdur, `installation.json` problemi).
        * `startup_failure_kind is None` (gözlənilməyən istisna VƏ YA heç bir
          başlanğıc uğursuzluğu baş verməyib) — BAĞLI, FAIL-CLOSED: naməlum
          səbəb ən az etibar edilən haldır. Bu, normal iş rejimini (baza
          işləkdir, adam giriş etməyib) də əhatə edir — orada `actor is None`
          olsa da qapı HƏMİŞƏ bağlı olmalıdır, bax aşağı.

    Genişlənmə İNDİ FAKTİKİ DARDIR (əvvəlki mətn "dar" deyirdi, amma bayraq
    bunu YOXLAMIRDI — istənilən `database_reachable=False` səbəbdən keçirdi,
    o cümlədən `CREDENTIALS_INVALID` kimi əslində baza İŞLƏYƏN hallardan).
    Baza İŞLƏYİRSƏ və adam giriş etməyibsə qapı YENƏ BAĞLIDIR (giriş
    ekranında `Ctrl+Shift+K` heç nə açmır) — bunun üçün ayrıca şərtə ehtiyac
    yoxdur: bu halda `startup_failure_kind` `None`-dur, `actor` da `None`-dur,
    ona görə aşağıdakı `_BYPASS_KINDS` yoxlaması avtomatik rədd edir.

    ──────────────────────────────────────────────────────────────────────────
    QALAN QORUMALAR — DÜRÜST QİYMƏTLƏNDİRMƏ (əvvəlki mətn ŞİŞİRDİRDİ)
    ──────────────────────────────────────────────────────────────────────────
    `connection.json` `%PROGRAMDATA%`-ya yazılır (`connection_file_path()`),
    LAKİN bu, GÜCLƏNDİRİLMİŞ ikinci qat DEYİL: qovluq
    `mkdir(parents=True, exist_ok=True)` ilə yaradılır (`connection_file.py`),
    ACL BƏRKİDİLMİR. Bu, «Windows-un təsadüfi defoltu» DEYİL — `installer/
    KompasOS.iss:127` (`Permissions: users-modify`) LAYİHƏNİN ÖZ QƏRARIDIR
    (standart `%PROGRAMDATA%` əslində YALNIZ yaradana tam icazə verərdi; biz
    onu qəsdən BOŞALDIRIQ ki, kassir A-nın yazdığı ayarı kassir B-nin
    proqramı yeniləyə bilsin, bax `.iss` faylının öz şərhi). Nəticə: fiziki
    girişi olan hər kəs `connection.json`-un `host` sahəsini GUI-dan KƏNAR,
    birbaşa fayl redaktoru ilə dəyişə bilər — məhz bu, `RecoveryConsoleController`
    başlığındakı QAYDA B-nin (saxlanmış parol bypass rejimində HEÇ VAXT
    işlədilmir) NİYƏ tək «hədəf dəyişməyibsə saxla» (Qayda A) YERİNƏ KEÇMƏDİYİNİN
    sübutudur: hücumçu host-u dəyişib GUI-də EYNİ host-u yenidən yazsa, Qayda
    A onu «hədəf dəyişməyib» sanıb buraxardı. Bu, YALNIZ ƏLAVƏ maneədir,
    zəmanətli səlahiyyət sərhədi deyil. DDL üçün ayrıca elevasiyalı BAZA
    parolu YENƏ DƏ lazımdır — bu, real qalan maneədir.
    """
    if not configured:
        return True
    if actor is None:
        kind_value = startup_failure_kind.value if startup_failure_kind is not None else None
        if kind_value in _BYPASS_KINDS:
            # İz QALIR: bu yol istisna haldır və sonradan «kim, nə vaxt, NİYƏ»
            # sualı verilə bilər. Audit cədvəli əlçatmazdır (baza məhz
            # düşüb/konfiqurasiya yoxdur), ona görə yeganə mümkün yer yerli
            # `security.log`-dur. `kind` DƏ yazılır — əks halda «hansı şərtlə
            # açıldı?» sualı hələ də cavabsız qalardı.
            _security_log.warning(
                "RECOVERY_CONSOLE_OPENED_WITHOUT_DATABASE",
                extra={
                    "reason": "baza əlçatmazdır — səlahiyyət yoxlanıla bilmir",
                    "kind": kind_value,
                },
            )
            return True
        return False

    from src.domain.value_objects.authorization import SystemRole  # noqa: PLC0415

    if not actor.has_permission(SWITCH_DB_FLAG, now=_now()):
        _security_log.warning(
            "RECOVERY_CONSOLE_DENIED_FLAG", extra={"actor_id": str(getattr(actor, "id", "?"))}
        )
        return False
    if actor.position.effective_system_role is not SystemRole.ROOT:
        _security_log.warning(
            "RECOVERY_CONSOLE_DENIED_ROLE",
            extra={"actor_id": str(getattr(actor, "id", "?"))},
        )
        return False
    return True


def _now() -> Any:
    """`has_permission` üçün cari an.

    `Clock` portu BURADA İŞLƏDİLMİR və bu, qəsdli istisnadır: konsol məhz
    baza (deməli `ServerTimeService` də) əlçatmaz olanda açılır. Yerli saat
    yeganə mövcud mənbədir və o, YALNIZ flag-in müddət pəncərəsinə baxır —
    heç bir audit/hesablama buradan qidalanmır.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC)


def diagnostics() -> list[tuple[str, str]]:
    """«Proqram hansı faylı oxuyur?» sualının TAM cavabı.

    Bağlantı Ayarları ekranındakı qısa diaqnostikadan FƏRQİ odur ki, burada
    axtarılan HƏR yol ayrıca sətirdir və hər birinin yanında tapılıb-tapılmadığı
    yazılır. Qısa variant «hansı fayl işlədilir?» sualına cavab verir; bu isə
    «niyə TAPILMIR?» sualına — və o sual yalnız nasazlıqda verilir.
    """
    from src.infrastructure.config.connection_file import (  # noqa: PLC0415
        connection_file_path,
        connection_search_paths,
        load_settings,
    )
    from src.shared.data_paths import default_data_dir, default_log_dir  # noqa: PLC0415

    rows: list[tuple[str, str]] = [("Tətbiq versiyası", __version__)]
    for index, path in enumerate(connection_search_paths(), start=1):
        state = "VAR" if path.is_file() else "yoxdur"
        rows.append((f"Konfiqurasiya axtarışı {index}", f"{path}  →  {state}"))
    rows.append(("Konfiqurasiya yazılacaq yer", str(connection_file_path())))

    # ŞİFRƏ AÇILDIMI — ayrıca sətirdir, çünki «fayl var» ilə «fayl oxunur»
    # tamamilə fərqli iki haldır: DPAPI blobu dəyişəndə fayl yerində qalır,
    # lakin parol açılmır (bax `config/connection_file.py`).
    try:
        settings = load_settings()
    except Exception as error:
        rows.append(("Konfiqurasiya oxunuşu", f"XƏTA — {error}"))
    else:
        if settings is None:
            rows.append(("Konfiqurasiya oxunuşu", "fayl tapılmadı"))
        else:
            where = f"{settings.username}@{settings.host}:{settings.port}"
            rows.append(("Konfiqurasiya oxunuşu", f"OK — {where}"))

    rows.append(("Log qovluğu", str(default_log_dir())))
    rows.append(("Yerli məlumat", str(default_data_dir())))
    return rows


class RecoveryConsoleController:
    r"""Bərpa konsolunun YAZI yolu — bütün ağır işlər FON SAPINDA.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HƏR ƏMƏLİYYAT `BackgroundTask`-DADIR
    ──────────────────────────────────────────────────────────────────────────
    Buradakı dörd əməliyyatın hamısı şəbəkəyə çıxır və ən ağırı (baza quruluşu)
    onlarla SQL faylı icra edir — dəqiqələrlə çəkə bilər. GUI sapında icra
    olunsaydı, Windows pəncərəni «Cavab vermir» kimi işarələyər, istifadəçi isə
    proqramı bağlamağa çalışardı — məhz quruluşun ortasında.

    ──────────────────────────────────────────────────────────────────────────
    ELEVASİYALI PAROL — `service_role` HAQQINDA DÜRÜST QEYD
    ──────────────────────────────────────────────────────────────────────────
    Supabase-in `service_role` açarı PostgREST üçün JWT-dir; BİRBAŞA Postgres
    bağlantısı (psycopg) onu QƏBUL ETMİR — DDL üçün baza istifadəçisi və parolu
    lazımdır. Ona görə ekrandakı sahə həmin JWT deyil, YALNIZ QURULUŞ üçün
    işlədilən elevasiyalı baza paroludur: adi istifadəçinin `CREATE TABLE`
    hüququ yoxdursa, texnik ora daha səlahiyyətli hesabın parolunu yazır.
    Dəyər fayla YAZILMIR və əməliyyat başlayan kimi ekrandan da silinir.
    Sahəni «service_role JWT» kimi təqdim etmək texniki cəhətdən YALAN olardı.

    ──────────────────────────────────────────────────────────────────────────
    SEC-2 GENİŞLƏNMƏSİ — KONSOL DEŞİFRƏ ORAKULU OLA BİLMƏZ (dövrə 1 audit)
    ──────────────────────────────────────────────────────────────────────────
    `may_open()` indi `_BYPASS_KINDS`-də AVTENTİFİKASİYASIZ açılışa icazə
    verir (toyuq-yumurta arqumenti, bax həmin funksiya). Bu, öz-özlüyündə
    yeni sirr AÇMIR — LAKİN `_settings_from()`-un köhnə «boş parol = mövcudu
    saxla» davranışı ilə birləşəndə açır. Hücum zənciri:

        1. fiziki giriş (kiosk/mağaza PC-si);
        2. şəbəkə kabeli çıxarılır → növbəti açılışda `StartupFailureKind.
           DATABASE_UNREACHABLE` (konfiqurasiyanın ÖZÜ düzgündür, server
           sadəcə əlçatmazdır);
        3. `Ctrl+Shift+K` → konsol `actor=None` ilə açılır (`may_open` bunu
           İNDİ icazə verir, `_BYPASS_KINDS`);
        4. `connection.json`-un ACL-i GÜCLƏNDİRİLMİŞ DEYİL — `installer/
           KompasOS.iss:127` `Permissions: users-modify` QƏSDƏN verir (kassir
           A-nın yazdığını kassir B-nin yeniləyə bilməsi üçün, bax həmin fayl
           şərhi) — yəni fiziki girişi olan adam `host` sahəsini ÖZ Postgres
           serverinə yönəldə bilər, PAROL isə DPAPI ilə şifrəli qalır, ona
           TOXUNMUR;
        5. konsolda «Bağlantını Test Et» basılır, PAROL SAHƏSİ BOŞ buraxılır
           → köhnə `_settings_from()` bunu «dəyişmə» kimi oxuyub saxlanmış
           İSTEHSALAT parolunu (DPAPI-dən AÇIQ MƏTNDƏ) bərpa edir və onu
           HÜCUMÇUNUN öz host-una göndərir.

    Nəticə: kod icra edə BİLMƏYƏN, sadəcə fiziki UI çıxışı olan şəxs
    istehsalat baza parolunu ələ keçirir — konsol DEŞİFRƏ ORAKULU rolunu
    oynayır (fayl özü açmır, amma açıb HƏR YAZILAN hosta göndərir).

    İKİ QAYDA BİRLİKDƏ tətbiq olunur (`_same_target`, `_requires_manual_password`):

        * **QAYDA A** (bütün rejimlərdə) — saxlanmış parol YALNIZ `host` +
          `port` + `username` DƏYİŞMƏYİBSƏ təkrar istifadə olunur (dərinlikdə
          müdafiə: hədəf eyni qalıbsa parolun "sızacağı" yer də eynidir).
        * **QAYDA B** (YALNIZ `authenticated=False`, yəni konsol bypass ilə
          açılıbsa) — QAYDA A-dan ASILI OLMAYARAQ saxlanmış parol HEÇ VAXT
          işlədilmir. `same_target` TƏK BAŞINA KİFAYƏT ETMİRDİ: hücumçu
          host-u dəyişib, sonra konsolda EYNİ host-u YENİDƏN yazsa,
          `same_target` `True` qayıdır və QAYDA A onu buraxardı — ACL zəif
          olduğu üçün "hədəf dəyişməyib" fərziyyəsinin özü hücumçunun
          nəzarətindədir. Bu rejimdə boş parol sahəsi "dəyişmə" DEYİL,
          "YOXDUR" deməkdir: `_on_test`/`_on_check`/`_on_provision` şəbəkəyə
          ÇIXMIR, `_on_save` YADDA SAXLAMIR (boş parolla saxlamaq da özü
          risklidir — host hücumçunun serverinə yazılıb sonra parol əl ilə
          doldurulmadan saxlanılsaydı, YA istehsalat parolu itərdi, YA da
          gələcək bir kod yolu onu yenidən doldurub göndərərdi; sadə həll —
          BÜTÜN yazı yolunu bağlamaq).

    Avtentifikasiyalı `Root` (`can_switch_db` + rol yoxlaması `may_open`-da
    ARTIQ keçib) üçün mövcud "boş = dəyişmə" erqonomikası QALIR — sadəcə
    QAYDA A ilə məhdudlaşır. `may_open()`-in bypass şərtinin ÖZÜ BURADA
    DƏYİŞMİR — biz qapını yox, qapının arxasındakı sirri bağlayırıq.
    """

    def __init__(
        self, *, on_saved: Callable[[], None] | None = None, authenticated: bool = True
    ) -> None:
        self._on_saved = on_saved
        #: SEC-2 genişlənməsi — `False` = konsol `may_open`-un bypass şərti
        #: ilə (actor=None) açılıb. Defolt `True` seçilib ki, konsolu birbaşa
        #: quran gələcək test/çağırış «unudulduqda» sükutla ƏN SƏRT rejimə
        #: düşsün (parol reuse-u qapalı qalsın) — yanlış tərəfə düşən defolt
        #: təhlükəsizlik qapılarında ən ucuz səhvdir.
        self._authenticated = authenticated
        #: Fon işçisinə İSTİNAD saxlanılır: o, ekranın uşağıdır, lakin yalnız
        #: yerli dəyişən qalsaydı Python onu nəticə gəlməmiş toplaya bilərdi.
        self._task: Any = None

    # ------------------------------ bağlanma ---------------------------------- #

    def attach(self, screen: Any) -> None:
        """Siqnalları bağlayır və mövcud vəziyyəti göstərir."""
        screen.test_requested.connect(lambda values: self._on_test(screen, values))
        screen.save_requested.connect(lambda values: self._on_save(screen, values))
        screen.check_tables_requested.connect(lambda values: self._on_check(screen, values))
        screen.provision_requested.connect(lambda values: self._on_provision(screen, values))
        screen.open_logs_requested.connect(self._open_logs)
        screen.open_config_requested.connect(self._open_config)
        self.refresh(screen)

    def refresh(self, screen: Any) -> None:
        """Sahələri və diaqnostikanı yenidən oxuyur.

        ──────────────────────────────────────────────────────────────────────
        `load_settings()` BYPASS REJİMİNDƏ DƏ ÇAĞIRILIR — VƏ BU, QAYDA B-Nİ POZMUR
        ──────────────────────────────────────────────────────────────────────
        Dövrə 2 audit sualı (team-lead) — aydınlıq üçün açıq yazılır:

            (a) BƏLİ, bura `authenticated=False` olsa BELƏ `load_settings()`
                çağırır — yəni DPAPI blobu AÇILIR (deşifrə BAŞ VERİR).
            (b) Açılan `settings.password` AŞAĞIDAKI `screen.populate(...)`-ə
                ÖTÜRÜLMÜR (dict-də `"password"` açarı YOXDUR) və heç bir
                şəbəkə/yazı yoluna (`_settings_from`, `_on_test`, `_on_save`
                və s.) ÇATMIR — bu funksiyanın yerli dəyişəni olaraq qalıb
                metod qayıdanda zibilə gedir.
            (c) Ona görə QAYDA B-nin (sinif başlığı) POZUNTUSU DEYİL: Qayda B
                "saxlanmış parolun İSTİFADƏ OLUNMASINI" (şəbəkəyə göndərmə/
                yazma) qadağan edir, "ekranın cari konfiqurasiyanı GÖSTƏRMƏSİNİ"
                yox — texnik hansı host/port/istifadəçi adının YAZILI olduğunu
                görməlidir, əks halda SEC-2-nin bütün mənası (diaqnostika)
                itər. GƏLƏCƏKDƏ kimsə `populate()`-ə `"password": settings.
                password` ƏLAVƏ ETMƏK istəsə — BUNU ETMƏ: həmin sətir QAYDA
                B-ni bilavasitə pozardı (bypass rejimində saxlanmış parolu
                EKRANA çıxarardı).

        ──────────────────────────────────────────────────────────────────────
        DEŞİFRƏ XƏTASI DA SIZDIRMIR — YOXLANIB
        ──────────────────────────────────────────────────────────────────────
        `load_settings()` DPAPI açıla bilməyəndə `ConnectionFileError` atır
        (`connection_file.py`); `str(error)` — `KompasOSError.__init__`-in
        `message` arqumenti — HƏMİŞƏ SABİT mətndir ("Bağlantı parolu
        deşifrələnmədi"). Underlying OS/crypto xətası YALNIZ `error.
        context["error"]`-dadır, `describe_failure()` isə ORA BAXMIR (yalnız
        `sqlstate` və `str(error)` oxuyur, bax onun başlığı) — üstəlik
        DEŞİFRƏ MƏHZ UĞURSUZ OLDUĞU üçün plaintext HEÇ YARANMAYIB, sızacaq
        bir şey yoxdur.
        """
        from src.infrastructure.config.connection_file import load_settings  # noqa: PLC0415

        screen.set_diagnostics(diagnostics())
        try:
            settings = load_settings()
        except Exception as error:
            screen.set_error(describe_failure(error))
            return
        if settings is None:
            screen.set_status("Konfiqurasiya tapılmadı — sahələri doldurun.")
            return
        screen.populate(
            {
                "host": settings.host,
                "port": settings.port,
                "database": settings.database,
                "username": settings.username,
                "tenant_id": os.environ.get("KOMPASOS_TENANT_ID", ""),
                "supabase_url": os.environ.get("KOMPASOS_SUPABASE_URL", ""),
                "anon_key": os.environ.get("KOMPASOS_SUPABASE_ANON_KEY", ""),
            }
        )
        screen.set_status(
            _UNAUTHENTICATED_REFRESH_STATUS
            if not self._authenticated
            else "Mövcud ayarlar göstərilir. Parol boş qalarsa dəyişmir."
        )

    # ------------------------------ əməliyyatlar ------------------------------ #

    def _settings_from(self, values: dict[str, str]) -> Any:
        """Ekran dəyərlərindən `ConnectionSettings`; parol boşdursa — ŞƏRTLƏ — MÖVCUDU.

        Boş parol «sil» DEYİL, «dəyişmə» deməkdir — ekran parolu heç vaxt
        göstərmir, ona görə boş sahəni silmə kimi oxumaq işlək ayarı sükutla
        pozardı (`ConnectionSettingsController`-dəki eyni qərar). AMMA bu,
        YALNIZ `self._authenticated` VƏ hədəf DƏYİŞMƏYİBSƏ doğrudur — QAYDA
        A/B, izahı sinif başlığında (SEC-2 genişlənməsi).
        """
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            ConnectionSettings,
            load_settings,
        )

        password = values.get("password", "")
        # QAYDA B: avtentifikasiyasız rejimdə bu blok ÜMUMİYYƏTLƏ İŞLƏMİR —
        # saxlanmış parol bura qədər belə gəlmir, `password` boş qalır.
        if not password and self._authenticated:
            with suppress(Exception):
                current = load_settings()
                if current is not None and self._same_target(values, current):
                    password = current.password
        return ConnectionSettings(
            host=values.get("host", ""),
            port=int(values.get("port") or 5432),
            database=values.get("database") or "postgres",
            username=values.get("username", ""),
            password=password,
        )

    def _same_target(self, values: dict[str, str], current: Any) -> bool:
        """QAYDA A — saxlanmış parol YALNIZ `host`+`port`+`username` eynidirsə keçərlidir.

        `database` adı BURAYA QƏSDƏN daxil edilmir: eyni server/istifadəçi
        daxilində fərqli baza adı seçmək parolun HARA GEDƏCƏYİNİ (hansı
        şəbəkə ünvanına, hansı istifadəçi ilə) dəyişmir — yalnız hansı bazaya
        qoşulacağını. Hədəf məhz "hara" sualının cavabıdır.
        """
        try:
            port = int(values.get("port") or 5432)
        except (TypeError, ValueError):
            return False
        # `current` `Any`-dir (`ConnectionSettings` yerli idxaldadır, bax
        # çağıran) — `bool(...)` mypy üçün deyil, dürüstlük üçün: müqayisə
        # zənciri artıq `bool`, sarğı yalnız NƏTİCƏNİN tipini bəyan edir.
        return bool(
            values.get("host", "") == current.host
            and port == current.port
            and values.get("username", "") == current.username
        )

    def _requires_manual_password(self, values: dict[str, str], *, elevated: str = "") -> bool:
        """QAYDA B — avtentifikasiyasız rejimdə boş parolla YAZI/ŞƏBƏKƏ YOX.

        `elevated` (`service_role` sahəsi) YALNIZ `_on_provision`-dan gəlir:
        o sahə HEÇ VAXT diskdən bərpa olunmur (bax sinif başlığı), yəni orada
        yazılmış dəyər HƏMİŞƏ texnikin ƏL İLƏ yazdığıdır — sızma riski
        daşımır, ona görə onun mövcudluğu bu bloku YAN keçməyə icazə verir.
        """
        if self._authenticated:
            return False
        return not values.get("password", "") and not elevated

    def _run(self, screen: Any, job: Callable[[], object], *, name: str) -> None:
        """İşi fonda buraxır və nəticəni ekrana çatdırır."""
        from src.presentation.background_task import BackgroundTask  # noqa: PLC0415

        screen.set_busy(True)
        task = BackgroundTask(parent=screen, name=name)
        task.succeeded.connect(lambda payload: self._deliver(screen, payload))
        task.failed.connect(lambda error: screen.set_error(describe_failure(error)))
        task.finished.connect(lambda: screen.set_busy(False))
        self._task = task
        task.run(job)

    def _deliver(self, screen: Any, payload: object) -> None:
        """Fon işinin nəticəsi — mətn, və ya `(mətn, təsdiq lazımdır?)` cütü."""
        if isinstance(payload, tuple) and len(payload) == _RESULT_PAIR:
            message, needs_confirmation = payload
            screen.set_status(str(message))
            screen.require_confirmation(bool(needs_confirmation))
            return
        screen.set_status(str(payload))

    def _on_test(self, screen: Any, values: dict[str, str]) -> None:
        # QAYDA B (sinif başlığı, SEC-2 genişlənməsi) — avtentifikasiyasız
        # rejimdə boş parolla ŞƏBƏKƏYƏ ÇIXILMIR: `_settings_from` bu halda
        # saxlanmış parolu HEÇ VAXT doldurmur, yəni davam etsəydik boş
        # parolla naməlum hosta qoşulmağa CƏHD edərdik — bunun özü də
        # diaqnostik siqnal sızdırar (host əlçatandırmı, auth metodu nədir).
        if self._requires_manual_password(values):
            screen.set_error(_UNAUTHENTICATED_NETWORK_BLOCKED)
            return
        settings = self._settings_from(values)

        def job() -> object:
            from src.infrastructure.persistence.connection import probe_dsn  # noqa: PLC0415

            probe_dsn(settings.dsn())
            return f"Bağlantı UĞURLUDUR — {settings.username}@{settings.host}:{settings.port}"

        self._run(screen, job, name="RECOVERY_TEST")

    def _on_save(self, screen: Any, values: dict[str, str]) -> None:
        # QAYDA B — boş parolla YADDA SAXLAMA da bağlıdır: sadəcə "yerli
        # yazı, təhlükəsizdir" DEYİL — host hücumçunun serverinə dəyişilib
        # parol boş saxlanılsa, NÖVBƏTİ AÇILIŞ tətbiqi ora bağlayar (gecikmiş
        # sızma forması, bax sinif başlığı) VƏ ya sadəcə istehsalat parolunu
        # sükutla SİLƏR — hər iki nəticə də qəbuledilməzdir.
        if self._requires_manual_password(values):
            screen.set_error(_UNAUTHENTICATED_SAVE_BLOCKED)
            return
        settings = self._settings_from(values)
        callback = self._on_saved

        def job() -> object:
            from src.infrastructure.config.connection_file import save_settings  # noqa: PLC0415

            target = save_settings(settings)
            return f"Yadda saxlanıldı: {target}"

        self._run(screen, job, name="RECOVERY_SAVE")
        if callback is not None:
            callback()

    def _on_check(self, screen: Any, values: dict[str, str]) -> None:
        # QAYDA B — bax `_on_test` eyni şərhi.
        if self._requires_manual_password(values):
            screen.set_error(_UNAUTHENTICATED_NETWORK_BLOCKED)
            return
        settings = self._settings_from(values)

        def job() -> object:
            import psycopg  # noqa: PLC0415

            from src.infrastructure.persistence.provisioning import (  # noqa: PLC0415
                existing_tables,
                expected_tables,
                missing_tables,
            )

            with psycopg.connect(settings.dsn(), connect_timeout=15) as conn, conn.cursor() as cur:
                existing = existing_tables(cur)
            missing = missing_tables(expected=expected_tables(), existing=existing)
            if not missing:
                return f"Bütün cədvəllər yerindədir ({len(existing)} cədvəl)."
            preview = ", ".join(missing[:_PREVIEW_LIMIT])
            suffix = "…" if len(missing) > _PREVIEW_LIMIT else ""
            return f"ÇATIŞAN {len(missing)} cədvəl: {preview}{suffix}"

        self._run(screen, job, name="RECOVERY_TABLES")

    def _on_provision(self, screen: Any, values: dict[str, str]) -> None:
        elevated = values.get("service_role", "")
        # QAYDA B — bax `_on_test` şərhi. `elevated` BURADA NƏZƏRƏ ALINIR:
        # o sahə diskdən heç vaxt bərpa olunmur (həmişə ƏL İLƏ yazılır),
        # yəni onun mövcudluğu QAYDA B-nin qorumaq istədiyi riski daşımır.
        if self._requires_manual_password(values, elevated=elevated):
            screen.set_error(_UNAUTHENTICATED_NETWORK_BLOCKED)
            return
        settings = self._settings_from(values)
        confirmation = values.get("confirmation", "")

        def job() -> object:
            import psycopg  # noqa: PLC0415

            from src.infrastructure.config.connection_file import (  # noqa: PLC0415
                ConnectionSettings,
            )
            from src.infrastructure.persistence.provisioning import (  # noqa: PLC0415
                inspect_database,
                provision,
            )

            target = settings
            if elevated:
                target = ConnectionSettings(
                    host=settings.host,
                    port=settings.port,
                    database=settings.database,
                    username=settings.username,
                    password=elevated,
                )

            # `autocommit=True` MƏCBURİDİR: fayllarda ÖZ `BEGIN;`/`COMMIT;`
            # cütü var (bax `provisioning.provision`).
            with (
                psycopg.connect(target.dsn(), connect_timeout=30, autocommit=True) as conn,
                conn.cursor() as cur,
            ):
                state = inspect_database(cur)
                if state.requires_confirmation and not state.accepts(confirmation):
                    rows = ", ".join(f"{name} ({count})" for name, count in state.populated_tables)
                    return (
                        f"DİQQƏT: bu bazada artıq məlumat var — {rows}. "
                        "Davam etmək data itkisinə səbəb ola bilər. "
                        "Təsdiq üçün «QUR» sözünü yazıb yenidən basın.",
                        True,
                    )
                report = provision(cur, confirmation=confirmation)

            if report.error:
                return (f"Quruluş DAYANDI — {report.error}", False)
            if report.missing_after:
                names = ", ".join(report.missing_after[:_PREVIEW_LIMIT])
                return (
                    f"Quruluş bitdi, lakin {len(report.missing_after)} cədvəl çatışır: {names}",
                    False,
                )
            return (
                f"HAZIRDIR — {len(report.applied)} miqrasiya tətbiq olundu, "
                f"{len(report.skipped)} artıq mövcud idi. İndi tətbiqi yenidən başladın.",
                False,
            )

        self._run(screen, job, name="RECOVERY_PROVISION")
        # Açar EKRANDAN dərhal silinir — nəticə gözlənilərkən də görünməməlidir.
        screen.clear_service_role()

    # ------------------------------ qovluqlar --------------------------------- #

    def _open_logs(self) -> None:
        from src.shared.data_paths import default_log_dir  # noqa: PLC0415

        _reveal(default_log_dir())

    def _open_config(self) -> None:
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            connection_file_path,
        )

        _reveal(connection_file_path().parent)


def _reveal(path: Path) -> None:
    """Qovluğu sistem fayl menecerində açır.

    `QDesktopServices` işlədilir, `explorer.exe` YOX: birincisi Qt-nin öz
    platformalararası yoludur və `subprocess` açmır — yəni paketlənmiş
    tətbiqdə antivirus evristikasına düşmür (SEC-027 ilə eyni məntiq).
    """
    from PySide6.QtCore import QUrl  # noqa: PLC0415
    from PySide6.QtGui import QDesktopServices  # noqa: PLC0415

    with suppress(OSError):
        path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


__all__ = [
    "SWITCH_DB_FLAG",
    "RecoveryConsoleController",
    "describe_failure",
    "diagnostics",
    "may_open",
]
