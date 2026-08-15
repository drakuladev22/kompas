KompasOS-un pəncərə-davranışını Windows-un native standartına (Chrome,
Discord kimi) tam uyğunlaşdırıram: Aero Snap (yuxarı/yan-kənara sürüşdürüb
buraxanda animasiyalı tam-ekran/yarım-ekran), Windows 11 Snap Layouts,
düzgün minimize/maximize/close düymələri, VƏ pəncərə ölçüsünə görə daxili
tərtibatın (layout) uyğunlaşması (responsive).

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud işləyən GUI-ni (ekranlar, naviqasiya, dizayn sistemi) SİLMƏ/YENİDƏN
QURMA — yalnız pəncərə-səviyyəli (window chrome) qatını təkmilləşdir.

===============================================================================
TEXNİKİ YANAŞMA (ARAŞDIRILIB, QƏTİ QƏRAR)
===============================================================================
Mövcud custom title bar (—, □, × düymələri, loqo sol yuxarıda) əl ilə
yazılmış frameless-window məntiqi ilə qurulubsa, bu, Windows-un native
Aero Snap-ini AVTOMATİK DƏSTƏKLƏMİR (Qt-də frameless pəncərə native OS-
davranışını itirir, bu, məlum bir problemdir). Bunun HƏLLİ:

`qframelesswindow` kitabxanəsini (PySide6 branch-i, PyPI-da
`PySideSix-Frameless-Window` adı ilə də var) `requirements.txt`-ə əlavə
et — bu, məhz bu problemi həll etmək üçün yazılıb: native Windows Aero
Snap, DPI-aware hit-testing, cross-platform resize. Mövcud `FramelessWindow`/
`FramelessMainWindow` bazasından İRƏLİ GEDƏRƏK öz Main Window-umuzu qur
(sıfırdan yazma, bu kitabxananın verdiyi əsası genişləndir).

**VACİB:** Bu kitabxanada Windows 11 Snap Layouts (maximize düyməsinin
üzərinə saat gəzdirəndə çıxan tərtibat-seçimləri) DEFOLT AKTİV DEYİL —
kitabxananın öz sənədləşməsində/GitHub issue-larında bunun necə aktiv
ediləcəyini TAP və tətbiq et (axtarış açar sözü: "snap layout" bu
kitabxananın repo-sunda).

===============================================================================
ADDIM 1 — PƏNCƏRƏ-İDARƏETMƏ DÜYMƏLƏRİ
===============================================================================
1. Minimize (—), Maximize/Restore (□/⧉), Close (×) düymələri native
   Windows davranışı ilə tam işləsin: minimize → Taskbar-a düşür,
   maximize → tam-ekran, artıq-maximized-ikən düymə RESTORE ikonuna
   (iki üst-üstə düşən kvadrat) DƏYİŞİR.
2. **İKON KEYFİYYƏTİ:** Bu 3+1 düymənin ikonlarını mövcud dizayn
   sisteminin "minimal line-based" ikon dilinə (Lucide/Feather tərzi)
   UYĞUNLAŞDIR — generic/defolt Qt ikonları ilə QALMA, sadə, nazik-xətli,
   dark/light hər ikisində aydın oxunan versiyalar qur.
3. Close düyməsinə hover-da standart qırmızı-fon effekti (Windows/Chrome
   konvensiyası) əlavə et.

===============================================================================
ADDIM 2 — AERO SNAP VƏ SNAP LAYOUTS
===============================================================================
1. Title bar-ı yuxarı ekran-kənarına sürüşdürüb buraxanda → pəncərə
   Windows-un öz native animasiyası ilə tam-ekrana keçsin (bizim özümüz
   animasiya YAZMIRIQ — bu, Windows-un DWM-inin öz işidir, kitabxana
   düzgün hit-testing versə, bu, AVTOMATİK işləyir).
2. Sol/sağ ekran-kənarına sürüşdürüb buraxanda → yarım-ekran snap.
3. Windows 11 Snap Layouts (maximize düyməsi üzərinə saat) aktivdir.
4. Test: bu 3 davranışı REAL Windows mühitində (VM və ya real PC) əl ilə
   sına, GIF/skrinşot əvəzinə mətnlə təsvir et ("sürüşdürdüm, animasiya
   işlədi/işləmədi").

===============================================================================
ADDIM 3 — RESPONSIVE DAXİLİ TƏRTİBAT (PƏNCƏRƏ ÖLÇÜSÜNƏ GÖRƏ)
===============================================================================
Mövcud "sol naviqasiya paneli daralda bilər" xüsusiyyətini FORMAL
BREAKPOINT sisteminə çevir:

- **Standart/geniş** (pəncərə eni ≥ 1280px — ROOT PARAMETRİ deyil, bu,
  UI-konfiqurasiya sabiti, kod-səviyyəli dəyişən kimi saxla): sol
  naviqasiya tam (ikon+mətn), bütün widget-lər tam en ilə.
- **Sıxılmış/snap-yarısı** (pəncərə eni 700-1280px arası — Windows-da
  yarım-ekran snap edəndə bu diapazona düşəcək): sol naviqasiya
  AVTOMATİK ikon-yalnız rejiminə keçir (mövcud daralma funksiyasını
  ÇAĞIRARAQ), Dashboard widget-ləri 1 sütuna yığılır.
- **Minimum** (700px-dən az — pəncərənin öz minimum-eni ilə məhdudlaşdırıla
  bilər): əgər praktiki deyilsə, pəncərənin öz minimum ölçüsünü bu
  həddə qoy (istifadəçi bundan kiçik edə bilməsin) əvəzinə mürəkkəb
  əlavə breakpoint qurma.

Bunu `resizeEvent`-ə bağlı bir mərkəzi funksiya ilə et (hər widget öz-
özünə yoxlamasın, mərkəzi bir "layout mode" siqnalına abunə olsun) —
təkrarlanan kod yaranmasın.

===============================================================================
ADDIM 4 — TƏHVİL-VERMƏ
===============================================================================
1. `git diff --stat` — mövcud ekranların strukturu qorunub təsdiqlə.
2. Real sınaq nəticələrini göstər (Addım 2-nin 4 test-halı).
3. Dark/light hər ikisində düymə-ikonlarının görünüşünü təsdiqlə.
4. Git-də "native-window-behavior-v1" tag-i ilə commit et.

QAYDA: Bitirdikdən sonra DAYAN, mənə nəticəni göstər.
