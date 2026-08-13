"""İnfrastruktur qatının ROOT konfiqurasiyası ilə əlaqəsi.

Yalnız `limits.py` var: infrastruktur modullarının `system_limits`-dən dəyər
oxumaq üçün işlətdiyi nazik körpü. Burada REPOSITORY YOXDUR — `SystemLimits`
portunun POSTGRES tətbiqi `persistence/config_repositories.py`-dədir və bu
paket ondan ASILI DEYİL (yalnız Protocol-u tanıyır), yəni offline/kiosk
rejimində bağlantısız da işləyir.
"""

from src.infrastructure.config.limits import (
    INFRA_LIMIT_BOUNDS,
    InfrastructureLimits,
    LimitReader,
)

__all__ = ["INFRA_LIMIT_BOUNDS", "InfrastructureLimits", "LimitReader"]
