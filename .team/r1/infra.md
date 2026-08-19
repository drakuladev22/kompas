# DÖVRƏ 1 — infra hesabatı
[INF-01] MED repositories.py:1381 — except UniqueViolation İKİ indeksi eyni DuplicateFineSubmissionError-a
  çevirir (uq_fines_manual_camera_idempotency_key VƏ uq_fines_one_live_auto_delay_per_leave, schema.sql:952).
  ARCHITECT TƏSDİQLƏDİ: hər iki indeks mövcuddur. Davranış təsiri YOXDUR (AUTO_DELAY yolu —
  leave_verification.step_create_fine — bu istisnanı TUTMUR; yalnız fine_management.py:295 tutur, o da manual yol),
  yəni zərər DİAQNOSTİKDİR. Həll: constraint_name-ə görə budaqlanma.
[INF-02] MED onboard_new_tenant.py — --tenant-id / --license-key CÜT tələb olunmur; yalnız biri veriləndə
  YENİ təsadüfi açar yaranıb müştəri konfiqinə yazılır (DB-dəki köhnə açar isə qalır) → gələcəkdə sükutlu uyğunsuzluq.
[INF-03] LOW migration 070:104 — şərh employee.py:246 deyir, faktiki sətir 258.
[INF-04] LOW migration 070:203 — şərh «add_notice_handler qurulmur» deyir, EYNİ dəstdə qurulub (köhnəlib).
TƏMİZ: 069-074 hamısı idempotent + DOWN + §7 parity düzgün; connection.py 4 yeni repo; composition.py bağlantıları;
  FailSoftSecurityEventRecorder sarğısı; telegram_repositories self._tenant gücləndirməsi; upload_queue SEC-4.
SUAL -> domain: INF-01 constraint budaqlanması, yoxsa AUTO_DELAY-ə də daimi idempotency_key?
