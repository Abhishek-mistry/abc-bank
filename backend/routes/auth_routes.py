"""04llm - /api/auth."""
from flask import Blueprint
from mysql.connector import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from db import fetch_all, fetch_one, run_transaction
from errors import ApiError
from responses import ok
from routes.account_routes import account_dict, create_account
from routes.user_routes import clean_profile, json_body, user_dict

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
def register():
    body = json_body()
    d = clean_profile(body, extra={"username": {"regex": r"[A-Za-z0-9_]{3,30}", "msg": "3-30 letters, digits or underscore"},
                                   "password": {"min_len": 4, "msg": "at least 4 characters"}})
    pw = generate_password_hash(str(body["password"]))

    def work(cur):
        cur.execute("INSERT INTO users (username, password_hash, full_name, email, phone, address, date_of_birth) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (d["username"], pw, d["full_name"], d["email"], d["phone"], d.get("address"), d.get("date_of_birth")))
        uid = cur.lastrowid
        return uid, create_account(cur, uid, "SAVINGS")

    try:
        uid, aid = run_transaction(work)
    except IntegrityError as e:
        if e.errno == 1062:
            raise (ApiError("USERNAME_TAKEN", "Username already taken") if "uq_users_username" in str(e.msg)
                   else ApiError("EMAIL_TAKEN", "Email already registered"))
        raise
    return ok({"user": user_dict(fetch_one("SELECT * FROM users WHERE user_id=%s", (uid,))),
               "account": account_dict(fetch_one("SELECT * FROM accounts WHERE account_id=%s", (aid,)))}, 201)


@auth_bp.post("/login")
def login():
    b = json_body()
    u = fetch_one("SELECT * FROM users WHERE username=%s", (str(b.get("username", "")),))
    if not u or u["is_system"] or not check_password_hash(u["password_hash"], str(b.get("password", ""))):
        raise ApiError("INVALID_CREDENTIALS", "Invalid username or password")  # identical for unknown/system/wrong pw
    accts = fetch_all("SELECT * FROM accounts WHERE user_id=%s ORDER BY account_id", (u["user_id"],))
    return ok({"user": {**user_dict(u), "role": u["role"]}, "accounts": [account_dict(a) for a in accts]})
