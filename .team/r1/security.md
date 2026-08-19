# DÖVRƏ 1 — security hesabatı
[SEC-01] HIGH authentication.py:463 register_failure() ÖLÜ KOD — yalnız testlərdən çağırılır.
  ARCHITECT TƏSDİQLƏDİ: employees.pin_locked_until YALNIZ bu metodla yazılır → PIN lockout
  siyasəti (PIN_MAX_FAILED_ATTEMPTS=5) HEÇ VAXT işə düşmür. face_control-un öz lockout-u İŞLƏYİR
  (face_control.py:1288) — deməli boşluq yalnız PIN-dədir. Əlavə: group_a_kiosk.py:398 şərhi
  «bloklama işçi-başınadır» deyir — baş vermir. SEC-7 bu ölü koda logging əlavə edib (yanıldıcı).
  STRUKTUR PROBLEM: PIN anonimdir — yanlış PIN-də «hansı işçi» sualı cavabsızdır, ona görə
  işçi-başına lockout PRİNSİPCƏ əlçatmazdır. Həll terminal/mağaza səviyyəli throttle olmalıdır.
[SEC-02] LOW session_guard.py — uzaqdan sessiya ləğvi 1-5 dəq gecikir (şüurlu trade-off, sənədləşdirmə tövsiyəsi).
TƏMİZ: encryption.py refaktoru, dual_control_guard/permission_guards (yalnız SEC-7 əlavəsi),
  auth_session zənciri, miqrasiya 072, recovery_console SEC-2 bypass qapısı (adopt_context sıfırlayır),
  permission_matrix (server qapısı qalır), SQL parametrizasiya, TIME-1, sirlərin sızması.
