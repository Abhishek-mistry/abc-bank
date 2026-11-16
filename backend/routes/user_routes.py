"""04llm - /api/users (+ shared profile validation used by register)."""
from datetime import datetime

from flask import Blueprint, g, request
from mysql.connector import IntegrityError

from db import execute, fetch_one
from errors import ApiError
from middleware import require_user
from responses import ok
from utils import iso, validate_fields

user_bp = Blueprint("user", __name__)
EMAIL = r"[^@\s]+@[^@\s]*\.[^@\s]*"


def json_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def user_dict(u):
    dob = u["date_of_birth"]
    return {"user_id": u["user_id"], "username": u["username"], "full_name": u["full_name"],
            "email": u["email"], "phone": u["phone"], "address": u["address"],
            "date_of_birth": dob.isoformat() if dob else None, "created_at": iso(u["created_at"])}


def clean_profile(body, partial=False, extra=None):
    """Validate the 5 profile fields (+ extra rules); all errors at once. Blank address/DOB -> None."""
    req = not partial
    rules = {"full_name": {"required": req, "min_len": 1, "max_len": 100},
             "email": {"required": req, "max_len": 120, "regex": EMAIL, "msg": "invalid email"},
             "phone": {"required": req, "regex": r"\d{10,15}", "msg": "must be 10-15 digits"},
             "address": {"required": False, "max_len": 255},
             "date_of_birth": {"required": False, "regex": r"\d{4}-\d{2}-\d{2}", "msg": "use YYYY-MM-DD"},
             **(extra or {})}
    body = {k: body[k] for k in rules if k in body}
    blank = {k: None for k in ("address", "date_of_birth") if k in body and not str(body[k] or "").strip()}
    data = {k: str(v) for k, v in body.items() if k not in blank and v is not None}
    errs, out = {}, {}
    try:
        out = validate_fields(data, rules)
    except ApiError as e:
        errs = dict(e.details.get("fields", {}))
    if out.get("date_of_birth"):
        try:
            datetime.strptime(out["date_of_birth"], "%Y-%m-%d")
        except ValueError:
            errs["date_of_birth"] = "invalid date"
    if errs:
        raise ApiError("VALIDATION_ERROR", "Invalid input", {"fields": errs})
    return {**out, **blank}


def _me():
    return ok({"user": user_dict(fetch_one("SELECT * FROM users WHERE user_id=%s", (g.user_id,)))})


@user_bp.get("/me")
@require_user
def get_me():
    return _me()


@user_bp.put("/me")
@require_user
def put_me():
    data = clean_profile(json_body(), partial=True)
    if data:
        try:
            execute("UPDATE users SET " + ", ".join(f"{k}=%s" for k in data) + " WHERE user_id=%s",
                    (*data.values(), g.user_id))
        except IntegrityError as e:
            if e.errno == 1062:
                raise ApiError("EMAIL_TAKEN", "Email already registered")
            raise
    return _me()
