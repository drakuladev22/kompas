# DÖVRƏ 1 — BÜTÜN TAPINTILAR (ARCHITECT yığdı, çarpaz faza üçün)

## BLOCKER / HIGH
[UI-01] BLOCKER recovery_console.py:112-213 + app.py:895 — `may_open()` indi `configured=True`
  maşında `actor=None` ikən `DATABASE_UNREACHABLE`/`CREDENTIALS_MISSING` halında bypass edir.
  ARCHITECT TƏSDİQİ: `git show HEAD` göstərir ki, ƏVVƏL bu hal ŞƏRTSİZ `return False` idi — yəni
  bu diff DEPLOY OLUNMUŞ maşında YENİ autentifikasiyasız yol açır. Şəbəkə kabelini çıxarmaq
  `DATABASE_UNREACHABLE` üçün kifayətdir.
  ARCHITECT ƏLAVƏSİ (heç kim tapmamışdı) — SIZMA ZƏNCİRİ: `_on_test/_on_save/_on_check/_on_provision`
  hamısı `_settings_from()`-dan keçir (sətir 400-449); o isə BOŞ parol sahəsini «dəyişmə» kimi oxuyub
  `load_settings().password` — YƏNİ İSTEHSALAT DB PAROLUNU — bərpa edir (sətir 364-370).
  Hücum: host-u öz Postgres serverinə yönəlt, parolu BOŞ burax, «Bağlantını Yoxla» → psycopg
  hücumçunun serverinin tələb etdiyi `password` auth metoduna AÇIQ MƏTNLƏ parolu göndərir.
  Nəticə: fiziki girişi olan istənilən şəxs istehsalat baza parolunu ələ keçirir.
  QEYD: dəyişikliyin MOTİVİ HƏQİQİDİR — `FatalStartupScreen` konsolu texnikin yeganə yolu elan edir,
  köhnə qapı isə məhz o anda bağlı idi. Problem motivdə yox, açılan qapının ENİNDƏDİR.

[UI-02] HIGH session_guard.py:189-213 + app.py:1601-1638 — `_touch_session` GUI sapında sinxron
  `context.session()` + `validate()` + `touch()` + `commit()` edir, `QApplication.eventFilter`-dən
  çağırılır. ~200+ ms donma, throttle-a baxmayaraq (5 dəq-dən bir). UI-1 dərsinin təkrarı.

[SEC-01] HIGH authentication.py:463 — `register_failure()` ÖLÜ KOD (yalnız testlərdən çağırılır).
  ARCHITECT TƏSDİQİ: `employees.pin_locked_until` YALNIZ bu metodla yazılır → PIN lockout
  siyasəti HEÇ VAXT işə düşmür. face_control-un lockout-u İŞLƏYİR (face_control.py:1288).
  group_a_kiosk.py:398 şərhi «bloklama işçi-başınadır» deyir — baş vermir.
  STRUKTUR: PIN anonimdir; yanlış PIN-də «hansı işçi» sualı cavabsızdır → işçi-başına lockout
  PRİNSİPCƏ əlçatmazdır. Həll terminal/mağaza səviyyəli throttle olmalıdır.

## MED
[ARCH-01] (DOM-03 gücləndirilmiş) `PENDING_RECONCILIATION` — bu diff `PostgresSagaStateRepository.
  list_pending_reconciliation()` YAZIB və `main.py:231` açılışda «N saga insan müdaxiləsi gözləyir»
  ERROR verir, AMMA bu siyahını oxuyan HEÇ BİR use case/ekran YOXDUR. Yarımçıq axın: problem
  bildirilir, alət verilmir.
[INF-01] repositories.py:1381 — `except UniqueViolation` İKİ indeksi eyni `DuplicateFineSubmissionError`-a
  çevirir. ARCHITECT TƏSDİQİ: davranış təsiri YOXDUR (AUTO_DELAY yolu bu istisnanı tutmur;
  yalnız fine_management.py:295 tutur = manual yol). Zərər DİAQNOSTİKDİR.
[INF-02] onboard_new_tenant.py — `--tenant-id`/`--license-key` cüt tələb olunmur; yalnız biri
  veriləndə YENİ təsadüfi açar müştəri konfiqinə yazılır.

## LOW
[SEC-02] session_guard — uzaqdan ləğv 1-5 dəq gecikir (şüurlu trade-off, sənədləşdirilməlidir).
[DOM-01] ports.py:1512 `limit: int = 10` — şərhsiz sabit.
[DOM-02] fine_management.py:83 `DUPLICATE_SUBMISSION_WINDOW_SECONDS=10` — CLAUDE.md §5 BAĞLI cədvəlinə yazılmayıb.
[INF-03] migration 070:104 — şərh `employee.py:246` deyir, faktiki sətir 258.
[INF-04] migration 070:203 — şərh «add_notice_handler qurulmur» deyir, EYNİ dəstdə qurulub.
[ARCH-02] repositories.py:22 — infrastruktur `src.application.use_cases.fine_management`-dan idxal edir
  və `ports.py:773` (DOMEN) tətbiq qatının istisnasını kontraktında adlandırır. CLAUDE.md §3-ün
  «port yalnız domen tipləri» prinsipinin ruhuna ziddir. Yeni deyil, amma qeydə alınmalıdır.

## TƏMİZ ELAN OLUNAN SAHƏLƏR
encryption.py, dual_control_guard/permission_guards, auth_session zənciri, miqrasiya 069-074 (hamısı
idempotent + DOWN + §7 parity), connection.py/composition.py bağlantıları, telegram_repositories
tenant gücləndirməsi, upload_queue SEC-4, LAYOUT-1 düzəlişləri, permission_matrix, buttons/focus_ring,
group_i plugin boş-vəziyyəti, profile/settings sessiya siyahısı, Clock portu, Feature Toggle retroaktivliyi,
hadisə yayımı/rollback, SQL parametrizasiya, TIME-1.
