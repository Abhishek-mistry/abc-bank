import re
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

_MONEY = re.compile(r"\d{1,13}(\.\d{1,2})?")  # fits DECIMAL(15,2); no sign, no exponent


def round2(d):
    return Decimal(d).quantize(Decimal("0.01"), ROUND_HALF_UP)


def money_str(d):
    return format(round2(d), "f")


def parse_money(value, field="amount", min_value=None, max_value=None):
    def bad(msg):
        raise ApiError("VALIDATION_ERROR", f"{field}: {msg}", {"fields": {field: msg}})

    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        bad("must be a number with at most 2 decimals")
    s = format(value, "f") if isinstance(value, Decimal) else str(value).strip()
    if not _MONEY.fullmatch(s):  # rejects "", "1e3", "-5", "1.234", "abc"; JSON floats like 10.5 pass via str()
        bad("must be a non-negative number with at most 2 decimals")
    d = Decimal(s)
    if min_value is not None and d < Decimal(str(min_value)):
        bad(f"must be at least {money_str(Decimal(str(min_value)))}")
    if max_value is not None and d > Decimal(str(max_value)):
        bad(f"must be at most {money_str(Decimal(str(max_value)))}")
    return round2(d)
