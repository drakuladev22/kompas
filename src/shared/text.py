"""Mətn normalizasiyası — qərar/səbəb/izah sahələri üçün TƏK mənbə.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR (QA-FULL Faza 6, xaos/stress sınağı)
──────────────────────────────────────────────────────────────────────────────
Domendə və tətbiq qatında onlarla yerdə eyni naxış TƏKRAR yazılırdı:
`" ".join(text.split())` (real boşluqları sıxır) və ya sadə `text.strip()`
(yalnız kənar boşluğu kəsir). Heç biri Unicode "Format" (Cf) kateqoriyasındakı
GÖRÜNMƏZ simvolları — sıfır-en boşluq (U+200B), sıfır-en birləşdirici
(U+200C/U+200D), söz birləşdiricisi (U+2060), soft-hyphen (U+00AD), sağdan-
sola/soldan-sağa işarələri (U+200E/U+200F) və s. — TƏMİZLƏMİRDİ. Python-un
`str.split()`-i və `str.isspace()`-i bu simvolları boşluq SAYMIR, ona görə
onlar mətnin "uzunluğuna" qatılır, amma ekranda HEÇ NƏ göstərmirlər.

Nəticə empirik sübut edildi: 10 ədəd sıfır-en boşluqdan (`"\\u200b" * 10`)
ibarət, insan gözünə TAM BOŞ görünən mətn `len(cleaned) >= MIN_..._LENGTH`
şərtini keçirdi və qərar İZAHI/SƏBƏBİ kimi QƏBUL edilirdi — halbuki işçi və
ya menecer bildirişdə HEÇ NƏ oxumur, sistem isə "mənalı izah verildi" sayır.
Bu, cərimə ləğvi, etiraz qərarı, növbə dəyişmə rəddi, məzuniyyət rəddi,
tapşırıq rəddi, xal etirazı, üz-tanıma istisnası, Emergency Access Recovery
istinadı kimi audit-kritik SƏBƏB sahələrinin HAMISINA aiddir — hamısı eyni
prinsipə tabedir: "qərarın SƏBƏBİ audit izi və bildiriş mətnidir, mənasız
mətn qərarı etibarsızlaşdırır".

Ona görə normalizasiya BİR yerə çıxarılıb: onlarla yerdə təkrar yazmaq
əvəzinə buradan idxal edilir. Bu, CLAUDE.md §5-in "hər qayda İKİ yerdə"
tələbinin DAHA SƏRT tətbiqidir — burada qayda İKİ FƏRQLİ QATDA (domen + DB)
yaşamırdı, EYNİ QATIN İÇİNDƏ onlarla nüsxədə təkrarlanırdı; təkrarı BİRƏ
endirmək düzgün seçimdir, çünki iyirmiyə yaxın müstəqil kopiya arasından
BİRİNİN düzəlişdən kənarda qalması vaxt məsələsi idi (məhz belə baş verdi).
"""

from __future__ import annotations

import unicodedata

__all__ = ["normalise_decision_text"]


def normalise_decision_text(raw: str) -> str:
    """Real boşluqları sıxır, GÖRÜNMƏZ (Unicode "Format", Cf) simvolları ATIR.

    İKİ addım, MƏHZ BU SIRA ilə:
        1. Cf kateqoriyalı hər simvol mətndən çıxarılır — bunlar HEÇ VAXT
           mənalı məzmun daşımır, yalnız render/qoşulma effekti üçün
           nəzərdə tutulub (sıfır-en boşluq, yön işarələri, soft-hyphen və s.).
           BU ADDIM `str.split()`-DƏN ƏVVƏL olmalıdır — əks halda görünməz
           simvol "sözün içində" qalıb `split()`-i heç cür bölmür və nəticə
           dəyişmir.
        2. Qalan mətn `str.split()` + `" ".join()` ilə sıxılır — ardıcıl
           boşluqlar/tab/sətir keçidləri BİR boşluğa endirilir (əvvəlki
           bütün çağırış yerlərinin DAVRANIŞI budur, saxlanılır).

    Nəticə: `len(normalise_decision_text(text)) >= MIN_..._LENGTH` yoxlaması
    artıq yalnız-görünməz mətni keçirmir — addım (1)-dən sonra belə mətn boş
    sətirə çevrilir və `len(...)` sıfır olur.
    """
    visible = "".join(ch for ch in raw if unicodedata.category(ch) != "Cf")
    return " ".join(visible.split())
