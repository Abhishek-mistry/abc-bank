import calendar
import re
import uuid
from datetime import datetime, timezone

from errors import ApiError


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)  # naive UTC, like DB DATETIMEs


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def new_ref():
    return str(uuid.uuid4())


def mask_name(full_name):
    parts = full_name.split()
    return f"{parts[0]} {parts[-1][0].upper()}." if len(parts) > 1 else full_name.strip()


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def validate_fields(data, rules):
    """rules = {field: {"required": True, "min_len", "max_len", "regex", "choices", "msg"}}.
    Returns {field: stripped str} for supplied fields; raises VALIDATION_ERROR with details.fields."""
    data, errs, out = (data if isinstance(data, dict) else {}), {}, {}
    for f, r in rules.items():
        v = data.get(f)
        if isinstance(v, str):
            v = v.strip()
        if v is None or v == "":
            if r.get("required", True):
                errs[f] = "is required"
            continue
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            errs[f] = "must be a string"
            continue
        v = str(v)
        if not r.get("min_len", 0) <= len(v) <= r.get("max_len", 10 ** 6):
            errs[f] = f"length must be between {r.get('min_len', 0)} and {r.get('max_len', '∞')}"
        elif "regex" in r and not re.fullmatch(r["regex"], v):
            errs[f] = r.get("msg", "invalid format")
        elif "choices" in r and v not in r["choices"]:
            errs[f] = "must be one of: " + ", ".join(r["choices"])
        else:
            out[f] = v
    if errs:
        raise ApiError("VALIDATION_ERROR", "Invalid input: " + ", ".join(errs), {"fields": errs})
    return out
