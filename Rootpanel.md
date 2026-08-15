KompasOS-un icazə/iyerarxiya modelində bir konseptual qarışıqlığı düzəldirəm.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud işləyən heç bir funksiyanı SİLMƏ — yalnız aşağıdakı səhv-prinsipin
nəticələrini tap və düzəlt.

===============================================================================
DÜZGÜN PRİNSİP (BUNU TAM ANLA, SONRA ÖZÜN AXTAR)
===============================================================================

1. İYERARXİYA: Root VƏ CEO EYNİ PİLLƏDƏ DEYİL. Root = tək başına ən
   üst pillə (0). CEO = Root-dan DƏRHAL aşağı, AYRI bir pillə (1). Admin
   = 2. HR_Admin/Mağaza_Meneceri/Kamera_Nəzarətçisi = 3. Satıcı = 4.

2. DEVELOPER PANEL AYRI SİSTEMDİR, ÜST PİLLƏ DEYİL: Tenant-daxili RBAC
   (Root→CEO→Admin→...→Satıcı) İLƏ Developer/Master Panel (bölmə 8, SİZİN
   bütün müştərilər üzərində lisenziya idarəetməniz) — bunlar EYNİ
   NƏRDİVANIN pillələri DEYİL, İKİ TAM AYRI SİSTEMDİR. Tenant-Root öz
   sistemində MÜTLƏQ, ETİRAZSIZ ən yuxarıdır — heç kim (Developer Panel
   daxil) onun ÜSTÜNDƏ DEYİL.

3. CEO GENİŞ, AMMA MƏHDUD SƏLAHİYYƏTLİDİR: CEO öz şirkəti haqqında
   hər şeyi görür, can_control_user_permissions/can_manage_positions
   ilə istədiyi işçiyə istədiyi (özündə olan) icazəni verə/yeni rol
   yarada bilər. AMMA can_manage_permissions (yeni flag-NÖVÜ), can_
   manage_system_limits, lisenziya/abunəlik — bunlar YALNIZ Root-a
   aiddir, CEO-ya BELƏ deyil.

4. ANTİ-FRAUD HARDLOCK MÜTLƏQDİR, ROOT DAXİL: can_verify_returns/
   can_override_return_time/can_issue_fines/can_approve_dual_control_
   override Mağaza_Meneceri/Satıcı-ya HEÇ VAXT, HEÇ KİM tərəfindən
   (Root-un özü daxil) verilə bilməz.

===============================================================================
TAPŞIRIQ — ÖZÜN GENİŞ AXTAR, MƏN SƏNƏ HƏR YERİ SADALAMIRAM
===============================================================================
Yuxarıdakı düzgün prinsipi əsas götürərək, bunun kod bazasında (schema,
permission-guard kodu, use case-lər, test-lər, şərhlər/comment-lər) VƏ
Kompas.md spesifikasiyasının öz nüsxəsində HARADA, NECƏ pozulduğunu
ÖZÜN TAP — mən konkret hər sətri deməyəcəyəm, bu, sənin öz işindir:

- positions/hierarchy-priority ilə bağlı BÜTÜN yerləri (schema defolt
  dəyərləri, seed-data, sənədləşdirmə) tap, "Root=CEO=0" fərziyyəsi ilə
  yazılmış hər şeyi düzgün (Root=0, CEO=1) prinsipə uyğunlaşdır.
- "Developer/Master Root" ifadəsinin tenant-Root-dan ÜSTÜN/AYRI bir
  səlahiyyət kimi işləndiyi BÜTÜN yerləri (kod-şərhləri, use-case adları,
  dəyişən adları, sənədləşdirmə) tap, düzəlt.
- Bu iki səhv fərziyyədən MƏNTİQİ OLARAQ YARANA BİLƏCƏK əlavə problemləri
  DE ÖZÜN DÜŞÜN — məsələn: CEO-nun hierarchy-guard testlərində səhvən
  "Root ilə eyni səviyyəli" kimi sınanıb-sınanmadığını, ya da hər hansı
  bir yerdə "yalnız Root VƏ CEO" formalı bir şərtin, əslində "yalnız
  Root" olmalı olduğunu — bunlar nümunədir, siyahı DEYİL, sən bundan
  kənar oxşar məntiqi nəticələri DƏ tap.

Hər tapıntını düzəlt, test yaz/yoxla ki, düzəliş yeni problem yaratmasın.

===============================================================================
TƏSDİQ TESTLƏRİ (MİNİMUM, ƏLAVƏ EDƏ BİLƏRSƏN)
===============================================================================
- "CEO, can_control_user_permissions ilə özündə olan flag-i HR_Admin-ə
  verə bilir" → keçməlidir.
- "Root-un özü belə, can_verify_returns-i Mağaza_Meneceri-yə verə
  bilmir" → rədd olunmalıdır.
- "CEO, Root-un icazələrinə toxuna bilmir" (indi Root=0, CEO=1
  olduğundan, bu, artıq Hierarchy Guard-ın TƏBİİ nəticəsidir) → rədd
  olunmalıdır.

===============================================================================
YEKUN
===============================================================================
Nəticəni göstər: nə tapdın (mənim sadalamadığım yerlər daxil), nəyi necə
düzəltdin. Bitirdikdən sonra DAYAN, mənə nəticəni göstər.