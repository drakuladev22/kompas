"""İcazə Matrisinin YAZI yolu — rol → flag təyinatı (bölmə 3).

──────────────────────────────────────────────────────────────────────────────
BU EKRAN LAYİHƏNİN ƏN HƏSSAS YAZI YOLUDUR
──────────────────────────────────────────────────────────────────────────────
Burada dəyişən bir checkbox real pul (cərimə yazmaq), real nəzarət (dual-control
təsdiqi) və real məlumat girişi (işçi hesabatları) deməkdir. Ona görə kontroller
HEÇ BİR qərar vermir — o, yalnız tərcüməçidir:

    ekran (mətn açarları)  →  `PositionManagementUseCase.set_role_flags(...)`

Bütün qapılar use case-in İÇİNDƏDİR və burada TƏKRARLANMIR:

    * `can_manage_positions` yoxlaması        → `_require_permission()`
    * SELF-ESCALATION GUARD                   → `_apply_flags()` (aktor yalnız
      ÖZÜNDƏ AKTİV olan flag-i rola verə bilər)
    * Dörd-səviyyəli hardlock                 → `PermissionFlag.assert_grantable_to()`
    * Anti-fraud vəzifə ayrılığı + SEC-001    → eyni metod
    * Kamera-tipli rol qaydaları              → eyni metod
    * Audit (`POSITION_FLAGS_UPDATED`)        → `set_role_flags()`

Burada öz yoxlamamızı yazsaydıq, qayda ÜÇÜNCÜ nüsxəyə sahib olardı (domen +
DB trigger + GUI) və biri dəyişəndə digərləri arxada qalardı. Kontrollerin
yeganə əlavəsi istisnanın İSTİFADƏÇİYƏ İZAH EDİLMƏSİDİR — səssiz udulma
burada ən pis nəticədir, çünki admin dəyişikliyin tətbiq olunduğunu sanardı.

──────────────────────────────────────────────────────────────────────────────
DB TRİGGER-İ İLƏ EYNİ YOL
──────────────────────────────────────────────────────────────────────────────
`enforce_grantor_owns_flag()` (miqrasiya 014) eyni qaydanı DB-də tətbiq edir
və qərarını `position_permissions.granted_by` sütununa görə verir. Sütun
`PostgresPositionRepository._sync_flags()`-də `app.user_id` sessiya
parametrindən doldurulur, ona görə kontroller sessiyanı MÜTLƏQ
`user_id=self._actor.id` ilə açır — əks halda yazı DB qapısını "seed" kimi yan
keçərdi və qayda yalnız bir yerdə qalardı.

──────────────────────────────────────────────────────────────────────────────
VERİLƏ BİLMƏYƏN XANALAR GÖRÜNÜR, LAKİN BASILA BİLMİR (D3)
──────────────────────────────────────────────────────────────────────────────
`PermissionMatrixScreen` onları `setEnabled(False)` ilə qurur və bu, QƏSDƏN
belədir (bax sinif docstring-i): "sənin görməyə icazən yoxdur" deyil, "bu
icazə heç kim tərəfindən dəyişdirilə bilməz". Kontroller həmin qərara
TOXUNMUR — sadəcə `PermissionFlag.is_grantable_to()` nəticəsini kataloqdan
olduğu kimi ötürür. Bu, YALNIZ statik hardlock səviyyəsini (əvvəlki naxış)
deyil, ROLA görə anti-fraud/kamera-tip istisnalarını da əhatə edir — əks
halda checkbox "Yadda Saxla"-ya qədər aktiv görünürdü (bax `_flag_groups`
başlığı).

──────────────────────────────────────────────────────────────────────────────
AKTORDA OLMAYAN İCAZƏ DƏ BASILA BİLMİR
──────────────────────────────────────────────────────────────────────────────
Self-Escalation Guard (`_apply_flags`) aktorun özündə olmayan flag-i rola
verməsini rədd edir, lakin admin bunu yalnız "Yadda Saxla"-dan SONRA görürdü:
bütün seçim geri qaytarılırdı və hansı xananın rədd edildiyi bəlli olmurdu.
Kontroller aktorun effektiv flag dəstini onsuz da bilir, ona görə həmin
məlumat matris sətrinin beşinci sahəsi kimi ekrana ÖTÜRÜLÜR. Yoxlamanın ÖZÜ
burada təkrarlanmır — qərar yenə use case-dədir.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import PermissionMatrixScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Kataloqda kateqoriyası olmayan flag bu başlıq altında toplanır.
OTHER_CATEGORY = "Digər"


class PermissionMatrixController:
    """İcazə Matrisini `PositionManagementUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: rol kodu → `Position` (matris yazısı `position_id` tələb edir).
        self._roles: dict[str, Any] = {}
        #: Seçili rol — yenilədikdən sonra bərpa olunur.
        self._active: str | None = None

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: PermissionMatrixScreen) -> None:
        screen.role_selected.connect(lambda code: self._on_role_selected(screen, code))
        screen.saved.connect(lambda code, flags: self._on_saved(screen, code, flags))
        screen.role_create_requested.connect(lambda: self._on_create(screen))
        self.refresh(screen)

    def refresh(self, screen: PermissionMatrixScreen) -> None:
        """Rol siyahısını yenidən oxuyur və seçili rolun matrisini çəkir."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                summaries = session.positions.list_roles(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                counts = _employee_counts(session)
        except KompasOSError as error:
            # Səlahiyyət yoxdursa ekran BOŞ deyil, SƏBƏBLƏ göstərilir — boş
            # matris "heç bir icazə yoxdur" kimi oxunardı və bu, yanlışdır.
            screen.show_error(title="Matris açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("PERMISSION_MATRIX_LOAD_FAILED")
            screen.show_error(
                title="Matris açıla bilmədi",
                message="Rol siyahısı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        self._roles = {summary.position.code: summary.position for summary in summaries}
        # Sıra pilləyə görədir: matris iyerarxik bir qərar sahəsidir və rolları
        # əlifba sırası ilə düzmək «Root» ilə «Satıcı»-nı yan-yana salardı.
        ordered = sorted(
            summaries, key=lambda item: (int(item.position.priority), item.position.code)
        )
        screen.set_roles(
            [
                (
                    summary.position.code,
                    summary.position.name_az,
                    counts.get(str(summary.position.id), 0),
                )
                for summary in ordered
            ]
        )

        active = self._active if self._active in self._roles else None
        if active is None and ordered:
            active = ordered[0].position.code
        if active is not None:
            # `select_role` `role_selected` siqnalını yayır və matris həmin
            # yolla dolur — ikinci bir doldurma yolu qursaydıq, siyahıdan
            # klikləmə ilə proqram seçimi fərqli davranardı.
            screen.select_role(active)

    # -------------------------------- matris --------------------------------- #

    def _on_role_selected(self, screen: PermissionMatrixScreen, role_code: str) -> None:
        position = self._roles.get(role_code)
        if position is None:
            return
        self._active = role_code

        try:
            with self._context.session(user_id=self._actor.id) as session:
                groups = _flag_groups(session, position, actor=self._actor)
        except Exception:
            _error_log.exception("PERMISSION_FLAGS_LOAD_FAILED", extra={"role": role_code})
            screen.show_error(
                title="İcazələr oxuna bilmədi",
                message="Flag kataloqu yüklənmədi. Yenidən cəhd edin.",
            )
            return

        screen.set_matrix(position.name_az, groups)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_saved(self, screen: PermissionMatrixScreen, role_code: str, flags: Any) -> None:
        """ "Yadda Saxla" — işarələnmiş flag dəsti use case-ə TAM ötürülür.

        Ekran bütün xanaları göndərir (hardlock olanlar DA daxil, dəyişməz
        vəziyyətdə) və `set_role_flags()` dəsti tam əvəzləyir. Yalnız
        dəyişənləri göndərmək ekranı vəziyyət izləməyə məcbur edərdi — həmin
        qərar use case-də açıq şəkildə izah olunub.
        """
        position = self._roles.get(role_code)
        if position is None:
            screen.show_error(
                title="Rol tapılmadı",
                message="Bu rol artıq dəyişdirilib. Siyahı yenilənir.",
            )
            self.refresh(screen)
            return

        selected = tuple(str(code) for code, enabled in (flags or {}).items() if bool(enabled))
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.positions.set_role_flags(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    position_id=position.id,
                    flag_codes=selected,
                )
                session.commit()
        except KompasOSError as error:
            # GUARD POZUNTUSU BURADA GÖRÜNÜR: hardlock, anti-fraud, SEC-001 və
            # Self-Escalation istisnalarının hamısı `KompasOSError`-dur və
            # `user_message` səbəbi Azərbaycanca deyir. Səssiz udulma admin-ə
            # "dəyişiklik tətbiq olundu" təəssüratı verərdi.
            screen.show_error(title="İcazələr yazılmadı", message=error.user_message)
            # Ekran YALAN göstərməməlidir: rədd edilmiş xanalar bazadakı
            # vəziyyətə qaytarılır.
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("PERMISSION_MATRIX_SAVE_FAILED", extra={"role": role_code})
            screen.show_error(
                title="İcazələr yazılmadı",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            self.refresh(screen)
            return

        self.refresh(screen)

    def _on_create(self, screen: PermissionMatrixScreen) -> None:
        from src.presentation.screens.group_c import RoleCreateDialog  # noqa: PLC0415

        dialog = RoleCreateDialog(screen.theme, parent=screen)
        dialog.submitted.connect(
            lambda name, priority, is_camera: self._create_role(
                screen, name=name, priority=priority, is_camera=is_camera
            )
        )
        dialog.exec()

    def _create_role(
        self, screen: PermissionMatrixScreen, *, name: str, priority: int, is_camera: bool
    ) -> None:
        """Yeni custom rol — İCAZƏSİZ yaradılır, flag-lər sonra verilir.

        `flag_codes` BOŞ göndərilir: yeni rol heç bir səlahiyyətlə doğulmur və
        admin onları matrisdən açıq şəkildə verir. Dialoqda flag seçimi
        təklif etsəydik, ən qapalı ilkin vəziyyət prinsipi pozulardı — eyni
        istiqamət `root_control._on_flag_created`-da da seçilib.
        """
        from src.application.use_cases.position_management import RoleDraft  # noqa: PLC0415
        from src.domain.value_objects.authorization import RolePriority  # noqa: PLC0415

        try:
            draft = RoleDraft(
                # Kod addan törədilir; use case onu normallaşdırır (bax
                # `RoleCreateDialog` docstring-i).
                code=name,
                name_az=name,
                priority=RolePriority(priority),
                is_camera_type=is_camera,
                flag_codes=(),
            )
        except ValueError:
            screen.show_error(
                title="Rol yaradılmadı",
                message="Səlahiyyət pilləsi tanınmadı.",
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                position = session.positions.create_role(
                    tenant_id=session.tenant_id, actor=self._actor, draft=draft
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Rol yaradılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ROLE_CREATE_FAILED", extra={"name": name})
            screen.show_error(
                title="Rol yaradılmadı",
                message="Rol saxlanmadı. Yenidən cəhd edin.",
            )
            return

        # Yeni rol DƏRHAL seçilir: admin onu yaratdıqdan sonra ilk işi ona
        # icazə vermək olacaq və siyahıda axtarmağa məcbur etmək mənasızdır.
        self._active = position.code
        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee_counts(session: Session) -> dict[str, int]:
    """`position_id → aktiv işçi sayı` — sol paneldəki rəqəm.

    Deaktiv işçilər sayılmır: rəqəm "bu rol neçə nəfərə təsir edir" sualına
    cavab verir və işdən çıxmış işçi həmin təsirin bir hissəsi deyil.
    """
    rows = session.uow.connection.execute(
        """
        SELECT position_id, count(*) AS total
          FROM employees
         WHERE tenant_id = %s AND is_active
         GROUP BY position_id
        """,
        (session.tenant_id,),
    ).fetchall()
    return {str(row["position_id"]): int(row["total"]) for row in rows}


def _flag_labels(session: Session) -> dict[str, str]:
    """`flag_code → name_az` — kataloqun insan-oxunaqlı etiketləri.

    `PermissionFlag` value object-i `name_az` daşımır (o, yalnız qayda
    sahələrini saxlayır), etiket isə `permission_flags.name_az` sütunundadır.
    Sətri birbaşa oxuyuruq: burada iş qaydası yoxdur, yalnız göstəriş var —
    eyni əsas `screen_data._fines`-də də izah olunub. Tapılmayan etiket üçün
    flag KODU göstərilir; tərcüməni burada UYDURMAQ kataloqla ekran arasında
    ikinci ad məkanı yaradardı.
    """
    rows = session.uow.connection.execute(
        "SELECT code, COALESCE(name_az, code) AS name_az FROM permission_flags"
    ).fetchall()
    return {str(row["code"]): str(row["name_az"]) for row in rows}


def _flag_groups(
    session: Session, position: Any, *, actor: Employee | None = None
) -> list[tuple[str, list[tuple[str, str, bool, bool, bool]]]]:
    """Kataloqu ekranın gözlədiyi qruplara çevirir.

    Format `PermissionMatrixScreen.set_matrix`-in FAKTİKİ oxuduğudur:
    `(kateqoriya, [(flag, etiket, aktiv, hardlock, aktorda_var)])` — maket
    yolundakı `preview_data.PERMISSION_GROUPS` ilə EYNİ struktur.

    ──────────────────────────────────────────────────────────────────────────
    BEŞİNCİ SAHƏ QAYDA DEYİL, MƏLUMATDIR
    ──────────────────────────────────────────────────────────────────────────
    `aktorda_var` Self-Escalation Guard-ın TƏKRARI deyil: qərar yenə də
    `_apply_flags`-dədir və istisna atır. Burada sadəcə həmin qərarın GİRİŞİ —
    aktorun effektiv flag dəsti — ekrana ötürülür ki, admin rədd ediləcək
    xananı işarələməmişdən əvvəl görsün. Yoxlamanı ekrana köçürsəydik qayda
    üçüncü nüsxəyə sahib olardı və biri dəyişəndə digərləri arxada qalardı.

    Args:
        actor: Matrisi açan istifadəçi. `None` YALNIZ aktor kontekstinin
            olmadığı çağırışlar üçündür (maket/test); belə halda heç bir xana
            ƏLAVƏ olaraq deaktiv edilmir. Bu, təhlükəsizlik güzəşti deyil —
            sahə yalnız GÖRÜNTÜNÜ idarə edir, yazını isə use case rədd edir.

    ──────────────────────────────────────────────────────────────────────────
    DÖRDÜNCÜ SAHƏ — İNDİ SADƏCƏ `hardlock` DEYİL, `is_grantable_to()` (D3)
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl `flag.hardlock is not HardlockLevel.NONE` idi — yəni flag-in ÖZ
    statik hardlock səviyyəsi, ROL nəzərə alınmadan. Kamera-tipli/anti-fraud-
    istisna edilən rol üçün (məs. `can_approve_dual_control_override`)
    checkbox buna görə AKTİV görünürdü: admin işarələyir, "Yadda Saxla"
    basır, YALNIZ SONRA `_apply_flags`-dəki SEC-001/vəzifə-ayrılığı qaydası
    onu rədd edirdi (bax `_on_saved`) — "görmək = səlahiyyət" qapı BURADA
    bir addım gecikirdi.
    `PermissionFlag.is_grantable_to()` (`authorization.py`, TOXUNULMUR — hazır
    funksiya) EYNİ qaydanı (hardlock SƏVİYYƏSİ + anti-fraud + kamera-tip
    istisnaları + SEC-001) ROLA GÖRƏ yoxlayır, ona görə köhnə hardlock
    yoxlamasını ƏVƏZ edir, ONA ƏLAVƏ olunmur — ikisini yanaşı saxlasaydıq
    üçüncü nüsxə yaranardı (bölmə 3).
    """
    labels = _flag_labels(session)
    granted = set(position.granted_flags)
    now = datetime.now(UTC)
    role = position.effective_system_role
    is_camera = bool(position.is_camera_type)

    grouped: dict[str, list[tuple[str, str, bool, bool, bool]]] = {}
    for flag in session.uow.repository("permission_flags").list_all():
        category = flag.category or OTHER_CATEGORY
        grouped.setdefault(category, []).append(
            (
                flag.code,
                labels.get(flag.code, flag.code),
                flag.code in granted,
                not flag.is_grantable_to(role, is_camera_type_role=is_camera),
                actor is None or actor.has_permission(flag.code, now=now),
            )
        )

    return [(category, grouped[category]) for category in sorted(grouped)]


__all__ = ["OTHER_CATEGORY", "PermissionMatrixController"]
