"""İstisna qaydalarının REYESTRİ (#9, rule-registry) — Faza 3.

──────────────────────────────────────────────────────────────────────────────
NİYƏ REYESTR — MOTORDA `if source == ...` ZƏNCİRİ NİYƏ RƏDD EDİLDİ
──────────────────────────────────────────────────────────────────────────────
Bu partiyada motora YALNIZ BİR mənbə bağlanır (#8 davranış anomaliyası,
Faza 5). Bir mənbə üçün ən qısa kod belə olardı::

    if source == "BEHAVIOR_ANOMALY":
        findings = self._behavior.evaluate(...)
    elif source == "...":              # gələcək mənbə
        ...

Bu variant üç səbəbdən rədd edildi:

  1. **Motor audit-kritik koddur.** `exceptions` cədvəlində `REVOKE DELETE`
     var — motorun yazdığı sətir SİLİNMİR. Yəni motorun hər dəyişikliyi artıq
     işləyən BÜTÜN mənbələri yenidən risk altına salır. `if` zənciri hər yeni
     mənbədə məhz bu faylın dəyişməsini TƏLƏB EDƏRDİ.
  2. **Asılılıq istiqaməti tərsinə dönərdi.** `if` zənciri motoru hər
     qaydanın modulundan asılı edir (import + konstruktor arqumenti). Nəticədə
     #8-in hesablama qüsuru motorun testini də sındırar, motorun testi isə
     "bütün mənbələr üçün doğrudur" iddiasını itirərdi.
  3. **Qismən uğur mümkün olmazdı.** Reyestrdə hər qayda AYRI vahiddir və
     birinin çökməsi digərlərini dayandırmır (bax `ExceptionEngineUseCase.run`).
     Zəncirdə isə bir `elif`-in istisnası bütün icranı aparardı.

DB tərəfi eyni qərarı verib: `exceptions.source` sərt `CHECK`/`ENUM` deyil,
`exception_sources` kataloquna `FOREIGN KEY`-dir — yeni mənbə bir `INSERT`-dir
(migrations/018 başlığı). Reyestr həmin qərarın KOD tərəfidir: yeni mənbə bir
`register()` çağırışıdır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SIRA QORUNUR
──────────────────────────────────────────────────────────────────────────────
Qaydalar qeydiyyat sırası ilə icra olunur (`dict` sırası). Təsadüfi sıra
(məs. `set`) eyni gecənin iki icrasında istisnaları FƏRQLİ ardıcıllıqla
yaradardı; `created_at` möhürləri qarışar və "hansı tapıntı əvvəl gəldi?"
sualı audit-də cavabsız qalardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ REYESTR DOMENDƏDİR, TƏTBİQ QATINDA YOX
──────────────────────────────────────────────────────────────────────────────
Reyestr heç bir infrastruktura toxunmur (DB, HTTP, GUI yoxdur) və onun
qaydaları — "eyni mənbə iki dəfə qeydiyyatdan keçə bilməz", "kod BÖYÜK
hərflərlədir" — kataloq cədvəlinin qaydalarının eynisidir. Onları tətbiq
qatına qoymaq domen invariantını DB-dən kənarda, test edilməsi çətin yerdə
saxlamaq olardı.
"""

from __future__ import annotations

from collections.abc import Iterator

from src.domain.interfaces.ports import ExceptionRule
from src.domain.value_objects.exception_signals import MIN_SOURCE_CODE_LENGTH
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

_log = get_logger(__name__)


class ExceptionRuleError(KompasOSError):
    """Qayda reyestrinin qurulmasında səhv — QURAŞDIRMA qüsurudur."""

    user_message = "Sistem konfiqurasiya xətası. Administratorla əlaqə saxlayın."


class DuplicateExceptionRuleError(ExceptionRuleError):
    """Eyni mənbə kodu ilə ikinci qayda qeydiyyatdan keçirilir."""


class InvalidRuleSourceError(ExceptionRuleError):
    """Qaydanın mənbə kodu kataloq formatına uyğun deyil."""


class ExceptionRuleRegistry:
    """Mənbə kodu → qayda uyğunluğu.

    İstifadə (kompozisiya kökündə, bir dəfə)::

        registry = ExceptionRuleRegistry()
        registry.register(BehaviorAnomalyRule(baselines=..., attendance=...))
        engine = ExceptionEngineUseCase(registry=registry, ...)
    """

    def __init__(self, rules: tuple[ExceptionRule, ...] = ()) -> None:
        self._rules: dict[str, ExceptionRule] = {}
        for rule in rules:
            self.register(rule)

    # ------------------------------ qeydiyyat -------------------------------- #

    def register(self, rule: ExceptionRule) -> str:
        """Qaydanı reyestrə yazır və normallaşdırılmış mənbə kodunu qaytarır.

        İKİQAT QEYDİYYAT SÜKUTLA UDULMUR: eyni kodla ikinci qayda demək,
        birincisinin heç vaxt işləməyəcəyi (və ya sükutla əvəzləndiyi)
        deməkdir — hər iki nəticə də aşkarlamanın yarısını GÖRÜNMƏZ şəkildə
        söndürərdi. Bu, quraşdırma qüsurudur və işə salınma anında yüksək
        səslə çökməlidir, gecə saat 3-də sükutla yox.
        """
        code = self._normalize(rule.source_code)
        existing = self._rules.get(code)
        if existing is not None:
            raise DuplicateExceptionRuleError(
                f"'{code}' mənbəyi üçün qayda artıq qeydiyyatdadır",
                context={
                    "source_code": code,
                    "existing_rule": type(existing).__name__,
                    "new_rule": type(rule).__name__,
                },
            )
        self._rules[code] = rule
        _log.info(
            "EXCEPTION_RULE_REGISTERED",
            extra={"source_code": code, "rule": type(rule).__name__},
        )
        return code

    # -------------------------------- oxuma ---------------------------------- #

    def get(self, source_code: str) -> ExceptionRule | None:
        """Mənbə kodu üzrə qayda; qeydiyyatda yoxdursa `None`."""
        try:
            return self._rules.get(self._normalize(source_code))
        except InvalidRuleSourceError:
            # Yararsız kod sadəcə "tapılmadı"dır: axtarış istisna atmamalıdır,
            # əks halda ekranın süzgəci sətir səhvinə görə çökərdi.
            return None

    def rules(self) -> tuple[ExceptionRule, ...]:
        """Qeydiyyat sırasına sadiq qayda siyahısı (icra sırası)."""
        return tuple(self._rules.values())

    def source_codes(self) -> tuple[str, ...]:
        """Qeydiyyatdan keçmiş mənbə kodları — icra sırası ilə."""
        return tuple(self._rules)

    @property
    def is_empty(self) -> bool:
        """Boş reyestr NORMAL vəziyyətdir — motor sadəcə heç nə tapmır.

        Bu, xəta deyil: qayda söndürülüb və ya hələ bağlanmayıb ola bilər
        (məs. Faza 5-dən əvvəlki hər buraxılış). Motorun boş reyestrdə
        çökməsi ekranı da, planlaşdırılmış işi də lazımsız yerə sındırardı.
        """
        return not self._rules

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, source_code: object) -> bool:
        return isinstance(source_code, str) and self.get(source_code) is not None

    def __iter__(self) -> Iterator[ExceptionRule]:
        return iter(self.rules())

    def __repr__(self) -> str:
        return f"ExceptionRuleRegistry(sources={list(self._rules)})"

    # ------------------------------- köməkçi --------------------------------- #

    @staticmethod
    def _normalize(source_code: str) -> str:
        """Kodu kataloqdakı formata gətirir (`exception_sources.code`).

        DB `CHECK (code = upper(code) AND char_length(trim(code)) >= 3)` tələb
        edir. Normallaşdırma burada edilir ki, `"behavior_anomaly"` yazan
        qayda `FOREIGN KEY` pozuntusu ilə YAZI ANINDA deyil, qeydiyyat anında
        aydın mesaj alsın.
        """
        code = (source_code or "").strip().upper()
        if len(code) < MIN_SOURCE_CODE_LENGTH:
            raise InvalidRuleSourceError(
                f"Mənbə kodu minimum {MIN_SOURCE_CODE_LENGTH} simvol olmalıdır",
                context={"source_code": source_code},
            )
        return code


__all__ = [
    "DuplicateExceptionRuleError",
    "ExceptionRuleError",
    "ExceptionRuleRegistry",
    "InvalidRuleSourceError",
]
