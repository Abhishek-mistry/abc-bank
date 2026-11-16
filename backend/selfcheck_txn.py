"""02llm self-check. Needs the server on :5000 and MySQL. RESETS the DB (leaves it seeded).
Run: python backend/selfcheck_txn.py   (PASS/FAIL per line, exit code 1 on any FAIL)"""
import concurrent.futures as cf
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import requests

import db
import init_db
from services.health_service import integrity_report

API = "http://127.0.0.1:5000/api"
ROOT = Path(__file__).resolve().parent
ALICE, BOB, CAROL = 2, 3, 4                                   # user ids (§12)
AN, BN, CN, SYS = "100000000001", "100000000002", "100000000003", "000000000001"
TXN_KEYS = {"txn_ref", "txn_type", "status", "amount", "from_account_number", "from_name", "to_account_number",
            "to_name", "description", "direction", "failure_code", "failure_reason", "related_txn_ref", "loan_id",
            "created_at", "completed_at"}
RESULTS = []


def ck(name, cond):
    RESULTS.append(bool(cond))
    print("PASS" if cond else "FAIL", name)


def call(method, path, uid=ALICE, body=None, **params):
    r = requests.request(method, API + path, json=body, params=params or None, timeout=60,
                         headers={"X-User-Id": str(uid)} if uid else {})
    j = r.json()
    return r.status_code, j.get("data") or j.get("error")


def xfer(frm=AN, to=BN, amount="100.00", uid=ALICE, **extra):
    return call("POST", "/transactions/transfer", uid,
                {"from_account_number": frm, "to_account_number": to, "amount": amount, **extra})


def dep(amount, acct=AN, uid=ALICE, **extra):
    return call("POST", "/transactions/deposit", uid, {"account_number": acct, "amount": amount, **extra})


def rev(ref, uid=ALICE, **extra):
    return call("POST", f"/transactions/{ref}/reverse", uid, extra)


def count(sql, *p):
    return db.fetch_one("SELECT COUNT(*) AS n " + sql, p)["n"]


def bal(num):
    return db.fetch_one("SELECT balance FROM accounts WHERE account_number = %s", (num,))["balance"]


def par(fn, n):
    with cf.ThreadPoolExecutor(n) as ex:
        return list(ex.map(fn, range(n)))


def integrity(label):
    bad = [k for k, c in integrity_report()["checks"].items() if not c["ok"]]
    ck(f"{label}: integrity I1-I6 {bad or ''}", not bad)


def is_err(res, status, code):
    return (res[0], res[1].get("code")) == (status, code)


def t_grep_gate():
    out = subprocess.run(["grep", "-rn", "--include=*.py", "--exclude=selfcheck_*.py", "--exclude-dir=tests", "UPDATE accounts SET " "balance",
                          str(ROOT)], capture_output=True, text=True).stdout.splitlines()
    print("\n".join("    " + line for line in out))
    ck("B1 grep gate: balance UPDATE only in services/ledger.py (+init_db.py)",
       out and all("services/ledger.py" in ln or "init_db.py" in ln for ln in out))


def t_happy():
    init_db.reset_database(test_fixtures=True)
    s, d = xfer()
    ref = d["transaction"]["txn_ref"]
    rows = db.fetch_all("SELECT a.account_number AS n, e.entry_type AS t, e.balance_after AS b FROM ledger_entries e "
                        "JOIN transactions x ON x.txn_id = e.txn_id JOIN accounts a ON a.account_id = e.account_id "
                        "WHERE x.txn_ref = %s ORDER BY e.entry_id", (ref,))
    ck("B2 201, balances 9900.00 / 5100.00", s == 201 and (bal(AN), bal(BN)) == (D("9900.00"), D("5100.00")))
    ck("B2 exactly DEBIT alice + CREDIT bob with correct balance_after",
       [(r["n"], r["t"], r["b"]) for r in rows] == [(AN, "DEBIT", D("9900.00")), (BN, "CREDIT", D("5100.00"))])
    ck("B2 COMPLETED + SENT/RECEIVED notifications",
       d["transaction"]["status"] == "COMPLETED"
       and count("FROM notifications WHERE related_ref = %s AND type IN ('TRANSFER_SENT','TRANSFER_RECEIVED')", ref) == 2)
    ck("B2 response shape (§7.3)", set(d) == {"transaction", "from_account", "idempotent_replay"}
       and set(d["transaction"]) == TXN_KEYS and d["from_account"] == {"account_number": AN, "balance": "9900.00"}
       and d["transaction"]["amount"] == "100.00" and d["transaction"]["direction"] == "OUT"
       and d["idempotent_replay"] is False)
    integrity("B2")


def t_failures():
    for mode in ("BEFORE_DEBIT", "AFTER_DEBIT", "BEFORE_COMMIT"):
        init_db.reset_database(test_fixtures=True)
        n0 = count("FROM ledger_entries")
        sr = "FROM notifications WHERE type IN ('TRANSFER_SENT','TRANSFER_RECEIVED')"
        sr0 = count(sr)
        r = xfer(simulate_failure=mode)
        ck(f"B3 {mode}: 503 SIMULATED_NETWORK_FAILURE", is_err(r, 503, "SIMULATED_NETWORK_FAILURE"))
        ck(f"B3 {mode}: balances + ledger unchanged",
           (bal(AN), bal(BN), count("FROM ledger_entries")) == (D("10000.00"), D("5000.00"), n0))
        ck(f"B3 {mode}: FAILED row (key NULL), TRANSFER_FAILED, no SENT/RECEIVED",
           count("FROM transactions WHERE status = 'FAILED' AND idempotency_key IS NULL") == 1
           and count("FROM notifications WHERE type = 'TRANSFER_FAILED' AND user_id = %s", ALICE) == 1
           and count(sr) == sr0)
        integrity(f"B3 {mode}")


def t_drop():
    init_db.reset_database(test_fixtures=True)
    k = uuid.uuid4().hex
    r = xfer(idempotency_key=k, simulate_failure="DROP_RESPONSE")
    ck("B4 504 NETWORK_TIMEOUT and money moved once", is_err(r, 504, "NETWORK_TIMEOUT") and bal(AN) == D("9900.00"))
    s, d = xfer(idempotency_key=k)
    ck("B4 retry -> 200 replay, balances unchanged, one COMPLETED txn",
       (s, d["idempotent_replay"]) == (200, True) and (bal(AN), bal(BN)) == (D("9900.00"), D("5100.00"))
       and count("FROM transactions WHERE idempotency_key = %s AND status = 'COMPLETED'", k) == 1)
    integrity("B4")


def t_idempotency():
    init_db.reset_database(test_fixtures=True)
    k = uuid.uuid4().hex
    (s1, _), (s2, d2) = xfer(idempotency_key=k), xfer(idempotency_key=k)
    ck("B5 same key twice sequentially -> 201 then 200 replay", (s1, s2, d2["idempotent_replay"]) == (201, 200, True))
    init_db.reset_database(test_fixtures=True)
    k = uuid.uuid4().hex
    res = par(lambda _: xfer(idempotency_key=k), 10)
    ck("B5 10 concurrent same key -> exactly one debit",
       sorted(s for s, _ in res) == [200] * 9 + [201] and bal(AN) == D("9900.00")
       and count("FROM transactions WHERE idempotency_key = %s", k) == 1)
    integrity("B5 concurrent")
    k = uuid.uuid4().hex
    (s1, _), (s2, d) = xfer(idempotency_key=k, simulate_failure="BEFORE_DEBIT"), xfer(idempotency_key=k)
    ck("B5 retry after FAILED with same key succeeds normally", (s1, s2, d["idempotent_replay"]) == (503, 201, False))


def t_business():
    init_db.reset_database(test_fixtures=True)
    cases = [("foreign sender", dict(frm=BN), 403, "FORBIDDEN"),
             ("same account", dict(to=AN), 422, "SAME_ACCOUNT_TRANSFER"),
             ("unknown sender", dict(frm="199999999999"), 404, "ACCOUNT_NOT_FOUND"),
             ("unknown recipient", dict(to="199999999999"), 404, "ACCOUNT_NOT_FOUND"),
             ("note of 101 chars", dict(note="x" * 101), 400, "VALIDATION_ERROR"),
             ] + [(f"amount {a!r}", dict(amount=a), 400, "VALIDATION_ERROR")
                  for a in ("0", "-1", "1.999", "abc", "200000.01")]
    for name, kw, status, code in cases:
        ck(f"B6 {name} -> {status} {code}", is_err(xfer(**kw), status, code))
    s, e = xfer(amount="99999.00")
    ck("B6 insufficient funds + details", (s, e["code"], e["details"]) ==
       (422, "INSUFFICIENT_FUNDS", {"available": "10000.00", "required": "99999.00"}))
    ck("B6 unknown recipient FAILED (to NULL); unknown sender left no row",
       count("FROM transactions WHERE status = 'FAILED' AND failure_code = 'ACCOUNT_NOT_FOUND'") == 1
       and count("FROM transactions WHERE status = 'FAILED' AND failure_code = 'ACCOUNT_NOT_FOUND' "
                 "AND to_account_id IS NULL") == 1)
    for name, who, status in (("frozen sender", AN, "FROZEN"), ("frozen recipient", BN, "FROZEN"),
                              ("closed recipient", BN, "CLOSED")):
        db.execute("UPDATE accounts SET status = %s WHERE account_number = %s", (status, who))
        ck(f"B6 {name} -> 422 ACCOUNT_NOT_ACTIVE", is_err(xfer(), 422, "ACCOUNT_NOT_ACTIVE"))
        db.execute("UPDATE accounts SET status = 'ACTIVE' WHERE account_number = %s", (who,))
    ck("B6 missing fields -> 400", is_err(call("POST", "/transactions/transfer", ALICE, {}), 400, "VALIDATION_ERROR"))
    ck("B6 missing header -> 401", is_err(xfer(uid=None), 401, "AUTH_REQUIRED"))
    integrity("B6")


def t_concurrency():
    init_db.reset_database(test_fixtures=True)
    res = par(lambda _: xfer(amount="10.00"), 20)
    ck("B7a 20 x 10.00 alice->bob: all 201, exact balances",
       all(s == 201 for s, _ in res) and (bal(AN), bal(BN)) == (D("9800.00"), D("5200.00")))
    integrity("B7a")
    init_db.reset_database(test_fixtures=True)
    res = par(lambda i: xfer(AN, BN, "10.00") if i % 2 else xfer(BN, AN, "10.00", uid=BOB), 40)
    ck("B7b 40 opposing transfers: all 201 (no TXN_RETRY_EXHAUSTED), net zero",
       all(s == 201 for s, _ in res) and (bal(AN), bal(BN)) == (D("10000.00"), D("5000.00")))
    integrity("B7b")
    init_db.reset_database(test_fixtures=True)
    res = par(lambda _: xfer(amount="700.00"), 30)
    wins = sum(s == 201 for s, _ in res)
    ck("B7c 30 overdraw attempts: never negative, successes x amount == balance drop",
       all(s in (201, 422) for s, _ in res) and bal(AN) >= 0 and wins * D("700.00") == D("10000.00") - bal(AN))
    integrity("B7c")


def t_reversal():
    init_db.reset_database(test_fixtures=True)
    ref = xfer()[1]["transaction"]["txn_ref"]
    s, d = rev(ref)
    ck("B8 reversal 201, REVERSAL txn linked, original REVERSED",
       s == 201 and d["transaction"]["txn_type"] == "REVERSAL" and d["transaction"]["related_txn_ref"] == ref
       and d["original"]["status"] == "REVERSED")
    ck("B8 balances restored, both parties notified",
       (bal(AN), bal(BN)) == (D("10000.00"), D("5000.00"))
       and count("FROM notifications WHERE type = 'TRANSFER_REVERSED' AND related_ref = %s",
                 d["transaction"]["txn_ref"]) == 2)
    ck("B8 second reversal -> TXN_NOT_REVERSIBLE", is_err(rev(ref), 422, "TXN_NOT_REVERSIBLE"))
    integrity("B8 happy")
    init_db.reset_database(test_fixtures=True)
    ref = xfer()[1]["transaction"]["txn_ref"]
    xfer(BN, CN, "5100.00", uid=BOB)  # recipient spends everything first
    ck("B8 recipient spent it -> REVERSAL_FUNDS_UNAVAILABLE, nothing changed",
       is_err(rev(ref), 422, "REVERSAL_FUNDS_UNAVAILABLE") and (bal(AN), bal(BN)) == (D("9900.00"), D("0.00"))
       and count("FROM transactions WHERE txn_type = 'REVERSAL' AND status = 'COMPLETED'") == 0)
    ck("B8 someone else's transfer -> 403 FORBIDDEN", is_err(rev(ref, CAROL), 403, "FORBIDDEN"))
    ck("B8 reversing a DEPOSIT -> TXN_NOT_REVERSIBLE",
       is_err(rev(dep("50.00")[1]["transaction"]["txn_ref"]), 422, "TXN_NOT_REVERSIBLE"))
    integrity("B8 rejected")
    for mode in ("BEFORE_DEBIT", "AFTER_DEBIT", "BEFORE_COMMIT"):
        init_db.reset_database(test_fixtures=True)
        ref = xfer()[1]["transaction"]["txn_ref"]
        ck(f"B8 reversal {mode}: 503 + full rollback",
           is_err(rev(ref, simulate_failure=mode), 503, "SIMULATED_NETWORK_FAILURE")
           and (bal(AN), bal(BN)) == (D("9900.00"), D("5100.00"))
           and count("FROM transactions WHERE txn_ref = %s AND status = 'COMPLETED'", ref) == 1)
        integrity(f"B8 reversal {mode}")


def t_deposit():
    init_db.reset_database(test_fixtures=True)
    s, d = dep("500.00")
    ck("B9 deposit 201, alice +500, system -500", s == 201 and set(d) == {"transaction", "account", "idempotent_replay"}
       and bal(AN) == D("10500.00") and bal(SYS) == D("-40500.00"))
    integrity("B9")
    for a in ("0.99", "100000.01"):
        ck(f"B9 amount {a} rejected", is_err(dep(a), 400, "VALIDATION_ERROR"))
    ck("B9 foreign account -> 403", is_err(dep("5.00", acct=BN), 403, "FORBIDDEN"))


def t_history():
    init_db.reset_database(test_fixtures=True)
    for a in ("10.00", "20.00", "30.00"):
        xfer(amount=a)
    xfer(simulate_failure="BEFORE_DEBIT")
    dep("5.00")
    lst = lambda uid=ALICE, **p: call("GET", "/transactions", uid, **p)[1]  # noqa: E731
    newest = [r["txn_ref"] for r in db.fetch_all("SELECT txn_ref FROM transactions ORDER BY txn_id DESC LIMIT 2")]
    d = lst(page_size=2)
    ck("B10 pagination totals + newest first", (d["total_items"], d["total_pages"], d["page_size"]) == (7, 4, 2)
       and [i["txn_ref"] for i in d["items"]] == newest)
    ck("B10 filters type / status / account_id",
       lst(type="DEPOSIT")["total_items"] == 2 and lst(type="TRANSFER")["total_items"] == 5
       and lst(status="FAILED")["total_items"] == 1 and lst(account_id=2)["total_items"] == 7
       and is_err(call("GET", "/transactions", ALICE, account_id=3), 403, "FORBIDDEN"))
    today = datetime.now(timezone.utc).date()
    ck("B10 date range inclusive", lst(from_date=str(today), to_date=str(today))["total_items"] == 7
       and lst(to_date=str(today - timedelta(days=1)))["total_items"] == 0)
    ck("B10 direction (alice OUT/IN, bob IN) + FAILED visible",
       {(i["txn_type"], i["direction"]) for i in lst(page_size=50)["items"]} == {("TRANSFER", "OUT"), ("DEPOSIT", "IN")}
       and all(i["direction"] == "IN" for i in lst(BOB, page_size=50)["items"])
       and any(i["status"] == "FAILED" for i in lst(page_size=50)["items"]))
    s, det = call("GET", f"/transactions/{newest[0]}")
    ck("B10 detail shape + FORBIDDEN + NOT_FOUND", set(det) == {"transaction", "ledger_entries"}
       and len(det["ledger_entries"]) == 2 and is_err(call("GET", f"/transactions/{newest[0]}", CAROL), 403, "FORBIDDEN")
       and is_err(call("GET", "/transactions/" + "0" * 36), 404, "NOT_FOUND"))


def t_lock_order():
    led = (ROOT / "services" / "ledger.py").read_text()
    svc = (ROOT / "services" / "transfer_service.py").read_text()
    ck("B11 move_money: exactly ONE ordered SELECT ... FOR UPDATE",
       led.count("FOR UPDATE") == 1 and "ORDER BY account_id FOR UPDATE" in led)
    ck("B11 reverse locks the original txn row before move_money",
       0 <= svc.index("FOR UPDATE OF t") < svc.rindex("move_money("))


if __name__ == "__main__":
    for t in (t_grep_gate, t_happy, t_failures, t_drop, t_idempotency, t_business, t_concurrency, t_reversal,
              t_deposit, t_history, t_lock_order):
        try:
            t()
        except Exception as e:  # a crashed check is a FAIL, keep going
            ck(f"{t.__name__} crashed: {e!r}", False)
    init_db.reset_database(test_fixtures=True)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    sys.exit(0 if all(RESULTS) else 1)
