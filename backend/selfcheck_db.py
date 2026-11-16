"""python backend/selfcheck_db.py  -> prints PASS/FAIL per check; exit 1 on any FAIL. Resets the DB (leaves it seeded)."""
import os
import re
import subprocess
import sys
import threading
from datetime import date
from decimal import Decimal

from mysql.connector import Error as MySQLError
from mysql.connector.errors import DatabaseError
from werkzeug.security import check_password_hash

import db
import init_db
from app import create_app
from errors import ApiError
from money import money_str, parse_money
from services.notify import create_notification
from utils import add_months, iso, mask_name

HERE = os.path.dirname(os.path.abspath(__file__))
TABLES = {"users", "accounts", "loans", "loan_documents", "guarantors", "transactions", "ledger_entries",
          "repayment_schedule", "notifications", "system_settings"}
BAL = {1: "-40000.00", 2: "10000.00", 3: "5000.00", 4: "25000.00"}
FAILS = []


def check(fn):
    try:
        fn()
        print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001 - report everything
        FAILS.append(fn.__name__)
        print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    return fn


class _Rollback(Exception):
    pass


def probe(fn):
    """Run fn(cur) in a transaction that is always rolled back. Returns None if fn succeeded, else the MySQL error."""
    try:
        with db.transaction() as cur:
            fn(cur)
            raise _Rollback
    except _Rollback:
        return None
    except MySQLError as e:
        return e


def ins(cur, table, **kw):
    cur.execute(f"INSERT INTO {table} ({','.join(kw)}) VALUES ({','.join(['%s'] * len(kw))})", list(kw.values()))
    return cur.lastrowid


def expect(err, errno):
    assert err is not None and err.errno == errno, f"expected MySQL errno {errno}, got {err!r}"


def snapshot():
    counts = {t: db.fetch_one(f"SELECT COUNT(*) c FROM {t}")["c"] for t in sorted(TABLES)}
    return counts, {r["account_id"]: r["balance"] for r in db.fetch_all("SELECT account_id, balance FROM accounts")}


def parse_schema():
    text = re.sub(r"--[^\n]*", "", open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
    out = {}
    for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\) ENGINE", text, re.S):
        t = {"cols": [], "idx": set(), "fk": set(), "chk": set()}
        for line in (ln.strip().rstrip(",") for ln in body.split("\n")):
            w = line.split()
            if not w:
                continue
            if w[0] == "PRIMARY":
                t["idx"].add("PRIMARY")
            elif w[0] in ("UNIQUE", "KEY"):
                t["idx"].add(w[2] if w[0] == "UNIQUE" else w[1])
            elif w[0] == "CONSTRAINT":
                t["chk" if " CHECK " in line else "fk"].add(w[1])
            else:
                t["cols"].append((w[0], re.match(r"\w+", w[1]).group().lower(), "NOT NULL" not in line))
        out[name] = t
    return out


# ---- B1 ---------------------------------------------------------------------------------------------------------
init_db.reset_database(test_fixtures=True)


@check
def b1_tables_exact():
    got = {list(r.values())[0] for r in db.fetch_all("SHOW TABLES")}
    assert got == TABLES, got ^ TABLES


@check
def b1_information_schema_matches_ddl():
    for name, t in parse_schema().items():
        cols = db.fetch_all("SELECT COLUMN_NAME n, DATA_TYPE d, IS_NULLABLE nl FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION", (name,))
        assert [(c["n"], c["d"], c["nl"] == "YES") for c in cols] == t["cols"], f"{name}: column mismatch"
        cons = db.fetch_all("SELECT CONSTRAINT_NAME n, CONSTRAINT_TYPE k FROM information_schema.TABLE_CONSTRAINTS "
                            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (name,))
        assert t["fk"] <= {c["n"] for c in cons if c["k"] == "FOREIGN KEY"}, f"{name}: missing FK"
        assert t["chk"] <= {c["n"] for c in cons if c["k"] == "CHECK"}, f"{name}: missing CHECK"
        idx = {r["i"] for r in db.fetch_all("SELECT DISTINCT INDEX_NAME i FROM information_schema.STATISTICS "
                                            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (name,))}
        assert t["idx"] <= idx, f"{name}: missing index {t['idx'] - idx}"


# ---- B2 constraint probes ---------------------------------------------------------------------------------------
def _txn(cur, **kw):
    base = dict(txn_ref="00000000-0000-4000-8000-000000000001", txn_type="DEPOSIT", from_account_id=1,
                to_account_id=2, amount=Decimal("1.00"))
    return ins(cur, "transactions", **{**base, **kw})


@check
def b2_negative_balance_rules():
    expect(probe(lambda c: ins(c, "accounts", account_number="900000000001", user_id=2, balance=-1)), 3819)
    assert probe(lambda c: ins(c, "accounts", account_number="900000000002", user_id=1, is_system=1, balance=-1)) is None


@check
def b2_txn_uniqueness_and_amount():
    expect(probe(lambda c: (_txn(c), _txn(c, idempotency_key="k1"))), 1062)  # duplicate txn_ref
    expect(probe(lambda c: (_txn(c, idempotency_key="dupkey01"),
                            _txn(c, txn_ref="00000000-0000-4000-8000-000000000002", idempotency_key="dupkey01"))), 1062)
    assert probe(lambda c: (_txn(c), _txn(c, txn_ref="00000000-0000-4000-8000-000000000002"))) is None  # two NULL keys
    expect(probe(lambda c: _txn(c, amount=Decimal("0.00"))), 3819)


@check
def b2_loan_and_guarantor_constraints():
    expect(probe(lambda c: ins(c, "loans", user_id=2, account_id=2, tenure_months=7)), 3819)

    def two_guarantors(c):
        lid = ins(c, "loans", user_id=2, account_id=2)
        g = dict(loan_id=lid, guarantor_name="G", guarantor_aadhar="123412341234", relationship="PARENT")
        ins(c, "guarantors", **g)
        ins(c, "guarantors", **g)
    expect(probe(two_guarantors), 1062)


# ---- B3 seed ----------------------------------------------------------------------------------------------------
@check
def b3_seed_and_integrity():
    counts, bal = snapshot()
    assert counts["users"] == 5 and counts["accounts"] == 4 and counts["transactions"] == 4, counts
    assert counts["ledger_entries"] == 8 and counts["system_settings"] == 2, counts
    assert {k: money_str(v) for k, v in bal.items()} == BAL, bal
    one = lambda sql: db.fetch_all(sql)  # noqa: E731
    dr, cr = "SUM(IF(l.entry_type='DEBIT',l.amount,0))", "SUM(IF(l.entry_type='CREDIT',l.amount,0))"
    assert not one(f"SELECT t.txn_id FROM transactions t LEFT JOIN ledger_entries l ON l.txn_id=t.txn_id "
                   f"WHERE t.status IN ('COMPLETED','REVERSED') GROUP BY t.txn_id "
                   f"HAVING COALESCE({dr},0)<>COALESCE({cr},0) OR COALESCE({dr},0)=0"), "I1"
    assert not one("SELECT a.account_id FROM accounts a LEFT JOIN ledger_entries l ON l.account_id=a.account_id "
                   "GROUP BY a.account_id, a.balance "
                   "HAVING a.balance <> COALESCE(SUM(IF(l.entry_type='CREDIT',l.amount,-l.amount)),0)"), "I2"
    assert db.fetch_one("SELECT SUM(balance) s FROM accounts")["s"] == Decimal("0.00"), "I4"
    assert not one("SELECT account_id FROM accounts WHERE is_system=0 AND balance<0"), "I5"
    h = {r["username"]: r["password_hash"] for r in db.fetch_all("SELECT username, password_hash FROM users")}
    assert check_password_hash(h["alice"], "alice123") and not check_password_hash(h["alice"], "wrong")
    assert not any(check_password_hash(h["__bank__"], p) for p in ("", "__bank__", "!unusable", "alice123"))


@check
def b3b_default_seed_is_one_demo_customer_and_one_officer():
    init_db.reset_database()  # the real (non-test) seed
    try:
        users = {r["username"]: r for r in db.fetch_all("SELECT username, role, is_system FROM users")}
        assert set(users) == {"__bank__", "demo", "officer"}, users.keys()
        assert users["demo"]["role"] == "CUSTOMER" and users["officer"]["role"] == "OFFICER"
        accts = db.fetch_all("SELECT u.username, a.balance FROM accounts a JOIN users u ON u.user_id=a.user_id ORDER BY a.account_id")
        assert [(a["username"], money_str(a["balance"])) for a in accts] == [("__bank__", "-10000.00"), ("demo", "10000.00")], accts
        assert not db.fetch_all("SELECT 1 FROM accounts a JOIN users u ON u.user_id=a.user_id WHERE u.role='OFFICER'"), "officer has no account"
        assert db.fetch_one("SELECT SUM(balance) s FROM accounts")["s"] == Decimal("0.00"), "I4"
        h = {r["username"]: r["password_hash"] for r in db.fetch_all("SELECT username, password_hash FROM users")}
        assert check_password_hash(h["demo"], "demo123") and check_password_hash(h["officer"], "officer123")
    finally:
        init_db.reset_database(test_fixtures=True)


# ---- B4 ---------------------------------------------------------------------------------------------------------
@check
def b4_reset_is_repeatable_and_no_seed():
    init_db.reset_database(test_fixtures=True)
    first = snapshot()
    init_db.reset_database(test_fixtures=True)
    assert snapshot() == first
    subprocess.run([sys.executable, os.path.join(HERE, "init_db.py"), "--no-seed"], check=True, capture_output=True)
    assert all(v == 0 for v in snapshot()[0].values()), snapshot()[0]
    init_db.reset_database(test_fixtures=True)  # restore seed for later checks


# ---- B5 run_transaction -----------------------------------------------------------------------------------------
@check
def b5a_exception_rolls_back():
    def fn(cur):
        ins(cur, "users", username="tmp_rb", password_hash="x", full_name="T", email="tmp_rb@x.y", phone="1234567890")
        raise KeyError("boom")
    try:
        db.run_transaction(fn)
        raise AssertionError("exception swallowed")
    except KeyError:
        pass
    assert db.fetch_one("SELECT 1 FROM users WHERE username='tmp_rb'") is None


@check
def b5b_real_deadlock_is_retried():
    barrier, attempts, errors = threading.Barrier(2, timeout=10), {"A": 0, "B": 0}, []

    def worker(name, first, second):
        def fn(cur):
            attempts[name] += 1
            cur.execute("SELECT balance FROM accounts WHERE account_id=%s FOR UPDATE", (first,))
            if attempts[name] == 1:
                barrier.wait()  # both hold their first lock -> guaranteed lock cycle
            cur.execute("SELECT balance FROM accounts WHERE account_id=%s FOR UPDATE", (second,))
        try:
            db.run_transaction(fn)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=worker, args=("A", 2, 3)), threading.Thread(target=worker, args=("B", 3, 2))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert not errors, errors
    assert sum(attempts.values()) >= 3, f"no retry happened: {attempts}"


@check
def b5c_forced_1213_exhausts_and_other_errors_propagate():
    calls = []

    def dead(cur):
        calls.append(1)
        raise DatabaseError(msg="Deadlock found", errno=1213)
    try:
        db.run_transaction(dead)
        raise AssertionError("no error")
    except ApiError as e:
        assert e.code == "TXN_RETRY_EXHAUSTED" and e.http_status == 503
    assert len(calls) == 3, calls
    calls.clear()

    def other(cur):
        calls.append(1)
        raise DatabaseError(msg="dup", errno=1062)
    try:
        db.run_transaction(other)
    except DatabaseError:
        pass
    assert len(calls) == 1


# ---- B6 helpers -------------------------------------------------------------------------------------------------
@check
def b6_helpers():
    assert parse_money("10") == Decimal("10.00") and str(parse_money(5)) == "5.00" and str(parse_money(10.5)) == "10.50"
    for bad in ("1.234", "-5", "abc", "", None, True, "1e3", -5, [1]):
        try:
            parse_money(bad, field="amount")
            raise AssertionError(f"{bad!r} accepted")
        except ApiError as e:
            assert e.code == "VALIDATION_ERROR" and "amount" in e.details["fields"], bad
    try:
        parse_money("0.50", min_value="1.00")
        raise AssertionError("min ignored")
    except ApiError:
        pass
    assert money_str(Decimal("5")) == "5.00" and add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert mask_name("Bob Singh") == "Bob S." and mask_name("Cher") == "Cher"
    assert iso(None) is None


# ---- B7 HTTP ----------------------------------------------------------------------------------------------------
@check
def b7_http_errors_and_auth():
    from flask import g

    from middleware import get_page_args, require_user
    from responses import ok
    app = create_app()

    @app.get("/api/_boom")
    def _boom():
        return 1 / 0

    @app.get("/api/_getonly")
    def _getonly():
        return ok({})

    @app.get("/api/_me")
    @require_user
    def _me():
        return ok({"uid": g.user_id, "pg": list(get_page_args())})

    @app.post("/api/_money")
    def _money():
        from flask import request
        parse_money(request.get_json()["amount"])

    c = app.test_client()

    def env(resp, status, code):
        j = resp.get_json()
        assert resp.status_code == status and j["success"] is False and j["error"]["code"] == code, (resp.status_code, j)
        assert isinstance(j["error"]["details"], dict) and "message" in j["error"]
        return j
    env(c.get("/api/nope"), 404, "NOT_FOUND")
    env(c.post("/api/nope"), 404, "NOT_FOUND")
    env(c.post("/"), 405, "METHOD_NOT_ALLOWED")
    env(c.post("/api/_getonly"), 405, "METHOD_NOT_ALLOWED")
    body = env(c.get("/api/_boom"), 500, "INTERNAL_ERROR")
    assert "Traceback" not in str(body) and "ZeroDivision" not in str(body)
    env(c.get("/api/_me"), 401, "AUTH_REQUIRED")
    env(c.get("/api/_me", headers={"X-User-Id": "abc"}), 401, "AUTH_REQUIRED")
    env(c.get("/api/_me", headers={"X-User-Id": "1"}), 401, "AUTH_REQUIRED")  # system user
    env(c.get("/api/_me", headers={"X-User-Id": "999"}), 401, "AUTH_REQUIRED")
    r = c.get("/api/_me?page_size=500", headers={"X-User-Id": "2"}).get_json()
    assert r == {"success": True, "data": {"uid": 2, "pg": [1, 50]}}, r
    env(c.get("/api/_me?page=0", headers={"X-User-Id": "2"}), 400, "VALIDATION_ERROR")
    j = env(c.post("/api/_money", json={"amount": "1.234"}), 400, "VALIDATION_ERROR")
    assert "amount" in j["error"]["details"]["fields"]
    env(c.post("/api/_money", data="{bad", content_type="application/json"), 400, "VALIDATION_ERROR")


@check
def b7_simulated_failures_map_to_http():
    from errors import SimulatedNetworkError, SimulatedResponseDropped
    app = create_app()
    app.add_url_rule("/api/_s1", "s1", lambda: (_ for _ in ()).throw(SimulatedNetworkError("AFTER_DEBIT")))
    app.add_url_rule("/api/_s2", "s2", lambda: (_ for _ in ()).throw(SimulatedResponseDropped()))
    c = app.test_client()
    r = c.get("/api/_s1")
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "SIMULATED_NETWORK_FAILURE"
    r = c.get("/api/_s2")
    assert r.status_code == 504 and r.get_json()["error"]["code"] == "NETWORK_TIMEOUT"
    assert "idempotency_key" in r.get_json()["error"]["details"]["hint"]


@check
def b7_error_status_covers_appendix_b():
    from errors import ERROR_STATUS
    design = os.environ.get("DESIGN_MD")
    if not design:
        assert len(ERROR_STATUS) == 21
        return
    rows = re.findall(r"^\| `([A-Z_]+)` \| (\d{3}) \|", open(design, encoding="utf-8").read().split("## Appendix B")[1], re.M)
    assert dict((k, int(v)) for k, v in rows) == ERROR_STATUS


# ---- B8 notify --------------------------------------------------------------------------------------------------
@check
def b8_notifications_transactional():
    try:
        with db.transaction() as cur:
            create_notification(cur, 2, "NOT_A_TYPE", "t", "m")
        raise AssertionError("unknown type accepted")
    except ValueError:
        pass
    ids = []

    def fn(cur):
        ids.append(create_notification(cur, 2, "DEPOSIT", "T" * 150, "M" * 300, related_ref=42))
        cur.execute("SELECT LENGTH(title) a, LENGTH(message) b, related_ref r FROM notifications WHERE notification_id=%s", (ids[0],))
        row = cur.fetchone()
        assert (row["a"], row["b"], row["r"]) == (100, 255, "42"), row
        raise _Rollback
    try:
        db.run_transaction(fn)
    except _Rollback:
        pass
    assert db.fetch_one("SELECT 1 FROM notifications WHERE notification_id=%s", (ids[0],)) is None
    with db.transaction() as cur:
        create_notification(cur, 2, "DEPOSIT", "kept", "kept")
    assert db.fetch_one("SELECT COUNT(*) c FROM notifications")["c"] == 1  # committed one persists
    init_db.reset_database(test_fixtures=True)


print("\nRESULT:", "ALL PASS" if not FAILS else f"FAILED {FAILS}")
sys.exit(1 if FAILS else 0)
