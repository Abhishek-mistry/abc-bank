import re
from functools import wraps

from flask import g, request

import db
from errors import ApiError


def _auth(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            raw = request.headers.get("X-User-Id", "").strip()
            if not re.fullmatch(r"[0-9]{1,10}", raw):
                raise ApiError("AUTH_REQUIRED", "Missing or unknown X-User-Id")
            u = db.fetch_one("SELECT role FROM users WHERE user_id=%s AND is_system=0", (int(raw),))
            if not u:
                raise ApiError("AUTH_REQUIRED", "Missing or unknown X-User-Id")
            if u["role"] != role:  # customers cannot reach staff APIs, staff have no customer data of their own
                raise ApiError("FORBIDDEN", "This area is for %s accounts only" % role.lower())
            g.user_id = int(raw)
            return fn(*args, **kwargs)
        return wrapper
    return deco


require_user = _auth("CUSTOMER")
require_officer = _auth("OFFICER")


def _arg(name, default):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    if not raw.isascii() or not raw.isdigit() or int(raw) < 1:
        raise ApiError("VALIDATION_ERROR", f"{name} must be a positive integer",
                       {"fields": {name: "must be a positive integer"}})
    return int(raw)


def get_page_args():
    return _arg("page", 1), min(_arg("page_size", 10), 50)
