"""04llm - /api/accounts."""
import random
import string

from flask import Blueprint, g, request
from mysql.connector import IntegrityError

from db import fetch_all, fetch_one, run_transaction
from errors import ApiError
from middleware import require_user
from money import money_str
from responses import ok
from routes.user_routes import json_body
from utils import iso, mask_name, validate_fields

account_bp = Blueprint("account", __name__)


def account_dict(a):
    return {"account_id": a["account_id"], "account_number": a["account_number"], "account_type": a["account_type"],
            "balance": money_str(a["balance"]), "status": a["status"], "created_at": iso(a["created_at"])}


def create_account(cur, user_id, account_type):
    """Insert an account with a random 12-digit number (first digit 1-9); retry <=5 on collision. Returns account_id."""
    for _ in range(5):
        num = random.choice("123456789") + "".join(random.choices(string.digits, k=11))
        try:
            cur.execute("INSERT INTO accounts (account_number, user_id, account_type) VALUES (%s,%s,%s)",
                        (num, user_id, account_type))
            return cur.lastrowid
        except IntegrityError as e:
            if e.errno != 1062:
                raise
    raise ApiError("INTERNAL_ERROR", "Could not allocate an account number")


@account_bp.get("")
@require_user
def list_accounts():
    rows = fetch_all("SELECT * FROM accounts WHERE user_id=%s ORDER BY account_id", (g.user_id,))
    return ok({"accounts": [account_dict(r) for r in rows]})


@account_bp.post("")
@require_user
def open_account():
    kind = validate_fields(json_body(), {"account_type": {"choices": ["SAVINGS", "CURRENT"]}})["account_type"]

    def work(cur):
        cur.execute("SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (g.user_id,))  # serialises the 5-cap
        cur.execute("SELECT COUNT(*) AS n FROM accounts WHERE user_id=%s AND status<>'CLOSED'", (g.user_id,))
        if cur.fetchone()["n"] >= 5:
            raise ApiError("LIMIT_EXCEEDED", "At most 5 open accounts per user")
        return create_account(cur, g.user_id, kind)

    aid = run_transaction(work)
    return ok({"account": account_dict(fetch_one("SELECT * FROM accounts WHERE account_id=%s", (aid,)))}, 201)


@account_bp.get("/lookup")
@require_user
def lookup():
    num = validate_fields(request.args.to_dict(), {"account_number": {"regex": r"\d{12}", "msg": "must be exactly 12 digits"}})["account_number"]
    r = fetch_one("SELECT a.status, a.is_system, u.full_name FROM accounts a JOIN users u ON u.user_id=a.user_id "
                  "WHERE a.account_number=%s", (num,))
    if not r or r["is_system"]:
        raise ApiError("ACCOUNT_NOT_FOUND", "Account not found")
    return ok({"account_number": num, "holder_name": mask_name(r["full_name"]), "status": r["status"]})


@account_bp.get("/<int:account_id>")
@require_user
def get_account(account_id):
    a = fetch_one("SELECT * FROM accounts WHERE account_id=%s", (account_id,))
    if not a:
        raise ApiError("NOT_FOUND", "Account not found")
    if a["user_id"] != g.user_id:
        raise ApiError("FORBIDDEN", "Not your account")
    return ok({"account": account_dict(a)})


@account_bp.patch("/<int:account_id>/status")
@require_user
def set_status(account_id):
    new = validate_fields(json_body(), {"status": {"choices": ["ACTIVE", "FROZEN", "CLOSED"]}})["status"]

    def work(cur):
        cur.execute("SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (g.user_id,))  # "last account" race guard
        cur.execute("SELECT * FROM accounts WHERE account_id=%s FOR UPDATE", (account_id,))
        a = cur.fetchone()
        if not a:
            raise ApiError("NOT_FOUND", "Account not found")
        if a["user_id"] != g.user_id:
            raise ApiError("FORBIDDEN", "Not your account")
        if a["status"] == new:
            return a
        if a["status"] == "CLOSED":
            raise ApiError("INVALID_STATE", "A closed account cannot be reopened")
        if new == "CLOSED":
            cur.execute("SELECT (SELECT COUNT(*) FROM loans WHERE account_id=%s AND status IN ('PENDING_REVIEW','APPROVED','ACTIVE')) AS loans,"
                        " (SELECT COUNT(*) FROM accounts WHERE user_id=%s AND status<>'CLOSED' AND account_id<>%s) AS others",
                        (account_id, g.user_id, account_id))
            c = cur.fetchone()
            if a["balance"] != 0:
                raise ApiError("INVALID_STATE", "Balance must be 0.00 before closing the account")
            if c["loans"]:
                raise ApiError("INVALID_STATE", "Account has a loan that is pending, approved or active")
            if not c["others"]:
                raise ApiError("INVALID_STATE", "Cannot close your last open account")
        cur.execute("UPDATE accounts SET status=%s WHERE account_id=%s", (new, account_id))
        return {**a, "status": new}

    return ok({"account": account_dict(run_transaction(work))})
