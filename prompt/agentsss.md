# TEAM-SETUP: KOMPASOS ÜÇÜN 5-NƏFƏRLİK AGENT KOMANDASI + SKILL-LƏR

Bu prompt: (1) lazımi skill-ləri qurur, (2) 5 teammate spawn edir,
(3) onlara canlıya-çıxış işini paylayır. Teammate-lər bir-biri ilə
danışacaq, hər biri AYRI fayl dəstinə sahibdir (toqquşma olmasın).

===============================================================================
⚠️ TOKEN XƏBƏRDARLIĞI
===============================================================================
Agent teams hər teammate üçün ayrı Claude instansiyası işlədir — token
istifadəsi teammate sayına görə xətti artır. Mənim həftəlik limitim
məhduddur. Ona görə:
- Teammate-lər **Sonnet** işlətsin (lead Opus qalsın)
- Hər teammate işini bitirəndə DƏRHAL hesabat versin, boş-boş gəzməsin
- Lead teammate-lərin işini gözləsin, ÖZÜ paralel iş görməsin

===============================================================================
ADDIM 0 — AGENT TEAMS-İ AKTİVLƏŞDİR
===============================================================================
`.claude/settings.json`-a əlavə et (mövcud ayarları silmədən):
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```
Yadda saxla, təsdiqlə.

===============================================================================
ADDIM 1 — 3 SKILL YARAT (VARSA TƏKRAR YARATMA)
===============================================================================
`.claude/skills/` qovluğunda (yoxdursa yarat). Bu skill-lər BÜTÜN
teammate-lərə avtomatik yüklənəcək — layihənin dəyişməz qaydalarını
hər teammate bilməlidir.

--- skill 1: `kompasos-architecture` ---
Məzmun (SKILL.md):
- **DƏYİŞMƏZ İYERARXİYA:** Root=0 (tək başına ən üst) → CEO=1 →
  Admin=2 → HR_Admin/Mağaza_Meneceri/Kamera_Nəzarətçisi=3 → Satıcı=4.
  Root və CEO EYNİ pillədə DEYİL.
- **HARDLOCK QAYDALARI (heç vaxt pozulmaz):** `can_manage_permissions`
  və `can_manage_system_limits` YALNIZ Root; `can_manage_positions`
  Root+CEO; `can_verify_returns`/`can_override_return_time`/
  `can_issue_fines`/`can_approve_dual_control_override` HEÇ VAXT
  Mağaza_Meneceri/Satıcı-ya (Root-un özü belə verə bilməz).
- **ROOT PARAMETRİ QAYDASI:** Konfiqurasiya edilə bilən HƏR ədəd/həddi/
  müddət `system_limits`-də olmalıdır, koda hardcode EDİLMİR.
- **QIRMIZI XƏTT:** Mövcud işləyən funksiya SİLİNMİR/YENİDƏN YAZILMIR —
  yalnız əlavə edilir və ya minimal düzəldilir.
- **1C SƏRHƏDİ:** 1C-yə yeni bağlantı nöqtəsi AÇILMIR (yalnız mövcud
  bal/satış kanalı).
- **DİL:** Bütün istifadəçi-mətnləri Azərbaycan dilində.

--- skill 2: `kompasos-security` ---
Məzmun (SKILL.md):
- Təhlükəsizlik CLIENT-də deyil, SERVERDƏ olur: UI-nı gizlətmək qorunma
  DEYİL, Supabase RLS + server-tərəfi yoxlama əsasdır.
- Vendor cədvəlləri (`tenants`, `vendor_accounts`, ödəniş) adi tenant
  istifadəçisindən RLS ilə qorunmalıdır.
- `service_role` açarı HEÇ VAXT `.exe`-yə paketlənmir.
- SQL sorğuları HƏMİŞƏ parametrized (string birləşdirmə YOX).
- Loglara token/parol/PII/üz-embedding YAZILMIR.
- İşçi deaktiv olanda `face_embedding` HƏQİQƏTƏN silinir (biometrik =
  hüquqi tələb).
- Kritik vaxt-möhürləri SERVER vaxtı ilə (client vaxtına etibar YOX).

--- skill 3: `kompasos-ui` ---
Məzmun (SKILL.md):
- Rəng palitrası: Deep Navy `#0B1D3A` + Amber `#F5A623` (proqram
  daxili). Turkuaz/yaşıl YALNIZ loqoda.
- Dark VƏ light — hər ikisi məcburi, WCAG AA kontrast.
- "GÖRMƏK = SƏLAHİYYƏTİN OLMASI": icazəsiz element boz DEYİL, tamamilə
  render olunmur.
- **UI THREAD BLOKLANMIR:** DB/şəbəkə/üz-tanıma/export əməliyyatları
  `QThread`/`QThreadPool` ilə arxa planda; hər uzun əməliyyatda progress
  göstəricisi.
- Ölçülər dizayn-tokenlərindən (hardcode YOX).
- Masaüstü konvensiyaları: sabit sol panel (hamburger YOX), custom title
  bar, native Aero Snap.

===============================================================================
ADDIM 2 — 5 TEAMMATE SPAWN ET (FAYL SAHİBLİYİ İLƏ)
===============================================================================
Hər teammate AYRI fayl dəstinə sahibdir — eyni faylı iki nəfər
redaktə ETMƏSİN. Hamısı **Sonnet** işlətsin.

**1. `security` (Təhlükəsizlik)**
Sahiblik: RLS/migration təhlükəsizlik faylları, permission-guard kodu,
şifrələmə modulu, `scripts/` (seed/onboarding).
Tapşırıq: Supabase RLS-in bütün cədvəllərdə aktiv olduğunu, vendor
cədvəllərinin qorunduğunu, hardlock qaydalarının DB-səviyyəsində
(trigger/constraint) tətbiq olunduğunu, `.exe`-də sirr qalmadığını,
SQL injection olmadığını yoxla və düzəlt. Tapdığın hər problemi ilgili
teammate-ə MESAJ GÖNDƏR (məs. use case-də yoxlama çatışmırsa →
`domain`-ə).

**2. `domain` (Biznes məntiqi)**
Sahiblik: `src/domain/`, use case-lər.
Tapşırıq: Server-vaxt bütövlüyü (kritik vaxt-möhürləri server vaxtı ilə),
icazə-yoxlamalarının UI-dan ƏLAVƏ use case səviyyəsində də olması,
biznes qaydalarının (cərimə, shift, məzuniyyət) düzgünlüyü. `security`
və `qa`-dan gələn mesajlara cavab ver.

**3. `infra` (İnfrastruktur)**
Sahiblik: `src/infrastructure/`, `migrations/`, config/bağlantı kodu,
`.spec`, `installer/`.
Tapşırıq: Miqrasiyaların təmiz bazada sıfırdan tətbiqi, config yolu
(`.exe` qovluğu → ProgramData), `--onedir` build, Inno Setup, Telegram
bağlantısı. Schema dəyişikliyi lazım olsa `domain` və `security` ilə
razılaşdır.

**4. `ui` (İnterfeys)**
Sahiblik: `src/presentation/` (və ya GUI qovluğu nə adlanırsa), QSS/
stil faylları.
Tapşırıq: UI donma probleminin həlli (threading), düymə bağlantılarının
(`.connect()`) tamlığı, sol naviqasiya/header/title bar düzəlişləri,
dark/light yoxlaması. `domain`-dən funksiya-imzası dəyişikliyi gəlsə
uyğunlaşdır.

**5. `qa` (Yoxlama)**
Sahiblik: `tests/`.
Tapşırıq: `pytest` tam paketini işə sal, uğursuzları tam traceback ilə
göstər; kod-toqquşmalarını (dublikat cədvəl/sinif adı, dairəvi import)
tap; `python main.py` startup xətalarını tut. Tapdığın hər problemi
ilgili teammate-ə birbaşa mesaj göndər. HEÇ BİR src faylını özün
DƏYİŞMƏ — yalnız test yaz və problemi sahibinə bildir.

===============================================================================
ADDIM 3 — İŞ ÜSULU: DÖVRƏVİ DEBAT (ƏSAS MEXANİZM)
===============================================================================
Bu, bir dəfəlik audit DEYİL. Teammate-lər **bir-biri ilə danışaraq,
sorğulayaraq, dövrə-dövrə** boşluqları tapıb düzəldəcəklər.

**HƏR DÖVRƏ 3 MƏRHƏLƏDƏN İBARƏTDİR:**

**Mərhələ A — Tap və Paylaş**
Hər teammate öz sahəsində boşluq/məntiqi xəta axtarır, tapdığını
QISACA lead-ə VƏ ilgili teammate-lərə mesajla bildirir.

**Mərhələ B — Çarpaz Sorğulama (ƏN VACİB)**
Hər teammate DİGƏRLƏRİNİN tapıntılarını oxuyur və **öz sahəsindən**
sual verir. Bu, məcburidir — susmaq olmaz. Nümunələr:
- `security` → `domain`: "Bu use case-də icazə yoxlaması yalnız UI-dadır,
  serverdə niyə yoxdur?"
- `qa` → `infra`: "Bu miqrasiya təmiz bazada sınır, niyə?"
- `domain` → `ui`: "Bu ekran mənim use case-imi köhnə imza ilə çağırır,
  uyğunlaşdırdınmı?"
- `ui` → `domain`: "Bu əməliyyat 4 saniyə çəkir, arxa plana köçürülməli
  amma use case sinxrondur — dəyişə bilərsənmi?"
- `infra` → `security`: "Bu cədvəldə RLS yoxdur, qəsdəndirmi?"

**Qayda:** Bir teammate-in tapıntısı BAŞQASININ sahəsinə toxunursa,
ÖZÜ düzəltmir — sahibinə mesaj göndərir, o düzəldir, sonra təsdiqləyir.

**Mərhələ C — Düzəlt və Təsdiqlə**
Hər kəs öz sahəsindəki (özünün tapdığı + başqasından gələn) problemləri
düzəldir. Düzəldəndən sonra sorğu göndərənə "düzəltdim, yoxla" mesajı
göndərir. Sorğu göndərən TƏSDİQLƏYİR və ya "hələ də problem var" deyir.

---

**DÖVRƏ TƏKRARLANIR** — Mərhələ C bitəndə yeni dövrə başlayır (çünki
düzəlişlər yeni boşluqlar aça bilər).

**DAYANMA ŞƏRTİ (hansı əvvəl gəlirsə):**
1. Bir tam dövrədə HEÇ KİM yeni problem tapmır (konvergensiya), VƏ YA
2. **6 dövrə tamamlanır** (token qorunması — sonsuz dövrə OLMASIN)

Hər dövrənin sonunda lead qısa xülasə versin: "Dövrə N: X problem
tapıldı, Y düzəldildi, Z açıq qaldı."

**MƏNƏ HESABAT:** Hər 2 dövrədən bir DAYAN, mənə vəziyyəti göstər, mən
"davam et" deyim. Beləliklə token istifadəsini nəzarətdə saxlayıram.

===============================================================================
ADDIM 3B — KOORDİNASİYA QAYDALARI
===============================================================================
1. **Başlanğıc sırası:** Birinci dövrədə əvvəlcə `qa` mövcud vəziyyəti
   skan etsin (nə sınıqdır?), nəticəni HAMIYA paylasın. Sonra qalanlar
   Mərhələ A-ya başlasın.
2. **Fayl toqquşması:** Başqasının faylını DƏYİŞMƏ — sahibinə mesaj
   göndər.
3. **Schema dəyişikliyi:** YALNIZ `infra` edir.
4. **Lead:** teammate-ləri gözlə, ÖZÜN paralel kod yazma. Yalnız
   koordinasiya et və sintez ver.
5. **"Əmin deyiləm" demək icazəlidir** — təxmin etmək QADAĞANDIR.
6. **Susmaq qadağandır:** Mərhələ B-də hər teammate ƏN AZI bir sual
   verməli və ya "bu dövrədə sənin sahəndə problem görmürəm" deməlidir.

===============================================================================
ADDIM 4 — YEKUN SİNTEZ (LEAD, DÖVRƏLƏR BİTƏNDƏN SONRA)
===============================================================================
Konvergensiya (və ya 6 dövrə) baş verəndə, mənə TƏK bir hesabat:
1. **Dövrə-dövrə xülasə:** hər dövrədə neçə problem tapıldı/düzəldildi
2. **Ən dəyərli çarpaz-tapıntılar:** hansı problemi bir teammate
   BAŞQASININ sahəsində tapdı (bunlar tək-sessiyada tapılmayacaq
   olanlardır — xüsusi vurğula)
3. **Açıq qalanlar:** düzəldilməyən problemlər + niyə
4. `pytest` yekun nəticəsi + `git diff --stat`
5. **Canlıya çıxmağa MANE olan bir şey qaldımı?** (bəli/xeyr + siyahı)

===============================================================================
QAYDA
===============================================================================
Addım 0 və 1-i bitirdikdən sonra DAYAN, mənə göstər, təsdiqimi gözlə.
SONRA Addım 2-yə (spawn) keç.
