"""Klaviatura-yalnız fokus halqası — `:focus-visible` ekvivalenti (FOCUS-1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA FAYL (D11 — dövrə 2/3 audit)
──────────────────────────────────────────────────────────────────────────────
Bu naxış əvvəl `buttons.py`-da yaşayırdı və YALNIZ `KeyFocusIconButton`/
`WindowButton`-a (başlıq zolağı, sol panel, pəncərə düymələri) tətbiq
olunurdu. Audit tapdı ki, tətbiqin ƏN ÇOX işlədilən elementləri —
`action_button()`/`secondary_button()` (`buttons.py`), `FilterChip`/
`LinkLabel`/`ClickableCard` (`primitives.py`), `TableRow` (`data_table.py`),
`NotificationItem` (`screens/group_g.py`) — bu qorumadan KƏNARDA qalmışdı:
QSS-də onların `:focus` qaydası ŞƏRTSİZ idi (`qss.py`-nin köhnə bazis şərhi
bunu açıq etiraf edirdi: "Fokus halqası HƏR İKİ variantda görünür").
Nəticə: `_InputModalityTracker`-in öz sənədləşdirdiyi qüsur ("Daxil Ol"
düyməsini SİÇANLA basmaq halqa yandırır) HƏLƏ DƏ REAL idi — sadəcə daha çox
yerdə.

Mixin BURAYA köçürüldü ki, `buttons.py`, `primitives.py`, `data_table.py`,
`screens/group_g.py` HAMISI ondan asılı ola bilsin DÖVRİ İDXAL yaratmadan:
`buttons.py` artıq `primitives.py`-dan `plain_label` idxal edir, yəni mixin
`primitives.py`-da qalsaydı (və ya orada TƏKRAR yazılsaydı), `primitives.py
→ buttons.py → primitives.py` dövrü yaranardı. Bu fayl İKİSİNDƏN də ASILI
DEYİL — YALNIZ Qt-nin öz APİ-sinə və `theme/manager.py`-a bağlıdır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt

from src.presentation.theme.manager import refresh_widget_style

if TYPE_CHECKING:
    from PySide6.QtGui import QFocusEvent

#: Tətbiq obyektinə bağlanan izləyicinin adı — ikinci nüsxə qurulmasın deyə.
_INPUT_TRACKER_NAME: Final = "kompasos.input_modality"


class _InputModalityTracker(QObject):
    """Sonuncu istifadəçi girişi KLAVİATURADAN idimi — `:focus-visible` ekvivalenti.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ FOKUS SƏBƏBİ TƏK BAŞINA KİFAYƏT ETMİR (FOCUS-1)
    ──────────────────────────────────────────────────────────────────────────
    Qt fokuslu widget-i SÖNDÜRƏNDƏ (`setEnabled(False)`) fokusu zəncirin
    növbəti elementinə `focusNextPrevChild()` ilə ötürür və o, səbəb kimi
    `TabFocusReason` yazır — yəni HƏQİQİ `Tab` basılışı ilə fərqlənmir.

    Bu, layihədə real nasazlıq idi: istifadəçi «Daxil Ol» düyməsini SİÇANLA
    basır, `set_busy(True)` düyməni söndürür, fokus başlıq zolağındakı tema
    düyməsinə sıçrayır və orada portağal halqa yanır. Eyni hadisə ekran
    əvəzlənməsində də baş verirdi — o hal `FramelessWindow.set_content`-də
    ƏLLƏ təmizlənirdi, lakin siyahı uzanırdı: hər yeni `setEnabled(False)`
    çağırışı üçün ayrıca təmizləmə yazmaq lazım gələcəkdi.

    Ona görə sual DƏYİŞDİRİLİR: «fokus necə gəldi?» əvəzinə «istifadəçi son
    olaraq nə ilə işləyirdi?». Brauzerlərin `:focus-visible` qaydası da
    məhz bunu edir. Nəticədə hər söndürmə/əvəzlənmə halı BİR yerdə həll
    olunur.

    Başlanğıc dəyər `True`-dur: hələ heç bir giriş hadisəsi olmayıb, yəni
    modallıq NAMƏLUMDUR. Belə halda halqanı GÖSTƏRMƏK seçilir — klaviatura
    istifadəçisi üçün görünməyən fokus, siçan istifadəçisi üçün artıq
    halqadan pis nasazlıqdır.
    """

    _KEYBOARD_EVENTS: ClassVar[frozenset[QEvent.Type]] = frozenset(
        {QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride}
    )
    _POINTER_EVENTS: ClassVar[frozenset[QEvent.Type]] = frozenset(
        {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.TouchBegin,
            QEvent.Type.Wheel,
        }
    )

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.keyboard = True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt adı
        """Hadisəni YALNIZ QEYD EDİR — heç birini udmur (`False` qaytarır)."""
        kind = event.type()
        if kind in self._KEYBOARD_EVENTS:
            self.keyboard = True
        elif kind in self._POINTER_EVENTS:
            self.keyboard = False
        return False


def input_modality_tracker() -> _InputModalityTracker | None:
    """Tətbiqə bağlı izləyici — ilk çağırışda qurulur.

    Quraşdırma başlanğıc kodunda DEYİL, burada olur: `QApplication` bəzi
    testlərdə və dizayn önizləməsində fərqli yollarla yaradılır, izləyicini
    isə fokus halqasını işlədən HƏR yol tələb edir. `findChild` ikinci nüsxənin
    qarşısını alır və valideynlik obyektin ömrünü tətbiqə bağlayır.

    `None` qaytarır: `QApplication` yoxdursa (yalnız domen testləri) fokus
    modallığı sualının mənası da yoxdur.
    """
    app = QCoreApplication.instance()
    if app is None:
        return None
    tracker = app.findChild(_InputModalityTracker, _INPUT_TRACKER_NAME)
    if tracker is None:
        tracker = _InputModalityTracker(app)
        tracker.setObjectName(_INPUT_TRACKER_NAME)
        app.installEventFilter(tracker)
    return tracker


class KeyFocusRingMixin:
    """Fokus halqasını YALNIZ klaviatura fokusunda göstərən davranış.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA MİXİN
    ──────────────────────────────────────────────────────────────────────────
    Qt pəncərə göstəriləndə fokusu fokus-zəncirinin BİRİNCİ elementinə verir.
    Başlıq zolağı tərtibatın ən üstündədir, yəni tətbiq açılan kimi oradakı
    ilk düymə fokus alır — və adi `:focus` qaydası halqanı ŞƏRTSİZ çəkir.
    İstifadəçi heç nəyə toxunmadan ekranda işıqlı kvadrat görür.

    Davranış əvvəl YALNIZ `WindowButton`-da vardı. Başlıq zolağına tema
    düyməsi əlavə olunanda eyni problem onda təkrarlandı — məhz buna görə
    məntiq İKİNCİ NÜSXƏ kimi köçürülmür, ortaq bazaya çıxarılır
    (`CLAUDE.md` §5: eyni qaydanın iki nüsxəsi sürüşür). D11 (dövrə 2/3 audit)
    həmin ortaq bazanı `action`/`secondary` düymələrinə, klik edilə bilən
    çiplərə/kartlara/sətirlərə GENİŞLƏNDİRDİ — bax modul başlığı.

    QSS tərəfi `[keyfocus="true"]` seçicisinə baxır; xüsusiyyət burada
    saxlanılır.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """İzləyicini QURULMA ANINDA quraşdırır — ilk klikdən ÇOX ƏVVƏL.

        Tənbəl qurma (yalnız `focusInEvent`-də) kifayət etmirdi: izləyici o
        vaxta qədər mövcud olmur, yəni istifadəçinin BİRİNCİ siçan basılışı
        qeydə düşmür və elə həmin basılışın yaratdığı fokus sıçrayışı
        «klaviatura» sayılırdı. Halqa məhz ilk dəfə görünürdü.

        Bu sinifdən törəyən widget-lər pəncərə örtüyü ilə birlikdə qurulur,
        yəni quraşdırma nöqtəsi kifayət qədər erkəndir.
        """
        super().__init__(*args, **kwargs)
        input_modality_tracker()

    #: Fokusun KLAVİATURADAN gəldiyini bildirən səbəblər.
    KEYBOARD_FOCUS_REASONS: ClassVar[frozenset[Qt.FocusReason]] = frozenset(
        {
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        }
    )

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Halqa yalnız `Tab`/`Shortcut` ilə gələn fokusda çəkilir.

        `ActiveWindow` səbəbi MÖVCUD vəziyyəti saxlayır: istifadəçi `Tab`-la bu
        elementə çatıb `Alt`+`Tab` ilə başqa proqrama keçib qayıdarsa, halqa
        yerində qalmalıdır — həmin halda fokus həqiqətən klaviaturadadır.

        Səbəbdən ƏLAVƏ giriş modallığı da yoxlanılır (FOCUS-1) — səbəbin özü
        siçanla yaranan sıçrayışı `Tab`-dan ayıra bilmir; izahı
        `_InputModalityTracker`-dədir.
        """
        if event.reason() is not Qt.FocusReason.ActiveWindowFocusReason:
            self._set_key_focus(self._reason_is_keyboard(event.reason()))
        super().focusInEvent(event)  # type: ignore[misc]

    def _reason_is_keyboard(self, reason: Qt.FocusReason) -> bool:
        if reason not in self.KEYBOARD_FOCUS_REASONS:
            return False
        tracker = input_modality_tracker()
        return tracker is None or tracker.keyboard

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Fokus getdi — halqa da getməlidir.

        `ActiveWindow` burada İSTİSNA DEYİL: pəncərə arxa plana keçəndə halqanı
        saxlamaq lazımdır, çünki qayıdışda eyni səbəblə geri gəlir və yuxarıdakı
        şərt onu olduğu kimi buraxır.
        """
        if event.reason() is not Qt.FocusReason.ActiveWindowFocusReason:
            self._set_key_focus(False)
        super().focusOutEvent(event)  # type: ignore[misc]

    def clear_key_focus_ring(self) -> None:
        """Halqanı söndürür — fokusun ÖZÜNƏ toxunmadan.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA ÇAĞIRIŞ LAZIM OLDU
        ──────────────────────────────────────────────────────────────────────
        Fokuslu widget MƏHV olanda (ekran əvəzlənir) Qt fokusu zəncirin
        növbəti elementinə `TabFocusReason` ilə ötürür — yəni HƏQİQİ `Tab`
        basılışı ilə EYNİ səbəb kodu ilə. `focusInEvent` ikisini ayırd edə
        bilmir və halqa çəkilirdi: istifadəçi «Yenidən cəhd et» düyməsini
        SİÇANLA basandan sonra başlıq zolağındakı tema düyməsinin
        işıqlandığını görürdü.

        Ayrım məlumatı yalnız ekranı əvəz EDƏN tərəfdədir
        (`FramelessWindow.set_content`), ona görə qərar oraya verilir.
        """
        self._set_key_focus(False)

    def _set_key_focus(self, active: bool) -> None:
        value = "true" if active else "false"
        if self.property("keyfocus") == value:  # type: ignore[attr-defined]
            return
        self.setProperty("keyfocus", value)  # type: ignore[attr-defined]
        refresh_widget_style(self)  # type: ignore[arg-type]


__all__ = ["KeyFocusRingMixin", "input_modality_tracker"]
