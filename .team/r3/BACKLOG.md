# DÖVRƏ 3 üçün açıq siyahı (ARCHITECT)

[ARCH-03] MED-HIGH — İKİ MƏNBƏ, SİFİR SİNXRONLAŞMA (domain tapdı, dövrə 2 sonu)
  `KOMPASOS_STORE_ID` (app.py:4016, kioskun PIN axtarışını FAKTİKİ təyin edən YEGANƏ mənbə)
  ilə `RegisteredDevice.store_id` (device_registry.py:405 — YALNIZ audit yazısında istifadə olunur)
  heç vaxt uzlaşmır. Admin `reassign_store()` ilə cihazı B mağazasına köçürür → Root panelində
  cihaz B-dədir, kiosk isə A-nın işçilərini axtarmağa davam edir. Xəbərdarlıq YOXDUR.
  Qərar lazımdır: (a) kiosk açılışda ikisini müqayisə edib uyğunsuzluğu göstərsin,
  (b) DB mənbəyi qalib gəlsin, (c) yalnız sənədləşdirilsin.

[ARCH-04] MED — KONTROLLER QATININ KOR NÖQTƏSİ (qa tapdı)
  10 kontroller LİTERAL 0% örtük, 8-i `.commit()` çağıran yazı yoludur, 5-inin adı `tests/`-də
  ümumiyyətlə çəkilmir. Ən riskli üçlük: pos_threshold.py (pul), employee_documents.py (şəxsi
  məlumat), open_shift.py (növbə bazarı yazı yolu).

[SEC-03] LOW — crash_reporter.scrub() denylist-i genişləndirilsin (nümunələr: .team/r3/SEC-03-scrub-patterns.md)

[INF2-02-GENİŞ] — 154 metod / ~40 fayl `self._tenant` naxışına keçirilməsi.
  BU AUDİTDƏ QƏSDƏN EDİLMƏDİ (miqyas + RLS onsuz da qoruyur). Ayrıca planlaşdırılmalıdır.

[ARCH-01] MED — PENDING_RECONCILIATION uzlaşdırma axını: repo + startup xəbərdarlığı var,
  İSTEHLAKÇI ekran/use case YOXDUR. domain-in dizaynı: blind-replay YOX; diaqnostika +
  mövcud use case-lərə yönləndirmə + məcburi resolution_reason ilə status bağlanması.

[SEC-01] HIGH — terminal/mağaza səviyyəli PIN throttle (dedikatə cədvəl, system_limits həddi).
  Dövrə 1-də tapıldı, koordinasiyalı iş olduğu üçün təxirə salındı.

## DÖVRƏ 3-də əlavə olunanlar
[D3-04] LOW ui — support_chat.py: canlı söhbətdə `add_separator()` heç vaxt çağırılmır (tarix ayırıcısı yoxdur).
[D3-05] LOW-MED ui — group_d.py:283 ErpServersScreen sıfır server halında EmptyState işlətmir (14 digər ekran işlədir).
[INF3-01] LOW infra — crash_reporter `_LONG_DIGITS` (PRE-EXISTING) 4+ rəqəmli hər ardıcıllığı gizlədir,
  o cümlədən `port=5432` kimi DİAQNOSTİK dəyəri. Həddindən artıq təmizləmə də qüsurdur — hesabat
  oxunmaz olur. security-nin rəyi lazımdır.
[QA-R3] qalan 7 sıfır-örtüklü kontroller: devices, plugin_page, sales_points, performance_review,
  tasks, announcements, attrition_risk. + aşağı örtüklü: support_inbox 18%, face_setup 21%,
  drive_connection 44%, screen_data 46%.
